"""Stand 10 / F2 (K-05): Ein Zug OHNE Nutzereingabe (inputKind autochat) spricht nur die Figur, die der Server waehlt.

AMASTER §28 Schritt 16 ("naechsten Sprecher bestimmen"), §48, KV §12.6. Befund F2 (ARBEITSSTAND_10/BEFUND_F2_10.md):
bis Stand 09 nahm prepare den Sprecher des Clients an, waehrend /api/kernel/autochat-gate eine andere Figur waehlte.
Echte P25-App (create_app, Flask-Testclient), Temp-SQLite mit P25-Seed, echte Routen wie die Oberflaeche, Provider
"synapse" (kein Netz, kein Modell-Nachweis). MATRIX07_ROOT = Produktordner. Aufruf: python3 -m pytest <diese Datei>
"""
from __future__ import annotations

import hashlib
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.environ.get("MATRIX07_ROOT") or str(Path.cwd())
sys.path.insert(0, ROOT)
J, M, G = "char_g7_johann", "char_g7_mara", "char_g7_gustav"


class F2Sprecher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="f2_")
        self.dbp = str(Path(self.tmp) / "t.sqlite")
        os.environ["MATRIX_DB"] = self.dbp
        os.environ["MATRIX_LIVE_LOG"] = str(Path(self.tmp) / "live.log")
        for k in ("OPENAI_API_KEY", "XAI_API_KEY", "MATRIX_API_KEY"):
            os.environ.pop(k, None)
        from matrix_api.db import connect, init_schema
        from matrix_api.seed_builtin import seed_if_missing
        from matrix_api.repos import create_session
        with closing(connect(self.dbp)) as c:
            init_schema(c)
            seed_if_missing(c)
            c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin', ?)", ('{"id": "admin", "name": "admin"}',))
            w = c.execute("select world_id from characters where id=?", (J,)).fetchone()[0]
            create_session(c, {"id": "ses_f2", "worldId": w, "name": "f2", "presentIds": [J, M, G], "avatarId": None,
                               "role": "teilnehmer"}, "admin")
            c.commit()
        from matrix_api import app as appmod
        self.client = appmod.create_app(self.dbp).test_client()
        self.H = {"X-Matrix-Actor": "admin"}
        self.assertEqual(self.client.put("/api/config", headers=self.H, json={"scope": "user", "provider": "synapse"}).status_code, 200)

    def prepare(self, speaker, text="", kind="speech"):
        truth = {"userId": "admin", "sessionId": "ses_f2", "speakerId": speaker, "inputActorId": "user", "speakAs": "operator",
                 "targetId": speaker if text else None, "inputKind": kind, "text": text}
        return self.client.post("/api/kernel/prepare", headers=self.H, json={"sessionId": "ses_f2", "truth": truth, "speaker": {"id": speaker}})

    def turn(self, speaker, text="", kind="speech"):
        p = self.prepare(speaker, text, kind)
        self.assertEqual(p.status_code, 200, p.get_data(as_text=True)[:300])
        pj = p.get_json()
        f = self.client.post("/api/llm/formulate", headers=self.H, json={
            "sessionId": "ses_f2", "sourceTurnId": pj["truth"]["id"], "speakerId": speaker, "text": text, "scope": "user",
            "inputKind": kind, "provider": "synapse", "turnBeleg": pj.get("turnBeleg")})
        self.assertEqual(f.status_code, 200, f.get_data(as_text=True)[:300])
        fj = f.get_json()
        c = self.client.post("/api/kernel/commit", headers=self.H, json={
            "sessionId": "ses_f2", "truth": pj["truth"], "speaker": {"id": speaker},
            "result": {"speech": fj["result"].get("speech"), "action": fj["result"].get("action")},
            "fired": ((pj.get("brainContext") or {}).get("spiegel") or {}).get("fired") or [],
            "turnBeleg": pj.get("turnBeleg"), "formulierungsBeleg": fj.get("formulierungsBeleg")})
        self.assertEqual(c.status_code, 200, c.get_data(as_text=True)[:300])

    def gate(self):
        r = self.client.post("/api/kernel/autochat-gate", headers=self.H, json={"sessionId": "ses_f2", "remaining": 2, "stimulus": ""})
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def digest(self):
        h = hashlib.sha256()
        with closing(sqlite3.connect(self.dbp)) as c:
            for t in ("scene_facts", "memories", "witness_knowledge", "turn_truth", "turns"):
                for row in c.execute(f"SELECT * FROM {t} WHERE session_id=? ORDER BY rowid", ("ses_f2",)):
                    h.update(repr(row).encode())
            h.update(repr(c.execute("SELECT json FROM sessions WHERE id=?", ("ses_f2",)).fetchall()).encode())
        return h.hexdigest()

    def test_folgezug_nur_mit_der_vom_server_gewaehlten_figur(self):
        self.turn(J, "Johann, die Kasse im Keller ist leer.")
        g = self.gate()
        self.assertFalse(g.get("stop"), g)
        gewaehlt = g["speakerId"]
        from matrix_api import app as appmod
        from matrix_api import kernel
        s = self.client.get("/api/sessions/ses_f2", headers=self.H).get_json()
        s = s.get("session") or s
        with closing(sqlite3.connect(self.dbp)) as c:
            import json
            natives = [json.loads(j) for (j,) in c.execute("select json from characters where id in (?,?,?)", (J, M, G))]
        # die Pruefung der Route und das Gate sind dieselbe Serverentscheidung
        self.assertEqual(appmod.autochat_sprecher(s, natives, {"inputKind": "autochat"}, gewaehlt)["grund"], "gewaehlt")
        fremd = [x for x in (M, G, J) if x != gewaehlt and not appmod.autochat_sprecher(s, natives, {"inputKind": "autochat"}, x)["ok"]]
        self.assertTrue(fremd, "keine nicht gewaehlte Figur zum Gegenpruefen")
        vorher = self.digest()
        r = self.prepare(fremd[0], "", "autochat")
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True)[:300])
        self.assertEqual(r.get_json().get("code"), "AUTOCHAT_SPRECHER_NICHT_GEWAEHLT")
        self.assertEqual(self.digest(), vorher, "abgewiesener Folgezug hat etwas gespeichert")
        self.turn(gewaehlt, "", "autochat")              # die gewaehlte Figur spricht
        self.assertTrue(kernel.latest_event_stimulus(
            (lambda j: j.get("session") or j)(self.client.get("/api/sessions/ses_f2", headers=self.H).get_json()))[0])

    def test_eingabezug_unveraendert_bedienperson_waehlt_ansprechpartner(self):
        # ein Zug MIT Nutzereingabe bleibt wie bisher: angesprochene, anwesende Figur antwortet
        self.turn(M, "Mara, wie geht es dir?")
        self.turn(G, "Gustav, und dir?")


if __name__ == "__main__":
    unittest.main()
