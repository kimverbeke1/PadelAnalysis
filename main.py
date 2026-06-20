from scraper.scraper import scrape_player, find_player_and_scrape
from scraper.firebase_service import get_player

# =========================================================
# KIES TESTMODE
# =========================================================

TEST_MODE = "by_id"   # "by_id" or "by_name"
PLAYER_ID = "1790766"
NAME_QUERY = "Kim Verbeke"
CLUB = None

FORCE_FULL_REFRESH = False
REFRESH_RECENT_PERIODS = 2


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    if TEST_MODE == "by_name":
        print("=== TESTMODE: zoek speler op naam + scrape incrementally ===")
        result = find_player_and_scrape(
            name_query=NAME_QUERY,
            club=CLUB,
            sport="Padel",
            headless=False,
            force_full_refresh=FORCE_FULL_REFRESH,
            refresh_recent_periods=REFRESH_RECENT_PERIODS,
        )
        player_id = result.get("player_id")

        print("\n=== GEKOZEN KANDIDAAT ===")
        chosen = result.get("search_chosen_candidate", {})
        print(chosen)

        print("\n=== ALLE GEVONDEN KANDIDATEN ===")
        for i, c in enumerate(result.get("search_candidates", []), start=1):
            print(i, c)
    else:
        print("=== TESTMODE: scrape op player_id met incrementele updates ===")
        result = scrape_player(
            player_id=PLAYER_ID,
            headless=False,
            max_periods=None,
            force_full_refresh=FORCE_FULL_REFRESH,
            refresh_recent_periods=REFRESH_RECENT_PERIODS,
        )
        player_id = PLAYER_ID
