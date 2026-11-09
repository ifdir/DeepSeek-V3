#!/usr/bin/env python3
"""Stand 08 / K-02: Live-Abnahme am echten Startweg (START.py, gebautes frontend_dist, Chromium), offline (Synapse).

Ablauf: Kopie der Vorlage-DB -> START.py -> Browser Phase 1 (Chat "Fall 06": Ereignis als Bedienperson; Mara und Gustav
anwesend, Robert nicht) -> SQLite read-only: wer hat welches Wissen -> echter Neustart -> Browser Phase 2 (Gedaechtnisseite:
Figurenabruf Mara, dann Robert) -> Antwortphase live: offene Eingabe, Gustav verlaesst die Szene, Wiederaufnahme ueber die
echten Routen -> Session-Trennung. Kein Modell-Nachweis.
Aufruf: python3 -I live_abnahme_k02_08.py <produktordner> <vorlage.sqlite> <evidence-ordner>
Exit 0 = alle Kriterien erfuellt, 2 = mindestens eines verletzt, 3 = Messung nicht moeglich.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parents[1] / "ARBEITSSTAND_07" / "tools"))
import live_abnahme_k01_07 as L7  # noqa: E402  (start/stop/req/sql/digest - unveraendert wiederverwendet)

SID, AV = "ses_v92", "ses_av06"
J, M, G, R = "char_g7_johann", "char_g7_mara", "char_g7_gustav", "char_g7_robert"


def mems(db, sid, cid):
    return [json.loads(j) for (j,) in L7.sql(db, "SELECT json FROM memories WHERE session_id=?", (sid,))
            if json.loads(j).get("characterId") == cid]


def node(phase, ev, extra):
    nodep = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    out = ev / f"L2_ui_phase{phase}.json"
    r = subprocess.run(["node", str(HIER / "live_ui_k02_08.cjs"), phase, str(out), str(ev / f"L2_ui_phase{phase}")] + extra,
                       capture_output=True, text=True, env=dict(os.environ, NODE_PATH=nodep), timeout=600)
    (ev / f"L2_ui_phase{phase}.log").write_text(r.stdout + r.stderr)
    return json.loads(out.read_text()) if out.exists() else {"fehler": (r.stdout + r.stderr)[-1500:]}


def main() -> int:
    root, vorlage, ev = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), Path(sys.argv[3])
    ev.mkdir(parents=True, exist_ok=True)
    db = root / "data" / "matrix10.sqlite"
    log = ev / "L2_start.log"
    if not L7.stop():
        return 3
    (root / "data").mkdir(exist_ok=True)
    for f in ("matrix10.sqlite", "matrix10.sqlite-wal", "matrix10.sqlite-shm"):
        (root / "data" / f).unlink(missing_ok=True)
    shutil.copy(vorlage, db)
    K: dict = {}
    E: dict = {"vorlage_sha256": hashlib.sha256(vorlage.read_bytes()).hexdigest(), "kriterien": K}
    if not L7.start(root, log):
        return 3
    av0 = L7.digest(db, AV)
    st = ev / "L2_storage_admin.json"
    p1 = node("1", ev, ["--storage-out", str(st)])
    E["phase1"] = p1.get("schritte")
    kasse = lambda cid: [m for m in mems(db, SID, cid) if "Kasse im Keller" in str(m.get("text") or "")]  # noqa: E731
    K["W1_anwesende_hoeren_das_ereignis_mara_gustav"] = bool(kasse(M)) and bool(kasse(G))
    K["W2_abwesender_robert_ohne_wissen"] = not kasse(R)
    K["W3_wissensart_gehoert_mit_zuschreibung"] = all(m.get("kind") == "gehoert" and "sagte:" in str(m.get("text")) for m in kasse(M))
    L7.stop()
    if not L7.start(root, log):
        return 3
    p2 = node("2", ev, ["--storage-in", str(st)])
    E["phase2"] = {"schritte": p2.get("schritte"), "mara": p2.get("mara_zeile"), "robert": p2.get("robert_zeile")}
    K["U1_gedaechtnisseite_kanonischer_abruf_mara_nach_neustart"] = "Kasse" in (p2.get("mara_zeile") or "") and "kanonisch" in (p2.get("mara_zeile") or "")
    K["U2_gedaechtnisseite_robert_keine_erinnerung"] = "keine Erinnerung" in (p2.get("robert_zeile") or "")
    K["U3_abruf_ueber_kernel_recall"] = bool(p2.get("recalls")) and all((x.get("res") or {}).get("engine") == "kernel.recall" for x in p2["recalls"])
    # ---- Antwortphase live (echte Routen gegen den laufenden Server)
    tr = {"userId": "admin", "sessionId": SID, "speakerId": J, "inputActorId": "user", "speakAs": "operator", "targetId": J,
          "inputKind": "speech", "text": "Johann, wo ist der Schluessel zum Keller?"}
    a, ja = L7.req("POST", "/api/kernel/prepare", {"sessionId": SID, "truth": tr, "speaker": {"id": J}})
    pend = (ja.get("session") or {}).get("pendingInputTurnId")
    pres = L7.req("POST", "/api/kernel/presence", {"sessionId": SID, "characterId": G})[0]
    b, jb = L7.req("POST", "/api/kernel/prepare", {"sessionId": SID, "truth": tr, "speaker": {"id": J}, "resumePending": {"turnTruthId": pend}})
    c, jc = L7.req("POST", "/api/llm/formulate", {"sessionId": SID, "sourceTurnId": (jb.get("truth") or {}).get("id"), "speakerId": J,
                                                  "text": tr["text"], "scope": "user", "inputKind": "speech", "provider": "synapse",
                                                  "turnBeleg": jb.get("turnBeleg")})
    res = jc.get("result") or {}
    d, jd = L7.req("POST", "/api/kernel/commit", {"sessionId": SID, "truth": jb.get("truth"), "speaker": {"id": J},
                                                  "result": {"speech": res.get("speech"), "action": res.get("action")},
                                                  "fired": ((jb.get("brainContext") or {}).get("spiegel") or {}).get("fired") or [],
                                                  "turnBeleg": jb.get("turnBeleg"), "formulierungsBeleg": jc.get("formulierungsBeleg")})
    E["antwortphase"] = {"prepare": a, "presence": pres, "wiederaufnahme": b, "formulate": c, "commit": [d, jd.get("code")]}
    ans = [json.loads(j) for (j,) in L7.sql(db, "SELECT json FROM scene_facts WHERE session_id=?", (SID,))]
    ans = [f for f in ans if f.get("sourceTurnId") == pend and f.get("actorId") == J and f.get("kind") == "speech"]
    fid = ans[0]["id"] if ans else None
    K["A1_antwort_committet"] = d == 200 and bool(fid)
    K["A2_gegangener_gustav_hoert_antwort_nicht"] = bool(fid) and not [m for m in mems(db, SID, G) if m.get("factId") == fid] \
        and not L7.sql(db, "SELECT 1 FROM witness_knowledge WHERE session_id=? AND character_id=? AND fact_id=?", (SID, G, fid))
    K["A3_anwesende_mara_hoert_antwort"] = bool(fid) and bool([m for m in mems(db, SID, M) if m.get("factId") == fid])
    K["I1_fremde_session_unveraendert"] = L7.digest(db, AV) == av0
    L7.stop()
    E["gesamt"] = "ERFUELLT" if all(K.values()) else "VERLETZT"
    (ev / "L2_abnahme_k02_08.json").write_text(json.dumps(E, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(K, indent=1, ensure_ascii=False))
    return 0 if all(K.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
