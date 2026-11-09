"""Stand 08 / K-02: Wahrnehmung -> Zuordnung -> Wissen -> Gedaechtnis -> Abruf -> naechste Entscheidung -> sichtbares Verhalten.

Echte P25-App (create_app, Flask-Testclient), frische Temp-SQLite mit P25-Seed, echte Routen wie die Oberflaeche:
prepare -> /api/llm/formulate -> commit (K-01-Belege), /api/kernel/presence ("Anwesend"), /api/sessions/<id>/recall
(Gedaechtnisseite). Formulierung = echte lokale Synapse (Provider "synapse", kein Netz). Das sichtbare Verhalten ist damit
ein DETERMINISTISCHER OFFLINE-NACHWEIS (local_render liest die abgerufenen Erinnerungen) - kein Modell-Nachweis.
MATRIX07_ROOT = Produktordner (Stage mit Rust-Bibliothek). Aufruf: python3 -m pytest <diese Datei>
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.environ.get("MATRIX07_ROOT") or str(Path.cwd())
sys.path.insert(0, ROOT)
J, M, G, R = "char_g7_johann", "char_g7_mara", "char_g7_gustav", "char_g7_robert"
EREIGNIS = "Johann, die Kasse im Keller ist leer."
FRAGE = "{name}, weißt du etwas über die Kasse im Keller?"


class K02(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="k02_")
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
            c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\",\"name\":\"admin\"}')")
            ids = {r[0] for r in c.execute("select id from characters")}
            self.assertTrue({J, M, G, R} <= ids, ids)
            self.W = c.execute("select world_id from characters where id=?", (J,)).fetchone()[0]
            for sid in ("ses_a", "ses_b"):
                create_session(c, {"id": sid, "worldId": self.W, "name": sid, "presentIds": [J, M, G], "avatarId": None,
                                   "role": "teilnehmer"}, "admin")
            c.commit()
        from matrix_api import app as appmod
        self.appmod = appmod
        self.client = appmod.create_app(self.dbp).test_client()
        self.H = {"X-Matrix-Actor": "admin"}
        self.assertEqual(self.client.put("/api/config", headers=self.H, json={"scope": "user", "provider": "synapse"}).status_code, 200)

    # ---- Produktwege wie kernel-bridge.ts / chat.$sessionId.tsx
    def session(self, sid="ses_a"):
        j = self.client.get(f"/api/sessions/{sid}", headers=self.H).get_json()
        return j.get("session") or j

    def turn(self, sid, speaker, text="", kind="speech", resume=None):
        truth = {"userId": "admin", "sessionId": sid, "speakerId": speaker, "inputActorId": "user", "speakAs": "operator",
                 "targetId": speaker if text else None, "inputKind": kind, "text": text}
        p = self.client.post("/api/kernel/prepare", headers=self.H, json={
            "sessionId": sid, "truth": truth, "speaker": {"id": speaker},
            **({"resumePending": {"turnTruthId": resume}} if resume else {})})
        self.assertEqual(p.status_code, 200, p.get_data(as_text=True)[:300])
        pj = p.get_json()
        f = self.client.post("/api/llm/formulate", headers=self.H, json={
            "sessionId": sid, "sourceTurnId": pj["truth"]["id"], "speakerId": speaker, "turnIndex": pj["session"].get("turnIndex"),
            "text": text, "scope": "user", "inputKind": kind, "provider": "synapse", "turnBeleg": pj.get("turnBeleg")})
        self.assertEqual(f.status_code, 200, f.get_data(as_text=True)[:300])
        fj = f.get_json()
        res = fj["result"]
        c = self.client.post("/api/kernel/commit", headers=self.H, json={
            "sessionId": sid, "truth": pj["truth"], "speaker": {"id": speaker},
            "result": {"speech": res.get("speech"), "action": res.get("action")},
            "fired": ((pj.get("brainContext") or {}).get("spiegel") or {}).get("fired") or [],
            "turnBeleg": pj.get("turnBeleg"), "formulierungsBeleg": fj.get("formulierungsBeleg")})
        self.assertEqual(c.status_code, 200, c.get_data(as_text=True)[:300])
        return pj["truth"]["id"], res

    def presence(self, sid, cid):
        r = self.client.post("/api/kernel/presence", headers=self.H, json={"sessionId": sid, "characterId": cid})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])

    def recall(self, sid, cid, cue):
        return self.client.post(f"/api/sessions/{sid}/recall", headers=self.H, json={"cue": cue, "characterId": cid})

    def mem(self, sid, cid, fact_id=None, text=None):
        return [m for m in self.session(sid).get("memories") or [] if m.get("characterId") == cid
                and (fact_id is None or m.get("factId") == fact_id) and (text is None or text in str(m.get("text") or ""))]

    def digest(self, sid):
        h = hashlib.sha256()
        with closing(sqlite3.connect(self.dbp)) as c:
            for t in ("scene_facts", "memories", "witness_knowledge", "turn_truth"):
                for row in c.execute(f"SELECT * FROM {t} WHERE session_id=? ORDER BY rowid", (sid,)):
                    h.update(repr(row).encode())
        return h.hexdigest()

    # ---- Wahrnehmung und Zuordnung
    def test_1_wahrnehmung_zuordnung_und_wissensart(self):
        b0 = self.digest("ses_b")
        tt, res = self.turn("ses_a", J, EREIGNIS)
        s = self.session()
        inp = next(f for f in s["facts"] if f.get("sourceTurnId") == tt and f.get("actorId") == "user")
        ans = next(f for f in s["facts"] if f.get("sourceTurnId") == tt and f.get("actorId") == J and f.get("kind") == "speech")
        # anwesende Hoerer: gehoert, mit Zuschreibung (Redeereignis, keine Weltwahrheit "Kasse ist leer")
        for cid in (M, G):
            hm = self.mem("ses_a", cid, inp["id"])
            self.assertEqual([m["kind"] for m in hm], ["gehoert"], hm)
            self.assertIn("sagte:", hm[0]["text"])
        # der Antwortende: eigene Rede = gesagt
        self.assertEqual([m["kind"] for m in self.mem("ses_a", J, ans["id"])], ["gesagt"])
        # abwesende Figur: kein Wissensweg
        self.assertFalse(self.mem("ses_a", R))
        self.assertFalse([w for w in s.get("witnessKnowledge") or [] if w.get("character_id") == R])
        self.assertEqual(self.digest("ses_b"), b0, "fremde Session veraendert")

    def test_2_antwortphase_wahrnehmung_zum_antwortzeitpunkt(self):
        truth = {"userId": "admin", "sessionId": "ses_a", "speakerId": J, "inputActorId": "user", "speakAs": "operator",
                 "targetId": J, "inputKind": "speech", "text": EREIGNIS}
        p = self.client.post("/api/kernel/prepare", headers=self.H, json={"sessionId": "ses_a", "truth": truth, "speaker": {"id": J}})
        self.assertEqual(p.status_code, 200)
        pend = self.session()["pendingInputTurnId"]
        self.presence("ses_a", G)                        # Gustav geht, bevor geantwortet wird
        self.assertNotIn(G, self.session()["scene"]["presentIds"])
        self.turn("ses_a", J, EREIGNIS, resume=pend)      # "Antwort erneut erzeugen"
        s = self.session()
        ans = next(f for f in s["facts"] if f.get("sourceTurnId") == pend and f.get("actorId") == J and f.get("kind") == "speech")
        self.assertFalse(self.mem("ses_a", G, ans["id"]), "Gustav erinnert eine Antwort, die er nicht gehoert hat")
        self.assertFalse([w for w in s["witnessKnowledge"] if w.get("character_id") == G and w.get("fact_id") == ans["id"]])
        self.assertNotIn(G, ans.get("witnessedBy") or [])
        from matrix_api import kernel
        self.assertFalse([d for d in kernel._dialogue_visible_to(s, G, s.get("turns") or []) if d.get("speech") == ans.get("text")])
        self.assertTrue(self.mem("ses_a", M, ans["id"]), "Mara (anwesend) hoert die Antwort")
        # die Eingabe selbst hat Gustav gehoert (er war da) - Historie bleibt
        inp = next(f for f in s["facts"] if f.get("sourceTurnId") == pend and f.get("actorId") == "user")
        self.assertTrue(self.mem("ses_a", G, inp["id"]))

    # ---- Abruf, Neustart, Session-Trennung, Folgeturn-Verhalten
    def test_3_abruf_neustart_trennung_und_verhalten(self):
        self.turn("ses_a", J, EREIGNIS)                   # Mara hoert; Robert ist nicht da
        self.presence("ses_a", R)                         # Robert kommt spaeter
        for i in range(11):                               # das Ereignis rueckt aus dem sichtbaren Dialogfenster (10 Turns)
            self.turn("ses_a", (J, G)[i % 2], "", "autochat")
        self.client = self.appmod.create_app(self.dbp).test_client()       # Neustart: neue App auf derselben SQLite
        # Abruf ueber die Gedaechtnisseite (kanonischer Leser der Figur)
        rm = self.recall("ses_a", M, "Kasse Keller").get_json()
        self.assertEqual(rm.get("engine"), "kernel.recall")
        self.assertTrue(any("Kasse" in str(m.get("text")) for m in rm["memories"]), rm)
        rr = self.recall("ses_a", R, "Kasse Keller").get_json()
        self.assertFalse(any("Kasse" in str(m.get("text")) for m in rr["memories"]), rr)
        self.assertFalse(any("Kasse" in str(f.get("text")) for f in rr["facts"]), rr)
        # naechste Entscheidung / sichtbares Verhalten (Synapse liest die abgerufenen Erinnerungen)
        _, a_m = self.turn("ses_a", M, FRAGE.format(name="Mara"))
        _, a_r = self.turn("ses_a", R, FRAGE.format(name="Robert"))
        self.assertIn("Ich erinnere mich", a_m["speech"], a_m)
        self.assertIn("Kasse", a_m["speech"], a_m)
        self.assertNotIn("Kasse", a_r["speech"], a_r)
        self.assertIn("weiß ich nicht", a_r["speech"], a_r)
        # Session-Trennung: dieselbe Figur, andere Session derselben Welt
        rb = self.recall("ses_b", M, "Kasse Keller").get_json()
        self.assertFalse(any("Kasse" in str(m.get("text")) for m in rb["memories"]), rb)

    def test_4_recall_nur_fuer_figuren_dieser_welt_und_cache_bleibt_gekennzeichnet(self):
        self.turn("ses_a", J, EREIGNIS)
        r = self.recall("ses_a", "char_gibt_es_nicht", "Kasse")
        self.assertIn(r.status_code, (404, 422), r.get_data(as_text=True)[:200])
        c = self.client.post("/api/sessions/ses_a/recall", headers=self.H, json={"cue": "Kasse"}).get_json()
        self.assertNotEqual(c.get("engine"), "kernel.recall")
        self.assertFalse(c.get("kanonisch", False))


if __name__ == "__main__":
    unittest.main()
