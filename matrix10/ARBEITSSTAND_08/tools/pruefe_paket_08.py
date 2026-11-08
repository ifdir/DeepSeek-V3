#!/usr/bin/env python3
"""Stand 08: das gebaute Produkt-ZIP am FRISCH ENTPACKTEN Stand pruefen (Linux x86_64) - bestehende Pruefungen.

1  ZIP-Integritaet, SHA-256 gegen .sha256, Hashes der Ebenen 06/07/08 + Rust-Bibliothek gegen MATRIX10_STAND08_STATUS.json
2  Erststart wie in der Startanleitung: python3 START.py ohne data/ -> UI + API erreichbar, eingebaute Welt vorhanden
3  cargo test --offline --locked in der mitgelieferten Rust-Crate
4  mitgelieferte K-01/K-02/SEC-Tests (pruefung/tests) gegen das entpackte Paket
5  Einwilligungskette (probe_p25_consent_06.py) gegen das entpackte Paket
6  P25-Testsuite: entpacktes Paket vs. unveraendertes P25 (erlaubt nur die dokumentierte K-01-Abweichung)
7  Live K-01 (live_abnahme_k01_07.py) und Live K-02 (live_abnahme_k02_08.py): START.py aus dem entpackten Paket, Chromium,
   echter Neustart (mit einer Kopie der Pruef-Vorlage-DB, nie der Original-DB)
Aufruf: python3 -I pruefe_paket_08.py <paket.zip> <vorlage.sqlite> <protokollordner>
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
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

M10 = Path(__file__).resolve().parents[2]
T06, T07, T08 = M10 / "ARBEITSSTAND_06/tools", M10 / "ARBEITSSTAND_07/tools", M10 / "ARBEITSSTAND_08/tools"
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
    soll = (zp.parent / (zp.name + ".sha256")).read_text().split()[0]
    E["zip_sha256"] = sha(zp)
    K["1b_zip_sha256"] = E["zip_sha256"] == soll
    work = Path(tempfile.mkdtemp(prefix="pruef08_"))
    with zipfile.ZipFile(zp) as z:
        z.extractall(work / "entpackt")
    root = next((work / "entpackt").iterdir())
    st = json.loads((root / "MATRIX10_STAND08_STATUS.json").read_text())
    E["commit"] = st["commit"]
    # massgeblich ist je Datei die OBERSTE Ebene, die sie ersetzt (08 vor 07 vor 06)
    oberste: dict = {rel: want for rel, want in st["ebene_06"].items()}
    oberste.update({rel: (info["sha256"] if isinstance(info, dict) else info) for rel, info in st["ebene_07"].items()})
    oberste.update({rel: (info["sha256"] if isinstance(info, dict) else info) for rel, info in st["ebene_08"].items()})
    abw = sorted(rel for rel, want in oberste.items() if not (root / rel).is_file() or sha(root / rel) != want)
    E["geprueft_dateien_aus_ebenen"] = len(oberste)
    K["1c_alle_reparaturebenen_06_07_08_im_paket"] = not abw
    E["hash_abweichungen"] = abw
    K["1d_rust_bibliothek_und_frontend_vorhanden"] = (sha(root / "matrix_api/native/libmatrix_boundary_core.so") == st["rust_bibliothek_sha256"]
                                                      and (root / "frontend_dist/index.html").is_file())
    # ---- 2 Erststart laut Anleitung (ohne data/)
    sh(["bash", str(T06 / "ui_stop.sh")])
    env = dict(os.environ, MATRIX_API_PORT="5150", MATRIX_UI_PORT="8180", MATRIX_NO_OPEN="1")
    for k in ("XAI_API_KEY", "OPENAI_API_KEY", "MATRIX_API_KEY"):
        env.pop(k, None)
    log = open(prot / "erststart.log", "wb")
    subprocess.Popen(["python3", "START.py"], cwd=root, env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
    ok = False
    for _ in range(90):
        try:
            urllib.request.urlopen("http://127.0.0.1:5150/api/health", timeout=2)
            urllib.request.urlopen("http://127.0.0.1:8180/", timeout=2)
            ok = True
            break
        except Exception:
            time.sleep(1)
    welt = False
    if ok:
        r = urllib.request.Request("http://127.0.0.1:5150/api/mcc", headers={"X-Matrix-Actor": "admin"})
        try:
            j = json.loads(urllib.request.urlopen(r, timeout=10).read())
            welt = bool(j.get("worlds")) and bool(j.get("characters"))
        except Exception as e:
            E["erststart_mcc_fehler"] = str(e)[:200]
    sh(["bash", str(T06 / "ui_stop.sh")])
    K["2_erststart_ohne_db_ui_api_und_welt"] = ok and welt and (root / "data/matrix10.sqlite").is_file()
    # ---- 3
    c, o = sh(["cargo", "test", "--offline", "--locked"], cwd=root / "native_core/matrix-boundary-core")
    (prot / "cargo_test.log").write_text(o)
    K["3_cargo_test"] = c == 0
    shutil.rmtree(root / "native_core/matrix-boundary-core/target", ignore_errors=True)
    # ---- 4
    penv = dict(os.environ, MATRIX07_ROOT=str(root))
    c, o = sh([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(root / "pruefung/tests")], cwd=root / "tests", env=penv)
    (prot / "k_tests.log").write_text(o)
    K["4_k01_k02_sec_tests"] = c == 0
    E["k_tests"] = o.strip().splitlines()[-1:]
    # ---- 5
    c, o = sh([sys.executable, "-I", str(T06 / "probe_p25_consent_06.py"), "--root", str(root), "--output", str(prot / "einwilligung.json"),
               "--label", "Paket 08"])
    ew = json.loads((prot / "einwilligung.json").read_text()) if c == 0 else {}
    K["5_einwilligungskette_10_von_10"] = ew.get("soll_erfuellt") == ew.get("gesamt") == 10
    # ---- 6
    p25 = work / "p25"
    with zipfile.ZipFile(P25_ZIP) as z:
        z.extractall(p25)
    p25 = p25 / "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
    r = {}
    for lbl, rr in (("p25", p25), ("paket", root)):
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
    E["paketpruefung"] = "BESTANDEN" if all(K.values()) else "NICHT BESTANDEN"
    E["vertragsstatus_gesamt"] = "ROT (bekannte offene Vertragsfehler; K-01/K-02 TEILGESCHLOSSEN; Modell BLOCKIERT)"
    E["vertragsstatus"] = st["vertragsstatus_aus_gesamtlauf_chain_08"]
    (prot / "MATRIX10_STAND08_PRUEFPROTOKOLL.json").write_text(json.dumps(E, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(K, indent=1, ensure_ascii=False))
    shutil.rmtree(work, ignore_errors=True)
    return 2 if all(K.values()) else 3


if __name__ == "__main__":
    raise SystemExit(main())
