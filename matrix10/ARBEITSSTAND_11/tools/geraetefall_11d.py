#!/usr/bin/env python3
"""Stand 11D: deine drei Eingaben vom Geraet (09.11. 11:08) ueber den echten Weg wie die UI, Modell = Testmodell mit den WOERTLICHEN
gpt-4o-mini-Antworten (drehbuch_geraetefall_0911_11d.json). Nutzt gleichstand_p25_10a.main() unveraendert, nur mit diesen Eingaben.
Aufruf: python3 -I geraetefall_11d.py <produktordner> <vorlage.sqlite> <ausgabe.json> <verzoegerung_s> [drehbuch.json]
"""
from pathlib import Path
import sys

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parents[1] / "ARBEITSSTAND_10A" / "tools"))
import gleichstand_p25_10a as G  # noqa: E402

G.EINGABEN = ["Hey süsse, ich klarsche dir auf deinen Arsch", "Ach komm stell dich nicht so an", "Ich greife unter dein tshirt und lach dich an"]
if len(sys.argv) < 6:
    sys.argv.append(str(HIER / "drehbuch_geraetefall_0911_11d.json"))
raise SystemExit(G.main())
