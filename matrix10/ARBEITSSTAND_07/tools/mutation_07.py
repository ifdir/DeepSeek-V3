#!/usr/bin/env python3
"""Stand 07: Mutationsgegenprobe - jede reparierte Schutzregel wird einzeln entfernt, die Tests muessen ROT werden.

Aufruf: python3 -I mutation_07.py <stage07-produktordner> <ausgabe.json>
Je Mutation: Kopie des Produktordners, genau eine Textersetzung (muss genau einmal passen), dann pytest auf
tests/test_k01_turntruth_07.py + tests/test_sec_mcc_07.py. Erkannt = mindestens ein Test schlaegt fehl.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HIER = Path(__file__).resolve().parents[1]
TESTS = [str(HIER / "tests" / "test_k01_turntruth_07.py"), str(HIER / "tests" / "test_sec_mcc_07.py")]
MUT = {
    "M1_beleg_ohne_signaturpruefung": ("matrix_api/app.py",
        "    if not _hmac.compare_digest(_hmac.new(_BELEG_KEY, raw, _hashlib.sha256).digest(), sig):\n        return None",
        "    pass"),
    "M2_eingabe_actor_vom_client": ("matrix_api/app.py",
        "    derived = gebundener_eingabe_actor(session, raw)\n    sent = str(raw.get(\"inputActorId\") or raw.get(\"input_actor_id\") or \"\")",
        "    sent = str(raw.get(\"inputActorId\") or raw.get(\"input_actor_id\") or \"\")\n    derived = sent or gebundener_eingabe_actor(session, raw)"),
    "M3_formulierung_ohne_beleg": ("matrix_api/app.py",
        "            if not formulierung_leer(result):\n                _fb = beleg_lesen",
        "            if False:\n                _fb = beleg_lesen"),
    "M4_fired_vom_client": ("matrix_api/app.py",
        "                if body.get(_key) not in (None, []) and _kanon(body.get(_key)) != _kanon(_own):",
        "                if False:"),
    "M5_sprecher_ohne_faehigkeit": ("matrix_api/kernel.py",
        "        if float(1 if _cons is None else _cons) < 0.5:",
        "        if float(_cons or 1) < 0.5:"),
    "M6_hoerer_rueckfall": ("matrix_api/kernel.py",
        "        hears_now = list(_scene_perception(s, list((s.get(\"scene\") or {}).get(\"presentIds\") or []))[0])",
        "        hears_now = list((s.get(\"scene\") or {}).get(\"hearsIds\") or (s.get(\"scene\") or {}).get(\"presentIds\") or [])"),
    "M7_w2_fremde_evidenz_kernel": ("matrix_api/kernel.py",
        "            return named if str(named.get(\"actorId\") or named.get(\"actor_id\") or \"\") == str(actor_id or \"\") else None",
        "            return named"),
    "M8_w2_status_ohne_evidenz": ("matrix_api/kernel.py",
        "    if lifecycle_evidence_fact(s, str(actor_id), fact_id) is None:\n        # Stand 07",
        "    if False:\n        # Stand 07"),
    "M9_w2_leseseite": ("matrix_api/scene_state.py",
        "        if _ev is not None and str(_ev.get(\"actorId\") or _ev.get(\"actor_id\") or \"\") != actor:\n            return False",
        "        pass"),
    "M9b_w2_quellturn_regel": ("matrix_api/scene_state.py",
        "            if actor not in _parteien:\n                return False",
        "            pass"),
    "M10_sec_schluessel_im_mcc": ("matrix_api/repos.py",
        "        \"config\": public_config_view(config) if isinstance(config, dict) else {},",
        "        \"config\": config if isinstance(config, dict) else {},"),
}


def main():
    root, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    res = {}
    for name, (rel, a, b) in MUT.items():
        work = Path(tempfile.mkdtemp(prefix="mut07_")) / "p"
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
