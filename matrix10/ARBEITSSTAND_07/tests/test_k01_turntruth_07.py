"""Stand 07 / K-01: serverseitige TurnTruth- und Commit-Bindung - Positiv-, Negativ- und Isolationsproben.

Echte P25-App (create_app, Flask-Testclient) auf frischer Temp-SQLite mit P25-Seed; echte Routen prepare -> formulate ->
commit wie die Oberflaeche (kernel-bridge.ts, chat.$sessionId.tsx). Die Formulierung ist die echte lokale Synapse
(Provider "synapse" in der Config, kein Netz) - kein Mock, kein vorab geschriebener Zustand.
MATRIX07_ROOT = Produktordner (Stage mit Rust-Bibliothek). Aufruf: python3 -m pytest <diese Datei>
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.environ.get("MATRIX07_ROOT") or str(Path.cwd())
sys.path.insert(0, ROOT)
J, M, G = "char_g7_johann", "char_g7_mara", "char_g7_gustav"
TABLES = ("scene_facts", "turns", "turn_truth", "memories", "witness_knowledge", "propositions", "goals", "relationships")


class Chain(unittest.TestCase):
    avatar: str | None = None

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="k01_")
        self.dbp = str(Path(self.tmp) / "t.sqlite")
        os.environ["MATRIX_DB"] = self.dbp
        os.environ["MATRIX_LIVE_LOG"] = str(Path(self.tmp) / "live.log")
        for k in ("OPENAI_API_KEY", "XAI_API_KEY", "MATRIX_API_KEY"):
            os.environ.pop(k, None)
        from matrix_api.db import connect, init_schema
        from matrix_api.seed_builtin import seed_if_missing
        from matrix_api.repos import create_session
        with closing(connect(self.dbp)) as c:
            init_schema(c)
            seed_if_missing(c)
            c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\",\"name\":\"admin\"}')")
            names = {json.loads(r[1])["name"]: json.loads(r[1]) for r in c.execute("select id,json from characters")}
            self.J = next(v for k, v in names.items() if "Johann" in k)
            self.M = next(v for k, v in names.items() if "Mara" in k)
            self.W = self.J["worldId"]
            others = [v for v in names.values() if v.get("worldId") == self.W and v["id"] not in (self.J["id"], self.M["id"])]
            self.G = others[0] if others else None
            pres = [self.J["id"], self.M["id"]] + ([self.G["id"]] if self.G else [])
            for sid, av in (("ses_k01", self.avatar_id()), ("ses_fremd", None)):
                create_session(c, {"id": sid, "worldId": self.W, "name": sid, "presentIds": pres, "avatarId": av,
                                   "role": "teilnehmer"}, "admin")
            c.commit()
        from matrix_api import app as appmod
        self.appmod = appmod
        self.client = appmod.create_app(self.dbp).test_client()
        self.H = {"X-Matrix-Actor": "admin"}
        r = self.client.put("/api/config", headers=self.H, json={"scope": "user", "provider": "synapse"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        self.fremd0 = self.digest("ses_fremd")

    def avatar_id(self):
        return None

    # ---------- helpers (same request shapes as kernel-bridge.ts / chat.$sessionId.tsx)
    def session(self, sid="ses_k01"):
        r = self.client.get(f"/api/sessions/{sid}", headers=self.H)
        return r.get_json().get("session") or r.get_json()

    def digest(self, sid):
        h = hashlib.sha256()
        with closing(sqlite3.connect(self.dbp)) as c:
            for t in TABLES:
                for row in c.execute(f"SELECT * FROM {t} WHERE session_id=? ORDER BY rowid", (sid,)):
                    h.update(repr(row).encode())
            h.update(repr(c.execute("SELECT json FROM sessions WHERE id=?", (sid,)).fetchall()).encode())
        return h.hexdigest()

    def facts(self, sid="ses_k01"):
        return [f for f in (self.session(sid).get("facts") or []) if isinstance(f, dict)]

    def prepare(self, text, speaker=None, speak_as="operator", input_kind="speech", extra=None, target=None):
        s = self.session()
        truth = {"userId": "admin", "operatorId": "admin", "worldId": s["worldId"], "sessionId": s["id"], "role": s.get("role"),
                 "speakerId": speaker, "responseSpeakerId": speaker, "avatarId": s.get("avatarId"),
                 "inputActorId": {"operator": "user", "observer": "observer", "avatar": s.get("avatarId")}.get(speak_as, "user"),
                 "speakAs": speak_as, "targetId": target, "authority": "character",
                 "presentIds": s["scene"]["presentIds"], "inputKind": input_kind, "text": text, **(extra or {})}
        return self.client.post("/api/kernel/prepare", headers=self.H, json={
            "session": s, "actorUserId": "admin", "truth": truth, "speaker": {"id": speaker} if speaker else {}})

    def formulate(self, pj, text=""):
        s = pj["session"]
        return self.client.post("/api/llm/formulate", headers=self.H, json={
            "spiegel": (pj.get("brainContext") or {}).get("spiegel"), "sessionId": s["id"], "sourceTurnId": pj["truth"]["id"],
            "speakerId": pj["truth"].get("speaker_id"), "turnIndex": s.get("turnIndex"), "text": text, "scope": "user",
            "inputKind": pj["truth"].get("input_kind") or "speech", "provider": "synapse", "turnBeleg": pj.get("turnBeleg")})

    def commit(self, pj, fj=None, result=None, extra=None, truth=None):
        res = result if result is not None else ((fj or {}).get("result") or {"speech": "", "action": None})
        body = {"session": pj["session"], "actorUserId": "admin", "truth": truth or pj["truth"],
                "speaker": {"id": pj["truth"].get("speaker_id")},
                "result": {"speech": res.get("speech"), "action": res.get("action"),
                           **({"proposals": res["proposals"]} if res.get("proposals") else {})},
                "fired": (pj.get("brainContext") or {}).get("spiegel", {}).get("fired") or [],
                "turnBeleg": pj.get("turnBeleg"), **({"formulierungsBeleg": fj["formulierungsBeleg"]} if fj and fj.get("formulierungsBeleg") else {}),
                **(extra or {})}
        return self.client.post("/api/kernel/commit", headers=self.H, json=body)

    def full_turn(self, text, speaker, speak_as="operator"):
        r = self.prepare(text, speaker, speak_as)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:400])
        pj = r.get_json()
        f = self.formulate(pj, text)
        self.assertEqual(f.status_code, 200, f.get_data(as_text=True)[:400])
        fj = f.get_json()
        self.assertTrue(fj.get("formulierungsBeleg"), fj)
        c = self.commit(pj, fj)
        self.assertEqual(c.status_code, 200, c.get_data(as_text=True)[:400])
        return pj, fj, c.get_json()

    def tearDown(self):
        self.assertEqual(self.digest("ses_fremd"), self.fremd0, "fremde Session wurde veraendert")


class Positiv(Chain):
    def test_operator_turn_binds_user_figure_and_server_text_and_follow_up_reads_it(self):
        pj, fj, cj = self.full_turn("Mara, wie geht es dir heute?", self.M["id"])
        tt = pj["truth"]["id"]
        mine = [f for f in self.facts() if f.get("sourceTurnId") == tt]
        inp = [f for f in mine if f.get("kind") == "speech" and f.get("actorId") == "user"]
        out = [f for f in mine if f.get("kind") == "speech" and f.get("actorId") == self.M["id"]]
        self.assertEqual(len(inp), 1, mine)
        self.assertEqual(len(out), 1, mine)
        self.assertEqual(out[0].get("text"), fj["result"]["speech"])        # genau der Servertext
        # Folgeturn: die naechste Vorbereitung liest diese Rede (Recall/Dialog des Spiegels)
        r = self.prepare("Und was sagt Johann dazu?", self.J["id"])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        sp = json.dumps(r.get_json().get("brainContext") or {}, ensure_ascii=False)
        self.assertIn(fj["result"]["speech"][:25], sp)

    def test_autochat_follow_up_without_text(self):
        self.full_turn("Mara, hallo.", self.M["id"])
        r = self.prepare("", self.J["id"], "operator", "autochat")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        pj = r.get_json()
        f = self.formulate(pj)
        self.assertEqual(f.status_code, 200, f.get_data(as_text=True)[:300])
        c = self.commit(pj, f.get_json())
        self.assertEqual(c.status_code, 200, c.get_data(as_text=True)[:300])
        self.assertTrue(any(x.get("actorId") == self.J["id"] and x.get("sourceTurnId") == pj["truth"]["id"] for x in self.facts()))

    def test_observer_comment_needs_no_formulation(self):
        r = self.prepare("Ein kalter Wind zieht herein.", self.M["id"], "observer", "comment")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        pj = r.get_json()
        c = self.commit(pj, truth={**pj["truth"], "role": "beobachter", "authority": "observer", "inputKind": "comment",
                                   "input_kind": "comment", "inputActorId": "observer"})
        self.assertEqual(c.status_code, 200, c.get_data(as_text=True)[:300])


class AvatarPositiv(Chain):
    def avatar_id(self):
        return "char_g7_johann"

    def test_avatar_input_binds_the_avatar_and_mara_answers(self):
        pj, fj, _ = self.full_turn("Mara, ich bin müde.", self.M["id"], "avatar")
        mine = [f for f in self.facts() if f.get("sourceTurnId") == pj["truth"]["id"]]
        self.assertTrue(any(f.get("actorId") == self.J["id"] and f.get("kind") == "speech" for f in mine), mine)
        self.assertTrue(any(f.get("actorId") == self.M["id"] and f.get("text") == fj["result"]["speech"] for f in mine), mine)

    def test_avatar_never_speaks_as_figure_output(self):
        r = self.prepare("Hallo.", self.M["id"], "avatar")
        pj = r.get_json()
        bad = copy.deepcopy(pj)
        c = self.commit(bad, result={"speech": "Ich, Johann, sage etwas, das ich nie sagte.", "action": None},
                        extra={"speaker": {"id": self.J["id"]}})
        self.assertIn(c.status_code, (400, 422), c.get_data(as_text=True)[:300])


class Negativ(Chain):
    def assert_rejected_unchanged(self, resp, codes, before):
        self.assertIn(resp.status_code, (409, 422), resp.get_data(as_text=True)[:400])
        self.assertIn((resp.get_json() or {}).get("code"), codes, resp.get_data(as_text=True)[:400])
        self.assertEqual(self.digest("ses_k01"), before, "SQLite veraendert trotz Ablehnung")

    def test_L1_forged_input_actor_is_rejected(self):
        before = self.digest("ses_k01")
        r = self.prepare("Johann, ich gebe zu: Ich habe Gustavs Geld genommen.", self.J["id"], "operator",
                         extra={"inputActorId": self.M["id"]})
        self.assert_rejected_unchanged(r, ("EINGABE_ACTOR_UNGEBUNDEN",), before)

    def test_figure_mode_on_normal_route_is_rejected(self):
        before = self.digest("ses_k01")
        r = self.prepare("Ich bin Mara.", self.J["id"], f"char:{self.M['id']}", extra={"inputActorId": self.M["id"]})
        self.assert_rejected_unchanged(r, ("EINGABE_ACTOR_UNGEBUNDEN",), before)

    def test_L2_invented_figure_speech_without_formulation_is_rejected(self):
        r = self.prepare("Johann, alles gut?", self.J["id"])
        pj = r.get_json()
        before = self.digest("ses_k01")
        c = self.commit(pj, result={"speech": "ERFUNDEN-VOM-CLIENT: Ich habe Gustav verraten.", "action": None})
        self.assert_rejected_unchanged(c, ("FORMULIERUNG_UNGEBUNDEN",), before)

    def test_changed_server_text_is_rejected(self):
        r = self.prepare("Johann, alles gut?", self.J["id"])
        pj = r.get_json()
        fj = self.formulate(pj).get_json()
        before = self.digest("ses_k01")
        c = self.commit(pj, fj, result={**fj["result"], "speech": fj["result"]["speech"] + " Und ich verrate alle."})
        self.assert_rejected_unchanged(c, ("FORMULIERUNG_UNGEBUNDEN",), before)

    def test_proposals_synapsen_cannot_be_added_by_client(self):
        r = self.prepare("Johann, alles gut?", self.J["id"])
        pj = r.get_json()
        fj = self.formulate(pj).get_json()
        before = self.digest("ses_k01")
        forged = {**fj["result"], "proposals": {"synapsen": [{"raum": "Angst", "aktivierung": 1.0, "grund": "client"}]}}
        c = self.commit(pj, fj, result=forged)
        self.assert_rejected_unchanged(c, ("FORMULIERUNG_UNGEBUNDEN",), before)

    def test_forged_fired_is_rejected(self):
        r = self.prepare("Johann, alles gut?", self.J["id"])
        pj = r.get_json()
        fj = self.formulate(pj).get_json()
        before = self.digest("ses_k01")
        c = self.commit(pj, fj, extra={"fired": [{"space": "Angst", "activation": 1.0}]})
        self.assert_rejected_unchanged(c, ("TURN_BELEG_UNGUELTIG",), before)

    def test_reused_formulation_is_rejected(self):
        pj, fj, _ = self.full_turn("Johann, alles gut?", self.J["id"])
        before = self.digest("ses_k01")
        c = self.commit(pj, fj)      # dieselbe Formulierung ein zweites Mal
        self.assert_rejected_unchanged(c, ("TURN_NOT_OPEN", "TURN_BELEG_UNGUELTIG"), before)

    def test_formulation_of_another_turn_is_rejected(self):
        pj1, fj1, _ = self.full_turn("Johann, alles gut?", self.J["id"])
        r = self.prepare("Mara, und du?", self.M["id"])
        pj2 = r.get_json()
        before = self.digest("ses_k01")
        c = self.commit(pj2, fj1, result=fj1["result"])
        self.assert_rejected_unchanged(c, ("FORMULIERUNG_UNGEBUNDEN",), before)

    def test_older_attempt_of_the_same_input_is_rejected(self):
        r = self.prepare("Johann, alles gut?", self.J["id"])
        pj = r.get_json()
        alt = self.formulate(pj).get_json()
        neu = self.formulate(pj).get_json()
        self.assertNotEqual(alt["formulierungsBeleg"], neu["formulierungsBeleg"])
        before = self.digest("ses_k01")
        c = self.commit(pj, alt)
        self.assert_rejected_unchanged(c, ("FORMULIERUNG_UNGEBUNDEN",), before)
        self.assertEqual(self.commit(pj, neu).status_code, 200)

    def test_tampered_turn_and_changed_truth_are_rejected(self):
        r = self.prepare("Johann, alles gut?", self.J["id"])
        pj = r.get_json()
        fj = self.formulate(pj).get_json()
        before = self.digest("ses_k01")
        raw, sig = pj["turnBeleg"].split(".")
        c = self.commit({**pj, "turnBeleg": raw[:-4] + "AAAA." + sig}, fj)
        self.assert_rejected_unchanged(c, ("TURN_BELEG_UNGUELTIG",), before)
        c = self.commit(pj, fj, truth={**pj["truth"], "speaker_id": self.M["id"], "speakerId": self.M["id"]})
        self.assert_rejected_unchanged(c, ("TURN_BELEG_UNGUELTIG", "FORMULIERUNG_UNGEBUNDEN"), before)

    def test_restart_invalidates_unfinished_formulations(self):
        r = self.prepare("Johann, alles gut?", self.J["id"])
        pj = r.get_json()
        fj = self.formulate(pj).get_json()
        before = self.digest("ses_k01")
        old = self.appmod._BELEG_KEY
        self.appmod._BELEG_KEY = os.urandom(32)        # neuer Serverprozess = neuer Schluessel (V65U)
        try:
            c = self.commit(pj, fj)
            self.assert_rejected_unchanged(c, ("TURN_BELEG_UNGUELTIG",), before)
        finally:
            self.appmod._BELEG_KEY = old

    def test_formulate_needs_a_prepared_turn(self):
        r = self.prepare("Johann, alles gut?", self.J["id"])
        pj = r.get_json()
        f = self.formulate({**pj, "turnBeleg": None})
        self.assertEqual(f.status_code, 422, f.get_data(as_text=True)[:300])
        f = self.formulate({**pj, "truth": {**pj["truth"], "speaker_id": self.M["id"]}})
        self.assertEqual(f.status_code, 422, f.get_data(as_text=True)[:300])

    def test_unconscious_selected_speaker_cannot_speak(self):
        from matrix_api.db import connect
        with closing(connect(self.dbp)) as c:
            row = c.execute("SELECT json FROM sessions WHERE id='ses_k01'").fetchone()
            env = json.loads(row[0])
            env.setdefault("runtimes", {}).setdefault(self.M["id"], {"characterId": self.M["id"]})["consciousness"] = 0.0
            c.execute("UPDATE sessions SET json=? WHERE id='ses_k01'", (json.dumps(env),))
            c.commit()
        before = self.digest("ses_k01")
        r = self.prepare("Mara, hörst du mich?", self.M["id"])
        self.assert_rejected_unchanged(r, ("SPEAKER_NOT_CAPABLE",), before)


class Wahrnehmung(Chain):
    def test_explicitly_empty_hearer_list_is_not_everybody(self):
        # Hoerer ueber die vorhandene Bedienung /api/kernel/perception: ausdruecklich niemand hoert ausser den Sprechenden
        s = self.session()
        r = self.client.post("/api/kernel/perception", headers=self.H, json={"sessionId": s["id"], "kind": "hearsIds",
                                                                             "ids": [], "explicit": True})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        pj, fj, _ = self.full_turn("Mara, ein Geheimnis: Ich gehe morgen fort.", self.M["id"])
        s = self.session()
        sp = next(f for f in s.get("facts") or [] if f.get("sourceTurnId") == pj["truth"]["id"] and f.get("actorId") == self.M["id"])
        # P25-Rueckfall `hearsIds or presentIds`: die Zeugenliste von Behauptungsregister und Frames (truth.register_claim,
        # conjunctive.apply_plan) nahm bei leerer Hoererliste alle Anwesenden
        reg = [x for x in (s.get("claims") or []) + (s.get("frames") or []) if isinstance(x, dict) and sp["id"] in json.dumps(x)]
        self.assertTrue(reg, "kein Register-/Frame-Eintrag zur Figurenrede - Probe misst nichts")
        wit = {w for x in reg for w in (x.get("witnesses") or [])}
        self.assertNotIn(self.J["id"], wit, reg)
        if self.G:
            self.assertNotIn(self.G["id"], wit, reg)


class W2(unittest.TestCase):
    """Lifecycle-Evidenz ist die eigene Aeusserung des Actors (Kernel- und Leseseite)."""

    def setUp(self):
        from matrix_api import kernel as K
        from matrix_api import scene_state as SC
        self.K, self.SC = K, SC

    def base(self, johann_answer: bool):
        s = {"id": "ses", "worldId": "w", "userId": "admin", "avatarId": J, "turnIndex": 2, "scene": {"presentIds": [J, M]},
             "facts": [{"id": "fM", "kind": "speech", "actorId": M, "targetId": J, "text": "Kommst du mit ins Kino?", "turn": 1,
                        "sourceTurnId": "ttA", "validated": True}],
             "turnTruths": [{"id": "ttA"}, {"id": "ttB"}], "goals": [], "runtimes": {},
             "propositions": [{"id": "p1", "kind": "request", "actorId": M, "targetId": J, "status": "open", "text": "Kino"}]}
        if johann_answer:
            s["facts"].append({"id": "fJ", "kind": "speech", "actorId": J, "targetId": M, "text": "Ja, gern.", "turn": 2,
                               "sourceTurnId": "ttB", "validated": True})
        return s

    def test_answer_without_own_utterance_changes_nothing(self):
        out = self.K.apply_proposition(self.base(False), actor_id=J, text="Ja, gern.", kind="acceptance", target_id=M,
                                       proposition_id="p1", fact_id=None, turn=2)
        self.assertEqual(out["propositions"][0]["status"], "open")
        self.assertFalse([f for f in out["facts"] if f.get("kind") == "lifecycle"])

    def test_named_foreign_fact_is_no_evidence(self):
        out = self.K.apply_proposition(self.base(True), actor_id=J, text="Ja, gern.", kind="acceptance", target_id=M,
                                       proposition_id="p1", fact_id="fM", turn=2)
        self.assertEqual(out["propositions"][0]["status"], "open")

    def test_own_answer_stays_valid_avatar_input_with_other_response_speaker(self):
        for fid in ("fJ", None):
            out = self.K.apply_proposition(self.base(True), actor_id=J, text="Ja, gern.", kind="acceptance", target_id=M,
                                           proposition_id="p1", fact_id=fid, turn=2)
            lf = [f for f in out["facts"] if f.get("kind") == "lifecycle"]
            self.assertEqual(out["propositions"][0]["status"], "accepted")
            self.assertEqual(lf[0].get("responds_to_fact_id"), "fJ")
            self.assertTrue(self.SC.lifecycle_bound(out, lf[0]))

    def test_write_boundary_quellturn_rule_keeps_avatar_and_figure_answers(self):
        # echte Schreibgrenze (repos.append_session_fact -> _check_lifecycle_actor) auf frischer SQLite
        import tempfile as _tf
        from matrix_api.db import connect, init_schema
        from matrix_api.seed_builtin import seed_if_missing
        from matrix_api import repos
        from matrix_api.repos import WriterError
        dbp = str(Path(_tf.mkdtemp(prefix="k01w2_")) / "t.sqlite")
        with closing(connect(dbp)) as c:
            init_schema(c)
            seed_if_missing(c)
            c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\"}')")
            w = c.execute("select world_id from characters where id=?", (M,)).fetchone()[0]
            repos.create_session(c, {"id": "sW", "worldId": w, "name": "sW", "presentIds": [J, M], "avatarId": J}, "admin")
            repos.create_session_proposition(c, "sW", {"id": "p", "kind": "request", "actorId": J, "targetId": M,
                                                      "state": "open", "evidence": []}, "admin")
            repos.append_session_turn_truth(c, "sW", {"id": "ttJ", "role": "character", "authority": "character",
                                                      "speaker_id": J, "present_ids": [J, M], "turn": 1}, "admin")
            repos.append_session_turn_truth(c, "sW", {"id": "ttAv", "role": "teilnehmer", "authority": "character",
                                                      "speaker_id": J, "input_actor_id": M, "present_ids": [J, M], "turn": 2}, "admin")
            c.commit()
            row = {"kind": "lifecycle", "event_kind": "acceptance", "actorId": M, "targetId": J, "propositionId": "p",
                   "validated": True, "text": "Ja."}
            with self.assertRaises(WriterError):     # Mara ist im Quellturn ttJ keine Partei (nur Johann spricht)
                repos.append_session_fact(c, "sW", {**row, "id": "l1", "sourceTurnId": "ttJ", "turn": 1}, "admin")
            c.rollback()
            # gueltig: Mara ist Eingabe-Actor ihres Quellturns (die Antwortfigur ist eine andere) - kein "actor == speaker"
            repos.append_session_fact(c, "sW", {**row, "id": "l2", "sourceTurnId": "ttAv", "turn": 2}, "admin")
            c.commit()

    def test_stored_lifecycle_with_foreign_evidence_is_not_bound(self):
        s = self.base(False)
        lf = {"id": "lfX", "kind": "lifecycle", "event_kind": "acceptance", "actorId": J, "authority": "character",
              "proposition_id": "p1", "propositionId": "p1", "responds_to_fact_id": "fM", "turn": 1}
        s["facts"].append(lf)
        self.assertFalse(self.SC.lifecycle_bound(s, lf))


if __name__ == "__main__":
    unittest.main()
