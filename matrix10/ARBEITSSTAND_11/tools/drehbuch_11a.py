#!/usr/bin/env python3
"""Stand 11a: ein Drehbuch des Testmodells (Einzel-Lesungen je Regel bzw. Stand-11-Liste "lesungen") EINMAL in das Schema-Format
der ersten Antwort umwandeln - komponenten[].pruefung, teilstellen, sprache, namen, grenzumfang (Planer); pruefung (Formulierung);
Kausalnachweis in der Erlebensantwort (dynamisch "mit_kausal"). Die Antworten sind DIESELBEN Drehbuch-Antworten wie bisher.
Das Testmodell selbst ergaenzt nichts mehr - fehlt im Drehbuch ein Pflichtfeld, bleibt die Lesung unbestaetigt.
Aufruf: python3 -I drehbuch_11a.py <produktordner> <alt.json> <neu.json>
"""
from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys

HIER = Path(__file__).resolve().parent
TM = HIER.parents[1] / "ARBEITSSTAND_09" / "tools" / "testmodell_f1_09.py"

FELDER = ("vollzug", "komponentenart", "sprecher", "koerper", "koerperBestaetigung", "wirkung", "beruehrung", "bewegung",
          "bittebezug", "erlaubnisbezug", "grenzbezug")
# Feld -> (Stand-11-Lesung, Einzelregel)
QUELLE = {"vollzug": ("vollzug", "VOLLZUG_CHECK_RULES"), "komponentenart": ("komponentenart", "KOMPONENTENART_CHECK_RULES"),
          "sprecher": ("sprecher", "SPRECHER_CHECK_RULES"), "koerper": ("koerper", "KOERPER_CHECK_RULES"),
          "wirkung": ("wirkung", "EFFECT_CHECK_RULES"), "beruehrung": ("beruehrung", "TOUCH_CONFIRM_RULES"),
          "bewegung": ("bewegung", "MOVE_CHECK_RULES"), "bittebezug": ("bittebezug", "BITTEBEZUG_CHECK_RULES"),
          "erlaubnisbezug": ("erlaubnisbezug", "ERLAUBNISBEZUG_CHECK_RULES"), "grenzbezug": ("grenzbezug", "GRENZBEZUG_CHECK_RULES")}
ANTWORT_FELDER = ("koerper", "koerperBestaetigung", "wirkung", "beruehrung", "bewegung", "grenzumfang", "offenbarung")


def main() -> int:
    root, alt, neu = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    sys.argv = [str(TM), root, "0", "/dev/null", str(alt)]
    T = runpy.run_path(str(TM), run_name="testmodell")         # nur Funktionen; der Server startet nicht
    buch = json.loads(alt.read_text(encoding="utf-8"))
    ea = T["_eintrag_antwort"]
    LC = T["LC"]

    def nach_schema(wert, schema):
        """Nur die Felder des Schemas (ein striktes Modell kann keine anderen liefern)."""
        if "anyOf" in schema:
            objs = [x for x in schema["anyOf"] if x.get("type") == "object"]
            typ = wert.get("typ") if isinstance(wert, dict) else None
            schema = next((x for x in objs if typ in ((x.get("properties") or {}).get("typ") or {}).get("enum", [])), None) \
                or (objs[0] if objs and isinstance(wert, dict) else schema["anyOf"][-1] if wert is None else schema["anyOf"][0])
        if isinstance(wert, dict) and schema.get("type") == "object":
            return {k: nach_schema(wert.get(k), v) for k, v in schema["properties"].items()}
        if isinstance(wert, list) and schema.get("type") == "array":
            return [nach_schema(x, schema["items"]) for x in wert]
        if wert is None and schema.get("type") == "boolean":
            return False    # Feld der Einzelregel fehlte (z. B. versuch bei MOVE_CHECK): nicht bloss versucht
        return wert

    def aus_liste(les, name, zu, als_text):
        for l in les:
            if l.get("lesung") == name and str(l.get("zu") or "").strip() == str(zu or "").strip():
                return json.loads(l["antwort_json"]) if als_text and "antwort_json" in l else l.get("antwort")
        return None

    def pruefung(stelle, extra, text, figur, les, als_text=False):
        p = {"handlung": stelle, "segment": stelle, "worte": stelle, "aeusserung": text, "figur": figur, "akteur": figur, **extra}
        out = {}
        for f in FELDER:
            if f == "koerperBestaetigung":
                continue
            name, regel = QUELLE[f]
            a = aus_liste(les, name, stelle, als_text) if les is not None else ea(buch, regel, json.dumps(p, ensure_ascii=False))
            out[f] = a if isinstance(a, dict) else None
        kp = out.get("koerper")
        kb = None
        if isinstance(kp, dict) and kp.get("beleg") and (kp.get("haltung") or kp.get("schlaf")):
            kb = aus_liste(les, "koerper_bestaetigung", kp["beleg"], als_text) if les is not None else \
                ea(buch, "KOERPER_BESTAETIGUNG_RULES", json.dumps(dict(p, stelle=kp["beleg"], text=stelle), ensure_ascii=False))
        out["koerperBestaetigung"] = kb if isinstance(kb, dict) else None
        return out

    def plan(a, user_wenn):
        if not isinstance(a, dict) or "dynamisch" in a or "komponenten" not in a:
            return a
        les = a.pop("lesungen", None)
        text = " ".join(str(c.get("segment") or "") for c in a["komponenten"] if isinstance(c, dict))
        segs = []
        for c in a["komponenten"]:
            if isinstance(c, dict):
                c["pruefung"] = pruefung(str(c.get("segment") or ""), {"ziel": c.get("ziel"), "ansage": c.get("einleitung")}, text,
                                         str(c.get("akteur") or ""), les)
                segs.append(str(c.get("segment") or "").strip())
        teil = []
        for l in les or []:
            zu = str(l.get("zu") or "").strip()
            if l.get("lesung") in ("vollzug", "koerper", "wirkung") and zu and zu not in segs and zu not in [t["stelle"] for t in teil]:
                teil.append({"stelle": zu, "pruefung": pruefung(zu, {}, text, "", les)})
        a["teilstellen"] = teil
        sp = next((l.get("antwort") for l in les or [] if l.get("lesung") == "sprache"), None) if les is not None else \
            ea(buch, "LANGUAGE_RULES", json.dumps({"aeusserung": user_wenn}, ensure_ascii=False))
        a["sprache"] = sp if isinstance(sp, dict) else {"stellen": []}
        a["namen"] = []
        g = a.get("grenze") if isinstance(a.get("grenze"), dict) else None
        gu = None
        if g and g.get("beleg"):
            gu = next((l.get("antwort") for l in les or [] if l.get("lesung") == "grenzumfang"), None) if les is not None else \
                ea(buch, "GRENZE_CHECK_RULES", json.dumps({"beleg": g["beleg"]}, ensure_ascii=False))
        a["grenzumfang"] = gu if isinstance(gu, dict) else None
        for c in a["komponenten"]:
            # Pflichtfeld komponentenart: fehlte es im alten Drehbuch, antwortet das Drehbuch-Modell so, wie es die Komponente selbst
            # typisiert hat (eigene Handlung bzw. eigene Rede) - im Drehbuch sichtbar, nicht vom Testmodell ergaenzt
            if isinstance(c, dict) and not isinstance((c.get("pruefung") or {}).get("komponentenart"), dict):
                c["pruefung"]["komponentenart"] = {"art": c.get("typ"), "beleg": c.get("segment"),
                                                   "wirkung": c.get("wirkung") if c.get("typ") == "handlung" else None}
        a["komponenten"] = nach_schema(a["komponenten"], LC.PLAN_SCHEMA["properties"]["komponenten"])
        for t in a["teilstellen"]:
            t["pruefung"] = nach_schema(t["pruefung"], LC.P_HANDLUNG_PRUEFUNG)
        return a

    def formulierung(a):
        if not isinstance(a, dict) or "dynamisch" in a:
            return a
        les = a.pop("lesungen", None)
        act = str(a.get("action") or "").strip()
        pr = {f: None for f in ANTWORT_FELDER}
        if act:
            pp = pruefung(act, {}, " ".join(x for x in (str(a.get("speech") or ""), act) if x), "", les, als_text=True)
            pr.update({f: pp.get(f) for f in ("koerper", "koerperBestaetigung", "wirkung", "beruehrung", "bewegung")})
        g = a.get("grenze") if isinstance(a.get("grenze"), dict) else None
        if g and g.get("beleg"):
            gu = aus_liste(les, "grenzumfang", g["beleg"], True) if les is not None else \
                ea(buch, "GRENZE_CHECK_RULES", json.dumps({"beleg": g["beleg"]}, ensure_ascii=False))
            pr["grenzumfang"] = gu if isinstance(gu, dict) else None
        a["pruefung"] = nach_schema(pr, LC.P_ANTWORT_PRUEFUNG)
        a.setdefault("aussagen", [])
        a.setdefault("grenze", None)
        for x in a.get("aussagen") or []:
            if isinstance(x, dict):
                x.setdefault("lesung", None)
        return a

    def erleben(a):
        if not isinstance(a, dict):
            return a
        if "dynamisch" in a:   # erleben_mit_kausal / mit_kausal liefern den Nachweis neben jedem Wert (Stand 11B)
            return a
        if "kausalpruefung" in a:
            return a
        return {"dynamisch": "mit_kausal", "param": {"vorschlag": a}}

    def jede(eintrag, f, mit_wenn=False):
        if isinstance(eintrag, list):
            out = []
            for e in eintrag:
                if isinstance(e, dict) and "wenn" in e:
                    w = e["wenn"] if isinstance(e["wenn"], str) else " ".join(e["wenn"])
                    out.append({**e, "antwort": f(e["antwort"], w) if mit_wenn else f(e["antwort"])})
                else:
                    out.append(f(e, "") if mit_wenn else f(e))
            return out
        return f(eintrag, "") if mit_wenn else f(eintrag)

    if "PLAN_RULES" in buch:
        buch["PLAN_RULES"] = jede(buch["PLAN_RULES"], plan, mit_wenn=True)
    if "FORMULIERUNG" in buch:
        buch["FORMULIERUNG"] = jede(buch["FORMULIERUNG"], formulierung)
    if "APPRAISAL_RULES" in buch:
        buch["APPRAISAL_RULES"] = jede(buch["APPRAISAL_RULES"], erleben)
    buch["_stand"] = "11a: Lesungen als Pflichtfelder der ersten Antwort (umgewandelt mit drehbuch_11a.py aus " + alt.name + ")"
    neu.write_text(json.dumps(buch, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(neu)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
