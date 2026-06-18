TPV SCRAPER V2 - TECHNICAL PROOF OF CONCEPT
===========================================

Purpose
-------
This V2 proof of concept keeps your existing Streamlit + Firebase project intact and adds a NEW scraping layer next to the current files.

It does NOT overwrite your current dashboard or old scraper flow.

New files
---------
- tpv_models_v2.py
- tpv_parser_v2.py
- tpv_firebase_adapter_v2.py
- tpv_scraper_v2.py
- tpv_main_v2.py

What this V2 does
-----------------
Phase 1 proof of concept for 1 player:
1. open the player results page (used as central match index)
2. parse all candidate rows with date + type + detail link
3. classify entries as:
   - tornooi
   - interclub
4. follow first tournament link
5. follow first interclub link
6. normalize data into:
   - player_matches
   - team_ties
   - team_pairings
7. optionally save back into Firebase in a legacy-compatible document shape

Important
---------
This site appears mostly server-rendered / HTML-driven rather than JSON API driven.
So the new approach is DOM/HTML-first, with Playwright for navigation.

How to test
-----------
1) Index only
   Edit tpv_main_v2.py:
   MODE = 'index_only'
   then run:
   py tpv_main_v2.py

2) Phase 1 full proof-of-concept
   Edit tpv_main_v2.py:
   MODE = 'phase1'
   py tpv_main_v2.py

3) Optional Firebase save
   Set:
   SAVE_TO_FIREBASE = True
   only once index + detail parsing looks good.

Debug output
------------
All html/json debug files are saved under:
- debug_output_v2/

Migration strategy
------------------
Keep your existing files.
If V2 works well, then later we can switch dashboard.py to read the new normalized fields.
