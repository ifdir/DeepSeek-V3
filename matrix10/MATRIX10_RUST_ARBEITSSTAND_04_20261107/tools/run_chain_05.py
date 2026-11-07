#!/usr/bin/env python3
"""Stand 05: EIN Gesamtlauf statt Einzeltests.

Reihenfolge (jede Stufe muss gruen sein, sonst Abbruch, Exit != 0):
  0. SHA256SUMS des Arbeitsstands 04 pruefen (Quellen/Code unveraendert).
  A. Ohne native Bibliothek: fail-closed-Nachweis (Transport 02 + Consent-Transport 03).
  B. cargo test --offline --locked (alle Rust-Unit-Tests, Zahl wird geparst).
  C. cargo build --release --offline --locked, .so nach integration/native/.
  D. Mit nativer Bibliothek: Consent-Transport 03 + Gesamtkette 05
     (Reader -> FFI -> Rust -> Projektion, Zeitleiste, Kreuz-Invarianten,
     Differenz gegen rekonstruiertes Original-V67).
  E. Mutationsprobe: Sprecher- und Fensterpruefung in Rust einzeln entfernt,
     neu gebaut; Gesamtkette MUSS rot werden.
  F. Schreibgrenze Lifecycle (echte .so): Kontrollen muessen stimmen; die
     belegten Defekte W1-W3 werden als OFFEN gemeldet, nicht als Gruen.

Nicht enthalten (NICHT_PRUEFBAR ohne V67-ZIP): Writer, SQLite, Neustart,
Folgeturn, HTTP, Frontend, Isolation. Kein Produkt-Release.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "integration/native_core/matrix-boundary-core"
LIB = "libmatrix_boundary_core.so"
NATIVE_DIR = ROOT / "integration/native"
MUTATIONS = {
    "ohne_sprecherbindung": ("e.active && e.by == giver", "e.active"),
    "ohne_gueltigkeitsfenster": ("e.active && e.by == giver", "e.by == giver"),
    # Stand 05: Widerruf/Ablehnung einer Tat darf keine Grenze aufheben ...
    "taetantwort_hebt_grenze_auf": ('if broad_kind == "refusal" && is_act_answer_against(&e) {', "if false {"),
    # ... und wirkt nur fuer die Stelle, an die sie gebunden ist.
    "taetantwort_ohne_bindung": ("!e.acts_bound || e.acts.iter()", "true || e.acts.iter()"),
}


def sh(cmd, cwd=ROOT):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def unit(pattern, root=ROOT):
    code, out = sh([sys.executable, "-B", "-m", "unittest", "discover", "-s", str(root / "tests"),
                    "-p", pattern, "-v"], cwd=root)
    ran = re.search(r"Ran (\d+) test", out)
    skipped = re.search(r"skipped=(\d+)", out)
    return {"pattern": pattern, "exit": code, "ran": int(ran.group(1)) if ran else 0,
            "skipped": int(skipped.group(1)) if skipped else 0}, out


def main() -> int:
    evidence = ROOT / "evidence/chain_05"
    evidence.mkdir(parents=True, exist_ok=True)
    result = {"stand": "05", "product_release": False, "stages": {}, "status": "ROT"}

    def stop(stage, reason):
        result["stages"].setdefault(stage, {})
        if isinstance(result["stages"][stage], list):
            result["stages"][stage] = {"laeufe": result["stages"][stage]}
        result["stages"][stage]["reason"] = reason
        (evidence / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(f"ROT in Stufe {stage}: {reason}")
        return 1

    # 0 -- Integritaet
    # Stand 04 ist die Basis; in Stand 05 duerfen NUR diese Dateien bewusst abweichen.
    changed_05 = {"integration/scene_state.py", "integration/native_boundary.py",
                  "integration/native_core/matrix-boundary-core/src/consent.rs",
                  "integration/native_core/matrix-boundary-core/src/lib.rs",
                  "tests/test_consent_transport_03.py"}  # nur Testdaten an ABI-3-Eintragsform
    bad, changed = [], []
    for line in (ROOT / "SHA256SUMS.txt").read_text().splitlines():
        digest, name = line.split(None, 1)
        name = name.strip().lstrip("*")
        p = ROOT / name
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            (changed if name in changed_05 else bad).append(name)
    result["stages"]["0_integritaet"] = {"unerwartet_abweichend": bad, "bewusst_geaendert_05": sorted(changed)}
    if bad:
        return stop("0_integritaet", "SHA256SUMS weicht ausserhalb der Stand-05-Aenderungen ab")

    # A -- fail-closed ohne Rust
    shutil.rmtree(NATIVE_DIR, ignore_errors=True)
    logs = []
    stage = []
    for pat in ("test_transport_02.py", "test_consent_transport_03.py"):
        r, out = unit(pat)
        stage.append(r)
        logs.append(out)
    (evidence / "A_fail_closed.log").write_text("\n".join(logs))
    result["stages"]["A_fail_closed_ohne_rust"] = stage
    if any(r["exit"] for r in stage):
        return stop("A_fail_closed_ohne_rust", "fail-closed-Tests rot")

    # B/C -- cargo
    ver = sh(["rustc", "--version"])[1].strip()
    code, out = sh(["cargo", "test", "--offline", "--locked"], cwd=CRATE)
    (evidence / "B_cargo_test.log").write_text(out)
    passed = sum(int(x) for x in re.findall(r"test result: ok\. (\d+) passed", out))
    failed = sum(int(x) for x in re.findall(r"(\d+) failed", out))
    result["stages"]["B_cargo_test"] = {"rustc": ver, "exit": code, "passed": passed, "failed": failed}
    if code or failed:
        return stop("B_cargo_test", "Rust-Tests rot")
    code, out = sh(["cargo", "build", "--release", "--offline", "--locked"], cwd=CRATE)
    (evidence / "C_cargo_build.log").write_text(out)
    built = CRATE / "target/release" / LIB
    result["stages"]["C_cargo_build"] = {"exit": code, "warnings": out.count("warning:")}
    if code or not built.is_file():
        return stop("C_cargo_build", "Build rot")
    NATIVE_DIR.mkdir(exist_ok=True)
    shutil.copy2(built, NATIVE_DIR / LIB)
    result["stages"]["C_cargo_build"]["library_sha256"] = hashlib.sha256(built.read_bytes()).hexdigest()

    # D -- native Gesamtkette
    logs, stage = [], []
    for pat in ("test_consent_transport_03.py", "test_consent_native_chain_05.py"):
        r, out = unit(pat)
        stage.append(r)
        logs.append(out)
    (evidence / "D_native_chain.log").write_text("\n".join(logs))
    result["stages"]["D_native_gesamtkette"] = stage
    if any(r["exit"] for r in stage) or stage[1]["skipped"]:
        return stop("D_native_gesamtkette", "native Gesamtkette rot oder uebersprungen")

    # E -- Mutationsprobe: der Gesamttest muss Defekte erkennen koennen
    killed = {}
    with tempfile.TemporaryDirectory(prefix="matrix05_mut_") as tmp:
        for name, (old, new) in MUTATIONS.items():
            copy = Path(tmp) / name
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("target", "native", "evidence"))
            src = copy / "integration/native_core/matrix-boundary-core/src/consent.rs"
            text = src.read_text()
            if text.count(old) != 1:
                return stop("D_native_gesamtkette", f"Mutationsanker {name} nicht eindeutig")
            src.write_text(text.replace(old, new))
            mcrate = copy / "integration/native_core/matrix-boundary-core"
            code, _ = sh(["cargo", "build", "--release", "--offline", "--locked"], cwd=mcrate)
            (copy / "integration/native").mkdir()
            shutil.copy2(mcrate / "target/release" / LIB, copy / "integration/native" / LIB)
            r, _ = unit("test_consent_native_chain_05.py", root=copy)
            killed[name] = {"build_exit": code, "chain_exit": r["exit"], "erkannt": code == 0 and r["exit"] != 0}
    result["stages"]["E_mutationsprobe"] = killed
    if not all(k["erkannt"] for k in killed.values()):
        return stop("E_mutationsprobe", "Mutation nicht erkannt: Gesamttest zu schwach")

    # F -- Schreibgrenze (Befund, kein Gruen)
    code, out = sh([sys.executable, "-B", str(ROOT / "tools/probe_writer_semantics_05.py")])
    (evidence / "F_writer_semantics.log").write_text(out)
    probe = json.loads((evidence / "writer_semantics_05.json").read_text())
    result["stages"]["F_schreibgrenze_lifecycle"] = {"exit": code, "controls_ok": probe["controls_ok"],
                                                    "offene_defekte": probe["writer_semantic_defects"]}
    if code or not probe["controls_ok"]:
        return stop("F_schreibgrenze_lifecycle", "Kontrollfaelle der Schreibgrenze rot")

    result["status"] = ("TEILGRUEN_CONSENT_READER_KETTE__WRITER_ROT" if probe["writer_semantic_defects"]
                        else "TEILGRUEN_CONSENT_READER_KETTE")
    result["nicht_pruefbar"] = ["V67-Writer", "SQLite Commit/Close/Reopen", "Folgeturn", "HTTP",
                                "Frontend", "User-/Session-Isolation", "AMASTER-Gesamtabnahme V12"]
    result["fehlt"] = "MATRIX10_V67_ABHAENGIGKEIT_20261031.zip (SHA-256 5158df26...efed)"
    (evidence / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
