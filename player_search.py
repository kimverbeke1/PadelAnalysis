import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import sync_playwright

from firebase_service import get_player_search_cache, save_player_search_cache, save_player_profile

BASE_SITE_URL = "https://www.tennisenpadelvlaanderen.be"
SEARCH_URL = "https://www.tennisenpadelvlaanderen.be/zoek-een-speler"
DEBUG_DIR = Path("debug_output")
DEBUG_DIR.mkdir(exist_ok=True)
SEARCH_LOG_FILE = DEBUG_DIR / "player_search_debug.log"


def clean_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def log_line(message: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line)
    with open(SEARCH_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + "\n")


def extract_player_id_from_url(url: str) -> Optional[str]:
    try:
        vals = parse_qs(urlparse(url).query).get('userId')
        return vals[0] if vals else None
    except Exception:
        return None


def dismiss_cookie_banner_if_present(page):
    for label in ["Alle cookies accepteren", "Cookies accepteren", "Ik ga akkoord", "Accepteren"]:
        try:
            loc = page.get_by_text(label, exact=False)
            if loc.count() > 0:
                loc.first.click(timeout=2000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass


def detect_robot_page(page) -> bool:
    try:
        body = page.locator('body').inner_text(timeout=3000).lower()
        return 'ben jij een robot?' in body or 'verhoogd aantal geautomatiseerde toegangspogingen' in body
    except Exception:
        return False


def try_fill_search_form(page, name_query: str, club: Optional[str], sport: str = 'Padel'):
    parts = [p for p in clean_text(name_query).split() if p]
    first_name = parts[0] if len(parts) >= 2 else None
    last_name = ' '.join(parts[1:]) if len(parts) >= 2 else (parts[0] if len(parts) == 1 else None)
    try:
        page.get_by_text(sport, exact=True).first.click(timeout=2000)
        page.wait_for_timeout(700)
    except Exception:
        pass
    if first_name:
        for getter in [lambda: page.get_by_label('Voornaam', exact=False), lambda: page.locator("input[name*='first']")]:
            try:
                loc = getter()
                if loc.count() > 0:
                    loc.first.fill(first_name, timeout=2000)
                    break
            except Exception:
                pass
    if last_name:
        for getter in [lambda: page.get_by_label('Naam', exact=False), lambda: page.locator("input[name*='name']"), lambda: page.locator("input[type='text']").nth(0)]:
            try:
                loc = getter()
                if loc.count() > 0:
                    loc.first.fill(last_name, timeout=2000)
                    break
            except Exception:
                pass
    if club:
        for getter in [lambda: page.get_by_label('Club', exact=False), lambda: page.locator("input[name*='club']")]:
            try:
                loc = getter()
                if loc.count() > 0:
                    loc.first.fill(club, timeout=2000)
                    break
            except Exception:
                pass


def try_submit_search(page):
    for action in [
        lambda: page.get_by_role('button', name=re.compile(r'zoek|search', re.I)).first.click(timeout=2000),
        lambda: page.locator("button[type='submit']").first.click(timeout=2000),
    ]:
        try:
            action()
            page.wait_for_timeout(3000)
            return True
        except Exception:
            pass
    try:
        page.keyboard.press('Enter')
        page.wait_for_timeout(3000)
        return True
    except Exception:
        return False


def extract_candidates_from_page(page) -> List[Dict]:
    out = []
    try:
        links = page.locator('a')
        for i in range(links.count()):
            try:
                href = links.nth(i).get_attribute('href') or ''
                text = clean_text(links.nth(i).inner_text(timeout=500))
            except Exception:
                continue
            if 'dashboard/resultaten' in href and 'userId=' in href:
                full_url = urljoin(BASE_SITE_URL, href)
                player_id = extract_player_id_from_url(full_url)
                candidate = {
                    'display_name': text or None,
                    'club': None,
                    'player_id': player_id,
                    'dashboard_url': full_url,
                    'source': 'link_scan',
                }
                out.append(candidate)
    except Exception:
        pass
    seen = set(); unique = []
    for c in out:
        key = (c.get('player_id'), c.get('dashboard_url'))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    for c in unique:
        if c.get('player_id'):
            save_player_profile(str(c['player_id']), c.get('display_name'), c.get('club'), dashboard_url=c.get('dashboard_url'), aliases=[c.get('display_name')] if c.get('display_name') else [])
    return unique


def search_players(name_query: str, club: Optional[str] = None, sport: str = 'Padel', headless: bool = True, use_cache: bool = True) -> List[Dict]:
    if use_cache:
        cached = get_player_search_cache(name_query, club=club, sport=sport)
        if cached and isinstance(cached.get('candidates'), list) and cached.get('candidates'):
            return cached.get('candidates', [])
    if SEARCH_LOG_FILE.exists():
        SEARCH_LOG_FILE.unlink()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(SEARCH_URL, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(4000)
            dismiss_cookie_banner_if_present(page)
            if detect_robot_page(page):
                raise RuntimeError('Robot-check gedetecteerd op spelerszoekpagina')
            try_fill_search_form(page, name_query=name_query, club=club, sport=sport)
            if not try_submit_search(page):
                raise RuntimeError('Kon zoekactie niet uitvoeren')
            if detect_robot_page(page):
                raise RuntimeError('Robot-check gedetecteerd na zoekactie')
            candidates = extract_candidates_from_page(page)
            if candidates:
                save_player_search_cache(name_query, club=club, sport=sport, candidates=candidates)
            return candidates
        finally:
            context.close(); browser.close()
