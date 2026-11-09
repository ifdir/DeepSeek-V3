# Kettenkarte Stand 12A – ein Ereignis durch die ganze Kette (09.11.2026)

**Auftrag:** freigegebener Plan 12A (Kettenvertrag §6). Diese Karte enthält nur Messung und Lesen; Produktcode ist nicht geändert.

**Status: ROT.** Erleben, Beziehung, Speicherung und Neustart tragen. Die Kette **eigene Handlung → Wirkung → Raum/Körper → nächster Zug** ist in beiden Ständen unterbrochen: in P25 teilweise, in Stand 12 fast vollständig.

## 1. Ausgangsbasis

| | |
|---|---|
| **Datenbank** | Deine DB aus Upload 11C, SHA-256 `069b7f19…`. Je Lauf eine eigene, unveränderte Kopie. Nur der Endpoint der Kopie zeigt auf die Zähl-Weiterleitung. |
| **P25** | Eingefrorenes ZIP (`33a51497…`) plus Ebene 06 (Rust-Schreibgrenze). P25 allein ist laut eigener Freigabesperre nicht startbar. Frontend und Rust-Bibliothek kommen aus dem Stand-12-Paket. |
| **Stand 12** | Paket `e90bd55`, frisch entpackt. |
| **Modell** | gpt-4o-mini, je Stand 2 Läufe. |
| **Messweg** | `ARBEITSSTAND_12/tools/kette_12a.py` und `oberflaeche_12a.cjs`: Sitzung **über die Oberfläche** angelegt (Chromium: Welt, Johann und Mara anwesend), Züge über die echten Routen, am Ende Anzeige, Spiegel, Neustart, wieder Spiegel und Anzeige. Rohdaten je Lauf: `ergebnis.json`, `modellaufrufe.jsonl`, Live-Log, Bildschirmfotos. |
| **Modell oder Code?** | Wo dieselbe Modellaussage in beiden Ständen verschieden wirkt, liegt es am Code. Wo die Modellaussage selbst falsch ist (z. B. „gewalt“ statt „fesseln“), steht „Modell“. |

## 2. Messfälle

1. **Grundfall:** Johann: „Hey süsse, ich klarsche dir auf deinen Arsch“, dann „Ach komm stell dich nicht so an“. Mara reagiert jeweils.
2. **Übergriff ohne Verletzung:** Johann: „Ich greife unter dein tshirt und lach dich an“. Mara reagiert.
3. **AutoChat:** 3 Züge, gewählt vom Server.
4. **Erfolg:** Mara, gesteuert: „Ich trete einen Schritt von Johann zurück.“
5. **Festhalten:** Johann: „Ich packe Mara fest am Handgelenk und halte sie fest.“ Danach Mara: „Ich gehe von Johann weg zur Tür.“
6. **Zwei Taten:** Mara: „Ich stoße Johann von mir weg und trete zurück.“
7. **Neustart:** Spiegel und Zustand vorher und nachher.
8. **Fremde Figuren:** Clara, Gustav, Robert, andere Sitzungen und Stamm, per Hash vorher/nachher.

## 3. Kettenkarte

Legende: Messung „P25 / 12“ = Ergebnis in den 2 + 2 Läufen. „Erste Abweichung“ = die erste Ebene, die vom Vertrag abweicht. Bei „≤ P25“ ist es schon im Ausgangsstand so.

| # | Glied | SOLL | Code (P25 → 12) | Messung P25 / 12 | Befund | Erste Abweichung |
|---|---|---|---|---|---|---|
| 1 | Oberfläche → neue Sitzung | §19 Startpräsenz | `chat.index.tsx` → `POST /api/sessions` | 2/2 / 2/2: Johann und Mara anwesend, kein alter Szenenzustand | **geht** | – |
| 2 | Eingabe lesen (Komponenten) | §24.2, §27.4: jedes Wort gehört zu einer Komponente | `bind_puppet_input`, `input_binding_outcome` | **P25: 0/2** – „Hey süsse, ich klarsche …“ wird ganz verworfen (422, „Hey süsse“ ungelesen). 12: 2/2 | P25 bricht, **12 repariert** (11B/11C/12) | P25 (C6) – Stand 12 behalten |
| 3 | Vollzug der Tat | §34.1 | Vollzugslesung (P25 Einzelaufruf, 12 Pflichtfeld des Planers) | alle Taten `geschieht: true`, beide | **geht** | – |
| 4 | **Ziel der Tat** (an wem?) | §25 Identität, §43 | `bind_input_components` → `commit_puppet` (`targetId`) | **P25:** „Ich trete einen Schritt von Johann zurück“ → `targetId: None`. **Stand 12:** `targetId: char_g7_johann` (Live-Log TURN_INPUT und SQLite-Fakt) | **P25 bricht, 12 geht** (*Korrektur nach Prüfung: in der ersten Fassung als Bruch in 12 geführt – falsch*) | P25, in einer späteren Ebene schon repariert |
| 5a | **Wirkung der Figurenantwort** (Mara zieht sich zurück, Johann rückt näher) | §24.2, §43, §43.1 | P25: Art aus der Antwort, Bestätigung per Einzelaufruf. 12: Bestätigung als Pflichtfeld `pruefung.bewegung` (null erlaubt) → `apply_effect_check` | wirksam: **P25 3/8, 4/8 – 12 0/9, 3/8**. In 12 meist `keine_pruefung` (Feld leer); in beiden auch `beleg_nicht_in_handlung` | P25 teilweise, **12 schlechter** | **Stand 11/11A** (Bestätigung als leeres Pflichtfeld) |
| 5b | **Festhalten** | §43 Capability, §42 | P25: Wirkungsprüfung „gewalt“ → nicht bestätigt → Ersatz Berührung. 12: `fesseln` + `keine_pruefung` | **beide 0/2:** Mara nie festgehalten (`restrained`/`heldBy` leer) | **bricht** | **≤ P25** (Modell liest gewalt statt fesseln **und** P25 hat keine eigene Bestätigung für „halte fest“) |
| 5c | **Eine Wirkung je Tat** | §34.1 jede Komponente | `commit_turn`: `_out_wirkung` **einmal** je Antwort, an jede Tat gehängt (P25 Z. 8548, 12 Z. 8588/8663) | in den Läufen nur Einzeltaten der Figur; im Puppet-Weg 2 Taten je eigener Fakt | Gefahr im Figurenweg, belegt im Code | ≤ P25 |
| 5d | **Beleg zu weit** | §24.2 wörtlich, je Tat | `apply_effect_check` verlangt den Beleg innerhalb **dieser** Tat | beide: Zitat über beide Taten („… weg und trete zurück.“) → `beleg_nicht_in_handlung` | **bricht** (Modell zitiert die ganze Eingabe; der Kernel hat keinen Bezug je Tat) | ≤ P25 |
| 5e | Ortswechsel ohne bekannten Ort („zur Tür“) | §43 SpatialState | `_apply_physical` move → `ziel_ort_unbekannt` | beide: keine Wirkung, sichtbar als mehrdeutig | **richtig fail-closed**; die Lesung „ortswechsel“ statt „entfernung“ ist eine Modellfrage | – |
| 6 | Berührung → Raum | §43.2, §68 Nr. 45 | `_apply_physical` social → `set_spatial(beruehrung)` | beide: Klaps und Griff → „Berührung“ | **geht** | – |
| 7 | **Raum im Zeitverlauf** | §43.2 | `sceneState.spatial` | 12 Lauf 1: „Berührung seit Zug 1“ **bis zum Ende**, obwohl Mara 6× zurücktritt; P25: wechselt nur, wenn 5a gelingt | **bricht** als Folge von 4/5 | Folge |
| 8 | **Eskalation** | §46 Fate, §41 | Schreiber `scene_state.record_physical` (+0,25 nur bei Schlag/Festhalten), Abklingen −0,08 in ruhigen Zügen; Leser in Sprecherwahl und Brief | beide: 0,0, weil nie ein Schlag oder Festhalten geprüft durchkam (5a/5b); Berührung gegen Ablehnung und überwundener Rückzug erhöhen nie | **teilweise angeschlossen** (*Korrektur: erste Fassung „nie angeschlossen“ – falsch*) | ≤ P25 |
| 9 | Wahrnehmung → Erleben (Gefühl, Absicht) | §42, §44, V62.7 | `pending_appraisals` → Erleben je Figur → `apply_appraisals` | beide: Gefühl und Absicht ändern sich je Ereignis (Ekel → Wut → Bedrohung → Angst; „sich abgrenzen“, „einschüchtern“). Verworfen: P25 4–5 Felder (Richtung/Disposition), 12 1–6 (fast nur Absicht) | **geht** | – |
| 10 | Beziehung | §42, §45 | Erleben → `_apply_relation_target` | beide: Vertrauen 0,15 → 0,07–0,11, Furcht 0,70 → 0,83–0,93 | **geht** | – |
| 11 | Körperzustand (Schmerz, Beweglichkeit) | §43 | `_apply_physical` / Körper-Writer | beide: Beweglichkeit 0,9 unverändert, kein Festhalten (5b) | bricht über 5b | ≤ P25 |
| 12 | Absicht → eigene Tat | §46, §48 | Brief „du willst gerade“ → Formulierung | beide: Absicht und Tat passen (Abgrenzen → Schritt zurück; Einschüchtern → Schritt näher). Wirksam nur, wenn 5a gelingt | Entscheidung **geht**, Ausführung **bricht** (5a) | Folge |
| 13 | Nächster Brief | §41, §49 | `bind_formulation_spiegel` → `render_persona_brief` (RAUM, LAGE) | liest den gespeicherten Raum – also „Körperkontakt“, wenn 5a nicht wirkte | Leser **richtig**, gibt die falsche Lage weiter | Folge |
| 14 | Speicherung und Neustart | §6.2, Kettenvertrag | SQLite → `repos.hydrate…` | 4/4: Zustand und Spiegel nach Neustart gleich | **geht** | – |
| 15 | Anzeige (Oberfläche) | Kettenvertrag §6.3 | `chat.$sessionId.tsx` | 4/4: Dialog und Fakten sichtbar, vor und nach Neustart. **Raum, Festhalten und Körper werden nirgends angezeigt** | Anzeige des Szenenzustands **fehlt** | ≤ P25 |
| 16 | Fremde Figuren, andere Sitzungen, Stamm | §39, Isolation | – | 4/4 unverändert | **geht** | – |
| 17 | Zurücksetzen der Sitzung | Reset-Semantik | `kernel_reset` (chat/runtime/memory) | Szenenzustand (Raum, Verlauf, offene Forderungen) **bleibt** stehen, gemessen an deiner Sitzung 11:07 | **bricht** | ≤ P25 (gleicher Writer) |
| 18 | Zeit und Aufrufe (10 Schritte) | V62.7: 7–15 s je Zug | – | P25: 189 s, 67–72 Aufrufe; 12: 122–138 s, 22–24 Aufrufe. Eingabe mit Reaktion: P25 25–34 s, 12 17–29 s; AutoChat P25 19–26 s, 12 12–16 s | 12 schneller | – |

**UNKLAR:** Das Lesen des Spiegels (prepare ohne Antwort) legt Erlebens-Fakten an. Der Zustand blieb gleich, die Anzeige zeigte danach zusätzliche Zeilen. Ob prepare dabei ein schon bewertetes Ereignis erneut bewertet, prüfe ich in der Reparatur.

## 4. Ein Ereignis durch die Kette (Beispiel, Stand 12 Lauf 1, Zug 3)

1. Johann: „Ich greife unter dein tshirt“.
2. Komponente Tat → Fakt, validiert, Ziel Mara → Berührung (Raum) → Mara nimmt wahr → Erleben: „Bedrohung (Angst); will: sich noch deutlicher abgrenzen“ → Beziehung: Vertrauen sinkt, Furcht steigt.
3. Brief: Lage, Absicht, Ablehnung → Antwort: „Lass das! …“ und „Ich mache einen Schritt zurück“, Vorschlag `entfernung`.
4. **Hier reißt die Kette:** `pruefung.bewegung = null` → `keine_pruefung` → ohne Wirkung → Raum bleibt „Berührung“ → der nächste Brief sagt Mara, Johann berühre sie noch.
5. Neustart: derselbe falsche Raum, korrekt gespeichert.

## 5. Erhalten (spätere gültige Funktionen, die bleiben)
- Eingabe ganz lesen (11B/11C/12).
- Ganzer Wortlaut im Brief.
- Lage zuerst und Auswahl nach Bedeutung (11E/11F).
- Erleben mit kurzem Nachweis (12).
- „Aus eigenem Antrieb“ (12).
- Sprecherprüfung am Server (07/10).
- Eigene Belege im Lebenszyklus (07).
- Wahrnehmung zum Antwortzeitpunkt (08).
- Rust-Schreibgrenze (06/10A).
- Sicherheitsfix `/api/mcc` (07).
- 3–4 statt 9–15 Aufrufe.

## 6. Reparaturplan (ein zusammenhängender Plan, zur Freigabe)

### Brüche und ihre Reparatur

| Bruch | Root-Cause | Reparatur: vorhandene Funktion wieder anschließen | Risiko |
|---|---|---|---|
| 5a, 5c, 5d | Art und Bestätigung getrennt (11A); eine Wirkung je Antwort; Beleg ohne Bezug zur Tat | **Eine Tat = ein Eintrag** mit eigenem Textabschnitt, eigener Art, eigenem Ziel, eigenem Beleg und Vollzug, Versuch, Berührung. Gilt für die Antwort der Figur (`handlungen[]`) und die Tat-Komponente des Planers. Die Figurenantwort läuft durch dieselbe Komponentenbindung wie Puppet und Avatar (`bind_input_components`, `parts_cover`). Der Umwandler versorgt die vorhandenen Validatoren vollständig (`bewegung`, `beruehrung`, `wirkung` inkl. `beruehrungBeleg`). **Ausgang und Erfolg entscheidet der Kernel unverändert** (`_movement_block`, Einwilligung, `act_outcome`). | Formulierung, Commit, Live-Log, Testmodell, Drehbücher |
| 4 | – | Entfällt: Stand 12 bindet das Ziel richtig (belegt). | – |
| 5b | „halte fest“ hatte keinen eigenen Bestätigungsweg | Folgt aus 5a: `fesseln` mit Beleg und Vollzug geht an den vorhandenen Festhalte-Writer. Liest das Modell „gewalt“, bleibt es Gewalt oder Berührung, sichtbar. | Körper, Fähigkeit |
| 17 | Das Zurücksetzen lässt den Szenenzustand stehen | `reset_session_chat` bzw. `runtime` leeren auch `sceneState`, wie `reset_session_full` es schon tut | Session-Reset, UI |
| 9 (Rest) | Verworfene Absicht | Am Zitat prüfen, nur Zuordnung korrigieren | Erleben |
| UNKLAR prepare | – | prüfen: zweimal prepare ohne neues Ereignis → keine neue Bewertung | Erleben, Idempotenz |

### Deine Entscheidung (nicht stillschweigend)
- **8 Eskalation:** Es gibt Leser, aber nie einen Schreiber. Entweder einen Writer aus den vorhandenen Ereignissen anschließen (z. B. Gewalt, überwundener Rückzug, Ablehnung) oder den Wert aus Brief und Sprecherwahl nehmen. Ohne Entscheidung bleibt er offen.
- **15 Anzeige des Szenenzustands:** Die Oberfläche zeigt Raum, Festhalten und Körper nicht. Eine kleine Anzeige im vorhandenen Szenenbereich, nur lesend, wäre nötig, damit „sichtbare Szene = gespeicherter Zustand“ prüfbar wird.

### No-Touch
- W3-C, NS2, SocialMatrix, GodCommandParser, START_ANWEISUNG.
- Profile und Backstory.
- K-05.
- Wiederholungsfilter (SPS K08).
- Keine neue Modell-Gegenprüfung, keine neue Route oder Schicht.

### Abnahme
- **Kettenlauf:** `kette_12a.py`, 2× live auf dem reparierten Stand gegen dieselben P25-Läufe, gleiche DB-Kopie.
- **Je Tat:** Text, Ziel, Fakt, Ausgang, Raum, Körper, nächster Brief, Anzeige – vor und nach dem Neustart.
- **Erfolg:**
  - Rückzug → Abstand.
  - Zwei Taten → zwei Wirkungen.
  - Klaps und Griff → Berührung gegen Ablehnung.
- **Misserfolg:**
  - Festgehalten → Weggehen blockiert, sichtbar.
  - Unbekannter Ort → mehrdeutig, sichtbar.
- **Fremde Figuren:** unverändert.
- **Tests:** Prüftests, P25-Suite (die 12 bekannten roten bleiben gelistet, nicht verschwiegen), F1 und F2.
- **Gerät:** Android/Termux ist **nicht** durch Linux ersetzt; das gilt erst mit deinem Gerätelauf.
