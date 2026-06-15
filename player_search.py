from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, quote, urljoin, urlparse

from playwright.sync_api import sync_playwright

from firebase_service import get_player_search_cache, save_player_search_cache, save_player_profile

BASE_SITE_URL = "https://www.tennisenpadelvlaanderen.be"
BASE_SEARCH_URL = "https://www.tennisenpadelvlaanderen.be/zoek-een-speler"
DEBUG_DIR = Path("debug_output")
DEBUG_DIR.mkdir(exist_ok=True)
SEARCH_LOG_FILE = DEBUG_DIR / "player_search_debug.log"


def log_line(message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}"
    print(line)
    with open(SEARCH_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def clean_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def split_name_for_tpv(name_query: str):
    parts = [p for p in clean_text(name_query).split() if p]
    if len(parts) >= 2:
        first_name = parts[0]
        last_name = " ".join(parts[1:])
    elif len(parts) == 1:
        first_name = ""
        last_name = parts[0]
    else:
        first_name = ""
        last_name = ""
    return first_name, last_name


def build_search_url(name_query: str, sport_id: int = 2) -> str:
    first_name, last_name = split_name_for_tpv(name_query)
    return (
        f"{BASE_SEARCH_URL}?sportId={sport_id}"
        f"&playerName={quote(last_name)}"
        f"&playerFirstName={quote(first_name)}"
        f"#searchResultStart"
    )


def dismiss_cookie_banner_if_present(page):
    for label in ["Alle cookies accepteren", "Cookies accepteren", "Ik ga akkoord", "Accepteren"]:
        try:
            loc = page.get_by_text(label, exact=False)
            if loc.count() > 0:
                loc.first.click(timeout=2000)
                page.wait_for_timeout(800)
                log_line(f"Cookie banner gesloten via: {label}")
                return
        except Exception:
            pass


def detect_robot_page(page) -> bool:
    try:
        body = page.locator("body").inner_text(timeout=3000).lower()
        return ("ben jij een robot?" in body) or ("verhoogd aantal geautomatiseerde toegangspogingen" in body)
    except Exception:
        return False


def extract_player_id_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        vals = parse_qs(parsed.query).get("userId")
        return vals[0] if vals else None
    except Exception:
        return None


def extract_candidates_from_page(page) -> List[Dict]:
    candidates: List[Dict] = []
    try:
        links = page.locator("a")
        for i in range(links.count()):
            try:
                href = links.nth(i).get_attribute("href") or ""
                text = clean_text(links.nth(i).inner_text(timeout=500))
            except Exception:
                continue
            if "dashboard/resultaten" in href and "userId=" in href:
                full_url = urljoin(BASE_SITE_URL, href)
                player_id = extract_player_id_from_url(full_url)
                candidates.append({
                    "display_name": text or None,
                    "club": None,
                    "player_id": player_id,
                    "dashboard_url": full_url,
                    "source": "url_search",
                })
    except Exception:
        pass

    unique = []
    seen = set()
    for c in candidates:
        key = (c.get("player_id"), c.get("dashboard_url"))
        if key not in seen:
            seen.add(key)
            unique.append(c)

    for c in unique:
        if c.get("player_id"):
            save_player_profile(
                player_id=str(c["player_id"]),
                display_name=c.get("display_name"),
                club=c.get("club"),
                dashboard_url=c.get("dashboard_url"),
                aliases=[c.get("display_name")] if c.get("display_name") else [],
            )
    return unique


def click_search_button_if_needed(page):
    """Sommige TPV-resultaten verschijnen pas na expliciete klik op de zoekknop."""
    actions = [
        lambda: page.get_by_role("button", name="Zoek").first.click(timeout=2500),
        lambda: page.get_by_role("button", name="Search").first.click(timeout=2500),
        lambda: page.locator("button[type='submit']").first.click(timeout=2500),
        lambda: page.get_by_text("Zoek", exact=True).click(timeout=2500),
    ]
    for idx, action in enumerate(actions, start=1):
        try:
            action()
            page.wait_for_timeout(2500)
            log_line(f"Zoekknop geklikt via methode {idx}")
            return True
        except Exception:
            continue
    try:
        page.keyboard.press("Enter")
        page.wait_for_timeout(2500)
        log_line("Zoektrigger via Enter")
        return True
    except Exception:
        return False


def search_players(name_query: str, club: Optional[str] = None, sport: str = "Padel", headless: bool = True, use_cache: bool = True) -> List[Dict]:
    if use_cache:
        cached = get_player_search_cache(name_query, club=club, sport=sport)
        if cached and isinstance(cached.get("candidates"), list) and cached.get("candidates"):
            log_line(f"Cache gebruikt voor zoekterm: {name_query}")
            return cached.get("candidates", [])

    if SEARCH_LOG_FILE.exists():
        SEARCH_LOG_FILE.unlink()

    url = build_search_url(name_query=name_query, sport_id=2)
    log_line(f"Zoek-URL: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3500)
            dismiss_cookie_banner_if_present(page)
            if detect_robot_page(page):
                raise RuntimeError("Robot-check gedetecteerd op zoekpagina")

            candidates = extract_candidates_from_page(page)
            if candidates:
                log_line(f"Kandidaten direct via URL gevonden: {len(candidates)}")
                save_player_search_cache(name_query, club=club, sport=sport, candidates=candidates)
                return candidates

            log_line("Nog geen kandidaten zichtbaar na URL-load, probeer expliciet op zoekknop te klikken...")
            clicked = click_search_button_if_needed(page)
            if clicked:
                if detect_robot_page(page):
                    raise RuntimeError("Robot-check gedetecteerd na zoektrigger")
                candidates = extract_candidates_from_page(page)
                if candidates:
                    log_line(f"Kandidaten gevonden na expliciete zoektrigger: {len(candidates)}")
                    save_player_search_cache(name_query, club=club, sport=sport, candidates=candidates)
                    return candidates

            log_line("Geen kandidaten gevonden")
            return []
        finally:
            context.close()
            browser.close()
