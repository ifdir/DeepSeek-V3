#!/usr/bin/env python3
"""K2 (vom Nutzer freigegeben): overlay/matrix_api/app.py aus P25-app.py, NUR Fehlerabbildung NativeBoundaryError -> 503.

Eingriffe ausschliesslich an den gemessen betroffenen Stellen (evidence/chain_06/D3_vorher_*.json):
  1. _run_write: Rollback + 503 vor den allgemeinen Zweigen (regie, presence, perception, move, fate, reset);
     _run_read: 503 (autochat-gate).
  2. Routen /api/kernel/god, /puppet, /prepare, /commit: eigener Zweig vor `except Exception` (dort sonst 400 KERNEL_FAILED).
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
    # Routen prepare / commit (gemessen: 400 KERNEL_FAILED, Kern ausserhalb _run_write erreicht)
    for stage in ("KERNEL_PREPARE", "KERNEL_COMMIT"):
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
