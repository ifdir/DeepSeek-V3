# Matrix10 – Rust-Arbeitsstand 05 (Nachtrag auf 04)

**Stand:** 7. November 2026. **Gesamtstatus: ROT, keine Produktfreigabe.**
**Teilstatus der Consent-Reader-Kette (Reader → FFI → Rust → Projektion): TEILGRÜN.**

## GELESEN / GEPRÜFT

- Paket 04: SHA-256 `04b870cb…ca66b`, ZIP-Integrität PASS, alle Einträge aus `SHA256SUMS.txt` stimmen.
- `BAUBERICHT_04.md`, `README.md`, `RUST_MIGRATION_STATUS.json`, Paketprüfung 04.
- Code: `integration/scene_state.py` (Reader), `integration/native_boundary.py` (FFI), `src/consent.rs`.
- AMASTER §36.4 (Bruch/Widerruf) nur punktuell per Suche, **nicht vollständig gelesen**.

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

3. **Gesamtkette 05** (`tests/test_consent_native_chain_05.py`) prüft ohne Mock:
   - **Zeitleiste mit 15 Ereignissen.** Nach **jedem** Ereignis werden **alle drei Reader gemeinsam** abgefragt (`body_contact_standing`, `restricted_permissions_standing`, `restricted_refusals_standing`). Die Ereignisse enthalten fremde und leere Sprecher, abgelaufene und gültige Zeitfenster, andere Stimme („meine rechte Hand“), Widerruf und mehr als 6 Ereignisse.
   - **Kreuz-Invarianten:** Kein Körperteil ist gleichzeitig erlaubt und abgelehnt. Zustand und Ausnahmen stammen nur vom Giver. Ausnahmen unter Ablehnung und Einzelerlaubnisse laufen nicht auseinander.
   - Unabhängigkeit von der Speicherreihenfolge, Fenstergrenzen (inklusiv, fehlender Zeitpunkt), Szenenfenster bei Ortswechsel, unbestätigter Teil, Gegenseite, Kompositum („Handtasche“).
   - **Differenzlauf gegen Original-V67:** Der Original-Reader wird aus `patches/scene_state.py.patch` rückwärts rekonstruiert. Sein SHA-256 `2d3c0dfa…17fe` muss dem V67-Wert entsprechen. Ergebnis: alle 4 C04-Fälle im Kandidaten SOLL und im Original rot. Die erste Abweichung in der Zeitleiste stammt von einem Ereignis der Defektklasse (fremder Sprecher oder abgelaufenes Fenster).
   - `matrix_api.ids` ist ein Stub, der **bei jedem Aufruf fehlschlägt**. Er beweist, dass die Reader keine IDs erzeugen. Er ist keine Nachbildung der V67-Datei.

Keine Änderung an Rust- oder Python-Produktcode. Neu sind nur ein Test, ein Werkzeug, Evidenz und dieser Bericht.

## UNKLAR (nicht entschieden, kein Patch)

- **Breite Zustimmung → Einzelerlaubnis → Widerruf (`revoke`, Scope `diese_tat`):** `body_contact_standing` meldet `revoked`. `restricted_permissions_standing` behält die Einzelerlaubnis aber bei, weil nur ein `jede_beruehrung`- oder ein gleichstelliger `eingeschraenkt`-Eintrag sie beendet. Ob ein Widerruf der breiten Zustimmung eine *vorher eigenständig* gegebene Einzelerlaubnis mit beendet, ist aus dem gelesenen AMASTER-Material nicht belegt. Für einen Patch muss §36.4 vollständig ausgelegt werden.
- Ob ein `revoke` mit Scope `diese_tat` überhaupt eine *breite* Zustimmung beenden darf (V67-Verhalten, im Kandidaten übernommen).

## Weiter offen (aus 04, unverändert)

1. Native Writer-, SQLite-, Neustart- und Folgeturn-Kette mit echtem V67 (benötigt V67-ZIP). C04 und B01–B04 dort grün nachweisen.
2. Semantische Schreibgrenze (Handlungsbindung, Körperstelle, Giver, Umfang, Zeit/Szene) beim **Writer**. Heute wird nur beim Lesen gefiltert. Falsch zugeschriebene Lifecycle-Einträge werden noch gespeichert.
3. Übrige Kernel-, Memory-, Erfahrungs-, Welt- und BrainContext-Kette nach AMASTER/SPS.
4. HTTP/Frontend über sichtbare Bedienung, V12-Abnahme. Erst danach Livetest.

## Reproduktion

```sh
python3 -B tools/run_chain_05.py      # Exit 0 = alle Stufen A–E grün
```
