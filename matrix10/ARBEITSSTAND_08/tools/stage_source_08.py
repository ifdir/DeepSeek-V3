#!/usr/bin/env python3
"""Arbeitsstand 08: Stage 07 (P25 + 06a + 07, unveraendertes stage_source_07.py), dann Overlay 08 (K-02). KEIN Produkt-Release.

- Jede Datei, die Overlay 08 ersetzt, muss im Stage-07-Stand den eingefrorenen Basis-Hash haben.
- Jede ersetzte Datei MUSS im Overlay 08 liegen (Lehre aus 06a: .gitignore `lib/`).
Aufruf: python3 -I stage_source_08.py <P25.zip> <zielordner>
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
STAGE07 = HIER.parent / "ARBEITSSTAND_07" / "tools" / "stage_source_07.py"
P25_DIR = "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
BASIS = {   # Datei im Stage-07-Stand -> SHA-256 der Basis
    "matrix_api/kernel.py": "ae4cb81389f5f6b2c5bed25138c0a1a3aa0a5388d229f7c11547234888026179",          # Overlay 07
    "matrix_api/app.py": "4535fbebec7ce0b7a7ace1e5a6e1f850377b3c2f69ea517e2e5b3013c31368c1",             # Overlay 07
    "src/routes/memory.tsx": "f2d54df87b5f6ab05e6408be9b8a42013e31dd2a7cf47a468120c856e774c668",         # P25
    "src/lib/matrix/api.ts": "e1a088e28a7b0dbca995470baf5c31aeeef66a916e145e99cd4b89d8caa54da0",         # Overlay 06a
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    zpath, target = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    fehlend = sorted(rel for rel in BASIS if not (OVERLAY / rel).is_file())
    extra = sorted(str(p.relative_to(OVERLAY)) for p in OVERLAY.rglob("*") if p.is_file() and str(p.relative_to(OVERLAY)) not in BASIS)
    if fehlend or extra:
        print(f"ABBRUCH: Overlay 08 unvollstaendig/unerwartet: fehlt {fehlend}, unerwartet {extra}")
        return 2
    r = subprocess.run([sys.executable, "-I", str(STAGE07), str(zpath), str(target)], capture_output=True, text=True)
    if r.returncode != 0:
        print("ABBRUCH: Stage 07:", r.stdout, r.stderr)
        return 2
    root = target / P25_DIR
    for rel, want in BASIS.items():
        if sha(root / rel) != want:
            print(f"ABBRUCH: {rel} hat im Stage-07-Stand nicht den eingefrorenen Basis-Hash")
            return 2
    angewandt = {}
    for rel in BASIS:
        shutil.copy2(OVERLAY / rel, root / rel)
        angewandt[rel] = sha(root / rel)
    m = json.loads((target / "STAGE_07_MANIFEST.json").read_text())
    m["stand_08"] = {"basis_sha256": {k: v for k, v in BASIS.items()}, "overlay_08": angewandt, "product_release": False,
                     "einordnung": "K-02 Wahrnehmung der Antwortphase + kanonischer Figurenabruf im Frontend; Gesamtprodukt ROT"}
    (target / "STAGE_08_MANIFEST.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    print(f"Stage 08 bereit: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
