import sys, os, json, tempfile
from pathlib import Path
from contextlib import closing
ROOT=sys.argv[1]; sys.path.insert(0, ROOT)
tmp=tempfile.mkdtemp(dir=sys.argv[2]); dbp=str(Path(tmp)/"t.sqlite")
os.environ["MATRIX_DB"]=dbp; os.environ["MATRIX_LIVE_LOG"]=str(Path(tmp)/"log.log")
for k in ("OPENAI_API_KEY","XAI_API_KEY"): os.environ.pop(k,None)
from matrix_api.db import connect, init_schema
from matrix_api.seed_builtin import seed_if_missing
from matrix_api.repos import create_session, get_session, get_world
with closing(connect(dbp)) as c:
    init_schema(c); seed_if_missing(c)
    c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\"}')")
    W=c.execute("select id from worlds limit 1").fetchone()[0]
    ch={json.loads(r[1])["name"]: json.loads(r[1]) for r in c.execute("select id,json from characters")}
    J=next(v for k,v in ch.items() if "Johann" in k); M=next(v for k,v in ch.items() if "Mara" in k)
    create_session(c,{"id":"ses_p","worldId":W,"name":"P","presentIds":[J["id"],M["id"]],"role":"beobachter"},"admin"); c.commit()
from matrix_api import app as appmod
cl=appmod.create_app(dbp).test_client(); H={"X-Matrix-Actor":"admin"}; out={}
cl.put("/api/config",headers=H,json={"scope":"user","apiKey":"sk-GEHEIM-1234567890","provider":"openai","model":"gpt-x","temperature":0.3})
g=cl.get("/api/config?scope=session&scope_id=ses_p",headers=H).get_json()
out["session_scope_keyPresent"]=g.get("keyPresent"); out["session_scope_model"]=g.get("model")
cl.put("/api/config",headers=H,json={"scope":"session","scope_id":"ses_p","model":"gpt-session","temperature":1.2})
p=cl.post("/api/llm/ping",headers=H,json={"live":False,"scope":"session","scope_id":"ses_p"}).get_json()
out["ping_session_scope"]={k:p.get(k) for k in ("provider","model","keyPresent","keySource")}
p=cl.post("/api/llm/ping",headers=H,json={"live":False}).get_json()
out["ping_user_scope"]={k:p.get(k) for k in ("provider","model","keyPresent","keySource")}
cl.put("/api/config",headers=H,json={"scope":"user","clearApiKey":True,"provider":"synapse"})
# Mode A world review accept -> world write -> readback
cl.post("/api/uploads",headers=H,json={"id":"upload_a1","name":"welt.txt","mime":"text/plain","text":"Die Stadt Triest liegt am Meer. Im Hafen herrscht die Gilde der Schmuggler. Es gilt die Regel: Niemand betritt nachts den Leuchtturm.","mode":"A","targetKind":"world","targetId":W,"worldId":W})
j=cl.post("/api/uploads/upload_a1/ingest",headers=H,json={}).get_json()
revs=j.get("reviews") or []
out["reviews"]=[(r["field"],str(r["newValue"])[:60]) for r in revs]
with closing(connect(dbp)) as c:
    w0=get_world(c,W,"admin")
for r in revs:
    rr=cl.post(f"/api/reviews/{r['id']}/resolve",headers=H,json={"status":"accepted"})
    out.setdefault("resolve",[]).append((rr.status_code,rr.get_json().get("ok"),rr.get_json().get("committed")))
with closing(connect(dbp)) as c:
    w1=get_world(c,W,"admin")
    up=json.loads(c.execute("select json from uploads where id='upload_a1'").fetchone()[0])
out["world_changed_fields"]=[k for k in set(w0)|set(w1) if json.dumps(w0.get(k),sort_keys=True)!=json.dumps(w1.get(k),sort_keys=True)]
out["upload_after"]=(up.get("status"),up.get("committed"),up.get("reviewAccepted"))
# review accept with failing owner write -> status code
cl.post("/api/reviews",headers=H,json={"id":"review_x1","kind":"stamm","characterId":"char_nonexist","worldId":W,"field":"goals","newValue":"x","status":"open"})
rr=cl.post("/api/reviews/review_x1/resolve",headers=H,json={"status":"accepted"})
out["resolve_fail"]=(rr.status_code,rr.get_json().get("ok"),rr.get_json().get("error"))
# Mode B note priority
cl.post("/api/uploads",headers=H,json={"id":"upload_b2","name":"brief.txt","mime":"text/plain","text":"Der Brief sagt: Das Gold liegt unter der Treppe.","note":"bitte lesen","mode":"B","targetKind":"session","targetId":"ses_p","sessionId":"ses_p"})
cl.post("/api/uploads/upload_b2/ingest",headers=H,json={})
with closing(connect(dbp)) as c:
    s=get_session(c,"admin","ses_p")
    out["b2_mem_texts"]=[m.get("text") for m in s.get("memories") or [] if m.get("source")=="upload_b2"]
    out["b2_fact"]=[f.get("text") for f in s.get("facts") or [] if f.get("sourceUploadId")=="upload_b2"]
print(json.dumps(out,ensure_ascii=False,indent=1,default=str))
