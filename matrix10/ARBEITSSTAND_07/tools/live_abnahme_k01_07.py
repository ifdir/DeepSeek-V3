#!/usr/bin/env python3
"""Stand 07 / K-01 + SEC: Live-Abnahme am echten Startweg (START.py, gebautes frontend_dist, Chromium), offline.

Ablauf: Kopie der Vorlage-DB -> START.py -> Browser Phase 1 (Nutzer, Konfiguration "Nur lokale Synapse", Chat "Fall 06",
senden als Bedienperson, "Figuren jetzt weiterreden lassen") -> SQLite read-only pruefen -> START.py beenden und NEU starten
(gleiche DB) -> Browser Phase 2 (Neuladen: Verlauf sichtbar, erneut senden = Folgeturn) -> gefaelschte Anfragen gegen den
laufenden Server (fremder Eingabe-Actor, erfundene Figurenrede, gefaelschtes fired) -> Isolation -> Schluessel-Leck.
Kein Modell: Provider "synapse" (lokale Formulierung) - KEIN Modell-Live-Beleg (bleibt BLOCKIERT).
Aufruf: python3 -I live_abnahme_k01_07.py <produktordner mit frontend_dist + Rust-Lib> <vorlage.sqlite> <evidence-ordner>
Exit 0 = alle Kriterien erfuellt, 2 = mindestens ein Kriterium verletzt, 3 = Messung nicht moeglich.
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

API, UI = "http://127.0.0.1:5150", "http://127.0.0.1:8180"
H = {"X-Matrix-Actor": "admin", "Content-Type": "application/json"}
TOOLS6 = Path(__file__).resolve().parents[2] / "ARBEITSSTAND_06" / "tools"
HIER = Path(__file__).resolve().parent
SID, AV = "ses_v92", "ses_av06"
J, M = "char_g7_johann", "char_g7_mara"
SCHLUESSEL = "sk-TESTONLY"


def req(method, path, body=None):
    r = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=H)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def start(root: Path, log: Path):
    env = dict(os.environ, MATRIX_API_PORT="5150", MATRIX_UI_PORT="8180", MATRIX_NO_OPEN="1")
    for k in ("XAI_API_KEY", "OPENAI_API_KEY", "MATRIX_API_KEY"):
        env.pop(k, None)
    for f in (".matrix10_start.lock",):
        (root / "data" / f).unlink(missing_ok=True)
    with open(log, "ab") as fh:
        subprocess.Popen(["python3", "START.py"], cwd=root, env=env, stdout=fh, stderr=fh, stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(90):
        try:
            urllib.request.urlopen(API + "/api/health", timeout=2)
            urllib.request.urlopen(UI + "/", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def stop():
    return subprocess.run(["bash", str(TOOLS6 / "ui_stop.sh")], capture_output=True, text=True).returncode == 0


def sql(db, q, a=()):
    with sqlite3.connect(Path(db).as_uri() + "?mode=ro", uri=True, timeout=10) as c:
        return c.execute(q, a).fetchall()


def facts(db, sid):
    out = []
    for (j,) in sql(db, "SELECT json FROM scene_facts WHERE session_id=? ORDER BY rowid", (sid,)):
        f = json.loads(j)
        out.append({k: f.get(k) for k in ("id", "kind", "actorId", "targetId", "text", "sourceTurnId", "authority")})
    return out


def digest(db, sid):
    h = hashlib.sha256()
    for t in ("scene_facts", "turns", "turn_truth", "memories", "witness_knowledge", "propositions"):
        for r in sql(db, f"SELECT * FROM {t} WHERE session_id=? ORDER BY rowid", (sid,)):
            h.update(repr(r).encode())
    h.update(repr(sql(db, "SELECT json FROM sessions WHERE id=?", (sid,))).encode())
    return h.hexdigest()


def node(phase, ev, extra):
    nodep = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    out = ev / f"L_ui_phase{phase}.json"
    r = subprocess.run(["node", str(HIER / "live_ui_k01_07.cjs"), phase, str(out), str(ev / f"L_ui_phase{phase}")] + extra,
                       capture_output=True, text=True, env=dict(os.environ, NODE_PATH=nodep), timeout=600)
    (ev / f"L_ui_phase{phase}.log").write_text(r.stdout + r.stderr)
    return json.loads(out.read_text()) if out.exists() else {"fehler": (r.stdout + r.stderr)[-1500:]}


def main() -> int:
    root, vorlage, ev = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), Path(sys.argv[3])
    ev.mkdir(parents=True, exist_ok=True)
    db = root / "data" / "matrix10.sqlite"
    log = ev / "L_start.log"
    if not stop():
        return 3
    (root / "data").mkdir(exist_ok=True)
    for f in ("matrix10.sqlite", "matrix10.sqlite-wal", "matrix10.sqlite-shm"):
        (root / "data" / f).unlink(missing_ok=True)
    shutil.copy(vorlage, db)
    K: dict = {}
    E: dict = {"vorlage_sha256": hashlib.sha256(vorlage.read_bytes()).hexdigest(), "kriterien": K}
    if not start(root, log):
        return 3
    av0 = digest(db, AV)
    f0 = {f["id"] for f in facts(db, SID)}
    st = ev / "L_storage_admin.json"
    p1 = node("1", ev, ["--storage-out", str(st)])
    E["phase1"] = {"schritte": p1.get("schritte"), "api": p1.get("api")}
    commits = [c for c in (p1.get("bodies") or {}).get("commit", []) if c.get("status") == 200]
    forms = (p1.get("bodies") or {}).get("formulate", [])
    neu = [f for f in facts(db, SID) if f["id"] not in f0]
    K["L1_ui_commit_200_turn_und_weiterreden"] = len(commits) >= 2
    t1 = (commits[0]["req"] or {}).get("truth", {}).get("id") if commits else None
    inp = [f for f in neu if f["sourceTurnId"] == t1 and f["kind"] == "speech" and f["actorId"] == "user"]
    fig = [f for f in neu if f["sourceTurnId"] == t1 and f["kind"] == "speech" and f["actorId"] not in ("user", None)]
    srv = [((x.get("res") or {}).get("result") or {}).get("speech") for x in forms if x.get("status") == 200]
    K["L2_eingabe_actor_bedienperson_user"] = len(inp) == 1
    K["L3_figurenrede_ist_servertext"] = bool(fig) and fig[0]["text"] in srv
    K["L4_ui_zeigt_figurenrede"] = bool(fig) and fig[0]["text"][:30] in (p1.get("sichtbar") or "")
    E["phase1_neue_facts"] = neu
    # ---- echter Neustart (gleiche DB), Phase 2
    stop()
    if not start(root, log):
        return 3
    p2 = node("2", ev, ["--storage-in", str(st)])
    E["phase2"] = {"schritte": p2.get("schritte"), "api": p2.get("api")}
    K["L5_verlauf_nach_neustart_sichtbar"] = bool(fig) and fig[0]["text"][:30] in (p2.get("sichtbar_nach_neustart") or "")
    c2 = [c for c in (p2.get("bodies") or {}).get("commit", []) if c.get("status") == 200]
    K["L6_folgeturn_nach_neustart_commit_200"] = len(c2) >= 1
    pr2 = [x for x in (p2.get("bodies") or {}).get("prepare", []) if x.get("status") == 200]
    K["L7_folgeturn_liest_erste_figurenrede"] = bool(fig) and any(fig[0]["text"][:25] in json.dumps(x.get("res") or {}, ensure_ascii=False) for x in pr2)
    # ---- gefaelschte Anfragen gegen den laufenden Server
    vorher = digest(db, SID)
    st_s, s = req("GET", f"/api/sessions/{SID}")
    sess = s.get("session") or s
    truth = {"userId": "admin", "sessionId": SID, "speakerId": J, "inputActorId": M, "speakAs": "operator", "targetId": J,
             "inputKind": "speech", "text": "Johann, ich gebe zu: Ich habe Gustavs Geld genommen."}
    a, ja = req("POST", "/api/kernel/prepare", {"session": sess, "truth": truth, "speaker": {"id": J}})
    b, jb = req("POST", "/api/kernel/commit", {"session": sess, "truth": {**truth, "inputActorId": "user"}, "speaker": {"id": J},
                                               "result": {"speech": "ERFUNDEN-VOM-CLIENT: Ich habe Gustav verraten.", "action": None},
                                               "fired": [{"space": "Angst", "activation": 1.0}]})
    E["negativ"] = {"prepare_fremder_actor": [a, ja.get("code")], "commit_erfunden": [b, jb.get("code")]}
    K["N1_fremder_eingabe_actor_422"] = a == 422 and ja.get("code") == "EINGABE_ACTOR_UNGEBUNDEN"
    K["N2_erfundene_figurenrede_abgewiesen"] = b in (409, 422)
    K["N3_sqlite_unveraendert_nach_faelschung"] = digest(db, SID) == vorher
    K["N4_fremde_session_unveraendert"] = digest(db, AV) == av0
    texte = [x.get("text") or "" for x in (p1.get("bodies") or {}).get("mcc", []) + (p2.get("bodies") or {}).get("mcc", [])]
    K["S1_kein_schluessel_in_mcc"] = bool(texte) and not any(SCHLUESSEL in t for t in texte)
    K["S2_kein_schluessel_im_browserzustand"] = SCHLUESSEL not in (p1.get("localStorage") or "") + (p2.get("localStorage") or "")
    K["S3_kein_schluessel_in_logs"] = SCHLUESSEL not in json.dumps(req("GET", "/api/logs")[1])
    stop()
    E["gesamt"] = "ERFUELLT" if all(K.values()) else "VERLETZT"
    (ev / "L_abnahme_k01_07.json").write_text(json.dumps(E, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(K, indent=1, ensure_ascii=False))
    return 0 if all(K.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
