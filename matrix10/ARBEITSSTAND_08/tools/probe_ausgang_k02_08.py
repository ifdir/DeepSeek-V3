#!/usr/bin/env python3
"""K-02 Ausgangsnachweis: Wahrnehmung der Figurenantwort (Antwortphase) ueber die echten Produktrouten.

Ablauf wie in der Oberflaeche: Eingabe an Johann (Mara und Gustav hoeren) -> Gustav verlaesst die Szene ("Anwesend",
/api/kernel/presence) -> "Antwort erneut erzeugen" (prepare resumePending -> /api/llm/formulate -> commit, K-01-Belege).
Gemessen: Wer ist Zeuge der ANTWORT (witnessedBy, witness_knowledge, Erinnerung "gehoert", Dialog im Spiegel)?
SOLL (AMASTER §26/§39): nur wer beim Antworten anwesend ist und hoert. Provider "synapse" (lokal, kein Netz).
Aufruf: python3 -I probe_ausgang_k02_08.py <produktordner> <ausgabe.json>
"""
import json
import os
from contextlib import closing
from pathlib import Path
import sys
import tempfile

ROOT, OUT = sys.argv[1], Path(sys.argv[2])
sys.path.insert(0, ROOT)
tmp = tempfile.mkdtemp(prefix="k02aus_")
dbp = str(Path(tmp) / "t.sqlite")
os.environ["MATRIX_DB"] = dbp
os.environ["MATRIX_LIVE_LOG"] = str(Path(tmp) / "live.log")
for k in ("OPENAI_API_KEY", "XAI_API_KEY", "MATRIX_API_KEY"):
    os.environ.pop(k, None)
from matrix_api.db import connect, init_schema  # noqa: E402
from matrix_api.seed_builtin import seed_if_missing  # noqa: E402
from matrix_api.repos import create_session  # noqa: E402

J, M, G = "char_g7_johann", "char_g7_mara", "char_g7_gustav"
with closing(connect(dbp)) as c:
    init_schema(c)
    seed_if_missing(c)
    c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\",\"name\":\"admin\"}')")
    W = c.execute("select world_id from characters where id=?", (J,)).fetchone()[0]
    create_session(c, {"id": "ses_k02", "worldId": W, "name": "K02", "presentIds": [J, M, G], "avatarId": None,
                       "role": "teilnehmer"}, "admin")
    c.commit()
from matrix_api import app as appmod  # noqa: E402
cl = appmod.create_app(dbp).test_client()
H = {"X-Matrix-Actor": "admin"}
cl.put("/api/config", headers=H, json={"scope": "user", "provider": "synapse"})


def sess():
    j = cl.get("/api/sessions/ses_k02", headers=H).get_json()
    return j.get("session") or j


def truth(text, kind="speech"):
    s = sess()
    return {"userId": "admin", "worldId": s["worldId"], "sessionId": "ses_k02", "speakerId": J, "inputActorId": "user",
            "speakAs": "operator", "targetId": J, "inputKind": kind, "text": text}


E = {"root": ROOT}
TEXT = "Johann, ich verrate dir ein Geheimnis: Die Kasse ist leer."
r = cl.post("/api/kernel/prepare", headers=H, json={"sessionId": "ses_k02", "truth": truth(TEXT), "speaker": {"id": J}})
E["1_prepare"] = r.status_code
pend = sess().get("pendingInputTurnId")
r = cl.post("/api/kernel/presence", headers=H, json={"sessionId": "ses_k02", "characterId": G})
E["2_gustav_verlaesst"] = [r.status_code, (r.get_json() or {}).get("code")]
E["2_anwesend_danach"] = (sess().get("scene") or {}).get("presentIds")
r = cl.post("/api/kernel/prepare", headers=H, json={"sessionId": "ses_k02", "truth": truth(TEXT), "speaker": {"id": J},
                                                    "resumePending": {"turnTruthId": pend}})
E["3_prepare_wiederaufnahme"] = [r.status_code, (r.get_json() or {}).get("code")]
pj = r.get_json() or {}
f = cl.post("/api/llm/formulate", headers=H, json={"sessionId": "ses_k02", "sourceTurnId": (pj.get("truth") or {}).get("id"),
                                                   "speakerId": J, "text": TEXT, "scope": "user", "inputKind": "speech",
                                                   "provider": "synapse", "turnBeleg": pj.get("turnBeleg")})
fj = f.get_json() or {}
E["4_formulate"] = f.status_code
res = fj.get("result") or {}
c = cl.post("/api/kernel/commit", headers=H, json={
    "sessionId": "ses_k02", "truth": pj.get("truth"), "speaker": {"id": J},
    "result": {"speech": res.get("speech"), "action": res.get("action")},
    "fired": ((pj.get("brainContext") or {}).get("spiegel") or {}).get("fired") or [],
    "turnBeleg": pj.get("turnBeleg"), "formulierungsBeleg": fj.get("formulierungsBeleg")})
E["5_commit"] = [c.status_code, (c.get_json() or {}).get("code")]
s = sess()
ans = [x for x in s.get("facts") or [] if x.get("sourceTurnId") == pend and x.get("actorId") == J and x.get("kind") == "speech"]
fid = ans[0]["id"] if ans else None
E["antwort"] = {"text": ans[0].get("text") if ans else None, "witnessedBy": ans[0].get("witnessedBy") if ans else None}
E["gustav_witness_rows_zur_antwort"] = [w.get("access") for w in s.get("witnessKnowledge") or []
                                        if w.get("character_id") == G and w.get("fact_id") == fid]
E["gustav_erinnerungen_zur_antwort"] = [m.get("text") for m in s.get("memories") or []
                                        if m.get("characterId") == G and m.get("factId") == fid]
E["mara_erinnerungen_zur_antwort"] = [m.get("text") for m in s.get("memories") or []
                                      if m.get("characterId") == M and m.get("factId") == fid]
from matrix_api import kernel  # noqa: E402
sp = kernel._dialogue_visible_to(s, G, s.get("turns") or [])
E["gustav_dialog_sieht_antwort"] = any((d.get("speech") or "") == E["antwort"]["text"] for d in sp)
E["defekt_gustav_als_zeuge_der_antwort"] = bool(E["gustav_witness_rows_zur_antwort"] or E["gustav_erinnerungen_zur_antwort"]
                                                or G in (E["antwort"]["witnessedBy"] or []) or E["gustav_dialog_sieht_antwort"])
E["kontrolle_mara_hoert_antwort"] = bool(E["mara_erinnerungen_zur_antwort"])
OUT.write_text(json.dumps(E, indent=2, ensure_ascii=False) + "\n")
print(json.dumps({k: E[k] for k in ("1_prepare", "2_gustav_verlaesst", "2_anwesend_danach", "3_prepare_wiederaufnahme", "4_formulate",
                                    "5_commit", "gustav_witness_rows_zur_antwort", "gustav_erinnerungen_zur_antwort",
                                    "gustav_dialog_sieht_antwort", "defekt_gustav_als_zeuge_der_antwort",
                                    "kontrolle_mara_hoert_antwort")}, ensure_ascii=False, indent=1))
