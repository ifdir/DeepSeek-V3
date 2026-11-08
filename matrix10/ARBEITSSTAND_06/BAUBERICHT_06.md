# Matrix10 – Arbeitsstand 06: Rust-Einwilligungskern auf Letztstand P25

**Stand:** 8. November 2026.
**Einordnung:** **Teilreparatur des P25-Einwilligungskerns**, keine vollständige Rust-Migration von Matrix10. Keine Produktfreigabe.
**Vertragsstatus gesamt:** siehe Abschnitt 6, Exitcode `run_chain_06.py`.

## GELESEN

- **Sollquellen (Kettenvertrag §0), vollständig:**
  - `AMASTERv2.md(1).txt` `fb4f2015…`
  - `Matrix10.txt` `1465980a…`
  - `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` `e62cf6bc…`
- **SPS als Lösungsreferenz:** V65S (Z. 2229), V65X (Z. 1390–1425), V60.5 (Z. 4149), V62.1 (Z. 4014), Bedienperson (Z. 967).
- **Produktbasis P25** `33a51497…` (aus `MATRIX10_FREIGABESPERRE_P25_V1_20261107-1.zip` `348f29dc…`). Gelesene Codepfade:
  - `scene_state.py`: Einwilligungsreader, `lifecycle_evidence`, `lifecycle_bound`, `act_consent`, `exception_verdict`;
  - `repos.py`: `append_session_fact`, `_check_fact_boundary`, `_check_lifecycle_actor`, `_check_fact_authority`, `patch_session_proposition`;
  - `kernel.py`: `apply_proposition` Z. 11985–12200, `_bind_lifecycle_evidence`, `_body_contact_answer`, `_body_contact_matter`, `reduce_current_state` Z. 1860–1890;
  - `app.py`: `_run_write`/`_run_read`, Kernel-Routen, verschluckende Handler;
  - Frontend: `src/lib/matrix/api.ts` (`apiJson`, `apiGetMcc`), `store.ts` (`setActiveUser`, `persistFailed`), `components/shell.tsx` (Fehlerbanner).
- **Rust-Ausgangspunkt:** Stand 05 (Commit `422d4b6`).
- Inputregister: `INPUTREGISTER_06.txt`.

## FEHLT

- Original-DB `e03dc445…` (für V12).
- Modell-/Providerschlüssel (Live-Folgeturn, V12 `--modell live`).
- Test-EPUB.
- P23/P24-ZIPs für die V12-Selbstabnahme.

---

## 1. Befund am unveränderten P25 (echte Writer → SQLite → Neuöffnen → Reader)

`tools/probe_p25_consent_06.py`, Ergebnis in `evidence/chain_06/S1_p25_original_probe.json` und `D2_p25_probe.json`: **3/10 Soll erfüllt.**
- Die Einwilligungsreader in P25 sind bytegleich mit V67.
- V70 `lifecycle_bound` hält nur Dritte ab.

| Fall | P25 IST | Soll (AMASTER) |
| --- | --- | --- |
| C04 fremder Giver (Johann „stimmt für Mara zu“) | geschrieben; `accepted`; Johanns Kuss `accepted` | abgewiesen; `declined` |
| C04 abgelaufene breite Zustimmung / Einzelablehnung / Einzelzustimmung | Grenze bzw. Erlaubnis verloren | bleibt (§35, Fenster je Ereignis) |
| S05 Widerruf der Ausnahme an einer Hand-Tat | Hand danach **`accepted`**, Kuss `unknown` | beide `declined` (§68.35, SPS V65X) |
| W2 Actor ≠ Sprecher der Quell-TurnTruth | geschrieben | abweisen (§34.1) |
| W3 Körperkontakt-Antwort ohne Proposition | geschrieben | abweisen (§35) |

## 2. Reparatur (Overlay auf P25, sonst bytegleich)

`tools/stage_source_06.py` prüft den P25-ZIP-Hash und die Originalhashes der zwei ersetzten Dateien. Ein bestehender Zielordner wird verweigert.

| Datei | Änderung | Erzeugung |
| --- | --- | --- |
| `matrix_api/scene_state.py` | Drei Reader + `names_restriction`/`same_restriction` über Rust (aus 05). `body_contact_entries` liefert zusätzlich `actTexts`/`actsBound`. `lifecycle_bound`: Körperkontakt-Antwort nur vom Giver; ohne `propositionId` ungebunden. | `tools/build_overlay_06.py`, Patch `patches/scene_state.py.P25_to_06.patch` |
| `matrix_api/app.py` | **nur K2**: `NativeBoundaryError` → Rollback + 503 mit Code in `_run_write`, `_run_read`, Routen `prepare`/`commit`/`god`/`puppet`, ein `errorhandler` | `tools/build_overlay_app_06.py`, Patch `patches/app.py.P25_to_06.patch` |
| `matrix_api/native_boundary.py` (neu) | FFI-Brücke ABI 3 (aus 05). `validate()` ist **nicht verdrahtet**: der P25-Python-Writer bleibt Owner. | Kopie |
| `native_core/matrix-boundary-core` (neu) | Rust-Crate aus 05 (ABI 3). `boundary.rs` ist im Crate, aber in 06 nicht verdrahtet. | Kopie |

**Kernel-Beleg für die Giver-Regel:** `kernel.apply_proposition` schreibt Körperkontakt-Antworten nur vom Berührten („only the giver … accepts, refuses or revokes“). Die Regel bricht also keinen gültigen Kernel-Write. Belegt durch Stufe F: 0 Abweichungen.

**W2 bewusst nicht gepatcht:** `_bind_lifecycle_evidence` bindet ohne `fact_id` positionell die letzte Rede *von oder an* den Antwortenden. Die Quell-TurnTruth kann deshalb die des Berührenden sein. Eine Regel „Actor = Sprecher“ würde gültige Writes abweisen. **W2 bleibt ROT/OFFEN.**

**route-safe: JA.** Kein neuer Store, keine neue Route, kein zweiter Owner. Die Entscheidung trifft Rust; Python transportiert und prüft die Antworten.

## 3. K1 – ABI 3 (Datenvertrag `ABI3_DATENVERTRAG_06.md`)

`tests/test_abi3_contract_06.py` gegen das Stage:
- Bibliothek meldet 3; jede Antwort `abi: 3`;
- fehlende ABI-3-Felder werden in Rust **und** Python abgewiesen;
- eine ABI-2-Bibliothek ergibt `NATIVE_ABI_MISMATCH`;
- P25-Einträge tragen die Felder für jede Eintragsart.

## 4. K2 / K2a – Fehlerkette Rust-Ausfall → API → Frontend

- **Vorher** (P25-`app.py`, ohne `.so` oder ABI 2):
  - `commit`, `prepare`, `puppet`, `god`, `autochat-gate`: 400;
  - `regie`, `presence`, `perception`, `move`, `fate`, `reset`: 500;
  - `GET /api/sessions`: 500 ohne Code.
  - SQLite blieb jeweils unverändert.
- **Nachher:** 24/24 Anfragen (12 Routen × 2 Ausfallvarianten) liefern **503** `NATIVE_BOUNDARY_UNAVAILABLE` bzw. `NATIVE_ABI_MISMATCH`. SQLite unverändert, keine Erfolgsmeldung, Grenze nachweislich erreicht (Zähl-Wrapper). Mit Rust unverändert 12×200.
- **K2a** (verschluckte Pfade):
  - AST-Inventar: 7 weiterlaufende Handler um Kernpfade.
  - Fehlerinjektion „Ausfall ab Aufruf k“ für **jede** Kernaufrufposition: 92 Ausfallpunkte in 8 Szenarien, **0 fail-open**. Nach Ausfallbeginn wird nichts geschrieben, und es gibt keine Erfolgsmeldung.
  - 5 Stellen sind einzeln belegt.
  - 2 Stellen sind **BLOCKIERT**: `_extract_user_plan` Z. 3959 und Zielthemen Z. 1759 erreichen den Kern auch mit Rust in keinem Szenario.
- **Frontend** (gebaute UI, `START.py`, Chromium):
  - Im Ausfall erscheint ein sichtbares `role="alert"`-Banner „Speichern fehlgeschlagen … 503“. Keine Erfolgsanzeige, SQLite unverändert.
  - Keine Frontend-Änderung nötig.

## 5. Offene Befunde (nicht gepatcht, brauchen Entscheidung)

1. **W2** – siehe oben.
2. **`prepare`-Meldung bei Teilcommit:** Die Eingabe wird *vor* dem Ausfall mit gültiger Rust-Entscheidung gespeichert (P25-Design „committed input stays valid“). Danach meldet die Route 503 „keine Speicherung freigegeben“. Die Meldung ist damit irreführend.
3. **Chat-Liste im Ausfall:** „Keine Session. Unten anlegen“ statt eines Fehlers. Das Banner nennt nur „503“, nicht den Code. Betrifft `chat.index.tsx`/`apiGetMcc` und bräuchte eine gesonderte Freigabe.
4. **P25-Altbefunde:** 24 rote Tests + 1 Sammelfehler, identisch in P25 und Stage 06.
5. V12, Modell-Folgeturn live: BLOCKIERT (siehe FEHLT).

## 6. Gesamtlauf `tools/run_chain_06.py`

_wird nach Abschluss des Laufs eingetragen_

## No-Touch (eingehalten)

Übrige P25-Kernel- und Writer-Logik, `act_consent`, Einwilligungsregeln ausserhalb der Rust-Reducer, Routen (keine neuen), Frontend, P25-Tests (keine Assertion geändert), Original-DB, `VERSION.txt`, Prüfmaschine V12.

## Reproduktion

```sh
python3 -B matrix10/ARBEITSSTAND_06/tools/run_chain_06.py      # Exitcode = Vertragsstatus (0/2/3)
```
