# Befund Stand 08: zusätzlich roter P18-Test (K-01) und nicht erkannte Rust-only-Mutation

**Gelesen:** AMASTERv2 §6, §28 Schritt 20, §36.2/§36.5, §50; Kettenvertrag §2, §4, §6.5; SPS V65S und V70; Nutzerentscheidung 06a (M1: Rust-Sprecherbindung bleibt redundante Pflichtschicht).
**Status beider Punkte:** ROT bleibt, nichts wird pauschal als erledigt erklärt.

## 1. P18-Test `test_avatar_position_and_figure_reply_with_forged_and_real_readings`

### Messung am gelieferten Paket
Der Test läuft im frisch entpackten Paket `…_6713376` und scheitert mit
`AssertionError: 422 != 200 … "code":"TURN_BELEG_UNGUELTIG"`.

### Erste falsche Stelle
Die erste falsche Stelle liegt **im Testaufbau, nicht im Produkt**.
- Die Testhilfe `P18AvatarAndFigure.respond()` (`tests/test_v92_p18_koerper.py`) postet Maras Antwort, „Mara keucht vor Schmerzen …“ bzw. „Mara setzt sich neben ihn.“, direkt als `result` an `/api/kernel/commit`.
- Sie geht dabei nicht über `/api/llm/formulate`.
- Der Test verlangt dafür HTTP 200, also dass eine Figurenrede committet wird, die der Server nicht formuliert hat.

### Vertragsprüfung
- **AMASTER §28 Schritt 20:** Committet werden „die tatsächlich ausgedrückten Rede- und Zustandskomponenten“.
- **AMASTER §50:** Das LLM formuliert, der Zustand kommt nicht vom Client.
- **Kettenvertrag §4:** Der Client darf Bedienabsicht senden, „aber keine kanonischen … überschreiben“.

Genau dieser Pfad war der K-01-Defekt. Er ist live reproduziert: Eine erfundene Figurenrede wurde committet und war nach dem Neustart noch da.

### Einordnung
**Veraltete Testannahme, keine Produktregression.** Der Test prüft zwei fachliche Aussagen:
- Der Server liest Körperänderungen nur selbst.
- Ein gefälschter Zusatz bewirkt nichts.

Beide Aussagen laufen mit **unveränderten Assertions** über den Produktweg in `ARBEITSSTAND_07/tests/test_k01_p18_portiert_07.py` und bestehen. Die Gegenprobe im selben Test belegt: Der alte Client-Text-Weg wird abgewiesen, und es wird nichts gespeichert.

### Bleibt
**Der P25-Test bleibt rot und wird nicht geändert** (`P25_testsuite_zusaetzlich_rot_durch_k01 = ROT`). Die Portierung ist ein zusätzlicher Nachweis und macht den Fehlschlag nicht ungeschehen. Über eine Anpassung des P25-Tests entscheidet der Nutzer.

## 2. Rust-only-Mutation „ohne Sprecherbindung“ (`consent.rs`: `e.active && e.by == giver` → `e.active`)

### Messung
Stufe E der Gesamtkette (zuletzt `chain_08`):
- Die Mutation wird über die Einwilligungskette **nicht** erkannt; die Kette bleibt bei 10 von 10.
- In Rusts eigenen Tests wird sie erkannt: `cargo test` wird rot.
- Die kombinierte Gegenprobe ohne Python- und ohne Rust-Bindung bleibt fail-closed.

### Erste Stelle, an der die Rust-Prüfung unbeobachtbar wird (Codefluss)
1. `scene_state.lifecycle_evidence` filtert jeden Lifecycle-Fact mit `lifecycle_bound` (`scene_state.py:340`). Dort gilt die Python-Giver-Regel: Körperkontakt beantwortet nur der Berührte (W1).
2. `body_contact_entries` (`scene_state.py:364`) liest nur diese gefilterten Facts.
3. Erst danach ruft `body_contact_standing` den Rust-Reducer auf (`reduce_body_contact_standing`, `scene_state.py:484`).
4. Zusätzlich weist die Schreibgrenze (`repos._check_lifecycle_actor` → `lifecycle_bound`) Facts mit fremdem Geber schon beim Schreiben ab.

Auf keinem Produktpfad erreicht Rust also ein Eintrag mit fremdem Geber. Seine Geber-Prüfung ist im Produkt nicht erreichbar, nur direkt (Rust-Unit-Tests, ABI-Vertragstest).

### Vertragsprüfung
- **AMASTER §6:** Jede Wahrheitsart hat genau einen zuständigen Owner. „Wer darf Einwilligung geben“ prüfen derzeit drei Schichten: die Python-Schreibgrenze, den Python-Leser und Rust.
- **Nutzerentscheidung 06a/M1:** Die Rust-Prüfung bleibt als redundante Pflichtschicht, ihre Nichtbeobachtbarkeit über die Kette bleibt dokumentiert ROT, „kein künstliches GRÜN“.

### Einordnung
Das ist **keine Regression**. Es ist die direkte Folge der beschlossenen Redundanz: Die Python-Leserschicht verdeckt Rust.

Eine Auflösung wäre eine Architekturentscheidung, entweder:
- (a) die Giver-Prüfung auf der Leseseite nur in Rust und an der Schreibgrenze in Python, oder
- (b) die Redundanz bleibt und die Kettenmutation bleibt nicht beobachtbar.

Ohne Nutzerentscheidung wird **nichts geändert**. Status bleibt **ROT** (`M1_rust_only_mutation_ueber_kette`).
