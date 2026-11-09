#!/usr/bin/env python3
"""Arbeitsstand 07: P25 + Overlay 06a frisch entpacken (stage_source_06.py), dann Overlay 07 (K-01 + SEC). KEIN Produkt-Release.

- Stage 06 wird mit dem unveraenderten stage_source_06.py erzeugt (prueft P25-ZIP-SHA-256, CRC, Originalhashes).
- Jede Datei, die Overlay 07 ersetzt, muss im Stage-06-Stand den eingefrorenen Basis-Hash haben.
- Jede ersetzte Datei MUSS im Overlay 07 liegen (Lehre aus 06a: .gitignore `lib/` hat api.ts ausgeschlossen).
- Baut KEINE native Bibliothek und KEIN Frontend.

Aufruf: python3 -I stage_source_07.py <P25.zip> <zielordner> [--ohne-sec | --ohne-k01]
  --ohne-sec / --ohne-k01 nur fuer Gegenproben (Mutationslauf), nie fuer die Abnahme.
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
STAGE06 = HIER.parent / "ARBEITSSTAND_06" / "tools" / "stage_source_06.py"
P25_DIR = "MATRIX10_V92_P25_QUELLREPARATUR_ROT_20261107"
# Datei im Stage-06-Stand -> erwarteter SHA-256 (Basis, die Overlay 07 ersetzt), Massnahme
BASIS = {
    "matrix_api/app.py": ("31675d9daf59bfec2f004e3e20a65c56c53d579aff112d80998a139a88769caf", "K-01"),          # 06a-Overlay
    "matrix_api/scene_state.py": ("bb1d7681dd9a8ed64375e46aee950146c26eb19cc517195b16ed9733c9794060", "K-01"),  # 06a-Overlay
    "matrix_api/kernel.py": ("5502e44731e429efa9b55d37872abbef2d7411788c7a116cf72be6801d30a398", "K-01"),       # P25
    "src/lib/matrix/kernel-bridge.ts": ("e6736516b2a0deaec18b9cc2c1725ac0d1f58878649d97dcef5c6e86979a4532", "K-01"),  # P25
    "src/routes/chat.$sessionId.tsx": ("442466884803ed52b84f4824256c72e768b7fc7540433b5e537681f83022e4d3", "K-01"),   # P25
    "matrix_api/repos.py": ("c9b3554699be916aec2ca53f3de18ce2fe1bb24e83acc76b2731c21ca40cafd9", "SEC"),          # P25
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    args = sys.argv[1:]
    ohne = {"--ohne-sec": "SEC", "--ohne-k01": "K-01"}
    skip = {ohne[a] for a in args if a in ohne}
    pos = [a for a in args if a not in ohne]
    zpath, target = Path(pos[0]).resolve(), Path(pos[1]).resolve()
    fehlend = sorted(rel for rel in BASIS if not (OVERLAY / rel).is_file())
    extra = sorted(str(p.relative_to(OVERLAY)) for p in OVERLAY.rglob("*") if p.is_file() and str(p.relative_to(OVERLAY)) not in BASIS)
    if fehlend or extra:
        print(f"ABBRUCH: Overlay 07 unvollstaendig/unerwartet: fehlt {fehlend}, unerwartet {extra}")
        return 2
    r = subprocess.run([sys.executable, "-I", str(STAGE06), str(zpath), str(target)], capture_output=True, text=True)
    if r.returncode != 0:
        print("ABBRUCH: Stage 06:", r.stdout, r.stderr)
        return 2
    root = target / P25_DIR
    basis_ist = {rel: sha(root / rel) for rel in BASIS}
    for rel, (want, _m) in BASIS.items():
        if basis_ist[rel] != want:
            print(f"ABBRUCH: {rel} hat im Stage-06-Stand nicht den eingefrorenen Basis-Hash")
            return 2
    angewandt = {}
    for rel, (_want, mass) in BASIS.items():
        if mass in skip:
            continue
        shutil.copy2(OVERLAY / rel, root / rel)
        angewandt[rel] = {"massnahme": mass, "sha256": sha(root / rel)}
    m = target / "STAGE_06_MANIFEST.json"
    manifest = json.loads(m.read_text()) if m.exists() else {}
    manifest["stand_07"] = {"basis_sha256": basis_ist, "overlay_07": angewandt, "ausgelassen": sorted(skip),
                            "product_release": False,
                            "einordnung": "K-01 TurnTruth/Commit-Bindung + SEC Schluessel-Leck; Gesamtprodukt ROT"}
    (target / "STAGE_07_MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"Stage 07 bereit: {root} (ausgelassen: {sorted(skip) or '-'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
