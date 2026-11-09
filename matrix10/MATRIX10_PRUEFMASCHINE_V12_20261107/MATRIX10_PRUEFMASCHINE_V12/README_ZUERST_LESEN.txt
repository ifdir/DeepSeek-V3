MATRIX10 – PRÜFMASCHINE V1.2
Freigabesperre V1.2 + unabhängiger Kettenprüfer V1.2 + Selbstabnahme
Stand: 7. November 2026

WAS DAS IST
Ein Prüfprogramm, getrennt vom Produkt. Es ändert keinen Matrix10-Code und nie die Originaldatenbank
(es arbeitet nur mit einer Kopie). Es entscheidet, ob ein Matrix10-ZIP freigegeben werden darf.
GRÜN gibt es nur, wenn JEDE Pflichtprüfung genau einmal vorliegt und bestanden ist und ALLE 16
Pflichtachsen mit allen Pflichtfällen und je 20 Kettengliedern nachgewiesen sind.
Fehlt ein Nachweis: BLOCKIERT. Ein Vertragsfehler: ROT.

REIHENFOLGE (verbindlich)
1. SELBSTABNAHME_V12.py   prüft die Maschine selbst. Nur wenn alles besteht, schreibt sie ABNAHME_V12.json
                          (Hashes aller Maschinendateien).
2. FREIGABE_PRUEFEN_V12.py prüft einen Kandidaten. Ohne gültige Abnahme oder bei einer geänderten Maschinendatei
                          (vor ODER nach dem Lauf) ist das Ergebnis BLOCKIERT.
Eine Änderung an Prüfer, Regeln, Fallkatalog oder Sollwerten ist eine NEUE Maschinenversion und braucht eine
neue Selbstabnahme. Produktreparaturen dürfen die Maschine nicht verändern.

BESTANDTEILE
- pm_auswertung.py             die EINE Entscheidungslogik (Fallstatus, Übernahme der Kette, Wissensnachweis,
                               Freigabeentscheidung, Abnahme-Manifest). Kein Netz, keine Datenbank.
- FREIGABE_PRUEFEN_V12.py      Freigabesperre: Abnahme, ZIP, Sollquellen, Frontend-Bau, TypeScript und pytest
                               (mit Rückgabecodes) gegen die P22-Basis, Kettenprüfer mit ALLEN Pflichtfällen,
                               Vorbefunde, 16 Achsen.
- SELBSTABNAHME_V12.py         Gegenproben (Logik und echte Ergebnisse), Mutationen M1-M9, Unterscheidung
                               P23/P24/P25, echter Abbruch, Manifestschutz.
- PRUEFREGELN_V12.json         eingefrorene Regeln: Sollquellen, 16 Pflichtachsen mit Pflichtfällen, P22-Basis,
                               Hashes der Kettenprüferdateien und der Auswertung.
- kettenpruefer/               bedient die echte Oberfläche (Chromium), echtes Modell über Proxy, liest SQLite
                               über eine getrennte Nur-Lese-Verbindung, prüft je Fall alle 20 Glieder.
  kp_faelle.json               10 Fälle (Puppet, Avatar, God, Regie) mit Erwartung je Glied; NICHT_ZUTREFFEND nur
                               mit Begründung im Katalog.
  kp_mutationen.py             9 eingebaute Fehler mit VORAB festgelegten erwarteten (Fall, Glied)-Punkten.
  kp_selbstabnahme_soll.json   bekannte Fehler von P23/P24/P25 und Vergleichsfälle, die bestehen müssen.
- modellaufnahmen/P25, P24     mitgeschnittene echte Modellantworten (keine Schlüssel) für die Wiedergabe.
- basis/                       P22-Basis: 415 Tests, 9 rot; 605 TypeScript-Fehler.

AUFRUF (Linux, so geprüft)
  python3 -I SELBSTABNAHME_V12.py --p25 <P25.zip> --p24 <P24.zip> --p23 <P23.zip> --db <Original-DB> \
          [--node-cache <Ordner mit node_modules>] --playwright <Pfad zum playwright-Modul>
  python3 -I FREIGABE_PRUEFEN_V12.py --kandidat <Matrix10.zip> --db <Original-DB> --modell live \
          --aufnahme <neuer Ordner> [--node-cache ...] --playwright <...>
  Für einen neuen Kandidaten immer --modell live (ca. 70 Modellaufrufe). --modell wiedergabe nur für P25.

WINDOWS
  PRUEFMASCHINE_STARTEN_WINDOWS.bat – UNGEPRÜFT (kein Windows-Rechner in dieser Umgebung).

EXITCODES   0 = GRÜN, 2 = ROT, 3 = BLOCKIERT.

GRENZEN
- Kettenfälle gibt es für 4 von 16 Achsen (Puppet, Avatar, God, Regie). Die übrigen 12 sind UNGEPRÜFT,
  deshalb kann heute kein Kandidat GRÜN werden.
- Quellenentscheidung (Kettenvertrag §0) wartet auf den Vertragseigner: Prüfung 03 BLOCKIERT.
- Test-EPUB fehlt.
- Der Wissensnachweis (Glied 13) belegt, dass die richtige Figur das Ereignis im richtigen Folgezug ERHALTEN
  hat. Ob sie es inhaltlich richtig VERWENDET, ist mechanisch ohne Wortlisten nicht prüfbar und bleibt offen.
