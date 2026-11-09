#!/usr/bin/env python3
"""F1-Durchlauf (Zielfaehigkeit, GESAMTKARTE_07/ZIELFAEHIGKEIT_F1.md) ueber den echten Startweg START.py + HTTP-Routen
der Oberflaeche, Modell = lokales Testmodell (Provider 'custom', testmodell_f1_09.py). Keine Produktaenderung.

Welt der Vorlage (Gasthaus): Johann (Taeter, Puppet), Mara (Opfer), Gustav (anwesend), Robert (abwesend).
Schritte: Konfiguration -> Puppet "Johann schlaegt Mara" -> Folgeturn an Mara (prepare -> formulate -> commit)
-> echter Neustart -> weiterer Folgeturn an Mara -> Pruefung je Glied (Zustand in SQLite, Brief an das Modell, Isolation).
Aufruf: python3 -I f1_durchlauf_09.py <produktordner> <vorlage.sqlite> <evidence-ordner> [drehbuch.json]
Gegenprobe: drehbuch_f1_gegenprobe_09.json (Bewertung ohne Bedeutung) muss G4/G4b/G6 ROT liefern.
Exit 0 = F1 erfuellt, 2 = mindestens ein Glied verletzt, 3 = Messung nicht moeglich.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parents[1] / "ARBEITSSTAND_07" / "tools"))
import live_abnahme_k01_07 as L7  # noqa: E402  (start/stop/req/sql/digest)

SID, AV = "ses_v92", "ses_av06"
J, M, G, R = "char_g7_johann", "char_g7_mara", "char_g7_gustav", "char_g7_robert"
PORT = 5199
TAT = "*Johann schlägt Mara mit der Faust ins Gesicht.*"
FRAGE1 = "Mara, Johann steht noch neben dir. Was sagst du zu ihm?"
FRAGE2 = "Mara, Johann setzt sich wieder zu dir an den Tisch. Was willst du jetzt von ihm?"


def zustand(db):
    s = json.loads(L7.sql(db, "SELECT json FROM sessions WHERE id=?", (SID,))[0][0])
    rel = {}
    for (j,) in L7.sql(db, "SELECT json FROM relationships WHERE session_id=?", (SID,)):
        x = json.loads(j)
        if x.get("fromId") in (M, R) and x.get("toId") == J:
            rel[x["fromId"]] = {k: x.get(k) for k in ("trust", "closeness", "fear")}
    rt = (s.get("runtimes") or {}).get(M) or {}
    return {"mara_runtime": {k: rt.get(k) for k in ("emotion", "intensity", "fear", "anger", "pain", "stress", "intent", "trust",
                                                    "mobility", "affects")},
            "beziehung_zu_johann": rel, "turnIndex": s.get("turnIndex")}


def turn(text, target, ev, tag):
    tr = {"userId": "admin", "sessionId": SID, "speakerId": target, "inputActorId": "user", "speakAs": "operator",
          "targetId": target, "inputKind": "speech", "text": text}
    a, ja = L7.req("POST", "/api/kernel/prepare", {"sessionId": SID, "truth": tr, "speaker": {"id": target}})
    c, jc = L7.req("POST", "/api/llm/formulate", {"sessionId": SID, "sourceTurnId": (ja.get("truth") or {}).get("id"),
                                                  "speakerId": target, "text": text, "scope": "user", "inputKind": "speech",
                                                  "turnBeleg": ja.get("turnBeleg")})
    res = jc.get("result") or {}
    d, jd = L7.req("POST", "/api/kernel/commit", {"sessionId": SID, "truth": ja.get("truth"), "speaker": {"id": target},
                                                  "result": {"speech": res.get("speech"), "action": res.get("action"),
                                                             **({"proposals": res["proposals"]} if res.get("proposals") else {})},
                                                  "fired": ((ja.get("brainContext") or {}).get("spiegel") or {}).get("fired") or [],
                                                  "turnBeleg": ja.get("turnBeleg"), "formulierungsBeleg": jc.get("formulierungsBeleg")})
    out = {"prepare": [a, ja.get("code"), ja.get("message")], "formulate": [c, jc.get("code"), res.get("speech"), res.get("source")],
           "commit": [d, jd.get("code"), jd.get("message")],
           "spiegel_mara": {k: ((ja.get("brainContext") or {}).get("spiegel") or {}).get(k)
                            for k in ("runtime", "relationsHere", "affects", "intent", "memories")}}
    (ev / f"{tag}.json").write_text(json.dumps({"prepare": ja, "formulate": jc, "commit": jd}, indent=1, ensure_ascii=False)[:400000])
    return out


def main() -> int:
    root, vorlage, ev = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), Path(sys.argv[3]).resolve()
    ev.mkdir(parents=True, exist_ok=True)
    prot = ev / "modellaufrufe.jsonl"
    buch = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else HIER / "drehbuch_f1_09.json"
    prot.unlink(missing_ok=True)
    db = root / "data" / "matrix10.sqlite"
    if not L7.stop():
        return 3
    (root / "data").mkdir(exist_ok=True)
    for f in ("matrix10.sqlite", "matrix10.sqlite-wal", "matrix10.sqlite-shm"):
        (root / "data" / f).unlink(missing_ok=True)
    shutil.copy(vorlage, db)
    tm = subprocess.Popen([sys.executable, "-I", str(HIER / "testmodell_f1_09.py"), str(root), str(PORT), str(prot), str(buch)])
    E: dict = {"vorlage_sha256": hashlib.sha256(vorlage.read_bytes()).hexdigest()}
    try:
        time.sleep(1.0)
        log = ev / "start.log"
        if not L7.start(root, log):
            return 3
        av0 = L7.digest(db, AV)
        stamm0 = L7.sql(db, "SELECT json FROM characters WHERE id=?", (M,))
        E["config"] = L7.req("PUT", "/api/config", {"scope": "user", "provider": "custom", "model": "f1-testmodell",
                                                    "endpoint": f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                                    "apiKey": "f1-testschluessel"})[0]
        E["vorher"] = zustand(db)
        p, jp = L7.req("POST", "/api/kernel/puppet", {"sessionId": SID, "figure": {"id": J, "name": "Johann"}, "text": TAT})
        E["puppet"] = [p, jp.get("code"), jp.get("message")]
        E["nach_tat"] = zustand(db)
        E["turn1"] = turn(FRAGE1, M, ev, "turn1")
        E["nach_turn1"] = zustand(db)
        L7.stop()
        if not L7.start(root, log):
            return 3
        E["nach_neustart"] = zustand(db)
        E["turn2"] = turn(FRAGE2, M, ev, "turn2")
        E["nach_turn2"] = zustand(db)
        E["isolation_andere_session_unveraendert"] = L7.digest(db, AV) == av0
        E["stamm_mara_unveraendert"] = L7.sql(db, "SELECT json FROM characters WHERE id=?", (M,)) == stamm0
        L7.stop()
    finally:
        tm.terminate()
    calls = [json.loads(x) for x in prot.read_text().splitlines()] if prot.exists() else []
    E["modellaufrufe"] = [[c["lesung"], c["nr"], c["geskriptet"]] for c in calls]
    E["appraisal_log"] = [json.loads(x) for f in sorted((root / "logs").glob("*.log")) for x in f.read_text().splitlines()
                          if '"stage": "APPRAISAL"' in x]
    E["kriterien"] = K = kriterien(db, E, calls)
    E["gesamt"] = "F1 ERFUELLT (Kernel-Kette, Testmodell)" if all(K.values()) else "F1 VERLETZT"
    (ev / "f1_ergebnis.json").write_text(json.dumps(E, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(K, indent=1, ensure_ascii=False))
    print(E["gesamt"])
    return 0 if all(K.values()) else 2


def kriterien(db, E, calls):
    facts = [json.loads(j) for (j,) in L7.sql(db, "SELECT json FROM scene_facts WHERE session_id=? ORDER BY rowid", (SID,))]
    tat = [f for f in facts if f.get("kind") == "action" and f.get("actorId") == J and f.get("targetId") == M]
    mem = lambda cid: [json.loads(j) for (j,) in L7.sql(db, "SELECT json FROM memories WHERE session_id=?", (SID,))  # noqa: E731
                       if json.loads(j).get("characterId") == cid and "schlägt" in str(json.loads(j).get("text"))]
    v, t, a1, n, a2 = (E[k] for k in ("vorher", "nach_tat", "nach_turn1", "nach_neustart", "nach_turn2"))
    rm = lambda z: z["mara_runtime"]  # noqa: E731
    rj = lambda z: z["beziehung_zu_johann"].get(M) or {}  # noqa: E731
    aff = [x for x in (rm(a1).get("affects") or []) if x.get("source") == "appraisal" and x.get("targetId") == J]
    briefe = [c["user"] for c in calls if c["lesung"] == "FORMULIERUNG"]

    def im_brief(u):
        b, _, st = u.partition("KANONISCHER LESEZUSTAND (IDs und Quellen):")
        try:
            rt = json.loads(st).get("runtime") or {}
        except Exception:
            rt = {}
        if not st:
            # Stand 11D: kein roher Zustand mehr im Prompt - Gefuehl (gegen Johann) und Absicht stehen im Brief ("DEINE LAGE JETZT")
            b = u.partition("KENNUNGEN (nur für refers_to und aussagen):")[0]
            lage = next((x for x in b.splitlines() if x.startswith("DEINE LAGE JETZT")), "")
            rt = {"intent": rm(a1).get("intent") if str(rm(a1).get("intent") or "") and str(rm(a1).get("intent")) in lage else None,
                  "emotionToward": "Johann Bruckner" if "gegenüber Johann Bruckner" in lage else None}
        rel = rj(a1)
        zeile = next((x for x in b.splitlines() if x.startswith("DEINE BEZIEHUNGEN ZU DEN ANWESENDEN")), "")
        jo = zeile.split("Johann Bruckner:", 1)[-1].split("|")[0] if "Johann Bruckner:" in zeile else ""
        werte = dict(re.findall(r"(Vertrauen|Furcht) ([0-9.]+)", jo))
        return (abs(float(werte.get("Vertrauen", 9)) - rel.get("trust", -9)) < 0.006 and abs(float(werte.get("Furcht", 9)) - rel.get("fear", -9)) < 0.006
                and "[erlebt] Johann Bruckner: Johann schlägt Mara" in b and f"Schmerz {rm(t).get('pain')}" in b
                and rt.get("intent") == rm(a1).get("intent") and rt.get("emotionToward") == "Johann Bruckner")
    def rahmen_benannt():
        for c in calls:
            if c["lesung"] != "APPRAISAL_RULES" or '"figur": "Mara Nowak"' not in c["user"]:
                continue
            u = json.loads(c["user"])
            r, gg = u.get("beziehung_zum_handelnden"), u.get("gerade_geschehen") or []
            return isinstance(r, dict) and bool(gg) and r.get("person") == gg[-1].get("wer") and r.get("ereignis") == gg[-1].get("id")
        return False
    return {
        "G1_tat_serverseitig_gebunden_johann_an_mara_gewalt": E["puppet"][0] == 200 and bool(tat)
            and (tat[0].get("effect") or {}).get("wirkung") == "gewalt" and (tat[0].get("effect") or {}).get("validated") is True,
        "G2_wahrnehmung_mara_erlebt_gustav_gesehen_robert_nichts": [m.get("kind") for m in mem(M)] == ["erlebt"]
            and [m.get("kind") for m in mem(G)] == ["gesehen"] and not mem(R),
        "G3_koerper_schmerz_steigt_beweglichkeit_sinkt": rm(t)["pain"] > rm(v)["pain"] and rm(t)["mobility"] < rm(v)["mobility"],
        "G4_bedeutung_angst_gegen_johann_absicht_abstand_aus_bewertung": bool(aff) and bool(rm(a1).get("intent")),
        "G4c_B2_beziehungsrahmen_der_bewertung_nennt_person_und_ereignis": rahmen_benannt(),
        "G4b_beziehung_vertrauen_sinkt_furcht_steigt": rj(a1).get("trust", 1) < rj(v)["trust"] and rj(a1).get("fear", 0) > rj(v)["fear"],
        "G6_naechster_zug_brief_enthaelt_beziehung_koerper_erinnerung_gefuehl_absicht": len(briefe) >= 1 and im_brief(briefe[0]),
        "G6b_nach_neustart_brief_enthaelt_dasselbe": len(briefe) >= 2 and im_brief(briefe[1]),
        "G7_figurenantworten_committet": E["turn1"]["commit"][0] == 200 and E["turn2"]["commit"][0] == 200,
        "G9_neustart_zustand_unveraendert": n == a1,
        "G9b_kein_doppeltes_anwenden_im_folgezug": rj(a2) == rj(a1),
        "G10_isolation_andere_session_und_stamm_unveraendert": E["isolation_andere_session_unveraendert"] and E["stamm_mara_unveraendert"]
            and E["nach_turn2"]["beziehung_zu_johann"].get(R) == v["beziehung_zu_johann"].get(R),
    }


if __name__ == "__main__":
    raise SystemExit(main())
