#!/usr/bin/env python3
"""헤드리스 Chromium 자동 검증 (Playwright).

사용:
    python3 verify/verify.py [--shots <스크린샷 저장 폴더>]

검사 항목: 초기 빈 캔버스, 0~9 프리셋 Max/Avg 10/10, 커널·ReLU·풀링·그리기,
단계 이동, 4단계 자동 정지, 설명 보드(이진 vs 다중 · MNIST 비교표), 실시간 수식 바,
애니메이션 규칙(cubic-bezier·keyframes·FC 스트로크 펄스), 1440/1024/900/390px 레이아웃
(1024·900px 한 줄 4열 좌→우 + 카드 사이 화살표, 390px 세로 스택), JS 콘솔 에러 0건.
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "index.html"
REPORT = Path(__file__).resolve().parent / "verify-report.json"
SHOTS = Path(sys.argv[sys.argv.index("--shots") + 1]) if "--shots" in sys.argv else None

report = {"target": str(TARGET), "checks": [], "console_errors": [], "page_errors": [], "presets": {}}


def chk(name, ok, detail=""):
    report["checks"].append({"check": name, "ok": bool(ok), "detail": str(detail)})
    print(("PASS " if ok else "FAIL ") + name + ((" — " + str(detail)) if detail else ""))


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: report["console_errors"].append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
    page.goto(TARGET.as_uri())
    page.wait_for_timeout(900)

    # --- 1. 첫 화면: 빈 캔버스 + 후행 예시 패널 ---------------------------------
    filled = page.eval_on_selector_all("#inputGrid8x8 .px-cell", "els => els.filter(e => e.classList.contains('on')).length")
    chk("초기 로드 시 빈 캔버스 (0칸)", filled == 0, f"filled={filled}")
    chk("초기 안내 문구", "그려 보세요" in page.inner_text("#canvasGuideBanner"), page.inner_text("#canvasGuideBanner"))
    chk("예시 프리셋 패널 초기 접힘", page.get_attribute("#btnTogglePresets", "aria-expanded") == "false",
        page.inner_text("#btnTogglePresets"))
    chk("빈 상태 최종 판별 비움", page.inner_text("#predDigitDisplay").strip() == "—", page.inner_text("#predDigitDisplay"))
    page.click("#btnTogglePresets")
    page.wait_for_timeout(300)
    chk("대표 숫자 예시 토글 열림", page.get_attribute("#btnTogglePresets", "aria-expanded") == "true",
        page.inner_text("#btnTogglePresets"))

    # --- 2. 0~9 프리셋 전수 (Max / Avg) ----------------------------------------
    def read_pred():
        return page.inner_text("#predDigitDisplay").strip(), page.inner_text("#predProbDisplay").strip()

    def run_presets(label):
        res = {}
        for d in range(10):
            page.click(f"#digitPresetContainer button:nth-child({d + 1})")
            page.wait_for_timeout(140)
            res[d] = {"pred": read_pred()[0], "prob": read_pred()[1]}
        ok = all(str(d) == res[d]["pred"] for d in range(10))
        chk(f"{label}: 0~9 프리셋 1순위 정답", ok,
            " ".join(f"{d}->{res[d]['pred']}({res[d]['prob']})" for d in range(10)))
        return res

    report["presets"]["max"] = run_presets("Max 풀링")
    page.click("#btnPoolAvg"); page.wait_for_timeout(350)
    report["presets"]["avg"] = run_presets("Avg 풀링")
    page.click("#btnPoolMax"); page.wait_for_timeout(350)
    chk("정확도 배지 10/10", "10/10" in page.inner_text("#accuracyBadge"), page.inner_text("#accuracyBadge"))

    page.click("#digitPresetContainer button:nth-child(4)")  # 숫자 3
    page.wait_for_timeout(200)
    chk("확률 목록 10행", page.eval_on_selector_all("#probList > *", "els => els.length") == 10)
    chk("숫자 3 예측", read_pred()[0] == "3", read_pred())

    # --- 3. 합성곱·풀링 상호작용 ------------------------------------------------
    fm = page.query_selector_all("#featureMap6x6 > *")
    chk("특징 맵 36칸", len(fm) == 36, len(fm))
    fm[14].hover(); page.wait_for_timeout(250)
    formula = page.inner_text("#dotFormulaText")
    chk("특징맵 호버 내적 수식", "=" in formula and "·" in formula, formula[:90])
    chk("수용 영역 9칸 하이라이트",
        page.eval_on_selector_all("#inputGrid8x8 .receptive-highlight", "els => els.length") == 9)
    chk("슬라이딩 커널 창 오버레이 표시", "is-visible" in (page.get_attribute("#receptiveSlider", "class") or ""),
        page.get_attribute("#receptiveSlider", "class"))

    before = page.inner_text("#probList")
    kernels = page.query_selector_all("#kernelGrid3x3 input")
    chk("커널 입력 9칸", len(kernels) == 9, len(kernels))
    kernels[4].fill("2"); kernels[4].dispatch_event("change"); page.wait_for_timeout(350)
    chk("커널 수정 → 확률 재계산", before != page.inner_text("#probList"))
    kernels[4].fill("4"); kernels[4].dispatch_event("change"); page.wait_for_timeout(350)
    chk("커널 프리셋 5종", len(page.query_selector_all("#kernelPresetContainer button")) == 5)
    relu = page.query_selector("#chkRelu")
    relu.uncheck(); page.wait_for_timeout(300)
    relu.check(); page.wait_for_timeout(300)
    chk("ReLU 토글 후 10/10 유지", "10/10" in page.inner_text("#accuracyBadge"), page.inner_text("#accuracyBadge"))
    chk("ReLU 후 숫자 3 유지", read_pred()[0] == "3", read_pred())

    # --- 4. 그리기 / 지우개 / 전체 지우기 / 픽셀 수치 ---------------------------
    cells = page.query_selector_all("#inputGrid8x8 .px-cell")
    chk("입력 그리드 64칸", len(cells) == 64, len(cells))
    page.click("#btnClearGrid"); page.wait_for_timeout(250)
    chk("전체 지우기 → 0칸 + 판별 비움",
        page.eval_on_selector_all("#inputGrid8x8 .px-cell", "els => els.filter(e => e.classList.contains('on')).length") == 0
        and page.inner_text("#predDigitDisplay").strip() == "—")
    box = cells[27].bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + 45, box["y"] + box["height"] / 2 + 8, steps=8)
    page.mouse.up(); page.wait_for_timeout(300)
    filled = page.eval_on_selector_all("#inputGrid8x8 .px-cell", "els => els.filter(e => e.classList.contains('on')).length")
    chk("드래그 그리기 → 채워짐", filled > 0, filled)
    page.click("#btnToolErase"); page.wait_for_timeout(150)
    before_e = filled
    box = cells[27].bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down(); page.mouse.up(); page.wait_for_timeout(250)
    after_e = page.eval_on_selector_all("#inputGrid8x8 .px-cell", "els => els.filter(e => e.classList.contains('on')).length")
    chk("지우개 → 칸 감소", after_e < before_e, f"{before_e}->{after_e}")
    page.click("#btnToolDraw")
    page.click("#btnTogglePixelVal"); page.wait_for_timeout(200)
    chk("픽셀 수치 토글", "ON" in page.inner_text("#btnTogglePixelVal"), page.inner_text("#btnTogglePixelVal"))
    page.click("#btnTogglePixelVal")

    # --- 5. 단계 이동 · 자동 재생 정지 -----------------------------------------
    page.click("#btnReset"); page.wait_for_timeout(400)
    chk("초기화 → 빈 캔버스 · 1단계",
        page.eval_on_selector_all("#inputGrid8x8 .px-cell", "els => els.filter(e => e.classList.contains('on')).length") == 0
        and page.inner_text("#stepIndicator").strip() == "1 / 4")
    page.click("#btnNextStep"); page.wait_for_timeout(300)
    s2 = page.inner_text("#stepIndicator").strip()
    page.click("#btnNextStep"); page.wait_for_timeout(300)
    s3 = page.inner_text("#stepIndicator").strip()
    page.click("#btnPrevStep"); page.wait_for_timeout(300)
    s2b = page.inner_text("#stepIndicator").strip()
    chk("단계 이동 1→2→3→2", (s2, s3, s2b) == ("2 / 4", "3 / 4", "2 / 4"), f"{s2} {s3} {s2b}")

    page.click("#btnReset"); page.wait_for_timeout(300)
    slider = page.query_selector("#speedSlider")
    slider.fill("3"); slider.dispatch_event("input"); page.wait_for_timeout(200)
    chk("속도 3.0×", "3.0" in page.inner_text("#speedValue"), page.inner_text("#speedValue"))
    page.click("#btnPlayPause"); page.wait_for_timeout(700)
    playing = page.inner_text("#btnPlayPause")
    page.wait_for_timeout(4500)
    step_play = page.inner_text("#stepIndicator").strip()
    ended = page.inner_text("#btnPlayPause")
    chk("재생 중 정지 라벨", "정지" in playing, playing)
    chk("재생 → 4단계 도달", step_play == "4 / 4", step_play)
    chk("재생 완료 후 자동 정지", "정지" not in ended, ended)
    t1 = page.inner_text("#stepIndicator")
    page.wait_for_timeout(1500)
    chk("정지 후 단계 고정 (무한 루프 없음)", t1 == page.inner_text("#stepIndicator") == "4 / 4")
    chk("빈 캔버스 시연 시 데모 숫자 3 로드", page.inner_text("#predDigitDisplay").strip() == "3")

    # --- 6. 설명 보드 -----------------------------------------------------------
    chk("설명 보드 탭 2개", len(page.query_selector_all("#tabAlgo, #tabMnist")) == 2)
    page.click("#tabMnist"); page.wait_for_timeout(300)
    mnist_text = page.inner_text("#eduBoardBody")
    chk("MNIST 비교표 (28×28 · 784 · 60,000)",
        all(k in mnist_text for k in ("MNIST", "28 × 28", "784", "60,000")), mnist_text[:60])
    chk("비교표 7행 이상", page.eval_on_selector_all("#eduBoardBody table tr", "els => els.length") >= 7)
    page.click("#tabAlgo"); page.wait_for_timeout(300)
    algo = page.inner_text("#eduBoardBody")
    chk("이진(시그모이드) vs 다중(소프트맥스) 설명", "시그모이드" in algo and "소프트맥스" in algo, algo[:60])
    page.click("#btnToggleEduBoard"); page.wait_for_timeout(250)
    chk("설명 보드 접기", page.get_attribute("#btnToggleEduBoard", "aria-expanded") == "false")
    page.click("#btnToggleEduBoard"); page.wait_for_timeout(250)

    f1, f2 = page.inner_text("#bottomLogitExpr"), page.inner_text("#bottomSoftmaxExpr")
    chk("하단 실시간 수식 바", "z" in f1 and "exp" in f2, f"{f1[:40]} | {f2[:40]}")

    # --- 7. 애니메이션 규칙 -----------------------------------------------------
    anim = page.evaluate("""() => {
      const bar = document.querySelector('#probList .prob-bar-fill');
      const cs = bar ? getComputedStyle(bar) : null;
      const sheet = [...document.styleSheets].map(s => { try { return [...s.cssRules].map(r => r.cssText).join('\\n'); } catch (e) { return ''; } }).join('\\n');
      return {
        barTransition: cs ? cs.transition : '',
        keyframes: (sheet.match(/@keyframes/g) || []).length,
        pulse: /fc-line-pulse|fcPulse/.test(sheet),
        bezier: /cubic-bezier/.test(sheet),
        arrows: document.querySelectorAll('.flow-arrow').length
      };
    }""")
    chk("확률 막대 cubic-bezier 전환", "cubic-bezier" in anim["barTransition"], anim["barTransition"])
    chk("@keyframes 애니메이션 정의", anim["keyframes"] > 0, anim["keyframes"])
    chk("FC 연결선 스트로크 펄스", anim["pulse"], anim["pulse"])
    chk("흐름 화살표 3개", anim["arrows"] == 3, anim["arrows"])

    # --- 8. 레이아웃 ------------------------------------------------------------
    page.click("#btnReset"); page.wait_for_timeout(300)

    def layout(width, height, name):
        page.set_viewport_size({"width": width, "height": height}); page.wait_for_timeout(450)
        page.evaluate("window.scrollTo(0,0)"); page.wait_for_timeout(150)
        info = page.evaluate("""() => {
          const cards = [1, 2, 3, 4].map(i => { const r = document.getElementById('stageCard' + i).getBoundingClientRect(); return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width)}; });
          const arrows = [12, 23, 34].map(n => { const el = document.getElementById('flowArrow' + n); const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return {x: Math.round(r.x), w: Math.round(r.width), visible: cs.display !== 'none' && r.width > 0}; });
          return {cards, arrows, overflow: document.documentElement.scrollWidth - window.innerWidth};
        }""")
        same_row = len({c["y"] for c in info["cards"]}) == 1
        left_to_right = all(info["cards"][i]["x"] < info["cards"][i + 1]["x"] for i in range(3))
        if width >= 840:
            chk(f"{width}px: Stage 1~4 한 줄 4열 좌→우", same_row and left_to_right, json.dumps([c['x'] for c in info['cards']]))
            chk(f"{width}px: 카드 사이 화살표", all(a["visible"] for a in info["arrows"]),
                json.dumps([a["x"] for a in info["arrows"]]))
        else:
            chk(f"{width}px: 세로 스택", all(info["cards"][i]["y"] < info["cards"][i + 1]["y"] for i in range(3)),
                json.dumps([c["y"] for c in info["cards"]]))
        chk(f"{width}px: 가로 넘침 없음", info["overflow"] <= 1, info["overflow"])
        if SHOTS:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)

    layout(1440, 900, "layout-1440")
    layout(1024, 768, "layout-1024")
    layout(900, 800, "layout-900")
    layout(390, 844, "layout-390")

    errors = [e for e in report["console_errors"] if e.startswith("error")]
    chk("JS 콘솔 에러 0건", len(errors) == 0 and len(report["page_errors"]) == 0,
        f"{errors[:2]} {report['page_errors'][:2]}")
    browser.close()

report["summary"] = {
    "passed": sum(1 for c in report["checks"] if c["ok"]),
    "failed": sum(1 for c in report["checks"] if not c["ok"]),
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n== summary:", report["summary"])
for c in report["checks"]:
    if not c["ok"]:
        print("FAILED:", c["check"], "|", c["detail"][:300])
