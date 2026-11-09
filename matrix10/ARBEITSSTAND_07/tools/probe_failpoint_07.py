#!/usr/bin/env python3
"""Stand 07 (aus probe_failpoint_06.py, Pruefaussage unveraendert): Commit-Szenarien holen ihre Figurenantwort ueber
prepare -> formulate (beleg_kette_07) OHNE Ausfall in der Vorbereitung; gemessen wird weiter nur die commit-Anfrage.

K2a: jede Stelle, an der eine Anfrage den Rust-Einwilligungskern erreicht, wird einzeln zur Ausfallstelle.

Fehlerinjektion "Ausfall ab Aufruf k": native_boundary._load arbeitet fuer die ersten k Aufrufe
der Anfrage normal (echte ABI-3-Bibliothek) und wirft ab dem k-ten Aufruf dieselbe
NativeBoundaryError, die das Produkt bei fehlender Bibliothek wirft. Das entspricht einem
Ausfall mitten in der Anfrage. Gemessen wird NUR die Fehlerbehandlung (kein Fachergebnis).

Je Anfrage: erst ein Lauf ohne Ausfall (zaehlt N Kernaufrufe), dann k = 0..N-1 je auf frischer
Kopie der Vorlage-DB. Fuer jedes k: HTTP-Status, Code, SQLite unveraendert?, Erfolgsmeldung?,
app.py-Zeilen auf dem Stapel des ERSTEN fehlschlagenden Aufrufs.

FAIL-OPEN = SQLite veraendert ODER Erfolgsmeldung (2xx + ok:true) bei einem Ausfall.

Aufruf: python3 -I probe_failpoint_06.py --root <Stage> --vorlage <db> --output <json> [--max-k 400]
"""
from __future__ import annotations

import argparse
import json
import os
from contextlib import closing
from pathlib import Path
import shutil
import sys
import tempfile
import traceback
import urllib.request
from unittest.mock import patch

J, M, G = "char_g7_johann", "char_g7_mara", "char_g7_gustav"
SID, AV = "ses_v92", "ses_av06"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--vorlage", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--max-k", type=int, default=400)
    a = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="matrix06_fp_"))
    root = work / "produkt"
    shutil.copytree(a.root, root, ignore=shutil.ignore_patterns("target", "node_modules", "__pycache__", "dist"))
    sys.path[:0] = [str(root), str(root / "tests"), str(Path(__file__).resolve().parent)]
    os.environ.pop("PYTEST_CURRENT_TEST", None)
    os.environ.pop("MATRIX_SKIP_SEED", None)
    dbp = str(work / "t.sqlite")
    os.environ["MATRIX_DB"] = dbp
    os.environ["MATRIX_LIVE_LOG"] = str(work / "live.log")
    from matrix_api.db import connect
    from matrix_api import app as appmod
    from matrix_api import native_boundary as nb
    from test_v92_puppet_vertrag import FakeProvider, plan, comp
    from probe_http_503_07 import digest
    import beleg_kette_07 as BK
    H = {"X-Matrix-Actor": "admin"}
    st = {"k": None, "n": 0, "erster_fehler": None, "digest_bei_ausfall": None, "sid": None}
    _orig = nb._load

    def _load():
        st["n"] += 1
        if st["k"] is not None and st["n"] > st["k"]:
            if st["erster_fehler"] is None:
                st["erster_fehler"] = sorted({fr.lineno for fr in traceback.extract_stack()[:-1]
                                              if fr.filename.endswith("matrix_api/app.py")})
                # committeter Stand im Moment des Ausfalls (eigene Lese-Verbindung sieht nur Committetes)
                with closing(connect(dbp)) as rc:
                    st["digest_bei_ausfall"] = digest(rc, st["sid"])
            raise nb.NativeBoundaryError("Rust-Schreibgrenze fehlt. (Fehlerinjektion: Ausfall ab Aufruf k)")
        return _orig()
    nb._load = _load

    def client():
        return appmod.create_app(dbp).test_client()

    def avatar_truth(text):
        return {"userId": "admin", "operatorId": "admin", "sessionId": AV, "role": "teilnehmer", "speakerId": M,
                "responseSpeakerId": M, "avatarId": J, "inputActorId": J, "speakAs": "avatar", "targetId": M,
                "authority": "teilnehmer", "presentIds": [J, M, G], "inputKind": "speech", "text": text,
                "userName": "Johann Bruckner"}

    def prepare(cl):
        def senden(kl=None):
            with patch.object(urllib.request, "urlopen", FakeProvider([])):
                return cl.post("/api/kernel/prepare", headers=H, json={
                    "sessionId": AV, "actorUserId": "admin", "trace_id": "kpr_fp", "truth": avatar_truth("Wie geht es dir, Mara?"),
                    "speaker": {"id": M, "name": "Mara Nowak"},
                    "present": [{"id": J, "name": "Johann Bruckner"}, {"id": M, "name": "Mara Nowak"}],
                    **({"klaerungen": kl} if kl else {})})
        r = senden()
        j = r.get_json(silent=True) or {}
        if r.status_code == 422 and j.get("code") == "IDENTITAET_KLAEREN":
            r = senden([{"frage": q.get("frage"), "id": M} for q in j.get("klaerung") or []])
        return r

    stash = {}

    def belege(cl, formulierung):
        b = BK.belege_holen(cl, H, connect=connect, dbp=dbp, sid=AV, speaker=M, truth_fn=avatar_truth,
                            formulierung=formulierung, FakeProvider=FakeProvider, trace="fp")
        if not isinstance(b, dict):
            return b
        stash["b"] = b
        return None

    def commit_vorb(cl):
        return belege(cl, {"speech": "Hallo Johann.", "action": None})

    def commit_belegt(cl):
        return BK.belegt_committen(cl, H, stash["b"], sid=AV, FakeProvider=FakeProvider, trace="fp")

    def commit(cl):
        r = commit_vorb(cl)
        return r if r is not None else commit_belegt(cl)

    def puppet(cl):
        prov = FakeProvider([plan("action", "act", [dict(comp("handlung", "Johann streichelt Mara", "zaertlich"))])])
        with patch.object(urllib.request, "urlopen", prov):
            return cl.post("/api/kernel/puppet", headers=H, json={
                "sessionId": SID, "actorUserId": "admin", "figure": {"id": J, "name": "Johann Bruckner"},
                "text": "Johann streichelt Mara", "targetId": M})

    def regie(cl):
        def analyse(p):
            seg = p["anweisung"].rstrip(".")
            return {"komponenten": [{"typ": "handlung", "akteur": "Johann Bruckner", "ziel": "Mara Nowak", "segment": seg,
                                     "beschreibung": seg, "wirkung": "zaertlich"}], "unklar": []}
        with patch.object(urllib.request, "urlopen", FakeProvider([], regie=analyse)):
            return cl.post("/api/kernel/regie", headers=H, json={"sessionId": SID, "actorUserId": "admin",
                                                                  "text": "Johann streichelt Mara.", "actorId": J})

    def god(cl):
        with patch.object(urllib.request, "urlopen", FakeProvider([], gott=lambda p: {"schmerz": "stark", "beleg": "starke Schmerzen"})):
            return cl.post("/api/kernel/god", headers=H, json={"sessionId": SID, "actorUserId": "admin",
                                                                "text": "Mara hat starke Schmerzen.", "scope": "body", "targetId": M})

    from test_v92_avatar_route import act as av_act

    def prepare_tat(cl):
        # Avatar-Tat (Plan aus der P25-Attrappe): erreicht _extract_user_plan -> _boundary_reference_step
        def senden(kl=None):
            prov = FakeProvider([plan("action", "act", [av_act("Ich streichle Mara", akteur="ich", ziel="Mara Nowak")])])
            with patch.object(urllib.request, "urlopen", prov):
                return cl.post("/api/kernel/prepare", headers=H, json={
                    "sessionId": AV, "actorUserId": "admin", "trace_id": "kpr_fp2", "truth": avatar_truth("Ich streichle Mara."),
                    "speaker": {"id": M, "name": "Mara Nowak"},
                    "present": [{"id": J, "name": "Johann Bruckner"}, {"id": M, "name": "Mara Nowak"}],
                    **({"klaerungen": kl} if kl else {})})
        r = senden()
        j = r.get_json(silent=True) or {}
        if r.status_code == 422 and j.get("code") == "IDENTITAET_KLAEREN":
            r = senden([{"frage": q.get("frage"), "id": M} for q in j.get("klaerung") or []])
        return r

    def johann_lehnt_mara_ab(cl):
        # Vorbereitung (echte Writer): Johann lehnt jede Beruehrung durch Mara ab
        from matrix_api import repos
        with closing(connect(dbp)) as c:
            hoechster = max([0] + [int(json.loads(j).get("turn") or 0) for (j,) in
                                   c.execute("SELECT json FROM scene_facts WHERE session_id=?", (AV,))])
            repos.create_session_proposition(c, AV, {"id": "p_mj", "kind": "koerperkontakt", "actorId": M, "targetId": J,
                                                    "state": "open", "evidence": []}, "admin")
            repos.append_session_turn_truth(c, AV, {"id": "tt0_mj", "role": "character", "authority": "character",
                                                    "speaker_id": J, "present_ids": [J, M, G], "hears_ids": [M, G],
                                                    "sees_ids": [M, G], "turn": hoechster}, "admin")
            repos.append_session_fact(c, AV, {"id": "f0_mj", "kind": "lifecycle", "event_kind": "refusal", "actorId": J,
                                              "targetId": M, "sourceTurnId": "tt0_mj", "propositionId": "p_mj", "turn": hoechster,
                                              "validated": True, "text": "Fass mich nicht an",
                                              "payload": {"koerperkontakt": {"scope": "jede_beruehrung",
                                                                             "beleg": "Fass mich nicht an"}}}, "admin")
            c.commit()

    def commit_tat_vorb(cl):
        r = johann_lehnt_mara_ab(cl)
        if r is not None and getattr(r, "status_code", 200) != 200:
            return r
        return belege(cl, {"speech": "Komm her.", "action": "Mara streichelt Johann", "wirkung": {"art": "zaertlich"}})

    def commit_und_wangengrenze(cl):
        # Vorbereitung: offenen Turn schliessen, dann (echte Writer) Mara lehnt die Beruehrung ihrer Wange ab
        r = commit(cl)
        if r.status_code != 200:
            return r
        from matrix_api import repos
        with closing(connect(dbp)) as c:
            hoechster = max([0] + [int(json.loads(j).get("turn") or 0) for (j,) in
                                   c.execute("SELECT json FROM scene_facts WHERE session_id=?", (AV,))])
            repos.append_session_turn_truth(c, AV, {"id": "tt_wange", "role": "character", "authority": "character",
                                                    "speaker_id": M, "present_ids": [J, M, G], "hears_ids": [J, G],
                                                    "sees_ids": [J, G], "turn": hoechster}, "admin")
            repos.append_session_fact(c, AV, {"id": "f_wange", "kind": "lifecycle", "event_kind": "refusal", "actorId": M,
                                              "targetId": J, "sourceTurnId": "tt_wange", "propositionId": f"p_kk_{AV}",
                                              "turn": hoechster, "validated": True, "text": "Nicht meine Wange",
                                              "payload": {"koerperkontakt": {"scope": "eingeschraenkt",
                                                                             "einschraenkung": "meine Wange",
                                                                             "beleg": "Nicht meine Wange"}}}, "admin")
            c.commit()
        return r

    # (name, session, vorbereitung ohne Ausfall, gemessene Anfrage)
    # Die Vorlage enthaelt einen offenen Avatar-Turn: ein weiteres prepare waere korrekt 409 (vorher abgewiesen).
    # Fuer prepare-Szenarien wird der offene Turn deshalb zuerst ueber commit geschlossen (ohne Ausfall).
    anfragen = [("commit", AV, commit_vorb, commit_belegt), ("puppet", SID, None, puppet),
                ("regie", SID, None, regie), ("god", SID, None, god),
                ("prepare_nach_commit", AV, commit, prepare), ("prepare_avatar_tat", AV, commit, prepare_tat),
                ("prepare_avatar_tat_mit_wangengrenze", AV, commit_und_wangengrenze, prepare_tat),
                ("commit_mit_tat_gegen_grenze", AV, commit_tat_vorb, commit_belegt)]
    ergebnis = []
    for name, sid, vorb, call in anfragen:
        def frisch():
            shutil.copy2(a.vorlage, dbp)
            if vorb is not None:
                st.update(k=None, n=0, erster_fehler=None)
                vr = vorb(client())
                if vr is not None and getattr(vr, "status_code", 200) != 200:
                    raise RuntimeError(f"Vorbereitung {name} HTTP {vr.status_code}")
        frisch()
        st.update(k=None, n=0, erster_fehler=None)
        r = call(client())
        n_ok, status_ok = st["n"], r.status_code
        punkte = []
        for k in range(min(n_ok, a.max_k)):
            frisch()
            with closing(connect(dbp)) as c:
                vorher = digest(c, sid)
            st.update(k=k, n=0, erster_fehler=None, digest_bei_ausfall=None, sid=sid)
            try:
                r = call(client())
                status, j = r.status_code, (r.get_json(silent=True) or {})
            except Exception as e:
                status, j = None, {"code": f"AUSNAHME:{type(e).__name__}"}
            with closing(connect(dbp)) as c:
                nachher = digest(c, sid)
            erfolg = bool(status and 200 <= status < 300 and j.get("ok") is True)
            bei = st["digest_bei_ausfall"]
            nach_ausfall_geschrieben = bei is not None and nachher != bei
            punkte.append({"k": k, "status": status, "code": j.get("code") or j.get("error"),
                           "sqlite_unveraendert": vorher == nachher, "erfolgsmeldung": erfolg,
                           "geschrieben_nach_ausfall": nach_ausfall_geschrieben,
                           "teilcommit_vor_ausfall": bei is not None and bei != vorher,
                           "fail_open": nach_ausfall_geschrieben or erfolg,
                           # 06a / M2: gemeldete Speicherung (Antwortfeld) gegen den gemessenen SQLite-Befund
                           "eingabe_gespeichert_gemeldet": j.get("eingabeGespeichert"),
                           "meldung_stimmt": (None if not name.startswith("prepare") else
                                              (isinstance(j.get("eingabeGespeichert"), bool)
                                               and j.get("eingabeGespeichert") == (bei is not None and bei != vorher))),
                           "app_stapel_erster_fehler": st["erster_fehler"]})
        ergebnis.append({"anfrage": name, "kernaufrufe_ohne_ausfall": n_ok, "status_ohne_ausfall": status_ok,
                         "geprueft_k": len(punkte), "fail_open": [p for p in punkte if p["fail_open"]],
                         "status_verteilung": sorted({f"{p['status']}:{p['code']}" for p in punkte}), "punkte": punkte})
        ergebnis[-1]["teilcommit_vor_ausfall"] = [p["k"] for p in punkte if p["teilcommit_vor_ausfall"]]
        ergebnis[-1]["meldung_falsch"] = [p["k"] for p in punkte if p["meldung_stimmt"] is False]
        print(f"{name:8} Kernaufrufe {n_ok:4} geprueft {len(punkte):4} fail_open {len(ergebnis[-1]['fail_open'])} "
              f"teilcommit_vor_ausfall {len(ergebnis[-1]['teilcommit_vor_ausfall'])} meldung_falsch {len(ergebnis[-1]['meldung_falsch'])} "
              f"Status {ergebnis[-1]['status_verteilung']}")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps({"anfragen": ergebnis}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
