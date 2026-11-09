"""MATRIX10 Prüfmaschine V1.2 – reine Auswertungslogik (kein Netz, keine Datenbank, kein Produktcode).

Ein Ort für jede Entscheidung, damit sie gezielt gegengeprüft werden kann (SELBSTABNAHME_V12.py):
  fall_status        – ein Fall ist nur GRÜN, wenn GENAU die Glieder 1..20 je einmal vorliegen, keines fehlt,
                       keines doppelt ist und NICHT_ZUTREFFEND nur dort steht, wo der eingefrorene Katalog es erlaubt.
  lauf_gesamt        – Gesamtstatus eines Kettenlaufs aus den NACHGERECHNETEN Fallstatus.
  wissen_im_folgezug – Glied 13: Wissen ist nur nachgewiesen, wenn GENAU die Folgezug-Figur das Ereignis erhalten hat:
                       kanonisches Zeugenwissen (SQLite) + BrainContext-PROMPT derselben Spur, derselben Sitzung,
                       desselben Sprechers, nach dem Hauptcommit, mit dem Ereignistext.
  kette_auswerten    – Übernahme eines Kettenprüfer-Ergebnisses durch die Freigabe: Echtheit (Hashes), Rückgabecode,
                       'gesamt', 'abbruch', Vollständigkeit aller Pflichtfälle, 20 Glieder, nachgerechnete Status.
  entscheidung       – GRÜN nur, wenn JEDE Pflichtprüfung genau einmal vorliegt und PASS ist und JEDE der 16
                       Pflichtachsen GRÜN ist. Fehlt etwas: BLOCKIERT. Ein Vertragsfehler: ROT.
Statuswerte: GRUEN / ROT / BLOCKIERT / NICHT_ZUTREFFEND (Glied) bzw. PASS / ROT / BLOCKIERT / UNGEPRUEFT (Prüfung).
"""
from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

GLIEDER = [
    "SOLL-Vertrag und konkrete Erwartung", "Ausgangs-ZIP, Hash und Datenbank", "Reale UI-Bedienung",
    "Gesendete IDs, Rolle, Modus, Actor, Target, Scope", "Backendroute und erste serverseitige Bindung",
    "Kanonischer Owner und Writer", "Zustand vor dem Write", "Zustand nach dem Write",
    "Erzeugte Fact-IDs und ihr Inhalt", "Wissensverteilung und Unwissende", "Runtime-/Körper-/Szenenfolgen",
    "Zuständiger Reader", "BrainContext im Folgezug", "Sichtbare Antwort und Komponentencommit",
    "Zustand im Folgezug", "Reload/Neustart", "Sichtbare UI-Rückanzeige", "Negative Isolation",
    "Prüfung am frisch entpackten ZIP", "Status mit Begründung",
]
GLIED_STATUS = ("GRUEN", "ROT", "BLOCKIERT", "NICHT_ZUTREFFEND")
RC_STATUS = {0: "GRUEN", 2: "ROT", 3: "BLOCKIERT"}
# beobachtbare Ereignisse (2_7master §26 Z.1327-1355): Anwesende am Ort, die wahrnehmen können, werden Zeugen
BEOBACHTBAR = ("speech", "action", "physical", "body_state", "regie", "presence")
WISSENS_ZUGANG = ("heard", "seen", "affected")
# unmittelbarer Stimulus des Folgezugs (2_7master §49.2: was gesagt, gefragt, getan wurde) - abgeleitete Zustands-Facts
# (physical, body_state) tragen technischen Text und sind nicht der Reiz, den die Figur im BrainContext erhalten muss
STIMULUS = ("speech", "action")


# ---------------------------------------------------------------- Fall und Lauf
def fall_status(glieder: list, n_a_erlaubt) -> tuple[str, list[str]]:
    """Status eines Falls aus seinen Gliedern 1..19 (Glied 20 ist das Ergebnis selbst)."""
    erlaubt = {int(x) for x in (n_a_erlaubt or [])}
    gruende = []
    nummern = [x.get("glied") for x in glieder if isinstance(x, dict)]
    if sorted(n for n in nummern if isinstance(n, int)) != list(range(1, 21)) or len(nummern) != 20:
        doppelt = sorted({n for n in nummern if nummern.count(n) > 1})
        fehlt = sorted(set(range(1, 21)) - set(nummern))
        gruende.append("Glieder nicht genau 1..20 je einmal (fehlt %s, doppelt %s)" % (fehlt, doppelt))
    stat = {}
    for x in glieder:
        if not isinstance(x, dict):
            continue
        n, s = x.get("glied"), x.get("status")
        stat[n] = s
        if n == 20:
            continue
        if s not in GLIED_STATUS:
            gruende.append("Glied %s mit unzulässigem Status %r" % (n, s))
        elif s == "NICHT_ZUTREFFEND" and n not in erlaubt:
            gruende.append("Glied %02d NICHT_ZUTREFFEND, im Katalog aber Pflicht" % n)
    for n in sorted(erlaubt):
        if n in stat and stat[n] != "NICHT_ZUTREFFEND":
            gruende.append("Glied %02d laut Katalog nicht zutreffend, aber als %s bewertet" % (n, stat[n]))
    if gruende:
        return "BLOCKIERT", gruende
    s19 = [stat[n] for n in range(1, 20)]
    if "ROT" in s19:
        return "ROT", []
    if "BLOCKIERT" in s19:
        return "BLOCKIERT", []
    return "GRUEN", []


def lauf_gesamt(fallstatus: list[str], kandidat_rot, abbruch) -> str:
    if kandidat_rot:
        return "ROT"
    if abbruch or not fallstatus:
        return "BLOCKIERT"
    if "ROT" in fallstatus:
        return "ROT"
    if any(s != "GRUEN" for s in fallstatus):
        return "BLOCKIERT"
    return "GRUEN"


# ---------------------------------------------------------------- Glied 13: Wissen im Folgezug
def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip().strip(".!?,;:*\"'„“ ").lower()


def text_enthalten(ereignis: str, prompt: str) -> tuple[bool, str]:
    """Der Ereignistext steht im PROMPT: zusammenhängende Übereinstimmung von mindestens min(Länge, 20) Zeichen.
    Allgemein (keine Wortliste); der Prompt darf den Akteursnamen anders voranstellen."""
    e, p = _norm(ereignis), _norm(prompt)
    if not e:
        return False, ""
    if e in p:
        return True, e[:60]
    m = SequenceMatcher(None, e, p, autojunk=False).find_longest_match(0, len(e), 0, len(p))
    return m.size >= min(len(e), 20), e[m.a:m.a + m.size][:60]


def _ts(z: dict) -> str:
    return str(z.get("ts") or "")


def wissen_im_folgezug(e: dict) -> tuple[str, str]:
    """Eingabe e (vom Kettenprüfer je Fall mitgeschrieben, Datei wissen_<Fall>.json):
       sid, soll ('erhalten' | 'nicht_erhalten'), haupt_facts, folge_facts, folge_turns, wk_nachher, namen, logz.
    Nachweis 'erhalten' verlangt ALLES:
       a) Folgezug-Sprecher S = Sprecher des ersten gespeicherten Figurenzugs nach dem Hauptcommit;
       b) S ist Zeuge jedes Haupt-Stimulus (Rede/Handlung, §49.2) (oder dessen Akteur) und hat dafür kanonisches Zeugenwissen
          (witness_knowledge heard/seen/affected) - außer S ist selbst der Akteur (selbst getan, Z.1340);
       c) Spur T = die Spur, deren WRITER die Folgezug-Facts geschrieben hat; in T bindet KERNEL_BIND genau diese
          Sitzung und genau S;
       d) in T steht ein PROMPT für S (Name), zeitlich nach dem Hauptcommit, der den Ereignistext enthält.
    'nicht_erhalten' (2_7master §49: BrainContext darf kein Wissen verteilen): S ist kein Zeuge und der Text fehlt."""
    g = []
    sid, logz = e.get("sid"), e.get("logz") or []
    haupt = [f for f in e.get("haupt_facts") or [] if f.get("kind") in STIMULUS]
    zuege = [t for t in e.get("folge_turns") or [] if t.get("role") == "character" and t.get("speakerId")]
    if not haupt:
        return "ROT", "kein Haupt-Ereignis (Rede/Handlung) gespeichert"
    if not zuege:
        return "ROT", "kein gespeicherter Folgezug einer Figur"
    S = str(zuege[0]["speakerId"])
    name = (e.get("namen") or {}).get(S)
    folge_ids = {str(f.get("id")) for f in e.get("folge_facts") or []}
    spuren = set()
    for z in logz:
        if z.get("stage") == "WRITER":
            ids = {str(z.get("record_id") or "")} | set(re.findall(r"fact_[0-9a-f_]+", str(z.get("turn_facts") or "")))
            if ids & folge_ids:
                spuren.add(z.get("trace_id"))
    if len(spuren) != 1:
        return "ROT", "Spur des Folgezugs nicht eindeutig (%d Spuren schrieben die Folgezug-Facts)" % len(spuren)
    T = next(iter(spuren))
    commits = sorted(_ts(z) for z in logz if z.get("stage") == "SQLITE_COMMIT" and z.get("status") in ("PASS", "INPUT_COMMITTED"))
    t_haupt = commits[0] if commits else ""
    bind = [z for z in logz if z.get("trace_id") == T and z.get("stage") == "KERNEL_BIND"]
    if not any(str(z.get("resolved_session_id")) == str(sid) and str(z.get("resolved_speaker_id")) == S for z in bind):
        g.append("KERNEL_BIND der Spur %s bindet nicht Sitzung %s und Sprecher %s (%s)" % (
            T, sid, S, [(z.get("resolved_session_id"), z.get("resolved_speaker_id")) for z in bind][:3]))
    prompts = [z for z in logz if z.get("trace_id") == T and z.get("stage") == "PROMPT"]
    eigene = [p for p in prompts if name and str(p.get("speaker")) == name and _ts(p) >= t_haupt]
    if not eigene:
        g.append("kein PROMPT für %s (%s) in der Spur des Folgezugs nach dem Hauptcommit (vorhanden: %s)" % (
            S, name, sorted({str(p.get("speaker")) for p in prompts})))
    wk = {(str(w.get("character_id") or w.get("characterId")), str(w.get("fact_id") or w.get("factId"))): w.get("access")
          for w in e.get("wk_nachher") or []}
    belege = []
    for f in haupt:
        fid, akteur = str(f.get("id")), str(f.get("actorId") or "")
        zeuge = S in [str(x) for x in f.get("witnessedBy") or []] or S == akteur
        wissen = S == akteur or wk.get((S, fid)) in WISSENS_ZUGANG
        drin, stueck = (False, "")
        for p in eigene:
            drin, stueck = text_enthalten(f.get("text") or "", json.dumps(p.get("sections") or {}, ensure_ascii=False))
            if drin:
                break
        if e.get("soll") == "nicht_erhalten":
            if zeuge or wissen or drin:
                g.append("%s erhält '%s' ohne zulässigen Wissensweg (Zeuge %s, Zeugenwissen %s, im PROMPT %s)" % (
                    S, str(f.get("text"))[:40], zeuge, wissen, drin))
            continue
        if not zeuge:
            g.append("%s ist nicht Zeuge von '%s'" % (S, str(f.get("text"))[:40]))
        if not wissen:
            g.append("%s hat kein kanonisches Zeugenwissen zu '%s'" % (S, str(f.get("text"))[:40]))
        if eigene and not drin:
            g.append("PROMPT für %s enthält '%s' nicht" % (name, str(f.get("text"))[:40]))
        belege.append(stueck)
    if g:
        return "ROT", "; ".join(g[:5])
    return "GRUEN", "Spur %s: Sprecher %s (%s), Sitzung gebunden, Zeugenwissen vorhanden, PROMPT nach Hauptcommit enthält %s" % (
        T, S, name, [b for b in belege if b][:3] or "-")


# ---------------------------------------------------------------- Übernahme in die Freigabe
def pflicht_faelle(regeln: dict) -> list[str]:
    out = []
    for a in regeln["pflichtachsen"]:
        out += list(regeln["pflichtfaelle"].get(a) or [])
    return out


def kette_auswerten(erg: dict | None, rc, katalog: dict, regeln: dict, kandidat_sha: str, katalog_sha: str) -> tuple[list, dict]:
    """Prüfungen und Achsenstatus aus einem Kettenprüfer-Lauf. Nichts wird geglaubt, alles nachgerechnet."""
    checks: list = []

    def p(i, s, d, art="vertrag"):
        checks.append({"id": i, "status": s, "detail": d, "art": art})

    soll = pflicht_faelle(regeln)
    kat = {f["id"]: f for f in katalog.get("faelle") or []}
    erg = erg if isinstance(erg, dict) else {}
    probleme = []
    b = erg.get("basis") or {}
    if not erg:
        probleme.append("kein Ergebnis")
    if b.get("zip_sha") != kandidat_sha:
        probleme.append("Ergebnis gehört zu anderem ZIP")
    if b.get("pruefer_sha") != regeln["kettenpruefer"]["sha256"]:
        probleme.append("Kettenprüfer-Hash weicht vom eingefrorenen ab")
    if b.get("faelle_sha") != katalog_sha or katalog_sha != regeln["kettenpruefer"]["dateien"].get("kettenpruefer/kp_faelle.json"):
        probleme.append("Fallkatalog-Hash fehlt oder weicht ab")
    if RC_STATUS.get(rc) != erg.get("gesamt"):
        probleme.append("Rückgabecode %r passt nicht zu gesamt=%r" % (rc, erg.get("gesamt")))
    if erg.get("abbruch"):
        probleme.append("Abbruch: %s" % erg.get("abbruch"))
    faelle = [f for f in erg.get("faelle") or [] if isinstance(f, dict)]
    ids = [f.get("id") for f in faelle]
    fremd = sorted({i for i in ids if i not in soll})
    if fremd:
        probleme.append("unbekannte/nicht verlangte Fälle %s" % fremd)
    nachgerechnet = {}
    for fid in soll:
        treffer = [f for f in faelle if f.get("id") == fid]
        if not treffer:
            nachgerechnet[fid] = "BLOCKIERT"
            p("07_kette_" + fid, "BLOCKIERT", "Pflichtfall fehlt im Ergebnis", "nachweis")
            continue
        if len(treffer) > 1 or fid not in kat:
            nachgerechnet[fid] = "BLOCKIERT"
            p("07_kette_" + fid, "BLOCKIERT", "Fall doppelt oder nicht im eingefrorenen Katalog", "nachweis")
            continue
        fe = treffer[0]
        s, gr = fall_status(fe.get("glieder") or [], (kat[fid].get("nicht_zutreffend") or {}).keys())
        g20 = next((x.get("status") for x in fe.get("glieder") or [] if isinstance(x, dict) and x.get("glied") == 20), None)
        if s != "BLOCKIERT" and (fe.get("status") != s or g20 != s):
            gr.append("gemeldeter Status %s/%s, nachgerechnet %s" % (fe.get("status"), g20, s))
            s = "BLOCKIERT"
        if fe.get("achse") != kat[fid].get("achse"):
            gr.append("Achse %r statt %r" % (fe.get("achse"), kat[fid].get("achse")))
            s = "BLOCKIERT"
        nachgerechnet[fid] = s
        rote = [x for x in fe.get("glieder") or [] if isinstance(x, dict) and x.get("status") == "ROT" and x.get("glied") != 20]
        p("07_kette_" + fid, {"GRUEN": "PASS", "ROT": "ROT"}.get(s, "BLOCKIERT"),
          "; ".join(gr) if gr else ("; ".join("Glied %02d: %s" % (x["glied"], str(x.get("beleg"))[:140]) for x in rote[:3]) or "alle 20 Glieder belegt"),
          "vertrag" if s == "ROT" else "nachweis")
    gesamt_neu = lauf_gesamt([nachgerechnet[f] for f in soll], erg.get("kandidat_rot"), erg.get("abbruch"))
    if erg and gesamt_neu != erg.get("gesamt") and not erg.get("kandidat_rot"):
        probleme.append("gemeldetes gesamt=%r, nachgerechnet %r" % (erg.get("gesamt"), gesamt_neu))
    for k in erg.get("kandidat_rot") or []:
        p("07_kettenpruefer_kandidat", "ROT", str(k))
    p("07_kettenpruefer_lauf", "BLOCKIERT" if probleme else "PASS", "; ".join(probleme) or
      "Lauf echt (ZIP-, Prüfer-, Katalog-Hash), Rückgabecode %s = %s, alle %d Pflichtfälle genau einmal" % (rc, erg.get("gesamt"), len(soll)),
      "nachweis" if probleme else "vertrag")
    achsen = {}
    for a in regeln["pflichtachsen"]:
        fs = list(regeln["pflichtfaelle"].get(a) or [])
        if not fs:
            achsen[a] = "UNGEPRUEFT"
        elif probleme or erg.get("kandidat_rot"):
            achsen[a] = "BLOCKIERT"     # unglaubwürdiger oder nicht gelaufener Lauf: weder GRÜN noch ROT ableitbar
        else:
            st = [nachgerechnet[f] for f in fs]
            achsen[a] = "ROT" if "ROT" in st else ("GRUEN" if all(x == "GRUEN" for x in st) else "BLOCKIERT")
    return checks, achsen


def pflicht_checks(regeln: dict) -> list[str]:
    ids = ["00_pruefmaschine_abgenommen", "00_basis_eingefroren", "01_zip"]
    ids += ["02_soll_" + n for n in regeln["sollquellen"]]
    ids += ["03_quellenregister", "04_frontend_bau", "05_typecheck_regression", "05_typecheck_gesamt",
            "06_python_suite", "06_regression_neu_rot", "06_unveraendert_rot", "07_kettenpruefer_lauf"]
    ids += ["07_kette_" + f for f in pflicht_faelle(regeln)]
    ids += ["08_vorbefund_" + v["id"] for v in regeln["offene_vorbefunde"]]
    ids += ["09_achse_" + a for a in regeln["pflichtachsen"]]
    ids += ["10_pruefmaschine_unveraendert"]
    return ids


def entscheidung(checks: list, achsen: dict, regeln: dict) -> tuple[str, list[str]]:
    """Einzige Freigabeentscheidung."""
    gr = []
    ids = [c.get("id") for c in checks if isinstance(c, dict)]
    pflicht = pflicht_checks(regeln)
    fehlt = [i for i in pflicht if i not in ids]
    doppelt = sorted({i for i in pflicht if ids.count(i) > 1})
    if fehlt:
        gr.append("Pflichtprüfungen fehlen: %s" % fehlt[:6])
    if doppelt:
        gr.append("Pflichtprüfungen doppelt: %s" % doppelt[:6])
    if sorted(achsen) != sorted(regeln["pflichtachsen"]):
        gr.append("Achsenliste weicht von den 16 Pflichtachsen ab")
    if not checks:
        gr.append("keine Prüfungen")
    rot = [c["id"] for c in checks if c.get("status") == "ROT"] + [a for a, s in achsen.items() if s == "ROT"]
    if gr:
        return "BLOCKIERT", gr + (["zusätzlich ROT: %s" % rot[:4]] if rot else [])
    if rot:
        return "ROT", ["ROT: %s" % rot[:8]]
    offen = [c["id"] for c in checks if c.get("status") != "PASS"] + [a for a, s in achsen.items() if s != "GRUEN"]
    if offen:
        return "BLOCKIERT", ["nicht nachgewiesen: %s" % offen[:8]]
    return "GRUEN", []


# ---------------------------------------------------------------- Unabhängigkeit: Abnahme-Manifest
MANIFEST = "ABNAHME_V12.json"


def maschinen_dateien(basis: Path) -> list[str]:
    """Alle Dateien, die die Prüfmaschine ausmachen (ohne Ergebnisse, Umgebungen, Belege)."""
    aus = ("ERGEBNIS_", "SELBSTABNAHME_LAUF", "MODELLAUFNAHME", ".pruefumgebung", ".playwright", "__pycache__", "BELEGE")
    out = []
    for p in sorted(basis.rglob("*")):
        r = p.relative_to(basis).as_posix()
        if p.is_file() and r != MANIFEST and not any(t in r for t in aus):
            out.append(r)
    return out


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def manifest_pruefen(basis: Path) -> tuple[bool, str, str]:
    """(ok, Grund, Manifest-SHA). ok nur, wenn das Abnahme-Manifest existiert, jede Maschinendatei darin steht
    und jeder Hash stimmt - und keine Datei hinzugekommen ist."""
    m = basis / MANIFEST
    if not m.is_file():
        return False, "kein Abnahme-Manifest – Prüfmaschine nicht abgenommen", ""
    try:
        d = json.loads(m.read_text(encoding="utf-8"))
    except Exception as ex:
        return False, "Manifest unlesbar: %s" % ex, sha(m)
    soll = d.get("dateien") or {}
    ist = maschinen_dateien(basis)
    abw = [r for r in ist if soll.get(r) != sha(basis / r)]
    fehlt = [r for r in soll if r not in ist]
    if abw or fehlt or d.get("selbstabnahme", {}).get("gesamt") != "GRUEN":
        return False, "Maschine weicht von der Abnahme ab: geändert/neu %s, fehlt %s, Selbstabnahme %s" % (
            abw[:4], fehlt[:4], d.get("selbstabnahme", {}).get("gesamt")), sha(m)
    return True, "Abnahme %s, %d Dateien unverändert" % (d.get("version"), len(soll)), sha(m)
