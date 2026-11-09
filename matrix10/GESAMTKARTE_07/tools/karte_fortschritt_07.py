#!/usr/bin/env python3
"""Gesamtkarte 07: Fortschritt nach Arbeitsstand 07 (K-01 + SEC) in die Bereichskarten eintragen - nur belegte Aenderungen.

Je betroffenem Eintrag: alter Status (status_05d8e8a), neuer Status, was geschlossen ist, was offen bleibt, Beleg.
GRUEN wird nicht vergeben (Formulierung mit echtem Modell BLOCKIERT, Kettenvertrag §3). Danach KARTE_GESAMT neu erzeugen:
python3 -I karte_fortschritt_07.py && python3 -I karte_zusammenfuehren_07.py
"""
import json
from pathlib import Path

HIER = Path(__file__).resolve().parents[1]
B = "ARBEITSSTAND_07 (Commits 3349958 SEC, 329df34 K-01); Abnahme evidence/chain_07 (frischer Klon)"
FORT = {
    "T-13": ("TEILGESCHLOSSEN", ["Eingabe-Actor serverseitig aus Session + Modus (app.eingabe_binden), abweichender inputActorId 422 "
                                 "EINGABE_ACTOR_UNGEBUNDEN", "sceneId/timeRef/uploadRef aus SceneState/Fokus",
                                 "Phase 'complete': Client-TurnTruth nur noch mit Turn-Beleg (Kern-Felder gegen prepare)"],
             ["Modell-Live-Lauf BLOCKIERT"]),
    "T-S05": ("TEILGESCHLOSSEN", ["Claims/Frames lesen die kanonische Wahrnehmung (_scene_perception) statt hearsIds||presentIds"],
              ["Antwortphase nutzt Hoerer der Eingabe-TurnTruth (T-20 Defekt 3)"]),
    "T-S18": ("TEILGESCHLOSSEN", ["commit nimmt nur die Serverformulierung dieses Turns (Formulierungsbeleg, juengster beendeter "
                                  "Antwortversuch V65U); fremder/veraenderter/aelterer Text 422"], ["Modell-Live-Lauf BLOCKIERT"]),
    "T-W2": ("TEILGESCHLOSSEN", ["Evidenz = eigene Aeusserung/Handlung des Actors (kernel.lifecycle_evidence_fact)",
                                 "Status aendert sich ohne Evidenz nicht", "Leser + Schreibgrenze: fremde Evidenz / keine "
                                 "Quellturn-Partei -> nicht gebunden; Avatar-/Bedienpersonen-Antwort bleibt gueltig"],
             ["Produktpfad mit Modell-Plan (Annahme/Ablehnung durch Figur) live BLOCKIERT"]),
    "T-17": ("ROT", ["Sprecherart Eingabe aus speak_as + Session gebunden"], ["Narrator und Beobachter fallen zusammen"]),
    "T-24": ("ROT", ["normale Route kann keine Figurenrede mehr unterschieben (char:/fremder Actor 422)"],
             ["speakAs 'char:<id>' bleibt dauerhaft in der Session (Wertung UNKLAR)"]),
    "T-S03": ("ROT", ["Eingabe-Actor gebunden", "Antwortsprecher muss anwesend UND sprechfaehig sein (figure_speaker_eligible)"],
              ["Auswahl selbst weiter im Browser (pickSpeaker) - K-05"]),
    "T-S16": ("ROT", ["Faehigkeitspruefung des gewaehlten Sprechers (Bewusstsein 0 galt als 1)"],
              ["Sprecherwahl vor Eingabe-Commit/Appraisal/Fate; Owner doppelt (Browser/Server) - K-05"]),
    "T-28": ("ROT", ["Server prueft Anwesenheit + Faehigkeit"], ["Browser-Heuristik pickSpeaker bleibt zweiter Owner - K-05"]),
    "T-20": ("ROT", ["leere Hoererliste faellt nicht mehr auf alle Anwesenden zurueck (Claims/Frames)"],
             ["Hoerer der Antwortphase vom Eingabezeitpunkt", "kein Writer fuer 'spaeter informiert' im Turnpfad"]),
    "Z-22": ("ROT", ["Client kann keine Synapsen/fired mehr setzen (Ausgangsnachweis: proposals.synapsen aenderten die Runtime)"],
             ["Modell-Vorschlaege laufen weiter als validated in apply_synapses; feste Wirkungstabelle - K-03"]),
    "P-21": ("ROT", ["SEC: GET /api/mcc ohne Klartext-Schluessel (maskierte Sicht wie /api/config)"],
             ["zweite Modellquelle user.providerConfig", "Felder ohne Backendleser", "verschluckter Fehler"]),
    "T-K9": ("ROT", ["Glieder serverseitige TurnTruth, Perception (Claims/Frames), Formulierung->Commit geschlossen (offline)"],
             ["Upload-Bindung T-S06", "Sprecherwahl clientseitig T-28", "Modell-Live BLOCKIERT"]),
}


def main():
    for b in "WTZAP":
        p = HIER / "karte" / f"{b}.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        for x in d:
            if x.get("id") in FORT:
                neu, zu, offen = FORT[x["id"]]
                x.setdefault("status_05d8e8a", x["status"])
                x["status"] = neu
                x["stand_07"] = {"status": neu, "geschlossen": zu, "offen": offen, "beleg": B}
        p.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("eingetragen:", sorted(FORT))


if __name__ == "__main__":
    main()
