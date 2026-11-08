#!/usr/bin/env python3
"""Stand 10a: das gebaute Produkt-ZIP am FRISCH ENTPACKTEN Stand pruefen (Linux x86_64) - bestehende Pruefungen.

1  ZIP-Integritaet, SHA-256 gegen .sha256, Hashes der Ebenen 06/07/08/09/10/10a + Rust-Bibliothek gegen MATRIX10_STAND10A_STATUS.json
2  Erststart wie in der Startanleitung: python3 START.py ohne data/ -> UI + API erreichbar, eingebaute Welt vorhanden
3  cargo test --offline --locked in der mitgelieferten Rust-Crate
4  mitgelieferte K-01/K-02/SEC-Tests (pruefung/tests) gegen das entpackte Paket
5  Einwilligungskette (probe_p25_consent_06.py) gegen das entpackte Paket
6  P25-Testsuite: entpacktes Paket vs. unveraendertes P25 (erlaubt nur die dokumentierte K-01-Abweichung)
7  Live K-01 (live_abnahme_k01_07.py) und Live K-02 (live_abnahme_k02_08.py): START.py aus dem entpackten Paket, Chromium,
   echter Neustart (mit einer Kopie der Pruef-Vorlage-DB, nie der Original-DB)
8  ABI-3-Vertrag (ARBEITSSTAND_06/tests/test_abi3_contract_06.py) gegen das entpackte Paket, Gegenprobe mit einer aus der
   mitgelieferten Crate gebauten ABI-2-Bibliothek
9  Rust im laufenden Produkt: START.py aus dem entpackten Paket, Anfrage an die Einwilligungsleser (GET /api/mcc) -> der
   API-Prozess hat genau die Paket-Bibliothek geladen (/proc/<pid>/maps); Gegenprobe: zweite frische Entpackung ohne
   Bibliothek -> 503 NATIVE_BOUNDARY_UNAVAILABLE, keine Python-Ersatzlogik
Das Abnahmeverzeichnis ist NEU und LEER unter /tmp (nicht das Scratchpad); ZIP und .sha256 werden dorthin kopiert.
Aufruf: python3 -I pruefe_paket_10a.py <paket.zip> <vorlage.sqlite> <protokollordner>
Exit = Vertragsstatus des Pakets: 2 ROT (bekannte offene Vertragsfehler) - Paketkriterien stehen getrennt im JSON.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

M10 = Path(__file__).resolve().parents[2]
T06, T07, T08, T09, T10 = (M10 / "ARBEITSSTAND_06/tools", M10 / "ARBEITSSTAND_07/tools", M10 / "ARBEITSSTAND_08/tools",
                           M10 / "ARBEITSSTAND_09/tools", M10 / "ARBEITSSTAND_10/tools")
P25_ZIP = M10 / "MATRIX10_FREIGABESPERRE_P25_V1_20261107/MATRIX10_FREIGABESPERRE_P25_V1/MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107.zip"
K01_ABW = "tests.test_v92_p18_koerper.P18AvatarAndFigure::test_avatar_position_and_figure_reply_with_forged_and_real_readings"


def sh(cmd, cwd=None, env=None, timeout=2400):
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def junit(p: Path) -> dict:
    out = {}
    for tc in ET.parse(p).getroot().iter("testcase"):
        st = "pass"
        for ch in tc:
            st = ch.tag if ch.tag in ("failure", "error") else ("skip" if ch.tag == "skipped" else st)
        out[tc.get("classname", "") + "::" + tc.get("name", "")] = st
    return out


def main() -> int:
    zp, vorlage, prot = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    prot.mkdir(parents=True, exist_ok=True)
    K: dict = {}
    E: dict = {"paket": zp.name, "plattform": "linux-x86_64", "kriterien": K}
    # ---- 1
    with zipfile.ZipFile(zp) as z:
        K["1a_zip_crc_ok"] = z.testzip() is None
    work = Path(f"/tmp/matrix10_abnahme_stand10a_{time.strftime('%Y%m%d_%H%M%S')}")
    work.mkdir(parents=True, exist_ok=False)                     # neu und leer, ausserhalb des Scratchpads
    shutil.copy2(zp, work / zp.name)
    shutil.copy2(zp.parent / (zp.name + ".sha256"), work / (zp.name + ".sha256"))
    zp = work / zp.name
    E["abnahmeverzeichnis"] = str(work)
    soll = (zp.parent / (zp.name + ".sha256")).read_text().split()[0]
    E["zip_sha256"] = sha(zp)
    K["1b_zip_sha256"] = E["zip_sha256"] == soll
    with zipfile.ZipFile(zp) as z:
        z.extractall(work / "entpackt")
    root = next((work / "entpackt").iterdir())
    st = json.loads((root / "MATRIX10_STAND10A_STATUS.json").read_text())
    E["commit"] = st["commit"]
    # massgeblich ist je Datei die OBERSTE Ebene, die sie ersetzt (10a vor 10 vor 09 vor 08 vor 07 vor 06)
    oberste: dict = {rel: want for rel, want in st["ebene_06"].items()}
    oberste.update({rel: (info["sha256"] if isinstance(info, dict) else info) for rel, info in st["ebene_07"].items()})
    oberste.update({rel: (info["sha256"] if isinstance(info, dict) else info) for rel, info in st["ebene_08"].items()})
    oberste.update({rel: (info["sha256"] if isinstance(info, dict) else info) for rel, info in st["ebene_09"].items()})
    oberste.update({rel: (info["sha256"] if isinstance(info, dict) else info) for rel, info in st["ebene_10"].items()})
    oberste.update({rel: (info["sha256"] if isinstance(info, dict) else info) for rel, info in st["ebene_10a"].items()})
    abw = sorted(rel for rel, want in oberste.items() if not (root / rel).is_file() or sha(root / rel) != want)
    E["geprueft_dateien_aus_ebenen"] = len(oberste)
    K["1c_alle_reparaturebenen_06_bis_10a_im_paket"] = not abw
    E["hash_abweichungen"] = abw
    K["1d_rust_bibliothek_und_frontend_vorhanden"] = (sha(root / "matrix_api/native/libmatrix_boundary_core.so") == st["rust_bibliothek_sha256"]
                                                      and (root / "frontend_dist/index.html").is_file())
    # ---- 2 Erststart EXAKT nach der mitgelieferten Anleitung: `python3 START.py` ohne Port-Variablen, URLs aus der Anleitung
    import re as _re2
    anl = (root / "MATRIX10_STAND10A_START.txt").read_text(encoding="utf-8")
    ui_url = _re2.search(r"Browser selbst oeffnen: (http://127\.0\.0\.1:\d+)", anl)
    api_url = _re2.search(r"\(API: (http://127\.0\.0\.1:\d+)\)", anl)
    E["anleitung_urls"] = {"ui": ui_url and ui_url.group(1), "api": api_url and api_url.group(1)}
    sh(["bash", str(T06 / "ui_stop.sh")])
    env0 = {k: v for k, v in os.environ.items() if not k.startswith("MATRIX_") and k not in ("XAI_API_KEY", "OPENAI_API_KEY")}
    log = open(prot / "erststart.log", "wb")
    subprocess.Popen(["python3", "START.py"], cwd=root, env=env0, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    ok = False
    for _ in range(90 if ui_url and api_url else 0):
        try:
            urllib.request.urlopen(api_url.group(1) + "/api/health", timeout=2)
            urllib.request.urlopen(ui_url.group(1) + "/", timeout=2)
            ok = True
            break
        except Exception:
            time.sleep(1)
    welt = False
    E["erststart_versuche"] = []
    for _ in range(10 if ok else 0):
        r = urllib.request.Request(api_url.group(1) + "/api/mcc", headers={"X-Matrix-Actor": "admin"})
        try:
            j = json.loads(urllib.request.urlopen(r, timeout=10).read())
            welt = bool(j.get("worlds")) and bool(j.get("characters"))
            E["erststart_versuche"].append({"welten": len(j.get("worlds") or []), "figuren": len(j.get("characters") or [])})
        except Exception as e:
            E["erststart_versuche"].append({"fehler": str(e)[:200]})
        if welt:
            break
        time.sleep(1)
    subprocess.run(["pkill", "-f", "python3 START.py"], check=False)
    subprocess.run(["pkill", "-f", "matrix_api.app"], check=False)
    time.sleep(2)
    sh(["bash", str(T06 / "ui_stop.sh")])
    K["2_erststart_exakt_nach_anleitung_ui_api_welt"] = ok and welt and (root / "data/matrix10.sqlite").is_file()
    src = M10 / "MATRIX10_RUST_ARBEITSSTAND_04_20261107/sources"
    K["2b_readme_stand10a_und_vertragsdateien"] = (
        "Arbeitsstand 10a" in (root / "README.md").read_text(encoding="utf-8").splitlines()[0]
        and all(sha(root / "vertrag" / n) == sha(src / n) for n in ("AMASTERv2.md(1).txt", "Matrix10.txt", "VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt")))
    # ---- 3
    c, o = sh(["cargo", "test", "--offline", "--locked"], cwd=root / "native_core/matrix-boundary-core")
    (prot / "cargo_test.log").write_text(o)
    K["3_cargo_test"] = c == 0
    shutil.rmtree(root / "native_core/matrix-boundary-core/target", ignore_errors=True)
    # ---- 4
    penv = dict(os.environ, MATRIX07_ROOT=str(root))
    c, o = sh([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(root / "pruefung/tests")], cwd=root / "tests", env=penv)
    (prot / "k_tests.log").write_text(o)
    K["4_k01_k02_sec_f1b2_f2_rust_diagnose_tests"] = c == 0
    E["k_tests"] = o.strip().splitlines()[-1:]
    # ---- 5
    c, o = sh([sys.executable, "-I", str(T06 / "probe_p25_consent_06.py"), "--root", str(root), "--output", str(prot / "einwilligung.json"),
               "--label", "Paket 10a"])
    ew = json.loads((prot / "einwilligung.json").read_text()) if c == 0 else {}
    K["5_einwilligungskette_10_von_10"] = ew.get("soll_erfuellt") == ew.get("gesamt") == 10
    # ---- 6
    p25 = work / "p25"
    with zipfile.ZipFile(P25_ZIP) as z:
        z.extractall(p25)
    p25 = p25 / "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
    # eigene, frisch entpackte Kopie: Schritt 2 (Erststart) hat in `root` bereits data/matrix10.sqlite angelegt, und
    # test_no_database_in_software_release prueft genau das ausgelieferte Paket ohne Datenbank
    with zipfile.ZipFile(zp) as z:
        z.extractall(work / "suite")
    suite_root = next((work / "suite").iterdir())
    r = {}
    for lbl, rr in (("p25", p25), ("paket", suite_root)):
        sh([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--continue-on-collection-errors", "tests",
            f"--junitxml={work / (lbl + '.xml')}"], cwd=rr)
        r[lbl] = junit(work / (lbl + ".xml"))
    abw6 = sorted(k for k in set(r["p25"]) | set(r["paket"]) if r["p25"].get(k) != r["paket"].get(k))
    E["p25_suite"] = {lbl: {s: list(v.values()).count(s) for s in set(v.values())} for lbl, v in r.items()}
    E["p25_suite_abweichungen"] = abw6
    verschlechtert = sorted(k for k in abw6 if r["p25"].get(k) == "pass" and r["paket"].get(k) != "pass")
    verbessert = sorted(k for k in abw6 if r["p25"].get(k) != "pass" and r["paket"].get(k) == "pass")
    E["p25_suite_verschlechtert"], E["p25_suite_verbessert"] = verschlechtert, verbessert
    # kein in P25 gruener Test darf im Paket rot sein - ausser der dokumentierten K-01-Vertragsabweichung
    K["6_p25_suite_keine_verschlechterung_ausser_k01_dokumentiert"] = verschlechtert == [K01_ABW]
    # ---- 7
    c1, o1 = sh([sys.executable, "-I", str(T07 / "live_abnahme_k01_07.py"), str(root), str(vorlage), str(prot / "live_k01")], timeout=1800)
    c2, o2 = sh([sys.executable, "-I", str(T08 / "live_abnahme_k02_08.py"), str(root), str(vorlage), str(prot / "live_k02")], timeout=1800)
    l1 = prot / "live_k01/L_abnahme_k01_07.json"
    l2 = prot / "live_k02/L2_abnahme_k02_08.json"
    E["live_k01"] = json.loads(l1.read_text())["kriterien"] if l1.exists() else o1[-800:]
    E["live_k02"] = json.loads(l2.read_text())["kriterien"] if l2.exists() else o2[-800:]
    K["7a_live_k01_sec_14_kriterien"] = c1 == 0
    K["7b_live_k02_10_kriterien"] = c2 == 0
    c3, o3 = sh([sys.executable, "-I", str(T09 / "f1_durchlauf_09.py"), str(root), str(vorlage), str(prot / "f1")], timeout=1800)
    l3 = prot / "f1/f1_ergebnis.json"
    E["f1_kernkette"] = json.loads(l3.read_text())["kriterien"] if l3.exists() else o3[-800:]
    K["7c_f1_kernkette_12_kriterien_testmodell"] = c3 == 0
    c4, o4 = sh([sys.executable, "-I", str(T10 / "f2_durchlauf_10.py"), str(root), str(vorlage), str(prot / "f2")], timeout=1800)
    l4 = prot / "f2/f2_ergebnis.json"
    E["f2_bindung"] = json.loads(l4.read_text())["kriterien"] if l4.exists() else o4[-800:]
    K["7d_f2_sprecherbindung_7_kriterien_testmodell"] = c4 == 0
    # ---- 8 ABI 3
    abi2 = work / "abi2_crate"
    shutil.copytree(root / "native_core/matrix-boundary-core", abi2, ignore=shutil.ignore_patterns("target"))
    lr = abi2 / "src/lib.rs"
    import re as _re
    lr.write_text(_re.sub(r"pub const ABI_VERSION: u32 = \d+;", "pub const ABI_VERSION: u32 = 2;", lr.read_text()))
    c, o = sh(["cargo", "build", "--release", "--offline", "--locked"], cwd=abi2)
    c, o = sh([sys.executable, "-I", str(M10 / "ARBEITSSTAND_06/tests/test_abi3_contract_06.py")],
              env=dict(os.environ, MATRIX06_ROOT=str(root), MATRIX06_ABI2_LIB=str(abi2 / "target/release/libmatrix_boundary_core.so")))
    (prot / "abi3_vertrag.log").write_text(o)
    K["8_abi3_vertrag_und_abi2_gegenprobe"] = c == 0
    # ---- 9 Rust im laufenden Produkt + Negativprobe ohne Bibliothek (Testaufbau auf 5150/8180)
    env = dict(env0, MATRIX_API_PORT="5150", MATRIX_UI_PORT="8180", MATRIX_NO_OPEN="1")
    def lauf(produkt: Path, tag: str):
        sh(["bash", str(T06 / "ui_stop.sh")])
        (produkt / "data").mkdir(exist_ok=True)
        for f in ("matrix10.sqlite-wal", "matrix10.sqlite-shm"):   # Reste frueherer Laeufe (F1) gehoeren nicht zur Vorlage
            (produkt / "data" / f).unlink(missing_ok=True)
        shutil.copy2(vorlage, produkt / "data/matrix10.sqlite")
        lg = open(prot / f"rust_lauf_{tag}.log", "wb")
        subprocess.Popen(["python3", "START.py"], cwd=produkt, env=env, stdout=lg, stderr=lg, stdin=subprocess.DEVNULL, start_new_session=True)
        for _ in range(90):
            try:
                urllib.request.urlopen("http://127.0.0.1:5150/api/health", timeout=2)
                break
            except Exception:
                time.sleep(1)
        try:
            resp = urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:5150/api/mcc", headers={"X-Matrix-Actor": "admin"}), timeout=20)
            status, code = resp.status, None
            meldung = None
        except urllib.error.HTTPError as he:
            _j = json.loads(he.read() or b"{}") or {}
            status, code, meldung = he.code, _j.get("code"), _j.get("message")
        try:
            rust_health = json.loads(urllib.request.urlopen("http://127.0.0.1:5150/api/health", timeout=10).read()).get("rustKern")
        except Exception as _e:
            rust_health = {"fehler": str(_e)[:200]}
        pids = subprocess.run(["pgrep", "-f", "matrix_api.app"], capture_output=True, text=True).stdout.split()
        geladen = []
        for pid in pids:
            try:
                geladen += [ln.split()[-1] for ln in open(f"/proc/{pid}/maps") if "libmatrix_boundary_core" in ln]
            except OSError:
                pass
        sh(["bash", str(T06 / "ui_stop.sh")])
        lg.close()
        start_text = (prot / f"rust_lauf_{tag}.log").read_text(errors="replace")
        return {"status": status, "code": code, "meldung": meldung, "health_rustKern": rust_health,
                "start_rust_zeilen": [z for z in start_text.splitlines() if z.startswith(("[RUST", "[RUST-FEHLER"))],
                "geladene_bibliothek": sorted(set(geladen))}
    r_ok = lauf(root, "mit_rust")
    ohne_dir = work / "ohne_rust"
    with zipfile.ZipFile(zp) as z:
        z.extractall(ohne_dir)
    ohne = next(ohne_dir.iterdir())
    shutil.rmtree(ohne / "matrix_api/native")
    r_ohne = lauf(ohne, "ohne_rust")
    # 9c: eine FREMDE Bibliothek (ELF fuer aarch64 auf x86-64 - wie das Linux-Paket auf dem Handy, nur umgekehrt)
    fremd_dir = work / "fremde_rust"
    with zipfile.ZipFile(zp) as z:
        z.extractall(fremd_dir)
    fremd = next(fremd_dir.iterdir())
    (fremd / "matrix_api/native/libmatrix_boundary_core.so").write_bytes(b"\x7fELF\x02\x01\x01" + b"\x00" * 9 + b"\x03\x00\xb7\x00" + b"\x00" * 400)
    r_fremd = lauf(fremd, "fremde_rust")
    E["rust_im_laufenden_produkt"] = {"mit_bibliothek": r_ok, "ohne_bibliothek": r_ohne, "fremde_bibliothek": r_fremd}
    lib_paket = str((root / "matrix_api/native/libmatrix_boundary_core.so").resolve())
    K["9a_laufendes_produkt_nutzt_paket_rust_bibliothek"] = r_ok["status"] == 200 and r_ok["geladene_bibliothek"] == [lib_paket]
    K["9b_ohne_bibliothek_fail_closed_503_keine_ersatzlogik"] = (r_ohne["status"] == 503 and r_ohne["code"] == "NATIVE_BOUNDARY_UNAVAILABLE"
                                                                 and not r_ohne["geladene_bibliothek"])
    K["9a2_start_meldet_rust_geladen"] = any("[RUST] Einwilligungskern geladen" in z for z in r_ok["start_rust_zeilen"]) \
        and (r_ok["health_rustKern"] or {}).get("ok") is True
    K["9c_fremde_bibliothek_grund_beim_start_in_health_und_im_503"] = (
        r_fremd["status"] == 503 and r_fremd["code"] == "NATIVE_BOUNDARY_UNAVAILABLE"
        and "Bibliothek ist fuer aarch64" in str(r_fremd["meldung"])
        and any("NICHT ladbar" in z and "aarch64" in z for z in r_fremd["start_rust_zeilen"])
        and (r_fremd["health_rustKern"] or {}).get("ok") is False and "aarch64" in str((r_fremd["health_rustKern"] or {}).get("grund")))
    E["paketpruefung"] = "BESTANDEN" if all(K.values()) else "NICHT BESTANDEN"
    E["vertragsstatus_gesamt"] = "ROT (bekannte offene Vertragsfehler; K-01/K-02 TEILGESCHLOSSEN; F1-Kernkette und F2-Bindung mit Testmodell erfuellt; K-05 Sprecherwahl per Wortliste ROT; echtes Modell BLOCKIERT)"
    E["vertragsstatus"] = st["vertragsstatus_aus_gesamtlauf_chain_08"]
    (prot / "MATRIX10_STAND10A_PRUEFPROTOKOLL.json").write_text(json.dumps(E, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(K, indent=1, ensure_ascii=False))
    for x in ("suite", "p25", "ohne_rust", "fremde_rust", "abi2_crate"):
        shutil.rmtree(work / x, ignore_errors=True)     # das entpackte Paket selbst bleibt fuer Einsicht liegen
    return 2 if all(K.values()) else 3


if __name__ == "__main__":
    raise SystemExit(main())
