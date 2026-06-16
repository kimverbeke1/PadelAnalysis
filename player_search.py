from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
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


def normalize_name_parts(first_name: str, last_name: str) -> Tuple[str, str, str]:
    first_name = clean_text(first_name)
    last_name = clean_text(last_name)
    full_name = clean_text(f"{first_name} {last_name}")
    return first_name, last_name, full_name


def split_full_name(full_name: str) -> Tuple[str, str, str]:
    parts = [p for p in clean_text(full_name).split() if p]
    if len(parts) >= 2:
        first_name = parts[0]
        last_name = " ".join(parts[1:])
    elif len(parts) == 1:
        first_name = ""
        last_name = parts[0]
    else:
        first_name = last_name = ""
    return normalize_name_parts(first_name, last_name)


def build_search_url(first_name: str, last_name: str, sport_id: int = 2) -> str:
    first_name, last_name, _ = normalize_name_parts(first_name, last_name)
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
    if not url:
        return None
    try:
        parsed = urlparse(url)
        vals = parse_qs(parsed.query).get("userId")
        return vals[0] if vals else None
    except Exception:
        return None


def parse_result_block(raw_text: str, fallback_first: str, fallback_last: str) -> Tuple[str, Optional[str]]:
    """
    Parse result container text. Usually the first line is the name.
    A later line may contain club information.
    """
    lines = [clean_text(line) for line in str(raw_text or "").splitlines()]
    lines = [line for line in lines if line and line.lower() != "profiel bekijken"]
    if not lines:
        return clean_text(f"{fallback_first} {fallback_last}"), None

    name = lines[0]
    club = None
    for line in lines[1:]:
        low = line.lower()
        if "padel" in low or "club" in low:
            club = line
            break
    return name, club


def _candidate_from_url_and_meta(url: str, display_name: str, club: Optional[str]) -> Optional[Dict]:
    full_url = urljoin(BASE_SITE_URL, url)
    player_id = extract_player_id_from_url(full_url)
    if not player_id:
        return None
    return {
        "display_name": clean_text(display_name) or None,
        "club": clean_text(club) or None,
        "player_id": str(player_id),
        "dashboard_url": full_url,
        "source": "search_result",
    }


def _save_profiles(candidates: List[Dict]) -> List[Dict]:
    unique = []
    seen = set()
    for c in candidates:
        key = (c.get("player_id"), c.get("dashboard_url"))
        if c.get("player_id") and key not in seen:
            seen.add(key)
            unique.append(c)
    for c in unique:
        save_player_profile(
            player_id=str(c["player_id"]),
            display_name=c.get("display_name"),
            club=c.get("club"),
            dashboard_url=c.get("dashboard_url"),
            aliases=[c.get("display_name")] if c.get("display_name") else [],
        )
    return unique


def extract_candidates_from_page(page, fallback_first: str, fallback_last: str) -> List[Dict]:
    candidates: List[Dict] = []

    # 1) Direct links with userId anywhere on the page.
    try:
        links = page.locator("a")
        for i in range(links.count()):
            try:
                link = links.nth(i)
                href = link.get_attribute("href") or ""
                text = clean_text(link.inner_text(timeout=400))
                container_text = link.evaluate(
                    """el => {
                        const row = el.closest('article, li, tr, .views-row, .search-result, .card, .row') || el.parentElement;
                        return row ? row.innerText : el.innerText;
                    }"""
                )
                parsed_name, parsed_club = parse_result_block(container_text, fallback_first, fallback_last)
            except Exception:
                continue
            if "userId=" in href or "/dashboard/resultaten" in href or "/dashboard?userId=" in href:
                c = _candidate_from_url_and_meta(href, parsed_name if parsed_name else text, parsed_club)
                if c:
                    candidates.append(c)
    except Exception:
        pass

    # 2) Controls/buttons/links with text 'Profiel bekijken'
    try:
        controls = []
        for getter in [
            lambda: page.get_by_text("Profiel bekijken", exact=False),
            lambda: page.get_by_role("link", name="Profiel bekijken"),
            lambda: page.get_by_role("button", name="Profiel bekijken"),
        ]:
            try:
                loc = getter()
                for i in range(loc.count()):
                    controls.append(loc.nth(i))
            except Exception:
                pass

        log_line(f"Aantal 'Profiel bekijken' controls gevonden: {len(controls)}")

        for idx, ctrl in enumerate(controls, start=1):
            href = None
            try:
                href = ctrl.get_attribute("href")
            except Exception:
                href = None

            if not href:
                try:
                    href = ctrl.evaluate(
                        """el => {
                            const a = el.closest('a');
                            return a ? a.getAttribute('href') : null;
                        }"""
                    )
                except Exception:
                    href = None

            if not href:
                try:
                    href = ctrl.evaluate(
                        """el => {
                            const node = el.closest('a,button,div,article,li,tr') || el;
                            const attrs = ['href','data-href','data-url','onclick'];
                            for (const attr of attrs) {
                                const val = node.getAttribute && node.getAttribute(attr);
                                if (val && typeof val === 'string' && val.includes('userId=')) return val;
                            }
                            return null;
                        }"""
                    )
                except Exception:
                    href = None

            try:
                raw_result = ctrl.evaluate(
                    """el => {
                        const row = el.closest('article, li, tr, .views-row, .search-result, .card, .row') || el.parentElement;
                        return row ? row.innerText : el.innerText;
                    }"""
                )
            except Exception:
                raw_result = ""

            parsed_name, parsed_club = parse_result_block(raw_result, fallback_first, fallback_last)

            if href:
                c = _candidate_from_url_and_meta(href, parsed_name, parsed_club)
                if c:
                    candidates.append(c)
                    log_line(f"Kandidaat via profielcontrol {idx}: {c.get('player_id')} | {c.get('display_name')} | {c.get('club')}")
                    continue

            try:
                # last resort: click control and inspect navigation
                old_url = page.url
                ctrl.click(timeout=2500)
                page.wait_for_timeout(2500)
                new_url = page.url
                log_line(f"Profielcontrol {idx} geklikt. Voor URL={old_url} | Na URL={new_url}")
                c = _candidate_from_url_and_meta(new_url, parsed_name, parsed_club)
                if c:
                    candidates.append(c)
                if page.url != old_url:
                    try:
                        page.go_back(timeout=10000)
                        page.wait_for_timeout(1200)
                    except Exception:
                        pass
            except Exception as e:
                log_line(f"Klik op profielcontrol {idx} mislukte: {e}")
    except Exception:
        pass

    return _save_profiles(candidates)


def click_search_button_if_needed(page):
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


def search_players(
    full_name: Optional[str] = None,
    club: Optional[str] = None,
    sport: str = "Padel",
    headless: bool = True,
    use_cache: bool = True,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> List[Dict]:
    if full_name is not None:
        first_name, last_name, full_name = split_full_name(full_name)
    else:
        first_name, last_name, full_name = normalize_name_parts(first_name or "", last_name or "")

    if use_cache:
        cached = get_player_search_cache(full_name, club=club, sport=sport)
        if cached and isinstance(cached.get("candidates"), list) and cached.get("candidates"):
            log_line(f"Cache gebruikt voor zoekterm: {full_name}")
            return cached.get("candidates", [])

    if SEARCH_LOG_FILE.exists():
        SEARCH_LOG_FILE.unlink()

    url = build_search_url(first_name=first_name, last_name=last_name, sport_id=2)
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

            candidates = extract_candidates_from_page(page, first_name, last_name)
            if candidates:
                log_line(f"Kandidaten direct zichtbaar: {len(candidates)}")
                save_player_search_cache(full_name, club=club, sport=sport, candidates=candidates)
                return candidates

            log_line("Nog geen kandidaten zichtbaar na URL-load, probeer expliciet op zoekknop te klikken...")
            if click_search_button_if_needed(page):
                if detect_robot_page(page):
                    raise RuntimeError("Robot-check gedetecteerd na zoektrigger")
                candidates = extract_candidates_from_page(page, first_name, last_name)
                if candidates:
                    log_line(f"Kandidaten gevonden na expliciete zoektrigger: {len(candidates)}")
                    save_player_search_cache(full_name, club=club, sport=sport, candidates=candidates)
                    return candidates

            log_line("Geen kandidaten gevonden")
            return []
        finally:
            context.close()
            browser.close()
