"""V92 Puppet-Planvertrag (AMASTER §27.4, §24.2/§24.7): Offline, deterministisch, echte Route /api/kernel/puppet,
SQLite-Rücklesung, Provider nur als Double an der Modellgrenze (Live-Rohantwort vom 04.11.2026 wörtlich).
Kein Netz, kein echter Key, Nutzer-DB nicht berührt (frische Temp-DB)."""
import io, json, os, sys, tempfile, unittest, urllib.request
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import test_v84_kausal_chain  # noqa: F401  (offline Flask shim wie die übrigen Tests)
from matrix_api import kernel, llm_contract
from matrix_api.db import connect, init_schema
from matrix_api.seed_builtin import seed_if_missing
from matrix_api.repos import create_session, get_session

# wörtliche Live-Rohantwort (Turn 2, Diagnoselauf 04.11.2026): kein `komponenten`, Bitte mit umgekehrter Richtung
LIVE_T2_RAW = {"event_kind": "request", "speech_act": "request", "durability": "utterance",
               "summary": "Johann Bruckner bittet Mara Nowak, ihn auf die Schenkel zu greifen.", "subject": "Johann Bruckner",
               "predicate": "bittet", "object": "Mara Nowak, ihn auf die Schenkel zu greifen.",
               "temporal": {"text": "heute", "precision": "day", "wochentag": "mittwoch", "relativ": "heute", "in_tagen": 0, "datum": "2026-11-04", "uhrzeit": None},
               "refers_to": None, "cue_terms": [], "grenze": None, "verweis": None}


def comp(typ, seg, wirkung=None, geschieht=True):
    # V92 (Gegenpruefung 04.11.): the planner declares for every act whether it HAPPENS (`geschieht`); an act without it is unproven.
    c = {"typ": typ, "segment": seg, "akteur": "Johann Bruckner", "ziel": "Mara Nowak", "zeit": "jetzt", "wirkung": wirkung, "bezug": None}
    if typ == "handlung":
        c["geschieht"] = geschieht
        if geschieht is True:
            # binder-level tests hand the binder what the SERVER attaches after its own second reading (app._check_component_vollzug);
            # the route tests get it from FakeProvider (a reading the plan brings is stripped, see V92 Paket 6)
            c["vollzugPruefung"] = {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "figur"}
    return c


def plan(kind, act, comps, summary="x"):
    return {"event_kind": kind, "speech_act": act, "durability": "utterance", "summary": summary, "subject": "Johann Bruckner",
            "predicate": "x", "object": "y", "temporal": {"text": None, "precision": "unknown"}, "refers_to": None, "cue_terms": [],
            "grenze": None, "verweis": None, "komponenten": comps}


# Stand 11 (SPS V62.7): die Fachlesungen kommen aus der ersten Antwort. Welche Lesung an welcher Stelle angefragt wurde (und ob
# die erste Antwort sie enthielt) steht in llm_contract.vorab_abrufe() - je Anfrage. Damit die Pruefaussagen "die Lesung lief /
# ihre Nutzlast" wie frueher je Provider-Double gelten, sammelt das Double sie ueber alle Anfragen seiner Lebenszeit.
_AKTIV = [None]
_LEEREN = llm_contract.vorab_leeren


def _leeren_mit_archiv():
    if _AKTIV[0] is not None:
        _AKTIV[0].abrufe_liste.extend(llm_contract.vorab_abrufe())
    _LEEREN()


llm_contract.vorab_leeren = _leeren_mit_archiv


class FakeProvider:
    """Antwortet auf Planer-Aufrufe aus einer Warteschlange; alles andere neutral."""
    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def __init__(self, plans, vollzug=None, sprecher=None, wirkung=None, koerper=None, bestaetigung=None, gott=None, regie=None):
        self.plans, self.systems = list(plans), []
        _leeren_mit_archiv()                      # Abrufe frueherer Anfragen gehoeren dem frueheren Double
        self.abrufe_liste = []; _AKTIV[0] = self
        # V92 Paket 19: the confirmation reading at the quote (default: confirms exactly what it is asked, anchored at the quote),
        # the typed God/Regie body reading (default: nothing) and the Regie analysis (default: no component)
        self.bestaetigung = bestaetigung or (lambda payload: {"art": "tatsaechlich", "inhalt": "gleich", "beleg": payload.get("stelle")})
        self.gott = gott or (lambda payload: {})
        self.regie = regie or (lambda payload: {"komponenten": [], "unklar": []})
        # V92 Paket 18: blind reading of the change an act makes to the actor's own body; default "no change"
        self.koerper = koerper or (lambda payload: {"haltung": None, "schlaf": None, "zeit": "jetzt", "beleg": None})
        self.wirkung = wirkung or (lambda payload: {"bestaetigt": False, "zeit": "jetzt", "ziel": None, "beleg": None})
        # V92 Paket 12: blind speaker reading (only for announcements naming several figures); default "the figure itself"
        self.sprecher = sprecher or (lambda payload: {"sprecher": "figur", "beleg": None})
        # blind Vollzugslesung (V92 Gegenpruefung): default "geschieht tatsaechlich"; a test may pass a function(user_json)->dict
        self.vollzug = vollzug or (lambda payload: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "figur"})

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode()); system = body["messages"][0]["content"]; user = body["messages"][1]["content"]
        self.systems.append((system, user))
        if "Konjunktives Gedächtnis" in system:
            content = json.dumps(self.erste_antwort(self.plans.pop(0), user), ensure_ascii=False)
        elif system.startswith("Körperzustand durch die Spielleitung"):
            # Stand 11a: die Bestaetigung an der Belegstelle ist ein Feld derselben Antwort (frueher ein eigener Aufruf, gleiche Funktion)
            u = json.loads(user); ans = dict(self.gott(u))
            ans["bestaetigung"] = (self.bestaetigung(dict(u, stelle=ans["beleg"]))
                                   if isinstance(ans.get("beleg"), str) and ans["beleg"].strip() else None)
            content = json.dumps(ans, ensure_ascii=False)
        elif "Sprecher prüfen" in system:
            content = json.dumps(self.sprecher(json.loads(user)), ensure_ascii=False)
        elif "Vollzug prüfen" in system:
            content = json.dumps(self.vollzug(json.loads(user)), ensure_ascii=False)
        elif "Körperwirkung prüfen" in system or "Raumwirkung prüfen" in system:
            content = json.dumps(self.wirkung(json.loads(user)), ensure_ascii=False)
        elif "Eigener Körperzustand" in system:
            content = json.dumps(self.koerper(json.loads(user)), ensure_ascii=False)
        elif "Körperänderung bestätigen" in system:
            content = json.dumps(self.bestaetigung(json.loads(user)), ensure_ascii=False)
        elif "Körperzustand durch die Spielleitung" in system:
            content = json.dumps(self.gott(json.loads(user)), ensure_ascii=False)
        elif "Regie-Analyse" in system:
            content = json.dumps(self.regie(json.loads(user)), ensure_ascii=False)
        else:
            content = "{}"
        return self.R(json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode())

    # Stand 11a (SPS V62.7; nur die Aufrufstruktur ist angepasst): die Fachlesungen, die dieses Double frueher je auf einen EIGENEN
    # Aufruf beantwortete, liefert es jetzt in der ERSTEN Antwort als Pflichtfelder (PLAN_SCHEMA: komponenten[].pruefung,
    # teilstellen, sprache, grenzumfang) - mit DENSELBEN Antwortfunktionen dieses Tests, je Stelle der Eingabe. Was es frueher
    # neutral ("{}") beantwortete, beantwortet es auch hier neutral.
    PRUEF_FUNKTION = {"vollzug": "vollzug", "sprecher": "sprecher", "wirkung": "wirkung", "bewegung": "wirkung", "koerper": "koerper"}
    NEUTRAL = ("komponentenart", "beruehrung", "erlaubnisbezug", "bittebezug", "grenzbezug")

    def _pruefung(self, st, c, u, text):
        c = c or {}
        payload = {"handlung": st, "segment": st, "worte": st, "stelle": st, "beleg": st, "aeusserung": text,
                   "figur": c.get("akteur") or u.get("sprecher"), "akteur": c.get("akteur") or u.get("sprecher"),
                   "ziel": c.get("ziel"), "ansage": c.get("einleitung"), "typ": c.get("typ"), "kind": c.get("typ")}
        pr = {feld: getattr(self, fn)(payload) for feld, fn in self.PRUEF_FUNKTION.items()}
        pr.update({n: {} for n in self.NEUTRAL})
        kp = pr.get("koerper")
        pr["koerperBestaetigung"] = (self.bestaetigung(dict(payload, stelle=kp["beleg"]))
                                     if isinstance(kp, dict) and kp.get("beleg") else None)
        # Stand 11B: Pflichtfelder nach Komponententyp (PLAN_SCHEMA) - rede: komponentenart + sprecher; handlung: ohne sprecher
        if str(c.get("typ") or "") == "rede":
            return {k: pr[k] for k in ("komponentenart", "sprecher")}
        return {k: v for k, v in pr.items() if k != "sprecher"}

    def erste_antwort(self, pl, user):
        import re as _re
        if not isinstance(pl, dict):
            return pl
        try:
            u = json.loads(user)
        except ValueError:
            u = {}
        text = str(u.get("aeusserung") or "")
        pl = json.loads(json.dumps(pl))
        gesehen = []
        for c in pl.get("komponenten") or []:
            if isinstance(c, dict) and str(c.get("segment") or "").strip():
                c["pruefung"] = self._pruefung(str(c["segment"]).strip(), c, u, text)
                gesehen.append(str(c["segment"]).strip().strip("*").strip())
        teil = []
        def add(t, c=None):
            t = str(t or "").strip().strip("*").strip()
            if t and t not in gesehen:
                gesehen.append(t)
                teil.append({"stelle": t, "pruefung": self._pruefung(t, dict(c or {}, typ="handlung"), u, text)})   # Teilstelle = Tat
        for c in pl.get("komponenten") or []:
            if isinstance(c, dict) and c.get("einleitung"):
                add(c.get("einleitung"), c)
            if isinstance(c, dict):
                for t in _re.split(r"(?<=[.!?])\s+", str(c.get("segment") or "").strip()):
                    if t != str(c.get("segment") or "").strip():
                        add(t.rstrip(".")); add(t)
        for m in _re.finditer(r"\*([^*]+)\*", text):
            add(m.group(1))
            for t in _re.split(r"(?<=[.!?])\s+", m.group(1).strip()):
                add(t.rstrip(".")); add(t)
        pl["teilstellen"] = teil
        pl["sprache"] = {}
        pl["namen"] = []
        pl["grenzumfang"] = {} if isinstance(pl.get("grenze"), dict) else None
        return pl

    def abrufe(self, lesung, nur_beantwortet=True):
        """Stand 11: die Nutzlasten, mit denen die Lesestellen die Lesung `lesung` angefragt haben (aus der ersten Antwort)."""
        alle = self.abrufe_liste + (llm_contract.vorab_abrufe() if _AKTIV[0] is self else [])
        return [a["payload"] for a in alle if a["lesung"] == lesung and (a["aus_erster_antwort"] or not nur_beantwortet)]

    def planner_calls(self):
        return [(s, u) for s, u in self.systems if "Konjunktives Gedächtnis" in s]


def frage_merken(tc, sid, text, r):
    """V92 Paket 17: the identity questions a route issued for this input (session, text) - the UI answers them by their `frage`."""
    j = r.get_json(silent=True) or {}
    if r.status_code == 422 and j.get("code") == "IDENTITAET_KLAEREN":
        tc.__dict__.setdefault("_fragen", {})[(sid, text)] = list(j.get("klaerung") or [])
    return r


def als_antwort(tc, sid, text, klaerungen):
    """V92 Paket 17 (Paket-16-Pruefung A): a test's answer given by the written span becomes what the UI sends - the answer to the
    question the route issued for exactly this input ({"frage", "id"}). An answer without such a question stays as it is (the
    route then rejects it: KLAERUNG_UNGUELTIG)."""
    if not klaerungen:
        return klaerungen
    from matrix_api import kernel as _k
    fragen = (tc.__dict__.get("_fragen") or {}).get((sid, text)) or []
    out = []
    for k in klaerungen:
        if not isinstance(k, dict) or "frage" in k or "text" not in k:
            out.append(k)
            continue
        q = [x for x in fragen if _k._name_words(x.get("text")) == _k._name_words(k["text"])]
        out.append({"frage": q[0]["frage"], "id": k.get("id")} if len(q) == 1 else k)
    return out


class PuppetContract(unittest.TestCase):
    # ---- Binder-Vertrag (kernel.bind_puppet_input) ----
    def setUp(self):
        seed = json.loads((ROOT / "matrix_api/gasthaus_seed.json").read_text(encoding="utf-8"))
        by = {c["name"]: c for c in seed["characters"]}
        self.J = next(v for k, v in by.items() if "Johann" in k); self.M = next(v for k, v in by.items() if "Mara" in k)

    def bind(self, raw, pl):
        return kernel.bind_puppet_input(raw, pl, self.J, [self.J, self.M], [self.J["id"], self.M["id"]], addressee_id=self.M["id"])

    def test_plan_without_components_is_incomplete_not_speech(self):
        r = self.bind("Greife mara auf die schenkel", LIVE_T2_RAW)
        self.assertTrue(r.get("incomplete")); self.assertEqual(r["speech"], ""); self.assertEqual(r["actions"], [])
        self.assertEqual(r["ambiguous"][0]["grund"], "zerlegung_unvollstaendig")

    def test_empty_component_list_is_incomplete(self):
        self.assertTrue(self.bind("Hallo", dict(LIVE_T2_RAW, komponenten=[])).get("incomplete"))

    def test_real_speech_only_stays_speech(self):
        r = self.bind("Guten Morgen, Mara.", plan("smalltalk", "chat", [comp("rede", "Guten Morgen, Mara.")]))
        self.assertFalse(r.get("incomplete")); self.assertEqual(r["speech"], "Guten Morgen, Mara."); self.assertEqual(r["actions"], [])

    def test_real_request_as_spoken_words_stays_speech(self):
        r = self.bind("Komm bitte her.", plan("request", "request", [comp("rede", "Komm bitte her.")]))
        self.assertFalse(r.get("incomplete")); self.assertEqual(r["speech"], "Komm bitte her.")

    def test_act_only_and_mixed(self):
        a = self.bind("Greife mara auf die schenkel", plan("action", "act", [comp("handlung", "Greife mara auf die schenkel", "zaertlich")]))
        self.assertEqual(len(a["actions"]), 1); self.assertEqual(a["speech"], "")
        m = self.bind("Guten Morgen, ich greife nach Maras Arm", plan("action", "act", [comp("rede", "Guten Morgen"), comp("handlung", "ich greife nach Maras Arm", "ohne_koerperwirkung")]))
        self.assertEqual(m["speech"], "Guten Morgen"); self.assertEqual(len(m["actions"]), 1)

    def test_no_plan_is_not_relabelled_as_speech(self):                       # Paket-5-Pruefung D
        ids = [self.J["id"], self.M["id"]]
        r = kernel.bind_puppet_input("Johann küsst Mara nicht.", None, self.J, [self.J, self.M], ids, client_speech="Johann küsst Mara nicht.", client_action=None)
        self.assertTrue(r.get("incomplete")); self.assertEqual((r["speech"], r["actions"]), ("", [])); self.assertEqual([a["grund"] for a in r["ambiguous"]], ["plan_fehlt"])

    def test_no_plan_even_with_marker_or_action_field_is_unproven(self):      # Paket-6-Pruefung: Marker sagt nicht, dass es geschieht
        ids = [self.J["id"], self.M["id"]]
        for raw, sp, ac in (("Hallo *lächelt*", "Hallo", "lächelt"), ("Hallo", "Hallo", "nickt")):
            r = kernel.bind_puppet_input(raw, None, self.J, [self.J, self.M], ids, client_speech=sp, client_action=ac)
            self.assertTrue(r.get("incomplete"), raw); self.assertEqual((r["speech"], r["actions"]), ("", []))

    # ---- Planer-Nutzlast: Puppet-Kontext nur für Puppet, sonst bytegleich ----
    def test_puppet_context_only_for_puppet_other_readings_byte_identical(self):
        seen = {}
        def spy(routing, system, payload, **kw):
            seen["system"], seen["payload"] = system, payload; return None
        routing = {"allowed": True, "model": "m", "endpoint": "http://x", "apiKey": "k"}
        with patch.object(llm_contract, "_llm_json", spy), patch.object(llm_contract, "_routing", lambda d, c: routing), patch.object(llm_contract, "_cfg", lambda *a, **k: {}):
            llm_contract.extract_turn_plan(None, "admin", "Greife mara auf die schenkel", speaker_name="Johann Bruckner", recipient_name="Mara Nowak", puppet=True)
            self.assertIn("ZUSATZ PUPPET", seen["system"]); self.assertEqual(seen["payload"]["eingabeart"], "puppet")
            self.assertTrue(seen["system"].startswith(llm_contract.PLAN_RULES))
            llm_contract.extract_turn_plan(None, "admin", "Hallo", speaker_name="Alrik", recipient_name="Mara Nowak")
            # Stand 11 (nur Aufrufstruktur): an jeder Planer-Lesung haengen dieselben Lesungsregeln der ersten Antwort; der
            # Puppet-Zusatz bleibt allein der Puppet-Lesung
            self.assertEqual(seen["system"], llm_contract.PLAN_RULES + llm_contract.PLAN_PRUEFUNG_RULES); self.assertNotIn("eingabeart", seen["payload"])
            self.assertNotIn("ZUSATZ PUPPET", seen["system"])


class PuppetRouteChain(unittest.TestCase):
    """Echte Route, frische Temp-DB, Rücklesung aus SQLite, neue Verbindung = Neustart-Leser."""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(); self.addCleanup(self._tmp.cleanup)
        self.dbp = str(Path(self._tmp.name) / "t.sqlite")
        self._env = patch.dict(os.environ, {"MATRIX_DB": self.dbp, "MATRIX_LIVE_LOG": str(Path(self._tmp.name) / "log.log")}, clear=False)
        self._env.start(); self.addCleanup(self._env.stop)
        os.environ.pop("PYTEST_CURRENT_TEST", None); os.environ.pop("MATRIX_SKIP_SEED", None)
        with closing(connect(self.dbp)) as c:
            init_schema(c); seed_if_missing(c)
            c.execute("INSERT OR IGNORE INTO users(id,json) VALUES('admin','{\"id\":\"admin\"}')")
            c.execute("INSERT INTO config(scope,scope_id,json) VALUES(?,?,?)", ("user", "admin", json.dumps({"scope": "user", "scope_id": "admin", "provider": "openai", "model": "t", "apiKey": "sk-TESTONLY", "endpoint": "http://127.0.0.1:9/v1/chat/completions"})))
            ch = {json.loads(r[1])["name"]: json.loads(r[1]) for r in c.execute("select id,json from characters")}
            self.J = ch["Johann Bruckner"] if "Johann Bruckner" in ch else next(v for k, v in ch.items() if "Johann" in k)
            self.M = next(v for k, v in ch.items() if "Mara" in k)
            W = c.execute("select id from worlds limit 1").fetchone()[0]
            create_session(c, {"id": "ses_v92", "worldId": W, "name": "V92", "presentIds": [self.J["id"], self.M["id"]]}, "admin"); c.commit()
        from matrix_api import app as appmod
        self.client = appmod.create_app(self.dbp).test_client()

    def session(self):
        with closing(connect(self.dbp)) as c: return get_session(c, "admin", "ses_v92")

    def puppet(self, provider, text, klaerungen=None):
        klaerungen = als_antwort(self, "ses_v92", text, klaerungen)   # V92 Paket 17: answer the issued question, like the UI
        with patch.object(urllib.request, "urlopen", provider):
            return frage_merken(self, "ses_v92", text, self.client.post("/api/kernel/puppet", headers={"X-Matrix-Actor": "admin"}, json={
                "session": self.session(), "sessionId": "ses_v92", "actorUserId": "admin", "figure": {"id": self.J["id"], "name": self.J["name"]},
                "text": text, "targetId": self.M["id"], **({"klaerungen": klaerungen} if klaerungen is not None else {})}))

    def snapshot(self, s):
        return {k: json.dumps(s.get(k), sort_keys=True, ensure_ascii=False) for k in ("turns", "facts", "frames", "propositions", "turnTruths", "relations", "witnessKnowledge")} | {"turnIndex": s.get("turnIndex")}

    def test_live_t2_shape_commits_nothing_after_one_retry(self):
        before = self.snapshot(self.session())
        prov = FakeProvider([LIVE_T2_RAW, LIVE_T2_RAW])          # beide Lesungen unvollständig
        r = self.puppet(prov, "Greife mara auf die schenkel")
        self.assertEqual(r.status_code, 422); self.assertEqual((r.get_json() or {}).get("code"), "PLAN_INCOMPLETE")
        self.assertEqual(len(prov.planner_calls()), 2, "genau eine Wiederholung, kein weiterer Aufruf")
        after = self.session()
        self.assertEqual(self.snapshot(after), before, "SQLite unverändert: keine Rede, keine Handlung, keine Bitte")
        self.assertFalse([f for f in after.get("frames") or [] if f.get("kind") == "bitte"])
        self.assertFalse([p for p in after.get("propositions") or [] if "bittet" in json.dumps(p, ensure_ascii=False)])

    def test_retry_with_complete_reading_commits_act_without_request(self):
        prov = FakeProvider([LIVE_T2_RAW, plan("action", "act", [comp("handlung", "Greife mara auf die schenkel", "zaertlich")])])
        r = self.puppet(prov, "Greife mara auf die schenkel")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.session()                                          # neue Verbindung = Reader nach Neustart
        acts = [f for f in s["facts"] if f.get("kind") == "action" and f.get("actorId") == self.J["id"]]
        self.assertEqual(len(acts), 1); self.assertEqual(acts[0].get("targetId"), self.M["id"])
        self.assertEqual(acts[0].get("affected_ids"), [self.M["id"]], "Betroffene der Handlung = gebundenes Ziel (V92)")
        self.assertFalse([f for f in s.get("frames") or [] if f.get("kind") == "bitte"])
        self.assertEqual([t for t in s["turns"] if t.get("speakerId") == self.J["id"]][-1]["speech"], "")
        # die planausgelöste Bitte-Prüfung: Mara hört keine offene Bitte von Johann
        from matrix_api import conjunctive as _c
        self.assertFalse([f for f in _c.frames_for(s, self.M["id"]) if "bittet" in str(f.get("what"))])

    # ---- Gegenpruefung 04.11.2026 (Fall A/B) ueber die echte Route, SQLite-Rueckleseung ----
    def _act_comp(self, seg, geschieht=True, akteur="Johann Bruckner"):
        c = comp("handlung", seg, "zaertlich", geschieht); c["akteur"] = akteur; return c

    def test_negation_denied_by_independent_reading_commits_nothing(self):
        before = self.snapshot(self.session())
        # the planner is wrong (geschieht true); only the blind reading says "verneint"
        prov = FakeProvider([plan("action", "act", [self._act_comp("Johann küsst Mara nicht.")])],
                            vollzug=lambda payload: {"geschieht": False, "art": "verneint", "beleg": "nicht", "taeter": "figur"})
        r = self.puppet(prov, "Johann küsst Mara nicht.")
        self.assertEqual(r.status_code, 422); self.assertEqual((r.get_json() or {}).get("code"), "PUPPET_NICHT_AUSFUEHRBAR")
        self.assertIn("Nichts wurde gespeichert", (r.get_json() or {}).get("message", ""))
        self.assertEqual(self.snapshot(self.session()), before, "SQLite unveraendert: keine Handlung, keine Rede, kein Zug")

    # ---- Paket-5-Pruefung 04.11.2026 (Faelle A-E: fail-open) ueber die echte Route, SQLite-Rueckleseung ----
    def _nothing_committed(self, prov, text, plan_comps, code="PUPPET_NICHT_AUSFUEHRBAR", grund=None, klaerungen=None):
        before = self.snapshot(self.session())
        r = self.puppet(prov, text, klaerungen)
        self.assertEqual(r.status_code, 422, r.get_data(as_text=True)[:300]); self.assertEqual((r.get_json() or {}).get("code"), code)
        self.assertIn("Nichts wurde gespeichert", (r.get_json() or {}).get("message", ""))
        if grund:
            self.assertIn(grund, (r.get_json() or {}).get("message", "") + json.dumps(self.session().get("turnTruths", []), ensure_ascii=False))
        self.assertEqual(self.snapshot(self.session()), before, "SQLite unveraendert")
        return r

    def test_a_reading_unavailable_is_no_act(self):                        # A: Zweitlesung fehlt/ungueltig -> kein Akt, keine Rede
        for bad in (None, {}, {"geschieht": True}, "kaputt"):
            prov = FakeProvider([plan("action", "act", [self._act_comp("Johann küsst Mara nicht.")])], vollzug=lambda payload, b=bad: b)
            r = self._nothing_committed(prov, "Johann küsst Mara nicht.", None)
            self.assertIn("geprüft", (r.get_json() or {}).get("message", ""))

    def test_c_reading_without_doer_is_incomplete(self):                   # C: geschieht+art, aber kein taeter
        prov = FakeProvider([plan("action", "act", [self._act_comp("Johann nimmt Mara an der Hand.", akteur="Mara Nowak")])],
                            vollzug=lambda payload: {"geschieht": True, "art": "tatsaechlich", "beleg": None})
        self._nothing_committed(prov, "Johann nimmt Mara an der Hand.", None)
        prov = FakeProvider([plan("action", "act", [self._act_comp("Johann nimmt Mara an der Hand.")])],
                            vollzug=lambda payload: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "  "})
        self._nothing_committed(prov, "Johann nimmt Mara an der Hand.", None)

    def test_c_reading_names_a_foreign_doer(self):                         # Kontrolle: echte Zweitlesung nennt Mara als Taeterin
        prov = FakeProvider([plan("action", "act", [self._act_comp("Mara nimmt Johann an der Hand.")])],
                            vollzug=lambda payload: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "Mara Nowak"})
        self._nothing_committed(prov, "Mara nimmt Johann an der Hand.", None)

    def test_d_no_plan_is_not_stored_as_speech(self):                      # D: Planer faellt aus -> nichts, keine Umdeutung zu Rede
        prov = FakeProvider([])                                            # leere Warteschlange: der Planeraufruf scheitert
        self._nothing_committed(prov, "Johann küsst Mara nicht.", None, code="PLAN_INCOMPLETE")

    def test_e_planner_supplied_reading_is_not_the_servers(self):          # E: Reviewer-Feld vom Planer + Ausfall der echten Lesung
        c = self._act_comp("Johann küsst Mara nicht."); c["vollzugPruefung"] = {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "figur"}
        prov = FakeProvider([plan("action", "act", [c])], vollzug=lambda payload: None)
        self._nothing_committed(prov, "Johann küsst Mara nicht.", None)
        c2 = self._act_comp("Johann küsst Mara nicht.", geschieht=True); c2["vollzugPruefung"] = {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "figur"}
        prov = FakeProvider([plan("action", "act", [c2])], vollzug=lambda payload: {"geschieht": False, "art": "verneint", "beleg": "nicht", "taeter": "figur"})
        self._nothing_committed(prov, "Johann küsst Mara nicht.", None)           # die echte Lesung entscheidet, nicht das Planerfeld

    def test_positive_complete_reading_still_commits(self):                # Kontrolle: vollstaendige Lesung, Taeter "figur" und Taeter = Figurname
        for t in ("figur", "Johann Bruckner", "Johann"):
            prov = FakeProvider([plan("action", "act", [self._act_comp("Johann streichelt Mara")])],
                                vollzug=lambda payload, t=t: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": t})
            r = self.puppet(prov, "Johann streichelt Mara")
            self.assertEqual(r.status_code, 200, (t, r.get_data(as_text=True)[:300]))
        s = self.session()
        self.assertEqual(len([f for f in s["facts"] if f.get("kind") == "action" and f.get("actorId") == self.J["id"]]), 3)

    def test_p6_marker_does_not_bypass_the_second_reading(self):          # Paket-6-Pruefung: *...* ueber die echte Route
        prov = FakeProvider([plan("action", "act", [self._act_comp("Johann küsst Mara nicht.")])],
                            vollzug=lambda payload: {"geschieht": False, "art": "verneint", "beleg": "nicht", "taeter": "figur"})
        self._nothing_committed(prov, "*Johann küsst Mara nicht.*", None)
        prov = FakeProvider([plan("action", "act", [self._act_comp("Johann nimmt Mara an der Hand.")])],
                            vollzug=lambda payload: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "Mara Nowak"})
        self._nothing_committed(prov, "*Johann nimmt Mara an der Hand.*", None)

    def test_p6_unknown_component_type_stores_nothing(self):
        bad = {"typ": "request", "segment": "Greife Mara auf die Schenkel.", "akteur": "Johann Bruckner"}
        self._nothing_committed(FakeProvider([plan("request", "ask", [bad]), plan("request", "ask", [bad])]), "Greife Mara auf die Schenkel.", None, code="PLAN_INCOMPLETE")

    def test_p8_pure_foreign_speech_stores_nothing(self):                   # Paket-8-Pruefung C5 ueber die echte Route
        foreign = dict(comp("rede", "Lass mich in Ruhe!"), akteur="Mara Nowak", einleitung="Mara sagt:")
        r = self._nothing_committed(FakeProvider([plan("smalltalk", "chat", [foreign])]), "Mara sagt: Lass mich in Ruhe!", None)
        self.assertIn("andere", (r.get_json() or {}).get("message", ""))

    def test_p9_bare_marker_left_out_by_the_planner(self):                 # Paket 9 ueber die Puppet-Route
        r = self.puppet(FakeProvider([plan("smalltalk", "chat", [dict(comp("rede", "Hallo Mara."))])]), "*nickt* Hallo Mara.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.session(); mine = [t for t in s["turns"] if t.get("speakerId") == self.J["id"]][-1]
        self.assertEqual((mine["speech"], mine["action"]), ("Hallo Mara.", "nickt"))

    def test_p10_partial_and_multiple_markers_over_the_route(self):        # Paket-9-Pruefung P9-01/P9-02, Puppet-Route
        r = self.puppet(FakeProvider([plan("action", "act", [self._act_comp("Johann lächelt")])]), "*Johann lächelt. Johann küsst Mara nicht.*")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        acts = lambda: [f["text"] for f in self.session()["facts"] if f.get("kind") == "action" and f.get("actorId") == self.J["id"]]
        self.assertEqual(acts(), ["Johann lächelt"])
        r = self.puppet(FakeProvider([plan("action", "act", [self._act_comp("Johann lächelt"), self._act_comp("Johann winkt")])]), "*Johann lächelt.* *Johann winkt.*")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(acts(), ["Johann lächelt", "Johann lächelt", "Johann winkt"])

    def test_p11_two_figures_called_johann_over_the_route(self):           # Paket-10-Pruefung, echte Route + SQLite
        with closing(connect(self.dbp)) as c:
            jrow = c.execute("select world_id, owner_user_id, json from characters where id=?", (self.J["id"],)).fetchone()
            w = dict(json.loads(jrow[2])); w["id"] = "char_test_johann_weber"; w["name"] = "Johann Weber"; w["aliases"] = []
            c.execute("INSERT INTO characters(id, world_id, owner_user_id, json) VALUES(?,?,?,?)", (w["id"], jrow[0], jrow[1], json.dumps(w, ensure_ascii=False)))
            create_session(c, {"id": "ses_jj", "worldId": jrow[0], "name": "JJ", "presentIds": [self.J["id"], self.M["id"], w["id"]]}, "admin"); c.commit()
        def run(text, comp, taeter):
            with closing(connect(self.dbp)) as c: before = get_session(c, "admin", "ses_jj")
            prov = FakeProvider([plan("action", "act", [comp])], vollzug=lambda p: {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": taeter})
            with patch.object(urllib.request, "urlopen", prov):
                r = self.client.post("/api/kernel/puppet", headers={"X-Matrix-Actor": "admin"}, json={
                    "session": before, "sessionId": "ses_jj", "actorUserId": "admin", "figure": {"id": self.J["id"], "name": self.J["name"]},
                    "text": text, "targetId": self.M["id"]})
            with closing(connect(self.dbp)) as c: after = get_session(c, "admin", "ses_jj")
            return r, before, after
        self.assertIn("char_test_johann_weber", run("Hallo.", comp("rede", "Hallo."), "figur")[2]["scene"]["presentIds"])
        for text, comp_, taeter in (("Johann Weber winkt.", dict(self._act_comp("Johann Weber winkt"), akteur="Johann Weber"), "Johann Weber"),
                                    ("Johann winkt.", dict(self._act_comp("Johann winkt"), akteur="Johann"), "Johann")):
            r, before, after = run(text, comp_, taeter)
            self.assertEqual(r.status_code, 422, (text, r.get_data(as_text=True)[:200]))
            self.assertEqual(self.snapshot(after), self.snapshot(before), text)
        r, before, after = run("Johann Bruckner winkt.", dict(self._act_comp("Johann Bruckner winkt")), "Johann Bruckner")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        self.assertIn("Johann Bruckner winkt", [f["text"] for f in after["facts"] if f.get("kind") == "action" and f.get("actorId") == self.J["id"]])

    # ---- Paket-11-Pruefung: Sprecherrolle, Zielidentitaet, vollstaendige Verarbeitung - ueber die echte Route + SQLite ----
    def test_p12_speaker_role_is_read_when_the_announcement_names_two_figures(self):
        rede_ = dict(comp("rede", "Lass mich in Ruhe!"), einleitung="Mara sagt zu Johann:")          # planner: speaker Johann (wrong)
        prov = FakeProvider([plan("smalltalk", "chat", [rede_])], sprecher=lambda p: {"sprecher": "Mara Nowak", "beleg": "Mara sagt"})
        self._nothing_committed(prov, "Mara sagt zu Johann: Lass mich in Ruhe!", None)
        self.assertTrue(prov.abrufe("sprecher"), "the speaker reading ran (Stand 11: aus der ersten Antwort)")
        own = dict(comp("rede", "Komm her."), einleitung="Johann sagt zu Mara:")
        r = self.puppet(FakeProvider([plan("smalltalk", "chat", [own])]), "Johann sagt zu Mara: Komm her.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual([t for t in self.session()["turns"] if t.get("speakerId") == self.J["id"]][-1]["speech"], "Komm her.")

    def test_p12_two_acts_in_one_component_are_both_read_and_stored(self):
        compound = self._act_comp("Johann lächelt. Johann winkt.")
        prov = FakeProvider([plan("action", "act", [compound])])
        r = self.puppet(prov, "*Johann lächelt. Johann winkt.*")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        acts = [f["text"].rstrip(".") for f in self.session()["facts"] if f.get("kind") == "action" and f.get("actorId") == self.J["id"]]
        self.assertEqual(acts, ["Johann lächelt", "Johann winkt"])
        self.assertEqual(sorted(p["handlung"].rstrip(".") for p in prov.abrufe("vollzug")), ["Johann lächelt", "Johann winkt"], "one reading per sentence")
        # one part denied by its own reading: only the other part is stored
        prov = FakeProvider([plan("action", "act", [self._act_comp("Johann lächelt. Johann küsst Mara nicht.")])],
                            vollzug=lambda p: ({"geschieht": False, "art": "verneint", "beleg": "nicht", "taeter": "figur"} if "nicht" in p.get("handlung", "")
                                               else {"geschieht": True, "art": "tatsaechlich", "beleg": None, "taeter": "figur"}))
        r = self.puppet(prov, "*Johann lächelt. Johann küsst Mara nicht.*")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        acts = [f["text"].rstrip(".") for f in self.session()["facts"] if f.get("kind") == "action" and f.get("actorId") == self.J["id"]]
        self.assertEqual(acts, ["Johann lächelt", "Johann winkt", "Johann lächelt"])

    def test_p12_two_figures_called_mara_target_and_body_chain(self):
        with closing(connect(self.dbp)) as c:
            jrow = c.execute("select world_id, owner_user_id, json from characters where id=?", (self.M["id"],)).fetchone()
            w = dict(json.loads(jrow[2])); w["id"] = "char_test_mara_schmidt"; w["name"] = "Mara Schmidt"; w["aliases"] = []
            c.execute("INSERT INTO characters(id, world_id, owner_user_id, json) VALUES(?,?,?,?)", (w["id"], jrow[0], jrow[1], json.dumps(w, ensure_ascii=False)))
            create_session(c, {"id": "ses_mm", "worldId": jrow[0], "name": "MM", "presentIds": [self.J["id"], self.M["id"], w["id"]]}, "admin"); c.commit()
        def run(text, comp_, wirkung=None, klaerungen=None):
            with closing(connect(self.dbp)) as c: before = get_session(c, "admin", "ses_mm")
            prov = FakeProvider([plan("action", "act", [comp_])], wirkung=wirkung)
            klaerungen = als_antwort(self, "ses_mm", text, klaerungen)
            with patch.object(urllib.request, "urlopen", prov):
                r = frage_merken(self, "ses_mm", text, self.client.post("/api/kernel/puppet", headers={"X-Matrix-Actor": "admin"}, json={
                    "session": before, "sessionId": "ses_mm", "actorUserId": "admin", "figure": {"id": self.J["id"], "name": self.J["name"]},
                    "text": text, "targetId": self.M["id"], **({"klaerungen": klaerungen} if klaerungen is not None else {})}))
            with closing(connect(self.dbp)) as c: return r, get_session(c, "admin", "ses_mm")
        # V92 Paket 16 (Paket-15-Pruefung): two Maras - nothing is bound, the operator is asked BEFORE anything is stored
        with closing(connect(self.dbp)) as c: n0 = len(get_session(c, "admin", "ses_mm")["facts"])
        r, s = run("Johann berührt Mara.", dict(self._act_comp("Johann berührt Mara"), ziel="Mara"))
        self.assertEqual((r.status_code, r.get_json()["code"]), (422, "IDENTITAET_KLAEREN"), r.get_data(as_text=True)[:300])
        self.assertEqual([(q["text"], sorted(x["id"] for x in q["kandidaten"])) for q in r.get_json()["klaerung"]],
                         [("Mara", sorted([self.M["id"], "char_test_mara_schmidt"]))])
        self.assertEqual(len(s["facts"]), n0, "nothing stored before the answer")
        r, s = run("Johann berührt Mara.", dict(self._act_comp("Johann berührt Mara"), ziel="Mara"), klaerungen=[{"text": "Mara", "id": None}])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertIsNone([f for f in s["facts"] if f.get("kind") == "action"][-1].get("targetId"), "two Maras, answered 'nobody': no target")
        # V92 Paket 17 (Paket-16-Pruefung C): the question of the first try belongs to the state before the stored turn - a stale
        # answer is rejected (nothing stored); the same input is asked again and the new question is answered
        r, s1 = run("Johann berührt Mara.", dict(self._act_comp("Johann berührt Mara"), ziel="Mara"), klaerungen=[{"frage": self._fragen[("ses_mm", "Johann berührt Mara.")][0]["frage"], "id": "char_test_mara_schmidt"}])
        self.assertEqual((r.status_code, r.get_json()["code"], r.get_json()["grund"]), (422, "KLAERUNG_UNGUELTIG", "andere_eingabe"))
        self.assertEqual(len(s1["facts"]), len(s["facts"]), "stale answer: nothing stored")
        r, s = run("Johann berührt Mara.", dict(self._act_comp("Johann berührt Mara"), ziel="Mara"))
        self.assertEqual((r.status_code, r.get_json()["code"]), (422, "IDENTITAET_KLAEREN"))
        r, s = run("Johann berührt Mara.", dict(self._act_comp("Johann berührt Mara"), ziel="Mara"), klaerungen=[{"text": "Mara", "id": "char_test_mara_schmidt"}])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual([f for f in s["facts"] if f.get("kind") == "action"][-1].get("targetId"), "char_test_mara_schmidt", "the operator's answer binds")
        pain = lambda s_, fid: float(((s_.get("runtimes") or {}).get(fid) or {}).get("pain") or 0)
        ok_effect = lambda p: {"bestaetigt": True, "zeit": "jetzt", "ziel": p.get("ziel"), "beleg": "schubst"}
        with closing(connect(self.dbp)) as c: s0 = get_session(c, "admin", "ses_mm")
        r, s = run("Johann schubst Mara Schmidt.", dict(self._act_comp("Johann schubst Mara Schmidt"), ziel="Mara Nowak", wirkung="gewalt"), ok_effect)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        last = [f for f in s["facts"] if f.get("kind") == "action"][-1]
        self.assertIsNone(last.get("targetId"), "the reading's wrong target is not taken")
        self.assertEqual((pain(s, self.M["id"]), pain(s, "char_test_mara_schmidt")), (pain(s0, self.M["id"]), pain(s0, "char_test_mara_schmidt")), "no body changed")
        r, s2 = run("Johann schubst Mara Schmidt.", dict(self._act_comp("Johann schubst Mara Schmidt"), ziel="Mara Schmidt", wirkung="gewalt"), ok_effect)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        last = [f for f in s2["facts"] if f.get("kind") == "action"][-1]
        self.assertEqual(last.get("targetId"), "char_test_mara_schmidt")
        self.assertEqual(pain(s2, self.M["id"]), pain(s0, self.M["id"]), "Mara Nowak's body untouched")
        self.assertGreater(pain(s2, "char_test_mara_schmidt"), pain(s0, "char_test_mara_schmidt"), "Mara Schmidt's body carries the push")
        phys = [f for f in s2["facts"] if f.get("kind") == "physical"]
        self.assertTrue(phys and {f.get("targetId") for f in phys} == {"char_test_mara_schmidt"}, phys)

    def test_foreign_actor_is_rejected_not_spoken(self):
        before = self.snapshot(self.session())
        prov = FakeProvider([plan("action", "act", [self._act_comp("Johann nimmt Mara an der Hand.", akteur="Mara Nowak")])])   # Mara ist der Akteur, Johann gefuehrt
        r = self.puppet(prov, "Johann nimmt Mara an der Hand.")
        self.assertEqual(r.status_code, 422); self.assertEqual((r.get_json() or {}).get("code"), "PUPPET_NICHT_AUSFUEHRBAR")
        self.assertEqual(self.snapshot(self.session()), before)

    def test_negation_as_speech_is_stored_as_speech_without_action(self):
        prov = FakeProvider([plan("smalltalk", "chat", [dict(comp("rede", "Ich küsse Mara nicht."), einleitung="Johann sagt:")])])
        r = self.puppet(prov, 'Johann sagt: "Ich küsse Mara nicht."')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.session(); mine = [t for t in s["turns"] if t.get("speakerId") == self.J["id"]][-1]
        self.assertIn("küsse Mara nicht", mine["speech"]); self.assertIsNone(mine["action"])
        self.assertFalse([f for f in s["facts"] if f.get("kind") == "action" and f.get("actorId") == self.J["id"]])

    def test_denied_act_with_real_speech_stores_only_the_speech(self):
        prov = FakeProvider([plan("action", "act", [self._act_comp("Johann küsst Mara nicht", geschieht=False), dict(comp("rede", "Hallo."), einleitung="sagt:")])])
        r = self.puppet(prov, "Johann küsst Mara nicht und sagt: Hallo.")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        s = self.session(); mine = [t for t in s["turns"] if t.get("speakerId") == self.J["id"]][-1]
        self.assertEqual(mine["speech"].rstrip("."), "Hallo"); self.assertIsNone(mine["action"])
        self.assertFalse([f for f in s["facts"] if f.get("kind") == "action" and f.get("actorId") == self.J["id"]])
        amb = [a.get("grund") for tt in s.get("turnTruths", []) for a in (tt.get("input_component_ambiguity") or [])]
        self.assertIn("handlung_nicht_vollzogen", amb, "die verworfene Handlung bleibt als Hinweis sichtbar")

    def test_pure_speech_mixed_and_follow_up_turns_keep_working(self):
        prov = FakeProvider([plan("smalltalk", "chat", [comp("rede", "Guten Morgen, Mara.")], "Johann grüßt Mara."),
                             plan("action", "act", [comp("rede", "Komm her"), comp("handlung", "ich nehme deine Hand", "zaertlich")], "Johann sagt: Komm her."),
                             plan("action", "act", [comp("handlung", "Streiche mara über den arsch", "zaertlich")])])
        for t in ("Guten Morgen, Mara.", "Komm her, ich nehme deine Hand", "Streiche mara über den arsch"):
            r = self.puppet(prov, t); self.assertEqual(r.status_code, 200, (t, r.get_data(as_text=True)[:200]))
        s = self.session(); mine = [t for t in s["turns"] if t.get("speakerId") == self.J["id"]]
        self.assertEqual(mine[0]["speech"], "Guten Morgen, Mara."); self.assertIsNone(mine[0]["action"])
        self.assertEqual(mine[1]["speech"], "Komm her"); self.assertTrue(mine[1]["action"])
        self.assertEqual(mine[2]["speech"], ""); self.assertTrue(mine[2]["action"])
        self.assertEqual(s["turnIndex"], 3)
        self.assertEqual(len(prov.planner_calls()), 3, "vollständige Lesungen: kein Wiederholungsaufruf")
        for sys_, user in prov.planner_calls():
            self.assertIn("ZUSATZ PUPPET", sys_); self.assertEqual(json.loads(user)["eingabeart"], "puppet")


if __name__ == "__main__":
    unittest.main()
