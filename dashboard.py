import re
from typing import Any, Dict, Optional

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from firebase_service import get_player, get_player_profile, save_player_profile, search_player_profiles
from player_search import search_players
from scraper.scraper import scrape_player

st.set_page_config(page_title="Padel Dashboard", page_icon="🎾", layout="wide")

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def clean_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def combine_name(first_name: str, last_name: str) -> str:
    return clean_text(f"{clean_text(first_name)} {clean_text(last_name)}")


def clean_period_sort_key(period_label: str):
    if not period_label:
        return (9999, 999)
    m = re.search(r"week\s+(\d{1,2})/(\d{4})", str(period_label).lower())
    if m:
        return (int(m.group(2)), int(m.group(1)))
    return (9999, 999)


def build_candidate_label(candidate: Dict[str, Any]) -> str:
    name = candidate.get("display_name") or "Onbekend"
    club = candidate.get("club")
    pid = candidate.get("player_id")
    if club:
        return f"{name} — {club} ({pid})"
    return f"{name} ({pid})"


def player_to_df(player_dict: Dict[str, Any]) -> pd.DataFrame:
    raw = player_dict.get("raw_data", {}) if isinstance(player_dict, dict) else {}
    matches = raw.get("matches", []) if isinstance(raw, dict) else []
    if not matches:
        return pd.DataFrame(columns=[
            "period_block", "match_date", "match_week", "partner", "opponent_1", "opponent_2",
            "ranking_player_or_team", "ranking_opponents", "poule", "result", "score", "won", "raw_text"
        ])

    rows = []
    for m in matches:
        rows.append({
            # current scraper usually only has a period block, not the true match date/week
            "period_block": m.get("period"),
            "match_date": m.get("match_date") or None,
            "match_week": m.get("match_week") or None,
            "partner": m.get("partner_name"),
            "opponent_1": m.get("opponent_1_name"),
            "opponent_2": m.get("opponent_2_name"),
            "ranking_player_or_team": m.get("ranking_player_or_team"),
            "ranking_opponents": m.get("ranking_opponents"),
            "poule": m.get("round_text"),
            "result": m.get("result_text") or "Onbekend",
            "score": m.get("score"),
            "won": m.get("won"),
            "raw_text": m.get("raw_text"),
        })
    return pd.DataFrame(rows)


def summarize_periods(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["period_block", "matches", "wins", "losses", "unknown", "winrate"])
    summary = (
        df.groupby("period_block", dropna=False)
        .agg(
            matches=("raw_text", "count"),
            wins=("result", lambda x: int((x == "Winst").sum())),
            losses=("result", lambda x: int((x == "Verlies").sum())),
            unknown=("result", lambda x: int((x == "Onbekend").sum())),
        )
        .reset_index()
    )
    summary["winrate"] = summary.apply(
        lambda r: round((r["wins"] / (r["wins"] + r["losses"]) * 100), 2)
        if (r["wins"] + r["losses"]) > 0 else 0.0,
        axis=1,
    )
    summary["sort_year"] = summary["period_block"].apply(lambda x: clean_period_sort_key(str(x))[0])
    summary["sort_week"] = summary["period_block"].apply(lambda x: clean_period_sort_key(str(x))[1])
    return summary.sort_values(["sort_year", "sort_week"], ascending=[False, False]).drop(columns=["sort_year", "sort_week"])


def summarize_people(df: pd.DataFrame, col_name: str, title_col: str) -> pd.DataFrame:
    if df.empty or col_name not in df.columns:
        return pd.DataFrame(columns=[title_col, "matches", "wins", "losses", "winrate"])
    work = df[[col_name, "result"]].copy()
    work = work[work[col_name].notna()]
    work[col_name] = work[col_name].astype(str).str.strip()
    work = work[work[col_name] != ""]
    if work.empty:
        return pd.DataFrame(columns=[title_col, "matches", "wins", "losses", "winrate"])
    summary = (
        work.groupby(col_name)
        .agg(
            matches=("result", "count"),
            wins=("result", lambda x: int((x == "Winst").sum())),
            losses=("result", lambda x: int((x == "Verlies").sum())),
        )
        .reset_index().rename(columns={col_name: title_col})
    )
    summary["winrate"] = summary.apply(
        lambda r: round((r["wins"] / (r["wins"] + r["losses"]) * 100), 2)
        if (r["wins"] + r["losses"]) > 0 else 0.0,
        axis=1,
    )
    # requested: sort primarily by winrate descending
    return summary.sort_values(["winrate", "matches", "wins"], ascending=[False, False, False])


def build_opponent_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["tegenstander", "matches", "wins", "losses", "winrate"])
    rows = []
    for _, row in df.iterrows():
        for col in ["opponent_1", "opponent_2"]:
            val = row.get(col)
            if pd.notna(val) and str(val).strip():
                rows.append({"tegenstander": str(val).strip(), "result": row.get("result", "Onbekend")})
    if not rows:
        return pd.DataFrame(columns=["tegenstander", "matches", "wins", "losses", "winrate"])
    temp = pd.DataFrame(rows)
    summary = (
        temp.groupby("tegenstander")
        .agg(
            matches=("result", "count"),
            wins=("result", lambda x: int((x == "Winst").sum())),
            losses=("result", lambda x: int((x == "Verlies").sum())),
        )
        .reset_index()
    )
    summary["winrate"] = summary.apply(
        lambda r: round((r["wins"] / (r["wins"] + r["losses"]) * 100), 2)
        if (r["wins"] + r["losses"]) > 0 else 0.0,
        axis=1,
    )
    return summary.sort_values(["winrate", "matches", "wins"], ascending=[False, False, False])


def render_donut_chart(wins: int, losses: int):
    fig, ax = plt.subplots(figsize=(3.8, 3.8))
    ax.pie([wins, losses], labels=["Winst", "Verlies"], autopct="%1.0f%%", startangle=90)
    centre_circle = plt.Circle((0, 0), 0.62, fc="white")
    fig.gca().add_artist(centre_circle)
    ax.axis("equal")
    st.pyplot(fig)
    plt.close(fig)


def render_metric_row(match_count: int, wins: int, losses: int, unknown: int, winrate: float):
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Matches", match_count)
    c2.metric("Wins", wins)
    c3.metric("Losses", losses)
    c4.metric("Unknown", unknown)
    c5.metric("Winrate", f"{winrate:.2f}%")


def style_analysis_table(df: pd.DataFrame, first_col: str):
    if df.empty:
        return
    st.dataframe(
        df,
        use_container_width=True,
        height=min(420, 40 + len(df) * 35),
        column_config={
            first_col: st.column_config.TextColumn(first_col, width="medium"),
            "matches": st.column_config.NumberColumn("Matches", width="small"),
            "wins": st.column_config.NumberColumn("Wins", width="small"),
            "losses": st.column_config.NumberColumn("Losses", width="small"),
            "winrate": st.column_config.NumberColumn("Winrate", format="%.2f%%", width="small"),
        },
    )


def apply_match_filters(df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
    filtered = df.copy()
    if not filtered.empty:
        date_val = filters.get("match_date")
        week_val = filters.get("match_week")
        block_val = filters.get("period_block")
        result_val = filters.get("result")
        partner_val = filters.get("partner")
        opp1_val = filters.get("opponent_1")
        opp2_val = filters.get("opponent_2")
        poule_val = filters.get("poule")
        score_search = filters.get("score_search")

        if date_val not in (None, "", "Alle"):
            filtered = filtered[filtered["match_date"].astype(str) == str(date_val)]
        if week_val not in (None, "", "Alle"):
            filtered = filtered[filtered["match_week"].astype(str) == str(week_val)]
        if block_val not in (None, "", "Alle"):
            filtered = filtered[filtered["period_block"].astype(str) == str(block_val)]
        if result_val not in (None, "", "Alle"):
            filtered = filtered[filtered["result"].astype(str) == str(result_val)]
        if partner_val not in (None, "", "Alle"):
            filtered = filtered[filtered["partner"].astype(str) == str(partner_val)]
        if opp1_val not in (None, "", "Alle"):
            filtered = filtered[filtered["opponent_1"].astype(str) == str(opp1_val)]
        if opp2_val not in (None, "", "Alle"):
            filtered = filtered[filtered["opponent_2"].astype(str) == str(opp2_val)]
        if poule_val not in (None, "", "Alle"):
            filtered = filtered[filtered["poule"].astype(str) == str(poule_val)]
        if score_search:
            mask = (
                filtered["score"].astype(str).str.contains(score_search, case=False, na=False)
                | filtered["raw_text"].astype(str).str.contains(score_search, case=False, na=False)
            )
            filtered = filtered[mask]
    return filtered


def render_match_details(filtered_df: pd.DataFrame):
    if filtered_df.empty:
        return
    st.markdown("### Matchdetails")
    options = []
    mapping = {}
    for _, row in filtered_df.reset_index(drop=True).iterrows():
        date_or_week = row.get("match_date") or row.get("match_week") or row.get("period_block") or "-"
        label = f"{date_or_week}: {row.get('result', '-')} | {row.get('score', '-')}"
        options.append(label)
        mapping[label] = row.to_dict()
    chosen = st.selectbox("Kies een match", options)
    row = mapping.get(chosen, {})
    c1, c2 = st.columns(2)
    with c1:
        st.write("**Datum:**", row.get("match_date", "-") or "-")
        st.write("**Week:**", row.get("match_week", "-") or "-")
        st.write("**Periodeblok:**", row.get("period_block", "-") or "-")
        st.write("**Resultaat:**", row.get("result", "-"))
        st.write("**Score:**", row.get("score", "-"))
        st.write("**Poule:**", row.get("poule", "-"))
    with c2:
        st.write("**Partner:**", row.get("partner", "-"))
        st.write("**Opponent 1:**", row.get("opponent_1", "-"))
        st.write("**Opponent 2:**", row.get("opponent_2", "-"))
        st.write("**Ranking:**", f"{row.get('ranking_player_or_team', '-')} vs {row.get('ranking_opponents', '-')}")
    if st.session_state.get("debug_mode"):
        st.code(str(row.get("raw_text", "")))


# ---------------------------------------------------------
# Navigation (top only)
# ---------------------------------------------------------
if "page" not in st.session_state:
    st.session_state["page"] = "Speler"

page = st.radio(
    "Navigatie",
    ["Speler", "Gebruiker toevoegen", "Team (preview)"],
    horizontal=True,
    label_visibility="collapsed",
    index=["Speler", "Gebruiker toevoegen", "Team (preview)"].index(st.session_state.get("page", "Speler")),
)
st.session_state["page"] = page

with st.expander("Debug & technische info", expanded=False):
    st.checkbox("Debug tonen", value=st.session_state.get("debug_mode", False), key="debug_mode")


# ---------------------------------------------------------
# Add user page
# ---------------------------------------------------------
def render_add_user_page():
    st.title("➕ Gebruiker toevoegen")
    st.caption("Zoek extern op voornaam + achternaam en voeg daarna de juiste speler toe.")

    pending_first = st.session_state.get("pending_add_first_name", "")
    pending_last = st.session_state.get("pending_add_last_name", "")

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        first_name = st.text_input("Voornaam", value=pending_first)
    with c2:
        last_name = st.text_input("Achternaam", value=pending_last)
    with c3:
        club_query = st.text_input("Club (optioneel)", value="")

    st.info("Bij meerdere kandidaten wordt de club mee getoond. ID staat enkel tussen haakjes.")

    if st.button("Zoek externe kandidaten", use_container_width=True):
        if not clean_text(first_name) and not clean_text(last_name):
            st.warning("Geef minstens een voornaam of achternaam in.")
        else:
            with st.spinner("Zoeken naar externe kandidaten..."):
                try:
                    candidates = search_players(
                        first_name=first_name,
                        last_name=last_name,
                        club=club_query.strip() or None,
                        headless=True,
                        use_cache=False,
                    )
                    st.session_state["candidate_results"] = candidates
                    st.session_state["candidate_first_name"] = first_name
                    st.session_state["candidate_last_name"] = last_name
                except Exception as e:
                    st.session_state["candidate_results"] = []
                    st.warning(f"Externe zoekopdracht mislukt: {e}")

    candidates = st.session_state.get("candidate_results", [])
    if candidates:
        st.success(f"{len(candidates)} kandidaat(en) gevonden")
        labels = [build_candidate_label(c) for c in candidates]
        mapping = {build_candidate_label(c): c for c in candidates}
        chosen_label = st.selectbox("Kies kandidaat", labels)
        chosen = mapping.get(chosen_label)
        scrape_now = st.checkbox("Haal direct resultaten op na toevoegen", value=False)

        if st.button("Kandidaat toevoegen aan database", type="primary", use_container_width=True):
            if not chosen:
                st.warning("Geen kandidaat geselecteerd.")
            else:
                player_id = str(chosen.get("player_id"))
                save_player_profile(
                    player_id=player_id,
                    display_name=chosen.get("display_name"),
                    club=chosen.get("club"),
                    dashboard_url=chosen.get("dashboard_url"),
                    aliases=[chosen.get("display_name")] if chosen.get("display_name") else [],
                )
                if scrape_now:
                    with st.spinner("Resultaten worden opgehaald..."):
                        try:
                            scrape_player(player_id, headless=True, force_full_refresh=False, refresh_recent_periods=2)
                            st.success(f"Gebruiker toegevoegd en resultaten opgehaald: {chosen.get('display_name')} ({player_id})")
                        except Exception as e:
                            st.warning(f"Gebruiker toegevoegd, maar scrape mislukte: {e}")
                else:
                    st.success(f"Gebruiker toegevoegd: {chosen.get('display_name')} ({player_id})")
    elif st.session_state.get("candidate_first_name") or st.session_state.get("candidate_last_name"):
        st.warning("Geen kandidaten gevonden.")


# ---------------------------------------------------------
# Player page
# ---------------------------------------------------------
def resolve_player_id_from_name(first_name: str, last_name: str, club_query: Optional[str]) -> Optional[str]:
    full_name = combine_name(first_name, last_name)
    local_candidates = search_player_profiles(full_name, club=club_query or None, limit=20) if full_name else []
    if local_candidates:
        labels = [build_candidate_label(c) for c in local_candidates]
        mapping = {build_candidate_label(c): c.get("player_id") for c in local_candidates}
        chosen = st.selectbox("Gevonden spelers", labels)
        return mapping.get(chosen)

    if full_name:
        st.session_state["pending_add_first_name"] = clean_text(first_name)
        st.session_state["pending_add_last_name"] = clean_text(last_name)
        st.warning("Niet gevonden in lokale database.")
        if st.button("Open 'Gebruiker toevoegen'", use_container_width=True):
            st.session_state["page"] = "Gebruiker toevoegen"
            st.rerun()
    return None


def render_player_page():
    st.title("🎾 Padel Dashboard")
    st.caption("Mobile-first dashboard voor speleranalyse.")

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        first_name = st.text_input("Voornaam", value=st.session_state.get("search_first_name", ""))
    with c2:
        last_name = st.text_input("Achternaam", value=st.session_state.get("search_last_name", ""))
    with c3:
        club_query = st.text_input("Club (optioneel)", value=st.session_state.get("search_club", ""))

    if st.button("Zoek speler", type="primary", use_container_width=True):
        st.session_state["search_first_name"] = first_name
        st.session_state["search_last_name"] = last_name
        st.session_state["search_club"] = club_query

    first_name = st.session_state.get("search_first_name", first_name)
    last_name = st.session_state.get("search_last_name", last_name)
    club_query = st.session_state.get("search_club", club_query)

    player_id = resolve_player_id_from_name(first_name, last_name, club_query.strip() or None)
    if not player_id:
        st.info("Zoek een speler op naam om data te bekijken.")
        return

    profile = get_player_profile(player_id)
    player = get_player(player_id)
    display_name = profile.get("display_name") if profile else combine_name(first_name, last_name)
    display_club = profile.get("club") if profile else None
    last_updated = player.get("last_updated") if player else profile.get("last_updated") if profile else None

    header_left, header_right = st.columns([3, 1])
    with header_left:
        title = f"{display_name}"
        if player_id:
            title += f" ({player_id})"
        st.subheader(title)
        if display_club:
            st.write(f"**Club:** {display_club}")
        st.write(f"**Laatste update gegevens:** {last_updated or 'onbekend'}")
    with header_right:
        if st.button("🔄 Gegevens verversen", use_container_width=True):
            with st.spinner("Recente data wordt opgehaald..."):
                try:
                    scrape_player(str(player_id), headless=True, force_full_refresh=False, refresh_recent_periods=2)
                    st.success("Gegevens succesvol ververst.")
                    st.rerun()
                except Exception as e:
                    st.warning(f"Verversen mislukt: {e}")

    if not player:
        st.warning("Geen spelerdata gevonden in Firestore voor deze speler.")
        st.info("Je kan via 'Gebruiker toevoegen' de speler eerst toevoegen of meteen resultaten ophalen.")
        return

    stats = player.get("stats", {})
    raw_data = player.get("raw_data", {})
    df = player_to_df(player)
    period_summary = summarize_periods(df)
    partner_summary = summarize_people(df, "partner", "partner")
    opponent_summary = build_opponent_summary(df)

    wins = int(stats.get("wins", 0) or 0)
    losses = int(stats.get("losses", 0) or 0)
    unknown = int(stats.get("unknown_results", 0) or 0)
    match_count = int(stats.get("matches", len(df)) or 0)
    winrate = float(stats.get("winrate", 0.0) or 0.0)
    periods_processed = raw_data.get("periods_processed", [])
    empty_periods = raw_data.get("empty_periods", [])
    failed_last_run = raw_data.get("failed_periods_last_run", raw_data.get("failed_periods", []))
    failed_open = raw_data.get("failed_periods_open", raw_data.get("failed_periods", []))

    render_metric_row(match_count, wins, losses, unknown, winrate)

    tabs = st.tabs(["Overzicht", "Match Explorer", "Partners", "Tegenstanders"] + (["Debug"] if st.session_state.get("debug_mode") else []))

    with tabs[0]:
        st.info(
            "Opmerking: de huidige scraper bewaart meestal een periodeblok en niet altijd de exacte matchdatum of echte week. "
            "Als je bij enkele verliezen geen exacte week/datum ziet, is dat een huidige datalimiet van de bron/scraper en geen echte tegenspraak met het resultaat."
        )
        left, right = st.columns([1, 2])
        with left:
            st.markdown("### Winst / verlies")
            if wins + losses > 0:
                render_donut_chart(wins, losses)
            else:
                st.info("Nog geen wins/losses beschikbaar.")
        with right:
            st.markdown("### Trend per periodeblok")
            if not period_summary.empty:
                chart_df = period_summary.rename(columns={"period_block": "periodeblok"}).set_index("periodeblok")
                st.bar_chart(chart_df[["matches", "wins", "losses"]])
                st.dataframe(period_summary.rename(columns={"period_block": "periodeblok"}), use_container_width=True, height=320)
            else:
                st.info("Geen periodeoverzicht beschikbaar.")

    with tabs[1]:
        st.markdown("### Match Explorer")
        if df.empty:
            st.info("Geen matches beschikbaar.")
        else:
            # compact filters in an expander instead of a permanent bulky filter bar
            with st.expander("Kolomfilters", expanded=False):
                c1, c2, c3 = st.columns(3)
                with c1:
                    date_options = ["Alle"] + sorted([x for x in df["match_date"].dropna().astype(str).unique().tolist() if x])
                    selected_date = st.selectbox("Datum", date_options)
                    week_options = ["Alle"] + sorted([x for x in df["match_week"].dropna().astype(str).unique().tolist() if x])
                    selected_week = st.selectbox("Week", week_options)
                    block_options = ["Alle"] + sorted(df["period_block"].dropna().astype(str).unique().tolist(), key=clean_period_sort_key, reverse=True)
                    selected_block = st.selectbox("Periodeblok", block_options)
                with c2:
                    result_options = ["Alle", "Winst", "Verlies", "Onbekend"]
                    selected_result = st.selectbox("Resultaat", result_options)
                    partner_options = ["Alle"] + sorted(df["partner"].dropna().astype(str).unique().tolist())
                    selected_partner = st.selectbox("Partner", partner_options)
                    poule_options = ["Alle"] + sorted(df["poule"].dropna().astype(str).unique().tolist())
                    selected_poule = st.selectbox("Poule", poule_options)
                with c3:
                    opp1_options = ["Alle"] + sorted(df["opponent_1"].dropna().astype(str).unique().tolist())
                    selected_opp1 = st.selectbox("Opponent 1", opp1_options)
                    opp2_options = ["Alle"] + sorted(df["opponent_2"].dropna().astype(str).unique().tolist())
                    selected_opp2 = st.selectbox("Opponent 2", opp2_options)
                    score_search = st.text_input("Score / tekst")

            filtered_df = apply_match_filters(
                df,
                {
                    "match_date": selected_date,
                    "match_week": selected_week,
                    "period_block": selected_block,
                    "result": selected_result,
                    "partner": selected_partner,
                    "opponent_1": selected_opp1,
                    "opponent_2": selected_opp2,
                    "poule": selected_poule,
                    "score_search": score_search,
                },
            )

            filter_wins = int((filtered_df["result"] == "Winst").sum()) if not filtered_df.empty else 0
            filter_losses = int((filtered_df["result"] == "Verlies").sum()) if not filtered_df.empty else 0
            filter_known = filter_wins + filter_losses
            filter_winrate = round((filter_wins / filter_known) * 100, 2) if filter_known > 0 else 0.0

            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Matches", len(filtered_df))
            s2.metric("Wins", filter_wins)
            s3.metric("Losses", filter_losses)
            s4.metric("Winrate", f"{filter_winrate:.2f}%")

            display_df = filtered_df.rename(
                columns={
                    "match_date": "Datum",
                    "match_week": "Week",
                    "period_block": "Periodeblok",
                    "partner": "Partner",
                    "opponent_1": "Opponent 1",
                    "opponent_2": "Opponent 2",
                    "poule": "Poule",
                    "result": "Resultaat",
                    "score": "Score",
                }
            )
            visible_cols = ["Datum", "Week", "Periodeblok", "Resultaat", "Score", "Partner", "Opponent 1", "Opponent 2", "Poule"]
            st.dataframe(display_df[visible_cols], use_container_width=True, height=380)
            render_match_details(filtered_df)

    with tabs[2]:
        st.markdown("### Partneranalyse")
        if partner_summary.empty:
            st.info("Geen partnerinfo beschikbaar.")
        else:
            with st.expander("Kolomfilters", expanded=False):
                c1, c2 = st.columns(2)
                with c1:
                    partner_search = st.text_input("Zoek partner", key="partner_table_search")
                with c2:
                    min_matches = st.number_input("Min. matches", min_value=0, value=0, step=1, key="partner_table_min_matches")
            table_df = partner_summary.copy()
            if partner_search:
                table_df = table_df[table_df["partner"].astype(str).str.contains(partner_search, case=False, na=False)]
            table_df = table_df[table_df["matches"] >= int(min_matches)]
            style_analysis_table(table_df, "partner")

    with tabs[3]:
        st.markdown("### Tegenstandersanalyse")
        if opponent_summary.empty:
            st.info("Geen tegenstanderinfo beschikbaar.")
        else:
            with st.expander("Kolomfilters", expanded=False):
                c1, c2 = st.columns(2)
                with c1:
                    opp_search = st.text_input("Zoek tegenstander", key="opp_table_search")
                with c2:
                    min_matches_opp = st.number_input("Min. matches", min_value=0, value=0, step=1, key="opp_table_min_matches")
            table_df = opponent_summary.copy()
            if opp_search:
                table_df = table_df[table_df["tegenstander"].astype(str).str.contains(opp_search, case=False, na=False)]
            table_df = table_df[table_df["matches"] >= int(min_matches_opp)]
            style_analysis_table(table_df, "tegenstander")

    if st.session_state.get("debug_mode"):
        with tabs[4]:
            st.markdown("### Debug")
            c1, c2 = st.columns(2)
            with c1:
                st.write("**Lege periodes**")
                st.write(empty_periods if empty_periods else [])
                st.write("**Mislukte periodes laatste run**")
                st.write(failed_last_run if failed_last_run else [])
            with c2:
                st.write("**Open mislukte periodes**")
                st.write(failed_open if failed_open else [])
                st.write("**Verwerkte periodes**")
                st.write(periods_processed if periods_processed else [])
            st.markdown("### Ruwe data")
            st.json(player)


# ---------------------------------------------------------
# Team preview page
# ---------------------------------------------------------
def render_team_preview_page():
    st.title("👥 Team pagina (preview)")
    st.caption("Voor de teampagina is nieuwe scraping nodig van teaminfo, pouledata en teamresultaten.")
    st.info(
        "Doel: teamresultaten, alle resultaten in de poule, spelerscombinaties en hulp om de beste opstelling te kiezen voor de volgende match."
    )
    st.markdown(
        "- teamoverzicht en laatste update\n"
        "- resultaten van het team\n"
        "- resultaten van alle teams in de poule\n"
        "- analyse van spelerscombinaties\n"
        "- inschatting beste opstelling"
    )


# ---------------------------------------------------------
# Render
# ---------------------------------------------------------
if page == "Gebruiker toevoegen":
    render_add_user_page()
elif page == "Team (preview)":
    render_team_preview_page()
else:
    render_player_page()
