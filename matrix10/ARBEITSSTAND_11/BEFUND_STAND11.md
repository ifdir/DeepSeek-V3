# Stand 11 – SPS V62.7 wiederhergestellt: Planer → Erleben → Formulierung

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
