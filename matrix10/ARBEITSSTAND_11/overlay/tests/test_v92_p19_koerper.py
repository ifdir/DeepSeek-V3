"""V92 Paket 19 (unabhaengige Pruefung Paket 18, 06.11.2026): ein Koerpervertrag fuer alle Aufrufer, Schlaf als eigener Zustand.

Befunde P18: N1 Aufwachen unerreichbar (Capability sperrt alles unter 0.5), N2 normale Rede im Schlaf gespeichert, N3/N4 eine
falsche Lesung mit woertlichem Zitat der Verneinung ("schläft nicht ein", "steht nicht auf") wurde geschrieben, N5/N6 God ohne
Beleg bzw. mit widersprechendem Beleg ("keine Schmerzen" -> stark) geschrieben, N7 God schrieb an apply_body_directive vorbei;
Regie las noch aus Woertern ("wird nicht bewusstlos" -> bewusstlos, "ist nicht blind" -> blind, "keucht vor Schmerzen" -> Schmerz).
AMASTER §43/§43.1 ("Handlungstext allein beweist noch keinen erfolgreichen Vollzug"), §46.1/§46.2, §24.2/§24.7, §6.2.
Echte Writer (commit_turn, commit_puppet, apply_god, apply_regie), Routen (Puppet, God, Regie), SQLite-Ruecklesung, Neustart.
Keine Nutzer-DB, kein Netz (Provider ersetzt).
"""
import json
import unittest
import urllib.request
from contextlib import closing
from unittest.mock import patch

import test_v84_kausal_chain as _K84  # offline Flask shim + Szenen-Fixture
from matrix_api import kernel
from matrix_api.db import connect
from matrix_api.repos import get_session, save_session
import test_v92_puppet_vertrag as _PV
import test_v92_avatar_route as _AV
from test_v92_puppet_vertrag import FakeProvider, plan

MARA, JOHANN, NATIVES = _K84.MARA, _K84.JOHANN, _K84.NATIVES


def bestaetigt(reading, text, *, art="tatsaechlich", inhalt="gleich", beleg=None, authority="character", figur_id=None, stelle=None,
               veraenderung=None):
    """The reading with the confirmation readings a route attaches (app._koerper_bestaetigen): one per field, asked about exactly
    the value and quote the kernel derives from the reading; `art`/`inhalt`/`beleg` = the confirmation's answer (a test may give a
    wrong one); `veraenderung` = the values the confirmation was (wrongly) asked about."""
    r = dict(reading)
    if figur_id is not None:
        r["figurId"] = str(figur_id)
    c = kernel.body_change_candidate(r, text, authority=authority)
    if c is None:
        return r
    ch, bl = c
    asked = {**ch, **(veraenderung or {})}
    r["bestaetigung"] = {"stelle": stelle if stelle is not None else bl,
                         "felder": {k: {"wert": asked[k], "art": art, "inhalt": inhalt, "beleg": beleg if beleg is not None else bl} for k in ch}}
    return r


def mara_state(start=None):
    s, _, _ = _K84.scene("Pruefung eigene Lage")
    s["runtimes"][MARA["id"]].update(start or {"consciousness": 1.0, "canSpeak": True, "pain": 0.25, "canSee": True})
    s["runtimes"].setdefault(JOHANN["id"], {}).update({"pain": 0.0, "consciousness": 1.0, "canSpeak": True})
    return s


def figure_commit(s, action, reading=None, speech="", proposals=None):
    t = kernel.bind_turn_truth(user_id="admin", world_id=s["worldId"], session_id=s["id"], role="teilnehmer", speaker_id=MARA["id"],
                               avatar_id=None, target_id=JOHANN["id"], authority="character", present_ids=s["scene"]["presentIds"],
                               hears_ids=s["scene"]["hearsIds"], input_kind="autochat", text="", input_actor_id=JOHANN["id"])
    n = len(s["facts"])
    out = kernel.commit_turn(s, truth=t, speaker=MARA, present=NATIVES, result={"speech": speech, "action": action},
                             proposals=proposals, koerper_lesung=reading)
    return out, [f for f in out["facts"][n:] if isinstance(f, dict)]


def asleep():
    a = "Mara schläft auf dem Stuhl ein."
    s, _ = figure_commit(mara_state(), a, bestaetigt({"haltung": "sitzend", "schlaf": "einschlafen", "zeit": "jetzt",
                                                      "beleg": "schläft auf dem Stuhl ein"}, a))
    assert s["runtimes"][MARA["id"]]["consciousness"] == 0.4 and s["runtimes"][MARA["id"]]["schlaeft"] is True
    return s


def god(text, reading, start=None):
    out = kernel.apply_god(mara_state(start), text, "body", MARA["id"], natives=NATIVES, body_state=reading)
    return out, out["runtimes"][MARA["id"]]


def regie(text, seg, desc, reading=None, start=None, akteur=None, legacy_lesung=None):
    s = mara_state(start)
    if legacy_lesung is not None:
        out = kernel.apply_regie(s, {}, text, actor_id=MARA["id"], present=NATIVES, koerper_lesung=legacy_lesung)
    else:
        comp = {"typ": "handlung", "akteur": akteur or MARA["name"], "ziel": None, "segment": seg, "beschreibung": desc,
                "wirkung": "ohne_koerperwirkung"}
        if reading is not None:
            comp["koerperPruefung"] = reading
        out = kernel.apply_regie(s, {}, text, actor_id=MARA["id"], present=NATIVES, components={"komponenten": [comp], "unklar": []})
    acts = [f for f in out["facts"] if f.get("kind") == "action"]
    return out, out["runtimes"][MARA["id"]], acts, [f for f in out["facts"] if f.get("kind") == "body_state"]


class P19Contract(unittest.TestCase):
    """Zweiter Schluessel: ein woertliches Zitat allein beweist nichts (Pruefung P18 N3/N4)."""

    def test_quote_alone_proves_nothing(self):
        for action, reading in (("Mara schläft nicht ein.", {"schlaf": "einschlafen", "zeit": "jetzt", "beleg": "schläft nicht ein"}),
                                ("Mara steht nicht auf.", {"haltung": "stehend", "zeit": "jetzt", "beleg": "steht nicht auf"}),
                                # also a correct reading: without the confirmation nothing is written (fail-closed)
                                ("Mara setzt sich auf die Bank.", {"haltung": "sitzend", "zeit": "jetzt", "beleg": "setzt sich auf die Bank"})):
            out, ff = figure_commit(mara_state(), action, reading)
            rt = out["runtimes"][MARA["id"]]
            self.assertEqual((rt.get("posture"), rt.get("consciousness")), (None, 1.0), action)
            self.assertFalse([f for f in ff if f["kind"] == "body_state"], action)
            self.assertEqual([f["effect"]["koerperPruefung"]["grund"] for f in ff if f["kind"] == "action"], ["bestaetigung_fehlt"], action)

    def test_the_confirmation_must_say_it_happens_here_now(self):
        a3, r3 = "Mara schläft nicht ein.", {"schlaf": "einschlafen", "zeit": "jetzt", "beleg": "schläft nicht ein"}
        a4, r4 = "Mara steht nicht auf.", {"haltung": "stehend", "zeit": "jetzt", "beleg": "steht nicht auf"}
        a2, r2 = "Mara setzt sich auf die Bank.", {"haltung": "sitzend", "zeit": "jetzt", "beleg": "setzt sich auf die Bank"}
        cases = [(a3, bestaetigt(r3, a3, art="verneint"), "bestaetigung_verneint"),
                 (a4, bestaetigt(r4, a4, art="verneint", beleg="steht nicht auf"), "bestaetigung_verneint"),
                 (a2, bestaetigt(r2, a2, art="ausdruck"), "bestaetigung_ausdruck"),
                 (a2, bestaetigt(r2, a2, art="wunsch"), "bestaetigung_wunsch"),
                 (a2, bestaetigt(r2, a2, stelle="setzt sich"), "bestaetigung_andere_stelle"),
                 (a2, bestaetigt(r2, a2, veraenderung={"haltung": "liegend"}), "bestaetigung_andere_veraenderung"),
                 (a2, bestaetigt(r2, a2, beleg="Mara"), "bestaetigung_andere_stelle"),
                 (a2, bestaetigt(r2, a2, beleg="legt sich hin"), "bestaetigung_beleg_nicht_im_text"),
                 (a2, bestaetigt(r2, a2, art=None), "bestaetigung_ohne_art"),
                 (a2, bestaetigt(r2, a2, inhalt="anders"), "bestaetigung_anders"),
                 # quotation marks: words said, not done (form only)
                 ("Mara sagt: „Ich setze mich.“", bestaetigt({"haltung": "sitzend", "zeit": "jetzt", "beleg": "Ich setze mich"}, "Mara sagt: „Ich setze mich.“"),
                  "beleg_im_zitat")]
        for action, reading, grund in cases:
            out, ff = figure_commit(mara_state(), action, reading)
            rt = out["runtimes"][MARA["id"]]
            self.assertEqual((rt.get("posture"), rt.get("consciousness"), [f for f in ff if f["kind"] == "body_state"]), (None, 1.0, []), grund)
            self.assertEqual([f["effect"]["koerperPruefung"]["grund"] for f in ff if f["kind"] == "action"], [grund])

    def test_a_confirmed_change_is_written_with_its_audit(self):
        a = "Mara setzt sich auf die Bank."
        out, ff = figure_commit(mara_state(), a, bestaetigt({"haltung": "sitzend", "zeit": "jetzt", "beleg": "setzt sich auf die Bank"}, a))
        self.assertEqual(out["runtimes"][MARA["id"]].get("posture"), "sitzend")
        act = next(f for f in ff if f["kind"] == "action")
        body = [f for f in ff if f["kind"] == "body_state"]
        self.assertEqual(act["effect"]["koerperPruefung"]["bestaetigung"],
                         {"haltung": {"art": "tatsaechlich", "inhalt": "gleich", "beleg": "setzt sich auf die Bank", "bestaetigt": True}})
        self.assertEqual((len(body), body[0]["payload"]["sourceFactId"], body[0]["text"].startswith("Mara Nowak:")), (1, act["id"], True))

    def test_only_confirmed_fields_are_written(self):
        # a God reading that names more than the text says ("geknebelt" + an unstated "gefesselt: false"): only the confirmed field
        t = "Mara ist geknebelt."
        r = bestaetigt({"geknebelt": True, "gefesselt": False, "beleg": "ist geknebelt"}, t, authority="god", figur_id=MARA["id"])
        r["bestaetigung"]["felder"]["gefesselt"].update(art="tatsaechlich", inhalt="anders")
        out, rt = god(t, r, start={"pain": 0.25, "restrained": True, "consciousness": 1.0, "canSpeak": True})
        self.assertEqual((rt.get("gagged"), rt.get("canSpeak"), rt.get("restrained")), (True, False, True))
        gf = [f for f in out["facts"] if f.get("kind") == "god"][-1]
        self.assertEqual(gf["payload"]["koerperPruefung"]["bestaetigung"]["gefesselt"]["grund"], "bestaetigung_anders")
        self.assertEqual([f["payload"]["aenderung"] for f in out["facts"] if f.get("kind") == "body_state"], [{"geknebelt": True}])

    def test_label_of_every_value_is_fixed_wording(self):
        self.assertEqual(kernel.body_change_label({"schlaf": "einschlafen", "haltung": "sitzend"}),
                         "nimmt jetzt die Körperlage sitzend ein; schläft jetzt ein")
        self.assertIn("hat jetzt keine Schmerzen", kernel.body_change_label({"schmerz": "kein"}))
        self.assertIn("ist jetzt nicht mehr gefesselt", kernel.body_change_label({"gefesselt": False}))


class P19Sleep(unittest.TestCase):
    """Schlaf/Capability (Pruefung P18 N1/N2): nur die eigene Aufwachhandlung, keine Rede, Zustand zu Zugbeginn."""

    def test_a_sleeping_figure_can_wake_herself_and_speak_afterwards(self):
        s = asleep()
        a = "Mara wacht auf."
        out, ff = figure_commit(s, a, bestaetigt({"schlaf": "aufwachen", "zeit": "jetzt", "beleg": "wacht auf"}, a))
        rt = out["runtimes"][MARA["id"]]
        self.assertEqual((rt.get("consciousness"), rt.get("schlaeft"), rt.get("canSpeak")), (1.0, False, True))
        act = next(f for f in ff if f["kind"] == "action")
        self.assertEqual((act.get("validated"), act["effect"].get("nurAufwachen")), (True, True))
        self.assertTrue([f for f in ff if f["kind"] == "body_state"])
        nxt, ff2 = figure_commit(out, None, None, "Guten Morgen.")
        self.assertEqual([(f["kind"], f["text"]) for f in ff2 if f["kind"] == "speech"], [("speech", "Guten Morgen.")])

    def test_no_words_while_asleep_or_unconscious(self):
        s = asleep()
        out, ff = figure_commit(s, None, None, "Hallo, ich bin noch im Schlaf.")
        self.assertFalse([f for f in ff if f["kind"] == "speech"])
        self.assertEqual(out.get("turnIndex"), s.get("turnIndex"), "no empty turn")
        s2 = mara_state({"consciousness": 0.2, "canSpeak": True, "pain": 0.25})   # legacy state: canSpeak left True
        out, ff = figure_commit(s2, None, None, "Ich rede trotzdem.")
        self.assertFalse([f for f in ff if f["kind"] == "speech"])

    def test_nothing_else_is_released(self):
        s = asleep()
        for a, r in (("Mara steht auf.", {"haltung": "stehend", "zeit": "jetzt", "beleg": "steht auf"}),
                     ("Mara wacht auf und schlägt Johann.", {"schlaf": "aufwachen", "zeit": "jetzt", "beleg": "wacht auf"}),
                     ("Mara wacht auf und steht auf.", {"schlaf": "aufwachen", "haltung": "stehend", "zeit": "jetzt", "beleg": "wacht auf und steht auf"})):
            out, ff = figure_commit(s, a, bestaetigt(r, a), proposals={"wirkung": {"art": "gewalt", "ziel": JOHANN["name"]}})
            rt = out["runtimes"][MARA["id"]]
            if a == "Mara wacht auf und steht auf.":
                # the quote covers the whole act: she wakes - and only wakes (her posture is not changed while asleep)
                self.assertEqual((rt.get("consciousness"), rt.get("posture")), (1.0, "sitzend"), a)
                self.assertEqual([f["payload"]["aenderung"] for f in ff if f["kind"] == "body_state"], [{"schlaf": "aufwachen"}])
            else:
                self.assertEqual((rt.get("consciousness"), rt.get("posture")), (0.4, "sitzend"), a)
            self.assertEqual(out["runtimes"][JOHANN["id"]].get("pain"), 0.0, a)
        # unconscious (not asleep): she cannot wake herself
        a = "Mara wacht auf."
        out, ff = figure_commit(mara_state({"consciousness": 0.2, "canSpeak": False, "pain": 0.25}), a,
                                bestaetigt({"schlaf": "aufwachen", "zeit": "jetzt", "beleg": "wacht auf"}, a))
        self.assertEqual(out["runtimes"][MARA["id"]].get("consciousness"), 0.2)

    def test_brain_context_says_what_capability_does(self):
        s = asleep()
        t = kernel.bind_turn_truth(user_id="admin", world_id=s["worldId"], session_id=s["id"], role="teilnehmer", speaker_id=MARA["id"],
                                   avatar_id=None, target_id=JOHANN["id"], authority="character", present_ids=s["scene"]["presentIds"],
                                   hears_ids=s["scene"]["hearsIds"], input_kind="autochat", text="", input_actor_id=JOHANN["id"])
        sp = kernel.bind_formulation_spiegel(s, t, speaker=MARA, present=NATIVES)
        self.assertEqual((sp["body"]["canDo"], sp["body"]["asleep"], sp["body"]["canSpeak"]), (["aufwachen"], True, False))
        self.assertIn("schläft", " ".join(sp["body"]["cannotDo"]))
        from matrix_api import llm_contract
        self.assertIn("du schläfst: du kannst nur aufwachen", llm_contract.render_persona_brief(sp, "Wach auf!", JOHANN["name"], ""))
        s2 = mara_state({"consciousness": 0.2, "canSpeak": False})
        sp2 = kernel.bind_formulation_spiegel(s2, t, speaker=MARA, present=NATIVES)
        self.assertEqual((sp2["body"]["canDo"], sp2["body"]["asleep"]), ([], False))

    def test_puppet_turn_start_state_decides_every_act(self):
        s = asleep()
        acts = [{"text": "Mara wacht auf", "targetId": None, "effectKind": None, "effectValid": False,
                 "koerperPruefung": bestaetigt({"schlaf": "aufwachen", "zeit": "jetzt", "beleg": "wacht auf"}, "Mara wacht auf")},
                {"text": "Mara schlägt Johann", "targetId": JOHANN["id"], "effectKind": "strike", "effectValid": True},
                {"text": "Mara steht auf", "targetId": None, "effectKind": None, "effectValid": False,
                 "koerperPruefung": bestaetigt({"haltung": "stehend", "zeit": "jetzt", "beleg": "steht auf"}, "Mara steht auf")}]
        out = kernel.commit_puppet(s, MARA, "Was ist los?", actions=acts, target_id=JOHANN["id"])
        rt = out["runtimes"][MARA["id"]]
        new = out["facts"][len(s["facts"]):]
        self.assertEqual((rt.get("consciousness"), out["runtimes"][JOHANN["id"]].get("pain")), (1.0, 0.0))
        self.assertEqual([(f["text"], f.get("validated"), f.get("rejection_reason")) for f in new if f["kind"] == "action"],
                         [("Mara wacht auf", True, None), ("Mara schlägt Johann", False, "capability"), ("Mara steht auf", False, "capability")])
        # the blocked act's audit does not claim a written change (its reading was confirmed, the act was not carried out)
        self.assertEqual([(f["effect"]["koerperPruefung"] or {}).get("grund") for f in new if f["kind"] == "action"][2], "handlung_gesperrt")
        self.assertEqual(rt.get("posture"), "sitzend")
        self.assertFalse([f for f in new if f["kind"] == "speech"], "no words in the turn she wakes up in")

    def test_regie_speech_order_of_a_sleeping_figure_is_no_speech(self):
        s = asleep()
        out = kernel.apply_regie(s, {}, f'{MARA["name"].split()[0]}, sage: "Ich bin wach."', actor_id=MARA["id"], present=NATIVES)
        new = out["facts"][len(s["facts"]):]
        self.assertFalse([f for f in new if f["kind"] == "speech"])
        self.assertEqual(next(f for f in new if f["kind"] == "regie")["payload"]["redeNichtMoeglich"]["grund"], "kann_jetzt_nicht_sprechen")


class P19AvatarSleep(unittest.TestCase):
    """Avatar-Eingabe (/api/kernel/prepare) einer schlafenden Avatar-Figur: keine Rede, nur das eigene Aufwachen; blockierte Eingabe 422."""
    setUp = _AV.AvatarRouteChain.setUp
    session = _AV.AvatarRouteChain.session
    snapshot = _AV.AvatarRouteChain.snapshot
    prepare = _AV.AvatarRouteChain.prepare

    def put_runtime(self, cid, values):
        with closing(connect(self.dbp)) as c:
            s = get_session(c, "admin", "ses_av")
            s.setdefault("runtimes", {}).setdefault(cid, {"characterId": cid}).update(values)
            save_session(c, "admin", s)
            c.commit()

    def test_sleeping_avatar(self):
        from test_v92_avatar_route import act
        self.put_runtime(self.J["id"], {"consciousness": 0.4, "schlaeft": True, "canSpeak": False})
        before = self.snapshot(self.session())
        for prov, text in ((FakeProvider([plan("smalltalk", "chat", [{"typ": "rede", "segment": "Bist du noch da?", "akteur": "ich"}])]), "Bist du noch da?"),
                           (FakeProvider([plan("action", "act", [dict(act("Ich stehe auf", akteur="ich", ziel=None), wirkung="ohne_koerperwirkung")])],
                                         koerper=lambda p: {"haltung": "stehend", "zeit": "jetzt", "beleg": "stehe auf"}), "Ich stehe auf.")):
            r = self.prepare(prov, text)
            self.assertEqual((r.status_code, (r.get_json() or {}).get("code")), (422, "EINGABE_NICHT_AUSFUEHRBAR"), r.get_data(as_text=True)[:300])
            self.assertIn("nicht", (r.get_json() or {}).get("message", ""))
            self.assertEqual(self.snapshot(self.session()), before, text)
        prov = FakeProvider([plan("action", "act", [dict(act("Ich wache auf", akteur="ich", ziel=None), wirkung="ohne_koerperwirkung")])],
                            koerper=lambda p: {"schlaf": "aufwachen", "zeit": "jetzt", "beleg": "wache auf"})
        r = self.prepare(prov, "Ich wache auf.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        rt = self.session()["runtimes"][self.J["id"]]
        self.assertEqual((rt.get("consciousness"), rt.get("schlaeft"), rt.get("canSpeak")), (1.0, False, True))
        af = [f for f in self.session()["facts"] if f.get("kind") == "action" and f.get("actorId") == self.J["id"]][-1]
        self.assertEqual((af["effect"].get("nurAufwachen"), af["effect"]["koerperPruefung"].get("nurAufwachen")), (True, True))


class P19God(unittest.TestCase):
    """God (Pruefung P18 N5-N7): Beleg Pflicht, Bestaetigung, gebundenes Ziel, EIN Writer; Inventar bleibt."""

    def g(self, text, reading, **kw):
        return bestaetigt(reading, text, authority="god", figur_id=MARA["id"], **kw)

    def test_god_writes_only_through_the_one_writer(self):
        t = "Mara hat starke Schmerzen."
        orig = kernel.apply_body_directive
        with patch.object(kernel, "apply_body_directive", side_effect=orig) as spy:
            out, rt = god(t, self.g(t, {"schmerz": "stark", "beleg": "starke Schmerzen"}))
        self.assertEqual((spy.call_count, rt.get("pain")), (1, 0.8))
        body = [f for f in out["facts"] if f.get("kind") == "body_state"]
        gf = [f for f in out["facts"] if f.get("kind") == "god"][-1]
        self.assertEqual((len(body), body[0]["payload"]["sourceFactId"], body[0]["witnessedBy"]), (1, gf["id"], [MARA["id"]]))
        self.assertTrue(gf["payload"]["koerperGeschrieben"])
        with patch.object(kernel, "apply_body_directive", side_effect=RuntimeError("Writer gesperrt")) as spy:
            out, rt = god(t, self.g(t, {"schmerz": "stark", "beleg": "starke Schmerzen"}))
        gf = [f for f in out["facts"] if f.get("kind") == "god"][-1]
        self.assertEqual((spy.call_count, rt.get("pain"), gf["payload"]["koerperGeschrieben"]), (1, 0.25, False))
        self.assertIn("RuntimeError", gf["payload"]["koerperFehler"])
        self.assertFalse([f for f in out["facts"] if f.get("kind") == "body_state"], "no half state")

    def test_god_quote_is_mandatory_and_must_mean_it(self):
        for text, reading, grund in (("Mara ist nicht verletzt.", {"schmerz": "stark", "figurId": MARA["id"]}, "beleg_fehlt"),
                                     ("Mara hat keine Schmerzen.", self.g("Mara hat keine Schmerzen.", {"schmerz": "stark", "beleg": "keine Schmerzen"}, art="verneint"),
                                      "bestaetigung_verneint"),
                                     ("Mara hat starke Schmerzen.", bestaetigt({"schmerz": "stark", "beleg": "starke Schmerzen"}, "Mara hat starke Schmerzen.",
                                                                               authority="god", figur_id=JOHANN["id"]), "figur_nicht_gebunden"),
                                     ("Mara hat starke Schmerzen.", {"schmerz": "stark", "beleg": "starke Schmerzen", "figurId": MARA["id"]}, "bestaetigung_fehlt")):
            out, rt = god(text, reading)
            gf = [f for f in out["facts"] if f.get("kind") == "god"][-1]
            self.assertEqual((rt.get("pain"), gf["payload"]["koerperPruefung"]["grund"]), (0.25, grund), text)
            self.assertFalse([f for f in out["facts"] if f.get("kind") == "body_state"], text)
            self.assertNotIn(text[:120], rt.get("constraints") or [], "no note of an unwritten state")

    def test_god_keeps_its_inventory(self):
        for text, reading, expect in (
                ("Mara hat keine Schmerzen mehr.", {"schmerz": "kein", "beleg": "keine Schmerzen mehr"}, {"pain": 0.0}),
                ("Mara hat leichte Schmerzen.", {"schmerz": "leicht", "beleg": "leichte Schmerzen"}, {"pain": 0.25}),
                ("Mara hat mittlere Schmerzen.", {"schmerz": "mittel", "beleg": "mittlere Schmerzen"}, {"pain": 0.5}),
                ("Mara kann sich kaum bewegen.", {"beweglichkeit": "stark_eingeschraenkt", "beleg": "kann sich kaum bewegen"}, {"mobility": 0.3}),
                ("Mara ist bewusstlos.", {"bewusstsein": "bewusstlos", "beleg": "ist bewusstlos"},
                 {"consciousness": 0.2, "canSpeak": False, "posture": "liegend", "schlaeft": False}),
                ("Mara ist gefesselt.", {"gefesselt": True, "beleg": "ist gefesselt"}, {"restrained": True, "mobility": 0.2}),
                ("Mara ist geknebelt.", {"geknebelt": True, "beleg": "ist geknebelt"}, {"gagged": True, "canSpeak": False}),
                ("Mara hat einen gebrochenen linken Arm.", {"verletzung": {"art": "gebrochen", "glied": "Arm", "seite": "links", "schwer": True},
                                                            "beleg": "hat einen gebrochenen linken Arm"},
                 {"pain": 0.7, "injuries": [("Arm (links)", "gebrochen")]})):
            out, rt = god(text, self.g(text, reading))
            got = {k: ([(i["part"], i["kind"]) for i in rt.get(k) or []] if k == "injuries" else rt.get(k)) for k in expect}
            self.assertEqual(got, expect, text)
            written = bool([f for f in out["facts"] if f.get("kind") == "body_state"])
            self.assertEqual(text[:120] in (rt.get("constraints") or []), written, "the God note goes with a written state only")
        # healing, waking, untie, ungag - from a state that has them
        start = {"pain": 0.7, "consciousness": 0.2, "canSpeak": False, "restrained": True, "gagged": True, "mobility": 0.2,
                 "injuries": [{"part": "Arm (links)", "kind": "gebrochen", "since": 1, "cause": "f"}],
                 "cannotDo": ["Arm (links) benutzen"]}
        for text, reading, expect in (
                ("Maras Verletzungen heilen.", {"heilung": True, "beleg": "Verletzungen heilen"}, {"injuries": [], "pain": 0.0, "cannotDo": []}),
                ("Mara ist wieder wach.", {"bewusstsein": "wach", "beleg": "ist wieder wach"}, {"consciousness": 1.0, "canSpeak": False}),
                ("Mara ist nicht mehr gefesselt.", {"gefesselt": False, "beleg": "ist nicht mehr gefesselt"}, {"restrained": False}),
                ("Mara ist wach und nicht mehr geknebelt.", {"bewusstsein": "wach", "geknebelt": False, "beleg": "ist wach und nicht mehr geknebelt"},
                 {"gagged": False, "canSpeak": True, "consciousness": 1.0})):
            out, rt = god(text, self.g(text, reading), start=dict(start))
            self.assertEqual({k: rt.get(k) for k in expect}, expect, text)


class P19Regie(unittest.TestCase):
    """Regie: Wortlesung entfernt; derselbe Vertrag fuer genau den angeordneten Akteur (Pruefung P18, drei Regie-Fehler)."""

    def r(self, seg, reading, **kw):
        return bestaetigt(reading, seg, authority="regie", figur_id=kw.pop("figur_id", MARA["id"]), **kw)

    def test_the_three_regie_negatives(self):
        for text, wrong in (("Mara wird nicht bewusstlos.", {"bewusstsein": "bewusstlos", "beleg": "wird nicht bewusstlos"}),
                            ("Mara ist nicht blind.", {"sehen": "verliert", "beleg": "ist nicht blind"}),
                            ("Mara keucht vor Schmerzen.", {"schmerz": "mittel", "beleg": "keucht vor Schmerzen"})):
            seg = text.rstrip(".")
            for reading, grund in ((None, "keine_lesung"), ({**wrong, "figurId": MARA["id"]}, "bestaetigung_fehlt"),
                                   (self.r(seg, wrong, art="ausdruck" if "keucht" in text else "verneint"),
                                    "bestaetigung_ausdruck" if "keucht" in text else "bestaetigung_verneint")):
                out, rt, acts, body = regie(text, seg, seg, reading)
                self.assertEqual((rt.get("consciousness"), rt.get("canSee"), rt.get("pain"), body), (1.0, True, 0.25, []), (text, grund))
                self.assertEqual([a["effect"]["koerperPruefung"]["grund"] for a in acts], [grund], text)

    def test_regie_positives_through_the_same_contract(self):
        for text, reading, expect, start in (
                ("Mara setzt sich auf die Bank.", {"haltung": "sitzend", "beleg": "setzt sich auf die Bank"}, {"posture": "sitzend"}, None),
                ("Mara macht einen Handstand.", {"haltung": "kopfstand", "beleg": "macht einen Handstand"}, {"posture": "Handstand", "handsFree": False}, None),
                ("Mara bricht sich den rechten Arm.", {"verletzung": {"art": "gebrochen", "glied": "Arm", "seite": "rechts", "schwer": True},
                                                       "beleg": "bricht sich den rechten Arm"}, {"pain": 0.7}, None),
                ("Mara wird ohnmächtig.", {"bewusstsein": "bewusstlos", "beleg": "wird ohnmächtig"}, {"consciousness": 0.2, "canSpeak": False}, None),
                ("Mara verliert ihr Augenlicht.", {"sehen": "verliert", "beleg": "verliert ihr Augenlicht"}, {"canSee": False}, None),
                ("Mara kommt wieder zu sich.", {"bewusstsein": "wach", "beleg": "kommt wieder zu sich"}, {"consciousness": 1.0, "canSpeak": True},
                 {"consciousness": 0.2, "canSpeak": False, "posture": "liegend"})):
            seg = text.rstrip(".")
            out, rt, acts, body = regie(text, seg, seg, self.r(seg, reading), start=start)
            self.assertEqual({k: rt.get(k) for k in expect}, expect, text)
            self.assertEqual(([a.get("validated") for a in acts], len(body)), ([True], 1), text)
        # the explicit *act* of the legacy syntax: the same contract (koerper_lesung)
        out, rt, acts, body = regie(f'{MARA["name"].split()[0]}: *setzt sich*', None, None,
                                    legacy_lesung=self.r("setzt sich", {"haltung": "sitzend", "beleg": "setzt sich"}))
        self.assertEqual((rt.get("posture"), len(body)), ("sitzend", 1))
        out, rt, acts, body = regie(f'{MARA["name"].split()[0]}: *setzt sich*', None, None, legacy_lesung={"haltung": "sitzend", "beleg": "setzt sich"})
        self.assertEqual((rt.get("posture"), body), (None, []))

    def test_ordered_own_body_outcome_without_effect_class(self):
        # the Regie reading leaves the effect class open (wirkung null) - the validated own-body change is the ordered outcome;
        # without it the act stays "wirkung_unklar" (V79)
        for text, reading, expect in (("Mara wird ohnmächtig.", {"bewusstsein": "bewusstlos", "beleg": "wird ohnmächtig"}, {"consciousness": 0.2}),
                                      ("Mara kommt wieder zu sich.", {"bewusstsein": "wach", "beleg": "kommt wieder zu sich"}, {"consciousness": 1.0})):
            seg = text.rstrip(".")
            s = mara_state({"consciousness": 0.2, "canSpeak": False} if "zu sich" in text else None)
            for r, ok in ((self.r(seg, reading), True), (None, False)):
                comp = {"typ": "handlung", "akteur": MARA["name"], "ziel": None, "segment": seg, "beschreibung": seg, "wirkung": None}
                if r is not None:
                    comp["koerperPruefung"] = r
                out = kernel.apply_regie(s, {}, text, actor_id=MARA["id"], present=NATIVES, components={"komponenten": [comp], "unklar": []})
                act = [f for f in out["facts"] if f.get("kind") == "action"][-1]
                rt = out["runtimes"][MARA["id"]]
                if ok:
                    self.assertEqual(({k: rt.get(k) for k in expect}, act.get("validated"), act["effect"].get("nurEigenerKoerper") or act["effect"].get("nurAufwachen")),
                                     (expect, True, True), text)
                else:
                    # unconscious and no validated waking: Capability blocks first; awake: the unclear effect class
                    self.assertEqual((act.get("validated"), act.get("rejection_reason")),
                                     (False, "capability" if "zu sich" in text else "wirkung_unklar"), text)

    def test_regie_binds_the_ordered_actor(self):
        seg = "Mara setzt sich"
        out, rt, acts, body = regie("Mara setzt sich.", seg, seg, self.r(seg, {"haltung": "sitzend", "beleg": "setzt sich"}, figur_id=JOHANN["id"]))
        self.assertEqual((rt.get("posture"), [a["effect"]["koerperPruefung"]["grund"] for a in acts]), (None, ["figur_nicht_gebunden"]))
        # a reading for Mara on an act ordered to Johann does not reach Johann (nor Mara)
        out, rt, acts, body = regie("Johann setzt sich.", "Johann setzt sich", "Johann setzt sich",
                                    self.r("Johann setzt sich", {"haltung": "sitzend", "beleg": "setzt sich"}), akteur=JOHANN["name"])
        self.assertEqual((out["runtimes"][JOHANN["id"]].get("posture"), rt.get("posture"), body), (None, None, []))


class P19Routes(unittest.TestCase):
    """Echte Routen: Puppet, God, Regie - Server-Lesung + Bestaetigung, SQLite, Neustart."""
    setUp = _PV.PuppetRouteChain.setUp
    session = _PV.PuppetRouteChain.session
    puppet = _PV.PuppetRouteChain.puppet
    _act_comp = _PV.PuppetRouteChain._act_comp

    def put_runtime(self, cid, values):
        with closing(connect(self.dbp)) as c:
            s = get_session(c, "admin", "ses_v92")
            s.setdefault("runtimes", {}).setdefault(cid, {"characterId": cid}).update(values)
            save_session(c, "admin", s)
            c.commit()

    def post(self, path, provider, body):
        with patch.object(urllib.request, "urlopen", provider):
            return self.client.post(path, headers={"X-Matrix-Actor": "admin"}, json={"sessionId": "ses_v92", "actorUserId": "admin", **body})

    def restart_read(self):
        from matrix_api import app as appmod
        appmod.create_app(self.dbp)
        return self.session()

    def test_puppet_confirmation_decides_and_a_sleeping_puppet_wakes(self):
        c1 = dict(self._act_comp("Johann setzt sich auf die Bank"), ziel=None, wirkung="ohne_koerperwirkung")
        prov = FakeProvider([plan("action", "act", [c1])], koerper=lambda p: {"haltung": "sitzend", "zeit": "jetzt", "beleg": "setzt sich auf die Bank"},
                            bestaetigung=lambda p: {"art": "verneint", "beleg": p.get("stelle")})
        r = self.puppet(prov, "Johann setzt sich auf die Bank.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.session()
        self.assertEqual(s["runtimes"][self.J["id"]].get("posture"), None)
        af = [f for f in s["facts"] if f.get("kind") == "action" and f.get("actorId") == self.J["id"]][-1]
        self.assertEqual(af["effect"]["koerperPruefung"]["grund"], "bestaetigung_verneint")
        self.assertTrue(prov.abrufe("koerper_bestaetigung"), "die Bestaetigung lief (Stand 11: aus der ersten Antwort)")
        # asleep: his speech is no speech, his own waking is the one act
        self.put_runtime(self.J["id"], {"consciousness": 0.4, "schlaeft": True, "canSpeak": False})
        c2 = dict(self._act_comp("Johann wacht auf"), ziel=None, wirkung="ohne_koerperwirkung")
        prov = FakeProvider([plan("action", "act", [c2])], koerper=lambda p: {"schlaf": "aufwachen", "zeit": "jetzt", "beleg": "wacht auf"})
        r = self.puppet(prov, "Johann wacht auf.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.restart_read()
        self.assertEqual((s["runtimes"][self.J["id"]].get("consciousness"), s["runtimes"][self.J["id"]].get("schlaeft")), (1.0, False))
        # asleep again: words and other acts are not executable - 422 with the reason, nothing written
        self.put_runtime(self.J["id"], {"consciousness": 0.4, "schlaeft": True, "canSpeak": False})
        before = self.session()
        c3 = dict(self._act_comp("Johann steht auf"), ziel=None, wirkung="ohne_koerperwirkung")
        prov = FakeProvider([plan("smalltalk", "chat", [{"typ": "rede", "segment": "Bist du noch da?", "akteur": "Johann Bruckner"}]),
                             plan("action", "act", [c3])], koerper=lambda p: {"haltung": "stehend", "zeit": "jetzt", "beleg": "steht auf"})
        for text in ("Bist du noch da?", "Johann steht auf."):
            r = self.puppet(prov, text)
            self.assertEqual((r.status_code, (r.get_json() or {}).get("code")), (422, "PUPPET_NICHT_AUSFUEHRBAR"), r.get_data(as_text=True)[:300])
            self.assertIn("schläft", (r.get_json() or {}).get("message", ""))
        after = self.session()
        self.assertEqual((after.get("turnIndex"), len(after["facts"])), (before.get("turnIndex"), len(before["facts"])))

    def test_god_route_body_scope(self):
        prov = FakeProvider([], gott=lambda p: {"schmerz": "stark", "beleg": "starke Schmerzen"})
        r = self.post("/api/kernel/god", prov, {"text": "Mara hat starke Schmerzen.", "scope": "body", "targetId": self.M["id"]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.restart_read()
        self.assertEqual(float(s["runtimes"][self.M["id"]].get("pain")), 0.8)
        gf = [f for f in s["facts"] if f.get("kind") == "god"][-1]
        self.assertEqual((gf["payload"]["koerperPruefung"]["bestaetigt"], gf["payload"]["koerperGeschrieben"]), (True, True))
        # a wrong first reading of a negated fact: the confirmation says "verneint" - nothing changes
        prov = FakeProvider([], gott=lambda p: {"schmerz": "stark", "beleg": "keine Schmerzen"},
                            bestaetigung=lambda p: {"art": "verneint", "beleg": "keine Schmerzen"})
        r = self.post("/api/kernel/god", prov, {"text": "Mara hat keine Schmerzen.", "scope": "body", "targetId": self.M["id"]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.restart_read()
        self.assertEqual(float(s["runtimes"][self.M["id"]].get("pain")), 0.8)
        gf = [f for f in s["facts"] if f.get("kind") == "god"][-1]
        self.assertEqual(gf["payload"]["koerperPruefung"]["grund"], "bestaetigung_verneint")

    def test_regie_route_reads_and_confirms_each_ordered_act(self):
        def analyse(p):
            seg = p["anweisung"].rstrip(".")
            return {"komponenten": [{"typ": "handlung", "akteur": self.M["name"], "ziel": None, "segment": seg, "beschreibung": seg,
                                     "wirkung": "ohne_koerperwirkung"}], "unklar": []}
        prov = FakeProvider([], regie=analyse, gott=lambda p: {"haltung": "sitzend", "beleg": "setzt sich auf die Bank"})
        r = self.post("/api/kernel/regie", prov, {"text": "Mara setzt sich auf die Bank.", "actorId": self.M["id"]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.restart_read()
        self.assertEqual(s["runtimes"][self.M["id"]].get("posture"), "sitzend")
        self.assertTrue([f for f in s["facts"] if f.get("kind") == "body_state" and f.get("authority") == "regie"])
        prov = FakeProvider([], regie=analyse, gott=lambda p: {"bewusstsein": "bewusstlos", "beleg": "wird nicht bewusstlos"},
                            bestaetigung=lambda p: {"art": "verneint", "beleg": "wird nicht bewusstlos"})
        r = self.post("/api/kernel/regie", prov, {"text": "Mara wird nicht bewusstlos.", "actorId": self.M["id"]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.restart_read()
        rt = s["runtimes"][self.M["id"]]
        self.assertEqual((rt.get("consciousness", 1.0), rt.get("canSpeak", True)), (1.0, True))
        af = [f for f in s["facts"] if f.get("kind") == "action" and f.get("authority") == "regie"][-1]
        self.assertEqual(af["effect"]["koerperPruefung"]["grund"], "bestaetigung_verneint")


if __name__ == "__main__":
    unittest.main()
