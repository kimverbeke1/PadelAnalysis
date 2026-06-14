V4 - SPELER ZOEKEN OP NAAM + INCREMENTEEL SCRAPEN
==================================================

Wat is nieuw?
- player_search.py
  Zoekt eerst een speler op naam via de publieke spelerszoekpagina
  en probeert zijn player_id / dashboard_url te vinden.

- scraper.py
  Ondersteunt nu incrementele updates:
  * eerste run: scrape alle periodes
  * volgende runs: scrape enkel nieuwe periodes + de meest recente N periodes opnieuw

Waarom opnieuw de meest recente periodes scrapen?
- Omdat daar nog nieuwe matchen kunnen bijkomen.
- Zo vermijd je dat je telkens ALLES herscrapet en toch recente updates mist.

Bestanden:
- firebase_service.py
- player_search.py
- scraper.py
- test.py
- reset_test.py

Gebruik:
1) Eventueel resetten:
   py .\reset_test.py

2) Test via player_id:
   Zet in test.py:
   TEST_MODE = "by_id"

3) Test via naam:
   Zet in test.py:
   TEST_MODE = "by_name"
   NAME_QUERY = "Voornaam Achternaam"
   CLUB = None of clubnaam

4) Run test:
   py .\test.py

Incremental instellingen:
- FORCE_FULL_REFRESH = False
- REFRESH_RECENT_PERIODS = 2

Aanbevolen setup:
- Laat standaard incrementieel lopen
- Gebruik force_full_refresh alleen als je een volledige rebuild wilt
- Bewaar zoekresultaten in cache om anti-bot te beperken
