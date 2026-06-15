PADELANALYSIS - PLUS BUNDLE V2
=============================

Extra t.o.v. vorige versie:
- Als je een naam ingeeft zonder lokale profielhit, probeert dashboard nu automatisch extern te zoeken.
- Als exact 1 speler gevonden wordt:
  - en data bestaat al in Firestore: die wordt meteen geladen
  - en data bestaat nog niet: er start automatisch een scrape met zichtbare melding
- Als meerdere externe hits gevonden worden: je kiest eerst de juiste kandidaat, daarna wordt bestaande data geladen of automatisch opgehaald.

Belangrijk:
- Er is GEEN stealth / detectie-omzeiling ingebouwd.
- Wel caching, incrementele updates en zichtbare statusmeldingen.
