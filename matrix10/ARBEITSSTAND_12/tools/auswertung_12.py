#!/usr/bin/env python3
"""Stand 12: Auswertung der Live-Laeufe (live_kette_12.py) als Tabelle: Zeit je Zug, Ausgabe-Token und Dauer je Stufe,
Wiederholung (5-Wort-Folgen in >=2 Antworten derselben Figur; gleiche Handlungsanfaenge), Maras Gefuehl/Absicht je Zug.
Aufruf: python3 -I auswertung_12.py <lauf1> [<lauf2> ...]"""
import json
import re
import sys
from pathlib import Path


def main() -> int:
    for d in map(Path, sys.argv[1:]):
        E = json.loads((d / "ergebnis.json").read_text(encoding="utf-8"))
        calls = [json.loads(x) for x in (d / "modellaufrufe.jsonl").read_text(encoding="utf-8").splitlines()]
        st: dict = {}
        for c in calls:
            s = st.setdefault(c["schema"], {"n": 0, "tok": [], "s": []})
            s["n"] += 1
            s["tok"].append((c.get("usage") or {}).get("completion_tokens") or 0)
            s["s"].append(c["dauer_s"])
        zeiten = [s.get("gesamt_s") for s in E["schritte"]]
        print(f"== {d.name}: Zuege {len(E['schritte'])}, Zeit je Zug {zeiten}, Fehlerstatus "
              f"{[s.get('status') for s in E['schritte'] if s.get('status') != [200, 200, 200]]}")
        for k, s in st.items():
            print(f"   {k:15s} n={s['n']:2d} Token Ø{sum(s['tok'])/len(s['tok']):5.0f} (max {max(s['tok'])})  "
                  f"Dauer Ø{sum(s['s'])/len(s['s']):5.1f}s (max {max(s['s'])})  Token/s {sum(s['tok'])/max(sum(s['s']),.1):4.0f}")
        for fig, w in E["wiederholung"].items():
            print(f"   Wiederholte 5-Wort-Folgen {fig}: {len(w['fuenfwort_in_2plus'])}")
        for s in E["schritte"]:
            z = s.get("zustand") or {}
            print(f"   {s['art']}{s.get('nr')} {s.get('sprecher')}: {str(s.get('speech'))[:70]!r} | {str(s.get('action'))[:50]!r} "
                  f"| Mara {z.get('emotion')} {z.get('intensity')} '{z.get('intent')}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
