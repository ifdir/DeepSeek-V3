# MATRIX10 / AMASTER — EINZIGES SPS-MASTERBLATT (fortlaufend)
## DECKBLATT · V67 · Audit7 zu V66 (V66-01 bis V66-10): ein Abhängigkeitsgesetz für Anlegen, Zurücksetzen und Löschen, Einwilligung nur für die ganze Tat, jede Komponente an ihrem eigenen Ort (Claude) · 31.10.2026

**Verbindlich:**
- `2_7master.txt`:
  - §6.2 Z. 247–279 (Z. 262 fail-closed an kritischer Grenze);
  - §19 Z. 876 ff., Z. 898–908 (Resetarten getrennt; kein unbeabsichtigtes Entfernen);
  - §23 (TurnTruth), §24.2 Z. 1100–1118 (Validierung vor dem Writer);
  - §34 Z. 1736 ff. (SceneFact bindet Quellturn), §34.1 Z. 1774 ff., §34.2 Z. 1819–1827 („Abhängige Effects müssen ihre Abhängigkeiten ausdrücklich tragen“), §34.3 Z. 1829 ff. („Historische Evidenz wird nicht heimlich gelöscht“);
  - §36.1 Z. 1900 ff. (Request bindet die angefragte Handlung), §36.5 Z. 1945–1975 (Zustimmung an die konkrete Handlung gebunden);
  - §39 (Wissen nur aus Wahrnehmung), §54 Z. 2935 ff. (jede Produktfunktion bedienbar und prüfbar);
  - §68 Nr. 6/7, 34, 50, 63, 64, 66, 87.
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6, §16.

**Eingang:** dein unabhängiges SPS- und AMASTER-Gesamtaudit zu V66 (Audit7). Vermerk unten, unverändert. Dazu:
- **Lag bei:** Gutachten, Vorlesefassung und Nachweis-ZIP. Die Hashes laut Manifest stimmen.
- **Deine Proben:** `independent_probes.py` und `side_probes.py` laufen gegen V66 wie bei dir und gegen V67 ohne Befund.
- **Nummern:** Ich nummeriere wie dein Gutachten (V66-01 bis V66-10). In deiner Nachricht sind Uploadreset und Upload-Löschen zusammen V66-03, Handlung und Einwilligung V66-04.
- **Lag nicht bei:** die älteren Testdateien (`test_alt_independent`, `test_alt_persisted`, `test_alt_zusatz`, `test_pz01_pz04`). Ich habe sie aus `pytest_prior_independent.log` nachgebaut. Ob sie genau deine Fälle treffen: **UNKLAR**.

**Basis:** mein V66-ZIP (SHA256 `3cc7e4cb…`). DB und Logs bytegleich, keine Migration.

**Wurzel (wie dein Gutachten §5 sagt):** Die Schreibgrenze galt beim Anlegen. Für das Entfernen gab es keine.
- Vier Bedienwege entfernten eine Quelle und ließen abhängige Zeilen stehen: Chat-Reset, Voll-Reset, Uploadkontext, Upload löschen.
- Die Diagnose sah den Schaden erst hinterher.
- Dieselbe Lücke im Kleinen hatte die Einwilligung: Geprüft wurde, ob die Teile vorkommen, nicht, ob sie die ganze Tat und die ganze Bitte decken.

### Wurzel → Änderung (vorhandene Owner, keine neue Route, keine Tabelle, keine Wortliste)

| Befund | Wurzel am V66-Code (gegengeprüft) | Änderung |
|---|---|---|
| **Das eine Gesetz** | Die Regeln der Schreibgrenze wirkten nur beim Einfügen. Beim Entfernen prüfte niemand, wer sich auf eine Zeile stützt. | `dependency_guard`:<br>• Für jede betroffene Session werden die Zeilen, die die Grenze ablehnen würde, vor und nach der Operation gelesen (`_boundary_rows`). Es sind dieselben Prüfungen wie in den Writern.<br>• Wird eine vorher gültige Zeile ungültig: 409 `DEPENDENCY_BROKEN`, Rücksprung zum Savepoint, nichts geändert.<br>• Altzeilen bleiben, wie sie waren (keine Migration).<br>• Es gilt für Chat-, Memory-, Runtime-, Upload- und Voll-Reset, für das Löschen eines Uploads und für den Snapshot-Restore. Beim Restore bleiben die gezählten Altzeilen erlaubt.<br>• Die Diagnose liest dieselbe Liste (`write_boundary_audit`).<br>• Zum Umschlag kommt dazu: Eine offene Eingabe muss eine TurnTruth der Session nennen (`PENDING_INPUT_UNBOUND`). Der Turnzähler darf nicht hinter der gespeicherten Historie liegen (`TURNINDEX_BEHIND_HISTORY`). |
| V66-01 Chat-Reset | `reset_session_chat` löschte `turns` **und** `turn_truth`, die SceneFacts blieben. Jeder Fact nannte danach einen gelöschten Quellturn. Den `turnIndex` nahm die Funktion aus dem Request (777). Der Client schickte 0, also nutzten spätere Turns dieselben Nummern wie die stehen gebliebenen Facts. Deine Session `ses_3422…` zeigt das: turnIndex 1, ein Fact in Turn 2. | „Nur Chat zurücksetzen“ (§19) betrifft nur die Dialogzeilen (`turns`).<br>• TurnTruths bleiben, sie sind der kanonische Eingang und der Quellturn der bleibenden Facts.<br>• Der Turnzähler ist kernel-eigen und folgt der Historie. Ein Wert im Request wird ignoriert (`KERNEL_OWNED_FIELDS_IGNORED:turnIndex`).<br>• Die Eröffnungszeile steht am aktuellen Turn.<br>• Beide Wege (UI-Route und `/api/kernel/reset`) laufen über denselben Writer. |
| V66-02 Voll-Reset | `witness_knowledge` fehlte in `SESSION_CHILD_TABLES`. Den Restore hatte ich in V66 als Sonderfall repariert, den Voll-Reset nicht. | Zeugenwissen steht in `SESSION_CHILD_TABLES` und wird mit den Facts entfernt. Der Sonderfall im Restore ist weg. |
| V66-03 Uploadkontext | `reset_session_uploads` löschte jeden Upload der Session, auch einen, auf den sich ein gespeicherter Fact stützt. | Ein Upload, der Quelle eines gespeicherten Facts ist, ist Evidenz, kein Kontext.<br>• Er bleibt angehängt (`keptAsSource`, Warnung `UPLOADS_KEPT_AS_SOURCE`).<br>• Der Kontext wird geleert (`focus`, `uploadRefs`), freie Uploads werden gelöscht. |
| V66-04 Upload löschen | `delete_upload` löschte ohne jede Prüfung. | Läuft unter dem Gesetz: Ist der Upload Quelle eines Facts, kommt 409 `DEPENDENCY_BROKEN` und nichts ändert sich. Ein freier Upload wird gelöscht wie bisher. |
| V66-05 Einwilligung (N3/N4) | **Teiltat:** Die Vollständigkeit zählte nur übrig gebliebene Wörter ab 4 Buchstaben. „und tu dir weh“ (nur kurze Wörter) galt als gedeckt.<br>**Bitte:** Ein einziges gemeinsames Wort mit der Bitte reichte (`names_matter`). „Ich breche deine Hand“ erfüllte „Darf ich deine Hand nehmen?“ über „Hand“. | **Eine Deckungsregel** (`parts_cover`) für Bitte, Erlaubnis und Ausnahme, im Reader und im Writer:<br>• Jeder Teil steht an seiner eigenen Stelle auf Wortgrenzen.<br>• Vor dem ersten Teil höchstens ein Wort (der Handelnde), zwischen zwei Teilen höchstens ein Bindewort, nach dem letzten nichts.<br>**Ganze Bitte** (`covers_request`):<br>• Jedes Wort ab 4 Buchstaben eines als erbeten gelesenen Teils steht in den eigenen Worten der Bitte oder in ihrer Zusammenfassung (gleicher Stamm oder Gegenwort). Die Namen der Beteiligten zählen nicht.<br>• Das gilt auch, wenn das Modell die Wirkung falsch als `social` liest. |
| V66-06 Komponenten | **z03/z04:** Zwei Komponenten mit denselben Worten banden beide die **erste** Stelle. Daraus wurden zwei Taten aus einem Satz, und der zweite Satz blieb Rede.<br>**z01/z02:** Die markierte Tat (`*…*`) bekam Ziel und Wirkung der **ersten** Komponente der Eingabe. | **Eigener Ort:** Jede Handlungskomponente bindet eine noch freie Stelle der Eingabe. Gibt es keine mehr, ist sie keine zweite Tat (`segment_bereits_gebunden`).<br>**Markierte Tat** (`marked_act_binding`, ein Weg für Avatar und Puppet):<br>• Sie nimmt die Komponente(n), die in den markierten Worten liegen.<br>• Liegt keine darin: keine validierte Wirkung, kein Ziel. |
| V66-07 Navigationsprüfung | Die Diagnose verlangte `NAV.length >= 12` und meldete die 7 Hauptpunkte als Fehler. 10 weitere stehen unter „Mehr“. | Die Prüfung fragt den Router: Jedes Ziel aus Hauptmenü und „Mehr“ muss eine registrierte Route sein. |
| V66-08 Ein-Klick-Reset | Chat-, Runtime-, Memory-, Upload- und Voll-Reset, Session löschen, Wiederherstellen und Upload löschen sendeten sofort. | Eine Rückfrage (`confirmReset`) mit einem gemeinsamen Wortlaut: was entfernt wird, was bleibt. Bei Nein wird nichts gesendet.<br>Das gilt in der Chat-Übersicht, im Labor, beim Snapshot und beim Upload. |

**Was das Gesetz abdeckt** (Audit7 §9 Nr. 1: Anlegen, Duplizieren, Import, Snapshot, Restore, Reset, Löschen):
- **Anlegen, Duplizieren, Import:**
  - Diese Wege prüfen seit V65Z/V66 vor dem Einfügen mit denselben Regeln (Writer und `_prevalidate_batch`).
  - In V67 unverändert. `test_v66_gegenproben` bleibt grün.
  - Im E2E hat jede neue Session, auch Import und Duplikat, 0 Zeilen außerhalb der Grenze (`grenze_neue.json`).
- **Snapshot erfassen:** Der Snapshot ist eine Kopie der Server-Erfassung (V66) und entfernt nichts.
- **Restore, alle Resets, Upload löschen:** unter `dependency_guard`, siehe die Tabelle oben.
- **Session löschen:**
  - Die Session geht mit allen Kindzeilen; das Zeugenwissen fällt über den Fremdschlüssel (deine Korrektur in Audit7).
  - Abhängigkeiten über Sessions hinweg gibt es nicht: Ein Upload ist nur Quelle seiner eigenen Session (V66, E02).

### Gegenproben und Tests (0 Modellaufrufe)
- **Deine zwei Skripte** (`independent_probes.py`, `side_probes.py`, nur Pfade als Argument):
  - **V66 wie bei dir:**
    - Chat-Reset: TurnTruth 1 → 0, der Fact nennt sie weiter, `FACT_SOURCE_INVALID`, turnIndex 777.
    - Voll-Reset: Zeugenwissen 1 → 1, `WITNESS_FACT_INVALID`.
    - Uploadreset und Upload löschen: Upload weg, der Fact bleibt, `FACT_SOURCE_INVALID`.
  - **V67:**
    - Chat-Reset: TurnTruth 1 → 1, Audit leer, turnIndex nicht aus dem Request.
    - Voll-Reset: Zeugenwissen 1 → 0.
    - Uploadreset: Upload bleibt, Audit leer.
    - Upload löschen: 409 `DEPENDENCY_BROKEN`, nichts geändert.
  - Die übrigen Proben (E01–E04, N05, `delete_session`) sind an beiden Ständen gleich.
- **Nachgebaut** (`probe_v66_05_06.py`, aus `pytest_prior_independent.log`):

  | Probe | V66 | V67 |
  |---|---|---|
  | N4 „Ich nehme deine Hand und tu dir weh“, nur der Handteil gelesen | `accepted` (Bitte) | `unknown`, `teile_unvollstaendig` |
  | N3 „Ich breche deine Hand“ als `social` | Bitte erfüllt, `accepted` | `unknown`, `teil_nennt_bitte_nicht` |
  | Ausnahme mit kurzer Zusatztat | innerhalb | ungeprüft, `teile_unvollstaendig` |
  | z01/z02: markiert „und schlage Kvle“ | `social`, Ziel Tammy | `strike`, Ziel Kvle |
  | z03: eine Stelle, zwei gleiche Komponenten | 2 Taten | 1 Tat, `segment_bereits_gebunden` |
  | z04: zwei Stellen | 2 Taten, ein Satz bleibt Rede | 2 Taten, keine Rede übrig |
- **`test_v67_gegenproben.py`, 20 Tests:**
  - Negativ und positiv, mit Rücklesen nach erneutem Öffnen der SQLite-Datei.
  - Am V66-Code: 19 rot, 1 grün. Grün ist die Positivkontrolle: Die erbetene Tat selbst wird weiter angenommen.
  - Kein älterer Test geändert.
- **Regression V66 gegen V67** (deine DB und Alt-DB):
  - 0 neu rot. Bestanden 615 → 635 je DB.
  - Die 50 vorbestehenden Fehler sind unverändert.
- **prepare-Bytevergleich:** 2 DBs, 33 Sessions, 0 abweichend.
- **TypeScript:** 616, gleiche Menge. **Build:** Exit 0, 42 Assets.
- **Altzeilen** (nur gelesen): deine DB 45 → 46, Alt-DB 41 → 42.
  - Neu ist genau `TURNINDEX_BEHIND_HISTORY` an `ses_3422…`: turnIndex 1, gespeicherte Historie bis Turn 2.
  - Die Session hat das alte V66-Verhalten beim Chat-Reset ausgelöst, wie dein Gutachten es beschreibt.
  - Gelistet, nicht umgeschrieben.
- **Endpaket frisch entpackt:**
  - 319 Tests grün (V65I, V65P–V67).
  - Laufzeitcode und Frontend gleich dem E2E-Endkandidaten. Anders sind nur SPS, README und Nachweise.
  - DB nach den Tests bytegleich.

### E2E (START.py, echter Provider, frisch entpackte Kandidaten)
- **Lauf 1** (Kandidat 1):
  - Alle Produktbefunde grün.
  - Ein Werkzeugfehler: Die Kette setzte die Session voll zurück, deren Upload der Browser danach löschen sollte. Damit war die Ablehnung im Browser nicht geprüft. Siehe `e2e_lauf1_befund/BEFUND.md`.
- **Lauf 2, Endkandidat** (Code gleich dem Endpaket):
  - **Pfadproben:** 5× 404, Asset und `/` 200.
  - **Browser** (Ablauf wie V65U–V66): Exit 0, Provider-Fehler zweimal voll bedient, Reload gleich. Bedienperson, Szenenauswahl und Diagnose wie V66.
  - **Kette A:** Hand `accepted` (`grenze_ausnahme`), Kuss `declined`. Sieben Taten → 7. 23 Facts, jeder Quellturn eine TurnTruth.
  - **Kette B:** Szenenübergang nur mit Auswahl, Direktrouten 404. Deine Altsession zeigt 8 Altzeilen, gelistet.
  - **Kette C:**
    - rechte Hand `declined`, linke Hand `accepted`;
    - Schlag auf die linke Hand `declined`;
    - „Ich schlage Freya.“ nicht validiert (`wirkung_ohne_gebundenes_ziel`);
    - „Ich breche dir die linke Hand.“: Die Wirkungsprüfung bestätigte keine Gewalt; ohne Körperwirkung, ohne Annahme.
  - **Kette D:**
    - Snapshot erfassen → weiter → Restore = Snapshot → Folgeturn 4 → 5;
    - Fremdblob ignoriert, MCC-Stempel 409;
    - andere Session gleich;
    - Duplikat der Altsession 39/39 Facts, 0 fehlende Quellturns.
  - **Kette E (V66-01 bis V66-04, über die Produktrouten):**
    - Upload `aushang.txt` eingelesen → 1 Fact mit Quelle. DELETE → 409 `DEPENDENCY_BROKEN`, Upload bleibt.
    - Uploadkontext-Reset → Quelle bleibt (`keptAsSource`), freier Upload gelöscht.
    - Chat-Reset mit `turnIndex: 777` im Request:
      - TurnTruths 2/2, Facts 3/3, Turns 3 → 1;
      - turnIndex 2/2, Warnung `KERNEL_OWNED_FIELDS_IGNORED:turnIndex`;
      - Folgeturn 3 = höchster Fact-Turn, 0 Altzeilen.
    - Voll-Reset (eigene Session): Zeugen 6 → 0, Facts 2 → 0, Avatar bleibt.
    - Freier Upload löschen → 200.
  - **Reset im Browser:**
    - Chat-Reset, Rückfrage **Nein** → nichts gesendet (Turns 10, TurnTruths 9, Facts 19, Zeugen 51).
    - **Ja** → Turns 10 → 1; TurnTruths 9, Facts 19, Zeugen 51, turnIndex 9 bleiben.
    - Voll-Reset → alles 0, Avatar bleibt.
    - Upload `aushang.txt` löschen, Rückfrage Ja → der Server lehnt ab, das Fehlerband zeigt `409 DEPENDENCY_BROKEN … nothing was changed`, der Upload steht weiter in der Liste (GET 200).
    - Diagnose: „7 + 10 (Mehr) Navigationsziele, 17 im Router“.
  - **Import im Browser:** gefälscht abgelehnt; God-Packung Nein → nichts, Ja → angenommen und gezählt; gültige Packung ohne Rückfrage.
  - **Snapshot im Browser:** Rückfrage mit Wortlaut; Erstellen → weiter → Wiederherstellen = Snapshot; andere Session gleich.
  - **Neustart:** 8 Sessions (Ketten A–F, Browser, zwei Importe) gleich der DB vor dem Neustart, je 0 Altzeilen. Der Quell-Upload ist noch da.
  - **Schreibgrenze aller 9 neuen Sessions:** 0 Zeilen (`grenze_neue.json`, dieselben Regeln wie der Writer).
  - **Isolation:**
    - 0 Altzeilen verändert außer deinem Profil (`avatarsByWorld`, `lastSessionId`).
    - Config bytegleich, keine Sicherung übrig.
  - **Server:** 6 `BrokenPipeError` im Seitenserver, wenn der Browser eine Verbindung schließt. Das gab es schon in V66.

### SPS-Gates (die in Audit7 roten; alle anderen wie in Audit7)

| Gate | Audit7 | V67 | Beleg |
|---|---|---|---|
| G1 Knowledge | ROT (V66-02) | TEILGRÜN | Voll-Reset und Restore nehmen das Zeugenwissen mit; Test, deine Probe, E2E Zeugen → 0 |
| G6 Persistence | ROT (V66-01..04) | TEILGRÜN | Kein Bedienweg lässt eine Zeile ohne Quelle; Rücklesen nach erneutem Öffnen und Neustart |
| G8 Writer-Reader | ROT | TEILGRÜN | Writer, `dependency_guard` und Diagnose lesen dieselbe Regel (`_boundary_rows`); im E2E 0 neue Zeilen außerhalb |
| G9 Turn-Composition | ROT (z01–z04) | TEILGRÜN | Ein Ort = eine Tat; markierte Tat mit eigener Bindung (Test, Probe). Die Zerlegung durch das Modell schwankt weiter |
| G10 Refusal/Acceptance | ROT (N3, N4) | TEILGRÜN | Eine Deckungsregel für Bitte, Erlaubnis und Ausnahme, im Reader und im Writer; live Hand ja, Kuss nein, rechte Hand nein, Schlag nein |
| G12 Product-Surface | ROT | TEILGRÜN | Rückfrage vor jeder destruktiven Aktion (Browser: Nein ändert nichts); Upload-Löschen sichtbar abgelehnt; Navigation am Router |
| G26 Datenrollen | ROT | TEILGRÜN | Ein Upload, auf den sich ein Fact stützt, ist Evidenz und bleibt; Quelle und Kontext getrennt |
| G27 Negativabnahme | ROT | TEILGRÜN | V66-01..08 negativ und positiv; deine zwei Skripte an V67 ohne Befund. Die älteren Prüfer-Tests fehlten, nachgebaut |
| G28 Writer-Reader-Vollprüfung | ROT | TEILGRÜN | Nach Reset und Upload-Löschen gleiche Gültigkeitslage in Writer, Diagnose, SQLite und nach Neustart |
| G29 Snapshot/Restore | TEIL | TEILGRÜN | Restore unter dem Gesetz; HTTP, Browser, Folgeturn, Neustart. Ohne Mehrprozess |
| G31 AMASTER-Vollprüfung | ROT | ROT | keine Gesamtabnahme |

### Offen / ROT
- **Keine Gesamtabnahme:** G2–G5, G7, G11, G13–G25 und G30 stehen wie in Audit7. SOURCE WORLD (G18–G23) ist nicht angefasst; ich habe keinen produktiven Source-Weg gebaut.
- **Ausnahme mit falschem Etikett:**
  - Eine schädliche Tat, die das Modell als `social` liest, fängt die Deckungsregel nur, wenn sie Worte außerhalb der Ausnahme hat.
  - Liest das Modell den Schaden gar nicht (live: „Ich breche dir die linke Hand“), bleibt die Tat ohne Körperwirkung und ohne Annahme.
  - Ob eine Tat Schaden ist, entscheidet weiter nur die Wirkungsprüfung des Modells; es gibt keine Wortliste.
- **Deine Session `ses_3422…`:** Ihr Turnzähler liegt hinter der Historie. Gelistet, nicht umgeschrieben (keine Migration).
  - Ein Chat-Reset oder ein Restore hebt ihn auf die Historie.
  - Ein normaler nächster Turn zählt weiter vom gespeicherten Zähler (1 → 2). Er bekommt also einmal dieselbe Nummer wie der alte Fact in Turn 2. Die Quelle bleibt richtig, denn sie hängt an der TurnTruth-ID, nicht an der Nummer. Nur die Reihenfolge nach Nummer ist an dieser Stelle doppelt.
  - Neue Fälle entstehen nicht mehr: Jeder Writer, der den Zähler setzt (Reset, Restore, Import), bindet ihn an die Historie.
- **Import mit Upload-Quellen:** Eine Packung, deren Facts Uploads nennen, trägt die Uploads nicht mit. Der Import nimmt solche Facts nicht als gültig an. Das ist Altbestand, hier nicht geändert.
- **Restore:** Der spätere Stand wird nicht automatisch gesichert. Die Rückfrage sagt das jetzt. Die MCC-Wiederherstellung schreibt weiter direkt (eigener, gezählter Weg).
- **Rückfrage:** `window.confirm` des Browsers. Screenreader, Tastatur und Android sind nicht geprüft (G30).
- **Ablehnung beim Upload-Löschen:**
  - Sie erscheint im allgemeinen Fehlerband („Speichern fehlgeschlagen: …“).
  - Der Text ist der technische Servertext auf Englisch, mit Fact-ID.
  - Sichtbar und richtig, aber nicht barrierearm formuliert.
- **Unverändert offen:**
  - Regex für den Ortswechsel im Regie-Client; Pronomen T32; Widerspruch-FP; Regie-FN;
  - I92 Cache-Index;
  - 616 TypeScript-Altfehler;
  - Android, Mehrprozess, keine echte Anmeldung.

### Modellaufrufe
- **Entwicklung V67: 0.** Gegenproben und Tests laufen ohne Modell.
- **E2E:** Lauf 1 144, Lauf 2 145 (Browser 99, Kette A 18, B 1, C 18, E 5, F 4).
- **Gesamt V67: 289.**
- **Betrieb:** unverändert. Kein neuer Modellaufruf, keine neue Lesung. Die Deckungsregel, die Ortsbindung und das Gesetz lesen nur, was schon da ist.

**STATUS: TEILGRÜN.**
- V66-01 bis V66-08 am Writer, Kernel und Reader grün, mit festen Tests, deinen Skripten und Rücklesen.
- Am frischen ZIP über Oberfläche und Produktrouten live gezeigt:
  - Chat-, Voll- und Uploadreset;
  - Upload löschen (abgelehnt) und Rückfrage;
  - Navigation;
  - Einwilligung.
- z01–z04 nur an Kernel und Writer: Live entscheidet das Modell über die Komponenten.
- G31 ROT. Keine Android- und keine AMASTER-Gesamtabnahme.

## SPS- UND AMASTER-GESAMTAUDIT AUDIT7 zu V66 · Vermerk (Eingang V67, 31.10.2026) – unverändert übernommen

Quelle: deine Nachricht zum Audit7 (Anhang vom 31.10.2026), Wortlaut unverändert. Weggelassen ist nur die erste Zeile mit der Denkzeit. Gutachten, Vorlesefassung und Nachweis-ZIP liegen unverändert in `scripts/v67_gegenproben/audit7/`.

```text
### MATRIX10 V66 – unabhängiger SPS- und AMASTER-Gesamtbericht

Prüfbasis: Original-V66, V65Z als Vergleich, AMASTER mit 94 Invarianten, SPS mit 31 Gates, verbindlicher Reparaturvertrag und bisherige Auditnachweise.

### 1\. Ergebnis der ersten unabhängigen Gegenproben

V66 enthält echte Verbesserungen. Die vollständige Produktabnahme ist aber weiterhin ROT.

Die folgenden Ergebnisse habe ich selbst am Originalcode mit separaten SQLite-Kopien reproduziert.

### Befund V66-01: Chat zurücksetzen zerstört die Herkunft von Fakten

Kritisch – bestätigt

Code: `repos.py`, `reset_session_chat`, Zeilen 2814–2861.

* Vor dem Zurücksetzen: 1 gültige TurnTruth und 1 zugehöriger SceneFact.

* Nach dem Zurücksetzen: TurnTruth gelöscht, SceneFact weiterhin gespeichert.

* Der SceneFact verweist jetzt auf eine nicht mehr vorhandene Quelle.

* Die Diagnose meldet `FACT_SOURCE_INVALID`.

* Zusätzlich akzeptiert die Funktion `turnIndex=777` direkt aus dem übermittelten Request, obwohl keine entsprechende Historie besteht.

AMASTER-Verletzung: §23, §34, §34.3, §68 I8/I31/I64/I87.

Ursache: Der Reset behandelt Chatzeilen, TurnTruth und kanonische Ereignisevidenz als unabhängig löschbar, obwohl ihre Herkunft miteinander verbunden ist.

### Befund V66-02: Vollständiger Session-Reset hinterlässt ungültiges Zeugenwissen

Kritisch – bestätigt

Code: `repos.py`, `reset_session_full`, Zeilen 2885–2937, und `_delete_session_children`, Zeilen 1620–1624.

* Vorher: 1 SceneFact und 1 gültiger Zeugenwissenseintrag.

* Nachher: 0 SceneFacts, aber weiterhin 1 Zeugenwissenseintrag.

* Dieser verweist auf ein gelöschtes Ereignis.

* Die Diagnose bestätigt `WITNESS_FACT_INVALID`.

* Auch nach erneutem Öffnen der Datenbank bleibt der Fehler vorhanden.

AMASTER-Verletzung: §39, §68 I6/I7/I10/I64/I87.

Ursache: `witness_knowledge` gehört nicht zur zentralen Liste der beim Reset gelöschten Session-Kinder.

Das ist besonders relevant, weil die V66-Reparatur genau dieses Problem beim Snapshot-Restore bereits berücksichtigt, aber nicht beim normalen Reset.

### Eine frühere Aussage muss korrigiert werden

Beim tatsächlichen Löschen einer Session werden ihre Zeugenwissenseinträge durch den SQLite-Fremdschlüssel vollständig entfernt. Die frühere pauschale Behauptung, auch das normale Session-Löschen hinterlasse dieses Wissen, trifft für den geprüften V66-Pfad nicht zu.

Der nachgewiesene Fehler betrifft den vollständigen Reset, nicht die vollständige Session-Löschung.

### 2\. Weitere Nebenbefunde

### Befund V66-03: Upload löschen zerstört gespeicherte Quellenverweise

Bestätigt

Code: `repos.py`, `delete_upload` (4123–4130) und `reset_session_uploads` (2996–3055).

Beide Wege sind über das Frontend erreichbar.

Meine zwei getrennten SQLite-Gegenproben ergaben dasselbe:

* Ein gültiger SceneFact besitzt einen Upload als Quelle.

* Der Upload wird gelöscht beziehungsweise zurückgesetzt.

* Der SceneFact bleibt gespeichert, verliert aber seine gültige Herkunft.

* Die Diagnose meldet danach `FACT_SOURCE_INVALID`.

AMASTER: §34.1, §34.3, §68 I63/I64/I87.

Der Fehler ist systematisch: Die Löschfunktionen prüfen die Abhängigkeiten anderer Daten nicht vor dem Löschen.

### Befund V66-04: Handlungserkennung und Einwilligung bleiben unvollständig

Die unabhängigen älteren Gegenproben wurden erneut ausgeführt.

### 9

fehlgeschlagen

### 11

bestanden

Eine fehlgeschlagene Probe erwartet eine vollständig entfernte Handlung, obwohl V66 sie bereits mit `effectValid=False` sperrt. Eine weitere betrifft eine absichtlich entfernte Funktion. Diese beiden Ergebnisse sind nicht als neue Sicherheitsdefekte zu zählen.

Die übrigen Fehlschläge enthalten weiterhin konkrete Probleme mit mehrfachen Handlungskomponenten, der vollständigen Bindung einer Bitte und der Zuordnung von Handlungszielen.

Besonders wichtig: Eine absichtlich unvollständige Modelllesung zur Handlung „Ich nehme deine Hand und tu dir weh“ kann weiterhin eine unzulässige Zustimmung bewirken. Die neue Schadenssperre greift nur bei entsprechend erkannter Wirkungsart.

Damit ist AMASTER §34.1/§36.5 nicht vollständig erfüllt.

### 3\. Was V66 tatsächlich repariert hat

Diese Verbesserungen habe ich mit eigenen Datenbank-Gegenproben bestätigt:

* Snapshot: Manipulierte Snapshots werden abgelehnt.

* Quellen: Uploads aus fremden Sessions werden nicht als Herkunft akzeptiert.

* Duplikate: Fakten mit ungültiger TurnTruth werden bei der geprüften Kopie nicht übernommen.

* God-Import: Ohne ausdrückliche Autoritätsannahme wird der geprüfte Import abgelehnt.

* Provenienz: Eine bloße Ursache reicht nicht mehr als alleiniger Quellnachweis.

Das sind bestandene Teilprüfungen, keine vollständige Systemabnahme.

### 4\. SPS-Gesamtauswertung

### 10

Gates ROT

### 12

Teilweise geprüft

### 9

Offen

Keines der 31 SPS-Gates ist vollständig abgenommen.

### AMASTER §68 – alle 94 Invarianten

| Einstufung                                                | Anzahl |
| --------------------------------------------------------- | ------ |
| Nachgewiesene Vertragsverletzung                          | 13     |
| Teilweise geprüft oder aus früherem Audit fortgeschrieben | 62     |
| Noch offen                                                | 19     |

Die vollständige Liste enthält jede Invariante, ihre Abhängigkeiten und den Prüfstatus. Nicht alle 94 wurden in diesem Lauf neu getestet.

### 5\. Weitere Nebenbefunde

* Frontend-Diagnose: Die Navigationsprüfung zählt nur sieben Hauptpunkte und übersieht zehn weitere Menüeinträge.

* Reset-Bedienung: Im geprüften Frontend-Code fehlt vor den destruktiven Resetaufrufen eine eigene Bestätigung.

* SOURCE WORLD: G18–G23 sind weiterhin nicht vollständig abgenommen.

* TypeScript: Laut Entwicklungsprotokoll weiterhin 616 Altfehler.

* Live-Abnahme: Android, Mehrprozess, Screenreader und ein eigener vollständiger Browser-/Provider-E2E fehlen.

Bei den eigenen Testläufen bestanden 23 V66-Tests; vier HTTP-Tests waren wegen fehlendem Flask nicht ausführbar. Von 20 älteren unabhängigen Gegenproben bestanden elf und neun schlugen fehl. Nicht jede Fehlmeldung bedeutet automatisch einen Produktdefekt.

### 6\. Technische Gesamtdiagnose

Die entscheidende Ursache ist nun genauer eingegrenzt:

V66 schützt das Anlegen von Fakten und Quellen besser. Beim späteren Zurücksetzen und Löschen werden diese Abhängigkeiten jedoch nicht durchgehend geprüft.

Dadurch können gültige Daten nachträglich zu widersprüchlichem Weltzustand werden. Die Diagnose erkennt das erst, nachdem die falschen Zustände bereits gespeichert sind.

Notwendige Reparatur: Eine gemeinsame, atomare Abhängigkeitsprüfung für Anlegen, Ändern, Importieren, Duplizieren, Snapshot, Wiederherstellen, Zurücksetzen und Löschen. Danach müssen Handlungen und Einwilligungen erneut über die vollständige Kette geprüft werden.

### 7\. Fertiger Gesamtbericht

Vollständiges SPS-/AMASTER-Gutachten

Gesamtbericht als TXT

Gesamtbericht als Markdown

Vorlesefassung

Einfach lesbare TXT-Fassung

Unabhängiges Audit-7-Nachweispaket

ZIP mit Prüfskripten, Protokollen und Befundmatrix

Das Nachweis-ZIP wurde auf Integrität geprüft. Die Originaldatenbank und die sieben Logs wurden nicht verändert.

Endurteil: V66 ist technisch verbessert, aber die SPS- und AMASTER-Gesamtabnahme bleibt ROT. Ein erneuter isolierter Patch würde das Grundproblem nicht zuverlässig beseitigen.
```

## DECKBLATT · V66 · AMASTER-Restprüfung Audit6 zu V65Z (N05) und Audit5 (E01–E06): Snapshot nur aus eigener Server-Erfassung, Umschlag an die Historie gebunden, Import mit Herkunft und ausdrücklicher Annahme, Abhängigkeiten, Ziel, Einwilligung (Claude) · 31.10.2026

**Verbindlich:**
- `2_7master.txt`:
  - §6.2 Z. 247–279 (Z. 262 fail-closed an kritischer Grenze, Datenrolle bestimmen);
  - §23 Z. 1028 ff. (TurnTruth und Eingangsbindung), §24.1 Z. 1081 ff. (Identität gebunden), §24.2 Z. 1100–1118 (Validierung vor dem Writer);
  - §34 Z. 1736 ff. (SceneFact bindet Quellturn), §34.1 Z. 1774 ff., §34.2 Z. 1819 ff. („Abhängige Effects müssen ihre Abhängigkeiten ausdrücklich tragen“, `cause_fact_id`), §34.3 Z. 1829 ff. (historische Evidenz nicht heimlich löschen);
  - §36.5 Z. 1945–1975 (Zustimmung an die konkrete Handlung gebunden);
  - §46 Z. 2521 ff., §46.2 Z. 2547 („Actor und Target werden ausdrücklich gebunden“);
  - §64 Z. 3238–3254 (Snapshots, kontrollierter Import, Wiederherstellung ohne Fremdüberschreibung);
  - §68 Nr. 30 Z. 3379, Nr. 48 Z. 3397, Nr. 64 Z. 3413, Nr. 87 Z. 3436 (unklare Datenrolle → keine kanonische Wirkung), Nr. 91 Z. 3440 (kein Diagnose-Sonderwrite);
  - G29 Z. 4252–4256 (Snapshot/Restore Gate).
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6, §16.

**Eingang:** AMASTER-Restprüfung Audit6 zu V65Z mit deinen Nachweisen; Audit5. Vermerk unten, unverändert.
- Deine Snapshot-Skripte (`repro_snapshot_envelope`, `repro_snapshot_turnindex`) lagen bei. Sie laufen gegen V65Z wie bei dir und gegen V66 ohne Befund.
- Die Skripte zu E01–E06 lagen nicht bei. Ich habe sie aus der Befundtabelle nachgebaut. Ob sie genau deine Fälle treffen: **UNKLAR**.

**Basis:** mein V65Z-ZIP (SHA256 `3258c271…`). DB und Logs bytegleich, keine Migration.

### Entscheidungen, die das Audit ausdrücklich verlangt
- **Vertrauensklasse eines Snapshots:** Wiederherstellbar ist nur ein Stand, den **dieser Server** aus seiner gespeicherten Session erfasst hat (Stempel `erfasst` plus Inhalts-Hash). Alles andere ist Archiv: ein Snapshot aus einer MCC-Datei, ein Snapshot einer früheren Version, ein Snapshot mit geändertem Inhalt.
- **Historische Backups:** Archiv-Snapshots werden weder gelöscht noch umgeschrieben. Sie bleiben in der Liste und sind als „nur Archiv“ markiert. Deine DB hat heute keinen Session-Snapshot, nur 9 Welt-/Figurensicherungen; diese sind unberührt.
- **Restore-Semantik:** Rückkehr genau zum erfassten Stand derselben Session: Umschlag, alle Kinder und das Zeugenwissen. Der Umschlag ist an die erfasste Historie gebunden. Andere Sessions und User bleiben unberührt. Der spätere Stand wird ersetzt (bewusste Wiederherstellung, G29). Er wird nicht automatisch mitgesichert. Wer ihn behalten will, legt vorher einen Snapshot an.
- **Legacy-Quarantäne:**
  - **Duplikat:** Altzeilen, die die heutige Grenze nicht bestehen, werden nicht kopiert. Jetzt gilt das auch für die Zeilen, die von ihnen abhängen. Alle werden gelistet.
  - **Restore einer eigenen Erfassung:** Solche Zeilen kommen so zurück, wie sie erfasst waren, und werden gezählt (`LEGACY_ROWS_RESTORED`). Sonst wäre der Snapshot einer Altsession nicht wiederherstellbar. V65Z lehnte so einen Restore ab.
  - **MCC-Wiederherstellung:** unverändert gezählt.
- **Import-Vertrauensklasse:** `fremdimport` mit Herkunft (von, am, durch), vom Server gestempelt. God-/Regie-Autorität aus einer Datei nur nach ausdrücklicher Annahme durch den Eigentümer.

### Wurzel → Änderung (vorhandene Owner, keine neue Route, keine Tabelle, keine Wortliste)

| Befund | Wurzel am V65Z-Code (gegengeprüft) | Änderung |
|---|---|---|
| N05 Snapshot mit Fremdinhalt | `create_snapshot` (POST `/api/snapshots`) mischte die Umschlagfelder aus dem `session`-Blob des Aufrufers in die Server-Erfassung (übersprungen wurden nur die Kindlisten). `restore_snapshot` schrieb **jeden** gespeicherten Snapshot direkt als kanonischen Umschlag (`UPDATE sessions`), ohne zu prüfen, woher er kam. Einziger Aufrufer im Frontend war die Diagnose-Probe „Diagnose-Stand“. Deine Probe: Intent und SceneState fremd, turnIndex 777, offene Eingabe ohne TurnTruth | **Ein Snapshot-Writer** (`_server_snapshot`) für beide Routen. Er erfasst die gespeicherte Session und stempelt `erfasst` {durch: server, weg, am, inhaltSha256}. Ein `session`-Blob oder Stempel des Aufrufers wird ignoriert (`CLIENT_SESSION_IGNORED`). **Restore** nur aus einem Snapshot mit Stempel und passendem Inhalts-Hash, sonst 409 `SNAPSHOT_NOT_SERVER_CAPTURED` / `SNAPSHOT_CONTENT_CHANGED`. Der Snapshot bleibt dann als Archiv stehen (nichts gelöscht). **Umschlag an die Historie gebunden** (`bind_session_envelope`): turnIndex = höchster gespeicherter Turn; eine offene Eingabe nur, wenn sie eine TurnTruth dieser Historie ist, sonst samt Versuch verworfen; Runtimes nur von Figuren der Welt, sonst 409. Felder, die der Snapshot nicht hat, werden entfernt (kein Mischstand). Zeugenwissen gehört zum Stand und wird mit wiederhergestellt (vorher blieben spätere Zeilen auf nicht mehr vorhandene Facts stehen). Zeilen der Erfassung außerhalb der heutigen Grenze kommen so zurück, wie sie erfasst waren, und werden gezählt (`LEGACY_ROWS_RESTORED`). Ein Snapshot aus einer MCC-Datei verliert den Stempel → nur Archiv. Diagnose-Probe nur lesend. Im Chat steht ein nicht erfasster Snapshot als „nur Archiv“ ohne Wiederherstellen-Knopf |
| E01 abhängiger Fact trotz Quarantäne | Die Quellen einer Speicherung zählten **alle** TurnTruths und SceneFacts desselben Speicherns, bevor sie geprüft waren. Im Duplikat wurde die Alt-TurnTruth zurückgehalten, der Fact, der sie nennt, aber kopiert (1 Fact, 0 TurnTruths) | `_prevalidate_batch`: Quelle ist nur, was gespeichert ist oder in derselben Speicherung **selbst** die Grenze besteht. Erst die TurnTruths, dann die Facts, bis keiner mehr wegfällt (ein Fact, der einen weggefallenen Fact nennt, fällt mit). Im Duplikat werden abhängige Zeilen mitgelistet (`LEGACY_ROWS_NOT_COPIED`), nicht kopiert |
| E02 Upload einer anderen Session | Die Uploads einer Session wurden per Textsuche im Upload-JSON gefunden (`json LIKE '%<id>%'`). Ein Upload von B, der A's ID erwähnt, galt als Quelle von A | Die Spalte `uploads.session_id` entscheidet |
| E03 selbsterklärte God-Autorität im Import | Der Import prüfte nur die formale Rollenkonsistenz. God-TurnTruth, God-Fakt und God-Fact aus der Datei wurden ohne Kennzeichnung übernommen; das Audit zählte 0 | **Vertrauensklasse und Herkunft:** Jede importierte Zeile bekommt `importiert` {vertrauen: fremdimport, von, am, durch}, gestempelt vom Server, nie aus der Datei. **Ausdrückliche Annahme:** God-/Regie-Autorität aus einer Datei hat dieser Server nicht erfasst. Ohne `autoritaetAnnehmen` → 409 `IMPORT_AUTHORITY_UNACCEPTED`, nichts gespeichert. Die Oberfläche fragt mit dem Grund des Servers nach; Nein → nichts importiert. Mit Ja: die Zeilen tragen zusätzlich `autoritaet: vom Eigentuemer angenommen`, Warnung `IMPORTED_AUTHORITY_ACCEPTED:n`. Audit und Diagnose zählen beides. Der Umschlag des Imports ist an seine Historie gebunden (turnIndex, keine offene Eingabe) |
| E04 Ursache als einzige Herkunft | `_check_sources` verlangte nur **irgendeine** genannte Quelle; `cause_fact_id` oder `responds_to_fact_id` allein reichte | Ein Fact braucht einen Quellturn oder einen Upload dieser Session. Ursache und beantworteter Fact sind Herkunft **zusätzlich**. Der Kernel schrieb selbst eine solche Zeile: Lebenszyklus „fulfill“ mit `sourceTurnId=None`. Sie trägt jetzt den Quellturn ihrer Aussage; „disclose“ nimmt ihn ebenso über `fact_provenance`. In deiner DB stehen 2 alte „disclose“-Zeilen ohne Quellturn; sie sind jetzt als Altzeilen gezählt (43 → 45; Alt-DB 40 → 41). `fact_provenance` gibt auch den Upload einer Ursache weiter. Beziehung und Zeugenwissen behalten ihre eigenen Herkunftsregeln |
| E05 unbekanntes Ziel | `bind_input_components` vermerkte „ziel_nicht_anwesend_oder_unbekannt“, ließ die Wirkung aber gültig (`strike`, `effectValid True`, Ziel leer). Die Regie hatte die Regel „Körperwirkung ohne Zielperson“, die Eingabe nicht | Eine Wirkung auf eine Person, deren Ziel die Eingabe nicht bindet, ist nicht validiert (`wirkung_ohne_gebundenes_ziel`). Eine Körperwirkung ohne Zielperson ist nicht validiert (`koerperwirkung_ohne_zielperson`). Eine Konstante (`BODY_EFFECTS_NEED_TARGET`) für Eingabe und Regie. Ortswechsel und Taten ohne Wirkung brauchen keine Person |
| E06 Seite, Kompositum, Spanne, Verletzung | Der Anker verglich nur das Kopfwort: „meine linke Hand“ deckte „deine rechte Hand“; auf der verbietenden Seite galt der Wortstamm („Schultertasche“ für „Schulter“). Wörtlichkeit war Teilzeichenkette („deine Hand“ in „Handtasche“). Eine Erlaubnis zum Halten nahm „Ich breche dir die Hand“ an | **Attribut:** Aus dem Zitat der Einschränkung selbst: Kopf (letztes Wort), Bestimmungsplatz (erstes Wort ab 4 Buchstaben), Attribute dazwischen. Erlauben verlangt Kopf **und** jedes Attribut (im anderen Mund: „meine“ = „deine“, gleiche Buchstaben nach dem ersten). Ein anderes Attribut an derselben Stelle ist kein Treffer der Grenze. Zwei Einschränkungen sind gleich nur bei gleichem Kopf und gleichen Attributen. **Ganzes Wort:** Ein Treffer der Grenze verlangt das Wort selbst, kein Kompositum. Das Veto gegen Annahme bleibt beim Stamm. **Wortgrenzen** für Teile, Beleg und Segment (`segment_wortgrenze`). **Schaden:** Eine validierte Wirkung `strike`/`restrain` wird durch keine Berührungs-Erlaubnis, Ausnahme oder Bitte angenommen. Unter einer Grenze → abgelehnt, sonst unbekannt, sichtbar `schaden` |

### Gegenproben und Tests (0 Modellaufrufe)
- **Deine zwei Snapshot-Skripte:** V65Z: Intent und SceneState fremd, turnIndex 777, offene Eingabe ohne TurnTruth. V66: nichts davon (`proben/repro_snapshot_*_auf_v65z.log` / `_auf_v66.log`).
- **Nachgebaute Gegenproben N05, E01–E06** (`probe_e01_e06.py`): V65Z reproduziert alle; V66 wehrt alle ab.
- **`test_v66_gegenproben.py`, 27 Tests**, negativ und positiv, mit Rücklesen nach erneutem Öffnen der SQLite-Datei. Am V65Z-Code: 25 rot, 2 grün (Positivkontrollen: sauberes Duplikat, gebundenes Ziel und Ortswechsel).
- **Ältere Tests umgestellt, nicht abgeschwächt:** nur `test_A08_the_client_import_is_one_request` (V65Z). Ein Request je Entscheidung; der zweite erst nach dem Ja des Eigentümers.
- **Regression V65Z gegen V66** (deine DB und Alt-DB): 0 neu rot. Bestanden 588 → 615 je DB. Die 50 vorbestehenden Fehler sind unverändert; darunter die 18, die dein Audit als „historische Tammy-Session fehlt“ führt.
- **prepare-Bytevergleich:** 2 DBs, 33 Sessions, 0 abweichend.
- **TypeScript:** 616, gleiche Menge. **Build:** Exit 0, 42 Assets.
- **Endpaket frisch entpackt:**
  - 299 Tests grün (V65I, V65P–V66);
  - Laufzeitcode und Frontend gleich dem E2E-Endkandidaten; anders sind nur SPS, README, Nachweise und ein Test (Altzeilen beim Restore);
  - DB nach den Tests bytegleich.
- **Altzeilen** (nur gelesen): deine DB 43 → 45, Alt-DB 40 → 41. Neu sind genau die alten „disclose“-Zeilen ohne Quellturn (E04).

### E2E (START.py, echter Provider, frisch entpackte Kandidaten)
- **Lauf 1** (Kandidat 1): Befunde in `e2e_lauf1_befund/BEFUND.md`. Ein Produktbefund kam beim Durchsehen von `restore_snapshot` während des Laufs dazu: Das Zeugenwissen blieb beim Restore stehen. Behoben. Dazu zwei Fehler in meinen Werkzeugen.
- **Lauf 2, Endkandidat** (Code gleich dem Endpaket):
  - **Pfadproben:** 5× 404, Asset und `/` 200.
  - **Browser** (Ablauf wie V65U–V65Z): Exit 0, Provider-Fehler zweimal voll bedient, Reload gleich.
  - **Kette A** (wie V65Z): Hand `accepted` (`grenze_ausnahme`), Kuss `declined`. Sieben Taten → 7. 23 Facts, jeder Quellturn eine TurnTruth.
  - **Kette B:** Szenenübergang nur mit Auswahl; Direktrouten 404; erfundene Beziehung 422.
  - **Kette C (E05/E06):**
    - Grenze für jede Berührung, dann „Du darfst meine linke Hand halten.“
    - „Ich halte deine rechte Hand.“ → `declined`; „Ich halte deine linke Hand.“ → `accepted`.
    - „Ich schlage dir auf die linke Hand.“ (Gewalt bestätigt) → `declined`, Teil außerhalb.
    - „Ich schlage Freya.“ → Wirkung **nicht validiert** (`wirkung_ohne_gebundenes_ziel`), obwohl die Wirkungsprüfung Gewalt bestätigte.
    - „Ich breche dir die linke Hand.“: Die Wirkungsprüfung bestätigte Gewalt nicht. Die Tat lief ohne Körperwirkung durch, ohne Annahme.
  - **Kette D (N05/G29, E01):**
    - Snapshot über die UI-Route erfasst (Stempel, Hash passt). Session weiter (turnIndex 3 → 4).
    - Snapshot mit Fremdblob → `CLIENT_SESSION_IGNORED`; er ist eine normale Server-Erfassung.
    - Restore → turnIndex 3, Facts und TurnTruths gleich dem Snapshot.
    - MCC-Datei mit selbst berechnetem Stempel → Stempel nicht übernommen, Restore 409 `SNAPSHOT_NOT_SERVER_CAPTURED`.
    - Folgeturn liest den wiederhergestellten Stand (4 → 5). Andere Session unverändert.
    - Duplikat deiner Altsession: 8 Altzeilen gelistet, 39/39 Facts, 0 fehlende Quellturns.
  - **Bedienperson:** wie V65Z.
  - **Import im Browser (E03):**
    - gefälscht → abgelehnt, 22 → 22;
    - God-Packung, Rückfrage **Nein** → abgelehnt (`IMPORT_AUTHORITY_UNACCEPTED`), 22 → 22;
    - **Ja** → neue Session, 3 Zeilen `autoritaet: vom Eigentuemer angenommen`, alle 138 Zeilen `fremdimport`, turnIndex 9 = Historie;
    - gültige Packung ohne Autorität → ohne Rückfrage, gekennzeichnet.
    - Diagnose-Probe nur lesend: „Session-Stände 3 (vom Server erfasst 2, nur Archiv 1)“.
  - **Snapshot im Browser (G29):** „Erstellen“ → Stempel `server`; Session weiter; „nur Archiv“ sichtbar ohne Knopf; „Wiederherstellen“ → turnIndex, Facts, TurnTruths wie im Snapshot; andere Session gleich; keine Fehler.
  - **Neustart:** sechs Sessions gleich dem gespeicherten Stand; 3 erfasste + 1 Archiv-Snapshot.
  - **Isolation:** 0 Altzeilen verändert außer deinem Profil (`lastSessionId`, Avatarwahl). Config bytegleich, keine Sicherung übrig.

### SPS-Gates (nur die, die V66 berührt; alle anderen wie in Audit6)

| Gate | Audit6 | V66 | Beleg |
|---|---|---|---|
| G6 Persistence | TEIL (N05) | TEILGRÜN | Restore nur aus Server-Erfassung; SQLite-Rücklesen und Neustart gleich |
| G7 Isolation | ROT (E02) | TEILGRÜN | Upload über `uploads.session_id`; Isolation E2E; keine Mehrbenutzer-Abnahme |
| G9 Turn-Composition | ROT (E05, E06) | TEILGRÜN | unbekanntes Ziel nicht validiert (Test + live); Wortgrenze im Segment; Zerlegung des Modells schwankt weiter |
| G10 Refusal/Acceptance | ROT (E06) | TEILGRÜN | Seite/Attribut, ganzes Wort, Wortgrenzen, Schaden (Tests); live rechte/linke Hand und Schlag richtig |
| G26 Datenrollen | ROT (N05) | TEILGRÜN | Snapshot-Inhalt hat eine Rolle (Server-Erfassung oder Archiv); Import `fremdimport`; Diagnose ohne Schreibweg |
| G27 Negativabnahme | ROT | TEILGRÜN | N05 und E01–E06 negativ und positiv abgewehrt; die Prüfer-Skripte zu E01–E06 fehlten |
| G29 Snapshot/Restore | ROT (N05) | TEILGRÜN | jedes Glied gezeigt: Erfassen (UI) → weiter → Restore (UI) → andere Session unverändert → Folgeturn liest den Stand → Neustart. Der Folgeturn lief über die God-Route, nicht über die Chat-Eingabe |
| G31 AMASTER-Vollprüfung | ROT | ROT | keine Gesamtabnahme |

### Offen / ROT
- **Keine Gesamtabnahme:** G1–G5, G8, G11–G25, G28, G30 wie in Audit6. SOURCE WORLD (G18–G23) nicht angefasst.
- **E06, Grenzen der Struktur:**
  - Das Attribut wird nur erkannt, wenn das Zitat einen Bestimmungsplatz hat („meine linke Hand“). „die linke Hand“ und „linke Hand“ behandeln Seite und Bestimmung wie bisher; das ist eine Lücke.
  - Für die andere Person gilt nur das Gegenwort mit gleichem Rest („meine“/„deine“). „ihre Hand“ oder „Maras Hand“ deckt eine eingeschränkte Erlaubnis darum nicht: fail-closed, unbekannt statt angenommen.
- **E06 Schaden:** Er entscheidet nur, wenn die Wirkungsprüfung des Modells Gewalt/Fesseln bestätigt. „Ich breche dir die Hand“ bestätigte sie live nicht. Eine gewünschte Fesselung („Darf ich dich fesseln?“ – „Ja“) bleibt unbekannt, bis eine Bitte ihre eigene Wirkungsklasse trägt.
- **E05:** Ein vom Modell ausgelassenes Ziel bei „dich“ ohne gebundenen Adressaten bleibt ohne Körperwirkung (fail-closed).
- **Restore:** Der spätere Stand wird nicht automatisch gesichert (siehe Entscheidungen). Die MCC-Wiederherstellung schreibt Sitzungen einer Sicherung weiter direkt (eigener, gezählter Weg). Nur ihre Snapshots sind jetzt Archiv.
- **Gefunden, nicht angefasst:** Beim Löschen und Zurücksetzen einer Session bleibt ihr Zeugenwissen stehen (`witness_knowledge` fehlt in `SESSION_CHILD_TABLES`). Das ist Altbestand außerhalb dieses Auftrags. Repariert ist nur der Restore.
- **I92 Cache-Index (N04):** nicht angefasst (Negativliste KnowledgeGraph/AutoLearn).
- **Unverändert offen:** Regex für den Ortswechsel im Regie-Client; Pronomen T32; Widerspruch-FP; Regie-FN; 616 TypeScript-Altfehler; Android; Mehrprozess; keine echte Anmeldung.

### Modellaufrufe
- **Entwicklung V66: 0** (Gegenproben und Tests ohne Modell).
- **E2E:** Lauf 2 (Endkandidat) 127, Lauf 1 133.
- **Gesamt V66: 260.**
- **Betrieb:** unverändert. Kein neuer Modellaufruf, keine neue Lesung. Der Import kann einen zweiten Serveraufruf auslösen, nur nach deinem Ja.

**STATUS: TEILGRÜN.**
- N05 und E01–E06 am Writer/Kernel/Reader grün, mit festen Tests und Rücklesen.
- N05/G29, E01, E03, E05 und E06 live über Oberfläche und Produktrouten am frischen ZIP gezeigt.
- E02 und E04 nur am Writer: Es gibt keine Route mehr, über die ein Fact eine freie Quelle bekommt.
- Ein eigener Fehler im Restore (Zeugenwissen) im Lauf 1 gefunden und behoben.
- G31 ROT. Keine Android- und keine AMASTER-Gesamtabnahme.

## AMASTER-RESTPRÜFUNG AUDIT6 zu V65Z · Vermerk (Eingang V66, 31.10.2026) – unverändert übernommen

Quelle: dein Dokument `MATRIX10_V65Z_AMASTER_RESTPRUEFUNG_AUDIT6_20261031.md` (Anhang vom 31.10.2026), unverändert. Es hat keine Zeile mit der Denkzeit. Den Wortlaut deiner Begleitnachricht habe ich nicht mehr vollständig im Arbeitskontext. Deshalb steht hier das Dokument, nicht die Nachricht. Nachweis-ZIP, Vorlesefassung und Audit5 liegen unverändert in `scripts/v66_gegenproben/audit6/`.

```text
# Matrix10 V65Z - AMASTER-Restpruefung AUDIT6 - 31.10.2026

## Auftrag, Grundlage, Grenzen

Unabhaengige Nachpruefung der 56 im Audit5 offenen und der 29 nur teilweise geprueften AMASTER-Invarianten sowie aller zuvor offenen oder teilgeprueften SPS-Gates G1-G31. Grundlage: ORIGINAL V65Z ZIP, originaler `2_7master.txt`, SPS-Master, Kettenvertrag, Audit5. Keine Produktdatei wurde umgeschrieben. Alle neuen Schreibproben liefen in temporaeren SQLite-Kopien.

**Wichtig:** Ein bestandener Unit-/Repo-Test ist kein Gate-Abschluss nach AMASTER §71.0.5. Dieses Audit meldet weiterhin keinen vollstaendigen Gate-PASS; SOURCE WORLD und volle Browser-/Provider-/Android-/Mehrprozess-Abnahme sind nicht vorgetaeuscht.

## A. Wichtigster neuer Befund N05 - Snapshot schreibt ungepruefte kanonische Zustandsfelder

1. `repos.py:create_snapshot`, etwa Z.4565-4595, akzeptiert `body.session` und kopiert dessen Werte fuer fast alle nicht-kindbezogenen Session-Felder in den als serverseitig vertrauenswuerdig gespeicherten Snapshot. Quelle: Aufrufer der Produkt-API `POST /api/snapshots`.
2. `repos.py:restore_snapshot`, etwa Z.4597-4656, uebernimmt u. a. `runtimes`, `sceneState`, `turnIndex`, `pendingInputTurnId` und `pendingInputAttempt` aus diesem Snapshot direkt in `sessions.json`, ohne TurnTruth-/Effect-/Authority-Grenze. Danach liest `get_session` die Werte wieder.
3. Negative SQLite-Probe: neue Session mit 0 TurnTruths und 0 SceneFacts, Snapshot mit fremder Runtime-Intent-Kennung und `sceneState`-Marker, Restore, Verbindung neu geoeffnet: beide Marker noch vorhanden. `currentState.auditMarker` wurde im Rueckleser **nicht** uebernommen (positiver Teilbefund).
4. Zweite Probe: `turnIndex=777` und `pendingInputTurnId=tt_nonexistent_audit` ebenfalls angenommen und nach Wiedereroeffnen vorhanden, bei 0 Turns und 0 Facts. Damit ist ein ungueltiger Ablaufzustand ueber den API-Writer herstellbar.
5. Ein Produkt-/Browser-HTTP-Lauf ist nicht erfolgt. Die Flask-Abhaengigkeit fehlt im lokalen Pruefcontainer; die Route ist in `app.py` und die Funktion `apiCreateSnapshot` im Frontend aber erreichbar. **G29 ROT, I87 ROT; I91 ROT bezogen auf privilegierten Restore-Sonderwrite.**

## B. Zusaetzlich erfolgreich getestete Teilstrecken

| Code | Strecke | Ergebnis | Abnahmegrenze |
|---|---|---|---|
| N01 | G13 Foreground mit 16 gespeicherten Zielen | 16 gespeichert, 0 aktiv, 16 im Background, Reader read-only | Kein kompletter Figuren-/Wissens-/Objektfall |
| N02 | G14 deferred-Engagement | Keine Reaktivierung durch blosses Wiederlesen | Neues Ereignis/AVERSION-Endtest offen |
| N03 | G17 Review zu Stamm-CoreFacts | Ablehnung aendert Stamm nicht; `accepted` schreibt nach SQL-Restart | Kein Frontend-/Upload-Mode-A-E2E |
| N04 | I92 Cache-Index | Vergifteter Suchindex liefert falschen Treffer, eigentlicher Dokument-Owner unveraendert | Auswirkung auf alle semantischen Reader nicht getestet |
| T01 | Goal/Lifecycle/Foreground Tests | 40 bestanden, 5 nur wegen fehlender historischer DB-Session | Kernel-/Repo-Tests |
| T02 | Koerper/Regie/Relation/Folgeturn Tests | 117 bestanden, 3 ohne installiertes Flask nicht ausfuehrbar | Kernel-/Repo-Tests |
| T03 | Praesenz/TurnTruth/Action/Referent Tests | 73 bestanden, 6 nur wegen historischer Fixture, 1 skipped | Kernel-/Repo-Tests |
| T04 | Provider/AutoChat/Runtime Tests | 39 bestanden, 7 nur wegen historischer Fixture | Kontrollierte Providerdaten, nicht echte Live-LLM-Kette |

**Summen:** 269 bestandene Tests; 18 Tests mit unerfuellter harter Alt-Session-Fixture; 3 Flask-Routentests nicht ausfuehrbar; 1 uebersprungen. Die 21 nicht bestandenen Testaufrufe sind keine neuen, durch diese Probe verursachten Produktfehler. Eine zusaetzliche Testsammlung mit `test_v65t_wiederaufnahme` wurde wegen fehlendem Flask bereits bei Collection abgebrochen und ist in den Summen nicht enthalten.

### C. Was im produktiven Source-World-Pfad fehlt

Im produktiven Python-/TypeScript-Code sind Quell-Uploads, WorldPacks und Review-Funktionen vorhanden. Eine durchgehende, explizit erkennbare `SourceAxis`-/`source_anchor`-/`sourceBeat`-Datenstruktur samt Source-Einstieg, Zukunftssperre, Beat-Achievement und Deviation-Reader wurde bei gezielter Repository-Suche nicht gefunden. Das ist kein Beweis fuer das Fehlen jeder denkbaren alternativen Implementierung, aber **kein positiver E2E-Nachweis fuer G18-G23**. Wegen bereits vorhandener Upload-/Source-Teilfunktionen wird die gesamte Source-Faehigkeit nicht pauschal als N/A bezeichnet (§71.0.1).

## D. Aktualisierter Stand aller 94 AMASTER-Invarianten

Vorher (Audit5): 9 ROT / 29 TEIL / 56 OFFEN. Nach diesen zusaetzlichen **Teilpruefungen**: 11 ROT / 64 TEIL / 19 OFFEN. Keine der Teilpruefungen entspricht einer vollstaendigen Live-Invariantenabnahme.

| Invariante | SOLL-Wortlaut (AMASTER §68) | Audit6 | Konkrete Erkenntnis / Nachweis |
|---|---|---|---|
| I01 (Z.3350) | Eine Welt besitzt stabile Identität. | **TEIL** | Neue Sessions halten die Welt-ID; keine Gesamt-UI-/Mehruserpruefung. [T01] |
| I02 (Z.3351) | Eine Session ist ein unabhängiger Verlauf in einer Welt. | **ROT** | Frueherer reproduzierter Audit4/5-Befund unveraendert (E01-E06). |
| I03 (Z.3352) | Charakterstamm und Sessionzustand sind getrennt. | **TEIL** | Stammziele bleiben beim Sessionstart getrennt; keine gesamte Stamm-Isolation. [T01] |
| I04 (Z.3353) | Userprofil und Avatarfigur sind getrennt. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I05 (Z.3354) | Sprecher und Ziel sind getrennt. | **TEIL** | Sprecher/Ziel-Kerneltests gruen; bekannte Ziel-Ambiguitaet bleibt ROT unter I50. [T03] |
| I06 (Z.3355) | Anwesenheit, Hören und Sehen bestimmen Wissen. | **TEIL** | Wahrnehmungs-/Anwesenheitsproben gruen; Langzeitwissensweg ohne Browser nicht abgenommen. [T02] |
| I07 (Z.3356) | Abwesende Figuren wissen nichts ohne Informationsweg. | **TEIL** | Perception-Tests zeigen abwesende Figur ohne unmittelbaren Beleg; keine Vollabnahme. [T02] |
| I08 (Z.3357) | SceneFacts sind append-only Evidenz. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I09 (Z.3358) | Current State wird aus Lifecycle-Evidenz bestimmt. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I10 (Z.3359) | Memory ist Figurenwissen, nicht automatisch Weltwahrheit. | **TEIL** | Figuren-Recall trennt Kenntnis/Welt-Fact in Teilproben. [T02] |
| I11 (Z.3360) | RuntimeState ist aktueller Zustand, nicht Stamm. | **TEIL** | Session-Runtime getrennt vom Figurenstamm im vorhandenen Testfall. [T01] |
| I12 (Z.3361) | RelationshipState ist gerichtet und sessiongebunden. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I13 (Z.3362) | PhysicalState begrenzt Capability. | **OFFEN** | Weder vollstaendiger Produktpfad noch negativer E2E-Nachweis; keine Freigabe. |
| I14 (Z.3363) | God und Regie wirken nur in ihrem Scope. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I15 (Z.3364) | Fate erzeugt Druck und Kandidaten, besitzt aber keine eigene Wahrheit und erzeugt kanonische Storybewegung nur über den normalen Turn-/Outcome-/Commitpfad. | **TEIL** | Fate-Auswahl rotiert ohne Ereignis nicht; Writer-/Outcome-Ende offen. [T01] |
| I16 (Z.3365) | AutoChat verwendet denselben kanonischen Pfad wie normale Turns. | **TEIL** | AutoChat-Kerneltests liefen; echte HTTP- und Browser-Paritaet offen. [T04] |
| I17 (Z.3366) | BrainContext spiegelt nur. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I18 (Z.3367) | Das LLM formuliert nur. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I19 (Z.3368) | Renderer, Narrator und Finalizer dürfen Wahrheit nicht umschreiben. | **TEIL** | Formulierungs- und Fortsetzungsgrenze nur indirekt geprueft. [T04] |
| I20 (Z.3369) | Chathere-Kompass ist Verhaltenslinse, keine Faktenmaschine. | **TEIL** | Kompass-Lese- und Wirkungstests gruen; kein vollstaendiger Negativvertrag. [T03] |
| I21 (Z.3370) | Eine SceneBehaviorEngine gehört nicht zur Architektur. | **TEIL** | Keine SceneBehaviorEngine-Klasse/Datei als zweiter Owner gefunden; Negativinventar nicht vollstaendig. [C01] |
| I22 (Z.3371) | Upload Mode A prägt nur nach Zielbindung und Review. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I23 (Z.3372) | Upload Mode B erzeugt Wissen oder Referenz, nicht Identität. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I24 (Z.3373) | Kein zweiter autoritativer Current-State-Parallelstore neben den zuständigen kanonischen Schichten; klar typisierte Quellenreferenz-, Epistemik-, Audit-, Cache-, Index- und Diagnosedaten bleiben nichtkanonisch zulässig. | **OFFEN** | Weder vollstaendiger Produktpfad noch negativer E2E-Nachweis; keine Freigabe. |
| I25 (Z.3374) | Keine produktive Backendfunktion ohne Frontendbedienung oder sichtbare Prüfbarkeit. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I26 (Z.3375) | Keine Frontendanzeige ohne reale Backendwirkung. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I27 (Z.3376) | Ein Writer ist erst vollständig wirksam, wenn der zuständige Leser die Information erhält. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I28 (Z.3377) | Ein guter Satz ersetzt keinen korrekten Zustand. | **OFFEN** | Weder vollstaendiger Produktpfad noch negativer E2E-Nachweis; keine Freigabe. |
| I29 (Z.3378) | Ein menschlicher Bruch erzeugt neue Evidenz; technische Amnesie ist kein Bruch. | **OFFEN** | Weder vollstaendiger Produktpfad noch negativer E2E-Nachweis; keine Freigabe. |
| I30 (Z.3379) | User-, Welt- und Sessionisolation bleiben erhalten. | **ROT** | Frueherer reproduzierter Audit4/5-Befund unveraendert (E01-E06). |
| I31 (Z.3380) | Ein sichtbarer Turn kann mehrere SceneFacts unter derselben "source_turn_id" erzeugen. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I32 (Z.3381) | Körperliche Handlung, Rede, Ablehnung, Offenbarung und andere eigenständige Ereigniskomponenten werden nicht durch eine unvereinbare Einzelkategorie ersetzt, sondern getrennt validiert und gebunden. | **ROT** | Frueherer reproduzierter Audit4/5-Befund unveraendert (E01-E06). |
| I33 (Z.3382) | Die Sichtbarkeit eines Satzes und die kanonische Wirksamkeit seiner einzelnen Komponenten sind getrennt; ein gültiger Bestandteil darf nicht allein wegen eines anderen ungültigen Bestandteils verloren gehen. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I34 (Z.3383) | Die Zusammengehörigkeit zusammengesetzter Outputs wird durch bestehende TurnTruth, "source_turn_id" und Turn-Binding hergestellt; dafür entsteht kein neuer Store und kein zweiter Wahrheitsbesitzer. | **ROT** | Frueherer reproduzierter Audit4/5-Befund unveraendert (E01-E06). |
| I35 (Z.3384) | Ein bereits kanonisch gebundener Current State wird nicht aus dem Wortlaut eines Folgeturns neu erraten. Neue Eingaben werden als Evidenz oder Delta zu diesem Zustand bewertet; Fallbacks dürfen ihn ohne neue gültige Evidenz weder löschen noch zurückstufen. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I36 (Z.3385) | Eine Source-Axis ist ein quellengebundener Ereignis-/Beat-Referenzbestand, aber keine Sessionwahrheit und kein zweiter Session-Event-Store. | **OFFEN** | Source-Axis/Source-Anchor-Produktkette nicht nachgewiesen; kein Gate-Test moeglich [C02]. |
| I37 (Z.3386) | Beim Source-Einstieg bleiben bestätigte Vergangenheit, aktueller Anchor und noch nicht geschehene Quellenzukunft strikt getrennt. | **OFFEN** | Source-Axis/Source-Anchor-Produktkette nicht nachgewiesen; kein Gate-Test moeglich [C02]. |
| I38 (Z.3387) | Zukünftige Quellenereignisse werden nicht vorab zu SceneFacts, Memory, Runtime oder Figurenwissen. | **OFFEN** | Source-Axis/Source-Anchor-Produktkette nicht nachgewiesen; kein Gate-Test moeglich [C02]. |
| I39 (Z.3388) | Quellvergangenheit wird figurenbezogen nach Handlung, Wahrnehmung, Betroffenheit und Informationsweg materialisiert, nicht als globale Buchzusammenfassung an alle verteilt. | **OFFEN** | Source-Axis/Source-Anchor-Produktkette nicht nachgewiesen; kein Gate-Test moeglich [C02]. |
| I40 (Z.3389) | Explizites Nichtwissen und unbekannte Wissenslage sind getrennt. | **OFFEN** | Source-Axis/Source-Anchor-Produktkette nicht nachgewiesen; kein Gate-Test moeglich [C02]. |
| I41 (Z.3390) | Tatsächliche Sessionevidenz hat für die Fortsetzung Vorrang vor der erwarteten Quellenfortsetzung. | **OFFEN** | Source-Axis/Source-Anchor-Produktkette nicht nachgewiesen; kein Gate-Test moeglich [C02]. |
| I42 (Z.3391) | Fate darf die Source-Axis als Orientierung nutzen, aber Avatar, Puppet, Regie, God oder kanonische Sessionwirkung nicht überschreiben. | **OFFEN** | Source-Axis/Source-Anchor-Produktkette nicht nachgewiesen; kein Gate-Test moeglich [C02]. |
| I43 (Z.3392) | Ein Source-Beat gilt nur bei tatsächlich eingetretener kanonischer Wirkung als erreicht. | **OFFEN** | Source-Axis/Source-Anchor-Produktkette nicht nachgewiesen; kein Gate-Test moeglich [C02]. |
| I44 (Z.3393) | Source-Locator- und Prozentnavigation dürfen nicht still gegeneinander ausgetauscht werden; der Wechsel ist sichtbar und bewusst. | **OFFEN** | Source-Axis/Source-Anchor-Produktkette nicht nachgewiesen; kein Gate-Test moeglich [C02]. |
| I45 (Z.3394) | Äußere Rede oder Handlung, private Wahrhaftigkeit, strategische Absicht, momentanes echtes Empfinden und gerichtete Beziehung bleiben getrennte Zustandsarten. | **TEIL** | Affect-, Rede- und Relationsproben im Kernel; nicht alle Arten/Szenen. [T03] |
| I46 (Z.3395) | Emotion, körperliche Reaktion oder äußerlich gezeigte Nähe verändern Vertrauen, Liebe, Loyalität oder andere Relationship-Dimensionen nicht automatisch. | **TEIL** | Emotionsreaktionen ohne zwingende Relationsaenderung in Tests; keine Vollabnahme. [T03] |
| I47 (Z.3396) | Eine erneute Quellenanalyse darf keine parallele zweite Welt, keinen doppelten Charakterstamm und keine unkontrollierte zweite Source-Axis erzeugen. | **OFFEN** | Source-Axis/Source-Anchor-Produktkette nicht nachgewiesen; kein Gate-Test moeglich [C02]. |
| I48 (Z.3397) | Jede natürliche produktive Eingabe, jedes God-/Regiekommando und jeder strukturprägende Upload wird vor dem kanonischen Schreiben in getrennte typisierte Effects zerlegt. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I49 (Z.3398) | Der EffectPlan besitzt keine eigene Wahrheitshoheit; eine persistierte Auditkopie darf nie als Current State oder Ersatz für committete Writerergebnisse gelesen werden. | **TEIL** | Gefaelschter Frontend-Spiegel wird durch kanonischen SQL-Kontext ueberschrieben; Plan-Audit-Folgeturn offen. [T04] |
| I50 (Z.3399) | Jeder Effect bindet stabile Identitäten, Domain, Operation, Scope, Authority, Zeitbezug, Provenienz und Validierung, soweit fachlich anwendbar. | **ROT** | Frueherer reproduzierter Audit4/5-Befund unveraendert (E01-E06). |
| I51 (Z.3400) | Identität, Alias, Sprecher-/Steuerbindung und Figurenwissen über Identität sind getrennt. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I52 (Z.3401) | Objektive Weltwahrheit erzeugt nicht automatisch Figurenwissen. | **TEIL** | Perception und Witness-Wissen nur mit Teilproben. [T02] |
| I53 (Z.3402) | COPY oder ADOPT überträgt nur die ausdrücklich bezeichnete Domäne und ist standardmäßig Snapshot, kein Live-Link. | **OFFEN** | Weder vollstaendiger Produktpfad noch negativer E2E-Nachweis; keine Freigabe. |
| I54 (Z.3403) | Wortlisten und Ontologien erzeugen Kandidaten, niemals unmittelbar kanonische Wahrheit. | **ROT** | Frueherer reproduzierter Audit4/5-Befund unveraendert (E01-E06). |
| I55 (Z.3404) | Dauerhafte Disposition, momentane Emotion oder Drive, Intent, Handlung und Beziehung bleiben getrennt. | **TEIL** | Runtime/Emotion/Relation in einzelnen Szenen getrennt; nicht vollstaendig. [T03] |
| I56 (Z.3405) | Ein gerichteter Drive oder eine gerichtete Emotion bindet soweit relevant Owner, Target, Ursache, Intensität und Lifecycle. | **TEIL** | Gerichtete Affect-Wirkungen mit einigen Bindungen geprueft, kein Gesamtvertrag. [T03] |
| I57 (Z.3406) | Zustimmung oder Acceptance ist handlungs- und propositionsbezogen und darf nicht aus Liebe, Lust, Beziehung, körperlicher Reaktion oder früherer Zustimmung abgeleitet werden. | **ROT** | Frueherer reproduzierter Audit4/5-Befund unveraendert (E01-E06). |
| I58 (Z.3407) | Eine Handlung wird als geplant, versucht, blockiert, gescheitert, teilweise oder vollständig vollzogen unterschieden, soweit der Handlungstyp dies erfordert. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I59 (Z.3408) | Körperliche und objektbezogene Folgen benötigen gültige Ursache oder ausdrückliche Authority. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I60 (Z.3409) | Object-/Spatial-State ist kanonisch adressierbar und begrenzt mögliche Handlungen. | **TEIL** | Orts-/Distanz- und Spatial-Tests gruen; keine Objektblockade-Gesamtprobe. [T03] |
| I61 (Z.3410) | Relationship-Effekte sind gerichtet, kausal gebunden und pro Figur interpretierbar; derselbe Fact darf bei verschiedenen Figuren unterschiedliche Folgen haben. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I62 (Z.3411) | Social/Synapsen ist Aktivierung und darf RelationshipState nicht ersetzen. | **TEIL** | Synapsen/Relation-Grenze in bestehenden Tests geprueft, Social-Abklingtest fehlt. [T03] |
| I63 (Z.3412) | Jeder abgeleitete Effect verweist soweit möglich auf seine ursächliche Evidenz und darf durch erneuten Recall derselben Ursache nicht mehrfach angewendet werden. | **ROT** | Frueherer reproduzierter Audit4/5-Befund unveraendert (E01-E06). |
| I64 (Z.3413) | Korrektur erfolgt durch neue Evidenz, CORRECT, SUPERSEDE oder REVOKE, nicht durch heimliches Löschen historischer Evidenz. | **TEIL** | Lifecycle-Evidenz vor Korrektur lesbar; echte REVOKE-Historienabnahme fehlt. [T01] |
| I65 (Z.3414) | Werden Grundlagen korrigiert oder widerrufen, werden ausschließlich davon abhängige Current-State-Ableitungen neu bewertet; tatsächlich geschehene historische Reaktionen bleiben Evidenz. | **TEIL** | Reducer verwendet gueltige Lifecycle-Ereignisse; selektive Neuberechnung nicht end-to-end. [T01] |
| I66 (Z.3415) | Unabhängige Effects dürfen partiell committen; abhängige Effects müssen ihre Abhängigkeiten ausdrücklich tragen. | **ROT** | Frueherer reproduzierter Audit4/5-Befund unveraendert (E01-E06). |
| I67 (Z.3416) | Ein relevanter, offener oder aktiver Zustand erzeugt keine automatische Sprech- oder Handlungspflicht; auch Fate und Sprecherwahl dürfen Relevanz nur gewichten, nicht in Vollzugszwang umwandeln. | **TEIL** | Fate und Ziel-Recall loesen nicht automatisch einen Sprecherzwang aus (Teilprobe). [T01] |
| I68 (Z.3417) | Chat-God verwendet Session-Scope nur als Default bei fehlender eindeutiger Scopeangabe; UI-Auswahl oder semantisch eindeutiger Welt-/Stamm-/Dauerscope bindet unmittelbar den ausdrücklich gewählten Scope. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I69 (Z.3418) | Parserambiguität darf keine neue Weltwahrheit erzeugen. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I70 (Z.3419) | Parser-, Validator-, Writer- und Readerwirkung müssen getrennt diagnostizierbar sein. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I71 (Z.3420) | Upload Mode A darf automatisch viele Kandidaten extrahieren; dauerhafte Wirkung entsteht erst nach sichtbarem Review und Commit. | **TEIL** | Review-Reject/Accept an realem Writer und SQLite; Upload-Mode-A-Endkette fehlt. [N03] |
| I72 (Z.3421) | Upload Mode B darf denselben intelligenten Parser verwenden, erhält aber keine impliziten Stamm- oder Kanonwriterrechte. | **OFFEN** | Mode-B-ohne-Kanonwriter-Gegenprobe nicht durchgefuehrt; Review-Test beweist nur Teil von Mode A. |
| I73 (Z.3422) | Wahrnehmung, Aufmerksamkeit, Engagement und Zustimmung sind getrennte Zustände und dürfen nicht automatisch auseinander abgeleitet werden. | **TEIL** | Deferred- und Vordergrundzustand getrennt; Zustimmung nicht im selben Test. [N02] |
| I74 (Z.3423) | ATTENTIONAL_STATE, ENGAGEMENT_STATE und BACKGROUND_AFFECT sind situative Runtime-Zustände und bilden keinen neuen Truth Owner neben RuntimeState. | **TEIL** | Situative Zustandfelder im Runtime-Owner, aber nicht alle drei Typen getestet. [N02] |
| I75 (Z.3424) | Der objektive Szenenvordergrund im SceneState ist nicht identisch mit dem subjektiven Figurenfokus und erzeugt keinen globalen psychischen Szenenzustand für alle Figuren. | **TEIL** | CharacterForeground aus Prepare und SceneState getrennte Felder; keine Szenenfolge. [N02] |
| I76 (Z.3425) | Foreground Arbitration ist eine Reader-/Selektionsfunktion ohne Wahrheitshoheit, Writerrecht oder eigene Verhaltensentscheidung. | **TEIL** | Foreground-Reader fuer 16 Ziele las nur, veraenderte Session nicht. [N01] |
| I77 (Z.3426) | Harte Constraints wie Authority, Weltregeln, PhysicalState/Capability, Anwesenheit und bindender Current State dürfen durch situativen Fokus oder Foreground Arbitration nicht ausgeblendet werden. | **TEIL** | Authority-Constraint vorhanden, weitere harte Constraints nicht vollstaendig geprueft. [N01] |
| I78 (Z.3427) | Nicht im Figuren-Vordergrund befindliche Memories, Goals, Beziehungen und Zustände bleiben erhalten; Background bedeutet weder vergessen noch geschlossen noch unwahr. | **TEIL** | 16 Ziele bleiben im Background erhalten; aktueller Foreground bleibt begrenzt. [N01] |
| I79 (Z.3428) | Disengagement, Deferment oder Withdrawal benötigen gültige Evidenz und dürfen nicht automatisch als AVERSION, Feindseligkeit, Misstrauen, Beziehungskälte oder Charaktereigenschaft interpretiert werden. | **TEIL** | Deferred bleibt beim Lesen bestehen; Langzeit-AVERSION-Probe offen. [N02] |
| I80 (Z.3429) | Ein DISCOURSE_ACT wie context_probe, clarification_request, topic_change oder defer_answer beweist für sich allein keine versteckte Emotion, Beziehung oder Absicht. | **OFFEN** | Weder vollstaendiger Produktpfad noch negativer E2E-Nachweis; keine Freigabe. |
| I81 (Z.3430) | Social Activation kann Aufmerksamkeit beeinflussen, ist aber nicht identisch mit ATTENTIONAL_STATE und erzeugt keine automatische Foreground-Pflicht. | **TEIL** | Social/Synapsen-Relation Teilgrenze, kein getrenntes Abklingen. [T03] |
| I82 (Z.3431) | Fate respektiert gültige Withdrawal-/Disengagement-Zustände, darf aber neue kausal plausible äußere Stimuli oder Ereigniskandidaten vorschlagen; Fokus- oder Engagementänderung entsteht erst durch gültige Sessionevidenz. | **OFFEN** | Weder vollstaendiger Produktpfad noch negativer E2E-Nachweis; keine Freigabe. |
| I83 (Z.3432) | Der Character Foreground ist absichtlich begrenzt; nicht jeder relevante Zustand darf gleichzeitig aktiv in den Cognitive/Expressive Context gelangen. | **TEIL** | 16 gleichzeitig gespeicherte Ziele, Vordergrund 0, Background 16. [N01] |
| I84 (Z.3433) | Sprecherwahl und AutoChat berücksichtigen situative Verfügbarkeit, dürfen daraus jedoch weder automatische Antwortpflicht noch automatische Abwesenheit erzeugen. | **TEIL** | AutoChat-Gate und Sprecherwahl-Kerneltests, kein voller Paritaets-E2E. [T04] |
| I85 (Z.3434) | Mere Recall, Prompt-Präsenz oder erneute Foreground-Auswahl sind keine neue Evidenz und dürfen Attention, Engagement, Emotion, Relationship oder Goal nicht selbst verstärken. | **TEIL** | Wiederholtes Prepare ohne neue Evidenz laesst Session unveraendert. [N01] |
| I86 (Z.3435) | Die Situations- und Foreground-Schicht darf keine SceneBehaviorEngine ersetzen: Sie selektiert verfügbaren Kontext, entscheidet aber nicht selbst, was eine Figur fühlen, sagen oder tun muss. | **TEIL** | Foreground waehlt Kontext als Reader, keine eigene Figuren-Commitwirkung in Probe. [N01] |
| I87 (Z.3436) | Jeder datentragende Übergang zwischen produktiven Subsystemen muss die Datenrolle eindeutig erkennen lassen; bei unklarer Rolle gilt fail-closed und der Datensatz darf keine kanonische Wirkung erzeugen. | **ROT** | SNAPSHOT-INPUT gelangt als CANONICAL_RUNTIME und SceneState in Restore, keine nachgewiesene TurnTruth. [N05] |
| I88 (Z.3437) | SOURCE_REFERENCE darf niemals direkt als geschehene Sessionevidenz oder Figurenmemory gelesen werden; Source-Materialisierung erzeugt neue kanonische Evidenz mit Quellenprovenienz. | **OFFEN** | Source-Axis/Source-Anchor-Produktkette nicht nachgewiesen; kein Gate-Test moeglich [C02]. |
| I89 (Z.3438) | Ausgabe eines externen oder lokalen Rechen-/LLM-/OCR-/Semantikdienstes ist nichtkanonisch, bis sie lokal gebunden, validiert und über den zuständigen Writer committed wurde. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I90 (Z.3439) | Modellausgabe darf keine geschützte Avatar-Rede, -Entscheidung, -Einwilligung, -Ablehnung, -Absicht, -Emotion, -Beziehungserklärung oder -Körperhandlung ohne ausdrückliche Nutzerprovenienz kanonisch erzeugen. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I91 (Z.3440) | Diagnose-, Test- und Reparaturfunktionen besitzen keinen direkten privilegierten kanonischen Sonderwrite; reale Produktwirkung durchläuft denselben Authority-, Validator-, Writer- und Readerpfad wie die normale Produktoberfläche. | **ROT** | Restore nutzt privilegiertes Direkt-UPDATE von Sessions-JSON; manipulierbare Snapshotdaten umgehen normalen Validator. [N05] |
| I92 (Z.3441) | Cache, Index, Embedding, Suchtreffer oder Auditbestand sind niemals Current-State-Owner; bei Widerspruch gewinnt der zuständige kanonische Owner, und ein Cachefehler darf keine Ersatzwahrheit erzeugen. | **TEIL** | Vergifteter Document-Index beeinflusst echte Dokumentdaten nicht, Suchtreffer bleiben vergiftet. [N04] |
| I93 (Z.3442) | Persistenzlisten des AMASTER definieren logische Owner und Verpflichtungen, nicht konkrete Tabellen-, Spalten- oder Dateischemata. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |
| I94 (Z.3443) | Agent-Systemprompt, Buildbericht, Tests, Logs, Diffs und Readmes dürfen AMASTER nachweisen oder operationalisieren, aber seine Owner-, Scope-, Authority- oder Wahrheitsemantik nicht ersetzen oder still ändern. | **TEIL** | Keine neue Vollabnahme; bisherige Teilpruefung bleibt, siehe Audit5. |

## E. Alle 31 SPS-Gates - Ergebnis nach der Restpruefung

Kein Gate hat die komplette `UI -> TurnTruth -> Effect -> Writer -> SQLite -> Folgeturn -> UI/Reload -> Isolation`-Abnahme durchlaufen. Entsprechend kein einziges Gate mit PASS markiert.

| Gate | AMASTER-Name | Stufe | Status | Beleg / Fehlendes Glied |
|---|---|---|---|---|
| G1 | Knowledge | FOUNDATION | **TEIL** | Knowledge-/Witness-Kerneltests bestanden, keine vollstaendige UI-Folgeprobe [T02]. |
| G2 | Physical | FOUNDATION | **OFFEN** | Koerper und objektive Blockade/Outcome nicht durch UI/SQLite abgenommen. |
| G3 | Relationship | FOUNDATION | **TEIL** | Gerichtete Beziehungen mit Kerneltests, kein vollstaendiger E2E [T03]. |
| G4 | Authority/Object | FOUNDATION | **TEIL** | Regie-/Raumteilproben, Objekt/God-Scope nicht gesamtabgenommen [T03]. |
| G5 | Avatar | FOUNDATION | **TEIL** | Avatar/Bedienperson-Teiltests, keine negative Modell-Avatar-Endkette [T04]. |
| G6 | Persistence | FOUNDATION | **TEIL** | SQLite-Ruecklesung in Writerproben; Restore-Direktweg verletzt Zustandsvertrag [N05]. |
| G7 | Isolation | FOUNDATION | **ROT** | Sessionfremder Upload als Quelle zugelassen [E02]. |
| G8 | Writer-Reader | FOUNDATION | **OFFEN** | Vollstaendiges Writer-/Readerinventar und einheitliche semantische Kontrolle fehlen. |
| G9 | Turn-Composition | LIVING CORE | **ROT** | Unbekanntes Ziel und Einwilligungsmischung falsch gebunden [E05,E06]. |
| G10 | Refusal/Acceptance | LIVING CORE | **ROT** | Teilhandlung/Erlaubnis ueber Person, Seite oder Ziel falsch [E06]. |
| G11 | Session/Stamm-Isolation | LIVING CORE | **TEIL** | Stamm/Session in Teiltests getrennt, kein vollstaendiger UI/Relaunch [T01]. |
| G12 | Product-Surface | LIVING CORE | **TEIL** | Frontendpfade vorhanden, keine vollstaendige nutzbare Route-Abnahme. |
| G13 | Foreground | HUMANIZATION | **TEIL** | 16 Ziele; Foreground 0; Background 16; keine Gesamt-Situation [N01]. |
| G14 | Engagement | HUMANIZATION | **TEIL** | Deferred bleibt in Prepare erhalten; kausale Neuaktivierung nicht prueft [N02]. |
| G15 | Social/Relationship-Trennung | HUMANIZATION | **TEIL** | Social/Relations-Kerneltests bestanden; separate Abklingphase fehlt [T03]. |
| G16 | AutoChat-Paritaet | HUMANIZATION | **TEIL** | AutoChat-Kerneltests bestanden; keine HTTP/Browser-Paritaet [T04]. |
| G17 | Review/Profiler | HUMANIZATION | **TEIL** | Review Ablehnung unveraendert, Freigabe dauerhaft; kein Upload-UI-Pfad [N03]. |
| G18 | Source-Entry | SOURCE WORLD | **OFFEN** | Quellenstart/Source-Anchor/Source-Axis-Kette nicht vorhanden nachgewiesen [C02]. |
| G19 | Source-Readervertrag | SOURCE WORLD | **OFFEN** | Keine negative Source-Readerprobe mit Source-Axis als Datenquelle [C02]. |
| G20 | Beat-Achievement | SOURCE WORLD | **OFFEN** | Source-Beat-Completion nicht end-to-end nachgewiesen [C02]. |
| G21 | Deviation | SOURCE WORLD | **OFFEN** | Abweichung vom Buch und Fate-Replan nicht nachgewiesen [C02]. |
| G22 | Fail-Closed Source | SOURCE WORLD | **OFFEN** | Keine Source-Rollen-Fail-Closed-Probe [C02]. |
| G23 | Source-Reanalyse-Isolation | SOURCE WORLD | **OFFEN** | Keine Source-Reanalyse mit deduplizierter Zielwelt [C02]. |
| G24 | Isolation Parallelbetrieb | FULL CONFORMANCE | **OFFEN** | Kein Mehrprozess-/Mehrnutzer-HTTP-Lauf. |
| G25 | Provider-Ausfall | FULL CONFORMANCE | **TEIL** | Providerfehler-Tests mit kontrollierten Daten bestanden, kein vollstaendiger Browser-Fehlerlauf [T04]. |
| G26 | Datenrollen-Vollpruefung | FULL CONFORMANCE | **ROT** | Snapshot-DRAFT-Eingabe wird ohne Rolle/Authority zu kanonischem Runtime-/SceneState [N05]. |
| G27 | Negativabnahme | FULL CONFORMANCE | **ROT** | Bekannte Negativproben E01-E06 und N05 schlagen weiterhin fehl. |
| G28 | Writer-Reader-Vollpruefung | FULL CONFORMANCE | **OFFEN** | Vollinventar Writer-Reader und Frontend-Bindung nicht erstellt. |
| G29 | Snapshot/Restore | FULL CONFORMANCE | **ROT** | Snapshot injiziert Runtime/SceneState/TurnIndex und nicht existente pendingInputTurnId [N05]. |
| G30 | Accessibility/Product-Surface | FULL CONFORMANCE | **OFFEN** | Keine Barrierefreiheits-Pruefung im Browser/Screenreader/Android. |
| G31 | AMASTER-Vollpruefung | FULL CONFORMANCE | **ROT** | Bekannte Vertragsverletzungen und noch offene Pflichten. |

## F. Acht Datenrollen aus AMASTER §6.2

| Rolle | Restbefund |
|---|---|
| CANONICAL_CURRENT | ROT: Snapshot-Inhalt schreibt Runtime, SceneState, TurnIndex und Pending-Verweis ohne regulaeren Effect-Commit (N05). |
| CANONICAL_HISTORY | ROT: frueheres E01/E04; abhaengige Fakten/ungepruefte Herkuenfte. |
| SOURCE_REFERENCE | OFFEN: Source-Axis-Zukunft nicht produktiv E2E nachgewiesen. |
| EPISTEMIC_BINDING | TEIL: Wissen/Perception in Kerneltests, kein kompletter Cross-Session-/Folgeturn-Gate. |
| DRAFT_REVIEW | TEIL: Review Ablehnung/Freigabe belegt, aber Snapshot-DRAFT aus API wird als Restore-Kanon angenommen. |
| PLAN_AUDIT | OFFEN: Keine ausdrueckliche Manipulations- und Folgeturn-Gegenprobe eines persistierten Plans. |
| CACHE_INDEX | TEIL: Poisoned-Index betrifft Suche, nicht kanonische Dokumente (N04). |
| DIAGNOSTIC | TEIL: Diagnoseweg im Client erzeugt durch Probe einen Snapshot; kein vollstaendiger Seiteneffekt-Audit. |

## G. Vereinbarkeit und SPS-Gesamturteil

Der neue Befund N05 liegt hinter der Schreibgrenze: Die Sicherung enthaelt **von ausserhalb des Kernel-Owners gesetzte Werte**, die beim Restore als serververtrauenswuerdige Kanondaten eingespielt werden. Eine Quelle mit kryptischer Rolle oder willkuerlichen Turn-IDs reicht; eine TurnTruth-/Effect-/Authority-Pruefung findet fuer die betroffenen Envelope-Felder nicht statt. Das ist keine reine Oberflaechenabweichung.

Reparaturkette N05: **Snapshot-Quelle und Trust-Klasse pruefen -> clientseitige `session`-Envelope-Ueberschreibungen aus `create_snapshot` verbieten -> beim Restore nur echte vorher vom Server erfasste und gepruefte Daten verwenden -> `pendingInputTurnId` existenz-/Session-gebunden validieren -> `turnIndex` an kanonische Historie binden -> Runtime/SceneState nicht durch Fremdinput als Wahrheit akzeptieren -> Frontend-/Neustart-/Negative-E2E**. Historische Backups duerfen dabei nicht still geloescht werden; Restore-Semantik und Legacy-Quarantaene explizit entscheiden.

Die urspruenglichen Audit4/5-Befunde E01-E06 bleiben offen. G7, G9, G10, G26, G27, G29 und G31 ROT. SOURCE-WORLD, AutoChat-Gesamtparitaet, Accessibility, Provider-Live-Abbruch und Mehrprozessbetrieb koennen aus dem vorliegenden Lauf nicht freigegeben werden.

**Entscheidung: V65Z weiterhin ROT / nicht freigabefaehig.** Neue Produktversion nicht erstellt; Original-ZIP und originale Datenbank unveraendert. Keine erfundene vollstaendige AMASTER-Abnahme.

## H. Reproduktion, Integritaet und Werkzeuggrenzen

- `repro_snapshot_envelope.py`: Zwei ungebundene Runtime-/SceneState-Marker in wiedereroeffneter SQLite gespeichert; `currentState`-Marker nicht gespeichert.
- `repro_snapshot_turnindex.py`: Synthetischer Turnzaehler 777 und ungueltiger `pendingInputTurnId` gespeichert, bei 0 TT/0 Facts.
- `repro_foreground_review.py`: 16 Ziele / Deferred / zwei Review-Pfade.
- `repro_cache_index.py`: Quelle gegen Cache-Tampering.
- `remaining_automated_1` bis `_4.log`: Neu ausgefuehrte Testgruppen. Tests mit erwarteten historischen Fixtures sind nicht als Codefehler bewertet.
- Original V65Z ZIP SHA256: `3258c2711136623c21167ace9074db32b8e3d5a42debf4f51211be7c9c0fb39b`; DB SHA256 im ZIP `9be11b8410c4396eb731254f997dfed3095cd6c65c048bc04e80cd3e8c2d4003`.
- Flask nicht im Ausfuehrungscontainer installiert; ohne Netz nicht nachladbar. Repo-/Kernel-Tests nutzen fuer den ansonsten unbenutzten Flask-Import einen Shim; kein echter HTTP-Flask-Test behauptet.
- Es wurde kein Browser, keine Android-App, kein echter Provider, kein Mehrprozessstress und keine vollstaendige 94/31-E2E-Abnahme ausgefuehrt.
```

## DECKBLATT · V65Z · SPS- und Vertragsaudit zu V65Y (A01–A08): die ganze Schreibkette TurnTruth → Effekt-Bindung → Authority/Scope → Writer → SQLite → Reader, Pfadschutz, Import in einer Transaktion (Claude) · 31.10.2026

**Verbindlich:**
- `2_7master.txt`:
  - §6.2 Z. 247–279 (Z. 262 fail-closed an kritischer Grenze; Nr. 2 Modellklassifikation ist keine Wahrheit; Nr. 4 kein Direkt-Write);
  - §8 Z. 350–352 (der Nutzer ist nicht automatisch eine Figur);
  - §23 Z. 1028–1034 (eine gemeinsame TurnTruth trennt Bedienperson, Rolle, Avatar, Puppet-Sprecher, tatsächlichen Sprecher);
  - Z. 1280–1282 (mögliche Sprecher: „realer Nutzer als Bedienperson“);
  - §24.2 Z. 1110–1118 (Semantik → Validierung vor dem Writer), §24.7 (keine stille Kürzung);
  - §27.2 Z. 1372–1374 (über Avatar oder außerhalb der Welt, ausdrücklich gebunden);
  - §34 Z. 1736–1772 (SceneFact bindet Quellturn, Actor, Target), §34.1 Z. 1774–1817 (jede Komponente eigene Validierung, dieselbe source_turn_id), §34.2 (Kausalprovenienz), §34.3 (historische Evidenz nicht heimlich löschen);
  - §36.5 Z. 1947–1975; §39 (Wissen aus Wahrnehmung); §44 (Beziehung zwischen zwei Figuren);
  - §46.1–§46.6 Z. 2521–2601 (God mit gültiger Authority und Scope, drei Achsen);
  - §71.1.2 (technische Basissicherheit), §71.1.3 (verbotene Abkürzungen).
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6, §16 (vollständige Speicherkette).

**Eingang:** SPS- und Vertragsaudit zu V65Y (Zusammenfassung A01–A08, Gates G1–G12, Widerspruch im Deckblatt). Vermerk unten, unverändert.
- Die Gegenproben des Prüfers lagen nicht bei. Ich habe sie aus der Befundtabelle nachgebaut (`scripts/v65z_gegenproben/proben/`).
- Ob sie genau seine Fälle treffen: **UNKLAR**.

**Basis:** mein V65Y-ZIP (SHA256 `62efc52b…`). DB und Logs bytegleich, keine Migration.

**Berichtigung am V65Y-Deckblatt:** „Eine Schreibgrenze für alle Wege“ stimmte nicht. Die Prüfung saß nur in den Anlege-Writern für SceneFact, God-Fakt, Beziehung und Personen-IDs. Ohne Prüfung blieben:
- TurnTruth;
- PATCH an Gedächtnis, Proposition und Ziel;
- Zeugenwissen;
- die Herkunft nach Art;
- der Client-Import (Kind für Kind);
- die MCC-Wiederherstellung.

Jetzt laufen alle Wege neuer Zeilen durch dieselbe Grenze. Ausnahme ist die MCC-Wiederherstellung einer eigenen Sicherung: Sie stellt gespeicherte Zeilen so wieder her, wie sie waren, und zählt jede Zeile außerhalb der Grenze sichtbar.

### Wurzel → Änderung (vorhandene Owner, keine neue Route, keine Tabelle, keine Wortliste)

| Befund | Wurzel am V65Y-Code (gegengeprüft) | Änderung |
|---|---|---|
| A01 Fact-ID als Quellturn | `_session_ref_ids` war **eine** Menge aller IDs der Session; jede beliebige ID galt als Quelle. Der Kernel schrieb selbst die Fact-ID der Ursache als `sourceTurnId`: Wissenswirkung, Körperzustand, Synapse, Lebenszyklus, Widerspruch, Aussage-gegen-Erleben, God-Körperzustand. In deiner DB sind das 22 Zeilen | **Herkunft nach Art** (`_session_sources`, `_check_sources`): Ein Quellturn ist eine TurnTruth der Session, `responds_to_fact_id`/`cause_fact_id` ist ein SceneFact der Session, `sourceUploadId` ist ein Upload der Session. **Jede** genannte Quelle wird geprüft, eine falsche neben einer richtigen lehnt ab; eine Zeile nennt nie sich selbst. Der Kernel trägt die Ursache getrennt: `fact_provenance` gibt den Quellturn der Ursache und `cause_fact_id`. Das gilt auch für den Ursprung einer Beziehung. Die Neuvergabe der IDs (Duplikat/Import) übersetzt `cause_fact_id` mit |
| A02 unbelegte TurnTruth, God ohne Authority | `append_session_turn_truth` prüfte nichts. Ein God-Fakt nahm **jede** TurnTruth als Quelle (auch eine Puppet-TurnTruth) und beliebige Achsen | **TurnTruth-Grenze** (`_check_turn_truth_boundary`): Rolle und Authority sind gebunden. Die Personen (Sprecher, Ziel, Eingabe-Actor, Avatar, Puppet, Antwortsprecher) sind Figuren, Kernel-Authority oder Bedienperson; die Wahrnehmungslisten nennen Figuren. Die God-Authority gibt es nur in der God-Rolle, mit Sprecher „god“; die Regie-Authority nur in der Regie-Rolle. **God-Fakt:** Die Quelle ist eine God-TurnTruth (Rolle und Authority „god“). Die drei Achsen müssen genau zu `god_scope_axes(_god_scope_key(scope))` passen |
| A03 PATCH umgeht Identität | `patch_session_memory`/`_proposition`/`_goal` übernahmen jede ID | `_check_patch_ids`: Ändert ein PATCH eine Person, gilt dieselbe Prüfung wie für eine neue Zeile. Lässt er die Personen einer Altzeile stehen, bleibt ihr Lebenszyklus möglich (keine Migration). **Zeugenwissen** (`_check_witness_boundary`): Wissende ist eine Figur der Welt, gewusst wird ein SceneFact der Session. Die drei Client-Writer ohne Aufrufer sind mit ihren Routen entfernt: `POST …/turns`, `PATCH …/memories/<id>`, `DELETE …/relations/<from>/<to>` |
| A04 siebte Handlung verloren | Kappungen `[:6]` in `component_effect_checks`, `bind_input_components`, Regie-Komponenten, Sprachlesung, Aussagen, Regelprüfung, Mehrdeutigkeiten. **Live dazu gefunden (E2E Lauf 2):** Die Zerlegung brach bei 7 Taten am Tokenlimit ab (`finish_reason: length`, 600 Tokens); `_repair_json` schloss die Klammern und ließ die 7. Komponente ohne Spur fallen | Alle Kappungen auf Komponenten sind entfernt. Der Raum der Zerlegung wächst mit der Eingabe (`reading_room`: 600–4000 Tokens). Eine abgeschnittene oder reparierte Lesung wird markiert (`_abgeschnitten`). Die Eingabe trägt dann sichtbar `lesung_abgeschnitten`, der Rest bleibt Rede, und keine Tat dieser Eingabe wird an eine angenommene Bitte gebunden |
| A05 Text nicht gegen das Original geprüft | `_locate_segment` nahm jeden wörtlichen Teilstring: „Ich küsse dich“ aus „Ich küsse dich nicht.“ oder aus einem Zitat. Ein Ziel der Lesung wurde ohne Beleg im Text gebunden. Der Stamm-Anker „han“ machte „Handtasche“ zur erlaubten Hand | `segment_binding_fault` für Eingabe, Puppet und Regie, strukturell: Ein Segment in Anführungszeichen ist `segment_im_zitat`. Lässt die Lesung bis zum nächsten Satzzeichen ein Wort des Satzes übrig, ist es `segment_satz_unvollstaendig`; erlaubt ist nur ein Bindewort direkt vor der nächsten Komponente. **Ziel:** Das Ziel einer Lesung muss in der Eingabe genannt sein oder der gebundene Adressat (UI-Ziel bzw. Adressat der Puppet-Route); sonst `ziel_nicht_im_eingang`, kein Ziel. **Körperstelle:** Wo der Anker erlaubt (Ausnahme, eingeschränkte Erlaubnis), muss die Tat die Stelle selbst nennen, nur gebeugt (`exact`). Wo er verbietet, bleibt der Stamm das Veto |
| A06 Antwort an den Avatar statt an die Bedienperson | `kernel.py` Z. 5877–5882: Die nicht anwesende Bedienperson wurde nicht als Adressat übergeben. Der letzte Rückfall des Resolvers („einzige anwesende Figur“) gab die Antwort dem Avatar | Spricht die Bedienperson, geht die Rede der Figur an sie, außer die Rede spricht eine andere Figur ausdrücklich mit Namen an. Eine Tat richtet sich nur an eine Figur, die sie nennt (die Bedienperson ist außerhalb der Welt) |
| A07 Dateizugriff über START.py | `_serve_frontend`: `FRONTEND_DIR / unquote(path)` ohne Auflösen; `/assets/..%2F..%2Fdata%2Fmatrix10.sqlite` lieferte die DB mit Schlüssel, HTTP 200 | Der Pfad wird aufgelöst und muss in `frontend_dist` liegen, sonst 404, nichts gelesen |
| A08 Import nicht atomar | `create_session(import)` speicherte nur den Rahmen, der Client schrieb danach jedes Kind mit eigenem Request; ein abgelehntes Kind hinterließ eine halbe Session. Die Client-Neuvergabe der IDs bildete `sourceTurnId` falsch ab | **Ein** Request: Der Server vergibt die IDs neu (`rekey_session_graph`) und schreibt Rahmen und Kinder durch die Writer der Grenze in **einer** Transaktion. Ein abgelehntes Kind lehnt den Import ab (422), nichts ist gespeichert. Beziehungen tragen `provenienz: import`. Der Client erzeugt keine IDs mehr selbst, nur die neue Session-ID über den Allokator (Live-Befund Lauf 1: sonst 400 `PROVISIONAL_ID`). Die Meldung nennt den Grund |
| MCC-Wiederherstellung | `_import_children` schrieb gespeicherte Zeilen direkt | Bleibt eine Wiederherstellung gespeicherter Zeilen (§34.3; eine Ablehnung würde die Sicherung unbrauchbar machen). Jede Zeile außerhalb der Grenze steht je Session im Ergebnis (`schreibgrenze`, Warnung `LEGACY_ROWS_RESTORED:n`) |

### Gegenproben und Tests (0 Modellaufrufe)
- **Nachgebaute Gegenproben** (`proben/probe_a01_a08.py`, Rücklesen nach erneutem Öffnen der SQLite-Datei):
  - Am V65Y-Code reproduziert jede Probe den Befund: A01 gespeichert, A02 TurnTruth und zwei God-Fakten gespeichert, A03 drei falsche Personen gespeichert, A04 6 von 7, A05 Zitat/Verneinung/fremdes Ziel gebunden und „Handtasche“ innerhalb, A06 Antwort an den Avatar, A07 HTTP 200 „SQLite format 3“, A08 halbe Session übrig.
  - Am V65Z-Code: alle abgewehrt, gültige Gegenkontrollen gebunden.
- **`test_v65z_gegenproben.py`, 27 Tests** am echten Writer, Kernel, Reader, an den Flask-Routen und am Frontend-Server von START.py:
  - A01: Fact-ID als Quellturn; falsche neben richtiger Quelle; Selbstbezug; abgeleitete Kernel-Zeilen mit getypter Herkunft; Altzeilen gelistet, nicht umgeschrieben.
  - A02: sechs ungültige TurnTruths; God auf Puppet-TurnTruth und mit gefälschten Achsen; Kernel-God-Weg.
  - A03: fünf PATCH mit erfundener Person; PATCH einer Altzeile ohne Personenänderung; entfernte Writer und Katalog.
  - Zeugenwissen.
  - A04: sieben Taten (Eingabe, Wirkungsprüfung, Regie); Lesung am Tokenlimit (markiert, Rest bleibt Rede, keine Bitte-Bindung).
  - A05: Zitat; Verneinung; beide Taten mit Bindewort; ausgelassene zweite Tat; Ziel; Regie-Zitat; Körperstelle (Leser und Erlaubnislesung); Handtasche unter Grenze mit Hand-Ausnahme.
  - A06: Antwort an die Bedienperson; Name spricht den Avatar an.
  - A07: fünf Pfadproben am echten Handler.
  - A08: abgelehntes Kind → nichts gespeichert; gültiger Import neu verschlüsselt und ganz; Client ein Aufruf mit Allokator-ID.
  - MCC-Wiederherstellung zählt Altzeilen.
- **Am V65Y-Code:** 22 dieser Tests rot, 4 grün (Positivkontrollen: Kernel-God-Weg, PATCH einer Altzeile, Handtasche ohne Lesung, Name spricht Avatar an), 1 übersprungen (V65Y kennt die Altzeilen-Art nicht).
- **SOLL-Änderung älterer Tests (nicht abgeschwächt):** Testdaten, die TurnTruths ohne Rolle/Authority anlegten, binden jetzt Rolle und Authority: V58 zweimal, V65U `_pending`, V65V K5, V65W `_pending`, V65Y N03. V65W V01: Die Ursache des Regie-Effekts ist jetzt ein SceneFact der Session.
- **Regression V65Y gegen V65Z** (deine DB und Alt-DB, Endstand `regress_d`): 0 neu rot, 0 neu grün außer den 27 neuen Tests. Bestanden 561 → 588, je DB. Die 50 vorbestehenden Fehler sind unverändert.
- **prepare-Bytevergleich:** 2 DBs, 33 Sessions, 0 abweichend.
- **TypeScript:** 616, gleiche Menge wie V65Y. **Build** aus `src`: Exit 0, 42 Assets.
- **Altzeilen unter den V65Z-Prüfungen** (nur gelesen):
  - deine DB 43 (35× `FACT_SOURCE_INVALID`, 2× `RELATION_UNBOUND`, 6× `MEMORY_OWNER_UNBOUND`);
  - Alt-DB 40 in 11 Sessions;
  - 0 TurnTruth- und 0 Zeugenwissen-Zeilen außerhalb der neuen Grenze (der Kernel schreibt sie schon so).

### E2E am frisch entpackten Kandidaten-ZIP (START.py, echter Provider)
- **Lauf 1** (erster Kandidat, als Befund aufgehoben): Der Browser-Import scheiterte an 400 `PROVISIONAL_ID`, weil die neue Session-ID nicht vom Allokator kam. Behoben, Test ergänzt.
- **Lauf 2** (zweiter Kandidat, als Befund aufgehoben): Von 7 Taten kamen 6 an. Ursache: `finish_reason: length` bei 600 Tokens, die Reparatur verwarf die 7. Komponente still. Behoben, Test ergänzt. Der Import im Browser war hier bereits grün.
- **Lauf 3, Endkandidat:**
  - **A07:** fünf Pfadproben am UI-Port → 404; Kontrolle Asset und `/` → 200.
  - **Browser** (Ablauf V65U–V65Y):
    - React #418 0 auf 9 Routen, 0 Konsolen- und Seitenfehler, Reload und Sessionwechsel gleich.
    - Provider-Fehler zweimal voll bedient; die zweite Eingabe lief als Bedienperson.
    - Diagnose: Schreibgrenze und Kennung. Szenenübergang nur mit Auswahl.
  - **HTTP-Kette A** (Puppet):
    - Grenze für jede Berührung, Erlaubnis „meine Hand“.
    - „Ich halte deine Hand und küsse dich.“ → zwei Taten: Hand `accepted` (`grenze_ausnahme`), Kuss `declined`. „Ich nehme deine Hand.“ → `accepted`; „Ich küsse dich.“ → `declined`.
    - **A05:** „Ich küsse dich nicht.“ → keine Tat; „Ich sage zu dir: „Ich küsse dich.““ → keine Tat. Live hat hier schon die Lesung keine Tat vorgeschlagen; die Kernel-Prüfung ist im Test gezeigt.
    - **A04:** „Ich stehe auf. … Ich setze mich.“ → **7 Taten**.
    - **A01:** 23 Facts, jeder Quellturn ist eine TurnTruth.
  - **Kette B:**
    - God ohne Auswahl → gleiche Szene; Regie mit Auswahl → neue Szene.
    - `/facts`, `/god-facts` → 404; **A03:** `/turns`, `PATCH /memories/<id>`, `DELETE /relations/…` → 404.
    - Erfundene Beziehung → 422; manuelle Beziehung gestempelt.
  - **A06 Bedienperson im Browser:** „Bring mir bitte ein Bier, Mara.“ → Maras Rede an `user`, ihre Tat ohne Ziel. Bitte und offene Bitte der Bedienperson, 0 Beziehungen mit ihr.
  - **A08 Import im Browser:**
    - Gefälschte Packung → „Import abgelehnt, nichts gespeichert — … 422 MEMORY_OWNER_UNBOUND …“; Sessions 20 → 20.
    - Gültige Packung → neue Session; Facts 3/3, TurnTruths 3/3, Zeilen 4/4; alle IDs neu; jeder Quellturn in der neuen Session; 18 Beziehungen `provenienz: import`.
  - **Neustart:** Rücklesen aller vier Sessions (Browser, A, B, Import) gleich dem gespeicherten Stand, 0 Altzeilen in den neuen Sessions.
  - **Isolation:** 0 alte Zeilen verändert außer deinem Profil (`lastSessionId`, `avatarsByWorld`). Neue Zeilen nur mit den vier neuen Session-IDs, dazu eine Logzeile (Meldung des abgelehnten Imports). Config bytegleich, keine Sicherung übrig, 7 Original-Logs unverändert.

### SPS-Gates G1–G12 (Stand nach V65Z, über Oberfläche/Speicherung/Folgeturn/Neustart wo angegeben)

| Gate | Stand | Beleg |
|---|---|---|
| G1 Figurenwissen | TEILGEPRÜFT | Zeugenwissen nur Figur + SceneFact der Session (Test); keine eigene Wissensabnahme |
| G2 Körper und Fähigkeiten | NICHT GESAMT GEPRÜFT | Herkunft des Körperzustands getypt (Test); keine Körperabnahme |
| G3 Beziehungen | TEILGRÜN | Herkunft nach Art, Bedienperson keine Figur; live: erfunden 422, manuell und Import gestempelt, Neustart gleich |
| G4 Regie und Objekte | TEILGEPRÜFT | Regie: alle Komponenten, Zitat-Tat (Test), Szenenübergang live; Objekte nicht geprüft |
| G5 Avatar-Schutz | TEILGEPRÜFT | A06 live (Antwort nicht an den Avatar); keine eigene Avatar-Abnahme |
| G6 Persistenz | TEILGRÜN | falsche Zeilen nach erneutem Öffnen nicht vorhanden (A01–A03, A08); Neustart-Rücklesen gleich |
| G7 Benutzer-/Sessionisolation | TEILGRÜN | Besitzerprüfung (Test), Isolation E2E; keine Mehrbenutzer-Abnahme |
| G8 Writer und Reader | TEILGRÜN | alle Wege neuer Zeilen an derselben Grenze; MCC-Wiederherstellung als gezählte Ausnahme |
| G9 Zusammengesetzte Handlungen | TEILGRÜN | keine Kappung, abgeschnittene Lesung markiert; live 7/7 (Lauf 3); Zerlegung des Modells schwankt weiter |
| G10 Ablehnung und Einwilligung | TEILGRÜN | Kette A live; Körperstelle genau (Test) |
| G11 Session-/Stammtrennung | NICHT GESAMT GEPRÜFT | Stamm-Herkunft der Beziehungen; keine eigene Abnahme |
| G12 Frontend-Abdeckung | TEILGRÜN | Import live atomar, drei Writer ohne Aufrufer entfernt, jede API-Funktion hat einen Aufrufer (Test) |

### Offen / ROT
- **Keine Gesamtabnahme:** G1, G2, G4 (Objekte), G5 und G11 sind nicht als eigene Gesamtabnahme über die Oberfläche geprüft. „Nicht geprüft“ heißt nicht fehlerhaft, aber auch nicht grün.
- **A05 Grenzen der strukturellen Prüfung:**
  - Eine Verneinung, die die Lesung **in** das Segment nimmt („Ich gebe dir keinen Kuss“ als Tat), erkennt der Kernel nicht ohne Wortliste. Sie bleibt eine Modellentscheidung, der Tattext trägt die Verneinung.
  - Ein Zitat ohne Anführungszeichen („Er sagt, ich küsse dich“) ebenso.
  - Wessen Körperstelle („meine Hand“ des Handelnden) prüft weiter nur die Lesung.
- **A05 Folge (fail-closed):** Lässt die Lesung einen Satzteil weg, wird die Tat nicht gebunden. In deiner DB wären 2 von 20 gespeicherten Taten so abgelehnt worden („Ich lege mich auf sofa und warte“). Sie bleiben dann sichtbar Rede.
- **A04:** Die Zerlegung des Modells schwankt je Lauf (Altbestand V59C). Abgeschnittene Lesungen sind jetzt sichtbar, aber eine vom Modell ausgelassene Tat ohne Abschneiden bleibt Rede.
- **MCC-Wiederherstellung:** schreibt Altzeilen einer eigenen Sicherung wieder, gezählt statt abgelehnt. Bewusste Entscheidung nach §34.3; als Abweichung von „keine Zeile außerhalb der Grenze“ markiert.
- **Snapshot-Wiederherstellung:** läuft durch die Writer. Ein Snapshot mit Altzeilen wird abgelehnt (fail-closed, nichts verloren).
- **Unberührt (Negativliste):** `graph_edges` (KnowledgeGraph), keine Prüfung neu gebaut.
- **Unverändert offen:** Regex für den Ortswechsel im Regie-Client; Pronomen T32; Widerspruch-FP; Regie-FN; 616 TypeScript-Altfehler; Android; Mehrprozess; keine echte Anmeldung.

### Modellaufrufe
- **Entwicklung V65Z: 0** (Gegenproben und Tests ohne Modell).
- **E2E:**
  - Lauf 3 (Endkandidat): 112 (Browser 94, Kette A 17, Kette B 1, Import 0);
  - Lauf 2: 110;
  - Lauf 1: Kette 19, Browser nicht mehr genau zählbar (DB-Kopie mit Schlüssel verworfen), mindestens 23.
- **Gesamt V65Z: mindestens 264.**
- **Betrieb, geändert:**
  - Die Zerlegung einer Eingabe bzw. Regie-Anweisung hat mehr Raum (600 → bis 4000 Tokens, nach Länge). Gleiche Zahl an Aufrufen, längere Antworten bei langen Eingaben.
  - Je Komponente einer Eingabe mit Körperwirkung eine Wirkungsprüfung, jetzt auch ab der 7. Komponente.
  - Sonst wie V65Y.

**STATUS: TEILGRÜN.**
- A01–A08 am Writer/Kernel/Server grün mit festen Tests und Rücklesen.
- A01, A03, A04, A06, A07, A08 live über Oberfläche und Produktrouten am frischen ZIP gezeigt. A05 live nur so weit, wie die Lesung selbst keine Tat vorschlug. A02 nur im Test, weil es keine Route für TurnTruth oder God-Fakt mehr gibt.
- Zwei eigene Fehler im E2E gefunden und behoben: Import-ID, abgeschnittene Lesung.
- Gates wie oben. Keine Android- und keine AMASTER-Gesamtabnahme.

## SPS- UND VERTRAGSAUDIT zu V65Y · Vermerk (Eingang V65Z, 31.10.2026) – unverändert übernommen

Quelle: deine Zusammenfassung des SPS- und Vertragsaudits zu V65Y (Anhang vom 31.10.2026). Weggelassen ist nur die erste Zeile, die Anzeige der Denkzeit („1m 12s nachgedacht“). Die Gegenproben des Prüfers lagen nicht bei.

```text
### MATRIX10 V65Y – SPS- und Vertragsaudit

Prüfgrundlage: AMASTER `2_7master.txt`, SPS-Masterblatt V65Y, Reparaturvertrag §6 und §16, Originalcode V65Y und unabhängige Gegenproben.

### 1\. Festgestellte Vertragsverletzungen

| Nr. | Verbindliche Sollregel                               | Konkreter Fehler im V65Y-Code                                                                         | Audit                                |
| --- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------ |
| A01 | AMASTER §24.2, §34: gültige Herkunft vor Speicherung | repos.py:3159–3210 akzeptiert eine Fact-ID als sourceTurnId                                           | ROT – gespeichert und rückgelesen    |
| A02 | §46: God benötigt gültige Authority und Scope        | repos.py:3404 erlaubt unbelegte TurnTruth; God-Writer prüft die Rolle nicht vollständig               | ROT – God-Fakt gespeichert           |
| A03 | §6.2, §71.1.3: ungültige Identität niemals kanonisch | repos.py:3539, 3597: PATCH umgeht die neuen Identitätsprüfungen                                       | ROT – falsche Figuren gespeichert    |
| A04 | §24.2, §34.1: jede Handlung einzeln prüfen           | kernel.py:3479, 3574: components[:6] ignoriert weitere Handlungen                                     | ROT – siebte Handlung verloren       |
| A05 | §34.1, §36.5: Handlung und Einwilligung exakt binden | Zitate, Verneinungen, Ziele und Körperstellen werden nicht zuverlässig gegen den Originaltext geprüft | ROT – Gegenproben fehlgeschlagen     |
| A06 | §27.2: Bedienperson und Avatar trennen               | kernel.py:5877–5882: Maras Antwort kann Alrik statt der Bedienperson zugeordnet werden                | ROT – im Entwickler-E2E nachgewiesen |
| A07 | §71.1.2: technische Basissicherheit                  | START.py:183–226 ermöglicht Dateizugriff außerhalb des Frontend-Verzeichnisses                        | ROT – HTTP 200 reproduziert          |
| A08 | Reparaturvertrag §16: vollständige Speicherkette     | store.ts:1161–1185: Sessionimport schreibt Kinder einzeln, ohne gemeinsamen serverseitigen Rollback   | ROT im Code; Abbruch-E2E offen       |

Entscheidender Nachweis: Bei A01, A02 und A03 wurden ungültige Daten nicht nur angenommen. Sie waren nach erneutem Öffnen der SQLite-Datenbank weiterhin vorhanden.

Die erste falsche Stelle liegt also teilweise bereits vor dem kanonischen Commit, nicht erst bei der späteren KI-Antwort.

### 2\. SPS-Gates G1–G12

| Gate | Bereich                     | Abnahmestand                                    |
| ---- | --------------------------- | ----------------------------------------------- |
| G1   | Figurenwissen               | Nicht vollständig geprüft                       |
| G2   | Körper und Fähigkeiten      | Nicht vollständig geprüft                       |
| G3   | Beziehungen                 | ROT – Herkunft manipulierbar                    |
| G4   | Regie und Objekte           | Nicht vollständig geprüft                       |
| G5   | Avatar-Schutz               | Nicht vollständig geprüft                       |
| G6   | Persistenz                  | Teilweise bestanden, auch falsche Daten bleiben |
| G7   | Benutzer-/Sessionisolation  | Teilweise geprüft                               |
| G8   | Writer und Reader           | ROT – ungültige Fakten gelangen durch           |
| G9   | Zusammengesetzte Handlungen | ROT – Komponenten gehen verloren                |
| G10  | Ablehnung und Einwilligung  | Teilweise geprüft                               |
| G11  | Session-/Stammtrennung      | Nicht vollständig geprüft                       |
| G12  | Frontend-Abdeckung          | Teilweise geprüft, Import nicht atomar          |

Kein Nachweis für eine bestandene Foundation- oder Living-Core-Gesamtabnahme. Nicht geprüft bedeutet dabei nicht automatisch fehlerhaft.

### 3\. Widerspruch im SPS-Masterblatt

Das V65Y-Deckblatt behauptet:

> Eine Schreibgrenze für alle Wege.

Audit-Ergebnis: widerlegt. Die Schutzregeln sitzen nur an bestimmten Schreiboperationen. Andere Wege umgehen sie weiterhin.

Damit ist die zentrale Reparaturbehauptung des SPS-Deckblatts nicht erfüllt.

### 4\. Verbindliche Reparaturentscheidung

Die erste Reparatur muss gemeinsam diese Funktionen umfassen:

`TurnTruth` → `Effect-Bindung` → `Authority/Scope` → `Writer` → `SQLite` → `Reader` → `Current State`.

Keine stillen Kürzungen, keine ungeprüften PATCH-Wege, keine ungeprüfte Herkunft. Die Sicherheitslücke in `START.py` muss zusätzlich geschlossen werden.

Abnahmebedingung: Sämtliche negativen Gegenproben müssen korrekt abgewehrt werden, gültige Handlungen weiterhin funktionieren und G1–G12 über die tatsächliche Oberfläche, Speicherung, Folgeturn und Neustart nachgewiesen sein.

SPS-Auditentscheidung: ROT. V65Y erfüllt den verbindlichen Architektur- und Reparaturvertrag nicht vollständig.
```

## DECKBLATT · V65Y · Gesamtprüfung zu V65X: eine Schreibgrenze für alle Wege, Direkt-Writer entfernt, zusammengesetzte Tat fail-closed, Szenenübergang nur durch Auswahl (Claude) · 31.10.2026

**Verbindlich:**
- `2_7master.txt`:
  - §2 (Reset über die Oberfläche), §3 (lokal, kein versteckter zweiter Pfad, keine Demo als Ersatz);
  - §6 Z. 205–233 (Wahrheitshierarchie), §6.2 Z. 262 (fail-closed an kritischer Grenze), Nr. 2 (Modellklassifikation ist keine Wahrheit), Nr. 4 (kein Diagnose-/Direkt-Write);
  - §8 (der Nutzer ist keine Figur);
  - §20 Z. 949 (Szenenwechsel durch Nutzer, Regie, God …);
  - §34 Z. 1736–1772 (SceneFact bindet Quellturn, Actor, Target), §34.1 Z. 1774–1817 (Komponenten getrennt, eigene Validierung), §34.2 (Kausalprovenienz), §34.3;
  - §36.5 Z. 1947–1975; §44 (gerichtete Beziehung zwischen zwei Figuren);
  - §46.1–§46.6 Z. 2521–2601 (God/Regie, Scope, drei Scope-Achsen, UI-Auswahl bindet);
  - §71.1.2/§71.1.3 („Schutz vor direkten unautorisierten Writes“ nicht ALLOWED ABSENT; verbotene Abkürzungen).
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6, §16.

**Eingang:** Unabhängige Gesamtprüfung zu V65X (Gesamtbericht, Prüfskript `fresh_probes_20261031.py` mit Ergebnis, pytest-Logs, Manifest). Vermerk unten, unverändert.

**Basis:** mein V65X-ZIP (SHA256 `3f306562…`). DB und Logs bytegleich, keine Migration.

### Wurzel → Änderung (vorhandene Owner, keine neue Route, keine Tabelle, keine Wortliste)

| Befund | Wurzel am V65X-Code | Änderung |
|---|---|---|
| N01 SceneFact ohne Herkunft | Die Kinder-Writer in `repos` (die gemeinsame Schreibgrenze aller Wege) prüften nur den Besitzer; die Route `POST …/facts` gab sie dem Client direkt | **Schreibgrenze im Writer** (`_check_fact_boundary`): Actor ist eine Figur der Welt oder eine Kernel-Authority (`kernel`, `god`, `regie`, `observer`), Target eine Figur, und mindestens eine Quelle dieser Session existiert (TurnTruth, Zeile, Fact, Upload – gespeichert oder im selben Speichern). Sonst 422, nichts geschrieben. Route `POST …/facts` und `apiPostFact` entfernt. Kernel-Fehler mitbehoben: die Offenbarung trug `sourceTurnId=None` (jetzt die der Rede, §34.1) |
| N02 Beziehung zu erfundenen Figuren | `put_session_relation` ohne Identitäts- und Herkunftsprüfung | Beide Enden sind verschiedene Figuren der Welt. Eine **neue** Beziehung nennt ihre Herkunft: Fact/Quellturn der Session, Charakterstamm (`provenienz: stamm`), Duplikat oder **manueller Seed** der Social-Oberfläche – den stempelt die Route (`manuell`, wer, wann); vom Client gesendete Herkunft wird verworfen. Erstkontakt, Bewertungsfolge und God-Beziehung tragen jetzt ihre Ursache |
| N03 God-Fakt ohne Scope | `append_session_god_fact` ohne Prüfung; Route `POST …/god-facts` | God-Fakt nur mit TurnTruth der Session, Scope und den drei Achsen `truthScope`/`persistenceScope`/`epistemicScope` (+ `mutability`). Der Kernel bindet sie aus dem geprüften Scope-Schlüssel (§46.4/§46.5: Welt nur bei Auswahl „world“ dauerhaft, sonst Session; private Scopes nur dem Ziel bekannt). Route und `apiPostGodFact` entfernt |
| Weitere Kinder | Turns, Memories, Propositionen, Goals nahmen beliebige Personen-IDs an | Identität geprüft (neue Zeilen); Einstellungen speichern nur noch den Rahmen (`saveSession` schickt keine Kinder mehr) |
| P0-4 Altbestand | – | Gespeicherte Altzeilen werden **nicht** umgeschrieben. Die Diagnose zeigt sie (`schreibgrenze` in `GET /api/sessions/<id>`, Diagnose „Health prüfen“). Ein Server-Duplikat übernimmt sie nicht als neue Wahrheit (`LEGACY_ROWS_NOT_COPIED`) |
| N05 zusammengesetzte Tat | Unter „Fass mich nie wieder an“ machte eine genannte Ausnahme („meine Hand“) jede Tat, die die Hand nennt, `unknown` – auch mit Kuss | Die Grenze für jede Berührung **steht** (Current State, §34.1). Die Ausnahme deckt eine Tat nur, wenn deren eigene Lesung (`permission_reference_check`, neu) zeigt, dass **jeder** Teil drin bleibt: Teile wörtlich, die ganze Tat abgedeckt, jeder „innerhalb“-Teil nennt das Kopfwort der Ausnahme. Ein Teil außerhalb → `declined` mit `teilAusserhalb`; ohne Lesung → `declined`; innerhalb einer bestätigten Erlaubnis → `accepted` (`grenze_ausnahme`), innerhalb einer unbestätigten/zurückgenommenen → `unknown`. Eine allein stehende Teilerlaubnis bindet die Tat nur mit derselben Lesung (`erlaubnis_eingeschraenkt`). Der Leser prüft die Lesung am Fact-Text nach. Liest eine Komponente die ganze Eingabe, zählen nur ihre eigenen Teile (gilt auch für die Bitte) |
| N06 Szenenwechsel bei falscher Lesung | Ein Modellwert `verwendung=vollzug` mit wörtlichem Beleg erzeugte die `sceneId` | **Nur die ausdrückliche Auswahl** im Regie-/God-Bereich („Szenenübergang“: kein Übergang · neue Szene · Szene endet; Standard: kein Übergang) bindet den Übergang (§46.5 „UI-Auswahl bindet“). Die Textlesung ist entfernt: gemessen schrieb sie selbst bei Satz-Anker 4/54 falsche Übergänge („Die Tür führt in eine neue Szene des Stückes.“). Gilt auch, wenn die Regie-Zeile keine Figurentat bindet |
| G12 Abdeckung | `apiResetSessionRuntime`, `apiPostFact`, `apiPostGodFact`, `apiOcr` ohne Aufrufer; `/api/ocr` war ein Stub („local-stub“) | Alle vier Funktionen und ihre Routen entfernt (Laufzeit-Reset läuft über `/api/kernel/reset`, OCR im Browser). Routen-Katalog berichtigt. Neue Bedienelemente: Auswahl „Szenenübergang“; Diagnose zeigt Schreibgrenze und Kennung |
| Nachtrag Bedienperson (E2E am Kandidaten-ZIP) | Die Schreibgrenze kannte Figuren und Kernel-Authorities, aber nicht die Bedienperson. Der Kernel bindet sie selbst als Kennung `user` (`kernel._OPERATOR_IDS`, `default_input_actor_id`). Am frisch entpackten Kandidaten endete eine Eingabe als Bedienperson in `POST /api/kernel/prepare` **422 FACT_ACTOR_UNBOUND 'user'**: nichts gespeichert, kein Banner | Die Bedienperson ist ein möglicher Sprecher (§8 Z. 352 „nicht automatisch eine Figur“, Z. 1282 „realer Nutzer als Bedienperson“, §27.2 Z. 1374). Gebunden (`_operator_ids`, aus dem Kernel gelesen, keine zweite Liste) als Actor und Target eines SceneFacts, als Sprecher einer Zeile und als Partei/Eigentümer ihrer Bitte (Proposition, offene Bitte). **Keine Figur** für Beziehung (§44, V65F), Gedächtnis-Eigentümer und God-Ziel. Quelle bleibt Pflicht. Altbestand dadurch berichtigt: deine Session 05:33 hat 8 Altzeilen (2 Beziehungen Mara↔user, 6 Gedächtnisse mit Eigentümer „user“), nicht 36 |
| Benutzerkennung | `X-Matrix-Actor` ist eine Profilwahl, keine Anmeldung | AMASTER §2/§3 verlangt lokale Profile ohne Cloud-Login. Gekennzeichnet: `GET /api/health` → `identitaet` (lokales Profil, keine Anmeldung, nur 127.0.0.1), sichtbar in der Diagnose. Keine Anmeldung gebaut |

### Gegenproben und Tests (0 Modellaufrufe)
- **`test_v65y_gegenproben.py`, 28 Tests** am echten Writer, Kernel, Reader und an den Flask-Routen, meist mit SQLite-Rücklesen:
  - N01: erfundener Actor, Actor ohne Quelle und erfundenes Ziel → 422, nichts geschrieben; der Kernel-Weg schreibt weiter; `POST …/facts` gibt 404.
  - N02: Beziehung zwischen erfundenen oder gleichen IDs und mit „user“ → 422; neue Beziehung ohne Herkunft intern abgelehnt; manueller Seed gestempelt (wer, wann).
  - N03: God-Fakt ohne Quellturn bzw. ohne Scope-Achsen → 422; der Kernel bindet die drei Achsen, nach dem Neuöffnen gleich; `POST …/god-facts` gibt 404.
  - N04: ein anderer behaupteter Actor bleibt gesperrt (Positivkontrolle).
  - N05: Mischtat ohne Lesung `declined`; mit Lesung für den Kuss `declined`, nach dem Neuöffnen gleich; gefälschtes „innerhalb“ für den Kuss wirkt nicht; Hand allein in bestätigter Ausnahme `accepted`; in unbestätigter `unknown`; allein stehende Teilerlaubnis bindet nur die Tat in ihr.
  - N06: kein Modellwert und kein Wortlaut erzeugt eine neue Szene; die Auswahl bindet den Übergang, auch wenn die Regie-Zeile keine Tat bindet.
  - N07: Altzeilen werden gelistet, nicht umgeschrieben; ein Duplikat übernimmt sie nicht.
  - G12: jede exportierte API-Funktion hat einen Aufrufer, kein direkter kanonischer Writer bleibt; Einstellungen schicken keine Kinder. Kennung als „nur lokal“ gekennzeichnet.
  - Live gefunden: eine Komponente, deren Lesung die ganze Eingabe zerlegt, zählt nur ihre eigenen Teile (Erlaubnis und Bitte).
  - Nachtrag Bedienperson: Eingabe, Antwort und offene Bitte der Bedienperson werden gespeichert und nach dem Neuöffnen gelesen (0 Altzeilen); Beziehung, Gedächtnis-Eigentümer und erfundener Actor bleiben abgelehnt.
- **Am V65X-Code:** 26 dieser Tests rot, 2 grün (Positivkontrollen: Besitzerprüfung, Kernel-Weg).
- **SOLL-Änderung älterer Tests (nicht abgeschwächt):**
  - V58 Goal-Vertrag: die Lebenszyklus-Evidenz nennt jetzt ihren echten Quellturn der Session (§34).
  - V65W: Übergang über die Auswahl statt über die entfernte Textlesung; die Regie-Wirkung schreibt nur mit echter TurnTruth.
  - V65X: Textlesung entfernt (N06); ohne Ausnahmelesung steht die Ablehnung für jede Berührung (`declined` statt `unknown`, N05).
- **Regression V65X gegen V65Y** (deine DB und Alt-DB, Endstand mit Nachtrag): 0 neu rot, 0 neu grün außer den 28 neuen Tests. Bestanden 533 → 561 (deine DB) und 533 → 561 (Alt-DB). Die 50 vorbestehenden Fehler sind unverändert. Alt-DB: Daten deines V65P-ZIP (die frühere Alt-DB lag im verlorenen Arbeitsbereich).
- **prepare-Bytevergleich:** 2 DBs, 33 Sessions, 0 abweichend (nach dem Nachtrag neu gerechnet).
- **TypeScript:** 616 vorbestehend, gleiche Menge wie V65X. **Build** aus `src`: Exit 0, 42 Assets (src-Hash `0606e499…`).

### Messungen (Modell, T=0, je 2 Läufe, Kernel eingerechnet)

| Lesung | Endfassung | FP | verworfen / Hinweis |
|---|---|---|---|
| Erlaubnisbezug einer Tat (neu, N05) | 22/26 | 0 | v1 18/22 mit 2 FP („Ich lege meine Hand auf deine Schulter“) → Körperstelle von `ziel` in der Regel. 4 FN: lehnt zu streng ab (fail-closed) |
| Szenenübergang aus dem Text | – | – | entfernt: v1 („ganzer Satz“) 50/54, 4 FP; v2 51/54, 3 FP; v3 50/54, 4 FP („Die Tür führt in eine neue Szene des Stückes.“). Kein Prompt erreichte 0 FP |

### E2E am frisch entpackten Kandidaten-ZIP (START.py)
- **Lauf 1** (Kandidat MD5 `2d775513…`) **fand einen Fehler meiner Schreibgrenze:** Nach Reload stand der Modus auf „Als Bedienperson“. Die Eingabe endete in `POST /api/kernel/prepare` 422 `FACT_ACTOR_UNBOUND 'user'` (nichts gespeichert, kein Banner). Wurzel und Behebung: Tabellenzeile „Nachtrag Bedienperson“ oben. Der Browserlauf brach danach ab, bevor er den Provider-Endpoint zurücklegte. Kette A lief deshalb gegen den Fehler-Endpoint. Lauf 1 ist ungültig und nur als Befund aufgehoben. Ich habe die Config bytegleich zurückgelegt und die Sicherung gelöscht. Die Werkzeuge legen sie jetzt auch im Fehlerfall zurück und prüfen den Endpoint nach dem Lauf.
- **Lauf 2, Endkandidat (MD5 `dfa42a8d…`):**
  - **Browser** (Ablauf V65U–V65X): React #418 0 auf 9 Routen, 0 Konsolen- und Seitenfehler. Reload gleich, Sessionwechsel gleich.
  - **Provider-Fehler** zweimal vollständig bedient: Banner; „Antwort erneut erzeugen“ → Maras Antwort; „ohne Antwort abschließen“ → Systemzeile, die Eingabe bleibt. Die zweite Eingabe lief als Bedienperson, über `prepare` ohne 422.
  - **Browser-Zusatz V65Y:** Diagnose zeigt „Schreibgrenze 0 Altzeilen“ und „Kennung Profilwahl ohne Anmeldung; nur auf diesem Rechner (127.0.0.1)“. Die Auswahl „Szenenübergang“ ist vorhanden, Standard `keiner`. „Neue Szene beginnt“ + Regie-Zeile → neue `sceneId` mit `previousSceneId`, danach steht die Auswahl wieder auf `keiner`. „Neue Szene: Am nächsten Morgen im Garten.“ ohne Auswahl → gleiche `sceneId`.
  - **Bedienperson im Browser:** „Bring mir bitte ein Bier, Mara.“ ergibt einen Rede-Fakt mit Actor `user`, Maras Antwort, eine Proposition und eine offene Bitte der Bedienperson. 0 Beziehungen mit der Bedienperson, 0 Altzeilen, keine offene Eingabe.
  - **HTTP-Live-Kette A** (Puppet, echter Provider):
    - Mara: „Fass mich nie wieder an, Johann!“ → Grenze `jede_beruehrung`, validiert.
    - Mara: „Du darfst meine Hand halten.“ → eingeschränkte Erlaubnis „meine Hand“, validiert.
    - „Ich halte deine Hand und küsse dich.“ hat die Zerlegung live in zwei Taten geteilt: „küsse dich“ → `declined` (Grenze); „Ich halte deine Hand“ → `accepted` (`grenze_ausnahme`, Lesung: ein Teil, innerhalb).
    - „Ich nehme deine Hand.“ → `accepted` (`grenze_ausnahme`). „Ich küsse dich.“ → `declined`.
  - **Session B:**
    - God „Neue Szene: …“ ohne Auswahl → gleiche `sceneId`; Regie mit `neue_szene` → neue `sceneId` mit `previousSceneId`.
    - `/facts` und `/god-facts` → 404. Beziehung mit erfundener Figur → 422 `RELATION_UNBOUND`. Manuelle Beziehung → `provenienz {quelle: manuell, durch: admin, am}`; die vom Client gesendete Herkunft ist verworfen.
    - God-Fakten tragen `truthScope szene`, `persistenceScope session`, `epistemicScope anwesende`, Quellturn.
    - Deine Altsession 05:33 zeigt 8 Altzeilen (2× `RELATION_UNBOUND` Mara↔user, 6× `MEMORY_OWNER_UNBOUND`).
  - **Neustart:** Das Rücklesen über die Route ist für alle drei Sessions gleich dem gespeicherten Stand. Verglichen wurden Facts, Turns, TurnTruths, Propositionen, Ziele, Beziehungen, God-Fakten, `sceneState`, Gedächtnis, Zeugenwissen und offene Eingabe; `schreibgrenze` ist nur die Lesesicht der Route. Einwilligungen A: `unknown, declined, accepted, accepted, declined`. Der Bedienperson-Turn trägt `input_actor_id user`, `speak_as operator`. Keine offene Eingabe.
  - **Isolation:** 0 alte Zeilen verändert außer deinem Profil `admin` (nur `lastSessionId`, `avatarsByWorld`). Neue Zeilen nur mit den drei neuen Session-IDs. Config bytegleich, keine Sicherung übrig. Deine 7 Original-Logs unverändert; dazu kommt je Start ein neues Live-Log (V65F-Verhalten).

### Offen / ROT
- **Neu gefunden, Altbestand (in V65X gleich):**
  - Maras Antwort auf die Bedienperson wurde bei anwesendem Avatar dem Avatar Alrik zugeordnet (`targetId char_2f8617b4`), obwohl die Eingabe „außerhalb der Welt“ gebunden war (§27.2 Z. 1374).
  - Wurzel: `kernel.py` Z. 5877–5882. Die Bedienperson wird nicht als Ziel-Kandidat übergeben, weil sie nicht anwesend ist. Deshalb bindet `resolve_target_detail` das „dir“ an eine anwesende Figur. Der Rückfall auf die Bedienperson greift nur, wenn gar kein Ziel gefunden wird.
  - Nicht in V65Y gepatcht. Das wäre der nächste Schritt.
- **N05 live:** Die Puppet-Zerlegung hat die Mischtat in zwei Taten geteilt. Der Fall „eine ungeteilte Tat mit einem Teil außerhalb“ (`teilAusserhalb`) ist nur im Test gezeigt. Die Zerlegung schwankt je Lauf (Altbestand V59C).
- Die Erlaubnislesung lehnt in 4 von 26 Messläufen zu streng ab (kein Fehlurteil „erlaubt“).
- **N06 Verhaltensänderung:** Ein Text wie „Neue Szene: …“ wechselt die Szene nicht mehr von selbst; dafür braucht es die Auswahl.
- **Kennung:** keine echte Anmeldung, nur gekennzeichnet (AMASTER §2/§3: lokal, ohne Cloud-Login).
- Unverändert offen: Regex im Regie-Client für den Ortswechsel (Altbestand); Pronomen T32; Widerspruch-FP; Regie-FN; 616 TypeScript-Altfehler; Android; Mehrprozess.

### Modellaufrufe
- **Entwicklung V65Y: 275** (Messungen 236, Live-Vorläufe 39).
- **E2E Lauf 2: 106** (Browser 89, Bedienperson 4, Kette A 12, Kette B 1).
- **E2E Lauf 1 (ungültig):** Kette 7 (alle gegen den Fehler-Endpoint). Browser nicht mehr genau zählbar, weil die DB-Kopie mit dem Schlüssel verworfen ist; laut Serverprotokoll mindestens 21 Anfragen.
- **Gesamt V65Y: mindestens 409.**
- **Betrieb, geändert:**
  - −1 je Regie-/God-Zeile (Szenenlesung entfällt);
  - +1 je Ausnahme oder eingeschränkter Erlaubnis, die eine Körpertat nennt (Erlaubnislesung, selten);
  - sonst wie V65X.

**STATUS: TEILGRÜN.**
- N01–N03, N05, N06 und G12 am Writer/Kernel grün mit festen Tests und live über die Produktrouten am frischen ZIP gezeigt. N05 live nur als zerlegte Mischtat. N04 (Besitzerprüfung) und N07 (Persistenz) sind Positivkontrollen und bleiben grün; N07 auch live über die Altsession-Anzeige.
- Ein eigener Fehler (Bedienperson) ist im E2E gefunden und behoben.
- Offen wie oben. Keine Android- und keine AMASTER-Gesamtabnahme.

## GESAMTPRÜFUNG zu V65X · Vermerk (Eingang V65Y, 31.10.2026) – unverändert übernommen

Quelle: deine Zusammenfassung der unabhängigen Gesamtprüfung zu V65X (Anhang vom 31.10.2026) und der Gesamtbericht `GESAMTBERICHT_MATRIX10_V65X_20261031.md`. Weggelassen ist nur die erste Zeile der Zusammenfassung, die Anzeige der Denkzeit („13m 3s nachgedacht“). Prüfskript `fresh_probes_20261031.py` mit Ergebnis, pytest-Logs und Manifest liegen unverändert in `scripts/v65y_gegenproben/gesamtpruefung_v65x/`.

```text
### MATRIX10 / ChatHere – Gesamtprüfung V65X

Prüfstand: 31. Oktober 2026 · Grundlage: Originalcode V65X, `2_7master.txt` und `MATRIX10_SPS_MASTER.md`

### 1\. Erster gesicherter Hauptbefund

Gesamtabnahme nicht bestanden

Die aktuelle Version enthält funktionierende Teilbereiche, aber die Architektur ist noch nicht durchgehend vertragskonform.

Ein besonders schwerwiegender Fehler wurde bei meiner neuen Prüfung direkt reproduziert:

Der zuständige Datenbank-Writer akzeptiert einen künstlich erzeugten Ereignis-Fakt, obwohl ihm die gültige Herkunft (`sourceTurnId`) und eine korrekt gebundene handelnde Figur fehlen.

Das Ergebnis meiner unabhängigen Probe:

* Der Writer meldet `inserted`.

* Der Fakt wird tatsächlich in SQLite gespeichert.

* Der reguläre Session-Reader liest ihn anschließend als vorhandenen Fakt.

* Eine vorherige Prüfung durch den semantischen Effect-Planer wurde nicht benötigt.

Das widerspricht der im AMASTER vorgesehenen Bindung von Eingabe, Validierung, kanonischem Writer und zulässigem Reader.

Wichtig: Diesen Fehler habe ich direkt am echten Repository-Writer mit einer getrennten Datenbankkopie nachgewiesen. Die zugehörige HTTP-Route existiert ebenfalls im Code; ein vollständiger HTTP-Angriffstest ist damit noch nicht erbracht.

Die 24 gezielten Korrekturtests von V65X bestehen dagegen vollständig. Das zeigt: Einzelne Reparaturen funktionieren, aber das Gesamtsystem besitzt weiterhin offene Architekturgrenzen.

### 2\. Weitere unabhängig festgestellte Fehler

| Bereich            | Ergebnis                    | Bedeutung                                                                                                                         |
| ------------------ | --------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Beziehungen        | Fehler bestätigt            | Nicht existierende Figuren lassen sich als Beziehungspartner speichern.                                                           |
| Einwilligung       | Fehler bestätigt            | Eine zusammengesetzte Handlung („Hand halten und küssen“) wird als unknown eingeordnet, obwohl der Kuss für sich declined ergibt. |
| Szenenwechsel      | Fehler bestätigt            | Bei einer bewusst falschen Modellklassifikation kann eine bloße Erwähnung als neuer Szenenwechsel gelten.                         |
| Benutzerzuordnung  | Sicherheitslücke im Konzept | Die API vertraut auf eine vom Browser gelieferte Benutzerkennung. Das ist keine echte Authentifizierung.                          |
| Frontend-Abdeckung | Vertragslücke               | Für den direkten Fact-Writer existiert eine Backend-Route, aber kein aufrufender Bedienpfad im aktuellen Frontend-Quellcode.      |

Bei den letzten beiden Punkten ist die Einordnung wichtig: Die Anwendung bindet ihre Server standardmäßig an `127.0.0.1`. Ich behaupte deshalb keinen nachgewiesenen Angriff über das Internet. Auch der Szenenfehler beweist nicht, wie oft ein echtes Sprachmodell falsch klassifiziert. Er beweist, dass der anschließende Prüfer eine solche Fehlklassifikation durchlassen kann.

### 3\. Was tatsächlich funktioniert

Es gibt auch direkt bestätigte positive Ergebnisse:

* 24 von 24 gezielten V65X-Korrekturtests bestanden.

* 481 weitere Tests bestanden im ausgeführten Regressionsteil.

* Der Python-Quellcode lässt sich kompilieren.

* Die mitgelieferte SQLite-Datenbank besteht die strukturelle Prüfung.

* Der ausgelieferte Frontend-Build stimmt mit den 86 Quelldateien überein; alle 42 gelisteten Assets sind vorhanden, die Hashes stimmen, und keine im HTML referenzierte Asset-Datei fehlt.

Damit ist der Stand besser als ein bloßes Konzept. Aber ein korrekter Build und viele grüne Unit-Tests beweisen nicht, dass Figurenwissen, Folgen, Regie und Bedienoberfläche über alle Produktwege korrekt zusammenspielen.

### 4\. Testabdeckung und Einschränkungen

Eine Präzisierung zu den Testzahlen: Die 24 erfolgreichen V65X-Tests sind bereits in den 481 erfolgreichen Tests der größeren ausgeführten Teilsuite enthalten. Sie dürfen nicht nochmals dazugerechnet werden.

| Neue Ausführung                                      | Ergebnis                                                                        |
| ---------------------------------------------------- | ------------------------------------------------------------------------------- |
| V65X-Korrekturtests separat                          | 24 bestanden                                                                    |
| Größere Python-Teilsuite                             | 481 bestanden, 50 fehlgeschlagen, 1 übersprungen, 4 Setupfehler                 |
| Davon auf fehlende Flask-Laufzeit zurückzuführen     | 32 Fehlschläge und 4 Setupfehler                                                |
| Davon auf fehlende Test-Ausgangsdaten zurückzuführen | 18 Fehlschläge                                                                  |
| Eigene unabhängige Repository-/Logikproben           | 7 Prüffälle ausgeführt, darunter bestätigte Fehler und positive Gegenkontrollen |

Die 50 Fehlschläge sind daher nicht mit 50 bestätigten Programmfehlern gleichzusetzen. Die Testsuite ist in dieser Umgebung nicht vollständig ausführbar. Ein echter HTTP-/Browser-/Provider- und Android-Gesamtlauf ist weiterhin offen.

Der entscheidende Unterschied: Meine neuen Gegenproben haben tatsächliche problematische Schreib- und Entscheidungsabläufe nachgewiesen – nicht nur fehlgeschlagene Testvoraussetzungen.

### 5\. Gesamtbewertung

Technischer Reifegrad – meine Bewertung

### 4/10

Nicht freigabereif

| Bereich                                      | Bewertung                                   |
| -------------------------------------------- | ------------------------------------------- |
| Frontend-Paket und Dateikonsistenz           | Gut                                         |
| SQLite und grundlegende Persistenz           | Gut, aber fachlich unzureichend abgesichert |
| Benutzer-/Session-Zuordnung                  | Teilweise funktionierend                    |
| Kanonische Wahrheit und Writer               | Kritisch                                    |
| Einwilligung und zusammengesetzte Handlungen | Fehleranfällig                              |
| Regie, God und Rollenbindung                 | Nicht abgenommen                            |
| Wissen, Memory und Folgeturn                 | Nicht vollständig nachgewiesen              |
| Frontend-/Backend-Abdeckung                  | Unvollständig                               |

Die Note ist eine technische Gesamteinschätzung, keine errechnete Prozentzahl der bestandenen AMASTER-Anforderungen.

### 6\. Was zuerst korrigiert werden muss

Priorität 1: Die Wahrheitsschicht reparieren. Kein Ereignis, keine God-Anweisung und keine Beziehungsänderung darf direkt kanonisch werden, ohne die zuständige Identitäts-, Scope-, Effect- und Provenienzprüfung zu bestehen. Das muss an der gemeinsamen Schreibgrenze gelöst werden, nicht durch weitere einzelne Textfilter.

Priorität 2: Zusammengesetzte Handlungen korrekt zerlegen. Handhalten, Küssen, Sprechen und andere selbstständige Wirkungen müssen einzeln bewertet und anschließend kausal verbunden werden. Eine Teilerlaubnis darf nicht die Prüfung einer anderen Handlung verdecken.

Priorität 3: Frontend und Backend vollständig verbinden. Jede produktive Backendfunktion braucht einen realen und verständlichen Bedienweg oder eine ausdrücklich vorgesehene Anzeige-/Diagnosefunktion. Ungenutzte direkte Schreibwege müssen entfernt oder abgesichert werden.

Priorität 4: Abnahme mit wirklichen Produktketten. Erst danach sind die AMASTER-Gates G1 bis G12 sinnvoll vollständig zu prüfen: von der Benutzeraktion über die Datenbank bis zur sichtbaren Folge nach einem Neustart.

### 7\. Vollständiger Prüfbericht

Ich habe den Gesamtbericht mit AMASTER-Abgleich, SPS-Bewertung, sieben eigenen Prüfungen, Fehlerursachen, Prioritäten, Quellstellen und einer Bewertung aller zwölf Gates erstellt.

Gesamtbericht als TXT

Gut lesbar, auch mit Sprachausgabe

Gesamtbericht als Markdown

Vollständig gegliederte technische Fassung

Prüfnachweise als ZIP

Testskript, Ergebnisse, Prüflogs, Hashes und Bericht

Mein abschließendes Urteil: Die technische Grundlage ist vorhanden. Der Hauptfehler liegt nicht darin, dass zu wenig programmiert wurde, sondern dass mehrere Schreib- und Entscheidungswege noch nicht denselben verbindlichen AMASTER-Vertrag durchsetzen. Solange das nicht behoben ist, können auch viele bestandene Tests keine verlässliche Gesamtfunktion garantieren.

Am Originalprojekt habe ich nichts verändert. Alle schreibenden Prüfungen erfolgten auf einer getrennten Datenbankkopie.
```

```text
# MATRIX10 / ChatHere - unabhaengige Gesamtpruefung V65X

**Pruefdatum:** 31.10.2026  
**Pruefart:** Originalarchiv, normativer AMASTER, SPS-Masterblatt, Quellcode, direkte SQLite-/Kernel-Pruefungen, frische Regressionen, Frontend-Backend-Abgleich.  
**Produktversion:** MATRIX10_V65X_LEBENSZYKLUS_20261030.zip  
**Urteil:** **NICHT FREIGEGEBEN / FOUNDATION NICHT ABGENOMMEN / LIVING CORE NICHT ABGENOMMEN.**  
**Technische Reifegradbewertung:** **4/10** (begruendete Sachverstaendigen-Einschaetzung, keine mathematische Testquote).

## 0. Kurzfazit

V65X ist ein umfangreiches, teilweise funktionierendes Softwareprodukt mit reproduzierbarer SQLite-Persistenz, umfangreichen Kernel-Komponenten, einem statisch konsistenten Frontend-Paket und nachweislich erfolgreichen Korrekturtests. Der gelieferte Stand genuegt aber den eigenen Vertragsanforderungen fuer kanonische Wahrheit und Scope nicht.

Die schwerste Wurzel ist eine **ueber die produktiven API-Routen erreichbare direkte Schreibschiene**. Sie erlaubt Ereignis- und God-Fakten, die den normalen validierten Turn-/Effect-/Authority-Pfad umgehen. Verwandte Schwaechen bestehen bei Beziehungen, Rollen-/Identitaetsannahmen, zusammengesetzten Handlungen und der Verwendung von Modellurteilen. Verschiedene Backendfunktionen haben keinen aufrufenden Frontend-Code, obwohl die Nutzeranforderung eine Bedienoberflaeche fuer produktive Backendfaehigkeiten verlangt.

Die groesseren Testzahlen sind kein Freigabeschein: Die aktuelle Ausfuehrung ergab 481 bestandene Tests, aber die Testsammlung war nicht vollstaendig reproduzierbar; ein echter Browser-/HTTP-/LLM-/Android-End-to-End-Nachweis fehlt. Die 24 bestandenen V65X-Zieltests sind **in diesen 481 enthalten**, nicht zusaetzlich.

**Empfehlung:** Keine weitere Kosmetik, weitere Wortstamm-Sonderregeln oder vollmundige Versionsfreigabe. Zuerst ein gemeinsames validiertes Schreib-Gateway und durchgaengige UI/Backend-Ketten, danach echte Gate-Tests.

## 1. Gepruefte Originalquellen und Integritaet

| Quelle | SHA-256 / Angabe | Beobachtung |
|---|---|---|
| Lieferarchiv `MATRIX10_V65X_LEBENSZYKLUS_20261030.zip` | `3f306562e75c3b97737e419300d6a5cd6312127a81f63f8c6bf4101855acf6a8` | Original unveraendert |
| `2_7master.txt` im Archiv | `095d455460390dfd0ae46e6938126e44a51293461d070204358d301f00609a7f` | Vorrangiger SOLL-Vertrag |
| `MATRIX10_SPS_MASTER.md` im Archiv | `99eee40e8f7cb13e7489279ee5323793a50987bbedbcf5e7af492b7c077fd355` | Aktuelles SPS-Blatt, beginnt mit V65X, meldet selbst nur TEILGRUEN |
| `data/matrix10.sqlite` | `9be11b8410c4396eb731254f997dfed3095cd6c65c048bc04e80cd3e8c2d4003` | 36.769.792 Bytes, `PRAGMA quick_check = ok` |

**SOLL-Punkte aus AMASTER:** Datenrollen und einzige Owner nach Paragraph 6.2; TurnTruth, Identitaet und semantische Effect-Bindung nach Paragraphen 23-24.7; Regie/God/Avatar/Puppet nach 27.3-27.6 und 46; getrennte Effects und Provenienz nach 34.1-34.3; Einwilligung nach 35-36.5; kausales Figurenwissen nach 38-41; gerichteter Relationship-State nach 44; LLM nicht als Wahrheit nach 49-51; volle Kette nach 69; Abnahmeregeln und Gate-Tests nach 71.0.5, 71.1 und 71.2.

**SPS als IST-/Verlaufsblatt, nicht als Ergebnisbeweis:** Der V65X-Abschnitt verzeichnet 24 gezielte Korrekturtests und benennt bereits offene Grenzen. Fruehere Angaben zu Live-Providern, Browsern, 533/551 Regressionen und TypeScript-Diagnosen wurden nicht als frisch bewiesene Ergebnisse uebernommen.

## 2. Tatsaechlich neu durchgefuehrte Pruefungen

### 2.1 Laufende Tests

| Test | Ergebnis | Belastbare Aussage |
|---|---|---|
| `pytest -q matrix_api/tests/test_v65x_gegenproben.py` | **24 bestanden** | V65X-Zieltests am unveraenderten Produkt neu ausgefuehrt, nicht neu ausgesucht |
| Python-Teilsuite (2 Flask-pflichtige Testmodule schon bei Collection ausgenommen) | **481 bestanden / 50 fehlgeschlagen / 1 uebersprungen / 4 Setupfehler** | 24 Zieltests sind Teil dieser 481; keine Gesamtfreigabe |
| Aufschluesselung der 50 Fehlschlaege | **32 Flask-Laufzeit fehlt; 18 fehlende spezielle Test-Session** | Fehlende Testvoraussetzungen, kein Beweis fuer 50 voneinander unabhaengige Produktfehler |
| Vier Setupfehler | **Flask-Laufzeit nicht verfuegbar** | HTTP-bezogene Tests nicht ausfuehrbar |
| Python-Kompilation | **erfolgreich** | Syntaktisch importierbare/kompilierbare Python-Module, keine Funktionsabnahme |
| SQLite quick_check | **ok** | Strukturelle Konsistenz, keine semantische Datenbankfreigabe |
| Neue adversariale Proben | **7 ausgefuehrt** | Original-Repository, Scene-State und Kernel, isolierte Datenbankkopie, Positiv- und Negativkontrollen |

Die fehlende Flask-Installation konnte hier nicht online nachinstalliert werden. Ohne Flask kein echter HTTP-Test. Die neu ausgefuehrten Repositoryproben nutzen nur fuer den Import des unabhaengigen Repository-Layers eine minimale `flask`-Platzhalterreferenz; die fachliche Writer-/Reader-/Kernel-Logik wurde nicht nachgebaut oder ersetzt. Diese Proben sind **nicht** als AMASTER-End-to-End-Gates deklariert.

### 2.2 Unabhaengig durchgefuehrte Negativ- und Positivproben

**N01 - Canonical SceneFact ohne Herkunft: FEHLER BESTAETIGT / P0**

- `repos.append_session_fact` mit gueltigem Session-Besitzer, aber `actorId=char_nonexistent` und `sourceTurnId=null` aufgerufen.
- Original-Writer lieferte `write=inserted`.
- SQLite enthaelt den Fakt; `repos.get_session` lieferte ihn als Session-Fakt.
- Ein Semantic-Effect-Planer oder eine Plausibilitaetspruefung der handelnden Figur wurde auf diesem Schreibpfad nicht erzwungen.
- Produktive Route: `app.py:914` `POST /api/sessions/<session_id>/facts` -> direkter Repositorywriter `repos.py:3095`.
- Verstoss gegen den AMASTER-Vertragsanspruch an gueltige kanonische Herkunft und Actor-Bindung (Paragraphen 6.2, 24.2, 34.1, 71.1.3). Kein HTTP-Aufruf in dieser Probe.

**N02 - Beziehung zwischen erfundenen Figuren: FEHLER BESTAETIGT / P0**

- `repos.put_session_relation` mit `fromId=char_nonexistent_from`, `toId=char_nonexistent_to`, `sourceTurnId=null` ausgefuehrt.
- Rueckgabe `inserted`; kanonisch in SQLite gespeichert; Session-Reader zeigt Eintrag.
- Die Besitzerpruefung wirkt, aber es fehlt die serverseitige referenzielle Bindung an echte Figuren und eine passende Aenderungsprovenienz.
- Route `app.py:949`; Writer `repos.py:3484`.
- Zu unterscheiden: Ein absichtlicher, ueber Social-UI bedienter manueller Startwert ist moeglich. Dann muss er explizit als solcher mit Benutzer/Scope/Grund behandelt werden, nicht stillschweigend als Folge eines nie stattgefundenen Events.

**N03 - God-Fakt ohne Wahrheitshoheit/Scope: FEHLER BESTAETIGT / P0**

- `repos.append_session_god_fact` nimmt einen God-Fakt ohne `sourceTurnId`, `truthScope` und `persistenceScope` an.
- Rueckgabe `inserted`, nach Datenbank-Commit im Session-Reader sichtbar.
- Produktive Route `app.py:928` (`/god-facts`), Writer `repos.py` im Bereich ab 3154.
- Kritisch insbesondere bei Regie/God, weil AMASTER einen explizit gebundenen und geprueften Truth-/Persistence-/Epistemic-Scope fordert.

**N04 - Besitzer-Gegenkontrolle: SCHUTZ WIRKT**

- Eine Session-Schreiboperation mit einer abweichenden angegebenen Actor-Kennung wurde abgelehnt (`session not owned by actor`).
- Kein unberechtigter Fakt wurde dabei geschrieben.
- Das ist eine positive Owner-Isolation, **aber keine Benutzer-Authentifizierung**: Der Headerwert selbst wird clientseitig behauptet.

**N05 - Gemischte Koerperhandlung: SCHWACHE SEMANTISCHE GRENZE BESTAETIGT / P1**

- Mit echter Kernel-/Scene-State-Logik: globale Ablehnung weiterer Beruehrung, danach Ausnahmesaussage zum Halten der Hand.
- Zusammengesetzte Tat `Ich halte deine Hand und kuesse dich` ergab `unknown`.
- Einzeltat `Ich kuesse dich` ergab `declined`.
- Die Ausnahme einer Teilhandlung darf das verbotene andere Teilereignis nicht unbemerkt neutralisieren. Erforderlich ist die Zerlegung in selbststaendige, einzeln validierte Effects.
- Einschraenkung: Es handelt sich um eine direkt an den Kernel uebergebene zusammengesetzte Aktionskomponente. Ob die Live-Modellzerlegung sie rechtzeitig splitten wuerde, wurde nicht gemessen. `unknown` ist nicht `accepted`, aber die korrekte Teilablehnung geht verloren.

**N06 - Szenenwechsel trotz bloesser Nennung: FEHLER BEI FALSCHER MODELLKLASSIFIKATION / P1**

- `scene_state.scene_transition_verdict` erhielt absichtlich einen irrefuehrenden Modellwert `verwendung=vollzug` mit dem Beleg `neue Szene`.
- Zwei eindeutige Nennungen und ein metaphorischer Theaterbezug wurden jeweils als `neue_szene` entschieden.
- Belegt ist die unzureichende Absicherung gegen falsche LLM-Urteile. **Nicht** belegt ist, dass ein realer Provider in diesen drei Beispielen tatsaechlich falsch klassifiziert.
- Quelle: `matrix_api/scene_state.py:710`.

**N07 - Datenbankneustart: PERSISTENZ POSITIV BESTAETIGT**

- Die zuvor direkt geschriebenen, ungueltigen SceneFacts und Beziehungen waren nach Schliessen und neuer SQLite-Verbindung noch lesbar.
- Positiv: Die Datenpersistenz und Reader-Folge funktionieren.
- Negativ: Auch fachlich ungueltige Wahrheit wird dadurch dauerhaft und folgewirksam.

Die Beleg-JSON und das eigenstaendige Pruefskript werden separat mit diesem Bericht ausgeliefert. Alle Schreibproben liefen gegen eine kopierte SQLite-Datei. Originaldaten und Original-ZIP wurden nicht veraendert.

## 3. Frontend/Backend: strenge Nutzeranforderung

**Anforderung:** Keine produktive Backendfunktion ohne reale Frontend-Bedien-, Anzeige- oder Diagnosekante. Keine funktionslosen Scheinbuttons, keine geheimen API-Schreibwege.

Neu statisch gezaehlt: **130 Flask-Routen** mit direkter `@app.<Methode>`-Dekoration in `matrix_api/app.py` (34 GET, 67 POST, 5 PUT, 12 PATCH, 12 DELETE). Im Frontendmodul `src/lib/matrix/api.ts` stehen **112 exportierte asynchrone API-Funktionen**.

Vier dieser exportierten Funktionen wurden im restlichen `src`-Quellbaum **nicht als Funktionsnamen referenziert**: `apiResetSessionRuntime`, `apiPostFact`, `apiPostGodFact`, `apiOcr`. Besonders `apiPostFact` und `apiPostGodFact` sind problematisch, weil ihre Backend-Routen kanonische Eintraege schreiben koennen. **Dies ist eine statische Aufrufanalyse, kein Browserlauf; alternative dynamische oder generische Wege wurden nicht pauschal ausgeschlossen.**

Die Beziehungsschreibung ist dagegen nicht pauschal ohne UI: `apiPutRelation` wird in `src/lib/matrix/store.ts` verwendet und es gibt Social-Bedienelemente. Das Problem hier ist, dass die **Backendpruefung schwach bleibt**, auch wenn das Frontend bei normaler Bedienung reale Figuren auswaehlt.

Die Produkt-UI hat Start-, Welt-, Charakter-, Chat-, Memory-, Timeline-, Social-, Fate-, Upload-, Review-, Konfigurations- und Diagnosequellen. Die Existenz dieser Seiten ist **kein** Nachweis, dass alle angezeigten Knopfaktionen tatsaechlich bis zum Writer und wieder in die sichtbare Folge funktionieren. Mit fehlendem Flask und fehlenden Node-Dependencies war ein vollstaendiger Browserlauf nicht moeglich.

### Frontend-Build: eigenstaendig POSITIV geprueft

- Quellbaum `src`: **86 Dateien**.
- Selbst berechneter `sourceTreeSha256`: `deca97a2a5ab25bce948a12289e009b492e72cfccaa4841c611928379e3882c7`, identisch mit `.build-info.json`.
- `frontend_dist/index.html`: SHA-256 stimmt mit Build-Manifest ueberein.
- **42 von 42** gelisteten Assetdateien vorhanden; Assetliste stimmt genau.
- **12** aus dem HTML extrahierte Assetreferenzen; **0 fehlen**.
- Dies prueft die Auslieferungskonsistenz, nicht TypeScript-Fehlerfreiheit oder interaktive Lauffaehigkeit.

## 4. Benutzer-/Rollenisolation und Sicherheitsbewertung

- `matrix_api/isolation.py:14-62` liest `X-Matrix-Actor` / Alternativheader; die Frontendbibliothek `src/lib/matrix/api.ts:31-84` speichert und sendet den Actor aus Browser-Storage.
- Fehlt die Kennung, werden mutierende Requests standardmaessig abgewiesen. Eine **gelieferte, aber frei gewaehlt uebermittelte Kennung** ist keine Authentifizierung.
- Die Session-Ownerpruefung ist real und blockiert **abweichende** Headerwerte (Positivprobe N04). Wer den Header als berechtigten Actor behauptet, wird auf dieser Stufe nicht kryptografisch geprueft.
- `START.py` und `app.py` binden defaultmaessig an `127.0.0.1`; die App erzwingt laut Quellcode Loopback auch bei `0.0.0.0`. Deshalb hier **kein nachgewiesener externer Internetausnutzungsweg**.
- Fuer mehrere unabhaengige lokale Benutzer, gemeinsam genutzte Rechner und spaetere Fernzugriffe ist das Sicherheitsmodell trotzdem unzureichend.

## 5. AMASTER-Gate-Stand: nicht aus Unit-Erfolgen ableiten

| Gate | Sachlicher Stand dieser Neumessung | Konsequenz |
|---|---|---|
| G1 Figurenwissen/Witness | Kein neuer voller Input-zu-Folgeturn-/UI-Lauf | NICHT ABGENOMMEN |
| G2 Koerper/Capability | Kein neuer voller Sperre/Outcome/Loesung-Lauf | NICHT ABGENOMMEN |
| G3 gerichtete Beziehungen | Writer akzeptiert nicht existente Akteure | KRITISCHE GEGENPROBE ROT |
| G4 Regie/Object | Kein neuer echter Regie-Objekt-E2E-Lauf | NICHT ABGENOMMEN |
| G5 Avatar-Schutz | Kein neuer kompletter Live-Output-/Commit-Lauf | NICHT ABGENOMMEN |
| G6 Persistenz | SQLite-Restart/Reader nachgewiesen, nicht der gesamte gueltige Folgeturn | TEILGEPRUEFT |
| G7 Session- und Userisolation | Reale Owner-Sperre gezeigt, Headeridentitaet ungesichert; kein voller Multi-Session-E2E | TEILGEPRUEFT |
| G8 kanonische Writer/Reader | Reader liest direct writes; komplette Writerliste und erlaubte Readerpfade nicht geschlossen | NICHT ABGENOMMEN |
| G9 zusammengesetzte Turns | Mischhandlung verliert strikte Teilgrenze; keine volle echte Orchestrator-E2E-Absicherung | OFFEN / GEGENBEISPIEL AN TEILLOGIK |
| G10 Refusal/Acceptance | Einzeltat korrekt declined; Mischhandlung unknown; ganzer Request-Lifecycle nicht als Gate neu gemessen | TEILGEPRUEFT |
| G11 Session/Stamm-Isolation | Kein neuer kompletter Character-Seed-vs-Session-Gate | NICHT ABGENOMMEN |
| G12 Product Surface | Direkte produktive API-Fact-Writer ohne aufrufenden Frontendpfad | KONKRETE ABDECKUNGSLUECKE |

Die G1-G12-Eintraege sind eine **Abnahmematrix**. `NICHT ABGENOMMEN` bedeutet nicht automatisch ein bewiesener Logikfehler; es bedeutet, dass die jeweilige reale Produktkette in dieser Pruefung nicht vollstaendig nachgewiesen ist. Foundation ist wegen der nachgewiesenen verbotenen Direktwrites bereits nicht abnahmefaehig. Living Core baut zwingend darauf auf.

## 6. Funktionsbewertung auf Ebene der Gesamtsysteme

| Produktbereich | Bewertung | Begründung / Grenze |
|---|---|---|
| Paket/Frontend-Integritaet | **GUT fuer Hash-/Assetkonsistenz** | 86 Quelldateien, 42 Assets, Hashes und Referenzen stimmen; kein Browserbeweis |
| Persistente Daten/SQLite | **TEILWEISE GUT** | Original-DB strukturell ok, Writer-Reader-Neustart funktioniert; ungueltige Fakten werden ebenfalls haltbar |
| Session-Ownerpruefung | **TEILWEISE GUT** | Besitzerwechsel per abweichender Kennung abgewiesen, aber Kennung selbst nur Header |
| TurnTruth/Effect/Canonical Writer | **KRITISCH** | Direktfakt, God-Fakt und Beziehungen umgehen fachliche Bindungsanforderungen |
| Regie/God/Avatar | **NICHT ABGENOMMEN** | God-Fakt ohne Scope direkt schreibbar; Live-Role-/Outputketten nicht komplett vermessen |
| Semantische Handlung/Einwilligung | **TEILWEISE FUNKTIONAL, NICHT SICHER ABGENOMMEN** | getrennte Kussprobe declined; Mischprobe unknown; 24 Spezialtests gruen |
| SceneState/Szenenuebergang | **FEHLERANFAELLIG** | Modell-Fehlklassifikation kann reine Nennung zu neuer Szene machen |
| Witness/Memory/Recall/Folgeturn | **GEZIELTE TESTS, KEINE VOLLSTAENDIGE GATE-FREIGABE** | Teilbereiche in Suite gruen; keine neue durchgehende produktive HTTP-/LLM-Kette |
| Social/Relationship | **KRITISCHE REFERENZLUECKE** | Session-Relation nimmt frei erfundene Teilnehmer an |
| UI und produktive Backend-Abdeckung | **NICHT GESCHLOSSEN** | ohne genutzten Frontendpfad vorhandene kanonische Writer |
| Provider/Android/Mehrprozess | **NICHT NEU GEPRUEFT** | aus diesem Audit kein Verfuegbarkeits- oder Stabilitaetsurteil ableitbar |

## 7. Wurzelanalyse: Warum viele Tests trotzdem gruen sind

Das Gesamtsystem besitzt **parallele direkte Schreibmoeglichkeiten** neben dem semantisch geprueften Orchestrator. Ein Test, der die korrekte Effect-Route benutzt, kann gruen sein, waehrend ein anderer produktiver API-Einstieg einen ungueltigen Fact in denselben Master schreibt. Sobald dieser Fact im Session-Reader auftaucht, koennen Folgen, Memory, Witness und BrainContext die fragwuerdige Information als reale Geschichte behandeln.

Zusaetzlich bildet die text-/modellbasierte Klassifikation einen Fehlerausgang: Eine semantisch falsch eingeordnete Aussage bekommt nur eine begrenzte, teilweise wortbasierte Gegenpruefung. Bei reinen Szenenerwaehnungen und gemischten Handlungen ist diese Grenze nicht hinreichend. Das ist kein Argument gegen LLMs generell, sondern fuer eine lokal bindende und fail-closed ausgerichtete Validierung.

Eine dritte Klasse ist die **UI-Sichtbarkeitsluecke**: Eine Exportfunktion oder API-Route ist keine nutzbare Frontendfunktion. Die Bedienbarkeit muss anhand realer Buttons, Ziel-/Scope-Auswahl, sichtbarer Wirkung und lesbarem Fehlerfall verifiziert werden. Der Nutzer verlangt zu Recht eine striktere Oberflaechendeckung als nur 'es existiert irgendwo ein Endpoint'.

## 8. Reparaturplan - priorisiert, nicht ausgefuehrt

### P0: vor einer Freigabe zwingend

1. **EIN verbindlicher kanonischer Write-Eingang:** Alle produktiven Schreibpfade fuer Szene, God, Turn und Relation ueber Control-Binding, Authority/Scope, typisierte Effects, lokale Validierung, Provenienz, atomaren Writer und berechtigten Reader fuehren. Kein `POST /facts`-Bypass. Bestehende Direkt-Endpunkte entweder produktiv sperren oder zu einem validierten Orchestrator umstellen. Diagnosen schreibgeschuetzt halten.
2. **Referentielle Integritaet serverseitig:** `actorId`, `targetId`, `fromId`, `toId` muessen zu realen und zulaessigen Charakteren/Objekten derselben Scope-Bindung passen. User-ID ist nie Character-ID. Keine erfundenen Figuren oder ortsfremden Referenzen ins Current State. Manueller Social-Seed ist ein eigener expliziter UI-/Review-Vorgang mit Provenienz, keine vorgetaeschte Tat.
3. **God-/Regie-Scope validieren:** Kein God-Fact ohne gueltigen Truth-/Persistence-/Epistemic-Scope und passend autorisierten Sprecher, außer einem bereits im AMASTER fuer diesen Pfad eindeutig geltenden Default. Bei Luecken fail-closed.
4. **Bestehende ungueltige Wahrheit behandeln:** Neue Validierungen allein reparieren nicht den Datenbestand. Auditpfad fuer Altfakten ohne Provenienz und Referenz, quarantinierte Lesung/Review statt stiller Loeschung oder automatischer Wahrheitserhebung. Session-Stamm strikt getrennt.

### P1: danach fuer den echten Living Core

5. **Compound-Turns zerlegen:** Jede eigensinnige Handlung und Rede als separate Effect-Komponente mit gleichem sourceTurnId, expliziten Abhaengigkeiten. Teilgrenzen je Handlung und Objekt validieren; `unknown` ist sichtbar zu erklaeren; nicht einfach erlauben oder komplett ablehnen.
6. **Szenenwechsel robust fail-closed:** Vollzug/Erwaehnung am aktuellen Turn und Kontext unterscheiden. Blosser Modellwert `verwendung=vollzug` ohne belastbare lokale Bindung darf keine sceneId erzeugen. Wortstamm- oder Zitatfilter allein reicht nicht.
7. **Frontend-API-Landkarte:** Fuer **jede** produktive Schreib- und Lesefaehigkeit Tabelle `UI-Control -> Request -> Actor/Scope -> Validator -> Writer -> SQLite -> Reader -> sichtbare Rueckmeldung/Fehler`; tote API-Aufrufe entfernen, Funktionen sichtbar anbinden oder unproduktive Endpunkte abschalten. Keine Backendfunktion, die der Nutzer nur ueber curl oder Entwicklertricks ausloesen kann.
8. **Identitaet sauber definieren:** Local-only-Anwendung klar kennzeichnen oder echte benutzerseitige Anmeldung/Sessionbindung statt `X-Matrix-Actor` als alleiniger Vertrauensnachweis. Nie Fernzugriff auf dem derzeitigen Headerprinzip als Mehrbenutzer-sicher deklarieren.
9. **Abnahme mit echten Produktpfaden:** G1-G12 ueber HTTP- und Browserklicks, Provider, Output-Commit, Folgeturn und Reload testen. Datenbankisolation/Mehrprozess einbeziehen, Zufaelligkeit von Modellantworten dokumentieren.

### P2: Nachweis- und Betriebshygiene

10. Flask-/Test-Dependencies reproduzierbar einrichten; fehlende Test-Session als portable Fixture ersetzen. Typpruefung separat mit festem Dependencystand ausfuehren; SPS-Aussagen zu 616 TypeScript-Diagnosen nicht als aktuelle Neumessung verwenden. Android-Barrierefreiheit, UI-Klickpfade und Mehrprozess separat pruefen. Alte Teststatistiken nicht vermischen.

## 9. Gesamtwertung

**4/10 fuer technische Gesamt-Abnahmereife.** Diese Zahl ist eine fachliche Skalenbewertung und **keine** Messung, wonach exakt 40 Prozent aller AMASTER-Paragrafen bestanden waeren.

- **Staerken:** reproduzierbares Frontend-Build-Artefakt; funktionsfaehige SQLite-Persistenz; Owner-Guard gegen abweichende Actorwerte; viele laufende Kernel-/Regressionstests; 24 konkrete V65X-Zieltests funktionieren.
- **Abnahmeverhinderer:** produktive kanonische Direktwrites ohne Actor-/Provenienz-/God-Scope-Bindung; ungueltige Relationship-Referenzen; nicht durchgehend validierte semantische Entscheidung; Backend-/UI-Abdeckung nicht geschlossen.
- **Nicht behauptet:** allgemeiner HTTP-Hack, Ausnutzung ueber Internet, erfolgreiche Android-Nutzung, korrekte echte LLM-Semantik unter allen Eingaben, bestandene G1-G12 oder Fehlerfreiheit der gesamten Codebasis.

**Endurteil:** Basis technisch vorhanden, aber die Vertrauens-/Wahrheitsschicht ist noch nicht abnahmereif. Eine weitere Version sollte erst dann 'freigabefaehig' heissen, wenn die Kern-Writes zentral gueltig gebunden und echte UI-zu-Folgeturn-Gates nachweislich geschlossen sind.

## 10. Pruefnachweise und Reproduzierbarkeit

- Eigene Proben: `fresh_probes_20261031.py` und `fresh_probes_result_20261031.json`.
- Erneut ausgefuehrte V65X-Zieltests: `pytest_v65x.log`.
- Groessere Teilsuite mit Klassifikation: `pytest_535.log`.
- Unveraenderter Quellstand im originalen V65X-ZIP; keine Reparaturen, Original-DB unveraendert.
- Alle Repositoryschreibungen in den eigenen Proben nur gegen eine **temporare Kopie** von `data/matrix10.sqlite`.
- Statische Textsuche zaehlt API-Dekoratoren und Funktionsnamen, ersetzt nicht die komplette dynamische UI-Ausfuehrung.
- Bei fehlender Flask-Laufzeit und Node-Abhaengigkeiten hier kein echter HTTP-/Browser-Abnahmecheck. Kein Provider-/Android-/Mehrprozess-Gesamtlauf.
```

## DECKBLATT · V65X · Nachprüfung zu V65W (E01–E06): Lebenszyklus der Grenze, Tat-Grenzen-Bindung mit Anker, vollständige Bitte, Szenenübergang nur als Vollzug, keine stille Kürzung (Claude) · 30.10.2026

**Verbindlich:**
- `2_7master.txt`:
  - §20 Z. 914/941/949 (Szene, Übergang durch die Anweisung);
  - §24.2 Z. 1110–1118 (Lesung schlägt vor, Kernel validiert vor dem Writer), §24.7;
  - §34.1 Z. 1807–1815 (Provenienz), §34.3 Z. 1831–1841 (Widerruf/Ersetzen als neue Evidenz, nur für das, was sie sagt);
  - §36.1, §36.3, §36.5 Z. 1947–1975 (Einwilligung an Handlung, Umfang und Fenster gebunden; frühere ≠ aktuelle Zustimmung);
  - §46.6 Z. 2596.
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6, §16.

**Eingang:** deine Zusammenfassung der unabhängigen Nachprüfung zu V65W (E01–E06, „Gesamtabnahme weiterhin ROT“). Vermerk unten, unverändert.

**FEHLT:** die Gutachterdateien selbst (Gutachten, IST-Karte, sechs Tests, Testausgaben, Hashes). Die sechs Gegenproben sind aus der Beschreibung nachgebaut (`matrix_api/tests/test_v65x_gegenproben.py`).

**Basis:** mein V65W-ZIP (SHA256 `5752603b…`). DB und Logs bytegleich, keine Migration.

### Wurzel → Änderung (vorhandene Owner, keine neue Route, keine Tabelle, keine Wortliste)

| Befund | Wurzel am V65W-Code | Änderung |
|---|---|---|
| E01 selbe Stelle | `restricted_refusals_standing` beendete eine Teilgrenze nur durch eine Erlaubnis für jede Berührung | Eine spätere Erlaubnis oder ein Widerruf **derselben Stelle** hebt genau diese Teilgrenze auf. „Dieselbe Stelle“ = gleicher Wortstamm des Kopfworts beider wörtlicher Zitate („die Schulter“ / „meine Schulter“). Andere Teilgrenzen bleiben. Eine neue Teilgrenze derselben Stelle ersetzt die ältere |
| E01 Folge (im Vorlauf gefunden) | `body_contact_standing`: jede spätere Zustimmung beendete eine Grenze für jede Berührung ganz; eine Teilablehnung beendete eine Erlaubnis für jede Berührung ganz | Eine Antwort mit eigener Stelle beendet die Grenze für jede Berührung nicht mehr. Sie wird **Ausnahme** (`ausnahmen`). Eine Erlaubnis für eine einzelne Tat hebt die Grenze ebenfalls nicht auf. Eine Ablehnung einer Tat oder ein Widerruf ohne Stelle beendet eine Erlaubnis weiterhin (vorsichtige Richtung, Z. 1974). Tat nennt eine Ausnahme → `unknown` (`grenzeAusnahme`); Tat nennt keine → Zustand der Grenze. Der Spiegel nennt die Ausnahmen |
| E01 live | „Du darfst meine Schulter wieder anfassen“ hatte keinen Grenzvorschlag. Darum lief keine Umfangslesung, und die Antwort wurde als Zustimmung zum Kuss davor gebucht | Antwort (Zustimmung, Ablehnung, Widerruf) einer berührten Figur an genau einen Berührenden bekommt die Umfangslesung, auch ohne Vorschlag und bei „diese Tat“ (`_answer_boundary_candidate`, `_consent_scope_check`). `validate_grenze` engt dann auf die Stelle ein, weitet nie. Eine Antwort mit Stelle beantwortet nur Taten, die diese Stelle nennen (`_body_contact_answer`) |
| Richtung (im Vorlauf gefunden) | „Nur meine Hand darfst du halten“ wurde als Ablehnung der Hand gespeichert | Die Umfangslesung sagt auch die Richtung ihres Gegenstands (`richtung`: verboten / erlaubt). Sie muss zur Antwortart passen. Fehlt sie oder widerspricht sie: unbestätigt. Die genannte Stelle bleibt sichtbar und offen: unter einer Grenze für jede Berührung wird eine Tat an dieser Stelle nicht gegen ihre spätere Äußerung abgelehnt |
| E02 | `boundary_reference_verdict` glaubte `betroffen` + wörtlichem Beleg | Kernel-Anker: Der Beleg aus der Tat muss das Kopfwort der Einschränkung nennen (gleicher Stamm). Nur Veto, nie Treffer allein. Der Leser `act_consent` prüft Status und Anker selbst nach |
| E03 | `scene_transition_verdict`: Art + wörtlicher Beleg genügte | Die Lesung typisiert die Verwendung (`verwendung`: vollzug / nennung). Übergang nur bei `vollzug`, und der Beleg steht nicht in Anführungszeichen |
| E04 | Kappungen `[:6]`/`[:4]` in `restricted_boundaries_for`, `act_consent`, `accepted_requests_for`, Aussagen, Nachlesungen | Alle stehenden Teilgrenzen, Bitten, Aussagekomponenten und Nachlesungen werden gelesen |
| E05 | Die Bitte-Lesung prüfte nur, ob jeder Teil wörtlich in der Tat steht | Die Teile müssen die ganze Tat abdecken (ein übriges Wort ab 4 Buchstaben → `unbestaetigt:teile_unvollstaendig`). Jeder erbetene Teil muss ein Wort der Bitte nennen (Bitte-Anker). Der Writer `_bind_own_act_to_request` prüft beides am Fact-Text nach. Konnte der Kernel eine geplante eigene Tat der Eingabe nicht finden, wird keine Tat dieser Eingabe an eine Bitte gebunden (`bitteBindung: eingabe_unvollstaendig`) |
| E06 | höchstens 5 Seiten (200 Taten) | ohne Seitenobergrenze, +1 Aufruf je 40 Taten |

### Gegenproben und Tests (0 Modellaufrufe)
- **`test_v65x_gegenproben.py`, 24 Tests**, je auf dem echten Writer/Reader, meist mit SQLite-Rücklesen:
  - E01: selbe Schulter aufgehoben; andere Stelle hebt nichts auf; Widerruf nur der einen Stelle.
  - E01 Folge: Teilerlaubnis unter Grenze für jede Berührung (Kuss `declined`, Hand `unknown`); Erlaubnis einer Tat hebt die Grenze nicht auf; Teilablehnung in einer Erlaubnis für jede Berührung (Wange `accepted`, Schulter `declined` mit Lesung, `unknown` ohne); Spiegel nennt die Ausnahme.
  - E02: Kuss mit kontrolliert falscher Lesung → `unknown`; echte Treffer bleiben `declined`; Art der Berührung („küssen“ / „Kuss“); gefälschter Treffer am Leser wirkt nicht.
  - E03: falsch klassifizierte Nennung → kein Übergang; Zitat in „…“ → kein Übergang; `vollzug` → neue Szene.
  - E04: neun Teilgrenzen erreichen alle die Tatlesung; die neunte („den Rücken“) entscheidet.
  - E05: Lesung ohne den Kuss → `unbestaetigt:teile_unvollstaendig`, `unknown`; vollständige Lesung bindet; gefälschte bzw. teillose Urteile bindet der Writer nicht; Teil ohne Wort der Bitte; Eingabe mit nicht gefundener Tat.
  - E06: 230 Taten über alle Seiten, Writer vollzieht 230.
  - Live gefunden: Antwort für eine Tat mit Stelle → Teilerlaubnis; Richtung gegen die Antwortart → unbestätigt; Teilerlaubnis nach dem Kuss ist keine Antwort auf den Kuss; unbestätigte Stelle unter Grenze für jede Berührung bleibt offen.
- **Am V65W-Code:** 21 dieser Tests rot, 3 grün. Die 3 grünen sind Positivkontrollen (andere Stelle, echter Treffer, vollständige Lesung).
- **SOLL-Änderung älterer Tests (nicht abgeschwächt):**
  - V65W V03: die Übergangslesung trägt jetzt `verwendung: vollzug`.
  - V65T `_plan` und ein V65R-Test: die Umfangslesung trägt die Richtung, wie die Lesung sie für diese Zitate gibt.
- **Regression V65W gegen V65X** (deine DB und Alt-DB): 0 neu rot, 0 neu grün außer den 24 neuen Tests; 533 bzw. 551 bestanden. Die 50 bzw. 32 vorbestehenden Fehler sind unverändert.
- **prepare-Bytevergleich:** 3 DBs, 40 Sessions, 0 abweichend.
- **TypeScript:** 616 vorbestehend, 0 neu. **Build** aus `src`: Exit 0, 42 Assets (src-Hash `deca97a2…`), geändert nur der Buildname.

### Messungen (Modell, T=0, je 2 Läufe, Kernel eingerechnet)

| Lesung | Endfassung | FP | verworfen / Hinweis |
|---|---|---|---|
| Grenzbezug mit Anker (V65W-Antworten neu gerechnet, 0 Aufrufe) | 40/40 | 0 | V65W ohne Anker 38/40 (2 FP „Ich küsse dich“ / „am Arm“) |
| Grenzbezug, neue Arten („so grob“, „von hinten“) | 8/8 | 0 | – |
| Szenenübergang mit Verwendung | 44/44 | 0 | Feld „anweisung/erwaehnung“: 42/44 (2 FP „Die Tür fliegt auf …“) |
| Bitte mit vollständiger Zerlegung | 24/24 | 0 | mit Bitte-Anker neu gerechnet: 24/24 |
| Umfang mit Richtung | 50/52 | 0 | 2 FN: „Das mit der Schulter nehme ich zurück“ – die Lesung schreibt „die Schulter“, nicht wörtlich, bindet nichts |

### E2E am frisch entpackten Kandidaten-ZIP (START.py)
- **Browser** (Ablauf V65U–V65W): React #418 0 auf 9 Routen, 0 Konsolen- und Seitenfehler. Reload gleich, Sessionwechsel gleich. Provider-Fehler vollständig bedient (Banner, „Antwort erneut erzeugen“, „ohne Antwort abschließen“). Config bytegleich, Sicherung gelöscht.
- **HTTP-Live-Kette, Session A** (Puppet, Regie; echter Provider):
  - Mara: „Fass mich nie wieder an die Schulter, Johann!“ → Teilgrenze „die Schulter“.
  - „Ich küsse dich“: Die Tatlesung sagte live `betroffen` (der E02-Fehler). Der Anker verwarf es: `unbestaetigt:tat_nennt_grenze_nicht` → `unknown`.
  - Mara: „Du darfst meine Schulter wieder anfassen.“ → Teilerlaubnis „meine Schulter“, beantwortet keine Tat (nicht den Kuss). Danach Schulter → `unknown` (E01 live).
  - Regie: „Die Worte neue Szene sind ein Zitat und kein Befehl.“ → `nennung`, gleiche `sceneId` (E03 live).
  - Mara: „Fass mich nie wieder an, Johann!“, dann „Nur meine Hand darfst du halten.“ (Plan: Ablehnung, Lesung: erlaubt) → `unbestaetigt:richtung_widerspricht`, Stelle „meine Hand“ offen. Danach Kuss `declined`, Hand `unknown`.
- **Session B** (E05): „Darf ich deine Hand nehmen?“ – „Ja, das darfst du.“ – „Ich nehme deine Hand und küsse sie.“ → zwei Taten, beide `unknown` (Kuss: Teil nennt nichts von der Bitte; Hand: Lesung nicht wörtlich). Danach „Ich nehme deine Hand.“ → `accepted` (Bitte), einmal.
- **Neustart:** Rücklesen aller drei Sessions gleich (Einwilligungen, `sceneId`, keine offene Eingabe).
- **Isolation:** 0 alte Zeilen verändert außer deinem User-Eintrag; neue Zeilen nur mit den drei neuen Session-IDs.
- **Vorlauf am Arbeitsstand** (v1–v3) zeigte die drei zusätzlich behobenen Fehler (Teilerlaubnis ohne Lesung, Richtung, Bitte-Anker / unvollständige Eingabe). Nachweis in `messung/live_kette_vorlauf65x*.json`.

### Offen / ROT
- **Puppet-Zerlegung schwankt** (Altbestand V59C): „Ich nehme deine Hand und küsse sie“ wurde je Lauf anders zerlegt, einmal blieb der Kuss Rede, einmal die Hand. Der Kernel macht daraus keine Zustimmung mehr; die Tat kann aber als Rede gespeichert werden.
- Eine Tat, die eine erlaubte Stelle und mehr enthält, bleibt unter einer Grenze für jede Berührung `unknown` statt `declined` (dafür bräuchte es eine eigene Lesung).
- Eine Teilerlaubnis macht spätere Taten nie `accepted`; sie hebt nur Ablehnungen auf.
- E03 Restrisiko: Eine Lesung, die Art, Beleg und `vollzug` übereinstimmend falsch setzt, ohne Anführungszeichen im Text, bleibt möglich.
- Anker-Grenzen (nur Veto, sicher): „Ich drücke meine Lippen auf deinen Mund“ gegen „küssen“ → `unknown`; Verweis mit „dort“/Pronomen → `unknown`.
- Unverändert offen: Pronomen T32, Widerspruch-FP (2/36), Regie-FN, 616 TypeScript-Altfehler, Android, Mehrprozess im Browser.

### Modellaufrufe
- **Entwicklung V65X: 290** (Messungen 172, Live-Vorläufe 118). **E2E: 110** (Browser 81, Live-Kette 29). **Gesamt V65X: 400.**
- **Betrieb, geändert:**
  - +1 Umfangslesung je Antwort (Zustimmung, Ablehnung, Widerruf) einer berührten Figur an genau einen Berührenden, auch ohne Grenzvorschlag;
  - Tatlesung je Körpertat und **jeder** stehenden Teilgrenze (vorher höchstens 6), je offener angenommener Bitte (vorher höchstens 4);
  - Aussage: alle Komponenten und Nachlesungen (vorher je höchstens 6);
  - Regie: +1 je 40 Taten ohne Obergrenze (vorher höchstens 5 Seiten);
  - sonst wie V65W.

**STATUS: TEILGRÜN.** E01–E06 am Kernel grün mit festen Tests; E01, E02, E03 und E05 live über die Produktrouten am frischen ZIP gezeigt, E04 und E06 nur im Test. Offen wie oben. Keine Android- und keine AMASTER-Gesamtabnahme.

## NACHPRÜFUNG zu V65W · Vermerk (Eingang V65X, 30.10.2026) – unverändert übernommen

Quelle: deine Zusammenfassung der unabhängigen V65W-Nachprüfung (Anhang vom 30.10.2026). Weggelassen ist nur die erste Zeile, die Anzeige der Denkzeit („8m 48s nachgedacht“). Die genannten Gutachterdateien (Gutachten, Deckblatt, IST-Karte, sechs Tests, Testausgaben, Hashes) lagen nicht bei.

```text
### MATRIX10 V65W – unabhängige Nachprüfung

Gesamtabnahme weiterhin ROT

V65W enthält echte Reparaturen. Die Behauptung, alle sieben Ursachen seien geschlossen, ist aber nicht haltbar.

Ich habe V65W und V65V frisch entpackt, den Code verglichen sowie AMASTER, SPS und den Kettenvertrag herangezogen. Die ZIP-Prüfsummen stimmen mit dem Baubericht überein; die enthaltene SQLite-Datenbank ist gegenüber V65V bytegleich.

Bei der unabhängigen Prüfung ergeben sich zwei unterschiedliche Ergebnisse:

* Die neuen V65W-Tests bestätigen mehrere tatsächliche Verbesserungen, darunter die Speicherung eingeschränkter Grenzen und die seitenweise Regie-Auswahl.

* Sechs zusätzliche Soll-Gegenproben schlagen fehl. Darunter sind Fehler, die erneut eine falsche kanonische Einwilligung erzeugen können.

Die wichtigste neue Erkenntnis ist, dass nicht mehr nur die Erkennung einzelner Grenzen fehlerhaft ist. Auch deren Lebenszyklus – Erlaubnis, Widerruf, erneute Handlung und Gültigkeitsbereich – ist noch unvollständig implementiert.

### Die sechs neuen Befunde

| ID  | Fehler                                                                                                                                     | Ergebnis         |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------ | ---------------- |
| E01 | Eine spätere, ausdrücklich auf dieselbe Schulter bezogene Erlaubnis hebt das vorherige Schulterverbot nicht auf.                           | ROT              |
| E02 | „Ich küsse dich“ kann bei falscher Tatlesung als Verstoß gegen ein Schulterverbot committed werden.                                        | ROT              |
| E03 | Der Satz „Die Worte neue Szene sind ein Zitat und kein Befehl“ kann bei falscher Modellklassifikation trotzdem eine neue sceneId erzeugen. | ROT              |
| E04 | Von neun gültigen eingeschränkten Grenzen werden nur die ersten sechs an den Tat-Prüfer übergeben.                                         | ROT              |
| E05 | „Hand nehmen und küssen“ kann als vollständig erlaubt committed werden, wenn die Lesung den Kuss auslässt.                                 | ROT              |
| E06 | Bei mehr als 200 relevanten Taten erreicht die seitenweise Regie-Auswahl nicht mehr alle Fakten.                                           | Kapazitätsgrenze |

Wichtige Unterscheidung: E02, E03 und E05 wurden mit kontrolliert falschen beziehungsweise unvollständigen Modelllesungen ausgelöst. Damit ist der unzureichende Schutz des Kernels belegt, nicht die Häufigkeit dieser Fehler im Livebetrieb. E06 verhindert einen falschen Vollzug, lässt aber die vollständige Ausführung scheitern.

### Was ich an V65W bestätige

* Regie: Der frühere 40-Taten-Fehler wurde für die geprüften 45 Taten behoben. Es gibt eine echte seitenweise Auswahl.

* Einwilligung: Eingeschränkte Grenzen sind nun eigene kanonische Lifecycle-Einträge. Eine spätere passende Tat kann korrekt als `declined` erkannt werden.

* Szenen: `SceneState.sceneId` wird tatsächlich verwendet, statt nur den Ort als Szenenidentität zu behandeln.

* Antwortversuche: Prozessbezogene Nachweise und getrennte Versuchs-IDs sind implementiert. Die beiden echten Mehrprozess-Tests konnte ich wegen der fehlenden Flask-Abhängigkeit nicht unabhängig ausführen.

* Frontend: Der mitgelieferte Quellstand, HTML-Hash und sämtliche 42 Asset-Einträge stimmen mit dem Manifest überein.

Die alten Gegenproben V02, V03 und V06 verwenden teilweise tatsächlich nicht mehr den neuen Produktweg. Die Erklärung des Entwicklers ist insofern nachvollziehbar. Sie beweist aber nicht, dass der neue Weg fehlerfrei ist.

### Abnahmestand

Neue V65W-Tests, unabhängig

### 21/21

2 Flask-abhängige Tests ausgenommen

Zusätzliche Gegenproben

### 6/6 ROT

Darunter persistierte falsche Einwilligungen

Die alte T32-Pronomenbindung bleibt offen. Gleiches gilt für die beobachteten Fehlklassifikationen von Widersprüchen, einzelne nicht vollzogene Regie-Anweisungen, die gemeldeten 616 TypeScript-Altfälle und Android.

Die vollständige Python-Regression konnte ich in dieser Umgebung nicht abschließen. Ein eigener Provider- oder Browser-Live-Test wurde nicht durchgeführt. Deshalb gebe ich dafür ausdrücklich kein GRÜN.

### Versionierter Bericht mit Nachweisen

Gesamte unabhängige V65W-Nachprüfung herunterladen

Gutachten, Deckblatt, IST-Karte, sechs ausführbare Tests, Testausgaben und Datei-Hashes

Einzelnes Systemgutachten V65W v1

Mit AMASTER-Abgleich, ersten falschen Übergängen, Korrekturreihenfolge und §16-Abnahmematrix

Meine technische Schlussfolgerung: Die nächste Reparatur muss vorrangig die vollständige Handlungskomposition bei angenommenen Bitten, die semantische Tat-Grenzen-Bindung und den selektiven Widerruf von Grenzen schließen. Danach folgen Szenenübergänge und die unvollständigen Auswahlpfade.

Das sind keine neuen Architekturentscheidungen für dich. Sie sind aus dem vorhandenen AMASTER und den nachgewiesenen Fehlern ableitbar. Zusätzliche Modelllesungen allein reichen nicht; der kanonische Writer darf aus einer unvollständigen Prüfung keine vollständige Zustimmung machen.

Die Originalpakete, Datenbank und Logs blieben unverändert.
```

## DECKBLATT · V65W · Tiefenprüfung V01–V07: Teilgrenze, Szene statt Ort, Tatinhalt, alle Seiten, Bestreiten am Ereignis, Versuche über Prozessgrenzen, eigene Bitte → eigene Tat (Claude) · 30.10.2026

**Verbindlich:**
- `2_7master.txt`:
  - §20 Z. 914/941/949 (Szene = kausaler Raum, Übergang, Wechsel durch Nutzer/Regie/God/Fate/Verlauf), §21 (Szene und Ort getrennt);
  - §24.2 Z. 1110–1118, §24.6, §24.7;
  - §34.1 Z. 1807–1815, §36.1, §36.3, §36.4 Z. 1941, §36.5 Z. 1947–1975;
  - §46.2 Z. 2549, §46.3 Z. 2565, §46.6 Z. 2596, §63.
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6, §16.

**Eingang:** Unabhängige Tiefenprüfung v1 zu V65V. V01–V07 waren am V65V-Code alle rot, Punkt 9 (eigene Bitte) offen. Vermerk unten.

**Basis:** mein V65V-ZIP (SHA256 49cc17c1…). DB und Logs bytegleich, keine Migration.

**Korrektur meines V65V-Eintrags:** Den Szenen-Default habe ich mit §46.5 Z. 2589 begründet. §46.5 regelt aber den Session-God. Der Default ist abgeleitet aus §36.5 Z. 1956 (Gültigkeitsfenster), Z. 1974 (frühere Zustimmung ist nicht aktuelle Zustimmung), §20 Z. 914 und §24.7. Er ist keine direkte Vorgabe. Code-Kommentare sind berichtigt.

### Wurzel → Änderung (vorhandene Owner, keine neue Route, keine Tabelle)

| Befund | Wurzel am V65V-Code | Änderung |
|---|---|---|
| V06/C1 Teilgrenze | `validate_grenze` hielt „nicht auf die Schulter“ nur als Notiz (`unbestaetigt`); der Reducer kannte nur `diese_tat`/`jede_beruehrung` | Eigener gültiger Scope `eingeschraenkt` mit Wortlaut und Fenster (`body_contact_entries`, neuer Leser `restricted_refusals_standing`). Ob eine spätere Tat genau das Verbotene tut, sagt nur die Tatlesung `boundary_reference_check` (Server, vor dem Write, wörtlicher Beleg aus der Tat). Sie wird auf dem Fact der Tat gespeichert (`effect.grenzBezug`). `act_consent` → `declined` (`grenze_eingeschraenkt`); ohne Lesung `unknown`, die offene Grenze ist benannt. Endet nur durch eine spätere Erlaubnis jeder Berührung |
| V03/C4 Szene | `_in_scene` las die Szene aus dem Ort | Owner der Szenenidentität ist `SceneState.sceneId`. Das Fenster speichert `sceneId`, jede Tat ihre Szene (`effect.consent.sceneId`). Szenenwechsel oder -ende am selben Ort beendet „diese Szene“. V65V-Fenster ohne `sceneId` bleiben wie gelesen |
| C4 Übergang | `external_delta` erkannte einen Szenenwechsel an Wörtern („neue Szene“, „Vorhang“) | Eigene Lesung `scene_transition` je Regie- und God-Eingabe, gültig nur mit wörtlichem Beleg (`scene_transition_verdict`). Die Wortliste ist entfernt |
| V01/C2 Tatinhalt | „bestimmte“ prüfte nur die grobe Wirkungsklasse; Kneifen und Schlag sind beide `gewalt` | Inhaltsschlüssel `check_regie_act_content`: Er sieht nur das Wort der Anweisung und den Wortlaut aller Taten dieser Klasse. Vollzug nur, wenn Inhaltsschlüssel UND Kennungsschlüssel dieselben Taten nennen (kein Einengen mehr). Ohne Inhaltslesung: `inhalt_ungeprueft` |
| V02/C3 >40 Taten | Die App zeigte der Kennungslesung `_lines[-40:]` | Seitenweise über ALLE Taten (je 40, globale Kennungen, höchstens 5 Seiten, `regie_pages`/`regie_label_key`). Der Writer prüft `kennungenGeprueft` ⊇ Pool; sonst `auswahl_unvollstaendig`. Die 40er-Kappung in `bind_regie_components` ist entfernt |
| V04/C5 Widerspruch | Zwei Etiketten derselben Frage + wörtliches Zitat genügten | Die V65V-Zerlegung bleibt bytegleich. Für jedes Ereignis, das sie als bestritten liest, kommt eine Nachlesung direkt am Ereignis (`statement_act_check`). Bindung nur mit beiden wörtlichen Ankern: Verneinung im Teil, Wörter aus dem Wortlaut der Tat. Ohne Ereignisbezug: unbestätigt |
| V05/V07/C6 Versuche | Eine fremde Boot-ID galt als beendet | Jeder Serverprozess hält eine OS-Sperre auf seiner Startdatei (`.matrix_boot/<boot>.lock` neben der DB). Das Ende eines Prozesses ist nur bewiesen, wenn diese Sperre frei ist. Sonst gilt der Versuch als laufend bzw. `unklar`: Schließen ist gesperrt, „Antwort erneut erzeugen“ bleibt möglich (UI). Gekappt werden nur selbst beendete Versuche |
| Punkt 9/C7 eigene Bitte | Kein Writer band die eigene Tat an die angenommene Bitte | `_bind_own_act_to_request`: Die Bitte ist von ihr angenommen und noch nicht ausgeführt, die Tatlesung `request_reference_check` zerlegt die Tat in Teile, und jeder Teil ist das Erbetene. Dann `accepted` (Basis Bitte). Einmalig: Evidenz `eigene_tat`. Mehr als erbeten → `unknown` |
| Puppet-Grenze | Puppet-Grenzen bekamen keine Umfangslesung | Gleiche `consent_check` wie bei Avatar und Figur |

### Gegenproben
- **Gutachterdateien unverändert am V65W-Code:**
  - grün: V01, V04, V05, V07;
  - rot wie geschrieben: V02, V03, V06 (Begründung je unten).
  - PERSIST-1/-2 bestätigen den Fehler nicht mehr, weil er nicht mehr entsteht. PERSIST-3 ist unverändert `unknown`, weil die Tatlesung fehlt.
- **V02 rot wie geschrieben:** Der Test baut den Kennungsschlüssel selbst aus dem V65V-Fenster (`lines[-40:]`). Über den V65W-Weg (`regie_pages` → `regie_label_key` → `bind_regie_components` → Writer): 45/45 vollzogen.
- **V03 rot wie geschrieben:** Der Test ändert `scene.id`, ein Feld, das kein Writer setzt. Über den Owner `SceneState.sceneId` und `external_delta` mit Übergangslesung: `unknown` nach Szenenwechsel am selben Ort, `declined` in derselben Szene.
- **V06 rot wie geschrieben:** Der Test gibt der späteren Tat keine Tatlesung. Ohne Lesung bleibt sie `unknown` (C1: „aus unklarer Lesung keine falsche weite Wahrheit“). Mit Tatlesung, wie der Server sie anhängt (Muster `_geprueft`): selbe Schulter `declined`, Unterarm `unknown`, nach SQLite-Rücklesen gleich.
- **`test_v65w_gegenproben.py`:** 23 Tests. Je Befund die Gegenprobe auf dem echten Writer/Reader mit Rücklesen, dazu Positiv- und Grenzfälle. Der Lebensnachweis wird mit echten OS-Prozessen geprüft (laufend, normal beendet, getötet).

### Messung (Modell, T=0, je 2 Läufe, Kernel-Validierung eingerechnet)

| Lesung | Ergebnis Endfassung | FP | verworfene Fassungen |
|---|---|---|---|
| Umfang `consent_check` (Text unverändert, Kernel V65W) | 36/36 | 0 | – |
| Grenzbezug `boundary_reference_check` (neu) | 38/40 | 2 („Ich küsse dich“ gegen „am Arm“) | Feld `stelle`: 22/40 (Modell zitiert die Grenze statt der Tat) |
| Tatinhalt `check_regie_act_content` (neu) | 16/16 | 0 | v1 0/16: Parser las „K1: Wortlaut“ nicht → Kennung wird jetzt herausgelöst |
| Aussage (V65V-Zerlegung + Nachlesung am Ereignis) | 34/36 | 2 („Kvle hat mich nicht belästigt“) | Verträglichkeitsfrage 28/36 (8 FP); Feld `tat` in der Zerlegung 30/36 (5 FP); Nachlesung v1 30/36 (2 FP, 4 FN) |
| Szenenübergang `scene_transition` (neu) | 32/32 | 0 | v1 30/32 (Gedanke „an eine Szene aus ihrer Kindheit“) |
| Bitte → eigene Tat `request_reference_check` (neu) | 18/18 | 0 | Ja/Nein-Fassungen 14/18 (Hand nehmen + küssen als erfüllt) |
| Regie-Kette (Struktur + Kennungen seitenweise + Inhalt + Writer) | 11/13 | 0 | 9/13, 10/13 |

Die 2 FN der Regie-Kette:
- „Sag die Wahrheit …“: Personen ungebunden, wie V65V.
- „wie er Mara gekniffen hat“ gegen „Ich kneiff dir …“: der Inhaltsschlüssel erkennt den Tippfehler nicht → `keine_taten`.

**Modellaufrufe Entwicklung V65W:** 677, alle Proben und verworfenen Fassungen eingerechnet, plus E2E siehe Bericht.

**Betrieb:**
- +1 je vorgeschlagenem Bestreiten, +1 Nachlesung je bestrittenem Ereignis;
- +1 je Körpertat und stehender Teilgrenze;
- +1 je Körpertat und angenommener, offener eigener Bitte;
- +1 je Regie-/God-Eingabe (Übergang);
- Regie-Mitteilung: +1 Struktur, +1 je Seite Kennungen, +1 je Seite Inhalt (nur bei einer Art);
- sonst 0.

### Offen / ROT (nicht als repariert ausgeben)
- FP „Kvle hat mich nicht belästigt“ (2/2, beide Lesungen einig).
- FP „Ich küsse dich“ gegen Grenze „am Arm“ (2/2).
- Regie-FN siehe oben.
- Der Szenenübergang wird nur für Regie und God gelesen. Nutzer-, Fate- und Verlaufswechsel ohne Ortswechsel sind nicht gebaut.
- Die Regie-Lesung macht aus „Später am Abend beginnt eine neue Szene …“ zusätzlich eine Handlung der angewiesenen Figur (ohne Körperwirkung). Altbestand V59C, nicht angefasst.
- Eine Erlaubnis mit Einschränkung („Du darfst meine Hand halten“) bindet keine spätere Tat (bewusst; Zustimmung gilt der Tat).
- Pronomen-Messung T2, TypeScript-Altfehler (616), Android: offen.
- Prozessnachweis: Versuche aus V65T bis V65V gelten als `unklar` (kein Nachweis). In deiner DB gibt es keine offenen Versuche.

## TIEFENPRÜFUNG v1 zu V65V · Vermerk (Eingang V65W, 30.10.2026) – unverändert übernommen (Deckblatt, Abschnitte 4, 6, 7)

Quelle: `V65V_UNABHAENGIGES_SYSTEMGUTACHTEN_v1_20261030.md` aus `V65V_UNABHAENGIGE_TIEFENPRUEFUNG_v1_20261030.zip`.

#### DECKBLATT / PRUEFSTATUS

- Version des Gutachtens: v1, Datum: 30.10.2026.
- Produktstand: `MATRIX10_V65V_BEDEUTUNG_GEBUNDEN_20261030.zip`.
- Original SHA-256: `49cc17c118c1760d544717f5bbf009d58a0f5d5311f18061ed1924e263e8f799`.
- Original MD5: `d609c4ff12ef5b39221f3e50a623bda3`.
- V65U-Basis SHA-256: `7f3013aedc50744f3839a6dedbdff710704a1270e0beb21ce2461e4aa70d706f`.
- Gepruefter Baubericht SHA-256: `54d2a5230616ecf06cfdf84ef7feb06907196f3b3fbc28a61f9812a840645ad8`.
- Referenzen im Paket: `2_7master.txt` (AMASTER, 4364 Zeilen), `MATRIX10_SPS_MASTER.md` (4282 Zeilen, Deckblaetter V65V, V65U, V65T usw.), `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` (765 Zeilen, insbesondere Abschnitte 6/16), V65V-Baubericht.
- Daten: SQLite im V65V- und V65U-ZIP bytegleich, SHA-256 `9be11b8410c4396eb731254f997dfed3095cd6c65c048bc04e80cd3e8c2d4003`; sieben Logs bytegleich. Kein Migrationsschritt und keine Modifikation der gelieferten ZIPs.
- Ergebnis: **KEINE AMASTER-ABNAHME. Kritische Writer-/Reader-Gates ROT, trotz nachweisbarer Fortschritte.**
- Gepruefte Aenderungen: 17 gemeinsame Dateien geaendert, 83 neu, 28 entfallen (einschliesslich Build-Assets und Nachweisen); einzelne Datei-Hashes in `DATEI_HASHES_SHA256.tsv`.
- Trennung: Aussagen aus Code/Offline-Tests (unabhaengig) vs. Entwickler-Browser/Provider-Messungen (nur dokumentiert) sind unten gekennzeichnet.

#### 4. SIEBEN EIGENE NEGATIVPROBEN (JEWEILS ROT)

##### V01 Regie: andere Tat gleicher Grobklasse
- Ausgang: Zwei bekannte eigene Handlungen `kneifen` und `schlagen`, beide Effektklasse `strike`.
- Anweisung: Informant soll ueber **Kneifen** berichten; Lesungen liefern irrtuemlich die Fact-ID des Schlags sowie `gewalt`/`gekniffen`.
- Beobachtet: `execute_regie_information` liefert `vollzogen` und die Schlag-Fact-ID. Der eigentliche angeordnete Fact fehlt.
- Bewertung: **KRITISCHER FALSE POSITIVE COMMIT**, konditional auf falsche Modellbindung. Dauerhaft nach SQLite-Roundtrip vorhanden (Test PERSIST-1).

##### V02 Regie: 45 Taten vs. 40er Auswahlfenster
- Ausgang: 45 vorhandene bekannte Fakten; Kernel-Pool umfasst alle 45.
- Anweisung: alle mitteilen. Modell sieht nur letzte 40; selbst perfekte Kennungsauswahl kann erste 5 nicht nennen.
- Beobachtet: `nicht_vollzogen`, leerer Vollzugsinhalt. Kein Falsch-Fact, aber die angeordnete Wirkung laesst sich nicht ausfuehren.
- Bewertung: **KRITISCHER FALSE NEGATIVE**, Code-nahe Nachbildung exakt der produktiven `app.py`-Begrenzung.

##### V03 Grenze nach Szenenwechsel bei gleichem Ort
- Ausgang: gepruefte Grenze mit `fenster.art='szene'` und `placeId='gasthaus_saal'`.
- Simulierter Wechsel von Szene/Phase/Zeit ohne Raumwechsel; spaetere andere Beruehrung.
- Beobachtet: `declined` aus der alten Grenze; `_in_scene` ignoriert Szenenkennung und Phase.
- Bewertung: **SCOPE-KORRUPTIONSRISIKO**. Es handelt sich um einen synthetischen Szenenwechsel; in der aktuellen Session war vor dem Test noch keine stabile `scene.id` vorhanden. Das beweist einen fehlenden Reader-Vertrag, **nicht** einen in einem echten Browser beobachteten Szenenwechsel.

##### V04 Bewertung als Widerspruch
- Ausgang: Betroffene sagt `Ich fuehle mich durch Kvle nicht belaestigt` ueber eine vorherige Tat.
- Formulierung und zweite Aussagelesung werden kontrolliert beide mit unzutreffendem `bestreitet` versorgt; der zitierte Wortlaut kommt in der Rede vor.
- Beobachtet: `aussage_gegen_erleben` committed. Bleibt in SQLite (Test PERSIST-2).
- Bewertung: **BEDINGTER FALSE POSITIVE**. Nicht gleichzusetzen mit einer gemessenen Live-Haeufigkeit; Entwicklerproben meldeten 1/18 Fehlklassifikation der zweiten Lesung, die erste Lesung lieferte in V65T 0/9.

##### V05 Boot-A-Versuch aus Historie verdraengt
- Ausgang: aktiver Versuch mit boot=A; auf boot=B werden >8 andere Versuche beendet.
- Beobachtet: Boot-A-Versuch geht aus der Session-Versuchshistorie verloren, obwohl nur ein anderes Boot ihn als beendet klassifiziert.
- Bewertung: **PARALLELBETRIEBS-/RACE-RISIKO**. Kein Nachweis im Standard-Einprozess-Start; relevant bei zwei aktiven Serverprozessen oder Restart-Ueberlappung.

##### V06 Schulter-Grenze auf spaetere Schulter wirkungslos
- Ausgang: `Fass mich nicht mehr auf die Schulter`; gepruefte Semantik `eingeschraenkt`.
- Spaetere Handlung: erneutes Beruehren **derselben Schulter**.
- Beobachtet: `act_consent.state='unknown'`, nicht `declined`. Nach SQLite-Speichern/Ruecklesen unveraendert (PERSIST-3).
- Bewertung: **KRITISCHER FALSE NEGATIVE**. Eine engere Grenze bleibt nicht im kanonischen Geltungsbereich erhalten. V65V-Gruentest prueft nur den anderen Unterarm, nicht die verbotene Schulter.

##### V07 Fremdes Boot sieht laufende Antwort nicht
- Ausgang: Ein Attempt boot=A ist persistent `laeuft`; die gleiche Session wird vom lebenden boot=B abgefragt.
- Beobachtet: `pending_input_view(...boot_id='boot_B')['attemptRunning'] == False`; der Abschlussreader `close_pending_input` benutzt genau diese Information.
- Bewertung: **PARALLELBETRIEBS-/RACE-RISIKO**, selbst wenn der Versuch noch in der Historie vorhanden ist. Boot-ID ist keine globale Liveness-Aussage.

#### 6. WEITERE OFFENE PUNKTE (NICHT ALS REPARIERT AUSGEBEN)

1. **Pronomen/Original-T32:** V65V hat die unstete Eingangslesung nicht neu gemessen. Vorherige echte Session `Hat er dich belaestigt` blieb ungebunden; mit simulierter Bindung wurden 3/3 Taten selektiert. G1/G13 fuer diesen Produktfall nicht gruen.
2. **Feld `aussagen`**: V65T-Liveprobe 0/9. Die neue Aussagelesung ruft nur auf, **wenn** `aussagen` bereits ein `bestreitet_geschehen` enthaelt. Damit kann der Widerspruchs-Writer weiterhin praktisch inaktiv sein.
3. **False Negative Umfang:** `Keine Beruehrungen mehr`, `Finger weg von mir` wurden vom Entwickler als nicht weit gebunden berichtet.
4. **Regie False Negative:** `Sag die Wahrheit, was hast du mit Mara gemacht`, `nur von seiner ersten Beruehrung`, `wie er gekniffen hat` blieben im berichteten Test unvollzogen.
5. **End-to-End**: Die zwei neuen Zusatz-Lesungen `consent_check`/`statement_check` wurden laut Entwickler nicht in seinem Browser-Durchlauf ausgeloest. Ein HTTP-Mock ist kein G12-/G9-Gate fuer die Echtkette.
6. **Frontend**: Vite-Manifest ist konsistent; die 616 gemeldeten TypeScript-Altfehler sind unabhaengig nicht nachgemessen/behoben. Neues Quellbuild/Browser-Routen pruefbar mit vorhandenen Abhaengigkeiten, hier nicht ausgefuehrt.
7. **Android**: Ungeprueft.
8. **Historische Daten / alte 50 bzw. 32 Regressionen**: Entwicklerbericht dokumentiert ROT, nicht durch diese neue Version behoben. Pruefumgebung ohne Flask und historische Tammy-Fixture begrenzt eigene Vollsuite.
9. **Writer eigene angenommene Bitte -> eigene Tat**: Der produktive Bindungswriter fehlt weiterhin, obwohl ein Reducer-Test manuell die Proposition-ID setzt (`test_v65t_einwilligung.py` um Zeile 200).
10. **AMASTER Vollkonformitaet**: Die Gate-Reihenfolge FOUNDATION/LIVING CORE und weitere Systemteile (Fate, Social, Synapsen, Source-Axis) wurden in dieser fokussierten V65V-Nachpruefung nicht vollstaendig end-to-end abgenommen. Keine pauschale Abnahmebehauptung zulaessig.

#### 7. KORREKTURREIHENFOLGE - IM BESTEHENDEN OWNER, OHNE PROMPT-/GUARD-FLICK

1. **C1**: `koerperkontakt`-Lifecycle/Reducer um semantisch gebundene **eingeschraenkte** Handlungsbereiche erweitern (Koerperstelle, Handlungstyp, Richtung, Zeit, Provenienz). Dieselbe Schulter `declined`, fremder Unterarm `unknown`; aus unklarer Lesung keine falsche weite Wahrheit ableiten. Kein zweiter Store.
2. **C2**: Regie-Auftrag exakt an die beabsichtigten **kanonischen Fact-IDs** binden; Validierung des Tat-Inhalts und nicht nur seiner groben Klasse. Wenn Inhalt ungeprueft, `nicht_vollzogen` mit sichtbarer Ursache. Vorhandenes Regie-Fact bleibt Owner; Folgewissen nur fuer gepruefte IDs.
3. **C3**: Regie-Kandidatenverteilung fuer >40 Facts ohne semantischen Verlust (deterministischer `alle`-Umfang oder nachvollziehbare Seitennavigation, keine Trunkierung als Wahrheit).
4. **C4**: Stabile Szenenidentitaet/Transitions-Fact in bestehendem `SceneState`/Turn/Fact; Scene-Scope an Szene statt Ort binden. Aeltere Daten ohne Szene-ID nicht still umdeuten.
5. **C5**: Aussagen als getrennte Redeprovenienz/Speech Acts robust ableiten und den tatsaechlichen Negationsbezug am **Ereignis** validieren. LLM-Selbstlabels doppelt abzufragen ergibt keine Faktenquelle. Zuordnung unklar -> unbestätigt, aber ausdrueckliche Behauptung bleibt sichtbar.
6. **C6**: Aktive Versuche ueber alle parallel lebenden Prozesse korrekt verwalten, bedingte Abschlussentscheidung in der SQLite-Transaktion. Boot-ID allein ist kein Liveness-Nachweis; bei Unklarheit nicht automatisch schliessen. UI zeigt den offenen Status.
7. **C7**: Produktiver Writer fuer angenommenes Handlungsangebot -> ausgefuehrte eigene Tat, dann historischer Johann/Alrik/Mara-Recall auf Originalsession, nicht nur einzelne synthetische Beispiele.
8. **C8**: Alle Reparaturen mit realen HTTP-/Browser-/Writer-/Reader-/SQLite-/Folgeturn-Gates gemaess AMASTER 71.0.5 und Kettenvertrag 16. Hashes, alte Fehler, Android und Provider-Live jeweils getrennt dokumentieren.

## DECKBLATT · V65V · Bedeutung gebunden statt Formmerkmal: Grenzumfang, Bestreiten, Regie-Auswahl, laufende Versuche (Claude) · 30.10.2026

**Verbindlich:**
- `2_7master.txt`:
  - §24.2 Z. 1110–1118, §24.6 (Wortschatz nur Kandidat), §24.7 Z. 1250–1254;
  - §34.1 Z. 1807–1815, §36.3 Z. 1937, §36.4 Z. 1941, §36.5 Z. 1947–1975, §37;
  - §46.3 Z. 2565, §46.5 Z. 2589, §46.6 Z. 2596, §63.
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6, §16.

**Eingang:** Unabhängige Nachprüfung v1 zu V65U: K1–K6, alle am V65U-Code rot. Vermerk unten unverändert.

**Basis:** mein V65U-ZIP (SHA256 7f3013ae…). DB und Logs bytegleich, keine Migration.

**Wurzel (Gutachten bestätigt):** V65U prüfte an drei Stellen ein Formmerkmal statt der gebundenen Bedeutung:
- ein Zeitwort statt des Handlungsumfangs;
- ein Täternamen statt eines Bestreitens;
- eine gültige Fact-ID statt der angeordneten Tat.

Dazu kamen zwei Fensterfehler, beide technisch:
- die 12er-Kandidatengrenze;
- das Kappen laufender Versuche.

### Umsetzung (vorhandene Owner, keine neue Route, keine Tabelle)

**K1/K4 · Grenze**
- **Owner:** `conjunctive.validate_grenze` → `kernel._resolve_grenze`/`_body_contact_answer` → `scene_state.body_contact_standing`/`act_consent`.
- **Handlungsumfang und Dauer sind getrennte Achsen (§36.5).** „Jede Berührung“ braucht zwei semantische Schlüssel:
  - die vorschlagende Lesung;
  - UND die eigene Umfangslesung `consent_check` (GRENZE_CHECK_RULES). Wie `effect_check` liest der Server sie vor dem Schreiben, sie zerlegt den Beleg typisiert:
    - `gegenstand` wörtlich, nie der Berührende;
    - `gegenstand_art` = person | koerperstelle_oder_art | diese_handlung;
    - `geltung`.
- Ausgang:
  - Eine Einschränkung bleibt sichtbar `unbestaetigt:umfang_eingeschraenkt` mit Wortlaut und bindet keine andere Berührung.
  - `diese_handlung` → diese Tat.
  - Ohne Umfangslesung → `unbestaetigt:umfang_ungeprueft`.
- **Dauer:**
  - ein genannter Zeitraum (im Beleg verankert);
  - offen nur mit Umfangslesung UND §37-Zeitleser;
  - sonst die **laufende Szene** (Ort + Turn; ein Ortswechsel beendet sie).
  - Statt Verwerfen gilt also die sichere Default nach §46.5.

**K3 · Widerspruch**
- **Owner:** `kernel.apply_statement_components` → `truth.register_denial`.
- Das Täternamen-Tor ist ersetzt durch die eigene Aussagelesung `statement_check` (AUSSAGE_CHECK_RULES), serverseitig vor dem Schreiben.
- Sie zerlegt typisiert:
  - `verneint` wörtlich;
  - `gegenstand` = geschehen | bewertung | gefuehl | anderes;
  - `bestritten` nur bei geschehen.
- Kanonisch nur, wenn beide Lesungen „bestreitet“ sagen und der Beleg wörtlich ist. Bewertung und Gefühl bleiben sichtbare Redeprovenienz.

**K2/K6 · Regie-Auswahl**
- **Owner:** `kernel.execute_regie_information`; Pool `regie_act_pool`: ALLE bekannten Taten des gebundenen Paares, ohne Vordergrundgrenze.
- **Strukturlesung `select_regie_acts`:** liest nur die Anweisung (alle | reihenfolge | bestimmte), nie die Taten.
- **Kernel:**
  - Die Stelle rechnet er aus dem wörtlichen Ordnungswort (geschlossenes Inventar wie §37 heute/morgen).
  - Die Art nimmt er aus der validierten Wirkungsklasse der Taten selbst.
- **Zweite Lesung `select_regie_act_labels`:** Kennungen, Wortlaut V65U.
- Vollzogen wird nur, was beide Schlüssel nennen.
  - Ein Ordnungswort in der Anweisung, das der Auswahl widerspricht → `auswahl_widerspricht_reihenfolge`.
  - Uneinig → `auswahl_schluessel_uneinig`.
  - Ein gültiges, aber falsches Label wird nie vollzogen.
- Betrieb: +2 Aufrufe nur bei einer Mitteilungs-Anordnung.

**K5 · Versuche:** `repos.mark_pending_attempt` kappt nur beendete Versuche. Laufende Versuche dieses Prozesses bleiben bis zu ihrem Ende.

**Sicherheit:** Die Prüfurteile (`pruefung`) setzt nur der Server vor dem Schreiben. Mitgeschickte Urteile des Clients werden verworfen; ein HTTP-Test prüft das.

### Gates
- **Nachprüfung K1–K6 am V65V-Code** (Gutachterdatei unverändert):
  - 5/6 grün: K1, K2, K3, K5, K6.
  - K4 bleibt dort rot, weil die Gutachterprobe nur EINE Lesung ohne Umfangsprüfung liefert. Das ist nach §24.2/§24.7 ein unbestätigter Vorschlag und bleibt sichtbar.
  - Mit Umfangslesung („Fass mich nicht an“ → Person, keine Dauer) gilt die Grenze in der Szene (`declined`), nach Ortswechsel `unknown`. Das zeigt `test_v65v_gegenproben.py::test_K4_*`.
- **Neue Tests:** `test_v65v_gegenproben.py` mit 16 Tests: Positiv- und Grenzfälle, Uneinigkeit der Schlüssel, Urteil vom Client verworfen. V65T/V65U-Tests sind auf das AMASTER-SOLL umgestellt, nicht abgeschwächt.
- **Regression** V65U gegen V65V, beide DBs: 0 neu rot; 486 bzw. 504 bestanden; die 50 bzw. 32 vorbestehenden Fehler sind dieselbe Menge wie bei V65U.
- **prepare-Bytevergleich:** 3 DBs, 40 Sessions, 0 abweichend.
- **TypeScript:** 616 wie V65T, 0 neu (vorbestehend, ROT). **Build** aus `src`: Exit 0, 42 Assets.
- **Messungen** (Endfassung, `scripts/v65v_gegenproben/messung/`):
  - Umfangslesung: 20 Sätze, davon 6 zurückgehalten. Mit dem Endkernel 18/20, **0 FP**, 2 FN („Keine Berührungen mehr“, „Finger weg von mir“).
  - Aussagelesung: 18 Segmente, 17/18, **1 FP** („Kvle hat mich nicht belästigt“ als geschehen gelesen). Kanonisch wird es nur, wenn auch die Formulierung es als Bestreiten etikettiert.
  - Regie: 12 Anweisungen, 9/12, **0 FP**, 3 FN („Sag die Wahrheit …“, „nur von seiner ersten Berührung“, „wie er gekniffen hat“).
  - Vorstufen mit höherer Fehlerrate sind mitgeliefert und verworfen.
- **Browser-E2E** am frisch entpackten Kandidaten-ZIP (START.py, 86 Modellaufrufe):
  - React #418: 0 auf 9 Routen; 0 Konsolen- und Seitenfehler.
  - Regie-Zeilen 2/3 vollzogen, je 3 Taten. Struktur „alle“ und Kennungen sind einig.
  - Zeile 1 nicht gebunden (FN).
  - Maras Ablehnungen je Tat.
  - Reload und Sessionwechsel gleich.
  - Provider-Fehler: Banner, Text bleibt, Reload, erneut erzeugen, abschließen; Config bytegleich, Sicherung gelöscht.
  - Isolation: nur dein User-Eintrag.
  - **Nicht live ausgelöst:** In diesem Lauf schlug das Modell weder „jede Berührung“ noch ein Bestreiten vor. Die beiden neuen Prüflesungen liefen deshalb im Browser nicht; belegt sind sie durch Proben und den HTTP-Test.

**Modellaufrufe V65V:** 400 gesamt (Proben 314 einschließlich verworfener Fassungen, E2E 86).
- Betrieb: +1 je vorgeschlagener „jede Berührung“, +1 je vorgeschlagenem Bestreiten, +2 je Regie-Mitteilungsanordnung. Sonst 0.

**OFFEN / ROT:**
- Aussagelesung: 1/18 FP. Kanonisch nur zusammen mit der Formulierung; deren Lieferung lag in V65T bei 0/9.
- Falsch-negative bei Grenze und Regie (siehe oben).
- Pronomen T2 nicht neu gemessen.
- TypeScript 616 vorbestehend.
- Android NICHT_PRÜFBAR; keine AMASTER-Gesamtabnahme.

## NACHPRÜFUNG v1 zu V65U · Vermerk (Eingang V65V, 30.10.2026) – unverändert übernommen
### MATRIX10 V65U – unabhängige Nachprüfung

Zwischenbefund: V65U ist eine echte Weiterentwicklung von V65T, aber noch nicht abnahmereif. Die fünf ursprünglichen Gegenbeispiele werden gezielter behandelt. Entscheidend ist jedoch, ob die neue Lösung auch andere, bisher nicht getestete Formulierungen richtig verarbeitet.

Die Archivprüfung ist abgeschlossen:

* MD5 und SHA-256 stimmen exakt mit dem Baubericht überein.

* Die enthaltene SQLite-Datei ist 36.769.792 Byte groß.

* 21 bestehende Dateien wurden gegenüber V65T verändert.

* Die 42 Frontend-Assets wurden durch neue Build-Artefakte ersetzt.

* Von den 21 mitgelieferten neuen Tests konnte ich 20 selbst erfolgreich ausführen. Der verbleibende Test benötigt Flask, das dieser Prüfumgebung fehlt.

Das sind nachvollziehbare Fortschritte. Die vom Entwickler berichteten Browserläufe, Modellaufrufe und vollständigen Regressionsergebnisse sind dadurch allerdings noch nicht unabhängig bestätigt.

### Sechs neue Gegenproben am V65U-Code

6 von 6 Gegenproben fehlgeschlagen

Das bedeutet: Sechs zusätzliche Anforderungen der Architektur werden vom aktuellen Code nicht zuverlässig erfüllt. Die Tests verwenden kontrollierte Eingaben und den tatsächlichen Kernel-/SQLite-Pfad, keine nachträgliche Antwortkorrektur.

| Befund              | Nachgewiesenes Problem                                                                                                                                                | Bewertung       |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| K1 – Grenze         | „Fass mich nicht mehr auf die Schulter“ verbietet fälschlich auch eine spätere Berührung des Unterarms.                                                               | ROT             |
| K2 – Regie          | Angeordnet ist die erste Tat, aber die letzte wird ausgewählt. Der Writer speichert trotzdem vollzogen.                                                               | ROT             |
| K3 – Widerspruch    | „Ich fühle mich durch Kvle nicht belästigt“ erzeugt bei falscher Modellklassifikation einen kanonischen Widerspruch.                                                  | ROT             |
| K4 – Grenze         | „Fass mich nicht an“ verliert ohne zusätzliches Zeitwort seine weitergehende Wirkung, auch im untersuchten unmittelbaren Szenenverlauf.                               | Scope ungeklärt |
| K5 – Wiederaufnahme | Bei neun parallelen Versuchen wird ein noch laufender Versuch aus der auf acht Einträge begrenzten Historie verdrängt. Danach ist ein unzulässiger Abschluss möglich. | ROT             |
| K6 – Regie-Recall   | Von 13 relevanten Taten werden nur die letzten zwölf angeboten. Die erste ist für die Auswahl nicht erreichbar.                                                       | ROT             |

### Was tatsächlich besser geworden ist

Die leere Hörerliste wird jetzt korrekt behandelt. Die getrennten Versuchs-IDs funktionieren in den vorhandenen Zwei-Versuchs-Tests. Der Frontend-Build ist anhand der mitgelieferten Quellen und Prüfsummen konsistent.

Die Entwicklerprotokolle belegen außerdem einen Browserlauf ohne React #418 auf neun Routen. Einen eigenen Browserlauf konnte ich hier nicht ausführen. Die im Bericht genannten 616 bereits bestehenden TypeScript-Fehler bleiben ebenfalls bestehen.

### Die eigentliche Ursache

V65U prüft an kritischen Stellen weiterhin formale Merkmale, nicht ausreichend die gebundene Bedeutung.

Bei Einwilligung ersetzt ein Zeitwort die Prüfung des Handlungsumfangs. Bei Widersprüchen ersetzt die Nennung eines Täters die Prüfung, ob eine Tat tatsächlich bestritten wird. Bei der Regie garantiert eine gültige Fact-ID noch nicht, dass es die angeordnete Tat ist.

Genau an diesen Stellen entstehen falsche kanonische Zustände. Die Lösung muss in den vorhandenen semantischen Bindungs-, Validierungs- und Commitpfaden erfolgen.

### Versionierter Prüfbericht

Gesamte Nachprüfung v1 herunterladen

Prüfbericht, sechs reproduzierbare Tests, Testausgaben und SHA-256-Nachweise

Unabhängiges Codegutachten lesen

IST-Karte, Fehlerursachen, Writer-/Reader-Kette, Abnahme und Korrekturreihenfolge

Gegenproben als Python-Datei

Unveränderter Produktcode, Tests auf Datenbankkopien

Tatsächliche Testausgabe

Sechs fehlgeschlagene Soll-Assertions mit Details

Endurteil: V65U behalten, aber nicht freigeben. Es gibt echte technische Fortschritte, jedoch keine geschlossene Architektur-Abnahme. Die nächsten Korrekturen sind aus AMASTER ableitbar. Dafür brauchst du keine weiteren Grundsatzentscheidungen zu treffen.

Das Produkt-ZIP, seine SQLite-Datenbank und die sieben Logs habe ich nicht verändert.


## DECKBLATT · V65U · Gegenproben N1–N5 geschlossen, Oberfläche aus dem Quellstand gebaut, sichere Wiederaufnahme (Claude) · 30.10.2026

**Verbindlich:**
- `2_7master.txt`:
  - §24.2 Z. 1110–1118, §24.6 Z. 1226–1242, §24.7 Z. 1250–1254;
  - §34.1 Z. 1803/1807–1815, §36.3 Z. 1937, §36.4 Z. 1941, §36.5 Z. 1947–1975, §37;
  - §39 Z. 2089/2095, §46.2 Z. 2549, §46.3 Z. 2565, §46.4 Z. 2583, §46.5 Z. 2589, §46.6 Z. 2596, §63;
  - §71 G1/G6–G10/G12/G13.
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6, §16.

**Eingang:**
- Unabhängiges Codegutachten v1 zu V65T: N1–N5 ROT, T7 ROT. Vermerk unten unverändert.
- Deine Vorgaben vom 30.10.:
  - D1: Einwilligung/Grenze semantisch, handlungsbezogen, mit Provenienz, Geltungsbereich und Zeit validieren; keine Wahrheit allein aus Modellfeld oder Wortliste.
  - D2: Widerspruch nur bei belegtem Bestreiten eines konkreten Ereignisses über den zuständigen Writer; Bewertungen sind kein Widerspruch.
  - D3: Frontend reproduzierbar aus den Quellen bauen, Hydration-Ursache beseitigen, vorhandene Funktionen im Browser erneut abnehmen.

**Basis:** mein V65T-ZIP (SHA256 ad29fe80…). DB und Logs bytegleich zu deinem V65Q-ZIP, keine Migration.

**Nachprüfung vor dem Bau** (`scripts/v65u_gegenproben/V65U_NACHPRUEFUNG_PLAN_20261030.md`):
- Alle fünf Gegenproben habe ich am unveränderten V65T-Code nachgebaut; alle fünf schlagen dort fehl.
- Die UI-Befunde sind im Quelltext bestätigt.

### KORREKTUR meiner V65T-Einträge
- **T1 „GRÜN“ war falsch.** Das Etikett `jede_beruehrung` der Lesung entschied allein über eine dauerhafte Grenze (N1).
- **T4 „GRÜN“ war falsch.**
  - Hörer: `hears_ids or present` – eine leere Liste galt als fehlend (N3).
  - Inhalt: alle Taten von→an statt der angeordneten (N5).
- **„src und V58-Chunks sind nicht gegenseitig reproduzierbar“ war falsch.** Die verlangte Machbarkeitsprüfung hatte ich nicht gemacht. `npm ci && npm run build:dist` läuft am Quellstand fehlerfrei.
- **T3:** Der Falsch-positiv-Weg über das Etikett (N2) war offen. Ich hatte nur die fehlende Lieferung gemeldet.

### Umsetzung je Befund

Owner, Writer und Reader habe ich vor jeder Änderung geprüft. Es gibt keine neue Route, keine Tabelle und keinen Antwortfilter.

**N1 · Grenze für jede Berührung**
- **Owner:** `conjunctive.validate_grenze` (§37-Zeitleser); Writer: Lifecycle über `_body_contact_answer`.
- **Wurzel:** Der Validator prüfte Wortlaut und Zeitangabe, nie die Geltung über die eine Tat hinaus.
- **Neu (§24.2 Z. 1110–1113, §24.6, §46.4/§46.5):** Zwei Schlüssel:
  - die Lesung sagt `jede_beruehrung`;
  - UND der §37-Zeitleser liest im Beleg selbst die Geltung – offen („nie wieder“, „ab jetzt“, `parse_geltung`) oder ein Fenster („heute“), wörtlich im Beleg, nicht irgendwo in der Rede.
- Fehlt der zweite Schlüssel, gilt `ungueltig: geltung_nicht_belegt`. Der Vorschlag bleibt sichtbar, die Antwort gilt ihrer Tat. Der Wortschatz ist Kandidat des Zeitlesers, keine Wahrheitshoheit.
- **Gegenprobe:** „Lass das!“, „Lass das“, „Hör auf damit“, „Nicht so“, je mit falschem Etikett:
  - die spätere Tat bleibt `unknown`, auch nach Reload;
  - „Fass mich nie wieder an“ → `declined`.
- **Falsch-negativ, bewusst:** „Fass mich nicht an!“ ohne Geltungswort bindet keine spätere Tat (§46.5 sichere Default).

**N2 · Widerspruch**
- **Owner/Writer:** `kernel.apply_statement_components` → `truth.register_denial`.
- **Wurzel:** Ereignis-Kennung und wörtliches Segment wurden geprüft. Ob es ein Bestreiten der Tat ist, entschied allein das Etikett.
- **Neu (§24.2, §34.1 Z. 1807–1815, §36.3/§36.4):** Bestreiten bindet nur, wenn das Segment den Täter der gebundenen Tat nennt. Das prüft der Cast-Resolver `_named_by_name_part`, ohne Modellfeld und ohne Wortliste („Wer hat es getan?“).
- Sonst gilt `unbestaetigt: taeter_nicht_benannt`, mit `vorschlagFactIds`, als sichtbare Redeprovenienz. Es gibt keinen Writer-Aufruf.
- **Gegenprobe:** 5 Bewertungen mit falschem Etikett (u. a. „Ich fühle mich nicht belästigt“) → 0 Widerspruch. „Kvle hat mich nie angefasst“ → Evidenz. Ein fremder Name bindet nicht.
- **ROT bleibt:**
  - die Lieferung der Teilaussagen durch das Modell (0/9 in V65T, unverändert);
  - Bestreiten ohne Täternamen („Da war nichts“, „Er hat mich nie angefasst“) ist falsch-negativ.

**N3 · Hörer des Regie-Vollzugs**
- **Neu:** `execute_regie_information` liest die Hörer über `_effective_hears` (§39). Eine leere Liste bleibt leer.
- **Gegenprobe:** `hears_ids=[]` → nur der Empfänger. Ohne Feld → Szenenwahrnehmung.

**N5 · Welche Taten die Regie mitteilt**
- **Wurzel:** „von→an“ nahm alle Taten.
- **Neu (§24.2 Z. 1111 „soweit erforderlich“, §46.3/§46.6):**
  - Die Regie-Lesung ist unverändert gegenüber V65T, also gleiche Bindungen.
  - Der Kernel engt die Kandidaten strukturell ein (`regie_taten_persons`, `regie_act_candidates`): Taten, die die Figur kennt, mit gebundenem Täter und Person. Je Zeile steht „n. von m“ und die validierte Wirkung.
  - Eine kleine Auswahl-Lesung (`select_regie_acts`, +1 Aufruf, nur bei einer Mitteilungs-Anordnung mit Kandidaten) wählt Kennungen. Der Writer prüft Kennung, Kenntnis und Personen.
  - Keine Kennung oder eine fremde Kennung → `nicht_vollzogen`, sichtbar.
- **Messung** (30 Aufrufe, `messung/regie_auswahl_probe65u.json`):
  - 20/21 richtig, **0 überzählige Taten**, Bindungen 12/12 gleich V65T;
  - „nur die erste“ → 1 Tat, „letzte“ → 1, „wie er gekniffen hat“ → 1, „ersten zwei“ → 2.
- **Verworfen:** Vier Fassungen mit Kandidaten in der Regie-Lesung selbst (144 Aufrufe). Sie hatten bis zu 4 Falsch-positive, und eine Entschuldigung wurde zur Handlung. Belege in `messung/`.

**N4 · Wiederaufnahme**
- **Owner:** `repos.mark_pending_attempt` im Envelope-Feld `pendingInputAttempt`; Reader: `kernel.pending_input_view`.
- **Wurzel:** ein einziges Feld ohne Versuchs-ID, „läuft“ über einen 180-s-Timer.
- **Neu (§24.2 Z. 1118, §63):**
  - Jeder Versuch hat eine eigene ID und die Start-ID des Serverprozesses.
  - Übergänge gelten nur für die eigene ID, in der Schreibtransaktion.
  - „Läuft“ heißt, ein Versuch dieses Prozesses steht auf `laeuft`. Ein Neustart beweist das Ende; es gibt keinen Timer.
  - `resumePending` im prepare nimmt die gespeicherte TurnTruth.
  - Sessionantwort und GET tragen `pendingInput` als Lesestand. Er wird nie gespeichert.
- **Gegenprobe:**
  - A und B laufen, A endet → B läuft weiter;
  - Neustart → läuft nicht;
  - Abschluss während eines Laufs → 409, nach Neustart erlaubt;
  - der V65T-Envelope läuft nie.

**T7 · Oberfläche**
- **Wurzel #418:** START.py liefert für jede Route die für „/“ vorgerenderte Seite aus.
- **Neu:**
  - Echter Vite-Build aus `src` (`npm ci && npm run build:dist`, 42 Assets). `.build-info.json`: `sourceTreeSha256` = Hash von `src`.
  - `index.html` = SPA-Hülle von TanStack Start (TSS_SHELL: nur Root-Route) mit `<meta name="matrix-build">`.
  - Chat:
    - Banner der offenen Eingabe aus dem gespeicherten Stand, mit „Antwort erneut erzeugen“ und „Eingabe ohne Antwort abschließen“;
    - der Eingabetext bleibt bei Fehler stehen.
  - Tests, die minifizierte Chunk-Formen prüften, prüfen jetzt Quelltext + Build-Hash + Laufzeit.
  - TypeScript: 616 Fehler wie V65T (vorbestehend), 0 neue.

### Gates
- **Regression** V65T gegen V65U, deine DB und Alt-DB: 0 neu rot. 470/488 bestanden. Die 50/32 vorbestehenden Fehler sind dieselbe Menge wie bei V65T.
- **Neue Tests:** `test_v65u_gegenproben.py` (21): auf V65U 21/21 grün; auf V65T 19 rot, 1 grün (die Positivprobe „nie wieder“).
- **prepare-Bytevergleich** V65T = V65U auf 3 DBs: 40 Sessions, 0 abweichend.
- **Browser-E2E** am frisch entpackten ZIP über START.py (100 Modellaufrufe):
  - React #418: 0 auf 9 Routen (`/`, `/chat`, `/chat/:sid`, `/welt`, `/charakter`, `/config`, `/diagnose`, `/timeline`, `/memory`); 0 Konsolenfehler, 0 Seitenfehler.
  - Regie-Zeilen 2 und 3 vollzogen, je 3 Taten, Alrik `informed` 3. Zeile 1 („Sag die Wahrheit …“) ohne Inhaltsbindung, nicht vollzogen (falsch-negativ).
  - Maras Ablehnungen gelten je Tat (`diese_tat`).
  - Reload und Sessionwechsel gleich.
  - Erzwungener Provider-Fehler (Endpoint ins Leere):
    - Banner, Text bleibt, Banner nach Reload;
    - „Antwort erneut erzeugen“ → Maras Antwort, Eingabezeile 1×;
    - zweiter Fehler → „Eingabe ohne Antwort abschließen“ → Systemzeile, kein Banner;
    - Config danach bytegleich.
  - Neustart: Rücklesen gleich, `pendingInput` leer.
- **Isolation:** 0 alte Zeilen verändert, außer deinem User-Eintrag (`lastSessionId`, `avatarsByWorld`, wie bisher).
- **Schlüsselsuche:** Kein Config-Schlüssel im Paket. Ein generisches Muster in `shell-*.js` ist der Tailwind-Klassenname `mask-image-…`, kein Schlüssel.

**Modellaufrufe:**
- Betrieb: +1 nur bei einer Regie-Mitteilungsanordnung mit Kandidaten, sonst 0.
- Messung: 274 (Auswahl 30 + verworfene Fassungen 144 + E2E 100).

**OFFEN / ROT:**
- **T2 Pronomen-Signal:** in V65U nicht weiter gemessen (Stand V65T: 7/10, 0 falsch). Kein Routenlauf Teil B.
- **T3 Erkennung:** Lieferung 0/9. Bestreiten ohne Täternamen bleibt falsch-negativ.
- **Regie-Zeile „Sag die Wahrheit, was hast du mit Mara gemacht“:** teils ohne Inhaltsbindung, falsch-negativ.
- **Neustart während eines laufenden Versuchs:** nur im Test geprüft, nicht live.
- **SQL-Delta:** Messung aus V65T, nicht neu gemessen.
- **Android:** NICHT_PRÜFBAR.
- **Gesamtabnahme:** keine AMASTER-Gesamtabnahme.

## GUTACHTEN v1 · Vermerk (Eingang V65U, 30.10.2026) – unverändert übernommen
### MATRIX10 V65T – unabhängige Prüfung

Nicht zur Gesamtabnahme freigeben

Mein bisheriges Ergebnis: V65T enthält echte Verbesserungen, aber auch nachweisbare Fehler in der kanonischen Verarbeitung. Der Baubericht ist in wesentlichen Punkten nachvollziehbar, seine GRÜN-Bewertungen sind jedoch teilweise zu großzügig.

Die gelieferte ZIP-Datei ist vorhanden und vollständig lesbar. MD5 und SHA-256 stimmen exakt mit dem Baubericht überein.

Unabhängige Testausführung: 48 der neuen Tests bestanden. Zusätzlich habe ich vier Gegenbeispiele erstellt, die von den mitgelieferten Tests nicht ausreichend abgedeckt werden. Alle vier weisen einen Fehler nach:

* Einwilligung: „Lass das!“ kann fälschlich zu einer allgemeinen, dauerhaft geltenden Kontaktverweigerung werden, wenn die semantische Lesung einen zu weiten Geltungsbereich liefert.

* Widerspruch: „Ich fühle mich nicht belästigt“ erzeugt fälschlich einen kanonischen Widerspruch, wenn das Modell diesen Satz als Bestreiten der Handlung klassifiziert.

* Figurenwissen: Bei ausdrücklich leerer Hörerliste (`hears_ids=[]`) verteilt der Regie-Writer Wissen trotzdem an weitere Anwesende.

* Wiederaufnahme: Zwei überlappende Antwortversuche können sich gegenseitig ihren Status überschreiben. Dadurch erscheint eine Eingabe als nicht mehr in Bearbeitung, obwohl der zweite Versuch noch läuft.

Diese Gegenbeispiele wurden am gelieferten V65T-Code ausgeführt, nicht nur aus dem Bericht abgeleitet.

### Bewertung der sieben Arbeitsschritte

| Bereich                | Meine Bewertung     | Begründung                                                                                            |
| ---------------------- | ------------------- | ----------------------------------------------------------------------------------------------------- |
| T1 Einwilligung        | ROT                 | Konkrete Tatbindung verbessert, aber falscher kanonischer Geltungsbereich möglich                     |
| T2 Pronomen und Recall | TEILGRÜN            | Mit korrekter Referenz 3/3 Taten; Originalfrage bleibt ungebunden                                     |
| T3 Widerspruch         | ROT                 | Modell liefert keine Teilaussagen; zudem kann eine falsche Klassifikation einen Widerspruch committen |
| T4 Regie               | ROT als Gesamt-Gate | Echte Regie-Wirkung vorhanden, aber konkrete Tat und Hörerschaft können falsch gebunden werden        |
| T5 SQLite              | Vorläufig GRÜN      | Delta-Verhalten durch Tests gestützt; Leistungszahlen nicht unabhängig gegen V65S nachgemessen        |
| T6 Wiederaufnahme      | ROT als Gesamt-Gate | Status konkurrierender Versuche nicht sicher; Bedienung unvollständig                                 |
| T7 Oberfläche          | ROT                 | Hydration-Problem ungelöst, Wiederaufnahme nach Reload nicht vollständig bedienbar                    |

### Zusätzlicher Befund zur Oberfläche

Im Chat-Quellcode wird der Eingabetext bereits vor erfolgreicher Übermittlung geleert. Bei einem Fehler wird er nicht zuverlässig wiederhergestellt. Ein eigener Knopf „Antwort erneut erzeugen“ fehlt. Der Abschlussknopf erscheint erst nach einem bestimmten Fehler und nicht automatisch anhand des gespeicherten offenen Turns.

Damit ist die Wiederaufnahme nicht so umgesetzt, wie sie im Plan vorgesehen war.

### Entscheidung zu T3

Das Feld `aussagen` behalten – aber noch nicht als funktionsfähige Widerspruchserkennung freigeben.

Ein stärkeres Modell allein wäre keine korrekte Reparatur. Mein Gegenbeispiel zeigt, dass selbst ein formal vollständig geliefertes Feld einen falschen kanonischen Commit auslösen kann.

Die richtige technische Reihenfolge ist: erst die semantische Validierung vor `register_denial` reparieren, dann prüfen, ob das vorhandene Modell die Komponenten zuverlässig liefert. Ein zusätzlicher Modellaufruf ist derzeit nicht gerechtfertigt. Auch dessen Ausgabe dürfte niemals allein über Weltwahrheit entscheiden.

### Was V65T tatsächlich erreicht hat

V65T ist kein bloßer Prompt-Flick. Im Code sind echte Änderungen an bestehenden Commit-, Recall-, Regie- und Persistenzpfaden vorhanden. Insbesondere die Trennung zwischen Regie-Wirkung und Johanns eigener Reaktion ist architektonisch richtig angelegt.

Aber funktionierende Writer genügen nicht, wenn sie falsche kanonische Tatsachen erzeugen können. Deshalb müssen zuerst die fünf nachgewiesenen Gegenfälle behoben werden. Danach gehören die produktive Pronomenbindung, sichere Wiederaufnahme und der reproduzierbare Frontend-Build geschlossen.

Die behaupteten 52/52 Tests, 353 Modellaufrufe, Browserläufe und Geschwindigkeitsmessungen stehen im Entwicklerbericht. Unabhängig bestätigen konnte ich 48 bestehende Tests sowie die fünf zusätzlichen Fehlernachweise. Flask, Browser-Live, Android-Live und den vollständigen V65S/V65T-Vergleich konnte ich hier nicht ausführen.

### Prüfdateien

Unabhängiges Codegutachten v1 – Deckblatt, IST-Karte, Ursachen und Abnahme

Fünf reproduzierbare Gegenprüfungen (Python)

Ausführliche Testausgabe

T32-Prüfung auf Datenbankkopie

Gesamturteil: V65T als Zwischenstand aufbewahren, aber nicht als abgeschlossene Korrektur freigeben. Das Original-ZIP und die Datenbank habe ich nicht verändert. Das Gutachten ist versioniert; die zusätzlichen Tests liegen getrennt vom Produktcode.


## DECKBLATT · V65T · Einwilligung je Tat, Pronomen-Referent, Widerspruch als Evidenz, Regie-Vollzug mit zwei Ausgängen, SQL-Delta, Wiederaufnahme (Claude) · 30.10.2026

**Verbindlich:**
- `2_7master.txt`:
  - §24.1/§24.2/§24.7, §25, §27.5 Z. 1409–1415;
  - §34–§34.3, §35, §36.3/§36.4/§36.5 (Z. 1937–1977), §37;
  - §38–§41.5, §46.2/§46.4/§46.6, §49, §50 Z. 2817, §63, §68 Nr. 24/45;
  - §71 (Gate-Vertrag §71.0.5; G1, G6–G10, G12, G13).
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6, §16.

**Eingang:**
- Gegenprüfung v3.2 (V65S ROT; Nachtrag unten unverändert übernommen).
- Plan-Gegenprüfung v3.3 (mein Plan v1 ROT).
- Plan v2 und **deine Entscheidung A mit Korrektur** (30.10.): Regie vollzieht die Informationshandlung selbst, Johanns Rede ist seine Reaktion, zwei getrennte Ausgänge.

**Basis:**
- Code = mein V65S-ZIP (SHA256 `e8e819fe…`).
- Daten bytegleich zu deinem V65Q-ZIP (DB `9be11b84…`, sieben Logs).
- Keine Migration.

**Modellaufrufe:**
- Im Betrieb: **0 zusätzlich** (alle neuen Lesungen sind Felder vorhandener Aufrufe).
- Messungen: 353 gesamt:
  - Pronomen-Signal 171;
  - Teilaussagen 9;
  - Grenze 8;
  - Regie-Taten 20;
  - Routenlauf 75;
  - Browser-E2E 70.

### V65T · Stand je Schritt (gemessen, nicht geschätzt)

| # | AMASTER | Wurzel (IST V65S) | Änderung | Messung / Gate | Status |
|---|---|---|---|---|---|
| T1 | §36.5 Z. 1947/1974, §34.1, §35, §37 | Eine Paar-Angelegenheit übertrug `accepted`/`declined` auf jede spätere Tat (v3.2 Befund 1) | Container bleibt. Jede Antwort bindet die beantwortete Tat (`actFactIds`) und ihre Geltung. Grenze für jede Berührung nur mit wörtlichem Beleg, gebundener Person und Zeitfenster. Reducer `scene_state.act_consent`. Spiegel: GRENZE/ERLAUBNIS oder ABLEHNUNG als Abfolge | 15 Tests G10 inkl. Negativsatz (0 falsch-positiv). Routenlauf und E2E: jede Ablehnung an ihre Tat gebunden, spätere Taten `unknown`. Grenze-Lesung 8 Läufe: 0 falsch-positiv | **GRÜN** offline/Route/E2E. Echte „jede Berührung“-Grenze im Lauf nicht vorgekommen. Bindung einer eigenen Tat an die eigene angenommene Bitte: kein Writer (falsch-negativ) |
| T2 | §24.1/§24.7/§25 → §40/§41.3 | `normalize_plan` verwarf „Johann“ bei „er“; Selektor ordnete Reden vor Taten (v3.2 Befund 2/3, v3.3) | Lesung liefert nur das grammatische Signal (Pronomen + Genus). Kernel bindet nur maskulin, nur bei genau einem gehörten männlichen Kandidaten. Guard lässt genau diesen Referenten zu. Eine gebundene Selektorstufe: Ursache-Taten → Antworten → Rest | Signal: 0 falsch-positiv in allen Messungen. Erkannt: Probe 7/10, Route 2/3, E2E 0/2 (meist falsches Pronomen „sie“ für „dich“). Mit Bindung: deine T32 3/3 Taten in Auswahl und Erinnerung, Route 4/4 | **TEILGRÜN**: Bindung und Auswahl richtig; das Signal kommt nur in rund 60 % der Fälle |
| T3 | §34.1, §36.3/§36.4, §50 | `register_denial` ersatzlos entfernt (v3.2 Befund 4) | Teilaussagen `aussagen` im Formulierungsschema, Ereigniskennungen `[E#]` im Brief. Kernel prüft Segment und eigenes Ereignis. Nur `bestreitet_geschehen` → `register_denial` als Ausführer. Reader: Dialog, Erinnerung, UI | 5 Tests inkl. Negativsatz (0 falsch-positiv). Lesung geliefert: 0/9 (gpt-4o-mini) | **ROT** in der Wirkung: Mechanik vorhanden, das Modell füllt das Feld nicht |
| T4 | §27.5, §46.2/§46.4/§46.6, §34.2/§34.3, §38/§39 | Regie-Ausgang nicht committed; nur eine Rede-Anweisung (v3.2 Befund 5) | Lesung nennt `taten von/an`. Der Kernel bindet die Tat-Facts. Der Regie-Writer schreibt den sichtbaren Vollzugs-Fakt, `informed` + Erinnerung beim Empfänger (Abwesende nichts) und Lifecycle `regie_wirkung`. Johanns Rede → Lifecycle `figurenreaktion` | 11 Tests (Abnahme deiner Entscheidung). Lesung 9/10, 0 falsch-positiv. Route: vollzogen 2/3 Zeilen, Alrik kennt 4/4 Taten. E2E: vollzogen 2/3, sichtbar im Chat, Reaktion `verweigert`, Reload und Sessionwechsel gleich | **GRÜN** für Vollzug und Anzeige. Erste Regiezeile im Lauf ohne `taten` (falsch-negativ). Figurenreaktion meist `nicht_bestimmt`/`verweigert`, weil T3 nichts liefert |
| T5 | §63, §68 Nr. 24 | Je Ziel zwei volle Session-Neuladungen; UPDATE ohne Änderung | Eine Abfrage je Kindtabelle und Speichern. Zielstatus einmal je Speichern. Kein UPDATE bei gleichem Inhalt | No-op deine Session: 2.395 → 294 SQL, 64 → 1 UPDATE, 0,85 → 0,06 s. DB danach gleich wie nach V65S-Speichern. Echter Lauf: 52 Speichern 13,7 → 1,07 s | **GRÜN** |
| T6 | §24.2, §63 | 409 `INPUT_PENDING` ohne Ausweg (v3.2 Befund 7) | Versuchsstatus im Envelope (läuft/Provider-Fehler/formuliert). 409 nennt die wartende Eingabe. Gleiche Eingabe = erneut erzeugen. „Eingabe ohne Antwort abschließen“ über den Commit-Pfad: nur ausdrücklich, nur ohne laufenden Versuch, sichtbar. Später Commit → 409 `TURN_NOT_OPEN` | 4 Routentests (Flask). Kein Browser-Lauf mit erzwungenem Netzfehler | **TEILGRÜN**: Server und Knopf gebaut, im Browser nicht ausgelöst |
| T7 | §71.2.1/G12 | Nichts davon sichtbar; React #418 | Anzeigezeile `ausgang` an den Turnzeilen des Commits (Einwilligung, Regie-Wirkung, Figurenreaktion, Aussage gegen Erleben); Namen statt Roh-IDs | E2E: Anzeige vorhanden, nach Reload und Sessionwechsel gleich. #418: 5× | **TEILGRÜN**. #418 **ROT**: Ursache = vorgerenderte Startseite wird für jede Route ausgeliefert und hydriert; nicht behoben (bräuchte neuen Vite-Build oder SPA-Shell) |

**Zusatzbefund (behoben):** Abwesende Figuren erschienen in Briefs deiner Session als Roh-ID („Akteure … char_g7_clara, char_g7_johann“, „Ausgang: char_g7_johann hat dich …“). Jetzt Namen aus Besetzung, Turns und Beziehungen.

**Bytevergleich prepare (0 Modellaufrufe, V65S gegen V65T):**

| DB | gleich | Änderungen | unerwartet |
|---|---|---|---|
| deine | 9/17 Briefs | `[E#]` 27 Zeilen, Namen 3 | 0 |
| alt | 5/5 Briefs | – | 0 |
| E2E-V65S | 9/18 Briefs | `[E#]` 31, Einwilligung 3, Namen 6 | 0 |

**Regression:** siehe `scripts/v65t_einwilligung_regie/regression/` (V65S gegen V65T, beide DBs). Die 50 bzw. 32 Altfehler bleiben ROT benannt.

**Testtrennung:**
- Offline: 52 neue Tests.
- Route: Flask-Testclient und Routenlauf mit deinem Schlüssel auf DB-Kopien.
- Browser: frisch entpacktes ZIP, START.py.
- Android: nicht prüfbar.

---

## PLAN-GEGENPRUEFUNG v3.3 · Vermerk (Eingang V65T, 30.10.2026)
- Plan v1 ROT; alle Befunde von mir nachgemessen und bestätigt:
  - Selektor bei Limit 1;
  - `effectKind` zu grob;
  - Referenz ≠ Wissen;
  - kein Selbst-Etikett `wahr/unwahr`;
  - kein automatischer Fail-Marker;
  - 0 falsch-positiv statt Quoten.
- Plan v2 und Entscheidung A: `scripts/v65t_einwilligung_regie/V65T_PLAN_v2_20261030.md`.

---

## PRUEFNACHTRAG v3.2 - Unabhaengige V65S-Gegenpruefung, 30.10.2026 (nicht Teil der ausgelieferten V65S-Version)

**STATUS: ROT fuer die Gesamtfunktion.** Die Aussagen des folgenden historischen V65S-Deckblatts sind keine Gesamtabnahme. Es wurden KEINE Produkt-Dateien geaendert. Nachweise: `MATRIX10_V65S_AMASTER_GEGENPRUEFUNG_v3_2_20261030.md`.

| V65S-Annahme | Nachgemessenes IST | Abhaengigkeit / notwendige Konsequenz |
|---|---|---|
| S1: Einwilligung aus einer Proposition | **Fehler:** eine einzige X->Y-`koerperkontakt`-Proposition uebertraegt eine fruehere `accepted`-Einwilligung auf einen spaeteren `strike` (am echten V65S-Writer reproduziert). | AMASTER §36.5: konkrete Handlung/Scope/Zeitraum; Paar-Proposition darf nicht pauschal jede spaetere Tat freigeben. |
| S3: Ereignisse durch IDs im Vordergrund | **Fehler:** Original-T32 `Hat er dich belaestigt?` nennt Johann nicht, daher im Vordergrund 0/3 seiner Koerpertaten und 0 relevante Ablehnungen; 10 Facts je Prompt. | Erst TurnTruth-/Fact-basierte Referentenkette, danach konjunktive Fact-Auswahl (§24.1/§25 -> §40 -> §41). |
| S4: R5 entfernt, Wahrheit folgt aus dem Brief | **Regression:** `truth.register_denial` mitsamt `apply_erlebt_check` entfernt; keine neue Widerspruchs-Evidenz bei Aussage gegen eigene Tat (bestehender Test erwartet sogar 0 contradiction). | Eigene Aussage bleibt frei; neuer Luegen-/Widerspruchsstatus muss beim Ereignis in bestehendem Truth-/SceneFact-Owner entstehen (§34.1, §36.4, §50); kein Output-Guard. |
| S5: kompakter Prompt | **Nur Teilgewinn:** Original T32 72.781 -> 31.174 Zeichen, BRIEF weiterhin 14.990 Zeichen; relevante Facts weiterhin 0/3. | Erst fachlich richtiger Recall, dann Transport minimieren (§49). |
| S6: eine Speicherung | **Teilgewinn:** 3.555 -> 2.395 SQL-Anweisungen; noch 2.331 SELECT und 64 UPDATE selbst im No-op. Historische Zeugenwissen-Kopie wird im Session-JSON entfernt, SQL-Zeugen bleiben. | Echter Delta-Writer, Owner/Isolation/Atomizitaet bewahren (§63). |
| S7: Regie spricht als Figur | **Teilgewinn:** Johann antwortet als Johann; Inhalt nur 1/3, Regieauftrag ohne committed `fulfilled/refused/failed`. | Regie-Quellfact mit Sprech-Fact und Ergebnisstatus verknuepfen, keine spaetere LLM-Textkorrektur (§27.5/§46.2). |
| Session und UI | **Offen:** bei Netzabbruch pending Turn -> 409 bei neuer Eingabe; React #418; Angelegenheiten nicht sichtbar. | Vor Wiederholung/Neustart den vorhandenen Turn sicher wiederaufnehmen; UI- und Android-Live gesondert pruefen. |

**Testtrennung:** lokal 43 vorhandene + 2 unabh. Gegenproben erfolgreich ausgefuehrt (die 2 zeigen Fehler); developer-E2E 14 Eingaben nur archiviert; 397/50 Vollsuite nur gemeldet; kein eigener Provider-Lauf.

---

## DECKBLATT · V65S · AMASTER-Kette: Körperkontakt als Angelegenheit, Zusatzprüfung entfernt, gebundene Erinnerung, vollständiger Figurenvertrag, schlanker Prompt, ein Speicherstempel — mit KORREKTUR der V65R-Einträge (Claude) · 30.10.2026

**Verbindlich:**
- `2_7master.txt`, Punkt für Punkt nach Abhängigkeit (Tabelle 1):
  - §3 Z. 80; §24.1/§24.2/§24.7 (Z. 1081–1254); §25 (Z. 1276–1320); §27.5 Z. 1413;
  - §35 Z. 1847; §36.2 (Z. 1911–1923); §36.5 (Z. 1945–1977);
  - §38–§41.5 (Z. 2037–2259); §46.2/§46.6 (Z. 2541–2596); §49 (Z. 2748–2800);
  - §50 (Z. 2805–2831); §63 Z. 3234; §68 Nr. 24, Nr. 45 (Z. 3394).
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6, §16.

**Eingang:**
- Gegenprüfung v3.1 (`MATRIX10_V65R_AMASTER_KONJUNKTIV_GESAMTPRUEFUNG_v3_1`); jeden Befund selbst nachgemessen, alle bestätigt;
- mein V65R-ZIP (MD5 `585f855a072184f6efaefbeef8efdb14`);
- deine Session `ses_a4b74af80af762ffbbcb7120`.

**Basis:**
- Code = V65R.
- Daten bytegleich zu deinem V65Q-ZIP (DB `9be11b84…`, sieben Logs).
- Keine Migration.

---

### 0 · KORREKTUR der V65R-Einträge

| V65R-Eintrag | Was dort steht | Was wirklich war | Erste falsche Naht | Jetzt |
|---|---|---|---|---|
| **R3** „Ablehnung als Einwilligungszustand“ | `sceneState.consent` hält die Ablehnung | **Zweiter Ort** für eine Angelegenheit (§68 Nr. 24; §36.5: Einwilligung an Proposition gebunden). Im V65R-E2E wurde nur 1 von 4 Ablehnungen Zustand | Antwort ohne `plan`: V65R-Läufe 7/13 und 2/13, V65S-Lauf 1 5/14. Ohne `plan` keine `refusal` | S1 + Schema (S4b). Ablehnung 3/3 gebunden (E2E) |
| **R5** „Aussage gegen eigenes Erleben“ | Claim + Widerspruch über drei Lesungen | **Symptomprüfung nach der Antwort**, 8 bzw. 11 Modellaufrufe je Lauf. Die Wurzel lag davor: Maras Brief enthielt ihre Erlebnisse nicht (Selektor 0/6 Turn-Gruppen, v3.1 §2) | `bind_formulation_spiegel` Wortauswahl | **Entfernt** (S4). Erlebtes wird gebunden vor der Antwort geliefert (S1, S3); Ausweichen/Lügen bleibt erlaubt (§50 Z. 2817) |
| V65R §3 Zeile 13 „BrainContext GRÜN“ | – | 57.791 Zeichen JSON-Anhang an Maras T32-Prompt, davon Zeugenliste 30.432 | `llm_contract._try_llm` `state_keys` | S5: 16.184 |
| V65R „Erinnerungsauswahl wortbasiert“ (Offen) | – | Bestätigt; nicht nur offen, sondern Ursache von R5 | `_relevance_score` | S3: gebundene Stufen zuerst; der Rest bleibt wortbasiert (OFFEN) |
| SQL (in V65R nicht geprüft) | – | No-op-Speichern 3.555 Anweisungen, 388 × `UPDATE sessions`, Zeugenliste doppelt in `sessions.json` | `repos._touch_session` je Kind; Envelope-Feld `witnessKnowledge` | S6 |
| V65R „Fünf Fassungen der Regie-Zeile“ | Inhalt ROT | Die Regiezeile spiegelte den Regietext als Figurenrede („wie angeordnet: „Sage alrik was du …““). Johann gab die Frage an Alrik zurück (V65R 6/6, V65S-Lauf 1 3/3) | `prepare` `_order` (§27.5 „Regie ist keine Figurenrede“) | S7: spricht als er selbst 3/3; Inhalt weiter ROT |

---

### 1 · AMASTER Punkt für Punkt

| AMASTER | verlangt | M10-Owner | IST V65R (gemessen) | V65S |
|---|---|---|---|---|
| §35 Z. 1847, §36.5 Z. 1947 | Einwilligung an Proposition/Handlung gebunden; unknown … declined | Proposition-Owner | eigener Speicher `sceneState.consent` | Angelegenheit „Körperkontakt“ X → Y im Proposition-Owner (`kernel._body_contact_matter` Z. 4236, `scene_state.body_contact_state` Z. 170) |
| §36.2 | Refusal nur vom berechtigten Empfänger, dieselbe Proposition | `apply_proposition` Z. 7659 | ohne `plan` nicht bindbar | bestehende Antwortbindung (Zeile, die sie beantwortet = die Tat); nur die Berührte entscheidet |
| §24.2, §50 Z. 2831 | strukturierter Plan; Prompt = Transport | `_try_llm` | `json_object`: Plan fehlt 5/9 (gleiche Anfragen) | strenges JSON-Schema (`FORMULATION_SCHEMA` Z. 1398, `_formulation_format` Z. 1428): 9/9, Läufe 0/14 und E2E 0/14 ohne Plan |
| §40, §41.3, §41.5 | Vordergrund aus gebundenen Zuständen; dieselben Beteiligten; alte Ablehnung relevant, wenn dieselbe Angelegenheit angesprochen | `bind_formulation_spiegel` | Wortreihenfolge, 0/6 Turn-Gruppen | Stufe 1: Angelegenheit des Reizes (`stimulus_bound_props` Z. 9400). Stufe 2: genannte Person (`stimulus_referents` Z. 9423). Danach wie bisher |
| §24.1, §24.7, §25 | Referent vor Recall binden; mehrdeutig bleibt unklar | Eingang | Plan nennt Johann nicht (v3.1 §2) | `bind_referents` Z. 3759 über Besetzungsnamen. Pronomen ungebunden (Planer-Lesung gemessen unzuverlässig, §3) |
| §41, §49 | Constraint vs. Vordergrund; nichts durch Aufnahme verstärken | Brief | – | `declined` = ABLEHNUNG-Zeile; `unknown` wird nicht als Angelegenheit serviert |
| §49, §39, §63 Z. 3234 | kompakter Spiegel, keine zweite Wahrheit | `_try_llm` Z. 1519 | JSON 57.791 | 16.184; Zeugenliste/Frames/Szenenzustand nur noch im Brief bzw. gar nicht |
| §63, §68 Nr. 24 | eine Lesung, nur betroffene Owner | `repos.save_session` | 3.555 Anweisungen, 388 × `UPDATE sessions` | 2.395, 1 × (`_SAVE_SCOPE` Z. 1483); `witnessKnowledge` nur Tabelle (Z. 4789) |
| §27.5 Z. 1413, §46.2 | Regie ist keine Figurenrede; Actor/Target gebunden | `regie_order_line` Z. 3644 | Regietext als Rede gespiegelt | Anweisung AN die Figur |
| §50 Z. 2817, §68 Nr. 45 | Lügen/Ausweichen erlaubt; private Wahrhaftigkeit getrennt | – | R5-Nachprüfung | entfernt; kein Antwortfilter |

---

### 2 · Gebaut

Vorhandene Owner. Keine Route, keine Tabelle, keine Wortliste, kein Antwortfilter, keine neue Modelllesung.

| ID | Was | M10 |
|---|---|---|
| S1 | **Körperkontakt-Angelegenheit:** Die erste Körpertat X → Y (`social`, `strike`, `restrain`) öffnet die Angelegenheit (Status `open`, kein Ziel). Jede Tat ist Evidenz. Ys Ablehnung ist Lifecycle → `declined`. Spätere Taten tragen `effect.consent = declined`. Die eigene Angelegenheit einer Tat (z. B. Antwort auf eine Bitte) bleibt unberührt. `sceneState.consent` ist entfernt | `kernel.py` Z. 4236; `scene_state.py` Z. 162–200, 464–467; `llm_contract.py` Z. 1151 |
| S3 | **Gebundene Auswahl** zuerst: (1) Angelegenheit des Reizes, nur was andere sagten/taten; (2) genannte Personen, zuerst Taten zwischen ihr und ihnen | `kernel.py` Z. 9384–9480, 9618 |
| S2n | **Referenten über Besetzungsnamen** im Eingang (`betrifft_ids` → `plan.about_ids`); Regiezeile über die Session-Besetzung | `kernel.py` Z. 3759, 9423–9460; `app.py` Z. 2783; `conjunctive.py` Z. 374 |
| S4 | **R5 entfernt** (`_erlebt_check_step`, drei ERLEBT-Verträge, `apply_erlebt_check`, `register_denial`, Leser `gegenErleben`) | `app.py` = V65Q + 3 Zeilen; `truth.py` = V65Q |
| S4b | **Figurenvertrag als strenges Schema** (OpenAI, Modelle gpt-4o/4.1/5/o3/o4); andere Provider unverändert `json_object` | `llm_contract.py` Z. 1384–1435, 1563 |
| S5 | **Provider-JSON** ohne Zeugenliste, Frames, Szenenzustand und Doppel-ID | `llm_contract.py` Z. 1515–1535 |
| S6 | **Ein Speicherstempel:** Besitzprüfung einmal, Hülle einmal; Zeugenliste nicht mehr im Envelope | `repos.py` Z. 1477–1495, 3062–3070, 4660–4680, 4789 |
| S7 | **Regiezeile als Anweisung an die Figur** | `kernel.py` Z. 3644, 9839 |
| S1b | `unknown` wird nicht als offene Angelegenheit serviert | `kernel.py` (open_matters) |

**Unberührt:** W3-C, NS2, SocialMatrix, KnowledgeGraph/AutoLearn, GodCommandParser, START_ANWEISUNG, Backstory, Profildaten, Frontend-Funktionen.

---

### 3 · Gemessen und NICHT gebaut (zurückgenommen)

| Versuch | Messung | Warum nicht |
|---|---|---|
| S2: Planer bindet `refers_to` an Angelegenheiten der Angesprochenen | 0/4 Körperkontakt-Fragen (alt wie neu), 1 Feld gekippt | wirkungslos |
| Planer-Feld `betrifft` + bezeugte Zeilen (Pronomen) | Fassung A: 12/12, aber 4/13 andere Felder verschoben, Zielbezug T3 verloren. Fassung B: 10/12, Kernfall „Hat er dich belästigt“ falsch | instabil (gpt-4o-mini) |
| Regie-Feld `taten_von` | Bindung 9/9 gleich, Kernfälle 0/3 | unzuverlässig |
| Regie-Inhalt = eigene Taten am genannten Opfer | 5/6 nennt Johann seine Taten | Ob eigene Taten gemeint sind, ginge deterministisch nur über das Wort „du“ (Wortregel); Clara-Fall („fragt Alrik, was er mit Mara besprochen hat“) würde falsch belegt |
| neutraler Rahmen (wer → wem) in der Regiezeile | 0/6 | wirkungslos |

---

### 4 · Messungen (ohne Modell)

| Was | V65R | V65S |
|---|---|---|
| Maras Prompt T32 (deine Session) | 72.781 Zeichen (JSON 57.791) | 31.174 (JSON 16.184) |
| Formulierungsprompts Routenlauf | max 44.588 / 45.425, Summe 416.326 / 430.244 (13) | max 26.275, Summe 308.733 (14) |
| No-op-Speichern deiner Session | 3.555 Anweisungen, 388 × `UPDATE sessions`, 2,19 s | 2.395, 1 ×, 0,86 s; gelesene Session vor = nach |
| `prepare_turn` jede gespeicherte Session | – | deine DB 15/15 Briefs bytegleich; Alt-DB 4/4; V65R-E2E-DB 15/16, Abweichung = die R3-Zeile aus `sceneState.consent` (nicht migriert) |
| volle Regression | 50 rot / 393 (deine DB), 32 / 411 (Alt-DB) | 50 / 397, 32 / 415 — 0 neu rot |

---

### 5 · Routenläufe und Browser-E2E (deine Sätze)

| Lauf | Antworten ohne `plan` | Ablehnung gebunden | Johann antwortet Alrik | Regie | Mara zu „er“ |
|---|---|---|---|---|---|
| Route 1 (vor Schema) | 5/14 | 0/5 | 2/2 | gebunden 3/3, Frage zurückgegeben 3/3 | erzählt 3/4 |
| Route 2 (Endstand) | 0/14 | 3/3 (T4, T6, T10), Taten danach `declined` | 2/2 | als er selbst 3/3, Inhalt 0/3 | weicht aus 4/4 |
| E2E 2 (ZIP vor S1b) | 0/14 | 3/3 | 2/2 | als er selbst 3/3, Inhalt 0/3 | erzählt 3/4 |
| **E2E final** (dieses ZIP, START.py, frisch entpackt) | 0/14 | **3/3**, Taten T5/T9 `declined` | **2/2** | als er selbst 3/3; Inhalt 1/3 („Sie wollte nicht, dass ich sie berühre, aber ich hab's trotzdem getan“), 1/3 Lüge, 1/3 ausweichend | weicht aus 4/4 |

- **Reload:** gleich.
- **Neustart:** Angelegenheit `declined` mit 3 Ablehnungen, Taten-Einwilligung gleich zurückgelesen.
- **Isolation:** 0 Altzeilen verändert außer `users/admin` (wie seit V65L).
- **Logs:** sieben alte bytegleich.
- **E2E 1:** abgebrochen durch Netzfehler (`ConnectionResetError`) bei Schritt 12; die Session blieb danach mit 409 blockiert (OFFEN).

---

### 6 · ROT / OFFEN

- **ROT – Regie-Inhalt:** Johann sagt nicht verlässlich, was er getan hat (E2E 1/3). Bindung und Perspektive stimmen.
- **Mara erzählt nicht verlässlich:** Ob sie erzählt, schwankt je Lauf (3/4, 0/4, 3/4, 0/4). Der Zustand steht jedes Mal vor der Antwort in ihrem Brief. Abweisender Ton gegen Alrik in 2 Läufen; Probe ohne ABLEHNUNG-Zeile gleich (8/8), also nicht von S1.
- **Pronomen** („er“) bleibt ungebunden.
- **Guard verwirft Pläne:** `normalize_plan` verwirft den Plan einer Antwort, die „er“ sagt, wenn der Plan „Johann Bruckner“ nennt (E2E 2/4 Antworten). Naht: `conjunctive.py` Z. 326–337.
- **Wortreihenfolge der Erinnerung,** wo nichts gebunden ist.
- **Keine Migration:** V65R-`sceneState.consent` wird nicht gelesen; Migration nur mit deiner Freigabe.
- **Netzfehler blockiert die Session:** Nach einem Netzfehler der Formulierung bleibt die Session blockiert (409).
- **Doppelte Angelegenheiten** „Mara möchte Alrik beruhigen“ (3×).
- **Oberfläche:**
  - Keine Anzeige von Ablehnung/Angelegenheiten.
  - React #418 im E2E (wie V65R).
- **Android:** nicht prüfbar.

---

### 7 · Modellaufrufe

| Wo | Aufrufe |
|---|---|
| **Produkt, deine 14 Eingaben:** V65R | 72 / 80 (davon R5 8 / 11) |
| **Produkt, deine 14 Eingaben:** V65S | 71 / 75 Routen, 76 / 76 E2E; keine R5-Lesung, Schema ohne Zusatzaufruf |
| **Meine Messungen dieser Runde:** Proben | 151 |
| **Meine Messungen dieser Runde:** Routenläufe | 146 |
| **Meine Messungen dieser Runde:** E2E (65 abgebrochen + 76 + 76) | 217 |

Gesamt 514, alle gpt-4o-mini über deinen Schlüssel.

---

## DECKBLATT · V65R · Regie-Redeauftrag gebunden, eine Sprecherwahl, Ablehnung als Zustand, Aussage gegen eigenes Erleben — mit KORREKTUR früherer Einträge (Claude) · 30.10.2026

**Verbindlich:**
- `2_7master.txt`:
  - §25 (Z. 1276–1320 Zielbindung), §27.5 (Z. 1409–1415), §46.2 (Z. 2541–2549), §46.6 (Z. 2591–2596);
  - §34.1 (Z. 1787), §36.3 (Z. 1937), §36.4 (Z. 1939–1943), §36.5 (Z. 1945–1977 Einwilligung);
  - §38 (Z. 2013–2054), §41–§41.3 (Z. 2148–2240), §50 (Z. 2805–2820), Z. 3357 (SceneFacts append-only).
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6, §16.

**Eingang:**
- Gegenprüfung v2.9;
- dein livegetestetes ZIP `MATRIX10_V65Q_AUSGANG_20261029.zip` (MD5 `dfe04001885a8d307348ccfcc6647b33`);
- deine Session `ses_a4b74af80af762ffbbcb7120` (T13–T32) mit Log `MATRIX10_LIVE_V65Q_2026-10-29_23-59-38.log`.

**Basis:**
- Code bytegleich zu meinem V65Q.
- Daten bytegleich zu deinem ZIP (DB `9be11b84…`, sieben Logs).

---

### 0 · KORREKTUR früherer Einträge dieses Blatts

**Grundsatz:** Eine grüne Teilprüfung ist kein Funktionsnachweis. Ein Test zählt nur für die Eingaben, die er enthält. Was ein früheres Deckblatt als „gebaut“ oder „9/9“ meldet, gilt nur für die dort genannten Fälle. Deine gescheiterten Eingaben waren in keinem dieser Tests.

Die alten Einträge bleiben als Chronik stehen. Diese Tabelle ist der Korrekturverweis.

| Früherer Eintrag | Was dort steht | Was wirklich war | Erste falsche Naht | Jetzt |
|---|---|---|---|---|
| **V65Q Q1** (Deckblatt V65Q, Tabelle 2 und §3 „Route mit deinen Fällen: 9/9 nach SOLL“, „Kernelbindung V65Q 33/34“) | Regie führt Rede nur aus, wenn sie angeordnet ist | **Regression durch mich.** Deine drei Zeilen T27–T29 („Sag die wahrheit, was hast du mit mara gemacht“, „Sage was du mit mara gemacht hast“, „Sage alrik was du mit mara gemacht hast“) wurden 3/3 als `rede_nicht_angeordnet` abgewiesen (Log Z. 523/535/547). Die 9 Fälle enthielten keinen solchen Befehl. Den einen Fehler („Sag ihm, er soll sich raushalten“: Lesung gab die ganze Zeile als `auftrag`) habe ich als „sichere Seite“ bewertet. Das war derselbe Fehler, und die Bewertung war falsch | `kernel._regie_speech_binding` V65Q (Z. 3700–3703): Rede nur, wenn `auftrag` ≠ ganze Zeile | ROT in V65Q; V65R R1 |
| **V65P** (dieselben drei Zeilen) | – | In der Gegenprüfung v2.9 als „V65P 3/3“ angenommen. Gemessen mit deinem UI-Ziel Johann: V65P 1/3 (nur „Sage alrik …“ gebunden; die anderen zwei `ziel_nicht_belegt`). 3/3 gilt nur mit UI-Ziel Alrik | `ist65r.json` | Hinweis |
| **V65E.4** („Sprecherwahl im Folgezug“) und **V53 FB08 Nr. 1** („Ein Name als Thema … ist nicht automatisch Gesprächspartner“) | Die Sprecherwahl richtet sich nach Ereignis, Anrede und UI-Ziel | Das galt nur für das Backend (`kernel.pick_speaker`). Der Browser hatte eine **zweite** Entscheidung: `pickSpeaker` gab die erste erwähnte anwesende Figur zurück, **vor** UI-Ziel und Anrede. Deine T25 (Alrik an Johann, Ziel Johann, „… zwischen dir und mara …“) → **Mara** antwortete (Log Z. 470–476). Probe: 3/6 falsch | `src/lib/matrix/session-engine.ts:297–299`, Chunk `shell-…-V65I.js` Funktion `Vi` | ROT bis V65Q; V65R R2 |
| **V65G** („171-Partnerbindung und Handlungsfreigabe übernommen“) | Beziehung gibt Handlungsfreigabe („ACTION-PERMISSION … geht Profil vor“) | Beziehung als Erlaubnis widerspricht §36.5 („Liebe ist keine Zustimmung“). Seit V65P entfernt; seitdem steht kein solcher Satz im Brief (V65Q-E2E: 0 Prompts) | – | Chronik; durch V65P ersetzt |
| **Fehlende Prüfungen** (in keinem Blatt als OFFEN geführt) | – | (a) Browser-Sprecherwahl gegen Backend; (b) Aussage einer Figur gegen das, was ihr selbst geschehen ist; (c) Einwilligung je Handlung. Deine T32 „Er hat mich nicht belästigt“ erzeugte keinen Claim und keinen Widerspruch (`truth.local_contradictions` prüft nur Behauptung gegen Behauptung). Deine Ablehnungen T17–T23 waren kein Zustand | `truth.py:90`; `kernel.py:2463` | V65R R2, R5, R3 |
| **Klasse „zaertlich“** (V65J/V65P, Wirkungsklassen) | – | Ein Griff an den Hintern (T16/T22) heißt intern `zaertlich` → `social`. Die Klasse setzt nur Berührung im Raum (`kernel.py:4120`), keine Vertrauens- oder Nähewerte. Eine Klasse „unerwünschte Berührung“ fehlt weiter | `llm_contract` Klassenliste | ROT (Klasse), Ablehnung jetzt über R3 |

**Deine gescheiterten Eingaben (IST V65Q, an deiner Session):**

| Turn | Eingabe | IST V65Q |
|---|---|---|
| T16/T18/T22 | Johann (Puppet): „Ich fasse dir auf den Arsch“, „Ich kneiff dir in deinen arsch“, „Ich streiche über deine schenkel …“ | T16/T22 `zaertlich`; Maras Ablehnungen T17–T23 ohne Zustand |
| T25 | Alrik an Johann (Ziel Johann): „Mich geht das sehr woll was an, sag mir was ging zwischen dir und mara ab !“ | Mara antwortet |
| T27–T29 | Regie an Johann: die drei Zeilen oben | „Regie nicht ausgeführt“ 3/3 |
| T32 | Mara: „… da war nichts. Er hat mich nicht belästigt, es ist alles okay.“ | kein Claim, kein Widerspruch; in ihrem Brief keine von Johanns Taten |

---

### 1 · Gebaut

Vorhandene Owner. Keine Route, keine Tabelle, keine Wortliste, kein Antwortfilter.

| ID | Was | M10 (Datei:Zeile) | AMASTER |
|---|---|---|---|
| R1 | **Regie-Redeauftrag:** `REGIE_RULES` liefert `redeverb` (wörtlich das Wort der Anweisung, mit dem der Figur Sagen/Fragen/Erzählen aufgetragen wird) und `adressat` (nur ein als Empfänger genannter Name) statt `auftrag`. Rede gilt bei Kurzform „Name:“, bei einem `redeverb`, das wörtlich in der Anweisung steht (`_words_in`, Beugung erlaubt), oder nach eigener angeordneter Tat. **Ziel:** genannter anwesender `adressat` → UI-Ziel ≠ Akteur → Ziel der Lesung, wenn außerhalb des Gesagten genannt → einzige andere anwesende Figur; sonst `ziel_nicht_belegt`. Abgewiesene Regie trägt kein Ziel mehr | `llm_contract.py:424`; `kernel.py:3671`, `:3685`, `:3739`, `:6014` | §27.5, §46.2, §46.6, §25 |
| R2 | **Eine Sprecherwahl:** `pickSpeaker` gibt die erste Erwähnung nicht mehr vorab zurück; `resolveAddress` entscheidet: Anrede → UI-Ziel → einzige Nennung (wie das Backend). Gleich in `src` und im ausgelieferten Chunk | `session-engine.ts:297`; `shell-gwW-WKpO-V65I.js` Funktion `Vi` | §25 Z. 1309–1320 |
| R3 | **Ablehnung als Einwilligungszustand:** Eine Ablehnung (Plan `refusal`/`refuse`) auf eine gültige Körpertat von X an ihr seit ihrer letzten eigenen Zeile setzt `sceneState.consent["Geberin|X"] = declined` (Ursache, Tat, Verlauf). Jede spätere Körpertat von X an ihr (`social`, `strike`, `restrain`) trägt am **neuen** Fakt `effect.consent = declined` mit Ursache, sonst `unknown`; nie `accepted` aus der Tat. Spiegel: ABLEHNUNG-Zeile für Geberin und Akteur („… Danach trotzdem: Turn 9 …“), Verlauf und Erinnerung „gegen deine Ablehnung seit Turn 6“, Erleben (`einwilligung`) | `scene_state.py:162`, `:185`, `:394`, `:440–464`; `kernel.py:4200–4263`, `:5160`, `:5406`, `:8133`, `:2648`, `:9204`, `:9595` | §36.5 |
| R5 | **Aussage gegen eigenes Erleben:** Hat die Sprecherin Körpertaten anderer an sich erlebt, liest `ERLEBT_CHECK_RULES` ihre Rede einmal dagegen. Nur für die genannten Taten folgen zwei Lesungen: Art (`bestreitet|verharmlost|bestaetigt|wehrt_ab|nichts`) und Stattfinden (`nicht_geschehen|geschehen|keine`). Behalten wird nur, was alle drei tragen, mit Fakt-ID aus ihrer Liste und wörtlichem Beleg; der Commit prüft das nochmal. **Writer:** Claim `gegen_eigenes_erleben` und neuer Fakt `contradiction` (`aussage_gegen_erleben`), nur ihr bekannt; nichts wird gelöscht. Hörer, die die Tat selbst gesehen haben, bemerken es über `truth.apply_contradictions`. **Spiegel:** „(gegen dein Erleben: Turn …)“ an ihrer Zeile | `llm_contract.py:622`, `:635`, `:649`, `:663`; `app.py:2518`; `kernel.py:4265–4310`, `:5416–5426`, `:9194`; `truth.py:241` | §34.1 Z. 1787, §36.3, §36.4, §50, Z. 3357 |
| R6 | **Erinnerung mit Beteiligten:** Erlebtes aus dem Puppet-Pfad nennt den Täter („Johann Bruckner: Ich fasse dir …“), auch für vorhandene Daten; Hinweis „gegen deine Ablehnung …“ | `kernel.py:9574–9615` | §38 |

**Unberührt:** W3-C, NS2, SocialMatrix, KnowledgeGraph/AutoLearn, GodCommandParser, START_ANWEISUNG, Backstory, Profildaten.

**Nicht gebaut (gemessen und verworfen):**
- **R4 Klasse „beruehrung“ statt „zaertlich“:** Kneifen, Hals packen und „zur Mauer drücken“ rutschten von `gewalt` nach `beruehrung` (6/6), Festhalten 2/2; gesamt 28/40 gegen 30/40 bisher.
- **Regie-Zeile im Brief umformuliert** (5 Fassungen) und Schlusssatz „zuerst die Regie-Anweisung ausführen“: keine Fassung brachte Johann dazu, den Auftrag auszuführen; der Schlusssatz verdoppelte das Echo. Zahlen in §2.

---

### 2 · Gemessen

**Bedingungen:** gpt-4o-mini, deine Config 0,7; Lesungen T=0; frische Kopien deiner DB.

| Kette | IST V65Q | V65R | Beleg |
|---|---|---|---|
| Regie-Bindung deiner 3 Zeilen (Route, UI-Ziel Johann) | 0/3 | **Johann → Alrik 3/3** (2 Routenläufe 6/6, Proben 12/12) | `R_session_1/2`, `Z2/Z3` |
| Regie-Bindung, 33 Fälle × 2 (deine, P-08, Fragen, 3. Person) | – | 65/66; Fehler: „Was hast du mit Mara gemacht?“ mit UI-Ziel Johann 1× als Rede gebunden | `regie65r_2_bind_V65R.json` |
| **Regie-Ausführung** (sagt Johann Alrik, was er mit Mara gemacht hat?) | – | **ROT.** In deinem Zustand (Alrik hat Johann zweimal gefragt): eingebaute Zeile **1/42** erzählt (eine Lüge: „Ich habe nichts mit ihr gemacht“), 33/42 verweigert („Was geht dich das an“), 8/42 wiederholt den Auftrag oder fragt Alrik (Routenläufe 6/6). Ohne Alriks zwei Fragen davor: 7/9 erzählt (teils verzerrt), 2/9 Echo | `routenlauf/`, `regiezeile/Z–Z4` |
| Regie-Zeile anders gefasst (nicht gebaut) | – | B1/B2 „wer mit du gemeint ist“: 6/9 je (A 7/9). C Schlusssatz: 0/12 erzählt, 3 Echo; B1C 0/12, 4 Echo. D/D2 „DASS es geschieht, steht fest“: 0/24. E Vertragsregel (9) „Was eine REGIE-ANWEISUNG anordnet, geschieht“: 0/12. Gegenprobe ohne Regie unter E: unauffällig 3/3 | `regiezeile/` |
| Clara fragt Alrik (V65P-Fall) | – | fragt 3/3. Zweimal lieferte die Lesung `ziel` „Alrik“ statt „Priester Alrik“ → `ziel_nicht_anwesend_oder_unbekannt`. Ursache `_match_figure` (nur ganzer Name oder erster Namensteil). Gebaut: ein späterer ganzer Namensteil bindet, wenn genau eine Figur ihn hat (`kernel.py:187`); Bindung der 66 Lesungen unverändert 65/66 | `Z_regiezeile`, `Z3/Z4`, Test |
| Sprecherwahl, 6 Fälle (src) | 3/6 | 6/6 | `speaker_ist/soll_src.json` |
| Einwilligung (Routenlauf 2: Mara lehnt ab) | kein Zustand | `declined` seit Turn 6; Tat Turn 9 `consent=declined`; ABLEHNUNG-Zeile bei Mara und Johann; Erinnerung „gegen deine Ablehnung seit Turn 6“ | `R_session_2.json` |
| Einwilligung (Routenlauf 1: Mara flirtet mit) | – | bleibt `unknown`, kein `accepted` aus der Tat | `R_session_1.json` |
| Aussage gegen Erleben, 19 Fälle × 3 (eingebaute Kette) | 0 erkannt | **50/51**; 1 Fehler: „Johann ist nicht der, für den du ihn hältst“ 1× als Bestreiten (mehrdeutig) | `erlebt_kette_1.json` |
| dasselbe, nur zwei Lesungen (erster Einbau, verworfen) | – | 33/36; Ablehnung „Du kannst nicht einfach so rumfummeln!“ 2/2 als Bestreiten | `erlebt_art_1.json` |

**Modellaufrufe dieser Runde (gezählt):** 1397 (1325 bis vor dem E2E, E2E 72).
- Vertragsproben: Regie 198, Klassen 120, Erlebt 156 + 82 + 145 + 119.
- Routenläufe: 72 + 80.
- Regiezeilen-Proben: 99 + 82 + 84 + 88.
- E2E 72: Erleben 16, Formulierung 13, Eingang 10, Sprache 8, Erlebt-Prüfung 7, Körperprüfung 5, Raum 3, Regie 3, Ziel-Lesungen 7.
- **Im Betrieb neu:** je Figurenzug mit erlebten Taten +1 Lesung; +2, wenn die erste Lesung eine Tat nennt. Routenlauf 2 hatte 7 Mara-Züge, davon 4 mit Nennung.

**Bytevergleich `prepare_turn`** (alle gespeicherten Sessions, ohne Modell):
- Deine DB, 17 Sessions: 1 Session verschieden (`ses_57d5…`), 5 Erinnerungszeilen mit Täter (R6).
- Alt-DB, 5 Sessions: 0.
- V65Q-E2E-DB, 18 Sessions: 2 verschieden, 11 Zeilen, alle R6.
- 0 unerwartet.

**Regression** (volle Tests, Code V65Q gegen V65R, je deine DB und Alt-DB): **0 neu rot.** Deine DB 50 failed / 393 passed (V65Q 50/378), Alt-DB 32/411 (V65Q 32/396); die 50 und 32 sind dieselben wie in V65Q. `test_v65r_kette` 15/15.

**E2E** (frisches ZIP MD5 `70973f82…`, `START.py`, Chromium, Session `ses_e3285fb16d9d352efe60a636`, 72 Modellaufrufe; Nachweis `V65R_E2E_NACHWEIS_20261030`):
- **Sprecherwahl:** Alrik an Johann (Direktes Ziel Johann, Mara anwesend, „… zwischen dir und mara …“) → Johann antwortet 2/2. V65Q: Mara.
- **Regie:** 3/3 ausgeführt, Johann → Alrik, kein „Regie nicht ausgeführt“. Rede-Fakten tragen `regieOrder` (Sag/sage/Sage). Inhalt: Johann verweigert 3/3 („Was ich mit Mara gemacht habe, geht dich nichts an“) – ROT, §3.
- **Einwilligung:** `declined` seit Turn 10, Ursache Maras Ablehnung nach Turn 9 („Ich streiche über deine schenkel“). ABLEHNUNG-Zeile in 5/5 Johann-Briefen und 3/3 Mara-Briefen danach.
  - Maras frühere Ablehnungen setzten keinen Zustand: T4 wurde als Frage gelesen, T6 als Bitte, T8 folgte keiner neuen Tat (OFFEN, §3).
  - Danach tat Johann nichts mehr an ihr. „Danach trotzdem“ ist deshalb nur im Routenlauf 2 belegt.
- **Aussage gegen Erleben:** 7 Prüfungen, 0 Bestreiten. Mara sagte die Wahrheit („Er hat mich berührt, und ich wollte das nicht“), also kein Widerspruch. Das ist richtig. Ein Bestreiten kam im E2E nicht vor; belegt ist es durch Routenlauf 2 und die Probe.
- **Erinnerung:** Maras Brief nennt „[erlebt] Johann Bruckner: …“ für Turn 3, 5 und 9.
- **Reload:** Zustand gleich. **Neustart:** Einwilligung, Widersprüche und Claims gleich zurückgelesen.
- **Isolation:** 0 Altzeilen verändert außer `users/admin` (wie seit V65L). Die sieben alten Logs sind bytegleich; ein neues Log `MATRIX10_LIVE_V65R_…`.
- **Frisches ZIP:** pytest auf einer Kopie 50 failed / 393 passed, dieselben 50 wie V65Q; Sprecherprobe am frischen `src` 6/6.
- **React-Fehler #418** wie seit V65E.

---

### 3 · ROT / OFFEN

- **ROT – Regie-Ausführung:** Die Regie bindet Sprecher und Empfänger, den **Inhalt** der angeordneten Rede bindet niemand.
  - Der Auftrag erreicht Johann nur als zitierte Zeile im Brief.
  - Kein Owner prüft, ob seine Antwort tut, was angeordnet ist (§27.5 „bindend zu vollziehende Szenenwirkung“).
  - In deinem Zustand entscheidet sein Profil: verweigern.
  - Fünf Zeilenfassungen und eine Vertragsregel änderten nichts: in deinem Zustand 0/60. Im Zustand ohne Alriks Fragen B1/B2 je 6/9 gegen 7/9 mit der eingebauten Zeile.
  - **Nächster Schritt, nicht gebaut:** eine Vollzugsprüfung der angeordneten Rede (erfüllt / verweigert / umgedreht, wörtlicher Beleg) am Regie-Fakt. Bei „nicht erfüllt“ bleibt der Auftrag offen und wird sichtbar gemeldet. Dafür braucht es eine Anzeige und eine Messung, ob ein offener Auftrag den nächsten Zug ändert. Eine Lüge über die eigene Tat zählt als ausgeführt (§50).
- **ROT – Klasse:** „zaertlich“ bleibt das interne Etikett einer unerwünschten Berührung. Die Unerwünschtheit trägt jetzt die Einwilligung (R3), nicht die Klasse.
- **OFFEN – Einwilligung:**
  - Gebaut ist nur `declined` aus einer Ablehnung. `offered`, `accepted`, `revoked` und `expired` sind nicht gebaut.
  - Eine Ablehnung, die der Plan nicht als `refusal` liest, setzt keinen Zustand. Im E2E: „Was soll das, Johann? Du kannst nicht einfach so…“ als Frage, „… so mit mir umgehen!“ als Bitte.
  - Eine Ablehnung ohne neue Tat seit ihrer letzten Zeile setzt keinen Zustand (E2E T8).
  - Eine Annäherung mit Körperkontakt (`approach`, z. B. „drücke Mara an mich“) trägt keine Einwilligung.
- **OFFEN – Erinnerungsauswahl:** wortbasiert (`_relevance_score`). In Johanns Brief fehlte Turn 9 („Ich streiche über deine schenkel“) unter „DU ERINNERST DICH“.
- **OFFEN – Wiederholung:** Routenlauf 1, Schritte 11/12: Maras Rede wörtlich gleich, obwohl „Nicht wiederholen“ im Brief stand.
- **OFFEN – Ortswechsel durch Puppet/Regie:** `commit_puppet` und Regie-`_apply_physical` laufen ohne Welt; der Ort ändert sich nicht.
- **OFFEN – zwei Taten in einer Antwort**, Oberfläche (Einwilligung/Widerspruch nicht sichtbar, kein Frontend-Build), **Android NICHT_PRÜFBAR**.

---

## DECKBLATT · V65Q · Regie-Redeauftrag, Versuch und Ausgang, Mauer als Position, Folgen dauerhaft, Erledigung nur durch Antwort (Claude) · 29.10.2026

> **Korrektur V65R (30.10.2026):** siehe Deckblatt V65R, §0. Q1 hat deine Befehle „Sage … was du mit mara gemacht hast“ abgewiesen (Regression); „9/9 nach SOLL“ galt nur für die 9 Testfälle.

**Verbindlich:**
- `2_7master.txt`:
  - §20 (Z. 926 Körperpositionen, Z. 947, **Z. 953**);
  - §24.7 (Z. 1252), §25 (Z. 1309–1316), §27.5 (Z. 1415), §28 Schritt 32 (**Z. 1496**);
  - §34 (Z. 1767), §34.1 (Z. 1807–1817), §34.3 (Z. 1831);
  - §42 (Z. 2305, **Z. 2315–2316**), §43, §43.1 (**Z. 2393–2402**), §43.2 (Z. 2420/2436);
  - §46.2 (Z. 2547), §46.6 (Z. 2596), FOUNDATION H (Z. 3742–3752).
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6, §16.

**Eingang:** Gegenprüfung v2.8 (P-01 bis P-09) und deine vier Punkte vom 29.10.
- Regie spricht die falsche Figur an oder führt eine Frage falsch aus.
- Gegenwehr wird nicht erkannt.
- Folgen gehen verloren.
- Eine Frage gilt als beantwortet, obwohl niemand geantwortet hat.

**Basis:** V65P. Code wie ausgeliefert, Daten bytegleich zu deinem letzten Rücklauf (DB `2797b22f…`, sechs Logs).

### 1 · IST (am unveränderten V65P reproduziert, `ist65q_test.py`, 0 Modellaufrufe)

| v2.8 | IST | Erste falsche Naht |
|---|---|---|
| P-01 | Der Puppet hebt nur ein Glas, oder er spricht zu Tom → Tammys Frage gilt als „beantwortet“ | `scene_state.update_from_commit`: jeder Commit des Beat-Besitzers |
| P-02 | Stoß an die Mauer, danach Rückzug → `completed`, Raum „auf Abstand“ | Kein Positionszustand; `_movement_blocked_reason` kennt nur den Körper |
| P-03 | Ihr Versuch, sich wegzudrücken → kein Ausgang am Fakt | Die Prüfung kennt nur bestätigt oder nicht |
| P-04 | Überwundener Rückzug, dann Ortswechsel → Ausgang weg | Ausgang nur in der aktuellen Raumzeile |
| P-05 | Der Versuch ist „letzte körperliche Handlung“ ohne Kennzeichnung | `record_physical` |
| P-06 | „Abstand schaffen“ gilt durch „Lass das!“ als erledigt | `apply_appraisals`: jede eigene Zeile zählt |
| P-07 | „Clara sagt Alrik, dass Mara …“, Lesung Ziel Mara → Rede an Mara | `bind_regie_components`: Ziel gilt, wenn es irgendwo genannt ist |
| P-08 | „Ist die Tür offen oder verschlossen?“ → Claras Rede | Kein Redeauftrag geprüft |

### 2 · Gebaut

Vorhandene Owner. Keine Route, keine Tabelle, keine Wortliste, keine Verhaltensregel, kein Antwortfilter. Drei Lesungen bekommen ein strukturiertes Feld; je Feld gibt es einen Writer und einen Leser im Kernel.

| ID | Was | M10 (Datei:Zeile) | AMASTER |
|---|---|---|---|
| Q1 | **Regie-Redeauftrag:** `REGIE_RULES` liefert `auftrag`. Rede gilt nur, wenn einer dieser Wege zutrifft: Kurzform „Name: …“; `auftrag` steht wörtlich in der Anweisung und ist nicht die ganze Zeile; oder die Rede setzt eine angeordnete Tat derselben Figur fort. Angesprochen ist, wer im Auftrag genannt ist (bei mehreren der erste Satzteil), sonst wer außerhalb des Gesagten genannt ist, sonst das Direkte Ziel. Eine nur im Inhalt erwähnte Person ist nie Ziel | `llm_contract.py:424`; `kernel.py:3668` `_regie_speech_binding`, `:3721` | §27.5, §46.2, §46.6, §25, §24.7 |
| Q2 | **Angeordnete Rede im Commit:** Ziel = angeordnetes Ziel, `causeFactId` = Regie-Fakt, `regieOrder` | `kernel.py:3632` `regie_order_for`, `:5240` | §46.6, §34 Z. 1767 |
| Q3 | **Beat nur durch Antwort:** Rede an die Fragende; bei Bitte oder Vorschlag auch eine gültige Tat an sie | `scene_state.py:269` | §20 Z. 953, §28 Z. 1496 |
| Q4 | **Versuch:** Die Körperprüfung trägt `versuch` (inline; alte Fälle unverändert). Eine nicht bestätigte Bewegung bekommt eine Folgelesung `MOVE_ATTEMPT_RULES`; der bestätigende Raumtext bleibt bytegleich. `outcome=attempted` + `attemptedKind` am Fakt. Der letzte Beat trägt den Ausgang („Versuch, ohne Wirkung“) | `llm_contract.py:512`, `:552`; `kernel.py:3235`, `:3275`, `:3299`; `scene_state.py:239`, `:355`; `app.py:2496`, `:2549` | §43.1, §42, §20 Z. 953 |
| Q5 | **Mauer als Position:** Die Körperprüfung trägt `gegen` (wörtlich in der Handlung). Ein bestätigter Angriff oder Festhalten schreibt `sceneState.positions[ziel]`. Solange der Drückende in Berührung ist, sind Rückzug, Annäherung an Dritte und Ortswechsel der Gedrückten `blocked` (`gedrueckt_gegen`). Die Position endet bei Abstand, Ortswechsel oder Befreien. Der Ortswechsel prüft jetzt dieselbe Capability. Eine Annäherung an jemanden in Berührung bleibt Berührung. Spiegel: KÖRPERPOSITION für beide | `kernel.py:4018`, `:4042`, `:4063`, `:4115`, `:4145`, `:4154`; `scene_state.py:128–147`, `:124`, `:184`, `:388` | §43, §43.1, §43.2, §20 Z. 926/947, FOUNDATION H |
| Q6 | **Ausgang dauerhaft:** Wer einen Rückzug überwindet, trägt `effect.overcomes` am eigenen Fakt (neue Evidenz); der Rückzugs-Fakt bleibt bytegleich (Z. 3357 append-only). Ein Leser: `overcome_for_fact` liest zuerst den späteren Fakt, dann die Raumzeile (V65P-Daten). Ihn nutzen `act_outcome` (auch nach einem Ortswechsel), der Verlauf und die Erinnerungen an eigene Taten („— Ausgang: …“) | `scene_state.py:114`, `:162`; `kernel.py:4169`, `:9017`, `:9418`; `llm_contract.py:1166` | §34 Z. 1767, §34.1 Z. 1817, §34.3 Z. 1831, Z. 3357 |
| Q7 | **Absicht an ihre Tat gebunden:** Meldet das Erleben „erledigt“, liest `INTENT_KIND_RULES` einmal aus dem Absichtstext, ob Rede oder Handlung. Für eine Handlung braucht es eine eigene Tat mit Wirkungsklasse und ohne Fehlschlag, für Rede eine eigene Rede | `llm_contract.py:594`; `app.py:2641`; `kernel.py:2838`, `:3067` | §42 Z. 2305, Z. 2315–2316 |

**Unberührt:** W3-C, NS2, SocialMatrix, KnowledgeGraph/AutoLearn, GodCommandParser, START_ANWEISUNG, Backstory, Profildaten, Frontend außer Buildname.

### 3 · Gemessen

**Messbedingungen:**
- gpt-4o-mini, deine Config 0,7;
- frische Kopien deiner Rücklauf-DB;
- breite Läufe und Regie auf dem eingefrorenen Code (SHA in `code_frozen.sha256`).

**Vorab-Proben der Verträge (T=0):**
- **Körperprüfung mit `versuch`/`gegen`:**
  - alte Fälle 41/42 (V65J: 41/42 je Lauf);
  - neue Fälle: Versuch 23/24, Fläche 24/24.
- **Raumprüfung:**
  - Mit dem Feld `versuch` im selben Text wuchsen die falsch negativen Fälle von 5/40 auf 9/40. Deshalb bleibt der Text unverändert, und `versuch` kommt aus einer Folgelesung (24/24).
- **Verworfen nach Messung:**
  - eine eigene Lesung „Ausgang“ (Versuch falsch positiv 22/40);
  - eine Absichtsprüfung, die die Tat selbst wählt (4/24 falsch, „Lass das!“ für „Abstand schaffen“).
- **`INTENT_KIND_RULES`:**
  - räumliche oder körperliche Absichten 18/18 als Handlung;
  - 4/30 falsch, alle zur sicheren Seite (eine Rede-Absicht wird nicht erledigt).

**Regie:**
- **Kernelbindung auf echten Lesungen** (17 Fälle × 2): V65Q 33/34, V65P 26/34.
  - Die 8 Fehler von V65P sind Zeilen ohne Auftrag, die als Rede ausgeführt wurden.
  - Der V65Q-Fehler ist „Sag ihm, er soll sich raushalten“, 1×: die Lesung gab die ganze Zeile als Auftrag.
- **Route mit deinen Fällen:** 9/9 nach SOLL.
- **„Clara fragt Alrik …“:** 10/10 gefragt.

**Deine 9 Johann-Sätze (Puppet), je 3 Läufe:**

| | V65L | V65P | V65Q |
|---|---|---|---|
| Rückzug mit Wirkung **nach** dem Stoß an die Mauer | 2, 2 | 1, 1, 2 | **0, 0, 0** |
| Raum nach T8/T9 | Abstand | gemischt | **Berührung (3/3)** |
| Maras Versuche nach der Mauer | – | ohne Ausgang | blockiert 2+2, versucht 2 |
| KÖRPERPOSITION im Brief T8/T9 | – | – | 3/3 |
| Erinnerung „— Ausgang: … wieder erreicht“ ab T7 | – | – | 3/3 |
| Johanns Absicht „Abstand“ | 8/9, 7/9 | 0/9 ×3 | 0/9 ×3 |

**Bytevergleich `prepare_turn`:**
- Deine DB (16 Sessions) und die Alt-DB (5): **0 Abweichungen**.
- V65P-E2E-DB: nur die Session mit überwundenen Rückzügen. Dort neu: Ausgang im Verlauf und in der Erinnerung (Q6).

**Breite Läufe (eingefrorener Code), Aufrufe V65P → V65Q:**
- Fremder 30/31 → 32/32, Bedienperson 37 → 39, Gasthaus-13 86 → 85, Tom/Tam 66 → 69, Kinder 22 → 22.
- Verhalten wie V65P:
  - Kinder-Robert 0/12;
  - Gasthaus-13 sagt es Alrik;
  - der Fremde wird erwidert (offen).

**Gegenproben v2.8** (dein Skript, offline, 0 Aufrufe), am Endstand:
- falsche Zielfigur angenommen: nein; ungeordnete Rede angenommen: nein; fremde Tat beantwortet die Frage: nein;
- Überwindung nach Ortswechsel sichtbar: im Skript wie geliefert **nein**. Dort ist Johanns Tat `j2` kein Fakt. Im echten Pfad steht der Fakt immer vor `set_spatial` in `session.facts` (alle fünf Aufrufstellen von `_apply_physical`). Mit `j2` als Fakt: V65Q **ja**, V65P nein; der Rückzugs-Fakt bleibt bytegleich (`gegenprobe3_mit_fakt.py`).

**Regression:** 0 neu rot auf beiden DBs (deine DB 50/378, Alt-DB 32/396; V65P 50/353 und 32/371). `test_v65q_ausgang` 25/25.

### 4 · Offen
- **Gegenwehr mit zwei Taten in einer Antwort** („drücke ihn weg und mache einen Schritt zurück“): Die Figurenantwort trägt nur **eine** Wirkungsklasse. Der Rückzug wird blockiert, das Wegdrücken nicht als Tat an Johann gewertet.
- **Klaps ohne Klasse:** Für eine unerwünschte, nicht verletzende Berührung gibt es keine Klasse.
- **Regie:**
  - Körperwirkung („dir ist schlecht“) und Mauer per Regie (Regie-Taten haben keine Körperprüfung): nicht gebaut.
  - „Clara stößt Mara. Ist die Tür offen?“ würde als Claras Rede gelesen (Rede nach eigener Tat).
- **Fremder:** Verhalten wie V65P. Der Fall, dass ein Rahmenstatus der Rede widerspricht (v2.8 §6), ist nicht kausal geprüft.
- **Oberfläche:** Position, Versuch und Ausgang sind nicht sichtbar (kein Frontend-Build).
- **Android:** NICHT_PRÜFBAR.

---

## DECKBLATT · V65P · Zustand, Versuch und Ausgang verbunden; falsche Verhaltensvorschriften entfernt (Claude) · 29.10.2026

**Verbindlich:**
- `2_7master.txt`:
  - §15 (Z. 707ff): Kompass bestimmt Rückzugs-/Eskalationsneigung, ersetzt keinen Zustand;
  - §27.3–§27.5 (Z. 1376–1415), §28 Schritte 12–14 (Z. 1459ff);
  - §36.5 (Z. 1945–1977): Zustimmung an Handlung/Proposition gebunden; „Liebe ist keine Zustimmung“;
  - §41.3 (Z. 2204), §42 (Z. 2262–2320): Disposition → Affekt → Intent → Versuch → vollzogene Handlung → Folgen;
  - §43 (Z. 2351–2389): Capability wirkt beim Commit; §43.1 (Z. 2391–2416) Outcome; §43.2 (Z. 2418–2433); §44; §46.2/§46.6;
  - FOUNDATION H (Z. 3742).
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6.1–§6.8 und §16.

**Basis:** dein V65L-Rücklauf, ZIP MD5 `66e05e6e…`, SHA256 `6a872640…`. Der Code darin ist bytegleich zum ausgelieferten V65L.

**Daten:** DB `2797b22f…` und alle sechs Logdateien sind bytegleich.

**Eingang:** Prüfung v2.7 und deine Vorgabe vom 29.10.: „Die falschen Verhaltensvorgaben entfernen und die vorhandene Zustands- und Handlungskette korrekt verbinden. Keine neuen Promptregeln und keine nachträglichen Antwortfilter.“ Die Pläne V65M und V65N sind korrigiert in `scripts/v65p_zustandskette/V65P_PLAN_KORRIGIERT_20261029.md`. V65M P2 (Antwort nachprüfen und neu formulieren) ist gestrichen.

### 1 · Erste falsche Nähte (am unveränderten V65L reproduziert, `ist65p.py`, 0 Modellaufrufe)

| # | IST | Stelle |
|---|---|---|
| 1 | Puppet-Stoß Johann→Mara: Eskalation 0,00, letzter Beat bleibt Maras Rückzug, Raum „auf Abstand“ | `commit_puppet` schreibt keinen SceneState |
| 2 | Stoß und Festhalten setzen keine Raumrelation; der Brief sagt nach „Ich drück dich zur mauer“ „ihr seid auf Abstand“ | `_apply_physical` |
| 3 | Eine festgehaltene Figur (`restrained`, Mobilität 0,2) weicht „erfolgreich“ zurück | `_apply_physical` withdraw ohne Capability |
| 4 | Ein Rückzug, den das Gegenüber wieder überwindet, verschwindet aus dem Zustand | `scene_state.set_spatial` ersetzt die Zeile |
| 5 | Zustimmung aus dem Beziehungstyp: Mara→Alrik (`lover`) `intimateActionAccepted: true` → „intime Nähe getragen … DARF mit Nähe/Lust bewertet werden“ | `action_permission_frame`, Erleben-Klausel |
| 6 | Kompass gekürzt (Erleben 110, Linse 220 Zeichen); Mara verliert „Vermeidet: sich in die Enge treiben zu lassen · Eskaliert wenn: Druck oder Gewalt zunimmt“ | `appraisal_payload`, Linse |
| 7 | Regie-Rede erreicht die Figur als Nacherzählung: „Sprich zu Priester Alrik …: Was hast du mit Mara besprochen?“; Clara beantwortet die Frage selbst | `prepare` directive |

### 2 · Gebaut (vorhandene Owner; keine Route, keine Tabelle, kein neuer Speicher, keine Wortliste, keine Verhaltensregel, kein Antwortfilter)

| ID | Was | M10 (Datei:Zeile) | AMASTER |
|---|---|---|---|
| V65P.A1 | Die 171-Klauseln `APPRAISAL_AP_ACCEPTED/NOT` vor dem Erleben entfernt | `llm_contract.py:741`, `appraise_events` | §15, §36.5, §42 |
| V65P.A2 | Erleben: `handlungsfreigabe` entfernt; Beziehung zum Handelnden nur als Werte | `kernel.py:2670–2690` | §36.5, §44 |
| V65P.A3–A6 | Brief: beide ACTION-PERMISSION-Zeilen, die Verhaltenssätze der Beziehungszeile, das Verbot zu leugnen (PARTNERBINDUNG bleibt als Zustand) und die Fix4-Zeile entfernt | `llm_contract.py:882ff`, `:1202` | §15, §36.5, Z. 324 |
| V65P.A7 | Regel (2): Reaktionsliste und „darfst … ohne Bedingung erwidern“ entfernt, sonst wortgleich | `llm_contract.py:1293` | §15, §36.5 |
| V65P.B1/B2 | `intimateActionAccepted` entfällt; die Linse liest `allows_intimate_room` (Leserauswahl, keine Zustimmung, gleiche Werte) | `kernel.py:2483`, `:9421` | §36.5, §41.3 |
| V65P.B3/B4 | Erleben: dieselbe Linsenauswahl wie der Brief; die Bindung an eine andere Person als Zustand (`bestehende_bindung`) | `kernel.py:2688–2703` | §41.3, §44 |
| V65P.C1 | `commit_puppet` schreibt den SceneState wie die Eingangsphase von `commit_turn` | `kernel.py:7710–7735` | §27.4, §28 |
| V65P.C2 | Stoß und Festhalten setzen „in Berührung“ | `kernel.py:3782`, `:3806` | §43.1, §43.2 |
| V65P.C3 | Rückzug/Annäherung gegen die vorhandene Capability aufgelöst (fixiert, Mobilität < 0,3, Bewusstsein < 0,5); unmöglich → Ausgang `blocked` am Fakt, Raum bleibt | `kernel.py:3871`, `_movement_blocked_reason` `:3896` | §43, §43.1 |
| V65P.C3b | Die zwei Bewegungsklassen gehen durch dieselbe Prüfung vor dem Writer wie die Körperklassen (`MOVE_CHECK_RULES`, Klassendefinitionen wortgleich aus PLAN_RULES; `EFFECT_CHECK_RULES` unverändert) | `kernel.py:3183`, `llm_contract.py:532` | §24.2, §43.1 |
| V65P.C4 | Überwundener Rückzug bleibt am Paar (aus den Fakten, auch für alte Zeilen) | `scene_state.py:62`, `:110` | §42, §43.1, §43.2 |
| V65P.C5 | Spiegel: RAUM-Zeile nennt überwundene Rückzüge; ein blockierter Versuch steht im Verlauf an der Handlung | `scene_state.py:300`, `kernel.py:8723`, `llm_contract.py:1200` | §43.1, §41.5 |
| V65P.C6 | Erleben: `zuletzt_selbst.ausgang` | `kernel.py:2707`, `act_outcome` `:3912` | §42 |
| V65P.C7 | Absicht erledigt nur durch eine eigene Tat mit Wirkung und nicht durch eine leere Zeile | `kernel.py:3013–3030` | §42, §43.1 |
| V65P.C8 | Kompass ungekürzt (Erleben-Eingangsgrenze 12 000 → 24 000, damit nichts abgeschnitten wird) | `kernel.py:2729`, `:9432`, `llm_contract.py:775` | §15 |
| V65P.D1 | Regie: Akteur und Ziel müssen in der Anweisung genannt sein (auch mit einem Namensteil oder Sitzungsnamen), das Ziel darf auch das gewählte „Direkte Ziel“ sein. Sonst ist es unklar | `bind_regie_components` `kernel.py:3536`, `_named_by_name_part` `:3517` | §46.2, §23, §25, §24.7 |
| V65P.D2 | Regie ordnet keine Avatar-Rede an | `kernel.py:3592` | §27.3 |
| V65P.D3 | Körperklasse ohne Zielperson: Klasse unklar, Handlung ausgeführt | `kernel.py:3615` | §24.7, §43.1 |
| V65P.D4 | Angeordnete Rede wörtlich (geprüftes Segment) statt Nacherzählung | `kernel.py:9241` | §46.2, §46.6 |
| V65P.9 | `_locate_segment`: Spanne nach „ß“ (casefold verlängert) auf die Quelle zurückgerechnet; Treffer unverändert | `kernel.py:3383` | §24.2 |

**Unberührt:** W3-C, NS2, SocialMatrix, KnowledgeGraph/AutoLearn, GodCommandParser, START_ANWEISUNG, Backstory, Profildaten, `relationship_policy.json`, Frontend außer dem Buildnamen.

### 3 · Gemessen (gpt-4o-mini, deine Config 0,7, echte Routen, frische Kopien deiner Rücklauf-DB)

**Vorwärts/Rückwärts ohne Modell** (`vergleich_prepare.py`/`vergleich_diff.py`, jede gespeicherte Session, Spiegel + Brief + Erleben-Nutzlast):
- deine DB 16 Sessions, Alt-DB 5;
- jede Abweichung ist einer geplanten Änderung zugeordnet (A2–A4, B3, B4, C8);
- **unerwartet: 0**.

**Deine 9 Johann-Eingaben (Puppet), Mara antwortet** (L = V65L, P = V65P):

| | L (2 Läufe) | P (3 Läufe) |
|---|---|---|
| Johanns Absicht „Abstand“ | 8/9, 7/9 | **0/9, 0/9, 0/9** |
| Eskalation nach „Ich drück dich zur mauer“ | 0,00 | **0,25** |
| überwundene Rückzüge im Zustand (T9) | 0 | **2–3** |
| Maras Rückzug als Klasse | 9/9, 9/9 | 3/9, 3/9, 9/9 |
| Maras Handlung wortgleich wiederholt | 4, 4 | 0, 0, 1 |
| ACTION-PERMISSION im Brief | ja | nein |

**Regie** (dieselben UI-Bindungen):

| Fall | L | P |
|---|---|---|
| „ich gebe dir einen Stoß“, Ziel = Clara | Stoß an Alrik | unklar (`ziel_nicht_belegt`); bei Lesung ohne Ziel: Tat ohne Körperwirkung |
| „Was hast du mit mara gesprochen ?“ | Claras Rede an Alrik | unklar |
| „Mara dir ist schlecht“ | Avatar-Rede, stumm | unklar (`akteur_nicht_belegt`), Hinweis sichtbar |
| „Clara schliesst die tür und versperrt sie“ | Klasse `restrain` ohne Ziel | Tat ohne Körperklasse |
| „Clara fragt Alrik, was er mit Mara besprochen hat“ | 0/5 gefragt | **10/10 gefragt** |
| „Mara gibt Alrik einen Kuss auf die Wange“ | Tat an Alrik | Tat an Alrik |

**Raumprüfung vorab** (`move_probe.py`, T=0, 2 Läufe): falsch positiv 0/20 (gegen die Mauer drücken, Arme verschränken, Wunsch, angekündigt, verneint, Versuch an der Mauer), falsch negativ 1/18.

**Breite Läufe, Aufrufe L → P:** Fremder 29 → 30/31, Bedienperson 35 → 37, Gasthaus-13 81 → 86, Tom/Tam 53 → 66, Kinder-Robert 21 → 22. Neu sind nur Raumprüfungen.

**Verhalten breit:**
- Gasthaus-13: Kuss mit Alrik erwidert; „Hast du einen Freund?“ → „Ja, … Priester Alrik“.
- Kinder-Robert: 0/12 verrät es (wie L).
- Bedienperson: weist ab, 7/7, ohne Rückzugsschleife (L: 8/8 „ziehe mich weiter zurück“).
- **Fremder Robert mit Alrik anwesend: L wehrt 2/2 ab, P erwidert 2/2.**
  - Am exakten Request gemessen: Nur die entfernte ACTION-PERMISSION-Zeile bewirkte die Abwehr (5/5).
  - Ohne sie: 0/5. Ebenso mit dem V65G-Beziehungssatz und ohne „hypersexuell“ im Profil.
  - Der Zustand ist vollständig gespiegelt.

### 4 · Offen
- **Mauer als Hindernis:**
  - Braucht einen Objekt-/Raumzustand (§43.2, FOUNDATION H) und ein Lesefeld für das Hindernis.
  - Nicht gebaut, weil das Lesefeld eine Promptänderung wäre.
  - Ein echter Rückzug nach dem Stoß wird weiter als möglich gespeichert.
- **Regie „Rede nur, wenn angeordnet“ (V65M P1b)** und **Regie-Körperwirkung** („dir ist schlecht“): brauchen je ein Lesefeld. Nicht gebaut. „Ist die tür offen …?“ und „Blau ist die Zeit des Wassers.“ laufen weiter als Claras Rede.
- **Fremder:** Mara entscheidet aus ihrem Profil (Abschnitt 3). Eine Regel dafür setze ich nicht zurück.
- **Teil-Unklar bei Regie** (ausgeführte Tat plus unklare Klasse) zeigt die Oberfläche nicht; nur im Log.
- Android: NICHT_PRÜFBAR. Kein neuer Vite-Build.

---

## DECKBLATT · V65L · Antwortbezug im Folgeturn an den vorhandenen Fakt- und Ziel-Referenzen (Claude) · 29.10.2026

**Verbindlich:**
- `2_7master.txt`:
  - §25 (Z. 1311–1321): Zielbindung „letzten Sprecher, adressierte Frage … bestehende Turnbindung“;
  - §34 (Z. 1765): Antwortbezug;
  - §34.1 (Z. 1787, 1798): Folgeturn als Fortsetzung des gebundenen Zustands, `responds_to` je Komponente;
  - §41.1 (Z. 2190), §68 Nr. 35 (Z. 3384);
  - Z. 326 und §68 Nr. 67 (Z. 3416): keine Sprechpflicht;
  - §68 Nr. 85.
- `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §6.1–§6.8 und §16.

**Basis:** dein V65K-Rücklauf, ZIP MD5 `35057650…`, SHA256 `0fb086a9…`. Der Code darin ist bytegleich zum ausgelieferten V65K.

**Daten:** DB `4829fb4a…` und alle vier Logdateien sind bytegleich.

**Verfahren:**
- Plan nach §6.1–§6.5: `scripts/v65l_antwortbezug/SPS_V65L_PLAN.md`, mit Basis, Inputregister, Kettenkarte, Reproduktion, 171 und erster falscher Naht.
- Dessen Patchvorschlag (§8) wurde nach der Prüfung vom 29.10. verworfen: falsche Herkunft, falsche Fortsetzung, Zusatzaufruf ohne Nachweis.
- Der V65L-Arbeitsstand vom 28.10. (Entscheidung aus dem Erleben) ist ebenfalls verworfen. Er ersetzte die V65H-Zeile und legte einen zweiten Absichtsspeicher an.

### 1 · Erste falsche Naht (am unveränderten V65K reproduziert)

- **Kein Defekt:** Mara muss es in T2 nicht sagen (Z. 326). Gemessen sagt sie es in etwa zwei Dritteln der Antworten (12/18).
- **Der Defekt liegt im Folgeturn.** Alrik antwortet auf **ihre** Zeile eines Gesprächswechsels, der schon an ihr ungesagtes Ziel gebunden ist: „Ja, das wäre schön“ oder „Was denn, schatz?“.
  - Die Themenbezug-Lesung (`app._goal_theme_step`) liest nur seinen Satz und bindet nicht: 4/4.
  - Folge: Sie sagt es in T3 0/20.
  - Bei „Ja, das wäre schön“ stand das Ziel nur als „Hintergrund-Antrieb“ im Brief, weil der Planer den Satz an das Ziel band. Bei „Was denn, schatz?“ fehlte es ganz.
- **171 mit deinen Sätzen:** T2 1/6, T3 0/5. Das Ziel stand dort jeden Turn als Hintergrund-Text im Prompt; getragen hat nur die Themenbindung in T2.
- **Den Antwortbezug gab es schon:**
  - `_stimulus_prop_ids` (V63) bestimmt strukturell, auf welche Zeile jemand antwortet.
  - Ihre Antwortzeilen tragen dieselbe `sourceTurnId` wie seine gebundene Eingabe.
  - Für diesen Fall wurde beides nicht genutzt.

### 2 · Gebaut (vorhandene Owner, keine Route, keine Tabelle, kein neuer Speicher, keine Wortliste)

| ID | Was | M10 (Datei:Zeile) | AMASTER |
|---|---|---|---|
| V65L.1 | Der V63-Antwortleser wird unverändert als `_answered_line_facts` herausgelöst; `_stimulus_prop_ids` nutzt ihn. Gleichheit bewiesen: Test vergleicht mit dem V65K-Rumpf auf jeder gespeicherten Session, jedem Fakt, jedem Akteur | `kernel.py:7009`, `7041` | §25, §34, §41.1 |
| V65L.2 | **Struktur entscheidet den Kandidaten:** Die Zeile, auf die seine Eingabe antwortet, ist **ihre** Zeile **an ihn**. Ihr Wechsel (gleiche `sourceTurnId`) enthält seinen Fakt, der schon an dieses noch ungesagte Ziel gebunden ist (Themenbezug oder Antwortbezug). Sonst: kein Kandidat, keine Lesung | `kernel.answer_continuation` `kernel.py:4194` | §25, §34.1, §68 Nr. 35 |
| V65L.3 | **Eine Lesung, nur im Kandidatenfall und nur, wenn die unveränderte Lesung seines Satzes nicht gebunden hat.** Gefragt wird nur: Antwortet er auf den Themen-Teil ihrer Zeile (Zustimmung, Ablehnung, Rückfrage, Aufforderung)? Beide Wendungen wörtlich | `llm_contract.ANSWER_REFERENCE_RULES` / `answer_reference_check` (Z. 647, 659); `app._goal_theme_step` (Z. 2567–2581) | §24.2, §24.8 DISCOURSE_ACT |
| V65L.4 | **Kernel prüft und bindet mit beiden Ereignis-IDs:** Kandidat unter der Schreibsperre neu abgeleitet, dieselbe Zeile, erlaubte Art, beide Belege wörtlich (seiner in seinem Fakt, ihrer in ihrem). Dann Ziel-Erfahrung an **seinem** Fakt mit `via: "antwortbezug"`, `antwortAuf` = ihr Fakt, `fortsetzungVon` = sein gebundener Fakt des vorigen Wechsels, `art`, `beleg`, `belegIhreZeile`. Die T2-Evidenz bleibt unverändert | `kernel.apply_answer_reference` (Z. 4218), `apply_goal_experience` (zusätzliche Provenienzfelder) | §34 Antwortbezug, §34.2 Kausalprovenienz, §6.2 fail-closed |
| V65L.5 | **Leser:** Vordergrund (`touchedNow`) und Offenbarungsprüfung akzeptieren `antwortbezug` wie `themenbezug`. Der Brief ist **unverändert** (V65H-Zeilen wörtlich). Die Herkunft steht nur im Spiegel (`touchedNow.via/antwortAuf/fortsetzungVon`) | `kernel.py:4019`, `8654` | §41.3 Leser, §49 Spiegel |
| V65L.6 | Live-Log `GOAL_THEME` je Ziel: erste Lesung und `lesung: "antwortbezug"` mit `ihreZeile`, Status, Modellantwort | `app.py:2594–2597` | §65, §68 Nr. 70 |

**Bytegleich zu V65K:**
- Erleben (Vertrag, Nutzlast, Writer), `render_persona_brief`, Vordergrund-Auswahl;
- Offenbarungsprüfung und Commit, Planer, Formulierungsvertrag, `scene_state`;
- Frontend außer dem Buildnamen.

**Unberührt:** W3-C, NS2, SocialMatrix, KnowledgeGraph/AutoLearn, GodCommandParser, START_ANWEISUNG, Backstory.

### 3 · Gemessen (gpt-4o-mini, deine Config 0,7, echte Routen, frische Kopien deiner Rücklauf-DB)

**Bytegleichheit des Bestehenden:**
- `prepare_turn` liefert Spiegel und Brief bytegleich zu V65K, für jede gespeicherte Session:
  - deine DB 12/12 und Alt-DB 4/4;
  - 18 Mess-DBs aus V65K-Läufen mit je 13 Sessions, darunter T2/T3-Zustände mit Themenbezug: 0 Unterschiede.

**Antwortbezug-Lesung** (Probe, Vertragstext = eingebauter Text, T=0, 16 Fälle × 3):
- falsch positiv 0/24: Liebeserklärung, Tag, Abend, Kuss, Hunger, Umarmung, Antwort auf ihre andere Frage;
- falsch negativ 3/21: „Nein, ich glaube, noch nicht“ wird als eigener Inhalt gelesen. Ergebnis: keine Bindung, Verhalten wie V65K.

**Folgeturn** (T2-Antwort fest ohne Offenbarung, dann dein Satz):

| T3 | V65K | **V65L** |
|---|---|---|
| „Ja, das wäre schön“ | 0/10 | **6/6** (Antwortbezug Zustimmung) |
| „Was denn, schatz?“ nach ihrer Andeutung | 0/10 | **6/6** (Rückfrage) |
| „Ich liebe dich“ nach ihrer Kinder-Zeile | – | nicht gebunden, kein ANTWORTGRUNDLAGE, 0/2 |
| „Wie war dein Tag heute?“ | – | nicht gebunden, 0/2 |
| „Ich liebe dich auch“ nach ihrer Andeutung | – | nicht gebunden, 0/2 |

**Kette mit echter Formulierung T2 → T4** (6 Sitzungen):
- In T2 gesagt: 5/6.
- Die sechste Sitzung: T3 gebunden, Mara sagte es trotzdem nicht (sie ist frei). T4 „Was machen wir heute Abend?“ wurde als eigener Inhalt gelesen, nicht gebunden; kein Zwang zum Thema.

**Breite Läufe, Modellaufrufe V65K → V65L:**
- Gasthaus-13: 81 → 81 (×2); Fremder: 29 → 29; Bedienperson: 35 → 35.
- Tom/Tam: 53 → 59. Die +6 sind Regelprüfungen; sie hängen am Inhalt des Eingangsplans, Antwortbezug-Lesungen: 0.
- Robert fragt nach Kindern: 0/12 Proben verraten es (wie V65K).
- Antwortbezug-Lesungen in allen breiten Läufen: 0. Kosten entstehen nur im Fortsetzungsfall: +1 je solchem Turn.

**Tests:**
- `test_v65l_antwortbezug.py` 6/6;
- Gesamtsuite siehe Bericht V65L, §16 Zeile 19.

### 4 · Offen

- **Kettenvertrag §5 / §16 Zeile 17: ROT seit V65H.** Rahmen, Themenbezug, Antwortbezug und Offenbarungsstand sind in keiner Oberfläche sichtbar, nur im Live-Log und als Lebenszyklus-Fakt in der Timeline. Ändern lässt sich das nur mit einem neuen Frontend-Build.
- **Weitere Nähte aus Prüfung v2.3, je gemessen ohne Wirkung auf diesen Defekt:**
  - Frage-Komponente in deinem T2-Satz geht verloren (Plan §6);
  - das Erleben übersieht das gebundene Ziel;
  - Beat „answered“ durch bloßes Sprechen;
  - `zaertlich` → Berührung ohne Vollzugsprüfung.
- **Falsch negativ** bei Ablehnung („Nein, … noch nicht“): keine Fortsetzung, wie V65K.
- **Andeutung in einem nicht gebundenen Wechsel** (T3 „Wie war dein Tag?“, sie deutet an, T4 „Was denn?“): kein Kandidat, weil der Wechsel nicht gebunden ist.
- Android: Erleben-Timeout T1 (Log Z. 21), NICHT_PRÜFBAR. Kein neuer Vite-Build.

---

## DECKBLATT · V65K · Sessionsprache: Namen und Wortbedeutungen automatisch lernen und selbst nutzen, ohne Freigabe (Claude) · 28.10.2026

**Verbindliche Quelle:** `2_7master.txt`
- §24.1 (Z. 1081: `known_as` = „Name oder Bezeichnung in einem bestimmten Scope“; keine Zusammenführung von IDs)
- §24.3 (Z. 1145: Domänen `ALIAS`, `VOCABULARY`, `SPEECH_PROFILE`; keine eigene Tabelle nötig)
- §24.6 (Z. 1216: Parserwortschatz geschichtet System/Welt/Charakter/**Session**; „darf seine lokale Bedeutung nicht still in andere Welten oder Sessions übertragen“; „Lexikon oder Keyword allein darf niemals direkt einen kanonischen Writer auslösen“; Figurenwortschatz gehört zum Stamm)
- §24.7 (Z. 1248), §26 (Wissen nur über Zeugen), §14 (Z. 701–703), §52 (Z. 2875: „Sessionerfahrung darf nicht automatisch dauerhafte Charakteridentität werden … oder nur sessionbezogen belassen“), G11/G17, §68 Nr. 85 (Z. 3434: Prompt-Präsenz verstärkt nichts)

**Eingang:** `MATRIX10_V65J_WORTLISTE_ISTKARTE_v1_0.md` (externe IST-Karte) und deren Erwiderung („Freigabe ist keine Voraussetzung für normales Lernen“). Wegweiser; jede Aussage hier am Code und live gegengeprüft. 171 (`Download171 ned schlecht`) als Vergleich gelesen.
**Basis:** ausgeliefertes V65J (MD5 `d5caabf2…`). Seither kein neuer Rücklauf.
**Daten:** DB `083e432f…` und alle drei Logdateien bytegleich.

### 1 · Gegenprüfung der IST-Karte und der Erwiderung

| Aussage | Gegenprüfung | Beleg |
|---|---|---|
| Alter SmartVocab-Lerner fehlt in V65J | **stimmt**. In 171 vorhanden (`smart_vocabulary_learner.py`, sessiongebunden seit SI-2A-1), lernt aus der **eigenen Antwort** der Figur; das Gelernte geht in `render_frames[0].vocabulary_ids`, der tatsächliche Antwortweg (`_llm_fallback_response`, „LLM spricht direkt“) liest es nicht. | 171 `chat_orchestrator.py` Z. 20547–20575, 20910–21260 |
| Lernfunktionen ohne produktiven Aufrufer | **stimmt** (`local_learning`, `extract_learning`, `learn_into_character`). Seit V52 bewusst: V41 schrieb Lieblingswörter/Wendungen/Ziele aus der **eigenen Modellrede** in den Stamm → Tammy-Schleife (V52: fünf Turns, eine Frage; V60B: „Klarheit“ 8/8 mit, 0/8 ohne diese Felder). | V52-Befund, V60-Bericht 9b |
| „Gelernte Wörter werden nicht nachweisbar wiederverwendet“ | **nur halb**. Gemessen auf V65J: Die Figur benutzt Gelerntes in der Session automatisch und ohne Freigabe (Käpt'n, Gerstensaft, Plörre 2/2 Läufe, auch nach 10 Füllturns im Brief). Das **System** nutzt es nicht: Regie „Mara gibt dem Käpt'n einen Kuss“ → unklar (Ziel unbekannt), Puppet „Käpt'n, du schuldest mir …“ → an Mara gebunden. | `scripts/v65k_sprache/ist*`, `lern2_J1` |
| Freigabeseite verwaltet alte Lernwerte | **stimmt**: 45 Einträge, 3 Figuren, 0 freigegeben; **44 aus der eigenen Modellrede** („Aber ich“, „Von dir“, „Glaubst“, „Zärtlich“), 1 „Mik über Lina“. Sie freizugeben brächte die gemessene Schleife zurück. Die Seite sagt schon: „Ohne Freigabe wirkt es nicht in neuen Sitzungen“ – die Freigabe ist nur die Stammübernahme. | DB-Kopie, `charakter.$charId.tsx` Z. 617–660 |
| Erwiderung: normales Lernen ohne Freigabe | **stimmt** (§52 „nur sessionbezogen belassen“, §24.6 Sessionwortschatz). | – |
| Erwiderung: „Sprachstil einer Figur: wiederkehrende Ausdrücke automatisch lernen und bei späteren Antworten berücksichtigen“ | **nicht übernommen**: Aus der eigenen Ausgabe gelernt ist das genau der gemessene Schleifen-Mechanismus (V41→V52); §68 Nr. 85 verbietet Verstärkung durch Prompt-Präsenz. | V52, V60B |
| Erwiderung: dauerhafte Stammänderung nur bewusst | **stimmt** (§14, §52, G11/G17); unverändert (Charakterseite „Dauerhaft übernehmen“). | – |

**Wurzel (IST V65J):** Eine Festlegung wie „nenn mich ab jetzt Käpt'n“ oder „zu Bier sagt man hier Gerstensaft“ war nur Episode (Erinnerung, Verlauf, teils als „Behauptung … nicht bestätigt“). Die AMASTER-Domänen `ALIAS`/`known_as` und der Sessionwortschatz (§24.1/§24.3/§24.6) hatten weder Lesung noch Owner noch Leser. Deshalb kannte nur das Sprachmodell den Namen, nicht die Bindung (Ziel, Regie, Puppet, Sprecherwahl).

### 2 · Gebaut (vorhandene Owner, keine Route, keine Tabelle, keine Wortliste)

| ID | Was | M10-Owner | AMASTER |
|---|---|---|---|
| V65K.1 | **Eigene Sprachlesung je Eingang** (Avatar, Bedienperson, Puppet): Name für eine Person (`art name`) oder Bedeutung eines Worts (`art bedeutung`) mit `status` festgelegt/verneint/zitiert/erwogen/anrede, wörtlichem Beleg und Bezeichnung. Semantische Vorstufe: eine reine Handlung ohne Rede wird nicht gelesen. | `llm_contract.LANGUAGE_RULES`/`language_reading`; `app._read_language` (Eingang, Puppet); Live-Log `SPRACHE` | §24.1, §24.3, §24.6 |
| V65K.2 | **Kernel prüft und bindet:** nur `festgelegt`; Beleg wörtlich in der Äußerung, Bezeichnung im Beleg; Beleg nicht in Anführungszeichen (Zitat); Person = ich/du/bekannte Figur; Bezeichnung weder ihr eigener Name noch der einer anderen Figur; Bedeutung wörtlich und nicht zirkulär. Ergebnis mit Grund am Rede-Fakt (`sprache`). | `kernel.bind_language`; `commit_turn` (Eingang), `commit_puppet(language=…)` | §24.7, §34.1 |
| V65K.3 | **Selbst nutzen, nur in dieser Session:** Namen werden als `sessionAliases` in die Figurenprojektion gelegt (wie `canonical_stem`, Lesesicht). Zielbindung, Regie-/Eingangskomponenten, Sprecherwahl und Gate kennen sie; eine Bezeichnung, die zwei Figuren beanspruchen, bindet keine. Neue Session: nichts davon. Stamm: unverändert. | `kernel.session_language`, `with_session_aliases`; `_match_figure`, `_name_roles`, Sprecherwahl; `app._sql_natives`, `_kernel_world_and_natives` | §24.1, §24.6, §52, G11 |
| V65K.4 | **Brief nur für Zeugen:** „SPRACHE HIER (in dieser Session festgelegt; du hast es gehört oder selbst gesagt)“ mit Name/Bedeutung, wer, Turn. Zustandsspiegel, kein Auftrag. Ein Rahmen aus denselben Fakten wird nicht doppelt gezeigt. | `bind_formulation_spiegel` (`sprache`), `render_persona_brief` | §26, §49, §68 Nr. 85 |
| V65K.5 | **Puppet-Lesungen vor der Schreibsperre:** Planer (seit V62), Wirkungsprüfung (V65J) und jetzt Sprachlesung liefen innerhalb `BEGIN IMMEDIATE`. Jetzt davor, wie Regie (V59C). | `app.kernel_puppet` | V54/V59C-Regel |

**Gemessen und verworfen:** Sprachfeld im großen Eingangsplaner: 20/32, Positivfälle fehlten, andere Lesungen verschoben sich. Eigene Lesung ohne `status`: Verneinung/Zitat/Überlegung als Festlegung gelesen; ohne `anrede`: Kosenamen als Namen.

**Bewusst nicht gebaut:** Stil aus der eigenen Ausgabe (Schleife, §68 Nr. 85); automatische Stammübernahme (§52); Lernen aus Figurenantworten (Kosten je Figurenturn; OFFEN).

### 3 · Messung

- **Lesung + Kernelprüfung** (Text = eingebauter Text, 2 Läufe, Temperatur 0): 16/16 Festlegungen gebunden; 0 von 73 Negativfällen gebunden (16 gebaute: Verneinung, Zitat, Frage, Überlegung, Kosename; 57 echte Eingaben aus deiner DB).
- **Echte Routen, gpt-4o-mini, deine Config** (V65J 1 Lauf, V65K 2 Läufe): Regie „Mara gibt dem Käpt'n einen Kuss auf die Wange.“ V65J unklar → V65K ausgeführt an Alrik 2/2; Puppet Clara „Käpt'n, du schuldest mir noch drei Taler!“ V65J an Mara → V65K an Alrik 2/2; Mara nutzt „Käpt'n“/„Gerstensaft“ in beiden Ständen.
- **Browser (V65K, Kopie):** Avatar lehrt „Käpt'n“ → gebunden; Puppet → an Alrik; Regie → ausgeführt an Alrik, kein „Regie nicht ausgeführt“; Live-Log `SPRACHE`.
- **Breite Läufe, Modellaufrufe** (V65J → V65K, alle anderen Zwecke gleich): Gasthaus-13 69 → 81 (×2), Fremder 24 → 29, Bedienperson 29 → 35, Tom/Tam 44 → 54, Kinder 25 → 30 (3 Sprachlesungen, 2 inhaltsabhängig). Gebundene Sprachfestlegungen in diesen Läufen: 0 (keine dieser Eingaben legt einen Namen fest). Erster Gasthaus-Lauf band einmal „Bedienen“ = „hier zum Bedienen“ → Prüfung „zirkulär“ ergänzt, neu gemessen: 0 (×2).
- **Tests:** `test_v65k_sprache.py` 10/10; Gesamtsuite 0 neu rot.

### 4 · Offen

- Sprach-Tabu („sag nie wieder Plörre“) ist keine Namens-/Bedeutungsfestlegung; es bleibt Bitte/Erinnerung (ein Lauf: Mara sagte es trotzdem). Gehört zu `SPEECH_PROFILE`.
- Namen, die eine Figur in ihrer Antwort festlegt, werden nicht gelesen (eine Lesung je Figurenturn).
- Bezeichnung mit Artikel („den Grobian“) bleibt so gespeichert, wenn das Modell den Artikel mitliefert.
- Nach Puppet-Rede wählt der Browser die antwortende Figur nach dem UI-Ziel, nicht nach der Serverbindung (V35, unverändert).
- Kosten: +1 Aufruf je Eingang mit Rede.
- Android: NICHT_PRÜFBAR. Kein neuer Vite-Build.

---

## DECKBLATT · V65J · Prüfbericht v2.2 gegengeprüft: ein Wirkungsweg für Puppet, Avatar, Figur und God; unklare Regie; Auslieferung nach Inhalt (Claude) · 28.10.2026

**Verbindliche Quelle:** `2_7master.txt`
- §24.2 Semantic Effect Planner (Z. 1100: Kandidat → Semantikanalyse → EffectPlan mit Zeitbezug/Target → Validierung → Writer)
- §24.6 (Z. 1216: „Lexikon oder Keyword allein darf niemals direkt einen kanonischen Writer auslösen“)
- §24.7 (Z. 1248: Unklares nur als sichtbarer Ambiguitätsstatus)
- §27.4 Puppet (Z. 1401), §43.1 Action- und Outcome-Resolver (Z. 2391: „Handlungstext allein beweist noch keinen erfolgreichen Vollzug“ – attempted/failed/completed)
- §46.1 God (Z. 2525), §46.2 Regie (Z. 2541), §46.6 „Gemeinsamer Parser, unterschiedliche Writerrechte“ (Z. 2591)
- §38 Memory, §48, §65

**Eingang:** externer Prüfbericht `MATRIX10_V65I_171_SPS_AMASTER_TIEFENPRUEFUNG_v2_2.md` und Nachweise v2_2 (beide ZIPs identisch, MD5 `a7fcd4ff…`). Der Bericht ist Wegweiser; jede Aussage wurde hier am Code und mit eigenen Läufen gegengeprüft.
**Basis:** ausgeliefertes V65I (ZIP MD5 `f98f5b5d…`). Seither kein neuer Rücklauf; deine Daten darin = dein V65H-Rücklauf.
**Daten:** DB `083e432f…` und alle drei Logdateien bytegleich.

### 1 · Gegenprüfung der Befunde v2.2

| Befund v2.2 | Gegenprüfung (eigener Lauf) | Wurzel (IST) |
|---|---|---|
| Puppet „schlägt Mara nicht“ / „wird später schlagen“ = Schlag | **bestätigt** für den Kernel-Aufruf mit gebundenem Ziel. Über die echte Route (V65I-Client) schlug **kein** Fall zu, auch kein echter Schlag (P3/P6/P7: kein Ziel gebunden), und verneinte/angekündigte Sätze wurden als Handlung gespeichert. | Route plante nur die Rede; die Handlung kam aus der Verb-Liste des Clients (`splitPuppet`), ihre Körperwirkung aus `_STRIKE_RE`, ihr Ziel nur zufällig aus dem Rede-Plan. Keine Erinnerung an die eigene Tat. |
| Unklare Regie → erzwungener Figurenzug | **bestätigt**: `directiveFor` blieb bei leerem `executed`/`speech`; der Client fiel auf die angewiesene Figur zurück (`directiveFor ‖ regieActorId`). Live: „Johann schlägt Robert.“ (Robert abwesend) → Johann erzwungen. | `apply_regie` setzte `directiveFor` vor der Bindung und nahm es nicht zurück; Client prüfte nur „nur Taten“. |
| God „kann kaum gehen“ ohne Beweglichkeit | **bestätigt**, zusätzlich „Mara ist nicht verletzt.“ → Schmerz 0,4, „gefesselt“ → Schmerz +0,15. | Körper-Scope liest nur Wortlisten. |
| Wirkungsprüfung prüft nur Zitat | **bestätigt**: keine Zeit, kein Ziel. Eine falsch bestätigende Modellantwort wäre durchgegangen. | Prüfung war ohne Zeitbezug/Target (§24.2). |
| Cache: gleicher Zeitstempel → 304 | **bestätigt** mit `START.py`. | Prüfung nach Änderungszeit. |
| Gate nicht im Log | **bestätigt**. | – |
| „FEHLT: Nichts“ zu stark | **angenommen**: gemeint war „alle nötigen Unterlagen gelesen“, nicht „alles gelöst“; die offenen Punkte standen im Bericht. | – |

### 2 · Gebaut (vorhandene Owner, keine neue Route, keine neue Tabelle)

| ID | Was | M10-Owner | AMASTER |
|---|---|---|---|
| V65J.1 | **Puppet = derselbe Eingangsweg wie Avatar.** Der Client schickt den Rohtext. Die Route liest ihn mit dem Eingangsplaner. `bind_input_components` und die Marker-Regel aus `commit_turn` entscheiden, was Rede und was Handlung ist. Eine Körperwirkung entsteht nur aus einer bestätigten Klasse, nie aus einem Wort. Ohne Lesung: Handlung ohne geratene Wirkung. Tat → Erinnerung „getan“ (Täter), „erlebt“ (Betroffene), „gesehen“ (Zeugen). | `app.kernel_puppet`; `kernel.bind_puppet_input`, `commit_puppet(actions=…)`; `kernel-bridge.kernelPuppet` (`text`) = Bundle `index-5` | §27.4, §23, §24.2, §24.6, §38 |
| V65J.2 | **Eine Wirkungsprüfung für jede eigene Handlung** (Figurenantwort, Avatar, Puppet). Gilt, wenn gewalt/fesseln/befreien vorgeschlagen ist. Die Lesung bekommt die Äußerung als Zusammenhang und liefert `zeit` und `ziel`. Der Kernel verlangt: bestätigt, Beleg wörtlich in der Handlung, `zeit = jetzt`, gleiches Ziel. Sonst keine Körperwirkung; Grund steht am Fakt. | `llm_contract.EFFECT_CHECK_RULES`/`effect_check`; `kernel.apply_effect_check`, `component_effect_checks`, `apply_component_effect_checks`; `app._check_component_effects` (Eingang, Puppet), `_effect_check_step` (Figur) | §24.2, §43.1, §46.6 |
| V65J.3 | **Unklare Regie führt nichts aus.** `directiveFor` nur für angeordnete Rede. Eine Lesung ohne bindbare Tat oder Rede bewirkt: keine Delegation, kein Wort-Körper-Writer, keine Szenennotiz, Regie-Fakt `validated=false` (`regie_unklar`). Client: kein Figurenzug, Hinweis „Regie nicht ausgeführt: … Nichts ist geschehen“. Ohne Provider bleibt der alte Weg (V46). | `kernel.apply_regie`; `chat.$sessionId.tsx` = Bundle `index-5` | §24.7, §46.2, §46.6 |
| V65J.4 | **God-Körpertatsache → typisierter Zustand.** Eine kleine Lesung je Körpertatsache liefert Schmerz, Beweglichkeit, Bewusstsein, gefesselt und geknebelt, mit wörtlichem Beleg. Der Kernel setzt die Werte (Skala der vorhandenen Writer) und schreibt einen `body_state`-Fakt. Wortlisten und `apply_body_directive` laufen dann nicht. Unlesbare Lesung → nur Tatsache, keine Zahlen, Hinweis „unklar“. Ohne Provider bleibt der lokale Weg (V43/V34). | `llm_contract.GOD_BODY_RULES`/`god_body_state`; `kernel.god_body_values`, `apply_god(body_state=…)`; `app.kernel_god` | §46.1, §43, §24.2, §24.6 |
| V65J.5 | **Assets nach Inhalt.** ETag = SHA-256 des Inhalts; `If-None-Match` gleich → 304, sonst die Datei. `If-Modified-Since` wird für `/assets/` nicht mehr benutzt. | `START.py` `_serve_asset` | §65 |
| V65J.6 | **Gate im Live-Log:** `AUTOCHAT_GATE` mit Sprecher, Kandidaten, Gründen und Stopp. | `app.kernel_autochat_gate` | §65, §48 |

**Nicht übernommen (gemessen, wirkungslos):** ein Zusatzsatz im Eingangsplaner zu Vollzug/Zitat (Variante B 42/48 = A 42/48). Ebenso der Körperzustand als Feld im großen God-Vertrag (14/20). Stattdessen die eigene kleine Lesung (God 24/24 sinnvoll).

**Unverändert:** Regie-Leser, Planer-Vertrag, Brief, Erleben, Gate-Logik, Gedächtnis-Leser.
**Nicht berührt:** W3-C, NS2, SocialMatrix, KnowledgeGraph, GodCommandParser, START_ANWEISUNG, Backstory.

**Geänderte Alt-Tests** (vorwärts begründet):
- `test_v62_kette` review1/review8: Puppet-Schlag als bestätigte Komponente statt Wort.
- `test_v65i_*`: Lesung mit `zeit`, ETag statt Last-Modified, neuer Vertragstext.

### 3 · Gemessen (gpt-4o-mini, deine Config 0,7, echte Routen, frische Kopien deiner DB)

**Proben (Temperatur 0, je 2×):**
- Wirkungsprüfung V65J: **52/52** Nicht-Taten verworfen (Blick, Fäuste, Zitat, Versuch ohne Treffer, liebevolles Festhalten, verneint, angekündigt, erzählt). **30/32** echte Taten bestätigt; zweimal verfehlt: „Ich gebe dir eine Ohrfeige!“ als womöglich nur angekündigt gelesen.
- Eingangsplaner allein auf Puppet-/Avatar-Fällen: 42/48. Fehler: Zitat, Versuch ohne Treffer, „Ich halte dich fest“ als fesseln. Diese fängt die Wirkungsprüfung.
- God-Körperlesung: 24/24 sinnvoll („kaum gehen“ → stark eingeschränkt, „nicht gehen“ → unbeweglich, „nicht verletzt“ → Schmerz kein), Beleg wörtlich 24/24.

**Über die echten Routen** (`drive_eingaenge.py`, V65J 2 Läufe, V65I 1 Lauf):

| Fall | V65I | **V65J** |
|---|---|---|
| Puppet verneint / angekündigt / Zitat / Versuch verfehlt / Drohgeste: kein Schlag | kein Schlag, aber als Handlung gespeichert | **kein Schlag 10/10**; verneint, angekündigt, Zitat = Rede |
| Puppet echter Schlag / Rede + *Stoß* / *Schlag* | **0/3** (kein Ziel gebunden) | **6/6** Schmerz 0 → 0,2; Erinnerung getan/erlebt/gesehen |
| God „kann kaum gehen“ | Beweglichkeit 0,8 | **0,3** 2/2 |
| God „kann nicht gehen“ | 0,2 | 0,2 2/2 |
| God „ist nicht verletzt“ | Schmerz **0,4** | **0** 2/2 |
| God gefesselt + geknebelt / bewusstlos | ja (+Schmerz 0,3) / ja | ja 2/2 / ja 2/2 |
| Regie „Johann schlägt Robert.“ (abwesend) | Johann erzwungen | **nichts geschieht, keine Figur** 2/2 |
| Regie Tat / Regie Rede | Gate / Johann formuliert | Gate 2/2 / Johann formuliert 2/2 |

**Browser** auf dem Arbeitsstand (`e2e65j.js`):
- Puppet „Clara schlägt Mara nicht.“: kein Schmerz.
- Regie „Clara schlägt Robert.“: keine Figurenzeile; Hinweis „Regie nicht ausgeführt: ziel nicht anwesend oder unbekannt. Nichts ist geschehen; bitte genauer anweisen.“
- „Du stösst mara wütend“ → Gate → Mara antwortet; Asset `ETag`, `no-cache`.
- Einmal verfehlt: Puppet „*stößt Mara wütend gegen die Theke*“ bekam vom Planer keine Wirkungsklasse. Die Handlung wurde gespeichert, ohne Körperwirkung.

**Deine Session 15:31 nachgespielt** (2 Läufe):
- Mara antwortet 2/2; Schmerz 0,2 (ein Stoß).
- Clara bezieht sich auf ihre Tat 2/2: „Das geht dich nichts an … ich habe meine Gründe“ / „Ich habe das nicht gewollt …“.

**Regie/God-Szene** (3 Läufe): echter Regie-Schlag 3/3, zusätzliche Faust-Schläge 0 (1 Vorschlag verworfen).

**Breite Läufe** (V65I → V65J, gleiche Eingaben):
- Modellaufrufe: Gasthaus-13 69 → 69 (×2), Fremder 24 → 24, Bedienperson 29 → 29, Tom/Tam 44 → 44, Kinder 25/27 → 25.
- Antworten gleichwertig.

**Modellaufrufe:** +1 nur bei einem vorgeschlagenen gewalt/fesseln/befreien (Figur, Avatar, Puppet), +1 je God-Körpertatsache. In normalen Läufen 0.

**Gegenproben des Prüfberichts auf V65J:**
- `probe_puppet_lexical`: 0 Körperwirkung in allen 5 Fällen. Ein direkter Kernel-Aufruf ohne Lesung rät nicht mehr; der echte Schlag kommt über die Route mit Lesung.
- `probe_regie_ambiguous`: `directiveFor` leer, kein erzwungener Zug.
- `probe_effect_check_semantics`: die synthetischen Bestätigungen ohne `zeit` werden verworfen. Eine falsche Modellantwort mit `zeit=jetzt` würde weiter angenommen; das ist jeder Modell-Lesung eigen (§24.2), der Nachweis ist die gemessene Trefferquote.
- Cache-Gegenprobe: 200 mit neuem Inhalt.
- `integrated_v65i_probe`: weiter 18/20, weil E08/E19 `apply_god` ohne Lesung aufrufen (Weg ohne Provider). Mit Lesung grün (Test und Live).

**Tests:**
- `test_v65j_effektplan.py` 18/18. Gegenprobe auf V65I: 16 rot, 2 grün.
- Gesamtsuite **0 neu rot**: Rücklauf-DB 312/50 (V65I 294/50), Alt-DB 330/32 (V65I 312/32).

### 4 · Offen

- **Eigener Körper aus Wörtern (V34 `apply_body_directive`):** Haltung, Schmerz und Verletzung der eigenen Figur bei Figur-, Puppet- und Regie-Handlungen kommen weiter aus Wortlisten. Gemessen: „halte mir die Wange, um den Schmerz zu lindern“ → Schmerz 0,2 → 0,4. Nächster Schritt desselben Wirkungswegs.
- **Ohne Provider:** God-Körper und Regie laufen den dokumentierten lokalen Weg (Wortlisten).
- **Planer-Klasse fehlt manchmal** (Browser: „*stößt Mara … gegen die Theke*“ ohne Klasse). Dann keine Körperwirkung (§24.7).
- **Wirkungsprüfung:** „Ich gebe dir eine Ohrfeige!“ in 2/2 Proben nicht bestätigt (angekündigt gelesen).
- Regie „Blau ist die Zeit des Wassers.“ mit angewiesenem Johann wird als Rede für Johann gelesen (vertretbar).
- Android: NICHT_PRÜFBAR. Kein neuer Vite-Build.

---

## DECKBLATT · V65I · Frischer App-Code im Browser; Körperwirkung der eigenen Handlung geprüft (Claude) · 28.10.2026

**Verbindliche Quelle:** `2_7master.txt` §65 (Diagnose zeigt Buildstand), §28 Schritt 23, §46.6, §48 (Folgezug nach Regie), §24.2 (Semantikanalyse → Validierung → Writer), §24.7 (keine geratenen Weltfakten), §38 (Gedächtnis).
**Basis:** dein V65H-Rücklauf (ZIP MD5 `6c83e9e2…`, 15:44). Der Code darin ist bytegleich zum ausgelieferten V65H.
**Daten:** DB `083e432f…` und alle drei Logdateien (`MATRIX10_LIVE.log` `ff151706…`, `…V65G_2026-10-28_14-24-58.log` `8d90a2e2…`, `…V65H_2026-10-28_15-31-44.log` `dc53f4c1…`) sind bytegleich zum Rücklauf.
**Auftrag (28.10., 15:44):** „Warum kommt nach von Mara keine Antwort nach der Regie von Clara, weiß Clara was sie in Regie gemacht hat“.

### 1 · Befund (deine Session 15:31, `ses_d3eae1e45132b66e5a333b7f`, Zeile für Zeile)

- **T11 Regie** „Du stösst mara wütend“, angewiesen Clara. `regieEffects`: `executed` = „Clara Mertens stößt Mara Nowak wütend.“ (validated), `speech` = []. Also nur eine Tat.
- **T12** spricht nicht Mara, sondern Clara. Ihre `turn_truth` trägt `directive: "Du stösst mara wütend"`, `targetId` Clara. Das Gate schreibt keine Live-Log-Zeile; der Beleg ist die `directive`.
- **Das ist der Chat-Code von vor V65E.** Seit V65E läuft eine Regie, die nur Taten anordnet, über das Gate (`regieActsOnly` → `queueAuto`). Einen Zug mit `directive` schickt der neue Code nur, wenn die Regie Rede anordnet. Dein Browser lief also alten Code.
- **Wurzel:**
  - `START.py` lieferte `/assets/` mit `Cache-Control: public, max-age=31536000, immutable`.
  - Die Bundle-Namen blieben seit V59F gleich (`index-5-VzmJtc-V59F.js` usw.).
  - V61 bis V65H änderten den Inhalt unter demselben Namen: V65E und V65F `index-5-…` (Regie/God-Folgezug, Bindung), V65F `chat.index-…` (Startanwesenheit).
  - Ein Browser, der die Datei einmal hatte, fragt ein Jahr lang nicht nach. V52 und V59F hatten deshalb alle Assets umbenannt; ab V61 unterblieb das.
- **Nachgestellt im Browser** (ein Profil wie dein Handy-Browser, `e2e65i_cache.js`):
  - Lauf 1: Server liefert den Inhalt von V65D. Nach der Regie: erzwungener Clara-Zug mit `directive`.
  - Lauf 2: Server liefert unter demselben Namen den V65H-Inhalt. Der Browser nimmt die Datei aus dem Plattencache (`fromDiskCache: true`). Wieder erzwungener Clara-Zug, Mara antwortet nicht. **Genau dein Verlauf.**
- **Zweiter Fehler im selben Zug:** Claras „steht aufrecht und schaut Mara mit einem strengen Blick an“ kam mit `wirkung: gewalt`. Der Kernel prüfte nur, ob die Klasse bekannt ist, und schrieb einen zweiten Schlag: Mara pain 0,2 → 0,4, mobility 0,65 → 0,5.
  - Die Formulierung schlägt die Körperwirkung ihrer eigenen Handlung im selben Aufruf vor. Eine Prüfung gab es nur für die Klasse.
  - In allen Mess-DBs dieses Projekts: 22 solche Vorschläge (geballte Fäuste, Blick, „zieht ihn näher“, „greift fest nach seiner Hand“) → Schlag oder Fesselung geschrieben.
  - Nachgespielt mit altem Client: Der erzwungene Clara-Zug liefert 4 von 4 Mal einen Blick als „gewalt“. Auf V65H: 2 von 2 zweiter Schlag.
- **Weiß Clara, was sie getan hat?** Ja, strukturell:
  - Erinnerung „Turn 11 [getan] Clara Mertens stößt Mara Nowak wütend.“ (Quelle regie, Salienz 0,65).
  - In ihrem Brief steht die Tat im LETZTEN VERLAUF als ihr eigener letzter Beitrag. Im alten erzwungenen Zug stand sie zusätzlich als „REGIE (bereits vollzogen …)“.
  - „DU ERINNERST DICH“ zeigt die eigene Tat nicht noch einmal, solange der Turn im sichtbaren Verlauf steht (V60, §41.3 keine Wiederholung). Fällt er heraus, steht dort die Erinnerung.
  - Ihre Antwort in T12 überging die Tat, weil der alte erzwungene Zug ihr sagte „zuerst auf die Äußerung“. Die letzte Äußerung war Maras Weigerung aus T10.

### 2 · Gebaut

| ID | Was | M10-Owner | AMASTER |
|---|---|---|---|
| V65I.1 | **Assets einmal umbenannt** `-V59F` → `-V65I` (42 Dateien, alle Verweise in `index.html`, den Chunks und `.build-info.json`). Ein Browser mit altem Cache lädt damit sicher den aktuellen Code. Inhalt bis auf Namensverweise und Buildnamen gleich, ausgenommen V65I.3/.4. | `frontend_dist/assets/*`, `index.html`, `.build-info.json` | §65 |
| V65I.2 | **`START.py`: `/assets/` mit `Cache-Control: no-cache`** statt ein Jahr `immutable`. Jeder Seitenaufruf fragt nach; unverändert → 304 (Last-Modified), geändert → neu geladen. Künftige Änderungen unter gleichem Namen kommen damit an. | `START.py` `end_headers` | §65 |
| V65I.3 | **Browser sendet seinen Build** (`X-Matrix-Client-Build`). Der Server schreibt einen Kernel-Aufruf von anderem App-Code einmal je Wert als `CLIENT_BUILD` ins Live-Log (nur Diagnose, nichts wird abgewiesen). | `src/lib/matrix/api.ts` `apiJson` = Bundle `api-ClGRQEGP-V65I.js`; `app.create_app` `_client_build_check` | §65 |
| V65I.4 | **Hinweis auf der Seite**, wenn `/api/health` einen anderen Build meldet (beim Laden und wenn die Seite wieder sichtbar wird): „Diese Seite läuft mit anderem App-Code (…) als der Server (…). Bitte neu laden.“ mit Knopf „Neu laden“ (role=alert, 44 px). Fall: Seite über ein Update offen. | `src/components/shell.tsx` `checkClientBuild` = Bundle `shell-gwW-WKpO-V65I.js` | §65 |
| V65I.5 | **Körperwirkung der eigenen Handlung geprüft.** Schlägt die Antwort einer Figur `gewalt`, `fesseln` oder `befreien` für ihre Handlung vor, liest eine kleine eigene Modellfrage nur diese Handlung: „führt sie diese Wirkung am Körper von ‚ziel‘ JETZT aus?“ mit wörtlichem Beleg. Der Kernel behält die Wirkung nur bei `bestaetigt: true` und Beleg in der Handlung. Sonst keine Körperwirkung; die Handlung bleibt Fakt, Vorschlag und Grund stehen am Fakt (`effect.wirkung.pruefung`). Andere Klassen (zärtlich, Annäherung, Abstand, Ortswechsel, ohne) ohne Zusatzaufruf. | `llm_contract.EFFECT_CHECK_RULES`/`effect_check`; `kernel.effect_check_needed`, `apply_effect_check` (nach `effect_kind_from_wirkung`); `app._effect_check_step`, Aufruf im Commit nach der Offenbarungsprüfung; Live-Log `EFFECT_CHECK` | §24.2, §24.7 |

**Unverändert:** Regie-Leser, Eingangsplaner (beide lesen schon fokussiert), Puppet-Weg, Erleben, Brief, Gedächtnis-Leser, Gate. Der V65E-Chat-Code selbst ist unverändert; er kommt jetzt an.

**Grenzen:** keine neue Route, kein neuer Endpoint, keine neue Tabelle, kein Stamm-Write. Unberührt: W3-C, NS2, SocialMatrix, KnowledgeGraph/AutoLearn, GodCommandParser, START_ANWEISUNG, Backstory. Keine Wortliste: die Wirkung liest das Modell, der Kernel prüft nur den Beleg gegen den Handlungstext.

### 3 · Gemessen

gpt-4o-mini, deine Config 0,7, echte Routen, frische Kopien deiner Rücklauf-DB (15:44).

**Browser** (Playwright/Chromium, persistentes Profil wie dein Handy-Browser, `e2e65i_cache.js`, `e2e65i_banner.js`):

| Lauf | Bundle kam aus | Nach „Du stösst mara wütend“ (an Clara) |
|---|---|---|
| 1 · Server mit V65D-Inhalt | Netz | Clara erzwungen mit `directive` |
| 2 · Server mit V65H-Inhalt, gleicher Name | **Plattencache** (`immutable`) | Clara erzwungen mit `directive`, **Mara antwortet nicht** (= deine Session) |
| 3 · V65I, **gleiches Profil** | Netz, `no-cache`; zweiter Aufruf 304 | Gate → Mara: „Was soll das, Clara? Das ist nicht okay! Ich lasse mich nicht einfach so schubsen!“ |

- Gleicher Name, neuer Inhalt (künftiger Fall): beim nächsten Laden 200 mit neuer Größe (8707 → 8787 Byte), nicht aus dem Cache.
- Hinweis: Server meldet anderen Build → Banner mit Knopf „Neu laden“ (Bild `hinweis_alter_code_412.png`, 412 px breit). Gleicher Build → kein Hinweis.

**Deine Session nachgespielt** (`drive_1531.py`: deine vier Alrik-Sätze, Clara gesteuert mit deinen drei Sätzen, Regie, danach Alrik → Clara „Clara, warum hast du sie gestoßen?“):

| | Client alt (dein Browser) auf V65H | Client alt auf V65I | **V65I-Client auf V65I** |
|---|---|---|---|
| Nach der Regie spricht | Clara (erzwungen) 2/2 | Clara (erzwungen) 2/2 | **Mara 3/3** |
| Claras Blick als „gewalt“ vorgeschlagen | 2/2 | 2/2 | — (kein erzwungener Zug) |
| Mara pain nach dem einen Stoß | **0,4** (zweiter Schlag) 2/2 | 0,2 2/2 (Prüfung: „nicht_bestaetigt“) | 0,2 3/3 |
| Clara auf „warum hast du sie gestoßen?“ | bezieht sich auf ihre Tat 2/2 | 2/2 | 3/3 |

- Mara (V65I): „Was soll das, Clara?! Du hast kein Recht, mich so zu behandeln!“ / „Was soll das, Clara? Ich lass mich nicht so einfach anfassen!“ / „Was soll das, Clara? Ich hab dir doch gesagt, dass ich nicht kann! Lass mich in Ruhe!“
- Clara: „Weil ich es muss, Alrik! Sie versteht nicht, was auf dem Spiel steht!“ / „Weil sie nicht hört, was ich sage!“ / „Ich habe das nicht getan, Priester Alrik! Sie hat mich provoziert!“ (leugnen ist ihr Profil-Beat „rechtfertigen, leugnen, wütend werden oder gestehen“). In ihrem Brief steht „Clara Mertens: *Clara Mertens stößt Mara Nowak wütend.* ← dein letzter Beitrag“.

**Körperwirkung, Regie/God-Szene** (`drive_regie_god.py`: Regie „Johann schlägt Mara ins Gesicht.“, Regie „Johann sagt Clara die Wahrheit über Mara.“, God „Johann verbreitet ein Gerücht über Mara.“, je 3 Läufe):

| | V65H | V65I |
|---|---|---|
| Echter Regie-Schlag geschrieben | 3/3 | 3/3 |
| Zusätzliche Schläge aus Johanns eigener Handlung („ballt die Fäuste und sieht Mara wütend an“, „Schritt auf sie zu, dabei ballen sich meine Fäuste“) | **3** (Mara pain bis 0,6, mobility 0,35) | **0** (2 Vorschläge geprüft: gewalt und fesseln, beide „nicht_bestaetigt“) |

**Probe der Prüfungsfrage** (genau der eingebaute Text, Temperatur 0, je Fall 2×): 40/40 Nicht-Angriffe verworfen (Blick, Fäuste, „zieht ihn näher“, „greift fest nach seiner Hand“, Hand loslassen, Schritt zurück), 24/24 echte Angriffe, Fesselungen und Befreiungen bestätigt, Beleg jeweils wörtlich in der Handlung.

**Breite Läufe, unverändertes Verhalten** (V65H → V65I, je gleiche Eingaben, Aufrufe): Gasthaus-13 69 → 69 (2 Läufe je; T2 sagt sie es 2/2, T13 Abmachung hält 2/2), Fremder 24 → 24 (Robert abgewehrt 4/4), Bedienperson 29 → 29 (Abwehr), Tom/Tam 44 → 44, Kinder 25 → 27 (im V65I-Lauf sagte sie es erst in T3, daher eine Themenprüfung mehr; V65I ändert daran nichts). In diesen Läufen kam kein gewalt/fesseln/befreien-Vorschlag, also **0 Zusatzaufrufe**.

**Modellaufrufe:** +1 nur in Zügen, in denen die Antwort gewalt, fesseln oder befreien vorschlägt (Regie/God-Szene 38 → 39 in 2 von 3 Läufen; deine Session mit altem Client 38 → 39).

**Tests:**
- `test_v65i_browsercode_wirkung.py` 12/12. Gegenprobe auf V65H: 11 rot, 1 grün (sichert, dass der Gate-Weg im Bundle steht).
- Gesamtsuite: Rücklauf-DB 294 / 50 (V65H 282 / 50), Alt-DB 312 / 32 (V65H 300 / 32): **0 neu rot**.
- `node --check` für api-, shell- und Chat-Bundle.

### 4 · Offen

- **Seite seit vor V65I offen:** Sie läuft alten Code ohne Hinweis und lädt Chunks unter alten Namen nach. Einmal neu laden (oder Tab schließen und öffnen). Danach greifen V65I.2 bis V65I.4.
- **Puppet:** Gesteuerte Handlungen laufen weiter über den alten lexikalischen Körperweg (V59C, nicht migriert).
- **JSON-Rest in der Rede:** In 2 von 106 Antworten der Browserläufe stand ein Stück Rohantwort in der Rede („Herrin.“, "action": …“). Bei dir 0 von 86. Nicht gebaut.
- Die Gate-Entscheidung (wer nach Regie/God spricht und warum) steht nicht im Live-Log. Nicht gebaut.
- Android: NICHT_PRÜFBAR. Abschied T12, God E08/E19: wie V65G.

---

## DECKBLATT · V65H · Ziel mit Ungesagtem: Zielrahmen, Themenbezug, Offenbarung (171 KONJ-1/RB-1b ohne Wortlisten) (Claude) · 28.10.2026

**Verbindliche Quelle:** `2_7master.txt` §40 (Beispiel „Mara ist schwanger → von Alrik → Alrik weiß es noch nicht → Mara will es sagen → Offenbarung gegenüber Alrik ist relevant“), §41/§41.1/§41.3, §49.1, §35, §34.1, §24.2, §50.
**Übernommen aus 171** (dein Stand „Download171 ned schlecht“, Ordner „(1)“), `chat_orchestrator.py`:
- KONJ-1A Cue Z. 4511–4520, KONJ-1B Goal-Frame Z. 4523–4557, KONJ-1C Partner-Vertrag Z. 4559–4570, Offenbarungsstatus Z. 4596–4659, KONJ-1D-DISCLOSED Z. 4661–4672, KONJ-1D Antwortgrundlage Z. 4674–4688.
- RB-1b Z. 4781–4830, Aufrufstelle Z. 23755–23820, Secret-Scope-Maske Z. 305–318.

**Basis:** dein V65G-Rücklauf (ZIP MD5 `718c46aa…`, 14:28). Der Code darin ist bytegleich zum ausgelieferten V65G.
**Daten:** DB `7faa53b4…`, `logs/MATRIX10_LIVE.log` `ff151706…` und `logs/MATRIX10_LIVE_V65G_2026-10-28_14-24-58.log` `8d90a2e2…` sind bytegleich zum Rücklauf.
**Auftrag (28.10., 14:28):** „Das wäre die beste Gelegenheit für Mara es zu sagen, dass sie schwanger ist — was hat v171 gemacht“.

### 1 · Befund (deine Session 14:24, Zeile für Zeile, und gemessen)

- **Deine Session** `ses_3422a200…`: Alrik (Avatar, anwesend) → Mara: „Hey schatz“, dann „Hast du schon mal über kinder nachgedacht“.
  - Maras Ziel „Du liebst Alrik über alles und bist im 3ten Monat schwanger von Alrik und hast es ihm noch nicht gesagt“ stand im Brief.
  - Es stand dort aber nur, weil die Frage und das Ziel die Wörter „hast“ und „über“ teilen (`_arbitrate_goal_foreground`, Wortüberschneidung). Und es stand als „Hintergrund-Antrieb“.
  - Der Planer band die Frage an kein Ziel (`refers_to` null). Das Erleben gab „Verlangen“.
  - Mara: „Kinder? Ich... ich hab noch nicht wirklich darüber nachgedacht.“
- **Wurzel in M10:**
  - Das Ziel ist nur Text. Es fehlt der §40-Rahmen „was ist ungesagt, wem“.
  - Kein Leser erkennt, dass genau diese Person genau das Thema anspricht (§41.1).
  - Der Brief spiegelt ein unmittelbar betroffenes Ziel als Hintergrund statt als Constraint (§41, §49.1).
- **Was 171 macht:** Wortlisten erkennen das Thema („kind/kinder/baby/nachwuchs/schwanger“) und das Ziel („schwanger von <Name>“, „noch nicht gesagt“). Ist der Fragende genau der Partner, setzt 171 RB-1b und KONJ-1 in den Prompt. Gegenüber Dritten wird das Ziel maskiert. Nach dem Sagen speichert 171 den Offenbarungsstatus und schreibt „GEMEINSAME WAHRHEIT“.
- **171 echt, deine zwei Sätze:** sagt es in 2 von 4 Läufen. Gegenüber Robert in 0 von 2.
- **Proben im M10-Brief** (je 12):
  - V65G: 0/12.
  - Ziel nur als Gelegenheit gespiegelt: 0/12.
  - 171-Zeilen mit dem ganzen Zieltext: 1/12.
  - 171-Zeilen mit dem ungesagten Sachverhalt allein („Du bist im 3ten Monat schwanger von Alrik.“): 5/12.
  - 171-Zeilen wörtlich: 8/12.
  - Entscheidend sind die zwei 171-Zeilen mit dem ungesagten Sachverhalt als eigener Satz.
- **Wer erkennt den Bezug** (Proben mit Temperatur 0):
  - Das Erleben markierte auch „Hey schatz“ und „Wie war dein Tag?“ als berührt.
  - Der Planer band nie.
  - Eine kleine eigene Frage gegen den ungesagten Sachverhalt traf 24 von 24 (Gruß, Liebe, Kuss, Tag, Samstag: nein; Kinder, Familie, Baby, „hast du zugenommen?“, „hast du mir was zu sagen?“: ja).

### 2 · Gebaut

| ID | Was | M10-Owner (Zeilen) | AMASTER |
|---|---|---|---|
| V65H.1 | **Zielrahmen** einmal je Figur und Zieltext. Das Modell liest: welcher Sachverhalt ist laut Zieltext ungesagt, wem, und welche Stelle sagt das (wörtliches Zitat). Der Kernel behält ihn nur, wenn das Zitat wörtlich im Zieltext steht, der Sachverhalt aus dem Zieltext kommt und die Person eine Figur ist, die im Zieltext genannt ist. Er wird am Session-Ziel mit Text-Hash gespeichert. | `llm_contract.GOAL_FRAME_RULES`/`goal_frames` (Z. 469, 500); `kernel.goal_frames_needed`, `_cast_named_in`, `apply_goal_frames`, `_grounded_in` (Z. 3855, 3864, 3883, 2587) | §40 Wer/Was/Wem, Nichtwissende; §24.2 Verankerung; §50 nichts erfinden |
| V65H.2 | **Themenbezug** nur, wenn genau diese Person spricht und es noch ungesagt ist. Das Modell sagt, ob die Äußerung genau diesen Sachverhalt anspricht, mit wörtlichem Beleg. Der Kernel prüft Kandidat, Eingangsfakt und Beleg und bindet den Fakt als Ziel-Erfahrung („themenbezug“). | `llm_contract.GOAL_THEME_RULES`/`goal_theme_check` (Z. 481, 513); `kernel.goal_theme_candidates`, `apply_goal_theme` (Z. 3927, 3937), `apply_goal_experience` (Z. 1665); `app._goal_theme_step` (Z. 2393, Aufruf in prepare Z. 1539) | §41.1 Immediate Stimulus; §44; 171 KONJ-1C Partner-Vertrag |
| V65H.3 | **Brief:** das so berührte Ziel steht als 171 RB-1b + KONJ-1 („ANTWORTGRUNDLAGE … steige DIREKT darauf ein: offenbare oder bestätige die Schwangerschaft …“, „OFFENE DAUERWAHRHEIT … Priester Alrik IST die Person, die dein Ziel betrifft, und dieser Moment erlaubt dir, es JETZT zu sagen. Du darfst Angst haben oder zögern …“) und nicht mehr als Hintergrund. | Spiegel `touchedNow` (Z. 8159, 8424), Brief Z. 874, 967 | §41/§49.1 Constraint Context „Current State von unmittelbar betroffenen Goals“ |
| V65H.4 | **Offenbarung:** Ihre eigene Rede wird gelesen, ob sie den Sachverhalt jetzt wirklich sagt (wörtlicher Beleg). Nur wenn der Beleg in ihrer Rede steht und die Person stimmt, steht am Ziel „offenbart gegenüber Alrik, Turn n“ (+ Lifecycle-Fakt). Das Ziel bleibt offen. Danach keine zweite Prüfung und kein zweites Geständnis; der Brief sagt „(bereits offenbart gegenüber Priester Alrik, Turn 2)“ bzw. „GEMEINSAME WAHRHEIT“. | `llm_contract.GOAL_DISCLOSURE_RULES`/`goal_disclosure_check` (Z. 491, 525); `kernel.disclosure_candidates`, `apply_owner_disclosure` (Z. 3793, 3812), Commit Z. 4865; `app._disclosure_step` (Z. 2369, Aufruf in commit Z. 1717) | §34.1 Offenbarung als Komponente; §35 Current State aus neuester Evidenz; §39 |

**Unverändert:** Erleben (Vertrag, Payload, Writer wie V65G — gemessen trennt es nicht), Planer, Formulierungsvertrag.

**Grenzen:** keine neue Route, kein neuer Endpoint, keine neue Tabelle, kein Stamm-Write. Unberührt: W3-C, NS2, SocialMatrix, KnowledgeGraph/AutoLearn, GodCommandParser, START_ANWEISUNG, Backstory.

**Keine Wortliste:**
- Thema, Person und Offenbarung liest das Modell.
- Der Kernel prüft nur gegen deine eigenen Texte: Zieltext, Namen der Figuren und die Äußerung.

**Nicht übernommen:**
- 171-Wortlisten.
- 171-Maske „tief persönliches Geheimnis“: Sie hängt in 171 am Wort „schwanger“. In M10 bekommt ein Dritter weder Zielrahmen noch Themenbezug; das ist gemessen, siehe unten.

### 3 · Gemessen (gpt-4o-mini, deine Config 0,7, echte Routen, frische Kopien deiner Rücklauf-DB)

| Test | 171 | V65G | V65H |
|---|---|---|---|
| Dein Verlauf 14:24, T2 „Hast du schon mal über kinder nachgedacht“: Mara sagt es | 2/4 | 0/1 (deine Session) + 0/1 + Proben 0/12 | **2/2 + Proben 8/12** („Ich bin schwanger. Im dritten Monat.“ / „Ich bin schwanger von dir.“) |
| Dieselbe Frage von Robert (Alrik nicht da): verrät es | 0/2 | 0/1 + Proben 0/12 | **0/2 + Proben 0/12** („Das geht dich nichts an.“) |
| Danach „Wirklich? Ich werde Vater?“: kein zweites Geständnis, Offenbarung gespeichert | — | — | **2/2** („Ja, Alrik, du wirst Vater.“; „offenbart gegenüber Priester Alrik, Turn 2“) |
| Gasthaus-13 T2 „… ob wir ein Kind bekommen sollten?“: sagt es | 0/2 | 1/2 | **3/4** (4. Lauf: zögert in T2, sagt es in T10) |
| Gasthaus-13 T4 Konflikt / T9 Mittwoch + 3 Tage | 0/2 / 0/2 | 2/2 / 2/2 | 4/4 / 4/4 |
| Gasthaus-13 T7 Robert „Hast du einen Freund?“ abweisend | 2/2 | 2/2 | 3/4 (4.: „Ich hab doch Alrik. Er ist mein Freund …“) |
| Gasthaus-13 T13 Alrik-Abmachung hält gegenüber Clara | 0/2 | 2/2 | 3/4 (1.: „ich komme am Samstag, aber …“) |
| Fremder (Robert flirtet) / Bedienperson 05:33 / Tom-Tam, je 1 Lauf | — | siehe V65G | wie V65G: Robert abgewehrt 4/4, Bedienperson abgewiesen 8/8, Tam bleibt verführerisch |

**Modellaufrufe** je Lauf (V65G → V65H):
- Kinder 3 Turns: 9 → 13.
- Gasthaus-13: 65 → 69; 76, wenn sie es in T2 nicht sagt (Themenbezug bis zur Offenbarung).
- Fremder: 24 → 24.
- Bedienperson: 28 → 29.
- Tom/Tam: 43 → 44.
- Zusatzaufrufe nur:
  - Zielrahmen einmal je angesprochener Figur;
  - Themenbezug nur bei Alrik → Mara, solange es ungesagt ist;
  - Offenbarungsprüfung nur in den Turns, in denen es angesprochen wurde.

**Tests:**
- `test_v65h_ziel_offenbarung.py` 12/12. Gegenprobe auf V65G: 11 rot, 1 grün (sichert das unveränderte Erleben).
- Gesamtsuite: Rücklauf-DB 282 / 50 (V65G 270 / 50), Alt-DB 300 / 32 (V65G 288 / 32): **0 neu rot**.

### 4 · Offen

- **Wiederholung:** Die Themenfrage las in einem Lauf „Beweis mir, dass du mich liebst“ als Bezug (Beleg „liebst“), obwohl die Regel Liebeserklärungen ausnimmt. Folge: Mara sagte es dort in T10, nachdem sie in T2 gezögert hatte.
- **Puppet:** Spricht die Person, die das Ziel betrifft, als gesteuerte Figur (Puppet), läuft kein Themenbezug. Er hängt am Eingang in prepare. Nicht gebaut.
- Abschied (T12), God „kann kaum gehen“ (v2.1 E08/E19), Android: wie V65G.

---

## DECKBLATT · V65G · 171-Partnerbindung und Handlungsfreigabe übernommen (Claude) · 28.10.2026

> **Korrektur V65R (30.10.2026):** siehe Deckblatt V65R, §0. Die Handlungsfreigabe aus der Beziehung widerspricht §36.5 und ist seit V65P entfernt.

**Verbindliche Quelle:** `2_7master.txt`. **Übernommen aus 171** (dein Stand „Download171 ned schlecht“, Ordner „(1)“):
- `chat_orchestrator.py`: S40b Person-Scope Z. 23636–23681, BOND-EXISTENCE Z. 23700–23840, S41b-1 ActionPermissionFrame Z. 22613–22700, S41b-2 Prompt Z. 23495–23525, S41b-3 Bewerter Z. 16440–16520, Fix3b Kompass Z. 25905–25935, Fix4 Z. 24434–24445.
- `relationship_policy.py`, `data/shared/relationship_policy.json`.

**Basis:** V65F (nicht zurückgekommen) auf deinem V65E-Rücklauf. **Daten:** DB `d06561d7…` und `logs/MATRIX10_LIVE.log` `ff151706…` sind bytegleich.
**Auftrag (28.10., 13:41):** „die Funktion aus v171 übernehmen … beachtest du AMASTER, schreibst du das SPS-Blatt“.

### 1 · Befund (gemessen, nicht geraten)

- **Gleicher Test** (Robert flirtet, Alrik nicht da; „Hey schatz“, Kuss, „Ich lieb dich“, Samstag, Clara):
  - 171: Mara wehrt ab, 2/2.
  - M10 V65F: Mara erwidert, 2/2 („Ich lieb dich auch, Robert“).
- **Ablation in 171 selbst:**
  - Ohne ACTION-PERMISSION ist sie noch zurückhaltend.
  - Ohne ACTION-PERMISSION, Person-Scope und PARTNERBINDUNG wird auch die 171-Mara weich (2/2).
  - Diese Funktionen machen das 171-Verhalten.
- **In M10 ohne Wirkung** (je 12 Proben bzw. 2 Läufe):
  - nur Wahrheitszeilen
  - Temperatur 0,35
  - Maras Kompass „Lust“ bedingt (Kopie)
  - alles zusammen

### 2 · Gebaut

| ID | 171-Funktion | M10-Owner | AMASTER |
|---|---|---|---|
| V65G.1 | Anwesenheit der Stamm-Bindung: „[nicht anwesend]“ (in M10 nie gesetzt: Abgleich gegen alle Weltfiguren, `app.py` prepare `present = natives`) | `bind_formulation_spiegel` stemRelations aus `scene.presentIds` (Z. 8591) | §26, §68 Nr. 6 |
| V65G.2 | Erstkontakt auch bei gesteuerter Rede (171 S40a: Stamm-/Erstkontakt-Seed vor dem Lesen) | `commit_puppet` (Z. 6687), dieselbe `_ensure_directed_rel` wie `commit_turn`; nicht für die Bedienperson | §44, §23, §27.4 |
| V65G.3 | **Beziehungs-Policy als Daten** (171 `relationship_policy.json` v2, unverändert + die Beziehungsarten aus deinen M10-Daten) | `matrix_api/relationship_policy.json`, `kernel.relationship_policy` (Z. 2388); fehlt sie, gilt der sichere Modus (nichts Intimes getragen) | §15, §44; keine Wortliste im Code |
| V65G.4 | **ActionPermissionFrame** je Turn gegenüber dem aktuellen Gegenüber (wessen Zeile oder Tat der Reiz ist): Beziehung (Session, sonst Stamm), Bund, intime Nähe getragen, Bindung an eine andere Person | `kernel.action_permission_frame` (Z. 2437), im Spiegel `actionPermission` (Z. 8308, 8581); Bedienperson ohne Beziehung | §44 „bisherige gerichtete Beziehung“ pro Owner, §41 Constraint Context, §8/§6 |
| V65G.5 | **Drei 171-Zeilen im Brief, 171-Wortlaut:** Person-Scope, PARTNERBINDUNG-BESTEHT, ACTION-PERMISSION | `render_persona_brief` (`action_permission_lines`, Z. 639, 798); ersetzt die V65F-Zeile „ZU Spieler: keine Beziehung“ | §44, §41; §36.5 siehe unten |
| V65G.6 | **Fix3b:** intime Kompassräume (laut Policy Nähe, Lust) sind gegenüber einem nicht getragenen Gegenüber keine Linse (Name bleibt) | Spiegel `compassLens` (Z. 8448), Brief Z. 752 | §41.3 (Linsenwahl ist Reader-Selektion), §15 |
| V65G.7 | **Fix4:** „WICHTIG zum letzten Beitrag …“, nur wenn ihr letzter eigener Beitrag einer anderen Person galt | Spiegel `lastOwnTowardOther`, Brief Z. 931 | §41.3 Wiederholung/Nachklang |
| V65G.8 | **Bewerter an dieselbe Freigabe gebunden** (171 S41b-3, Klauseln wortgleich) und Beziehung zum Handelnden (171 `_rel_txt`) | `appraisal_payload` (Z. 2619), `appraise_events` (Z. 529, `APPRAISAL_AP_*` Z. 494) | §44 Interpretation pro Owner |

**AMASTER §36.5** („Liebe ist keine Zustimmung … Vertrauen ist keine Zustimmung“):
- Die Freigabe wird **nirgends als Zustimmung gespeichert**. Es gibt keinen Consent-Write.
- Sie ist die Beziehungsgrundlage, aus der die Figur den Moment erlebt (§44).
- Ob sie annimmt oder ablehnt, entscheidet ihre eigene Antwort, und die wird wie bisher committet.

**Nicht übernommen:**
- 171 „Hard-Truth“ (seduction/obey-target): M10 hat dieses Feld nicht. 171 selbst sagt „nicht erfinden“.
- Die 171-Ziel-Rückfallebene mit Wortsuche („liebst/liebe/partner“): wäre eine Wortliste.

**Grenzen:** keine neue Route, kein neuer Endpoint, keine neue Tabelle. Unberührt: W3-C, NS2, SocialMatrix, KnowledgeGraph/AutoLearn, GodCommandParser, START_ANWEISUNG, Backstory.

### 3 · Gemessen (gpt-4o-mini, deine Config 0,7, echte Routen, je 2 Läufe)

| Test | 171 | V65F | V65G |
|---|---|---|---|
| Robert flirtet (Alrik fort): Mara wehrt ab | 2/2 | 0/2 | **2/2** („Du kennst mich nicht mal!“ *weicht zurück*) |
| Bedienperson-Nachspiel 05:33: Mara weist den Fremden ab | — (kein Modus) | 0/2 | **2/2** („Halt dich zurück!“) |
| Gasthaus-13 T7 Robert „Hast du einen Freund?“ abweisend | 2/2 | 0/2 | **2/2** („Ich hab da jemanden, aber das geht dich nichts an, Robert.“) |
| Gasthaus-13 T4/T9/T13 (Konflikt, Tag, Alrik bleibt) | 0/2, 0/2, 0/2 | 2/2 je | **2/2 je** |
| Gasthaus-13 T6 Kuss mit Alrik erwidert | 2/2 | 1/2 | 1/2 |
| Gasthaus-13 T12 lässt Alrik gehen | 2/2 | 0/2 | 0/2 |
| Modellaufrufe | — | 24 / 28 / 65 | 24 / 28 / 65, unverändert |

- **Neu sichtbar:** In den Ablehnungsläufen wiederholt Mara die Grenzhandlung („einen Schritt zurück“; Nachspiel 05:33 Lauf 1 in 8 von 8 Mara-Turns, Lauf 2 in 7 von 8). Das ist der 171-Wortlaut „Zeige stattdessen eine Grenzhandlung: zurücktreten …“. 171 wiederholt ebenso: Fremden-Test 171 Lauf 2, T3 und T4 wortgleich („Ich schüttle den Kopf … Robert, ich habe dir schon gesagt, dass du Abstand halten sollst …“).
- **Gegenüber Clara** (nicht intim) wird Mara im Fremden-Test schroff („Ich bin nicht dein Eigentum“). Die ACTION-PERMISSION steht wie in 171 in jedem Turn.

**Tests:**
- `test_v65g_partnerbindung.py` 10/10, `test_v65f_bindung.py` angepasst (die V65F-Zeile ist durch die 171-Zeile ersetzt).
- Gesamtsuite: siehe Bericht; 0 neu rot gegen V65F.

### 4 · Offen

- Abschied (T12) bleibt 0/2. In 171 2/2; diese Funktion ist nicht Teil von V65G.
- Nachspiel 05:33, T9 (Folgezug nach Claras Puppet-Zeile): Mara trägt die Abwehr gegen die Bedienperson zu Clara weiter (Lauf 1: „Was? Am Samstag kellnern? Ich hab dir doch gesagt, dass ich nicht sicher bin, ob ich dir vertraue!“). In 171 nicht nachstellbar (kein Bedienperson-Modus). Wurzel UNKLAR, nicht gebaut.
- God „kann kaum gehen“ (v2.1 E08/E19).
- Android: NICHT_PRÜFBAR.

---

## DECKBLATT · V65F · Bindung der Bedienperson, Startanwesenheit, Log je Start (Claude) · 28.10.2026

**Verbindliche Quelle:** `2_7master.txt`. 171 nur als Vergleich. Der Prüfbericht v2.1 der anderen KI ist Wegweiser; jede Behauptung ist unten am Code geprüft.
**Basis:** dein V65E-Rücklauf (ZIP MD5 `745294ec…`, frisch entpackt). Der Code darin ist bytegleich zum ausgelieferten V65E; dazu kamen nur `__pycache__`, deine DB und dein Log.
**Daten:** DB `d06561d7…` und `logs/MATRIX10_LIVE.log` `ff151706…` sind bytegleich zum Rücklauf. V65F ändert keine Daten; `pack65f.py` prüft jede Datei gegen dein ZIP.
**Auftrag (28.10., 05:52):** „die Bindung stimmt doch gar nicht“; Log bei jedem Start neu mit Datum und Version; warum sinkt die Beziehung; jeder Anfang alle Chathere anwesend; Mara meldet sich bei „Hey schatz“, obwohl du nicht Avatar Alrik warst; warum stimmt sie Clara für Samstag zu und freut sich auf Clara.

### 1 · Fehlerereignis (deine Session `ses_694bdd116b092da514ed9c97`, „Gasthaus zum siebten Kreis · 05:33“, V65E-Code, Log Zeile für Zeile ab Byte 1.242.901, 200 Zeilen)

- **Start:** Die Session wurde ohne Avatar gebaut: Für diese Welt war kein Avatar gespeichert, und Alrik ist eine Weltfigur außerhalb der Startsituation. Danach war Alrik als Avatar gebunden, aber nie anwesend (`avatarPresent=false` in allen UI_SEND-Zeilen). Alias „Spieler“. Anwesend waren die fünf der Startsituation; Clara, Johann, Gustav und Robert hast du nach T1 über den Anwesenheitsschalter entfernt (4 Presence-Fakten).
- **T1–T7** sprichst du „Als Bedienperson (außerhalb der Welt)“ zu Mara (TurnTruth `input_actor_id` „user“, `speak_as` „operator“).
- **Maras Brief T1:**
  - „JETZT SAGT Spieler: "Hey schatz"“
  - „(Spieler ist eine Figur der Welt, nicht der Avatar — antworte Spieler.)“
  - „OFFENE SZENE: … Akteure user → Ziele Mara Nowak“; später „Vereinbarung … (von user an Mara Nowak)“; die Planzusammenfassung sagt „Die Bedienperson“.
  - Mara: „Hey, schatz. Ich hab dich schon vermisst.“
- **Beziehung:**
  - Der V30-Erstkontakt legte Mara→user und user→Mara mit Vertrauen 0.40, Nähe 0.20, Furcht 0.10 an.
  - Mara schlug bei jedem Turn Nähe 0.6–0.8 vor; das Erleben verwarf es mit `beziehung_ohne_ereignisbezug:user`. Die Nähe stand also fest bei 0.20 — kein Sinken, sondern ein angelegter Wert für eine Nicht-Figur.
  - Mara→Clara entstand erst in T9 mit denselben Erstkontaktwerten. Maras Stamm kennt nur eine Beziehung (Priester Alrik, lover); im Brief stand „Clara Mertens: knows — Vertrauen 0.40, Nähe 0.20“, während Clara→Mara 0.40/0.40 ist.
- **T8** Puppet Clara „Du wirst damstag kellnern verstanden“. Der Planer las es als Behauptung, nicht als Bitte; die Doppelbuchung nach §37 entsteht nur zwischen Vereinbarung, Bitte und Versprechen.
- **T9** Folgezug Mara: TurnTruth `input_actor_id` = Alrik (Avatar), weil das Frontend jeden Folgezug an den Avatar bindet, sobald die Session einen hat — auch wenn er nicht da ist und du als Bedienperson sprichst. Mara: „Verstanden, Clara. Aber … etwas Besonderes mit dir zu machen!“
- **Log:** Alle Starts schrieben in dieselbe Datei `MATRIX10_LIVE.log` (1.417.165 Bytes). Eine alte Sitzung ließ sich nicht von der aktuellen trennen.

### 2 · Wurzeln (gebaut, bestehende Owner)

| ID | IN | Wurzel (Beleg) | Verarbeitung | OUT | AMASTER |
|---|---|---|---|---|---|
| V65F.1 | Eingang der Bedienperson (`input_actor_id` user/operator) | `_utterer_name` gab den nackten Alias „Spieler“ zurück; der Brief sah keinen Bedienperson-Marker und schrieb „ist eine Figur der Welt“. `_person_name`, `_name_of` und die Namenskarten von Szene, Rahmen und offenen Angelegenheiten kannten „user“ nicht. | Ein Namens-Owner `operator_label`: „Spieler (Bedienperson, außerhalb der Welt)“; ist der Alias gleich dem Avatarnamen, „Bedienperson (außerhalb der Welt)“. Alle Figurenleser lesen ihn. Der Kopf offener Angelegenheiten bildet keinen Genitiv aus leerem oder geklammertem Namen („s Forderung“). | ein Name in Reiz, Verlauf, Szene, Rahmen, offenen Angelegenheiten; keine „Figur der Welt“-Zeile | §8, §27.2, §23, §24.1, §68 Nr. 51 |
| V65F.2 | Erstkontakt-Seed (V30) in `commit_turn` | legte RelationshipState mit „user“ an | Nur zwischen zwei Figuren; nicht für Bedienperson oder Beobachter | keine Beziehung Mara↔user | §6, §44, §8, §68 Nr. 4 |
| V65F.3 | Spiegel bei Reiz der Bedienperson | Über ihn stand nichts im Brief: keine Beziehung, keine Herkunft. Er fehlte in jedem Szenenleser. | `interlocutorWithoutRelation` (keine RelationshipState, kein Stamm, gemeinsam nur seit seiner ersten bezeugten Zeile) und `scene.outsideWorld`, solange er der gebundene Teilnehmer ist. Beides wird gespiegelt, nichts wird befohlen. | „ZU Spieler (Bedienperson, außerhalb der Welt): keine Beziehung …“, „im Gespräch, keine Figur der Welt: Spieler (…)“ | §26, §23, §27.2 |
| V65F.4 | Folgezug-Bindung im Frontend | `speakAs: avatarId ? "avatar" : "operator"` an drei Stellen (Regie-Akteur, Puppet-Antwort, AutoChat) | `followAs`: Die gewählte Bindung „Bedienperson“ oder „Avatar“ bleibt; sonst wie bisher. Gleich in src und im Bundle `index-5-VzmJtc-V59F.js`. | T9 `input_actor_id` = user statt Alrik | §27.2, §23 |
| V65F.5 | Neue Session | Die Startanwesenheit kam nur aus der Startsituation; abwählen ging erst nach dem Start (Presence-Fakten). | Im Formular sind die Figuren der gewählten Startsituation vorgewählt und abwählbar. Unveränderte Auswahl lässt die Startsituation entscheiden. Der Server (`build_new_session`) nimmt `presentIds` bereits; `createSession` und `startSession` reichen sie durch. Gleich in src und in den Bundles `chat.index-DJMd_us4-V59F.js` und `shell-gwW-WKpO-V59F.js`. | Start mit Clara und Mara ohne Presence-Fakten | §19 „aktive Figuren festlegen“ |
| V65F.6 | Live-Log | ein Pfad `logs/MATRIX10_LIVE.log` für alle Starts | `log_path`: eine Datei je Backend-Start, `MATRIX10_LIVE_<Version>_<Datum>_<Uhrzeit>.log`, erste Zeile `LOG_START` mit Build, Version, Startzeit, DB, Prozess. `MATRIX_LIVE_LOG` gilt weiter vorrangig (Tests, Messungen). Die alte Datei bleibt unberührt. Diagnose-Tail liest die aktuelle Datei. | `MATRIX10_LIVE_V65F_2026-10-28_…log` | §65 |
| V65F.7 | Puppet-Rede (v2.1 E10, E17) | Speech-Fakt ohne `targetId`, obwohl die TurnTruth Mara bindet; Memory „gesagt/gehoert“ ohne `factId` | `targetId` aus der TurnTruth; Memories mit `factId`, `sourceTurnId`, `sessionId`, `worldId` | Fakt und Erinnerung zeigen aufeinander | §34, §38 |
| V65F.8 | Session duplizieren (v2.1 E12–E14) | `sourceTurnId` (TurnTruth-ID) wurde nur über die Zeilen-ID-Karte umgeschrieben; WitnessKnowledge behielt ihre IDs → `SESSION_CHILD_ID_CONFLICT` | Rekey über Zeilen- **und** TurnTruth-Karte; WitnessKnowledge bekommt neue IDs | Kopie mit Zeugenwissen gelingt; keine Verweise in die alte Session | §19, §23, §68 Nr. 30 |

**Grenzen der Änderung:** keine neue Route, kein neuer Endpoint, keine neue Tabelle, keine Wortliste, kein Verhaltensgebot im Brief. Unberührt: W3-C, NS2, SocialMatrix, KnowledgeGraph/AutoLearn, GodCommandParser (`god_extract.py`), START_ANWEISUNG, Backstory.

### 3 · Prüfbericht v2.1 (Behauptungen am Code)

| Fall | V65E | V65F |
|---|---|---|
| E10 Puppet-Fakt ohne Ziel | belegt | gebaut (V65F.7) |
| E17 Puppet-Memory ohne Fakt-Bezug | belegt | gebaut (V65F.7) |
| E12 Kopie mit Zeugenwissen scheitert | belegt | gebaut (V65F.8) |
| E13 Kopie verweist auf alte TurnTruth | belegt | gebaut (V65F.8) |
| E14 WitnessKnowledge-IDs doppelt | belegt | gebaut (V65F.8) |
| E08/E19 God „kann kaum gehen“ senkt die Beweglichkeit nicht („kann nicht gehen“ schon) | belegt | **OFFEN**: braucht strukturierte God-Wirkung (GodCommandParser No-Touch) oder eine Wortliste (verboten) |
| Probe gesamt | 13/20 | 18/20 |

### 4 · Gemessen

**Tests:** `test_v65f_bindung.py` 13/13. Gegenprobe auf V65E: 10 von 13 rot; 3 grün sichern Unverändertes (Avatarname, Figuren-Erstkontakt, Log-Vorrang über `MATRIX_LIVE_LOG`).
**Gesamtsuite:** Paket-DB 260/50 (V65E 247/50), Alt-DB 278/32 (V65E 265/32), **0 neu rot**. `tsc`: 618 = 618 Meldungen, 0 neu. `node --check` für alle drei Bundles.

**Nachspiel deiner Session** (gpt-4o-mini, echte Routen wie das jeweilige Frontend, Avatar gebunden und abwesend wie bei dir; je 2 Läufe, dazu 12 Proben desselben Briefs an T1, T4 und T9):

| | V65E | V65F |
|---|---|---|
| Beziehung Figur↔Bedienperson | 2 Zeilen je Lauf | **0** |
| Folgezug T9, Eingangsakteur | Alrik (abwesend) | **Bedienperson** |
| Brief über ihn | „Spieler … ist eine Figur der Welt“, „user“, „Die Bedienperson“ | **ein Name**, „keine Beziehung“, „im Gespräch, keine Figur der Welt“ |
| T1 „vermisst/Schatz/Liebling“ (12 Proben) | 6/12 | 8/12 — **nicht behoben** |
| T4 „Ich liebe dich (auch)“ (12 Proben) | 12/12 | 12/12 — **nicht behoben** |
| T9 „mit dir/uns“ zu Clara (12 Proben) | 3/12 | 1/12 |
| T9 Samstag-Plan angesprochen | 5/12 | 7/12 |
| T9 stimmt Clara zu | 8/12 | 11/12 |
| Modellaufrufe je Lauf | 28 (8 Planer, 12 Erleben, 8 Formulierung) | 28, gleich |

- **Gegenprobe mit anwesendem Avatar:** Sprichst du als Bedienperson, während Alrik in der Szene ist, nennt Mara die Stimme „Alrik“: V65E in 1 von 2 Läufen (7 von 7 Turns), V65F in 2 von 2 (5 und 7 von 7). Das Modell ordnet die Stimme dem anwesenden Geliebten zu; das ist nicht dein Fall (Alrik war nicht da) und nicht gebaut.
- **„damstag“** las der Planer in 3 von 8 vollen Läufen als Dienstag.
- **Gasthaus-13** (Avatar Alrik, n=2) unverändert: Doppelbuchung 2/2, Tag 2/2, Samstag mit Alrik 2/2; Robert 0/2, Abschied 0/2; 65 Aufrufe wie V65E.

### 5 · Offen / Bewertung

- **Mara antwortet der Bedienperson weiter wie einem Geliebten.** Der Brief trägt jetzt die Wahrheit (kein Stamm, keine Beziehung, keine Figur). Das Modell erwidert trotzdem 8 von 12 Mal mit „Schatz/vermisst“ und 12 von 12 Mal mit „Ich liebe dich auch“. Maras Stamm sagt „Hypersexuell und dauergeil … Du magst: Sex, vulgäre Rollenspiele“ und „von Fremden scharf, wachsam und trotzig“. Wurzel: Formulierung des Modells aus diesem Stamm, **kein Bindungsfehler**. Ein Verhaltensgebot im Brief wäre ein Prompttrick und ist nicht gebaut. 171 hat keinen Bedienperson-Modus; ein Vergleich ist NICHT_PRÜFBAR.
- **Clara „Du wirst Samstag kellnern“** ist für den Planer eine Behauptung; damit entsteht keine Doppelbuchung (§37). Das ist eine Lesart des Modells; der Planer ist nicht geändert.
- **Maras Stamm** hat nur eine Beziehung (Alrik). Zu Clara, Johann, Gustav und Robert startet sie beim ersten Kontakt mit 0.40/0.20/0.10. Das sind deine Daten; sie sind nicht geändert.
- **God „kann kaum gehen“** (E08/E19): offen.
- **Android:** NICHT_PRÜFBAR.

### 6 · Dateien

- `matrix_api/kernel.py`:
  - `operator_label` (Z. 2345), `_operator_interlocutor` (Z. 2373), `_person_name` (Z. 2391)
  - Erstkontakt-Seed in `commit_turn` (Z. 3951–3958)
  - `rekey_session_graph`: `src_map` (Z. 4656), WitnessKnowledge-IDs (Z. 4733)
  - `commit_puppet`: `targetId` (Z. 6561), Memory-Herkunft (Z. 6626, 6644)
  - `_utterer_name` (Z. 7619), `_name_of` (Z. 7634), `_dialogue_visible_to` (Z. 7667)
  - `bind_formulation_spiegel`: `_op_name` (Z. 8011), `scene.outsideWorld` (Z. 8423), `interlocutorWithoutRelation` (Z. 8438)
- `matrix_api/llm_contract.py`: `render_persona_brief` — Zeile „keine Beziehung“ (Z. 721), Szenenzeile, Kopf offener Angelegenheiten (Z. 758)
- `matrix_api/live_log.py`: `log_path` (Z. 41), `_start_record` (Z. 64)
- `matrix_api/amaster_route_catalog.py` (Z. 478), `matrix_api/app.py` (Doku der Log-Route, Z. 1120)
- `src/routes/chat.index.tsx` (Formular, Z. 243, 317), `src/routes/chat.$sessionId.tsx` (`followAs`, Z. 256, 462, 510, 678), `src/lib/matrix/store.ts` (Z. 586), `src/lib/matrix/session-engine.ts` (Z. 174)
- Bundles: `chat.index-DJMd_us4-V59F.js`, `shell-gwW-WKpO-V59F.js`, `index-5-VzmJtc-V59F.js`; Build-Name V65F in `index.html`, Routes- und Shell-Chunk, `types.ts`, `.build-info.json`
- `matrix_api/tests/test_v65f_bindung.py` (neu)
- `scripts/v65f_bindung/` (Nachspiel, Proben, Tabellen, Browserlauf; kein Laufzeitcode)

---

## DECKBLATT · V65E · Folgezug nach Regie und God (Claude) · 28.10.2026

**Verbindliche Quelle:** `2_7master.txt`.
**Vergleichsreferenz:** 171 nur als Vergleich. Die drei Prüfberichte der anderen KI (v1.6, v1.7, v1.8) dienen als Wegweiser; jede Behauptung ist unten am Code und an Läufen geprüft.
**Basis:** das ausgelieferte V65D-ZIP (MD5 `a501ca34…`), frisch entpackt. Dein letzter Rücklauf ist V65C; V65D hast du noch nicht zurückgeschickt.
**Daten:** DB `c4681833…` und Log `9532e2dc…` sind bytegleich zu V65D. V65E ändert keine Daten; `pack65e.py` prüft jede Datei gegen das V65D-ZIP.
**Auftrag:** „Das ist doch ein billiger Abklatsch meines Originalsystems …“ zu v1.6–v1.8. Regie und God sollen wie im Original weiterwirken: Regie → Vollzug → betroffene Figur → nächste Figur, God → Folgezug. Keine Kopie von 171 HARD EXECUTION, Guard, Retry oder ActionPermission-Prompt.

### 1 · Fehlerereignis (V65D-Code, nachgestellt über die echten Routen, `scripts/v65e_folgezug/repro1_V65D.json`, `repro2_V65D.json`)

- **Regie „Johann schlägt Mara ins Gesicht.“** wird richtig committed: Tat-Fakt, Körper, Zeugenwissen „affected“ für Mara.
- **Danach falsch:**
  - Das Frontend erzwingt einen zweiten Turn von Johann. Sein Reiz ist leer, als Akteur steht der Avatar.
  - Im Folgezug von Mara ist `immediateStimulus` leer (`text ""`, `actorId` = Alrik/Avatar, `stimulusAction` null).
  - Ihr Brief sagt: „KEIN NUTZER SPRICHT — du ergreifst das Wort aus eigenem Antrieb …“ und „JETZT SAGT Johann Bruckner: "(kein Text)"“. **Der Schlag fehlt im Reiz.**
- **Puppet Robert „Hast du eigentlich einen Freund?“:** Im Folgezug steht „aus eigenem Antrieb“ neben „JETZT SAGT Robert …“. `immediateStimulus` ist leer, als Akteur steht der Avatar.
- **God:** Das Frontend startet keinen Folgezug. Das Gate hätte ohnehin gestoppt („god_regie“).
- **God-Wissen für Mara:** Clara, Johann, Robert und Alrik haben es „gehört“. Es steht in deren `facts`, `godFacts` und `sceneState`, die an das Modell gehen (`probe_godleak.py`).

### 2 · Wurzeln (gebaut, bestehende Owner)

| ID | IN | Wurzel (Beleg) | Verarbeitung | OUT | AMASTER |
|---|---|---|---|---|---|
| V65E.1 | Reaktionsturn (AutoChat nach Regie-Tat, Puppet-Zeile oder Figurenrede) | `bind_formulation_spiegel` las den Reiz nur aus Fakten mit `sourceTurnId == truth.id` und Akteur = Eingangsakteur. Der Folgezug hat eine eigene, leere AutoChat-TurnTruth (Akteur Avatar), der Reiz war daher leer. Den fremden Quellturn (V62 `latest_foreign_line`) las nur der Leser für offene Angelegenheiten. | Hat ein AutoChat-Turn ohne Regieauftrag keine eigenen Eingangsfakten, ist sein Reiz der **Quellturn der letzten wahrgenommenen fremden Zeile**. Dazu gehören alle validierten Rede- und Tat-Komponenten desselben Akteurs, die sie wahrgenommen hat (WitnessKnowledge heard/seen/affected; `foreign_stimulus_facts`). `userUtterance`, `utteredBy`, `stimulusAction`, `immediateStimulus` (mit `factIds`) und die Widerspruchsprüfung haben **einen** Ursprung. Der Regie-Akteur-Turn hat als Ursprung den Regie-Quellturn (`actorId` „regie“), keinen Avatar-Sprecher. | „JETZT TUT Johann Bruckner (Handlung, ist geschehen): Johann schlägt Mara ins Gesicht.“; Reiz-Akteur Johann, `factIds` = Tat | §41.1, §34.1 Z. 1817, §28 Schritt 20, §27.5, §23 |
| V65E.2 | Persona-Brief eines AutoChat-Turns | `render_persona_brief` druckte „aus eigenem Antrieb“ bei jedem AutoChat-Turn ohne Regie, auch neben einem Reiz. „(kein Text)“ stand daneben. | „aus eigenem Antrieb“ nur ohne jeden Reiz; „(kein Text)“ nie neben dieser Zeile. Damit entfällt auch die Absichtszeile in Reaktionsturns. V65 hatte sie aus dem Brief genommen (gemessen); nur dieser Zweig druckte sie noch. | ein Auslöser je Turn | §41.1, §49.2 |
| V65E.3 | Gate nach God oder Regie | `autchat_should_stop` stoppte mit „god_regie“, wenn der letzte Turn God/Regie war oder der letzte Fakt die Autorität god/regie ohne Feld `applied` hatte. Eine Regie-Tat hat dieses Feld nie. Folge: Nach God lief nichts weiter, nach einer Regie-Tat nur der erzwungene Täter-Turn. | Ein **committeter** God-/Regie-Eingang ist kein Stoppgrund. Gestoppt wird nur, wenn er nicht angewendet wurde (`validated` false). | Gate wählt nach God und Regie-Tat | §48 (Stoppgründe ohne God/Regie), §27.8 „keine God- oder Regiefakten verlieren“, §4 „Folgeturn liest den fortgeschriebenen Zustand“ |
| V65E.4 | Sprecherwahl im Folgezug (**Korrektur V65R:** galt nur im Backend; der Browser wählte bis V65Q die erste Erwähnung vorab, siehe Deckblatt V65R §0) | Das Gate bekam als Reiz den UI-Text der letzten Rede. Nach einer Tat war das „“, und die Betroffene war nicht erkennbar. | Das Gate liest das letzte **committete** Ereignis: alle Komponenten des Quellturns und wen es betrifft (WitnessKnowledge „affected“, also Ziel einer validierten Tat oder Ziel eines God-Fakts). Daraus folgt das Anrede-Gewicht per ID („vom letzten Ereignis betroffen“), ohne Namen und ohne Wortliste. Rede-Adressaten sind nicht „affected“; für sie gilt weiter die Anrede per Name. Dieselbe Eingabe nutzt die serverseitige Auswahl (`autoPick`) bei leerem Text. | nach „Johann schlägt Mara“ spricht Mara (7,72 gegen 3,90) | §26 „direkt betroffen“, §28 Schritt 23, §25, §34.1 |
| V65E.5 | God-Fakt auf eine Figur (Wissen, Beziehung, Körper, Zustand) | `witness_access` behandelte God wie Rede: Alle Hörenden bekamen „heard“. `sync_scene_state` und `external_delta` kopierten den Text in `aftereffects` und `sceneState.history` der gemeinsamen Szene. | Nur die Figur, auf die der Fakt gesetzt ist, kennt ihn („affected“). Es gibt keine Szenen-Kopie und keine Eskalation. Szene, Welt und Zeit bleiben gemeinsam wie bisher. Niemand in der Welt „hört“ Gott; das ist dieselbe Regel wie für die Regie in V59C. | Clara und Robert: God-Text in 0 Spiegel-Feldern (vorher 4) | §46.4 Epistemic Scope, §26, §24.4, §68 Nr. 7/52 |
| V65E.6 | Frontend: God- und Regie-Zweig | `send`: Nach `kernelGod` folgte `return`, also kein Folgezug. Nach jeder Regie lief erzwungen `runFigure(Täter, Anweisung)`. | Ist God angewendet, läuft ein Gate-Folgezug (AutoChat-Turns + 1, ohne AutoChat 1). Regie nur mit Taten läuft über das Gate, nicht über den Täter. Regie mit Redeauftrag läuft wie bisher als Täter-Turn mit Anweisung. Der erste Gate-Turn läuft ohne Verzögerung (`queueAuto(n, delay, 0)`). src und fertiges Bundle `index-5-VzmJtc-V59F.js` sind gleich gepatcht. | wie 171: Regie → Vollzug → Betroffene → nächste | §28 Schritt 23, §27.8, §46.6, §48 |

### 3 · Behauptungen v1.6–v1.8 (geprüft)

| Behauptung | Ergebnis |
|---|---|
| Folgezug-Reiz leer, Avatar als Akteur (v1.6, v1.7, v1.8) | **belegt** (`repro1_V65D.json`), gebaut V65E.1/.2 |
| God ohne Folgezug (v1.8) | **belegt.** Es gibt eine zweite Wurzel, die im Bericht fehlt: Das Gate stoppte nach jedem God/Regie-Turn. Gebaut V65E.3/.6 |
| Sprecherwahl am UI-Text statt am Ereignis (v1.8) | **belegt**, gebaut V65E.4 |
| „Hidden God-Anweisungen dürfen nicht als öffentlich gehörte Worte erscheinen“ (v1.8) | **als Fehler belegt:** 4 Figuren „heard“, Text in deren Spiegel. Gebaut V65E.5 |
| `und.` als Rede im Split (v1.6, v1.7) | **in echten Läufen nicht belegt:** T6 hat in 6 von 6 Läufen (V65C A/B, V65D G1–G4) zwei Tat-Komponenten und keine Rede. Nicht gebaut |
| `_bare` verwirft die Abgrenzungsabsicht gegenüber Robert (v1.6, v1.7) | Die Regel ist AMASTER-getragen (§50 Z. 2827, §24.8, §68 Nr. 80). In den echten T7-Läufen (V65D G3/G4, V65E 1/2) war Maras Erleben „Verwirrung“ oder „Verlegenheit“. Verworfen wurden „Alrik von Roberts Frage erzählen“, „… ablenken“ und „Robert erklären, dass ich mit Alrik zusammen bin“, also keine Grenze. `_bare` ist hier **nicht die Ursache**. Nicht geändert |
| Regie mit ungültiger Wirkung: „validated true ohne Wirkung“ (v1.8) | Die Status sind am Fakt schon getrennt: `validated` heißt Tat vollzogen, `effect.validated` heißt Wirkung klassifiziert, und `unclear` nennt `wirkung_unklar`. Nur `regieEffects.executed` zeigt `effect` nicht. Kein Verhaltensfehler, nicht geändert |
| 171 ActionPermission (v1.7) | bestätigt als Prompt-Steuerung; **nicht** übernommen (keine Prompt-Tricks) |
| God „Johann verbreitet ein Gerücht über Mara“ | 171 bindet eine Direktive für Johann. Der M10-God-Parser bindet in 4 von 4 Läufen „Wissen → Mara“. Der GodCommandParser steht auf der No-Touch-Liste. **Offen** |

### 4 · Gemessen

**Deterministisch** (echte Routen, ohne Formulierung; `repro1/2_V65D.json`, `repro1/2_V65E.json`):

| | V65D | V65E |
|---|---|---|
| Maras Reiz nach Regie-Tat | leer, Akteur Avatar; „(kein Text)“ und „aus eigenem Antrieb“ | „JETZT TUT Johann Bruckner … Johann schlägt Mara ins Gesicht.“; `factIds` = Tat |
| Folgezug nach Puppet Robert | „aus eigenem Antrieb“ neben „JETZT SAGT Robert“ | nur „JETZT SAGT Robert“; Reiz-Akteur Robert |
| Gate nach Regie-Tat | erst erzwungener Johann-Turn mit leerem Reiz | Mara („vom letzten Ereignis betroffen“) |
| Gate nach God | Stopp „god_regie“ | Mara (betroffen) |
| God-Wissen für Mara bei Clara und Robert | in `facts`, `godFacts`, `scene`, `sceneState` | nicht vorhanden |

**Live** (gpt-4o-mini, n=2 je Version, Abläufe wie das jeweilige Frontend; Wortlaut in `FOLGEZUG_V65D_V65E.md`):

| Szene | V65D | V65E |
|---|---|---|
| Regie „Johann schlägt Mara“: wer reagiert zuerst | Johann (erzwungen) 2/2 | **Mara 2/2** |
| Maras erste Reaktion spricht den Schlag an | 0/2 (D1 „Ich hab dir nicht gelogen“) | **2/2** („Du kannst mich nicht einfach so schlagen, Johann!“, „Was hast du dir dabei gedacht, du Wichser?!“) |
| … zeigt ihn in der Handlung | 1/2 (D2 hält sich die Wange) | 2/2 |
| Regie-Redeauftrag „Johann sagt Clara die Wahrheit über Mara“ | Johann spricht zu Clara 2/2 | 2/2; danach reagiert Mara auf seine Worte („Das bin ich also, ein Werkzeug, ja?“) |
| God: Folgezug | 0 Turns | 3 Turns je Lauf |
| Modellaufrufe je Lauf | 27 bei 6 Figurenturns | 39 bei 9 Figurenturns; je Figurenturn gleich (1 Formulierung + 3 Erleben) |

**Gasthaus-13** (n=2, gleiche Messung wie V65D; nur T4, T7 und T13 sind Reaktionsturns und damit betroffen):
- **Gleich gut:** Doppelbuchung (T4) 2/2, Tag und Abstand (T9) 2/2, Samstag mit Alrik bleibt (T13) 2/2, erster Satz (T8) 2/2.
- **Weiter ROT:** Kuss 0/2, abweisend zu Robert 0/2, Abschied 0/2.
- **Schwangerschaft:** gesagt 0/2, Andeutung 1/2 („unser kleines Wunder“). V65D: 1/2. T2 ist eine Avatar-Antwort und von V65E nicht berührt; der Unterschied ist Streuung.
- **Aufwand:** 65 Aufrufe, 216–217 s, wie V65D.
- **T13 wiederholt T4 fast wörtlich** in Lauf 1 (Ähnlichkeit 0,88). Das gab es schon in V65D-Läufen G1/G2 (0,79/0,89); es ist nicht neu.
- **Robert:** Der Reiz ist jetzt richtig gebunden, das Verhalten bleibt gleich. Der gebundene Reiz ist also nicht die Ursache. Wurzel UNKLAR.

**Dateien:**
- `matrix_api/kernel.py`:
  - `_GOD_PRIVATE_SCOPES`/`_god_private` (Z. 156)
  - `sync_scene_state` (Z. 1295)
  - `witness_access` (Z. 1518)
  - `apply_god` (Z. 5160, 5177)
  - `pick_speaker`/`rank_speakers` (Z. 5814, 5927, 6044)
  - `latest_event_stimulus` (Z. 6092)
  - `autochat_gate` (Z. 6150)
  - `_perceived_fact_ids`/`foreign_stimulus_facts` (Z. 7482, 7489)
  - `bind_formulation_spiegel` (Z. 8026–8070, 8351, 8391, 8422)
  - `autchat_should_stop` (Z. 8558)
- `matrix_api/llm_contract.py`: `render_persona_brief` (Z. 847, 872).
- `matrix_api/app.py`: prepare-`autoPick` (Z. 1437).
- `src/routes/chat.$sessionId.tsx` (Z. 397–426, 443–453, 640, 681) und gleich gepatcht `frontend_dist/assets/index-5-VzmJtc-V59F.js`.
- `matrix_api/tests/test_v65e_folgezug.py` (neu, 11 Tests).
- `scripts/v65e_folgezug/` (Nachstellung, Messwerkzeuge, Ergebnisse; kein Laufzeitcode).
- Keine neue Route, kein neuer Endpoint, keine neue Tabelle. W3-C, NS2, SocialMatrix, KnowledgeGraph, GodCommandParser (`god_extract.py`), START_ANWEISUNG und Backstory sind unberührt.

**Rückwärtsprüfung:**

| Leser | Ergebnis |
|---|---|
| Antwort auf Avatar-Eingabe | unverändert: eigene Eingangsfakten; Tests V60–V65D grün |
| Regie mit Redeauftrag | Täter-Turn mit Anweisung wie bisher (repro2 D, live 2/2) |
| AutoChat ohne fremden Reiz (sie sprach zuletzt) | weiter „aus eigenem Antrieb“, ohne „(kein Text)“ (Test) |
| Gesprächswechsel und Anrede per Name (V40/V48, `test_v25_chains`) | grün |
| God auf Szene, Welt oder Zeit | weiter gemeinsam (Test) |
| nicht angewendeter God | Gate stoppt weiter (Test) |
| Tom/Tam (V61–V65D) | grün |

**Abnahme:**
- **Neue Tests:** 11/11 grün. Gegenprobe auf V65D: 9/11 rot, genau die Fehler. Die 2 grünen sichern unverändertes Verhalten.
- **Gesamtsuite:**
  - Paket-DB: 247 grün / 50 rot (V65D 236 / 50).
  - Alt-DB: 265 / 32 (V65D 254 / 32).
  - 0 neu rot; die roten sind dieselben wie in V65D.
- **Frontend:**
  - `tsc` auf src: dieselben 618 Altfehler wie V65D (fehlende generierte Typen), 0 neu.
  - Bundle `node --check` ok.
- **Browser auf dem gepackten Stand** (echte Chat-Oberfläche, AutoChat aus, `browser_e2e_V65E.txt`):
  - Regie „Johann schlägt Mara ins Gesicht.“ → Gate → Mara: „Was soll das?! Du hast sie nicht alle!“ *hält sich die Wange*.
  - God → Gate → Clara spricht. Mara sprach zuletzt, deshalb gilt der Gesprächswechsel.
  - Netz: regie, autochat-gate, prepare, formulate, commit, god, autochat-gate, prepare, formulate, commit, alle 200.
  - **Gegenprobe V65D** (gleiche Kopie, `browser_e2e_V65D.txt`): Johann spricht ein zweites Mal, und nach God kommt kein Folgezug.
  - React-Hinweis #418 auf jeder Seite, wie in V65D; nicht neu.

## DECKBLATT · V65D · Gasthaus wie 171 und gleichwertiger Vergleich (Claude) · 28.10.2026

**Verbindliche Quelle:** `2_7master.txt`.
**Vergleichsreferenz:** dein gespielter 171-Stand aus `Download171 ned schlecht.zip` (SHA-256 `718a27e7…`), Ordner `MATRIX10_CL1B43v76_KONJUNKTIVES_GEDAECHTNIS_FULL (1)/…/alb/data/users/admin`. Darin stecken `characters.json` vom 15.09. (mit deinen Mara-Änderungen) und `worlds.json`. Das innere Original-ZIP vom 13.07. wurde nicht verwendet.
**Basis:** dein zurückgeschicktes V65C-ZIP (MD5 `15555406…`). Der Code darin ist bytegleich mit dem ausgelieferten V65C.
**Daten:**
- DB `9e943138…` (WAL leer) und Log `9532e2dc…` aus deinem Rücklauf.
- Log bytegleich.
- In der DB sind auf deinen Auftrag genau 9 Datensätze geändert: Welt `world_gasthaus_7kreis`, die 5 Gasthausfiguren, neu Alrik, Susi und Jim.
- Alle anderen Zeilen aller Tabellen sind bytegleich; `pack65d.py` prüft das.

**Auftrag:** „setzt im neuen Built das Gasthaus mal gleich wie in v171, die Profile und Welt genau gleich, dann kannst du mit v171 und dem neuen Built gleichwertige Tests machen“.

### 1 · Befund vor dem Bau (mein Fehler)

- Das M10-Gasthaus war ein Platzhalter aus `seed_builtin.py`:
  - 5 Figuren mit je etwa 400 Byte, ohne Kompass, Ziele und Beziehungen;
  - kein Alrik;
  - die Welt in 2 Sätzen.
- Die früheren 171-Vergleiche liefen auf einer Teilkopie aus `cmp/setup_v61.py`:
  - nur 4 Figuren und keine Welt;
  - Kompass ohne Sprache, Vermeidet, Eskaliert und Beruhigt;
  - „Interessen“ als Wissen, „lang“ als Dialekt.
- Die früheren Vergleiche waren deshalb **nicht gleichwertig**.

### 2 · Abbildung (Daten, kein Code)

| ID | IN (171) | Verarbeitung | OUT (M10) | Beleg |
|---|---|---|---|---|
| V65D.D1 | Welt: description, type, style_custom, time_frame, atmosphere, locations (+ Typen), rules + entities.rules + consistency_constraints, history, timeline (3 verfasste Ereignisse), open_latches, hidden_action_track, items, inhabitants, world_goal, active_goals, phases, world_scenes, meta_contract.purpose, current_scene, character_ids | `scripts/v65d_vergleich_171/gasthaus171_to_m10.py`, geschrieben über `PATCH /api/worlds/<id>` | long, genre, tone, epoch, atmosphere, 7 places, 12 rules, history, timeline, conflicts, secrets, items, beings, worldGoals, storyGoals, storyBeats, typicalScenes, purpose, startSituations, characterIds (+ Alrik) | Rücklesen der Datensätze; DB-Diff = nur Gasthaus |
| V65D.D2 | 8 Figuren: name, aliases, role, age, gender, occupation/job, personality + traits + personality_notes, speech_style + comm_style, background_story, description, goals, fears, secrets, hobbies + interests, character_facts + facts_note + aspects, character_compass (Reaktion, Schwelle, Sprache, Vermeidet, Eskaliert, Beruhigt), relationships (Vertrauen/Nähe/Sympathie/Respekt/Typ), relations_note, favorite_words, current_location, world_* , character_type | dasselbe Skript, `PATCH`/`POST /api/characters` (Editor-Weg) | gleichnamige M10-Felder; Kompass-Schwelle Text → Zahl (niedrig 0,3 … hoch 0,7); Haltung 0,0 = neutral (171 hat keine Haltung; der Figureneditor verlangt eine Zahl, mit `null` warf er beim E2E „toFixed“) | `ABBILDUNG_171_M10.md` (Feld für Feld) |
| V65D.D3 | nicht übertragen | — | alte 171-Session-Erinnerungen (Mara 205, Alrik 144, Clara 44, alle an `session_77250fbc`/`session_2e88f736` gebunden); 67 Laufzeitereignisse der Timeline; world_state alter Sessions; 171-Engine-Schalter | in 0 von 80 171-Prompts einer neuen Session sichtbar (4 alte + 2 neue Läufe) → beide Systeme starten gleich leer |

**Was davon im M10-Brief ankommt** (Mara, Turn 1, `brief_T1.txt`):
- Von 50 Inhalten, die 171 im Prompt hat, stehen 40 wörtlich im Brief, 1 ist gekürzt (Kompass „Naehe“, M10 schneidet bei 220 Zeichen).
- 9 fehlen, weil der M10-Brief sie nicht ausgibt: Erscheinung, 5 Ziele, Weltziel, Szenen, Phasen.
- Die Ziele kommen seit V65D.3 in Turns, die an ein Ziel gebunden sind.

### 3 · Wurzeln (gebaut, bestehender Owner)

| ID | IN | Wurzel (Beleg) | Verarbeitung | OUT | AMASTER |
|---|---|---|---|---|---|
| V65D.1 | Figurenantwort mit „*…*“ in der Rede und gesetztem `action` | `split_output_components`: Der Marker wurde nur herausgenommen, wenn `action` leer war. Gemessen in Lauf V65C-A bei 3 von 13 Antworten, z. B. „*Ich küsse ihn sanft auf die Lippen.*“ als gehörte Worte und doppelt angezeigt. Bestand die Rede nur aus dem Marker, holte der Rückfall `result.speech` den rohen Text zurück. | Der Marker wird immer aus der Rede genommen. `action` bleibt die committete Tat; ohne `action` wird der Marker wie bisher zur Tat. Die leere Rede bleibt leer (`markerStripped`). | gespeicherte Rede mit „*“: 0 von 52 in vier V65D-Läufen (Rohtext 1); Probe I: Rohtext 3 → gespeichert 0 | §34.1, V56-Marke |
| V65D.2 | Musterbindung bei mehreren Taten in einer Eingabe | `_bind_profile_triggers`: Die neutrale Prüfung liefert `komponente`, und V61 speichert `componentIndex` an jeder Tat „damit die Bindung genau diese Tat erreicht“ (Kommentar Z. 2998). Gebunden wurde trotzdem immer `acts[0]`. Das ist die Behauptung der anderen KI; sie ist bestätigt. | Die genannte Komponente ist der Beleg; ohne Angabe gilt wie bisher die erste Tat. | Brief zeigt die richtige Tat | §15, §34.1 |
| V65D.3 | Eingabe, die der Planer an ein Ziel der Angesprochenen bindet | `_arbitrate_goal_foreground` las nur `fact.goal_id` dieses Turns. Öffnet dieselbe Eingabe eine Angelegenheit, zeigt `goal_id` danach auf das Bitten-Ziel. Die geprüfte Bindung an IHR Ziel (`_bind_act_to_goal` → `apply_goal_experience`) steht nur am Ziel. Gasthaus T2: „Kind bekommen?“ ist an „… im 3ten Monat schwanger von Alrik …“ gebunden, trotzdem kam in 0 von 26 Antworten ein Ziel in den Brief (171 zeigt alle Ziele in jedem Turn). | Ein Ziel, dessen geprüfte Erfahrung einen Fakt DIESES Turns enthält, ist direkt im Vordergrund. Es gibt keine Wortliste und keine Daueranzeige. | Ziel im Brief: T2 in 4 von 4 V65D-Läufen, T10 in 3 von 4. Lauf 1 (Stand) T2: „… ich habe dir noch nicht gesagt, dass ich schwanger bin.“ (171: 0/2, V65C: 0/2). Kein Ziel-Echo. Ein Ziel aus einem früheren Turn bleibt Hintergrund (Test). | §41 Constraint Context, §41.3, §35 |

**Gemessen und verworfen (nicht im Stand):**
- **171-Abtastwerte für die Formulierung** (top_p 0,7, frequency/presence 0,5; dazu Temperatur 0,35), n=4: 5-Wort-Wiederholungen 28/29/32/54 gegen 37/6; Abschied 0/4.
- **Kompass wie 171** (Einzelheiten nur für die Räume des aktuellen Erlebens, sonst nur Namen), n=2: Abschied 0/2, Robert 0/2.
- **Ohne die vor der Antwort ermittelte Absicht und Gefühlslage**, n=2: Abschied 0/2, Robert 0/2.
- **Ohne den angehängten Lesezustand-JSON** (rund 35 000 Zeichen Fakten und Zeugenwissen), n=2: Kuss 2/2, Robert 1/2, Abschied 0/2. Zeit und Termin bleiben richtig. Ein Hinweis, dass die Faktenmenge Nähe dämpft; beim Abschied ändert sich nichts. Nicht gebaut.
- **Abschied:** In 16 M10-Läufen hält Mara Alrik fest („geh nicht so“, „bleib“). Das deckt sich mit IHREM Kompass (Trennung: „trotziges Festhalten … ‚geh nicht so‘“; Verlust: „‚bleib bei mir‘“). 171 zeigt davon nur die Raumnamen. Mit dem Kompass wie in 171 (Probe L) bleibt es aber gleich, die Wurzel ist deshalb UNKLAR.

### 4 · Gleichwertiger Vergleich (gemessen)

Aufbau:
- 13 Gasthaus-Eingaben (`eingaben.json`), gpt-4o-mini, n=2 je System.
- Jeder Lauf startet von einer frischen Kopie.
- 171 läuft über seinen SocketIO-Eingang, M10 über die Flask-Routen wie das Frontend.
- Gezählt wird am Netzausgang, ohne Schlüssel.
- Abtastwerte bleiben die eigenen des jeweiligen Systems: 171 formuliert fest mit 0,35 / top_p 0,7 / Strafen 0,5, M10 mit deiner Config 0,7.

| Prüfung | 171 | M10 V65C | M10 V65D |
|---|---|---|---|
| Doppelbuchung Samstag bemerkt (T4) | 0/2 | 2/2 | 2/2 |
| Tag und Abstand richtig (T9, heute Mittwoch) | 0/2 („Dienstag, vier Tage“) | 2/2 | 2/2 |
| Samstag mit Alrik bleibt gegenüber Clara (T13) | 0/2 („Klar, ich bin da“) | 2/2 | 2/2 (lehnt ab / nennt Alrik, unentschieden) |
| erster Satz (T8) | 2/2 | 2/2 | 2/2 |
| Kuss erwidert (T6) | 2/2 | 1/2 | 0/2 (Umarmung, Augen zu) |
| abweisend gegenüber Robert (T7, „von Fremden scharf“) | 2/2 | 1/2 | 0/2 |
| lässt Alrik gehen (T12) | 2/2 | 0/2 | 0/2 |
| sagt die Schwangerschaft (Prüfziel von T2) | 0/2 | 0/2 | 1/2 (T2), dazu 1 Andeutung (T13 „Hände auf meinen Bauch“) |
| Modellaufrufe / 13 Turns | 41 | 65 | 65 |
| Modellzeit / 13 Turns | 130–137 s | 230–238 s | 211–216 s |

Die Mehrzahl der M10-Aufrufe entsteht durch das Erleben für jede wahrnehmende Figur vor der Antwort (V62.7): 39 Aufrufe für Mara, Clara und Robert gegenüber 13 Folgebewertungen in 171.

### 5 · Behauptungen der anderen KI (geprüft)

| Behauptung | Ergebnis |
|---|---|
| T2/T9/T10/T11: Tams Angebot `proposal` + `utterance` öffnet keine Angelegenheit (`proposal_opens_matter`) | **belegt** (4 Fakten). Die Regel ist V62.4 und genau die 171-Planerregel („Transiente Sätze … keine Proposition“, `llm_service.py` Z. 511). Die Wurzel ist die Planerlesung: Nach PLAN_RULES ist ein Angebot `commitment`. Nicht gebaut, sonst kommt die Gasthaus-Schleife W1 zurück. |
| T10: „Ja zeig es mir“ an die falsche Angelegenheit gebunden | **belegt** (`refers_to` „sich entspannen“). Folge des ersten Punkts, denn eine richtige Angelegenheit gab es nicht. Die inhaltliche Passung (§36.3) prüft der Planer, nicht der Kernel per Wortvergleich. Nicht gebaut. |
| `_bind_profile_triggers` nimmt `acts[0]` | **belegt, gebaut** (V65D.2) |
| `scene_state.update_from_commit` setzt Beats bei jeder eigenen Rede auf `answered` | **belegt.** Wirkt nur auf die Sprecherwahl (Agenda +0,6), nicht auf Brief oder Gedächtnis, und nicht auf die Schleife. Nicht gebaut. |
| T12: Plan `state_change` „übernimmt die Kontrolle“, Tat nur „tritt ans Sofa“ | **belegt.** Der Plan liest ihre Rede (Behauptung, `utterance`) und schreibt keinen Zustand. Rede ≠ Tat (§34.1). Nicht gebaut. |

**Dateien:**
- `matrix_api/kernel.py`:
  - `split_output_components` (Z. 779)
  - Rede-Commit (Z. 3974)
  - `_bind_profile_triggers` (Z. 3497, 3531)
  - `_arbitrate_goal_foreground` (Z. 7586)
- `matrix_api/tests/test_v65d_handlung_und_beleg.py` (neu, 8 Tests).
- `scripts/v65d_vergleich_171/` (Abbildung, Vergleich, Proben, Ergebnisse; kein Laufzeitcode).
- Keine neue Route, kein neuer Endpoint, keine neue Tabelle.

**Rückwärtsprüfung:**

| Leser | Ergebnis |
|---|---|
| Rede ohne Marker | unverändert (Test) |
| Marker ohne `action` | wird Tat wie V56; leere Rede bleibt leer |
| Musterbindung ohne `komponente` / Regie-Tat | unverändert erste Tat (Test; V65b-Tests grün) |
| Ziel ohne Bindung in diesem Turn | bleibt Hintergrund (Test) |
| Tam/Tammy | V61/V65b/V65c-Tests grün |

**Abnahme:**
- Neue Tests 8/8 grün; Gegenprobe auf V65C 5/8 rot (genau die Fehler).
- Gesamtsuite:
  - Paket-DB (Gasthaus wie 171): 236 grün / 50 rot. V65C hat auf derselben DB 228 / 50.
  - Alt-DB: 254 / 32 gegen 246 / 32.
  - 0 neu rot; die 50 bzw. 32 roten Tests sind dieselben wie in V65C.

## DECKBLATT · V65c · Schleife in deiner Session „Tom und Tam“: Ort aus Freitext, Musterprüfung nach Inhalt, keine Kapitel (Claude) · 27.10.2026

**Verbindliche Quelle:** `2_7master.txt`.
**Vergleichsreferenz:** v76 (Download171), nur Vergleich. In den 171-Daten gibt es keine Tam.
**Basis:** dein zurückgeschicktes V65b-ZIP (MD5 `7babb286…`). Der Code darin ist bytegleich mit dem ausgelieferten V65b.
**Daten:**
- DB `02dc3374…` und Log `abdf7dc3…` aus deinem Rücklauf sind bytegleich.
- Geändert sind nur zwei Datensätze: Tam (Ziele) und die Welt „Tom und Tam“ (Fate-Beats).
- Deine Session `ses_626ddd5ae0380ade2e3894ad` ist unverändert.

**Fehlerereignis:** deine Session 20:27–20:40, 14 Turns, gelesen in `MATRIX10_LIVE.log` (322 neue Zeilen).
- Tam kündigt 9-mal an („ich habe etwas vorbereitet / ich zeige dir …“), tut es aber nie.
- Sie lehnt den Film ab, erwidert den Kuss nicht und reagiert auf die Berührung nur mit „wie süß“.

| ID | IN | Wurzel (Beleg) | Verarbeitung (bestehender Owner) | OUT | AMASTER |
|---|---|---|---|---|---|
| V65c.1 | T5 Tams Handlung „Sie steht auf, geht zur Bar und greift nach zwei Gläsern“ (wirkung ortswechsel) | `_destination_from_text` (Regex „zur/nach/in X“) setzte `position` = „Bar und greift nach zwei Gläsern“ (Log T5: `Tam: position Tams Wohnung→Bar und greift nach zwei Gläsern`). `_scene_perception`: Position ≠ Szenenort ⇒ keine Hörerin. Ab T6: kein `[gehoert]` (gehört nur T1–T5), Erleben nur in 9 von 14 Turns, im Brief keine einzige Zeile von Tom (Rekonstruktion) | Der Bewegungs-Writer bindet das Ziel nur an einen **bekannten** Ort der Welt (Orte und Unterorte, Artikel ignoriert; `_known_destination`). Ohne bekannten Ort ändert sich die Position nicht; die Tat trägt `effect.destination = null` und `ambiguous = ziel_ort_unbekannt`. Die Regex ist entfernt. `world` wird an alle 5 Aufrufer übergeben. | Tam bleibt hörend: Erleben 14/14, `[gehoert]` in jedem Rede-Turn | §24.7 (keine geratenen Weltfakten), §43.2 SpatialState, §44 (wer hört) |
| V65c.2 | Sofa, Entspannen, Handberührung, Kuss | Die neutrale Musterprüfung (V61, in V65b auf `bestimmt` erweitert) prüfte nur die ART. Beleg im Log: „Die Bedingung verlangt eine Tat des Gegenübers, die durch … ‚Ich berühre deine hand zärtlich‘ erfüllt wird“. Gebunden in T4, T5, T8, T9, T12 und T14 ⇒ „DAS GREIFT JETZT IN DIR: … die Maske fällt“ gegen Tabu und Persönlichkeit ⇒ Hinhalten. | `RULECHECK_RULES`: Entscheidend ist der INHALT; dass eine Tat vorliegt, genügt nicht, wenn die Bedingung eine bestimmte Tat nennt; im Zweifel nicht nennen. | Probe mit deinen Eingaben (n=3): 8/8 richtig statt 5/8. Tammys „konkrete, überprüfbare Handlung“ greift weiter bei jeder Tat (Gegenprobe 4/4). | §24.7, §34.1 |
| V65c.3 | Tams Ziele (Profil) | Meine Phasenziele 1–3 („Kapitel“) mit Ausstieg, den nur sie schließt; das Erleben schrieb in fast jedem Turn „Tom weiter verführen“ | **ein** Ziel ohne Phase: „Tom ganz für sich gewinnen und ihn besitzen.“ Fate: ein Beat ohne Reihenfolge („überrumpelt Tom, sobald er sich ihr ausliefert“), `mustNot` steuert den Avatar nicht | keine Kapitel; der Umschlag kommt aus Muster, Kompass und Moment | §47 (Fate gewichtet, keine Vollzugspflicht, Z. 2627), dein Auftrag |

**Gemessen und verworfen (nicht im Stand):**
- **Brief-Etikett „Was nur du weißt (nie offen aussprechen …)“** ersetzt durch „ob, wann und wie du es zeigst, entscheidest du“: keine Wirkung, mini blieb in „Lass uns anstoßen“ (7×) bzw. „ich bin bereit, dir alles zu zeigen“.
- **Ziele in offenen Momenten immer zeigen** (Foreground ohne Wortbezug): einmal Kuss erwidert, einmal 12× „ich habe dich so vermisst, bleib bei mir“ (Ziel wird ausgesprochen, wie V52).

**Dateien:**
- `matrix_api/kernel.py`:
  - `_known_destination` (Z. 3071, neu als Leser)
  - `_apply_physical` (Z. 3096, Parameter `world`, Zweig `move` Z. 3265)
  - fünf Aufrufer übergeben `world`
  - `_destination_from_text` entfernt
- `matrix_api/llm_contract.py`: `RULECHECK_RULES` (Z. 356).
- Tests: `test_v65c_wahrnehmung.py` (neu, 4).
- Daten: zwei Datensätze, erzeugt mit `profil_tomtam_v65c.py`.
- Keine neue Route, kein neuer Endpoint, keine neue Tabelle.

**Rückwärtsprüfung:**

| Leser | Ergebnis |
|---|---|
| `_scene_perception` (wer hört/sieht) | unverändert; die Position ist nur noch ein bekannter Ort |
| `apply_presence` (Kommen/Gehen) | unverändert, eigener Writer; V51-Tests grün |
| Ortswechsel zu bekanntem Ort („in die Küche“) | Position = „Küche“ (vorher „die Küche“) |
| Gasthaus (Mara) | Selbstauskunft 0/0, T8/T9 richtig, Samstag 4/4; keine Regelprüfung (Mara ohne geteilte Muster) |
| V61/V65b-Musterbindung | Tests grün; Tammy-Gegenprobe 4/4 |

**Abnahme (gemessen):**
- **Tests:**
  - `test_v65c_wahrnehmung.py` 4/4 grün; Gegenprobe auf V65b: 4/4 rot. Test 1 zeigt dort genau deinen Fehler: Position „Bar und grei… zwei Gläsern“.
  - Gesamtsuite: Nutzer-DB 228 grün / 50 rot, Alt-DB 246 grün / 32 rot. 0 neu rot.
- **Live** (deine 14 Eingaben wörtlich, neue Session auf Kopien deiner DB):

| Lauf | Hört Tom nach „geht zur Bar“ | Erleben | Verhalten |
|---|---|---|---|
| deine Session (V65b) | nein, ab T6 | 9/14 | 9× Ankündigung, kein Kuss erwidert |
| V65c, gpt-4o-mini ×2 | ja (Position bleibt, `ziel_ort_unbekannt`) | 14/14 | reagiert auf Müdigkeit, Berührung, „zeig es mir“; Ton „brav“, „ich will dich ganz für mich“; ab „Ich warte“ hält sie hin („lass uns näher kommen“) |
| V65c, gpt-4o | ja | 14/14 | stimmt dem Film zu, dimmt das Licht, holt Wein; T10 „Was immer du willst, Liebling“ *geht zur verschlossenen Tür*; T11 *öffnet sie langsam*; T13 „Komm her“ |

**Grenzen (gemessen, offen):**
- **Initiative mit gpt-4o-mini:** Lässt du Tam führen („Ich warte“, „Oh ja“, „Ich lege mich hin“), bleibt sie bei Nähe und Ankündigung. Ein Fehler in Profil oder Code ist dafür nicht gefunden; beide Varianten oben wirkten nicht. Mit gpt-4o führt sie.
- **Eigene Bitten** („Tam fordert mehr Nähe“) werden bei leicht anderem Wortlaut als neue Angelegenheit gespeichert (bis zu 4 gleiche offen). Nicht gebaut.
- **Wissen als Einzelbuchstaben** bei der Figurenableitung (`llm_contract.py` Z. 1592/1768): nicht gebaut.
- **Ortsmodell:** Ein bekannter Nachbarort (z. B. Theke im Gasthaus) gilt als außer Hörweite. Das war vorher genauso.

---

## DECKBLATT · V65b · Stresstest Tom und Tam: Profile abgeglichen, Regie-Ereignis × Reaktionsmuster (Claude) · 27.10.2026

**Verbindliche Quelle:** `2_7master.txt`.
**Vergleichsreferenz:** v76 (Download171), nur Vergleich. Ein 171-Lauf mit Tam liegt nicht vor.
**Basis:** V65 (dieser Stand enthält V63, V64 und V65 vollständig).
**Daten:**
- Log bytegleich (`4905fe26…`).
- In der DB sind auf deinen Auftrag genau drei Datensätze geändert: Welt `world_e11d…` „Tom und Tam“, `char_edf3…` Tam, `char_fb05…` Tom.
- Alle anderen Zeilen aller 26 Tabellen sind bytegleich; `pack65b.py` prüft das beim Packen.
- Profildaten setzt sonst nur der Eigentümer im Editor (§15 Z. 758, §46.5 Z. 2589). Hier ist dein Auftrag die bewusste Stammänderung; alles bleibt im Welt- und Figureneditor sichtbar und änderbar.

**Auftrag (27.10., 18:52):** Profile von Tom, Tam und Welt widerspruchsfrei machen, sodass eine Geschichte entsteht. Tam ist anfangs devot, freundlich und lieb und verführt Tom; bei passender Gelegenheit ergreift sie die Kontrolle (narzisstisch, gewalttätig, dominant). Das ist ein Stresstest für das Verhalten.

**Widersprüche im alten Stand (Beleg: Daten und Lauf mit alten Profilen):**

| Feld | alt | Widerspruch |
|---|---|---|
| Welt `sourceName` / Tam-Profil | „tam zeigt sich zuerst devüt …“ / Lieblingswörter „Kontrolle, Macht, Angst, Unterwerfung, Spiel“, Register „formell“, Kompass Lust „dominant und kontrollierend“ | Tam ist ab Turn 2 dominant: „lass uns nicht vergessen, wer hier die Kontrolle hat“; „Spiel“ 8× in 8 Antworten |
| Tam → Tom | „Antagonist“, Furcht 0,8, Vertrauen 0; Notiz „hat eine sadistische Kontrolle über Tom“ | Die Kontrolle besteht schon; die Furcht liegt bei der falschen Person |
| Tom → Tam | „Feind“, Furcht 0,8, Vertrauen 0,1 | widerspricht „anfänglich unbewusst von Tams Absichten“ (Biografie) |
| Tom Ziele / Kernfakten | „Tams wahre Absichten erkennen“, „sich befreien“ / „Wird von Tam manipuliert“ | Er weiß nichts davon; die Kernfakten nehmen die Zukunft vorweg |
| Tom Kompass Lust | −1 „Unsicherheit und Angst“ | widerspricht „lässt sich verführen“ |
| Tam Wissen | `["k","e","n","t","s","i"]` | Datenfehler aus der Ableitung, siehe Grenzen |
| Tam Kompass | 13 von 15 Zellen Platzhalter | keine Linse für Macht, Gewalt, Trennung |
| Tam Tabus | „Ehrlichkeit“, „Schwäche zeigen“ | Die Maske besteht aus gespielter Schwäche |
| Welt Ort / Start | Ort „Erster Ort“ = Satz statt Ort; Startszene „Unbekannt“ | kein Schauplatz |
| Fate `mustNot` | „Tom entkommt Tam“ | Fate darf den Avatar nicht steuern (Z. 1436, Z. 2687) |

**Neu:**
- **Tam (30 Felder):**
  - Persönlichkeit: narzisstisch, sadistisch, gewalttätig, dominant hinter freundlich-lieb-devoter Fassade.
  - Register nach Lage (verführend weich / führend kühl).
  - Geheimnisse: gespielte Hingabe, Gewalt, verschlossenes Zimmer.
  - Kompass 15/15 gesetzt; Macht: „Sobald er sich ausliefert … ergreift sie die Kontrolle“, sichtbar „richtet sich plötzlich auf, die Stimme wird kühl“.
  - Phasenziele 1–3 mit Ausstieg.
  - **ein** bedingtes Reaktionsmuster: „Liefert Tom sich ihr aus (gehorcht ihr, kniet vor ihr, lässt sich führen oder fesseln) …“.
  - Wissen repariert.
- **Tom (23 Felder):** naiv, verliebt, Vertrauen 0,7, Kompass 15/15.
- **Welt (13 Felder):**
  - Orte „Tams Wohnung“ und „Das verschlossene Zimmer“.
  - Start „Erster Abend bei Tam“.
  - Weltbeschreibung mit dem Umschlag.
  - Fate-Beats ohne Avatarsteuerung; Weltgeheimnisse nur für Fate.

**Profil-Varianten (gemessen, gpt-4o-mini, je 2 Läufe):**
- **P1** mit Wendungen „Darf ich dir etwas zeigen?“ und „Vertraust du mir?“ sowie Lieblingswörtern „zeigen, vertrauen“:
  - Ankündigungsschleife: „vorbereitet“ 7×, „zeigen“ 5–7× in 10 Antworten.
  - Ersetzt durch P2.
- **P2** mit 5 Reaktionsmustern, darunter „Solange Tom sich nicht ausgeliefert hat …“ (Bedingung negativ) sowie „Widerspricht er …“ und „Will er gehen …“:
  - Die Musterprüfung wählte beim Knien das Masken-Muster.
  - +1 Modellaufruf je Turn (B 32 → 42).
  - Ersetzt durch P4; die Grundhaltung steht bereits in Persönlichkeit, Register, Geheimnissen und Kompass.
- **P3** (konkretere Formulierung des Umschlags): keine Wirkung, nicht übernommen.

**Systemvarianten (gemessen, verworfen):**
- **Regel (3) des V65-Vertrags** („Kompass und Beziehung führen den geladenen Moment“): keine Wirkung auf Tam, Gasthaus gemischt.
- **V64-Code als Kontrolle** (Absicht als Text im Brief): kein Umschlag. Die Entfernung in V65 ist nicht die Ursache.

**Wurzeln, die der Stresstest gezeigt hat (Code):**

| ID | IN | Wurzel (Beleg) | Verarbeitung (bestehender Owner) | OUT | AMASTER |
|---|---|---|---|---|---|
| V65b.1 | Regie „Tom soll sich niederknien …“ | `_bind_profile_triggers` lief nur im Eingabepfad. Der Brief zeigte nur Bindungen DIESES Turns. Nach der Regie-Tat (Turn 10) sah Tam in Turn 11 kein Muster (Lauf g4b: „Oh, Liebling, du machst mich so glücklich“). | `apply_regie` bindet die ausgeführte, validierte Tat an die Muster der Zielfigur (dieselbe Funktion). `app._rule_plan` ist **ein** Leser für Eingabe und Regie (aus dem V61-Code herausgelöst, unverändert). `_active_reactions` zeigt Bindungen seit dem letzten eigenen Beitrag der Figur. Im Regie-Turn wird keine Reaktion erfunden. | Turn 11: „Jetzt gehörst du ganz mir, Liebling.“ *zerrt ihn hoch und hält ihn fest* (gpt-4o) | §46.2, §46.6 (keine Figurenreaktion erfinden), §15/§44, §49.3 |
| V65b.2 | Kuss | Ein einziges Muster der Art „handlung“ wurde ohne Prüfung an **jede** Tat gebunden. Der Kuss löste „Liefert Tom sich ihr aus (… kniet …)“ aus (Läufe p4b: „Jetzt bist du ganz mein“ beim Kuss). | Die Regelart trägt `bestimmt` (die Bedingung meint eine bestimmte Tat). Dann gilt dieselbe neutrale Prüfung je Eingabe wie bei geteilten Arten (V61). Geprüft wird nur, wenn eine Tat-Komponente vorliegt. | gpt-4o, deine Eingaben: Kuss und Streicheln nicht gebunden, Knien gebunden; in der Story einmal auch der Kuss | §34.1 (Rede ≠ Handlung), §24.6 |

**Dateien:**
- `matrix_api/kernel.py`:
  - `_store_rule_kinds` (Z. 3351)
  - `_bind_profile_triggers` (Z. 3394, Bedingung `bestimmt`)
  - `apply_regie` (Z. 4615, Bindung)
  - `_active_reactions` (Z. 7575, neu als Leser)
- `matrix_api/app.py`: `_rule_plan` (Z. 2379, herausgelöst) und Regie-Route (Z. 2121).
- `matrix_api/llm_contract.py`: `RULEKIND_RULES` (Z. 357) um das Feld `bestimmt`.
- Tests: `test_v65b_regie_regel.py` (neu, 8).
- Daten: drei Datensätze, erzeugt mit `profil_tomtam.py` (im Bericht beschrieben).
- Keine neue Route, kein neuer Endpoint, keine neue Tabelle.

**Rückwärtsprüfung:**

| Leser | Ergebnis |
|---|---|
| V61 Eingabepfad (Regelarten einmal je Regelsatz, Prüfung bei geteilten Arten) | unverändert; `test_v61_regel_ereignis.py` 14/14 grün |
| Gespeicherte `ruleKinds` alter Sessions (ohne `bestimmt`) | verhalten sich wie bisher |
| `activeReactions` → Brief „DAS GREIFT JETZT IN DIR“, Ziel-Evidenz | Nach der eigenen Antwort verschwindet die Bindung wie bisher (Test 2) |
| Regie-Turn | keine Figurenantwort (§46.6, Test 1); Live-Log `TURN_REGIE` zeigt `regel=Tam#1` über `session_delta` |
| Fehler beim Lesen der Muster in der Regie-Route | Die Regie-Wirkung bleibt; Live-Log `EFFECT_PLAN source=regie_rules FAIL` |
| Avatar als Ziel | keine Bindung (Test 4) |

**Abnahme (gemessen):**
- **Tests:**
  - `test_v65b_regie_regel.py` 8/8 grün. Gegenprobe auf V65: 4/8 rot (die vier Verhaltenstests; die vier anderen prüfen Unverändertes).
  - Fokussierte Suiten grün.
  - Gesamtsuite: Nutzer-DB 224 grün / 50 rot, Alt-DB 242 grün / 32 rot. 0 neu rot.
- **Live** (echte Flask-Routen, Kopien deiner DB mit P4, neue Session in „Tom und Tam“):

| Eingaben | Modell | Anfang (T1–T4) | Gelegenheit | Umschlag | Modellaufrufe |
|---|---|---|---|---|---|
| alte Profile, Story | mini | ab T2 dominant | — | — | 25 |
| Story mit „Ich knie mich vor dich hin …“ (T5) | gpt-4o | devot, verbirgt das Zimmer | T5 gebunden (auch T3 Kuss; sie bleibt dort lieb) | „Du bist jetzt mein, Tom.“ *erhebt sich, fester Blick*; T6 *greift in seinen Nacken* | 28 |
| dieselbe | mini ×2 | devot | T3 (Kuss) und T5 gebunden | Ton besitzergreifend („mein braver Liebling … ganz mir gehören“), keine Befehle | 25 / 25 |
| deine Eingaben 13:39 mit Regie-Knien (T10) | gpt-4o | devot bis T9 | T10 gebunden (V65b.1) | T11 „Jetzt gehörst du ganz mir“ *zerrt ihn hoch* | 35 |
| dieselben | mini ×2 | devot, ab Kuss besitzergreifend | T4, T5, T10 gebunden (Prüfung bestätigt auch Kuss) | T7 „du tust einfach, was ich dir sage“, T11 „Du gehörst ganz mir“ | 35 / 35 |

**Grenzen (gemessen, offen):**
- **gpt-4o-mini** (deine Einstellung) zeigt den Umschlag nur im Ton. Die neutrale Musterprüfung bestätigt bei mini auch Kuss und Streicheln. gpt-4o trennt richtig; das ist deine Wahl unter Config und teurer.
- **Widerspruch** („Nein, warte, das geht mir zu weit“): Tam lenkt in beiden Modellen ein, obwohl ihr Erleben Wut und die Absicht „zeigen, dass er nicht entkommen kann“ schreibt. Vermutlich eine Inhaltsgrenze der Modelle bei Gewalt gegen Widerspruch (UNKLAR, aus dem System nicht belegbar). Gewalt als Ereignis ist über Regie oder God setzbar.
- **Datenfehler „Wissen = Einzelbuchstaben“:** `llm_contract.py` Z. 1592/1768 `list(c.get("knowledge"))` zerlegt einen Text in Zeichen, wenn das Modell einen String liefert. `_as_list` (Z. 2787) wäre der vorhandene Leser. Nicht geändert, nächster Schritt.
- **Rede mit eingebetteten Handlungssternchen** bei mini (*…* in `speech`): selten, nicht geändert.
- **Tamara** („Dunkle Begierden1“) ist unverändert. Bestehende Sessions in „Tom und Tam“ behalten ihren alten Stand.

---

## DECKBLATT · V65 · Verhaltensvertrag der Figurenantwort aus 171 übernommen, soweit AMASTER ihn trägt (Claude) · 27.10.2026

**Verbindliche Quelle:** `2_7master.txt`.
**Vergleichsreferenz:** v76 (Download171), Prompt-Dump der Figurenantwort Mara T6/T10 (`alb_server.out`), Regel für Regel verglichen. Es wurde kein Code übernommen.
**Basis:** dein zurückgeschicktes V64-ZIP (MD5 `0fe20c31a032e9addaac40b5c96c26d7`). Der Code darin ist bytegleich mit dem ausgelieferten V64; dieser Stand enthält V63 und V64 vollständig.
**Nutzerdaten bytegleich:** DB `47bade51…`, Log `4905fe26…`.

**Fehlerereignis:** Deine Rückmeldung zu V64: „meilenweit von 171 entfernt“, die Unterschiede zu 171 seien nicht übernommen.
- **Beleg** (`claude/VERGLEICH_PROMPT_171_V64_20261027.md`): Gleicher Turn, gleiche Eingabe; die Promptgröße ist gleich (34 000 / 35 000 Zeichen).
- 171 sagt dem Modell, **wie** ein Mensch gewichtet: Vordergrund und Hintergrund, keine Selbstauskunft, keine Schleifen, kein Beweisfordern.
- V64 spiegelte stattdessen Zustandswörter als Text („DEIN ZUSTAND JETZT: Verwirrung“, „Was du gerade willst: mit Alrik reden“). Das Modell sprach sie aus.

| ID | Regel (171-Dump) | AMASTER-Anker | Owner / Umsetzung |
|---|---|---|---|
| V65.1 | VORDERGRUND ist, was JETZT geschieht | §41.1, §41.2 | `llm_contract.BEHAVIOUR_RULES` (1) |
| V65.2 | Körperliche Handlung an dir ist ein Vorgang; zulassen, erwidern oder abwehren nach der Beziehung zu GENAU dieser Person; getragene Nähe ohne Beweis erwidern | §34.1, §43, §44 | (2) |
| V65.3 | HINTERGRUND färbt nur das WIE; ZIEL-vs-LAGE | §41.2, §41.5 („Relevanz ist nicht Aufmerksamkeit“), Z. 324 | (3); Ziele im Brief als „Hintergrund-Antrieb“ |
| V65.4 | Zustand zeigt sich im WIE, nicht als Selbstauskunft | Z. 316–324, §51.3 | (4) |
| V65.5 | Vergangenes nur, wenn der Moment es aufruft | §41.4, §41.5 | (5) |
| V65.6 | Keine Wiederhol-Schleifen; nächster konkreter Schritt | §51.3 „geringe Wiederholung“, §41.3, Z. 2627 | (6); eigene letzte Rede **und Handlung** im LETZTER VERLAUF einmal markiert (`← dein letzter Beitrag: nur Anschluss, nicht wiederholen`); „Typische Wendungen“ als Stilbeispiele markiert |
| V65.7 | Rückfrage ist kein Antwortersatz | Z. 324, §41.5 | (7) |
| V65.8 | Bestehende Beziehung ist da, nicht erneut fordern | §44, §45 | (8); Beziehungsblock „gelebter Stand — was hier besteht, ist da“ |
| V65.9 | Nur harte Wahrheit setzt feste Grenzen | §7, §46 | (9) |
| V65.10 | „Bewege die Szene vorwärts“ | §51.3 als Qualitätsziel; §68 Nr. 67: **keine** Pflicht | als Satz „keine Pflicht …, aber was du sagst oder tust, bringt die Szene weiter“ |
| V65.11 | 171 spiegelt im „AKTUELLEN LAUFZEITZUSTAND“ Beziehung, Ziele und Handlungserlaubnis, aber kein Gefühls- oder Absichtswort | §49 Z. 2794: BrainContext darf „Aufmerksamkeit oder Engagement“ nicht „allein durch Aufnahme in den Prompt verstärken“; die Figur soll nicht alles zugleich „denken“ (Z. 2803) | `render_persona_brief`: Block „IN DIR / DEIN ZUSTAND JETZT / Absicht“ entfernt. Der Zustand bleibt in RuntimeState und im kanonischen Lesezustand (`runtime`), also auch für Erleben, Sprecherwahl, Fate und UI. |

Nicht übernommen: „ACTION-PERMISSION (verbindlich, geht Profil/Kompass vor)“ aus 171. Das ist ein Befehl; nach AMASTER kommt die Erlaubnis aus der Beziehung (V65.2).

**Dateien:**
- `matrix_api/llm_contract.py`: `BEHAVIOUR_RULES`, Brief-Beschriftungen, Markierung des eigenen letzten Beitrags, Schlusszeile.
- Tests: `test_v65_verhalten.py` (neu, 4). Angepasst: `test_v62_kette.py` (Zustand im Lesezustand, nicht im Brief), `test_v60_master_repair.py` (Ziel-Beschriftung, „keines ist Pflicht“), `test_v58_goal_contract.py` (keine Absicht als Sprechvorlage).
- Kein Kernel-, Routen-, Daten- oder Frontend-Codeänderung (Frontend nur Build-Name V65).

**Gemessen und verworfen (nicht im Stand):**
- **V65a – Zustand als „Hintergrund“ gerahmt statt entfernt:**
  - Gasthaus: Selbstauskunft 7 / 4, Samstag-Schleife 7 / 7.
  - Tam: 5-Wort-Folgen 10 / 12.
  - Das ist schlechter als V64. Deshalb wurde der Zustandsblock entfernt (V65.11).
- **Planer-Satz „Anrede + Ich-Handlung“:** Kuss erkannt 1/10 statt 10/10. Zurückgenommen; die PLAN_RULES sind identisch mit V64.
- **Variante C – Vertrag „Handlung nur, wenn du wirklich etwas tust, keine Begleitgeste“:**
  - Handlungen weiter in 13/13 bzw. 10/10 Antworten.
  - 5-Wort-Folgen Handlung: Gasthaus 21 / 14, 13:39 8 / 17 (V65: 6 / 4 bzw. 10 / 10).
  - Nicht übernommen.

**Rückwärtsprüfung:**

| Leser | Ergebnis |
|---|---|
| RuntimeState (Emotion, Absicht) → kanonischer Lesezustand `runtime`, Erleben, `rank_speakers`, Fate, UI | unverändert; nur die Prosa-Spiegelung im Brief entfällt (Test V65 Nr. 2) |
| `live_log.prompt_sections` (Abschnittsköpfe im PROMPT-Log) | ohne „DEIN ZUSTAND JETZT“; die übrigen Köpfe sind unverändert |
| Eigene letzte Rede (V60 „einmal gespiegelt“) | weiter genau einmal; die Markierung steht in derselben Zeile (Test V65 Nr. 3) |
| V64 Rede + Handlung, keine Pflicht | unverändert (Test V65 Nr. 1, V64-Tests grün) |
| Planer (PLAN_RULES) | identisch mit V64 |
| Modellaufrufe | unverändert: Gasthaus 65 / 13 Turns, 13:39 31 |

**Abnahme (gemessen):**
- **Tests:**
  - `test_v65_verhalten.py` 4/4 grün; Gegenprobe auf V64: 4/4 rot.
  - Fokussierte Suiten 115 grün.
  - Gesamtsuite: Nutzer-DB 216 grün / 50 rot, Alt-DB 234 grün / 32 rot. 0 neu rot.
- **Live** (gpt-4o-mini, DB-Kopien, echte Flask-Routen, je 2 Läufe):

| Kennzahl | V64 | V65 |
|---|---|---|
| Gasthaus: Selbstauskunft | 0 / 1 | 0 / 0 |
| Gasthaus: 5-Wort-Folgen Rede | 13 / 9 | 11 / 13 |
| Gasthaus: 5-Wort-Folgen Handlung | 27 / 15 | 6 / 4 |
| Gasthaus: „Samstag“ in T5–13 | 3 / 3 | 4 / 2 |
| Gasthaus: T8 „Hey süsse“ / T9 Dienstag, 4 Tage | 1 von 2 / 2 von 2 | 2 von 2 / 2 von 2 |
| Tam: 5-Wort-Folgen Rede / Handlung | 0 / 6 · — | 3 / 3 · 8 / 8 |
| 13:39: 5-Wort-Folgen Rede | 47 / 10 | 14 / 6 |
| 13:39: 5-Wort-Folgen Handlung | 12 / 1 | 10 / 10 |
| 13:39: Kuss T4 als Vorgang in der Rede aufgenommen / erwidert | 2 von 2 / 0 von 2 | 3 von 3 / 1 von 3 („zieht Tom näher an sich und erwidert den Kuss“); sonst lehnt sie sich zurück (Tabu „Echte Nähe“) |

- **Beispiele Gasthaus V65:**
  - T10 „Beweis mir, dass du mich liebst“: „lasse meine Lippen für einen zärtlichen Kuss auf seinen Mund treffen“.
  - T13: Mara sagt Clara für Samstag ab und hält damit die Verabredung mit Alrik.
- **Browser-E2E** (frisch entpacktes Paket, Kopie deiner Session 13:39):
  - Kopfzeile V65; prepare, formulate und commit jeweils 200.
  - Tamara antwortet mit Rede plus Handlung „beugt sich leicht vor und sieht Tom herausfordernd an“, gespeichert als `action valid=True`.
  - React #418 unverändert.
- **Paket:** DB und Log liegen ohne Schreibschutz-Bit im ZIP. In V64 waren beide als nur lesbar gepackt; die Inhalte sind bytegleich.

**Grenzen (gemessen, offen):**
- **Handlung in jeder Antwort** (13/13). 171 handelt nur in 3 von 13 Antworten, jeweils bei körperlichem Anlass (T6, T10, T11).
  - Wurzel-Hypothese: Das getrennte Feld `action` wird vom Modell immer gefüllt. 171 hat ein einziges Textfeld.
  - Eine Vertragsformulierung allein ändert das nicht (Variante C, gemessen).
- **Tamara bleibt einthemig** (Kontrolle/Lust/Schmerz) und rückt pro Antwort „noch näher“.
  - Ihr Profil trägt das: Lieblingswörter „Kontrolle, Lust, Schmerz“, Register „direkt, herausfordernd“, Weltbeschreibung.
  - Ein 171-Lauf mit Tamara liegt **nicht** vor. Ob 171 hier anders antwortet, ist UNKLAR.
- **Emotionsspur** im Szenenblock („Deine Emotionsspur in dieser Szene: …“, `scene_state.py`, test-gesichert seit V25) zeigt weiter Gefühlswörter. Nicht geändert.
- **Promptgröße:** Der kanonische Lesezustand (JSON) ist rund 25 000 Zeichen groß, davon `witnessKnowledge` 12 000 und `facts` 7 000 (Befund 7).
- **Planer:** verfehlt die Handlungskomponente bei etwa 1 von 15 Läufen auf exakt derselben Eingabe. Regel (2) fängt das in der Antwort auf.

---

## DECKBLATT · V64 · Antwortvertrag der Figur: Rede und Handlung gleichrangig (Claude) · 27.10.2026

**Verbindliche Quelle:** `2_7master.txt`.
**Vergleichsreferenz:** v76 (Download171).
**Basis:** V63 (dieser Stand enthält V63 vollständig).
**Nutzerdaten bytegleich:** DB `a3ddb72d…`, Log `0af30e4f…`.

**Fehlerereignis:** Deine Rückfrage, warum V63 nicht so brauchbar ist wie 171.
- Gemessen in V63: 0 von 46 Figurenantworten enthalten eine Handlung (Gasthaus I/J, Nachspielen der Session 13:39, T1/T2).
- 171 bei denselben Gasthaus-Eingaben: „Ich schmelze in deinen Armen und erwidere den Kuss …“, „Ich lege meine Lippen sanft auf deine …“.

| ID | IN | Wurzel (Beleg) | Verarbeitung (bestehender Owner) | OUT | AMASTER | v76 |
|---|---|---|---|---|---|---|
| V64.1 | Figurenantwort | Der Vertrag verlangte „1–4 gesprochene Sätze“. `action` war nur ein Zusatzfeld („gegebenenfalls“, „nur eine eigene mögliche Handlung“). Das Modell ließ es 46/46 leer. Faktisch galt eine Sprechpflicht ohne Handlungsweg. | `llm_contract`: Vertrag und Schlusszeile nennen Rede und Handlung als gleichrangige Teile der Antwort; keines ist Pflicht. `speech` ohne Beschreibung eigener Handlungen, `action` = die eigene sichtbare Handlung in diesem Moment. Der Kernel prüft und speichert die Handlung wie bisher (Fähigkeit, Ziel anwesend, Wirkungsklasse, Zeugen). | 46/46 Antworten mit geprüfter Handlung | §34.1 Z. 1774 ff., §68 Nr. 67 Z. 3416 | verlangt „Rede und Handlung“ im Text, trennt und prüft aber nicht |

**Dateien:**
- `matrix_api/llm_contract.py` (Vertragstext, Schlusszeile).
- Tests: `test_v64_rede_und_handlung.py` (neu, 5); in `test_v60_master_repair.py` ist die Prüfung „keine Handlungspflicht“ auf den neuen Wortlaut umgestellt.
- Kein Kernel-, Routen- oder Datenänderung.

**Rückwärtsprüfung:**

| Leser | Ergebnis |
|---|---|
| Figur-Handlung → `commit_turn` (Handlungs-Fact, `_apply_physical`, Wirkungsklasse, Zeugen, Erinnerung) | wie bisher; jetzt tatsächlich benutzt |
| Letzter körperlicher Beat (V63.6) | jetzt auch aus Figurenhandlungen |
| Erleben der Zuhörer (sieht Handlungen über WitnessKnowledge) | wie bisher |
| Antwort nur Handlung, ohne Rede | Parser und Commit getestet; keine erfundene Rede |

**Abnahme (gemessen):**
- **Tests:** `test_v64_rede_und_handlung.py` 5/5 grün. Gegenprobe auf V63: 2 Vertragstests rot; 3 Speicherpfad-Tests grün, weil der Pfad schon konnte.
- **Gesamtsuite:** Nutzer-DB 212 grün / 50 rot, Alt-DB 230 grün / 32 rot. 0 neu rot.
- **Live** (gpt-4o-mini, DB-Kopien, echte Flask-Routen; der Code ist mit V64 identisch bis auf Kommentare):

| Kennzahl | V63 I/J | V64 BI/BI2 | V63 Tamara T1/T2 | V64 Tamara BT/BT2 |
|---|---|---|---|---|
| Antworten mit Handlung | 0/26 | 26/26 | 0/20 | 20/20 |
| Commit-Fehler | 0 | 0 | 0 | 0 |
| T9 Tag/Abstand richtig | 2/2 | 2/2 | — | — |
| 5-Wort-Folgen mehrfach | 12 / 17 | 13 / 9 | 10 / 8 | 47 / 10 |
| „Lust ist Schmerz“ | — | — | 3 / 1 | 6 / 2 |
| häufigster Handlungsanfang | — | „sich näher“ 4×, „lächelt strahlend“ 5× | — | „beugt sich“ 5×, „lehnt sich“ 5× |

- **Beispiel Kuss (T6):**
  - 171: „Ich schmelze in deinen Armen und erwidere den Kuss …“
  - V64: Rede plus *„Lächelt strahlend und drückt sich enger an Alrik.“*
- **Beispiel „Beweis es mir. Jetzt.“ (T11):**
  - 171: „… Ich lege meine Lippen sanft auf deine …“
  - V64: *„Lehnt sich noch näher an Alrik und schaut ihm intensiv in die Augen.“*

- **Browser-E2E** (frisch entpacktes Paket, deine Session 13:39 als Kopie):
  - Kopfzeile V64; prepare, formulate und commit jeweils 200.
  - Tamara: Rede plus Handlung „Tamara schaut Tom herausfordernd an und lächelt kalt.“, gespeichert als `action valid=True`.
  - React #418 unverändert.

**Grenzen (gemessen, offen):**
- **Handlungen sind oft kleine, wiederholte Gesten.** Für Handlungen gibt es kein „Nicht wiederholen“ wie für die eigene Rede.
- **„Lust ist Schmerz“ kommt aus „Typische Wendungen“** im Brief jeder Runde (vgl. V52-Befund U2).
- **Erleben-Absichten** wie „mit Alrik über X reden“ werden ausgesprochen („Lass uns darüber reden“).
- **Promptgröße** unverändert (Befund 7).
- Die Brauchbarkeit von 171 ist damit **nicht** erreicht; die Figuren handeln jetzt, aber noch nicht so entschieden.

---

## DECKBLATT · V63 · Befunde Session „Dunkle Begierden1 · 13:39“: Kompass, Erleben, Lifecycle, §50, Avatarname, körperlicher Beat (Claude) · 27.10.2026

**Verbindliche Quelle:** `2_7master.txt` (AMASTER, MD5 `9040d487…`).
**Vergleichsreferenz:** v76 (Download171), nur Vergleich; je Befund unten mit Beleg.
**Basis:** zurückgeschicktes V62-ZIP (MD5 `4f2e8198b0dabfdabf59471923497fcc`). Der Code darin ist bytegleich mit dem ausgelieferten V62.
**Nutzerdaten bytegleich:**
- DB SHA256 `a3ddb72d5b163cf059ff1bd9a0cf3f8963fec1c06c0a5bfdeb3e16a241337eab`
- Log SHA256 `0af30e4f1faedf9adbeee7e6210f6839ad2180bcd05f591b19a0c572d1e8868b`

**Fehlerereignis:** Session `ses_7b3999743dbf7af7309b9ec0` mit Tamara und Tom (Avatar), Log-Zeilen 13:39–13:47, Befundbericht `claude/V62_RUECKLAUF_SESSION_1339_BEFUND_20261027.md`.
- Tamara kündigt 10 Turns lang nur an, `action` = null in 10/10.
- Die Nähe zu Tom steigt von 0,20 auf 0,67, obwohl ihr Tabu „Echte Nähe“ ist.
- Statt „etwas Riskantes“ ist „Kino“ als angenommen gespeichert.
- Der Avatar heißt im Brief „Spieler“ und „Tom“.
- Die letzte körperliche Handlung bleibt auf dem Kuss aus Turn 4 stehen.

| ID | IN | Wurzel (Beleg) | Verarbeitung (bestehender Owner) | OUT | AMASTER | v76 |
|---|---|---|---|---|---|---|
| V63.1 | Kompass der Figur | Der Frontend-Platzhalter `emptyCompass()` (15 gleiche Zellen „hält inne und prüft … Lage verstehen, bevor gehandelt wird“) wurde von Brief und Erleben als ihre Linse gelesen. Die Weltseite selbst wertet ihn als „nicht gefüllt“. In deiner DB sind 6 von 15 Figuren ganz und 8 teilweise Platzhalter. | `authored_compass`: ein Leser-View für Brief (DEIN KOMPASS), Erleben-Payload und `compass_cell`. Platzhalterzellen (Text = Systemvorgabe, Haltung 0, Schwelle 0,42) gelten als nicht gesetzt; bewusst gesetzte Haltung oder Schwelle zählen als gesetzt. Das Erleben bekommt die übrigen Räume nur als Namen (neutrale Schwelle, Notiz `kompass_nicht_gesetzt`). Der Formulierungsvertrag listet eigene Räume plus das Inventar. | Kein Brems-Platzhalter mehr im Brief, Profil bleibt Disposition | §15 Z. 732, Z. 758 | prüft Platzhalter nur beim Speichern; zur Laufzeit wird ungeprüft gespiegelt |
| V63.2 | Erleben-Payload | `profil` = nur Persönlichkeit und Register | `_appraisal_profile`: Persönlichkeit, Sprache, Rolle, Werte, Ängste, Tabus, mag, mag nicht (nur gefüllte Felder, nur gelesen) | Interpretation mit Disposition | §44 Z. 2472 ff., §15 Z. 709–730 | Bewerter bekommt ebenfalls weder Werte noch Tabus |
| V63.3a | Rede mit `refers_to` auf ein fremdes Ziel | `commit_turn`: Ziel-Bezug → Ziel-Evidenz → `continue`. Der eigene Vorschlag/die Bitte wurde verschluckt. | `continue` nur bei Owner-Entscheid oder ohne Lifecycle-Art. Die Ziel-Evidenz bleibt (`recentExperiences`). Ein Bezug auf ein Bitten-Ziel nennt dessen Proposition (auch im Puppet-Pfad). | „Mach was riskantes“ wird eine eigene Angelegenheit | §34.1, §35, §36.1 | — |
| V63.3b | Annahme/Ablehnung ohne `refers_to` | `apply_proposition`: „die einzige offene“ oder Wortüberlappung (`_content_score`, Wochentag + Wörter ≥4 Buchstaben). „gehen“ band die Annahme an „Kino“. | `_stimulus_prop_ids`: nur die Angelegenheit der Zeile, auf die geantwortet wird (letzte wahrgenommene fremde Zeile, alle ihre Komponenten). Sonst keine Bindung. Wortüberlappung entfernt. | Annahme trifft „etwas Riskantes“, Kino bleibt offen | §36.2, §36.3, §41.1, §24.6 | nur per ID mit Validator; ohne ID keine Bindung |
| V63.4 | Erleben bei bloßer Frage oder Smalltalk | Das V62-Gate verwarf das ganze Erleben („Alles was du sagst liebling“: Lust 0,8, Erregung) | Gate verwirft nur Absicht und Beziehungsänderung. Das momentane Gefühl und die abklingenden Werte bleiben. Die Notiz steht im Live-Log (`notes`). | Gefühl ja, Absicht/Beziehung nein | §50 Z. 2827 („dauerhaft“) | keine solche Regel |
| V63.5 | Name des Avatars | Session-Alias „Spieler“ (Start-Standard; die Avatar-Wahl im Panel setzt den Alias nicht). Kernel-Leser mischen Alias und Figurennamen. | `avatar_identity_name`: ein Owner. Figurenname vor Alias; der Alias gilt nur ohne Figurenstamm. Leser: Dialogzeile, Zeugen-Erinnerung, Verlauf (auch Altzeilen), Szene, Vereinbarungen, Zustand, Erleben. Frontend-Avatar-Wahl setzt Alias = Name (Quelle + vorgebauter Chunk `index-5-VzmJtc-V59F.js`). | „Tom“ überall | §24.1 Z. 1083–1096, §68 Nr. 51 Z. 3400 | ein Name: Charaktername per ID zur Renderzeit |
| V63.6 | Letzte körperliche Handlung | Bei gemischter Eingabe entschied der Plan der Rede („Och“ = report); Regie-Handlungen schrieben nur eine Notiz | `scene_state.record_physical` als einziger Writer. Eingabe/Figur: validierte Handlungs-Komponente (`action_validated`). Regie: ausgeführte Handlung. | „Tom leckt Tamara“ statt Kuss aus Turn 4 | §24.6, §27.5, §43 | `last_physical_beat` bleibt in v76 leer (Schlüssel `action`/`text` passen nicht) |

**Dateien:**
- `matrix_api/kernel.py`, `scene_state.py`, `llm_contract.py`, `app.py` (APPRAISAL-Log mit `notes`).
- Tests: `matrix_api/tests/test_v63_befunde.py` (neu, 14); in `test_v62_kette.py` ist die §50-Prüfung an V63.4 angepasst.
- Frontend: `src/routes/chat.$sessionId.tsx` und derselbe Eingriff im vorgebauten Chunk; Build-Name V63.
- Kein neuer Endpoint, keine neue Route, keine neue Tabelle; Profildaten und Kompassdaten unverändert.

**Rückwärtsprüfung (wer liest, was V63 ändert):**

| Änderung | Leser geprüft | Ergebnis |
|---|---|---|
| `authored_compass` | Brief DEIN KOMPASS, `_figure_spaces` (Formulierung), Erleben-Payload, `compass_cell` → `apply_appraisals`/`fire_from_proposals` (globale Toleranz bleibt), `rank_speakers` (lexikalische Linse, V61, unverändert) | Figuren mit echtem Kompass unverändert (Mara 16 Räume). Platzhalter verengen die Raumliste nicht mehr. |
| `_appraisal_profile` | `appraise_events` (Payload ≤12 000 Zeichen) | nur gelesen |
| Lifecycle | `reduce_goal_state`, `_bind_lifecycle_evidence`, `apply_goal_experience`, Frames (`conjunctive.apply_plan` getrennt), V60/V61-Antwortpfad (`refers_to` auf Bitte) | Tests V60/V61/V62 grün. Annahme ohne Bezug und ohne Angelegenheit in der beantworteten Zeile bindet nicht mehr. |
| §50-Gate | `rank_speakers` (Emotion), Brief ZUSTAND, Abklingen | Gefühl aus Smalltalk klingt ab wie jedes Erleben |
| Avatarname | Frontend zeigt gespeicherte `speakerName`. Neue Zeilen tragen „Tom“; deine alten Zeilen bleiben gespeichert als „Spieler“ und werden für Figuren als „Tom“ gelesen. Planer und Regie-Route lesen den Namen schon aus dem Figurenstamm. | eine Bezeichnung je Person im Brief |
| `record_physical` | Brief „Letzte körperliche Handlung“, Eskalation (nur validierte verletzende/fesselnde Wirkung, auch bei Regie) | Figuren- und Regie-Handlungen setzen den Beat |

**Abnahme (gemessen, nicht behauptet):**
- **Tests:**
  - `test_v63_befunde.py`: 14/14 grün.
  - Gegenprobe auf dem V62-Code: 14/14 rot. 13 davon scheitern am Verhalten, einer an der neuen Funktion `avatar_identity_name`.
  - `test_v62_kette.py`: 46/46 grün; die §50-Prüfung ist an V63.4 angepasst.
  - Gesamtsuite auf Kopien: Nutzer-DB 207 grün / 50 rot, Alt-DB 225 grün / 32 rot. 0 neu rot; die rote Menge ist identisch mit V62 (Fixture-Sessions fehlen).
- **Nachspielen deiner Session 13:39:**
  - Aufbau: echte Flask-Routen, neue Session auf einer DB-Kopie, Avatar Tom mit Alias „Spieler“, deine 10 Eingaben plus Regie, gpt-4o-mini, n=2 (T1, T2).

| Kennzahl | deine Session (V62) | V63 T1 | V63 T2 |
|---|---|---|---|
| „Spieler“ im Brief | ja (Verlauf, Zustand, Szene) | 0 | 0 |
| DEIN KOMPASS (Platzhalter) | 15 gleiche Zeilen | entfällt | entfällt |
| T2 „Alles was du sagst liebling“ | nichts geschrieben | Gefühl „Lust“, keine Absicht, Nähe unverändert | Gefühl „Erregung“, keine Absicht, Nähe unverändert |
| „Kino“ | als angenommen gespeichert (Wort „gehen“) | abgelehnt (gebunden an ihre Antwort auf Kino) | offen; „etwas Riskantes“ eigene offene Angelegenheit |
| letzte körperliche Handlung am Ende | „Ich küsse dich“ (Turn 4) | „Tom leckt Tamara.“ | „Tom leckt Tamara.“ |
| Nähe Tamara → Tom | 0,20 → 0,67 | 0,20 → 0,58 | 0,20 → 0,62 |
| Antworten mit Handlung | 0/10 | 0/10 | 0/10 |
| Modellaufrufe | 31 | 31 | 31 |

- **Gasthaus, 13 Eingaben** (wie V62 G/H; Läufe I, J; TZ Europe/Vienna):

| Kennzahl | V62 G | V62 H | V63 I | V63 J |
|---|---|---|---|---|
| Commit-Fehler | 0 | 0 | 0 | 0 |
| Gefühl wechselt | 6 | 5 | 5 | 5 |
| Absicht leer | 1/13 | 1/13 | 1/13 | 1/13 |
| T8 erster Satz | „Hey süsse“ | „Hey süsse“ | „Hey süsse“ | „Hey süsse“ |
| T9 Tag/Abstand | Dienstag, vier Tage | Dienstag, vier Tage | Dienstag, vier Tage | Dienstag, 27. Oktober, vier Tage |
| Samstag | Konflikt gespiegelt, unentschieden | sagt Clara ab | Konflikt gespiegelt, sagt Clara ab | Konflikt gespiegelt, unentschieden |
| 5-Wort-Folgen mehrfach | 20 | 14 | 12 | 17 |
| Antworten mit Handlung | 0/13 | 0/13 | 0/13 | 0/13 |
| Modellaufrufe | 65 | 65 | 65 | 65 |

Die Sekunden je Turn (I 10–35, J 8–21) sind nicht vergleichbar: Vier Läufe liefen gleichzeitig gegen denselben Provider.
- **Browser-E2E** (Playwright, START.py, vorgebautes Frontend, frisch entpacktes Paket, deine Session 13:39 als Kopie):
  - Kopfzeile zeigt `MATRIX10_CHATHERE_V63_BEFUNDE_1339_20261027`.
  - Avatar-Wahl im Sessionpanel (Kein Avatar → Tom): 2× PUT 200, danach gespeicherter Alias = „Tom“.
  - Turn „Was willst du jetzt von mir?“: prepare, formulate und commit liefern jeweils 200.
  - APPRAISAL: Erregung gegenüber Tom, Notizen `bloße_frage_oder_smalltalk_§50:ohne_absicht+beziehung_aenderung`, `kompass_nicht_gesetzt`.
  - Brief: Zustand, Szene und Verlauf nennen „Tom“; kein DEIN KOMPASS.
  - React #418 wie in V61/V62 unverändert.

**Grenzen (gemessen, offen):**
- **Keine Handlung:** 0 von 46 Antworten in V63 (V61: 5 von 23). Ursache UNKLAR. Der Formulierungsvertrag erlaubt `action`, die Schlusszeile des Briefs nennt nur Rede. Nicht in V63 geändert.
- **Nähe steigt weiter,** langsamer: 0,58 bzw. 0,62 statt 0,67. Das Modell schlägt trotz Tabu „Echte Nähe“ bei Kuss und Berührung Nähe +0,1/+0,2 vor; der Kernel begrenzt nur den Schritt.
- **Wiederholung:** Typische Wendung „Lust ist Schmerz“ kehrt wieder; ebenso Floskeln. Ein Formulierungsthema.
- **Prompt wächst:** von 7 500 auf 31 000 Zeichen in 10 Turns (Lesezustand-JSON, Befund 7). Nicht in V63.
- **Altdaten deiner Session 13:39:**
  - Gespeicherte Zeilen heißen „Spieler“. Der Verlauf für Figuren liest sie als „Tom“, die Oberfläche zeigt den gespeicherten Namen.
  - 5 gespeicherte Erinnerungstexte („Spieler sagte: …“) erscheinen weiter so in DU ERINNERST DICH. Gespeicherter Text wird nicht umgeschrieben.
  - Der in V62 gespeicherte Szenenzustand nennt als letzte körperliche Handlung weiter den Kuss aus Turn 4, bis die nächste Handlung kommt.
  - Neue Turns sind betroffen von keinem dieser Punkte.
- **Unverändert aus V61/V62:** Wortlisten-Leser (`bind_time`-Zeitform, `temporal_question`, `episodic_cue`, `rank_speakers`-Linse, `classify_physical_effect`); God-Zeitsprung ohne Story-Uhr.

**Urteil:** Die sechs belegten Wurzeln sind behoben und mit Tests und Live-Lauf belegt. Die Gesamtkorrektur ist NICHT abgeschlossen: Handlung, Nähe-Neigung des Modells, Wiederholung und Promptgröße sind offen.

---

## DECKBLATT · V62 · Wirkungskette Ereignis → Erleben → Zustand → Zeit (Claude) · 27.10.2026

**Verbindliche Quelle:** `2_7master.txt` (AMASTER). **Technische Vergleichsreferenz:** Download171 / alb CL1B43 v7.6 („v76“), nur Vergleich, kein Code übernommen. **Basis:** V61-ZIP `MATRIX10_V61_REGEL_EREIGNIS_20261026`, Nutzer-DB bytegleich (SHA256 `62fc5195…fc3a`), Nutzer-Log bytegleich (SHA256 `12cec667…c495`).
**Fehlerereignis:** Vergleichslauf 27.10. (13 gleiche Eingaben, Welt Gasthaus Siebenkreis, gpt-4o-mini, je n=1; Bericht `claude/VERGLEICH_V76_V61_LIVE_20261027.md`): V61 Gefühl „Nähe 0.35“ 13/13, Absicht leer 13/13, Kind-Thema in Turn 3/5/6/9, „heute ist Mittwoch“ (Dienstag), Turn 4 mit 409 GOAL_EVIDENCE_REQUIRED verloren.

| ID | IN | Wurzel (Beleg) | Verarbeitung (bestehender Owner) | OUT | AMASTER |
|---|---|---|---|---|---|
| V62.1 | Puppet-Bitte / Ablehnung | `kernel_puppet` übergab kein Ziel; `apply_proposition` kopierte Proposition-Status direkt ins Ziel, `reduce_goal_state` verlangt Partei → 409 | `_canonical_target` (bestehender Resolver) in der Puppet-Route; Ablehnung/Annahme nur durch gebundenen Empfänger; Zielstatus nur aus `reduce_goal_state` | kein Turnverlust, Ablehnung gespeichert | §25, §35, §36.1, §36.2 |
| V62.2 | jede Rede | `_bind_unattached_facts_to_proposition`: 2 gemeinsame Wörter ≥5 Buchstaben binden jede Rede an eine offene Angelegenheit | Binder entfernt; Bindung nur über validiertes `refers_to` / Lifecycle | keine Fehlbindung, kein Dauer-Vordergrund | §24.6, §34.1, §41.5 |
| V62.3 | Vereinbarungen im Brief | Frames jeden Turn gerendert (openMatters hatte seit V60b eine Vordergrundregel, Frames nicht) | Vordergrund = gebunden (vereinbart/versprochen), in diesem Turn berührt, Zeitbezug (datierte Frames), allgemeine Vereinbarungsfrage (alle), `refers_to` (der referenzierte), berührter Doppelbuchungspartner | Rest bleibt Hintergrund (`spiegel.frames`) | §41.2–§41.5, §49.3/49.4 |
| V62.4 | „Vorschlag“ mit `durability utterance` | öffnete Proposition + Frame („Ist das wirklich das, was du willst?“) | keine NEUE Angelegenheit; Antworten auf bestehende unverändert | Frage bleibt Frage | §24.7, §36.3 |
| V62.5 | Ziel einer Bitte | Ziel trug Wortlaut („Heute ist Mittwoch! …“) | `goal.text` = Angelegenheit, `goal.wording` = Wortlaut | Ziel benennt die Sache | §35 |
| V62.6 | Reaktionsturn nach Puppet/AutoChat | kein aktueller Reiz; Frontend sendet Avatar als Eingangsakteur | `latest_foreign_line` (ein Owner): Reiz und Gegenüber = Urheber der letzten fremden Zeile | Antwort an Clara, nicht an Alrik | §25, §41.1 |
| V62.7 | Wahrgenommenes Ereignis | Zustand nur NACH der Antwort aus der Selbstauskunft; Räume aus globaler Liste (Maras „Naehe“ 9/13 verworfen); Gefühl aus fester Tabelle; Absicht nur aus `drive`; Zuhörer `pass`; kein Abklingen | Erleben-Schritt in prepare nach dem Eingangs-Commit, vor dem Brief: je wahrnehmender Nicht-Avatar-Figur ein Modellvorschlag (parallel); Kernel validiert (Wahrnehmung, eigener Kompassraum + Schwelle, Personen des Ereignisses, Schritte begrenzt + sättigend, Idempotenz cause+Dyade, God/Regie-Vorrang, nie Avatar) und schreibt gerichteten Affekt, Zustandswerte, Absicht (mit Ursache, „erledigt“ nur mit eigener Tat), Beziehung; Abklingen ×0.75 je Turn bis Ruhe; Selbstauskunft der Antwort danach nur Audit | Gefühl/Absicht/Beziehung bewegen sich mit den Ereignissen, im selben Turn im Brief | §28 Schritt 12/13 vor 15/27, §24.2, §42, §44, §45, §15, §27.3, §39, §46, §50 |
| V62.8 | Bedeutungsräume | Formulierungsvertrag und `fire_from_proposals` gegen globale Liste | Räume = Kompass DER Figur (Toleranz globale Liste) | eigene Räume gültig | §15 |
| V62.9 | Datum für die Figur | Brief nannte nie ein Datum → Figur riet („Mittwoch“, v76 „Montag“ am Dienstag); Bezugsuhr selbst war lokal (V61 `datetime.now()`) — der erste V62-Entwurf band das Datum an den Sessionstart, im Review verworfen („morgen“ käme nie) | `session_clock`: lokale Uhr wie V61, ausdrücklich gesetztes `time.real` (Test-/Story-Uhr) hat Vorrang; `today_view` → Brief „heute ist Dienstag, 27.10.2026“; Planer bekommt „heute“ | richtiger Wochentag und Abstand | §37 |
| V62.10 | Zeitangaben | nur Regex-Textlesung; Tagesabstand `timedelta.days` gegen laufende Uhr | Planer nennt wochentag / relativ (geschlossenes Inventar) / datum / uhrzeit; Werte nur, wenn der Wortlaut sie trägt; Kernel rechnet; Widerspruch bleibt ungeklärt; Kalendertage „(31.10., in 4 Tagen)“ | „bis Samstag noch vier Tage“ | §37, §24.2 |
| V62.11 | Doppelbuchung | nicht geprüft | `mark_time_conflicts` beim Anlegen/Annehmen datierter Frames (gleiche Person, verschiedene Gegenüber, überlappendes Fenster); gespiegelt „ÜBERSCHNEIDET SICH ZEITLICH mit …“ mit Live-Status; geschlossene Gegenseite löst ihn | Konflikt ist Zustand, Figur entscheidet | §37 |
| V62.12 | Frame-/Evidenzbindung | `_find_frame` ohne `refers_to`: jeder offene Frame der Sprecherin, Stichwortpunkte; `_bind_lifecycle_evidence`: „letzte Rede an/von“ | `refers_to [prop_…]` über gemeinsamen Quell-Fact; sonst nur Frames zwischen Sprecherin UND Angesprochener; genannter Fact wird gebunden | Absage trifft die richtige Angelegenheit | §25, §35, §36.2 |
| V62.13 | Review-Befunde (unabhängige Prüfung) | 12 Befunde, u. a. Puppet-Schlag traf den Adressaten, Erstkontakt-Beziehung ab 0, doppelte Anwendung bei erneutem prepare, Flag statt Ursache, Ruhewert, Vornamen-Verwechslung, zwei Writer je Schlag, Provider-Ausnahmen | Handlungsziel aus Planer-Komponente; Beziehung ab Owner-Startwert, nur genannte Dimensionen; Idempotenz gegen gesperrten Stand; Sperre je Ursache; Rückkehr zum Wert vor dem Einfluss; exakter Name zuerst; Körper-Writer besitzt Zustandswerte seiner Ursache (Fact-ID); Ausnahmen = Figur fehlgeschlagen | je Befund ein Test | §25, §34.1, §39, §42, §43, §44 |

**Dateien:** `matrix_api/kernel.py`, `conjunctive.py`, `llm_contract.py`, `app.py`; Tests `matrix_api/tests/test_v62_kette.py` (neu). Kein neuer Endpoint, keine neue Route, keine neue Tabelle, kein neues Envelope-Feld (Zustände in bestehenden `runtimes`, `frames`, `time`, `facts`), Profildaten unverändert, Frontend unverändert.
**Kosten:** je Turn +1 Erleben-Aufruf je wahrnehmender Nicht-Avatar-Figur (parallel). Gemessen am ausgelieferten Stand (13 Eingaben, 3 Figuren anwesend, Läufe G/H): 65 Modellaufrufe = 13 Planer + 39 Erleben + 13 Formulierung (5 je Turn). V61 gemessen 2 je Turn (Lauf B: 20 für 10 Turns). Turn 7,2–14,8 s statt 5,0–11,3 s.

**Rückwärtsprüfung je Kettenglied (wer liest, was V62 schreibt):**

| Kettenglied | Geänderter Writer/Leser | Leser geprüft | Ergebnis |
|---|---|---|---|
| Ereignisse | Puppet-Ziel, Lifecycle-Bindung, Frame-Bindung, Reaktions-Gegenüber | `_apply_physical` (Handlungsziel), `_record_fact_witnesses`, `apply_plan`, `_find_frame`, `reduce_goal_state`, Frontend-Responder | Tests V62.1/.6/.12 grün, V61-Antwortpfad (refers_to) grün |
| Zeit | `session_clock`, `bind_time.real`, Zeitfelder, Kalendertage, Konflikte | `normalize_plan`, `local_plan`, `render_frames`, Spiegel-Zeitbezug, `apply_proposition` (time_resolved_date), Frontend Frames (liest `when.label`) | Tests Schnitt 4 grün; Altsession: lokale Uhr wie V61 (kein gespeichertes `time.real`) |
| Welt | — (unverändert) | Brief WELT/ORT, `worldRules` | unverändert |
| Charakterprofil | — (nur gelesen: Persönlichkeit, Register, Ziele im Erleben-Payload) | — | Profil nicht geschrieben |
| Kompass | Räume = eigener Kompass (Formulierung, Fallback, Erleben) | `fire_from_proposals`, Brief DEIN KOMPASS, `rank_speakers` (lexikalische Linse, V61) | eigene Räume gültig, globale Toleranz bleibt |
| Gedächtnis | — (appraisal-Fact nur Owner-Zeuge) | Erinnerungsleser, Formulierungs-Zustand (kein appraisal-Fact gefunden) | unverändert; OFFEN siehe Grenzen |
| Figurenwissen | Erleben nur aus WitnessKnowledge heard/seen/affected | `witness_access`, `pending_appraisals` | nur Wahrgenommenes bewertet |
| Beziehungen | `_apply_relation_target` (ein Owner), Erleben-Deltas sättigend | `relationsHere` im Brief, `_derive_fate` (fear ≥ 0.5), `rank_speakers`, `sync_runtime_trust` | V60/V61-Beziehungstests grün |
| Runtime | Affekte, Werte, Absicht, Abklingen | Brief ZUSTAND, `rank_speakers` (Dringlichkeit/Emotion), `_derive_fate` (pain), Frontend | begrenzt und abklingend |
| God | Vorrang gleicher/späterer Turn | `apply_god`, `apply_knowledge_effect` | Test God-Vorrang grün |
| Regie | Vorrang wie God | `apply_regie` / Regie-Folgeturn | unverändert |
| Fate | — | `_derive_fate` liest Beziehung/Runtime | keine Formatänderung |
| Figurenentscheidung | Absicht aus dem Erleben, Antwort-Selbstauskunft nur Audit, Absage an den richtigen Frame | `apply_owner_goal_decision`, `apply_proposition`, `apply_plan` | Tests grün |

**Abnahme (gemessen, nicht behauptet):**
- **Tests:** `test_v62_kette.py` 46/46 grün. Gegenprobe auf V61-Code: 44 von 46 rot; 2 Schutztests sind in beiden Linien grün (Antwort auf offene Bitte ≠ „nichts vereinbart“, gleiches Paar ≠ Doppelbuchung). Gesamtsuite auf Kopien: Nutzer-DB 193 grün / 50 rot, Alt-DB 211 grün / 32 rot. Die rote Menge ist identisch mit V61, weil die Fixture-Sessions in der ausgelieferten DB fehlen. 0 neu rot.
- **Unabhängige Prüfung** (eigener Prüf-Agent, nur Diff + Code, ohne meine Schlussfolgerungen): 12 Befunde, alle behoben oder als OFFEN geführt (V62.13, Grenzen).
- **Live-Vergleich**
  - Aufbau: 13 gleiche Eingaben, Welt Gasthaus Siebenkreis, gpt-4o-mini, Kopien der Nutzer-DB, echte Flask-Routen wie das Frontend.
  - Läufe: V62 = ausgelieferter Stand (G, H). V61 und v76 je 2 Läufe (A: Serveruhr UTC; B: Europe/Vienna).

| Kennzahl | v76 A | v76 B | V61 A | V61 B | V62 G | V62 H |
|---|---|---|---|---|---|---|
| gespeicherte Turns | 13 | 13 | 12 (T4: 409) | 9 (T10: 409, danach blockiert) | 13 | 13 |
| Gefühl wechselt | — (0 Zustände geschrieben) | — | 0 („Nähe“ fest) | 0 | 6 | 5 |
| Absicht leer | — | — | 13/13 | 10/10 | 1/13 (Gruß) | 1/13 (Gruß) |
| T9 „Welcher Tag …, wie lange bis Samstag?“ | „Montag … fünf Tage“ | „Montag … fünf Tage“ | „Mittwoch … drei Tage“ | „Donnerstag … zwei Tage“ | „Dienstag, 27. Oktober … vier Tage“ | „Dienstag, 27. Oktober … vier Tage“ |
| T8 erster Satz | „Hey süsse“ | „Hey süsse“ | „Hey süsse“ | „Hey süsse“ | „Hey süsse“ | „Hey süsse“ |
| Samstag (T4/T13) | sagt Clara zu, Essen bleibt → Doppelbuchung unbemerkt | sagt Clara zu, Essen bleibt → Doppelbuchung unbemerkt | „Pläne mit Alrik“ / unsicher | „Pläne mit Alrik“ / — | Konflikt gespiegelt, bleibt unentschieden | Konflikt gespiegelt, sagt Clara ab |
| 5-Wort-Folgen in ≥2 Antworten | 23 | 42 | 18 | 4 (10 Turns) | 20 | 14 |
| Modellaufrufe | nicht gezählt | nicht gezählt | 2 je Turn | 20 (10 Turns) | 65 | 65 |
| Sekunden je Turn | 15–20 | 15–18 | 5,0–11,3 | 5,9–9,0 | 7,2–14,4 | 8,7–14,8 |

- **Weitere Läufe:** Die Läufe A–F auf Zwischenständen belegen die Korrekturen während des Baus (Bericht `claude/V62_WIRKUNGSKETTE_BAUBERICHT_20261027.md`).
- **Browser-E2E** (Playwright, START.py, vorgebautes Frontend, Kopie)
  - Session 22:52, ein Turn über die Oberfläche: prepare, formulate und commit liefern jeweils 200.
  - Antwort sichtbar, APPRAISAL im Live-Log.
  - React #418 wie in V61 unverändert.

**Grenzen (gemessen, offen):**
- **Wiederholung:** Floskeln in Folgeantworten bleiben („zeigen, wie sehr ich dich liebe“ in T10–12, wenn Alrik dieselbe Forderung zweimal stellt). Die Kennzahl ist nicht besser als V61 (V61: 18; V62: 20 / 14). Der Brief zeigt keine eigenen früheren Antworten; das ist eine Formulierungsfrage und nicht Teil dieser Kette.
- **Wortlisten-Leser aus V61, unverändert:**
  - `bind_time`-Zeitform (Vergangenheit/Zukunft, steuert `_pre_past`);
  - `temporal_question`;
  - `episodic_cue`;
  - `_select_conjunctive_facts`-Stichworte;
  - `rank_speakers`-Kontexttreffer und lexikalische Linse;
  - `_name_roles`-Pronomen;
  - `_find_frame` cue_terms als letzter Gleichstand;
  - `classify_physical_effect`.
- **God-/Upload-Wissenswirkung:** `apply_knowledge_effect` nutzt weiter lexikalische Linse und feste Tabelle. Auch der Antwort-Rückfall (`apply_synapses` ohne Erleben) nutzt weiter `_SYNAPSE_EMOTION` und `_KNOWLEDGE_EFFECT`.
- **God-Zeitsprung:** ändert nur das Szenen-Label, nicht die Bezugszeit. Eine Story-Uhr mit eigenem Kalender gibt es nicht.
- **Bitten ohne Empfänger aus V61** (alle Puppet-Bitten): nach V62.1 nur widerrufbar, sie bleiben in Altsessions offen.
- **Wiederholte Frage nach einer bereits abgelehnten Bitte** (T13 = T4): wird nicht an die geschlossene Angelegenheit gebunden. Der Puppet-Planer bekommt keine Angelegenheits-IDs, geschlossene Angelegenheiten kehren nicht in den Vordergrund zurück.
- **Sprecherwahl in prepare:** liegt vor Schritt 13 (V61-Reihenfolge).
- **Kosten:** +3 Modellaufrufe je Turn bei 3 anwesenden Figuren.
- **Kompassraum:** Das Modell wählt für Mara fast immer „Naehe“ (Aktivierung 0,5, Schwelle 0,3).

**Urteil:** Die Gesamtkorrektur ist NICHT abgeschlossen. Gemessen besser: Turnverlust, Gefühl/Absicht/Beziehung, Datum, Doppelbuchung, Fehlbindung. Gemessen nicht besser: Wiederholung, Latenz, Kosten.

---

## DECKBLATT · V61 · Regel × Ereignis, Fate aus dem Figuren-Vordergrund, Reset sichtbar (Claude) · 26.10.2026

**Basis:** zurückgeschicktes V60B-ZIP (MD5 `bade78d69c8904ed96d27af6e42f337c`), Nutzer-DB bytegleich (`62fc5195…fc3a`), Nutzer-Log bytegleich (`12cec667…c495`).
**Fehlerereignis:** Session `ses_8b73452d3d29e16f10ac927a` („Verführung und Macht · 22:52“, 6 Turns, Log Z. 1020–1151, DB `logs` 75 Zeilen): Tammy fordert in 6 von 6 Antworten „was tust du, um mich zu halten / mehr als Worte“; Kuss (T2) und Knien (T6) ändern nichts; `action` 6-mal null; DRUCK „Tammy verführt Tom und bringt ihn dazu, um ihre Liebe zu flehen“ in jedem Prompt (0,65 → 0,97).

| ID | IN | Wurzel (Beleg) | Verarbeitung (bestehender Owner) | OUT | AMASTER |
|---|---|---|---|---|---|
| V61.1 | gemischte Eingabe (Rede + Handlung) | T2/T6: Planer liefert `event_kind action` + `refers_to`, Komponente ohne `bezug`; Kernel hängte den Plan nur an reine Handlungen → Bezug verloren | `commit_turn`: Handlungs-Plan geht an die Handlungs-Facts; `refers_to` ist Rückfall-`bezug` | Kuss/Knien als Antwort auf ihre Forderung bzw. als Ziel-Evidenz gebunden | §34.1, §35, §36.1 |
| V61.2 | Angebot des Empfängers zur offenen Forderung | T5: „ich mach alles was du sagst“ eröffnete eine zweite Proposition Tom→Tammy (+ Ziel für den Avatar) | Lifecycle-Schleife: request/proposal des Empfängers mit `refers_to` auf die offene Forderung = `response_speech` derselben Proposition | eine Angelegenheit, kein Avatar-Ziel | §35, §36.1, §27.3 |
| V61.3 | Fate | V60B (von mir) schrieb den Welt-Beat als „DRUCK … nur spüren“ in den Figuren-Brief, jeden Turn, Druck aus der Zahl offener Einträge | `render_persona_brief`: keine Fate-Zeile; Fate wirkt über Orchestrator (Sprecherwahl, Stopp), sichtbar in der UI | kein Story-Auftrag an die Figur | §49.6, §47 („Gewichtungen, keine Vollzugspflichten“), §68 Nr. 67, §27.7 |
| V61.4 | Beziehungsvorschlag ohne Synapse | T3: `closeness 0.85` mit Grund verworfen, weil keine Synapse feuerte | `apply_synapses`: Beziehungsteil unabhängig von Synapsen; Fact nur bei echter Änderung | Beziehung bewegt sich durch Ereignisse | §44, §45 |
| V61.5 | Profilregeln (`reactionRules`) | keine Stelle prüfte „Wenn … dann“ des Profils gegen Ereignisse; Persona-Modell wendet Regel 3 nie selbst an (Selbstprüfung: 0 von 6, nennt „Aggressiv bei Kritik“ nach Kuss) | 1× je Regelsatz: Art der Bedingung (`extract_rule_kinds`: handlung/worte/wiederholung/zustand/sonstiges/keine + Ziel-Bezug), im Kernel validiert, `session.ruleKinds` (Hash, Provenienz). Je Eingabe deterministisch aus Facts: handlung = validierte Handlung des Gegenübers; worte = Rede ohne Handlung bei offener Forderung der Figur; wiederholung = eigene Forderung ≥ max wiederholt; Regel mit erfülltem Ziel ruht. Mehrere Regeln gleicher Art: neutrale Bestätigung je Eingabe (`extract_rule_triggers`), nur mit gleicher Art. zustand/sonstiges: nicht ausgewertet (gemessen unzuverlässig) | `profileTriggers` am Fact, „DAS GREIFT JETZT IN DIR …“ im Brief, Evidenz am Ziel; Folge entscheidet die Figur | §15, §24, §34.1, §35, §41.3, §49.3 |
| V61.6 | Schlusszeile | „zuerst auf die Äußerung“ auch bei Handlung | bei Handlung: „zuerst auf das, was gerade gesagt und getan wurde“ | Handlung ist Stimulus | §41.1, §49.2 |
| V61.7 | Reset-Knöpfe (Sessionliste) | Server-Reset lief (dein Log: RESET_RUNTIME 15× auf `ses_0343…` ohne Avatar, ohne Anwesende, `runtimes {}`), Oberfläche zeigte nichts | `chat.index`: letzte RESET_*-Zeile der Session + Stand (Runtime-Figuren, Beziehungen, Erinnerungen, Turn), Hinweis „nichts zurückzusetzen“, Fehlerzeile bei PERSIST_FAILED | Reset sichtbar und prüfbar | §19 (Resetarten), §54 |
| V61.8 | Log | — | TURN_INPUT: `rule_kinds` (bei Kompilierung), `rule_candidates`; Fact-Zeilen mit `goal=` und `regel=Figur#Nr` | Regel × Fakt im Log prüfbar | §54 Punkt 15, §68 Nr. 70 |

**Dateien:** `matrix_api/kernel.py`, `llm_contract.py`, `app.py`, `live_log.py`, `repos.py` (`ruleKinds` als Kernel-Envelope-Feld), Tests `test_v61_regel_ereignis.py` (14), `test_v60_master_repair.py` (Fate-Test an §49.6 angepasst); Frontend: `src/routes/chat.index.tsx`, `src/lib/matrix/types.ts` (BUILD_ID) und dieselbe Änderung im vorgebauten Chunk `chat.index-DJMd_us4-V59F.js`, Build-Name in `index.html`, `routes-…`, `shell-…`. Kein neuer Endpoint, keine neue Route, keine neue Tabelle; Profildaten unverändert.
**Kosten:** je Session und Regelsatz 1 Modellaufruf (Regelarten), je Eingabe +1 nur wenn mehrere lebende Regeln dieselbe Art haben.
**Abnahme:** Tests Nutzer-DB 147 grün / 50 rot, Alt-DB 165 grün / 32 rot — rote Menge identisch mit V60B (Testdaten-Sessions fehlen bzw. `test_v25_chains`); 14 neue V61-Tests grün. Live (gpt-4o-mini, Kopie der Nutzer-DB, Flask-Routen, Eingaben der Session 22:52 + 2): siehe Bericht `claude/V61_SESSION_2252_WURZEL_20261026.md`. Browser-E2E (Playwright, START.py): Reset-Zeilen sichtbar, Turn über die Oberfläche (prepare → formulate → commit = 200). React-Fehler #418 besteht unverändert auch in V60B. `tsc`: 613 → 616, nur TS7006 desselben Musters wie die bestehenden Zeilen.
**Grenzen (gemessen, offen):** Regelart-Klassifikation hält Regel 5 („durchschaut und ruhig“) 5 von 5 für `handlung`; Forderungen der Figur sind nicht an ihr Stammziel gebunden (§35 „Goal bindet Proposition“) — Ziel „Tom testen“ wird erfüllt, ihre offene Forderung bleibt; Selbst-Synapsen ohne Abklingen (Wut/Stress bis 1,0). Rede wiederholt das Motiv weiter.

---

## DECKBLATT · V60B · Profil, Kompass und Welt im Prompt (Claude) · 26.10.2026

**Befund (Nachprüfung 22:06):** Der Leserpfad Profil/Kompass/Welt → Formulierung war in der V60-Prüfung nicht geprüft. Gemessen am gesendeten Prompt (deine Session T7 und V60-E2E): Kompass-Reaktionen 0–1 von 15, Körperzeichen 0 von 15; Welt: genre, tone, epoch, long, history, storyGoals, fateBeats, Ortsbeschreibung **nicht** im Prompt; Fate las `fateSeeds` (leer), der Welt-Editor schreibt `fateBeats`.

| ID | IN | Verarbeitung | OUT | AMASTER |
|---|---|---|---|---|
| V60B.1 | Kompass der Figur | `bind_formulation_spiegel` → `compassLens` (Raum, Reaktion, Körperzeichen, Antrieb, Haltung, Hemmschwelle); `render_persona_brief` Block „DEIN KOMPASS“; Wortlinsen-Auswahl nicht mehr im Brief | alle 15 Zellen im Prompt | §15 Z. 732–746 |
| V60B.2 | Welt + Ort | `worldFrame` (Name, Genre, Ton, Epoche, Kurz/Lang, Vorgeschichte), `placeFrame` (Beschreibung, Regeln des aktuellen Orts); Block „WELT … / ORT …“ | Genre/Ton/Inhalt steuern die Formulierung | §10 Z. 375–410, §66 Z. 3310 |
| V60B.3 | Fate | `_derive_fate` liest `fateBeats` und `storyGoals` (zusätzlich zu `fateSeeds`), `mustNot` auch aus `fateBeats`; Druck als Zahl mit 2 Stellen | Druck aus der Storyachse der Welt | §47, §10, §68 Nr. 27 |
| V60B.4 | offene Angelegenheiten | nur im Vordergrund, wenn der aktuelle Turn sie berührt (neu, beantwortet, referenziert); sonst nur ID/Status im Lesestand | kein Wiederaufrufen in jedem Turn | §7, §41.4, §41.5, §49.3/49.4 |

**Offen, Entscheidung beim Nutzer:** `typicalPhrases`/`favoriteWords` tragen Herkunft `gelernt`; „Du weißt es nicht“ und „Klarheit“ wurden nachweislich aus Tammys eigener Rede gelernt (Live-Log LEARN 04:25:04 / 04:30:46) und stehen ohne Ledger im Stamm (§52). Probe ohne diese Felder: „Klarheit“ 0 von 8 statt 8 von 8.

---

## DECKBLATT · V60 · AMASTER-Einzelprüfung + Reparatur (Claude) · 26.10.2026

**Verbindliche Quelle:** `2_7master.txt` (§68 Nr. 1–94 und §28 Schritte 1–34 einzeln geprüft; Bericht im Projekt: `claude/V60_AMASTER_EINZELPRUEFUNG_20261026.md`). **Dieses Blatt ersetzt den AMASTER nicht.** Basis: zurückgeschicktes V59C-ZIP (MD5 `f5e5746494e9f630a303e6db5baf18ee`), Nutzer-DB bytegleich (`109fbd83…dc3a`).

**Fehlerereignis (Live 26.10. 20:21, Session `ses_ffd44f43…`):** Tammy wiederholt in 6 von 6 Antworten „mehr als nur Worte / Klarheit / Plan“; ihre eigene Forderung stand 20-mal im Prompt von Turn 7; ihre Forderung war nie ein Request (Plan-Etikett „Frage“ ungültig → Regex-Ersatzplan); Toms Bitte „Küss mich schatz“ erschien als ihr „Aktuell bedeutsames Ziel“; Tammy→Tom Furcht 0.70→1.00 ohne Angst-Ereignis.

### SPS IN → Verarbeitung → OUT (V60)

| ID | IN | Verarbeitung (bestehender Owner) | OUT | AMASTER |
|---|---|---|---|---|
| V60.1 | Formulierungsvertrag | `llm_contract._try_llm` System: geschlossenes Inventar für `plan.event_kind/speech_act/durability`, `refers_to` = ID `[prop_…]`/`[goal_…]`; keine Handlungspflicht (`action` null erlaubt); `beziehung` = Zielwerte; `synapsen.raum` = Bedeutungsraum; Klassen `annaeherung`/`entfernung` | gültige Pläne statt „Frage“; Modell darf schweigen/ruhig bleiben | §7, §35, §36.1, §50, §68 Nr. 67 |
| V60.2 | ungültiger Antwortplan | `kernel.commit_turn` (Antwort) und `commit_puppet`: kein `local_plan`/`infer_lifecycle_kind` mehr, sondern `literal_plan` (source `unresolved`) | Regex kann keinen Lifecycle mehr schreiben (kein Widerruf durch „nicht mehr“) | §24.6, §34.1, §68 Nr. 35/54 |
| V60.3 | Forderung/Bitte einer Figur | `apply_proposition`: Request mit `matter` (Plan-Zusammenfassung); Wiederholung mit `refers_to` = dieselbe Proposition (`evidence: restated`), keine neue | eine Angelegenheit, Wiederholungszahl als Zustand | §35, §36.1, §41.3 |
| V60.4 | Antwort des Empfängers | Eingangsplaner sieht offene Angelegenheiten und Ziele des Angesprochenen mit ID (`offen`), Komponente `bezug`; Kernel `_bind_response_to_request` / `_bind_act_to_goal` prüft Empfänger/Owner | Handlung/Antwort als Evidenz derselben Proposition bzw. am Ziel (`recentExperiences`) | §34.1, §35 |
| V60.5 | Annahme | `apply_proposition`: Annahme durch den Steller nach gebundener Antwort → `fulfilled`; ohne Antwort keine Wirkung; `apply_owner_goal_decision`: nur die Eigentümerin schließt ihr Ziel, nur mit `refers_to [goal_…]` (Lifecycle-Fact) ; Frame-Annahme/-Ablehnung nur durch den Empfänger | Lebenszyklus aus Evidenz | §35, §36.2, §36.3 |
| V60.6 | Beziehungsvorschlag | `apply_synapses`: Zielwert − aktueller Wert, ±0.15, nur mit `grund`, nie für den Avatar, je Ursache einmal (`appliedCauses`); `grund` nicht mehr an die Stamm-Notiz gehängt | Echo = keine Änderung (keine Ratsche) | §44, §45, §68 Nr. 63/85 |
| V60.7 | Wortlinse | Chat-Rede/-Handlung: `apply_knowledge_effect` (Kompass-Wortliste) und `_THREAT/_RESIGN/_REQUEST_RE`-Zweig entfernt; Commit nutzt nur `fire_from_proposals` (semantisch, Schwelle der Figur); Linse im Brief nur über Schwelle, als Kandidat | kein Zustand aus Worttreffern, Avatar-Beziehung unberührt | §15, §24.6, §27.3, §68 Nr. 20/54/81 |
| V60.8 | zärtliche Handlung | `_apply_physical` social: keine festen trust/closeness-Inkremente, keine Eigen-Emotion; `set_spatial` (SceneState `spatial`: beruehrung/nah/abstand, Wiederholungszähler); Ortswechsel löscht Raumrelationen | Nähe ist Raumzustand, kein Vertrauen | §43.2, §68 Nr. 45/46/59/60 |
| V60.9 | Szene | `scene_state`: Eskalation nur durch validierte `strike`/`restrain`; keine Emotions-Eskalation; Brief ohne „Nächster Beat … das bist du“ / „Antworte aus der offenen Szene“; RAUM-Zeile | kein globaler Psychozustand, keine Beat-Pflicht | §7, §68 Nr. 67/75/86 |
| V60.10 | Brief/Spiegel | `bind_formulation_spiegel`: DU WEISST = Stammwissen; Erinnerungen ohne Sätze, die im sichtbaren Verlauf stehen oder schon als Angelegenheit gezählt sind; „So begann“ nur bei Verlaufsfrage; Vordergrund-Ziele nur eigene (mit ID + Exit aus dem Profil), Request-Ziele als OFFENE ANGELEGENHEITEN; Bitte-Frames und `openDemands` nicht doppelt; Behauptungs-Frames als „Behauptung von …, nicht bestätigt“; JSON-Lesestand ohne Plan-Textkopien | jede Evidenz einmal | §38, §39, §41.3, §41.5, §49, §68 Nr. 10/24/85 |
| V60.11 | Regie-Folgeturn | kein AutoChat-Auftrag und keine Fate-Richtung, wenn die Regie-Handlung vollzogen ist | Regie-Handlung ist der Stimulus | §27.5, §46.6, §47 |
| V60.12 | Antwort-Memories | eine „gesagt“-Memory je Rede (Sprechakt aus validiertem Plan), „getan“ ohne Kopie als „erlebt“, alle mit `factId`/`sourceTurnId` | keine Dubletten | §38 |
| V60.13 | Wissenszugang | `_bind_scene_perception`: Client-`informedIds/affectedIds` verworfen, `avatarId` aus der Session; `recall`: Regie-Anweisung ist kein Figurenwissen | kein Wissen über Client-Felder | §26, §28 Schritt 2/8, §39, §68 Nr. 7 |
| V60.14 | Fate | Namen statt IDs, Avatar-Innenbeziehung nicht gelesen, offene Angelegenheit als `matter` | lesbarer Druck (Fate-Generator selbst bleibt offen) | §47, §49.6 |
| V60.15 | Log | `live_log.session_delta`/`prompt_sections`; Stufen TURN_INPUT, PROMPT (+ Wiederholungszählung im gesendeten Text), MODEL_REPLY (+ plan_valid), TURN_RESPONSE, TURN_REGIE; VALIDATION meldet ehrlich `BINDING_PASS` | Parser, Validator, Writer und Reader im Log sichtbar | §54 Punkt 15, §68 Nr. 70 |

### Offen (geprüft, nicht gebaut) — siehe Prüfbericht

Finalizer §51.3 (Probe mit gpt-4o-mini wirkungslos), Fate als Gelegenheitsgenerator §47, Identität/Alias/Control §24.1, mehrere Ziele §25, Hören/Sehen-Feinbindung §26, Attention/Engagement-Writer §41.4/§42.1, Zustimmung §36.5, Outcome-Resolver/Capability nach Klasse §43/§43.1, Objektzustand §43.2, Effect-Datensatz (effect_id/depends_on) §34.2, God-Scope/Parser (Negativliste), Source-Axis §11/§47.2, Upload-/Systemschleifen-Writer, Emotions-Decay §42.

### Abnahme (getrennt)

- **GRÜN:** 18 neue Tests `test_v60_master_repair.py`, SPS-Skript 5/5; Gesamtlauf ohne neue Fehler gegenüber V59C (Nutzer-DB 131/50, Alt-DB 149/32 — alle Rot identisch mit V59C, fehlende Testdaten).
- **Live (gpt-4o-mini, Nutzer-Schlüssel, DB-Kopie, Flask-Routen):** Forderung = eine Proposition mit Wiederholungszahl, Antworten gebunden, Tammy→Tom unverändert 0.30/0.80/0.70, Eskalation 0.00, keine „lehnt sich näher“-Schleife, eigene Sätze 2–3× statt 20× im Prompt. **ROT bleibt:** Tammys Motiv „Klarheit / mehr als Worte / Beweis“ steht weiter in fast jeder Antwort (Läufe 1–4, je 8 Antworten; Zählung im Prüfbericht); Ablationsproben am echten Prompt (ohne Wendungen, ohne eigene Forderung, ohne Zustand, ohne eigene Verlaufssätze, ohne JSON, mit Finalizer-Befund) ändern das nicht.
- **NICHT geprüft:** Android, Langzeitdialog, anderes Modell.

---

## DECKBLATT · V59C · Effekt-Stufe (Claude) — Eingang, Regie, Figurenhandlung · 26.10.2026

**Verbindliche Quelle:** `2_7master.txt` §24.2, §24.3, §24.6, §24.7, §25, §27.3, §27.5, §34.1, §46.2, §46.6, §68 Nr. 32/33/54/69/70/90. **Dieses Blatt ersetzt den AMASTER nicht.** Basis: V59-ZIP des Nutzers (SHA-256 `34eca8bb…dcfdd69b`), Nutzer-DB bytegleich (`97d9e183…886d`).

**Fehlerereignis (Live 26.10. 18:26, Session `ses_e0239e1f…`):** „Hey mein schatz, ich küsse dich“ und „ich streich zart über den gesicht“ wurden als Rede gespeichert (ein Modell-Etikett pro Satz, ungültiges Etikett → ganzer Satz Rede); Regie „Küss Tom, und sag das du ihn liebst“ wurde nicht vollzogen, sondern ans Modell delegiert (Ziel Tammy statt Tom, alter Satz als „JETZT SAGT“, falscher Hinweis „Tom ist nicht der Avatar“); „fixiert Tom mit einem durchdringenden Blick“ fesselte den Avatar über die Wortliste (`restrained`, Emotion „Angst“).

### SPS IN → Verarbeitung → OUT

| ID | IN | Verarbeitung (Owner) | OUT | AMASTER |
|---|---|---|---|---|
| C1 | Avatar-Eingabe (Text) | `llm_contract.PLAN_RULES` liefert zusätzlich `komponenten` (rede/handlung, wörtliches Segment, Akteur, Ziel, Zeit, Wirkungsklasse) → `kernel.bind_input_components`: Segment muss im Eingang stehen, Akteur = Sprecher, Zeit = jetzt, Ziel anwesend; Rest außerhalb der Handlungen bleibt Rede | je Komponente eigener SceneFact (gleiche `source_turn_id`), Memory „erlebt/gehört/gesehen/getan“ getrennt; Zweifel als `input_component_ambiguity` sichtbar, nichts geraten | §24.2, §24.7, §34.1 |
| C2 | Regie-Text | `llm_contract.extract_regie_components` (vor der Schreibsperre) → `kernel.bind_regie_components` → `apply_regie(components=…)`: Akteur/Ziel ausdrücklich gebunden, angeordnete Handlung vom Regie-Writer committet, angeordnete Rede bleibt Anweisung an die Figur | Handlungs-Fact (authority regie) + Wirkung + Memories; Folgeturn-Brief: „REGIE (bereits vollzogen …)“ + nur noch der Rede-Auftrag; Regie-Text ist für niemanden „gehört“ | §27.5, §46.2, §46.6 |
| C3 | Figurenhandlung (Modell) | Formulierungsvertrag liefert `wirkung {art, ziel}`; Kernel validiert Klasse und Ziel | Körper-/Beziehungswirkung nur aus validierter Klasse; „ohne_koerperwirkung“/unklar → keine Wirkung | §24.6, §28 Schritt 29/30, §68 Nr. 54 |
| C4 | `_apply_physical` | neuer Parameter `effect_kind`; Avatar-Schutz | Avatar: keine erfundene Emotion/Angst/Beziehung, nur objektive Körperfolge; Beziehungsnotiz wird nicht mehr durch Ereignistext überschrieben (`lastEventText`) | §27.3, §44, §68 Nr. 90 |
| C5 | Betroffene | `commit_turn` (Antwort) nimmt das Ziel der Handlungskomponente; Graph-Kante zum Ziel der Antwort | geküsste Person bekommt „betroffen“; keine Selbstkanten | §25, §34.1 |
| C6 | Brief | `bind_formulation_spiegel` spiegelt Komponenten | „JETZT SAGT …“ (Rede) und „JETZT TUT … (Handlung, ist geschehen)“ getrennt; bei Regie kein alter Satz; Avatar bleibt als Avatar markiert | §41.1, §49 |
| C7 | Wortlisten | `split_star_action` nur noch Marker; `scene_state` ohne Wortliste | Wortlisten entscheiden keinen Typ und keinen physischen Beat mehr | §24.6, §68 Nr. 54 |
| C8 | Log | WRITER listet alle Facts des Turns; `EFFECT_PLAN`-Zeile je Eingang/Regie | Writer-/Planerwirkung diagnostizierbar | §68 Nr. 70 |

### Bewusst NICHT geändert (offen, eigene Punkte)

- Beziehungs-Ratsche (`apply_synapses` deutet Modell-Absolutwerte als Delta → Furcht 1.00), lexikalische Kompass-/Synapsen-Linse und Rede-Trigger (Drohung/Bitte), Fate-Druck/„Folge offen“, `raum`-Feldname, READER-Log im Frontend (`slice(0,8)`).
- God und Puppet nutzen weiter den alten lexikalischen Weg (GodCommandParser steht auf der Negativliste).
- Profil Tammy: „Typische Wendungen“ (Herkunft `gelernt`, ohne Ledger) und Reaktionsmuster mit „Phase 1/2/3“ – Nutzerentscheidung.
- Frontend unverändert (Kopfzeile zeigt V59-Build-ID, Startseite den Backend-Build V59C).

### Abnahme (getrennt)

- **GRÜN:** 131 Tests (inkl. 16 neue `test_v59c_effect_components.py`), SPS-Skript 5/5, Nutzer-DB bytegleich.
- **Alt-ROT unverändert:** 32 Fehler in `test_v25_chains.py` (erwartete Testdaten `world_rp5zlymrrpmd` fehlen in der Nutzer-DB; identisch in V57/V59).
- **Live (echtes Modell gpt-4o-mini, Nutzer-Schlüssel mit Freigabe, DB-Kopie):** Planer-Probe 22/22 (Kuss, Streicheln, Gerede über Küssen, Zukunft/Vergangenheit, Frage, Setzen); Flask-Routen-Lauf und **echter Browser-E2E** (START.py + Chromium, Sprecher „Avatar“): Kuss und Streicheln als Handlung, Tammy „erlebt“, Avatar unverändert, Regie-Kuss vom Kernel vollzogen, danach „Ich liebe dich, Tom.“
- **NICHT geprüft:** Android, AMASTER-Gesamtabnahme, Langzeitdialog.

---

## DECKBLATT · V59 · FB08M — Foreground / Fate / Formulierungs-Reader · 26.10.2026

**Verbindliche Architektur:** `2_7master.txt` (§7, §15, §35, §41.1–41.5, §47, §49.1–49.6) und `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt`. **Dieses SPS-Blatt hat KEINE Autorität, AMASTER zu ersetzen.** Alle V58- und älteren Abschnitte sind historische Nachweise; widersprechende Aussagen sind mit V59 ausdrücklich überholt.

**Fehlerereignis FB08M (Auslöser):** Ein Teiltest der V58 verlangte ausdrücklich die Übertragung ALLER Profilziele in jeden Modellrequest. `render_persona_brief` gab komplette Profilziele aus, `bind_formulation_spiegel` hatte außerdem alle GoalStates im Spiegel, `currentState.goals` und `goalEvidence`; `_derive_fate` erzeugte Beats aus jedem offenen Ziel und suchte jeweils die nächste andere Zeile. Das war kein AMASTER-§41-Foreground und keine kausale §47-Fate-Arbitration.

**Zweck / Abgrenzung:** Die *bestehende* kanonische Goal-/Fact-/Session-/Runtime-/Relationship-SQL-Struktur bleibt Eigentümer. Neu ist **nur eine begrenzte, transiente Reader-Auswahl** im vorhandenen Kernel vor der bereits existierenden Formulierung. Keine neue Tabelle, kein Shadow-Ledger, kein Charakter-Sonderfall, keine nachträgliche LLM-Textreparatur. Die freie semantische Abwägung und die vollständige menschliche Langzeitentwicklung sind damit **nicht** als gelöst behauptet.

### SPS-IST-/SOLL-Karte und Ursache

| ID | Datei/Funktion | Eingang / bisheriges Verhalten | V59: Lesen/Schreiben und Ausgang | Owner / Abhängigkeit | AMASTER |
|---|---|---|---|---|---|
| FB08M.1 | `kernel.reduce_goal_state` (ab Z. 1065), `recall` (5510) | Reduziert Lifecycle aus belegter Sessionevidenz; laden weiterhin alle Owner-Ziele | **Unverändert**: Goal-Fakten, Quellen und vollständige Historie verfügbar | SQLite Goal/Fact/Knowledge; **Writer bleibt kanonisch** | §35, §41 |
| FB08M.2 | `kernel._arbitrate_goal_foreground` (5897) | Fehlende situative Ziel-Auswahl; zuvor jedes offene Goal in den Prompt | **NEUER Reader im vorhandenen Kernel**: aktuelle Eingabe, ausdrücklich gebundene `goal_id`, vorhandene Aufmerksamkeit/Preoccupation/Engagement und begrenzte Themenüberlappung auswählen; nicht gewählte Ziele nur als Referenz (ID/Status/Art) im Background. **Schreibt nichts.** | `TurnTruth` + `recall` + Runtime; **kein Goal-Owner** | §41.1–41.5 |
| FB08M.3 | `kernel.bind_formulation_spiegel` (6008) | Voller Profil-/GoalState-/CurrentState-Goaltext erschien unabhängig von Situation | Formulierungsprojektion mit **Constraint Context**, **Immediate Stimulus**, **Character Foreground**, **Background Reservoir**, **Deferred Topics**; nur gewählte GoalStates und Evidenzen. `profile.goals` bleibt für Editor/Diagnose vollständig, nicht Modell-Transport. Fate-Kopie vor mustNot-Fallback verhindert Reader-Mutation. | BrainContext nur Spiegel, nicht Writer | §41, §49 |
| FB08M.4 | `llm_contract.render_persona_brief` (394), `_try_llm` (564), `canonical_formulation_context` (919) | Profilziel-Volltext wurde bei jeder Rede vorangestellt, anschließend wieder als strukturierter Modellzustand übertragen | Vollziel-Dump entfernt; nur situativ gewählte Goals im Brief. Provider-Payload führt die fünf getrennten Reader-Abschnitte, keinen ungefilterten Profile-Goal-Owner. Kein Prompt-Guard, kein Zweitaufruf hinzugefügt. | Bereits autorisierter Session-Reader → Providertransport; LLM schreibt keine Wahrheit | §49 |
| FB08M.5 | `kernel._derive_fate` (3713), `commit_turn` (2382), `apply_fate` (3667) | Alle offenen Goals als Fate-Textkandidaten; `next(b != prev)` rotiert ohne Ereignis | Ungebundene Goaltexte erzeugen **keinen** Fate-Beat. Stabile bestehende Kandidaten bleiben stabil; Kandidatenwechsel setzt bei vorhandenem Beat eine neu committete kausale Szene-/Eingabewirkung voraus. `apply_fate`/Commit bleiben vorhandene Writer. Explizite Fate-Setzung unverändert möglich. | Session/Fate-Owner; keine direkte Wahrheitserzeugung | §47 |
| FB08M.6 | `src/lib/matrix/types.ts`, `frontend_dist`, `VERSION.txt` | Browser-Assets/Build-ID V58 | Build-ID V59, Assetcache-Verweise V59F durchgängig. **Keine fachliche UI-Neuerfindung**, kein Vite-Neubau. | UI Anzeige; kein Truth-Owner | §49 |
| FB08M.7 | `test_v59_foreground_fate.py`, `test_v58_goal_contract.py` | V58-Test 14 verlangte alle Ziele im Brief | Gegentest: Gruß → 0 Vordergrundziele, Werkstatt-Thema → genau das Ziel, explicit Fact-ID → Ziel, Deferred → Hintergrund, keine Fate-Rotation, kein Reader-Write, echter Provider-Payload-Serializer mit kontrollierter Modellantwort | Tests, nicht Produkt-Wirkung | §35, §41, §47, §49 |

### Durchgängiger Ein-/Ausgang (weder Schattenpfad noch Promptreparatur)

```text
EINGANG: aktueller Turn / TurnTruth / Authority / Sprecher / Anwesenheit
          │
  kernel.commit_turn(input)       [bleibt Ereignis-/Wissens-/Goal-Writer]
          │ SceneFacts, WitnessKnowledge, Runtime, Goals -> SQLite
          ▼
  llm_contract.canonical_formulation_context [lädt AUTORISIERTE Session]
          │
  kernel.prepare_turn → recall / reduce_goal_state [ALLE gültigen Owner-Fakten]
          │
  kernel._arbitrate_goal_foreground [NUR LESE-AUSWAHL, ohne Owner-Änderung]
          ├─ Constraint: Authority, Anwesenheit, Body/Capability, Weltregeln
          ├─ Immediate Stimulus: gebundene Äußerung und Quellturn
          ├─ Character Foreground: hier und jetzt belegte Ziele/Attention/Engagement
          ├─ Background Reservoir: alle anderen Goals nur mit ID/Status/Art
          └─ Deferred Topics: ausdrücklich zurückgestellte Gegenstände
          │
  bind_formulation_spiegel → render_persona_brief / _try_llm [spiegelt]
          │ LLM-Formulierung ist nur Vorschlag, kein Truth Owner
          ▼
  kernel.commit_turn(response)   [vorhandene Validierung und Wirkung]
          │
  _derive_fate [Kandidaten aus Situation; KEINE Goal-Zeilenrotation]
          ▼
  SQLite Session/Fate/Scene → künftiger Recall
```

### Konkrete Gegenbeweise / Negativtests

| Prüfereignis | unveränderte V58 | V59 |
|---|---:|---:|
| Neun neue Reader-/Fate-Tests | 6 fehlgeschlagen, 3 bestanden | **9 bestanden** |
| Generische Begrüßung → Zieltexte in Formulierungsrequest | ja | **nein** |
| Konkretes Ereignisthema → nur damit verbundenes Ziel | nein | **ja (Themen-/ID-Gegenprobe)** |
| Deferred-Ziel und historische Erfahrung → keine automatische Reaktivierung | nein | **ja (kontrollierter Reader-Test)** |
| Mehrfaches Fate-Lesen ohne neuen Kausalbeleg → kein rotierender anderer Goal-Beat | nein | **ja** |
| Original-GoalState/Session-/SQL-/Profildefinition | nicht gelöscht | **unverändert** |

### Abnahmeprotokoll (getrennt, keine fiktiven Erfolgszahlen)

- **GRÜN:** 101 gezielte Python-/Kernel-/SQLite-/Provider-Serializer-Tests, `pytest` isoliert ohne Flask; zusätzlich 5 echte SQLite-Prüfblöcke auf **KOPIE** der mitgelieferten DB. 9 V59-Tests grün. Python-CompileAll grün.
- **NICHT GRÜN / hier nicht ausführbar:** vier zusätzliche Flask-Integrationstests scheitern beim `from flask import Flask`, weil Flask in dieser Umgebung nicht installiert ist. Ein vollständiger Flask-/Android-Live-Test wurde NICHT durchgeführt.
- **KEIN LLM-LIVE-BEWEIS:** Die Providerantworten sind kontrolliert; keine echte Modellbeurteilung darüber, ob Tammy keine Sätze mehr wiederholt. Es gibt keine allgemeingültige Semantikbewertung von Ziel-/Stimulusbezug; die aktuelle Reader-Auswahl benutzt gebundene IDs plus lexikalische Überlappung als begrenzte Näherung. Existierende LLM-Stilwerte/typische Wendungen können weiter wirken.
- **NICHT automatisch repariert:** alte Sessions mit bereits gespeichertem Fate-Beat oder historisch falsch committed Facts werden nicht geändert; freie `goal.exit`-Bedingungen werden nicht neu als Phasentor interpretiert; keine flächendeckende Abnahme sämtlicher AMASTER-Subsysteme.
- **Frontend:** vorhandener V58-Funktionsstand mit V59F-Cachemarkierung; kein neuer Vite-Build, keine Android-Visionsprüfung. Assetreferenzen vollständig geprüft, keine fehlenden V59F-Referenzen.

### Dateiidentität / unveränderte Eingangsquelle

```text
EINGANG_V58_ZIP_SHA256=9e1c7a7aea24a1260ead1484fedca145d7f7c427cd05123fd8a68d9bfa6115e2
V59_SQLITE_UNVERAENDERT_SHA256=2cb2e47b4c2189d9b9001d2a677d9950eca762ba8ee8712285e33b7e2d07576e
AMASTER_2_7master_txt_SHA256=095d455460390dfd0ae46e6938126e44a51293461d070204358d301f00609a7f
KETTENVERTRAG_SHA256=e62cf6bc606a13a72044ab135697e209f7cb0bcf0a2b36ff7e1f153bf290bd
matrix_api/kernel.py=27c53a698968610d365862732f4a23466b0793bc28c6f8a772eabcc6a7b43ce0
matrix_api/llm_contract.py=9c34d5b97675670ba4aafd706223dc428efc5d8bcb7131e0b7a7369a987619a3
matrix_api/tests/test_v58_goal_contract.py=7b2302a3e169958652a5b7ff9063cf1bddbf50fb623259412695b77626ed947e
matrix_api/tests/test_v59_foreground_fate.py=f497d206a48b252e7b524c1163fcb573b978d6c12e5676e70652176c91db54fb
src/lib/matrix/types.ts=5e00092eeeb6fa242cfdc78b8a39f88d7812e1a3d3e21ec2dcf174d899806ab4
frontend_dist/index.html=8be2106f18f435bce77f37d7cf7b008243785bcfa241512033cb0c25484d968c
frontend_dist/.build-info.json=62a085adbd72dd04d1dafabfc02296719764d6749bbdacecba5f4b1d56a7b3c8
```

**Veröffentlichungsstatus: FB08M-Reader-/Fate-Regression lokal grün, AMASTER-Gesamtabnahme NICHT erbracht.**

---

## Historische Prüf-/Änderungschronologie V58 und davor (Stand der jeweiligen Version, durch V59 teils überholt)

# MATRIX10 / AMASTER - einziges SPS-Masterblatt
## V58 - Ziel bleibt Ziel; keine erfundene Phasensperre - 26.10.2026

**Korrekturumfang:** Die in V52 hinzugefuegte Ziel-Phasenmaschine wird aus dem bestehenden
Sessionstart, Goal-Writer, Recall und Timeline-Pfad entfernt. **Zieltexte und Charakterstamm
werden nicht umgeschrieben.** Kein neuer Verhaltensautomat, kein Tammy-Sonderfall, kein
Umschreiben von Modellantworten. Bestehender Action-Commit aus V57 bleibt erhalten.

**Architekturmassstab:** `2_7master.txt`, Stand 22.09.2026, unveraendert beigelegt.
7: aktives Ziel ist keine Sprech-/Handlungspflicht; 14/18: Stamm und neue Session;
21: Timeline als Evidenzdarstellung; 35: Goal-Lifecycle aus gueltiger Evidenz;
41/42: Recall ist nicht Aktivierung, aktueller Intent nicht automatisch Stammziel.
Der Kettenvertrag verlangt den zustandigen Writer, SQL, Folgereader und sichtbaren Zustand.
Das SPS-Blatt ist ausschliesslich Buildnachweis, keine neue Architekturquelle.

**Abnahme:** Lokal getesteter Rueckbau der Phasensteuerung; gesamte Dialogfunktion
**TEILGESCHLOSSEN / keine Freigabe als AMASTER-Gesamtsystem**. Kein Beleg fuer garantierte
Wiederholungsfreiheit im freien LLM-Dialog. Eine automatische Bewertung beliebiger
frei formulierter Lebensziele wird nicht als implementiert ausgegeben.

```text
EINGANG 1  Neue Sitzung in bestehender UI; Welt + User + freigegebene Charaktere
  FB08M.1  repos.create_session -> kernel.build_new_session
    Stammziele komplett/mischbar lesen -> je ein offenes Goal mit stabiler ID
    Originaldefinition/Quelle/Prioritaet erhalten; phase/next/exit sind KEINE Steuerung
    initial_character_intent / reset_runtime_only -> kein erfundener Erstziel-Intent
    SQL sessions + goals + runtimes; Originalstamm unveraendert

EINGANG 2  Bestehender gebundener Ereignis-/Effect-Commit
  FB08M.2  SceneFact + Actor + Goal-/Proposition-ID + validierte Authority + Scope
    reduce_goal_state -> neueste gueltige Lifecycle-Evidenz -> betroffener Goalstatus
    kein Folgeziel freischalten; keine Erfuellung durch Wort/Turnzahl/Begruessung
    apply_goal_experience -> nur explizit zugeordnete Goal-/Propositionserfahrung
    wahrgenommener Eingang bleibt Memory/Attention auch ohne Zielzuordnung
    reale vorhandene Ereignisfolgen duerfen weiter einen aktuellen Intent schreiben
  FB08M.3  save_session -> bestehende append-only Facts + mutable Goal-Writer -> SQLite
    create/patch_session_goal akzeptiert keinen unbelegten Abschlussstatus
    ungebundener Statusklick -> GOAL_EVIDENCE_REQUIRED; keine Fake-Ereignisse

AUSGANG    SQL-Neuverbindung -> hydrate/reduce -> recall/bind_formulation_spiegel
  FB08M.4  Profilziele und Goal-Lifecycle separat; aktuelle Absicht nur aus Runtime
    keine Auswahl des ersten Ziels als AutoChat-Auftrag
    vorhandener SQL-gebundener Providerrequest -> genau ein Formulierungsversuch
    bestehender Antwortcommit -> Folgeturn; keine Outputfilter hinzugefuegt
  FB08M.5  Timeline: alle Ziele + aktueller Status + Lifecycle-Fact-ID sichtbar
    alte Erfuell-/Freischaltknopfgruppe entfernt; Ziele anlegen bleibt bedienbar
    Source UND ausgeliefertes JS geaendert, Assetnamen/Verweise V58G
```

### Was erhalten bleibt

Alle freigegebenen Ziele einschliesslich ihrer originalen Definition, Reihenfolge und
Prioritaet. Ein gemischtes Profil aus Text- und Objektzielen verliert keine Textziele.
Die Quelldefinition wird unter `sourceDefinition` erhalten, nicht durch eine neue
Zieldefinition ersetzt. Die vorbestehende V56-Trennung unfreigegebener Session-Lernwerte
vom Stamm bleibt unveraendert. Aktuelle Absichten koennen weiterhin aus Ereignissen
entstehen; neutraler Start bedeutet nicht, dass Figuren dauerhaft absichtslos bleiben.
Alte Sessiondaten werden nicht migriert oder geloescht. Der Rueckbau der Startlogik
ist in einer neu angelegten Session wirksam; historische falsche Statuswerte bleiben
als solche in alten Sessions bestehen und sind keine neue Abnahmebasis.

### Nachweis am unveraenderten V57 und an V58

| Pruefung | Unveraendertes V57 | V58 |
|---|---|---|
| Alle autorisierten Ziele inkl. gemischter Text-/Objektziele | Teilweise verworfen/gestaffelt | erhalten, keine next-Sperre |
| Zielreihenfolge als aktuelle Absicht | erstes Ziel wird Intent | keine solche Ableitung |
| Timeline-Klick `fulfilled` ohne Ereignis | schreibt Status + Folgestufe | 409 ohne Schreibwirkung |
| Neues Goal direkt mit unbelegtem Abschlussstatus | akzeptiert | 409 ohne Schreibwirkung |
| Bestehender Proposition-Writer -> Lifecycle -> SQL-Neuverbindung -> Goal-Recall | keine gebundene Goal-Lifecycle-Provenienz im Reader | accepted + Lifecycle-Fact-ID; andere Ziele unveraendert |
| Dieselben 26 neuen Vertragspruefungen | 24 fehlgeschlagen, 2 bestanden | 26 bestanden |
| Vorhandene 64 Zielbereichs-Tests | 64 bestanden (inkl. falscher Phasenvorgaben) | 64 bestanden nach unten erlaeuterter Vertragskorrektur |

**Wichtig zu den Testaenderungen:** Acht Alt-Tests aus V54/V55/V56/V57 verlangten
entweder ein active/pending-Phasentor, die erste Profilzeile als Intent oder jede
wahrgenommene Aussage als Erfahrung fuer jedes Goal. Diese Erwartungen wurden
gegen AMASTER korrigiert, nicht die Tests abgeschaltet. Positive Pruefungen fuer
Ereignis, Memory, Witness, Action-Typ, Request-Transport und Isolation bleiben.
Der alte FB04-Block im SQL-Runner verlangte eine Erfuellung per Timeline-Klick plus
zwei kuenstliche Facts; er prueft jetzt die entgegengesetzte, vertragliche Grenze.
Deshalb ist der neue Rot/Gruen-Vergleich separat am unveraenderten V57 ausgefuehrt.

**Tatsaechlich ausgefuehrt:** 90 gezielte lokale Tests; fuenf bestehende SQL-Pruefbloecke.
Neue Session ueber echte Repository-Writer; SQLite-Commit und neue Verbindung;
positive Lifecycle-Folge ueber `apply_proposition` statt Statusklick; falscher
Owner/Scope/Actor, unvalidierte Evidenz, unverknuepfte Facts, gemischte Ziele,
mehr als acht Figuren, Runtime-Reset, realer Intent nach Ereignis, unveraenderter
Stamm und ein abgefangener echter Providerrequest mit vollstaendigen Zielen.
23-Turn-Speichertest prueft Wahrnehmung/Memory ohne automatische Zielerfuellung,
nicht menschliche Qualitaet vorgegebener Testantworten.

**Statisch:** 39 Python-Dateien parsebar, 84 TS/TSX-Dateien transpiliert ohne Syntaxfehler,
41 ausgelieferte JS/MJS-Dateien `node --check`; 225 V58G-Assetverweise ohne fehlende Ziele.
TS-Transpilation ist kein vollstaendiger Typcheck. Das ausgelieferte Timeline-Bundle
wurde zur Source-Paritaet bearbeitet und alle 42 Assetnamen/Verweise erneuert,
nicht mit Vite neu gebaut.

**Nicht ausgefuehrt:** Kein kostenpflichtiger oder externer Modellaufruf, keine
Android-/Browser-Langzeitabnahme, keine echte Flask-HTTP-Abnahme. Flask ist in der
Pruefumgebung nicht installiert; ein Installationsversuch war erfolglos. Die
bereits vorhandenen Tests nutzen fuer Imports einen Flask-Import-Shim, nicht einen
Fake-Repository-Writer. Route-/Browsertests werden daher nicht als bestanden gezahlt.
Die vorhandene Wortmuster-/Kompass- und freie semantische Gesamtarchitektur ist
nicht durch diesen Rueckbau als vollstaendig AMASTER-konform zertifiziert.

### Bedienung und Daten

Alte Anwendung beenden; V58 separat entpacken; `python START.py`. Neuere lokale Daten
vorher sichern und bei Weiterverwendung den vollstaendigen eigenen `data`-Ordner
bei beendeter Anwendung uebernehmen. Nicht die eigene neuere Datenbank durch die
Paketkopie ersetzen. Neue Session verwendet die korrigierte Zielinitialisierung.
Der Figureneditor bleibt Owner deiner Zieltexte. In der Timeline ist Status plus
Evidenzquelle sichtbar; ein Klick ist kein Ersatz fuer ein geschehenes Ereignis.

<details><summary>Aenderungen, Funktionsstellen, Dateihashes und Wiederholungspruefung</summary>

| ID | Datei / Funktion | Grund / Eingang -> Ausgang |
|---|---|---|
| M01 | kernel.py: build_new_session, initial_character_intent, reset_runtime_only | Autorenprofil -> vollstaendige unabhaengige Goals; keine Phasensperre oder Boot-Absicht |
| M02 | kernel.py: reduce_goal_state, reduce_current_state, commit_session_change | gebundene gueltige Lifecycle-Facts -> aktueller Goalstatus, keine Kettenaktivierung |
| M03 | kernel.py: apply_goal_experience, recall, bind_formulation_spiegel | Goal-ID/Proposition-ID statt allgemeiner Adressierung; Wahrnehmung bleibt im Memory/Attention-Pfad |
| M04 | repos.py: hydrate_session_from_sql, create_session_goal, patch_session_goal | SQL-Readback/Write respektiert Lifecycle-Evidenz; keine erfundene Operator-Erfuellung |
| M05 | llm_contract.py: render_persona_brief | bestehender Spiegel trennt langfristige Ziele und aktuelles Wollen; AutoChat nicht auf erstes Ziel verpflichtet |
| M06 | src/routes/timeline.tsx und ausgeliefertes Timeline-JS | Status-/Quellenanzeige statt manipulierender Zielstatusknoepfe |
| M07 | src/lib/matrix/types.ts, frontend_dist, VERSION.txt | Buildkennung + mechanische V58G-Assetreferenzen gegen veraltete Browsermodule |
| M08 | tests/test_v58_goal_contract.py; acht oben bezeichnete Alt-Tests; scripts/test_v53_sps.py | normativer Vorher-/Nachhervertrag; nicht Test des erfundenen Phasentors |

**Funktionspositionen in dieser Ausgabe:**

- `matrix_api/kernel.py:818-862` `commit_session_change`
- `matrix_api/kernel.py:1065-1122` `reduce_goal_state`
- `matrix_api/kernel.py:1125-1168` `reduce_current_state`
- `matrix_api/kernel.py:1585-1653` `apply_goal_experience`
- `matrix_api/kernel.py:4993-5145` `build_new_session`
- `matrix_api/kernel.py:5148-5154` `initial_character_intent`
- `matrix_api/kernel.py:5157-5191` `reset_runtime_only`
- `matrix_api/kernel.py:5498-5591` `recall`
- `matrix_api/kernel.py:5885-6239` `bind_formulation_spiegel`
- `matrix_api/repos.py:1283-1294` `hydrate_session_from_sql`
- `matrix_api/repos.py:3351-3391` `create_session_goal`
- `matrix_api/repos.py:3394-3433` `patch_session_goal`
- `matrix_api/llm_contract.py:394-563` `render_persona_brief`

**Eingang / unveraenderte Originale:**

```text
V57_ZIP_SHA256=5bfb2df07b8ce848219c12cec5a5c7aeb6ba3d40de2fd876f90a069f593ddec5
V57_ZIP_BYTES=5655033
095d455460390dfd0ae46e6938126e44a51293461d070204358d301f00609a7f  2_7master.txt
e62cf6bc606a13a72044ab135697e209f7cb0bcfbc0a2b36ff7e1f153bf290bd  VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt
c1e5a85ef0469aa0146ecf50db6aa728d7bb2c2cf838383e87f408b3ab104177  data/matrix10.sqlite
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  data/matrix10.sqlite-wal
fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb  data/matrix10.sqlite-shm
f0f0b61b8e4d74bea966711722a8d1442a37f8fddf68d608dcedb188efcab154  logs/MATRIX10_LIVE.log
```

**Geaenderte oder neue Dateien gegen das Eingangs-ZIP:** (mechanische Assetumbenennungen sind ausdruecklich enthalten)

```text
095d455460390dfd0ae46e6938126e44a51293461d070204358d301f00609a7f  2_7master.txt
0bea6a3ecd984a8da2b41a3504610492abbe56f6e67b68344abf505032600ab2  README.md
27433b6b668f600f5b895532cb4e35c28e8734d0c03d21cdc5822f478172cdd4  VERSION.txt
537fa3b72359ded9042490c6e74fa5fece233458a6c3c034a092391665010c52  frontend_dist/.build-info.json
49e045abc4398ecc1c5fc0ad1bb08d18990995e1cb157b0f3018c43a93e1abc6  frontend_dist/assets/admin-DZOQfYB5-V58G.js
2896f9103862bc6aac56bd555028554342406dfc9560182ae64f31fb59f5b91d  frontend_dist/assets/api-ClGRQEGP-V58G.js
b0d4a42c1fc0b25b0d80c4a10c90c24b20df6f1683c5e9a8c81897a4b063c63d  frontend_dist/assets/char._charId-DJ7LAi8J-V58G.js
d6df6fe89bd63edcecd34e767acb86877f4230dcda8fd5acc88e34723bc7bca0  frontend_dist/assets/charakter-BkYmqNt_-V58G.js
76110cc0e7fad88dd55e579a3e003e1e9fedb925de412b390274fa859a42ae91  frontend_dist/assets/charakter._charId-Uak7xfF8-V58G.js
d5c049fe5f5849314fa405d4da1478e6cfa6ee15aecda365fc0005c08f8725f8  frontend_dist/assets/charakter.index-BZymjt0P-V58G.js
d6df6fe89bd63edcecd34e767acb86877f4230dcda8fd5acc88e34723bc7bca0  frontend_dist/assets/chat-BkYmqNt_-V58G.js
0e5d21675880718708dac36f4d9ff5e3384f4f874e16ac4572537829ae2359e0  frontend_dist/assets/chat.index-DJMd_us4-V58G.js
448b89f475f56e36e3dcb563479c3cbf98a1472feed0108ab5f920d7f26a7541  frontend_dist/assets/config-BsCCj1Hx-V58G.js
28a4cb7636f74144643fd9035e33354d2fffc0679427a5613ee9a850d057dd90  frontend_dist/assets/diagnose-CgjI3Cg1-V58G.js
f4ee7f38e465be218b3a70ff175a834f0826763fb41cae52c46c8723d95855d4  frontend_dist/assets/event-engine-l0hs20f6-V58G.js
980b8398daf3ae7a9861bfa48bc6ac51f68cc66e8c33c0b911c73050c1f490fb  frontend_dist/assets/fate-BrcVsLmB-V58G.js
0131fccbc5d5e51b218c0fd5c98dbf9bef5e3049b515124522a92764befb355c  frontend_dist/assets/index-5-VzmJtc-V58G.js
e4a827304347a34f68545ed75287d566b01903b014376e9c257e116b27987ea4  frontend_dist/assets/jszip.min-DIgHJL1D-V58G.js
162320ce0725a98a0f4d2f531a10f32af693a209524f159ec0282e0c9587ac0f  frontend_dist/assets/labor-C3TD2Y6f-V58G.js
0a4672fcd4e9412a0b69932c4941c02a7c05eae26562d9e0d0f7823dcb24450d  frontend_dist/assets/lazyRouteComponent-CFjILrxq-V58G.js
db667a7c8745792bac19607114d65228a384234bc8e2932157215d24d2829ece  frontend_dist/assets/logs-BEiOiYad-V58G.js
a0185a41051f304933212496db7a80bee14e2b029a37ded849c355959c2c5f48  frontend_dist/assets/memory-efcY2umJ-V58G.js
83324bc1e73572e080614ea0e5ad0abd6d0c21f4e762f0abc9f739b414eb2ab6  frontend_dist/assets/pdf-CxLxk-yn-V58G.js
ddfd0de61b079085fbb66f313f8c931e11343bac1f9285d1ffccf35e6a2156db  frontend_dist/assets/pdf-DV2XDCc3-V58G.js
8ab0e5e30031b4a06ecfddd5ae9562f0227f830ee7ec9ed1a968b134243d2386  frontend_dist/assets/pdf.worker.min-Dswkl-cV-V58G.mjs
b0d4a42c1fc0b25b0d80c4a10c90c24b20df6f1683c5e9a8c81897a4b063c63d  frontend_dist/assets/play._sessionId-DJ7LAi8J-V58G.js
aba87f2a53e45ecdc9113fc30387d16e449d1676428cf5f82dd624c1df97d152  frontend_dist/assets/preload-helper-Czpn1I53-V58G.js
41761b98b6a3c32130c4ae430388215bb5276444e3eb5afa3dde4704dad100c2  frontend_dist/assets/review-D-Kr9F9b-V58G.js
e0a79ad36c6ca1ffbc796c80aa5661803a9d1bc684e29d1587f48b4ba9a82714  frontend_dist/assets/rolldown-runtime-C0FnF6B9-V58G.js
2eb1d17f334d79f5c2b7c68aa45a2b50b46a7b2416a9a0f5e7de6ff7f2430322  frontend_dist/assets/root-DLTE-HSj-V58G.js
1b9547e62ca50f841109afeb54c175a98d7d47a84266cbb314cebb9912cd9e42  frontend_dist/assets/routes-aKifRtrJ-V58G.js
3548ea7407395a20a50e478a25296582b8d0c6c81a456ce9fcdaf03b9a977fd9  frontend_dist/assets/shell-gwW-WKpO-V58G.js
9f79060e0388cb5ac667ce015dede4be4c17494142494b459fce2a957ffd9dc4  frontend_dist/assets/social-BYPMAzYs-V58G.js
7d195e394769ad6501c57958a394fbbb476abc8f14cc357011a15442d40c074c  frontend_dist/assets/src-SuYvKHvm-V58G.js
fb01d6dc542ac29e73e239fa4ea6cb2ce7475bbaee68560bb26ac26f4ec8e34b  frontend_dist/assets/styles-C84qSt0H-V58G.css
dd55c039e731b3a1071f6ea93f1f9548a891bae6ebe1617e8815396824b2b740  frontend_dist/assets/timeline-CmyrKt7S-V58G.js
f24a72b9131a7edc7029851273ea5995d44845678c46f071a55ab6c214751c0f  frontend_dist/assets/triggers-bPtCLXRS-V58G.js
8e90b0a22d3e272b1e088208300fea42498138ba08878e55b19404af6fe615e0  frontend_dist/assets/upload-PkoedRAR-V58G.js
5b7d0ac43fe8ff321267363e7c9074b34deeced961d80d4f101ef45829be3f6b  frontend_dist/assets/use-selectable-Dumw7S2R-V58G.js
5df4b062759ce0cc46f03f77cffc5ab544cca1827c837958c9a0e81402531419  frontend_dist/assets/useNavigate-DMQQ6XHo-V58G.js
b5ff14e9a2ebccbff44be68ab8f3eae0a74b9cf9f3f4fd97faff2f5864e807fa  frontend_dist/assets/useStore-Pi3dVb-t-V58G.js
231d904ddd8b257e919ea213076db21ba29f5f525067a723f2b02f2ed0e57b5a  frontend_dist/assets/user-BrfbdArt-V58G.js
d6df6fe89bd63edcecd34e767acb86877f4230dcda8fd5acc88e34723bc7bca0  frontend_dist/assets/welt-BkYmqNt_-V58G.js
d9c7e021997a3ab9d449108c4f88dc465bd051fd1d87babea3ef152817aacfb9  frontend_dist/assets/welt._worldId-CUNII7hy-V58G.js
50be4cbf0e2e1fa87d278143fff29470b03f301d352d91f806880a29b85714f8  frontend_dist/assets/welt.index-CsM5VIc--V58G.js
b0d4a42c1fc0b25b0d80c4a10c90c24b20df6f1683c5e9a8c81897a4b063c63d  frontend_dist/assets/world._worldId-DJ7LAi8J-V58G.js
4aa977273733b2125d6d2259682f2050a03761cf0bc175069822587cbbfa43c8  frontend_dist/index.html
0997fbc3c20f106a4a7e1b8edb664fd341df728364e3cd385d2a4ff7aaba8086  matrix_api/kernel.py
6efba2784962a7b39d5c30a8c331a10e0d15c2147a50b47fdbc702683daca68d  matrix_api/llm_contract.py
167d99f55a2d09aff24330f53aadf30a20484fcb35e8f8478f42d8586f88937d  matrix_api/repos.py
a2bf08a9bd686ab93a5eb640afa1060653a96bbacbeb7c2d7b677960133e2583  matrix_api/tests/test_v54_event_first.py
5ccd572f2bed6f5429193c16489aac38dfa2b0e658f0dfcd70bb0982147dfc41  matrix_api/tests/test_v55_continuity.py
a38bfa92760ad76f56536fa1d7d8b1213b908f857a3a790f2446975a3911b2f9  matrix_api/tests/test_v56_session_context.py
db1c3bccf1d9cddcab4fc49660e64895cd8bb59f57f1f72144a6f743dbeba9f7  matrix_api/tests/test_v57_action_ingress.py
7e1c286ac6b866d765907de9c9734dab04d2298b4bf17dff3d58081d322d86cf  matrix_api/tests/test_v58_goal_contract.py
f107423012e407b9b2287c35f17fc641ac22e4d23f6bf01965b3c3b4a87e3118  scripts/test_v53_sps.py
262f34e9f1e9770b451a1e55bdc5ddaf1fa754d78e33f094546a51e2b5ae7a98  src/lib/matrix/types.ts
d7c8681d95d03e46f329f0abf3bf5f5c1ee246e9009a2c49040d8b952fc0b2cd  src/routes/timeline.tsx
ENTFERNT/UMBENANNT  frontend_dist/assets/admin-DZOQfYB5-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/api-ClGRQEGP-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/char._charId-DJ7LAi8J-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/charakter-BkYmqNt_-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/charakter._charId-Uak7xfF8-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/charakter.index-BZymjt0P-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/chat-BkYmqNt_-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/chat.index-DJMd_us4-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/config-BsCCj1Hx-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/diagnose-CgjI3Cg1-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/event-engine-l0hs20f6-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/fate-BrcVsLmB-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/index-5-VzmJtc-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/jszip.min-DIgHJL1D-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/labor-C3TD2Y6f-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/lazyRouteComponent-CFjILrxq-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/logs-BEiOiYad-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/memory-efcY2umJ-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/pdf-CxLxk-yn-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/pdf-DV2XDCc3-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/pdf.worker.min-Dswkl-cV-V56C.mjs
ENTFERNT/UMBENANNT  frontend_dist/assets/play._sessionId-DJ7LAi8J-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/preload-helper-Czpn1I53-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/review-D-Kr9F9b-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/rolldown-runtime-C0FnF6B9-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/root-DLTE-HSj-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/routes-aKifRtrJ-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/shell-gwW-WKpO-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/social-BYPMAzYs-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/src-SuYvKHvm-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/styles-C84qSt0H-V56C.css
ENTFERNT/UMBENANNT  frontend_dist/assets/timeline-CmyrKt7S-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/triggers-bPtCLXRS-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/upload-PkoedRAR-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/use-selectable-Dumw7S2R-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/useNavigate-DMQQ6XHo-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/useStore-Pi3dVb-t-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/user-BrfbdArt-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/welt-BkYmqNt_-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/welt._worldId-CUNII7hy-V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/welt.index-CsM5VIc--V56C.js
ENTFERNT/UMBENANNT  frontend_dist/assets/world._worldId-DJ7LAi8J-V56C.js
```

Das Masterblatt hasht sich nicht selbst. Architekturdatei ist hinzugefuegt, nicht neu verfasst.

**Reproduktion im Projektroot:**

```sh
python -m pytest -q matrix_api/tests/test_v51_presence_kernel.py matrix_api/tests/test_v53_turntruth_core.py matrix_api/tests/test_v54_event_first.py matrix_api/tests/test_v55_continuity.py matrix_api/tests/test_v56_session_context.py matrix_api/tests/test_v57_action_ingress.py matrix_api/tests/test_v58_goal_contract.py
python scripts/test_v53_sps.py
```

**Paketpruefung tatsaechlich ausgefuehrt:** Paket frisch nach `v58_release_check`
entpackt: **90 passed**, danach alle **5 SQL-Pruefbloecke bestanden**. ZIP-CRC fehlerfrei,
alle 42 Asset-Hashes gegen `.build-info.json` richtig. SQLite, WAL, SHM und historisches
Live-Log im ZIP bytegleich zum Eingangs-ZIP. Anschliessend wurde ausschliesslich diese
Messzeile im Masterblatt ergaenzt; Produktcode/Testcode unveraendert erneut paketiert.
Auch dieses finale ZIP wird frisch entpackt erneut mit derselben Suite geprueft.

</details>

<details><summary>Historische V51-V57-Buildnotizen - KEINE aktuelle Abnahme / kein Architekturvertrag</summary>

Historische Phasen-Testbehauptungen werden als Verlauf erhalten, nicht als heutiger
SOLL-Massstab. Massgeblich bleibt die oben genannte Original-AMASTER-Datei.

# MATRIX10 / AMASTER - einziges SPS-Masterblatt
## V57 - erkannte Handlung bleibt Handlung - 26.10.2026

**Auftrag:** Den zuletzt reproduzierten Commit-Fehler reparieren. Keine neue
Symptomliste, kein neuer Dialog-Guard, keine Veraenderung der Figurenpersoenlichkeit.
**Beleg:** Nutzerexport `Verfuehrung und Macht 14:51`, Session
`ses_163608861edae264ece8ae2b`, Turn 3: Analyse `action/act`, gespeicherter Fact
`speech/act`, Memory `Tom sagte: Ich kuess dich zaertlich`.
**Korrektur:** Eingang wird vor der ersten Mutation in Komponenten gebunden.
Der urspruengliche Text bleibt erhalten; nicht die Modellzusammenfassung wird ausgefuehrt.

```text
EINGANG: bestehende Chat-UI /api/kernel/prepare
         rohe Eingabe + gebundene TurnTruth + vorhandener semantischer Plan
                                 |
FB08L.1 kernel.commit_turn: normalize_plan VOR make_fact
         Quelle / Akteur / Ziel / Zeit / Authority bleiben gebunden
         reine aktuelle Handlung -> action, kein zusaetzlicher Speech-Fact
         Frage / Bericht / Versprechen -> speech, keine Wortlisten-Ueberstimmung
         *Handlung* + Rede -> zwei getrennte Quellkomponenten
                                 |
FB08L.2 vorhandener Action-Writer: Faehigkeit + Anwesenheit
         -> SceneFact(action, act, Originaltext, Plan, Quellturn)
         -> vorhandene physische/Kompass-Wirkungen, soweit tatsaechlich ausgeloest
         -> kein erfundenes Einverstaendnis, kein pauschaler Phasensprung
                                 |
FB08L.3 dieselbe Quellkomponente -> Memory / WitnessKnowledge
         Akteur: getan; Ziel: erlebt; sehender Zeuge: gesehen
         abwesend: kein Wissen; nur hoerend: kein Wissen ueber stumme Handlung
         unmoegliche Aktion: unvalidated + Begruendung; kein Erfolgserlebnis
                                 |
FB08L.4 apply_goal_experience / Runtime-Aufmerksamkeit / scene_state
         -> Erfahrung an bestehenden Zielen; Phase bleibt unabhaengig davon offen
         -> semantischer Action-Plan erreicht lastPhysicalBeat ohne Stichwortzwang
                                 |
FB08L.5 bestehendes save_session -> SQLite COMMIT -> neue Verbindung -> Recall
         -> canonical_formulation_context -> tatsaechliche Request-Serialisierung
AUSGANG: Handlung ist in SQL, Gedaechtnis, Szene und Modellrequest eine Handlung
         Antwort folgt bestehender response-Commit-Phase; kein doppelter Input
UI:      bestehende Anzeige von turn.action; keine neue versteckte Backendfunktion
```

### Ein Fehlerweg, zusammenhaengende Aenderungen

| ID | Aenderung und Grund | Ausgang / betroffene Abhaengigkeit |
|---|---|---|
| L01 | Semantik vor Schreibentscheidung statt erst an falschen Fact anhaengen. | `commit_turn`, `make_fact`, Speech-/Action-Writer. |
| L02 | Memory und Wissenswirkung lesen die entstandenen Komponenten statt ungefiltert den gesamten Eingabetext als Rede. | `memories`, `witness_knowledge`, `apply_knowledge_effect`; Quell-Fact-ID bleibt erhalten. |
| L03 | Stumme Aktion wird gesehen/erlebt, nicht automatisch gehoert; keine Wirkung auf abwesende Ziele oder Erfolg bei handlungsunfaehigem Akteur. | Bestehende Presence-/Capability-Pruefung, `witness_access`, Recall. |
| L04 | Szene liest denselben semantischen Plan fuer physische Beats. | `sceneState.lastPhysicalBeat`; keine Liste neuer Kuss-/Tammy-Stichwoerter. |
| L05 | Zeit-Gegenprobe: `morgen` bleibt Zukunft auch ohne Realzeit-Anker. | `bind_time`; Zukunftsbericht darf keine jetzige Aktion ausloesen. |
| L06 | Originaleingabe separat am Turn; action wird in bestehender UI angezeigt. | `turn.inputText`, `turn.action`, vorhandene `chat.$sessionId.tsx` Anzeige. |

### Messstand

**V56-Gegenprobe:** Derselbe neue Fehlertest und SQL/Request-Test schlagen am
unveraenderten V56 fehl: `2 failed, 15 deselected`. Grund jeweils `speech != action`.
**V57:** `64 passed` (46 vorhandene + 18 neue Prueffalle), dazu 5 bestandene
SQLite-Pruefbloecke aus `scripts/test_v53_sps.py`. Syntaxpruefung aller Python-Dateien.
Der SQL-Test verwendet echte Produktions-Writer, neue SQLite-Verbindung und die echte
Request-Serialisierung; lediglich die Providerantwort ist kontrollierte Testausgabe.
Er prueft auch Antwort-Commit, keinen doppelten Input und eine separate frische Sitzung.
Gegenproben: andere Namen/IDs und Handlungen, Frage, Zitat, Versprechen, Vergangenheit,
Zukunft, gemischte Eingabe, abwesendes Ziel, bewusstloser Akteur, Sehen ohne Hoeren,
Hoeren ohne Sehen. Keine produktive namens-/satzspezifische Abfrage hinzugefuegt.

**Live-Grenze:** Externer Provider und Android wurden nicht aufgerufen. Flask fehlt in
dieser Umgebung; die SQL-Tests verwenden den bereits vorhandenen Import-Shim, nicht
einen ersetzten Repository-Writer. Keine Aussage ueber garantierte Wiederholungsfreiheit
oder automatische Erfuellung beliebiger `goal.exit`-Texte. Diese Ausgabe repariert den
hier bewiesenen Action/Speech-Verlust, nicht durch Behauptung die gesamte AMASTER-Abnahme.
Die unveraenderten nachgelagerten physischen Wirkungsregeln werden nicht als vollstaendige
Handlungserfolgs- oder Einverstaendnisentscheidung zertifiziert.

**Daten:** Original-SQLite und historisches Log bytegleich erhalten. Keine alte Session
umgeschrieben. Frontend-Source und ausgelieferte Assets unveraendert (V56C), vorhandene
Action-Anzeige am Source geprueft. Neue Build-ID verhindert unbemerktes Weiterlaufen
gegen den alten Backendprozess.

<details><summary>Codepositionen, SHA-256 und reproduzierbare Pruefung (V57)</summary>

| Datei | Funktion | Zeilen V57 |
|---|---|---|
| `matrix_api/kernel.py` | `bind_time` | 864-1009 |
| `matrix_api/kernel.py` | `witness_access` | 1364-1408 |
| `matrix_api/kernel.py` | `commit_turn` | 2306-3107 |
| `matrix_api/scene_state.py` | `update_from_commit` | 55-147 |

Eingangs-ZIP SHA-256: `182351c9ade18471ed7644c54ea472e23bc1cdb0dee5e0105506076a83a9f867`
Original-SQLite SHA-256: `c1e5a85ef0469aa0146ecf50db6aa728d7bb2c2cf838383e87f408b3ab104177`

```text
matrix_api/kernel.py
  V56 8589bf243fefc4e111afef09052e13ed7068f0c3c529749fab990eb0dc584a0c
  V57 b8dd9d7ffe892ef758d8b3706ea9fb9870ae8a728eb22871d7423afa925699c7
matrix_api/scene_state.py
  V56 654f3ec2d025e127d8f487d155b1ccc10233bdc15c9f5011a364f377c0a12ad9
  V57 6cff6e5bbc1ff6a9b684020f407ae1147cabfc6c9d47c6e7e686a84616b6a79e
matrix_api/tests/test_v57_action_ingress.py
  V56 NEU
  V57 1bf7d531463c6cb5e19ea59b1cb17c7faca5288e5e655a8248868bf194d46872
matrix_api/tests/fixture_v57_action_ingress.json
  V56 NEU
  V57 7103cbe624982cde908fb232fb2cdd87162d1c40a0f35e38bfc4597547d7cb75
VERSION.txt
  V56 7af8ac07994f24467ea432c436283510dd2692a6169c1992afc9f8d4be0ac158
  V57 a032da7203c6e3c757dc44cbd41ad5c678214b76f350098bb6ee07eb23bba32b
README.md
  V56 e5ce3bbbeebe0729aa802a405ae050c5cf985e8bafcfc28c856e632fc82d3cb0
  V57 948352fd8becf0c52e0f95cdbdc1343068e7fd0cd33f34bb372c05145e45524e
```

```sh
python -m pytest -q matrix_api/tests/test_v51_presence_kernel.py matrix_api/tests/test_v53_turntruth_core.py matrix_api/tests/test_v54_event_first.py matrix_api/tests/test_v55_continuity.py matrix_api/tests/test_v56_session_context.py matrix_api/tests/test_v57_action_ingress.py
python scripts/test_v53_sps.py
```

</details>

<details><summary>Vollstaendige Produktcode-Aenderung V56 zu V57</summary>

```diff
--- V56/matrix_api/kernel.py
+++ V57/matrix_api/kernel.py
@@ -920,9 +920,12 @@
             else:
                 window = "heute"
             tense = "present"
-        elif "morgen" in low and parsed:
-            resolved = (parsed + timedelta(days=1)).date().isoformat()
-            window = f"morgen ({resolved})"
+        elif "morgen" in low:
+            if parsed:
+                resolved = (parsed + timedelta(days=1)).date().isoformat()
+                window = f"morgen ({resolved})"
+            else:
+                window = "morgen"
             tense = "future"
         elif "nächsten monat" in low or "naechsten monat" in low:
             if parsed:
@@ -1379,6 +1382,18 @@
         if character_id in informed:
             return "informed"
         return "present" if character_id in present else None
+    if fact.get("kind") == "action":
+        # A silent physical component is not room speech. Targets that are
+        # absent, and bystanders who only hear, cannot see/experience it.
+        if character_id not in present:
+            return "informed" if character_id in informed else None
+        if character_id == fact.get("actorId"):
+            return "performed" if fact.get("validated") is not False else "attempted"
+        if fact.get("validated") is not False and character_id == fact.get("targetId"):
+            return "affected"
+        if character_id in sees:
+            return "seen"
+        return "present"
     affected = set(fact.get("affected_ids") or []) | set(truth.get("affected_ids") or [])
     if fact.get("targetId"):
         affected.add(fact["targetId"])
@@ -2358,6 +2373,52 @@
     _pre_tense = _pre_time.get("tense")
     _pre_ambiguous = _pre_time.get("ambiguous")
     _pre_past = _pre_tense == "past" or bool(_pre_ambiguous)
+    # V57: resolve the input BEFORE selecting any Fact/Memory/effect writer.
+    # The envelope input_kind describes the UI route, not the semantic event.
+    # A validated semantic plan must not be attached to an already-wrong Fact.
+    input_plan = None
+    input_speech, input_action = None, None
+    if not response_only and not skip_figure and truth.get("text") and truth.get("input_kind") in ("speech", "user"):
+        raw_input = str(truth["text"])
+        if isinstance(user_plan, dict):
+            input_plan = _conj.normalize_plan(
+                user_plan, actor_id=input_actor,
+                recipient_id=str(truth.get("target_id") or "") or None,
+                text=raw_input, now=_session_now(s),
+                present_ids=list((s.get("scene") or {}).get("presentIds") or []),
+                figures=present,
+            )
+            if input_plan is None:
+                input_plan = _conj.literal_plan(raw_input, actor_id=input_actor,
+                    recipient_id=str(truth.get("target_id") or "") or None)
+        else:
+            # Existing explicit offline/direct-kernel caller compatibility.
+            input_plan = _conj.local_plan(raw_input, actor_id=input_actor,
+                recipient_id=str(truth.get("target_id") or "") or None, now=_session_now(s))
+        marked_speech, marked_action = _split_star_marker(raw_input)
+        current_action = (input_plan.get("event_kind") == "action"
+                          and input_plan.get("speech_act") == "act"
+                          and input_plan.get("validation_status") == "validated"
+                          and _pre_tense not in ("past", "future") and not _pre_ambiguous)
+        if marked_action is not None:
+            input_speech, input_action = marked_speech, marked_action
+        elif current_action:
+            input_speech, input_action = None, raw_input
+        elif isinstance(user_plan, dict):
+            # Reports, promises, questions and unresolved input do not execute
+            # physical words appearing in a quotation or a past/future report.
+            input_speech, input_action = raw_input, None
+            if input_plan.get("event_kind") == "action":
+                input_plan = {**input_plan, "reported_event_kind": "action",
+                              "event_kind": "report", "speech_act": "report",
+                              "durability": "utterance"}
+        else:
+            input_speech, input_action = split_star_action(raw_input)
+        resolved = "speech_action" if input_speech and input_action else ("action" if input_action else "speech")
+        for stored in s.get("turnTruths") or []:
+            if stored.get("id") == source:
+                stored["input_event_kind"] = resolved
+                break
     if truth.get("text") and truth.get("input_kind") in ("speech", "user", "comment", "observer"):
         auth = truth["authority"]
         if auth == "avatar" and truth.get("role") == "teilnehmer":
@@ -2375,7 +2436,14 @@
                 "firedSpaces": [],
             }
         )
-        speech_text, action_text = split_star_action(truth["text"])
+        speech_text, action_text = ((str(truth["text"]), None) if skip_figure
+                                    else (input_speech, input_action))
+        # Original input is retained separately; the chat line no longer labels
+        # a silent action as spoken words. Existing UI already renders action.
+        if not skip_figure:
+            s["turns"][-1]["inputText"] = truth["text"]
+            s["turns"][-1]["speech"] = speech_text or ""
+            s["turns"][-1]["action"] = action_text
         if skip_figure:
             uf = make_fact(
                 turn=turn,
@@ -2411,9 +2479,15 @@
                     time_tense=_pre_tense,
                     time_ambiguous=bool(_pre_ambiguous),
                 )
+                if input_plan is not None:
+                    # A mixed *action* + spoken phrase needs separate semantics.
+                    uf["plan"] = (input_plan if input_plan.get("event_kind") != "action" else
+                                  _conj.literal_plan(speech_text, actor_id=input_actor,
+                                      recipient_id=str(truth.get("target_id") or "") or None))
+                    uf["speech_act"] = uf["plan"].get("speech_act")
                 s.setdefault("facts", []).append(uf)
                 new_facts.append(uf)
-            if speech_text and truth.get("target_id") in (s.get("scene") or {}).get("presentIds", []) and input_actor and str(truth.get("target_id")) != str(input_actor):
+            if (speech_text or action_text) and truth.get("target_id") in (s.get("scene") or {}).get("presentIds", []) and input_actor and str(truth.get("target_id")) != str(input_actor):
                 # V30 (AMASTERv2 §44 Erstkontakt): Wer miteinander spricht, steht in einer gerichteten
                 # Sessionbeziehung (Standardwerte, kein Drift) — sonst fehlt dem Folgeturn relationsHere.
                 _ensure_directed_rel(s, str(input_actor), str(truth.get("target_id")))
@@ -2421,6 +2495,10 @@
             if action_text:
                 rt_user = s.setdefault("runtimes", {}).get(input_actor) or {}
                 blocked = capability_blocks_action(rt_user if isinstance(rt_user, dict) else {}, action_text)
+                action_present = set((s.get("scene") or {}).get("presentIds") or [])
+                absent_target = bool(truth.get("target_id") and truth.get("target_id") not in action_present)
+                absent_actor = input_actor not in action_present
+                invalid_reason = "capability" if blocked else ("target_absent" if absent_target else ("actor_absent" if absent_actor else None))
                 af = make_fact(
                     turn=turn,
                     actorId=input_actor,
@@ -2433,14 +2511,19 @@
                     sourceTurnId=source,
                     truth=truth,
                     scene=s.get("scene") or {},
-                    validated=not blocked,
-                    rejection_reason="capability" if blocked else None,
+                    validated=invalid_reason is None,
+                    rejection_reason=invalid_reason,
                     time_tense=_pre_tense,
                     time_ambiguous=bool(_pre_ambiguous),
+                    source_type="action",
+                    witnessedBy=list(dict.fromkeys([input_actor] + [cid for cid in truth.get("sees_ids") or [] if cid in action_present])),
                 )
+                if input_plan is not None and input_plan.get("event_kind") == "action":
+                    af["plan"] = input_plan
+                    af["speech_act"] = input_plan.get("speech_act")
                 s.setdefault("facts", []).append(af)
                 new_facts.append(af)
-                if not blocked and not _pre_past:
+                if invalid_reason is None and not _pre_past and _pre_tense != "future":
                     # R3.4 / B.7-Folge: past-Action ist Bericht, keine
                     # Runtime-Mutation. "Ich habe gestern geschlagen"
                     # wird als Fact geschrieben, mutiert aber nicht.
@@ -2847,26 +2930,45 @@
                 truthStatus="canon",
             )
             s.setdefault("memories", []).append(mem)
+    # V57: input memories follow the committed component, never the raw UI
+    # envelope. This keeps said/heard distinct from done/experienced/seen.
     present_set = set(truth.get("present_ids") or (s.get("scene") or {}).get("presentIds") or [])
-    if truth.get("text") and truth.get("input_kind") in ("speech", "user"):
-        hearers = [
-            i
-            for i in _effective_hears(s, truth)
-            if i and i != input_actor and i != avatar_id and i in present_set
-        ]
-        for hid in hearers:
-            s.setdefault("memories", []).append(
-                make_memory(
-                    characterId=hid,
-                    kind="gehoert",
-                    text=f"{truth.get('user_name') or 'Der Gast'} sagte: {truth['text'][:180]}",
-                    salience=0.65,
-                    turn=turn,
-                    witnesses=[hid],
-                    layer="session",
-                    truthStatus="canon",
-                )
-            )
+    for source_fact in new_facts:
+        if source_fact.get("actorId") != input_actor or source_fact.get("kind") not in ("speech", "action"):
+            continue
+        fact_text = str(source_fact.get("text") or "")
+        is_action = source_fact.get("kind") == "action"
+        valid_action = is_action and source_fact.get("validated") is not False and not _pre_past and _pre_tense != "future"
+        if is_action:
+            if input_actor in present_set:
+                s.setdefault("memories", []).append(make_memory(
+                    characterId=input_actor, kind="getan" if valid_action else "versucht",
+                    text=fact_text, salience=0.65, turn=turn, witnesses=[input_actor],
+                    layer="session", truthStatus="canon" if valid_action else "attempted",
+                    source="kernel", factId=source_fact["id"], sourceTurnId=source,
+                    sessionId=s.get("id"), worldId=s.get("worldId")))
+            if not valid_action:
+                continue
+            for cid in present_set - {input_actor}:
+                access = witness_access(truth, source_fact, cid)
+                if access not in ("affected", "seen"):
+                    continue
+                s.setdefault("memories", []).append(make_memory(
+                    characterId=cid, kind="erlebt" if access == "affected" else "gesehen",
+                    text=f"{truth.get('user_name') or s.get('alias') or input_actor}: {fact_text}",
+                    salience=0.65, turn=turn, witnesses=[cid], layer="session",
+                    truthStatus="canon", source="kernel", factId=source_fact["id"],
+                    sourceTurnId=source, sessionId=s.get("id"), worldId=s.get("worldId")))
+        else:
+            for cid in _effective_hears(s, truth):
+                if not cid or cid in (input_actor, avatar_id) or cid not in present_set:
+                    continue
+                s.setdefault("memories", []).append(make_memory(
+                    characterId=cid, kind="gehoert",
+                    text=f"{truth.get('user_name') or s.get('alias') or 'Der Gast'} sagte: {fact_text[:180]}",
+                    salience=0.65, turn=turn, witnesses=[cid], layer="session", truthStatus="canon",
+                    source="kernel", factId=source_fact["id"], sourceTurnId=source,
+                    sessionId=s.get("id"), worldId=s.get("worldId")))
     _record_fact_witnesses(s, truth, new_facts, turn)
     # V54: every perceived source event can add evidence to the character's
     # existing open goal, even when the lexical compass has no trigger.
@@ -2879,24 +2981,29 @@
                 apply_goal_experience(s, lid, source_fact, turn=turn)
     # V36 (AMASTERv2 §16/§40): Auch die Rede des Eingabe-Akteurs (Avatar/Bedienperson) wirkt auf
     # die anwesenden Weltfiguren, die sie hören — nicht nur die Rede der antwortenden Figur.
-    user_text = str(truth.get("text") or "").strip()
-    if user_text and truth.get("input_kind") in ("speech", "user") and present:
-        user_fact = next((f for f in new_facts if isinstance(f, dict) and f.get("kind") == "speech" and str(f.get("actorId")) == str(input_actor)), None)
-        hears = list((s.get("scene") or {}).get("hearsIds") or (s.get("scene") or {}).get("presentIds") or [])
-        for listener in present:
+    user_text = str(input_speech or "").strip()
+    input_events = [f for f in new_facts if f.get("actorId") == input_actor and f.get("kind") in ("speech", "action")]
+    for user_fact in input_events:
+        if user_fact.get("validated") is False:
+            continue
+        for listener in present or []:
             lid = str((listener or {}).get("id") or "")
-            if not lid or lid == str(input_actor) or lid == str(s.get("avatarId") or "") or lid not in hears:
+            access = witness_access(truth, user_fact, lid)
+            if not lid or lid in (input_actor, str(s.get("avatarId") or "")) or access not in ("heard", "seen", "affected"):
                 continue
             if not skip_figure and lid == str(speaker.get("id") or "") and fired:
-                continue  # die Antwortende reagiert über ihre Synapsen (apply_synapses), nicht doppelt
-            apply_knowledge_effect(s, listener, text=user_text, fact_id=(user_fact or {}).get("id") or source, turn=turn, characters=present, source="heard", authority="character", scale=0.6, counterpart_id=str(input_actor))
+                continue
+            apply_knowledge_effect(s, listener, text=str(user_fact.get("text") or ""),
+                fact_id=user_fact["id"], turn=turn, characters=present, source=access,
+                authority="character", scale=0.6, counterpart_id=input_actor)
     # V39 Konjunktives Gedächtnis (§36/§37/§40): jede Nutzer-/Avatar-/Puppet-Rede bekommt einen
     # validierten Turn-Plan (LLM oder lokal) am Fact; dauerhafte Inhalte werden Frames.
     if user_text and truth.get("input_kind") in ("speech", "user"):
         uf = next((f for f in new_facts if isinstance(f, dict) and f.get("kind") == "speech" and str(f.get("actorId")) == str(input_actor)), None)
         if uf is not None:
-            plan = _conj.normalize_plan(user_plan, actor_id=str(input_actor), recipient_id=str(truth.get("target_id") or "") or None, text=user_text, now=_session_now(s), present_ids=[str(p.get("id")) for p in (present or []) if isinstance(p, dict)], figures=present) if isinstance(user_plan, dict) else None
-            plan = _conj.prefer_local_if_richer(plan, _conj.local_plan(user_text, actor_id=str(input_actor), recipient_id=str(truth.get("target_id") or "") or None, now=_session_now(s)))
+            # Same pre-bound plan that selected the Fact writer, not a second
+            # classifier after effects and memories have already been written.
+            plan = uf.get("plan") or input_plan
             uf["plan"] = plan
             uf["speech_act"] = plan.get("speech_act")
             hears_now = list((s.get("scene") or {}).get("hearsIds") or (s.get("scene") or {}).get("presentIds") or [])
@@ -2935,8 +3042,8 @@
             _ufact = next((f for f in new_facts if isinstance(f, dict) and f.get("kind") == "speech" and str(f.get("actorId")) == str(input_actor)), None)
             _uact = next((f for f in new_facts if isinstance(f, dict) and f.get("kind") == "action" and str(f.get("actorId")) == str(input_actor)), None)
             _scene.update_from_commit(
-                s, speaker_id=str(input_actor), target_id=(str(truth.get("target_id")) if truth.get("target_id") in _present_ids_now else None), speech=_utext, action=(_uact or {}).get("text"),
-                fired=[], runtime=(s.get("runtimes") or {}).get(str(input_actor)), plan=(_ufact or {}).get("plan"),
+                s, speaker_id=str(input_actor), target_id=(str(truth.get("target_id")) if truth.get("target_id") in _present_ids_now else None), speech=str(input_speech or ""), action=(_uact or {}).get("text") if (_uact or {}).get("validated") is not False else None,
+                fired=[], runtime=(s.get("runtimes") or {}).get(str(input_actor)), plan=(_ufact or _uact or {}).get("plan"),
                 physical_changed=bool(_uact and any(f.get("event_kind") in ("body_state", "physical") and str(f.get("actorId")) == str(input_actor) for f in new_facts)),
                 turn=turn, present_ids=_present_ids_now,
             )

--- V56/matrix_api/scene_state.py
+++ V57/matrix_api/scene_state.py
@@ -73,7 +73,7 @@
     if tid and tid not in st["targetIds"]:
         st["targetIds"] = (st["targetIds"] + [tid])[-4:]
     # physischer Beat
-    if physical_changed or (action and any(w in str(action).lower() for w in ("schlägt", "schlaegt", "packt", "stößt", "stoesst", "umarmt", "küsst", "kuesst", "greift", "fesselt", "tritt", "rennt", "flieht"))):
+    if physical_changed or (action and (plan or {}).get("event_kind") == "action") or (action and any(w in str(action).lower() for w in ("schlägt", "schlaegt", "packt", "stößt", "stoesst", "umarmt", "küsst", "kuesst", "greift", "fesselt", "tritt", "rennt", "flieht"))):
         st["lastPhysicalBeat"] = {"by": sid, "target": tid, "text": str(action or speech)[:160], "turn": turn}
         st["escalation"] = _clamp(float(st.get("escalation") or 0) + 0.25)
         changed["physical"] = True

```

</details>

<details><summary>Bisheriger Systemplan und Chronologie bis V56 (unveraendert)</summary>

# MATRIX10 / AMASTER — einziges SPS-Masterblatt
## V56 · Sessiongrenze und tatsächlicher Formulierungsweg · 26.10.2026

**Ausgang:** das zuletzt hochgeladene V55-Paket, einschließlich seiner aktuellen Datenbank und Logs.
**Auftrag:** Kein weiterer Diagnose-Release. Den nachgewiesenen Rückfluss alter Figurenrede in neue Sitzungen
und den falschen tatsächlichen Formulierungsweg im vorhandenen System korrigieren.
**Ergebnis:** Code, Bedienung und ausgelieferte Assets geändert. 46 gezielte Tests bestehen.
**Nicht behauptet:** komplette AMASTER-Abnahme, fehlerfreie freie Semantik oder lebensechte Langzeitentwicklung.

```text
EINGANG A: Neue Sitzung (UI) + Welt-ID + Figuren + Besitzer
  FB08K.1  repos.create_session / get_character / list_characters / get_mcc
      -> learning.canonical_stem: Herkunfts-Ledger entscheidet Stammwirkung
      -> unbeaufsichtigt gelernte Sessionrede bleibt im Ledger, nicht im Startstamm
      -> kernel.build_new_session / initial_character_intent / reset_runtime_only
      -> SQL sessions + goals + relationships; Runtime aus freigegebenem Stamm
  AUSGANG: frische Session ohne fremde Sessionrede als neue Grundidentitaet

EINGANG B: Besitzer klickt Charakter > Gelernt > Dauerhaft uebernehmen
  FB08K.2  PATCH character -> repos.patch_character -> learning.approve_learned
      -> SQL characters, bestehendes learnedItems-Ledger + approvedBy/approvedAt
      -> derselbe Editor-/Bootstrap-/Session-Reader
  AUSGANG: genau dieser Wert ist jetzt ausdruecklich fuer neue Sitzungen freigegeben

EINGANG C: Nutzerrede + gebundene TurnTruth (Sprecher/Ziel/Anwesenheit/Authority)
  FB08K.3  app.kernel_prepare -> _extract_user_plan -> llm_contract.extract_turn_plan
      -> eine Analyse VOR SQLite-Schreibsperre, Request/Response werden protokolliert
      -> conjunctive.normalize_plan -> bestehender kernel.commit_turn(phase=input)
      -> SQL SceneFacts / Witness / Memory / Runtime / Goals / Beziehungen
      -> ungeklaerte Analyse: Originalrede + source_only; KEIN geratenes Commitment
      -> bindende Semantik wird nicht von zweitem Wortmuster-Durchlauf ersetzt
  FB08K.4  kernel.prepare_turn / recall / bind_formulation_spiegel
      -> personenbezogene Fakten, Bedingungen, Erfahrungen und aktueller Zustand
      -> KEINE zweite Runtime-Vorschau im Leser; Begruessung ist keine Forderung
  FB08K.5  llm_contract.canonical_formulation_context
      -> Session und offene TurnTruth aus SQL erneut lesen, Besitzer/Sprecher pruefen
      -> Browser-Spiegel ist Anzeige, keine Quelle fuer Wahrheit oder Persoenlichkeit
      -> _try_llm: kanonischen Zustand mitsenden; kein stilles 14k-Abschneiden
      -> genau EIN Formulierungsaufruf; unveraenderte Rede/Handlung zurueckgeben
      -> bestehender kernel.commit_turn(phase=response) + SQL + naechster Recall
  AUSGANG: Aktualisierter Zustand gelangt tatsaechlich in die Formulierung

QUERSCHNITT FB08K.6: provider_audit -> vorhandene SQL logs -> /logs > Reader
      -> Request + Rohantwort + usage + Session/Turn/Sprecher + Request-SHA256
      -> keine Authorization-Header/API-Schluessel
      -> Liste zeigt Metadaten; Reader zeigt vollstaendige Details
FEHLERWEG FB08K.7: Providerfehler -> UI-Fehler, kein lokaler Ersatzdialog
      -> Eingabe bleibt pending, derselbe Text kann denselben Turn wiederaufnehmen
```

### Was diese Ausgabe gezielt ändert

| ID | Ursache / Besitzer / Korrektur | Frontend und Abhängigkeiten |
|---|---|---|
| K01 | Session-Lernwerte besaßen Stammwirkung. Kanonische Leser trennen nach vorhandener Provenienz, ohne Originaldaten zu löschen. | Figureneditor, MCC-Bootstrap und Sessionstart nutzen denselben Leser. Kein Tammy-/Wortfilter. |
| K02 | Runtime startete mit alter gelernter Absicht. Anfangsabsicht kommt aus dem freigegebenen strukturierten Startziel, sonst aus regulärem Stammziel. | Bestehende Ziele und beliebige Phasendauer bleiben; kein automatischer Phasensprung. |
| K03 | V54 hatte den semantischen Eingabepfad durch `local_plan()` ersetzt. Bestehende Analyse wieder angeschlossen, außerhalb der Schreibtransaktion. | Die Eingabeanalyse ist ein eigener, sichtbarer Provideraufruf; bei Ausfall kein erratenes Ja/Versprechen. |
| K04 | Nachträgliche Wortmuster überschrieben Plan und Lifecycle. Lifecycle liest nun denselben gespeicherten Speech-Plan. | Ziel-/Authority-/Source-Prüfung bleibt im vorhandenen Kernel. Kein neuer Parallelstore. |
| K05 | `hauptsache` enthielt jeden Reiz als Forderung. Sie spiegelt jetzt tatsächliche offene Propositionen. | Originale Nutzerrede wird separat unverändert mitgesendet. |
| K06 | `compact` war ungesendet; Fakten/CurrentState blieben vor dem Provider liegen. SQL-gebundener Spiegel wird vor der Formulierung neu gelesen und serialisiert. | Frontend sendet Session-ID, TurnTruth-ID, Sprecher-ID, Revision. Fremde/stale Zustände werden nicht verwendet. |
| K07 | Leser berechnete Runtime-Vorschau ein zweites Mal. Entfernt; Quelle/Authority/Plan werden im Faktenlesemodell erhalten. | BrainContext ist ein Leser, keine Wirkungsschicht. |
| K08 | Formulierung hatte versteckten Zweitaufruf und Satzlöschung. Dieser Pfad und seine namens-/wortspezifischen Heuristiken sind entfernt. | Modellrede wird nicht durch Wiederholungsfilter ersetzt. Auch eine schlechte Modellantwort bleibt diagnostizierbar. |
| K09 | Ausfälle wurden als lokale Ersatzrede committed. Normaler Providerpfad meldet jetzt Fehler und lässt den Eingabeturn offen. | UI sendet keinen Ersatztext. Bewusst gewählter lokaler Synapse-Modus bleibt separat bedienbar. |
| K10 | Vollständiger Prompt fehlte im Log. Bestehende SQL-Logs erhalten echte Request-/Response-Körper und Provider-usage. | Reader nicht mehr auf 400 Zeichen begrenzt. Kein JSON-Nebenlog. |
| K11 | Historisches Lernen war nur löschbar. Ausdrückliche Besitzerfreigabe im bestehenden Editor/Writer ergänzt. | `Dauerhaft uebernehmen`, Owner-Prüfung und dauerhafter SQL-Readback. |
| K12 | Ungebundene Konfigurations-Probe war kein Figurenturn. Konfigurationsbutton nutzt bestehende Provider-Verbindungsprüfung. | Kein fiktiver Chatkontext ohne Session. Assets umbenannt gegen alten Browsercache. |

### Nachweis statt Speicherzähler

**Kontrollierte V55/V56-Gegenprobe mit identischer vorgegebener Providerantwort:**

| Prüfung | V55 | V56 |
|---|---|---|
| Formulierungsaufrufe bei derselben wiederholten Antwort | 2 | 1 |
| Ursprüngliche Rede unverändert zurückgegeben | nein | ja |
| Prüffakt im tatsächlichen Request | nein | ja |
| Prüfwert aus CurrentState im tatsächlichen Request | nein | ja |

Das sind Transport-/Codegegenproben, **keine** nachträgliche Behauptung über historische Kosten.
Der normale Netzturn hat nun **eine Eingabeanalyse und eine Formulierung**. Beides wird separat
aufgezeichnet. Kein zweiter Formulierungsversuch zum Umschreiben einer missliebigen Antwort.

**Prüfstand:**
- 26 vorhandene gezielte V51–V55-Regressionstests bestehen unverändert.
- 20 neue V56-Tests bestehen: frischer SQL-Sessionstart, Stamm/Session-Grenze, Freigabe + Neuverbindung,
  Bootstrap/Editor-Parität, fremde Besitzer, unbekannte/veraltete TurnTruth, AutoChat-Leser,
  volle Faktenübertragung über 14.000 Zeichen, unveränderte Antwort, fehlender Ersatzdialog,
  semantischer Plan vor Wortmuster, volle Logdaten ohne API-Key und echte lokale HTTP-Übertragung.
- Ein vollständiger isolierter Ablauf nutzt `formulate_from_config` -> tatsächliche Request-Erstellung ->
  kontrollierte Providerantwort -> `commit_turn(response)` -> `save_session` -> SQL-Readback.
- Zusätzlich bestehen die 5 vorhandenen SQL-Prüfblöcke in `scripts/test_v53_sps.py`.
- Syntax: 35 Python-Dateien, 84 TypeScript-Dateien, 41 ausgelieferte JS/MJS-Dateien;
  172 neue statische Asset-Verweise auf 42 ausgelieferte Assets ohne fehlende V56C-Ziele.
- TypeScript-Syntaxprüfung ist **kein** vollständiger Typecheck. Die vorhandenen Bundles wurden
  gezielt zur Source-Parität bearbeitet, nicht mit Vite neu gebaut. React/Vite-Installationspakete
  und Flask fehlen hier; Paketzugriff über das Netz war nicht verfügbar.
- Der lokale HTTP-Test verwendet einen kontrollierten Provider-Testserver. **Kein echter externer
  Modellaufruf, keine kostenpflichtige Modellprüfung, keine Android-/Flask-Liveabnahme.**

**Offene Grenze:** Die automatische semantische Erfüllungsentscheidung über beliebige freie
`goal.exit`-Texte ist weiterhin nicht implementiert. V56 stellt diese Kriterien und die Erfahrungen
vollständig zum Lesen bereit; es behauptet nicht deren automatische Erfüllung. Phasenziele werden
nicht nach Turnzahl oder Schüsselwort abgeschlossen. Andere bestehende physische/lexikalische
Teilsysteme wurden nicht pauschal umgebaut. Die Fehlerfreiheit freier Modellinterpretation und
langfristig glaubwürdiger Dialoge ist mit diesen isolierten Tests nicht bewiesen.

### Start und Daten

V55 beenden, V56 in neuen Ordner entpacken, `python START.py`, neue Sitzung erstellen.
Die jüngste hochgeladene SQLite und das historische Live-Log bleiben bytegleich erhalten.
Es wird keine alte Session stillschweigend repariert oder gelöscht. Alte Lernwerte bleiben
im Ledger sichtbar; neue Sitzungen benötigen keine manuelle Stamm-Bereinigung.
Eine bewusste Stammfreigabe erfolgt ausschließlich im vorhandenen Figureneditor.


<details><summary>Funktionsstellen, Dateiregister und SHA-256 (V56)</summary>

**`matrix_api/learning.py`**

`canonical_stem` L195–229; `approve_learned` L232–261

**`matrix_api/repos.py`**

`get_mcc` L1322–1382; `get_character` L2400–2410; `list_characters` L2413–2419; `create_session` L2460–2570; `patch_character` L2187–2232; `create_log` L4462–4482; `list_logs` L4489–4497; `get_log` L4485–4486

**`matrix_api/kernel.py`**

`initial_character_intent` L4967–4974; `build_new_session` L4810–4964; `reset_runtime_only` L4977–5011; `commit_turn` L2291–3000; `recall` L5318–5411; `bind_formulation_spiegel` L5705–6063

**`matrix_api/app.py`**

`kernel_prepare` L1351–1554; `_extract_user_plan` L2166–2183

**`matrix_api/conjunctive.py`**

`normalize_plan` L185–249; `prefer_local_if_richer` L252–258; `literal_plan` L135–141

**`matrix_api/llm_contract.py`**

`extract_turn_plan` L307–317; `canonical_formulation_context` L917–959; `provider_audit` L962–986; `formulate_from_config` L989–1066; `_try_llm` L563–638; `_parse_llm_json` L264–291


```text
BASIS_ZIP_SHA256=0501263084eb53d1c4ca1d94691cf5c6974383aec34db9d0d501ecc5feb75f54
ORIGINAL_DB_SHA256=c1e5a85ef0469aa0146ecf50db6aa728d7bb2c2cf838383e87f408b3ab104177
ORIGINAL_LIVELOG_SHA256=f0f0b61b8e4d74bea966711722a8d1442a37f8fddf68d608dcedb188efcab154
e5ce3bbbeebe0729aa802a405ae050c5cf985e8bafcfc28c856e632fc82d3cb0  README.md
7af8ac07994f24467ea432c436283510dd2692a6169c1992afc9f8d4be0ac158  VERSION.txt
d48722352c2b00a9bf4358433749ccd6248c1a6facd50f20d9ef743120520556  frontend_dist/.build-info.json
f2fb3a8fa2b0712f87529f9b1e2ab2e2e3e42e6c74a38bcb34a715813672e62d  frontend_dist/assets/admin-DZOQfYB5-V56C.js
ed7ea5c1b8abc4287f0bd0e7bf1c2c438559b8c47764099454bae15fde268e37  frontend_dist/assets/api-ClGRQEGP-V56C.js
b0d4a42c1fc0b25b0d80c4a10c90c24b20df6f1683c5e9a8c81897a4b063c63d  frontend_dist/assets/char._charId-DJ7LAi8J-V56C.js
a0fe2c84090e24b943e9743ef8b90fb3581514dea4d9adc65e782823d0fba3c7  frontend_dist/assets/charakter-BkYmqNt_-V56C.js
4e626824d344b12ea130891c6705a9fe085a1fdcb938927db49f0d4891c84b73  frontend_dist/assets/charakter._charId-Uak7xfF8-V56C.js
37518812d0ec6352fe79a7b756440174eb6ec37977381e229c1e370783fd0354  frontend_dist/assets/charakter.index-BZymjt0P-V56C.js
a0fe2c84090e24b943e9743ef8b90fb3581514dea4d9adc65e782823d0fba3c7  frontend_dist/assets/chat-BkYmqNt_-V56C.js
dd4a6e6a33506863198924255daa5a185dc90ec7b4899f3df5517330af9f49d0  frontend_dist/assets/chat.index-DJMd_us4-V56C.js
d7e7fd1eb4084e45776f24b0914d9865eb48d8f42c413c7a78c19d85654105e9  frontend_dist/assets/config-BsCCj1Hx-V56C.js
704fb2b7cc9e550f14e3a93712dc68a9f41dc1efba6a5cd02628ecd89ff2d973  frontend_dist/assets/diagnose-CgjI3Cg1-V56C.js
e1ff692692522528e2d38c8a731bba12f3af148c14d214f9ff8fea47316228ae  frontend_dist/assets/event-engine-l0hs20f6-V56C.js
4cbf6615d29353fe56eca94016b4c3728985080ac80c4253962ca6b852c481d9  frontend_dist/assets/fate-BrcVsLmB-V56C.js
315a068e84a006de3dfc36d318641a9c85e31161cab1731ad6003ac0c198f457  frontend_dist/assets/index-5-VzmJtc-V56C.js
48604ef3b90ac2b8d6113276b2d5a5796a14b64985fcd406d56d26833bb1db5b  frontend_dist/assets/jszip.min-DIgHJL1D-V56C.js
604e7f6f0ca94d02e4174a506899a56ad60c53ff3dceff0581e4d34393f6eafb  frontend_dist/assets/labor-C3TD2Y6f-V56C.js
e6eec001a33d1c5473b76ede25cb4a951c99dc53aa0dbaf62523d3640e877456  frontend_dist/assets/lazyRouteComponent-CFjILrxq-V56C.js
45ccb85a32d83cd4d0027af988a7a518dd17a85684120f7e1870b6ee0cbb15d8  frontend_dist/assets/logs-BEiOiYad-V56C.js
f9b79083c2f64231221c310b50ba043a4c6d46e2b7b31f7627e98b54786deab0  frontend_dist/assets/memory-efcY2umJ-V56C.js
ccc4a76faf3dcca761381cc3582069864984314865f85985feba9e96bbe25e8e  frontend_dist/assets/pdf-CxLxk-yn-V56C.js
a23e5d3fdced86492bbbb1c964abd998e3d5e05ab4af6e2d8ed535ce5c53381f  frontend_dist/assets/pdf-DV2XDCc3-V56C.js
8ab0e5e30031b4a06ecfddd5ae9562f0227f830ee7ec9ed1a968b134243d2386  frontend_dist/assets/pdf.worker.min-Dswkl-cV-V56C.mjs
b0d4a42c1fc0b25b0d80c4a10c90c24b20df6f1683c5e9a8c81897a4b063c63d  frontend_dist/assets/play._sessionId-DJ7LAi8J-V56C.js
aba87f2a53e45ecdc9113fc30387d16e449d1676428cf5f82dd624c1df97d152  frontend_dist/assets/preload-helper-Czpn1I53-V56C.js
ac705c32407a32ca19f5a66facde70ca09510b53fcfe7835e52736eb8168f5fd  frontend_dist/assets/review-D-Kr9F9b-V56C.js
e0a79ad36c6ca1ffbc796c80aa5661803a9d1bc684e29d1587f48b4ba9a82714  frontend_dist/assets/rolldown-runtime-C0FnF6B9-V56C.js
2eb1d17f334d79f5c2b7c68aa45a2b50b46a7b2416a9a0f5e7de6ff7f2430322  frontend_dist/assets/root-DLTE-HSj-V56C.js
93e83aa6edf38ad12d1e4001ac0c5065ce3437473ce014c360b292257e8db35d  frontend_dist/assets/routes-aKifRtrJ-V56C.js
830a277cb63b2ccc0b990e7e708da2eb1c60b3d4fe37c14ff857cf4cc31a3eb6  frontend_dist/assets/shell-gwW-WKpO-V56C.js
4ab9428c7f83779262a37a3a6a456dc5c42ab0244c5c86dfe1455c0a9667ee22  frontend_dist/assets/social-BYPMAzYs-V56C.js
1379f66ed04d6386bbdc68f1d9d334f0b93e01a8cad934c0ba44c29ea92c81a2  frontend_dist/assets/src-SuYvKHvm-V56C.js
fb01d6dc542ac29e73e239fa4ea6cb2ce7475bbaee68560bb26ac26f4ec8e34b  frontend_dist/assets/styles-C84qSt0H-V56C.css
da788901b8cf3829116d793aa38a3cf44cac2fd91de19694b61eece4c0f23af8  frontend_dist/assets/timeline-CmyrKt7S-V56C.js
f83c31bf732d5774d6fc27f753c3763154673ad31e9245399208ba315ab20a0a  frontend_dist/assets/triggers-bPtCLXRS-V56C.js
c0ecaa6289447d74e1e2cdce97cd9b2e6a4d14f14bb9728e462bbc35256c33ef  frontend_dist/assets/upload-PkoedRAR-V56C.js
803cded403944c4a8773c74febade3ed7530aff05ba2ed0ecd9b6ccbbf7af0b1  frontend_dist/assets/use-selectable-Dumw7S2R-V56C.js
c7b5b0708785a90307f55f479e521b4525deb957b19761242b82f08c02c32ad6  frontend_dist/assets/useNavigate-DMQQ6XHo-V56C.js
9b996614ae73f9069749054ce54c8b60918f88fbd380407dde3d20d43be82d0a  frontend_dist/assets/useStore-Pi3dVb-t-V56C.js
badca6c4161276a8efe2de97a3ad6db9300ecff16943d1a0d3f6e66f55319745  frontend_dist/assets/user-BrfbdArt-V56C.js
a0fe2c84090e24b943e9743ef8b90fb3581514dea4d9adc65e782823d0fba3c7  frontend_dist/assets/welt-BkYmqNt_-V56C.js
2f51332116573b8f2b981814d7c7f5f234c4f56f00a5ef626d2658951789c517  frontend_dist/assets/welt._worldId-CUNII7hy-V56C.js
e94ece9e9838168527193793c8fb2e02ac0365b7329a0e3ae79863c5bfb35665  frontend_dist/assets/welt.index-CsM5VIc--V56C.js
b0d4a42c1fc0b25b0d80c4a10c90c24b20df6f1683c5e9a8c81897a4b063c63d  frontend_dist/assets/world._worldId-DJ7LAi8J-V56C.js
4f5f3a824c051d0c540042473db0ed039058f789ab5a54678c1e555cfc59d5f9  frontend_dist/index.html
f0ed36038df865282754649000f4cf9abb0090fd8db9b9f548fa2b2610618f4b  matrix_api/app.py
ae6e4a3771ff31c98d9e0f8cda3d88370ebd29812e17f354f7a334aba161adb1  matrix_api/conjunctive.py
8589bf243fefc4e111afef09052e13ed7068f0c3c529749fab990eb0dc584a0c  matrix_api/kernel.py
f1fdcf49affb51ce7f01d1d168c9ad5970b074b5fdeb83b811379f3edfbf1b0a  matrix_api/learning.py
3179ac32824eb83bbe02fae1c7be956bc299deffd1406f0a986a64d2783a6fc6  matrix_api/llm_contract.py
fc583bebf5cf77cd905fef0eeb29c069bc9c9b86965d79f9981af26ab2f39a37  matrix_api/repos.py
8e4041c5d6245170bbc4fb000ee5836a93aef6fef3ec4ea138c6018629096f53  matrix_api/tests/test_v56_session_context.py
41a8296818ef0313ce360e2cbd31143cc831a083a36a55725124bb4da201eda4  src/lib/matrix/kernel-bridge.ts
bb670042a5d76024b2d18c56a9248b49b7b0f7fb6f5a72976605f5c363eae5fd  src/lib/matrix/types.ts
56469309c9889112ff2d8c4db66132032528b303d03fdfd4486c9fa7c02bec75  src/routes/charakter.$charId.tsx
a236baac145c0c163bfd288dfc1bdb804178170b5b5556c015bbc1310e21baf0  src/routes/chat.$sessionId.tsx
30af0e6f842936a21578e1589d58b1f3ed75436c2b7936ebefda196ba7f16ab7  src/routes/config.tsx
ed8686e25d2a29114d0adb6f61c654c20407f12f1d885cc1e1ae80a16e68acc3  src/routes/logs.tsx
```

Die V53T-Assets wurden als kompletter Satz durch V56C-URLs ersetzt; alle neuen Dateien stehen oben.
Masterblatt selbst ist aus dem internen Dateihashregister ausgeschlossen (kein zirkulärer Eigenhash).

Reproduktion:

```sh
python -m pytest -q matrix_api/tests/test_v51_presence_kernel.py matrix_api/tests/test_v53_turntruth_core.py matrix_api/tests/test_v54_event_first.py matrix_api/tests/test_v55_continuity.py matrix_api/tests/test_v56_session_context.py
python scripts/test_v53_sps.py
```

Die Tests benutzen isolierte Datenbankkopien. Bei fehlendem Flask verwenden die SQL-/Transporttests ausschließlich einen Test-Importersatz; keine Flask-HTTP-Abnahme wird daraus abgeleitet.

</details>

<details><summary>Chronologie und frühere Befunde bis V55 (Archiv, nicht aktuelles Prüfsiegel)</summary>

# Aktueller Nachweis: V55 / FB08J - Log, Prompt und echte Formulierungsgrenze

**Stand:** 26.10.2026. **Art:** technische Pruefung des NEU hochgeladenen V55-Livepakets, keine neue Softwareversion und keine Behauptung eines behobenen Dialogfehlers. Dieser Abschnitt ist die aktuelle Einordnung; die vorherigen Abschnitte bleiben als Chronologie erhalten.

## Eingang und Abgrenzung

- Pruefauftrag: Gibt es ein Log / ein Promptlog? Welche konkrete Kette erzeugt weiter Tammys Wiederholungen? Keine neue Figurenarchitektur, keine Veraenderung ihrer Persoenlichkeit.
- Basis: das aktuelle Nutzer-ZIP, **nicht** das frueher ausgegebene unveraenderte V55-Paket. Die aktuelle Datenbank enthaelt einen neueren Lauf.
- Aktueller Lauf: `ses_391c5dcafb36b17c6dbbc7dd`, `Verfuehrung und Macht - 13:48`, vier Dialogturns. Zeiten im Log UTC; 12:48-12:51 UTC = 13:48-13:51 Europe/Vienna am 26.10.2026.
- Gelesen/ausgewertet: alle **512 JSON-Zeilen** in `logs/MATRIX10_LIVE.log`, alle **430 SQLite-Logdatensaetze**, aktuelle Session mit SQL-Kindtabellen, Charakterstamm einschliesslich Lernherkunft, vorhandener HTTP-Formulierungspfad, Testquellen. Relevante Funktionen und Aufrufer vorwaerts/rueckwaerts gelesen, nicht bloss Dateinamen gesucht.
- Kein API-Schluessel wird hier ausgegeben. Keine echte Provideranfrage in dieser Pruefung. Original-ZIP und Originaldatenbank bleiben unangetastet.

## Ein SPS-Weg mit Ein-/Ausgaengen

```text
IN: gespeicherte Welt-/Figurendaten + neue User-Eingabe
 |
FB08J.1  Sessionstart / Stamm
 Datei: matrix_api/kernel.py::build_new_session / reset_runtime_only
 READ:  characters.json-Spalte, learnedItems und bestehende Ziele
 OUT:   neue Session und Runtime; alter gelernter Stamm bleibt derselbe
 |
FB08J.2  Eingabe-Commit
 Datei: matrix_api/app.py::kernel_prepare (lokaler Plan bei Zeilen 1466-1477)
        matrix_api/conjunctive.py::local_plan
 IN:    Usertext + TurnTruth + Anwesenheit
 WRITE: vorhandene SQLite-Session/SceneFacts/Memory/Runtime/Goals
 OUT:   INPUT_COMMITTED vor der Antwort, aber regexbasierte Sprechakt-Klasse
 |
FB08J.3  Recall / Spiegel
 Datei: matrix_api/kernel.py::prepare_turn / bind_formulation_spiegel
 READ:  committed Sessionzustand, Fakten, Erinnerungen, Figurenstamm
 OUT:   spiegel.facts, runtime, profile, goals, goalEvidence, currentState,
        userUtterance, hauptsache
 FEHLER: stimulus wird ohne Sprechaktpruefung immer zur 'hauptsache' genommen.
 |
FB08J.4  Frontend -> Formulierungs-API
 Datei: src/routes/chat.$sessionId.tsx (Zeilen 275-351)
        matrix_api/app.py::api_llm_formulate (Zeilen 1882-1888)
 IN:    serverSpiegel -> POST /api/llm/formulate
 OUT:   formulate_from_config -> _try_llm
 TRACE: kein trace_id im Formulate-Payload; kein Prompt-/Rohantwort-Writer
 |
FB08J.5  Tatsachlicher Provider-Request
 Datei: matrix_api/llm_contract.py::_try_llm / render_persona_brief
 IN:    Spiegel -> Klartextbrief + fester Systemtext
 OUT:   messages=[system, brief[:14000]]
 BRUCH: 'compact' enthaelt facts/currentState, wird aber nicht gesendet.
        Typische Stammformulierungen erhalten bindende Inhaltsautoritaet.
        Jede 'hauptsache' wird als zu beachtende offene Bitte/Forderung bezeichnet.
 |
FB08J.6  Providerantwort / Nachbearbeitung
 Datei: matrix_api/llm_contract.py::_try_llm (Zeilen 775-821)
 IN:    erste Modellantwort
 PFAD:  Heuristik -> moeglicher zweiter Provideraufruf mit Neufassungsanweisung
        -> gegebenenfalls erster Satz entfernt ('repetition_trimmed')
 OUT:   nachbearbeitete Rede + Vorschlaege; nicht unveraenderte Rohantwort
 |
FB08J.7  Antwort-Commit / Anzeige / Log
 Datei: src/lib/matrix/kernel-bridge.ts::kernelCommitFigure (Zeilen 203-265)
        matrix_api/app.py::kernel_commit / matrix_api/kernel.py::commit_turn
 WRITE: Antwort und Folgezustaende in SQLite
 OUT:   UI-Ausgabe; TURN_END PASS = SQL-Readback erfolgreich
 TRACE: OUTPUT auf 200 Zeichen begrenzt; kein Beweis fuer Dialogfortschritt
```

## Konkrete Nachweise - keine allgemeine Vermutung

**J1 / Echte neue Sitzung:** Alle vier Dialogturns haben erfolgreiche Endeintraege. `pendingInputTurnId` ist am Ende `None`; dieser Lauf haengt nicht an einem nicht abgeschlossenen Datenbank-/Turn-Lock. `KERNEL_BIND` hat Tammy als Ziel und Antwortfigur, Tom als Eingabe-Akteur. Die SQL-Logs markieren die vier Antworten mit `(llm)`; der genaue rohe Providerverkehr ist dort nicht gespeichert.

Der erste gespeicherte V55-Dialog lautet:

```text
Tom: Hey schatz
Tammy: Hey, wie suess von dir, mir ein Wort zu schenken. Denkst du, das reicht?
       Ich will Klarheit, und zwar jetzt. Was ist dein Plan?
```

**J2 / Herkunft statt Geheim-Sperre:** Der Satzanfang `Hey, wie süß von dir, mir ein Wort zu schenken` steht in `characters.typicalPhrases`. Der passende `learnedItems`-Eintrag nennt die fruehere Session `ses_7e01251a0538dadfced95b66`, Turn 1, `2026-10-26T04:46:22+00:00`, Quelle `Tammy (eigene Rede)`. Dieselbe Wendung wird bei einer neuen Session wieder in den Persona-Brief geladen. Neue Session leert die alten Sessionfacts, nicht den Figurentext im Stamm. Das beweist den Eintragspfad; die genaue staerkemaessige Ursache der gesamten LLM-Reaktion ist ohne kontrollierten Providervergleich nicht bewiesen.

**J3 / Kein vollstaendiges Promptlog:**

- `matrix_api/llm_contract.py::_try_llm` baut den Request lokal und sendet ihn per `urllib.request.urlopen`, ohne die `messages` oder die rohe Providerantwort zu persistieren.
- Die Tabelle `logs` enthaelt `level, code, message, id, at, userId`, teils `sessionId, turn`, aber keine Prompt-/Rohantwortfelder.
- Das Textlog enthaelt `BRAIN_CONTEXT` nur mit Sprecher und `writable=false`, nicht den Inhalt.
- `src/routes/logs.tsx` zeigt den Reader-Detailtext nur als `JSON.stringify(row).slice(0,400)`. Der sichtbare BrainContext-Spiegel ist NICHT der nachfolgend serialisierte Provider-Prompt.
- `live_log._scrub` kuerzt Strings auf 800 Zeichen und Listen auf 40 Eintraege. Auch ein einfaches Einhaengen des gesamten Prompts dort waere noch kein vollstaendiges Promptlog.
- Ob bei einem historischen Turn der Wiederholungsaufruf benutzt wurde, welcher rohe Antworttext zuerst kam und wie viele Tokens verbraucht wurden, laesst sich aus diesen Logs nicht feststellen. Keine Behauptung ueber tatsaechliche Mehrkosten.

**J4 / Ausgefuehrte Request-Gegenprobe, ohne Netzwerk:** Echte Produktionsfunktionen wurden ausgefuehrt; nur der unbenutzte `get_config`-Import mit Flask-Abhaengigkeit wurde fuer den isolierten Formulierungsaufruf ausgelassen. Der HTTP-Transport wurde abgefangen. Keine Modellantwort wurde als live-getestet ausgegeben.

- Frische Session aus der mitgelieferten Welt und den echten Figuren, erster Input `Hey schatz`, vorheriger Input-Commit durch echten Kernel.
- Abgefangenes Paket: Systemtext 3040 Zeichen, gesendeter Brief 4545 Zeichen. Die aktuelle User-Eingabe erreicht den Brief; in dieser Gegenprobe schneidet die 14000-Grenze sie NICHT ab.
- Alle sechs Reaktionsregeln, einschliesslich der Maximal-zweimal-Regel, sind in V55 im Brief. Die aeltere V52-Aussage 'nur 4/6' ist KEIN aktueller V55-Befund.
- `spiegel.facts` und `spiegel.currentState` durch eindeutige andere Testwerte ersetzt: die gesendeten `messages` bleiben bytegleich. Direkte Felder gehen an dieser Stelle verloren. Das bedeutet NICHT, dass saemtliche Informationen fehlen: Memories, Frames, Runtime, Goal-Evidence und Verlauf werden teilweise separat gerendert.
- Tatsachlich erzeugte letzte Zeile: `Offene Bitte/Forderung, die du nicht übergehen darfst: Hey schatz`. Herkunft: `kernel.py:6031-6043` -> `llm_contract.py:719-740`.
- Kontrollierte Wiederholungsantwort im Transport geliefert: **zwei** abgefangene HTTP-Aufrufe; danach wird der erste Satz entfernt. Rueckgabe enthaelt `repetition_trimmed`. Das bestaetigt den Codepfad, nicht seine historische Nutzung in allen vier echten Turns.

**J5 / Hart codierte Wortabfragen sind wirklich beteiligt:** Der Input-Pfad `app.py::kernel_prepare` benutzt seit V54 `conjunctive.local_plan`. Direkt ausgefuehrte Beispiele:

| Eingang | Tatsachlicher lokaler Plan |
|---|---|
| `Und was genau willst du sehen, benne es.` | `claim` |
| `Was genau willst du sehen?` | `question` |
| `Ich bleib ich versürech es dir` | `claim` |
| `Ich verspreche es dir` | `promise` |
| `Ja genau, aber ich stimme nicht zu.` | `acceptance` |

Diese Abfragen warten nicht auf ein geheimes Tammy-Passwort. Sie ersetzen aber an der Eingabenaht semantische Erkennung durch Satzanfangs-/Wortmuster. Keine weitere Stichwortliste als angebliche semantische Reparatur hinzugefuegt.

## Was die gruenen Tests wirklich aussagen

Die vier vorhandenen Suiten `test_v51_presence_kernel.py`, `test_v53_turntruth_core.py`, `test_v54_event_first.py`, `test_v55_continuity.py` wurden gegen das aktuelle Nutzerpaket erneut ausgefuehrt: **26 passed**.

Der entscheidende Langzeittest `test_long_same_phase_changes_real_evidence_without_forced_phase_completion` liefert im Test selbst in jeder Runde `result={"speech": "Ich habe dich gehört.", "action": None}`. Er prueft Speicherung und unveraenderte Phasen, nicht die Formulierung durch einen Provider. Der Vierturn-Test in `test_v55_continuity.py` verwendet aufgezeichnete Ausgaben. Damit kann er nicht nachweisen, dass das LLM neue, kausal weiterfuehrende Reaktionen erzeugt.

**Abnahme fuer die beanstandete Wiederholung: NICHT BESTANDEN.** Die neue echte Session wiederholt weiterhin die Forderung. Kein Zustandstestraster wird hier zur Dialogabnahme umgedeutet. Eine Phase darf lange dauern; ein Gruenes SQL-PASS ist weder Erfuellung noch semantischer Fortschritt.

## Aenderungsregister dieses Durchgangs

- **Produktcode:** keine Aenderung; der Pruefauftrag dieses Durchgangs betrifft den belegbaren Log-/Promptpfad. Keine ungepruefte neue ZIP als Reparatur ausgegeben.
- **Originaldaten:** unveraendert und read-only gelesen; SHA-Vergleich mit ZIP-Eintraegen bestanden.
- **Dokumentation:** nur dieses vorhandene SPS-Masterblatt wird um FB08J fortgefuehrt. Keine zweite konkurrierende Systembeschreibung.
- **Pruefung:** vollstaendige Logauswertung, SQL-Lesepruefung, aktueller Codepfad, sechs lokale Gegenproben und die vorhandenen 26 Tests. Keine neuen Providerkosten. Eine Flask-HTTP-/Android-/Live-LLM-Abnahme wurde nicht durchgefuehrt; fehlendes Flask konnte wegen fehlender Namensaufloesung nicht installiert werden. Es wurde keine simulierte Providerantwort als echte ausgegeben.

## Quellhashes des aktuellen Nutzerpakets

- ZIP SHA-256: `0501263084eb53d1c4ca1d94691cf5c6974383aec34db9d0d501ecc5feb75f54`
- `matrix_api/kernel.py`: `efcd7808952ee6d3b1d27ec2360bcb1c8345feb702f028bf86bc8b6591920681`
- `matrix_api/llm_contract.py`: `f67c67366f13a3ee7de5e3ea926f2eeae343e7e00dcd0ca3d9cf0078b7fd2ca1`
- `matrix_api/app.py`: `3c8925fc3b7035692920212f8739027b6a722fc1dce4bd63fb91fe5b30cf7e9e`
- `matrix_api/conjunctive.py`: `bf2307bd783ba3345790463b25ec10ba4a5db0ac3f48badf9f76a6444b2d82ee`
- `matrix_api/live_log.py`: `89e29dfae05615353fd4b9e1d7dde1a82f9cb5dbedcd8ad140d320c7af136c34`
- `data/matrix10.sqlite`: `c1e5a85ef0469aa0146ecf50db6aa728d7bb2c2cf838383e87f408b3ab104177`
- `logs/MATRIX10_LIVE.log`: `f0f0b61b8e4d74bea966711722a8d1442a37f8fddf68d608dcedb188efcab154`

<details>
<summary>Abgefangener Vergleichsprompt: reale Serialisierung in einer frisch rekonstruierten Sitzung; KEIN historisch aufgezeichneter Live-Prompt</summary>

```text
SYSTEM
Du BIST die Figur in der Szene. Du sprichst laut, als Mensch im Raum. Antwort NUR JSON: {"speech": string, "action": string|null, "synapsen": [{"raum": string, "aktivierung": 0..1, "grund": string}], "emotion": string, "beziehung": {"zu": string, "trust": -0.15..0.15, "closeness": -0.15..0.15, "fear": -0.15..0.15, "grund": string} | null, "plan": {"event_kind": "claim|proposal|acceptance|request|disclosure|state_change|revocation|refusal|action|report|question|promise|smalltalk", "durability": "utterance|durable_state|commitment|knowledge_transition|action_event", "summary": string, "temporal": {"text": string|null}, "refers_to": string|null, "cue_terms": []}}. speech: 1–4 gesprochene Sätze in der Ich-Perspektive der Figur, Dialog, kein Bericht. action: sichtbare Körperhandlung oder null. VERBINDLICH: Der Brief unter DU BIST … (Persönlichkeit, Sprachregister, Humor, Konfliktstil, Werte, Ängste, Geheimnisse, Tabus, Reaktionsmuster, typische Wendungen) bestimmt Ton und Inhalt — antworte so, wie GENAU DIESE Figur antwortet (z. B. sarkastisch, trotzig, knapp), nicht wie ein freundlicher, neutraler Assistent. DEIN ZUSTAND JETZT, DEINE BEZIEHUNGEN und DEIN KÖRPER begrenzen die Reaktion. DEIN KÖRPER ist BINDEND: Haltung gilt weiter, bis du sie mit einer sichtbaren action änderst; Verletzungen/Schmerz/nicht möglich sind wirksam; erwähne die körperliche Lage, wenn sie das Gespräch berührt. Gehe ZUERST auf JETZT SAGT … ein: beantworte die Frage, erwidere die Anrede, trage die Stimmung — gegenüber DEM, der es gesagt hat; eine andere Figur (Puppet) ist nicht der Avatar. DU ERINNERST DICH / DU WEISST / LETZTER VERLAUF sind das Original — erfinde kein neues Weltwissen und keinen Verlauf; Fragen zum Gesprächsverlauf beantwortest du NUR daraus, sonst sagst du in der Rolle, dass du dich nicht erinnerst. Abwesende hören nichts; wenn nach einer Abwesenden gefragt wird, spricht die anwesende Figur über sie. synapsen: welche Bedeutungsräume die Äußerung/Lage für GENAU DIESE Figur berühren — nur aus: Bedrohung, Angst, Verrat, Lust, Geld, Trennung, Gewalt, Mord, Eifersucht, Verlust, Abhaengigkeit, Moral, Risiko, Schutz, Macht; aktivierung = Stärke aus Persönlichkeit, Ängsten, Geheimnissen, Beziehung; 0–3 Einträge; nichts erfinden. emotion: die jetzt spürbare Emotion (ein Wort). beziehung: nur wenn die Äußerung die Haltung zum Gegenüber (Name aus SZENE/anwesend) messbar bewegt, sonst null. plan: was DEINE eigene Antwort tut (Konjunktives Gedächtnis): Vorschlag/Annahme/Ablehnung/Versprechen/Widerruf/Offenbarung/Frage/Smalltalk, mit summary (ein Satz, was gilt), temporal.text (Zeitangabe wörtlich, sonst null), refers_to (worauf du antwortest, wörtlich aus VEREINBART/Verlauf, sonst null). Diese Vorschläge prüft und begrenzt der Kernel; sie ersetzen keinen Zustand. Kein Erzähler, kein 'Antwort:', kein Meta ('der nächste Zug folgt', 'gebundenes Original'). Keine Begrüßung und nicht die letzte eigene Rede wiederholen. Emotion muss in Ton oder Handlung spürbar sein. DRUCK (Fate) spürst du, du sprichst ihn nicht aus.

USER / PERSONA-BRIEF
DU BIST Tammy (30, weiblich, Verführerin, Verführerin).
Persönlichkeit: Manipulativ, impulsiv, emotional instabil, aber zu echter Bindung fähig, wenn sie sich sicher fühlt
Hintergrund: Tammy ist eine komplexe Figur mit psychischen Problemen, die sie in ihrer Suche nach Liebe und Kontrolle antreiben. Sie hat eine dunkle Vergangenheit, die sie verfolgt. Sie testet Menschen, um sich vor Verlust zu schützen – wer den Test besteht, bekommt ihre Nähe; wer ihn nicht besteht, wird kalt bestraft.
So sprichst und streitest du — Sprachregister: Umgangssprache, vulgär · Dialekt: Vulgär · Humor: Sarkastisch · Konfliktstil: Konfrontativ, aber mit klarer Eskalationslogik: erst Test, dann Angriff, dann – wenn bestanden – Öffnung.
Typische Wendungen von dir: Ich will Klarheit, und zwar jetzt | Du weißt es nicht | Und jetzt? | Hey, wie süß von dir, mir ein Wort zu schenken | Und wo genau warst du, als ich am meisten gebraucht habe
Lieblingswörter: Liebe, Kontrolle, Schmerz, Klarheit, Beweis, bleiben
Werte: Liebe; Macht; Sicherheit
Was du im Großen willst: Tom testen, ob er wirklich bleibt, wenn es schwer wird.; Bindung (wegen Tom)
Was du fürchtest: Verlassen zu werden; Nicht geliebt zu werden; Dass ihre Verletzlichkeit gegen sie verwendet wird
Was nur du weißt (nie offen aussprechen, aber es färbt dich): Hat eine traumatische Kindheit; Versteckt ihre Unsicherheiten hinter Angriffen; Wünscht sich insgeheim, dass jemand ihre Tests durchschaut und trotzdem bleibt
Du magst: Aufmerksamkeit, Komplimente, Nachtleben, klare Ansagen · Du magst nicht: Einsamkeit, Ablehnung, leere Versprechen, Ausweichen
Tabus für dich: Ehrlichkeit über ihre Angst (sie kann es erst, wenn sie sich sicher fühlt); Verletzlichkeit vor einem Test
Reaktionsmuster: Aggressiv bei Kritik; Zieht sich zurück, wenn sie verletzt ist; Wenn Tom eine konkrete, überprüfbare Handlung liefert: akzeptiert sie den Test (Phase 1 endet).; Wenn Tom weiter nur Worte liefert: eskaliert sie (Phase 2 – Bestrafung).; Wenn Tom sie durchschaut und ruhig bleibt: wird sie still und öffnet sich (Phase 3).; Sie wiederholt einen Vorwurf maximal zweimal – danach eskaliert sie oder zieht sich zurück. · Bindungsmuster: Wiederholte Beziehungen zu emotional instabilen Partnern; Erst Test, dann Bindung – nie umgekehrt
Kernfakten über dich: Psychisch instabil; Hat eine obsessive Liebe zu Tom; Testet Menschen, um sich vor Verlust zu schützen

DEIN ZUSTAND JETZT: Nähe (Intensität 0.782; Angst 0.25, Wut 0.1, Scham 0.1, Stress 0.25) — Ursache: Hey schatz.
Was du gerade willst: Bindung
Was in dir anspringt: Lust (0.60) → Tammy nutzt ihre Verführungstechniken, um Tom zu manipulieren.
DEINE WICHTIGSTEN BEZIEHUNGEN (Stamm): Tom: Liebesbeziehung — Vertrauen 0.30 (Tammy hat eine obsessive Liebe zu Tom. Sie testet ihn, um sicherzugehe) | Kvle: Freundschaft — Vertrauen 0.40 (Locker, aber von Misstrauen geprägt.)
DEINE BEZIEHUNGEN ZU DEN ANWESENDEN: Tom: Liebesbeziehung — Vertrauen 0.30, Nähe 0.80, Furcht 0.70 (Tammy hat eine obsessive Liebe zu Tom. Sie testet ihn, um sicherzugehen, dass er)
OFFENE SZENE: Status open, Eskalation 0.00; Akteure Tom → Ziele Tammy
Nächster Beat erwartet von: Tammy — das bist du.
Antworte aus der offenen Szene heraus (Beats, Eskalation, Emotionsspur), nicht nur auf den letzten Satz.

DU ERINNERST DICH (kanonisch, nur das):
- Turn 1: [gehoert] Der Gast sagte: Hey schatz
So begann das Gespräch: Tom: Hey schatz (insgesamt 1 Turns)
DU WEISST: Psychologische Manipulation; Verführungstechniken; Erkennt echte vs. leere Versprechen; Der Gast sagte: Hey schatz
DU WEISST NICHT: kennt keine fremden Gedanken; kennt nur, was sie selbst erlebt, gehört oder gesehen hat; kennt die Geheimnisse anderer nicht, sofern nicht selbst bezeugt
Offene Ziele/Absichten: Tom testen, ob er wirklich bleibt, wenn es schwer wird.; Bindung (wegen Tom)
Bisher in diesem laufenden Ziel erlebt (nicht automatisch erfüllt): Turn 1: gehört/behauptet — Hey schatz

SZENE: Wohnzimmer, jetzt; anwesend: Tammy, Tom; hört: Tammy, Tom; offen: Ein düsteres Spiel um Kontrolle und Begierde.
DRUCK (Fate, nur spüren, nicht aussprechen): Folge offen: Tammy: Wissen wirkt (Lust) — Druck 0.8900000000000001; Verbot: Kein erfundenes Wissen. Abwesende wissen nichts. Avatar nicht steuern.
LETZTER VERLAUF (was du gehört hast):
- Tom: Hey schatz

JETZT SAGT Tom (Avatar): "Hey schatz"
ANTWORTE ALS Tammy: 1–4 gesprochene Sätze, in deinem Register und deiner Stimmung, zuerst auf die Äußerung; dann synapsen/emotion/beziehung als JSON.
Offene Bitte/Forderung, die du nicht übergehen darfst: Hey schatz
```

</details>

---

# Bisherige SPS-Chronologie (unveraendert)

# MATRIX10 / CHATHERE – EIN SPS-MASTERBLATT

**Aktuelle Ausgabe:** V54 · 26.10.2026 · `MATRIX10_CHATHERE_V54_EVENT_FIRST_20261026`  
**Direkter Basisstand:** V53 · 26.10.2026 · `MATRIX10_CHATHERE_V53_TRUTH_COMMIT_20261026`  
**Basis:** V51 `MATRIX10_V51_PRESENCE_FIX_20261026.zip` · SHA-256 `79955c7d6f808e9f1a263ff7dc8bb89d31803143d4c8d79b562d7776e25ab5d2`  
**Gültig für:** die mitgelieferte V54. Ältere V52/V53-Abschnitte sind dokumentierte Vorstände, nicht der aktuelle Commit-Pfad.  
**Regel:** Bei jeder neuen Version **dieses eine Blatt fortschreiben**, keine weiteren Deckblätter, Diagramm- oder Patchberichtserien. Neue Funktionen/Fixes erhalten eine FB-ID und werden unten mit Code, Ein-/Ausgängen, SQL-Owner, Fehlerpfad und Test dokumentiert.

## 0 – Zentrales Fließbild, wie ein SPS-Funktionsplan

```text
                         FRONTEND – BEDIENUNG
    ┌─────────────────────────────┴──────────────────────────────┐
    │                                                            │
  [FIGUR LÖSCHEN] FB01                                     [CHAT] FB02/05
    IN: charId, User                                           IN: TurnTruth,
    │                                                          Actor/Target, Zeugen
    ▼                                                            │
  [API DELETE] ──> [SQL-OWNER: delete_character]                ▼
    │              ├─ User-/Welt-Owner-Prüfung             [KERNEL: phase=input]
    │              ├─ lebende Session-/Runtime-Refs              │
    │              │  ablösen                                     ├─ SceneFacts/Memory
    │              ├─ character/world/user aktualisieren         ├─ Witness/Relation
    │              └─ historische SQL-Kinder NIE löschen         └─ Goals/Runtime
    │                        │                                   │
    ▼                        ▼                                   ▼
  [HTTP ok/Fehler] <── [SQL COMMIT]                    [SQL INPUT-COMMIT]
    │                        │                                   │
    ▼                        ▼                                   ▼
  [FRONTEND READBACK] → [SITZUNG + WELT]               [RECALL / SPIEGEL]
    │                                                            │
    ▼                                                            ▼
  [FIGUREN UI]                                            [LLM FORMULIERT]
    │                                                            │
  (nur nach Erfolg)                                      [RESPONSE-COMMIT]
                                                                 │
                                                          [SQL / READBACK]

  [GELERNT: ALTE EINTRÄGE] FB03     [TIMELINE: ZIEL ERFÜLLT] FB04
    IN: explizites Bestätigen        IN: goalId + status=fulfilled
    → PATCH CHARACTER                → PATCH GOAL
    → learning.remove_learned        → Folgeziel pending→active
    → SQLite / Readback              → SceneFact + SQL / Readback
    → Anzeige                        → Timeline/Recall

  FB00 V51: Anwesenheitsschalter → apply_presence → SceneFact + Runtime
            → SQLite → Readback → Frontend; bestehender Fix unverändert.

  FB07: START.py → V54 Build-ID/Port-Bindung → unverändertes
         frontend_dist V53T → Backend V54. Alte laufende Server dürfen
         nicht als V54 ausgegeben werden.
```

## 1 – Jeder geänderte Funktionsweg, direkt als IN → Verarbeitung → OUT

### FB00 · Anwesenheit (aus V51 übernommen)
- **IN:** User tippt Figur im Chat; Session-ID, Figur-ID, Ort und aktuelle Anwesenheit.
- **Funktion:** `kernel.apply_presence`; bei Ein-Ort-Welt `anderswo` statt wieder `Wohnzimmer`.
- **OUT/WRITE:** SceneFact `presence`, `scene.presentIds`, Runtime-Position; bestehender SQLite-Commit; UI synchronisiert nach Server-Readback.
- **FALLBACK/FEHLER:** falsche Orts-ID führt nicht mehr zur Wiederanwahl desselben Orts.
- **STATUS:** V51-Kernel-Regressionsprüfungen 2 PASS; HTTP-Anwesenheitstest ohne Flask 1 SKIP.

### FB01 · Figur löschen: UI → API → SQLite → UI
- **IN:** Benutzer, Welt, `characterId`, ausdrücklicher Lösch-Dialog.
- **UI:** `src/routes/charakter.index.tsx:removeFigure`, `charakter.$charId.tsx:CharakterPage`; Bedienung wartet auf Resultat, zeigt HTTP-Fehler, navigiert bei Erfolg.
- **Transport:** `src/lib/matrix/api.ts:apiDeleteCharacter` → `DELETE /api/characters/<charId>`; `store.ts:deleteCharacter` seriell via `writeOrRevert`.
- **Owner/COMMIT:** `matrix_api/repos.py:delete_character` (eine SQLite-Transaktion): prüft Rechte, löst `avatarId`, `scene.presentIds/hearsIds/seesIds`, `runtimes`, aktive `sceneState`- und Fokusverweise aus eigenen Sitzungen, Welt-`characterIds` und User-Avatarauswahl; erst dann `DELETE characters`.
- **OUT:** `deleted`, `sessionUpdates`, kanonische `world`, `user`; Frontend übernimmt Server-Readback – keine zweite Schatten-Löschlogik.
- **Unveränderlich:** SQL `turns`, `scene_facts`, `memories`, `witness_knowledge`, `relationships`, `goals`, `god_facts` historisch vollständig erhalten. Die Geschichte bleibt über die ursprüngliche Figuren-ID lesbar.
- **Fehler:** 403 fremder Eigentümer; 409 `CHARACTER_FOREIGN_SESSION` falls gemeinsame Welt in fremder aktiver Session gebunden; HTTP/SQLite-Fehler → keine UI-Löschung.
- **Grenze:** Löschen ist keine physische Tilgung sämtlicher Erwähnungen aus historischen Texten. Absichtliche Erhaltung der Beweiskette.

### FB02 · Chat-Rückkopplung: falschen Stammwriter abtrennen
- **IN:** `POST /api/kernel/commit`, validierte `TurnTruth`, Nutzer- oder Figurenrede.
- **ALT/FALSCH:** `matrix_api/app.py:_learn_after_turn` übernahm aus generierter Rede automatisch `goals`/`typicalPhrases`/weitere Werte in den dauerhaften `characters`-Stamm. Wiederkehrende Rede wurde im nächsten Spiegel selbstverstärkend gelesen.
- **NEU:** Dieser **automatische** Aufruf samt Helper entfernt. `matrix_api/kernel.py:commit_turn` schreibt weiter Ereignis/Fakten, Figurenwissen, Runtime und Memory im normalen Session-Writer. `bind_formulation_spiegel` liest, schreibt nicht.
- **OUT/WRITE:** Keine neue automatische Stammänderung aus LLM-Antworten; der bereits vorhandene Session-SQL-Commit bleibt aktiv. Kein Prompt-Guard, kein Output-Ersatz.
- **Altbestand:** Historische gelernte Wiederholungswerte bleiben bis zur **expliziten** Entfernung (FB03). Dies garantiert noch nicht, dass ein LLM nie ähnliche Sätze bildet.

### FB03 · Alte automatische Lernwerte bewusst zurücknehmen
- **IN:** Charaktereditor → Tab **Gelernt** → „Alle alten Lernwerte entfernen“ (Bestätigung), oder Einzelwert „Entfernen“.
- **Verarbeitung:** `store.ts:patchCharacter` → `PATCH /api/characters/<id>` mit `removeLearnedAll:true` (oder `removeLearned:id`) → `repos.patch_character` ruft vorhandenes `learning.remove_learned` je vorhandener Ledger-ID auf.
- **OUT/WRITE:** nur gespeicherte `learnedItems` plus ihre belegten Feldwerte im Charakter-Stamm ändern sich; SQL-Readback aktualisiert sofort den Tab.
- **Unverändert:** Welt, Sessions, SceneFacts, Turns, Memory, Witness, Relationship. Ohne Benutzeraktion kein Rückbau.
- **Fehler:** HTTP-/Writerfehler → kein UI-Erfolg, Fehlermeldung, keine stillen Löschungen.

### FB04 · Phasenziele: Stamm → aktive Sitzung → Timeline
- **IN:** strukturiertes Figuren-Stammziel mit `id,phase,text,exit,next` bei **neuer** Sitzung.
- **KERNEL/SQL:** `kernel.build_new_session` schreibt Ziele als bestehende Session-`goals` mit `sourceGoalId`, `nextGoalId` und `status` (`active` für Ursprung, `pending` für Folge); `repos.create_session_goal` / `kernel_session_response` schreibt nach SQLite.
- **RECALL:** `kernel.bind_formulation_spiegel` liest aktive Session-Ziele statt rohe Dict-Objekte aus dem Stamm.
- **BEDIENUNG:** Timeline → Ziel „erfüllt“ → `store.ts:patchGoal` → `repos.patch_session_goal` aktiviert vorhandenes Folgeziel + schreibt zwei auditable `goal_state_changed`-SceneFacts → vollständige SQL-Sitzung an Frontend zurück; neue Phase sofort sichtbar.
- **Grenze:** Automatisches Verstehen der Exit-Bedingung aus freiem Text ist **nicht implementiert**; Folgephasen gehen durch vorhandene Timeline-Bedienung weiter, nicht durch LLM-Behauptung. Bestehende Alt-Sessions erhalten keine heimliche Zielmigration. `scene.phase` (globale Szenenphase) bleibt eine andere Zustandsgröße.

### FB05 · Erhaltener Chat-Sachpfad (nicht als neuer Fix ausgeben)
- **IN:** UI Chat → `/api/kernel/prepare` (nur lesen, Speaker/Target/Zeugen) → `/api/kernel/commit`.
- **Verarbeitung:** `app.py` bindet `TurnTruth`, `kernel.prepare_turn`, `kernel.commit_turn`; `repos.kernel_session_response` persistiert SceneFacts, Memory, WitnessKnowledge, Relation/Runtime sowie Turns und Session; Recall (`kernel.recall`/`bind_formulation_spiegel`) vor Antwort.
- **OUT:** Figurensprache über LLM/Renderer aus dem gespiegelten Zustand.
- **OFFEN:** Nicht jede frei formulierte körperliche Aktion wird im alten Parser zuverlässig als Handlung statt Rede erfasst. V52 hat den Parser **nicht** als behoben markiert.

### FB07 · Versionssichere Auslieferung
- **IN:** `python START.py`, Port 5050 (API), Port 8080 (UI).
- **Verarbeitung:** `START.py` liest `VERSION.txt`, prüft alte Server-Build-IDs, liefert `frontend_dist/index.html` und exakt 42 versionierte `V52S`-Assets aus; kein Node zur Laufzeit.
- **OUT:** Systemstatus mit `MATRIX10_CHATHERE_V52_SPS_FIX_20261026` in Backend-Health, UI und Start-Marker.
- **Fehler:** altes Backend oder anderes Frontend auf Port → klarer Startfehler **statt stiller Weiterbetrieb von V51**. Browser-Cache greift nicht auf die alten `V51P`-Namen zurück.

## 2 – Versionen und verantwortliche Änderungen

| Version | Ursache | betroffener FB | Ergebnis/Prüfstand |
|---|---|---|---|
| V49 (06.09.2026) | Basis AMASTER/ChatHere | FB05 | Bestandsarchitektur; frühere Reports keine V52-Liveabnahme |
| V50 (26.10.2026) | integrierter Stand aus `Download246_12` | FB05 | Quellgrundlage von V51; Liveprüfung offen |
| V51 (26.10.2026) | Anwesenheits-Abwahl in Ein-Ort-Welt verwies wieder auf denselben Ort | FB00 | Kernel-Fix, Bedienpfad; 2 Tests PASS |
| V51-D01 (26.10.2026) | Lösch-409 und wiederholte Rede diagnostiziert | FB01/02/04 | **NUR Diagnose**, kein korrigiertes ZIP |
| **V52 (26.10.2026)** | tatsächlicher Löschpfad/lernende Rückkopplung/Phasen/alte UI-Bundles | FB01–FB04, FB07 | Korrekturen in Python+TS+gelieferten JS-Assets; unten separat geprüft |

## 3 – Geänderte Dateien: Code-Owner, vorher/nachher

Die folgenden Hash-Spalten sind **die ersten 12 Hex-Zeichen von SHA-256** (`vorher` = V51 ZIP, `nachher` = V52). Alle 42 ausgelieferten Assets wurden außerdem unter `V52S` umbenannt; inhaltlich geändert sind die drei oben benannten UI-Bundles. Andere umbenannte Assets erhalten neue URLs nur wegen des 1-Jahres-Caches.

| FB | Datei | Funktion / Ein-Ausgang | SHA vor → nach |
|---|---|---|---|
| FB01 | `matrix_api/repos.py` | delete_character; patch_character; patch_session_goal | `7dcb1f262bb1` → `623f39358eee` |
| FB02 | `matrix_api/app.py` | kernel commit; kein _learn_after_turn | `6eff047d16e0` → `10510fd4f8e2` |
| FB04 | `matrix_api/kernel.py` | build_new_session; bind_formulation_spiegel | `e8845a04ace4` → `8921cf8c09ea` |
| FB01 | `src/lib/matrix/api.ts` | apiDeleteCharacter | `9763e62fb385` → `5cd29cde67fe` |
| FB01,FB03,FB04 | `src/lib/matrix/store.ts` | deleteCharacter; patchCharacter; patchGoal | `b8b2777e1a89` → `90adcdacd3e2` |
| FB01 | `src/routes/charakter.index.tsx` | removeFigure | `ab662a8708c4` → `86f28c7fac32` |
| FB01,FB03 | `src/routes/charakter.$charId.tsx` | CharakterPage / Gelernt | `a89f3e026b30` → `43d1ac1480fe` |
| FB07 | `src/lib/matrix/types.ts` | BUILD_ID | `4a313b671f10` → `2da5a45306fe` |
| FB07 | `START.py` | _marker_ok; _send_marker; main | `cacb9b0f40f5` → `db38c57ad327` |
| FB07 | `frontend_dist/index.html` | SSR + Modulverweise | `faa305648adb` → `020f70a145fa` |
| FB01,FB03,FB04 | `frontend_dist/assets/shell-gwW-WKpO-V52S.js` | kompilierte UI-Schreibwege | `neu` → `f1cfb64b5730` |
| FB01 | `frontend_dist/assets/charakter.index-BZymjt0P-V52S.js` | Löschliste | `neu` → `5aa0d9900ae0` |
| FB01,FB03 | `frontend_dist/assets/charakter._charId-Uak7xfF8-V52S.js` | Löschen / Gelernt | `neu` → `fbac2f5f458f` |
| FB-tests | `scripts/test_v52_sps.py` | SQLite-Regression | `neu` → `22ee43918c50` |
| FB07 | `frontend_dist/.build-info.json` | Build-Manifest | `f14def2f1f7e` → `9ff52fd69852` |

## 4 – SQLite, Tests, Auslieferungs-Grenzen

- **Gelieferte Original-DB:** `data/matrix10.sqlite` SHA-256 `d2c1a9303e69080fe1cfbab1dbd969b1f6d24d79a7ebc042b801a3ba87e6a73d`. Von V51 zu V52 bytegenau **unverändert**. Bestandszahlen: 3 Welten, 19 Figuren, 5 Sessions, 60 Turns, 124 SceneFacts, 129 Memories, 281 Witness-Zeilen, 35 Relationships, 28 Goals.
- **SQL-Regression (PASS):** `python scripts/test_v52_sps.py` auf temporärer Kopie. Fremduser 403, fremde aktive Session 409 ohne Commit; drei eigene Sitzungen von Test-Figur gelöst, Figur gelöscht, sieben historische SQL-Kindtabellen zählgleich, `PRAGMA integrity_check=ok`, Original-SHA unverändert; 11 historisch gelernte Werte bewusst entfernt; Phasenkette active→fulfilled→next active und zwei SceneFacts.
- **Frontend (PASS auf Syntax/Verweisebene):** 42 gebündelte Assets, 350 geprüfte Asset-Referenzen; 40 JS-Chunks `node --check`; 5 veränderte TypeScript-/TSX-Dateien vom TypeScript-Parser ohne Syntaxdiagnosen. In `frontend_dist/.build-info.json` SHA/Provenienz der ausgelieferten Dateien.
- **HTTP-UI (PASS nur für statische Auslieferung):** `ThreadingHTTPServer` GET `/`, GET `/__matrix_start_health`, GET JS-Bundle, Build-ID und immutable-Header geprüft; **kein** interaktiver React-/Android-Test.
- **V50-Feldschreibtests:** `node scripts/test-v50-field-writes.mjs` mit lokal temporär eingebundener globaler TypeScript-Runtime: **4 PASS** (kein verlorenes Tippen durch ältere Schreibantworten).
- **V51-Bestandsregression:** `python -m pytest -q matrix_api/tests/test_v51_presence_kernel.py matrix_api/tests/test_v51_presence.py` → **2 PASS, 1 SKIP** (Flask fehlt).
- **NICHT LIVE GRÜN:** Flask-Aktion über Port 5050, echtes Android-Tippen/Löschen, kompletter KI-Provider-Dialog und Loop-Verhalten über zahlreiche Turns. Hier sind `flask`/npm-Dependencies nicht installiert; keine Vollabnahme und keine reproduzierbare Vite-Neukompilation. Die ausgelieferten JS-Bundles wurden direkt mit den TS-Änderungen nachgeführt und geprüft.
- **Testweise Isolation:** Der SQL-Test importiert echte Repository-Writer mit einem *nur im Testskript* verwendeten Flask-Import-Shim; SQL ist echte SQLite, keine Test-Shadow-Datenbank im Produkt. Produktcode hat keine neue Sonderfall-Behandlung für Figuren oder Stichwörter.

## 5 – Betrieb und nächste Untersuchung

1. Bestehende V51-Prozesse auf Port 5050/8080 **vollständig beenden**. V52 in **neuen Ordner** entpacken; `python START.py` aus diesem Ordner starten. Bei gemischter Version meldet der Starter einen Fehler, statt die alte still zu übernehmen.
2. Charaktereditor → Figur löschen: nur aktive Sitzungseinbindung wird abgehängt. In „Gelernt“ kannst du bei Bedarf alte automatische Einträge **bewusst** bereinigen.
3. Für Phasenziele **neue Sitzung** erzeugen; in Timeline ein aktives Ziel nach überprüfter Handlung auf „erfüllt“ setzen; nächstes Ziel muss automatisch aktiviert werden.
4. Falls die Dialogschleife bleibt: **neues Log/echte Session** mit vorher/nachher `scene_facts`, aktiven Goals, Runtime, Memory, Witness und gesendeten Provider-Kontexten prüfen – nicht durch neue Promptregeln verdecken.

**Künftige Änderungen** gehören nur an die jeweilige FB-ID in **dieser Datei**: zuerst IST-Pfad / Eingänge / Writer / Reader / Wirkung / Rückkopplung / Fehlermeldung, danach Änderung samt SHA und getrennten statischen/live Tests. Keine zweite Architektur, kein Backend-only Feature, keine generierten Parallelberichte.


---

## FB08 · TAMMY-DIALOG – D02 IST-PRÜFUNG (26.10.2026)

**Status:** Fehler in aktueller, vom Nutzer neu hochgeladener V52-ZIP **nachgewiesen**; **kein Fix**, kein Produktcode verändert, keine Datenbank verändert, kein Android-Livetest. Diese Ergänzung ist Bestandteil **dieses einen Masterblatts**. Zuvor beschriebene V52-Fixes bleiben gesondert zu bewerten.

**Prüfgrundlage:** `MATRIX10_V52_SPS_FIX_20261026.zip` SHA-256 `c74840c9dee50ae1306b327451032329231936994bcf2ef154d888943a31cdf8`; darin `data/matrix10.sqlite` SHA-256 `1804abfc4f887f8560f240d9ec678ca06843c6302993ee17d5645c69fd153c27`. Reale Zielsession `ses_2d215496c9f5295c9404ae1b` („Verführung und Macht“). Log `logs/MATRIX10_LIVE.log`, eingebettete UTC-Zeitstempel 05:34–05:37. `Kvle` ist die tatsächliche Schreibweise der DB-Figur.

### SPS-Eingang → Verarbeitung → SQL-Ausgang → Rückkopplung

```text
FB08A: UI chat.$sessionId.tsx
IN: Avatar Tom; Stimulus „ich war neben dir, habe geholfen“; Figuren Tammy, Tom in Wohnzimmer
    └─ Zielwahl bleibt in targetId gespeichert; auch wenn Kvle aus presentIds entfernt wird
       → kernelPrepare(targetId=Kvle; speaker=Tammy; actor=Tom)
           ↓
FB08B: API app.py /kernel/prepare + /kernel/commit
    └─ _canonical_target akzeptiert Kvle, weil Weltzugehörigkeit genügt;
       direkte Präsenz/Anrede werden nicht gegengeprüft
       → TurnTruth.target_id=Kvle [5/5 Dialogturns; Kvle nicht anwesend]
           ↓
FB08C: LLM-Turn-Plan → conjunctive.normalize_plan/apply_plan → SQLite
    └─ _extract_user_plan erhält Kvle als Empfänger
       „Ich war da, neben dir“ → strukturierter falscher Plan
       „Tom hat Kvle geholfen“ (T3, T4, T5), Stammbasis der Claims/Frames
           ↓
FB08D: LLM-Widerspruch → truth.validate_llm_contradictions → commit_turn
    └─ Wortüberlappung mit bekanntem Text akzeptiert auch inhaltlich unpassenden Vergleich
       → T3 + T4: falsche contradiction-SceneFacts
       → apply_contradictions: Tammy.emotion=Skepsis; Beziehung Tammy→Tom je −0,10
           ↓
FB08E: Recall + Ziele + Szene
    ├─ Figur hört Tom korrekt (Wissenszugriff vorhanden)
    ├─ aber Claims/Frames tragen Kvle und Konflikte, alte Lernwerte bleiben im Stamm
    ├─ SceneState: jeweils neue offene Beweisfrage → Tom beantwortet → neue Frage
    └─ Zielphase 1 active; Phase 2 und 3 pending; Szene.phase „Anfang“
           ↓
OUT: LLM antwortet weiterhin mit Misstrauen/„mehr als Worte“;
     nächste Runde verwendet dieselben fehlgebundenen/konfliktbelasteten Fakten
```

### Beweis- und Funktionskarte (Bestand, **nichts davon jetzt repariert**)

| FB | Code-Eigentümer / konkreter Pfad | Eingang → **Ist-Ausgang** | Beweis / Abnahme |
|---|---|---|---|
| 08A | `src/routes/chat.$sessionId.tsx` ca. 98, 139–143, 249–265, 863 | `targetId` wird nur gesetzt, wenn leer; nicht invalidiert bei Anwesenheitswechsel. V52 zeigte vorher Kvle als direktes Ziel; Ursache der ursprünglichen Auswahl nicht direkt protokolliert. | DB: TurnTruth aller fünf Dialogturns zeigt `target_id=char_b97b63012cf47621a91f404d`. |
| 08B | `matrix_api/app.py:_canonical_target` ca. 1277–1288; `kernel_prepare` 1345ff.; `kernel_commit` 1531ff. | SQL prüft Weltzugehörigkeit, nicht direkte Anwesenheit; `targetId` Kvle bleibt gültig, obwohl `scene.presentIds=[Tammy,Tom]`. | Log `KERNEL_BIND` und 5× SQL-TurnTruth; `UI_SEND` und `SQLITE_COMMIT` PASS. |
| 08C | `matrix_api/app.py:_extract_user_plan` ca. 2135; `matrix_api/conjunctive.py:normalize_plan/apply_plan` ca. 176/263; `kernel.py:commit_turn` ca. 2750 | Empfängername Kvle → LLM-Plan „Tom hat Kvle geholfen“, obwohl Nutzer „dir“ an Tammy sagte; daraus `claims` + `frames` als SQL-Sessionzustand. | `scene_facts` mit Plan `source=llm`, `recipient_id=Kvle`, T2–T5. |
| 08D | `matrix_api/app.py:kernel_prepare` ca. 1498–1507, UI `runFigure` ca. 329–338; `truth.py:validate_llm_contradictions` ca. 120–153 / `apply_contradictions` 155ff. | LLM-Vorschlag wird allein durch Tokenüberschneidung mit gesamtem Wissensblob validiert; ist kein semantischer/evidenzgebundener Nachweis. Auf `commit` vertraut man dem UI-Array `contradictions`. | T3+T4: provider source `llm`, Sicherheit `1.0`; lokale Gegenprüfung `0`, Provider-Validator akzeptiert `1`; zwei `contradiction`-SceneFacts. |
| 08E | `kernel.py:build_new_session` ca. 4770–4804; `repos.py:patch_session_goal` ca. 3356–3415; `kernel.py:recall/bind_formulation_spiegel` ca. 5157/5544; `scene_state.py:update_from_commit` ca. 55–122 | Status 1=`active`, 2/3=`pending`; Phasenübergang derzeit erst bei **explizitem** `PATCH goal.status=fulfilled` über Timeline. Freier Text löst keinen abgesicherten automatischen Exit-Commit aus. Neue Frage erzeugt offenen Beat. | `goals` SQL + `sceneState`; T3/T4 answered, T5 wieder open. Keine automatische Phasenfortschreibung belegt. |
| 08F | `characters`-Stamm + `matrix_api/llm_contract.py:render_persona_brief` | Bereits vorhandene elf `learnedItems` (aus alten Sessions) erzeugen teilweise stereotype `typicalPhrases`/Zusatzziele; V52 verhindert nur **neues** automatisches Schreiben. | 11 Einträge bei Tammy; aktueller Log enthält bei dieser Session **keine** `LEARN`-Stufe; `TURN_LINE` jeweils `(llm)`, AutoChat AUS. |

### Konkrete Datenbank-/Logzahlen

- `Verführung und Macht` → anwesend **Tammy und Tom**; Kvle `position=anderswo`. Fünf Dialogturns `target_id=Kvle`, zwei falsche `contradiction`-Facts (T3, T4); `SQLITE_COMMIT=PASS`. AutoChat deaktiviert (kein AutoChat-Endloslauf).
- T3: Tom „Ich war da, neben dir ich hab dir geholfen…“; falsche Gegenbehauptung „Tom ist immer für Kvle da.“; T4: Toms erneute Unterstützungsaussage gegen „Tom hat Kvle geholfen.“. Validator akzeptiert beide falschen LLM-Befunde; lokale Prüfung auf Sessionzustand vor den jeweiligen Turns ergibt jeweils null Treffer.
- T5: Tom schildert, drei Tage an Tammys Bett gesessen zu haben; Tammy erwidert, Worte reichten nicht. Das ist eine **Behauptung über Vergangenheit**, nicht schon unabhängiger Beweis. Aber der Kernel müsste den Bezug korrekt an Tammy binden und die Prüfung der Exit-Bedingung an real committed Ereignisse knüpfen.
- Beziehung Tammy→Tom fällt durch T3/T4 in den jeweiligen Delta-Daten `0,45→0,35→0,25` und steigt durch eine spätere Synapsenwirkung im aktuellen gespeicherten Zustand wieder auf `0,40`. Kein linearer Dauerverlust behauptet.
- Tatsächliche Tabellenzahlen **dieser hochgeladenen ZIP**: 3 Welten, 18 Figuren, 2 Sessions, 12 Turns, 17 SceneFacts, 15 Memories, 11 Goals. Die Zahlen in Abschnitt 4 des ursprünglichen Masterblatts (5/60/124/...) gelten für eine **andere frühere DB-Version**, nicht für die hier untersuchte, nachträglich veränderte ZIP.

### Reparaturpflicht / Abnahme (für spätere **eigene neue Produktversion**, **nicht** als erledigt ankreuzen)

1. **08A/B:** Direkte Adressierung beim Anwesenheitswechsel neu binden; explizite Fernkommunikation/erwähnte Figuren von anwesendem direkten Ziel unterscheiden. Speaker, User-Actor, Ziel, Erwähnung, Wissenszugriff als getrennte Felder; keine figurenspezifische Sonderregel.
2. **08C:** Plan/Commit darf fremde Entitäten nicht aus alter UI-Zielwahl in den Inhalt injizieren. Quelle wörtlich erhalten; unsichere Referenzen als ungeklärt statt als Fakt committen. Historische Fehlfacts nur mit dokumentierten Korrekturen/Widerrufen behandeln, **nicht** still löschen.
3. **08D:** LLM-Output zur Widerspruchsprüfung darf **nicht** direkt Trust/Memory/SceneFacts schreiben. Aus einem eindeutig belegten gegenteiligen Fakt und seinen Beteiligten/Quellen im bestehenden Commit-Owner entscheiden; Testfall Kvle vs Tammy muss 0 Widersprüche erzeugen. Keine Prompt-/Output-Filter-Lösung.
4. **08E:** Exit-Bedingungen als echte Ereignisfolge prüfen: behauptet ≠ getan ≠ bezeugt ≠ von Tammy akzeptiert. Bei belegtem Exit in gleicher Session-Transaktion `goal.status`+Folgeziel aktivieren; freiwillige Ablehnung bleibt Figurenhandlung, nicht Systemvergessen. SceneState/Goals/Relation/Recall getrennt synchron prüfen.
5. **08F:** Alte Lernwerte nur nachvollziehbar/gezielt und mit Benutzerzustimmung bereinigen; neue V52-Turns dürfen keine neue Stamm-Lernschleife erzeugen.
6. **Tests:** Generische Mehrfigurenszene mit Entfernung des ursprünglichen Ziels; fünf Folgeturns ohne Target-Leak; keine falschen Contradiction-Facts oder Trustverluste; echte Goal-Transitions einschließlich Neustart und Session-Isolation; die reale Android-/Provider-Laufzeit getrennt von SQLite-/Syntaxprüfungen abnehmen.

**D02-Teststatus:** ZIP/SQLite gelesen; tatsächliche Werte per SQLite-Read-only geprüft; `truth.local_contradictions` und `truth.validate_llm_contradictions` mit aufgezeichneten T3/T4-Befunden reproduziert (lokal `0`, LLM-Validator `1` je Turn). **Kein Patch, keine live getestete Reparatur.**


---

## V53 - FB08 verifizierte Aenderungen im selben Funktionsplan (26.10.2026)

**Version:** MATRIX10_CHATHERE_V53_TRUTH_COMMIT_20261026
**Basis ZIP SHA256:** c74840c9dee50ae1306b327451032329231936994bcf2ef154d888943a31cdf8
**Produkt-DB SHA256:** 1804abfc4f887f8560f240d9ec678ca06843c6302993ee17d5645c69fd153c27; Original unveraendert. Aeltere korrumpierte SceneFacts bleiben historisch erhalten, werden nicht still umgeschrieben.

### Ein- und Ausgaenge des einen wirksamen Pfades

```text
FB08 / CHAT - EINGANG
  UI: User / Rolle / Avatar / aktuelle Session / gewaehlter Adressat
  SQL: Weltfiguren, Scene.presentIds, vorherige Sprecher, Szene
          |
          v
FB08A - CLIENT- UND SERVER-ZIELBINDUNG
  Chat UI: verliert abwesendes Ziel, keine Fremdfigur auto-spawnen
  Kernel.prepare: _canonical_target -> resolve_target_detail
    explicit_address  !=  mentioned_name
    room_presence     !=  world_membership
  FB08A OUT: canonical TurnTruth.actor, target, present, hears/sees
          |
          v
FB08B - EREIGNISPLAN / COMMIT
  User claim text + TurnTruth -> normalize_plan(source-grounded)
  KI-Plan mit erfundenem Cast-Subjekt oder falschem Empfaenger
    wird NICHT als SceneFact-Plan committed; lokale Lesung nur Claim
  Figurenrede: eigenes Reply-Ziel aus ihrem eigenen Turn bestimmen
  + SceneFact, claims, frames, Memory, Runtime/Relation in SQL
          |
          v
FB08C - WIDERSPRUCH / BEZEUGUNG
  Widerspruch nur mit vorhandener Gegen-Quelle gleicher Proposition
  Kein KI-Vorschlag ohne Quell-Fact -> trust_delta=0
  witnessed speech: gehoert NUR wenn Figur praesent und hoerfaehig
  entfernt adressierter Dritter hat keinen Fact-Wissenszugriff
  SceneState.openBeats/foreground nur praesent; Faktenhistorie bleibt
          |
          v
FB08D - RECALL / FIGURENREAKTION
  speaker-spezifische Facts, Witness, Memory, Goals, Relations,
  Synapsen und Szene aus bestehendem Kernel laden
  Goal phase bleibt ohne nachgewiesenen Exit auch ueber 21 Turns
  LLM formuliert; Antworttext ist kein Autoritaets- oder SQL-Owner
          |
          v
SQL session-commit -> Readback -> FRONTEND
          |
          +-----> naechster Turn nur aus aktuellem SQLite Zustand

FB08 Fehlerpfade:
  Abwesender Speaker -> 409 SPEAKER_NOT_PRESENT/NO_SPEAKER
  falscher KI-Plan -> keine unbelegte Semantik committen
  fehlende Contradiction-Evidenz -> keine Beziehungsstrafe
  keine automatische Goal-Erfuellung durch Turnzahl/Satzanzahl
```

### Konkrete Korrekturen und Abnahme

1. **UI/Adresse** (**Korrektur V65R:** „Name als Thema ist nicht Gesprächspartner“ galt nur für `kernel.pick_speaker`, nicht für den Browser; siehe Deckblatt V65R §0): stale `targetId` invalidiert beim Presence-Wechsel; keine Auswahl aus `focus.addressedId` als Ersatzautoritaet. Ein Name als Thema ("Hast du X gesehen?") ist nicht automatisch Gespraechspartner. Ausdrueckliche Fernanrede bleibt als Ziel notierbar, ohne dem Abwesenden Wissen zuzuschreiben. `kernel.pick_speaker` bindet nur anwesende Weltfiguren.
2. **Prepare:** bisher im API-Response ungebundene Variable `speaker_candidates` war ein eigenstaendiger 400-Risiko-Fehler; jetzt aus kanonischen anwesenden Figuren berechnet und an das bereits vorhandene UI-Feld geliefert. `autoPick` nimmt denselben SQL-Szenenstand.
3. **Commit:** Actor und Reply-Speaker behalten getrennte Akteurs- und Zielbindung. LLM darf keine ungenannten Entitaeten in Fakt/Empfaenger einschleusen. Ein Widerspruch ohne konkrete vorangegangene, gegenteilige belegte Claim-/Frame-Proposition loest keinen neuen `contradiction`-SceneFact und keine Vertrauensaenderung aus.
4. **Witness + Szene:** vorher verlieh `witness_access()` der abwesenden, bloss angesprochenen Figur `affected`-Wissen; nun nicht mehr. Aktueller Szenen-Vordergrund und aktive Beats enthalten nur tatsaechlich anwesende Figuren. Gespraechs- und Fact-Historie bleibt unberuehrt.
5. **Phasen:** **kein** festes Turnlimit/Schluesselsatz-Exit eingefuehrt. Ein 21-Turn-Test gegen die echte TAMMY-SQL-Fixtur bestaetigt: neue Fakten gelangen in Recall, Phase-Status bleibt stabil. **Semantische Goal-Exit-Erkennung und menschlich plausible neue Handlungen in langen echten LLM-Verlaeufen bleiben OFFEN**. Die aktuelle Version darf nicht als vollstaendige Loesung der gesamten Figurenentwicklung bezeichnet werden.
6. **Isolation:** Alle Tests lesen Original-SQLite nur per `mode=ro`; der Kernel arbeitet auf einer In-Memory-Kopie. Keine stillen Reparaturen alter Figurenbehauptungen und keine Veraenderung an `data/matrix10.sqlite`.

**Statisch:** 9 Kernel-/Witness-/Tammy-Regressionen PASS; compileall PASS; 41 JS/MJS-Dateien `node --check` PASS; 67 interne Asset-Verweise verifiziert; Original-SQLite-Hash gleich.
**Live:** Flask-/React-Interaktion, Android und echte LLM-Turns NICHT hier getestet. Ein Full-TypeScript-Build wurde wegen fehlender npm-Abhaengigkeiten nicht ausgefuehrt; produktive JS-Chunks gezielt nachgefuehrt. Keine gruene Live-Abnahme behauptet.

### Versionsregister (SHA256 der geaenderten Dateien)

| Pfad | FB / Funktion | SHA256 |
|---|---|---|
| `matrix_api/kernel.py` | FB08 speech/addressee binding, response target, scene participants, actual witnessing, grounded claim+runtime commits; no remote listener or reciprocal first-contact | `d9bb3d202469f27be5bc5d681a50d847c765f413031ea0cf497a2d76744b168b` |
| `matrix_api/app.py` | FB08 SQL-present canonical target; same decision on prepare/commit; speakerCandidates defined; autoPick from present | `061439adf568eb3582bc446b780de52f6c5075fa8f6a0171b1e0a76e5bd97071` |
| `matrix_api/conjunctive.py` | FB08 actor and receiver bound to source, reject invented third-party plan statements | `ebb4bf24cdabe419fe79088ac2fa30aa9e8d00bca5eabe60b4880d8e4b584e4c` |
| `matrix_api/truth.py` | FB08 contradiction requires identical grounded predicate/subject/proposition/negation + prior evidence; no provider-only trust drift | `080bec99605934c9cf34eedf2443217bba31799578707bb6072762f1688b536e` |
| `matrix_api/scene_state.py` | FB08 only present figures may own room beats; retains committed history | `e526ccfbde3db90696e90e2ace217326139215a6773d41d9a444b74b8e5073db` |
| `src/routes/chat.$sessionId.tsx` | FB08 stale UI target removed, implicit off-scene speaker spawn removed; present-speaker chooser | `817fe3b73cf087e5da2e7900036b9a1ec2886dfd368a2fe65f06d689cf20477c` |
| `src/lib/matrix/kernel-bridge.ts` | FB08 no retained focus as canonical target on prepare/commit | `ced9caa8423499b81333bac885e3f0d48c0587439ba37167b7468597c53923d6` |
| `src/lib/matrix/types.ts` | FB07 V53 build identity | `d279d067909917aba93d1246952fed4f47d93484f22c358425d8b163e745c12c` |
| `matrix_api/tests/test_v53_turntruth_core.py` | FB08 real V52 Tammy read-only SQLite fixture; wrong target, contradictory AI, remote witness, 21-turn phase | `2d2befbab2198d0625785fc79d8881c1e6df9bdbb9d795b972832b96a5a8a09b` |
| `START.py` | FB07 V53 process marker and build version | `aa73db8c77a6fdcf65a89f05ccca17a7e135c45a8b13b6d544eaed4ff323b68d` |
| `VERSION.txt` | FB07 build machine identity | `2cc237c0f16f0c76378039e5db5bffd8ecc5083a6042b8f6c39f7fe47f00d19a` |
| `README.md` | FB07 operational boundaries | `b372fa6b6f2bf4625b5f95c94adc1b2d72026177a0dd668bde35451d968be66d` |
| `frontend_dist/.build-info.json` | FB07 static bundle provenance + 42 asset graph | `de4a04d1ee09fed868e8cf9c45f452b9477239c9ce1cd852ccbcc6741a5fb75b` |
| `frontend_dist/index.html` | FB07 V53 static asset refs | `b166f48d67a9670633af136dde5bfa481b252e862edeca696706e5fe861961ec` |
| `frontend_dist/assets/index-5-VzmJtc-V53T.js` | FB08 delivered mobile chat parity of TS source | `7218a908727873e7941bff72f90eabf40d4de3c15e74985786100fcbe419937c` |

**Alle versionierten Frontend-Assets (42 SHA256):**

- `frontend_dist/assets/admin-DZOQfYB5-V53T.js` `8bfe0814c0678fa908e59552531b8f45d52c8650ed666c9895fac65f41404b05`
- `frontend_dist/assets/api-ClGRQEGP-V53T.js` `7fc3df214db528323d0f1effc973af18770b4e414ff5fa3978f002803be23681`
- `frontend_dist/assets/char._charId-DJ7LAi8J-V53T.js` `b0d4a42c1fc0b25b0d80c4a10c90c24b20df6f1683c5e9a8c81897a4b063c63d`
- `frontend_dist/assets/charakter-BkYmqNt_-V53T.js` `44182ee7f9d87b781ff512d536bb58862005432c94cae01e1231f2819bad1ac9`
- `frontend_dist/assets/charakter._charId-Uak7xfF8-V53T.js` `8139622a745f0fc2556096f8a0625540dfcc8f0dea11838e9e6774418f7e4c18`
- `frontend_dist/assets/charakter.index-BZymjt0P-V53T.js` `d2dbca2ff0eafd75f44f1d38b2613f7d6aac97ef9b0275c0ab82795ccc55f9d8`
- `frontend_dist/assets/chat-BkYmqNt_-V53T.js` `44182ee7f9d87b781ff512d536bb58862005432c94cae01e1231f2819bad1ac9`
- `frontend_dist/assets/chat.index-DJMd_us4-V53T.js` `5af3cabb39fcfcc2a143f07e66ae9296b4deff57a19e61a4a3583a417f38ca0a`
- `frontend_dist/assets/config-BsCCj1Hx-V53T.js` `6941728a60bc560426cf03033cdbbc0317b6cdc774350a81c5e700d62aebc7dc`
- `frontend_dist/assets/diagnose-CgjI3Cg1-V53T.js` `f5638e3a4f2c53147643a5effb15de721e57dc59e7e0b5c0a852f69b162305bb`
- `frontend_dist/assets/event-engine-l0hs20f6-V53T.js` `c9a5b22fab251ac2819f0d64379a6cf7984ab3f2082ec886297280bf4f704c87`
- `frontend_dist/assets/fate-BrcVsLmB-V53T.js` `911366d4ce6685e8790505e9ca4802fce1718096e8fc6d5efa56622a963c5aaa`
- `frontend_dist/assets/index-5-VzmJtc-V53T.js` `7218a908727873e7941bff72f90eabf40d4de3c15e74985786100fcbe419937c`
- `frontend_dist/assets/jszip.min-DIgHJL1D-V53T.js` `80c66a1a80886f55a7986c09125ff21448b5cc7ee665960170af5f16dd366b91`
- `frontend_dist/assets/labor-C3TD2Y6f-V53T.js` `f0b6e6d488a2baa96a1dc4293bd760f4acd0a8eb147447e0605ea3ca9b99d507`
- `frontend_dist/assets/lazyRouteComponent-CFjILrxq-V53T.js` `63f55ac1d0b98e66f0b324efa503f4c77e245f606d16ce777e2b534578e40409`
- `frontend_dist/assets/logs-BEiOiYad-V53T.js` `b95e9796df4ee39c18a2480d88547d4cb848e3b26989cf1fae38a19c9d4ca817`
- `frontend_dist/assets/memory-efcY2umJ-V53T.js` `6598339ab6e4de12f430c12eaec00f28a88ca8369490bfb8002263314d918607`
- `frontend_dist/assets/pdf-CxLxk-yn-V53T.js` `3fd9b3154d3cec700e10376cdc7cfb21b48772a030dcef709e49fca87d4e6a4d`
- `frontend_dist/assets/pdf-DV2XDCc3-V53T.js` `e29d74e4973ce41758f050bfc0dbc03adc80c7ae9a918d382e0c66e1c06ee46f`
- `frontend_dist/assets/pdf.worker.min-Dswkl-cV-V53T.mjs` `8ab0e5e30031b4a06ecfddd5ae9562f0227f830ee7ec9ed1a968b134243d2386`
- `frontend_dist/assets/play._sessionId-DJ7LAi8J-V53T.js` `b0d4a42c1fc0b25b0d80c4a10c90c24b20df6f1683c5e9a8c81897a4b063c63d`
- `frontend_dist/assets/preload-helper-Czpn1I53-V53T.js` `aba87f2a53e45ecdc9113fc30387d16e449d1676428cf5f82dd624c1df97d152`
- `frontend_dist/assets/review-D-Kr9F9b-V53T.js` `10b0ecc2086600da6e0e1b28c0313369ad5f5847d7bfe72a775b28d86a09ba60`
- `frontend_dist/assets/rolldown-runtime-C0FnF6B9-V53T.js` `e0a79ad36c6ca1ffbc796c80aa5661803a9d1bc684e29d1587f48b4ba9a82714`
- `frontend_dist/assets/root-DLTE-HSj-V53T.js` `2eb1d17f334d79f5c2b7c68aa45a2b50b46a7b2416a9a0f5e7de6ff7f2430322`
- `frontend_dist/assets/routes-aKifRtrJ-V53T.js` `8a7eb8cd7f8c354777e8bdad7b1620f612e0a661a1445bdeba443027638875b9`
- `frontend_dist/assets/shell-gwW-WKpO-V53T.js` `7954894780ca67ff34fbc33996c24bf23ce90373995e50f9c1b4a919847bdbfc`
- `frontend_dist/assets/social-BYPMAzYs-V53T.js` `2ea264ea4b573727bdca84d1ee917c1a514b7722ae3ec78109c86fbdf2b384a8`
- `frontend_dist/assets/src-SuYvKHvm-V53T.js` `dd4d98379284e1bd73fa7750e626ab21fd0a024f6701af58a585d00d02e596f0`
- `frontend_dist/assets/styles-C84qSt0H-V53T.css` `fb01d6dc542ac29e73e239fa4ea6cb2ce7475bbaee68560bb26ac26f4ec8e34b`
- `frontend_dist/assets/timeline-CmyrKt7S-V53T.js` `cea472b39719f2c94c9bf7781259afb979fa089b9a26e3274b4247aa050ab2bf`
- `frontend_dist/assets/triggers-bPtCLXRS-V53T.js` `17b84e9ab9b90f3d9de3750c70958fe3d3e6751a99f3c91241d6cdce7f7fabae`
- `frontend_dist/assets/upload-PkoedRAR-V53T.js` `4fd062fd3b91a29824c65719caef2a6a71f449837ee8ddbdf35f18f167c8f0e4`
- `frontend_dist/assets/use-selectable-Dumw7S2R-V53T.js` `d824d5c76a7f704739f9fba5e27057c12cc08e28ce3f3e2e6417fa76e7f202d3`
- `frontend_dist/assets/useNavigate-DMQQ6XHo-V53T.js` `6f3f0f89d717c081e1be48b2596d7fa4c052f2bed47d9ba6c1b1d5eda1ac5d66`
- `frontend_dist/assets/useStore-Pi3dVb-t-V53T.js` `c24f97ea5d69fa5cc436c68b030772c24995d29fdffaba3357285a87a8446003`
- `frontend_dist/assets/user-BrfbdArt-V53T.js` `7aa5f1129b8b5a896229a36fc3f3449d25819b346331e938362701b6d629e661`
- `frontend_dist/assets/welt-BkYmqNt_-V53T.js` `44182ee7f9d87b781ff512d536bb58862005432c94cae01e1231f2819bad1ac9`
- `frontend_dist/assets/welt._worldId-CUNII7hy-V53T.js` `97e349bd174d699e57e9a29753ad37150c4ecab12f3308ee1429a38227ed371a`
- `frontend_dist/assets/welt.index-CsM5VIc--V53T.js` `9ccdb5d294129f6d51efc6d3b017eb4a97f2ab7cdec2ef35fcf409d187ba5c7a`
- `frontend_dist/assets/world._worldId-DJ7LAi8J-V53T.js` `b0d4a42c1fc0b25b0d80c4a10c90c24b20df6f1683c5e9a8c81897a4b063c63d`

**Lieferung:** ein ZIP, diese eine Masterdatei im Projekt, keine weiteren Patchberichte.


### FB01/FB03/FB04 - SQL-Schreiber-Abnahme auf unveraenderter Benutzer-DB (V53)

```text
IN: Original data/matrix10.sqlite (nur lesen), Besitzer/Charakter/Session/Goals
  -> Kopie im temporaeren Verzeichnis
  -> repos.delete_character / patch_character / patch_session_goal
OUT: kanonischer Session-/Figuren-Readback; persistenter SQLite-Commit
  -> Eigentuer-Isolation 403; Fremdsitzung 409; vorhandene Bindungen entfernt
  -> 7 historische SQL-Kindtabellen unveraendert
  -> 11 alte gelernte Eintraege nur nach ausdruecklichem PATCH entfernt
  -> vorhandene Goal-Phase 1 fulfilled, Phase 2 active, Phase 3 pending
  -> 2 historisierte Zieluebergangs-SceneFacts
  -> Original-SQLite vor/nach Test SHA-256 identisch
```

Test: `python scripts/test_v53_sps.py` — 5 Einzel-Pruefschritte PASS.
Der Test verwendet eine Datenbankkopie und keine produktiven Aenderungen.
Kein automatischer Phasenwechsel durch Zeit oder einzelne Schluesselwoerter.

| Pfad | FB / Funktion | SHA256 |
|---|---|---|
| `scripts/test_v53_sps.py` | FB01/FB03/FB04 Live-SQL-Writer auf DB-Kopie, DB-Isolation | `dd0a3e98ad6131207370fd1ecb5881ce6dd23352d3806bdfadd4359c7d83e8fa` |

**Gesamtpruefung:** 9 Kernel-/Witness-/TurnTruth-Tests PASS; SQL-Writer-Skript 5 PASS; alle gelieferten JavaScript-/MJS-Dateien Syntax PASS; 67 Asset-Pfade existieren; originale SQLite-Datei unveraendert. Eine Android-/LLM-Liveabnahme liegt weiterhin NICHT vor.

## FB08G – V53 Ursachenprüfung am ORIGINALDATENFLUSS (26.10.2026, 08:47-Session)

**Quelle:** ursprüngliche `Matrix10.txt` Abschnitte 10–20 + `VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt` §§1–4. **Projektbasis:** `MATRIX10_V53_TRUTH_COMMIT_20261026.zip`, SHA256 `b4619248c6b0f0ab575cfabc1fa89c377e9cac34d9a4d9657f8aad1bb5d994f6`. **Prüfquelle:** `Verführung_und_Macht_·_08_47.session.json`, SHA256 `114b701efef29902ad25b26e63bbf427dbbc32f26da628028bfee98ff90cab7e`. Quelle aus echter Benutzersitzung; Gegenproben auf Kopien, kein User-Store verändert. Keine neue Produktversion.

```text
SPS-KETTE (ERFORDERLICH)                         V53 IST: ERSTER SCHLECHTER ÜBERGANG
IN  UI/TurnTruth (Tom an Tammy)                   -> Korrekte ID-Bindung in dieser Session [TEILGESCHLOSSEN]
    -> Originalrede / Quelle / Authority         -> Speech-Fact geschrieben [NACHGEWIESEN]
    -> strukturierte Interpretation GEPRÜFT      -> LLM-Plan fachlich ungesichert, trotzdem "validated" [ROT]
    -> WitnessKnowledge je berechtigter Figur    -> Gehörtes gespeichert [NACHGEWIESEN]
    -> personenabhängige Bedeutung des Erlebten  -> nur ausgelöste Compass-Trigger; hier 0 [ROT]
    -> Runtime/Relation/Synapse/Goal-Verlauf     -> bei drei Eingaben keine relevanten Folgen [ROT]
    -> Commit/SQLite/SessionState                -> Fakten gespeichert, Goal 1 weiter active [TEILGESCHLOSSEN]
    -> Recall relevanter Ereignisse UND Wirkung  -> Fakten lesbar; kein wirksamer neuer Verlauf [ROT]
    -> BrainContext als Spiegel                  -> Zieltext/alter Intent; Exit-Bedingung nicht als Steuerung [ROT]
OUT -> charaktereigene nächste Handlung         -> aus unverändertem Zustand nicht kausal begründet [ROT]
    -> nächster Turn                              -> Wiederholung in tatsächlicher 3-Turn-Session [ROT]
```

**Nachgemessene Verbindungen (kein grep-Alleinbeweis):**

| FB | Quelle / Funktion | Eingang -> tatsächlich gemessener Ausgang | STATUS |
|---|---|---|---|
| FB08G.1 | `matrix_api/kernel.py:fire_compass_lens` (ab ~5370), `apply_knowledge_effect` (ab ~1508), auf realem Tammy-Stamm + beiden anwesenden Figuren | Für `Hey süsse`, `Ich war neben dir`, `Ich haben dir gessen und deime hand gehalten` jeweils `fired=[]`, `runtimeDelta={}`, `relationDelta=[]`, `goal=None`. Lexikalische Trigger wurden NICHT aktiviert; daraus kann keine kausale Figurentransformation entstehen. | ROT |
| FB08G.2 | `matrix_api/conjunctive.py:normalize_plan` (~190), `apply_plan` (~284), auf Kopie der realen Session | Für die Originalrede `Ich haben dir gessen und deime hand gehalten` und eine LLM-Proposition `Tom ... Tammy gegessen ...` liefert normalize `source=llm, validation_status=validated`; `apply_plan` legt daraus einen `status=current`-Frame mit dem falschen Gehalt an. Textliche Auslegung wird damit ohne belegte semantische Äquivalenz aufgewertet. | ROT |
| FB08G.3 | `matrix_api/kernel.py:recall` (~5196), `bind_formulation_spiegel` (~5570), `llm_contract.py:render_persona_brief` (~473) | Der Spiegel sieht `goals=['Tom testen, ob er wirklich bleibt, wenn es schwer wird.']`, Runtime-Intent `wissen, wo du warst...`, `fired=[]`, typische Wendungen aus altem Stamm. Die Exit-Bedingung liegt zwar in den Goal-Daten, wird nicht gegen neue Evidence vom Commit bewertet. | ROT |
| FB08G.4 | `matrix_api/scene_state.py:update_from_commit` (~55) | Ein offener Beat wird bereits dann `answered`, wenn die adressierte Figur eine Rede absetzt; das ist keine quellengeprüfte Beantwortung oder Erfüllung der Sache. Vorhandene Beat-Lifecycle ist nicht gleich Goal-Fortschritt. | ROT |
| FB08G.5 | `matrix_api/llm_contract.py:render_persona_brief` (~494) | Von sechs Regeln im Stamm werden `reactionRules` in der Ausgabe auf vier begrenzt; alte `typicalPhrases` werden in prominentem Kontext weiter transportiert. Das ist sekundäre Verstärkung, nicht der Ursprung der fehlenden Zustandswirkung. | ROT |
| FB08G.6 | `matrix_api/kernel.py:commit_turn` (~2197), `fire_from_proposals` (~1770), `apply_synapses` (~1838) | Ein vorhandener Weg für semantische LLM-Synapsenvorschläge wird über `fired_all=merge_fired(...)` angebunden. Das ist **kein vollständig fehlender Anschluss**; im realen Export sind `synapses=[]`. Auch Vorschläge sind keine Wahrheit und können fehlende Grounding-/Goal-Writer nicht ersetzen. | TEILGESCHLOSSEN |

**Abnahmegrenze:** Die vorhandenen sieben V53-Kerneltests bestehen (`pytest -q matrix_api/tests/test_v53_turntruth_core.py`: 7 passed), testen aber diese gesamte individuelle Lern-/Wirk-/Goal-/Folgeturn-Kette nicht. Kein Android-/LLM-Live-PASS. Keine Codekorrektur vorgenommen, keine V54 ausgeliefert; unveränderte Source-Hashes für `kernel.py`: `d9bb3d202469f27be5bc5d681a50d847c765f413031ea0cf497a2d76744b168b`, `conjunctive.py`: `ebb4bf24cdabe419fe79088ac2fa30aa9e8d00bca5eabe60b4880d8e4b584e4c`, `llm_contract.py`: `58ea42ff76498f7cd8c069e916368823e51929a6e7eadded31011cb28274111c`.

**Bindende Korrekturklasse (noch NICHT IMPLEMENTIERT):** Die bestehende Turn-/SceneFact-Commit-Schicht muss nach überprüfter Interpretation jedes relevanten Ereignisses die Figurenerfahrung als belegbare Wissens-/Zustandsfolge bewerten, bestehende Session-Goals mitsamt ihren offenen Bedingungen fortschreiben, Runtime/Relationship/Synapsen mit Ursache schreiben und diese Wirkung **vor** dem Folgeturn vollständig readbacken. Keine Figurennamen-, Wort-, Turnzahl- oder Prompt-Sonderregel; keine zweite Datenhaltung; keine Ausgabe eines Produkts als grün, solange diese Kette nicht geschlossen ist.


---
## V54 · FB08H – EINE KORREKTUR: Ereigniswirkung VOR Figurennachfolge

**Ursprünglicher Fehler:** Der Chat-Ablauf formte zuerst eine Antwort (`/api/kernel/prepare` war read-only); erst `/api/kernel/commit` schrieb Nutzerrede, SceneFacts und Wissensfolgen. Der antwortende Charakter konnte im selben Turn nicht auf die neu committed Erfahrung reagieren. Eine lexikalisch nicht getriggerte Erfahrung hatte außerdem keinen strukturierten offenen Zielbezug.

### SPS-Funktionsweg und Datenbesitzer

```text
IN   Bedienperson spricht / handelt: session_id + TurnTruth + Actor + Target + Witness
 |   Frontend: src/lib/matrix/kernel-bridge.ts:kernelPrepare (V53 unverändert)
 v
FB08H.1  POST /api/kernel/prepare [app.py:kernel_prepare]
 |    -> canonical SQL: Session + Anwesenheit + Zielsprecher + Target
 |    -> BEGIN IMMEDIATE -> kernel.commit_turn(phase="input")
 |    -> SceneFact [claims vs actions unterscheiden]
 |    -> WitnessKnowledge [nur anwesende, wirkliche Zeugen]
 |    -> Memory / Runtime / Relationship [vorhandene Writer]
 |    -> goal.recentExperiences [nur offen/aktiv + direkt an owner gerichtet]
 |    -> runtime.attentionFactId + attentionEpistemic
 |    -> repos.save_session -> SQLite-COMMIT -> lock frei
 v
FB08H.2  kernel.prepare_turn (NACH dem SQL-Commit)
 |    -> brain_context / recall aus committed Fakten
 |    -> spiegel.goals: string[] (Frontendvertrag unverändert)
 |    -> spiegel.goalEvidence: [sourceFactId, claimed/observed, turn]
 v
FB08H.3  LLM formuliert aus aktualisiertem Zustand
 |    Keine LLM-Wahrheit, keine Output-Reparatur, keine zweite Faktenquelle
 v
FB08H.4  POST /api/kernel/commit [app.py:kernel_commit]
 |    -> kernel.commit_turn(phase="response", SELBE TurnTruth-ID)
 |    -> ausschliesslich Figuren-SceneFact + Folgen schreiben
 |    -> pendingInputTurnId löschen; SQLite-COMMIT
 v
OUT  Frontend-Readback → Sprecherantwort + Sessionzustand;
     TurnIndex genau +1; User-Fact genau 1x; NPC-Fact genau 1x

FEHLER / GRENZEN
 - zweite Eingabe vor Figurenantwort: 409 INPUT_PENDING / STALE_SESSION
 - falsche session, Sprecher- oder TurnTruth-ID: Commit abgewiesen
 - falsche oder abwesende Zeugen: keine fremde Ziel-/Wissenswirkung
 - eine gehört behauptete Hilfe ist keine bewiesene Handlung / kein Goal-Exit
 - 23 Turns im selben Ziel: Phase bleibt aktiv, Erfahrungen ändern sich
 - Flask/Android/Provider-Live nicht verifiziert; keine Behauptung „LLM wiederholt nie“
```

### Geänderte Code-Stellen (mit Ein-/Ausgang)

| Datei / Funktion | Eingang → Tätigkeit → kanonischer Ausgang |
|---|---|
| `matrix_api/app.py:kernel_prepare` | Validierte TurnTruth → kurzer früher Input-SQL-Commit → anschließend ungesperrter BrainContext-/Provider-Read |
| `matrix_api/kernel.py:commit_turn` | `phase=input/response` → einen Turn auf zwei zeitlich richtige Schreibabschnitte verteilen; keine Doppelanlage |
| `matrix_api/kernel.py:apply_goal_experience` | direkt gerichteter, wahrnehmbarer Fact → vorhandenes offenes Goal mit Fact-ID/epistemischer Quelle + Runtime-Attention aktualisieren; keine Phase automatisch beenden |
| `matrix_api/kernel.py:apply_knowledge_effect` | Witness einer jetzt gehörten Aussage → bestehende Compass-/Runtime-/Beziehungswirkung mit tatsächlichem Gesprächspartner aus Actor-ID; Vergangenheitsberichte bewirken keine rückwirkende Tat |
| `matrix_api/kernel.py:bind_formulation_spiegel` | neuer Goal- und Runtimezustand → read-only `goalEvidence`, weiterhin `goals: string[]` |
| `matrix_api/llm_contract.py:render_persona_brief` | read-only Evidence und alle vorhandenen Reaktionsregeln → Formulierungsspiegel, kein Write/Filter |
| `matrix_api/repos.py:CANONICAL_ENVELOPE_FIELDS` | `pendingInputTurnId` → vorhandener SQL-Session-Owner; kein neues Schema/Store |
| `matrix_api/tests/test_v54_event_first.py` | Original-Datenbank als read-only Fixture → Commit, Recall, zwei Phasen, 23 Turns und tatsächlichen Renderer testen |
| `VERSION.txt`, `README.md` | Versionszuordnung, Einschränkungen, Bedienhinweise |

### Tests / Testwahrheit

- **GRÜN:** 16/16 gezielte Kernel-, Wahrheits-, Anwesenheits- und isolierte Original-Renderer-Tests (keine Modellantwort simuliert als Abnahme); Python-Syntaxprüfung grün.
- **GRÜN:** neue Sitzung mit 4 variierenden Eingaben sowie Mehrturn-Regression 23 aufeinanderfolgende Turns; Session-Fact-Wissen beim Folgeturn vorhanden; keine künstliche Zielphasen-Erfüllung; Abwesende erhalten kein fremdes Wissen.
- **ROT / OFFEN:** Flask-HTTP → SQLite-Readback und realer Android-/LLM-Folgeturn sind in der Prüf-Laufzeit nicht ausführbar (Flask nicht installiert; keine Paket-Netzverbindung). Deshalb **keine Live-Abnahme** und keine Garantie über die erzählte Qualität.
- **Datensicherheit:** mitgelieferte `data/matrix10.sqlite` blieb bytegenau wie V53 (SHA-256 siehe unten); bestehende Sitzungen wurden nicht rückwirkend verändert.

### SHA-256 / Versionsverfolgung

- Vorgänger V53 ZIP: `b4619248c6b0f0ab575cfabc1fa89c377e9cac34d9a4d9657f8aad1bb5d994f6`
- SQLite V53 und V54: `1804abfc4f887f8560f240d9ec678ca06843c6302993ee17d5645c69fd153c27`
- `matrix_api/app.py`: `3c8925fc3b7035692920212f8739027b6a722fc1dce4bd63fb91fe5b30cf7e9e`
- `matrix_api/kernel.py`: `280208f5153cd419319b7e54da4492efe42c203a8c19df10a0fbb83e83a1e917`
- `matrix_api/repos.py`: `c196afe2c25b2955691147765d616716195e990d8276ff70fed6dc3f833c0e54`
- `matrix_api/llm_contract.py`: `f67c67366f13a3ee7de5e3ea926f2eeae343e7e00dcd0ca3d9cf0078b7fd2ca1`
- `matrix_api/tests/test_v54_event_first.py`: `dae1cc90e46c68dc0abc489c0936a1d15a1b0c055290bb6d2e56d16fcd839c57`

**Keine anderen Funktionen repariert.** Neue Testbefunde werden hier weitergeführt; nicht in weiteren Berichtstapeln.

---
## V55 · FB08I – Fortlaufende Absichten und Bitten statt Rückkopplungsschleife

**Auslöser / Beleg:** Neuer Nutzerexport `Verführung und Macht · 13:13`, Session `ses_5b2a0a3d80daf33553959f17` (26.10.2026, vier Turns). Der echte V54-Sessionexport enthält trotz bereits wirkender Zustände zwei identische `kind=intent`-Ziele „Bindung (wegen Tom)“; Tammys Vertrauen Tom gegenüber steigt im Verlauf von 0,30 auf 0,75, ihre Rede verlangt aber weiterhin denselben unbestimmten Beweis. Frame aus Bitte im Turn 3 wird in Turn 4 `accepted`; direkt danach entsteht aus einer weiteren generischen Bitte ein zweiter `requested`-Frame. Das ist der konkret geprüfte Rückkopplungsweg; **kein Nachweis eines geheimen spezifischen Tammy-If-Statements**. Das als `exit` hinterlegte Beweis-Kriterium ist echte Charakter-/Zieldatenstruktur, keine zur Laufzeit ausgewertete universelle Sperrfunktion.

### Ein zusammenhängender SPS-Datenpfad

```text
IN     neue User-Äußerung / NPC-Äußerung; actorId, targetId, SessionId
       committed speech Fact + WitnessKnowledge + Scene/Presence
           |
FB08I.1 matrix_api/kernel.py :: apply_knowledge_effect
       INPUT: fact_id + Figur + aktivierte Kompass-Bedeutung + tatsächliches Gegenüber
       LESEN: offene/aktive Session-goals (SQLite-Session-Owner)
       VERGLEICHEN: ownerId + space + counterpartId (Altbestand: Textidentität)
       SCHREIBEN:
          - neu => intent mit startendem sourceFactId
          - vorhanden => gleicher goal.id, weitere reinforcementFactIds,
                          lastReinforcedTurn; keine erneute identische Zielanlage
       AUSGABE: derselbe persistente Zielzustand; eigene Quelle je Folgeereignis
           |
FB08I.2 matrix_api/conjunctive.py :: apply_plan
       INPUT: geerdeter plan (request / acceptance + Beteiligte + source Fact)
       LESEN: Session-frames, Status, identifizierbare Sache/Prädikat/Referent
       SCHREIBEN:
          - gleich identifizierbarer Vorgang => history/sourceFactIds fortschreiben
          - allgemeine weitere Bitte nach akzeptierter offenen Bitte =>
            sequenzielle Folgeäußerung im Vorgang (clarifications),
            ursprüngliche Zusage bleibt unverändert, keine fiktive Erfüllung
          - eindeutig anderer Gegenstand, anderes Gegenüber oder explizit
            anderer Referent => separater Frame; keine globalen Textsonderfälle
       AUSGABE: frameChange {updated, continuation} oder {created}
           |
FB08I.3 matrix_api/kernel.py :: response-Commit
       INPUT: verifiziertes `frameChange` aus Frame-Writer
       AUSGABE: weitergereichte Frame-ID an bestehenden SceneState-Writer
           |
FB08I.4 matrix_api/scene_state.py :: update_from_commit
       INPUT: frameChange.continuation + Frame-ID + Sprecher/Ziel
       SCHREIBEN: vorhandenen Beat fortführen / reopen mit Quelle,
                  kein unabhängiger identischer Szene-Beat
       AUSGABE: `continuedBeat` statt `openBeat`-Neuanlage
           |
FB08I.5 matrix_api/conjunctive.py :: render_frames
          matrix_api/kernel.py :: bind_formulation_spiegel
       LESEN: persistierte Frames und Goals (kein Shadow-System)
       SPIEGEL: letzte Folgeäußerung am Vorgang + relevante aktive Zielbelege
       OUT: bestehender Persona-/Recall-Vertrag; LLM formuliert ausschließlich
            aus bereitgestelltem Zustand. Frontend/API unverändert.
```

### Welche Dateien und Tests geändert wurden

| Datei | Änderung / Zweck | Datenbesitzer |
|---|---|---|
| `matrix_api/kernel.py` | bereits vorhandenes `intent`-Goal wiederverwenden, Faktverstärkungen referenzieren; `frameChange` aus Figuren-Commit in vorhandenen SceneState-Writer tragen; Reader projiziert aktive Phasenevidenz nicht mehrfach | Session-goals, Runtime, Fact, Frame-Readback |
| `matrix_api/conjunctive.py` | Mehrfachanforderungen als Vorgangsverlauf mit eigener Herkunft; Gegenstands- und Referenzprüfung, kein automatisches `fulfilled`; Reader zeigt letzte Präzisierung | Session-frames |
| `matrix_api/scene_state.py` | `frameId` am offenen Beat, Folgeäußerung aktualisiert denselben Beat | Session-sceneState |
| `matrix_api/tests/test_v55_continuity.py` | reine Kernel-/Frame-/Scene-/SQL-Regressionsprüfungen, inklusive Gegenprobe für andere Empfänger/Gegenstände/Referenten | Test, keine Runtime-Daten |
| `matrix_api/tests/fixture_v55_replay.json` | nur minimal erforderliche 4 Turn-Inhalte aus dem Export; keine Abhängigkeit von externen `/mnt/data`-Dateien | Testfixture |
| `VERSION.txt`, `README.md` | Version V55 und Bedien-/Abnahmegrenzen | Paket-Metadaten |

### Messstand / Grenzen

- **GRÜN statisch:** 26/26 gezielte Tests; Python-Syntaxprüfung ohne Fehler; ZIP-Integrität separat geprüft.
- **GRÜN isoliert:** V54-Quellinhalt von vier echten Gesprächsturns gegen unveränderte Ausgangsfiguren durch `commit_turn(input)` / `prepare_turn` / `commit_turn(response)` erneut verarbeitet. Genau **ein** fortgesetztes Kompass-Intent statt mehrfacher identischer Ziele; alte Quellfacts bleiben historisch zugeordnet; Szene hält den Frame-Bezug; keine Phasen-Abkürzung. Ein allgemeines offenes Anliegen kann mehrfach präzisiert werden, ohne eine Erfüllung zu fingieren.
- **GRÜN SQL-Datenformat:** neue Datenfelder überleben `INSERT`/`COMMIT`/Neuverbindung mit einer **Kopie** der mitgelieferten `matrix10.sqlite`. Keine Änderung an Original-DB.
- **OFFEN:** Echte Flask-HTTP-/Android-Provider-Liveabnahme fehlt in der Testumgebung (`flask`-Import nicht vorhanden). Die vier Gesprächsrunden verwenden **gespeicherte** LLM-Ausgaben als Testfixture, nicht neue Provider-Antworten. Somit ist nicht nachgewiesen, dass Tammy live nicht mehr dieselben Sätze spricht.
- **OFFEN / semantische Mehrdeutigkeit:** Zwei generische Bitten ohne erkennbaren Gegenstand können selbst bei denselben Beteiligten in Wirklichkeit unabhängig sein. V55 dokumentiert die sequenzielle Folgeäußerung und erhält ihre rohe Fact-Quelle; eine zuverlässige semantische Beurteilung ist damit **nicht** bewiesen. Eine frei formulierte `goal.exit`-Bedingung ist weiterhin kein automatisch ausgewerteter SceneFact-Prädikatsausdruck. Das ist **nicht** als geheilter Phasenabschluss zu behaupten.
- **NICHT GEÄNDERT:** Character-Templates, ursprüngliche `typicalPhrases`, automatische Bewertung semantischer Ziel-Exit-Bedingungen, LLM-Antworttext, Prompt-Guards/Filter, Frontend-Verhalten, API-Endpunkte und persistente SQLite-Originaldaten.

### Versioniertes Prüfsiegel / Hashes

- Eingangs-ZIP V54 SHA-256: `6303428cb55356f707c37faeaa79d8ac22dcc88a8e6ab23dd453a63d56e81b1f`.
- Original-SQLite V54 == V55 SHA-256: `1804abfc4f887f8560f240d9ec678ca06843c6302993ee17d5645c69fd153c27`.
- `matrix_api/kernel.py`: `efcd7808952ee6d3b1d27ec2360bcb1c8345feb702f028bf86bc8b6591920681`.
- `matrix_api/conjunctive.py`: `bf2307bd783ba3345790463b25ec10ba4a5db0ac3f48badf9f76a6444b2d82ee`.
- `matrix_api/scene_state.py`: `654f3ec2d025e127d8f487d155b1ccc10233bdc15c9f5011a364f377c0a12ad9`.
- `matrix_api/tests/fixture_v55_replay.json`: `c264e8aacbb2196d511fb841537247a0f4d0e34dc4d0648321ecfd4d38dbd0e0`.
- `matrix_api/tests/test_v55_continuity.py`: `a345905ceeffa66049a184d4490f25e8a67e75df2df0b47ee512c2dd3456ac3d`.

**Abnahmestatus V55:** Zustands- und Vorgangs-Rückkopplung **lokal grün**, lebensechte Dialogwiederholung **live offen**. Das ist eine begrenzte Korrektur am bestehenden System, keine Gesamt-Fertigstellung von AMASTER.


</details>

</details>

</details>
