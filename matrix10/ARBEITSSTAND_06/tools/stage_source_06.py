#!/usr/bin/env python3
"""Arbeitsstand 06: P25 frisch entpacken + Overlay anwenden. KEIN Produkt-Release.

- Prueft das P25-ZIP gegen den eingefrorenen SHA-256 und auf CRC.
- Verweigert einen bestehenden Zielordner.
- Prueft die Originalhashes der Dateien, die das Overlay ersetzt.
- Kopiert nur die Overlay-Dateien; alles andere bleibt P25-bytegleich.
- Baut KEINE native Bibliothek (das macht run_chain_06.py, Stufe C).

Aufruf: python3 -I stage_source_06.py <P25.zip> <zielordner>
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

P25_ZIP_SHA256 = "33a51497ce5e84fa9ee1f05a96338a67f93fdb17233b811713648cd4ac9860d1"
P25_DIR = "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
OVERLAY = Path(__file__).resolve().parents[1] / "overlay"
# Original-Datei in P25 -> erwarteter SHA-256 (nur Dateien, die das Overlay ERSETZT)
REPLACED = {"matrix_api/scene_state.py": "34c70dbd12281e2b2656171b25fc6bd517f6288533b67a6f02ec92c66c4ffee6",
            "matrix_api/app.py": "a17b6f47012df1751c9551402e8b195549348e58906a949bd6e108c0375519a3"}   # K2: nur NativeBoundaryError -> 503
NEW = {"matrix_api/native_boundary.py", "native_core/matrix-boundary-core"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    zpath, target = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    if target.exists():
        print(f"ABBRUCH: Zielordner existiert bereits: {target}")
        return 2
    if sha(zpath) != P25_ZIP_SHA256:
        print("ABBRUCH: P25-ZIP hat nicht den eingefrorenen SHA-256")
        return 2
    with zipfile.ZipFile(zpath) as z:
        bad = z.testzip()
        if bad:
            print(f"ABBRUCH: CRC-Fehler in {bad}")
            return 2
        for n in z.namelist():
            if n.startswith("/") or ".." in Path(n).parts:
                print(f"ABBRUCH: unsicherer Pfad {n}")
                return 2
        target.mkdir(parents=True)
        z.extractall(target)
    root = target / P25_DIR
    original = {rel: sha(root / rel) for rel in REPLACED}
    for rel, want in REPLACED.items():
        if original[rel] != want:
            print(f"ABBRUCH: {rel} in P25 hat nicht den erwarteten Originalhash")
            return 2
    for rel in NEW:
        if (root / rel).exists():
            print(f"ABBRUCH: {rel} existiert in P25 bereits; Overlay wuerde ueberschreiben")
            return 2
    for src in sorted(OVERLAY.rglob("*")):
        if src.is_file():
            rel = src.relative_to(OVERLAY)
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    manifest = {"basis": f"{P25_DIR}.zip", "basis_sha256": P25_ZIP_SHA256,
                "ersetzt_original_sha256": original,
                "overlay_sha256": {str(p.relative_to(OVERLAY)): sha(p) for p in sorted(OVERLAY.rglob("*")) if p.is_file()},
                "native_gebaut": False, "product_release": False,
                "einordnung": "Teilreparatur des P25-Einwilligungskerns, keine vollstaendige Rust-Migration"}
    (target / "STAGE_06_MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"Stage 06 bereit: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
