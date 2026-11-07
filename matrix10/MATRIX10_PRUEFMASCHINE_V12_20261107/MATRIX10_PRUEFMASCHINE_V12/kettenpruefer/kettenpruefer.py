#!/usr/bin/env python3
"""MATRIX10 Kettenprüfer V1.2 – unabhängige End-to-End-Abnahme nach Kettenvertrag §16.

V1.2: alle 20 Glieder je Fall Pflicht (NICHT_ZUTREFFEND nur laut eingefrorenem Katalog), Wissen im Folgezug
an Spur, Sitzung, Sprecher und Zeugenwissen gebunden, Abwesende ohne Wissen, Rückanzeige im Gesprächsverlauf
auch nach dem Server-Neustart, Status nur aus pm_auswertung (eine Entscheidungslogik).

Getrennt vom Produkt. Ändert keinen Produktcode und nie die übergebene Original-DB.
Ablauf je Kandidat:
  ZIP-Hash -> frisch entpacken -> Frontend bauen (Build-Kennung) -> DB-KOPIE anlegen
  (nur der Modell-Endpunkt der Kopie zeigt auf den Prüfer-Proxy) -> Server mit START.py
  -> je Fall: echte Oberfläche bedienen (kp_ui.js), SQLite vorher/nachher über GETRENNTE
  Nur-Lese-Verbindung, Live-Log des Laufs, Proxy-Zähler -> 20 Glieder bewerten
  -> Neustart des Servers und Persistenzprüfung -> ERGEBNIS.json / ERGEBNIS_LESEN.txt.
Exitcodes: 0 = alle Fälle GRÜN, 2 = mindestens ein Fall ROT, 3 = BLOCKIERT (Voraussetzung fehlt).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
sys.path.insert(0, str(HIER.parent))
import kp_modellproxy  # noqa: E402
import pm_auswertung as pa  # noqa: E402

API = "http://127.0.0.1:5050"
UI = "http://127.0.0.1:8080"
H = {"X-Matrix-Actor": "admin", "Content-Type": "application/json"}
PROXY_PORT = 5099
GLIEDER = pa.GLIEDER
ISOLATIONS_TABELLEN_STAMM = ("characters", "worlds", "users", "config")
BEOBACHTBAR = pa.BEOBACHTBAR
SITZUNGS_TABELLEN = ("scene_facts", "turns", "turn_truth", "witness_knowledge", "god_facts", "memories",
                     "relationships", "goals", "propositions", "graph_edges", "appointments", "snapshots", "uploads")


def sha_datei(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def http(method: str, pfad: str, body=None, timeout=60):
    req = urllib.request.Request(API + pfad, data=json.dumps(body).encode() if body is not None else None,
                                 headers=H, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


# ---------------------------------------------------------------- Kandidat vorbereiten
def entpacken(zip_pfad: Path, ziel: Path) -> Path:
    with zipfile.ZipFile(zip_pfad) as z:
        if z.testzip():
            raise RuntimeError("CRC defekt")
        wurzeln = set()
        for i in z.infolist():
            p = PurePosixPath(i.filename)
            if i.filename.startswith("/") or ".." in p.parts or "\\" in i.filename:
                raise RuntimeError("unsicherer ZIP-Pfad " + i.filename)
            wurzeln.add(p.parts[0])
        if len(wurzeln) != 1:
            raise RuntimeError("ZIP hat nicht genau einen Projektordner")
        z.extractall(ziel)
    return ziel / next(iter(wurzeln))


def build_id(root: Path) -> str | None:
    for z in (root / "VERSION.txt").read_text(encoding="utf-8").splitlines():
        if z.startswith("BUILD_ID="):
            return z.split("=", 1)[1].strip()
    return None


class KandidatRot(Exception):
    """Fehler des KANDIDATEN selbst (z. B. Bau scheitert, Sollquelle verändert): ROT, nicht BLOCKIERT."""


def frontend_bauen(root: Path, nm_cache: Path | None, log: Path) -> tuple[str, str]:
    lock = root / "package-lock.json"
    if nm_cache and (nm_cache / "node_modules").is_dir() and (nm_cache / "package-lock.json").is_file() \
            and sha_datei(nm_cache / "package-lock.json") == sha_datei(lock):
        (root / "node_modules").symlink_to(nm_cache / "node_modules")
        quelle = "node_modules aus Cache mit gleichem package-lock"
    else:
        r = subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=root, capture_output=True, text=True, timeout=1200)
        log.write_text(r.stdout + r.stderr, encoding="utf-8")
        if r.returncode != 0:
            return "BLOCKIERT", "npm ci Exitcode %d" % r.returncode
        quelle = "npm ci"
    r = subprocess.run(["npm", "run", "build:dist"], cwd=root, capture_output=True, text=True, timeout=900)
    with log.open("a", encoding="utf-8") as f:
        f.write(r.stdout + r.stderr)
    if r.returncode != 0:
        return "ROT", "Frontend-Bau Exitcode %d (%s)" % (r.returncode, quelle)
    info = json.loads((root / "frontend_dist" / ".build-info.json").read_text(encoding="utf-8"))
    if info.get("buildId") != build_id(root):
        return "ROT", "Build-Kennung %s ungleich VERSION.txt %s" % (info.get("buildId"), build_id(root))
    return "GRUEN", "frisch gebaut (%s), Kennung %s" % (quelle, info.get("buildId"))


def db_kopie(original: Path, root: Path) -> Path:
    ziel = root / "data" / "matrix10.sqlite"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, ziel)
    c = sqlite3.connect(ziel)
    rows = c.execute("select scope, scope_id, json from config").fetchall()
    for scope, sid, js in rows:
        d = json.loads(js)
        d["endpoint"] = "http://127.0.0.1:%d/v1/chat/completions" % PROXY_PORT   # nur die KOPIE
        c.execute("update config set json=? where scope=? and scope_id=?", (json.dumps(d, ensure_ascii=False), scope, sid))
    c.commit()
    c.close()
    return ziel


def port_frei(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def server_start(root: Path, logdatei: Path) -> subprocess.Popen:
    # Selbstschutz: Ein fremder Server auf denselben Ports würde unbemerkt gemessen.
    belegt = [p for p in (5050, 8080) if not port_frei(p)]
    if belegt:
        raise RuntimeError("BLOCKIERT: Port(s) %s schon belegt - fremder Server, Messung wäre wertlos" % belegt)
    env = {k: v for k, v in os.environ.items()}
    extra = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    p = subprocess.Popen([sys.executable, "START.py"], cwd=root, stdout=logdatei.open("a"), stderr=subprocess.STDOUT,
                         env=env, **extra)
    soll_db = str((root / "data" / "matrix10.sqlite").resolve())
    for _ in range(90):
        time.sleep(1)
        try:
            st, j = http("GET", "/api/health", timeout=5)
            with urllib.request.urlopen(UI + "/", timeout=5) as r:
                if st == 200 and r.status == 200:
                    if str(Path(str(j.get("db") or "")).resolve()) != soll_db:
                        raise RuntimeError("BLOCKIERT: Server meldet DB %s statt %s" % (j.get("db"), soll_db))
                    return p
        except RuntimeError:
            server_stop(p)
            raise
        except Exception:
            pass
    server_stop(p)
    raise RuntimeError("Server startet nicht")


def _nachkommen(pid: int) -> list[int]:
    kinder = []
    for d in Path("/proc").iterdir() if Path("/proc").is_dir() else []:
        if d.name.isdigit():
            try:
                ppid = int((d / "stat").read_text().split(")")[-1].split()[1])
            except Exception:
                continue
            if ppid == pid:
                kinder.append(int(d.name))
    alle = list(kinder)
    for k in kinder:
        alle += _nachkommen(k)
    return alle


def server_stop(p: subprocess.Popen):
    if os.name == "nt":   # Windows: ganzen Prozessbaum beenden (ungeprüft in dieser Umgebung)
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        time.sleep(3)
        if not (port_frei(5050) and port_frei(8080)):
            raise RuntimeError("BLOCKIERT: Server liess sich nicht vollständig beenden (Ports belegt)")
        return
    baum = _nachkommen(p.pid)
    for sig in (15, 9):
        for pid in [p.pid] + baum:
            try:
                os.kill(pid, sig)
            except Exception:
                pass
        try:
            os.killpg(p.pid, sig)
        except Exception:
            pass
        time.sleep(2)
        if port_frei(5050) and port_frei(8080):
            break
    try:
        p.wait(timeout=10)
    except Exception:
        pass
    if not (port_frei(5050) and port_frei(8080)):
        raise RuntimeError("BLOCKIERT: Server liess sich nicht vollständig beenden (Ports belegt)")


# ---------------------------------------------------------------- Messung (getrennte Verbindung)
def roh_stand(db: Path) -> dict:
    c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    st: dict = {"tab": {}}
    for t in ("sessions",) + SITZUNGS_TABELLEN + ISOLATIONS_TABELLEN_STAMM:
        try:
            cols = [r[1] for r in c.execute('pragma table_info("%s")' % t)]
        except sqlite3.Error:
            continue
        if not cols:
            continue
        key = "id" if "id" in cols else cols[0]
        sid_col = "session_id" if "session_id" in cols else ("id" if t == "sessions" else None)
        rows = {}
        for r in c.execute('select * from "%s"' % t):
            d = dict(zip(cols, r))
            rows[str(d.get(key)) + ("|" + str(d.get("scope_id")) if t == "config" else "")] = {
                "sid": d.get(sid_col) if sid_col else None, "json": d.get("json")}
        st["tab"][t] = rows
    c.close()
    return st


def sitzungsdaten(stand: dict, sid: str) -> dict:
    s = json.loads(stand["tab"]["sessions"][sid]["json"]) if sid in stand["tab"]["sessions"] else {}
    facts = [json.loads(r["json"]) for r in stand["tab"]["scene_facts"].values() if r["sid"] == sid]
    turns = [json.loads(r["json"]) for r in stand["tab"]["turns"].values() if r["sid"] == sid]
    wk = [json.loads(r["json"]) for r in stand["tab"]["witness_knowledge"].values() if r["sid"] == sid]
    return {"session": s, "facts": facts, "turns": turns, "wk": wk}


def ortsname(welt: dict, place_id: str | None) -> str | None:
    for pl in welt.get("places") or []:
        if pl.get("id") == place_id:
            return pl.get("name")
    return None


def wahrnehmend(rt: dict) -> bool:
    try:
        bew = float(rt.get("consciousness", 1))
    except Exception:
        bew = 1.0
    return bew >= 0.5 and not rt.get("schlaeft")


def neue_log_zeilen(logordner: Path, vorher: dict) -> list[dict]:
    zeilen = []
    for f in sorted(logordner.glob("*.log")):
        start = vorher.get(f.name, 0)
        with f.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(start)
            for z in fh:
                try:
                    zeilen.append(json.loads(z))
                except Exception:
                    pass
    return zeilen


def log_stand(logordner: Path) -> dict:
    return {f.name: f.stat().st_size for f in logordner.glob("*.log")} if logordner.is_dir() else {}


# ---------------------------------------------------------------- Bewertung (V1.2)
ROUTE = {"puppet": "/api/kernel/puppet", "avatar": "/api/kernel/prepare", "gott": "/api/kernel/god", "regie": "/api/kernel/regie"}
COMMIT_OK = ("PASS", "INPUT_COMMITTED")


def haupt_spur(logz: list[dict], route: str) -> str | None:
    """Spur (trace_id) der Hauptanfrage: der erste UI_REQUEST an die Hauptroute dieses Falls."""
    return next((z.get("trace_id") for z in logz if z.get("stage") == "UI_REQUEST" and z.get("endpoint") == route), None)


def passt(w: dict, f: dict, fig: dict) -> bool:
    if "kind" in w and f.get("kind") != w["kind"]:
        return False
    if "akteur" in w and f.get("actorId") != fig[w["akteur"]]:
        return False
    if "text" in w and w["text"].lower() not in str(f.get("text") or "").lower():
        return False
    if "betrifft" in w:
        m = fig[w["betrifft"]]
        if not (f.get("actorId") == m or f.get("targetId") == m or m in (f.get("affected_ids") or [])):
            return False
    return True


def wk_schluessel(w: dict) -> tuple[str, str]:
    return str(w.get("character_id") or w.get("characterId") or ""), str(w.get("fact_id") or w.get("factId") or "")


def bewerte(fall: dict, fig: dict, vor: dict, nach: dict, ui: dict, logz: list[dict], welt: dict, proxy: dict,
            zip_info: dict, reader: tuple, namen: dict, ausgangsort: str) -> dict:
    sid = fall["sessionId"]
    e = fall["erwartung"]
    na = {int(k): v for k, v in (fall.get("nicht_zutreffend") or {}).items()}
    a, b = sitzungsdaten(vor, sid), sitzungsdaten(nach, sid)
    ids = lambda xs: {x.get("id") for x in xs}  # noqa: E731
    neu_f = [f for f in b["facts"] if f.get("id") not in ids(a["facts"])]
    neu_t = [t for t in b["turns"] if t.get("id") not in ids(a["turns"])]
    wk_a = {wk_schluessel(w) for w in a["wk"]}
    wk_b = {wk_schluessel(w): w.get("access") for w in b["wk"]}
    neu_wk = [w for w in b["wk"] if wk_schluessel(w) not in wk_a]
    # Eingabe und Folgezug werden nach dem SQLite-Commit getrennt (jeder Fact/Zug trägt seine Commit-Nummer)
    commits = sorted({int(x.get("commit") or 0) for x in neu_f + neu_t})
    erste = commits[0] if commits else None
    haupt_f = [f for f in neu_f if erste is not None and int(f.get("commit") or 0) == erste]
    folge_f = [f for f in neu_f if erste is not None and int(f.get("commit") or 0) > erste]
    folge_t = [t for t in neu_t if erste is not None and int(t.get("commit") or 0) > erste and t.get("role") == "character"]
    rt_a, rt_b = a["session"].get("runtimes") or {}, b["session"].get("runtimes") or {}
    sc_a, sc_b = a["session"].get("scene") or {}, b["session"].get("scene") or {}
    ort_a = ortsname(welt, sc_a.get("placeId"))
    praesent_a = set(sc_a.get("presentIds") or [])
    abwesend = {k for k in set(rt_a) | set(fig.values()) if k not in praesent_a}
    route = ROUTE[fall["modus"]]
    tm = haupt_spur(logz, route)
    tm_log = [z for z in logz if tm and z.get("trace_id") == tm]
    g: dict = {}

    def setze(nr, status, beleg):
        g[nr] = {"glied": nr, "name": GLIEDER[nr - 1], "status": status, "beleg": beleg}

    # 01 SOLL
    setze(1, "GRUEN" if "Z." in fall.get("soll", "") and "haupt" in e else "BLOCKIERT", fall.get("soll") or "kein SOLL im Katalog")
    # 02 ZIP/DB
    setze(2, "GRUEN" if zip_info.get("original_db_unveraendert") else "ROT",
          "ZIP %s…, DB-Kopie aus Original %s… (Original unverändert: %s)" % (zip_info["zip_sha"][:16], zip_info["db_sha"][:16],
                                                                            zip_info.get("original_db_unveraendert")))
    # 03 UI-Bedienung
    schritte = ui.get("schritte") or []
    if ui.get("fehler"):
        setze(3, "BLOCKIERT", "UI-Treiber: " + ui["fehler"])
    elif not any(s.startswith("Senden: ") for s in schritte) or "Seite neu geladen" not in schritte:
        setze(3, "BLOCKIERT", "Bedienung unvollständig: %s" % schritte)
    else:
        setze(3, "GRUEN", "; ".join(schritte))
    # 04 gesendete IDs
    haupt_req = [r for r in ui.get("anfragen") or [] if r["pfad"] == route]
    if not haupt_req:
        setze(4, "ROT", "Hauptanfrage %s wurde nicht gesendet" % route)
    else:
        r0, f4 = haupt_req[0], []
        if r0.get("sessionId") != sid:
            f4.append("sessionId %s statt %s" % (r0.get("sessionId"), sid))
        if fall["modus"] == "puppet" and r0.get("figur") != fig[fall["figur"]]:
            f4.append("Figur %s statt %s" % (r0.get("figur"), fig[fall["figur"]]))
        if fall.get("ziel") and r0.get("ziel") != fig[fall["ziel"]]:
            f4.append("UI-Ziel %s statt %s" % (r0.get("ziel"), fig[fall["ziel"]]))
        if (r0.get("text") or "").strip() != fall["text"]:
            f4.append("Text abweichend")
        setze(4, "ROT" if f4 else "GRUEN", "; ".join(f4) or "Route %s, Sitzung %s, Figur %s, UI-Ziel %s, Text gleich" % (
            route, r0.get("sessionId"), r0.get("figur"), r0.get("ziel")))
    # 05 Route und erste Bindung - in DER Spur der Hauptanfrage
    haupt_resp = [r for r in ui.get("antworten") or [] if r["pfad"] == route]
    st = haupt_resp[0]["status"] if haupt_resp else None
    f5 = []
    if st != e.get("haupt"):
        f5.append("HTTP %s statt %s" % (st, e.get("haupt")))
    if not tm:
        f5.append("keine Spur der Hauptanfrage im Live-Log")
    # erste serverseitige Bindung (Kettenvertrag §16 Zeile 5): die Spur gehört zu DIESER Sitzung und bindet serverseitig
    if not any((z.get("stage") == "KERNEL_BIND" and z.get("resolved_session_id") == sid) or
               (z.get("stage") == "TURN_START" and z.get("session_id") == sid) for z in tm_log):
        f5.append("Hauptspur gehört nicht nachweislich zu dieser Sitzung")
    if not any(z.get("stage") in ("KERNEL_BIND", "TARGET_BIND") for z in tm_log):
        f5.append("keine serverseitige Bindung (KERNEL_BIND/TARGET_BIND) in der Hauptspur")
    if fall["modus"] == "puppet" and not any(z.get("stage") == "TARGET_BIND" and z.get("speaker_id") == fig[fall["figur"]] for z in tm_log):
        f5.append("TARGET_BIND bindet den Sprecher nicht")
    setze(5, "ROT" if f5 else "GRUEN", ("; ".join(f5) + " | " if f5 else "") + "HTTP %s, Spur %s: %s, Meldung: %s" % (
        st, tm, ",".join(sorted({z.get("stage") for z in tm_log}))[:160], (haupt_resp[0]["meldung"][:140] if haupt_resp else "")))
    # 06 Writer und Commit in der Hauptspur
    commit_tm = [z for z in tm_log if z.get("stage") == "SQLITE_COMMIT" and z.get("status") in COMMIT_OK]
    if e.get("keine_wirkung"):
        ok6 = not neu_f and not neu_t and not commit_tm
        setze(6, "GRUEN" if ok6 else "ROT", "neue Facts %d, neue Züge %d, Commits der Hauptspur %d (erwartet: keine)" % (
            len(neu_f), len(neu_t), len(commit_tm)))
    else:
        geschrieben = bool(haupt_f or [t for t in neu_t if int(t.get("commit") or 0) == erste])
        if e.get("schreibpflicht", True) and not geschrieben:
            setze(6, "ROT", "keine Haupt-Facts/-Züge geschrieben (Commits der Hauptspur %d)" % len(commit_tm))
        elif geschrieben and not commit_tm:
            setze(6, "ROT", "Daten in SQLite, aber kein SQLITE_COMMIT in der Hauptspur %s" % tm)
        else:
            setze(6, "GRUEN", "Writer: %d Haupt-Facts, Commit %s in Spur %s (%s)" % (
                len(haupt_f), erste, tm, ",".join(z.get("status") for z in commit_tm) or "nichts geschrieben, zulässig"))
    # 07 Ausgangslage laut Katalog (sonst ist der Fall wertlos)
    soll_praesent = {fig[x] for x in fall["anwesend"]}
    f7 = []
    if praesent_a != soll_praesent:
        f7.append("anwesend %s statt %s" % (sorted(praesent_a), sorted(soll_praesent)))
    if ort_a != ausgangsort:
        f7.append("Ort %s statt %s" % (ort_a, ausgangsort))
    for pid in sorted(soll_praesent):
        r = rt_a.get(pid) or {}
        if r.get("position") != ausgangsort or not wahrnehmend(r):
            f7.append("%s Position %s, wahrnehmend %s" % (pid, r.get("position"), wahrnehmend(r)))
    setze(7, "BLOCKIERT" if f7 else "GRUEN", "; ".join(f7) or "vorher: %s in %s, alle wahrnehmungsfähig; %d Facts, %d Züge (Nur-Lese-Verbindung)" % (
        sorted(praesent_a), ort_a, len(a["facts"]), len(a["turns"])))
    # 08 Zustand nach dem Write lesbar
    setze(8, "GRUEN" if b["session"] and isinstance(sc_b.get("presentIds"), list) else "ROT",
          "nachher: %d Facts, %d Züge, anwesend %s, Ort %s" % (len(b["facts"]), len(b["turns"]), sc_b.get("presentIds"), sc_b.get("placeId")))
    # 09 Inhalt der Haupt-Facts
    f9 = []
    if e.get("keine_wirkung"):
        if neu_f:
            f9.append("Facts gespeichert, obwohl keine Wirkung erwartet: %s" % [str(f.get("text"))[:40] for f in neu_f[:3]])
    elif not (e.get("neu") or e.get("nicht")):
        f9.append("BLOCKIERT: Katalog nennt keine Fact-Erwartung")
    for w in e.get("neu") or []:
        treffer = [f for f in haupt_f if passt(w, f, fig)]
        if not treffer:
            f9.append("fehlt: %s" % w)
        elif "ziel" in w and not any(f.get("targetId") == fig.get(w["ziel"]) for f in treffer):
            f9.append("%s an %s statt %s" % (w.get("kind"), [f.get("targetId") for f in treffer], fig.get(w["ziel"])))
    for w in e.get("nicht") or []:
        treffer = [f for f in haupt_f if passt(w, f, fig)]
        if treffer:
            f9.append("verboten vorhanden: %s von %s: %s" % (treffer[0].get("kind"), treffer[0].get("actorId"), str(treffer[0].get("text"))[:50]))
    if e.get("keine_neue_figur"):
        bekannte = set(fig.values()) | set(rt_a)
        fremd = [f.get("actorId") for f in neu_f if f.get("actorId") and f.get("actorId") not in bekannte | {"god", "regie", "user"}]
        if fremd or set(rt_b) - set(rt_a) or set(sc_b.get("presentIds") or []) - set(rt_a):
            f9.append("unbekannte Figur angelegt: %s" % (fremd or sorted((set(rt_b) | set(sc_b.get("presentIds") or [])) - set(rt_a))))
    beleg9 = "Haupt-Facts: " + ("; ".join("%s/%s/%s→%s" % (f.get("kind"), f.get("actorId"), str(f.get("text"))[:50], f.get("targetId")) for f in haupt_f[:6]) or "keine")
    st9 = "BLOCKIERT" if any(x.startswith("BLOCKIERT") for x in f9) else ("ROT" if f9 else "GRUEN")
    setze(9, st9, ("; ".join(f9) + " | " if f9 else "") + beleg9)
    # 10 Wissen: Zeugen anwesend und wahrnehmend, Abwesende ohne Wissen, Zeugenwissen je Zeuge, nichts ohne Zeugenschaft
    f10 = []
    for f in neu_f:
        rt = rt_a if f in haupt_f else rt_b
        ort = ortsname(welt, f.get("placeId") or f.get("scene_id"))
        zeugen = [str(z) for z in f.get("witnessedBy") or []]
        akteur = str(f.get("actorId") or "")
        for z in zeugen:
            if z in abwesend:
                f10.append("abwesende Figur %s ist Zeuge von '%s'" % (z, str(f.get("text"))[:30]))
        if f.get("kind") not in BEOBACHTBAR:
            # innerer Zustand / God-Setzung: Wissen nur bei Handelndem, Ziel, Betroffenen (Z.1340-1352)
            erlaubt = {akteur, str(f.get("targetId"))} | {str(x) for x in f.get("affected_ids") or []}
            fremde = [z for z in zeugen if z not in erlaubt]
            if fremde:
                f10.append("innerer Zustand '%s' bei anderen: %s" % (str(f.get("text"))[:30], fremde))
            continue
        for z in zeugen:
            if z == akteur:
                continue    # selbst getan (Z.1340)
            r = rt.get(z) or {}
            if ort and r.get("position") != ort:
                f10.append("%s bezeugt '%s' in %s, ist aber in %s" % (z, str(f.get("text"))[:30], ort, r.get("position")))
            elif not wahrnehmend(r):
                f10.append("%s bezeugt '%s', nimmt aber nicht wahr (Bewusstsein %s)" % (z, str(f.get("text"))[:30], r.get("consciousness")))
            if wk_b.get((z, str(f.get("id")))) not in pa.WISSENS_ZUGANG:
                f10.append("Zeuge %s ohne kanonisches Zeugenwissen zu '%s'" % (z, str(f.get("text"))[:30]))
        if e.get("zeugen") and f in haupt_f and ort:
            soll = {k for k, r in rt_a.items() if k in praesent_a and r.get("position") == ort and wahrnehmend(r)}
            if set(zeugen) != soll:
                f10.append("Zeugen von '%s' %s statt %s" % (str(f.get("text"))[:30], sorted(zeugen), sorted(soll)))
    fakten = {str(f.get("id")): f for f in b["facts"]}
    for w in neu_wk:
        c, fid = wk_schluessel(w)
        f = fakten.get(fid) or {}
        if c in abwesend:
            f10.append("abwesende Figur %s erhielt Zeugenwissen zu %s" % (c, fid))
        elif c not in {str(x) for x in f.get("witnessedBy") or []} | {str(f.get("actorId")), str(f.get("targetId"))} | {str(x) for x in f.get("affected_ids") or []}:
            f10.append("Zeugenwissen ohne Zeugenschaft: %s zu '%s'" % (c, str(f.get("text"))[:30]))
    for z in (e.get("folgezug") or {}).get("zeugen_nicht") or []:
        for f in folge_f:
            if f.get("kind") in BEOBACHTBAR and fig[z] in (f.get("witnessedBy") or []):
                f10.append("%s als Zeuge im Folgezug: '%s'" % (z, str(f.get("text"))[:40]))
                break
    if not neu_f and not neu_wk:
        setze(10, "GRUEN" if e.get("keine_wirkung") or e.get("schreibpflicht") is False else "BLOCKIERT",
              "kein Wissen entstanden" + ("" if e.get("keine_wirkung") or e.get("schreibpflicht") is False else " - Wissenskette nicht prüfbar"))
    else:
        setze(10, "ROT" if f10 else "GRUEN", "; ".join(f10[:6]) or "%d Facts, %d neue Zeugenwissen: Zeugen anwesend und wahrnehmend, Abwesende %s ohne Wissen" % (
            len(neu_f), len(neu_wk), sorted(abwesend)))
    # 11 Runtime / Körper / Szene (Anwesenheit ist in JEDEM Fall kanonisch, Z.1327)
    f11 = []
    for w in e.get("laufzeit") or []:
        ist = (rt_b.get(fig[w["figur"]]) or {}).get(w["feld"])
        if ist != w["gleich"]:
            f11.append("%s.%s = %r statt %r" % (w["figur"], w["feld"], ist, w["gleich"]))
    for z in e.get("keine_koerperwirkung") or []:
        ra, rb = rt_a.get(fig[z]) or {}, rt_b.get(fig[z]) or {}
        for k in ("consciousness", "posture", "schlaeft", "canSpeak", "pain"):
            if ra.get(k) != rb.get(k):
                f11.append("%s.%s %r→%r" % (z, k, ra.get(k), rb.get(k)))
    ort_b = ortsname(welt, sc_b.get("placeId"))
    for pid in sc_b.get("presentIds") or []:
        pos = (rt_b.get(pid) or {}).get("position")
        if pos != ort_b:
            f11.append("%s anwesend in Szene '%s', Position aber '%s'" % (pid, ort_b, pos))
    for pid, r in rt_b.items():
        if ort_b and r.get("position") == ort_b and pid not in (sc_b.get("presentIds") or []):
            f11.append("%s ist in '%s', fehlt aber in der Anwesenheit" % (pid, ort_b))
    setze(11, "ROT" if f11 else "GRUEN", "; ".join(f11[:6]) or "Laufzeit, Körper und Anwesenheit stimmig (Szene %s)" % ort_b)
    # 12 Reader liefert dieselben Facts mit gleichem Inhalt
    st12, j12 = reader
    rd = {f.get("id"): f for f in ((j12.get("session") or {}).get("facts") or [])}
    f12 = []
    for f in neu_f:
        r = rd.get(f.get("id"))
        if not r:
            f12.append("fehlt %s" % f.get("id"))
        elif any(r.get(k) != f.get(k) for k in ("kind", "actorId", "targetId", "text")):
            f12.append("Inhalt abweichend %s" % f.get("id"))
    setze(12, "GRUEN" if st12 == 200 and not f12 else "ROT", "GET /api/sessions: HTTP %s, %d von %d neuen Facts gleich; %s" % (
        st12, len(neu_f) - len(f12), len(neu_f), "; ".join(f12[:3]) or "ok"))
    # 13 Wissen im Folgezug - gebunden an Spur, Sitzung, Sprecher, Zeugenwissen
    fz = e.get("folgezug") or {}
    wissen_eingabe = {"sid": sid, "soll": fz.get("wissen"), "namen": namen,
                      "haupt_facts": [{k: f.get(k) for k in ("id", "kind", "actorId", "targetId", "text", "witnessedBy")} for f in haupt_f],
                      "folge_facts": [{"id": f.get("id")} for f in folge_f],
                      "folge_turns": [{"role": t.get("role"), "speakerId": t.get("speakerId")} for t in folge_t],
                      "wk_nachher": [{"character_id": c, "fact_id": fid, "access": acc} for (c, fid), acc in wk_b.items()],
                      "logz": [{k: z.get(k) for k in ("ts", "stage", "trace_id", "status", "record_id", "turn_facts", "resolved_session_id",
                                                     "resolved_speaker_id", "speaker", "sections", "source", "error", "endpoint")}
                               for z in logz if z.get("stage") in ("WRITER", "KERNEL_BIND", "PROMPT", "SQLITE_COMMIT", "MODEL_REPLY", "UI_REQUEST")]}
    if 13 in na:
        setze(13, "NICHT_ZUTREFFEND", na[13])
    elif fz.get("wissen") not in ("erhalten", "nicht_erhalten"):
        setze(13, "BLOCKIERT", "Katalog legt den Wissensnachweis im Folgezug nicht fest")
    else:
        s13, b13 = pa.wissen_im_folgezug(wissen_eingabe)
        setze(13, s13, b13)
    # 14 Folgezug: Modellantwort und Commit in der Spur des Folgezugs
    spur_f = {z.get("trace_id") for z in logz if z.get("stage") == "WRITER" and
              ({str(z.get("record_id"))} | set(__import__("re").findall(r"fact_[0-9a-f_]+", str(z.get("turn_facts") or "")))) & {str(f.get("id")) for f in folge_f}}
    if 14 in na:
        setze(14, "NICHT_ZUTREFFEND", na[14])
    else:
        mr = [z for z in logz if z.get("trace_id") in spur_f and z.get("stage") == "MODEL_REPLY"]
        cm = [z for z in logz if z.get("trace_id") in spur_f and z.get("stage") == "SQLITE_COMMIT" and z.get("status") == "PASS"]
        f14 = []
        if not ui.get("folgezug_commit"):
            f14.append("Oberfläche hat keinen Folgezug gespeichert (%s)" % (ui.get("folgezug_hinweis") or "kein Commit"))
        if not folge_t:
            f14.append("kein Folgezug einer Figur in SQLite")
        if len(spur_f) != 1:
            f14.append("Spur des Folgezugs nicht eindeutig (%d)" % len(spur_f))
        if not any(str(z.get("source")) == "llm" and str(z.get("error")) in ("None", "") for z in mr):
            f14.append("keine fehlerfreie Modellantwort (MODEL_REPLY source=llm) in der Folgezug-Spur")
        if not cm:
            f14.append("kein SQLITE_COMMIT PASS in der Folgezug-Spur")
        if not proxy.get("anfragen"):
            f14.append("kein Modellaufruf über den Prüfer-Proxy")
        setze(14, "ROT" if f14 else "GRUEN", "; ".join(f14) or "Folgezug von %s: Modellantwort und Commit in Spur %s" % (
            sorted({t.get("speakerId") for t in folge_t}), next(iter(spur_f))))
    # 15 Zustand im Folgezug: Sprecher anwesend und sprechfähig, Vorgaben, Haupt-Facts erhalten
    if 15 in na:
        setze(15, "NICHT_ZUTREFFEND", na[15])
    else:
        sprecher = sorted({t.get("speakerId") for t in folge_t})
        f15 = []
        if not folge_t:
            f15.append("kein Folgezug")
        for s_ in sprecher:
            r = rt_b.get(s_) or {}
            if s_ not in praesent_a | set(sc_b.get("presentIds") or []):
                f15.append("%s spricht, war aber nicht anwesend" % s_)
            if r.get("canSpeak") is False or not wahrnehmend(r):
                f15.append("%s spricht, ist aber nicht sprechfähig (canSpeak %s, Bewusstsein %s)" % (s_, r.get("canSpeak"), r.get("consciousness")))
        for z in fz.get("sprecher_nicht") or []:
            if fig[z] in sprecher:
                f15.append("%s spricht im Folgezug, obwohl ausgeschlossen" % z)
        if fz.get("antwort_von") and fig[fz["antwort_von"]] not in sprecher:
            f15.append("Antwort nicht von %s, sondern %s" % (fz["antwort_von"], sprecher))
        if [f.get("id") for f in haupt_f if f.get("id") not in ids(b["facts"])]:
            f15.append("Haupt-Facts im Folgezug verschwunden")
        setze(15, "ROT" if f15 else "GRUEN", "; ".join(f15) or "Folgezug-Sprecher %s anwesend und sprechfähig, Haupt-Facts erhalten" % sprecher)
    # 16 nach dem Neustart (wird im Hauptlauf gesetzt)
    setze(16, "BLOCKIERT", "Neustart-Prüfung steht aus")
    # 17 Rückanzeige im Gesprächsverlauf nach Neuladen
    vl = ui.get("verlauf_nach_reload")
    f17 = []
    if not (e.get("ui_enthaelt") or e.get("ui_nicht") or e.get("ui_meldung")):
        setze(17, "BLOCKIERT", "Katalog nennt keine sichtbare Rückanzeige")
    elif vl is None:
        setze(17, "BLOCKIERT", "kein eindeutiger Gesprächsverlauf (role=log) in der Oberfläche")
    else:
        if e.get("ui_enthaelt") and e["ui_enthaelt"].lower() not in vl.lower():
            f17.append("nach Neuladen nicht im Verlauf: '%s'" % e["ui_enthaelt"])
        if e.get("ui_nicht") and e["ui_nicht"].lower() in vl.lower():
            f17.append("nach Neuladen im Verlauf, obwohl nicht gespeichert: '%s'" % e["ui_nicht"])
        if e.get("ui_meldung") and not (ui.get("meldungen") or []):
            f17.append("keine sichtbare Meldung")
        setze(17, "ROT" if f17 else "GRUEN", "; ".join(f17) or "Verlauf nach Neuladen stimmt; Meldungen: %s" % (ui.get("meldungen") or ["keine"])[:2])
    # 18 Isolation
    f18 = []
    for t, rows_a in vor["tab"].items():
        rows_b = nach["tab"].get(t, {})
        for k in set(rows_a) | set(rows_b):
            ra, rb = rows_a.get(k), rows_b.get(k)
            sid_x = (ra or rb or {}).get("sid")
            if t == "users" and k == "admin":
                continue   # das bedienende Profil selbst (UI-Profilwahl schreibt es); Glied 18 betrifft ANDERE Nutzer
            if t in ISOLATIONS_TABELLEN_STAMM or (sid_x not in (sid, None) or (t == "sessions" and k != sid)):
                if (ra or {}).get("json") != (rb or {}).get("json"):
                    f18.append("%s/%s verändert" % (t, k[:40]))
    setze(18, "ROT" if f18 else "GRUEN", "; ".join(f18[:6]) or "andere Sitzungen, Figurenstamm, Welt, Nutzer und Konfiguration unverändert")
    setze(19, "GRUEN", "Kandidat frisch aus ZIP %s… in eigenem Arbeitsordner entpackt und gebaut" % zip_info["zip_sha"][:16])
    if proxy.get("fehlgriffe"):
        for x in g.values():
            if x["status"] == "GRUEN" and x["glied"] in (5, 6, 9, 10, 11, 13, 14, 15):
                x["status"] = "BLOCKIERT"
                x["beleg"] += " | Modellaufnahme fehlte (%d Fehlgriffe)" % proxy["fehlgriffe"]
    beleg = {"neue_facts": [{"commit": f.get("commit"), "kind": f.get("kind"), "actor": f.get("actorId"), "target": f.get("targetId"),
                             "text": str(f.get("text") or "")[:120], "ort": f.get("placeId"), "zeugen": f.get("witnessedBy"),
                             "betroffen": f.get("affected_ids")} for f in sorted(neu_f, key=lambda x: int(x.get("seq") or 0))],
             "neue_zuege": [{"commit": t.get("commit"), "turn": t.get("turn"), "rolle": t.get("role"), "sprecher": t.get("speakerId"),
                             "rede": str(t.get("speech") or "")[:100], "handlung": str(t.get("action") or "")[:100]} for t in neu_t],
             "neues_zeugenwissen": [list(wk_schluessel(w)) + [w.get("access")] for w in neu_wk],
             "anwesend_vorher": sorted(praesent_a), "anwesend_nachher": sc_b.get("presentIds"), "ort_nachher": sc_b.get("placeId"),
             "positionen_nachher": {k: (v.get("position"), v.get("consciousness"), v.get("canSpeak")) for k, v in rt_b.items()}}
    return {"glieder": [g[n] for n in sorted(g)], "neue_fact_ids": [f.get("id") for f in neu_f], "haupt_status": st, "beleg": beleg,
            "wissen_eingabe": wissen_eingabe}


# ---------------------------------------------------------------- Hauptlauf
def ui_lauf(spec: dict, arbeits: Path, ns) -> dict:
    sp = arbeits / ("fall_%s%s.json" % (spec["id"], "_ansehen" if spec.get("nurAnsehen") else ""))
    sp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(["node", str(HIER / "kp_ui.js"), str(sp)], capture_output=True, text=True, timeout=600,
                       env={**os.environ, "KP_PLAYWRIGHT": ns.playwright})
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"fehler": (r.stderr or r.stdout)[-400:]}


def lauf(ns) -> int:
    zip_pfad = Path(ns.kandidat).resolve()
    orig_db = Path(ns.db).resolve()
    aus = Path(ns.ausgabe).resolve()
    aus.mkdir(parents=True, exist_ok=True)
    (aus / "bilder").mkdir(exist_ok=True)
    katalog = json.loads((HIER / "kp_faelle.json").read_text(encoding="utf-8"))
    fig = katalog["figuren"]
    wahl = [x for x in (ns.faelle or "").split(",") if x]
    faelle = [f for f in katalog["faelle"] if not wahl or f["id"] in wahl or f["id"].split("_")[0] in wahl]
    zip_info = {"zip": zip_pfad.name, "zip_sha": sha_datei(zip_pfad), "db_sha": sha_datei(orig_db),
                "faelle_sha": sha_datei(HIER / "kp_faelle.json"), "pruefer_sha": sha_datei(Path(__file__)),
                "auswertung_sha": sha_datei(HIER.parent / "pm_auswertung.py")}
    ergebnis = {"pruefer": "MATRIX10_KETTENPRUEFER_V12", "zeit_utc": datetime.now(timezone.utc).isoformat(),
                "modus": ns.modus, "mutation": ns.mutation, "basis": zip_info, "angefordert": [f["id"] for f in faelle],
                "faelle": [], "vorbereitung": {}}
    arbeits = Path(tempfile.mkdtemp(prefix="kp_"))
    server = None
    proxy_srv = None
    try:
        if wahl and len(faelle) != len(set(wahl)):
            raise RuntimeError("unbekannte Fallauswahl %s" % wahl)
        root = entpacken(zip_pfad, arbeits)
        for name, sha in katalog["soll_quellen"].items():
            p = root / name
            ok = p.is_file() and sha_datei(p) == sha
            ergebnis["vorbereitung"]["soll_" + name] = "GRUEN" if ok else "ROT: Hash abweichend oder fehlt"
            if not ok:
                ergebnis.setdefault("kandidat_rot", []).append("Sollquelle %s fehlt oder Hash abweichend" % name)
        if ns.mutation:
            import kp_mutationen
            ergebnis["vorbereitung"]["mutation"] = kp_mutationen.anwenden(root, ns.mutation)
        st, txt = frontend_bauen(root, Path(ns.node_cache) if ns.node_cache else None, aus / "bau.log")
        ergebnis["vorbereitung"]["frontend"] = st + ": " + txt
        if st == "ROT":
            raise KandidatRot("Frontend des Kandidaten: " + txt)
        if st != "GRUEN":
            raise RuntimeError("Frontend: " + txt)
        db = db_kopie(orig_db, root)
        proxy_srv, proxy_z = kp_modellproxy.starte(ns.modus, Path(ns.aufnahme).resolve(), PROXY_PORT)
        server = server_start(root, aus / "server.log")
        c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        welt = json.loads(c.execute("select json from worlds where id=?", (katalog["welt"],)).fetchone()[0])
        namen = {}
        for cid, js in c.execute("select id, json from characters"):
            try:
                namen[str(cid)] = str(json.loads(js).get("name") or "")
            except Exception:
                pass
        c.close()
        for f in faelle:
            f = dict(f)
            f["sessionId"] = "ses_kp_fall_%02d" % f["nr"]
            body = {"id": f["sessionId"], "worldId": katalog["welt"], "name": "Kettenprüfer Fall %02d" % f["nr"],
                    "presentIds": [fig[x] for x in f["anwesend"]]}
            if f.get("avatar"):
                body.update({"avatarId": fig[f["avatar"]], "role": "teilnehmer", "alias": ""})
            stc, _ = http("POST", "/api/sessions", body)
            if stc != 200:
                raise RuntimeError("Sitzung für %s nicht anlegbar (HTTP %s)" % (f["id"], stc))
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/__fall/%s" % (PROXY_PORT, f["id"]), data=b"", method="POST"))
            vor_proxy = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/__stand" % PROXY_PORT).read())
            vor = roh_stand(db)
            lg = log_stand(root / "logs")
            ui = ui_lauf({"id": f["id"], "ui": UI, "sessionId": f["sessionId"], "modus": f["modus"],
                          "figur": fig.get(f.get("figur")) if f.get("figur") else None,
                          "ziel": fig.get(f.get("ziel")) if f.get("ziel") else None,
                          "text": f["text"], "bild": str(aus / "bilder" / f["id"])}, arbeits, ns)
            time.sleep(2)
            nach = roh_stand(db)
            logz = neue_log_zeilen(root / "logs", lg)
            nach_proxy = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/__stand" % PROXY_PORT).read())
            proxy = {k: nach_proxy.get(k, 0) - vor_proxy.get(k, 0) for k in ("anfragen", "treffer", "fehlgriffe", "weitergeleitet", "upstream_fehler")}
            # Fehlgriffe VOR dem ersten Commit dieses Falls verfälschen die Hauptwirkung; spätere betreffen nur den Folgezug
            fzeit = [t for t in nach_proxy.get("fehlgriff_zeiten", []) if t not in vor_proxy.get("fehlgriff_zeiten", [])]
            commits = sorted(datetime.fromisoformat(str(z["ts"])).timestamp() for z in logz
                             if z.get("stage") == "SQLITE_COMMIT" and z.get("status") in COMMIT_OK and z.get("ts"))
            proxy["fehlgriffe_vor_hauptcommit"] = len([t for t in fzeit if not commits or t < commits[0]])
            zip_info["original_db_unveraendert"] = sha_datei(orig_db) == zip_info["db_sha"]
            reader = http("GET", "/api/sessions/" + f["sessionId"])
            bew = bewerte(f, fig, vor, nach, ui, logz, welt, proxy, zip_info, reader, namen, katalog["ausgangsort"])
            (aus / ("ui_%s.json" % f["id"])).write_text(json.dumps(ui, ensure_ascii=False, indent=1), encoding="utf-8")
            (aus / ("log_%s.jsonl" % f["id"])).write_text("\n".join(json.dumps(z, ensure_ascii=False) for z in logz), encoding="utf-8")
            (aus / ("wissen_%s.json" % f["id"])).write_text(json.dumps(bew.pop("wissen_eingabe"), ensure_ascii=False), encoding="utf-8")
            ergebnis["faelle"].append({"id": f["id"], "achse": f["achse"], "art": f["art"], "text": f["text"], "sessionId": f["sessionId"],
                                       "modell": proxy, **bew})
            print("[vor Neustart] %s: %s" % (f["id"], "; ".join(
                "%02d %s %s" % (x["glied"], x["status"], x["beleg"][:90]) for x in bew["glieder"] if x["status"] in ("ROT", "BLOCKIERT") and x["glied"] != 16)[:500]), flush=True)
        # 16 Neustart: Server stoppen, starten, Rohstand, Reader UND Oberfläche aus dem gespeicherten Zustand
        vor_neustart = roh_stand(db)
        server_stop(server)
        server = server_start(root, aus / "server.log")
        nach_neustart = roh_stand(db)
        for fe in ergebnis["faelle"]:
            kf = next(k for k in katalog["faelle"] if k["id"] == fe["id"])
            sid = fe["sessionId"]
            a, b = sitzungsdaten(vor_neustart, sid), sitzungsdaten(nach_neustart, sid)
            st16, j16 = http("GET", "/api/sessions/" + sid)
            rd = {f.get("id") for f in ((j16.get("session") or {}).get("facts") or [])}
            fehlt = [i for i in fe["neue_fact_ids"] if i not in rd]
            gleich = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
            ui16 = ui_lauf({"id": fe["id"], "ui": UI, "sessionId": sid, "nurAnsehen": True, "bild": str(aus / "bilder" / fe["id"])}, arbeits, ns)
            vl = ui16.get("verlauf_nach_neustart")
            e = kf["erwartung"]
            f16 = []
            if not gleich:
                f16.append("SQLite-Stand nach Neustart verändert")
            if st16 != 200 or fehlt:
                f16.append("Reader HTTP %s, fehlende Facts %s" % (st16, fehlt[:3]))
            if ui16.get("fehler") or vl is None:
                f16.append("Oberfläche nach Neustart nicht prüfbar (%s)" % (ui16.get("fehler") or "kein Verlauf")[:120])
            else:
                if e.get("ui_enthaelt") and e["ui_enthaelt"].lower() not in vl.lower():
                    f16.append("nach Neustart nicht im Verlauf: '%s'" % e["ui_enthaelt"])
                if e.get("ui_nicht") and e["ui_nicht"].lower() in vl.lower():
                    f16.append("nach Neustart im Verlauf, obwohl nicht gespeichert: '%s'" % e["ui_nicht"])
            g16 = next(x for x in fe["glieder"] if x["glied"] == 16)
            g16["status"] = ("BLOCKIERT" if any(x.startswith("Oberfläche nach Neustart nicht prüfbar") for x in f16) and len(f16) == 1
                             else ("ROT" if f16 else "GRUEN"))
            g16["beleg"] = "; ".join(f16) or "nach Server-Neustart: SQLite gleich, Reader vollständig, Verlauf in der Oberfläche stimmt"
        for fe in ergebnis["faelle"]:
            kf = next(k for k in katalog["faelle"] if k["id"] == fe["id"])
            s, gr = pa.fall_status(fe["glieder"] + [{"glied": 20, "status": "GRUEN"}], (kf.get("nicht_zutreffend") or {}).keys())
            rote = [("%02d %s: %s" % (x["glied"], x["name"], x["beleg"])) for x in fe["glieder"] if x["status"] in ("ROT", "BLOCKIERT")]
            fe["glieder"].append({"glied": 20, "name": GLIEDER[19], "status": s, "beleg": " | ".join(gr + rote) or "alle Glieder belegt"})
            fe["status"] = s
        if [f["id"] for f in ergebnis["faelle"]] != ergebnis["angefordert"]:
            raise RuntimeError("nicht alle angeforderten Fälle bewertet")
    except KandidatRot as ex:
        ergebnis.setdefault("kandidat_rot", []).append(str(ex))
    except Exception as ex:
        ergebnis["abbruch"] = "%s: %s" % (type(ex).__name__, ex)
    finally:
        if server:
            try:
                server_stop(server)
            except Exception as ex:
                ergebnis["abbruch"] = ergebnis.get("abbruch") or "%s: %s" % (type(ex).__name__, ex)
        if proxy_srv:
            proxy_srv.shutdown()
        if not ns.behalten:
            shutil.rmtree(arbeits, ignore_errors=True)
        else:
            ergebnis["arbeitsordner"] = str(arbeits)
    status = pa.lauf_gesamt([f.get("status") for f in ergebnis["faelle"]], ergebnis.get("kandidat_rot"), ergebnis.get("abbruch"))
    ergebnis["gesamt"] = status
    (aus / "ERGEBNIS.json").write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1), encoding="utf-8")
    z = ["MATRIX10 KETTENPRÜFER V1.2", "=" * 60, "GESAMT: %s" % status, "Kandidat: %s  SHA-256 %s" % (zip_info["zip"], zip_info["zip_sha"]),
         "Modell: %s   Mutation: %s   Fälle: %s" % (ns.modus, ns.mutation or "keine", ",".join(ergebnis["angefordert"])), ""]
    for k, v in ergebnis["vorbereitung"].items():
        z.append("Vorbereitung %s: %s" % (k, v))
    for k in ergebnis.get("kandidat_rot") or []:
        z.append("KANDIDAT ROT: " + k)
    if ergebnis.get("abbruch"):
        z.append("ABBRUCH: " + ergebnis["abbruch"])
    for fe in ergebnis["faelle"]:
        z += ["", "[%s] %s (%s, %s): %s" % (fe["status"], fe["id"], fe["achse"], fe["art"], fe["text"])]
        for x in fe["glieder"]:
            z.append("   %02d %-16s %s: %s" % (x["glied"], x["status"], x["name"], x["beleg"][:300]))
    (aus / "ERGEBNIS_LESEN.txt").write_text("\n".join(z) + "\n", encoding="utf-8")
    print("GESAMT:", status, "->", aus / "ERGEBNIS_LESEN.txt", flush=True)
    return {"GRUEN": 0, "ROT": 2}.get(status, 3)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="MATRIX10 Kettenprüfer V1.2")
    ap.add_argument("--kandidat", required=True, help="Produkt-ZIP (unverändert)")
    ap.add_argument("--db", required=True, help="Original-DB; es wird nur eine Kopie benutzt")
    ap.add_argument("--ausgabe", required=True)
    ap.add_argument("--modus", choices=("live", "wiedergabe"), default="live")
    ap.add_argument("--aufnahme", required=True, help="Ordner der Modellaufnahme (live: schreiben, wiedergabe: lesen)")
    ap.add_argument("--faelle", default="", help="Fall-IDs oder Kürzel, z.B. PU1,AV1 (leer = alle)")
    ap.add_argument("--mutation", default="", help="nur für die Selbstabnahme")
    ap.add_argument("--node-cache", default="", help="Ordner mit node_modules und package-lock.json")
    ap.add_argument("--playwright", default="playwright")
    ap.add_argument("--behalten", action="store_true")
    sys.exit(lauf(ap.parse_args()))
