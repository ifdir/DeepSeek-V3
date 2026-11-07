"""Isolated ORIGINAL repository functions, without a Flask request runtime.

This is NOT a live product import and NOT frontend/E2E evidence. The only removed
AST node is repos.py's isolation import, replaced by the byte-for-byte bodies of
its five pure ownership predicates from isolation.py. No predicate is mocked.
All SQLite writers, boundary checks and reducers execute their original bodies.
"""
from __future__ import annotations
import ast
import importlib
from pathlib import Path
import sqlite3
import sys
import types


def load_reference(root: Path) -> tuple[types.ModuleType, types.ModuleType]:
    sys.path.insert(0, str(root))
    db = importlib.import_module("matrix_api.db")
    text = (root / "matrix_api/repos.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    removed = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "matrix_api.isolation"]
    if len(removed) != 1:
        raise RuntimeError("Expected exactly one isolation import")
    names = {x.name for x in removed[0].names}
    iso = ast.parse((root / "matrix_api/isolation.py").read_text(encoding="utf-8"))
    pure = [n for n in iso.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in pure} != names:
        raise RuntimeError("Ownership predicate inventory mismatch")
    module = types.ModuleType("matrix_api._isolated_repository_probe")
    module.__dict__["__file__"] = str(root / "matrix_api/repos.py")
    module.__dict__["GASTHAUS_ID"] = db.GASTHAUS_ID
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *pure], type_ignores=[])),
                 str(root / "matrix_api/isolation.py"), "exec"), module.__dict__)
    tree.body = [n for n in tree.body if n not in removed]
    exec(compile(tree, str(root / "matrix_api/repos.py"), "exec"), module.__dict__)
    return module, db


def create_fixture(path: Path, db) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    for sql in db.SCHEMA_STATEMENTS:
        conn.execute(sql)
    db.ensure_relations_owner(conn)
    db.ensure_consistency_triggers(conn)
    db.ensure_query_indexes(conn)
    db.ensure_read_views(conn)
    # Real reference schema/views/triggers; no production DB copied.
    import json
    for letter in ("A", "B"):
        user, world, sid = f"usr_{letter}", f"world_{letter}", f"session_{letter}"
        conn.execute("INSERT INTO users(id,json) VALUES(?,?)", (user, json.dumps({"id": user})))
        conn.execute("INSERT INTO worlds(id,owner_user_id,json) VALUES(?,?,?)", (world, user, json.dumps({"id": world})))
        conn.execute("INSERT INTO sessions(id,user_id,world_id,json) VALUES(?,?,?,?)", (sid,user,world,json.dumps({"id":sid,"userId":user,"worldId":world,"turnIndex":20})))
    for char, world, user in [("alice","world_A","usr_A"),("bob","world_A","usr_A"),("foreign","world_B","usr_B")]:
        conn.execute("INSERT INTO characters(id,world_id,owner_user_id,json) VALUES(?,?,?,?)", (char,world,user,json.dumps({"id":char,"name":char})))
    conn.commit()
    return conn
