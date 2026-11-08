#!/usr/bin/env python3
"""Stand 10 / Schritt A: F1-Restbefunde B3 (neue Grenze aus Figurenrede) und B4 (Abklingen bei fortbestehender Ursache)
messen - gleicher Weg wie F1 (START.py, HTTP-Routen der UI, Testmodell 'custom', Neustart), KEINE Produktaenderung.
Bausteine unveraendert aus ARBEITSSTAND_09/tools/f1_durchlauf_09.py (turn, zustand) und testmodell_f1_09.py.
Aufruf: python3 -I f1_rest_10.py <produktordner> <vorlage.sqlite> <evidence-ordner> [drehbuch.json]
Ausgabe: Messreihe je Zug (kein Urteil im Exit; Exit 0 = Messung gelaufen, 3 = nicht moeglich).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

HIER = Path(__file__).resolve().parent
T09 = HIER.parents[1] / "ARBEITSSTAND_09" / "tools"
sys.path.insert(0, str(T09))
import f1_durchlauf_09 as F1  # noqa: E402
L7 = F1.L7
FRAGEN = ["Mara, Johann steht noch neben dir. Was sagst du zu ihm?"] + \
         [f"Mara, Johann ist immer noch hier (Runde {i}). Was sagst du zu ihm?" for i in range(2, 7)]


def grenzen(db):
    out = []
    for (j,) in L7.sql(db, "SELECT json FROM scene_facts WHERE session_id=? ORDER BY rowid", (F1.SID,)):
        f = json.loads(j)
        if f.get("kind") == "lifecycle" or f.get("grenze") or (f.get("lifecycle") or {}):
            out.append({k: f.get(k) for k in ("id", "turn", "kind", "actorId", "targetId", "text", "grenze", "lifecycle")})
    return out


def main() -> int:
    root, vorlage, ev = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), Path(sys.argv[3]).resolve()
    buch = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else HIER / "drehbuch_f1_rest_10.json"
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
    tm = subprocess.Popen([sys.executable, "-I", str(T09 / "testmodell_f1_09.py"), str(root), str(F1.PORT), str(prot), str(buch)])
    E: dict = {"vorlage_sha256": hashlib.sha256(vorlage.read_bytes()).hexdigest(), "zuege": []}
    try:
        time.sleep(1.0)
        if not L7.start(root, ev / "start.log"):
            return 3
        L7.req("PUT", "/api/config", {"scope": "user", "provider": "custom", "model": "f1-testmodell",
                                      "endpoint": f"http://127.0.0.1:{F1.PORT}/v1/chat/completions", "apiKey": "f1-testschluessel"})
        E["vorher"] = F1.zustand(db)
        E["grenzen_vorher"] = grenzen(db)
        E["puppet"] = L7.req("POST", "/api/kernel/puppet", {"sessionId": F1.SID, "figure": {"id": F1.J, "name": "Johann"}, "text": F1.TAT})[0]
        E["nach_tat"] = F1.zustand(db)
        for i, frage in enumerate(FRAGEN, 1):
            if i == 3:
                L7.stop()
                if not L7.start(root, ev / "start.log"):
                    return 3
            t = F1.turn(frage, F1.M, ev, f"zug{i}")
            z = F1.zustand(db)
            E["zuege"].append({"zug": i, "neustart_davor": i == 3, "status": [t["prepare"][0], t["formulate"][0], t["commit"][0]],
                               "mara": {k: z["mara_runtime"].get(k) for k in ("emotion", "intensity", "pain", "fear", "intent")},
                               "affekte": [(a.get("type"), a.get("base"), a.get("targetId"), a.get("reinforcedTurn"))
                                           for a in z["mara_runtime"].get("affects") or []],
                               "beziehung": z["beziehung_zu_johann"].get(F1.M), "anwesend": F1.J in json.loads(
                                   L7.sql(db, "SELECT json FROM sessions WHERE id=?", (F1.SID,))[0][0]).get("scene", {}).get("presentIds", [])})
        E["grenzen_nachher"] = grenzen(db)
        L7.stop()
    finally:
        tm.terminate()
    calls = [json.loads(x) for x in prot.read_text().splitlines()] if prot.exists() else []
    E["grenze_im_brief"] = [next((x for x in c["user"].splitlines() if x.startswith("GRENZE")), None)
                            for c in calls if c["lesung"] == "FORMULIERUNG"]
    E["bewertung_ereignisse_je_aufruf"] = [len((json.loads(c["user"]).get("gerade_geschehen") or []))
                                           for c in calls if c["lesung"] == "APPRAISAL_RULES" and '"figur": "Mara Nowak"' in c["user"]]
    E["modellaufrufe"] = [[c["lesung"], c["nr"], c["geskriptet"]] for c in calls]
    (ev / "f1_rest_ergebnis.json").write_text(json.dumps(E, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in E.items() if k != "modellaufrufe"}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
