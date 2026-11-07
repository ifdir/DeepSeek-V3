#!/usr/bin/env python3
"""Externe, fail-closed Freigabesperre fuer Matrix10 P25.

Kein Produktpatch. Kein Produktstart. Keine automatische Freigabe ohne
externe/echte Kettenabnahme nach AMASTER, SPS und Kettenvertrag.
Python-Standardbibliothek; produktfremdes Skript, SHA im Ergebnisbericht.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from zipfile import ZipFile, BadZipFile

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "PRUEFREGELN.json"
CHECKPOINTS = [
    "SOLL-Vertrag und konkrete Erwartung",
    "Ausgangs-ZIP, SHA-256 und Datenbank",
    "Reale UI-Bedienung",
    "IDs, Rolle, Modus, Actor, Target, Scope, Authority",
    "Backendroute und erste serverseitige Bindung",
    "Kanonischer Owner und Writer",
    "Zustand vor dem Write",
    "Zustand nach dem Write",
    "Fact-, Proposition-, Goal-, Memory-, Relationship-IDs",
    "Wissensverteilung und ausgeschlossene Unwissende",
    "Runtime-, Koerper-, Beziehungs-, SceneState-Folgen",
    "Zustaendiger Recall/Reader",
    "BrainContext",
    "Sichtbare Antwort und Komponentencommit",
    "Zustand im Folgeturn",
    "Reload/Neustart und Persistenz",
    "Sichtbare UI-Rueckanzeige",
    "Negative Isolation fremder User/Welten/Sessions/Figuren",
    "Pruefung am frisch entpackten Release-ZIP",
    "Status mit konkreter Begruendung",
]


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def add(checks: list[dict], ident: str, status: str, detail: str, log: str | None = None):
    assert status in ('PASS', 'ROT', 'BLOCKIERT', 'UNGEPRUEFT')
    obj = {'id': ident, 'status': status, 'detail': detail}
    if log:
        obj['log'] = log
    checks.append(obj)
    print(f'[{status}] {ident}: {detail}', flush=True)


def release_status(checks: list[dict], axes: dict) -> str:
    # Fail closed: empty checklist can never become GREEN.
    if not checks or not axes:
        return 'BLOCKIERT'
    if any(c['status'] == 'ROT' for c in checks):
        return 'ROT'
    if any(c['status'] != 'PASS' for c in checks):
        return 'BLOCKIERT'
    if any(any(row['status'] != 'GRUEN' for row in rows) for rows in axes.values()):
        return 'BLOCKIERT'
    # Deliberate final guard: This v1 does not implement independent full E2E.
    # Only subsequent auditor versions may enable release after proving all axes.
    return 'BLOCKIERT'


def safe_zip_members(z: ZipFile) -> tuple[str, int]:
    """Fail for zip slip, symlink, duplicates, multi-root, bombs, missing root."""
    entries = z.infolist()
    if not entries:
        raise ValueError('ZIP ist leer')
    roots, seen, total = set(), set(), 0
    for info in entries:
        s = info.filename
        p = PurePosixPath(s)
        if not s or '\\' in s or s.startswith('/') or s.startswith('//') or p.is_absolute():
            raise ValueError('Unsicherer ZIP-Pfad: ' + repr(s))
        if re.match(r'^[A-Za-z]:', s) or '..' in p.parts or '.' in p.parts:
            raise ValueError('Unsicherer ZIP-Pfad: ' + repr(s))
        if s in seen:
            raise ValueError('Doppelter ZIP-Pfad: ' + repr(s))
        seen.add(s)
        if not p.parts or len(p.parts) < 2 and not info.is_dir():
            raise ValueError('Unerwartete ZIP-Rootstruktur: ' + repr(s))
        roots.add(p.parts[0])
        if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
            raise ValueError('Symlink im ZIP: ' + repr(s))
        if info.file_size > 70 * 1024 * 1024:
            raise ValueError('Einzeldatei zu gross: ' + repr(s))
        total += info.file_size
        if total > 400 * 1024 * 1024:
            raise ValueError('ZIP entpackt zu gross')
    if len(roots) != 1:
        raise ValueError('Mehrere ZIP-Projektroots: ' + ', '.join(sorted(roots)))
    error = z.testzip()
    if error:
        raise ValueError('CRC defekt: ' + error)
    return next(iter(roots)), len(entries)


def assert_manifest(root: Path) -> tuple[int, list[str]]:
    manifest = root / 'P25_MANIFEST.json'
    if not manifest.is_file():
        raise ValueError('P25_MANIFEST.json fehlt')
    m = json.loads(manifest.read_text(encoding='utf-8'))
    files = m.get('sha256_files')
    if not isinstance(files, dict) or not files:
        raise ValueError('SHA-256-Dateiliste fehlt')
    mismatch = []
    for rel, expected in files.items():
        path = root / rel
        if not path.is_file() or sha_file(path) != expected:
            mismatch.append(rel)
    versionhash = m.get('version_unchanged_sha256')
    if versionhash and sha_file(root / 'VERSION.txt') != versionhash:
        mismatch.append('VERSION.txt vs. eingefrorener Parent')
    return len(files), mismatch


def only_project_files(root: Path) -> dict[str, str]:
    paths = ('VERSION.txt', 'package.json', 'package-lock.json',
             '2_7master.txt', 'MATRIX10_SPS_MASTER.md',
             'VERBINDLICHER_REPARATUR_KETTENVERTRAG.txt')
    d = {}
    for p in paths:
        f = root / p
        if f.is_file():
            d[p] = sha_file(f)
    for sub in ('src', 'matrix_api', 'tests'):
        for f in (root / sub).rglob('*'):
            if f.is_file() and f.suffix in ('.ts', '.tsx', '.js', '.py', '.cjs', '.mjs'):
                d[str(f.relative_to(root)).replace('\\', '/')] = sha_file(f)
    return d


def process_step(checks, logs: Path, ident: str, argv: list[str], cwd: Path,
                 env: dict, timeout_seconds: int, *, missing_as='BLOCKIERT'):
    log = logs / (re.sub('[^A-Za-z0-9_-]', '_', ident) + '.txt')
    print('RUN', ident, ' '.join(argv[:4]), flush=True)
    try:
        with log.open('w', encoding='utf-8', errors='replace') as f:
            f.write('COMMAND: ' + ' '.join(argv) + '\n\n')
            f.flush()
            res = subprocess.run(argv, cwd=str(cwd), env=env, stdout=f,
                                 stderr=subprocess.STDOUT, timeout=timeout_seconds,
                                 check=False)
        if res.returncode == 0:
            add(checks, ident, 'PASS', 'Exitcode 0; Rohbeleg vorhanden', log.name)
        else:
            add(checks, ident, 'ROT', f'Exitcode {res.returncode}; Rohbeleg lesen', log.name)
    except subprocess.TimeoutExpired:
        add(checks, ident, 'BLOCKIERT', f'Zeitgrenze von {timeout_seconds}s ueberschritten', log.name)
    except OSError as e:
        add(checks, ident, missing_as, f'Ausfuehrung fehlt: {e}', log.name)


def make_axes(config: dict):
    return {name: [{'schritt': i + 1, 'beschreibung': label, 'status': 'UNGEPRUEFT',
                    'beleg': None} for i, label in enumerate(CHECKPOINTS)]
            for name in config['pflichtachsen']}


def write_report(report_dir: Path, checks: list[dict], axes: dict,
                 metadata: dict) -> str:
    status = release_status(checks, axes)
    payload = {'gate': 'MATRIX10_FREIGABESPERRE_V1', 'gesamtstatus': status,
               'produktfreigabe': False, 'basis': metadata,
               'pruefungen': checks, 'vertragsachsen': axes,
               'hinweis': 'V1 prueft nie automatisch GRUEN: reale UI/Provider/SQLite/Folgeturn/Isolation nicht implementiert.'}
    (report_dir / 'ERGEBNIS.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['MATRIX10 - UNABHAENGIGE FREIGABESPERRE V1',
             '=' * 65, f'GESAMTSTATUS: {status}', 'PRODUKTFREIGABE: NEIN',
             '', 'BASIS (unveraenderliches ZIP)',
             json.dumps(metadata, ensure_ascii=False, indent=2), '', 'PRUEFSCHRITTE']
    for c in checks:
        lines.append(f"[{c['status']}] {c['id']}: {c['detail']}" + (f" (Log {c['log']})" if c.get('log') else ''))
    lines += ['', 'PFLICHTACHSEN: JEWEILS 20 KETTENGLIEDER NACH §16',
              'Diese Achsen sind NICHT durch Einzeltests abgeschlossen.']
    for k, rows in axes.items():
        missing = sum(r['status'] != 'GRUEN' for r in rows)
        lines.append(f'[UNGEPRUEFT] {k}: {missing}/{len(rows)} Kettenglieder ohne E2E-Beleg')
    lines += ['', 'ABSCHLUSS',
              'Fehlende Voraussetzungen sind keine bestandenen Tests.',
              'Keine Produktcode-Aenderung. Keine Kundendatenbank angefasst.',
              'Das Testskript erstellt keinen Beweis fuer echte Provider-/Browser-/Folgeturn-Ketten.',
              'Keine GRUEN-Aussage und kein Produkt-Release erlaubt.',
              '', 'Maschinenlesbare Details: ERGEBNIS.json',
              'Alle Ausgaben einzelner Pruefungen: *.txt im LOGS-Ordner', '']
    (report_dir / 'ERGEBNIS_LESEN.txt').write_text('\n'.join(lines), encoding='utf-8')
    return status


def run_main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Matrix10 externe Freigabesperre, nie Produktfreigabe durch Einzeltests')
    ap.add_argument('--preflight-only', action='store_true', help='Nur Basis und Vertragsluecken; keine Tests/Build')
    ap.add_argument('--install-dependencies', action='store_true', help='Im frischen Arbeitsordner npm ci ausfuehren')
    ns = ap.parse_args(argv)
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    candidate = BASE / config['paketdatei']
    report_dir = BASE / ('ERGEBNIS_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    logs = report_dir / 'LOGS'
    logs.mkdir(parents=True, exist_ok=True)
    checks: list[dict] = []
    axes = make_axes(config)
    meta = {'gate_script_sha256': sha_file(Path(__file__)),
            'pruefregeln_sha256': sha_file(CONFIG), 'zeit_utc': datetime.now(timezone.utc).isoformat(),
            'basisdatei': candidate.name,
            'basis_sha256_erwartet': config['paket_sha256'],
            'kundendatenbank': 'NICHT GELESEN; nur isoliertes Pruefverzeichnis'}
    project = None
    safe = False
    temp = tempfile.TemporaryDirectory(prefix='matrix10_gate_')
    try:
        if not candidate.is_file():
            add(checks, '01_paket', 'ROT', 'Kandidaten-ZIP fehlt: ' + candidate.name)
        else:
            meta['basis_bytes'] = candidate.stat().st_size
            actual_hash = sha_file(candidate)
            meta['basis_sha256_gemessen'] = actual_hash
            if actual_hash != config['paket_sha256']:
                add(checks, '01_paket', 'ROT', 'SHA-256 stimmt NICHT; falsches oder veraendertes Paket')
            else:
                add(checks, '01_paket', 'PASS', 'P25-ZIP stimmt bytegenau mit eingefrorenem Hash ueberein')
                try:
                    with ZipFile(candidate) as z:
                        rootname, count = safe_zip_members(z)
                        meta['zip_eintraege'] = count
                        meta['root'] = rootname
                        z.extractall(temp.name)
                    project = Path(temp.name) / rootname
                    safe = True
                    add(checks, '02_zip_integritaet', 'PASS', f'{count} Eintraege; CRC, Pfade und Entpackgrenzen OK')
                except (BadZipFile, OSError, ValueError) as ex:
                    add(checks, '02_zip_integritaet', 'ROT', str(ex))
        if safe and project is not None:
            try:
                n, mismatches = assert_manifest(project)
                add(checks, '03_innenmanifest', 'PASS' if not mismatches else 'ROT',
                    f'{n} Datei-SHA-256 verglichen; Abweichungen: {mismatches[:8] or "keine"}')
            except (OSError, ValueError, KeyError) as ex:
                add(checks, '03_innenmanifest', 'ROT', str(ex))
            for doc in config['aktuelle_sollquellen']:
                p = project / doc['pfad']
                state = ('PASS' if p.is_file() and sha_file(p) == doc['sha256'] else 'ROT')
                add(checks, '04_soll_' + p.name, state, 'Aktuelle vorliegende Quelle hashgeprueft' if state == 'PASS' else 'Fehlend oder hashabweichend')
            # DO NOT silently equate new master documents with normative SHA in §0.
            legacy = [d['pfad'] for d in config['vertrag_normreferenzen'] if not (project / d['pfad']).is_file()]
            add(checks, '05_normreferenzen_klaeren', 'BLOCKIERT' if legacy else 'PASS',
                'Kettenvertrag §0 benennt andere normative Dateien: ' + (', '.join(legacy) if legacy else 'alle vorhanden'))
            if not (project / 'START.bat').is_file():
                add(checks, '06_windows_standardstarter', 'BLOCKIERT', 'START.bat fehlt; Produktstart nach §18 nicht abgenommen')
            else:
                add(checks, '06_windows_standardstarter', 'UNGEPRUEFT', 'START.bat vorhanden, realer Start noch nicht pruefbar')
            if not (BASE / config['epub_testdatei']).is_file():
                add(checks, '07_epub_fixture', 'BLOCKIERT', 'Verbindliches EPUB fuer §7 fehlt neben Gate')
            else:
                epath = BASE / config['epub_testdatei']
                isgood = sha_file(epath) == config['epub_sha256']
                add(checks, '07_epub_fixture', 'PASS' if isgood else 'ROT',
                    'Test-EPUB korrekt vorhanden' if isgood else 'Test-EPUB hat falschen Hash')
            meta['version_sha256'] = sha_file(project / 'VERSION.txt') if (project / 'VERSION.txt').exists() else None
            before = only_project_files(project)
            env = os.environ.copy()
            for name in list(env):
                if re.search(r'(API[_-]?KEY|SECRET|_TOKEN$|^OPENAI_|^ANTHROPIC_)', name, re.I):
                    env.pop(name, None)
            # Keep all test-created state in the temporary, fresh extract.
            isolated_db = project / 'data' / 'matrix10_gate.sqlite'
            isolated_db.parent.mkdir(exist_ok=True)
            env['MATRIX_DB'] = str(isolated_db)
            isolated_profile = project / '_gate_home'
            isolated_profile.mkdir(exist_ok=True)
            for var in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'TMP', 'TEMP', 'TMPDIR'):
                env[var] = str(isolated_profile)
            env['PYTHONPATH'] = os.pathsep.join([str(project), str(project / 'tests')])
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            env['CI'] = '1'
            if ns.preflight_only:
                add(checks, '08_tests', 'UNGEPRUEFT', 'Nur Vorpruefung angefordert; volle Suite nicht ausgefuehrt')
                add(checks, '09_frontend', 'UNGEPRUEFT', 'Nur Vorpruefung angefordert; Frontend nicht gebaut')
            else:
                if importlib.util.find_spec('pytest') is None:
                    add(checks, '08_vollsuite', 'BLOCKIERT', 'pytest fehlt')
                elif importlib.util.find_spec('flask') is None:
                    add(checks, '08_vollsuite', 'BLOCKIERT', 'Flask fehlt: Routen-Suite nicht ausfuehrbar; kein Teil-PASS als Ersatz')
                else:
                    process_step(checks, logs, '08_vollsuite',
                                 [sys.executable, '-m', 'pytest', '-q', 'tests'], project, env, 480)
                if importlib.util.find_spec('flask') is None:
                    add(checks, '08_unabhaengige_gegenproben', 'BLOCKIERT', 'Flask fehlt; Gegenproben nicht als abgenommen ausgeben')
                else:
                    process_step(checks, logs, '08_unabhaengige_gegenproben',
                                 [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'audit_*.py', '-q'], project, env, 240)
                node, npm = shutil.which('node'), shutil.which('npm')
                if not node or not npm:
                    add(checks, '09_frontend_build', 'BLOCKIERT', 'Node/npm fehlen')
                else:
                    if not (project / 'node_modules').is_dir():
                        if ns.install_dependencies:
                            process_step(checks, logs, '09_npm_ci',
                                [npm, 'ci', '--no-audit', '--no-fund'], project, env, 900)
                        else:
                            add(checks, '09_npm_ci', 'BLOCKIERT',
                                'Abhaengigkeiten fehlen in frischem ZIP; fuer Installation Windows-Pruefstart nutzen')
                    if (project / 'node_modules').is_dir():
                        process_step(checks, logs, '09_frontend_build',
                                     [npm, 'run', 'build:dist'], project, env, 540)
                        if (project / 'frontend_dist' / 'index.html').is_file():
                            infofile = project / 'frontend_dist' / '.build-info.json'
                            if not infofile.is_file():
                                add(checks, '09_build_identitaet', 'ROT', '.build-info.json fehlt')
                            else:
                                info = json.loads(infofile.read_text(encoding='utf-8'))
                                version = (project / 'VERSION.txt').read_text(encoding='utf-8')
                                build_id = next((line.split('=', 1)[1].strip() for line in version.splitlines() if line.startswith('BUILD_ID=')), None)
                                good = info.get('buildId') == build_id and info.get('frontendCompiledAnew') is True
                                add(checks, '09_build_identitaet', 'PASS' if good else 'ROT',
                                    'Frisch gebaut; Kennung ist gleich' if good else 'Kennung stimmt nicht')
                        else:
                            add(checks, '09_build_identitaet', 'ROT', 'frontend_dist nicht gebaut')
                        process_step(checks, logs, '09_typescript_typecheck',
                                     [npm, 'run', 'typecheck'], project, env, 300)
                        process_step(checks, logs, '09_frontend_followup_tests',
                                     [npm, 'run', 'test:frontend-followup'], project, env, 180)
            # Every mandatory E2E step has to be independent and exercised on exact ZIP.
            if not (project / 'scripts/amaster-browser-e2e.mjs').is_file():
                add(checks, '10_browser_e2e', 'BLOCKIERT',
                    'package.json nennt test:browser-e2e, Skript fehlt; echte UI-E2E nicht nachgewiesen')
            else:
                add(checks, '10_browser_e2e', 'UNGEPRUEFT', 'Skript vorhanden; keine ausgefuehrte Provider/SQLite/Folgeturn-E2E-Abnahme')
            add(checks, '11_live_modell_und_folgeturn', 'UNGEPRUEFT',
                'Kein unabhaengiger E2E-Adapter fuer echtes Modell + SQLite-Writer + Folgeturn + Replay')
            add(checks, '12_frontend_backend_matrix', 'UNGEPRUEFT',
                'Kein nachweisbarer bidirektionaler UI-/Writer-/Reader-Katalog')
            add(checks, '13_aktive_testdb_migration_start', 'BLOCKIERT',
                'Testet temporaere DB, aber nicht mitgelieferten Standardstart samt Migration und Neustart')
            # Pre-existing known open contract findings are NOT allowed to disappear
            # when dependencies are missing or the new checks were never run.
            prior = [x['id'] for x in config.get('offene_vorbefunde', [])]
            add(checks, '16_offene_vertragsvorbefunde', 'ROT' if prior else 'BLOCKIERT',
                ('Nicht erneut am Live-System verifiziert; laut P25-Bericht ungeklärt: '
                 + ', '.join(prior)) if prior else 'Keine geprüfte Liste offener Vertragsvorbefunde')
            after = only_project_files(project)
            diff = sorted(set(before) ^ set(after) | {k for k in before.keys() & after.keys() if before[k] != after[k]})
            add(checks, '14_unveraenderte_quelldateien', 'PASS' if not diff else 'ROT',
                'Source/Vertrag/VERSION unveraendert' if not diff else 'Produktquellen im Test veraendert: ' + ', '.join(diff[:12]))
        # Whether happy or failed, source ZIP never mutated.
        if candidate.is_file() and 'basis_sha256_gemessen' in meta:
            changed = sha_file(candidate) != meta['basis_sha256_gemessen']
            add(checks, '15_original_zip_unveraendert', 'ROT' if changed else 'PASS',
                'Kandidaten-ZIP unveraendert' if not changed else 'Kandidaten-ZIP wurde veraendert')
    except Exception as exc:
        add(checks, '99_unerwartete_ausnahme', 'ROT', f'{type(exc).__name__}: {exc}')
    finally:
        temp.cleanup()
    status = write_report(report_dir, checks, axes, meta)
    print('\n' + '=' * 55, flush=True)
    print('GESAMTSTATUS: ' + status + ' | PRODUKTFREIGABE: NEIN', flush=True)
    print('Lesbarer Bericht: ' + str(report_dir / 'ERGEBNIS_LESEN.txt'), flush=True)
    print('Maschinenbericht: ' + str(report_dir / 'ERGEBNIS.json'), flush=True)
    return 2 if status == 'ROT' else 3


if __name__ == '__main__':
    raise SystemExit(run_main())
