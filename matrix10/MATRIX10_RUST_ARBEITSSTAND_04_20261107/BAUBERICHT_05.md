# Matrix10 – Rust-Arbeitsstand 05 (Nachtrag auf 04)

**Stand:** 7. November 2026. **Gesamtstatus: ROT, keine Produktfreigabe.**
**Teilstatus der Consent-Reader-Kette (Reader → FFI → Rust → Projektion): TEILGRÜN.**

## GELESEN / GEPRÜFT

- Paket 04: SHA-256 `04b870cb…ca66b`, ZIP-Integrität PASS, alle Einträge aus `SHA256SUMS.txt` stimmen.
- `BAUBERICHT_04.md`, `README.md`, `RUST_MIGRATION_STATUS.json`, Paketprüfung 04.
- Code: `integration/scene_state.py` (Reader), `integration/native_boundary.py` (FFI), `src/consent.rs`.
- **AMASTER vollständig gelesen (§1–§70)**, Auswertung als Gesamtsystem (siehe „AMASTER-Entscheidung“).
- SPS: V65X (Z. 1390–1425), V60.5 (Z. 4149), V62.1 (Z. 4014), V65S-Tabelle (Z. 2229), Bedienperson (Z. 967).
- Leserkette: `act_consent` (Konsument aller drei Reader für eine konkrete Tat), `body_contact_state`.
- `integration/repos.py`: `append_session_fact` → `_check_fact_boundary` → `_native_boundary` (Kontextaufbau).

## FEHLT

- `MATRIX10_V67_ABHAENGIGKEIT_20261031.zip` (SHA-256 `5158df26…efed`). Ohne diese Datei gibt es kein V67-`ids.py`, keine Writer und keine SQLite-Datenbank.
  Deshalb sind `test_consent_projection_04`, `test_restriction_contract_02`, `probe_native_sqlite_04` und `probe_original_consent_04` hier **NICHT_PRÜFBAR**.

## Neu in 05

1. **Rust-Toolchain vorhanden** (`rustc 1.97.0`). Blocker aus 04 aufgehoben.
2. **Ein Gesamtlauf** `tools/run_chain_05.py`. Jede Stufe muss grün sein, sonst Abbruch:

| Stufe | Inhalt | Ergebnis |
| --- | --- | --- |
| 0 | SHA256SUMS Stand 04; nur die 5 bewusst geänderten Dateien dürfen abweichen | 0 unerwartete Abweichungen |
| A | ohne Rust: fail-closed (Transport 02, Consent-Transport 03) | 13/13 + 8/8 |
| B | `cargo test --offline --locked` | **86/86 real ausgeführt** (78 aus 04 + 8 neu) |
| C | `cargo build --release --offline --locked` | PASS, ABI 3, `.so` SHA-256 `146db175…d6f7` |
| D | mit Rust: Consent-Transport 03 + **Gesamtkette 05** | 8 (1 Skip by design) + **18/18** |
| E | Gegenprobe: 4 Regeln in Rust einzeln entfernt (Sprecher, Fenster, Tat-Antwort hebt Grenze auf, Tat-Bindung) | alle 4 **erkannt** (Kette rot) |
| F | Schreibgrenze Lifecycle, echte `.so` (`tools/probe_writer_semantics_05.py`) | Kontrollen korrekt, **3 Defekte belegt (ROT)** |

Status des Gesamtlaufs: `TEILGRUEN_CONSENT_READER_KETTE__WRITER_ROT`.

3. **Gesamtkette 05** (`tests/test_consent_native_chain_05.py`) prüft ohne Mock:
   - **Zeitleiste mit 15 Ereignissen.** Nach **jedem** Ereignis werden **alle drei Reader gemeinsam** abgefragt (`body_contact_standing`, `restricted_permissions_standing`, `restricted_refusals_standing`). Die Ereignisse enthalten fremde und leere Sprecher, abgelaufene und gültige Zeitfenster, andere Stimme („meine rechte Hand“), Widerruf und mehr als 6 Ereignisse.
   - **Kreuz-Invarianten:** Kein Körperteil ist gleichzeitig erlaubt und abgelehnt. Zustand und Ausnahmen stammen nur vom Giver. Ausnahmen unter Ablehnung und Einzelerlaubnisse laufen nicht auseinander.
   - Unabhängigkeit von der Speicherreihenfolge, Fenstergrenzen (inklusiv, fehlender Zeitpunkt), Szenenfenster bei Ortswechsel, unbestätigter Teil, Gegenseite, Kompositum („Handtasche“).
   - **Differenzlauf gegen Original-V67:** Der Original-Reader wird aus `patches/scene_state.py.patch` rückwärts rekonstruiert. Sein SHA-256 `2d3c0dfa…17fe` muss dem V67-Wert entsprechen. Ergebnis: alle 4 C04-Fälle im Kandidaten SOLL und im Original rot. Die erste Abweichung in der Zeitleiste stammt von einem Ereignis der Defektklasse (fremder Sprecher oder abgelaufenes Fenster).
   - `matrix_api.ids` ist ein Stub, der **bei jedem Aufruf fehlschlägt**. Er beweist, dass die Reader keine IDs erzeugen. Er ist keine Nachbildung der V67-Datei.

   - **Gesamtsystem über `act_consent`** (6 Tests): Kette Ereignis → drei Reader → Rust → `act_consent` → Zustand einer *konkreten* neuen Berührung, jeweils gegen V67.

Geänderter Produktcode in 05: nur `consent.rs`, `lib.rs` (ABI 3), `native_boundary.py`, `scene_state.py` (`body_contact_entries`). Diff zum V67-Original: `patches/scene_state.py.patch05`.

## Schreibgrenze: belegter Defekt (Stufe F)

Codepfad (IST): `append_session_fact` → `_check_fact_boundary` → `_native_boundary("fact")` → Rust `boundary::fact`.
Der Kontext enthält nur cast, operators und Quell-IDs. Proposition, berechtigter Empfänger und TurnTruth-Sprecher fehlen.
Der Rust-Code sagt das selbst: *„structural validation, NOT semantic effect authorization“*.

| Fall | AMASTER | SOLL | IST |
| --- | --- | --- | --- |
| W1 Alice stimmt im Namen von Bob zu | §36.3 Sprecher/Empfänger | abweisen | **angenommen** |
| W2 Actor ≠ Sprecher der Quell-TurnTruth | §34.1 Actor aus TurnTruth | abweisen | **angenommen** |
| W3 Lifecycle ohne `propositionId` | §36.2/§35 dieselbe Proposition | abweisen | **angenommen** |
| U1 Ablehnung ohne `responds_to_fact_id` | §36.2 vs. §34.1 „gesetzte Grenze“ | UNKLAR | angenommen |
| K1 gültige Ablehnung von Bob | Kontrolle | annehmen | angenommen |
| K2 fremde Quell-TurnTruth | Kontrolle | abweisen | abgewiesen |

Folge: Falsch zugeschriebene Einträge landen dauerhaft (append-only) im Bestand. Der Reader aus Stand 04/05 filtert sie beim Lesen heraus. Andere Leser dieser Fakten (Memory, Beziehung, Folgeturn) sind dadurch **nicht** geschützt. Geprüft: UNKLAR, Code fehlt.

**Kein Patch in 05. Grund:** Die Lifecycle-Einträge schreibt `kernel.apply_proposition` (V67-`kernel.py`), und diese Datei fehlt. Ohne sie ist nicht belegt,
- welche `event_kind` mit welchem `actorId` legitim geschrieben werden (z. B. `request` vom Fragenden, `fulfilled`),
- ob die Bedienperson (`_OPERATOR_IDS`) als Avatar im Namen des Givers antwortet.

Eine Sperre ohne diesen Beleg kann gültige Writes in die Quarantäne schicken.

**Korrektur nach SPS-Prüfung:** Eine allgemeine Regel „acceptance nur vom Empfänger“ wäre falsch. SPS V60.5 (Z. 4149) erlaubt bei allgemeinen Propositionen die *Annahme durch den Steller* nach gebundener Antwort (→ `fulfilled`). Die Bindung an die berührte Figur gilt laut SPS Z. 2229 (V65S, §36.2: „nur die Berührte entscheidet“) und V62.1 nur für die Angelegenheit **Körperkontakt**. Die Bedienperson `user` ist laut SPS Z. 967 als Actor und Target zulässig. Ist sie die Berührte, ist sie auch der Giver.

**Minimaler Patchplan (erst mit V67, korrigiert):**
1. `repos._native_boundary`: Nur für `operation == "fact"` mit `kind == "lifecycle"` **und** `payload.koerperkontakt` kommen zwei Felder in den Kontext: die gespeicherte Proposition (`kind`, `actorId`, `targetId`) und der Sprecher der Quell-TurnTruth (über das vorhandene `_turn_truth_row`). Kein neuer Store, keine neue Route.
2. Rust `boundary::fact`: Gilt nur, wenn die Proposition die Art `koerperkontakt` hat und `event_kind` nach `_KK_KIND` Zustimmung, Ablehnung oder Widerruf ist. Dann muss gelten: actor == Proposition.targetId == TurnTruth-Sprecher, und `propositionId` ist Pflicht. Alle anderen Lifecycle-Arten (V60.5 `fulfilled` usw.) bleiben unberührt.
3. ABI 2 → 3. Python und Rust gleichzeitig umstellen.
4. Abnahme im selben Gesamtlauf: W1–W3 werden abgewiesen, K1/K2 bleiben gleich, C04 und Zeitleiste bleiben grün. **Zusätzliche Gegenprobe:** Eine V60.5-Annahme durch den Steller bei einer Nicht-Körperkontakt-Proposition wird weiter angenommen. Dazu kommen reale V67-Writes über SQLite.

**No-Touch:** Reader-Logik aus 04/05, `restriction.rs`, andere Writer-Operationen (`truth`, `god`, `relation`, `witness`, `ids`), vorhandene Fakten (kein Umschreiben historischer Zeilen), GodCommandParser, SocialMatrix, Routen.

route-safe für diesen Plan: **UNKLAR** bis `kernel.py` gelesen ist.

## AMASTER-Entscheidung: Antworten auf eine konkrete Tat (Patch in 05)

**Gesamtsystem-Befund (Altfehler V67, in 04 nach Rust übernommen).** Er ist nur im Zusammenspiel sichtbar: Standing-Reader + Erlaubnis-Reader + `act_consent`.

| Kette | V67 / Stand 04 | SOLL |
| --- | --- | --- |
| Bob lehnt jede Berührung ab → erlaubt rechte Hand → Hand-Tat a3 → Bob widerruft, gebunden an a3 → neue Hand-Tat a5 → Kuss a6 | a3 accepted, **a5 accepted, a6 unknown** | a3 accepted, **a5 declined, a6 declined** |

Ursache: In `reduce_standing` beendete *jeder* Widerruf (auch „diese Tat“) die Ablehnung jeder Berührung. Danach war `body_contact_standing` leer, und `act_consent` fiel auf den Erlaubnis-Zweig zurück. Die Einzelerlaubnis blieb stehen. Bobs Widerruf hat also *mehr* Berührung erlaubt.

**Regel, abgeleitet aus dem AMASTER als Ganzes:**
- §68.35/§34.1: Ein kanonisch gebundener Current State wird ohne neue gültige Evidenz nicht zurückgestuft.
- §35/§36.3: Current State kommt aus der neuesten *gültigen* Evidenz derselben Proposition. Eine Zustimmung gilt nur, wenn sie gebunden ist und keine spätere Evidenz die Sache geschlossen hat.
- §34.1: Jede Komponente hat ihre eigene Bindung.
- §36.4: Widerruf ist neue Evidenz.
- SPS V65X Z. 1414: „eine Erlaubnis für eine einzelne Tat hebt die Grenze nicht auf. Eine Ablehnung einer Tat oder ein Widerruf ohne Stelle beendet eine Erlaubnis weiterhin (vorsichtige Richtung).“

Daraus folgt für eine Ablehnung oder einen Widerruf mit Scope `diese_tat`:
1. Sie ist nur Evidenz für die Taten, an die sie gebunden ist (`actFactIds`), und wirkt nur in die vorsichtige Richtung.
2. Unter **breiter Zustimmung**: Sie beendet die Zustimmung (SPS). Unverändert.
3. Unter **breiter Ablehnung**: Sie hebt die Ablehnung **nie** auf. Sie beendet die Ausnahme-Erlaubnisse, deren Stelle eine gebundene Tat nennt.
4. **Eigenständige Einzelerlaubnis**: Sie endet, wenn eine gebundene Tat ihre Stelle nennt. Eine Tat an einer anderen Stelle (Schulter, linke Hand) beendet sie nicht.
5. Antwort ohne gebundene Tat, oder eine gebundene Tat existiert nicht: vorsichtig, alle Erlaubnisse/Ausnahmen enden.
6. Fremder, leerer oder abgelaufener Sprecher: keine Wirkung (wie 04).

Damit ist auch der frühere UNKLAR-Punkt (Einzelerlaubnis nach Widerruf ohne Stelle) entschieden, ohne Vorgabe von außen. Die beiden SPS-Sätze widersprechen sich nicht. Bindung entscheidet, und Unbindbares wirkt vorsichtig.

**Umsetzung (route-safe: JA).** Kein neuer Store, keine Route, kein zweiter Owner, keine Python-Entscheidung:
- `scene_state.body_contact_entries` liefert zusätzlich `actTexts` (die gespeicherten Texte der gebundenen Taten aus denselben Session-Fakten) und `actsBound`. Diese Werte werden nur transportiert.
- Rust `consent.rs` entscheidet mit dem vorhandenen `restriction::names_restriction`, ob eine Tat eine Stelle nennt. Ändert sich die Eintragsform, ist das ein Vertragsbruch → **ABI 2 → 3** (Python und Rust gleichzeitig).
- Python prüft die Rückgabe strenger: Eine beendete Ablehnung darf nur durch eine breite Zustimmung beendet sein.
- No-Touch eingehalten: `restriction.rs`, Writer-Operationen, `act_consent`-Logik, Fakten (append-only), Routen.

**Risiko:** Die Regel braucht korrekt gebundene `actFactIds`. Diese kommen vom Lifecycle-Writer, und den deckt Stufe F nicht ab (siehe Schreibgrenze). Ein falsch gebundener Widerruf kann eine Erlaubnis beenden, aber nie eine Grenze aufheben. Der Fehler geht also nur in die vorsichtige Richtung.

## Weiter offen (aus 04, unverändert)

1. Native Writer-, SQLite-, Neustart- und Folgeturn-Kette mit echtem V67 (benötigt V67-ZIP). C04 und B01–B04 dort grün nachweisen.
2. Schreibgrenze für Lifecycle-Einträge: Defekt jetzt belegt (Stufe F), Patchplan siehe oben. Benötigt V67-`kernel.py`.
3. Übrige Kernel-, Memory-, Erfahrungs-, Welt- und BrainContext-Kette nach AMASTER/SPS.
4. HTTP/Frontend über sichtbare Bedienung, V12-Abnahme. Erst danach Livetest.

## Reproduktion

```sh
python3 -B tools/run_chain_05.py      # Exit 0 = Stufen 0, A–F gelaufen; Status nennt Writer-ROT
```
