"""P20 regressions: semantic name EXTENT, person-ID priority, God auto scope.

All model readings are synthetic and must be validated by the real server-side
kernel. No live provider, user SQLite, browser, or customer data is used.
"""
import unittest
from unittest.mock import patch

import test_v84_kausal_chain  # noqa - existing offline Flask fallback
from matrix_api import kernel, llm_contract
from test_v92_p19_koerper import MARA, JOHANN, NATIVES, mara_state, bestaetigt


class SemanticNameBoundary(unittest.TestCase):
    def setUp(self):
        self.m = {"id": "mara1", "name": "Mara Nowak"}
        self.ms = {"id": "mara2", "name": "Mara Schmidt"}
        self.j = {"id": "johann", "name": "Johann Bruckner"}
        self.s = {"scene": {"presentIds": ["mara1", "mara2", "johann"]}, "avatarId": "johann"}

    def semantic(self, text, cast, name, *, role="nennung", override=None):
        candidates = kernel.name_boundary_candidates(text, cast)
        self.assertTrue(candidates, (text, cast))
        # P22 contract migration (explicit): the P20 free-name response was
        # removed because two truncating readings could turn "Anna Mara Nowak"
        # into a body effect on Mara. Preserve ALL positive assertions below,
        # but feed the CURRENT P21/P22 response schema, bound to source words.
        words = candidates[0]["wortfolge"].casefold()
        classes_by_source = {
            "hallo mara": ["gruss", "name"],
            "guten morgen mara": ["gruss", "gruss", "name"],
            "frau nowak": ["titel", "name"],
            "mara wasser": ["name", "anderes"],
            "mara nowak brot": ["name", "name", "anderes"],
            "mara nowak fotos": ["name", "name", "anderes"],
        }
        self.assertIn(words, classes_by_source, (text, candidates))
        proposal = {**candidates[0], "wortklassen": classes_by_source[words],
                    "status": "eindeutig", "rolle": role}
        if override:
            proposal.update(override)
        return kernel.with_name_boundary_reading(text, cast, {"grenzen": [proposal]})

    def test_existing_positive_greetings_use_reading_not_ui_focus(self):
        for text in ("Hallo Mara, wie geht es dir?", "Guten Morgen Mara."):
            with self.subTest(text=text):
                cast = self.semantic(text, [self.m, self.j], "Mara", role="anrede")
                out = kernel.resolve_target_detail(self.s, cast, text, ui_target_id="johann", input_actor_id="johann")
                self.assertEqual(out["target_id"], "mara1", out)
                self.assertFalse(out["ambiguous"])
                self.assertEqual([(r["state"], r["ids"]) for r in kernel.name_occurrences(text,cast)],
                                 [("ok", {"mara1"})])
        text = "Frau Nowak, komm her."
        cast = self.semantic(text, [self.m, self.j], "Nowak", role="anrede")
        self.assertEqual(kernel.resolve_target_detail(self.s, cast, text, input_actor_id="johann")["target_id"],"mara1")

    def test_right_object_not_falsely_absorbed_into_name(self):
        tests = (("Johann reicht Mara Wasser.", "Mara"),
                 ("Johann gibt Mara Nowak Brot.", "Mara Nowak"),
                 ("Johann zeigt Mara Nowak Fotos.", "Mara Nowak"))
        for text, who in tests:
            with self.subTest(text=text):
                cast = self.semantic(text, [self.m,self.j], who)
                occ = kernel.name_occurrences(text, cast)
                self.assertIn("mara1", [next(iter(o["ids"])) for o in occ if o["state"]=="ok" and len(o["ids"])==1])
                self.assertFalse(any(o["state"] == "unklar" for o in occ),occ)
                self.assertFalse(any(o["words"] in ("mara wasser", "mara nowak brot", "mara nowak fotos") for o in occ),occ)

    def test_no_provider_reading_does_not_guess(self):
        for text in ("Hallo Mara, wie geht es dir?", "Johann reicht Mara Wasser."):
            occ = kernel.name_occurrences(text,[self.m,self.j])
            self.assertTrue(any(o["state"] == "unklar" for o in occ),occ)

    def test_duplicate_id_stays_unbound_without_operator_answer(self):
        text = "Hallo Mara, wie geht es dir?"
        cast = self.semantic(text,[self.m,self.ms,self.j],"Mara",role="anrede",
                             override={"figurId":"mara1"})
        out = kernel.resolve_target_detail(self.s,cast,text,"mara1",input_actor_id="johann")
        self.assertIsNone(out["target_id"],out)
        self.assertTrue(out["ambiguous"])
        self.assertEqual(set(out["candidates"]),{"mara1","mara2"})

    def test_signed_operator_answer_outranks_semantic_reader_and_ui(self):
        text = "Hallo Mara, wie geht es dir?"
        cast = self.semantic(text,[self.m,self.ms,self.j],"Mara",role="anrede")
        answered = kernel.with_klaerungen(cast,[{"text":"Hallo Mara","a":0,"b":10,"id":"mara2"}],text)
        out = kernel.resolve_target_detail(self.s,answered,text,"mara1",input_actor_id="johann")
        self.assertEqual(out["target_id"],"mara2",out)
        self.assertTrue(any(o.get("geklaert") and o["ids"]=={"mara2"} for o in kernel.name_occurrences(text,answered)))

    def test_wrong_or_forged_model_span_cannot_bind(self):
        text = "Johann schubst Anna Mara Nowak."
        cast = [self.m,self.j]
        candidate = kernel.name_boundary_candidates(text,cast)
        self.assertTrue(candidate)
        forged = kernel.with_name_boundary_reading(text,cast,{"grenzen":[
            {**candidate[0],"name":"Mara Nowak","beleg":"not in input","status":"eindeutig"}]})
        self.assertTrue(any(o["state"]=="unklar" for o in kernel.name_occurrences(text,forged)))
        whole = kernel.with_name_boundary_reading(text,cast,{"grenzen":[
            {**candidate[0],"name":"Anna Mara Nowak","beleg":candidate[0]["wortfolge"],"status":"eindeutig"}]})
        self.assertTrue(any(o["state"]=="unklar" for o in kernel.name_occurrences(text,whole)))

    def test_semantic_request_one_bounded_call_only_when_needed(self):
        # Stand 11 (SPS V62.7; nur die Aufrufstruktur angepasst): die Namenslesung kommt aus der ERSTEN Antwort (Planer bzw.
        # God-Zerlegung, Lesung "namen") - nie ein eigener Aufruf; gelesen wird nur, wo eine Grenze wirklich unsicher ist.
        llm_contract.vorab_leeren()
        with patch.object(llm_contract,"_routing",return_value={"allowed":True}), \
             patch.object(llm_contract,"_llm_json",return_value={"grenzen":[]}) as call:
            self.assertEqual(llm_contract.name_boundary_check(None,"admin","Mara Nowak, komm her!",figures=[self.m,self.j]),
                             {"grenzen":[]})
            self.assertEqual(llm_contract.vorab_abrufe(),[], "sichere Namen: keine Lesung")
            self.assertIsNone(llm_contract.name_boundary_check(None,"admin","Hallo Mara!",figures=[self.m,self.j]))
            self.assertEqual([(a["lesung"],a["payload"]["wortfolge"],a["aus_erster_antwort"]) for a in llm_contract.vorab_abrufe()],
                             [("namen","Hallo Mara",False)], "genau die unsichere Stelle")
            call.assert_not_called()


class GodAutoSemanticScope(unittest.TestCase):
    def test_unread_body_fact_is_never_false_applied(self):
        text = "Mara ist bewusstlos."
        for reading in (None, {}, {"bereich":"unklar"}, {"bereich":"koerper"}):
            with self.subTest(reading=reading):
                scope=kernel.god_auto_state_scope(reading)
                self.assertEqual(scope,"body")
                s=mara_state()
                result=kernel.apply_god(s,text,scope,MARA["id"],natives=NATIVES,
                                        body_state=reading)
                self.assertFalse(result["godFacts"][-1]["applied"])
                self.assertEqual(result["runtimes"][MARA["id"]]["consciousness"],1.0)
                self.assertFalse(any(f.get("kind")=="body_state" for f in result["facts"]))

    def test_real_confirmed_body_fact_keeps_existing_writer(self):
        text = "Mara ist bewusstlos."
        read = bestaetigt({"bewusstsein":"bewusstlos","beleg":"ist bewusstlos"},text,
                          authority="god", figur_id=MARA["id"])
        read["bereich"]="koerper"
        scope=kernel.god_auto_state_scope(read)
        self.assertEqual(scope,"body")
        result=kernel.apply_god(mara_state(),text,scope,MARA["id"],natives=NATIVES,body_state=read)
        self.assertTrue(result["godFacts"][-1]["applied"])
        self.assertEqual(result["runtimes"][MARA["id"]]["consciousness"],.2)
        self.assertTrue([f for f in result["facts"] if f.get("kind")=="body_state"])

    def test_explicit_nonbody_character_state_remains_possible(self):
        scope=kernel.god_auto_state_scope({"bereich":"nicht_koerper"})
        self.assertEqual(scope,"character")
        text="Mara weiß jetzt, dass Johann traurig ist."
        result=kernel.apply_god(mara_state(),text,scope,MARA["id"],natives=NATIVES)
        self.assertTrue(result["godFacts"][-1]["applied"])
        self.assertTrue([m for m in result["memories"] if m.get("characterId")==MARA["id"]])

    def test_body_fields_override_wrong_nonbody_classification(self):
        scope=kernel.god_auto_state_scope({"bereich":"nicht_koerper","schmerz":"leicht"})
        self.assertEqual(scope,"body")

    def test_unbound_target_has_correct_visible_error(self):
        errors = ("ziel_nicht_anwesend_oder_unbekannt", "wirkung_ohne_gebundenes_ziel", "koerperwirkung_ohne_zielperson")
        for reason in errors:
            with self.subTest(reason=reason):
                msg=kernel.act_rejection_text(reason)
                self.assertIn("nicht",msg)
                self.assertTrue("Zielperson" in msg or "Zielperson" in msg.capitalize())
                self.assertNotIn("nicht eindeutig als Handlung gelesen",msg)

if __name__=="__main__":
    unittest.main()
