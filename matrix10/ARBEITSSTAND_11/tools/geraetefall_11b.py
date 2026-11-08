#!/usr/bin/env python3
"""Stand 11B: deine zwei Eingaben vom Geraet (08.11. 21:58) ueber den echten Weg wie die UI (START.py, Puppet Johann -> Reaktionszug
Mara -> commit), Modell = Testmodell mit den WOERTLICHEN gpt-4o-mini-Antworten (drehbuch_geraetefall_2158_11b.json).
Nutzt gleichstand_p25_10a.main() unveraendert, nur mit diesen Eingaben.
Aufruf: python3 -I geraetefall_11b.py <produktordner> <vorlage.sqlite> <ausgabe.json> <verzoegerung_s> [drehbuch.json]
"""
from pathlib import Path
import sys

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parents[1] / "ARBEITSSTAND_10A" / "tools"))
import gleichstand_p25_10a as G  # noqa: E402

G.EINGABEN = ["Ich streiche über deine schenkel", "Ach komm, ich streiche über deibe brust, dir gefällt das ja"]
if len(sys.argv) < 6:
    sys.argv.append(str(HIER / "drehbuch_geraetefall_2158_11b.json"))
raise SystemExit(G.main())
