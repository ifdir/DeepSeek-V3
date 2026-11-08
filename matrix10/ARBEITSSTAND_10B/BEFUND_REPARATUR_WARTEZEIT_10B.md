# Stand 10B: Reparatur der Wartezeit nach Kettenvertrag §6

**§6.1 Basis:** P25 (SHA-256 `33a51497…`), Vergleichsstand 10A `663eaaf`, Gerätebeleg 08.11. (Pydroid 3).

**§6.4 Defekt:**
- Ein Austausch dauert auf dem Gerät 41–49 s.
- Gemessen (Teil 1, `ARBEITSSTAND_10A/BEFUND_GLEICHSTAND_P25_10A.md`): P25 und 10A sind identisch, je Austausch laufen 8–12 Modell-Lesungen **nacheinander**.

**§6.5 Erste falsche Naht (Codestellen):**
- **Nach der Figurenantwort:** `kernel_commit` (app.py) ruft nacheinander
  - `_disclosure_step` (Offenbarung),
  - `_effect_check_step` (Bewegung/Wirkung),
  - `_koerper_check_step` (eigener Körper),
  - `_consent_scope_check` (Grenzumfang).

  Jede dieser Lesungen liest nur die Antwort der Figur und schreibt in ein eigenes Feld (`proposals.offenbarung` / `proposals.wirkung` / Körperlesung / `plan.grenze`). Keine braucht das Ergebnis einer anderen. Die Wartezeit summiert sich trotzdem.
- **Puppet:** `_read_language` (Namen/Wortbedeutungen) liest nur den Rohtext, wartet aber auf die ganze Vollzug-, Körper- und Wirkungs-Kette.

**Vorhandene SPS-Lösung:**
- V62.7: Bewertung „je Figur ein Modellvorschlag (parallel)“, umgesetzt in `appraise_events` mit eigenem Thread je Figur und Audit danach.
- V54/V59C/V65K: Netzaufrufe laufen außerhalb der Schreibsperre.

**§6.6 Reparatur (nur `matrix_api/app.py`, Ebene 10B):**
- `lesungen_gleichzeitig` führt die oben genannten unabhängigen Lesungen gleichzeitig aus. Jede Lesung bekommt eine eigene SQLite-Verbindung (autocommit, außerhalb der Schreibsperre).
- Die Ergebnisse werden **in derselben Reihenfolge und mit derselben Fehlerbehandlung** übernommen wie im Ablauf nacheinander.
- Abgesichert sind zwei Sonderfälle:
  - Bei abweichender Eingabe (Client-Vorschläge werden erst zusammengeführt) bleibt es beim Ablauf nacheinander.
  - Weicht die Vorbedingung der Sprachlesung vorher und nachher ab, wird die Sprachlesung nacheinander ausgeführt.
- Es gibt keine neue Lesung, keine Lesung entfällt, keine neue Route, Tabelle oder Schicht.

**Nachweis (Testmodell mit 1,5 s je Aufruf, deine 5 Geräte-Eingaben, Neustart vor Eingabe 4):**

| Austausch | Aufrufe P25 / 10A / 10B | Dauer 10A | Dauer 10B |
|---|---|---|---|
| 1 | 9 / 9 / 9 | 12,2 s | 10,7 s |
| 2 | 11 / 11 / 11 | 12,3 s | 9,3 s |
| 3 | 11 / 11 / 11 | 12,3 s | 9,4 s |
| 4 | 15 / 15 / 15 | 18,4 s | 14,0 s |
| 5 | 12 / 12 / 12 | 14,0 s | 11,0 s |

- **Gespeicherter Endstand 10B = 10A:** Fakten, Wahrnehmung, Beziehungen, Ziele, Züge, TurnTruth, Zustände, Szene, Rahmen. Die einzige Ausnahme, die Reihenfolge zeitgleicher Erinnerungen, schwankt schon zwischen drei Läufen von 10A.
- Mara: Furcht 0,73 → 0,823 in P25, 10A und 10B gleich.
- F1 12/12, F2 7/7, alle 42 Prüftests grün.
- Neuer Test `tests/test_lesungen_gleichzeitig_10b.py`: grün auf 10B, rot auf 10A.

**Erwartung auf dem Gerät:** etwa 20–25 % weniger Wartezeit je Austausch (aus 41–49 s etwa 31–38 s). Gemessen ist das nur mit dem Testmodell, auf dem Gerät noch nicht.

**Weiter offen (P25-Bestand, unverändert):**
- Die Zahl der Modellaufrufe (Kosten). Weniger Aufrufe hieße, SPS-Lesungen zusammenzulegen oder zu streichen. Das ist eine fachliche Entscheidung gegen SPS-Belege.
- Wiederholung: AMASTER §51.3, §28 Schritt 19 (K-13).
- AutoChat läuft nur über den Browser (K-05).
