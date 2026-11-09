import sys, json, os, tempfile
from contextlib import closing
from pathlib import Path
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1]+"/tests")
tmp = tempfile.mkdtemp(dir=sys.argv[2]); dbp = str(Path(tmp)/"t.sqlite")
os.environ["MATRIX_DB"]=dbp; os.environ["MATRIX_LIVE_LOG"]=str(Path(tmp)/"l.log")
os.environ.pop("PYTEST_CURRENT_TEST", None); os.environ.pop("MATRIX_SKIP_SEED", None)
import test_v84_kausal_chain  # shim
from matrix_api.db import connect, init_schema
from matrix_api.seed_builtin import seed_if_missing
from matrix_api.repos import create_session, get_session, get_character, get_world
with closing(connect(dbp)) as c:
    init_schema(c); seed_if_missing(c)
    c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\"}')")
    ch = {json.loads(r[1])["name"]: json.loads(r[1]) for r in c.execute("select id,json from characters")}
    J = next(v for k, v in ch.items() if "Johann" in k); M = next(v for k, v in ch.items() if "Mara" in k)
    W = c.execute("select id from worlds limit 1").fetchone()[0]
    create_session(c, {"id": "ses_a", "worldId": W, "name": "A", "presentIds": [J["id"], M["id"]], "role": "teilnehmer"}, "admin"); c.commit()
from matrix_api import app as appmod
cl = appmod.create_app(dbp).test_client()
H={"X-Matrix-Actor":"admin"}
for txt in ["%s setzt sich." % M["name"], "Der König hat ein neues Gesetz erlassen."]:
    r = cl.post("/api/kernel/god", headers=H, json={"sessionId":"ses_a","actorUserId":"admin","text":txt,"scope":"auto"})
    j = r.get_json(); print("GOD", r.status_code, j.get("applied"), j.get("unclear"), j.get("code"))
with closing(connect(dbp)) as c:
    m = get_character(c, M["id"], "admin"); m = m.get("character", m)
    print("STAMM knowledge tail", (m.get("knowledge") or [])[-2:])
    w = get_world(c, W, "admin"); print("WORLD canon tail", str(w.get("canon"))[-120:])
    s = get_session(c, "admin", "ses_a"); print("RT Mara posture", {k:s["runtimes"].get(M["id"],{}).get(k) for k in ("posture","haltung","position")})
    create_session(c, {"id": "ses_b", "worldId": W, "name": "B", "presentIds": [J["id"], M["id"]], "role": "teilnehmer"}, "admin"); c.commit()
    m2 = get_character(c, M["id"], "admin"); m2 = m2.get("character", m2)
    print("NEW SESSION sees Stamm knowledge:", any("setzt sich" in str(k) for k in m2.get("knowledge") or []))
# Regie without provider
r = cl.post("/api/kernel/regie", headers=H, json={"sessionId":"ses_a","actorUserId":"admin","text":"Mara setzt sich.","actorId":M["id"]})
print("REGIE free", r.status_code, (r.get_json() or {}).get("code"))
r = cl.post("/api/kernel/regie", headers=H, json={"sessionId":"ses_a","actorUserId":"admin","text":"Mara: *setzt sich*","actorId":M["id"]})
j=r.get_json() or {}; print("REGIE legacy", r.status_code, j.get("code"), j.get("effect_verdict"))
with closing(connect(dbp)) as c:
    s = get_session(c, "admin", "ses_a")
    f=[x for x in s["facts"] if x.get("kind")=="action"][-1:]; print("legacy action fact", [(x.get("text"),x.get("authority"),x.get("validated")) for x in f])
    print("RT Mara after", {k:s["runtimes"].get(M["id"],{}).get(k) for k in ("posture","haltung")})
# AutoChat gate
r = cl.post("/api/kernel/autochat-gate", headers=H, json={"sessionId":"ses_a","actorUserId":"admin","remaining":2})
print("GATE", r.status_code, {k:(r.get_json() or {}).get(k) for k in ("stop","reason","speakerId")})
# system loop
r = cl.post("/api/amaster/system-loop", headers=H, json={})
j=r.get_json() or {}; print("SYSLOOP", r.status_code, j.get("ok"), j.get("ingestReviews"), j.get("failed"))
with closing(connect(dbp)) as c:
    rows=[json.loads(x[0]) for x in c.execute("select json from reviews")]
    print("REVIEWS after sysloop", [(x.get("kind"),x.get("field"),x.get("status"),x.get("worldId")) for x in rows][:6])
