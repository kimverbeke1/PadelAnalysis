PADELANALYSIS - PLUS BUNDLE
==========================

Wat zit in deze versie?
- Zoek op naam in dashboard (op basis van player_profiles in Firestore)
- Snellere scraper dankzij incrementele updates
- Betere UI met extra filters, trends en samenvattingen

Belangrijk:
- Dashboard gebruikt root firebase_service.py
- scraper/__init__.py heeft GEEN side effects
- scraper/firebase_service.py is enkel een shim naar root firebase_service.py

Lokale scraper setup:
- py -m pip install -r requirements.txt
- py -m playwright install chromium

Cloud / Streamlit:
- Dashboard werkt publiek met Firestore-data
- Live Playwright scraping is vooral bedoeld voor lokaal/admin gebruik
- Zet Firebase secrets in Streamlit under App settings > Secrets
