#!/usr/bin/env python3
"""Arbeitsstand 06, Stufe D3 (Plan K2/K2a): Fehlerkette Rust-Einwilligungskern -> P25-API.

Je Anfrage wird gemessen:
  - erreicht:  wurde die native Grenze (native_boundary._load) in dieser Anfrage aufgerufen?
               Zaehl-Wrapper reicht unveraendert durch, er ist kein Mock.
  - HTTP-Status, JSON-Code, ob eine Erfolgsmeldung entstand (2xx und ok:true),
  - SQLite-Digest der Session vorher/nachher (kein Commit = unveraendert).

Echte P25-App (create_app) ueber den Flask-Testclient, frische Temp-SQLite mit P25-Seed.
Das LLM wird wie in den P25-eigenen Routentests ueber deren FakeProvider ersetzt
(tests/test_v92_puppet_vertrag.py); das ist nur Transportersatz fuer die Modelllesung.

Varianten (je eigener Prozess):  ok | fehlt (matrix_api/native entfernt) | abi2 (ABI-2-Bibliothek)

Aufruf: python3 -I probe_http_503_06.py --root <Stage> --variante ok|fehlt|abi2 [--abi2-lib <so>] --output <json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from contextlib import closing
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request
from unittest.mock import patch

J, M, G = "char_g7_johann", "char_g7_mara", "char_g7_gustav"
SID = "ses_v92"
TABLES = ("scene_facts", "turns", "propositions", "turn_truth", "sessions", "memories", "witness_knowledge", "god_facts")


def digest(conn, sid):
    h = hashlib.sha256()
    for table in TABLES:
        col = "id" if table == "sessions" else "session_id"
        try:
            rows = conn.execute(f"SELECT * FROM {table} WHERE {col}=? ORDER BY rowid", (sid,)).fetchall()
        except Exception as e:
            rows = [("TABELLE_FEHLT", table, type(e).__name__)]
        for r in rows:
            h.update(repr(tuple(r)).encode())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--variante", choices=("ok", "fehlt", "abi2"), required=True)
    ap.add_argument("--abi2-lib", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="matrix06_http_"))
    root = work / "produkt"
    shutil.copytree(a.root, root, ignore=shutil.ignore_patterns("target", "node_modules", "__pycache__", "dist"))
    native = root / "matrix_api" / "native"
    if a.variante == "fehlt":
        shutil.rmtree(native, ignore_errors=True)
    elif a.variante == "abi2":
        shutil.copy2(a.abi2_lib, native / "libmatrix_boundary_core.so")
    sys.path[:0] = [str(root), str(root / "tests")]
    os.environ.pop("PYTEST_CURRENT_TEST", None)
    os.environ.pop("MATRIX_SKIP_SEED", None)
    dbp = str(work / "t.sqlite")
    os.environ["MATRIX_DB"] = dbp
    os.environ["MATRIX_LIVE_LOG"] = str(work / "live.log")

    from matrix_api.db import connect, init_schema
    from matrix_api.seed_builtin import seed_if_missing
    from matrix_api import repos
    from test_v92_puppet_vertrag import FakeProvider, plan, comp      # P25-eigene Provider-Attrappe
    with closing(connect(dbp)) as c:
        init_schema(c)
        seed_if_missing(c)
        c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\"}')")
        c.execute("INSERT INTO config(scope,scope_id,json) VALUES(?,?,?)", ("user", "admin", json.dumps(
            {"scope": "user", "scope_id": "admin", "provider": "openai", "model": "t", "apiKey": "sk-TESTONLY",
             "endpoint": "http://127.0.0.1:9/v1/chat/completions"})))
        w = c.execute("select world_id from characters where id=?", (M,)).fetchone()[0]
        repos.create_session(c, {"id": SID, "worldId": w, "name": "Fall 06", "presentIds": [J, M, G]}, "admin")
        # Ausgangslage: Mara hat jede Beruehrung durch Johann abgelehnt (echter Writer, Turn 0)
        repos.create_session_proposition(c, SID, {"id": "p_kk", "kind": "koerperkontakt", "actorId": J, "targetId": M,
                                                 "state": "open", "evidence": []}, "admin")
        repos.append_session_turn_truth(c, SID, {"id": "tt0", "role": "character", "authority": "character", "speaker_id": M,
                                                 "present_ids": [J, M, G], "hears_ids": [J, G], "sees_ids": [J, G], "turn": 0}, "admin")
        repos.append_session_fact(c, SID, {"id": "f0", "kind": "lifecycle", "event_kind": "refusal", "actorId": M, "targetId": J,
                                           "sourceTurnId": "tt0", "propositionId": "p_kk", "turn": 0, "validated": True,
                                           "text": "Fass mich nicht an", "payload": {"koerperkontakt": {
                                               "scope": "jede_beruehrung", "beleg": "Fass mich nicht an"}}}, "admin")
        c.commit()

    from matrix_api import app as appmod
    from matrix_api import native_boundary as nb
    zaehler = {"n": 0}
    _orig_load = nb._load

    def _zaehlend_load():
        zaehler["n"] += 1
        return _orig_load()
    nb._load = _zaehlend_load
    cl = appmod.create_app(dbp).test_client()
    H = {"X-Matrix-Actor": "admin"}

    def session():
        with closing(connect(dbp)) as c:
            return repos.get_session(c, "admin", SID)

    def post(path, body, prov=None):
        with patch.object(urllib.request, "urlopen", prov or FakeProvider([])):
            return cl.post(path, headers=H, json={"sessionId": SID, "actorUserId": "admin", **body})

    def puppet_act():
        prov = FakeProvider([plan("action", "act", [dict(comp("handlung", "Johann streichelt Mara", "zaertlich"))])])
        with patch.object(urllib.request, "urlopen", prov):
            # nur sessionId: die Route laedt den Stand selbst aus SQLite (_kernel_stored_session). Ein Sitzungs-Blob
            # wuerde im Pruefprozess ueber get_session schon VOR der Anfrage am Kern scheitern (gemessen) - dann
            # waere nicht die Route gemessen, sondern das Messwerkzeug.
            return cl.post("/api/kernel/puppet", headers=H, json={
                "sessionId": SID, "actorUserId": "admin",
                "figure": {"id": J, "name": "Johann Bruckner"}, "text": "Johann streichelt Mara", "targetId": M})

    def regie_act():
        def analyse(p):
            seg = p["anweisung"].rstrip(".")
            return {"komponenten": [{"typ": "handlung", "akteur": "Johann Bruckner", "ziel": "Mara Nowak", "segment": seg,
                                     "beschreibung": seg, "wirkung": "zaertlich"}], "unklar": []}
        return post("/api/kernel/regie", {"text": "Johann streichelt Mara.", "actorId": J}, FakeProvider([], regie=analyse))

    anfragen = [
        ("POST /api/kernel/puppet (Johann streichelt Mara)", puppet_act),
        ("POST /api/kernel/regie (Johann streichelt Mara)", regie_act),
        ("POST /api/kernel/god (Koerper Mara)", lambda: post("/api/kernel/god", {
            "text": "Mara hat starke Schmerzen.", "scope": "body", "targetId": M},
            FakeProvider([], gott=lambda p: {"schmerz": "stark", "beleg": "starke Schmerzen"}))),
        ("POST /api/kernel/presence", lambda: post("/api/kernel/presence", {"characterId": G})),
        ("POST /api/kernel/perception", lambda: post("/api/kernel/perception", {"kind": "seesIds", "ids": [J, M]})),
        ("POST /api/kernel/move", lambda: post("/api/kernel/move", {"placeId": "kueche", "moverId": G})),
        ("POST /api/kernel/fate", lambda: post("/api/kernel/fate", {})),
        ("GET /api/sessions/<id>", lambda: cl.get(f"/api/sessions/{SID}", headers=H)),
    ]
    out = []
    for name, call in anfragen:
        with closing(connect(dbp)) as c:
            vorher = digest(c, SID)
        n0 = zaehler["n"]
        try:
            r = call()
            status, j = r.status_code, (r.get_json(silent=True) or {})
        except Exception as e:   # Testclient leitet nicht abgefangene Ausnahmen weiter, wenn PROPAGATE aktiv ist
            import traceback
            tb = [f"{fr.filename.rsplit('/', 2)[-1]}:{fr.lineno}:{fr.name}" for fr in traceback.extract_tb(e.__traceback__)]
            status, j = None, {"code": f"AUSNAHME:{type(e).__name__}", "message": str(e), "ort": tb[:14]}
        with closing(connect(dbp)) as c:
            nachher = digest(c, SID)
        out.append({"anfrage": name, "erreicht_native_grenze": zaehler["n"] > n0, "status": status,
                    "code": j.get("code") or j.get("error"), "erfolgsmeldung": bool(status and 200 <= status < 300 and j.get("ok") is True),
                    "sqlite_unveraendert": vorher == nachher, "meldung": str(j.get("message") or "")[:200],
                    **({"ausnahme_ort": j["ort"]} if j.get("ort") else {})})
    report = {"variante": a.variante, "anfragen": out}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for o in out:
        print(f"[{a.variante:5}] {o['anfrage'][:45]:45} erreicht={str(o['erreicht_native_grenze']):5} HTTP {o['status']} "
              f"{o['code']} erfolg={o['erfolgsmeldung']} sqlite_unv={o['sqlite_unveraendert']}")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
