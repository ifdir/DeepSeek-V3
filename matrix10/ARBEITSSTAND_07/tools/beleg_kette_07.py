"""Stand 07 / K-01: Figurenantwort fuer Pruefwerkzeuge ueber den echten Produktweg statt als Client-Text.

Die 06-Proben schickten die Figurenantwort ("Hallo Johann.", "Mara streichelt Johann") direkt an /api/kernel/commit.
Nach K-01 nimmt commit nur die Formulierung, die der Server fuer diesen Turn erzeugt hat. Diese Hilfe geht deshalb den
Weg der Oberflaeche: prepare (Wiederaufnahme der offenen Eingabe, UI "Antwort erneut erzeugen", V65U) -> /api/llm/formulate
-> commit mit Turn- und Formulierungsbeleg. Das Modell wird wie in 06 nur als Transport ersetzt (P25-FakeProvider + eine
Antwort auf genau den Formulierungs-Prompt); Server, Kern, SQLite und Rust laufen echt.
"""
from __future__ import annotations

import json
from contextlib import closing
import urllib.request
from unittest.mock import patch

FORMULIER_MARKE = "Formuliere, was die gebundene Figur jetzt sagt"


def formulier_provider(FakeProvider, formulierung: dict, **kw):
    class _P(FakeProvider):
        def __call__(self, req, timeout=None):
            body = json.loads(req.data.decode())
            system = body["messages"][0]["content"]
            if FORMULIER_MARKE in system:
                self.systems.append((system, body["messages"][1]["content"]))
                content = json.dumps(formulierung, ensure_ascii=False)
                return self.R(json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode())
            return super().__call__(req, timeout)
    return _P([], **kw)


def offene_turntruth(connect, dbp, sid):
    with closing(connect(dbp)) as c:
        env = json.loads(c.execute("SELECT json FROM sessions WHERE id=?", (sid,)).fetchone()[0])
        pend = str(env.get("pendingInputTurnId") or "")
        tt = next((json.loads(j) for (j,) in c.execute("SELECT json FROM turn_truth WHERE session_id=?", (sid,))
                   if json.loads(j).get("id") == pend), None)
    return pend, tt


def belege_holen(cl, H, *, connect, dbp, sid, speaker, truth_fn, formulierung, FakeProvider, trace="k01"):
    """prepare (Wiederaufnahme) + formulate. Liefert {"pj","fj"} oder die erste nicht-200-Antwort."""
    pend, tt = offene_turntruth(connect, dbp, sid)
    if not tt:
        raise RuntimeError("keine offene Eingabe fuer die Wiederaufnahme")
    with patch.object(urllib.request, "urlopen", FakeProvider([])):
        p = cl.post("/api/kernel/prepare", headers=H, json={
            "sessionId": sid, "actorUserId": "admin", "trace_id": f"kpr_{trace}", "truth": truth_fn(str(tt.get("text") or "")),
            "speaker": {"id": speaker}, "resumePending": {"turnTruthId": pend}})
    if p.status_code != 200:
        return p
    pj = p.get_json()
    with patch.object(urllib.request, "urlopen", formulier_provider(FakeProvider, formulierung)):
        f = cl.post("/api/llm/formulate", headers=H, json={
            "sessionId": sid, "sourceTurnId": pj["truth"]["id"], "speakerId": pj["truth"].get("speaker_id"),
            "turnIndex": pj["session"].get("turnIndex"), "text": "", "scope": "user",
            "inputKind": pj["truth"].get("input_kind") or "speech", "turnBeleg": pj.get("turnBeleg")})
    if f.status_code != 200 or not (f.get_json() or {}).get("formulierungsBeleg"):
        return f
    return {"pj": pj, "fj": f.get_json()}


def belegt_committen(cl, H, belege, *, sid, FakeProvider, trace="k01", provider=None):
    pj, fj = belege["pj"], belege["fj"]
    res = fj.get("result") or {}
    with patch.object(urllib.request, "urlopen", provider or FakeProvider([])):
        return cl.post("/api/kernel/commit", headers=H, json={
            "sessionId": sid, "actorUserId": "admin", "trace_id": f"kc_{trace}", "truth": pj["truth"],
            "speaker": {"id": pj["truth"].get("speaker_id")},
            "result": {"speech": res.get("speech"), "action": res.get("action"),
                       **({"proposals": res["proposals"]} if res.get("proposals") else {})},
            "fired": ((pj.get("brainContext") or {}).get("spiegel") or {}).get("fired") or [],
            "turnBeleg": pj.get("turnBeleg"), "formulierungsBeleg": fj.get("formulierungsBeleg")})
