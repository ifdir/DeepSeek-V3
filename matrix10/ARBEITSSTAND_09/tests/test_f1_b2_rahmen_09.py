"""Stand 09 / F1-B2: Der Beziehungsrahmen der Bewertung (AMASTER §44) nennt die Person und das Ereignis, zu denen er gehoert.

Befund F1 (ARBEITSSTAND_09/BEFUND_F1_DURCHLAUF_09.md): nach Johanns Schlag und einer Frage der Bedienperson stand im
Bewertungs-Payload von Mara nur "zu dieser Person besteht KEIN gewachsener Bund - neutral/fremd" - ohne Person. Der Rahmen
gehoert dem Akteur ihres zuletzt wahrgenommenen Ereignisses; jetzt steht er mit Person und Ereignis-ID da.
Echte P25-Welt (seed_builtin) auf frischer Temp-SQLite; kernel.appraisal_payload wie app._appraise_perceived.
MATRIX07_ROOT = Produktordner. Aufruf: python3 -m pytest <diese Datei>
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
J, M, G = "char_g7_johann", "char_g7_mara", "char_g7_gustav"


class F1B2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="f1b2_")
        dbp = str(Path(self.tmp) / "t.sqlite")
        os.environ["MATRIX_DB"] = dbp
        from matrix_api.db import connect, init_schema
        from matrix_api.seed_builtin import seed_if_missing
        with closing(connect(dbp)) as c:
            init_schema(c)
            seed_if_missing(c)
            self.W = c.execute("select world_id from characters where id=?", (J,)).fetchone()[0]
            self.natives = [json.loads(j) for (j,) in c.execute("select json from characters where world_id=?", (self.W,))]
        from matrix_api import kernel
        self.k = kernel
        self.schlag = {"id": "fact_schlag", "turn": 1, "kind": "action", "actorId": J, "targetId": M,
                       "text": "Johann schlägt Mara mit der Faust ins Gesicht", "authority": "character"}
        self.frage = {"id": "fact_frage", "turn": 2, "kind": "speech", "actorId": "user", "targetId": M,
                      "text": "Mara, was sagst du zu ihm?", "authority": "teilnehmer"}

    def payload(self, events):
        s = {"id": "ses_f1b2", "worldId": self.W, "turnIndex": 2, "scene": {"presentIds": [J, M, G]},
             "facts": [e[0] for e in events], "runtimes": {},
             "relations": [{"fromId": M, "toId": J, "trust": 0.15, "closeness": 0.25, "fear": 0.7, "kind": "Druck"}]}
        pend = [{"id": M, "name": "Mara Nowak", "events": [{"fact": f, "access": a} for f, a in events]}]
        figs = self.k.appraisal_payload(s, self.natives, pend).get("figuren") or []
        self.assertEqual(len(figs), 1)
        return figs[0]

    def test_rahmen_gehoert_der_letzten_person_und_nennt_sie(self):
        fig = self.payload([(self.schlag, "affected"), (self.frage, "heard")])
        r = fig.get("beziehung_zum_handelnden")
        self.assertIsInstance(r, dict, r)
        self.assertEqual(r["person"], fig["gerade_geschehen"][-1]["wer"])
        self.assertEqual(r["ereignis"], "fact_frage")
        self.assertNotEqual(r["person"], "Johann Bruckner")
        self.assertIn("Johann Bruckner", [b.get("zu") for b in fig.get("beziehungen") or []])

    def test_rahmen_zum_taeter_nennt_den_taeter(self):
        fig = self.payload([(self.schlag, "affected")])
        r = fig.get("beziehung_zum_handelnden")
        self.assertIsInstance(r, dict, r)
        self.assertEqual((r["person"], r["ereignis"]), ("Johann Bruckner", "fact_schlag"))
        self.assertIn("Vertrauen 15/100", r["stand"])


if __name__ == "__main__":
    unittest.main()
