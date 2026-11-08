# Arbeitsstand 07 – K-01 TurnTruth- und Commit-Bindung (mit W2) und SEC Schlüssel-Leck

**Status Gesamtprodukt: ROT.** Keine Produktfreigabe. Der Gesamtlauf endet mit Exit 2.
**Basis:** P25 (`33a51497…`) + 06a, frisch aus Git `05d8e8a`.
**Commits:**
- `3349958` SEC
- `329df34` K-01
- `8ebc842` Kartenwerkzeug

**Abnahme:** frischer Klon von `329df34`, `run_chain_07.py`, Belege in `evidence/chain_07/`.

## 1. Doku-Lage und Methode

- **Gelesen:**
  - AMASTERv2 `fb4f2015…` (§4, §6, §23, §25–§28, §34–§36, §43, §50, §60, §68, §69);
  - Matrix10.txt `1465980a…`;
  - Kettenvertrag `e62cf6bc…` §1–§6 und §16;
  - SPS V71 im P25-Produkt, darin die Lösungen V65F (Bedienperson, `default_input_actor_id`, `followAs`), V65U (`pendingInputTurnId`, Antwortversuch, Neustart beendet Versuche) und V65Z (Schreibkette).
- **Fehlt:**
  - Original-DB, Provider-Schlüssel, Test-EPUB, P23- und P24-ZIPs;
  - alles mit echtem Modell bleibt deshalb **BLOCKIERT**.
- **Methode:** Kettenvertrag §6.
  - Basis eingefroren, Codefluss kartiert.
  - Ausgangsnachweis am unveränderten Stand.
  - Erste falsche Naht bestimmt, Kette vollständig repariert.
  - Negativ- und Mutationsproben, Regression.
  - Abnahme am frisch ausgecheckten Stand.

## 2. Erste falsche Stelle und Root-Cause

**Erste falsche Naht:** `app.py` `kernel_prepare` und `kernel_commit`.
- `bound = dict(raw)` übernahm die TurnTruth des Clients.
- `kernel.default_input_actor_id` (`kernel.py:1002–1004`) ließ einen expliziten Clientwert immer gewinnen.
- `commit` nahm `result`, `fired`, `contradictions` und `proposals` aus dem Request-Body (`app.py:1987/1991/2033`).

`/api/llm/formulate` liest den Zustand dagegen bereits serverseitig neu (`llm_contract.canonical_formulation_context`). Zwischen Formulierung und Commit gab es aber keine Bindung.

**Ausgangsnachweis am unveränderten Stand:**

| Befund | Messung | Beleg |
|---|---|---|
| Fremder Eingabe-Actor | Live `START.py`: Bedienperson sendet `inputActorId=Mara`; Rede-Fact mit Actor Mara gespeichert | `GESAMTKARTE_07/belege/live/L_turntruth_07.json` |
| Nie formulierte Figurenrede committet, nach Neustart erhalten | live, ebenda | ebenda |
| `result.proposals.synapsen` vom Client ändert die Runtime | Testclient 06a: `runtime_geaendert = true` → **jetzt bestätigt** (zuvor UNGEPRÜFT) | `chain_07/AUS_ohne_k01_06a.json` |
| `fired` vom Client ändert die Runtime | 06a: **nein**, also nicht als Produktdefekt bezeichnet (Einordnung: Synapsen-Wirkung ist offen, K-03); die Annahme ist trotzdem gesperrt, weil der Client keinen Zustand liefert | ebenda |
| Leere Hörerliste → alle Anwesenden Zeugen in Behauptungsregister/Frames | 06a: Mara als Zeugin trotz `hearsIds=[]` | ebenda |
| Bewusstlose Figur (consciousness 0) als Sprecher wählbar | `float(0 or 1)` = 1; 06a: prepare 200 | K-01-Tests auf 06a: 22 failed |
| W2: Annahme ohne eigene Äußerung bindet die Frage der anderen Figur, Status `accepted` | Kernelprobe, Szenario 3 | `GESAMTKARTE_07/belege/proben/probe_w2.py` |
| SEC: `GET /api/mcc` liefert `apiKey` im Klartext | `test_sec_mcc_07.py` auf 06a ROT | Commit `3349958` |

## 3. Änderung (Diffs in `patches/*.06a_to_07.patch`), Zuordnung AMASTER/SPS

| Datei | Änderung | AMASTER / Kettenvertrag | SPS genutzt |
|---|---|---|---|
| `app.py` | `eingabe_binden`: Eingabe-Actor aus Session + Modus (Bedienperson `user`, Avatar, Beobachter); ein abweichender oder Figuren-Actor auf dem Normalweg führt zu **422 `EINGABE_ACTOR_UNGEBUNDEN`**. Szene, Zeit und Upload kommen aus SceneState und Fokus. Die TurnTruth-ID vergibt der Server. | §8, §23, §27.2, §27.4; KV §4 | V65F (Mapping von `default_input_actor_id` ohne Client-Vorrang) |
| `app.py` | **Turn-Beleg** (prepare) und **Formulierungsbeleg** (formulate). Beide sind HMAC dieses Serverprozesses über Session, TurnTruth-Kern, `turnIndex`, Sprecher, eigene `fired`/`contradictions` und das Formulierungsergebnis. `commit` nimmt nur genau diese Werte. Abweichungen ergeben **422 `TURN_BELEG_UNGUELTIG`** bzw. **`FORMULIERUNG_UNGEBUNDEN`**, gespeichert wird nichts. Bei offener Eingabe muss der jüngste beendete Antwortversuch die Formulierung sein. **Kein Store, keine Tabelle, kein Schema.** | §28 Schritte 8/18–20, §50; KV §4, §9 | V65U `pendingInputAttempt` und Boot-Semantik: Ein Neustart beendet unfertige Versuche |
| `kernel.py` | `figure_speaker_eligible` (eine Prüfung für die Server- und die UI-Wahl). Fehler `consciousness or 1` behoben. | §28 Schritt 16, §43 | `pick_speaker` (ausgezogen, nicht verdoppelt) |
| `kernel.py` | Hörer von Behauptungsregister/Frames über `_scene_perception` | §26, §39 | vorhandener Wahrnehmungs-Owner |
| `kernel.py` | **W2:** `lifecycle_evidence_fact`. Evidenz ist die eigene Äußerung/Handlung des Actors. Ohne Evidenz ändern sich weder Status noch Lifecycle. | §34, §35, §36.3 | — |
| `scene_state.py`, `repos.py` | W2-Leseseite und Schreibgrenze: Fremde Evidenz bindet nicht. Ohne Evidenz muss der Actor eine **Partei des Quellturns** sein (Sprecher, Eingabe-Actor oder Puppet). Ausdrücklich **nicht** „actor == speaker“. | §34, §36.3, §68 Nr. 9 | V70 `lifecycle_bound` erweitert |
| `repos.py` (SEC, eigener Commit) | `get_mcc` gibt `public_config_view` zurück (Vorhandensein und Maske) | §60, §67; KV §14 | vorhandene Maskierung von `/api/config` |
| `kernel-bridge.ts`, `chat.$sessionId.tsx` | reichen die Belege durch | KV §5 | keine neue Route, kein neuer Store |

Rust (Einwilligungsreducer, ABI 3) ist unverändert. Es gibt keine doppelte Geschäftslogik.

## 4. Abnahme am frisch ausgecheckten Stand (`run_chain_07`, Klon `329df34`)

| Stufe | Ergebnis |
|---|---|
| 0 Integrität (P25-Hash, Stage frisch, 6 Overlay-07-Dateien, Abbruch bei fehlender Overlay-Datei) | PASS |
| A, B (cargo 86/86), C (ABI 3) | PASS |
| D Einwilligungskette an echten Writern + SQLite | **10/10** (in 06a 9/10; W2 jetzt erfüllt) |
| D2 gegen P25 | PASS, 0 verschlechtert |
| D3 HTTP (12 Anfragen × ok/fehlt/abi2) | PASS: ok 12×200, Ausfall 503 mit Code, nichts gespeichert |
| K2a Fehlerinjektion (8 Szenarien, `commit` jetzt über Belege) | 0 fail-open, 0 falsche Meldungen |
| D3F Frontend-Fehleranzeige (M3) | PASS |
| **K** (K-01, SEC und portierter P18-Test) | **29/29** |
| **AUS** Ausgangsnachweis 06a | Hörer-Rückfall und Client-Synapsen reproduziert; K-01-Tests auf 06a: 22 rot |
| **MUT** 11 Mutationen (Belegsignatur, Eingabe-Actor, Formulierung, fired, Sprechfähigkeit, Hörer, W2 ×4, SEC) | **11/11 erkannt** |
| **LIVE** `START.py` + gebautes Frontend + Chromium | **14/14** (siehe unten) |
| E Gegenprobe Einwilligung | ROT wie in 06a: Die Rust-only-Mutation „ohne Sprecherbindung“ erkennt die Kette nicht (dokumentiert, kein künstliches GRÜN) |
| F P25-Suite | 421/25/1 statt 422/24/1. **Einzige Abweichung:** `P18AvatarAndFigure::test_avatar_position_and_figure_reply_with_forged_and_real_readings` (siehe 5) |
| G Prüfmaschine V12 | BLOCKIERT |

**LIVE-Kriterien.** Der echte Startweg, Bedienung über die Oberfläche:
- Nutzer wählen, unter Konfiguration „Nur lokale Synapse“ setzen, Session „Fall 06“ öffnen.
- Als Bedienperson senden, dann „Figuren jetzt weiterreden lassen“.
- Echter Neustart, neu laden, erneut senden.

Ergebnisse:
- `prepare → formulate → commit` liefert je 200.
- Der Eingabe-Actor ist `user`.
- Die gespeicherte Figurenrede ist genau der Servertext und erscheint im UI.
- Der Verlauf ist nach dem Neustart sichtbar.
- Der Folgeturn nach dem Neustart: Commit 200, der Prepare-Kontext enthält die erste Figurenrede.
- Gefälschte Anfragen gegen den laufenden Server, fremder Actor und erfundene Rede: 422, SQLite unverändert.
- Die fremde Session bleibt unverändert.
- Der Schlüssel steht weder in `/api/mcc`, noch im `localStorage`, noch in den Logs.

Screenshots liegen in `evidence/chain_07/live/`.

## 5. Bestehende Tests: eine begründete Abweichung, keine Abschwächung

Der P25-Test `test_avatar_position_and_figure_reply_with_forged_and_real_readings` schickt Maras Antwort als Client-Text an `commit`. Das ist genau der reparierte Defektpfad. Nach K-01 erhält er 422.

Er wird **nicht** geändert. Seine Assertions laufen **unverändert** in `tests/test_k01_p18_portiert_07.py` über den Produktweg `prepare → formulate → commit` und bestehen. Die Gegenprobe im selben Test zeigt: Der alte Client-Text-Weg wird abgewiesen, es wird nichts gespeichert. Alle übrigen 446 P25-Ergebnisse sind gleich; die 24 Fehlschläge und 1 Fehler der P25-Altbefunde bleiben ROT.

Die 06-Proben, die committeten, laufen als 07-Fassungen (`probe_http_503_07.py`, `probe_failpoint_07.py`) mit unveränderten Prüfaussagen. Die Figurenantwort entsteht über `prepare` (Wiederaufnahme) → `formulate`. Das Modell wird dabei nur als Transport ersetzt.

## 6. Vertragsstatus nach Stand 07

| Punkt | Status |
|---|---|
| K-01 TurnTruth- und Commit-Bindung (offline, Live-UI, Neustart, Folgeturn) | **GRÜN** (offline, lokale Synapse) |
| K-01 Formulierung mit echtem Modell | **BLOCKIERT** (kein Provider-Schlüssel) |
| W2 Lifecycle-Evidenz = eigene Äußerung (Kernel, Leser, Schreibgrenze, 4 Mutationen) | **GRÜN** (offline) |
| SEC kein Schlüssel in Antworten, Browser oder Logs | **GRÜN** |
| C04, S05, W1/W3, K1, K2, M2, M3, M1-Rust-Unit, M1 kombiniert | GRÜN (unverändert) |
| P25-Altbefunde (24 + 1) | **ROT** |
| M1 Rust-only-Mutation über die Kette | **ROT** |
| K2a (2 Stellen nie erreicht), V12, Modell-Folgeturn | **BLOCKIERT** |
| **Gesamt** | **ROT, Exit 2** |

## 7. Was K-01 bewusst nicht schließt (offen, in der Karte eingetragen)

- **Sprecherauswahl:** Der Browser wählt weiter (`pickSpeaker`), der Server prüft nur Anwesenheit und Fähigkeit. Der zweite Owner bleibt, die Zeitlage der Wahl vor dem Eingabe-Commit ebenfalls. Gehört zu K-05.
- **Ausgabeprüfung:** §28 Schritt 19 (Darstellungsgrenzen) fehlt weiterhin. Gehört zur LLM-/Renderer-Kette.
- **Hörer der Antwortphase:** Sie stammen vom Eingabezeitpunkt. Ein Writer für „später informiert“ fehlt (T-20).
- **Modell-Synapsen:** Sie wirken weiter als `validated`, mit fester Wirkungstabelle (Z-22). Gehört zu K-03.
