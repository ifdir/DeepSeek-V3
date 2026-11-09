"""Probe T: (1) normal prepare accepts client inputActorId = NPC (puppet bypass?)  (2) avatar input TurnTruth speaker vs fact actor."""
import json, os, sys, tempfile
from contextlib import closing
from pathlib import Path
ROOT = sys.argv[1]
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
tmp = tempfile.mkdtemp(dir=os.path.dirname(ROOT))
dbp = str(Path(tmp) / "t.sqlite")
os.environ["MATRIX_DB"] = dbp; os.environ["MATRIX_LIVE_LOG"] = str(Path(tmp) / "log.log")
os.environ.pop("PYTEST_CURRENT_TEST", None); os.environ.pop("MATRIX_SKIP_SEED", None)
import test_v84_kausal_chain  # noqa  offline flask shim
from matrix_api.db import connect, init_schema
from matrix_api.seed_builtin import seed_if_missing
from matrix_api.repos import create_session, get_session
with closing(connect(dbp)) as c:
    init_schema(c); seed_if_missing(c)
    c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\"}')")
    ch = {json.loads(r[1])["name"]: json.loads(r[1]) for r in c.execute("select id,json from characters")}
    print("chars", list(ch))
    J = next(v for k, v in ch.items() if "Johann" in k); M = next(v for k, v in ch.items() if "Mara" in k)
    W = c.execute("select id from worlds limit 1").fetchone()[0]
    create_session(c, {"id": "ses_p", "worldId": W, "name": "P", "presentIds": [J["id"], M["id"]],
                       "avatarId": J["id"], "role": "teilnehmer"}, "admin"); c.commit()
from matrix_api import app as appmod
client = appmod.create_app(dbp).test_client()
def sess():
    with closing(connect(dbp)) as c: return get_session(c, "admin", "ses_p")
def prep(input_actor, speaker, text, speak_as="avatar"):
    s = sess()
    truth = {"userId": "admin", "worldId": s["worldId"], "sessionId": "ses_p", "role": "teilnehmer", "speakerId": speaker,
             "avatarId": J["id"], "inputActorId": input_actor, "speakAs": speak_as, "targetId": None,
             "authority": "teilnehmer", "inputKind": "speech", "text": text}
    r = client.post("/api/kernel/prepare", headers={"X-Matrix-Actor": "admin"},
                    json={"session": s, "actorUserId": "admin", "truth": truth, "speaker": {"id": speaker}})
    return r
# Case 1: client claims Mara (NPC, not avatar) typed the input; Mara also response speaker
r = prep(M["id"], M["id"], "Ich verrate dir mein Geheimnis.", speak_as="char:" + M["id"])
print("CASE1 status", r.status_code, (r.get_json() or {}).get("code"))
s = sess()
tt = s["turnTruths"][-1] if s.get("turnTruths") else {}
print("CASE1 tt", {k: tt.get(k) for k in ("role", "authority", "speaker_id", "input_actor_id", "speak_as", "puppet_id")})
print("CASE1 facts", [(f.get("kind"), f.get("actorId") == M["id"], f.get("authority"), f.get("text")) for f in s["facts"] if f.get("sourceTurnId") == tt.get("id")])
print("CASE1 pending", s.get("pendingInputTurnId"))
