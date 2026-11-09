"""Python adapter and SceneState projection tests ONLY.

A mocked `_native_request` establishes transport shape but NEVER counts as
executed Rust or a product pass. Every test includes a label in the build
report identifying what it does and does not establish.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'integration'

# Load the candidate reader with only the original pure package dependencies.
# No application server or fake SQLite writer is installed.
package = types.ModuleType('matrix_api')
package.__path__ = [str(SRC)]
sys.modules.setdefault('matrix_api', package)

def load(name, filepath):
    spec = importlib.util.spec_from_file_location('matrix_api.'+name, filepath)
    module = importlib.util.module_from_spec(spec)
    sys.modules['matrix_api.'+name] = module
    spec.loader.exec_module(module)
    return module

# the actual original ids.py is provided by the reference product on the
# source-stage's parent path; this test runs without touching its database.
ref = Path(os.environ.get('MATRIX10_V67_ROOT', ''))
if not os.environ.get('MATRIX10_V67_ROOT') or not (ref/'matrix_api'/'ids.py').is_file():
    raise unittest.SkipTest('MATRIX10_V67_ROOT must point to an unpacked reference or freshly staged source')
package.__path__.append(str(ref/'matrix_api'))
bridge = load('native_boundary', SRC/'native_boundary.py')
sc = load('scene_state', SRC/'scene_state.py')


def event(i, by, kind, scope, part=None, window=None, open_part=None):
    kk={'scope':scope,'einschraenkung':part,'window':window,'beleg':'test-evidence'}
    if open_part is not None:
        kk['einschraenkung']=open_part
        kk['scope']='diese_tat'
    return {'id':f'f{i}','kind':'lifecycle','event_kind':kind,'actorId':by,
            'propositionId':'prop','validated':True,'turn':i,'text':f'event {i}',
            'payload':{'koerperkontakt':kk}}

def scene(*facts):
    prop={'id':'prop','kind':'koerperkontakt','actorId':'alice','targetId':'bob'}
    return {'facts':list(facts),'propositions':[prop],'time':{},'sceneState':{}},prop

class ConsentBoundaryProjectionTests(unittest.TestCase):
    def test_broad_wrong_actor_reaches_rust_as_wrong_actor(self):
        s,p=scene(event(1,'bob','refusal','jede_beruehrung'),
                  event(2,'alice','acceptance','jede_beruehrung'))
        with patch.object(bridge,'_native_request',return_value={'standing':0,'ended':None,'exceptions':[]}) as call:
            result=sc.body_contact_standing(s,p)
        self.assertEqual(result['state'],'declined')
        self.assertEqual(result['causeFactId'],'f1')
        operation,context,payload=call.call_args.args
        self.assertEqual(operation,'body_contact_standing')
        self.assertEqual(payload['giver'],'bob')
        self.assertEqual([e['by'] for e in payload['entries']],['bob','alice'])
        self.assertEqual([e['active'] for e in payload['entries']],[True,True])

    def test_broad_expired_event_has_inactive_mask(self):
        expired={'art':'zeit','start':'2026-11-01T12:00','end':'2026-11-01T13:00'}
        s,p=scene(event(1,'bob','refusal','jede_beruehrung'),
                  event(2,'bob','acceptance','jede_beruehrung',window=expired))
        with patch.object(bridge,'_native_request',return_value={'standing':0,'ended':None,'exceptions':[]}) as call:
            result=sc.body_contact_standing(s,p,at='2026-11-07T12:00')
        self.assertEqual(result['state'],'declined')
        self.assertEqual([e['active'] for e in call.call_args.args[2]['entries']],[True,False])

    def test_narrow_expired_event_has_inactive_mask_and_preserves_evidence(self):
        expired={'art':'zeit','start':'2026-11-01T12:00','end':'2026-11-01T13:00'}
        s,p=scene(event(1,'bob','refusal','eingeschraenkt',part='rechte Hand'),
                  event(2,'bob','acceptance','eingeschraenkt',part='rechte Hand',window=expired))
        with patch.object(bridge,'_native_request',return_value={'indices':[0]}) as call:
            result=sc.restricted_refusals_standing(s,p,at='2026-11-07T12:00')
        self.assertEqual([x['einschraenkung'] for x in result],['rechte Hand'])
        self.assertEqual([e['active'] for e in call.call_args.args[2]['entries']],[True,False])
        self.assertEqual(len(s['facts']),2)

    def test_multiple_scoped_exceptions_and_provenance_projection(self):
        s,p=scene(event(1,'bob','refusal','jede_beruehrung'),
                  event(2,'bob','acceptance','eingeschraenkt',part='linke Hand'),
                  event(3,'bob','acceptance','eingeschraenkt',part='rechte Hand'))
        with patch.object(bridge,'_native_request',return_value={
                'standing':0,'ended':None,'exceptions':[{'index':1,'kind':'acceptance'},
                                                       {'index':2,'kind':'acceptance'}]}):
            result=sc.body_contact_standing(s,p)
        self.assertEqual(result['state'],'declined')
        self.assertEqual(result['ausnahmen'],[
            {'causeFactId':'f2','kind':'acceptance','einschraenkung':'linke Hand','turn':2},
            {'causeFactId':'f3','kind':'acceptance','einschraenkung':'rechte Hand','turn':3}])

    def test_revoke_evidence_projects_existing_original_rows(self):
        s,p=scene(event(1,'bob','acceptance','jede_beruehrung'),
                  event(2,'bob','revoke','diese_tat'))
        with patch.object(bridge,'_native_request',return_value={'standing':None,'ended':[0,1],'exceptions':[]}):
            result=sc.body_contact_standing(s,p)
        self.assertEqual(result['state'],'revoked')
        self.assertEqual(result['causeFactId'],'f2')
        self.assertEqual(result['grantedTurn'],1)

    def test_unconfirmed_exception_stays_unconfirmed(self):
        s,p=scene(event(1,'bob','refusal','jede_beruehrung'),
                  event(2,'bob','acceptance','diese_tat',open_part='linke Hand'))
        with patch.object(bridge,'_native_request',return_value={
                'standing':0,'ended':None,'exceptions':[{'index':1,'kind':'unbestaetigt'}]}):
            result=sc.body_contact_standing(s,p)
        self.assertEqual(result['ausnahmen'][0]['kind'],'unbestaetigt')
        self.assertEqual(result['ausnahmen'][0]['einschraenkung'],'linke Hand')

    def test_permission_window_expired_refusal_cannot_erase_still_active_permission(self):
        expired={'art':'zeit','start':'2026-11-01T12:00','end':'2026-11-01T13:00'}
        s,p=scene(event(1,'bob','acceptance','eingeschraenkt',part='rechte Hand'),
                  event(2,'bob','refusal','eingeschraenkt',part='rechte Hand',window=expired))
        with patch.object(bridge,'_native_request',return_value={'indices':[0]}) as call:
            chosen=sc.restricted_permissions_standing(s,p,at='2026-11-07T12:00')
        self.assertEqual([r['einschraenkung'] for r in chosen],['rechte Hand'])
        self.assertEqual([e['active'] for e in call.call_args.args[2]['entries']],[True,False])
        self.assertEqual(call.call_args.args[0],'restricted_permissions')

    def test_restricted_permission_from_unrelated_speaker_must_not_grant(self):
        s,p=scene(event(1,'alice','acceptance','eingeschraenkt',part='rechte Hand'))
        with patch.object(bridge,'_native_request',return_value={'indices':[]}) as call:
            selected=sc.restricted_permissions_standing(s,p)
        self.assertEqual(selected,[])
        self.assertEqual(call.call_args.args[2]['giver'],'bob')
        self.assertEqual(call.call_args.args[2]['entries'][0]['by'],'alice')

    def test_malformed_native_permission_index_is_refused(self):
        s,p=scene(event(1,'alice','acceptance','eingeschraenkt',part='rechte Hand'))
        for reply in ({'indices':[0]},{'indices':[False]},{'indices':[1]},{'indices':[-1]},{}):
            with self.subTest(reply=reply),patch.object(bridge,'_native_request',return_value=reply):
                with self.assertRaises(bridge.NativeBoundaryError):
                    sc.restricted_permissions_standing(s,p)

    def test_read_fails_closed_when_native_absent(self):
        if bridge.library_path().exists():self.skipTest('Native library present')
        s,p=scene(event(1,'bob','refusal','jede_beruehrung'))
        with self.assertRaises(bridge.NativeBoundaryError) as cm:
            sc.body_contact_standing(s,p)
        self.assertEqual(cm.exception.code,'NATIVE_BOUNDARY_UNAVAILABLE')
        self.assertEqual(cm.exception.status,503)

    def test_malformed_reply_never_becomes_accepted(self):
        s,p=scene(event(1,'bob','refusal','jede_beruehrung'))
        malformed=({'standing':2,'ended':None,'exceptions':[]},
                   {'standing':False,'ended':None,'exceptions':[]},
                   {'standing':0,'ended':[0,1],'exceptions':[]},
                   {'standing':0,'ended':None,'exceptions':[{'index':2,'kind':'acceptance'}]},
                   {'standing':None,'ended':None,'exceptions':[{'index':0,'kind':'acceptance'}]},
                   {'standing':0,'ended':None,'exceptions':[{'index':0,'kind':'magic'}]},
                   {'ended':None,'exceptions':[]},
                   {'standing':0,'ended':None})
        for reply in malformed:
            with self.subTest(reply=reply),patch.object(bridge,'_native_request',return_value=reply):
                with self.assertRaises(bridge.NativeBoundaryError):
                    sc.body_contact_standing(s,p)

    def test_read_op_cannot_be_used_to_authorize_writer(self):
        with self.assertRaises(bridge.NativeBoundaryError) as cm:
            bridge.validate('body_contact_standing',{}, {})
        self.assertEqual(cm.exception.code,'NATIVE_CONTRACT_INVALID')

    def test_boolean_window_is_not_introduced_from_untyped_input(self):
        s,p=scene(event(1,'bob','refusal','jede_beruehrung'))
        for mask in ([],[1],[None],[False,True],'yes'):
            with self.subTest(mask=mask),self.assertRaises(bridge.NativeBoundaryError):
                bridge.reduce_body_contact_standing('bob',sc.body_contact_entries(s,p),mask)


    def test_native_broad_reply_must_identify_actual_broad_event(self):
        s,p=scene(event(1,'bob','acceptance','eingeschraenkt',part='rechte Hand'))
        with patch.object(bridge,'_native_request',return_value={'standing':0,'ended':None,'exceptions':[]}):
            with self.assertRaises(bridge.NativeBoundaryError):
                sc.body_contact_standing(s,p)

    def test_native_restricted_reply_must_identify_correct_kind(self):
        s,p=scene(event(1,'bob','refusal','eingeschraenkt',part='rechte Hand'),
                  event(2,'bob','acceptance','eingeschraenkt',part='linke Hand'))
        for reply,reader in (({'indices':[0]},sc.restricted_permissions_standing),
                             ({'indices':[1]},sc.restricted_refusals_standing)):
            with self.subTest(reader=reader.__name__),patch.object(bridge,'_native_request',return_value=reply):
                with self.assertRaises(bridge.NativeBoundaryError):
                    reader(s,p)

    def test_native_exception_must_match_recorded_fact(self):
        s,p=scene(event(1,'bob','refusal','jede_beruehrung'),
                  event(2,'bob','refusal','eingeschraenkt',part='linke Hand'))
        for row in ({'index':1,'kind':'acceptance'},{'index':1,'kind':'unbestaetigt'}):
            with self.subTest(row=row),patch.object(bridge,'_native_request',return_value={
                    'standing':0,'ended':None,'exceptions':[row]}):
                with self.assertRaises(bridge.NativeBoundaryError):
                    sc.body_contact_standing(s,p)

    def test_native_ending_must_have_broad_anchor(self):
        s,p=scene(event(1,'bob','acceptance','eingeschraenkt',part='rechte Hand'),
                  event(2,'bob','revoke','diese_tat'))
        with patch.object(bridge,'_native_request',return_value={
                'standing':None,'ended':[0,1],'exceptions':[]}):
            with self.assertRaises(bridge.NativeBoundaryError):
                sc.body_contact_standing(s,p)

    def test_native_exception_cannot_precede_broad_boundary(self):
        s,p=scene(event(1,'bob','acceptance','eingeschraenkt',part='linke Hand'),
                  event(2,'bob','refusal','jede_beruehrung'))
        with patch.object(bridge,'_native_request',return_value={
                'standing':1,'ended':None,'exceptions':[{'index':0,'kind':'acceptance'}]}):
            with self.assertRaises(bridge.NativeBoundaryError):
                sc.body_contact_standing(s,p)

if __name__=='__main__':unittest.main()
