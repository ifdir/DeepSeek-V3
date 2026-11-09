"""V92 (Kettenvertrag §6): Puppet-Wirkungskette - Quellenvertrag der Disposition, Einwilligungsstand, Betroffenheit.
Fixture: echter Live-Zustand (04.11.2026, Johann/Mara, drei Übergriffe, drei Ablehnungen 'diese_tat')."""
import copy, json, unittest
from pathlib import Path
from matrix_api import kernel
from test_v84_kausal_chain import scene, proposed, NATIVES, MARA, JOHANN

FIX = Path(__file__).parent / "fixtures" / "v92_live_k3b_state.json"


class EinwilligungStand(unittest.TestCase):
    def setUp(self):
        self.s = json.loads(FIX.read_text(encoding="utf-8"))
        self.pid = next(p["id"] for p in self.s["propositions"] if p.get("kind") == "koerperkontakt")

    def test_fixture_has_three_one_act_refusals_and_open_container(self):
        lc = [f for f in self.s["facts"] if f.get("kind") == "lifecycle" and f.get("event_kind") == "refusal"]
        self.assertEqual(len(lc), 3)
        self.assertTrue(all((f["payload"]["koerperkontakt"]["scope"] == "diese_tat") for f in lc))
        self.assertEqual([p["status"] for p in self.s["propositions"] if p["id"] == self.pid], ["open"])

    def test_one_act_refusals_do_not_close_the_container_in_current_state(self):
        cs = kernel.reduce_current_state(self.s)
        self.assertNotIn(self.pid, [p["id"] for p in cs["closedPropositions"]])
        self.assertIn(self.pid, [p["id"] for p in cs["openPropositions"]])

    def test_standing_refusal_for_every_touch_closes_it_as_declined(self):
        s = copy.deepcopy(self.s)
        for f in s["facts"]:
            if f.get("kind") == "lifecycle" and f.get("event_kind") == "refusal":
                f["payload"]["koerperkontakt"]["scope"] = "jede_beruehrung"
        cs = kernel.reduce_current_state(s)
        self.assertIn((self.pid, "declined"), [(p["id"], p["status"]) for p in cs["closedPropositions"]])


class DispositionQuellenvertrag(unittest.TestCase):
    def run_review(self, mutate):
        s, p, e = scene()
        row = proposed()
        src = kernel.appraisal_disposition_source_list(s, MARA, "char_g7_mara", {"char_g7_johann"})
        ids = {x["text"]: x["id"] for x in src}
        q = "Loyal wo sicher, trotzig unter Druck, körperlich-direkt."
        checks = []
        for field in kernel.appraisal_effect_fields(row):
            c = {"feld": field, "urteil": "gestuetzt", "factId": e["id"], "beleg": e["text"],
                 "dispositionsQuelle": ids[q], "dispositionsBeleg": "Loyal wo sicher",
                 "richtung": "steigt" if kernel.appraisal_field_sign(row, field) > 0 else "sinkt",
                 "begruendung": "Loyal wo sicher: Maras Disposition gegenüber diesem Ereignis trägt die Änderung."}
            mutate(c, ids); checks.append(c)
        row["_kausalpruefung"] = {"pruefungen": checks}
        out, diag = kernel.apply_appraisals(s, p, {"bewertungen": [row]}, natives=NATIVES)
        return diag[0]

    def test_payload_source_ids_are_the_validators_ids(self):
        s, p, e = scene()
        pay = kernel.appraisal_payload(s, NATIVES, p)
        fig = pay["figuren"][0]
        ids = {x["id"] for x in fig["dispositionsquellen"]}
        direct = {kernel.appraisal_source_id(t) for t in kernel.appraisal_disposition_sources(s, MARA, "char_g7_mara", {"char_g7_johann"})}
        self.assertEqual(ids, direct); self.assertTrue(ids)

    def test_right_source_id_is_accepted(self):
        d = self.run_review(lambda c, ids: None)
        self.assertFalse([r for r in d["rejects"] if r.startswith("disposition_nicht_belegt")], d["rejects"])
        self.assertTrue(d["runtimeDelta"] or d["relationDelta"])

    def test_source_with_opposite_direction_is_rejected_field_by_field(self):
        """Näheanstieg nach unerwünschter Berührung: Quelle trägt nur das Thema, nicht die Richtung."""
        def opposite(c, ids): c["richtung"] = "sinkt" if c["feld"].startswith("beziehung") and c["feld"].endswith("closeness") else c["richtung"]
        d = self.run_review(opposite)
        self.assertIn("richtung_nicht_belegt:beziehung.0.closeness", d["rejects"])

    def test_missing_direction_on_numeric_field_is_rejected(self):
        def none(c, ids): c.pop("richtung")
        d = self.run_review(none)
        self.assertTrue([r for r in d["rejects"] if r.startswith("richtung_nicht_belegt:zustand") or r.startswith("richtung_nicht_belegt:beziehung")])

    def test_wrong_source_id_is_rejected(self):
        def wrong(c, ids): c["dispositionsQuelle"] = "Qdeadbeef"
        d = self.run_review(wrong)
        self.assertTrue([r for r in d["rejects"] if r.startswith("disposition_nicht_belegt")])
        self.assertFalse(d["runtimeDelta"]); self.assertFalse(d["relationDelta"])

    def test_rendered_projection_instead_of_source_text_is_rejected(self):
        def rendered(c, ids):
            c["dispositionsBeleg"] = 'mag: ["Wärme", "ehrliche Nähe"]'
            c["begruendung"] = 'mag: ["Wärme", "ehrliche Nähe"] trägt die Änderung.'
        d = self.run_review(rendered)
        self.assertTrue([r for r in d["rejects"] if r.startswith("disposition_nicht_belegt")])

    def test_independent_review_still_rejects_unsupported(self):
        def no(c, ids): c["urteil"] = "nicht_gestuetzt"
        d = self.run_review(no)
        self.assertTrue([r for r in d["rejects"] if r.startswith("wirkung_nicht_belegt")])
        self.assertFalse(d["runtimeDelta"])


if __name__ == "__main__":
    unittest.main()


class BerührungStattVerletzung(unittest.TestCase):
    A = "Johann greift Mara an den Hintern."

    def chk(self, reading, **kw):
        return kernel.apply_effect_check({"art": "gewalt", "ziel": "Mara Nowak"}, self.A, reading, figures=[MARA, {"id": "char_g7_johann", "name": "Johann Bruckner"}])

    def test_denied_injury_with_touch_reading_keeps_the_touch_class_with_audit(self):
        w = self.chk({"bestaetigt": False, "zeit": "jetzt", "ziel": "Mara Nowak", "versuch": False, "beruehrung": True,
                      "beruehrungBeleg": "greift Mara an den Hintern"})
        self.assertEqual(w["art"], "zaertlich"); self.assertEqual(kernel.effect_kind_from_wirkung(w["art"]), (True, "social"))
        self.assertEqual((w["pruefung"]["bestaetigt"], w["pruefung"]["vorschlag"], w["pruefung"]["ersatz"]), (False, "gewalt", "zaertlich"))

    def test_without_literal_touch_part_wrong_target_attempt_or_time_the_effect_stays_dropped(self):
        base = {"bestaetigt": False, "zeit": "jetzt", "ziel": "Mara Nowak", "versuch": False, "beruehrung": True, "beruehrungBeleg": "greift Mara an den Hintern"}
        for patch in ({"beruehrungBeleg": "schlägt zu"}, {"ziel": "Johann Bruckner"}, {"versuch": True}, {"zeit": "zukunft"}, {"beruehrung": False}, {"beruehrungBeleg": None}):
            self.assertEqual(self.chk({**base, **patch})["art"], "ohne_koerperwirkung", patch)

    def test_confirmed_violence_is_unchanged(self):
        w = kernel.apply_effect_check({"art": "gewalt", "ziel": "Mara Nowak"}, "Johann schlägt Mara ins Gesicht.",
                                      {"bestaetigt": True, "zeit": "jetzt", "ziel": "Mara Nowak", "beleg": "schlägt Mara ins Gesicht"}, figures=[MARA])
        self.assertEqual(w["art"], "gewalt")


# ---------------------------------------------------------------------------------------------------------------------
# V92 Restrede: Rede nur aus validierten Rede-Komponenten (AMASTER §34.1, §24.7). Live-Befund: "und." als Johanns Rede.
from test_v92_puppet_vertrag import comp, plan, ROOT  # noqa: E402


class RestredeBinder(unittest.TestCase):
    def setUp(self):
        seed = json.loads((ROOT / "matrix_api/gasthaus_seed.json").read_text(encoding="utf-8"))
        by = {c["name"]: c for c in seed["characters"]}
        self.J = next(v for k, v in by.items() if "Johann" in k); self.M = next(v for k, v in by.items() if "Mara" in k)

    def bind(self, raw, comps, **kw):
        pl = plan("action", "act", comps)
        if kw.get("cut"): pl["_abgeschnitten"] = True
        return kernel.bind_puppet_input(raw, pl, self.J, [self.J, self.M], [self.J["id"], self.M["id"]], addressee_id=self.M["id"])

    def grunds(self, r): return [a["grund"] for a in r["ambiguous"]]

    def test_two_acts_joined_by_a_connecting_word_make_no_speech(self):
        r = self.bind("Johann zieht Mara an sich und küsst sie.", [comp("handlung", "Johann zieht Mara an sich", "annaeherung"), comp("handlung", "küsst sie", "zaertlich")])
        self.assertEqual(len(r["actions"]), 2); self.assertIn(r["speech"], (None, ""))
        self.assertEqual(self.grunds(r), [], "das Bindewort ist kein unzugeordneter Text")

    def test_pure_speech_and_spoken_request_stay_speech(self):
        for raw in ("Guten Morgen, Mara.", "Komm bitte her."):
            r = self.bind(raw, [comp("rede", raw)])
            self.assertEqual((r["speech"], r["actions"]), (raw, []))

    def test_pure_act_has_no_speech(self):
        r = self.bind("Johann küsst Mara.", [comp("handlung", "Johann küsst Mara", "zaertlich")])
        self.assertEqual(len(r["actions"]), 1); self.assertIn(r["speech"], (None, ""))

    def test_act_and_real_speech_each_keep_their_part(self):
        # Planner-Zerlegung wie im Live-Lauf 04.11. (rede-Segment "sage: Bleib hier"; das einzelne Bindewort "und" steht zwischen den Komponenten)
        r = self.bind("Ich nehme deine Hand und sage: Bleib hier.", [comp("handlung", "Ich nehme deine Hand", "ohne_koerperwirkung"), comp("rede", "sage: Bleib hier")])
        self.assertEqual(r["speech"], "sage: Bleib hier."); self.assertEqual(len(r["actions"]), 1); self.assertEqual(self.grunds(r), [])

    def test_speech_between_acts_is_kept_in_order(self):
        r = self.bind("Komm her, ich nehme deine Hand, alles wird gut.", [comp("rede", "Komm her"), comp("handlung", "ich nehme deine Hand", "ohne_koerperwirkung"), comp("rede", "alles wird gut")])
        self.assertEqual(r["speech"], "Komm her alles wird gut."); self.assertEqual(len(r["actions"]), 1)

    def test_unassigned_text_is_visible_and_never_spoken(self):
        # Stand 11C (AMASTER §27.4 "Die Puppet-Eingabe ist die tatsaechliche Rede oder Handlung dieser Figur", §34.1 "eine nicht
        # validierte Komponente darf als sichtbare ... Redeprovenienz erhalten bleiben"; Nutzerentscheidung 08.11. 22:22) - hebt
        # Paket-8-Pruefung C6 fuer diesen Fall auf: ungekennzeichneter Text ohne geprufte Handlung und ohne fremden Namen ist die
        # eigene Rede der Figur (Herkunft sichtbar als rest_als_rede), nie eine Handlung. Geschuetzt bleiben unten: Marker-Rest,
        # abgeschnittene Lesung, fremde Rede, fremder Name (P24/R1).
        r = self.bind("Johann nimmt Mara an der Hand. Hallo zusammen!", [comp("handlung", "Johann nimmt Mara an der Hand", "ohne_koerperwirkung")])
        self.assertEqual(r["speech"], "Hallo zusammen!"); self.assertEqual(len(r["actions"]), 1)
        self.assertEqual([(a["grund"], a["segment"]) for a in r["ambiguous"]], [("rest_als_rede", "Hallo zusammen!")])

    def test_speech_component_not_in_input_is_flagged_not_invented(self):
        r = self.bind("Johann küsst Mara.", [comp("handlung", "Johann küsst Mara", "zaertlich"), comp("rede", "ich liebe dich")])
        self.assertIn(r["speech"], (None, "")); self.assertIn("rede_nicht_im_eingang", self.grunds(r))

    def test_act_inside_a_quotation_is_not_executed(self):
        r = self.bind('Johann sagt: "Ich schlage dich."', [comp("handlung", "Ich schlage dich", "gewalt")])
        # Gegenpruefung 04.11. (Fall B): the quoted act the planner mislabelled is no act - and its text is not re-labelled as
        # this figure's speech either (before: speech = whole input). Nothing executable; the ambiguity stays visible.
        self.assertEqual(r["actions"], []); self.assertEqual(r["speech"], ""); self.assertTrue(r.get("nichts_ausfuehrbar"))
        self.assertIn("segment_im_zitat", self.grunds(r))

    def test_cut_reading_shows_the_lost_rest_but_never_speaks_it(self):
        # Paket-8-Pruefung C6 (supersedes V65Z A04 "der Rest bleibt Rede"): a cut reading binds what it lists; the unlisted rest
        # is visible (lesung_abgeschnitten + rest_ohne_komponente), never speech of the figure
        r = self.bind("Johann küsst Mara. Und er flüstert etwas.", [comp("handlung", "Johann küsst Mara", "zaertlich")], cut=True)
        self.assertIn(r["speech"], (None, "")); self.assertEqual(len(r["actions"]), 1)
        self.assertIn("lesung_abgeschnitten", self.grunds(r)); self.assertIn("rest_ohne_komponente", self.grunds(r))

    def test_other_actor_speech_is_not_his_speech(self):
        c = comp("rede", "Lass das"); c["akteur"] = "Mara Nowak"
        r = self.bind("Johann küsst Mara. Lass das", [comp("handlung", "Johann küsst Mara", "zaertlich"), c])
        self.assertIn(r["speech"], (None, "")); self.assertIn("rede_akteur_ist_nicht_der_sprecher", self.grunds(r))


class AvatarPfadGleicherBinder(unittest.TestCase):
    """Avatar-Eingabe (commit_turn) nutzt denselben Binder: keine erfundene Rede aus dem Bindewort, echte Rede bleibt."""
    def run_input(self, raw, comps):
        from test_v92_puppet_vertrag import plan as _plan
        s, p, e = scene('x'); s['facts'] = []; s['witnessKnowledge'] = []; s['turnTruths'] = []; s['avatarId'] = JOHANN['id']; s['role'] = 'teilnehmer'
        t = kernel.bind_turn_truth(user_id='admin', world_id=s['worldId'], session_id=s['id'], role='teilnehmer', speaker_id=MARA['id'],
                                   avatar_id=JOHANN['id'], target_id=MARA['id'], authority='avatar', present_ids=s['scene']['presentIds'],
                                   hears_ids=s['scene']['hearsIds'], input_kind='speech', text=raw, input_actor_id=JOHANN['id'])
        pl = _plan('action', 'act', comps)
        return kernel.commit_turn(s, truth=t, speaker=MARA, present=NATIVES, result={'speech': 'Hm.', 'action': None}, user_plan=pl)

    def mine(self, out, kind): return [f for f in out['facts'] if f.get('actorId') == JOHANN['id'] and f.get('kind') == kind]

    def test_two_acts_no_invented_speech(self):
        from test_v92_puppet_vertrag import comp as _c
        out = self.run_input('Johann zieht Mara an sich und küsst sie.', [_c('handlung', 'Johann zieht Mara an sich', 'annaeherung'), _c('handlung', 'küsst sie', 'zaertlich')])
        self.assertEqual(len(self.mine(out, 'action')), 2)
        self.assertEqual([f.get('text') for f in self.mine(out, 'speech')], [])

    def test_act_and_speech_each_kept(self):
        from test_v92_puppet_vertrag import comp as _c
        out = self.run_input('Komm her, ich nehme deine Hand, alles wird gut.', [_c('rede', 'Komm her'), _c('handlung', 'ich nehme deine Hand', 'ohne_koerperwirkung'), _c('rede', 'alles wird gut')])
        self.assertEqual(len(self.mine(out, 'action')), 1)
        self.assertEqual([f.get('text') for f in self.mine(out, 'speech')], ['Komm her alles wird gut.'])

    # ---- Paket-8-Pruefung C1/C2: Avatar ohne Lesung (kein Provider) ----
    def run_offline(self, raw):
        s, p, e = scene('x'); s['facts'] = []; s['witnessKnowledge'] = []; s['turnTruths'] = []; s['avatarId'] = JOHANN['id']; s['role'] = 'teilnehmer'
        t = kernel.bind_turn_truth(user_id='admin', world_id=s['worldId'], session_id=s['id'], role='teilnehmer', speaker_id=MARA['id'],
                                   avatar_id=JOHANN['id'], target_id=MARA['id'], authority='avatar', present_ids=s['scene']['presentIds'],
                                   hears_ids=s['scene']['hearsIds'], input_kind='speech', text=raw, input_actor_id=JOHANN['id'])
        return kernel.commit_turn(s, truth=t, speaker=MARA, present=NATIVES, result={'speech': 'Hm.', 'action': None}, user_plan=None)

    # ---- Paket-10-Pruefung: Benutzername/Alias sind keine Figurenidentitaet ----
    def test_user_name_of_another_figure_does_not_make_her_act_the_avatars(self):
        from test_v92_puppet_vertrag import comp as _c
        s, p, e = scene('x'); s['facts'] = []; s['witnessKnowledge'] = []; s['turnTruths'] = []; s['avatarId'] = JOHANN['id']; s['role'] = 'teilnehmer'
        s['alias'] = 'Mara Nowak'
        def run(raw, comps):
            t = kernel.bind_turn_truth(user_id='admin', world_id=s['worldId'], session_id=s['id'], role='teilnehmer', speaker_id=MARA['id'],
                                       avatar_id=JOHANN['id'], target_id=MARA['id'], authority='avatar', present_ids=s['scene']['presentIds'],
                                       hears_ids=s['scene']['hearsIds'], input_kind='speech', text=raw, input_actor_id=JOHANN['id'])
            t['user_name'] = 'Mara Nowak'
            from test_v92_puppet_vertrag import plan as _plan
            return kernel.commit_turn(s, truth=t, speaker=MARA, present=NATIVES, result={'speech': 'Hm.', 'action': None}, user_plan=_plan('action', 'act', comps))
        foreign = dict(_c('handlung', 'Mara küsst Johann', 'zaertlich'), akteur='Mara Nowak', ziel='Johann Bruckner')
        foreign['vollzugPruefung'] = {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "Mara Nowak"}
        self.assertEqual(self.mine(run('Mara küsst Johann.', [foreign]), 'action'), [])
        own = dict(_c('handlung', 'Ich lächle', 'ohne_koerperwirkung'), akteur='Ich')
        self.assertEqual([f['text'] for f in self.mine(run('Ich lächle.', [own]), 'action')], ['Ich lächle'])

    def test_offline_two_markers_none_stored_speech_outside_both(self):        # Paket 10: every marker, also offline
        out = self.run_offline("Hallo *lächelt* Mara. *nickt*")
        self.assertEqual([f["text"] for f in self.mine(out, "speech")], ["Hallo Mara."]); self.assertEqual(self.mine(out, "action"), [])
        self.assertEqual([a["segment"] for a in out["turnTruths"][-1]["input_component_ambiguity"] if a["grund"] == "plan_fehlt"], ["lächelt", "nickt"])

    def test_offline_marker_is_no_act_but_typed_speech_stays_the_avatars(self):
        for raw in ("*Johann küsst Mara nicht.*", "*Mara küsst Johann.*"):
            out = self.run_offline(raw)
            self.assertEqual(self.mine(out, "action"), [], raw); self.assertEqual(self.mine(out, "speech"), [], raw)
            self.assertEqual(out["turnTruths"][-1].get("input_event_kind"), "nicht_ausfuehrbar")
        out = self.run_offline("Hallo Mara. *lächelt*")
        self.assertEqual([f["text"] for f in self.mine(out, "speech")], ["Hallo Mara."]); self.assertEqual(self.mine(out, "action"), [])

    # ---- Paket-7-Pruefung A7-01/02: der Avatar-Marker umgeht die Komponentenvalidierung nicht ----
    def _ac(self, seg, akteur, pruefung, geschieht=True, ziel="Mara Nowak"):
        return {"typ": "handlung", "segment": seg, "akteur": akteur, "ziel": ziel, "zeit": "jetzt", "wirkung": "zaertlich", "bezug": None,
                "geschieht": geschieht, "vollzugPruefung": pruefung}

    def test_marker_denied_act_is_no_avatar_action(self):
        out = self.run_input("*Johann küsst Mara nicht.*", [self._ac("Johann küsst Mara nicht.", "Johann Bruckner", {"geschieht": False, "art": "verneint", "beleg": "nicht", "taeter": "figur"})])
        self.assertEqual(self.mine(out, "action"), [])

    def test_marker_foreign_act_is_no_avatar_action(self):
        out = self.run_input("*Mara küsst Johann.*", [self._ac("Mara küsst Johann.", "Mara Nowak", {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "Mara Nowak"}, ziel="Johann Bruckner")])
        self.assertEqual(self.mine(out, "action"), [])

    def test_marker_checked_act_with_own_speech_still_works(self):
        from test_v92_puppet_vertrag import comp as _c
        out = self.run_input("*Johann lächelt.* Hallo Mara.", [self._ac("Johann lächelt", "Johann Bruckner", {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "figur"}), _c("rede", "Hallo Mara.")])
        self.assertEqual([f["text"] for f in self.mine(out, "action")], ["Johann lächelt"]); self.assertEqual([f["text"] for f in self.mine(out, "speech")], ["Hallo Mara."])

    def test_marker_rest_without_speech_component_is_visible_not_spoken(self):      # Paket-8-Pruefung Punkt 2
        out = self.run_input("*Johann lächelt.* Hallo Mara.", [self._ac("Johann lächelt", "Johann Bruckner", {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "figur"})])
        self.assertEqual([f["text"] for f in self.mine(out, "action")], ["Johann lächelt"]); self.assertEqual(self.mine(out, "speech"), [])
        tt = out["turnTruths"][-1]
        self.assertIn("rest_ohne_komponente", [a.get("grund") for a in tt.get("input_component_ambiguity") or []])


def rcomp(seg, einleitung=None, sprecher=None):
    c = comp("rede", seg); c["einleitung"] = einleitung
    if sprecher is not None:
        # V92 Paket 13: the server's blind speaker reading, attached by the route where the announcement names nobody of the cast
        c["sprecherPruefung"] = {"sprecher": sprecher, "beleg": None}
    return c


class SegmentGate(unittest.TestCase):
    """Freigabe 04.11.2026: Segment-Gate ursächlich reparieren, ohne die Satzvollständigkeitsprüfung (SPS A05) zu lockern.
    Planner-Formen wie im Live-Lauf p7 (04.11.2026): handlung + rede mit `einleitung`."""
    setUp = RestredeBinder.setUp
    bind = RestredeBinder.bind
    grunds = RestredeBinder.grunds

    @staticmethod
    def _lit(c, ziel):
        # V92 Paket 13: the server's blind vollzug reading now also names the target LITERALLY ("Mara" in "reicht Mara Wasser");
        # binder-level tests hand the binder what app._check_component_vollzug attaches (see comp() in test_v92_puppet_vertrag)
        c["vollzugPruefung"] = {**c["vollzugPruefung"], "ziel": ziel}; return c

    def test_act_and_quoted_speech_with_announcement(self):                       # Gegenprobe 2: Handlung + Rede
        r = self.bind("Johann reicht Mara Wasser und sagt: „Danke.“", [self._lit(comp("handlung", "Johann reicht Mara Wasser", "ohne_koerperwirkung"), "Mara"), rcomp("Danke.", "sagt:", "Johann")])
        self.assertEqual(len(r["actions"]), 1); self.assertEqual(r["actions"][0]["text"], "Johann reicht Mara Wasser")
        self.assertIn("Danke", r["speech"]); self.assertNotIn("reicht", r["speech"]); self.assertNotIn("sagt", r["speech"])
        # V92 Paket 14 (Paket-13-Pruefung N1, fail-closed): "Mara Wasser" cannot be told from "Mara Schmidt" by the form, and a
        # shorter reading ("Mara") no longer decides - the act and the speech stay, the target stays visibly unbound
        self.assertEqual(self.grunds(r), ["ziel_name_unklar"]); self.assertIsNone(r["actions"][0]["targetId"])

    def test_announcement_with_adverb(self):
        r = self.bind("Johann reicht Mara ein Glas Wasser und sagt leise: Du hast heute genug geschuftet.",
                      [comp("handlung", "Johann reicht Mara ein Glas Wasser", "ohne_koerperwirkung"), rcomp("Du hast heute genug geschuftet.", "sagt leise:", "Johann")])
        self.assertEqual(len(r["actions"]), 1); self.assertTrue(r["speech"].startswith("Du hast heute")); self.assertEqual(self.grunds(r), [])

    def test_reported_thanks_without_words_is_a_second_act_not_speech(self):      # Gegenprobe 1
        r = self.bind("Johann reicht Mara Wasser und bedankt sich.", [self._lit(comp("handlung", "Johann reicht Mara Wasser", "ohne_koerperwirkung"), "Mara"), comp("handlung", "bedankt sich", "ohne_koerperwirkung")])
        self.assertEqual(len(r["actions"]), 2); self.assertIn(r["speech"], (None, ""))
        self.assertEqual(self.grunds(r), ["ziel_name_unklar"])      # V92 Paket 14: see test_act_and_quoted_speech_with_announcement

    def test_p14_noun_after_a_name_stays_unclear_even_with_a_shorter_reading(self):
        # V92 Paket 13 accepted the reading's "Mara" for "Mara Wasser" - and so also for "Mara Schmidt" (Paket-13-Pruefung N1:
        # Mara Nowak got the push). Paket 14: the extent of the name in the text decides, a shorter reading never overrides it.
        for lit in (None, "Mara", "Mara Wasser"):
            c = comp("handlung", "Johann reicht Mara Wasser", "ohne_koerperwirkung")
            r = self.bind("Johann reicht Mara Wasser.", [self._lit(c, lit) if lit else c])
            self.assertEqual([a.get("targetId") for a in r["actions"]], [None], lit)
            self.assertTrue(set(self.grunds(r)) & {"ziel_name_unklar", "ziel_nicht_anwesend_oder_unbekannt"}, lit)
        r = self.bind("Johann reicht Mara ein Glas Wasser.", [self._lit(comp("handlung", "Johann reicht Mara ein Glas Wasser", "ohne_koerperwirkung"), "Mara")])
        self.assertEqual([a.get("targetId") for a in r["actions"]], [self.M["id"]]); self.assertEqual(self.grunds(r), [])
        r = self.bind("Johann schubst Mara Schmidt.", [self._lit(comp("handlung", "Johann schubst Mara Schmidt", "gewalt"), "Mara Schmidt")])
        self.assertEqual([(a.get("targetId"), a.get("effectValid")) for a in r["actions"]], [(None, False)])
        self.assertIn("ziel_nicht_anwesend_oder_unbekannt", self.grunds(r))

    def test_two_separate_acts(self):                                              # Gegenprobe 5
        r = self.bind("Johann reicht Mara Wasser und greift nach dem Glas.", [comp("handlung", "Johann reicht Mara Wasser", "ohne_koerperwirkung"), comp("handlung", "greift nach dem Glas", "ohne_koerperwirkung")])
        self.assertEqual([a["text"] for a in r["actions"]], ["Johann reicht Mara Wasser", "greift nach dem Glas"])

    def test_said_act_stays_speech_and_no_act(self):                               # Gegenprobe 4
        raw = "Johann sagt: „Ich schlage Mara.“"
        r = self.bind(raw, [rcomp("Ich schlage Mara.", "Johann sagt:")])
        # Paket 9: the speech is the spoken words; the announcement "Johann sagt:" is its introduction, not speech
        self.assertEqual(r["actions"], []); self.assertEqual(r["speech"], "Ich schlage Mara."); self.assertEqual(self.grunds(r), [])

    def test_negation_outside_the_act_segment_still_faults(self):                  # A05 bleibt
        r = self.bind("Johann küsst Mara nicht.", [comp("handlung", "Johann küsst Mara", "zaertlich")])
        self.assertEqual(r["actions"], []); self.assertIn("segment_satz_unvollstaendig", self.grunds(r))

    def test_negation_before_the_announcement_still_faults_and_is_not_spoken(self):
        raw = "Johann küsst Mara nicht und sagt: Hallo."
        r = self.bind(raw, [comp("handlung", "Johann küsst Mara", "zaertlich"), rcomp("Hallo.", "sagt:", "Johann")])
        self.assertEqual(r["actions"], []); self.assertIn("segment_satz_unvollstaendig", self.grunds(r))
        self.assertEqual(r["speech"].rstrip("."), "Hallo"); self.assertNotIn("küsst", r["speech"])      # D2: der Handlungstext wird nicht zur Rede

    def test_unproven_act_text_is_never_turned_into_speech(self):                  # D2
        raw = "Johann reicht Mara Wasser und flüstert etwas Hallo."
        r = self.bind(raw, [comp("handlung", "Johann reicht Mara Wasser", "ohne_koerperwirkung"), rcomp("Hallo.")])
        self.assertEqual(r["actions"], []); self.assertEqual(r["speech"].rstrip("."), "Hallo"); self.assertIn("segment_satz_unvollstaendig", self.grunds(r))

    def test_without_valid_speech_a_faulty_act_is_no_speech_for_the_puppet(self):  # SPS A05 bleibt: keine Handlung
        # Gegenpruefung 04.11. (Fall B): the puppet path no longer re-labels a rejected act as the figure's speech.
        r = self.bind("Ich küsse dich nicht.", [comp("handlung", "Ich küsse dich", "zaertlich")])
        self.assertEqual((r["actions"], r["speech"]), ([], "")); self.assertTrue(r.get("nichts_ausfuehrbar"))
        self.assertIn("segment_satz_unvollstaendig", self.grunds(r))

    def test_avatar_binder_still_keeps_the_faulty_act_out_of_the_actions(self):  # SPS A05 am Avatar-Binder
        r = kernel.bind_input_components("Ich küsse dich nicht.", [comp("handlung", "Ich küsse dich", "zaertlich")], actor_id="a", actor_names=["Alrik"],
                                         figures=[], present_ids=[], default_target=None, text_tense=None)
        self.assertEqual(r["actions"], []); self.assertEqual(r["ambiguous"][0]["grund"], "segment_satz_unvollstaendig")

    def test_announcement_must_stand_directly_before_the_speech(self):
        raw = "Johann reicht Mara Wasser und sagt leise, dass er müde ist: Danke."
        r = self.bind(raw, [comp("handlung", "Johann reicht Mara Wasser", "ohne_koerperwirkung"), rcomp("Danke.", "sagt leise")])
        self.assertEqual(r["actions"], []); self.assertIn("segment_satz_unvollstaendig", self.grunds(r))

    def test_announcement_not_in_the_input_is_no_announcement(self):
        r = self.bind("Johann reicht Mara Wasser und sagt: Danke.", [comp("handlung", "Johann reicht Mara Wasser", "ohne_koerperwirkung"), rcomp("Danke.", "erklärt dazu:")])
        self.assertEqual(r["actions"], [])

    def test_incomplete_decomposition_uses_the_existing_error_path(self):          # Gegenprobe 6
        for pl in (plan("action", "act", []), plan("action", "act", [{"typ": "handlung"}])):
            r = kernel.bind_puppet_input("Johann reicht Mara Wasser und sagt: Danke.", pl, self.J, [self.J, self.M], [self.J["id"], self.M["id"]], addressee_id=self.M["id"])
            self.assertTrue(r.get("incomplete") or (r["actions"] == [] and r["ambiguous"]), r)
            self.assertNotIn("reicht", r["speech"] or "")

    def test_avatar_path_uses_the_same_binder(self):
        out = kernel.bind_input_components("Johann reicht Mara Wasser und sagt: „Danke.“",
                                           [self._lit(comp("handlung", "Johann reicht Mara Wasser", "ohne_koerperwirkung"), "Mara"), rcomp("Danke.", "sagt:", "Johann")],
                                           actor_id=self.J["id"], actor_names=["Johann Bruckner"], figures=[self.J, self.M], present_ids=[self.J["id"], self.M["id"]],
                                           default_target=None, text_tense=None, addressee_id=self.M["id"])
        self.assertEqual(len(out["actions"]), 1); self.assertIn("Danke", out["speech"])
