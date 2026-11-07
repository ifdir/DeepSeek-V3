#!/usr/bin/env python3
"""Selbstabnahme der Prüfmaschine V1.2 – erst danach darf sie Produkte prüfen.

Die Maschine wird gegen sich selbst geprüft, mit positiven und negativen Fällen:
  A  Gegenproben an der reinen Entscheidungslogik (pm_auswertung), u. a. alle sechs Befunde der
     unabhängigen Negativprüfung vom 07.11.2026 (leere Glieder, Teilachsen, entfernte rote Fälle, ...).
  B  Echte Kettenläufe: P25 vollständig, P24 und P23 - jeder Kandidat muss an seinen BEKANNTEN Fehlern
     erkannt werden (muss_rot), richtige Vergleichsfälle müssen bestehen (muss_gruen).
  C  Mutationen M1-M9 im Produkt (je genau eine Stelle): JEDER vorab festgelegte (Fall, Glied)-Punkt muss
     unverändert genau GRÜN und mutiert genau ROT sein; nicht ausgeführt / Abbruch / Modell-Fehlgriff vor
     dem Hauptcommit = nicht erkannt.
  D  Gegenproben an den ECHTEN Ergebnissen aus B: roten Fall entfernen, Glied entfernen/verdoppeln,
     unerlaubtes NICHT_ZUTREFFEND, Abbruch mit Teilresultat, falscher Rückgabecode/'gesamt', falscher
     ZIP-/Katalog-Hash, falscher Sprecher-/Sitzungs-PROMPT im Wissensnachweis. Jede muss die Freigabe verhindern.
  E  Echter Abbruch: Port des Produkts belegt -> Kettenprüfer muss BLOCKIERT melden, Freigabe darf nicht GRÜN werden.
  F  Unabhängigkeit: Manifest erkennt geänderte, fehlende und hinzugekommene Maschinendateien.
Nur wenn ALLES besteht, wird ABNAHME_V12.json geschrieben (Hashes aller Maschinendateien).
Exitcodes: 0 abgenommen, 2 nicht abgenommen (Fehlerkennung mangelhaft), 3 BLOCKIERT (Umgebung).
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "kettenpruefer"))
import pm_auswertung as pa  # noqa: E402
import kp_mutationen  # noqa: E402

KP = BASE / "kettenpruefer" / "kettenpruefer.py"
SOLL = json.loads((BASE / "kettenpruefer" / "kp_selbstabnahme_soll.json").read_text(encoding="utf-8"))
KATALOG_PFAD = BASE / "kettenpruefer" / "kp_faelle.json"
KATALOG = json.loads(KATALOG_PFAD.read_text(encoding="utf-8"))
REGELN = json.loads((BASE / "PRUEFREGELN_V12.json").read_text(encoding="utf-8"))
ERG: list = []   # (Bereich, Name, ok, Beleg)


def probe(bereich: str, name: str, ok: bool, beleg: str = ""):
    ERG.append({"bereich": bereich, "name": name, "ok": bool(ok), "beleg": beleg})
    print("[%s] %s %s: %s" % ("OK " if ok else "FEHLT", bereich, name, beleg[:220]), flush=True)


def glied(erg: dict, fall: str, nr: int):
    fe = next((f for f in erg.get("faelle") or [] if f.get("id") == fall), None)
    if not fe:
        return "FEHLT", "Fall nicht gelaufen (%s)" % (erg.get("abbruch") or erg.get("kandidat_rot")), {}
    x = next((g for g in fe["glieder"] if g["glied"] == nr), {"status": "FEHLT", "beleg": ""})
    return x["status"], x["beleg"], fe.get("modell") or {}


def kettenlauf(ns, zip_pfad: str, aufnahme: str | None, faelle: list[str], aus: Path, mutation: str = "") -> tuple[int, dict]:
    auf = Path(aufnahme) if aufnahme else Path(tempfile.mkdtemp(prefix="leere_aufnahme_"))
    cmd = [sys.executable, "-I", str(KP), "--kandidat", zip_pfad, "--db", ns.db, "--ausgabe", str(aus), "--modus", "wiedergabe",
           "--aufnahme", str(auf if auf.is_absolute() else BASE / auf), "--faelle", ",".join(faelle), "--playwright", ns.playwright]
    if ns.node_cache:
        cmd += ["--node-cache", ns.node_cache]
    if mutation:
        cmd += ["--mutation", mutation]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=5400)
    (aus.parent / (aus.name + ".konsole.txt")).write_text(r.stdout + r.stderr, encoding="utf-8")
    erg = json.loads((aus / "ERGEBNIS.json").read_text(encoding="utf-8")) if (aus / "ERGEBNIS.json").is_file() else {}
    return r.returncode, erg


def regeln_mit(faelle: list[str]) -> dict:
    """Prüfregeln, in denen nur die gelaufenen Fälle Pflicht sind (für Teilläufe von P24/P23)."""
    r = copy.deepcopy(REGELN)
    for a in r["pflichtachsen"]:
        r["pflichtfaelle"][a] = [f for f in r["pflichtfaelle"].get(a) or [] if f in faelle]
    return r


# ---------------------------------------------------------------- A: reine Logik
def teil_a():
    probe("A", "Befund 1: leere Gliederliste ist nie GRÜN", pa.fall_status([], [])[0] == "BLOCKIERT", str(pa.fall_status([], [])))
    probe("A", "Befund 1: ein einziges grünes Glied ist nie GRÜN", pa.fall_status([{"glied": 1, "status": "GRUEN"}], [])[0] == "BLOCKIERT")
    voll = [{"glied": n, "status": "GRUEN"} for n in range(1, 21)]
    probe("A", "20 grüne Glieder ergeben GRÜN (GRÜN erreichbar)", pa.fall_status(voll, [])[0] == "GRUEN")
    dop = voll[:-1] + [{"glied": 9, "status": "GRUEN"}]
    probe("A", "doppeltes Glied statt Glied 20 blockiert", pa.fall_status(dop, [])[0] == "BLOCKIERT")
    na = copy.deepcopy(voll)
    na[12]["status"] = "NICHT_ZUTREFFEND"
    probe("A", "NICHT_ZUTREFFEND ohne Katalogerlaubnis blockiert", pa.fall_status(na, [])[0] == "BLOCKIERT")
    probe("A", "NICHT_ZUTREFFEND mit Katalogerlaubnis zulässig", pa.fall_status(na, ["13"])[0] == "GRUEN")
    probe("A", "erlaubtes NICHT_ZUTREFFEND, aber bewertet, blockiert", pa.fall_status(voll, ["13"])[0] == "BLOCKIERT")
    rot = copy.deepcopy(voll)
    rot[3]["status"] = "ROT"
    probe("A", "ein rotes Glied macht den Fall ROT", pa.fall_status(rot, [])[0] == "ROT")
    probe("A", "unbekannter Gliedstatus blockiert", pa.fall_status([dict(x, status="UNGEPRUEFT") if x["glied"] == 5 else x for x in voll], [])[0] == "BLOCKIERT")
    probe("A", "Lauf ohne Fälle ist BLOCKIERT", pa.lauf_gesamt([], None, None) == "BLOCKIERT")
    probe("A", "Abbruch mit grünen Teilfällen ist BLOCKIERT", pa.lauf_gesamt(["GRUEN"], None, "x") == "BLOCKIERT")
    # Befund 2: Teilachsen
    c1 = [{"id": "x", "status": "PASS"}]
    probe("A", "Befund 2: eine PASS-Prüfung + eine grüne Achse ist nicht GRÜN",
          pa.entscheidung(c1, {"Puppet (§12.2)": "GRUEN"}, REGELN)[0] == "BLOCKIERT", str(pa.entscheidung(c1, {"Puppet (§12.2)": "GRUEN"}, REGELN)))
    # GRÜN erreichbar: alles Pflichtige PASS, alle Achsen GRÜN
    alle = [{"id": i, "status": "PASS"} for i in pa.pflicht_checks(REGELN)]
    gruen = {a: "GRUEN" for a in REGELN["pflichtachsen"]}
    probe("A", "GRÜN erreichbar, wenn wirklich alles nachgewiesen ist", pa.entscheidung(alle, gruen, REGELN)[0] == "GRUEN")
    probe("A", "eine fehlende Pflichtprüfung blockiert", pa.entscheidung(alle[1:], gruen, REGELN)[0] == "BLOCKIERT")
    probe("A", "eine doppelte Pflichtprüfung blockiert", pa.entscheidung(alle + alle[:1], gruen, REGELN)[0] == "BLOCKIERT")
    probe("A", "eine fehlende Achse blockiert", pa.entscheidung(alle, dict(list(gruen.items())[1:]), REGELN)[0] == "BLOCKIERT")
    probe("A", "eine UNGEPRÜFTE Achse blockiert", pa.entscheidung(alle, {**gruen, "Fate (§12.5)": "UNGEPRUEFT"}, REGELN)[0] == "BLOCKIERT")
    probe("A", "eine ROT-Prüfung macht ROT", pa.entscheidung([dict(c, status="ROT") if c["id"] == "01_zip" else c for c in alle], gruen, REGELN)[0] == "ROT")
    probe("A", "eine rote Achse macht ROT", pa.entscheidung(alle, {**gruen, "God (§12.4)": "ROT"}, REGELN)[0] == "ROT")
    probe("A", "eine BLOCKIERT-Prüfung macht nicht GRÜN", pa.entscheidung([dict(c, status="BLOCKIERT") if c["id"] == "01_zip" else c for c in alle], gruen, REGELN)[0] == "BLOCKIERT")
    probe("A", "kein Ergebnis -> Kette BLOCKIERT, keine Achse GRÜN", (lambda r: all(s != "GRUEN" for s in r[1].values())
          and any(c["id"] == "07_kettenpruefer_lauf" and c["status"] == "BLOCKIERT" for c in r[0]))(pa.kette_auswerten(None, 3, KATALOG, REGELN, "x", "y")))


# ---------------------------------------------------------------- B: Unterscheidung P23/P24/P25
def fingerabdruck(name: str, rc: int, erg: dict) -> None:
    s = SOLL["kandidaten"][name]
    if s.get("kandidat_rot"):
        probe("B", "%s: Kandidat als ROT erkannt (bekannter Fehler)" % name,
              rc == 2 and erg.get("gesamt") == "ROT" and bool(erg.get("kandidat_rot")), "rc %s, gesamt %s, %s" % (rc, erg.get("gesamt"), erg.get("kandidat_rot")))
        return
    probe("B", "%s: Lauf vollständig, Rückgabecode passt" % name, not erg.get("abbruch") and pa.RC_STATUS.get(rc) == erg.get("gesamt"),
          "rc %s, gesamt %s, abbruch %s" % (rc, erg.get("gesamt"), erg.get("abbruch")))
    for fall, nr in s["muss_rot"]:
        st, beleg, _ = glied(erg, fall, nr)
        probe("B", "%s: bekannter Fehler %s Glied %02d ROT" % (name, fall, nr), st == "ROT", beleg)
    for fall in s["muss_gruen"]:
        fe = next((f for f in erg.get("faelle") or [] if f["id"] == fall), {})
        rote = [(g["glied"], g["status"], g["beleg"][:120]) for g in fe.get("glieder") or [] if g["status"] in ("ROT", "BLOCKIERT") and g["glied"] != 20]
        probe("B", "%s: Vergleichsfall %s GRÜN" % (name, fall), fe.get("status") == "GRUEN", str(rote[:3]) or "alle 20 Glieder grün")


# ---------------------------------------------------------------- C: Mutationen
def teil_c(ns, basis: dict, aus: Path):
    for name, m in kp_mutationen.MUTATIONEN.items():
        faelle = sorted({f for f, _ in m["erwartet"]})
        rc, erg = kettenlauf(ns, ns.p25, SOLL["kandidaten"]["P25"]["aufnahme"], faelle, aus / name, name)
        ausgefuehrt = str((erg.get("vorbereitung") or {}).get("mutation", "")).startswith("angewendet")
        probe("C", "%s ausgeführt, Lauf ohne Abbruch" % name, ausgefuehrt and not erg.get("abbruch"),
              "%s | %s" % ((erg.get("vorbereitung") or {}).get("mutation"), erg.get("abbruch")))
        for fall, nr in m["erwartet"]:
            s0, _, _ = glied(basis, fall, nr)
            s1, beleg, modell = glied(erg, fall, nr)
            fehl = int(modell.get("fehlgriffe_vor_hauptcommit") or 0) if modell else 0
            probe("C", "%s: %s Glied %02d unverändert GRÜN -> mutiert ROT" % (name, fall, nr),
                  ausgefuehrt and s0 == "GRUEN" and s1 == "ROT" and fehl == 0,
                  "unverändert %s, mutiert %s, Modell-Fehlgriffe vor Hauptcommit %d | %s" % (s0, s1, fehl, beleg[:160]))


# ---------------------------------------------------------------- D: Gegenproben an echten Ergebnissen
def teil_d(r25: tuple, aus25: Path):
    rc, erg = r25
    kz, ksha = erg["basis"]["zip_sha"], pa.sha(KATALOG_PFAD)

    def ausw(e, r=rc, z=kz, k=ksha):
        return pa.kette_auswerten(e, r, KATALOG, REGELN, z, k)

    checks, achsen = ausw(copy.deepcopy(erg))
    lauf = next(c for c in checks if c["id"] == "07_kettenpruefer_lauf")
    probe("D", "echtes P25-Ergebnis wird als echt und vollständig übernommen", lauf["status"] == "PASS", lauf["detail"])
    probe("D", "echtes P25-Ergebnis: Puppet/God/Regie ROT, Avatar GRÜN, Rest UNGEPRÜFT",
          achsen.get("Puppet (§12.2)") == "ROT" and achsen.get("God (§12.4)") == "ROT" and achsen.get("Regie (§12.3)") == "ROT"
          and achsen.get("Avatar (§12.1)") == "GRUEN" and list(achsen.values()).count("UNGEPRUEFT") == 12, str(achsen))

    def nie_gruen(name, e, r=rc, z=kz, k=ksha, achse=None, check=None, erwartet=None):
        c, a = ausw(e, r, z, k)
        st = {x["id"]: x["status"] for x in c}
        ok = True
        if achse:
            ok = ok and a.get(achse) != "GRUEN"
        if check:
            ok = ok and st.get(check) == (erwartet or "BLOCKIERT")
        ok = ok and pa.entscheidung(c, a, REGELN)[0] != "GRUEN"
        probe("D", name, ok, "Achse %s=%s, %s=%s" % (achse, a.get(achse), check, st.get(check)))

    for fall, achse in (("PU2_anrede_gegen_ui_auswahl", "Puppet (§12.2)"), ("GO1_bewusstlos", "God (§12.4)"), ("RE1_figur_verlaesst_raum", "Regie (§12.3)")):
        e = copy.deepcopy(erg)
        e["faelle"] = [f for f in e["faelle"] if f["id"] != fall]
        e["gesamt"] = pa.lauf_gesamt([f["status"] for f in e["faelle"]], None, None)
        r = {v: k for k, v in pa.RC_STATUS.items()}[e["gesamt"]]
        nie_gruen("Befund 3: roter Fall %s entfernt -> Achse nicht GRÜN, Fall fehlt" % fall, e, r, achse=achse, check="07_kette_" + fall)
    e = copy.deepcopy(erg)
    fe = next(f for f in e["faelle"] if f["id"] == "PU1_handlung_eigenes_subjekt")
    fe["glieder"] = [g for g in fe["glieder"] if g["glied"] != 13]
    nie_gruen("Pflichtglied 13 entfernt -> Fall BLOCKIERT", e, achse="Puppet (§12.2)", check="07_kette_PU1_handlung_eigenes_subjekt")
    e = copy.deepcopy(erg)
    fe = next(f for f in e["faelle"] if f["id"] == "AV1_frage_und_antwort")
    fe["glieder"] = [g for g in fe["glieder"] if g["glied"] != 10] + [dict(next(g for g in fe["glieder"] if g["glied"] == 9))]
    nie_gruen("Glied 10 durch doppeltes Glied 9 ersetzt -> BLOCKIERT", e, achse="Avatar (§12.1)", check="07_kette_AV1_frage_und_antwort")
    e = copy.deepcopy(erg)
    fe = next(f for f in e["faelle"] if f["id"] == "AV1_frage_und_antwort")
    next(g for g in fe["glieder"] if g["glied"] == 13)["status"] = "NICHT_ZUTREFFEND"
    nie_gruen("Glied 13 unerlaubt NICHT_ZUTREFFEND -> BLOCKIERT", e, achse="Avatar (§12.1)", check="07_kette_AV1_frage_und_antwort")
    e = copy.deepcopy(erg)
    fe = next(f for f in e["faelle"] if f["id"] == "PU2_anrede_gegen_ui_auswahl")
    fe["status"] = "GRUEN"
    next(g for g in fe["glieder"] if g["glied"] == 20)["status"] = "GRUEN"
    nie_gruen("roter Fall als GRÜN gemeldet (Glieder rot) -> nicht übernommen", e, achse="Puppet (§12.2)", check="07_kette_PU2_anrede_gegen_ui_auswahl")
    e = copy.deepcopy(erg)
    e["faelle"] = e["faelle"][:3]
    e["abbruch"] = "RuntimeError: künstlicher Abbruch"
    e["gesamt"] = "BLOCKIERT"
    nie_gruen("Abbruch mit Teilresultat -> Lauf BLOCKIERT", e, 3, check="07_kettenpruefer_lauf")
    e = copy.deepcopy(erg)
    e["gesamt"] = "GRUEN"
    nie_gruen("gesamt=GRÜN bei roten Fällen, Rückgabecode 0 -> BLOCKIERT", e, 0, check="07_kettenpruefer_lauf")
    nie_gruen("Rückgabecode 0 zu gesamt=ROT -> BLOCKIERT", copy.deepcopy(erg), 0, check="07_kettenpruefer_lauf")
    nie_gruen("fremdes ZIP (Hash) -> BLOCKIERT", copy.deepcopy(erg), z="0" * 64, check="07_kettenpruefer_lauf")
    e = copy.deepcopy(erg)
    e["basis"]["faelle_sha"] = "0" * 64
    nie_gruen("falscher Katalog-Hash im Ergebnis -> BLOCKIERT", e, check="07_kettenpruefer_lauf")
    e = copy.deepcopy(erg)
    e["basis"].pop("faelle_sha", None)
    nie_gruen("fehlender Katalog-Hash im Ergebnis -> BLOCKIERT", e, check="07_kettenpruefer_lauf")
    nie_gruen("Katalog der Maschine verändert (Hash) -> BLOCKIERT", copy.deepcopy(erg), k="1" * 64, check="07_kettenpruefer_lauf")
    e = copy.deepcopy(erg)
    e["faelle"].append(dict(copy.deepcopy(e["faelle"][0]), id="XX_unbekannt"))
    nie_gruen("unbekannter zusätzlicher Fall -> BLOCKIERT", e, check="07_kettenpruefer_lauf")
    e = copy.deepcopy(erg)
    next(f for f in e["faelle"] if f["id"] == "AV1_frage_und_antwort")["achse"] = "Puppet (§12.2)"
    nie_gruen("Fall unter falscher Achse gemeldet -> BLOCKIERT", e, achse="Avatar (§12.1)", check="07_kette_AV1_frage_und_antwort")
    # Wissensnachweis (Befund 4) an den echten Eingaben von PU1
    w = json.loads((aus25 / "wissen_PU1_handlung_eigenes_subjekt.json").read_text(encoding="utf-8"))
    s0, b0 = pa.wissen_im_folgezug(w)
    probe("D", "Wissensnachweis PU1 echt: GRÜN", s0 == "GRUEN", b0)
    sprecher = str(w["folge_turns"][0]["speakerId"])
    andere = next(n for k, n in w["namen"].items() if k != sprecher and n and k in {str(x) for f in w["haupt_facts"] for x in f.get("witnessedBy") or []})

    def wv(name, fn):
        v = copy.deepcopy(w)
        fn(v)
        s, b = pa.wissen_im_folgezug(v)
        probe("D", "Befund 4: " + name + " -> ROT", s == "ROT", b)

    def falscher_sprecher(v):
        for z in v["logz"]:
            if z["stage"] == "PROMPT" and z.get("speaker") == v["namen"][sprecher]:
                z["speaker"] = andere
    wv("PROMPT gehört einer anderen Figur", falscher_sprecher)

    def andere_spur(v):
        for z in v["logz"]:
            if z["stage"] == "PROMPT":
                z["trace_id"] = "fremde_spur"
    wv("PROMPT aus anderer Spur als der Folgezug-Writer", andere_spur)

    def andere_sitzung(v):
        for z in v["logz"]:
            if z["stage"] == "KERNEL_BIND":
                z["resolved_session_id"] = "andere_sitzung"
    wv("Spur bindet eine andere Sitzung", andere_sitzung)

    def ohne_text(v):
        t = v["haupt_facts"][0]["text"]
        for z in v["logz"]:
            if z["stage"] == "PROMPT":
                z["sections"] = json.loads(json.dumps(z["sections"], ensure_ascii=False).replace(t, "…").replace(t.lower(), "…"))
    wv("PROMPT ohne das Ereignis", ohne_text)

    def kein_zeugenwissen(v):
        v["wk_nachher"] = [x for x in v["wk_nachher"] if x["character_id"] != sprecher]
    wv("Folgezug-Figur ohne kanonisches Zeugenwissen", kein_zeugenwissen)

    def kein_zeuge(v):
        for f in v["haupt_facts"]:
            f["witnessedBy"] = [x for x in f.get("witnessedBy") or [] if str(x) != sprecher]
    wv("Folgezug-Figur nicht Zeuge", kein_zeuge)

    def prompt_vorher(v):
        for z in v["logz"]:
            if z["stage"] == "PROMPT":
                z["ts"] = "2000-01-01T00:00:00+00:00"
    wv("PROMPT vor dem Hauptcommit", prompt_vorher)

    def kein_folgezug(v):
        v["folge_turns"] = []
    wv("kein Folgezug gespeichert", kein_folgezug)


# ---------------------------------------------------------------- E: echter Abbruch
def teil_e(ns, aus: Path):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", 5050))
        s.listen(1)
    except OSError as ex:
        probe("E", "Port für den Abbruchversuch belegbar", False, str(ex))
        return
    try:
        rc, erg = kettenlauf(ns, ns.p25, SOLL["kandidaten"]["P25"]["aufnahme"], ["PU1"], aus)
    finally:
        s.close()
    probe("E", "echter Abbruch (Port belegt): Kettenprüfer BLOCKIERT, Rückgabecode 3",
          rc == 3 and erg.get("gesamt") == "BLOCKIERT" and bool(erg.get("abbruch")), "rc %s, %s" % (rc, erg.get("abbruch")))
    c, a = pa.kette_auswerten(erg, rc, KATALOG, REGELN, erg.get("basis", {}).get("zip_sha"), pa.sha(KATALOG_PFAD))
    probe("E", "echter Abbruch: Freigabe nicht GRÜN, keine Achse GRÜN", pa.entscheidung(c, a, REGELN)[0] != "GRUEN" and "GRUEN" not in a.values(), str(a)[:200])


# ---------------------------------------------------------------- F: Manifest
def teil_f():
    t = Path(tempfile.mkdtemp(prefix="manifest_"))
    try:
        kopie = t / "m"
        shutil.copytree(BASE, kopie, ignore=shutil.ignore_patterns("SELBSTABNAHME_LAUF*", "ERGEBNIS_*", "__pycache__", "BELEGE*", pa.MANIFEST))
        probe("F", "ohne Manifest: nicht abgenommen", not pa.manifest_pruefen(kopie)[0])
        d = {"version": "test", "dateien": {r: pa.sha(kopie / r) for r in pa.maschinen_dateien(kopie)}, "selbstabnahme": {"gesamt": "GRUEN"}}
        (kopie / pa.MANIFEST).write_text(json.dumps(d), encoding="utf-8")
        probe("F", "passendes Manifest: abgenommen", pa.manifest_pruefen(kopie)[0])
        (kopie / "kettenpruefer" / "kp_faelle.json").write_text((kopie / "kettenpruefer" / "kp_faelle.json").read_text() + " ", encoding="utf-8")
        probe("F", "Fallkatalog geändert: nicht abgenommen", not pa.manifest_pruefen(kopie)[0])
        shutil.copy2(BASE / "kettenpruefer" / "kp_faelle.json", kopie / "kettenpruefer" / "kp_faelle.json")
        (kopie / "kettenpruefer" / "neu.py").write_text("x = 1\n", encoding="utf-8")
        probe("F", "Datei hinzugefügt: nicht abgenommen", not pa.manifest_pruefen(kopie)[0])
        (kopie / "kettenpruefer" / "neu.py").unlink()
        (kopie / "PRUEFREGELN_V12.json").unlink()
        probe("F", "Prüfregeln entfernt: nicht abgenommen", not pa.manifest_pruefen(kopie)[0])
        shutil.copy2(BASE / "PRUEFREGELN_V12.json", kopie / "PRUEFREGELN_V12.json")
        d["selbstabnahme"]["gesamt"] = "ROT"
        (kopie / pa.MANIFEST).write_text(json.dumps(d), encoding="utf-8")
        probe("F", "Manifest einer nicht bestandenen Selbstabnahme: nicht abgenommen", not pa.manifest_pruefen(kopie)[0])
    finally:
        shutil.rmtree(t, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--p25", required=True)
    ap.add_argument("--p24", required=True)
    ap.add_argument("--p23", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--node-cache", default="")
    ap.add_argument("--playwright", default="playwright")
    ns = ap.parse_args()
    aus = BASE / ("SELBSTABNAHME_LAUF_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))
    aus.mkdir()
    vorher = {r: pa.sha(BASE / r) for r in pa.maschinen_dateien(BASE)}
    for n, k in (("P25", ns.p25), ("P24", ns.p24), ("P23", ns.p23)):
        probe("B", "%s ist der Kandidat aus den Sollwerten (Hash)" % n, pa.sha(Path(k)) == SOLL["kandidaten"][n]["zip_sha"], pa.sha(Path(k))[:16])
    teil_a()
    teil_f()
    alle = [f["id"] for f in KATALOG["faelle"]]
    r25 = kettenlauf(ns, ns.p25, SOLL["kandidaten"]["P25"]["aufnahme"], alle, aus / "P25")
    fingerabdruck("P25", *r25)
    teil_d(r25, aus / "P25")
    for n in ("P24", "P23"):
        s = SOLL["kandidaten"][n]
        rc, erg = kettenlauf(ns, getattr(ns, n.lower()), s["aufnahme"], s["faelle"], aus / n)
        fingerabdruck(n, rc, erg)
        if not s.get("kandidat_rot"):
            c, a = pa.kette_auswerten(erg, rc, KATALOG, regeln_mit(erg.get("angefordert") or []), erg.get("basis", {}).get("zip_sha"), pa.sha(KATALOG_PFAD))
            probe("B", "%s: Freigabeauswertung übernimmt den Lauf und meldet nicht GRÜN" % n,
                  next(x["status"] for x in c if x["id"] == "07_kettenpruefer_lauf") == "PASS" and pa.entscheidung(c, a, REGELN)[0] != "GRUEN", str(a)[:160])
    teil_c(ns, r25[1], aus / "MUTATIONEN")
    teil_e(ns, aus / "ABBRUCH")
    nachher = {r: pa.sha(BASE / r) for r in pa.maschinen_dateien(BASE)}
    probe("F", "Maschine während der Selbstabnahme unverändert", vorher == nachher)
    fehl = [x for x in ERG if not x["ok"]]
    gesamt = "GRUEN" if not fehl else "ROT"
    ergebnis = {"version": "V1.2", "zeit_utc": datetime.now(timezone.utc).isoformat(), "gesamt": gesamt,
                "anzahl": len(ERG), "bestanden": len(ERG) - len(fehl), "proben": ERG}
    (aus / "SELBSTABNAHME_ERGEBNIS.json").write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1), encoding="utf-8")
    zeilen = ["MATRIX10 PRÜFMASCHINE V1.2 – SELBSTABNAHME", "=" * 60, "GESAMT: %s (%d von %d Proben bestanden)" % (gesamt, len(ERG) - len(fehl), len(ERG)), ""]
    for x in ERG:
        zeilen.append("[%s] %s %s%s" % ("OK" if x["ok"] else "FEHLT", x["bereich"], x["name"], (" | " + x["beleg"][:200]) if x["beleg"] else ""))
    (aus / "SELBSTABNAHME_LESEN.txt").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    if gesamt == "GRUEN":
        manifest = {"version": "V1.2", "erstellt_utc": ergebnis["zeit_utc"], "dateien": nachher,
                    "selbstabnahme": {"gesamt": gesamt, "proben": len(ERG), "ergebnis_sha256": pa.sha(aus / "SELBSTABNAHME_ERGEBNIS.json"),
                                      "lauf": aus.name}}
        (BASE / pa.MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("SELBSTABNAHME:", gesamt, "->", aus / "SELBSTABNAHME_LESEN.txt", flush=True)
    return 0 if gesamt == "GRUEN" else 2


if __name__ == "__main__":
    sys.exit(main())
