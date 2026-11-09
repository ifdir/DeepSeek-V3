"""Python transport tests ONLY. They do not execute or prove any Rust code."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import random
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("boundary_transport", ROOT / "integration/native_boundary.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class TransportTests(unittest.TestCase):
    def test_json_types_and_unicode(self):
        value = {"none": None, "bool": True, "int": -2**63, "large": 2**63-1,
                 "float": 0.125, "text": "Gr\u00fc\u00dfe \U0001f44b", "list": [False, {}, []]}
        self.assertEqual(b.decode(b.encode(value)), value)
        self.assertIs(type(b.decode(b.encode(True))), bool)
        self.assertIs(type(b.decode(b.encode(1))), int)

    def test_golden_binary_protocol(self):
        # Independently written fixed bytes, not an encoder-derived expectation.
        expected = b"MXRB\x01\x00\x07\x01\x00\x00\x00\x01\x00\x00\x00a\x03\x07\x00\x00\x00\x00\x00\x00\x00"
        self.assertEqual(b.encode({"a": 7}), expected)
        self.assertEqual(b.decode(expected), {"a": 7})

    def test_all_truncated_prefixes(self):
        encoded = b.encode({"a": ["alice", 12, None]})
        for end in range(len(encoded)):
            with self.subTest(end=end), self.assertRaises(b.NativeBoundaryError):
                b.decode(encoded[:end])

    def test_trailing_unknown_and_duplicate(self):
        for invalid in [b.encode(None) + b"x", b.MAGIC + b"\x09",
                        b.MAGIC + bytes([7,2,0,0,0,1,0,0,0,120,0,1,0,0,0,120,0])]:
            with self.assertRaises(b.NativeBoundaryError):
                b.decode(invalid)

    def test_huge_collection_count_rejected(self):
        for tag in (6, 7):
            with self.assertRaises(b.NativeBoundaryError):
                b.decode(b.MAGIC + bytes([tag]) + struct.pack("<I", 2**32-1))

    def test_nonfinite_and_out_of_range(self):
        for invalid in [float("nan"), float("inf"), 2**63, -(2**63)-1, {1: "x"}, b"bytes"]:
            with self.assertRaises(b.NativeBoundaryError):
                b.encode(invalid)

    def test_depth_is_error_not_truncation(self):
        value = None
        for _ in range(66):
            value = [value]
        with self.assertRaises(b.NativeBoundaryError):
            b.encode(value)

    def test_no_six_component_truncation(self):
        value = [{"id": f"component_{i}", "text": "x"} for i in range(257)]
        self.assertEqual(b.decode(b.encode(value)), value)

    def test_deterministic_random_roundtrips(self):
        rng = random.Random(67121107)
        def value(depth=0):
            if depth > 3:
                return rng.choice([None, True, False, "alice", "\u00e4\u00f6\u00fc", -99, 0.125])
            kind = rng.randrange(3)
            if kind == 0:
                return [value(depth+1) for _ in range(rng.randrange(6))]
            if kind == 1:
                return {f"key{i}": value(depth+1) for i in range(rng.randrange(6))}
            return value(4)
        for i in range(200):
            with self.subTest(i=i):
                v = value()
                self.assertEqual(b.decode(b.encode(v)), v)

    def test_scope_query_does_not_fallback_without_rust(self):
        with self.assertRaises(b.NativeBoundaryError) as caught:
            b.restriction_match("rechte Hand", "linke Hand", "same")
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.code, "NATIVE_BOUNDARY_UNAVAILABLE")

    def test_scope_query_cannot_be_used_as_writer_authorization(self):
        with self.assertRaises(b.NativeBoundaryError) as caught:
            b.validate("restriction_match", {}, {})
        self.assertEqual(caught.exception.code, "NATIVE_CONTRACT_INVALID")

    def test_invalid_scope_query_never_returns_false_as_a_verdict(self):
        for mode in ("none", "unknown", "", None):
            with self.subTest(mode=mode), self.assertRaises(b.NativeBoundaryError):
                b.restriction_match("rechte Hand", "linke Hand", mode)

    def test_missing_library_never_authorizes(self):
        self.assertFalse(b.library_path().exists(), "This test requires the source-only package")
        with self.assertRaises(b.NativeBoundaryError) as caught:
            b.validate("fact", {}, {})
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.code, "NATIVE_BOUNDARY_UNAVAILABLE")

if __name__ == "__main__":
    unittest.main()
