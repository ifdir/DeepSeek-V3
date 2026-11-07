#!/usr/bin/env python3
"""Build/test native SOURCE work; this does NOT grant a product release.
A missing compiler is BLOCKIERT, never a skipped/passing test.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("product_root", type=Path)
    p.add_argument("--evidence-dir", type=Path, required=True)
    a = p.parse_args()
    root = a.product_root.resolve()
    evidence = a.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    result = {"product_acceptance": "UNGEPRUEFT", "product_release": False,
              "rustc": shutil.which("rustc"), "cargo": shutil.which("cargo"), "steps": []}
    target = evidence / "native_build_result.json"
    if not result["rustc"] or not result["cargo"]:
        result.update(status="BLOCKIERT", reason="Rust compiler/toolchain not installed", native_tests_executed=0)
        target.write_text(json.dumps(result, indent=2) + "\n")
        print("BLOCKIERT: rustc/cargo fehlen; 0 Rust-Tests ausgefuehrt. Keine Produktfreigabe.")
        return 3
    manifest = root / "native_core/matrix-boundary-core/Cargo.toml"
    if not manifest.is_file():
        result.update(status="BLOCKIERT", reason="Staged Cargo.toml missing")
        target.write_text(json.dumps(result, indent=2) + "\n")
        return 3
    for name, command in [
        ("rustc_version", [result["rustc"], "--version", "--verbose"]),
        ("test", [result["cargo"], "test", "--offline", "--locked", "--manifest-path", str(manifest)]),
        ("build", [result["cargo"], "build", "--release", "--offline", "--locked", "--manifest-path", str(manifest)]),
    ]:
        run = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
        log = evidence / f"cargo_{name}.log"
        log.write_text(run.stdout + run.stderr, encoding="utf-8")
        result["steps"].append({"name": name, "command": command, "exit_code": run.returncode, "log": log.name})
        if run.returncode:
            result.update(status="ROT", reason=f"Native {name} failed")
            target.write_text(json.dumps(result, indent=2) + "\n")
            return 1
    filename = ("matrix_boundary_core.dll" if sys.platform == "win32" else
                "libmatrix_boundary_core.dylib" if sys.platform == "darwin" else "libmatrix_boundary_core.so")
    source = manifest.parent / "target/release" / filename
    if not source.is_file():
        result.update(status="ROT", reason="Compiler returned success but native library was not found")
        target.write_text(json.dumps(result, indent=2) + "\n")
        return 1
    dest = root / "matrix_api/native" / filename
    dest.parent.mkdir(exist_ok=True)
    shutil.copy2(source, dest)
    result.update(status="NATIVE_BUILD_ONLY", library_sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
                  note="Native unit tests/build are NOT frontend/SQLite/next-turn/isolation acceptance")
    target.write_text(json.dumps(result, indent=2) + "\n")
    print("Native library built. Matrix10-Gesamtabnahme: UNGEPRUEFT. Keine Produktfreigabe.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
