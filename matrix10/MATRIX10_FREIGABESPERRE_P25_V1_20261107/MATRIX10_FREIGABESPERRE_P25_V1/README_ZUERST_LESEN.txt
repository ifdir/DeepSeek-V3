MATRIX10 - TECHNISCHE FREIGABESPERRE V1
07.11.2026

ZWECK
Diese Datei startet einen EXTERNEN Pruefer fuer die unveraenderte Originaldatei
MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107.zip.
Es wird kein Produktcode geaendert. Es wird KEINE bestehende Datenbank verwendet.
Es entsteht KEINE neue Matrix10-Produktversion.

1. BEDIENUNG AUF WINDOWS

- Dieses ZIP in einen neuen leeren Ordner entpacken.
- FREIGABE_PRUEFEN_WINDOWS.bat doppelklicken.
- Das schwarze Fenster bleibt am Ende offen.
- Danach im neuesten Ordner ERGEBNIS_... die Datei ERGEBNIS_LESEN.txt
  oeffnen. Dort steht zuerst der Gesamtstatus und danach jeder Sperrgrund.
- Fuer vollstaendige Einzelprotokolle gibt es den Ordner LOGS.

Python 3 ist erforderlich. Node und npm werden fuer den Frontend-Bau benoetigt.
Der Windows-Pruefstart darf mit npm ci Abhaengigkeiten aus dem Internet laden,
jedoch NUR in der frisch entpackten temporaeren Pruefkopie. Er startet weder
Matrix10 noch eine produktive Kundendatenbank.

2. WAS DIE ERSTE FREIGABESPERRE WIRKLICH KANN

- Eingangsarchiv gegen fest eingefrorenen SHA-256 pruefen.
- CRC, ZIP-Pfade, Doppeldateien, Symlinks, Entpackgroesse pruefen.
- Original-P25-Dateien einzeln gegen das mitgelieferte Manifest pruefen.
- Sollquellen und Vertragsreferenzen auf Widersprueche pruefen.
- Vorhandene Flask-/Python-Tests nur dann als bestanden werten, wenn sie
  tatsaechlich ausgefuehrt werden und Exitcode 0 liefern.
- Frontend bei vorhandenen Voraussetzungen frisch bauen; Build-ID pruefen.
- Bei fehlendem Browser-/Provider-/SQLite-/Folgeturn-Nachweis sperren.
- Fuer jede Pflichtachse alle 20 Punkte nach Kettenvertrag Paragraph 16
  als UNGEPRUEFT sichtbar machen, nicht als stilles PASS.
- Bereits dokumentierte offene Vertragsvorbefunde bleiben ROT, solange
  sie nicht durch neue echte Kettennachweise ausgeraeumt sind.
- Selbst bei manipulierten/pauschal gruen markierten lokalen Testresultaten
  KEINE automatische Produktfreigabe.

3. WAS SIE NOCH NICHT KANN

- Echtes Modell mit realem UI und SQLite bis zum Folgeturn nachmessen.
- Produkt-Standardstart / Migration / Neustart und Android abnehmen.
- Vollstaendige bidirektionale Frontend-Backend-Funktionsmatrix pruefen.
- Alle AMASTER-/SPS-Pflichtketten nach §16 automatisch beweisen.

Daher kennt diese V1 KEINE gruene Produktfreigabe. Diese Sperre ist die
technische Voraussetzung fuer ein spaeteres unabhaengiges E2E-Pruefsystem,
nicht dessen Ersatz.

4. DIE DREI OFFENEN VORARBEITEN, BEVOR PRODUKTREPARATUREN WEITERGEHEN

A. Autoritative SOLL-Quellen verbindlich zuordnen:
   Vertrag §0 nennt AMASTERv2.md(1).txt und Matrix10.txt mit anderen SHA-Werten.
   Im P25-Paket liegen 2_7master.txt und MATRIX10_SPS_MASTER.md. Weder Namen
   noch Inhalte werden automatisch gleichgesetzt. Dieses Dokumentkonflikt
   muss autoritativ entschieden und in ein Inputregister aufgenommen werden.

B. Testumgebung vollstaendig herstellen (Flask, Node, npm, Build, Startweg,
   vorgegebene Test-EPUB, isolierte DB-Kopie, Provider/Browser).

C. Echte externe Kettenpruefer nach §16 erstellen: UI-Interaktion ->
   API/Authority -> Writer -> SQLite -> Reader/BrainContext -> Figur ->
   Commit -> Folgeturn -> Reload -> UI -> Negativ-Isolation.
   Fuer jede Achse muss der Test die Originaldaten und Fremdsessions unberuehrt
   lassen. Ein isolierter Unit-Test oder Textsuche reicht nicht aus.

5. EXITCODES

0 = in V1 absichtlich nicht verfuegbar (keine Produktfreigabe)
2 = ROT: nachgewiesene Fehlschlaege oder offene Vertragsvorbefunde
3 = BLOCKIERT: fehlende Voraussetzungen ohne weiteren ROT-Nachweis

FREIGABE_ERZEUGEN ist absichtlich nicht vorhanden. Es wird weder ein
neues Produkt-ZIP noch eine irrefuehrende Gruen-Meldung erzeugt.

6. DATENSCHUTZ / GRENZEN

Das P25-ZIP wird im neu angelegten temporaeren Pruefordner entpackt und
nach Abschluss geloescht. Die Original-P25-Datei bleibt bytegleich.
Die Umgebung loescht API-Schluessel-Variablen aus Testprozessen, um keine
echten Provideranfragen aus nicht autorisierten Tests zu starten.
Trotzdem werden produktfremde Abhaengigkeiten per npm ci ausgefuehrt:
vorher package-lock und Herkunft der Pakete pruefen, wenn das Material
nicht vertrauenswuerdig ist.

WICHTIG: Dieses Verfahren beweist, dass es eine Stoppsperre gibt. Es ist
noch keine unabhaengige, gruene Gesamtpruefung der Matrix10-Software.
