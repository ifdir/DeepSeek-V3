# Stand 11 / 11A – SPS V62.7 wiederhergestellt: Planer → Erleben → Formulierung

**Status: ROT – keine Produktfreigabe.** Echte Modellantworten und das Android-Gerät sind nicht geprüft. 12 P25-Tests sind schon im unveränderten P25 rot (Abschnitt 5).

## 1. Was geändert ist (Overlay 11: `matrix_api/llm_contract.py`, `matrix_api/app.py`)

- **Fachlesungen aus der ersten Antwort.**
  - Gilt für: Vollzug, Komponentenart, Sprecher, Wirkung, Bewegung/Bewegungsversuch, Berührung, Bitte-/Erlaubnis-/Grenzbezug, Grenzumfang, Körper + Körperbestätigung, Sprache, Namen, Aussage/Aussage-Tat, Offenbarung, Absichtsart.
  - Diese Lesungen stehen jetzt in der ersten Antwort (Planer, Formulierung bzw. Erleben) im Feld `lesungen`.
  - Jede Lesestelle behält ihren Aufruf, ihre Nachverarbeitung und ihren Kernel-Validator.
  - Nur der Netzaufruf entfällt (`_llm_json` → `ERSTE_ANTWORT_LESUNGEN`).
  - Fehlt eine Lesung, gibt es keinen Ersatzaufruf. Die Sache bleibt unbestätigt.
- **Speicher je Anfrage.** Die Lesungen liegen je Anfrage in einem eigenen Speicher (`contextvars`). Hilfsthreads derselben Anfrage bekommen den Kontext mit (`lesungen_gleichzeitig`, Sprachlesung im Puppet-Weg). Gleichzeitige Anfragen sehen sich nie gegenseitig.
- **Erleben.**
  - Je Figur gibt es einen Aufruf. Der Kausalnachweis `kausalpruefung` steht in derselben Antwort; `dispositionsquellen` bleiben im Payload.
  - Der Antwortraum beträgt 320 + 3200 Tokens: das frühere Erleben plus der Höchstwert des früheren Kausalaufrufs. Eine abgeschnittene Antwort ist ungültig.
  - `_appraisal_cause_proofs` prüft wie bisher.
- **Namen (Wortgrenzen).**
  - Die Lesung kommt aus der Planer-Antwort (Avatar, Puppet) bzw. aus der God-Zerlegung.
  - Die Textpositionen setzt der Server aus seinen eigenen Kandidaten. Danach wird die Zielbindung neu bestimmt.
  - `with_name_boundary_reading` ist unverändert.
- **God/Regie-Körper.** Die Bestätigung der Körperänderung kommt in derselben Antwort wie die Körperlesung. Der Kernel prüft wie bisher.
- **Brief.** „DEINE LAGE JETZT“ steht vor dem Profil. Dazu gehören Gefühl mit Stärke und Ursache, Absicht, Grenzen, Schmerz und die Beziehung zu den betroffenen Personen. Es gibt keine festen Antworten und keine Wortlisten.

## 2. Modellaufrufe (gezählt am Testmodell-Protokoll, 1,5 s je Aufruf)

| Lauf | Stand 10C | Stand 11 |
|---|---|---|
| 5 echte Geräteeingaben (Puppet Johann → Mara) | 9–15 Aufrufe, 12,2–18,4 s je Austausch | **4–5 Aufrufe, 4,7–4,9 s** (Planer 1, Erleben 2–3 parallel, Formulierung 1) |
| Maras Zustand nach 5 Eingaben (Furcht zu Johann) | 0,73 → 0,823 | 0,73 → 0,823 (gleich) |

Im Protokoll gibt es keine ungeskriptete Lesung. `llm_contract.vorab_abrufe()` weist je Anfrage nach, welche Lesung an welcher Stelle angefragt und aus der ersten Antwort beantwortet wurde.

## 3. Kette (Testmodell über den echten HTTP-Weg mit START.py und Neustart)

- F1 (`f1_durchlauf_09.py`): **ERFÜLLT 12/12**.
- Gegenprobe ohne Bedeutung: G4/G4b/G6/G6b sind **ROT**, wie erwartet.
- F2 (`f2_durchlauf_10.py`): **ERFÜLLT 7/7**.
- F1-Rest: Die Grenze „Fass mich nicht an“ steht im Brief.

## 4. Tests

- Mitgelieferte K-Tests: 44/44. `test_k01_p18_portiert_11.py` ersetzt `..._07`; nur `respond()` liefert die Lesungen in der Formulierungsantwort.
- P25-Suite: 435 bestanden, 13 rot. Das ist derselbe Satz wie in 10B; es gibt keine neue Abweichung.
- Angepasste P25-Tests (`overlay/tests`, Basis-Hash in `stage_source_11.py`): Angepasst ist **nur die Aufrufstruktur**, die Schutzaussagen sind unverändert.
  - Das Test-Double liefert dieselben Antworten jetzt in der ersten Antwort.
  - Prüfungen wie „die Lesung lief“ und „ihre Nutzlast“ lesen `vorab_abrufe()`.
  - Die Kausal- und Namensprüfung bestätigt: ein Aufruf, voller Antwortraum, Serverpositionen.

## 5. Offen (nicht grün)

- **12 P25-Tests sind schon im unveränderten P25 rot.**
  - Die Fälle: Identität „Mara Schmidt“/„Anna Mara Nowak“ (5), verneinte Tat neben Rede/Teilablehnung (3), fremde Rede (1), Berührungsklasse (1), Quelltextprüfung p22 (1), `START.bat` fehlt (1).
  - Sie sind nicht durch Stand 11 entstanden und nicht repariert.
  - `test_v92_p18_koerper` (P25-Client-Textweg) bleibt nach K-01 abgewiesen. Die Portierung ist grün.
- **Direkter Commit ohne vorbereitete Eingabe** (`kernel_commit` ohne `pendingInputTurnId`): Dieser Weg hat keine erste Antwort mit Namen. Bei einer unsicheren Namensgrenze wird deshalb nachgefragt. Die Oberfläche nutzt prepare → commit.
- **Echtes Modell:** Der Planer-Prompt ist um ≈22 000 Zeichen Lesungsregeln länger. Ob ein echtes Modell alle Lesungen vollständig liefert, ist **ungeprüft**. Fehlende Lesungen machen die Handlung unbestätigt; sie werden nicht geraten.
- **Android-Gerät:** Das Paket ist gebaut, auf dem Gerät aber nicht geprüft.

## 6. Stand 11A – Befund auf dem Gerät und Reparatur

**Gerät (Upload `34769ab5`, Live-Log 08.11. 20:51, Rohantworten in der Tabelle `logs`; Modell gpt-4o-mini):**
- „Hey süsse“ funktioniert: Erleben mit Kausalnachweis in einer Antwort, Mara reagiert mit Unbehagen.
- „Ich klatsche auf deinen arsch“ wurde **zweimal nichts gespeichert**.
  - Die Planer-Antwort hatte **kein** Feld `lesungen`.
  - Damit wurden Vollzug und Wirkung nicht gelesen (`modell: null`, `keine_pruefung`), und die Tat galt als unbestätigt.
- Die Formulierung lieferte `"lesungen": []`.
- Dauer je Austausch: Planer 11 s, Erleben 20 s, Formulierung 11 s.
- **Messlücke von Stand 11:** Das Testmodell hatte die Lesungen selbst eingesetzt.

**Reparatur 11A** (nur `llm_contract.py`, keine neue Route/Tabelle/Schicht):
- **Lesungen sind Pflichtfelder der ersten Antwort.**
  - Planer: je Komponente `pruefung`, dazu `teilstellen` (Sternchen-Teile, Einzelsätze, eigene Tat in der Ankündigung), `sprache`, `namen`, `grenzumfang`.
  - Formulierung: `pruefung` und `aussagen[].lesung`.
  - God-Körper: `bestaetigung`. God-Zerlegung: `namen`. Erleben: `vorher_absicht_art`.
- **Schemas:** `PLAN_SCHEMA`, `FORMULATION_SCHEMA`, `GOD_SCHEMA`, `GOD_BODY_SCHEMA` werden bei OpenAI **strikt erzwungen**. Andere Anbieter bekommen `json_object` mit demselben Regeltext.
- **Übergabe:** Die Felder gehen über `plan_lesungen` / `antwort_lesungen` in den unveränderten Lesungsspeicher. Lesestellen und Kernel-Validatoren sind unverändert. Fehlt ein Feld, bleibt die Sache unbestätigt.
- **Regeltext des Planers:** 30 000 (Stand 11) → **13 800 Zeichen**. 10C hatte 8 155 Zeichen (+69 %). Das Ziel „≤ 10C + 20 %“ ist **nicht erreicht**; dafür entfallen 9–15 Einzelaufrufe.
- **Testmodell:** ergänzt nichts mehr. Die Drehbücher sind einmal mit `tools/drehbuch_11a.py` in das Schema-Format umgewandelt und gegen die Schemas geprüft (22 Antworten, 0 Abweichungen).

**Geprüft (Testmodell, HTTP-Weg mit START.py):**
- F1: 12/12. Gegenprobe: 8/12, also wie erwartet rot.
- F2: 7/7.
- F1-Rest: Grenze im Brief.
- 5 Geräteeingaben: je 4–5 Aufrufe, 4,7–4,9 s, Mara 0,73 → 0,823 (gleich).
- K-Tests: 49/49, neu `tests/test_erste_antwort_11a.py`:
  - strikter Request an api.openai.com;
  - jede Lesestelle hat ein Pflichtfeld;
  - **wörtliche Geräteantwort ohne Pflichtfelder → unbestätigt**;
  - mit Pflichtfeldern → die Lesung kommt an der Lesestelle an.

**Weiter offen:**
- **Echtes Modell:** Hier nicht prüfbar, das Netzgeheimnis der Umgebung bekommt 401. Abnahme auf dem Gerät.
- **Erleben mit 20 s auf dem Gerät:** Ob 11A insgesamt schneller ist als 10C, zeigt erst der Gerätelauf.

## 7. Stand 11B – zweiter Gerätelauf (Upload `74b5e4f1`, 08.11. 21:58, gpt-4o-mini)

**Befund:**
1. „Ich streiche über deine schenkel“ wurde gespeichert, Mara reagierte. Der Planer las dieselben Worte zweimal, als handlung **und** als rede. Die Folge war ein interner Hinweis „Rede überschneidet sich mit einer Handlung“ an dich.
2. „Ach komm, ich streiche über deibe brust, dir gefällt das ja“ wurde **ganz abgewiesen** (422 PUPPET_TEILABLEHNUNG). Grund: Der Planer ließ „dir gefällt das ja“ aus, und `input_binding_outcome` verwirft bei jedem ungelesenen Rest alles.
3. Maras Gefühl und Absicht wurden verworfen (`kausalpruefung_fehlend:gefuehl/absicht`). Das Modell schrieb den Nachweis in der freien Liste für „aktivierung“ und vergaß „absicht“. Im Brief standen nur Schmerz und die letzte Tat.
4. Dauer: Planer 17 s, Erleben 13 s, Formulierung 16 s.

**Reparatur 11B** (`kernel.py` neu im Overlay, Basis Ebene 09; `llm_contract.py`):
- **Ungelesener Rest:**
  - Er wird **nie** Rede (P25 Paket-8-Prüfung C6 bleibt).
  - Er kippt die Eingabe nur, wenn er ungekennzeichnet eine Person nennt (P24 „Gustav, setz dich.“, R1 „Robert steht auf.“, beide weiter geschützt). Sonst wird gespeichert, was gelesen ist, und der Rest bleibt sichtbar.
  - Rest in einem `*Marker*`: Die Tat bleibt unbewiesen, die Eingabe läuft.
- **Wortgleiche Doppel-Lesung** rede = gelesene handlung: Die Handlung zählt, es gibt keinen Hinweis. Überschneidungen mit anderen Worten oder mit einem Marker bleiben sichtbar.
- **Erleben:** `APPRAISAL_SCHEMA`, bei OpenAI strikt. Der Nachweis steht **direkt neben** jedem vorgeschlagenen Wert. `erleben_aus_antwort` baut daraus die bisherige Struktur mit exakten Feldnamen; `_appraisal_cause_proofs` ist unverändert. Ein Wert ohne Nachweis wird allein verworfen.
- **Planer-Komponente nach Typ:** rede `{komponentenart, sprecher}`, handlung ohne `sprecher`. Deine echten Antworten wären damit rund 24 % kürzer (1 907 → 1 457, 2 088 → 1 578 Zeichen).

**Geprüft:**
- Deine zwei Eingaben **wörtlich** (rohe gpt-4o-mini-Antworten, `tools/drehbuch_geraetefall_2158_11b.json`, `tools/geraetefall_11b.py`):
  - beide 200;
  - Johann: Tat Schenkel / „Ach komm“ + Tat Brust;
  - Hinweis nur `rest_ohne_komponente: dir gefällt das ja`, kein Doppelungs-Hinweis;
  - Mara: Gefühl Bedrohung 0,80, Absicht „sich zurückziehen“, Furcht zu Johann 0,79 → 0,853;
  - im Brief des Folgezugs: Gefühl, Ursache, Absicht und Grenzverletzung.
- F1: 12/12. Gegenprobe: 8/12, also wie erwartet rot.
- F2: 7/7.
- F1-Rest: Grenze im Brief.
- 5 Gerätefälle: 4–5 Aufrufe, Mara 0,73 → 0,823.
- K-Tests: 50/50.
- P25-Suite: 436 bestanden, 12 rot (alle vorbekannt), **neu grün:** `test_p10_partial_and_multiple_markers_over_the_route`.

**Offen:**
- „dir gefällt das ja“ wird nicht zur Rede, solange das Modell es keinem Teil zuordnet. Der Planer-Text verlangt jetzt ausdrücklich, dass jedes Wort in einer Komponente steht.
- Echtes Modell, Zeit und Reaktion: Abnahme auf dem Gerät.

## 8. Stand 11C – eine Äußerung bleibt eine Äußerung (deine Rückmeldung 08.11. 22:22 / 22:37)

**Befund:**
- „Hey süsse“ (22:22) und „dir gefällt das ja“ (21:58) gingen verloren. Die P25-Regel C6 („ungelesener Rest nie Rede“) hat sie verworfen, weil das Modell sie keinem Teil zugeordnet hat.
- Maras Brief zeigte deine Eingabe nur zerlegt („JETZT TUT …“). Weggefallene Worte hat sie nie erfahren.
- Die Vergleichs-KI (22:37) gibt die ganze Nachricht an die Figur, und die Figur antwortet auf alles zusammen.

**AMASTER:**
- §27.4: Die Puppet-Eingabe ist die tatsächliche Rede oder Handlung der Figur.
- §34.1: Getrennt wird nur zur Prüfung der Wirkungen. Ein Scheitern vernichtet keine andere Komponente. Ungeprüftes bleibt sichtbare Redeprovenienz, ohne Körper- oder Weltwirkung.

**Reparatur 11C:**
- **`kernel._speech_from_components`: kein Wort geht verloren.** Ungekennzeichneter Text ohne geprüfte Handlung und ohne fremden Namen ist Rede der Figur (Provenienz `rest_als_rede`, nie Tat).
  - Ausnahmen bleiben geschützt: `*Marker*`-Rest, abgeschnittene Lesung, Wortrest direkt an einer abgewiesenen Komponente („Johann küsst Mara **nicht** und sagt: Hallo“), fremder Name (P24/R1).
  - C6 ist für diesen Fall aufgehoben; Test `test_unassigned_text_is_visible_and_never_spoken` ist mit Begründung angepasst.
- **Wahrnehmung der ganzen Äußerung:**
  - Die Puppet-TurnTruth trägt `wortlaut` (die ganze Eingabe; Provenienz, keine Wahrheit).
  - Die antwortende Figur bekommt im Brief „JETZT – …, die ganze Äußerung wörtlich: „…““ und darunter „Davon wirklich geschehen (geprüft): …“ bzw. „keine Handlung – nur Worte“.
  - Wirkungen kommen weiter nur aus geprüften Facts.
- **UI (`eingabe-hinweis.ts`):** Keine internen Lesevermerke mehr (Rest-als-Rede, Doppelung, verneinte oder ungeprüfte Teil-Tat, Marker-Rest). Hinweise mit Folge für dich bleiben (z. B. Wirkung nicht angewendet), ebenso Rückfragen.

**Geprüft (Testmodell):**
- Gerätefälle:
  - „Hey süsse ich klatsche dir auf deinen arsch“ → Johann: Rede „Hey süsse“ + Tat.
  - Schenkel → Tat.
  - „Ach komm, ich streiche über deibe brust, dir gefällt das ja“ → Rede „Ach komm dir gefällt das ja“ + Tat; Maras Brief enthält den ganzen Satz wörtlich und darunter die geprüfte Tat.
  - Mara: Bedrohung 0,80, Absicht „sich zurückziehen“, Furcht zu Johann 0,79 → 0,85 → 0,90.
- F1: 12/12. Gegenprobe: 8/12, also wie erwartet rot.
- F2: 7/7.
- 5 Gerätefälle: 4–5 Aufrufe.
- K-Tests: 50/50.
- P25-Suite: keine neue Abweichung außer dem bewusst angepassten C6-Test.
