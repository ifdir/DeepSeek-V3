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
| `matrix_api/app.py` | **nur K2 + 06a/M2**: `NativeBoundaryError` → Rollback + 503 mit Code in `_run_write`, `_run_read`, Routen `prepare`/`commit`/`god`/`puppet`, ein `errorhandler`; `prepare` meldet einen Teilcommit zutreffend | `tools/build_overlay_app_06.py`, Patch `patches/app.py.P25_to_06.patch` |
| `src/lib/matrix/api.ts`, `src/routes/chat.index.tsx` | **nur 06a/M3** (Fehleranzeige) | `tools/build_overlay_frontend_06.py`, Patches `patches/*.P25_to_06.patch` |
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
2. ~~**`prepare`-Meldung bei Teilcommit:**~~ erledigt in 06a/M2. Die Eingabe wird *vor* dem Ausfall mit gültiger Rust-Entscheidung gespeichert (P25-Design „committed input stays valid“). Danach meldet die Route 503 „keine Speicherung freigegeben“. Die Meldung ist damit irreführend.
3. ~~**Chat-Liste im Ausfall:**~~ erledigt in 06a/M3. „Keine Session. Unten anlegen“ statt eines Fehlers. Das Banner nennt nur „503“, nicht den Code. Betrifft `chat.index.tsx`/`apiGetMcc` und bräuchte eine gesonderte Freigabe.
4. **P25-Altbefunde:** 24 rote Tests + 1 Sammelfehler, identisch in P25 und Stage 06.
5. V12, Modell-Folgeturn live: BLOCKIERT (siehe FEHLT).

## 6. Gesamtlauf `tools/run_chain_06.py` – Ergebnis

**Exitcode 2 = Vertragsstatus ROT.** Ergebnis in `evidence/chain_06/result_06.json`. Die Teilprüfungen sind dort getrennt aufgeführt.

| Teilprüfung | Status | Inhalt |
| --- | --- | --- |
| 0 Integrität | PASS | P25-ZIP-Hash; nur `scene_state.py` und `app.py` ersetzt (Originalhashes geprüft) |
| A fail-closed ohne Bibliothek | PASS | 3/3 Reader → `NativeBoundaryError` 503, keine Entscheidung |
| B cargo test | PASS | 86/86 |
| C Build + K1 | PASS | ABI-3-Vertrag 6/6, ABI-2-Gegenprobe |
| D Einwilligungskette Stage 06 | PASS | 9/10; nur W2 ROT |
| D2 Differenz zu P25 | PASS | 6 repariert, 0 verschlechtert |
| D3 HTTP 503 | PASS | 12 Routen × 3 Varianten |
| D3 K2a | PASS | 84 Ausfallpunkte, **0 fail-open**, 24 Teilcommits *vor* Ausfall (prepare); 5 Stellen belegt, 2 BLOCKIERT |
| D3F Frontend | PASS | Fehlerbanner sichtbar, keine Erfolgsanzeige |
| **E Gegenprobe** | **ROT** | 4/5 Mutationen erkannt. **Nicht erkannt: „Rust ohne Sprecherbindung“**, siehe unten |
| F P25-Testsuite | PASS | P25 und Stage 06 identisch (422 pass, 24 failure, 1 error) |
| G Prüfmaschine V12 | BLOCKIERT | Original-DB, Modellschlüssel und P23/P24-ZIPs fehlen |

**Zu E (Befund, nicht nachträglich umgedeutet):** Die Sprecherbindung liegt in Stand 06 in **drei** Schichten:
1. Python `lifecycle_bound`: Writer und `lifecycle_evidence`, neu mit Giver-Regel;
2. Rust `consent.rs::eligible`;
3. Python-Antwortprüfung `native_boundary._checked_index` (Index muss vom Giver stammen).

Ohne Schicht 2 erreicht in P25 kein fremder Eintrag Rust; über die Kette ist das nicht beobachtbar. Belegt ist die Rust-Regel durch die Rust-Unit-Tests (`different_speaker_cannot_undo_*`).

Kombinierte Gegenprobe (`evidence/chain_06/E_kombiniert_sprecherbindung.json`): Schicht 1 und 2 sind entfernt. Johanns Zustimmung wird geschrieben, Rust meldet sie als stehend, Schicht 3 weist mit `NATIVE_REPLY_INVALID` ab. Ergebnis fail-closed, kein „accepted“.

Bewertung: Teilprüfung E bleibt ROT. Entweder fängt eine künftige Gegenprobe Schicht 2 über einen Pfad ab, der Schicht 1 umgeht (es gibt in P25 keinen), oder die Schicht wird bewusst als Redundanz deklariert. **Das ist eine Entscheidung, keine stille Abschwächung.**

| Vertragspunkt | Status |
| --- | --- |
| C04 fremder Giver / abgelaufene Fenster | GRÜN |
| S05 Tat-Antwort hebt keine Grenze auf | GRÜN |
| W1/W3 Schreibgrenze Giver + Proposition | GRÜN |
| **W2 Actor = Sprecher der Quell-TurnTruth** | **ROT** |
| K1 ABI 3 | GRÜN |
| K2 HTTP 503 | GRÜN |
| K2 Frontend-Fehler sichtbar | GRÜN |
| K2a verschluckte Pfade | BLOCKIERT (2 Stellen ohne Kernaufruf in allen Szenarien) |
| **P25-Altbefunde Testsuite** | **ROT** |
| Modell-Folgeturn live, V12-Achsen | BLOCKIERT |
| Meldung Teilcommit `prepare`, Chat-Liste „Keine Session“ | OFFEN |

## 7. Nachtrag 06a – drei Entscheidungen des Nutzers (8.11.2026)

Alle drei Maßnahmen bleiben in der P25-Architektur: keine neue Route, keine zweite Zustandsverwaltung, keine neue Einwilligungsregel, keine verlorene Funktion. Gesamtlauf danach: **Exit 2 (ROT)**.

| Maßnahme | Umsetzung | Nachweis | Status |
| --- | --- | --- | --- |
| **M1** Rust-Sprecherbindung bleibt (Redundanz verbindlich) | keine Produktänderung | `cargo test` wird bei Entfernen der Rust-Bindung **rot** (5 Tests: `different_speaker_cannot_undo_broad_refusal`, `…_narrow_refusal`, `empty_actor_cannot_undo_narrow_refusal`, `narrow_permission_is_scoped_to_the_giver`, `s05_foreign_or_expired_answer_ends_nothing`); kombinierte Gegenprobe (Python- + Rust-Schicht entfernt) bleibt fail-closed | eigene Tests GRÜN, Kette fail-closed GRÜN; **Rust-only-Mutation über die Kette: weiter nicht erkannt, ROT, dokumentiert** |
| **M2** `prepare`-Meldung | `app.py`-Overlay: `last = "INPUT_COMMITTED"` nach TX1 (vorhandene Variable), Helfer `_prepare_teilcommit_antwort`; 503 meldet „Eingabe gespeichert. Die Antwort wurde nicht vorbereitet …“ mit `eingabeGespeichert`/`antwortVorbereitet`/`sourceTurnId`, sonst ausdrücklich `eingabeGespeichert: false` | Fehlerinjektion: 42 `prepare`-Ausfallpunkte, Meldung == SQLite-Befund in allen; 84 Ausfallpunkte gesamt, 0 fail-open | GRÜN |
| **M3** Chat-Liste | `api.ts` (`apiGetMcc` liest Code und Meldung); `chat.index.tsx` („Keine Session“ nur nach erfolgreicher Abfrage mit leerer Liste, sonst `role=alert` mit Code; Startleser-Fehler statt „Lädt…“) | gebaute UI im Chromium: ohne `.so` / ABI 2 nach Nutzerwahl **und** nach Neuladen Fehler mit `NATIVE_BOUNDARY_UNAVAILABLE` / `NATIVE_ABI_MISMATCH`, keine Leer- oder Lademeldung; mit Rust Liste sichtbar; Nutzer ohne Session → „Keine Session“; TypeScript-Fehlermenge identisch (606) | GRÜN |

**AMASTER-Prüfung zu M2:** Die Speicherung der Eingabe vor der Antwortvorbereitung ist zulässig, Atomarität wird nicht verlangt. Belege:
- §4 Gesamtfluss: Fakten schreiben vor dem BrainContext;
- §28 Schritt 20;
- §34.1: Das Scheitern einer Komponente vernichtet keine gültige andere;
- P25 hat den Zustand „offene Eingabe“ (V65U).

Die Transaktionsgrenze bleibt deshalb. Die Einwilligung der Eingabe-Handlungen wird **in** TX1 mit funktionierendem Kern entschieden; nicht abgeschlossen sind nur die Wahrnehmungsbewertung und die Antwortvorbereitung. Die Meldung sagt genau das.

**Regression:** Alle Stufen 0–F wurden erneut ausgeführt.
- P25-Suite: P25 und Stage 06 identisch (422/24/1).
- HTTP: mit Rust 12×200, im Ausfall 24/24 Antworten 503.

**Resthinweis (nicht in den freigegebenen Dateien):** Das Shell-Banner (`confirm-reset.ts`/`shell.tsx`) trägt beim Laden den Titel „Speichern fehlgeschlagen“. Es zeigt jetzt aber den Code.

**Weiter ROT:** W2, P25-Altbefunde, Rust-only-Mutation über die Kette. **BLOCKIERT:** V12, Modell-Folgeturn live, K2a-Stellen Z. 3959/1759.

## No-Touch (eingehalten)

Übrige P25-Kernel- und Writer-Logik, `act_consent`, Einwilligungsregeln ausserhalb der Rust-Reducer, Routen (keine neuen), Frontend ausser `api.ts`/`chat.index.tsx` (06a/M3), P25-Tests (keine Assertion geändert), Original-DB, `VERSION.txt`, Prüfmaschine V12.

## Reproduktion

```sh
python3 -B matrix10/ARBEITSSTAND_06/tools/run_chain_06.py      # Exitcode = Vertragsstatus (0/2/3)
```
