#!/usr/bin/env python3
"""Erzeugt overlay/matrix_api/scene_state.py aus P25-scene_state.py (unveraendert gelesen)
und den Rust-Readern aus Stand 05. Deterministisch, jede Ersetzung wird gezaehlt.

Aufruf: python3 -I build_overlay_06.py <P25-scene_state.py> <05-integration/scene_state.py> <ziel>
"""
import re, sys
from pathlib import Path

P25_SHA = "34c70dbd12281e2b"   # Praefix SHA-256 P25 matrix_api/scene_state.py


def block(src, name):
    m = re.search(r'^def ' + name + r'\b.*?(?=^def |^_[A-Z_]+ *=|^[A-Z_]+ *=|^# |\Z)', src, re.M | re.S)
    if not m:
        raise SystemExit(f"Funktion {name} fehlt")
    return m.group(0)


def main():
    import hashlib
    p25 = Path(sys.argv[1]).read_text(encoding="utf-8")
    if hashlib.sha256(p25.encode()).hexdigest()[:16] != P25_SHA:
        raise SystemExit("P25 scene_state.py hat nicht den eingefrorenen Hash")
    s05 = Path(sys.argv[2]).read_text(encoding="utf-8")
    out = p25
    # 1. Die drei Einwilligungsreader + die beiden Restriktionsvergleiche: Rust-Owner aus Stand 05 (ABI 3)
    for name in ("body_contact_standing", "restricted_refusals_standing", "restricted_permissions_standing",
                 "names_restriction", "same_restriction"):
        old, new = block(out, name), block(s05, name)
        assert out.count(old) == 1, name
        out = out.replace(old, new.rstrip("\n") + "\n\n\n")
    # 2. body_contact_entries: P25-Schleife (lifecycle_evidence) bleibt; nur die ABI-3-Felder kommen hinzu
    a = '''    pid = str(prop.get("id") or "")
    out = []
    for i, f in lifecycle_evidence(session):'''
    b = '''    pid = str(prop.get("id") or "")
    out = []
    by_id = {str(f.get("id") or ""): f for f in session.get("facts") or [] if isinstance(f, dict)}
    for i, f in lifecycle_evidence(session):'''
    assert out.count(a) == 1; out = out.replace(a, b)
    a = '''        out.append({"index": i, "factId": f.get("id"), "kind": kind, "turn": int(f.get("turn") or 0), "text": str(f.get("text") or ""),
                    "by": str(f.get("actorId") or ""), "acts": [str(x) for x in kk.get("actFactIds") or []],'''
    b = '''        acts = [str(x) for x in kk.get("actFactIds") or []]
        # Stand 06 / ABI 3 (AMASTER §34.1/§35): the persisted texts of the concrete acts this answer is bound to
        # (kernel._body_contact_answer actFactIds). Only transported; Rust decides which part an act names.
        # Bound only if every named act exists in this session.
        found = [by_id[x] for x in acts if x in by_id]
        out.append({"index": i, "factId": f.get("id"), "kind": kind, "turn": int(f.get("turn") or 0), "text": str(f.get("text") or ""),
                    "by": str(f.get("actorId") or ""), "acts": acts,
                    "actTexts": [str(x.get("text") or "") for x in found], "actsBound": bool(acts) and len(found) == len(acts),'''
    assert out.count(a) == 1; out = out.replace(a, b)
    # 3. Schreibgrenze W1/W3 im vorhandenen einzigen Vertrag lifecycle_bound (Writer + alle Reader)
    a = '''    pid, gid = _lc_subject(f)
    if not pid and not gid:
        return True'''
    b = '''    pid, gid = _lc_subject(f)
    _pl = f.get("payload") if isinstance(f.get("payload"), dict) else {}
    _kk = isinstance(_pl.get("koerperkontakt"), dict) and _KK_KIND.get(str(f.get("event_kind") or "").lower()) is not None
    if not pid and not gid:
        # Stand 06 (W3; AMASTER §35 dieselbe Angelegenheit, §36.2): an answer about body contact names its matter
        return not _kk'''
    assert out.count(a) == 1; out = out.replace(a, b)
    a = '''    props = {str(p.get("id")): p for p in (session or {}).get("propositions") or [] if isinstance(p, dict) and p.get("id")}
    parties = set()'''
    b = '''    props = {str(p.get("id")): p for p in (session or {}).get("propositions") or [] if isinstance(p, dict) and p.get("id")}
    if _kk and pid in props and props[pid].get("kind") == "koerperkontakt":
        # Stand 06 (W1; AMASTER §36.2 "die antwortende Figur der berechtigte Empfaenger", §36.3 "Sprecher und Empfaenger
        # stimmen", SPS V65S "nur die Beruehrte entscheidet"; kernel.apply_proposition writes these answers only from the
        # touched figure): consent to body contact is accepted, refused or revoked only by the giver (targetId).
        return actor == str(props[pid].get("targetId") or "")
    parties = set()'''
    assert out.count(a) == 1; out = out.replace(a, b)
    Path(sys.argv[3]).write_text(out, encoding="utf-8")
    print("overlay scene_state.py geschrieben")


if __name__ == "__main__":
    main()
