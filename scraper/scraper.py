import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from .firebase_service import get_player, save_player
from .player_search import search_players


# =========================================================
# CONFIG
# =========================================================

BASE_URL = "https://www.tennisenpadelvlaanderen.be/nl/dashboard/resultaten?userId={player_id}"

DEBUG_DIR = Path("debug_output")
DEBUG_DIR.mkdir(exist_ok=True)

NETWORK_LOG_JSONL = DEBUG_DIR / "network_log.jsonl"
SCRAPER_LOG_TXT = DEBUG_DIR / "scraper_debug.log"
LAST_HTML_FILE = DEBUG_DIR / "last_page.html"
LAST_SCREENSHOT_FILE = DEBUG_DIR / "last_page.png"

SURNAME_PARTICLES = {
    "de", "den", "der", "van", "vanden", "vander", "ten", "ter", "op", "te",
    "du", "del", "della", "la", "le"
}
SURNAME_PARTICLE_SEQUENCES = {
    ("van", "de"),
    ("van", "den"),
    ("van", "der"),
    ("de", "la"),
}


# =========================================================
# LOGGING
# =========================================================

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
    if not text:
        return ""
    return " ".join(str(text).split()).strip()


def save_debug_snapshot(page, prefix="snapshot"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = DEBUG_DIR / f"{prefix}_{timestamp}.html"
    png_path = DEBUG_DIR / f"{prefix}_{timestamp}.png"
    try:
        html = page.content()
        html_path.write_text(html, encoding="utf-8")
        page.screenshot(path=str(png_path), full_page=True)
        log_line(f"DEBUG snapshot opgeslagen: {html_path.name}, {png_path.name}")
    except Exception as e:
        log_line(f"Kon debug snapshot niet opslaan: {e}")


# =========================================================
# NETWORK LOGGING
# =========================================================

def attach_network_logging(page):
    def on_request(req):
        try:
            if req.resource_type in ("xhr", "fetch"):
                append_jsonl(
                    NETWORK_LOG_JSONL,
                    {
                        "type": "request",
                        "timestamp": utc_now_iso(),
                        "method": req.method,
                        "url": req.url,
                        "resource_type": req.resource_type,
                        "headers": req.headers,
                    },
                )
        except Exception as e:
            log_line(f"NETWORK request log fout: {e}")

    def on_response(res):
        try:
            req = res.request
            if req.resource_type in ("xhr", "fetch"):
                log_line(f"XHR/FETCH response: {res.status} {res.url}")
                record = {
                    "type": "response",
                    "timestamp": utc_now_iso(),
                    "status": res.status,
                    "url": res.url,
                    "resource_type": req.resource_type,
                    "headers": res.headers,
                }
                content_type = res.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        txt = res.text()
                        if txt and len(txt) < 100000:
                            record["body_preview"] = txt[:5000]
                    except Exception as inner_e:
                        record["body_preview_error"] = str(inner_e)
                append_jsonl(NETWORK_LOG_JSONL, record)
        except Exception as e:
            log_line(f"NETWORK response log fout: {e}")

    page.on("request", on_request)
    page.on("response", on_response)


# =========================================================
# PAGE / UI HELPERS
# =========================================================

def detect_robot_page(page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=3000).lower()
        if "ben jij een robot?" in text or "verhoogd aantal geautomatiseerde toegangspogingen" in text:
            return True
    except Exception:
        pass
    return False


def dismiss_cookie_banner_if_present(page):
    texts = ["Alle cookies accepteren", "Cookies accepteren", "Ik ga akkoord", "Accepteren"]
    for txt in texts:
        try:
            locator = page.get_by_text(txt, exact=False)
            if locator.count() > 0:
                locator.first.click(timeout=2000)
                page.wait_for_timeout(1000)
                log_line(f"Cookie-banner knop geklikt: {txt}")
                return
        except Exception:
            pass


def open_dashboard(page, player_id: str):
    url = BASE_URL.format(player_id=player_id)
    log_line(f"Open URL: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)
    dismiss_cookie_banner_if_present(page)
    if detect_robot_page(page):
        save_debug_snapshot(page, prefix="robot_page")
        raise RuntimeError("Robot-check gedetecteerd. Los dit eerst manueel op in de browser.")
    save_debug_snapshot(page, prefix="after_open")
    return url


def try_activate_padel_tab(page):
    candidate_actions = [
        lambda: page.get_by_role("tab", name=re.compile(r"^Padel$", re.I)).click(timeout=3000),
        lambda: page.get_by_role("button", name=re.compile(r"^Padel$", re.I)).click(timeout=3000),
        lambda: page.get_by_role("link", name=re.compile(r"^Padel$", re.I)).click(timeout=3000),
        lambda: page.get_by_text("Padel", exact=True).click(timeout=3000),
    ]
    for i, action in enumerate(candidate_actions, start=1):
        try:
            action()
            page.wait_for_timeout(2500)
            log_line(f"Padel-tab geactiveerd via methode {i}")
            save_debug_snapshot(page, prefix="after_padel_tab")
            return True
        except Exception:
            continue
    log_line("Padel-tab niet expliciet kunnen activeren; ga verder met huidige weergave.")
    return False


def log_all_selects(page, title="SELECT DEBUG"):
    try:
        selects = page.locator("select")
        count = selects.count()
        log_line(f"{title}: totaal selects = {count}")
        for i in range(count):
            sel = selects.nth(i)
            try:
                visible = sel.is_visible()
            except Exception:
                visible = False
            sel_id = sel.get_attribute("id") or ""
            sel_name = sel.get_attribute("name") or ""
            sel_class = sel.get_attribute("class") or ""
            options = sel.locator("option")
            option_count = options.count()
            log_line(
                f"{title}: select[{i}] visible={visible} id='{sel_id}' name='{sel_name}' class='{sel_class}' options={option_count}"
            )
    except Exception as e:
        log_line(f"Kon selects niet loggen: {e}")


# =========================================================
# PERIOD SELECTOR + INCREMENTAL LOGIC
# =========================================================

def get_select_options_from_select(page):
    candidates = []
    try:
        selects = page.locator("select")
        count = selects.count()
        log_line(f"Aantal <select> elementen gevonden: {count}")
        for i in range(count):
            sel = selects.nth(i)
            try:
                visible = sel.is_visible()
            except Exception:
                visible = False
            sel_id = sel.get_attribute("id") or ""
            sel_name = sel.get_attribute("name") or ""
            sel_class = sel.get_attribute("class") or ""
            options = sel.locator("option")
            option_count = options.count()
            names = []
            values = []
            for j in range(option_count):
                try:
                    text = clean_text(options.nth(j).inner_text())
                    value = options.nth(j).get_attribute("value")
                except Exception:
                    continue
                if text:
                    names.append(text)
                    values.append(value)
            period_like = [n for n in names if "resultaten van week" in n.lower()]
            log_line(
                f"SELECT index={i} visible={visible} id='{sel_id}' name='{sel_name}' class='{sel_class}' options={len(names)} period_options={len(period_like)}"
            )
            if len(period_like) >= 2:
                candidates.append({
                    "mode": "select",
                    "index": i,
                    "visible": visible,
                    "id": sel_id,
                    "name": sel_name,
                    "class": sel_class,
                    "options": [{"label": n, "value": v} for n, v in zip(names, values)],
                })
    except Exception as e:
        log_line(f"Fout in get_select_options_from_select: {e}")
        return None

    if not candidates:
        return None

    def score(c):
        txt = f"{c.get('id', '')} {c.get('name', '')}".lower()
        visible_score = 100 if c.get("visible") else 0
        padel_score = 50 if "padel" in txt else 0
        return visible_score + padel_score

    best = sorted(candidates, key=score, reverse=True)[0]
    log_line(
        f"Gekozen periode-select: index={best['index']} visible={best['visible']} id='{best['id']}' name='{best['name']}' met {len(best['options'])} opties"
    )
    return best


def detect_period_selector(page):
    return get_select_options_from_select(page)


def wait_for_results_state(page, period_label: str, timeout_ms: int = 15000):
    start = time.time()
    no_result_patterns = ["geen uitslagen beschikbaar", "geen resultaten beschikbaar", "geen uitslagen"]
    while (time.time() - start) * 1000 < timeout_ms:
        if detect_robot_page(page):
            raise RuntimeError("Robot-check tijdens wachten op resultaten gedetecteerd.")
        try:
            table_count = page.locator("table").count()
        except Exception:
            table_count = 0
        try:
            body_text = clean_text(page.locator("body").inner_text(timeout=1000)).lower()
        except Exception:
            body_text = ""
        if table_count > 0:
            log_line(f"[{period_label}] resultatenstatus: {table_count} tables aanwezig")
            return "tables"
        if any(p in body_text for p in no_result_patterns):
            log_line(f"[{period_label}] resultatenstatus: expliciete 'geen uitslagen'-melding")
            return "empty"
        page.wait_for_timeout(500)
    log_line(f"[{period_label}] resultatenstatus: timeout zonder tables of leegmelding")
    return "timeout"


def select_period(page, selector_info, option):
    label = option["label"]
    value = option["value"]
    if selector_info["mode"] == "select":
        sel = page.locator("select").nth(selector_info["index"])
        try:
            is_visible = sel.is_visible()
        except Exception:
            is_visible = False
        log_line(
            f"Periode selecteren op select index={selector_info['index']} visible={is_visible} id='{selector_info.get('id', '')}' name='{selector_info.get('name', '')}' -> {label}"
        )
        if is_visible:
            try:
                if value is not None:
                    sel.select_option(value=value, timeout=5000)
                else:
                    sel.select_option(label=label, timeout=5000)
                wait_for_results_state(page, label)
                log_line(f"Periode geselecteerd via select_option: {label}")
                return True
            except Exception as e:
                log_line(f"select_option faalde voor '{label}': {e}")
        try:
            js_value = value if value is not None else label
            sel.evaluate(
                """(el, val) => {
                    el.value = val;
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                js_value,
            )
            wait_for_results_state(page, label)
            log_line(f"Periode geselecteerd via JS fallback: {label}")
            return True
        except Exception as e:
            log_line(f"JS fallback faalde voor '{label}': {e}")
            return False
    return False


def determine_periods_to_scrape(all_options: List[Dict], existing_player: Optional[Dict], refresh_recent_periods: int = 2, force_full_refresh: bool = False) -> List[Dict]:
    """
    Incremental strategy:
    - eerste run: scrape alles
    - latere runs: scrape altijd de meest recente N periodes opnieuw,
      plus alle periodes die nog niet eerder verwerkt zijn.

    Waarom deze aanpak:
    - de meest recente periode(s) kunnen nog wijzigen door nieuwe matchen
    - oude periodes zijn meestal stabiel en hoeven niet telkens opnieuw
    """
    if force_full_refresh or not existing_player:
        return all_options

    raw = existing_player.get("raw_data", {}) if isinstance(existing_player, dict) else {}
    already_processed = set(raw.get("periods_processed", []) or [])

    recent = all_options[:refresh_recent_periods]
    not_yet_processed = [o for o in all_options[refresh_recent_periods:] if o.get("label") not in already_processed]

    # combine and preserve order
    labels_seen = set()
    combined = []
    for opt in recent + not_yet_processed:
        label = opt.get("label")
        if label not in labels_seen:
            labels_seen.add(label)
            combined.append(opt)
    return combined


# =========================================================
# NAME PARSING
# =========================================================

def is_header_or_noise(text: str) -> bool:
    t = clean_text(text).lower()
    if not t:
        return True
    noise_patterns = [
        "partner tegenstander klassement ronde w/v uitslag",
        "tegenstander klassement ronde w/v uitslag",
        "geen uitslagen beschikbaar",
        "uitslagen tornooien geen uitslagen beschikbaar",
        "uitslagen interclub geen uitslagen beschikbaar",
        "momenteel organiseert tennis en padel vlaanderen nog geen pickleball competities",
    ]
    return any(p in t for p in noise_patterns)


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
    score = 0.0
    if len(tokens) == 2:
        score += 5.0
    elif len(tokens) == 3:
        score += 4.0
    elif len(tokens) == 4:
        score += 3.0
    elif len(tokens) == 5:
        score += 1.0
    if all(is_name_token(t) for t in tokens):
        score += 2.0
    else:
        score -= 4.0
    surname_tokens = tokens[:-1]
    lowered = [t.lower() for t in surname_tokens]
    particle_count = sum(1 for t in lowered if t in SURNAME_PARTICLES)
    score += particle_count * 1.0
    for i in range(len(lowered) - 1):
        pair = (lowered[i], lowered[i + 1])
        if pair in SURNAME_PARTICLE_SEQUENCES:
            score += 3.0
    if len(tokens) == 2 and is_particle(tokens[0]):
        score -= 20.0
    if surname_tokens and is_particle(surname_tokens[-1]):
        score -= 10.0
    for tok in surname_tokens:
        if is_particle(tok):
            score += 0.2
        elif is_capitalized_name_token(tok):
            score += 0.5
        else:
            score -= 2.0
    return score


def split_names_into_players(names_text: str) -> Tuple[Optional[str], Optional[str], Optional[str], List[str]]:
    names_text = clean_text(names_text)
    if not names_text:
        return None, None, None, []
    tokens = names_text.split()
    n = len(tokens)
    best = None
    best_score = -10_000.0
    for i in range(2, min(6, n - 3) + 1):
        for j in range(i + 2, min(i + 5, n - 1) + 1):
            g1 = tokens[:i]
            g2 = tokens[i:j]
            g3 = tokens[j:]
            if len(g1) < 2 or len(g2) < 2 or len(g3) < 2:
                continue
            if len(g1) > 5 or len(g2) > 5 or len(g3) > 5:
                continue
            score = score_name_group(g1) + score_name_group(g2) + score_name_group(g3)
            lengths = [len(g1), len(g2), len(g3)]
            score -= (max(lengths) - min(lengths)) * 0.3
            if score > best_score:
                best_score = score
                best = (g1, g2, g3)
    if best:
        g1, g2, g3 = best
        players = [" ".join(g1), " ".join(g2), " ".join(g3)]
        return players[0], players[1], players[2], players
    if n >= 6:
        partner = " ".join(tokens[:2])
        opp1 = " ".join(tokens[2:4])
        opp2 = " ".join(tokens[4:]) if len(tokens[4:]) >= 2 else None
        players = [p for p in [partner, opp1, opp2] if p]
        return partner, opp1, opp2, players
    return None, None, None, [names_text]


def parse_row_structured(row_text: str) -> Dict[str, Optional[str]]:
    row_text = clean_text(row_text)
    parsed = {
        "raw_text": row_text,
        "names_text": None,
        "partner_name": None,
        "opponent_1_name": None,
        "opponent_2_name": None,
        "all_detected_players": [],
        "ranking_player_or_team": None,
        "ranking_opponents": None,
        "round_text": None,
        "result_letter": None,
        "result_text": None,
        "score": None,
        "won": None,
    }

    pattern = re.compile(
        r"^(?P<names>.+?)\s+"
        r"(?P<ranking1>P\d+)\s+"
        r"(?P<ranking2>P\d+)\s+"
        r"(?P<round>.+?)\s+"
        r"(?P<result>[WV])\s+"
        r"(?P<score>.+)$"
    )
    m = pattern.match(row_text)
    if m:
        names_text = clean_text(m.group("names"))
        partner, opp1, opp2, players = split_names_into_players(names_text)
        result_letter = m.group("result")
        won = True if result_letter == "W" else False if result_letter == "V" else None
        parsed.update(
            {
                "names_text": names_text,
                "partner_name": partner,
                "opponent_1_name": opp1,
                "opponent_2_name": opp2,
                "all_detected_players": players,
                "ranking_player_or_team": m.group("ranking1"),
                "ranking_opponents": m.group("ranking2"),
                "round_text": clean_text(m.group("round")),
                "result_letter": result_letter,
                "result_text": "Winst" if result_letter == "W" else "Verlies",
                "score": clean_text(m.group("score")),
                "won": won,
            }
        )
        return parsed

    m2 = re.search(r"\b([WV])\b\s+(.+)$", row_text)
    if m2:
        result_letter = m2.group(1)
        won = True if result_letter == "W" else False if result_letter == "V" else None
        score = clean_text(m2.group(2))
        before = clean_text(row_text[:m2.start()])
        rankings = re.findall(r"\bP\d+\b", before)
        names_text = re.split(r"\bP\d+\b", before)[0].strip() if rankings else before
        round_text = None
        if len(rankings) >= 2:
            tail = before.split(rankings[1], 1)
            if len(tail) > 1:
                round_candidate = clean_text(tail[1])
                round_text = round_candidate if round_candidate else None
        partner, opp1, opp2, players = split_names_into_players(names_text)
        parsed.update(
            {
                "names_text": names_text or before,
                "partner_name": partner,
                "opponent_1_name": opp1,
                "opponent_2_name": opp2,
                "all_detected_players": players,
                "ranking_player_or_team": rankings[0] if len(rankings) >= 1 else None,
                "ranking_opponents": rankings[1] if len(rankings) >= 2 else None,
                "round_text": round_text,
                "result_letter": result_letter,
                "result_text": "Winst" if result_letter == "W" else "Verlies",
                "score": score,
                "won": won,
            }
        )
    return parsed


def dedupe_matches(matches: List[Dict]) -> List[Dict]:
    seen = set()
    unique = []
    for m in matches:
        key = (m.get("period"), m.get("raw_text"))
        if key not in seen:
            seen.add(key)
            unique.append(m)
    return unique


def calculate_stats(matches: List[Dict]) -> Dict[str, float]:
    wins = sum(1 for m in matches if m.get("won") is True)
    losses = sum(1 for m in matches if m.get("won") is False)
    unknown = sum(1 for m in matches if m.get("won") is None)
    known = wins + losses
    winrate = round((wins / known) * 100, 2) if known > 0 else 0.0
    return {
        "matches": len(matches),
        "wins": wins,
        "losses": losses,
        "unknown_results": unknown,
        "winrate": winrate,
    }


def collect_structured_rows(page, current_period: str) -> List[Dict]:
    matches = []
    state = wait_for_results_state(page, current_period, timeout_ms=12000)
    if state in ("empty", "timeout"):
        if state == "empty":
            log_line(f"[{current_period}] Geen uitslagen beschikbaar voor deze periode")
        else:
            log_line(f"[{current_period}] Timeout tijdens wachten op resultaten")
        return matches
    try:
        page.wait_for_selector("table", state="attached", timeout=5000)
    except PlaywrightTimeoutError:
        log_line(f"Geen table gevonden voor periode: {current_period}")
        return matches

    tables = page.locator("table")
    table_count = tables.count()
    log_line(f"[{current_period}] aantal tabellen gevonden: {table_count}")
    for t in range(table_count):
        table = tables.nth(t)
        rows = table.locator("tr")
        row_count = rows.count()
        log_line(f"[{current_period}] tabel {t + 1}/{table_count}: {row_count} rijen")
        for r in range(row_count):
            try:
                row_text = clean_text(rows.nth(r).inner_text(timeout=2000))
                if is_header_or_noise(row_text):
                    continue
                parsed = parse_row_structured(row_text)
                parsed.update({"period": current_period, "table_index": t, "row_index": r})
                matches.append(parsed)
            except Exception as e:
                log_line(f"Fout bij lezen/parsen rij {r} in tabel {t}: {e}")
    return matches


def merge_incremental_data(existing_player: Optional[Dict], new_matches: List[Dict], periods_processed_now: List[str], empty_periods_now: List[str], failed_periods_now: List[str], scrape_mode: str, refresh_recent_periods: int) -> Dict:
    existing_raw = existing_player.get("raw_data", {}) if isinstance(existing_player, dict) else {}
    existing_matches = existing_raw.get("matches", []) if isinstance(existing_raw, dict) else []

    # Incremental strategy:
    # - keep older untouched matches
    # - replace periods that were re-scraped this run
    periods_replaced = set(periods_processed_now)
    preserved_old = [m for m in existing_matches if m.get("period") not in periods_replaced]
    combined_matches = dedupe_matches(preserved_old + new_matches)

    all_periods = []
    seen_periods = set()
    for p in (periods_processed_now + existing_raw.get("periods_processed", [])):
        if p not in seen_periods:
            seen_periods.add(p)
            all_periods.append(p)

    all_empty = []
    seen_empty = set()
    for p in (empty_periods_now + existing_raw.get("empty_periods", [])):
        if p not in seen_empty:
            seen_empty.add(p)
            all_empty.append(p)

    all_failed = []
    seen_failed = set()
    for p in (failed_periods_now + existing_raw.get("failed_periods", [])):
        if p not in seen_failed:
            seen_failed.add(p)
            all_failed.append(p)

    stats = calculate_stats(combined_matches)
    now_iso = utc_now_iso()

    # useful incremental metadata
    raw_data = {
        "player_id": existing_player.get("player_id") if existing_player else None,
        "timestamp": now_iso,
        "matches_count": len(combined_matches),
        "schema_version": "v4_incremental_structured_matches",
        "periods_processed": all_periods,
        "empty_periods": all_empty,
        "failed_periods": all_failed,
        "network_log_file": str(NETWORK_LOG_JSONL),
        "debug_log_file": str(SCRAPER_LOG_TXT),
        "matches": combined_matches,
        "scrape_mode": scrape_mode,
        "incremental_settings": {
            "refresh_recent_periods": refresh_recent_periods,
        },
        "last_incremental_scrape": now_iso,
        "last_scraped_periods_this_run": periods_processed_now,
    }

    return {
        "last_updated": now_iso,
        "stats": stats,
        "raw_data": raw_data,
    }


# =========================================================
# MAIN SCRAPER - BY ID / BY NAME
# =========================================================

def scrape_player(player_id: str, headless: bool = False, max_periods=None, force_full_refresh: bool = False, refresh_recent_periods: int = 2):
    """
    V4 scraper met incrementele updates.

    Gedrag:
    - eerste run: scrape alle periodes
    - volgende runs: scrape enkel nieuwe periodes + de meest recente N periodes opnieuw

    Waarom recente periodes opnieuw?
    Omdat daar nog nieuwe matchen kunnen bijkomen.
    """
    for p in [NETWORK_LOG_JSONL, SCRAPER_LOG_TXT]:
        if p.exists():
            p.unlink()

    existing_player = get_player(player_id)
    if existing_player:
        log_line(f"Bestaande spelerdata gevonden voor {player_id}")
    else:
        log_line(f"Geen bestaande spelerdata gevonden voor {player_id}; volledige eerste scrape")

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
            log_all_selects(page, title="NA PADEL TAB")

            if detect_robot_page(page):
                save_debug_snapshot(page, prefix="robot_after_tab")
                raise RuntimeError("Robot-check na tabwissel gedetecteerd.")

            selector_info = detect_period_selector(page)
            if not selector_info:
                log_line("Geen periode-selector gevonden. Ik scrape alleen de huidige zichtbare periode.")
                current_matches = collect_structured_rows(page, current_period="HUIDIGE_PERIODE")
                new_matches.extend(current_matches)
                processed_periods_now.append("HUIDIGE_PERIODE")
            else:
                options = [o for o in selector_info["options"] if "resultaten van week" in o["label"].lower()]
                if max_periods is not None:
                    options = options[:max_periods]

                options_to_scrape = determine_periods_to_scrape(
                    all_options=options,
                    existing_player=existing_player,
                    refresh_recent_periods=refresh_recent_periods,
                    force_full_refresh=force_full_refresh,
                )

                scrape_mode = "full_refresh" if (force_full_refresh or not existing_player) else "incremental"
                log_line(f"Scrape mode: {scrape_mode}")
                log_line(f"Totaal beschikbare periodes: {len(options)}")
                log_line(f"Totaal periodes te scrapen deze run: {len(options_to_scrape)}")
                log_line(f"Refresh recent periods instelling: {refresh_recent_periods}")

                for idx, option in enumerate(options_to_scrape, start=1):
                    label = option["label"]
                    log_line(f"--- Periode {idx}/{len(options_to_scrape)}: {label} ---")
                    ok = select_period(page, selector_info, option)
                    if not ok:
                        log_line(f"Periode overgeslagen wegens selectiefout: {label}")
                        failed_periods_now.append(label)
                        continue

                    if detect_robot_page(page):
                        save_debug_snapshot(page, prefix="robot_during_periods")
                        raise RuntimeError("Robot-check tijdens periodewissel gedetecteerd.")

                    save_debug_snapshot(page, prefix=f"period_{idx}")
                    period_matches = collect_structured_rows(page, current_period=label)
                    log_line(f"[{label}] opgehaalde rijen (voor dedupe): {len(period_matches)}")

                    if period_matches:
                        new_matches.extend(period_matches)
                    else:
                        empty_periods_now.append(label)
                    processed_periods_now.append(label)

            scrape_mode = "full_refresh" if (force_full_refresh or not existing_player) else "incremental"
            final_doc = merge_incremental_data(
                existing_player=existing_player,
                new_matches=new_matches,
                periods_processed_now=processed_periods_now,
                empty_periods_now=empty_periods_now,
                failed_periods_now=failed_periods_now,
                scrape_mode=scrape_mode,
                refresh_recent_periods=refresh_recent_periods,
            )
            final_doc["player_id"] = str(player_id)
            save_player(player_id, final_doc)

            log_line(f"✅ Player opgeslagen: {player_id}")
            log_line(f"✅ Unieke matches totaal: {final_doc['stats']['matches']}")
            log_line(f"✅ Stats: {final_doc['stats']}")
            return {"player_id": str(player_id), **final_doc}

        finally:
            try:
                LAST_HTML_FILE.write_text(page.content(), encoding="utf-8")
                page.screenshot(path=str(LAST_SCREENSHOT_FILE), full_page=True)
            except Exception:
                pass
            context.close()
            browser.close()
            log_line("Browser gesloten")


def find_player_and_scrape(name_query: str, club: Optional[str] = None, sport: str = "Padel", headless: bool = False, force_full_refresh: bool = False, refresh_recent_periods: int = 2):
    """
    Zoekt eerst speler op naam en scrapt daarna zijn resultaten.

    Als meerdere kandidaten gevonden worden:
    - de functie kiest hier voorlopig de eerste
    - maar returnt ook de volledige kandidatenlijst zodat je later kunt disambigueren in de UI.
    """
    candidates = search_players(name_query=name_query, club=club, sport=sport, headless=headless, use_cache=True)
    if not candidates:
        raise RuntimeError(f"Geen spelers gevonden voor query: {name_query}")

    chosen = candidates[0]
    player_id = chosen.get("player_id")
    if not player_id:
        raise RuntimeError(f"Geen player_id gevonden in eerste kandidaat voor query: {name_query}")

    result = scrape_player(
        player_id=str(player_id),
        headless=headless,
        max_periods=None,
        force_full_refresh=force_full_refresh,
        refresh_recent_periods=refresh_recent_periods,
    )
    result["search_candidates"] = candidates
    result["search_chosen_candidate"] = chosen
    return result


# =========================================================
# DIRECT TEST
# =========================================================

if __name__ == "__main__":
    player_id = "1790766"
    result = scrape_player(
        player_id=player_id,
        headless=False,
        max_periods=None,
        force_full_refresh=False,
        refresh_recent_periods=2,
    )
    print("\n=== RESULTAAT V4 ===")
    print(json.dumps(result["stats"], indent=2, ensure_ascii=False))
