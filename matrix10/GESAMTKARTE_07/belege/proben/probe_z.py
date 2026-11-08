import json, os, sys, tempfile
from contextlib import closing
from pathlib import Path
root = sys.argv[1]
sys.path.insert(0, root)
tmp = tempfile.mkdtemp(dir=sys.argv[2])
dbp = str(Path(tmp) / "t.sqlite")
os.environ["MATRIX_DB"] = dbp
os.environ["MATRIX_LIVE_LOG"] = str(Path(tmp) / "log.log")
os.environ.pop("MATRIX_SKIP_SEED", None)
from matrix_api.db import connect, init_schema
from matrix_api.seed_builtin import seed_if_missing
from matrix_api.repos import create_session, get_session

with closing(connect(dbp)) as c:
    init_schema(c); seed_if_missing(c)
    c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\"}')")
    ch = {json.loads(r[1])["name"]: json.loads(r[1]) for r in c.execute("select id,json from characters")}
    J = next(v for k, v in ch.items() if "Johann" in k); M = next(v for k, v in ch.items() if "Mara" in k)
    others = [v for k, v in ch.items() if v["id"] not in (J["id"], M["id"])]
    W = c.execute("select id from worlds limit 1").fetchone()[0]
    create_session(c, {"id": "ses_z", "worldId": W, "name": "Z", "presentIds": [J["id"], M["id"]], "avatarId": J["id"], "role": "teilnehmer"}, "admin")
    c.commit()

def sess():
    with closing(connect(dbp)) as c:
        return get_session(c, "admin", "ses_z")

from matrix_api import app as appmod
client = appmod.create_app(dbp).test_client()
H = {"X-Matrix-Actor": "admin"}

def turn(text, speech, action=None):
    s = sess()
    truth = {"userId": "admin", "operatorId": "admin", "worldId": s["worldId"], "sessionId": "ses_z", "role": "teilnehmer",
             "speakerId": M["id"], "responseSpeakerId": M["id"], "avatarId": J["id"], "inputActorId": J["id"], "speakAs": "avatar", "userName": J["name"], "targetId": M["id"],
             "authority": "teilnehmer", "presentIds": s["scene"]["presentIds"], "inputKind": "speech", "text": text}
    r = client.post("/api/kernel/prepare", headers=H, json={"session": s, "actorUserId": "admin", "truth": truth,
                    "speaker": {"id": M["id"], "name": M["name"]},
                    "present": [{"id": J["id"], "name": J["name"]}, {"id": M["id"], "name": M["name"]}]})
    pj = r.get_json() or {}
    print("PREPARE", r.status_code, (pj.get("code") or pj.get("error")), str(pj.get("message"))[:200])
    s = sess()
    tt = s.get("pendingInputTurnId")
    bc = pj.get("brainContext") or {}
    sp = pj.get("spiegel") or bc.get("spiegel") or {}
    print("  brain memories:", [ (m.get("kind"), m.get("text")[:60]) for m in (bc.get("memories") or [])][:8])
    print("  spiegel memories:", [ (m.get("kind"), m.get("text")[:60]) for m in (sp.get("memories") or [])][:8])
    print("  spiegel runtime:", {k: (sp.get("runtime") or {}).get(k) for k in ("emotion","trust","fear","intent")})
    print("  spiegel relations:", sp.get("relations"))
    body = {"session": s, "actorUserId": "admin", "truth": {**truth, "id": tt},
            "speaker": {"id": M["id"], "name": M["name"]}, "result": {"speech": speech, "action": action}}
    r = client.post("/api/kernel/commit", headers=H, json=body)
    cj = r.get_json() or {}
    print("COMMIT", r.status_code, cj.get("code") or cj.get("error"), str(cj.get("message"))[:300])

turn("Mara, ich habe gestern die Kasse geplündert und dich belogen.", "Das glaube ich dir nicht, Johann.")
s = sess()
print("AFTER T1 memories", [(m.get("characterId"), m.get("kind"), m.get("text")[:50]) for m in s.get("memories") or []])
print("AFTER T1 wk", [(w.get("character_id"), w.get("access")) for w in s.get("witnessKnowledge") or []])
print("AFTER T1 relations", [(r["fromId"],r["toId"],r.get("trust"),r.get("fear")) for r in s.get("relations") or [] if {r["fromId"],r["toId"]}=={J["id"],M["id"]}])
print("AFTER T1 runtimes", {k: {kk: v.get(kk) for kk in ("emotion","trust","fear","intent","affects")} for k, v in (s.get("runtimes") or {}).items()})
print("AFTER T1 frames", [(f.get("kind"), f.get("status"), f.get("what")) for f in s.get("frames") or []])
print("AFTER T1 props", [(p.get("kind"), p.get("status"), p.get("text")) for p in s.get("propositions") or []])
# "restart": new app instance, same DB
client = appmod.create_app(dbp).test_client()
turn("Was habe ich dir vorhin über die Kasse gesagt?", "Dass du sie geplündert hast.")
with closing(connect(dbp)) as c:
    for t in ("memories", "witness_knowledge", "relationships", "scene_facts", "propositions", "goals"):
        print("ROWS", t, c.execute(f"select count(*) from {t} where session_id='ses_z'").fetchone()[0])
