# Stand 12 – Handlungsfähigkeit, gemessen mit echtem Modell (09.11.2026)

**Quelle:** Overlay `ARBEITSSTAND_11/overlay` weitergeführt. Stand 12 ist keine neue Schicht. Pakete: `MATRIX10_STAND12_*`.
**Anlass:** Deine Rückmeldung, dass Matrix10 schon weiter war (SPS V62.7) und die Figuren mechanisch wirken. Jede Reparatur wird an der Kette gemessen, nicht an grünen Einzeltests.

## 1. Was V62.7 laut SPS wirklich konnte

Quelle: SPS-Deckblatt V62, Z. 4008–4090.

| | V62.7 (SPS, gemessen am Server) | Einordnung |
|---|---|---|
| Erleben vor der Antwort, Gefühl/Absicht/Beziehung im selben Zug | ja | Diese Kette ist in 11F/12 unverändert vorhanden (Kernel: `appraise`, Abklingen ×0,75, Absicht mit Ursache, Avatar nie bewertet). |
| Aufrufe je Zug | 5 (13 Planer + 39 Erleben + 13 Formulierung bei 3 Figuren) | 11F/12: 3–4 (Planer, Erleben je Figur gleichzeitig, Formulierung). |
| Sekunden je Zug | 7,2–14,8 | siehe Abschnitt 3 |
| Wiederholung | **offen**: 14–20 wiederholte 5-Wort-Folgen je Lauf | Diese Grenze hatte V62.7 auch. |
| Eigenständiges Handeln | **offen** („Handlung … offen“) | SOLL nach AMASTER, nie als erreicht belegt. |

Zwischen V62.7 und P25 kamen die V84–V92-Prüfungen dazu: Kausalnachweis und Einzellesungen. Damit stieg die Zahl auf 9–15 Aufrufe je Zug (`ARBEITSSTAND_10A/BEFUND_GLEICHSTAND_P25_10A.md`). Stand 11 hat die Lesungen in die erste Antwort gelegt, aber die Antworten wurden dadurch lang.

## 2. Messweg (live, gpt-4o-mini, dein Schlüssel)

- **Daten:** Kopie deiner Datenbank (Upload 11C), Sitzung „Gasthaus zum siebten Kreis · 11:07“, auf der Kopie zurückgesetzt.
- **Szenario:** deine drei Eingaben als Johann, je Eingabe Maras Reaktionszug wie in der Oberfläche, danach 3 AutoChat-Züge (`autochat-gate` → Sprecher des Servers).
- **Werkzeuge:**
  - `tools/live_kette_12.py` fährt den Lauf über die echten Routen.
  - `tools/zaehler_12.py` leitet jede Modellanfrage unverändert an OpenAI weiter und zählt sie; der Schlüssel wird nie protokolliert.
  - `tools/auswertung_12.py` erstellt die Tabelle.
- **Wichtig:** Die Geschwindigkeit von OpenAI schwankte stark. Derselbe unveränderte Planer brauchte 5–7 s, in einem Lauf 16–27 s. Deshalb liefen die Stände abwechselnd und werden mit Ausgabe-Token verglichen.

## 3. Ergebnis 11F gegen 12 (je 3 Läufe, abwechselnd)

| Kennzahl | 11F | 12 |
|---|---|---|
| Erleben: Ausgabe je Antwort | Ø 658–796 Token (max 1215) | Ø 374–417 Token (max 540) |
| Erleben: Dauer | Ø 10,1–11,8 s | Ø 6,1–7,5 s |
| Verworfene Erlebensfelder (Kernel) | 81 in 38 Antworten, davon 72 „ursache_nicht_woertlich“ | 16 in 29 Antworten, fast nur die unveränderte Absicht ohne Nachweis |
| Zeit AutoChat-Zug (Erleben + Formulierung) | 20,3–38,4 s | 13,5–19,2 s |
| Zeit Eingabe-Zug (Planer + Erleben + Formulierung) | 22,4–40,0 s | 22,4–25,7 s (ohne den langsamen Lauf 12_1) |
| Verlorene Züge | 0 | 1 (Lauf 12_3, Ursache und Reparatur siehe 4.4) |
| Wiederholte 5-Wort-Folgen Mara | 8 / 13 / 2 | 6 / 10 / 9 |

**Nicht verbessert:** Mara wiederholt sich gleich oft. Die Zahlen streuen stark, ein Unterschied ist nicht belegt.

## 4. Ursachen und Änderungen

### 4.1 Das Erleben war die langsamste Stufe, und der Kernel verwarf es meist

- **Ursache, belegt:** Je Wert schrieb das Modell einen langen Nachweis: Fakt-ID, Zitat, Quellen-ID, Quellzitat, Richtung, Begründung. Das sind 600–1200 Token. Außerdem hing es Johanns wörtlichen Satz oft an die Kennung seiner Handlung aus demselben Zug (Rede und Handlung sind zwei Fakten). Der Kernel prüft wörtlich und verwarf deshalb Gefühl, Absicht und Beziehung.
- **Änderung** (`llm_contract`: `_erleben_kennungen`, `_nachweise_auffalten`, `P_NACHWEIS`):
  - Der Nachweis ist kurz: Kennung G1/G2, Zitat mit 2–8 Wörtern, Quellen-ID, Richtung, Grund mit höchstens 8 Wörtern.
  - Den Quelltext und die Begründungsform baut der Server aus der Quellen-ID.
  - Steht das Zitat wörtlich in genau einem anderen Ereignis dieses Erlebens, gilt dieses Ereignis.
  - Der Kernel prüft unverändert: Ereignis wahrgenommen und validiert, Zitat wörtlich, Quelle gehört zu diesem Feld, Richtung.
- **Ehrlich:** Früher musste das Modell die Quelle zusätzlich wörtlich abschreiben. Jetzt nennt es nur ihre ID, und der Kernel prüft, dass diese Quelle zum Feld gehört. Das Abschreiben war keine inhaltliche Prüfung. Die Unabhängigkeit der Gegenprüfung (P25: zweiter, blinder Aufruf) fehlt seit Stand 11 und bleibt offen.

### 4.2 „Aus eigenem Antrieb“ griff fast nie

- **Ursache, belegt** (`kernel.bind_formulation_spiegel`): In einem AutoChat-Zug ohne neuen Reiz (sie hat schon geantwortet) nahm der alte Leser die letzte fremde Dialogzeile. Sie bekam „JETZT SAGT Johann: …“ ein zweites Mal und antwortete erneut darauf.
- **Änderung:** Kein Reiz bedeutet die Zeile „KEIN NUTZER SPRICHT — du ergreifst das Wort aus eigenem Antrieb; aktuelle gespeicherte Absicht: …“.
- **Test:** `test_kette_12`. An 11F rot.
- **Grenze:** Im Live-Szenario (zwei Anwesende) wechseln sich die Sprecher ab, jede Figur hat dann einen neuen Reiz. Der Fall tritt bei mehreren Figuren oder einer Figur, die zuletzt sprach, auf.

### 4.3 Wiederholung

- **Ursache:**
  - Im Verlauf war nur die **letzte** eigene Zeile als „nicht wiederholen“ markiert. Mara übernahm Sätze aus früheren eigenen Zeilen („Ich hab dir gesagt, dass ich nicht …“).
  - Die Antwort ist zu 70 % Pflicht-JSON und zu 30 % Rede und Handlung.
- **Änderung:** Frühere eigene Zeilen tragen „← von dir schon gesagt/getan“.
- **Ergebnis:** Nicht messbar besser (siehe 3).
- **Bewusst nicht gemacht:** Sätze nachträglich löschen. Die SPS hat das entfernt (K08: „Modellrede wird nicht durch Wiederholungsfilter ersetzt“).

### 4.4 Verlorener Zug durch eine erfundene Komponente (live gefunden)

- **Befund** (Lauf 12_3): Auf „Ach komm stell dich nicht so an“ erfand der Planer eine zweite Komponente, „lehnt die Berührung ab“. Diese Worte stehen nicht im Eingang. Der Satz war vollständig als Rede gelesen, trotzdem wurde `PUPPET_TEILABLEHNUNG` gemeldet und nichts gespeichert. Das ist dieselbe Fehlerklasse wie die verlorenen Züge in 11 und 11A auf deinem Gerät.
- **Änderung** (`kernel.input_binding_outcome`): Eine Komponente mit Worten, die nicht im Eingang stehen, kippt die Eingabe nicht, wenn kein Rest übrig ist. Gibt es einen Rest (das Modell könnte eine echte Tat umschrieben haben), bleibt es bei der Teilablehnung. Sonst würde aus einer Tat Rede.
- **Tests:** beide Fälle in `test_kette_12`.

## 5. Prüfung (Paket aus Commit, frisch entpackt, Testmodell)

- Prüftests: 67/67, darunter `test_kette_12` 11/11. An 11F scheitern davon 8.
- P25-Suite: 436 grün, 12 rot. Das sind dieselben 12 wie in P25 und 11F (Build-Vertrag im Linux-Paket plus 11 P25-Altfehler).
- F1: 12/12. Gegenprobe 8/12 (soll rot sein).
- F2: 7/7.
- Grenze im Brief: 6/6.
- Gerätefälle: 4–5 Aufrufe.

## 6. Offen (Status ROT)

- **Wiederholung:** nicht gelöst. Die nächste Stellschraube wäre der Formulierungsauftrag selbst (70 % Pflicht-JSON, Rede bis 6 Sätze). Das ist eine Entscheidung über den Antwortvertrag, kein Prompt-Flick.
- **Zeit:** Eingabe-Zug 22–26 s bei normaler OpenAI-Geschwindigkeit, AutoChat-Zug 13–19 s. Das Ziel ≤15 s ist für AutoChat erreicht, für Eingabe-Züge nicht. Planer (~6 s) und Formulierung (~8–9 s) sind unverändert.
- **Unabhängige Kausalprüfung:** seit Stand 11 nicht mehr blind (siehe 4.1).
- **Weitere offene Punkte:** K-05 (Sprecherwahl mit Wortlisten), 11 P25-Altfehler, Android-Gerät.
