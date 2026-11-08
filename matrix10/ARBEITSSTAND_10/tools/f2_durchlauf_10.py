#!/usr/bin/env python3
"""F2-Durchlauf (Zielfaehigkeit F2, GESAMTKARTE_07/ZIELFAEHIGKEIT_F2.md): eigenstaendiges Handeln nach einem Erlebnis.

Gleicher Weg wie F1 (START.py, HTTP-Routen der UI, lokales Testmodell 'custom', Neustart), Bausteine aus
ARBEITSSTAND_09/tools/f1_durchlauf_09.py. Ablauf wie chat.$sessionId.tsx:
Puppet "Johann schlaegt Mara" -> Reaktionszug der Betroffenen (inputKind autochat, wie die UI nach Puppet)
-> AutoChat: /api/kernel/autochat-gate -> Folgezug (prepare autochat -> formulate -> commit)
-> Gegenprobe: Folgezug mit einer ANDEREN anwesenden Figur als der vom Server gewaehlten
-> echter Neustart -> Gate erneut.
Aufruf: python3 -I f2_durchlauf_10.py <produktordner> <vorlage.sqlite> <evidence-ordner> [drehbuch.json]
Exit 0 = F2 erfuellt, 2 = mindestens ein Glied verletzt, 3 = Messung nicht moeglich.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

HIER = Path(__file__).resolve().parent
T09 = HIER.parents[1] / "ARBEITSSTAND_09" / "tools"
sys.path.insert(0, str(T09))
import f1_durchlauf_09 as F1  # noqa: E402
L7 = F1.L7
SID, J, M, G = F1.SID, F1.J, F1.M, F1.G


def figurenzug(speaker, text, ev, tag, target=None):
    """Reaktions-/AutoChat-Zug wie runFigure(..., {inputKind: "autochat", speakAs: followAs(...)}) ohne autoPick."""
    tr = {"userId": "admin", "sessionId": SID, "speakerId": speaker, "inputActorId": "user", "speakAs": "operator",
          "targetId": target, "inputKind": "autochat", "text": text}
    a, ja = L7.req("POST", "/api/kernel/prepare", {"sessionId": SID, "truth": tr, "speaker": {"id": speaker}})
    gebunden = str(((ja.get("truth") or {}).get("speakerId")) or ((ja.get("truth") or {}).get("speaker_id")) or "")
    c, jc = L7.req("POST", "/api/llm/formulate", {"sessionId": SID, "sourceTurnId": (ja.get("truth") or {}).get("id"),
                                                  "speakerId": gebunden or speaker, "text": text, "scope": "user", "inputKind": "autochat",
                                                  "turnBeleg": ja.get("turnBeleg")})
    res = jc.get("result") or {}
    d, jd = L7.req("POST", "/api/kernel/commit", {"sessionId": SID, "truth": ja.get("truth"), "speaker": {"id": gebunden or speaker},
                                                  "result": {"speech": res.get("speech"), "action": res.get("action"),
                                                             **({"proposals": res["proposals"]} if res.get("proposals") else {})},
                                                  "fired": ((ja.get("brainContext") or {}).get("spiegel") or {}).get("fired") or [],
                                                  "turnBeleg": ja.get("turnBeleg"), "formulierungsBeleg": jc.get("formulierungsBeleg")})
    (ev / f"{tag}.json").write_text(json.dumps({"prepare": ja, "formulate": jc, "commit": jd}, indent=1, ensure_ascii=False)[:400000])
    return {"angefragt": speaker, "gebunden": gebunden, "prepare": [a, ja.get("code"), ja.get("message")],
            "formulate": [c, jc.get("code"), res.get("speech"), res.get("action")], "commit": [d, jd.get("code"), jd.get("message")]}


def gate(remaining):
    s, j = L7.req("POST", "/api/kernel/autochat-gate", {"sessionId": SID, "remaining": remaining, "stimulus": ""})
    return {"status": s, "stop": j.get("stop"), "reason": j.get("reason"), "speakerId": j.get("speakerId"),
            "kandidaten": [{"id": c.get("id"), "score": c.get("score"), "gruende": c.get("reasons")} for c in j.get("candidates") or []]}


def lage(db):
    s = json.loads(L7.sql(db, "SELECT json FROM sessions WHERE id=?", (SID,))[0][0])
    rt = s.get("runtimes") or {}
    facts = [json.loads(j) for (j,) in L7.sql(db, "SELECT json FROM scene_facts WHERE session_id=? ORDER BY rowid", (SID,))]
    return {"turnIndex": s.get("turnIndex"),
            "mara": {k: (rt.get(M) or {}).get(k) for k in ("position", "intent", "emotion", "heldBy", "holding")},
            "raum": (s.get("currentState") or {}).get("space") or (s.get("scene") or {}).get("contacts"),
            "figurenakte": [(f.get("turn"), f.get("kind"), f.get("actorId"), f.get("targetId"), str(f.get("text"))[:70],
                             (f.get("effect") or {}).get("wirkung")) for f in facts
                            if f.get("actorId") in (M, J, G) and f.get("kind") in ("speech", "action", "physical") and int(f.get("turn") or 0) >= 2]}


def main() -> int:
    root, vorlage, ev = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), Path(sys.argv[3]).resolve()
    buch = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else HIER / "drehbuch_f2_10.json"
    ev.mkdir(parents=True, exist_ok=True)
    prot = ev / "modellaufrufe.jsonl"
    prot.unlink(missing_ok=True)
    db = root / "data" / "matrix10.sqlite"
    if not L7.stop():
        return 3
    (root / "data").mkdir(exist_ok=True)
    for f in ("matrix10.sqlite", "matrix10.sqlite-wal", "matrix10.sqlite-shm"):
        (root / "data" / f).unlink(missing_ok=True)
    shutil.copy(vorlage, db)
    tm = subprocess.Popen([sys.executable, "-I", str(T09 / "testmodell_f1_09.py"), str(root), str(F1.PORT), str(prot), str(buch)])
    E: dict = {"vorlage_sha256": hashlib.sha256(vorlage.read_bytes()).hexdigest()}
    try:
        time.sleep(1.0)
        log = ev / "start.log"
        if not L7.start(root, log):
            return 3
        L7.req("PUT", "/api/config", {"scope": "user", "provider": "custom", "model": "f1-testmodell",
                                      "endpoint": f"http://127.0.0.1:{F1.PORT}/v1/chat/completions", "apiKey": "f1-testschluessel"})
        E["puppet"] = L7.req("POST", "/api/kernel/puppet", {"sessionId": SID, "figure": {"id": J, "name": "Johann"}, "text": F1.TAT})[0]
        E["nach_tat"] = lage(db)
        E["gate0_nach_tat"] = gate(1)   # was der Server nach der Tat waehlen wuerde (UI nimmt hier die Betroffene)
        # Reaktionszug der Betroffenen (UI: evidence.targetId -> responder, inputKind autochat, targetIdOverride = Puppet-Figur)
        E["reaktion_mara"] = figurenzug(M, "Johann schlägt Mara mit der Faust ins Gesicht", ev, "reaktion_mara", target=J)
        E["nach_reaktion"] = lage(db)
        E["gate1"] = g1 = gate(3)
        sp1 = g1.get("speakerId")
        fremd = next((x for x in (G, J, M) if x != sp1), None)
        E["gegenprobe_fremder_sprecher"] = figurenzug(fremd, "", ev, "gegenprobe_fremd")
        E["nach_gegenprobe"] = lage(db)
        E["autochat1"] = figurenzug(sp1, "", ev, "autochat1") if sp1 else None
        E["nach_autochat1"] = lage(db)
        L7.stop()
        if not L7.start(root, log):
            return 3
        E["nach_neustart"] = lage(db)
        E["gate2"] = gate(2)
        L7.stop()
    finally:
        tm.terminate()
    calls = [json.loads(x) for x in prot.read_text().splitlines()] if prot.exists() else []
    E["modellaufrufe"] = [[c["lesung"], c["nr"], c["geskriptet"]] for c in calls]
    E["kriterien"] = K = kriterien(E)
    E["gesamt"] = "F2 (Bindung) ERFUELLT (Kernel-Kette, Testmodell)" if all(K.values()) else "F2 VERLETZT"
    E["gate_log"] = [json.loads(x) for f in sorted((root / "logs").glob("*.log")) for x in f.read_text().splitlines()
                     if '"stage": "AUTOCHAT_GATE"' in x]
    (ev / "f2_ergebnis.json").write_text(json.dumps(E, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(E["kriterien"], indent=1, ensure_ascii=False))
    print(E["gesamt"])
    return 0 if all(E["kriterien"].values()) else 2


def kriterien(E):
    g0 = next((c for c in E["gate0_nach_tat"]["kandidaten"] if c["id"] == M), {})
    akt = [a for a in E["nach_reaktion"]["figurenakte"] if a[1] == "action" and a[2] == M]
    gp, ac = E["gegenprobe_fremder_sprecher"], E["autochat1"] or {}
    return {
        "F2_1_server_waehlt_nach_der_tat_die_betroffene_aus_ihrem_zustand": E["gate0_nach_tat"]["speakerId"] == M
            and "vom letzten Ereignis betroffen" in (g0.get("gruende") or []) and any(str(r).startswith("Druck") for r in g0.get("gruende") or []),
        "F2_2_reaktion_der_betroffenen_committet": E["reaktion_mara"]["commit"][0] == 200 and E["reaktion_mara"]["gebunden"] == M,
        "F2_3_absicht_wirkt_auf_handlung_entfernung_validiert": bool(akt) and (akt[0][5] or {}).get("art") == "entfernung"
            and ((akt[0][5] or {}).get("pruefung") or {}).get("bestaetigt") is True,
        "F2_4_fremder_sprecher_im_folgezug_abgewiesen_409": gp["prepare"][0] == 409 and gp["prepare"][1] == "AUTOCHAT_SPRECHER_NICHT_GEWAEHLT",
        "F2_5_abweisung_speichert_nichts": E["nach_gegenprobe"]["turnIndex"] == E["nach_reaktion"]["turnIndex"]
            and E["nach_gegenprobe"]["figurenakte"] == E["nach_reaktion"]["figurenakte"],
        "F2_6_gate_sprecher_spricht_im_folgezug": bool(ac) and ac.get("gebunden") == E["gate1"]["speakerId"] and ac["commit"][0] == 200,
        "F2_7_neustart_zustand_unveraendert_gate_entscheidet_weiter": E["nach_neustart"] == E["nach_autochat1"]
            and E["gate2"]["status"] == 200 and bool(E["gate2"]["speakerId"]),
    }


if __name__ == "__main__":
    raise SystemExit(main())
