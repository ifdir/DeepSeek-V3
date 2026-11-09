"""Stand 07 / SEC: kein gespeicherter Provider-Schluessel in API-Antworten, Browserzustand oder Protokollen.

Echte P25-App (create_app, Flask-Testclient), frische Temp-SQLite mit P25-Seed. Kein Netz: der Schluessel ist ein
Dummy, kein Provider wird aufgerufen. Aufruf (aus dem Stage-Produktordner): python3 -m pytest <diese Datei>
Umgebungsvariable MATRIX07_ROOT = Produktordner (Stage).
"""
from __future__ import annotations

import json
import os
from contextlib import closing
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = os.environ.get("MATRIX07_ROOT") or str(Path.cwd())
sys.path.insert(0, ROOT)
DUMMY = "sk-DUMMY07-NICHT-ECHT-4711"


class SecMcc(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sec07_")
        self.dbp = str(Path(self.tmp) / "t.sqlite")
        os.environ["MATRIX_DB"] = self.dbp
        os.environ["MATRIX_LIVE_LOG"] = str(Path(self.tmp) / "live.log")
        for k in ("OPENAI_API_KEY", "XAI_API_KEY", "MATRIX_API_KEY"):
            os.environ.pop(k, None)
        from matrix_api.db import connect, init_schema
        from matrix_api.seed_builtin import seed_if_missing
        with closing(connect(self.dbp)) as c:
            init_schema(c)
            seed_if_missing(c)
            c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\",\"name\":\"admin\"}')")
            c.commit()
        from matrix_api import app as appmod
        self.client = appmod.create_app(self.dbp).test_client()
        self.H = {"X-Matrix-Actor": "admin"}
        r = self.client.put("/api/config", headers=self.H, json={"scope": "user", "apiKey": DUMMY, "provider": "openai", "model": "gpt-4o-mini"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])

    def test_mcc_carries_no_key_but_presence(self):
        r = self.client.get("/api/mcc", headers=self.H)
        self.assertEqual(r.status_code, 200)
        text = r.get_data(as_text=True)
        self.assertNotIn(DUMMY, text, "GET /api/mcc enthaelt den Klartext-Schluessel")
        cfg = r.get_json().get("config") or {}
        self.assertTrue(cfg.get("apiKeyPresent"), cfg)
        self.assertNotIn("apiKey", cfg)
        self.assertTrue(str(cfg.get("apiKeyMasked") or "").strip(), cfg)

    def test_other_readers_carry_no_key(self):
        for path in ("/api/config?scope=user", "/api/logs", "/api/health", "/api/users/admin"):
            r = self.client.get(path, headers=self.H)
            self.assertNotIn(DUMMY, r.get_data(as_text=True), path)

    def test_provider_still_resolves_the_stored_key_server_side(self):
        # Providerfunktion bleibt: der Server liest den gespeicherten Schluessel selbst (ohne Netzaufruf geprueft).
        from matrix_api.db import connect
        from matrix_api.repos import get_config
        from matrix_api.llm_contract import provider_status
        with closing(connect(self.dbp)) as c:
            st = provider_status(get_config(c, "admin", "user"))
        self.assertTrue(st["keyPresent"], st)
        self.assertEqual(st["provider"], "openai", st)
        r = self.client.get("/api/config?scope=user", headers=self.H).get_json()
        cfg = r.get("config") or r
        self.assertTrue(cfg.get("keyPresent") or cfg.get("apiKeyPresent"), r)


if __name__ == "__main__":
    unittest.main()
