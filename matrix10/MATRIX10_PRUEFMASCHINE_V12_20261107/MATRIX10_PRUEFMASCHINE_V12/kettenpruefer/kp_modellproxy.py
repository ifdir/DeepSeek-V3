#!/usr/bin/env python3
"""Modell-Proxy des Kettenprüfers (nur Standardbibliothek).

Das Produkt bleibt unverändert. Der Prüfer setzt in SEINER Datenbank-Kopie den
Provider-Endpunkt auf diesen Proxy. Der Proxy

- leitet im Modus "live" jede Anfrage an den echten Anbieter weiter und schreibt
  Anfrage-Art und Antwort mit (Schlüssel werden nie geschrieben),
- gibt im Modus "wiedergabe" genau die mitgeschnittenen echten Antworten in derselben
  Reihenfolge je Prüffall und Anfrage-Art zurück. Fehlt eine Aufnahme, antwortet er
  mit HTTP 599; der Prüfer wertet das als BLOCKIERT, nie als bestanden.

Steuerung: POST /__fall/<fall-id> setzt den aktuellen Prüffall.
GET /__stand liefert Zähler (Anfragen, Treffer, Fehlgriffe).
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UPSTREAM = "https://api.openai.com/v1/chat/completions"


def anfrage_art(body: dict) -> str:
    """Stabile Art einer Anfrage: Anfang der Systemanweisung (Vertragsname), ohne Sitzungsdaten."""
    msgs = body.get("messages") or []
    sys_text = ""
    for m in msgs:
        if m.get("role") == "system":
            sys_text = str(m.get("content") or "")
            break
    if not sys_text and msgs:
        sys_text = str(msgs[0].get("content") or "")
    kopf = " ".join(sys_text.split())[:90]
    return hashlib.sha256(kopf.encode("utf-8")).hexdigest()[:16] + "|" + kopf[:48]


class Zustand:
    def __init__(self, modus: str, ordner: Path):
        self.modus = modus
        self.ordner = ordner
        self.ordner.mkdir(parents=True, exist_ok=True)
        self.fall = "ohne_fall"
        self.zaehler: dict[tuple[str, str], int] = {}
        self.lock = threading.Lock()
        self.stand = {"anfragen": 0, "weitergeleitet": 0, "treffer": 0, "fehlgriffe": 0, "upstream_fehler": 0}
        self.fehlgriff_zeiten: list[float] = []   # Unix-Zeit jedes Fehlgriffs (Selbsttest: vor/nach dem Hauptcommit)
        self.aufnahme = {}
        datei = self.ordner / "aufnahme.jsonl"
        if datei.exists():
            for zeile in datei.read_text(encoding="utf-8").splitlines():
                if zeile.strip():
                    r = json.loads(zeile)
                    self.aufnahme[(r["fall"], r["art"], r["nr"])] = r

    def naechste_nr(self, art: str) -> int:
        k = (self.fall, art)
        n = self.zaehler.get(k, 0)
        self.zaehler[k] = n + 1
        return n


def mache_handler(z: Zustand):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keine Konsole voller Zeilen
            pass

        def _json(self, code: int, obj: dict):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/__stand":
                with z.lock:
                    return self._json(200, {"modus": z.modus, "fall": z.fall, **z.stand, "fehlgriff_zeiten": list(z.fehlgriff_zeiten)})
            return self._json(404, {"fehler": "unbekannt"})

        def do_POST(self):
            laenge = int(self.headers.get("Content-Length") or 0)
            roh = self.rfile.read(laenge) if laenge else b""
            if self.path.startswith("/__fall/"):
                with z.lock:
                    z.fall = self.path[len("/__fall/"):]
                return self._json(200, {"fall": z.fall})
            try:
                body = json.loads(roh.decode("utf-8") or "{}")
            except Exception:
                return self._json(400, {"fehler": "kein JSON"})
            art = anfrage_art(body)
            with z.lock:
                z.stand["anfragen"] += 1
                nr = z.naechste_nr(art)
                fall = z.fall
            if z.modus == "wiedergabe":
                r = z.aufnahme.get((fall, art, nr))
                with z.lock:
                    z.stand["treffer" if r else "fehlgriffe"] += 1
                    if not r:
                        z.fehlgriff_zeiten.append(time.time())
                if not r:
                    return self._json(599, {"error": {"message": f"Kettenpruefer: keine Aufnahme fuer {fall} / {art} / {nr}"}})
                return self._json(int(r["status"]), r["antwort"])
            # live: weiterleiten, Schlüssel nur im Header durchreichen, nie speichern
            req = urllib.request.Request(UPSTREAM, data=roh, method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": self.headers.get("Authorization") or ""})
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    status, antwort = resp.status, json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                status = e.code
                try:
                    antwort = json.loads(e.read().decode("utf-8") or "{}")
                except Exception:
                    antwort = {"error": {"message": f"HTTP {e.code}"}}
                with z.lock:
                    z.stand["upstream_fehler"] += 1
            except Exception as e:  # Netz weg: sichtbar, nicht aufgenommen
                with z.lock:
                    z.stand["upstream_fehler"] += 1
                return self._json(502, {"error": {"message": f"Kettenpruefer-Proxy: {type(e).__name__}"}})
            with z.lock:
                z.stand["weitergeleitet"] += 1
                with (z.ordner / "aufnahme.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"fall": fall, "art": art, "nr": nr, "status": status, "antwort": antwort},
                                       ensure_ascii=False) + "\n")
            return self._json(status, antwort)

    return H


def starte(modus: str, ordner: Path, port: int) -> tuple[ThreadingHTTPServer, Zustand]:
    z = Zustand(modus, ordner)
    srv = ThreadingHTTPServer(("127.0.0.1", port), mache_handler(z))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, z


if __name__ == "__main__":
    s, _ = starte(sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]))
    print("Proxy laeuft", sys.argv[1:], flush=True)
    threading.Event().wait()
