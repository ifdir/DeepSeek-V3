#!/usr/bin/env python3
"""Arbeitsstand 10: Stage 09 (P25 + 06a + 07 + 08 + 09, unveraendertes stage_source_09.py), dann Overlay 10 (F2: Sprecherbindung AutoChat). KEIN Produkt-Release.

- Jede Datei, die Overlay 10 ersetzt, muss im Stage-09-Stand den eingefrorenen Basis-Hash haben.
- Jede ersetzte Datei MUSS im Overlay 10 liegen (Lehre aus 06a: .gitignore `lib/`).
Aufruf: python3 -I stage_source_10.py <P25.zip> <zielordner>
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
STAGE09 = HIER.parent / "ARBEITSSTAND_09" / "tools" / "stage_source_09.py"
P25_DIR = "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
BASIS = {   # Datei im Stage-09-Stand -> SHA-256 der Basis
    "matrix_api/app.py": "a7272cb93049ae0c010e23fcbd687b1e749decc938c308dc34dcc996f5454965",          # Overlay 08
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    zpath, target = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    fehlend = sorted(rel for rel in BASIS if not (OVERLAY / rel).is_file())
    extra = sorted(str(p.relative_to(OVERLAY)) for p in OVERLAY.rglob("*") if p.is_file() and str(p.relative_to(OVERLAY)) not in BASIS)
    if fehlend or extra:
        print(f"ABBRUCH: Overlay 10 unvollstaendig/unerwartet: fehlt {fehlend}, unerwartet {extra}")
        return 2
    r = subprocess.run([sys.executable, "-I", str(STAGE09), str(zpath), str(target)], capture_output=True, text=True)
    if r.returncode != 0:
        print("ABBRUCH: Stage 09:", r.stdout, r.stderr)
        return 2
    root = target / P25_DIR
    for rel, want in BASIS.items():
        if sha(root / rel) != want:
            print(f"ABBRUCH: {rel} hat im Stage-09-Stand nicht den eingefrorenen Basis-Hash")
            return 2
    angewandt = {}
    for rel in BASIS:
        shutil.copy2(OVERLAY / rel, root / rel)
        angewandt[rel] = sha(root / rel)
    m = json.loads((target / "STAGE_09_MANIFEST.json").read_text())
    m["stand_10"] = {"basis_sha256": {k: v for k, v in BASIS.items()}, "overlay_10": angewandt, "product_release": False,
                     "einordnung": "F2: Sprecher eines Zugs ohne Nutzereingabe nur aus Serverwahl (Gate/Betroffen/Regie); Gesamtprodukt ROT"}
    (target / "STAGE_10_MANIFEST.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    print(f"Stage 10 bereit: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
