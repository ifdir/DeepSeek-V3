#!/usr/bin/env python3
"""Arbeitsstand 10a: Stage 10 (P25 + 06a + 07 + 08 + 09 + 10, unveraendertes stage_source_10.py), dann Overlay 10Ba (Rust-Ladediagnose). KEIN Produkt-Release.

- Jede Datei, die Overlay 10B ersetzt, muss im Stage-10a-Stand den eingefrorenen Basis-Hash haben.
- Jede ersetzte Datei MUSS im Overlay 10B liegen (Lehre aus 06a: .gitignore `lib/`).
Aufruf: python3 -I stage_source_10b.py <P25.zip> <zielordner>
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
STAGE10A = HIER.parent / "ARBEITSSTAND_10A" / "tools" / "stage_source_10a.py"
P25_DIR = "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
BASIS = {   # Datei im Stage-10a-Stand -> SHA-256 der Basis
    "matrix_api/app.py": "5e42008692001a38c91024ce3deed64a58be09001f2eb13271605d104ade1807",   # Overlay 10a
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    zpath, target = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    fehlend = sorted(rel for rel in BASIS if not (OVERLAY / rel).is_file())
    extra = sorted(str(p.relative_to(OVERLAY)) for p in OVERLAY.rglob("*") if p.is_file() and str(p.relative_to(OVERLAY)) not in BASIS)
    if fehlend or extra:
        print(f"ABBRUCH: Overlay 10B unvollstaendig/unerwartet: fehlt {fehlend}, unerwartet {extra}")
        return 2
    r = subprocess.run([sys.executable, "-I", str(STAGE10A), str(zpath), str(target)], capture_output=True, text=True)
    if r.returncode != 0:
        print("ABBRUCH: Stage 10a:", r.stdout, r.stderr)
        return 2
    root = target / P25_DIR
    for rel, want in BASIS.items():
        if sha(root / rel) != want:
            print(f"ABBRUCH: {rel} hat im Stage-10a-Stand nicht den eingefrorenen Basis-Hash")
            return 2
    angewandt = {}
    for rel in BASIS:
        shutil.copy2(OVERLAY / rel, root / rel)
        angewandt[rel] = sha(root / rel)
    m = json.loads((target / "STAGE_10A_MANIFEST.json").read_text())
    m["stand_10b"] = {"basis_sha256": {k: v for k, v in BASIS.items()}, "overlay_10b": angewandt, "product_release": False,
                     "einordnung": "Unabhaengige Modell-Lesungen gleichzeitig (SPS V62-Muster), gleiche Aufrufe/Ergebnisse; Gesamtprodukt ROT"}
    (target / "STAGE_10B_MANIFEST.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    print(f"Stage 10B bereit: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
