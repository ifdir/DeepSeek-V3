#!/usr/bin/env python3
"""Arbeitsstand 06 - Einwilligungskette am ECHTEN P25-Code (oder an Stage 06).

Kette je Fall:
  echte P25-Writer (create_session_proposition, append_session_turn_truth,
  append_session_fact) -> commit -> close -> neue Verbindung ->
  repos.get_session (P25-Hydration) -> drei Einwilligungsreader gemeinsam ->
  act_consent jeder Tat -> body_contact_state (Spiegel fuer den Folgeturn).
Dazu: fremde Session bleibt unberuehrt.

Laeuft NUR auf einer frisch entpackten Kopie (--root) und einer neuen
Temp-SQLite. Keine Original-DB, kein Mock, kein Modell.

Aufruf:  python3 -I probe_p25_consent_06.py --root <P25-Ordner> --output <json>
Exit 0 = Probe lief vollstaendig (Befunde stehen im JSON, ROT ist moeglich).
Exit 1 = Probe selbst gescheitert.
"""
from __future__ import annotations

import argparse
import json
import os
from contextlib import closing
from pathlib import Path
import sys
import tempfile
import traceback

J, M, G = "char_g7_johann", "char_g7_mara", "char_g7_gustav"   # Beruehrender, Beruehrte (Giver), Dritter
AT = "2026-11-07T12:00"
EXPIRED = {"art": "zeit", "start": "2026-11-01T12:00", "end": "2026-11-01T13:00"}
HAND_ACT = "Johann hält deine rechte Hand"
HAND_OK = "Du darfst meine rechte Hand halten"
KISS_ACT = "Johann küsst deine Wange"


def tt(i, speaker):
    return {"kind": "tt", "id": f"tt{i}", "role": "character", "authority": "character", "speaker_id": speaker,
            "present_ids": [J, M, G], "hears_ids": [x for x in (J, M, G) if x != speaker],
            "sees_ids": [x for x in (J, M, G) if x != speaker], "turn": i}


def lc(i, by, kind, scope, part=None, window=None, acts=None, text=None, prop="p", src=None):
    kk = {"scope": scope, "beleg": text or f"Antwort {i}"}
    if part is not None:
        kk["einschraenkung"] = part
    if window is not None:
        kk["window"] = window
    if acts:
        kk["actFactIds"] = list(acts)
    f = {"id": f"f{i}", "kind": "lifecycle", "event_kind": kind, "actorId": by, "targetId": J if by != J else M,
         "sourceTurnId": src or f"tt{i}", "turn": i, "validated": True, "text": text or f"Antwort {i}",
         "payload": {"koerperkontakt": kk}}
    if prop is not None:
        f["propositionId"] = prop
    return {"kind": "fact", "row": f}


def act(i, text, exception_of=None, words=None):
    eff = {}
    if exception_of is not None:
        eff["grenzBezug"] = [{"art": "ausnahme", "causeFactId": exception_of, "status": "validiert",
                              "teile": [{"wortlaut": words, "innerhalb": True}]}]
    return {"kind": "fact", "row": {"id": f"a{i}", "kind": "action", "actorId": J, "targetId": M,
                                    "sourceTurnId": f"tt{i}", "turn": i, "validated": True, "text": text,
                                    "effect": eff}}


def steps(*items):
    """TurnTruth des jeweiligen Sprechers vor jedem Fakt (§23, §34.1)."""
    out = []
    for it in items:
        row = it["row"]
        if row.get("sourceTurnId", "").startswith("tt") and row["sourceTurnId"] == f"tt{row['turn']}":
            out.append(tt(row["turn"], row["actorId"]))
        out.append(it)
    return out


# (id, beschreibung, schritte, soll)  soll: {"write": {factId: "OK"|"REJECT"}, "lesen": {...}}
CASES = [
    ("C04_FREMDER_GIVER", "Mara lehnt jede Beruehrung ab, Johann 'stimmt zu'",
     steps(lc(1, M, "refusal", "jede_beruehrung"), lc(2, J, "acceptance", "jede_beruehrung"), act(3, KISS_ACT)),
     {"lesen": {"state": "declined"}, "acts": {"a3": "declined"}, "write": {"f2": "REJECT"}}),
    ("C04_ABGELAUFENE_BREITE_ZUSTIMMUNG", "Mara lehnt ab, spaetere eigene Zustimmung ist abgelaufen",
     steps(lc(1, M, "refusal", "jede_beruehrung"), lc(2, M, "acceptance", "jede_beruehrung", window=EXPIRED)),
     {"lesen": {"state": "declined"}}),
    ("C04_ABGELAUFENE_EINZELABLEHNUNG", "Mara erlaubt rechte Hand, spaetere Ablehnung abgelaufen",
     steps(lc(1, M, "acceptance", "eingeschraenkt", "rechte Hand", text=HAND_OK),
           lc(2, M, "refusal", "eingeschraenkt", "rechte Hand", window=EXPIRED)),
     {"lesen": {"perms": ["rechte Hand"]}}),
    ("C04_ABGELAUFENE_EINZELZUSTIMMUNG", "Mara lehnt rechte Hand ab, spaetere Zustimmung abgelaufen",
     steps(lc(1, M, "refusal", "eingeschraenkt", "rechte Hand"),
           lc(2, M, "acceptance", "eingeschraenkt", "rechte Hand", window=EXPIRED, text=HAND_OK)),
     {"lesen": {"refs": ["rechte Hand"]}}),
    ("S05_WIDERRUF_DER_AUSNAHME", "Ablehnung jeder Beruehrung, Ausnahme rechte Hand, Widerruf an der Hand-Tat",
     steps(lc(1, M, "refusal", "jede_beruehrung"),
           lc(2, M, "acceptance", "eingeschraenkt", "rechte Hand", text=HAND_OK),
           act(3, HAND_ACT, "f2", "hält deine rechte Hand"),
           lc(4, M, "revoke", "diese_tat", acts=["a3"], text="Nein, nicht mehr"),
           act(5, HAND_ACT, "f2", "hält deine rechte Hand"),
           act(6, KISS_ACT)),
     {"lesen": {"state": "declined", "perms": []}, "acts": {"a5": "declined", "a6": "declined"}}),
    ("S05_ANDERE_STELLE", "Erlaubnis rechte Hand, Widerruf an einer Schulter-Tat",
     steps(lc(1, M, "acceptance", "eingeschraenkt", "rechte Hand", text=HAND_OK),
           act(2, "Johann berührt deine Schulter"),
           lc(3, M, "revoke", "diese_tat", acts=["a2"], text="Lass das"),
           act(4, HAND_ACT, "f1", "hält deine rechte Hand")),
     {"lesen": {"perms": ["rechte Hand"]}, "acts": {"a4": "accepted"}}),
    ("W2_ACTOR_NICHT_SPRECHER", "Ablehnung mit Actor Mara aus einer TurnTruth, in der Johann spricht",
     [tt(1, J), lc(1, M, "refusal", "jede_beruehrung")],
     {"write": {"f1": "REJECT"}}),
    ("W3_OHNE_PROPOSITION", "Koerperkontakt-Antwort ohne propositionId",
     steps(lc(1, M, "refusal", "jede_beruehrung", prop=None)),
     {"write": {"f1": "REJECT"}}),
    ("K_DRITTER_SPRECHER", "Kontrolle: Gustav (keine Partei) stimmt zu",
     steps(lc(1, M, "refusal", "jede_beruehrung"), lc(2, G, "acceptance", "jede_beruehrung")),
     {"write": {"f2": "REJECT"}, "lesen": {"state": "declined"}}),
    ("K_GUELTIGE_ABLEHNUNG", "Kontrolle: Mara lehnt jede Beruehrung ab, Kuss danach",
     steps(lc(1, M, "refusal", "jede_beruehrung"), act(2, KISS_ACT)),
     {"write": {"f1": "OK"}, "lesen": {"state": "declined"}, "acts": {"a2": "declined"}}),
]


def run_case(repos, sc, connect, init_schema, gid, case, tmp):
    cid, beschr, ablauf, soll = case
    db = Path(tmp) / f"{cid}.sqlite"
    acts_ids = [s["row"]["id"] for s in ablauf if s["kind"] == "fact" and s["row"]["kind"] == "action"]
    writes = {}
    with closing(connect(db)) as c:
        init_schema(c)
        for sid in ("sA", "sB"):
            repos.create_session(c, {"id": sid, "worldId": gid, "name": sid, "presentIds": [J, M, G]}, "admin")
        repos.create_session_proposition(c, "sA", {"id": "p", "kind": "koerperkontakt", "actorId": J, "targetId": M,
                                                  "state": "open", "evidence": []}, "admin")
        c.commit()
        for s in ablauf:
            try:
                if s["kind"] == "tt":
                    body = {k: v for k, v in s.items() if k != "kind"}
                    repos.append_session_turn_truth(c, "sA", body, "admin")
                else:
                    repos.append_session_fact(c, "sA", s["row"], "admin")
                    writes[s["row"]["id"]] = "OK"
                    if s["row"]["kind"] == "action":
                        # wie kernel._body_contact_matter: die Tat wird Evidenz der Koerperkontakt-Angelegenheit,
                        # ueber den echten Writer patch_session_proposition (V70: nur vorhandene Fakten)
                        cur = repos.get_session(c, "admin", "sA")
                        ev = next(p for p in cur["propositions"] if p.get("id") == "p").get("evidence") or []
                        repos.patch_session_proposition(c, "sA", "p", {"evidence": ev + [
                            {"kind": "act", "factId": s["row"]["id"], "by": J, "turn": s["row"]["turn"],
                             "text": s["row"]["text"]}]}, "admin")
                c.commit()
            except Exception as e:   # WriterError oder NativeBoundaryError: genau so messen
                c.rollback()
                if s["kind"] == "fact":
                    writes[s["row"]["id"]] = f"REJECT:{getattr(e, 'code', None) or getattr(e, 'error', None) or type(e).__name__}"
                else:
                    writes[s["id"]] = f"REJECT:{getattr(e, 'code', None) or type(e).__name__}"
    with closing(connect(db)) as c:
        s = repos.get_session(c, "admin", "sA")
        other = repos.get_session(c, "admin", "sB")
        prop = next(p for p in s.get("propositions") or [] if p.get("id") == "p")
        stored = sorted(f.get("id") for f in s.get("facts") or [])
        lesen, fehler = {}, None
        try:
            st = sc.body_contact_standing(s, prop, at=AT)
            lesen = {"state": st and st["state"],
                     "perms": [x["einschraenkung"] for x in sc.restricted_permissions_standing(s, prop, at=AT)],
                     "refs": [x["einschraenkung"] for x in sc.restricted_refusals_standing(s, prop, at=AT)]}
            facts = {f.get("id"): f for f in s.get("facts") or []}
            lesen["acts"] = {a: (sc.act_consent(s, facts[a]) or {}).get("state") for a in acts_ids if a in facts}
            mirror = sc.body_contact_state(s, prop, now=AT) or {}
            lesen["spiegel_state"] = mirror.get("state")
        except Exception as e:
            fehler = f"{type(e).__name__}:{getattr(e, 'code', '')}:{e}"
    befunde = []
    for fid, want in (soll.get("write") or {}).items():
        got = writes.get(fid, "NICHT_VERSUCHT")
        if not got.startswith(want):
            befunde.append(f"write {fid}: SOLL {want}, IST {got}")
    for k in ("state", "perms", "refs"):
        if k in (soll.get("lesen") or {}) and lesen.get(k) != soll["lesen"][k]:
            befunde.append(f"{k}: SOLL {soll['lesen'][k]}, IST {lesen.get(k)}")
    for a, want in (soll.get("acts") or {}).items():
        got = (lesen.get("acts") or {}).get(a)
        if got != want:
            befunde.append(f"act_consent {a}: SOLL {want}, IST {got}")
    if fehler:
        befunde.append(f"Lesen gescheitert: {fehler}")
    if lesen.get("state") is not None and lesen.get("spiegel_state") not in (lesen.get("state"),):
        befunde.append(f"Folgeturn-Spiegel {lesen.get('spiegel_state')} != Reader {lesen.get('state')}")
    if other.get("facts"):
        befunde.append(f"Isolation verletzt: fremde Session hat {len(other['facts'])} Fakten")
    return {"fall": cid, "beschreibung": beschr, "writes": writes, "gespeichert": stored, "lesen": lesen,
            "fremde_session_fakten": len(other.get("facts") or []), "befunde": befunde,
            "soll_erfuellt": not befunde}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    root = a.root.resolve()
    sys.path.insert(0, str(root))
    os.environ["MATRIX_SKIP_SEED"] = "0"
    os.environ.pop("PYTEST_CURRENT_TEST", None)
    try:
        from matrix_api.db import connect, init_schema, GASTHAUS_ID
        from matrix_api import repos, scene_state as sc
        out = []
        with tempfile.TemporaryDirectory(prefix="matrix06_probe_") as tmp:
            for case in CASES:
                out.append(run_case(repos, sc, connect, init_schema, GASTHAUS_ID, case, tmp))
    except Exception:
        traceback.print_exc()
        return 1
    report = {"label": a.label, "root": str(root), "rust_native": (root / "matrix_api/native").is_dir(),
              "faelle": out, "soll_erfuellt": sum(c["soll_erfuellt"] for c in out), "gesamt": len(out),
              "rot": [c["fall"] for c in out if not c["soll_erfuellt"]], "product_release": False}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for c in out:
        print(("OK  " if c["soll_erfuellt"] else "ROT ") + c["fall"] + ("" if c["soll_erfuellt"] else "  | " + " ; ".join(c["befunde"])))
    print(f"SOLL erfuellt {report['soll_erfuellt']}/{report['gesamt']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
