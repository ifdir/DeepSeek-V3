"""Stand 11a: die Fachlesungen sind PFLICHTFELDER der ersten Antwort (Befund Geraet 08.11. 20:51).

Auf dem Handy (gpt-4o-mini) fehlte in der Planer-Antwort die angehaengte freie Liste "lesungen" ganz - "Ich klatsche auf deinen
arsch" wurde zweimal abgewiesen (Vollzug/Wirkung ohne Lesung). Stand 11a: Schema mit Pflichtfeldern je Komponente, bei OpenAI
strikt erzwungen. Geprueft wird:
- der echte Request an api.openai.com traegt das strikte Schema (Planer, Formulierung, God, God-Koerper);
- die Schemas sind gueltige strikte Schemas (jedes Objekt: alle Schluessel Pflicht, keine Zusatzfelder);
- JEDE Lesung, die eine Lesestelle anfragen kann (ERSTE_ANTWORT_LESUNGEN), hat ein Pflichtfeld in einer ersten Antwort;
- Gegenprobe mit der WOERTLICHEN Geraeteantwort (ohne Pflichtfelder): keine Lesung, die Tat bleibt unbestaetigt (nichts geraten);
- dieselbe Antwort MIT Pflichtfeldern: Vollzug und Wirkung kommen an der Lesestelle an.
Laeuft im tests/-Ordner des Stage-Produkts: MATRIX07_ROOT=<stage> python3 -m pytest <datei>
"""
import io
import json
import os
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = os.environ.get("MATRIX07_ROOT") or str(Path.cwd().parent if Path.cwd().name == "tests" else Path.cwd())
sys.path[:0] = [ROOT, str(Path(ROOT) / "tests")]

from matrix_api import llm_contract as L  # noqa: E402

OPENAI = {"allowed": True, "provider": "openai", "model": "gpt-4o-mini", "endpoint": "https://api.openai.com/v1/chat/completions",
          "apiKey": "sk-TESTONLY", "keySource": "test", "providerChosen": "openai", "providerResolved": "openai"}

# woertlich: Rohantwort des Planers auf dem Geraet (Upload 34769ab5, logs, 19:53:08Z) fuer "Ich klatsche auf deinen arsch"
GERAET_PLAN = {"event_kind": "action", "speech_act": "act", "durability": "action_event",
               "summary": "Johann Bruckner klatscht auf den Arsch von Mara Nowak.", "subject": "Johann Bruckner", "predicate": "klatscht auf",
               "object": "den Arsch von Mara Nowak", "temporal": None, "refers_to": None, "cue_terms": [], "grenze": None, "verweis": None,
               "komponenten": [{"typ": "handlung", "segment": "Ich klatsche auf deinen arsch", "akteur": "Johann Bruckner", "ziel": "Mara Nowak",
                                "zeit": "jetzt", "wirkung": "gewalt", "bezug": None, "einleitung": None, "geschieht": True},
                               {"typ": "rede", "segment": "Ich klatsche auf deinen arsch", "akteur": "Johann Bruckner", "ziel": "Mara Nowak",
                                "zeit": "jetzt", "wirkung": None, "bezug": None, "einleitung": None}]}
TEXT = "Ich klatsche auf deinen arsch"


class Fang:
    """Faengt den Request ab und antwortet mit `antwort`."""
    def __init__(self, antwort):
        self.antwort, self.bodies = antwort, []

    def __call__(self, req, timeout=None):
        self.bodies.append(json.loads(req.data.decode()))
        content = json.dumps(self.antwort, ensure_ascii=False)
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode())


def strikt_gueltig(tc, schema, pfad="$"):
    if "anyOf" in schema:
        for s in schema["anyOf"]:
            strikt_gueltig(tc, s, pfad)
        return
    typ = schema.get("type")
    if typ == "object" or (isinstance(typ, list) and "object" in typ):
        props = schema.get("properties") or {}
        tc.assertIs(schema.get("additionalProperties"), False, pfad)
        tc.assertEqual(sorted(schema.get("required") or []), sorted(props), pfad)
        for k, v in props.items():
            strikt_gueltig(tc, v, f"{pfad}.{k}")
    if typ == "array" or (isinstance(typ, list) and "array" in typ):
        strikt_gueltig(tc, schema["items"], pfad + "[]")


def pruefung_mit(**werte):
    p = {k: None for k in L.P_HANDLUNG_PRUEFUNG["properties"]}
    p.update(werte)
    return p


# woertlich: Geraet 08.11. 21:58 (Upload 74b5e4f1, logs) - Erlebensantwort mit dem Nachweis als freie Liste: "aktivierung" statt
# "gefuehl", "absicht" fehlt -> beides wurde verworfen
GERAET_ERLEBEN_ALT = {"raum": "Angst", "aktivierung": 0.8, "gefuehl": "Bedrohung", "gegenueber": "Johann Bruckner",
                      "zustand_aenderung": {"angst": 0.3, "wut": 0, "scham": 0, "stress": 0, "lust": 0}, "absicht": "sich zurückziehen",
                      "vorher_absicht_erledigt": False,
                      "beziehung_aenderung": [{"zu": "Johann Bruckner", "trust": -0.3, "closeness": -0.3, "fear": 0.3}],
                      "kausalpruefung": {"pruefungen": [{"feld": "aktivierung", "urteil": "gestuetzt"}, {"feld": "zustand.angst", "urteil": "gestuetzt"}]}}


class ErsteAntwort11a(unittest.TestCase):
    def setUp(self):
        L.vorab_leeren()

    def test_openai_request_traegt_striktes_schema(self):
        f = Fang(dict(GERAET_PLAN))
        with patch.object(L, "_routing", return_value=OPENAI), patch.object(L, "_cfg", return_value={}), \
             patch.object(urllib.request, "urlopen", f):
            L.extract_turn_plan(None, "admin", TEXT, speaker_name="Johann Bruckner", recipient_name="Mara Nowak", puppet=True)
            L.god_body_state(None, "admin", text="Mara hat starke Schmerzen.", figure="Mara Nowak")
            L.extract_god_instructions(None, "admin", "Mara hat starke Schmerzen.", figures=["Mara Nowak"])
        rf = [b["response_format"] for b in f.bodies]
        self.assertEqual([(r["type"], r["json_schema"]["strict"]) for r in rf], [("json_schema", True)] * 3)
        self.assertEqual(rf[0]["json_schema"]["schema"], L.PLAN_SCHEMA)
        self.assertEqual(rf[1]["json_schema"]["schema"], L.GOD_BODY_SCHEMA)
        self.assertEqual(rf[2]["json_schema"]["schema"], L.GOD_SCHEMA)
        fm = L._formulation_format("gpt-4o-mini", OPENAI["endpoint"])
        self.assertEqual(fm["json_schema"]["schema"], L.FORMULATION_SCHEMA)
        self.assertIn("pruefung", L.FORMULATION_SCHEMA["required"])
        # anderer Provider: json_object, die Pflichtfelder stehen im Regeltext
        self.assertIsNone(L._strikt(dict(OPENAI, endpoint="http://127.0.0.1:5199/v1/chat/completions"), "x", L.PLAN_SCHEMA))
        self.assertIn('"pruefung"', L.PLAN_PRUEFUNG_RULES); self.assertIn('"teilstellen"', L.PLAN_PRUEFUNG_RULES)

    def test_schemas_sind_strikt_gueltig(self):
        for s in (L.PLAN_SCHEMA, L.FORMULATION_SCHEMA, L.GOD_SCHEMA, L.GOD_BODY_SCHEMA, L.APPRAISAL_SCHEMA):
            strikt_gueltig(self, s)
        rede, handlung = L.PLAN_SCHEMA["properties"]["komponenten"]["items"]["anyOf"]
        self.assertIn("pruefung", rede["required"]); self.assertIn("pruefung", handlung["required"])
        self.assertEqual(sorted(rede["properties"]["pruefung"]["required"]), ["komponentenart", "sprecher"])
        self.assertEqual(sorted(handlung["properties"]["pruefung"]["required"]),
                         sorted(["vollzug", "komponentenart", "koerper", "koerperBestaetigung", "wirkung", "beruehrung",
                                 "bewegung", "bittebezug", "erlaubnisbezug", "grenzbezug"]))
        # Stand 11B: Erleben - Nachweis neben jedem Wert, Pflicht
        a = L.APPRAISAL_SCHEMA
        self.assertTrue({"gefuehl_nachweis", "absicht_nachweis", "vorher_absicht_art"} <= set(a["required"]))
        self.assertIn("nachweis", a["properties"]["zustand_aenderung"]["items"]["required"])
        self.assertTrue({"trust_nachweis", "closeness_nachweis", "fear_nachweis"} <= set(a["properties"]["beziehung_aenderung"]["items"]["required"]))

    def test_jede_lesestelle_hat_ein_pflichtfeld(self):
        abgedeckt = set()
        for feld in list(L.P_HANDLUNG_PRUEFUNG["properties"]) + list(L.P_REDE_PRUEFUNG["properties"]):
            abgedeckt |= set(L._PRUEFUNG_LESUNG.get(feld, ()))
        abgedeckt |= {"koerper_bestaetigung"}                                                  # koerperBestaetigung
        abgedeckt |= {n for n in ("sprache", "namen", "grenzumfang") if n in L.PLAN_SCHEMA["required"]}
        for feld in L.P_ANTWORT_PRUEFUNG["properties"]:
            abgedeckt |= set(L._PRUEFUNG_LESUNG.get(feld, ()))
        a = L.FORMULATION_SCHEMA["properties"]["aussagen"]["items"]["properties"]["lesung"]["anyOf"][0]["properties"]
        abgedeckt |= {"aussage"} if "aussage" in a else set()
        abgedeckt |= {"aussage_tat"} if "taten" in a else set()
        self.assertIn("vorher_absicht_art", L.APPRAISAL_KAUSAL_IN_ERSTER_ANTWORT)
        abgedeckt |= {"absichtsart"}
        self.assertEqual(set(L.ERSTE_ANTWORT_LESUNGEN) - abgedeckt, set(), "Lesung ohne Pflichtfeld in einer ersten Antwort")

    def test_geraeteantwort_ohne_pflichtfelder_bleibt_unbestaetigt(self):
        p = json.loads(json.dumps(GERAET_PLAN))
        self.assertEqual(L.plan_lesungen(p, TEXT), [])
        L.vorab_registrieren([], quelle="test")
        self.assertIsNone(L._llm_json(OPENAI, L.VOLLZUG_CHECK_RULES, {"handlung": TEXT, "aeusserung": TEXT, "figur": "Johann Bruckner"}))
        self.assertIsNone(L._llm_json(OPENAI, L.EFFECT_CHECK_RULES, {"handlung": TEXT, "vorschlag": "gewalt"}))
        self.assertEqual([(a["lesung"], a["aus_erster_antwort"]) for a in L.vorab_abrufe()], [("vollzug", False), ("wirkung", False)])

    def test_dieselbe_antwort_mit_pflichtfeldern_kommt_an_der_lesestelle_an(self):
        p = json.loads(json.dumps(GERAET_PLAN))
        vz = {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "figur", "ziel": None}
        wk = {"bestaetigt": True, "zeit": "jetzt", "ziel": "Mara Nowak", "beleg": "klatsche auf deinen arsch", "versuch": False,
              "gegen": None, "beruehrung": False, "beruehrungBeleg": None}
        kp = {"haltung": "sitzend", "schlaf": None, "zeit": "jetzt", "beleg": "klatsche"}
        kb = {"art": "tatsaechlich", "inhalt": "gleich", "beleg": "klatsche"}
        p["komponenten"][0]["pruefung"] = pruefung_mit(vollzug=vz, wirkung=wk, koerper=kp, koerperBestaetigung=kb)
        p["komponenten"][1]["pruefung"] = {"komponentenart": None, "sprecher": None}
        p.update({"teilstellen": [], "sprache": {"stellen": []}, "namen": [], "grenzumfang": None})
        les = L.plan_lesungen(p, TEXT)
        self.assertNotIn("pruefung", p["komponenten"][0]); self.assertNotIn("teilstellen", p)
        L.vorab_registrieren(les, quelle="test")
        self.assertEqual(L._llm_json(OPENAI, L.VOLLZUG_CHECK_RULES, {"handlung": TEXT, "aeusserung": TEXT, "figur": "Johann Bruckner"}), vz)
        self.assertEqual(L._llm_json(OPENAI, L.EFFECT_CHECK_RULES, {"handlung": TEXT, "vorschlag": "gewalt"}), wk)
        self.assertEqual(L._llm_json(OPENAI, L.KOERPER_BESTAETIGUNG_RULES, {"text": TEXT, "stelle": "klatsche"}), kb)
        self.assertEqual(L._llm_json(OPENAI, L.SPRACHE_RULES if hasattr(L, "SPRACHE_RULES") else L.LANGUAGE_RULES,
                                     {"aeusserung": TEXT}), {"stellen": []})


    def test_erleben_nachweis_neben_dem_wert(self):
        from matrix_api import kernel as K
        # die woertliche Geraeteantwort (alte Form): gefuehl und absicht ohne Nachweis - bleibt so (Kernel verwirft beides)
        alt = L.erleben_aus_antwort(json.loads(json.dumps(GERAET_ERLEBEN_ALT)))
        self.assertNotIn("gefuehl", [p["feld"] for p in alt["kausalpruefung"]["pruefungen"]])
        # Schema-Form: jeder Wert traegt seinen Nachweis -> Felder exakt wie kernel.appraisal_effect_fields
        n = {"urteil": "gestuetzt", "factId": "f1", "beleg": "streiche", "dispositionsQuelle": "Q1", "dispositionsBeleg": "unter Bedrohung",
             "richtung": None, "begruendung": "x"}
        neu = {"raum": "Angst", "aktivierung": 0.8, "gefuehl": "Bedrohung", "gefuehl_nachweis": n, "gegenueber": "Johann Bruckner",
               "zustand_aenderung": [{"name": "angst", "wert": 0.3, "nachweis": dict(n, richtung="steigt")}], "absicht": "sich zurückziehen",
               "absicht_nachweis": n, "vorher_absicht_erledigt": False, "vorher_absicht_art": None,
               "beziehung_aenderung": [{"zu": "Johann Bruckner", "trust": -0.3, "trust_nachweis": dict(n, richtung="sinkt"), "closeness": 0,
                                        "closeness_nachweis": None, "fear": 0.3, "fear_nachweis": dict(n, richtung="steigt")}], "grund": "g"}
        o = L.erleben_aus_antwort(neu)
        self.assertEqual(sorted(p["feld"] for p in o["kausalpruefung"]["pruefungen"]), sorted(K.appraisal_effect_fields(o)))
        self.assertEqual(o["zustand_aenderung"], {"angst": 0.3})
        self.assertNotIn("trust_nachweis", o["beziehung_aenderung"][0])
        # ein Wert ohne Nachweis bekommt keinen Eintrag (Kernel verwirft nur ihn)
        o2 = L.erleben_aus_antwort(dict(neu, absicht_nachweis=None))
        self.assertNotIn("absicht", [p["feld"] for p in o2["kausalpruefung"]["pruefungen"]])


if __name__ == "__main__":
    unittest.main()
