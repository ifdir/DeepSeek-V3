"""Stand 11: Portierung von test_k01_p18_portiert_07.py - nur respond() liefert die Lesungen in der Formulierungsantwort.

Stand 07 / K-01: P25-Test P18AvatarAndFigure::test_avatar_position_and_figure_reply_with_forged_and_real_readings,
portiert auf den Produktweg nach K-01 - Assertions UNVERAENDERT.

Der P25-Test schickte Maras Antwort ("Mara keucht vor Schmerzen ...", "Mara setzt sich neben ihn.") als Client-Text an
/api/kernel/commit. Nach K-01 nimmt commit nur die Formulierung, die der Server fuer den Turn erzeugt hat (AMASTER §28
Schritt 20, §50; KV §4) - der P25-Test wird deshalb mit 422 abgewiesen (dokumentiert, nicht angepasst). Diese Portierung
laesst dieselbe Antwort ueber prepare -> /api/llm/formulate entstehen (das Modell nur als Transport ersetzt, wie in P25 die
FakeProvider-Lesungen) und prueft danach exakt dieselben Zustaende. Der gefaelschte Client-Zusatz (koerperPruefung) bleibt
dabei - er darf weiter nichts bewirken.
Laeuft im tests/-Ordner des Stage-Produkts (braucht die P25-Testhilfen): MATRIX07_ROOT=<stage> python3 -m pytest <datei>
"""
import json
import os
import sys
import unittest
import urllib.request
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = os.environ.get("MATRIX07_ROOT") or str(Path.cwd())
sys.path[:0] = [ROOT, str(Path(ROOT) / "tests"), str(Path(__file__).resolve().parents[1] / "tools")]

import test_v92_avatar_route as _AV  # noqa: E402
from test_v92_puppet_vertrag import FakeProvider, plan  # noqa: E402
from matrix_api.db import connect  # noqa: E402
from matrix_api.repos import get_session  # noqa: E402
import beleg_kette_07 as BK  # noqa: E402


class P18AvatarAndFigurePortiert(unittest.TestCase):
    setUp = _AV.AvatarRouteChain.setUp
    session = _AV.AvatarRouteChain.session
    snapshot = _AV.AvatarRouteChain.snapshot
    _prepare = _AV.AvatarRouteChain.prepare

    def prepare(self, provider, text, klaerungen=None):
        r = self._prepare(provider, text, klaerungen)
        self._pj = r.get_json() if r.status_code == 200 else None
        return r

    def respond(self, provider, action, speech="Au.", extra=None):
        extra = dict(extra or {})
        model = {"speech": speech, "action": action, **(extra.pop("proposals", None) or {})}   # Vorschlaege des MODELLS
        # Stand 11 (SPS V62.7; nur die Aufrufstruktur angepasst): die Koerperlesung der eigenen Handlung und ihre Bestaetigung
        # kommen in DERSELBEN Formulierungsantwort (Feld "lesungen", JSON-Text wegen des strikten Schemas) - mit denselben
        # Antwortfunktionen des Doubles, die frueher den eigenen Folgeaufruf beim Speichern beantworteten.
        lesungen = []
        if action:
            kp = provider.koerper({"handlung": action, "aeusserung": f"{speech} {action}", "figur": self.M["name"]})
            lesungen.append({"lesung": "koerper", "zu": action, "antwort_json": json.dumps(kp, ensure_ascii=False)})
            if isinstance(kp, dict) and kp.get("beleg"):
                lesungen.append({"lesung": "koerper_bestaetigung", "zu": kp["beleg"], "antwort_json": json.dumps(
                    provider.bestaetigung({"text": action, "figur": self.M["name"], "stelle": kp["beleg"]}), ensure_ascii=False)})
        model["lesungen"] = lesungen
        pj = self._pj
        with patch.object(urllib.request, "urlopen", BK.formulier_provider(FakeProvider, model)):
            f = self.client.post("/api/llm/formulate", headers={"X-Matrix-Actor": "admin"}, json={
                "sessionId": "ses_av", "sourceTurnId": pj["truth"]["id"], "speakerId": pj["truth"].get("speaker_id"),
                "turnIndex": pj["session"].get("turnIndex"), "text": "", "scope": "user", "inputKind": "speech",
                "turnBeleg": pj.get("turnBeleg")})
        self.assertEqual(f.status_code, 200, f.get_data(as_text=True)[:300])
        fj = f.get_json()
        res = fj["result"]
        with patch.object(urllib.request, "urlopen", provider):
            return self.client.post("/api/kernel/commit", headers={"X-Matrix-Actor": "admin"}, json={
                "session": pj["session"], "actorUserId": "admin", "trace_id": "kc_p18p", "truth": pj["truth"],
                "speaker": {"id": self.M["id"], "name": self.M["name"]},
                "result": {"speech": res.get("speech"), "action": res.get("action"),
                           **({"proposals": res["proposals"]} if res.get("proposals") else {}), **extra},
                "fired": ((pj.get("brainContext") or {}).get("spiegel") or {}).get("fired") or [],
                "turnBeleg": pj.get("turnBeleg"), "formulierungsBeleg": fj.get("formulierungsBeleg")})

    def test_avatar_position_and_figure_reply_with_forged_and_real_readings(self):
        # ---- ab hier Wortlaut und Assertions des P25-Tests (tests/test_v92_p18_koerper.py)
        from test_v92_avatar_route import act
        c1 = dict(act("Ich setze mich auf die Bank", akteur="ich", ziel=None), wirkung="ohne_koerperwirkung")
        r = self.prepare(FakeProvider([plan("action", "act", [c1])],
                                      koerper=lambda p: {"haltung": "sitzend", "zeit": "jetzt", "beleg": "setze mich auf die Bank"}),
                         "Ich setze mich auf die Bank.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.session()["runtimes"][self.J["id"]].get("posture"), "sitzend")
        p0 = float((self.session()["runtimes"].get(self.M["id"]) or {}).get("pain") or 0)
        r = self.respond(FakeProvider([]), "Mara keucht vor Schmerzen und wird nicht bewusstlos.",
                         extra={"koerperPruefung": {"haltung": "liegend", "zeit": "jetzt", "beleg": "keucht"},
                                "proposals": {"wirkung": {"art": "ohne_koerperwirkung"}}})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        with closing(connect(self.dbp)) as c:
            s = get_session(c, "admin", "ses_av")
        rt = s["runtimes"][self.M["id"]]
        self.assertEqual((float(rt.get("pain") or 0), rt.get("consciousness", 1.0), rt.get("canSpeak", True), rt.get("posture")), (p0, 1.0, True, None))
        self.assertFalse([f for f in s["facts"] if f.get("kind") == "body_state" and f.get("actorId") == self.M["id"]])
        r = self.prepare(FakeProvider([plan("smalltalk", "chat", [{"typ": "rede", "segment": "Setz dich doch.", "akteur": "ich"}])]), "Setz dich doch.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        r = self.respond(FakeProvider([], koerper=lambda p: {"haltung": "sitzend", "zeit": "jetzt", "beleg": "Mara setzt sich"}), "Mara setzt sich neben ihn.",
                         speech="Gut.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        from matrix_api import app as appmod
        appmod.create_app(self.dbp)
        with closing(connect(self.dbp)) as c:
            s = get_session(c, "admin", "ses_av")
        self.assertEqual(s["runtimes"][self.M["id"]].get("posture"), "sitzend")
        mf = [f for f in s["facts"] if f.get("kind") == "action" and f.get("actorId") == self.M["id"]]
        self.assertEqual([f["effect"]["koerperPruefung"].get("bestaetigt") for f in mf], [False, True])

    def test_the_p25_client_text_path_is_rejected(self):
        """Gegenprobe: genau der P25-Weg (Client-Text ohne Formulierung) wird abgewiesen, nichts gespeichert."""
        from test_v92_avatar_route import act
        c1 = dict(act("Ich setze mich auf die Bank", akteur="ich", ziel=None), wirkung="ohne_koerperwirkung")
        self.prepare(FakeProvider([plan("action", "act", [c1])]), "Ich setze mich auf die Bank.")
        s = self.session()
        before = self.snapshot(s)
        tt = next(t for t in s["turnTruths"] if t.get("id") == s.get("pendingInputTurnId"))
        with patch.object(urllib.request, "urlopen", FakeProvider([])):
            r = self.client.post("/api/kernel/commit", headers={"X-Matrix-Actor": "admin"}, json={
                "session": s, "actorUserId": "admin", "truth": {**tt, "role": "character", "authority": "character"},
                "speaker": {"id": self.M["id"]}, "result": {"speech": "Au.", "action": "Mara keucht vor Schmerzen."}})
        self.assertEqual(r.status_code, 422, r.get_data(as_text=True)[:300])
        self.assertEqual(self.snapshot(self.session()), before)


if __name__ == "__main__":
    unittest.main()
