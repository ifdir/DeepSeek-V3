#!/usr/bin/env python3
"""Build a disposable SOURCE-ONLY V67+Rust04 tree; never update original.

This stages NOT an installable Matrix10 product.  It validates the unchanged
V67 archive before and after extraction, then overlays only declared files.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import stat
from pathlib import Path
import zipfile

ORIGINAL_SHA256="5158df268ab7f9105428b26c90932998e5b7b10fb8a3926e97ff2c4aa382efed"
ROOT="MATRIX10_V67_ABHAENGIGKEIT_20261031"
MODIFIED=("matrix_api/repos.py","matrix_api/scene_state.py")
NEW=("RUST_MIGRATION_STATUS.json","matrix_api/native_boundary.py")

def digest(p:Path):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()

def run(a):
    original=Path(a.original_zip).resolve();root=Path(a.out).resolve();this=Path(__file__).resolve().parents[1]
    if root.exists(): raise SystemExit("REFUSED: staging target already exists; fresh empty target required")
    if digest(original)!=ORIGINAL_SHA256: raise SystemExit("REFUSED: V67 original archive hash differs")
    # Validate entries before touching disk; no symlinks or path traversal.
    with zipfile.ZipFile(original) as z:
        infos=[f for f in z.infolist() if not f.is_dir()]
        paths=set()
        for f in z.infolist():
            p=Path(f.filename)
            if (p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!=ROOT
                    or ((f.external_attr>>16) & stat.S_IFMT(stat.S_IFLNK)) == stat.S_IFLNK):
                raise SystemExit("REFUSED: unsafe original ZIP member")
            if f.filename in paths:raise SystemExit("REFUSED: duplicate ZIP entry")
            paths.add(f.filename)
        root.mkdir(parents=True)
        z.extractall(root)
    product=root/ROOT
    if not product.is_dir():raise SystemExit("REFUSED: original root missing")
    for rel in MODIFIED:
        shutil.copy2(this/"integration"/Path(rel).name, product/rel)
    shutil.copy2(this/"integration"/"native_boundary.py",product/"matrix_api/native_boundary.py")
    shutil.copytree(this/"integration/native_core",product/"native_core")
    shutil.copy2(this/"integration/RUST_MIGRATION_STATUS.json",product/"RUST_MIGRATION_STATUS.json")
    changed=[];preserved=0
    with zipfile.ZipFile(original) as z:
        for f in infos:
            rel=str(Path(f.filename).relative_to(ROOT))
            path=product/rel
            if not path.is_file():raise SystemExit("REFUSED: original member lost: "+rel)
            raw=z.read(f.filename)
            if hashlib.sha256(raw).digest() != bytes.fromhex(digest(path)):
                changed.append(rel)
            else: preserved+=1
    assert sorted(changed)==sorted(MODIFIED),changed
    expected={str(p.relative_to(product)) for p in product.rglob('*') if p.is_file()}
    originals={str(Path(f.filename).relative_to(ROOT)) for f in infos}
    added=sorted(expected-originals)
    intended=set(NEW)|{str(p.relative_to(this/'integration')) for p in (this/'integration/native_core').rglob('*') if p.is_file()}
    if set(added)!=intended: raise SystemExit("REFUSED: unexpected additions: "+str(set(added)^intended))
    db_candidates=[x for x in originals if x.startswith('data/') and x.endswith(('.db','.sqlite','.sqlite3'))]
    report={"kind":"SOURCE_STAGING_ONLY_NOT_RELEASE", "original_archive_sha256":ORIGINAL_SHA256,
            "unchanged_original_files":preserved,"changed_original_files":changed,
            "original_total_files":len(infos),"added_files":added,
            "product_release":False,"native_build_executed":False,
            "original_database_hashes":{x:digest(product/x) for x in db_candidates}}
    (root/"STAGE_VERIFICATION_04.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('original_zip');p.add_argument('out');run(p.parse_args())
