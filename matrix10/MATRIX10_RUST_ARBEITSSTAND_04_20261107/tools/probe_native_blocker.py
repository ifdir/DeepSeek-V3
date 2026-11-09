#!/usr/bin/env python3
"""Check the unavailable-native-module path in a staged repository copy.
This proves ONLY that missing native code does not authorize/write a TurnTruth.
It does not run Rust and does not prove any successful product functionality.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tests"))
from original_boundary_harness import load_reference,create_fixture


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("staged_root",type=Path)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args(); repo,db=load_reference(a.staged_root.resolve())
    from matrix_api.native_boundary import library_path
    if library_path().exists():
        print("BLOCKIERT: this test applies only to a source worktree without a native library")
        return 3
    with tempfile.TemporaryDirectory(prefix="matrix_native_blocker_") as folder:
        conn=create_fixture(Path(folder)/"probe.sqlite",db)
        before=list(conn.iterdump())
        error=None
        try:
            repo.append_session_turn_truth(conn,"session_A",{
                "id":"tt_probe","role":"avatar","authority":"avatar","speaker_id":"alice",
                "present_ids":["alice","bob"],"turn":1},"usr_A")
        except repo.WriterError as exc:
            error={"code":exc.error,"status":exc.status}
        after=list(conn.iterdump())
        count=conn.execute("SELECT COUNT(*) FROM turn_truth").fetchone()[0]
        unchanged=before==after
        conn.close()
    passed=error=={"code":"NATIVE_BOUNDARY_UNAVAILABLE","status":503} and count==0 and unchanged
    result={"scope":"STAGED_PYTHON_MISSING_LIBRARY_PATH_ONLY","passed":passed,"error":error,
            "turntruth_rows":count,"sqlite_dump_unchanged":unchanged,"rust_tests_executed":0,
            "product_acceptance":"BLOCKIERT","successful_native_operation_proven":False}
    a.output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    return 0 if passed else 1

if __name__=="__main__":
    raise SystemExit(main())
