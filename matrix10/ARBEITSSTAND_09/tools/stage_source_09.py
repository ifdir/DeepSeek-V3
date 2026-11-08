#!/usr/bin/env python3
"""Arbeitsstand 09: Stage 08 (P25 + 06a + 07 + 08, unveraendertes stage_source_08.py), dann Overlay 09 (F1-B2). KEIN Produkt-Release.

- Jede Datei, die Overlay 09 ersetzt, muss im Stage-08-Stand den eingefrorenen Basis-Hash haben.
- Jede ersetzte Datei MUSS im Overlay 09 liegen (Lehre aus 06a: .gitignore `lib/`).
Aufruf: python3 -I stage_source_09.py <P25.zip> <zielordner>
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
STAGE08 = HIER.parent / "ARBEITSSTAND_08" / "tools" / "stage_source_08.py"
P25_DIR = "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
BASIS = {   # Datei im Stage-08-Stand -> SHA-256 der Basis
    "matrix_api/kernel.py": "82c9892bb74deae85ee81eee62a4ae12d95f2f3be432f3d0b599af45853c3559",          # Overlay 08
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    zpath, target = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    fehlend = sorted(rel for rel in BASIS if not (OVERLAY / rel).is_file())
    extra = sorted(str(p.relative_to(OVERLAY)) for p in OVERLAY.rglob("*") if p.is_file() and str(p.relative_to(OVERLAY)) not in BASIS)
    if fehlend or extra:
        print(f"ABBRUCH: Overlay 09 unvollstaendig/unerwartet: fehlt {fehlend}, unerwartet {extra}")
        return 2
    r = subprocess.run([sys.executable, "-I", str(STAGE08), str(zpath), str(target)], capture_output=True, text=True)
    if r.returncode != 0:
        print("ABBRUCH: Stage 08:", r.stdout, r.stderr)
        return 2
    root = target / P25_DIR
    for rel, want in BASIS.items():
        if sha(root / rel) != want:
            print(f"ABBRUCH: {rel} hat im Stage-08-Stand nicht den eingefrorenen Basis-Hash")
            return 2
    angewandt = {}
    for rel in BASIS:
        shutil.copy2(OVERLAY / rel, root / rel)
        angewandt[rel] = sha(root / rel)
    m = json.loads((target / "STAGE_08_MANIFEST.json").read_text())
    m["stand_09"] = {"basis_sha256": {k: v for k, v in BASIS.items()}, "overlay_09": angewandt, "product_release": False,
                     "einordnung": "F1-B2: Beziehungsrahmen der Bewertung nennt die Person; Gesamtprodukt ROT"}
    (target / "STAGE_09_MANIFEST.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    print(f"Stage 09 bereit: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
