# Stand 10: F1-Restbefunde und F2 (eigenständiges Handeln), gemessen über den echten Weg

**Weg:**
- START.py, HTTP-Routen wie `chat.$sessionId.tsx`, lokales Testmodell (Provider `custom`), echter Neustart.
- Kein echtes Modell.
- Werkzeuge: `tools/f1_rest_10.py`, `tools/f2_durchlauf_10.py`, Drehbücher `tools/drehbuch_*_10.json`.
- Belege: `evidence/messung_stage10/`.

## Schritt A: F1-Restbefunde (Paket 09, keine Änderung)
- **B4 Abklingen:** 6 Folgezüge, Neustart vor Zug 3, Johann bleibt anwesend.
  - Die Stärke des momentanen Gefühls sinkt je Zug ×0,75 (0,85 → 0,20). Das ist die SPS-Regel V62.7.
  - Stabil bleiben: Gefühl „Angst“ gegenüber Johann, Absicht „Abstand“, Schmerz 0,25, Furcht 0,5, Beziehung (Vertrauen 0,105, Furcht 0,79).
  - **Kein ROT-Beleg gegen AMASTER §42.** Die Folgen der Ursache bleiben, nur die momentane Intensität sinkt.
- **B3 neue Grenze aus Figurenrede:** Die Grenzlesung läuft (`GRENZE_CHECK`: umfang `jede_beruehrung`, geltung `offen`).
  - In der Vorlagewelt besteht schon seit Zug 0 eine Grenze für jeden Körperkontakt von Johann. Deshalb gibt es keinen neuen Lifecycle-Fact, und **B3 ist hier nicht unterscheidbar (UNKLAR)**.
  - Notiert: Der Plan führt `gilt_fuer: diese_tat`, die Prüfung liefert `umfang: jede_beruehrung`.
- **B1 doppelte Tat:** Die erste Bewertung sieht 3 Ereignisse (action, physical, Frage), die folgenden je 1. UNKLAR ohne echtes Modell.

## Schritt C: F2-Messung (Paket 09)
Ablauf wie die UI: Puppet-Schlag → Reaktion der Betroffenen → `autochat-gate` → Folgezug, dazu eine Gegenprobe mit einer anderen Figur → Neustart → erneutes Gate.

**Erste Bruchstelle:** Das Gate wählte Johann, der Folgezug mit Gustav lief trotzdem durch (prepare, formulate, commit je 200).

**Ursache:** Im prepare (`app.py`) übernimmt ein Zug mit `inputKind autochat` ohne `autoPick` den Sprecher des Clients. Geprüft werden nur Anwesenheit und Sprechfähigkeit. Die Sprecherwahl nach AMASTER §28 Schritt 16 liegt damit beim Browser.

## Schritt D: Reparatur (Ebene 10, nur `matrix_api/app.py`)
`autochat_sprecher(session, natives, bound, requested)`: Ein Zug ohne Nutzereingabe darf nur eine Figur sprechen lassen, die der Server aus gespeicherten Daten bestimmt.
- **gewählt:** dieselbe Funktion wie das Gate (`latest_event_stimulus` + `pick_speaker(autochat=True, affected_ids)`);
- **betroffen/adressiert:** vom zuletzt committeten Ereignis betroffen oder dessen gebundenes Ziel (die UI-Reaktion nach Puppet);
- **regie:** von einer gespeicherten Regie-Zeile mit genau dieser Anweisung angeordnet (`regie_order_for` / `directiveFor`).

Alles andere ergibt 409 `AUTOCHAT_SPRECHER_NICHT_GEWAEHLT`, und es wird nichts gespeichert.

Es gibt keine neue Route, Tabelle oder Schicht. Züge mit Nutzereingabe bleiben unverändert.

## Nachweis
| Prüfung | Stand 09 | Stand 10 |
|---|---|---|
| `f2_durchlauf_10.py` (7 Kriterien) | 5/7, Exit 2 (F2_4/F2_5 rot) | **7/7**, Exit 0 |
| `tests/test_f2_sprecher_10.py` | rot | grün (2/2) |

## Weiter ROT (nicht angefasst)
- Die Sprecherwahl nutzt weiter Wortlisten und Namenstreffer (`rank_speakers`).
- AutoChat stößt nur der Browser an.

Beides ist eigene Arbeit in K-05.

## Eigener Test aus Stand 08 auf Stand 10 zusätzlich rot (dokumentiert, nicht geändert)
`ARBEITSSTAND_08/tests/test_k02_wissen_08.py::test_3` füllte elf Züge mit `inputKind autochat` und fest vorgegebenen Sprechern (Johann/Gustav im Wechsel). Das ist genau der Pfad, den Stand 10 schließt. Gemessen: 409 `AUTOCHAT_SPRECHER_NICHT_GEWAEHLT`, der Server hatte Mara gewählt.

Das ist keine Produktregression, sondern eine veraltete Testannahme (wie P18/K-01). Der 08-Test bleibt unverändert.

Ins Paket kommt die Portierung `tests/test_k02_wissen_portiert_10.py`, mit allen Prüfaussagen unverändert:
- Die Füllzüge sind Eingaben der Bedienperson an Johann/Gustav.
- AutoChat-Züge mit Serverwahl taugen als Füller nicht: Mit der lokalen Synapse stoppt das Gate nach wenigen Zügen korrekt mit `repetition`.
