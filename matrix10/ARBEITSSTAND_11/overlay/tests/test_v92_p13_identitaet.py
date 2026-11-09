"""V92 Paket 13 (Paket-12-Pruefung 05.11.2026, Bedingungen A-F): ein strenger Identitaetsvertrag fuer die ganze Eingangskette.

A  figure_ids_for_name: ein voller Name, der keiner Figur gehoert, bindet niemanden (kein Rueckfall auf den Vornamen).
B  name_occurrences: Textabgleich und Zielbindung lesen Namen im Text mit demselben Vertrag; eine unbekannte Person bleibt
   sichtbar ungebunden - keine Wirkung auf eine anwesende Figur mit gleichem Vornamen.
C  dieselbe Regel in Wirkungspruefung (_same_figure), Bewertung (apply_appraisals), Grenze, Referenten, Pronomenkandidaten.
D  der Planer bekommt die anwesenden Figuren dieser Session als Kontext (id, Name, Beinamen, Praesenz) und Sprecher-,
   Puppet- und Empfaenger-ID getrennt; die serverseitige Bindung sperrt Falschantworten weiter.
E  Negativfaelle N1-N4, Positivfaelle P1-P2, zwei gleichnamige Anwesende, Abwesende, umgekehrte Besetzungsreihenfolge,
   direkte und gemischte Rede, echte Route + SQLite-Ruecklesung (neue Verbindung = Leser nach Neustart).
"""
import copy
import json
import unittest
import urllib.request
from contextlib import closing
from unittest.mock import patch

import test_v84_kausal_chain  # noqa: F401  (offline Flask shim wie die übrigen Tests)
from matrix_api import kernel
from matrix_api.db import connect
from matrix_api.repos import create_session, get_session
import test_v92_negativgrenzen as _NG
import test_v92_puppet_vertrag as _PV
import test_v92_avatar_route as _AV
from test_v92_negativgrenzen import hc, rc, JA
from test_v92_puppet_vertrag import FakeProvider, plan, comp
from test_v92_avatar_route import act, rede


def pain(s, fid):
    return float(((s.get("runtimes") or {}).get(fid) or {}).get("pain") or 0)


class P13Binder(unittest.TestCase):
    """Binder + commit_puppet mit kontrollierten Planer-Daten (wie die unabhaengige Gegenprobe zu Paket 12).
    Helfer aus test_v92_negativgrenzen (ohne deren Tests ein zweites Mal zu sammeln)."""
    setUp = _NG.Negativgrenzen.setUp
    bind = _NG.Negativgrenzen.bind
    commit = _NG.Negativgrenzen.commit
    grunds = _NG.Negativgrenzen.grunds

    def _cases(self):
        J = "Johann Bruckner"
        return {
            "N1": ("Johann schubst Mara Schmidt.", [hc("Johann schubst Mara Schmidt", wirkung="gewalt", pruefung=JA, ziel="Mara Schmidt")]),
            "N2": ("Johann schubst Mara Schmidt.", [hc("Johann schubst Mara Schmidt", wirkung="gewalt", pruefung=JA, ziel="Mara Nowak")]),
            "N3": ("Johann Weber winkt.", [hc("Johann Weber winkt", akteur="Johann Weber", wirkung="ohne_koerperwirkung", pruefung=dict(JA, taeter="Johann Weber"), ziel=None)]),
            "N4": ("Johann Weber sagt: Hallo.", [rc("Hallo.", akteur="Johann Weber", einleitung="Johann Weber sagt:")]),
            "N3b": ("Johann Weber winkt.", [hc("Johann Weber winkt", akteur=J, wirkung="ohne_koerperwirkung", pruefung=dict(JA, taeter="Johann Weber"), ziel=None)]),
            "N4b": ("Johann Weber sagt: Hallo.", [rc("Hallo.", akteur=J, einleitung="Johann Weber sagt:")]),
            "N4c": ("Johann Weber sagt: Hallo.", [rc("Hallo.", akteur=J, einleitung="sagt:")]),
        }

    def _no_effect_on_mara(self, key, r):
        s = self.commit(r)
        phys = [f for f in s.get("facts", []) if f.get("kind") == "physical"]
        self.assertEqual(phys, [], key)
        self.assertFalse([f for f in s.get("facts", []) if f.get("kind") == "action" and f.get("targetId") == self.M["id"]], key)
        self.assertEqual(pain(s, self.M["id"]), 0.0, key)
        return s

    def _run_negatives(self):
        for key, (raw, comps) in self._cases().items():
            r = self.bind(raw, copy.deepcopy(comps))
            self.assertFalse([a for a in r["actions"] if a.get("targetId") == self.M["id"]], key)
            if key.startswith("N3"):
                self.assertEqual(r["actions"], [], key); self.assertIn("akteur_ist_nicht_der_sprecher", self.grunds(r), key)
            if key.startswith("N4"):
                self.assertEqual(r["speech"], "", key)
                self.assertTrue(set(self.grunds(r)) & {"rede_akteur_ist_nicht_der_sprecher", "rede_sprecher_unklar", "rede_sprecher_name_unklar"}, (key, self.grunds(r)))
            if key in ("N1", "N2"):
                self.assertTrue(set(self.grunds(r)) & {"ziel_unklar", "ziel_nicht_anwesend_oder_unbekannt", "ziel_name_unklar"}, (key, self.grunds(r)))
                self.assertEqual([(a.get("targetId"), a.get("effectValid")) for a in r["actions"]], [(None, False)], key)
            s = self._no_effect_on_mara(key, r)
            self.assertFalse([f for f in s.get("facts", []) if f.get("kind") == "speech" and f.get("actorId") == self.J["id"]
                              and key.startswith("N4")], key)

    def test_a_resolver_full_name_never_falls_back_to_a_first_name(self):
        figs = [self.J, self.M]
        self.assertEqual(kernel.figure_ids_for_name("Mara Schmidt", figs), set())
        self.assertEqual(kernel.figure_ids_for_name("Johann Weber", figs), set())
        self.assertEqual(kernel.figure_ids_for_name("Mara", figs), {self.M["id"]})
        self.assertEqual(kernel.figure_ids_for_name("Mara Nowak.", figs), {self.M["id"]})
        self.assertEqual(kernel.figure_ids_for_name("mara nowak", list(reversed(figs))), {self.M["id"]})
        self.assertIsNone(kernel._match_figure("Mara Schmidt", figs))
        self.assertEqual(kernel.component_party("Johann Weber", self.J["id"], figs, ["Johann Bruckner", "Johann"]), "fremd")
        self.assertEqual(kernel.component_party("Johann", self.J["id"], figs, ["Johann Bruckner"]), "eigen")

    def test_b_text_reading_unknown_full_name_names_nobody(self):
        figs = [self.J, self.M]
        self.assertEqual(kernel.figures_named_in_text("Johann schubst Mara Schmidt.", figs), ({self.J["id"]}, True))
        self.assertEqual(kernel.figures_named_in_text("Johann schubst Mara.", figs), ({self.J["id"], self.M["id"]}, False))
        self.assertEqual(kernel.figures_named_in_text("Johann schubst Mara Nowak.", figs), ({self.J["id"], self.M["id"]}, False))
        # V92 Paket 14 (Paket-13-Pruefung N1): a shorter literal reading ("Mara") never decides where the name of the text ends -
        # "Mara Wasser" and "Mara Schmidt" stay unclear by their form (fail-closed)
        self.assertEqual(kernel.figures_named_in_text("Johann reicht Mara Wasser.", figs, ["Mara"]), ({self.J["id"]}, True))
        self.assertEqual(kernel.figures_named_in_text("Johann schubst Mara Schmidt.", figs, ["Mara"]), ({self.J["id"]}, True))
        self.assertEqual(kernel.figures_named_in_text("Johann reicht Mara Wasser.", figs), ({self.J["id"]}, True))
        self.assertEqual(kernel.figures_named_in_text("Johann schubst Mara Schmidt.", figs, ["Mara Schmidt"]), ({self.J["id"]}, True))
        # an unknown person with no name word of the cast: a name (capitalised) is unknown, a pronoun the reading returned is none
        self.assertEqual(kernel.figures_named_in_text("Johann schubst Peter.", figs, ["Peter"]), ({self.J["id"]}, True))
        self.assertEqual(kernel.figures_named_in_text("Johann schubst sie.", figs, ["sie"]), ({self.J["id"]}, False))
        self.assertEqual(kernel._named_by_name_part("Ich habe Mara Schmidt gesehen.", figs), set())
        self.assertEqual(kernel._named_by_name_part("Ich habe Mara gesehen.", figs), {self.M["id"]})

    def test_e_negatives_n1_to_n4_commit_nothing_for_mara_or_johann(self):
        self._run_negatives()

    def test_e_negatives_with_reversed_cast_order(self):
        self.chars = [self.M, self.J]; self.present = [self.M["id"], self.J["id"]]
        self._run_negatives()

    def test_e_negatives_with_the_literal_target_reading(self):
        for ziel in ("Mara Schmidt", "Mara Nowak", None):
            r = self.bind("Johann schubst Mara Schmidt.", [hc("Johann schubst Mara Schmidt", wirkung="gewalt", pruefung=dict(JA, ziel="Mara Schmidt"), ziel=ziel)])
            self.assertEqual([(a.get("targetId"), a.get("effectValid")) for a in r["actions"]], [(None, False)], ziel)
            self._no_effect_on_mara(ziel, r)

    def test_e_positives_p1_p2(self):
        r = self.bind("Johann Bruckner winkt.", [hc("Johann Bruckner winkt", wirkung="ohne_koerperwirkung", pruefung=dict(JA, taeter="Johann Bruckner"), ziel=None)])
        self.assertEqual([a["text"] for a in r["actions"]], ["Johann Bruckner winkt"]); self.assertEqual(self.grunds(r), [])
        for chars in ([self.J, self.M], [self.M, self.J]):
            self.chars = chars; self.present = [c["id"] for c in chars]
            r = self.bind("Johann schubst Mara Nowak.", [hc("Johann schubst Mara Nowak", wirkung="gewalt", pruefung=dict(JA, ziel="Mara Nowak"), ziel="Mara Nowak")])
            self.assertEqual([a.get("targetId") for a in r["actions"]], [self.M["id"]])
            r = self.bind("Johann reicht Mara ein Glas Wasser.", [hc("Johann reicht Mara ein Glas Wasser", wirkung="ohne_koerperwirkung", pruefung=dict(JA, ziel="Mara"), ziel="Mara Nowak")])
            self.assertEqual([a.get("targetId") for a in r["actions"]], [self.M["id"]]); self.assertEqual(self.grunds(r), [])
            # V92 Paket 14: "Mara Wasser" stays unclear even with the reading "Mara" (fail-closed, see Paket-13-Pruefung N1)
            r = self.bind("Johann reicht Mara Wasser.", [hc("Johann reicht Mara Wasser", wirkung="ohne_koerperwirkung", pruefung=dict(JA, ziel="Mara"), ziel="Mara Nowak")])
            self.assertEqual([a.get("targetId") for a in r["actions"]], [None]); self.assertIn("ziel_name_unklar", self.grunds(r))

    def test_e_two_same_named_present_and_absent_figure(self):
        sch = copy.deepcopy(self.M); sch["id"] = "char_test_mara_schmidt"; sch["name"] = "Mara Schmidt"; sch["aliases"] = []
        for chars in ([self.J, self.M, sch], [sch, self.M, self.J]):
            self.chars = chars; self.present = [c["id"] for c in chars]
            r = self.bind("Johann schubst Mara Schmidt.", [hc("Johann schubst Mara Schmidt", wirkung="gewalt", pruefung=dict(JA, ziel="Mara Schmidt"), ziel="Mara Schmidt")])
            self.assertEqual([a.get("targetId") for a in r["actions"]], [sch["id"]])
            r = self.bind("Johann schubst Mara.", [hc("Johann schubst Mara", wirkung="gewalt", pruefung=dict(JA, ziel="Mara"), ziel="Mara Nowak")])
            self.assertEqual([a.get("targetId") for a in r["actions"]], [None]); self.assertIn("ziel_unklar", self.grunds(r))
        # Mara Schmidt known in the world but ABSENT: nobody of the present cast is meant
        self.chars = [self.J, self.M, sch]; self.present = [self.J["id"], self.M["id"]]
        for ziel in ("Mara Schmidt", "Mara Nowak", None):
            r = self.bind("Johann schubst Mara Schmidt.", [hc("Johann schubst Mara Schmidt", wirkung="gewalt", pruefung=JA, ziel=ziel)])
            self.assertEqual([(a.get("targetId"), a.get("effectValid")) for a in r["actions"]], [(None, False)], ziel)

    def _avatar_bind(self, raw, comps):
        # the avatar binder binds the selected recipient (UI) as default target where the act's words name nobody else
        return kernel.bind_input_components(raw, comps, actor_id=self.J["id"], actor_names=["Johann Bruckner"], figures=self.chars,
                                            present_ids=self.present, default_target=self.M["id"], text_tense=None, addressee_id=self.M["id"])

    def test_d_selected_recipient_never_replaces_a_named_unknown_target(self):
        # "Ich schubse Peter." with Mara selected: the planner gave no target (live: "Johann schubst Peter." 1 of 2 without
        # ziel); the literal reading names Peter -> the recipient is not taken, no effect on Mara
        r = self._avatar_bind("Ich schubse Peter.", [hc("Ich schubse Peter", akteur="ich", wirkung="gewalt", pruefung=dict(JA, ziel="Peter"), ziel=None)])
        self.assertEqual([(a.get("targetId"), a.get("effectValid")) for a in r["actions"]], [(None, False)])
        r = self._avatar_bind("Ich schubse Mara Schmidt.", [hc("Ich schubse Mara Schmidt", akteur="ich", wirkung="gewalt", pruefung=JA, ziel=None)])
        self.assertEqual([(a.get("targetId"), a.get("effectValid")) for a in r["actions"]], [(None, False)])
        # a pronoun the reading returned is no name: the selected recipient stays the target (no false negative)
        for z in ("dich", "", None):
            pr = dict(JA, ziel=z) if z is not None else JA
            r = self._avatar_bind("Ich umarme dich.", [hc("Ich umarme dich", akteur="ich", wirkung="zaertlich", pruefung=pr, ziel=None)])
            self.assertEqual([a.get("targetId") for a in r["actions"]], [self.M["id"]], z)

    def test_d_speech_announcement_naming_nobody_needs_the_speaker_reading(self):
        raw = "Peter sagt: „Hallo.“"
        c = rc("Hallo.", akteur="Johann Bruckner", einleitung="Peter sagt:")       # planner error measured live 05.11. (1 of 2)
        self.assertEqual(kernel.speaker_reading_indices(raw, [c], self.chars), [0])
        r = self.bind(raw, [copy.deepcopy(c)]); self.assertEqual(r["speech"], "")
        self.assertTrue(set(self.grunds(r)) & {"rede_sprecher_fehlt", "rede_sprecher_unklar"}, self.grunds(r))      # unproven speaker
        r = self.bind(raw, [rc("Hallo.", akteur="Johann Bruckner", einleitung="Peter sagt:", sprecher="Peter")])
        self.assertEqual(r["speech"], ""); self.assertIn("rede_akteur_ist_nicht_der_sprecher", self.grunds(r))
        r = self.bind("Johann sagt: „Hallo.“", [rc("Hallo.", einleitung="Johann sagt:")])                  # names the figure: no reading
        self.assertEqual(r["speech"].strip("“"), "Hallo."); self.assertFalse(kernel.speaker_reading_needed("Johann sagt:", self.chars)[0])
        r = self.bind("Er lächelt und sagt: „Hallo.“", [hc("Er lächelt", wirkung="ohne_koerperwirkung", pruefung=JA, ziel=None), rc("Hallo.", einleitung="sagt:", sprecher="figur")])
        self.assertEqual(len(r["actions"]), 1); self.assertTrue(r["speech"].startswith("Hallo"))

    def test_d_own_act_inside_the_announcement_is_its_own_component(self):
        # live 05.11. with the cast as context: ONE speech with einleitung "Johann lächelt und sagt" (2 of 2; 1 of 3 after the prompt fix)
        raw = "Johann lächelt und sagt: „Schön, dich zu sehen.“"
        speech = rc("Schön, dich zu sehen.", einleitung="Johann lächelt und sagt", sprecher="Johann")
        speech["sprecherPruefung"]["handlung"] = "Johann lächelt"
        self.assertEqual(kernel.speaker_reading_indices(raw, [speech], self.chars), [0])
        extra = kernel.announcement_act_components(raw, [speech], "Johann Bruckner")
        self.assertEqual([(c["segment"], c["ansageHandlung"]) for c in extra], [("Johann lächelt", True)])
        extra[0]["vollzugPruefung"] = dict(JA, taeter="Johann")
        r = self.bind(raw, [speech] + extra)
        self.assertEqual([a["text"] for a in r["actions"]], ["Johann lächelt"]); self.assertTrue(r["speech"].startswith("Schön, dich zu sehen"))
        self.assertEqual([g for g in self.grunds(r) if g != "wirkung_unklar"], [])     # no body class proposed (like a marker component)
        s = self.commit(r)
        self.assertEqual(sorted(f.get("kind") for f in s["facts"] if f.get("actorId") == self.J["id"] and f.get("kind") in ("action", "speech")), ["action", "speech"])
        # its own blind reading still decides: denied -> no act, the speech stays
        extra[0]["vollzugPruefung"] = {"geschieht": False, "art": "verneint", "beleg": "nicht", "taeter": "Johann"}
        r = self.bind(raw, [speech] + extra)
        self.assertEqual(r["actions"], []); self.assertTrue(r["speech"].startswith("Schön")); self.assertIn("handlung_nicht_vollzogen", self.grunds(r))
        # a foreign doer inside the announcement: the act is not the figure's
        extra[0]["vollzugPruefung"] = dict(JA, taeter="Mara")
        self.assertIn("akteur_ist_nicht_der_sprecher", self.grunds(self.bind(raw, [speech] + extra)))
        # without a reading for the server component: unproven, never an act
        extra[0].pop("vollzugPruefung")
        self.assertIn("vollzug_nicht_geprueft", self.grunds(self.bind(raw, [speech] + extra)))
        # the reading's act reaches into the speech verb: no server component, but never silently swallowed - visible
        sp4 = rc("Ruhe!", einleitung="Johann schlägt auf den Tisch und brüllt", sprecher="Johann")
        sp4["sprecherPruefung"]["handlung"] = "Johann schlägt auf den Tisch und brüllt"
        raw4 = "Johann schlägt auf den Tisch und brüllt: „Ruhe!“"
        self.assertEqual(kernel.announcement_act_components(raw4, [sp4], "Johann Bruckner"), [])
        r = self.bind(raw4, [sp4]); self.assertTrue(r["speech"].startswith("Ruhe")); self.assertIn("rest_ohne_komponente", self.grunds(r))
        # a speaking manner is no act: no component
        sp2 = rc("Hallo.", einleitung="sagt leise", sprecher="figur"); sp2["sprecherPruefung"]["handlung"] = None
        self.assertEqual(kernel.announcement_act_components("Johann sagt leise: „Hallo.“", [sp2], "Johann Bruckner"), [])
        # a name the reading gives that is not inside the announcement: no component
        sp3 = rc("Hallo.", einleitung="sagt", sprecher="figur"); sp3["sprecherPruefung"]["handlung"] = "Johann lächelt"
        self.assertEqual(kernel.announcement_act_components("Johann sagt: „Hallo.“", [sp3], "Johann Bruckner"), [])

    def test_e_direct_and_mixed_speech_mentioning_an_unknown_person(self):
        r = self.bind("Hallo Mara Schmidt.", [rc("Hallo Mara Schmidt.")])
        self.assertEqual(r["speech"], "Hallo Mara Schmidt.")                                               # speech may name anyone
        self.assertEqual(kernel.bind_referents("Hallo Mara Schmidt.", self.chars), [])                       # but binds nobody of the cast
        r = self.bind("*Johann winkt.* Hallo Mara Schmidt.", [hc("Johann winkt", wirkung="ohne_koerperwirkung", pruefung=JA, ziel=None), rc("Hallo Mara Schmidt.")])
        self.assertEqual(len(r["actions"]), 1); self.assertEqual(r["speech"], "Hallo Mara Schmidt.")
        s = self.commit(r)
        self.assertFalse([f for f in s.get("facts", []) if f.get("kind") == "physical"])

    def test_c_effect_check_same_figure_and_boundary_and_appraisal(self):
        figs = [self.J, self.M]
        self.assertFalse(kernel._same_figure("Mara Schmidt", "Mara Nowak", figs))
        self.assertTrue(kernel._same_figure("Mara", "Mara Nowak", figs))
        w = kernel.apply_effect_check({"art": "gewalt", "ziel": "Mara Nowak"}, "Johann schubst Mara Schmidt",
                                      {"bestaetigt": True, "zeit": "jetzt", "ziel": "Mara Schmidt", "beleg": "schubst"}, figures=figs)
        self.assertEqual((w["art"], w["pruefung"]["grund"]), ("ohne_koerperwirkung", "ziel_abweichend"))
        s = {"scene": {"presentIds": [self.J["id"], self.M["id"]], "placeId": "x"}, "turns": [], "relations": [], "facts": []}
        g = kernel._resolve_grenze(s, {"status": "validiert", "gilt_fuer": "jede_beruehrung", "wer": "Mara Schmidt"}, figs, self.J["id"])
        self.assertEqual((g.get("status"), g.get("werId")), ("ungueltig", None))
        g = kernel._resolve_grenze(s, {"status": "validiert", "gilt_fuer": "jede_beruehrung", "wer": "Mara"}, figs, self.J["id"])
        self.assertEqual(g.get("werId"), self.M["id"])
        # appraisal rows are bound by the same contract: "Mara Schmidt" is no appraisal of Mara Nowak
        sess = {"id": "a", "turnIndex": 2, "scene": {"presentIds": [self.J["id"], self.M["id"]]}, "runtimes": {}, "facts": [], "relations": []}
        pend = [{"id": self.M["id"], "name": "Mara Nowak", "events": [{"fact": {"id": "f1", "actorId": self.J["id"], "targetId": self.M["id"], "turn": 1, "kind": "action"}}]}]
        _s, proto = kernel.apply_appraisals(sess, pend, {"bewertungen": [{"figur": "Mara Schmidt"}]}, natives=figs)
        self.assertIn("keine_bewertung", proto[0]["rejects"])
        _s, proto = kernel.apply_appraisals(sess, pend, {"bewertungen": [{"figur": "Mara"}]}, natives=figs)
        self.assertNotIn("keine_bewertung", proto[0]["rejects"])

    def test_d_planner_cast_is_this_sessions_present_figures_only(self):
        other = copy.deepcopy(self.M); other["id"] = "char_other_world"; other["name"] = "Mara Fremd"
        s = {"scene": {"presentIds": [self.J["id"], self.M["id"], "char_not_in_cast"]}}
        cast = kernel.planner_cast(s, [self.J, self.M, other])
        self.assertEqual([c["id"] for c in cast], [self.J["id"], self.M["id"]])
        self.assertEqual(set(cast[0]), {"id", "name", "beinamen", "anwesend"})


class P13PuppetRoute(unittest.TestCase):
    """Echte Route /api/kernel/puppet, FakeProvider wie die Live-Messung 05.11. (Planer mit Besetzung bildet Fremdnamen ab)."""
    setUp = _PV.PuppetRouteChain.setUp
    session = _PV.PuppetRouteChain.session
    puppet = _PV.PuppetRouteChain.puppet
    snapshot = _PV.PuppetRouteChain.snapshot
    _nothing_committed = _PV.PuppetRouteChain._nothing_committed
    _act_comp = _PV.PuppetRouteChain._act_comp

    def _payload(self, prov, branch):
        # Stand 11 (nur Aufrufstruktur): Fachlesungen kommen aus der ersten Antwort - ihre Anfrage-Nutzlast steht in prov.abrufe
        lesung = {"Vollzug prüfen": "vollzug", "Sprecher prüfen": "sprecher"}.get(branch)
        if lesung:
            return prov.abrufe(lesung)
        return [json.loads(u) for sy, u in prov.systems if branch in sy]

    def test_planner_gets_present_cast_and_separate_ids_readings_get_none(self):
        prov = FakeProvider([plan("smalltalk", "chat", [comp("rede", "Hallo.")])])
        r = self.puppet(prov, "Hallo.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        p = self._payload(prov, "Konjunktives Gedächtnis")[0]
        self.assertEqual({c["id"] for c in p["anwesende"]}, {self.J["id"], self.M["id"]})
        self.assertEqual((p["sprecher_id"], p["puppet_figur_id"], p["empfaenger_id"]), (self.J["id"], self.J["id"], self.M["id"]))
        self.assertTrue(all(set(c) == {"id", "name", "beinamen", "anwesend"} for c in p["anwesende"]))
        prov = FakeProvider([plan("action", "act", [self._act_comp("Johann winkt")])])
        self.puppet(prov, "Johann winkt.")
        self.assertTrue(self._payload(prov, "Vollzug prüfen"))
        self.assertTrue(all("anwesende" not in u for u in self._payload(prov, "Vollzug prüfen")))

    def test_n1_n2_live_shape_planner_maps_to_mara_nowak_server_locks(self):
        s0 = self.session()
        ok_effect = lambda p: {"bestaetigt": True, "zeit": "jetzt", "ziel": p.get("ziel"), "beleg": "schubst"}
        for ziel in ("Mara Nowak", "Mara Schmidt"):
            c = dict(self._act_comp("Johann schubst Mara Schmidt"), ziel=ziel, wirkung="gewalt")
            prov = FakeProvider([plan("action", "act", [c])] * 2, wirkung=ok_effect,
                                vollzug=lambda p: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "Johann", "ziel": "Mara Schmidt"})
            # V92 Paket 16: a full name nobody carries that holds a cast name - the operator is asked first, nothing stored
            r = self._nothing_committed(prov, "Johann schubst Mara Schmidt.", None, code="IDENTITAET_KLAEREN")
            self.assertEqual([(q["text"], [x["id"] for x in q["kandidaten"]]) for q in r.get_json()["klaerung"]], [("Mara Schmidt", [self.M["id"]])])
            r = self.puppet(prov, "Johann schubst Mara Schmidt.", [{"text": "Mara Schmidt", "id": None}])
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
            s = self.session()
            last = [f for f in s["facts"] if f.get("kind") == "action"][-1]
            self.assertIsNone(last.get("targetId"), ziel)
            self.assertEqual(pain(s, self.M["id"]), pain(s0, self.M["id"]), ziel)
            self.assertFalse([f for f in s["facts"] if f.get("kind") == "physical"], ziel)
            amb = [a.get("grund") for a in (s["turnTruths"][-1].get("input_component_ambiguity") or [])]
            self.assertTrue(set(amb) & {"ziel_unklar", "ziel_nicht_anwesend_oder_unbekannt"}, amb)

    def test_n3_n4_live_shape_planner_names_the_puppet_server_locks(self):
        c = dict(self._act_comp("Johann Weber winkt"), akteur="Johann Bruckner")
        prov = FakeProvider([plan("action", "act", [c])] * 2, vollzug=lambda p: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "Johann Weber", "ziel": ""})
        # V92 Paket 16: the reading's doer "Johann Weber" holds the cast name "Johann" - asked first; "nobody" -> foreign act, nothing stored
        self._nothing_committed(prov, "Johann Weber winkt.", None, code="IDENTITAET_KLAEREN")
        self._nothing_committed(prov, "Johann Weber winkt.", None, klaerungen=[{"text": "Johann Weber", "id": None}])
        rd = dict(comp("rede", "Hallo."), einleitung="Johann Weber sagt:")
        # V92 Paket 16: without a literal reading the boundary of "Johann Weber" is unproven - asked first (nothing stored); the
        # answer "nobody of the cast" leaves it a foreign speech: nothing stored
        prov = FakeProvider([plan("smalltalk", "chat", [rd])] * 2)
        r = self._nothing_committed(prov, "Johann Weber sagt: „Hallo.“", None, code="IDENTITAET_KLAEREN")
        self.assertEqual([q["text"] for q in r.get_json()["klaerung"]], ["Johann Weber"])
        self._nothing_committed(prov, "Johann Weber sagt: „Hallo.“", None, klaerungen=[{"text": "Johann Weber", "id": None}])
        rd = dict(comp("rede", "Hallo."), einleitung="Peter sagt:")
        prov = FakeProvider([plan("smalltalk", "chat", [rd])], sprecher=lambda p: {"sprecher": "Peter", "beleg": "Peter sagt"})
        self._nothing_committed(prov, "Peter sagt: „Hallo.“", None)
        self.assertTrue(self._payload(prov, "Sprecher prüfen"), "the blind speaker reading ran")
        self.assertTrue(all("anwesende" not in json.dumps(u) for u in self._payload(prov, "Sprecher prüfen")))

    def test_own_act_inside_the_announcement_is_read_and_stored(self):
        rd = dict(comp("rede", "Schön, dich zu sehen."), einleitung="Johann lächelt und sagt")
        prov = FakeProvider([plan("smalltalk", "chat", [rd])],
                            sprecher=lambda p: {"sprecher": "Johann", "beleg": "Johann lächelt und sagt", "handlung": "Johann lächelt" if p.get("ansage") else None},
                            vollzug=lambda p: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "Johann", "ziel": ""})
        r = self.puppet(prov, "Johann lächelt und sagt: „Schön, dich zu sehen.“")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.session()
        self.assertEqual([f["text"] for f in s["facts"] if f.get("kind") == "action" and f.get("actorId") == self.J["id"]], ["Johann lächelt"])
        self.assertTrue([t for t in s["turns"] if t.get("speakerId") == self.J["id"]][-1]["speech"].startswith("Schön, dich zu sehen"))
        self.assertEqual(self._payload(prov, "Sprecher prüfen")[0]["ansage"], "Johann lächelt und sagt")
        self.assertEqual(len(self._payload(prov, "Vollzug prüfen")), 1, "the act got its own vollzug reading (Stand 11: aus der ersten Antwort)")

    def test_p1_p2_and_follow_up_turn_after_restart(self):
        r = self.puppet(FakeProvider([plan("action", "act", [self._act_comp("Johann Bruckner winkt")])]), "Johann Bruckner winkt.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        ok_effect = lambda p: {"bestaetigt": True, "zeit": "jetzt", "ziel": p.get("ziel"), "beleg": "schubst"}
        s0 = self.session()
        c = dict(self._act_comp("Johann schubst Mara Nowak"), ziel="Mara Nowak", wirkung="gewalt")
        prov = FakeProvider([plan("action", "act", [c])], wirkung=ok_effect,
                            vollzug=lambda p: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "Johann", "ziel": "Mara Nowak"})
        r = self.puppet(prov, "Johann schubst Mara Nowak.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.session()                                           # new connection = reader after restart
        self.assertEqual([f for f in s["facts"] if f.get("kind") == "action"][-1].get("targetId"), self.M["id"])
        self.assertGreater(pain(s, self.M["id"]), pain(s0, self.M["id"]))
        self.assertEqual({f.get("targetId") for f in s["facts"] if f.get("kind") == "physical"}, {self.M["id"]})
        r = self.puppet(FakeProvider([plan("smalltalk", "chat", [comp("rede", "Alles gut?")])]), "Alles gut?")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual([t for t in self.session()["turns"] if t.get("speakerId") == self.J["id"]][-1]["speech"], "Alles gut?")

    def test_two_maras_present_reversed_order_and_absent_schmidt(self):
        with closing(connect(self.dbp)) as c:
            jrow = c.execute("select world_id, owner_user_id, json from characters where id=?", (self.M["id"],)).fetchone()
            w = dict(json.loads(jrow[2])); w["id"] = "char_test_mara_schmidt"; w["name"] = "Mara Schmidt"; w["aliases"] = []
            c.execute("INSERT INTO characters(id, world_id, owner_user_id, json) VALUES(?,?,?,?)", (w["id"], jrow[0], jrow[1], json.dumps(w, ensure_ascii=False)))
            create_session(c, {"id": "ses_rev", "worldId": jrow[0], "name": "REV", "presentIds": [w["id"], self.M["id"], self.J["id"]]}, "admin")
            create_session(c, {"id": "ses_abs", "worldId": jrow[0], "name": "ABS", "presentIds": [self.J["id"], self.M["id"]]}, "admin"); c.commit()
        ok_effect = lambda p: {"bestaetigt": True, "zeit": "jetzt", "ziel": p.get("ziel"), "beleg": "schubst"}

        def run(sid, ziel, klaerungen=None):
            with closing(connect(self.dbp)) as c: before = get_session(c, "admin", sid)
            prov = FakeProvider([plan("action", "act", [dict(self._act_comp("Johann schubst Mara Schmidt"), ziel=ziel, wirkung="gewalt")])], wirkung=ok_effect,
                                vollzug=lambda p: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "Johann", "ziel": "Mara Schmidt"})
            klaerungen = _PV.als_antwort(self, sid, "Johann schubst Mara Schmidt.", klaerungen)   # V92 Paket 17
            with patch.object(urllib.request, "urlopen", prov):
                r = _PV.frage_merken(self, sid, "Johann schubst Mara Schmidt.", self.client.post("/api/kernel/puppet", headers={"X-Matrix-Actor": "admin"}, json={
                    "session": before, "sessionId": sid, "actorUserId": "admin", "figure": {"id": self.J["id"], "name": self.J["name"]},
                    "text": "Johann schubst Mara Schmidt.", "targetId": self.M["id"], **({"klaerungen": klaerungen} if klaerungen else {})}))
            with closing(connect(self.dbp)) as c: return r, before, get_session(c, "admin", sid), prov
        r, b, a, prov = run("ses_rev", "Mara Schmidt")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual([f for f in a["facts"] if f.get("kind") == "action"][-1].get("targetId"), "char_test_mara_schmidt")
        self.assertEqual(pain(a, self.M["id"]), pain(b, self.M["id"]))
        self.assertGreater(pain(a, "char_test_mara_schmidt"), pain(b, "char_test_mara_schmidt"))
        p = [json.loads(u) for sy, u in prov.systems if "Konjunktives Gedächtnis" in sy][0]
        self.assertEqual({c["id"] for c in p["anwesende"]}, {"char_test_mara_schmidt", self.M["id"], self.J["id"]})
        r, b, a, prov = run("ses_abs", "Mara Nowak")                 # Schmidt is in the world, but not in this scene
        self.assertEqual((r.status_code, r.get_json()["code"]), (422, "IDENTITAET_KLAEREN"))   # V92 Paket 16: asked first, nothing stored
        self.assertEqual(len(a["facts"]), len(b["facts"]))
        r, b, a, prov = run("ses_abs", "Mara Nowak", [{"text": "Mara Schmidt", "id": None}])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertIsNone([f for f in a["facts"] if f.get("kind") == "action"][-1].get("targetId"))
        self.assertEqual((pain(a, self.M["id"]), pain(a, "char_test_mara_schmidt")), (pain(b, self.M["id"]), pain(b, "char_test_mara_schmidt")))
        p = [json.loads(u) for sy, u in prov.systems if "Konjunktives Gedächtnis" in sy][0]
        self.assertNotIn("char_test_mara_schmidt", [c["id"] for c in p["anwesende"]], "absent figure is no planner context")


class EchoProvider(FakeProvider):
    """FakeProvider whose planner answer names the speaker exactly as the server named it in the payload ("{sprecher}")."""
    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode())
        if "Konjunktives Gedächtnis" in body["messages"][0]["content"] and self.plans:
            sp = json.loads(body["messages"][1]["content"]).get("sprecher") or ""
            self.plans[0] = json.loads(json.dumps(self.plans[0], ensure_ascii=False).replace("{sprecher}", sp))
        return super().__call__(req, timeout)


class P13AvatarRoute(unittest.TestCase):
    """Echte Route /api/kernel/prepare (Avatar Johann, Empfaengerin Mara)."""
    setUp = _AV.AvatarRouteChain.setUp
    session = _AV.AvatarRouteChain.session
    snapshot = _AV.AvatarRouteChain.snapshot
    prepare = _AV.AvatarRouteChain.prepare
    mine = _AV.AvatarRouteChain.mine

    def test_avatar_unknown_full_name_target_and_referents(self):
        s0 = self.session()
        ok_effect = lambda p: {"bestaetigt": True, "zeit": "jetzt", "ziel": p.get("ziel"), "beleg": "schubse"}
        a = dict(act("Ich schubse Mara Schmidt", akteur="ich", ziel="Mara Nowak"), wirkung="gewalt")
        prov = FakeProvider([plan("action", "act", [a])] * 2, wirkung=ok_effect,
                            vollzug=lambda p: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "figur", "ziel": "Mara Schmidt"})
        r = self.prepare(prov, "Ich schubse Mara Schmidt.")                                   # V92 Paket 16: asked first
        self.assertEqual((r.status_code, (r.get_json() or {}).get("code")), (422, "IDENTITAET_KLAEREN"), r.get_data(as_text=True)[:300])
        r = self.prepare(prov, "Ich schubse Mara Schmidt.", [{"text": "Mara Schmidt", "id": None}])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.session()
        self.assertEqual([(f.get("text"), f.get("targetId"), (f.get("plan") or {}).get("about_ids")) for f in s["facts"] if f.get("kind") == "action"],
                         [("Ich schubse Mara Schmidt", None, [])], "the act stays visible, bound to nobody")
        amb = [a.get("grund") for a in (s["turnTruths"][-1].get("input_component_ambiguity") or [])]
        self.assertTrue(set(amb) & {"ziel_unklar", "ziel_nicht_anwesend_oder_unbekannt"}, amb)
        self.assertFalse([f for f in s["facts"] if f.get("kind") == "action" and f.get("targetId") == self.M["id"]])
        self.assertFalse([f for f in s["facts"] if f.get("kind") == "physical"])
        self.assertEqual(pain(s, self.M["id"]), pain(s0, self.M["id"]))
        p = [json.loads(u) for sy, u in prov.systems if "Konjunktives Gedächtnis" in sy][0]
        self.assertEqual({c["id"] for c in p["anwesende"]}, {self.J["id"], self.M["id"]})
        self.assertEqual((p["sprecher_id"], p["empfaenger_id"]), (self.J["id"], self.M["id"]))
        self.assertNotIn("puppet_figur_id", p)

    def test_operator_speech_named_as_the_server_named_it_is_the_operators(self):
        # Browser-Folgezug 05.11.: after a reload the input came as Bedienperson; the reading named the speaker as the server had
        # named it to the planner ("Bedienperson") and the binder did not know that name as the operator's own -> 422
        s = self.session()
        truth = {"userId": "admin", "operatorId": "admin", "worldId": s["worldId"], "sessionId": "ses_av", "role": "teilnehmer",
                 "speakerId": self.M["id"], "responseSpeakerId": self.M["id"], "avatarId": self.J["id"], "inputActorId": "user",
                 "speakAs": "operator", "targetId": self.M["id"], "authority": "teilnehmer", "presentIds": s["scene"]["presentIds"],
                 "inputKind": "speech", "text": "Wie geht es dir?"}
        prov = EchoProvider([plan("question", "ask", [rede("Wie geht es dir?", akteur="{sprecher}")])])
        with patch.object(urllib.request, "urlopen", prov):
            r = self.client.post("/api/kernel/prepare", headers={"X-Matrix-Actor": "admin"}, json={
                "session": s, "actorUserId": "admin", "trace_id": "kpr_op", "truth": truth, "speaker": {"id": self.M["id"], "name": self.M["name"]},
                "present": [{"id": self.J["id"], "name": self.J["name"]}, {"id": self.M["id"], "name": self.M["name"]}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        sp = json.loads([u for sy, u in prov.systems if "Konjunktives Gedächtnis" in sy][0])["sprecher"]
        self.assertIn("Bedienperson", sp)
        self.assertEqual([f.get("text") for f in self.session()["facts"] if f.get("kind") == "speech" and f.get("actorId") == "user"], ["Wie geht es dir?"])

    def test_avatar_speech_about_an_unknown_person_binds_no_referent(self):
        prov = FakeProvider([plan("claim", "assert", [rede("Ich habe Mara Schmidt gesehen.", akteur="ich")])])
        r = self.prepare(prov, "Ich habe Mara Schmidt gesehen.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.session()
        self.assertEqual(self.mine("speech")[-1], "Ich habe Mara Schmidt gesehen.")
        dumped = json.dumps([tt.get("plan") or tt.get("userPlan") or {} for tt in s.get("turnTruths") or []], ensure_ascii=False)
        self.assertNotIn(f'"betrifft_ids": ["{self.M["id"]}"]', dumped)
        about = [m for m in json.dumps(s, ensure_ascii=False).split('"about_ids": ')[1:]]
        self.assertFalse([x for x in about if x.startswith(f'["{self.M["id"]}"')], "no memory about Mara Nowak from 'Mara Schmidt'")


if __name__ == "__main__":
    unittest.main()
