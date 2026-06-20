"""
fetch_period_playwright.py
Playwright helper voor periode-wisseling op het TVL dashboard.
Geeft per periode de HTML terug; parsing gebeurt via scraper_v2.py.
"""

import time
import logging
from typing import Optional

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

BASE_URL = "https://www.tennisenpadelvlaanderen.be"
DEFAULT_PADEL_PARAMS = {
    "tab": "padel", "tspid": "80", "tdpid": "80",
    "ppid": "79", "tscid": "80", "pcid": "79",
}


def _build_url(player_id: str) -> str:
    qs = "&".join(f"{k}={v}" for k, v in {"userId": player_id, **DEFAULT_PADEL_PARAMS}.items())
    return f"{BASE_URL}/dashboard/resultaten?{qs}"


def _dismiss_cookies(page):
    for txt in ["Alle cookies accepteren", "Cookies accepteren", "Accepteren"]:
        try:
            loc = page.get_by_text(txt, exact=False)
            if loc.count() > 0:
                loc.first.click(timeout=2000)
                page.wait_for_timeout(800)
                return
        except Exception:
            pass


def _get_padel_period_select(page):
    """Return the padel period <select> element (3rd select with period options)."""
    period_selects = []
    for sel in page.locator("select").all():
        try:
            opts = sel.locator("option").all()
            if any("resultaten van week" in (o.text_content() or "").lower() for o in opts):
                period_selects.append(sel)
        except Exception:
            pass
    return period_selects[2] if len(period_selects) >= 3 else (period_selects[-1] if period_selects else None)


def _get_period_options(page, padel_select) -> list[dict]:
    """Extract all period options from the padel select."""
    options = []
    for o in padel_select.locator("option").all():
        try:
            label = (o.text_content() or "").strip()
            value = page.evaluate("(o) => o.value", o.element_handle())
            if "resultaten van week" in label.lower():
                options.append({"label": label, "value": value})
        except Exception:
            pass
    return options


def _wait_after_select(page, timeout_ms: int = 10000):
    """Wait for network to settle after period selection."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass
    page.wait_for_timeout(1500)


def fetch_all_periods_html(
    player_id: str,
    max_periods: Optional[int] = None,
    headless: bool = True,
    delay_between_periods: float = 1.0,
) -> list[dict]:
    """
    Open player dashboard, iterate over padel periods, capture HTML per period.

    Returns list of:
        {"label": str, "value": str, "html": str, "status": "ok"|"empty"|"error"}
    """
    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"
        ).new_page()

        try:
            url = _build_url(player_id)
            logger.info(f"Opening: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            _dismiss_cookies(page)

            padel_select = _get_padel_period_select(page)
            if padel_select is None:
                logger.error("Geen padel period select gevonden")
                return results

            all_options = _get_period_options(page, padel_select)
            logger.info(f"  {len(all_options)} periodes gevonden")

            if max_periods is not None:
                all_options = all_options[:max_periods]

            for i, opt in enumerate(all_options):
                label, value = opt["label"], opt["value"]
                logger.info(f"  [{i+1}/{len(all_options)}] {label}")

                if i > 0:
                    try:
                        padel_select.select_option(value=value, timeout=5000)
                        _wait_after_select(page)
                    except Exception as e:
                        logger.error(f"    → selectie FOUT: {e}")
                        results.append({**opt, "html": "", "status": "error", "error": str(e)})
                        continue

                html = page.content()
                results.append({**opt, "html": html, "status": "ok"})
                logger.info(f"    → html captured ({len(html)} bytes)")

                if i < len(all_options) - 1:
                    time.sleep(delay_between_periods)

        finally:
            page.context.browser.close()

    return results


if __name__ == "__main__":
    import json
    from pathlib import Path
    from bs4 import BeautifulSoup

    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from scraper_v2 import parse_tournament_section, parse_interclub_section

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print("Test: eerste 5 periodes voor speler 214435...")
    pages = fetch_all_periods_html("214435", max_periods=5, headless=True)

    all_matches = []
    for p in pages:
        if not p["html"]:
            print(f"  {p['label'][:55]}: FOUT")
            continue
        soup = BeautifulSoup(p["html"], "html.parser")
        t = parse_tournament_section(soup, "214435", p["label"])
        ic = parse_interclub_section(soup, "214435", p["label"])
        all_matches.extend(t + ic)
        print(f"  {p['label'][:55]}: {len(t)} tornooi + {len(ic)} interclub")

    print(f"\nTotaal: {len(all_matches)} matches")

    out = Path(__file__).parent.parent / "debug_output_v2" / "test_multiperiod_214435.json"
    out.write_text(json.dumps(all_matches, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Output: {out}")
