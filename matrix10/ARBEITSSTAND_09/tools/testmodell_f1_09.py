#!/usr/bin/env python3
"""F1-Testmodell: lokaler OpenAI-kompatibler Endpoint (Provider 'custom'), feste Antworten je Lesung.

KEIN echtes Modell und kein Nachweis fuer Formulierungsqualitaet. Zweck: die Kernel-Kette (Lesung -> Pruefung -> Writer ->
Reader -> naechster Zug -> Neustart) ueber den echten HTTP-Weg messbar machen. Jeder Aufruf wird mit Lesungsname, System-
und Nutzertext protokolliert; der Nutzertext der Formulierung ist der echte BrainContext/Brief, den der Server sendet.
Aufruf: python3 -I testmodell_f1_09.py <produktordner> <port> <protokoll.jsonl> <drehbuch.json>
Drehbuch: {"<LESUNG>": <json-antwort> | [<antwort 1>, ...] | [{"wenn": <text(e) im Nutzertext>, "antwort": ...}, ...]}; ohne Eintrag: {} (als 'UNGESCRIPTET' protokolliert).
"""
from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading

root, port, prot, buch = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
sys.path.insert(0, str(root))
from matrix_api import llm_contract as LC  # noqa: E402  (nur Konstanten lesen)

NAMEN = sorted(((n, v) for n, v in vars(LC).items() if n.endswith("_RULES") and isinstance(v, str) and len(v) > 40),
               key=lambda x: -len(x[1]))
LOCK = threading.Lock()
ZAEHLER: dict = {}


RICHTUNG = {"fear": "steigt", "angst": "steigt", "wut": "steigt", "stress": "steigt", "scham": "steigt", "trust": "sinkt",
            "closeness": "sinkt", "lust": "sinkt"}


def kausal(user: str) -> dict:
    """Kausale Gegenpruefung: jedes zu pruefende Feld wird mit einer Ereignis-ID und einer Dispositionsquelle aus DEM
    PAYLOAD belegt (wortgleiche Ausschnitte) - der Kernel prueft diese Belege selbst."""
    try:
        p = json.loads(user)
    except Exception:
        return {"pruefungen": []}
    fig = p.get("figur") if isinstance(p.get("figur"), dict) else {}
    gg = p.get("gerade_geschehen") or fig.get("gerade_geschehen") or []
    ev = next((e for e in gg if "schlägt" in str(e.get("text"))), None) or (gg[-1] if gg and os.environ.get("F1_KAUSAL_ALLGEMEIN") else None)
    quellen = fig.get("dispositionsquellen") or p.get("dispositionsquellen") or []
    q = next((x for x in quellen if str(x.get("text")) == "Johanns Druck"), None) or \
        next((x for x in quellen if "Bedrohung" in str(x.get("text"))), quellen[0] if quellen else {})
    qt = str(q.get("text") or "")
    qb = " ".join(qt.split()[:4]) if qt else ""
    out = []
    for f in p.get("zu_pruefen") or []:
        name = str(f.get("feld") if isinstance(f, dict) else f)
        if not ev or not q:
            out.append({"feld": name, "urteil": "nicht_gestuetzt"})
            continue
        r = next((v for k, v in RICHTUNG.items() if k in name), "steigt")
        _bel = "schlägt Mara mit der Faust" if "schlägt" in str(ev.get("text")) else " ".join(str(ev.get("text")).split()[:3])
        out.append({"feld": name, "urteil": "gestuetzt", "factId": ev.get("id"), "beleg": _bel,
                    "dispositionsQuelle": q.get("id"), "dispositionsBeleg": qb, "richtung": r,
                    "begruendung": f'"{qb}" - der Schlag trifft genau das, was diese Quelle bei ihr beschreibt.'})
    return {"pruefungen": out}


def rede_bedienperson(user: str) -> dict:
    """Planer-Lesung einer Frage der Bedienperson an Mara: eine rede-Komponente, Segment = die ganze Aeusserung woertlich."""
    p = json.loads(user)
    t = str(p.get("aeusserung") or "")
    return {"event_kind": "question", "speech_act": "ask", "durability": "utterance",
            "summary": "Die Bedienperson fragt Mara etwas.", "subject": "Bedienperson", "predicate": "fragt", "object": "Mara",
            "temporal": {"text": None, "precision": "unknown", "wochentag": None, "relativ": None, "in_tagen": None, "datum": None,
                         "uhrzeit": None},
            "refers_to": None, "cue_terms": [], "grenze": None, "verweis": None,
            "komponenten": [{"typ": "rede", "segment": t, "akteur": str(p.get("sprecher") or ""), "ziel": "Mara Nowak", "zeit": "jetzt",
                             "wirkung": None, "bezug": None, "einleitung": None, "geschieht": None}]}


def komponentenart(user: str, param: dict) -> dict:
    """Lesung Rede/Handlung eines Puppet-Segments nach fester Tabelle (param: {"handlungen": {segment: wirkung}})."""
    p = json.loads(user)
    seg = str(p.get("segment") or "")
    for h, w in (param.get("handlungen") or {}).items():
        if h in seg or seg in h:
            return {"art": "handlung", "beleg": seg, "wirkung": w}
    return {"art": "rede", "beleg": seg, "wirkung": None}


def vollzug(user: str, param: dict) -> dict:
    p = json.loads(user)
    h = str(p.get("handlung") or "")
    return {"geschieht": True, "art": "tatsaechlich", "beleg": h, "taeter": "Ich" if h.lower().startswith("ich ") else "figur",
            "ziel": "dir" if " dir " in f" {h} " else ""}


def koerper(user: str, param: dict) -> dict:
    p = json.loads(user)
    h = str(p.get("handlung") or "")
    return {"haltung": None, "schlaf": None, "zeit": "jetzt", "beleg": h or None}


def bewegung(user: str, param: dict) -> dict:
    p = json.loads(user)
    h = str(p.get("handlung") or "")
    return {"bestaetigt": True, "zeit": "jetzt", "ziel": str(p.get("ziel") or "") or None, "beleg": " ".join(h.split()[:5]),
            "versuch": False, "gegen": None, "beruehrung": False, "beruehrungBeleg": None}


DYNAMISCH = {"kausal": kausal, "rede_bedienperson": rede_bedienperson, "komponentenart": komponentenart, "vollzug": vollzug,
             "koerper": koerper, "bewegung": bewegung}


def lesung(system: str) -> str:
    if system.startswith("Formuliere, was die gebundene Figur"):
        return "FORMULIERUNG"
    for n, v in NAMEN:
        if system.startswith(v[:200]):
            return n
    return "UNBEKANNT:" + system[:60]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        msgs = body.get("messages") or []
        system = next((m.get("content") for m in msgs if m.get("role") == "system"), "") or ""
        user = next((m.get("content") for m in msgs if m.get("role") == "user"), "") or ""
        name = lesung(system)
        t0 = time.time()
        time.sleep(float(os.environ.get("F1_VERZOEGERUNG") or 0))   # feste Modell-Latenz je Aufruf (Messung), Standard 0
        drehbuch = json.loads(buch.read_text()) if buch.exists() else {}
        with LOCK:
            i = ZAEHLER.get(name, 0)
            ZAEHLER[name] = i + 1
            eintrag = drehbuch.get(name)
            if isinstance(eintrag, list) and eintrag and all(isinstance(e, dict) and "wenn" in e for e in eintrag):
                treffer = [e for e in eintrag if all(w in user for w in (e["wenn"] if isinstance(e["wenn"], list) else [e["wenn"]]))]
                antwort = treffer[0]["antwort"] if treffer else {}
                eintrag = eintrag if treffer else None
            elif isinstance(eintrag, list):
                antwort = eintrag[min(i, len(eintrag) - 1)] if eintrag else {}
            else:
                antwort = eintrag if eintrag is not None else {}
            if isinstance(antwort, dict) and "dynamisch" in antwort:
                _f = DYNAMISCH[antwort["dynamisch"]]
                antwort = _f(user, antwort.get("param") or {}) if "param" in antwort else _f(user)
            with prot.open("a") as fh:
                fh.write(json.dumps({"lesung": name, "nr": i + 1, "geskriptet": eintrag is not None, "user": user,
                                     "system_anfang": system[:160], "antwort": antwort,
                                     "t_start": t0, "t_ende": time.time()}, ensure_ascii=False) + "\n")
        out = {"id": "f1", "object": "chat.completion", "model": "f1-testmodell",
               "choices": [{"index": 0, "finish_reason": "stop",
                            "message": {"role": "assistant", "content": json.dumps(antwort, ensure_ascii=False)}}],
               "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
