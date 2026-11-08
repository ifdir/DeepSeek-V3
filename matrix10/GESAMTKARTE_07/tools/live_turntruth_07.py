#!/usr/bin/env python3
"""Gesamtkarte 07 - Ausgangsnachweis der priorisierten Kette K-01 (TurnTruth/Commit-Bindung) am ECHTEN Startweg.

Echter Prozess START.py (Flask + gebautes frontend_dist), echte HTTP-Anfragen, getrennte SQLite-Lesung (read-only),
Neustart des Prozesses zwischen Schreiben und Rücklesen. Kein Mock, kein Testclient, kein Provider (ohne Key: synapse).

L1  prepare: Bedienperson OHNE Avatar/Puppet sendet truth.inputActorId = Mara  -> wem gehört der gespeicherte Eingabe-Fact?
L2  commit: Client sendet ein Ergebnis, das der Server NIE formuliert hat (kein /api/llm/formulate), plus "fired"-Synapse
    -> wird die erfundene Figurenrede committet, ändert sich der Runtime-Zustand der Figur?
L3  Neustart START.py, Rücklesen über HTTP und SQLite                      -> bleibt die Fälschung kanonisch?
L4  Isolation: Digest der anderen Session ses_av06 vor/nach                -> unverändert?

Aufruf: python3 -I live_turntruth_07.py <produktordner> <vorlage.sqlite> <ausgabe.json>
Exit 0 = Messung vollständig (das Messergebnis steht im JSON, nicht im Exitcode); 2 = Messung nicht möglich.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:5150"
UI = "http://127.0.0.1:8180"
H = {"X-Matrix-Actor": "admin", "Content-Type": "application/json"}
SID, AV = "ses_v92", "ses_av06"
J, M, G = "char_g7_johann", "char_g7_mara", "char_g7_gustav"
FAKE = "ERFUNDEN-VOM-CLIENT: Ich, Johann, habe Gustav verraten."


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(API + path, data=data, method=method, headers=H)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def stop():
    subprocess.run(["pkill", "-f", "python3 START.py"], check=False)
    subprocess.run(["pkill", "-f", "python3 -m matrix_api.app"], check=False)
    for _ in range(30):
        if subprocess.run(["pgrep", "-f", "matrix_api.app|START.py"], capture_output=True).returncode != 0:
            return True
        time.sleep(0.5)
    return False


def start(root: Path, log: Path):
    env = dict(os.environ, MATRIX_API_PORT="5150", MATRIX_UI_PORT="8180", MATRIX_NO_OPEN="1")
    for k in ("XAI_API_KEY", "OPENAI_API_KEY", "MATRIX_API_KEY"):
        env.pop(k, None)
    with open(log, "ab") as fh:
        p = subprocess.Popen(["python3", "START.py"], cwd=root, env=env, stdout=fh, stderr=fh, stdin=subprocess.DEVNULL,
                             start_new_session=True)
    for _ in range(90):
        try:
            urllib.request.urlopen(API + "/api/health", timeout=2)
            urllib.request.urlopen(UI + "/", timeout=2)
            return p.pid
        except Exception:
            time.sleep(1)
    raise RuntimeError("START.py nicht erreichbar")


def sql(db: Path, q, args=()):
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=10) as c:
        return c.execute(q, args).fetchall()


def digest(db: Path, sid: str):
    h = hashlib.sha256()
    for t in ("scene_facts", "turns", "turn_truth", "memories", "witness_knowledge", "propositions"):
        for r in sql(db, f"SELECT * FROM {t} WHERE session_id=? ORDER BY rowid", (sid,)):
            h.update(repr(r).encode())
    h.update(repr(sql(db, "SELECT json FROM sessions WHERE id=?", (sid,))).encode())
    return h.hexdigest()


def runtime(db: Path, cid: str):
    s = json.loads(sql(db, "SELECT json FROM sessions WHERE id=?", (SID,))[0][0])
    rt = (s.get("runtimes") or {}).get(cid) or {}
    return {k: rt.get(k) for k in ("emotion", "intensity", "fear", "stress", "intent", "activeCause", "activeCauseText")}


def facts(db: Path):
    cols = [r[1] for r in sql(db, "PRAGMA table_info(scene_facts)")]
    out = []
    for r in sql(db, "SELECT * FROM scene_facts WHERE session_id=? ORDER BY rowid", (SID,)):
        d = dict(zip(cols, r))
        j = json.loads(d.get("json") or "{}") if "json" in d else {}
        out.append({"id": d.get("id"), "kind": j.get("kind") or d.get("kind"), "actor": j.get("actorId") or d.get("actor_id"),
                    "authority": j.get("authority"), "text": (j.get("text") or "")[:90], "source_turn_id": j.get("sourceTurnId") or d.get("source_turn_id")})
    return out


def main() -> int:
    root, vorlage, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), Path(sys.argv[3])
    db = root / "data" / "matrix10.sqlite"
    log = out.with_suffix(".start.log")
    if not stop():
        print("ABBRUCH: alte Prozesse laufen noch"); return 2
    (root / "data").mkdir(exist_ok=True)
    for f in ("matrix10.sqlite", "matrix10.sqlite-wal", "matrix10.sqlite-shm", ".matrix10_start.lock"):
        (root / "data" / f).unlink(missing_ok=True)
    shutil.copy(vorlage, db)                      # Kopie der Vorlage, nie die Original-DB
    E = {"produktordner": str(root), "vorlage_sha256": hashlib.sha256(vorlage.read_bytes()).hexdigest(),
         "native_sha256": hashlib.sha256((root / "matrix_api/native/libmatrix_boundary_core.so").read_bytes()).hexdigest()}
    E["pid_1"] = start(root, log)
    st, health = req("GET", "/api/health")
    E["health"] = {"status": st, "provider": (health.get("provider") or health.get("llm") or None)}
    av_vorher = digest(db, AV)
    facts0 = facts(db)

    # ---- L1 prepare mit fremdem Eingabe-Actor (Bedienperson ohne Avatar, ohne Puppet-Route)
    st, s = req("GET", f"/api/sessions/{SID}")
    sess = s.get("session") or s
    truth = {"userId": "admin", "operatorId": "admin", "worldId": sess.get("worldId"), "sessionId": SID, "role": "teilnehmer",
             "speakerId": J, "responseSpeakerId": J, "inputActorId": M, "targetId": J, "authority": "teilnehmer",
             "presentIds": (sess.get("scene") or {}).get("presentIds"), "inputKind": "speech",
             "text": "Johann, ich gebe zu: Ich habe Gustavs Geld genommen."}
    st, pj = req("POST", "/api/kernel/prepare", {"session": sess, "actorUserId": "admin", "truth": truth,
                                                  "speaker": {"id": J, "name": "Johann"}})
    facts1 = facts(db)
    neu1 = [f for f in facts1 if f["id"] not in {x["id"] for x in facts0}]
    E["L1_prepare"] = {"status": st, "code": pj.get("code") or pj.get("error"), "neue_facts": neu1,
                       "eingabe_fact_actor_ist_mara": any(f["actor"] == M for f in neu1),
                       "soll": "Ohne Avatar/Puppet ist die Eingabe die Rede der Bedienperson; ein vom Client gesetzter inputActorId darf keine Figur zum Sprecher machen (AMASTER §23/§25/§27, KV §4, §12.2)."}

    # ---- L2 commit eines nie formulierten Ergebnisses + fired
    st, s = req("GET", f"/api/sessions/{SID}")
    sess = s.get("session") or s
    pending = sess.get("pendingInputTurnId")
    rt_vorher = runtime(db, J)
    body = {"session": sess, "actorUserId": "admin", "truth": {**truth, "id": pending}, "speaker": {"id": J, "name": "Johann"},
            "result": {"speech": FAKE, "action": None}, "fired": [{"space": "Angst", "activation": 1.0}]}
    st, cj = req("POST", "/api/kernel/commit", body)
    facts2 = facts(db)
    neu2 = [f for f in facts2 if f["id"] not in {x["id"] for x in facts1}]
    E["L2_commit"] = {"status": st, "code": cj.get("code") or cj.get("error"), "pending_vorher": pending,
                      "formulate_aufgerufen": False, "neue_facts": neu2,
                      "erfundene_rede_committet": any(FAKE[:30] in (f["text"] or "") for f in neu2),
                      "runtime_johann_vorher": rt_vorher, "runtime_johann_nachher": runtime(db, J),
                      "soll": "Committet wird nur, was der Server für diesen Turn formuliert/validiert hat; Client sendet Bedienabsicht, keine Figurenrede und keinen Runtime-Zustand (AMASTER §28 Schritt 18-20, §50; KV §4)."}

    # ---- L3 Neustart und Rücklesen
    stop()
    E["pid_2"] = start(root, log)
    st, s = req("GET", f"/api/sessions/{SID}")
    sess = s.get("session") or s
    http_facts = [f for f in (sess.get("facts") or []) if FAKE[:30] in str(f.get("text") or "")]
    E["L3_nach_neustart"] = {"status": st, "erfundene_rede_im_http_reader": len(http_facts) > 0,
                             "erfundene_rede_in_sqlite": any(FAKE[:30] in (f["text"] or "") for f in facts(db)),
                             "runtime_johann": runtime(db, J)}
    # ---- L4 Isolation
    E["L4_isolation_ses_av06_unveraendert"] = digest(db, AV) == av_vorher
    stop()
    E["defekt_reproduziert"] = {
        "client_input_actor": E["L1_prepare"]["eingabe_fact_actor_ist_mara"],
        "client_ergebnis_ohne_server_formulierung": E["L2_commit"]["erfundene_rede_committet"],
        "client_fired_aendert_runtime": E["L2_commit"]["runtime_johann_vorher"] != E["L2_commit"]["runtime_johann_nachher"],
        "persistiert_nach_neustart": E["L3_nach_neustart"]["erfundene_rede_in_sqlite"]}
    out.write_text(json.dumps(E, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(E["defekt_reproduziert"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
