#!/usr/bin/env python3
"""Kettenvertrag §6.4: Gleichstandsmessung P25 (eingefrorene Basis) gegen 10A mit DEINEN 5 Eingaben vom Handy (Live-Log 08.11.
18:29-18:38) ueber den echten Weg wie die UI: START.py, Puppet "Johann ..." -> Reaktionszug der Betroffenen (Mara, inputKind autochat,
wie chat.$sessionId.tsx nach Puppet) -> commit; Neustart vor Eingabe 4. Modell = lokales Testmodell, Antworten = die ECHTEN
Modellantworten vom Geraet (drehbuch_geraet_10a.json), feste Verzoegerung je Modellaufruf (F1_VERZOEGERUNG).
Gemessen je Austausch: HTTP-Status, Dauer, Modellaufrufe je Lesung, Maras Zustand (Gefuehl, Absicht, Beziehung zu Johann).
Aufruf: python3 -I gleichstand_p25_10a.py <produktordner> <vorlage.sqlite> <ausgabe.json> <verzoegerung_s>
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HIER = Path(__file__).resolve().parent
T09 = HIER.parents[1] / "ARBEITSSTAND_09" / "tools"
T10 = HIER.parents[1] / "ARBEITSSTAND_10" / "tools"
sys.path.insert(0, str(T09))
sys.path.insert(0, str(T10))
import f1_durchlauf_09 as F1  # noqa: E402
import f2_durchlauf_10 as F2  # noqa: E402
L7 = F1.L7
EINGABEN = ["Ich klatsch dir auf deinen arsch", "Ich greif dir auf die schenkel", "Ach stell dich nicht so an",
            "Ich streiche dir über die schenkel und halte dir 100 Euro hin und sag gehen wir ins hinterzimmer",
            "Meine hände gleiten zwischen deine schenkel"]


def figurenzug(speaker, text, ev, tag, target=None):
    """Reaktionszug wie runFigure(..., {inputKind: "autochat"}) - mit turnIndex wie kernel-bridge.ts (P25 verlangt ihn)."""
    tr = {"userId": "admin", "sessionId": F1.SID, "speakerId": speaker, "inputActorId": "user", "speakAs": "operator",
          "targetId": target, "inputKind": "autochat", "text": ""}
    a, ja = L7.req("POST", "/api/kernel/prepare", {"sessionId": F1.SID, "truth": tr, "speaker": {"id": speaker}})
    c, jc = L7.req("POST", "/api/llm/formulate", {"sessionId": F1.SID, "sourceTurnId": (ja.get("truth") or {}).get("id"), "speakerId": speaker,
                                                  "turnIndex": (ja.get("session") or {}).get("turnIndex"), "text": "", "scope": "user",
                                                  "inputKind": "autochat", "turnBeleg": ja.get("turnBeleg")})
    res = jc.get("result") or {}
    d, jd = L7.req("POST", "/api/kernel/commit", {"sessionId": F1.SID, "truth": ja.get("truth"), "speaker": {"id": speaker},
                                                  "result": {"speech": res.get("speech"), "action": res.get("action"),
                                                             **({"proposals": res["proposals"]} if res.get("proposals") else {})},
                                                  "fired": ((ja.get("brainContext") or {}).get("spiegel") or {}).get("fired") or [],
                                                  "turnBeleg": ja.get("turnBeleg"), "formulierungsBeleg": jc.get("formulierungsBeleg")})
    (ev / f"{tag}.json").write_text(json.dumps({"prepare": ja, "formulate": jc, "commit": jd}, indent=1, ensure_ascii=False)[:400000])
    return {"prepare": [a, ja.get("code"), ja.get("message")], "formulate": [c, jc.get("code")], "commit": [d, jd.get("code"), jd.get("message")]}


def main() -> int:
    root, vorlage, aus, verz = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), Path(sys.argv[3]).resolve(), sys.argv[4]
    ev = aus.parent / (aus.stem + "_ev")
    ev.mkdir(parents=True, exist_ok=True)
    prot = ev / "modellaufrufe.jsonl"
    prot.unlink(missing_ok=True)
    db = root / "data" / "matrix10.sqlite"
    if not L7.stop():
        return 3
    (root / "data").mkdir(exist_ok=True)
    for f in ("matrix10.sqlite", "matrix10.sqlite-wal", "matrix10.sqlite-shm"):
        (root / "data" / f).unlink(missing_ok=True)
    shutil.copy(vorlage, db)
    env = dict(os.environ, F1_VERZOEGERUNG=str(verz), F1_KAUSAL_ALLGEMEIN="1")
    buch = Path(sys.argv[5]).resolve() if len(sys.argv) > 5 else HIER / "drehbuch_geraet_10a.json"
    tm = subprocess.Popen([sys.executable, "-I", str(T09 / "testmodell_f1_09.py"), str(root), str(F1.PORT), str(prot), str(buch)], env=env)
    E: dict = {"produkt": str(root), "verzoegerung_s": float(verz), "austausch": []}
    try:
        time.sleep(1.0)
        if not L7.start(root, ev / "start.log"):
            return 3
        L7.req("PUT", "/api/config", {"scope": "user", "provider": "custom", "model": "f1-testmodell",
                                      "endpoint": f"http://127.0.0.1:{F1.PORT}/v1/chat/completions", "apiKey": "f1-testschluessel"})
        for i, text in enumerate(EINGABEN, 1):
            if i == 4:
                L7.stop()
                if not L7.start(root, ev / "start.log"):
                    return 3
            t0 = time.time()
            p, jp = L7.req("POST", "/api/kernel/puppet", {"sessionId": F1.SID, "figure": {"id": F1.J, "name": "Johann"}, "text": text,
                                                         "targetId": F1.M})   # wie auf dem Geraet: Mara ist die angesprochene Figur
            t1 = time.time()
            r = figurenzug(F1.M, text, ev, f"reaktion{i}", target=F1.J)
            t2 = time.time()
            z = F1.zustand(db)
            facts = [json.loads(j) for (j,) in L7.sql(db, "SELECT json FROM scene_facts WHERE session_id=? ORDER BY rowid", (F1.SID,))]
            mara = [f for f in facts if f.get("actorId") == F1.M and f.get("kind") in ("speech", "action")][-2:]
            E["austausch"].append({"nr": i, "neustart_davor": i == 4, "eingabe": text, "puppet": [p, jp.get("code"), jp.get("message")],
                                   "reaktion": [r["prepare"][0], r["formulate"][0], r["commit"][0], r["commit"][1]],
                                   "dauer_puppet_s": round(t1 - t0, 2), "dauer_reaktion_s": round(t2 - t1, 2), "dauer_gesamt_s": round(t2 - t0, 2),
                                   "fenster": [t0, t2], "mara_zustand": {k: z["mara_runtime"].get(k) for k in ("emotion", "intensity", "intent", "fear")},
                                   "mara_zu_johann": z["beziehung_zu_johann"].get(F1.M), "mara_akte": [(f.get("kind"), str(f.get("text"))[:80]) for f in mara]})
        L7.stop()
    finally:
        tm.terminate()
    calls = [json.loads(x) for x in prot.read_text().splitlines()] if prot.exists() else []
    for a in E["austausch"]:
        w = [c for c in calls if a["fenster"][0] <= c.get("t_start", 0) <= a["fenster"][1]]
        n: dict = {}
        for c in w:
            n[c["lesung"]] = n.get(c["lesung"], 0) + 1
        a["modellaufrufe"] = n
        a["modellaufrufe_summe"] = len(w)
        a["modellzeit_summe_s"] = round(sum(c["t_ende"] - c["t_start"] for c in w), 1)
    aus.write_text(json.dumps(E, indent=1, ensure_ascii=False) + "\n")
    for a in E["austausch"]:
        print(a["nr"], a["puppet"][0], a["reaktion"], a["dauer_gesamt_s"], "s", a["modellaufrufe_summe"], "Aufrufe", a["mara_zu_johann"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
