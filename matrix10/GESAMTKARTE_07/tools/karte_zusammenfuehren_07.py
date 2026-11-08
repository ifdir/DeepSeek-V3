#!/usr/bin/env python3
"""Gesamtkarte 07: fuehrt die fuenf Bereichskarten (W, T, Z, A, P) zu EINER Karte zusammen.

Eingabe: karte/{W,T,Z,A,P}.json (je Funktion: amaster, soll, sps_loesung, owner, kette{eingang..frontend},
ui_bedienung, statischer_befund, status, defekte, abhaengig_von, belege). Keine Bewertung wird hier veraendert.
Ausgabe: KARTE_GESAMT_07.json (alle Funktionen + Zaehlung) und KARTE_GESAMT_07.md (Tabelle).
Aufruf: python3 -I karte_zusammenfuehren_07.py
"""
import collections
import json
from pathlib import Path

HIER = Path(__file__).resolve().parents[1]
BEREICHE = {"W": "Welt, Userprofil, Charakterstamm (§7–§17, KV §7–§8)",
            "T": "Session, Szene, Turn, TurnTruth, Orchestrierung (§18–§28, KV §9)",
            "Z": "Fakten, Lifecycle, Memory, Witness, Runtime, Beziehung (§34–§45, KV §10–§11)",
            "A": "God, Regie, Fate, AutoChat, BrainContext, LLM, Review (§46–§53, KV §12)",
            "P": "Upload, Suche, Oberfläche, Config, Persistenz, Diagnose (§29–§33, §54–§67, KV §5, §13–§15)"}


def kurz(x, n=160):
    s = " ".join(str(x or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def main():
    alle, matrix = [], None
    for b in BEREICHE:
        for x in json.loads((HIER / "karte" / f"{b}.json").read_text(encoding="utf-8")):
            if x.get("id") == "P-MATRIX":
                matrix = x
                continue
            x["bereich"] = b
            alle.append(x)
    zahl = {b: dict(collections.Counter(x["status"] for x in alle if x["bereich"] == b)) for b in BEREICHE}
    gesamt = dict(collections.Counter(x["status"] for x in alle))
    statisch = dict(collections.Counter(x.get("statischer_befund") for x in alle))
    (HIER / "KARTE_GESAMT_07.json").write_text(json.dumps(
        {"funktionen": len(alle), "status_gesamt": gesamt, "status_je_bereich": zahl, "statischer_befund": statisch,
         "gruen": gesamt.get("GRÜN", 0), "frontend_backend_matrix": matrix, "eintraege": alle},
        indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    z = ["# KARTE_GESAMT_07 – alle kartierten AMASTER-Funktionen (generiert, nicht von Hand ändern)", "",
         f"Funktionen: **{len(alle)}** · Status: " + ", ".join(f"{k} {v}" for k, v in sorted(gesamt.items())) +
         " · GRÜN: 0 (keine Live-Abnahme)", "",
         "Statischer Codefluss: " + ", ".join(f"{k} {v}" for k, v in sorted(statisch.items(), key=lambda t: str(t[0]))), ""]
    for b, titel in BEREICHE.items():
        z += [f"## {b} – {titel}", "", "Status: " + ", ".join(f"{k} {v}" for k, v in sorted(zahl[b].items())), "",
              "| ID | AMASTER | Funktion | Owner (IST) | Status | Codefluss | Erster Defekt | abhängig von |",
              "|---|---|---|---|---|---|---|---|"]
        for x in alle:
            if x["bereich"] != b:
                continue
            d = (x.get("defekte") or ["–"])[0]
            ab = ", ".join(map(str, x.get("abhaengig_von") or [])) or "–"
            z.append("| " + " | ".join(kurz(v, n).replace("|", "/") for v, n in (
                (x["id"], 12), (x.get("amaster"), 26), (x.get("funktion"), 60), (x.get("owner"), 60), (x.get("status"), 16),
                (x.get("statischer_befund"), 26), (d, 170), (ab, 80))) + " |")
        z.append("")
    if matrix:
        r = matrix.get("routen") or []
        z += ["## Frontend-Backend-Matrix (P-MATRIX, KV §5)", "", f"Routen erfasst: {len(r)} · Zählung: {json.dumps(matrix.get('zaehlung'), ensure_ascii=False)}", "",
              "| Methode | Route | Backend | Aufruf im Frontend | Sichtbare Kontrolle | Zuordnung |", "|---|---|---|---|---|---|"]
        for x in r:
            z.append("| " + " | ".join(kurz(x.get(k), n).replace("|", "/") for k, n in (
                ("methode", 8), ("route", 60), ("backend", 34), ("aufruf", 90), ("sichtbare_kontrolle", 90), ("zuordnung", 34))) + " |")
        z += ["", "### Frontendfelder ohne (richtige) Backendwirkung", ""]
        for f in matrix.get("frontendfelder_ohne_backendwirkung") or []:
            z.append("- " + kurz(json.dumps(f, ensure_ascii=False) if isinstance(f, dict) else f, 300))
        z.append("")
    (HIER / "KARTE_GESAMT_07.md").write_text("\n".join(z) + "\n", encoding="utf-8")
    print(len(alle), gesamt)


if __name__ == "__main__":
    main()
