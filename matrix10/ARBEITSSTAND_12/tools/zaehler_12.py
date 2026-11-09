#!/usr/bin/env python3
"""Stand 12: Zaehl-Weiterleitung fuer Live-Laeufe. Der Server spricht http://127.0.0.1:<port>/api.openai.com/v1/chat/completions
(enthaelt "openai.com" -> gleiche Routing-/Schema-Entscheidung wie der echte Endpoint); jede Anfrage wird UNVERAENDERT an
https://api.openai.com/v1/chat/completions weitergegeben. Protokolliert je Aufruf: Zeit, Schema-Name, Prompt-/Antwortgroesse,
Token-Nutzung, Status, Anfrage-Nachrichten und Antworttext. Der Authorization-Header wird nie protokolliert.
Aufruf: python3 -I zaehler_12.py <port> <protokoll.jsonl>
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import threading
import time
import urllib.error
import urllib.request

ZIEL = "https://api.openai.com/v1/chat/completions"
LOCK = threading.Lock()


def main() -> int:
    port, prot = int(sys.argv[1]), sys.argv[2]

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n)
            t0 = time.time()
            req = urllib.request.Request(ZIEL, data=body, method="POST", headers={
                "Content-Type": "application/json", "Authorization": self.headers.get("Authorization") or ""})
            status, out = 0, b""
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    status, out = r.status, r.read()
            except urllib.error.HTTPError as e:
                status, out = e.code, e.read()
            except Exception as e:  # Netz: wie ein Providerfehler zurueckgeben
                status, out = 502, json.dumps({"error": {"message": type(e).__name__}}).encode()
            t1 = time.time()
            try:
                q = json.loads(body)
            except Exception:
                q = {}
            try:
                a = json.loads(out)
            except Exception:
                a = {}
            rf = q.get("response_format") or {}
            msgs = q.get("messages") or []
            eintrag = {"t_start": t0, "t_ende": t1, "dauer_s": round(t1 - t0, 2), "status": status,
                       "schema": (rf.get("json_schema") or {}).get("name") or rf.get("type") or "",
                       "max_tokens": q.get("max_tokens") or q.get("max_completion_tokens"),
                       "prompt_zeichen": sum(len(str(m.get("content") or "")) for m in msgs),
                       "usage": a.get("usage"), "finish": ((a.get("choices") or [{}])[0]).get("finish_reason"),
                       "nachrichten": msgs, "antwort": ((a.get("choices") or [{}])[0].get("message") or {}).get("content"),
                       "fehler": (a.get("error") or {}).get("message") if status != 200 else None}
            with LOCK, open(prot, "a", encoding="utf-8") as f:
                f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
