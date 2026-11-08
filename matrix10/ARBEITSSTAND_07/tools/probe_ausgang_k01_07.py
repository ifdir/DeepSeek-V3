#!/usr/bin/env python3
"""K-01 Ausgangsnachweis ohne Belege (laeuft auf jedem Stand): Hoerer-Rueckfall und Client-Synapsen.

H1  Hoerer ausdruecklich leer (UI-Route /api/kernel/perception) -> wer steht als Zeuge an der Figurenrede?
S1  commit mit result.proposals.synapsen (Angst 1.0) vom Client -> aendert sich der Runtime-Zustand der Figur?
S2  commit mit fired=[Angst 1.0] vom Client                      -> aendert sich der Runtime-Zustand der Figur?
Auf einem Stand MIT K-01 liefern S1/S2 eine Ablehnung (das ist dann das Ergebnis, keine Messung der Wirkung).
Aufruf: python3 -I probe_ausgang_k01_07.py <produktordner> <ausgabe.json>
"""
import json
import os
from contextlib import closing
from pathlib import Path
import sys
import tempfile

ROOT, OUT = sys.argv[1], Path(sys.argv[2])
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="k01aus_")
dbp = str(Path(tmp) / "t.sqlite")
os.environ["MATRIX_DB"] = dbp
os.environ["MATRIX_LIVE_LOG"] = str(Path(tmp) / "live.log")
for k in ("OPENAI_API_KEY", "XAI_API_KEY", "MATRIX_API_KEY"):
    os.environ.pop(k, None)
from matrix_api.db import connect, init_schema  # noqa: E402
from matrix_api.seed_builtin import seed_if_missing  # noqa: E402
from matrix_api.repos import create_session  # noqa: E402

with closing(connect(dbp)) as c:
    init_schema(c); seed_if_missing(c)
    c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\",\"name\":\"admin\"}')")
    ch = {json.loads(r[1])["name"]: json.loads(r[1]) for r in c.execute("select id,json from characters")}
    J = next(v for k, v in ch.items() if "Johann" in k)["id"]
    M = next(v for k, v in ch.items() if "Mara" in k)["id"]
    W = next(v for k, v in ch.items() if "Johann" in k)["worldId"]
    for sid in ("ses_h", "ses_s1", "ses_s2"):
        create_session(c, {"id": sid, "worldId": W, "name": sid, "presentIds": [J, M], "avatarId": None, "role": "teilnehmer"}, "admin")
    c.commit()
from matrix_api import app as appmod  # noqa: E402
cl = appmod.create_app(dbp).test_client()
H = {"X-Matrix-Actor": "admin"}
cl.put("/api/config", headers=H, json={"scope": "user", "provider": "synapse"})


def sess(sid):
    j = cl.get(f"/api/sessions/{sid}", headers=H).get_json()
    return j.get("session") or j


def turn(sid, text, result, fired=None):
    s = sess(sid)
    truth = {"userId": "admin", "worldId": s["worldId"], "sessionId": sid, "speakerId": J, "inputActorId": "user", "speakAs": "operator",
             "targetId": J, "presentIds": s["scene"]["presentIds"], "inputKind": "speech", "text": text}
    p = cl.post("/api/kernel/prepare", headers=H, json={"session": s, "truth": truth, "speaker": {"id": J}})
    pj = p.get_json() or {}
    if p.status_code != 200:
        return {"prepare": p.status_code, "code": pj.get("code")}
    body = {"session": pj["session"], "truth": pj["truth"], "speaker": {"id": J}, "result": result,
            "fired": fired if fired is not None else ((pj.get("brainContext") or {}).get("spiegel") or {}).get("fired") or [],
            **({"turnBeleg": pj["turnBeleg"]} if pj.get("turnBeleg") else {})}
    c = cl.post("/api/kernel/commit", headers=H, json=body)
    return {"prepare": 200, "commit": c.status_code, "code": (c.get_json() or {}).get("code"), "tt": pj["truth"]["id"]}


def rt(sid, cid):
    r = (sess(sid).get("runtimes") or {}).get(cid) or {}
    return {k: r.get(k) for k in ("emotion", "intensity", "fear", "stress", "intent", "activeCauseText")}


E = {"root": ROOT}
s = sess("ses_h")
E["H1_perception"] = cl.post("/api/kernel/perception", headers=H, json={"sessionId": "ses_h", "kind": "hearsIds", "ids": [], "explicit": True}).status_code
r = turn("ses_h", "Johann, ein Geheimnis.", {"speech": "Still, niemand darf es hoeren.", "action": None})
sp = [f for f in sess("ses_h").get("facts") or [] if f.get("sourceTurnId") == r.get("tt") and f.get("actorId") == J and f.get("kind") == "speech"]
_sh = sess("ses_h")
_fid = sp[0]["id"] if sp else None
_cl = [x for x in (_sh.get("claims") or []) if isinstance(x, dict) and x.get("factId") in (_fid,) or (isinstance(x, dict) and x.get("fact_id") == _fid)]
_fr = [x for x in (_sh.get("frames") or []) if isinstance(x, dict) and _fid and _fid in json.dumps(x)]
_wit = sorted({w for x in _cl + _fr for w in (x.get("witnesses") or [])})
E["H1"] = {**r, "hoerer_der_szene": (_sh.get("scene") or {}).get("hearsIds"), "hearsExplicit": (_sh.get("scene") or {}).get("hearsExplicit"),
           "fact_witnessedBy": (sp[0].get("witnessedBy") if sp else None), "claims": len(_cl), "frames": len(_fr),
           "claim_frame_zeugen": _wit,
           "mara_als_zeugin_trotz_leerer_hoererliste": M in _wit}
v = rt("ses_s1", J)
r = turn("ses_s1", "Johann?", {"speech": "Ja.", "action": None, "proposals": {"synapsen": [{"raum": "Angst", "aktivierung": 1.0, "grund": "client"}]}})
E["S1_proposals_synapsen"] = {**r, "runtime_vorher": v, "runtime_nachher": rt("ses_s1", J)}
E["S1_proposals_synapsen"]["runtime_geaendert"] = E["S1_proposals_synapsen"]["runtime_vorher"] != E["S1_proposals_synapsen"]["runtime_nachher"]
v = rt("ses_s2", J)
r = turn("ses_s2", "Johann?", {"speech": "Ja.", "action": None}, fired=[{"space": "Angst", "activation": 1.0}])
E["S2_fired"] = {**r, "runtime_vorher": v, "runtime_nachher": rt("ses_s2", J)}
E["S2_fired"]["runtime_geaendert"] = E["S2_fired"]["runtime_vorher"] != E["S2_fired"]["runtime_nachher"]
OUT.write_text(json.dumps(E, indent=2, ensure_ascii=False) + "\n")
print(json.dumps({k: (v if not isinstance(v, dict) else {x: v.get(x) for x in ("commit", "code", "runtime_geaendert", "mara_als_zeugin_trotz_leerer_hoererliste") if x in v}) for k, v in E.items()}, ensure_ascii=False))
