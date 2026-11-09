# AMASTER → IST → Rust: vollständiges Abschnittsregister (statisch)

**Kein Grün-Nachweis.** Die Zuordnung enthält Quellkandidaten, nicht ausgeführte End-to-End-Ketten.
Normative AMASTER und Matrix10 stimmen mit Kettenvertrag §0 überein; die vorhandene V67 ist IST, nicht SOLL.

- **70** AMASTER-Abschnitte inventarisiert, **35** explizite Invarianten aus AMASTER §68
- **24** Python-Module / **1059** Python-Funktionsdefinitionen (AST, inklusive geschachtelter)
- **123** deklarierte HTTP-Methodenrouten / **27** vorhandene UI-Routendateien
- **16** Achsen im V12-Pflichtkatalog, für dieses Produkt alle ungeprüft

## Wichtigste nicht portierte Gesamtketten

TurnOrchestrierung (§28, 23 Schritte), semantische Komponentenwirkung (§34), Gedächtnis/Witness (§38–41),
Runtime/Physical/Relationship (§42–45), God/Regie/Fate/AutoChat (§46–48), BrainContext/LLM (§49–51),
SQLite-Owner mit Writer/Reader (§63), Snapshot/Import und vollständige API-/UI-Bedienbarkeit (§54–65).

## Systematische Zuordnung

| AMASTER | Abschnitt | Python-IST-Kandidaten | Oberfläche-Kandidaten | Rust |
|---:|---|---|---|---|
| 1 | Systemidentität | matrix_api/kernel.py, matrix_api/repos.py | src/routes/index.tsx | NICHT_PORTIERT |
| 2 | Produktziel | matrix_api/kernel.py, matrix_api/repos.py | src/routes/index.tsx | NICHT_PORTIERT |
| 3 | Lokale Produktgrenze | matrix_api/kernel.py, matrix_api/repos.py | src/routes/index.tsx | NICHT_PORTIERT |
| 4 | Gesamtsystemfluss | matrix_api/kernel.py, matrix_api/repos.py | src/routes/index.tsx | NICHT_PORTIERT |
| 5 | Dokumentenrollen | matrix_api/kernel.py, matrix_api/repos.py | src/routes/index.tsx | NICHT_PORTIERT |
| 6 | Wahrheitshierarchie und Zuständigkeiten | matrix_api/kernel.py, matrix_api/repos.py | src/routes/index.tsx | TEILQUELLE_UNKOMPILIERT |
| 7 | Menschliche Figurenlinie | matrix_api/kernel.py, matrix_api/repos.py | src/routes/index.tsx | NICHT_PORTIERT |
| 8 | Userprofil | matrix_api/repos.py, matrix_api/isolation.py | src/routes/user.tsx | TEILQUELLE_UNKOMPILIERT |
| 9 | Weltmodell | matrix_api/repos.py, matrix_api/analyze.py | src/routes/welt.index.tsx, src/routes/welt.$worldId.tsx | NICHT_PORTIERT |
| 10 | Welterstellung | matrix_api/repos.py, matrix_api/analyze.py | src/routes/welt.index.tsx, src/routes/welt.$worldId.tsx | NICHT_PORTIERT |
| 11 | Weltanalyse | matrix_api/repos.py, matrix_api/analyze.py | src/routes/welt.index.tsx, src/routes/welt.$worldId.tsx | NICHT_PORTIERT |
| 12 | Weltseite | matrix_api/repos.py, matrix_api/analyze.py | src/routes/welt.index.tsx, src/routes/welt.$worldId.tsx | NICHT_PORTIERT |
| 13 | Charaktererstellung und Spawning | matrix_api/repos.py, matrix_api/kernel.py | src/routes/charakter.index.tsx, src/routes/charakter.$charId.tsx | NICHT_PORTIERT |
| 14 | Charakterstamm | matrix_api/repos.py, matrix_api/kernel.py | src/routes/charakter.index.tsx, src/routes/charakter.$charId.tsx | NICHT_PORTIERT |
| 15 | Charakterprofil und Chathere-Kompass | matrix_api/repos.py, matrix_api/kernel.py | src/routes/charakter.index.tsx, src/routes/charakter.$charId.tsx | NICHT_PORTIERT |
| 16 | SceneBehaviorEngine | matrix_api/repos.py, matrix_api/kernel.py | src/routes/charakter.index.tsx, src/routes/charakter.$charId.tsx | NICHT_PORTIERT |
| 17 | Charakterseite | matrix_api/repos.py, matrix_api/kernel.py | src/routes/charakter.index.tsx, src/routes/charakter.$charId.tsx | NICHT_PORTIERT |
| 18 | Sessions | matrix_api/repos.py, matrix_api/scene_state.py | src/routes/chat.index.tsx, src/routes/timeline.tsx | TEILQUELLE_UNKOMPILIERT |
| 19 | Sessionverwaltung | matrix_api/repos.py, matrix_api/scene_state.py | src/routes/chat.index.tsx, src/routes/timeline.tsx | NICHT_PORTIERT |
| 20 | Szene und SceneState | matrix_api/repos.py, matrix_api/scene_state.py | src/routes/chat.index.tsx, src/routes/timeline.tsx | NICHT_PORTIERT |
| 21 | Timeline | matrix_api/repos.py, matrix_api/scene_state.py | src/routes/chat.index.tsx, src/routes/timeline.tsx | NICHT_PORTIERT |
| 22 | Chat und Turn | matrix_api/app.py, matrix_api/kernel.py, matrix_api/truth.py | src/routes/chat.$sessionId.tsx | NICHT_PORTIERT |
| 23 | TurnTruth und Eingangsbindung | matrix_api/app.py, matrix_api/kernel.py, matrix_api/truth.py | src/routes/chat.$sessionId.tsx | TEILQUELLE_UNKOMPILIERT |
| 24 | Eingabenormalisierung | matrix_api/app.py, matrix_api/kernel.py, matrix_api/truth.py | src/routes/chat.$sessionId.tsx | NICHT_PORTIERT |
| 25 | Sprecher- und Zielbindung | matrix_api/app.py, matrix_api/kernel.py, matrix_api/truth.py | src/routes/chat.$sessionId.tsx | NICHT_PORTIERT |
| 26 | Anwesenheit, Hören und Sehen | matrix_api/app.py, matrix_api/kernel.py, matrix_api/truth.py | src/routes/chat.$sessionId.tsx | TEILQUELLE_UNKOMPILIERT |
| 27 | Rollen und Modi | matrix_api/app.py, matrix_api/kernel.py, matrix_api/truth.py | src/routes/chat.$sessionId.tsx | NICHT_PORTIERT |
| 28 | Sprecherwahl und Orchestrierung | matrix_api/app.py, matrix_api/kernel.py, matrix_api/truth.py | src/routes/chat.$sessionId.tsx | NICHT_PORTIERT |
| 29 | Uploadsystem | matrix_api/analyze.py, matrix_api/vector.py, matrix_api/repos.py | src/routes/upload.tsx | NICHT_PORTIERT |
| 30 | Upload Mode A — prägend und bindend | matrix_api/analyze.py, matrix_api/vector.py, matrix_api/repos.py | src/routes/upload.tsx | NICHT_PORTIERT |
| 31 | Upload Mode B — Wissen, Beobachtung und Referenz | matrix_api/analyze.py, matrix_api/vector.py, matrix_api/repos.py | src/routes/upload.tsx | NICHT_PORTIERT |
| 32 | Dokument-, OCR- und Knowledge-Base-Schicht | matrix_api/analyze.py, matrix_api/vector.py, matrix_api/repos.py | src/routes/upload.tsx | NICHT_PORTIERT |
| 33 | Semantik-, Graph- und Vektorsuche | matrix_api/analyze.py, matrix_api/vector.py, matrix_api/repos.py | src/routes/upload.tsx | NICHT_PORTIERT |
| 34 | SceneFact und Commit | matrix_api/repos.py, matrix_api/kernel.py, matrix_api/scene_state.py | src/routes/chat.$sessionId.tsx, src/routes/timeline.tsx | TEILQUELLE_UNKOMPILIERT |
| 35 | Proposition, Goal und Lifecycle | matrix_api/repos.py, matrix_api/kernel.py, matrix_api/scene_state.py | src/routes/chat.$sessionId.tsx, src/routes/timeline.tsx | TEILQUELLE_UNKOMPILIERT |
| 36 | Request, Refusal, Acceptance und Commitment | matrix_api/repos.py, matrix_api/kernel.py, matrix_api/scene_state.py | src/routes/chat.$sessionId.tsx, src/routes/timeline.tsx | TEILQUELLE_UNKOMPILIERT |
| 37 | Zeit und Termine | matrix_api/kernel.py, matrix_api/scene_state.py | src/routes/chat.$sessionId.tsx | NICHT_PORTIERT |
| 38 | Memory | matrix_api/conjunctive.py, matrix_api/kernel.py, matrix_api/repos.py | src/routes/memory.tsx | NICHT_PORTIERT |
| 39 | WitnessKnowledge | matrix_api/conjunctive.py, matrix_api/kernel.py, matrix_api/repos.py | src/routes/memory.tsx | TEILQUELLE_UNKOMPILIERT |
| 40 | Konjunktives Gedächtnis und Pattern Completion | matrix_api/conjunctive.py, matrix_api/kernel.py, matrix_api/repos.py | src/routes/memory.tsx | NICHT_PORTIERT |
| 41 | Recall und Kontextaufbau | matrix_api/conjunctive.py, matrix_api/kernel.py, matrix_api/repos.py | src/routes/memory.tsx | NICHT_PORTIERT |
| 42 | RuntimeState und Emotion | matrix_api/kernel.py, matrix_api/scene_state.py | src/routes/charakter.$charId.tsx | NICHT_PORTIERT |
| 43 | PhysicalState und Capability | matrix_api/kernel.py, matrix_api/scene_state.py | src/routes/charakter.$charId.tsx | NICHT_PORTIERT |
| 44 | RelationshipState | matrix_api/kernel.py, matrix_api/repos.py | src/routes/social.tsx | TEILQUELLE_UNKOMPILIERT |
| 45 | Social und Synapsen | matrix_api/kernel.py, matrix_api/repos.py | src/routes/social.tsx | NICHT_PORTIERT |
| 46 | God und Regie | matrix_api/kernel.py, matrix_api/app.py, matrix_api/god_extract.py | src/routes/chat.$sessionId.tsx | TEILQUELLE_UNKOMPILIERT |
| 47 | Fate | matrix_api/kernel.py, matrix_api/system_loop.py | src/routes/fate.tsx | NICHT_PORTIERT |
| 48 | AutoChat | matrix_api/system_loop.py, matrix_api/pipeline.py | src/routes/chat.$sessionId.tsx | NICHT_PORTIERT |
| 49 | BrainContext | matrix_api/kernel.py, matrix_api/llm_contract.py | src/routes/chat.$sessionId.tsx | NICHT_PORTIERT |
| 50 | LLM-Grenze | matrix_api/llm_contract.py, matrix_api/pipeline.py | src/routes/config.tsx | NICHT_PORTIERT |
| 51 | Renderer, Narrator und Finalizer | matrix_api/local_render.py, matrix_api/kernel.py | src/routes/chat.$sessionId.tsx | NICHT_PORTIERT |
| 52 | Review und Stammübernahme | matrix_api/repos.py, matrix_api/analyze.py | src/routes/review.tsx | NICHT_PORTIERT |
| 53 | Profiler und gezielte Feldverbesserung | matrix_api/analyze.py, matrix_api/kernel.py | src/routes/charakter.$charId.tsx | NICHT_PORTIERT |
| 54 | Benutzeroberfläche | matrix_api/app.py | src/router.tsx | NICHT_PORTIERT |
| 55 | Startseite und Hauptmenü | matrix_api/app.py | src/routes/index.tsx | NICHT_PORTIERT |
| 56 | Chatoberfläche | matrix_api/app.py, matrix_api/kernel.py | src/routes/chat.$sessionId.tsx | NICHT_PORTIERT |
| 57 | Upload-Center | matrix_api/app.py, matrix_api/repos.py | src/routes/upload.tsx | NICHT_PORTIERT |
| 58 | Gedächtnis- und Wissensseite | matrix_api/kernel.py, matrix_api/repos.py | src/routes/memory.tsx | NICHT_PORTIERT |
| 59 | Beziehungs- und Socialseite | matrix_api/kernel.py, matrix_api/repos.py | src/routes/social.tsx | NICHT_PORTIERT |
| 60 | Konfiguration und API | matrix_api/app.py, matrix_api/repos.py | src/routes/config.tsx | NICHT_PORTIERT |
| 61 | Accessibility | matrix_api/app.py | src/routes/__root.tsx | NICHT_PORTIERT |
| 62 | STT und TTS | matrix_api/app.py, matrix_api/llm_contract.py | src/routes/chat.$sessionId.tsx | NICHT_PORTIERT |
| 63 | Persistenz und Datenhaltung | matrix_api/db.py, matrix_api/repos.py, matrix_api/schema.sql | src/routes/diagnose.tsx | NICHT_PORTIERT |
| 64 | Snapshots, Backup, Import und Export | matrix_api/repos.py, matrix_api/app.py | src/routes/admin.tsx, src/routes/diagnose.tsx | NICHT_PORTIERT |
| 65 | Diagnose, Logs und Nachvollziehbarkeit | matrix_api/live_log.py, matrix_api/app.py | src/routes/diagnose.tsx, src/routes/logs.tsx | NICHT_PORTIERT |
| 66 | Inhalts- und Genresteuerung | matrix_api/genre_policy.py, matrix_api/kernel.py | src/routes/config.tsx | NICHT_PORTIERT |
| 67 | Sicherheit | matrix_api/upload_security.py, matrix_api/isolation.py | src/routes/admin.tsx | NICHT_PORTIERT |
| 68 | Kanonische Invarianten | matrix_api/kernel.py, matrix_api/repos.py, matrix_api/app.py | src/router.tsx | TEILQUELLE_UNKOMPILIERT |
| 69 | Verbindliche Produktabnahme | matrix_api/kernel.py, matrix_api/repos.py, matrix_api/app.py | src/router.tsx | NICHT_PORTIERT |
| 70 | Verbindliche Kurzform | matrix_api/kernel.py, matrix_api/repos.py, matrix_api/app.py | src/router.tsx | NICHT_PORTIERT |

## Freigaberegel

Für alle 70 Abschnitte und alle 35 Invarianten fehlen die vollständigen Nachweise nach Kettenvertrag §16.
Bisherige Rust-Teilquelle, Python-Oracle, alte Tests, REST-Route oder UI-Datei zählen nicht als geschlossene Kette.
Native Kompilierung, Frontend-Anbindung, SQLite-Rücklesen, Folgeturn, Neustart, Isolation und V12-Produktabnahme
sind für eine Freigabe zwingend nachzuholen. Vorher **ROT / BLOCKIERT**.
