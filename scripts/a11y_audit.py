"""Accessibility audit of every screen in a real browser at phone size (360 px).

Runs axe-core (WCAG 2.0/2.1/2.2 A and AA rules) on each screen and state, and also checks the
project's own rules: no horizontal scrolling at 360 px and touch targets of at least 44 px.

Needs the app running (`.\\scripts\\dev.ps1 up`), loaded data, and Python Playwright on the host:
    pip install playwright && python -m playwright install chromium
    docker compose exec backend python -c "from app.core.ocr.synthetic import render; \
        open('/data/cache/rx_sample.png','wb').write(render(['Tab Dolo 650', 'Tab Telma 40']))"
    python scripts/a11y_audit.py [--screenshots docs/screenshots]

Exit code 1 if any violation is found.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
AXE = ROOT / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
SAMPLE = ROOT / "data" / "cache" / "rx_sample.png"
BASE = "http://localhost:5173"
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]

SMALL_TARGETS_JS = """() => [...document.querySelectorAll('button, a, input, select, summary, [role=option]')]
  .filter(e => e.offsetParent !== null && !e.closest('.sr-only') && !e.classList.contains('sr-only'))
  // A checkbox or radio is tapped through its label, so the label is the target.
  .map(e => (e.type === 'checkbox' || e.type === 'radio') && e.closest('label') ? e.closest('label') : e)
  .map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.height), Math.round(r.width),
              (e.innerText || e.getAttribute('aria-label') || e.tagName).trim().slice(0, 40)]; })
  .filter(([h, w]) => h > 0 && (h < 44 || w < 24))"""


def audit(
    page: Page, name: str, results: dict[str, list[str]], shots: Path | None, touch: bool = True
) -> None:
    page.add_script_tag(path=str(AXE))
    report = page.evaluate(
        "async (tags) => await axe.run(document, {runOnly: {type: 'tag', values: tags}})", TAGS
    )
    problems = [
        f"axe {v['impact']} {v['id']}: {v['help']} -> "
        + "; ".join(", ".join(n["target"]) for n in v["nodes"][:4])
        for v in report["violations"]
    ]
    width = page.evaluate("document.documentElement.scrollWidth")
    if width > 360:
        problems.append(f"horizontal overflow: {width}px at a 360px viewport")
    if touch:  # not on paper
        targets = page.evaluate(SMALL_TARGETS_JS)
        problems += [f"small target {h}x{w}px: {label!r}" for h, w, label in targets]
    results[name] = problems
    print(f"{name}: {len(report['passes'])} rules passed, {len(problems)} problem(s)")
    for p in problems:
        print("   -", p)
    if shots:
        page.screenshot(path=shots / f"{name}.png", full_page=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[str]] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 360, "height": 780}, device_scale_factor=2)
        page = context.new_page()
        page.goto(BASE)
        box = page.get_by_role("combobox", name="Add medicine")
        box.wait_for()
        audit(page, "check-empty", results, args.screenshots)

        box.fill("dolo")
        page.get_by_role("listbox").get_by_role("option").first.wait_for()
        audit(page, "check-autocomplete", results, args.screenshots)
        page.get_by_role("listbox").get_by_role("option", name="Dolo 650").click()
        for typed, option in (("warf", "warfarin"), ("ecosp", "Ecosprin 75"), ("telma", "Telma 40")):
            box.fill(typed)
            page.get_by_role("listbox").get_by_role("option", name=option).first.click()
        box.fill("amlodipin")
        box.press("Enter")
        page.get_by_text("Please confirm which medicine this is").wait_for()
        telma = page.locator("li", has_text="Telma 40").first
        telma.get_by_role("button", name="Add batch number (optional)").click()
        telma.get_by_label("Batch number (from the strip or box)").fill("K18230707")
        page.get_by_text("About the patient (optional)").click()
        page.get_by_label("Older adult (65+)").check()
        audit(page, "check-list-confirm", results, args.screenshots)

        page.locator("li", has_text="amlodipin").get_by_role("button", name="amlodipine").first.click()
        page.get_by_role("button", name="Check safety").click()
        page.get_by_role("heading", level=1).wait_for(timeout=15000)
        for summary in page.locator("details > summary").all():  # audit the expanded content too
            summary.click()
        audit(page, "results", results, args.screenshots)
        page.emulate_media(media="print")
        audit(page, "results-print", results, args.screenshots, touch=False)
        page.emulate_media(media="screen")

        page.goto(f"{BASE}/about")
        page.get_by_text("DDInter").first.wait_for(timeout=10000)
        audit(page, "about", results, args.screenshots)
        page.get_by_role("button", name="Save for offline use", exact=False).click()
        page.get_by_text("Saved on this device").wait_for(timeout=60000)
        audit(page, "about-offline-saved", results, args.screenshots)

        # Offline: results computed on the phone from the saved pack.
        context.set_offline(True)
        # In-app navigation (no page load: the dev server has no service worker).
        page.get_by_role("link", name="PrescripTrace", exact=True).click()
        # A different list than before, so the (cached) online result is not reused.
        page.get_by_role("button", name="Remove Telma 40").click()
        page.get_by_role("button", name="Check safety").click()
        try:
            page.get_by_role("heading", name="Offline check: partial").wait_for(timeout=15000)
        except Exception:
            page.screenshot(path=ROOT / "data" / "cache" / "offline_failure.png", full_page=True)
            raise
        audit(page, "results-offline", results, args.screenshots)
        context.set_offline(False)

        page.goto(f"{BASE}/scan")
        page.get_by_text("Take or choose a photo").wait_for()
        audit(page, "scan-start", results, args.screenshots)
        if SAMPLE.exists():
            page.get_by_label("Take or choose a photo").set_input_files(str(SAMPLE))
            page.get_by_text("Compare each line with the photo").wait_for(timeout=60000)
            audit(page, "scan-results", results, args.screenshots)
        else:
            print(f"scan-results: skipped ({SAMPLE} not found)")

        page.goto(BASE)
        page.get_by_role("combobox", name="Language").select_option("hi")
        page.get_by_text("मशीन से").wait_for()
        audit(page, "check-hindi", results, args.screenshots)
        page.get_by_role("combobox", name="भाषा").select_option("kn")
        audit(page, "check-kannada", results, args.screenshots)
        page.get_by_role("combobox", name="ಭಾಷೆ").select_option("en")

        page.goto(f"{BASE}/no-such-page")
        audit(page, "not-found", results, args.screenshots)
        browser.close()

    total = sum(len(v) for v in results.values())
    print(json.dumps({"screens": len(results), "problems": total}))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
