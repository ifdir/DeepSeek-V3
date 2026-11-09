"""Arbeitsstand 06 - Nachweise K1 (ABI 3) gegen die GESTAGTE P25-Kopie.

Umgebung: MATRIX06_ROOT = Stage-06-Produktordner (mit matrix_api/native/<lib>).
Optional: MATRIX06_ABI2_LIB = absichtlich mit ABI 2 gebaute Bibliothek (Gegenprobe).
Kein Mock. Fehlt MATRIX06_ROOT oder die Bibliothek: Fehler, kein Skip.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(os.environ["MATRIX06_ROOT"]).resolve()
sys.path.insert(0, str(ROOT))
from matrix_api import native_boundary as nb          # noqa: E402
from matrix_api import scene_state as sc              # noqa: E402

FIELDS = ("by", "kind", "scope", "einschraenkung", "einschraenkungOffen", "actTexts", "actsBound")


def entry(**kw):
    e = {"by": "mara", "kind": "refusal", "scope": "jede_beruehrung", "einschraenkung": None,
         "einschraenkungOffen": None, "actTexts": [], "actsBound": False}
    e.update(kw)
    return e


class Abi3Contract(unittest.TestCase):
    def test_library_reports_abi_3(self):
        self.assertTrue(nb.library_path().is_file(), "native Bibliothek fehlt im Stage")
        self.assertEqual(nb.ABI, 3)
        self.assertEqual(nb._load().matrix_boundary_abi_version(), 3)

    def test_every_reply_carries_abi_3(self):
        payload = nb._consent_request("mara", [entry()], [True])
        for op in ("body_contact_standing", "restricted_refusals", "restricted_permissions"):
            with self.subTest(op=op):
                self.assertEqual(nb._native_request(op, {}, payload)["abi"], 3)
        self.assertEqual(nb._native_request("restriction_match", {}, {"text": "Hand", "restriction": "Hand"},
                                            {"mode": "same"})["abi"], 3)

    def test_missing_abi3_field_is_contract_invalid_in_rust(self):
        for field in ("actTexts", "actsBound"):
            payload = nb._consent_request("mara", [entry()], [True])
            del payload["entries"][0][field]
            with self.subTest(field=field), self.assertRaises(nb.NativeBoundaryError) as cm:
                nb._native_request("restricted_permissions", {}, payload)
            self.assertEqual(cm.exception.code, "NATIVE_CONTRACT_INVALID")
            self.assertEqual(cm.exception.status, 503)

    def test_missing_abi3_field_is_rejected_in_python_before_transport(self):
        bad = entry()
        del bad["actTexts"]
        with self.assertRaises(nb.NativeBoundaryError) as cm:
            nb.reduce_restricted_permissions("mara", [bad], [True])
        self.assertEqual(cm.exception.code, "NATIVE_CONTRACT_INVALID")

    def test_abi2_library_is_rejected(self):
        lib2 = os.environ.get("MATRIX06_ABI2_LIB")
        self.assertTrue(lib2 and Path(lib2).is_file(), "MATRIX06_ABI2_LIB fehlt: Gegenprobe nicht ausfuehrbar")
        with tempfile.TemporaryDirectory() as d:
            pkg = Path(d) / "matrix_api"
            (pkg / "native").mkdir(parents=True)
            shutil.copy2(ROOT / "matrix_api/native_boundary.py", pkg / "native_boundary.py")
            shutil.copy2(lib2, pkg / "native" / nb.library_path().name)
            import importlib.util
            spec = importlib.util.spec_from_file_location("nb_abi2_probe", pkg / "native_boundary.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            with self.assertRaises(mod.NativeBoundaryError) as cm:
                mod._load()
            self.assertEqual(cm.exception.code, "NATIVE_ABI_MISMATCH")

    def test_p25_entries_carry_abi3_fields_for_every_kind(self):
        acts = [{"id": "a1", "kind": "action", "actorId": "johann", "targetId": "mara", "turn": 1,
                 "text": "Johann hält deine rechte Hand", "validated": True}]

        def lc(i, kind, kk):
            return {"id": f"f{i}", "kind": "lifecycle", "event_kind": kind, "actorId": "mara", "propositionId": "p",
                    "validated": True, "turn": i + 1, "text": f"t{i}", "payload": {"koerperkontakt": kk}}
        facts = acts + [
            lc(1, "refusal", {"scope": "jede_beruehrung"}),
            lc(2, "acceptance", {"scope": "eingeschraenkt", "einschraenkung": "rechte Hand"}),
            lc(3, "acceptance", {"scope": "diese_tat", "einschraenkung": "linke Hand"}),       # unbestaetigt
            lc(4, "revoke", {"scope": "diese_tat", "actFactIds": ["a1"]}),                     # gebunden
            lc(5, "revoke", {"scope": "diese_tat"}),                                           # ungebunden
            lc(6, "refusal", {"scope": "diese_tat", "actFactIds": ["a1", "fehlt"]}),           # Tat fehlt
        ]
        prop = {"id": "p", "kind": "koerperkontakt", "actorId": "johann", "targetId": "mara"}
        session = {"facts": facts, "propositions": [prop]}
        rows = {e["factId"]: e for e in sc.body_contact_entries(session, prop)}
        self.assertEqual(set(rows), {"f1", "f2", "f3", "f4", "f5", "f6"})
        for fid, e in rows.items():
            for f in FIELDS:
                self.assertIn(f, e, f"{fid}: {f} fehlt")
        self.assertEqual((rows["f4"]["actTexts"], rows["f4"]["actsBound"]), (["Johann hält deine rechte Hand"], True))
        self.assertEqual((rows["f5"]["actTexts"], rows["f5"]["actsBound"]), ([], False))
        self.assertEqual(rows["f6"]["actsBound"], False, "eine fehlende Tat darf nicht als gebunden gelten")
        self.assertEqual(rows["f3"]["einschraenkungOffen"], "linke Hand")
        # und der Rust-Reducer nimmt genau diese Form an
        active = [True] * len(rows)
        ordered = sc.body_contact_entries(session, prop)
        self.assertIsInstance(nb.reduce_body_contact_standing("mara", ordered, active), dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
