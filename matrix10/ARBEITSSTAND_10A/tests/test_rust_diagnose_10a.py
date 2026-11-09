"""Stand 10a: Ist der Rust-Einwilligungskern HIER nicht ladbar, nennen Server, /api/health und der 503-Text den Grund.

Anlass: Android-Lauf 08.11. - die erste Beruehrungs-Eingabe scheiterte mit "Rust-Schreibgrenze konnte nicht geladen werden"
ohne Grund; native_boundary._load verwarf den Ladertext. Fail-closed bleibt (Nutzerentscheidung 06a/M1): kein Ersatz, keine
Speicherung. MATRIX07_ROOT = Produktordner mit der echten Paket-Bibliothek. Aufruf: python3 -m pytest <diese Datei>
"""
from __future__ import annotations

import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = os.environ.get("MATRIX07_ROOT") or str(Path.cwd())
sys.path.insert(0, ROOT)


def fremdes_elf(machine: int) -> bytes:
    return b"\x7fELF\x02\x01\x01" + b"\x00" * 9 + struct.pack("<HH", 3, machine) + b"\x00" * 200


class RustDiagnose(unittest.TestCase):
    def setUp(self):
        from matrix_api import native_boundary as nb
        self.nb = nb
        self.echt = nb.library_path
        nb._library = None

    def tearDown(self):
        self.nb.library_path = self.echt
        self.nb._library = None

    def mit_datei(self, inhalt: bytes) -> Path:
        d = Path(tempfile.mkdtemp(prefix="rk_")) / "matrix_api" / "native"
        d.mkdir(parents=True)
        p = d / "libmatrix_boundary_core.so"
        p.write_bytes(inhalt)
        self.nb.library_path = lambda: p
        return p

    def test_echte_bibliothek_ok(self):
        st = self.nb.status()
        self.assertTrue(st["ok"], st)
        self.assertEqual(st["abi"], self.nb.ABI)

    def test_falsche_architektur_wird_benannt_und_bleibt_fail_closed(self):
        import platform
        fremd = 183 if platform.machine().lower() in ("x86_64", "amd64") else 62
        self.mit_datei(fremdes_elf(fremd))
        with self.assertRaises(self.nb.NativeBoundaryError) as cm:
            self.nb._load()
        self.assertEqual(cm.exception.code, "NATIVE_BOUNDARY_UNAVAILABLE")
        self.assertEqual(cm.exception.status, 503)
        self.assertIn("konnte nicht geladen werden: ", cm.exception.message)
        self.assertIn("Bibliothek ist fuer", cm.exception.message)
        self.assertIn("Lader meldet:", cm.exception.message)
        self.assertIsNone(self.nb._library)
        st = self.nb.status()
        self.assertFalse(st["ok"])
        self.assertIn("Bibliothek ist fuer", st["grund"])
        self.assertTrue(st["abhilfe"])

    def test_nicht_ladbarer_ort_wird_ueber_byte_gleiche_kopie_geladen(self):
        """Pydroid 3 / Download: der Ort erlaubt kein Laden (noexec). Dieselbe Bibliothek wird aus dem App-Speicher geladen."""
        import ctypes
        import hashlib
        echt = self.echt()
        p = self.mit_datei(echt.read_bytes())
        orig = ctypes.CDLL

        def cdll(name, *a, **k):
            if str(name) == str(p):
                raise OSError(f"{p}: failed to map segment from shared object")
            return orig(name, *a, **k)
        self.nb.ctypes.CDLL = cdll
        try:
            st = self.nb.status()
        finally:
            self.nb.ctypes.CDLL = orig
        self.assertTrue(st["ok"], st)
        self.assertEqual(st["geladenAus"], "app_kopie")
        kopien = list(Path(tempfile.gettempdir()).glob("matrix10_native_*/libmatrix_boundary_core-*.so"))
        self.assertTrue(any(hashlib.sha256(k.read_bytes()).hexdigest() == hashlib.sha256(echt.read_bytes()).hexdigest() for k in kopien))

    def test_keine_elf_datei(self):
        self.mit_datei(b"")
        st = self.nb.status()
        self.assertFalse(st["ok"])
        self.assertIn("keine Linux/Android-Bibliothek", st["grund"])

    def test_health_meldet_rustkern(self):
        tmp = tempfile.mkdtemp(prefix="rkh_")
        os.environ["MATRIX_DB"] = str(Path(tmp) / "t.sqlite")
        from matrix_api import app as appmod
        c = appmod.create_app(os.environ["MATRIX_DB"]).test_client()
        self.assertTrue(c.get("/api/health").get_json()["rustKern"]["ok"])
        self.nb._library = None          # ein anderer Prozess/Start mit einer nicht ladbaren Datei
        self.mit_datei(fremdes_elf(183 if __import__("platform").machine().lower() in ("x86_64", "amd64") else 62))
        rk = c.get("/api/health").get_json()["rustKern"]
        self.assertFalse(rk["ok"])
        self.assertIn("Bibliothek ist fuer", rk["grund"])


if __name__ == "__main__":
    unittest.main()
