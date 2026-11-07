#!/usr/bin/env python3
"""Regressionsvergleich zweier Kettenprüfer-Ergebnisse (ERGEBNIS.json): je Fall und je Glied
   neu rot / wieder grün / unverändert rot / sonst geändert.

Aufruf: python3 -I kp_vergleich.py <ALT/ERGEBNIS.json> <NEU/ERGEBNIS.json> [Ausgabe.txt]
Nur Fälle, die in BEIDEN Läufen gelaufen sind, werden verglichen; die übrigen werden genannt.
Exitcode 2, wenn etwas neu rot ist, sonst 0.
"""
import json
import sys
from pathlib import Path


def lade(p: str) -> dict:
    e = json.loads(Path(p).read_text(encoding="utf-8"))
    return {f["id"]: {"status": f["status"], "glieder": {g["glied"]: (g["status"], g["beleg"]) for g in f["glieder"]}}
            for f in e.get("faelle") or []}, e


def main() -> int:
    (alt, ea), (neu, en) = lade(sys.argv[1]), lade(sys.argv[2])
    z = ["KETTENVERGLEICH", "=" * 60,
         "ALT: %s  %s" % (ea["basis"]["zip"], ea["basis"]["zip_sha"][:16]),
         "NEU: %s  %s" % (en["basis"]["zip"], en["basis"]["zip_sha"][:16]),
         "Prüfer gleich: %s, Fallkatalog gleich: %s" % (ea["basis"].get("pruefer_sha") == en["basis"].get("pruefer_sha"),
                                                     ea["basis"].get("faelle_sha") == en["basis"].get("faelle_sha")), ""]
    gruppen = {"NEU ROT": [], "WIEDER GRUEN": [], "UNVERAENDERT ROT": [], "SONST GEAENDERT": []}
    for fid in sorted(set(alt) & set(neu)):
        for nr in sorted(set(alt[fid]["glieder"]) | set(neu[fid]["glieder"])):
            if nr == 20:
                continue
            sa = alt[fid]["glieder"].get(nr, ("FEHLT", ""))[0]
            sn, bn = neu[fid]["glieder"].get(nr, ("FEHLT", ""))
            zeile = "%s Glied %02d: %s -> %s | %s" % (fid, nr, sa, sn, bn[:140])
            if sn == "ROT" and sa != "ROT":
                gruppen["NEU ROT"].append(zeile)
            elif sa == "ROT" and sn == "GRUEN":
                gruppen["WIEDER GRUEN"].append(zeile)
            elif sa == "ROT" and sn == "ROT":
                gruppen["UNVERAENDERT ROT"].append(zeile)
            elif sa != sn:
                gruppen["SONST GEAENDERT"].append(zeile)
    for k, v in gruppen.items():
        z += ["%s: %d" % (k, len(v))] + ["  " + x for x in v] + [""]
    nur = sorted(set(alt) ^ set(neu))
    if nur:
        z.append("Nicht in beiden Läufen (nicht verglichen): " + ", ".join(nur))
    text = "\n".join(z) + "\n"
    if len(sys.argv) > 3:
        Path(sys.argv[3]).write_text(text, encoding="utf-8")
    print(text)
    return 2 if gruppen["NEU ROT"] else 0


if __name__ == "__main__":
    sys.exit(main())
