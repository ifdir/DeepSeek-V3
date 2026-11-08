#!/usr/bin/env python3
"""Stand 11: vollstaendiges Matrix10-Produktpaket fuer Linux x86_64 bauen - mit dem bestehenden Stage-Verfahren.

stage_source_11.py (-> 10c -> 10b -> 10a -> 10 -> 09 -> 08 -> 07 -> 06 -> P25-ZIP, Basis-Hash je Ebene) -> cargo build --release --offline --locked (Rust-Kern) ->
npm ci + npm run build:dist (Frontend) -> ZIP. Keine Produktcode-Aenderung. ZIP wird NICHT committet.
Aufruf: python3 -I paket_11.py <ausgabeordner>
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

HIER = Path(__file__).resolve().parents[1]                        # matrix10/ARBEITSSTAND_11
M10 = HIER.parent
REPO = M10.parent
P25_ZIP = M10 / "MATRIX10_FREIGABESPERRE_P25_V1_20261107/MATRIX10_FREIGABESPERRE_P25_V1/MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107.zip"
P25_DIR = "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
LIB = "libmatrix_boundary_core.so"
PLATTFORM = "linux-x86_64"
WEG = {"node_modules", "target", "data", "__pycache__", ".pytest_cache"}
PRUEF = {"tests": [M10 / "ARBEITSSTAND_07/tests/test_k01_turntruth_07.py", M10 / "ARBEITSSTAND_07/tests/test_sec_mcc_07.py",
                   M10 / "ARBEITSSTAND_11/tests/test_k01_p18_portiert_11.py", M10 / "ARBEITSSTAND_10/tests/test_k02_wissen_portiert_10.py",
                   M10 / "ARBEITSSTAND_09/tests/test_f1_b2_rahmen_09.py",
                   M10 / "ARBEITSSTAND_10/tests/test_f2_sprecher_10.py",
                   M10 / "ARBEITSSTAND_10A/tests/test_rust_diagnose_10a.py",
                   M10 / "ARBEITSSTAND_10B/tests/test_lesungen_gleichzeitig_10b.py"],
         "tools": [M10 / "ARBEITSSTAND_07/tools/beleg_kette_07.py"]}


def sh(cmd, cwd=None, timeout=2400):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise SystemExit(f"ABBRUCH: {' '.join(map(str, cmd))}\n{(r.stdout + r.stderr)[-2000:]}")
    return r.stdout


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("ABBRUCH: dieses Paket wird nur auf Linux x86_64 gebaut und geprueft")
    if sh(["git", "status", "--porcelain"], cwd=REPO).strip():
        raise SystemExit("ABBRUCH: Arbeitsbaum nicht sauber - Paket muss einem Commit entsprechen")
    commit = sh(["git", "rev-parse", "HEAD"], cwd=REPO).strip()
    kurz = commit[:7]
    tmp = Path(tempfile.mkdtemp(prefix="paket11_"))
    sh([sys.executable, "-I", str(HIER / "tools/stage_source_11.py"), str(P25_ZIP), str(tmp / "stage")])
    root = tmp / "stage" / P25_DIR
    man = json.loads((tmp / "stage/STAGE_11_MANIFEST.json").read_text())
    if not (man.get("stand_07", {}).get("overlay_07") and man.get("stand_08", {}).get("overlay_08") and man.get("stand_09", {}).get("overlay_09") and man.get("stand_10", {}).get("overlay_10") and man.get("stand_10a", {}).get("overlay_10a") and man.get("stand_10b", {}).get("overlay_10b") and man.get("stand_10c", {}).get("overlay_10c") and man.get("stand_11", {}).get("overlay_11") and man.get("overlay_sha256")):
        raise SystemExit("ABBRUCH: Manifest ohne alle Ebenen 06/07/08/09/10/10a/10b/10c/11")
    crate = root / "native_core/matrix-boundary-core"
    sh(["cargo", "build", "--release", "--offline", "--locked"], cwd=crate)
    (root / "matrix_api/native").mkdir(parents=True, exist_ok=True)
    shutil.copy2(crate / "target/release" / LIB, root / "matrix_api/native" / LIB)
    sh(["npm", "ci", "--no-audit", "--no-fund"], cwd=root)
    sh(["npm", "run", "build:dist"], cwd=root)
    if not (root / "frontend_dist/index.html").is_file():
        raise SystemExit("ABBRUCH: frontend_dist/index.html fehlt nach dem Build")
    name = f"MATRIX10_STAND11_PRODUKT_{PLATTFORM}_{kurz}"
    pkg = tmp / name
    shutil.copytree(root, pkg, ignore=lambda d, n: [x for x in n if x in WEG])
    for sub, files in PRUEF.items():
        (pkg / "pruefung" / sub).mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(f, pkg / "pruefung" / sub / f.name)
    # Lieferdokumente (keine Produktlogik): Vertragsgrundlage beilegen, README beschreibt den gelieferten Stand
    src = M10 / "MATRIX10_RUST_ARBEITSSTAND_04_20261107/sources"
    (pkg / "vertrag").mkdir()
    for n in ("AMASTERv2.md(1).txt", "Matrix10.txt", "VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt"):
        shutil.copy2(src / n, pkg / "vertrag" / n)
    (pkg / "README.md").rename(pkg / "README_P25_QUELLARBEITSKOPIE.md")
    shutil.copy2(HIER / "tools/README_STAND11.md", pkg / "README.md")
    res = json.loads((M10 / "ARBEITSSTAND_08/evidence/chain_08/result_08.json").read_text())
    status = {
        "stand": "11", "plattform": PLATTFORM, "nur_getestet_auf": "Linux x86_64 (diese Umgebung); keine Aussage zu Windows/Android",
        "commit": commit, "branch": "claude/matrix10-rust-repair-xq9k34", "repository": "https://github.com/ifdir/DeepSeek-V3",
        "p25_zip_sha256": man["basis_sha256"], "ebene_06": man["overlay_sha256"], "ebene_07": man["stand_07"]["overlay_07"],
        "ebene_08": man["stand_08"]["overlay_08"],
        "ebene_09": man["stand_09"]["overlay_09"],
        "ebene_10": man["stand_10"]["overlay_10"],
        "ebene_10a": man["stand_10a"]["overlay_10a"],
        "ebene_10b": man["stand_10b"]["overlay_10b"], "ebene_10c": man["stand_10c"]["overlay_10c"], "ebene_11": man["stand_11"]["overlay_11"], "rust_bibliothek_sha256": sha(pkg / "matrix_api/native" / LIB),
        "frontend_index_sha256": sha(pkg / "frontend_dist/index.html"),
        "gesamtstatus": "ROT - keine Produktfreigabe",
        "vorgaenger": "Stand 10C (b0cba3b)",
        "aenderung_11": "SPS V62.7: Planer -> Erleben (je Figur EIN Aufruf mit Kausalnachweis) -> EINE Formulierung; alle Fachlesungen (Vollzug, Wirkung, Beruehrung, Bewegung, Koerper + Bestaetigung, Grenze, Bitte/Erlaubnis, Sprecher, Komponentenart, Sprache, Namen, Aussagen, Offenbarung) kommen aus der ersten Antwort und werden unveraendert vom Kernel geprueft; Brief: aktuelle Lage vor dem Profil",
        "offen_11": "12 P25-Tests sind schon im unveraenderten P25 rot (siehe ARBEITSSTAND_11/BEFUND_STAND11.md); echtes Modell und Android-Geraet UNGEPRUEFT",
        "anlass_10a": "Android 08.11.: 503 'Rust-Schreibgrenze konnte nicht geladen werden' ohne Grund bei der ersten Beruehrungs-Eingabe",
        "aenderung_09": "F1-B2: Beziehungsrahmen der Bewertung nennt Person und Ereignis (kernel.appraisal_payload)",
        "aenderung_10": "F2: Zug ohne Nutzereingabe spricht nur die vom Server gewaehlte Figur (app.autochat_sprecher in prepare)",
        "aenderung_10b": "Unabhaengige Modell-Lesungen gleichzeitig (Antwort: Offenbarung/Wirkung/Koerper/Grenze; Puppet: Sprache), gleiche Aufrufe und gleicher Endstand wie 10a/P25, je Austausch ~20-25 % kuerzer",
        "gleichstand_p25": "Aufrufe und Zustand identisch mit P25 (ARBEITSSTAND_10A/BEFUND_GLEICHSTAND_P25_10A.md); Wiederholung/AutoChat/Lesungszahl = P25-Bestand",
        "aenderung_10a": "Rust-Ladediagnose: Grund beim Start (START.py), in /api/health (rustKern), im 503-Text und als Hinweisbalken in der UI; fail-closed unveraendert",
        "f2_bindung": "ERFUELLT mit lokalem Testmodell (ARBEITSSTAND_10/BEFUND_F2_10.md); Sprecherwahl nutzt weiter Wortlisten (K-05 ROT)",
        "f1_kernkette": "ERFUELLT mit lokalem Testmodell (ARBEITSSTAND_09/BEFUND_F1_DURCHLAUF_09.md); echtes Modell UNGEPRUEFT",
        "vertrag_sha256": {n: sha(pkg / "vertrag" / n) for n in sorted(x.name for x in (pkg / "vertrag").iterdir())},
        "vertragsstatus_aus_gesamtlauf_chain_08": res["vertragsstatus"],
        "vertragsstatus_hinweis": "Gesamtlauf chain_08 auf Ebene 08; Ebenen 09/10 im Pruefprotokoll (F1, F2, Tests, P25-Suite, Live K-01/K-02)",
        "paketpruefung": "siehe MATRIX10_STAND11_PRUEFPROTOKOLL (wird nach Pruefung des entpackten ZIP mitgeliefert)",
    }
    (pkg / "MATRIX10_STAND11_STATUS.json").write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n")
    shutil.copy2(M10 / "ARBEITSSTAND_10A/tools/RUST_AUF_DEM_HANDY_BAUEN.sh", pkg / "RUST_AUF_DEM_HANDY_BAUEN.sh")
    shutil.copy2(HIER / "tools/MATRIX10_STAND11_START.txt", pkg / "MATRIX10_STAND11_START.txt")
    shutil.copy2(HIER / "tools/MATRIX10_STAND11_START_ANDROID.txt", pkg / "MATRIX10_STAND11_START_ANDROID.txt")
    zp = out / f"{name}.zip"
    zp.unlink(missing_ok=True)
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(pkg.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(tmp))
    (out / f"{name}.zip.sha256").write_text(f"{sha(zp)}  {zp.name}\n")
    shutil.rmtree(tmp, ignore_errors=True)
    print(zp, sha(zp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
