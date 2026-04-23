"""Render the 7 infographic HTMLs to PDF using playwright.

Requires the preview server (or any HTTP server) on http://localhost:8766
to be serving C:\\projects\\lawyer-dashboard\\public\\.
"""
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL = "http://localhost:8766/infographics"
OUT_DIR = Path(r"C:\projects\lawyer-dashboard\public\infographics\pdf")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# (relative URL path, output pdf name, nominal page height hint in px)
PAGES = [
    ("01_operating_trend.html",             "01_operating_trend.pdf",       1870),
    ("02_expense_structure.html",           "02_expense_structure.pdf",     1700),
    ("03_profit_contribution.html",         "03_profit_contribution.pdf",   2140),
    ("industry2026/01_market_pyramid.html", "industry_01_market_pyramid.pdf",   1790),
    ("industry2026/02_six_models.html",     "industry_02_six_models.pdf",       1800),
    ("industry2026/03_former_judge.html",   "industry_03_former_judge.pdf",     1920),
    ("industry2026/04_future_variables.html","industry_04_future_variables.pdf", 1930),
    ("industry2026/05_ai_impact.html",        "industry_05_ai_impact.pdf",        3010),
]

WIDTH_PX = 1080


async def render_one(browser, rel_path: str, out_name: str, height_hint: int) -> Path:
    context = await browser.new_context(
        viewport={"width": WIDTH_PX, "height": height_hint},
        device_scale_factor=2,
    )
    page = await context.new_page()
    url = f"{BASE_URL}/{rel_path}?pdf=1"
    await page.goto(url, wait_until="networkidle")
    # Ensure fonts fully ready
    await page.evaluate("document.fonts.ready")
    # Measure actual .page height
    page_h = await page.evaluate("""
        () => {
            const p = document.querySelector('.page');
            return p ? p.offsetHeight : document.body.scrollHeight;
        }
    """)
    # Add a little buffer so the watermark isn't cut off
    page_h = int(page_h) + 40
    out_path = OUT_DIR / out_name
    # 1px = 1/96 inch in CSS pixels; playwright PDF size is in CSS px here
    await page.pdf(
        path=str(out_path),
        width=f"{WIDTH_PX}px",
        height=f"{page_h}px",
        print_background=True,
        margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        prefer_css_page_size=False,
    )
    await context.close()
    return out_path


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        results = []
        for rel_path, out_name, h in PAGES:
            try:
                pth = await render_one(browser, rel_path, out_name, h)
                size_kb = pth.stat().st_size // 1024
                print(f"OK  {out_name}  ({size_kb} KB)")
                results.append((out_name, True, size_kb))
            except Exception as e:
                print(f"FAIL {out_name}: {e}")
                results.append((out_name, False, str(e)))
        await browser.close()
    ok = sum(1 for _, s, _ in results if s)
    print(f"\nDone: {ok}/{len(results)} rendered to {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
