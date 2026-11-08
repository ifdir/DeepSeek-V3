#!/usr/bin/env python3
"""Stand 08 (K-02, Aufbau wie mutation_07.py): Mutationsgegenprobe - jede reparierte Schutzregel wird einzeln entfernt, die Tests muessen ROT werden.

Aufruf: python3 -I mutation_08.py <stage08-produktordner> <ausgabe.json>
Je Mutation: Kopie des Produktordners, genau eine Textersetzung (muss genau einmal passen), dann pytest auf
tests/test_k02_wissen_08.py. Erkannt = mindestens ein Test schlaegt fehl.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HIER = Path(__file__).resolve().parents[1]
TESTS = [str(HIER / "tests" / "test_k02_wissen_08.py")]
MUT = {
    "K02_M1_antwortphase_wahrnehmung_der_eingabe": ("matrix_api/kernel.py",
        "        truth[\"present_ids\"], truth[\"hears_ids\"], truth[\"sees_ids\"] = _pres_now, list(_hears_now), list(_sees_now)",
        "        pass"),
    "K02_M2_figurenabruf_nicht_kanonisch": ("matrix_api/app.py",
        "        if character_id:\n            # Stand 08 / K-02",
        "        if False:\n            # Stand 08 / K-02"),
}


def main():
    root, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    res = {}
    for name, (rel, a, b) in MUT.items():
        work = Path(tempfile.mkdtemp(prefix="mut08_")) / "p"
        shutil.copytree(root, work, ignore=shutil.ignore_patterns("node_modules", "frontend_dist", "target", "data"))
        f = work / rel
        t = f.read_text(encoding="utf-8")
        n = t.count(a)
        if n < 1:
            res[name] = {"fehler": f"Muster {n}x gefunden"}
            continue
        f.write_text(t.replace(a, b), encoding="utf-8")
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS], cwd=work,
                           env={"MATRIX07_ROOT": str(work), "PATH": "/usr/bin:/bin:/usr/local/bin"}, capture_output=True, text=True, timeout=900)
        failed = [ln.split("::", 1)[1] for ln in p.stdout.splitlines() if ln.startswith("FAILED")]
        res[name] = {"datei": rel, "ersetzungen": n, "erkannt": bool(failed), "rote_tests": failed,
                     "zusammenfassung": (p.stdout.strip().splitlines() or [""])[-1]}
        shutil.rmtree(work.parent, ignore_errors=True)
        print(name, "ERKANNT" if failed else "NICHT ERKANNT", len(failed))
    out.write_text(json.dumps({"mutationen": res, "alle_erkannt": all(v.get("erkannt") for v in res.values())}, indent=2, ensure_ascii=False) + "\n")
    return 0 if all(v.get("erkannt") for v in res.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
