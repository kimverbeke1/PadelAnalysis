import re
from typing import Any, Dict, Optional, Tuple

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from firebase_service import get_player, get_player_profile, save_player_profile, search_player_profiles
from player_search import search_players
from scraper.scraper import scrape_player

st.set_page_config(page_title="Padel Dashboard", page_icon="🎾", layout="wide")


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


def player_to_df(player_dict: Dict[str, Any]) -> pd.DataFrame:
    raw = player_dict.get("raw_data", {}) if isinstance(player_dict, dict) else {}
    matches = raw.get("matches", []) if isinstance(raw, dict) else []
    if not matches:
        return pd.DataFrame(columns=["period","partner_name","opponent_1_name","opponent_2_name","ranking_player_or_team","ranking_opponents","round_text","result_text","score","won","raw_text"])
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
        return pd.DataFrame(columns=["period","matches","wins","losses","unknown","winrate"])
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
    summary["winrate"] = summary.apply(lambda r: round((r["wins"]/(r["wins"]+r["losses"])*100),2) if (r["wins"]+r["losses"])>0 else 0.0, axis=1)
    summary["sort_year"] = summary["period"].apply(lambda x: clean_period_sort_key(str(x))[0])
    summary["sort_week"] = summary["period"].apply(lambda x: clean_period_sort_key(str(x))[1])
    return summary.sort_values(["sort_year","sort_week"], ascending=[False,False]).drop(columns=["sort_year","sort_week"])


def summarize_people(df: pd.DataFrame, col_name: str, title_col: str) -> pd.DataFrame:
    if df.empty or col_name not in df.columns:
        return pd.DataFrame(columns=[title_col,"matches","wins","losses","winrate"])
    work = df[[col_name, "result_text"]].copy()
    work = work[work[col_name].notna()]
    work[col_name] = work[col_name].astype(str).str.strip()
    work = work[work[col_name] != ""]
    if work.empty:
        return pd.DataFrame(columns=[title_col,"matches","wins","losses","winrate"])
    summary = (
        work.groupby(col_name)
        .agg(
            matches=("result_text", "count"),
            wins=("result_text", lambda x: int((x == "Winst").sum())),
            losses=("result_text", lambda x: int((x == "Verlies").sum())),
        )
        .reset_index().rename(columns={col_name: title_col})
    )
    summary["winrate"] = summary.apply(lambda r: round((r["wins"]/(r["wins"]+r["losses"])*100),2) if (r["wins"]+r["losses"])>0 else 0.0, axis=1)
    return summary.sort_values(["matches","winrate"], ascending=[False,False])


def build_opponent_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["tegenstander","matches","wins","losses","winrate"])
    rows = []
    for _, row in df.iterrows():
        for col in ["opponent_1_name", "opponent_2_name"]:
            val = row.get(col)
            if pd.notna(val) and str(val).strip():
                rows.append({"tegenstander": str(val).strip(), "result_text": row.get("result_text", "Onbekend")})
    if not rows:
        return pd.DataFrame(columns=["tegenstander","matches","wins","losses","winrate"])
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
    summary["winrate"] = summary.apply(lambda r: round((r["wins"]/(r["wins"]+r["losses"])*100),2) if (r["wins"]+r["losses"])>0 else 0.0, axis=1)
    return summary.sort_values(["matches","winrate"], ascending=[False,False])


def build_ranking_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["ranking_combo","matches","wins","losses","winrate"])
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
    summary["winrate"] = summary.apply(lambda r: round((r["wins"]/(r["wins"]+r["losses"])*100),2) if (r["wins"]+r["losses"])>0 else 0.0, axis=1)
    return summary.sort_values(["matches","winrate"], ascending=[False,False])


def render_donut_chart(wins: int, losses: int):
    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    ax.pie([wins, losses], labels=["Winst", "Verlies"], autopct="%1.0f%%", startangle=90)
    centre_circle = plt.Circle((0,0), 0.62, fc="white")
    fig.gca().add_artist(centre_circle)
    ax.axis("equal")
    st.pyplot(fig)
    plt.close(fig)


def render_metric_row(match_count: int, wins: int, losses: int, unknown: int, winrate: float, periods: int):
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Matches", match_count)
    c2.metric("Wins", wins)
    c3.metric("Losses", losses)
    c4.metric("Unknown", unknown)
    c5.metric("Winrate", f"{winrate:.2f}%")
    c6.metric("Periodes", periods)


def build_candidate_label(candidate: Dict[str, Any]) -> str:
    name = candidate.get("display_name") or candidate.get("player_id") or "Onbekend"
    club = candidate.get("club")
    pid = candidate.get("player_id")
    if club:
        return f"{name} — {club} [{pid}]"
    return f"{name} [{pid}]"


def render_add_user_page():
    st.title("➕ Gebruiker toevoegen")
    st.caption("Voeg een speler toe aan de database via manuele input of externe naamzoeking.")

    pending_first = st.session_state.get("pending_add_first_name", "")
    pending_last = st.session_state.get("pending_add_last_name", "")

    mode = st.radio("Methode", ["Manueel toevoegen", "Extern zoeken op naam"], horizontal=True)

    if mode == "Manueel toevoegen":
        c1, c2 = st.columns(2)
        with c1:
            player_id = st.text_input("Player ID", value="")
            first_name = st.text_input("Voornaam", value=pending_first)
        with c2:
            last_name = st.text_input("Achternaam", value=pending_last)
            club = st.text_input("Club (optioneel)", value="")
        aliases = st.text_input("Alias(s), gescheiden door komma", value="")

        if st.button("Gebruiker opslaan in database", type="primary"):
            full_name = combine_name(first_name, last_name)
            if not player_id.strip() or not full_name:
                st.warning("Player ID, voornaam en achternaam zijn verplicht.")
            else:
                alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
                save_player_profile(
                    player_id=player_id.strip(),
                    display_name=full_name,
                    club=club.strip() or None,
                    aliases=alias_list,
                )
                st.success(f"Gebruiker opgeslagen: {full_name} [{player_id.strip()}]")

    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            first_name = st.text_input("Voornaam", value=pending_first)
        with c2:
            last_name = st.text_input("Achternaam", value=pending_last)
        with c3:
            club_query = st.text_input("Club (optioneel)", value="")

        st.info("Zoeken start alleen via de knop 'Zoek externe kandidaten'. Bij meerdere hits wordt club mee getoond.")

        if st.button("Zoek externe kandidaten"):
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

            if st.button("Kandidaat toevoegen aan database", type="primary"):
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
                                st.success(f"Gebruiker toegevoegd en resultaten opgehaald: {chosen.get('display_name') or player_id}")
                            except Exception as e:
                                st.warning(f"Gebruiker toegevoegd, maar scrape mislukte: {e}")
                    else:
                        st.success(f"Gebruiker toegevoegd: {chosen.get('display_name') or player_id}")
        elif st.session_state.get("candidate_first_name") or st.session_state.get("candidate_last_name"):
            st.warning("Geen kandidaten gevonden.")


def resolve_player_id_from_name(first_name: str, last_name: str, club_query: Optional[str]) -> Optional[str]:
    full_name = combine_name(first_name, last_name)
    local_candidates = search_player_profiles(full_name, club=club_query or None, limit=20) if full_name else []
    if local_candidates:
        labels = [build_candidate_label(c) for c in local_candidates]
        mapping = {build_candidate_label(c): c.get("player_id") for c in local_candidates}
        chosen = st.sidebar.selectbox("Lokale profielhits", labels)
        return mapping.get(chosen)

    if full_name:
        st.session_state["pending_add_first_name"] = clean_text(first_name)
        st.session_state["pending_add_last_name"] = clean_text(last_name)
        st.sidebar.warning("Niet gevonden in lokale database. Ga naar pagina 'Gebruiker toevoegen' om deze speler toe te voegen.")
    return None


def pick_player_id() -> Optional[str]:
    st.sidebar.header("Speler kiezen")
    mode = st.sidebar.radio("Selectiemethode", ["Player ID", "Naam"], horizontal=True)
    if mode == "Player ID":
        return st.sidebar.text_input("Player ID", value="1790766").strip() or None

    c1, c2 = st.sidebar.columns(2)
    with c1:
        first_name = st.text_input("Voornaam", value="")
    with c2:
        last_name = st.text_input("Achternaam", value="")
    club_query = st.sidebar.text_input("Club (optioneel)", value="")
    if st.sidebar.button("Zoek speler"):
        st.session_state["dashboard_first_name"] = first_name
        st.session_state["dashboard_last_name"] = last_name
        st.session_state["dashboard_club"] = club_query

    first_name = st.session_state.get("dashboard_first_name", first_name)
    last_name = st.session_state.get("dashboard_last_name", last_name)
    club_query = st.session_state.get("dashboard_club", club_query)
    return resolve_player_id_from_name(first_name, last_name, club_query.strip() or None)


def render_dashboard_page():
    st.title("🎾 Padel Dashboard")
    st.caption("Zoek bestaande spelers. Nieuwe speler niet gevonden? Voeg toe via de aparte pagina.")

    player_id = pick_player_id()
    show_raw = st.sidebar.checkbox("Toon ruwe player data", value=False)
    show_debug_info = st.sidebar.checkbox("Toon debug-informatie", value=True)

    if not player_id:
        st.info("Zoek links een speler via ID of via de knop 'Zoek speler'.")
        st.stop()

    profile = get_player_profile(player_id)
    if profile and profile.get("display_name"):
        st.write(f"**Profielnaam:** {profile.get('display_name')}")
        if profile.get("club"):
            st.write(f"**Club:** {profile.get('club')}")

    player = get_player(player_id)
    if not player:
        st.warning("Geen spelerdata gevonden in Firestore voor deze player ID.")
        st.info("Als het profiel wel bestaat maar nog geen resultaten heeft, ga naar 'Gebruiker toevoegen' en vink daar 'Haal direct resultaten op' aan.")
        st.stop()

    stats = player.get("stats", {})
    raw_data = player.get("raw_data", {})
    df = player_to_df(player)
    period_summary = summarize_periods(df)
    partner_summary = summarize_people(df, "partner_name", "partner")
    opponent_summary = build_opponent_summary(df)
    ranking_summary = build_ranking_summary(df)
    round_summary = summarize_people(df, "round_text", "ronde")

    wins = int(stats.get("wins", 0) or 0)
    losses = int(stats.get("losses", 0) or 0)
    unknown = int(stats.get("unknown_results", 0) or 0)
    match_count = int(stats.get("matches", len(df)) or 0)
    winrate = float(stats.get("winrate", 0.0) or 0.0)
    periods_processed = raw_data.get("periods_processed", [])
    empty_periods = raw_data.get("empty_periods", [])
    failed_periods = raw_data.get("failed_periods", [])

    st.subheader(f"Speler {player.get('player_id', player_id)}")
    st.write(f"**Laatste update:** {player.get('last_updated', '-')}  ")
    st.write(f"**Schema:** {raw_data.get('schema_version', '-')}")
    render_metric_row(match_count, wins, losses, unknown, winrate, len(periods_processed))

    s1, s2, s3 = st.columns(3)
    s1.info(f"Verwerkte periodes: {len(periods_processed)}")
    s2.warning(f"Lege periodes: {len(empty_periods)}")
    s3.error(f"Mislukte periodes (laatste run): {len(failed_periods)}")

    tab_overview, tab_matches, tab_partners, tab_opponents, tab_raw = st.tabs([
        "Overzicht", "Match Explorer", "Partners", "Tegenstanders", "Ruwe data"
    ])

    with tab_overview:
        left, right = st.columns([1, 2])
        with left:
            st.markdown("### Winst / verlies")
            if wins + losses > 0:
                render_donut_chart(wins, losses)
            else:
                st.info("Nog geen wins/losses beschikbaar.")
            st.markdown("### Snelle inzichten")
            if not partner_summary.empty:
                st.write("**Top partner:**", partner_summary.iloc[0]["partner"])
            if not opponent_summary.empty:
                st.write("**Vaakste tegenstander:**", opponent_summary.iloc[0]["tegenstander"])
        with right:
            st.markdown("### Trend per periode")
            if not period_summary.empty:
                st.bar_chart(period_summary.set_index("period")[["matches", "wins", "losses"]])
                st.dataframe(period_summary, use_container_width=True, height=320)
            else:
                st.info("Geen periodeoverzicht beschikbaar.")
        a, b = st.columns(2)
        with a:
            st.markdown("### Top partners")
            if not partner_summary.empty:
                st.dataframe(partner_summary.head(10), use_container_width=True, height=320)
        with b:
            st.markdown("### Top ranking-combinaties")
            if not ranking_summary.empty:
                st.dataframe(ranking_summary.head(10), use_container_width=True, height=320)

    with tab_matches:
        st.markdown("### Match Explorer")
        if df.empty:
            st.info("Geen matches beschikbaar.")
        else:
            c1, c2, c3, c4, c5 = st.columns(5)
            period_options = ["Alle periodes"] + sorted(df["period"].dropna().unique().tolist(), key=clean_period_sort_key, reverse=True)
            result_options = ["Alles", "Winst", "Verlies", "Onbekend"]
            partner_options = ["Alle partners"] + sorted(df["partner_name"].dropna().astype(str).unique().tolist()) if df["partner_name"].notna().any() else ["Alle partners"]
            opponent_values = sorted(set(df["opponent_1_name"].dropna().astype(str).tolist() + df["opponent_2_name"].dropna().astype(str).tolist()))
            opponent_options = ["Alle tegenstanders"] + opponent_values if opponent_values else ["Alle tegenstanders"]
            round_options = ["Alle rondes"] + sorted(df["round_text"].dropna().astype(str).unique().tolist()) if df["round_text"].notna().any() else ["Alle rondes"]
            selected_period = c1.selectbox("Periode", period_options)
            selected_result = c2.selectbox("Resultaat", result_options)
            selected_partner = c3.selectbox("Partner", partner_options)
            selected_opponent = c4.selectbox("Tegenstander", opponent_options)
            selected_round = c5.selectbox("Ronde", round_options)
            search_text = st.text_input("Zoeken in raw tekst / namen / score")
            filtered_df = df.copy()
            if selected_period != "Alle periodes":
                filtered_df = filtered_df[filtered_df["period"] == selected_period]
            if selected_result != "Alles":
                filtered_df = filtered_df[filtered_df["result_text"] == selected_result]
            if selected_partner != "Alle partners":
                filtered_df = filtered_df[filtered_df["partner_name"] == selected_partner]
            if selected_opponent != "Alle tegenstanders":
                filtered_df = filtered_df[(filtered_df["opponent_1_name"] == selected_opponent) | (filtered_df["opponent_2_name"] == selected_opponent)]
            if selected_round != "Alle rondes":
                filtered_df = filtered_df[filtered_df["round_text"] == selected_round]
            if search_text:
                mask = (
                    filtered_df["raw_text"].astype(str).str.contains(search_text, case=False, na=False)
                    | filtered_df["partner_name"].astype(str).str.contains(search_text, case=False, na=False)
                    | filtered_df["opponent_1_name"].astype(str).str.contains(search_text, case=False, na=False)
                    | filtered_df["opponent_2_name"].astype(str).str.contains(search_text, case=False, na=False)
                    | filtered_df["score"].astype(str).str.contains(search_text, case=False, na=False)
                )
                filtered_df = filtered_df[mask]
            st.write(f"**Aantal zichtbare matches:** {len(filtered_df)}")
            st.dataframe(filtered_df, use_container_width=True, height=520)
            st.download_button(
                "Download selectie als CSV",
                filtered_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"padel_matches_{player.get('player_id', player_id)}.csv",
                mime="text/csv",
            )

    with tab_partners:
        st.markdown("### Partneranalyse")
        if partner_summary.empty:
            st.info("Geen partnerinfo beschikbaar.")
        else:
            st.dataframe(partner_summary, use_container_width=True, height=420)
            st.bar_chart(partner_summary.head(15).set_index("partner")[["matches", "wins", "losses"]])

    with tab_opponents:
        st.markdown("### Tegenstandersanalyse")
        if opponent_summary.empty:
            st.info("Geen tegenstanderinfo beschikbaar.")
        else:
            st.dataframe(opponent_summary, use_container_width=True, height=420)
            st.bar_chart(opponent_summary.head(15).set_index("tegenstander")[["matches", "wins", "losses"]])

    with tab_raw:
        st.markdown("### Technische info")
        st.write("**Schema version:**", raw_data.get("schema_version", "-"))
        st.write("**Network log file:**", raw_data.get("network_log_file", "-"))
        st.write("**Debug log file:**", raw_data.get("debug_log_file", "-"))
        st.write("**Aantal ruwe matches:**", raw_data.get("matches_count", 0))
        if show_debug_info:
            d1, d2, d3 = st.columns(3)
            with d1:
                st.write("**Verwerkte periodes**")
                st.write(periods_processed if periods_processed else [])
            with d2:
                st.write("**Lege periodes**")
                st.write(empty_periods if empty_periods else [])
            with d3:
                st.write("**Mislukte periodes (laatste run)**")
                st.write(failed_periods if failed_periods else [])
            st.markdown("### Ronde-overzicht")
            if not round_summary.empty:
                st.dataframe(round_summary, use_container_width=True, height=320)
        if show_raw:
            st.markdown("### Ruwe player data")
            st.json(player)


page = st.sidebar.radio("Pagina", ["Dashboard", "Gebruiker toevoegen"], index=0)
if page == "Gebruiker toevoegen":
    render_add_user_page()
else:
    render_dashboard_page()
