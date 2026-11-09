import sys, os, json, tempfile
from pathlib import Path
from contextlib import closing
ROOT = sys.argv[1]
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(dir=sys.argv[2])
dbp = str(Path(tmp)/"t.sqlite")
os.environ["MATRIX_DB"] = dbp
os.environ["MATRIX_LIVE_LOG"] = str(Path(tmp)/"log.log")
for k in ("OPENAI_API_KEY","XAI_API_KEY"): os.environ.pop(k, None)
from matrix_api.db import connect, init_schema
from matrix_api.seed_builtin import seed_if_missing
from matrix_api.repos import create_session, get_session
with closing(connect(dbp)) as c:
    init_schema(c); seed_if_missing(c)
    c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\"}')")
    ch = {json.loads(r[1])["name"]: json.loads(r[1]) for r in c.execute("select id,json from characters")}
    names = list(ch)
    W = c.execute("select id from worlds limit 1").fetchone()[0]
    J = next(v for k,v in ch.items() if "Johann" in k); M = next(v for k,v in ch.items() if "Mara" in k)
    others = [v for k,v in ch.items() if v["id"] not in (J["id"],M["id"]) and v.get("worldId")==W]
    create_session(c, {"id":"ses_p","worldId":W,"name":"P","presentIds":[J["id"],M["id"]],"avatarId":None,"role":"beobachter"}, "admin"); c.commit()
from matrix_api import app as appmod
cl = appmod.create_app(dbp).test_client()
H={"X-Matrix-Actor":"admin"}
out={}
# 1 config key leak through /api/mcc
r=cl.put("/api/config",headers=H,json={"scope":"user","apiKey":"sk-GEHEIM-1234567890","provider":"openai","model":"x"})
out["put_config"]=r.status_code
m=cl.get("/api/mcc",headers=H).get_json()
out["mcc_config_apiKey"]=m.get("config",{}).get("apiKey")
out["mcc_blob_config_apiKey"]=((m.get("blob") or {}).get("config") or {}).get("apiKey")
g=cl.get("/api/config?scope=user",headers=H).get_json()
out["get_config_has_plain"]= "sk-GEHEIM" in json.dumps(g)
# remove key to avoid network
cl.put("/api/config",headers=H,json={"scope":"user","clearApiKey":True,"provider":"synapse","model":"x"})
# 2 ingest failure returns 200 ok:false
r=cl.post("/api/uploads",headers=H,json={"id":"upload_f1","name":"leer.txt","mime":"text/plain","text":"   ","mode":"B","targetKind":"session","targetId":"ses_p","sessionId":"ses_p"})
out["create_upload_empty"]=(r.status_code, r.get_json().get("error"))
ri=cl.post("/api/uploads/upload_f1/ingest",headers=H,json={})
out["ingest_empty"]=(ri.status_code, ri.get_json().get("ok"), ri.get_json().get("error"))
# 3 Mode B with explicit character target: distribution to whom?
r=cl.post("/api/uploads",headers=H,json={"id":"upload_b1","name":"krimi.txt","mime":"text/plain","text":"Ein Krimi ueber einen Mord im Hafen von Triest. Der Kommissar ermittelt.","mode":"B","targetKind":"character","targetId":M["id"],"characterId":M["id"],"sessionId":"ses_p","worldId":W})
out["create_upload_b1"]=r.status_code
ri=cl.post("/api/uploads/upload_b1/ingest",headers=H,json={})
j=ri.get_json()
out["ingest_b1"]=(ri.status_code,j.get("ok"),j.get("witnessIds"),j.get("error"),j.get("message"))
out["target_char"]=M["id"]; out["J"]=J["id"]
with closing(connect(dbp)) as c:
    s=get_session(c,"admin","ses_p")
    out["wk"]=[(w.get("characterId") or w.get("character_id"), w.get("access")) for w in s.get("witnessKnowledge") or []]
    out["mems"]=[(x.get("characterId"),x.get("kind"),x.get("source")) for x in s.get("memories") or [] if x.get("source")=="upload_b1"]
    out["upload_row"]=json.loads(c.execute("select json from uploads where id='upload_b1'").fetchone()[0]).get("status")
# 4 Mode A world: status after ingest
r=cl.post("/api/uploads",headers=H,json={"id":"upload_a1","name":"welt.txt","mime":"text/plain","text":"Die Stadt Triest liegt am Meer. Im Hafen herrscht die Gilde der Schmuggler. Johann Bruckner ist Kapitaen.","mode":"A","targetKind":"world","targetId":W,"worldId":W})
ri=cl.post("/api/uploads/upload_a1/ingest",headers=H,json={})
j=ri.get_json()
out["ingest_a1"]=(ri.status_code,j.get("ok"),j.get("status"),len(j.get("reviews") or []),j.get("committed"))
# 5 Mode A without target
r=cl.post("/api/uploads",headers=H,json={"id":"upload_a0","name":"x.txt","mime":"text/plain","text":"Text hier vorhanden.","mode":"A"})
ri=cl.post("/api/uploads/upload_a0/ingest",headers=H,json={})
out["ingest_a0"]=(ri.status_code,ri.get_json().get("error"))
# 6 commit route bypass: mode A commit without review
rc=cl.post("/api/uploads/upload_a0/commit",headers=H,json={})
out["commit_route_a0"]=(rc.status_code, (rc.get_json().get("upload") or {}).get("status"))
# 7 search structured: document with group and article
cl.post("/api/documents",headers=H,json={"id":"document_d1","title":"Katalog","text":"Folie 3: Artikelnummer 123 Hammer","documentGroup":"Werkzeug"})
s1=cl.post("/api/search",headers=H,json={"q":"Wo ist die Folie mit Artikelnummer 123?"}).get_json()
out["search_art"]=s1.get("hits")[:3]
s2=cl.post("/api/search",headers=H,json={"q":"Werkzeug"}).get_json()
out["search_group"]=[h for h in s2.get("hits") if h["id"]=="document_d1"]
s3=cl.post("/api/search",headers=H,json={"q":"Hamer"}).get_json()
out["search_typo"]=[h for h in s3.get("hits") if h["id"]=="document_d1"]
s4=cl.post("/api/document-index/search",headers=H,json={"q":"werkzeug"}).get_json()
out["docindex_group"]=len(s4.get("hits"))
# 8 security: path / type
r=cl.post("/api/uploads",headers=H,json={"id":"upload_s1","name":"../../etc/passwd","mime":"text/plain","text":"x","mode":"B","sessionId":"ses_p"})
out["sec_path"]=(r.status_code,r.get_json().get("error"))
r=cl.post("/api/uploads",headers=H,json={"id":"upload_s2","name":"a.exe","mime":"application/x-msdownload","text":"x","mode":"B","sessionId":"ses_p"})
out["sec_exe"]=(r.status_code,r.get_json().get("error"))
r=cl.post("/api/documents",headers=H,json={"id":"document_s3","name":"a.exe","title":"../x","text":"x"})
out["sec_doc_exe"]=r.status_code
# 9 foreign user
cl.post("/api/users",headers={"X-Matrix-Actor":"u2"},json={"id":"u2","name":"U2"})
r=cl.get("/api/uploads/upload_b1",headers={"X-Matrix-Actor":"u2"})
out["foreign_get_upload"]=r.status_code
r=cl.get("/api/documents/document_d1",headers={"X-Matrix-Actor":"u2"})
out["foreign_get_doc"]=r.status_code
s=cl.post("/api/search",headers={"X-Matrix-Actor":"u2"},json={"q":"Hammer"}).get_json()
out["foreign_search"]=[h for h in s.get("hits") if h["id"]=="document_d1"]
# 10 speech stubs
out["stt"]=cl.post("/api/speech/stt",headers=H,json={}).get_json()
out["tts"]=cl.post("/api/speech/tts",headers=H,json={"text":"Hallo"}).get_json()
# 11 put mcc
out["put_mcc"]=cl.put("/api/mcc",headers=H,json={}).status_code
# 12 resolve review owner write failure status code
print(json.dumps(out,ensure_ascii=False,indent=1,default=str))
