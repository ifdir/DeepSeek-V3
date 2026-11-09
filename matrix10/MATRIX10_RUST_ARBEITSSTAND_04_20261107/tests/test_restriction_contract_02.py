#!/usr/bin/env python3
"""AMASTER 34.1/34.3/36.5 independent counterprobes; real V67 SQLite writers and readers.
Usage: python -B test_restriction_contract_02.py PRODUCT_ROOT
No monkeypatched writers/reducers and no production database.
"""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

if len(sys.argv) < 2:
    raise SystemExit('usage: test_restriction_contract_02.py /path/to/unpacked/MATRIX10')
ROOT = Path(sys.argv.pop(1)).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parent))
from original_boundary_harness import load_reference, create_fixture  # noqa: E402
repo, db = load_reference(ROOT)
from matrix_api import scene_state as sc  # noqa: E402


def state(cases, *, act=None):
    """Write canonical lifecycle evidence and reopen SQLite before reducing."""
    with tempfile.TemporaryDirectory(prefix='m10_restriction_chain_') as d:
        name=Path(d)/'case.sqlite'
        conn=create_fixture(name, db)
        prop={'id':'prop_touch','kind':'koerperkontakt','actorId':'alice','targetId':'bob','state':'open'}
        repo.create_session_proposition(conn,'session_A',prop,'usr_A')
        for index, (kind, scope, part, by) in enumerate(cases, 1):
            tt={'id':f'tt_{index}','role':'avatar','authority':'avatar','speaker_id':'bob',
                'present_ids':['alice','bob'],'hears_ids':['alice'],'sees_ids':['alice'],'turn':index}
            repo.append_session_turn_truth(conn,'session_A',tt,'usr_A')
            fact={'id':f'fact_{index}','kind':'lifecycle','event_kind':kind,'actorId':by,'targetId':'alice',
                  'sourceTurnId':f'tt_{index}','propositionId':'prop_touch','validated':True,'turn':index,
                  'payload':{'koerperkontakt':{'scope':scope,'einschraenkung':part,'beleg':part or ''}}}
            repo.append_session_fact(conn,'session_A',fact,'usr_A')
        conn.commit();conn.close()
        with sqlite3.connect(name) as conn:
            conn.row_factory=sqlite3.Row
            s=repo.get_session(conn,'usr_A','session_A')
            p=next(p for p in s['propositions'] if p['id']=='prop_touch')
            rs=sc.restricted_refusals_standing(s,p)
            ps=sc.restricted_permissions_standing(s,p)
            broad=sc.body_contact_standing(s,p)
            mirrored=sc.body_contact_state(s,p)
            audit=repo.write_boundary_audit(conn,'session_A')
            other=repo.get_session(conn,'usr_B','session_B')
            return {'refusals':[x['einschraenkung'] for x in rs],
                    'permissions':[x['einschraenkung'] for x in ps],
                    'exceptions':[(e['einschraenkung'],e['kind']) for e in (broad or {}).get('ausnahmen') or []],
                    'broad':(broad or {}).get('state'),
                    'mirrored':mirrored,
                    'facts':len(s.get('facts') or []), 'audit':audit['codes'],
                    'otherFacts':len(other.get('facts') or [])}

class ContractRegression(unittest.TestCase):
    def test_explicit_qualifier_is_part_of_the_identity(self):
        self.assertFalse(sc.same_restriction('rechte Hand', 'linke Hand'))
        self.assertFalse(sc.same_restriction('linke Hand', 'rechte Hand'))
        self.assertFalse(sc.same_restriction('die rechte Hand', 'die linke Hand'))
        self.assertFalse(sc.same_restriction('Hand', 'linke Hand'))

    def test_variants_of_exact_same_part_match(self):
        for a,b in [('rechte Hand','meine rechte Hand'),('die rechte Hand','deine rechte Hand'),
                    ('meiner rechten Hand','mit deiner rechten Hand'),('meine linke Hand','die linke Hand'),
                    ('die Schulter','meine Schulter'),('meine Hand','deine Hand')]:
            with self.subTest(a=a,b=b):
                self.assertTrue(sc.same_restriction(a,b))
                self.assertTrue(sc.same_restriction(b,a))

    def test_no_compounds_or_different_parts(self):
        self.assertFalse(sc.same_restriction('Schulter', 'Schultertasche'))
        self.assertFalse(sc.same_restriction('meine Hand', 'Handtasche'))
        self.assertFalse(sc.same_restriction('die Schulter', 'die Hand'))

    def test_qualifier_is_not_ignored_by_named_part_reader(self):
        self.assertFalse(sc.names_restriction('Ich halte deine linke Hand', 'rechte Hand', exact=True))
        self.assertFalse(sc.names_restriction('deine linke Hand', 'rechte Hand', word=True))
        self.assertTrue(sc.names_restriction('deine rechte Hand','rechte Hand', exact=True))
        self.assertTrue(sc.names_restriction('deine Hand','rechte Hand', word=True))  # ambiguous; no invented alternative
        self.assertFalse(sc.names_restriction('deine Hand','rechte Hand', exact=True))

    def test_qualifier_cannot_migrate_from_another_component(self):
        line = 'Ich halte deine rechte Hand und beruehre deinen linken Arm'
        self.assertFalse(sc.names_restriction(line, 'meine linke Hand', exact=True))
        self.assertFalse(sc.names_restriction(line, 'meine linke Hand', word=True))
        self.assertTrue(sc.names_restriction(line, 'meine rechte Hand', exact=True))
        line2 = 'Ich halte deine linke Hand und beruehre deine rechte Schulter'
        self.assertFalse(sc.names_restriction(line2, 'meine rechte Hand', exact=True))
        self.assertFalse(sc.names_restriction(line2, 'meine rechte Hand', word=True))
        self.assertTrue(sc.names_restriction(line2, 'meine linke Hand', exact=True))

    def test_sqlite_refusal_right_then_acceptance_left_does_not_revoke_right(self):
        p=state([('refusal','eingeschraenkt','rechte Hand','bob'),
                 ('acceptance','eingeschraenkt','linke Hand','bob')])
        self.assertEqual(p['refusals'],['rechte Hand'])
        self.assertEqual(p['permissions'],['linke Hand'])
        self.assertEqual([x['einschraenkung'] for x in p['mirrored'].get('eingeschraenkt') or []],['rechte Hand'])
        self.assertEqual(p['facts'],2)
        self.assertEqual(p['otherFacts'],0)
        self.assertEqual(p['audit'],{})

    def test_sqlite_refusal_right_then_acceptance_right_ends_exactly_right(self):
        p=state([('refusal','eingeschraenkt','rechte Hand','bob'),
                 ('acceptance','eingeschraenkt','meine rechte Hand','bob')])
        self.assertEqual(p['refusals'],[])
        self.assertEqual(p['permissions'],['meine rechte Hand'])
        self.assertEqual(p['facts'],2)  # historical facts retained

    def test_sqlite_refusals_right_and_left_coexist(self):
        p=state([('refusal','eingeschraenkt','rechte Hand','bob'),
                 ('refusal','eingeschraenkt','linke Hand','bob')])
        self.assertCountEqual(p['refusals'],['rechte Hand','linke Hand'])
        self.assertEqual(p['facts'],2)

    def test_sqlite_revoke_other_side_does_not_erase_refusal(self):
        p=state([('refusal','eingeschraenkt','rechte Hand','bob'),
                 ('revoke','eingeschraenkt','linke Hand','bob')])
        self.assertEqual(p['refusals'],['rechte Hand'])

    def test_sqlite_other_speaker_cannot_revoke_boundary(self):
        p=state([('refusal','eingeschraenkt','rechte Hand','bob'),
                 ('acceptance','eingeschraenkt','rechte Hand','alice')])
        self.assertEqual(p['refusals'],['rechte Hand'])

    def test_sqlite_broad_refusal_with_left_exception_still_declines_rest(self):
        p=state([('refusal','jede_beruehrung',None,'bob'),
                 ('acceptance','eingeschraenkt','linke Hand','bob')])
        self.assertEqual(p['broad'],'declined')
        self.assertEqual(p['exceptions'],[('linke Hand','acceptance')])
        self.assertEqual(p['facts'],2)

    def test_sqlite_broad_refusal_with_two_distinct_exceptions(self):
        p=state([('refusal','jede_beruehrung',None,'bob'),
                 ('acceptance','eingeschraenkt','rechte Hand','bob'),
                 ('acceptance','eingeschraenkt','linke Hand','bob')])
        self.assertEqual(p['broad'],'declined')
        self.assertCountEqual(p['exceptions'],[('rechte Hand','acceptance'),('linke Hand','acceptance')])

    def test_sqlite_broad_refusal_same_exception_is_updated_not_duplicated(self):
        p=state([('refusal','jede_beruehrung',None,'bob'),
                 ('acceptance','eingeschraenkt','rechte Hand','bob'),
                 ('revoke','eingeschraenkt','die rechte Hand','bob')])
        self.assertEqual(p['broad'],'declined')
        self.assertEqual(p['exceptions'],[('die rechte Hand','revoke')])

    def test_sqlite_refusal_narrow_not_erased_by_narrow_permission_other_side(self):
        p=state([('refusal','eingeschraenkt','die rechte Hand','bob'),
                 ('acceptance','eingeschraenkt','meine linke Hand','bob')])
        self.assertEqual(p['refusals'],['die rechte Hand'])
        self.assertEqual(p['permissions'],['meine linke Hand'])

    def test_sqlite_global_acceptance_has_existing_explicit_scope_semantics(self):
        p=state([('refusal','eingeschraenkt','rechte Hand','bob'),
                 ('acceptance','jede_beruehrung',None,'bob')])
        self.assertEqual(p['refusals'],[])
        self.assertEqual(p['broad'],'accepted')

if __name__=='__main__':
    unittest.main(verbosity=2)
