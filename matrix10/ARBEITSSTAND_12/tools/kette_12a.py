#!/usr/bin/env python3
"""Stand 12A Kettenkarte (Kettenvertrag §6.3, AMASTER §24/§34/§41-§46): EIN Ereignis durch die ganze Kette verfolgen, Oberflaeche bis
Oberflaeche, mit echtem Modell (gpt-4o-mini, Schluessel aus deiner DB-KOPIE, ueber zaehler_12.py gezaehlt und protokolliert).

Ablauf je Lauf (identisch fuer P25-lauffaehig und Stand 12):
  1. eigene, unveraenderte Kopie DEINER DB (SHA-256 im Beleg), Endpoint der KOPIE auf die Zaehl-Weiterleitung;
  2. START.py; neue Sitzung ueber die Oberflaeche (oberflaeche_12a.cjs neu: Welt Gasthaus, anwesend Johann + Mara);
  3. Schritte (unten): Puppet-Eingaben wie die UI (/api/kernel/puppet), danach Reaktionszug der angesprochenen Figur (prepare ->
     formulate -> commit, inputKind autochat wie chat.$sessionId.tsx), AutoChat-Zuege (autochat-gate -> Sprecher des Servers);
  4. je Schritt: neue Fakten (Art, Text, validiert, Wirkungsklasse, Ausgang), Raum/Szene (sceneState ohne Verlauf + neue
     Verlaufseintraege), Koerper/Zustand/Absicht/Beziehung von Mara und Johann, Erlebens-Verwerfungen (Live-Log), Antwort der Figur
     mit Wirkungsvorschlag, und der Brief, den die Figur im naechsten Zug liest (Formulierungs-Prompt aus dem Protokoll);
  5. vor dem Ende: Anzeige lesen (oberflaeche_12a.cjs lesen), Spiegel lesen (prepare ohne formulate/commit), Server NEU starten,
     Spiegel und Anzeige erneut - beides muss gleich sein;
  6. fremde Figuren (Clara, Gustav, Robert), andere Sitzungen und Stamm: Hash vorher/nachher.
Aufruf: python3 -I kette_12a.py <produktordner> <nutzer.sqlite> <ausgabeordner>
Der Schluessel wird nie ausgegeben oder protokolliert.
"""
from __future__ import annotations

import hashlib
import json
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

J, M = "char_g7_johann", "char_g7_mara"
FREMD = ("char_g7_clara", "char_g7_gustav", "char_g7_robert")
WELT = "world_gasthaus_7kreis"
ZPORT = 5191
NAMEN = {J: "Johann", M: "Mara"}

# Messfaelle: (Fall, Art, Figur, Text, reagiert)  - reagiert = Figur, die danach ihren Reaktionszug macht (wie die UI)
SCHRITTE = [
    ("G Grundfall", "puppet", J, "Hey süsse, ich klarsche dir auf deinen Arsch", M),
    ("G Grundfall", "puppet", J, "Ach komm stell dich nicht so an", M),
    ("U Uebergriff ohne Verletzung", "puppet", J, "Ich greife unter dein tshirt und lach dich an", M),
    ("A Absicht -> eigene Tat (AutoChat)", "autochat", None, None, None),
    ("A Absicht -> eigene Tat (AutoChat)", "autochat", None, None, None),
    ("E Erfolg Rueckzug (Mara gesteuert)", "puppet", M, "Ich trete einen Schritt von Johann zurück.", None),
    ("B Misserfolg: festgehalten", "puppet", J, "Ich packe Mara fest am Handgelenk und halte sie fest.", None),
    ("B Misserfolg: festgehalten", "puppet", M, "Ich gehe von Johann weg zur Tür.", None),
    ("Z Zwei Taten in einer Eingabe", "puppet", M, "Ich stoße Johann von mir weg und trete zurück.", None),
    ("A Absicht -> eigene Tat (AutoChat)", "autochat", None, None, None),
]


def sql(db, q, a=()):
    with sqlite3.connect(Path(db).as_uri() + "?mode=ro", uri=True, timeout=10) as c:
        return c.execute(q, a).fetchall()


def sitzung(db, sid):
    return json.loads(sql(db, "SELECT json FROM sessions WHERE id=?", (sid,))[0][0])


def fakten(db, sid):
    return [json.loads(j) for (j,) in sql(db, "SELECT json FROM scene_facts WHERE session_id=? ORDER BY rowid", (sid,))]


def beziehung(db, sid, a, b):
    for (j,) in sql(db, "SELECT json FROM relationships WHERE session_id=? AND from_id=? AND to_id=?", (sid, a, b)):
        r = json.loads(j)
        return {k: r.get(k) for k in ("trust", "closeness", "fear")}
    rt = (sitzung(db, sid).get("runtimes") or {}).get(a) or {}
    return (rt.get("relations") or {}).get(b)


def zustand(db, sid):
    s = sitzung(db, sid)
    out = {}
    for fid in (M, J):
        rt = (s.get("runtimes") or {}).get(fid) or {}
        out[NAMEN[fid]] = {k: rt.get(k) for k in ("emotion", "intensity", "intent", "fear", "anger", "pain", "stress", "mobility",
                                                    "posture", "position", "restrained", "heldBy")}
        out[NAMEN[fid]]["affekte"] = [[a.get("type"), a.get("intensity"), a.get("targetId")] for a in (rt.get("affects") or [])
                                      if isinstance(a, dict)]
    out["Mara->Johann"] = beziehung(db, sid, M, J)
    st = s.get("sceneState") or {}
    out["szene"] = {k: v for k, v in st.items() if k not in ("history", "openEmotions")}
    out["szene_verlauf_n"] = len(st.get("history") or [])
    return out


def fremd_hash(db, sid):
    h = hashlib.sha256()
    s = sitzung(db, sid)
    for fid in FREMD:
        h.update(json.dumps((s.get("runtimes") or {}).get(fid), sort_keys=True).encode())
    for (i, j) in sql(db, "SELECT id, json FROM sessions WHERE id<>? ORDER BY id", (sid,)):
        h.update(i.encode() + j.encode())
    for (j,) in sql(db, "SELECT json FROM characters ORDER BY id"):
        h.update(j.encode())
    return h.hexdigest()[:16]


def figurenzug(sid, speaker, ev, tag, target=None):
    tr = {"userId": "admin", "sessionId": sid, "speakerId": speaker, "inputActorId": "user", "speakAs": "operator",
          "targetId": target, "inputKind": "autochat", "text": "", "roleOverride": "teilnehmer"}
    a, ja = L7.req("POST", "/api/kernel/prepare", {"sessionId": sid, "truth": tr, "speaker": {"id": speaker}})
    spk = str(((ja.get("truth") or {}).get("speaker_id")) or ((ja.get("truth") or {}).get("speakerId")) or speaker)
    c, jc = L7.req("POST", "/api/llm/formulate", {"sessionId": sid, "sourceTurnId": (ja.get("truth") or {}).get("id"), "speakerId": spk,
                                                  "turnIndex": (ja.get("session") or {}).get("turnIndex"), "text": "", "scope": "user",
                                                  "inputKind": "autochat", "turnBeleg": ja.get("turnBeleg")})
    res = jc.get("result") or {}
    d, jd = L7.req("POST", "/api/kernel/commit", {"sessionId": sid, "truth": ja.get("truth"), "speaker": {"id": spk},
                                                  "result": {"speech": res.get("speech"), "action": res.get("action"),
                                                             **({"proposals": res["proposals"]} if res.get("proposals") else {})},
                                                  "fired": ((ja.get("brainContext") or {}).get("spiegel") or {}).get("fired") or [],
                                                  "turnBeleg": ja.get("turnBeleg"), "formulierungsBeleg": jc.get("formulierungsBeleg")})
    (ev / f"{tag}.json").write_text(json.dumps({"prepare": ja, "formulate": jc, "commit": jd}, ensure_ascii=False)[:900000])
    props = res.get("proposals") if isinstance(res.get("proposals"), dict) else {}
    return {"sprecher": NAMEN.get(spk, spk), "status": [a, c, d], "code": [ja.get("code"), jc.get("code"), jd.get("code")],
            "speech": res.get("speech"), "action": res.get("action"), "wirkungsvorschlag": props.get("wirkung"),
            "quelle": res.get("source") or jc.get("source")}


def spiegel_jetzt(sid, speaker):
    """Spiegel des naechsten Zuges (prepare ohne formulate/commit) - Sprecher wie die UI vom Server (autochat-gate)."""
    g, jg = L7.req("POST", "/api/kernel/autochat-gate", {"userId": "admin", "sessionId": sid, "remaining": 1, "stimulus": ""})
    speaker = str(jg.get("speakerId") or speaker)
    tr = {"userId": "admin", "sessionId": sid, "speakerId": speaker, "inputActorId": "user", "speakAs": "operator",
          "inputKind": "autochat", "text": "", "roleOverride": "teilnehmer"}
    a, ja = L7.req("POST", "/api/kernel/prepare", {"sessionId": sid, "truth": tr, "speaker": {"id": speaker}})
    sp = ((ja.get("brainContext") or {}).get("spiegel") or {})
    if a != 200:
        return a, {"code": ja.get("code"), "message": str(ja.get("message") or "")[:200], "sprecher": speaker}
    keep = ("runtime", "relationsHere", "spatial", "raum", "dialogue", "memories", "stimulusAction", "userUtterance", "consent",
            "grenzen", "bodyState", "currentState")
    return a, {k: sp.get(k) for k in keep if k in sp}


def schritt_fakten(db, sid, vorher_n):
    out = []
    for f in fakten(db, sid)[vorher_n:]:
        eff = f.get("effect") if isinstance(f.get("effect"), dict) else {}
        out.append({"art": f.get("kind"), "von": NAMEN.get(f.get("actorId"), f.get("actorId")), "an": NAMEN.get(f.get("targetId"), f.get("targetId")),
                    "text": str(f.get("text") or "")[:120], "validiert": f.get("validated"),
                    "wirkungsklasse": eff.get("effectKind"), "wirkung": (eff.get("wirkung") or {}).get("art") if isinstance(eff.get("wirkung"), dict) else None,
                    "wirkung_validiert": eff.get("validated"), "ausgang": eff.get("outcome") or f.get("outcome"),
                    "pruefgrund": ((eff.get("pruefung") or eff.get("effectCheck") or {}) if isinstance(eff.get("pruefung") or eff.get("effectCheck"), dict) else {}).get("grund")})
    return out


def main() -> int:
    root, nutzer, aus = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    aus.mkdir(parents=True, exist_ok=True)
    prot = aus / "modellaufrufe.jsonl"
    prot.unlink(missing_ok=True)
    if not L7.stop():
        return 3
    data = root / "data"
    shutil.rmtree(data, ignore_errors=True)
    data.mkdir()
    db = data / "matrix10.sqlite"
    shutil.copy(nutzer, db)
    if (nutzer.parent / ".matrix10_db_initialized").exists():
        shutil.copy(nutzer.parent / ".matrix10_db_initialized", data / ".matrix10_db_initialized")
    E: dict = {"produkt": str(root), "db_sha256_vorher": hashlib.sha256(nutzer.read_bytes()).hexdigest(), "schritte": []}
    with sqlite3.connect(db) as c:   # nur die KOPIE: Endpoint auf die Zaehl-Weiterleitung (Schluessel bleibt unberuehrt)
        sc, si, j = c.execute("SELECT scope, scope_id, json FROM config WHERE scope='user'").fetchone()
        d = json.loads(j)
        d["endpoint"] = f"http://127.0.0.1:{ZPORT}/api.openai.com/v1/chat/completions"
        c.execute("UPDATE config SET json=? WHERE scope=? AND scope_id=?", (json.dumps(d), sc, si))
    zp = subprocess.Popen([sys.executable, "-I", str(HIER / "zaehler_12.py"), str(ZPORT), str(prot)])
    try:
        time.sleep(0.8)
        if not L7.start(root, aus / "start.log"):
            return 3
        subprocess.run(["node", str(HIER / "oberflaeche_12a.cjs"), "neu", WELT, f"{J},{M}", str(aus / "ui_neu.json")], timeout=120)
        sid = json.loads((aus / "ui_neu.json").read_text()).get("sessionId")
        E["sitzung"] = sid
        if not sid:
            E["abbruch"] = "Sitzung ueber die Oberflaeche nicht angelegt"
            return 3
        E["fremd_vorher"] = fremd_hash(db, sid)
        E["start_zustand"] = zustand(db, sid)
        for k, (fall, art, fig, text, reagiert) in enumerate(SCHRITTE, 1):
            t0 = time.time()
            n0 = len(fakten(db, sid))
            rec: dict = {"nr": k, "fall": fall, "art": art}
            if art == "puppet":
                ziel = M if fig == J else J
                p, jp = L7.req("POST", "/api/kernel/puppet", {"sessionId": sid, "figure": {"id": fig, "name": NAMEN[fig]}, "text": text,
                                                             "targetId": ziel})
                rec.update({"eingabe": f"{NAMEN[fig]}: {text}", "puppet": [p, jp.get("code"), str(jp.get("message") or "")[:200]]})
                rec["fakten_eingabe"] = schritt_fakten(db, sid, n0)
                if reagiert and p == 200:
                    n1 = len(fakten(db, sid))
                    rec["reaktion"] = figurenzug(sid, reagiert, aus, f"s{k:02d}_reaktion", target=fig)
                    rec["fakten_reaktion"] = schritt_fakten(db, sid, n1)
            else:
                reden = [f for f in fakten(db, sid) if f.get("kind") == "speech"]
                g, jg = L7.req("POST", "/api/kernel/autochat-gate", {"userId": "admin", "sessionId": sid, "remaining": 1,
                                                                    "stimulus": str(reden[-1].get("text") or "") if reden else ""})
                rec["gate"] = [g, jg.get("stop"), jg.get("reason"), NAMEN.get(jg.get("speakerId"), jg.get("speakerId"))]
                if not jg.get("stop") and jg.get("speakerId"):
                    rec["reaktion"] = figurenzug(sid, str(jg["speakerId"]), aus, f"s{k:02d}_autochat")
                    rec["fakten_reaktion"] = schritt_fakten(db, sid, n0)
            rec["dauer_s"] = round(time.time() - t0, 2)
            rec["fenster"] = [t0, time.time()]
            rec["zustand"] = zustand(db, sid)
            E["schritte"].append(rec)
            print(k, fall, rec.get("puppet") or rec.get("gate"), (rec.get("reaktion") or {}).get("status"), rec["dauer_s"], "s", flush=True)
        # Anzeige und Spiegel vor dem Neustart
        subprocess.run(["node", str(HIER / "oberflaeche_12a.cjs"), "lesen", sid, str(aus / "ui_vorher.json"), str(aus / "ui_vorher.png")], timeout=120)
        a1, sp1 = spiegel_jetzt(sid, M)
        z1 = zustand(db, sid)
        L7.stop()
        if not L7.start(root, aus / "start.log"):
            return 3
        a2, sp2 = spiegel_jetzt(sid, M)
        z2 = zustand(db, sid)
        subprocess.run(["node", str(HIER / "oberflaeche_12a.cjs"), "lesen", sid, str(aus / "ui_nachher.json"), str(aus / "ui_nachher.png")], timeout=120)
        E["neustart"] = {"prepare_status": [a1, a2], "spiegel_gleich": sp1 == sp2, "zustand_gleich": z1 == z2,
                         "spiegel_unterschied": [k for k in set(sp1) | set(sp2) if sp1.get(k) != sp2.get(k)]}
        (aus / "spiegel_vor_nach_neustart.json").write_text(json.dumps({"vorher": sp1, "nachher": sp2}, ensure_ascii=False, indent=1))
        E["fremd_nachher"] = fremd_hash(db, sid)
        E["fremd_unveraendert"] = E["fremd_vorher"] == E["fremd_nachher"]
        L7.stop()
    finally:
        L7.stop()
        zp.terminate()
    calls = [json.loads(x) for x in prot.read_text(encoding="utf-8").splitlines()] if prot.exists() else []
    for s in E["schritte"]:
        w = [c for c in calls if s["fenster"][0] <= c["t_start"] <= s["fenster"][1]]
        s["modellaufrufe"] = len(w)
        s["modellzeit_s"] = round(sum(c["dauer_s"] for c in w), 1)
        s["aufruf_status"] = sorted({c["status"] for c in w})
    # Erlebens-Verwerfungen und Wirkungspruefungen aus dem Live-Log dieses Laufs
    logs = sorted((root / "logs").glob("*.log"), key=lambda p: p.stat().st_mtime)
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in logs[-2:])
    E["log"] = {"erleben_verworfen": re.findall(r'"rejects": (\[[^\]]+\])', text)[:60],
                "wirkungspruefung": [{"vorschlag": m.group(1), "ergebnis": m.group(2), "grund": m.group(3)} for m in re.finditer(
                    r'"stage": "EFFECT_CHECK".*?"vorschlag": "([a-z_]+)".*?"ergebnis": "([a-z_]+)"(?:.*?"grund": "([a-z_]+)")?', text)]}
    (aus / "ergebnis.json").write_text(json.dumps(E, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Neustart:", E.get("neustart"), "fremd unveraendert:", E.get("fremd_unveraendert"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
