#!/usr/bin/env python3
"""Read-only AMASTER/SPS/IST inventory. Catalogues are not product tests.

The script always emits UNGEPRUEFT or TEILGESCHLOSSEN where only source exists,
never GRUEN. No product DB, UI or model is written or invoked.
"""
from __future__ import annotations
import argparse
import ast
import csv
import hashlib
import json
import re
from pathlib import Path

EXPECTED = {
    "AMASTER": "fb4f2015783dafe9474ee77d26b23fafb7c2c76a1c6ba923727f3aaedba5721d",
    "Matrix10": "1465980a0675a36b3143175c216048dae04d615c9e174d5821a8a2bb94917bc8",
}
# These are SOURCE-CANDIDATES found in V67, not tested or certified chains.
DOMAINS = [
 (1,7,["matrix_api/kernel.py","matrix_api/repos.py"],["src/routes/index.tsx"]),
 (8,8,["matrix_api/repos.py","matrix_api/isolation.py"],["src/routes/user.tsx"]),
 (9,12,["matrix_api/repos.py","matrix_api/analyze.py"],["src/routes/welt.index.tsx","src/routes/welt.$worldId.tsx"]),
 (13,17,["matrix_api/repos.py","matrix_api/kernel.py"],["src/routes/charakter.index.tsx","src/routes/charakter.$charId.tsx"]),
 (18,21,["matrix_api/repos.py","matrix_api/scene_state.py"],["src/routes/chat.index.tsx","src/routes/timeline.tsx"]),
 (22,28,["matrix_api/app.py","matrix_api/kernel.py","matrix_api/truth.py"],["src/routes/chat.$sessionId.tsx"]),
 (29,33,["matrix_api/analyze.py","matrix_api/vector.py","matrix_api/repos.py"],["src/routes/upload.tsx"]),
 (34,36,["matrix_api/repos.py","matrix_api/kernel.py","matrix_api/scene_state.py"],["src/routes/chat.$sessionId.tsx","src/routes/timeline.tsx"]),
 (37,37,["matrix_api/kernel.py","matrix_api/scene_state.py"],["src/routes/chat.$sessionId.tsx"]),
 (38,41,["matrix_api/conjunctive.py","matrix_api/kernel.py","matrix_api/repos.py"],["src/routes/memory.tsx"]),
 (42,43,["matrix_api/kernel.py","matrix_api/scene_state.py"],["src/routes/charakter.$charId.tsx"]),
 (44,45,["matrix_api/kernel.py","matrix_api/repos.py"],["src/routes/social.tsx"]),
 (46,46,["matrix_api/kernel.py","matrix_api/app.py","matrix_api/god_extract.py"],["src/routes/chat.$sessionId.tsx"]),
 (47,47,["matrix_api/kernel.py","matrix_api/system_loop.py"],["src/routes/fate.tsx"]),
 (48,48,["matrix_api/system_loop.py","matrix_api/pipeline.py"],["src/routes/chat.$sessionId.tsx"]),
 (49,49,["matrix_api/kernel.py","matrix_api/llm_contract.py"],["src/routes/chat.$sessionId.tsx"]),
 (50,50,["matrix_api/llm_contract.py","matrix_api/pipeline.py"],["src/routes/config.tsx"]),
 (51,51,["matrix_api/local_render.py","matrix_api/kernel.py"],["src/routes/chat.$sessionId.tsx"]),
 (52,52,["matrix_api/repos.py","matrix_api/analyze.py"],["src/routes/review.tsx"]),
 (53,53,["matrix_api/analyze.py","matrix_api/kernel.py"],["src/routes/charakter.$charId.tsx"]),
 (54,54,["matrix_api/app.py"],["src/router.tsx"]),
 (55,55,["matrix_api/app.py"],["src/routes/index.tsx"]),
 (56,56,["matrix_api/app.py","matrix_api/kernel.py"],["src/routes/chat.$sessionId.tsx"]),
 (57,57,["matrix_api/app.py","matrix_api/repos.py"],["src/routes/upload.tsx"]),
 (58,58,["matrix_api/kernel.py","matrix_api/repos.py"],["src/routes/memory.tsx"]),
 (59,59,["matrix_api/kernel.py","matrix_api/repos.py"],["src/routes/social.tsx"]),
 (60,60,["matrix_api/app.py","matrix_api/repos.py"],["src/routes/config.tsx"]),
 (61,61,["matrix_api/app.py"],["src/routes/__root.tsx"]),
 (62,62,["matrix_api/app.py","matrix_api/llm_contract.py"],["src/routes/chat.$sessionId.tsx"]),
 (63,63,["matrix_api/db.py","matrix_api/repos.py","matrix_api/schema.sql"],["src/routes/diagnose.tsx"]),
 (64,64,["matrix_api/repos.py","matrix_api/app.py"],["src/routes/admin.tsx","src/routes/diagnose.tsx"]),
 (65,65,["matrix_api/live_log.py","matrix_api/app.py"],["src/routes/diagnose.tsx","src/routes/logs.tsx"]),
 (66,66,["matrix_api/genre_policy.py","matrix_api/kernel.py"],["src/routes/config.tsx"]),
 (67,67,["matrix_api/upload_security.py","matrix_api/isolation.py"],["src/routes/admin.tsx"]),
 (68,70,["matrix_api/kernel.py","matrix_api/repos.py","matrix_api/app.py"],["src/router.tsx"]),
]
PARTIAL_RUST = {6,8,18,23,26,34,35,36,39,44,46,68}


def sha(p: Path): return hashlib.sha256(p.read_bytes()).hexdigest()

def parse_sections(s: str):
    sections=[]
    for number,title in re.findall(r"(?m)^(\d{1,2})\. ([^\n]+)$", s):
        n=int(number)
        if 1 <= n <= 70 and (not sections or n == sections[-1]["section"]+1):
            sections.append({"section":n,"title":title.strip()})
    assert [x["section"] for x in sections] == list(range(1,71)), f"AMASTER headings not complete: {len(sections)}"
    return sections

def parse_invariants(s: str):
    block = s[s.index("68. Kanonische Invarianten"):s.index("69. Verbindliche Produktabnahme")]
    rows=[{"invariant":int(n),"text":txt.strip()} for n,txt in re.findall(r"(?m)^(\d+)\. ([^\n]+)",block) if 1 <= int(n) <= 35]
    assert [r["invariant"] for r in rows] == list(range(1,36)),f"AMASTER invariants incomplete: {len(rows)}"
    return rows

def inspect_python(root:Path):
    modules=[]; functions=[]
    for file in sorted((root/"matrix_api").glob("*.py")):
        tree=ast.parse(file.read_text(encoding="utf-8"),filename=file.name)
        defs=[]
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                qual=node.name
                defs.append({"name":qual,"line":node.lineno,"end_line":node.end_lineno or node.lineno})
                functions.append({"file":str(file.relative_to(root)),"name":qual,"line":node.lineno,"end_line":node.end_lineno or node.lineno})
        modules.append({"file":str(file.relative_to(root)),"lines":len(file.read_text(encoding="utf-8").splitlines()),
                        "functions":len(defs),"sha256":sha(file)})
    return modules,functions

def endpoints(root:Path):
    source=(root/"matrix_api/app.py").read_text(encoding="utf-8")
    paths=re.findall(r'(?m)^\s*@app\.(get|post|put|delete|patch)\("([^"]+)"\)',source)
    src='\n'.join(p.read_text(encoding="utf-8",errors="replace") for p in (root/"src").rglob("*.ts*") if not p.name.endswith(".gen.ts"))
    out=[]
    for method,path in paths:
        # Presence of literal prefix in TS source is evidence of a reference only;
        # absence does not prove no UI because routes may be constructed dynamically.
        prefix=re.split(r'<[^>]+>',path)[0].rstrip('/')
        out.append({"method":method.upper(),"path":path,"frontend_literal_prefix_referenced":bool(prefix and prefix in src),
                    "frontend_operable":"UNGEPRUEFT", "http_e2e":"UNGEPRUEFT"})
    return out

def run(args):
    src=Path(args.v67).resolve(); out=Path(args.out).resolve(); out.mkdir(parents=True,exist_ok=True)
    amaster=Path(args.amaster).resolve(); matrix=Path(args.matrix).resolve()
    actual={"AMASTER":sha(amaster),"Matrix10":sha(matrix)}
    assert actual == EXPECTED, f"Normative hashes mismatch, refuse catalog: {actual}"
    sections=parse_sections(amaster.read_text(encoding="utf-8"))
    invariant=parse_invariants(amaster.read_text(encoding="utf-8"))
    modules,functions=inspect_python(src)
    api=endpoints(src)
    for row in sections:
        n=row["section"]
        found=[(m,u) for a,b,m,u in DOMAINS if a<=n<=b]
        assert len(found)==1, (n,found)
        mods,ui=found[0]
        assert all((src/p).is_file() for p in mods+ui), (n, mods,ui)
        row.update({"candidate_python_owners":mods,"candidate_visible_routes":ui,
                    "rust_source_state":"TEILQUELLE_UNKOMPILIERT" if n in PARTIAL_RUST else "NICHT_PORTIERT",
                    "chain_status":"UNGEPRUEFT", "actual_frontend_to_folgeturn_evidence":False,
                    "note":"Nur Quellkandidaten, keine Wirkungs-/Bedienbarkeitsabnahme."})
    for i in invariant:
        i.update({"source_section":68,"chain_status":"UNGEPRUEFT","end_to_end_evidence":False})
    raw_v12=Path(args.v12).resolve()
    v12=json.loads(raw_v12.read_text(encoding="utf-8"))
    axes=[{"axis":x, "stand":"UNGEPRUEFT", "evidence":"V12-Katalog vorhanden, am V67-Rust-Kandidaten NICHT ausgefuehrt"}
          for x in v12["pflichtachsen"]]
    result={"type":"STATIC_AMASTER_SPS_RUST_DEPENDENCY_CATALOG_NOT_A_CONFORMANCE_REPORT",
            "authority":{"hashes":actual,"v67_root":src.name,"sps_sha256":sha(src/"MATRIX10_SPS_MASTER.md")},
            "summary":{"amaster_sections":len(sections),"canonical_invariants":len(invariant),
                       "v12_axes":len(axes),"original_python_modules":len(modules),
                       "original_function_definitions":len(functions),"http_method_routes":len(api),
                       "frontend_route_files":len(list((src/"src/routes").glob("*.tsx"))),
                       "rust_modules_partially_referenced_sections":len(PARTIAL_RUST),
                       "product_release_eligible":False,"rust_compilation_executed":False},
            "sections":sections,"canonical_invariants":invariant,"v12_axes":axes,
            "python_modules":modules,"python_functions":functions,"http_routes":api}
    (out/"AMASTER_CODE_MAP_03.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (out/"AMASTER_CODE_MAP_03.csv").open("w",encoding="utf-8",newline="") as f:
        writer=csv.writer(f,delimiter=';');writer.writerow(["AMASTER Abschnitt","Inhalt","Rustquelle","Python-Kandidaten","Frontend-Kandidaten","E2E-Stand"])
        for r in sections:writer.writerow([r["section"],r["title"],r["rust_source_state"],
                                           ', '.join(r["candidate_python_owners"]),
                                           ', '.join(r["candidate_visible_routes"]),r["chain_status"]])
    lines=["# AMASTER → IST → Rust: vollständiges Abschnittsregister (statisch)","",
           "**Kein Grün-Nachweis.** Die Zuordnung enthält Quellkandidaten, nicht ausgeführte End-to-End-Ketten.",
           "Normative AMASTER und Matrix10 stimmen mit Kettenvertrag §0 überein; die vorhandene V67 ist IST, nicht SOLL.","",
           f"- **70** AMASTER-Abschnitte inventarisiert, **{len(invariant)}** explizite Invarianten aus AMASTER §68",
           f"- **{len(modules)}** Python-Module / **{len(functions)}** Python-Funktionsdefinitionen (AST, inklusive geschachtelter)",
           f"- **{len(api)}** deklarierte HTTP-Methodenrouten / **{result['summary']['frontend_route_files']}** vorhandene UI-Routendateien",
           f"- **{len(axes)}** Achsen im V12-Pflichtkatalog, für dieses Produkt alle ungeprüft","",
           "## Wichtigste nicht portierte Gesamtketten", "",
           "TurnOrchestrierung (§28, 23 Schritte), semantische Komponentenwirkung (§34), Gedächtnis/Witness (§38–41),",
           "Runtime/Physical/Relationship (§42–45), God/Regie/Fate/AutoChat (§46–48), BrainContext/LLM (§49–51),",
           "SQLite-Owner mit Writer/Reader (§63), Snapshot/Import und vollständige API-/UI-Bedienbarkeit (§54–65).","",
           "## Systematische Zuordnung", "",
           "| AMASTER | Abschnitt | Python-IST-Kandidaten | Oberfläche-Kandidaten | Rust |", "|---:|---|---|---|---|" ]
    for r in sections:
        lines.append(f"| {r['section']} | {r['title']} | {', '.join(r['candidate_python_owners'])} | {', '.join(r['candidate_visible_routes'])} | {r['rust_source_state']} |")
    lines.extend(["", "## Freigaberegel", "", "Für alle 70 Abschnitte und alle 35 Invarianten fehlen die vollständigen Nachweise nach Kettenvertrag §16.",
                  "Bisherige Rust-Teilquelle, Python-Oracle, alte Tests, REST-Route oder UI-Datei zählen nicht als geschlossene Kette.",
                  "Native Kompilierung, Frontend-Anbindung, SQLite-Rücklesen, Folgeturn, Neustart, Isolation und V12-Produktabnahme",
                  "sind für eine Freigabe zwingend nachzuholen. Vorher **ROT / BLOCKIERT**.", ""])
    (out/"AMASTER_CODE_MAP_03.md").write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(result['summary'],ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--v67',required=True);p.add_argument('--amaster',required=True)
    p.add_argument('--matrix',required=True);p.add_argument('--v12',required=True);p.add_argument('--out',required=True)
    run(p.parse_args())
