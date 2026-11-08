#!/usr/bin/env python3
"""MATRIX10 production launcher: Flask API + prebuilt UI, Python only.

Runtime requirements:
- Python + the project's requirements.txt dependencies
- NO Node.js, npm, Vite or Tailwind at runtime

Services:
- Flask API: 127.0.0.1:5050 (MATRIX_API_PORT)
- Prebuilt UI: 127.0.0.1:8080 (MATRIX_UI_PORT)

The UI server also proxies /api/* to Flask, matching the former Vite dev proxy.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import sqlite3
import mimetypes
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend_dist"
FRONTEND_MARKER = "/__matrix_start_health"

# One launch may not silently reuse the old build on ports 5050/8080.
# V53 ships a different backend + frontend and must reject mixed versions.
BUILD_ID = next(
    (line.split("=", 1)[1].strip()
     for line in (ROOT / "VERSION.txt").read_text(encoding="utf-8").splitlines()
     if line.startswith("BUILD_ID=")),
    "UNKNOWN",
)

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".mjs")


def _http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 400
    except Exception:
        return False


def _marker_ok(ui_port: str, timeout: float = 1.0) -> bool:
    url = f"http://127.0.0.1:{ui_port}{FRONTEND_MARKER}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return False
            data = json.loads(response.read().decode("utf-8"))
            return data.get("service") == "matrix10-python-ui" and data.get("buildId") == BUILD_ID
    except Exception:
        return False


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(ROOT)
        if not env.get("PYTHONPATH")
        else str(ROOT) + os.pathsep + env["PYTHONPATH"]
    )
    env["MATRIX_DB"] = str(ROOT / "data" / "matrix10.sqlite")
    env.setdefault("MATRIX_API_HOST", "127.0.0.1")
    env.setdefault("MATRIX_API_PORT", "5050")
    env.setdefault("MATRIX_UI_HOST", "127.0.0.1")
    env.setdefault("MATRIX_UI_PORT", "8080")
    env.setdefault(
        "MATRIX_API_ORIGIN",
        f"http://127.0.0.1:{env['MATRIX_API_PORT']}",
    )
    return env


def _terminate(process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _make_handler(api_port: str):
    class MatrixFrontendHandler(SimpleHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

        def log_message(self, fmt: str, *args) -> None:
            # Keep the Pydroid console readable. Backend logs remain visible.
            return

        def _send_marker(self, include_body: bool = True) -> None:
            payload = json.dumps(
                {"ok": True, "service": "matrix10-python-ui", "buildId": BUILD_ID},
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if include_body:
                self.wfile.write(payload)

        def _proxy_api(self) -> None:
            body = None
            length = self.headers.get("Content-Length")
            if length:
                try:
                    body = self.rfile.read(int(length))
                except ValueError:
                    self.send_error(400, "Invalid Content-Length")
                    return

            request_headers: dict[str, str] = {}
            hop_by_hop = {
                "connection",
                "keep-alive",
                "proxy-authenticate",
                "proxy-authorization",
                "te",
                "trailers",
                "transfer-encoding",
                "upgrade",
                "host",
            }
            for key, value in self.headers.items():
                if key.lower() not in hop_by_hop:
                    request_headers[key] = value
            request_headers["Host"] = f"127.0.0.1:{api_port}"

            conn = http.client.HTTPConnection("127.0.0.1", int(api_port), timeout=900)
            try:
                conn.request(self.command, self.path, body=body, headers=request_headers)
                upstream = conn.getresponse()
                payload = upstream.read()
                self.send_response(upstream.status, upstream.reason)
                for key, value in upstream.getheaders():
                    if key.lower() in hop_by_hop or key.lower() == "content-length":
                        continue
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)
            except (OSError, http.client.HTTPException) as exc:
                payload = json.dumps(
                    {
                        "ok": False,
                        "error": "BACKEND_UNAVAILABLE",
                        "message": str(exc),
                    }
                ).encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)
            finally:
                conn.close()

        def _serve_storage_status(self, include_body: bool = True) -> None:
            # Product-visible read-only verification, not a second writer.
            # Only bound on localhost; no world, user names or row payloads exposed.
            db_name = os.environ.get("MATRIX_DB", str(ROOT / "data" / "matrix10.sqlite"))
            db_file = Path(db_name)
            if not db_file.is_absolute():
                db_file = ROOT / db_file
            try:
                if not db_file.is_file():
                    raise FileNotFoundError("Datenbank fehlt")
                actor = self.headers.get("X-Matrix-Actor", "").strip()
                if not actor or len(actor) > 128:
                    raise PermissionError("Bitte zuerst den eigenen Matrix10-Benutzer oben auf der Löschseite wählen.")
                with sqlite3.connect(db_file.as_uri() + "?mode=ro", uri=True, timeout=5) as conn:
                    if conn.execute("SELECT id FROM users WHERE id=?", (actor,)).fetchone() is None:
                        raise PermissionError("Unbekannter Benutzer. Keine fremden Daten anzeigen.")
                    def pragma(name: str):
                        return conn.execute("PRAGMA " + name).fetchone()[0]
                    values = {
                        "ok": True,
                        "dbBytes": db_file.stat().st_size,
                        "dbPath": str(db_file.resolve()),
                        "walBytes": db_file.with_name(db_file.name + "-wal").stat().st_size if db_file.with_name(db_file.name + "-wal").exists() else 0,
                        "sessionCount": conn.execute("SELECT count(*) FROM sessions WHERE user_id=?", (actor,)).fetchone()[0],
                        "characterCount": conn.execute("SELECT count(*) FROM characters WHERE owner_user_id=?", (actor,)).fetchone()[0],
                        "memoryCount": conn.execute("SELECT count(*) FROM memories WHERE user_id=?", (actor,)).fetchone()[0],
                        "logCount": conn.execute("SELECT count(*) FROM logs WHERE user_id=?", (actor,)).fetchone()[0],
                        "orphanSessionLogCount": conn.execute(
                            "SELECT count(*) FROM logs AS l WHERE l.user_id=? "
                            "AND (CASE WHEN json_valid(l.json) THEN COALESCE(json_extract(l.json,'$.sessionId'), json_extract(l.json,'$.session_id')) END) IS NOT NULL "
                            "AND (CASE WHEN json_valid(l.json) THEN COALESCE(json_extract(l.json,'$.sessionId'), json_extract(l.json,'$.session_id')) END) <> '' "
                            "AND NOT EXISTS (SELECT 1 FROM sessions AS s WHERE s.id=(CASE WHEN json_valid(l.json) THEN COALESCE(json_extract(l.json,'$.sessionId'), json_extract(l.json,'$.session_id')) END) AND s.user_id=l.user_id)",
                            (actor,),
                        ).fetchone()[0],
                        "freePages": pragma("freelist_count"),
                        "autoVacuum": pragma("auto_vacuum"),
                        "quickCheck": pragma("quick_check"),
                        "foreignKeyViolations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
                    }
                body = json.dumps(values, ensure_ascii=False).encode("utf-8")
                status = 200
            except Exception as exc:
                body = json.dumps({"ok": False, "message": str(exc)}).encode("utf-8")
                status = 503
            if status == 503 and b'Bitte zuerst' in body:
                status = 403
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if include_body:
                self.wfile.write(body)

        def _serve_storage_page(self, include_body: bool = True) -> None:
            body = (ROOT / "matrix_speicher_v91.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if include_body:
                self.wfile.write(body)

        def _serve_frontend(self, include_body: bool = True) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/__matrix_speicher/status":
                self._serve_storage_status(include_body=include_body)
                return
            if parsed.path == "/__matrix_speicher":
                self._serve_storage_page(include_body=include_body)
                return
            if parsed.path == FRONTEND_MARKER:
                self._send_marker(include_body=include_body)
                return

            if parsed.path.startswith("/api"):
                self._proxy_api()
                return

            query = urllib.parse.parse_qs(parsed.query)
            if (
                query.get("install", [""])[0].lower() in {"1", "true"}
                and query.get("platform", [""])[0].lower() == "ios"
            ):
                self.path = "/__grok/install/index.html"
                if include_body:
                    super().do_GET()
                else:
                    super().do_HEAD()
                return

            # Serve real build assets directly. Everything else gets the
            # pre-rendered TanStack document so client-side routing can take over.
            relative = urllib.parse.unquote(parsed.path).lstrip("/")
            # V65Z (SPS-Audit V65Y A07; AMASTER §71.1.2 technische Basissicherheit): the requested file must lie INSIDE
            # frontend_dist after resolving the path. "/assets/..%2F..%2Fdata%2Fmatrix10.sqlite" resolved to the database
            # (with the provider key) and was served with HTTP 200. Outside -> 404, nothing read.
            try:
                _root = FRONTEND_DIR.resolve()
                candidate = (FRONTEND_DIR / relative).resolve()
                _inside = candidate == _root or _root in candidate.parents
            except (OSError, ValueError):
                _inside = False
            if not _inside:
                self.send_error(404, "File not found")
                return
            if parsed.path.startswith("/assets/") and candidate.is_file():
                self._serve_asset(candidate, include_body=include_body)
                return
            if parsed.path == "/":
                candidate = FRONTEND_DIR / "index.html"
                self.path = "/index.html"
            elif candidate.is_file():
                self.path = parsed.path
            else:
                self.path = "/index.html"

            if include_body:
                super().do_GET()
            else:
                super().do_HEAD()

        def _serve_asset(self, path: Path, include_body: bool = True) -> None:
            """V65J (AMASTER §65; Prüfbericht v2.2 Cache-Randfall): /assets/ are validated by
            their CONTENT. ETag = SHA-256 of the bytes; If-None-Match equal -> 304, otherwise
            the file. If-Modified-Since is ignored here: a file changed with an unchanged
            modification time got 304 before (reproduced). Cache-Control stays no-cache."""
            try:
                data = path.read_bytes()
            except OSError:
                self.send_error(404, "File not found")
                return
            etag = '"' + hashlib.sha256(data).hexdigest()[:32] + '"'
            inm = [t.strip() for t in str(self.headers.get("If-None-Match") or "").split(",") if t.strip()]
            if etag in inm or "*" in inm:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(str(path)))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("ETag", etag)
            self.end_headers()
            if include_body:
                self.wfile.write(data)

        def end_headers(self) -> None:
            path = urllib.parse.urlsplit(self.path).path
            if path.startswith("/assets/"):
                # V65I (AMASTER §65 Diagnose zeigt Buildstand; dein Lauf 28.10. 15:31): the
                # assets were cached "immutable" for a year, but their names stayed "-V59F"
                # while V61-V65H patched their content. Your browser kept the chat code from
                # before V65E: after an acts-only Regie it forced the actor's turn instead of
                # the kernel gate, so Mara never answered. Revalidate every load instead.
                # V65J: by content (ETag, _serve_asset), not by modification time.
                self.send_header("Cache-Control", "no-cache")
            elif path.endswith("index.html") or path.endswith(".webmanifest"):
                self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def do_GET(self) -> None:
            self._serve_frontend(include_body=True)

        def do_HEAD(self) -> None:
            self._serve_frontend(include_body=False)

        def do_POST(self) -> None:
            if urllib.parse.urlsplit(self.path).path.startswith("/api"):
                self._proxy_api()
            else:
                self.send_error(405, "Method Not Allowed")

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

        def do_OPTIONS(self) -> None:
            if urllib.parse.urlsplit(self.path).path.startswith("/api"):
                self._proxy_api()
            else:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()

    return MatrixFrontendHandler


def main() -> int:
    os.chdir(ROOT)
    # Do not migrate data while an older server still owns the product ports.
    if _http_ok('http://127.0.0.1:'+os.environ.get('MATRIX_UI_PORT','8080')+'/') and not _marker_ok(os.environ.get('MATRIX_UI_PORT','8080')):
        print('[STOP] Auf Port 8080 laeuft bereits eine andere Matrix10-Version. Diese zuerst beenden.',file=sys.stderr)
        return 1
    api_health='http://127.0.0.1:'+os.environ.get('MATRIX_API_PORT','5050')+'/api/health'
    if _http_ok(api_health):
        try:
            with urllib.request.urlopen(api_health,timeout=2) as response:
                other_build=json.load(response).get('buildId')
        except (OSError,ValueError):
            other_build=None
        if other_build != BUILD_ID:
            print('[STOP] Eine andere Matrix10-API laeuft noch. Vor Datenmigration beenden.',file=sys.stderr)
            return 1
    # V89: check essential runtime before first SQLite initialization.
    # If Flask is missing, an empty new DB must not block later adoption of
    # the existing previous-version project data and provider settings.
    try:
        from flask import Flask as _flask_runtime_check
    except ImportError as exc:
        print('[START-FEHLER] Flask/Abhaengigkeit fehlt. Keine Datenbank angelegt. '
              'Python-Umgebung laut requirements.txt einrichten: '+str(exc),file=sys.stderr)
        return 1
    from datenbank_projekt_v81 import prepare_data
    try:
        ready, explanation = prepare_data()
    except Exception as exc:
        print('[DATEN-FEHLER] Projektdatenbank unverändert: '+str(exc), file=sys.stderr)
        return 1
    print('[DATEN] '+explanation)
    if not ready:
        return 1
    # Stand 10a (Android-Ausfall 08.11.): check the Rust consent core ONCE at start and say why it cannot load - before,
    # the first touch input failed with a bare 503. The server still starts; touch/consent inputs stay fail-closed.
    try:
        sys.path.insert(0, str(ROOT))
        from matrix_api import native_boundary as _nb
        _rk = _nb.status()
        if _rk.get("ok"):
            print(f"[RUST] Einwilligungskern geladen (ABI {_rk.get('abi')}, Geraet {_rk.get('geraet')}"
                  + (", aus dem App-Speicher geladen - der Paketordner erlaubt kein Laden (z. B. Download)" if _rk.get("geladenAus") == "app_kopie" else "")
                  + ").")
        else:
            print("[RUST-FEHLER] Einwilligungskern NICHT ladbar: " + str(_rk.get("grund")), file=sys.stderr)
            if _rk.get("abhilfe"):
                print("[RUST-FEHLER] Abhilfe: " + str(_rk.get("abhilfe")), file=sys.stderr)
            print("[RUST-FEHLER] Beruehrungs-/Einwilligungs-Eingaben werden bis dahin NICHT gespeichert (503).", file=sys.stderr)
    except Exception as exc:
        print(f"[RUST-FEHLER] Pruefung nicht moeglich: {exc}", file=sys.stderr)
    env = _build_env()
    api_port = env["MATRIX_API_PORT"]
    ui_host = env["MATRIX_UI_HOST"]
    ui_port = env["MATRIX_UI_PORT"]
    health_url = f"http://127.0.0.1:{api_port}/api/health"
    ui_url = f"http://127.0.0.1:{ui_port}/"

    if not FRONTEND_DIR.joinpath("index.html").is_file():
        print("[FEHLER] Fertiges Frontend fehlt: frontend_dist/index.html", file=sys.stderr)
        return 1

    backend: subprocess.Popen[bytes] | subprocess.Popen[str] | None = None
    frontend: ThreadingHTTPServer | None = None
    frontend_thread: threading.Thread | None = None

    try:
        if _http_ok(health_url):
            try:
                with urllib.request.urlopen(health_url, timeout=2) as response:
                    active_build = json.load(response).get("buildId")
            except (OSError, ValueError) as exc:
                print(f"[FEHLER] Backend-Version nicht lesbar: {exc}", file=sys.stderr)
                return 1
            if active_build != BUILD_ID:
                print(f"[FEHLER] Auf Port {api_port} laeuft {active_build}; erwartet {BUILD_ID}. Alte Version zuerst beenden.", file=sys.stderr)
                return 1
            print(f"[OK] Backend laeuft bereits: {health_url} ({BUILD_ID})")
        else:
            print(f"[START] Backend: Python -> Port {api_port}")
            backend = subprocess.Popen(
                [sys.executable, "-m", "matrix_api.app"],
                cwd=ROOT,
                env=env,
            )

        if _marker_ok(ui_port):
            print(f"[OK] Python-Frontend laeuft bereits: {ui_url}")
        elif _http_ok(ui_url):
            print(
                f"[FEHLER] Port {ui_port} ist durch ein anderes/altes Frontend belegt. "
                "Dieses zuerst beenden.",
                file=sys.stderr,
            )
            return 1
        else:
            handler = _make_handler(api_port)
            try:
                frontend = ThreadingHTTPServer((ui_host, int(ui_port)), handler)
            except OSError as exc:
                print(f"[FEHLER] Frontend-Port {ui_port} kann nicht geoeffnet werden: {exc}", file=sys.stderr)
                return 1
            frontend.daemon_threads = True
            frontend_thread = threading.Thread(target=frontend.serve_forever, daemon=True)
            frontend_thread.start()
            print(f"[START] Frontend: fertiger Build, nur Python -> Port {ui_port}")

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            backend_ready = _http_ok(health_url)
            frontend_ready = _marker_ok(ui_port)
            if backend_ready and frontend_ready:
                print("[OK] Backend und Frontend laufen.")
                # Android/Pydroid3 has no Windows wrapper. Open the functional
                # storage/deletion page after both services are truly ready.
                if Path('/system/bin/am').exists() and os.environ.get('MATRIX_NO_OPEN')!='1':
                    try:
                        subprocess.Popen(['/system/bin/am','start','-a',
                            'android.intent.action.VIEW','-d',ui_url],
                            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    except OSError:
                        pass
                print("[OK] Node.js/npm werden NICHT benoetigt.")
                print(f"[UI] {ui_url}")
                print("[STOP] Strg+C beendet die von START.py gestarteten Prozesse.")
                break
            if backend is not None and backend.poll() is not None:
                print(f"[FEHLER] Backend beendet: Exit-Code {backend.returncode}", file=sys.stderr)
                return backend.returncode or 1
            time.sleep(0.2)
        else:
            print("[FEHLER] Start-Timeout: Backend oder Frontend wurde nicht bereit.", file=sys.stderr)
            return 1

        # If both were already running, there is nothing owned by this invocation.
        if backend is None and frontend is None:
            return 0

        while True:
            if backend is not None and backend.poll() is not None:
                print(f"[ENDE] Backend wurde mit Exit-Code {backend.returncode} beendet.")
                return backend.returncode or 0
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[STOP] Beende gestartete Prozesse ...")
        return 0
    finally:
        if frontend is not None:
            frontend.shutdown()
            frontend.server_close()
        if backend is not None:
            _terminate(backend)


if __name__ == "__main__":
    raise SystemExit(main())
