"""Stand 12: Handlungsfaehigkeit (Live-Messung 09.11. mit gpt-4o-mini auf deiner Geraetesitzung, ARBEITSSTAND_12/BEFUND_STAND12.md).
- AutoChat-Zug ohne neuen Reiz (sie hat auf die letzte fremde Zeile schon geantwortet) -> "aus eigenem Antrieb" mit ihrer Absicht,
  nicht noch einmal dieselbe Zeile als "JETZT SAGT" (an 11F: rot);
- Erleben: kurzer Nachweis wird zu den Prueffeldern des Kernels aufgefaltet; ein woertliches Zitat aus Johanns REDE an der Kennung
  seiner HANDLUNG desselben Zuges gilt fuer die Rede (sonst verwarf der Kernel 9 von 13 Erlebensantworten teilweise);
  unbekannte Quelle -> kein Quelltext (der Kernel verwirft das Feld); bisherige Form: nur Kennung -> Fakt-ID;
- Eingabe: eine vom Modell erfundene Komponente (Worte nicht im Eingang) kippt eine vollstaendig gelesene Eingabe nicht mehr
  (Live: "Ach komm stell dich nicht so an" -> 422, nichts gespeichert); bleibt ein Rest, weiter Teilablehnung;
- Brief: auch fruehere eigene Zeilen sind als "schon gesagt/getan" markiert, nicht nur die letzte.
Laeuft im tests/-Ordner des Stage-Produkts: MATRIX07_ROOT=<stage> python3 -m pytest <datei>
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = os.environ.get("MATRIX07_ROOT") or str(Path.cwd().parent if Path.cwd().name == "tests" else Path.cwd())
sys.path[:0] = [ROOT, str(Path(ROOT) / "tests")]

from matrix_api import kernel as K  # noqa: E402
from matrix_api import llm_contract as L  # noqa: E402

M = {"id": "m", "name": "Mara Nowak"}
J = {"id": "j", "name": "Johann Bruckner"}


def fact(fid, actor, kind, text, turn, src):
    return {"id": fid, "kind": kind, "actorId": actor, "text": text, "turn": turn, "sourceTurnId": src, "authority": "kernel",
            "validated": True, "status": "validated", "witnessedBy": ["m", "j"]}


def sitzung(zeilen):
    facts, turns, wk = [], [], []
    for i, (wer, text) in enumerate(zeilen, 1):
        facts.append(fact(f"f{i}", wer["id"], "speech", text, i, f"t{i}"))
        turns.append({"turn": i, "role": "character", "speakerName": wer["name"], "speakerId": wer["id"], "speech": text})
        wk.append({"fact_id": f"f{i}", "character_id": "m", "access": "heard"})
    return {"id": "s", "turnIndex": len(zeilen), "scene": {"presentIds": ["m", "j"]},
            "runtimes": {"m": {"intent": "Johann zur Rede stellen"}}, "facts": facts, "turns": turns, "witnessKnowledge": wk}


def autochat_brief(s):
    t = {"id": "tx", "speaker_id": "m", "input_kind": "autochat", "input_actor_id": "user", "text": ""}
    sp = K.bind_formulation_spiegel(s, t, speaker=M, present=[M, J])
    return sp, L.render_persona_brief(sp, sp.get("userUtterance") or "", sp.get("utteredBy") or "", "")


class Eigenantrieb12(unittest.TestCase):
    def test_schon_beantwortete_zeile_ist_kein_neuer_reiz(self):
        sp, b = autochat_brief(sitzung([(J, "Ich hab gezahlt."), (M, "Lass mich in Ruhe.")]))
        self.assertEqual(sp.get("userUtterance"), "")
        self.assertNotIn('JETZT SAGT Johann Bruckner: "Ich hab gezahlt."', b)
        self.assertIn("aus eigenem Antrieb", b)
        self.assertIn("Johann zur Rede stellen", b)

    def test_neue_fremde_zeile_bleibt_reiz(self):
        sp, b = autochat_brief(sitzung([(M, "Lass mich in Ruhe."), (J, "Ich hab gezahlt.")]))
        self.assertEqual(sp.get("userUtterance"), "Ich hab gezahlt.")
        self.assertIn('JETZT SAGT Johann Bruckner: "Ich hab gezahlt."', b)
        self.assertNotIn("aus eigenem Antrieb", b)

    def test_fruehere_eigene_zeilen_markiert(self):
        _, b = autochat_brief(sitzung([(J, "Hey."), (M, "Lass das, Johann."), (J, "Ach komm."), (M, "Ich hab Arbeit."),
                                        (J, "Ich hab gezahlt.")]))
        zeilen = [z for z in b.splitlines() if z.startswith("- Mara Nowak:")]
        self.assertEqual(len(zeilen), 2)
        self.assertIn("schon gesagt/getan", zeilen[0])
        self.assertIn("dein letzter Beitrag", zeilen[1])


class TatMitEigenerWirkung12A(unittest.TestCase):
    """Stand 12A (Kettenkarte 12A Bruch 5a/5c/5d): Art und Nachweis einer Tat in EINEM Eintrag; je Tat eigene Lesungen."""

    def test_planer_rueckzug_mit_beleg_ergibt_bewegungslesung(self):
        p = {"komponenten": [{"typ": "handlung", "segment": "Ich trete einen Schritt von Johann zurück", "ziel": "Johann Bruckner",
                              "zeit": "jetzt", "wirkung": "entfernung", "geschieht": True, "wirkungBeleg": "trete einen Schritt von Johann zurück",
                              "versuch": False, "beruehrt": False, "beruehrungBeleg": None, "gegen": None,
                              "pruefung": {"vollzug": {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "figur", "ziel": "Johann Bruckner"}}}]}
        les = L.plan_lesungen(p, "Ich trete einen Schritt von Johann zurück")
        bew = [l for l in les if l["lesung"] == "bewegung"]
        self.assertEqual(len(bew), 1)
        self.assertEqual(bew[0]["zu"], "Ich trete einen Schritt von Johann zurück")
        self.assertTrue(bew[0]["antwort"]["bestaetigt"]); self.assertEqual(bew[0]["antwort"]["beleg"], "trete einen Schritt von Johann zurück")
        self.assertNotIn("wirkungBeleg", p["komponenten"][0])   # der Kernel sieht die Komponente wie bisher

    def test_ohne_beleg_keine_bestaetigung(self):
        les = L.wirkung_lesungen({"geschieht": True, "zeit": "jetzt", "wirkungBeleg": "", "versuch": False}, "tritt zurück", "entfernung")
        self.assertFalse(les[0]["antwort"]["bestaetigt"])

    def test_antwort_zwei_taten_je_eigene_lesungen(self):
        parsed = {"handlungen": [
            {"segment": "Ich stoße Johann von mir weg", "art": "gewalt", "ziel": "Johann Bruckner", "zeit": "jetzt", "geschieht": True,
             "wirkungBeleg": "stoße Johann von mir weg", "versuch": False, "beruehrt": True, "beruehrungBeleg": "stoße Johann", "gegen": None},
            {"segment": "trete zurück", "art": "entfernung", "ziel": "Johann Bruckner", "zeit": "jetzt", "geschieht": True,
             "wirkungBeleg": "trete zurück", "versuch": False, "beruehrt": False, "beruehrungBeleg": None, "gegen": None}]}
        les = L.antwort_lesungen(parsed, "", "Ich stoße Johann von mir weg und trete zurück.")
        self.assertEqual({(l["lesung"], l["zu"]) for l in les},
                         {("wirkung", "Ich stoße Johann von mir weg"), ("beruehrung", "Ich stoße Johann von mir weg"),
                          ("bewegung", "trete zurück"), ("bewegungsversuch", "trete zurück")})

    def test_kernel_uebernimmt_wirkung_je_komponente(self):
        res = {"speech": "Lass mich!", "action": "x", "components": [
            {"kind": "speech", "text": "Lass mich!"},
            {"kind": "action", "text": "Ich stoße Johann von mir weg", "wirkung": {"art": "gewalt", "ziel": "Johann Bruckner"}},
            {"kind": "action", "text": "trete zurück", "wirkung": {"art": "entfernung", "ziel": "Johann Bruckner"}}]}
        comps = K.split_output_components({"target_id": "j"}, res, M)
        self.assertEqual([c.get("wirkung", {}).get("art") for c in comps if c["kind"] == "action"], ["gewalt", "entfernung"])
        self.assertNotIn("wirkung", [c for c in comps if c["kind"] == "speech"][0])


class Eskalation12A(unittest.TestCase):
    """Stand 12A: die Szene eskaliert durch geschehene, bedrohliche Ausgaenge einer Tat - je Tat einmal."""

    def _s(self, eff):
        s = {"facts": [{"id": "f1", "kind": "action", "validated": True, "effect": eff}]}
        K._scene.ensure_state(s)["escalation"] = 0.1
        return s

    def test_beruehrung_gegen_ablehnung_und_ueberwundener_rueckzug(self):
        s = self._s({"effectKind": "social", "consent": {"state": "declined"}, "overcomes": ["w1"]})
        K._eskalation_aus_tat(s, "f1", 3)
        self.assertAlmostEqual(s["sceneState"]["escalation"], 0.35)
        K._eskalation_aus_tat(s, "f1", 3)   # dieselbe Tat nicht zweimal
        self.assertAlmostEqual(s["sceneState"]["escalation"], 0.35)

    def test_blockierte_tat_und_worte_eskalieren_nicht(self):
        s = self._s({"effectKind": "social", "consent": {"state": "declined"}, "outcome": "blocked"})
        K._eskalation_aus_tat(s, "f1", 3)
        self.assertAlmostEqual(s["sceneState"]["escalation"], 0.1)
        s = self._s({"effectKind": "social", "consent": {"state": "unknown"}})
        K._eskalation_aus_tat(s, "f1", 3)
        self.assertAlmostEqual(s["sceneState"]["escalation"], 0.1)


class ErfundeneKomponente12(unittest.TestCase):
    PLAN = {"event_kind": "claim", "komponenten": [
        {"typ": "rede", "segment": "Ach komm stell dich nicht so an", "akteur": "Johann Bruckner", "ziel": "Mara Nowak", "zeit": "jetzt",
         "wirkung": None, "bezug": None, "einleitung": None, "geschieht": None,
         "pruefung": {"komponentenart": {"art": "rede", "beleg": None, "wirkung": None},
                      "sprecher": {"sprecher": "Johann Bruckner", "beleg": None, "handlung": None, "adressat": "Mara Nowak",
                                   "ansageRolle": "sprecheransage", "ansageBeleg": None}}},
        {"typ": "handlung", "segment": "lehnt die Berührung ab", "akteur": "Johann Bruckner", "ziel": "Mara Nowak", "zeit": "jetzt",
         "wirkung": "ohne_koerperwirkung", "bezug": None, "einleitung": None, "geschieht": True, "pruefung": {}}]}

    def _lies(self, text, plan):
        return K.bind_puppet_input(text, plan, J, [J, M], ["j", "m"], addressee_id="m")

    def test_vollstaendig_gelesen_wird_gespeichert(self):
        r = self._lies("Ach komm stell dich nicht so an", self.PLAN)
        self.assertEqual(r.get("speech"), "Ach komm stell dich nicht so an")
        self.assertFalse(r.get("partial_rejection"))
        self.assertEqual(r.get("actions"), [])
        self.assertIn("segment_nicht_im_eingang", [a.get("grund") for a in r.get("ambiguous") or []])   # sichtbar

    def test_mit_rest_bleibt_teilablehnung(self):
        import copy
        p = copy.deepcopy(self.PLAN)
        p["komponenten"][0]["segment"] = "Ach komm"
        r = self._lies("Ach komm, ich fasse dir an den Hintern", p)
        self.assertTrue(r.get("partial_rejection"))


class ErlebenKurz12(unittest.TestCase):
    FIG = {"gerade_geschehen": [{"id": "fact_rede", "text": "Ich hab gezahlt, also hab ich ein Recht auf dich!"},
                                {"id": "fact_tat", "text": "tritt naeher und fixiert sie"}],
           "dispositionsquellen": [{"id": "Q1", "text": "Unter Bedrohung scharf und wachsam."}]}

    def _auf(self, nachweis):
        fig, kurz = L._erleben_kennungen(self.FIG)
        self.assertEqual([e["id"] for e in fig["gerade_geschehen"]], ["G1", "G2"])
        res = L._nachweise_auffalten({"gefuehl": "Wut", "gefuehl_nachweis": nachweis}, fig, kurz)
        return res["gefuehl_nachweis"]

    def test_andere_verweise_auf_das_ereignis_folgen_der_kennung(self):
        fig, _ = L._erleben_kennungen({**self.FIG, "beziehung_zum_handelnden": {"person": "Johann", "ereignis": "fact_tat"}})
        self.assertEqual(fig["beziehung_zum_handelnden"]["ereignis"], "G2")

    def test_kurzform_wird_aufgefaltet(self):
        n = self._auf({"urteil": "gestuetzt", "ereignis": "G1", "beleg": "ein Recht auf dich", "quelle": "Q1", "richtung": None,
                       "warum": "Besitzanspruch"})
        self.assertEqual(n["factId"], "fact_rede")
        self.assertEqual(n["dispositionsBeleg"], "Unter Bedrohung scharf und wachsam.")
        self.assertTrue(n["begruendung"].startswith('"Unter Bedrohung scharf und wachsam."'))

    def test_zitat_an_falscher_kennung_desselben_zuges(self):
        n = self._auf({"urteil": "gestuetzt", "ereignis": "G2", "beleg": "ein Recht auf dich", "quelle": "Q1", "richtung": None,
                       "warum": "x"})
        self.assertEqual(n["factId"], "fact_rede")

    def test_zitat_nirgends_bleibt_und_unbekannte_quelle_ohne_text(self):
        n = self._auf({"urteil": "gestuetzt", "ereignis": "G2", "beleg": "erfunden", "quelle": "Q9", "richtung": None, "warum": "x"})
        self.assertEqual(n["factId"], "fact_tat")
        self.assertEqual(n["dispositionsBeleg"], "")

    def test_bisherige_form_nur_kennung(self):
        n = self._auf({"urteil": "gestuetzt", "factId": "G2", "beleg": "tritt naeher", "dispositionsQuelle": "Q1",
                       "dispositionsBeleg": "scharf und wachsam", "richtung": None, "begruendung": '"scharf und wachsam" - x'})
        self.assertEqual(n["factId"], "fact_tat")
        self.assertEqual(n["dispositionsBeleg"], "scharf und wachsam")

    def test_schema_ist_kurz(self):
        self.assertEqual(set(L.P_NACHWEIS["properties"]), {"urteil", "ereignis", "beleg", "quelle", "richtung", "warum"})


if __name__ == "__main__":
    unittest.main()
