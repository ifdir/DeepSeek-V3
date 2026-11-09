"""Stand 10B: unabhaengige Modell-Lesungen laufen gleichzeitig - je Lesung eine eigene SQLite-Verbindung, Fehler bleiben je
Lesung erhalten und werden beim Aufrufer wie im Ablauf nacheinander ausgeloest. MATRIX07_ROOT = Produktordner."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.environ.get("MATRIX07_ROOT") or str(Path.cwd())
sys.path.insert(0, ROOT)


class Gleichzeitig(unittest.TestCase):
    def setUp(self):
        self.db = str(Path(tempfile.mkdtemp(prefix="l10b_")) / "t.sqlite")
        from matrix_api import app as appmod
        self.app = appmod

    def test_gleichzeitig_eigene_verbindungen_und_fehler_je_lesung(self):
        gesehen = []

        def lesung(c, name):
            gesehen.append((name, threading.get_ident(), id(c)))
            time.sleep(0.4)
            if name == "kaputt":
                raise ValueError("Lesung fehlgeschlagen")
            return name.upper()
        t0 = time.time()
        r = self.app.lesungen_gleichzeitig(self.db, {k: (lambda c, k=k: lesung(c, k)) for k in ("a", "b", "kaputt")})
        dauer = time.time() - t0
        self.assertLess(dauer, 1.0, "nicht gleichzeitig")
        self.assertEqual(r["a"], ("ok", "A"))
        self.assertEqual(r["b"], ("ok", "B"))
        self.assertEqual(r["kaputt"][0], "fehler")
        self.assertEqual(len({g[2] for g in gesehen}), 3, "Lesungen teilen eine Verbindung")
        with self.assertRaises(ValueError):
            self.app._vorab_oder(r, "kaputt", lambda: "nicht aufrufen")
        self.assertEqual(self.app._vorab_oder(r, "a", lambda: "nicht aufrufen"), "A")
        self.assertEqual(self.app._vorab_oder({}, "x", lambda: "jetzt"), "jetzt")

    def test_sprach_vorbedingung_wie_read_language(self):
        b = self.app._braucht_sprache
        self.assertFalse(b({"event_kind": "action", "komponenten": [{"typ": "handlung"}]}))
        self.assertTrue(b({"event_kind": "action", "komponenten": [{"typ": "handlung"}, {"typ": "rede"}]}))
        self.assertTrue(b({"event_kind": "claim", "komponenten": [{"typ": "rede"}]}))


if __name__ == "__main__":
    unittest.main()
