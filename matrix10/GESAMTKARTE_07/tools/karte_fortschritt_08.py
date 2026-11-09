#!/usr/bin/env python3
"""Gesamtkarte: Fortschritt nach Arbeitsstand 08 (K-02) eintragen - nur belegte Aenderungen (Abnahme evidence/chain_08).

Status vor 08 bleibt in `status_vor_08`; GRUEN wird nicht vergeben (Modell BLOCKIERT, Kettenvertrag §3).
python3 -I karte_fortschritt_08.py && python3 -I karte_zusammenfuehren_07.py
"""
import json
from pathlib import Path

HIER = Path(__file__).resolve().parents[1]
B = "ARBEITSSTAND_08 (K-02); Abnahme ARBEITSSTAND_08/evidence/chain_08 (frischer Klon)"
FORT = {
    "T-S21": ("TEILGESCHLOSSEN", ["Witness-Quellen einheitlich: Eingabe (prepare), Antwort (Antwortzeitpunkt), Claims/Frames "
                                  "(_scene_perception)", "W2 (Stand 07)"], ["Modell-Live BLOCKIERT"]),
    "T-20": ("ROT", ["Antwortphase: Wahrnehmung zum Antwortzeitpunkt (gegangene Figur hoert die Antwort nicht, live belegt)",
                     "leere Hoererliste / Positions-/Bewusstseinsfilter (Stand 07)"],
             ["kein Writer fuer 'spaeter informiert' im Turnpfad (nur Regie) - K-03 (braucht Bedeutungslesung, welches "
              "Ereignis erzaehlt wird)"]),
    "Z-15": ("TEILGESCHLOSSEN", ["Negativ-Nachweis ausgefuehrt: abwesende/gegangene Figur ohne Wissen (Tests + live)"],
             ["'spaeter informiert' fehlt (T-20)"]),
    "Z-19": ("TEILGESCHLOSSEN", ["Gedaechtnisseite zeigt den kanonischen Abruf der gewaehlten Figur (kernel.recall), live nach "
                                 "Neustart belegt; Cache-Abruf als nicht kanonisch gekennzeichnet"],
             ["Abruf liest gespeicherten statt reduzierten Propositionsstatus (open_texts, nur Relevanz)"]),
    "Z-30": ("TEILGESCHLOSSEN", ["echter Prozess-Neustart (START.py) belegt: Wissen/Abruf unveraendert (live)"],
             ["Modell-Live BLOCKIERT"]),
    "Z-13": ("TEILGESCHLOSSEN", ["Zuordnung gehoert/gesagt mit Zuschreibung an Berechtigte geprueft (Tests + live)"],
             ["Vertrauensgrad, Relationen zwischen Erinnerungen fehlen; Memory nach Commit unveraenderlich - K-03"]),
    "Z-14": ("ROT", [], ["Writer fuer geglaubt/vermutet/bestritten/unsicher/vergessen fehlt - zugeordnet K-03 (Bedeutungslesung)"]),
    "Z-17": ("TEILGESCHLOSSEN", ["gehoerte Rede bleibt Redeereignis mit Zuschreibung, keine Weltwahrheit (geprueft)"],
             ["kein Zustand glaubt/bezweifelt je Hoerer - K-03"]),
}


def main():
    for b in "WTZAP":
        p = HIER / "karte" / f"{b}.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        for x in d:
            if x.get("id") in FORT:
                neu, zu, offen = FORT[x["id"]]
                x["status_vor_08"] = x["status"]
                x["status"] = neu
                x["stand_08"] = {"status": neu, "geschlossen": zu, "offen": offen, "beleg": B}
        p.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("eingetragen:", sorted(FORT))


if __name__ == "__main__":
    main()
