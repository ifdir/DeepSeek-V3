#!/usr/bin/env python3
"""K2 (vom Nutzer freigegeben): overlay/matrix_api/app.py aus P25-app.py, NUR Fehlerabbildung NativeBoundaryError -> 503.

Eingriffe ausschliesslich an den gemessen betroffenen Stellen (evidence/chain_06/D3_vorher_*.json):
  1. _run_write: Rollback + 503 vor den allgemeinen Zweigen (regie, presence, perception, move, fate, reset);
     _run_read: 503 (autochat-gate).
  2. Routen /api/kernel/god, /puppet, /prepare, /commit: eigener Zweig vor `except Exception` (dort sonst 400 KERNEL_FAILED).
     06a / M2: prepare meldet, ob die Eingabe VOR dem Ausfall bereits gespeichert war (details.eingabeGespeichert).
  3. create_app: errorhandler fuer nicht abgefangene Faelle (GET /api/sessions/<id>), mit Rollback.
Keine neue Route, keine Aenderung an Einwilligungsregeln oder Zustandsverwaltung.
Aufruf: python3 -I build_overlay_app_06.py <P25-app.py> <ziel>
"""
import hashlib, sys
from pathlib import Path

P25_SHA_PREFIX = None   # wird beim ersten Lauf aus der Datei gelesen und im Bericht festgehalten


def main():
    src = Path(sys.argv[1]).read_text(encoding="utf-8")
    out = src

    def rep(a, b, n=1):
        nonlocal out
        assert out.count(a) == n, (a[:80], out.count(a))
        out = out.replace(a, b)

    rep("from matrix_api import kernel\n",
        "from matrix_api import kernel\n"
        "from matrix_api.native_boundary import NativeBoundaryError   # Stand 06 / K2: Fehler des Rust-Einwilligungskerns\n")
    rep('''        return jsonify(out), 200
    except SnapshotForbidden as exc:''',
        '''        return jsonify(out), 200
    except NativeBoundaryError as exc:
        # Stand 06 / K2 (AMASTER §65 "Fehler duerfen nicht verschluckt werden", fail-closed): the Rust consent core is
        # unavailable or refused its contract - nothing is committed, the client gets 503 with the boundary's code.
        conn.rollback()
        return _json_error(exc.code, exc.message, 503, exc.code)
    except SnapshotForbidden as exc:''')
    rep('''        except WriterError as exc:
            return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_GOD", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)''',
        '''        except WriterError as exc:
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
            return _json_error("KERNEL_FAILED", str(exc), 400)''')
    rep('''        except WriterError as exc:
            return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_PUPPET", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)''',
        '''        except WriterError as exc:
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
            return _json_error("KERNEL_FAILED", str(exc), 400)''')
    # _run_read (gemessen: autochat-gate gibt den Fehler sonst an das 400 der Route weiter)
    rep('''        return jsonify(out), 200
    except IsolationError as exc:
        return _json_error(str(exc), str(exc), 403, "ISOLATION")''',
        '''        return jsonify(out), 200
    except NativeBoundaryError as exc:   # Stand 06 / K2: read path of the consent core unavailable -> 503, no state derived
        return _json_error(exc.code, exc.message, 503, exc.code)
    except IsolationError as exc:
        return _json_error(str(exc), str(exc), 403, "ISOLATION")''')
    # 06a / M2: Helfer fuer die zutreffende Meldung, wenn die Eingabe vor dem Ausfall gespeichert war
    rep('''def _run_read(fn):''',
        '''_PREPARE_NACH_EINGABE = ("INPUT_COMMITTED", "KERNEL_BIND", "BRAIN_CONTEXT")


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


def _run_read(fn):''')
    rep('''                    "trace_id": trace_id,
                }

            return _run_read(_read)
        except IsolationError as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="VALIDATION", exc=exc, last_successful_stage=last)''',
        '''                    "trace_id": trace_id,
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
            matrix_live_log.live_error(trace_id=trace_id, stage="VALIDATION", exc=exc, last_successful_stage=last)''')
    # Routen prepare / commit (gemessen: 400 KERNEL_FAILED, Kern ausserhalb _run_write erreicht)
    # Stand 06a / M2: in prepare die tatsaechlich erreichte Stufe nach TX1 festhalten (vorhandene Variable `last`)
    rep('''                        except Exception:
                            conn.rollback()
                            raise
                        matrix_live_log.live_log("SQLITE_COMMIT", trace_id=trace_id,
                            status="INPUT_COMMITTED", session_id=session.get("id"),''',
        '''                        except Exception:
                            conn.rollback()
                            raise
                        # Stand 06a / M2: the input is committed (its own consent was decided inside this transaction)
                        last = "INPUT_COMMITTED"
                        matrix_live_log.live_log("SQLITE_COMMIT", trace_id=trace_id,
                            status="INPUT_COMMITTED", session_id=session.get("id"),''')
    rep('''        except WriterError as exc:
            return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="KERNEL_PREPARE", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)''',
        '''        except WriterError as exc:
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
            return _json_error("KERNEL_FAILED", str(exc), 400)''')
    for stage in ("KERNEL_COMMIT",):
        rep(f'''        except WriterError as exc:
            return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="{stage}", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)''',
            f'''        except WriterError as exc:
            return _json_error(exc.error, exc.message, exc.status, exc.error, details=getattr(exc, "details", None))
        except NativeBoundaryError as exc:   # Stand 06 / K2: measured 400 KERNEL_FAILED before
            matrix_live_log.live_error(trace_id=trace_id, stage="{stage}", exc=exc, last_successful_stage=last)
            try:
                _get_conn().rollback()
            except Exception:
                pass
            return _json_error(exc.code, exc.message, 503, exc.code)
        except Exception as exc:
            matrix_live_log.live_error(trace_id=trace_id, stage="{stage}", exc=exc, last_successful_stage=last)
            return _json_error("KERNEL_FAILED", str(exc), 400)''')
    rep('''    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
''',
        '''    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(NativeBoundaryError)
    def _native_boundary_unavailable(exc):
        # Stand 06 / K2: a consent-core failure no route caught itself (measured: puppet, GET /api/sessions/<id>)
        try:
            _get_conn().rollback()
        except Exception:
            pass
        return _json_error(exc.code, exc.message, 503, exc.code)
''')
    Path(sys.argv[2]).write_text(out, encoding="utf-8")
    print("overlay app.py geschrieben; P25 app.py SHA-256", hashlib.sha256(src.encode()).hexdigest())


if __name__ == "__main__":
    main()
