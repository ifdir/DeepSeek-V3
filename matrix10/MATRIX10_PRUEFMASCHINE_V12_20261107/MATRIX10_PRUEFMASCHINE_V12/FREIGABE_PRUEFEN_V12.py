#!/usr/bin/env python3
"""MATRIX10 Freigabesperre V1.2 – Nachfolger von V1.1, unabhängig vom Produkt.

Korrekturen gegenüber V1.1 (unabhängige Negativprüfung vom 07.11.2026):
  1. Vollständigkeit erzwungen: jede Pflichtprüfung (pm_auswertung.pflicht_checks) muss GENAU einmal vorliegen,
     alle 16 Pflichtachsen müssen bewertet sein, jeder Pflichtfall mit genau 20 Gliedern; fehlt etwas: BLOCKIERT.
  2. Kettenprüfer-Ergebnis wird nicht geglaubt: Rückgabecode, 'gesamt', 'abbruch', ZIP-/Prüfer-/Katalog-Hash,
     Fallmenge und jeder Fallstatus werden nachgerechnet (pm_auswertung.kette_auswerten).
  3. Rückgabecodes von Bau, Typprüfung und pytest werden ausgewertet; Widersprüche ergeben BLOCKIERT.
  4. Unabhängigkeit: Die Maschine muss durch SELBSTABNAHME_V12.py abgenommen sein (ABNAHME_V12.json); jede
     Abweichung einer Maschinendatei - vor ODER nach dem Lauf - ergibt BLOCKIERT. Das Produkt läuft in einem
     eigenen Arbeitsordner; Prüfer, Sollwerte und Fallkatalog liegen nur in der Maschine.
Exitcodes: 0 GRÜN, 2 ROT, 3 BLOCKIERT.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import pm_auswertung as pa  # noqa: E402

REGELN = BASE / "PRUEFREGELN_V12.json"
sha = pa.sha


def pruef(checks: list, ident: str, status: str, detail: str, art: str = "vertrag"):
    assert status in ("PASS", "ROT", "BLOCKIERT", "UNGEPRUEFT")
    checks.append({"id": ident, "status": status, "detail": detail, "art": art})
    print("[%s] %s: %s" % (status, ident, detail[:300]), flush=True)


def junit_auswerten(xml_pfad: Path) -> dict:
    if not xml_pfad.is_file():
        return {"gelaufen": 0, "fehlschlaege": [], "fehler": [], "sammelfehler": ["keine JUnit-Datei"]}
    wurzel = ET.parse(xml_pfad).getroot()
    gelaufen, fehl, err, sammel = 0, [], [], []
    for tc in wurzel.iter("testcase"):
        e = tc.find("error")
        # pytest schreibt einen Sammelabbruch als <testcase classname="" name="tests.modul"><error message="collection failure">
        if e is not None and (e.get("message") == "collection failure" or not tc.get("classname")):
            sammel.append("%s: %s" % (tc.get("name", ""), ((e.text or "").strip().splitlines() or [""])[-1][:160]))
            continue
        gelaufen += 1
        name = "%s::%s" % (tc.get("classname", ""), tc.get("name", ""))
        if tc.find("failure") is not None:
            fehl.append(name)
        elif e is not None:
            err.append(name)
    if not gelaufen and not sammel and any(int(s.get("errors", 0)) > 0 for s in wurzel.iter("testsuite")):
        sammel.append("Testsuite meldet Fehler ohne einen einzigen Testfall")
    return {"gelaufen": gelaufen, "fehlschlaege": sorted(fehl), "fehler": sorted(err), "sammelfehler": sammel}


def normiere_testid(pytest_id: str) -> str:
    s = pytest_id.replace("/", ".").replace(".py::", "::", 1)
    teile = s.split("::")
    return "%s.%s::%s" % (teile[0], teile[1], teile[2]) if len(teile) == 3 else s


def lauf(ns) -> int:
    regeln = json.loads(REGELN.read_text(encoding="utf-8"))
    katalog_pfad = BASE / "kettenpruefer" / "kp_faelle.json"
    katalog = json.loads(katalog_pfad.read_text(encoding="utf-8"))
    kandidat = Path(ns.kandidat).resolve()
    bericht = BASE / ("ERGEBNIS_V12_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))
    logs = bericht / "LOGS"
    logs.mkdir(parents=True)
    checks: list = []
    achsen = {a: "UNGEPRUEFT" for a in regeln["pflichtachsen"]}
    meta = {"gate": "MATRIX10_FREIGABESPERRE_V12", "gate_sha256": sha(Path(__file__)), "regeln_sha256": sha(REGELN),
            "kandidat": kandidat.name, "zeit_utc": datetime.now(timezone.utc).isoformat()}
    ok, grund, msha = pa.manifest_pruefen(BASE)
    meta["abnahme_manifest_sha256"] = msha
    pruef(checks, "00_pruefmaschine_abgenommen", "PASS" if ok else "BLOCKIERT", grund, "nachweis")
    tmp = Path(tempfile.mkdtemp(prefix="gate12_"))
    try:
        geaendert = [n for n, h in (regeln.get("basis_sha256") or {}).items() if not (BASE / n).is_file() or sha(BASE / n) != h]
        pruef(checks, "00_basis_eingefroren", "BLOCKIERT" if geaendert or not regeln.get("basis_sha256") else "PASS",
              ("Basisdatei verändert/fehlt: " + ", ".join(geaendert)) if geaendert else "P22-Basis unverändert (Hash)", "nachweis")
        meta["kandidat_sha256"] = sha(kandidat)
        with zipfile.ZipFile(kandidat) as z:
            if z.testzip():
                raise RuntimeError("CRC defekt")
            wurzeln = {PurePosixPath(i.filename).parts[0] for i in z.infolist()}
            if any(i.filename.startswith("/") or ".." in PurePosixPath(i.filename).parts for i in z.infolist()) or len(wurzeln) != 1:
                raise RuntimeError("unsichere ZIP-Struktur")
            z.extractall(tmp)
            n_eintraege = len(z.infolist())
        root = tmp / next(iter(wurzeln))
        pruef(checks, "01_zip", "PASS", "SHA-256 %s, %d Einträge, CRC und Pfade in Ordnung" % (meta["kandidat_sha256"][:16], n_eintraege))
        for name, h in regeln["sollquellen"].items():
            p = root / name
            gut = p.is_file() and sha(p) == h
            pruef(checks, "02_soll_" + name, "PASS" if gut else "ROT", "eingefroren %s…" % h[:16] if gut else "fehlt oder Hash abweichend")
        e = regeln.get("quellen_entscheidung") or {}
        pruef(checks, "03_quellenregister", "PASS" if e.get("bestaetigt_von_vertragseigner") else "BLOCKIERT",
              e.get("text") or "Abweichung Kettenvertrag §0 noch nicht vom Vertragseigner bestätigt", "nachweis")
        # ---- Frontend VOR der Suite
        npm = shutil.which("npm")
        if not shutil.which("node") or not npm:
            pruef(checks, "04_frontend_bau", "BLOCKIERT", "Node/npm fehlen", "umgebung")
            pruef(checks, "05_typecheck_regression", "BLOCKIERT", "ohne Bau nicht prüfbar", "umgebung")
            pruef(checks, "05_typecheck_gesamt", "BLOCKIERT", "ohne Bau nicht prüfbar", "umgebung")
        else:
            cache = Path(ns.node_cache) if ns.node_cache else None
            if cache and (cache / "node_modules").exists() and sha(cache / "package-lock.json") == sha(root / "package-lock.json"):
                (root / "node_modules").symlink_to((cache / "node_modules").resolve())
            else:
                r = subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=root, capture_output=True, text=True, timeout=1500)
                (logs / "npm_ci.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
            if not (root / "node_modules").exists():
                pruef(checks, "04_frontend_bau", "BLOCKIERT", "Abhängigkeiten nicht installierbar (npm ci)", "umgebung")
                pruef(checks, "05_typecheck_regression", "BLOCKIERT", "ohne Bau nicht prüfbar", "umgebung")
                pruef(checks, "05_typecheck_gesamt", "BLOCKIERT", "ohne Bau nicht prüfbar", "umgebung")
            else:
                r = subprocess.run([npm, "run", "build:dist"], cwd=root, capture_output=True, text=True, timeout=900)
                (logs / "frontend_bau.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
                info = root / "frontend_dist" / ".build-info.json"
                bid = next((l.split("=", 1)[1].strip() for l in (root / "VERSION.txt").read_text(encoding="utf-8").splitlines() if l.startswith("BUILD_ID=")), None)
                gut = r.returncode == 0 and info.is_file() and json.loads(info.read_text(encoding="utf-8")).get("buildId") == bid
                pruef(checks, "04_frontend_bau", "PASS" if gut else "ROT", "gebaut, Kennung %s" % bid if gut else "Bau oder Kennung fehlerhaft (Exitcode %d)" % r.returncode)
                r = subprocess.run([npm, "run", "typecheck"], cwd=root, capture_output=True, text=True, timeout=600)
                (logs / "typecheck.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
                ist = sorted(re.sub(r"\(\d+,\d+\)", "", z) for z in (r.stdout + r.stderr).splitlines() if "error TS" in z)
                if (r.returncode == 0) != (not ist):
                    pruef(checks, "05_typecheck_regression", "BLOCKIERT", "Exitcode %d passt nicht zu %d gemeldeten Fehlern" % (r.returncode, len(ist)), "umgebung")
                    pruef(checks, "05_typecheck_gesamt", "BLOCKIERT", "Typprüfung widersprüchlich", "umgebung")
                else:
                    basis = (BASE / regeln["basis_typfehler"]).read_text(encoding="utf-8").splitlines()
                    neu = [z for z in ist if z not in basis or ist.count(z) > basis.count(z)]
                    weg = [z for z in basis if z not in ist]
                    pruef(checks, "05_typecheck_regression", "ROT" if neu else "PASS",
                          "TypeScript-Fehler %d (Basis P22 %d): neu %d, behoben %d%s" % (len(ist), len(basis), len(set(neu)), len(set(weg)),
                                                                                      (" | neu: " + "; ".join(sorted(set(neu))[:3])) if neu else ""))
                    pruef(checks, "05_typecheck_gesamt", "PASS" if not ist else "ROT", "%d TypeScript-Fehler insgesamt (Altlast zählt für die Freigabe)" % len(ist))
        # ---- Python-Suite NACH dem Bau, gezählt, mit Rückgabecode
        try:
            import flask  # noqa: F401
            import pytest  # noqa: F401
            umgebung_ok = True
        except ImportError as ex:
            umgebung_ok = False
            for i in ("06_python_suite", "06_regression_neu_rot", "06_unveraendert_rot"):
                pruef(checks, i, "BLOCKIERT", "Python-Abhängigkeit fehlt: %s" % ex.name, "umgebung")
        if umgebung_ok:
            xml = logs / "pytest_junit.xml"
            env = {k: v for k, v in os.environ.items() if not re.search(r"(API[_-]?KEY|SECRET|TOKEN)", k, re.I)}
            env["MATRIX_DB"] = str(root / "data" / "gate_test.sqlite")
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--continue-on-collection-errors",
                                "--junitxml", str(xml), "tests"], cwd=root, capture_output=True, text=True, timeout=1200, env=env)
            (logs / "pytest.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
            j = junit_auswerten(xml)
            rot = set(j["fehlschlaege"]) | set(j["fehler"])
            widerspruch = (r.returncode not in (0, 1)) or (r.returncode == 0 and (rot or j["sammelfehler"])) or \
                          (r.returncode == 1 and not rot and not j["sammelfehler"])
            if j["gelaufen"] == 0 or j["sammelfehler"] or widerspruch:
                pruef(checks, "06_python_suite", "BLOCKIERT", "Suite nicht vollständig: gelaufen %d, Sammelabbrüche %s, Exitcode %d%s" % (
                    j["gelaufen"], j["sammelfehler"][:2], r.returncode, " (widerspricht dem Ergebnis)" if widerspruch else ""), "umgebung")
            else:
                pruef(checks, "06_python_suite", "PASS", "%d Tests gelaufen, Exitcode %d, keine Sammelabbrüche" % (j["gelaufen"], r.returncode))
            basis = {normiere_testid(z) for z in (BASE / regeln["basis_fehlschlaege"]).read_text(encoding="utf-8").split()}
            neu_rot, wieder_gruen, bleibt_rot = sorted(rot - basis), sorted(basis - rot), sorted(rot & basis)
            (bericht / "TEST_VERGLEICH_P22.json").write_text(json.dumps(
                {"gelaufen": j["gelaufen"], "exitcode": r.returncode, "neu_rot": neu_rot, "wieder_gruen": wieder_gruen,
                 "unveraendert_rot": bleibt_rot, "alle_fehlschlaege": j["fehlschlaege"], "alle_fehler": j["fehler"],
                 "sammelfehler": j["sammelfehler"]}, ensure_ascii=False, indent=1), encoding="utf-8")
            vollst = j["gelaufen"] > 0 and not j["sammelfehler"] and not widerspruch
            pruef(checks, "06_regression_neu_rot", ("ROT" if neu_rot else "PASS") if vollst else "BLOCKIERT",
                  "neu rot gegenüber P22: %d%s" % (len(neu_rot), (" – " + "; ".join(neu_rot[:4])) if neu_rot else ""))
            pruef(checks, "06_wieder_gruen", "PASS", "wieder grün gegenüber P22: %d%s" % (len(wieder_gruen), (" – " + "; ".join(wieder_gruen[:4])) if wieder_gruen else ""))
            pruef(checks, "06_unveraendert_rot", ("ROT" if bleibt_rot else "PASS") if vollst else "BLOCKIERT",
                  "unverändert rot seit P22: %d%s" % (len(bleibt_rot), (" – " + "; ".join(bleibt_rot[:4])) if bleibt_rot else ""))
        # ---- Kettenprüfer in DIESEM Lauf, alle Pflichtfälle
        kp = BASE / regeln["kettenpruefer"]["skript"]
        abweichend = [n for n, h in regeln["kettenpruefer"]["dateien"].items() if not (BASE / n).is_file() or sha(BASE / n) != h]
        faelle = pa.pflicht_faelle(regeln)
        if not kp.is_file() or sha(kp) != regeln["kettenpruefer"]["sha256"] or abweichend:
            pruef(checks, "07_kettenpruefer_lauf", "BLOCKIERT", "Kettenprüfer/Fallkatalog nicht der eingefrorene: %s" % (abweichend or [regeln["kettenpruefer"]["skript"]]), "nachweis")
            for f in faelle:
                pruef(checks, "07_kette_" + f, "BLOCKIERT", "Kettenprüfer nicht eingefroren", "nachweis")
            achsen = {a: ("UNGEPRUEFT" if not regeln["pflichtfaelle"].get(a) else "BLOCKIERT") for a in regeln["pflichtachsen"]}
        elif not ns.db:
            pruef(checks, "07_kettenpruefer_lauf", "BLOCKIERT", "keine Original-DB angegeben (--db)", "umgebung")
            for f in faelle:
                pruef(checks, "07_kette_" + f, "BLOCKIERT", "nicht gelaufen", "umgebung")
            achsen = {a: ("UNGEPRUEFT" if not regeln["pflichtfaelle"].get(a) else "BLOCKIERT") for a in regeln["pflichtachsen"]}
        else:
            aus = bericht / "KETTENPRUEFER"
            r = subprocess.run([sys.executable, "-I", str(kp), "--kandidat", str(kandidat), "--db", str(Path(ns.db).resolve()),
                                "--ausgabe", str(aus), "--modus", ns.modell, "--aufnahme", str(Path(ns.aufnahme).resolve()),
                                "--faelle", ",".join(faelle),
                                *(["--node-cache", ns.node_cache] if ns.node_cache else []), "--playwright", ns.playwright],
                               capture_output=True, text=True, timeout=7200)
            (logs / "kettenpruefer.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
            erg = json.loads((aus / "ERGEBNIS.json").read_text(encoding="utf-8")) if (aus / "ERGEBNIS.json").is_file() else None
            kchecks, achsen = pa.kette_auswerten(erg, r.returncode, katalog, regeln, meta["kandidat_sha256"], sha(katalog_pfad))
            for c in kchecks:
                pruef(checks, c["id"], c["status"], c["detail"], c["art"])
        # ---- Vorbefunde: nur durch benannte Beweisfälle, die in DIESEM Lauf bestehen
        ok_faelle = {c["id"][len("07_kette_"):] for c in checks if c["id"].startswith("07_kette_") and c["status"] == "PASS"}
        for vb in regeln["offene_vorbefunde"]:
            beweise = vb.get("beweisfaelle") or []
            zu = bool(beweise) and all(b in ok_faelle for b in beweise)
            pruef(checks, "08_vorbefund_" + vb["id"], "PASS" if zu else "ROT",
                  ("geschlossen durch " + ", ".join(beweise)) if zu else ("offen: " + vb["hinweis"] + (" (Beweisfall fehlt)" if not beweise else " (Beweisfall nicht grün)")))
    except Exception as ex:
        pruef(checks, "99_abbruch", "BLOCKIERT", "%s: %s" % (type(ex).__name__, ex), "umgebung")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for a, s in achsen.items():
        pruef(checks, "09_achse_" + a, {"GRUEN": "PASS", "ROT": "ROT", "UNGEPRUEFT": "UNGEPRUEFT"}.get(s, "BLOCKIERT"),
              "Pflichtfälle %s: %s" % (regeln["pflichtfaelle"].get(a) or "keine", s), "nachweis" if s != "ROT" else "vertrag")
    ok2, grund2, msha2 = pa.manifest_pruefen(BASE)
    pruef(checks, "10_pruefmaschine_unveraendert", "PASS" if ok2 and msha2 == msha else "BLOCKIERT",
          "Maschine nach dem Lauf unverändert" if ok2 and msha2 == msha else "Maschine nach dem Lauf: " + grund2, "nachweis")
    status, gruende = pa.entscheidung(checks, achsen, regeln)
    meta["gesamt"], meta["gruende"] = status, gruende
    (bericht / "ERGEBNIS.json").write_text(json.dumps({"meta": meta, "pruefungen": checks, "achsen": achsen}, ensure_ascii=False, indent=1), encoding="utf-8")
    zeilen = ["MATRIX10 FREIGABESPERRE V1.2", "=" * 60, "GESAMTSTATUS: " + status, "Begründung: " + "; ".join(gruende),
              "Kandidat: %s  %s" % (kandidat.name, meta.get("kandidat_sha256", "")), "Abnahme-Manifest: %s" % (msha or "fehlt"), ""]
    zeilen += ["[%s] %s: %s" % (c["status"], c["id"], c["detail"]) for c in checks]
    zeilen += ["", "PFLICHTACHSEN"] + ["  %-12s %s" % (s, a) for a, s in achsen.items()]
    zeilen += ["", "GRÜN nur, wenn jede Pflichtprüfung genau einmal vorliegt und PASS ist und alle 16 Achsen GRÜN sind.",
               "Fehlender Nachweis/Umgebung = BLOCKIERT, Vertragsfehler = ROT."]
    (bericht / "ERGEBNIS_LESEN.txt").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    print("GESAMTSTATUS:", status, "->", bericht / "ERGEBNIS_LESEN.txt", flush=True)
    return {"GRUEN": 0, "ROT": 2}.get(status, 3)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kandidat", required=True)
    ap.add_argument("--db", default="", help="Original-DB (nur Kopie wird benutzt)")
    ap.add_argument("--modell", choices=("live", "wiedergabe"), default="live")
    ap.add_argument("--aufnahme", default=str(BASE / "MODELLAUFNAHME"))
    ap.add_argument("--node-cache", default="")
    ap.add_argument("--playwright", default="playwright")
    sys.exit(lauf(ap.parse_args()))
