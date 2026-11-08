"""V92 Paket-8-Pruefung (05.11.2026): Avatar-Eingang ueber die echte Route /api/kernel/prepare, SQLite-Ruecklesung.

Gleiche Regel wie Puppet (bind_input_components -> input_binding_outcome): der Avatar speichert genau
die validierte eigene Rede und die validierten eigenen Handlungen. Nichts Validiertes -> 422, nichts gespeichert, Text bleibt.
Ohne Lesung (kein Provider): ungemarkter Text ist die direkte Rede des Avatars, eine *markierte* Handlung wird nicht gespeichert.
"""
import json
import os
import tempfile
import unittest
import urllib.request
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import test_v84_kausal_chain  # noqa: F401  (offline Flask shim wie die übrigen Tests)
from matrix_api.db import connect, init_schema
from matrix_api.seed_builtin import seed_if_missing
from matrix_api.repos import create_session, get_session
from test_v92_puppet_vertrag import FakeProvider, plan, frage_merken, als_antwort

GUT = {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "figur"}


def act(seg, akteur="Johann Bruckner", geschieht=True, ziel="Mara Nowak"):
    return {"typ": "handlung", "segment": seg, "akteur": akteur, "ziel": ziel, "zeit": "jetzt", "wirkung": "ohne_koerperwirkung",
            "bezug": None, "geschieht": geschieht}


def rede(seg, akteur="Johann Bruckner", einleitung=None):
    return {"typ": "rede", "segment": seg, "akteur": akteur, "ziel": "Mara Nowak", "zeit": "jetzt", "wirkung": None, "bezug": None,
            "einleitung": einleitung}


class AvatarRouteChain(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(); self.addCleanup(self._tmp.cleanup)
        self.dbp = str(Path(self._tmp.name) / "t.sqlite")
        self._env = patch.dict(os.environ, {"MATRIX_DB": self.dbp, "MATRIX_LIVE_LOG": str(Path(self._tmp.name) / "log.log")}, clear=False)
        self._env.start(); self.addCleanup(self._env.stop)
        os.environ.pop("PYTEST_CURRENT_TEST", None); os.environ.pop("MATRIX_SKIP_SEED", None)
        with closing(connect(self.dbp)) as c:
            init_schema(c); seed_if_missing(c)
            c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\"}')")
            c.execute("INSERT INTO config(scope,scope_id,json) VALUES(?,?,?)", ("user", "admin", json.dumps({"scope": "user", "scope_id": "admin", "provider": "openai", "model": "t", "apiKey": "sk-TESTONLY", "endpoint": "http://127.0.0.1:9/v1/chat/completions"})))
            ch = {json.loads(r[1])["name"]: json.loads(r[1]) for r in c.execute("select id,json from characters")}
            self.J = next(v for k, v in ch.items() if "Johann" in k); self.M = next(v for k, v in ch.items() if "Mara" in k)
            W = c.execute("select id from worlds limit 1").fetchone()[0]
            create_session(c, {"id": "ses_av", "worldId": W, "name": "AV", "presentIds": [self.J["id"], self.M["id"]],
                               "avatarId": self.J["id"], "role": "teilnehmer"}, "admin"); c.commit()
        from matrix_api import app as appmod
        self.client = appmod.create_app(self.dbp).test_client()
        self.assertEqual(self.session().get("avatarId"), self.J["id"], "session with avatar")

    def session(self):
        with closing(connect(self.dbp)) as c: return get_session(c, "admin", "ses_av")

    def snapshot(self, s):
        return {k: json.dumps(s.get(k), sort_keys=True, ensure_ascii=False) for k in ("turns", "facts", "turnTruths", "relations", "propositions")} | {"turnIndex": s.get("turnIndex"), "pending": s.get("pendingInputTurnId")}

    def prepare(self, provider, text, klaerungen=None):
        s = self.session()
        truth = {"userId": "admin", "operatorId": "admin", "worldId": s["worldId"], "sessionId": "ses_av", "role": "teilnehmer",
                 "speakerId": self.M["id"], "responseSpeakerId": self.M["id"], "avatarId": self.J["id"], "inputActorId": self.J["id"],
                 "speakAs": "avatar", "targetId": self.M["id"], "authority": "teilnehmer", "presentIds": s["scene"]["presentIds"],
                 "inputKind": "speech", "text": text, "userName": self.J["name"]}
        klaerungen = als_antwort(self, "ses_av", text, klaerungen)   # V92 Paket 17: answer the issued question, like the UI
        with patch.object(urllib.request, "urlopen", provider):
            return frage_merken(self, "ses_av", text, self.client.post("/api/kernel/prepare", headers={"X-Matrix-Actor": "admin"}, json={
                "session": s, "actorUserId": "admin", "trace_id": "kpr_test", "truth": truth,
                "speaker": {"id": self.M["id"], "name": self.M["name"]},
                "present": [{"id": self.J["id"], "name": self.J["name"]}, {"id": self.M["id"], "name": self.M["name"]}],
                **({"klaerungen": klaerungen} if klaerungen is not None else {})}))

    def mine(self, kind):
        return [f.get("text") for f in self.session()["facts"] if f.get("actorId") == self.J["id"] and f.get("kind") == kind]

    def rejected(self, provider, text, code="EINGABE_NICHT_AUSFUEHRBAR"):
        before = self.snapshot(self.session())
        r = self.prepare(provider, text)
        self.assertEqual(r.status_code, 422, r.get_data(as_text=True)[:300]); self.assertEqual((r.get_json() or {}).get("code"), code)
        self.assertIn("Nichts wurde gespeichert", (r.get_json() or {}).get("message", ""))
        self.assertEqual(self.snapshot(self.session()), before, "SQLite unveraendert, keine offene Eingabe")
        return r

    def asked(self, provider, text):
        """V92 Paket 16: the greeting "Hallo Mara" cannot prove the boundary of the name ("Hallo" vs a first name) - the route asks
        before anything is stored; returns the question."""
        r = self.rejected(provider, text, code="IDENTITAET_KLAEREN")
        k = (r.get_json() or {}).get("klaerung") or []
        self.assertEqual([(q["text"], [c["id"] for c in q["kandidaten"]]) for q in k], [("Hallo Mara", [self.M["id"]])])
        return [{"frage": k[0]["frage"], "id": self.M["id"]}]   # V92 Paket 17: the answer to exactly this issued question

    # ---- Negativgrenzen (Paket-8-Pruefung C1-C4 und Paket-7 A7-01/02) ----
    def test_marker_denied_act_is_rejected(self):
        prov = FakeProvider([plan("action", "act", [act("Johann küsst Mara nicht.")])],
                            vollzug=lambda p: {"geschieht": False, "art": "verneint", "beleg": "nicht", "taeter": "figur"})
        self.rejected(prov, "*Johann küsst Mara nicht.*")

    def test_marker_foreign_act_is_rejected(self):
        prov = FakeProvider([plan("action", "act", [act("Mara küsst Johann.", akteur="Mara Nowak", ziel="Johann Bruckner")])],
                            vollzug=lambda p: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "Mara Nowak"})
        self.rejected(prov, "*Mara küsst Johann.*")

    def test_foreign_speech_after_own_marker_is_not_the_avatars_speech(self):
        prov = FakeProvider([plan("action", "act", [act("Johann lächelt"), rede("Lass mich in Ruhe!", akteur="Mara Nowak", einleitung="Mara sagt:")])])
        r = self.prepare(prov, "*Johann lächelt.* Mara sagt: Lass mich in Ruhe!")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.mine("action"), ["Johann lächelt"]); self.assertEqual(self.mine("speech"), [])
        tt = self.session()["turnTruths"][-1]
        self.assertIn("rede_akteur_ist_nicht_der_sprecher", [a.get("grund") for a in tt.get("input_component_ambiguity") or []])

    def test_foreign_act_after_own_marker_is_not_the_avatars_speech(self):
        prov = FakeProvider([plan("action", "act", [act("Johann lächelt"), act("Mara geht aus dem Raum", akteur="Mara Nowak", ziel=None)])],
                            vollzug=lambda p: {"geschieht": True, "art": "tatsaechlich", "beleg": None,
                                               "taeter": "Mara Nowak" if "Mara geht" in p.get("handlung", "") else "figur"})
        r = self.prepare(prov, "*Johann lächelt.* Mara geht aus dem Raum.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.mine("action"), ["Johann lächelt"]); self.assertEqual(self.mine("speech"), [])

    def test_only_foreign_speech_is_rejected(self):
        self.rejected(FakeProvider([plan("smalltalk", "chat", [rede("Lass mich in Ruhe!", akteur="Mara Nowak", einleitung="Mara sagt:")])]),
                      "Mara sagt: Lass mich in Ruhe!")

    def test_reading_without_components_is_incomplete(self):
        # the planner answers twice without `komponenten` (no component -> no proof of speech or act)
        self.rejected(FakeProvider([plan("action", "act", []), plan("action", "act", [])]), "Ich küsse dich.", code="PLAN_INCOMPLETE")

    def test_reading_without_components_is_read_once_more(self):             # live 05.11.: 10/24 avatar readings without components
        prov = FakeProvider([plan("smalltalk", "chat", []), plan("smalltalk", "chat", [rede("Wie war dein Tag?")])])
        r = self.prepare(prov, "Wie war dein Tag?")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300]); self.assertEqual(self.mine("speech"), ["Wie war dein Tag?"])
        from matrix_api import llm_contract
        self.assertEqual(len([1 for sy, _u in prov.systems if sy.startswith(llm_contract.PLAN_RULES[:60])]), 2, "genau eine Wiederholung")

    def test_offline_marked_act_is_not_stored_but_direct_speech_is(self):
        prov = FakeProvider([])                                  # provider fails: the route has no reading (literal_plan)
        self.rejected(prov, "*Johann küsst Mara nicht.*")
        self.rejected(FakeProvider([]), "*Mara küsst Johann.*")
        answer = self.asked(FakeProvider([]), "Hallo Mara. *lächelt*")
        r = self.prepare(FakeProvider([]), "Hallo Mara. *lächelt*", answer)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.mine("speech"), ["Hallo Mara."]); self.assertEqual(self.mine("action"), [])
        self.assertIn("plan_fehlt", [a.get("grund") for a in self.session()["turnTruths"][-1].get("input_component_ambiguity") or []])

    # ---- Paket 9: der Planer laesst einen blossen *Marker* aus ----
    def test_bare_marker_left_out_by_the_planner_is_read_and_stored(self):
        prov = FakeProvider([plan("smalltalk", "chat", [rede("Hallo Mara.", einleitung="*lächelt*")])])   # live-Form: Marker als Ansage
        r = self.prepare(prov, "*lächelt* Hallo Mara.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.mine("action"), ["lächelt"]); self.assertEqual(self.mine("speech"), ["Hallo Mara."])
        self.assertTrue(any("lächelt" in p["handlung"] for p in prov.abrufe("vollzug")), "the marked act got its reading (Stand 11: erste Antwort)")

    def test_bare_marker_denied_by_the_reading_is_not_stored(self):
        prov = FakeProvider([plan("smalltalk", "chat", [rede("Hallo Mara.")])],
                            vollzug=lambda p: {"geschieht": False, "art": "verneint", "beleg": "nicht", "taeter": "figur"})
        r = self.prepare(prov, "*küsst Mara nicht* Hallo Mara.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.mine("action"), []); self.assertEqual(self.mine("speech"), ["Hallo Mara."])

    def test_planner_cannot_set_the_marker_flag(self):
        c = act("Ich küsse dich", geschieht=None); c["markierung"] = True
        self.rejected(FakeProvider([plan("action", "act", [c])]), "Ich küsse dich.")

    # ---- Paket-9-Pruefung P9-01/P9-02 ueber die Route ----
    def test_partial_marker_stores_only_the_checked_act(self):
        r = self.prepare(FakeProvider([plan("action", "act", [act("Johann lächelt")])]), "*Johann lächelt. Johann schubst Mara.*")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.mine("action"), ["Johann lächelt"]); self.assertEqual(self.mine("speech"), [])
        self.assertIn("rest_ohne_komponente", [a.get("grund") for a in self.session()["turnTruths"][-1].get("input_component_ambiguity") or []])

    def test_two_markers_two_acts(self):
        r = self.prepare(FakeProvider([plan("action", "act", [act("Johann lächelt"), act("Johann winkt")])]), "*Johann lächelt.* *Johann winkt.*")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300]); self.assertEqual(self.mine("action"), ["Johann lächelt", "Johann winkt"])

    def test_two_bare_markers_the_planner_put_into_the_speech(self):     # live form: Marker als Ansage, keine Handlung geliefert
        prov = FakeProvider([plan("smalltalk", "chat", [rede("Ja, gern.", einleitung="*nickt*")])],
                            vollzug=lambda p: {"geschieht": "lächelt" not in p.get("handlung", "") or True, "art": "tatsaechlich", "beleg": None, "taeter": "figur"})
        r = self.prepare(prov, "*nickt* Ja, gern. *lächelt*")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.mine("action"), ["nickt", "lächelt"]); self.assertEqual(self.mine("speech"), ["Ja, gern."])

    def test_second_marker_denied_by_its_reading(self):
        prov = FakeProvider([plan("action", "act", [act("Johann lächelt")])],
                            vollzug=lambda p: ({"geschieht": False, "art": "verneint", "beleg": "nicht", "taeter": "figur"} if "nicht" in p.get("handlung", "")
                                               else {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "figur"}))
        r = self.prepare(prov, "*Johann lächelt.* *küsst Mara nicht*")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300]); self.assertEqual(self.mine("action"), ["Johann lächelt"])

    # ---- Paket-10-Pruefung: Identitaet ueber die Route ----
    def test_foreign_speech_without_speaker_or_with_wrong_speaker_is_rejected(self):
        for c in (rede("Lass mich in Ruhe!", akteur=None, einleitung="Mara sagt:"), rede("Lass mich in Ruhe!", einleitung="Mara sagt:")):
            self.rejected(FakeProvider([plan("smalltalk", "chat", [c])]), "Mara sagt: Lass mich in Ruhe!")

    def test_session_alias_of_another_figure_is_no_avatar_identity(self):
        with closing(connect(self.dbp)) as c:
            row = c.execute("select json from sessions where id='ses_av'").fetchone()
            if row is not None:
                js = json.loads(row[0]); js["alias"] = "Mara Nowak"; c.execute("update sessions set json=? where id='ses_av'", (json.dumps(js),)); c.commit()
        prov = FakeProvider([plan("action", "act", [act("Mara küsst Johann.", akteur="Mara Nowak", ziel="Johann Bruckner")])],
                            vollzug=lambda p: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "Mara Nowak"})
        self.rejected(prov, "Mara küsst Johann.")
        r = self.prepare(FakeProvider([plan("action", "act", [act("Ich lächle", akteur="Ich")])]), "Ich lächle.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300]); self.assertEqual(self.mine("action"), ["Ich lächle"])

    def test_one_marker_two_sentences_two_facts(self):
        prov = FakeProvider([plan("smalltalk", "chat", [rede("Hallo.")])])        # the planner did not read the marker at all
        r = self.prepare(prov, "*Johann lächelt. Johann winkt.* Hallo.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.mine("action"), ["Johann lächelt", "Johann winkt"]); self.assertEqual(self.mine("speech"), ["Hallo."])

    def test_speaker_role_and_two_acts_in_one_component_over_the_avatar_route(self):   # Paket-11-Pruefung
        rede_ = rede("Lass mich in Ruhe!", einleitung="Mara sagt zu Johann:")
        self.rejected(FakeProvider([plan("smalltalk", "chat", [rede_])], sprecher=lambda p: {"sprecher": "Mara Nowak", "beleg": None}),
                      "Mara sagt zu Johann: Lass mich in Ruhe!")
        r = self.prepare(FakeProvider([plan("action", "act", [act("Johann lächelt. Johann winkt.")])]), "*Johann lächelt. Johann winkt.*")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual([a.rstrip(".") for a in self.mine("action")], ["Johann lächelt", "Johann winkt"])

    # ---- Positivkontrollen ----
    def test_own_marked_act_and_own_speech(self):
        prov = FakeProvider([plan("action", "act", [act("Johann lächelt"), rede("Hallo Mara.")])] * 2)
        answer = self.asked(prov, "*Johann lächelt.* Hallo Mara.")
        r = self.prepare(prov, "*Johann lächelt.* Hallo Mara.", answer)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.mine("action"), ["Johann lächelt"]); self.assertEqual(self.mine("speech"), ["Hallo Mara."])

    def test_pure_own_speech_and_announced_speech(self):
        prov = FakeProvider([plan("smalltalk", "chat", [rede("Hallo Mara, wie geht es dir?")])] * 2)
        answer = self.asked(prov, "Hallo Mara, wie geht es dir?")
        r = self.prepare(prov, "Hallo Mara, wie geht es dir?", answer)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.mine("speech"), ["Hallo Mara, wie geht es dir?"])


if __name__ == "__main__":
    unittest.main()
