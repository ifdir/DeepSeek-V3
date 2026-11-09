#!/usr/bin/env python3
"""K2a: Inventar der Stellen, an denen P25 eine Ausnahme faengt und WEITERLAEUFT, und die den
Rust-Einwilligungskern erreichen koennen. Statisch (AST), danach mit Laufzeitstapeln abzugleichen.

Ein Handler gilt als "verschluckend", wenn er die Ausnahme nicht weitergibt (kein raise im
Handler) und Exception/BaseException/ohne Typ oder NativeBoundaryError faengt. Typ-spezifische
Handler (WriterError, KeyError, ...) fangen NativeBoundaryError nicht und zaehlen nicht.

"Erreicht den Kern" = der try-Block ruft (direkt oder ueber den namensbasierten Aufrufgraphen
der Module app/kernel/pipeline/scene_state/repos/conjunctive) eine der Wurzeln auf.
Namensbasiert = Ueberabschaetzung, nie Unterschaetzung fuer Funktionen dieser Module.

Aufruf: python3 -I inventar_swallow_06.py <Stage-Produktordner> <ausgabe.json>
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

MODULE = ("app", "kernel", "pipeline", "scene_state", "repos", "conjunctive")
WURZELN = {"_native_request", "_load", "reduce_body_contact_standing", "reduce_restricted_refusals",
           "reduce_restricted_permissions", "restriction_match"}
BREIT = {"Exception", "BaseException", "NativeBoundaryError"}


def called_names(node):
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def main():
    root = Path(sys.argv[1]) / "matrix_api"
    trees = {m: ast.parse((root / f"{m}.py").read_text(encoding="utf-8")) for m in MODULE}
    trees["native_boundary"] = ast.parse((root / "native_boundary.py").read_text(encoding="utf-8"))
    # Aufrufgraph: Funktionsname -> aufgerufene Namen (alle verschachtelten defs eingeschlossen)
    graph: dict[str, set] = {}
    for m, t in trees.items():
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                graph.setdefault(n.name, set()).update(called_names(n))
    reach = set(WURZELN)
    changed = True
    while changed:
        changed = False
        for fn, calls in graph.items():
            if fn not in reach and calls & reach:
                reach.add(fn)
                changed = True
    funde = []
    for m in MODULE:
        t = trees[m]
        parents = {}
        for n in ast.walk(t):
            for c in ast.iter_child_nodes(n):
                parents[c] = n
        for n in ast.walk(t):
            if not isinstance(n, ast.Try):
                continue
            body_calls = set().union(*(called_names(b) for b in n.body)) if n.body else set()
            hits = sorted(body_calls & reach)
            if not hits:
                continue
            for h in n.handlers:
                typ = h.type
                names = set()
                if typ is None:
                    names = {"<alle>"}
                elif isinstance(typ, ast.Name):
                    names = {typ.id}
                elif isinstance(typ, ast.Tuple):
                    names = {e.id for e in typ.elts if isinstance(e, ast.Name)}
                elif isinstance(typ, ast.Attribute):
                    names = {typ.attr}
                if not (names & BREIT or "<alle>" in names):
                    continue
                hm = ast.Module(body=h.body, type_ignores=[])
                reraise = any(isinstance(x, ast.Raise) for x in ast.walk(hm))
                # "endet mit Antwort" nur, wenn das return eine HTTP-Fehlerantwort baut (return None = Weiterlaufen beim Aufrufer)
                antwortet = any(isinstance(x, ast.Return) and x.value is not None
                                and called_names(x.value) & {"_json_error", "jsonify"} for x in ast.walk(hm))
                art = "gibt_weiter" if reraise else ("endet_mit_antwort" if antwortet else "laeuft_weiter")
                # umgebende Funktion
                p, fn = n, None
                while p in parents:
                    p = parents[p]
                    if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        fn = p.name
                        break
                funde.append({"datei": f"matrix_api/{m}.py", "try_zeile": n.lineno, "try_ende": n.end_lineno,
                              "handler_zeile": h.lineno, "faengt": sorted(names), "art": art,
                              "funktion": fn, "erreicht_ueber": hits[:8]})
    verschluckend = [f for f in funde if f["art"] == "laeuft_weiter"]
    report = {"wurzeln": sorted(WURZELN), "funktionen_die_den_kern_erreichen": len(reach),
              "breite_handler_um_kernpfade": len(funde), "laeuft_weiter": verschluckend,
              "endet_mit_antwort": [f for f in funde if f["art"] == "endet_mit_antwort"],
              "gibt_weiter": [f for f in funde if f["art"] == "gibt_weiter"]}
    Path(sys.argv[2]).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Funktionen mit Kernpfad: {len(reach)}; breite Handler um Kernpfade: {len(funde)}; laeuft weiter: {len(verschluckend)}; "
          f"endet mit Antwort: {len(report['endet_mit_antwort'])}; gibt weiter: {len(report['gibt_weiter'])}")
    for f in verschluckend:
        print(f"  {f['datei']}:{f['handler_zeile']} in {f['funktion']} faengt {f['faengt']} | try {f['try_zeile']}-{f['try_ende']} | {', '.join(f['erreicht_ueber'][:4])}")


if __name__ == "__main__":
    main()
