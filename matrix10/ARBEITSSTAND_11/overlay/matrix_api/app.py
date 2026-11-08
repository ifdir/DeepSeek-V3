"""Flask factory for MATRIX10 SQLite master (B1R2.4).

PUT /api/mcc is always 409 SNAPSHOT_OWNER_FORBIDDEN.
Product mutation goes through scoped writers (create vs update separated).
PUT /api/sessions/:id is envelope-only; children use dedicated writers.
"""

from __future__ import annotations

import base64
import copy
import errno
import hashlib
import hmac
import json
import secrets
import os
import socket
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from flask import Flask, g, jsonify, request

from matrix_api.db import connect, db_path, init_schema
from matrix_api.isolation import get_actor, read_actor_raw
from matrix_api import kernel
from matrix_api import llm_contract as _llm_vorab   # Stand 11: Lesungen der ersten Antwort
from matrix_api.native_boundary import NativeBoundaryError   # Stand 06 / K2: Fehler des Rust-Einwilligungskerns
from matrix_api import live_log as matrix_live_log
from matrix_api.analyze import analyze_text
from matrix_api.genre_policy import evaluate_genre
from matrix_api.vector import vector_search
from matrix_api.pipeline import ingest_upload
from matrix_api.llm_contract import (
    analyze_with_llm,
    detect_contradictions,
    extract_god_instructions,
    extract_regie_components,
    check_regie_act_content,
    select_regie_act_labels,
    select_regie_acts,
    extract_turn_plan,
    extract_rule_triggers,
    extract_rule_kinds,
    complete_profiles_from_config,
    derive_compass_from_config,
    enrich_analysis,
    formulate_from_config,
    generate_characters_from_config,
    generate_world_from_config,
    ping_provider,
    provider_status,
    suggest_profile_from_config,
)
from matrix_api.system_loop import run_bound_system
from matrix_api.amaster_ext import (
    create_appointment,
    list_appointments,
    create_graph_edge,
    list_graph_edges,
    recall_patterns,
)
from matrix_api.repos import (
    public_config_view,
    ImportAborted,
    IsolationError,
    SnapshotForbidden,
    WriterError,
    add_snapshot,
    append_session_turn,
    allocate_ids,
    commit_upload,
    create_character,
    create_log,
    create_preference,
    create_review,
    create_session,
    create_session_goal,
    create_session_memory,
    create_session_proposition,
    create_snapshot,
    create_trigger,
    create_upload,
    create_document,
    create_user,
    create_world,
    import_world_pack,
    backup_world,
    list_world_backups,
    restore_world_backup,
    backup_character,
    list_character_backups,
    restore_character_backup,
    delete_character,
    delete_document,
    delete_preference,
    delete_session,
    delete_session_relation,
    delete_snapshot,
    delete_trigger,
    delete_upload,
    delete_user,
    delete_user_logs,
    delete_orphan_session_logs,
    hard_reset_user,
    reset_user_sessions,
    delete_world,
    get_character,
    get_config,
    get_log,
    get_mcc,
    get_preference,
    get_review,
    get_session,
    get_snapshot,
    get_trigger,
    get_upload,
    get_document,
    get_user,
    get_world,
    import_mcc,
    list_characters,
    list_logs,
    list_preferences,
    list_reviews,
    list_sessions,
    list_session_evidence,
    list_snapshots,
    list_triggers,
    list_uploads,
    list_documents,
    list_document_index,
    list_users,
    list_user_directory,
    list_worlds,
    patch_character,
    patch_preference,
    patch_session,
    patch_session_goal,
    patch_session_memory,
    patch_session_proposition,
    patch_trigger,
    patch_upload,
    patch_user,
    patch_world,
    patch_review,
    patch_document,
    put_config,
    put_session,
    put_session_relation,
    reset_session_chat,
    reset_session_full,
    reset_session_memory,
    reset_session_runtime,
    reset_session_uploads,
    resolve_review,
    restore_snapshot,
    save_session,
    search_document_index,
    upsert_user,
)


def _get_conn():
    conn = getattr(g, "_matrix_db", None)
    if conn is None:
        from flask import current_app

        configured = current_app.config.get("MATRIX_DB")
        conn = connect(configured) if configured else connect()
        init_schema(conn)
        g._matrix_db = conn
    return conn


def _json_error(error: str, message: str, status: int, code: str | None = None, details: dict | None = None):
    body = {"ok": False, "error": error, "message": message, "code": code or error}
    if isinstance(details, dict):
        body.update({k: v for k, v in details.items() if k not in body})
    return jsonify(body), status


def _run_write(fn, *, checkpoint_after: bool = False):
    conn = _get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        out = fn(conn)
        conn.commit()
        if checkpoint_after:
            # A session delete or full reset is already committed. The active
            # database uses auto_vacuum=FULL after the one-time safe import.
            # Checkpointing frees SQLite WAL pages without another data write.
            # A busy reader can defer file shrink, not the successful delete.
            try:
                checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if isinstance(out, dict):
                    out["storageCheckpoint"] = (
                        "completed" if checkpoint and checkpoint[0] == 0 else "deferred"
                    )
            except Exception:
                if isinstance(out, dict):
                    out["storageCheckpoint"] = "deferred"
        if isinstance(out, tuple) and len(out) == 2 and isinstance(out[1], int):
            body, status = out
            return jsonify(body), status
        return jsonify(out), 200
    except NativeBoundaryError as exc:
        # Stand 06 / K2 (AMASTER §65 "Fehler duerfen nicht verschluckt werden", fail-closed): the Rust consent core is
        # unavailable or refused its contract - nothing is committed, the client gets 503 with the boundary's code.
        conn.rollback()
        return _json_error(exc.code, exc.message, 503, exc.code)
    except SnapshotForbidden as exc:
        conn.rollback()
        return _json_error("SNAPSHOT_OWNER_FORBIDDEN", str(exc), 409, "SNAPSHOT_OWNER_FORBIDDEN")
    except IsolationError as exc:
        conn.rollback()
        return _json_error(str(exc), str(exc), 403, "ISOLATION")
    except WriterError as exc:
        conn.rollback()
        return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
    except KeyError as exc:
        conn.rollback()
        return _json_error("NOT_FOUND", str(exc), 404, "NOT_FOUND")
    except Exception as exc:
        conn.rollback()
        return _json_error("WRITE_FAILED", str(exc), 500)


_PREPARE_NACH_EINGABE = ("INPUT_COMMITTED", "KERNEL_BIND", "BRAIN_CONTEXT")


def _prepare_teilcommit_antwort(code, body):
    """Stand 06a / M2 (AMASTER §4/§28/§34.1, §65): prepare committed the input BEFORE the consent core failed (its own
    consent was decided inside that transaction with a working core); the reply was not prepared. Say exactly that -
    never "nothing stored", never success. The pending input id is read from the stored session envelope."""
    _pending = None
    try:
        _sid = str((body or {}).get("sessionId") or ((body or {}).get("truth") or {}).get("sessionId") or "")
        _row = _get_conn().execute("SELECT json FROM sessions WHERE id=?", (_sid,)).fetchone()
        _pending = (json.loads(_row[0]) or {}).get("pendingInputTurnId") if _row else None
    except Exception:
        _pending = None
    return _json_error(code,
                       "Eingabe gespeichert. Die Antwort wurde nicht vorbereitet: die Rust-Einwilligungspruefung ist "
                       "waehrend der Wahrnehmungsbewertung/Antwortvorbereitung ausgefallen. Es wurde keine Antwort erzeugt "
                       "und nichts Weiteres freigegeben; die gespeicherte Eingabe bleibt offen (Antwort erneut erzeugen).",
                       503, code, details={"eingabeGespeichert": True, "antwortVorbereitet": False, "sourceTurnId": _pending})


def _run_read(fn):
    conn = _get_conn()
    try:
        out = fn(conn)
        if isinstance(out, tuple) and len(out) == 2 and isinstance(out[1], int):
            body, status = out
            return jsonify(body), status
        return jsonify(out), 200
    except NativeBoundaryError as exc:   # Stand 06 / K2: read path of the consent core unavailable -> 503, no state derived
        return _json_error(exc.code, exc.message, 503, exc.code)
    except IsolationError as exc:
        return _json_error(str(exc), str(exc), 403, "ISOLATION")
    except WriterError as exc:
        return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
    except KeyError as exc:
        return _json_error("NOT_FOUND", str(exc), 404, "NOT_FOUND")


def _body():
    return request.get_json(silent=True)


def authority_from_role(role: str | None) -> str:
    r = (role or "").strip().lower()
    if r == "avatar":
        return "avatar"
    if r == "teilnehmer":
        return "teilnehmer"
    if r == "god":
        return "god"
    if r == "regie":
        return "regie"
    if r in ("beobachter", "observer"):
        return "observer"
    if r == "puppet":
        return "character"
    if r == "autochat":
        return "autochat"
    return r or "observer"


def normal_kernel_authority(session: dict, raw_truth: dict | None = None) -> str:
    """Bind ordinary turns only from the canonical session, not UI role hints.

    A no-new-input figure follow-up stays a *character* turn, even if the
    permanent session UI mode is Regie/God/Puppet/Beobachter and AutoChat
    is switched off (manual 'Figuren weiterreden lassen' is still possible).
    A text-bearing special-authority input must use its own special route.
    """
    role = str((session or {}).get("role") or "teilnehmer").strip().lower()
    raw = raw_truth if isinstance(raw_truth, dict) else {}
    if kernel.is_figure_followup_turn(raw):
        return "character"
    if role in ("god", "regie", "puppet"):
        raise WriterError(
            f"role {role} requires its dedicated kernel route",
            409,
            "SPECIAL_AUTHORITY_ROUTE_REQUIRED",
        )
    return authority_from_role(role)


def _normal_kernel_avatar_user_input(session: dict, truth: dict | None, speaker_id: str | None) -> bool:
    """True only for the explicit user-controlled Avatar input mode.

    The ordinary prepare/commit endpoints model a figure response speaker.
    A participant's own speech is carried by ``inputActorId`` and therefore
    remains valid while the response speaker is another figure.  The Avatar
    itself may only occupy the speaker slot for the dedicated canonical
    ``role=avatar`` / ``speakAs=avatar`` user-input mode; AutoChat can never
    use that exception.
    """
    avatar_id = str((session or {}).get("avatarId") or "")
    sid = str(speaker_id or "")
    if not avatar_id or sid != avatar_id:
        return False
    raw = truth if isinstance(truth, dict) else {}
    role = str((session or {}).get("role") or "teilnehmer").strip().lower()
    input_kind = str(raw.get("input_kind") or raw.get("inputKind") or "speech").strip().lower()
    speak_as = str(raw.get("speak_as") or raw.get("speakAs") or "").strip().lower()
    input_actor = str(raw.get("input_actor_id") or raw.get("inputActorId") or "")
    return role == "avatar" and input_kind != "autochat" and speak_as == "avatar" and input_actor == avatar_id


def _normal_kernel_avatar_output_present(result: dict | None) -> bool:
    """Normal figure output must never manufacture Avatar speech/action."""
    if not isinstance(result, dict):
        return False
    if str(result.get("speech") or "").strip() or str(result.get("action") or "").strip():
        return True
    comps = result.get("components")
    return bool(isinstance(comps, list) and any(isinstance(c, dict) and str(c.get("text") or "").strip() for c in comps))


# V65U (AMASTER §63, Codegutachten v1 N4): the start id of THIS server process. A formulation attempt counts as
# running only while it is `laeuft` under this id; a restart proves the end of every older attempt (no timer).
import uuid as _uuid  # noqa: E402
SERVER_BOOT_ID = _uuid.uuid4().hex[:12]

# ---------------------------------------------------------------------------------------------------------------------
# Stand 07 / K-01 (AMASTER §23 TurnTruth, §28 Schritte 8/16/18-20, §50 "Das LLM formuliert nur"; Kettenvertrag §4 "Der Client
# darf Bedienabsicht, Auswahl und erwartete Revision senden, aber keine kanonischen ... ueberschreiben"; SPS V65U "ein Neustart
# beweist das Ende jedes aelteren Versuchs").
# prepare binds the TurnTruth, /api/llm/formulate re-reads the session and formulates (llm_contract.canonical_formulation_
# context) - but commit took `truth`, `result`, `fired` and `contradictions` from the request body. A Beleg is this server
# process's proof that it issued exactly these values for exactly this session, TurnTruth and turn index. It stores NOTHING
# (no table, no envelope field, no second truth): the data stay in their owners (TurnTruth, pendingInputAttempt, session);
# the key exists only in this process, so a restart ends every unfinished formulation exactly like V65U ends its attempt.
import base64 as _b64  # noqa: E402
import hashlib as _hashlib  # noqa: E402
import hmac as _hmac  # noqa: E402
import secrets as _secrets  # noqa: E402

_BELEG_KEY = _secrets.token_bytes(32)


def _kanon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def beleg_ausstellen(art: str, daten: dict) -> str:
    raw = _kanon({"art": art, "boot": SERVER_BOOT_ID, **daten}).encode("utf-8")
    sig = _hmac.new(_BELEG_KEY, raw, _hashlib.sha256).digest()
    return _b64.urlsafe_b64encode(raw).decode("ascii") + "." + _b64.urlsafe_b64encode(sig).decode("ascii")


def beleg_lesen(art: str, token) -> dict | None:
    """The payload of a Beleg this process issued for `art`, or None (forged, foreign process, other kind)."""
    try:
        raw_b, sig_b = str(token or "").split(".", 1)
        raw = _b64.urlsafe_b64decode(raw_b.encode("ascii"))
        sig = _b64.urlsafe_b64decode(sig_b.encode("ascii"))
    except Exception:
        return None
    if not _hmac.compare_digest(_hmac.new(_BELEG_KEY, raw, _hashlib.sha256).digest(), sig):
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get("art") == art and data.get("boot") == SERVER_BOOT_ID else None


def beleg_hash(token) -> str:
    return _hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def turn_kern(truth: dict) -> dict:
    """The identity of a turn that must not change between prepare, formulate and commit."""
    t = truth if isinstance(truth, dict) else {}

    def g(a, b):
        v = t.get(a) if a in t else t.get(b)
        return "" if v is None else str(v)
    return {"tt": g("id", "id"), "sid": g("session_id", "sessionId"), "speaker": g("speaker_id", "speakerId"),
            "inputActor": g("input_actor_id", "inputActorId"), "target": g("target_id", "targetId"),
            "kind": g("input_kind", "inputKind"), "text": g("text", "text"), "directive": g("directive", "directive")[:300]}


def lesungen_gleichzeitig(db_pfad, aufgaben: dict) -> dict:
    """Stand 10B (Geraet 08.11.: 41-49 s je Austausch; P25 = 10A gemessen, 8-12 Modell-Lesungen NACHEINANDER; AMASTER §28,
    SPS V62 "je Figur ein Modellvorschlag (parallel)", V54/V59C "keine Netzwerkaufrufe unter der Schreibsperre"):
    voneinander unabhaengige Lesungen laufen gleichzeitig - dieselben Aufrufe, dieselben Eingaben, keine Lesung entfaellt.
    Jede Lesung bekommt eine EIGENE SQLite-Verbindung (Konfiguration lesen, Provider-Audit schreiben; autocommit, ausserhalb
    der Schreibsperre), weil eine Verbindung nicht zwischen Threads geteilt wird. Ergebnis je Schluessel: ("ok", wert) oder
    ("fehler", exception) - der Aufrufer behandelt Fehler genau wie zuvor im Ablauf nacheinander."""
    import concurrent.futures as _cf

    def _lauf(f):
        c = connect(db_pfad) if db_pfad else connect()
        try:
            return ("ok", f(c))
        except Exception as exc:   # an den Aufrufer zurueck, dort wie bisher behandelt
            return ("fehler", exc)
        finally:
            c.close()
    if not aufgaben:
        return {}
    with _cf.ThreadPoolExecutor(max_workers=len(aufgaben)) as ex:
        # Stand 11: jede Lesung laeuft im Kontext dieser Anfrage (Lesungen aus der ersten Antwort, llm_contract._VORAB_CTX)
        import contextvars as _cv
        futs = {k: ex.submit(_cv.copy_context().run, _lauf, f) for k, f in aufgaben.items()}
        return {k: fu.result() for k, fu in futs.items()}


def _braucht_sprache(plan) -> bool:
    """Dieselbe Vorbedingung wie _read_language: eine reine Tat ohne Rede legt keinen Namen fest."""
    if not isinstance(plan, dict):
        return False
    comps = plan.get("komponenten") if isinstance(plan.get("komponenten"), list) else []
    has_speech = any(isinstance(c, dict) and str(c.get("typ") or "").lower() == "rede" for c in comps)
    return not (str(plan.get("event_kind") or "") == "action" and not has_speech)


def _vorab_oder(vorab: dict, key: str, sofort):
    """Wert einer gleichzeitig gelaufenen Lesung (Fehler wird hier erneut ausgeloest) oder - ohne Vorablesung - die Lesung jetzt."""
    if key in vorab:
        status, wert = vorab[key]
        if status == "fehler":
            raise wert
        return wert
    return sofort()


def formulierung_kern(result) -> dict:
    """What a commit takes from a formulation: the figure's speech, action and the model's proposals."""
    r = result if isinstance(result, dict) else {}
    props = r.get("proposals") if isinstance(r.get("proposals"), dict) and r.get("proposals") else None
    act = r.get("action")
    return {"speech": str(r.get("speech") or ""), "action": (str(act) if act not in (None, "") else None), "proposals": props}


def formulierung_leer(result) -> bool:
    k = formulierung_kern(result)
    comps = (result or {}).get("components") if isinstance(result, dict) else None
    return not k["speech"].strip() and not (k["action"] or "").strip() and not k["proposals"] and not comps


def autochat_sprecher(session: dict, natives: list, bound: dict, requested: str) -> dict:
    """Stand 10 / F2 (AMASTER §28 Schritt 16, §27.5/§46.6, §48; KV §12.5/§12.6): who may speak in a turn WITHOUT user input
    (inputKind autochat). Only server-canonical choices, each from the stored session:
    - gewaehlt: the figure the kernel picks from the latest committed event - the SAME call as kernel.autochat_gate
      (latest_event_stimulus + pick_speaker(autochat=True, affected_ids)), so gate and turn cannot diverge;
    - betroffen/adressiert: a present figure the latest committed event affected or was bound to (its canonical targetId) -
      the UI's reaction of the addressee after a Puppet act (chat.$sessionId.tsx), now checked against stored facts;
    - regie: the figure a stored Regie row ordered with exactly this directive (kernel.regie_order_for / directiveFor).
    Everything else is refused - the client's speaker is a request, never the decision."""
    req = str(requested or "")
    ev_text, ev_aff = kernel.latest_event_stimulus(session)
    stim = ev_text if ev_text is not None else str(bound.get("text") or "")
    chosen = kernel.pick_speaker(session, natives, stim, autochat=True, affected_ids=ev_aff)
    chosen_id = str((chosen or {}).get("id") or "")
    if req and req == chosen_id:
        return {"ok": True, "grund": "gewaehlt", "gewaehlt": chosen_id}
    present = {str(x) for x in ((session.get("scene") or {}).get("presentIds") or [])}
    fig = next((c for c in natives or [] if isinstance(c, dict) and str(c.get("id") or "") == req), None)
    faehig = bool(fig) and req in present and req != str(session.get("avatarId") or "") and kernel.figure_speaker_eligible(session, fig)
    facts = [f for f in (session.get("facts") or []) if isinstance(f, dict)]
    last = next((f for f in reversed(facts) if f.get("kind") in ("speech", "action") and f.get("actorId") and kernel._scene.validiert(f)), None)
    if faehig and last is not None and req != str(last.get("actorId") or ""):
        src = str(last.get("sourceTurnId") or last.get("source_turn_id") or "")
        ziele = {str(f.get("targetId") or "") for f in facts if f.get("kind") in ("speech", "action") and kernel._scene.validiert(f)
                 and str(f.get("actorId") or "") == str(last.get("actorId") or "") and src
                 and str(f.get("sourceTurnId") or f.get("source_turn_id") or "") == src} | {str(last.get("targetId") or "")}
        if req in {str(x) for x in ev_aff} or req in ziele:
            return {"ok": True, "grund": "betroffen_oder_adressiert", "gewaehlt": chosen_id}
    directive = str(bound.get("directive") or "").strip()
    if faehig and directive:
        if kernel.regie_order_for(session, directive, req) is not None:
            return {"ok": True, "grund": "regie", "gewaehlt": chosen_id}
        for row in reversed(session.get("turns") or []):
            if isinstance(row, dict) and row.get("role") == "regie":
                if (str(row.get("directiveFor") or "") == req
                        and str(row.get("directiveText") or "").strip()[:300] == directive[:300]):
                    return {"ok": True, "grund": "regie", "gewaehlt": chosen_id}
                break
    return {"ok": False, "angefragt": req, "gewaehlt": chosen_id or None}


_SPEAK_AS_OPERATOR = ("operator", "user", "bedienperson")


def gebundener_eingabe_actor(session: dict, raw: dict) -> str:
    """Who produced the input text of an ordinary turn (prepare/commit) - from the canonical session and the UI's
    stated mode (Bedienabsicht), never from a client actor id (Stand 07 / K-01; AMASTER §8 "der Nutzer ist nicht
    automatisch eine Figur", §23, §27.2; SPS V65F Bedienperson `user`, V65F.4 followAs). The same mapping as
    kernel.default_input_actor_id without its first line (an explicit client value won). A figure speaks for herself
    only through the Puppet route (§27.4). Raises WriterError 422 for a mode this route cannot bind."""
    speak_as = str(raw.get("speakAs") or raw.get("speak_as") or "").strip().lower()
    kind = str(raw.get("inputKind") or raw.get("input_kind") or "").strip().lower()
    role = str((session or {}).get("role") or "teilnehmer").strip().lower()
    avatar = str((session or {}).get("avatarId") or "")
    if speak_as in _SPEAK_AS_OPERATOR:
        return "user"
    if speak_as == "observer" or kind in ("comment", "observer") or (role == "beobachter" and not speak_as):
        return "observer"
    if speak_as == "avatar" or (not speak_as and role in ("avatar", "teilnehmer")):
        if speak_as == "avatar" and not avatar:
            raise WriterError("„Als Avatar“ ist gewählt, diese Session hat aber keinen Avatar. Nichts wurde gespeichert.",
                              422, "EINGABE_ACTOR_UNGEBUNDEN", details={"speakAs": speak_as})
        return avatar or "user"
    if not speak_as:
        return avatar or "user"
    raise WriterError("Diese Eingabeart ist auf dem normalen Chatweg nicht zulässig (für eine Figur sprechen nur über "
                      "„Puppet“). Nichts wurde gespeichert.", 422, "EINGABE_ACTOR_UNGEBUNDEN", details={"speakAs": speak_as})


def eingabe_binden(session: dict, raw: dict, bound: dict, aid: str) -> dict:
    """Server-bind the client TurnTruth fields that are not Bedienabsicht. A sent input actor that differs from the bound
    one is rejected (visible, nothing stored) instead of silently replaced."""
    derived = gebundener_eingabe_actor(session, raw)
    sent = str(raw.get("inputActorId") or raw.get("input_actor_id") or "")
    if sent and sent != derived:
        raise WriterError("Die Eingabe ist einer anderen Person zugeordnet als dieser Session-Modus erlaubt "
                          f"(gesendet: {sent}, gebunden: {derived}). Für eine Figur sprechen nur über „Puppet“. "
                          "Nichts wurde gespeichert.", 422, "EINGABE_ACTOR_UNGEBUNDEN",
                          details={"gesendet": sent, "gebunden": derived})
    for k in ("inputActorId", "input_actor_id", "puppetId", "puppet_id", "operatorId", "operator_id", "sceneId",
              "scene_id", "timeRef", "time_ref", "uploadRef", "upload_ref", "responseSpeakerId", "response_speaker_id"):
        bound.pop(k, None)
    scene = (session or {}).get("scene") or {}
    bound["inputActorId"] = derived
    bound["operatorId"] = aid or (session or {}).get("userId") or ""
    if scene.get("placeId"):
        bound["sceneId"] = scene.get("placeId")
    if scene.get("time"):
        bound["timeRef"] = scene.get("time")
    _up = ((session or {}).get("focus") or {}).get("uploadId") if isinstance((session or {}).get("focus"), dict) else None
    if _up:
        bound["uploadRef"] = _up
    return bound

# V65W (Tiefenpruefung v1 P05/P07/C6; AMASTER §63 sichere Wiederaufnahme): a boot id alone is no proof that its process
# still runs (two server processes on one database, or a restart that overlaps the old process). Every server process
# holds an exclusive OS lock on its own start file next to the database (`.matrix_boot/<boot>.lock`) for its lifetime;
# the operating system releases it when the process ends, also on a crash. Another process proves the end by taking
# that lock (no timer, no table, no truth - orchestration status only). Attempts of processes without such a file
# (before V65W) are "unklar" and never count as ended.
import atexit as _atexit  # noqa: E402
_BOOT_LOCKS: dict[str, Any] = {}
BOOT_PROOF = "bootlock"


def _boot_dir(db_file: str | None) -> Path | None:
    if not db_file or str(db_file).startswith(":memory:"):
        return None
    return Path(str(db_file)).resolve().parent / ".matrix_boot"


def _os_lock(fh, *, blocking: bool) -> bool:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return True
    except OSError:
        return False


def _os_unlock(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def hold_boot_lock(db_file: str | None) -> bool:
    """V65W: this process's start lock for the database in `db_file` (idempotent). False = no lock (memory DB, no
    writable directory) - then attempts of this process carry no proof and read as "unklar" elsewhere."""
    d = _boot_dir(db_file)
    if d is None:
        return False
    key = str(d)
    if key in _BOOT_LOCKS:
        return True
    try:
        d.mkdir(exist_ok=True)
        p = d / f"{SERVER_BOOT_ID}.lock"
        fh = open(p, "a+")
        fh.write("1")
        fh.flush()
        if not _os_lock(fh, blocking=True):
            fh.close()
            return False
    except OSError:
        return False
    _BOOT_LOCKS[key] = (fh, p)

    def _release(fh=fh, p=p):
        _os_unlock(fh)
        try:
            fh.close()
            p.unlink()
        except OSError:
            pass
    _atexit.register(_release)
    return True


def boot_alive(boot: str, db_file: str | None) -> bool | None:
    """V65W: True = the process of `boot` still runs (its start lock is held), False = it ended (lock free or file
    removed at its normal end), None = cannot be proven (no lock directory). Read only (removes a free stale file)."""
    if str(boot or "") == SERVER_BOOT_ID:
        return True
    d = _boot_dir(db_file)
    if d is None or not boot or not re.fullmatch(r"[0-9a-f]{6,32}", str(boot)):
        return None
    p = d / f"{boot}.lock"
    if not p.exists():
        return False
    try:
        fh = open(p, "a+")
    except OSError:
        return None
    try:
        if _os_lock(fh, blocking=False):
            _os_unlock(fh)
            fh.close()
            try:
                p.unlink()
            except OSError:
                pass
            return False
        return True
    finally:
        if not fh.closed:
            fh.close()


def _attempt_alive_for(db_file: str | None):
    """V65W: the process proof for kernel.pending_input_view(alive=...): only attempts that recorded the start-lock
    proof (lebensnachweis = bootlock) can be proven ended; older attempts stay unclear (None)."""
    def alive(attempt: dict) -> bool | None:
        if str(attempt.get("boot") or "") == SERVER_BOOT_ID:
            return True
        if str(attempt.get("lebensnachweis") or "") != BOOT_PROOF:
            return None
        return boot_alive(str(attempt.get("boot") or ""), db_file)
    return alive


def create_app(db_path_arg=None) -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(NativeBoundaryError)
    def _native_boundary_unavailable(exc):
        # Stand 06 / K2: a consent-core failure no route caught itself (measured: puppet, GET /api/sessions/<id>)
        try:
            _get_conn().rollback()
        except Exception:
            pass
        return _json_error(exc.code, exc.message, 503, exc.code)
    if db_path_arg is not None:
        app.config["MATRIX_DB"] = str(db_path_arg)

    def _db_file_now() -> str:
        return str(app.config.get("MATRIX_DB") or db_path())

    def _alive():
        # V65W (C6): the process proof for attempts of other server processes (their start locks)
        return _attempt_alive_for(_db_file_now())

    # V65I (AMASTER §65 Diagnose zeigt Buildstand; dein Lauf 28.10. 15:31): the browser
    # sends the build of the app code it runs. A kernel call from other code than the
    # server's (cached bundle, page open across an update, tool without header) is
    # written once per value to the live log. Diagnostic only; nothing is refused.
    _server_build = matrix_live_log._build_ids()[0]
    _client_builds_seen: set[str] = set()

    @app.before_request
    def _client_build_check():
        if request.method != "POST" or not request.path.startswith("/api/kernel/"):
            return None
        client = str(request.headers.get("X-Matrix-Client-Build") or "").strip()
        if client == _server_build or client in _client_builds_seen:
            return None
        _client_builds_seen.add(client)
        matrix_live_log.live_log(
            "CLIENT_BUILD", trace_id="client_build", endpoint=request.path,
            client_build=client or None, server_build=_server_build,
            hinweis=("kein Build mitgesendet (App-Code vor V65I oder ein Werkzeug)" if not client
                     else "der Browser läuft anderen App-Code als der Server") + " - Seite neu laden")
        return None

    @app.teardown_appcontext
    def _close_db(_exc=None):
        conn = getattr(g, "_matrix_db", None)
        if conn is not None:
            conn.close()
            g._matrix_db = None

    def _health_provider():
        """Providerstatus für Startseite (§55): gespeicherte User-Config des
        Actors (Header) oder admin, sonst ENV. Nie ein Klartext-Key."""
        try:
            actor = read_actor_raw() or "admin"
            cfg = get_config(_get_conn(), actor, "user", actor)
        except Exception:
            cfg = {}
        return provider_status(cfg if isinstance(cfg, dict) else {})

    def _rust_kern_status():
        try:
            from matrix_api import native_boundary as _nb
            return _nb.status()
        except Exception as exc:   # the health answer itself must not fail
            return {"ok": False, "grund": f"Status nicht ermittelbar: {type(exc).__name__}", "abhilfe": ""}

    @app.get("/api/health")
    def health():
        _get_conn()
        configured = app.config.get("MATRIX_DB")
        shown = str(configured) if configured else str(db_path())
        build = "UNKNOWN"
        try:
            from pathlib import Path

            ver = Path(__file__).resolve().parent.parent / "VERSION.txt"
            for line in ver.read_text(encoding="utf-8").splitlines():
                if line.startswith("BUILD_ID="):
                    build = line.split("=", 1)[1].strip()
                    break
        except Exception:
            pass
        auth_on = True
        env_flag = os.environ.get("VITE_AUTH_ENABLED")
        if env_flag is not None and env_flag != "":
            auth_on = env_flag != "false"
        else:
            try:
                from pathlib import Path

                env_path = Path(__file__).resolve().parent.parent / ".grok" / "app-env.json"
                parsed = json.loads(env_path.read_text(encoding="utf-8"))
                auth_on = str(parsed.get("VITE_AUTH_ENABLED", "true")) != "false"
            except Exception:
                auth_on = True
        return jsonify(
            {
                "ok": True,
                "db": shown,
                "build": build,
                "buildId": build,
                "sqlite": True,
                "service": "matrix10-flask",
                "master": "sqlite",
                "secondMaster": False,
                "authInfra": "on" if auth_on else "off",
                # V65Y (Gesamtpruefung V65X "Benutzerzuordnung"; AMASTER §2/§3 lokale Profile ohne Cloud-Login, §8): the
                # user is a LOCAL profile chosen in the UI and sent as X-Matrix-Actor. It is no authentication; the server
                # binds to 127.0.0.1 only (run(): 0.0.0.0 is forced to loopback). Not for shared machines or remote access.
                "identitaet": {"art": "lokales_profil", "anmeldung": False, "nurLokal": True,
                               "hinweis": "Profilwahl ohne Anmeldung; nur auf diesem Rechner (127.0.0.1)"},
                "productStore": "flask-sqlite",
                "pgliteRunning": False,
                "neonRunning": False,
                "llmProvider": _health_provider()["provider"],
                "llmKeyPresent": _health_provider()["keyPresent"],
                "llmKeySource": _health_provider()["keySource"],
                "llmModel": _health_provider()["model"] or "",
                # Stand 10a: is the Rust consent core loadable HERE (touch/consent inputs need it, fail-closed otherwise)
                "rustKern": _rust_kern_status(),
            }
        )

    @app.get("/api/live-log")
    def api_live_log_tail():
        actor, err = get_actor(mutating=False)
        if err is not None:
            return err
        return jsonify(matrix_live_log.read_tail(80))

    @app.put("/api/mcc")
    def put_mcc():
        # Always forbidden. No write. SQL is the persistent master.
        # PUT /api/mcc is not a live persist writer.
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "SNAPSHOT_OWNER_FORBIDDEN",
                    "code": "SNAPSHOT_OWNER_FORBIDDEN",
                    "message": "PUT /api/mcc is not a live persist writer. Use scoped /api/worlds, /api/sessions, /api/users or POST /api/import/mcc. Global MCC replace is forbidden; SQL is the persistent master.",
                }
            ),
            409,
        )

    @app.post("/api/import/mcc")
    def post_import_mcc():
        actor, err = get_actor(mutating=True)
        data = request.get_json(silent=True)
        if data is None:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "IMPORT_FAILED",
                        "message": "Body must be JSON MCC snapshot",
                    }
                ),
                400,
            )
        as_tf = bool(data.get("asTestfixture") or data.get("as_testfixture"))
        testing = bool(app.config.get("TESTING") or os.environ.get("TESTING") or os.environ.get("MATRIX_TESTING"))
        if as_tf and testing:
            actor = "admin"
            err = None
        elif as_tf and not testing:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "OWNER_FORBIDDEN",
                        "message": "asTestfixture is not a product path",
                    }
                ),
                403,
            )
        if err is not None:
            return err
        conn = _get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = import_mcc(conn, data, actor or "admin", as_testfixture=as_tf)
            conn.commit()
            if "ok" not in result:
                result = {"ok": True, **result}
            return jsonify(result), 200
        except ImportAborted as exc:
            conn.rollback()
            return (
                jsonify({"ok": False, "error": exc.error, "message": exc.message}),
                exc.status,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            conn.rollback()
            return (
                jsonify({"ok": False, "error": "IMPORT_FAILED", "message": str(exc)}),
                400,
            )
        except Exception as exc:
            conn.rollback()
            return (
                jsonify({"ok": False, "error": "IMPORT_FAILED", "message": str(exc)}),
                500,
            )

    @app.get("/api/mcc")
    def api_get_mcc():
        actor, err = get_actor(mutating=False)
        conn = _get_conn()
        if not actor:
            blob = {
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
            return jsonify({"ok": True, "blob": None, "empty": True, **blob})
        blob = get_mcc(conn, actor)
        empty = not blob.get("worlds") and not blob.get("sessions")
        return jsonify({"ok": True, "blob": None if empty else blob, "empty": empty, **blob})

    @app.get("/api/sessions/<session_id>")
    def api_get_session(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        conn = _get_conn()
        try:
            sess = get_session(conn, actor or "admin", session_id)
        except KeyError:
            return jsonify({"ok": False, "error": "NOT_FOUND", "message": "session not found", "code": "NOT_FOUND"}), 404
        except IsolationError as exc:
            return jsonify({"ok": False, "error": "FORBIDDEN", "message": str(exc), "code": "ISOLATION"}), 403
        # V65U (Plan V65U U4/U5): the open input as a read view (not stored; save_session keeps only envelope fields),
        # so the UI shows "Antwort erneut erzeugen" / "Eingabe ohne Antwort abschliessen" from the stored state.
        if isinstance(sess, dict):
            sess["pendingInput"] = kernel.pending_input_view(sess, boot_id=SERVER_BOOT_ID, alive=_alive())
            # V65Y (Gesamtpruefung V65X P0-4): stored legacy rows outside the write boundary, as a read view (diagnosis)
            from matrix_api.repos import write_boundary_audit
            sess["schreibgrenze"] = write_boundary_audit(conn, session_id)
        body = dict(sess)
        body["ok"] = True
        body["session"] = sess
        return jsonify(body), 200

    # ----- canonical ID allocation -----
    @app.post("/api/ids/allocate")
    def api_allocate_ids():
        # Allocation creates no product state and therefore needs no actor.
        # Ownership/isolation are enforced by the subsequent canonical writer.
        return _run_read(lambda _conn: allocate_ids(_body()))

    # ----- users -----
    @app.post("/api/users")
    def api_post_users():
        actor, err = get_actor(mutating=True)
        body = _body() or {}
        if err is not None and isinstance(body, dict) and body.get("id"):
            actor = str(body.get("id"))
            err = None
        if err is not None:
            return err
        return _run_write(lambda conn: create_user(conn, body, actor))

    @app.patch("/api/users/<user_id>")
    def api_patch_user(user_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: patch_user(conn, user_id, _body(), actor))

    @app.delete("/api/users/<user_id>")
    def api_delete_user(user_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: delete_user(conn, user_id, actor))

    @app.get("/api/users")
    def api_list_users():
        actor, err = get_actor(mutating=False)
        if err is not None:
            return err
        if not actor:
            return _run_read(lambda conn: list_user_directory(conn))
        return _run_read(lambda conn: list_users(conn, actor))

    @app.get("/api/users/<user_id>")
    def api_get_user(user_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: get_user(conn, user_id, actor))

    @app.delete("/api/users/<user_id>/logs")
    def api_delete_user_logs(user_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: delete_user_logs(conn, user_id, actor), checkpoint_after=True)

    @app.delete("/api/users/<user_id>/logs/orphan-sessions")
    def api_delete_orphan_session_logs(user_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: delete_orphan_session_logs(conn, user_id, actor), checkpoint_after=True)

    @app.post("/api/users/<user_id>/hard-reset")
    def api_hard_reset_user(user_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: hard_reset_user(conn, user_id, actor), checkpoint_after=True)

    @app.post("/api/users/<user_id>/reset-sessions")
    def api_reset_user_sessions(user_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: reset_user_sessions(conn, user_id, actor), checkpoint_after=True)

    # ----- worlds -----
    @app.post("/api/worlds")
    def api_post_worlds():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_world(conn, _body(), actor))

    @app.post("/api/world-packs/import")
    def api_import_world_pack():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: import_world_pack(conn, _body(), actor))

    @app.patch("/api/worlds/<world_id>")
    def api_patch_world(world_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: patch_world(conn, world_id, _body(), actor))

    @app.delete("/api/worlds/<world_id>")
    def api_delete_world(world_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: delete_world(conn, world_id, actor), checkpoint_after=True)

    @app.get("/api/worlds")
    def api_list_worlds():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_worlds(conn, actor))

    @app.get("/api/worlds/<world_id>")
    def api_get_world(world_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: get_world(conn, world_id, actor))

    @app.post("/api/worlds/<world_id>/backup")
    def api_backup_world(world_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: backup_world(conn, world_id, actor))

    @app.get("/api/worlds/<world_id>/backup")
    def api_list_world_backups(world_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_world_backups(conn, world_id, actor))

    @app.post("/api/worlds/<world_id>/restore-backup")
    def api_restore_world_backup(world_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: restore_world_backup(conn, world_id, actor, _body()))

    # ----- characters -----
    @app.post("/api/characters")
    def api_post_characters():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_character(conn, _body(), actor))

    @app.patch("/api/characters/<char_id>")
    def api_patch_character(char_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: patch_character(conn, char_id, _body(), actor))

    @app.delete("/api/characters/<char_id>")
    def api_delete_character(char_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: delete_character(conn, char_id, actor), checkpoint_after=True)

    @app.post("/api/characters/<char_id>/backup")
    def api_backup_character(char_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: backup_character(conn, char_id, actor))

    @app.get("/api/characters/<char_id>/backup")
    def api_list_character_backups(char_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_character_backups(conn, char_id, actor))

    @app.post("/api/characters/<char_id>/restore-backup")
    def api_restore_character_backup(char_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: restore_character_backup(conn, char_id, actor, _body()))

    @app.get("/api/characters")
    def api_list_characters():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_characters(conn, actor))

    @app.get("/api/characters/<char_id>")
    def api_get_character(char_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: get_character(conn, char_id, actor))

    # ----- sessions envelope -----
    @app.post("/api/sessions")
    def api_post_sessions():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_session(conn, _body(), actor))

    @app.put("/api/sessions/<session_id>")
    def api_put_session(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: put_session(conn, session_id, _body(), actor))

    @app.patch("/api/sessions/<session_id>")
    def api_patch_session(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: patch_session(conn, session_id, _body(), actor))

    @app.delete("/api/sessions/<session_id>")
    def api_delete_session(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        # V80: Session löschen means Session + all associated data, including logs.
        return _run_write(lambda conn: delete_session(conn, session_id, actor), checkpoint_after=True)

    @app.post("/api/sessions/<session_id>/reset-chat")
    def api_reset_session_chat(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: reset_session_chat(conn, session_id, _body(), actor))

    @app.post("/api/sessions/<session_id>/reset-memory")
    def api_reset_session_memory(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: reset_session_memory(conn, session_id, actor))

    @app.post("/api/sessions/<session_id>/reset-full")
    def api_reset_session_full(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: reset_session_full(conn, session_id, actor), checkpoint_after=True)

    # V65Y (Gesamtpruefung V65X G12; AMASTER §2 Reset ueber die Oberflaeche, §3 kein versteckter zweiter Pfad): the
    # runtime reset of the UI is /api/kernel/reset kind=runtime (labor.tsx); the duplicate direct route without a caller
    # is removed.

    @app.post("/api/sessions/<session_id>/reset-uploads")
    def api_reset_session_uploads(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: reset_session_uploads(conn, session_id, actor))

    # V65Y (Gesamtpruefung V65X N01/G12; AMASTER §6.2 Nr. 4, §71.1.3 "ungepruefter Rohtext direkt als kanonischer
    # Session-Fact", "Schutz vor direkten unautorisierten Writes"): SceneFacts are written only by the kernel's turn,
    # puppet, Regie, God and upload paths (validated, TurnTruth-bound). The direct client route POST .../facts (no UI
    # caller) is removed; the repository writer itself enforces actor, target and source (repos._check_fact_boundary).

    # V65Z (SPS-Audit V65Y §3/A03/A08; AMASTER §6.2 Nr. 4 kein Direkt-Write, §71.1.3): the direct client writers
    # POST .../turns (a dialogue line), PATCH .../memories/<id> and DELETE .../relations/<from>/<to> had one caller, the
    # client import's child loop (now one server-side import). Removed with their API functions; the repository writers
    # behind them keep the write boundary for the kernel paths.

    # V65Y (N03/G12; AMASTER §46.3/§46.4): God facts come only from /api/kernel/god (scope selection, TurnTruth, the
    # three scope axes); the direct route POST .../god-facts (no UI caller) is removed.

    @app.post("/api/sessions/<session_id>/memories")
    def api_post_session_memory(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_session_memory(conn, session_id, _body(), actor))

    @app.put("/api/sessions/<session_id>/relations")
    def api_put_session_relation(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        # V65Y (N02): the Social UI's manual seed - the writer drops client provenance and stamps who and when
        return _run_write(lambda conn: put_session_relation(conn, session_id, _body(), actor, manual=True))

    @app.post("/api/sessions/<session_id>/propositions")
    def api_post_session_proposition(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_session_proposition(conn, session_id, _body(), actor))

    @app.patch("/api/sessions/<session_id>/propositions/<prop_id>")
    def api_patch_session_proposition(session_id: str, prop_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: patch_session_proposition(conn, session_id, prop_id, _body(), actor))

    @app.post("/api/sessions/<session_id>/goals")
    def api_post_session_goal(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_session_goal(conn, session_id, _body(), actor))

    @app.patch("/api/sessions/<session_id>/goals/<goal_id>")
    def api_patch_session_goal(session_id: str, goal_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: patch_session_goal(conn, session_id, goal_id, _body(), actor))

    @app.get("/api/sessions")
    def api_list_sessions():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: {"ok": True, "sessions": list_sessions(conn, actor)})

    @app.get("/api/sessions/<session_id>/evidence")
    def api_list_session_evidence(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_session_evidence(conn, session_id, actor))

    # ----- uploads -----
    @app.post("/api/uploads")
    def api_post_uploads():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_upload(conn, _body(), actor))

    @app.patch("/api/uploads/<upload_id>")
    def api_patch_upload(upload_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: patch_upload(conn, upload_id, _body(), actor))

    @app.post("/api/uploads/<upload_id>/ingest")
    def api_ingest_upload(upload_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: ingest_upload(conn, upload_id, actor))

    @app.post("/api/uploads/<upload_id>/commit")
    def api_commit_upload(upload_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: commit_upload(conn, upload_id, actor))

    @app.delete("/api/uploads/<upload_id>")
    def api_delete_upload(upload_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: delete_upload(conn, upload_id, actor))

    @app.get("/api/uploads")
    def api_list_uploads():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_uploads(conn, actor))

    @app.get("/api/uploads/<upload_id>")
    def api_get_upload(upload_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: get_upload(conn, upload_id, actor))

    @app.post("/api/documents")
    def api_post_documents():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_document(conn, _body(), actor))

    @app.get("/api/documents")
    def api_list_documents():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_documents(conn, actor))

    @app.get("/api/documents/<doc_id>")
    def api_get_document(doc_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: get_document(conn, doc_id, actor))

    @app.delete("/api/documents/<doc_id>")
    def api_delete_document(doc_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: delete_document(conn, doc_id, actor))

    @app.patch("/api/documents/<doc_id>")
    def api_patch_document(doc_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: patch_document(conn, doc_id, _body(), actor))

    @app.get("/api/document-index")
    def api_list_document_index():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_document_index(conn, actor))

    @app.post("/api/document-index/search")
    def api_search_document_index():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        body = _body() or {}
        q = str((body or {}).get("q") or (body or {}).get("cue") or "")
        return _run_read(lambda conn: search_document_index(conn, actor, q))

    # ----- reviews -----
    @app.post("/api/reviews")
    def api_post_reviews():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_review(conn, _body(), actor))

    @app.post("/api/reviews/<review_id>/resolve")
    def api_resolve_review(review_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: resolve_review(conn, review_id, _body(), actor))

    @app.patch("/api/reviews/<review_id>")
    def api_patch_review(review_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: patch_review(conn, review_id, _body(), actor))

    @app.get("/api/reviews")
    def api_list_reviews():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_reviews(conn, actor))

    @app.get("/api/reviews/<review_id>")
    def api_get_review(review_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: get_review(conn, review_id, actor))

    # ----- snapshots -----
    @app.post("/api/snapshots")
    def api_post_snapshots():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_snapshot(conn, _body(), actor))

    @app.post("/api/snapshots/<snap_id>/restore")
    def api_restore_snapshot(snap_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: restore_snapshot(conn, snap_id, actor))

    @app.delete("/api/snapshots/<snap_id>")
    def api_delete_snapshot(snap_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: delete_snapshot(conn, snap_id, actor))

    @app.get("/api/snapshots")
    def api_list_snapshots():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_snapshots(conn, actor))

    @app.get("/api/snapshots/<snap_id>")
    def api_get_snapshot(snap_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: get_snapshot(conn, snap_id, actor))

    # ----- triggers -----
    @app.post("/api/triggers")
    def api_post_triggers():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_trigger(conn, _body(), actor))

    @app.patch("/api/triggers/<trigger_id>")
    def api_patch_trigger(trigger_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: patch_trigger(conn, trigger_id, _body(), actor))

    @app.delete("/api/triggers/<trigger_id>")
    def api_delete_trigger(trigger_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: delete_trigger(conn, trigger_id, actor))

    @app.get("/api/triggers")
    def api_list_triggers():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_triggers(conn, actor))

    @app.get("/api/triggers/<trigger_id>")
    def api_get_trigger(trigger_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: get_trigger(conn, trigger_id, actor))

    # ----- preferences -----
    @app.post("/api/preferences")
    def api_post_preferences():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_preference(conn, _body(), actor))

    @app.patch("/api/preferences/<pref_id>")
    def api_patch_preference(pref_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: patch_preference(conn, pref_id, _body(), actor))

    @app.delete("/api/preferences/<pref_id>")
    def api_delete_preference(pref_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: delete_preference(conn, pref_id, actor))

    @app.get("/api/preferences")
    def api_list_preferences():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_preferences(conn, actor))

    @app.get("/api/preferences/<pref_id>")
    def api_get_preference(pref_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: get_preference(conn, pref_id, actor))

    # ----- config (user-scoped) -----
    @app.put("/api/config")
    def api_put_config():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: put_config(conn, _body(), actor))

    @app.get("/api/config")
    def api_get_config():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        scope = str(request.args.get("scope") or "user")
        scope_id = request.args.get("scope_id") or request.args.get("scopeId")
        return _run_read(lambda conn: _public_config(get_config(conn, actor, scope, scope_id)))

    # ----- logs append-only -----
    @app.post("/api/logs")
    def api_post_logs():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: create_log(conn, _body(), actor))

    @app.get("/api/logs")
    def api_list_logs():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_logs(conn, actor))

    @app.post("/api/logs/live")
    def api_live_log():
        """Append structured turn-trace lines to the per-start live log (logs/MATRIX10_LIVE_<Version>_<Start>.log, no secrets)."""
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "bad body"}), 400
        stage = str(body.get("stage") or "UNKNOWN")
        trace_id = str(body.get("trace_id") or body.get("traceId") or matrix_live_log.new_trace_id())
        turn_id = body.get("turn_id") or body.get("turnId") or trace_id
        fields = {k: v for k, v in body.items() if k not in ("stage", "trace_id", "traceId", "turn_id", "turnId")}
        try:
            matrix_live_log.live_log(stage, trace_id=trace_id, turn_id=str(turn_id), **fields)
            return jsonify({"ok": True, "trace_id": trace_id, "path": str(matrix_live_log.log_path())})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.get("/api/logs/<log_id>")
    def api_get_log(log_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: get_log(conn, log_id, actor))

    @app.put("/api/logs/<log_id>")
    def api_put_log(log_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _json_error("METHOD_NOT_ALLOWED", "logs are append-only; no PUT overwrite", 405)

    @app.delete("/api/logs/<log_id>")
    def api_delete_log(log_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _json_error("LOG_DELETE_FORBIDDEN", "logs are append-only except user-scoped hard reset", 403)

    @app.post("/api/sessions/<session_id>/snapshots")
    def api_post_session_snapshot(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        body = _body() or {}
        name = (body.get("name") if isinstance(body, dict) else None) or "Stand"
        return _run_write(lambda conn: {"ok": True, "snapshot": add_snapshot(conn, actor, session_id, name)})

    @app.post("/api/sessions/<session_id>/appointments")
    def api_post_appointment(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        body = _body() or {}
        if isinstance(body, dict):
            body.setdefault("sessionId", session_id)
        return _run_write(lambda conn: create_appointment(conn, body, actor))

    @app.get("/api/sessions/<session_id>/appointments")
    def api_list_appointments(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_appointments(conn, session_id, actor))

    @app.post("/api/sessions/<session_id>/graph")
    def api_post_graph(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        body = _body() or {}
        if isinstance(body, dict):
            body.setdefault("sessionId", session_id)
        return _run_write(lambda conn: create_graph_edge(conn, body, actor))

    @app.get("/api/sessions/<session_id>/graph")
    def api_list_graph(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_read(lambda conn: list_graph_edges(conn, session_id, actor))

    @app.post("/api/sessions/<session_id>/recall")
    def api_recall(session_id: str):
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        body = _body() or {}
        cue = str((body or {}).get("cue") or (body or {}).get("q") or "")
        character_id = (body or {}).get("characterId") or (body or {}).get("character_id")
        if character_id:
            # Stand 08 / K-02 (AMASTER §41, KV §5 "wo kann der Nutzer den gespeicherten Zustand pruefen ... welcher reale Reader
            # benutzt ihn"): with a chosen figure the page shows exactly what THIS figure recalls - the same reader the
            # figure's turn uses (kernel.recall: witnessed facts, own memories, own relations), not the cache overlap over
            # every figure's memories. Read only.
            def _figur(conn):
                sess = get_session(conn, actor or "admin", session_id)
                ch = get_character(conn, str(character_id), actor or "admin")
                if not isinstance(ch, dict) or ch.get("worldId") != sess.get("worldId"):
                    raise WriterError("Figur gehört nicht zur Welt dieser Session.", 422, "CHARACTER_NOT_IN_WORLD")
                rc = kernel.recall(sess, str(character_id), cue or None)
                mems = [{k: m.get(k) for k in ("id", "kind", "text", "turn", "factId", "sourceTurnId")} for m in rc.get("memories") or []]
                facts = [{k: f.get(k) for k in ("id", "kind", "actorId", "text", "turn")} for f in rc.get("facts") or []]
                return {"ok": True, "engine": "kernel.recall", "kanonisch": True, "characterId": str(character_id),
                        "characterName": ch.get("name"), "cue": cue, "memories": mems, "facts": facts,
                        "hits": [{"id": m["id"], "text": f"{m.get('kind')}: {m.get('text')}", "sourceMemoryId": m["id"]} for m in mems]}
            return _run_read(_figur)
        return _run_read(lambda conn: recall_patterns(conn, session_id, actor, cue, character_id=character_id))

    def kernel_session_response(conn, actor, session):
        if not actor:
            raise WriterError("actor required", 401, "UNAUTHORIZED")
        if not conn.execute("SELECT id FROM users WHERE id=?", (actor,)).fetchone():
            upsert_user(conn, {"id": actor, "name": actor})
        writes = (session or {}).pop("_godOwnerWrites", None) if isinstance(session, dict) else None
        if isinstance(writes, dict) and writes:
            canon = writes.get("worldCanon")
            wid = session.get("worldId") if isinstance(session, dict) else None
            if canon and wid:
                world = get_world(conn, str(wid), actor)
                if not isinstance(world, dict):
                    raise WriterError("world not found for god owner write", 404, "NOT_FOUND")
                existing = world.get("canon") or ""
                extra = str(canon).strip()
                if extra and extra not in str(existing):
                    nxt = (str(existing).rstrip() + "\n" + extra).strip() if existing else extra
                    patch_world(conn, str(wid), {"canon": nxt}, actor)
            ck = writes.get("characterKnowledge")
            if isinstance(ck, dict) and ck.get("id") and ck.get("text"):
                ch = get_character(conn, str(ck["id"]), actor)
                if not isinstance(ch, dict):
                    raise WriterError("character not found for god owner write", 404, "NOT_FOUND")
                knowledge = list(ch.get("knowledge") or [])
                txt = str(ck["text"]).strip()
                if txt and txt not in knowledge:
                    knowledge.append(txt)
                    patch_character(conn, str(ck["id"]), {"knowledge": knowledge[-24:]}, actor)
            # V74 / AMASTER §46: a successful owner persistence operation is
            # already marked applied by the kernel. Never turn an explicitly
            # rejected God effect into a canonical truth just because SQLite
            # accepted the enclosing session row.
        saved = save_session(conn, actor, session)
        if isinstance(saved, dict):
            # V65U: read view of the open input for the UI (never persisted, see api_get_session)
            saved["pendingInput"] = kernel.pending_input_view(saved, boot_id=SERVER_BOOT_ID, alive=_alive())
        return saved

    def _sql_natives(conn, aid, session):
        natives: list = []
        wid = session.get("worldId")
        try:
            listed = list_characters(conn, aid or session.get("userId") or "admin")
            all_chars = listed.get("characters") if isinstance(listed, dict) else listed
            for row in all_chars or []:
                if isinstance(row, dict) and (not wid or row.get("worldId") == wid or row.get("world_id") == wid):
                    natives.append(row)
        except (WriterError, KeyError, IsolationError):
            natives = []
        # V65K (AMASTER §24.1 known_as, scope = this session): names established in this session
        # bind entities like a stem alias, as a read projection - the stem is never changed.
        return kernel.with_session_aliases(natives, session)

    def _canonical_speaker(conn, aid, session, speaker_hint, natives):
        hint = speaker_hint if isinstance(speaker_hint, dict) else {}
        sid = hint.get("id") or ""
        if not sid:
            return {}
        stamm = None
        try:
            stamm = get_character(conn, str(sid), aid or session.get("userId") or "admin")
        except (WriterError, KeyError, IsolationError):
            stamm = next((c for c in natives if isinstance(c, dict) and c.get("id") == sid), None)
        if not isinstance(stamm, dict):
            raise WriterError(f"speaker {sid} not found", 404, "FIGURE_NOT_FOUND")
        out = dict(stamm)
        out["id"] = stamm.get("id") or sid
        return out

    def _canonical_target(conn, aid, session, target_id, natives, *, text="", input_actor_id=""):
        """One speech addressee binding for prepare AND commit. A remembered UI
        choice is not valid after that person left the scene. Mention is not
        address; an explicit absent vocative still does not grant knowledge.
        """
        candidate = str(target_id or "")
        wid = str(session.get("worldId") or "")
        if candidate:
            row = conn.execute("SELECT id, world_id FROM characters WHERE id=?", (candidate,)).fetchone()
            if not row or (wid and str(row["world_id"]) != wid):
                candidate = ""
        decision = kernel.resolve_target_detail(
            session, natives, str(text or ""), ui_target_id=candidate or None,
            input_actor_id=str(input_actor_id or ""),
        )
        return decision


    def _bind_scene_perception(session, bound):
        """Presence + Hörer/Seher from SQL scene, never client rewrite."""
        present = list((session.get("scene") or {}).get("presentIds") or [])
        bound["presentIds"] = present
        bound.pop("present_ids", None)
        hears, sees = kernel._scene_perception(session, present)
        bound["hearsIds"] = hears
        bound["seesIds"] = sees
        bound.pop("hears_ids", None)
        bound.pop("sees_ids", None)
        # V60 (AMASTER §26/§39, §68 Nr. 7, §28 Schritt 2/8): who is informed or
        # affected is decided by the kernel writers from canonical perception,
        # never by client TurnTruth fields; the avatar is the session's avatar.
        for key in ("informedIds", "informed_ids", "affectedIds", "affected_ids"):
            bound.pop(key, None)
        if session.get("avatarId"):
            bound["avatarId"] = session.get("avatarId")
            bound.pop("avatar_id", None)
        return bound

    def _kernel_actor(body):
        actor, err = get_actor(mutating=True)
        if actor:
            return actor, None
        return None, err

    def _public_config(cfg):
        """V25: gespeicherter Key nur als Vorhandensein/Maske; Status aus der
        gescopten Config (Frontend-Key vor ENV), nie Klartext."""
        raw = dict(cfg) if isinstance(cfg, dict) else {}
        status = provider_status(raw)
        data = public_config_view(raw)
        data["keyPresent"] = status["keyPresent"]
        data["keySource"] = status["keySource"]
        stored = str(data.get("provider") or "").strip()
        if stored in ("synapse", "synapse-local"):
            data["provider"] = "synapse"
        elif not stored:
            data["provider"] = status["provider"]
        if status["model"]:
            data["liveModel"] = status["model"]
        data["liveProvider"] = status["provider"]
        return data

    def _kernel_stored_session(conn, aid, body):
        session = (body or {}).get("session") or {}
        truth = (body or {}).get("truth") or {}
        sid = (
            (body or {}).get("sessionId")
            or (body or {}).get("session_id")
            or (truth.get("sessionId") if isinstance(truth, dict) else None)
            or (truth.get("session_id") if isinstance(truth, dict) else None)
            or session.get("id")
        )
        if not sid:
            raise WriterError("session id required", 400, "BAD_REQUEST")
        if not aid:
            raise WriterError("X-Matrix-Actor required", 401, "UNAUTHORIZED")
        try:
            return get_session(conn, aid, str(sid))
        except KeyError as exc:
            raise WriterError("session not found", 404, "NOT_FOUND") from exc

    @app.post("/api/kernel/prepare")
    def kernel_prepare():
        _llm_vorab.vorab_leeren()   # Stand 11: Lesungen der ersten Antwort gelten nur fuer diese Anfrage
        body = request.get_json(silent=True) or {}
        trace_id = str(body.get("trace_id") or body.get("traceId") or matrix_live_log.new_trace_id("kpr"))
        last = "UI_REQUEST"
        matrix_live_log.live_log("UI_REQUEST", trace_id=trace_id, endpoint="/api/kernel/prepare")
        aid, err = _kernel_actor(body)
        if err is not None and not aid:
            return err
        try:
            def _read(conn):
                nonlocal last
                session = _kernel_stored_session(conn, aid, body)
                raw = body.get("truth") or {}
                if not isinstance(raw, dict):
                    raw = {}
                bound = dict(raw)
                bound["userId"] = aid or session.get("userId") or bound.get("userId") or ""
                bound["worldId"] = session.get("worldId") or bound.get("worldId") or ""
                bound["sessionId"] = session.get("id") or bound.get("sessionId") or ""
                bound["role"] = "character" if kernel.is_figure_followup_turn(raw) else (session.get("role") or "teilnehmer")
                bound["authority"] = normal_kernel_authority(session, raw)
                if session.get("avatarId") and not (bound.get("avatarId") or bound.get("avatar_id")):
                    bound["avatarId"] = session.get("avatarId")
                _bind_scene_perception(session, bound)
                eingabe_binden(session, raw, bound, aid)   # Stand 07 / K-01: input actor, scene/time/upload from the server
                bound.pop("id", None)   # the TurnTruth id is the server's (an open input keeps its stored one below)
                speaker = body.get("speaker") or {}
                if not isinstance(speaker, dict):
                    speaker = {}
                requested = speaker.get("id") or bound.get("speakerId") or bound.get("speaker_id")
                authority = bound.get("authority") or "observer"
                if requested and requested == session.get("avatarId") and not _normal_kernel_avatar_user_input(session, bound, requested):
                    return {"ok": False, "error": "AVATAR_NOT_SPEAKER", "message": "Avatar is never a normal figure speaker"}, 400
                natives = _sql_natives(conn, aid, session)
                if not natives:
                    natives = []
                # V92 Paket 16 (Paket-15-Pruefung): the operator's answers to an identity clarification of THIS input - a read
                # projection for the name readers (target, plan, binder); the speaker choice keeps the plain cast. Never stored.
                # V92 Paket 17 (Paket-16-Pruefung A, C, D): valid only for a question this server issued for exactly this input
                _ktext = str(bound.get("text") or "")
                _kctx = _klaerung_kontext(session, _ktext, _klaerung_akteur(bound), natives)
                _klaer = _klaerungen_pruefen(body.get("klaerungen"), _kctx, _ktext)
                knatives = kernel.with_klaerungen(natives, _klaer, _ktext)
                if (not _klaer and str(bound.get("inputKind") or bound.get("input_kind") or "") in ("speech", "user") and _ktext):
                    from matrix_api.llm_contract import name_boundary_check as _name_boundary_check
                    _np = _name_boundary_check(conn, aid or "admin", _ktext, figures=knatives,
                                               data={"sessionId": session.get("id"), "worldId": session.get("worldId")})
                    knatives = kernel.with_name_boundary_reading(_ktext, knatives, _np)
                hint_id = speaker.get("id") or bound.get("speakerId") or bound.get("speaker_id")
                hint_name = None
                # V40: autoPick = der Client überlässt die Sprecherwahl der Turn-Taking-Heuristik (§28)
                if body.get("autoPick") is True:
                    hint_id = None
                if hint_id:
                    hit = next((c for c in natives if c.get("id") == hint_id), None)
                    if hit:
                        hint_name = hit.get("name")
                client_tid = bound.get("targetId") or bound.get("target_id")
                target_binding = _canonical_target(
                    conn, aid, session, client_tid, knatives,
                    text=bound.get("text") or "",
                    input_actor_id=bound.get("inputActorId") or bound.get("input_actor_id") or "",
                )
                # Keep camel/snake forms identical; prepare truth and commit
                # must not retain an outdated shadow target field.
                bound["targetId"] = target_binding.get("target_id")
                bound["target_id"] = target_binding.get("target_id")
                matrix_live_log.live_log("TARGET_BIND", trace_id=trace_id,
                    requested=client_tid, resolved=target_binding.get("target_id"),
                    reason=target_binding.get("reason"), ambiguous=target_binding.get("ambiguous"))
                # Live turn-taking candidates from the same canonical session
                # that controls presence and knowledge. This variable was
                # previously unbound in the response (prepare HTTP 400).
                present_ids = set((session.get("scene") or {}).get("presentIds") or [])
                eligible_speakers = [c for c in natives if isinstance(c, dict) and
                    c.get("id") in present_ids and c.get("id") != session.get("avatarId")]
                speaker_candidates = kernel.rank_speakers(
                    session, eligible_speakers, str(bound.get("text") or ""),
                    natives=natives, autochat=bool(body.get("autoPick")),
                )[:4]
                if body.get("autoPick") is True:
                    _auto = bool(str(bound.get("inputKind") or bound.get("input_kind") or "") == "autochat")
                    _pick_text, _pick_aff = str(bound.get("text") or ""), None
                    if _auto and not _pick_text.strip():
                        # V65E (AMASTER §28 Schritte 20/23, §27.8): a reaction
                        # turn picks from the latest committed event, same as the gate.
                        _ev_text, _pick_aff = kernel.latest_event_stimulus(session)
                        _pick_text = _ev_text if _ev_text is not None else _pick_text
                    chosen = kernel.pick_speaker(
                        session, natives, _pick_text,
                        ui_target_id=target_binding.get("target_id"),
                        autochat=_auto,
                        affected_ids=_pick_aff,
                    )
                    if not chosen:
                        raise WriterError("no present figure can speak", 409, "NO_SPEAKER")
                    speaker = chosen
                    bound["speakerId"] = chosen["id"]
                    bound["speaker_id"] = chosen["id"]
                elif str(bound.get("inputKind") or bound.get("input_kind") or "") == "autochat" and requested:
                    # Stand 10 / F2 (AMASTER §28 Schritt 16 "nächsten Sprecher bestimmen", §48, KV §12.6; K-05): a reaction /
                    # AutoChat turn has no user input - who speaks is the SERVER's decision, the same one the gate shows.
                    # Measured F2 (P25..09): the gate chose Johann, the client sent Gustav, prepare/formulate/commit 200.
                    zulaessig = autochat_sprecher(session, natives, bound, requested)
                    if not zulaessig.get("ok"):
                        raise WriterError("Diese Figur ist für den Folgezug nicht vom Server gewählt (AutoChat/Reaktion). Nichts wurde "
                                          "gespeichert.", 409, "AUTOCHAT_SPRECHER_NICHT_GEWAEHLT", details=zulaessig)
                elif requested and requested != session.get("avatarId") and requested not in present_ids:
                    raise WriterError("selected speaker is not present", 409, "SPEAKER_NOT_PRESENT")
                elif requested and requested != session.get("avatarId") and not kernel.figure_speaker_eligible(
                        session, next((c for c in natives if isinstance(c, dict) and c.get("id") == requested), {"id": requested})):
                    # Stand 07 / K-01 (AMASTER §28 Schritt 16, §43): the selected figure is present but cannot speak now
                    raise WriterError("Die gewählte Figur kann gerade nicht sprechen (bewusstlos, geknebelt oder ohne Stimme). "
                                      "Nichts wurde gespeichert.", 409, "SPEAKER_NOT_CAPABLE", details={"speakerId": requested})
                present = natives
                world = {}
                wid = session.get("worldId")
                if wid:
                    try:
                        world = get_world(conn, str(wid), aid or session.get("userId") or "admin") or {}
                    except (WriterError, KeyError, IsolationError):
                        world = {}
                if not isinstance(world, dict):
                    world = {}
                # V54: the user's event is authoritative BEFORE the NPC answer.
                # Write through the same canonical turn/children SQL owners; the
                # reply commit completes the same TurnTruth and turn number.
                incoming = kernel.normalize_truth(bound)
                is_input = bool(str(incoming.get("text") or "").strip()) and str(incoming.get("input_kind") or "") in ("speech", "user")
                if is_input:
                    if session.get("pendingInputTurnId"):
                        old_truth = next((r for r in (session.get("turnTruths") or []) if r.get("id") == session["pendingInputTurnId"]), None)
                        # V65U (Plan V65U U4, "Antwort erneut erzeugen"): an explicit resume of THIS open input takes the
                        # stored TurnTruth as it is - independent of the current UI selection; never a second event.
                        _resume = body.get("resumePending") if isinstance(body.get("resumePending"), dict) else {}
                        _resume_ok = bool(_resume) and str(_resume.get("turnTruthId") or "") == str(session["pendingInputTurnId"])
                        # P23: a GET saying "running or not provably finished"
                        # cannot authorize a second write, even when the request
                        # repeats the same input verbatim or skips resumePending.
                        # A merely timed-out client does NOT end the server's work.
                        _attempt_view = kernel.pending_input_view(session, boot_id=SERVER_BOOT_ID, alive=_alive()) or {}
                        if _attempt_view.get("attemptRunning") and not _attempt_view.get("attemptUnklar"):
                            raise WriterError(
                                "Für diese Eingabe läuft nachweislich ein Antwortversuch. "
                                "Bitte den Status prüfen; ein zweiter gleichzeitiger Versuch ist gesperrt.",
                                409, "PENDING_RESPONSE_ATTEMPT_ACTIVE")
                        if not isinstance(old_truth, dict) or (not _resume_ok and any(
                            str(old_truth.get(key) or "") != str(incoming.get(key) or "")
                            for key in ("text", "input_actor_id", "target_id", "speaker_id")
                        )):
                            _pv = kernel.pending_input_view(session, boot_id=SERVER_BOOT_ID, alive=_alive()) or {}
                            _att = _pv.get("attempt") or {}
                            # V65T (Plan v2 Schritt 6): say which input waits and what happened to its answer; the UI
                            # offers "Antwort erneut erzeugen" (the same input again) and "Eingabe ohne Antwort abschliessen".
                            raise WriterError(
                                f"Die vorige Eingabe wartet noch auf ihre Antwort: „{_pv.get('text') or ''}“ "
                                f"(Turn {_pv.get('turn')}; Antwortversuch: "
                                f"{ {'laeuft': ('nicht nachweisbar beendet' if _pv.get('attemptUnklar') else 'läuft') if _pv.get('attemptRunning') else 'abgebrochen', 'provider_fehler': 'Provider-Fehler', 'formuliert': 'formuliert, nicht gespeichert'}.get(str(_att.get('state') or ''), 'nicht erfasst') }). "
                                f"Gleiche Eingabe erneut senden erzeugt die Antwort erneut. [{_pv.get('turnTruthId') or ''}]",
                                409, "INPUT_PENDING")
                        incoming = old_truth  # retry the same event, never duplicate it
                    else:
                        # V56: use the existing semantic ingress, never a word
                        # recognizer as authority. No network under SQLite lock.
                        plan = _extract_user_plan(conn, aid, session, incoming, knatives)
                        if isinstance(plan, dict) and not _klaer and _ktext and str(bound.get("inputKind") or bound.get("input_kind") or "") in ("speech", "user"):
                            # Stand 11: die Namenslesung kam mit der ersten Planer-Antwort - anwenden, Zielbindung neu bestimmen
                            _np = _name_boundary_check(conn, aid or "admin", _ktext, figures=knatives,
                                                       data={"sessionId": session.get("id"), "worldId": session.get("worldId")})
                            if _np:
                                knatives = kernel.with_name_boundary_reading(_ktext, knatives, _np)
                                target_binding = _canonical_target(
                                    conn, aid, session, client_tid, knatives, text=bound.get("text") or "",
                                    input_actor_id=bound.get("inputActorId") or bound.get("input_actor_id") or "")
                                incoming["target_id"] = target_binding.get("target_id")
                                matrix_live_log.live_log("TARGET_BIND", trace_id=trace_id, requested=client_tid,
                                    resolved=target_binding.get("target_id"), reason=target_binding.get("reason"),
                                    ambiguous=target_binding.get("ambiguous"), namen="erste_antwort")
                        if not isinstance(plan, dict):
                            from matrix_api.conjunctive import literal_plan
                            plan = literal_plan(str(incoming.get("text") or ""),
                                actor_id=str(incoming.get("input_actor_id") or ""),
                                recipient_id=str(incoming.get("target_id") or "") or None)
                        # Keep the SQLite writer transaction SHORT: the provider
                        # contradiction/context reader below may make a network
                        # call and must never hold a write lock while doing so.
                        conn.execute("BEGIN IMMEDIATE")
                        try:
                            # Re-read under the lock to reject concurrent/stale
                            # turns instead of overwriting another input.
                            locked = _kernel_stored_session(conn, aid, body)
                            if (locked.get("pendingInputTurnId") or
                                    int(locked.get("turnIndex") or 0) != int(session.get("turnIndex") or 0)):
                                raise WriterError("session advanced while preparing input", 409, "STALE_SESSION")
                            session = kernel.commit_turn(
                                locked, truth=incoming, speaker=speaker, present=knatives,
                                result={"speech": "", "action": None}, fired=[],
                                world=world, user_plan=plan, phase="input",
                            )
                            _ask_identity(session, incoming, target_binding, _klaer, natives, trace_id, kontext=_kctx, text=_ktext)
                            _reject_unexecutable_input(session, incoming, natives, trace_id)
                            session = kernel_session_response(conn, aid or "admin", session)
                            conn.commit()
                        except Exception:
                            conn.rollback()
                            raise
                        # Stand 06a / M2: the input is committed (its own consent was decided inside this transaction)
                        last = "INPUT_COMMITTED"
                        matrix_live_log.live_log("SQLITE_COMMIT", trace_id=trace_id,
                            status="INPUT_COMMITTED", session_id=session.get("id"),
                            source_turn_id=incoming.get("id"))
                        _stored_tt = next((r for r in (session.get("turnTruths") or []) if r.get("id") == incoming.get("id")), {}) or {}
                        matrix_live_log.live_log("EFFECT_PLAN", trace_id=trace_id, source="input",
                            components=len((plan or {}).get("komponenten") or []) if isinstance(plan, dict) else 0,
                            input_event_kind=_stored_tt.get("input_event_kind"),
                            ambiguous=[a.get("grund") for a in (_stored_tt.get("input_component_ambiguity") or [])][:6])
                        # V60 (AMASTER §54 Punkt 15, §68 Nr. 70): readable turn
                        # protocol — what the input planner proposed and what the
                        # writers really committed. Diagnosis only, no owner.
                        _names = {str(c.get("id")): str(c.get("name") or "") for c in natives if isinstance(c, dict)}
                        matrix_live_log.live_log("TURN_INPUT", trace_id=trace_id, source_turn_id=incoming.get("id"),
                            speaker=_names.get(str(incoming.get("input_actor_id") or ""), str(incoming.get("input_actor_id") or "")),
                            target=_names.get(str(incoming.get("target_id") or ""), ""),
                            text=str(incoming.get("text") or ""),
                            plan={k: (plan or {}).get(k) for k in ("event_kind", "summary", "refers_to", "source")} if isinstance(plan, dict) else None,
                            components=[{k: c.get(k) for k in ("typ", "segment", "ziel", "zeit", "wirkung", "bezug")}
                                        for c in ((plan or {}).get("komponenten") or []) if isinstance(c, dict)][:8] if isinstance(plan, dict) else [],
                            ambiguity=[{k: a.get(k) for k in ("grund", "segment")} for a in (_stored_tt.get("input_component_ambiguity") or [])][:6],
                            # V61: rule kinds as stored by the kernel (only when
                            # compiled in this turn) and the per-input candidates.
                            rule_kinds=([f"{r.get('nr')}:{r.get('art')}" + (f"@{r.get('ziel')}" if r.get('ziel') else "")
                                         for r in ((session.get("ruleKinds") or {}).get(str(incoming.get("target_id") or "")) or {}).get("rules") or []]
                                        if isinstance(plan, dict) and plan.get("regelarten") else None),
                            rule_candidates=((plan or {}).get("profilregeln") if isinstance(plan, dict) else None),
                            **matrix_live_log.session_delta(locked, session, source_turn_id=incoming.get("id"), names=_names))
                        # V65H (AMASTER §40, §41.1, §41/§49.1; 171 KONJ-1/RB-1b ohne
                        # Wortlisten): goal frame of the addressee (once per goal
                        # text) and the Themenbezug of THIS input to a still unsaid
                        # part meant for exactly this speaker. Additive: a failure
                        # leaves the committed input untouched.
                        try:
                            session = _goal_theme_step(conn, aid, session, incoming, natives, trace_id)
                        except WriterError:
                            raise
                        except Exception as _gt_exc:
                            matrix_live_log.live_log("GOAL_THEME", trace_id=trace_id, status="ERROR",
                                                     error=f"{type(_gt_exc).__name__}: {str(_gt_exc)[:200]}")
                    bound = incoming
                # V62 (AMASTER §28 Schritt 12/13 vor 15/27, §42, §44): what the
                # present figures perceived (this input, the previous answer,
                # a puppet line) is appraised and its immediate consequences
                # are committed BEFORE runtime is loaded for the formulation.
                try:
                    session = _appraise_perceived(conn, aid, session, natives, trace_id)
                except WriterError:
                    raise
                except Exception as _ap_exc:
                    # The committed input stays valid; the events stay pending
                    # and are appraised at the next prepare (review finding 9).
                    matrix_live_log.live_log("APPRAISAL", trace_id=trace_id, status="ERROR",
                                             error=f"{type(_ap_exc).__name__}: {str(_ap_exc)[:200]}")
                prepared = kernel.prepare_turn(
                    session,
                    truth=bound,
                    speaker=speaker,
                    present=present if isinstance(present, list) else [],
                    world=world if isinstance(world, dict) else {},
                )
                rules = []
                try:
                    trig = list_triggers(conn, aid or session.get("userId") or "admin")
                    rules = (trig.get("triggers") if isinstance(trig, dict) else trig) or []
                except (WriterError, KeyError, IsolationError):
                    rules = []
                cues = kernel.match_triggers_as_cues(bound.get("text") or "", session, rules if isinstance(rules, list) else [])
                bc = prepared.get("brainContext")
                if isinstance(bc, dict):
                    bc["triggerHints"] = cues
                truth = prepared["truth"]
                matrix_live_log.live_log(
                    "KERNEL_BIND",
                    trace_id=trace_id,
                    resolved_user_id=truth.get("user_id") or truth.get("userId"),
                    resolved_world_id=truth.get("world_id") or truth.get("worldId"),
                    resolved_session_id=truth.get("session_id") or truth.get("sessionId"),
                    resolved_speaker_id=truth.get("speaker_id") or truth.get("speakerId"),
                    resolved_input_actor_id=truth.get("input_actor_id") or truth.get("inputActorId"),
                    resolved_target_id=truth.get("target_id") or truth.get("targetId"),
                    resolved_authority=truth.get("authority"),
                    endpoint="/api/kernel/prepare",
                )
                last = "KERNEL_BIND"
                matrix_live_log.live_log(
                    "BRAIN_CONTEXT",
                    trace_id=trace_id,
                    writable=False,
                    speaker_id=truth.get("speaker_id") or truth.get("speakerId"),
                )
                last = "BRAIN_CONTEXT"
                # Grounded contradiction facts are already part of the committed
                # input. Formulation reads them; no hidden extra provider pass.
                from matrix_api import truth as _truth_mod
                sp_ = prepared.get("spiegel") or {}
                sp_["contradictionsText"] = _truth_mod.render_contradictions(sp_.get("contradictions") or [])
                # Stand 07 / K-01: the server's proof of THIS turn (identity, turn index, its own fired synapses and
                # contradictions); formulate and commit accept the turn only with it.
                _turn_beleg = beleg_ausstellen("turn", {**turn_kern(prepared["truth"]),
                                                        "turnIndex": int(session.get("turnIndex") or 0),
                                                        "fired": sp_.get("fired") or [],
                                                        "contradictions": sp_.get("contradictions") or []})
                return {
                    "ok": True,
                    "writable": False,
                    "turnBeleg": _turn_beleg,
                    "truth": prepared["truth"],
                    "brainContext": prepared["brainContext"],
                    "spiegel": prepared.get("spiegel"),
                    "fired": prepared.get("fired") or [],
                    "speakerCandidates": speaker_candidates,
                    "session": session,
                    "trace_id": trace_id,
                }

            _antwort = _run_read(_read)
            # 06a / M2: _run_read maps a consent-core failure to 503; if the input was already committed, say so
            if isinstance(_antwort, tuple) and len(_antwort) == 2 and _antwort[1] == 503:
                _j = _antwort[0].get_json(silent=True) or {}
                if str(_j.get("code") or "").startswith("NATIVE_"):
                    if last in _PREPARE_NACH_EINGABE:
                        return _prepare_teilcommit_antwort(_j.get("code"), body)
                    return _json_error(_j.get("code"), str(_j.get("message") or ""), 503, _j.get("code"),
                                       details={"eingabeGespeichert": False, "antwortVorbereitet": False})
            return _antwort
        except IsolationError as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="VALIDATION", exc=exc, last_successful_stage=last)
            matrix_live_log.live_log("VALIDATION", trace_id=trace_id, result="REJECT", reject_reason=str(exc))
            return _json_error(str(exc), str(exc), 403, "ISOLATION")
        except WriterError as exc:
            return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
        except NativeBoundaryError as exc:   # Stand 06 / K2 + 06a / M2: measured 400 KERNEL_FAILED before
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_PREPARE", exc=exc, last_successful_stage=last)
            try:
                _get_conn().rollback()
            except Exception:
                pass
            if last in _PREPARE_NACH_EINGABE:
                return _prepare_teilcommit_antwort(exc.code, body)
            return _json_error(exc.code, exc.message, 503, exc.code,
                               details={"eingabeGespeichert": False, "antwortVorbereitet": False})
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_PREPARE", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)

    @app.post("/api/kernel/commit")
    def kernel_commit():
        _llm_vorab.vorab_leeren()   # Stand 11: Lesungen der ersten Antwort gelten nur fuer diese Anfrage
        body = request.get_json(silent=True) or {}
        trace_id = str(body.get("trace_id") or body.get("traceId") or matrix_live_log.new_trace_id("kc"))
        last = "UI_REQUEST"
        aid, err = _kernel_actor(body)
        if err is not None and not aid:
            return err
        if isinstance(body.get("closePending"), dict):
            # V65T (AMASTER §24.2, §63; Plan v2 Schritt 6): the user closes the open input WITHOUT a response - explicit,
            # only when no attempt is running; same commit route, same SQL owners, no new route.
            _tt = str((body.get("closePending") or {}).get("turnTruthId") or "")

            def _close(conn):
                stored = _kernel_stored_session(conn, aid, body)
                try:
                    out = kernel.close_pending_input(stored, _tt, boot_id=SERVER_BOOT_ID, alive=_alive())
                except RuntimeError as _rexc:
                    if "unclear" in str(_rexc):
                        # V65W (C6): not proven ended -> never closed; generating the answer again stays possible
                        raise WriterError("Für diese Eingabe ist ein Antwortversuch nicht nachweisbar beendet (womöglich läuft er in einem "
                                          "anderen Serverprozess). Abschließen ist gesperrt; „Antwort erneut erzeugen“ ist "
                                          "nur auf ausdrücklichen Klick möglich. Nur der erste SQLite-Commit gewinnt.",
                                          409, "ATTEMPT_UNCLEAR")
                    raise WriterError("Für diese Eingabe läuft gerade ein Antwortversuch.", 409, "ATTEMPT_RUNNING")
                except ValueError:
                    raise WriterError("Keine offene Eingabe mit dieser Kennung.", 409, "NO_OPEN_INPUT")
                saved = kernel_session_response(conn, aid or out.get("userId") or "admin", out)
                matrix_live_log.live_log("INPUT_CLOSED", trace_id=trace_id, session_id=saved.get("id"), turn_truth_id=_tt)
                return {"ok": True, "session": saved}
            return _run_write(_close)
        try:
            session = body.get("session") or {}
            try:
                session = _kernel_stored_session(_get_conn(), aid, body) or session
            except IsolationError:
                raise
            raw = body.get("truth") or {}
            if not isinstance(raw, dict):
                raw = {}
            bound = dict(raw)
            bound["userId"] = aid or session.get("userId") or ""
            bound["worldId"] = session.get("worldId") or ""
            bound["sessionId"] = session.get("id") or ""
            bound["role"] = "character" if kernel.is_figure_followup_turn(raw) else (session.get("role") or "teilnehmer")
            bound["authority"] = normal_kernel_authority(session, raw)
            if session.get("avatarId") and not (bound.get("avatarId") or bound.get("avatar_id")):
                bound["avatarId"] = session.get("avatarId")
            bound["presentIds"] = list((session.get("scene") or {}).get("presentIds") or [])
            bound.pop("present_ids", None)
            _bind_scene_perception(session, bound)
            eingabe_binden(session, raw, bound, aid)   # Stand 07 / K-01: same binding as prepare
            truth = kernel.normalize_truth(bound)
            _kern_gesendet = turn_kern(truth)          # Stand 07 / K-01: compared with the Turn-Beleg below
            conn_read = _get_conn()
            natives = _sql_natives(conn_read, aid, session)
            speaker_in = body.get("speaker") or {}
            if not isinstance(speaker_in, dict):
                speaker_in = {}
            spid = speaker_in.get("id") or truth.get("speaker_id")
            authority = truth.get("authority") or ""
            if kernel.is_figure_followup_turn(raw):
                allowed = {str(c.get("id")) for c in natives if isinstance(c, dict)}
                present_ids = {str(x) for x in ((session.get("scene") or {}).get("presentIds") or [])}
                if (not spid or str(spid) not in allowed or str(spid) not in present_ids
                        or str(truth.get("speaker_id") or "") != str(spid)):
                    raise WriterError("Figure follow-up speaker is not a present character in this world",
                                      409, "SPEAKER_NOT_PRESENT")
            if spid and spid == session.get("avatarId") and not _normal_kernel_avatar_user_input(session, truth, spid):
                return _json_error("AVATAR_NOT_SPEAKER", "Avatar is never a normal figure speaker", 400, "AVATAR_NOT_SPEAKER")
            if spid:
                try:
                    speaker = _canonical_speaker(conn_read, aid, session, {"id": spid}, natives)
                except WriterError:
                    if authority in ("character", "autochat"):
                        raise
                    speaker = {"id": spid}
            else:
                speaker = {}
            # V92 Paket 16: the operator's answers to an identity clarification of THIS input (read projection, never stored)
            # V92 Paket 17 (Paket-16-Pruefung A, C, D): valid only for a question this server issued for exactly this input; a
            # figure's response to an input committed before has no open question (an answer there is unsolicited)
            _ktext = str(truth.get("text") or "")
            _kctx = _klaerung_kontext(session, _ktext, _klaerung_akteur(raw), natives)
            if session.get("pendingInputTurnId") and body.get("klaerungen") not in (None, [], ""):
                raise WriterError("Die Antwort auf die Rückfrage gilt nicht für diese Eingabe: Zu einer bereits gespeicherten Eingabe "
                                  "ist keine Rückfrage offen. Nichts wurde gespeichert.", 422, "KLAERUNG_UNGUELTIG",
                                  details={"grund": "keine_offene_frage"})
            _klaer = _klaerungen_pruefen(body.get("klaerungen"), _kctx, _ktext)
            present = kernel.with_klaerungen(natives, _klaer, _ktext)
            if (not _klaer and str(truth.get("input_kind") or "") in ("speech", "user") and _ktext
                    and not session.get("pendingInputTurnId")):
                from matrix_api.llm_contract import name_boundary_check as _name_boundary_check
                _nr = _name_boundary_check(conn_read, aid or "admin", _ktext, figures=present,
                                           data={"sessionId": session.get("id"), "worldId": session.get("worldId")})
                present = kernel.with_name_boundary_reading(_ktext, present, _nr)
            target_binding = _canonical_target(
                conn_read, aid, session, truth.get("target_id") or truth.get("targetId"), present,
                text=truth.get("text") or "", input_actor_id=truth.get("input_actor_id") or truth.get("inputActorId") or "",
            )
            truth["target_id"] = target_binding.get("target_id")
            truth["targetId"] = target_binding.get("target_id")
            matrix_live_log.live_log("TARGET_BIND", trace_id=trace_id,
                requested=(body.get("truth") or {}).get("target_id") or (body.get("truth") or {}).get("targetId"),
                resolved=truth["target_id"], reason=target_binding.get("reason"), ambiguous=target_binding.get("ambiguous"))
            result = body.get("result") or {}
            # Even canonical Avatar user-input mode may not be turned into
            # generated figure output by the normal commit endpoint.
            if spid and spid == session.get("avatarId") and _normal_kernel_avatar_output_present(result):
                return _json_error("AVATAR_NOT_SPEAKER", "Avatar output must come from the user, not normal figure generation", 400, "AVATAR_NOT_SPEAKER")
            # Stand 07 / K-01 (AMASTER §23, §28 Schritte 8/18-20, §50; KV §4): commit only the turn this server prepared and
            # only the formulation this server produced for it. Client `result`, `fired`, `contradictions` and `proposals`
            # are no source; a deviation is rejected visibly with nothing stored.
            _tb = beleg_lesen("turn", body.get("turnBeleg"))
            _tb_kern = {k: (_tb or {}).get(k) for k in _kern_gesendet}
            if (_tb is None or _tb_kern != _kern_gesendet or _tb.get("sid") != str(session.get("id") or "")
                    or int(_tb.get("turnIndex") or 0) != int(session.get("turnIndex") or 0)
                    or (spid and str(spid) != str(_tb.get("speaker") or ""))):
                _abw = sorted(k for k in _kern_gesendet if _tb is not None and _tb_kern.get(k) != _kern_gesendet[k])
                return _json_error("TURN_BELEG_UNGUELTIG", "Dieser Turn wurde so nicht vom Server vorbereitet "
                                   "(Turn, Sprecher, Eingabe oder Stand weichen ab, oder der Server wurde neu gestartet). "
                                   "Nichts wurde gespeichert.", 422, "TURN_BELEG_UNGUELTIG",
                                   details={"abweichend": _abw or ["beleg"], "turnIndexServer": session.get("turnIndex")})
            if spid and str(spid) != str(session.get("avatarId") or "") and not kernel.figure_speaker_eligible(
                    session, next((c for c in natives if isinstance(c, dict) and c.get("id") == spid), {"id": spid})):
                return _json_error("SPEAKER_NOT_CAPABLE", "Die Figur kann gerade nicht sprechen. Nichts wurde gespeichert.",
                                   409, "SPEAKER_NOT_CAPABLE", details={"speakerId": spid})
            for _key, _own in (("fired", _tb.get("fired") or []), ("contradictions", _tb.get("contradictions") or [])):
                if body.get(_key) not in (None, []) and _kanon(body.get(_key)) != _kanon(_own):
                    return _json_error("TURN_BELEG_UNGUELTIG", f"„{_key}“ stammt nicht aus der Vorbereitung dieses Turns. "
                                       "Nichts wurde gespeichert.", 422, "TURN_BELEG_UNGUELTIG", details={"abweichend": [_key]})
            if not formulierung_leer(result):
                _fb = beleg_lesen("formulierung", body.get("formulierungsBeleg"))
                _att = session.get("pendingInputAttempt") if isinstance(session.get("pendingInputAttempt"), dict) else {}
                # the latest FINISHED attempt of this open input (repos.mark_pending_attempt) must be the formulation
                _fertig = [a for a in (_att.get("attempts") or []) if isinstance(a, dict)
                           and a.get("state") in ("formuliert", "provider_fehler")] \
                    if str(_att.get("turnTruthId") or "") == str(truth.get("id") or "") else None
                if (_fb is None or _fb.get("sid") != str(session.get("id") or "") or _fb.get("tt") != str(truth.get("id") or "")
                        or _fb.get("speaker") != str(spid or "") or _fb.get("turnIndex") != _tb.get("turnIndex")
                        or _fb.get("turnBeleg") != beleg_hash(body.get("turnBeleg"))
                        or _kanon(formulierung_kern(result)) != _kanon(_fb.get("result"))
                        or (_fertig is not None and (not _fertig or str(_fertig[-1].get("id") or "") != str(_fb.get("attempt") or "")))):
                    return _json_error("FORMULIERUNG_UNGEBUNDEN", "Diese Figurenantwort hat der Server für diesen Turn nicht "
                                       "formuliert (fremder, veränderter oder älterer Text). Nichts wurde gespeichert.",
                                       422, "FORMULIERUNG_UNGEBUNDEN")
                _fk = _fb["result"]
                result = {"speech": _fk.get("speech") or "", "action": _fk.get("action"),
                          **({"proposals": _fk["proposals"]} if isinstance(_fk.get("proposals"), dict) else {})}
            else:
                result = {"speech": "", "action": None}
            fired = list(_tb.get("fired") or [])
            body = {**body, "contradictions": list(_tb.get("contradictions") or []), "proposals": None}
            matrix_live_log.live_log(
                "KERNEL_BIND",
                trace_id=trace_id,
                resolved_user_id=truth.get("user_id") or truth.get("userId"),
                resolved_world_id=truth.get("world_id") or truth.get("worldId"),
                resolved_session_id=truth.get("session_id") or truth.get("sessionId"),
                resolved_speaker_id=truth.get("speaker_id") or truth.get("speakerId"),
                resolved_target_id=truth.get("target_id") or truth.get("targetId"),
                resolved_authority=truth.get("authority"),
                endpoint="/api/kernel/commit",
            )
            last = "KERNEL_BIND"
            matrix_live_log.live_log("VALIDATION", trace_id=trace_id, result="BINDING_PASS", reject_reason=None, scope="Actor/Session/Sprecher gebunden; inhaltliche Prüfung je Fact steht in TURN_INPUT/TURN_RESPONSE/TURN_REGIE (valid=…, reason=…)")
            last = "VALIDATION"
            world = {}
            wid = session.get("worldId")
            if wid:
                try:
                    world = get_world(conn_read, str(wid), aid or session.get("userId") or "admin") or {}
                except (WriterError, KeyError, IsolationError):
                    world = {}
            if not isinstance(world, dict):
                world = {}
            # V65H (AMASTER §34.1 Offenbarung, §35; 171 KONJ-1 Offenbarungsstatus):
            # whether HER speech now says the unsaid part of her goal to the person
            # she answers — a model reading with a literal quote; the kernel checks
            # and records it. Only when such a goal exists and this turn addressed
            # it or her plan reads her speech as a disclosure. Additive.
            # Stand 11: die Fachlesungen zu IHRER Antwort kommen aus derselben Formulierung (Proposals, durch den Formulierungsbeleg
            # gebunden) - die Lesestellen unten machen keinen eigenen Modellaufruf mehr.
            _props_l = (result.get("proposals") if isinstance(result, dict) and isinstance(result.get("proposals"), dict)
                        else body.get("proposals") if isinstance(body.get("proposals"), dict) else {})
            _llm_vorab.vorab_registrieren((_props_l or {}).get("lesungen"), quelle="formulierung")
            # Stand 10B: Offenbarung, Bewegung/Wirkung, eigener Koerper und Grenzumfang lesen alle nur IHRE Antwort und schreiben
            # in getrennte Felder (offenbarung / wirkung / Koerperlesung / plan.grenze) - sie laufen gleichzeitig. Nur wenn das
            # Zusammenfuehren der Client-Vorschlaege unten ein No-op ist (dann sind die Eingaben identisch mit dem Ablauf nacheinander).
            _vorab = {}
            if isinstance(result, dict) and (isinstance(result.get("proposals"), dict) or not isinstance(body.get("proposals"), dict)):
                from flask import current_app as _ca
                _speech_v = str(result.get("speech") or "")
                _sid_v = str((speaker or {}).get("id") or "")

                def _grenze_vorab(c, _r=result):
                    _pc = _r.get("proposals") if isinstance(_r.get("proposals"), dict) else None
                    if _pc is None or not isinstance(_pc.get("plan"), dict):
                        return None
                    _pl = _pc["plan"]
                    if not isinstance(_pl.get("grenze"), dict):
                        _pl = _answer_boundary_candidate(session, _pl, _speech_v, (speaker or {}).get("id"),
                                                         truth.get("input_actor_id") or truth.get("inputActorId"), natives)
                    if not isinstance(_pl, dict) or not isinstance(_pl.get("grenze"), dict):
                        return None
                    return (_pl["grenze"], _consent_scope_check(c, aid, _pl["grenze"], _speech_v,
                                                                {"sessionId": session.get("id"), "worldId": session.get("worldId"),
                                                                 "sourceTurnId": truth.get("id"), "speakerId": _sid_v},
                                                                trace_id=trace_id, where="figur"))
                _vorab = lesungen_gleichzeitig(_ca.config.get("MATRIX_DB"), {
                    "offb": lambda c, _r=result: _disclosure_step(c, aid, session, truth, speaker, _r, natives, trace_id),
                    "wchk": lambda c, _r=result: _effect_check_step(c, aid, session, truth, speaker, _r, natives, trace_id),
                    "klesung": lambda c, _r=result: _koerper_check_step(c, aid, session, truth, speaker, _r, trace_id),
                    "grenze": _grenze_vorab})
            try:
                _offb = _vorab_oder(_vorab, "offb", lambda: _disclosure_step(conn_read, aid, session, truth, speaker, result, natives, trace_id))
            except Exception as _od_exc:
                _offb = None
                matrix_live_log.live_log("GOAL_DISCLOSURE", trace_id=trace_id, status="ERROR",
                                         error=f"{type(_od_exc).__name__}: {str(_od_exc)[:200]}")
            if _offb:
                result = {**result, "proposals": {**(result.get("proposals") if isinstance(result.get("proposals"), dict) else {}),
                                                  "offenbarung": _offb}}
            # V65I (AMASTER §24.2/§24.7): a proposed body effect on another figure
            # (gewalt/fesseln/befreien) is confirmed by a separate reading with a
            # literal quote before any writer; otherwise no body effect (audit stays).
            if isinstance(result, dict) and not isinstance(result.get("proposals"), dict) and isinstance(body.get("proposals"), dict):
                result = {**result, "proposals": body.get("proposals")}   # same source commit_turn reads
            try:
                _wchk = _vorab_oder(_vorab, "wchk", lambda: _effect_check_step(conn_read, aid, session, truth, speaker, result, natives, trace_id))
            except Exception as _we_exc:
                _wp = (result.get("proposals") or {}).get("wirkung") if isinstance(result.get("proposals"), dict) else None
                _wchk = kernel.apply_effect_check(_wp, str(result.get("action") or ""), None) if kernel.effect_check_needed(_wp, result.get("action")) else None
                matrix_live_log.live_log("EFFECT_CHECK", trace_id=trace_id, status="ERROR",
                                         error=f"{type(_we_exc).__name__}: {str(_we_exc)[:200]}")
            if _wchk is not None:
                result = {**result, "proposals": {**(result.get("proposals") if isinstance(result.get("proposals"), dict) else {}),
                                                  "wirkung": _wchk}}
            # V92 Paket 18: the server's reading of the change her action makes to her own body (passed to the writer explicitly)
            try:
                _klesung = _vorab_oder(_vorab, "klesung", lambda: _koerper_check_step(conn_read, aid, session, truth, speaker, result, trace_id))
            except Exception as _kc_exc:
                _klesung = None
                matrix_live_log.live_log("KOERPER_CHECK", trace_id=trace_id, status="ERROR", error=f"{type(_kc_exc).__name__}: {str(_kc_exc)[:200]}")
            # V65W (Tiefenpruefung v1 P06/C1): the figure's own body act against standing restricted boundaries - the
            # server's act reading only (a client-supplied verdict is dropped); on error the act stays unknown.
            _wp2 = (result.get("proposals") or {}).get("wirkung") if isinstance(result, dict) and isinstance(result.get("proposals"), dict) else None
            if isinstance(_wp2, dict):
                _wp2 = {k: v for k, v in _wp2.items() if k != "grenzBezug"}
                try:
                    _ok2, _kind2 = kernel.effect_kind_from_wirkung(_wp2.get("art"))
                    if _ok2 and _kind2 in kernel._CONSENT_ACTS:
                        _sid2 = str((speaker or {}).get("id") or "")
                        _v2 = _boundary_readings(conn_read, aid, session, _sid2, str((speaker or {}).get("name") or ""),
                                                 str(result.get("action") or ""), str(result.get("action") or ""), natives,
                                                 {"sessionId": session.get("id"), "worldId": session.get("worldId"),
                                                  "sourceTurnId": truth.get("id"), "speakerId": _sid2}, trace_id=trace_id, where="figur")
                        if _v2 is not None:
                            _wp2["grenzBezug"] = _v2
                except Exception as _gb_exc:
                    matrix_live_log.live_log("BOUNDARY_REFERENCE", trace_id=trace_id, status="ERROR", error=f"{type(_gb_exc).__name__}: {str(_gb_exc)[:200]}")
                result = {**result, "proposals": {**result["proposals"], "wirkung": _wp2}}
            # V65V (Nachpruefung v1 K1/K3/K4): the boundary scope and denials of the figure's speech are read once more
            # by the server before the write; on error the components stay unconfirmed (verdicts dropped).
            _props_c = result.get("proposals") if isinstance(result, dict) and isinstance(result.get("proposals"), dict) else None
            try:
                if _props_c is not None and isinstance(_props_c.get("plan"), dict) and not isinstance(_props_c["plan"].get("grenze"), dict):
                    _cand = _answer_boundary_candidate(session, _props_c["plan"], str(result.get("speech") or ""), (speaker or {}).get("id"),
                                                       truth.get("input_actor_id") or truth.get("inputActorId"), natives)
                    if _cand is not _props_c["plan"]:
                        _props_c = {**_props_c, "plan": _cand}
                        result = {**result, "proposals": _props_c}
                if _props_c is not None and isinstance(_props_c.get("plan"), dict) and isinstance(_props_c["plan"].get("grenze"), dict):
                    _sid_c = str((speaker or {}).get("id") or "")
                    _gv = _vorab.get("grenze")
                    if _gv is not None and _gv[0] == "ok" and isinstance(_gv[1], tuple) and _gv[1][0] == _props_c["plan"]["grenze"]:
                        _g_c = _gv[1][1]          # Stand 10B: gleichzeitig gelesen, gleiche Eingabe (Grenze und Rede)
                    elif _gv is not None and _gv[0] == "fehler":
                        raise _gv[1]              # wie im Ablauf nacheinander: Fehler der Lesung -> except unten
                    else:
                        _g_c = _consent_scope_check(conn_read, aid, _props_c["plan"]["grenze"], str(result.get("speech") or ""),
                                                    {"sessionId": session.get("id"), "worldId": session.get("worldId"),
                                                     "sourceTurnId": truth.get("id"), "speakerId": _sid_c}, trace_id=trace_id, where="figur")
                    result = {**result, "proposals": {**_props_c, "plan": {**_props_c["plan"], "grenze": _g_c}}}
                result = _statement_check_step(conn_read, aid, session, speaker, result, natives, trace_id)
            except Exception as _cc_exc:
                _pp = result.get("proposals") if isinstance(result.get("proposals"), dict) else {}
                if isinstance(_pp.get("plan"), dict) and isinstance(_pp["plan"].get("grenze"), dict):
                    _pp = {**_pp, "plan": {**_pp["plan"], "grenze": {k: v for k, v in _pp["plan"]["grenze"].items() if k != "pruefung"}}}
                if isinstance(_pp.get("aussagen"), list):
                    _pp = {**_pp, "aussagen": [{k: v for k, v in a.items() if k != "pruefung"} for a in _pp["aussagen"] if isinstance(a, dict)]}
                result = {**result, "proposals": _pp}
                matrix_live_log.live_log("CONSENT_CHECK", trace_id=trace_id, status="ERROR", error=f"{type(_cc_exc).__name__}: {str(_cc_exc)[:200]}")
            # When prepare committed the input, finish its SAME TurnTruth.
            # Legacy autochat/observer events still use the one-shot writer.
            _raw_tt = str((body.get("truth") or {}).get("id") or "") if isinstance(body.get("truth"), dict) else ""
            if (_raw_tt and _raw_tt != str(session.get("pendingInputTurnId") or "")
                    and any(isinstance(t, dict) and str(t.get("id") or "") == _raw_tt for t in session.get("turnTruths") or [])):
                # V65T (Plan v2 Schritt 6, v3.3 Race): a response for an input that is no longer open (answered or closed
                # without answer) is not committed again as a new one-shot turn.
                return _json_error("TURN_NOT_OPEN", "Diese Eingabe ist bereits abgeschlossen; die Antwort wird nicht gespeichert.", 409, "TURN_NOT_OPEN")
            commit_phase = "response" if session.get("pendingInputTurnId") else "complete"
            out = kernel.commit_turn(
                session,
                truth=truth,
                speaker=speaker,
                present=present,
                result=result,
                fired=fired,
                phase=commit_phase,
                accept_llm_state=False,
                proposals=(result.get("proposals") if isinstance(result, dict) and isinstance(result.get("proposals"), dict) else (body.get("proposals") if isinstance(body.get("proposals"), dict) else None)),
                recall_count=(int(body.get("recallCount")) if str(body.get("recallCount") or "").isdigit() else None),
                # The input is already committed and grounded. Do not call
                # the external plan interpreter a second time for this turn.
                user_plan=(None if commit_phase == "response" else _extract_user_plan(conn_read, aid, session, truth, present)),
                contradictions=(body.get("contradictions") if isinstance(body.get("contradictions"), list) else None),
                world=world,
                koerper_lesung=_klesung,
            )
            if commit_phase == "complete":
                _ask_identity(out, truth, target_binding, _klaer, natives, trace_id, kontext=_kctx, text=_ktext)
                _reject_unexecutable_input(out, truth, natives, trace_id)
            facts = out.get("facts") or []
            last_fact = facts[-1] if facts else {}
            turn_facts = [f for f in facts if isinstance(f, dict) and str(f.get("sourceTurnId") or f.get("source_turn_id") or "") == str(truth.get("id") or "")]
            matrix_live_log.live_log(
                "WRITER",
                trace_id=trace_id,
                owner="kernel",
                table="session_facts",
                record_id=last_fact.get("id"),
                fact_type=last_fact.get("kind"),
                commit_status="pending_sqlite",
                turn_facts=[{"id": f.get("id"), "kind": f.get("kind"), "validated": f.get("validated")} for f in turn_facts][:16],
            )
            # V60 (AMASTER §54 Punkt 15, §68 Nr. 70): what the reply really
            # changed, per writer. Diagnosis only; reads the two snapshots.
            _names = {str(c.get("id")): str(c.get("name") or "") for c in natives if isinstance(c, dict)}
            _props = (result.get("proposals") if isinstance(result, dict) and isinstance(result.get("proposals"), dict) else {}) or {}
            matrix_live_log.live_log("TURN_RESPONSE", trace_id=trace_id, source_turn_id=truth.get("id"),
                speaker=_names.get(str((speaker or {}).get("id") or ""), str((speaker or {}).get("id") or "")),
                speech=str((result or {}).get("speech") or ""), action=(result or {}).get("action"),
                proposals={k: _props.get(k) for k in ("wirkung", "emotion", "beziehung", "plan", "synapsen") if k in _props},
                **matrix_live_log.session_delta(session, out, source_turn_id=truth.get("id"), names=_names))
            last = "WRITER"

            def _persist(conn):
                saved = kernel_session_response(conn, aid or out.get("userId") or "admin", out)
                matrix_live_log.live_log("SQLITE_COMMIT", trace_id=trace_id, status="PASS", session_id=saved.get("id"))
                extra: dict = {}
                extra_warnings: list[str] = []
                sid = saved.get("id") or session.get("id")
                sp = (speaker or {}).get("id") or truth.get("speaker_id")
                # V59C (AMASTER §25): the address edge of a reply points to the
                # reply's own bound target, never back to the speaker itself.
                _reply = next((f for f in reversed(out.get("facts") or []) if isinstance(f, dict)
                               and f.get("kind") == "speech" and str(f.get("actorId")) == str(sp)
                               and str(f.get("sourceTurnId") or "") == str(truth.get("id") or "")), None)
                tg = (_reply or {}).get("targetId")
                if tg and str(tg) == str(sp):
                    tg = None
                # V52: no character-stem write from generated response text.
                # SceneFacts, witnessed knowledge, session memories and relations
                # were committed by kernel_session_response above. Those are
                # recalled on the next turn; the language model only formulates.
                if sid and sp and tg:
                    try:
                        extra["graph"] = create_graph_edge(
                            conn,
                            {
                                "sessionId": sid,
                                "fromId": sp,
                                "toId": tg,
                                "kind": "turn_address",
                                "sourceTurnId": truth.get("id"),
                            },
                            aid or "admin",
                        ).get("edge")
                    except WriterError as hook_exc:
                        extra_warnings.append(f"graph: {hook_exc.message}")
                        extra["graphError"] = {"error": hook_exc.error, "message": hook_exc.message}
                cue = truth.get("text") or ""
                if sid and cue:
                    try:
                        extra["recall"] = recall_patterns(
                            conn, sid, aid or "admin", str(cue), character_id=sp
                        )
                    except WriterError as hook_exc:
                        extra_warnings.append(f"recall: {hook_exc.message}")
                        extra["recallError"] = {"error": hook_exc.error, "message": hook_exc.message}
                if extra_warnings:
                    extra["warnings"] = extra_warnings
                return {"ok": True, "session": saved, "trace_id": trace_id, **extra}

            return _run_write(_persist)
        except IsolationError as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="VALIDATION", exc=exc, last_successful_stage=last)
            matrix_live_log.live_log("VALIDATION", trace_id=trace_id, result="REJECT", reject_reason=str(exc))
            return _json_error(str(exc), str(exc), 403, "ISOLATION")
        except WriterError as exc:
            return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
        except NativeBoundaryError as exc:   # Stand 06 / K2: measured 400 KERNEL_FAILED before
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_COMMIT", exc=exc, last_successful_stage=last)
            try:
                _get_conn().rollback()
            except Exception:
                pass
            return _json_error(exc.code, exc.message, 503, exc.code)
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_COMMIT", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)

    @app.post("/api/amaster/system-loop")
    def api_amaster_system_loop():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        return _run_write(lambda conn: run_bound_system(conn, actor or "admin"))

    @app.post("/api/analyze")
    def api_analyze():
        actor, err = get_actor(mutating=False)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        text = ""
        world_id = None
        title = ""
        if isinstance(body, dict):
            text = str(body.get("text") or body.get("source") or "")
            world_id = body.get("worldId") or body.get("world_id")
            title = str(body.get("title") or body.get("name") or "")
        analysis = analyze_text(text, world_id=str(world_id) if world_id else None, source_title=title)
        analysis = enrich_analysis(analysis, text, title=title, network=False)
        # V25.1 (AMASTERv2 §11, Vertrag §7/§8): Analyse über den konfigurierten Provider,
        # sofern vorhanden; sonst lokal, ehrlich markiert (analysisSource/llmError).
        use_llm = body.get("llm", True) if isinstance(body, dict) else True
        if use_llm is not False:
            analysis = analyze_with_llm(_get_conn(), actor or "admin", text, title, analysis, body if isinstance(body, dict) else {})
        else:
            analysis["analysisSource"] = "local"
        return jsonify(analysis), 200

    @app.post("/api/genre/policy")
    def api_genre_policy():
        actor, err = get_actor(mutating=False)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        genre = str((body or {}).get("genre") or "") if isinstance(body, dict) else ""
        text = str((body or {}).get("text") or "") if isinstance(body, dict) else ""
        return jsonify(evaluate_genre(genre, text)), 200

    @app.post("/api/vector/search")
    def api_vector_search():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        q = str((body or {}).get("q") or (body or {}).get("query") or "")
        try:
            limit = int((body or {}).get("limit") or 20)
        except Exception:
            limit = 20
        return _run_read(lambda conn: vector_search(conn, actor or "", q, limit=limit))

    @app.post("/api/search")
    def api_search():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        q = str((body or {}).get("q") or (body or {}).get("query") or "")
        return _run_read(lambda conn: vector_search(conn, actor or "", q, limit=20))

    # V65Y (Gesamtpruefung V65X G12; AMASTER §3 "keine Demo als Ersatz fuer das echte Produkt"): OCR runs in the browser
    # (src/lib/matrix/ocr.ts, tesseract.js). The server stub POST /api/ocr ("local-stub", echoed the text) had no caller
    # and is removed.

    @app.post("/api/speech/stt")
    def api_speech_stt():
        actor, err = get_actor(mutating=False)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        transcript = str((body or {}).get("transcript") or (body or {}).get("text") or "") if isinstance(body, dict) else ""
        return jsonify({"ok": True, "device": False, "mode": "contract", "engine": "local-stub", "transcript": transcript}), 200

    @app.post("/api/speech/tts")
    def api_speech_tts():
        actor, err = get_actor(mutating=False)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        text = str((body or {}).get("text") or "") if isinstance(body, dict) else ""
        return jsonify({"ok": True, "device": False, "spoken": False, "engine": "local-stub", "text": text[:400]}), 200

    @app.post("/api/llm/formulate")
    def api_llm_formulate():
        actor, err = get_actor(mutating=True)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        body = body if isinstance(body, dict) else {}
        _sid, _tt = str(body.get("sessionId") or ""), str(body.get("sourceTurnId") or "")
        # Stand 07 / K-01: a character formulation belongs to a turn this server prepared (session, TurnTruth, speaker,
        # turn index from the Turn-Beleg - the client's turnIndex is not the source)
        _tb = beleg_lesen("turn", body.get("turnBeleg"))
        if (_tb is None or _tb.get("sid") != _sid or _tb.get("tt") != _tt
                or (str(body.get("speakerId") or "") and str(body.get("speakerId")) != _tb.get("speaker"))):
            return _json_error("TURN_BELEG_UNGUELTIG", "Diese Formulierung gehört zu keinem vom Server vorbereiteten Turn "
                               "(Session, Turn oder Sprecher stimmen nicht, oder der Server wurde neu gestartet). "
                               "Nichts wurde formuliert oder gespeichert; bitte den Turn neu senden.", 422, "TURN_BELEG_UNGUELTIG")
        body = {**body, "speakerId": _tb.get("speaker"), "turnIndex": _tb.get("turnIndex")}

        _attempt_id = _uuid.uuid4().hex[:10]

        def _mark(state: str, **extra):
            # V65T (Plan v2 Schritt 6): orchestration status of the open input's attempt (envelope only, own short write)
            # V65U (Codegutachten v1 N4): this request's own attempt id + the server start id; per-attempt transitions.
            if not _sid or not _tt:
                return
            # V65W (C6): before its first attempt this process takes its start lock - the proof of life other server
            # processes read (taken once, held until the process ends)
            _proof = hold_boot_lock(_db_file_now()) if state == "laeuft" else True
            try:
                from matrix_api.repos import mark_pending_attempt
                _run_write(lambda conn: {"ok": mark_pending_attempt(conn, actor or "admin", _sid, _tt,
                                                                    {"state": state, "id": _attempt_id, "boot": SERVER_BOOT_ID,
                                                                     **({"lebensnachweis": BOOT_PROOF} if _proof else {}), **extra})})
            except Exception as _mexc:   # status only - never blocks the formulation
                matrix_live_log.live_log("PENDING_ATTEMPT", trace_id=_tt, status="FAIL", error=str(_mexc)[:120])

        _now_iso = lambda: datetime.now().isoformat(timespec="seconds")  # noqa: E731
        _mark("laeuft", since=_now_iso())
        try:
            out = formulate_from_config(_get_conn(), actor or "admin", body)
        except WriterError as exc:
            _mark("provider_fehler", error=str(exc.message)[:120], at=_now_iso())
            return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
        except Exception as exc:
            _mark("provider_fehler", error=f"{type(exc).__name__}: {str(exc)[:100]}", at=_now_iso())
            raise
        if isinstance(out, dict) and (out.get("ok") is False or (out.get("llmError") and out.get("source") != "llm")):
            _mark("provider_fehler", error=str(out.get("llmError") or out.get("error") or "")[:120], at=_now_iso())
        else:
            _mark("formuliert", at=_now_iso())
        if isinstance(out, dict) and out.get("ok") is not False and isinstance(out.get("result"), dict):
            # Stand 07 / K-01: exactly this server formulation may be committed for this turn (AMASTER §28 Schritt 20).
            # Also for the local Synapse text, which P25 marks as attempt `provider_fehler` (llmError LLM_REQUIRED).
            out["formulierungsBeleg"] = beleg_ausstellen("formulierung", {
                "sid": _sid, "tt": _tt, "speaker": _tb.get("speaker"), "turnIndex": _tb.get("turnIndex"),
                "turnBeleg": beleg_hash(body.get("turnBeleg")), "attempt": _attempt_id,
                "result": formulierung_kern(out["result"])})
        if isinstance(out, tuple) and len(out) == 2 and isinstance(out[1], int):
            return jsonify(out[0]), out[1]
        return jsonify(out), 200

    @app.post("/api/llm/world")
    def api_llm_world():
        actor, err = get_actor(mutating=False)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        return _run_read(lambda conn: generate_world_from_config(conn, actor or "admin", body if isinstance(body, dict) else {}))

    @app.post("/api/llm/characters")
    def api_llm_characters():
        actor, err = get_actor(mutating=False)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        return _run_read(lambda conn: generate_characters_from_config(conn, actor or "admin", body if isinstance(body, dict) else {}))

    @app.post("/api/llm/profile")
    def api_llm_profile():
        actor, err = get_actor(mutating=False)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        return _run_read(lambda conn: suggest_profile_from_config(conn, actor or "admin", body if isinstance(body, dict) else {}))

    @app.post("/api/llm/complete-profiles")
    def api_llm_complete_profiles():
        actor, err = get_actor(mutating=False)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        return _run_read(lambda conn: complete_profiles_from_config(conn, actor or "admin", body if isinstance(body, dict) else {}))

    @app.post("/api/llm/compass")
    def api_llm_compass():
        actor, err = get_actor(mutating=False)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        return _run_read(lambda conn: derive_compass_from_config(conn, actor or "admin", body if isinstance(body, dict) else {}))

    @app.post("/api/llm/ping")
    @app.get("/api/llm/ping")
    def api_llm_ping():
        actor, err = get_actor(mutating=False)
        if err is not None:
            return err
        body = request.get_json(silent=True) or {}
        return _run_read(lambda conn: ping_provider(conn, actor or "admin", body if isinstance(body, dict) else {}))

    @app.post("/api/kernel/god")
    def kernel_god():
        body = request.get_json(silent=True) or {}
        trace_id = str(body.get("trace_id") or body.get("traceId") or matrix_live_log.new_trace_id("kg"))
        last = "UI_REQUEST"
        matrix_live_log.live_log("UI_REQUEST", trace_id=trace_id, endpoint="/api/kernel/god")
        _llm_vorab.vorab_leeren()   # Stand 11: Lesungen der ersten Antwort gelten nur fuer diese Anfrage
        aid, err = _kernel_actor(body)
        if err is not None and not aid:
            return err
        try:
            from matrix_api.llm_contract import name_boundary_check as _name_boundary_check
            _ngod_text = str(body.get("text") or "")
            _nread_conn = _get_conn()
            _nread_session = _kernel_stored_session(_nread_conn, aid, body)
            _nread_cast = _sql_natives(_nread_conn, aid, _nread_session)
            _ngod_names = _name_boundary_check(_nread_conn, aid or "admin", _ngod_text, figures=_nread_cast,
                                                data={"sessionId": _nread_session.get("id"), "worldId": _nread_session.get("worldId")})
            def _persist(conn):
                nonlocal last
                session = _kernel_stored_session(conn, aid, body)
                matrix_live_log.live_log(
                    "KERNEL_BIND",
                    trace_id=trace_id,
                    resolved_user_id=aid or session.get("userId"),
                    resolved_world_id=session.get("worldId"),
                    resolved_session_id=session.get("id"),
                    resolved_authority="god",
                    endpoint="/api/kernel/god",
                )
                last = "KERNEL_BIND"
                target_id = body.get("targetId") or body.get("target_id")
                matrix_live_log.live_log("VALIDATION", trace_id=trace_id, result="BINDING_PASS", reject_reason=None, scope="Actor/Session/Sprecher gebunden; inhaltliche Prüfung je Fact steht in TURN_INPUT/TURN_RESPONSE/TURN_REGIE (valid=…, reason=…)")
                last = "VALIDATION"
                god_world, god_natives = _kernel_world_and_natives(conn, aid, session)
                god_scope = str(body.get("scope") or "auto").strip().lower()
                # V65W (Tiefenpruefung v1 P03/C4; AMASTER §20 Z. 949): does this God text end the scene or begin a new one?
                # One reading of the whole text (the route's existing reading place); applied once, with the first effect.
                _ueb_god = _scene_transition_read(conn, aid, str(body.get("text") or ""), session, trace_id=trace_id, where="god",
                                                  auswahl=body.get("szenenuebergang"))
                applied_list: list = []
                unclear_list: list = []
                if god_scope in ("auto", "strukturiert", "", "action"):
                    # V43: freier God-Text → strukturierte Einzelanweisungen (Provider oder lokal), jede über den
                    # zuständigen God-Scope angewendet; Unklares wird zurückgemeldet, nicht erfunden.
                    from matrix_api import god_extract as _ge

                    figs = [n for n in (god_natives or []) if isinstance(n, dict)]
                    figs = kernel.with_name_boundary_reading(_ngod_text, figs, _ngod_names)
                    raw = None
                    try:
                        raw = extract_god_instructions(conn, aid or "admin", body.get("text") or "", figures=[str(f.get("name") or "") for f in figs])
                    except Exception:
                        raw = None
                    if raw and not _ngod_names:
                        # Stand 11: die Namenslesung kam mit dieser ersten Antwort - jetzt anwenden (Kernel prueft sie am Originaltext)
                        _ngod_names = _name_boundary_check(conn, aid or "admin", _ngod_text, figures=figs,
                                                           data={"sessionId": session.get("id"), "worldId": session.get("worldId")})
                        figs = kernel.with_name_boundary_reading(_ngod_text, figs, _ngod_names)
                    instructions, unclear_list = _ge.normalize_llm_instructions(raw, figs, source_text=body.get("text") or "") if raw else _ge.local_god_instructions(body.get("text") or "", figs, list((session.get("scene") or {}).get("presentIds") or []))
                    # A provider reply rejected by the original-input validator must NOT be
                    # reinterpreted and committed by a weaker local parser (fail closed).
                    if god_scope == "action":
                        # V74 / §46.6: the UI's explicit action scope uses the
                        # SAME semantic binding and owner as auto. Never pass
                        # arbitrary prose to the old character-memory writer.
                        actions = [i for i in instructions if i.get("art") == "handlung"]
                        # Explicit action scope never bypasses a failed provider reading.
                        other_kinds = [i for i in instructions if i.get("art") != "handlung"]
                        unclear_list.extend({"text": str(i.get("text") or "")[:200],
                                             "grund": "kein Handlungs-Effect im gewählten God-Scope"}
                                            for i in other_kinds)
                        instructions = actions
                        if target_id and any(str(i.get("targetId")) != str(target_id) for i in instructions):
                            raise WriterError("Ausgewählte handelnde Figur widerspricht dem Handlungstext", 422,
                                              "GOD_ACTION_ACTOR_CONFLICT")
                    if not instructions:
                        raise WriterError("God-Text ließ sich nicht binden: " + "; ".join(str(u.get("grund") or "") for u in unclear_list[:3]), 422, "GOD_UNBOUND")
                    out = session
                    # V65J (AMASTER §46.1/§43/§24.2/§24.6; Prüfbericht v2.2 E08/E19): a God fact about a
                    # body is read once into the typed state it sets; that reading - not a word list - is
                    # the body writer's input. Without a provider the documented local path stays.
                    from matrix_api.llm_contract import god_body_state, provider_reading_allowed
                    _god_read = provider_reading_allowed(conn, aid or "admin")
                    for ins in instructions:
                        scope_key = _ge.ART_TO_SCOPE.get(str(ins.get("art")), "scene")
                        _bstate = None
                        _gdata = {"sessionId": session.get("id"), "worldId": session.get("worldId")}
                        if str(ins.get("art")) == "zustand" and ins.get("source") == "llm":
                            # God auto: the first model can label a physical fact as a
                            # generic character state. Check the *meaning* once using
                            # the existing body reader, then route to the one writer.
                            # If the reader cannot establish a non-body scope, fail
                            # closed as an unconfirmed body command (applied=false).
                            if ins.get("targetId") and _god_read:
                                _bstate = god_body_state(conn, aid or "admin", text=str(ins.get("text") or ""),
                                                         figure=str(ins.get("targetName") or ""), data=_gdata) or {}
                            scope_key = kernel.god_auto_state_scope(_bstate)
                        if scope_key == "body" and ins.get("targetId") and _god_read:
                            if _bstate is None:
                                _bstate = god_body_state(conn, aid or "admin", text=str(ins.get("text") or ""),
                                                         figure=str(ins.get("targetName") or ""), data=_gdata) or {}
                            # V92 Paket 19 (Pruefung P18 N5-N7): quote mandatory + confirmation at the quote, for exactly this target
                            _bstate = _koerper_bestaetigen(conn, aid, _bstate, text=str(ins.get("text") or ""), figur=str(ins.get("targetName") or ""),
                                                           authority="god", data=_gdata, trace_id=trace_id, quelle="god",
                                                           figur_id=ins.get("targetId"))
                            _bvals, _baud = kernel.authority_body_change(_bstate, str(ins.get("text") or ""), figur_id=ins.get("targetId"), authority="god")
                            matrix_live_log.live_log("GOD_BODY", trace_id=trace_id, figure=ins.get("targetName"), text=str(ins.get("text") or "")[:200],
                                                     modell=_bstate or None, werte=_bvals, pruefung=_baud)
                            if not _bvals:
                                unclear_list.append({"text": str(ins.get("text") or "")[:200], "grund": "Körperzustand nicht sicher lesbar oder nicht bestätigt - nicht angewendet"})
                        out = kernel.apply_god(
                            out,
                            str(ins.get("text") or ""),
                            scope_key,
                            ins.get("targetId"),
                            other_id=ins.get("otherId"),
                            world=god_world if isinstance(god_world, dict) else None,
                            natives=god_natives if isinstance(god_natives, list) else None,
                            body_state=_bstate,
                            uebergang=_ueb_god,
                        )
                        _ueb_god = None   # the transition belongs to the God input, not to each of its instructions
                        applied_list.append({"art": ins.get("art"), "scope": scope_key, "target": ins.get("targetName"), "other": ins.get("otherName"), "text": ins.get("text"), "source": ins.get("source"), "applied": bool((out.get("godFacts") or [{}])[-1].get("applied", True)) if out.get("godFacts") else True})
                else:
                    _bstate = None
                    if kernel._god_scope_key(god_scope) == "body" and target_id:
                        from matrix_api.llm_contract import god_body_state, provider_reading_allowed
                        if provider_reading_allowed(conn, aid or "admin"):
                            _tname = next((str(n.get("name") or "") for n in (god_natives or []) if isinstance(n, dict) and str(n.get("id")) == str(target_id)), "")
                            _gdata = {"sessionId": session.get("id"), "worldId": session.get("worldId")}
                            _bstate = god_body_state(conn, aid or "admin", text=str(body.get("text") or ""), figure=_tname, data=_gdata) or {}
                            # V92 Paket 19 (Pruefung P18 N5-N7): quote mandatory + confirmation at the quote, for exactly this target
                            _bstate = _koerper_bestaetigen(conn, aid, _bstate, text=str(body.get("text") or ""), figur=_tname, authority="god",
                                                           data=_gdata, trace_id=trace_id, quelle="god", figur_id=target_id)
                            matrix_live_log.live_log("GOD_BODY", trace_id=trace_id, figure=_tname, text=str(body.get("text") or "")[:200],
                                                     modell=_bstate or None,
                                                     pruefung=kernel.authority_body_change(_bstate, str(body.get("text") or ""), figur_id=target_id, authority="god")[1])
                    out = kernel.apply_god(
                        session,
                        body.get("text") or "",
                        god_scope,
                        target_id,
                        other_id=body.get("otherId") or body.get("other_id"),
                        world=god_world if isinstance(god_world, dict) else None,
                        natives=god_natives if isinstance(god_natives, list) else None,
                        body_state=_bstate,
                        uebergang=_ueb_god,
                    )
                matrix_live_log.live_log(
                    "WRITER",
                    trace_id=trace_id,
                    owner="kernel",
                    table="sessions",
                    fact_type="god",
                    commit_status="pending_sqlite",
                )
                last = "WRITER"
                saved = kernel_session_response(conn, aid or out.get("userId") or "admin", out)
                matrix_live_log.live_log("SQLITE_COMMIT", trace_id=trace_id, status="PASS", session_id=saved.get("id"))
                return {"ok": True, "session": saved, "trace_id": trace_id, "applied": applied_list, "unclear": unclear_list}

            return _run_write(_persist)
        except IsolationError as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="VALIDATION", exc=exc, last_successful_stage=last)
            matrix_live_log.live_log("VALIDATION", trace_id=trace_id, result="REJECT", reject_reason=str(exc))
            return _json_error(str(exc), str(exc), 403, "ISOLATION")
        except WriterError as exc:
            return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
        except NativeBoundaryError as exc:   # Stand 06 / K2: the God path reaches the consent core outside _run_write
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_GOD", exc=exc, last_successful_stage=last)
            try:
                _get_conn().rollback()
            except Exception:
                pass
            return _json_error(exc.code, exc.message, 503, exc.code)
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_GOD", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)

    @app.post("/api/kernel/regie")
    def kernel_regie():
        body = request.get_json(silent=True) or {}
        trace_id = str(body.get("trace_id") or body.get("traceId") or matrix_live_log.new_trace_id("kr"))
        last = "UI_REQUEST"
        matrix_live_log.live_log("UI_REQUEST", trace_id=trace_id, endpoint="/api/kernel/regie")
        _llm_vorab.vorab_leeren()   # Stand 11: Lesungen der ersten Antwort gelten nur fuer diese Anfrage
        aid, err = _kernel_actor(body)
        if err is not None and not aid:
            return err
        # V59C (AMASTER §46.2/§46.6, §24.2): the shared semantic planner reads
        # the Regie text BEFORE the SQLite write lock; the kernel validates.
        regie_components = None
        regie_rule_plans: dict = {}
        regie_legacy_koerper = None   # V92 Paket 19: body reading of the legacy *act* (with its confirmation)
        _ueb_regie = None
        try:
            conn_plan = _get_conn()
            plan_session = _kernel_stored_session(conn_plan, aid, body)
            _w, plan_natives = _kernel_world_and_natives(conn_plan, aid, plan_session)
            if not plan_natives:
                plan_natives = _sql_natives(conn_plan, aid, plan_session)
            present_ids = [str(x) for x in ((plan_session.get("scene") or {}).get("presentIds") or [])]
            names = [str(n.get("name") or "") for n in (plan_natives or []) if isinstance(n, dict) and str(n.get("id") or "") in present_ids]
            if plan_session.get("avatarId") and str(plan_session.get("avatarId")) in present_ids:
                av = next((n for n in plan_natives or [] if isinstance(n, dict) and str(n.get("id")) == str(plan_session.get("avatarId"))), None)
                if av is None and plan_session.get("alias"):
                    names.append(str(plan_session.get("alias")))
            # AMASTER §46.2: "Direktes Ziel" darf nie die Anweisung an
            # einen Handelnden ersetzen. Der Semantikleser darf einen im
            # Text genannten Akteur vorschlagen; gebunden wird er erst im
            # existierenden Kernel-Binder gegen Anweisung/Anwesenheit/UI.
            directed = body.get("actorId") or body.get("actor_id") or ""
            directed_name = next((str(n.get("name") or "") for n in plan_natives or [] if isinstance(n, dict) and str(n.get("id")) == str(directed)), "")
            direct_action = body.get("directAction") is True
            if direct_action:
                # Explicit UI-authorized action, NOT a guessed free-text parse.
                # Both the actor and any chosen target must be present, native
                # figures of this stored session. The original literal action
                # proceeds through the SAME binder/writer as the model plan.
                text_direct = str(body.get("text") or "").strip()
                aid_direct = str(body.get("actorId") or "")
                target_direct = str(body.get("targetId") or "")
                present_by_id = {str(n.get("id")): n for n in plan_natives or []
                                 if isinstance(n, dict) and str(n.get("id")) in present_ids}
                if not text_direct or len(text_direct) > 240:
                    raise WriterError("Regiehandlung muss 1 bis 240 Zeichen haben", 422, "REGIE_ACTION_TEXT")
                if aid_direct not in present_by_id:
                    raise WriterError("Angewiesene Figur muss bewusst ausgewaehlt und anwesend sein", 422, "REGIE_ACTOR_REQUIRED")
                if target_direct and target_direct not in present_by_id:
                    raise WriterError("Regieziel muss anwesend sein", 422, "REGIE_TARGET_ABSENT")
                first_word = text_direct.split(maxsplit=1)[0]
                named_first = kernel._named_by_name_part(first_word, list(present_by_id.values()))
                if named_first and named_first != {aid_direct}:
                    raise WriterError("Regietext und gewaehlter Handelnder widersprechen einander", 422, "REGIE_ACTOR_CONFLICT")
                regie_components = {"komponenten": [{"typ": "handlung", "akteur": str(present_by_id[aid_direct].get("name") or ""),
                    "ziel": str(present_by_id[target_direct].get("name") or "") if target_direct else "",
                    "segment": text_direct, "beschreibung": text_direct,
                    "wirkung": "ohne_koerperwirkung"}], "unklar": []}
            else:
                regie_components = extract_regie_components(
                    conn_plan, aid or "admin", str(body.get("text") or ""), directed_name=directed_name,
                    figures=[n for n in names if n],
                    data={"sessionId": plan_session.get("id"), "worldId": plan_session.get("worldId"),
                          "speakerId": str(directed or "")})
                if regie_components is None:
                    # V89: No provider result is NOT a valid ordered effect.
                    # The existing route reports this through its error path;
                    # no TurnTruth, SceneFact or SQLite turn is written.
                    matrix_live_log.live_log("EFFECT_PLAN", trace_id=trace_id, source="regie", status="BLOCKIERT", reason="semantikdienst_nicht_verfuegbar")
            # V65U (AMASTER §24.2 Z. 1110-1113, §46.3 Z. 2565, §46.6 Z. 2596; Codegutachten v1 N5): an informing order
            # transfers exactly the acts it means. The kernel narrows the candidates structurally (acts the directed
            # figure knows, by the bound doer/person); a small reading picks labels (+1 call, only for such an order);
            # the labels are mapped here and validated by the Regie writer. No label -> nothing is executed.
            for _rc in ((regie_components or {}).get("komponenten") or []) if isinstance(regie_components, dict) else []:
                if not (isinstance(_rc, dict) and _rc.get("typ") == "rede" and isinstance(_rc.get("taten"), dict)):
                    continue
                _rnat = [n for n in (plan_natives or []) if isinstance(n, dict)]
                _von, _an = kernel.regie_taten_persons(plan_session, _rc, directed_id=directed, figures=_rnat)
                _rc["taten"].update({"vonId": _von, "anId": _an, "ereignisse": [], "factIds": [], "unbekannt": []})
                for _k in ("auswahl", "kennungen", "kennungenGeprueft", "inhalt"):   # V65W: keys are the server's readings only
                    _rc["taten"].pop(_k, None)
                if not _von:
                    continue
                # V65V (Nachpruefung v1 K2/K6): candidates = ALL acts of the bound pair the figure knows (no foreground
                # cut); the reading list is capped only as payload, and a "bestimmte" selection over a capped list is
                # marked incomplete (not executed). The selection's structure goes to the Regie writer, which computes.
                # V65V (Nachpruefung v1 K2/K6): the selection reading reads only the instruction's structure; the Regie
                # writer selects from ALL committed acts of the bound pair the figure knows (regie_act_pool, no cut).
                if not kernel.regie_act_pool(plan_session, directed, von_id=_von, an_id=_an):
                    continue
                _sel = select_regie_acts(conn_plan, aid or "admin", str(body.get("text") or ""), directed_name=directed_name,
                                         data={"sessionId": plan_session.get("id"), "worldId": plan_session.get("worldId"),
                                               "speakerId": str(directed or "")}) or {}
                _art = str(_sel.get("auswahl") or "")
                _aus: dict = {"art": _art} if _art in ("alle", "reihenfolge", "bestimmte") else {}
                if _art == "reihenfolge":
                    _aus["wort"] = str(_sel.get("wort") or "")[:40] or None
                elif _art == "bestimmte":
                    _aus.update({"wirkung": str(_sel.get("wirkung") or "")[:24] or None, "beleg": str(_sel.get("beleg") or "")[:160] or None})
                _rc["taten"]["auswahl"] = _aus or None
                # V65V (Nachpruefung v1 K2): the second key - the acts by label over the kernel's lines of the whole pool
                # (+1 call, only for an informing order with a read structure); the writer executes only when both agree
                _rdata = {"sessionId": plan_session.get("id"), "worldId": plan_session.get("worldId"), "speakerId": str(directed or "")}
                if _aus:
                    # V65W (Tiefenpruefung v1 P02/C3): the label key reads ALL acts of the pool, page by page (40 lines each,
                    # global labels; V65X E06: no page limit) - +1 call per page; the writer gets which acts the
                    # key saw (kennungenGeprueft) and executes only when it covered the whole pool.
                    _lines, _labmap = kernel.regie_act_candidates(plan_session, directed, _rnat, von_id=_von, an_id=_an)
                    _pages = kernel.regie_pages(_lines, _labmap)
                    _answers = [select_regie_act_labels(conn_plan, aid or "admin", str(body.get("text") or ""), directed_name=directed_name,
                                                        candidates=_pg, data=_rdata) for _pg, _ids in _pages]
                    _named, _seen = kernel.regie_label_key(_pages, _answers, _labmap)
                    _rc["taten"]["kennungen"] = _named
                    _rc["taten"]["kennungenGeprueft"] = _seen
                if _aus.get("art") == "bestimmte" and _aus.get("beleg") and _aus.get("wirkung"):
                    # V65W (Tiefenpruefung v1 P01/C2): the content key - which acts of the named validated class the
                    # instruction's own word names (+1 call per page of such acts); never the instruction's other words
                    _clines, _clabels = kernel.regie_content_candidates(plan_session, directed, von_id=_von, an_id=_an, wirkung=_aus.get("wirkung"))
                    _cpages = kernel.regie_pages(_clines, _clabels)
                    _canswers = [check_regie_act_content(conn_plan, aid or "admin", bezeichnung=str(_aus.get("beleg") or ""), taten=_pg,
                                                         data=_rdata) for _pg, _ids in _cpages]
                    _cnamed, _cseen = kernel.regie_label_key(_cpages, _canswers, _clabels)
                    if _cpages and any(isinstance(a, list) for a in _canswers):
                        _rc["taten"]["inhalt"] = {"beleg": str(_aus.get("beleg") or ""), "factIds": _cnamed, "geprueft": _cseen}
                    matrix_live_log.live_log("REGIE_TATINHALT", trace_id=trace_id, beleg=_aus.get("beleg"), wirkung=_aus.get("wirkung"),
                                             kandidaten=len(_clines), modell=_canswers, gewaehlt=_cnamed)
                matrix_live_log.live_log("REGIE_TATEN", trace_id=trace_id, status="READ" if _aus else "NONE", auswahl=_aus.get("art"),
                                         kennungen=len(_rc["taten"].get("kennungen") or []), gesehen=len(_rc["taten"].get("kennungenGeprueft") or []))
            # V65W (Tiefenpruefung v1 P03/C4): the scene transition of this Regie instruction (+1 call), server-side only
            _ueb_regie = _scene_transition_read(conn_plan, aid, str(body.get("text") or ""), plan_session, trace_id=trace_id, where="regie",
                                                auswahl=body.get("szenenuebergang"))
            # V65W (Tiefenpruefung v1 P06/C1): an ORDERED body act against a standing restricted boundary of the person it
            # touches gets the same act reading (server-side; client verdicts are not accepted from anywhere).
            try:
                for _hc in ((regie_components or {}).get("komponenten") or []) if isinstance(regie_components, dict) else []:
                    if not (isinstance(_hc, dict) and str(_hc.get("typ") or "") == "handlung"):
                        continue
                    _hc.pop("grenzBezug", None)
                    _ok_h, _kind_h = kernel.effect_kind_from_wirkung(_hc.get("wirkung"))
                    if not (_ok_h and _kind_h in kernel._CONSENT_ACTS):
                        continue
                    _aname = str(_hc.get("akteur") or "").strip() or directed_name
                    _aid_h = next((str(n.get("id")) for n in plan_natives or [] if isinstance(n, dict) and str(n.get("name") or "") == _aname), str(directed or ""))
                    _v_h = _boundary_readings(conn_plan, aid, plan_session, _aid_h, _aname, str(_hc.get("beschreibung") or "").strip(),
                                              str(body.get("text") or ""), plan_natives,
                                              {"sessionId": plan_session.get("id"), "worldId": plan_session.get("worldId"), "speakerId": _aid_h},
                                              trace_id=trace_id, where="regie")
                    if _v_h is not None:
                        _hc["grenzBezug"] = _v_h
            except Exception as _rb_exc:
                matrix_live_log.live_log("BOUNDARY_REFERENCE", trace_id=trace_id, status="ERROR", error=f"{type(_rb_exc).__name__}: {str(_rb_exc)[:200]}")
            # V92 Paket 19 (unabhaengige Pruefung Paket 18, Regie-Koerperkette; AMASTER §46.2/§46.6, §43.1, §24.2/§24.7): the body
            # change of each ORDERED act is read from the act's own words in the instruction for its actor (the same typed reading
            # as God, +1 call per ordered act) and confirmed at the quote (+1 call when a change is proposed); the Regie writer
            # validates it for exactly the bound actor. The former word reading of the kernel (_regie_body_words) is removed.
            # A reading that came with the plan is removed first.
            try:
                from matrix_api.llm_contract import god_body_state as _rbody
                _rdata_b = {"sessionId": plan_session.get("id"), "worldId": plan_session.get("worldId"), "speakerId": str(directed or "")}
                _rpresent = [n for n in (plan_natives or []) if isinstance(n, dict) and str(n.get("id") or "") in present_ids]
                # the explicit legacy syntax decides the writer path (kernel.apply_regie): its components are not executed then,
                # so they are not read either
                _lsp, _lact = kernel.parse_regie_components(str(body.get("text") or ""))
                for _hc in ((regie_components or {}).get("komponenten") or []) if isinstance(regie_components, dict) else []:
                    if not isinstance(_hc, dict):
                        continue
                    _hc.pop("koerperPruefung", None)
                    if _lsp or _lact or str(_hc.get("typ") or "") != "handlung" or not str(_hc.get("segment") or "").strip():
                        continue
                    _ak = str(_hc.get("akteur") or "").strip()
                    _afig = kernel._match_figure(_ak, _rpresent) if _ak else next((n for n in _rpresent if str(n.get("id")) == str(directed or "")), None)
                    if _afig is None:
                        continue
                    _seg_b = str(_hc.get("segment") or "").strip()
                    _rb = _rbody(conn_plan, aid or "admin", text=_seg_b, figure=str(_afig.get("name") or ""), kontext=str(body.get("text") or ""),
                                 quelle="regie", data=_rdata_b)
                    matrix_live_log.live_log("REGIE_BODY", trace_id=trace_id, figure=_afig.get("name"), segment=_seg_b[:200], modell=_rb)
                    if isinstance(_rb, dict):
                        _hc["koerperPruefung"] = _koerper_bestaetigen(conn_plan, aid, _rb, text=_seg_b, figur=str(_afig.get("name") or ""),
                                                                      authority="regie", data=_rdata_b, trace_id=trace_id, quelle="regie",
                                                                      figur_id=_afig.get("id"))
                if _lact:
                    # the explicit *act* of the legacy syntax ("Mara: *setzt sich*") - same reading for the directed actor
                    _la, _lt = kernel.resolve_regie_actor_target(actor_id=directed or None, target_id=body.get("targetId") or body.get("target_id"),
                                                                 text=str(body.get("text") or ""), figures=plan_natives)
                    _lfig = next((n for n in (plan_natives or []) if isinstance(n, dict) and str(n.get("id")) == str(_la or "")), None)
                    if _lfig is not None:
                        _lr = _rbody(conn_plan, aid or "admin", text=str(_lact), figure=str(_lfig.get("name") or ""), kontext=str(body.get("text") or ""),
                                     quelle="regie", data=_rdata_b)
                        matrix_live_log.live_log("REGIE_BODY", trace_id=trace_id, figure=_lfig.get("name"), segment=str(_lact)[:200], modell=_lr, legacy=True)
                        if isinstance(_lr, dict):
                            regie_legacy_koerper = _koerper_bestaetigen(conn_plan, aid, _lr, text=str(_lact), figur=str(_lfig.get("name") or ""),
                                                                        authority="regie", data=_rdata_b, trace_id=trace_id, quelle="regie",
                                                                        figur_id=_lfig.get("id"))
            except Exception as _rk_exc:   # a body reading never drops the ordered act; without it the act changes no body
                matrix_live_log.live_log("REGIE_BODY", trace_id=trace_id, status="ERROR", error=f"{type(_rk_exc).__name__}: {str(_rk_exc)[:200]}")
            matrix_live_log.live_log("EFFECT_PLAN", trace_id=trace_id, source="regie",
                                     status="READ" if isinstance(regie_components, dict) else "NONE",
                                     components=len((regie_components or {}).get("komponenten") or []) if isinstance(regie_components, dict) else 0)
            # V65b (AMASTER §46.2, §15/§44, §46.6): an ordered act at a present
            # figure is a scene event she experiences; her authored reaction
            # rules are read with the SAME reader as for an input act (rule x
            # fact). The kernel binds; no figure reaction is invented here.
            try:
                from matrix_api.learning import canonical_stem as _cstem
                _acts = [c for c in ((regie_components or {}).get("komponenten") or []) if isinstance(c, dict) and c.get("typ") == "handlung"]
                for _c in _acts:
                    _tname = str(_c.get("ziel") or "")
                    _tgt = next((n for n in plan_natives or [] if isinstance(n, dict) and str(n.get("name") or "") == _tname
                                 and str(n.get("id") or "") in present_ids), None)
                    if _tgt is None or str(_tgt.get("id")) == str(plan_session.get("avatarId") or "") or str(_tgt.get("id")) in regie_rule_plans:
                        continue
                    _rules = [str(r) for r in (_cstem(_tgt).get("reactionRules") or []) if str(r or "").strip()]
                    if not _rules:
                        continue
                    _comps = [{"typ": "handlung", "segment": str(x.get("beschreibung") or x.get("segment") or ""),
                               "akteur": x.get("akteur"), "ziel": x.get("ziel")} for x in _acts if str(x.get("ziel") or "") == _tname]
                    regie_rule_plans[str(_tgt.get("id"))] = _rule_plan(
                        conn_plan, aid, plan_session, str(_tgt.get("id")), _tname, str(_c.get("akteur") or ""), _rules, _comps, [],
                        {"sessionId": plan_session.get("id"), "worldId": plan_session.get("worldId"), "speakerId": str(directed or "")})
            except Exception as _rexc:  # a rule reading never drops the ordered Regie effect
                regie_rule_plans = {}
                matrix_live_log.live_log("EFFECT_PLAN", trace_id=trace_id, source="regie_rules", status="FAIL", error=str(_rexc)[:160])
        except (WriterError, KeyError, IsolationError):
            regie_components = None
        except Exception as exc:  # planner is a candidate source, never a turn abort
            matrix_live_log.live_log("EFFECT_PLAN", trace_id=trace_id, source="regie", status="FAIL", error=str(exc)[:160])
            regie_components = None
        try:
            def _persist(conn):
                nonlocal last
                session = _kernel_stored_session(conn, aid, body)
                world, natives = _kernel_world_and_natives(conn, aid, session)
                if not natives:
                    natives = _sql_natives(conn, aid, session)
                if not natives:
                    natives = body.get("present") or body.get("characters") or []
                matrix_live_log.live_log(
                    "KERNEL_BIND",
                    trace_id=trace_id,
                    resolved_user_id=aid or session.get("userId"),
                    resolved_world_id=session.get("worldId"),
                    resolved_session_id=session.get("id"),
                    resolved_authority="regie",
                    endpoint="/api/kernel/regie",
                )
                last = "KERNEL_BIND"
                matrix_live_log.live_log("VALIDATION", trace_id=trace_id, result="BINDING_PASS", reject_reason=None, scope="Actor/Session/Sprecher gebunden; inhaltliche Prüfung je Fact steht in TURN_INPUT/TURN_RESPONSE/TURN_REGIE (valid=…, reason=…)")
                last = "VALIDATION"
                actor_id = body.get("actorId") or body.get("actor_id")
                target_id = body.get("targetId") or body.get("target_id")
                if actor_id:
                    try:
                        actor_id = (_canonical_speaker(conn, aid, session, {"id": actor_id}, natives) or {}).get("id") or actor_id
                    except WriterError:
                        raise
                legacy_speech, legacy_action = kernel.parse_regie_components(str(body.get("text") or ""))
                # Preserve the existing explicit *action* / Name: speech path.
                # Uninterpreted ordinary director text may not become a fake turn.
                if regie_components is None and not (legacy_speech or legacy_action):
                    raise WriterError(
                        "Regie nicht ausgefuehrt: Sprachdienst/Regieanalyse nicht verfuegbar. In Konfiguration den Provider live pruefen.",
                        503, "REGIE_SEMANTIK_NICHT_VERFUEGBAR")
                out = kernel.apply_regie(
                    session,
                    world,
                    body.get("text") or "",
                    target_id=target_id,
                    place_name=body.get("placeName"),
                    actor_id=actor_id,
                    present=natives,
                    components=regie_components,
                    rule_plans=regie_rule_plans,
                    uebergang=_ueb_regie,
                    koerper_lesung=regie_legacy_koerper,
                )
                regie_row = next((t for t in reversed(out.get("turns") or []) if t.get("role") == "regie"), {}) or {}
                eff = regie_row.get("regieEffects") or {}
                matrix_live_log.live_log(
                    "WRITER",
                    trace_id=trace_id,
                    owner="kernel",
                    table="sessions",
                    fact_type="regie",
                    commit_status="pending_sqlite",
                    executed=[{"fact_id": e.get("factId"), "validated": e.get("validated")} for e in (eff.get("executed") or [])],
                    ordered_speech=len(eff.get("speech") or []),
                    unclear=len(eff.get("unclear") or []),
                )
                # V60 (AMASTER §54 Punkt 15, §68 Nr. 70): readable Regie protocol.
                _names = {str(c.get("id")): str(c.get("name") or "") for c in natives if isinstance(c, dict)}
                matrix_live_log.live_log("TURN_REGIE", trace_id=trace_id, text=str(body.get("text") or ""),
                    directed=_names.get(str(actor_id or target_id or ""), str(actor_id or target_id or "")),
                    components=[{k: c.get(k) for k in ("typ", "akteur", "ziel", "segment", "beschreibung", "inhalt", "wirkung")}
                                for c in ((regie_components or {}).get("komponenten") or []) if isinstance(c, dict)][:8],
                    executed=[str(e.get("text") or "") for e in (eff.get("executed") or [])],
                    speech_order=[str(x.get("inhalt") or "") for x in (eff.get("speech") or [])],
                    unclear=[str(u) for u in (eff.get("unclear") or [])][:6],
                    **matrix_live_log.session_delta(session, out, names=_names))
                valid_actions = [e for e in (eff.get("executed") or []) if e.get("validated") is True]
                declined = bool(eff.get("unclear") or any(e.get("validated") is not True for e in (eff.get("executed") or [])))
                has_effect = bool(valid_actions or eff.get("speech") or eff.get("uebergang"))
                semantic_status = ("UNVERIFIED" if not isinstance(regie_row.get("regieEffects"), dict) else
                                   "TEIL" if has_effect and declined else
                                   "PASS" if has_effect else "REJECT")
                matrix_live_log.live_log("EFFECT_VERDICT", trace_id=trace_id, authority="regie",
                                         status=semantic_status, executed=len(valid_actions),
                                         rejected=len(eff.get("unclear") or []))
                last = "WRITER"
                # Legacy explicit speech/action has its separate existing writer.
                # Verify its actual Fact, not merely a parsed string.
                legacy_executed = bool(
                    (legacy_speech or legacy_action)
                    and any(isinstance(f, dict) and f.get("validated") is not False
                            and f.get("turn") == out.get("turnIndex")
                            and f.get("kind") in ("speech", "action")
                            and f.get("actorId") not in (None, "regie")
                            for f in (out.get("facts") or []))
                )
                if not has_effect and not legacy_executed:
                    # Der vorhandene Binder hat den fehlenden Akteur bereits
                    # nachgewiesen; statt einer leeren Regie-Runde erscheint
                    # die zugehörige sichtbare UI-Kontrolle im Fehlertext.
                    # Kein Ersatz durch das Ziel, keine neue Parserlogik.
                    _unbound_actor = any(
                        str(c.get("grund") or "") in
                        ("akteur_nicht_belegt", "akteur_nicht_anwesend_oder_unbekannt")
                        for c in eff.get("unclear") or [] if isinstance(c, dict))
                    if _unbound_actor and not actor_id:
                        raise WriterError(
                            "Regie nicht ausgefuehrt: handelnde Figur nicht gebunden. "
                            "In der Regie-Oberflaeche 'Angewiesene Figur' auswaehlen; "
                            "'Direktes Ziel' ist die betroffene Figur, NICHT der Handelnde. "
                            "Keine Szenenaenderung gespeichert.",
                            422, "REGIE_AKTEUR_NICHT_GEBUNDEN")
                    # A rejected or empty plan must not be committed as a
                    # successful Regie turn. Independent valid components
                    # continue to be accepted (partial effects are possible).
                    raise WriterError(
                        "Regie nicht vollzogen: keine validierte Handlung, Rede oder Szenenwirkung. Keine Szenenaenderung gespeichert.",
                        422, "REGIE_KEINE_VALIDIERTE_WIRKUNG")
                saved = kernel_session_response(conn, aid or out.get("userId") or "admin", out)
                # Rehydrate from SQLite, then independently verify the real
                # action/scene/witness writer output. A request returning 200
                # or an LLM speech directive does not mean the action happened.
                verdict = kernel.regie_persisted_verdict(saved, out.get("turnIndex"))
                semantic_status = verdict["status"]
                matrix_live_log.live_log("REGIE_SQLITE_RUECKLESUNG", trace_id=trace_id, **verdict)
                matrix_live_log.live_log("SQLITE_COMMIT", trace_id=trace_id, status="PASS", session_id=saved.get("id"))
                return {"ok": True, "session": saved, "trace_id": trace_id,
                        "effect_verdict": semantic_status}

            return _run_write(_persist)
        except IsolationError as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="VALIDATION", exc=exc, last_successful_stage=last)
            matrix_live_log.live_log("VALIDATION", trace_id=trace_id, result="REJECT", reject_reason=str(exc))
            return _json_error(str(exc), str(exc), 403, "ISOLATION")
        except WriterError as exc:
            return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_REGIE", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)

    @app.post("/api/kernel/puppet")
    def kernel_puppet():
        _llm_vorab.vorab_leeren()   # Stand 11: Lesungen der ersten Antwort gelten nur fuer diese Anfrage
        body = request.get_json(silent=True) or {}
        trace_id = str(body.get("trace_id") or body.get("traceId") or matrix_live_log.new_trace_id("kp"))
        last = "UI_REQUEST"
        matrix_live_log.live_log("UI_REQUEST", trace_id=trace_id, endpoint="/api/kernel/puppet")
        aid, err = _kernel_actor(body)
        if err is not None and not aid:
            return err
        try:
            # V65K (V54/V59C "keine Netzwerkaufrufe unter der SQLite-Schreibsperre", wie Regie): the
            # semantic readings of the puppet input run BEFORE the write lock; the write below only
            # binds and commits. Before V65K the planner (since V62) and the body-effect readings
            # (V65J) ran inside BEGIN IMMEDIATE.
            def _puppet_speaker(conn, session, natives):
                fig_hint = body.get("figure") if isinstance(body.get("figure"), dict) else {"id": body.get("figureId") or body.get("figure_id")}
                # P23: a client-supplied figure ID is never an authority. Resolve
                # it against the current user's canonical world cast, including
                # authorised figures that are not yet present in this scene.
                fig_id = str(fig_hint.get("id") or "")
                if not fig_id or not any(str(c.get("id") or "") == fig_id for c in natives):
                    raise WriterError("puppet figure not in this world", 404, "FIGURE_NOT_FOUND")
                sp = _canonical_speaker(conn, aid, session, {"id": fig_id}, natives)
                if str(sp.get("id") or "") != fig_id:
                    raise WriterError("puppet ID changed during binding", 409, "PUPPET_ID_STALE")
                return sp

            conn_read = _get_conn()
            session_r = _kernel_stored_session(conn_read, aid, body)
            natives_r = _sql_natives(conn_read, aid, session_r)
            speaker_r = _puppet_speaker(conn_read, session_r, natives_r)
            # V65J (AMASTER §23 ein Eingangsweg -> eine Bedeutung, §24.2/§24.6, §27.4; Prüfbericht
            # v2.2 Kette C): the puppet input is read like an avatar input - the raw text the user
            # typed (old clients: their speech + *action*) goes through the same planner, the same
            # body-effect reading and bind_input_components. Before, only the speech was planned
            # and the action's body effect came from a word list ("schlägt ... nicht" hit).
            _praw = str(body.get("text") or "").strip()
            if not _praw:
                _psp, _pac = str(body.get("speech") or "").strip(), str(body.get("action") or "").strip()
                _praw = " ".join(x for x in (_psp, f"*{_pac}*" if _pac else "") if x).strip()
            # V92 Paket 16 (Paket-15-Pruefung): the operator's answers to an identity clarification of THIS input (never stored).
            # V92 Paket 17 (Paket-16-Pruefung A, C, D): valid only for a question this server issued for exactly this input -
            # checked here, before any reading, and again under the write lock (_persist); then placed in the input
            _pakteur = "puppet|" + str(speaker_r.get("id") or "")
            _klaer = _klaerungen_pruefen(body.get("klaerungen"), _klaerung_kontext(session_r, _praw, _pakteur, natives_r), _praw)
            natives_r = kernel.with_klaerungen(natives_r, _klaer, _praw)
            from matrix_api.llm_contract import name_boundary_check as _name_boundary_check
            # Signed operator answers are authoritative for their text place.
            # Do not ask the model to re-read and override "Niemand davon".
            _pnames_read = (_name_boundary_check(conn_read, aid or "admin", _praw, figures=natives_r,
                                                 data={"sessionId": session_r.get("id"), "worldId": session_r.get("worldId")})
                            if not _klaer else None)
            natives_r = kernel.with_name_boundary_reading(_praw, natives_r, _pnames_read)
            # V62 (AMASTER §25 Zielbindung, §36.1): the puppet figure's speech has an addressee like
            # every other speech. Same canonical resolver as prepare/commit (_canonical_target).
            # V65K: session names (§24.1 known_as) are part of the natives projection.
            _pdec = _canonical_target(conn_read, aid, session_r, body.get("targetId") or body.get("target_id"), natives_r,
                                      text=_praw, input_actor_id=str(speaker_r.get("id") or ""))
            _ptarget_id = str((_pdec or {}).get("target_id") or "") or None
            if _ptarget_id == str(speaker_r.get("id") or ""):
                _ptarget_id = None
            _ptarget_name = next((str(c.get("name") or "") for c in natives_r if isinstance(c, dict) and str(c.get("id")) == str(_ptarget_id)), None) if _ptarget_id else None
            matrix_live_log.live_log("TARGET_BIND", trace_id=trace_id, endpoint="/api/kernel/puppet", speaker_id=speaker_r.get("id"),
                                     target_id=_ptarget_id, reason=(_pdec or {}).get("reason"), ambiguous=bool((_pdec or {}).get("ambiguous")))
            _pplan = None
            _pdata = {"sessionId": session_r.get("id"), "worldId": session_r.get("worldId"), "speakerId": speaker_r.get("id")}
            try:
                from matrix_api import conjunctive as _c
                _open = [f.get("what") for f in _c.frames_for(session_r, speaker_r["id"]) if f.get("status") in _c.FRAME_OPEN]
                # V92 Paket 13 (Bedingung D): the present persons of this session as context; speaker/puppet figure and the
                # selected recipient as separate IDs (the reading proposes, the kernel binds)
                _pcast = dict(anwesende=kernel.planner_cast(session_r, natives_r), sprecher_id=str(speaker_r.get("id") or ""),
                              puppet_figur_id=str(speaker_r.get("id") or ""), empfaenger_id=_ptarget_id)
                _pplan = extract_turn_plan(conn_read, aid or "admin", _praw, speaker_name=str(speaker_r.get("name") or ""), recipient_name=_ptarget_name, open_frames=_open,
                                           data=_pdata, today=(kernel.today_view(session_r) or {}).get("text"), puppet=True, **_pcast)
                if isinstance(_pplan, dict) and not (isinstance(_pplan.get("komponenten"), list) and _pplan.get("komponenten")):
                    # V92: the reading lacks the required `komponenten`. ONE repeat of the same reading; if it is still
                    # incomplete, bind_puppet_input reports it and nothing is committed (no silent speech, no request).
                    matrix_live_log.live_log("PLAN_EXTRACT", trace_id=trace_id, status="INCOMPLETE_RETRY", error="komponenten_fehlen")
                    _pplan2 = extract_turn_plan(conn_read, aid or "admin", _praw, speaker_name=str(speaker_r.get("name") or ""), recipient_name=_ptarget_name, open_frames=_open,
                                                data=_pdata, today=(kernel.today_view(session_r) or {}).get("text"), puppet=True, **_pcast)
                    if isinstance(_pplan2, dict):
                        _pplan = _pplan2
                if isinstance(_pplan, dict):
                    # Stand 11: die Fachlesungen des Planers (erste Antwort) fuer die Lesestellen unten - kein eigener Aufruf
                    _llm_vorab.vorab_registrieren(_pplan.get("lesungen"), quelle="puppet")
                    if not _klaer:
                        # Stand 11: die Namenslesung (Wortgrenzen) kam mit dieser ersten Antwort - jetzt anwenden und die
                        # Zielbindung mit derselben, vom Kernel geprueften Projektion neu bestimmen (vorher: eigener Aufruf vor dem Planer)
                        _pnames_read = _name_boundary_check(conn_read, aid or "admin", _praw, figures=natives_r,
                                                            data={"sessionId": session_r.get("id"), "worldId": session_r.get("worldId")})
                        if _pnames_read:
                            natives_r = kernel.with_name_boundary_reading(_praw, natives_r, _pnames_read)
                            _pdec = _canonical_target(conn_read, aid, session_r, body.get("targetId") or body.get("target_id"), natives_r,
                                                      text=_praw, input_actor_id=str(speaker_r.get("id") or ""))
                            _ptarget_id = str((_pdec or {}).get("target_id") or "") or None
                            if _ptarget_id == str(speaker_r.get("id") or ""):
                                _ptarget_id = None
                            _ptarget_name = next((str(c.get("name") or "") for c in natives_r if isinstance(c, dict) and str(c.get("id")) == str(_ptarget_id)), None) if _ptarget_id else None
                            matrix_live_log.live_log("TARGET_BIND", trace_id=trace_id, endpoint="/api/kernel/puppet", speaker_id=speaker_r.get("id"),
                                                     target_id=_ptarget_id, reason=(_pdec or {}).get("reason"), ambiguous=bool((_pdec or {}).get("ambiguous")),
                                                     namen="erste_antwort")
                    # P23: the actor is authorised by its canonical world ID, NOT
                    # by pre-existing presence. The semantic reader needs this
                    # identity even when the room is empty. Presence itself is
                    # written only later, after all validators pass.
                    _pcast_for_kind = kernel.puppet_kind_cast(
                        natives_r, (session_r.get("scene") or {}).get("presentIds") or [],
                        str(speaker_r.get("id") or ""))
                    # Stand 10B: die Sprachlesung (Namen/Wortbedeutungen) liest nur den Rohtext - sie laeuft gleichzeitig zur
                    # Vollzug-/Koerper-/Wirkungs-Kette; uebernommen nur, wenn ihre Vorbedingung vorher und nachher gleich ist.
                    from flask import current_app as _ca
                    import concurrent.futures as _cfp
                    _lang_vor = _pplan
                    _lang_ex = _cfp.ThreadPoolExecutor(max_workers=1)
                    import contextvars as _cvp
                    _lang_fut = _lang_ex.submit(_cvp.copy_context().run, lesungen_gleichzeitig, _ca.config.get("MATRIX_DB"), {
                        "sprache": lambda c, _p=_lang_vor: _read_language(c, aid, _p, _praw, str(speaker_r.get("name") or ""), _ptarget_name,
                                                                          natives_r, _pdata, trace_id=trace_id, where="puppet")})
                    _pplan = _check_component_vollzug(conn_read, aid, _pplan, _praw, str(speaker_r.get("name") or ""), _pdata, where="puppet",
                                                      present_figures=_pcast_for_kind,
                                                      actor_id=str(speaker_r.get("id") or ""))
                    _pplan = _check_component_effects(conn_read, aid, _pplan, _praw, str(speaker_r.get("name") or ""), natives_r, _pdata, where="puppet")
                    _pplan = _boundary_reference_step(conn_read, aid, session_r, str(speaker_r.get("id") or ""), str(speaker_r.get("name") or ""),
                                                      _pplan, _praw, natives_r, _pdata, trace_id=trace_id, where="puppet")
                    _lang_res = _lang_fut.result().get("sprache")
                    _lang_ex.shutdown(wait=False)
                    if (_lang_res is not None and _lang_res[0] == "ok" and isinstance(_lang_res[1], dict)
                            and _braucht_sprache(_lang_vor) == _braucht_sprache(_pplan)):
                        if "sprache" in _lang_res[1]:
                            _pplan = {**_pplan, "sprache": _lang_res[1]["sprache"]}
                    else:
                        _pplan = _read_language(conn_read, aid, _pplan, _praw, str(speaker_r.get("name") or ""), _ptarget_name, natives_r, _pdata,
                                                trace_id=trace_id, where="puppet")
                    _pplan = _answer_boundary_candidate(session_r, _pplan, _praw, speaker_r.get("id"), _ptarget_id, natives_r)
                    if isinstance(_pplan.get("grenze"), dict):
                        # V65W: a boundary the puppet figure sets gets the same scope reading as the avatar's and the figure
                        # reply's (V65V had it only there - a puppet boundary for every touch stayed unconfirmed)
                        _pplan["grenze"] = _consent_scope_check(conn_read, aid, _pplan["grenze"], _praw, _pdata, trace_id=trace_id, where="puppet")
            except Exception as _pp_exc:
                _pplan = None
                matrix_live_log.live_log("PLAN_EXTRACT", trace_id=trace_id, status="FAIL", error=str(_pp_exc)[:160])

            def _persist(conn):
                nonlocal last
                session = _kernel_stored_session(conn, aid, body)
                natives = _sql_natives(conn, aid, session)
                speaker = _puppet_speaker(conn, session, natives)
                if str(speaker.get("id") or "") != str(speaker_r.get("id") or ""):
                    raise WriterError("puppet identity changed since semantic reading", 409, "PUPPET_ID_STALE")
                # V92 Paket 17: the answers' context again under the write lock (the session may have advanced meanwhile)
                _kctx = _klaerung_kontext(session, _praw, "puppet|" + str(speaker.get("id") or ""), natives)
                _klaer_w = _klaerungen_pruefen(body.get("klaerungen"), _kctx, _praw)
                natives = kernel.with_klaerungen(natives, _klaer_w, _praw)
                # Revalidate the provider's purely semantic spans against the
                # fresh SQL cast under the lock. No provider call in the writer.
                natives = kernel.with_name_boundary_reading(_praw, natives, _pnames_read)
                matrix_live_log.live_log(
                    "KERNEL_BIND",
                    trace_id=trace_id,
                    resolved_user_id=aid or session.get("userId"),
                    resolved_world_id=session.get("worldId"),
                    resolved_session_id=session.get("id"),
                    resolved_authority="puppet",
                    endpoint="/api/kernel/puppet",
                )
                last = "KERNEL_BIND"
                matrix_live_log.live_log("VALIDATION", trace_id=trace_id, result="BINDING_PASS", reject_reason=None, scope="Actor/Session/Sprecher gebunden; inhaltliche Prüfung je Fact steht in TURN_INPUT/TURN_RESPONSE/TURN_REGIE (valid=…, reason=…)")
                last = "VALIDATION"
                # V34 (AMASTERv2 §22/§27.4): Puppet ist explizite Nutzersteuerung einer Figur. Ist sie
                # nicht anwesend, holt der Nutzer sie damit ausdrücklich in die Szene — als kanonischer
                # Presence-Fact (kein 409, kein Sprechen aus dem Off).
                presence_added = False
                present_now = list((session.get("scene") or {}).get("presentIds") or [])
                if speaker.get("id") and speaker["id"] not in present_now:
                    god_world, god_natives = _kernel_world_and_natives(conn, aid, session)
                    session = kernel.apply_presence(session, speaker["id"], world=god_world if isinstance(god_world, dict) else None, natives=god_natives if isinstance(god_natives, list) else None)
                    presence_added = True
                _pin = kernel.bind_puppet_input(_praw, _pplan, speaker, natives, list((session.get("scene") or {}).get("presentIds") or []),
                                                client_speech=body.get("speech"), client_action=body.get("action"),
                                                addressee_id=_ptarget_id)   # V65Z (A05): the bound addressee
                if _pin.get("partial_rejection"):
                    _unread = [str(a.get("segment") or "")[:120] for a in (_pin.get("ambiguous") or [])
                               if isinstance(a, dict) and a.get("grund") not in ("wirkung_unklar",)]
                    raise WriterError("Puppet: Nicht alle Satzteile wurden sicher gelesen. Nichts wurde gespeichert. "
                                      "Ungeklärte Teile: " + "; ".join(_unread[:4]),
                                      422, "PUPPET_TEILABLEHNUNG")
                if _pin.get("incomplete"):
                    # V92 (§24.7, §27.4): an unreadable puppet input is not an event. Nothing is written; the UI keeps the text.
                    matrix_live_log.live_log("TURN_INPUT", trace_id=trace_id, endpoint="/api/kernel/puppet", figure=speaker.get("name"),
                                             text=_praw[:300], speech="", actions=[], reading=False, ambiguous=_pin.get("ambiguous") or None,
                                             abgelehnt=str(((_pin.get("ambiguous") or [{}])[0] or {}).get("grund") or "zerlegung_unvollstaendig"))
                    _no_plan = any(isinstance(a, dict) and a.get("grund") == "plan_fehlt" for a in (_pin.get("ambiguous") or []))
                    raise WriterError(("Puppet: Die Eingabe konnte gerade nicht geprüft werden (keine Lesung verfügbar). "
                                       "Nichts wurde gespeichert. Bitte erneut senden; eine Handlung ohne Prüfung wird nicht gespeichert."
                                       if _no_plan else
                                       "Puppet: Die Eingabe konnte nicht eindeutig als Rede oder Handlung der Figur gelesen werden. "
                                       "Nichts wurde gespeichert. Bitte erneut senden oder genauer formulieren."), 422, "PLAN_INCOMPLETE")
                _frag = kernel.identity_questions(_pin.get("ambiguous"), _pdec, _klaer_w, natives,
                                                  present_ids=(session.get("scene") or {}).get("presentIds") or [])
                if _frag:
                    _frag = _klaerung_fragen(_frag, _kctx, _praw)   # V92 Paket 17: one signed question per written place
                    # V92 Paket 16 (Paket-15-Pruefung: "Bei Zweifeln keine Ziel-/Akteur- oder Sprecherbindung und kein falscher
                    # kanonischer Effekt; eine sichtbare Klartext-Rueckfrage ... muss die korrekte Figur-ID ermitteln koennen"): a name
                    # whose boundary or identity the server cannot prove is asked BEFORE anything is stored; the answer comes back
                    # with the same input (`klaerungen`). Nothing is written now; the text stays.
                    matrix_live_log.live_log("TURN_INPUT", trace_id=trace_id, endpoint="/api/kernel/puppet", figure=speaker.get("name"),
                                             text=_praw[:300], speech="", actions=[], reading=True, ambiguous=_pin.get("ambiguous") or None,
                                             abgelehnt="identitaet_klaeren", klaerung=_frag)
                    raise WriterError(f"Puppet: {kernel.identity_question_text(_frag)} Nichts wurde gespeichert. Bitte unten die gemeinte "
                                      "Figur wählen; die Eingabe wird dann mit dieser Klärung erneut geprüft.", 422, "IDENTITAET_KLAEREN",
                                      details={"klaerung": _frag})
                if _pin.get("nichts_ausfuehrbar"):
                    # V92 (Gegenpruefung 04.11. Fall B): every act of this input was rejected by the validation and there is no
                    # speech of the figure. Nothing is written (no fact, no turn); the person gets the reason, the text stays.
                    matrix_live_log.live_log("TURN_INPUT", trace_id=trace_id, endpoint="/api/kernel/puppet", figure=speaker.get("name"),
                                             text=_praw[:300], speech="", actions=[], reading=True, ambiguous=_pin.get("ambiguous") or None,
                                             abgelehnt="nichts_ausfuehrbar")
                    _why = kernel.input_rejection_text(_pin.get("ambiguous"))
                    raise WriterError(f"Puppet: Nichts davon ist eine ausführbare Rede oder Handlung von {speaker.get('name')}: {_why}. "
                                      "Nichts wurde gespeichert. Bitte anders formulieren oder die passende Figur wählen.", 422, "PUPPET_NICHT_AUSFUEHRBAR")
                matrix_live_log.live_log("TURN_INPUT", trace_id=trace_id, endpoint="/api/kernel/puppet", figure=speaker.get("name"),
                                         text=_praw[:300], speech=str(_pin.get("speech") or "")[:200],
                                         actions=[{k: a.get(k) for k in ("text", "targetId", "effectKind", "effectValid", "wirkungPruefung")} for a in (_pin.get("actions") or [])],
                                         reading=bool(_pin.get("used")), ambiguous=_pin.get("ambiguous") or None)
                out = kernel.commit_puppet(session, speaker, _pin.get("speech") or "", _pin.get("legacyAction"), plan=_pplan,
                                           # V92 Paket 14: the addressee the speech names in its own words outranks the selected one
                                           target_id=(_pin.get("speechTarget") if _pin.get("speechTargetSet") else _ptarget_id),
                                           actions=_pin.get("actions"),
                                           component_ambiguity=_pin.get("ambiguous") or None,
                                           language=(_pplan or {}).get("sprache") if isinstance(_pplan, dict) else None,
                                           figures=natives)
                if int(out.get("turnIndex") or 0) == int(session.get("turnIndex") or 0):
                    # V92 Paket 19 (Pruefung P18 "blockierte Turns"; AMASTER §43 Capability): nothing of this input could be carried
                    # out with the figure's body state (asleep, unconscious, gagged, mute) - nothing is written, the person sees why
                    raise WriterError(f"Puppet: {speaker.get('name') or 'Die Figur'} kann das jetzt nicht ausführen – "
                                      f"{kernel.capability_reason_text((session.get('runtimes') or {}).get(str(speaker.get('id'))))}. "
                                      "Nichts wurde gespeichert.", 422, "PUPPET_NICHT_AUSFUEHRBAR")
                # V52: committed puppet speech remains session knowledge; no auto-stem write.
                if presence_added:
                    out["puppetPresenceAdded"] = speaker["id"]
                matrix_live_log.live_log(
                    "WRITER",
                    trace_id=trace_id,
                    owner="kernel",
                    table="sessions",
                    fact_type="puppet",
                    commit_status="pending_sqlite",
                )
                last = "WRITER"
                saved = kernel_session_response(conn, aid or out.get("userId") or "admin", out)
                matrix_live_log.live_log("SQLITE_COMMIT", trace_id=trace_id, status="PASS", session_id=saved.get("id"))
                return {"ok": True, "session": saved, "trace_id": trace_id, "presenceAdded": out.get("puppetPresenceAdded")}

            return _run_write(_persist)
        except IsolationError as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="VALIDATION", exc=exc, last_successful_stage=last)
            matrix_live_log.live_log("VALIDATION", trace_id=trace_id, result="REJECT", reject_reason=str(exc))
            return _json_error(str(exc), str(exc), 403, "ISOLATION")
        except WriterError as exc:
            return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
        except NativeBoundaryError as exc:   # Stand 06 / K2: measured 400 KERNEL_FAILED before (puppet reaches the core outside _run_write)
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_PUPPET", exc=exc, last_successful_stage=last)
            try:
                _get_conn().rollback()
            except Exception:
                pass
            return _json_error(exc.code, exc.message, 503, exc.code)
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_PUPPET", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)

    def _disclosure_step(conn, aid, session, truth, speaker, result, natives, trace_id):
        """V65H: one small reading per candidate goal (normally none). No write here."""
        from matrix_api.llm_contract import goal_disclosure_check
        sid = str((speaker or {}).get("id") or "")
        speech = str((result or {}).get("speech") or "").strip() if isinstance(result, dict) else ""
        to = str(truth.get("input_actor_id") or truth.get("inputActorId") or "")
        if not sid or not speech or speech == "—" or not to or to == sid:
            return None
        props = result.get("proposals") if isinstance(result.get("proposals"), dict) else {}
        cands = kernel.disclosure_candidates(session, sid, to, source_turn_id=str(truth.get("id") or ""), plan=props.get("plan"))
        if not cands:
            return None
        names = {str(c.get("id")): str(c.get("name") or "") for c in natives if isinstance(c, dict)}
        _data = {"sessionId": session.get("id"), "worldId": session.get("worldId"), "sourceTurnId": truth.get("id"), "speakerId": sid}
        out = []
        for g in cands:
            res = goal_disclosure_check(conn, aid or "admin", text=speech, speaker=names.get(sid, sid),
                                        recipient=names.get(to) or kernel.operator_label(session, None, natives),
                                        unsaid=str((g.get("frame") or {}).get("ungesagt") or ""), data=_data)
            out.append({"goalId": g.get("id"), "offenbart": (res or {}).get("offenbart") is True, "beleg": (res or {}).get("beleg")})
        matrix_live_log.live_log("GOAL_DISCLOSURE", trace_id=trace_id, status="READ", figure=names.get(sid, sid),
                                 to=names.get(to, to), results=out)
        return out

    def _koerper_bestaetigen(conn, aid, reading, *, text, figur, authority, data, trace_id, quelle, figur_id=None):
        """V92 Paket 19 (unabhaengige Pruefung Paket 18 N3-N6; AMASTER §43.1, §24.2/§24.7): the second key of every body change -
        when a reading proposes one (kernel.body_change_candidate: closed values, literal quote), one confirmation reading per field
        at the quote asks how the text states exactly this value there (llm_contract.koerper_bestaetigung). The answers are put on
        the reading as `bestaetigung` (quote + per field the value asked about); the kernel validates them before the ONE writer.
        A confirmation that came with the reading (client/model) is removed first. No write here."""
        from matrix_api.llm_contract import koerper_bestaetigung
        if not isinstance(reading, dict):
            return reading
        r = {k: v for k, v in reading.items() if k not in ("bestaetigung", "figurId")}
        if figur_id is not None:
            r["figurId"] = str(figur_id)
        cand = kernel.body_change_candidate(r, str(text or ""), authority=authority)
        if cand is None:
            return r
        change, beleg = cand
        felder: dict = {}
        modell: dict = {}
        for key, one in kernel.body_change_fields(change):   # one reading per field (+1 call each)
            res = None
            try:
                res = koerper_bestaetigung(conn, aid or "admin", text=str(text or ""), figur=str(figur or ""), stelle=beleg,
                                           veraenderung=kernel.body_change_label(one), data=data)
            except Exception as _kb_exc:
                matrix_live_log.live_log("KOERPER_BESTAETIGUNG", trace_id=trace_id, status="ERROR", quelle=quelle,
                                         error=f"{type(_kb_exc).__name__}: {str(_kb_exc)[:200]}")
            modell[key] = res
            if isinstance(res, dict):
                felder[key] = {"wert": one[key], "art": res.get("art"), "inhalt": res.get("inhalt"), "beleg": res.get("beleg")}
        r["bestaetigung"] = {"stelle": beleg, "felder": felder}
        matrix_live_log.live_log("KOERPER_BESTAETIGUNG", trace_id=trace_id, quelle=quelle, figure=str(figur or ""),
                                 text=str(text or "")[:200], stelle=beleg, veraenderung=kernel.body_change_label(change), modell=modell,
                                 ergebnis=kernel.body_change_validated(r, str(text or ""), authority=authority, figur_id=figur_id)[1])
        return r

    def _koerper_check_step(conn, aid, session, truth, speaker, result, trace_id):
        """V92 Paket 18 (unabhaengige Pruefung Paket 17 N1-N9; AMASTER §43.1, §24.2/§24.7): the change the figure's action makes to
        her OWN body (position, falling asleep, waking up), read once, alone, by the server - never taken from the client. None
        without action or provider (then her action changes nothing on her body). No write here; the kernel validates."""
        from matrix_api.llm_contract import koerper_check
        action = str((result or {}).get("action") or "").strip() if isinstance(result, dict) else ""
        if not action:
            return None
        sid = str((speaker or {}).get("id") or "")
        _kdata = {"sessionId": session.get("id"), "worldId": session.get("worldId"), "sourceTurnId": truth.get("id"), "speakerId": sid}
        res = koerper_check(conn, aid or "admin", handlung=action, figur=str((speaker or {}).get("name") or sid),
                            aeusserung=" ".join(x for x in (str(result.get("speech") or "").strip(), action) if x),
                            data=_kdata)
        matrix_live_log.live_log("KOERPER_CHECK", trace_id=trace_id, quelle="figur", figure=str((speaker or {}).get("name") or sid),
                                 handlung=action[:200], modell=res)
        if not isinstance(res, dict):
            return None
        # V92 Paket 19: the confirmation reading at the quote (second key) before the kernel validates
        return _koerper_bestaetigen(conn, aid, {k: res.get(k) for k in ("haltung", "schlaf", "zeit", "beleg")}, text=action,
                                    figur=str((speaker or {}).get("name") or sid), authority="character", data=_kdata,
                                    trace_id=trace_id, quelle="figur")

    def _effect_check_step(conn, aid, session, truth, speaker, result, natives, trace_id):
        """V65I (AMASTER §24.2/§24.7): the body effect the reply proposes for its own
        action toward another figure (gewalt/fesseln/befreien) is read once more,
        alone; the kernel keeps it only with a literal quote. No write here."""
        from matrix_api.llm_contract import effect_check
        props = result.get("proposals") if isinstance(result, dict) and isinstance(result.get("proposals"), dict) else {}
        w = props.get("wirkung") if isinstance(props.get("wirkung"), dict) else None
        action = str((result or {}).get("action") or "").strip() if isinstance(result, dict) else ""
        if not kernel.effect_check_needed(w, action):
            return None
        sid = str((speaker or {}).get("id") or "")
        names = {str(c.get("id")): str(c.get("name") or "") for c in natives if isinstance(c, dict)}
        ziel = str(w.get("ziel") or "").strip() or names.get(str(truth.get("input_actor_id") or truth.get("inputActorId") or ""), "")
        _data = {"sessionId": session.get("id"), "worldId": session.get("worldId"), "sourceTurnId": truth.get("id"), "speakerId": sid}
        res = effect_check(conn, aid or "admin", action=action, akteur=names.get(sid) or str((speaker or {}).get("name") or sid),
                           ziel=ziel, vorschlag=str(w.get("art") or ""), aeusserung=action, data=_data)
        checked = kernel.apply_effect_check(w, action, res, figures=[c for c in natives if isinstance(c, dict)])
        if kernel.touch_confirmation_needed(checked):
            from matrix_api.llm_contract import touch_confirmation_check
            second = touch_confirmation_check(conn, aid or "admin", action=action,
                                              akteur=names.get(sid) or str((speaker or {}).get("name") or sid),
                                              ziel=ziel, data=_data)
            checked = kernel.apply_touch_confirmation(checked, action, second,
                                                      figures=[c for c in natives if isinstance(c, dict)], planned_target=ziel)
        att = None
        if kernel.attempt_check_needed(checked):
            # V65Q (AMASTER §43.1 attempted; Pruefung v2.8 P-03): an unconfirmed movement
            # done now - was it an attempt of exactly this movement? One follow-up reading.
            att = effect_check(conn, aid or "admin", action=action, akteur=names.get(sid) or str((speaker or {}).get("name") or sid),
                               ziel=ziel, vorschlag=str(w.get("art") or ""), aeusserung=action, data=_data, attempt=True)
            checked = kernel.apply_attempt_check(checked, att)
        matrix_live_log.live_log("EFFECT_CHECK", trace_id=trace_id, figure=names.get(sid, sid), ziel=ziel or None,
                                 vorschlag=w.get("art"), handlung=action[:200], modell=res,
                                 ergebnis=checked.get("art"), pruefung=checked.get("pruefung"),
                                 **({"versuchLesung": att} if att is not None else {}))
        return checked

    def _read_language(conn, aid, plan, utterance, speaker_name, addressee_name, natives, data, *, trace_id="plan", where=""):
        """V65K (AMASTER §24.1 known_as, §24.3 ALIAS/VOCABULARY, §24.6 Sessionwortschatz): the separate
        semantic reading of names and word meanings one utterance establishes. Semantic precondition from
        the planner: an input that is ONLY an act (event_kind action, no rede component) establishes no
        name. The reading only proposes; kernel.bind_language validates when the Fact is written."""
        if not isinstance(plan, dict):
            return plan
        comps = plan.get("komponenten") if isinstance(plan.get("komponenten"), list) else []
        has_speech = any(isinstance(c, dict) and str(c.get("typ") or "").lower() == "rede" for c in comps)
        if str(plan.get("event_kind") or "") == "action" and not has_speech:
            return plan
        from matrix_api.llm_contract import language_reading
        persons = [str(c.get("name") or "") for c in (natives or []) if isinstance(c, dict) and c.get("name")]
        rows = language_reading(conn, aid or "admin", text=str(utterance or ""), speaker_name=str(speaker_name or ""),
                                addressee_name=addressee_name, persons=persons, data=data)
        if rows is None:
            return plan
        matrix_live_log.live_log("SPRACHE", trace_id=trace_id, where=where, text=str(utterance or "")[:200],
                                 stellen=[{k: r.get(k) for k in ("art", "status", "bezeichnung", "person", "bedeutung", "beleg")} for r in rows])
        return {**plan, "sprache": rows}

    def _answer_boundary_candidate(session, plan, utterance, speaker_id, addressee_id, natives):
        """V65X (Nachpruefung V65W E01; live 30.10.: Maras "Du darfst meine Schulter wieder anfassen" had no boundary
        proposal, so no scope reading ran and the answer became the answer to the kiss; AMASTER §36.5 Z. 1947, §24.2 Z.
        1110-1113): an acceptance, refusal or revocation (the plan's own reading) of a figure that WAS touched by exactly one
        known person - the addressee, else the only toucher - is proposed as an answer for this act, quoted whole, so the
        separate scope reading can say whether it names a body part. No toucher or several -> nothing (no guess). Read only."""
        if not isinstance(plan, dict) or isinstance(plan.get("grenze"), dict):
            return plan
        if str(plan.get("event_kind") or "").strip().lower() not in ("acceptance", "refusal", "revocation"):
            return plan
        sid = str(speaker_id or "")
        touchers = {str(p.get("actorId") or "") for p in session.get("propositions") or []
                    if isinstance(p, dict) and p.get("kind") == "koerperkontakt" and str(p.get("targetId") or "") == sid} - {"", sid}
        who = str(addressee_id or "") if str(addressee_id or "") in touchers else (next(iter(touchers)) if len(touchers) == 1 else "")
        name = next((str(c.get("name") or "") for c in natives or [] if isinstance(c, dict) and str(c.get("id")) == who), "") if who else ""
        beleg = str(utterance or "").strip()
        if not name or not beleg:
            return plan
        return {**plan, "grenze": {"gilt_fuer": "diese_tat", "wer": name, "beleg": beleg[:200], "zeit": None, "quelle": "antwort_ohne_vorschlag"}}

    def _consent_scope_check(conn, aid, grenze, utterance, data, *, trace_id, where):
        """V65V (AMASTER §36.5, §24.2 Z. 1110-1113; Nachpruefung v1 K1/K4): a boundary proposed for EVERY touch gets the
        separate scope reading (consent_check) before the write - network, no write; the kernel validates both keys.
        Any client-supplied verdict is dropped (the verdict is the server's reading only)."""
        if not isinstance(grenze, dict):
            return grenze
        g = {k: v for k, v in grenze.items() if k != "pruefung"}
        # V65X (Nachpruefung V65W E01, live 30.10.): also an answer proposed for ONE act gets the scope reading - it may name
        # a body part ("Du darfst meine Schulter wieder anfassen"); validate_grenze never widens it, only narrows it to that part
        if str(g.get("gilt_fuer") or "").strip().lower() not in ("jede_beruehrung", "diese_tat") or not str(g.get("beleg") or "").strip():
            return g
        from matrix_api.llm_contract import consent_check
        res = consent_check(conn, aid or "admin", aeusserung=str(utterance or ""), beleg=str(g.get("beleg") or ""),
                            person=str(g.get("wer") or ""), data=data)
        if isinstance(res, dict):
            g["pruefung"] = kernel.consent_check_verdict(res)
        matrix_live_log.live_log("CONSENT_CHECK", trace_id=trace_id, quelle=where, beleg=str(g.get("beleg") or "")[:160],
                                 modell=res if isinstance(res, dict) else None)
        return g

    def _scene_transition_read(conn, aid, text, session, *, trace_id, where, auswahl=None):
        """V65W (C4) scene transition of one Regie/God instruction.
        V65Y (Gesamtpruefung V65X N06; AMASTER §6.2 Z. 262 fail-closed, Nr. 2 "Modellklassifikation ... fuer sich keine
        Sessionwahrheit", §20 Z. 949 "Eine Szene kann durch Nutzer, Regie, God ... wechseln", §46.3 klarer Scope, §46.5
        "UI-Auswahl ... bindet"): the transition is bound ONLY by the director's explicit choice in the Regie/God panel
        (neue_szene | szene_endet; default keiner). The V65W text reading is no longer asked: measured 31.10., a model reading
        that quotes a whole sentence ("Die Tür führt in eine neue Szene des Stückes.") passed every kernel anchor (4/54 FP),
        so a model value alone could still create a sceneId. 0 calls (V65W: +1 per Regie/God)."""
        _a = str(auswahl or "keiner").strip().lower()
        verdict = {"art": _a if _a in ("neue_szene", "szene_endet") else "keiner", "quelle": "auswahl" if _a in ("neue_szene", "szene_endet", "keiner") else "keine_auswahl"}
        matrix_live_log.live_log("SCENE_TRANSITION", trace_id=trace_id, quelle=where, text=str(text or "")[:200], auswahl=_a, ergebnis=verdict)
        return verdict

    def _boundary_readings(conn, aid, session, actor_id, actor_name, act_text, utterance, natives, data, *, trace_id, where):
        """V65W (Tiefenpruefung v1 P06/C1; AMASTER §36.5, §24.2 Z. 1110-1113): a body act of `actor_id` while a RESTRICTED
        refusal of a present figure stands against him is read once per such boundary (boundary_reference_check) - network,
        no write; the kernel records the verdicts on the act's own Fact and act_consent decides. None = no such boundary."""
        reqs = kernel.restricted_boundaries_for(session, actor_id, natives)
        # V65Y (Gesamtpruefung V65X N05): + the exceptions / restricted permissions the act NAMES (+1 call each, rare)
        exc = [e for e in kernel.restricted_exceptions_for(session, actor_id, natives)
               if kernel._scene.names_restriction(act_text, e.get("einschraenkung"), exact=True)]   # V65Z (A05)
        if (not reqs and not exc) or not str(act_text or "").strip():
            return None
        from matrix_api.llm_contract import boundary_reference_check, permission_reference_check
        out, models = [], []
        for e in reqs:
            res = boundary_reference_check(conn, aid or "admin", handlung=str(act_text), aeusserung=str(utterance or act_text),
                                           grenze=str(e.get("beleg") or ""), verboten=str(e.get("einschraenkung") or ""),
                                           akteur=str(actor_name or ""), ziel=str(e.get("targetName") or ""), data=data)
            out.append(kernel.boundary_reference_verdict(res, act_text=str(act_text), entry=e))
            models.append(res if isinstance(res, dict) else None)
        for e in exc:
            res = permission_reference_check(conn, aid or "admin", handlung=str(act_text), aeusserung=str(utterance or act_text),
                                             erlaubnis=str(e.get("beleg") or ""), erlaubt=str(e.get("einschraenkung") or ""),
                                             akteur=str(actor_name or ""), ziel=str(e.get("targetName") or ""), data=data)
            out.append(kernel.permission_reference_verdict(res, act_text=str(act_text), entry=e, utterance=str(utterance or "")))
            models.append(res if isinstance(res, dict) else None)
        matrix_live_log.live_log("BOUNDARY_REFERENCE", trace_id=trace_id, quelle=where, handlung=str(act_text)[:160],
                                 pruefungen=[{**v, "modell": m} for v, m in zip(out, models)])
        return out

    def _request_readings(conn, aid, session, actor_id, actor_name, act_text, utterance, natives, data, *, trace_id, where):
        """V65W (Tiefenpruefung v1 Punkt 9 / C7; AMASTER §36.1/§36.3/§36.5): a body act of `actor_id` while a request of his
        that the touched figure accepted is not yet carried out is read once per such request (request_reference_check) -
        network, no write; kernel._bind_own_act_to_request binds it. None = no such request."""
        reqs = kernel.accepted_requests_for(session, actor_id, natives)
        if not reqs or not str(act_text or "").strip():
            return None
        from matrix_api.llm_contract import request_reference_check
        out, models = [], []
        for e in reqs:
            res = request_reference_check(conn, aid or "admin", handlung=str(act_text), aeusserung=str(utterance or act_text),
                                          bitte=str(e.get("bitte") or ""), akteur=str(actor_name or ""), ziel=str(e.get("targetName") or ""),
                                          data=data)
            out.append(kernel.request_reference_verdict(res, act_text=str(act_text), entry=e, utterance=str(utterance or "")))
            models.append(res if isinstance(res, dict) else None)
        matrix_live_log.live_log("REQUEST_REFERENCE", trace_id=trace_id, quelle=where, handlung=str(act_text)[:160],
                                 pruefungen=[{**v, "modell": m} for v, m in zip(out, models)])
        return out

    def _boundary_reference_step(conn, aid, session, actor_id, actor_name, plan, utterance, natives, data, *, trace_id, where):
        """V65W (C1): every own body act of a planned input (avatar, puppet, Regie) gets the act readings against standing
        restricted boundaries. Client-supplied verdicts are dropped (the verdict is the server's reading only)."""
        comps = plan.get("komponenten") if isinstance(plan, dict) and isinstance(plan.get("komponenten"), list) else None
        if not comps:
            return plan
        out = []
        for c in comps:
            if not isinstance(c, dict):
                out.append(c)
                continue
            c = {k: v for k, v in c.items() if k not in ("grenzBezug", "bitteBezug")}
            if str(c.get("typ") or "").lower() == "handlung":
                ok, kind = kernel.effect_kind_from_wirkung(c.get("wirkung"))
                if ok and kind in kernel._CONSENT_ACTS:
                    _act = str(c.get("segment") or c.get("beschreibung") or "")
                    _v = _boundary_readings(conn, aid, session, actor_id, actor_name, _act, utterance, natives, data,
                                            trace_id=trace_id, where=where)
                    if _v is not None:
                        c["grenzBezug"] = _v
                    _r = _request_readings(conn, aid, session, actor_id, actor_name, _act, utterance, natives, data,
                                           trace_id=trace_id, where=where)
                    if _r is not None:
                        c["bitteBezug"] = _r
            out.append(c)
        return {**plan, "komponenten": out}

    def _statement_check_step(conn, aid, session, speaker, result, natives, trace_id):
        """V65V (AMASTER §36.3/§36.4, §24.2; Nachpruefung v1 K3): every statement component the formulation labelled as
        denying an event gets the separate statement reading (statement_check) with the events it cites - network, no
        write; apply_statement_components validates. Client-supplied verdicts are dropped."""
        props = result.get("proposals") if isinstance(result, dict) and isinstance(result.get("proposals"), dict) else None
        if not props or not isinstance(props.get("aussagen"), list):
            return result
        labels = props.get("ereignisse") if isinstance(props.get("ereignisse"), dict) else {}
        by_id = {str(f.get("id") or ""): f for f in session.get("facts") or [] if isinstance(f, dict)}
        names = {str(c.get("id")): str(c.get("name") or "") for c in natives or [] if isinstance(c, dict)}
        sid = str((speaker or {}).get("id") or "")
        _data = {"sessionId": session.get("id"), "worldId": session.get("worldId"), "speakerId": sid}
        from matrix_api.llm_contract import statement_check, statement_act_check
        out = []
        for a in props["aussagen"]:   # V65X (E04): no silent cut
            if not isinstance(a, dict):
                continue
            a = {k: v for k, v in a.items() if k != "pruefung"}
            if str(a.get("art") or "") == "bestreitet_geschehen":
                evl = []
                for e in a.get("ereignis") or []:
                    lab = str(e).strip().strip("[]")
                    f = by_id.get(str(labels.get(lab) or ""))
                    if f is not None:
                        evl.append(f"{lab}: Täter {names.get(str(f.get('actorId') or ''), '')}: „{str(f.get('text') or '')[:160]}“")
                res = statement_check(conn, aid or "admin", segment=str(a.get("segment") or ""), sprecher=names.get(sid, sid),
                                      ereignisse=evl, data=_data) if evl else None
                # V65W (Tiefenpruefung v1 P04/C5): one follow-up per event the decomposition read as denied - at the event itself
                _tb = {}
                if isinstance(res, dict) and str(res.get("gegenstand") or "").strip().lower() == "geschehen":
                    _lines = {ln.split(":", 1)[0]: ln for ln in evl}
                    for _lab in [str(x).strip().strip("[]") for x in (res.get("bestritten") or [])]:
                        if _lab in _lines:
                            _tb[_lab] = statement_act_check(conn, aid or "admin", segment=str(a.get("segment") or ""),
                                                            sprecher=names.get(sid, sid), ereignis=_lines[_lab].split(":", 1)[1].strip(),
                                                            data=_data)
                if isinstance(res, dict):
                    a["pruefung"] = kernel.statement_check_verdict(res, _tb)
                matrix_live_log.live_log("STATEMENT_CHECK", trace_id=trace_id, segment=str(a.get("segment") or "")[:160],
                                         modell=res if isinstance(res, dict) else None, tatbezug=_tb or None)
            out.append(a)
        return {**result, "proposals": {**props, "aussagen": out}}

    # V92 Paket 17 (Paket-16-Pruefung, Vertragsverletzung A; Forderungen A, C, D): an answer to an identity question is valid only
    # for the question THIS server issued - same session at the same turn, same input text, same speaker binding, same cast and
    # presence, same written place, and one of the figures that question offered (or "nobody"). The question carries that as a
    # signed, opaque `frage`; nothing is stored for it (no new table, no new owner: the question stays the routes' 422 of Paket 16).
    # The key exists per server start - a question of an earlier start is no longer valid (the person is asked again).
    _klaerung_key = secrets.token_bytes(32)

    def _klaerung_kontext(session, text, actor_key, natives):
        """What an identity answer is bound to (hash): session, its turn and open input, the input text, who speaks the input,
        the cast (IDs, names, aliases, session names) and who is present."""
        cast = sorted([str(c.get("id") or ""), str(c.get("name") or ""), sorted(str(a) for a in (c.get("aliases") or [])),
                       sorted(str(a) for a in (c.get("sessionAliases") or []))] for c in (natives or []) if isinstance(c, dict))
        scene = (session or {}).get("scene") or {}
        data = [str((session or {}).get("id") or ""), int((session or {}).get("turnIndex") or 0),
                str((session or {}).get("pendingInputTurnId") or ""), str(text or ""), str(actor_key or ""), cast,
                sorted(str(x) for x in (scene.get("presentIds") or []))]
        return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _klaerung_akteur(d):
        """Who speaks an avatar/user input (input actor and speak-as binding) - part of the answer's context."""
        d = d if isinstance(d, dict) else {}
        return "eingabe|" + str(d.get("inputActorId") or d.get("input_actor_id") or "") + "|" + str(d.get("speakAs") or d.get("speak_as") or "")

    def _klaerung_fragen(fragen, kontext, text):
        """The issued questions: each with its signed `frage` and a short excerpt around its place (`vor`, `nach`) so two places of
        the same name are told apart in the UI."""
        raw = str(text or "")
        out = []
        for q in fragen or []:
            payload = json.dumps({"k": kontext, "a": q.get("a"), "b": q.get("b"), "t": str(q.get("text") or ""),
                                  "c": [str(c.get("id")) for c in (q.get("kandidaten") or [])]},
                                 ensure_ascii=False, sort_keys=True).encode("utf-8")
            sig = hmac.new(_klaerung_key, payload, hashlib.sha256).hexdigest()
            token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=") + "." + sig
            a, b = q.get("a"), q.get("b")
            ctx = {}
            if type(a) is int and type(b) is int and 0 <= a <= b <= len(raw):
                ctx = {"vor": raw[max(0, a - 30):a].split("\n")[-1], "nach": raw[b:b + 30].split("\n")[0]}
            out.append({**q, "frage": token, **ctx})
        return out

    def _klaerungen_pruefen(klaerungen, kontext, text):
        """V92 Paket 17: the answers sent with an input, checked against the questions this server issued for exactly this input
        BEFORE anything is read or written. Returns the answers in kernel form [{"text","a","b","id"}]. A missing, foreign,
        changed, stale or unsolicited answer, a figure the question did not offer, two answers for one place: 422
        KLAERUNG_UNGUELTIG - nothing is stored, the text stays, the person sends the input again and is asked again."""
        if klaerungen in (None, [], ""):
            return []

        def _bad(grund, msg):
            raise WriterError(f"Die Antwort auf die Rückfrage gilt nicht für diese Eingabe: {msg} Nichts wurde gespeichert. "
                              "Bitte die Eingabe erneut senden; offene Rückfragen werden dann neu gestellt.",
                              422, "KLAERUNG_UNGUELTIG", details={"grund": grund})

        if not isinstance(klaerungen, list) or len(klaerungen) > 8:
            _bad("format", "Die Antworten haben nicht die erwartete Form.")
        raw = str(text or "")
        out, places = [], set()
        for k in klaerungen:
            token = str((k or {}).get("frage") or "") if isinstance(k, dict) else ""
            body_b64, _, sig = token.partition(".")
            try:
                payload = base64.urlsafe_b64decode(body_b64 + "=" * (-len(body_b64) % 4)) if body_b64 else b""
            except (ValueError, TypeError):
                payload = b""
            if not payload or not sig or not hmac.compare_digest(sig, hmac.new(_klaerung_key, payload, hashlib.sha256).hexdigest()):
                _bad("nicht_gestellt", "Zu dieser Antwort hat der laufende Server keine Rückfrage gestellt (fehlend, verändert "
                                       "oder aus einem früheren Serverstart).")
            q = json.loads(payload.decode("utf-8"))
            if q.get("k") != kontext:
                _bad("andere_eingabe", "Die Rückfrage gehört zu einer anderen Eingabe, Session, Sprecherbindung, Besetzung oder einem "
                                       "früheren Stand.")
            fid = k.get("id")
            fid = None if fid in (None, "") else str(fid)
            if fid is not None and fid not in (q.get("c") or []):
                _bad("nicht_angeboten", "Diese Figur wurde für diese Stelle nicht angeboten.")
            a, b = q.get("a"), q.get("b")
            if (a, b) in places:
                _bad("doppelt", "Für dieselbe Stelle kamen zwei Antworten.")
            places.add((a, b))
            if type(a) is int and type(b) is int and kernel._name_words(raw[a:b]) != kernel._name_words(q.get("t")):
                _bad("andere_eingabe", "Die Stelle steht so nicht in dieser Eingabe.")
            out.append({"text": str(q.get("t") or ""), **({"a": a, "b": b} if type(a) is int and type(b) is int else {}), "id": fid})
        return out

    def _ask_identity(session, incoming, target_binding, klaerungen, natives, trace_id, kontext="", text=""):
        """V92 Paket 16 (Paket-15-Pruefung; AMASTER §24.1, §24.7, §25): a name of this avatar/user input whose boundary or identity
        the server cannot prove (binder records, addressee decision) is asked BEFORE anything is stored - the caller's transaction
        is rolled back, the UI shows the question with the candidate figures and sends the same input again with the answer.
        V92 Paket 17: one question per written place, each signed for this input (_klaerung_fragen)."""
        _tt = next((r for r in (session.get("turnTruths") or []) if isinstance(r, dict) and r.get("id") == (incoming or {}).get("id")), None)
        _amb = (_tt or {}).get("input_component_ambiguity") or []
        _frag = kernel.identity_questions(_amb, target_binding, klaerungen, natives,
                                          present_ids=(session.get("scene") or {}).get("presentIds") or [])
        if not _frag:
            return
        _frag = _klaerung_fragen(_frag, kontext, text)
        matrix_live_log.live_log("TURN_INPUT", trace_id=trace_id, source_turn_id=(incoming or {}).get("id"), text=str((incoming or {}).get("text") or "")[:300],
                                 speech="", actions=[], ambiguous=_amb or None, abgelehnt="identitaet_klaeren", klaerung=_frag)
        raise WriterError(f"Eingabe: {kernel.identity_question_text(_frag)} Nichts wurde gespeichert. Bitte unten die gemeinte Figur wählen; "
                          "die Eingabe wird dann mit dieser Klärung erneut geprüft.", 422, "IDENTITAET_KLAEREN", details={"klaerung": _frag})

    def _reject_unexecutable_input(session, incoming, natives, trace_id):
        """V92 (Paket-8-Pruefung; AMASTER §24.7, §27.3): the kernel validated NOTHING of this avatar/user input (no own speech, no
        own act - e.g. only a denied or foreign act, only another figure's speech, a marked act without a reading). Nothing is
        written (the caller's transaction is rolled back), the person sees why and keeps the text - as on the puppet route."""
        _tt = next((r for r in (session.get("turnTruths") or []) if isinstance(r, dict) and r.get("id") == (incoming or {}).get("id")), None)
        if not isinstance(_tt, dict) or _tt.get("input_event_kind") != "nicht_ausfuehrbar":
            return
        _amb = _tt.get("input_component_ambiguity") or []
        _name = next((str(c.get("name") or "") for c in (natives or []) if isinstance(c, dict)
                      and str(c.get("id")) == str((incoming or {}).get("input_actor_id") or (incoming or {}).get("inputActorId") or "")), "") or "deiner Figur"
        matrix_live_log.live_log("TURN_INPUT", trace_id=trace_id, source_turn_id=(incoming or {}).get("id"), text=str((incoming or {}).get("text") or "")[:300],
                                 speech="", actions=[], ambiguous=_amb or None, abgelehnt="nichts_ausfuehrbar")
        _incomplete = not any(isinstance(a, dict) and isinstance(a.get("vorschlag"), dict) for a in _amb)
        raise WriterError(f"Eingabe: Nichts davon ist eine ausführbare Rede oder Handlung von {_name}: {kernel.input_rejection_text(_amb)}. "
                          "Nichts wurde gespeichert. Bitte anders formulieren (Handlung in *Sternchen*, Rede als eigene Worte).",
                          422, "PLAN_INCOMPLETE" if _incomplete else "EINGABE_NICHT_AUSFUEHRBAR")

    def _check_component_vollzug(conn, aid, plan, utterance, actor_name, data, *, where, present_figures=None, actor_id=None):
        """V92 (Gegenpruefung 04.11. Fall A; AMASTER §24.2): every act component gets one blind reading whether it HAPPENS in its
        utterance (not denied, wished, asked, conditional, announced, told, quoted). Network call, no write; the kernel validates."""
        from matrix_api.llm_contract import vollzug_check
        comps = plan.get("komponenten") if isinstance(plan, dict) else None
        if not isinstance(comps, list):
            return plan
        # a reading that came with the plan is not ours: remove first (also when no act is in the list); so is a marker flag
        comps = [({k: v for k, v in c.items() if k not in ("markierung", "sprecherPruefung")} if isinstance(c, dict) else c)
                 for c in kernel.apply_component_vollzug(comps, {})]
        # V92 Paket 12: an act component over several sentences -> one component per sentence, each with its own reading
        comps = kernel.split_compound_acts(comps)
        # V92 Paket 9: the input's own *marked* act the reading left out becomes a component of its own (same reading, same binder)
        comps = comps + kernel.marker_act_components(utterance, comps, actor_name)   # V92 Paket 10: every marker
        # V92 Paket 12/13: the speaker of an announced speech - one blind literal reading each (mandatory where the announcement
        # does not decide by itself); it also names an own act the announcement holds ("Johann lächelt und sagt:"), which becomes
        # a component of its own (kernel.announcement_act_components) with the same mandatory vollzug reading and binder
        from matrix_api.llm_contract import sprecher_check
        _figs = [f for f in (present_figures or []) if isinstance(f, dict)]
        # P22: a named subject at the beginning of planned "speech" can be
        # a narrated ACT. Also check components that the planner falsely
        # assigned to an addressee rather than to this Puppet. This semantic
        # reading is independent of the planner, and the kernel binds the
        # result to the original source and the already-authorized speaker ID.
        # Converted actions continue through vollzug_check and effect_check;
        # an unconfirmed type is rejected rather than written as speech.
        if where == "puppet":
            from matrix_api.llm_contract import komponentenart_check
            # P23: check against the authenticated world cast (including the
            # explicitly controlled absent Puppet), never the old presence
            # snapshot. Also check a completely empty scene; no bypass.
            _bound_actor_id = str(actor_id or "")
            if not _bound_actor_id or not any(str(f.get("id") or "") == _bound_actor_id for f in _figs):
                raise ValueError("puppet_actor_id_not_bound_to_authorized_cast")
            idx_kind = kernel.component_kind_candidate_indices(utterance, comps, _figs, _bound_actor_id)
            if idx_kind:
                kind_reads = {i: komponentenart_check(conn, aid or "admin", aeusserung=utterance,
                              segment=str(comps[i].get("segment") or ""), figur=actor_name, data=data)
                              for i in idx_kind}
                comps = kernel.apply_component_kind_readings(utterance, comps, kind_reads,
                         figures=_figs, actor_id=_bound_actor_id, actor_name=actor_name)
                matrix_live_log.live_log("COMPONENT_KIND_CHECK", trace_id=str((data or {}).get("sourceTurnId") or "component_kind"),
                    quelle=where, pruefungen=[{"segment": str(comps[i].get("segment") or "")[:160],
                    "modell": kind_reads.get(i), "ergebnis": comps[i].get("typ")} for i in idx_kind])
        for i in kernel.speaker_reading_indices(utterance, comps, _figs):
            _sr = sprecher_check(conn, aid or "admin", worte=str(comps[i].get("segment") or ""), figur=str(actor_name or ""),
                                 aeusserung=str(utterance or ""), ansage=str(comps[i].get("einleitung") or "") or None, data=data)
            comps[i] = {**comps[i], **({"sprecherPruefung": {"sprecher": str(_sr.get("sprecher") or "").strip()[:80], "beleg": _sr.get("beleg"),
                                                             "handlung": (str(_sr.get("handlung")).strip()[:160] or None) if isinstance(_sr.get("handlung"), str) else None,
                                                             # V92 Paket 14: the literal addressee of the words (bound by the kernel)
                                                             "adressat": (str(_sr.get("adressat")).strip()[:80] or None) if isinstance(_sr.get("adressat"), str) else None,
                                                             "ansageRolle": str(_sr.get("ansageRolle") or "").strip()[:24],
                                                             "ansageBeleg": (str(_sr.get("ansageBeleg")).strip()[:160] or None) if isinstance(_sr.get("ansageBeleg"), str) else None}}
                                       if _sr else {})}
            matrix_live_log.live_log("SPRECHER_CHECK", trace_id=str((data or {}).get("sourceTurnId") or "sprecher_check"), quelle=where,
                                     figure=actor_name, segment=str(comps[i].get("segment") or "")[:160], modell=_sr)
        comps = comps + kernel.announcement_act_components(utterance, comps, actor_name)
        plan = {**plan, "komponenten": comps}
        readings = {}
        for i, c in enumerate(comps):
            if isinstance(c, dict) and str(c.get("typ") or c.get("type") or "").strip().lower() == "handlung":
                readings[i] = vollzug_check(conn, aid or "admin", action=str(c.get("segment") or ""), figur=str(actor_name or ""),
                                            aeusserung=str(utterance or ""), data=data)
        plan = {**plan, "komponenten": comps}
        if not readings:
            return plan
        matrix_live_log.live_log("VOLLZUG_CHECK", trace_id=str((data or {}).get("sourceTurnId") or "vollzug_check"), quelle=where, figure=actor_name,
                                 pruefungen=[{"segment": str(comps[i].get("segment") or "")[:160], "planner": comps[i].get("geschieht"),
                                              "modell": r} for i, r in readings.items()])
        return {**plan, "komponenten": kernel.apply_component_vollzug(comps, readings)}

    def _check_component_effects(conn, aid, plan, utterance, actor_name, natives, data, *, where):
        """V65J (AMASTER §24.2: Kandidat -> Semantikanalyse -> Validierung -> Writer; Prüfbericht
        v2.2 Kette B/C): every body class a participant's OWN act is proposed to have
        (avatar input, puppet; the figure reply has _effect_check_step) gets the same small
        reading, with the utterance as context. Network call, no write; the kernel validates."""
        from matrix_api.llm_contract import effect_check, koerper_check
        comps = plan.get("komponenten") if isinstance(plan, dict) else None
        if isinstance(comps, list):
            # V92 Paket 18 (unabhaengige Pruefung Paket 17; AMASTER §43.1, §24.2/§24.7): the change each act that HAPPENS makes to
            # the actor's OWN body (position, falling asleep, waking up) - one blind reading per act with a literal quote; the kernel
            # validates it before the body writer. A reading that came with the plan is removed first.
            _kread = {i: koerper_check(conn, aid or "admin", handlung=str(comps[i].get("segment") or ""), figur=str(actor_name or ""),
                                       aeusserung=str(utterance or ""), data=data)
                      for i in kernel.own_body_check_indices(comps)}
            # V92 Paket 19: each proposed change gets its confirmation reading at the quote (second key) before the kernel
            _kread = {i: (_koerper_bestaetigen(conn, aid, {k: r.get(k) for k in ("haltung", "schlaf", "zeit", "beleg")},
                                               text=str(comps[i].get("segment") or "").replace("*", " ").strip(), figur=str(actor_name or ""),
                                               authority="character", data=data,
                                               trace_id=str((data or {}).get("sourceTurnId") or "koerper_check"), quelle=where)
                          if isinstance(r, dict) else r)
                      for i, r in _kread.items()}
            comps = kernel.apply_own_body_readings(comps, _kread)
            plan = {**plan, "komponenten": comps}
            if _kread:
                matrix_live_log.live_log("KOERPER_CHECK", trace_id=str((data or {}).get("sourceTurnId") or "koerper_check"), quelle=where,
                                         figure=actor_name, pruefungen=[{"segment": str(comps[i].get("segment") or "")[:160], "modell": _kread.get(i),
                                                                         "ergebnis": kernel.own_body_change(_kread.get(i), str(comps[i].get("segment") or "").replace("*", " ").strip())[1]}
                                                                        for i in _kread])
        idx = kernel.component_effect_checks(comps)
        if not idx:
            return plan
        readings = {}
        for i in idx:
            c = comps[i]
            readings[i] = effect_check(conn, aid or "admin", action=str(c.get("segment") or ""), akteur=str(actor_name or ""),
                                       ziel=str(c.get("ziel") or ""), vorschlag=str(c.get("wirkung") or ""),
                                       aeusserung=str(utterance or ""), data=data)
        checked = kernel.apply_component_effect_checks(comps, readings, figures=[n for n in (natives or []) if isinstance(n, dict)])
        # This second model question runs only for an initially denied violence
        # effect with a first-reading suggestion of physical contact.
        for i in idx:
            c = checked[i]
            if kernel.touch_confirmation_needed({"pruefung": c.get("wirkungPruefung")}):
                from matrix_api.llm_contract import touch_confirmation_check
                second = touch_confirmation_check(conn, aid or "admin", action=str(comps[i].get("segment") or ""),
                                                  akteur=str(actor_name or ""), ziel=str(comps[i].get("ziel") or ""), data=data)
                effect = kernel.apply_touch_confirmation({"art": c.get("wirkung"), "pruefung": c.get("wirkungPruefung")},
                                                         str(comps[i].get("segment") or ""), second,
                                                         figures=[n for n in (natives or []) if isinstance(n, dict)],
                                                         planned_target=str(comps[i].get("ziel") or ""))
                c["wirkung"], c["wirkungPruefung"] = effect.get("art"), effect.get("pruefung")
        for i in idx:
            # V65Q (AMASTER §43.1 attempted): the same follow-up for an unconfirmed movement.
            c = checked[i]
            if kernel.attempt_check_needed({"pruefung": c.get("wirkungPruefung")}):
                att = effect_check(conn, aid or "admin", action=str(comps[i].get("segment") or ""), akteur=str(actor_name or ""),
                                   ziel=str(comps[i].get("ziel") or ""), vorschlag=str(comps[i].get("wirkung") or ""),
                                   aeusserung=str(utterance or ""), data=data, attempt=True)
                c["wirkungPruefung"] = kernel.apply_attempt_check({"pruefung": c.get("wirkungPruefung")}, att).get("pruefung")
        matrix_live_log.live_log("EFFECT_CHECK", trace_id=str((data or {}).get("sourceTurnId") or "effect_check"), quelle=where,
                                 figure=actor_name, pruefungen=[{"segment": str(comps[i].get("segment") or "")[:160],
                                                                 "vorschlag": comps[i].get("wirkung"), "modell": readings.get(i),
                                                                 "ergebnis": checked[i].get("wirkung"),
                                                                 "pruefung": checked[i].get("wirkungPruefung")} for i in idx])
        return {**plan, "komponenten": checked}

    def _goal_theme_step(conn, aid, session, incoming, natives, trace_id):
        """V65H: network calls WITHOUT the SQLite write lock (as the planner and
        the appraisal); the write re-reads under the lock and rejects a
        concurrently advanced session. Only for an input to a figure."""
        from matrix_api.llm_contract import goal_frames, goal_theme_check
        target = str((incoming or {}).get("target_id") or "")
        actor = str((incoming or {}).get("input_actor_id") or "")
        names = {str(c.get("id")): str(c.get("name") or "") for c in natives if isinstance(c, dict)}
        if not target or target == actor or target not in names:
            return session
        _data = {"sessionId": session.get("id"), "worldId": session.get("worldId"), "sourceTurnId": incoming.get("id"), "speakerId": target}
        need = kernel.goal_frames_needed(session, target)
        frames = goal_frames(conn, aid or "admin", figure=names[target], persons=sorted({n for n in names.values() if n}),
                             goals=need, data=_data) if need else None
        probe = copy.deepcopy(session)
        frame_proto = kernel.apply_goal_frames(probe, target, frames, natives) if frames is not None else []
        speaker_name = names.get(actor) or kernel.operator_label(session, None, natives)
        checks = []
        for g in kernel.goal_theme_candidates(probe, target, actor):
            res = goal_theme_check(conn, aid or "admin", text=str(incoming.get("text") or ""), speaker=speaker_name,
                                   figure=names[target], unsaid=str((g.get("frame") or {}).get("ungesagt") or ""), data=_data)
            checks.append((str(g.get("id")), res))
        # V65L (AMASTER §25, §34 Antwortbezug, §41.1; Kettenvertrag §6.5): only when the reading of HIS input alone did
        # not bind and the structure shows that he answers HER line of an exchange already bound to this goal, one more
        # reading asks whether he answers its theme part. No candidate -> no call (unchanged V65K path).
        from matrix_api.llm_contract import answer_reference_check
        answers = []
        for gid, res in checks:
            if not isinstance(res, dict) or res.get("angesprochen") is True:
                continue
            cont = kernel.answer_continuation(probe, target, actor, str(incoming.get("id") or ""), gid)
            if cont is None:
                continue
            res2 = answer_reference_check(conn, aid or "admin", line=str(cont["herFact"].get("text") or ""),
                                          text=str(incoming.get("text") or ""), speaker=speaker_name, figure=names[target],
                                          unsaid=str((cont["goal"].get("frame") or {}).get("ungesagt") or ""), data=_data)
            answers.append((gid, str(cont["herFact"].get("id")), res2))
        if frames is None and not checks:
            return session
        conn.execute("BEGIN IMMEDIATE")
        try:
            locked = _kernel_stored_session(conn, aid, {"sessionId": session.get("id")})
            if (int(locked.get("turnIndex") or 0) != int(session.get("turnIndex") or 0)
                    or str(locked.get("pendingInputTurnId") or "") != str(session.get("pendingInputTurnId") or "")):
                raise WriterError("session advanced while reading goal frames", 409, "STALE_SESSION")
            if frames is not None:
                kernel.apply_goal_frames(locked, target, frames, natives)
            bound = [{"goalId": gid, **kernel.apply_goal_theme(locked, target, actor, str(incoming.get("id") or ""), gid, res),
                      "modell": {k: (res or {}).get(k) for k in ("angesprochen", "beleg", "thema")}} for gid, res in checks]
            bound += [{"goalId": gid, "lesung": "antwortbezug", "ihreZeile": her_id,
                       **kernel.apply_answer_reference(locked, target, actor, str(incoming.get("id") or ""), gid, her_id, res2),
                       "modell": {k: (res2 or {}).get(k) for k in ("antwortet", "art", "beleg_aeusserung", "beleg_ihre_zeile")}}
                      for gid, her_id, res2 in answers]
            out = kernel_session_response(conn, aid or "admin", locked)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        matrix_live_log.live_log("GOAL_THEME", trace_id=trace_id, status="COMMITTED", figure=names[target],
                                 frames=[{**f, "wer": names.get(str(f.get("wer") or ""), f.get("wer"))} for f in frame_proto] if frames is not None else None,
                                 checks=bound)
        return out

    def _appraise_perceived(conn, aid, session, natives, trace_id):
        """V62: appraisal step. Network call WITHOUT the SQLite write lock (as
        the input planner); the write re-reads under the lock and rejects a
        concurrently advanced session. Without provider only decay runs."""
        from matrix_api.llm_contract import appraise_events, _last_llm_error
        pend = kernel.pending_appraisals(session, natives)
        result = None
        payload = None
        if pend:
            payload = kernel.appraisal_payload(session, natives, pend)
            result = appraise_events(conn, aid or "admin", payload, data={
                "sessionId": session.get("id"), "worldId": session.get("worldId"),
                "sourceTurnId": session.get("pendingInputTurnId"), "speakerId": ""})
            for _bw in ((result or {}).get("bewertungen") or []) if isinstance(result, dict) else []:
                if isinstance(_bw, dict):
                    _llm_vorab.vorab_registrieren(_bw.get("lesungen"), quelle="erleben")   # Stand 11: Absichtsart aus derselben Antwort
            # V65Q (AMASTER §42 Z. 2305/2315; Pruefung v2.8 P-06): a proposed "intent done"
            # gets ONE reading of how that intent is carried out (rede|handlung), still
            # without the write lock; the kernel takes the evidence from canonical Facts.
            if isinstance(result, dict):
                _claims = kernel.intent_resolution_claims(session, pend, result)
                if _claims:
                    from matrix_api.llm_contract import intent_kind
                    _kinds = {}
                    for _c in _claims:
                        _r = intent_kind(conn, aid or "admin", absicht=_c["intent"], data={
                            "sessionId": session.get("id"), "worldId": session.get("worldId"),
                            "sourceTurnId": session.get("pendingInputTurnId"), "speakerId": _c["id"]})
                        _kinds[_c["id"]] = _r if isinstance(_r, dict) else {"fehler": True}
                    result = {**result, "absichtArt": _kinds}
        probe = copy.deepcopy(session)
        if not pend or result is None:
            if not kernel.refresh_affects(probe):
                if pend:
                    matrix_live_log.live_log("APPRAISAL", trace_id=trace_id, status="NO_RESULT", error=_last_llm_error(),
                        figures=[p["name"] for p in pend], events=sum(len(p["events"]) for p in pend))
                return session
        conn.execute("BEGIN IMMEDIATE")
        try:
            locked = _kernel_stored_session(conn, aid, {"sessionId": session.get("id")})
            if (int(locked.get("turnIndex") or 0) != int(session.get("turnIndex") or 0)
                    or str(locked.get("pendingInputTurnId") or "") != str(session.get("pendingInputTurnId") or "")):
                raise WriterError("session advanced while appraising", 409, "STALE_SESSION")
            out, proto = kernel.apply_appraisals(locked, pend if result is not None else [], result, natives=natives)
            out = kernel_session_response(conn, aid or "admin", out)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        names = {str(c.get("id")): str(c.get("name") or "") for c in natives if isinstance(c, dict)}
        matrix_live_log.live_log("APPRAISAL", trace_id=trace_id, status="COMMITTED" if result is not None else "DECAY_ONLY",
            error=None if result is not None or not pend else _last_llm_error(),
            figures=[{"figure": e.get("figure"), "events": e.get("events"), "affect": e.get("affect"), "intent": e.get("intent"),
                      "runtime": {k: v.get("to") for k, v in (e.get("runtimeDelta") or {}).items()},
                      "relations": [{"to": r.get("toName"), "after": r.get("after")} for r in e.get("relationDelta") or []],
                      "rejects": e.get("rejects"), "notes": e.get("notes")} for e in proto],
            proposals=(result or {}).get("bewertungen") if isinstance(result, dict) else None,
            intentKinds=(result or {}).get("absichtArt") if isinstance(result, dict) else None,
            emotions={names.get(cid, cid): {"emotion": rt.get("emotion"), "intensity": rt.get("intensity")}
                      for cid, rt in (out.get("runtimes") or {}).items() if isinstance(rt, dict) and rt.get("affects") is not None})
        return out

    def _rule_plan(conn, aid, session, target_id, recipient, counterpart, rules, components, open_frames, data):
        """V61 (Prolog: rule x fact), extracted unchanged in V65b so the input
        path and the Regie path use ONE reader. 1) The CONDITION kind of each
        authored rule is classified once per rule set (cached in the session
        by the kernel, provenance rule_kind_compile). 2) The kernel evaluates
        handlung/worte/wiederholung itself from committed Facts. 3) Only when
        several rules share one kind, a neutral per-input check names which of
        them applies; the kernel accepts it only with the same kind and a
        bound Fact. Returns the plan keys "regelarten"/"profilregeln"."""
        import hashlib as _hl
        out: dict = {}
        _h = _hl.sha256("\n".join(rules).encode("utf-8")).hexdigest()[:16]
        _known = ((session.get("ruleKinds") or {}).get(target_id) or {}) if isinstance(session.get("ruleKinds"), dict) else {}
        kinds = _known.get("rules") if _known.get("hash") == _h else None
        if kinds is None:
            _goal_lines = []
            for g in session.get("goals") or []:
                if isinstance(g, dict) and str(g.get("ownerId") or "") == target_id and g.get("kind") == "stamm":
                    d = g.get("sourceDefinition") if isinstance(g.get("sourceDefinition"), dict) else {}
                    _goal_lines.append(f"[{g.get('id')}]" + (f" Phase {d.get('phase')}:" if d.get("phase") else "")
                                       + f" {str(g.get('text') or '')[:160]}" + (f" (erreicht, wenn: {str(d.get('exit'))[:120]})" if d.get("exit") else ""))
            kinds = extract_rule_kinds(conn, aid or "admin", figure_name=recipient or "", rules=rules,
                                       goals=_goal_lines, data=data)
            if kinds is not None:
                out["regelarten"] = {"ownerId": target_id, "hash": _h, "rules": kinds}
        _arts = [str(r.get("art") or "") for r in (kinds or []) if isinstance(r, dict)]
        # V65b: a rule whose condition names a particular act/utterance
        # ("bestimmt") is checked like rules sharing one kind.
        other = [int(r.get("nr")) for r in (kinds or []) if isinstance(r, dict) and str(r.get("nr") or "").isdigit()
                 and str(r.get("art") or "") in ("handlung", "worte", "wiederholung")
                 and (_arts.count(str(r.get("art"))) > 1 or r.get("bestimmt") is True)]
        # A "handlung" condition can only be met by an act component (§34.1);
        # without one the kernel binds nothing, so no check is asked for.
        _has_act = any(isinstance(c, dict) and c.get("typ") == "handlung" for c in (components or []))
        _art_of = {int(r.get("nr")): str(r.get("art") or "") for r in (kinds or []) if isinstance(r, dict) and str(r.get("nr") or "").isdigit()}
        other = [nr for nr in other if _art_of.get(nr) != "handlung" or _has_act]
        if other and isinstance(components, list) and components:
            trig = extract_rule_triggers(conn, aid or "admin", figure_name=recipient or "", counterpart_name=counterpart,
                                         rules=rules, components=components, open_frames=open_frames,
                                         data=data, only=other)
            if trig is not None:
                out["profilregeln"] = [t for t in trig if str(t.get("nr") or "").isdigit() and int(t["nr"]) in other]
        return out

    def _extract_user_plan(conn, aid, session, truth, natives):
        """V39: Plan der Nutzer-/Avatar-Rede über den Provider (falls konfiguriert)."""
        try:
            text = str((truth or {}).get("text") or "").strip()
            if not text or str((truth or {}).get("input_kind") or "") not in ("speech", "user"):
                return None
            by_id = {str(n.get("id")): str(n.get("name") or "") for n in (natives or []) if isinstance(n, dict)}
            actor_id = str((truth or {}).get("input_actor_id") or "")
            # V92 Paket 13 (Browser-Folgezug 05.11.: the operator's "Wie geht es dir?" came back with akteur "Bedienperson", a name the
            # binder does not know as the operator's own -> 422): the operator is named by the ONE canonical label
            # (kernel.operator_label) that commit_turn also accepts as the operator's own name
            speaker_name = by_id.get(actor_id) or (str(session.get("alias") or "Spieler") if actor_id == str(session.get("avatarId") or "")
                                                   else kernel.operator_label(session, truth, natives))
            recipient = by_id.get(str((truth or {}).get("target_id") or ""))
            from matrix_api import conjunctive as _c
            # V60 (AMASTER §35/§36.1): open requests with their Proposition ID,
            # so a component that answers one can name it ("bezug"); the kernel
            # validates the reference. Other open frames stay as text.
            open_frames = []
            for p in session.get("propositions") or []:
                if not isinstance(p, dict) or p.get("status") not in ("open", "active", "accepted"):
                    continue
                if actor_id not in (str(p.get("actorId") or ""), str(p.get("targetId") or "")):
                    continue
                who = by_id.get(str(p.get("actorId") or "")) or (str(session.get("alias") or "") if str(p.get("actorId")) == str(session.get("avatarId")) else "")
                whom = by_id.get(str(p.get("targetId") or "")) or (str(session.get("alias") or "") if str(p.get("targetId")) == str(session.get("avatarId")) else "")
                # V61 (AMASTER §35): the canonical restatement count of this
                # same matter (evidence "restated"), so a rule whose condition
                # is repetition can be bound to the Proposition.
                _rest = sum(1 for e in (p.get("evidence") or []) if isinstance(e, dict) and e.get("kind") == "restated")
                open_frames.append(f"[{p.get('id')}] {who} → {whom}: {str(p.get('matter') or p.get('text') or '')[:140]}"
                                   + (f" (von {who} bisher {_rest + 1}-mal gestellt)" if _rest else ""))
            # V60 (AMASTER §35, §41.3): the addressee's own open goals with ID, so
            # the planner can relate an act/answer to one ("bezug"). Relevance
            # only — the kernel validates; the exit is decided by the owner.
            target_id = str((truth or {}).get("target_id") or "")
            for g in session.get("goals") or []:
                if (isinstance(g, dict) and target_id and str(g.get("ownerId") or "") == target_id
                        and g.get("status") in ("open", "active", "accepted")
                        and not (g.get("proposition_id") or g.get("propositionId")) and g.get("kind") == "stamm"):
                    d = g.get("sourceDefinition") if isinstance(g.get("sourceDefinition"), dict) else {}
                    open_frames.append(f"[{g.get('id')}] Ziel von {by_id.get(target_id, '')}: {str(g.get('text') or '')[:140]}"
                                       + (f" (erreicht, wenn: {str(d.get('exit'))[:120]})" if d.get("exit") else ""))
            open_frames += [f.get("what") for f in _c.frames_for(session, actor_id)
                            if f.get("status") in _c.FRAME_OPEN and f.get("kind") != "bitte"]
            # V61 (AMASTER §15, §14 Konfliktverhalten): the addressee's authored
            # reaction rules (stem, canonical projection). Never the avatar's.
            recipient_rules: list[str] = []
            if target_id and target_id != str(session.get("avatarId") or ""):
                from matrix_api.learning import canonical_stem as _cstem
                _rc = next((n for n in (natives or []) if isinstance(n, dict) and str(n.get("id") or "") == target_id), None)
                if _rc is not None:
                    recipient_rules = [str(r) for r in (_cstem(_rc).get("reactionRules") or []) if str(r or "").strip()]
            _data = {"sessionId": session.get("id"), "worldId": session.get("worldId"),
                     "sourceTurnId": truth.get("id"), "speakerId": actor_id}
            # V92 Paket 13 (Bedingung D): the present persons of this session as context, speaker and selected recipient as IDs
            _cast = dict(anwesende=kernel.planner_cast(session, natives), sprecher_id=actor_id, empfaenger_id=target_id or None)
            plan = extract_turn_plan(conn, aid or "admin", text, speaker_name=speaker_name, recipient_name=recipient,
                                     open_frames=open_frames, data=_data, today=(kernel.today_view(session) or {}).get("text"), **_cast)
            if isinstance(plan, dict) and not (isinstance(plan.get("komponenten"), list) and plan.get("komponenten")):
                # V92 (Paket 9; live 05.11.: 10 of 24 avatar speech readings came without `komponenten`): the reading lacks the
                # required components - ONE repeat of the same reading, as on the puppet route. Still incomplete: the kernel
                # reports it (zerlegung_unvollstaendig) and the route writes nothing (no silent speech, no act).
                matrix_live_log.live_log("PLAN_EXTRACT", trace_id=str(truth.get("id") or "plan"), status="INCOMPLETE_RETRY", error="komponenten_fehlen")
                _plan2 = extract_turn_plan(conn, aid or "admin", text, speaker_name=speaker_name, recipient_name=recipient,
                                           open_frames=open_frames, data=_data, today=(kernel.today_view(session) or {}).get("text"), **_cast)
                if isinstance(_plan2, dict):
                    plan = _plan2
            if isinstance(plan, dict):
                _llm_vorab.vorab_registrieren(plan.get("lesungen"), quelle="eingabe")   # Stand 11
                # V65S (AMASTER §24.1/§25; Pruefung v3.1 §6 Schritt 2): the cast figures this input names, by the
                # cast data (no model, no pronoun guess); recall arbitration activates her memories of them.
                plan["betrifft_ids"] = kernel.bind_referents(text, natives)
                if isinstance(plan.get("verweis"), dict):
                    # V65T (AMASTER §24.1/§24.7/§25; Plan v2 Schritt 2a): a pronoun for a third person (the reading's
                    # signal) is bound by the kernel from the lines the speaker heard - exactly one candidate or none.
                    _vb = kernel.bind_pronoun_referent(session, text, plan.get("verweis"), speaker_id=actor_id,
                                                       addressee_id=target_id or None, figures=natives)
                    plan["verweis_bindung"] = _vb
                    if _vb.get("gebunden") and _vb["gebunden"] not in plan["betrifft_ids"]:
                        plan["betrifft_ids"] = (plan["betrifft_ids"] + [_vb["gebunden"]])[:4]
                _pres = set(str(x) for x in ((session.get("scene") or {}).get("presentIds") or []))
                plan = _check_component_vollzug(conn, aid, plan, text, speaker_name, _data, where="eingang",
                                                present_figures=[n for n in natives if isinstance(n, dict) and str(n.get("id")) in _pres])
                plan = _check_component_effects(conn, aid, plan, text, speaker_name, natives, _data, where="eingang")
                plan = _boundary_reference_step(conn, aid, session, actor_id, speaker_name, plan, text, natives, _data,
                                                trace_id=str(truth.get("id") or "plan"), where="eingang")
                plan = _answer_boundary_candidate(session, plan, text, actor_id, target_id, natives)
                if isinstance(plan.get("grenze"), dict):
                    plan["grenze"] = _consent_scope_check(conn, aid, plan["grenze"], text, _data,
                                                          trace_id=str(truth.get("id") or "plan"), where="eingang")
                plan = _read_language(conn, aid, plan, text, speaker_name, recipient, natives, _data,
                                      trace_id=str(truth.get("id") or "plan"), where="eingang")
            if isinstance(plan, dict) and recipient_rules:
                plan.update(_rule_plan(conn, aid, session, target_id, recipient or "", speaker_name, recipient_rules,
                                       plan.get("komponenten"), open_frames, _data))
            return plan
        except Exception as exc:  # Plan ist Zusatz — nie ein Turnabbruch
            matrix_live_log.live_log("PLAN_EXTRACT", trace_id="plan", status="FAIL", error=str(exc)[:160])
            return None

    def _kernel_world_and_natives(conn, aid, session):
        world = {}
        natives: list = []
        wid = session.get("worldId")
        if wid:
            try:
                world = get_world(conn, str(wid), aid or session.get("userId") or "admin") or {}
            except (WriterError, KeyError, IsolationError):
                world = {}
        if not isinstance(world, dict):
            world = {}
        try:
            listed = list_characters(conn, aid or session.get("userId") or "admin")
            all_chars = listed.get("characters") if isinstance(listed, dict) else listed
            for row in all_chars or []:
                if isinstance(row, dict) and (not wid or row.get("worldId") == wid or row.get("world_id") == wid):
                    natives.append(row)
        except (WriterError, KeyError, IsolationError):
            natives = []
        # V65K (AMASTER §24.1 known_as, scope = this session): read projection, never a stem write.
        return world, kernel.with_session_aliases(natives, session)

    @app.post("/api/kernel/move")
    def kernel_move():
        body = request.get_json(silent=True) or {}
        trace_id = str(body.get("trace_id") or body.get("traceId") or matrix_live_log.new_trace_id("km"))
        last = "UI_REQUEST"
        matrix_live_log.live_log("UI_REQUEST", trace_id=trace_id, endpoint="/api/kernel/move")
        aid, err = _kernel_actor(body)
        if err is not None and not aid:
            return err
        try:
            def _persist(conn):
                nonlocal last
                session = _kernel_stored_session(conn, aid, body)
                world, natives = _kernel_world_and_natives(conn, aid, session)
                if isinstance(body.get("world"), dict) and body["world"].get("places") and not world.get("places"):
                    world = {**world, "places": body["world"].get("places")}
                last = "KERNEL_BIND"
                place_id = body.get("placeId") or body.get("place_id") or ""
                mover_id = body.get("moverId") or body.get("mover_id") or session.get("avatarId") or ""
                out = kernel.apply_move(session, world, str(place_id), str(mover_id), natives=natives)
                last = "WRITER"
                saved = kernel_session_response(conn, aid or out.get("userId") or "admin", out)
                matrix_live_log.live_log("SQLITE_COMMIT", trace_id=trace_id, status="PASS", session_id=saved.get("id"))
                return {"ok": True, "session": saved, "trace_id": trace_id}

            return _run_write(_persist)
        except IsolationError as exc:
            return _json_error(str(exc), str(exc), 403, "ISOLATION")
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_MOVE", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)

    @app.post("/api/kernel/presence")
    def kernel_presence():
        body = request.get_json(silent=True) or {}
        trace_id = str(body.get("trace_id") or body.get("traceId") or matrix_live_log.new_trace_id("kps"))
        last = "UI_REQUEST"
        matrix_live_log.live_log("UI_REQUEST", trace_id=trace_id, endpoint="/api/kernel/presence")
        aid, err = _kernel_actor(body)
        if err is not None and not aid:
            return err
        try:
            def _persist(conn):
                nonlocal last
                session = _kernel_stored_session(conn, aid, body)
                world, natives = _kernel_world_and_natives(conn, aid, session)
                last = "KERNEL_BIND"
                cid = body.get("characterId") or body.get("character_id") or ""
                out = kernel.apply_presence(session, str(cid), world=world, natives=natives)
                last = "WRITER"
                saved = kernel_session_response(conn, aid or out.get("userId") or "admin", out)
                matrix_live_log.live_log("SQLITE_COMMIT", trace_id=trace_id, status="PASS", session_id=saved.get("id"))
                return {"ok": True, "session": saved, "trace_id": trace_id}

            return _run_write(_persist)
        except IsolationError as exc:
            return _json_error(str(exc), str(exc), 403, "ISOLATION")
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_PRESENCE", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)

    @app.post("/api/kernel/perception")
    def kernel_perception():
        """V2/V3: visible UI control for explicit hears/sees overrides.

        The request may choose the override value, but it never supplies a
        replacement scene/session blob. SQL session state is loaded first and
        the kernel mutates only the requested perception control.
        """
        body = request.get_json(silent=True) or {}
        aid, err = _kernel_actor(body)
        if err is not None and not aid:
            return err

        def _persist(conn):
            session = _kernel_stored_session(conn, aid, body)
            kind = str(body.get("kind") or "")
            if kind not in ("hearsIds", "seesIds"):
                raise WriterError("invalid perception kind", 400, "BAD_REQUEST")
            explicit = body.get("explicit", True)
            ids = body.get("ids")
            if explicit is False:
                ids = None
            elif not isinstance(ids, list):
                raise WriterError("perception ids must be a list", 400, "BAD_REQUEST")
            if isinstance(ids, list):
                world_id = str(session.get("worldId") or "")
                for raw in ids:
                    cid = str(raw or "").strip()
                    if not cid:
                        continue
                    row = conn.execute("SELECT world_id FROM characters WHERE id=?", (cid,)).fetchone()
                    if row is None:
                        raise WriterError(f"figure {cid} not found", 404, "FIGURE_NOT_FOUND")
                    if world_id and str(row["world_id"]) != world_id:
                        raise WriterError("perception figure belongs to another world", 409, "FIGURE_WORLD_MISMATCH")
            out = kernel.apply_perception_override(session, kind, ids)
            saved = kernel_session_response(conn, aid, out)
            return {"ok": True, "session": saved}

        return _run_write(_persist)

    @app.post("/api/kernel/fate")
    def kernel_fate():
        body = request.get_json(silent=True) or {}
        trace_id = str(body.get("trace_id") or body.get("traceId") or matrix_live_log.new_trace_id("kf"))
        last = "UI_REQUEST"
        matrix_live_log.live_log("UI_REQUEST", trace_id=trace_id, endpoint="/api/kernel/fate")
        aid, err = _kernel_actor(body)
        if err is not None and not aid:
            return err
        try:
            def _persist(conn):
                nonlocal last
                session = _kernel_stored_session(conn, aid, body)
                last = "KERNEL_BIND"
                enabled = body.get("enabled")
                if enabled is None:
                    enabled = (body.get("fate") or {}).get("enabled") if isinstance(body.get("fate"), dict) else body.get("fate")
                if enabled is not None and not isinstance(enabled, bool):
                    enabled = str(enabled).lower() in ("1", "true", "on", "yes")
                world = {}
                wid = session.get("worldId")
                if wid:
                    try:
                        world = get_world(conn, str(wid), aid or session.get("userId") or "admin") or {}
                    except (WriterError, KeyError, IsolationError):
                        world = {}
                if not isinstance(world, dict):
                    world = {}
                out = kernel.apply_fate(
                    session,
                    seed_id=body.get("seedId") or body.get("seed_id"),
                    beat=body.get("beat"),
                    pressure=body.get("pressure"),
                    proposal=body.get("proposal"),
                    enabled=enabled,
                    world=world,
                )
                last = "WRITER"
                saved = kernel_session_response(conn, aid or out.get("userId") or "admin", out)
                matrix_live_log.live_log("SQLITE_COMMIT", trace_id=trace_id, status="PASS", session_id=saved.get("id"))
                return {"ok": True, "session": saved, "trace_id": trace_id}

            return _run_write(_persist)
        except IsolationError as exc:
            return _json_error(str(exc), str(exc), 403, "ISOLATION")
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_FATE", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)

    @app.post("/api/kernel/autochat-gate")
    def kernel_autochat_gate():
        body = request.get_json(silent=True) or {}
        aid, err = _kernel_actor(body)
        if err is not None and not aid:
            return err
        try:
            def _read(conn):
                session = _kernel_stored_session(conn, aid, body)
                _world, natives = _kernel_world_and_natives(conn, aid, session)
                remaining = body.get("remaining")
                if remaining is None:
                    remaining = (session.get("autoChat") or {}).get("turns") or 0
                res = kernel.autochat_gate(
                    session,
                    natives,
                    remaining,
                    user_decision=body.get("user_decision") or body.get("userDecision") or body.get("reason"),
                    stimulus=str(body.get("stimulus") or body.get("text") or ""),
                )
                # V65J (AMASTER §65 Diagnose, §48; Prüfbericht v2.2 IST-Karte "Log / Abnahme"): who
                # speaks next after Regie/God/AutoChat and why is part of the live log now.
                try:
                    _names = {str(n.get("id")): str(n.get("name") or "") for n in natives if isinstance(n, dict)}
                    _res = res if isinstance(res, dict) else {}
                    matrix_live_log.live_log(
                        "AUTOCHAT_GATE", trace_id=str(body.get("trace_id") or body.get("traceId") or "gate"),
                        session_id=session.get("id"), turn=session.get("turnIndex"), remaining=remaining,
                        stop=bool(_res.get("stop")), reason=_res.get("reason"),
                        speaker=_names.get(str(_res.get("speakerId") or ""), _res.get("speakerId")),
                        candidates=[{"name": _names.get(str(c.get("id") or ""), c.get("id")), "score": c.get("score"),
                                     "reasons": (c.get("reasons") or [])[:4]} for c in (_res.get("candidates") or [])[:5] if isinstance(c, dict)])
                except Exception:
                    pass
                return res

            return _run_read(_read)
        except IsolationError as exc:
            return _json_error(str(exc), str(exc), 403, "ISOLATION")
        except Exception as exc:
            return _json_error("KERNEL_FAILED", str(exc), 400)

    # B.26: Backend ist Source of Truth für Compass-Trigger-Liste.
    # Frontend (src/lib/matrix/compass.ts) liest diese Liste statt eigener
    # TRIGGERS-Konstante, damit es keine Drift zwischen UI und Engine gibt.
    @app.get("/api/compass/triggers")
    def compass_triggers():
        from matrix_api.kernel import _COMPASS_TRIGGERS
        return jsonify(
            {
                "triggers": {space: list(words) for space, words in _COMPASS_TRIGGERS.items()},
                "spaces": list(_COMPASS_TRIGGERS.keys()),
                "version": "v18-b26",
            }
        )

    @app.post("/api/kernel/reset")
    def kernel_reset():
        body = request.get_json(silent=True) or {}
        aid, err = _kernel_actor(body)
        if err is not None and not aid:
            return err
        kind = body.get("kind") or "chat"
        try:
            def _persist(conn):
                # V2/Bruch 21: the client session/characters blob is not a
                # reset input. Only the session id selects SQL canonical state.
                session = _kernel_stored_session(conn, aid, body)
                sid = str(session.get("id") or "")
                if kind == "chat":
                    result = reset_session_chat(conn, sid, {"turnIndex": 0, "focus": {}}, aid)
                elif kind == "runtime":
                    result = reset_session_runtime(conn, sid, {}, aid)
                elif kind == "memory":
                    result = reset_session_memory(conn, sid, aid)
                elif kind == "uploads":
                    result = reset_session_uploads(conn, sid, aid)
                else:
                    raise WriterError("unknown reset kind", 400, "BAD_REQUEST")
                return {
                    "ok": True,
                    "session": result.get("session"),
                    **({"deleted": result.get("deleted")} if kind == "uploads" else {}),
                }

            return _run_write(_persist)
        except IsolationError as exc:
            return _json_error(str(exc), str(exc), 403, "ISOLATION")
        except WriterError as exc:
            return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
        except Exception as exc:
            return _json_error("KERNEL_FAILED", str(exc), 400)

    @app.errorhandler(404)
    def _ui_fallback(err):
        path = request.path or "/"
        if path.startswith("/api/") or path == "/api":
            return err
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return err
        return _proxy_preview()

    return app


app = create_app()

PORT_IN_USE_TEMPLATE = "PORT {port} already in use. Set PORT=... or stop the other process."


def _proxy_preview():
    import urllib.error
    import urllib.request

    origin = os.environ.get("MATRIX_PREVIEW_ORIGIN", "http://127.0.0.1:8080")
    url = origin.rstrip("/") + (request.full_path or "/")
    if url.endswith("?"):
        url = url[:-1]
    headers = {}
    for key, val in request.headers:
        if key.lower() in {"host", "connection", "content-length", "transfer-encoding"}:
            continue
        headers[key] = val
    body = request.get_data() or None
    req = urllib.request.Request(url, data=body, headers=headers, method=request.method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            out = [
                (k, v)
                for k, v in resp.headers.items()
                if k.lower() not in {"transfer-encoding", "connection", "content-encoding"}
            ]
            return payload, resp.status, out
    except urllib.error.HTTPError as exc:
        return exc.read(), exc.code, [("Content-Type", exc.headers.get("Content-Type", "text/html; charset=utf-8"))]
    except Exception:
        html = (
            "<!doctype html><html lang=de><head><meta charset=utf-8><title>MATRIX</title></head>"
            "<body><p>Oberfläche startet. Neu laden.</p></body></html>"
        )
        return html, 503, [("Content-Type", "text/html; charset=utf-8")]


def _is_addr_in_use(exc: BaseException) -> bool:
    err = getattr(exc, "errno", None)
    if err in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", None)):
        return True
    return "address already in use" in str(exc).lower()


def _ensure_port_free(host: str, port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        if _is_addr_in_use(exc):
            print(PORT_IN_USE_TEMPLATE.format(port=port), file=sys.stderr)
            raise SystemExit(1) from exc
        raise
    finally:
        sock.close()


def main() -> int:
    host = os.environ.get("MATRIX_API_HOST") or os.environ.get("HOST") or "127.0.0.1"
    if host in ("0.0.0.0", "::", "[::]"):
        host = "127.0.0.1"
    port = int(os.environ.get("MATRIX_API_PORT") or os.environ.get("PORT", "5050"))
    try:
        _ensure_port_free(host, port)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1
    try:
        app.run(host=host, port=port, threaded=True)
    except OSError as exc:
        if _is_addr_in_use(exc):
            print(PORT_IN_USE_TEMPLATE.format(port=port), file=sys.stderr)
            return 1
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
