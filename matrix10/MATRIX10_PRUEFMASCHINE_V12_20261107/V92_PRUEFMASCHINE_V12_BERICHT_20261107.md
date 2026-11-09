# MATRIX10 V92 – Prüfmaschine V1.2 (Bericht vom 7. November 2026)

**Auftrag:** ChatGPT-Entscheidung „Zuerst Prüfmaschine V1.2, mit nachgewiesener vollständiger Fehlererkennung und ohne falsches GRÜN“ sowie die unabhängige Negativprüfung der V1 (beides von Ajp weitergegeben). Keine Produktreparatur, kein P26.

## GELESEN

- Die unabhängige Negativprüfung (`PRUEFMASCHINE_V1_UNABHAENGIGE_NEGATIVPRUEFUNG_20261107.md`) und ChatGPTs 7 Änderungen.
- Das hochgeladene ZIP: byte-gleich mit meiner V1-Abgabe (d8f2c78b…).
- **Sollquellen:** `2_7master.txt` (095d4554…), dort:
  - §26 Z.1325–1356: Anwesenheit und Wissenswege;
  - §39 Z.2077–2099: WitnessKnowledge;
  - §49 Z.2750–2803: BrainContext;
  - Z.222.
- Kettenvertrag §16: die 20 Glieder.
- **Kandidaten:**
  - P25 (33a51497…);
  - P24, nur als Rekonstruktion (8a232c4b…);
  - P23 (4d711308…);
  - P22 (f21a46d3…) als Basis.
- **Produktcode P25:**
  - Wahrnehmung `kernel.py` Z.1067–1099;
  - Zeugenwissen-Writer Z.2271–2284;
  - God-Körper Z.10734–10745;
  - Regie-Ablehnung `app.py` Z.2811–2834;
  - Avatar-Eingabe-Commit `app.py` Z.1690–1700;
  - Szenenblock `scene_state.py` Z.1160–1185;
  - Prompt-Verlauf `llm_contract.py` Z.2054–2075.
- **Logs:** alle Live-Logs, Prompts und JUnit-Ausgaben der Läufe.

## FEHLT

- AMASTERv2.md(1).txt und Matrix10.txt (Kettenvertrag §0).
- Die Test-EPUB.
- Ein echtes P24-ZIP.
- Ein Windows-Rechner.

## STATUS

| Gegenstand | Status |
|---|---|
| Prüfmaschine V1.2, Selbstabnahme (109 von 109 Proben bestanden) | **ABGENOMMEN** |
| Kandidat P25 | **ROT** |
| Freigabe insgesamt | **ROT** |

- Abnahme-Manifest: `ABNAHME_V12.json`, SHA-256 9e145601…
- Die Freigabe ist zusätzlich BLOCKIERT: Das Quellenregister ist nicht bestätigt, und 12 Achsen sind UNGEPRÜFT.

---

## 1. Ergebnis

- **Alle sechs Befunde der Negativprüfung sind richtig.** Ich habe sie am V1-Code nachgestellt (`BELEGE/NEGATIVPRUEFUNG_V1_NACHGESTELLT.txt`).
- **V1.2 baut die Prüfarchitektur um:** Es gibt eine einzige Entscheidungslogik (`pm_auswertung.py`), die nichts glaubt und alles nachrechnet.
  - GRÜN ist nur möglich, wenn jede Pflichtprüfung genau einmal vorliegt und alle 16 Achsen mit allen Pflichtfällen und je 20 Gliedern belegt sind.
  - Die Maschine prüft erst sich selbst und friert sich dann ein.
- **Die Selbstabnahme hat bestanden:** 109 von 109 Proben, ausgeführt aus dem frisch entpackten Werkzeug-ZIP (21e86d07…).
  - 9 Mutationen trafen alle 21 vorab festgelegten Prüfpunkte.
  - P23, P24 und P25 werden an ihren bekannten Fehlern unterschieden.
  - Die richtigen Vergleichsfälle bestehen.
  - Ein echter Abbruch wird erkannt.
  - Jede Manipulation des Ergebnisses verhindert die Freigabe.
- Die Originaldatenbank ist vor und nach allen Läufen unverändert (e03dc445…).

## 2. Die sechs Befunde der Negativprüfung – nachgestellt und behoben

| # | Befund (V1) | Nachgestellt | V1.2 | Gegenprobe in der Selbstabnahme |
|---|---|---|---|---|
| 1 | `fall_status([])` = GRÜN | ja, auch bei nur einem grünen Glied | genau die Glieder 1–20 je einmal; NICHT_ZUTREFFEND nur, wo der eingefrorene Katalog es mit Begründung erlaubt | A: leere, einzelne, doppelte und unerlaubt nicht zutreffende Glieder sind nie GRÜN |
| 2 | `entscheidung` mit 1 Prüfung und 1 Achse = GRÜN | ja | Pflichtprüfungsliste aus den Regeln (48 Pflichtprüfungen); alle 16 Achsen Pflicht | A: fehlende, doppelte oder UNGEPRÜFTE Prüfung/Achse ergibt BLOCKIERT; GRÜN bleibt erreichbar |
| 3 | rote Fälle entfernt → 4 Achsen GRÜN | ja (echter P25-Lauf) | Pflichtfälle je Achse in den eingefrorenen Regeln; ein fehlender Fall ergibt BLOCKIERT | D: am echten P25-Ergebnis PU2, GO1 und RE1 einzeln entfernt → Achse nie GRÜN |
| 4 | Glied 13: irgendein PROMPT mit dem Text | ja | Wissensnachweis gebunden an Spur, Sitzung, Sprecher, Zeitpunkt und kanonisches Zeugenwissen (siehe 4.3) | D: falscher Sprecher, fremde Spur, fremde Sitzung, Text fehlt, kein Zeugenwissen, kein Zeuge, PROMPT vor dem Commit, kein Folgezug → je ROT |
| 5 | Mutation: `s0 != ROT`, `any(treffer)` | ja | Ausgangslage genau GRÜN, mutiert genau ROT, und zwar an **jedem** vorab festgelegten Punkt; nicht ausgeführt / Abbruch / Modell-Fehlgriff = nicht erkannt | C: 21 Punkte aus 9 Mutationen |
| 6 | Gate ignoriert `gesamt`, `abbruch`, Rückgabecode, Vollständigkeit | ja | Echtheit (ZIP-, Prüfer- und Katalog-Hash), Rückgabecode zu `gesamt`, Abbruch, Fallmenge und jeder Fallstatus werden nachgerechnet | D und E: Abbruch mit Teilresultat, falsches `gesamt`, falscher Rückgabecode, fremdes ZIP, falscher oder fehlender Katalog-Hash, unbekannter Fall, falsche Achse, rot gemeldet als GRÜN; dazu ein **echter** Abbruch (Port belegt) |

## 3. Weitere Schwächen der V1, die ich selbst gefunden habe

1. **Glieder ohne Prüfung GRÜN.** Die Glieder 1, 7 und 8 waren immer GRÜN. Glieder 6, 9 und 17 waren ohne Katalogerwartung GRÜN.
   - Neu: Glied 7 prüft die Ausgangslage (Anwesende, Ort, Wahrnehmungsfähigkeit), sonst BLOCKIERT.
   - Neu: Jeder Fall muss für Fakten und Rückanzeige eine Erwartung nennen.
2. **UI-Prüfung über die ganze Seite.** Die Seitenleiste enthält immer „Küche“, und der Sitzungsname enthielt die Fallwörter, z. B. „bewusstlos“.
   - Neu: Geprüft wird nur der Gesprächsverlauf (ARIA `role="log"`).
   - Neu: Die Sitzungen heißen neutral „Fall NN“.
   - Neu: Die Rückanzeige wird auch **nach dem Server-Neustart** in der Oberfläche geprüft (Glied 16).
3. **Glied 5 nicht an die Hauptanfrage gebunden.** Die Log-Stationen wurden aus dem ganzen Fall genommen, einschließlich Folgezug.
   - Neu: Nur die Spur der Hauptanfrage zählt.
4. **Glied 6 ohne Commit-Prüfung.** Glied 6 ist neu an den SQLITE_COMMIT der Hauptspur gebunden.
   - Mutation M3 („meldet Erfolg, schreibt nichts“) loggt selbst `SQLITE_COMMIT PASS`. Erkannt wird sie nur über die getrennte SQLite-Messung.
5. **Folgezug ohne Modellnachweis.** Neu verlangt Glied 14 eine fehlerfreie Modellantwort (`MODEL_REPLY source=llm`) und einen Commit in **der** Spur, die die Folgezug-Facts geschrieben hat.
6. **Sprechfähigkeit im Folgezug.** Neu prüft Glied 15, ob der Folgezug-Sprecher anwesend und sprechfähig ist.
7. **Nebenwirkung nur einmal sichtbar.** Mutation M4 setzte in V1 nur einmal einen festen Wert, darum war der zweite Fall blind. Jetzt ändert M4 den Wert bei jedem Aufruf.

## 4. Die neue Logik

### 4.1 Vollständigkeit

**Fall:** Ein Fall ist nur GRÜN, wenn alle 20 Glieder einzeln belegt sind.

Ein Glied darf nur NICHT_ZUTREFFEND sein, wenn der eingefrorene Katalog es erlaubt und die Begründung aus dem Vertrag nennt:

| Fall | Nicht zutreffend | Begründung |
|---|---|---|
| Abgelehnte Eingaben (PU3, AV2, RE2) | 13–15 | Z.262 |
| GO2 | 13–15 | §46.6, God erfindet keinen Folgeakt |
| GO1 | 13 | Soll offen, siehe 7 |

**Freigabe:** Sie verlangt 48 Pflichtprüfungen und 16 Achsen. Jede fehlende, doppelte oder offene ergibt BLOCKIERT.

### 4.2 Übernahme der Kette

Die Freigabe rechnet aus den Gliedern selbst nach und vergleicht mit den Angaben des Kettenprüfers:

- Status je Fall;
- Gesamtstatus;
- Rückgabecode;
- ZIP-, Prüfer- und Katalog-Hash;
- Abbruch;
- Vollständigkeit der Fälle.

Bei jedem Widerspruch ist der Lauf BLOCKIERT.

### 4.3 Wissen im Folgezug (Glied 13)

Nachgewiesen ist es nur, wenn alles gilt:

1. Die Folgezug-Figur S ist Zeuge des Haupt-Stimulus, also der Rede oder Handlung (§49.2).
2. S hat dazu **kanonisches Zeugenwissen** in SQLite (heard/seen/affected, §39). Ausnahme: S hat es selbst getan (Z.1340).
3. Die Spur, die die Folgezug-Facts geschrieben hat, bindet genau diese Sitzung und genau S (KERNEL_BIND).
4. In genau dieser Spur steht **nach** dem Hauptcommit ein PROMPT für S, der das Ereignis enthält.

Glied 10 prüft neu:

- Jeder Zeuge braucht Zeugenwissen.
- Abwesende bekommen weder Zeugenschaft noch Zeugenwissen.
- Es gibt kein Zeugenwissen ohne Zeugenschaft.

**Grenze:** Ob die Figur das erhaltene Wissen inhaltlich richtig **verwendet**, ist ohne Wortlisten nicht mechanisch prüfbar. Das bleibt offen.

### 4.4 Unabhängigkeit

- Die Maschine ist nur nach bestandener Selbstabnahme gültig. Das Manifest hält die Hashes aller 18 Maschinendateien.
- Die Freigabe prüft das Manifest **vor und nach** dem Lauf. Jede geänderte, fehlende oder neue Datei ergibt BLOCKIERT. Das ist in Teil F gegengeprüft.
- Das Produkt läuft in einem eigenen Arbeitsordner und bekommt nur eine DB-Kopie.
- Prüfer, Sollwerte und Fallkatalog liegen nur in der Maschine.
- Eine Regeländerung ist eine neue Maschinenversion und braucht eine eigene Selbstabnahme.

## 5. Selbstabnahme (109 von 109 Proben)

| Teil | Inhalt | Proben |
|---|---|---|
| A | Entscheidungslogik: die Befunde 1 und 2, GRÜN erreichbar, ROT/BLOCKIERT korrekt | 21 |
| B | Unterscheidung von P23, P24 und P25 an bekannten Fehlern; Vergleichsfälle grün | 22 |
| C | 9 Mutationen: 9-mal ausgeführt, 21 Prüfpunkte getroffen | 30 |
| D | Gegenproben an den echten P25-Ergebnissen und am echten Wissensnachweis | 27 |
| E | echter Abbruch (Port 5050 belegt) | 2 |
| F | Manifest: ohne, passend, Katalog geändert, Datei hinzu, Regeln entfernt, nicht bestandene Abnahme; Maschine während des Laufs unverändert | 7 |

**Mutationen.** Die Erwartungen wurden vorab aus dem Vertrag festgelegt. Jede Mutation ändert genau eine Stelle im Produkt.

| Mutation | Erwartete Punkte (alle getroffen) |
|---|---|
| M1 Writer schreibt die Eingabe einer anderen Figur zu | PU1/09, PU2/09 |
| M2 Rede an falschen Adressaten | PU2/09 |
| M3 Erfolg gemeldet, nichts gespeichert | PU1/06, 09, 13; PU2/06, 09, 13 |
| M4 Figurenstamm nebenbei verändert | PU1/18, PU2/18 |
| M5 Abwesende hören und sehen mit | PU1/10, PU2/10 |
| M6 kein Zeugenwissen geschrieben | PU1/10, 13; PU2/10, 13 |
| M7 Avatar-Eingabe an falschen Adressaten | AV1/09 |
| M8 God-Körperänderung landet bei falscher Figur | GO1/11 |
| M9 Regie ohne gebundene Wirkung wird nicht abgelehnt | RE2/05, 06 |

**Unterscheidung der Kandidaten** (Sollwerte vorab eingefroren in `kp_selbstabnahme_soll.json`):

- **P23:** ROT, weil der Kandidat nicht baut.
- **P24:**
  - ROT an PU4/05, 06, 09 (R1);
  - ROT an PU2/04 (B1);
  - PU1 GRÜN.
- **P25:**
  - ROT an PU2/04 (B1), GO1/10 (B2), RE1/11 (B3);
  - PU1, PU3, PU4, AV1, AV2, GO2 und RE2 sind alle GRÜN; alle 20 Glieder sind belegt, NICHT_ZUTREFFEND nur, wo der Katalog es erlaubt.

## 6. Freigabelauf V1.2 gegen P25

Mit abgenommener Maschine, Wiedergabe der 72 echten Modellantworten, 0 Fehlgriffe.

**Ergebnis: ROT.** Alle 48 Pflichtprüfungen und eine Info-Prüfung liegen vor. Von diesen 49 Prüfungen sind 19 PASS, 17 ROT, 12 UNGEPRÜFT (Achsen) und 1 BLOCKIERT (Quellenregister).

**Maschine:**

- vor dem Lauf abgenommen (PASS);
- nach dem Lauf unverändert (PASS).

**Technik:**

- TypeScript: 606 Fehler, 1 neuer (TS2352).
- pytest: 448 Tests gelaufen, Exitcode 1 passend zum Ergebnis.
  - neu rot: 3;
  - unverändert rot: 9.

**Kette:**

- 7 Fälle GRÜN, jeweils mit allen 20 Gliedern belegt.
- PU2, GO1 und RE1 ROT.
- Achsen:
  - Avatar GRÜN;
  - Puppet, God und Regie ROT;
  - 12 Achsen UNGEPRÜFT.

## 7. Produktbefunde aus V1.2

B1–B3 sind unverändert bestätigt, die Ursachen stehen im V1-Bericht.

**B4 (neu gemessen, RE1 Glied 10).** Im Regie-Pfad widersprechen sich Zeugenliste und Zeugenwissen.

- Gemessen:
  - Regie-Fact und body_state-Fact führen Johann und Mara in `witnessedBy`.
  - Für beide gibt es kein Zeugenwissen.
  - Beim physical-Fact steht für beide „heard“.
- Nach §39 (Z.2081) hält WitnessKnowledge den Wahrnehmungsweg. Nach §26 gibt es Wissen nur über einen gültigen Weg.
- Welche der beiden Angaben falsch ist, entscheidet der Vertrag nicht eindeutig. Sicher ist: Sie widersprechen sich. Der Fix ist offen.

**Hinweise, nicht geprüft:**

- `scene_state.py` Z.1183 spiegelt „Letzte körperliche Handlung“ ohne Wahrnehmungsfilter in jeden Brief. Das ist möglicherweise Wissen ohne Wahrnehmungsweg (§49 „darf nicht Wissen verteilen“). Ein Kettenfall dafür fehlt noch.
- In GO1 und RE1 spricht Gustav im Folgezug „user“ an, obwohl kein Avatar beteiligt ist. Das ist UNKLAR und nicht bewertet.

**GO1, Glied 13 bleibt NICHT_ZUTREFFEND.** Ob Anwesende einen von God gesetzten Körperzustand wahrnehmen, legt der Master nicht eindeutig fest: Z.1340–1352 nennt „God setzt Wissen“ nur für Betroffene. Das muss der Vertragseigner entscheiden, nicht die Maschine.

## 8. Eigene Fehler und Korrekturen während V1.2 (offen gelegt)

Gefunden im Entwicklungslauf, alles vor der Selbstabnahme korrigiert:

1. **Zu breiter Wissensnachweis.** Ich hatte für Glied 13 alle beobachtbaren Haupt-Facts verlangt. Der body_state-Fact trägt aber technischen Text („Körperzustand — posture …“), der in keinem Brief stehen kann.
   - Korrigiert auf den Stimulus (Rede/Handlung), nach §49.2.
2. **Zu enges Glied 5.** Ich hatte für Glied 5 eine VALIDATION in der Hauptspur verlangt. Der Avatar-Weg lehnt aber vor der Validierung ab (AV2).
   - Laut Kettenvertrag Zeile 5 geht es um die „erste serverseitige Bindung“. Jetzt gilt: Die Spur muss zur Sitzung gehören und KERNEL_BIND oder TARGET_BIND enthalten.
3. **Live-Aufnahme als Maschinenänderung.** Eine Live-Modellaufnahme im Maschinenordner hätte die Abnahmeprüfung nach dem Lauf fälschlich gebrochen. Live-Aufnahmen sind jetzt ausgenommen.
4. **Windows-Start:** `python -I -c "import pm_auswertung"` findet das Modul nicht.
   - Korrigiert. Die Datei ist trotzdem ungeprüft.

## 9. Grenzen

- **Nur 4 von 16 Achsen haben Kettenfälle.** Damit ist heute keine Freigabe möglich, und das ist gewollt.
- **Die Mutationserwartungen habe ich selbst aus dem Vertrag abgeleitet.** Eine unabhängige Stelle sollte sie gegenlesen.
- **Wiedergabe statt Live.** Die Wiedergabe gilt nur für die aufgenommenen Kandidaten. Ein neuer Kandidat braucht `--modell live`.
- **P24 ist nur rekonstruiert.**
- **Windows ist ungeprüft.**

## 10. Entscheidungen und nächster Schritt

1. **§0-Nachtrag, weiterhin offen.** Ajp bestätigt `NACHTRAG_01_SOLLQUELLEN_ENTWURF.txt` oder lehnt ihn ab.
2. **Nächste Maschinenversion V1.3.** Sie braucht Kettenfälle für die 12 fehlenden Achsen, jeweils mit eigener Selbstabnahme. Benötigt werden:
   - die Test-EPUB für §7;
   - Upload-Testdateien für Modus A und B (§13);
   - Fälle zu Fate, AutoChat, Reset/Snapshot, Provider/Konfiguration, Spawn, Memory/Beziehung und §5.
3. **Danach P26 als Gesamtkette:** B1–B4, TS2352, Test- und Quellenkonflikt beim Puppet-Wächter, R2/R3. Erst nach der Abdeckung, nicht vorher.
