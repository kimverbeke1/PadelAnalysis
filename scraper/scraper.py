import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from firebase_service import get_player, save_player, save_player_profile
from player_search import search_players

BASE_URL = "https://www.tennisenpadelvlaanderen.be/nl/dashboard/resultaten?userId={player_id}"
DEBUG_DIR = Path("debug_output")
DEBUG_DIR.mkdir(exist_ok=True)
NETWORK_LOG_JSONL = DEBUG_DIR / "network_log.jsonl"
SCRAPER_LOG_TXT = DEBUG_DIR / "scraper_debug.log"
LAST_HTML_FILE = DEBUG_DIR / "last_page.html"
LAST_SCREENSHOT_FILE = DEBUG_DIR / "last_page.png"

SURNAME_PARTICLES = {"de", "den", "der", "van", "vanden", "vander", "ten", "ter", "op", "te", "du", "del", "della", "la", "le"}
SURNAME_PARTICLE_SEQUENCES = {("van", "de"), ("van", "den"), ("van", "der"), ("de", "la")}


def log_line(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(SCRAPER_LOG_TXT, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def append_jsonl(path: Path, obj: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def save_debug_snapshot(page, prefix="snapshot"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = DEBUG_DIR / f"{prefix}_{timestamp}.html"
    png_path = DEBUG_DIR / f"{prefix}_{timestamp}.png"
    try:
        html_path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(png_path), full_page=True)
    except Exception:
        pass


def attach_network_logging(page):
    def on_request(req):
        try:
            if req.resource_type in ("xhr", "fetch"):
                append_jsonl(NETWORK_LOG_JSONL, {
                    "type": "request",
                    "timestamp": utc_now_iso(),
                    "method": req.method,
                    "url": req.url,
                    "resource_type": req.resource_type,
                })
        except Exception:
            pass

    def on_response(res):
        try:
            req = res.request
            if req.resource_type in ("xhr", "fetch"):
                append_jsonl(NETWORK_LOG_JSONL, {
                    "type": "response",
                    "timestamp": utc_now_iso(),
                    "status": res.status,
                    "url": res.url,
                    "resource_type": req.resource_type,
                })
        except Exception:
            pass

    page.on("request", on_request)
    page.on("response", on_response)


def detect_robot_page(page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=3000).lower()
        return "ben jij een robot?" in text or "verhoogd aantal geautomatiseerde toegangspogingen" in text
    except Exception:
        return False


def dismiss_cookie_banner_if_present(page):
    for txt in ["Alle cookies accepteren", "Cookies accepteren", "Ik ga akkoord", "Accepteren"]:
        try:
            locator = page.get_by_text(txt, exact=False)
            if locator.count() > 0:
                locator.first.click(timeout=2000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            pass


def open_dashboard(page, player_id: str):
    url = BASE_URL.format(player_id=player_id)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500)
    dismiss_cookie_banner_if_present(page)
    if detect_robot_page(page):
        save_debug_snapshot(page, prefix="robot_page")
        raise RuntimeError("Robot-check gedetecteerd.")
    return url


def try_activate_padel_tab(page):
    actions = [
        lambda: page.get_by_role("tab", name=re.compile(r"^Padel$", re.I)).click(timeout=3000),
        lambda: page.get_by_role("button", name=re.compile(r"^Padel$", re.I)).click(timeout=3000),
        lambda: page.get_by_role("link", name=re.compile(r"^Padel$", re.I)).click(timeout=3000),
        lambda: page.get_by_text("Padel", exact=True).click(timeout=3000),
    ]
    for action in actions:
        try:
            action()
            page.wait_for_timeout(2000)
            return True
        except Exception:
            continue
    return False


def get_select_options_from_select(page):
    candidates = []
    try:
        selects = page.locator("select")
        count = selects.count()
        for i in range(count):
            sel = selects.nth(i)
            try:
                visible = sel.is_visible()
            except Exception:
                visible = False
            options = sel.locator("option")
            names = []
            values = []
            for j in range(options.count()):
                try:
                    text = clean_text(options.nth(j).inner_text())
                    value = options.nth(j).get_attribute("value")
                except Exception:
                    continue
                if text:
                    names.append(text)
                    values.append(value)
            period_like = [n for n in names if "resultaten van week" in n.lower()]
            if len(period_like) >= 2:
                candidates.append({
                    "mode": "select",
                    "index": i,
                    "visible": visible,
                    "options": [{"label": n, "value": v} for n, v in zip(names, values)],
                })
    except Exception:
        return None
    if not candidates:
        return None
    return sorted(candidates, key=lambda c: (100 if c.get("visible") else 0), reverse=True)[0]


def wait_for_results_state(page, timeout_ms: int = 12000):
    start = time.time()
    empty_patterns = ["geen uitslagen beschikbaar", "geen resultaten beschikbaar"]
    while (time.time() - start) * 1000 < timeout_ms:
        try:
            if page.locator("table").count() > 0:
                return "tables"
        except Exception:
            pass
        try:
            body = clean_text(page.locator("body").inner_text(timeout=600)).lower()
            if any(p in body for p in empty_patterns):
                return "empty"
        except Exception:
            pass
        page.wait_for_timeout(300)
    return "timeout"


def select_period(page, selector_info, option):
    if selector_info["mode"] != "select":
        return False, "no_selector"
    sel = page.locator("select").nth(selector_info["index"])
    attempts = []
    for attempt in range(3):
        try:
            if option.get("value") is not None:
                sel.select_option(value=option["value"], timeout=5000)
            else:
                sel.select_option(label=option["label"], timeout=5000)
            state = wait_for_results_state(page, timeout_ms=15000)
            attempts.append(state)
            if state in ("tables", "empty"):
                return True, state
        except Exception:
            attempts.append("exception")
        page.wait_for_timeout(1200)
    return False, ",".join(attempts)


def determine_periods_to_scrape(all_options: List[Dict], existing_player: Optional[Dict], refresh_recent_periods: int = 2, force_full_refresh: bool = False) -> List[Dict]:
    if force_full_refresh or not existing_player:
        return all_options
    raw = existing_player.get("raw_data", {}) if isinstance(existing_player, dict) else {}
    already_processed = set(raw.get("periods_processed", []) or [])
    recent = all_options[:refresh_recent_periods]
    not_yet = [o for o in all_options[refresh_recent_periods:] if o.get("label") not in already_processed]
    out = []
    seen = set()
    for opt in recent + not_yet:
        label = opt.get("label")
        if label not in seen:
            seen.add(label)
            out.append(opt)
    return out


def is_header_or_noise(text: str) -> bool:
    t = clean_text(text).lower()
    return (not t) or ('geen uitslagen beschikbaar' in t) or ('partner tegenstander klassement ronde w/v uitslag' in t)


def is_name_token(token: str) -> bool:
    return bool(re.match(r"^[A-Za-zÀ-ÿ'\-]+$", token))


def is_capitalized_name_token(token: str) -> bool:
    return bool(re.match(r"^[A-ZÀ-Ý][A-Za-zÀ-ÿ'\-]+$", token))


def is_particle(token: str) -> bool:
    return token.lower() in SURNAME_PARTICLES


def score_name_group(tokens: List[str]) -> float:
    if len(tokens) < 2 or len(tokens) > 5:
        return -100.0
    last = tokens[-1]
    if not is_capitalized_name_token(last) or is_particle(last):
        return -100.0
    score = 2.0 if all(is_name_token(t) for t in tokens) else -4.0
    score += {2: 5.0, 3: 4.0, 4: 3.0, 5: 1.0}.get(len(tokens), 0.0)
    lowered = [t.lower() for t in tokens[:-1]]
    score += sum(1 for t in lowered if t in SURNAME_PARTICLES)
    for i in range(len(lowered)-1):
        if (lowered[i], lowered[i+1]) in SURNAME_PARTICLE_SEQUENCES:
            score += 3.0
    return score


def split_names_into_players(names_text: str) -> Tuple[Optional[str], Optional[str], Optional[str], List[str]]:
    names_text = clean_text(names_text)
    if not names_text:
        return None, None, None, []
    tokens = names_text.split(); n = len(tokens)
    best = None; best_score = -10000.0
    for i in range(2, min(6, n-3)+1):
        for j in range(i+2, min(i+5, n-1)+1):
            g1, g2, g3 = tokens[:i], tokens[i:j], tokens[j:]
            if min(len(g1), len(g2), len(g3)) < 2 or max(len(g1), len(g2), len(g3)) > 5:
                continue
            score = score_name_group(g1) + score_name_group(g2) + score_name_group(g3)
            if score > best_score:
                best_score = score; best = (g1, g2, g3)
    if best:
        g1, g2, g3 = best
        players = [' '.join(g1), ' '.join(g2), ' '.join(g3)]
        return players[0], players[1], players[2], players
    return None, None, None, [names_text]


def parse_row_structured(row_text: str) -> Dict[str, Optional[str]]:
    row_text = clean_text(row_text)
    parsed = {'raw_text': row_text, 'names_text': None, 'partner_name': None, 'opponent_1_name': None, 'opponent_2_name': None, 'all_detected_players': [], 'ranking_player_or_team': None, 'ranking_opponents': None, 'round_text': None, 'result_letter': None, 'result_text': None, 'score': None, 'won': None}
    m = re.match(r'^(?P<names>.+?)\s+(?P<ranking1>P\d+)\s+(?P<ranking2>P\d+)\s+(?P<round>.+?)\s+(?P<result>[WV])\s+(?P<score>.+)$', row_text)
    if m:
        names_text = clean_text(m.group('names'))
        partner, opp1, opp2, players = split_names_into_players(names_text)
        result_letter = m.group('result')
        parsed.update({
            'names_text': names_text,
            'partner_name': partner,
            'opponent_1_name': opp1,
            'opponent_2_name': opp2,
            'all_detected_players': players,
            'ranking_player_or_team': m.group('ranking1'),
            'ranking_opponents': m.group('ranking2'),
            'round_text': clean_text(m.group('round')),
            'result_letter': result_letter,
            'result_text': 'Winst' if result_letter == 'W' else 'Verlies',
            'score': clean_text(m.group('score')),
            'won': True if result_letter == 'W' else False,
        })
    return parsed


def collect_structured_rows(page, current_period: str) -> List[Dict]:
    out = []
    state = wait_for_results_state(page, timeout_ms=8000)
    if state in ("empty", "timeout"):
        return out
    try:
        page.wait_for_selector('table', state='attached', timeout=5000)
    except PlaywrightTimeoutError:
        return out
    tables = page.locator('table')
    for t in range(tables.count()):
        rows = tables.nth(t).locator('tr')
        for r in range(rows.count()):
            try:
                row_text = clean_text(rows.nth(r).inner_text(timeout=2000))
                if is_header_or_noise(row_text):
                    continue
                parsed = parse_row_structured(row_text)
                parsed.update({'period': current_period, 'table_index': t, 'row_index': r})
                out.append(parsed)
            except Exception:
                pass
    return out


def dedupe_matches(matches: List[Dict]) -> List[Dict]:
    seen, out = set(), []
    for m in matches:
        key = (m.get('period'), m.get('raw_text'))
        if key not in seen:
            seen.add(key); out.append(m)
    return out


def calculate_stats(matches: List[Dict]) -> Dict[str, float]:
    wins = sum(1 for m in matches if m.get('won') is True)
    losses = sum(1 for m in matches if m.get('won') is False)
    unknown = sum(1 for m in matches if m.get('won') is None)
    known = wins + losses
    return {'matches': len(matches), 'wins': wins, 'losses': losses, 'unknown_results': unknown, 'winrate': round((wins / known) * 100, 2) if known else 0.0}


def unique_keep_order(items: List[str]) -> List[str]:
    seen = set(); out = []
    for item in items:
        if item not in seen:
            seen.add(item); out.append(item)
    return out


def merge_incremental_data(existing_player: Optional[Dict], new_matches: List[Dict], periods_processed_now: List[str], empty_periods_now: List[str], failed_periods_now: List[str], scrape_mode: str, refresh_recent_periods: int) -> Dict:
    existing_raw = existing_player.get('raw_data', {}) if isinstance(existing_player, dict) else {}
    existing_matches = existing_raw.get('matches', []) if isinstance(existing_raw, dict) else []
    periods_replaced = set(periods_processed_now)
    preserved_old = [m for m in existing_matches if m.get('period') not in periods_replaced]
    combined_matches = dedupe_matches(preserved_old + new_matches)
    stats = calculate_stats(combined_matches)
    now_iso = utc_now_iso()

    previous_failed_open = existing_raw.get('failed_periods_open') or existing_raw.get('failed_periods') or []
    # if a period is successfully processed now, remove it from open failures
    previous_failed_open = [p for p in previous_failed_open if p not in periods_processed_now]
    failed_open = unique_keep_order(failed_periods_now + previous_failed_open)

    raw_data = {
        'player_id': existing_player.get('player_id') if existing_player else None,
        'timestamp': now_iso,
        'matches_count': len(combined_matches),
        'schema_version': 'vnext_cleanup_failed_periods',
        'periods_processed': unique_keep_order(periods_processed_now + (existing_raw.get('periods_processed', []) or [])),
        'empty_periods': unique_keep_order(empty_periods_now + (existing_raw.get('empty_periods', []) or [])),
        # compatibility field now means open unresolved failures, not full history
        'failed_periods': failed_open,
        'failed_periods_open': failed_open,
        'failed_periods_last_run': failed_periods_now,
        'network_log_file': str(NETWORK_LOG_JSONL),
        'debug_log_file': str(SCRAPER_LOG_TXT),
        'matches': combined_matches,
        'scrape_mode': scrape_mode,
        'incremental_settings': {'refresh_recent_periods': refresh_recent_periods},
        'last_incremental_scrape': now_iso,
        'last_scraped_periods_this_run': periods_processed_now,
    }
    return {'last_updated': now_iso, 'stats': stats, 'raw_data': raw_data}


def scrape_player(player_id: str, headless: bool = True, max_periods=None, force_full_refresh: bool = False, refresh_recent_periods: int = 2):
    existing_player = get_player(player_id)
    new_matches = []
    processed_periods_now = []
    empty_periods_now = []
    failed_periods_now = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        attach_network_logging(page)
        try:
            open_dashboard(page, player_id)
            try_activate_padel_tab(page)
            selector_info = get_select_options_from_select(page)
            if not selector_info:
                period_matches = collect_structured_rows(page, 'HUIDIGE_PERIODE')
                if period_matches:
                    new_matches.extend(period_matches)
                else:
                    empty_periods_now.append('HUIDIGE_PERIODE')
                processed_periods_now.append('HUIDIGE_PERIODE')
            else:
                options = [o for o in selector_info['options'] if 'resultaten van week' in o['label'].lower()]
                if max_periods is not None:
                    options = options[:max_periods]
                options_to_scrape = determine_periods_to_scrape(options, existing_player, refresh_recent_periods, force_full_refresh)
                for opt in options_to_scrape:
                    label = opt['label']
                    ok, result_state = select_period(page, selector_info, opt)
                    if not ok:
                        failed_periods_now.append(label)
                        log_line(f"Periode mislukt: {label} | state={result_state}")
                        continue
                    period_matches = collect_structured_rows(page, label)
                    if period_matches:
                        new_matches.extend(period_matches)
                    else:
                        empty_periods_now.append(label)
                    processed_periods_now.append(label)
            scrape_mode = 'full_refresh' if (force_full_refresh or not existing_player) else 'incremental'
            final_doc = merge_incremental_data(existing_player, new_matches, processed_periods_now, empty_periods_now, failed_periods_now, scrape_mode, refresh_recent_periods)
            final_doc['player_id'] = str(player_id)
            save_player(player_id, final_doc)
            return {'player_id': str(player_id), **final_doc}
        finally:
            try:
                LAST_HTML_FILE.write_text(page.content(), encoding='utf-8')
                page.screenshot(path=str(LAST_SCREENSHOT_FILE), full_page=True)
            except Exception:
                pass
            context.close(); browser.close()


def find_player_and_scrape(full_name: Optional[str] = None, club: Optional[str] = None, sport: str = 'Padel', headless: bool = True, force_full_refresh: bool = False, refresh_recent_periods: int = 2, first_name: Optional[str] = None, last_name: Optional[str] = None):
    candidates = search_players(full_name=full_name, first_name=first_name, last_name=last_name, club=club, sport=sport, headless=headless, use_cache=True)
    if not candidates:
        raise RuntimeError(f'Geen spelers gevonden voor query')
    chosen = candidates[0]
    player_id = chosen.get('player_id')
    if not player_id:
        raise RuntimeError('Geen player_id gevonden in eerste kandidaat')
    if chosen.get('display_name') or chosen.get('club'):
        save_player_profile(str(player_id), chosen.get('display_name'), chosen.get('club'), dashboard_url=chosen.get('dashboard_url'), aliases=[chosen.get('display_name')] if chosen.get('display_name') else [])
    result = scrape_player(str(player_id), headless=headless, force_full_refresh=force_full_refresh, refresh_recent_periods=refresh_recent_periods)
    result['search_candidates'] = candidates
    result['search_chosen_candidate'] = chosen
    return result
