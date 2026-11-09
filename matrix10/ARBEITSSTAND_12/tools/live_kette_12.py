#!/usr/bin/env python3
"""Stand 12: Live-Kettenlauf mit ECHTEM Modell (gpt-4o-mini, Schluessel aus deiner DB-Kopie) ueber den echten Weg wie die UI.
Szenario = deine Geraetesitzung 09.11. 11:07 (Gasthaus zum siebten Kreis, Johann + Mara): Sitzung auf der KOPIE zurueckgesetzt
(chat, runtime, memory), dann 3 Puppet-Eingaben als Johann -> Reaktionszug Mara (inputKind autochat wie chat.$sessionId.tsx),
danach 3 AutoChat-Zuege ohne neue Eingabe (autochat-gate -> Sprecher des Servers -> prepare/formulate/commit).
Modellaufrufe laufen ueber zaehler_12.py (unveraendert weitergeleitet, gezaehlt). Der Schluessel wird nie ausgegeben.
Aufruf: python3 -I live_kette_12.py <produktordner> <nutzer.sqlite> <ausgabeordner>
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parents[1] / "ARBEITSSTAND_07" / "tools"))
import live_abnahme_k01_07 as L7  # noqa: E402

SID = "ses_709ec2dd2ccc20f2b1c9a3b4"
J, M = "char_g7_johann", "char_g7_mara"
EINGABEN = ["Hey süsse, ich klarsche dir auf deinen Arsch", "Ach komm stell dich nicht so an",
            "Ich greife unter dein tshirt und lach dich an"]
AUTOCHAT = 3
ZPORT = 5191


def figurenzug(speaker, ev, tag, target=None):
    tr = {"userId": "admin", "sessionId": SID, "speakerId": speaker, "inputActorId": "user", "speakAs": "operator",
          "targetId": target, "inputKind": "autochat", "text": "", "roleOverride": "teilnehmer"}
    a, ja = L7.req("POST", "/api/kernel/prepare", {"sessionId": SID, "truth": tr, "speaker": {"id": speaker}})
    spk = str(((ja.get("truth") or {}).get("speaker_id")) or ((ja.get("truth") or {}).get("speakerId")) or speaker)
    c, jc = L7.req("POST", "/api/llm/formulate", {"sessionId": SID, "sourceTurnId": (ja.get("truth") or {}).get("id"), "speakerId": spk,
                                                  "turnIndex": (ja.get("session") or {}).get("turnIndex"), "text": "", "scope": "user",
                                                  "inputKind": "autochat", "turnBeleg": ja.get("turnBeleg")})
    res = jc.get("result") or {}
    d, jd = L7.req("POST", "/api/kernel/commit", {"sessionId": SID, "truth": ja.get("truth"), "speaker": {"id": spk},
                                                  "result": {"speech": res.get("speech"), "action": res.get("action"),
                                                             **({"proposals": res["proposals"]} if res.get("proposals") else {})},
                                                  "fired": ((ja.get("brainContext") or {}).get("spiegel") or {}).get("fired") or [],
                                                  "turnBeleg": ja.get("turnBeleg"), "formulierungsBeleg": jc.get("formulierungsBeleg")})
    (ev / f"{tag}.json").write_text(json.dumps({"prepare": ja, "formulate": jc, "commit": jd}, indent=1, ensure_ascii=False)[:600000])
    return {"sprecher": spk, "status": [a, c, d], "code": [ja.get("code"), jc.get("code"), jd.get("code")],
            "meldung": [ja.get("message"), jc.get("message"), jd.get("message")], "speech": res.get("speech"), "action": res.get("action"),
            "quelle": res.get("source") or jc.get("source")}


def zustand(db):
    with sqlite3.connect(Path(db).as_uri() + "?mode=ro", uri=True) as c:
        s = json.loads(c.execute("SELECT json FROM sessions WHERE id=?", (SID,)).fetchone()[0])
    rt = ((s.get("runtimes") or {}).get(M)) or {}
    rel = None
    for r in (s.get("relations") or s.get("relationships") or []):
        if isinstance(r, dict) and r.get("from") == M and r.get("to") == J:
            rel = {k: r.get(k) for k in ("trust", "closeness", "fear")}
    return {"emotion": rt.get("emotion"), "intensity": rt.get("intensity"), "intent": rt.get("intent"), "fear": rt.get("fear"),
            "anger": rt.get("anger"), "stress": rt.get("stress"), "position": rt.get("position"),
            "affekte": [[a.get("type"), a.get("intensity"), a.get("targetId")] for a in (rt.get("affects") or []) if isinstance(a, dict)],
            "beziehung": rel or (rt.get("relations") or {}).get(J), "turnIndex": s.get("turnIndex")}


def main() -> int:
    root, nutzer, aus = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    aus.mkdir(parents=True, exist_ok=True)
    prot = aus / "modellaufrufe.jsonl"
    prot.unlink(missing_ok=True)
    if not L7.stop():
        return 3
    data = root / "data"
    data.mkdir(exist_ok=True)
    for f in ("matrix10.sqlite", "matrix10.sqlite-wal", "matrix10.sqlite-shm"):
        (data / f).unlink(missing_ok=True)
    db = data / "matrix10.sqlite"
    shutil.copy(nutzer, db)
    if (nutzer.parent / ".matrix10_db_initialized").exists():
        shutil.copy(nutzer.parent / ".matrix10_db_initialized", data / ".matrix10_db_initialized")
    with sqlite3.connect(db) as c:   # nur die KOPIE: Endpoint auf die Zaehl-Weiterleitung (Schluessel bleibt unberuehrt)
        sc, si, j = c.execute("SELECT scope, scope_id, json FROM config WHERE scope='user'").fetchone()
        d = json.loads(j)
        d["endpoint"] = f"http://127.0.0.1:{ZPORT}/api.openai.com/v1/chat/completions"
        c.execute("UPDATE config SET json=? WHERE scope=? AND scope_id=?", (json.dumps(d), sc, si))
    zp = subprocess.Popen([sys.executable, "-I", str(HIER / "zaehler_12.py"), str(ZPORT), str(prot)])
    E: dict = {"produkt": str(root), "sitzung": SID, "schritte": []}
    try:
        time.sleep(0.8)
        if not L7.start(root, aus / "start.log"):
            return 3
        for kind in ("chat", "runtime", "memory"):
            st, jr = L7.req("POST", "/api/kernel/reset", {"userId": "admin", "sessionId": SID, "kind": kind})
            E.setdefault("reset", []).append([kind, st, jr.get("code")])
        E["start_zustand"] = zustand(db)
        for i, text in enumerate(EINGABEN, 1):
            t0 = time.time()
            p, jp = L7.req("POST", "/api/kernel/puppet", {"sessionId": SID, "figure": {"id": J, "name": "Johann"}, "text": text,
                                                         "targetId": M})
            t1 = time.time()
            r = figurenzug(M, aus, f"eingabe{i}_reaktion", target=J)
            t2 = time.time()
            E["schritte"].append({"art": "eingabe", "nr": i, "eingabe": text, "puppet": [p, jp.get("code"), jp.get("message")],
                                  "puppet_s": round(t1 - t0, 2), "reaktion_s": round(t2 - t1, 2), "gesamt_s": round(t2 - t0, 2),
                                  "fenster": [t0, t2], **r, "zustand": zustand(db)})
        for k in range(AUTOCHAT, 0, -1):
            t0 = time.time()
            with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as c:
                fs = [json.loads(x) for (x,) in c.execute("SELECT json FROM scene_facts WHERE session_id=? ORDER BY rowid", (SID,))]
            reden = [f for f in fs if f.get("kind") == "speech"]
            stim = str(reden[-1].get("text") or "") if reden else ""
            g, jg = L7.req("POST", "/api/kernel/autochat-gate", {"userId": "admin", "sessionId": SID, "remaining": k, "stimulus": stim})
            if jg.get("stop") or not jg.get("speakerId"):
                E["schritte"].append({"art": "autochat", "gate": [g, jg.get("stop"), jg.get("reason")], "fenster": [t0, time.time()]})
                break
            r = figurenzug(str(jg["speakerId"]), aus, f"autochat{AUTOCHAT - k + 1}")
            t2 = time.time()
            E["schritte"].append({"art": "autochat", "nr": AUTOCHAT - k + 1, "gate": [g, jg.get("stop"), jg.get("reason"), jg.get("speakerId")],
                                  "gesamt_s": round(t2 - t0, 2), "fenster": [t0, t2], **r, "zustand": zustand(db)})
        L7.stop()
    finally:
        L7.stop()
        zp.terminate()
    calls = [json.loads(x) for x in prot.read_text(encoding="utf-8").splitlines()] if prot.exists() else []
    for s in E["schritte"]:
        w = [c for c in calls if s["fenster"][0] <= c["t_start"] <= s["fenster"][1]]
        s["aufrufe"] = [[c["schema"], c["dauer_s"], c["prompt_zeichen"], (c.get("usage") or {}).get("completion_tokens"), c["status"],
                         c.get("finish")] for c in w]
        s["aufrufe_summe"] = len(w)
    # Wiederholung: 5-Wort-Folgen in >=2 Antworten derselben Figur; gleiche Handlung hintereinander
    def woerter(t):
        return re.findall(r"\w+", str(t or "").lower())
    je_fig: dict = {}
    for s in E["schritte"]:
        if s.get("speech") is not None or s.get("action") is not None:
            je_fig.setdefault(s.get("sprecher"), []).append(s)
    wied = {}
    for fig, ss in je_fig.items():
        folgen: dict = {}
        for idx, s in enumerate(ss):
            w = woerter(s.get("speech"))
            for f in {" ".join(w[i:i + 5]) for i in range(len(w) - 4)}:
                folgen.setdefault(f, set()).add(idx)
        wied[fig] = {"fuenfwort_in_2plus": sorted(f for f, v in folgen.items() if len(v) >= 2)}
    E["wiederholung"] = wied
    (aus / "ergebnis.json").write_text(json.dumps(E, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for s in E["schritte"]:
        print(s.get("art"), s.get("nr"), s.get("status") or s.get("gate"), s.get("gesamt_s"), "s", s.get("aufrufe_summe"), "Aufrufe |",
              s.get("sprecher"), "|", str(s.get("speech"))[:90], "|", str(s.get("action"))[:70], "|", (s.get("zustand") or {}).get("emotion"),
              (s.get("zustand") or {}).get("intent"))
    print("Wiederholung:", json.dumps(wied, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
