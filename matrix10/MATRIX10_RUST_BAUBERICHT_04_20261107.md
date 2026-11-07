# Matrix10 – Rust-Arbeitsstand 04: Ketten-/Ursachenbericht

**Stand:** 7. November 2026. **ROT / BLOCKIERT / keine Produktfreigabe.**

## Verbindliche Grundlagen und Quellen

- AMASTERv2.md(1).txt, SHA-256 `fb4f2015783dafe9474ee77d26b23fafb7c2c76a1c6ba923727f3aaedba5721d`.
- Matrix10.txt, SHA-256 `1465980a0675a36b3143175c216048dae04d615c9e174d5821a8a2bb94917bc8`.
- MATRIX10_SPS_MASTER.md und VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt. Es gilt der jeweils vorhandene Originalwortlaut.
- Eingefrorene IST-Basis V67: `MATRIX10_V67_ABHAENGIGKEIT_20261031.zip`, SHA-256 `5158df268ab7f9105428b26c90932998e5b7b10fb8a3926e97ff2c4aa382efed`.
- Vorangehender Rust-Arbeitsstand 03. Keine Produkt-, Datenbank- oder Altversionsüberschreibung.

**Quellenabweichung:** In diesem eingepackten AMASTER sind die Abschnitte 36.1–36.4 vorhanden. Das ältere SPS und Codekommentare referenzieren teilweise §36.5. Die hier geprüften Anforderungen werden anhand des tatsächlichen AMASTER-Textes (u. a. §34–§37, §68) ausgelegt. Alte Verweise sind keine neuen AMASTER-Paragraphen.

## 1. Erste falsche Stellen am unveränderten Original

Ausgeführtes Werkzeug: `tools/probe_original_consent_04.py` mit unveränderter V67, originalen Repository-Writern, isolierten SQLite-Dateien, Commit/Close/Reopen und `scene_state`-Reader. Alle 4 Fälle wurden **auf Original-V67 als fehlerhaft reproduziert** (also nicht als neue Defekte gezählt). Details: `evidence/original_reader_counterprobes_04.json`.

| Fall | Eingangskette | Soll | Ist in V67 |
| --- | --- | --- | --- |
| C04_WRONG_GIVER_BROAD | Bob lehnt alle Berührungen ab, Alice stimmt später zu | Bobs Ablehnung bleibt | `accepted` |
| C04_EXPIRED_BROAD_ACCEPTANCE | Bob lehnt ab, Bobs spätere Zustimmung ist zum Prüfzeitpunkt abgelaufen | `declined` | `null` |
| C04_EXPIRED_NARROW_REFUSAL | Bob erlaubt rechte Hand, spätere Ablehnung ist abgelaufen | Erlaubnis bleibt | keine Erlaubnis |
| C04_EXPIRED_NARROW_ACCEPTANCE | Bob lehnt rechte Hand ab, spätere Zustimmung ist abgelaufen | Ablehnung bleibt | keine Ablehnung |

Bei jedem Fall: 2 persistierte Fakten nach SQLite-Neuöffnung; fremde Session 0 Fakten. Die Fakten sind Originalevidenz, die fehlerhafte Current-State-Projektion ist eine separate Reader-Ursache.

## 2. Quellreparatur in V04 – noch keine native Wirkung bewiesen

**Gesamte Teilkette:** `body_contact_entries` → kanonische `window`-Prüfung mit `_in_window` für **jedes** Ereignis → FFI der Version 2 → Rust-Evidenzreduktion auf den gebundenen `giver` → nur Faktenindizes an Python zurück → Reader-Projektion auf belegte Fakt-IDs und vorhandene UI-/Kernel-Datenformen.

Drei `scene_state`-Reader nutzen jetzt Rust-Reducer-Quellen:

- `body_contact_standing` (allgemeine Grenzen / gültige Ausnahmen / historische Beendigung),
- `restricted_refusals_standing` (eingeschränkte Ablehnungen),
- `restricted_permissions_standing` (eingeschränkte Erlaubnisse).

Alle drei verwenden denselben Sprecher- und Zeitfenster-Mechanismus. Ein fremder oder leerer Sprecher und eine nicht mehr gültige Einschränkung dürfen spätere Zustände nicht ändern. Keine Trunkierung nach sechs Ereignissen. Rust schreibt keine zweite Datenbank und ersetzt keine historischen Fakten.

**Python-FFI-Härtung:** Die Brücke prüft die Indizes gegen den tatsächlichen Sprecher, die Gültigkeit und den gespeicherten Scope/Kontext des angezeigten Fakts. Fehlerhafte Native-Antworten dürfen weder Erlaubnis noch Ablehnung als positive Aussage belegen. Die ABI-Kennung steht konsistent auf 2; der dazugehörige Rust-Test wurde auf 2 geändert.

**Unveränderte API-Wirkung:** Keine neuen HTTP-Routen, kein neuer Zustandsspeicher und keine nur über eine verborgene API steuerbaren Funktionen. Die bestehende Oberfläche ist jedoch **nicht end-to-end geprüft**. Die fachliche Schreibvalidierung von Lifecycle-Events ist **nicht vollständig in Rust repariert**.

## 3. Kontrollierter Originalvergleich

V67 enthält 2.102 Originaldateien. Davon sind im frischen Stage 2.100 bytegleich; lediglich `matrix_api/repos.py` und `matrix_api/scene_state.py` sind kontrolliert verändert. Neun zusätzliche Quell-/Statusdateien gehören zum Rust-Source-Overlay. Die V67-Originaldatenbank `data/matrix10.sqlite` ist unverändert (SHA-256 `9be11b8410c4396eb731254f997dfed3095cd6c65c048bc04e80cd3e8c2d4003`). Der Python-Adapter wird als neue Datei hinzugefügt. Staging erfolgt nur in einem neuen Zielordner und verweigert bestehenden Zielordner oder abweichende Originalhashes.

## 4. Ausgeführte Prüfschritte (dieser Stand)

| Prüfart | Resultat | Aussagegrenze |
| --- | --- | --- |
| Python-Transport | **13/13 PASS** | Codec/FFI-Verhalten ohne Rust |
| Python-Consent-Transport | **8/8 PASS** | Eingabeform und negative Transporttests ohne Rust |
| Python-Consent-Projektion inkl. 5 neuer Antwort-Gegenproben | **18/18 PASS** | `_native_request` gemockt, **kein Rust-Nachweis** |
| Original-V67 SQLite-Reader-Gegenproben C04 | **0/4 SOLL**, Fehler 4/4 reproduziert | Belegt Altfehler, nicht die Quellreparatur |
| Drei geänderte Python-Module, Syntax | **PASS** | Keine semantische Native-Funktion |
| Native-Build/Tests | **BLOCKIERT**, `rustc`/`cargo` fehlen | 0 Rust-Tests ausgeführt |
| Native-Writer/SQLite-Probe | **BLOCKIERT**, kein kompiliertes `.so` | 0 native SQLite-Prüfungen ausgeführt |
| Rust-Testdefinitionen | **78**, davon **0 ausgeführt** | Testdefinition ist kein Testnachweis |
| Vollständige V12-/AMASTER-Prüfung, Frontend, Folgeturn, Fremdisolation | **UNGEPRÜFT/ROT** | Kein Produktnachweis |

Der Writer liefert ohne Native-Bibliothek Fehler 503 und soll keine Schreibtransaktion autorisieren. Das ist **Fail-closed**, nicht eine reparierte oder grüne Produktkette.

## 5. Offene notwendige Arbeit (keine Freigabe)

1. `rustc`/`cargo` installieren und den Rust-Source gegen `cargo test --offline --locked` sowie `cargo build --release --offline --locked` tatsächlich kompilieren; sämtliche Unit-Tests ausführen. Vorhandene Rust-Unit-Tests schließen allein noch keine Kette.
2. Rust-Evidenzreduktion in echten Writer-/SQLite-/Reader-/Folgeturn-Prüfungen bestätigen; diese C04-Gegenproben sowie B01–B04 auf dem **ausführbaren** Kandidaten grün nachweisen. Kein Ersatz durch Python-Mock/Orakel.
3. Die semantische Schreibgrenze (Handlungsbindung, betroffene Körperstelle, Giver, Umfang, Zeit-/Szenengültigkeit, Validierungs-Commit) vollständig reparieren. Insbesondere ist aktuell nicht bewiesen, dass falsch zugeschriebene Lifecycle-Einträge schon beim Writer konsequent abgewiesen werden.
4. Danach übrige Python-Kernel-Funktionen, Charakter-/Gedächtnis-/Erfahrungs-/Lern-, Welt- und BrainContext-Folgekette nach AMASTER/SPS vollständig nach Rust übertragen. Eine bloße 70-Abschnitt-Dateizuordnung ist dafür kein Beweis.
5. Frontend und HTTP über **sichtbare Bedienhandlungen** bis SQLite, Reader, Folgeturn, Neustart und User-/Session-Isolation unter der unabhängigen Prüfmaschine V12 offline vollständig abnehmen. Erst danach Nutzer-Livetest.

**Status:** UNVERÄNDERT ROT. Dieses Quellpaket ist ausdrücklich **keine installierbare Matrix10-Version**.
