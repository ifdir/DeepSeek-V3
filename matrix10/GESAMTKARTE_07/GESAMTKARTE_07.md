# Matrix10 – Gesamtkarte 07: AMASTER-SOLL / IST / Abhängigkeiten des P25-/Rust-Systems

**Stand:** 08.11.2026 · **Status Gesamtprodukt: ROT** · keine Produktfreigabe · keine Produktdatei geändert.
**Code-Basis:** P25 (`MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107.zip`, SHA-256 `33a51497…60d1`) + Overlay Arbeitsstand 06a, Commit `1b56e13`, frisch entpackt mit `ARBEITSSTAND_06/tools/stage_source_06.py`.

## 0. Doku-Lage

**GELESEN**
- **AMASTERv2** `fb4f2015…`
  - selbst gelesen: §1–§6, §68–§70;
  - die Bereichsprüfer haben ihre Abschnitte §7–§67 jeweils vollständig gelesen.
- **Matrix10.txt** `1465980a…`: vollständig selbst gelesen.
- **Reparatur-Kettenvertrag** `e62cf6bc…`: §0–§20 selbst gelesen.
- **SPS-Blatt:**
  - verwendet wird das Blatt im P25-Produkt, Stand V71, SHA-256 `1f0cb05d…`, 7293 Zeilen;
  - das Blatt in `sources/` ist älter: Stand V67, SHA-256 `6c1747bb…`, 6006 Zeilen;
  - zitiert sind die zutreffenden Deckblätter V65F, V65U, V65Z und V70.
- **P25-Unterlagen:** `P25_PRUEFBERICHT.md`, `README.md`, `ABNAHMEMATRIX_20_PUNKTE.txt`.
- **Code (statisch):** `matrix_api/*.py` mit 39 969 Zeilen, Rust-Kern, `src/routes/*.tsx`, `src/lib/matrix/*.ts`.

**FEHLT / BLOCKIERT**
- Original-DB `e03dc445…`.
- Modell-Provider-Schlüssel.
- Test-EPUB `Swift_Die-mustergueltige-Ehefrau…epub` (`32cf5c85…`, Kettenvertrag §7).
- P23- und P24-ZIPs.

Jede Kette, die ein echtes Modell oder das Buch braucht, ist deshalb **BLOCKIERT**. Offline-Proben ersetzen das nicht.

**Methode** (Kettenvertrag §2, §6.3)
1. **Codefluss je Funktion:** Fünf Bereichsprüfer haben je Funktion die Kette Eingang → Verarbeitung → Speicherung → Wiederlesen → Entscheidung → Folgewirkung → Frontend mit `datei:zeile` gelesen.
2. **Ausgeführte Proben:** Flask-Testclient auf Temp-SQLite, Provider `synapse` (lokal), Skripte in `belege/proben/`.
3. **Live-Probe am echten Startweg:** `START.py` als echter Prozess mit gebautem `frontend_dist`, Neustart dazwischen, SQLite read-only gelesen (`tools/live_turntruth_07.py`, Beleg `belege/live/L_turntruth_07.json`).
4. **Gegenprüfung:** Die schwersten Befunde (Z-22, T-13, W-Wortliste, formulate→commit) habe ich im Code selbst nachgeprüft.

Kein Eintrag ist GRÜN, weil keine Funktion live mit Modell, UI, Folgeturn und Isolation abgenommen ist.

## 1. Sicherung Arbeitsstand 06a (Auftrag Punkt 1)

Die Nachprüfung des **gepushten** Codes am frischen Klon ergab einen Fehler meiner früheren Meldung:

| Commit | Ergebnis | Ursache |
|---|---|---|
| `81eb6a5` (gemeldet als 06a fertig) | Gesamtlauf Exit 2; **M3 ROT**: Fehlermeldung „GET /api/mcc 503“ **ohne Code** | `.gitignore`-Regel `lib/` hat `overlay/src/lib/matrix/api.ts` nie committet. Mein Lauf am Arbeitsbaum war grün, der gepushte Stand nicht. Die frühere GRÜN-Meldung für M3 war damit **falsch**. |
| `1b56e13` (Korrektur) | Gesamtlauf Exit 2 = ROT wie vertraglich erwartet; **M3 GRÜN** (6 von 6 Kriterien im Browser); M1, M2, K1, K2, C04, S05, W1/W3 GRÜN | Die fehlende Datei ist nachgereicht. `stage_source_06.py` bricht jetzt mit Exit 2 ab, wenn eine ersetzte Datei im Overlay fehlt; das habe ich am alten Stand negativ geprüft. |

Belege: `belege/nachpruefung_06a/`.

Unverändert offen und ausdrücklich dokumentiert:
- **ROT:** W2; die P25-Altbefunde; die Rust-only-Mutation, die die Gesamtkette nicht erkennt.
- **BLOCKIERT:** K2a (2 Stellen), Modell-Folgeturn, V12.

## A. SOLL-/IST-/Abhängigkeitskarte

Die vollständige Karte liegt in `KARTE_GESAMT_07.md` (Tabelle) und `KARTE_GESAMT_07.json` (alle Felder je Funktion). Je Funktion enthält sie:
- AMASTER-Stelle, SOLL und Kettenvertragsbezug;
- die SPS-Lösung, den Owner im IST und den Owner nach Architektur;
- die Kette Eingang, Verarbeitung, Speicherung, Wiederlesen, Entscheidung, Folgewirkung und Frontend, jeweils mit `datei:zeile`;
- UI-Bedienung, Status, Defekte, Abhängigkeiten, Auswirkung und Belege.

Die Teilkarten liegen in `karte/{W,T,Z,A,P}.json`. Darin steht auch die Frontend-Backend-Matrix über alle 124 Routen (`P-MATRIX`).

| Bereich | AMASTER | Funktionen | ROT | TEILGESCHLOSSEN | UNGEPRÜFT | BLOCKIERT | GRÜN |
|---|---|---:|---:|---:|---:|---:|---:|
| W Welt, Userprofil, Charakterstamm | §7–§17, KV §7–§8 | 32 | 16 | 12 | 4 | 0 | 0 |
| T Session, Szene, Turn, TurnTruth, Orchestrierung (inkl. der 23 Schritte aus §28 und W2) | §18–§28, KV §9 | 53 | 20 | 30 | 3 | 0 | 0 |
| Z Fakt, Lifecycle, Memory, Witness, Runtime, Beziehung | §34–§45, KV §10–§11 | 30 | 6 | 19 | 2 | 3 | 0 |
| A God, Regie, Fate, AutoChat, BrainContext, LLM, Review | §46–§53, KV §12 | 34 | 19 | 13 | 2 | 0 | 0 |
| P Upload, Suche, UI, Config, Persistenz, Diagnose | §29–§33, §54–§67, KV §5, §13–§15 | 34 | 24 | 9 | 0 | 1 | 0 |
| **Summe** | | **183** | **85** | **83** | **11** | **4** | **0** |

**Codefluss (statisch, keine Abnahme):** 54 Ketten sind im Code geschlossen. 104 haben eine Lücke, bei 10 fehlt die Implementierung, 15 sind UNKLAR.

**Frontend-Backend-Matrix (Kettenvertrag §5):** Von 124 Routen sind 90 mit Aufruf und sichtbarer Kontrolle verbunden.
- 18 haben keinen Frontendaufruf, 7 keine sichtbare Kontrolle.
- 3 werden nur aus `matrix_speicher_v91.html` aufgerufen.
- 2 haben einen Frontendaufruf ohne Backendwirkung (Sprach-Stubs).
- 14 Frontendfelder haben keine oder eine falsche Backendwirkung.

**Zuständigkeit Python/Rust (Architekturvertrag):** Rust ist nach dem beschlossenen Stand nur für die Einwilligungsreducer zuständig (ABI 3). Alle übrigen Owner sind Python (P25) und bleiben es. Die Karte fand **keine** Funktion, deren Defekt durch eine Verlagerung nach Rust entstünde oder behoben würde. Die Fehler liegen in der Bindung, im Owner und im Leser, nicht in der Sprache.

## B. Priorisierte Liste der Gesamtfunktionsketten

Die Reihenfolge richtet sich danach, welche Kette Voraussetzung für andere ist (Kettenvertrag §6.5: früheste falsche Naht zuerst). „Live“ bedeutet echter Prozess `START.py`.

| Prio | Gesamtkette | AMASTER / KV | Status | Wichtigste belegte Defekte | Frontend-Anbindung | Voraussetzung für |
|---:|---|---|---|---|---|---|
| **1** | **K-01 Serverseitige TurnTruth und Commit-Bindung**: wer spricht, wer handelt, was wird committet | §23, §25, §27, §28 Schritte 8/16/18–20, §50; KV §4, §9, §12.2 | **ROT** | (a) Den Eingabe-Actor übernimmt der Server ungeprüft vom Client (`app.py:1579` `bound=dict(raw)`, `kernel.py:1002–1004`). **Live L1**: Die Bedienperson ohne Avatar und ohne Puppet sendet `inputActorId=Mara`, gespeichert wird ein Rede-Fact mit Actor Mara. (b) Der Commit übernimmt `result` und `fired` aus dem Request-Body (`app.py:1987`, `:1991`); `/api/llm/formulate` ist zustandslos (`llm_contract.py:2844`). **Live L2/L3**: Eine nie vom Server formulierte Figurenrede wird als Rede Johanns committet und ist nach dem Neustart über HTTP und in SQLite vorhanden. (c) Der Sprecher wird im Browser gewählt (`chat.$sessionId.tsx:887–941`); der Server prüft nur die Anwesenheit (`app.py:1663`). (d) `scene_id`, `time_ref` und `upload_ref` kommen vom Client (`kernel.py:12632–12634`). (e) Die Hörerliste fällt von `hearsIds` leer auf alle Anwesenden zurück (`kernel.py:8688`, `8978`, `12542`). (f) Schritt 19, die Prüfung der Ausgabe, fehlt (`llm_contract.py:2276`). (g) W2: Die positionale Lifecycle-Bindung prüft nicht den Actor des `responds_to`-Facts (`kernel.py:11895`). | Chat: Eingabe, Zielwahl, „Figuren weiterreden lassen“; `kernel-bridge.ts:165/253`, `chat.$sessionId.tsx:443/606` | **alle** Writer: Fakt, Witness, Memory, Lifecycle, Einwilligung, Runtime, Beziehung, Mode B, Avatar-Grenze, AutoChat |
| 2 | K-02 Wahrnehmung → Witness → Memory → Recall (Erfahrung speichern und wiederverwenden) | §26, §38–§41; KV §10 | TEILGESCHLOSSEN | Lokal geschlossen: Ereignis → Witness → Memory → SQLite → Recall im Folgeturn → neue App-Instanz (Z-Probe), Persistenz nach echtem Neustart (live L3). Defekte: Für geglaubt, bezweifelt, vergessen usw. gibt es keinen Writer (Z-14). Hörensagen ohne Bezug zum erzählten Ereignis (Z-15/17). Hörer-Fallback aus K-01. | Gedächtnisseite (memory.tsx), Zustandspanel | K-03, K-05, Mode B, Fate |
| 3 | K-03 Bedeutung von Erfahrung → Runtime, Ziel, Beziehung (psychologische Wirkung, Lernen in der Session) | §42–§45; Matrix10 Nr. 16–17; KV §10–§11 | ROT / BLOCKIERT | Der Appraisal-Writer läuft nur mit Provider (`llm_contract.py:1522`); ohne Provider ändert eine Erinnerung weder Emotion, Vertrauen noch Ziel (Z-Probe). `apply_knowledge_effect` leitet Runtime und Beziehung per Wortliste ab (`kernel.py:2432/2296`). Die Socialseite überschreibt Beziehungen ohne Ereignis (`repos.py:4848`). | Beziehungs- und Socialseite, Zustandspanel | K-05, Fate, Review |
| 4 | K-04 Proposition, Goal, Lifecycle, Einwilligung | §35–§37 | TEILGESCHLOSSEN | Die Einwilligungsreducer in Rust sind im Vertrag 06 GRÜN (C04, S05, W1/W3). Offen: zwei Lifecycle-Owner (`conjunctive.apply_plan` gegenüber `kernel.apply_proposition`, Z-04); Entscheidungsleser lesen den gespeicherten statt des reduzierten Status; Termine und `graph_edges` ohne Systemleser (Z-12, Z-28); W2 (siehe K-01). | Timeline, Ziele, Chat | K-05, Fate |
| 5 | K-05 Eigenständiges Handeln: Sprecherwahl, AutoChat, Fate | §28 Schritt 16, §47, §48; KV §12.5–§12.6 | ROT | Die Sprecherwahl nutzt Wortlisten (`_COMPASS_TRIGGERS` `kernel.py:13300` in `rank_speakers` `:11670`). AutoChat stößt nur der Browser an (`chat.$sessionId.tsx:967–1012`). Der Gate-Sprecher ist nicht an den Folgeturn gebunden. Fate liest den Seed nicht. Ein „harter Konflikt“ gilt nur bei „samstag/sonntag“ (`kernel.py:14901`). | AutoChat-Schalter, Kandidatenliste, Fate-Seite | Produktziel „selbstständig handelnde Figuren“ |
| 6 | K-06 God, Regie, Avatar, Puppet | §27, §46; KV §12.1–§12.4 | ROT | God wählt den Scope per Wortliste (`god_extract.py:25/101`) und schreibt Sessiontext ohne Review in den Stamm (`app.py:1432–1440`, ausgeführt). Der Weltkanon hat keinen Leser. Regie „setzt sich“ ändert den Körper nicht (R-1). `canBeAvatar` wird nie gelesen (W-05). | God/Regie-Panel im Chat | K-03, K-07 |
| 7 | K-07 Welt- und Charakterstamm → Verhalten (EPUB → spielbare Welt, Spawn) | §9–§17; KV §7–§8 | ROT (EPUB BLOCKIERT) | Viele Welt- und Charakterfelder haben keinen Turn-Leser (W-06). Der Welt-Commit besteht aus mehreren Requests ohne Transaktion und erzeugt Dubletten (`store.ts:695`, `normalize.ts:447`). Der Kompass wirkt als Wortlisten-Zustandsmaschine (gegen §15/§16). | Weltseite, Charakterseite, Spawn | K-05, Fate |
| 8 | K-08 Upload Mode A und Mode B | §29–§33; KV §13 | ROT | Mode B verteilt an alle Hörer und speichert den Hinweis statt des Inhalts (`pipeline.py:151–155`). Mode A ersetzt `long` durch die Kurzfassung (`pipeline.py:403`). Ein Fehler wird mit 200 und der Anzeige „committed“ beantwortet. | Upload-Center | K-02, K-07 |
| 9 | K-09 Konfiguration und Provider | §60; KV §14 | ROT / BLOCKIERT | **Der API-Key steht im Klartext in `GET /api/mcc`** (`repos.py:1444–1466`, ausgeführt). Die Scopes erben nicht; der Chat fällt still auf `synapse` zurück (`llm_contract.py:2445`). Live-Provider BLOCKIERT. | Konfigurationsseite | K-03, alle Live-Abnahmen |
| 10 | K-10 Review: Sessionerfahrung → Stamm | §52–§53; Matrix10 Nr. 23 | ROT / FEHLT | Kein Generator für Review-Vorschläge. `learning.py` hat keine Aufrufer (Z-27). Die Systemschleife nimmt alle Reviews automatisch an und verändert die Startwelt (`system_loop.py:179–226`, ausgeführt). `resolve_review` dupliziert einen Spawn. | Reviewseite, Diagnose „Systemschleife“ | dauerhafte Entwicklung |
| 11 | K-11 Reset, Snapshot, Persistenz, Isolation, Diagnose | §63–§65; KV §15 | TEILGESCHLOSSEN / ROT | Persistenz nach Neustart und Isolation der anderen Session hielten live (L3/L4). Die Systemschleife schreibt Testdaten in die Produkt-DB. Die Diagnose testet die Browser-Engine statt des Servers (`diagnose.tsx:31`). Falsche Erfolgsmeldungen. | Admin, Diagnose, Snapshots | Abnahmefähigkeit |
| 12 | K-12 UI-Abdeckung | §54–§62; KV §5 | ROT | 28 Routen ohne Aufruf oder Kontrolle, 14 Felder ohne Wirkung, zentrale Steuerung nur über „Steuerung einblenden“ oder „Mehr“. | – | §68 Nr. 25/26 |

**Gesondert gemeldet (Sicherheit, unabhängig von der Reihenfolge):** Das Klartextleck des API-Keys in K-09 betrifft jeden Seitenaufruf. Ich empfehle, es als eigene, kleine, freizugebende Maßnahme zu behandeln. Es wird **nicht** in K-01 vermischt.

## C. Nächste Kette: K-01 Serverseitige TurnTruth und Commit-Bindung

**Warum diese zuerst:**
- AMASTER §4/§28 und Kettenvertrag §1 verlangen, dass vor jedem Writer feststeht, wer gesprochen oder gehandelt hat und was tatsächlich gesagt oder getan wurde.
- Kettenvertrag §4 verbietet, dass der Client „kanonische runtimes, scene, turnIndex, currentState, witnessKnowledge oder Zeitwahrheit überschreibt“.
- Solange der Client Eingabe-Actor, Sprecher und Figurenrede vorgibt, schreiben **alle** nachgelagerten Owner gegebenenfalls korrekt die falsche Wahrheit. Das gilt für Witness, Memory, Lifecycle, Einwilligung in Rust, Runtime, Beziehung, Mode B und die Avatar-Grenze.
- Jede Reparatur in K-02 bis K-08 bliebe sonst umgehbar.
- K-01 ist damit die früheste falsche Naht (Kettenvertrag §6.5).

**Ausgangsnachweis (live, `belege/live/L_turntruth_07.json`):**

| Probe | Messung | Ergebnis |
|---|---|---|
| L1 | Bedienperson ohne Avatar/Puppet, `prepare` mit `inputActorId=char_g7_mara` → HTTP 200, neuer Fact `speech`, **actor `char_g7_mara`**, authority `teilnehmer` | Defekt reproduziert |
| L2 | `commit` mit `result.speech="ERFUNDEN-VOM-CLIENT: …"`, **ohne** `/api/llm/formulate` → HTTP 200, Fact `speech`, actor Johann, authority `character` | Defekt reproduziert |
| L2 | `fired=[Angst 1.0]` → Runtime Johanns unverändert | **nicht** reproduziert. Die Testclient-Probe Z-22 hat die Runtime über `result.proposals.synapsen` geändert; dieser Weg ist live noch UNGEPRÜFT. |
| L3 | Neustart `START.py`, Rücklesen HTTP + SQLite | Fälschung bleibt kanonisch |
| L4 | Digest der anderen Session `ses_av06` | unverändert (Isolation hält) |

**Root-Cause:** `/api/kernel/prepare` und `/api/kernel/commit` behandeln die Client-TurnTruth und das Client-Ergebnis als Wahrheit statt als Bedienabsicht.
- `app.py:1579`: `bound = dict(raw)`.
- `kernel.default_input_actor_id`, `kernel.py:1002–1004`: Ein explizit gesendeter Wert gewinnt immer.
- `app.py:1987`: `result = body.get("result")`.
- `/api/llm/formulate` speichert sein Ergebnis nicht am Quellturn. Es gibt deshalb nichts, woran der Commit gebunden werden könnte.

**Bestehende SPS-Lösung, wird erhalten und nicht neu gebaut:**
- `kernel._OPERATOR_IDS` und `default_input_actor_id` (V65F, SPS Z. 4352ff.) leiten die Bedienperson, den Avatar, den Puppet-Sprecher und den Figurenfolgezug bereits aus Rolle und Route ab. Fehlerhaft ist nur, dass ein Clientwert diese Ableitung überstimmt.
- `pendingInputTurnId` mit „Antwort erneut erzeugen“ (V65U, Z. 3020) ist die vorhandene offene Eingabe, an die das Formulierungsergebnis gebunden werden kann.
- Die Schreibkette TurnTruth → Effekt-Bindung → Writer (V65Z, Z. 1845) bleibt der einzige Schreibweg.
- Die Sprecherwahl `rank_speakers` existiert serverseitig. Sie läuft nur bei `autoPick`.

**Beteiligte Dateien:**

| Datei | Stelle | Was die Reparatur dort tun muss |
|---|---|---|
| `matrix_api/app.py` | `kernel_prepare` (TurnTruth-Bindung ≈1575–1700) | Actor, Sprecher, Szene, Zeit und Upload serverseitig binden. Ein Clientwert ist nur Bedienabsicht: Er wird gegen die Ableitung geprüft und bei Widerspruch fail-closed abgelehnt (422 mit Code), nicht übernommen. |
| `matrix_api/app.py` | `kernel_commit` (≈1940–2000) | Nur das für diesen Quellturn serverseitig erzeugte Ergebnis committen. Client-`result`, `fired` und `proposals` sind keine Quelle. |
| `matrix_api/kernel.py` | `default_input_actor_id` :1000; TurnTruth-Aufbau :12620ff; Hörer :8688/:8978/:12542; `_bind_lifecycle_evidence` :11895 (W2) | Ableitung statt Übernahme. Hörerliste ohne Fallback „leer → alle“. W2: Prüfregel „Actor des `responds_to`-Facts passt zum Lifecycle-Actor bei gleicher Quell-TurnTruth“, **nicht** „actor == speaker“. Die T-W2-Probe belegt, dass „actor == speaker“ gültige Avatar-, Bedienpersonen-, Regie- und Körperkontakt-Antworten zerstören würde. |
| `matrix_api/llm_contract.py` | `formulate_from_config` :2844 | Das Ergebnis am vorhandenen Quellturn (`pendingInputTurnId`) im **vorhandenen** Turn-/TurnTruth-Owner ablegen, kein neuer Store. Ob die vorhandene Zeile das trägt, ist vor der Umsetzung zu belegen; bis dahin UNKLAR. |
| `src/routes/chat.$sessionId.tsx`, `src/lib/matrix/kernel-bridge.ts` | Sprecherwahl :887–941, formulate :443, commit :606, Bridge :165/:253 | Der Client sendet Bedienabsicht (Text, gewähltes Ziel, Modus) und die Referenz des Quellturns, keine Figurenrede, keinen Actor, keine Synapsen. Fehler werden sichtbar mit Code angezeigt (wie M3). |

**Grenzen:**
- keine neue Route, kein neuer Store, keine zweite Zustandsverwaltung;
- keine neuen Einwilligungsregeln; der Rust-Kern bleibt unverändert;
- Puppet, Regie-Folgezug, AutoChat, Avatar-Eingabe und Bedienperson bleiben funktionsfähig, als ausdrückliche Positivfälle.

**Abnahmekriterien** (Kettenvertrag §16, alle am frisch entpackten Paket, echter `START.py`, Browser):
1. **Negativ:** L1, L2 und die Variante `proposals.synapsen` werden abgelehnt (4xx mit Code). SQLite ist vorher und nachher gleich (Digest), es gibt keine Erfolgsanzeige und die Fehlermeldung im UI ist sichtbar.
2. **Positiv über die echte Oberfläche:** Bedienperson, Avatar-Eingabe, Puppet, Regie-Folgezug und AutoChat-Turn.
   - Gespeichert sind jeweils der richtige Eingabe-Actor, Sprecher und Hörer, und genau der serverseitig formulierte Text.
   - Gespeichert sind dieselbe `source_turn_id`, Witness nur für Hörer und Seher, und Memory nur für Berechtigte.
3. **Folgeturn:** Der Recall der antwortenden Figur enthält genau diese Facts; eine Abwesende und eine Nicht-Hörerin wissen nichts.
4. **Neustart:** Das Rücklesen über HTTP und SQLite ist gleich. Die UI zeigt nach dem Reload denselben Verlauf.
5. **W2:** Szenario 3 der T-W2-Probe (Annahme ohne eigene Rede, Bindung an fremde Frage) wird abgewiesen. Die Positivfälle Avatar-Annahme, Bedienperson und Körperkontakt-Antwort bleiben gültig.
6. **Mutationsgegenprobe:** Wird die Ableitung entfernt (Clientwert gewinnt wieder), müssen die Kriterien 1 und 5 ROT werden.
7. **Regression:** Die Kette `run_chain_06` ist unverändert (Exit 2, nur bekannte ROT/BLOCKIERT). Die P25-Suite hat keine neue Abweichung, die Isolation fremder Sessions hält.
8. **BLOCKIERT bis Provider vorhanden:** Formulierung mit echtem Modell und psychologische Folgewirkung (K-03). Offline wird mit `synapse` geprüft und so gekennzeichnet.

**route-safe: JA, unter Vorbehalt.**
- Keine neue Route.
- Die vorhandenen SPS-Bausteine (`default_input_actor_id`, `pendingInputTurnId`, V65Z-Schreibkette) werden genutzt statt verdoppelt.
- Der Prompt bleibt Spiegel.
- **Vorbehalt UNKLAR:** Der Ort, an dem das Formulierungsergebnis am Quellturn abgelegt wird. Er ist vor dem Patch am Schema `turns`/`turn_truth` zu belegen. Er darf kein neuer Store werden.

## D. Gesamtfortschritt

**Bewertungsgrundlage:** Kettenvertrag §3; keine Prozentwerte, die einen ROT-Punkt verdecken. Die Zahlen sind Anzahl Funktionen; Belegquelle ist Codefluss und, wo angegeben, eine ausgeführte Probe.

| Kategorie | Anzahl | Bedeutung |
|---|---:|---|
| läuft vollständig (GRÜN) | **0** | Keine Funktion ist mit UI, Modell, Folgeturn, Reload und Isolation abgenommen. |
| teilweise (TEILGESCHLOSSEN) | 83 | Glieder belegt, E2E unbewiesen. Darunter 54 Ketten, die im Code geschlossen sind. |
| defekt (ROT) | 85 | mindestens ein Pflichtglied falsch, fehlend oder umgangen, mit `datei:zeile` |
| fehlt (statisch FEHLT_IM_CODE) | 10 | z. B. Review-Generator, epistemische Memory-Zustände, Prüfung der Ausgabe (§28 Schritt 19) |
| ungeprüft | 11 | statisch UNKLAR, Ausführung nötig |
| blockiert | 4 + alle Live-Modellketten | Provider-Key, Original-DB und Test-EPUB fehlen |

**Die sechs Pflichtabläufe für selbstständig handelnde Figuren (Auftrag Punkt 5):**

| Ablauf | Status | Beleg |
|---|---|---|
| Figur löst im erlaubten Rahmen eigenständig eine Handlung aus | ROT | AutoChat nutzt denselben Turnpfad (A), aber nur vom Browser angestoßen; Sprecher vom Client (K-01); Wortlisten-Ranking (K-05) |
| Wahrnehmung und Entscheidung nutzen den richtigen Welt- und Szenenzustand | ROT | Weltfelder ohne Leser (W-06); Hörer-Fallback; das Ranking liest den Stand vor dem Eingabe-Commit (`app.py:1652` vor `:1732`) |
| Erfahrungen dauerhaft speichern und wiederverwenden | TEILGESCHLOSSEN | Witness → Memory → Recall → neue App-Instanz (Z-Probe, ausgeführt); Persistenz nach echtem Neustart (live L3); aber Actor und Inhalt sind fälschbar (K-01) |
| Neue Erfahrungen beeinflussen späteres Verhalten | ROT / BLOCKIERT | Ohne Provider keine Wirkung auf Runtime, Ziel oder Beziehung (Z-Probe); lokal nur Wortüberlappung; mit Provider ungeprüft |
| Andere Figuren und User erleben konsistente Auswirkungen | ROT | Mode B an alle; Hörensagen ohne Bezug; Socialseite überschreibt Beziehungen (K-02, K-03, K-08) |
| Steuerbar und nachvollziehbar über die bestehende Oberfläche | TEILGESCHLOSSEN | AutoChat-Schalter und Kandidatenliste mit Gründen vorhanden; der Stoppgrund steht nur im Client-Log; 28 Routen ohne Bedienung |

**Gesamturteil:**
- Matrix10 ist ein weit ausgebauter P25-Kern mit echter Persistenz, einem gemeinsamen Turnpfad und einer funktionierenden lokalen Gedächtniskette.
- Das Produktziel erreicht er nicht. Die Wahrheit über Sprecher, Actor und Gesagtes wird nicht serverseitig gebunden (K-01).
- Die psychologische Wirkung von Erfahrung hängt vollständig am Provider (K-03).
- Mehrere Wortlisten-Automaten steuern Verhalten, obwohl AMASTER §15/§16/§68 Nr. 21 sie ausschließen.
- **Status: ROT.**
- Nächster Schritt nach Freigabe: K-01 vollständig nach Kettenvertrag §6 umsetzen und unabhängig abnehmen, keine Folge isolierter Teilkorrekturen.

## Dateien dieser Lieferung

- `GESAMTKARTE_07.md`: dieser Bericht (A–D).
- `KARTE_GESAMT_07.md` / `.json`: vollständige Karte, generiert mit `tools/karte_zusammenfuehren_07.py` aus `karte/*.json`.
- `karte/{W,T,Z,A,P}.json`: Bereichskarten inklusive `P-MATRIX` und `T-W2`.
- `tools/live_turntruth_07.py`: Live-Ausgangsnachweis K-01. Aufruf: `python3 -I live_turntruth_07.py <produktordner mit frontend_dist und Rust-Lib> <vorlage.sqlite> <ausgabe.json>`.
- `belege/live/`: `L_turntruth_07.json`, Startlog, Vorlage-DB (aus dem Gesamtlauf `1b56e13`, mit Rust erzeugt).
- `belege/proben/`: ausgeführte Proben der Bereichsprüfer (Testclient). Sie erwarten Pfade zu einer Kopie des Stage-Ordners als Argument.
- `belege/nachpruefung_06a/`: Nachprüfung am frischen Klon.
