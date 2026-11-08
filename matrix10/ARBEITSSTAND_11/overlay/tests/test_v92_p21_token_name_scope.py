"""P21 independent regression contract: source-word semantics; existing positive and negative paths.

No live provider and no user DB. Includes P20 actual-provider response fixtures
and their expected limitations, exact source offsets, presence and SQLite reader.
"""
import unittest
from unittest.mock import patch
import test_v84_kausal_chain   # Flask-free test fixture import
from matrix_api import kernel, llm_contract


class WordBoundaries(unittest.TestCase):
    def setUp(self):
        self.m = {"id":"m1","name":"Mara Nowak"}
        self.ms = {"id":"m2","name":"Mara Schmidt"}
        self.j = {"id":"j1","name":"Johann Bruckner"}
        self.n = [self.m,self.j]
        self.both = [self.m,self.ms,self.j]
        self.absent = {"scene":{"presentIds":["m1","j1"]},"avatarId":"j1"}
        self.present = {"scene":{"presentIds":["m1","m2","j1"]},"avatarId":"j1"}

    def projection(self, raw, classes, *, role="nennung", cast=None, extra=None):
        cast = cast or self.n
        spots = kernel.name_boundary_candidates(raw,cast)
        self.assertTrue(spots,raw)
        rec = {**spots[0],"wortklassen":classes,"rolle":role,"status":"eindeutig",**(extra or {})}
        return kernel.with_name_boundary_reading(raw,cast,{"grenzen":[rec]})

    def occ(self, raw, cast):
        return [(x["words"],x["state"],x["ids"]) for x in kernel.name_occurrences(raw,cast)]

    def test_realistic_model_full_name_ignored_when_exact_tokens_supplied(self):
        for text,classes,name,role in (
            ("Hallo Mara, wie geht es dir?",["gruss","name"],"mara","anrede"),
            ("Guten Morgen Mara.",["gruss","gruss","name"],"mara","anrede"),
            ("Frau Nowak, komm her.",["titel","name"],"nowak","anrede"),
            ("Johann reicht Mara Wasser.",["name","anderes"],"mara","nennung"),
            ("Johann gibt Mara Nowak Brot.",["name","name","anderes"],"mara nowak","nennung"),
            ("Johann zeigt Mara Nowak Fotos.",["name","name","anderes"],"mara nowak","nennung"),
        ):
            with self.subTest(text=text):
                # P20 real model supplied the *catalog* name, not the written
                # name; this is now optional metadata, not the source of truth.
                cast=self.projection(text,classes,role=role,extra={"name":"Mara Nowak","beleg":text})
                self.assertIn((name,"ok",{"m1"}),self.occ(text,cast))
                if role=="anrede":
                    target=kernel.resolve_target_detail(self.absent,cast,text,ui_target_id="j1",input_actor_id="j1")
                    self.assertEqual(target["target_id"],"m1",target)

    def test_absent_namesake_cannot_force_clarification_on_address(self):
        text="Hallo Mara, wie geht es dir?"
        cast=self.projection(text,["gruss","name"],cast=self.both,role="anrede")
        self.assertEqual(kernel.resolve_target_detail(self.absent,cast,text,ui_target_id="m2",input_actor_id="j1")["target_id"],"m1")
        ambiguous=kernel.resolve_target_detail(self.present,cast,text,ui_target_id="m1",input_actor_id="j1")
        self.assertIsNone(ambiguous["target_id"])
        self.assertTrue(ambiguous["ambiguous"])
        self.assertEqual(set(ambiguous["candidates"]),{"m1","m2"})

    def test_an_absent_full_name_cannot_fall_back_to_present_first_name(self):
        text="Mara Schmidt, komm her."
        # A known full name is already proven by source; the referent is absent.
        target=kernel.resolve_target_detail(self.absent,self.both,text,ui_target_id="m1",input_actor_id="j1")
        self.assertNotEqual(target["target_id"],"m1",target)

    def test_unknown_extended_full_name_stays_unbound(self):
        text="Johann schubst Anna Mara Nowak."
        cast=self.projection(text,["name","name","name"],cast=self.both)
        self.assertNotIn(("mara nowak","ok",{"m1"}),self.occ(text,cast))
        self.assertTrue(any(st=="unklar" for _,st,_ in self.occ(text,cast)))
        # If the model gets the source NAME tokens wrong in an unsafe way,
        # that remains an open double-reader failure mode, NOT a test success.

    def test_invalid_or_forged_token_readings_are_rejected(self):
        raw="Johann reicht Mara Wasser."
        failures=[
            {"wortklassen":["name"]},
            {"wortklassen":["name","unknown"]},
            {"wortklassen":["unklar","name"]},
            {"wortklassen":["gruss","name"],"rolle":"nennung"},
            {"wortklassen":["name","anderes"],"name":"Johann Bruckner"},
            {"wortklassen":["name","anderes"],"beleg":"I made it up"},
            {"wortklassen":["name","anderes"],"a":0},
            {"wortklassen":["name","anderes"],"wortfolge":"Mara Schmidt"},
        ]
        for extra in failures:
            with self.subTest(extra=extra):
                cast=self.projection(raw,extra.pop("wortklassen"),extra=extra)
                self.assertTrue(any(s=="unklar" for _,s,_ in self.occ(raw,cast)),self.occ(raw,cast))

    def test_noncontiguous_name_tokens_are_rejected(self):
        raw="Guten Morgen Mara."
        cast=self.projection(raw,["name","anderes","name"],role="anrede")
        self.assertTrue(any(s=="unklar" for _,s,_ in self.occ(raw,cast)))

    def test_signed_answer_cannot_be_undone_by_semantic_reading(self):
        text="Hallo Mara, wie geht es dir?"
        cast=self.projection(text,["gruss","name"],cast=self.both,role="anrede")
        answered=kernel.with_klaerungen(cast,[{"text":"Hallo Mara","a":0,"b":10,"id":"m2"}],text)
        target=kernel.resolve_target_detail(self.present,answered,text,"m1",input_actor_id="j1")
        self.assertEqual(target["target_id"],"m2",target)

    def test_single_model_read_to_canonical_target_no_catalog_name_copy(self):
        # Stand 11 (nur Aufrufstruktur): dieselbe Lesung kommt aus der ersten Antwort (Lesung "namen" an der Wortfolge), kein Aufruf
        raw="Hallo Mara, wie geht es dir?"
        llm_contract.vorab_leeren()
        llm_contract.vorab_registrieren([{"lesung":"namen","zu":"Hallo Mara","antwort":{"wortklassen":["gruss","name"],
                                         "name":"Mara Nowak","beleg":raw,"rolle":"anrede","status":"eindeutig"}}])
        with patch.object(llm_contract,"_routing",return_value={"allowed":True}), \
             patch.object(llm_contract,"_llm_json",side_effect=AssertionError("kein eigener Aufruf")) as read:
            result=llm_contract.name_boundary_check(None,"admin",raw,figures=self.n)
        self.assertEqual(read.call_count,0)
        projected=kernel.with_name_boundary_reading(raw,self.n,result)
        target=kernel.resolve_target_detail(self.absent,projected,raw,ui_target_id="j1",input_actor_id="j1")
        self.assertEqual((target["target_id"],target["reason"]),("m1","semantic_explicit_address"))

    def test_true_provider_schema_contains_source_bound_word_offsets(self):
        # Stand 11: die Wortpositionen setzt der SERVER aus seinen Kandidaten - auch wenn die erste Antwort andere a/b nennt
        text="Hallo Mara, wie geht es dir?"
        llm_contract.vorab_leeren()
        llm_contract.vorab_registrieren([{"lesung":"namen","zu":"Hallo Mara","antwort":{"a":3,"b":99,"wortfolge":"Mara",
                                         "wortklassen":["gruss","name"],"rolle":"anrede","status":"eindeutig"}}])
        with patch.object(llm_contract,"_routing",return_value={"allowed":True}):
            res=llm_contract.name_boundary_check(None,"admin",text,figures=self.n)
        self.assertEqual([(g["a"],g["b"],g["wortfolge"]) for g in res["grenzen"]],[(0,10,"Hallo Mara")])
        self.assertIn("wortklassen",llm_contract.PLAN_LESUNGEN_RULES); self.assertIn("[namen]",llm_contract.PLAN_LESUNGEN_RULES)
        self.assertIn("[namen]",llm_contract.GOD_NAMEN_LESUNGEN_RULES)

    def test_original_p20_real_model_response_is_not_mistaken_for_source_proof(self):
        raw="Hallo Mara, wie geht es dir?"
        spot=kernel.name_boundary_candidates(raw,self.n)[0]
        old={**spot,"name":"Mara Nowak","beleg":raw,"rolle":"anrede","status":"eindeutig"}
        cast=kernel.with_name_boundary_reading(raw,self.n,{"grenzen":[old]})
        self.assertTrue(any(s=="unklar" for _,s,_ in self.occ(raw,cast)))
        # This fixture proves the OLD response is insufficient; it does not
        # claim a genuine provider has successfully answered the NEW schema.

    def test_binder_writer_sqlite_brain_reader_positive_and_negative(self):
        import json
        import tempfile
        from contextlib import closing
        from pathlib import Path
        import test_v92_p17_klaerung as T
        from matrix_api.db import connect, init_schema, GASTHAUS_ID
        from matrix_api.seed_builtin import seed_if_missing
        from matrix_api.repos import create_session, save_session, get_session
        for raw, classes, suggested, expect in (
            ("Johann reicht Mara Wasser.",["name","anderes"],"Mara",True),
            ("Johann gibt Mara Nowak Brot.",["name","name","anderes"],"Mara Nowak",True),
            ("Johann schubst Anna Mara Nowak.",["anderes","name","name"],"Mara Nowak",False),
        ):
            with self.subTest(raw=raw):
                harness=T.P17Kernel();harness.setUp()
                fixture=harness.f
                rec=kernel.name_boundary_candidates(raw,fixture.chars)[0]
                projected=kernel.with_name_boundary_reading(raw,fixture.chars,{
                    "grenzen":[{**rec,"wortklassen":classes,"rolle":"nennung","status":"eindeutig"}]})
                component=harness.act(raw[:-1],suggested,"ohne_koerperwirkung")
                present=[pid for pid in fixture.present if pid!=T.S]
                bound=kernel.bind_puppet_input(raw,{"komponenten":[component]},fixture.J,projected,present,
                                               addressee_id=fixture.M["id"])
                valid_actions=[a for a in bound["actions"] if not a.get("targetBindingInvalid")]
                self.assertEqual(len(valid_actions),int(expect),(raw,bound))
                saved=fixture.commit(bound)
                actions=[f for f in saved["facts"] if f.get("kind")=="action" and f.get("validated")]
                self.assertEqual(len(actions),int(expect),actions)
                if expect:
                    self.assertEqual(actions[0].get("targetId"),fixture.M["id"])
                with tempfile.TemporaryDirectory(prefix="p21_kernel_") as tmp:
                    fp=Path(tmp)/"test.sqlite"
                    with closing(connect(fp)) as c:
                        init_schema(c);seed_if_missing(c)
                        # The P17 fixture contains an extra Mara Schmidt; the
                        # isolated DB must contain her referenced figure ID.
                        origin=c.execute("select world_id,owner_user_id,json from characters where id=?",(fixture.M["id"],)).fetchone()
                        clone=json.loads(origin[2]);clone.update({"id":T.S,"name":"Mara Schmidt","aliases":[]})
                        c.execute("insert into characters(id,world_id,owner_user_id,json) values(?,?,?,?)",
                                  (T.S,origin[0],origin[1],json.dumps(clone,ensure_ascii=False)))
                        create_session(c,{"id":saved["id"],"worldId":GASTHAUS_ID,"name":"P21 test",
                                          "presentIds":present},"admin")
                        save_session(c,"admin",saved);c.commit()
                    with closing(connect(fp)) as c:
                        after=get_session(c,"admin",saved["id"])
                        self.assertEqual(c.execute("pragma quick_check").fetchone()[0],"ok")
                    got=[f for f in after["facts"] if f.get("kind")=="action" and f.get("validated")]
                    self.assertEqual(len(got),int(expect))
                    if expect:
                        self.assertEqual(got[0].get("targetId"),fixture.M["id"])
                    # No fabricated action may enter the next figure prompt.
                    context=kernel.brain_context(after,fixture.M["id"])
                    if not expect:
                        self.assertFalse(got)
                    self.assertIsInstance(context,dict)

    def test_semantic_preposition_can_precede_real_name_without_a_wordlist(self):
        text="Neben Mara Nowak sitzt Johann."
        cast=self.projection(text,["praeposition","name","name"])
        self.assertIn(("mara nowak","ok",{"m1"}),self.occ(text,cast))

    def test_double_shortened_unknown_name_cannot_use_other_label(self):
        # Both planner and semantic reader propose 'Mara Nowak' for the
        # unknown extended written name.  'anderes' as a capitalized prefix
        # is insufficient evidence to erase 'Anna'.
        text="Johann schubst Anna Mara Nowak."
        cast=self.projection(text,["anderes","name","name"])
        self.assertTrue(any(st=="unklar" for _,st,_ in self.occ(text,cast)))

if __name__ == "__main__":
    unittest.main()
