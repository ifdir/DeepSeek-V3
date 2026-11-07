"""Python FFI-envelope tests for 03. DO NOT count as executed Rust tests."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("matrix03_native_bridge", ROOT / "integration/native_boundary.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def e(by='bob', kind='refusal', scope='eingeschraenkt', part='rechte Hand'):
    # Stand 05 / ABI 3: jeder kanonische Eintrag traegt die gebundenen Taten (body_contact_entries).
    return {"by":by,"kind":kind,"scope":scope,"einschraenkung":part,"einschraenkungOffen":None,
            "actTexts":[],"actsBound":False}

class ConsentEnvelopeTests(unittest.TestCase):
    def test_preserves_canonical_indices_not_new_rows(self):
        sample=[e(),e(kind='acceptance',part='linke Hand')]
        with patch.object(bridge,'_native_request', return_value={"indices":[0]} ) as call:
            self.assertEqual(bridge.reduce_restricted_refusals('bob',sample,[True]*len(sample)),[0])
        op,ctx,payload=call.call_args.args
        self.assertEqual(op,'restricted_refusals')
        self.assertEqual(ctx,{})
        self.assertEqual(len(payload['entries']),2)
        self.assertEqual([e['active'] for e in payload['entries']],[True,True])

    def test_legacy_nullable_fields_are_normalized_without_new_effect(self):
        original=e(scope=None,part=None)
        with patch.object(bridge,'_native_request',return_value={"indices":[]} ) as call:
            self.assertEqual(bridge.reduce_restricted_refusals('bob',[original],[True]),[])
        fields=call.call_args.args[2]['entries'][0]
        self.assertEqual(fields,{"by":"bob","kind":"refusal","scope":"","einschraenkung":"", "einschraenkungOffen":"", "active": True,
                                 "actTexts":[],"actsBound":False})
        self.assertIsNone(original['scope'],"The canonical original must not be mutated")

    def test_11_entries_are_never_silently_truncated(self):
        cases=[e(part=p) for p in ('Hand','Arm','Schulter','Knie','Fuss','Nase','Ohr','Lippe','Mund','Zehe','Bein')]
        with patch.object(bridge,'_native_request',return_value={"indices":list(range(11))}) as call:
            self.assertEqual(bridge.reduce_restricted_refusals('bob',cases,[True]*len(cases)),list(range(11)))
        self.assertEqual(len(call.call_args.args[2]['entries']),11)

    def test_fail_closed_without_native_library(self):
        if bridge.library_path().exists(): self.skipTest('Real Rust native boundary available in this environment')
        with self.assertRaises(bridge.NativeBoundaryError) as cm:
            bridge.reduce_restricted_refusals('bob',[e()],[True])
        self.assertEqual(cm.exception.code,'NATIVE_BOUNDARY_UNAVAILABLE')
        self.assertEqual(cm.exception.status,503)

    def test_invalid_giver_or_non_event_never_becomes_empty_permission(self):
        for giver,rows in [('',[e()]),('bob',{}),('bob',[None]),('bob',[{'kind':'refusal'}]),(None,[e()])]:
            with self.subTest(giver=giver,rows=rows), self.assertRaises(bridge.NativeBoundaryError) as cm:
                bridge.reduce_restricted_refusals(giver,rows,[True]*len(rows) if type(rows) is list else [])
            self.assertEqual(cm.exception.code,'NATIVE_CONTRACT_INVALID')

    def test_native_indices_are_validated_no_silent_drop(self):
        for reply in ({},{"indices":None},{"indices":[-1]}, {"indices":[2]},
                      {"indices":[1,0]}, {"indices":[0,0]}, {"indices":[True]},
                      {"indices":[0.0]}, {"indices":"0"}):
            with self.subTest(reply=reply), patch.object(bridge,'_native_request',return_value=reply):
                with self.assertRaises(bridge.NativeBoundaryError) as cm:
                    bridge.reduce_restricted_refusals('bob',[e(),e()],[True,True])
                self.assertEqual(cm.exception.code,'NATIVE_REPLY_INVALID')

    def test_reader_op_is_not_a_write_authorization(self):
        with self.assertRaises(bridge.NativeBoundaryError) as cm:
            bridge.validate('restricted_refusals',{}, {})
        self.assertEqual(cm.exception.code,'NATIVE_CONTRACT_INVALID')

    def test_zero_event_input_remains_valid_when_native_says_empty(self):
        with patch.object(bridge,'_native_request',return_value={"indices":[]}):
            self.assertEqual(bridge.reduce_restricted_refusals('bob',[],[]),[])

if __name__=='__main__': unittest.main()
