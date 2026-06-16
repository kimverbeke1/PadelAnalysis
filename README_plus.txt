PADELANALYSIS - CLEANUP FIX V-NEXT
=================================

Nieuw in deze cleanup-fix:
- failed_periods wordt opgeschoond:
  - succesvol herhaalde periodes verdwijnen uit open failures
  - failed_periods_last_run toont alleen de laatste scrape
  - failed_periods_open toont nog open/onopgeloste failures
- dashboard toont nu standaard de teller van de laatste run, zodat oude ontbrekende periodes niet meer misleidend blijven hangen

Dit is een patch bovenop je huidige V2-naamfix versie.
