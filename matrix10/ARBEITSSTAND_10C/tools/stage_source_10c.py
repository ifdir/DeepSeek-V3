#!/usr/bin/env python3
"""Arbeitsstand 10a: Stage 10 (P25 + 06a + 07 + 08 + 09 + 10, unveraendertes stage_source_10.py), dann Overlay 10Ca (Rust-Ladediagnose). KEIN Produkt-Release.

- Jede Datei, die Overlay 10C ersetzt, muss im Stage-10B-Stand den eingefrorenen Basis-Hash haben.
- Jede ersetzte Datei MUSS im Overlay 10C liegen (Lehre aus 06a: .gitignore `lib/`).
Aufruf: python3 -I stage_source_10c.py <P25.zip> <zielordner>
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
STAGE10B = HIER.parent / "ARBEITSSTAND_10B" / "tools" / "stage_source_10b.py"
P25_DIR = "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
BASIS = {   # Datei im Stage-10B-Stand -> SHA-256 der Basis
    "matrix_api/llm_contract.py": "6a1a9cbe621d4a7fbf644eededd4049d9becf64f6b7dacb24a1b44241fa50ac8",   # P25
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    zpath, target = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    fehlend = sorted(rel for rel in BASIS if not (OVERLAY / rel).is_file())
    extra = sorted(str(p.relative_to(OVERLAY)) for p in OVERLAY.rglob("*") if p.is_file() and str(p.relative_to(OVERLAY)) not in BASIS)
    if fehlend or extra:
        print(f"ABBRUCH: Overlay 10C unvollstaendig/unerwartet: fehlt {fehlend}, unerwartet {extra}")
        return 2
    r = subprocess.run([sys.executable, "-I", str(STAGE10B), str(zpath), str(target)], capture_output=True, text=True)
    if r.returncode != 0:
        print("ABBRUCH: Stage 10B:", r.stdout, r.stderr)
        return 2
    root = target / P25_DIR
    for rel, want in BASIS.items():
        if sha(root / rel) != want:
            print(f"ABBRUCH: {rel} hat im Stage-10B-Stand nicht den eingefrorenen Basis-Hash")
            return 2
    angewandt = {}
    for rel in BASIS:
        shutil.copy2(OVERLAY / rel, root / rel)
        angewandt[rel] = sha(root / rel)
    m = json.loads((target / "STAGE_10B_MANIFEST.json").read_text())
    m["stand_10c"] = {"basis_sha256": {k: v for k, v in BASIS.items()}, "overlay_10c": angewandt, "product_release": False,
                     "einordnung": "AMASTER §15 Kompass als Tendenz, §42/§49 aktuelle Absicht im Brief; Gesamtprodukt ROT"}
    (target / "STAGE_10C_MANIFEST.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    print(f"Stage 10C bereit: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
