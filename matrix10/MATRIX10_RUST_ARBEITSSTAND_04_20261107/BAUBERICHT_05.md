# Matrix10 – Rust-Arbeitsstand 05 (Nachtrag auf 04)

**Stand:** 7. November 2026. **Gesamtstatus: ROT, keine Produktfreigabe.**
**Teilstatus der Consent-Reader-Kette (Reader → FFI → Rust → Projektion): TEILGRÜN.**

## GELESEN / GEPRÜFT

- Paket 04: SHA-256 `04b870cb…ca66b`, ZIP-Integrität PASS, alle Einträge aus `SHA256SUMS.txt` stimmen.
- `BAUBERICHT_04.md`, `README.md`, `RUST_MIGRATION_STATUS.json`, Paketprüfung 04.
- Code: `integration/scene_state.py` (Reader), `integration/native_boundary.py` (FFI), `src/consent.rs`.
- AMASTER §34 bis §37 vollständig gelesen (Zeilen 1270–1480 im eingepackten AMASTER).
- `integration/repos.py`: `append_session_fact` → `_check_fact_boundary` → `_native_boundary` (Kontextaufbau).

## FEHLT

- `MATRIX10_V67_ABHAENGIGKEIT_20261031.zip` (SHA-256 `5158df26…efed`). Ohne diese Datei gibt es kein V67-`ids.py`, keine Writer und keine SQLite-Datenbank.
  Deshalb sind `test_consent_projection_04`, `test_restriction_contract_02`, `probe_native_sqlite_04` und `probe_original_consent_04` hier **NICHT_PRÜFBAR**.

## Neu in 05

1. **Rust-Toolchain vorhanden** (`rustc 1.97.0`). Blocker aus 04 aufgehoben.
2. **Ein Gesamtlauf** `tools/run_chain_05.py`. Jede Stufe muss grün sein, sonst Abbruch:

| Stufe | Inhalt | Ergebnis |
| --- | --- | --- |
| 0 | SHA256SUMS Stand 04 | 0 Abweichungen |
| A | ohne Rust: fail-closed (Transport 02, Consent-Transport 03) | 13/13 + 8/8 |
| B | `cargo test --offline --locked` | **78/78 real ausgeführt** |
| C | `cargo build --release --offline --locked` | PASS, `.so` SHA-256 `0bd03507…bb94`, reproduzierbar |
| D | mit Rust: Consent-Transport 03 + **Gesamtkette 05** | 8 (1 Skip by design) + 10/10 |
| E | Mutationsprobe: Sprecherbindung bzw. Gültigkeitsfenster in Rust entfernt | beide **erkannt** (Kette rot) |
| F | Schreibgrenze Lifecycle, echte `.so` (`tools/probe_writer_semantics_05.py`) | Kontrollen korrekt, **3 Defekte belegt (ROT)** |

Status des Gesamtlaufs: `TEILGRUEN_CONSENT_READER_KETTE__WRITER_ROT`.

3. **Gesamtkette 05** (`tests/test_consent_native_chain_05.py`) prüft ohne Mock:
   - **Zeitleiste mit 15 Ereignissen.** Nach **jedem** Ereignis werden **alle drei Reader gemeinsam** abgefragt (`body_contact_standing`, `restricted_permissions_standing`, `restricted_refusals_standing`). Die Ereignisse enthalten fremde und leere Sprecher, abgelaufene und gültige Zeitfenster, andere Stimme („meine rechte Hand“), Widerruf und mehr als 6 Ereignisse.
   - **Kreuz-Invarianten:** Kein Körperteil ist gleichzeitig erlaubt und abgelehnt. Zustand und Ausnahmen stammen nur vom Giver. Ausnahmen unter Ablehnung und Einzelerlaubnisse laufen nicht auseinander.
   - Unabhängigkeit von der Speicherreihenfolge, Fenstergrenzen (inklusiv, fehlender Zeitpunkt), Szenenfenster bei Ortswechsel, unbestätigter Teil, Gegenseite, Kompositum („Handtasche“).
   - **Differenzlauf gegen Original-V67:** Der Original-Reader wird aus `patches/scene_state.py.patch` rückwärts rekonstruiert. Sein SHA-256 `2d3c0dfa…17fe` muss dem V67-Wert entsprechen. Ergebnis: alle 4 C04-Fälle im Kandidaten SOLL und im Original rot. Die erste Abweichung in der Zeitleiste stammt von einem Ereignis der Defektklasse (fremder Sprecher oder abgelaufenes Fenster).
   - `matrix_api.ids` ist ein Stub, der **bei jedem Aufruf fehlschlägt**. Er beweist, dass die Reader keine IDs erzeugen. Er ist keine Nachbildung der V67-Datei.

Keine Änderung an Rust- oder Python-Produktcode. Neu sind nur ein Test, ein Werkzeug, Evidenz und dieser Bericht.

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

## UNKLAR (nicht entschieden, kein Patch)

AMASTER §36.4 sagt nur: *„Bruch, Widerruf und Widerspruch erzeugen neue Evidenz. Sie löschen das frühere Commitment nicht aus der Geschichte.“* Die beiden folgenden Punkte entscheidet es **nicht**. Ein Patch muss sich daher auf SPS/Kettenvertrag oder eine Vorgabe des Users stützen:

- **Breite Zustimmung → Einzelerlaubnis → Widerruf (`revoke`, Scope `diese_tat`):** `body_contact_standing` meldet `revoked`. `restricted_permissions_standing` behält die Einzelerlaubnis aber bei, weil nur ein `jede_beruehrung`- oder ein gleichstelliger `eingeschraenkt`-Eintrag sie beendet. Ob ein Widerruf der breiten Zustimmung eine *vorher eigenständig* gegebene Einzelerlaubnis mit beendet, ist nicht belegt. Dasselbe gilt für eine Einzelerlaubnis, auf die ein Widerruf ohne Stelle oder eine Ablehnung einer Tat folgt: Die Erlaubnis bleibt stehen, im Kandidaten wie im Original. Zwei SPS-Stellen ziehen in verschiedene Richtungen:
  - V65X Z. 1414: „Widerruf ohne Stelle beendet *eine* Erlaubnis (vorsichtige Richtung)“;
  - V65X: „Eine Antwort mit Stelle beantwortet nur Taten, die diese Stelle nennen“, und §34.3 (2_7master): „nur für das, was sie sagt“.
  Eine saubere Lösung hinge von der beantworteten Tat ab (`acts`/`actFactIds`). Diese wird heute **nicht** an Rust übergeben. Das ist eine Entscheidung für den User, kein Patch.
- ~~Ob ein `revoke` ohne Stelle eine *breite* Zustimmung beenden darf.~~ **Geklärt durch SPS V65X Z. 1414:** „ein Widerruf ohne Stelle beendet eine Erlaubnis weiterhin (vorsichtige Richtung)“. Kandidat = Original = SOLL. Jetzt Test `test_sps_v65x_revoke_without_part_ends_broad_permission`.

## Weiter offen (aus 04, unverändert)

1. Native Writer-, SQLite-, Neustart- und Folgeturn-Kette mit echtem V67 (benötigt V67-ZIP). C04 und B01–B04 dort grün nachweisen.
2. Schreibgrenze für Lifecycle-Einträge: Defekt jetzt belegt (Stufe F), Patchplan siehe oben. Benötigt V67-`kernel.py`.
3. Übrige Kernel-, Memory-, Erfahrungs-, Welt- und BrainContext-Kette nach AMASTER/SPS.
4. HTTP/Frontend über sichtbare Bedienung, V12-Abnahme. Erst danach Livetest.

## Reproduktion

```sh
python3 -B tools/run_chain_05.py      # Exit 0 = alle Stufen A–E grün
```
