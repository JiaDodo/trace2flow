"""Capture the real local Streamlit UI; requires optional Playwright tooling.

Run against an already started local server. No Agent/provider requests are
performed. Screenshots are generated artifacts, never fabricated UI mockups.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8512")
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path(__file__).resolve().parents[1] / "docs/assets/m12",
    )
    args = parser.parse_args()
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost"}:
        parser.error("capture only an explicitly local demo server")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200}, device_scale_factor=1)
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(type(error).__name__))
        # The archive demo needs no off-machine resources, including telemetry.
        page.route("**/*", lambda route: route.continue_()
                   if urlparse(route.request.url).hostname in {"127.0.0.1", "localhost"}
                   else route.abort())
        page.goto(args.url)
        page.get_by_text("覆盖率 66.7%", exact=False).wait_for()
        page.get_by_text("call_00_ziWTFkCs5ouBy3yoc76i7777", exact=False).first.wait_for()

        def capture(name: str) -> None:
            page.locator('[data-testid="stSkeleton"]:visible').first.wait_for(state="hidden")
            page.evaluate("document.fonts.ready")
            visible_grids = page.locator('[data-testid="stDataFrame"]:visible')
            for index in range(visible_grids.count()):
                visible_grids.nth(index).locator("canvas").first.wait_for()
            page.set_viewport_size({"width": 1440, "height": 1200})
            height = page.locator('[data-testid="stMain"]').evaluate("e => e.scrollHeight")
            page.set_viewport_size({"width": 1440, "height": min(height + 100, 4500)})
            page.locator('[data-testid="stMain"]').evaluate("e => e.scrollTo(0, 0)")
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
            assert page.locator('[data-testid="stException"]').count() == 0
            assert not page_errors, page_errors
            path = args.output_dir / name
            page.screenshot(path=str(path), full_page=True)
            print(path.name)

        capture("01-recording.png")
        page.get_by_role("tab", name="2 · DAG 与声明绑定", exact=True).click()
        graph = page.locator('[data-testid="stGraphVizChart"] svg').first
        graph.wait_for()
        assert graph.locator("g.node").count() == 5
        assert graph.locator("g.edge").count() == 3
        capture("02-dag-bindings.png")
        page.get_by_role("tab", name="3 · 新状态验证", exact=True).click()
        page.get_by_role("button", name="运行冻结工作流（新模拟状态）", exact=True).click()
        page.get_by_text(
            "独立本地模拟验证通过：执行 5 个节点，最终输出与完整状态匹配。", exact=True,
        ).wait_for()
        capture("03-fresh-state.png")
        page.get_by_role("combobox").click()
        page.get_by_role("option", name="test-11", exact=True).click()
        page.get_by_role("button", name="运行冻结工作流（新模拟状态）", exact=True).click()
        page.get_by_text("安全拒绝，未运行工具且完整状态不变", exact=False).wait_for()
        capture("04-safe-refusal.png")
        page.get_by_role("tab", name="1 · 原始调用摘录", exact=True).click()
        page.get_by_role("combobox").click()
        page.get_by_role("option", name="compile-10", exact=False).click()
        page.get_by_text("call_00_UZp9PKC1yUo2Yfooj9j53269", exact=False).first.wait_for()
        capture("05-repeated-failures.png")
        page.get_by_role("combobox").click()
        page.get_by_role("option", name="test-11", exact=False).click()
        page.get_by_text("零工具调用：calls=[]", exact=False).wait_for()
        capture("06-zero-call.png")
        page.get_by_role("tab", name="4 · 失败与范围", exact=True).click()
        capture("07-failure-inventory.png")
        browser.close()
    print("7 screenshots; successful update, safe refusal, failures and zero-call checked")


if __name__ == "__main__":
    main()
