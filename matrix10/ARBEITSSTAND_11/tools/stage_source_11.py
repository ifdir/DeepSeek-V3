#!/usr/bin/env python3
"""Arbeitsstand 11: Stage 10C (unveraendertes stage_source_10c.py), dann Overlay 11 (SPS V62.7: Fachlesungen aus der ersten Antwort). KEIN Produkt-Release.

- Jede Datei, die Overlay 11 ersetzt, muss im Stage-10C-Stand den eingefrorenen Basis-Hash haben.
- Jede ersetzte Datei MUSS im Overlay 11 liegen (Lehre aus 06a: .gitignore `lib/`).
Aufruf: python3 -I stage_source_11.py <P25.zip> <zielordner>
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HIER = Path(__file__).resolve().parents[1]
OVERLAY = HIER / "overlay"
STAGE10C = HIER.parent / "ARBEITSSTAND_10C" / "tools" / "stage_source_10c.py"
P25_DIR = "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
BASIS = {   # Datei im Stage-10C-Stand -> SHA-256 der Basis
    "matrix_api/llm_contract.py": "65b5d8f430d034b97102e4f0c26c5ebb7501d6a46c985e8a959a027f159a8112",   # Overlay 10C
    "matrix_api/app.py": "e6c3f6d445453654b4b38ad4bab8e36061151852a396282cc2304dcf03466ae8",   # Overlay 10B
    "matrix_api/kernel.py": "0bad26d267cd195b0093e59e0c6b73f7673cbd09553d0bde8581e9c147e00846",   # Overlay 09 (Stand 11B: Rest/Doppelung)
    "matrix_api/repos.py": "75f1b1eba70ea88975bfa444962671563b1a5e74abea552c82396eb453e68de1",   # Overlay 07 (Stand 12A: Runtime-Reset leert den Szenenzustand)
    "src/lib/matrix/eingabe-hinweis.ts": "e6d2ca5605a02b7abe0316c6cc54e1ae5cf2ecff0891a8e9af89441a6dce5915",   # P25 (Stand 11C: keine Lesevermerke)
    "tests/test_v92_puppet_kette.py": "883081900f409555281b261fa5b1eb69352d3233f72566c8510636ac1a285644",   # P25 (Stand 11C: C6-Test)
    # P25-Tests, deren Aufrufstruktur Stand 11 anpasst (Lesungen aus der ersten Antwort); Schutzaussagen bleiben
    "tests/test_v92_puppet_vertrag.py": "8415cff5db50f2d6b1fa48b4ae941b6c868c05bb124e3cf6fb8dbcdd18edfb0c",   # P25
    "tests/test_v92_avatar_route.py": "74fb8df70fbd42ab116fa36fc8cf28ebe233a341914c5b023fb271df69aef581",   # P25
    "tests/test_v92_p13_identitaet.py": "dd7f071ac7981dab553c95cc3839c2ccafc2a58e1fef069d026132a11655ba14",   # P25
    "tests/test_v92_p19_koerper.py": "ea5b1c65dc40111e758355eef98c835a2761cd2823025ab91cb0cf7e26d49c77",   # P25
    "tests/test_v84_kausal_chain.py": "76526b87414e904de4d1cd96e9eaae652991ae8b31bfbfb617a9c12a51ce63da",   # P25
    "tests/test_v87_kausalquelle.py": "0fa898bfd695c7680ba425d325db352fca88160d4b92025bc05f4063c7a4549e",   # P25
    "tests/test_v92_p20_semantische_name_god_scope.py": "faaac8cfcefbe245b40fd65343e16b09eface6639f55ca07c8c6a854ea8cc846",   # P25
    "tests/test_v92_p21_token_name_scope.py": "6af2d01ee9c03d07f89c55e313cd9883e0a158d418385bcc842fb3158a86e964",   # P25
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    zpath, target = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    fehlend = sorted(rel for rel in BASIS if not (OVERLAY / rel).is_file())
    extra = sorted(str(p.relative_to(OVERLAY)) for p in OVERLAY.rglob("*") if p.is_file() and str(p.relative_to(OVERLAY)) not in BASIS)
    if fehlend or extra:
        print(f"ABBRUCH: Overlay 11 unvollstaendig/unerwartet: fehlt {fehlend}, unerwartet {extra}")
        return 2
    r = subprocess.run([sys.executable, "-I", str(STAGE10C), str(zpath), str(target)], capture_output=True, text=True)
    if r.returncode != 0:
        print("ABBRUCH: Stage 10C:", r.stdout, r.stderr)
        return 2
    root = target / P25_DIR
    for rel, want in BASIS.items():
        if sha(root / rel) != want:
            print(f"ABBRUCH: {rel} hat im Stage-10C-Stand nicht den eingefrorenen Basis-Hash")
            return 2
    angewandt = {}
    for rel in BASIS:
        shutil.copy2(OVERLAY / rel, root / rel)
        angewandt[rel] = sha(root / rel)
    m = json.loads((target / "STAGE_10C_MANIFEST.json").read_text())
    m["stand_11"] = {"basis_sha256": {k: v for k, v in BASIS.items()}, "overlay_11": angewandt, "product_release": False,
                     "einordnung": "SPS V62.7: Planer -> Erleben -> Formulierung, Fachlesungen aus der ersten Antwort, Lage vor Profil; Gesamtprodukt ROT"}
    (target / "STAGE_11_MANIFEST.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    print(f"Stage 11 bereit: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
