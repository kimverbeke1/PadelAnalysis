import sys
sys.path.insert(0, ".")
sys.path.insert(0, "scraper")
import firebase_service as fb
import pandas as pd

profiles = [d.to_dict() for d in fb.db.collection(fb.PLAYER_PROFILES_COLLECTION).stream()]
print(f"Profiles: {len(profiles)}")
for p in profiles:
    print(f"  {p.get('display_name')} ({p.get('player_id')})")

doc = fb.get_player("214435")
if doc:
    matches = doc.get("matches", [])
    stats = doc.get("stats", {})
    print(f"Matches: {len(matches)}, stats: {stats}")

    rows = []
    for m in matches:
        rows.append({
            "type": m.get("match_type",""),
            "period": m.get("period_label",""),
            "datum": m.get("tournament_date_start") or m.get("match_date") or "",
            "partner": m.get("partner_name") or "",
            "opp1": m.get("opp1_name") or "",
            "opp2": m.get("opp2_name") or "",
            "result": m.get("result") or "",
            "won": m.get("won"),
            "score": m.get("score") or "",
        })
    df = pd.DataFrame(rows)
    print(f"DataFrame: {len(df)} rows")
    print("Types:", df["type"].value_counts().to_dict())
    print("Results:", df["result"].value_counts().to_dict())
    print("Sample partner:", df["partner"].iloc[0] if len(df) else "–")
else:
    print("No doc for 214435")
