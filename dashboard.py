"""
dashboard.py  —  PadelAnalysis v2 Streamlit dashboard

Schema v2: matches zitten in doc.matches (niet doc.raw_data.matches)
Stats: total_matches, tournament_matches, interclub_matches, wins, losses, winrate
"""

import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

# Path setup
_ROOT = Path(__file__).parent
for _p in [str(_ROOT), str(_ROOT / "scraper")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import firebase_service as fb
import lineup_lab as ll
import schedule_scraper as ss
import opponent_scout as osc

st.set_page_config(
    page_title="Padel Analysis",
    page_icon="🎾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────
# Custom CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
/* Clean card-style metric */
[data-testid="stMetric"] {
    background: #f8f9fa;
    border-radius: 10px;
    padding: 12px 16px;
    border-left: 4px solid #1a73e8;
}
[data-testid="stMetricLabel"] { font-size: 0.75rem; color: #666; }
[data-testid="stMetricValue"] { font-size: 1.5rem; font-weight: 700; }

/* Tab styling */
.stTabs [data-baseweb="tab"] { font-size: 0.85rem; padding: 6px 14px; }
.stTabs [aria-selected="true"] { border-bottom: 3px solid #1a73e8 !important; }

/* Win badge */
.badge-win  { background:#d4edda; color:#155724; border-radius:4px; padding:2px 8px; font-size:0.8rem; font-weight:600; }
.badge-loss { background:#f8d7da; color:#721c24; border-radius:4px; padding:2px 8px; font-size:0.8rem; font-weight:600; }

/* Section header */
.section-header { font-size:1.1rem; font-weight:700; margin-bottom:8px; color:#1a1a1a; border-bottom:2px solid #e0e0e0; padding-bottom:4px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _clean(text) -> str:
    return " ".join(str(text or "").split()).strip()


def _period_sort_key(label: str):
    m = re.search(r"week\s+(\d+)/(\d{4})", str(label).lower())
    return (int(m.group(2)), int(m.group(1))) if m else (9999, 999)


def _matches_to_df(matches: list) -> pd.DataFrame:
    """Convert v2 match list to a clean DataFrame."""
    if not matches:
        return pd.DataFrame()
    rows = []
    for m in matches:
        rows.append({
            "type":            m.get("match_type", ""),
            "period":          m.get("period_label", ""),
            "datum":           m.get("tournament_date_start") or m.get("match_date") or "",
            "week":            m.get("tournament_week") or "",
            "toernooi":        m.get("tournament_name") or m.get("competition_name") or "",
            "reeks":           m.get("reeks_name") or "",
            "ronde":           m.get("round_text") or "",
            "partner":         m.get("partner_name") or "",
            "partner_id":      m.get("partner_user_id") or "",
            "opp1":            m.get("opp1_name") or "",
            "opp1_id":         m.get("opp1_user_id") or "",
            "opp2":            m.get("opp2_name") or "",
            "opp2_id":         m.get("opp2_user_id") or "",
            "opp1_ranking":    m.get("opp1_ranking") or "",
            "opp2_ranking":    m.get("opp2_ranking") or "",
            "score":           m.get("score") or "",
            "result":          m.get("result") or "",
            "won":             m.get("won"),
            "reeks_url":       m.get("reeks_url") or "",
            "reeks_id":        m.get("reeks_id") or "",
            "tornooi_id":      m.get("tornooi_id") or "",
            "encounter":       m.get("encounter") or "",
            "uitslagenblad":   m.get("uitslagenblad_url") or "",
        })
    return pd.DataFrame(rows)


def _winrate_str(wins, losses) -> str:
    known = wins + losses
    if known == 0:
        return "–"
    return f"{round(wins / known * 100, 1)}%"


def _render_metrics(total, wins, losses, t_matches, ic_matches):
    cols = st.columns(5)
    cols[0].metric("Totaal matches", total)
    cols[1].metric("Winst", wins)
    cols[2].metric("Verlies", losses)
    cols[3].metric("Winrate", _winrate_str(wins, losses))
    cols[4].metric("Tornooi / Interclub", f"{t_matches} / {ic_matches}")


def _summarize_partner(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "partner" not in df.columns:
        return pd.DataFrame()
    sub = df[df["partner"].str.strip().ne("")].copy()
    if sub.empty:
        return pd.DataFrame()
    g = sub.groupby("partner").agg(
        matches=("won", "count"),
        wins=("won", lambda x: x.eq(True).sum()),
        losses=("won", lambda x: x.eq(False).sum()),
    ).reset_index()
    g["winrate"] = g.apply(lambda r: _winrate_str(r.wins, r.losses), axis=1)
    return g.sort_values(["wins", "matches"], ascending=False)


def _summarize_opponents(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    rows = []
    for _, r in df.iterrows():
        for col in ["opp1", "opp2"]:
            name = str(r.get(col, "")).strip()
            if name:
                rows.append({"tegenstander": name, "won": r.get("won")})
    if not rows:
        return pd.DataFrame()
    tmp = pd.DataFrame(rows)
    g = tmp.groupby("tegenstander").agg(
        matches=("won", "count"),
        wins=("won", lambda x: x.eq(True).sum()),
        losses=("won", lambda x: x.eq(False).sum()),
    ).reset_index()
    g["winrate"] = g.apply(lambda r: _winrate_str(r.wins, r.losses), axis=1)
    return g.sort_values(["wins", "matches"], ascending=False)


def _render_table(df: pd.DataFrame, name_col: str, height=400):
    if df.empty:
        st.info("Geen data beschikbaar.")
        return
    st.dataframe(
        df,
        use_container_width=True,
        height=min(height, 40 + len(df) * 36),
        column_config={
            name_col: st.column_config.TextColumn(name_col, width="large"),
            "matches": st.column_config.NumberColumn("M", width="small"),
            "wins":    st.column_config.NumberColumn("W", width="small"),
            "losses":  st.column_config.NumberColumn("L", width="small"),
            "winrate": st.column_config.TextColumn("Winrate", width="small"),
        },
    )


# ─────────────────────────────────────────────
# State helpers
# ─────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner="Wedstrijdschema ophalen...")
def _load_poule_fixtures(reeks_url: str):
    """Haalt en parset het publieke poule-schema. Returns (fixtures, error_message_or_None)."""
    try:
        html = ss.fetch_poule_schedule_html(reeks_url, delay=0.5)
        fixtures = ss.parse_poule_schedule(html)
        return fixtures, None
    except Exception as e:
        return [], str(e)


def _clean_name(text: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _get_all_profiles() -> list:
    try:
        docs = fb.db.collection(fb.PLAYER_PROFILES_COLLECTION).stream()
        return [d.to_dict() for d in docs]
    except Exception:
        return []


# ─────────────────────────────────────────────
# Navigation
# ─────────────────────────────────────────────

PAGES = ["📊 Speler", "➕ Speler toevoegen", "🧩 Opstelling-analyse", "🔄 Scrapen"]

if "page" not in st.session_state:
    st.session_state["page"] = PAGES[0]

# Top nav bar
nav_col = st.columns(len(PAGES))
for i, p in enumerate(PAGES):
    if nav_col[i].button(p, use_container_width=True,
                          type="primary" if st.session_state["page"] == p else "secondary"):
        st.session_state["page"] = p
        st.rerun()

st.divider()
page = st.session_state["page"]


# ═══════════════════════════════════════════════
# PAGE: Speler toevoegen
# ═══════════════════════════════════════════════

def page_add_player():
    st.header("➕ Speler toevoegen")
    st.caption("Zoek een speler op de TVL-website en voeg hem/haar toe aan de database.")

    with st.form("search_form"):
        c1, c2, c3 = st.columns([2, 2, 2])
        first = c1.text_input("Voornaam")
        last  = c2.text_input("Achternaam")
        club  = c3.text_input("Club (optioneel)")
        submitted = st.form_submit_button("🔍 Zoek op TVL-website", use_container_width=True, type="primary")

    if submitted:
        if not _clean(first) and not _clean(last):
            st.warning("Geef minstens een voornaam of achternaam in.")
            return

        with st.spinner("Zoeken op tennisenpadelvlaanderen.be..."):
            try:
                from player_search import search_players
                candidates = search_players(
                    first_name=first, last_name=last,
                    club=_clean(club) or None,
                    headless=True, use_cache=False,
                )
                st.session_state["add_candidates"] = candidates
                st.session_state["add_search_done"] = True
            except Exception as e:
                st.error(f"Zoekfout: {e}")
                return

    candidates = st.session_state.get("add_candidates", [])
    if not st.session_state.get("add_search_done"):
        return

    if not candidates:
        st.warning("Geen spelers gevonden op TVL.")
        return

    st.success(f"{len(candidates)} kandidaat(en) gevonden")

    for i, c in enumerate(candidates):
        name = c.get("display_name") or "?"
        club_str = c.get("club") or ""
        pid = c.get("player_id") or "?"
        url = c.get("dashboard_url") or ""

        with st.container(border=True):
            col_info, col_btn = st.columns([4, 1])
            with col_info:
                st.markdown(f"**{name}**")
                if club_str:
                    st.caption(f"🏟️ {club_str} · ID: {pid}")
                else:
                    st.caption(f"ID: {pid}")
                if url:
                    st.markdown(f"[Profiel op TVL ↗]({url})", unsafe_allow_html=False)
            with col_btn:
                scrape_key = f"scrape_{i}"
                do_scrape = st.checkbox("Direct scrapen", key=scrape_key, value=True)
                if st.button("➕ Toevoegen", key=f"add_{i}", use_container_width=True, type="primary"):
                    # Save profile
                    fb.save_player_profile(
                        player_id=str(pid),
                        display_name=name,
                        club=club_str or None,
                        dashboard_url=url or None,
                        aliases=[name],
                    )
                    if do_scrape:
                        with st.spinner(f"Scraping {name}..."):
                            try:
                                from scrape_player import scrape_player as _scrape
                                result = _scrape(str(pid), save_to_firebase=True)
                                s = result.get("stats", {})
                                st.success(
                                    f"✅ {name} toegevoegd — "
                                    f"{s.get('total_matches',0)} matches, "
                                    f"winrate {s.get('winrate',0)}%"
                                )
                            except Exception as e:
                                st.warning(f"Profiel opgeslagen, scrape mislukt: {e}")
                    else:
                        st.success(f"✅ {name} toegevoegd (nog niet gescraped)")


# ═══════════════════════════════════════════════
# PAGE: Opstelling-analyse (Fase 1 — retrospectieve test-tool)
# ═══════════════════════════════════════════════

@st.cache_data(ttl=600, show_spinner="Ontmoetingen ophalen...")
def _load_encounter_index(profile_ids: tuple):
    docs = ll.get_docs_for_players(list(profile_ids))
    index = ll.build_encounter_index(docs)
    return docs, index


def page_lineup_lab():
    st.header("🧩 Opstelling-analyse")
    st.caption(
        "Fase 1 — test-tool op basis van reeds gespeelde interclub-ontmoetingen, "
        "aangevuld met een 'volgende match'-verkenner op basis van het publieke wedstrijdschema."
    )

    profiles = _get_all_profiles()
    if not profiles:
        st.info("Nog geen spelers in de database. Voeg eerst spelers toe via '➕ Speler toevoegen'.")
        return

    name_lookup_global = {p.get("player_id"): p.get("display_name", p.get("player_id")) for p in profiles}

    # ═══════════════════════════════════════
    # Volgende match (op basis van het publieke wedstrijdschema)
    # ═══════════════════════════════════════
    st.markdown('<div class="section-header">📅 Volgende match</div>', unsafe_allow_html=True)
    settings = fb.get_app_settings()
    home_id = settings.get("home_player_id")

    if not home_id:
        st.info("Stel eerst 'Dit ben ik' in op de '📊 Speler'-pagina, dan kan ik hier je volgende match opzoeken.")
    else:
        home_doc = fb.get_player(home_id)
        own_interclub_matches = [
            m for m in (home_doc or {}).get("matches", [])
            if m.get("match_type") == "interclub" and m.get("reeks_url")
        ]
        if not own_interclub_matches:
            st.info("Geen interclub-matches met een poule-link gevonden in jouw profiel. Scrape je profiel eerst (zie '📊 Speler').")
        else:
            most_recent = sorted(own_interclub_matches, key=lambda m: m.get("match_date") or "", reverse=True)[0]
            reeks_url = most_recent["reeks_url"]

            try:
                fixtures, fetch_error = _load_poule_fixtures(reeks_url)
            except Exception as e:
                fixtures, fetch_error = [], str(e)

            if fetch_error:
                st.warning(f"Kon het wedstrijdschema niet ophalen: {fetch_error}")
            elif not fixtures:
                st.warning("Geen wedstrijden gevonden op de poule-pagina (onverwachte paginastructuur?).")
            else:
                home_ploeg_id, away_ploeg_id, matched_fx = ss.identify_own_ploeg_id(fixtures, own_interclub_matches)
                own_ploeg_id = None
                if matched_fx:
                    # bepaal welke kant van de gematchte fixture WIJ zijn via de tegenstandersnaam in onze eigen data
                    opp_names_known = {(_clean_name(m.get("opp1_name"))) for m in own_interclub_matches if m.get("opp1_name")}
                    if _clean_name(matched_fx["away_name"]) in opp_names_known or any(
                        _clean_name(matched_fx["away_name"]) in _clean_name(n) for n in opp_names_known
                    ):
                        own_ploeg_id = home_ploeg_id
                    else:
                        own_ploeg_id = away_ploeg_id

                if not own_ploeg_id:
                    st.warning(
                        "Kon niet zeker bepalen welke ploeg 'wij' zijn op de poule-pagina "
                        "(geen overeenkomende datum/score gevonden). Mogelijk is dit nog niet dezelfde reeks, "
                        "of week het scoreformaat af van wat ik verwachtte."
                    )
                else:
                    team_fixtures = ss.get_team_fixtures(fixtures, own_ploeg_id)
                    next_match = ss.get_next_match(team_fixtures)

                    if not next_match:
                        st.success("Geen nog te spelen wedstrijden gevonden — seizoen voor jouw ploeg is voorbij (of het schema toont nog niets).")
                    else:
                        opp = ss.opponent_of(next_match, own_ploeg_id)
                        st.markdown(f"**{next_match['date_text']}** — tegen **{opp['name']}** ({next_match['poule_label']})")

                        scout_key = f"scout_{opp['ploeg_id']}_{next_match['date_text']}"
                        if st.button("🔍 Tegenstander analyseren", key="btn_scout"):
                            with st.spinner("Vorige wedstrijd(en) van de tegenstander opzoeken..."):
                                bundle = osc.scout_opponent(
                                    fixtures, opp["name"], opp["ploeg_id"], next_match["date_text"], lookback=1
                                )
                            st.session_state[scout_key] = bundle

                        bundle = st.session_state.get(scout_key)
                        if bundle:
                            if bundle["note"]:
                                st.info(bundle["note"])
                            else:
                                st.write("Gebaseerd op hun vorige wedstrijd: gevonden spelers —")
                                unknown = [p for p in bundle["unique_players"] if not fb.get_player_profile(p["user_id"])]
                                known = [p for p in bundle["unique_players"] if fb.get_player_profile(p["user_id"])]
                                for p in bundle["unique_players"]:
                                    status = "✅ al gekend" if p in known else "❓ nog niet gescraped"
                                    st.write(f"  • {p['name']} — {status}")

                                if unknown and st.button(f"📥 Scrape {len(unknown)} nieuwe tegenstander(s)", key="btn_scrape_opp"):
                                    progress = st.progress(0.0, text="Starten...")
                                    def _cb(i, total, name):
                                        progress.progress(i / total, text=f"({i}/{total}) {name} scrapen...")
                                    result = osc.scrape_new_opponent_players(unknown, lookback_periods=1, delay=1.5, progress_callback=_cb)
                                    progress.progress(1.0, text="Klaar.")
                                    st.success(f"{len(result['newly_scraped'])} gescraped, {len(result['failed'])} mislukt.")
                                    if result["failed"]:
                                        for f in result["failed"]:
                                            st.write(f"  ❌ {f['name']}: {f['error']}")
                                    st.rerun()

    st.divider()

    # ═══════════════════════════════════════
    # Retrospectieve analyse (Fase 1 — bestaand)
    # ═══════════════════════════════════════
    st.markdown('<div class="section-header">🕰️ Retrospectieve analyse (eerder gespeelde ontmoetingen)</div>', unsafe_allow_html=True)
    name_lookup = name_lookup_global

    profile_ids = tuple(sorted(p.get("player_id") for p in profiles if p.get("player_id")))
    if st.button("🔄 Ontmoetingen vernieuwen"):
        _load_encounter_index.clear()

    docs, index = _load_encounter_index(profile_ids)
    encounters = ll.list_encounters(index)

    if not encounters:
        st.info(
            "Geen interclub-ontmoetingen gevonden in de gescrapete data van je spelers. "
            "Zodra er interclub-matches gescraped zijn, duiken ze hier op."
        )
        return

    labels = [lbl for _, lbl in encounters]
    chosen_label = st.selectbox("Kies een eerder gespeelde ontmoeting", labels)
    key = next(k for k, lbl in encounters if lbl == chosen_label)

    entries = index[key]
    boards = ll.reconstruct_boards(entries)
    if not boards:
        st.warning("Kon geen geldige boards reconstrueren voor deze ontmoeting (ontbrekende data).")
        return

    actual_required = ll.required_counts_from_boards(boards)
    players = list(actual_required.keys())

    st.markdown('<div class="section-header">Werkelijk gespeelde opstelling</div>', unsafe_allow_html=True)
    board_rows = []
    for b in sorted(boards, key=lambda x: (x.get("round_text") or "")):
        p1, p2 = tuple(b["pair"])
        board_rows.append({
            "Ronde": b.get("round_text") or "–",
            "Koppel": f"{name_lookup.get(p1,p1)} / {name_lookup.get(p2,p2)}",
            "Tegen": f"{b.get('opp1_name','?')} / {b.get('opp2_name','?')}",
            "Score": b.get("score") or "–",
            "W/V": b.get("result") or "–",
        })
    st.dataframe(pd.DataFrame(board_rows), use_container_width=True, hide_index=True)

    exclude_keys = {b["dedupe_key"] for b in boards}
    synergy = ll.compute_pairwise_synergy(docs, players, exclude_match_keys=exclude_keys)
    score_fn = ll.make_pair_score_fn(synergy, docs)
    actual_score = ll.score_actual_lineup(boards, score_fn)

    st.metric(
        "Synergie-score van de werkelijke opstelling",
        actual_score,
        help="Som van de partner-winrates (of, bij gebrek aan gezamenlijke historie, het gemiddelde van "
             "de individuele winrates) van elk gespeeld koppel. Hoger = sterker op basis van historische data. "
             "De ontmoeting die je hier bekijkt is zelf uitgesloten uit deze berekening."
    )

    st.divider()

    # ── Wat-als parameters ──
    st.markdown('<div class="section-header">Wat als... (aantal wedstrijden per speler aanpassen)</div>', unsafe_allow_html=True)
    st.caption(
        "Standaard staat dit op het aantal wedstrijden dat elke speler die dag écht speelde. "
        "Zet een speler op 0 om te zien hoe de opstelling zou veranderen zonder die speler "
        "(de vrijgekomen wedstrijden moet je dan wel zelf verdelen over de anderen)."
    )
    total_boards = len(boards)
    cols = st.columns(min(len(players), 6) or 1)
    overrides = {}
    for i, p in enumerate(players):
        with cols[i % len(cols)]:
            overrides[p] = st.number_input(
                name_lookup.get(p, p),
                min_value=0, max_value=total_boards,
                value=actual_required[p],
                step=1, key=f"override_{key}_{p}",
            )

    total_override = sum(overrides.values())
    if total_override == 0:
        st.warning("Geef minstens enkele spelers wedstrijden om een opstelling te kunnen berekenen.")
        return
    if total_override % 2 != 0:
        st.error(
            f"Het totaal aantal wedstrijd-slots moet even zijn (elke wedstrijd = 2 spelers). "
            f"Huidig totaal: {total_override}. Pas een speler met ±1 aan."
        )
        return

    if st.button("🧮 Beste opstelling(en) berekenen", type="primary"):
        with st.spinner("Mogelijke opstellingen doorrekenen..."):
            results, truncated = ll.optimize_lineup(players, overrides, score_fn, top_n=5)

        if truncated:
            st.caption(
                "⚠️ Grote zoekruimte — resultaten zijn gebaseerd op een beperkte zoekdiepte, "
                "niet gegarandeerd het absolute optimum."
            )

        if not results:
            st.warning(
                "Geen geldige opstelling gevonden binnen deze beperkingen "
                "(bv. te weinig spelers om iedereen een andere partner te geven)."
            )
        else:
            st.markdown('<div class="section-header">Berekende alternatieven</div>', unsafe_allow_html=True)
            is_same_as_actual = overrides == actual_required
            for rank, (score, pairs) in enumerate(results, start=1):
                delta = score - actual_score
                delta_str = f"({'+' if delta >= 0 else ''}{delta:.2f} t.o.v. werkelijk)" if is_same_as_actual else ""
                with st.expander(f"#{rank} — score {score} {delta_str}", expanded=(rank == 1)):
                    for pair in pairs:
                        p1, p2 = tuple(pair)
                        st.write(f"• {name_lookup.get(p1,p1)} / {name_lookup.get(p2,p2)} "
                                 f"(synergie: {score_fn(p1,p2):.2f})")

    st.divider()
    st.caption(
        "📌 Volgende fases (later): een manuele modus om een opstelling samen te stellen vóór een nog niet "
        "gespeelde wedstrijddag, en een modus die het wedstrijdschema automatisch ophaalt."
    )




# ═══════════════════════════════════════════════
# PAGE: Scrapen
# ═══════════════════════════════════════════════

def page_scrape():
    st.header("🔄 Scrapen")

    profiles = _get_all_profiles()

    if not profiles:
        st.info("Geen spelers in database. Voeg eerst spelers toe via '➕ Speler toevoegen'.")
        return

    st.subheader("Individuele speler")
    profile_options = {
        f"{p.get('display_name','?')} ({p.get('player_id','?')})": p.get("player_id")
        for p in sorted(profiles, key=lambda x: x.get("display_name") or "")
    }
    chosen_label = st.selectbox("Kies speler", list(profile_options.keys()))
    chosen_id = profile_options.get(chosen_label)

    c1, c2, c3 = st.columns(3)
    full_refresh = c1.checkbox("Volledige refresh (alle periodes)", value=False)
    max_periods = c2.number_input("Max nieuwe periodes (0 = alles)", min_value=0, value=0)
    show_browser = c3.checkbox("Browser zichtbaar (debug)", value=False)

    if st.button("▶️ Scrape speler", type="primary", use_container_width=True):
        with st.spinner(f"Scraping {chosen_label}..."):
            try:
                from scrape_player import scrape_player as _scrape
                result = _scrape(
                    str(chosen_id),
                    force_full_refresh=full_refresh,
                    max_new_periods=int(max_periods) if max_periods > 0 else None,
                    headless=not show_browser,
                    save_to_firebase=True,
                )
                s = result.get("stats", {})
                st.success(
                    f"✅ Klaar — {s.get('total_matches',0)} matches "
                    f"({s.get('tournament_matches',0)}T + {s.get('interclub_matches',0)}IC), "
                    f"winrate {s.get('winrate',0)}%"
                )
                st.write(f"Periodes gescraped: {len(result.get('periods_scraped',[]))}, "
                         f"leeg: {len(result.get('periods_empty',[]))}, "
                         f"mislukt: {len(result.get('periods_failed',[]))}")
            except Exception as e:
                st.error(f"Scrape mislukt: {e}")

    st.divider()
    st.subheader("Meerdere spelers scrapen")
    bulk_options = {
        f"{p.get('display_name','?')} ({p.get('player_id','?')})": p.get("player_id")
        for p in sorted(profiles, key=lambda x: x.get("display_name") or "")
    }
    bulk_chosen = st.multiselect("Kies spelers", list(bulk_options.keys()), key="bulk_scrape_select")

    if bulk_chosen and st.button("▶️ Scrape geselecteerde spelers", type="primary", use_container_width=True):
        for label in bulk_chosen:
            mid = bulk_options[label]
            with st.spinner(f"Scraping {label}..."):
                try:
                    from scrape_player import scrape_player as _scrape
                    result = _scrape(str(mid), save_to_firebase=True)
                    s = result.get("stats", {})
                    st.write(f"  ✅ {label}: {s.get('total_matches',0)} matches, "
                             f"winrate {s.get('winrate',0)}%")
                except Exception as e:
                    st.write(f"  ❌ {label}: {e}")
        st.success("Bulk-scrape voltooid.")


# ═══════════════════════════════════════════════
# PAGE: Speler dashboard
# ═══════════════════════════════════════════════

def page_player():
    st.header("📊 Spelerdashboard")

    # ── Speler kiezen ──
    profiles = _get_all_profiles()

    if not profiles:
        st.info("Nog geen spelers in de database. Voeg eerst spelers toe via '➕ Speler toevoegen'.")
        return

    profile_map = {
        f"{p.get('display_name','?')} ({p.get('player_id','?')})": p
        for p in sorted(profiles, key=lambda x: x.get("display_name") or "")
    }

    # ── "Dit ben ik" + refresh-knop ──
    settings = fb.get_app_settings()
    home_id = settings.get("home_player_id")

    with st.container(border=True):
        if not home_id:
            st.caption("👤 Stel hier eenmalig in wie jij bent, zodat refresh en analyses meteen op jouw profiel werken.")
            pick_label = st.selectbox("Dit ben ik", [""] + list(profile_map.keys()), key="home_player_pick")
            if pick_label and st.button("💾 Instellen als 'mij'"):
                fb.save_app_settings({"home_player_id": profile_map[pick_label]["player_id"]})
                st.success("Ingesteld!")
                st.rerun()
        else:
            home_profile = next((p for p in profiles if p.get("player_id") == home_id), None)
            home_doc = fb.get_player(home_id)
            home_name = home_profile.get("display_name", home_id) if home_profile else home_id
            last_scraped = (home_doc or {}).get("scraped_at", "onbekend")

            ic1, ic2, ic3 = st.columns([3, 2, 1])
            with ic1:
                st.markdown(f"**👤 Jij:** {home_name} &nbsp;·&nbsp; laatst gescraped: `{last_scraped}`")
            with ic2:
                if st.button("🔄 Vernieuwen (enkel nieuwe periodes)", type="primary"):
                    with st.spinner("Verversen..."):
                        try:
                            from scrape_player import scrape_player as _scrape
                            result = _scrape(str(home_id), force_full_refresh=False, save_to_firebase=True)
                            st.success(f"Klaar — {result.get('stats',{}).get('total_matches',0)} matches totaal.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Mislukt: {e}")
            with ic3:
                if st.button("✏️ Wijzig"):
                    fb.save_app_settings({"home_player_id": None})
                    st.rerun()

            with st.expander("⚙️ Debug: volledig herscrapen"):
                st.caption("Haalt ALLE periodes opnieuw op, niet enkel de nieuwe. Trager, normaal niet nodig.")
                if st.button("⚠️ Volledig herscrapen", key="full_rescrape_home"):
                    with st.spinner("Volledig herscrapen... dit kan even duren."):
                        try:
                            from scrape_player import scrape_player as _scrape
                            result = _scrape(str(home_id), force_full_refresh=True, save_to_firebase=True)
                            st.success(f"Klaar — {result.get('stats',{}).get('total_matches',0)} matches totaal.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Mislukt: {e}")

    # Quick search filter
    search_q = st.text_input("🔍 Filter speler", placeholder="Typ naam of club...", label_visibility="collapsed")
    filtered_labels = [
        lbl for lbl in profile_map
        if not search_q or search_q.lower() in lbl.lower()
    ]

    if not filtered_labels:
        st.warning("Geen spelers gevonden.")
        return

    chosen_label = st.selectbox("Speler", filtered_labels, label_visibility="collapsed")
    profile = profile_map[chosen_label]
    player_id = profile.get("player_id")

    # ── Load data ──
    player_doc = fb.get_player(player_id)

    # ── Header ──
    hcol1, hcol2 = st.columns([5, 1])
    with hcol1:
        st.subheader(profile.get("display_name", "?"))
        club = profile.get("club")
        if club:
            st.caption(f"🏟️ {club} · ID: {player_id}")
        if player_doc:
            updated = player_doc.get("last_updated", "")
            st.caption(f"Laatste update: {updated[:19] if updated else '–'}")
    with hcol2:
        if st.button("🔄 Verversen", use_container_width=True):
            with st.spinner("Scraping..."):
                try:
                    from scrape_player import scrape_player as _scrape
                    _scrape(str(player_id), save_to_firebase=True)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    if not player_doc:
        st.warning("Geen data in Firebase. Druk op 🔄 om te scrapen.")
        return

    # ── Build DataFrame ──
    matches = player_doc.get("matches", [])
    stats = player_doc.get("stats", {})
    df = _matches_to_df(matches)

    wins    = int(stats.get("wins", 0))
    losses  = int(stats.get("losses", 0))
    total   = int(stats.get("total_matches", len(df)))
    t_count = int(stats.get("tournament_matches", 0))
    ic_count = int(stats.get("interclub_matches", 0))

    _render_metrics(total, wins, losses, t_count, ic_count)

    # ── Tabs ──
    tab_overview, tab_explorer, tab_partners, tab_opponents, tab_debug = st.tabs([
        "Overzicht", "Match Explorer", "Partners", "Tegenstanders", "Debug"
    ])

    # ── Overzicht ──
    with tab_overview:
        if df.empty:
            st.info("Geen matches beschikbaar.")
        else:
            # Period summary
            st.markdown('<div class="section-header">Per periode</div>', unsafe_allow_html=True)
            periods = df.groupby("period").agg(
                matches=("won", "count"),
                wins=("won", lambda x: x.eq(True).sum()),
                losses=("won", lambda x: x.eq(False).sum()),
            ).reset_index()
            periods["winrate"] = periods.apply(lambda r: _winrate_str(r.wins, r.losses), axis=1)
            periods = periods.sort_values("period", key=lambda s: s.map(_period_sort_key), ascending=False)
            st.dataframe(
                periods, use_container_width=True, height=min(400, 40 + len(periods) * 36),
                column_config={
                    "period":  st.column_config.TextColumn("Periode", width="large"),
                    "matches": st.column_config.NumberColumn("M", width="small"),
                    "wins":    st.column_config.NumberColumn("W", width="small"),
                    "losses":  st.column_config.NumberColumn("L", width="small"),
                    "winrate": st.column_config.TextColumn("Winrate", width="small"),
                }
            )

            # Tornooi vs Interclub split
            st.markdown('<div class="section-header">Tornooi vs Interclub</div>', unsafe_allow_html=True)
            tc1, tc2 = st.columns(2)
            for col, label, filter_val in [
                (tc1, "Tornooi", "tornooi"),
                (tc2, "Interclub", "interclub"),
            ]:
                sub = df[df["type"] == filter_val]
                sub_w = int(sub["won"].eq(True).sum())
                sub_l = int(sub["won"].eq(False).sum())
                col.metric(f"{label} ({len(sub)})", _winrate_str(sub_w, sub_l), f"{sub_w}W – {sub_l}L")

    # ── Match Explorer ──
    with tab_explorer:
        if df.empty:
            st.info("Geen matches.")
        else:
            with st.expander("🔽 Filters", expanded=False):
                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    type_opts = ["Alle"] + sorted(df["type"].unique().tolist())
                    sel_type = st.selectbox("Type", type_opts)
                    period_opts = ["Alle"] + sorted(df["period"].unique().tolist(),
                                                    key=_period_sort_key, reverse=True)
                    sel_period = st.selectbox("Periode", period_opts)
                with fc2:
                    result_opts = ["Alle", "W", "V"]
                    sel_result = st.selectbox("Resultaat (W/V)", result_opts)
                    partner_opts = ["Alle"] + sorted(df["partner"].replace("", pd.NA).dropna().unique().tolist())
                    sel_partner = st.selectbox("Partner", partner_opts)
                with fc3:
                    reeks_opts = ["Alle"] + sorted(df["reeks"].replace("", pd.NA).dropna().unique().tolist())
                    sel_reeks = st.selectbox("Reeks", reeks_opts)
                    score_q = st.text_input("Zoek in score")

            fdf = df.copy()
            if sel_type != "Alle":    fdf = fdf[fdf["type"] == sel_type]
            if sel_period != "Alle":  fdf = fdf[fdf["period"] == sel_period]
            if sel_result != "Alle":  fdf = fdf[fdf["result"] == sel_result]
            if sel_partner != "Alle": fdf = fdf[fdf["partner"] == sel_partner]
            if sel_reeks != "Alle":   fdf = fdf[fdf["reeks"] == sel_reeks]
            if score_q:               fdf = fdf[fdf["score"].str.contains(score_q, case=False, na=False)]

            fw = int(fdf["won"].eq(True).sum())
            fl = int(fdf["won"].eq(False).sum())
            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("Matches", len(fdf))
            sm2.metric("W", fw)
            sm3.metric("L", fl)
            sm4.metric("Winrate", _winrate_str(fw, fl))

            # Display columns
            show_cols = ["type", "datum", "period", "reeks", "ronde", "partner",
                         "opp1", "opp1_ranking", "opp2", "opp2_ranking", "result", "score"]
            show_cols = [c for c in show_cols if c in fdf.columns]

            fdf_display = fdf[show_cols].rename(columns={
                "type": "Type", "datum": "Datum", "period": "Periode",
                "reeks": "Reeks", "ronde": "Ronde", "partner": "Partner",
                "opp1": "Tegenstander 1", "opp1_ranking": "R1",
                "opp2": "Tegenstander 2", "opp2_ranking": "R2",
                "result": "W/V", "score": "Score",
            })
            st.caption("👉 Klik op een rij om de details onderaan te tonen.")
            explorer_event = st.dataframe(
                fdf_display,
                use_container_width=True,
                height=min(500, 40 + len(fdf) * 36),
                column_config={
                    "W/V": st.column_config.TextColumn("W/V", width="small"),
                    "Score": st.column_config.TextColumn("Score", width="small"),
                    "R1": st.column_config.TextColumn("R1", width="small"),
                    "R2": st.column_config.TextColumn("R2", width="small"),
                },
                on_select="rerun",
                selection_mode="single-row",
                key="match_explorer_table",
            )

            # Match detail
            if not fdf.empty:
                st.markdown("---")
                st.markdown("**Match detail**")
                selected_rows = (explorer_event or {}).get("selection", {}).get("rows", [])
                if not selected_rows:
                    st.info("Klik op een rij in de tabel hierboven om de details te zien.")
                else:
                    idx = selected_rows[0]
                    row = fdf.iloc[idx]

                    dc1, dc2 = st.columns(2)
                    with dc1:
                        st.write(f"**Type:** {row.get('type','–')}")
                        st.write(f"**Datum:** {row.get('datum','–') or '–'}")
                        st.write(f"**Periode:** {row.get('period','–')}")
                        st.write(f"**Toernooi/Competitie:** {row.get('toernooi','–') or '–'}")
                        st.write(f"**Reeks:** {row.get('reeks','–') or '–'}")
                        st.write(f"**Ronde:** {row.get('ronde','–') or '–'}")
                    with dc2:
                        st.write(f"**Partner:** {row.get('partner','–') or '–'}")
                        st.write(f"**Tegenstander 1:** {row.get('opp1','–')} ({row.get('opp1_ranking','?')})")
                        st.write(f"**Tegenstander 2:** {row.get('opp2','–')} ({row.get('opp2_ranking','?')})")
                        st.write(f"**Score:** {row.get('score','–')}")
                        result_badge = "win" if row.get("result") == "W" else "loss"
                        st.markdown(
                            f"**Resultaat:** <span class='badge-{result_badge}'>"
                            f"{'✅ Winst' if result_badge=='win' else '❌ Verlies'}</span>",
                            unsafe_allow_html=True,
                        )
                        if row.get("reeks_url"):
                            st.markdown(f"[📋 Poule/tabel ↗](https://www.tennisenpadelvlaanderen.be{row['reeks_url']})")
                        if row.get("uitslagenblad"):
                            st.markdown(f"[📄 Uitslagenblad ↗](https://www.tennisenpadelvlaanderen.be{row['uitslagenblad']})")

    # ── Partners ──
    with tab_partners:
        st.markdown('<div class="section-header">Partneranalyse</div>', unsafe_allow_html=True)
        partner_df = _summarize_partner(df)
        if not partner_df.empty:
            q = st.text_input("Zoek partner", placeholder="Filter...", label_visibility="collapsed")
            if q:
                partner_df = partner_df[partner_df["partner"].str.contains(q, case=False, na=False)]
        _render_table(partner_df, "partner")

    # ── Tegenstanders ──
    with tab_opponents:
        st.markdown('<div class="section-header">Tegenstandersanalyse</div>', unsafe_allow_html=True)
        opp_df = _summarize_opponents(df)
        if not opp_df.empty:
            q = st.text_input("Zoek tegenstander", placeholder="Filter...", label_visibility="collapsed")
            if q:
                opp_df = opp_df[opp_df["tegenstander"].str.contains(q, case=False, na=False)]
        _render_table(opp_df, "tegenstander")

    # ── Debug ──
    with tab_debug:
        st.json(player_doc, expanded=False)
        st.write(f"**Schema:** {player_doc.get('schema_version','?')}")
        st.write(f"**Periodes gescraped:** {player_doc.get('periods_scraped',[])}")
        st.write(f"**Periodes leeg:** {player_doc.get('periods_empty',[])}")
        st.write(f"**Periodes mislukt:** {player_doc.get('periods_failed',[])}")


# ═══════════════════════════════════════════════
# RENDER
# ═══════════════════════════════════════════════

if page == "➕ Speler toevoegen":
    page_add_player()
elif page == "🧩 Opstelling-analyse":
    page_lineup_lab()
elif page == "🔄 Scrapen":
    page_scrape()
else:
    page_player()
