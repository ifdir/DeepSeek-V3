"""Stand 11F: Auswahl im Figurenbrief nach Bedeutung (Pruefbericht 11E; AMASTER §41 "Recall nach Relevanz, ohne
lifecycle-relevante Evidenz zu verlieren", §49). Gegenbeispiele des Pruefberichts als Test:
- Frage nach dem abwesenden Alrik -> sein Wissen bleibt; Wissen nur ueber andere Abwesende faellt weg;
- "Annette" bindet nicht die Bindung zu "Ann" (Identitaet statt Namensteil);
- eine aeltere, noch wirkende Ursache haelt ihre Profilstelle (nicht nur die zwei juengsten Erlebnisse);
- offener Moment: Werte und kurzer Lebenslauf, keine unbelegte Angst;
- Geheimnis nur bei Bezug;
- ein Einwilligungsvermerk ist kein Scheitern; ein ueberwundener Rueckzug schon;
- intent_kind (Absichtsart) macht keinen Netzaufruf, die Antwort kommt aus der Erlebensantwort.
Laeuft im tests/-Ordner des Stage-Produkts: MATRIX07_ROOT=<stage> python3 -m pytest <datei>
"""
import os
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = os.environ.get("MATRIX07_ROOT") or str(Path.cwd().parent if Path.cwd().name == "tests" else Path.cwd())
sys.path[:0] = [ROOT, str(Path(ROOT) / "tests")]

from matrix_api import kernel as K  # noqa: E402
from matrix_api import llm_contract as L  # noqa: E402

M = {"id": "m", "name": "Mara Nowak"}
J = {"id": "j", "name": "Johann Bruckner"}
A = {"id": "a", "name": "Alrik Stein"}
C = {"id": "c", "name": "Clara Mertens"}
ANN = {"id": "ann", "name": "Ann Weber"}
CAST = [M, J, A, C, ANN]


def session(runtime=None, facts=None):
    return {"id": "s", "scene": {"presentIds": ["m", "j"]}, "runtimes": {"m": runtime or {}}, "facts": facts or []}


def beleg(fid, text):
    return {"factId": fid, "dispositionsBeleg": text, "dispositionsQuelle": K.appraisal_source_id(text)}


class BriefAuswahl11F(unittest.TestCase):
    def test_wissen_ueber_jetzt_genannte_abwesende_person_bleibt(self):
        r = K._brief_auswahl(session(), {"knowledge": []}, "m", CAST, {},
                             ["Alrik ist in der Kapelle.", "Clara schützt das Haus.", "Johann zahlte."], "Wo ist Alrik?")
        self.assertIn("Alrik ist in der Kapelle.", r["wissen"])
        self.assertIn("Johann zahlte.", r["wissen"])          # anwesend
        self.assertNotIn("Clara schützt das Haus.", r["wissen"])   # nur Abwesende, jetzt nicht genannt

    def test_annette_bindet_nicht_ann(self):
        r = K._brief_auswahl(session(), {}, "m", CAST, {}, [], "Annette kommt gleich.")
        self.assertNotIn("ann", r["bezugIds"]); self.assertEqual(r["genannt"], [])
        r = K._brief_auswahl(session(), {}, "m", CAST, {}, [], "Ann kommt gleich.")
        self.assertIn("ann", r["bezugIds"])

    def test_aeltere_noch_wirkende_ursache_haelt_ihre_profilstelle(self):
        facts = [{"kind": "appraisal", "actorId": "m", "payload": {"kausalBelege": {"gefuehl": beleg("f1", "Obdachlosigkeit")}}}]
        facts += [{"kind": "appraisal", "actorId": "m", "payload": {"kausalBelege": {"gefuehl": beleg(f"f{i}", "Wärme")}}} for i in (2, 3, 4)]
        rt = {"affects": [{"type": "Angst", "causeFactId": "f1", "reinforcedBy": ["f1"]}]}
        s = session(rt, facts)
        sp = {"fears": ["Obdachlosigkeit", "Spinnen"], "likes": ["Wärme"], "values": ["Bindung"], "biography": "Lang."}
        r = K._brief_auswahl(s, sp, "m", CAST, rt, [], "")
        self.assertEqual(r["profil"]["fears"], ["Obdachlosigkeit"])      # belegt durch die noch wirkende Ursache f1
        self.assertEqual(r["profil"]["likes"], [])                        # f2-f4 wirken nicht mehr
        self.assertFalse(r["profil"]["offenerMoment"]); self.assertEqual(r["profil"]["values"], [])
        self.assertEqual(K._angesprochen(s, "m"), ["Obdachlosigkeit"])

    def test_offener_moment_werte_und_kurzer_lebenslauf_keine_unbelegte_angst(self):
        sp = {"fears": ["Spinnen"], "values": ["Bindung"], "biography": "X" * 600}
        r = K._brief_auswahl(session(), sp, "m", CAST, {}, [], "Hallo.")
        self.assertTrue(r["profil"]["offenerMoment"]); self.assertEqual(r["profil"]["values"], ["Bindung"])
        self.assertEqual(r["profil"]["fears"], []); self.assertEqual(len(r["profil"]["biography"]), 300)

    def test_geheimnis_nur_bei_bezug(self):
        sp = {"secrets": ["Johann schuldet ihr Geld.", "Sie war im Gefängnis."]}
        r = K._brief_auswahl(session(), sp, "m", CAST, {}, [], "")
        self.assertEqual(r["profil"]["ownSecrets"], ["Johann schuldet ihr Geld."])

    def _brief(self, dlg_extra):
        sp = {"profile": {"name": "Mara Nowak"}, "runtime": {"intent": "Abstand halten"}, "scene": {"present": ["Mara Nowak"]},
              "dialogue": [{"name": "Mara Nowak", "speech": "Lass das.", "action": "tritt zurück", "turn": 2, **dlg_extra}]}
        return L.render_persona_brief(sp, "", "", "")

    def test_einwilligungsvermerk_ist_kein_scheitern(self):
        b = self._brief({"actionOutcome": "gegen deine Ablehnung seit Turn 0", "consentNote": "gegen deine Ablehnung seit Turn 0"})
        self.assertNotIn("nicht gereicht", b); self.assertIn("du willst gerade: Abstand halten", b)
        b = self._brief({"actionOutcome": "Johann hat dich danach wieder erreicht (Turn 3: greift zu)", "actionOutcomeState": "overcome"})
        self.assertIn("aber es hat nicht gereicht: Johann hat dich danach wieder erreicht", b)

    def test_absichtsart_ohne_netzaufruf(self):
        L.vorab_leeren()
        L.vorab_registrieren([{"lesung": "absichtsart", "zu": "Abstand halten", "antwort": {"art": "handlung"}}])
        routing = {"allowed": True, "provider": "openai", "model": "gpt-4o-mini",
                   "endpoint": "https://api.openai.com/v1/chat/completions", "apiKey": "sk-TESTONLY"}
        with patch.object(L, "_routing", return_value=routing), patch.object(L, "_cfg", return_value={}), \
             patch.object(urllib.request, "urlopen", side_effect=AssertionError("kein Netzaufruf erlaubt")) as net:
            r = L.intent_kind(None, "admin", absicht="Abstand halten")
        self.assertEqual(r, {"art": "handlung"}); self.assertEqual(net.call_count, 0)


if __name__ == "__main__":
    unittest.main()
