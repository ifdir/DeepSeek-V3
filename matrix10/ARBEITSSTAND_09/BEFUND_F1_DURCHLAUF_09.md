# F1-Durchlauf: Messung am gelieferten Paket 9b94cb8 (Schritt 1 aus ZIELFAEHIGKEIT_F1)

**Gemessen:** Paket `MATRIX10_STAND08_PRODUKT_linux-x86_64_9b94cb8.zip` (SHA-256 `e12fe563…6d84a`), frisch entpackt.
- Start über `START.py` und die HTTP-Routen der Oberfläche (puppet, prepare, formulate, commit), mit echtem Neustart.
- Am Produkt wurde **nichts geändert**.

**Modell:** ein lokales Testmodell `tools/testmodell_f1_09.py` über den vorhandenen Provider `custom`. Es liefert feste Antworten je Lesung (`tools/drehbuch_f1_09.json`).
- Es ist **kein echtes Modell**. Belegt ist die Kernel-Kette, nicht die Qualität der Formulierung.
- Jeder Modellaufruf wird mit dem echten Prompt protokolliert (`evidence/f1_paket9b94cb8/modellaufrufe.jsonl`).

## Ergebnis: Kernel-Kette F1 ERFÜLLT (11/11), Gegenprobe ROT wie erwartet

Ablauf: Johann schlägt Mara (Puppet) → Folgezug an Mara → Neustart → weiterer Folgezug an Mara.

| Glied | Messwert |
|---|---|
| G1 Tat gebunden | Action-Fact Johann → Mara, Wirkung `gewalt`, validiert |
| G2 Wahrnehmung | Mara `erlebt`, Gustav `gesehen`, Robert (abwesend) **nichts** |
| G3 Körper | Schmerz 0,05 → 0,25, Beweglichkeit 0,90 → 0,75 |
| G4 Bedeutung | Bewertung → Kernel-Prüfung → Affekt „Angst“ gegenüber Johann (Quelle `appraisal`, Ursache = Tat-Fact), Absicht „Abstand zu Johann halten“ |
| G4b Beziehung Mara → Johann | Vertrauen 0,15 → 0,105, Nähe 0,25 → 0,20, Furcht 0,70 → 0,79 |
| G6 Nächster Zug | Der Prompt an das Modell enthält Beziehung (Vertrauen 0,10, Furcht 0,79), Schmerz, Erinnerung „[erlebt] … schlägt Mara“, die verletzte Grenze, und im Lesezustand Gefühl und Absicht |
| G6b Nach Neustart | derselbe Inhalt im Prompt des nächsten Zugs |
| G7 | Beide Figurenantworten sind committet (200) |
| G9 Persistenz | Zustand nach dem Neustart identisch |
| G9b | Im Folgezug wird nichts doppelt angewendet (die Kausalprüfung ohne neue Evidenz lehnt ab) |
| G10 Isolation | Die andere Session und Maras Stamm sind unverändert, Roberts Beziehung ist unverändert |

**Gegenprobe** (`drehbuch_f1_gegenprobe_09.json`: Die Bewertung liefert keine Bedeutung): G4, G4b, G6 und G6b werden ROT. Der Durchlauf misst also wirklich die Bedeutungskette.

## Was das heißt

- **Die Kette Erlebnis → Bedeutung → Zustand → nächster Zug → Neustart ist im Produkt vorhanden und geschlossen**, sobald ein Modell die Bewertung liefert.
- Sie war bisher ungemessen. Die Gesamtkarte führte K-03 als ROT/BLOCKIERT, weil sie **ohne** Provider gemessen wurde. Ohne Schlüssel bleibt es dabei: Es läuft nur das Abklingen (`app.py:_appraise_perceived`).
- **Offen und nicht hier messbar:**
  - echte Modellantworten (Glied 7);
  - Android und echter Schlüssel (Glieder 11 und 12);
  - eigenständiges Handeln (K-05, Glied 8).

## Befunde auf dem F1-Pfad (nicht repariert, ohne Patch)

| Nr | Befund | Beleg | Einordnung |
|---|---|---|---|
| B1 | Ein Schlag erzeugt zwei Facts mit gleichem Text (`action` und `physical`). Beide stehen als getrennte Ereignisse in `gerade_geschehen` der Bewertung | `scene_facts` Turn 1. Payload der Bewertung in `modellaufrufe.jsonl` | UNKLAR. Ein echtes Modell könnte den Schlag doppelt gewichten. Messung mit echtem Modell nötig |
| B2 | `beziehung_zum_handelnden` beschreibt den Akteur des **letzten** Ereignisses (hier die Bedienperson: „KEIN gewachsener Bund – neutral/fremd“). Im Payload steht aber nicht, welche Person gemeint ist. Der Schlag kam von Johann (Vertrauen 0,15, Furcht 0,70) | `kernel.py` (`_ev_actor` = Akteur von `p["events"][-1]`), Payload der Bewertung | ROT-Kandidat für G4 mit echtem Modell: Der Bewerter kann „neutral/fremd“ auf Johann beziehen. Minimaler Ansatz: den Namen der Person in den vorhandenen Text aufnehmen. Erst nach Freigabe |
| B3 | „Fass mich nie wieder an, Johann.“ ruft `GRENZE_CHECK_RULES` auf. Im Testmodell ist das nicht gescriptet, daher wird keine neue Grenze gesetzt | `modellaufrufe.jsonl` | nicht gemessen |
| B4 | Die Intensität des Gefühls sinkt im Folgezug (0,85 → 0,637), obwohl Schmerz und Johanns Anwesenheit fortbestehen. Der Basiswert des Affekts bleibt 0,85 | `f1_ergebnis.json` nach_turn2 | UNKLAR gegen AMASTER §42 („aktive Ursache darf nicht allein durch Zeitablauf verschwinden“). Mehr Züge messen |
