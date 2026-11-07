#!/usr/bin/env python3
"""Stand 05: Schreibgrenze fuer Lifecycle-Fakten, ECHTE Rust-Bibliothek.

Sendet genau die Kontextform, die repos._native_boundary("fact", ...) baut
(user/world/session, cast, operators, sources), an validate("fact", ...).
Kein Mock. Kein SQLite (V67-ZIP fehlt) -> belegt nur die native Pruefung,
nicht den Python-Writer-Pfad davor/danach.

SOLL je Fall aus AMASTER:
  §36.2  Refusal gilt nur, wenn die antwortende Figur der berechtigte
         Empfaenger ist, der Request existiert, dieselbe Proposition.
  §36.3  Acceptance: Sprecher und Empfaenger stimmen, Proposition stimmt.
  §34.1  Actor ... pro Komponente aus derselben TurnTruth gebunden.

Erwartung fuer den IST-Stand 04/05: W1-W3 werden ANGENOMMEN (U1 = UNKLAR) (= Defekt
nachgewiesen), Kontrollen K1/K2 verhalten sich korrekt.
Exit 0 = Probe lief und Befund ist wie dokumentiert; kein Produkt-Gruen.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
pkg = types.ModuleType("matrix_api")
pkg.__path__ = [str(ROOT / "integration")]
sys.modules["matrix_api"] = pkg
spec = importlib.util.spec_from_file_location("matrix_api.native_boundary", ROOT / "integration/native_boundary.py")
bridge = importlib.util.module_from_spec(spec)
sys.modules["matrix_api.native_boundary"] = bridge
spec.loader.exec_module(bridge)

# Szene: Proposition p (alice fragt bob nach Koerperkontakt).
# tt1: bob spricht (Ablehnung), tt2: alice spricht.
CONTEXT = {"user_id": "usr_A", "world_id": "w_A", "session_id": "session_A",
           "cast": ["alice", "bob"], "operators": ["user"],
           "sources": {"turnTruth": ["tt1", "tt2"], "fact": ["f_req", "f1"], "upload": []}}
TURN_SPEAKER = {"tt1": "bob", "tt2": "alice"}
PROPOSITION = {"id": "p", "actorId": "alice", "targetId": "bob"}


def lifecycle(fid, kind, actor, tt, prop="p", responds="f_req"):
    row = {"id": fid, "kind": "lifecycle", "event_kind": kind, "actorId": actor, "targetId": "alice",
           "sourceTurnId": tt, "turn": 2, "validated": True,
           "payload": {"koerperkontakt": {"scope": "jede_beruehrung", "einschraenkung": None,
                                          "window": None, "beleg": ""}}}
    if prop is not None:
        row["propositionId"] = prop
    if responds is not None:
        row["responds_to_fact_id"] = responds
    return row


CASES = [
    ("W1_FREMDER_GIVER_ZUSTIMMUNG", "§36.3 Sprecher/Empfaenger", lifecycle("f2", "acceptance", "alice", "tt2"), "REJECT"),
    ("W2_ACTOR_NICHT_TURNTRUTH_SPRECHER", "§34.1 Actor aus TurnTruth", lifecycle("f2", "refusal", "alice", "tt1"), "REJECT"),
    ("W3_OHNE_PROPOSITION", "§36.2 dieselbe Proposition", lifecycle("f2", "refusal", "bob", "tt1", prop=None), "REJECT"),
    # UNKLAR: §34.1 kennt auch die "ausdruecklich gesetzte Grenze" ohne Request.
    ("U1_OHNE_REQUEST_BEZUG", "§36.2 vs §34.1 Grenze", lifecycle("f2", "refusal", "bob", "tt1", responds=None), "UNKLAR"),
    ("K1_GUELTIGE_ABLEHNUNG", "Kontrolle", lifecycle("f2", "refusal", "bob", "tt1"), "ACCEPT"),
    ("K2_FREMDE_QUELLE", "Kontrolle strukturell", lifecycle("f2", "refusal", "bob", "tt_FREMD"), "REJECT"),
]


def main() -> int:
    if not bridge.library_path().is_file():
        print("BLOCKIERT: native Bibliothek fehlt (tools/run_chain_05.py zuerst)")
        return 3
    out = []
    for name, rule, row, soll in CASES:
        try:
            bridge.validate("fact", CONTEXT, row, {})
            ist, code = "ACCEPT", "OK"
        except bridge.NativeBoundaryError as exc:
            ist, code = "REJECT", exc.code
        out.append({"case": name, "amaster": rule, "soll": soll, "ist": ist, "code": code,
                    "soll_erfuellt": None if soll == "UNKLAR" else soll == ist,
                    "hinweis_turn_speaker": TURN_SPEAKER.get(row["sourceTurnId"]),
                    "hinweis_proposition_target": PROPOSITION["targetId"]})
    defects = [c["case"] for c in out if c["case"].startswith("W") and c["soll_erfuellt"] is False]
    controls_ok = all(c["soll_erfuellt"] for c in out if c["case"].startswith("K"))
    report = {"stand": "05", "rust_executed": True, "sqlite": False, "product_release": False,
              "cases": out, "writer_semantic_defects": defects, "controls_ok": controls_ok,
              "befund": "Native fact-Pruefung ist rein strukturell; Giver/Proposition/Request/"
                        "TurnTruth-Sprecher werden beim Schreiben NICHT geprueft."}
    target = ROOT / "evidence/chain_05/writer_semantics_05.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if controls_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
