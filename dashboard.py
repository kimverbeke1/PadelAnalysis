import re
from collections import Counter
from typing import Any, Dict, List

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

from scraper.firebase_service import get_player


# =========================================================
# PAGE CONFIG
# =========================================================

st.set_page_config(
    page_title="Padel Dashboard V3",
    page_icon="🎾",
    layout="wide",
)


# =========================================================
# HELPERS
# =========================================================

def clean_period_sort_key(period_label: str):
    if not period_label:
        return (9999, 999)

    m = re.search(r"week\s+(\d{1,2})/(\d{4})", str(period_label).lower())
    if m:
        week = int(m.group(1))
        year = int(m.group(2))
        return (year, week)

    return (9999, 999)


def load_player(player_id: str):
    try:
        return get_player(player_id)
    except Exception as e:
        st.error(f"Fout bij ophalen van speler {player_id} uit Firestore: {e}")
        return None


@st.cache_data(show_spinner=False)
def player_to_df(player_dict: Dict[str, Any]) -> pd.DataFrame:
    raw_data = player_dict.get("raw_data", {}) if isinstance(player_dict, dict) else {}
    matches = raw_data.get("matches", []) if isinstance(raw_data, dict) else []

    if not matches:
        return pd.DataFrame(
            columns=[
                "period",
                "partner_name",
                "opponent_1_name",
                "opponent_2_name",
                "ranking_player_or_team",
                "ranking_opponents",
                "round_text",
                "result_text",
                "score",
                "won",
                "raw_text",
            ]
        )

    rows = []
    for m in matches:
        rows.append(
            {
                "period": m.get("period"),
                "partner_name": m.get("partner_name"),
                "opponent_1_name": m.get("opponent_1_name"),
                "opponent_2_name": m.get("opponent_2_name"),
                "all_detected_players": ", ".join(m.get("all_detected_players", [])) if isinstance(m.get("all_detected_players"), list) else m.get("all_detected_players"),
                "ranking_player_or_team": m.get("ranking_player_or_team"),
                "ranking_opponents": m.get("ranking_opponents"),
                "round_text": m.get("round_text"),
                "result_letter": m.get("result_letter"),
                "result_text": m.get("result_text"),
                "score": m.get("score"),
                "won": m.get("won"),
                "raw_text": m.get("raw_text"),
                "table_index": m.get("table_index"),
                "row_index": m.get("row_index"),
            }
        )

    df = pd.DataFrame(rows)
    if "result_text" in df.columns:
        df["result_text"] = df["result_text"].fillna("Onbekend")
    return df


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
        if (r["wins"] + r["losses"]) > 0
        else 0.0,
        axis=1,
    )

    summary["sort_year"] = summary["period"].apply(lambda x: clean_period_sort_key(str(x))[0])
    summary["sort_week"] = summary["period"].apply(lambda x: clean_period_sort_key(str(x))[1])
    summary = summary.sort_values(["sort_year", "sort_week"], ascending=[False, False]).drop(columns=["sort_year", "sort_week"])
    return summary


def summarize_people(df: pd.DataFrame, col_name: str, title_col: str) -> pd.DataFrame:
    if df.empty or col_name not in df.columns:
        return pd.DataFrame(columns=[title_col, "matches", "wins", "losses", "winrate"])

    working = df[[col_name, "result_text"]].copy()
    working = working[working[col_name].notna()]
    working[col_name] = working[col_name].astype(str).str.strip()
    working = working[working[col_name] != ""]

    if working.empty:
        return pd.DataFrame(columns=[title_col, "matches", "wins", "losses", "winrate"])

    summary = (
        working.groupby(col_name)
        .agg(
            matches=("result_text", "count"),
            wins=("result_text", lambda x: int((x == "Winst").sum())),
            losses=("result_text", lambda x: int((x == "Verlies").sum())),
        )
        .reset_index()
        .rename(columns={col_name: title_col})
    )

    summary["winrate"] = summary.apply(
        lambda r: round((r["wins"] / (r["wins"] + r["losses"]) * 100), 2)
        if (r["wins"] + r["losses"]) > 0
        else 0.0,
        axis=1,
    )

    return summary.sort_values(["matches", "winrate"], ascending=[False, False])


def build_opponent_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["tegenstander", "matches", "wins", "losses", "winrate"])

    rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        for col in ["opponent_1_name", "opponent_2_name"]:
            val = row.get(col)
            if pd.notna(val) and str(val).strip():
                rows.append({
                    "tegenstander": str(val).strip(),
                    "result_text": row.get("result_text", "Onbekend"),
                })

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
        if (r["wins"] + r["losses"]) > 0
        else 0.0,
        axis=1,
    )
    return summary.sort_values(["matches", "winrate"], ascending=[False, False])


def build_ranking_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["ranking_combo", "matches", "wins", "losses", "winrate"])

    temp = df.copy()
    temp["ranking_combo"] = (
        temp["ranking_player_or_team"].fillna("?").astype(str)
        + " vs "
        + temp["ranking_opponents"].fillna("?").astype(str)
    )

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
        if (r["wins"] + r["losses"]) > 0
        else 0.0,
        axis=1,
    )
    return summary.sort_values(["matches", "winrate"], ascending=[False, False])


def render_donut_chart(wins: int, losses: int):
    fig, ax = plt.subplots(figsize=(4.4, 4.4))
    values = [wins, losses]
    labels = ["Winst", "Verlies"]
    ax.pie(values, labels=labels, autopct="%1.0f%%", startangle=90)
    centre_circle = plt.Circle((0, 0), 0.62, fc="white")
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


def build_compare_df(players: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for p in players:
        if not p:
            continue
        stats = p.get("stats", {})
        raw = p.get("raw_data", {})
        rows.append(
            {
                "player_id": p.get("player_id"),
                "schema_version": raw.get("schema_version"),
                "matches": stats.get("matches", 0),
                "wins": stats.get("wins", 0),
                "losses": stats.get("losses", 0),
                "unknown": stats.get("unknown_results", 0),
                "winrate": stats.get("winrate", 0.0),
                "periods": len(raw.get("periods_processed", [])),
                "laatste_update": p.get("last_updated"),
            }
        )
    return pd.DataFrame(rows)


# =========================================================
# SIDEBAR
# =========================================================

st.title("🎾 Padel Dashboard V3")
st.caption("Dashboard op basis van gestructureerde V3.1-scraperdata uit Firestore")

with st.sidebar:
    st.header("Instellingen")
    default_player_id = "1790766"
    player_id = st.text_input("Hoofdspeler ID", value=default_player_id)
    compare_ids_raw = st.text_area(
        "Vergelijk met speler IDs (optioneel, komma of nieuwe regel)",
        value="",
        height=100,
        placeholder="bv. 1790766, 1234567",
    )
    show_raw = st.checkbox("Toon ruwe player data", value=False)
    show_debug_info = st.checkbox("Toon debug-informatie", value=True)

player = load_player(player_id)
if not player:
    st.warning("Geen spelerdata gevonden. Run eerst de scraper en probeer opnieuw.")
    st.stop()

compare_ids: List[str] = []
for part in re.split(r"[,\n;]+", compare_ids_raw):
    part = part.strip()
    if part and part != player_id:
        compare_ids.append(part)

compare_players = [load_player(pid) for pid in compare_ids] if compare_ids else []


# =========================================================
# PREP DATA
# =========================================================

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


# =========================================================
# TOP OVERVIEW
# =========================================================

st.subheader(f"Speler {player.get('player_id', player_id)}")
st.write(f"**Laatste update:** {player.get('last_updated', '-')}  ")
st.write(f"**Schema:** {raw_data.get('schema_version', '-')}")
render_metric_row(match_count, wins, losses, unknown, winrate, len(periods_processed))

s1, s2, s3 = st.columns(3)
s1.info(f"Verwerkte periodes: {len(periods_processed)}")
s2.warning(f"Lege periodes: {len(empty_periods)}")
s3.error(f"Mislukte periodes: {len(failed_periods)}")


# =========================================================
# TABS
# =========================================================

tab_overview, tab_matches, tab_partner, tab_opponents, tab_compare, tab_raw = st.tabs(
    ["Overzicht", "Match Explorer", "Partners", "Tegenstanders", "Vergelijken", "Ruwe data"]
)


# =========================================================
# TAB OVERZICHT
# =========================================================

with tab_overview:
    left, right = st.columns([1, 2])

    with left:
        st.markdown("### Winst / verlies")
        if wins + losses > 0:
            render_donut_chart(wins, losses)
        else:
            st.info("Nog geen wins/losses beschikbaar.")

        st.markdown("### Periodestatus")
        st.write(f"**Verwerkte periodes:** {len(periods_processed)}")
        st.write(f"**Lege periodes:** {len(empty_periods)}")
        st.write(f"**Mislukte periodes:** {len(failed_periods)}")

    with right:
        st.markdown("### Trend per periode")
        if not period_summary.empty:
            chart_df = period_summary.set_index("period")[["matches", "wins", "losses"]]
            st.bar_chart(chart_df)
            st.dataframe(period_summary, use_container_width=True, height=320)
        else:
            st.info("Geen periodeoverzicht beschikbaar.")

    a, b = st.columns(2)
    with a:
        st.markdown("### Top partners")
        if not partner_summary.empty:
            st.dataframe(partner_summary.head(10), use_container_width=True, height=320)
        else:
            st.info("Geen partnerinfo beschikbaar.")

    with b:
        st.markdown("### Top rankingcombinaties")
        if not ranking_summary.empty:
            st.dataframe(ranking_summary.head(10), use_container_width=True, height=320)
        else:
            st.info("Geen rankinginfo beschikbaar.")


# =========================================================
# TAB MATCH EXPLORER
# =========================================================

with tab_matches:
    st.markdown("### Match Explorer")
    if df.empty:
        st.info("Geen matches beschikbaar.")
    else:
        c1, c2, c3, c4, c5, c6 = st.columns(6)

        period_options = ["Alle periodes"] + sorted(df["period"].dropna().unique().tolist(), key=clean_period_sort_key, reverse=True)
        result_options = ["Alles", "Winst", "Verlies", "Onbekend"]
        partner_options = ["Alle partners"] + sorted(df["partner_name"].dropna().astype(str).unique().tolist()) if df["partner_name"].notna().any() else ["Alle partners"]
        opponent_values = sorted(set(df["opponent_1_name"].dropna().astype(str).tolist() + df["opponent_2_name"].dropna().astype(str).tolist()))
        opponent_options = ["Alle tegenstanders"] + opponent_values if opponent_values else ["Alle tegenstanders"]
        ranking_values = sorted(set(df["ranking_player_or_team"].dropna().astype(str).tolist() + df["ranking_opponents"].dropna().astype(str).tolist()))
        ranking_options = ["Alle klassementen"] + ranking_values if ranking_values else ["Alle klassementen"]
        round_options = ["Alle rondes"] + sorted(df["round_text"].dropna().astype(str).unique().tolist()) if df["round_text"].notna().any() else ["Alle rondes"]

        selected_period = c1.selectbox("Periode", period_options)
        selected_result = c2.selectbox("Resultaat", result_options)
        selected_partner = c3.selectbox("Partner", partner_options)
        selected_opponent = c4.selectbox("Tegenstander", opponent_options)
        selected_ranking = c5.selectbox("Klassement", ranking_options)
        selected_round = c6.selectbox("Ronde", round_options)
        search_text = st.text_input("Zoeken in raw tekst / namen / score")

        filtered_df = df.copy()

        if selected_period != "Alle periodes":
            filtered_df = filtered_df[filtered_df["period"] == selected_period]
        if selected_result != "Alles":
            filtered_df = filtered_df[filtered_df["result_text"] == selected_result]
        if selected_partner != "Alle partners":
            filtered_df = filtered_df[filtered_df["partner_name"] == selected_partner]
        if selected_opponent != "Alle tegenstanders":
            filtered_df = filtered_df[
                (filtered_df["opponent_1_name"] == selected_opponent)
                | (filtered_df["opponent_2_name"] == selected_opponent)
            ]
        if selected_ranking != "Alle klassementen":
            filtered_df = filtered_df[
                (filtered_df["ranking_player_or_team"] == selected_ranking)
                | (filtered_df["ranking_opponents"] == selected_ranking)
            ]
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

        csv_data = filtered_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="Download selectie als CSV",
            data=csv_data,
            file_name=f"padel_matches_{player.get('player_id', player_id)}_v3.csv",
            mime="text/csv",
        )


# =========================================================
# TAB PARTNERS
# =========================================================

with tab_partner:
    st.markdown("### Partneranalyse")
    if partner_summary.empty:
        st.info("Geen partnerinfo beschikbaar.")
    else:
        st.dataframe(partner_summary, use_container_width=True, height=420)
        top_partner_chart = partner_summary.head(15).set_index("partner")[["matches", "wins", "losses"]]
        st.bar_chart(top_partner_chart)

        selected_partner_detail = st.selectbox(
            "Detailweergave partner",
            ["-- kies partner --"] + partner_summary["partner"].tolist(),
            key="partner_detail",
        )
        if selected_partner_detail != "-- kies partner --":
            partner_df = df[df["partner_name"] == selected_partner_detail]
            st.write(f"**Matches met partner {selected_partner_detail}: {len(partner_df)}**")
            st.dataframe(partner_df, use_container_width=True, height=360)


# =========================================================
# TAB TEGENSTANDERS
# =========================================================

with tab_opponents:
    st.markdown("### Tegenstandersanalyse")
    if opponent_summary.empty:
        st.info("Geen tegenstanderinfo beschikbaar.")
    else:
        st.dataframe(opponent_summary, use_container_width=True, height=420)
        top_opponent_chart = opponent_summary.head(15).set_index("tegenstander")[["matches", "wins", "losses"]]
        st.bar_chart(top_opponent_chart)

        selected_opponent_detail = st.selectbox(
            "Detailweergave tegenstander",
            ["-- kies tegenstander --"] + opponent_summary["tegenstander"].tolist(),
            key="opp_detail",
        )
        if selected_opponent_detail != "-- kies tegenstander --":
            opp_df = df[(df["opponent_1_name"] == selected_opponent_detail) | (df["opponent_2_name"] == selected_opponent_detail)]
            st.write(f"**Matches tegen {selected_opponent_detail}: {len(opp_df)}**")
            st.dataframe(opp_df, use_container_width=True, height=360)


# =========================================================
# TAB VERGELIJKEN
# =========================================================

with tab_compare:
    st.markdown("### Vergelijk spelers")
    if compare_players:
        all_players = [player] + [p for p in compare_players if p]
        compare_df = build_compare_df(all_players)
        st.dataframe(compare_df, use_container_width=True, height=320)
        if not compare_df.empty:
            chart_df = compare_df.set_index("player_id")[["matches", "wins", "losses", "winrate"]]
            st.bar_chart(chart_df)
    else:
        st.info("Voeg in de sidebar extra speler IDs toe om te vergelijken.")


# =========================================================
# TAB RUWE DATA
# =========================================================

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
            st.write("**Mislukte periodes**")
            st.write(failed_periods if failed_periods else [])

        st.markdown("### Ronde-overzicht")
        if not round_summary.empty:
            st.dataframe(round_summary, use_container_width=True, height=320)
        else:
            st.info("Geen ronde-info beschikbaar.")

    if show_raw:
        st.markdown("### Ruwe player data")
        st.json(player)
