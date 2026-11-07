"""Private Rust boundary bridge for the existing Matrix10 backend.

This module is not an HTTP API, second backend or datastore. Callers remain the
canonical repository writers and their common dependency/audit checks. There is
NO fallback to the old Python validation when the native module is unavailable.
A missing/invalid library raises a visible 503; no operation is authorized.

Source work only: Rust compilation and end-to-end acceptance are still blocked.
"""
from __future__ import annotations

import ctypes
import math
import struct
import sys
import threading
from pathlib import Path
from typing import Any

ABI = 2
MAGIC = b"MXRB\x01\x00"
MAX_BYTES = 32 * 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 1_000_000
OUTPUT_CAPACITY = 64 * 1024


class NativeBoundaryError(RuntimeError):
    def __init__(self, message: str, code: str = "NATIVE_BOUNDARY_UNAVAILABLE", status: int = 503):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def encode(value: Any) -> bytes:
    """Encode only JSON-compatible values; never trim lists or coerce identities."""
    out = bytearray(MAGIC)
    nodes = 0

    def string(s: str) -> None:
        b = s.encode("utf-8", "strict")
        if len(out) + len(b) + 4 > MAX_BYTES:
            raise NativeBoundaryError("Native transport exceeds 32 MiB; no partial validation", "NATIVE_FRAME_LIMIT")
        out.extend(struct.pack("<I", len(b)))
        out.extend(b)

    def put(v: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise NativeBoundaryError("Native transport nesting/node limit; no partial validation", "NATIVE_FRAME_LIMIT")
        if v is None:
            out.append(0)
        elif v is False:
            out.append(1)
        elif v is True:
            out.append(2)
        elif isinstance(v, int):
            if not -(2**63) <= v < 2**63:
                raise NativeBoundaryError("Integer outside signed 64-bit transport range", "NATIVE_FRAME_LIMIT")
            out.append(3)
            out.extend(struct.pack("<q", v))
        elif isinstance(v, float):
            if not math.isfinite(v):
                raise NativeBoundaryError("Non-finite numeric value", "NATIVE_FRAME_INVALID")
            out.append(4)
            out.extend(struct.pack("<d", v))
        elif isinstance(v, str):
            out.append(5)
            string(v)
        elif isinstance(v, (list, tuple)):
            if len(v) > MAX_NODES - nodes:
                raise NativeBoundaryError("Array exceeds transport node limit", "NATIVE_FRAME_LIMIT")
            out.append(6)
            out.extend(struct.pack("<I", len(v)))
            for item in v:
                put(item, depth + 1)
        elif isinstance(v, dict):
            if len(v) > MAX_NODES - nodes:
                raise NativeBoundaryError("Object exceeds transport node limit", "NATIVE_FRAME_LIMIT")
            out.append(7)
            out.extend(struct.pack("<I", len(v)))
            for key, item in v.items():
                if not isinstance(key, str):
                    raise NativeBoundaryError("Object keys must be strings", "NATIVE_FRAME_INVALID")
                string(key)
                put(item, depth + 1)
        else:
            raise NativeBoundaryError(f"Unsupported native transport type: {type(v).__name__}", "NATIVE_FRAME_INVALID")
        if len(out) > MAX_BYTES:
            raise NativeBoundaryError("Native frame exceeds 32 MiB", "NATIVE_FRAME_LIMIT")

    try:
        put(value, 0)
    except (UnicodeError, OverflowError, struct.error) as exc:
        raise NativeBoundaryError("Invalid value in native transport", "NATIVE_FRAME_INVALID") from exc
    return bytes(out)


def decode(data: bytes) -> Any:
    if len(data) > MAX_BYTES or not data.startswith(MAGIC):
        raise NativeBoundaryError("Invalid native response header", "NATIVE_FRAME_INVALID")
    offset = len(MAGIC)
    nodes = 0

    def take(n: int) -> bytes:
        nonlocal offset
        if n < 0 or offset + n > len(data):
            raise NativeBoundaryError("Truncated native frame", "NATIVE_FRAME_INVALID")
        out = data[offset:offset+n]
        offset += n
        return out

    def length() -> int:
        return struct.unpack("<I", take(4))[0]

    def string() -> str:
        return take(length()).decode("utf-8", "strict")

    def read(depth: int) -> Any:
        nonlocal nodes
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise NativeBoundaryError("Native response complexity limit", "NATIVE_FRAME_LIMIT")
        tag = take(1)[0]
        if tag == 0:
            return None
        if tag in (1, 2):
            return tag == 2
        if tag == 3:
            return struct.unpack("<q", take(8))[0]
        if tag == 4:
            f = struct.unpack("<d", take(8))[0]
            if not math.isfinite(f):
                raise NativeBoundaryError("Non-finite native response", "NATIVE_FRAME_INVALID")
            return f
        if tag == 5:
            return string()
        if tag in (6, 7):
            n = length()
            min_bytes = 1 if tag == 6 else 5
            if n > MAX_NODES - nodes or n > (len(data) - offset) // min_bytes:
                raise NativeBoundaryError("Invalid native collection length", "NATIVE_FRAME_INVALID")
            if tag == 6:
                return [read(depth + 1) for _ in range(n)]
            out = {}
            for _ in range(n):
                key = string()
                if key in out:
                    raise NativeBoundaryError("Duplicate native key", "NATIVE_FRAME_INVALID")
                out[key] = read(depth + 1)
            return out
        raise NativeBoundaryError("Unknown native value tag", "NATIVE_FRAME_INVALID")

    try:
        result = read(0)
        if offset != len(data):
            raise NativeBoundaryError("Trailing native bytes", "NATIVE_FRAME_INVALID")
        return result
    except (UnicodeError, struct.error) as exc:
        raise NativeBoundaryError("Malformed native response", "NATIVE_FRAME_INVALID") from exc


_library: Any = None
_library_lock = threading.Lock()


def library_path() -> Path:
    filename = ("matrix_boundary_core.dll" if sys.platform == "win32" else
                "libmatrix_boundary_core.dylib" if sys.platform == "darwin" else
                "libmatrix_boundary_core.so")
    return Path(__file__).resolve().parent / "native" / filename


def _load() -> Any:
    global _library
    with _library_lock:
        if _library is not None:
            return _library
        path = library_path()
        if not path.is_file():
            raise NativeBoundaryError("Rust-Schreibgrenze fehlt. Dieser Quellstand ist nicht startbereit; keine Speicherung freigegeben.")
        try:
            lib = ctypes.CDLL(str(path))
            lib.matrix_boundary_abi_version.argtypes = []
            lib.matrix_boundary_abi_version.restype = ctypes.c_uint32
            if lib.matrix_boundary_abi_version() != ABI:
                raise NativeBoundaryError("Rust-Schreibgrenze: ABI stimmt nicht ueberein", "NATIVE_ABI_MISMATCH")
            lib.matrix_boundary_check.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_size_t,
                                                  ctypes.POINTER(ctypes.c_ubyte), ctypes.c_size_t]
            lib.matrix_boundary_check.restype = ctypes.c_ssize_t
        except (OSError, AttributeError) as exc:
            raise NativeBoundaryError("Rust-Schreibgrenze konnte nicht geladen werden") from exc
        _library = lib
        return lib


def _native_request(operation: str, context: dict[str, Any], payload: dict[str, Any],
                    options: dict[str, Any] | None = None) -> dict[str, Any]:
    """The only native request path. Fail closed, never synthesize an answer."""
    frame = encode({"operation": operation, "context": context, "payload": payload, "options": options or {}})
    lib = _load()
    source = (ctypes.c_ubyte * len(frame)).from_buffer_copy(frame)
    target = (ctypes.c_ubyte * OUTPUT_CAPACITY)()
    size = int(lib.matrix_boundary_check(source, len(frame), target, OUTPUT_CAPACITY))
    if size <= 0 or size > OUTPUT_CAPACITY:
        raise NativeBoundaryError(f"Native transport failed ({size}); no write or state derived", "NATIVE_TRANSPORT_FAILED")
    reply = decode(bytes(target[:size]))
    if not isinstance(reply, dict) or type(reply.get("ok")) is not bool:
        raise NativeBoundaryError("Native response has no boolean result", "NATIVE_REPLY_INVALID")
    if reply["ok"]:
        if type(reply.get("abi")) is not int or reply.get("abi") != ABI:
            raise NativeBoundaryError("Native response ABI mismatch", "NATIVE_ABI_MISMATCH")
        return reply
    code, message, status = reply.get("code"), reply.get("message"), reply.get("status")
    if not isinstance(code, str) or not isinstance(message, str) or type(status) is not int or status not in (422, 503):
        raise NativeBoundaryError("Native refusal has malformed fields", "NATIVE_REPLY_INVALID")
    raise NativeBoundaryError(message, code, status)


def validate(operation: str, context: dict[str, Any], payload: dict[str, Any], options: dict[str, Any] | None = None) -> None:
    """Only existing writer checks can authorize a commit, never a reader predicate."""
    if operation not in {"fact", "truth", "god", "relation", "witness", "ids", "patch_ids", "sources"}:
        raise NativeBoundaryError("Unknown native writer operation", "NATIVE_CONTRACT_INVALID")
    _native_request(operation, context, payload, options)


def restriction_match(text: str, restriction: str, mode: str) -> bool:
    """A read-only native scope comparison used by existing consent reducers."""
    if type(text) is not str or type(restriction) is not str or mode not in {"same", "exact", "word", "veto"}:
        raise NativeBoundaryError("Invalid restriction query", "NATIVE_CONTRACT_INVALID")
    reply = _native_request("restriction_match", {}, {"text": text, "restriction": restriction}, {"mode": mode})
    if type(reply.get("match")) is not bool:
        raise NativeBoundaryError("Native scope reply has no literal boolean", "NATIVE_REPLY_INVALID")
    return reply["match"]


def _consent_request(giver: str, entries: list[dict[str, Any]], active: list[bool]) -> dict[str, Any]:
    """Canonical event payload: keep ALL committed indices, require each event's
    current time/scene validity. The existing SceneState owner decides that
    window through `_in_window`; Rust decides which evidence is still standing.
    No missing window is silently interpreted as active.
    """
    if (type(giver) is not str or not giver or type(entries) is not list
            or type(active) is not list or len(active) != len(entries)
            or any(type(flag) is not bool for flag in active)):
        raise NativeBoundaryError("Invalid consent reducer input/window mask", "NATIVE_CONTRACT_INVALID")
    fields = ("by", "scope", "kind", "einschraenkung", "einschraenkungOffen")
    prepared = []
    for event, flag in zip(entries, active):
        if (not isinstance(event, dict) or any(k not in event for k in fields)
                or type(event["by"]) is not str or type(event["kind"]) is not str
                or event["scope"] is not None and type(event["scope"]) is not str
                or event["einschraenkung"] is not None and type(event["einschraenkung"]) is not str
                or event["einschraenkungOffen"] is not None and type(event["einschraenkungOffen"]) is not str):
            raise NativeBoundaryError("Invalid canonical consent evidence", "NATIVE_CONTRACT_INVALID")
        prepared.append({"by": event["by"], "kind": event["kind"],
                         "scope": event["scope"] or "", "einschraenkung": event["einschraenkung"] or "",
                         "einschraenkungOffen": event["einschraenkungOffen"] or "", "active": flag})
    return {"giver": giver, "entries": prepared}


def _checked_index(value: Any, entries: list[dict], active: list[bool], giver: str) -> int:
    if (type(value) is not int or value < 0 or value >= len(entries)
            or not active[value] or entries[value].get("by") != giver):
        raise NativeBoundaryError("Native consent result has an unbound evidence index", "NATIVE_REPLY_INVALID")
    return value


def reduce_restricted_refusals(giver: str, entries: list[dict[str, Any]], active: list[bool]) -> list[int]:
    """The Rust current-state reducer returns only canonical evidence indices."""
    payload = _consent_request(giver, entries, active)
    reply = _native_request("restricted_refusals", {}, payload)
    indices = reply.get("indices")
    if type(indices) is not list or indices != sorted(set(x for x in indices if type(x) is int)):
        raise NativeBoundaryError("Native refusal result is not an ordered unique index list", "NATIVE_REPLY_INVALID")
    for index in indices:
        _checked_index(index, entries, active, giver)
        row = entries[index]
        if row.get("scope") != "eingeschraenkt" or row.get("kind") != "refusal" or not row.get("einschraenkung"):
            raise NativeBoundaryError("Native refusal index does not identify a restricted refusal", "NATIVE_REPLY_INVALID")
    return indices


def reduce_restricted_permissions(giver: str, entries: list[dict[str, Any]], active: list[bool]) -> list[int]:
    """Only Rust can declare an active standalone narrow permission."""
    payload = _consent_request(giver, entries, active)
    reply = _native_request("restricted_permissions", {}, payload)
    indices = reply.get("indices")
    if type(indices) is not list or indices != sorted(set(x for x in indices if type(x) is int)):
        raise NativeBoundaryError("Native permission result is not an ordered unique index list", "NATIVE_REPLY_INVALID")
    for index in indices:
        _checked_index(index, entries, active, giver)
        row = entries[index]
        if row.get("scope") != "eingeschraenkt" or row.get("kind") != "acceptance" or not row.get("einschraenkung"):
            raise NativeBoundaryError("Native permission index does not identify a restricted acceptance", "NATIVE_REPLY_INVALID")
    return indices


def reduce_body_contact_standing(giver: str, entries: list[dict[str, Any]], active: list[bool]) -> dict[str, Any]:
    """Broad-standing and its scoped exceptions; Rust owns the state choice.

    Index-only reply; the existing SceneState reader projects validated,
    persisted Fact provenance. This is not a parallel state store.
    """
    payload = _consent_request(giver, entries, active)
    reply = _native_request("body_contact_standing", {}, payload)
    standing = reply.get("standing", "missing")
    if standing is not None:
        _checked_index(standing, entries, active, giver)
        row = entries[standing]
        if row.get("scope") != "jede_beruehrung" or row.get("kind") not in {"acceptance", "refusal"}:
            raise NativeBoundaryError("Native broad boundary points to a non-broad event", "NATIVE_REPLY_INVALID")
    ended = reply.get("ended", "missing")
    if ended is not None:
        if (type(ended) is not list or len(ended) != 2):
            raise NativeBoundaryError("Native consent ending is malformed", "NATIVE_REPLY_INVALID")
        start = _checked_index(ended[0], entries, active, giver)
        finish = _checked_index(ended[1], entries, active, giver)
        if start >= finish:
            raise NativeBoundaryError("Native consent ending order is invalid", "NATIVE_REPLY_INVALID")
        old, last = entries[start], entries[finish]
        if (old.get("scope") != "jede_beruehrung" or old.get("kind") not in {"acceptance", "refusal"}
                or last.get("kind") not in {"acceptance", "refusal", "revoke"}
                or last.get("scope") == "jede_beruehrung"
                or (old.get("kind") == "refusal" and last.get("kind") == "acceptance"
                    and last.get("scope") == "diese_tat")):
            raise NativeBoundaryError("Native consent ending refers to incompatible events", "NATIVE_REPLY_INVALID")
    if standing is not None and ended is not None:
        raise NativeBoundaryError("Native consent replied both standing and ended", "NATIVE_REPLY_INVALID")
    exceptions = reply.get("exceptions")
    if type(exceptions) is not list:
        raise NativeBoundaryError("Native consent exception list missing", "NATIVE_REPLY_INVALID")
    known = set()
    last = -1
    for item in exceptions:
        if type(item) is not dict or set(item) != {"index", "kind"}:
            raise NativeBoundaryError("Malformed native consent exception", "NATIVE_REPLY_INVALID")
        index = _checked_index(item["index"], entries, active, giver)
        row = entries[index]
        kind = item["kind"]
        if (index <= last or kind not in {"acceptance", "refusal", "revoke", "unbestaetigt"}
                or index in known or (standing is not None and index <= standing)):
            raise NativeBoundaryError("Unordered/invalid native consent exception", "NATIVE_REPLY_INVALID")
        if kind == "unbestaetigt":
            valid = bool(row.get("einschraenkungOffen")) and row.get("kind") in {"acceptance", "refusal"}
        else:
            valid = (row.get("scope") == "eingeschraenkt" and bool(row.get("einschraenkung"))
                     and row.get("kind") == kind)
        if not valid:
            raise NativeBoundaryError("Native consent exception does not match original evidence", "NATIVE_REPLY_INVALID")
        last = index
        known.add(index)
    if exceptions and standing is None:
        raise NativeBoundaryError("Unanchored native consent exception", "NATIVE_REPLY_INVALID")
    return {"standing": standing, "ended": ended, "exceptions": exceptions}
