import re
from typing import Any, Dict, Optional

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from firebase_service import get_player, get_player_profile, save_player_profile, search_player_profiles
from player_search import search_players
from scraper.scraper import scrape_player

st.set_page_config(page_title="Padel Dashboard", page_icon="🎾", layout="wide")


# =========================================================
# Helpers
# =========================================================

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
            "period", "partner_name", "opponent_1_name", "opponent_2_name",
            "ranking_player_or_team", "ranking_opponents", "round_text",
            "result_text", "score", "won", "raw_text"
        ])
    rows = []
    for m in matches:
        rows.append({
            "period": m.get("period"),
            "partner_name": m.get("partner_name"),
            "opponent_1_name": m.get("opponent_1_name"),
            "opponent_2_name": m.get("opponent_2_name"),
            "ranking_player_or_team": m.get("ranking_player_or_team"),
            "ranking_opponents": m.get("ranking_opponents"),
            "round_text": m.get("round_text"),
            "result_text": m.get("result_text") or "Onbekend",
            "score": m.get("score"),
            "won": m.get("won"),
            "raw_text": m.get("raw_text"),
        })
    return pd.DataFrame(rows)


def summarize_periods(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["period", "matches", "wins", "losses", "unknown", "winrate"])
    summary = (
        df.groupby("period", dropna=False)
        .agg(
            matches=("raw_text", "count"),
            wins=("result_text", lambda x: int((x == "Winst").sum())),
            losses=("result_text", lambda x: int((x == "Verlies").sum())),
            unknown=("result_text", lambda x: int((x == "Onbekend").sum())),
        )
        .reset_index()
    )
    summary["winrate"] = summary.apply(
        lambda r: round((r["wins"] / (r["wins"] + r["losses"]) * 100), 2)
        if (r["wins"] + r["losses"]) > 0 else 0.0,
        axis=1,
    )
    summary["sort_year"] = summary["period"].apply(lambda x: clean_period_sort_key(str(x))[0])
    summary["sort_week"] = summary["period"].apply(lambda x: clean_period_sort_key(str(x))[1])
    return summary.sort_values(["sort_year", "sort_week"], ascending=[False, False]).drop(columns=["sort_year", "sort_week"])


def summarize_people(df: pd.DataFrame, col_name: str, title_col: str) -> pd.DataFrame:
    if df.empty or col_name not in df.columns:
        return pd.DataFrame(columns=[title_col, "matches", "wins", "losses", "winrate"])
    work = df[[col_name, "result_text"]].copy()
    work = work[work[col_name].notna()]
    work[col_name] = work[col_name].astype(str).str.strip()
    work = work[work[col_name] != ""]
    if work.empty:
        return pd.DataFrame(columns=[title_col, "matches", "wins", "losses", "winrate"])
    summary = (
        work.groupby(col_name)
        .agg(
            matches=("result_text", "count"),
            wins=("result_text", lambda x: int((x == "Winst").sum())),
            losses=("result_text", lambda x: int((x == "Verlies").sum())),
        )
        .reset_index().rename(columns={col_name: title_col})
    )
    summary["winrate"] = summary.apply(
        lambda r: round((r["wins"] / (r["wins"] + r["losses"]) * 100), 2)
        if (r["wins"] + r["losses"]) > 0 else 0.0,
        axis=1,
    )
    return summary.sort_values(["matches", "winrate"], ascending=[False, False])


def build_opponent_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["tegenstander", "matches", "wins", "losses", "winrate"])
    rows = []
    for _, row in df.iterrows():
        for col in ["opponent_1_name", "opponent_2_name"]:
            val = row.get(col)
            if pd.notna(val) and str(val).strip():
                rows.append({"tegenstander": str(val).strip(), "result_text": row.get("result_text", "Onbekend")})
    if not rows:
        return pd.DataFrame(columns=["tegenstander", "matches", "wins", "losses", "winrate"])
    temp = pd.DataFrame(rows)
    summary = (
        temp.groupby("tegenstander")
        .agg(
            matches=("result_text", "count"),
            wins=("result_text", lambda x: int((x == "Winst").sum())),
            losses=("result_text", lambda x: int((x == "Verlies").sum())),
        )
        .reset_index()
    )
    summary["winrate"] = summary.apply(
        lambda r: round((r["wins"] / (r["wins"] + r["losses"]) * 100), 2)
        if (r["wins"] + r["losses"]) > 0 else 0.0,
        axis=1,
    )
    return summary.sort_values(["matches", "winrate"], ascending=[False, False])


def build_ranking_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["ranking_combo", "matches", "wins", "losses", "winrate"])
    temp = df.copy()
    temp["ranking_combo"] = temp["ranking_player_or_team"].fillna("?").astype(str) + " vs " + temp["ranking_opponents"].fillna("?").astype(str)
    summary = (
        temp.groupby("ranking_combo")
        .agg(
            matches=("raw_text", "count"),
            wins=("result_text", lambda x: int((x == "Winst").sum())),
            losses=("result_text", lambda x: int((x == "Verlies").sum())),
        )
        .reset_index()
    )
    summary["winrate"] = summary.apply(
        lambda r: round((r["wins"] / (r["wins"] + r["losses"]) * 100), 2)
        if (r["wins"] + r["losses"]) > 0 else 0.0,
        axis=1,
    )
    return summary.sort_values(["matches", "winrate"], ascending=[False, False])


def render_donut_chart(wins: int, losses: int):
    fig, ax = plt.subplots(figsize=(3.8, 3.8))
    ax.pie([wins, losses], labels=["Winst", "Verlies"], autopct="%1.0f%%", startangle=90)
    centre_circle = plt.Circle((0, 0), 0.62, fc="white")
    fig.gca().add_artist(centre_circle)
    ax.axis("equal")
    st.pyplot(fig)
    plt.close(fig)


def render_metric_row(match_count: int, wins: int, losses: int, unknown: int, winrate: float, periods: int):
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


# =========================================================
# Top navigation (no sidebar navigation)
# =========================================================
if "page" not in st.session_state:
    st.session_state["page"] = "Speler"

page = st.radio(
    "Navigatie",
    ["Speler", "Gebruiker toevoegen", "Team (preview)"],
    index=["Speler", "Gebruiker toevoegen", "Team (preview)"].index(st.session_state.get("page", "Speler")),
    horizontal=True,
    label_visibility="collapsed",
)
st.session_state["page"] = page

# small global debug control kept out of sidebar
with st.expander("Debug & technische info", expanded=False):
    debug_mode = st.checkbox("Debug tonen", value=st.session_state.get("debug_mode", False), key="debug_mode")


# =========================================================
# Page: gebruiker toevoegen
# =========================================================
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


# =========================================================
# Page: speler
# =========================================================
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


def render_match_details(filtered_df: pd.DataFrame):
    if filtered_df.empty:
        return
    st.markdown("### Matchdetails")
    options = []
    mapping = {}
    for idx, row in filtered_df.reset_index(drop=True).iterrows():
        label = f"{row.get('period', '-')}: {row.get('result_text', '-')} | {row.get('score', '-')}"
        options.append(label)
        mapping[label] = row.to_dict()
    chosen = st.selectbox("Kies een match", options)
    row = mapping.get(chosen, {})
    c1, c2 = st.columns(2)
    with c1:
        st.write("**Periode:**", row.get("period", "-"))
        st.write("**Resultaat:**", row.get("result_text", "-"))
        st.write("**Score:**", row.get("score", "-"))
        st.write("**Ronde:**", row.get("round_text", "-"))
    with c2:
        st.write("**Partner:**", row.get("partner_name", "-"))
        st.write("**Tegenstander 1:**", row.get("opponent_1_name", "-"))
        st.write("**Tegenstander 2:**", row.get("opponent_2_name", "-"))
        st.write("**Ranking:**", f"{row.get('ranking_player_or_team', '-')} vs {row.get('ranking_opponents', '-')}")
    if st.session_state.get("debug_mode"):
        st.code(str(row.get("raw_text", "")))


def render_player_page():
    st.title("🎾 Padel Dashboard")
    st.caption("Mobile-first spelerdashboard, met focus op zoeken, bekijken en snel verversen.")

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
    last_updated = None
    if player:
        last_updated = player.get("last_updated")
    elif profile:
        last_updated = profile.get("last_updated")

    header_left, header_right = st.columns([3, 1])
    with header_left:
        title = f"{display_name}"
        if player_id:
            title += f" ({player_id})"
        st.subheader(title)
        if display_club:
            st.write(f"**Club:** {display_club}")
        if last_updated:
            st.write(f"**Laatste update gegevens:** {last_updated}")
        else:
            st.write("**Laatste update gegevens:** onbekend")
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
    partner_summary = summarize_people(df, "partner_name", "partner")
    opponent_summary = build_opponent_summary(df)
    ranking_summary = build_ranking_summary(df)

    wins = int(stats.get("wins", 0) or 0)
    losses = int(stats.get("losses", 0) or 0)
    unknown = int(stats.get("unknown_results", 0) or 0)
    match_count = int(stats.get("matches", len(df)) or 0)
    winrate = float(stats.get("winrate", 0.0) or 0.0)
    periods_processed = raw_data.get("periods_processed", [])
    empty_periods = raw_data.get("empty_periods", [])
    failed_last_run = raw_data.get("failed_periods_last_run", raw_data.get("failed_periods", []))
    failed_open = raw_data.get("failed_periods_open", raw_data.get("failed_periods", []))

    render_metric_row(match_count, wins, losses, unknown, winrate, len(periods_processed))

    tabs = st.tabs(["Overzicht", "Match Explorer", "Partners", "Tegenstanders"] + (["Debug"] if st.session_state.get("debug_mode") else []))

    with tabs[0]:
        left, right = st.columns([1, 2])
        with left:
            st.markdown("### Winst / verlies")
            if wins + losses > 0:
                render_donut_chart(wins, losses)
            else:
                st.info("Nog geen wins/losses beschikbaar.")
        with right:
            st.markdown("### Trend per periode")
            if not period_summary.empty:
                st.bar_chart(period_summary.set_index("period")[["matches", "wins", "losses"]])
                st.dataframe(period_summary, use_container_width=True, height=320)
            else:
                st.info("Geen periodeoverzicht beschikbaar.")

    with tabs[1]:
        st.markdown("### Match Explorer")
        if df.empty:
            st.info("Geen matches beschikbaar.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                period_options = ["Alle periodes"] + sorted(df["period"].dropna().unique().tolist(), key=clean_period_sort_key, reverse=True)
                selected_period = st.selectbox("Periode", period_options)
            with c2:
                result_options = ["Alles", "Winst", "Verlies", "Onbekend"]
                selected_result = st.selectbox("Resultaat", result_options)

            c3, c4 = st.columns(2)
            with c3:
                partner_values = sorted(df["partner_name"].dropna().astype(str).unique().tolist()) if df["partner_name"].notna().any() else []
                selected_partner = st.selectbox("Partner", ["Alle partners"] + partner_values)
            with c4:
                opponent_values = sorted(set(df["opponent_1_name"].dropna().astype(str).tolist() + df["opponent_2_name"].dropna().astype(str).tolist()))
                selected_opponent = st.selectbox("Tegenstander", ["Alle tegenstanders"] + opponent_values)

            search_text = st.text_input("Zoeken in score / tekst")

            filtered_df = df.copy()
            if selected_period != "Alle periodes":
                filtered_df = filtered_df[filtered_df["period"] == selected_period]
            if selected_result != "Alles":
                filtered_df = filtered_df[filtered_df["result_text"] == selected_result]
            if selected_partner != "Alle partners":
                filtered_df = filtered_df[filtered_df["partner_name"] == selected_partner]
            if selected_opponent != "Alle tegenstanders":
                filtered_df = filtered_df[(filtered_df["opponent_1_name"] == selected_opponent) | (filtered_df["opponent_2_name"] == selected_opponent)]
            if search_text:
                mask = (
                    filtered_df["raw_text"].astype(str).str.contains(search_text, case=False, na=False)
                    | filtered_df["score"].astype(str).str.contains(search_text, case=False, na=False)
                )
                filtered_df = filtered_df[mask]

            filter_wins = int((filtered_df["result_text"] == "Winst").sum()) if not filtered_df.empty else 0
            filter_losses = int((filtered_df["result_text"] == "Verlies").sum()) if not filtered_df.empty else 0
            filter_unknown = int((filtered_df["result_text"] == "Onbekend").sum()) if not filtered_df.empty else 0
            filter_known = filter_wins + filter_losses
            filter_winrate = round((filter_wins / filter_known) * 100, 2) if filter_known > 0 else 0.0

            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Matches", len(filtered_df))
            s2.metric("Wins", filter_wins)
            s3.metric("Losses", filter_losses)
            s4.metric("Winrate", f"{filter_winrate:.2f}%")

            display_cols = ["period", "result_text", "score", "partner_name", "opponent_1_name", "opponent_2_name", "round_text"]
            st.dataframe(filtered_df[display_cols], use_container_width=True, height=360)
            render_match_details(filtered_df)

    with tabs[2]:
        st.markdown("### Partneranalyse")
        if partner_summary.empty:
            st.info("Geen partnerinfo beschikbaar.")
        else:
            style_analysis_table(partner_summary, "partner")

    with tabs[3]:
        st.markdown("### Tegenstandersanalyse")
        if opponent_summary.empty:
            st.info("Geen tegenstanderinfo beschikbaar.")
        else:
            style_analysis_table(opponent_summary, "tegenstander")

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


# =========================================================
# Page: team preview
# =========================================================
def render_team_preview_page():
    st.title("👥 Team pagina (preview)")
    st.caption("Deze pagina is voorbereid als volgende stap, maar vraagt een aparte en grotere scraping-logica.")

    st.info(
        "Doel van de teampagina: teamresultaten, poule-resultaten, spelerscombinaties en inschatting van de beste opstelling. "
        "Daarvoor is nieuwe scraping nodig van teaminfo, poule-uitslagen en spelers per team."
    )

    st.markdown("### Wat hier later in kan komen")
    st.markdown(
        "- teamoverzicht en laatste update\n"
        "- alle resultaten van het team\n"
        "- resultaten van andere teams in dezelfde poule\n"
        "- analyse van spelerscombinaties\n"
        "- inschatting van beste opstelling voor volgende match"
    )


# =========================================================
# App render
# =========================================================
if page == "Gebruiker toevoegen":
    render_add_user_page()
elif page == "Team (preview)":
    render_team_preview_page()
else:
    render_player_page()
