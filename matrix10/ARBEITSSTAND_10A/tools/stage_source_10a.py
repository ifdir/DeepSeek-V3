#!/usr/bin/env python3
"""Arbeitsstand 10a: Stage 10 (P25 + 06a + 07 + 08 + 09 + 10, unveraendertes stage_source_10.py), dann Overlay 10aa (Rust-Ladediagnose). KEIN Produkt-Release.

- Jede Datei, die Overlay 10a ersetzt, muss im Stage-10-Stand den eingefrorenen Basis-Hash haben.
- Jede ersetzte Datei MUSS im Overlay 10a liegen (Lehre aus 06a: .gitignore `lib/`).
Aufruf: python3 -I stage_source_10a.py <P25.zip> <zielordner>
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
STAGE10 = HIER.parent / "ARBEITSSTAND_10" / "tools" / "stage_source_10.py"
P25_DIR = "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
BASIS = {   # Datei im Stage-10-Stand -> SHA-256 der Basis
    "matrix_api/native_boundary.py": "f7e8d5de92249c0c5f271847670add14f7c77729bf8402747990d12de6e42e90",   # Overlay 06
    "matrix_api/app.py": "c946a4964f3acd5fbbccab1e18390c2c2623cb9699385081f262e99f6bba5685",               # Overlay 10
    "START.py": "25167dd87a8f96cc76a6218d02b168c434b1d49ac5c43f55e56913ce82b9eedd",                        # P25
    "src/components/shell.tsx": "4459566b75bec36e7b21f6ec06f8946edb91be7014e628f1db6643587075222f",        # P25
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    zpath, target = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    fehlend = sorted(rel for rel in BASIS if not (OVERLAY / rel).is_file())
    extra = sorted(str(p.relative_to(OVERLAY)) for p in OVERLAY.rglob("*") if p.is_file() and str(p.relative_to(OVERLAY)) not in BASIS)
    if fehlend or extra:
        print(f"ABBRUCH: Overlay 10a unvollstaendig/unerwartet: fehlt {fehlend}, unerwartet {extra}")
        return 2
    r = subprocess.run([sys.executable, "-I", str(STAGE10), str(zpath), str(target)], capture_output=True, text=True)
    if r.returncode != 0:
        print("ABBRUCH: Stage 10:", r.stdout, r.stderr)
        return 2
    root = target / P25_DIR
    for rel, want in BASIS.items():
        if sha(root / rel) != want:
            print(f"ABBRUCH: {rel} hat im Stage-10-Stand nicht den eingefrorenen Basis-Hash")
            return 2
    angewandt = {}
    for rel in BASIS:
        shutil.copy2(OVERLAY / rel, root / rel)
        angewandt[rel] = sha(root / rel)
    m = json.loads((target / "STAGE_10_MANIFEST.json").read_text())
    m["stand_10a"] = {"basis_sha256": {k: v for k, v in BASIS.items()}, "overlay_10a": angewandt, "product_release": False,
                     "einordnung": "Rust-Ladediagnose: Grund beim Start, in /api/health, im 503-Text und als Hinweis in der UI; Gesamtprodukt ROT"}
    (target / "STAGE_10A_MANIFEST.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    print(f"Stage 10a bereit: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
