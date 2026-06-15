TPV URL SEARCH FIX
==================

Wat is aangepast?
- player_search.py gebruikt nu rechtstreeks de TPV zoek-URL met:
  - playerName = achternaam
  - playerFirstName = voornaam
- dashboard.py gebruikt die verbeterde externe zoekstap automatisch bij naamzoeking
- bestaande players-data wordt meteen geladen als player_id al in Firestore zit
- nieuwe spelers worden automatisch opgehaald met zichtbare statusmelding

Belangrijk:
- geen detectie-omzeiling / stealth
- wel caching, incrementele updates en duidelijke statusmeldingen
