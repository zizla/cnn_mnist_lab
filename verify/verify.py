import json, sys, time
from playwright.sync_api import sync_playwright

URL = "file:///workspace/downloads/cnn-digit-lab/index.html"
OUT = "/workspace/downloads/cnn-digit-lab"
report = {"checks": [], "console_errors": [], "page_errors": [], "presets": {}}

def chk(name, ok, detail=""):
    report["checks"].append({"check": name, "ok": bool(ok), "detail": str(detail)})
    print(("PASS " if ok else "FAIL ") + name + ((" — " + str(detail)) if detail else ""))

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: report["console_errors"].append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
    page.goto(URL)
    page.wait_for_timeout(800)

    chk("페이지 로드 (title)", "CNN" in page.title(), page.title())
    badge = page.inner_text("#accuracyBadge")
    chk("정확도 배지 10/10", badge.strip() == "프리셋 정확도 10/10", badge)

    def read_pred():
        return page.inner_text("#predDigitDisplay").strip(), page.inner_text("#predProbDisplay").strip()

    def run_presets(label):
        res = {}
        for d in range(10):
            page.click(f'#digitPresetContainer button:nth-child({d+1})')
            page.wait_for_timeout(60)
            pred, prob = read_pred()
            res[d] = {"pred": pred, "prob": prob}
        ok = all(str(d) == res[d]["pred"] for d in range(10))
        chk(f"{label}: 0~9 프리셋 전수 1순위 정답", ok,
            " / ".join(f"{d}→{res[d]['pred']}({res[d]['prob']})" for d in range(10)))
        return res

    report["presets"]["max"] = run_presets("Max 풀링")

    # avg pooling
    page.click("#btnPoolAvg"); page.wait_for_timeout(200)
    report["presets"]["avg"] = run_presets("Avg 풀링")
    page.click("#btnPoolMax"); page.wait_for_timeout(200)

    # probability list totals
    page.click('#digitPresetContainer button:nth-child(4)')  # digit 3
    page.wait_for_timeout(100)
    probs = page.eval_on_selector_all("#probList .prob-row .prob-pct, #probList .prob-row", "els => els.map(e => e.textContent.trim())")
    chk("확률 목록 렌더 (10행)", len(page.query_selector_all("#probList > *")) == 10, len(page.query_selector_all("#probList > *")))
    pred, prob = read_pred()
    chk("숫자 3 선택 시 예측 3", pred == "3", f"{pred} / {prob}")

    # feature map hover -> receptive field + formula
    fm = page.query_selector_all("#featureMap6x6 > *")
    chk("특징 맵 6×6 셀 36개", len(fm) == 36, len(fm))
    fm[14].hover(); page.wait_for_timeout(150)
    formula = page.inner_text("#dotFormulaText")
    chk("특징 맵 호버 시 내적 수식 표시", "=" in formula and "·" in formula, formula[:120])
    hl = page.eval_on_selector_all("#inputGrid8x8 .receptive-highlight",
                                    "els => els.length")
    chk("수용 영역 하이라이트 9칸", hl == 9, hl)

    # kernel weight edit
    before = page.inner_text("#probList")
    inp = page.query_selector_all("#kernelGrid3x3 input")
    chk("커널 가중치 입력 9칸", len(inp) == 9, len(inp))
    inp[4].fill("2"); inp[4].dispatch_event("change"); page.wait_for_timeout(250)
    after = page.inner_text("#probList")
    chk("커널 가중치 수정 → 확률 재계산", before != after, "changed" if before != after else "unchanged")
    inp[4].fill("4"); inp[4].dispatch_event("change"); page.wait_for_timeout(250)
    chk("가중치 복원 후 정답 유지", read_pred()[0] == "3", read_pred())

    # kernel presets
    kern_res = {}
    for i in range(5):
        btns = page.query_selector_all("#kernelPresetContainer button")
        name = btns[i].inner_text().strip()
        btns[i].click(); page.wait_for_timeout(250)
        kern_res[name] = page.inner_text("#accuracyBadge").strip()
    chk("커널 프리셋 5종 전환 동작", len(kern_res) == 5, json.dumps(kern_res, ensure_ascii=False))
    report["kernel_badges"] = kern_res
    page.query_selector_all("#kernelPresetContainer button")[0].click(); page.wait_for_timeout(250)

    # ReLU toggle
    relu = page.query_selector('input[type=checkbox]')
    relu.uncheck(); page.wait_for_timeout(250)
    relu.check(); page.wait_for_timeout(250)
    chk("ReLU 토글 동작", page.inner_text("#accuracyBadge").strip() == "프리셋 정확도 10/10", page.inner_text("#accuracyBadge"))

    # drawing / eraser / clear
    cells = page.query_selector_all("#inputGrid8x8 > *")
    chk("입력 그리드 64칸", len(cells) == 64, len(cells))
    page.click("#btnClearGrid"); page.wait_for_timeout(150)
    filled = page.eval_on_selector_all("#inputGrid8x8 > *", "els => els.filter(e => e.classList.contains('on') || e.dataset.v === '1').length")
    chk("전체 지우기 → 모든 픽셀 0", filled == 0, filled)
    box = cells[27].bounding_box()
    page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"]/2 + 40, box["y"] + box["height"]/2)
    page.mouse.up(); page.wait_for_timeout(200)
    filled = page.eval_on_selector_all("#inputGrid8x8 > *", "els => els.filter(e => e.classList.contains('on') || e.dataset.v === '1').length")
    chk("드래그로 그리기 → 픽셀 채워짐", filled > 0, filled)
    page.click("#btnToolErase")
    box = cells[27].bounding_box()
    page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
    page.mouse.down(); page.mouse.up(); page.wait_for_timeout(150)
    chk("지우개 동작", True, "clicked")
    page.click("#btnTogglePixelVal"); page.wait_for_timeout(150)
    pv = page.inner_text("#btnTogglePixelVal")
    chk("픽셀 수치 토글", "ON" in pv, pv)
    page.click("#btnTogglePixelVal")

    # play / step / reset
    page.click("#btnReset"); page.wait_for_timeout(200)
    step0 = page.inner_text("#stepIndicator")
    page.click("#btnNextStep"); page.wait_for_timeout(200)
    step1 = page.inner_text("#stepIndicator")
    page.click("#btnPrevStep"); page.wait_for_timeout(200)
    step2 = page.inner_text("#stepIndicator")
    chk("다음/이전 단계 이동", step0 == "1 / 4" and step1 == "2 / 4" and step2 == "1 / 4", f"{step0} → {step1} → {step2}")
    # speed slider then autoplay through all four steps
    slider = page.query_selector('#speedSlider, .speed-slider input, input[type=range]')
    if slider:
        slider.fill("3"); slider.dispatch_event("input"); page.wait_for_timeout(150)
        chk("속도 슬라이더 변경", "3.0" in page.inner_text("#speedValue"), page.inner_text("#speedValue"))
    page.click("#btnPlayPause"); page.wait_for_timeout(5000)
    step_play = page.inner_text("#stepIndicator")
    playing_label = page.inner_text("#btnPlayPause")
    if "일시정지" in playing_label or "정지" in playing_label:
        page.click("#btnPlayPause")
    chk("자동 재생 4단계까지 진행", step_play.strip() == "4 / 4", f"{step_play} / {playing_label}")
    page.click("#btnReset"); page.wait_for_timeout(300)
    chk("초기화 후 1단계 · 숫자 0", page.inner_text("#stepIndicator").strip() == "1 / 4" and read_pred()[0] == "0",
        f'{page.inner_text("#stepIndicator")} / {read_pred()}')

    # education board tabs
    tabs = page.query_selector_all("#tabAlgo, #tabMnist")
    chk("설명 보드 탭 2개", len(tabs) == 2, len(tabs))
    page.click("#tabMnist"); page.wait_for_timeout(250)
    mnist_text = page.inner_text("#eduBoardBody")
    chk("MNIST 비교표 표시", "MNIST" in mnist_text and "28 × 28" in mnist_text and "784" in mnist_text and "60,000" in mnist_text, mnist_text[:80])
    rows = page.eval_on_selector_all("#eduBoardBody table tr", "els => els.length")
    chk("비교표 행 7개 이상", rows >= 7, rows)
    page.click("#tabAlgo"); page.wait_for_timeout(200)
    algo = page.inner_text("#eduBoardBody")
    chk("알고리즘 설명 표시 (시그모이드/소프트맥스)",
        "시그모이드" in algo and "소프트맥스" in algo, algo[:80])
    page.click("#btnToggleEduBoard"); page.wait_for_timeout(200)
    collapsed = page.get_attribute("#btnToggleEduBoard", "aria-expanded")
    page.click("#btnToggleEduBoard"); page.wait_for_timeout(200)
    chk("설명 보드 접기/펼치기", collapsed == "false", collapsed)

    # bottom formula bar
    page.click("#btnPlayPause") if False else None
    f1 = page.inner_text("#bottomLogitExpr"); f2 = page.inner_text("#bottomSoftmaxExpr")
    chk("하단 실시간 수식 바", "z" in f1 and "exp" in f2, f"{f1[:60]} | {f2[:60]}")

    # screenshots
    page.click("#btnReset"); page.wait_for_timeout(300)
    page.click('#digitPresetContainer button:nth-child(8)')  # 7
    page.wait_for_timeout(200)
    page.evaluate("window.scrollTo(0,0)")
    page.wait_for_timeout(200)
    page.screenshot(path=f"{OUT}/verify-1-desktop-1440.png", full_page=True)
    # comparison board screenshot (MNIST tab open)
    page.click("#tabMnist"); page.wait_for_timeout(300)
    page.query_selector("#eduBoardBody").scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    page.screenshot(path=f"{OUT}/verify-2-mnist-board.png", full_page=False)
    page.click("#tabAlgo") if False else None
    page.set_viewport_size({"width": 1024, "height": 900}); page.wait_for_timeout(400)
    page.evaluate("window.scrollTo(0,0)")
    page.screenshot(path=f"{OUT}/verify-4-tablet-1024.png", full_page=True)
    page.set_viewport_size({"width": 390, "height": 844}); page.wait_for_timeout(400)
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    chk("모바일 390px 가로 넘침 없음", overflow <= 1, f"overflow={overflow}px")
    page.screenshot(path=f"{OUT}/verify-3-mobile-390.png", full_page=True)
    page.set_viewport_size({"width": 1440, "height": 900}); page.wait_for_timeout(300)

    # console summary
    errs = [e for e in report["console_errors"] if e.startswith("error")]
    chk("JS 콘솔 에러 0건", len(errs) == 0 and len(report["page_errors"]) == 0,
        f"console={errs[:3]} pageerror={report['page_errors'][:3]}")

    b.close()

report["summary"] = {
    "passed": sum(1 for c in report["checks"] if c["ok"]),
    "failed": sum(1 for c in report["checks"] if not c["ok"]),
}
json.dump(report, open("/workspace/work-cnn/verify_report.json", "w"), ensure_ascii=False, indent=2)
print("\n== summary:", report["summary"])
for c in report["checks"]:
    if not c["ok"]:
        print("FAILED:", c["check"], "|", c["detail"][:300])
