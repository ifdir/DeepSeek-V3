"""Transactional MCC import + scoped SQL readers + product writers (B1R2.2/B1R2.4/B1R2.5).

IDs and relations are preserved. SQL user_id/world_id/session_id win;
JSON userId/worldId/sessionId are canonicalized to those columns on import.

Writers: Create vs Update are separate. Logs append-only. Config user-scoped.
PUT session is envelope-only (B1R2.4): child collections are not inserted,
updated, or deleted via snapshot. Dedicated session child writers own mutations.

B1R2.5: every child loaded from SQL overlays userId/worldId/sessionId from the
SQL columns. Stale or client JSON identity cannot appear in GET/Reload output.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

from matrix_api.db import CHILD_READ_VIEW, GASTHAUS_ID, VIEW_ALLOW
from matrix_api.upload_security import UploadSecurityError, validate_upload_meta
from matrix_api.ids import uid
from matrix_api.isolation import (
    is_shared_gasthaus,
    session_owner_ok,
    user_is_self,
    world_is_owned,
    world_is_readable,
)

MIGRATE_CLASSES = (
    "users",
    "activeUserId",
    "worlds",
    "characters",
    "sessions",
    "uploads",
    "reviews",
    "snapshots",
    "triggers",
    "logs",
    "preferences",
    "config",
)

NICHTKANONISCH_CLASSES = {
    "lastSpiegelJson": "UI-Cache/Lesespiegel, kein Master. Nach Reload aus kanonischem Zustand rekonstruierbar.",
    "compassPreview": "UI-Entwurf. Nicht Master.",
    "providerOnline": "Runtime-Flag.",
}

CHILD_FIELDS = (
    ("facts", "scene_facts"),
    ("memories", "memories"),
    ("godFacts", "god_facts"),
    ("turns", "turns"),
    ("turnTruths", "turn_truth"),
    ("propositions", "propositions"),
    ("goals", "goals"),
)

# relationships use a dedicated shape (from_id/to_id)
REL_FIELD = "relations"
REL_TABLE = "relationships"

# B1.4 persist/reader boundary. SQL child tables own these collections.
# sessions.json arrays are a PROJECTION rebuilt from SQL on productive reads.
SQL_OWNED_SESSION_COLLECTIONS = (
    ("facts", "scene_facts"),
    ("memories", "memories"),
    ("relations", "relationships"),
    ("godFacts", "god_facts"),
    ("turns", "turns"),
    ("turnTruths", "turn_truth"),
    ("propositions", "propositions"),
    ("goals", "goals"),
    # B.19 (AMASTERv2 §39): WitnessKnowledge ist die epistemische
    # Zugriffsschicht — kein zweiter Fact-Store, sondern (character × fact × access)
    # mit Foreign-Key-Beziehung. Wird deshalb als eigene Tabelle geführt,
    # nicht als JSON-Array in sessions.json.
    ("witnessKnowledge", "witness_knowledge"),
)

# Object-ID compare keys (MIGRATE classes + session children + singletons).
ID_COMPARE_KEYS = (
    "users",
    "worlds",
    "characters",
    "sessions",
    "uploads",
    "reviews",
    "snapshots",
    "triggers",
    "logs",
    "preferences",
    "facts",
    "memories",
    "relations",
    "godFacts",
    "turns",
    "turnTruths",
    "propositions",
    "goals",
    "witnessKnowledge",
    "config",
    "activeUserId",
)

# Map idCompare class name → SQL table with an `id` column.
CLASS_ID_TABLE = {
    "users": "users",
    "worlds": "worlds",
    "characters": "characters",
    "sessions": "sessions",
    "uploads": "uploads",
    "reviews": "reviews",
    "snapshots": "snapshots",
    "triggers": "triggers",
    "logs": "logs",
    "preferences": "preferences",
    "facts": "scene_facts",
    "memories": "memories",
    "relations": "relationships",
    "godFacts": "god_facts",
    "turns": "turns",
    "turnTruths": "turn_truth",
    "propositions": "propositions",
    "goals": "goals",
    "witnessKnowledge": "witness_knowledge",
}

CHILD_COLLECTION_KEYS = (
    "facts",
    "memories",
    "godFacts",
    "turns",
    "turnTruths",
    "propositions",
    "goals",
    "relations",
)

SESSION_CHILD_TABLES = (
    # V67 (Audit7 V66-02; AMASTER §39 Wissen nur aus Wahrnehmung, §68 Nr. 6/7): the witness rows are children of the session
    # like the facts they name - a full reset or a restore that clears the facts clears them too (V66 kept them, each then
    # naming a fact that was gone: WITNESS_FACT_INVALID)
    "witness_knowledge",
    "scene_facts",
    "memories",
    "relationships",
    "propositions",
    "goals",
    "god_facts",
    "turns",
    "turn_truth",
    "appointments",
    "graph_edges",
)

# V2: PUT/PATCH /api/sessions is a UI-settings writer only. Kernel-owned
# runtime/scene/turn state must never be accepted from a browser/session blob.
# Session creation remains a separate ingress because it establishes the
# initial session; subsequent canonical state changes use dedicated writers.
ENVELOPE_FIELDS = (
    "name",
    "avatarId",
    "alias",
    "role",
    "pipeline",
    "autoChat",
    "focus",
    # V92 Paket 14 (Paket-13-Pruefung, Entscheidung 4; AMASTER §27.2 "wird ausdruecklich gebunden"): the speaker binding the
    # user chose in "Spreche als" (avatar | operator | observer | regie | gott | char:<figure id>) - read back after a reload
    "speakAs",
)
SPEAK_AS_MODES = ("avatar", "operator", "observer", "regie", "gott")

# Internal server/kernel envelope fields. This is deliberately separate from
# ENVELOPE_FIELDS so save_session can persist canonical kernel output without
# reopening those fields to PUT/PATCH callers.
CANONICAL_ENVELOPE_FIELDS = (
    "name",
    "avatarId",
    "alias",
    "role",
    "scene",
    "runtimes",
    "fate",
    "pipeline",
    "autoChat",
    "focus",
    "speakAs",   # V92 Paket 14: the stored speaker binding (UI setting, validated by put_session)
    "turnIndex",
    "createdAt",
    "updatedAt",
    # V65S (AMASTER §63 Z. 3234, §68 Nr. 24; B.19 "nicht als JSON-Array in sessions.json"; Pruefung v3.1 §4): witnessKnowledge
    # is owned by its SQL table (SQL_OWNED_SESSION_COLLECTIONS, every read hydrates it from there); no envelope copy.
    "currentState",
    "time",
    "directorActions",
    "frames",
    "claims",
    "sceneState",
    "pendingInputTurnId",  # V54 canonical two-phase turn, never a client-owned field
    "pendingInputAttempt",  # V65T: orchestration status of the open input's formulation (mark_pending_attempt)
    # V61: kernel-validated condition kinds of authored reaction rules per
    # figure (session-derived, hash of the rule set; never written to the stem).
    "ruleKinds",
)

TABLE_ALLOW = frozenset(
    {
        "users",
        "worlds",
        "characters",
        "sessions",
        "scene_facts",
        "memories",
        "relationships",
        "propositions",
        "goals",
        "god_facts",
        "turns",
        "uploads",
        "reviews",
        "snapshots",
        "triggers",
        "logs",
        "preferences",
        "config",
        "meta",
        "documents",
        "appointments",
        "graph_edges",
        "turn_truth",
        "app_config",
        "witness_knowledge",
    }
)



class ImportAborted(Exception):
    def __init__(self, message: str, status: int = 400, error: str = "IMPORT_FAILED"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.error = error


class WriterError(Exception):
    def __init__(self, message: str, status: int = 400, error: str = "BAD_REQUEST", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.error = error
        # V92 Paket 16: structured content of a rejection the UI acts on (e.g. the identity clarification), never stored
        self.details = details


class IsolationError(PermissionError):
    pass


class SnapshotForbidden(PermissionError):
    """PUT /api/mcc is not a live persist writer. Historical replace-all lives in put_mcc_legacy."""

    code = "SNAPSHOT_OWNER_FORBIDDEN"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _loads(raw: str | None) -> Any:
    if raw is None:
        return None
    return json.loads(raw)


def _json_equal(a: Any, b: Any) -> bool:
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except (TypeError, ValueError):
            pass
    if isinstance(b, str):
        try:
            b = json.loads(b)
        except (TypeError, ValueError):
            pass
    return a == b


def unwrap_mcc(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ImportAborted("MCC payload must be a JSON object", 400)
    blob = payload.get("blob")
    if isinstance(blob, dict) and (
        any(k in blob for k in MIGRATE_CLASSES)
        or any(k in blob for k in ("users", "worlds", "sessions", "uploads"))
    ):
        return blob
    inner = payload.get("state")
    if isinstance(inner, dict) and (
        any(k in inner for k in MIGRATE_CLASSES)
        or any(k in inner for k in ("users", "worlds", "sessions", "uploads"))
    ):
        return inner
    return payload


def _require_list(mcc: dict[str, Any], key: str) -> list[Any]:
    if key not in mcc or mcc[key] is None:
        return []
    val = mcc[key]
    if not isinstance(val, list):
        raise ImportAborted(f"{key} must be a list", 400)
    return val


def _require_id(obj: Any, kind: str) -> str:
    if not isinstance(obj, dict):
        raise ImportAborted(f"{kind} entry must be an object", 400)
    oid = obj.get("id")
    if oid is None or str(oid).strip() == "":
        raise ImportAborted(f"{kind} missing required field id", 400)
    return str(oid)


def _owner_of_world(obj: dict[str, Any]) -> str:
    owner = obj.get("ownerUserId") or obj.get("owner_user_id")
    if owner is None or str(owner).strip() == "":
        raise ImportAborted(f"world {obj.get('id')!r} missing required field ownerUserId", 400)
    return str(owner)


def count_table(conn: sqlite3.Connection, table: str) -> int:
    if table not in TABLE_ALLOW:
        raise ValueError(f"refusing count on {table}")
    row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
    return int(row[0] if row else 0)


def _list_ids(conn: sqlite3.Connection, table: str) -> list[str]:
    if table not in TABLE_ALLOW:
        raise ValueError(f"refusing id list on {table}")
    rows = conn.execute(f"SELECT id FROM {table}").fetchall()
    return [str(r[0]) for r in rows if r[0] is not None]


def _add_id(bucket: dict[str, list[str]], klass: str, id_: str) -> None:
    lst = bucket.setdefault(klass, [])
    sid = str(id_)
    if sid not in lst:
        lst.append(sid)


def _uniq_sorted(ids: list[str]) -> list[str]:
    return sorted(dict.fromkeys(ids))


def _relation_row_id(session_id: str, rel: dict[str, Any]) -> str | None:
    """Stable relationship row id: explicit id, else sessionId:fromId:toId."""
    rid = rel.get("id")
    if rid is not None and str(rid).strip() != "":
        return str(rid)
    from_id = rel.get("fromId") or rel.get("from_id")
    to_id = rel.get("toId") or rel.get("to_id")
    if not from_id or not to_id:
        return None
    return f"{session_id}:{from_id}:{to_id}"


def _session_child_ids(session: dict[str, Any], session_id: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for field, _table in CHILD_FIELDS:
        items = session.get(field) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                cid = item.get("id")
                if cid is not None and str(cid).strip() != "":
                    _add_id(out, field, str(cid))
    rels = session.get(REL_FIELD) or []
    if isinstance(rels, list):
        for rel in rels:
            if not isinstance(rel, dict):
                continue
            rid = _relation_row_id(session_id, rel)
            if rid:
                _add_id(out, "relations", rid)
    return out


def _merge_skip_children(
    skipped: dict[str, list[str]], session: dict[str, Any], session_id: str
) -> None:
    for klass, ids in _session_child_ids(session, session_id).items():
        for cid in ids:
            _add_id(skipped, klass, cid)


def _select_json(conn: sqlite3.Connection, table: str, id_: str) -> str | None:
    if table not in TABLE_ALLOW:
        raise ValueError(table)
    own = _scope_own(table)
    if own is not None and id_ in own:
        return own[id_]   # V65T: read once per save (this session's rows of this table)
    row = conn.execute(f"SELECT json FROM {table} WHERE id=?", (id_,)).fetchone()
    return None if row is None else row[0]


def _insert_keep(
    conn: sqlite3.Connection,
    table: str,
    id_: str,
    payload: dict[str, Any],
    columns: dict[str, Any],
    warnings: list[str],
) -> str:
    """INSERT; same id+payload → idempotent; same id+other payload → keep existing + warning."""
    if table not in TABLE_ALLOW:
        raise ValueError(table)
    existing = _select_json(conn, table, id_)
    # V72: the legacy MCC importer also uses this INSERT-only path. For a
    # session child it has COPY semantics, not live event creation. Keep a
    # proven incoming position, never make up one, and reject collisions with
    # already stored rows (including rows of other child tables).
    if existing is None and table in _SEQ_TABLES and columns.get("session_id"):
        _check_position_for_legacy_copy(conn, table, str(columns["session_id"]), id_, payload)
    dumped = _dumps(payload)
    if existing is not None:
        if _json_equal(existing, payload):
            return "idempotent"
        warnings.append(f"{table} id={id_}: existing row kept (payload differs)")
        return "kept"
    cols = ["id", "json"]
    vals: list[Any] = [id_, dumped]
    for k, v in columns.items():
        if k in ("id", "json"):
            continue
        cols.append(k)
        vals.append(v)
    placeholders = ",".join("?" for _ in cols)
    conn.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", vals)
    return "inserted"


def _canon(obj: dict[str, Any], *, user_id: str | None = None, world_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    out = dict(obj)
    if user_id is not None:
        out["userId"] = user_id
        out.pop("user_id", None)
    if world_id is not None:
        out["worldId"] = world_id
        out.pop("world_id", None)
    if session_id is not None:
        out["sessionId"] = session_id
        out.pop("session_id", None)
    return out


def _overlay_sql_identity(
    obj: Any,
    *,
    user_id: Any,
    world_id: Any,
    session_id: Any,
) -> dict[str, Any]:
    """B1R2.5 reader overlay: SQL columns are the only allowed child identity.

    fromId/toId are left untouched (relationship endpoints are not scope fields).
    """
    out = dict(obj) if isinstance(obj, dict) else {}
    out["userId"] = user_id
    out["worldId"] = world_id
    out["sessionId"] = session_id
    out.pop("user_id", None)
    out.pop("world_id", None)
    out.pop("session_id", None)
    return out


def _world_owner_map(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT id, owner_user_id FROM worlds").fetchall()
    return {r[0]: r[1] for r in rows}


def _session_user_map(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT id, user_id FROM sessions").fetchall()
    return {r[0]: r[1] for r in rows}


def _char_world_map(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT id, world_id FROM characters").fetchall()
    return {r[0]: r[1] for r in rows}


def session_world_allowed(world_id: str, world_owner: str, session_user: str) -> bool:
    if is_shared_gasthaus(world_id, world_owner):
        return True
    return world_owner == session_user


def world_bindable(conn: sqlite3.Connection, actor_id: str, world_id: str) -> bool:
    """Session-Owner → World-Owner → User-Scope."""
    if not world_id or not actor_id:
        return False
    row = conn.execute("SELECT owner_user_id FROM worlds WHERE id = ?", (world_id,)).fetchone()
    if not row:
        return False
    owner = row["owner_user_id"]
    if owner == actor_id:
        return True
    if world_id == GASTHAUS_ID and owner == "admin":
        return True
    return False


def assert_world_bindable(conn: sqlite3.Connection, actor_id: str, world_id: str) -> None:
    if not world_id:
        raise IsolationError("session world missing")
    row = conn.execute("SELECT owner_user_id FROM worlds WHERE id = ?", (world_id,)).fetchone()
    if not row:
        raise IsolationError("session world not found")
    owner = row["owner_user_id"]
    if owner == actor_id:
        return
    if world_id == GASTHAUS_ID and owner == "admin":
        return
    raise IsolationError("cannot bind session to foreign world")



def _skip_foreign(warnings: list[str], table: str, id_: str, reason: str) -> None:
    warnings.append(f"{table} id={id_}: skipped ({reason})")


def _record_skip(
    warnings: list[str],
    skipped: dict[str, list[str]],
    klass: str,
    id_: str,
    reason: str,
    table: str | None = None,
) -> None:
    _skip_foreign(warnings, table or klass, id_, reason)
    _add_id(skipped, klass, id_)


def _proven_remap_from_ids(
    remapped: list[Any],
    target_ids: dict[str, list[str]],
) -> dict[str, set[str]]:
    """Source IDs with a remap mapping whose target ID is actually in SQL."""
    proven: dict[str, set[str]] = {}
    for entry in remapped or []:
        if not isinstance(entry, dict):
            continue
        klass = entry.get("class") or entry.get("klass")
        frm = entry.get("from") or entry.get("fromId") or entry.get("sourceId")
        to = entry.get("to") or entry.get("toId") or entry.get("targetId")
        if not klass or frm is None or to is None:
            continue
        tgt = {str(x) for x in (target_ids.get(str(klass)) or [])}
        if str(to) in tgt:
            proven.setdefault(str(klass), set()).add(str(frm))
    return proven


def _build_id_compare(
    source_ids: dict[str, list[str]],
    target_ids: dict[str, list[str]],
    skipped: dict[str, list[str]],
    remapped: list[Any] | None = None,
) -> dict[str, Any]:
    """Compare source vs target object IDs.

    missing = source - target - skipped - proven-remaps
        Unexpected gaps. Nonempty → ImportAborted (rollback). Skipped foreign
        IDs are NOT missing, so a non-admin import of A+B does not roll back A.

    unresolved / notMigrated = source - target - proven-remaps
        Source IDs not in SQLite, EVEN IF skipped. Skipped is diagnosis, not
        a successful migration.

    skippedBlocking = skipped ∩ unresolved
        Foreign/skipped IDs that never landed in the master.

    preserved and cutoverComplete are false when unresolved is nonempty.
    Counts matching is not a substitute for ID completeness.
    """
    remapped_list = list(remapped or [])
    proven_from = _proven_remap_from_ids(remapped_list, target_ids)
    missing: dict[str, list[str]] = {}
    unresolved: dict[str, list[str]] = {}
    skipped_blocking: dict[str, list[str]] = {}
    keys = set(source_ids) | set(target_ids) | set(skipped)
    for klass in keys:
        src = set(source_ids.get(klass) or [])
        tgt = set(target_ids.get(klass) or [])
        skp = set(skipped.get(klass) or [])
        proven = proven_from.get(klass) or set()
        miss = sorted(src - tgt - skp - proven)
        if miss:
            missing[klass] = miss
        unres = sorted(src - tgt - proven)
        if unres:
            unresolved[klass] = unres
        block = sorted((skp & src) - tgt - proven)
        if block:
            skipped_blocking[klass] = block
    source_out = {k: _uniq_sorted(source_ids.get(k) or []) for k in ID_COMPARE_KEYS}
    target_out = {k: _uniq_sorted(target_ids.get(k) or []) for k in ID_COMPARE_KEYS}
    skipped_out = {k: _uniq_sorted(v) for k, v in skipped.items() if v}
    not_migrated = {k: list(v) for k, v in unresolved.items()}
    unresolved_nonempty = bool(unresolved)
    preserved = not unresolved_nonempty
    cutover_complete = (not unresolved_nonempty) and (not missing)
    if skipped_blocking:
        status = "SKIPPED_BLOCKING"
    elif cutover_complete:
        status = "COMPLETE"
    else:
        status = "INCOMPLETE"
    return {
        "sourceIds": source_out,
        "targetIds": target_out,
        "missing": missing,
        "skipped": skipped_out,
        "unresolved": unresolved,
        "skippedBlocking": skipped_blocking,
        "notMigrated": not_migrated,
        "remapped": remapped_list,
        "preserved": preserved,
        "cutoverComplete": cutover_complete,
        "cutoverStatus": status,
    }


def _non_admin_import(actor: str) -> bool:
    return actor != "admin"


def _import_children(
    conn: sqlite3.Connection,
    session_id: str,
    user_id: str,
    world_id: str,
    session: dict[str, Any],
    warnings: list[str],
    source_child_counts: dict[str, int],
) -> None:
    # The current session-import route already checks these before writing.
    # The older, still UI-accessible MCC route must not bypass that contract.
    try:
        _check_copied_positions(session)
    except WriterError as exc:
        raise ImportAborted(str(exc), exc.status, exc.error) from exc
    for field, table in CHILD_FIELDS:
        items = session.get(field) or []
        if items is None:
            items = []
        if not isinstance(items, list):
            raise ImportAborted(f"session {session_id} {field} must be a list", 400)
        source_child_counts[field] = source_child_counts.get(field, 0) + len(items)
        for item in items:
            cid = _require_id(item, f"session.{field}")
            payload = _canon(item, user_id=user_id, world_id=world_id, session_id=session_id)
            _insert_keep(
                conn,
                table,
                cid,
                payload,
                {"user_id": user_id, "world_id": world_id, "session_id": session_id},
                warnings,
            )

    rels = session.get(REL_FIELD) or []
    if rels is None:
        rels = []
    if not isinstance(rels, list):
        raise ImportAborted(f"session {session_id} relations must be a list", 400)
    source_child_counts["relations"] = source_child_counts.get("relations", 0) + len(rels)
    for rel in rels:
        if not isinstance(rel, dict):
            raise ImportAborted(f"session {session_id} relation must be an object", 400)
        from_id = rel.get("fromId") or rel.get("from_id")
        to_id = rel.get("toId") or rel.get("to_id")
        if not from_id or not to_id:
            raise ImportAborted(f"session {session_id} relation missing fromId/toId", 400)
        from_id = str(from_id)
        to_id = str(to_id)
        rid = _relation_row_id(session_id, rel) or f"{session_id}:{from_id}:{to_id}"
        payload = _canon(rel, user_id=user_id, world_id=world_id, session_id=session_id)
        payload["fromId"] = from_id
        payload["toId"] = to_id
        if "id" not in payload:
            payload["id"] = rid
        _insert_keep(
            conn,
            REL_TABLE,
            rid,
            payload,
            {
                "user_id": user_id,
                "world_id": world_id,
                "session_id": session_id,
                "from_id": from_id,
                "to_id": to_id,
            },
            warnings,
        )


def import_mcc(
    conn: sqlite3.Connection,
    payload: Any,
    actor: str | None = None,
    as_testfixture: bool = False,
    actor_id: str = "",
) -> dict[str, Any]:
    """Transactional import of ALL MIGRATE classes. Raises ImportAborted on failure.

    Caller must BEGIN; this function does not commit. On exception the caller rolls back.

    actor!=admin: filter to actor-owned records (skip+warning). Foreign users are
    neither created nor overwritten. Gasthaus stammobjekt (id+owner=admin) may be
    imported as shared seed; actor must not re-own it.

    as_testfixture=True → actor admin, report source=TESTFIXTURE.
    """
    if as_testfixture:
        actor = "admin"
    elif not actor:
        actor = actor_id or "admin"
    actor = str(actor)
    mcc = unwrap_mcc(payload)
    warnings: list[str] = []
    source_counts: dict[str, Any] = {}
    classes: dict[str, Any] = {}
    source_child_counts: dict[str, int] = {}
    source_ids: dict[str, list[str]] = {k: [] for k in ID_COMPARE_KEYS}
    skipped_ids: dict[str, list[str]] = {k: [] for k in ID_COMPARE_KEYS}

    users = _require_list(mcc, "users")
    worlds = _require_list(mcc, "worlds")
    characters = _require_list(mcc, "characters")
    sessions = _require_list(mcc, "sessions")
    uploads = _require_list(mcc, "uploads")
    reviews = _require_list(mcc, "reviews")
    snapshots = _require_list(mcc, "snapshots")
    triggers = _require_list(mcc, "triggers")
    logs = _require_list(mcc, "logs")
    preferences = _require_list(mcc, "preferences")

    source_counts["users"] = len(users)
    source_counts["worlds"] = len(worlds)
    source_counts["characters"] = len(characters)
    source_counts["sessions"] = len(sessions)
    source_counts["uploads"] = len(uploads)
    source_counts["reviews"] = len(reviews)
    source_counts["snapshots"] = len(snapshots)
    source_counts["triggers"] = len(triggers)
    source_counts["logs"] = len(logs)
    source_counts["preferences"] = len(preferences)

    active = mcc.get("activeUserId")
    if active is None or active == "":
        source_counts["activeUserId"] = 0
        active_s = None
    else:
        if not isinstance(active, str):
            raise ImportAborted("activeUserId must be a string", 400)
        source_counts["activeUserId"] = 1
        active_s = active

    cfg = mcc.get("config")
    if cfg is None:
        source_counts["config"] = 0
        cfg_obj = None
    elif not isinstance(cfg, dict):
        raise ImportAborted("config must be an object", 400)
    else:
        source_counts["config"] = 0 if cfg == {} else 1
        cfg_obj = cfg

    for nk, note in NICHTKANONISCH_CLASSES.items():
        present = 1 if nk in mcc and mcc[nk] is not None else 0
        classes[nk] = {
            "source": present,
            "target": 0,
            "action": "NICHTKANONISCH",
            "notes": note,
        }

    # --- users ---
    for u in users:
        uid = _require_id(u, "user")
        _add_id(source_ids, "users", uid)
        if _non_admin_import(actor) and uid != actor:
            _record_skip(warnings, skipped_ids, "users", uid, "foreign user; actor is not admin")
            continue
        created = u.get("createdAt") or u.get("created_at") or _now()
        payload_u = dict(u)
        payload_u["id"] = uid
        _insert_keep(conn, "users", uid, payload_u, {"created_at": created}, warnings)

    # --- worlds ---
    for w in worlds:
        wid = _require_id(w, "world")
        _add_id(source_ids, "worlds", wid)
        owner = _owner_of_world(w)
        if _non_admin_import(actor) and owner != actor and not is_shared_gasthaus(wid, owner):
            _record_skip(warnings, skipped_ids, "worlds", wid, f"foreign world owner={owner}")
            continue
        payload_w = dict(w)
        payload_w["id"] = wid
        # Gasthaus stammobjekt stays owner=admin; actor must not re-own it.
        if is_shared_gasthaus(wid, owner):
            payload_w["ownerUserId"] = "admin"
            _insert_keep(conn, "worlds", wid, payload_w, {"owner_user_id": "admin"}, warnings)
            continue
        payload_w["ownerUserId"] = owner
        _insert_keep(conn, "worlds", wid, payload_w, {"owner_user_id": owner}, warnings)

    # V81: importing an unrelated world must never resurrect a deleted Gasthaus.
    owners = _world_owner_map(conn)

    # --- characters ---
    for c in characters:
        cid = _require_id(c, "character")
        _add_id(source_ids, "characters", cid)
        world_id = c.get("worldId") or c.get("world_id")
        if not world_id:
            raise ImportAborted(f"character {cid} missing required field worldId", 400)
        world_id = str(world_id)
        owner = owners.get(world_id)
        if owner is None:
            if _non_admin_import(actor):
                _record_skip(warnings, skipped_ids, "characters", cid, f"world {world_id} not found")
                continue
            raise ImportAborted(f"character {cid} world {world_id} not found", 400)
        if _non_admin_import(actor) and owner != actor:
            _record_skip(warnings, skipped_ids, "characters", cid, f"world owner={owner}")
            continue
        payload_c = _canon(c, world_id=world_id)
        payload_c["id"] = cid
        _insert_keep(
            conn,
            "characters",
            cid,
            payload_c,
            {"world_id": world_id, "owner_user_id": owner},
            warnings,
        )

    # --- sessions + children ---
    _restored_sids: list[str] = []   # V65Z: sessions restored from the backup (write-boundary audit below)
    for s in sessions:
        sid = _require_id(s, "session")
        _add_id(source_ids, "sessions", sid)
        for klass, cids in _session_child_ids(s, sid).items():
            for cid in cids:
                _add_id(source_ids, klass, cid)
        user_id = s.get("userId") or s.get("user_id")
        world_id = s.get("worldId") or s.get("world_id")
        if not user_id:
            raise ImportAborted(f"session {sid} missing required field userId", 400)
        if not world_id:
            raise ImportAborted(f"session {sid} missing required field worldId", 400)
        user_id = str(user_id)
        world_id = str(world_id)
        if _non_admin_import(actor) and user_id != actor:
            _record_skip(warnings, skipped_ids, "sessions", sid, f"userId={user_id} != actor")
            _merge_skip_children(skipped_ids, s, sid)
            continue
        owner = owners.get(world_id)
        if owner is None:
            if _non_admin_import(actor):
                _record_skip(warnings, skipped_ids, "sessions", sid, f"world {world_id} not found")
                _merge_skip_children(skipped_ids, s, sid)
                continue
            raise ImportAborted(f"session {sid} world {world_id} not found", 400)
        if not session_world_allowed(world_id, owner, user_id):
            if _non_admin_import(actor):
                _record_skip(
                    warnings,
                    skipped_ids,
                    "sessions",
                    sid,
                    f"cannot bind session to foreign world {world_id}",
                )
                _merge_skip_children(skipped_ids, s, sid)
                continue
            raise ImportAborted(
                f"session {sid} must not bind foreign world {world_id} (owner={owner}, userId={user_id})",
                409,
                "SESSION_WORLD_OWNER_MISMATCH",
            )
        envelope = _canon(s, user_id=user_id, world_id=world_id)
        envelope["id"] = sid
        keep = _insert_keep(
            conn,
            "sessions",
            sid,
            envelope,
            {"user_id": user_id, "world_id": world_id},
            warnings,
        )
        if keep == "kept" and (actor == "admin" or user_id == actor):
            try:
                put_session(conn, sid, envelope, user_id)
            except (WriterError, IsolationError):
                pass
        _import_children(conn, sid, user_id, world_id, s, warnings, source_child_counts)
        _restored_sids.append(sid)

    owners = _world_owner_map(conn)
    sess_users = _session_user_map(conn)
    char_worlds = _char_world_map(conn)

    def _derive_user_from_session(session_id: str | None) -> str | None:
        if session_id and session_id in sess_users:
            return sess_users[session_id]
        return None

    def _derive_user_from_world(world_id: str | None) -> str | None:
        if world_id and world_id in owners:
            return owners[world_id]
        return None

    # --- uploads ---
    for u in uploads:
        uid = _require_id(u, "upload")
        _add_id(source_ids, "uploads", uid)
        user_id = str(u.get("userId") or u.get("user_id") or actor)
        if _non_admin_import(actor) and user_id != actor:
            _record_skip(warnings, skipped_ids, "uploads", uid, f"userId={user_id} != actor")
            continue
        payload_u = _canon(u, user_id=user_id)
        payload_u["id"] = uid
        _insert_keep(conn, "uploads", uid, payload_u, {"user_id": user_id}, warnings)

    # --- reviews ---
    for r in reviews:
        rid = _require_id(r, "review")
        _add_id(source_ids, "reviews", rid)
        sess_id = r.get("sourceSessionId") or r.get("sessionId")
        world_id = r.get("worldId") or r.get("world_id")
        user_id = r.get("userId") or r.get("user_id")
        user_id = str(
            user_id
            or _derive_user_from_session(str(sess_id) if sess_id else None)
            or _derive_user_from_world(str(world_id) if world_id else None)
            or actor
        )
        if _non_admin_import(actor) and user_id != actor:
            _record_skip(warnings, skipped_ids, "reviews", rid, f"userId={user_id} != actor")
            continue
        payload_r = _canon(r, user_id=user_id)
        payload_r["id"] = rid
        _insert_keep(conn, "reviews", rid, payload_r, {"user_id": user_id}, warnings)

    # --- snapshots ---
    for sn in snapshots:
        nid = _require_id(sn, "snapshot")
        _add_id(source_ids, "snapshots", nid)
        sess_id = sn.get("sessionId") or sn.get("session_id")
        nested = sn.get("session") if isinstance(sn.get("session"), dict) else {}
        if not sess_id and nested:
            sess_id = nested.get("id")
        sess_id_s = str(sess_id) if sess_id else None
        user_id = sn.get("userId") or sn.get("user_id") or (nested.get("userId") if nested else None)
        user_id = str(user_id or _derive_user_from_session(sess_id_s) or actor)
        if _non_admin_import(actor) and user_id != actor:
            _record_skip(warnings, skipped_ids, "snapshots", nid, f"userId={user_id} != actor")
            continue
        payload_sn = dict(sn)
        # V66 (Audit6 N05): a snapshot that comes in with a file is no capture of THIS server - archive only (kept, listed),
        # never a restore source; its stamp is not taken from the file
        payload_sn.pop(SNAPSHOT_STAMP, None)
        payload_sn["id"] = nid
        if sess_id_s:
            payload_sn["sessionId"] = sess_id_s
        payload_sn["userId"] = user_id
        _insert_keep(
            conn,
            "snapshots",
            nid,
            payload_sn,
            {"user_id": user_id, "session_id": sess_id_s},
            warnings,
        )

    # --- triggers ---
    for t in triggers:
        tid = _require_id(t, "trigger")
        _add_id(source_ids, "triggers", tid)
        sess_id = t.get("sessionId") or t.get("session_id")
        world_id = t.get("worldId") or t.get("world_id")
        user_id = t.get("userId") or t.get("user_id")
        user_id = str(
            user_id
            or _derive_user_from_session(str(sess_id) if sess_id else None)
            or _derive_user_from_world(str(world_id) if world_id else None)
            or actor
        )
        if _non_admin_import(actor) and user_id != actor:
            _record_skip(warnings, skipped_ids, "triggers", tid, f"userId={user_id} != actor")
            continue
        payload_t = _canon(t, user_id=user_id)
        payload_t["id"] = tid
        _insert_keep(conn, "triggers", tid, payload_t, {"user_id": user_id}, warnings)

    # --- logs ---
    for lg in logs:
        lid = _require_id(lg, "log")
        _add_id(source_ids, "logs", lid)
        sess_id = lg.get("sessionId") or lg.get("session_id")
        user_id = lg.get("userId") or lg.get("user_id")
        user_id = str(user_id or _derive_user_from_session(str(sess_id) if sess_id else None) or actor)
        if _non_admin_import(actor) and user_id != actor:
            _record_skip(warnings, skipped_ids, "logs", lid, f"userId={user_id} != actor")
            continue
        payload_l = _canon(lg, user_id=user_id)
        payload_l["id"] = lid
        # never copy secrets into a derived log line
        _insert_keep(conn, "logs", lid, payload_l, {"user_id": user_id}, warnings)

    # --- preferences ---
    for p in preferences:
        pid = _require_id(p, "preference")
        _add_id(source_ids, "preferences", pid)
        user_id = p.get("userId") or p.get("user_id")
        char_id = p.get("characterId") or p.get("character_id")
        if not user_id and char_id and char_id in char_worlds:
            user_id = owners.get(char_worlds[str(char_id)])
        user_id = str(user_id or actor)
        if _non_admin_import(actor) and user_id != actor:
            _record_skip(warnings, skipped_ids, "preferences", pid, f"userId={user_id} != actor")
            continue
        payload_p = _canon(p, user_id=user_id)
        payload_p["id"] = pid
        _insert_keep(conn, "preferences", pid, payload_p, {"user_id": user_id}, warnings)

    # --- config (user-scope; do not print apiKey) ---
    if cfg_obj is not None and cfg_obj != {}:
        _add_id(source_ids, "config", "config")
        scope = "user"
        if _non_admin_import(actor):
            if active_s and active_s != actor:
                _skip_foreign(warnings, "config", str(active_s), "foreign activeUserId; scoped to actor")
            scope_id = actor
        else:
            scope_id = active_s or actor
        existing = conn.execute(
            "SELECT json FROM config WHERE scope=? AND scope_id=?", (scope, scope_id)
        ).fetchone()
        dumped = _dumps(cfg_obj)
        if existing is None:
            conn.execute(
                "INSERT INTO config (scope, scope_id, json) VALUES (?,?,?)",
                (scope, scope_id, dumped),
            )
        elif not _json_equal(existing[0], cfg_obj):
            warnings.append(f"config scope={scope}/{scope_id}: existing row kept (payload differs)")

    if active_s:
        _add_id(source_ids, "activeUserId", "activeUserId")
        if _non_admin_import(actor) and active_s != actor:
            _record_skip(
                warnings,
                skipped_ids,
                "activeUserId",
                "activeUserId",
                f"foreign value {active_s}",
                table="meta",
            )
        else:
            existing_meta = conn.execute("SELECT value FROM meta WHERE key=?", ("activeUserId",)).fetchone()
            if existing_meta is None:
                conn.execute("INSERT INTO meta (key, value) VALUES (?,?)", ("activeUserId", active_s))
            elif existing_meta[0] != active_s:
                warnings.append("meta activeUserId: existing value kept (payload differs)")


    source_counts.update({k: source_child_counts.get(k, 0) for k in ("facts", "memories", "relations", "godFacts", "turns", "propositions", "goals")})

    target_counts: dict[str, Any] = {
        "users": count_table(conn, "users"),
        "worlds": count_table(conn, "worlds"),
        "characters": count_table(conn, "characters"),
        "sessions": count_table(conn, "sessions"),
        "uploads": count_table(conn, "uploads"),
        "reviews": count_table(conn, "reviews"),
        "snapshots": count_table(conn, "snapshots"),
        "triggers": count_table(conn, "triggers"),
        "logs": count_table(conn, "logs"),
        "preferences": count_table(conn, "preferences"),
        "facts": count_table(conn, "scene_facts"),
        "memories": count_table(conn, "memories"),
        "relations": count_table(conn, "relationships"),
        "godFacts": count_table(conn, "god_facts"),
        "turns": count_table(conn, "turns"),
        "propositions": count_table(conn, "propositions"),
        "goals": count_table(conn, "goals"),
    }
    cfg_n = count_table(conn, "config")
    target_counts["config"] = cfg_n if cfg_n else 0
    meta_active = conn.execute("SELECT value FROM meta WHERE key=?", ("activeUserId",)).fetchone()
    target_counts["activeUserId"] = 1 if meta_active and meta_active[0] else 0

    for name in MIGRATE_CLASSES:
        src = int(source_counts.get(name) or 0)
        tgt = int(target_counts.get(name) or 0)
        classes[name] = {
            "source": src,
            "target": tgt,
            "action": "MIGRATE",
            "notes": "IDs preserved; SQL columns canonical",
        }

    target_ids: dict[str, list[str]] = {k: [] for k in ID_COMPARE_KEYS}
    for klass, table in CLASS_ID_TABLE.items():
        target_ids[klass] = _list_ids(conn, table)
    target_ids["config"] = ["config"] if cfg_n else []
    target_ids["activeUserId"] = ["activeUserId"] if meta_active and meta_active[0] else []

    id_compare = _build_id_compare(source_ids, target_ids, skipped_ids)
    if id_compare["missing"]:
        raise ImportAborted(
            f"source IDs missing from target: {id_compare['missing']}",
            409,
            "ID_COMPARE_FAILED",
        )

    # V65Z (SPS-Audit V65Y §3 "Andere Wege umgehen sie weiterhin"): the MCC restore writes the STORED rows of an own backup
    # as they were (§34.3 historical evidence is not silently dropped; a refused restore would lose the backup). It is the one
    # path that does not refuse a row outside the write boundary - so every such row is counted here per session (the same
    # audit as the diagnosis), never silent.
    _restored = {}
    for _sid in dict.fromkeys(_restored_sids):
        _a = write_boundary_audit(conn, _sid)
        if _a.get("altzeilen"):
            _restored[_sid] = _a
    if _restored:
        warnings.append(f"LEGACY_ROWS_RESTORED:{sum(a['altzeilen'] for a in _restored.values())}")
    return {
        "ok": True,
        "schreibgrenze": _restored,
        "source": "TESTFIXTURE" if as_testfixture else "REAL",
        "sourceCounts": source_counts,
        "targetCounts": target_counts,
        "idCompare": id_compare,
        "classes": classes,
        "warnings": warnings,
    }


def _session_child_order_sql(table: str) -> str:
    """V1: fachliche Reader-Reihenfolge nur dort, wo sie definiert ist.

    Turns werden zuerst nach fachlichem ``turn`` und dann nach dem beim
    kanonischen Append persistierten ``turnOrder`` geladen. Fuer historische
    Turn-Payloads ohne dieses Feld ist die unveraenderliche SQLite-Einfuegefolge
    (``rowid``) der belastbare Legacy-Fallback; zufaellige IDs besitzen keine
    Chronologie. Andere Child-Tabellen behalten ihre bisherige ID-Reihenfolge.
    """
    if table == "turns":
        # V70 (Audit10 §4): the writer's event position `seq` first (rows since V70), then the per-turn position turnOrder
        return (
            "CAST(COALESCE(json_extract(json, '$.turn'), 0) AS INTEGER), "
            "json_type(json, '$.seq') IS NOT NULL, CAST(json_extract(json, '$.seq') AS INTEGER), "
            "CASE WHEN json_type(json, '$.turnOrder') IS NULL "
            "THEN rowid ELSE CAST(json_extract(json, '$.turnOrder') AS INTEGER) END, "
            "rowid"
        )
    return "id"


_CHILD_BASE = {"relations": "relationships"}


def _session_child_query(table: str, view: str, *, speicher: bool = False) -> str:
    """V69 (Audit9 P0-2 "ID-Reihenfolge ist keine Ereignisreihenfolge"; AMASTER §23, §34, §35 "Der aktuelle Zustand wird aus
    der neuesten gueltigen Evidenz reduziert"): the readers' order of a session's child rows is the event order - the turn,
    then the order the canonical writer stored them in. V68 and earlier read every child but `turns` by id: an id is a random
    identity, so rows of the same millisecond, an import and the next normal fact came out of order. Ids are identity only.
    V70 (Audit10 §4 "rowid ist eine technische Zeilenkennung, keine dauerhaft garantierte fachliche Ereignisnummer"; AMASTER §34
    Zeit/commit_group, §34.2): the position is the writer's persisted event position `seq` (stamped by _insert_new into the
    row itself, kept by import, duplicate, snapshot and restore). Rows without it (written before V70) come first in their
    turn, by their SQLite insertion order - that order is not proven (scene_state.order_unproven_turns) and decides no
    current state where it would matter (scene_state.lifecycle_order_conflicts). The read view still supplies the canonical
    SQL identity (json_set)."""
    if speicher:
        # V70 (Audit10 §4): a COPY of the stored state (snapshot capture, export) keeps the order the rows were written in (their
        # insertion sequence; the event positions travel inside the rows). The readers' turn order would hide a turn number a
        # later row reused, and a restore would then write that history as if it had been in order.
        base = _CHILD_BASE.get(table, table)
        if base not in TABLE_ALLOW:
            raise ValueError(base)
        if table == "turns":
            return "SELECT json, user_id, world_id, session_id FROM turns WHERE session_id=? ORDER BY rowid"
        return (f"SELECT v.json, v.user_id, v.world_id, v.session_id FROM {view} v JOIN {base} b ON b.id = v.id WHERE v.session_id=? "
                f"ORDER BY b.rowid")
    if table == "turns":
        return f"SELECT json, user_id, world_id, session_id FROM turns WHERE session_id=? ORDER BY {_session_child_order_sql(table)}"
    base = _CHILD_BASE.get(table, table)
    if base not in TABLE_ALLOW:
        raise ValueError(base)
    return (f"SELECT v.json, v.user_id, v.world_id, v.session_id FROM {view} v JOIN {base} b ON b.id = v.id "
            f"WHERE v.session_id=? ORDER BY CAST(COALESCE(json_extract(b.json, '$.turn'), 0) AS INTEGER), "
            f"json_type(b.json, '$.seq') IS NOT NULL, CAST(json_extract(b.json, '$.seq') AS INTEGER), b.rowid")


def _turn_append_order(conn: sqlite3.Connection, session_id: str, turn: int) -> int:
    """Naechste fachliche Position innerhalb eines Turnindex.

    ``turns`` ist append-only. Deshalb ist die Zahl bereits persistierter Zeilen
    desselben Turnindex genau die naechste Writer-Position. Sie wird in der
    Turn-Payload gespeichert und ueberlebt damit Save/GET/Reload.
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM turns WHERE session_id=? "
        "AND CAST(COALESCE(json_extract(json, '$.turn'), 0) AS INTEGER)=?",
        (session_id, int(turn)),
    ).fetchone()
    return int(row[0] if row is not None else 0)


def _load_session_children(conn: sqlite3.Connection, session_id: str) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    mapping = {
        "facts": "scene_facts",
        "memories": "memories",
        "godFacts": "god_facts",
        "turns": "turns",
        "turnTruths": "turn_truth",
        "propositions": "propositions",
        "goals": "goals",
        "relations": "relationships",
    }
    for field, table in mapping.items():
        # V1-Restnaht: turns brauchen fuer Legacy-Payloads ohne turnOrder den
        # append-only rowid-Fallback. _overlay_sql_identity() setzt danach
        # dieselbe kanonische SQL-Identitaet wie v_turns.
        view = table if table == "turns" else CHILD_READ_VIEW.get(table, table)
        if table not in TABLE_ALLOW:
            raise ValueError(table)
        if view not in VIEW_ALLOW and view not in TABLE_ALLOW:
            raise ValueError(view)
        rows = conn.execute(_session_child_query(table, view), (session_id,)).fetchall()   # V69: event order
        loaded: list[Any] = []
        for r in rows:
            loaded.append(
                _overlay_sql_identity(
                    _loads(r["json"]),
                    user_id=r["user_id"],
                    world_id=r["world_id"],
                    session_id=r["session_id"],
                )
            )
        out[field] = loaded
    return out


def rehydrate_session_row(conn: sqlite3.Connection, row: sqlite3.Row, *, wirksam: bool = True) -> dict[str, Any]:
    sess = _loads(row["json"]) if not isinstance(row["json"], dict) else dict(row["json"])
    if not isinstance(sess, dict):
        sess = {}
    sess["id"] = row["id"]
    sess["userId"] = row["user_id"]
    sess["worldId"] = row["world_id"]
    # V70: hydrate_session_from_sql loads every SQL-owned collection (a superset of _load_session_children) - one read
    return hydrate_session_from_sql(conn, sess, wirksam=wirksam)


def _load_children(conn: sqlite3.Connection, table: str, sid: str, *, speicher: bool = False) -> list:
    """SQL child rows for hydrate_session_from_sql. Reads go through views; writes stay on tables."""
    # V1-Restnaht: fuer turns wird die Basistabelle gelesen, damit historische
    # Payloads ohne turnOrder nach unveraenderlicher Einfuegefolge statt ID
    # geordnet werden koennen. SQL-Identitaet wird unten weiterhin ueberlagert.
    view = table if table == "turns" else CHILD_READ_VIEW.get(table, table)
    if table not in TABLE_ALLOW and table not in CHILD_READ_VIEW:
        raise ValueError(table)
    if view not in VIEW_ALLOW and view not in TABLE_ALLOW:
        raise ValueError(view)
    rows = conn.execute(_session_child_query(table, view, speicher=speicher), (sid,)).fetchall()   # V69: event order; V70: copies
    out = []
    for r in rows:
        out.append(
            _overlay_sql_identity(
                _loads(r["json"]),
                user_id=r["user_id"],
                world_id=r["world_id"],
                session_id=r["session_id"],
            )
        )
    return out


def hydrate_session_from_sql(conn: sqlite3.Connection, session_dict: dict, *, wirksam: bool = True) -> dict:
    """Overwrite SQL-owned arrays from _load_children. SQL wins if json disagrees.

    Mutates session_dict in place and returns it. Envelope keys stay in sessions.json.
    V70 (Audit10 §7 "eine gemeinsame Vertragsgrenze fuer jede gespeicherte Wirkung und jeden produktiven Reader"): the reader
    boundary. Every product reader - turn, prepare, puppet, Regie, God, AutoChat, upload, the session view - gets its session
    here, so the rows the write boundary refuses (`_boundary_rows`: no valid source, foreign scope, no validation, no role
    authority, no party, double commit, invalid position, or depending on such a row) are taken out of the effective lists.
    They stay stored and visible (`altbestand`, a read view, never persisted; AMASTER §34.3 "Historische Evidenz wird nicht
    heimlich geloescht", §6.2 Z. 262). `wirksam=False` reads every stored row (snapshot capture, export): a copy of the
    stored state, not a reader of evidence.
    """
    sid = session_dict.get("id") or ""
    for json_key, table in SQL_OWNED_SESSION_COLLECTIONS:
        session_dict[json_key] = _load_children(conn, table, sid, speicher=not wirksam) if sid else []
    if wirksam and sid:
        _apply_reader_boundary(conn, session_dict)
    else:
        session_dict.pop("altbestand", None)
    from matrix_api import kernel
    session_dict["goals"] = kernel.reduce_goal_state(session_dict)
    session_dict["currentState"] = kernel.reduce_current_state(session_dict)
    return session_dict


def _apply_reader_boundary(conn: sqlite3.Connection, session_dict: dict) -> None:
    """V70: take the rows outside the boundary out of the session's effective lists and attach the read view `altbestand`:
    the rows (table, id, code, turn), their highest turn (a new turn never reuses it), the stored turns whose order is not
    proven (two or more rows without an event position `seq`; for dialogue lines also without turnOrder) and the matters
    whose state that unproven order would decide (scene_state.lifecycle_order_conflicts). Read only (no row is changed)."""
    from matrix_api import scene_state as _sc
    sid = str(session_dict.get("id") or "")
    listed: dict[str, dict[str, str]] = {}
    for table, rid, code in _boundary_rows(conn, sid):
        if table != "sessions":
            listed.setdefault(table, {}).setdefault(str(rid), code)
    zeilen, hoechster = [], 0
    unbelegt: dict[str, list[int]] = {}
    for json_key, table in SQL_OWNED_SESSION_COLLECTIONS:
        q = listed.get(table) or {}
        keep = []
        for r in session_dict.get(json_key) or []:
            rid = str((r or {}).get("id") or "") if isinstance(r, dict) else ""
            if rid and rid in q:
                tn = r.get("turn")
                zeilen.append({"tabelle": table, "id": rid, "code": q[rid], "turn": tn})
                if isinstance(tn, int) and not isinstance(tn, bool):
                    hoechster = max(hoechster, tn)
                continue
            keep.append(r)
        session_dict[json_key] = keep
        counts: dict[int, int] = {}
        for r in keep:
            if not isinstance(r, dict) or r.get("seq") is not None or (json_key == "turns" and r.get("turnOrder") is not None):
                continue
            tn = r.get("turn")
            tn = tn if isinstance(tn, int) and not isinstance(tn, bool) else 0
            counts[tn] = counts.get(tn, 0) + 1
        turns = sorted(tn for tn, n in counts.items() if n >= 2)
        if turns:
            unbelegt[json_key] = turns
    session_dict["altbestand"] = {"anzahl": len(zeilen), "zeilen": zeilen, "hoechsterTurn": hoechster,
                                  "reihenfolgeUnbelegt": unbelegt, "mehrdeutig": []}
    session_dict["altbestand"]["mehrdeutig"] = _sc.lifecycle_order_conflicts(session_dict)


def get_session(conn: sqlite3.Connection, actor_or_sid, sid_or_actor=None, *, wirksam: bool = True):
    """REF order: get_session(conn, actor, session_id). Raises KeyError / IsolationError.

    Product order get_session(conn, session_id, actor) is also accepted.
    """
    row_first = conn.execute(
        "SELECT id, user_id, world_id, json FROM v_sessions WHERE id=?", (actor_or_sid,)
    ).fetchone()
    row_second = conn.execute(
        "SELECT id, user_id, world_id, json FROM v_sessions WHERE id=?", (sid_or_actor,)
    ).fetchone()
    if row_second is not None:
        actor = actor_or_sid
        row = row_second
    elif row_first is not None:
        actor = sid_or_actor
        row = row_first
    else:
        raise KeyError("session not found")
    if not session_owner_ok(row["user_id"], actor):
        raise IsolationError("foreign session")
    if not world_bindable(conn, actor, row["world_id"]):
        raise IsolationError("cannot bind session to foreign world")
    return rehydrate_session_row(conn, row, wirksam=wirksam)   # V70: one hydrate (it was read twice)



def get_mcc(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    """Scoped export for actor. SQL children win on session read."""
    users: list[Any] = []
    row = conn.execute("SELECT json FROM users WHERE id=?", (actor,)).fetchone()
    if row:
        users.append(_loads(row[0]))
    # admin profile only when actor is admin (already included as own row)

    worlds: list[Any] = []
    world_ids: set[str] = set()
    for r in conn.execute("SELECT id, owner_user_id, json FROM v_worlds"):
        wid, owner, js = r[0], r[1], r[2]
        if world_is_readable(wid, owner, actor):
            worlds.append(_loads(js))
            world_ids.add(wid)

    characters: list[Any] = []
    for r in conn.execute("SELECT world_id, json FROM v_characters"):
        if r[0] in world_ids:
            from matrix_api.learning import canonical_stem
            characters.append(canonical_stem(_loads(r[1])))

    sessions: list[Any] = []
    for r in conn.execute(
        "SELECT id, user_id, world_id, json FROM v_sessions WHERE user_id=? ORDER BY id",
        (actor,),
    ):
        if not world_bindable(conn, actor, r["world_id"]):
            continue
        sessions.append(rehydrate_session_row(conn, r, wirksam=False))   # V70: an export copies every stored row

    def _owned(table: str) -> list[Any]:
        if table not in TABLE_ALLOW:
            raise ValueError(table)
        rows = conn.execute(f"SELECT json FROM {table} WHERE user_id=? ORDER BY id", (actor,)).fetchall()
        return [_loads(x[0]) for x in rows]

    cfg_row = conn.execute(
        "SELECT json FROM config WHERE scope=? AND scope_id=?", ("user", actor)
    ).fetchone()
    config = _loads(cfg_row[0]) if cfg_row else {}

    meta = conn.execute("SELECT value FROM meta WHERE key=?", ("activeUserId",)).fetchone()
    active = meta[0] if meta and meta[0] else actor
    if not any(isinstance(u, dict) and u.get("id") == active for u in users):
        active = actor

    return {
        "users": users,
        "activeUserId": active,
        "worlds": worlds,
        "characters": characters,
        "sessions": sessions,
        "uploads": _owned("uploads"),
        "reviews": _owned("reviews"),
        "snapshots": _owned("snapshots"),
        "triggers": _owned("triggers"),
        "logs": list_logs(conn, actor)["logs"],
        "preferences": _owned("preferences"),
        # Stand 07 / SEC (AMASTER §60/§67, KV §14 "API-Keys erscheinen nicht im Klartext"): the MCC reader goes to every
        # page of the browser - it carries the same masked view as GET /api/config (key presence + mask), never the key.
        "config": public_config_view(config) if isinstance(config, dict) else {},
    }


# ---------------------------------------------------------------------------
# B1R2.2 scoped product writers
# ---------------------------------------------------------------------------

_SECRET_KEYS = {"apikey", "api_key", "api-key"}


def _redact_secrets(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if str(k).lower() in _SECRET_KEYS:
                out[k] = "***"
            else:
                out[k] = _redact_secrets(v)
        return out
    if isinstance(obj, list):
        return [_redact_secrets(x) for x in obj]
    return obj


def _body_dict(body: Any, kind: str = "body") -> dict[str, Any]:
    if not isinstance(body, dict):
        raise WriterError(f"{kind} must be a JSON object", 400, "BAD_REQUEST")
    return body


_PROVISIONAL_ID_RE = re.compile(r"^tmp_([a-z0-9-]+)_([a-z0-9]+)_([a-z0-9]+)$", re.I)
_CANONICAL_PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$", re.I)


def allocate_ids(body: Any) -> dict[str, Any]:
    """R4.1: backend-owned canonical ID allocation for frontend drafts.

    The frontend may create provisional tmp_* ids for an in-memory graph, but no
    tmp_* id is allowed to reach a persistent writer. This endpoint is the only
    product path that turns those provisional identities into canonical ids.
    """
    data = _body_dict(body, "id allocation")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise WriterError("id allocation requires items", 400, "BAD_REQUEST")
    if len(items) > 5000:
        raise WriterError("too many id allocation items", 400, "BAD_REQUEST")
    allocations: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    for raw in items:
        if not isinstance(raw, dict):
            raise WriterError("id allocation item must be object", 400, "BAD_REQUEST")
        temp_id = str(raw.get("tempId") or raw.get("temp_id") or "").strip()
        match = _PROVISIONAL_ID_RE.match(temp_id)
        if not match:
            raise WriterError("id allocation item is not provisional", 400, "BAD_REQUEST")
        prefix = str(raw.get("prefix") or match.group(1)).strip().lower()
        if prefix != match.group(1).lower() or not _CANONICAL_PREFIX_RE.match(prefix):
            raise WriterError("id allocation prefix mismatch", 400, "BAD_REQUEST")
        canonical = seen.get(temp_id)
        if canonical is None:
            canonical = f"{prefix}_{secrets.token_hex(12)}"
            seen[temp_id] = canonical
        allocations.append({"tempId": temp_id, "prefix": prefix, "id": canonical})
    return {"ok": True, "allocations": allocations}


def _wid(body: dict[str, Any], kind: str) -> str:
    oid = body.get("id")
    if oid is None or str(oid).strip() == "":
        raise WriterError(f"{kind} missing required field id", 400, "BAD_REQUEST")
    value = str(oid).strip()
    if _PROVISIONAL_ID_RE.match(value):
        raise WriterError(f"{kind} provisional id must be canonicalized by backend allocator", 400, "PROVISIONAL_ID")
    return value


def _world_row(conn: sqlite3.Connection, world_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, owner_user_id, json FROM worlds WHERE id=?", (world_id,)
    ).fetchone()


def _session_row(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (session_id,)
    ).fetchone()


# V65S (AMASTER §63 "eine Lesung je notwendigem Session-Snapshot, Aenderung nur betroffener Owner"; Pruefung v3.1 §4:
# a save without any change ran 3,555 SQL statements, 388 of them UPDATE sessions): inside ONE save_session the
# session row is read and its ownership checked once, and the envelope is stamped once (by save_session itself) -
# not again by every child writer. Outside a save (a single child API write) nothing changes.
_SAVE_SCOPE: contextvars.ContextVar[dict | None] = contextvars.ContextVar("matrix10_save_scope", default=None)
# V65T (AMASTER §63 "Aenderung nur betroffener Owner", §68 Nr. 24; Gegenpruefung v3.2 Befund 6, Plan v2 Schritt 5): inside
# ONE save_session the existing rows of this session are read once per child table (id -> stored JSON). Writers compare
# against them instead of one SELECT per item; nothing is cached across saves (the scope ends with the save).
_SCOPE_TABLES = ("scene_facts", "memories", "god_facts", "turns", "turn_truth", "propositions", "goals", "relationships")


def _scope_own(table: str) -> dict[str, str] | None:
    scope = _SAVE_SCOPE.get()
    own = (scope or {}).get("own")
    return own.get(table) if isinstance(own, dict) else None


def _require_owned_session(conn: sqlite3.Connection, session_id: str, actor: str) -> sqlite3.Row:
    scope = _SAVE_SCOPE.get()
    if scope is not None and scope.get("sid") == session_id and scope.get("actor") == actor and scope.get("row") is not None:
        return scope["row"]
    row = _session_row(conn, session_id)
    if row is None:
        raise WriterError("session not found", 404, "NOT_FOUND")
    if not session_owner_ok(row["user_id"], actor):
        raise WriterError("session not owned by actor", 403, "FORBIDDEN")
    return row


def _strip_child_collections(obj: dict[str, Any]) -> dict[str, Any]:
    out = dict(obj)
    for k in CHILD_COLLECTION_KEYS:
        out.pop(k, None)
    return out


def _char_row(conn: sqlite3.Connection, char_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, world_id, owner_user_id, json FROM characters WHERE id=?", (char_id,)
    ).fetchone()


def _world_readable(conn: sqlite3.Connection, world_id: str, actor: str) -> bool:
    row = _world_row(conn, world_id)
    if row is None:
        return False
    return world_is_readable(row["id"], row["owner_user_id"], actor)


def _world_owned(conn: sqlite3.Connection, world_id: str, actor: str) -> bool:
    row = _world_row(conn, world_id)
    if row is None:
        return False
    return world_is_owned(row["owner_user_id"], actor)


# V70 (Audit10 §4 "explizite, kanonische event_seq/commit_order mit persistierter Semantik, einschliesslich Import, Snapshot,
# Restore und Rekonstruktion"; AMASTER §34 "Zeit", "commit_group", "Duplicate-Key", §34.2, §35 "neueste gueltige Evidenz"): the
# session child tables whose rows carry the writer's event position. `seq` is unique within a session and grows with every
# stored row (the commit order); `commit` names the save that stored it (the seq of its first row). Both are written by the
# writer only - a client or a kernel value is replaced (like turnOrder, V1) - and travel with the row in duplicate, import,
# snapshot and restore (copy semantics, herkunft "kopie": kept, checked, never invented).
_SEQ_TABLES = ("scene_facts", "memories", "relationships", "god_facts", "turns", "turn_truth", "propositions", "goals",
               "witness_knowledge")
_WRITER_OWNED_KEYS = ("seq", "commit")


def _is_pos_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _stored_max_seq(conn: sqlite3.Connection, sid: str) -> int:
    best = 0
    for tb in _SEQ_TABLES:
        r = conn.execute(f"SELECT MAX(CAST(json_extract(json, '$.seq') AS INTEGER)) FROM {tb} WHERE session_id=?", (sid,)).fetchone()
        if r is not None and isinstance(r[0], int) and r[0] > best:
            best = r[0]
    return best


def _stamp_event_position(conn: sqlite3.Connection, table: str, sid: str, payload: dict[str, Any]) -> None:
    """V70: give a NEW session child row its event position (see _SEQ_TABLES). Inside a copy (duplicate, import, restore of a
    server snapshot) the row keeps the position it carries - an integer, unique in the session - and a row without one stays
    without (its order within the turn is then not proven and is never guessed). Every other insert is a live commit: the
    next position after the session's stored rows; one save shares one `commit`."""
    scope = _SAVE_SCOPE.get()
    mine = scope is not None and scope.get("sid") == sid
    if mine and scope.get("herkunft") == "kopie":
        seq = payload.get("seq")
        if seq is None:
            payload.pop("commit", None)
            return
        if not _is_pos_int(seq) or (payload.get("commit") is not None and not _is_pos_int(payload.get("commit"))):
            raise WriterError(f"{table} row carries no valid event position (seq {seq!r})", 422, "SEQ_INVALID")
        used = scope.get("seqUsed")
        if used is None:
            used = scope["seqUsed"] = set()
        if seq in used:
            raise WriterError(f"{table} row repeats event position seq {seq} of this session", 422, "SEQ_DUPLICATE")
        used.add(seq)
        return
    if mine and scope.get("nextSeq") is not None:
        seq = scope["nextSeq"]
    else:
        seq = _stored_max_seq(conn, sid) + 1
        if mine:
            scope["commit"] = seq
    if mine:
        scope["nextSeq"] = seq + 1
    payload["seq"] = seq
    payload["commit"] = scope["commit"] if mine else seq


def _preserve_stored_position(payload: dict[str, Any], existing: Any) -> None:
    """V72: seq/commit belong to the ORIGINAL SQL row, not to a PATCH/PUT payload.

    Modify the caller's object in place: the API must return exactly the position
    it stored. A pre-V70 row without these fields stays unpositioned; guessing a
    sequence here would silently change historical evidence.
    """
    if isinstance(existing, str):
        try:
            existing = _loads(existing)
        except (ValueError, TypeError):
            existing = None
    stored = existing if isinstance(existing, dict) else {}
    for key in _WRITER_OWNED_KEYS:
        payload.pop(key, None)
        if key in stored:
            payload[key] = stored[key]


def _check_position_for_legacy_copy(conn: sqlite3.Connection, table: str, sid: str,
                                    id_: str, payload: dict[str, Any]) -> None:
    """COPY-only path for POST /api/import/mcc (unlike live _insert_new).

    One physical seq across all children of a session, including a previous
    MCC import. A missing seq remains missing, with no guessed commit.
    """
    seq = payload.get("seq")
    if seq is None:
        payload.pop("commit", None)
        return
    if not _is_pos_int(seq) or (payload.get("commit") is not None and not _is_pos_int(payload["commit"])):
        raise ImportAborted(f"{table} row has invalid copied event position", 422, "SEQ_INVALID")
    for other in _SEQ_TABLES:
        hit = conn.execute(
            f"SELECT id FROM {other} WHERE session_id=? AND json_extract(json, '$.seq')=? LIMIT 1",
            (sid, seq),
        ).fetchone()
        if hit is not None and (other != table or str(hit[0]) != id_):
            raise ImportAborted(f"session {sid} has duplicate copied seq {seq}", 422, "SEQ_DUPLICATE")


def _same_stored_row(existing: Any, payload: dict[str, Any]) -> bool:
    """Idempotency: live re-sends may carry *any* untrusted seq/commit.

    A copied row (import/duplicate/restore) must keep its own historical position:
    there we still compare exact values, and never silently adopt a different one.
    """
    try:
        cur = _loads(existing) if isinstance(existing, str) else existing
    except (TypeError, ValueError):
        return False
    if not isinstance(cur, dict):
        return False
    if _json_equal(cur, payload):
        return True
    scope = _SAVE_SCOPE.get()
    if scope is not None and scope.get("herkunft") == "kopie":
        return False
    strip = lambda r: {k: v for k, v in r.items() if k not in _WRITER_OWNED_KEYS}
    return strip(cur) == strip(payload)

def _insert_new(
    conn: sqlite3.Connection,
    table: str,
    id_: str,
    payload: dict[str, Any],
    columns: dict[str, Any],
) -> None:
    if table not in TABLE_ALLOW:
        raise ValueError(table)
    if table in _SEQ_TABLES and columns.get("session_id"):
        _stamp_event_position(conn, table, str(columns["session_id"]), payload)   # V70 (Audit10 §4)
    cols = ["id", "json"]
    vals: list[Any] = [id_, _dumps(payload)]
    for k, v in columns.items():
        if k in ("id", "json"):
            continue
        cols.append(k)
        vals.append(v)
    placeholders = ",".join("?" for _ in cols)
    conn.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", vals)


def _update_json(conn: sqlite3.Connection, table: str, id_: str, payload: dict[str, Any], extra: dict[str, Any] | None = None) -> None:
    if table not in TABLE_ALLOW:
        raise ValueError(table)
    if table in _SEQ_TABLES:
        # V72 (AMASTER §34/§35): read the original even when BOTH fields arrived
        # in the payload. Never trust the updater's values or mint a new position.
        # Mutate in place so repository results and API responses show persisted data.
        r = conn.execute(f"SELECT json FROM {table} WHERE id=?", (id_,)).fetchone()
        if r is None:
            raise WriterError(f"{table} row not found", 404, "NOT_FOUND")
        _preserve_stored_position(payload, r[0])
    if extra:
        sets = ["json=?"]
        vals: list[Any] = [_dumps(payload)]
        for k, v in extra.items():
            if k in ("id", "json"):
                continue
            sets.append(f"{k}=?")
            vals.append(v)
        vals.append(id_)
        conn.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", vals)
    else:
        conn.execute(f"UPDATE {table} SET json=? WHERE id=?", (_dumps(payload), id_))

def _owned_get(conn: sqlite3.Connection, table: str, id_: str, actor: str, kind: str) -> dict[str, Any]:
    if table not in TABLE_ALLOW:
        raise ValueError(table)
    row = conn.execute(f"SELECT user_id, json FROM {table} WHERE id=?", (id_,)).fetchone()
    if row is None:
        raise WriterError(f"{kind} not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError(f"{kind} not readable by actor", 403, "FORBIDDEN")
    obj = _loads(row[1])
    return obj if isinstance(obj, dict) else {"id": id_}


def _owned_list(conn: sqlite3.Connection, table: str, actor: str) -> list[Any]:
    if table not in TABLE_ALLOW:
        raise ValueError(table)
    rows = conn.execute(f"SELECT json FROM {table} WHERE user_id=? ORDER BY id", (actor,)).fetchall()
    return [_loads(r[0]) for r in rows]


def _conflict_or_forbidden(existing_owner: str | None, actor: str, kind: str, error_forbidden: str) -> None:
    if existing_owner is None:
        return
    if existing_owner != actor:
        raise WriterError(f"{kind} exists and is not owned by actor", 403, error_forbidden)
    raise WriterError(f"{kind} exists; use PATCH", 409, "USE_PATCH")


def _delete_session_children(conn: sqlite3.Connection, session_id: str) -> None:
    for table in SESSION_CHILD_TABLES:
        if table not in TABLE_ALLOW:
            raise ValueError(table)
        conn.execute(f"DELETE FROM {table} WHERE session_id=?", (session_id,))



# V80: gezielte Endloeschung. Keine neue Tabelle, kein zweiter Speicher-Owner.
# Diese Hilfen werden ausschliesslich ueber vorhandene DELETE-Produktwriter erreicht.
_DELETE_ID_TABLES = ("documents", "document_index", "reviews", "triggers", "logs", "preferences", "uploads", "snapshots")
_DELETE_WORLD_CHILD_TABLES = ("witness_knowledge", "scene_facts", "memories", "relationships", "propositions", "goals", "god_facts", "turns", "turn_truth", "appointments", "graph_edges")


def _references_deleted_id(raw: Any, identifiers: set[str]) -> bool:
    """Exact identity only. Also matches IDs embedded in diagnostic text, never names/stems."""
    if not identifiers:
        return False
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        return any(token in raw for token in identifiers)
    if isinstance(raw, dict):
        return any(_references_deleted_id(k, identifiers) or _references_deleted_id(v, identifiers)
                   for k, v in raw.items())
    if isinstance(raw, (list, tuple)):
        return any(_references_deleted_id(v, identifiers) for v in raw)
    return False


def _prune_deleted_ids(raw: Any, identifiers: set[str]) -> tuple[Any, bool]:
    """Remove exact obsolete IDs from live *mutable* envelopes; preserve other values."""
    if isinstance(raw, str):
        if _references_deleted_id(raw, identifiers):
            return None, True
        return raw, False
    if isinstance(raw, list):
        result = []
        changed = False
        for v in raw:
            clean, was_changed = _prune_deleted_ids(v, identifiers)
            changed |= was_changed
            if clean is not None or (v is None and not was_changed):
                result.append(clean)
        return result, changed
    if isinstance(raw, dict):
        result = {}
        changed = False
        for k, v in raw.items():
            if _references_deleted_id(k, identifiers):
                changed = True
                continue
            clean, was_changed = _prune_deleted_ids(v, identifiers)
            changed |= was_changed
            if clean is not None or (v is None and not was_changed):
                result[k] = clean
        return result, changed
    return raw, False


def _purge_scoped_references(conn: sqlite3.Connection, actor: str, identifiers: set[str]) -> dict[str, int]:
    """Ancillary data of *this* owner, referenced by deleted DB identities.

    Documents and document_index are deleted together. Rows about other IDs
    and every foreign-user row are left byte-for-byte unchanged.
    """
    counts = {}
    for table in _DELETE_ID_TABLES:
        id_column = "document_id" if table == "document_index" else "id"
        selected = [(r[0], r[1]) for r in conn.execute(
            f"SELECT {id_column}, json FROM {table} WHERE user_id=?", (actor,))
            if _references_deleted_id(r[1], identifiers)]
        if table == "documents":
            for doc_id, _ in selected:
                conn.execute("DELETE FROM document_index WHERE document_id=? AND user_id=?", (doc_id, actor))
        for row_id, _ in selected:
            conn.execute(f"DELETE FROM {table} WHERE {id_column}=? AND user_id=?", (row_id, actor))
        counts[table] = len(selected)
    # Config has no user_id, thus only remove specifically scoped rows; never
    # wipe the global app settings or a different user's config.
    for target in identifiers:
        conn.execute("DELETE FROM config WHERE scope IN ('world','character','session') AND scope_id=?", (target,))
    return counts


def _assert_no_foreign_refs(conn: sqlite3.Connection, actor: str, identifiers: set[str], *, world_id: str | None = None, session_id: str | None = None) -> None:
    """No DELETE may orphan or mutate someone else's content."""
    for table in _DELETE_WORLD_CHILD_TABLES + _DELETE_ID_TABLES:
        for row in conn.execute(f"SELECT * FROM {table} WHERE user_id IS NOT NULL AND user_id<>?", (actor,)):
            if _references_deleted_id(row["json"], identifiers):
                raise WriterError("Fremde Benutzer-Daten verweisen auf das Löschziel. Nichts wurde gelöscht.",
                                  409, "DELETE_FOREIGN_DEPENDENCY")
            if world_id is not None and "world_id" in row.keys() and str(row["world_id"]) == world_id:
                raise WriterError("Fremde Weltdaten vorhanden. Nichts wurde gelöscht.", 409, "DELETE_FOREIGN_DEPENDENCY")
            if session_id is not None and "session_id" in row.keys() and str(row["session_id"]) == session_id:
                raise WriterError("Fremde Sessiondaten vorhanden. Nichts wurde gelöscht.", 409, "DELETE_FOREIGN_DEPENDENCY")


def _delete_child_json_refs(conn: sqlite3.Connection, actor: str, identifiers: set[str]) -> dict[str, int]:
    """Purge anomalous session/world child rows with ID only in JSON.

    With no valid SQL scope, the exact immutable ID is still a relationship.
    Never touch another user's evidence.
    """
    result = {}
    for table in _DELETE_WORLD_CHILD_TABLES:
        rows = list(conn.execute(f"SELECT id, json FROM {table} WHERE user_id=? OR user_id IS NULL", (actor,)))
        removed = [r[0] for r in rows if _references_deleted_id(r[1], identifiers)]
        for rid in removed:
            conn.execute(f"DELETE FROM {table} WHERE id=?", (rid,))
        result[table] = len(removed)
    return result


def _check_deleted_ids_absent(conn: sqlite3.Connection, actor: str, identifiers: set[str]) -> None:
    """Backend is not permitted to claim success with any owned SQL remnant."""
    # The actor's user envelope can retain e.g. an old selected ID and is checked too.
    for table in _DELETE_WORLD_CHILD_TABLES + _DELETE_ID_TABLES + ("users", "sessions", "worlds"):
        if table == "users":
            rows = conn.execute("SELECT json FROM users WHERE id=?", (actor,))
        elif table == "worlds":
            rows = conn.execute("SELECT json FROM worlds WHERE owner_user_id=?", (actor,))
        elif table == "document_index":
            rows = conn.execute("SELECT json FROM document_index WHERE user_id=?", (actor,))
        else:
            rows = conn.execute(f"SELECT json FROM {table} WHERE user_id=? OR user_id IS NULL", (actor,)) if table not in ("documents", "reviews", "triggers", "logs", "preferences", "uploads", "snapshots") else conn.execute(f"SELECT json FROM {table} WHERE user_id=?", (actor,))
        if any(_references_deleted_id(r[0], identifiers) for r in rows):
            raise WriterError("Linked SQLite data still exist in " + table, 409, "DELETE_INCOMPLETE")

def _scrub_live_owner_json(conn: sqlite3.Connection, actor: str, identifiers: set[str], *, world_id: str | None = None) -> list[str]:
    """Remove references from existing user/session/world envelopes, not evidence tables.

    Only own sessions are modified. The belonging world is updated solely if
    it is owned by the actor (or is part of a deletion already authorized).
    """
    for r in conn.execute("SELECT id, json FROM users WHERE id=?", (actor,)):
        obj = _loads(r[1])
        clean, changed = _prune_deleted_ids(obj, identifiers)
        if changed:
            _update_json(conn, "users", r[0], clean)
    changed_sessions: list[str] = []
    for r in conn.execute("SELECT id, json FROM sessions WHERE user_id=?", (actor,)):
        obj = _loads(r[1])
        clean, changed = _prune_deleted_ids(obj, identifiers)
        if changed:
            _update_json(conn, "sessions", r[0], clean)
            changed_sessions.append(str(r[0]))
    if world_id:
        wrow = _world_row(conn, world_id)
        if wrow and world_is_owned(wrow["owner_user_id"], actor):
            obj = _loads(wrow["json"])
            clean, changed = _prune_deleted_ids(obj, identifiers)
            if changed:
                _update_json(conn, "worlds", world_id, clean)
    return changed_sessions


def _delete_session_content(conn: sqlite3.Connection, sid: str, owner: str) -> dict[str, int]:
    """Shared session teardown for DELETE session and DELETE world; no optional leftovers."""
    _delete_session_children(conn, sid)
    _delete_child_json_refs(conn, owner, {sid})
    for table in ("snapshots", "uploads"):
        conn.execute(f"DELETE FROM {table} WHERE session_id=?", (sid,))
    extras = _purge_scoped_references(conn, owner, {sid})
    # Old uploads can carry a session ID only in json; handled above.
    conn.execute("DELETE FROM sessions WHERE id=? AND user_id=?", (sid, owner))
    _scrub_live_owner_json(conn, owner, {sid})
    return extras


def _session_extra_children(conn: sqlite3.Connection, session_id: str) -> dict[str, list[Any]]:
    appointments = [_loads(r[0]) for r in conn.execute("SELECT json FROM appointments WHERE session_id=?", (session_id,))]
    edges = [_loads(r[0]) for r in conn.execute("SELECT json FROM graph_edges WHERE session_id=?", (session_id,))]
    return {
        "appointments": [x for x in appointments if isinstance(x, dict)],
        "graphEdges": [x for x in edges if isinstance(x, dict)],
    }


def _capture_session_for_snapshot(conn: sqlite3.Connection, session_id: str, actor: str) -> dict[str, Any]:
    # V70: the capture copies EVERY stored row (also those outside the reader boundary), so a restore brings back the stored
    # state as it was - never a reader's selection of it (AMASTER §34.3 "Historische Evidenz wird nicht heimlich geloescht")
    sess = get_session(conn, actor, session_id, wirksam=False)
    if not isinstance(sess, dict):
        sess = {}
    sess.update(_session_extra_children(conn, session_id))
    return sess


def _insert_extra_children(conn: sqlite3.Connection, session_id: str, nested: dict[str, Any]) -> None:
    row = _session_row(conn, session_id)
    if row is None:
        return
    user_id = row["user_id"]
    world_id = row["world_id"]
    for apt in nested.get("appointments") or []:
        if not isinstance(apt, dict):
            continue
        aid = str(apt.get("id") or uid("apt"))
        payload = dict(apt)
        payload["id"] = aid
        payload["sessionId"] = session_id
        payload["userId"] = user_id
        payload["worldId"] = payload.get("worldId") or world_id
        if conn.execute("SELECT id FROM appointments WHERE id=?", (aid,)).fetchone() is None:
            conn.execute(
                "INSERT INTO appointments(id,user_id,world_id,session_id,json) VALUES (?,?,?,?,?)",
                (aid, user_id, world_id, session_id, _dumps(payload)),
            )
    edges = nested.get("graphEdges") or nested.get("graph_edges") or []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        eid = str(edge.get("id") or uid("ge"))
        payload = dict(edge)
        payload["id"] = eid
        payload["sessionId"] = session_id
        payload["userId"] = user_id
        payload["worldId"] = payload.get("worldId") or world_id
        payload["fromId"] = payload.get("fromId") or payload.get("from_id")
        payload["toId"] = payload.get("toId") or payload.get("to_id")
        if not payload.get("fromId") or not payload.get("toId"):
            continue
        if conn.execute("SELECT id FROM graph_edges WHERE id=?", (eid,)).fetchone() is None:
            conn.execute(
                "INSERT INTO graph_edges(id,user_id,world_id,session_id,from_id,to_id,json) VALUES (?,?,?,?,?,?,?)",
                (eid, user_id, world_id, session_id, payload["fromId"], payload["toId"], _dumps(payload)),
            )


def _replace_session_children(conn: sqlite3.Connection, session_id: str, actor: str, nested: dict[str, Any], *,
                              keep: list | None = None) -> None:
    """Delete SQL children then re-insert from nested snapshot/reset payload.
    V66: `keep` only from restore_snapshot of a checked server capture (see _boundary_violation)."""
    _delete_session_children(conn, session_id)
    payload = dict(nested or {})
    payload["id"] = session_id
    _sync_session_children(conn, actor, payload, keep=keep, herkunft="kopie")   # V70: a restore keeps the stored positions
    _insert_extra_children(conn, session_id, payload)


def seed_session_relations_from_world(conn: sqlite3.Connection, session_id: str, actor: str) -> None:
    row = _require_owned_session(conn, session_id, actor)
    chars: list[dict[str, Any]] = []
    for r in conn.execute("SELECT json FROM characters WHERE world_id=?", (row["world_id"],)):
        obj = _loads(r[0])
        if isinstance(obj, dict) and obj.get("id"):
            chars.append(obj)
    by_name = {(c.get("name") or "").lower(): c for c in chars}
    by_id = {str(c["id"]): c for c in chars}
    for c in chars:
        for rel in c.get("relations") or []:
            if not isinstance(rel, dict):
                continue
            tid = rel.get("targetId") or rel.get("target_id")
            tname = str(rel.get("targetName") or rel.get("target_name") or "").lower()
            target = by_id.get(str(tid)) if tid else by_name.get(tname)
            if not target:
                continue
            fear = float(rel.get("fear") or 0)
            put_session_relation(
                conn,
                session_id,
                {
                    "fromId": str(c["id"]),
                    "toId": str(target["id"]),
                    "trust": rel.get("trust", 0.4),
                    "closeness": rel.get("closeness", 0.4),
                    "fear": fear,
                    "hostility": rel.get("hostility") if rel.get("hostility") is not None else (0.2 if fear > 0.5 else 0),
                    "note": rel.get("note") or "",
                    "kind": rel.get("kind") or "knows",
                    "provenienz": {"quelle": "stamm", "characterId": str(c["id"])},   # V65Y: origin of the seed
                },
                actor,
                on_conflict="skip",
            )


def _insert_session_children(
    conn: sqlite3.Connection,
    session_id: str,
    user_id: str,
    world_id: str,
    session: dict[str, Any],
    warnings: list[str],
    *,
    omit_skip: bool,
) -> None:
    """Insert-only children. Never UPDATE existing rows. Never DELETE omitted.

    omit_skip=True: missing field is ignored (PUT save). omit_skip=False: treat missing as [].
    """
    for field, table in CHILD_FIELDS:
        if field not in session and omit_skip:
            continue
        items = session.get(field)
        if items is None:
            if omit_skip:
                continue
            items = []
        if not isinstance(items, list):
            raise WriterError(f"session {field} must be a list", 400, "BAD_REQUEST")
        for item in items:
            if not isinstance(item, dict):
                raise WriterError(f"session {field} entry must be an object", 400, "BAD_REQUEST")
            cid = item.get("id")
            if cid is None or str(cid).strip() == "":
                raise WriterError(f"session {field} missing id", 400, "BAD_REQUEST")
            cid = str(cid)
            payload = _canon(item, user_id=user_id, world_id=world_id, session_id=session_id)
            payload["id"] = cid
            _insert_keep(
                conn,
                table,
                cid,
                payload,
                {"user_id": user_id, "world_id": world_id, "session_id": session_id},
                warnings,
            )

    if REL_FIELD not in session and omit_skip:
        return
    rels = session.get(REL_FIELD)
    if rels is None:
        if omit_skip:
            return
        rels = []
    if not isinstance(rels, list):
        raise WriterError("session relations must be a list", 400, "BAD_REQUEST")
    for rel in rels:
        if not isinstance(rel, dict):
            raise WriterError("session relation must be an object", 400, "BAD_REQUEST")
        from_id = rel.get("fromId") or rel.get("from_id")
        to_id = rel.get("toId") or rel.get("to_id")
        if not from_id or not to_id:
            raise WriterError("session relation missing fromId/toId", 400, "BAD_REQUEST")
        from_id = str(from_id)
        to_id = str(to_id)
        rid = str(rel.get("id") or f"{session_id}:{from_id}:{to_id}")
        payload = _canon(rel, user_id=user_id, world_id=world_id, session_id=session_id)
        payload["fromId"] = from_id
        payload["toId"] = to_id
        payload["id"] = rid
        _insert_keep(
            conn,
            REL_TABLE,
            rid,
            payload,
            {
                "user_id": user_id,
                "world_id": world_id,
                "session_id": session_id,
                "from_id": from_id,
                "to_id": to_id,
            },
            warnings,
        )


# --- users ---

def create_user(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "user")
    uid = _wid(data, "user")
    row = conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
    if row is not None:
        if uid != actor:
            raise WriterError("cannot create/overwrite a foreign user", 403, "USER_OWNER_FORBIDDEN")
        raise WriterError("user exists; use PATCH", 409, "USE_PATCH")
    if uid != actor and actor != "admin":
        raise WriterError("cannot create a user as another actor", 403, "USER_OWNER_FORBIDDEN")
    payload = dict(data)
    payload["id"] = uid
    created = payload.get("createdAt") or payload.get("created_at") or _now()
    payload["createdAt"] = created
    _insert_new(conn, "users", uid, payload, {"created_at": created})
    return {"ok": True, "user": payload}


def patch_user(conn: sqlite3.Connection, user_id: str, body: Any, actor: str) -> dict[str, Any]:
    if not user_is_self(user_id, actor):
        raise WriterError("only self-patch is allowed", 403, "USER_OWNER_FORBIDDEN")
    data = _body_dict(body, "user")
    row = conn.execute("SELECT json, created_at FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        raise WriterError("user not found", 404, "NOT_FOUND")
    existing = _loads(row[0]) if row[0] else {}
    if not isinstance(existing, dict):
        existing = {"id": user_id}
    patch = dict(data)
    patch.pop("id", None)
    merged = {**existing, **patch, "id": user_id}
    conn.execute("UPDATE users SET json=? WHERE id=?", (_dumps(merged), user_id))
    return {"ok": True, "user": merged}


def delete_user(conn: sqlite3.Connection, user_id: str, actor: str) -> dict[str, Any]:
    if user_id == "admin":
        raise WriterError("admin user cannot be deleted", 403, "USER_OWNER_FORBIDDEN")
    if actor != user_id and actor != "admin":
        raise WriterError("cannot delete a foreign user", 403, "USER_OWNER_FORBIDDEN")
    row = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        raise WriterError("user not found", 404, "NOT_FOUND")
    sess_ids = [r[0] for r in conn.execute("SELECT id FROM sessions WHERE user_id=?", (user_id,))]
    for sid in sess_ids:
        _delete_session_children(conn, sid)
        conn.execute("DELETE FROM snapshots WHERE session_id=?", (sid,))
        conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
    conn.execute("DELETE FROM uploads WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    return {"ok": True, "deleted": user_id}


def get_user(conn: sqlite3.Connection, user_id: str, actor: str) -> dict[str, Any]:
    row = conn.execute("SELECT json FROM users WHERE id=?", (user_id,)).fetchone()
    if row is None:
        raise WriterError("user not found", 404, "NOT_FOUND")
    if user_id != actor:
        raise WriterError("user profile not readable by actor", 403, "USER_OWNER_FORBIDDEN")
    obj = _loads(row[0])
    return obj if isinstance(obj, dict) else {"id": user_id}


def list_users(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    row = conn.execute("SELECT json FROM users WHERE id=?", (actor,)).fetchone()
    users = [_loads(row[0])] if row else []
    return {"ok": True, "users": users}


def list_user_directory(conn: sqlite3.Connection) -> dict[str, Any]:
    """Picker directory: id+name only. No actor scope. Not a profile dump."""
    users: list[dict[str, Any]] = []
    for r in conn.execute("SELECT id, json FROM users ORDER BY id"):
        obj = _loads(r[1]) if r[1] else {}
        name = r[0]
        if isinstance(obj, dict) and obj.get("name"):
            name = str(obj.get("name"))
        users.append({"id": r[0], "name": name})
    return {"ok": True, "users": users, "directory": True}


# --- worlds ---

def create_world(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "world")
    if "world" in data and isinstance(data.get("world"), dict) and not data.get("id"):
        data = dict(data["world"])
    wid = _wid(data, "world")
    row = _world_row(conn, wid)
    if row is not None:
        if row["owner_user_id"] != actor:
            raise IsolationError("cannot patch foreign world")
        raise WriterError("world exists; use PATCH", 409, "USE_PATCH")
    payload = dict(data)
    payload["id"] = wid
    payload["ownerUserId"] = actor
    _insert_new(conn, "worlds", wid, payload, {"owner_user_id": actor})
    return {"ok": True, "world": payload}


def import_world_pack(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    """Commit an imported world, characters, and source evidence in ONE owner transaction.

    The Flask _run_write boundary owns BEGIN/COMMIT/ROLLBACK. This is an
    orchestration of existing SQLite writers, not a parallel world store.
    """
    pack = _body_dict(body, "world pack")
    if pack.get("kind") != "matrix10-world-pack" or pack.get("version") != 1:
        raise WriterError("unsupported world pack format/version", 400, "BAD_WORLD_PACK")
    world = pack.get("world")
    characters = pack.get("characters")
    if not isinstance(world, dict) or not isinstance(characters, list):
        raise WriterError("world and characters are required", 400, "BAD_WORLD_PACK")
    if any(not isinstance(c, dict) for c in characters):
        raise WriterError("invalid character in world pack", 400, "BAD_WORLD_PACK")
    world = dict(world)
    world_id = _wid(world, "world")
    ids = [str(c.get("id") or "") for c in characters]
    if not all(ids) or len(set(ids)) != len(ids):
        raise WriterError("missing or duplicate character IDs", 400, "BAD_WORLD_PACK")
    for character in characters:
        if str(character.get("worldId") or character.get("world_id") or "") != world_id:
            raise WriterError("character bound to different world", 409, "WORLD_PACK_SCOPE")
        for relation in character.get("relations") or []:
            if isinstance(relation, dict) and relation.get("targetId") and relation["targetId"] not in ids:
                raise WriterError("unresolved character relation", 409, "WORLD_PACK_REFERENCE")
    # Source IDs must never silently refer to another world/user after import.
    source_ids = world.get("sourcePartIds") or []
    if not isinstance(source_ids, list) or any(not isinstance(x, str) or not x for x in source_ids):
        raise WriterError("invalid source document IDs", 400, "BAD_WORLD_PACK")
    source_docs = pack.get("sourceDocuments") or []
    if not isinstance(source_docs, list) or any(not isinstance(x, dict) for x in source_docs):
        raise WriterError("invalid source documents", 400, "BAD_WORLD_PACK")
    docs_by_id: dict[str, dict[str, Any]] = {}
    for doc in source_docs:
        did = str(doc.get("id") or "")
        if not did or did in docs_by_id:
            raise WriterError("missing or duplicate source document ID", 400, "BAD_WORLD_PACK")
        docs_by_id[did] = doc
    from secrets import token_hex
    copied_docs: list[dict[str, Any]] = []
    new_source_ids: list[str] = []
    source_remap: dict[str, str] = {}
    for source_id in source_ids:
        if source_id not in source_remap:
            doc = docs_by_id.get(source_id)
            if doc is None:
                row = conn.execute("SELECT user_id, json FROM documents WHERE id=?", (source_id,)).fetchone()
                if row is None or row["user_id"] != actor:
                    raise WriterError(
                        f"source document unavailable in pack: {source_id}",
                        409,
                        "WORLD_PACK_SOURCE_MISSING",
                    )
                doc = _loads(row["json"])
            if not isinstance(doc, dict) or not str(doc.get("text") or "").strip():
                raise WriterError("source document has no text", 400, "WORLD_PACK_SOURCE_EMPTY")
            new_id = f"doc_{token_hex(12)}"
            copied = {**doc, "id": new_id, "worldId": world_id, "documentGroup": f"world-source:{world_id}"}
            for stale_link in ("previousId", "headId", "supersededBy"):
                copied.pop(stale_link, None)
            copied_docs.append(copied)
            source_remap[source_id] = new_id
        new_source_ids.append(source_remap[source_id])
    world["sourcePartIds"] = new_source_ids
    world["characterIds"] = ids
    created_world = create_world(conn, world, actor)["world"]
    created_chars = [create_character(conn, c, actor)["character"] for c in characters]
    for doc in copied_docs:
        create_document(conn, doc, actor)
    if str(world.get("sourceText") or "").strip():
        slug = re.sub(r"[^a-z0-9]+", "", world_id.lower())[:48] or "w"
        create_document(conn, {
            "id": f"doc.world.v1.{slug}.join", "worldId": world_id,
            "title": world.get("sourceName") or world.get("name") or "Weltquelle",
            "text": world["sourceText"], "documentGroup": f"world-source:{world_id}",
            "docKind": "src-join", "schema": 1, "ocrStatus": "ready",
        }, actor)
    return {"ok": True, "world": created_world, "characters": created_chars,
            "sourceDocumentIds": new_source_ids}


def patch_world(conn: sqlite3.Connection, world_id: str, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "world")
    row = _world_row(conn, world_id)
    if row is None:
        raise WriterError("world not found", 404, "NOT_FOUND")
    if not world_is_owned(row["owner_user_id"], actor):
        raise WriterError("world not owned by actor", 403, "WORLD_OWNER_FORBIDDEN")
    existing = _loads(row["json"]) if row["json"] else {}
    if not isinstance(existing, dict):
        existing = {"id": world_id}
    patch = dict(data)
    patch.pop("id", None)
    claimed = patch.pop("ownerUserId", None) or patch.pop("owner_user_id", None)
    if claimed is not None and str(claimed) != row["owner_user_id"]:
        raise WriterError("cannot reassign world owner", 403, "WORLD_OWNER_FORBIDDEN")
    merged = {**existing, **patch, "id": world_id, "ownerUserId": row["owner_user_id"]}
    _update_json(conn, "worlds", world_id, merged)
    return {"ok": True, "world": merged}


def delete_world(conn: sqlite3.Connection, world_id: str, actor: str) -> dict[str, Any]:
    """One scoped SQLite transaction: world, characters, sessions and children."""
    row = _world_row(conn, world_id)
    if row is None:
        raise WriterError("world not found", 404, "NOT_FOUND")
    if not world_is_owned(row["owner_user_id"], actor):
        raise WriterError("world not owned by actor", 403, "WORLD_OWNER_FORBIDDEN")
    foreign_sessions = conn.execute("SELECT count(*) FROM sessions WHERE world_id=? AND user_id<>?", (world_id, actor)).fetchone()[0]
    foreign_chars = conn.execute("SELECT count(*) FROM characters WHERE world_id=? AND owner_user_id<>?", (world_id, actor)).fetchone()[0]
    if foreign_sessions or foreign_chars:
        raise WriterError("Welt ist von fremden Benutzern belegt. Nichts wird gelöscht.", 409, "WORLD_FOREIGN_DATA")
    char_ids = {str(r[0]) for r in conn.execute("SELECT id FROM characters WHERE world_id=?", (world_id,))}
    sess_ids = [str(r[0]) for r in conn.execute("SELECT id FROM sessions WHERE world_id=?", (world_id,))]
    _assert_no_foreign_refs(conn, actor, {world_id} | char_ids | set(sess_ids), world_id=world_id)
    for sid in sess_ids:
        _delete_session_content(conn, sid, actor)
    # Remove any historical/orphaned world-scoped children too. Only the owner.
    for table in _DELETE_WORLD_CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE world_id=? AND (user_id=? OR user_id IS NULL)", (world_id, actor))
    _delete_child_json_refs(conn, actor, {world_id} | char_ids)
    removed_extras = _purge_scoped_references(conn, actor, {world_id} | char_ids)
    conn.execute("DELETE FROM characters WHERE world_id=? AND owner_user_id=?", (world_id, actor))
    _scrub_live_owner_json(conn, actor, {world_id} | char_ids | set(sess_ids))
    conn.execute("DELETE FROM worlds WHERE id=?", (world_id,))
    if conn.execute("SELECT count(*) FROM worlds WHERE id=?", (world_id,)).fetchone()[0]:
        raise WriterError("world remains in SQLite", 500, "DELETE_INCOMPLETE")
    _check_deleted_ids_absent(conn, actor, {world_id} | char_ids | set(sess_ids))
    return {"ok": True, "deleted": world_id, "deletedCharacters": len(char_ids),
            "deletedSessions": len(sess_ids), "deletedRelated": removed_extras,
            "verifiedRowsRemaining": 0}


def get_world(conn: sqlite3.Connection, world_id: str, actor: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, owner_user_id, json FROM v_worlds WHERE id=?", (world_id,)
    ).fetchone()
    if row is None:
        raise WriterError("world not found", 404, "NOT_FOUND")
    if not world_is_readable(row["id"], row["owner_user_id"], actor):
        raise WriterError("world not readable by actor", 403, "WORLD_OWNER_FORBIDDEN")
    obj = _loads(row["json"])
    return obj if isinstance(obj, dict) else {"id": world_id}


def list_worlds(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    items: list[Any] = []
    for r in conn.execute("SELECT id, owner_user_id, json FROM v_worlds ORDER BY id"):
        if world_is_readable(r["id"], r["owner_user_id"], actor):
            items.append(_loads(r["json"]))
    return {"ok": True, "worlds": items}


def backup_world(conn: sqlite3.Connection, world_id: str, actor: str) -> dict[str, Any]:
    row = _world_row(conn, world_id)
    if row is None:
        raise WriterError("world not found", 404, "NOT_FOUND")
    if not world_is_owned(row["owner_user_id"], actor):
        raise WriterError("world not owned by actor", 403, "WORLD_OWNER_FORBIDDEN")
    world = _loads(row["json"]) if row["json"] else {"id": world_id}
    if not isinstance(world, dict):
        world = {"id": world_id}
    chars: list[Any] = []
    for r in conn.execute("SELECT json FROM characters WHERE world_id=? ORDER BY id", (world_id,)):
        obj = _loads(r[0])
        if isinstance(obj, dict):
            chars.append(obj)
    nid = uid("wbak")
    payload = {
        "id": nid,
        "kind": "world-backup",
        "worldId": world_id,
        "userId": actor,
        "sessionId": "",
        "name": f"Sicherung {(world.get('name') if isinstance(world, dict) else world_id) or world_id}",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "world": world,
        "characters": chars,
    }
    _insert_new(conn, "snapshots", nid, payload, {"user_id": actor, "session_id": ""})
    return {"ok": True, "backup": payload}


def list_world_backups(conn: sqlite3.Connection, world_id: str, actor: str) -> dict[str, Any]:
    row = _world_row(conn, world_id)
    if row is None:
        raise WriterError("world not found", 404, "NOT_FOUND")
    if not world_is_readable(row["id"], row["owner_user_id"], actor):
        raise WriterError("world not readable by actor", 403, "WORLD_OWNER_FORBIDDEN")
    items: list[Any] = []
    for r in conn.execute("SELECT json FROM snapshots WHERE user_id=? ORDER BY id DESC", (actor,)):
        obj = _loads(r[0])
        if isinstance(obj, dict) and obj.get("kind") == "world-backup" and obj.get("worldId") == world_id:
            items.append(obj)
    return {"ok": True, "backups": items}


def restore_world_backup(conn: sqlite3.Connection, world_id: str, actor: str, body: Any) -> dict[str, Any]:
    data = body if isinstance(body, dict) else {}
    bid = str(data.get("backupId") or data.get("id") or "")
    if not bid:
        raise WriterError("backupId required", 400, "BAD_REQUEST")
    snap = conn.execute("SELECT user_id, json FROM snapshots WHERE id=?", (bid,)).fetchone()
    if snap is None:
        raise WriterError("backup not found", 404, "NOT_FOUND")
    if snap[0] != actor:
        raise WriterError("backup not owned by actor", 403, "FORBIDDEN")
    payload = _loads(snap[1]) if snap[1] else {}
    if not isinstance(payload, dict) or payload.get("kind") != "world-backup":
        raise WriterError("not a world backup", 400, "BAD_REQUEST")
    if payload.get("worldId") != world_id:
        raise WriterError("backup belongs to another world", 409, "WORLD_MISMATCH")
    packed = payload.get("world") if isinstance(payload.get("world"), dict) else {}
    patch = dict(packed)
    patch.pop("id", None)
    patch.pop("ownerUserId", None)
    patch.pop("owner_user_id", None)
    world = patch_world(conn, world_id, patch, actor).get("world")
    restored = 0
    for ch in payload.get("characters") or []:
        if not isinstance(ch, dict) or not ch.get("id"):
            continue
        cid = str(ch["id"])
        existing = _char_row(conn, cid)
        body_ch = dict(ch)
        body_ch["worldId"] = world_id
        if existing is None:
            create_character(conn, body_ch, actor)
            restored += 1
        elif existing["world_id"] == world_id:
            patch_character(conn, cid, body_ch, actor)
            restored += 1
    return {"ok": True, "world": world, "restoredCharacters": restored, "backupId": bid}


def backup_character(conn: sqlite3.Connection, char_id: str, actor: str) -> dict[str, Any]:
    row = _char_row(conn, char_id)
    if row is None:
        raise WriterError("character not found", 404, "NOT_FOUND")
    if row["owner_user_id"] != actor and not _world_owned(conn, row["world_id"], actor):
        raise WriterError("character not owned by actor", 403, "OWNER_FORBIDDEN")
    obj = _loads(row["json"]) if row["json"] else {"id": char_id}
    if not isinstance(obj, dict):
        obj = {"id": char_id}
    nid = uid("cbak")
    payload = {
        "id": nid,
        "kind": "character-backup",
        "characterId": char_id,
        "worldId": row["world_id"],
        "userId": actor,
        "sessionId": "",
        "name": f"Sicherung {obj.get('name') or char_id}",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "character": obj,
    }
    _insert_new(conn, "snapshots", nid, payload, {"user_id": actor, "session_id": ""})
    return {"ok": True, "backup": payload}


def list_character_backups(conn: sqlite3.Connection, char_id: str, actor: str) -> dict[str, Any]:
    row = _char_row(conn, char_id)
    if row is None:
        raise WriterError("character not found", 404, "NOT_FOUND")
    if not _world_readable(conn, row["world_id"], actor):
        raise WriterError("character not readable by actor", 403, "FORBIDDEN")
    items: list[Any] = []
    for r in conn.execute("SELECT json FROM snapshots WHERE user_id=? ORDER BY id DESC", (actor,)):
        obj = _loads(r[0])
        if isinstance(obj, dict) and obj.get("kind") == "character-backup" and obj.get("characterId") == char_id:
            items.append(obj)
    return {"ok": True, "backups": items}


def restore_character_backup(conn: sqlite3.Connection, char_id: str, actor: str, body: Any) -> dict[str, Any]:
    data = body if isinstance(body, dict) else {}
    bid = str(data.get("backupId") or data.get("id") or "")
    if not bid:
        raise WriterError("backupId required", 400, "BAD_REQUEST")
    snap = conn.execute("SELECT user_id, json FROM snapshots WHERE id=?", (bid,)).fetchone()
    if snap is None:
        raise WriterError("backup not found", 404, "NOT_FOUND")
    if snap[0] != actor:
        raise WriterError("backup not owned by actor", 403, "FORBIDDEN")
    payload = _loads(snap[1]) if snap[1] else {}
    if not isinstance(payload, dict) or payload.get("kind") != "character-backup":
        raise WriterError("not a character backup", 400, "BAD_REQUEST")
    if payload.get("characterId") != char_id:
        raise WriterError("backup belongs to another character", 409, "CHARACTER_MISMATCH")
    packed = payload.get("character") if isinstance(payload.get("character"), dict) else {}
    patch = dict(packed)
    patch.pop("id", None)
    patch.pop("ownerUserId", None)
    patch.pop("owner_user_id", None)
    patch.pop("worldId", None)
    patch.pop("world_id", None)
    restored = patch_character(conn, char_id, patch, actor).get("character")
    return {"ok": True, "character": restored, "backupId": bid}


# --- characters ---

def create_character(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "character")
    cid = _wid(data, "character")
    world_id = data.get("worldId") or data.get("world_id")
    if not world_id:
        raise WriterError("character missing required field worldId", 400, "BAD_REQUEST")
    world_id = str(world_id)
    wrow = _world_row(conn, world_id)
    if wrow is None:
        raise WriterError("world not found", 404, "NOT_FOUND")
    if not world_is_readable(wrow["id"], wrow["owner_user_id"], actor):
        raise WriterError("world not readable by actor", 403, "WORLD_OWNER_FORBIDDEN")
    existing = _char_row(conn, cid)
    if existing is not None:
        if existing["owner_user_id"] != actor and not world_is_owned(wrow["owner_user_id"], actor):
            raise WriterError("cannot create/overwrite a foreign character", 403, "OWNER_FORBIDDEN")
        raise WriterError("character exists; use PATCH", 409, "USE_PATCH")
    payload = _canon(data, world_id=world_id)
    payload["id"] = cid
    payload["ownerUserId"] = actor
    _insert_new(conn, "characters", cid, payload, {"world_id": world_id, "owner_user_id": actor})
    # Shared-Welt: Mitgliedschaft atomar im Writer, kein User-PATCH auf admin-Welt.
    wobj = _loads(wrow["json"]) if wrow["json"] else {}
    if isinstance(wobj, dict):
        ids = [x for x in (wobj.get("characterIds") or []) if x]
        if cid not in ids:
            ids.append(cid)
            wobj["characterIds"] = ids
            wobj["id"] = world_id
            _update_json(conn, "worlds", world_id, wobj)
    return {"ok": True, "character": payload}


def patch_character(conn: sqlite3.Connection, char_id: str, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "character")
    row = _char_row(conn, char_id)
    if row is None:
        raise WriterError("character not found", 404, "NOT_FOUND")
    if row["owner_user_id"] != actor and not _world_owned(conn, row["world_id"], actor):
        raise WriterError("character not owned by actor", 403, "OWNER_FORBIDDEN")
    existing = _loads(row["json"]) if row["json"] else {}
    if not isinstance(existing, dict):
        existing = {"id": char_id}
    patch = dict(data)
    patch.pop("id", None)
    world_id = row["world_id"]
    # V56: pending session values remain in the ledger, not in the stem.
    from matrix_api import learning as _learn
    existing = _learn.canonical_stem(existing)
    approve_id = patch.pop("approveLearned", None)
    if approve_id and not _learn.approve_learned(existing, str(approve_id), actor):
        raise WriterError("learning entry not found or not approvable", 400, "LEARNING_NOT_APPROVABLE")
    # An explicit manual edit of a field can also approve exactly that value.
    for item in existing.get("learnedItems") or []:
        if not isinstance(item, dict) or item.get("status") == "approved":
            continue
        values = patch.get(str(item.get("field") or ""))
        if isinstance(values, list) and item.get("value") in values:
            _learn.approve_learned(existing, str(item.get("id") or ""), actor)
    # V41: gelernten Eintrag entfernen (bearbeitbar): {"removeLearned": "<ledger-id>"}
    remove_id = patch.pop("removeLearned", None)
    remove_all = patch.pop("removeLearnedAll", False)
    if remove_id or remove_all is True:
        from matrix_api import learning as _learn
        if remove_all is True:
            # Explicit editor action only. Never purge automatically and never
            # touch committed SceneFacts, witness knowledge or memory tables.
            for item in list(existing.get("learnedItems") or []):
                if isinstance(item, dict) and item.get("id"):
                    _learn.remove_learned(existing, str(item["id"]))
        elif remove_id:
            _learn.remove_learned(existing, str(remove_id))
    if "worldId" in patch or "world_id" in patch:
        claimed = patch.get("worldId") or patch.get("world_id")
        if claimed and str(claimed) != world_id:
            raise WriterError("cannot move character to another world via patch", 403, "OWNER_FORBIDDEN")
    merged = {**existing, **patch, "id": char_id, "worldId": world_id}
    _update_json(conn, "characters", char_id, merged)
    return {"ok": True, "character": merged}


def learn_into_character(conn: sqlite3.Connection, char_id: str, actor: str, learned: dict[str, Any], *, source: str, session_id: str, turn: int) -> list[dict[str, Any]]:
    """V41: Gelerntes direkt in den Stamm (Nutzerentscheidung: kein Review), mit Ledger."""
    from matrix_api import learning as _learn

    row = _char_row(conn, char_id)
    if row is None:
        return []
    if row["owner_user_id"] != actor and not _world_owned(conn, row["world_id"], actor):
        return []
    existing = _loads(row["json"]) if row["json"] else {}
    if not isinstance(existing, dict):
        return []
    added = _learn.apply_learning(existing, learned, source=source, session_id=session_id, turn=turn)
    if added:
        existing["id"] = char_id
        existing["worldId"] = row["world_id"]
        _update_json(conn, "characters", char_id, existing)
    return [{**a, "characterId": char_id} for a in added]


def delete_character(conn: sqlite3.Connection, char_id: str, actor: str) -> dict[str, Any]:
    """Remove a character plus all character-bound SQLite data, not only its stem."""
    row = _char_row(conn, char_id)
    if row is None:
        raise WriterError("character not found", 404, "NOT_FOUND")
    if row["owner_user_id"] != actor and not _world_owned(conn, row["world_id"], actor):
        raise WriterError("character not owned by actor", 403, "OWNER_FORBIDDEN")
    world_id = str(row["world_id"])
    stem = _loads(row["json"]) if row["json"] else {}
    stem_name = str(stem.get("name") or "") if isinstance(stem, dict) else ""

    # Historical evidence and foreign diagnostics must be checked as well,
    # before any user/session/world data changes.
    _assert_no_foreign_refs(conn, actor, {char_id})
    # Never silently edit another user's session. Reject BEFORE any mutation;
    # _run_write rolls this whole operation back if a later writer fails.
    sessions = list(conn.execute("SELECT id, user_id, json FROM sessions WHERE world_id=?", (world_id,)))
    other_owners = []
    for srow in sessions:
        if srow["user_id"] == actor:
            continue
        data = _loads(srow["json"]) if srow["json"] else {}
        if not isinstance(data, dict):
            continue
        sc = data.get("scene") if isinstance(data.get("scene"), dict) else {}
        refs = {str(x) for key in ("presentIds", "hearsIds", "seesIds") for x in (sc.get(key) or [])}
        refs.update(str(x) for x in (data.get("runtimes") or {}) if isinstance(data.get("runtimes"), dict))
        if str(data.get("avatarId") or "") == char_id or char_id in refs:
            other_owners.append(str(srow["id"]))
    if other_owners:
        raise WriterError(
            "Figur ist in Sitzungen anderer Benutzer aktiv; deren Zustand darf nicht heimlich geändert werden: "
            + ", ".join(other_owners[:4]),
            409, "CHARACTER_FOREIGN_SESSION",
        )

    touched_sessions: list[str] = []
    for srow in sessions:
        if srow["user_id"] != actor:
            continue
        data = _loads(srow["json"]) if srow["json"] else {}
        if not isinstance(data, dict):
            continue
        changed = False
        if str(data.get("avatarId") or data.get("avatar_id") or "") == char_id:
            data["avatarId"] = None
            data.pop("avatar_id", None)
            changed = True
        scene = data.get("scene") if isinstance(data.get("scene"), dict) else {}
        for key in ("presentIds", "hearsIds", "seesIds"):
            if isinstance(scene.get(key), list) and char_id in [str(x) for x in scene[key]]:
                scene[key] = [x for x in scene[key] if str(x) != char_id]
                changed = True
        if changed:
            data["scene"] = scene
        runtimes = data.get("runtimes") if isinstance(data.get("runtimes"), dict) else {}
        if char_id in runtimes:
            runtimes.pop(char_id)
            changed = True
        for rt in runtimes.values():
            if not isinstance(rt, dict):
                continue
            # Current physical pointers cannot continue pointing to a removed body.
            for key in ("heldBy", "holding"):
                if str(rt.get(key) or "") == char_id:
                    rt[key] = None
                    changed = True
        if changed:
            data["runtimes"] = runtimes
        st = data.get("sceneState") if isinstance(data.get("sceneState"), dict) else {}
        for key in ("actorIds", "targetIds"):
            if isinstance(st.get(key), list) and char_id in [str(x) for x in st[key]]:
                st[key] = [x for x in st[key] if str(x) != char_id]
                changed = True
        if str(st.get("nextBeatOwner") or "") == char_id:
            st["nextBeatOwner"] = ""
            changed = True
        if isinstance(st.get("openEmotions"), dict) and char_id in st["openEmotions"]:
            st["openEmotions"].pop(char_id)
            changed = True
        for beat in st.get("openBeats") or []:
            if isinstance(beat, dict) and beat.get("status") == "open" and char_id in (str(beat.get("by") or ""), str(beat.get("owner") or "")):
                beat["status"] = "closed"
                beat["closedReason"] = "character_removed_from_world"
                changed = True
        if changed:
            data["sceneState"] = st
        focus = data.get("focus") if isinstance(data.get("focus"), dict) else {}
        for k, v in list(focus.items()):
            if k.lower().endswith("id") and str(v or "") == char_id:
                focus[k] = None
                changed = True
        if changed:
            data["focus"] = focus
            data["updatedAt"] = _now()
            _update_json(conn, "sessions", str(srow["id"]), data)
            touched_sessions.append(str(srow["id"]))

    # Session-local history remains attributable by immutable character ID.
    # Only character spawn defaults that unambiguously name this stem are reset.
    wrow = _world_row(conn, world_id)
    if wrow is not None:
        wobj = _loads(wrow["json"]) if wrow["json"] else {}
        if isinstance(wobj, dict):
            ids = wobj.get("characterIds")
            if isinstance(ids, list):
                wobj["characterIds"] = [x for x in ids if str(x) != char_id]
            if stem_name:
                same_name_elsewhere = any(
                    str(_loads(other[0]).get("name") or "").casefold() == stem_name.casefold()
                    for other in conn.execute("SELECT json FROM characters WHERE world_id=? AND id<>?", (world_id, char_id))
                )
                if not same_name_elsewhere:
                    for situ in wobj.get("startSituations") or []:
                        if isinstance(situ, dict) and isinstance(situ.get("presentNames"), list):
                            situ["presentNames"] = [n for n in situ["presentNames"] if str(n).casefold() != stem_name.casefold()]
            _update_json(conn, "worlds", world_id, wobj)

    # User's avatar pickers are live references, not historical scene evidence.
    urow = conn.execute("SELECT json FROM users WHERE id=?", (actor,)).fetchone()
    if urow is not None:
        profile = _loads(urow[0]) if urow[0] else {}
        if isinstance(profile, dict):
            picked = False
            for key in ("avatarsByWorld", "avatarsBySession"):
                values = profile.get(key)
                if isinstance(values, dict):
                    for k, v in list(values.items()):
                        if str(v) == char_id:
                            values.pop(k)
                            picked = True
            if picked:
                _update_json(conn, "users", actor, profile)
    # Character-related events/memories/turns/relationships/knowledge have
    # immutable source semantics: remove the entire linked row, not a fictive
    # re-attribution to another character. No stem-matching by similar names.
    removed_evidence: dict[str, int] = {}
    for table in _DELETE_WORLD_CHILD_TABLES:
        ids = []
        # Match either the literal canonical ID in the JSON or a dedicated
        # identity column. Never use approximate character names or stems.
        for x in conn.execute(f"SELECT * FROM {table} WHERE world_id=? AND (user_id=? OR user_id IS NULL)", (world_id, actor)):
            row_keys = x.keys()
            matched = _references_deleted_id(x["json"], {char_id})
            if not matched:
                matched = any(str(x[col]) == char_id for col in ("character_id", "from_id", "to_id") if col in row_keys)
            if matched:
                ids.append(x["id"])
        for evid_id in ids:
            conn.execute(f"DELETE FROM {table} WHERE id=?", (evid_id,))
        removed_evidence[table] = len(ids)
    # Old rows sometimes carry the character only in JSON despite null/mismatched
    # world_id. Remove those as well, without altering foreign-user rows.
    extra_evidence = _delete_child_json_refs(conn, actor, {char_id})
    for table, count in extra_evidence.items():
        removed_evidence[table] += count
    removed_extras = _purge_scoped_references(conn, actor, {char_id})
    newly_scrubbed_sessions = _scrub_live_owner_json(conn, actor, {char_id}, world_id=world_id)
    touched_sessions = list(dict.fromkeys(touched_sessions + newly_scrubbed_sessions))
    conn.execute("DELETE FROM characters WHERE id=?", (char_id,))
    _check_deleted_ids_absent(conn, actor, {char_id})
    for table, column in (("witness_knowledge", "character_id"), ("relationships", "from_id"),
                          ("relationships", "to_id"), ("graph_edges", "from_id"), ("graph_edges", "to_id")):
        if conn.execute(f"SELECT count(*) FROM {table} WHERE {column}=? AND (user_id=? OR user_id IS NULL)", (char_id, actor)).fetchone()[0]:
            raise WriterError("Character reference remains in " + table, 500, "DELETE_INCOMPLETE")
    updated = [rehydrate_session_row(conn, conn.execute("SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (sid,)).fetchone()) for sid in touched_sessions]
    world_after = _loads(conn.execute("SELECT json FROM worlds WHERE id=?", (world_id,)).fetchone()[0])
    user_after = _loads(conn.execute("SELECT json FROM users WHERE id=?", (actor,)).fetchone()[0]) if urow is not None else None
    return {"ok": True, "deleted": char_id, "detachedSessions": touched_sessions,
            "sessionUpdates": updated, "world": world_after, "user": user_after,
            "historyPreserved": False, "deletedRelated": removed_extras,
            "deletedEvidence": removed_evidence, "verifiedRowsRemaining": 0}


def get_character(conn: sqlite3.Connection, char_id: str, actor: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, world_id, json FROM v_characters WHERE id=?", (char_id,)
    ).fetchone()
    if row is None:
        raise WriterError("character not found", 404, "NOT_FOUND")
    if not _world_readable(conn, row["world_id"], actor):
        raise WriterError("character not readable by actor", 403, "FORBIDDEN")
    obj = _loads(row["json"])
    from matrix_api.learning import canonical_stem
    return canonical_stem(obj) if isinstance(obj, dict) else {"id": char_id}


def list_characters(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    items: list[Any] = []
    for r in conn.execute("SELECT world_id, json FROM v_characters ORDER BY id"):
        if _world_readable(conn, r[0], actor):
            from matrix_api.learning import canonical_stem
            items.append(canonical_stem(_loads(r[1])))
    return {"ok": True, "characters": items}


# --- sessions ---

def _assert_figures_in_world(conn: sqlite3.Connection, world_id: str, ids: list[str]) -> None:
    """Reject missing character rows (no ghost ids) and figures bound to another world.

    Empty strings are skipped. A referenced avatarId/presentId with no characters
    row raises FIGURE_NOT_FOUND. A row whose world_id differs raises AVATAR_WORLD_MISMATCH.
    """
    seen: set[str] = set()
    for cid in ids:
        cid = str(cid or "").strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        row = conn.execute("SELECT world_id FROM characters WHERE id=?", (cid,)).fetchone()
        if row is None:
            raise WriterError(f"figure {cid} not found", 404, "FIGURE_NOT_FOUND")
        bound = row["world_id"] if not isinstance(row, tuple) else row[0]
        if str(bound) != str(world_id):
            raise WriterError(
                f"figure {cid} belongs to world {bound}, not {world_id}",
                409,
                "AVATAR_WORLD_MISMATCH",
            )


def _session_figure_ids(data: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    av = data.get("avatarId") or data.get("avatar_id")
    if av:
        ids.append(str(av))
    scene = data.get("scene") if isinstance(data.get("scene"), dict) else {}
    for cid in scene.get("presentIds") or scene.get("present_ids") or []:
        if cid:
            ids.append(str(cid))
    return ids


def create_session(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    """Envelope-only create. Child collections in the body are ignored (not insert)."""
    data = _body_dict(body, "session")
    if "session" in data and isinstance(data.get("session"), dict) and not data.get("id"):
        data = dict(data["session"])
    sid = _wid(data, "session")
    row = _session_row(conn, sid)
    if row is not None:
        if row["user_id"] != actor:
            raise WriterError("cannot create/overwrite a foreign session", 403, "FORBIDDEN")
        raise WriterError("session exists; use PUT/PATCH", 409, "USE_PATCH")
    world_id = data.get("worldId") or data.get("world_id")
    if not world_id:
        raise WriterError("session missing required field worldId", 400, "BAD_REQUEST")
    world_id = str(world_id)
    wrow = _world_row(conn, world_id)
    if wrow is None:
        raise WriterError("world not found", 404, "NOT_FOUND")
    if not session_world_allowed(world_id, wrow["owner_user_id"], actor):
        raise WriterError(
            f"session must not bind foreign world {world_id}",
            409,
            "SESSION_WORLD_OWNER_MISMATCH",
        )
    user_id = actor
    warnings: list[str] = []
    source_sid = str(data.get("sourceSessionId") or data.get("source_session_id") or "").strip()
    import_mode = data.get("import") is True
    if source_sid:
        # AMASTERv2 §19 "Session duplizieren, sofern bewusst gewünscht": der
        # Server kopiert seinen eigenen kanonischen Stand — kein Client-Blob.
        from matrix_api import kernel as _kernel

        src = get_session(conn, actor, source_sid)
        if str(src.get("worldId")) != world_id:
            raise WriterError("duplicate must stay in the same world", 409, "SESSION_WORLD_IMMUTABLE")
        copy_ = _kernel.rekey_session_graph({**src, "id": sid, "name": str(data.get("name") or f"{src.get('name')} (Kopie)"),
                                             "createdAt": _now(), "updatedAt": _now(), "duplicatedFrom": source_sid})
        copy_["id"] = sid
        copy_["userId"] = user_id
        copy_["worldId"] = world_id
        # Relationen tragen session-gebundene IDs (session:from:to) → im Duplikat neu vergeben.
        # V65Y (Gesamtpruefung V65X N02): the copied relation's origin is the source session's canonical state
        copy_["relations"] = [{**{k: v for k, v in r.items() if k != "id"}, "provenienz": {"quelle": "duplikat", "von": source_sid}}
                              for r in (copy_.get("relations") or []) if isinstance(r, dict)]
        # V65Y (Gesamtpruefung V65X P0-4 "Bestehende ungueltige Wahrheit behandeln"): stored legacy rows that fail the
        # write boundary are not copied into the new session - listed, not elevated to new truth, not rewritten
        _q: list = []
        sess = _insert_built_session(conn, actor, world_id, copy_, quarantine=_q, herkunft="kopie")
        warnings.append("DUPLICATED_FROM_SERVER_STATE")
        # V70: the source is read through the reader boundary - its rows outside it are not part of the copy (listed)
        _q = _q + [{"code": z.get("code")} for z in ((src.get("altbestand") or {}).get("zeilen") or []) if isinstance(z, dict)]
        if _q:
            warnings.append(f"LEGACY_ROWS_NOT_COPIED:{len(_q)}:" + ",".join(sorted({str(x.get('code')) for x in _q})))
        return {"ok": True, "session": sess, "warnings": warnings}
    if import_mode:
        # AMASTERv2 §64 "kontrollierter Import": ausdrücklich, sichtbar markiert, Figurenbindung geprüft.
        # V65Z (SPS-Audit V65Y A08; Reparaturvertrag §16 vollstaendige Speicherkette; AMASTER §6.2 Z. 262 fail-closed): the
        # WHOLE session - envelope and children - comes in this one request. The server re-keys it (kernel.rekey_session_graph,
        # the same as the duplicate) and writes every child through the child writers of the write boundary inside the route's
        # one transaction (_run_write): a child that fails refuses the whole import (422), nothing is stored. V65Y stored the
        # envelope here and the client then wrote each child with its own request; a failing child left a half session.
        from matrix_api import kernel as _kernel

        raw = {k: v for k, v in data.items() if k not in ("import", "autoritaetAnnehmen", "importedFrom")}
        copy_ = _kernel.rekey_session_graph(raw)
        now = _now()
        von = str(data.get("importedFrom") or data.get("id") or "")
        copy_.update({"id": sid, "userId": user_id, "worldId": world_id, "importedAt": now,
                      "createdAt": data.get("createdAt") or data.get("created_at") or now, "updatedAt": now})
        # the imported relation's origin is the import itself (stamped here, never taken from the file)
        copy_["relations"] = [{**{k: v for k, v in r.items() if k not in ("id", "provenienz", "sourceFactId", "sourceTurnId",
                                                                         "appliedCauses")},
                               "provenienz": {"quelle": "import", "am": now, "durch": actor, **({"von": von} if von else {})}}
                              for r in (copy_.get("relations") or []) if isinstance(r, dict)]
        # V66 (Audit6 N05 / Audit5 E03; AMASTER §64 "kontrollierter Import", §46 "God benoetigt gueltige Authority", §68 Nr. 87
        # "bei unklarer Rolle gilt fail-closed", B30 "Legacy wiederherstellen != externes JSON ohne Provenienz autorisieren"):
        # (1) the envelope is bound to the imported history (turnIndex, no open input, runtimes of figures);
        warnings.extend(bind_session_envelope(conn, {"world_id": world_id}, copy_, copy_, keep_pending=False))
        # (2) every imported row carries its trust class and provenance, stamped here (never taken from the file);
        # (3) God/Regie authority in the file is not proven by this server - it is taken over only when the owner accepts it
        #     explicitly (autoritaetAnnehmen); otherwise the import is refused (409) and nothing is stored.
        claims = import_authority_claims(copy_)
        if claims and data.get("autoritaetAnnehmen") is not True:
            raise WriterError(f"the file carries {claims} God/Regie authority rows this server did not record; accept them "
                              "explicitly (autoritaetAnnehmen) or import without them", 409, "IMPORT_AUTHORITY_UNACCEPTED")
        stamp = {"vertrauen": "fremdimport", "am": now, "durch": actor, **({"von": von} if von else {})}
        for key in CHILD_COLLECTION_KEYS:
            for r in copy_.get(key) or []:
                if isinstance(r, dict):
                    r["importiert"] = {**stamp, **({"autoritaet": "vom Eigentuemer angenommen"} if _authority_claim(key, r) else {})}
        _assert_figures_in_world(conn, world_id, _session_figure_ids(copy_))
        _check_copied_positions(copy_)   # V70 (Audit10 §7 Nr. 4 "erneut gereihter Import")
        sess = _insert_built_session(conn, actor, world_id, copy_, herkunft="kopie")
        warnings.append("IMPORTED_CANONICAL_STATE")
        if claims:
            warnings.append(f"IMPORTED_AUTHORITY_ACCEPTED:{claims}")
        return {"ok": True, "session": sess, "warnings": warnings}
    # V25 SES-01/SES-02 (Vertrag §4: "Der Client darf Bedienabsicht, Auswahl und
    # erwartete Revision senden, aber keine kanonischen runtimes, scene,
    # turnIndex, currentState, witnessKnowledge oder Zeitwahrheit überschreiben").
    from matrix_api import kernel as _kernel

    world = get_world(conn, world_id, actor)
    if not isinstance(world, dict):
        raise WriterError("world not found", 404, "NOT_FOUND")
    listed = list_characters(conn, actor)
    chars = listed.get("characters") if isinstance(listed, dict) else listed
    chars = [c for c in (chars or []) if isinstance(c, dict) and str(c.get("worldId") or c.get("world_id") or "") == world_id]
    avatar_id = data.get("avatarId") or data.get("avatar_id")
    if avatar_id and not any(str(c.get("id")) == str(avatar_id) for c in chars):
        raise WriterError(f"avatar {avatar_id} is not a figure of world {world_id}", 409, "AVATAR_WORLD_MISMATCH")
    present_ids = data.get("presentIds") if isinstance(data.get("presentIds"), list) else None
    if present_ids is None and isinstance(data.get("scene"), dict) and isinstance(data["scene"].get("presentIds"), list):
        present_ids = data["scene"].get("presentIds")  # Auswahl aus Altclient, nur als Selektion gewertet
    fate_enabled = data.get("fateEnabled")
    if fate_enabled is None and isinstance(data.get("fate"), dict) and isinstance(data["fate"].get("enabled"), bool):
        fate_enabled = data["fate"]["enabled"]
    ignored = [k for k in ("scene", "runtimes", "fate", "turnIndex", "witnessKnowledge", "currentState", "time", "directorActions") if k in data]
    if ignored:
        warnings.append("KERNEL_OWNED_FIELDS_IGNORED:" + ",".join(ignored))
    if any(k in data for k in CHILD_COLLECTION_KEYS):
        warnings.append("CHILD_COLLECTIONS_IGNORED")
    built = _kernel.build_new_session(
        world,
        chars,
        session_id=sid,
        user_id=user_id,
        avatar_id=str(avatar_id) if avatar_id else None,
        situation_id=str(data.get("situationId") or "") or None,
        place_id=str(data.get("placeId") or (data.get("scene") or {}).get("placeId") or "") if isinstance(data.get("scene"), (dict, type(None))) else None,
        present_ids=[str(x) for x in present_ids] if present_ids else None,
        name=str(data.get("name") or "") or None,
        role=str(data.get("role") or "") or None,
        alias=str(data.get("alias") or "") or None,
        pipeline=data.get("pipeline") if isinstance(data.get("pipeline"), dict) else None,
        auto_chat=data.get("autoChat") if isinstance(data.get("autoChat"), dict) else None,
        focus=data.get("focus") if isinstance(data.get("focus"), dict) else None,
        fate_enabled=bool(fate_enabled) if fate_enabled is not None else None,
        now=str(data.get("createdAt") or "") or None,
    )
    _assert_figures_in_world(conn, world_id, _session_figure_ids(built))
    sess = _insert_built_session(conn, actor, world_id, built)
    return {"ok": True, "session": sess, "warnings": warnings}


def _check_copied_positions(session: dict[str, Any]) -> None:
    """V70 (Audit10 §4/§7 Nr. 4; AMASTER §6.2 Z. 262): the event positions an imported file carries are kept (its order is the
    order it was committed in, whatever order its lists come in) - but only as positions: integers above 0, each once in
    the session. A file that repeats or breaks them is refused as a whole (422), nothing is stored. A file without them
    (written before V70) is imported without them: its order within a turn stays unproven, visibly (never guessed)."""
    seen: set[int] = set()
    for key in CHILD_COLLECTION_KEYS + ("witnessKnowledge",):
        for r in session.get(key) or []:
            if not isinstance(r, dict) or r.get("seq") is None:
                continue
            seq = r.get("seq")
            if not _is_pos_int(seq) or (r.get("commit") is not None and not _is_pos_int(r.get("commit"))):
                raise WriterError(f"imported {key} row carries no valid event position (seq {seq!r})", 422, "SEQ_INVALID")
            if seq in seen:
                raise WriterError(f"imported {key} row repeats event position seq {seq}", 422, "SEQ_DUPLICATE")
            seen.add(seq)


_AUTHORITY_ROLES = frozenset({"god", "regie"})


def _authority_claim(key: str, r: dict[str, Any]) -> bool:
    """A row of an imported session that claims God/Regie authority: every God fact, a TurnTruth of the God/Regie role or
    authority, a SceneFact the God/Regie authority wrote."""
    if key == "godFacts":
        return True
    if key == "turnTruths":
        return str(r.get("role") or "") in _AUTHORITY_ROLES or str(r.get("authority") or "") in _AUTHORITY_ROLES
    if key == "facts":
        return str(r.get("authority") or "") in _AUTHORITY_ROLES or str(r.get("actorId") or "") in _AUTHORITY_ROLES
    return False


def import_authority_claims(session: dict[str, Any]) -> int:
    """V66 (Audit5 E03): how many rows of an imported session claim God/Regie authority. Read only."""
    return sum(1 for key in ("godFacts", "turnTruths", "facts") for r in session.get(key) or []
               if isinstance(r, dict) and _authority_claim(key, r))


def _insert_built_session(conn: sqlite3.Connection, actor: str, world_id: str, session: dict[str, Any], *,
                          quarantine: list | None = None, herkunft: str = "live") -> dict[str, Any]:
    """Serverseitig gebauten Sessionstand einfügen: Envelope (nur kanonische
    Felder) + Kinder über die zuständigen Writer. Kein Umweg über create_session."""
    sid = str(session["id"])
    envelope: dict[str, Any] = {}
    for key in CANONICAL_ENVELOPE_FIELDS:
        if key in session:
            envelope[key] = session[key]
    for key in ("serverBuilt", "duplicatedFrom", "importedAt"):
        if key in session:
            envelope[key] = session[key]
    envelope["id"] = sid
    envelope["userId"] = actor
    envelope["worldId"] = world_id
    envelope["createdAt"] = envelope.get("createdAt") or _now()
    envelope["updatedAt"] = _now()
    _insert_new(conn, "sessions", sid, envelope, {"user_id": actor, "world_id": world_id})
    warnings = _sync_session_children(conn, actor, {**session, "id": sid, "userId": actor, "worldId": world_id}, quarantine=quarantine,
                                      herkunft=herkunft)
    if warnings:
        raise WriterError("session child id conflict: " + "; ".join(warnings), 409, "SESSION_CHILD_ID_CONFLICT")
    return rehydrate_session_row(
        conn,
        conn.execute("SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (sid,)).fetchone(),
    )


def put_session(conn: sqlite3.Connection, session_id: str, body: Any, actor: str) -> dict[str, Any]:
    """UI-settings writer. Kernel-owned state in the body is ignored.

    V2 server-authority contract: scene/runtimes/turnIndex/currentState/
    witnessKnowledge/time (and session identity/world binding) are not owned by
    PUT/PATCH. Dedicated kernel/repository writers own those fields.
    """
    data = _body_dict(body, "session")
    if "session" in data and isinstance(data.get("session"), dict):
        inner = dict(data["session"])
        for k, v in data.items():
            if k != "session" and k not in inner:
                inner[k] = v
        data = inner
    if not data.get("id"):
        data["id"] = session_id
    row = _session_row(conn, session_id)
    if row is None:
        # PUT is not an upsert. Session creation has its own POST ingress; a
        # stale/client-supplied envelope must never materialize a ghost row.
        raise WriterError("session not found", 404, "NOT_FOUND")
    if not session_owner_ok(row["user_id"], actor):
        raise IsolationError("cannot overwrite foreign session")
    user_id = row["user_id"]
    world_id = row["world_id"]
    existing = _loads(row["json"]) if row["json"] else {}
    if not isinstance(existing, dict):
        existing = {}
    merged = _strip_child_collections(dict(existing))
    for k in ENVELOPE_FIELDS:
        if k == "worldId":
            continue
        if k in data:
            merged[k] = data[k]
    if "speakAs" in data:
        # V92 Paket 14: only a real binding is stored - a mode, or a figure of THIS world ("char:<id>"); empty clears it
        _sa = str(data.get("speakAs") or "").strip()
        if not _sa:
            merged["speakAs"] = None
        elif _sa in SPEAK_AS_MODES or (_sa.startswith("char:") and _sa[5:].strip()):
            if _sa.startswith("char:"):
                _assert_figures_in_world(conn, world_id, [_sa[5:].strip()])
            merged["speakAs"] = _sa
        else:
            raise WriterError("speakAs must be avatar, operator, observer, regie, gott or char:<figure id>", 400, "SPEAK_AS_INVALID")
    requested_world = data.get("worldId") or data.get("world_id")
    if requested_world and str(requested_world) != str(world_id):
        raise WriterError(
            "session world binding is immutable after creation",
            409,
            "SESSION_WORLD_IMMUTABLE",
        )
    merged["id"] = session_id
    merged["userId"] = user_id
    merged["worldId"] = world_id
    if not merged.get("createdAt"):
        merged["createdAt"] = existing.get("createdAt") or existing.get("created_at") or _now()
    merged["updatedAt"] = _now()
    _assert_figures_in_world(conn, world_id, _session_figure_ids(merged))
    conn.execute(
        "UPDATE sessions SET json=?, world_id=? WHERE id=?",
        (_dumps(merged), world_id, session_id),
    )
    warnings: list[str] = []
    if any(k in data for k in CHILD_COLLECTION_KEYS):
        warnings.append("CHILD_COLLECTIONS_IGNORED")
    sess = rehydrate_session_row(
        conn,
        conn.execute(
            "SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (session_id,)
        ).fetchone(),
    )
    return {"ok": True, "session": sess, "warnings": warnings}


def patch_session(conn: sqlite3.Connection, session_id: str, body: Any, actor: str) -> dict[str, Any]:
    """UI-settings patch. Does not touch kernel state or children."""
    data = _body_dict(body, "session")
    slim = {k: v for k, v in data.items() if k in ENVELOPE_FIELDS}
    return put_session(conn, session_id, slim, actor)


def delete_session(conn: sqlite3.Connection, session_id: str, actor: str, *, delete_session_logs: bool = True) -> dict[str, Any]:
    """Delete the requested session AND all its data, not the SQLite database.

    Existing callers may still pass delete_session_logs; the flag can no longer
    make an ordinary 'session löschen' secretly retain session data.
    """
    if not actor:
        raise WriterError("actor required", 401, "UNAUTHORIZED")
    row = _session_row(conn, session_id)
    if row is None:
        raise WriterError("session not found", 404, "NOT_FOUND")
    if not session_owner_ok(row["user_id"], actor):
        raise WriterError("session not owned by actor", 403, "FORBIDDEN")
    sid = str(row["id"])
    owner = str(row["user_id"])
    # No foreign row may be removed or left dangling; preflight before writes.
    _assert_no_foreign_refs(conn, owner, {sid}, session_id=sid)
    # The cleanup is executed in the caller's BEGIN IMMEDIATE transaction.
    counts = _delete_session_content(conn, sid, owner)
    leftovers = conn.execute("SELECT count(*) FROM sessions WHERE id=?", (sid,)).fetchone()[0]
    if leftovers:
        raise WriterError("session remains in SQLite", 500, "DELETE_INCOMPLETE")
    _check_deleted_ids_absent(conn, owner, {sid})
    return {"ok": True, "deleted": sid, "deletedSessionLogs": counts["logs"],
            "deletedRelated": counts, "verifiedRowsRemaining": 0}


def reset_session_chat(conn: sqlite3.Connection, session_id: str, body: Any, actor: str) -> dict[str, Any]:
    """AMASTER §19 "nur Chat zuruecksetzen": clear the dialogue lines, then persist a server-owned opening narrator line.
    Body.turns are NOT re-inserted.
    V67 (Audit7 V66-01; AMASTER §23 TurnTruth, §34 "SceneFact bindet Quellturn", §34.3, §68 Nr. 34/64/87): only the dialogue
    lines (`turns`) are the chat. The TurnTruths are the canonical record of what was entered and the Quellturn of every
    SceneFact that stays - V66 deleted them and left each fact naming a turn that was gone (FACT_SOURCE_INVALID). They stay,
    and so does the turn index: it is kernel-owned and follows the stored history (V66 took it from the request; a reset to 0
    made later turns reuse the turn numbers of the facts that stayed - your session ses_3422… shows it, turnIndex 1 with a
    fact of turn 2). One dependency contract (`dependency_guard`)."""
    row = _session_row(conn, session_id)
    if row is None:
        raise WriterError("session not found", 404, "NOT_FOUND")
    if not session_owner_ok(row["user_id"], actor):
        raise WriterError("session not owned by actor", 403, "FORBIDDEN")
    with dependency_guard(conn, [session_id], "reset-chat"):
        return _reset_session_chat(conn, row, session_id, body, actor)


def _reset_session_chat(conn: sqlite3.Connection, row: sqlite3.Row, session_id: str, body: Any, actor: str) -> dict[str, Any]:
    data = body if isinstance(body, dict) else {}
    conn.execute("DELETE FROM turns WHERE session_id=?", (session_id,))
    existing = _loads(row["json"]) if row["json"] else {}
    if not isinstance(existing, dict):
        existing = {}
    existing = _strip_child_collections(existing)
    warnings: list[str] = []
    if "turnIndex" in data and data.get("turnIndex") != existing.get("turnIndex"):
        warnings.append("KERNEL_OWNED_FIELDS_IGNORED:turnIndex")
    existing["turnIndex"] = max(int(existing.get("turnIndex") or 0), _stored_history_turn(conn, session_id))
    if "focus" in data:
        existing["focus"] = data["focus"]
    existing["id"] = session_id
    existing["userId"] = row["user_id"]
    existing["worldId"] = row["world_id"]
    existing["updatedAt"] = _now()
    conn.execute("UPDATE sessions SET json=? WHERE id=?", (_dumps(existing), session_id))
    if "turns" in data:
        warnings.append("CHILD_COLLECTIONS_IGNORED")
    scene = existing.get("scene") if isinstance(existing.get("scene"), dict) else {}
    opening = str(scene.get("notes") or "").strip() or "Die Szene steht."
    turn = {
        "id": uid("ln"),
        "turn": int(existing["turnIndex"]),   # V67: the opening line stands at the current turn, not before the history
        "speakerId": "narrator",
        "speakerName": "Szene",
        "role": "narrator",
        "speech": opening,
        "firedSpaces": [],
        "source": "engine",
    }
    append_session_turn(conn, session_id, turn, actor, on_conflict="reject")
    sess = rehydrate_session_row(
        conn,
        conn.execute(
            "SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (session_id,)
        ).fetchone(),
    )
    return {"ok": True, "session": sess, "warnings": warnings}


def reset_session_memory(conn: sqlite3.Connection, session_id: str, actor: str) -> dict[str, Any]:
    """Clear memories via own path. SceneFacts/Turns/GodFacts/Relations/Goals/Propositions are NOT deleted.

    Memories live in the child table; GET overlays SQL children. Envelope updatedAt is stamped.
    """
    row = _session_row(conn, session_id)
    if row is None:
        raise WriterError("session not found", 404, "NOT_FOUND")
    if not session_owner_ok(row["user_id"], actor):
        raise WriterError("session not owned by actor", 403, "FORBIDDEN")
    with dependency_guard(conn, [session_id], "reset-memory"):   # V67: the one dependency contract
        conn.execute("DELETE FROM memories WHERE session_id=?", (session_id,))
        _touch_session(conn, session_id)
    sess = rehydrate_session_row(
        conn,
        conn.execute(
            "SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (session_id,)
        ).fetchone(),
    )
    return {"ok": True, "session": sess, "warnings": []}


def reset_session_full(conn: sqlite3.Connection, session_id: str, actor: str) -> dict[str, Any]:
    """Keep session identity (id/user/world/avatar/name). Clear SQL children. Do not delete uploads or the row.
    V67 (Audit7 V66-02): the witness rows are cleared with the facts (SESSION_CHILD_TABLES); one dependency contract."""
    row = _require_owned_session(conn, session_id, actor)
    with dependency_guard(conn, [session_id], "reset-full"):
        return _reset_session_full(conn, row, session_id, actor)


def _reset_session_full(conn: sqlite3.Connection, row: sqlite3.Row, session_id: str, actor: str) -> dict[str, Any]:
    existing = _loads(row["json"]) if row["json"] else {}
    if not isinstance(existing, dict):
        existing = {}
    existing = _strip_child_collections(existing)
    scene = existing.get("scene") if isinstance(existing.get("scene"), dict) else {}
    avatar_id = existing.get("avatarId")
    present = [avatar_id] if avatar_id else []
    opening = scene.get("notes") or (scene.get("openMatters") or ["Die Szene steht."])[0] if scene else "Die Szene steht."
    envelope = {
        "id": session_id,
        "name": existing.get("name") or "Session",
        "avatarId": avatar_id,
        "alias": existing.get("alias") or "",
        "role": existing.get("role") or "teilnehmer",
        "createdAt": existing.get("createdAt") or _now(),
        "updatedAt": _now(),
        "scene": {
            "placeId": scene.get("placeId") or "",
            "placeName": scene.get("placeName") or "",
            "time": scene.get("time") or "jetzt",
            "presentIds": present,
            "tension": 0.35,
            "danger": 0.15,
            "openMatters": [opening],
            "notes": opening,
            "phase": "Anfang",
        },
        "runtimes": {},
        "fate": existing.get("fate") if isinstance(existing.get("fate"), dict) else {"enabled": True, "pressure": 0.4},
        "pipeline": existing.get("pipeline") if isinstance(existing.get("pipeline"), dict) else {},
        "autoChat": existing.get("autoChat") if isinstance(existing.get("autoChat"), dict) else {},
        "focus": {},
        "turnIndex": 0,
        "witnessKnowledge": [],
        "currentState": None,
    }
    canonical = _strip_child_collections(dict(envelope))
    canonical["id"] = session_id
    canonical["userId"] = row["user_id"]
    canonical["worldId"] = row["world_id"]
    conn.execute("UPDATE sessions SET json=? WHERE id=?", (_dumps(canonical), session_id))
    _delete_session_children(conn, session_id)
    seed_session_relations_from_world(conn, session_id, actor)
    sess = rehydrate_session_row(
        conn,
        conn.execute(
            "SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (session_id,)
        ).fetchone(),
    )
    return {"ok": True, "session": sess, "kept": {"id": session_id, "avatarId": avatar_id}, "warnings": []}


def reset_session_runtime(conn: sqlite3.Connection, session_id: str, body: Any, actor: str) -> dict[str, Any]:
    """Server-authoritative runtime/relationship reset.

    ``body`` is deliberately ignored. It is retained only for route/signature
    compatibility so stale clients cannot reintroduce client-computed runtime
    or relationship truth.
    """
    row = _require_owned_session(conn, session_id, actor)
    with dependency_guard(conn, [session_id], "reset-runtime"):   # V67: the one dependency contract
        return _reset_session_runtime(conn, row, session_id, actor)


def _reset_session_runtime(conn: sqlite3.Connection, row: sqlite3.Row, session_id: str, actor: str) -> dict[str, Any]:
    canonical = get_session(conn, actor, session_id)
    world_id = str(row["world_id"] or canonical.get("worldId") or "")
    listed = list_characters(conn, actor)
    chars = [
        c
        for c in (listed.get("characters") if isinstance(listed, dict) else listed) or []
        if isinstance(c, dict)
        and str(c.get("worldId") or c.get("world_id") or "") == world_id
    ]
    # Local import keeps repositories independent at module import time.
    from matrix_api import kernel as _kernel

    reset = _kernel.reset_runtime_only(canonical, chars)
    existing = _loads(row["json"]) if row["json"] else {}
    if not isinstance(existing, dict):
        existing = {}
    existing = _strip_child_collections(existing)
    existing["runtimes"] = reset.get("runtimes") if isinstance(reset.get("runtimes"), dict) else {}
    existing["updatedAt"] = _now()
    existing["id"] = session_id
    existing["userId"] = row["user_id"]
    existing["worldId"] = row["world_id"]
    conn.execute("UPDATE sessions SET json=? WHERE id=?", (_dumps(existing), session_id))
    conn.execute("DELETE FROM relationships WHERE session_id=?", (session_id,))
    rels = reset.get("relations")
    warnings: list[str] = []
    if isinstance(rels, list) and rels:
        for rel in rels:
            if not isinstance(rel, dict):
                warnings.append("relation skipped: not an object")
                continue
            try:
                put_session_relation(conn, session_id, rel, actor, on_conflict="skip", warnings=warnings)
            except WriterError as exc:
                warnings.append(
                    f"relation {rel.get('fromId') or rel.get('from_id')}-{rel.get('toId') or rel.get('to_id')}: {exc.message}"
                )
    else:
        seed_session_relations_from_world(conn, session_id, actor)
    sess = rehydrate_session_row(
        conn,
        conn.execute(
            "SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (session_id,)
        ).fetchone(),
    )
    return {"ok": True, "session": sess, "warnings": warnings}


def reset_session_uploads(conn: sqlite3.Connection, session_id: str, actor: str) -> dict[str, Any]:
    """AMASTER §19: only this session's upload context. Avatar stays. Mode A committed world/character sources detach, not delete.
    V67 (Audit7 V66-03; AMASTER §34.1, §34.3 historische Evidenz nicht heimlich loeschen, §68 Nr. 64/66): an upload that is
    the source of a stored SceneFact of this session is evidence, not context - it stays attached (`keptAsSource`); V66
    deleted it and left the fact naming an upload that was gone. The context (focus, uploadRefs) is cleared."""
    row = _require_owned_session(conn, session_id, actor)
    with dependency_guard(conn, [session_id], "reset-uploads"):
        return _reset_session_uploads(conn, row, session_id, actor)


def _upload_source_ids(conn: sqlite3.Connection, session_id: str) -> set[str]:
    """The uploads the stored SceneFacts of a session name as their source (sourceUploadId). Read only."""
    out: set[str] = set()
    for (j,) in conn.execute("SELECT json FROM scene_facts WHERE session_id=?", (session_id,)):
        f = _loads(j) or {}
        u = str(f.get("sourceUploadId") or f.get("source_upload_id") or "")
        if u:
            out.add(u)
    return out


def _reset_session_uploads(conn: sqlite3.Connection, row: sqlite3.Row, session_id: str, actor: str) -> dict[str, Any]:
    existing = _loads(row["json"]) if row["json"] else {}
    if not isinstance(existing, dict):
        existing = {}
    existing = _strip_child_collections(existing)
    avatar_id = existing.get("avatarId")
    focus = existing.get("focus") if isinstance(existing.get("focus"), dict) else {}
    focus.pop("uploadId", None)
    focus.pop("upload_id", None)
    existing["focus"] = focus
    existing["uploadRefs"] = []
    existing["updatedAt"] = _now()
    existing["id"] = session_id
    existing["userId"] = row["user_id"]
    existing["worldId"] = row["world_id"]
    existing["avatarId"] = avatar_id
    conn.execute("UPDATE sessions SET json=? WHERE id=?", (_dumps(existing), session_id))
    deleted: list[str] = []
    kept_mode_a: list[str] = []
    kept_source: list[str] = []
    sources = _upload_source_ids(conn, session_id)
    for r in conn.execute("SELECT id, user_id, json FROM uploads WHERE session_id=?", (session_id,)).fetchall():
        uid_, owner, raw = r[0], r[1], r[2]
        if str(uid_) in sources:
            kept_source.append(str(uid_))
            continue
        obj = _loads(raw) if raw else {}
        if not isinstance(obj, dict):
            obj = {"id": uid_}
        mode = str(obj.get("mode") or "B")
        committed = bool(obj.get("committed") or obj.get("status") == "committed")
        worldish = bool(
            obj.get("worldId")
            or obj.get("characterId")
            or str(obj.get("targetKind") or "") in ("world", "character")
        )
        if mode == "A" and committed and worldish:
            obj.pop("sessionId", None)
            conn.execute(
                "UPDATE uploads SET session_id=NULL, json=? WHERE id=?",
                (_dumps(obj), uid_),
            )
            kept_mode_a.append(str(uid_))
            continue
        if owner != actor:
            continue
        conn.execute("DELETE FROM uploads WHERE id=?", (uid_,))
        deleted.append(str(uid_))
    sess = rehydrate_session_row(
        conn,
        conn.execute(
            "SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (session_id,)
        ).fetchone(),
    )
    return {
        "ok": True,
        "kind": "reset-uploads",
        "session": sess,
        "deleted": deleted,
        "keptModeA": kept_mode_a,
        "keptAsSource": kept_source,
        "avatarId": avatar_id,
        "warnings": [f"UPLOADS_KEPT_AS_SOURCE:{len(kept_source)}"] if kept_source else [],
    }


def delete_session_relation(
    conn: sqlite3.Connection,
    session_id: str,
    from_id: str,
    to_id: str,
    actor: str,
) -> dict[str, Any]:
    _require_owned_session(conn, session_id, actor)
    if not from_id or not to_id:
        raise WriterError("relation missing fromId/toId", 400, "BAD_REQUEST")
    conn.execute(
        "DELETE FROM relationships WHERE session_id=? AND from_id=? AND to_id=?",
        (session_id, str(from_id), str(to_id)),
    )
    _touch_session(conn, session_id)
    return {"ok": True, "deleted": {"sessionId": session_id, "fromId": str(from_id), "toId": str(to_id)}}


# --- B1R2.4 canonical session child writers ---

def _child_item(body: Any, kind: str) -> tuple[dict[str, Any], str]:
    data = _body_dict(body, kind)
    # R4.1 guard applies to session children too: tmp_* is draft-only.
    return data, _wid(data, kind)


def _canon_from_session(item: dict[str, Any], row: sqlite3.Row, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(item)
    if extra:
        payload.update(extra)
    # SQL session row wins last: extra/client must never keep a foreign identity.
    return _canon(
        payload,
        user_id=row["user_id"],
        world_id=row["world_id"],
        session_id=row["id"],
    )


def _append_immutable_child(
    conn: sqlite3.Connection,
    table: str,
    id_: str,
    payload: dict[str, Any],
    columns: dict[str, Any],
    immutable_error: str,
    *,
    on_conflict: str = "reject",
    warnings: list[str] | None = None,
) -> str:
    """INSERT new; identical payload → idempotent; different payload → 409 or skip."""
    existing = _select_json(conn, table, id_)
    if existing is None:
        _insert_new(conn, table, id_, payload, columns)
        return "inserted"
    if _same_stored_row(existing, payload):
        if table in _SEQ_TABLES:
            _preserve_stored_position(payload, existing)
        return "idempotent"
    if on_conflict == "skip":
        if table in _SEQ_TABLES:
            # An ID collision may belong to a FOREIGN session. 'kept' is not
            # a read authorization; reveal neither its SQL position nor the
            # caller's spoofed one in the attempted (uncommitted) payload.
            for key in _WRITER_OWNED_KEYS:
                payload.pop(key, None)
        if warnings is not None:
            warnings.append(f"{table} id={id_}: existing row kept (payload differs)")
        return "kept"
    raise WriterError(f"{table} id={id_} is immutable", 409, immutable_error)


def _create_mutable_child(
    conn: sqlite3.Connection,
    table: str,
    id_: str,
    payload: dict[str, Any],
    columns: dict[str, Any],
    *,
    on_conflict: str = "reject",
    warnings: list[str] | None = None,
) -> str:
    """Create-only. Existing identical → idempotent; existing different → USE_PATCH or skip."""
    existing = _select_json(conn, table, id_)
    if existing is None:
        _insert_new(conn, table, id_, payload, columns)
        return "inserted"
    if _same_stored_row(existing, payload):
        if table in _SEQ_TABLES:
            _preserve_stored_position(payload, existing)
        return "idempotent"
    if on_conflict == "skip":
        if table in _SEQ_TABLES:
            # An ID collision may belong to a FOREIGN session. 'kept' is not
            # a read authorization; reveal neither its SQL position nor the
            # caller's spoofed one in the attempted (uncommitted) payload.
            for key in _WRITER_OWNED_KEYS:
                payload.pop(key, None)
        if warnings is not None:
            warnings.append(f"{table} id={id_}: existing row kept (use dedicated PATCH)")
        return "kept"
    raise WriterError(f"{table} id={id_} exists; use PATCH", 409, "USE_PATCH")


def _scope_columns(row: sqlite3.Row) -> dict[str, Any]:
    return {"user_id": row["user_id"], "world_id": row["world_id"], "session_id": row["id"]}


def _touch_session(conn: sqlite3.Connection, session_id: str) -> None:
    """Stamp session envelope updatedAt after a child writer. Does not rewrite SQL children.
    V65S: inside a save_session of this session the envelope was stamped by the save itself - no second write."""
    scope = _SAVE_SCOPE.get()
    if scope is not None and scope.get("sid") == session_id:
        return
    row = conn.execute("SELECT json FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        return
    existing = _loads(row[0]) if row[0] else {}
    if not isinstance(existing, dict):
        existing = {}
    existing["updatedAt"] = _now()
    existing["id"] = session_id
    conn.execute("UPDATE sessions SET json=? WHERE id=?", (_dumps(existing), session_id))



# ---------------------------------------------------------------------------------------------------------------------
# V65Y (Gesamtpruefung V65X N01-N03; AMASTER §6.2 Z. 262 fail-closed an kritischer Grenze, §6.2 Nr. 4 kein Direkt-Write,
# §8 User ist keine Figur, §34 SceneFact bindet Quellturn/Actor/Target, §34.1 dieselbe source_turn_id je Komponente,
# §44 RelationshipState gerichtet zwischen zwei Figuren, §46.3/§46.4 God mit Scope und drei Scope-Achsen,
# §71.1.3 "ungepruefter Rohtext direkt als kanonischer Session-Fact", "User-ID und Character-ID als austauschbare
# Identitaet", "Schutz vor direkten unautorisierten Writes" nicht ALLOWED ABSENT): the ONE common write boundary of the
# canonical session children. Every path - the kernel save (save_session), Upload B (pipeline), session seeding, the
# Social UI - passes these writers, so the invariants hold for all of them. New rows only (an existing immutable row is
# kept as before; data is not reinterpreted, no migration). Violations raise WriterError 422 and nothing is written.
SYSTEM_ACTOR_IDS = frozenset({"kernel", "god", "regie", "observer"})   # the authorities the kernel itself writes as Actor
_GOD_TRUTH_SCOPES = frozenset({"welt", "session", "szene"})
_GOD_PERSISTENCE_SCOPES = frozenset({"momentan", "session", "dauerhaft", "invariante"})
_GOD_EPISTEMIC_SCOPES = frozenset({"anwesende", "ziel", "keine"})
_RELATION_PROVENANCE = frozenset({"stamm", "manuell", "duplikat", "import"})   # V65Z: "import" stamped by create_session
SYSTEM_SPEAKER_IDS = SYSTEM_ACTOR_IDS | {"narrator", "system", ""}   # dialogue lines the kernel writes without a figure


def _boundary_violation(table: str, cid: str, err: "WriterError") -> str:
    """V65Y: inside a server-side duplicate (quarantine scope) a stored legacy row that fails the boundary is not copied
    into the new session; it is listed (visible), never elevated to new truth and never silently rewritten -> "quarantined".
    V66 (Audit6 N05; AMASTER §64 "Wiederherstellung", §34.3 "Historische Evidenz wird nicht heimlich geloescht", G29): inside
    the restore of a snapshot THIS server captured (stamp and content hash checked by restore_snapshot) such a row was the
    session's own stored row at capture time - it comes back as it was and is listed (keep scope) -> "kept".
    "" -> the caller raises."""
    scope = _SAVE_SCOPE.get()
    if scope is None:
        return ""
    entry = {"table": table, "id": cid, "code": getattr(err, "error", "") or str(err)[:60]}
    if scope.get("keep") is not None:
        scope["keep"].append(entry)
        return "kept"
    if scope.get("quarantine") is not None:
        scope["quarantine"].append(entry)
        return "quarantined"
    return ""


def _check_ids(conn: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any], keys: tuple[str, ...], *,
               required: tuple[str, ...] = (), system: frozenset | set = frozenset(), code: str) -> None:
    """V65Y (Gesamtpruefung V65X N02 "Referentielle Integritaet serverseitig"; AMASTER §8, §71.1.3): the person IDs of a
    NEW session child are figures of the session's world (or one of the given kernel authorities)."""
    cast = _session_cast_ids(conn, row)
    for k in keys:
        v = payload.get(k)
        if (v is None or v == "") and k not in required:
            continue
        if str(v or "") not in cast and str(v or "") not in system:
            raise WriterError(f"{k} {v!r} is no figure of this world", 422, code)


def _session_cast_ids(conn: sqlite3.Connection, row: sqlite3.Row) -> set[str]:
    """The figures a session may bind: the characters of its world (create_session/_assert_figures_in_world bind only
    those). Read once per save."""
    scope = _SAVE_SCOPE.get()
    if scope is not None and scope.get("sid") == row["id"] and scope.get("cast") is not None:
        return scope["cast"]
    ids = {str(r[0]) for r in conn.execute("SELECT id FROM characters WHERE world_id=?", (row["world_id"],))}
    if scope is not None and scope.get("sid") == row["id"]:
        scope["cast"] = ids
    return ids


_SOURCE_KEYS = (("sourceTurnId", "turnTruth"), ("source_turn_id", "turnTruth"), ("responds_to_fact_id", "fact"),
                ("respondsToFactId", "fact"), ("cause_fact_id", "fact"), ("causeFactId", "fact"),
                ("sourceUploadId", "upload"), ("source_upload_id", "upload"))


def _session_sources(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, set[str]]:
    """V65Z (SPS-Audit V65Y A01; AMASTER §23 TurnTruth, §24.2, §34 "SceneFact bindet Quellturn", §34.1 dieselbe
    source_turn_id je Komponente, §34.2 Kausalprovenienz): the sources a new row of THIS session may name, BY KIND - its
    TurnTruths, its SceneFacts, its uploads (stored, or in the same save). V65Y kept one set of all IDs, so a SceneFact id
    passed as Quellturn (sourceTurnId) and was stored. Read once per save."""
    scope = _SAVE_SCOPE.get()
    sid = row["id"]
    if scope is not None and scope.get("sid") == sid and scope.get("sources") is not None:
        return scope["sources"]
    src = {"turnTruth": {str(r[0]) for r in conn.execute("SELECT id FROM turn_truth WHERE session_id=?", (sid,))},
           "fact": {str(r[0]) for r in conn.execute("SELECT id FROM scene_facts WHERE session_id=?", (sid,))},
           # V66 (Audit5 E02; AMASTER §6.2, §30, §34): an upload belongs to the session by its own session column - V65Z found
           # it by a text search in the upload JSON, so an upload of session B that mentioned A's id counted as A's source
           "upload": {str(r[0]) for r in conn.execute("SELECT id FROM uploads WHERE session_id=?", (sid,))}}
    if scope is not None and scope.get("sid") == sid:
        src["turnTruth"] |= set(scope.get("batchTruths") or ())
        src["fact"] |= set(scope.get("batchFacts") or ())
        scope["sources"] = src
    return src


def _check_sources(conn: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any], *, code: str,
                   keys: tuple = _SOURCE_KEYS, required: bool = True) -> None:
    """V65Z (A01): every source a new row names is of its kind in this session (a Quellturn is a TurnTruth, a cause or
    answered fact is a SceneFact, an upload an upload of this session); a row never names itself; with `required` at least
    one source is named. Fail-closed: one wrong reference refuses the row, even next to a right one."""
    src = _session_sources(conn, row)
    own = str(payload.get("id") or "")
    named = [(k, str(payload.get(k)), kind) for k, kind in keys if payload.get(k) not in (None, "")]
    for k, v, kind in named:
        if v not in src[kind] or (kind == "fact" and v == own):
            raise WriterError(f"source {k}={v!r} is no {kind} of this session", 422, code.replace("UNBOUND", "INVALID"))
    if required and not any(kind in ("turnTruth", "upload") for _, _, kind in named):
        # V66 (Audit5 E04; AMASTER §34 "SceneFact bindet Quellturn", §34.2): a cause or answered fact is provenance IN ADDITION
        # to the Quellturn or upload, never instead of it (V65Z accepted a fact with only cause_fact_id)
        raise WriterError("row has no Quellturn or upload of this session (sourceTurnId/sourceUploadId); a cause_fact_id or "
                          "responds_to_fact_id alone is no source", 422, code)


def _operator_ids() -> frozenset[str]:
    """V65Y-Nachtrag (E2E am Kandidaten-ZIP 31.10.: eine Eingabe als Bedienperson endete in POST /api/kernel/prepare 422
    FACT_ACTOR_UNBOUND 'user'). AMASTER §8 Z. 352 ("nicht automatisch eine Figur"), Z. 1282 (moegliche Sprecher:
    "realer Nutzer als Bedienperson"), §27.2 Z. 1374 (er nimmt am Dialog teil, ausserhalb der Welt): die Kennung, die der
    Kernel selbst fuer die Bedienperson bindet (kernel._OPERATOR_IDS, default_input_actor_id) - Actor und Sprecher ihrer
    Eingabe, Ziel einer Antwort, Partei und Eigentuemer ihrer Bitte. Sie ist keine Figur: keine Beziehung (§44, V65F),
    kein Gedaechtnis-Eigentuemer, kein Ziel eines God-Fakts."""
    from matrix_api import kernel as _kernel
    return frozenset(_kernel._OPERATOR_IDS)


def _bound_id(value: Any, cast: set[str], *, system: bool, operator: bool = False) -> bool:
    v = str(value or "")
    return v in cast or (system and v in SYSTEM_ACTOR_IDS) or (operator and v in _operator_ids())


def _check_fact_boundary(conn: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any]) -> None:
    """A NEW SceneFact: Actor a figure of the session's world, a kernel authority or the Bedienperson; Target (if any) a
    figure or the Bedienperson; at least
    one source that exists in this session (Quellturn / beantworteter Fact / Ursache / Upload). Fail-closed."""
    cast = _session_cast_ids(conn, row)
    actor = payload.get("actorId") if "actorId" in payload else payload.get("actor_id")
    if not _bound_id(actor, cast, system=True, operator=True):
        raise WriterError(f"fact actor {actor!r} is no figure of this world", 422, "FACT_ACTOR_UNBOUND")
    target = payload.get("targetId") or payload.get("target_id")
    if target and not _bound_id(target, cast, system=False, operator=True):
        raise WriterError(f"fact target {target!r} is no figure of this world", 422, "FACT_TARGET_UNBOUND")
    _check_sources(conn, row, payload, code="FACT_SOURCE_UNBOUND")   # V65Z (A01): typed, every reference
    # V70 (Audit10 §2/§7 Nr. 3/4; AMASTER §34 "Validierung", "Authority", §34.1, §6.2 Nr. 3/Z. 262): a stored fact carries its
    # validation as a bool (a missing or None flag is no state the readers can decide on), its role authority from a
    # TurnTruth of that role, and a lifecycle fact comes from a party of the matter it names
    if not isinstance(payload.get("validated"), bool):
        raise WriterError("fact carries no validation (validated must be true or false)", 422, "FACT_VALIDATION_UNBOUND")
    _check_fact_authority(conn, row, payload)
    _check_lifecycle_actor(conn, row, payload)


# V70 (Audit10 §7 Nr. 4 "Authority"; AMASTER §6.2 Nr. 3 Avatar-Effects nur aus ausdruecklichem Nutzerinput, §23 TurnTruth trennt
# Bedienperson, Rolle, Avatar, Puppet-Sprecher, §46 "God benoetigt gueltige Authority", §46.2 Regie): the role authorities a fact
# may carry only from a TurnTruth of the same role (its Quellturn). Measured on your DB: every stored fact of these authorities
# names a TurnTruth of that role, except legacy rows without a stored Quellturn.
_ROLE_AUTHORITIES = frozenset({"god", "regie", "avatar", "teilnehmer", "puppet"})


def _check_fact_authority(conn: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any]) -> None:
    auth = str(payload.get("authority") or "").strip().lower()
    if auth not in _ROLE_AUTHORITIES:
        return
    src = str(payload.get("sourceTurnId") or payload.get("source_turn_id") or "")
    tt = _turn_truth_row(conn, row["id"], src) if src else None
    if tt is None or str(tt.get("role") or "").strip().lower() != auth:
        raise WriterError(f"fact authority {auth!r} without a TurnTruth of that role as its Quellturn", 422, "FACT_AUTHORITY_UNBOUND")


def _session_matters(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, list]:
    """The propositions and goals a lifecycle fact of this session may name: the save's own session state (stored and new,
    in a save) or the stored rows (an audit / a direct write). Read only."""
    scope = _SAVE_SCOPE.get()
    if scope is not None and scope.get("sid") == row["id"] and scope.get("matters") is not None:
        return scope["matters"]
    out = {"propositions": [_loads(j) for (j,) in conn.execute("SELECT json FROM v_propositions WHERE session_id=?", (row["id"],))],
           "goals": [_loads(j) for (j,) in conn.execute("SELECT json FROM v_goals WHERE session_id=?", (row["id"],))]}
    if scope is not None and scope.get("sid") == row["id"]:
        scope["matters"] = out
    return out


def _check_lifecycle_actor(conn: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any]) -> None:
    """V70 (Audit10 §7 Nr. 4 "Revoke"; AMASTER §35, §36.4): the same binding the readers apply (scene_state.lifecycle_bound)."""
    if payload.get("kind") not in ("lifecycle", "goal_state_changed"):
        return
    from matrix_api import scene_state as _sc
    if not _sc.lifecycle_bound(_session_matters(conn, row), payload):
        raise WriterError("lifecycle fact from no party of the matter it names", 422, "LIFECYCLE_ACTOR_UNBOUND")


def _check_turn_not_behind(conn: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any]) -> None:
    """V70 (Audit10 §7 Nr. 4 "Zeitruecklauf"; AMASTER §23, §42): a NEW fact of a live commit carries a turn number not below the
    highest one the session's stored facts carry (the same rule as the audit, _turn_reversal_rows). Copies keep their rows."""
    scope = _SAVE_SCOPE.get()
    if scope is not None and scope.get("sid") == row["id"] and scope.get("herkunft") == "kopie":
        return
    tn = payload.get("turn")
    if not (isinstance(tn, int) and not isinstance(tn, bool)):
        return
    r = conn.execute("SELECT MAX(CAST(json_extract(json, '$.turn') AS INTEGER)) FROM scene_facts WHERE session_id=?", (row["id"],)).fetchone()
    if r is not None and isinstance(r[0], int) and tn < r[0]:
        raise WriterError(f"fact turn {tn} lies below the stored history (turn {r[0]})", 422, "FACT_TURN_REVERSAL")


def _check_duplicate_commit(conn: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any], cid: str) -> None:
    """V70 (Audit10 §7 Nr. 4 "Doppelcommit"; AMASTER §34 "Duplicate-Key"): a NEW fact whose duplicate key (Quellturn, kind,
    actor, text) a fact of an EARLIER commit of this session already carries is the same component committed twice - refused.
    Components of one save may repeat (two equal acts in one input are two acts). Copies keep their rows as they are."""
    key = str(payload.get("duplicate_key") or "")
    scope = _SAVE_SCOPE.get()
    mine = scope is not None and scope.get("sid") == row["id"]
    if not key or (mine and scope.get("herkunft") == "kopie"):
        return
    cur = scope.get("commit") if mine else None
    hit = conn.execute("SELECT id FROM scene_facts WHERE session_id=? AND id<>? AND json_extract(json, '$.duplicate_key')=? "
                       "AND (json_extract(json, '$.commit') IS NULL OR json_extract(json, '$.commit')<>?)",
                       (row["id"], cid, key, cur if cur is not None else -1)).fetchone()
    if hit is not None:
        raise WriterError(f"fact repeats the committed component {hit[0]} (duplicate key)", 409, "FACT_DUPLICATE_COMMIT")


def _turn_truth_row(conn: sqlite3.Connection, sid: str, tt_id: str) -> dict[str, Any] | None:
    """The TurnTruth `tt_id` of session `sid` - stored, or in the same save. Read only."""
    scope = _SAVE_SCOPE.get()
    if scope is not None and scope.get("sid") == sid and tt_id in (scope.get("batchTruthRows") or {}):
        return scope["batchTruthRows"][tt_id]
    r = conn.execute("SELECT json FROM turn_truth WHERE id=? AND session_id=?", (tt_id, sid)).fetchone()
    return (_loads(r[0]) or {}) if r is not None else None


def _check_god_fact_boundary(conn: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any]) -> None:
    """A NEW God fact: its Quellturn is a God TurnTruth of this session (role and authority "god", §46 "God benoetigt
    gueltige Authority"), it carries a scope and the three scope axes exactly as the kernel derives them from that scope
    (§46.3-§46.5: Welt/dauerhaft only with the world choice); Target (if any) a figure. Fail-closed.
    V65Z (SPS-Audit V65Y A02): V65Y took ANY TurnTruth of the session (a puppet's, or one without role) and any axes."""
    sid = row["id"]
    src = str(payload.get("sourceTurnId") or payload.get("source_turn_id") or "")
    tt = _turn_truth_row(conn, sid, src) if src else None
    if tt is None:
        raise WriterError("god fact has no TurnTruth of this session", 422, "GODFACT_SOURCE_UNBOUND")
    if str(tt.get("role") or "") != "god" or str(tt.get("authority") or "") != "god":
        raise WriterError("god fact source is no God TurnTruth (role/authority god)", 422, "GODFACT_AUTHORITY_UNBOUND")
    if not str(payload.get("scope") or "").strip():
        raise WriterError("god fact has no scope", 422, "GODFACT_SCOPE_UNBOUND")
    from matrix_api import kernel as _kernel
    want = _kernel.god_scope_axes(_kernel._god_scope_key(str(payload.get("scope"))))
    if any(payload.get(k) != want[k] for k in ("truthScope", "persistenceScope", "epistemicScope")):
        raise WriterError("god fact scope axes do not follow its scope", 422, "GODFACT_SCOPE_AXES")
    target = payload.get("targetId")
    if target and not _bound_id(target, _session_cast_ids(conn, row), system=False):
        raise WriterError(f"god fact target {target!r} is no figure of this world", 422, "GODFACT_TARGET_UNBOUND")


_TT_PERSON_KEYS = ("speaker_id", "speakerId", "target_id", "targetId", "input_actor_id", "avatar_id", "puppet_id",
                   "response_speaker_id")
_TT_LIST_KEYS = ("present_ids", "hears_ids", "sees_ids")


def _check_turn_truth_boundary(conn: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any]) -> None:
    """V65Z (SPS-Audit V65Y A02; AMASTER §23 "Alle produktiven Eingangswege erzeugen eine gemeinsame kanonische TurnTruth",
    sie trennt Bedienperson, Rolle, Avatar, Puppet-Sprecher, tatsaechlichen Sprecher; §46 Authority): a NEW TurnTruth binds
    a role and an authority, its persons are figures of the world, a kernel authority or the Bedienperson, its perception
    lists name figures, and the God / Regie authority is only that role's (a God TurnTruth speaks as "god"). V65Y stored a
    TurnTruth without any of this, and a God fact could then name it as its Quellturn."""
    role, auth = str(payload.get("role") or "").strip(), str(payload.get("authority") or "").strip()
    if not role or not auth:
        raise WriterError("turn truth binds no role/authority", 422, "TURNTRUTH_UNBOUND")
    cast = _session_cast_ids(conn, row)
    for k in _TT_PERSON_KEYS:
        v = payload.get(k)
        if v not in (None, "") and not _bound_id(v, cast, system=True, operator=True):
            raise WriterError(f"turn truth {k} {v!r} is no figure of this world", 422, "TURNTRUTH_PERSON_UNBOUND")
    for k in _TT_LIST_KEYS:
        bad = [x for x in (payload.get(k) or []) if str(x or "") not in cast] if isinstance(payload.get(k), list) else []
        if bad:
            raise WriterError(f"turn truth {k} names {bad[0]!r}, no figure of this world", 422, "TURNTRUTH_PERSON_UNBOUND")
    if (auth == "god") != (role == "god") or (auth == "god" and str(payload.get("speaker_id") or "") not in ("god", "")):
        raise WriterError("god authority only in a God TurnTruth", 422, "TURNTRUTH_AUTHORITY")
    if auth == "regie" and role != "regie":
        raise WriterError("regie authority only in a Regie TurnTruth", 422, "TURNTRUTH_AUTHORITY")


def _check_relation_boundary(conn: sqlite3.Connection, row: sqlite3.Row, from_id: str, to_id: str,
                             payload: dict[str, Any], *, new: bool) -> None:
    """A directed relation is between two different figures of the session's world (§44, §8). A NEW relation names its
    origin: a SceneFact of this session (sourceFactId / appliedCauses), the character stem at session start, or the
    manual Social seed of the owner (stamped by the route, never by the client). Fail-closed."""
    cast = _session_cast_ids(conn, row)
    if from_id == to_id or from_id not in cast or to_id not in cast:
        raise WriterError(f"relation {from_id!r} -> {to_id!r} is not between two figures of this world", 422, "RELATION_UNBOUND")
    if not new:
        return
    prov = payload.get("provenienz") if isinstance(payload.get("provenienz"), dict) else {}
    if prov.get("quelle") in _RELATION_PROVENANCE:
        return
    # V65Z (A01): the origin by kind - a SceneFact (sourceFactId / appliedCauses) or a TurnTruth (sourceTurnId) of this session
    rel = {"sourceFactId": payload.get("sourceFactId"), "sourceTurnId": payload.get("sourceTurnId")}
    keys = [("sourceFactId", "fact"), ("sourceTurnId", "turnTruth")]
    for i, c in enumerate(payload.get("appliedCauses") or []):
        rel[f"appliedCauses[{i}]"] = c.get("factId") if isinstance(c, dict) else c
        keys.append((f"appliedCauses[{i}]", "fact"))
    try:
        _check_sources(conn, row, rel, code="RELATION_SOURCE_UNBOUND", keys=tuple(keys), required=False)
        if not any(v not in (None, "") for v in rel.values()):
            raise WriterError("relation has no origin", 422, "RELATION_SOURCE_UNBOUND")
    except WriterError as e:
        raise WriterError(e.message if e.error.endswith("INVALID") else "relation has no origin (SceneFact, stamm or manual seed)",
                          422, e.error) from None



def _check_witness_boundary(conn: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any]) -> None:
    """V65Z (SPS-Audit V65Y §3 "Andere Wege umgehen sie weiterhin"; AMASTER §39 Wissen nur aus Wahrnehmung, §8): a NEW
    WitnessKnowledge row: the knower is a figure of the world (the Bedienperson is outside it and knows nothing in it) and
    the known fact is a SceneFact of this session. V65Y checked neither. Fail-closed."""
    who = payload.get("characterId") or payload.get("character_id")
    if not who or str(who) not in _session_cast_ids(conn, row):
        raise WriterError(f"witness {who!r} is no figure of this world", 422, "WITNESS_PERSON_UNBOUND")
    _fid = payload.get("factId") or payload.get("fact_id")
    if not _fid:
        raise WriterError("witness names no fact", 422, "WITNESS_FACT_UNBOUND")
    _check_sources(conn, row, {"factId": _fid}, code="WITNESS_FACT_UNBOUND", keys=(("factId", "fact"),), required=False)
    # V68 (Audit8 P0-5, found by the independent checker: 28 witness rows of ses_3422 name a Quellturn that is not stored;
    # AMASTER §39 Wissen nur aus Wahrnehmung, §34.2 abhaengige Zeilen tragen ihre Abhaengigkeiten): a named Quellturn is a
    # TurnTruth of this session. Not required (the fact carries the source); a wrong one refuses the row.
    _check_sources(conn, row, {"sourceTurnId": payload.get("sourceTurnId") or payload.get("source_turn_id")},
                   code="WITNESS_SOURCE_UNBOUND", keys=(("sourceTurnId", "turnTruth"),), required=False)


def _check_memory_boundary(conn: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any]) -> None:
    """V68 (Audit8 P0-5; AMASTER §34.2 Z. 1819-1827, §39): a NEW memory: its owner is a figure of the world (V65Y) and the
    fact and Quellturn it names are a SceneFact and a TurnTruth of this session. V67 checked only the owner; the independent
    checker found 10 memories of ses_3422 whose Quellturn is not stored. Fail-closed."""
    _check_ids(conn, row, payload, ("characterId",), required=("characterId",), code="MEMORY_OWNER_UNBOUND")
    _check_sources(conn, row, {"factId": payload.get("factId") or payload.get("fact_id"),
                               "sourceTurnId": payload.get("sourceTurnId") or payload.get("source_turn_id")},
                   code="MEMORY_SOURCE_UNBOUND", keys=(("factId", "fact"), ("sourceTurnId", "turnTruth")), required=False)


def _check_patch_ids(conn: sqlite3.Connection, row: sqlite3.Row, existing: dict[str, Any], merged: dict[str, Any],
                     keys: tuple[str, ...], *, system: frozenset | set = frozenset(), code: str) -> None:
    """V65Z (SPS-Audit V65Y A03; AMASTER §6.2, §71.1.3 "User-ID und Character-ID als austauschbare Identitaet"): a PATCH
    that CHANGES a person of a stored row runs the same identity check as a new row (V65Y: PATCH took any ID). A patch that
    leaves the persons as stored is not re-checked, so a listed legacy row keeps its lifecycle (no migration)."""
    changed = tuple(k for k in keys if str(merged.get(k) or "") != str(existing.get(k) or ""))
    if changed:
        _check_ids(conn, row, merged, changed, system=system, code=code)


def _boundary_rows(conn: sqlite3.Connection, session_id: str) -> list[tuple[str, str, str]]:
    """V67 (Audit7 V66-01..04; AMASTER §34.2 "Abhaengige Effects muessen ihre Abhaengigkeiten ausdruecklich tragen", §68 Nr. 66,
    Nr. 87): every stored row of one session that the write boundary would refuse as a new row - (table, id, code). The ONE
    rule set for both directions: the child writers apply it before an insert, `dependency_guard` applies it around every
    operation that removes or replaces rows, `write_boundary_audit` shows it. Also the envelope: an open input must name a
    TurnTruth of the session, and the turn index must not lie behind the stored history. Read only.
    V70 (Audit10 §3/§7; AMASTER §6.2 Z. 262 "darf dann weder Current State veraendern noch als Weltwahrheit, Figurenwissen,
    Handlungserlaubnis, Relationship-Wirkung oder geschehenes Sessionereignis verwendet werden", §34 User/Welt/Session, §34.2,
    §34.3 "abhaengige Ableitungen"): it is also the reader boundary - the rows it lists are not effective evidence
    (hydrate_session_from_sql). Added: the scope of every row (its user, world and session columns are the session's, and
    the identity its stored JSON names is the same - V69 checked neither, a witness row of another user or world passed
    both checkers), the validation flag, the role authority, the lifecycle party, a double commit, the event position, and
    every row that depends on a listed row (QUELLE_ALTBESTAND). Read in a scope of its own (one read of the session's
    sources and figures), never the cache of a save in progress."""
    token = _SAVE_SCOPE.set({"sid": session_id, "audit": True})
    try:
        return _boundary_rows_scoped(conn, session_id)
    finally:
        _SAVE_SCOPE.reset(token)


# V70 (Audit10 §3): the scope columns of the session child tables and the identity keys their stored JSON may carry
_ROW_SCOPE_TABLES = ("scene_facts", "god_facts", "relationships", "turn_truth", "witness_knowledge", "turns", "propositions",
                     "goals", "memories", "uploads")
_JSON_IDENTITY_KEYS = (("user_id", ("userId", "user_id")), ("world_id", ("worldId", "world_id")),
                       ("session_id", ("sessionId", "session_id")))


def _scope_rows(conn: sqlite3.Connection, srow: sqlite3.Row) -> list[tuple[str, str, str]]:
    """V70: rows of the session whose scope columns are not the session's user and world (SCOPE_UNBOUND), or whose stored JSON
    names another identity than its columns (SCOPE_JSON_CONFLICT; the read views lay the columns over the JSON, so the JSON
    claim is silently replaced - a contradiction the canonical writers never produce). Read only."""
    out = []
    for table in _ROW_SCOPE_TABLES:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        sc = [c for c in ("user_id", "world_id", "session_id") if c in cols]
        for r in conn.execute(f"SELECT id, {', '.join(sc)}, json FROM {table} WHERE session_id=?", (srow["id"],)):
            got = dict(zip(sc, r[1:1 + len(sc)]))
            if str(got.get("user_id") or "") != str(srow["user_id"]) or ("world_id" in got and str(got.get("world_id") or "") != str(srow["world_id"])):
                out.append((table, str(r[0]), "SCOPE_UNBOUND"))
                continue
            j = _loads(r[-1]) if r[-1] else {}
            j = j if isinstance(j, dict) else {}
            if any(j.get(k) not in (None, "") and str(j.get(k)) != str(got.get(col) or "")
                   for col, keys in _JSON_IDENTITY_KEYS if col in got for k in keys):
                out.append((table, str(r[0]), "SCOPE_JSON_CONFLICT"))
    return out


def _position_rows(conn: sqlite3.Connection, sid: str) -> list[tuple[str, str, str]]:
    """V70 (Audit10 §4): stored event positions - an integer above 0, once per session (SEQ_INVALID / SEQ_DUPLICATE). Rows
    without a position are legacy, not invalid. Read only."""
    out, seen = [], set()
    for table in _SEQ_TABLES:
        order = _session_child_order_sql("turns") if table == "turns" else (
            "CAST(COALESCE(json_extract(json, '$.turn'), 0) AS INTEGER), rowid")
        for rid, j in conn.execute(f"SELECT id, json FROM {table} WHERE session_id=? ORDER BY {order}", (sid,)):
            x = _loads(j) if j else {}
            seq = x.get("seq") if isinstance(x, dict) else None
            if seq is None:
                continue
            if not _is_pos_int(seq) or (x.get("commit") is not None and not _is_pos_int(x.get("commit"))):
                out.append((table, str(rid), "SEQ_INVALID"))
            elif seq in seen:
                out.append((table, str(rid), "SEQ_DUPLICATE"))
            else:
                seen.add(seq)
    return out


def _duplicate_commit_rows(conn: sqlite3.Connection, sid: str) -> list[tuple[str, str, str]]:
    """V70 (Audit10 §7 Nr. 4; AMASTER §34 Duplicate-Key): stored facts that repeat the duplicate key of an earlier fact of
    another commit (or without a commit: legacy) - the same component committed twice. The first one stays. Read only."""
    first: dict[str, Any] = {}
    out = []
    q = (f"SELECT id, json FROM scene_facts WHERE session_id=? ORDER BY CAST(COALESCE(json_extract(json, '$.turn'), 0) AS INTEGER), "
         "json_type(json, '$.seq') IS NOT NULL, CAST(json_extract(json, '$.seq') AS INTEGER), rowid")
    for rid, j in conn.execute(q, (sid,)):
        x = _loads(j) if j else {}
        key = str((x or {}).get("duplicate_key") or "") if isinstance(x, dict) else ""
        if not key:
            continue
        if key not in first:
            first[key] = x.get("commit")
            continue
        c0, c1 = first[key], x.get("commit")
        if c0 is None or c1 is None or c0 != c1:
            out.append(("scene_facts", str(rid), "FACT_DUPLICATE_COMMIT"))
    return out


def _dependent_rows(conn: sqlite3.Connection, sid: str, listed: set[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """V70 (Audit10 §7 "Erst dann duerfen Foreground, Recall, ... daraus Folgen ableiten"; AMASTER §34.2 abhaengige Effects,
    §34.3 "ausschliesslich davon abhaengige abgeleitete Current-State-Wirkungen muessen neu bewertet werden", §39 Wissen nur
    aus gueltiger Evidenz): rows that name a listed row as their source, cause, answered fact, known fact or matter - a fact
    on a listed Quellturn, a witness row or memory of a listed fact, a lifecycle of a listed proposition or goal, a relation
    caused by a listed fact. Until no further row joins. Read only."""
    rows: list[tuple[str, str, dict]] = []
    for table, view in (("scene_facts", "scene_facts"), ("god_facts", "god_facts"), ("witness_knowledge", "v_witness_knowledge"),
                        ("memories", "memories"), ("relationships", "relationships")):
        for rid, j in conn.execute(f"SELECT id, json FROM {view} WHERE session_id=?", (sid,)):
            x = _loads(j) if j else {}
            rows.append((table, str(rid), x if isinstance(x, dict) else {}))

    def refs(table: str, x: dict) -> list[tuple[str, str]]:
        pl = x.get("payload") if isinstance(x.get("payload"), dict) else {}
        out = [("turn_truth", str(x.get(k))) for k in ("sourceTurnId", "source_turn_id") if x.get(k)]
        out += [("scene_facts", str(x.get(k))) for k in ("responds_to_fact_id", "respondsToFactId", "cause_fact_id", "causeFactId",
                                                         "factId", "fact_id", "sourceFactId") if x.get(k)]
        out += [("scene_facts", str(c.get("factId") if isinstance(c, dict) else c)) for c in x.get("appliedCauses") or [] if c]
        if table == "scene_facts":
            out += [("propositions", str(v)) for v in (x.get("propositionId"), x.get("proposition_id"), pl.get("proposition_id")) if v]
            out += [("goals", str(v)) for v in (x.get("goalId"), x.get("goal_id"), pl.get("goal_id")) if v]
        return out
    found: list[tuple[str, str, str]] = []
    bad = set(listed)
    changed = True
    while changed:
        changed = False
        for table, rid, x in rows:
            if (table, rid) in bad:
                continue
            if any(r in bad for r in refs(table, x)):
                bad.add((table, rid))
                found.append((table, rid, "QUELLE_ALTBESTAND"))
                changed = True
    return found


def _turn_reversal_rows(conn: sqlite3.Connection, sid: str) -> list[tuple[str, str, str]]:
    """V70 (Audit10 §7 Nr. 4 "Zeitruecklauf"; AMASTER §23, §34 Quellturn, §42): in the order the facts were written (their
    insertion sequence - a live commit writes in event-position order, a restore in its capture's stored order), a later fact
    never carries a turn number below one already used -
    such a fact names a turn whose history was already written (your ses_3422 shows one, the turn number reuse V68 closed).
    Read only."""
    out, seen = [], -1
    # the physical write order (insertion sequence): a row written past the writer without a position is checked where it was
    # written, not taken for an older one
    for rid, j in conn.execute("SELECT id, json FROM scene_facts WHERE session_id=? ORDER BY rowid", (sid,)):
        x = _loads(j) if j else {}
        tn = x.get("turn") if isinstance(x, dict) else None
        if isinstance(tn, int) and not isinstance(tn, bool):
            if tn < seen:
                out.append(("scene_facts", str(rid), "FACT_TURN_REVERSAL"))
            seen = max(seen, tn)
    return out


_ENVELOPE_ID_KINDS = (("fact_", "scene_facts"), ("tt_", "turn_truth"), ("prop_", "propositions"), ("up_", "uploads"),
                      ("mem_", "memories"))
_ENVELOPE_CHILD_KEYS = frozenset({"id", "turns", "facts", "godFacts", "memories", "relations", "propositions", "goals", "turnTruths",
                                  "witnessKnowledge", "uploads", "pendingInputTurnId"})


def _envelope_unbound_refs(conn: sqlite3.Connection, sid: str, env: dict[str, Any]) -> list[str]:
    """V70 (Audit10 §7 Nr. 4; AMASTER §34.1 Current State, §6.2 Nr. 5): the ids of facts, TurnTruths, propositions, uploads and
    memories the session envelope's own state (runtimes, sceneState, currentState, frames, claims ...) names - each must be a
    row of this session (V69: only the independent checker looked). Read only."""
    names: list[tuple[str, str]] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            for pre, table in _ENVELOPE_ID_KINDS:
                if o.startswith(pre) and re.fullmatch(r"[a-z]+_[0-9a-z_]+", o):
                    names.append((table, o))
                    break
    for k, v in (env or {}).items():
        if k not in _ENVELOPE_CHILD_KEYS:
            walk(v)
    bad = []
    for table, ident in names:
        if conn.execute(f"SELECT 1 FROM {table} WHERE id=? AND session_id=?", (ident, sid)).fetchone() is None:
            bad.append(ident)
    return bad


def _boundary_rows_scoped(conn: sqlite3.Connection, session_id: str) -> list[tuple[str, str, str]]:
    row = conn.execute("SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        return []
    out: list[tuple[str, str, str]] = []

    def _hit(table: str, rid: str, e: WriterError) -> None:
        out.append((table, str(rid), getattr(e, "error", "") or "UNBOUND"))

    for rid, j in conn.execute("SELECT id, json FROM scene_facts WHERE session_id=?", (session_id,)):
        try:
            _check_fact_boundary(conn, row, _loads(j) or {})
        except WriterError as e:
            _hit("scene_facts", rid, e)
    for rid, j in conn.execute("SELECT id, json FROM god_facts WHERE session_id=?", (session_id,)):
        try:
            _check_god_fact_boundary(conn, row, _loads(j) or {})
        except WriterError as e:
            _hit("god_facts", rid, e)
    for rid, f, t in conn.execute("SELECT id, from_id, to_id FROM relationships WHERE session_id=?", (session_id,)):
        try:
            _check_relation_boundary(conn, row, str(f), str(t), {}, new=False)
        except WriterError as e:
            _hit("relationships", rid, e)
    for rid, j in conn.execute("SELECT id, json FROM turn_truth WHERE session_id=?", (session_id,)):
        try:
            _check_turn_truth_boundary(conn, row, _loads(j) or {})
        except WriterError as e:
            _hit("turn_truth", rid, e)
    # V69 (Audit9 §5, found by the mutation matrix): the canonical witness values are the table's columns (the read view
    # v_witness_knowledge lays character_id, fact_id and source_turn_id over the JSON) - V68 checked the raw JSON, so a row
    # whose column named another figure, fact or turn passed. Read through the view, as every reader does.
    for rid, j in conn.execute("SELECT id, json FROM v_witness_knowledge WHERE session_id=?", (session_id,)):
        try:
            _check_witness_boundary(conn, row, _loads(j) or {})
        except WriterError as e:
            _hit("witness_knowledge", rid, e)
    op = _operator_ids()
    for table, keys, sysids, code in (("turns", ("speakerId",), SYSTEM_SPEAKER_IDS | op, "TURN_SPEAKER_UNBOUND"),
                                      ("propositions", ("actorId", "targetId"), op, "PROPOSITION_PERSON_UNBOUND"),
                                      ("goals", ("ownerId", "targetId"), op, "GOAL_PERSON_UNBOUND")):
        for rid, j in conn.execute(f"SELECT id, json FROM {table} WHERE session_id=?", (session_id,)):
            try:
                _check_ids(conn, row, _loads(j) or {}, keys, system=sysids, code=code)
            except WriterError as e:
                _hit(table, rid, e)
    for rid, j in conn.execute("SELECT id, json FROM memories WHERE session_id=?", (session_id,)):
        try:
            _check_memory_boundary(conn, row, _loads(j) or {})
        except WriterError as e:
            _hit("memories", rid, e)
    env = _loads(row["json"]) if row["json"] else {}
    env = env if isinstance(env, dict) else {}
    pid = str(env.get("pendingInputTurnId") or "")
    if pid and conn.execute("SELECT 1 FROM turn_truth WHERE id=? AND session_id=?", (pid, session_id)).fetchone() is None:
        out.append(("sessions", session_id, "PENDING_INPUT_UNBOUND"))
    hist = _stored_history_turn(conn, session_id)
    ti = env.get("turnIndex")
    if isinstance(ti, int) and not isinstance(ti, bool) and ti < hist:
        out.append(("sessions", session_id, "TURNINDEX_BEHIND_HISTORY"))
    # V70 (Audit10 §7 Nr. 4): the three dependencies V69 left to the independent checker alone
    for rid, j in conn.execute("SELECT id, json FROM propositions WHERE session_id=?", (session_id,)):
        try:
            _check_proposition_evidence(conn, row, _loads(j) or {})
        except WriterError as e:
            _hit("propositions", rid, e)
    out.extend(_turn_reversal_rows(conn, session_id))
    if _envelope_unbound_refs(conn, session_id, env):
        out.append(("sessions", session_id, "ENVELOPE_REFERENCE_UNBOUND"))
    # V70 (Audit10 §3/§4/§7): scope, event position, double commit - then every row that depends on a listed row
    have = {(t_, i_) for t_, i_, _c in out}
    for hit in _scope_rows(conn, row) + _position_rows(conn, session_id) + _duplicate_commit_rows(conn, session_id):
        if (hit[0], hit[1]) not in have:
            out.append(hit)
            have.add((hit[0], hit[1]))
    out.extend(_dependent_rows(conn, session_id, {(t_, i_) for t_, i_, _c in out if t_ != "sessions"}))
    return out


def _stored_history_turn(conn: sqlite3.Connection, session_id: str) -> int:
    """The highest `turn` the stored history of a session carries (dialogue lines, SceneFacts, God facts). Read only."""
    best = 0
    for table in ("turns", "scene_facts", "god_facts"):
        for (j,) in conn.execute(f"SELECT json FROM {table} WHERE session_id=?", (session_id,)):
            t = (_loads(j) or {}).get("turn") if j else None
            if isinstance(t, int) and not isinstance(t, bool) and t > best:
                best = t
    return best


def write_boundary_audit(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """V65Y (Gesamtpruefung V65X P0-4; AMASTER §6.2 fail-closed, §34.3 "Historische Evidenz wird nicht heimlich
    geloescht"): the stored rows of one session that the current write boundary would not accept as new rows - legacy
    data from earlier versions (e.g. a source turn that was never stored, an ID that is no figure). Read only: nothing is deleted,
    rewritten or re-classified; the diagnosis shows them. {"altzeilen": n, "codes": {code: n}, "beispiele": [...]}.
    V67: the rows come from `_boundary_rows` (the same rules as the writers and `dependency_guard`)."""
    if conn.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone() is None:
        return {"altzeilen": 0, "codes": {}, "beispiele": []}
    rows = _boundary_rows(conn, session_id)
    codes: dict[str, int] = {}
    for _t, _i, c in rows:
        codes[c] = codes.get(c, 0) + 1
    ex = [{"table": t, "id": i, "code": c} for t, i, c in rows[:8]]
    # V66 (Audit5 E03): imported rows and the God/Regie authority the owner accepted with an import - visible, not Altzeilen
    imp = aut = 0
    for table in ("scene_facts", "god_facts", "turn_truth", "turns", "memories", "propositions", "goals", "relationships"):
        for (j,) in conn.execute(f"SELECT json FROM {table} WHERE session_id=?", (session_id,)):
            st = (_loads(j) or {}).get("importiert") if j else None
            if isinstance(st, dict):
                imp += 1
                aut += 1 if st.get("autoritaet") else 0
    return {"altzeilen": len(rows), "codes": codes, "beispiele": ex, "importiert": imp, "importierteAutoritaet": aut}


@contextlib.contextmanager
def dependency_guard(conn: sqlite3.Connection, session_ids: Any, op: str, *, allowed: Any = None):
    """V67 (Audit7 "eine gemeinsame, atomare Abhaengigkeitspruefung fuer Anlegen, Aendern, Importieren, Duplizieren, Snapshot,
    Wiederherstellen, Zuruecksetzen und Loeschen"; AMASTER §34.2, §34.3 "Historische Evidenz wird nicht heimlich geloescht",
    §68 Nr. 34, 64, 66, 87; Kettenvertrag §6): an operation that removes or replaces rows of a session must not leave a row
    behind that the write boundary would refuse - a SceneFact whose Quellturn or upload is gone, a witness row whose fact is
    gone, an open input without its TurnTruth. The rows the boundary refuses are read before and after the operation
    (`_boundary_rows`, the same rules as the writers); a row that was valid before and is not after refuses the whole
    operation: 409 DEPENDENCY_BROKEN, rolled back to the savepoint, nothing changed. Rows that were legacy before stay as they
    were (no migration). `allowed()` names rows the operation itself restores knowingly (snapshot restore: counted)."""
    sids = [str(x) for x in dict.fromkeys(session_ids or []) if x]
    before = {sid: {(t, i) for t, i, _c in _boundary_rows(conn, sid)} for sid in sids}
    sp = "dep_" + secrets.token_hex(4)
    conn.execute(f"SAVEPOINT {sp}")
    try:
        yield
        ok = {(str(t), str(i)) for t, i in (allowed() if callable(allowed) else [])}
        broken: list[tuple[str, str, str]] = []
        for sid in sids:
            if conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone() is None:
                continue   # the session itself is gone (its rows went with it, ON DELETE CASCADE)
            # V70: a row listed only because it depends on a listed row (QUELLE_ALTBESTAND) is no break of its own - an
            # operation that newly breaks the row it depends on is refused for that row
            broken += [r for r in _boundary_rows(conn, sid) if (r[0], r[1]) not in before[sid] and (r[0], r[1]) not in ok
                       and r[2] != "QUELLE_ALTBESTAND"]
        if broken:
            shown = "; ".join(f"{t} {i} {c}" for t, i, c in broken[:6])
            raise WriterError(f"{op} would leave {len(broken)} row(s) without their dependency ({shown}); nothing was changed",
                              409, "DEPENDENCY_BROKEN")
    except BaseException:
        conn.execute(f"ROLLBACK TO {sp}")
        conn.execute(f"RELEASE {sp}")
        raise
    else:
        conn.execute(f"RELEASE {sp}")


def append_session_fact(
    conn: sqlite3.Connection,
    session_id: str,
    body: Any,
    actor: str,
    *,
    on_conflict: str = "reject",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    row = _require_owned_session(conn, session_id, actor)
    data, cid = _child_item(body, "fact")
    payload = _canon_from_session(data, row, {"id": cid})
    if _select_json(conn, "scene_facts", cid) is None:
        try:
            _check_fact_boundary(conn, row, payload)   # V65Y: new rows only, every path
            _check_duplicate_commit(conn, row, payload, cid)   # V70 (Audit10 §7 Nr. 4)
            _check_turn_not_behind(conn, row, payload)          # V70 (Audit10 §7 Nr. 4 "Zeitruecklauf")
        except WriterError as e:
            _bv = _boundary_violation("scene_facts", cid, e)
            if _bv == "quarantined":
                return {"ok": True, "fact": payload, "write": "quarantined"}
            if _bv != "kept":
                raise
    status = _append_immutable_child(
        conn,
        "scene_facts",
        cid,
        payload,
        _scope_columns(row),
        "SCENEFACT_IMMUTABLE",
        on_conflict=on_conflict,
        warnings=warnings,
    )
    _touch_session(conn, session_id)
    return {"ok": True, "fact": payload, "write": status}


def append_session_turn(
    conn: sqlite3.Connection,
    session_id: str,
    body: Any,
    actor: str,
    *,
    on_conflict: str = "reject",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    row = _require_owned_session(conn, session_id, actor)
    data, cid = _child_item(body, "turn")
    # V1-Restnaht: Die fachliche Intra-Turn-Reihenfolge gehoert in die
    # persistierte Turn-Payload. Bei bereits vorhandenen Legacy-Zeilen wird
    # nichts nachtraeglich umgeschrieben; neue Zeilen erhalten die naechste
    # Append-Position innerhalb ihres Turnindex.
    existing = _select_json(conn, "turns", cid)
    if existing is None:
        # Writer owns the ordinal; a client-supplied value cannot reorder canon.
        data["turnOrder"] = _turn_append_order(conn, session_id, int(data.get("turn") or 0))
    payload = _canon_from_session(data, row, {"id": cid})
    if existing is None:
        try:
            _check_ids(conn, row, payload, ("speakerId",), system=SYSTEM_SPEAKER_IDS | _operator_ids(),
                       code="TURN_SPEAKER_UNBOUND")   # V65Y; Bedienperson: _operator_ids
        except WriterError as e:
            _bv = _boundary_violation("turns", cid, e)
            if _bv == "quarantined":
                return {"ok": True, "turn": payload, "write": "quarantined"}
            if _bv != "kept":
                raise
    status = _append_immutable_child(
        conn,
        "turns",
        cid,
        payload,
        _scope_columns(row),
        "TURN_IMMUTABLE",
        on_conflict=on_conflict,
        warnings=warnings,
    )
    _touch_session(conn, session_id)
    return {"ok": True, "turn": payload, "write": status}


def append_session_god_fact(
    conn: sqlite3.Connection,
    session_id: str,
    body: Any,
    actor: str,
    *,
    on_conflict: str = "reject",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    row = _require_owned_session(conn, session_id, actor)
    data, cid = _child_item(body, "godFact")
    payload = _canon_from_session(data, row, {"id": cid})
    if _select_json(conn, "god_facts", cid) is None:
        try:
            _check_god_fact_boundary(conn, row, payload)   # V65Y
        except WriterError as e:
            _bv = _boundary_violation("god_facts", cid, e)
            if _bv == "quarantined":
                return {"ok": True, "godFact": payload, "write": "quarantined"}
            if _bv != "kept":
                raise
    status = _append_immutable_child(
        conn,
        "god_facts",
        cid,
        payload,
        _scope_columns(row),
        "GODFACT_IMMUTABLE",
        on_conflict=on_conflict,
        warnings=warnings,
    )
    _touch_session(conn, session_id)
    return {"ok": True, "godFact": payload, "write": status}


def append_session_turn_truth(
    conn: sqlite3.Connection,
    session_id: str,
    body: Any,
    actor: str,
    *,
    on_conflict: str = "reject",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    row = _require_owned_session(conn, session_id, actor)
    data, cid = _child_item(body, "turnTruth")
    payload = _canon_from_session(data, row, {"id": cid})
    if _select_json(conn, "turn_truth", cid) is None:
        try:
            _check_turn_truth_boundary(conn, row, payload)   # V65Z (A02)
        except WriterError as e:
            _bv = _boundary_violation("turn_truth", cid, e)
            if _bv == "quarantined":
                return {"ok": True, "turnTruth": payload, "write": "quarantined"}
            if _bv != "kept":
                raise
    status = _append_immutable_child(
        conn,
        "turn_truth",
        cid,
        payload,
        _scope_columns(row),
        "TURNTRUTH_IMMUTABLE",
        on_conflict=on_conflict,
        warnings=warnings,
    )
    _touch_session(conn, session_id)
    return {"ok": True, "turnTruth": payload, "write": status}


# B.19 (AMASTERv2 §39): WitnessKnowledge als eigene Tabelle.
# Append-only: Wissen wächst, wird nicht überschrieben.
def append_witness_knowledge(
    conn: sqlite3.Connection,
    session_id: str,
    body: Any,
    actor: str,
    *,
    on_conflict: str = "skip",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    row = _require_owned_session(conn, session_id, actor)
    data, cid = _child_item(body, "wk")
    payload = _canon_from_session(data, row, {"id": cid})
    if _select_json(conn, "witness_knowledge", cid) is None:
        try:
            _check_witness_boundary(conn, row, payload)   # V65Z
        except WriterError as e:
            _bv = _boundary_violation("witness_knowledge", cid, e)
            if _bv == "quarantined":
                return {"ok": True, "witness": payload, "write": "quarantined"}
            if _bv != "kept":
                raise
    # B.19 Idempotenz: gleiche (character, fact, access)-Kombination
    # ist semantisch dasselbe Wissen — kein Duplikat.
    char_id = str(payload.get("characterId") or payload.get("character_id") or "")
    fact_id_s = str(payload.get("factId") or payload.get("fact_id") or "")
    access_s = str(payload.get("access") or "")
    existing_dup = conn.execute(
        "SELECT id FROM witness_knowledge WHERE session_id=? AND character_id=? AND fact_id=? AND access=?",
        (session_id, char_id, fact_id_s, access_s),
    ).fetchone()
    if existing_dup is not None:
        if warnings is not None:
            warnings.append(
                f"witness_knowledge (char={char_id}, fact={fact_id_s}, access={access_s}) bereits vorhanden, skip"
            )
        return {"ok": True, "witness": payload, "write": "idempotent"}
    status = _append_immutable_child(
        conn,
        "witness_knowledge",
        cid,
        payload,
        _scope_columns(row),
        "WITNESS_IMMUTABLE",
        on_conflict=on_conflict,
        warnings=warnings,
    )
    # B.19: zusätzlich charakter/fact/Spalten für SQL-Filterbarkeit.
    conn.execute(
        "UPDATE witness_knowledge SET character_id=?, fact_id=?, access=?, source_turn_id=?, turn=? WHERE id=?",
        (
            str(payload.get("characterId") or payload.get("character_id") or ""),
            str(payload.get("factId") or payload.get("fact_id") or ""),
            str(payload.get("access") or ""),
            str(payload.get("sourceTurnId") or payload.get("source_turn_id") or ""),
            int(payload.get("turn") or 0),
            cid,
        ),
    )
    _touch_session(conn, session_id)
    return {"ok": True, "witness": payload, "write": status}


def upsert_witness_knowledge(
    conn: sqlite3.Connection,
    session_id: str,
    body: Any,
    actor: str,
    *,
    on_conflict: str = "skip",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """B.19: wie append_witness_knowledge, aber generiert ID falls fehlt.

    Praktisch für pipeline- und kernel-Aufrufer, die kein explizites
    id-Feld setzen wollen.
    """
    data = _body_dict(body, "wk")
    if not data.get("id"):
        data["id"] = uid("wk")
    return append_witness_knowledge(
        conn, session_id, data, actor, on_conflict=on_conflict, warnings=warnings,
    )


def create_session_memory(
    conn: sqlite3.Connection,
    session_id: str,
    body: Any,
    actor: str,
    *,
    on_conflict: str = "reject",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    row = _require_owned_session(conn, session_id, actor)
    data, cid = _child_item(body, "memory")
    payload = _canon_from_session(data, row, {"id": cid})
    if _select_json(conn, "memories", cid) is None:
        try:
            _check_memory_boundary(conn, row, payload)   # V65Y owner; V68 (Audit8 P0-5) its named fact and Quellturn
        except WriterError as e:
            _bv = _boundary_violation("memories", cid, e)
            if _bv == "quarantined":
                return {"ok": True, "memory": payload, "write": "quarantined"}
            if _bv != "kept":
                raise
    status = _create_mutable_child(
        conn,
        "memories",
        cid,
        payload,
        _scope_columns(row),
        on_conflict=on_conflict,
        warnings=warnings,
    )
    _touch_session(conn, session_id)
    return {"ok": True, "memory": payload, "write": status}


def patch_session_memory(
    conn: sqlite3.Connection,
    session_id: str,
    memory_id: str,
    body: Any,
    actor: str,
) -> dict[str, Any]:
    row = _require_owned_session(conn, session_id, actor)
    data = _body_dict(body, "memory")
    mrow = conn.execute(
        "SELECT session_id, json FROM memories WHERE id=?", (memory_id,)
    ).fetchone()
    if mrow is None or mrow[0] != session_id:
        raise WriterError("memory not found", 404, "NOT_FOUND")
    existing = _loads(mrow[1]) if mrow[1] else {}
    if not isinstance(existing, dict):
        existing = {"id": memory_id}
    patch = dict(data)
    patch.pop("id", None)
    merged = _canon_from_session({**existing, **patch}, row, {"id": memory_id})
    _check_patch_ids(conn, row, existing, merged, ("characterId",), code="MEMORY_OWNER_UNBOUND")   # V65Z (A03)
    _preserve_stored_position(merged, existing)
    _update_json(conn, "memories", memory_id, merged, extra=_scope_columns(row))
    _touch_session(conn, session_id)
    return {"ok": True, "memory": merged}


def _check_proposition_evidence(conn: sqlite3.Connection, row: sqlite3.Row, payload: dict[str, Any],
                                existing: dict[str, Any] | None = None) -> None:
    """V70 (Audit10 §7 Nr. 4 "Jede negative Mutation muss in beiden Pruefungen nachweisbar scheitern"; AMASTER §34.2, §35): the
    evidence a proposition records names facts of this session (V69: only the independent checker looked). On a patch only the
    entries it adds are checked (stored evidence is not re-judged)."""
    old = {str(e.get("factId")) for e in (existing or {}).get("evidence") or [] if isinstance(e, dict) and e.get("factId")}
    named = [str(e.get("factId")) for e in payload.get("evidence") or [] if isinstance(e, dict) and e.get("factId")]
    new = [f for f in named if f not in old]
    if new:
        facts = _session_sources(conn, row)["fact"]
        bad = [f for f in new if f not in facts]
        if bad:
            raise WriterError(f"proposition evidence names {bad[0]!r}, no fact of this session", 422, "PROPOSITION_SOURCE_INVALID")


def create_session_proposition(
    conn: sqlite3.Connection,
    session_id: str,
    body: Any,
    actor: str,
    *,
    on_conflict: str = "reject",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    row = _require_owned_session(conn, session_id, actor)
    data, cid = _child_item(body, "proposition")
    payload = _canon_from_session(data, row, {"id": cid})
    if _select_json(conn, "propositions", cid) is None:
        try:
            _check_ids(conn, row, payload, ("actorId", "targetId"), system=_operator_ids(),
                       code="PROPOSITION_PERSON_UNBOUND")   # V65Y; Bedienperson: _operator_ids
            _check_proposition_evidence(conn, row, payload)   # V70 (Audit10 §7 Nr. 4)
        except WriterError as e:
            _bv = _boundary_violation("propositions", cid, e)
            if _bv == "quarantined":
                return {"ok": True, "proposition": payload, "write": "quarantined"}
            if _bv != "kept":
                raise
    status = _create_mutable_child(
        conn,
        "propositions",
        cid,
        payload,
        _scope_columns(row),
        on_conflict=on_conflict,
        warnings=warnings,
    )
    _touch_session(conn, session_id)
    return {"ok": True, "proposition": payload, "write": status}


def patch_session_proposition(
    conn: sqlite3.Connection,
    session_id: str,
    prop_id: str,
    body: Any,
    actor: str,
) -> dict[str, Any]:
    row = _require_owned_session(conn, session_id, actor)
    data = _body_dict(body, "proposition")
    prow = conn.execute(
        "SELECT session_id, json FROM propositions WHERE id=?", (prop_id,)
    ).fetchone()
    if prow is None or prow[0] != session_id:
        raise WriterError("proposition not found", 404, "NOT_FOUND")
    existing = _loads(prow[1]) if prow[1] else {}
    if not isinstance(existing, dict):
        existing = {"id": prop_id}
    patch = dict(data)
    patch.pop("id", None)
    merged = _canon_from_session({**existing, **patch}, row, {"id": prop_id})
    _check_proposition_evidence(conn, row, merged, existing)   # V70 (Audit10 §7 Nr. 4): only the entries the patch adds
    _check_patch_ids(conn, row, existing, merged, ("actorId", "targetId"), system=_operator_ids(),
                     code="PROPOSITION_PERSON_UNBOUND")   # V65Z (A03)
    _preserve_stored_position(merged, existing)
    if _json_equal(existing, merged):
        return {"ok": True, "proposition": merged, "write": "unchanged"}   # V65T: no UPDATE without a change
    _update_json(conn, "propositions", prop_id, merged, extra=_scope_columns(row))
    _touch_session(conn, session_id)
    return {"ok": True, "proposition": merged}


def create_session_goal(
    conn: sqlite3.Connection,
    session_id: str,
    body: Any,
    actor: str,
    *,
    on_conflict: str = "reject",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    row = _require_owned_session(conn, session_id, actor)
    data, cid = _child_item(body, "goal")
    payload = _canon_from_session(data, row, {"id": cid})
    if _select_json(conn, "goals", cid) is None:
        try:
            _check_ids(conn, row, payload, ("ownerId", "targetId"), system=_operator_ids(),
                       code="GOAL_PERSON_UNBOUND")   # V65Y; offene Bitte der Bedienperson: _operator_ids
        except WriterError as e:
            _bv = _boundary_violation("goals", cid, e)
            if _bv == "quarantined":
                return {"ok": True, "goal": payload, "write": "quarantined"}
            if _bv != "kept":
                raise
    # An authored goal may be open/active; creating it cannot itself prove
    # acceptance, fulfilment or failure. Use the same canonical evidence reader
    # as updates, including for the existing server-side save_session path.
    requested = payload.get("status") or "open"
    if requested not in ("open", "active", "pending"):
        from matrix_api import kernel
        bound = rehydrate_session_row(conn, row)
        candidate = {**payload, "status": "open"}
        bound["goals"] = [g for g in bound.get("goals") or [] if g.get("id") != cid] + [candidate]
        reduced = next(g for g in kernel.reduce_goal_state(bound) if g.get("id") == cid)
        scope = _SAVE_SCOPE.get()
        kopie = scope is not None and scope.get("sid") == session_id and scope.get("herkunft") == "kopie"
        # V70 (Audit10 §4): a copy (restore, duplicate, import) carries the status its source reduced - it is stored as the
        # evidence of THIS session reduces it (e.g. "unklar" where the copied order is not proven), never refused, never taken over
        if reduced.get("status") != requested and not kopie:
            raise WriterError(
                "Zielabschluss benoetigt gebundene Ereignisevidenz.",
                409, "GOAL_EVIDENCE_REQUIRED",
            )
        payload = reduced
    else:
        payload["status"] = requested
    status = _create_mutable_child(
        conn,
        "goals",
        cid,
        payload,
        _scope_columns(row),
        on_conflict=on_conflict,
        warnings=warnings,
    )
    _touch_session(conn, session_id)
    return {"ok": True, "goal": payload, "write": status}


def patch_session_goal(
    conn: sqlite3.Connection,
    session_id: str,
    goal_id: str,
    body: Any,
    actor: str,
) -> dict[str, Any]:
    row = _require_owned_session(conn, session_id, actor)
    data = _body_dict(body, "goal")
    grow = conn.execute(
        "SELECT session_id, json FROM goals WHERE id=?", (goal_id,)
    ).fetchone()
    if grow is None or grow[0] != session_id:
        raise WriterError("goal not found", 404, "NOT_FOUND")
    existing = _loads(grow[1]) if grow[1] else {}
    if not isinstance(existing, dict):
        existing = {"id": goal_id}
    from matrix_api import kernel
    scope = _SAVE_SCOPE.get()
    in_save = scope is not None and scope.get("sid") == session_id
    if in_save and isinstance(scope.get("goalsReduced"), dict):
        _red = scope["goalsReduced"]
    else:
        # V65T (§35 one goal reducer; Plan v2 Schritt 5): inside a save the goal states are reduced ONCE, from the
        # session as SQL holds it after this save's facts and propositions (before: a full reload per goal, twice).
        session = rehydrate_session_row(conn, row)
        _red = {str(g.get("id")): g for g in kernel.reduce_goal_state(session)}
        if in_save:
            scope["goalsReduced"] = _red
    reduced = _red.get(goal_id, existing)
    requested = data.get("status", reduced.get("status"))
    if requested != reduced.get("status"):
        raise WriterError(
            "Zielstatus folgt gueltiger Ereignisevidenz; ein Statusklick ist kein Ereignis.",
            409, "GOAL_EVIDENCE_REQUIRED",
        )
    patch = dict(data)
    for key in ("id", "status", "lifecycleFactId", "lifecycleTurn"):
        patch.pop(key, None)
    merged = _canon_from_session({**existing, **patch}, row, {"id": goal_id})
    for key in ("status", "lifecycleFactId", "lifecycleTurn"):
        if key in reduced:
            merged[key] = reduced[key]
    _check_patch_ids(conn, row, existing, merged, ("ownerId", "targetId"), system=_operator_ids(),
                     code="GOAL_PERSON_UNBOUND")   # V65Z (A03)
    _preserve_stored_position(merged, existing)
    if not _json_equal(existing, merged):   # V65T: no UPDATE without a change
        _update_json(conn, "goals", goal_id, merged, extra=_scope_columns(row))
        # No synthetic operator achievement and no next-goal activation.
        _touch_session(conn, session_id)
    if in_save:
        return {"ok": True, "goal": merged}   # the save hydrates once at its end
    current = rehydrate_session_row(conn, conn.execute(
        "SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (session_id,)
    ).fetchone())
    return {"ok": True, "goal": merged, "session": current}


def put_session_relation(
    conn: sqlite3.Connection,
    session_id: str,
    body: Any,
    actor: str,
    *,
    on_conflict: str = "reject",
    warnings: list[str] | None = None,
    manual: bool = False,
) -> dict[str, Any]:
    """Current-state directed relation. Identity is session+fromId+toId.
    V65Y (Gesamtpruefung V65X N02): both ends are figures of the session's world, a new relation names its origin
    (_check_relation_boundary). `manual` = the owner's Social UI write (route): client-sent provenance is dropped and the
    server stamps the manual seed (who, when) - never a pretended event."""
    row = _require_owned_session(conn, session_id, actor)
    data = _body_dict(body, "relation")
    if manual:
        data = {k: v for k, v in data.items() if k not in ("provenienz", "sourceFactId", "appliedCauses", "lastChangeReason")}
        data["provenienz"] = {"quelle": "manuell", "durch": str(actor), "am": _now()}
    from_id = data.get("fromId") or data.get("from_id")
    to_id = data.get("toId") or data.get("to_id")
    if not from_id or not to_id:
        raise WriterError("relation missing fromId/toId", 400, "BAD_REQUEST")
    from_id = str(from_id)
    to_id = str(to_id)
    rid = str(data.get("id") or f"{session_id}:{from_id}:{to_id}")
    payload = _canon_from_session(
        data,
        row,
        {"id": rid, "fromId": from_id, "toId": to_id},
    )
    columns = {**_scope_columns(row), "from_id": from_id, "to_id": to_id}

    by_pair = conn.execute(
        "SELECT id, session_id, json FROM relationships WHERE session_id=? AND from_id=? AND to_id=?",
        (session_id, from_id, to_id),
    ).fetchone()
    if by_pair is None or manual:
        # V65Y: new pairs always; an update of a stored pair only from the manual route (the kernel updates stored pairs
        # it bound before - a legacy row is kept readable and listed by the write-boundary audit, not reinterpreted)
        try:
            _check_relation_boundary(conn, row, from_id, to_id, payload, new=by_pair is None)
        except WriterError as e:
            _bv = _boundary_violation("relationships", rid, e)
            if _bv == "quarantined":
                return {"ok": True, "relation": payload, "write": "quarantined"}
            if _bv != "kept":
                raise
    if by_pair is not None:
        rid = by_pair[0]
        payload["id"] = rid
        _preserve_stored_position(payload, by_pair[2])
        if _json_equal(by_pair[2], payload):
            return {"ok": True, "relation": payload, "write": "unchanged"}   # V65T: no UPDATE without a change
        _update_json(conn, "relationships", rid, payload, extra=columns)
        _touch_session(conn, session_id)
        return {"ok": True, "relation": payload, "write": "updated"}

    existing = conn.execute(
        "SELECT id, session_id FROM relationships WHERE id=?", (rid,)
    ).fetchone()
    if existing is None:
        _insert_new(conn, "relationships", rid, payload, columns)
        _touch_session(conn, session_id)
        return {"ok": True, "relation": payload, "write": "inserted"}
    if existing[1] != session_id:
        if on_conflict == "skip":
            if warnings is not None:
                warnings.append(f"relationships id={rid}: existing row kept (other session)")
            return {"ok": True, "relation": payload, "write": "kept"}
        raise WriterError(f"relationships id={rid} exists", 409, "ID_CONFLICT")
    _update_json(conn, "relationships", rid, payload, extra=columns)
    _touch_session(conn, session_id)
    return {"ok": True, "relation": payload, "write": "updated"}


def list_sessions(conn: sqlite3.Connection, actor: str) -> list[Any]:
    items: list[Any] = []
    for r in conn.execute(
        "SELECT id, user_id, world_id, json FROM v_sessions WHERE user_id=? ORDER BY id",
        (actor,),
    ):
        if not world_bindable(conn, actor, r["world_id"]):
            continue
        items.append(rehydrate_session_row(conn, r))   # V70: one hydrate (it was read twice)
    return items


def list_session_evidence(conn: sqlite3.Connection, session_id: str, actor: str) -> dict[str, Any]:
    """Append-only evidence for a session. Identity already overlaid in the view."""
    row = conn.execute(
        "SELECT id, user_id, world_id FROM v_sessions WHERE id=?", (session_id,)
    ).fetchone()
    if row is None:
        raise WriterError("session not found", 404, "NOT_FOUND")
    if not session_owner_ok(row["user_id"], actor):
        raise IsolationError("foreign session")
    items: list[Any] = []
    for r in conn.execute(
        "SELECT layer, json FROM v_session_evidence WHERE session_id=? ORDER BY id",
        (session_id,),
    ):
        obj = _loads(r["json"])
        if not isinstance(obj, dict):
            obj = {}
        obj["layer"] = r["layer"]
        items.append(obj)
    return {"ok": True, "sessionId": session_id, "evidence": items}


# --- uploads ---

def create_upload(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "upload")
    uid = _wid(data, "upload")
    try:
        validate_upload_meta(
            name=str(data.get("name") or uid),
            mime=str(data.get("mime") or ""),
            size=len(str(data.get("text") or "").encode("utf-8")),
        )
    except UploadSecurityError as exc:
        raise WriterError(exc.message, 400, exc.code) from exc
    existing = conn.execute("SELECT user_id FROM uploads WHERE id=?", (uid,)).fetchone()
    if existing is not None:
        _conflict_or_forbidden(existing[0], actor, "upload", "OWNER_FORBIDDEN")
    payload = _canon(data, user_id=actor)
    payload["id"] = uid
    session_id = data.get("sessionId") or data.get("session_id") or payload.get("sessionId")
    if not session_id and str(data.get("targetKind") or payload.get("targetKind") or "") in ("session", "scene"):
        session_id = data.get("targetId") or payload.get("targetId")
    if session_id:
        payload["sessionId"] = str(session_id)
    extra = {"user_id": actor}
    if session_id:
        extra["session_id"] = str(session_id)
    _insert_new(conn, "uploads", uid, payload, extra)
    return {"ok": True, "upload": payload}


def patch_upload(conn: sqlite3.Connection, upload_id: str, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "upload")
    row = conn.execute("SELECT user_id, json FROM uploads WHERE id=?", (upload_id,)).fetchone()
    if row is None:
        raise WriterError("upload not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError("upload not owned by actor", 403, "OWNER_FORBIDDEN")
    existing = _loads(row[1]) if row[1] else {}
    if not isinstance(existing, dict):
        existing = {"id": upload_id}
    patch = dict(data)
    patch.pop("id", None)
    patch.pop("userId", None)
    merged = {**existing, **patch, "id": upload_id, "userId": actor}
    _update_json(conn, "uploads", upload_id, merged)
    return {"ok": True, "upload": merged}


def commit_upload(conn: sqlite3.Connection, upload_id: str, actor: str) -> dict[str, Any]:
    row = conn.execute("SELECT user_id, json FROM uploads WHERE id=?", (upload_id,)).fetchone()
    if row is None:
        raise WriterError("upload not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError("upload not owned by actor", 403, "OWNER_FORBIDDEN")
    existing = _loads(row[1]) if row[1] else {}
    if not isinstance(existing, dict):
        existing = {"id": upload_id}
    existing["committed"] = True
    existing["status"] = "committed"
    existing["id"] = upload_id
    existing["userId"] = actor
    _update_json(conn, "uploads", upload_id, existing)
    return {"ok": True, "upload": existing}


def delete_upload(conn: sqlite3.Connection, upload_id: str, actor: str) -> dict[str, Any]:
    row = conn.execute("SELECT user_id FROM uploads WHERE id=?", (upload_id,)).fetchone()
    if row is None:
        raise WriterError("upload not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError("upload not owned by actor", 403, "OWNER_FORBIDDEN")
    # V67 (Audit7 V66-04): the sessions whose stored facts may name this upload (candidates by text, decided by the guard's
    # exact rules) - an upload that is the source of a SceneFact is not deleted (409 DEPENDENCY_BROKEN, nothing changed)
    sids = [str(r[0]) for r in conn.execute("SELECT DISTINCT session_id FROM scene_facts WHERE json LIKE ?", (f'%"{upload_id}"%',))]
    sids += [str(r[0]) for r in conn.execute("SELECT session_id FROM uploads WHERE id=? AND session_id IS NOT NULL", (upload_id,))]
    with dependency_guard(conn, sids, "delete-upload"):
        conn.execute("DELETE FROM uploads WHERE id=?", (upload_id,))
    return {"ok": True, "deleted": upload_id}


def get_upload(conn: sqlite3.Connection, upload_id: str, actor: str) -> dict[str, Any]:
    return _owned_get(conn, "uploads", upload_id, actor, "upload")


def list_uploads(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    return {"ok": True, "uploads": _owned_list(conn, "uploads", actor)}


def create_document(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "document")
    did = _wid(data, "document")
    existing = conn.execute("SELECT user_id FROM documents WHERE id=?", (did,)).fetchone()
    if existing is not None:
        _conflict_or_forbidden(existing[0], actor, "document", "OWNER_FORBIDDEN")
    payload = _canon(data, user_id=actor)
    payload["id"] = did
    payload["ocrStatus"] = payload.get("ocrStatus") or payload.get("status") or "ready"
    text = str(payload.get("text") or "")
    art = re.search(
        r"(?:artikel(?:nummer)?|art\.?\s*nr\.?|sku|nr\.?)\s*[:#]?\s*([A-Z0-9][-A-Z0-9/]{1,24})",
        text,
        re.I,
    )
    if not payload.get("articleNo") and art:
        payload["articleNo"] = art.group(1)
    payload["documentGroup"] = payload.get("documentGroup") or payload.get("group") or ""
    payload["uploadGroup"] = payload.get("uploadGroup") or payload.get("uploadId") or ""
    if not payload.get("keywords"):
        payload["keywords"] = sorted({w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{4,}", text)})[:24]
    if not payload.get("pages"):
        chunks = [ch.strip() for ch in re.split(r"\f|(?:^|\n)\s*Seite\s+\d+\s*", text) if ch and ch.strip()]
        payload["pages"] = [{"n": i + 1, "text": ch[:2000]} for i, ch in enumerate(chunks[:40])] if chunks else []
    payload.setdefault("slides", [])
    _insert_new(conn, "documents", did, payload, {"user_id": actor})
    rebuild_document_index(conn, did, actor, payload)
    return {"ok": True, "document": payload}


def list_documents(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    return {"ok": True, "documents": _owned_list(conn, "documents", actor)}


def get_document(conn: sqlite3.Connection, doc_id: str, actor: str) -> dict[str, Any]:
    return _owned_get(conn, "documents", doc_id, actor, "document")


def delete_document(conn: sqlite3.Connection, doc_id: str, actor: str) -> dict[str, Any]:
    row = conn.execute("SELECT user_id FROM documents WHERE id=?", (doc_id,)).fetchone()
    if row is None:
        raise WriterError("document not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError("document not owned by actor", 403, "OWNER_FORBIDDEN")
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    purge_document_index(conn, doc_id)
    return {"ok": True, "deleted": doc_id}


def patch_document(conn: sqlite3.Connection, doc_id: str, body: Any, actor: str) -> dict[str, Any]:
    row = conn.execute("SELECT user_id, json FROM documents WHERE id=?", (doc_id,)).fetchone()
    if row is None:
        raise WriterError("document not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError("document not owned by actor", 403, "OWNER_FORBIDDEN")
    existing = _loads(row[1]) if row[1] else {}
    if not isinstance(existing, dict):
        existing = {"id": doc_id}
    data = body if isinstance(body, dict) else {}
    text_changed = "text" in data
    for k in ("title", "text", "documentGroup", "uploadGroup", "articleNo", "keywords", "pages", "slides", "ocrStatus", "note", "zipPath", "partIndex", "sourceKey", "docKind", "zone", "partKind", "layer", "worldId", "anchor", "rev", "previousId", "headId", "supersededBy", "schema"):
        if k in data:
            existing[k] = data[k]
    existing["id"] = doc_id
    existing["userId"] = actor
    if text_changed:
        text = str(existing.get("text") or "")
        if "articleNo" not in data:
            art = re.search(
                r"(?:artikel(?:nummer)?|art\.?\s*nr\.?|sku|nr\.?)\s*[:#]?\s*([A-Z0-9][-A-Z0-9/]{1,24})",
                text,
                re.I,
            )
            existing["articleNo"] = art.group(1) if art else ""
        if "keywords" not in data:
            existing["keywords"] = sorted({w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß0-9]{4,}", text)})[:24]
    _update_json(conn, "documents", doc_id, existing)
    rebuild_document_index(conn, doc_id, actor, existing)
    return {"ok": True, "document": existing}


def _document_index_payload(document_id: str, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "")
    title = str(payload.get("title") or payload.get("name") or "")
    return {
        "id": document_id,
        "userId": user_id,
        "sourceDocumentId": document_id,
        "derivedFrom": "documents",
        "inventsTruth": False,
        "title": title,
        "name": str(payload.get("name") or title),
        "articleNo": payload.get("articleNo") or "",
        "keywords": payload.get("keywords") or [],
        "text": text,
        "excerpt": text[:400],
    }


def rebuild_document_index(
    conn: sqlite3.Connection, document_id: str, user_id: str, payload: dict[str, Any]
) -> None:
    """Derived search index. Not a second document owner."""
    idx = _document_index_payload(document_id, user_id, payload if isinstance(payload, dict) else {})
    conn.execute(
        "INSERT INTO document_index(document_id, user_id, json) VALUES (?,?,?) "
        "ON CONFLICT(document_id) DO UPDATE SET user_id=excluded.user_id, json=excluded.json",
        (document_id, user_id, _dumps(idx)),
    )


def purge_document_index(conn: sqlite3.Connection, document_id: str) -> None:
    conn.execute("DELETE FROM document_index WHERE document_id=?", (document_id,))


def ensure_document_index(conn: sqlite3.Connection, actor: str) -> None:
    if actor == "admin":
        rows = conn.execute("SELECT id, user_id, json FROM documents").fetchall()
    else:
        rows = conn.execute("SELECT id, user_id, json FROM documents WHERE user_id=?", (actor,)).fetchall()
    indexed = {r[0] for r in conn.execute("SELECT document_id FROM document_index")}
    for did, uid_owner, raw in rows:
        if did in indexed:
            continue
        obj = _loads(raw) if raw else {}
        if not isinstance(obj, dict):
            obj = {}
        rebuild_document_index(conn, str(did), str(uid_owner), obj)


def list_document_index(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    ensure_document_index(conn, actor)
    if actor == "admin":
        rows = conn.execute("SELECT json FROM document_index ORDER BY document_id").fetchall()
    else:
        rows = conn.execute(
            "SELECT json FROM document_index WHERE user_id=? ORDER BY document_id", (actor,)
        ).fetchall()
    items = []
    for r in rows:
        obj = _loads(r[0])
        if isinstance(obj, dict):
            items.append(obj)
    return {
        "ok": True,
        "owner": "document_index",
        "derivedFrom": "documents",
        "inventsTruth": False,
        "entries": items,
    }


def search_document_index(conn: sqlite3.Connection, actor: str, q: str) -> dict[str, Any]:
    listed = list_document_index(conn, actor)
    qn = (q or "").strip().lower()
    hits: list[dict[str, Any]] = []
    for entry in listed.get("entries") or []:
        blob = " ".join(
            [
                str(entry.get("title") or ""),
                str(entry.get("name") or ""),
                str(entry.get("articleNo") or ""),
                " ".join(str(x) for x in (entry.get("keywords") or [])),
                str(entry.get("text") or ""),
            ]
        ).lower()
        if qn and qn not in blob:
            continue
        hits.append(
            {
                "kind": "document-index",
                "id": entry.get("sourceDocumentId") or entry.get("id"),
                "sourceDocumentId": entry.get("sourceDocumentId") or entry.get("id"),
                "title": entry.get("title") or "",
                "excerpt": entry.get("excerpt") or "",
                "derivedFrom": "documents",
                "inventsTruth": False,
            }
        )
    return {
        "ok": True,
        "owner": "document_index",
        "derivedFrom": "documents",
        "inventsTruth": False,
        "q": q,
        "hits": hits[:50],
    }


# --- reviews ---

def create_review(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "review")
    rid = _wid(data, "review")
    existing = conn.execute("SELECT user_id FROM reviews WHERE id=?", (rid,)).fetchone()
    if existing is not None:
        _conflict_or_forbidden(existing[0], actor, "review", "OWNER_FORBIDDEN")
    payload = _canon(data, user_id=actor)
    payload["id"] = rid
    _insert_new(conn, "reviews", rid, payload, {"user_id": actor})
    return {"ok": True, "review": payload}


def patch_review(conn: sqlite3.Connection, review_id: str, body: Any, actor: str) -> dict[str, Any]:
    row = conn.execute("SELECT user_id, json FROM reviews WHERE id=?", (review_id,)).fetchone()
    if row is None:
        raise WriterError("review not found", 404, "NOT_FOUND")
    existing = _loads(row[1]) if row[1] else {}
    if not isinstance(existing, dict):
        existing = {"id": review_id}
    world_id = existing.get("worldId") or existing.get("world_id")
    allowed = row[0] == actor
    if not allowed and world_id:
        allowed = _world_owned(conn, str(world_id), actor)
    if not allowed:
        raise WriterError("review not owned by actor", 403, "OWNER_FORBIDDEN")
    if str(existing.get("status") or "open") not in ("open", "pending"):
        raise WriterError("review already resolved", 409, "ALREADY_RESOLVED")
    data = body if isinstance(body, dict) else {}
    for k in ("newValue", "oldValue", "field", "reason"):
        if k in data:
            existing[k] = data[k]
    existing["id"] = review_id
    existing["userId"] = row[0]
    _update_json(conn, "reviews", review_id, existing)
    return {"ok": True, "review": existing}


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s[:1] in "{[":
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return value
    return value


def _dedupe_append(cur: list[Any], items: list[Any]) -> list[Any]:
    out = list(cur)
    seen: set[str] = set()
    for x in out:
        if isinstance(x, dict):
            seen.add(str(x.get("id") or x.get("name") or x).lower())
        else:
            seen.add(str(x).lower())
    for it in items:
        key = str(it.get("id") or it.get("name") or it).lower() if isinstance(it, dict) else str(it).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def resolve_review(conn: sqlite3.Connection, review_id: str, body: Any, actor: str) -> dict[str, Any]:
    data = body if isinstance(body, dict) else {}
    row = conn.execute("SELECT user_id, json FROM reviews WHERE id=?", (review_id,)).fetchone()
    if row is None:
        raise WriterError("review not found", 404, "NOT_FOUND")
    existing = _loads(row[1]) if row[1] else {}
    if not isinstance(existing, dict):
        existing = {"id": review_id}
    world_id = existing.get("worldId") or existing.get("world_id")
    allowed = row[0] == actor
    if not allowed and world_id:
        allowed = _world_owned(conn, str(world_id), actor)
    if not allowed:
        raise WriterError("review not owned by actor", 403, "OWNER_FORBIDDEN")
    status = data.get("status")
    if status is None:
        raise WriterError("resolve requires status", 400, "BAD_REQUEST")
    if "newValue" in data and data.get("newValue") is not None:
        existing["newValue"] = data["newValue"]
    existing["status"] = status
    existing["id"] = review_id
    existing["userId"] = row[0]
    committed = False
    write_error: str | None = None
    if str(status) == "accepted":
        field = existing.get("field")
        new_value = existing.get("newValue")
        kind = existing.get("kind")
        if kind == "spawn" and world_id:
            cand = _parse_jsonish(new_value)
            if not isinstance(cand, dict):
                cand = {"name": str(new_value or "")}
            name = str(cand.get("name") or "").strip()
            if name:
                cid = str(cand.get("id") or uid("char"))
                rels = cand.get("relations")
                if not isinstance(rels, list) or (rels and not isinstance(rels[0], dict)):
                    rels = []
                    for r in cand.get("relationships") or []:
                        if not isinstance(r, dict):
                            continue
                        target = r.get("to") if r.get("from") == name else r.get("from")
                        if not target or target == name:
                            continue
                        rels.append(
                            {
                                "targetName": str(target),
                                "kind": r.get("kind") or "kennt",
                                "note": str(r.get("text") or r.get("note") or "")[:180],
                                "trust": float(r.get("trust") or 0.5),
                                "closeness": float(r.get("closeness") or 0.4),
                                "fear": float(r.get("fear") or 0.1),
                            }
                        )
                try:
                    create_character(
                        conn,
                        {
                            "id": cid,
                            "name": name,
                            "worldId": world_id,
                            "role": cand.get("role") or cand.get("occupation") or "",
                            "origin": cand.get("origin") or "",
                            "biography": cand.get("biography") or "",
                            "personality": cand.get("personality") or "",
                            "appearance": cand.get("appearance") or "",
                            "age": cand.get("age") or "",
                            "gender": cand.get("gender") or "",
                            "occupation": cand.get("occupation") or cand.get("role") or "",
                            "goals": list(cand.get("goals") or []),
                            "fears": list(cand.get("fears") or []),
                            "secrets": list(cand.get("secrets") or []),
                            "values": list(cand.get("values") or []),
                            "knowledge": list(cand.get("knowledge") or []),
                            "taboos": list(cand.get("taboos") or []),
                            "typicalPhrases": list(cand.get("typicalPhrases") or []),
                            "coreFacts": list(cand.get("coreFacts") or cand.get("traits") or []),
                            "aliases": list(cand.get("aliases") or [name]),
                            "relations": rels,
                            "compass": cand.get("compass") if isinstance(cand.get("compass"), dict) else {},
                            "speechRegister": cand.get("speechRegister") or cand.get("speechProfile") or "",
                            "conflictStyle": cand.get("conflictStyle") or "",
                            "typicalPlace": cand.get("typicalPlace") or cand.get("origin") or "",
                            "worldNotes": cand.get("worldNotes") or "",
                            "bindingPatterns": list(cand.get("bindingPatterns") or []),
                            # V25.1 CHAR-01: restliche Frontend-Profilfelder aus dem Kandidaten übernehmen
                            "likes": list(cand.get("likes") or []),
                            "dislikes": list(cand.get("dislikes") or []),
                            "humor": cand.get("humor") or "",
                            "dialect": cand.get("dialect") or "",
                            "favoriteWords": list(cand.get("favoriteWords") or []),
                            "reactionRules": list(cand.get("reactionRules") or []),
                            "lastingAbilities": list(cand.get("lastingAbilities") or []),
                            "fieldProvenance": cand.get("fieldProvenance") if isinstance(cand.get("fieldProvenance"), dict) else (cand.get("provenance") if isinstance(cand.get("provenance"), dict) else {}),
                            "isWorldNative": True,
                            "status": "entwurf",
                            "sourceRefs": [str(cand.get("source") or "review")],
                        },
                        actor,
                    )
                    committed = True
                except WriterError as exc:
                    write_error = str(exc)
        elif field and new_value is not None:
            list_fields = {
                "places",
                "factions",
                "rules",
                "conflicts",
                "items",
                "secrets",
                "beings",
                "history",
                "timeline",
                "worldKnowledge",
                "secretKnowledge",
                "knowledgeBounds",
                "startScenes",
                "storyGoals",
                "fateBeats",
                "figureRelations",
                "culture",
                "language",
                "subplaces",
                "placeRelations",
            }
            if kind == "stamm" and existing.get("characterId"):
                try:
                    stamm_list_fields = {
                        "goals",
                        "fears",
                        "knowledge",
                        "coreFacts",
                        "typicalPhrases",
                        "taboos",
                        "values",
                    }
                    value: Any = new_value
                    if str(field) in stamm_list_fields:
                        char_obj = get_character(conn, str(existing["characterId"]), actor)
                        if isinstance(char_obj, dict) and isinstance(char_obj.get("character"), dict):
                            char_obj = char_obj["character"]
                        cur = char_obj.get(str(field)) if isinstance(char_obj, dict) else []
                        if not isinstance(cur, list):
                            cur = []
                        parsed = _parse_jsonish(new_value)
                        items = parsed if isinstance(parsed, list) else [parsed]
                        value = _dedupe_append(cur, items)
                    patch_character(conn, str(existing["characterId"]), {str(field): value}, actor)
                    committed = True
                except WriterError as exc:
                    write_error = str(exc)
            if kind == "world" and world_id:
                try:
                    if str(field) in list_fields:
                        world_obj = get_world(conn, str(world_id), actor)
                        cur = world_obj.get(str(field)) if isinstance(world_obj, dict) else []
                        if not isinstance(cur, list):
                            cur = []
                        parsed = _parse_jsonish(new_value)
                        items = parsed if isinstance(parsed, list) else [parsed]
                        patch_world(conn, str(world_id), {str(field): _dedupe_append(cur, items)}, actor)
                    else:
                        patch_world(conn, str(world_id), {str(field): new_value}, actor)
                    committed = True
                except WriterError as exc:
                    write_error = str(exc)
        else:
            committed = True
        if write_error:
            existing["status"] = "pending"
            existing["commitError"] = write_error
            _update_json(conn, "reviews", review_id, existing)
            return {"ok": False, "error": "OWNER_WRITE_FAILED", "message": write_error, "review": existing}
        existing["status"] = status
        _update_json(conn, "reviews", review_id, existing)
        _settle_upload_after_review(conn, existing, actor)
        return {"ok": True, "review": existing, "committed": committed}
    existing["status"] = status
    _update_json(conn, "reviews", review_id, existing)
    _settle_upload_after_review(conn, existing, actor)
    return {"ok": True, "review": existing}


def _settle_upload_after_review(conn: sqlite3.Connection, review: dict[str, Any], actor: str) -> None:
    """V25 UPL-A01 (AMASTERv2 §30, Vertrag §13): Ein Mode-A-Upload gilt erst als
    committed, wenn seine Reviews bewusst entschieden wurden und mindestens
    eine Freigabe den Zielowner geschrieben hat. Solange Reviews offen sind,
    bleibt der Upload im Status review_open."""
    upload_id = str(review.get("sourceUploadId") or review.get("source_upload_id") or "")
    if not upload_id:
        return
    urow = conn.execute("SELECT user_id, json FROM uploads WHERE id=?", (upload_id,)).fetchone()
    if urow is None or urow[0] != actor:
        return
    rows = conn.execute("SELECT json FROM reviews WHERE user_id=?", (actor,)).fetchall()
    mine = []
    for r in rows:
        obj = _loads(r[0]) if r[0] else {}
        if isinstance(obj, dict) and str(obj.get("sourceUploadId") or "") == upload_id:
            mine.append(obj)
    if any(str(r.get("status") or "open") in ("open", "pending") for r in mine):
        return
    upload = _loads(urow[1]) if urow[1] else {}
    if not isinstance(upload, dict):
        upload = {"id": upload_id}
    accepted = [r for r in mine if str(r.get("status")) == "accepted"]
    upload["id"] = upload_id
    upload["userId"] = actor
    upload["reviewOpen"] = 0
    upload["reviewAccepted"] = len(accepted)
    upload["reviewResolved"] = len(mine)
    if accepted:
        upload["committed"] = True
        upload["status"] = "committed"
        upload["committedAt"] = _now()
    else:
        upload["committed"] = False
        upload["status"] = "rejected"
    _update_json(conn, "uploads", upload_id, upload)


def set_upload_status(conn: sqlite3.Connection, upload_id: str, actor: str, *, status: str, committed: bool | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """V25: expliziter Statuswriter (analyzed/review_open/failed/committed)."""
    row = conn.execute("SELECT user_id, json FROM uploads WHERE id=?", (upload_id,)).fetchone()
    if row is None:
        raise WriterError("upload not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError("upload not owned by actor", 403, "OWNER_FORBIDDEN")
    existing = _loads(row[1]) if row[1] else {}
    if not isinstance(existing, dict):
        existing = {"id": upload_id}
    existing["status"] = status
    if committed is not None:
        existing["committed"] = bool(committed)
    if extra:
        existing.update(extra)
    existing["id"] = upload_id
    existing["userId"] = actor
    _update_json(conn, "uploads", upload_id, existing)
    return {"ok": True, "upload": existing}


def get_review(conn: sqlite3.Connection, review_id: str, actor: str) -> dict[str, Any]:
    return _owned_get(conn, "reviews", review_id, actor, "review")


def list_reviews(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    return {"ok": True, "reviews": _owned_list(conn, "reviews", actor)}


# --- snapshots ---

# V66 (Audit6 N05; AMASTER §64 "Ein Snapshot enthaelt die fuer den Fortgang benoetigten gebundenen Zustaende",
# "Wiederherstellung darf keine andere Session oder fremde Userdaten ueberschreiben", §6.2 Z. 262 fail-closed, §68 Nr. 87
# "bei unklarer Rolle ... keine kanonische Wirkung", Nr. 91 kein Sonderwrite, G29): a session snapshot is the server's OWN
# capture of the stored session. It carries the stamp `erfasst` {durch: "server", weg, am, inhaltSha256}; restore_snapshot
# restores only a snapshot whose stamp and content hash match. V65Z merged the client's `session` envelope fields (intent,
# sceneMarker, turnIndex 777, pendingInputTurnId of no TurnTruth) into the snapshot, and restore wrote them as truth.
SNAPSHOT_STAMP = "erfasst"


def _snapshot_content_hash(session: dict[str, Any]) -> str:
    """sha256 of the content in its stored JSON form (one round trip first, so the capture and the stored row hash alike)."""
    import hashlib
    norm = json.loads(_dumps(session))
    return hashlib.sha256(json.dumps(norm, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _server_snapshot(conn: sqlite3.Connection, actor: str, session_id: str, *, snap_id: str, name: str, weg: str) -> dict[str, Any]:
    """The ONE snapshot writer of a session: capture the stored session (get_session + its extra children) and stamp it."""
    srow = _session_row(conn, session_id)
    if srow is None:
        raise WriterError("session not found", 404, "NOT_FOUND")
    if not session_owner_ok(srow["user_id"], actor):
        raise WriterError("session not owned by actor", 403, "FORBIDDEN")
    captured = _capture_session_for_snapshot(conn, session_id, actor)
    now = _now()
    # V68 (Audit8 P0-6 "Snapshots mit anfangs ungueltigen Altzeilen und mit abhaengigen Uploads wiederherstellen"): the capture
    # records its OWN rows outside the write boundary at this moment. Only these come back counted on restore; a row that was
    # valid when captured and lacks its dependency now (an upload deleted after a full reset) is no legacy row.
    alt = [[t, i, c] for t, i, c in _boundary_rows(conn, session_id)]
    snap = {"id": snap_id, "sessionId": session_id, "userId": actor, "name": name, "createdAt": now, "session": captured,
            SNAPSHOT_STAMP: {"durch": "server", "weg": weg, "am": now, "inhaltSha256": _snapshot_content_hash(captured),
                             "altzeilen": alt}}
    _insert_new(conn, "snapshots", snap_id, snap, {"user_id": actor, "session_id": session_id})
    return snap


def create_snapshot(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    """POST /api/snapshots: the same server capture as POST /api/sessions/<id>/snapshots. The client names the session and
    a label; a `session` blob or a stamp in the body is ignored (warning), never merged into the snapshot."""
    data = _body_dict(body, "snapshot")
    nid = _wid(data, "snapshot")
    existing = conn.execute("SELECT user_id FROM snapshots WHERE id=?", (nid,)).fetchone()
    if existing is not None:
        _conflict_or_forbidden(existing[0], actor, "snapshot", "OWNER_FORBIDDEN")
    nested = data.get("session") if isinstance(data.get("session"), dict) else {}
    sess_id = data.get("sessionId") or data.get("session_id") or nested.get("id")
    if not sess_id:
        raise WriterError("snapshot missing sessionId", 400, "BAD_REQUEST")
    warnings = ["CLIENT_SESSION_IGNORED"] if ("session" in data or SNAPSHOT_STAMP in data) else []
    snap = _server_snapshot(conn, actor, str(sess_id), snap_id=nid, name=str(data.get("name") or data.get("label") or "Stand"),
                            weg="POST /api/snapshots")
    return {"ok": True, "snapshot": snap, "warnings": warnings}


def _history_turn_index(nested: dict[str, Any]) -> int:
    """The turn index the canonical history of a session carries: the highest `turn` of its dialogue lines, SceneFacts and
    God facts (0 without). V67: facts count too - after a chat reset the lines are gone, the facts stay. V68: one rule with
    the kernel's next turn number (scene_state.history_turn)."""
    from matrix_api import scene_state as _scene
    return _scene.history_turn(nested)


def bind_session_envelope(conn: sqlite3.Connection, srow: sqlite3.Row, env: dict[str, Any], nested: dict[str, Any], *,
                          keep_pending: bool) -> list[str]:
    """V66 (Audit6 N05 "pendingInputTurnId existenz-/Session-gebunden validieren -> turnIndex an kanonische Historie binden ->
    Runtime/SceneState nicht durch Fremdinput als Wahrheit akzeptieren"; AMASTER §23, §34, §42, §6.2 Z. 262): the envelope a
    restore or an import writes is bound to the history it writes with it. turnIndex follows the stored turns; an open input
    names a TurnTruth of THIS history (else it and its attempt are dropped - an import never carries one); the runtimes are
    those of figures of the session's world (else refused). Changes `env` in place, returns warnings."""
    out: list[str] = []
    hist = _history_turn_index(nested)
    if env.get("turnIndex") != hist:
        if "turnIndex" in env:
            out.append(f"TURNINDEX_BOUND_TO_HISTORY:{env.get('turnIndex')!r}->{hist}")
        env["turnIndex"] = hist
    pid = str(env.get("pendingInputTurnId") or "")
    tts = {str(t.get("id")) for t in nested.get("turnTruths") or [] if isinstance(t, dict) and t.get("id")}
    if pid and (not keep_pending or pid not in tts):
        env.pop("pendingInputTurnId", None)
        env.pop("pendingInputAttempt", None)
        out.append("PENDING_INPUT_DROPPED:" + ("import" if not keep_pending else "no TurnTruth of this history"))
    elif not pid and env.get("pendingInputAttempt") is not None:
        env.pop("pendingInputAttempt", None)
    rts = env.get("runtimes")
    if rts is not None:
        cast = {str(r[0]) for r in conn.execute("SELECT id FROM characters WHERE world_id=?", (srow["world_id"],))}
        bad = [k for k in (rts.keys() if isinstance(rts, dict) else ["<keine Zuordnung>"]) if str(k) not in cast]
        if bad:
            raise WriterError(f"runtime of {bad[0]!r}, no figure of this world", 409, "SESSION_RUNTIME_UNBOUND")
    return out


def _legacy_at_capture(conn: sqlite3.Connection, session_id: str, stamp: dict, nested: dict, kept: list) -> list[tuple[str, str]]:
    """V68 (Audit8 P0-6; AMASTER §34.3 "Historische Evidenz wird nicht heimlich geloescht", §6.2 fail-closed): the rows of a
    restore that may come back outside today's boundary - those the capture itself carried outside it. A V68 stamp lists them
    (`altzeilen`). An older stamp does not: then a row whose upload is gone now is no legacy row (the upload lies outside the
    capture; its absence cannot be part of it) - fail-closed; the other counted rows come back as in V66/V67. Read only."""
    rec = stamp.get("altzeilen") if isinstance(stamp, dict) else None
    rows = [(str(k.get("table")), str(k.get("id"))) for k in kept]
    if isinstance(rec, list):
        listed = {(str(x[0]), str(x[1])) for x in rec if isinstance(x, (list, tuple)) and len(x) >= 2}
        return [r for r in rows if r in listed]
    ups = {str(r[0]) for r in conn.execute("SELECT id FROM uploads WHERE session_id=?", (session_id,))}
    facts = {str(f.get("id")): f for f in nested.get("facts") or [] if isinstance(f, dict)}

    def _upload_gone(t: str, i: str) -> bool:
        f = facts.get(i) if t == "scene_facts" else None
        u = (f or {}).get("sourceUploadId") or (f or {}).get("source_upload_id")
        return bool(u) and str(u) not in ups

    return [r for r in rows if not _upload_gone(*r)]


def restore_snapshot(conn: sqlite3.Connection, snap_id: str, actor: str) -> dict[str, Any]:
    row = conn.execute("SELECT user_id, session_id, json FROM snapshots WHERE id=?", (snap_id,)).fetchone()
    if row is None:
        raise WriterError("snapshot not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError("snapshot not owned by actor", 403, "FORBIDDEN")
    snap = _loads(row[2]) if row[2] else {}
    nested = snap.get("session") if isinstance(snap, dict) and isinstance(snap.get("session"), dict) else {}
    session_id = row[1] or (nested.get("id") if nested else None)
    if not session_id:
        raise WriterError("snapshot has no session", 400, "BAD_REQUEST")
    # V66 (Audit6 N05): only the server's own, unchanged capture is restored. A snapshot without the stamp (taken in by an
    # MCC import, or written by an earlier version) stays in the archive - listed, never deleted - but is no restore source.
    stamp = snap.get(SNAPSHOT_STAMP) if isinstance(snap, dict) else None
    if not (isinstance(stamp, dict) and stamp.get("durch") == "server" and stamp.get("inhaltSha256")):
        raise WriterError("snapshot was not captured by this server (archive only, kept)", 409, "SNAPSHOT_NOT_SERVER_CAPTURED")
    if _snapshot_content_hash(nested) != stamp.get("inhaltSha256"):
        raise WriterError("snapshot content differs from its server capture (archive only, kept)", 409, "SNAPSHOT_CONTENT_CHANGED")
    if str(nested.get("id") or "") != str(session_id) or str(nested.get("userId") or actor) != str(row[0]):
        raise WriterError("snapshot content belongs to another session", 409, "SNAPSHOT_SESSION_MISMATCH")
    srow = _session_row(conn, str(session_id))
    if srow is None:
        raise WriterError("session not found", 404, "NOT_FOUND")
    if not session_owner_ok(srow["user_id"], actor):
        raise WriterError("session not owned by actor", 403, "FORBIDDEN")
    nested_world = nested.get("worldId") or nested.get("world_id") if nested else None
    if nested_world:
        nested_world = str(nested_world)
        wrow = _world_row(conn, nested_world)
        if wrow is None:
            raise WriterError("world not found", 404, "NOT_FOUND")
        if not session_world_allowed(nested_world, wrow["owner_user_id"], srow["user_id"]):
            raise WriterError(
                f"snapshot restore must not bind foreign world {nested_world}",
                409,
                "SESSION_WORLD_OWNER_MISMATCH",
            )
    # Snapshot restore is a trusted server-side writer. Do not route the stored
    # canonical snapshot through the public UI PUT contract, whose job is only
    # to accept user-editable session settings. Restore canonical envelope state
    # from the server-owned snapshot while keeping identity/world binding fixed.
    current = _loads(srow["json"]) if srow["json"] else {}
    if not isinstance(current, dict):
        current = {}
    restored = _strip_child_collections(dict(current))
    for key in CANONICAL_ENVELOPE_FIELDS:
        if key in nested:
            restored[key] = nested[key]
    for key in CANONICAL_ENVELOPE_FIELDS:
        if key not in nested:
            restored.pop(key, None)   # the captured state, not a mix with the current one
    restored["id"] = str(session_id)
    restored["userId"] = srow["user_id"]
    restored["worldId"] = srow["world_id"]
    restored["updatedAt"] = _now()
    if not restored.get("createdAt"):
        restored["createdAt"] = current.get("createdAt") or current.get("created_at") or _now()
    warnings = bind_session_envelope(conn, srow, restored, nested, keep_pending=True)   # V66 (N05)
    _assert_figures_in_world(conn, str(srow["world_id"]), _session_figure_ids(restored))
    has_child_payload = any(k in nested for k in CHILD_COLLECTION_KEYS) or any(
        k in nested for k in ("appointments", "graphEdges", "graph_edges")
    )
    kept: list = []
    # V66 (Audit6 N05, G29): the witness rows belong to the captured state as well (V67: SESSION_CHILD_TABLES). V67: the one
    # dependency contract - rows the capture carried outside today's boundary are the counted ones (`kept`). V68 (Audit8
    # P0-6): the envelope is written inside the same guard - a refused restore changes nothing, whatever the caller's
    # transaction (V67 wrote the envelope before the guard; only the route's rollback undid it).
    with dependency_guard(conn, [str(session_id)], "restore-snapshot",
                          allowed=lambda: _legacy_at_capture(conn, str(session_id), stamp, nested, kept)):
        conn.execute(
            "UPDATE sessions SET json=? WHERE id=?",
            (_dumps(restored), str(session_id)),
        )
        if has_child_payload:
            _replace_session_children(conn, str(session_id), actor, nested, keep=kept)
    if kept:
        # V66 (N05; §34.3): rows of the capture outside today's write boundary come back as they were captured - counted
        warnings.append(f"LEGACY_ROWS_RESTORED:{len(kept)}:" + ",".join(sorted({str(x.get('code')) for x in kept})))
    sess = rehydrate_session_row(
        conn,
        conn.execute(
            "SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (str(session_id),)
        ).fetchone(),
    )
    return {"ok": True, "session": sess, "warnings": warnings, "schreibgrenze": write_boundary_audit(conn, str(session_id))}


def delete_snapshot(conn: sqlite3.Connection, snap_id: str, actor: str) -> dict[str, Any]:
    row = conn.execute("SELECT user_id FROM snapshots WHERE id=?", (snap_id,)).fetchone()
    if row is None:
        raise WriterError("snapshot not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError("snapshot not owned by actor", 403, "OWNER_FORBIDDEN")
    conn.execute("DELETE FROM snapshots WHERE id=?", (snap_id,))
    return {"ok": True, "deleted": snap_id}


def get_snapshot(conn: sqlite3.Connection, snap_id: str, actor: str) -> dict[str, Any]:
    return _owned_get(conn, "snapshots", snap_id, actor, "snapshot")


def list_snapshots(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    return {"ok": True, "snapshots": _owned_list(conn, "snapshots", actor)}


# --- triggers ---

def create_trigger(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "trigger")
    tid = _wid(data, "trigger")
    existing = conn.execute("SELECT user_id FROM triggers WHERE id=?", (tid,)).fetchone()
    if existing is not None:
        _conflict_or_forbidden(existing[0], actor, "trigger", "OWNER_FORBIDDEN")
    world_id = data.get("worldId") or data.get("world_id")
    if world_id and not _world_readable(conn, str(world_id), actor):
        raise WriterError("world not readable by actor", 403, "FORBIDDEN")
    payload = _canon(data, user_id=actor)
    payload["id"] = tid
    _insert_new(conn, "triggers", tid, payload, {"user_id": actor})
    return {"ok": True, "trigger": payload}


def patch_trigger(conn: sqlite3.Connection, trigger_id: str, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "trigger")
    row = conn.execute("SELECT user_id, json FROM triggers WHERE id=?", (trigger_id,)).fetchone()
    if row is None:
        raise WriterError("trigger not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError("trigger not owned by actor", 403, "OWNER_FORBIDDEN")
    existing = _loads(row[1]) if row[1] else {}
    if not isinstance(existing, dict):
        existing = {"id": trigger_id}
    patch = dict(data)
    patch.pop("id", None)
    patch.pop("userId", None)
    world_id = patch.get("worldId") or patch.get("world_id") or existing.get("worldId")
    if world_id and not _world_readable(conn, str(world_id), actor):
        raise WriterError("world not readable by actor", 403, "FORBIDDEN")
    merged = {**existing, **patch, "id": trigger_id, "userId": actor}
    _update_json(conn, "triggers", trigger_id, merged)
    return {"ok": True, "trigger": merged}


def delete_trigger(conn: sqlite3.Connection, trigger_id: str, actor: str) -> dict[str, Any]:
    row = conn.execute("SELECT user_id FROM triggers WHERE id=?", (trigger_id,)).fetchone()
    if row is None:
        raise WriterError("trigger not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError("trigger not owned by actor", 403, "OWNER_FORBIDDEN")
    conn.execute("DELETE FROM triggers WHERE id=?", (trigger_id,))
    return {"ok": True, "deleted": trigger_id}


def get_trigger(conn: sqlite3.Connection, trigger_id: str, actor: str) -> dict[str, Any]:
    return _owned_get(conn, "triggers", trigger_id, actor, "trigger")


def list_triggers(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    return {"ok": True, "triggers": _owned_list(conn, "triggers", actor)}


# --- preferences ---

def create_preference(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "preference")
    pid = _wid(data, "preference")
    existing = conn.execute("SELECT user_id FROM preferences WHERE id=?", (pid,)).fetchone()
    if existing is not None:
        _conflict_or_forbidden(existing[0], actor, "preference", "OWNER_FORBIDDEN")
    char_id = data.get("characterId") or data.get("character_id")
    if char_id:
        crow = _char_row(conn, str(char_id))
        if crow is None:
            raise WriterError("character not found", 404, "NOT_FOUND")
        if not _world_readable(conn, crow["world_id"], actor):
            raise WriterError("character world not readable by actor", 403, "FORBIDDEN")
    payload = _canon(data, user_id=actor)
    payload["id"] = pid
    _insert_new(conn, "preferences", pid, payload, {"user_id": actor})
    return {"ok": True, "preference": payload}


def patch_preference(conn: sqlite3.Connection, pref_id: str, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "preference")
    row = conn.execute("SELECT user_id, json FROM preferences WHERE id=?", (pref_id,)).fetchone()
    if row is None:
        raise WriterError("preference not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError("preference not owned by actor", 403, "OWNER_FORBIDDEN")
    existing = _loads(row[1]) if row[1] else {}
    if not isinstance(existing, dict):
        existing = {"id": pref_id}
    patch = dict(data)
    patch.pop("id", None)
    patch.pop("userId", None)
    merged = {**existing, **patch, "id": pref_id, "userId": actor}
    _update_json(conn, "preferences", pref_id, merged)
    return {"ok": True, "preference": merged}


def delete_preference(conn: sqlite3.Connection, pref_id: str, actor: str) -> dict[str, Any]:
    row = conn.execute("SELECT user_id FROM preferences WHERE id=?", (pref_id,)).fetchone()
    if row is None:
        raise WriterError("preference not found", 404, "NOT_FOUND")
    if row[0] != actor:
        raise WriterError("preference not owned by actor", 403, "OWNER_FORBIDDEN")
    conn.execute("DELETE FROM preferences WHERE id=?", (pref_id,))
    return {"ok": True, "deleted": pref_id}


def get_preference(conn: sqlite3.Connection, pref_id: str, actor: str) -> dict[str, Any]:
    return _owned_get(conn, "preferences", pref_id, actor, "preference")


def list_preferences(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    return {"ok": True, "preferences": _owned_list(conn, "preferences", actor)}


# --- config ---

def put_config(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "config")
    scope = str(data.get("scope") or "user")
    if scope not in {"global", "user", "world", "character", "session", "runtime"}:
        raise WriterError("invalid config scope", 400, "BAD_REQUEST")
    raw_id = str(data.get("scope_id") or data.get("scopeId") or "")
    scope_id = _config_scope_id(conn, actor, scope, raw_id, write=True)
    existing = conn.execute(
        "SELECT json FROM config WHERE scope=? AND scope_id=?", (scope, scope_id)
    ).fetchone()
    prev = _loads(existing[0]) if existing and existing[0] else {}
    if not isinstance(prev, dict):
        prev = {}
    stored = dict(data)
    # V25 CFG-01 (AMASTERv2 §60, MATRIX10 Nr. 1, Vertrag §14): Der im Frontend
    # eingegebene API-Key wird gescopt in SQLite gespeichert und vom Backend
    # benutzt. Leeres Feld überschreibt einen gespeicherten Key nicht
    # (Formular ohne Neueingabe); ausdrückliches clearApiKey löscht ihn.
    incoming_key = str(stored.pop("apiKey", None) or stored.pop("api_key", None) or "").strip()
    stored.pop("api_key", None)
    clear_key = bool(stored.pop("clearApiKey", False))
    for leak in ("apiKeyMasked", "apiKeyPresent", "keyPresent", "keySource", "liveModel", "liveStatus"):
        stored.pop(leak, None)
    if clear_key:
        stored.pop("apiKey", None)
    elif incoming_key:
        stored["apiKey"] = incoming_key
    elif prev.get("apiKey"):
        stored["apiKey"] = prev["apiKey"]
    stored["scope"] = scope
    stored["scope_id"] = scope_id
    dumped = _dumps(stored)
    if existing is None:
        conn.execute(
            "INSERT INTO config (scope, scope_id, json) VALUES (?,?,?)",
            (scope, scope_id, dumped),
        )
    else:
        conn.execute(
            "UPDATE config SET json=? WHERE scope=? AND scope_id=?",
            (dumped, scope, scope_id),
        )
    return {"ok": True, "config": public_config_view(stored), "scope": scope, "scope_id": scope_id}


def mask_api_key(key: str | None) -> str:
    k = str(key or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return "•" * len(k)
    return f"{k[:3]}…{k[-4:]}"


def public_config_view(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """Config ohne Klartext-Key (AMASTERv2 §60/§67): nur Vorhandensein + Maske."""
    data = dict(cfg) if isinstance(cfg, dict) else {}
    key = str(data.pop("apiKey", "") or data.pop("api_key", "") or "").strip()
    data.pop("api_key", None)
    data["apiKeyPresent"] = bool(key)
    data["apiKeyMasked"] = mask_api_key(key)
    return data


def get_config(conn: sqlite3.Connection, actor: str, scope: str = "user", scope_id: str | None = None) -> dict[str, Any]:
    if scope not in {"global", "user", "world", "character", "session", "runtime"}:
        raise WriterError("invalid config scope", 400, "BAD_REQUEST")
    sid = _config_scope_id(conn, actor, scope, scope_id or "", write=False)
    row = conn.execute(
        "SELECT json FROM config WHERE scope=? AND scope_id=?", (scope, sid)
    ).fetchone()
    cfg = _loads(row[0]) if row else {}
    return cfg if isinstance(cfg, dict) else {}


def _config_scope_id(conn: sqlite3.Connection, actor: str, scope: str, raw_id: str, *, write: bool) -> str:
    if scope == "global":
        if write and actor != "admin":
            raise WriterError("global config is admin-only", 403, "OWNER_FORBIDDEN")
        return "global"
    if scope == "user":
        return actor
    if not raw_id:
        raise WriterError("scope_id required", 400, "BAD_REQUEST")
    if scope == "world":
        row = conn.execute("SELECT owner_user_id FROM worlds WHERE id=?", (raw_id,)).fetchone()
        if row is None:
            raise WriterError("world not found", 404, "NOT_FOUND")
        if row[0] != actor:
            raise WriterError("foreign world config", 403, "OWNER_FORBIDDEN")
        return raw_id
    if scope in ("session", "runtime"):
        row = conn.execute("SELECT user_id FROM sessions WHERE id=?", (raw_id,)).fetchone()
        if row is None:
            raise WriterError("session not found", 404, "NOT_FOUND")
        if row[0] != actor:
            raise WriterError("foreign session config", 403, "OWNER_FORBIDDEN")
        return raw_id
    if scope == "character":
        row = conn.execute("SELECT json FROM characters WHERE id=?", (raw_id,)).fetchone()
        if row is None:
            raise WriterError("character not found", 404, "NOT_FOUND")
        obj = _loads(row[0]) if row else {}
        wid = obj.get("worldId") if isinstance(obj, dict) else None
        wrow = conn.execute("SELECT owner_user_id FROM worlds WHERE id=?", (wid,)).fetchone() if wid else None
        owner = wrow[0] if wrow else None
        if owner != actor:
            raise WriterError("foreign character config", 403, "OWNER_FORBIDDEN")
        return raw_id
    return raw_id


# --- logs (append-only) ---

def create_log(conn: sqlite3.Connection, body: Any, actor: str) -> dict[str, Any]:
    data = _body_dict(body, "log")
    data = _redact_secrets(data)
    # R4.1: logs are canonical persisted rows as well; reject frontend tmp_* ids.
    lid = _wid(data, "log")
    existing = conn.execute("SELECT user_id, json FROM logs WHERE id=?", (lid,)).fetchone()
    if existing is not None:
        if existing[0] != actor:
            raise WriterError("cannot overwrite a foreign log", 403, "OWNER_FORBIDDEN")
        existing_obj = _loads(existing[1])
        payload_try = _canon(data, user_id=actor)
        payload_try["id"] = lid
        if _json_equal(existing_obj, payload_try):
            return {"ok": True, "log": existing_obj if isinstance(existing_obj, dict) else payload_try}
        raise WriterError("logs are append-only", 409, "LOG_IMMUTABLE")
    payload = _canon(data, user_id=actor)
    payload["id"] = lid
    if not payload.get("at"):
        payload["at"] = _now()
    _insert_new(conn, "logs", lid, payload, {"user_id": actor})
    return {"ok": True, "log": payload}


def get_log(conn: sqlite3.Connection, log_id: str, actor: str) -> dict[str, Any]:
    return _owned_get(conn, "logs", log_id, actor, "log")


def list_logs(conn: sqlite3.Connection, actor: str) -> dict[str, Any]:
    rows = _owned_list(conn, "logs", actor)
    for row in rows:
        if isinstance(row, dict) and row.get("code") in ("MODEL_REQUEST", "MODEL_RESPONSE"):
            for key in ("payload", "response"):
                if key in row:
                    row.pop(key)
                    row["detailAvailable"] = True
    return {"ok": True, "logs": rows}


def delete_orphan_session_logs(conn: sqlite3.Connection, user_id: str, actor: str) -> dict[str, Any]:
    """Explicit, user-scoped deletion of logs referring to absent sessions.

    A log with malformed JSON, no session ID or an empty ID is not treated as
    an orphan. This predicate is also used by the UI statistics endpoint.
    """
    if user_id != actor:
        raise WriterError("cannot delete foreign logs", 403, "LOG_DELETE_FORBIDDEN")
    sid = "(CASE WHEN json_valid(logs.json) THEN COALESCE(json_extract(logs.json,'$.sessionId'), json_extract(logs.json,'$.session_id')) END)"
    predicate = f"""user_id=? AND {sid} IS NOT NULL AND {sid} <> ''
        AND NOT EXISTS (SELECT 1 FROM sessions WHERE sessions.id={sid}
            AND sessions.user_id=?)"""
    cur = conn.execute(f"DELETE FROM logs WHERE {predicate}", (actor, actor))
    remaining = conn.execute(f"SELECT count(*) FROM logs WHERE {predicate}", (actor, actor)).fetchone()[0]
    return {"ok": True, "deletedOrphanSessionLogs": int(cur.rowcount),
            "remainingOrphanSessionLogs": int(remaining), "rowsAffected": int(cur.rowcount)}


def delete_user_logs(conn: sqlite3.Connection, user_id: str, actor: str) -> dict[str, Any]:
    """User-scoped hard-reset of logs. Only self."""
    if user_id != actor:
        raise WriterError("cannot delete foreign logs", 403, "LOG_DELETE_FORBIDDEN")
    conn.execute("DELETE FROM logs WHERE user_id=?", (user_id,))
    return {"ok": True, "deleted": "logs"}


def reset_user_sessions(conn: sqlite3.Connection, user_id: str, actor: str) -> dict[str, Any]:
    """Single-transaction user reset: all sessions of self. Worlds remain."""
    if user_id != actor:
        raise WriterError("cannot reset foreign user sessions", 403, "FORBIDDEN")
    sids = [r[0] for r in conn.execute("SELECT id FROM sessions WHERE user_id=?", (user_id,)).fetchall()]
    deleted: list[str] = []
    for sid in sids:
        delete_session(conn, sid, actor)
        deleted.append(sid)
    return {"ok": True, "kind": "user-reset", "deletedSessions": deleted, "worldsPreserved": True}


def hard_reset_user(conn: sqlite3.Connection, user_id: str, actor: str) -> dict[str, Any]:
    """Single-transaction USER HARD RESET. Self only. Worlds/Stamm remain. One writer."""
    if user_id != actor:
        raise WriterError("cannot hard-reset foreign user", 403, "FORBIDDEN")
    sids = [r[0] for r in conn.execute("SELECT id FROM sessions WHERE user_id=?", (user_id,)).fetchall()]
    deleted_sessions: list[str] = []
    for sid in sids:
        delete_session(conn, sid, actor)
        deleted_sessions.append(sid)
    conn.execute("DELETE FROM uploads WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM logs WHERE user_id=?", (user_id,))
    at = _now()
    lid = f"log_hard_reset_{user_id}_{at}"
    payload = {
        "id": lid,
        "userId": user_id,
        "kind": "hard-reset",
        "code": "HARD_RESET",
        "level": "warn",
        "message": f"USER HARD RESET scoped to {user_id}",
        "at": at,
    }
    _insert_new(conn, "logs", lid, payload, {"user_id": user_id})
    return {
        "ok": True,
        "kind": "hard-reset",
        "deletedSessions": deleted_sessions,
        "worldsPreserved": True,
        "log": payload,
    }


# ---------------------------------------------------------------------------
# B1R2.10 thin adapters (kernel / recovery). Do not weaken B1R2.4/8 writers.
# ---------------------------------------------------------------------------

def upsert_user(conn: sqlite3.Connection, user: dict) -> dict:
    """Keep-or-create. Never overwrite a different existing payload as a foreign write."""
    uid_ = user["id"]
    row = conn.execute("SELECT json FROM users WHERE id=?", (uid_,)).fetchone()
    if row is not None:
        existing = _loads(row[0]) if row[0] else {"id": uid_}
        if isinstance(existing, dict):
            return existing
        return user
    payload = dict(user)
    payload["id"] = uid_
    created = payload.get("createdAt") or payload.get("created_at") or _now()
    payload["createdAt"] = created
    _insert_new(conn, "users", uid_, payload, {"created_at": created})
    return payload


def upsert_world(
    conn: sqlite3.Connection,
    actor_id: str,
    world: dict,
    characters: list | None = None,
) -> dict:
    """Keep-or-create. Foreign owner → IsolationError. No foreign overwrite."""
    if not conn.execute("SELECT id FROM users WHERE id=?", (actor_id,)).fetchone():
        upsert_user(conn, {"id": actor_id, "name": actor_id})
    world = {**world, "ownerUserId": actor_id}
    existing = conn.execute(
        "SELECT owner_user_id, json FROM worlds WHERE id=?", (world["id"],)
    ).fetchone()
    if existing and existing["owner_user_id"] != actor_id:
        raise IsolationError("cannot patch foreign world")
    if existing is None:
        _insert_new(conn, "worlds", world["id"], world, {"owner_user_id": actor_id})
    else:
        merged = {**(_loads(existing["json"]) or {}), **world, "id": world["id"], "ownerUserId": actor_id}
        conn.execute(
            "UPDATE worlds SET json=?, owner_user_id=? WHERE id=?",
            (_dumps(merged), actor_id, world["id"]),
        )
        world = merged
    if characters:
        for c in characters:
            cid = c.get("id")
            if not cid:
                continue
            payload = {**c, "worldId": world["id"]}
            crow = conn.execute("SELECT id FROM characters WHERE id=?", (cid,)).fetchone()
            if crow is None:
                _insert_new(
                    conn,
                    "characters",
                    cid,
                    payload,
                    {"world_id": world["id"], "owner_user_id": actor_id},
                )
    return world


def _safe_child_id(conn: sqlite3.Connection, table: str, sid: str, proposed: str | None, prefix: str) -> str:
    """Stable id for insert. Never steal another session's primary key."""
    if table == "relations":
        table = "relationships"
    cid = (proposed or "").strip() or uid(prefix)
    scope = _SAVE_SCOPE.get()
    own = _scope_own(table)
    if own is not None and scope is not None and scope.get("sid") == sid and cid in own:
        return cid   # V65T: a row of THIS session (read once per save)
    row = conn.execute(f"SELECT session_id FROM {table} WHERE id = ?", (cid,)).fetchone()
    if row and row["session_id"] != sid:
        raise WriterError(
            f"{table} id={cid} already belongs to another session",
            409,
            "SESSION_CHILD_ID_CONFLICT",
        )
    return cid


def _upsert_child(conn: sqlite3.Connection, table: str, columns, values) -> None:
    """INSERT new ids. Same-id SceneFact is NOT rewritten (ON CONFLICT keep)."""
    placeholders = ",".join("?" * len(values))
    col_sql = ",".join(columns)
    conn.execute(
        f"INSERT INTO {table}({col_sql}) VALUES({placeholders}) ON CONFLICT(id) DO NOTHING",
        values,
    )


def _sync_session_children(conn: sqlite3.Connection, actor_id: str, session: dict, *, quarantine: list | None = None,
                           keep: list | None = None, herkunft: str = "live") -> list[str]:
    """Insert NEW child IDs via dedicated writers. NEVER DELETE because omitted.

    Same-id SceneFacts/turns/godFacts are append-only (not rewritten).
    Relations use current-state PUT.
    Propositions and Goals are mutable current-state: same ID is PATCHed.
    WriterError is not swallowed: skip-conflicts go into warnings, hard failures raise.
    """
    sid = session["id"]
    warnings: list[str] = []
    # V70 (Audit10 §4): herkunft "live" (a commit: the writer gives every new row its event position) or "kopie" (duplicate,
    # import, restore: rows keep the position they carry, see _stamp_event_position)
    _token = _SAVE_SCOPE.set({"sid": sid, "actor": actor_id, "row": None, "quarantine": quarantine, "keep": keep,
                              "herkunft": "kopie" if herkunft == "kopie" else "live"})
    try:
        _SAVE_SCOPE.get()["row"] = _require_owned_session(conn, sid, actor_id)   # once, checked as before
        return _sync_session_children_scoped(conn, actor_id, session, sid, warnings)
    finally:
        _SAVE_SCOPE.reset(_token)


def _prevalidate_batch(conn: sqlite3.Connection, scope: dict, session: dict) -> None:
    """V66 (Audit5 E01 "Abhaengigkeit Quarantaene"; AMASTER §34.1, §34.2, §6.2 Z. 262; I63/I66 "abhaengige Effects muessen ihre
    Abhaengigkeiten tragen"): the sources a new row of this save may name are the stored rows and the NEW rows of the same save
    that themselves pass the write boundary. V65Z counted every TurnTruth and SceneFact of the save as a source before they were
    checked - in a duplicate the legacy TurnTruth was quarantined, yet the fact citing it was copied (1 fact, 0 TurnTruths).
    TurnTruths first, then SceneFacts until no further one drops out (a fact citing a dropped fact drops too). Read only."""
    row = scope["row"]
    # V70 (Audit10 §7 Nr. 4): the matters a lifecycle fact of this save may name are the save's own propositions and goals
    # (the facts are written before them)
    scope["matters"] = {"propositions": [p for p in session.get("propositions") or [] if isinstance(p, dict)],
                        "goals": [g for g in session.get("goals") or [] if isinstance(g, dict)]}
    own_tt, own_f = scope["own"]["turn_truth"], scope["own"]["scene_facts"]
    valid_tt: dict[str, Any] = {}
    for x in session.get("turnTruths") or []:
        if not isinstance(x, dict) or not x.get("id") or str(x["id"]) in own_tt:
            continue
        try:
            _check_turn_truth_boundary(conn, row, _canon_from_session(dict(x), row, {"id": str(x["id"])}))
        except WriterError:
            continue
        valid_tt[str(x["id"])] = x
    scope["batchTruthRows"] = valid_tt
    scope["batchTruths"] = set(valid_tt)
    cand = {str(f["id"]): f for f in session.get("facts") or [] if isinstance(f, dict) and f.get("id") and str(f["id"]) not in own_f}
    valid = set(cand)
    while True:
        scope["batchFacts"] = set(valid)
        scope["sources"] = None
        drop = set()
        for fid in valid:
            try:
                _check_fact_boundary(conn, row, _canon_from_session(dict(cand[fid]), row, {"id": fid}))
            except WriterError:
                drop.add(fid)
        if not drop:
            break
        valid -= drop
    scope["sources"] = None


def _sync_session_children_scoped(conn: sqlite3.Connection, actor_id: str, session: dict, sid: str, warnings: list[str]) -> list[str]:
    """V65S: the body of _sync_session_children, inside its save scope.
    V65T: the session's existing child rows are read once per table at the start of the save (scope["own"],
    scope["wk"]); same rows, same decisions, without one SELECT per item."""
    scope = _SAVE_SCOPE.get()
    if scope is not None:
        scope["own"] = {t: {str(r[0]): r[1] for r in conn.execute(f"SELECT id, json FROM {t} WHERE session_id=?", (sid,))}
                        for t in _SCOPE_TABLES}
        scope["wk"] = {(str(r[0]), str(r[1]), str(r[2])) for r in conn.execute(
            "SELECT character_id, fact_id, access FROM witness_knowledge WHERE session_id=?", (sid,))}
        # V65Y: the sources a new row may name include those saved in this same save (one commit, §34.1);
        # V65Z (A01/A02): by kind - TurnTruths (with their content for the God check) and SceneFacts
        _prevalidate_batch(conn, scope, session)   # V66 (Audit5 E01): only rows that pass count as sources of this save
    for f in session.get("facts") or []:
        if not isinstance(f, dict):
            continue
        item = dict(f)
        item["id"] = _safe_child_id(conn, "scene_facts", sid, item.get("id"), "fact")
        append_session_fact(conn, sid, item, actor_id, on_conflict="skip", warnings=warnings)
    for m in session.get("memories") or []:
        if not isinstance(m, dict):
            continue
        item = dict(m)
        item["id"] = _safe_child_id(conn, "memories", sid, item.get("id"), "mem")
        create_session_memory(conn, sid, item, actor_id, on_conflict="skip", warnings=warnings)
    for r in session.get("relations") or []:
        if not isinstance(r, dict):
            continue
        put_session_relation(conn, sid, r, actor_id, on_conflict="skip", warnings=warnings)
    for g in session.get("godFacts") or []:
        if not isinstance(g, dict):
            continue
        item = dict(g)
        item["id"] = _safe_child_id(conn, "god_facts", sid, item.get("id"), "god")
        append_session_god_fact(conn, sid, item, actor_id, on_conflict="skip", warnings=warnings)
    for t in session.get("turns") or []:
        if not isinstance(t, dict):
            continue
        item = dict(t)
        item["id"] = _safe_child_id(conn, "turns", sid, item.get("id"), "ln")
        append_session_turn(conn, sid, item, actor_id, on_conflict="skip", warnings=warnings)
    for tt in session.get("turnTruths") or []:
        if not isinstance(tt, dict):
            continue
        item = dict(tt)
        item["id"] = _safe_child_id(conn, "turn_truth", sid, item.get("id"), "tt")
        append_session_turn_truth(conn, sid, item, actor_id, on_conflict="skip", warnings=warnings)
    for p in session.get("propositions") or []:
        if not isinstance(p, dict):
            continue
        item = dict(p)
        item["id"] = _safe_child_id(conn, "propositions", sid, item.get("id"), "prop")
        existing = (item["id"] in scope["own"]["propositions"]) if scope is not None else conn.execute(
            "SELECT id FROM propositions WHERE id=?", (item["id"],)).fetchone()
        if existing:
            patch_session_proposition(conn, sid, item["id"], item, actor_id)
        else:
            create_session_proposition(conn, sid, item, actor_id, on_conflict="skip", warnings=warnings)
    for g in session.get("goals") or []:
        if not isinstance(g, dict):
            continue
        item = dict(g)
        item["id"] = _safe_child_id(conn, "goals", sid, item.get("id"), "goal")
        existing = (item["id"] in scope["own"]["goals"]) if scope is not None else conn.execute(
            "SELECT id FROM goals WHERE id=?", (item["id"],)).fetchone()
        if existing:
            patch_session_goal(conn, sid, item["id"], item, actor_id)
        else:
            create_session_goal(conn, sid, item, actor_id, on_conflict="skip", warnings=warnings)
    # B.19: witness_knowledge ist append-only. Existierende Einträge werden
    # nicht überschrieben — nur neue werden via append_witness_knowledge
    # persistiert (idempotent über character_id+fact_id+access).
    for w in session.get("witnessKnowledge") or []:
        if not isinstance(w, dict):
            continue
        item = dict(w)
        item["id"] = _safe_child_id(conn, "witness_knowledge", sid, item.get("id"), "wk")
        # Idempotenz: gleicher (character, fact, access) → kein Duplikat.
        _key = (str(item.get("characterId") or item.get("character_id") or ""), str(item.get("factId") or item.get("fact_id") or ""),
                str(item.get("access") or ""))
        if scope is not None:
            if _key in scope["wk"]:
                continue
        elif conn.execute(
            "SELECT id FROM witness_knowledge WHERE session_id=? AND character_id=? AND fact_id=? AND access=?",
            (sid, *_key),
        ).fetchone() is not None:
            continue
        append_witness_knowledge(conn, sid, item, actor_id, on_conflict="skip", warnings=warnings)
        if scope is not None:
            scope["wk"].add(_key)
    hydrate_session_from_sql(conn, session)
    return warnings


PENDING_ATTEMPTS_KEPT = 8


def mark_pending_attempt(conn: sqlite3.Connection, actor: str, session_id: str, turn_truth_id: str, attempt: dict[str, Any]) -> bool:
    """V65T (AMASTER §24.2 verworfene/abgebrochene Effects bleiben Audit, §63; Plan v2 Schritt 6): the orchestration
    status of the formulation attempt for the OPEN input (pendingInputTurnId) - running / provider error / formulated -
    kept in the session envelope only while that input is open. No world truth, no child row; any other turn: no-op.
    V65U (Codegutachten v1 N4): every attempt has its own id and the start id of its server process (boot). Called
    inside the caller's BEGIN IMMEDIATE (app._run_write), so read-modify-write is one transaction. Transitions are per
    attempt and conditional: `laeuft` only creates a NEW attempt id; `provider_fehler` / `formuliert` only end the SAME
    attempt while it is `laeuft`. One attempt never ends another one. Returns whether the transition was written."""
    row = _session_row(conn, session_id)
    if row is None or not session_owner_ok(row["user_id"], actor):
        return False
    env = _loads(row["json"]) if row["json"] else {}
    if not isinstance(env, dict) or str(env.get("pendingInputTurnId") or "") != str(turn_truth_id or "") or not turn_truth_id:
        return False
    aid, state = str(attempt.get("id") or ""), str(attempt.get("state") or "")
    if not aid or state not in ("laeuft", "provider_fehler", "formuliert"):
        return False
    cur = env.get("pendingInputAttempt") if isinstance(env.get("pendingInputAttempt"), dict) else {}
    if str(cur.get("turnTruthId") or "") != str(turn_truth_id) or not isinstance(cur.get("attempts"), list):
        cur = {"turnTruthId": str(turn_truth_id), "attempts": []}
    atts = [a for a in cur["attempts"] if isinstance(a, dict)]
    mine = next((a for a in atts if str(a.get("id") or "") == aid), None)
    if state == "laeuft":
        if mine is not None:
            return False
        atts.append({"id": aid, "boot": str(attempt.get("boot") or ""), "state": "laeuft", "since": attempt.get("since"),
                     **({"lebensnachweis": str(attempt.get("lebensnachweis"))[:20]} if attempt.get("lebensnachweis") else {})})
    else:
        if mine is None or mine.get("state") != "laeuft":
            return False
        mine.update({"state": state, "at": attempt.get("at"), **({"error": str(attempt.get("error") or "")[:120]} if state == "provider_fehler" else {})})
    # V65V (Nachpruefung v1 K5, AMASTER §63): only FINISHED attempts are capped. An attempt of this process still in
    # `laeuft` is the proof that a request is running - it is never dropped by the cap (nine parallel attempts kept
    # the first one running but evicted it).
    # V65W (Tiefenpruefung v1 P05/V05): no process decides here about another one - every attempt still `laeuft`, of any
    # process, is kept (the writer cannot prove that another process ended; that is the reader's proof, app._attempt_alive).
    # Only attempts that ended themselves (formuliert / provider_fehler) are capped. The list ends with its open input.
    live = [a for a in atts if a.get("state") == "laeuft"]
    done = [a for a in atts if a not in live][-PENDING_ATTEMPTS_KEPT:]
    env["pendingInputAttempt"] = {"turnTruthId": str(turn_truth_id), "attempts": [a for a in atts if a in live or a in done]}
    conn.execute("UPDATE sessions SET json=? WHERE id=?", (_dumps(env), session_id))
    return True


def save_session(conn: sqlite3.Connection, actor_id: str, session: dict) -> dict:
    """Envelope create/put + dedicated inserts for NEW child IDs.

    Omission does not delete. Same-ID facts are not rewritten.
    """
    if not conn.execute("SELECT id FROM users WHERE id=?", (actor_id,)).fetchone():
        upsert_user(conn, {"id": actor_id, "name": actor_id})
    existing = conn.execute(
        "SELECT user_id FROM sessions WHERE id = ?", (session["id"],)
    ).fetchone()
    if existing and existing["user_id"] != actor_id:
        raise IsolationError("cannot overwrite foreign session")
    assert_world_bindable(conn, actor_id, session.get("worldId") or "")
    session = {**session, "userId": actor_id}
    body = dict(session)
    # V1: Altstände dürfen einen früheren _id_counters-Key enthalten; er ist
    # ausdrücklich kein persistenter Zustand und wird weiterhin entfernt.
    body.pop("_id_counters", None)
    if existing is None:
        create_session(conn, body, actor_id)
    else:
        # Internal canonical writer: unlike client PUT, kernel-owned envelope
        # fields are allowed here because callers are repository/kernel code,
        # not a browser blob. Preserve omitted fields for slim internal saves.
        row = _session_row(conn, session["id"])
        if row is None:
            raise WriterError("session not found", 404, "NOT_FOUND")
        current = _loads(row["json"]) if row["json"] else {}
        if not isinstance(current, dict):
            current = {}
        merged = _strip_child_collections(dict(current))
        merged.pop("witnessKnowledge", None)   # V65S: an older envelope copy is dropped; the SQL rows stay the owner
        for key in CANONICAL_ENVELOPE_FIELDS:
            if key in body:
                merged[key] = body[key]
        world_id = str(row["world_id"])
        requested_world = body.get("worldId") or body.get("world_id")
        if requested_world and str(requested_world) != world_id:
            raise WriterError(
                "session world binding is immutable after creation",
                409,
                "SESSION_WORLD_IMMUTABLE",
            )
        merged["id"] = session["id"]
        merged["userId"] = actor_id
        merged["worldId"] = world_id
        if not merged.get("createdAt"):
            merged["createdAt"] = current.get("createdAt") or current.get("created_at") or _now()
        merged["updatedAt"] = _now()
        _assert_figures_in_world(conn, world_id, _session_figure_ids(merged))
        conn.execute(
            "UPDATE sessions SET json=? WHERE id=?",
            (_dumps(merged), session["id"]),
        )
    warnings = _sync_session_children(conn, actor_id, session)
    if warnings:
        # Ein abweichender Payload unter derselben kanonischen Child-ID ist
        # kein erfolgreicher idempotenter Save. Im HTTP-Writer führt dieser
        # WriterError zu 409 + Rollback statt zu einem stillen "kept".
        raise WriterError(
            "session child id conflict: " + "; ".join(warnings),
            409,
            "SESSION_CHILD_ID_CONFLICT",
        )
    row = conn.execute(
        "SELECT id, user_id, world_id, json FROM sessions WHERE id=?", (session["id"],)
    ).fetchone()
    return rehydrate_session_row(conn, row)


def export_mcc(conn: sqlite3.Connection, actor_id: str = "", scoped: bool = False) -> dict:
    """MCC snapshot. GET /api/mcc uses scoped=True. Session collections hydrate from SQL."""
    def rows(table: str) -> list:
        return [_loads(r[0]) for r in conn.execute(f"SELECT json FROM {table}").fetchall()]

    def session_rows() -> list:
        out = []
        for r in conn.execute("SELECT id, user_id, world_id, json FROM sessions"):
            out.append(rehydrate_session_row(conn, r, wirksam=False))   # V70: an export copies every stored row
        return out

    if scoped:
        aid = (actor_id or "").strip()
        if not aid:
            return {
                "users": [],
                "activeUserId": "",
                "worlds": [],
                "characters": [],
                "sessions": [],
                "uploads": [],
                "reviews": [],
                "snapshots": [],
                "triggers": [],
                "logs": [],
                "preferences": [],
                "config": {},
            }
        return get_mcc(conn, aid)
    return {
        "users": rows("users"),
        "activeUserId": "admin",
        "worlds": rows("worlds"),
        "characters": rows("characters"),
        "sessions": session_rows(),
        "uploads": rows("uploads"),
        "reviews": rows("reviews"),
        "snapshots": rows("snapshots"),
        "triggers": rows("triggers"),
        "logs": rows("logs"),
        "preferences": rows("preferences"),
        "config": {},
    }


def put_mcc(conn: sqlite3.Connection, blob: dict) -> dict:
    """Forbidden as a live persist writer. Browser blobs are not canonical authority."""
    raise SnapshotForbidden(
        "PUT /api/mcc is not a live persist writer. Use scoped writers or POST /api/import/mcc."
    )


def put_mcc_legacy(conn: sqlite3.Connection, blob: dict) -> dict:
    """HISTORICAL ROT (R-B1-001). Replace-all snapshot writer. Not the product path."""
    blob = blob or {}
    users = blob.get("users") or []
    worlds = blob.get("worlds") or []
    characters = blob.get("characters") or []
    sessions = blob.get("sessions") or []
    if not users and not worlds and not sessions:
        return {"ok": True, "skipped": "empty"}

    for u in users:
        if u.get("id"):
            upsert_user(conn, u)

    incoming_worlds = {w["id"] for w in worlds if w.get("id")}
    for w in worlds:
        owner = w.get("ownerUserId") or blob.get("activeUserId") or "admin"
        if not conn.execute("SELECT id FROM users WHERE id = ?", (owner,)).fetchone():
            upsert_user(conn, {"id": owner, "name": owner})
        chars = [c for c in characters if c.get("worldId") == w["id"]]
        upsert_world(conn, owner, w, chars)

    for row in conn.execute("SELECT id, owner_user_id FROM worlds").fetchall():
        if row["id"] not in incoming_worlds:
            try:
                delete_world(conn, row["id"], row["owner_user_id"])
            except (IsolationError, WriterError):
                continue

    incoming_sessions = {s["id"] for s in sessions if s.get("id")}
    for row in conn.execute("SELECT id, user_id FROM sessions").fetchall():
        if row["id"] not in incoming_sessions:
            try:
                delete_session(conn, row["id"], row["user_id"])
            except (IsolationError, WriterError):
                continue

    for s in sessions:
        uid_user = s.get("userId") or "admin"
        if not conn.execute("SELECT id FROM users WHERE id = ?", (uid_user,)).fetchone():
            upsert_user(conn, {"id": uid_user, "name": uid_user})
        save_session(conn, uid_user, s)

    return {"ok": True, "source": "LOCAL_MCC_LEGACY"}


def add_snapshot(conn: sqlite3.Connection, actor_id: str, session_id: str, name: str) -> dict:
    """POST /api/sessions/<id>/snapshots (UI "Snapshot erstellen"): the server capture (V66: stamped, _server_snapshot)."""
    return _server_snapshot(conn, actor_id, session_id, snap_id=uid("snap"), name=name, weg="POST /api/sessions/<id>/snapshots")
