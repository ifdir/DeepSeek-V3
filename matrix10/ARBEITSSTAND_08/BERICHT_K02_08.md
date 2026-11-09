# Arbeitsstand 08 – K-02 Wahrnehmung → Wissen → Gedächtnis → Abruf → Entscheidung → Verhalten

**Status Gesamtprodukt: ROT.** Keine Produktfreigabe. **K-02 = TEILGESCHLOSSEN.** **K-01 = TEILGESCHLOSSEN.**
**Basis:** P25 + 06a + 07, frisch aus Git.
**Abnahme:** frischer Klon von `5b75c59`, `run_chain_08.py`, Exit 2. Belege in `evidence/chain_08/`.

## 1. Doku-Lage

- **Gelesen:**
  - AMASTERv2 §26 (Anwesenheit, Hören, Sehen), §28 (Schritte 5, 11, 19–21), §38 (Memory), §39 (WitnessKnowledge), §40 (Konjunktives Gedächtnis), §41 (Recall), §50, §51;
  - Matrix10 Nr. 11, 15, 16, 21;
  - Kettenvertrag §6 und §10;
  - SPS V71 (V60 Wahrnehmung aus der SQL-Szene, V65U Wiederaufnahme der offenen Eingabe).
- **Fehlt:** Provider-Schlüssel, Original-DB, Test-EPUB. Alles mit echtem Modell ist **BLOCKIERT**.

## 2. Vorhandene Kette (Codefluss) und was davon schon funktionierte

| Glied | Owner (vorhanden, wiederverwendet) | Befund vor 08 |
|---|---|---|
| Wahrnehmung der Eingabe | `app._bind_scene_perception` → `kernel._scene_perception` (SQL-Szene, Position, `canHear`, Bewusstsein) | korrekt |
| Zuordnung / Wissensweg | `kernel.witness_access`, `_record_fact_witnesses` → `witness_knowledge` | korrekt für die Eingabe |
| Gedächtnis | `commit_turn` → `make_memory` (`gesagt`, `gehoert` mit Zuschreibung „X sagte: …“, `getan`, `gesehen`, `erlebt`) → `memories` | korrekt (Test 1 besteht schon an Stand 07) |
| Abruf der Figur | `kernel.recall` (Fakten nur bei heard/seen/affected/informed, eigene Erinnerungen) → `bind_formulation_spiegel` (Dialog nur mit `witnessedBy`) | korrekt |
| Entscheidung / Verhalten | Modell: Spiegel als Prompt (BLOCKIERT). Offline: `local_render` antwortet auf Fragen aus abgerufenen Erinnerungen. | offline korrekt |
| **Wahrnehmung der Antwort** | `commit_turn` Antwortphase | **ROT:** Wahrnehmung von der Eingabe-TurnTruth übernommen |
| **Frontend: Abruf prüfen** | Gedächtnisseite „Recall“ | **ROT:** zweiter Leser (`recall_patterns`, Wortüberlappung über alle Figuren, ohne Figur); was eine Figur weiß, war nicht prüfbar (KV §5) |

## 3. Erste falsche Stelle (Ausgangsnachweis)

**Erste falsche Stelle:** `kernel.commit_turn` in der Antwortphase.
- `truth = dict(stored_truth)` übernahm `present_ids`, `hears_ids` und `sees_ids` der **Eingabe**.
- `witness_access`, die Gedächtnis-Writer und `witnessedBy` (damit der Dialogspiegel) lasen diese Werte.

**Ausgangsnachweis an Stand 07 über die echten Produktrouten:**
1. Eingabe an Johann, Mara und Gustav hören zu.
2. Gustav verlässt über „Anwesend“ die Szene.
3. „Antwort erneut erzeugen“: `prepare` als Wiederaufnahme, `formulate`, `commit`.

Ergebnis an Stand 07:
- Gustav steht mit `heard` in der WitnessKnowledge zur Antwort.
- Er hat die Erinnerung „gehört“ an die Antwort.
- Er sieht die Antwort im Dialogspiegel.

Belege: `chain_08/AUS2_stage07.json`, `chain_08/AUS2_stage08.json`.

## 4. Änderung (Diffs in `patches/*.07_to_08.patch`)

| Datei | Änderung | AMASTER / KV | wiederverwendet |
|---|---|---|---|
| `kernel.py` | Antwortphase: Wahrnehmung zum **Antwortzeitpunkt** aus dem SceneState. Die gespeicherte Eingabe-TurnTruth bleibt unverändert (Historie). | §26, §39, §28 Schritt 5 | `_scene_perception` (derselbe Owner wie `prepare`) |
| `app.py` | `/api/sessions/<id>/recall` mit `characterId` liefert `kernel.recall` (Figur muss zur Welt der Session gehören, sonst 422). Ohne Figur bleibt der Cache unverändert. | §41; KV §5 | vorhandene Route, vorhandener Leser |
| `api.ts`, `memory.tsx` | Gedächtnisseite: Mit gewählter Figur zeigt „Recall“ den kanonischen Abruf dieser Figur. Der Cache ist als „abgeleitet, kein Kanon“ gekennzeichnet. | KV §5 | vorhandene Figurenauswahl |

Kein neuer Speicher, keine neue Tabelle, keine neue Route, keine zweite Gedächtnislogik.

## 5. Abnahme am frisch ausgecheckten Stand (`run_chain_08`, Klon `5b75c59`)

| Stufe | Ergebnis |
|---|---|
| K2T: `test_k02_wissen_08.py` | **4/4** |
| AUS2: dieselben Tests an Stand 07 | 3 rot, genau an den reparierten Stellen; 1 grün (Zuordnung war korrekt) |
| AUS2: Ausgangsprobe | Stand 07: Gustav hört die Antwort; Stand 08: nicht. Kontrolle: Mara hört sie. |
| MUT2: K-02-Mutationen | **2/2 erkannt** |
| MUT: K-01-Mutationen auf Stage 08 | 11/11 erkannt |
| **LIVE2** (`START.py`, gebautes Frontend, Chromium, echter Neustart) | **10/10** |
| LIVE (K-01/SEC) | 14/14, unverändert |
| D: Einwilligungskette | 10/10 |
| D3 HTTP, K2a, D3F | PASS |
| F: P25-Suite | 421/25/1, einzige Abweichung der dokumentierte K-01-Test, keine neue |
| E | ROT (Rust-only-Mutation, unverändert) |
| G | BLOCKIERT |

**LIVE2-Kriterien:**
- Im Chat „Fall 06“ sendet die Bedienperson das Ereignis.
  - Mara und Gustav haben die Erinnerung `gehoert` mit Zuschreibung.
  - Robert war abwesend und hat kein Wissen.
- Nach einem **echten Neustart**: Die Gedächtnisseite (Session, Figur, „Recall“) zeigt Maras kanonischen Abruf mit der Kasse. Bei Robert steht „keine Erinnerung“. Abgerufen wurde über `kernel.recall`.
- Antwortphase live: Der gegangene Gustav hört die Antwort nicht, die anwesende Mara schon.
- Die fremde Session ist unverändert.

## 6. Prüffragen des Auftrags

| Frage | Ergebnis | Nachweisart |
|---|---|---|
| Wer hat was wahrgenommen, wer nicht? | Eingabe und Antwort jeweils zum eigenen Zeitpunkt; Abwesende und Gegangene ohne Wissen | Tests + live |
| Wissen, Vermutung, fremde Behauptung, eigene Erfahrung unterschieden? | **teilweise.** Unterschieden sind gesagt, gehört (mit Zuschreibung, keine Weltwahrheit), getan, gesehen und erlebt. **Es fehlen** geglaubt, vermutet, bestritten, unsicher und vergessen sowie Glaube oder Zweifel je Hörer. | Test 1 + live W3; Lücke ROT |
| Nur berechtigte Figuren und Sessions? | ja | Tests (Session B), live I1 |
| Nach Neustart erhalten? | ja | neue App-Instanz (Test 3) + echter `START.py`-Neustart (live) |
| Richtige, aktuelle Information beim Abruf? | ja für Wissen und Erinnerung. Offen: Der Abruf sortiert Propositionen nach gespeichertem statt reduziertem Status (nur Relevanz). | Test 3, live U1/U2 |
| Beeinflusst sie nachweisbar die Handlung? | **offline deterministisch ja.** Mara: „Ich erinnere mich: … Kasse …“, Robert: „Das weiß ich nicht.“, über die echten Routen mit lokaler Synapse. **Mit Modell BLOCKIERT.** | Test 3 |
| Bedienung im Frontend? | Chat, Anwesend, „Antwort erneut erzeugen“ und Gedächtnisseite mit Figurenabruf funktionieren live | LIVE2 |

## 7. Vertragsstatus nach Stand 08

| Punkt | Status |
|---|---|
| K02 Wahrnehmung (inkl. Antwortphase), offline deterministisch | **GRÜN** |
| K02 Figurenabruf im Frontend kanonisch | **GRÜN** |
| K02 Verhalten aus Erinnerung, offline (Synapse) | **GRÜN** |
| K02 Verhalten aus Erinnerung mit Modell | **BLOCKIERT** |
| K02 epistemische Zustände und Hörensagen | **ROT** (Writer fehlen) |
| **K02 gesamt** | **TEILGESCHLOSSEN** |
| K01 gesamt | TEILGESCHLOSSEN |
| P25-Suite: zusätzlich rot durch K-01 | **ROT** (dokumentierte Vertragsabweichung) |
| P25-Altbefunde, Rust-only-Mutation | ROT |
| **Gesamt** | **ROT, Exit 2** |

## 8. Offen und zugeordnet

- **Epistemische Zustände (Z-14), „später informiert“ (T-20), Glaube/Zweifel je Hörer (Z-17):** zugeordnet **K-03**.
  - Diese Writer brauchen eine Bedeutungslesung: welches Ereignis erzählt wird, ob die Figur glaubt oder zweifelt.
  - Sie wären ohne Modell nur als Wortliste möglich, und die schließt AMASTER §15/§16/§68 Nr. 21 aus.
- **Vertrauensgrad und Relationen zwischen Erinnerungen (Z-13, Z-18):** K-03. Ein Vertrauenswert ohne SOLL-Skala würde erfunden; dafür ist eine Entscheidung nötig.
- **Abruf mit gespeichertem statt reduziertem Propositionsstatus (Z-19):** gehört zu K-04 (Lifecycle-Owner).
- **§28 Schritt 19:** K-13.
