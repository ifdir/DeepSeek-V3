# ABI 3 – Datenvertrag Einwilligungskern (Arbeitsstand 06)

**Gilt für:** `overlay/native_core/matrix-boundary-core` (Rust, `ABI_VERSION = 3`) und `overlay/matrix_api/native_boundary.py` (`ABI = 3`). Python und Rust werden nur gemeinsam geändert.

**Warum ABI 3:** Stand 04 hatte ABI 2. In 06 hat jeder Einwilligungseintrag zwei neue Pflichtfelder (`actTexts`, `actsBound`), damit eine Antwort auf eine Tat nur für die gebundenen Taten wirkt (S05). Damit ist die Eintragsform nicht mehr kompatibel, und eine ABI-2-Bibliothek muss abgewiesen werden.

## Transport

- Ein Rahmen beginnt mit `MXRB\x01\x00`, danach folgen typisierte Werte (`native_boundary.encode`/`decode`).
- Die Antwort hat höchstens 64 KiB.
- `matrix_boundary_check(in, len, out, cap)` liefert die geschriebenen Bytes. `-1` steht für ungültige Zeiger oder Längen, `-2` für zu wenig Ausgabepuffer, `-3` für einen Codec-Fehler.
- `matrix_boundary_abi_version()` muss `3` liefern. Sonst gilt `NATIVE_ABI_MISMATCH`, und die Bibliothek wird nicht geladen.

## Anfrage (Einwilligungsreducer)

```
{operation: "body_contact_standing" | "restricted_refusals" | "restricted_permissions",
 context: {}, options: {},
 payload: {giver: <nichtleerer Text>, entries: [Eintrag, ...]}}
```

Ein Eintrag in kanonischer Reihenfolge (P25 `scene_state.body_contact_entries`, über `lifecycle_evidence`) hat diese Felder:

| Feld | Typ | Quelle in P25 | Pflicht |
| --- | --- | --- | --- |
| `by` | Text | `fact.actorId` | ja |
| `kind` | `acceptance` / `refusal` / `revoke` | `_KK_KIND[event_kind]` | ja |
| `scope` | `""` / `diese_tat` / `eingeschraenkt` / `jede_beruehrung` | `payload.koerperkontakt.scope` | ja |
| `einschraenkung` | Text (`""` = keine) | `koerperkontakt.einschraenkung` bei Scope `eingeschraenkt` | ja |
| `einschraenkungOffen` | Text (`""` = keine) | `koerperkontakt.einschraenkung` bei einem anderen Scope (unbestätigt) | ja |
| `active` | Bool | `scene_state._in_window` (Zeit/Szene) **je Ereignis** | ja |
| `actTexts` | Liste von Text | gespeicherte Texte der Taten in `koerperkontakt.actFactIds` (`kernel._body_contact_answer`) | ja (**neu ABI 3**) |
| `actsBound` | Bool | `true` nur, wenn `actFactIds` nicht leer ist **und** jede Tat in der Session existiert | ja (**neu ABI 3**) |

Fehlt ein Feld oder hat es einen falschen Typ, antwortet Rust mit `ok:false, code: NATIVE_CONTRACT_INVALID, status: 503`. Python wirft daraus `NativeBoundaryError`.

## Antworten

| Operation | Antwort bei `ok:true` (immer mit `abi: 3`) |
| --- | --- |
| `restricted_refusals` | `indices`: aufsteigende, eindeutige Eintragsindizes (nur Giver, aktiv, `eingeschraenkt`/`refusal`) |
| `restricted_permissions` | `indices`: ebenso (nur `eingeschraenkt`/`acceptance`) |
| `body_contact_standing` | `standing`: Index einer breiten Antwort oder `null`; `ended`: `[von, bis]` oder `null`; `exceptions`: `[{index, kind}]` |
| `restriction_match` | `match`: Bool |

Python (`native_boundary._checked_index` u. a.) prüft jeden Index gegen den echten Eintrag: Giver, aktiv, Art und Scope. Ein Widerspruch ergibt `NATIVE_REPLY_INVALID` und keine Entscheidung.

## Fachregeln (Rust `consent.rs`)

- Nur Einträge, die vom Giver stammen und aktiv sind, wirken (C04).
- Eine Antwort `diese_tat` vom Typ `refusal` oder `revoke` wirkt nur für die gebundenen Taten und nur in die vorsichtige Richtung (S05). Belege: AMASTER §68.35/§35/§36.3, SPS V65X Z. 1414.
  - Sie beendet eine breite Zustimmung.
  - Sie hebt eine breite Ablehnung **nie** auf. Sie beendet nur die Ausnahme-Erlaubnisse, deren Stelle eine gebundene Tat nennt.
  - Sie beendet eine eigenständige Einzelerlaubnis nur, wenn eine gebundene Tat deren Stelle nennt.
  - Ist sie an keine Tat gebunden (`actsBound = false`), wirkt sie vorsichtig und beendet alle Erlaubnisse.

## Fehlerkette

`NativeBoundaryError(code, status=503)` → Reader → API. Wie der Fehler an der HTTP-Grenze und im Frontend ankommt, ist **nicht** Teil dieses Vertrags. Das prüft `run_chain_06.py`, Stufe D3 (Plan K2).
