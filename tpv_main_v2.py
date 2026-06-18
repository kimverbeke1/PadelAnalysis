from __future__ import annotations

import json
from pathlib import Path

from tpv_scraper_v2 import scrape_player_index, scrape_player_v2

# ---------------------------------------------------------
# CHANGE ONLY THESE VALUES FOR TESTING
# ---------------------------------------------------------
PLAYER_ID = '214435'     # Alexandra Chardon example from discussion
HEADLESS = False
SAVE_TO_FIREBASE = False
MODE = 'phase1'          # 'index_only' or 'phase1'


if __name__ == '__main__':
    if MODE == 'index_only':
        result = scrape_player_index(player_id=PLAYER_ID, headless=HEADLESS)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print('\nSaved debug files under debug_output_v2/')
    else:
        result = scrape_player_v2(
            player_id=PLAYER_ID,
            headless=HEADLESS,
            follow_first_tournament=True,
            follow_first_interclub=True,
            save_to_firebase=SAVE_TO_FIREBASE,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print('\nSaved debug files under debug_output_v2/')
