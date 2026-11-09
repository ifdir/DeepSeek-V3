#!/usr/bin/env python3
"""Prueft die Sperrlogik selbst, nicht die Produktfunktion."""
import importlib.util
from pathlib import Path
import tempfile
import zipfile

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('gate', here / 'FREIGABE_PRUEFEN.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

sample = {'Puppet': [{'status': 'UNGEPRUEFT'}]}
assert module.release_status([{'status': 'PASS'}], sample) == 'BLOCKIERT'
assert module.release_status([{'status': 'ROT'}], sample) == 'ROT'
assert module.release_status([{'status': 'PASS'}], {}) == 'BLOCKIERT'
assert module.release_status([], {'Puppet': [{'status': 'GRUEN'}]}) == 'BLOCKIERT'
# Even manually placing all GRUEN does not bypass the mandatory independent live E2E gate.
assert module.release_status([{'status': 'PASS'}], {'Puppet': [{'status': 'GRUEN'}]}) == 'BLOCKIERT'
with tempfile.TemporaryDirectory() as t:
    p = Path(t) / 'danger.zip'
    with zipfile.ZipFile(p, 'w') as z:
        z.writestr('root/../escape.txt', 'no')
    with zipfile.ZipFile(p) as z:
        try: module.safe_zip_members(z)
        except ValueError: pass
        else: raise AssertionError('ZIP-Traversal nicht abgefangen')
    p = Path(t) / 'duplicate.zip'
    with zipfile.ZipFile(p, 'w') as z:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            z.writestr('root/a.txt', 'one')
            z.writestr('root/a.txt', 'two')
    with zipfile.ZipFile(p) as z:
        try: module.safe_zip_members(z)
        except ValueError: pass
        else: raise AssertionError('ZIP-Duplikat nicht abgefangen')
# End-to-end: a different ZIP under the expected name must never pass the gate.
with tempfile.TemporaryDirectory() as d:
    import shutil, subprocess, json, sys
    t = Path(d)
    shutil.copy2(here / 'FREIGABE_PRUEFEN.py', t / 'FREIGABE_PRUEFEN.py')
    shutil.copy2(here / 'PRUEFREGELN.json', t / 'PRUEFREGELN.json')
    cfg = json.loads((t / 'PRUEFREGELN.json').read_text(encoding='utf-8'))
    with zipfile.ZipFile(t / cfg['paketdatei'], 'w') as z:
        z.writestr('root/x.txt', 'FAKE')
    proc = subprocess.run([sys.executable, str(t / 'FREIGABE_PRUEFEN.py'), '--preflight-only'],
        cwd=t, capture_output=True, text=True, timeout=20)
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    assert 'SHA-256 stimmt NICHT' in proc.stdout, proc.stdout
    assert 'PRODUKTFREIGABE: NEIN' in proc.stdout, proc.stdout
print('SELBSTTEST PASS: Rot-/Blockierlogik, ZIP-Traversal, Duplikate und falscher Paket-Hash sperren.')
