"""MATRIX system kernel (Python). Fachliche Owner bleiben getrennt. LLM formuliert nur."""
from __future__ import annotations

import copy
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from .ids import uid
from . import conjunctive as _conj
from . import truth as _truth
from . import scene_state as _scene


# R4.2 / B.34-Folge: Lock für Fate-mustNot-Initialisierung.
# commit_turn, apply_fate und apply_fate_pressure können alle
# mustNot initialisieren. In single-threaded Python ist das effektiv
# sequenziell, aber logisch ein Race (AutoChat + User können sich
# überlappen, und der Validator in kernel_session_response Z. 4523
# liest den Wert). Lock garantiert dass nur EIN Initialisierer
# gewinnt, andere bleiben idempotent.
_FATE_MUSTNOT_LOCK = threading.Lock()
_DEFAULT_MUSTNOT = "Kein erfundenes Wissen. Abwesende wissen nichts. Avatar nicht steuern."


def _ensure_fate_mustNot(fate: dict, world: dict | None) -> dict:
    """R4.2 / B.34-Folge: Stellt sicher, dass fate.mustNot gesetzt ist.

    Idempotent: wenn schon gesetzt, unverändert. Wenn leer, sucht nach
    world.fateSeeds[].mustNot, dann Default-String.

    Thread-safe via _FATE_MUSTNOT_LOCK — verhindert Race wenn AutoChat
    + User parallel mustNot initialisieren wollen.

    Returns:
        fate (mutiert in-place + return für Chaining).
    """
    with _FATE_MUSTNOT_LOCK:
        if fate.get("mustNot"):
            return fate
        must = ""
        if isinstance(world, dict):
            for seed in list(world.get("fateSeeds") or []) + list(world.get("fateBeats") or []):
                if isinstance(seed, dict) and seed.get("mustNot"):
                    must = str(seed.get("mustNot") or "")
                    break
        fate["mustNot"] = must or _DEFAULT_MUSTNOT
        return fate


def _next_id(prefix: str, session: dict | None, kind: str | None = None) -> str:
    """V1/B.27: kanonische Child-ID ohne Request-Lifetime-Counter.

    Persistierte Child-IDs dürfen nicht von einem In-Memory-Counter abhängen,
    weil ein HTTP-Reload einen neuen Session-Dict-Lifetime beginnt. Der bereits
    vorhandene Backend-ID-Owner ``uid(prefix)`` erzeugt deshalb die neue ID.
    Gegen den aus SQLite rehydrierten Kindbestand der Session wird zusätzlich
    geprüft, dass eine bereits persistierte ID nicht wiederverwendet wird.

    ``kind`` bleibt nur signaturkompatibel; Persistenz-Identität hängt nicht
    mehr von einem flüchtigen Sub-Counter ab.
    """
    collection = {
        "ln": "turns",
        "prop": "propositions",
        "goal": "goals",
    }.get(prefix)
    existing: set[str] = set()
    if isinstance(session, dict) and collection:
        for item in session.get(collection) or []:
            if isinstance(item, dict) and item.get("id"):
                existing.add(str(item.get("id")))

    # uid() ist der bestehende Backend-ID-Owner. Die Schleife macht selbst
    # eine extrem unwahrscheinliche Kollision gegen den rehydrierten Bestand
    # sichtbar/unschädlich, ohne einen zweiten Counter oder Store einzuführen.
    for _ in range(64):
        candidate = uid(prefix)
        if candidate not in existing:
            return candidate
    raise RuntimeError(f"unable to allocate unique persisted child id for {prefix}")
# B.9 (AMASTERv2 §9 / §39): Stammwissen ist der einzige Reader.
# Volltext-Heuristik als zweiter Wissensowner entfernt (war source_knowledge_for).
# Importe bleiben ungenutzt — kein zweiter Pfad.


_CAPABILITY_RE = re.compile(
    r"steht auf|rennt|greift|geht|läuft|schlägt|tritt|läuft|geht zur|zur tür|zur tuer",
    re.I,
)
_MOVE_RE = re.compile(
    r"geht|läuft|rennt|steht auf|setzt sich|kommt|verlässt|tritt ein|zur tür|zur tuer|zur theke",
    re.I,
)
_QUESTION_RE = re.compile(
    r"^\s*(was|wer|wie|wo|wann|warum|wieso|weshalb|weswegen|welche|welcher|welches|"
    r"kannst|kann\b|könntest|koenntest|würdest|wuerdest|willst|hast du|habt ihr|"
    r"bist du|seid ihr|ist\b|sind\b|darf|soll|möchtest|moechtest|machst du)\b",
    re.I,
)
_REFUSE_RE = re.compile(r"\b(nein|lehne ab|weiger|will nicht|tu ich nicht|mache ich nicht)\b", re.I)
_WEEKDAYS = {
    "montag": "Montag",
    "dienstag": "Dienstag",
    "mittwoch": "Mittwoch",
    "donnerstag": "Donnerstag",
    "freitag": "Freitag",
    "samstag": "Samstag",
    "sonntag": "Sonntag",
}
# V36: Wortgrenzen — "schaut" enthielt "haut", "Vorschlag" enthielt "schlag" → Fehlklassifikation als Schlag
_STRIKE_RE = re.compile(r"\b(schlägt|schlaegt|schlagen|schlug|greift (?:ihn|sie|dich|mich|an)|tritt (?:ihn|sie|dich|mich|zu|nach)|schlag\b|haut (?:ihm|ihr|dir|mir|zu|ab)|boxt|prügelt|pruegelt|stößt|stoesst|ohrfeigt|würgt|wuergt|packt (?:ihn|sie|dich|mich))", re.I)
_RESTRAIN_RE = re.compile(r"fessel|bindet|knebel|fesselt|fesseln|fixier", re.I)
_FREE_RE = re.compile(r"befreit|losbind|entfessel|losgemacht|entfesselt|losgebunden", re.I)
_SOCIAL_RE = re.compile(r"küsst|küsse|kuss|umarmt|umarme|umarmen|streichelt|streichel", re.I)
_THREAT_RE = re.compile(r"\b(bedroh\w*|schlag\b|schläg\w*|schlaeg\w*|waffe\w*|verletz\w*|droh\w*|umbring\w*|töt\w*|toet\w*|bring\w* \w+ um\b)", re.I)
_RESIGN_RE = re.compile(r"kündig|verlass(?:e|t)? das haus|komme nicht zurück|meine entscheidung", re.I)
_GREET_LINE_RE = re.compile(r"guten tag|herzlich willkommen|ich bin .{0,80}(haushälter|wirtin)", re.I)
_ACCEPT_RE = re.compile(
    r"^(ja|ok|okay|einverstanden|geht klar|mache ich|in ordnung|klar|sicher|mach ich)"
    r"|das mache ich|mache ich gern|übernehme (die )?schicht|ich übernehme|mach ich"
    r"|gern(e)?\.?$|alles klar",
    re.I,
)
_REFUSE_MORE_RE = re.compile(
    r"auf keinen fall|niemals|kommt nicht in frage|tu ich nicht|mache ich nicht|will nicht",
    re.I,
)
_REQUEST_RE = re.compile(
    r"\bbitte\b|kannst du|könntest du|würdest du|arbeite\b|bleib bei|bleib hier|bleib bitte|mach (das|es) für",
    re.I,
)
_CHECKIN_RE = re.compile(r"alles in ordnung|alles gut|alles okay|geht's dir|geht es dir", re.I)
_GOD_OWNER_SCOPES = frozenset(
    {"world", "session", "scene", "character", "body", "time", "knowledge", "relationship", "action"}
)
_GOD_SCOPE_ALIAS = {
    "memory": "knowledge",
    "relation": "relationship",
    "wissen": "knowledge",
    "beziehung": "relationship",
    "körper": "body",
    "zeit": "time",
    "szene": "scene",
    "handlung": "action",
}

# V65E (AMASTER §46.4 Epistemic Scope "Welche Figuren kennen die gesetzte
# Tatsache?", §26, §24.4, §68 Nr. 52/7): a God fact set ON one figure —
# knowledge, relationship, body, character state — is known to that figure
# only; nobody in the world hears God (like Regie, V59C). Scene/world/time/
# session God facts change the shared world and stay perceivable by presence.
# Before, every God fact was "heard" by all present figures and copied into the
# shared scene (aftereffects, sceneState history): a hidden God fact for Mara
# stood in Clara's and Robert's facts/godFacts/sceneState sent to the model.
_GOD_PRIVATE_SCOPES = frozenset({"knowledge", "relationship", "body", "character"})


def _god_private(fact: dict) -> bool:
    if str(fact.get("kind") or fact.get("event_kind") or "") != "god":
        return False
    payload = fact.get("payload") if isinstance(fact.get("payload"), dict) else {}
    return _god_scope_key(str(payload.get("scope") or "")) in _GOD_PRIVATE_SCOPES


_REGIE_LABELS = frozenset({"regie", "director", "regisseur", "regie-stimme"})
_LEAD_NAME_RE = re.compile(
    r"^\s*(?P<name>[^,:\n]{1,48}?)\s*,\s*(?:sag(?:e)?|sprich|rede)\b",
    re.I,
)
_ZU_NAME_RE = re.compile(r"\bzu\s+(?P<name>[^:,.]{1,48})", re.I)
_SPEECH_COLON_RE = re.compile(
    r"(?:sag(?:e)?|sprich|rede)\b[^:：]*[:：]\s*(?P<speech>.+)$",
    re.I | re.S,
)
_ACTION_STAR_RE = re.compile(r"\*(?P<action>[^*]+)\*")


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _is_regie_label(value: str | None) -> bool:
    return _norm_name(value or "") in _REGIE_LABELS or not (value or "").strip()


def _match_figure(name: str, figures: list[dict] | None) -> dict | None:
    """V92 Paket 12 (Paket-11-Pruefung; AMASTER §24.1, §25 Zielbindung, §46.2): the ONE identity procedure of the kernel - a
    name binds the figure it names, by the cast data, or nobody. Before, the first figure whose FIRST name matched won
    ("Mara Schmidt" bound Mara Nowak when she stood first in the cast), and a name two figures carry bound one of them.
    Now: figure_ids_for_name - an exact form binds exactly, a single name word binds only when exactly ONE figure carries it;
    several -> None (a later reader shows it as unclear). The V65R rule (a later unique name part, "Alrik" for "Priester
    Alrik") is part of figure_ids_for_name."""
    figs = [f for f in figures or [] if isinstance(f, dict)]
    ids = figure_ids_for_name(name, figs)
    if len(ids) != 1:
        return None
    fid = next(iter(ids))
    return next((f for f in figs if str(f.get("id") or "") == fid), None)


def _name_words(s: Any) -> str:
    """A name as its words (case and punctuation do not matter: "Mara Nowak." == "mara nowak")."""
    return " ".join(re.findall(r"\w+", str(s or "").casefold()))


def _figure_name_forms(f: dict) -> list[str]:
    return [w for w in (_name_words(x) for x in [f.get("name"), *(f.get("aliases") or []), *(f.get("sessionAliases") or [])]) if w]


def figure_ids_for_name(name: str, figures: list[dict] | None) -> set[str]:
    """V92 Paket 11/13 (Paket-10/12-Pruefung; AMASTER §24.1 Identitaet, §46.2 "Actor und Target werden ausdruecklich gebunden"):
    the figure IDs a name of a reading can mean, from the cast data only (name, registered aliases, session names, id).
    A name of SEVERAL words binds only a figure that carries exactly this form - an unknown full name ("Mara Schmidt" when only
    Mara Nowak is known) binds nobody; it never falls back to its first word (Paket-12-Pruefung N1-N4). A single word binds
    every figure that carries it as a form or a whole part of a form (two figures called Johann -> two IDs). No word list."""
    n = _name_words(name)
    if not n:
        return set()
    figs = [f for f in figures or [] if isinstance(f, dict) and str(f.get("id") or "")]
    # V92 Paket 16: a span the operator assigned to one figure by a clarification of THIS input means exactly that figure.
    # V92 Paket 17 (Paket-16-Pruefung N3/N4): by its words only when that span stands ONCE in the input - a name written at two
    # places is bound place by place (name_occurrences with `base`), never by its wording
    claimed = {str(f["id"]) for f in figs if any(c["eindeutig"] and c["words"] == n for c in _klaerung_claims(f))}
    if claimed:
        return claimed
    exact = {str(f["id"]) for f in figs if n == _name_words(f.get("id")) or n in _figure_name_forms(f)}
    if " " in n:
        return exact
    return exact | {str(f["id"]) for f in figs if any(n in form.split() for form in _figure_name_forms(f))}


def component_party(name: str, actor_id: str, figures: list[dict] | None, own_names: Any = ()) -> str:
    """V92 Paket 11: whose is a component, by the name the reading gives - "eigen" (exactly the controlled figure), "fremd"
    (another figure or someone who is not this figure), "unklar" (the name fits several figures), "fehlt" (no name).
    "ich"/"figur" (the reading's word for the figure itself) is the figure. The figure's own name forms count only when the
    name fits NO figure of the scene - a user name or session alias that is another figure's name is that figure (§8, §27.2:
    the operator is no figure; control binding is not identity)."""
    n = _name_words(name)
    if not n:
        return "fehlt"
    if n in ("ich", "figur"):
        return "eigen"
    ids = figure_ids_for_name(n, figures)
    if len(ids) == 1:
        return "eigen" if str(actor_id or "") in ids else "fremd"
    if len(ids) > 1:
        return "unklar"
    return "eigen" if n in {_name_words(x) for x in (own_names or []) if str(x or "").strip()} else "fremd"


def _claimed_party(occurrences: list[dict] | None, name: Any, actor_id: str) -> str | None:
    """V92 Paket 17 (Paket-16-Pruefung N3/N4): whose a reading's name is when the operator answered the clarification for the place
    where that name stands in THIS clause (a record of name_occurrences with `base`, "geklaert") - "eigen"/"fremd" by the chosen
    figure's ID; None when no answered place carries that name (then component_party decides as before). The answer of one
    place never decides another place with the same words."""
    w = _name_words(name)
    if not w:
        return None
    hit = next((o for o in occurrences or [] if o.get("geklaert") and w in (o.get("klaert"), o.get("words"))), None)
    if hit is None:
        return None
    return "eigen" if hit.get("ids") == {str(actor_id or "")} else "fremd"


def planner_cast(session: dict | None, natives: list[dict] | None) -> list[dict]:
    """V92 Paket 13 (Paket-12-Pruefung, Bedingung D): the minimal context of the present persons for the input reading - from the
    canonical cast of THIS session only (its scene's presentIds that are figures of this session's own cast): id, name, the
    registered names (aliases, names established in this session), presence. No figure of another world or session. Read only;
    whatever the reading makes of it stays a proposal that the kernel binds (figure_ids_for_name, literal readings)."""
    by = {str(c.get("id")): c for c in natives or [] if isinstance(c, dict) and c.get("id")}
    out = []
    for pid in dict.fromkeys(str(x) for x in (((session or {}).get("scene") or {}).get("presentIds") or [])):
        c = by.get(pid)
        if not c or not str(c.get("name") or "").strip():
            continue
        names = [str(a).strip() for a in list(c.get("aliases") or []) + list(c.get("sessionAliases") or []) if str(a or "").strip()]
        out.append({"id": pid, "name": str(c.get("name")).strip(), "beinamen": list(dict.fromkeys(names))[:6], "anwesend": True})
    return out[:12]


# V92 Paket 15: a hyphen between two words joins them into ONE written word ("Nowak-Schmidt") - form only
_NAME_JOIN = re.compile(r"[-\u2010\u2011]")
# V92 Paket 16: words of one written name stand on one line, separated by blanks only - form only
_NAME_BLANK = re.compile(r"[ \t\u00a0]+")


def _klaerung_claims(f: dict) -> list[dict]:
    """V92 Paket 16/17: the written name spans the operator assigned to this figure for THIS input (clarification answers) - only
    the ones place_klaerungen has PLACED in the input: {"words", "a", "b" (offsets in the input), "eindeutig" (the span's words
    stand at exactly this one place of the input)}. An answer that is not placed binds nothing."""
    out = []
    for c in f.get("klaerung") or []:
        if isinstance(c, dict) and type(c.get("a")) is int and type(c.get("b")) is int and _name_words(c.get("text")):
            out.append({"words": _name_words(c.get("text")), "a": c["a"], "b": c["b"], "eindeutig": c.get("eindeutig") is True})
    return out


def place_klaerungen(text: str, figures: list[dict] | None) -> list[dict]:
    """V92 Paket 17 (Paket-16-Pruefung N1-N4; AMASTER §24.1, §24.7, §34.1): the operator's answers on the figures (`klaerung`,
    with_klaerungen) PLACED in this input - a read projection, never stored. An answer names ONE written place of the input:
      - with offsets ("a", "b"): the place must be exactly a run of whole words of this text with the answer's words;
      - without offsets: only when its words stand at exactly ONE place of the input ("Mara" written twice names no place - the
        operator must answer each place on its own, the routes always send the place);
      - the chosen figure must be one the place offers: a figure whose name words stand in it (the `kandidaten` rule of
        name_occurrences - "Frau Nowak" never offers Mara Schmidt). Anything else binds nothing; the question stays open;
      - a place two figures are claimed for binds nobody.
    Each placed answer carries "eindeutig" (its words stand only there) - only then may a reader without the place
    (figure_ids_for_name) use it. Form and cast data only, no word list."""
    raw = str(text or "")
    figs = list(figures or [])
    if not any(isinstance(f, dict) and f.get("klaerung") for f in figs):
        return figs
    toks = [(m.group(0).casefold(), m.start(), m.end()) for m in re.finditer(r"\w+", raw)]
    low = [t[0] for t in toks]

    def _places(words: list[str]) -> list[tuple[int, int]]:
        n = len(words)
        return [(toks[i][1], toks[i + n - 1][2]) for i in range(len(toks) - n + 1) if low[i:i + n] == words]

    def _carries(f: dict, words: list[str]) -> bool:
        fl = _figure_name_forms(f)
        return any(w == form or (len(w) >= 3 and w in form.split()) for w in words for form in fl)

    placed: list[tuple[int, dict]] = []
    for idx, f in enumerate(figs):
        if not isinstance(f, dict):
            continue
        for c in f.get("klaerung") or []:
            t = c if isinstance(c, str) else (c.get("text") if isinstance(c, dict) else None)
            words = _name_words(t).split()
            if not words:
                continue
            places = _places(words)
            a = c.get("a") if isinstance(c, dict) else None
            b = c.get("b") if isinstance(c, dict) else None
            if type(a) is int and type(b) is int:
                at = (a, b) if (a, b) in places else None
            else:
                at = places[0] if len(places) == 1 else None
            if at is None or not _carries(f, words):
                continue
            placed.append((idx, {"text": raw[at[0]:at[1]], "a": at[0], "b": at[1], "eindeutig": len(places) == 1}))
    _owners: dict[tuple[int, int], set[str]] = {}
    for idx, c in placed:
        _owners.setdefault((c["a"], c["b"]), set()).add(str(figs[idx].get("id") or ""))
    by: dict[int, list[dict]] = {}
    for idx, c in placed:
        if len(_owners[(c["a"], c["b"])]) == 1:
            by.setdefault(idx, [])
            if c not in by[idx]:
                by[idx].append(c)
    return [({**f, "klaerung": by.get(i, [])} if isinstance(f, dict) and "klaerung" in f else f) for i, f in enumerate(figs)]


def name_boundary_candidates(text: str, figures: list[dict] | None) -> list[dict]:
    """Only suspect capitalized *name boundaries*, never infer IDs from a word list.

    The existing resolver finds these spans conservatively. A semantic reading is
    requested only for the spans it cannot distinguish from an unknown full name.
    """
    raw = str(text or "")
    return [{"a": o["a"], "b": o["b"], "wortfolge": raw[o["a"]:o["b"]]}
            for o in name_occurrences(raw, figures)
            if o.get("state") == "unklar" and o.get("kandidaten")]


def with_name_boundary_reading(text: str, figures: list[dict] | None, reading: Any) -> list[dict]:
    """Validate one independent semantic NAME-EXTENT reading; return a request-local cast.

    Source spans and actual name spans must align with original input. The model
    cannot select a character ID; duplicate names remain ambiguous, and an unknown
    full name cannot be promoted to a different figure. No reading -> no shortcut.
    This metadata is only attached to request-local cast copies; it is never stored.
    """
    figs = [dict(f) for f in figures or [] if isinstance(f, dict)]
    raw = str(text or "")
    if not isinstance(reading, dict) or not raw or not figs:
        return figs
    candidates = {(x["a"], x["b"]): x for x in name_boundary_candidates(raw, figs)}
    valid: list[dict] = []
    for rec in (reading.get("grenzen") if isinstance(reading.get("grenzen"), list) else [])[:24]:
        if not isinstance(rec, dict) or rec.get("status") != "eindeutig":
            continue
        a, b = rec.get("a"), rec.get("b")
        if type(a) is not int or type(b) is not int or (a, b) not in candidates:
            continue
        whole = candidates[(a, b)]["wortfolge"]
        if str(rec.get("wortfolge") or "") != whole:
            continue
        # P22 / AMASTER 24.2, 24.7: only source-token classifications are
        # acceptable.  The legacy free-form name+quote response is an unsafe
        # second validator: two independent omissions of the first unknown
        # name ("Anna Mara Nowak" -> "Mara Nowak") could silently bind a
        # different figure and commit a bodily effect.  The provider now sends
        # wortklassen; unrecognized/old responses remain unresolved.
        token_classes = rec.get("wortklassen")
        if not isinstance(token_classes, list):
            continue
        words = list(re.finditer(r"\w+", whole))
        if not words or len(words) != len(token_classes):
            continue
        allowed = {"name", "gruss", "titel", "praeposition", "anderes", "unklar"}
        if any(type(kind) is not str or kind not in allowed for kind in token_classes):
            continue
        if "unklar" in token_classes:
            continue
        name_positions = [i for i, kind in enumerate(token_classes) if kind == "name"]
        if not name_positions or name_positions != list(range(name_positions[0], name_positions[-1] + 1)):
            continue
        if "gruss" in token_classes and rec.get("rolle") != "anrede":
            continue
        # A leading unmatched capitalized word is not silently discarded as
        # 'anderes' (e.g. Anna Mara Nowak).  Source syntax is only a proposal;
        # the model cannot choose an ID.
        if any(kind == "anderes" for kind in token_classes[:name_positions[0]]):
            continue
        na = a + words[name_positions[0]].start()
        nb = a + words[name_positions[-1]].end()
        named = raw[na:nb]
        if not figure_ids_for_name(named, figs):
            continue
        suggested = str(rec.get("name") or "").strip()
        if suggested and not (figure_ids_for_name(suggested, figs) & figure_ids_for_name(named, figs)):
            continue
        quote = str(rec.get("beleg") or "").strip()
        if quote and not (whole in quote and quote in raw):
            continue
        if not (a <= na < nb <= b):
            continue
        valid.append({"a": a, "b": b, "na": na, "nb": nb, "source": raw,
                      "rolle": "anrede" if rec.get("rolle") == "anrede" else "nennung"})
    if not valid:
        return figs
    return [{**f, "_name_boundary_readings": valid} for f in figs]


def name_occurrences(text: str, figures: list[dict] | None, literal: Any = (), base: int | None = None) -> list[dict]:
    """V92 Paket 13-16 (Paket-12-Pruefung N1-N4; Paket-13-Pruefung "verkuerzte Zweitlesung"; Paket-14-Pruefung "bekannter
    Vollname als Praefix eines fremden Vollnamens"; Paket-15-Pruefung "vorangestellter Name", "gleiche volle Namensformen";
    AMASTER §24.1 Entity-/Alias-Resolver, §24.7 "Ambiguitaet bleibt sichtbar ungebunden", §25 Namensnennung): THE one reading of
    which persons a text names - every name-in-text procedure of the kernel uses it, with the same contract as
    figure_ids_for_name. One record per name occurrence: {"ids", "state", "a", "b", "words", "kandidaten"}; state "ok" (ids = the
    figures it can mean, several = ambiguous), "unbekannt" (a full name the cast does not carry) or "unklar" (the extent of the
    name is not proven); "kandidaten" = the figures of the cast whose name words stand in it (what a clarification can offer).
    EXTENT (one rule for EVERY match - full name form of the cast, literal name of a reading, single name word): a match is a name
    of a figure only when its WHOLE written name is proven by the text. The written name reaches over words joined by a hyphen
    (one written word, both directions) and - for a capitalised name - over the directly ADJACENT capitalised words on both sides
    (blanks only, same line, no punctuation): "Mara Nowak-Schmidt", "Mara Nowak Schmidt", "Anna Mara Nowak". When no SINGLE figure
    the match means carries every further word, the boundary is not proven: the name binds nobody ("unklar"; a literal reading
    giving exactly that whole name makes it "unbekannt"). Paket 15 read the left side only over a hyphen; the Paket-15-Pruefung
    reproduced "Johann schubst Anna Mara Nowak." with planner AND reading shortened to "Mara Nowak" -> body effect on Mara Nowak.
    By form, "Anna Mara Nowak" and "Neben Mara Nowak" / "Frau Nowak" / "Hallo Mara" cannot be told apart without a word list, and
    two readings that agree on the shorter name are no proof - so all of them stay unbound and the operator is asked (the routes'
    clarification, `klaerung` of the figures: an answered span binds exactly the chosen figure). Identical full forms of several
    figures (two "Mara Nowak", a shared alias) are read TOGETHER: one record with all their IDs - never the first one.
    V92 Paket 17 (Paket-16-Pruefung N3/N4): an answer binds the written PLACE it was given for, not its wording - `base` is the
    offset of `text` in the input the answers were placed in (place_klaerungen); without `base` only an answer whose words stand
    once in the input applies. Records stay in the coordinates of `text`; a clarified record carries the answered span's words
    ("klaert").
    Order: (0) a literal reading name NO figure carries; (1) multi-word name
    forms of the cast, longest first, identical forms grouped; (2) the other literal reading names; (3) single name words (>= 3
    letters, or a whole short alias). A literal name without any name word of the cast is an unknown person when written as a
    name (capitalised), otherwise no name (the readings return pronouns). "ich"/"figur" are the readings' contract words, no
    names. Form and cast data only, no word list."""
    raw = str(text or "")
    toks = [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\w+", raw)]
    low = [t.casefold() for t, _a, _b in toks]
    figs = [f for f in figures or [] if isinstance(f, dict) and str(f.get("id") or "")]
    forms = {str(f["id"]): _figure_name_forms(f) for f in figs}
    used = [False] * len(toks)
    out: list[dict] = []
    boundaries = []
    for f in figs:
        for boundary in f.get("_name_boundary_readings") or []:
            if isinstance(boundary, dict) and boundary not in boundaries:
                boundaries.append(boundary)

    def _source_origin(source: str) -> int | None:
        if base is not None:
            return base if source[base:base + len(raw)] == raw else None
        if source == raw:
            return 0
        # Only use a substring when it occurs at one place in the parent input.
        pos = source.find(raw)
        return pos if pos >= 0 and source.find(raw, pos + 1) < 0 else None

    def _semantic_extent(s: int, e: int) -> tuple[int, int] | None:
        for b in boundaries:
            source = str(b.get("source") or "")
            origin = _source_origin(source)
            if origin is None:
                continue
            a, z = int(b["a"]), int(b["b"])
            if (toks[s][1] + origin, toks[e][2] + origin) != (a, z):
                continue
            na, nb = int(b["na"]) - origin, int(b["nb"]) - origin
            if 0 <= na < nb <= len(raw):
                return na, nb
        return None

    def _carriers(w: str) -> set[str]:
        return {fid for fid, fl in forms.items() if any(w == form or (len(w) >= 3 and w in form.split()) for form in fl)}

    def _joined(j: int) -> bool:
        # tokens j and j+1 are one written word (joined by exactly one hyphen)
        return bool(_NAME_JOIN.fullmatch(raw[toks[j][2]:toks[j + 1][1]]))

    def _blank(j: int) -> bool:
        # tokens j and j+1 stand side by side on one line, separated by blanks only
        return bool(_NAME_BLANK.fullmatch(raw[toks[j][2]:toks[j + 1][1]]))

    def _cap(j: int) -> bool:
        return toks[j][0][:1].isupper()

    def _extent(i: int, k: int, fids: set[str]) -> tuple[int, int, bool]:
        # (start, end, unproven) of the whole written name around the match i..k - from the text alone (not from `used`)
        cap = _cap(i)
        s = i
        while s > 0 and (_joined(s - 1) or (cap and _blank(s - 1) and _cap(s - 1))):
            s -= 1
        e = k
        while e + 1 < len(toks) and (_joined(e) or (cap and _blank(e) and _cap(e + 1))):
            e += 1
        # proven only when ONE figure the match means carries every further word (two Maras: "Mara Nowak-Schmidt" is neither)
        extra = [low[x] for x in [*range(s, i), *range(k + 1, e + 1)]]
        own = [{w for form in forms.get(fid, []) for w in form.split()} for fid in fids]
        return s, e, bool(extra) and not any(all(w in o for w in extra) for o in own)

    def _add(i: int, k: int, ids: set[str], state: str, cover: tuple[int, int] | None = None, geklaert: bool = False) -> None:
        c0, c1 = cover or (i, k)
        for x in range(c0, c1 + 1):
            used[x] = True
        cand = set(ids) | {fid for x in range(c0, c1 + 1) for fid in _carriers(low[x])}
        out.append({"ids": set(ids), "state": state, "a": toks[i][1], "b": toks[k][2],
                    "words": " ".join(low[i:k + 1]), "kandidaten": sorted(cand),
                    **({"geklaert": True, "klaert": " ".join(low[c0:c1 + 1])} if geklaert else {})})

    def _match(lw: list[str]):
        for i in range(len(toks) - len(lw) + 1):
            if not any(used[i:i + len(lw)]) and low[i:i + len(lw)] == lw:
                yield i

    # The operator's clarification (V92 Paket 16, routes' `klaerungen`): a written span of THIS text means exactly this figure -
    # its boundary is proven by the operator; inside it, the figure's own name form is the name occurrence (the other words of
    # the span are no name: "Neben Mara Nowak" -> Mara Nowak at "Mara Nowak"); identical forms of several figures -> the chosen one.
    # V92 Paket 17: at its PLACE (`base`); without the place only an answer whose words stand once in the input
    claims = []
    _tok_at = {toks[x][1]: x for x in range(len(toks))}
    for f in figs:
        for c in _klaerung_claims(f):
            fw = c["words"].split()
            if base is not None:
                i = _tok_at.get(c["a"] - base)
                if i is not None and i + len(fw) <= len(toks) and low[i:i + len(fw)] == fw and toks[i + len(fw) - 1][2] + base == c["b"]:
                    claims.append((i, i + len(fw) - 1, str(f["id"])))
            elif c["eindeutig"]:
                claims.extend((i, i + len(fw) - 1, str(f["id"])) for i in range(len(toks) - len(fw) + 1) if low[i:i + len(fw)] == fw)

    def _claimed(s0: int, e0: int, fids: set[str]) -> str | None:
        return next((fid for cs, ce, fid in claims if cs == s0 and ce == e0 and (not fids or fid in fids)), None)

    def _inner(s0: int, e0: int, fid: str) -> tuple[int, int]:
        # the longest name form (or name word) of `fid` inside the span s0..e0
        best = None
        for form in forms.get(fid, []):
            fw = form.split()
            for i in range(s0, e0 - len(fw) + 2):
                if low[i:i + len(fw)] == fw and (best is None or len(fw) > best[1] - best[0] + 1):
                    best = (i, i + len(fw) - 1)
        if best is None:
            best = next(((i, i) for i in range(s0, e0 + 1) if fid in _carriers(low[i])), (s0, e0))
        return best

    def _bind(i: int, k: int, fids: set[str], state_if_proven: str) -> None:
        ss, ee, unproven = _extent(i, k, fids)
        # A signed operator clarification at this exact text position outranks
        # a new model reading. The semantic reader may propose a name boundary,
        # never reinterpret the person's answer or pick a figure ID.
        cf = _claimed(ss, ee, fids)
        if cf:
            ii, kk = _inner(ss, ee, cf)
            _add(ii, kk, {cf}, "ok", cover=(ss, ee), geklaert=True)
            return
        # A second semantic reading can prove the *extent* of a name at this
        # exact original-input place. It never chooses between duplicate IDs.
        extent = _semantic_extent(ss, ee) if unproven else None
        if extent is not None:
            na, nb = extent
            if (toks[i][1], toks[k][2]) == (na, nb) and fids:
                _add(i, k, fids, state_if_proven, cover=(ss, ee))
            # A model-proposed longer unknown name (or an adjacent cast name)
            # cannot consume this proven smaller name and override its owner.
            return
        if unproven:
            _add(ss, ee, set(), "unklar")
        else:
            _add(i, k, fids, state_if_proven)

    def _literal(names: list[str]) -> None:
        for name in names:
            lw = _name_words(name).split()
            if not lw or " ".join(lw) in ("ich", "figur"):
                continue
            _cast_word = any(_carriers(w) for w in lw)
            for i in _match(lw):
                if not _cast_word and not _cap(i):
                    break   # a word the reading calls a name, written small, carrying no name word of the cast: no name
                ids = figure_ids_for_name(" ".join(lw), figs)
                _bind(i, i + len(lw) - 1, ids, "ok" if ids else "unbekannt")
                break

    _lits = [str(x or "") for x in (literal if isinstance(literal, (list, tuple, set)) else [literal])]
    # (0) a literal name of a reading that NO figure carries and that stands in the text is an unknown person - read before the
    # cast forms, so a known form inside it ("Mara Nowak" in "Anna Mara Nowak") cannot override the reading's longer name
    _literal([n for n in _lits if _name_words(n) and not figure_ids_for_name(n, figs)])
    # (1) the multi-word forms, identical forms of several figures TOGETHER (Paket-15-Pruefung N4/N5: the first figure won)
    multi: dict[str, set[str]] = {}
    for fid, fl in forms.items():
        for form in fl:
            if " " in form:
                multi.setdefault(form, set()).add(fid)
    for form in sorted(multi, key=lambda x: -len(x.split())):
        fw, fids = form.split(), multi[form]
        for i in list(_match(fw)):
            if any(used[i:i + len(fw)]):
                continue
            ss, ee, unproven = _extent(i, i + len(fw) - 1, fids)
            if not unproven or _claimed(ss, ee, fids) or _semantic_extent(ss, ee):
                _bind(i, i + len(fw) - 1, fids, "ok")
    _literal([n for n in _lits if _name_words(n) and figure_ids_for_name(n, figs)])
    for i, w in enumerate(low):
        if used[i]:
            continue
        hit = _carriers(w)
        if hit:
            _bind(i, i, hit, "ok")
    return sorted(out, key=lambda o: o["a"])


def figures_named_in_text(text: str, figures: list[dict] | None, literal: Any = ()) -> tuple[set[str], bool]:
    """V92 Paket 11-14: which figures a short text names, by name_occurrences. (ids, unclear): the IDs named unambiguously;
    unclear when a name fits several figures, belongs to an unknown person or its extent is not proven."""
    ids: set[str] = set()
    unclear = False
    for o in name_occurrences(text, figures, literal):
        if o["state"] == "ok" and len(o["ids"]) == 1:
            ids |= o["ids"]
        else:
            unclear = True
    return ids, unclear


def identity_klaerung(occurrences: list[dict] | None, text: str, *, exclude: Any = (), allowed: Any = None,
                      base: int = 0) -> dict | None:
    """V92 Paket 16 (Paket-15-Pruefung: "Bei Zweifeln keine Bindung ... eine sichtbare Klartext-Rueckfrage in der vorhandenen
    Oberflaeche muss die korrekte Figur-ID ermitteln koennen"; AMASTER §24.7): the clarification a name the one identity reading
    leaves unbound offers - its written span in `text` and the cast figures whose names stand in it (`kandidaten` of
    name_occurrences), never more than these. None when nothing can be offered (an unknown person). Read only.
    V92 Paket 17 (Paket-16-Pruefung N3/N4, Forderung B): with its PLACE in the input ("a", "b"; `base` = offset of `text` in the
    input) - the same name written twice is asked twice, each answer binds only its place."""
    ex = {str(x) for x in (exclude or ())}
    al = None if allowed is None else {str(x) for x in allowed}
    for o in occurrences or []:
        # a proven name of one figure needs no answer. Asked: an unproven boundary ("unklar"), a name several figures carry, and a
        # full name nobody of the cast carries that still holds a cast name ("unbekannt" - "Frau Nowak", "Mara Schmidt": live
        # 05.11. the reading gave "Frau Nowak" literally; whether that is Mara Nowak only the operator can say). A name without
        # any cast name ("Peter") offers nobody and is not asked.
        if o.get("state") == "ok" and len(o.get("ids") or ()) == 1:
            continue
        cand = [c for c in (o.get("kandidaten") or []) if c not in ex and (al is None or c in al)]
        if cand:
            return {"text": str(text or "")[o["a"]:o["b"]], "a": int(base) + o["a"], "b": int(base) + o["b"], "kandidaten": cand}
    return None


def with_klaerungen(figures: list[dict] | None, klaerungen: Any, text: str | None = None) -> list[dict]:
    """V92 Paket 16 (Paket-15-Pruefung: "eine sichtbare Klartext-Rueckfrage in der vorhandenen Oberflaeche muss die korrekte
    Figur-ID ermitteln koennen"): the operator's answers to the identity clarification of THIS input - [{"text": written span,
    "id": figure ID or null, "a"/"b": its place in the input}] - as a read projection of the cast (like with_session_aliases):
    the answer becomes the figure's `klaerung` for this request only. Only figures of the given cast can be chosen; "null"
    (= nobody of the cast) adds nothing. Never stored. No word list.
    V92 Paket 17 (Paket-16-Pruefung N1-N4): with `text` (the input) the answers are placed at once (place_klaerungen: the place
    must exist, the chosen figure must be one the place offers); the binders place them again in their own input. The routes
    pass only answers they validated against the question they issued (app: _klaerungen_pruefen)."""
    by: dict[str, list[dict]] = {}
    for k in (klaerungen if isinstance(klaerungen, list) else [])[:8]:
        if not isinstance(k, dict):
            continue
        t, fid = str(k.get("text") or "").strip()[:80], str(k.get("id") or "").strip()
        if t and fid:
            c = {"text": t, **({"a": k["a"], "b": k["b"]} if type(k.get("a")) is int and type(k.get("b")) is int else {})}
            by.setdefault(fid, []).append(c)
    if not by:
        return list(figures or [])
    out = [({**f, "klaerung": list(f.get("klaerung") or []) + by[str(f.get("id") or "")]})
           if isinstance(f, dict) and str(f.get("id") or "") in by else f for f in (figures or [])]
    return place_klaerungen(text, out) if text is not None else out


def identity_questions(ambiguous: Any, decision: Any, klaerungen: Any, figures: list[dict] | None, present_ids: Any = None) -> list[dict]:
    """V92 Paket 16: the open identity clarifications of an input - from the binder's records (`klaerung`) and the addressee
    decision (resolve_target_detail) - that the operator has not answered yet. Each: {"text": the written span, "a"/"b": its
    place in the input, "kandidaten": [{"id", "name"}]} - only figures of the cast. The routes ask these BEFORE anything is
    stored (422 IDENTITAET_KLAEREN); an answered place (a figure or "nobody") is never asked again. With `present_ids` each
    candidate says whether it is in the scene ("anwesend") - two figures of the same name stay distinguishable. Read only.
    V92 Paket 17 (Paket-16-Pruefung N2/N3): ONE question per written PLACE (the same name at two places = two questions; two
    readers asking about the same place = one question). A place counts as answered only by an answer for exactly that place
    (an answer without a place: only when no other open question has its words) whose choice the question offers - a figure
    among its candidates or "nobody"; an answer naming a figure the question does not offer answers nothing."""
    names = {str(f.get("id")): str(f.get("name") or f.get("id")) for f in (figures or []) if isinstance(f, dict) and f.get("id")}
    pres = None if present_ids is None else {str(x) for x in present_ids}
    items = [a.get("klaerung") for a in (ambiguous if isinstance(ambiguous, list) else []) if isinstance(a, dict)]
    items.append((decision or {}).get("klaerung") if isinstance(decision, dict) else None)
    qs: list[dict] = []
    seen: set[Any] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        w = _name_words(it.get("text"))
        cand = [{"id": c, "name": names[c], **({"anwesend": c in pres} if pres is not None else {})}
                for c in (it.get("kandidaten") or []) if c in names]
        a, b = it.get("a"), it.get("b")
        key = (a, b) if type(a) is int and type(b) is int else w
        if not w or key in seen or not cand:
            continue
        seen.add(key)
        qs.append({"text": str(it.get("text") or "")[:80], **({"a": a, "b": b} if type(a) is int and type(b) is int else {}),
                   "kandidaten": cand, "_w": w})
    answers = [k for k in (klaerungen if isinstance(klaerungen, list) else []) if isinstance(k, dict) and _name_words(k.get("text"))]

    def _answered(q: dict) -> bool:
        offered = {c["id"] for c in q["kandidaten"]}
        for k in answers:
            fid = str(k.get("id") or "").strip()
            if fid and fid not in offered:
                continue   # a figure this question does not offer answers nothing (Paket-16-Pruefung N1/N2)
            if type(k.get("a")) is int and type(k.get("b")) is int:
                if "a" in q and (k["a"], k["b"]) == (q["a"], q["b"]):
                    return True
            elif _name_words(k.get("text")) == q["_w"] and sum(1 for x in qs if x["_w"] == q["_w"]) == 1:
                return True
        return False

    return [{k: v for k, v in q.items() if k != "_w"} for q in qs if not _answered(q)]


def identity_question_text(questions: list[dict]) -> str:
    """V92 Paket 16: the plain-language question of the clarification (one line per written span)."""
    return " ".join(f"Wer ist mit „{q['text']}“ gemeint?" for q in questions or [])


def unresolved_names(occurrences: list[dict]) -> list[dict]:
    """V92 Paket 14: the occurrences naming an unknown person or a name of unproven extent (not: a name of several figures)."""
    return [o for o in occurrences or [] if o.get("state") in ("unbekannt", "unklar")]


def role_witnessed(occurrences: list[dict], name: Any, figure_id: str, start: int | None = None) -> bool:
    """V92 Paket 14 (Paket-13-Pruefung): a role (doer, speaker) is witnessed by the text when the blind reading's LITERAL name stands
    in the text with its full extent and binds exactly this figure - or the reading gives the first person ("ich") of the input -
    or the clause OPENS (`start`, its first word) with a name of full extent that binds exactly this figure (the opening name is
    the doer/speaker of a German statement). A shortened name ("Johann" in "Johann Weber"), a name not in the text, "figur"
    without such an opening name: not witnessed."""
    w = _name_words(name)
    if w == "ich":
        return True
    occ = [o for o in occurrences or [] if o.get("state") == "ok" and o.get("ids") == {str(figure_id)}]
    return any((w and o.get("words") == w) or (start is not None and o.get("a") == start) for o in occ)


def clause_start(raw: str, a: int, other_spans: list) -> int:
    """V92 Paket 14/15: `a` moved backwards over the directly adjacent words of the same clause - blanks or a joining hyphen
    ("Johann Bruckner-" before "Weber sagt:"), no other punctuation, not into another component. Form only."""
    prev = max([e for _s, e in (other_spans or []) if e <= a] or [0])
    while True:
        m = re.search(r"(\w+)(?:\s+|[-\u2010\u2011])$", raw[prev:a])
        if not m:
            break
        a = prev + m.start(1)
    return a


def clause_end(raw: str, b: int, other_spans: list) -> int:
    """V92 Paket 15 (Paket-14-Pruefung: the whole name must be read before it binds): `b` moved forwards over the directly adjacent
    words of the same clause - blanks or a joining hyphen ("Mara Nowak" + "-Schmidt"), no other punctuation, not into another
    component. Form only."""
    nxt = min([s for s, _e in (other_spans or []) if s >= b] or [len(raw)])
    while True:
        m = re.match(r"(?:\s+|[-\u2010\u2011])(\w+)", raw[b:nxt])
        if not m:
            break
        b += m.end()
    return b


def act_clause_span(raw: str, span: tuple[int, int], other_spans: list) -> int:
    """V92 Paket 14: start of the WHOLE clause of an act component - its segment start, moved backwards over the directly adjacent
    words of the same clause (clause_start). Form only."""
    return clause_start(raw, span[0], other_spans)


def opening_name(text: str, occurrences: list[dict]) -> dict | None:
    """V92 Paket 14: the name occurrence that OPENS the clause in subject position - it starts at the first word and is followed
    by a further word without punctuation in between (a vocative "Mara, ..." is no subject). None otherwise. Form only."""
    t = str(text or "")
    first = re.search(r"\w", t)
    if not first:
        return None
    o = next((x for x in occurrences or [] if x.get("a") == first.start()), None)
    if o is None or not re.match(r"\s+\w", t[o["b"]:]):
        return None
    return o


def _opens_with_ich(text: str) -> bool:
    """V92 Paket 14: the clause opens with the first person - the contract word "ich" component_party already binds to the
    figure itself (not a new word list)."""
    m = re.search(r"\w+", str(text or ""))
    return bool(m) and m.group(0).casefold() == "ich"


def names_accounted(unresolved: list[dict], name: Any, start: int) -> bool:
    """V92 Paket 14: every unknown/unclear name is accounted for by the OTHER role of the blind reading (target of an act, addressee
    of a speech): the reading names exactly this unknown full name literally (state "unbekannt", not a shortened part), and it
    does not open the clause (the opening name is the doer/speaker in a German statement). Otherwise the doer/speaker stays
    unproven (fail-closed)."""
    w = _name_words(name)
    return bool(w) and all(o.get("state") == "unbekannt" and o.get("words") == w and o.get("a", 0) > start for o in unresolved or [])


def resolve_regie_actor_target(
    *,
    actor_id: str | None,
    target_id: str | None,
    text: str,
    figures: list[dict] | None = None,
) -> tuple[str, str | None]:
    """AUTHORITY stays regie. Actor is the directed figure, never the label 'regie' when a figure is known."""
    actor = None if _is_regie_label(actor_id) else actor_id
    target = target_id or None
    lead = _LEAD_NAME_RE.search(text or "")
    if not actor and lead:
        hit = _match_figure(lead.group("name"), figures)
        if hit:
            actor = hit.get("id")
    zu = _ZU_NAME_RE.search(text or "")
    parsed_target = None
    if zu:
        hit = _match_figure(zu.group("name"), figures)
        if hit:
            parsed_target = hit.get("id")
            if parsed_target != actor:
                target = parsed_target
    # V89 / AMASTER 27.5, 46.2: missing actor must not turn the target
    # into the acting figure. The existing component binder may still bind
    # a distinctly named actor from a validated semantic reading.
    if actor and target == actor and parsed_target and parsed_target != actor:
        target = parsed_target
    return actor or (actor_id or "regie"), target


def _split_star_marker(raw: str) -> tuple[str | None, str | None]:
    """B.20: gemeinsame *action*-Extraktion.

    Liefert (speech_ohne_marker, action_text). Beide können None sein.
    Wird von split_star_action UND parse_regie_components genutzt.
    """
    if not raw:
        return None, None
    star = _ACTION_STAR_RE.search(raw)
    if not star:
        return None, None
    action = (star.group("action") or "").strip() or None
    speech = _ACTION_STAR_RE.sub("", raw).strip() or None
    return speech, action


def split_star_action(text: str) -> tuple[str | None, str | None]:
    """Keep remaining speech when a *action* marker is present. Does not invent facts."""
    raw = text or ""
    # B.20: gemeinsame Marker-Extraktion.
    speech, action = _split_star_marker(raw)
    if action is not None:
        return speech, action
    t = raw.strip()
    if not t:
        return None, None
    # V59C (AMASTER §24.6, §68 Nr. 54): a word list may not turn spoken text
    # into an action. Only the explicit marker or the validated semantic
    # component reading separates an action from speech.
    return t, None


def parse_regie_components(text: str) -> tuple[str | None, str | None]:
    speech = None
    action = None
    m = _SPEECH_COLON_RE.search(text or "")
    if m:
        speech = (m.group("speech") or "").strip()
        # B.20: gemeinsame Marker-Extraktion statt zweiter _ACTION_STAR_RE.search.
        speech_no_marker, marker_action = _split_star_marker(speech)
        if marker_action is not None:
            action = marker_action
            speech = speech_no_marker
        speech = speech or None
    else:
        # B.20: gemeinsame Marker-Extraktion statt zweiter _ACTION_STAR_RE.search.
        _, action = _split_star_marker(text or "")
    return speech, action


def bind_turn_truth(
    *,
    user_id: str,
    world_id: str,
    session_id: str,
    role: str,
    speaker_id: str | None,
    avatar_id: str | None,
    target_id: str | None,
    authority: str,
    present_ids: list[str],
    input_kind: str,
    text: str,
    source_turn_id: str | None = None,
    hears_ids: list[str] | None = None,
    sees_ids: list[str] | None = None,
    informed_ids: list[str] | None = None,
    affected_ids: list[str] | None = None,
    scene_id: str | None = None,
    time_ref: str | None = None,
    upload_ref: str | None = None,
    input_actor_id: str | None = None,
    response_speaker_id: str | None = None,
    puppet_id: str | None = None,
    speak_as: str | None = None,
    operator_id: str | None = None,
    **_extra: Any,
) -> dict:
    if not user_id or not world_id or not session_id:
        raise ValueError("TurnTruth requires user_id, world_id, session_id")
    if role == "teilnehmer" and authority == "avatar":
        authority = "teilnehmer"
    present = list(present_ids or [])
    # Presence is not hearing and not seeing. Explicit empty stays empty.
    # Callers that want SceneState default must pass hears from _scene_perception
    # (bind_from_session / Flask prepare). Unspecified here stays empty, never present.
    hears = list(hears_ids) if hears_ids is not None else []
    sees = list(sees_ids) if sees_ids is not None else []
    bound = {
        "id": uid("tt"),
        "user_id": user_id,
        "world_id": world_id,
        "session_id": session_id,
        "source_turn_id": source_turn_id,
        "role": role,
        "speaker_id": speaker_id,
        "avatar_id": avatar_id,
        "target_id": target_id,
        "authority": authority,
        "present_ids": present,
        "hears_ids": hears,
        "sees_ids": sees,
        "informed_ids": list(informed_ids or []),
        "affected_ids": list(affected_ids) if affected_ids is not None else ([target_id] if target_id else []),
        "input_kind": input_kind,
        "text": text,
        "scene_id": scene_id,
        "time_ref": time_ref,
        "upload_ref": upload_ref,
        "operator_id": operator_id or user_id,
        "speak_as": speak_as or "",
        "puppet_id": puppet_id,
        "response_speaker_id": response_speaker_id or speaker_id,
    }
    bound["input_actor_id"] = input_actor_id or default_input_actor_id(bound)
    return bound


def attach_turn_truth(session: dict, truth: dict) -> None:
    """Keep bound TurnTruth on the session so the existing SQL child writer can persist it.

    AMASTER §4/§6: TurnTruth is a canonical layer, not only an in-memory bind.
    """
    if not isinstance(session, dict) or not isinstance(truth, dict):
        return
    tid = str(truth.get("id") or "").strip()
    if not tid:
        return
    bucket = session.get("turnTruths")
    if not isinstance(bucket, list):
        bucket = []
        session["turnTruths"] = bucket
    if any(isinstance(x, dict) and str(x.get("id") or "") == tid for x in bucket):
        return
    bucket.append(copy.deepcopy(truth))


def default_input_actor_id(truth: dict) -> str:
    """Who produced truth.text. Never the planned NPC response speaker by default."""
    explicit = truth.get("input_actor_id") or truth.get("inputActorId")
    if explicit:
        return str(explicit)
    speak_as = str(truth.get("speak_as") or truth.get("speakAs") or "").lower()
    role = str(truth.get("role") or "")
    kind = str(truth.get("input_kind") or truth.get("inputKind") or "")
    speaker_id = truth.get("speaker_id") or truth.get("speakerId")
    avatar_id = truth.get("avatar_id") if "avatar_id" in truth else truth.get("avatarId")
    puppet_id = truth.get("puppet_id") or truth.get("puppetId")
    authority = str(truth.get("authority") or "")
    if kind in ("autochat",) or role == "character":
        return str(speaker_id or "")
    if kind == "puppet" or role == "puppet" or speak_as == "puppet":
        return str(puppet_id or speaker_id or "")
    if role in ("beobachter",) or authority == "observer" or speak_as == "observer" or kind in ("comment", "observer"):
        return "observer"
    if speak_as in ("operator", "user", "bedienperson"):
        return "user"
    if speak_as == "avatar" or role == "avatar":
        return str(avatar_id or "user")
    if role == "teilnehmer":
        return str(avatar_id or "user")
    if kind in ("speech", "user"):
        return str(avatar_id or "user")
    return str(speaker_id or avatar_id or "user")


def extract_time_window(text: str | None, session: dict | None = None) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    bound = bind_time(session or {}, relative=raw)
    if bound.get("ambiguous"):
        return None
    window = bound.get("window")
    return str(window) if window else None


def _perception_override(scene: dict, key: str, present: list[str]) -> list[str] | None:
    """Return an explicit user override, or None for derived perception.

    V3 distinguishes a real user selection from the historic derived default.
    New writes carry ``hearsExplicit``/``seesExplicit``. For legacy sessions
    without a marker, a list identical to the then-current presence is treated
    as the old frozen default; a subset/empty list remains an explicit legacy
    restriction.
    """
    marker = "hearsExplicit" if key == "hearsIds" else "seesExplicit"
    legacy_key = "hears_ids" if key == "hearsIds" else "sees_ids"
    if marker in scene:
        if scene.get(marker) is not True:
            return None
        raw = scene.get(key) if key in scene else scene.get(legacy_key)
        return [str(x) for x in (raw or []) if x]
    if key not in scene and legacy_key not in scene:
        return None
    raw = scene.get(key) if key in scene else scene.get(legacy_key)
    ids = [str(x) for x in (raw or []) if x]
    # Historical createSession/sync_scene_state persisted exactly the current
    # presence as if it were a user whitelist. That shape is a derived default.
    if ids == [str(x) for x in present if x]:
        return None
    return ids


def _scene_perception(session: dict, present: list[str]) -> tuple[list[str], list[str]]:
    scene = session.get("scene") or {}
    runtimes = session.get("runtimes") or {}
    place = scene.get("placeName")
    hears_src = _perception_override(scene, "hearsIds", present)
    sees_src = _perception_override(scene, "seesIds", present)

    def _filter(ids: list[str] | None, hear: bool) -> list[str]:
        candidates = ids if ids is not None else present
        out = []
        for cid in candidates:
            if cid not in present:
                continue
            rt = runtimes.get(cid) or {}
            if place and rt.get("position") and rt.get("position") != place:
                continue
            flag = rt.get("canHear" if hear else "canSee")
            if flag is False:
                continue
            if hear and rt.get("gagged") and rt.get("canHear") is False:
                continue
            consciousness = rt.get("consciousness")
            try:
                if float(1 if consciousness is None else consciousness) <= 0:
                    continue
            except (TypeError, ValueError):
                pass
            out.append(cid)
        return out

    return _filter(hears_src if hears_src is not None else None, True), _filter(
        sees_src if sees_src is not None else None, False
    )


def _effective_hears(session: dict, truth: dict) -> list[str]:
    """Explicit hearers win. Empty list stays empty. Unspecified binds from SceneState, never from mere presence."""
    hears = truth.get("hears_ids")
    if hears is not None:
        return list(hears)
    present = list(truth.get("present_ids") or (session.get("scene") or {}).get("presentIds") or [])
    derived, _ = _scene_perception(session, present)
    return derived


def _effective_sees(session: dict, truth: dict) -> list[str]:
    sees = truth.get("sees_ids")
    if sees is not None:
        return list(sees)
    present = list(truth.get("present_ids") or (session.get("scene") or {}).get("presentIds") or [])
    _, derived = _scene_perception(session, present)
    return derived


def bind_from_session(
    session: dict,
    *,
    role: str,
    authority: str,
    speaker_id: str | None,
    target_id: str | None,
    input_kind: str,
    text: str,
    input_actor_id: str | None = None,
    speak_as: str | None = None,
    puppet_id: str | None = None,
) -> dict:
    scene = session.get("scene") or {}
    present = list(scene.get("presentIds") or [])
    hears, sees = _scene_perception(session, present)
    return bind_turn_truth(
        user_id=session.get("userId") or "",
        world_id=session.get("worldId") or "",
        session_id=session.get("id") or "",
        role=role,
        speaker_id=speaker_id,
        avatar_id=session.get("avatarId"),
        target_id=target_id,
        authority=authority,
        present_ids=present,
        input_kind=input_kind,
        text=text,
        hears_ids=hears,
        sees_ids=sees,
        scene_id=scene.get("placeId") or scene.get("id"),
        time_ref=scene.get("time"),
        upload_ref=(session.get("focus") or {}).get("uploadId"),
        input_actor_id=input_actor_id,
        speak_as=speak_as,
        puppet_id=puppet_id,
        operator_id=session.get("userId") or "",
        response_speaker_id=speaker_id if input_kind in ("autochat", "puppet") or role in ("character", "puppet") else None,
    )


def match_triggers_as_cues(text: str, session: dict, rules: list[dict]) -> list[dict]:
    """Keyword hits are non-canonical cues, never scene truth."""
    n = (text or "").lower()
    cues = []
    for r in rules:
        if not r.get("active"):
            continue
        if r.get("worldId") and r["worldId"] != session.get("worldId"):
            continue
        if r.get("sessionId") and r["sessionId"] != session.get("id"):
            continue
        match = (r.get("match") or "").lower()
        if match and match in n:
            cues.append({"match": r.get("match"), "effectText": r.get("effectText"), "canonical": False})
    return cues


def apply_fire_preview(runtime: dict, fired: list[dict]) -> dict:
    """Lens only — must not be persisted as owner before commit."""
    rt = copy.deepcopy(runtime) if isinstance(runtime, dict) else {}
    if rt.get("activeCause") and str(rt.get("emotion") or "") not in ("", "wach", "calm"):
        return rt
    space_emotion = {
        "Bedrohung": "Angst",
        "Angst": "Angst",
        "Gewalt": "Wut",
        "Verrat": "Misstrauen",
        "Verlust": "Trauer",
        "Eifersucht": "Eifersucht",
        "Lust": "Nähe",
        "Schutz": "Sorge",
        "Moral": "Scham",
    }
    for row in fired or []:
        if not isinstance(row, dict):
            continue
        emo = space_emotion.get(str(row.get("space") or ""))
        if not emo:
            continue
        rt["emotion"] = emo
        act = float(row.get("activation") or 0)
        rt["intensity"] = max(float(rt.get("intensity") or 0.35), min(1.0, act))
        if emo == "Angst":
            rt["fear"] = max(float(rt.get("fear") or 0), min(1.0, 0.2 + act * 0.5))
        if emo == "Wut":
            rt["anger"] = max(float(rt.get("anger") or 0), min(1.0, 0.2 + act * 0.5))
        if emo == "Scham":
            rt["shame"] = max(float(rt.get("shame") or 0), min(1.0, 0.2 + act * 0.4))
        break
    return rt


def infer_speech_act(text: str) -> str:
    raw = text or ""
    low = raw.lower().strip()
    if "?" in raw or _QUESTION_RE.search(low) or _CHECKIN_RE.search(low):
        return "ask"
    if _REFUSE_RE.search(low) or _REFUSE_MORE_RE.search(low):
        return "refuse"
    if _REQUEST_RE.search(low):
        return "ask"
    if _ACCEPT_RE.search(low):
        return "accept"
    return "assert"


def infer_lifecycle_kind(text: str | None) -> str | None:
    raw = (text or "").strip().lower()
    if not raw:
        return None
    # Request utterances already create the proposition; do not map them to lifecycle.
    if infer_speech_act(text or "") == "ask":
        return None
    compact = re.sub(r"[.!?…]+$", "", raw).strip()
    if "?" in (text or "") or _CHECKIN_RE.search(compact):
        return None
    if (
        compact in ("ja", "ok", "okay", "einverstanden", "geht klar", "mache ich", "in ordnung", "klar", "sicher", "mach ich")
        or compact.startswith("ja ")
        or compact.startswith("ja,")
        or compact.startswith("einverstanden")
        or _ACCEPT_RE.search(compact)
    ):
        return "acceptance"
    if (
        compact in ("nein",)
        or compact.startswith("nein")
        or "lehne" in compact
        or _REFUSE_MORE_RE.search(compact)
        or _REFUSE_RE.search(compact)
    ):
        return "refusal"
    if "widerruf" in compact:
        return "revoke"
    if "widerspruch" in compact or "widerspreche" in compact:
        return "refusal"
    if "erfüllt" in compact or "habe gemacht" in compact or "ist erledigt" in compact:
        return "fulfill"
    return None


def make_fact(**kwargs) -> dict:
    truth = kwargs.get("truth") or {}
    scene = kwargs.get("scene") or {}
    kind = kwargs["kind"]
    text = kwargs.get("text", "")
    event_kind = kwargs.get("event_kind") or kind
    speech_act = kwargs.get("speech_act")
    if event_kind == "speech" and not speech_act:
        speech_act = infer_speech_act(text)
    if event_kind in ("action", "physical"):
        speech_act = speech_act if speech_act not in (None, "") else None
    # V70 (Audit10 §2): the validation flag is a bool - anything but True is no validation (fail-closed, never None)
    validated = kwargs.get("validated", True) is True
    source_turn_id = (
        kwargs.get("sourceTurnId")
        or kwargs.get("source_turn_id")
        or truth.get("id")
        or truth.get("source_turn_id")
    )
    actor_id = kwargs.get("actorId", "")
    target_id = kwargs.get("targetId")
    if "witnessedBy" in kwargs:
        witnessed = list(kwargs.get("witnessedBy") or [])
    else:
        hears = truth.get("hears_ids")
        if hears is not None:
            witnessed = list(hears)
        else:
            # Presence is not hearing. Unspecified perception stays empty.
            witnessed = []
    affected = list(kwargs.get("affected_ids") or ([target_id] if target_id else []))
    place_id = kwargs.get("placeId") or scene.get("placeId")
    time_val = kwargs.get("time") or scene.get("time")
    dup = kwargs.get("duplicate_key") or "|".join(
        str(x) for x in (source_turn_id, event_kind, actor_id, text[:80]) if x is not None
    )
    return {
        "id": kwargs.get("id") or uid("fact"),
        "turn": kwargs.get("turn", 0),
        "user_id": kwargs.get("user_id") or truth.get("user_id") or "",
        "world_id": kwargs.get("world_id") or truth.get("world_id") or "",
        "session_id": kwargs.get("session_id") or truth.get("session_id") or "",
        "scene_id": kwargs.get("scene_id") or place_id,
        "placeId": place_id,
        "actorId": actor_id,
        "targetId": target_id,
        "affected_ids": affected,
        "kind": kind,
        "event_kind": event_kind,
        "speech_act": speech_act,
        "text": text,
        "summary": kwargs.get("summary") or (text[:180] if text else ""),
        "payload": kwargs.get("payload") or {"text": text, "kind": kind},
        "authority": kwargs.get("authority", "character"),
        "source_turn_id": source_turn_id,
        "sourceTurnId": source_turn_id,
        "source_type": kwargs.get("source_type") or truth.get("input_kind") or "turn",
        "validated": validated,
        "status": kwargs.get("status") or ("canon" if validated else "unvalidated"),
        "validation": kwargs.get("validation")
        or {"ok": validated, "reason": kwargs.get("rejection_reason")},
        "provenance": kwargs.get("provenance", "kernel"),
        "witnessedBy": witnessed,
        "time": time_val,
        "temporal_scope": kwargs.get("temporal_scope") or "turn",
        "duplicate_key": dup,
        "proposition_id": kwargs.get("proposition_id"),
        "goal_id": kwargs.get("goal_id"),
        "responds_to_fact_id": kwargs.get("responds_to_fact_id"),
        # V65Z (A01, §34.2 Kausalprovenienz): the cause of a derived fact, as a SceneFact id (never as Quellturn)
        **({"cause_fact_id": kwargs["cause_fact_id"]} if kwargs.get("cause_fact_id") else {}),
        # V70 (found by the V25 chain test on its rebuilt fixture; AMASTER §34.2, V66 "a cause from an upload hands on its
        # upload"): fact_provenance hands on the upload of a cause - make_fact dropped it, so every fact derived from an upload
        # (a witness's knowledge effect) had no source and the ingest was refused (422 FACT_SOURCE_UNBOUND)
        **({"sourceUploadId": kwargs["sourceUploadId"]} if kwargs.get("sourceUploadId") else {}),
        "rejection_reason": kwargs.get("rejection_reason"),
        # R3.4 / B.7-Folge: Time-Kontext persistiert auf Fact.
        # Damit spätere Drift-Suppress / Compass-Reaktion / finalizer
        # wissen, ob der Fact in der Vergangenheit oder Gegenwart liegt.
        "time_tense": kwargs.get("time_tense"),
        "time_ambiguous": kwargs.get("time_ambiguous", False),
    }


def fact_provenance(session: dict, cause: Any) -> dict:
    """V65Z (SPS-Audit V65Y A01; AMASTER §34 Quellturn, §34.1 "Alle Komponenten desselben Outputs tragen dieselbe
    source_turn_id", §34.2 Kausalprovenienz): the provenance of a row DERIVED from `cause` (knowledge effect, body state,
    synapse, lifecycle): a TurnTruth of the session is its Quellturn; a SceneFact is its cause (cause_fact_id) and that
    fact's own Quellturn is the derived row's Quellturn. Before, the kernel wrote the cause FACT id as sourceTurnId (22 such
    rows in your DB). Nothing is guessed: an unknown id stays the cause only. Read only."""
    c = str(cause or "")
    if not c:
        return {}
    tts = {str(t.get("id")) for t in session.get("turnTruths") or [] if isinstance(t, dict) and t.get("id")}
    if c in tts:
        return {"sourceTurnId": c}
    f = next((x for x in session.get("facts") or [] if isinstance(x, dict) and str(x.get("id") or "") == c), None)
    tt = str((f or {}).get("sourceTurnId") or (f or {}).get("source_turn_id") or "")
    # V66 (Audit5 E04; AMASTER §34.2 Kausalprovenienz): a cause from an upload hands on its upload, as a Quellturn is handed on
    up = str((f or {}).get("sourceUploadId") or (f or {}).get("source_upload_id") or "")
    return {"cause_fact_id": c, **({"sourceTurnId": tt} if tt in tts else {}), **({"sourceUploadId": up} if up else {})}


def make_memory(**kwargs) -> dict:
    if "truthStatus" not in kwargs:
        kwargs["truthStatus"] = "canon"
    kwargs.setdefault("id", uid("mem"))
    kwargs.setdefault("layer", "session")
    kwargs.setdefault("witnesses", [])
    kwargs.setdefault("salience", 0.5)
    kwargs.setdefault("source", kwargs.get("source") or "kernel")
    kwargs.setdefault("epistemic", kwargs.get("kind") or "erlebt")
    return kwargs


def capability_blocks_action(runtime: dict, action: str | None) -> bool:
    if not action:
        return False
    text = str(action)
    consciousness = float(runtime.get("consciousness") if runtime.get("consciousness") is not None else 1)
    mobility = float(runtime.get("mobility") if runtime.get("mobility") is not None else 1)
    if consciousness < 0.5:
        return True
    physical = bool(
        _MOVE_RE.search(text)
        or _CAPABILITY_RE.search(text)
        or _STRIKE_RE.search(text)
        or _RESTRAIN_RE.search(text)
        or _FREE_RE.search(text)
    )
    if runtime.get("canMove") is False and physical:
        return True
    if mobility < 0.3 and physical:
        return True
    if runtime.get("restrained") and _CAPABILITY_RE.search(text):
        return True
    if runtime.get("gagged") and re.search(r"spricht|redet|schreit|ruft", text, re.I):
        return True
    if runtime.get("handsFree") is False and _STRIKE_RE.search(text):
        return True
    if runtime.get("breathing") is not None and float(runtime.get("breathing") or 1) <= 0:
        return True
    if runtime.get("balance") is not None and float(runtime.get("balance") or 1) < 0.3 and _MOVE_RE.search(text):
        return True
    if runtime.get("canSee") is False and re.search(r"sieht|schaut|blickt|schaut nach", text, re.I):
        return True
    return False


def split_output_components(truth: dict, result: dict, speaker: dict) -> list[dict]:
    """Separate event_kind/speech_act. LLM proposals and Fate are not owners."""
    proposed = result.get("components")
    if isinstance(proposed, list) and proposed:
        out = []
        for p in proposed:
            if not isinstance(p, dict):
                continue
            kind = str(p.get("kind") or p.get("event_kind") or "speech").lower()
            # V2/Bruch 17: normal figure output has a closed component kind
            # set. God/Regie/Puppet keep their dedicated routes.
            if kind not in ("speech", "action", "physical"):
                continue
            ek_raw = str(p.get("event_kind") or kind).lower()
            if kind == "speech":
                ek = "speech"
            elif ek_raw in ("action", "physical"):
                ek = ek_raw
            else:
                ek = kind
            sa = p.get("speech_act")
            if ek in ("action", "physical"):
                sa = None
            elif not sa:
                sa = infer_speech_act(p.get("text") or "")
            out.append(
                {
                    "kind": kind,
                    "event_kind": ek,
                    "speech_act": sa,
                    "text": p.get("text") or "",
                    # Component actor identity is server-bound to the selected
                    # canonical figure speaker. LLM/client actorId is ignored.
                    "actorId": speaker.get("id"),
                    "targetId": p["targetId"] if "targetId" in p else truth.get("target_id"),
                }
            )
        if out:
            return out
    speech_text = str(result.get("speech") or "")
    action_text = result.get("action")
    leftover, starred = split_star_action(speech_text)
    # V65D (AMASTER §34.1 Rede und Handlung sind getrennte Komponenten; V56
    # "*…*" ist die ausdrückliche Handlungsmarke): a "*…*" segment in the
    # figure's speech describes her own act. Before, it stayed in the speech
    # whenever the action field was also set — measured 28.10. (Gasthaus wie
    # 171, M10-Lauf A) 3 of 13 replies: "*Ich küsse ihn sanft auf die Lippen.*"
    # was committed as heard WORDS and shown twice. The marked segment is now
    # always taken out of the speech; the action field stays the committed act.
    marker_stripped = bool(starred)
    if starred:
        speech_text = leftover or ""
        if not action_text:
            action_text = starred
    comps = [
        {
            "kind": "speech",
            "event_kind": "speech",
            "speech_act": infer_speech_act(speech_text),
            "text": speech_text,
            "actorId": speaker.get("id"),
            "targetId": truth.get("target_id"),
            "markerStripped": marker_stripped,
        }
    ]
    if action_text:
        comps.append(
            {
                "kind": "action",
                "event_kind": "action",
                "speech_act": None,
                "text": action_text,
                "actorId": speaker.get("id"),
                "targetId": truth.get("target_id"),
            }
        )
    return comps


def validate_component(comp: dict, runtime: dict) -> dict:
    out = dict(comp)
    if out.get("event_kind") in ("action", "physical") and capability_blocks_action(runtime, out.get("text")):
        out["validated"] = False
        out["rejection_reason"] = "capability"
        return out
    if out.get("event_kind") in ("action", "physical") and out.get("speech_act"):
        out["speech_act"] = None
    out["validated"] = True
    return out


def commit_session_change(
    session: dict,
    *,
    world: dict | None = None,
    source_turn_id: str | None = None,
    relative: str | None = None,
    sync_state: bool = True,
    sync_scene: bool = True,
) -> dict:
    """R3.1 / B.32: Gemeinsamer Helper für Session-Mutationen.

    Setzt s["time"], s["currentState"] und ruft sync_scene_state.
    9 Funktionen (commit_turn, apply_regie, apply_god, commit_puppet,
    apply_proposition + 4 sub-pfade) riefen vorher dasselbe 3-Zeilen-
    Pattern auf. Mit diesem Helper ist es 1 Zeile.

    Args:
        session: Die Session (in-place modifiziert).
        world: Welt-Dict (optional) für bounds/foreground-Berechnung.
        source_turn_id: turn_id für Time-Bindung.
        relative: Relativer Time-String (z. B. Speech-Text).
        sync_state: Wenn False, currentState nicht neu berechnen.
        sync_scene: Wenn False, sync_scene_state nicht aufrufen.

    Returns:
        session (für chaining).
    """
    # Time-Bind (mit allen unterstützten Parametern)
    if relative is not None or source_turn_id is not None:
        session["time"] = bind_time(
            session,
            source_turn_id=source_turn_id,
            relative=relative,
        )
    else:
        # Default: nur rebinden wenn scene sich geändert hat
        session["time"] = bind_time(session)
    # Current-State neu berechnen
    if sync_state:
        session["goals"] = reduce_goal_state(session)
        session["currentState"] = reduce_current_state(session)
    # Scene-State (bounds/foreground) synchronisieren
    if sync_scene:
        sync_scene_state(session, world=world)
    return session


def _local_naive(raw: Any) -> datetime | None:
    """ISO timestamp -> local wall clock (naive). An aware value (createdAt is
    stored in UTC) is converted to the local zone of the running app (the
    user's machine); a naive value is already local."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def session_clock(session: dict) -> datetime | None:
    """V62 (AMASTER §37 Zeitebenen): reference time of the current turn. An
    explicitly bound time.real (test clock, later a story clock) wins;
    otherwise the local clock of the running app (the user's machine) — the
    same reference V61 used (datetime.now()). Root of the wrong weekday in the
    comparison run ("Mittwoch"/"Montag" on Tuesday) was NOT this clock but that
    the date was never mirrored to the figure and the planner's time was read
    by word lists (see today_view, temporal_from_fields). A frozen session date
    (first V62 draft, bound from createdAt) was rejected in review: "morgen"
    would never arrive and old sessions would live on their start date."""
    t = session.get("time") if isinstance(session.get("time"), dict) else {}
    for key in ("real", "realIso", "iso"):
        dt = _local_naive(t.get(key))
        if dt is not None:
            return dt
    return datetime.now()


_WEEKDAY_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def today_view(session: dict) -> dict | None:
    """Read-only mirror of the session date for brief and planner."""
    now = session_clock(session)
    if now is None:
        return None
    return {"weekday": _WEEKDAY_DE[now.weekday()], "date": now.strftime("%d.%m.%Y"), "iso": now.date().isoformat(),
            "text": f"{_WEEKDAY_DE[now.weekday()]}, {now.strftime('%d.%m.%Y')}"}


def bind_time(session: dict, *, source_turn_id: str | None = None, real: str | None = None, relative: str | None = None) -> dict:
    scene = session.get("scene") or {}
    prev = dict(session.get("time") or {})
    rel = relative or prev.get("relative") or ""
    low = str(rel).lower()
    real_s = real if real is not None else prev.get("real")
    parsed = _parse_real(real_s)
    days = re.findall(r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag", low)
    # B.7 (AMASTERv2 §37): erweiterte Vergangenheits-/Zukunfts-Marker.
    # Vorher nur gestern/morgen — jetzt auch vorgestern, übermorgen,
    # letzte/naechste Woche, früher/einst/bald.
    vague = bool(re.search(
        r"\b(später|spaeter|damals|irgendwann|demnachst|demnächst|"
        r"früher|frueher|einst|bald)\b",
        low,
    ))
    past_mark = bool(re.search(
        r"\b(gestern|vorgestern|damals|vorher|zuvor|früher|frueher|einst|"
        r"letzten?|vorletzten?|vergangenen?)\b",
        low,
    ))
    future_mark = bool(re.search(
        r"\b(morgen|übermorgen|uebermorgen|nächsten|naechsten|später|spaeter|"
        r"bald|in \d+|nachmittag|abend)\b",
        low,
    ))
    ambiguous = bool(len(set(days)) > 1 or (past_mark and future_mark) or (vague and days))
    window = None
    resolved = None
    tense = "unbound"
    if not ambiguous:
        if "vorgestern" in low:
            if parsed:
                resolved = (parsed - timedelta(days=2)).date().isoformat()
                window = f"vorgestern ({resolved})"
            else:
                window = "vorgestern"
            tense = "past"
        elif "gestern" in low:
            if parsed:
                resolved = (parsed - timedelta(days=1)).date().isoformat()
                window = f"gestern ({resolved})"
            else:
                window = "gestern"
            tense = "past"
        elif "übermorgen" in low or "uebermorgen" in low:
            if parsed:
                resolved = (parsed + timedelta(days=2)).date().isoformat()
                window = f"übermorgen ({resolved})"
            else:
                window = "übermorgen"
            tense = "future"
        elif "heute" in low:
            if parsed:
                resolved = parsed.date().isoformat()
                window = f"heute ({resolved})"
            else:
                window = "heute"
            tense = "present"
        elif "morgen" in low:
            if parsed:
                resolved = (parsed + timedelta(days=1)).date().isoformat()
                window = f"morgen ({resolved})"
            else:
                window = "morgen"
            tense = "future"
        elif "nächsten monat" in low or "naechsten monat" in low:
            if parsed:
                y, m = parsed.year, parsed.month + 1
                if m == 13:
                    y, m = y + 1, 1
                resolved = f"{y:04d}-{m:02d}"
                window = f"nächsten Monat ({resolved})"
            else:
                window = "nächsten Monat"
            tense = "future"
        elif days:
            key = days[0]
            nxt = "nächsten" in low or "naechsten" in low
            if parsed:
                resolved = _next_weekday(parsed, key, next_week=nxt)
                label = "nächsten" if nxt else "diesen"
                window = f"{label} {_WEEKDAYS[key]} ({resolved})"
            else:
                label = "nächsten" if nxt else "diesen"
                window = f"{label} {_WEEKDAYS[key]}"
            tense = "future" if nxt or (parsed and resolved and resolved > parsed.date().isoformat()) else "present"
        elif re.search(r"\b(später|spaeter|bald)\b", low):
            window = "später"
            tense = "future"
        elif "damals" in low or re.search(r"\b(früher|frueher|einst|letzten|letzter|letztes|vorletzten|vorletzter|vorletztes)\b", low):
            window = "damals"
            tense = "past"
    # V3 rest seam: ``relative`` is temporal state, never a transport for
    # arbitrary dialogue.  Parsing may inspect the full utterance, but only
    # the derived temporal window (or an ambiguity marker) may persist.
    parsed_window = window
    # §37 continuity: an unresolved temporal conflict is canonical state and
    # must survive later binds that carry no new temporal information.  In
    # particular, the derived marker ``mehrdeutig`` must never be reparsed as
    # if it were a fresh utterance and thereby turn into ``ambiguous=False``.
    # A subsequent *recognised* temporal expression (for example ``Samstag``
    # or ``morgen``) may bind/replace the open ambiguity; arbitrary dialogue
    # may not.  This also keeps the V3 no-dialogue-in-time contract intact.
    prior_ambiguous = bool(prev.get("ambiguous"))
    has_new_temporal_semantics = bool(parsed_window or ambiguous)
    if prior_ambiguous and not has_new_temporal_semantics:
        ambiguous = True
        window = prev.get("window")
        resolved = prev.get("resolved_date")
        tense = prev.get("tense") or "unbound"
    if not window:
        window = prev.get("window")
    if ambiguous and prior_ambiguous and not has_new_temporal_semantics:
        persisted_relative = "mehrdeutig"
    elif relative is None:
        persisted_relative = prev.get("relative")
    elif parsed_window:
        persisted_relative = parsed_window
    elif ambiguous:
        persisted_relative = "mehrdeutig"
    else:
        persisted_relative = None
    # Existing sessions from the pre-fix build can already contain a raw
    # utterance in time.relative.  Never carry that legacy payload forward:
    # if it is not one of our derived temporal values, drop it on rebind.
    if relative is None and persisted_relative and persisted_relative != prev.get("window"):
        probe = bind_time({**session, "time": {k: v for k, v in prev.items() if k != "relative"}}, relative=str(persisted_relative))
        persisted_relative = probe.get("relative")
    commit_allowed = (not ambiguous) and tense != "past"
    return {
        "world": prev.get("world") or session.get("worldTime") or scene.get("worldTime") or "unbekannt",
        "world_id": session.get("worldId") or session.get("world_id") or "",
        "session": prev.get("session") if prev.get("session") is not None else 0,
        "session_id": session.get("id") or session.get("sessionId") or "",
        "scene": scene.get("time") or prev.get("scene"),
        "turn": int(session.get("turnIndex") or 0),
        "real": real_s,
        "source_turn_id": source_turn_id,
        "window": window,
        "relative": persisted_relative,
        "ambiguous": ambiguous,
        "resolved_date": resolved,
        "tense": tense,
        "commit_allowed": commit_allowed,
    }


def _parse_real(real: str | None) -> datetime | None:
    if not real:
        return None
    s = str(real).strip().replace("Z", "")
    for fmt in (None, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            if fmt is None:
                return datetime.fromisoformat(s)
            return datetime.strptime(s[:19] if "T" in s else s[:10], fmt)
        except (TypeError, ValueError):
            continue
    return None


def _next_weekday(base: datetime, key: str, *, next_week: bool) -> str:
    order = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
    target = order.index(key)
    cur = base.weekday()
    if next_week:
        delta = (7 - cur) + target
    else:
        delta = (target - cur) % 7
    return (base + timedelta(days=delta)).date().isoformat()


_LIFECYCLE_TO_STATUS = {
    "accept": "accepted",
    "acceptance": "accepted",
    "accepted": "accepted",
    "commitment": "active",
    "refuse": "declined",
    "refusal": "declined",
    "declined": "declined",
    "fulfill": "fulfilled",
    "fulfilled": "fulfilled",
    "complete": "completed",
    "completed": "completed",
    "revoke": "revoked",
    "revoked": "revoked",
    "contradict": "contradicted",
    "contradicted": "contradicted",
    "supersede": "superseded",
    "superseded": "superseded",
    "fail": "failed",
    "failed": "failed",
    "close": "closed",
    "closed": "closed",
    "open": "open",
    "active": "active",
}


def reduce_goal_state(session: dict) -> list[dict]:
    """Read-only reduction of the existing Goal owner (AMASTER 35).

    Only typed, validated, scoped lifecycle evidence can change lifecycle.
    A source definition, a phase number, wording, a turn count or an unrelated
    experience is never a lifecycle operation. No successor is activated.
    """
    goals = [copy.deepcopy(g) for g in session.get("goals") or [] if isinstance(g, dict)]
    props = {str(p.get("id")): p for p in session.get("propositions") or [] if isinstance(p, dict)}
    scope = (("sessionId", "session_id", session.get("id")),
             ("worldId", "world_id", session.get("worldId") or session.get("world_id")),
             ("userId", "user_id", session.get("userId") or session.get("user_id")))
    # V69 (Audit9 P0-3/P0-4): the one eligibility and order rule for lifecycle evidence (scene_state.lifecycle_events)
    unklar = _scene.lifecycle_order_conflicts(session)   # V70 (Audit10 §4): see reduce_current_state
    for fact in _scene.lifecycle_events(session, ("lifecycle", "goal_state_changed")):
        if not fact.get("id"):
            continue
        if any(fact.get(a, fact.get(b)) not in (None, "", expected)
               for a, b, expected in scope if expected):
            continue
        payload = fact.get("payload") if isinstance(fact.get("payload"), dict) else {}
        operation = payload.get("lifecycle") or payload.get("to") or fact.get("event_kind")
        status = _LIFECYCLE_TO_STATUS.get(str(operation or "").lower())
        gid = fact.get("goal_id") or fact.get("goalId") or payload.get("goal_id") or payload.get("goalId")
        pid = fact.get("proposition_id") or fact.get("propositionId") or payload.get("proposition_id")
        if not status or not (gid or pid):
            continue
        actor = str(fact.get("actorId") or fact.get("actor_id") or "")
        authority = str(fact.get("authority") or "").lower()
        for goal in goals:
            goal_pid = goal.get("proposition_id") or goal.get("propositionId")
            if gid and str(goal.get("id")) != str(gid):
                continue
            if pid and str(goal_pid or "") != str(pid):
                continue
            if not gid and (not pid or str(goal_pid or "") != str(pid)):
                continue
            prop = props.get(str(pid or "")) or {}
            parties = {str(prop.get("actorId") or ""), str(prop.get("targetId") or "")} - {""}
            owner = str(goal.get("ownerId") or "")
            # Existing validator owns action authority. This reducer additionally
            # checks the referenced goal owner / proposition parties; it never
            # treats an admin button as a character's experienced achievement.
            bound_actor = bool(actor and (actor == owner or (owner in parties and actor in parties)))
            if authority not in ("god", "gott", "regie", "director") and not bound_actor:
                continue
            if authority == "operator":
                continue
            goal["status"] = status
            goal["lifecycleFactId"] = fact["id"]
            goal["lifecycleTurn"] = fact.get("turn", 0)
    for goal in goals:
        gp = str(goal.get("proposition_id") or goal.get("propositionId") or "")
        for c in unklar:
            hit = (c.get("goalId") and str(c["goalId"]) == str(goal.get("id"))) or (c.get("propositionId") and gp and str(c["propositionId"]) == gp)
            if hit and int(c.get("turn") or 0) >= int(goal.get("lifecycleTurn") or -1):
                goal["status"] = "unklar"
                goal["reihenfolgeUnbelegt"] = {"turn": c.get("turn"), "factIds": c.get("factIds")}
                goal.pop("lifecycleFactId", None)
    return goals


def reduce_current_state(session: dict) -> dict:
    """Current state from latest validated lifecycle evidence — not from wording."""
    props = list(session.get("propositions") or [])
    status_by_prop: dict[str, str] = {}
    # V69 (Audit9 P0-3 "falsche Sortierung", P0-4 "unvalidierte Evidenz"): validated lifecycle evidence only, in event order
    # (turn, position) - the same rule as reduce_goal_state; the latest one of a proposition decides
    turn_by_prop: dict[str, int] = {}
    for f in _scene.lifecycle_events(session, ("lifecycle",)):
        pid = f.get("propositionId") or f.get("proposition_id")
        payload = f.get("payload") if isinstance(f.get("payload"), dict) else {}
        if not pid:
            pid = payload.get("proposition_id")
        if not pid:
            continue
        raw = f.get("event_kind") or payload.get("lifecycle") or f.get("status")
        status_by_prop[str(pid)] = _LIFECYCLE_TO_STATUS.get(str(raw or "").lower(), str(raw or "open"))
        turn_by_prop[str(pid)] = int(f.get("turn") or 0)
    # V92 (AMASTER §36.5 Z. 1947 "an die betreffende Handlung gebunden", Z. 1974; Kettenvertrag §6): the Koerperkontakt container
    # is the BOUNDARY STANDING NOW (apply_proposition writes it so: open without a boundary). A refusal of ONE act (diese_tat) is
    # an append-only lifecycle answer bound to that act - it must not close the container for every later touch. The latest
    # lifecycle status therefore does not decide it; the one owner `scene_state.body_contact_standing` does.
    for _p in props:
        if isinstance(_p, dict) and _p.get("kind") == "koerperkontakt" and _p.get("id"):
            _now = session_clock(session)
            status_by_prop[str(_p["id"])] = (_scene.body_contact_standing(
                session, _p, at=_now.isoformat(timespec="minutes") if _now else None) or {}).get("state") or "open"
    # V70 (Audit10 §4; AMASTER §35, §6.2 Z. 262): a matter whose latest lifecycle turn holds different operations in an order
    # that is not proven (scene_state.lifecycle_order_conflicts) has no reducible current state - "unklar", visibly, never
    # the stored status or a guess from the insertion order. Later proven evidence decides again.
    unklar = {str(c["propositionId"]): c for c in _scene.lifecycle_order_conflicts(session) if c.get("propositionId")}
    reduced: list[dict] = []
    for p in props:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "")
        if pid and pid in unklar and int(unklar[pid].get("turn") or 0) >= turn_by_prop.get(pid, -1):
            p = dict(p)
            p["status"] = "unklar"
            p["reihenfolgeUnbelegt"] = {"turn": unklar[pid].get("turn"), "factIds": unklar[pid].get("factIds")}
        elif pid and pid in status_by_prop:
            p = dict(p)
            p["status"] = status_by_prop[pid]
        reduced.append(p)
    live = [p for p in reduced if p.get("status") in ("open", "active", "accepted")]
    closed = [
        p
        for p in reduced
        if p.get("status")
        in ("declined", "revoked", "fulfilled", "completed", "closed", "failed", "contradicted", "superseded")
    ]
    t = session.get("time") or bind_time(session)
    scene = session.get("scene") or {}
    return {
        "time": t,
        "placeId": scene.get("placeId"),
        "placeName": scene.get("placeName"),
        "openPropositions": live,
        "closedPropositions": [{"id": p.get("id"), "status": p.get("status")} for p in closed[-8:]],
        # V70 (Audit10 §4): matters whose state an unproven order would decide - neither open nor closed, visible
        "unklarePropositions": [{"id": p.get("id"), "status": "unklar", "reihenfolgeUnbelegt": p.get("reihenfolgeUnbelegt")}
                                for p in reduced if p.get("status") == "unklar"],
        "goals": [g for g in reduce_goal_state(session) if g.get("status") in ("open", "active", "accepted", None)],
        "turn": int(session.get("turnIndex") or 0),
    }


def sync_scene_state(session: dict, *, world: dict | None = None) -> dict:
    """Fill AMASTER §20 SceneState from evidence. Does not invent presence or perception."""
    scene = session.setdefault("scene", {})
    present = list(scene.get("presentIds") or [])
    runtimes = session.get("runtimes") or {}
    scene["actors"] = [cid for cid in present if cid]
    scene["bodyPositions"] = {
        cid: str(rt.get("position") or scene.get("placeName") or "")
        for cid, rt in runtimes.items()
        if isinstance(rt, dict)
    }
    props = list(session.get("propositions") or [])
    questions = [
        p.get("text") or ""
        for p in props
        if p.get("status") == "open" and ("?" in (p.get("text") or "") or infer_speech_act(p.get("text") or "") == "ask")
    ]
    scene["openQuestions"] = questions
    scene["openDemands"] = [
        p.get("text") or ""
        for p in props
        if p.get("status") == "open" and (p.get("text") or "") not in questions
    ]
    scene["openPromises"] = [
        p.get("text") or ""
        for p in props
        if p.get("status") in ("accepted", "active")
    ]
    goals = list(session.get("goals") or [])
    scene["goals"] = [g.get("text") or "" for g in goals if g.get("status") in ("open", "active", "accepted", None)]
    turn = int(session.get("turnIndex") or 0)
    last_facts = [f for f in (session.get("facts") or []) if f.get("turn") == turn]
    scene["ongoingActions"] = [
        f.get("text") or ""
        for f in last_facts
        if f.get("kind") in ("action", "physical") and _scene.validiert(f)
    ]
    wits: list[str] = []
    for f in last_facts:
        for wid in f.get("witnessedBy") or []:
            if wid and wid not in wits:
                wits.append(wid)
    scene["witnesses"] = wits
    rels = session.get("relations") or []
    scene["conflicts"] = [
        f"{r.get('fromId')}→{r.get('toId')}"
        for r in rels
        if float(r.get("hostility") or 0) >= 0.4 or float(r.get("fear") or 0) >= 0.5
    ]
    after = list(scene.get("aftereffects") or [])
    for f in last_facts:
        if f.get("kind") in ("physical", "action", "god") and _scene.validiert(f) and not _god_private(f):
            txt = (f.get("text") or "").strip()
            if txt and txt not in after:
                after.append(txt)
    scene["aftereffects"] = after[-8:]
    items = list(scene.get("items") or [])
    for f in session.get("facts") or []:
        if not isinstance(f, dict):
            continue
        payload = f.get("payload") if isinstance(f.get("payload"), dict) else {}
        for raw in (payload.get("item"), payload.get("object"), f.get("item")):
            if isinstance(raw, str) and raw.strip() and raw not in items:
                items.append(raw.strip())
    scene["items"] = items[-12:]
    if not scene.get("danger"):
        scene["danger"] = min(1.0, float(scene.get("tension") or 0) * 0.5 + (0.25 if scene["conflicts"] else 0))
    # B.30-Folge: bounds = aktive Tabus und Grenzen der Szene.
    #
    # Quellen (AMASTERv2 §15 "Tabus und Grenzen" + §18 "Anwesenheit"):
    # 1. Charakterprofile der present-Charaktere (personality.tabus, personality.bounds)
    # 2. Weltregeln (world.bounds, statisch)
    # 3. Runtime-Constraints (consciousness, mobility) — verhindern Aktionen
    # 4. Aktive Konflikte (relationships mit hostility > 0.4) — "Gewalt tabu"
    # 5. Regie-Constraints (last_facts mit kind='god'/'regie') — göttliche Verbote
    bounds: list[dict] = list(scene.get("bounds") or [])
    have_keys = {(b.get("kind"), b.get("source"), b.get("value") or b.get("text")) for b in bounds if isinstance(b, dict)}
    world_ref = world if isinstance(world, dict) else {}
    # 1. Charakterprofile
    for cid in present:
        ch = next((c for c in (world_ref.get("characters") or []) if isinstance(c, dict) and c.get("id") == cid), None)
        if not isinstance(ch, dict):
            continue
        pers = ch.get("personality") or {}
        if not isinstance(pers, dict):
            pers = {}
        for tabu in (pers.get("tabus") or []):
            if not isinstance(tabu, str):
                continue
            t = tabu.strip()
            if not t:
                continue
            key = ("tabu", cid, t)
            if key in have_keys:
                continue
            bounds.append({"kind": "tabu", "source": cid, "value": t, "text": t})
            have_keys.add(key)
        for bound in (pers.get("bounds") or []):
            if isinstance(bound, str):
                b_text = bound.strip()
                if b_text:
                    key = ("bound", cid, b_text)
                    if key not in have_keys:
                        bounds.append({"kind": "bound", "source": cid, "value": b_text, "text": b_text})
                        have_keys.add(key)
    # 2. Weltregeln
    for rule in (world_ref.get("bounds") or world_ref.get("rules") or []):
        if isinstance(rule, str):
            r_text = rule.strip()
            if r_text:
                key = ("world", "world", r_text)
                if key not in have_keys:
                    bounds.append({"kind": "world", "source": "world", "value": r_text, "text": r_text})
                    have_keys.add(key)
    # 3. Runtime-Constraints
    for cid in present:
        rt = runtimes.get(cid) or {}
        if not isinstance(rt, dict):
            continue
        if float(rt.get("consciousness") or 1) < 0.3:
            key = ("consciousness", cid, "<0.3")
            if key not in have_keys:
                bounds.append({
                    "kind": "consciousness",
                    "source": cid,
                    "value": f"{cid} ist nicht bei Bewusstsein",
                    "text": f"{cid} consciousness<0.3",
                })
                have_keys.add(key)
        if float(rt.get("mobility") or 1) < 0.2:
            key = ("mobility", cid, "<0.2")
            if key not in have_keys:
                bounds.append({
                    "kind": "mobility",
                    "source": cid,
                    "value": f"{cid} kann sich nicht bewegen",
                    "text": f"{cid} mobility<0.2",
                })
                have_keys.add(key)
        if rt.get("gagged") or rt.get("canSpeak") is False:
            key = ("speech", cid, "gagged")
            if key not in have_keys:
                bounds.append({
                    "kind": "speech",
                    "source": cid,
                    "value": f"{cid} kann nicht sprechen",
                    "text": f"{cid} gagged/noSpeech",
                })
                have_keys.add(key)
    # 4. Konflikte
    for r in rels:
        if not isinstance(r, dict):
            continue
        if float(r.get("hostility") or 0) >= 0.4:
            pair = f"{r.get('fromId')}→{r.get('toId')}"
            key = ("conflict", pair, "hostility")
            if key not in have_keys:
                bounds.append({
                    "kind": "conflict",
                    "source": pair,
                    "value": f"Konflikt: {pair} (hostility>0.4)",
                    "text": f"Konflikt {pair}",
                })
                have_keys.add(key)
    # 5. Regie/Gott — gewaltsame Tabus aus autoritativen Eingriffen
    for f in last_facts:
        if not isinstance(f, dict):
            continue
        if f.get("kind") in ("god", "regie") and _scene.validiert(f):
            txt = (f.get("text") or "").strip()
            if txt and ("verboten" in txt.lower() or "tabu" in txt.lower()):
                key = ("regie", f.get("id") or f.get("sourceTurnId") or "?", txt)
                if key not in have_keys:
                    bounds.append({
                        "kind": "regie",
                        "source": f.get("authority") or "regie",
                        "value": txt[:200],
                        "text": txt[:200],
                    })
                    have_keys.add(key)
    scene["bounds"] = bounds

    # B.30-Folge: foreground = aktive Figuren, die in dieser Szene handeln
    # (AMASTERv2 §18 "aktive Figuren").
    # Wer ist "im Vordergrund"?
    # 1. Speaker des letzten Turns
    # 2. Target des letzten Speech/Action
    # 3. Witness des letzten Turns
    # 4. Charaktere mit intensity > 0.5 oder nicht-wach Emotion
    # 5. Charaktere mit offenen Zielen/Propositions
    # Foreground describes bodies actually here, not every character named
    # or remotely addressed in a Fact. Old erroneous focus is pruned as a
    # derived view without rewriting any historical SceneFact.
    foreground: list[str] = [str(cid) for cid in (scene.get("foreground") or [])
                              if str(cid) in present or str(cid) == "narrator"]
    fg_set = {str(c) for c in foreground if c}
    last_turn = None
    for t in reversed(session.get("turns") or []):
        if isinstance(t, dict) and t.get("speakerId"):
            last_turn = t
            break
    if isinstance(last_turn, dict):
        speaker = str(last_turn.get("speakerId") or "")
        if speaker and (speaker in present or speaker == "narrator") and speaker not in fg_set:
            foreground.append(speaker)
            fg_set.add(speaker)
    # Letzter speech/action/physical fact — egal welcher turn.
    for f in reversed(session.get("facts") or []):
        if not isinstance(f, dict):
            continue
        if f.get("kind") in ("speech", "action", "physical"):
            for k in ("actorId", "targetId"):
                tid = f.get(k)
                if tid and str(tid) in present and str(tid) not in fg_set:
                    foreground.append(str(tid))
                    fg_set.add(str(tid))
            break
    for cid in present:
        rt = runtimes.get(cid) or {}
        if not isinstance(rt, dict):
            continue
        intensity = float(rt.get("intensity") or 0)
        emotion = str(rt.get("emotion") or "wach")
        if intensity > 0.5 and cid not in fg_set:
            foreground.append(cid)
            fg_set.add(cid)
        elif emotion not in ("", "wach", "calm") and cid not in fg_set:
            foreground.append(cid)
            fg_set.add(cid)
    for p in session.get("propositions") or []:
        if not isinstance(p, dict):
            continue
        if p.get("status") in ("open", "active", "accepted"):
            for k in ("actorId", "targetId"):
                tid = p.get(k)
                if tid and str(tid) in present and str(tid) not in fg_set:
                    foreground.append(str(tid))
                    fg_set.add(str(tid))
    scene["foreground"] = foreground
    # B.30: nextScene — wenn danger hoch, markiere "Wechsel ratsam" (deterministisch,
    # ohne LLM). Die konkrete Orts-Empfehlung kommt in einer Folge-Iteration,
    # sobald reduce_current_state Zugriff auf world.places bekommt.
    if not scene.get("nextScene"):
        if float(scene.get("danger") or 0) >= 0.7:
            scene["nextScene"] = "Szenenwechsel ratsam"
        else:
            scene["nextScene"] = ""
    # V60 (AMASTER §68 Nr. 24): open requests/questions have ONE owner, the
    # Proposition (mirrored as openQuestions/openDemands and in the brief as
    # OFFENE ANGELEGENHEITEN); they are no longer copied into openMatters.
    prop_texts = {str(p.get("text") or "") for p in props if isinstance(p, dict)}
    scene["openMatters"] = [m for m in (scene.get("openMatters") or []) if m and m not in prop_texts][-12:]
    return session


def witness_access(truth: dict, fact: dict, character_id: str | None) -> str | None:
    """Authority for figure access to fact content, not a mention/target edge.

    Being addressed by speech is not hearing it. A non-present addressee is
    never taught by targetId alone. Physical impact, actual observation,
    having performed the action, and an explicit knowledge transfer remain
    distinct sources of information.
    """
    if not character_id:
        return None
    present = set(truth.get("present_ids") or [])
    hears = set(truth.get("hears_ids") or [])
    sees = set(truth.get("sees_ids") or [])
    informed = set(truth.get("informed_ids") or [])
    event_kind = str(fact.get("event_kind") or fact.get("kind") or "").lower()
    if event_kind == "regie" or fact.get("kind") == "regie":
        # V59C (AMASTER §27.5): Regie is not figure speech. Nobody in the
        # world hears the instruction; its effects carry their own witnesses.
        return None
    if _god_private(fact):
        return "affected" if (character_id == fact.get("targetId")
                              or character_id in set(fact.get("affected_ids") or [])) else None
    if event_kind == "speech" or fact.get("kind") == "speech":
        if character_id in hears and character_id in present:
            return "heard"
        if character_id in informed:
            return "informed"
        return "present" if character_id in present else None
    if fact.get("kind") == "action":
        # A silent physical component is not room speech. Targets that are
        # absent, and bystanders who only hear, cannot see/experience it.
        if character_id not in present:
            return "informed" if character_id in informed else None
        if character_id == fact.get("actorId"):
            return "performed" if _scene.validiert(fact) else "attempted"
        if _scene.validiert(fact) and character_id == fact.get("targetId"):
            return "affected"
        if character_id in sees:
            return "seen"
        return "present"
    affected = set(fact.get("affected_ids") or []) | set(truth.get("affected_ids") or [])
    if fact.get("targetId"):
        affected.add(fact["targetId"])
    if character_id in affected:
        return "affected"
    if character_id in hears and character_id in present:
        return "heard"
    if character_id in sees and character_id in present:
        return "seen"
    if character_id in informed:
        return "informed"
    return "present" if character_id in present else None


def record_witness(
    session: dict,
    *,
    character_id: str,
    fact_id: str,
    access: str,
    source_turn_id: str | None,
    turn: int,
) -> dict:
    session.setdefault("witnessKnowledge", []).append(
        {
            "character_id": character_id,
            "fact_id": fact_id,
            "access": access,
            "source_turn_id": source_turn_id,
            "turn": turn,
        }
    )
    return session


def _candidate_witness_ids(truth: dict, fact: dict) -> list[str]:
    ids: list[str] = []
    for bucket in (
        truth.get("present_ids"),
        truth.get("hears_ids"),
        truth.get("sees_ids"),
        truth.get("informed_ids"),
        truth.get("affected_ids"),
        fact.get("affected_ids"),
        fact.get("witnessedBy"),
        [fact.get("actorId"), fact.get("targetId"), truth.get("speaker_id"), truth.get("avatar_id"), truth.get("target_id")],
    ):
        for i in bucket or []:
            if i and i not in ids:
                ids.append(i)
    return ids


def _record_fact_witnesses(session: dict, truth: dict, facts: list[dict], turn: int) -> None:
    for fact in facts:
        for cid in _candidate_witness_ids(truth, fact):
            access = witness_access(truth, fact, cid)
            if not access:
                continue
            record_witness(
                session,
                character_id=cid,
                fact_id=fact["id"],
                access=access,
                source_turn_id=truth.get("id") or fact.get("source_turn_id"),
                turn=turn,
            )


_DEFAULT_LENS_CELL = {
    "stance": 0.0,
    "threshold": 0.42,
    "reaction": "hält inne und prüft, was das für sie/ihn bedeutet",
    "bodyCue": "Atem wird kürzer",
    "drive": "verstehen, was das für die eigene Lage heißt",
}

# Bedeutungsraum → (Runtime-Delta, gerichtete Beziehungs-Deltas gegenüber benannten Beteiligten)
_KNOWLEDGE_EFFECT: dict[str, dict[str, Any]] = {
    "Verrat":      {"emotion": "Misstrauen", "runtime": {"anger": 0.35, "trust": -0.30, "stress": 0.25}, "rel": {"trust": -0.35, "hostility": 0.15, "closeness": -0.10}},
    "Bedrohung":   {"emotion": "Angst",      "runtime": {"fear": 0.40, "stress": 0.30},                  "rel": {"fear": 0.25, "trust": -0.10}},
    "Angst":       {"emotion": "Angst",      "runtime": {"fear": 0.30, "stress": 0.20},                  "rel": {"fear": 0.15}},
    "Gewalt":      {"emotion": "Wut",        "runtime": {"anger": 0.30, "fear": 0.20, "stress": 0.25},   "rel": {"hostility": 0.25, "fear": 0.15, "trust": -0.15}},
    "Mord":        {"emotion": "Entsetzen",  "runtime": {"fear": 0.35, "stress": 0.35},                  "rel": {"fear": 0.30, "trust": -0.25}},
    "Eifersucht":  {"emotion": "Eifersucht", "runtime": {"anger": 0.20, "stress": 0.20},                  "rel": {"hostility": 0.15, "trust": -0.10}},
    "Verlust":     {"emotion": "Trauer",     "runtime": {"stress": 0.25, "fatigue": 0.10},                "rel": {}},
    "Lust":        {"emotion": "Nähe",       "runtime": {"lust": 0.20},                                   "rel": {"closeness": 0.15}},
    "Schutz":      {"emotion": "Sorge",      "runtime": {"stress": 0.15},                                 "rel": {"closeness": 0.10}},
    "Moral":       {"emotion": "Scham",      "runtime": {"shame": 0.25},                                  "rel": {}},
    "Trennung":    {"emotion": "Sorge",      "runtime": {"stress": 0.25, "fear": 0.15},                   "rel": {"closeness": -0.10}},
    "Geld":        {"emotion": "wach",       "runtime": {"stress": 0.10},                                 "rel": {}},
    "Macht":       {"emotion": "wach",       "runtime": {"stress": 0.15},                                 "rel": {}},
    "Risiko":      {"emotion": "wach",       "runtime": {"stress": 0.15},                                 "rel": {}},
    "Abhaengigkeit": {"emotion": "Sorge",    "runtime": {"stress": 0.20, "fear": 0.10},                   "rel": {}},
}


def _clamp01(v: Any) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _named_participants(text: str, characters: list[dict] | None, self_id: str) -> list[dict]:
    """Figuren, die im Wissenstext namentlich vorkommen (ohne die wissende Figur selbst)."""
    blob = _norm_cue(text)
    out: list[dict] = []
    for c in characters or []:
        if not isinstance(c, dict) or not c.get("id") or str(c.get("id")) == str(self_id):
            continue
        names = [str(c.get("name") or "")] + [str(a) for a in (c.get("aliases") or []) if a]
        tokens = []
        for n in names:
            n = n.strip()
            if not n:
                continue
            tokens.append(n)
            first = n.split()[0]
            if len(first) >= 3:
                tokens.append(first)
        if any(_norm_cue(t) in blob for t in tokens if len(t) >= 3):
            out.append(c)
    return out


def apply_goal_experience(session: dict, owner_id: str, source_fact: dict, *, turn: int,
                          goal_id: str | None = None, reading: dict | None = None) -> dict:
    """Commit perceived evidence into the EXISTING running goal and runtime.

    A new claim is evidence that somebody SAID something, not proof it happened.
    A witnessed validated action is observable evidence. No turn counter,
    word trigger, or LLM response may by itself fulfil a goal.

    V65H (AMASTER §40 Frame, §41/§41.1 Immediate Stimulus, §41.3): ``goal_id``
    with ``reading`` is the validated Themenbezug (apply_goal_theme): this event
    addresses exactly the still unsaid part of this goal, toward the person the
    goal's frame names. Evidence of relevance only — never an exit or a duty.
    """
    fid = str(source_fact.get("id") or "")
    actor = str(source_fact.get("actorId") or "")
    kind = str(source_fact.get("kind") or "")
    text = str(source_fact.get("text") or "").strip()
    if not fid or not actor or not text or actor == owner_id or kind not in ("speech", "action", "physical"):
        return {}
    # A listener may remember room speech without making it evidence for
    # every unrelated goal. Here the event directly concerns its addressee.
    if str(source_fact.get("targetId") or "") != owner_id:
        return {}
    if not _scene.validiert(source_fact):
        return {}
    # No transfer from an absent or unperceiving actor; the witness writer is
    # the sole access authority, not mere target/mention or world membership.
    known = any(
        str(w.get("fact_id") or w.get("factId") or "") == fid
        and str(w.get("character_id") or w.get("characterId") or "") == owner_id
        and w.get("access") in ("heard", "seen", "affected", "informed")
        for w in session.get("witnessKnowledge") or []
    )
    if not known:
        return {}
    event_status = "observed" if kind in ("action", "physical") else "claimed"
    obs = {"sourceFactId": fid, "actorId": actor, "kind": kind, "epistemic": event_status,
           "turn": turn, "text": text[:180]}
    if goal_id and isinstance(reading, dict):
        obs.update({k: reading[k] for k in ("via", "gemeint", "unausgesprochen", "wahrheit", "thema", "anlass", "beleg") if k in reading})
        # V65L (§34 Antwortbezug, §34.2 Kausalprovenienz): the answered line and the bound exchange it continues
        obs.update({k: reading[k] for k in ("antwortAuf", "belegIhreZeile", "art", "fortsetzungVon") if k in reading})
    affected = []
    payload = source_fact.get("payload") if isinstance(source_fact.get("payload"), dict) else {}
    goal_ref = goal_id or source_fact.get("goal_id") or source_fact.get("goalId") or payload.get("goal_id") or payload.get("goalId")
    prop_ref = None if goal_id else (source_fact.get("proposition_id") or source_fact.get("propositionId") or payload.get("proposition_id"))
    for goal in session.get("goals") or []:
        if (not isinstance(goal, dict) or str(goal.get("ownerId") or "") != owner_id
                or goal.get("status") not in ("active", "open", "accepted")):
            continue
        # The binding must already come from the canonical effect/commit.
        # Do not guess goal relevance from addressee, words or list position.
        if goal_ref:
            if str(goal.get("id") or "") != str(goal_ref):
                continue
        elif prop_ref:
            if str(goal.get("proposition_id") or goal.get("propositionId") or "") != str(prop_ref):
                continue
        else:
            continue
        experiences = goal.setdefault("recentExperiences", [])
        if not isinstance(experiences, list):
            experiences = []
            goal["recentExperiences"] = experiences
        _same = next((row for row in experiences if isinstance(row, dict) and row.get("sourceFactId") == fid), None)
        if _same is not None:
            if obs.get("via") and not _same.get("via"):
                # V65H: the same event was already bound (planner); the validated
                # Themenbezug reading is added, not a second experience.
                _same.update({k: obs[k] for k in ("via", "gemeint", "unausgesprochen", "wahrheit", "thema", "anlass", "beleg") if k in obs})
                _same.update({k: obs[k] for k in ("antwortAuf", "belegIhreZeile", "art", "fortsetzungVon") if k in obs})
                affected.append(goal.get("id"))
            continue
        experiences.append(dict(obs))
        goal["recentExperiences"] = experiences[-8:]
        goal["lastExperienceFactId"] = fid
        goal["lastExperienceTurn"] = turn
        affected.append(goal.get("id"))
    # Immediate perceived input stays available independently of having goals.
    # It is attention, not an instruction to pursue or finish a long-term goal.
    rt = session.setdefault("runtimes", {}).setdefault(owner_id, {"characterId": owner_id})
    rt["attentionFactId"] = fid
    rt["attentionTurn"] = turn
    rt["attentionText"] = text[:180]
    rt["attentionEpistemic"] = event_status
    return {"goals": affected, "sourceFactId": fid, "epistemic": event_status}


def apply_knowledge_effect(
    session: dict,
    character: dict,
    *,
    text: str,
    fact_id: str,
    turn: int,
    characters: list[dict] | None = None,
    source: str = "upload",
    authority: str = "observer",
    scale: float = 1.0,
    counterpart_id: str | None = None,
) -> dict[str, Any]:
    """V25 UPL-B03 (MATRIX10 Nr. 16, AMASTERv2 §41/§42/§44, Vertrag §10).

    Kanonisch erhaltenes Wissen (Fact fact_id, für diese Figur berechtigt) trifft
    auf ihren Stamm: die vorhandene Kompass-Linse (fire_compass_lens) bestimmt,
    welche Bedeutungsräume für GENAU DIESE Figur feuern. Daraus folgen — mit dem
    Fact als kanonischer Ursache — RuntimeState-Delta, gerichtete Beziehungs-
    Deltas gegenüber im Wissen benannten Figuren und ein Ziel/eine Absicht aus
    dem Kompass-Drive. Keine neue Weltwahrheit, kein Wissen für Dritte, kein
    Prompt-only-Zustand. Mutiert session in place; gibt Effektprotokoll zurück.
    """
    cid = str(character.get("id") or "")
    if not cid or not text:
        return {"characterId": cid, "fired": [], "runtimeDelta": {}, "relationDelta": [], "goal": None}
    runtimes = session.setdefault("runtimes", {})
    rt = runtimes.get(cid)
    if not isinstance(rt, dict):
        rt = {"characterId": cid, "emotion": "wach", "intensity": 0.35, "fear": 0.1, "trust": 0.4, "anger": 0.1, "stress": 0.25}
        runtimes[cid] = rt
    lens_char = dict(character)
    if not isinstance(lens_char.get("compass"), dict) or not lens_char.get("compass"):
        # Stamm ohne Kompass: neutrale Linse (stance 0) — Wissen wirkt, aber ohne Persona-Verstärkung.
        lens_char["compass"] = {space: dict(_DEFAULT_LENS_CELL) for space in _KNOWLEDGE_EFFECT}
    participants = _named_participants(text, characters, cid)
    # The actor who was actually heard is part of the event even if the
    # statement uses "ich"/"du" rather than naming them. Do not use a mere
    # mentioned name as the sole social target.
    if counterpart_id and counterpart_id != cid and counterpart_id in set((session.get("scene") or {}).get("presentIds") or []):
        direct = next((c for c in (characters or []) if isinstance(c, dict) and str(c.get("id") or "") == counterpart_id), None)
        if isinstance(direct, dict) and not any(str(p.get("id") or "") == counterpart_id for p in participants):
            participants.insert(0, direct)
    rel_hint = None
    if participants:
        rel_hint = next(
            (r for r in session.get("relations") or [] if isinstance(r, dict) and r.get("fromId") == cid and r.get("toId") == participants[0].get("id")),
            None,
        )
    fired = fire_compass_lens(lens_char, text, runtime=rt, scene=session.get("scene") or {}, relation=rel_hint)
    fired = [f for f in fired if str(f.get("space") or "") in _KNOWLEDGE_EFFECT]
    before = dict(rt)
    runtime_delta: dict[str, Any] = {}
    relation_delta: list[dict[str, Any]] = []
    goal_out: dict | None = None
    top = fired[0] if fired else None
    for f in fired[:3]:
        space = str(f.get("space"))
        act = _clamp01(f.get("activation"))
        cell = f.get("cell") if isinstance(f.get("cell"), dict) else {}
        try:
            threshold = float((lens_char.get("compass") or {}).get(space, {}).get("threshold") or 0.42)
        except (TypeError, ValueError):
            threshold = 0.42
        if act < threshold:
            continue
        spec = _KNOWLEDGE_EFFECT[space]
        eff_scale = min(1.0, 0.5 + act) * max(0.1, min(1.0, float(scale)))  # Aktivierung × Quellgewicht (gehört < Fakt)
        for key, delta in (spec.get("runtime") or {}).items():
            cur = float(rt.get(key) or 0)
            rt[key] = round(_clamp01(cur + delta * eff_scale), 3)
        for p in participants:
            pid = str(p.get("id"))
            hit = _ensure_directed_rel(session, cid, pid, cause=fact_id)
            b = dict(hit)
            for key, delta in (spec.get("rel") or {}).items():
                hit[key] = round(_clamp01(float(hit.get(key) or 0) + delta * eff_scale), 3)
            hit["note"] = (str(hit.get("note") or "")[:120] + f" | {space} durch Wissen ({fact_id})").strip(" |")[:240]
            hit["sourceFactId"] = fact_id
            relation_delta.append({"fromId": cid, "toId": pid, "space": space, "before": {k: b.get(k) for k in ("trust", "closeness", "fear", "hostility")}, "after": {k: hit.get(k) for k in ("trust", "closeness", "fear", "hostility")}})
    if top is not None and _clamp01(top.get("activation")) >= 0.42:
        spec = _KNOWLEDGE_EFFECT[str(top.get("space"))]
        cell = top.get("cell") if isinstance(top.get("cell"), dict) else {}
        emo = str(spec.get("emotion") or "wach")
        if emo != "wach":
            rt["emotion"] = emo
        rt["intensity"] = round(max(float(rt.get("intensity") or 0.35), _clamp01(top.get("activation"))), 3)
        rt["activeCause"] = fact_id
        rt["activeCauseText"] = str(text)[:160]
        drive = str(cell.get("drive") or "").strip()
        if drive:
            rt["intent"] = drive[:120]
        who = ", ".join(str(p.get("name") or p.get("id")) for p in participants[:2])
        goal_text = (f"{drive}" if drive else f"Bedeutung von {top.get('space')} klären") + (f" (wegen {who})" if who else "")
        goals = session.setdefault("goals", [])
        # One persistent intention per owner + meaning + counterpart. The
        # source Fact is an occurrence, not the identity of an intention. Using
        # sourceFactId as the only duplicate check re-created the same goal on
        # every heard utterance and fed an ever-growing goal list into recall.
        counterpart = str(participants[0].get("id") or "") if participants else ""
        existing = next((g for g in goals if isinstance(g, dict)
            and str(g.get("ownerId") or "") == cid
            and g.get("kind") == "intent"
            and g.get("status") in ("open", "active", "accepted")
            and str(g.get("space") or "") == str(top.get("space") or "")
            and (str(g.get("counterpartId") or "") == counterpart
                 or (not g.get("counterpartId") and str(g.get("text") or "") == goal_text[:200]))
            ), None)
        if existing is not None:
            evidence = existing.setdefault("reinforcementFactIds", [])
            if not isinstance(evidence, list):
                evidence = []
            first = str(existing.get("sourceFactId") or "")
            if first and first not in evidence:
                evidence.insert(0, first)
            if fact_id not in evidence:
                evidence.append(fact_id)
            existing["reinforcementFactIds"] = evidence[-16:]
            existing["lastReinforcedFactId"] = fact_id
            existing["lastReinforcedTurn"] = turn
            # A reinforcement does not reset goal status or erase older facts.
        else:
            goal_out = {
                "id": uid("goal"),
                "ownerId": cid,
                "text": goal_text[:200],
                "status": "open",
                "kind": "intent",
                "sourceFactId": fact_id,
                "space": str(top.get("space")),
                "counterpartId": counterpart,
                "reinforcementFactIds": [fact_id],
                "lastReinforcedFactId": fact_id,
                "lastReinforcedTurn": turn,
                "turn": turn,
            }
            goals.append(goal_out)
    for k in ("emotion", "intensity", "fear", "trust", "anger", "stress", "shame", "lust", "fatigue", "intent", "activeCause"):
        if before.get(k) != rt.get(k):
            runtime_delta[k] = {"from": before.get(k), "to": rt.get(k)}
    effect = {
        "characterId": cid,
        "fired": [{"space": f.get("space"), "activation": f.get("activation")} for f in fired[:3]],
        "runtimeDelta": runtime_delta,
        "relationDelta": relation_delta,
        "goal": goal_out,
        "sourceFactId": fact_id,
    }
    if runtime_delta or relation_delta or goal_out:
        fact = make_fact(
            turn=turn,
            actorId=cid,
            targetId=None,
            kind="knowledge_effect",
            event_kind="knowledge_effect",
            text=f"{character.get('name') or cid}: Wissen wirkt ({', '.join(str(f.get('space')) for f in fired[:2]) or 'neutral'})",
            authority=authority,
            **fact_provenance(session, fact_id),   # V65Z (A01): Quellturn of the cause, cause_fact_id
            truth={"user_id": session.get("userId"), "world_id": session.get("worldId"), "session_id": session.get("id")},
            scene=session.get("scene") or {},
            witnessedBy=[cid],
            affected_ids=[cid] + [str(p.get("id")) for p in participants],
            payload={"kind": "knowledge_effect", "sourceFactId": fact_id, "source": source, "runtimeDelta": runtime_delta,
                     "relationDelta": relation_delta, "goalId": (goal_out or {}).get("id"), "fired": effect["fired"]},
            source_type=source,
            provenance="kernel",
            validated=True,
        )
        session.setdefault("facts", []).append(fact)
        effect["effectFactId"] = fact["id"]
        effect["effectFact"] = fact
    return effect


# V92 Paket 19 (unabhaengige Pruefung Paket 18 N1-N7 und die drei Regie-Wortfehler; AMASTER §43, §43.1, §46.1/§46.2,
# §24.2/§24.7, §6.2 fail-closed; Kettenvertrag §1/§3/§6): ONE typed body contract for every caller - figure reply, puppet,
# avatar input, God, Regie:
#   typed reading (closed values + literal quote)
#   -> confirmation reading AT the quoted place (a different question: "does exactly this change take place here, now?",
#      with its own literal anchor; llm_contract.koerper_bestaetigung)
#   -> kernel validation (body_change_validated)  ->  ONE writer (write_body_change -> apply_body_directive).
# A literal quote alone is no proof (P18 N3/N4/N6: "schläft nicht ein", "steht nicht auf", "keine Schmerzen" were quoted
# literally by a wrong reading). The former word readings (_regie_body_words and the _BODY_*_RE lists) are removed - no word
# list decides a body state any more.
_OWN_BODY_POSTURE = {"liegend": "liegend", "sitzend": "sitzend", "kniend": "kniend", "stehend": "stehend", "kopfstand": "Handstand"}
# the writer's effect of a position (unchanged values of the former _BODY_POSTURE table, without its word patterns)
_POSTURE_EFFECT = {
    "Handstand": {"handsFree": False, "mobility": 0.2, "cannotDo": ["gehen", "Hände benutzen", "etwas tragen"]},
    "liegend": {"mobility": 0.5, "cannotDo": ["gehen"]},
    "sitzend": {"mobility": 0.7, "cannotDo": []},
    "kniend": {"mobility": 0.5, "cannotDo": ["gehen"]},
    "stehend": {"mobility": None, "handsFree": True, "cannotDo": []},
}
# V65J scale (unchanged): mobility 0.2 = cannot walk (capability blocks < 0.3), < 0.35 "kann sich nicht frei bewegen";
# pain > 0.7 "starke Schmerzen"; consciousness 0.2 = unconscious, 0.4 = asleep (V92 Paket 18)
_GOD_PAIN = {"kein": 0.0, "leicht": 0.25, "mittel": 0.5, "stark": 0.8}
_GOD_MOBILITY = {"frei": 1.0, "eingeschraenkt": 0.6, "stark_eingeschraenkt": 0.3, "unbeweglich": 0.2}
_GOD_CONSCIOUS = {"wach": 1.0, "benommen": 0.6, "bewusstlos": 0.2}
_BODY_VALUES = {
    "haltung": tuple(_OWN_BODY_POSTURE), "schlaf": ("einschlafen", "aufwachen"), "bewusstsein": tuple(_GOD_CONSCIOUS),
    "schmerz": tuple(_GOD_PAIN), "beweglichkeit": tuple(_GOD_MOBILITY), "sehen": ("verliert", "zurueck"),
    "sprechen": ("verliert", "zurueck"),
}
_BODY_FLAGS = ("gefesselt", "geknebelt")
# what a participant's OWN act may change on the actor's own body (figure reply, puppet, avatar input): the position taken now and
# falling asleep / waking up. Pain, injury, unconsciousness, loss of speech or sight come from a validated effect of another
# figure's act (_apply_physical) or from an explicit authority (God, Regie) - with the same contract.
_PARTICIPANT_BODY_FIELDS = ("haltung", "schlaf")
_BODY_FULL_AUTHORITY = ("god", "regie")
_BODY_CONFIRMED = "tatsaechlich"   # the modality of VOLLZUG_CHECK_RULES: stated as happening/holding now


def _full_body_authority(authority: Any) -> bool:
    return str(authority or "").strip().lower() in _BODY_FULL_AUTHORITY


def _typed_body_change(reading: Any, *, full: bool) -> tuple[dict, str | None]:
    """V92 Paket 19: the typed values of a reading, closed inventory only -> (change, fault). Read only."""
    r = reading if isinstance(reading, dict) else {}
    ch: dict[str, Any] = {}
    fault = None
    for k in (tuple(_BODY_VALUES) if full else _PARTICIPANT_BODY_FIELDS):
        v = r.get(k)
        if v in (None, "", False):
            continue
        v = str(v).strip().lower()
        if v in _BODY_VALUES[k]:
            ch[k] = v
        else:
            fault = fault or "wert_unbekannt"
    if full:
        for k in _BODY_FLAGS:
            if isinstance(r.get(k), bool):
                ch[k] = r[k]
            elif r.get(k) not in (None, ""):
                fault = fault or "wert_unbekannt"
        if r.get("heilung") is True:
            ch["heilung"] = True
        inj = r.get("verletzung")
        if isinstance(inj, dict) and str(inj.get("art") or "").strip():
            ch["verletzung"] = {"art": str(inj.get("art")).strip()[:30],
                                "glied": str(inj.get("glied") or "").strip()[:30] or None,
                                "seite": str(inj.get("seite") or "").strip().lower()[:10] or None,
                                "schwer": inj.get("schwer") is True}
        elif inj not in (None, "", {}, False):
            fault = fault or "wert_unbekannt"
    return ch, fault


def _body_change_core(reading: Any, text: str, *, authority: str) -> tuple[dict | None, str, str | None]:
    """(change, quote, fault) of a reading BEFORE its confirmation: closed values, NOW (participants), a quote that stands
    literally in `text` (mandatory for every caller - P18 N5 took a God reading without quote)."""
    full = _full_body_authority(authority)
    r = reading if isinstance(reading, dict) else {}
    beleg = " ".join(str(r.get("beleg") or "").split())
    if not r:
        return None, beleg, "keine_lesung"
    ch, fault = _typed_body_change(r, full=full)
    if fault:
        return None, beleg, fault
    if not ch:
        return None, beleg, "keine_veraenderung"
    if not full:
        zeit = str(r.get("zeit") or "").strip().lower()
        if zeit != "jetzt":
            return None, beleg, f"zeit_{zeit or 'unklar'}"
    if not beleg:
        return None, beleg, "beleg_fehlt"
    _sp = _locate_segment(text, beleg)
    if _sp is None:
        return None, beleg, ("beleg_nicht_im_text" if full else "beleg_nicht_in_handlung")
    if any(qa <= _sp[0] and _sp[1] <= qb for qa, qb in quoted_spans(text)):
        # V65Z rule (segment_binding_fault): words inside quotation marks are said, not done - form only, no word list
        return None, beleg, "beleg_im_zitat"
    return ch, beleg, None


def body_change_label(change: Any) -> str:
    """V92 Paket 19: the typed change in plain words for the confirmation reading (closed inventory -> fixed wording; the
    reading's own words never come back here). Read only."""
    ch = change if isinstance(change, dict) else {}
    out: list[str] = []
    if ch.get("haltung"):
        out.append({"kopfstand": "steht jetzt im Hand- oder Kopfstand"}.get(ch["haltung"], f"nimmt jetzt die Körperlage {ch['haltung']} ein"))
    if ch.get("schlaf"):
        out.append("schläft jetzt ein" if ch["schlaf"] == "einschlafen" else "wacht jetzt aus dem Schlaf auf")
    if ch.get("bewusstsein"):
        out.append({"wach": "ist jetzt wach und bei vollem Bewusstsein", "benommen": "ist jetzt benommen",
                    "bewusstlos": "ist jetzt bewusstlos"}[ch["bewusstsein"]])
    if ch.get("schmerz"):
        out.append({"kein": "hat jetzt keine Schmerzen", "leicht": "hat jetzt leichte Schmerzen",
                    "mittel": "hat jetzt mittlere Schmerzen", "stark": "hat jetzt starke Schmerzen"}[ch["schmerz"]])
    if ch.get("beweglichkeit"):
        out.append({"frei": "kann sich jetzt wieder frei bewegen", "eingeschraenkt": "ist jetzt in der Bewegung eingeschränkt",
                    "stark_eingeschraenkt": "kann sich jetzt nur mit großer Mühe bewegen",
                    "unbeweglich": "kann sich jetzt nicht bewegen"}[ch["beweglichkeit"]])
    for k, ja, nein in (("gefesselt", "ist jetzt gefesselt", "ist jetzt nicht mehr gefesselt"),
                        ("geknebelt", "ist jetzt geknebelt", "ist jetzt nicht mehr geknebelt")):
        if isinstance(ch.get(k), bool):
            out.append(ja if ch[k] else nein)
    if ch.get("sehen"):
        out.append("kann jetzt nicht mehr sehen" if ch["sehen"] == "verliert" else "kann jetzt wieder sehen")
    if ch.get("sprechen"):
        out.append("kann jetzt nicht mehr sprechen" if ch["sprechen"] == "verliert" else "kann jetzt wieder sprechen")
    if isinstance(ch.get("verletzung"), dict):
        v = ch["verletzung"]
        wo = " ".join(x for x in (str(v.get("seite") or ""), str(v.get("glied") or "")) if x).strip()
        out.append("hat jetzt eine Verletzung: " + str(v.get("art") or "verletzt") + (f" ({wo})" if wo else "")
                   + (", schwer" if v.get("schwer") else ""))
    if ch.get("heilung") is True:
        out.append("ihre Verletzungen sind jetzt geheilt")
    return "; ".join(out)


def body_change_candidate(reading: Any, text: str, *, authority: str = "character") -> tuple[dict, str] | None:
    """V92 Paket 19: (change, quote) a reading proposes that the confirmation reading must check - None when the reading
    already fails before (no change, unknown value, not now, quote missing or not in the text). Read only."""
    ch, beleg, fault = _body_change_core(reading, text, authority=authority)
    return (ch, beleg) if fault is None and ch else None


def body_change_fields(change: Any) -> list[tuple[str, dict]]:
    """V92 Paket 19: the change split into its fields - each field is confirmed on its own (a reading that names more than the text
    says loses only that field, not the field the text does say). Read only."""
    return [(k, {k: copy.deepcopy(v)}) for k, v in (change.items() if isinstance(change, dict) else [])]


def _body_confirmed_fields(reading: dict, change: dict, beleg: str, text: str) -> tuple[dict, dict, str | None]:
    """V92 Paket 19: the second key, per field. The confirmation reading (llm_contract.koerper_bestaetigung, put on the reading by the
    route as `bestaetigung` = {"stelle": quote, "felder": {field: {"wert", "art", "inhalt", "beleg"}}}) must have been asked at exactly
    this quote about exactly this field value, say that the text states it as happening/holding NOW (`art` tatsaechlich - the
    modality taxonomy of VOLLZUG_CHECK_RULES) and the same thing (`inhalt` gleich), and anchor its answer literally in the text at the
    same place (both literal anchors hold, pattern of V65W AUSSAGE_TAT_RULES). -> (confirmed fields, per-field verdicts, fault of
    the whole when NO field is confirmed)."""
    b = reading.get("bestaetigung") if isinstance(reading.get("bestaetigung"), dict) else None
    if b is None:
        return {}, {}, "bestaetigung_fehlt"
    if " ".join(str(b.get("stelle") or "").split()) != beleg:
        return {}, {}, "bestaetigung_andere_stelle"
    felder = b.get("felder") if isinstance(b.get("felder"), dict) else {}
    sp = _locate_segment(text, beleg)
    ok: dict = {}
    verdicts: dict = {}
    for k, one in body_change_fields(change):
        f = felder.get(k) if isinstance(felder.get(k), dict) else None
        if f is None:
            why = "bestaetigung_fehlt"
        elif _typed_body_change({k: f.get("wert")}, full=True)[0] != one:
            why = "bestaetigung_andere_veraenderung"
        elif str(f.get("art") or "").strip().lower() != _BODY_CONFIRMED:
            why = ("bestaetigung_" + (re.sub(r"[^a-z_]", "", str(f.get("art") or "").strip().lower()) or "ohne_art"))[:40]
        elif str(f.get("inhalt") or "").strip().lower() != "gleich":
            why = "bestaetigung_anders"
        else:
            bb = " ".join(str(f.get("beleg") or "").split())
            bsp = _locate_segment(text, bb) if bb else None
            why = ("bestaetigung_beleg_nicht_im_text" if bsp is None
                   else None if (sp is not None and bsp[0] < sp[1] and sp[0] < bsp[1]) else "bestaetigung_andere_stelle")
        verdicts[k] = {"art": (f or {}).get("art"), "inhalt": (f or {}).get("inhalt"), "beleg": (f or {}).get("beleg"),
                       **({"grund": why} if why else {"bestaetigt": True})}
        if why is None:
            ok.update(one)
    first = next((v.get("grund") for v in verdicts.values() if v.get("grund")), None)
    return ok, verdicts, (None if ok else (first or "bestaetigung_fehlt"))


def body_change_validated(reading: Any, text: str, *, authority: str = "character", figur_id: Any = None) -> tuple[dict | None, dict]:
    """V92 Paket 19: THE validation of every body change before the writer -> (change or None, audit). Valid only: closed
    values (participants: position/sleep, NOW), a literal quote, and per field a confirmation reading that says the text states
    exactly this value as happening/holding now (`tatsaechlich`, `gleich`) at exactly this place with its own literal anchor;
    for God/Regie the reading must be made for exactly the bound figure (`figurId`). Only confirmed fields are written; nothing
    confirmed -> nothing written (fail-closed). The audit says why, per field. No word list."""
    full = _full_body_authority(authority)
    r = reading if isinstance(reading, dict) else {}
    ch, beleg, fault = _body_change_core(r, text, authority=authority)
    if fault is None and full and str(r.get("figurId") or "") != str(figur_id or ""):
        fault = "figur_nicht_gebunden"
    ok, verdicts = {}, {}
    if fault is None:
        ok, verdicts, fault = _body_confirmed_fields(r, ch or {}, beleg, text)
    shown = {"bestaetigung": copy.deepcopy(verdicts) if verdicts else None}
    if fault is None:
        return ok, {"bestaetigt": True, **copy.deepcopy(ok), "beleg": beleg[:160], **({} if full else {"zeit": "jetzt"}), **shown}
    vals = {k: copy.deepcopy(r.get(k)) for k in (tuple(_BODY_VALUES) + _BODY_FLAGS + ("verletzung", "heilung"))
            if r.get(k) not in (None, "", False) or (k in _BODY_FLAGS and r.get(k) is False)}
    return None, {"bestaetigt": False, "grund": fault, **vals, "beleg": beleg[:160] or None,
                  **({} if full else {"zeit": str(r.get("zeit") or "").strip().lower() or None}), **shown}


def own_body_change(reading: Any, action: str) -> tuple[dict | None, dict]:
    """V92 Paket 18/19: the validated change of the actor's OWN body a reading (llm_contract.koerper_check + koerper_bestaetigung)
    names for THIS act - (change or None, audit). Participant authority: position and sleep only (body_change_validated)."""
    return body_change_validated(reading, action, authority="character")


def authority_body_change(reading: Any, text: str, *, figur_id: Any, authority: str) -> tuple[dict | None, dict]:
    """V92 Paket 19: the validated body change a God fact or a Regie order sets for the bound figure `figur_id` - the SAME
    contract as a participant's own act, with the full typed inventory (pain/mobility levels, consciousness, restrained, gagged,
    position, sleep, sight, speech, injury, healing). Replaces god_body_values (God) and _regie_body_words (Regie)."""
    return body_change_validated(reading, text, authority=authority if _full_body_authority(authority) else "god", figur_id=figur_id)


def can_speak_now(runtime: Any) -> bool:
    """V92 Paket 19 (Pruefung P18 N2): whether the figure can speak NOW - not gagged, not mute, and conscious (asleep or
    unconscious = consciousness < 0.5 speaks no words). One rule for every speech gate. Read only."""
    rt = runtime if isinstance(runtime, dict) else {}
    cons = float(rt.get("consciousness") if rt.get("consciousness") is not None else 1)
    return not (rt.get("gagged") or rt.get("stumm") or rt.get("canSpeak") is False or cons < 0.5)


def capability_reason_text(runtime: Any) -> str:
    """V92 Paket 19: plain wording of why the body state blocks speech/acts now (for the message shown to the person). Read only."""
    rt = runtime if isinstance(runtime, dict) else {}
    cons = float(rt.get("consciousness") if rt.get("consciousness") is not None else 1)
    if cons < 0.5 and rt.get("schlaeft"):
        return "Zustand: schläft (möglich ist nur das eigene Aufwachen)"
    if cons < 0.5:
        return "Zustand: bewusstlos"
    if not can_speak_now(rt):
        return "Zustand: kann jetzt nicht sprechen (geknebelt oder stumm), die Handlung ist nicht möglich"
    return "der Körperzustand lässt es nicht zu"


def wakes_from(runtime: Any, change: Any, authority: Any) -> bool:
    """V92 Paket 19 (Pruefung P18 N1): the one change that lifts a figure below consciousness 0.5 - being woken. A participant
    (her own act) only out of SLEEP (`schlaeft`) and only by a validated own change schlaf=aufwachen; an unconscious figure
    cannot wake herself. God/Regie (full authority) also out of unconsciousness (bewusstsein wach/benommen). Read only."""
    rt = runtime if isinstance(runtime, dict) else {}
    ch = change if isinstance(change, dict) else {}
    if _full_body_authority(authority):
        return ch.get("schlaf") == "aufwachen" or ch.get("bewusstsein") in ("wach", "benommen")
    return bool(rt.get("schlaeft")) and ch.get("schlaf") == "aufwachen"


def _only_quoted_act(text: str, beleg: str, names: Any) -> bool:
    """V92 Paket 19: the act consists of the quoted words alone - outside the quote at most its subject (a name of the actor or
    one word). Form only: "Mara wacht auf." yes; "Mara wacht auf und schlägt Johann." no (the rest is another act)."""
    sp = _locate_segment(text, beleg) if beleg else None
    if sp is None:
        return False
    rest = " " + _name_words(_residual_text(str(text or ""), [sp]) or "") + " "
    for n in sorted({_name_words(x) for x in (names or []) if _name_words(x)}, key=len, reverse=True):
        rest = rest.replace(" " + n + " ", " ")
    return len(rest.split()) <= 1


def act_capability(runtime: Any, text: str, change: Any, audit: Any, *, authority: str = "character",
                   names: Any = ()) -> tuple[str | None, dict | None, bool]:
    """V92 Paket 19 (Pruefung P18 N1/N2; AMASTER §43 Capability, §43.1): whether an act can be carried out with the body state
    at the START of the turn -> (rejection or None, the body change to write, wake_only).
    - consciousness >= 0.5: capability_blocks_action decides (unchanged); the validated change stays as it is.
    - below 0.5 (asleep or unconscious) every act is blocked - except the one act that wakes: wakes_from() with a validated
      change, and only when the act IS that waking (_only_quoted_act). A participant then writes only schlaf=aufwachen; the act
      has no other effect (wake_only). Nothing else of a sleeping or unconscious figure is released."""
    rt = runtime if isinstance(runtime, dict) else {}
    cons = float(rt.get("consciousness") if rt.get("consciousness") is not None else 1)

    def _blocked() -> tuple[str, None, bool]:
        # the audit of the body reading says that the act itself was not carried out (its reading may have been confirmed)
        if isinstance(audit, dict) and audit.get("bestaetigt"):
            audit.update({"bestaetigt": False, "grund": "handlung_gesperrt"})
        return "capability", None, False
    if cons >= 0.5:
        if capability_blocks_action(rt, text):
            return _blocked()
        return None, (change if isinstance(change, dict) else None), False
    if not (isinstance(change, dict) and wakes_from(rt, change, authority)
            and _only_quoted_act(text, str((audit or {}).get("beleg") or "") if isinstance(audit, dict) else "", names)):
        return _blocked()
    if isinstance(audit, dict) and not _full_body_authority(authority):
        # a participant asleep writes only her waking: the audit names exactly what is written
        for k in [k for k in list(audit) if k in _BODY_VALUES and k != "schlaf"]:
            audit.pop(k, None)
        audit["nurAufwachen"] = True
    return None, (copy.deepcopy(change) if _full_body_authority(authority) else {"schlaf": "aufwachen"}), True


def apply_body_directive(session: dict, actor_id: str, change: Any, *, fact_id: str, turn: int, authority: str = "regie",
                         text: str = "", vermerk: str | None = None, witnesses: list | None = None,
                         actor_name: str | None = None) -> dict[str, Any]:
    """V34 PhysicalState-Writer (AMASTERv2 §43, Vertrag §10/§28): the ONE writer of the body state - position, injuries, pain,
    mobility, consciousness and sleep, restrained/gagged, speech and sight, cannotDo - as canonical state with its cause (fact_id)
    and a body_state Fact. V92 Paket 18/19: it takes only a TYPED change that body_change_validated accepted; it reads no words.
    A participant's authority (character, puppet, the avatar's input) may change only the position and sleep/waking of its own
    body (_PARTICIPANT_BODY_FIELDS); God and Regie the full inventory. Speech follows the state: canSpeak = not gagged, not mute
    (`stumm`), conscious (asleep/unconscious speak no words). `text` is the cause shown in the mirror (bodyCauseText);
    `vermerk` (God) is kept as a note of the written state; `witnesses` default: the present figures."""
    if not actor_id or not isinstance(change, dict) or not change:
        return {}
    full = _full_body_authority(authority)
    ch = {k: v for k, v in change.items() if full or k in _PARTICIPANT_BODY_FIELDS}
    if not ch:
        return {}
    rt = session.setdefault("runtimes", {}).setdefault(actor_id, {"characterId": actor_id})
    keys = ("posture", "injuries", "pain", "mobility", "consciousness", "schlaeft", "canSpeak", "stumm", "canSee", "handsFree",
            "cannotDo", "restrained", "gagged")
    before = {k: copy.deepcopy(rt.get(k)) for k in keys}
    delta: dict[str, Any] = {}
    if ch.get("heilung") is True:
        if rt.get("injuries"):
            delta["injuries"] = []
        delta["pain"] = 0.0
        _left = [c for c in (rt.get("cannotDo") or []) if not ("benutzen" in str(c) or "greifen" in str(c) or "normal gehen" in str(c))]
        if _left != list(rt.get("cannotDo") or []):
            delta["cannotDo"] = _left
    inj = ch.get("verletzung") if isinstance(ch.get("verletzung"), dict) else None
    if inj and ch.get("heilung") is not True:
        seite, glied = (str(inj.get("seite") or "").strip() or None), (str(inj.get("glied") or "").strip() or None)
        part = " ".join(x for x in (glied, f"({seite})" if seite else None) if x).strip() or "Körper"
        entry = {"part": part[:40], "kind": str(inj.get("art") or "verletzt")[:30], "since": turn, "cause": fact_id}
        injuries = [i for i in (rt.get("injuries") or []) if isinstance(i, dict)]
        if not any(i.get("part") == entry["part"] and i.get("kind") == entry["kind"] for i in injuries):
            injuries.append(entry)
        delta["injuries"] = injuries
        delta["pain"] = max(float(rt.get("pain") or 0), 0.7 if inj.get("schwer") else 0.4)
        cannot = list(rt.get("cannotDo") or [])
        if glied and glied.lower() in ("arm", "hand", "handgelenk", "finger", "schulter"):
            cannot.append(f"{part} benutzen")
            if seite:
                cannot.append(f"mit {part} greifen oder schreiben")
        if glied and glied.lower() in ("bein", "fuß", "fuss", "knie", "knöchel", "knoechel", "hüfte", "huefte"):
            cannot.append("normal gehen")
            delta["mobility"] = min(float(rt.get("mobility") or 1), 0.3)
        delta["cannotDo"] = list(dict.fromkeys(cannot))
    if ch.get("schmerz") in _GOD_PAIN:
        delta["pain"] = _GOD_PAIN[ch["schmerz"]]
    posture = _OWN_BODY_POSTURE.get(str(ch.get("haltung") or ""))
    if posture:
        eff = _POSTURE_EFFECT[posture]
        delta["posture"] = posture
        if eff.get("mobility") is not None:
            delta["mobility"] = eff["mobility"] if not rt.get("injuries") else min(float(delta.get("mobility", rt.get("mobility") or 1)), eff["mobility"])
        elif posture == "stehend" and rt.get("posture") in ("Handstand", "liegend", "kniend", "sitzend"):
            delta["mobility"] = 0.3 if any("gehen" in str(c) for c in (rt.get("cannotDo") or []) if "normal" in str(c)) else 0.8
        if "handsFree" in eff:
            delta["handsFree"] = eff["handsFree"]
        keep = [c for c in (delta.get("cannotDo", rt.get("cannotDo")) or []) if "benutzen" in str(c) or "greifen" in str(c) or "normal gehen" in str(c)]
        delta["cannotDo"] = list(dict.fromkeys(keep + list(eff.get("cannotDo") or [])))
    if ch.get("beweglichkeit") in _GOD_MOBILITY:
        delta["mobility"] = _GOD_MOBILITY[ch["beweglichkeit"]]
    if isinstance(ch.get("gefesselt"), bool):
        delta["restrained"] = ch["gefesselt"]
        if ch["gefesselt"]:
            delta["mobility"] = min(float(delta.get("mobility", rt.get("mobility") if rt.get("mobility") is not None else 1)), 0.2)
    if isinstance(ch.get("geknebelt"), bool):
        delta["gagged"] = ch["geknebelt"]
    if ch.get("bewusstsein") == "bewusstlos":
        delta["consciousness"] = _GOD_CONSCIOUS["bewusstlos"]
        delta["posture"] = "liegend"
        delta["schlaeft"] = False
    elif ch.get("bewusstsein") in ("wach", "benommen"):
        delta["consciousness"] = _GOD_CONSCIOUS[ch["bewusstsein"]]
        delta["schlaeft"] = False
    if ch.get("schlaf") == "einschlafen" and ch.get("bewusstsein") != "bewusstlos":
        delta["consciousness"] = 0.4
        delta["schlaeft"] = True
        # V92 Paket 19: asleep on a chair she stays sitting; otherwise she lies (V34 default)
        delta["posture"] = delta.get("posture") or (rt.get("posture") if rt.get("posture") in ("sitzend", "liegend") else "liegend")
    elif ch.get("schlaf") == "aufwachen" and ch.get("bewusstsein") not in ("bewusstlos", "benommen"):
        delta["consciousness"] = 1.0
        delta["schlaeft"] = False
    if ch.get("sehen") in ("verliert", "zurueck"):
        delta["canSee"] = ch["sehen"] == "zurueck"
    if ch.get("sprechen") in ("verliert", "zurueck"):
        delta["stumm"] = ch["sprechen"] == "verliert"
    if any(k in ch for k in ("bewusstsein", "schlaf", "geknebelt", "sprechen")):
        _after = {**rt, **delta}
        delta["canSpeak"] = can_speak_now({**_after, "canSpeak": None})
    if not delta:
        return {}
    for k, v in delta.items():
        rt[k] = v
    rt["bodyCause"] = fact_id
    rt["bodyCauseText"] = str(text or "")[:160]
    rt["bodySince"] = turn
    changed = {k: {"from": before.get(k), "to": copy.deepcopy(rt.get(k))} for k in delta if before.get(k) != rt.get(k)}
    if changed:
        if vermerk and full:
            notes = list(rt.get("constraints") or [])
            if str(vermerk)[:120] not in notes:
                notes.append(str(vermerk)[:120])
            rt["constraints"] = notes[-6:]
        name = str(actor_name or "").strip() or (_name_of(actor_id, [], session) if "_name_of" in globals() else actor_id)
        shown = [k for k in ("posture", "pain", "mobility", "consciousness", "schlaeft", "canSpeak", "canSee", "restrained", "gagged")
                 if k in changed]
        fact = make_fact(
            turn=turn,
            actorId=actor_id,
            targetId=None,
            kind="body_state",
            event_kind="body_state",
            text=(f"{name}: Körperzustand — " + ", ".join(f"{k}: {changed[k]['to']}" for k in shown)) if shown else f"{name}: Körperzustand geändert",
            authority=authority,
            **fact_provenance(session, fact_id),   # V65Z (A01)
            truth={"user_id": session.get("userId"), "world_id": session.get("worldId"), "session_id": session.get("id")},
            scene=session.get("scene") or {},
            witnessedBy=list(witnesses) if isinstance(witnesses, list) else list((session.get("scene") or {}).get("presentIds") or []),
            affected_ids=[actor_id],
            # V92 Paket 18/19: the typed change that was written (its reading and confirmation are on the cause fact)
            payload={"kind": "body_state", "delta": changed, "sourceFactId": fact_id,
                     "aenderung": {k: copy.deepcopy(v) for k, v in ch.items() if k != "beleg"}},
            source_type="body",
            provenance="kernel",
            validated=True,
        )
        session.setdefault("facts", []).append(fact)
    return changed


def write_body_change(session: dict, actor_id: Any, change: Any, *, fact_id: str, turn: int, authority: str, text: str = "",
                      vermerk: str | None = None, witnesses: list | None = None, actor_name: str | None = None) -> dict[str, Any]:
    """V92 Paket 19 (Pruefung P18 N7): the ONE entry of every caller (figure, puppet, avatar input, God, Regie) to the body
    writer apply_body_directive - no caller writes a body field itself any more (God's former cur.update is removed). A writer
    failure leaves no half state: the actor's runtime and the Facts are restored, the caller records the failure on its cause
    Fact -> {"geschrieben", "delta", "fehler"}."""
    if not actor_id or not isinstance(change, dict) or not change:
        return {"geschrieben": False, "delta": {}, "fehler": None}
    runtimes = session.setdefault("runtimes", {})
    aid = str(actor_id)
    had = aid in runtimes
    snap = copy.deepcopy(runtimes.get(aid))
    facts = session.setdefault("facts", [])
    n = len(facts)
    try:
        changed = apply_body_directive(session, aid, change, fact_id=fact_id, turn=turn, authority=authority, text=text,
                                       vermerk=vermerk, witnesses=witnesses, actor_name=actor_name)
    except Exception as exc:   # fail-closed: the state stays as it was before this write
        if had:
            runtimes[aid] = snap
        else:
            runtimes.pop(aid, None)
        del facts[n:]
        return {"geschrieben": False, "delta": {}, "fehler": f"{type(exc).__name__}: {str(exc)[:160]}"}
    return {"geschrieben": bool(changed), "delta": changed or {}, "fehler": None}


MEANING_SPACES = (
    "Bedrohung", "Angst", "Verrat", "Lust", "Geld", "Trennung", "Gewalt", "Mord",
    "Eifersucht", "Verlust", "Abhaengigkeit", "Moral", "Risiko", "Schutz", "Macht",
)

_SYNAPSE_EMOTION = {
    "Bedrohung": "Angst", "Angst": "Angst", "Gewalt": "Wut", "Mord": "Entsetzen", "Verrat": "Misstrauen",
    "Verlust": "Trauer", "Eifersucht": "Eifersucht", "Lust": "Nähe", "Schutz": "Sorge", "Moral": "Scham",
    "Trennung": "Sorge", "Macht": "wach", "Geld": "wach", "Risiko": "wach", "Abhaengigkeit": "Sorge",
}


def _fold_space(value: Any) -> str:
    return (str(value or "").strip().lower().replace("ä", "ae").replace("ö", "oe")
            .replace("ü", "ue").replace("ß", "ss"))


# V63 (AMASTER §15 Z. 732 "editierbare Verhaltenslinse über diese
# Profilbestandteile", Z. 758 "Änderungen am Kompass erfolgen sichtbar über das
# Frontend"): the placeholder cells the system itself writes for a figure
# whose compass was never derived or edited. Owners of these values: the
# frontend `emptyCompass()` (src/lib/matrix/compass.ts) — the world page
# already treats exactly this as "nicht gefüllt" (isDefaultCompass) — the
# local fallback of llm_contract.derive_compass_from_config and the kernel's
# _DEFAULT_LENS_CELL. A placeholder is no lens over HER profile; readers treat
# it as "not set" (the profile itself stays the disposition). Session 13:39,
# 27.10.: Tamara (dominatrix) was mirrored 15 identical cells "hält inne und
# prüft … Antrieb: Lage verstehen, bevor gehandelt wird".
_COMPASS_PLACEHOLDER_TEXTS = (
    ("hält inne und prüft, was das mit ihr/ihm macht", "Atem wird kürzer", "Lage verstehen, bevor gehandelt wird"),
    (_DEFAULT_LENS_CELL["reaction"], _DEFAULT_LENS_CELL["bodyCue"], _DEFAULT_LENS_CELL["drive"]),
)


def _is_placeholder_cell(cell: Any) -> bool:
    if not isinstance(cell, dict):
        return True
    texts = tuple(" ".join(str(cell.get(k) or "").split()) for k in ("reaction", "bodyCue", "drive"))
    if texts not in _COMPASS_PLACEHOLDER_TEXTS:
        return False
    try:
        stance = float(cell.get("stance") or 0)
        threshold = float(cell.get("threshold")) if cell.get("threshold") is not None else _DEFAULT_LENS_CELL["threshold"]
    except (TypeError, ValueError):
        return False
    # an explicitly set stance or threshold is an edit of the lens
    return stance == 0 and abs(threshold - float(_DEFAULT_LENS_CELL["threshold"])) < 1e-9


def authored_compass(character: dict | None) -> dict:
    """V63 (§15): the figure's compass without placeholder cells — the ONE
    reader view used by the brief (DEIN KOMPASS), the appraisal payload and
    compass_cell (threshold of the appraisal step)."""
    comp = (character or {}).get("compass") if isinstance((character or {}).get("compass"), dict) else {}
    return {k: v for k, v in comp.items() if isinstance(v, dict) and not _is_placeholder_cell(v)}


def compass_cell(character: dict, space: Any) -> tuple[str | None, dict | None]:
    """V62 (AMASTER §15): the figure's own compass cell for a proposed meaning
    space (key or cell name, umlaut-tolerant). (None, None) when her lens has
    no such space. Profile data; it decides no event and no state.
    V63: placeholder cells are not her lens (authored_compass)."""
    want = _fold_space(space)
    comp = authored_compass(character)
    if not want:
        return None, None
    for key, cell in comp.items():
        if isinstance(cell, dict) and want in (_fold_space(key), _fold_space(cell.get("space"))):
            return str(key), cell
    return None, None


def _apply_relation_target(session: dict, owner_id: str, target_id: str, values: dict, *, grund: str,
                           cause_fact_id: str | None, allow_verified_partial_retry: bool = False) -> dict | None:
    """V60/V61 RelationshipState writer (AMASTER §44, §45, §68 Nr. 63/85),
    extracted unchanged from apply_synapses so the appraisal step uses the SAME
    owner: the proposal is the owner's NEW target value; the change is the
    difference, bounded to ±0.15 per cause; an echo is no change; one cause
    changes a dyad once (idempotency: cause_fact_id per directed dyad); the
    avatar's relationship is never written by the system (§27.3)."""
    if not owner_id or not target_id or owner_id == target_id or not grund:
        return None
    if owner_id == str(session.get("avatarId") or ""):
        return None
    hit = _ensure_directed_rel(session, owner_id, target_id, cause=cause_fact_id)
    applied = [str(x) for x in (hit.get("appliedCauses") or [])]
    if cause_fact_id and str(cause_fact_id) in applied and not allow_verified_partial_retry:
        return None
    b = {k: hit.get(k) for k in ("trust", "closeness", "fear")}
    for key in ("trust", "closeness", "fear"):
        try:
            want_v = _clamp01(float(values.get(key)))
        except (TypeError, ValueError):
            continue
        cur = float(hit.get(key) or 0)
        delta = max(-0.15, min(0.15, want_v - cur))
        if abs(delta) >= 0.005:
            hit[key] = round(_clamp01(cur + delta), 3)
    out = None
    if any(b[k] != hit.get(k) for k in b):
        # The stem note stays the relationship description; the event
        # reason is kept separately (§44, §14), never appended to it.
        hit["lastChangeReason"] = grund[:160]
        hit["sourceFactId"] = cause_fact_id
        out = {"toId": target_id, "before": b, "after": {k: hit.get(k) for k in b}, "grund": grund[:160]}
    if cause_fact_id:
        hit["appliedCauses"] = (applied + [str(cause_fact_id)])[-12:]
    return out


def fire_from_proposals(character: dict, proposals: dict | None, runtime: dict | None = None) -> list[dict]:
    """V37 (AMASTERv2 §15/§48/§51): Das LLM schlägt vor, welche Bedeutungsräume die Äußerung
    für DIESE Figur berührt (semantische Synapse). Der Kernel validiert: nur bekannte Räume,
    Aktivierung 0..1, Schwelle und Reaktion aus dem Kompass der Figur. Kein Vorschlag wird
    ohne Kompass-Zelle wirksam; der Kernel bleibt Owner."""
    if not isinstance(proposals, dict):
        return []
    rows = proposals.get("synapsen") or proposals.get("synapses") or []
    if not isinstance(rows, list):
        return []
    compass = character.get("compass") if isinstance(character.get("compass"), dict) else {}
    out: list[dict] = []
    for row in rows[:6]:
        if not isinstance(row, dict):
            continue
        # V62 (AMASTER §15 "editierbare Verhaltenslinse"): valid spaces are the
        # figure's OWN compass keys; the shared inventory stays the tolerance
        # for figures without that key. Comparison run 27.10.: Mara's compass
        # space "Naehe" (proposed as "Nähe") was not in the global list and
        # was dropped in 9 of 13 turns; Clara/Robert ("Gewissen", "Dominanter
        # Trieb") could never fire.
        space, cell = compass_cell(character, str(row.get("raum") or row.get("space") or ""))
        if space is None:
            want = _fold_space(row.get("raum") or row.get("space"))
            space = next((m for m in MEANING_SPACES if _fold_space(m) == want), "")
            if not space:
                continue
            cell = compass.get(space) if isinstance(compass.get(space), dict) else dict(_DEFAULT_LENS_CELL)
        try:
            act = max(0.0, min(1.0, float(row.get("aktivierung") if row.get("aktivierung") is not None else row.get("activation") or 0)))
        except (TypeError, ValueError):
            continue
        try:
            threshold = float(cell.get("threshold") if cell.get("threshold") is not None else 0.42)
        except (TypeError, ValueError):
            threshold = 0.42
        # Persona-Disposition wie in der lexikalischen Linse: |stance| verstärkt
        try:
            act = min(1.0, act + abs(float(cell.get("stance") or 0)) * 0.12)
        except (TypeError, ValueError):
            pass
        if act < threshold:
            continue
        out.append({
            "space": space,
            "activation": round(act, 4),
            "source": "llm",
            "reason": str(row.get("grund") or row.get("reason") or "")[:160],
            "cell": {"reaction": cell.get("reaction") or "", "bodyCue": cell.get("bodyCue") or "", "drive": cell.get("drive") or "", "speech": cell.get("speech")},
        })
    out.sort(key=lambda r: -float(r.get("activation") or 0))
    return out


def merge_fired(lexical: list[dict] | None, llm: list[dict] | None) -> list[dict]:
    by: dict[str, dict] = {}
    for row in list(lexical or []) + list(llm or []):
        if not isinstance(row, dict) or not row.get("space"):
            continue
        sp = str(row["space"])
        cur = by.get(sp)
        if cur is None or float(row.get("activation") or 0) > float(cur.get("activation") or 0):
            merged = dict(row)
            if cur is not None and cur.get("source") != row.get("source"):
                merged["source"] = "lexikalisch+llm"
            by[sp] = merged
        elif cur is not None and cur.get("source") != row.get("source"):
            cur["source"] = "lexikalisch+llm"
    rows = list(by.values())
    rows.sort(key=lambda r: -float(r.get("activation") or 0))
    return rows


def apply_synapses(session: dict, speaker: dict, fired: list[dict], *, cause_fact_id: str | None, turn: int, proposals: dict | None = None, present: list[dict] | None = None) -> dict[str, Any]:
    """Compass synapses change the figure's current runtime and leave a cause fact.

    AMASTER §24.2/§44/§50: a figure reply is NOT an independent proof for its
    own LLM-proposed persistent relation delta. Such changes belong to the
    separately reviewed appraisal writer, never to this fallback.
    """
    sid = str(speaker.get("id") or "")
    if not sid or not fired:
        return {}
    rt = session.setdefault("runtimes", {}).setdefault(sid, {"characterId": sid, "emotion": "wach", "intensity": 0.35})
    before = {k: rt.get(k) for k in ("emotion", "intensity", "fear", "anger", "shame", "trust", "stress", "intent", "activeCause")}
    top = fired[0] if fired else {}
    space = str(top.get("space") or "")
    act = float(top.get("activation") or 0)
    emo = _SYNAPSE_EMOTION.get(space, "wach")
    if fired and (act >= 0.5 or str(rt.get("emotion") or "wach") in ("", "wach", "calm")):
        if emo != "wach":
            rt["emotion"] = emo
        rt["intensity"] = round(max(float(rt.get("intensity") or 0.35), min(1.0, act)), 3)
        rt["activeCause"] = cause_fact_id or rt.get("activeCause")
        rt["activeCauseText"] = f"Synapse {space}"
    for row in fired[:3]:
        sp = str(row.get("space") or ""); a = float(row.get("activation") or 0); scale = min(1.0, 0.4 + a)
        spec = _KNOWLEDGE_EFFECT.get(sp) or {}
        for key, delta in (spec.get("runtime") or {}).items():
            rt[key] = round(_clamp01(float(rt.get(key) or 0) + delta * scale * 0.7), 3)
        drive = str((row.get("cell") or {}).get("drive") or "").strip()
        if drive and row is top:
            rt["intent"] = drive[:120]
    changed = {k: {"from": before.get(k), "to": rt.get(k)} for k in before if before.get(k) != rt.get(k)}
    # Relation proposals of the same reply are kept in its UI/audit result,
    # but have no direct canonical writer without independent causal evidence.
    _syn_text = (f"{speaker.get('name') or sid}: Synapsen " + ", ".join(
        f"{r.get('space')} {float(r.get('activation') or 0):.2f}" for r in fired[:3])
        + (f" → {rt.get('emotion')}" if changed.get('emotion') else ""))
    fact = make_fact(
        turn=turn,
        actorId=sid,
        targetId=None,
        kind="synapse",
        event_kind="synapse",
        text=_syn_text,
        authority="character",
        **fact_provenance(session, cause_fact_id),   # V65Z (A01)
        truth={"user_id": session.get("userId"), "world_id": session.get("worldId"), "session_id": session.get("id")},
        scene=session.get("scene") or {},
        witnessedBy=[sid],
        affected_ids=[sid],
        payload={"kind": "synapse", "fired": [{"space": r.get("space"), "activation": r.get("activation"), "source": r.get("source") or "lexikalisch", "reason": r.get("reason")} for r in fired[:4]], "runtimeDelta": changed, "relationDelta": [], "sourceFactId": cause_fact_id},
        source_type="synapse",
        provenance="kernel",
        validated=True,
    )
    session.setdefault("facts", []).append(fact)
    return {"fired": fired, "runtimeDelta": changed, "relationDelta": [], "factId": fact["id"]}


# --- V62: Erleben / Bewertung wahrgenommener Ereignisse ----------------------
# AMASTER §28 Schritt 12/13 (Eingang committen, "unmittelbare Folgezustände"
# fortschreiben, BEVOR Runtime geladen und das LLM gerufen wird), §24.2
# ("kausale Folge-Effects"), §42 (Disposition -> Affect -> Intent; gerichtete
# Zustände mit Owner, Target, Intensität, cause_fact_id, started/last_reinforced,
# decay_policy, resolved_by), §44 (Interpretation je Relationship-Owner,
# cause_fact_id, Idempotenz), §15 (Kompass = Linse inkl. Hemmschwelle),
# §27.3 (nie der Avatar), §39 (nur Wahrgenommenes), §50 (LLM schlägt vor, der
# Kernel validiert und schreibt).
# Before V62 the figure's state changed only after her own answer, from a
# fixed table space -> emotion over a global space list, never for listeners,
# never decaying (comparison run 27.10.: Mara "Nähe 0.35" in 13 of 13 turns,
# intent empty in 13 of 13).

APPRAISAL_DECAY_PER_TURN = 0.75      # decay_policy "turn": intensity x 0.75 per session turn without reinforcement
APPRAISAL_RESOLVE_BELOW = 0.15       # below this an appraisal affect is resolved (resolved_by "decay")
APPRAISAL_MAX_STATE_STEP = 0.25      # bounded change of a runtime scalar per appraisal
APPRAISAL_MAX_EVENTS = 4             # newest perceived events per figure and call
APPRAISAL_WINDOW_TURNS = 2           # older unappraised events are past moments
APPRAISAL_PERCEPTION = ("heard", "seen", "affected")
APPRAISAL_STATE_KEYS = {"angst": "fear", "wut": "anger", "scham": "shame", "stress": "stress", "lust": "lust"}
APPRAISAL_BASELINE = {"emotion": "wach", "intensity": 0.35}
_APPRAISAL_EVENT_KINDS = ("speech", "action", "physical")


def appraisal_effect_fields(row: dict) -> list[str]:
    """AMASTER §24.2/§42/§44/§50: enumerate every proposed state effect.

    These are existing Runtime/Relationship fields, not new behavioural rules.
    Each requires its own independently checked, witnessed cause before write.
    """
    if not isinstance(row, dict):
        return []
    fields = []
    if str(row.get("gefuehl") or "").strip():
        fields.append("gefuehl")
    if str(row.get("absicht") or "").strip().casefold() not in ("", "neutral", "keine", "unbestimmt", "-"):
        fields.append("absicht")
    state = row.get("zustand_aenderung") if isinstance(row.get("zustand_aenderung"), dict) else {}
    for key in APPRAISAL_STATE_KEYS:
        try:
            if abs(float(state.get(key) or 0)) > 1e-9:
                fields.append("zustand." + key)
        except (ValueError, TypeError, OverflowError):
            pass
    changes = row.get("beziehung_aenderung")
    changes = [changes] if isinstance(changes, dict) else (changes if isinstance(changes, list) else [])
    for i, relation in enumerate(changes):
        if not isinstance(relation, dict):
            continue
        for key in ("trust", "closeness", "fear"):
            try:
                if abs(float(relation.get(key) or 0)) > 1e-9:
                    fields.append(f"beziehung.{i}.{key}")
            except (ValueError, TypeError, OverflowError):
                pass
    return fields


def appraisal_disposition_sources(session: dict, character: dict, figure_id: str, involved_ids: set[str]) -> list[str]:
    """§15/§44: existing canonical disposition read by the appraisal, no new
    judgement or truth owner. A review must point to this owner's actual data;
    the model's claim that a profile *might* justify something is not evidence.
    Only directed relationships to actors of the perceived facts are included.
    """
    # The appraisal payload reads the approved stem projection. The proof
    # validator MUST use that same projection: raw learnedItems may contain
    # unapproved, session-only claims that are not personality truth (§15).
    from matrix_api.learning import canonical_stem
    character = canonical_stem(character)
    sources: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            sources.append(" ".join(value.split()))
        elif isinstance(value, (list, tuple)):
            for item in value:
                add(item)

    for field in ("personality", "biography", "values", "fears", "taboos", "likes", "dislikes", "goals"):
        add(character.get(field))
    compass = character.get("compass")
    if isinstance(compass, dict):
        for cell in compass.values():
            if isinstance(cell, dict):
                for field in ("reaction", "drive", "bodyCue"):
                    add(cell.get(field))
    for rel in character.get("relations") or []:
        if isinstance(rel, dict) and str(rel.get("targetId") or "") in involved_ids:
            add(rel.get("note"))
            if rel.get("kind") not in ("knows", "unknown", "neutral"):
                add(rel.get("kind"))
    for rel in session.get("relations") or []:
        if isinstance(rel, dict) and str(rel.get("fromId") or "") == figure_id and str(rel.get("toId") or "") in involved_ids:
            add(rel.get("note"))
            if rel.get("kind") not in ("knows", "unknown", "neutral"):
                add(rel.get("kind"))
    for goal in session.get("goals") or []:
        if isinstance(goal, dict) and str(goal.get("characterId") or goal.get("ownerId") or "") == figure_id:
            add(goal.get("text") or goal.get("description"))
    return list(dict.fromkeys(sources))


def appraisal_source_id(text: str) -> str:
    """V92 (Kettenvertrag §6, AMASTER §24.2/§44 Provenienz): the stable server-side id of ONE disposition source. It is derived
    from the source text itself, so the review that is shown the source and the validator that checks the citation use the
    same owner and the same id (before: the review quoted a rendered profile projection, the validator knew atomic strings)."""
    import hashlib
    return "Q" + hashlib.sha1(" ".join(str(text or "").split()).casefold().encode("utf-8")).hexdigest()[:8]


def appraisal_disposition_source_list(session: dict, character: dict, figure_id: str, involved_ids: set[str]) -> list[dict]:
    """The sources of `appraisal_disposition_sources` with their ids - shown to the independent review, never invented."""
    return [{"id": appraisal_source_id(t), "text": t} for t in appraisal_disposition_sources(session, character, figure_id, involved_ids)]


def appraisal_field_sign(row: dict, field: str) -> int:
    """Vorzeichen der vorgeschlagenen Änderung eines Zahlenfelds (+1/-1), sonst 0 (gefuehl/absicht)."""
    try:
        parts = field.split(".")
        if parts[0] == "zustand" and len(parts) == 2:
            v = float((row.get("zustand_aenderung") or {}).get(parts[1]) or 0)
        elif parts[0] == "beziehung" and len(parts) == 3:
            rels = row.get("beziehung_aenderung")
            rels = [rels] if isinstance(rels, dict) else rels if isinstance(rels, list) else []
            v = float(rels[int(parts[1])].get(parts[2]) or 0)
        else:
            return 0
        return 1 if v > 0 else -1 if v < 0 else 0
    except (AttributeError, TypeError, ValueError, OverflowError, IndexError):
        return 0


def _appraisal_positive_relation_field(row: dict, field: str) -> bool:
    try:
        _, index, dimension = field.split(".")
        rels = row.get("beziehung_aenderung")
        rels = [rels] if isinstance(rels, dict) else rels if isinstance(rels, list) else []
        return isinstance(rels[int(index)], dict) and float(rels[int(index)].get(dimension) or 0) > 0
    except (AttributeError, TypeError, ValueError, OverflowError, IndexError):
        return False


def _appraisal_cause_has_unresolved_adverse_effect(fact: dict, pending: dict, owner_id: str) -> bool:
    """AMASTER §44/§50: evaluate a proposed durable relation against the
    *same canonical source turn's* already validated physical consequences.

    This is not a fixed reaction to a word or a particular character: only
    an observed adverse change to THIS owner's PhysicalState counts. An
    action-specific consent is not inferred from affection, sensation,
    or the execution of the act (§36.5).

    A contrary positive relationship update needs a separate canonical
    supportive event/accepted action, not the attacker's or reviewer LLM's
    assertion that harm itself proves trust. The remaining fields and
    other independent causes retain their own validations.
    """
    if not isinstance(fact, dict):
        return False
    source_turn = str(fact.get("source_turn_id") or fact.get("sourceTurnId") or "")
    if not source_turn:
        return False
    # A formally accepted action-specific consent is a distinct canonical
    # proposition. Unknown/expired/declined states cannot grant permission.
    actor_id = str(fact.get("actorId") or "")
    target_id = str(fact.get("targetId") or "")
    action_text = " ".join(str(fact.get("text") or "").split())

    def _same_act(other: dict) -> bool:
        return (str(other.get("source_turn_id") or other.get("sourceTurnId") or "") == source_turn
                and str(other.get("actorId") or "") == actor_id
                and str(other.get("targetId") or "") == target_id
                and " ".join(str(other.get("text") or "").split()) == action_text)

    # Consent is not a relationship benefit (AMASTER §36.5). Even if an
    # action-specific consent exists, the harmful bodily effect itself does
    # not establish increased directed trust or closeness. Only a distinct,
    # independently proven supportive cause can authorize that delta.

    for event in pending.get("events") or []:
        if not isinstance(event, dict):
            continue
        physical = event.get("fact")
        if not isinstance(physical, dict) or physical.get("kind") != "physical" or not _scene.validiert(physical):
            continue
        if not _same_act(physical):
            continue
        affected = {str(x) for x in (physical.get("affected_ids") or [])}
        if owner_id not in affected and str(physical.get("targetId") or "") != owner_id:
            continue
        delta = (physical.get("payload") or {}).get("delta") if isinstance(physical.get("payload"), dict) else None
        if not isinstance(delta, dict):
            continue
        for state_name in ("pain", "fear", "anger", "stress", "mobility"):
            values = delta.get(state_name)
            if not isinstance(values, dict):
                continue
            try:
                before = float(values.get("from") if values.get("from") is not None else (1 if state_name == "mobility" else 0))
                after = float(values.get("to"))
            except (TypeError, ValueError, OverflowError):
                continue
            if state_name == "mobility" and after < before - 1e-9:
                return True
            if state_name != "mobility" and after > before + 1e-9:
                return True
    return False


def _appraisal_cause_proofs(row: dict, pending: dict, entry: dict, disposition_by_field: dict[str, list[str]]) -> dict[str, dict]:
    """Validate INDEPENDENT review (not the proposing model's reasoning).

    Each nonzero effect needs the requested field, a real perceived/validated
    SceneFact id and an actual literal citation in that Fact. A model verdict
    cannot invent a Fact, add a non-witnessed cause or approve other fields.
    Fail-closed only for the unproved effect; unrelated effects remain eligible.
    """
    expected = appraisal_effect_fields(row)
    events = {str(e.get("fact", {}).get("id")): e.get("fact") for e in pending.get("events") or []
              if isinstance(e, dict) and isinstance(e.get("fact"), dict)
              and e.get("access") in APPRAISAL_PERCEPTION and _scene.validiert(e["fact"])}
    raw = row.get("_kausalpruefung")
    checks = raw.get("pruefungen") if isinstance(raw, dict) else None
    checks = checks if isinstance(checks, list) else []
    accepted: dict[str, dict] = {}
    for field in expected:
        matches = [x for x in checks if isinstance(x, dict) and x.get("feld") == field]
        if len(matches) != 1:
            entry["rejects"].append("kausalpruefung_fehlend:" + field)
            continue
        ch = matches[0]
        fid = str(ch.get("factId") or "")
        fact = events.get(fid)
        quote = str(ch.get("beleg") or "").strip()
        reason = str(ch.get("begruendung") or "").strip()
        # The independent evaluator must cite an actual individual disposition,
        # not just recite the witnessed incident. This is provenance validation,
        # NOT a judgement that the person must react positively or negatively.
        disposition_quote = " ".join(str(ch.get("dispositionsBeleg") or "").split())
        # V92: a cited source id (dispositionsQuelle) binds the quote to exactly that source of this field; without an id
        # the quote must still be literal in one of the field's sources (unchanged contract)
        _src_id = str(ch.get("dispositionsQuelle") or "").strip()
        _field_sources = disposition_by_field.get(field, [])
        _candidates = [v for v in _field_sources if appraisal_source_id(v) == _src_id] if _src_id else _field_sources
        individual_source = (
            bool(disposition_quote)
            and any(
                _scene.literal_in(disposition_quote, value)
                and (len(disposition_quote.split()) >= 2
                     or _fold_space(disposition_quote) == _fold_space(value))
                for value in _candidates
            )
            and _scene.literal_in(disposition_quote, reason)
        )
        if ch.get("urteil") not in ("gestuetzt", "nicht_gestuetzt"):
            entry["rejects"].append("kausalurteil_ungueltig:" + field)
        elif ch.get("urteil") == "nicht_gestuetzt":
            # This is a conclusive *negative* review, not a transport or
            # validation failure. No effect is committed.
            entry["rejects"].append("wirkung_nicht_belegt:" + field)
        elif fact is None:
            entry["rejects"].append("ursache_nicht_wahrgenommen:" + field)
        elif not quote or not _scene.literal_in(quote, str(fact.get("text") or "")):
            entry["rejects"].append("ursache_nicht_woertlich:" + field)
        elif not reason:
            entry["rejects"].append("begruendung_fehlt:" + field)
        elif not individual_source:
            entry["rejects"].append("disposition_nicht_belegt:" + field)
        elif appraisal_field_sign(row, field) and str(ch.get("richtung") or "").strip().casefold() != (
                "steigt" if appraisal_field_sign(row, field) > 0 else "sinkt"):
            # V92: the cited source must carry the DIRECTION of the change, not merely the topic
            entry["rejects"].append("richtung_nicht_belegt:" + field)
        elif (field.startswith("beziehung.")
              and field.rsplit(".", 1)[-1] in ("trust", "closeness")
              and isinstance(fact, dict)
              and _appraisal_cause_has_unresolved_adverse_effect(fact, pending, str(pending.get("id") or ""))
              and _appraisal_positive_relation_field(row, field)):
            # A genuine witnessed bodily deterioration cannot *by itself*
            # substantiate an improvement in trust/closeness. A later
            # supportive event may be proven separately; this rejects only
            # the unsupported field and never dictates the character's speech.
            entry["rejects"].append("koerperfolge_widerspricht_beziehungsanstieg:" + field)
        else:
            accepted[field] = {"factId": fid, "beleg": quote[:220],
                               "dispositionsBeleg": disposition_quote[:220], "begruendung": reason[:240],
                               **({"richtung": str(ch.get("richtung")).strip().casefold()} if appraisal_field_sign(row, field) else {}),
                               **({"dispositionsQuelle": _src_id} if _src_id else {})}
    if accepted:
        entry["kausalBelege"] = copy.deepcopy(accepted)
    return accepted


def avatar_identity_name(session: dict, figures: list[dict] | None = None) -> str:
    """V63 — the ONE owner of the avatar's name in figure-facing readers.

    AMASTER §24.1 Z. 1083–1096 and §68 Nr. 51 (Z. 3400): control binding (the
    user plays the avatar) and identity are separate. The world figure the user
    controls keeps its canonical name; the session alias is the control label.
    Only an avatar without a named figure record falls back to the alias.
    Session 13:39, 27.10.: avatar Tom, alias left at the start default
    "Spieler" -> Tamara's brief named the same person "Spieler" (history,
    state, scene) and "Tom" (current line, relations, Regie) while her goal
    read "Vollständige Kontrolle über Tom"."""
    aid = str(session.get("avatarId") or "")
    if aid:
        for f in figures or []:
            if isinstance(f, dict) and str(f.get("id") or "") == aid and str(f.get("name") or "").strip():
                return str(f["name"]).strip()
        for r in session.get("relations") or []:
            if isinstance(r, dict):
                if str(r.get("fromId") or "") == aid and str(r.get("fromName") or "").strip():
                    return str(r["fromName"]).strip()
                if str(r.get("toId") or "") == aid and str(r.get("toName") or "").strip():
                    return str(r["toName"]).strip()
    return str(session.get("alias") or ("Avatar" if aid else ""))


_OPERATOR_IDS = ("user", "operator")


def operator_label(session: dict, truth: dict | None = None, figures: list[dict] | None = None) -> str:
    """V65F — the ONE name of the real user speaking as Bedienperson (Teilnehmer
    without avatar) in figure-facing readers.

    AMASTER §8 "Der reale Nutzer ist nicht automatisch eine Figur", §27.2 (ob er
    über einen Avatar spricht oder außerhalb der Welt bleibt, wird ausdrücklich
    gebunden), §23 (eine ID bedeutet nicht in einer Phase Userprofil und in der
    nächsten etwas anderes), §24.1/§68 Nr. 4/51. Session 05:33, 28.10.: input
    actor "user", speakAs "operator"; the brief said "Spieler ist eine Figur der
    Welt", the matters said "user"/"Die Bedienperson", the open matter had no
    name at all ("s Forderung"). The label keeps the Bedienperson marker; a label
    that is the avatar's name is not used (control binding is not identity)."""
    name = ""
    if truth and str(truth.get("input_actor_id") or truth.get("inputActorId") or "") in _OPERATOR_IDS:
        name = str(truth.get("user_name") or truth.get("userName") or "").strip()
    if not name:
        for t in reversed(session.get("turns") or []):
            if isinstance(t, dict) and str(t.get("speakerId") or "") in _OPERATOR_IDS and str(t.get("speakerName") or "").strip():
                name = str(t["speakerName"]).strip()
                break
    if "(Bedienperson" in name:
        return name
    av = avatar_identity_name(session, figures) if session.get("avatarId") else ""
    # Control aliases label a UI session, not a real person's identity.
    # A legacy user line bearing the same alias is not reliable name evidence.
    alias = str(session.get("alias") or "").strip()
    explicit = str((truth or {}).get("user_name") or (truth or {}).get("userName") or "").strip()
    if (not name or (av and name.casefold() == av.casefold()) or
            (alias and name.casefold() == alias.casefold() and not explicit)):
        return "Bedienperson (außerhalb der Welt)"
    return f"{name} (Bedienperson, außerhalb der Welt)"


# --- V65G: 171 Partnerbindung und Handlungsfreigabe (ActionPermission) -------
# Uebernommen aus 171 (chat_orchestrator S40a/S40b/S41b, relationship_policy.py,
# data/shared/relationship_policy.json). AMASTER: §44 (die Interpretation eines
# Ereignisses beruecksichtigt pro Owner die bisherige gerichtete Beziehung),
# §26/§41 Constraint Context (Anwesenheit, Beziehung), §41.3 (Linsenauswahl ist
# Reader-Selektion), §8/§6 (die Bedienperson ist keine Figur), §36.5 (diese
# Freigabe ist KEINE gespeicherte Zustimmung: sie wird nirgends als Consent
# geschrieben; was die Figur tut, entscheidet ihre eigene Antwort).
_REL_POLICY: dict[str, Any] = {"mtime": None, "policy": None}


def _norm_kind(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def relationship_policy() -> dict | None:
    """The data source (matrix_api/relationship_policy.json), cached per mtime.
    Missing or broken -> None = safe mode (nothing intimate is carried), as 171."""
    import json as _json
    from pathlib import Path as _Path
    path = _Path(__file__).with_name("relationship_policy.json")
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _REL_POLICY.update({"mtime": None, "policy": None})
        return None
    if _REL_POLICY.get("mtime") == mtime and _REL_POLICY.get("policy") is not None:
        return _REL_POLICY["policy"]
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
        types = {_norm_kind(k): {f: bool((v or {}).get(f)) for f in ("counts_as_social_bond", "allows_romantic_emotion",
                                                                     "allows_intimate_room", "allows_intimate_action")}
                 for k, v in (data.get("relationship_types") or {}).items() if isinstance(v, dict)}
        rooms = {_norm_kind(x) for x in ((data.get("compass_room_classes") or {}).get("intimate") or [])}
        policy = {"types": types, "intimate_rooms": rooms}
    except Exception:
        policy = None
    _REL_POLICY.update({"mtime": mtime, "policy": policy})
    return policy


def _kind_flags(kind: Any, policy: dict | None) -> dict:
    row = ((policy or {}).get("types") or {}).get(_norm_kind(kind)) or {}
    return {f: bool(row.get(f)) for f in ("counts_as_social_bond", "allows_romantic_emotion", "allows_intimate_room", "allows_intimate_action")}


def _bond_row(session: dict, speaker: dict, target_id: str, target_name: str) -> tuple[dict | None, str]:
    """The directed relationship speaker -> target: session RelationshipState
    first; without one the Stamm relation of the speaker (171 S40a: Stamm seed
    before reading, so a Stamm bond such as 'lover' is known in turn one)."""
    sid = str((speaker or {}).get("id") or "")
    hit = next((r for r in session.get("relations") or [] if isinstance(r, dict)
                and str(r.get("fromId") or "") == sid and str(r.get("toId") or "") == str(target_id)), None)
    if isinstance(hit, dict):
        return hit, "session"
    tn = _norm_kind(target_name)
    for r in (speaker or {}).get("relations") or []:
        if not isinstance(r, dict):
            continue
        if (target_id and str(r.get("targetId") or r.get("target_id") or "") == str(target_id)) or (tn and _norm_kind(r.get("targetName")) == tn):
            return r, "stamm"
    return None, "none"


def action_permission_frame(session: dict, speaker: dict, partner_id: str | None, present: list[dict] | None) -> dict | None:
    """171 S41b-1 ActionPermissionFrame, per turn, for the speaker and her CURRENT
    counterpart (the one whose line/act is her stimulus). Read only.
    - partner bond (171 _v151_partner_bond): social/romantic type or trust/closeness >= 0.6
    - an existing bond to SOMEONE ELSE (171 BOND-EXISTENCE): romantic type, or social
      type with trust >= 0.7, or trust >= 0.75, or closeness >= 0.7 (171 thresholds /100).
    V65P (AMASTER §36.5 "Liebe ist keine Zustimmung", Pruefung v2.7): the frame
    carries NO permission or consent any more. V65G derived
    "intimateActionAccepted" from the relationship TYPE (lover = accepted) and
    mirrored it as "intime Naehe getragen"; M10 has no act-bound consent state,
    so nothing is mirrored as consent. Kept: relationship values and type, the
    bond to someone else, and `intimateRoomsLens` - the policy flag
    allows_intimate_room for the READER selection of the compass lens (§41.3),
    which is not a consent."""
    pid = str(partner_id or "")
    if not pid or pid in ("regie", "god", "narrator") or not isinstance(speaker, dict) or pid == str(speaker.get("id") or ""):
        return None
    policy = relationship_policy()
    if pid in _OPERATOR_IDS:
        pname = operator_label(session, None, present)
        rel, source = None, "none"          # §8/§6: no RelationshipState with the Bedienperson
    else:
        pname = (avatar_identity_name(session, present) if pid == str(session.get("avatarId") or "") else _name_of(pid, present or [], session))
        rel, source = _bond_row(session, speaker, pid, pname)
    kind = str((rel or {}).get("kind") or "")
    tr = float((rel or {}).get("trust") or 0)
    pr = float((rel or {}).get("closeness") or 0)
    flags = _kind_flags(kind, policy) if rel else _kind_flags("", policy)
    partner_bond = bool(rel) and (flags["counts_as_social_bond"] or flags["allows_romantic_emotion"] or tr >= 0.6 or pr >= 0.6)
    rooms_lens = bool(rel) and policy is not None and flags["allows_intimate_room"]
    present_ids = set((session.get("scene") or {}).get("presentIds") or [])
    other = None
    seen = set()
    rows = [(r, str(r.get("toId") or ""), _name_of(str(r.get("toId") or ""), present or [], session)) for r in session.get("relations") or []
            if isinstance(r, dict) and str(r.get("fromId") or "") == str(speaker.get("id") or "")]
    rows += [(r, str(r.get("targetId") or r.get("target_id") or ""), str(r.get("targetName") or "")) for r in (speaker.get("relations") or [])
             if isinstance(r, dict) and r.get("targetName")]
    for r, tid, tname in rows:
        key = _norm_kind(tname) or tid
        if not key or key in seen or tid == pid or (tname and _norm_kind(tname) == _norm_kind(pname)):
            continue
        seen.add(key)
        f = _kind_flags(r.get("kind"), policy)
        rtr, rpr = float(r.get("trust") or 0), float(r.get("closeness") or 0)
        if f["allows_romantic_emotion"] or (f["counts_as_social_bond"] and rtr >= 0.7) or rtr >= 0.75 or rpr >= 0.7:
            other = {"name": tname or tid, "kind": str(r.get("kind") or "") or "enge Bindung",
                     "present": any(str(p.get("id") or "") in present_ids and _norm_kind(p.get("name")) == _norm_kind(tname)
                                    for p in (present or []) if isinstance(p, dict)) or tid in present_ids}
            break
    return {"partnerId": pid, "partnerName": pname, "isFigure": pid not in _OPERATOR_IDS,
            "relation": ({"kind": kind or "knows", "trust": round(tr, 2), "closeness": round(pr, 2), "source": source} if rel else None),
            "partnerBond": partner_bond, "intimateRoomsLens": rooms_lens,
            "flags": flags, "otherBond": (other if not partner_bond else None), "policyLoaded": policy is not None}


def _person_name(session: dict, natives: list[dict] | None, cid: str | None) -> str:
    cid = str(cid or "")
    if not cid:
        return ""
    if cid == str(session.get("avatarId") or ""):
        return avatar_identity_name(session, natives)
    if cid in _OPERATOR_IDS:
        return operator_label(session, None, natives)   # V65F: no raw "user"
    hit = next((c for c in natives or [] if isinstance(c, dict) and str(c.get("id") or "") == cid), None)
    # V65T (AMASTER §23 ein Name je Person in jedem Leser; found 30.10. in Maras Brief deiner Session: "Ausgang:
    # char_g7_johann hat dich danach wieder erreicht" - Johann was absent, so not in the given list): an absent
    # figure is named from the session's own sources (_name_of: turns, relations), never by its raw ID.
    return str((hit or {}).get("name") or _name_of(cid, list(natives or []), session))


def _affect_now(affect: dict, turn_now: int) -> float:
    """decay_policy "turn": pure function of base intensity and elapsed turns."""
    try:
        base = float(affect.get("base") or 0)
        since = int(affect.get("reinforcedTurn") or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(base * (APPRAISAL_DECAY_PER_TURN ** max(0, int(turn_now) - since)), 4)


def pending_appraisals(session: dict, natives: list[dict] | None) -> list[dict]:
    """Read-only: per present non-avatar figure, the validated events of OTHER
    actors she perceived (WitnessKnowledge heard/seen/affected, §39) and has not
    appraised yet. The figure's own deeds are not appraised by herself."""
    avatar = str(session.get("avatarId") or "")
    present = [str(x) for x in ((session.get("scene") or {}).get("presentIds") or [])]
    by_id = {str(c.get("id")): c for c in natives or [] if isinstance(c, dict) and c.get("id")}
    facts = [f for f in session.get("facts") or [] if isinstance(f, dict) and f.get("id")]
    order = {str(f.get("id")): i for i, f in enumerate(facts)}
    by_fid = {str(f.get("id")): f for f in facts}
    turn = int(session.get("turnIndex") or 0)
    # Window of recent turns (events older than that are past moments). The
    # previous answer (turn N-1) is inside it for the listeners. Probe 27.10.:
    # a session-level start marker was not a persisted envelope field, so
    # listeners never appraised the previous answer.
    since = turn - APPRAISAL_WINDOW_TURNS
    out: list[dict] = []
    for cid in present:
        if cid == avatar or cid not in by_id:
            continue
        rt = (session.get("runtimes") or {}).get(cid) or {}
        done = {str(x) for x in (rt.get("appraisedFactIds") or [])}
        seen: dict[str, dict] = {}
        for w in session.get("witnessKnowledge") or []:
            if not isinstance(w, dict) or str(w.get("character_id") or w.get("characterId") or "") != cid:
                continue
            if w.get("access") not in APPRAISAL_PERCEPTION:
                continue
            fid = str(w.get("fact_id") or w.get("factId") or "")
            f = by_fid.get(fid)
            if f is None or fid in done or fid in seen:
                continue
            if f.get("kind") not in _APPRAISAL_EVENT_KINDS or not _scene.validiert(f):
                continue
            if str(f.get("actorId") or "") in ("", cid) or int(f.get("turn") or 0) < since:
                continue
            if str(f.get("text") or "").strip() in ("", "—"):
                continue
            seen[fid] = {"fact": f, "access": w.get("access")}
        if not seen:
            continue
        events = sorted(seen.values(), key=lambda e: order.get(str(e["fact"].get("id")), 0))
        out.append({"id": cid, "name": str(by_id[cid].get("name") or cid),
                    "events": events[-APPRAISAL_MAX_EVENTS:], "superseded": [str(e["fact"]["id"]) for e in events[:-APPRAISAL_MAX_EVENTS]]})
    return out


def _appraisal_profile(c: dict) -> dict:
    """V63: the disposition fields of the stem that the owner's interpretation
    needs (§44, §15) — each only when filled; nothing derived."""
    def _lst(key: str) -> list[str]:
        v = c.get(key)
        rows = v if isinstance(v, list) else ([v] if isinstance(v, str) and v.strip() else [])
        return [" ".join(str(x).split())[:80] for x in rows if str(x).strip()][:6]
    out: dict[str, Any] = {}
    for label, key in (("persoenlichkeit", "personality"), ("sprache", "speechRegister"), ("rolle", "role")):
        if str(c.get(key) or "").strip():
            out[label] = " ".join(str(c.get(key)).split())[:240]
    for label, key in (("werte", "values"), ("aengste", "fears"), ("tabus", "taboos"),
                       ("mag", "likes"), ("mag_nicht", "dislikes")):
        rows = _lst(key)
        if rows:
            out[label] = rows
    return out


def _grounded_in(text: str, source: str, *, short: bool = False) -> str:
    """V65H (AMASTER §40 "keine neuen Weltfakten erfinden", §24.2 Validierung):
    an LLM restatement of a goal is kept only when its content words come from
    the goal's own text (same word, or same 5-letter stem for longer words).
    No vocabulary of its own; returns the cleaned text or ""."""
    t = " ".join(str(text or "").split())[:(60 if short else 240)]
    toks = re.findall(r"[a-zäöüß]{4,}", t.casefold())
    if not toks:
        return ""
    src = set(re.findall(r"[a-zäöüß]{3,}", str(source or "").casefold()))

    def _hit(w: str) -> bool:
        return any((w[:5] == x[:5]) if (len(w) >= 5 and len(x) >= 5) else (w == x) for x in src)

    return t if sum(1 for w in toks if _hit(w)) / len(toks) >= (0.5 if short else 0.6) else ""


def appraisal_payload(session: dict, natives: list[dict] | None, pending: list[dict]) -> dict:
    """The provider payload: per figure ONLY her own profile, compass, state,
    relationships, open matters and what she perceived (§39, §49)."""
    from matrix_api.learning import canonical_stem
    by_id = {str(c.get("id")): canonical_stem(c) for c in natives or [] if isinstance(c, dict) and c.get("id")}
    persons = sorted({_person_name(session, natives, x) for x in ((session.get("scene") or {}).get("presentIds") or [])} - {""})
    figures = []
    for p in pending:
        cid = p["id"]
        c = by_id.get(cid) or {}
        rt = (session.get("runtimes") or {}).get(cid) or {}
        involved = {str(e["fact"].get(k) or "") for e in p["events"] for k in ("actorId", "targetId")} - {"", cid}
        rels = []
        for oid in sorted(involved):
            r = next((x for x in session.get("relations") or [] if isinstance(x, dict) and x.get("fromId") == cid and x.get("toId") == oid), {}) or {}
            rels.append({"zu": _person_name(session, natives, oid), **{k: round(float(r.get(k) or 0), 2) for k in ("trust", "closeness", "fear")},
                         **({"art": r.get("kind")} if r.get("kind") else {})})
        offen = []
        for pr in session.get("propositions") or []:
            if not isinstance(pr, dict) or cid not in (str(pr.get("actorId") or ""), str(pr.get("targetId") or "")):
                continue
            if pr.get("status") not in ("open", "active", "accepted", "fulfilled", "declined"):
                continue
            _rest = sum(1 for e in (pr.get("evidence") or []) if isinstance(e, dict) and e.get("kind") == "restated")
            offen.append(f"{_person_name(session, natives, pr.get('actorId'))} → {_person_name(session, natives, pr.get('targetId'))}: "
                         f"{str(pr.get('matter') or pr.get('text') or '')[:140]} (Stand: {pr.get('status')}"
                         + (f"; {_rest + 1}-mal gestellt" if _rest else "") + ")")
        goals = [str(g.get("text") or "")[:120] for g in session.get("goals") or []
                 if isinstance(g, dict) and str(g.get("ownerId") or "") == cid and g.get("status") in ("open", "active", "accepted")][:4]
        comp = authored_compass(c)   # V63: placeholder cells are no lens (§15)
        events = []
        for e in p["events"]:
            f = e["fact"]
            # V65R (AMASTER §36.5): an act on HER against her declined consent carries that state.
            _ctx = act_consent_text(session, f, natives, viewer=cid) if f.get("kind") == "action" and str(f.get("targetId") or "") == str(cid) else None
            events.append({"id": f.get("id"), "turn": f.get("turn"), "wer": _person_name(session, natives, f.get("actorId")),
                           "art": "sagte" if f.get("kind") == "speech" else "tat",
                           "an": _person_name(session, natives, f.get("targetId")),
                           "text": str(f.get("text") or "")[:300],
                           "wahrnehmung": {"heard": "gehört", "seen": "gesehen", "affected": "betroffen"}.get(str(e.get("access")), ""),
                           **({"einwilligung": _ctx} if _ctx else {})})
        ev_turns = {int(e["fact"].get("turn") or 0) for e in p["events"]}
        verlauf = [f"{d.get('name')}: {str(d.get('speech') or '')[:120]}" + (f" *{str(d.get('action'))[:60]}*" if d.get("action") else "")
                   + (f" ({d.get('actionOutcome')})" if d.get("action") and d.get("actionOutcome") else "")
                   for d in _dialogue_visible_to(session, cid, session.get("turns") or [], avatar_identity_name(session, natives),
                                                 operator_label(session, None, natives))
                   if int(d.get("turn") or 0) not in ev_turns or str(d.get("name") or "") == p["name"]][-4:]
        own = next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict) and str(f.get("actorId") or "") == cid
                    and f.get("kind") in ("speech", "action") and _scene.validiert(f)
                    and str(f.get("text") or "").strip() not in ("", "—")), None)
        # V65G (171 S41b-3 "Evaluator an denselben ActionPermission-Frame binden",
        # Z. 16440-16520; AMASTER §44 Interpretation pro Owner mit bisheriger
        # Beziehung): the frame toward the actor of her latest perceived event.
        # V65P (AMASTER §36.5, §15; Pruefung v2.7): no "handlungsfreigabe" any
        # more (it was a permission from the relationship TYPE) and no
        # behaviour clause ("Leite KEINE ... ab; reagiere aus neutraler
        # Haltung ..."); the relationship toward the actor stays as values.
        _ev_actor = str((p["events"][-1]["fact"] if p.get("events") else {}).get("actorId") or "")
        _apf = action_permission_frame(session, c if c else {"id": cid}, _ev_actor, natives) if _ev_actor and _ev_actor != cid else None
        _ap_extra = {}
        if _apf:
            _rel = _apf.get("relation") if isinstance(_apf.get("relation"), dict) else None
            if _rel and _apf.get("partnerBond"):
                _rel_txt = (f"Vertrauen {round(float(_rel.get('trust') or 0) * 100)}/100, Naehe {round(float(_rel.get('closeness') or 0) * 100)}/100, "
                            f"Typ {_rel.get('kind') or 'neutral'}" + (" (Stammbindung)" if _rel.get("source") == "stamm" else ""))
            else:
                _vals = (f"Vertrauen {round(float(_rel.get('trust') or 0) * 100)}/100, Naehe {round(float(_rel.get('closeness') or 0) * 100)}/100, "
                         f"Typ {_rel.get('kind') or 'neutral'}") if _rel else "keine Beziehung, Typ neutral"
                _rel_txt = "zu dieser Person besteht KEIN gewachsener Bund - neutral/fremd (" + _vals + ")."
            # Stand 09 / F1-B2 (AMASTER §44 Interpretation je Owner mit der bisherigen Beziehung, §25 Bindung): the frame
            # belongs to ONE person - the actor of her latest perceived event - and now names her. Before, the bare text
            # ("KEIN gewachsener Bund - neutral/fremd") stood beside a violent act of someone else (measured F1: operator
            # question after Johann's blow) and could be read as the relation to that other person.
            _ap_extra = {"beziehung_zum_handelnden": {"person": _person_name(session, natives, _ev_actor),
                                                      "ereignis": str((p["events"][-1]["fact"] or {}).get("id") or ""),
                                                      "stand": _rel_txt}}
            # V65P (AMASTER §44 Interpretation je Owner mit ihren bestehenden
            # Beziehungen; V65P-Messlauf "Fremder" f2: Mara erwiderte Roberts Kuss
            # mit "Ich lieb dich auch", ihr Erleben kannte ihre Bindung nicht): the
            # existing bond to SOMEONE ELSE - already in the frame and mirrored in
            # the brief (PARTNERBINDUNG) - reaches her Erleben as state as well.
            _ob = _apf.get("otherBond") if isinstance(_apf.get("otherBond"), dict) else None
            if _ob:
                _ap_extra["bestehende_bindung"] = {"zu": str(_ob.get("name") or ""), "art": str(_ob.get("kind") or "enge Bindung"),
                                                   "anwesend": bool(_ob.get("present"))}
        # V65P (AMASTER §41.3 Linsenauswahl ist Reader-Selektion, §15; V65G Fix3b):
        # the SAME lens selection as her brief - toward a counterpart whose
        # relationship carries no intimate rooms (policy allows_intimate_room)
        # the intimate rooms are no lens: their name stays, their reaction text
        # is not mirrored. Before, only the brief scoped them; the Erleben got the
        # full "Lust"/"Naehe" text and wrote "Begeisterung, will ihm naeher kommen".
        _scope_rooms = bool(_apf) and not _apf.get("intimateRoomsLens")
        _int_rooms = ((relationship_policy() or {}).get("intimate_rooms")) or {"naehe", "nähe", "lust"}

        def _lens_cell(k: Any, cell: dict) -> dict:
            if _scope_rooms and _norm_kind(cell.get("space") or k) in _int_rooms:
                return {"raum": str(k)}
            return {"raum": str(k), "schwelle": cell.get("threshold"), "reaktion": str(cell.get("reaction") or "")}
        # V65P (AMASTER §42 Versuch -> tatsaechlicher Ausgang -> Folgen, §43.1):
        # her own last attempt carries its resolved outcome from state (blocked
        # on the Fact, or overcome in the SpatialState). Without an outcome the
        # entry is unchanged.
        _own_out = act_outcome_text(session, own, natives, own=True) if own else None
        figures.append({
            **_ap_extra,
            "figur": p["name"],
            "zuletzt_selbst": ({"turn": own.get("turn"), "art": "sagte" if own.get("kind") == "speech" else "tat",
                                "text": str(own.get("text") or "")[:200], **({"ausgang": _own_out} if _own_out else {})} if own else None),
            # V63 (AMASTER §44 Z. 2472 ff. "Persönlichkeit und Werte", §15 Z. 709–730
            # "Nähe gegenüber Distanz … Dominanz … Tabus und Grenzen"): the owner
            # interprets the event with her disposition. V62 sent only personality
            # and register; session 13:39: Tamara (taboo "Echte Nähe", dislikes
            # "Emotionale Bindungen") was proposed closeness +0.1/+0.2 per turn,
            # 0.20 -> 0.67 in 10 turns. Profile data, read-only.
            "profil": _appraisal_profile(c),
            "ziele": goals,
            # V63 (§15): her lens where it is authored; the remaining spaces of
            # the shared inventory as bare names (no threshold, no reaction —
            # the kernel applies the neutral threshold there). A figure without
            # an authored compass still gets a space inventory to name.
            # V65P (§15 Z. 707ff: Rueckzug/Eskalation/Beruhigung gehoeren zum
            # Kompass): the reaction text is no longer cut at 110 characters;
            # for Mara the cut dropped "Vermeidet: sich in die Enge treiben zu
            # lassen · Eskaliert wenn: Druck oder Gewalt zunimmt".
            "kompass": ([_lens_cell(k, cell)
                         for k, cell in comp.items() if isinstance(cell, dict)][:16]
                        + [{"raum": m} for m in MEANING_SPACES
                           if _fold_space(m) not in {_fold_space(k) for k in comp} | {_fold_space((v or {}).get("space")) for v in comp.values() if isinstance(v, dict)}]),
            # §42 / §41.5: "Dass derselbe Zustand erneut … in einen Prompt
            # gespiegelt … wird, ist keine neue Evidenz und darf ihn nicht selbst
            # verstärken." The current affect is NOT sent: the event is appraised
            # from disposition, relationships and what is open; the kernel blends
            # it with the decaying earlier affects. Acceptance run A 27.10.: with
            # the prior feeling in the payload "Verwirrung" was re-proposed in
            # 5 consecutive turns. Only the current INTENT is sent (to judge
            # whether it changes or was carried out).
            "vorher": {"absicht": str(rt.get("intent") or "")[:160]},
            "beziehungen": rels,
            "offen": offen[-6:],
            "verlauf": verlauf,
            # V92: the citable disposition sources of THIS figure (id + literal text) - the same owner the validator uses
            "dispositionsquellen": appraisal_disposition_source_list(session, c, cid, involved),
            "gerade_geschehen": events,
        })
    return {"personen": persons, "figuren": figures}


def _mirror_owned_by_appraisal(rt: dict) -> bool:
    """The emotion mirror belongs to the appraisal step only while nobody else
    wrote it since the last refresh (God, Regie, body, knowledge effect and the
    reply fallback write emotion/activeCause directly)."""
    if rt.get("emotionSource") != "appraisal":
        return False
    m = rt.get("affectMirror")
    if not isinstance(m, dict):
        return True
    return m.get("emotion") == rt.get("emotion") and str(m.get("activeCause") or "") == str(rt.get("activeCause") or "")


def _authority_holds_mirror(session: dict, rt: dict, event_turn: int) -> bool:
    """God/Regie precedence (§27.5/§27.6, §46): a state set by a God/Regie fact
    of the same or a later turn than the appraised event is not overwritten."""
    cause = str(rt.get("activeCause") or "")
    if not cause or _mirror_owned_by_appraisal(rt):
        return False
    f = next((x for x in session.get("facts") or [] if isinstance(x, dict) and str(x.get("id") or "") == cause), None)
    if not isinstance(f, dict):
        return False
    auth = str(f.get("authority") or f.get("kind") or "")
    return auth in ("god", "regie") and int(f.get("turn") or 0) >= int(event_turn or 0)


def refresh_affects(session: dict) -> bool:
    """Apply decay_policy "turn" to appraisal affects and mirror the dominant
    one into emotion/intensity/activeCause (readers keep their fields). A mirror
    set by another writer (God, Regie, body, knowledge effect) is not decayed
    here. Deterministic in turnIndex; returns True when something changed."""
    turn_now = int(session.get("turnIndex") or 0)
    changed = False
    for cid, rt in (session.get("runtimes") or {}).items():
        if not isinstance(rt, dict):
            continue
        # Momentary scalars written by the appraisal return toward the
        # figure's rest value by the same rule (§42 Nachwirkung/decay_policy);
        # a value another writer changed since (God, body) is not touched.
        marks = rt.get("stateMarks") if isinstance(rt.get("stateMarks"), dict) else {}
        for en, m in list(marks.items()):
            if not isinstance(m, dict):
                continue
            try:
                cur_v = float(rt.get(en) or 0)
                if abs(cur_v - float(m.get("last"))) > 1e-6:
                    marks.pop(en, None)
                    changed = True
                    continue
                rest_v = float(m.get("base") if m.get("base") is not None else cur_v)
                now_v = round(rest_v + (float(m.get("value")) - rest_v) * (APPRAISAL_DECAY_PER_TURN ** max(0, turn_now - int(m.get("turn") or 0))), 3)
            except (TypeError, ValueError):
                continue
            if now_v != cur_v:
                rt[en] = now_v
                m["last"] = now_v
                changed = True
        if not isinstance(rt.get("affects"), list):
            continue
        active, resolved = [], []
        for a in rt["affects"]:
            if not isinstance(a, dict):
                continue
            (active if _affect_now(a, turn_now) >= APPRAISAL_RESOLVE_BELOW else resolved).append(a)
        if resolved:
            hist = [x for x in (rt.get("resolvedAffects") or []) if isinstance(x, dict)]
            rt["resolvedAffects"] = (hist + [{**a, "resolvedBy": "decay", "resolvedTurn": turn_now} for a in resolved])[-8:]
            changed = True
        active.sort(key=lambda a: -_affect_now(a, turn_now))
        if [id(a) for a in active] != [id(a) for a in rt["affects"]]:
            rt["affects"] = active
        if not _mirror_owned_by_appraisal(rt):
            if rt.get("emotionSource") == "appraisal":
                rt["emotionSource"] = "other"   # another writer took the mirror
                changed = True
            continue
        top = active[0] if active else None
        want = ({"emotion": top.get("type"), "intensity": round(_affect_now(top, turn_now), 3), "emotionToward": top.get("targetId"),
                 "activeCause": top.get("causeFactId"), "activeCauseText": top.get("causeText")} if top else
                {"emotion": APPRAISAL_BASELINE["emotion"], "intensity": APPRAISAL_BASELINE["intensity"], "emotionToward": None,
                 "activeCause": None, "activeCauseText": ""})
        for k, v in want.items():
            if rt.get(k) != v:
                rt[k] = v
                changed = True
        rt["affectMirror"] = {"emotion": rt.get("emotion"), "activeCause": rt.get("activeCause")}
    return changed


def intent_resolution_claims(session: dict, pending: list[dict], results: dict | None) -> list[dict]:
    """V65Q: the figures whose appraisal proposes that their current intent is done
    (`vorher_absicht_erledigt`), with that intent - the app reads HOW each intent is
    carried out before the writer runs (no write here). Name match like the writer:
    exact name, else a unique first name among the pending figures."""
    rows = (results or {}).get("bewertungen") if isinstance(results, dict) else None
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    out = []
    for p in pending or []:
        nm = _fold_space(p.get("name"))
        same_first = [q for q in pending if _fold_space(q.get("name")).split()[:1] == nm.split()[:1]]
        row = next((r for r in rows if _fold_space(r.get("figur")) == nm), None)
        if row is None and nm and len(same_first) == 1:
            row = next((r for r in rows if _fold_space(r.get("figur")).split()[:1] == nm.split()[:1]), None)
        rt = (session.get("runtimes") or {}).get(str(p.get("id"))) or {}
        if row is not None and row.get("vorher_absicht_erledigt") is True and str(rt.get("intent") or "").strip():
            out.append({"id": str(p.get("id")), "name": p.get("name"), "intent": str(rt.get("intent"))})
    return out


def apply_appraisals(session: dict, pending: list[dict], results: dict | None, *, natives: list[dict] | None) -> tuple[dict, list[dict]]:
    """Canonical writer of the appraisal step. The provider result is a
    proposal per figure; the kernel validates figure, perception, compass space
    and threshold, persons, bounds and idempotency, then writes RuntimeState
    (directed affect, scalars, intent) and RelationshipState with the perceived
    event as cause_fact_id. Without a result (no provider / call failed) only
    decay runs and the events stay pending. Returns (session, protocol)."""
    s = copy.deepcopy(session)
    proto: list[dict] = []
    turn_now = int(s.get("turnIndex") or 0)
    if results is None or not pending:
        refresh_affects(s)
        return s, proto
    refresh_affects(s)   # bring every state to "now" before new steps are added
    rows = results.get("bewertungen") if isinstance(results, dict) else None
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    avatar = str(s.get("avatarId") or "")
    present = [str(x) for x in ((s.get("scene") or {}).get("presentIds") or [])]

    def _who(name: Any) -> str | None:
        # Exact full name first over ALL candidates; a first-name match only
        # when it is unique (review: "Anna Maier"/"Anna Schmidt" both went to
        # the first one).
        # V92 Paket 13 (Paket-12-Pruefung, Bedingung C Runtime): the same identity contract as every other binder
        # (figure_ids_for_name) - an unknown full name ("Mara Schmidt") never falls back to a first name of another figure.
        if not _fold_space(name):
            return None
        cands = list(dict.fromkeys(present + ([avatar] if avatar else [])))
        _by = {str(c.get("id") or ""): c for c in natives or [] if isinstance(c, dict)}
        figs = [{"id": pid, "name": _person_name(s, natives, pid), "aliases": list((_by.get(pid) or {}).get("aliases") or []),
                 "sessionAliases": list((_by.get(pid) or {}).get("sessionAliases") or [])} for pid in cands]
        ids = figure_ids_for_name(str(name), figs)
        return next(iter(ids)) if len(ids) == 1 else None

    failed = {_fold_space(x) for x in ((results or {}).get("fehlgeschlagen") or [])}
    for p in pending:
        cid = p["id"]
        if cid == avatar or _fold_space(p.get("name")) in failed:
            continue   # call failed for her: the events stay pending (no silent loss)
        char = next((c for c in natives or [] if isinstance(c, dict) and str(c.get("id") or "") == cid), {}) or {}
        rt = s.setdefault("runtimes", {}).setdefault(cid, {"characterId": cid, **APPRAISAL_BASELINE})
        # Idempotency (§44 "nicht allein durch erneuten Recall erneut
        # angewendet"): events already appraised in THIS (locked) state are
        # not applied again — e.g. a retried prepare on the same input.
        _done = {str(x) for x in (rt.get("appraisedFactIds") or [])}
        _events = [e for e in p["events"] if str(e["fact"].get("id")) not in _done]
        if not _events:
            continue
        p = {**p, "events": _events}
        ev_ids = [str(e["fact"]["id"]) for e in p["events"]]
        last = p["events"][-1]["fact"]
        cause = str(last.get("id"))
        cause_turn = int(last.get("turn") or 0)
        involved = {str(e["fact"].get(k) or "") for e in p["events"] for k in ("actorId", "targetId")} - {"", cid}
        row = next((r for r in rows if _who(r.get("figur")) == cid), None)
        entry = {"figureId": cid, "figure": p["name"], "events": ev_ids, "superseded": p.get("superseded") or [],
                 "causeFactId": cause, "rejects": [], "notes": [], "runtimeDelta": {}, "relationDelta": [], "affect": None, "intent": None}
        if row is None:
            # A missing result is NOT a completed appraisal. Keep the
            # witnessed event pending for the next legal appraisal attempt.
            entry["rejects"].append("keine_bewertung")
            proto.append(entry)
            continue
        # Once examined, these causes are not a second time rewritten by the
        # reply's self-report/synapse. A refused appraisal is a zero-effect,
        # not a license to bypass the rejected causal check on the reply path.
        rt["appraisalCauses"] = ([str(x) for x in (rt.get("appraisalCauses") or [])] + ev_ids)[-120:]
        before = {k: rt.get(k) for k in ("emotion", "intensity", "emotionToward", "intent", *APPRAISAL_STATE_KEYS.values())}
        # A relational proof must cite THIS owner's relation to the proposed
        # target, never an unrelated person's directed relationship (§44).
        _relation_rows = row.get("beziehung_aenderung")
        _relation_rows = ([_relation_rows] if isinstance(_relation_rows, dict)
                          else _relation_rows if isinstance(_relation_rows, list) else [])
        _dispositions_by_field: dict[str, list[str]] = {}
        for _field in appraisal_effect_fields(row):
            if _field.startswith("beziehung."):
                _index = int(_field.split(".")[1])
                _target = _who((_relation_rows[_index] or {}).get("zu")) if isinstance(_relation_rows[_index], dict) else None
                _relevant = {_target} if _target in involved else set()
            else:
                _target = _who(row.get("gegenueber"))
                _relevant = {_target} if _target in involved else involved
            _dispositions_by_field[_field] = appraisal_disposition_sources(s, char, cid, _relevant)
        approved = _appraisal_cause_proofs(row, p, entry, _dispositions_by_field)
        # A review with missing/invalid proof is NOT finished (§6/§10 of the
        # chain contract). A partial review may commit independently valid
        # effects, but the other fields must remain retryable. Deduplicate
        # already committed effects through existing canonical appraisal Facts,
        # not through a new truth owner or a blanket per-event rejection.
        incomplete_proof = any(str(reason).startswith((
            "kausalpruefung_fehlend:", "kausalurteil_ungueltig:",
            "ursache_nicht_wahrgenommen:", "ursache_nicht_woertlich:",
            "begruendung_fehlt:", "disposition_nicht_belegt:")) for reason in entry["rejects"])
        already_committed: set[tuple[str, str]] = set()
        for previous in s.get("facts") or []:
            if not isinstance(previous, dict) or previous.get("kind") != "appraisal" or str(previous.get("actorId") or "") != cid:
                continue
            payload = previous.get("payload") if isinstance(previous.get("payload"), dict) else {}
            relation_changes = payload.get("relationDelta") or []
            runtime_changes = payload.get("runtimeDelta") or {}
            for field, belege in (payload.get("kausalBelege") or {}).items():
                if not isinstance(belege, dict) or not belege.get("factId"):
                    continue
                # V84 audit listed APPROVED fields even when its writer silently
                # skipped them. Only the writer's REAL effect proves commit.
                if field.startswith("beziehung."):
                    dimension = field.rsplit(".", 1)[-1]
                    actually_written = any(
                        isinstance(delta, dict) and
                        (delta.get("before") or {}).get(dimension) != (delta.get("after") or {}).get(dimension)
                        for delta in relation_changes)
                elif field.startswith("zustand."):
                    en = APPRAISAL_STATE_KEYS.get(field.split(".",1)[-1])
                    actually_written = bool(en and en in runtime_changes)
                elif field == "gefuehl":
                    actually_written = bool(payload.get("affect"))
                elif field == "absicht":
                    actually_written = bool(payload.get("intent"))
                else:
                    actually_written = False
                if actually_written:
                    already_committed.add((str(belege["factId"]), str(field)))
        skipped = [field for field, proof in approved.items() if (str(proof["factId"]), field) in already_committed]
        for field in skipped:
            approved.pop(field)
        if skipped:
            entry["notes"].append("bereits_committete_effects:" + ",".join(sorted(skipped)))
        # A proposal may name several events. Each committed effect uses its
        # own approved source Fact rather than blindly the latest event.
        _facts_by_id = {str(e["fact"]["id"]): e["fact"] for e in p["events"]}
        def _approved_fact(field):
            return _facts_by_id.get(str((approved.get(field) or {}).get("factId") or ""))
        # §50 (Z. 2827): "aus bloßer Frage, Schweigen, Höflichkeit oder kurzer
        # Antwort ohne Evidenz einen DAUERHAFTEN inneren Zustand, Relationship-
        # Wert oder Intent erfinden" is excluded. When everything she perceived
        # is a validated plain question/smalltalk (no action, no matter), the
        # proposal creates no intent and no relationship change. Acceptance runs
        # E/F 27.10.: "Welcher Tag ist heute?" became intent "nach dem Grund
        # seiner Frage fragen" and Mara did not answer the date.
        # V63: the momentary, decaying feeling and state values are NOT
        # "dauerhaft" and stay (session 13:39, T2: "Alles was du sagst liebling"
        # was classified smalltalk and the whole appraisal — Lust 0.8,
        # "Erregung" — was dropped). A carried-out intent is still recorded.
        _bare = all(e["fact"].get("kind") == "speech" and isinstance(e["fact"].get("plan"), dict)
                    and e["fact"]["plan"].get("source") == "llm"
                    and e["fact"]["plan"].get("event_kind") in ("question", "smalltalk")
                    and not e["fact"]["plan"].get("refers_to")
                    and not (e["fact"].get("proposition_id") or e["fact"].get("propositionId"))
                    for e in p["events"])
        if _bare:
            _dropped = [k for k in ("absicht", "beziehung_aenderung") if row.get(k)]
            entry["notes"].append("bloße_frage_oder_smalltalk_§50" + (":ohne_" + "+".join(_dropped) if _dropped else ""))
            row = {k: v for k, v in row.items() if k not in ("absicht", "beziehung_aenderung")}
        # (1) meaning space and threshold: the figure's own lens (§15)
        key, cell = compass_cell(char, row.get("raum"))
        if row.get("raum") and key is None:
            # Outside her authored lens: no lens modulation, the neutral
            # threshold applies (the compass shapes, it does not replace
            # RuntimeState, §15). Recorded, not silently mapped.
            entry["notes"].append(f"raum_ausserhalb_kompass:{str(row.get('raum'))[:30]}" if authored_compass(char)
                                  else "kompass_nicht_gesetzt")
        try:
            threshold = float((cell or {}).get("threshold")) if (cell or {}).get("threshold") is not None else float(_DEFAULT_LENS_CELL["threshold"])
        except (TypeError, ValueError):
            threshold = float(_DEFAULT_LENS_CELL["threshold"])
        try:
            act = _clamp01(row.get("aktivierung"))
        except (TypeError, ValueError):
            act = 0.0
        taken = act >= threshold
        feeling = " ".join(str(row.get("gefuehl") or "").split())[:30]
        toward = _who(row.get("gegenueber"))
        if toward is not None and toward not in involved and toward not in present:
            toward = None
        hold = _authority_holds_mirror(s, rt, cause_turn)
        if hold:
            entry["rejects"].append("god_regie_vorrang")
        # (2) directed affect (§42) — only above the figure's threshold
        if feeling and taken and "gefuehl" in approved:
            _af_fact = _approved_fact("gefuehl") or last
            _af_cause = str(_af_fact["id"])
            _af_turn = int(_af_fact.get("turn") or 0)
            affects = [a for a in (rt.get("affects") or []) if isinstance(a, dict)]
            same = next((a for a in affects if _fold_space(a.get("type")) == _fold_space(feeling)
                         and str(a.get("targetId") or "") == str(toward or "")), None)
            cause_text = f"Turn {_af_turn}: {_person_name(s, natives, _af_fact.get('actorId'))} " \
                         f"{'sagte' if _af_fact.get('kind') == 'speech' else 'tat'}: {str(_af_fact.get('text') or '')[:110].rstrip(' .')}"
            if same is not None:
                same["base"] = round(max(act, _affect_now(same, turn_now)), 3)
                same["reinforcedTurn"] = turn_now
                same["causeFactId"] = _af_cause
                same["causeText"] = cause_text
                same["reinforcedBy"] = ([str(x) for x in (same.get("reinforcedBy") or [])] + [_af_cause])[-8:]
            else:
                affects.append({"type": feeling, "space": key or "", "ownerId": cid, "targetId": toward, "base": round(act, 3),
                                "causeFactId": _af_cause, "causeText": cause_text, "startedTurn": turn_now, "reinforcedTurn": turn_now,
                                "reinforcedBy": [_af_cause], "decayPolicy": "turn", "source": "appraisal", "visibility": "open"})
            rt["affects"] = affects
            if not hold:
                rt["emotionSource"] = "appraisal"
                rt.pop("affectMirror", None)
            entry["affect"] = {"type": feeling, "space": key or "", "activation": act, "threshold": threshold, "toward": toward}
        elif feeling and "gefuehl" in approved:
            entry["rejects"].append(f"unter_hemmschwelle:{act:.2f}<{threshold:.2f}")
        # (3) runtime scalars: target values, bounded step; a rise needs the
        # threshold (Hemmschwelle), calming toward rest is always possible (§15
        # Beruhigungsneigung).
        zs = row.get("zustand_aenderung") if isinstance(row.get("zustand_aenderung"), dict) else {}
        _phys = set(ev_ids) & {str(x) for x in (rt.get("physicalCauses") or [])}
        if _phys and zs:
            # §43/§42: the physical writer already applied this cause's
            # fear/anger/stress (one cause, one effect per dimension).
            entry["notes"].append("zustand_durch_koerperwirkung_bereits_geschrieben")
            zs = {}
        if not hold:
            for de, en in APPRAISAL_STATE_KEYS.items():
                if zs.get(de) is None or "zustand." + de not in approved:
                    continue
                try:
                    delta = float(zs.get(de))
                except (TypeError, ValueError):
                    continue
                cur = float(rt.get(en) or 0)
                # saturating, bounded step (a momentary state approaches its
                # bound ever more slowly; measured: +0.25 per line ran Robert's
                # fear/anger/stress to 1.0 within 13 turns)
                raw = delta * (1.0 - cur) if delta > 0 else delta * cur
                step = round(max(-APPRAISAL_MAX_STATE_STEP, min(APPRAISAL_MAX_STATE_STEP, raw)), 4)
                if abs(step) < 0.005 or (step > 0 and not taken):
                    continue
                marks = rt.setdefault("stateMarks", {})
                prev_m = marks.get(en) if isinstance(marks.get(en), dict) else None
                # decay returns to the value before THIS appraisal influence
                # began (kept while the mark lives); a value another writer set
                # (mark dropped) becomes the new base and is never decayed away.
                base = float(prev_m.get("base")) if prev_m and prev_m.get("base") is not None else round(cur, 3)
                rt[en] = round(_clamp01(cur + step), 3)
                marks[en] = {"value": rt[en], "turn": turn_now, "last": rt[en], "base": base,
                             "cause": str(approved["zustand." + de]["factId"])}
        # (4) intent (§42 "gegebenenfalls Intent"), bound to its cause
        intent = " ".join(str(row.get("absicht") or "").split())[:160] if "absicht" in approved else ""
        if row.get("vorher_absicht_erledigt") is True and rt.get("intent"):
            # §42 resolved_by: the figure's own committed act after the intent
            # was set (her line is the evidence; the proposal only names it).
            _fl = [f for f in (s.get("facts") or []) if isinstance(f, dict)]
            _ci = next((i for i, f in enumerate(_fl) if str(f.get("id") or "") == str(rt.get("intentCause") or "")), -1)
            # V65P (AMASTER §42 "Versuch -> tatsaechlich vollzogene Handlung",
            # §43.1; Pruefung v2.6 §7): an own attempt that stayed without effect
            # (blocked) or was undone by the other (overcome withdrawal) is no
            # evidence that the intent was carried out; neither is an empty line
            # (same criterion as `zuletzt_selbst` in the payload).
            _own_all = [f for f in reversed(_fl[_ci + 1:]) if str(f.get("actorId") or "") == cid
                        and f.get("kind") in ("speech", "action") and _scene.validiert(f)
                        and str(f.get("text") or "").strip() not in ("", "—")]
            own_after = next((f for f in _own_all if act_outcome(s, f) is None), None)
            # V65Q (AMASTER §42 Z. 2305 resolved_by, Z. 2315-2316 "Intent -> Versuch ->
            # tatsaechlich vollzogene Handlung"; Pruefung v2.8 P-06): HOW the intent is
            # carried out (read once from its text, see app) decides which own act is
            # evidence: a bodily/spatial intent only by her own act with a validated
            # effect class whose outcome is no failure (not attempted, blocked or
            # overcome); a spoken intent by her own words. "Lass das!" no longer
            # resolves "Abstand schaffen". Without that reading: as V65P.
            _kinds = (results or {}).get("absichtArt") if isinstance((results or {}).get("absichtArt"), dict) else None
            _kr = _kinds.get(cid) if _kinds is not None else None
            _art = str((_kr or {}).get("art") or "").strip().lower() if isinstance(_kr, dict) else ""
            if _kinds is not None and cid in _kinds:
                if _art == "handlung":
                    own_after = next((f for f in _own_all if f.get("kind") == "action" and isinstance(f.get("effect"), dict)
                                      and f["effect"].get("effectKind") and _scene.validiert(f["effect"])
                                      and act_outcome(s, f) is None), None)
                elif _art == "rede":
                    own_after = next((f for f in _own_all if f.get("kind") == "speech"), None)
                else:
                    own_after = None
            if _kinds is not None and cid in _kinds and own_after is None and rt.get("intentCause"):
                entry["rejects"].append(f"absicht_{_art or 'art_unbekannt'}_ohne_passende_eigene_tat")
            elif own_after is None and _own_all and rt.get("intentCause"):
                entry["rejects"].append("absicht_erledigt_nur_durch_wirkungslosen_versuch")
            elif own_after is not None or not rt.get("intentCause"):
                hist = [x for x in (rt.get("resolvedIntents") or []) if isinstance(x, dict)]
                rt["resolvedIntents"] = (hist + [{"intent": rt.get("intent"), "cause": rt.get("intentCause"),
                                                  "resolvedBy": (own_after or {}).get("id"), "turn": turn_now,
                                                  **({"art": _art} if _art else {})}])[-6:]
                rt["intent"] = ""
                rt["intentCause"] = None
                entry["intentResolved"] = True
            else:
                entry["rejects"].append("absicht_erledigt_ohne_eigene_tat")
        if intent and intent.lower() not in ("neutral", "keine", "unbestimmt", "-"):
            rt["intent"] = intent
            rt["intentCause"] = str(approved["absicht"]["factId"])
            rt["intentTurn"] = turn_now
            rt["intentToward"] = toward
            entry["intent"] = intent
        # (5) relationships per owner (§44): only toward persons of these events
        grund = " ".join(str(row.get("grund") or "").split())[:160] or f"Ereignis Turn {cause_turn}"
        rels = row.get("beziehung_aenderung")
        rels = [rels] if isinstance(rels, dict) else (rels if isinstance(rels, list) else [])
        for rel_index, rel in enumerate(rels):
            if not isinstance(rel, dict):
                continue
            tid = _who(rel.get("zu"))
            if tid is None or tid not in involved:
                entry["rejects"].append(f"beziehung_ohne_ereignisbezug:{str(rel.get('zu'))[:30]}")
                continue
            # The existing directed-dyad writer is idempotent PER CAUSE.
            # Group validated dimensions by their proven cause and write
            # them TOGETHER. V84 called it once for trust and once for
            # closeness, so the second was lost as an alleged duplicate.
            groups: dict[str, dict] = {}
            for k in ("trust", "closeness", "fear"):
                proof = approved.get(f"beziehung.{rel_index}.{k}")
                if proof is None:
                    continue
                try:
                    d = float(rel.get(k) or 0)
                except (TypeError, ValueError):
                    continue
                if not d:
                    continue
                rel_cause = str(proof["factId"])
                cur_rel = _ensure_directed_rel(s, cid, tid, cause=rel_cause)
                cur_v = float(cur_rel.get(k) or 0)
                value = cur_v + (d * (1.0 - cur_v) if d > 0 else d * cur_v)
                group = groups.setdefault(rel_cause, {"values": {}, "reason": str(proof["begruendung"])})
                group["values"][k] = value
            for rel_cause, group in groups.items():
                # A cause can legally supply a missing second dimension after
                # an earlier partial commit. This permission is available only
                # if an actual earlier appraisal write was proven from Facts.
                prior_dimension = any(fid == rel_cause and field.startswith("beziehung.")
                                      for fid, field in already_committed)
                r_out = _apply_relation_target(s, cid, tid, group["values"],
                                               grund=group["reason"], cause_fact_id=rel_cause,
                                               allow_verified_partial_retry=prior_dimension)
                if r_out is not None:
                    entry["relationDelta"].append({**r_out, "toName": _person_name(s, natives, tid)})
        refresh_affects(s)
        entry["runtimeDelta"] = {k: {"from": before.get(k), "to": rt.get(k)} for k in before if before.get(k) != rt.get(k)}
        if entry["runtimeDelta"] or entry["relationDelta"]:
            _audit_cause = (next(iter(approved.values()))["factId"] if approved else cause)
            fact = make_fact(
                turn=turn_now, actorId=cid, targetId=None, kind="appraisal", event_kind="appraisal",
                text=f"{p['name']}: erlebt {feeling or '—'}" + (f" ({key})" if key else "")
                     + (f"; will: {intent}" if entry["intent"] else ""),
                authority="character", sourceTurnId=str(last.get("sourceTurnId") or last.get("source_turn_id") or ""),
                truth={"user_id": s.get("userId"), "world_id": s.get("worldId"), "session_id": s.get("id")},
                scene=s.get("scene") or {}, witnessedBy=[cid],
                affected_ids=[cid] + [r["toId"] for r in entry["relationDelta"]],
                # An incomplete review can legitimately commit trust now and
                # closeness on a later retry. These are DIFFERENT effects of
                # the same source turn, not a duplicate SceneFact component.
                # A repeat of the SAME effect/Fact remains a duplicate.
                duplicate_key="appraisal|" + cid + "|" + "|".join(sorted(
                    f"{name}:{proof['factId']}" for name, proof in approved.items())),
                payload={"kind": "appraisal", "causeFactIds": ev_ids, "sourceFactId": _audit_cause,
                         "kausalBelege": entry.get("kausalBelege") or {}, "proposal": {
                    k: row.get(k) for k in ("raum", "aktivierung", "gefuehl", "gegenueber", "absicht", "grund")},
                    "affect": entry["affect"], "runtimeDelta": entry["runtimeDelta"], "relationDelta": entry["relationDelta"],
                    "rejects": entry["rejects"], "notes": entry["notes"]},
                source_type="appraisal", provenance="kernel", validated=True,
            )
            s.setdefault("facts", []).append(fact)
            entry["factId"] = fact["id"]
        # Do not mark a perception as completed before the proof protocol
        # finished. A rejected (not_gestuetzt) verdict IS a completed, zero-
        # effect judgement; a missing/broken review is not. This also keeps
        # valid partial effects, while retrying only what is still unproved.
        if incomplete_proof:
            entry["notes"].append("kausalpruefung_unvollstaendig_erneut_pruefen")
        else:
            rt["appraisedFactIds"] = ([str(x) for x in (rt.get("appraisedFactIds") or [])]
                                       + (p.get("superseded") or []) + ev_ids)[-120:]
        proto.append(entry)
    refresh_affects(s)
    return s, proto


def _ensure_directed_rel(session: dict, from_id: str, to_id: str, *, cause: Any = None) -> dict:
    """Directed RelationshipState owner. Creates the pair if the event is first contact.
    V65Y (Gesamtpruefung V65X N02; AMASTER §34.2 Kausalprovenienz, §44): a pair created here records the event that
    created it (`cause` = its SceneFact or Quellturn) - the write boundary accepts no relation without an origin."""
    rels = session.setdefault("relations", [])
    hit = next(
        (r for r in rels if isinstance(r, dict) and r.get("fromId") == from_id and r.get("toId") == to_id),
        None,
    )
    if isinstance(hit, dict):
        return hit
    hit = {
        "fromId": from_id,
        "toId": to_id,
        "trust": 0.4,
        "closeness": 0.2,
        "fear": 0.1,
        "hostility": 0,
        "note": "",
        "kind": "knows",
        # V65Z (A01): the origin by kind - a TurnTruth as Quellturn, a SceneFact as sourceFactId
        **({"sourceTurnId": str(cause)} if cause and "cause_fact_id" not in fact_provenance(session, cause)
           else {"sourceFactId": str(cause)} if cause else {}),
    }
    rels.append(hit)
    return hit


def classify_physical_effect(text: str) -> str | None:
    raw = text or ""
    if _FREE_RE.search(raw):
        return "free"
    if _RESTRAIN_RE.search(raw):
        return "restrain"
    if _STRIKE_RE.search(raw):
        return "strike"
    if _MOVE_RE.search(raw):
        return "move"
    if _SOCIAL_RE.search(raw):
        return "social"
    return None


# ---------------------------------------------------------------------------
# V59C – Semantic Effect stage (AMASTER §24.2, §24.3, §24.6, §24.7, §34.1)
#
# Path: provider reading = candidate -> structural validation here -> the
# existing canonical writers. A word list is never the deciding authority.
# The semantic classes below are the planner's ACTION/PHYSICAL_STATE domain
# values; they are routed to the already existing physical writer branches.
# ---------------------------------------------------------------------------
_WIRKUNG_EFFECT = {
    "zaertlich": "social",
    "gewalt": "strike",
    "fesseln": "restrain",
    "befreien": "free",
    "ortswechsel": "move",
    # V60 (AMASTER §43.2 SpatialState): approaching / stepping back changes
    # the spatial relation only — no body, emotion or relationship value.
    "annaeherung": "approach",
    "entfernung": "withdraw",
    "ohne_koerperwirkung": None,
}
# V65U: effectKind -> the planner's class name (inverse of _WIRKUNG_EFFECT), for reading lines only.
_EFFECT_WIRKUNG = {v: k for k, v in _WIRKUNG_EFFECT.items() if v}
# Marker for callers that were deliberately not migrated in V59C (God,
# Puppet). Only they still use the legacy lexical classification.
_LEXICAL = object()


def effect_kind_from_wirkung(value: Any) -> tuple[bool, str | None]:
    """(valid, effect_kind). Unknown/missing class is NOT guessed (§24.7)."""
    key = str(value or "").strip().lower()
    key = key.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss").replace(" ", "_")
    if key in _WIRKUNG_EFFECT:
        return True, _WIRKUNG_EFFECT[key]
    return False, None


# V65I (AMASTER §24.2 "Validierung vor dem Writer", §24.7 "keine geratenen Weltfakten";
# dein Lauf 28.10. 15:31 T12): the figure's reply proposes the body effect of its own
# action in the same call that writes the action. Clara's "steht aufrecht und schaut
# Mara mit einem strengen Blick an" came as "gewalt" and the writer gave Mara pain and
# less mobility a second time. Measured runs: 22 such proposals (clenched fists, a
# stare, "zieht ihn näher") wrote strike or restraint. Only the classes that change
# ANOTHER figure's body state get a separate small reading; the kernel keeps the
# proposal only when that reading confirms it with a literal part of the action.
_BODY_CHECK_EFFECTS = ("strike", "restrain", "free")
# V65P (AMASTER §24.2, §43.1, §43.2; V65P route run T8/T9 "Mara drückt sich gegen die
# Mauer" proposed as entfernung -> room "auf Abstand"): the movement classes change the
# SpatialState between two figures; they pass the same validation before the writer
# (llm_contract.MOVE_CHECK_RULES, same schema, same apply_effect_check).
_MOVE_CHECK_EFFECTS = ("withdraw", "approach")


def effect_check_needed(wirkung: Any, action: Any) -> bool:
    if not isinstance(wirkung, dict) or not str(action or "").strip():
        return False
    ok, eff = effect_kind_from_wirkung(wirkung.get("art"))
    return bool(ok and eff in _BODY_CHECK_EFFECTS + _MOVE_CHECK_EFFECTS)


def apply_effect_check(wirkung: dict, action: str, reading: Any, *, figures: list[dict] | None = None) -> dict:
    """Validated wirkung for the writer. Unconfirmed -> no body effect (the action
    itself stays a fact); proposal, reason and quote stay as audit on the fact.
    V65J (AMASTER §24.2 EffectPlan: zeitlicher Scope, Target): the reading must
    also place the act NOW and name the same hit figure as the proposal."""
    w = copy.deepcopy(wirkung) if isinstance(wirkung, dict) else {}
    r = reading if isinstance(reading, dict) else {}
    beleg = " ".join(str(r.get("beleg") or "").split())
    zeit = str(r.get("zeit") or "").strip().lower()
    r_ziel, p_ziel = str(r.get("ziel") or "").strip(), str(w.get("ziel") or "").strip()
    if not r:
        grund = "keine_pruefung"
    elif r.get("bestaetigt") is not True:
        grund = "nicht_bestaetigt"
    elif not beleg or _locate_segment(action, beleg) is None:
        grund = "beleg_nicht_in_handlung"
    elif zeit != "jetzt":
        grund = f"zeit_{zeit or 'unklar'}"
    elif r_ziel and p_ziel and not _same_figure(r_ziel, p_ziel, figures):
        grund = "ziel_abweichend"
    else:
        w["pruefung"] = {"bestaetigt": True, "beleg": beleg[:160], "zeit": "jetzt", "ziel": r_ziel or p_ziel or None}
        # V65Q (AMASTER §43.2, §20 Z. 926/947, FOUNDATION H; Pruefung v2.8 P-02): the
        # surface the target is pressed or held against - only when it stands
        # literally in the act (the reading proposes, the act is the evidence).
        gegen = " ".join(str(r.get("gegen") or "").split()).strip(" .,;:!?")
        g_span = _locate_segment(action, gegen) if gegen else None
        if g_span is not None:
            w["pruefung"]["gegen"] = str(action)[g_span[0]:g_span[1]].strip()[:80]
        return w
    w["pruefung"] = {"bestaetigt": False, "vorschlag": w.get("art"), "grund": grund, "beleg": beleg[:160] or None,
                     "zeit": zeit or None, "ziel": r_ziel or None}
    # V65Q (AMASTER §43.1 attempted, §42 Versuch; Pruefung v2.8 P-03): not done, but
    # tried NOW - the act is an attempt of exactly this effect (its outcome).
    if grund == "nicht_bestaetigt" and zeit == "jetzt" and r.get("versuch") is True:
        w["pruefung"]["versuch"] = True
    # V92 (AMASTER §24.2 Kandidat -> Validierung, §36.5 Einwilligung an die Handlung; SPS Klasse "zaertlich" = Berührung ohne Verletzung,
    # live 04.11.: "Johann greift Mara an den Hintern" came as gewalt 3/4, the reading rightly denied the injury and the touch itself
    # vanished - no container, no room, no consent evidence). The SAME reading says whether the act touches the target's body NOW
    # without the proposed effect; then the validated class is the touch class - with a literal part of the act, the proposal
    # kept as audit. No attempt, no other target, no other time.
    _b_beleg = " ".join(str(r.get("beruehrungBeleg") or "").split())
    _ok_cls, _prop_eff = effect_kind_from_wirkung(w.get("art"))
    if (grund == "nicht_bestaetigt" and zeit == "jetzt" and r.get("versuch") is not True and r.get("beruehrung") is True
            and _ok_cls and _prop_eff in _BODY_CHECK_EFFECTS and _b_beleg and _locate_segment(action, _b_beleg) is not None
            and not (r_ziel and p_ziel and not _same_figure(r_ziel, p_ziel, figures))):
        # A second, independent semantic verdict is required before a denied
        # violent effect can be replaced by a real body-contact event. Until then
        # this is only an audited proposal and writes NO contact, consent or room.
        w["pruefung"]["beruehrungVorschlag"] = True
        w["pruefung"]["beruehrungBeleg"] = _b_beleg[:160]
        w["art"] = "ohne_koerperwirkung"
        return w
    w["art"] = "ohne_koerperwirkung"
    return w



def touch_confirmation_needed(effect: Any) -> bool:
    check = (effect or {}).get("pruefung") if isinstance(effect, dict) else None
    return bool(isinstance(check, dict) and check.get("beruehrungVorschlag") is True)


def apply_touch_confirmation(effect: dict, action: str, reading: Any, *, figures: list[dict] | None = None,
                             planned_target: str | None = None) -> dict:
    """Second independent reading at the literal contact site. Never upgrades a
    wrong target, a disjoint quote, or an unconfirmed proposal into truth.
    """
    w = copy.deepcopy(effect) if isinstance(effect, dict) else {}
    p = w.get("pruefung") if isinstance(w.get("pruefung"), dict) else None
    if not p or p.get("beruehrungVorschlag") is not True:
        return w
    r = reading if isinstance(reading, dict) else {}
    z1 = str(planned_target or p.get("ziel") or "")
    z2 = str(r.get("ziel") or "")
    q1 = str(p.get("beruehrungBeleg") or "").strip()
    q2 = str(r.get("beleg") or "").strip()
    a = _locate_segment(action, q1) if q1 else None
    b = _locate_segment(action, q2) if q2 else None
    ids1 = figure_ids_for_name(z1, figures) if z1 else set()
    ids2 = figure_ids_for_name(z2, figures) if z2 else set()
    if not r:
        reason = "zweitlesung_fehlt"
    elif r.get("beruehrt") is not True or str(r.get("zeit") or "").strip().lower() != "jetzt":
        reason = "zweitlesung_verneint"
    elif not a or not b or a[0] >= b[1] or b[0] >= a[1]:
        reason = "zweitlesung_anderer_beleg"
    elif not ids1 or len(ids1) != 1 or ids1 != ids2:
        reason = "zweitlesung_ziel_ungebunden"
    else:
        reason = "bestaetigt"
        w["art"] = "zaertlich"
        p["ersatz"] = "zaertlich"
    p["beruehrungBestaetigung"] = {"grund": reason, "beleg": q2[:160] or None, "ziel": z2 or None}
    return w


def attempt_check_needed(wirkung: Any) -> bool:
    """V65Q: an unconfirmed MOVEMENT proposal of an act done now gets the follow-up
    attempt reading (llm_contract.MOVE_ATTEMPT_RULES); body classes carry it inline."""
    p = (wirkung or {}).get("pruefung") if isinstance(wirkung, dict) else None
    if not isinstance(p, dict) or p.get("bestaetigt") is not False or "versuch" in p:
        return False
    ok, eff = effect_kind_from_wirkung(p.get("vorschlag"))
    return bool(ok and eff in _MOVE_CHECK_EFFECTS and p.get("grund") == "nicht_bestaetigt" and p.get("zeit") == "jetzt")


def apply_attempt_check(wirkung: dict, reading: Any) -> dict:
    """V65Q: the follow-up reading marks the unconfirmed movement as attempted only when
    it, too, does not confirm it and places the attempt now."""
    w = copy.deepcopy(wirkung) if isinstance(wirkung, dict) else {}
    r = reading if isinstance(reading, dict) else {}
    p = w.get("pruefung") if isinstance(w.get("pruefung"), dict) else None
    if p is None:
        return w
    p["versuch"] = bool(r.get("versuch") is True and r.get("bestaetigt") is not True
                        and str(r.get("zeit") or "").strip().lower() == "jetzt")
    p["versuchLesung"] = "move_attempt" if r else "keine"
    return w


def _mark_outcome_from_check(effect: dict | None) -> None:
    """V65Q (AMASTER §43.1, §34.1 Z. 1807-1817): the canonical outcome fields of an
    act's effect from its check audit - `attempted` (+ the attempted class) and the
    surface (`gegen`). Written once at commit, read by act_outcome and the writers."""
    if not isinstance(effect, dict):
        return
    p = effect.get("pruefung") if isinstance(effect.get("pruefung"), dict) else None
    if p is None and isinstance(effect.get("wirkung"), dict) and isinstance(effect["wirkung"].get("pruefung"), dict):
        p = effect["wirkung"]["pruefung"]
    if not isinstance(p, dict):
        return
    if p.get("bestaetigt") is False and p.get("versuch") is True:
        ok, kind = effect_kind_from_wirkung(p.get("vorschlag"))
        effect["outcome"] = "attempted"
        effect["attemptedKind"] = kind if ok else None
    if p.get("bestaetigt") is True and p.get("gegen"):
        effect["gegen"] = str(p.get("gegen"))[:80]


def _same_figure(a: str, b: str, figures: list[dict] | None) -> bool:
    """Two names bind the same figure.
    V92 Paket 13 (Paket-12-Pruefung, Bedingung C body/physical): by the one identity contract figure_ids_for_name - both
    names bind exactly the same single figure; a name the cast does not carry is the same only as the same words
    ("Mara Schmidt" is never "Mara Nowak" by a shared first name)."""
    na, nb = _name_words(a), _name_words(b)
    if na and na == nb:
        # Keep the Paket-16 positive rule: identical written names at the
        # effect-reading stage must not suppress a valid target later bound by ID.
        # The final ID/person check belongs to bind_input_components below.
        return True
    ia, ib = figure_ids_for_name(a, figures), figure_ids_for_name(b, figures)
    if ia or ib:
        return len(ia) == 1 and ia == ib
    return False


# V65K (AMASTER §24.1 known_as, §24.3 ALIAS/VOCABULARY, §24.6 Sessionwortschatz, §26 Wissen nur über Zeugen,
# §52/G11 Session ≠ Stamm, §24.7): a participant's own explicit establishment of a NAME for a person or of a WORD
# MEANING. The semantic reading (llm_contract.language_reading) only proposes; here it is validated and bound.
# Nothing is written to the stem; the result lives on the speech Fact (session scope, its witnesses know it).
_QUOTE_CHARS = "\"„“”»«"


def _inside_quotation(text: str, span: tuple[int, int], label: str = "") -> bool:
    """Structural check: the span lies inside a pair of quotation marks (wörtlich wiedergegebene
    Rede). A name merely set in quotation marks ('nenn mich „Käpt'n“') is not a quotation."""
    text = str(text or "")
    marks = [i for i, ch in enumerate(text) if ch in _QUOTE_CHARS]
    a, b = span
    for o, c in zip(marks[0::2], marks[1::2]):
        if o <= a and b <= c + 1:
            inner = text[o + 1:c].strip(" .,;:!?")
            return not (label and _norm_name(inner) == _norm_name(label))
    return False


def bind_language(raw: str, readings: Any, *, speaker_id: str, addressee_id: str | None,
                  figures: list[dict] | None) -> list[dict[str, Any]]:
    """Validate the language reading of ONE utterance. Every proposal stays visible
    (validated True/False + reason); only a validated entry is ever read again."""
    out: list[dict[str, Any]] = []
    if not isinstance(readings, list):
        return out
    figs = [f for f in (figures or []) if isinstance(f, dict) and f.get("id")]
    by_id = {str(f["id"]): f for f in figs}
    for r in readings:   # V65Z (A04, §24.7): every reading, no silent cut
        if not isinstance(r, dict):
            continue
        art = str(r.get("art") or "").strip().lower()
        status = str(r.get("status") or "").strip().lower()
        label = " ".join(str(r.get("bezeichnung") or "").split())[:60]
        beleg = str(r.get("beleg") or "")
        row = {"art": art, "status": status, "bezeichnung": label, "beleg": beleg[:200],
               "personId": None, "personName": None, "bedeutung": None, "validated": False, "rejection_reason": None}
        span = _locate_segment(raw, beleg.strip(_QUOTE_CHARS + " ")) if beleg.strip() else None
        why = None
        if art not in ("name", "bedeutung"):
            why = "art_unbekannt"
        elif status != "festgelegt":
            why = f"status_{status or 'leer'}"
        elif not label or len(label) > 40:
            why = "bezeichnung_leer_oder_zu_lang"
        elif span is None:
            why = "beleg_nicht_in_aeusserung"
        elif label.casefold() not in raw[span[0]:span[1]].casefold():
            why = "bezeichnung_nicht_im_beleg"
        elif _inside_quotation(raw, span, label):
            why = "zitat"
        if not why and art == "name":
            person = " ".join(str(r.get("person") or "").split())
            pl = person.casefold()
            hit = (by_id.get(str(speaker_id)) if pl in ("ich", "mich", "mir") else
                   by_id.get(str(addressee_id or "")) if pl in ("du", "dich", "dir") else
                   _match_figure(person, figs))
            if hit is None:
                why = "person_unbekannt"
            else:
                row["personId"], row["personName"] = str(hit["id"]), str(hit.get("name") or "")
                own = {_norm_name(hit.get("name") or ""), _norm_name(str(hit.get("name") or "").split()[0] if hit.get("name") else ""),
                       *(_norm_name(a) for a in hit.get("aliases") or [])}
                if _norm_name(label) in own:
                    why = "schon_ihr_name"
                else:
                    other = next((f for f in figs if str(f["id"]) != str(hit["id"]) and _norm_name(label) in
                                  {_norm_name(f.get("name") or ""), _norm_name(str(f.get("name") or "").split()[0] if f.get("name") else ""),
                                   *(_norm_name(a) for a in (f.get("aliases") or []) + list(f.get("sessionAliases") or []))}), None)
                    if other is not None:
                        why = "bezeichnung_gehoert_schon_anderer_figur"
        if not why and art == "bedeutung":
            meaning = " ".join(str(r.get("bedeutung") or "").split())[:160]
            if not meaning or _locate_segment(raw, meaning) is None:
                why = "bedeutung_nicht_woertlich"
            elif label.casefold() in meaning.casefold():
                # An explanation that contains the word itself explains nothing (live 28.10.:
                # "ich brauche dich hier zum Bedienen" -> "Bedienen" = "hier zum Bedienen").
                why = "bedeutung_zirkulaer"
            else:
                row["bedeutung"] = meaning
        row["validated"] = why is None
        row["rejection_reason"] = why
        out.append(row)
    return out


def session_language(session: dict, for_figure: str | None = None) -> list[dict[str, Any]]:
    """Validated name/meaning establishments of THIS session (§24.6 Sessionwortschatz), oldest first.
    With for_figure: only what that figure perceived or said itself (§26/§39)."""
    known = _perceived_fact_ids(session, for_figure) if for_figure else None
    rows: list[dict[str, Any]] = []
    for f in session.get("facts") or []:
        if not isinstance(f, dict) or not isinstance(f.get("sprache"), list):
            continue
        if known is not None and str(f.get("id") or "") not in known and str(f.get("actorId") or "") != str(for_figure):
            continue
        for e in f["sprache"]:
            if isinstance(e, dict) and e.get("validated"):
                rows.append({**copy.deepcopy(e), "factId": f.get("id"), "turn": f.get("turn"), "actorId": f.get("actorId")})
    return rows


def with_session_aliases(natives: list[dict] | None, session: dict | None) -> list[dict]:
    """Read projection (like canonical_stem): names established in this session become
    `sessionAliases` of the named figure for entity binding (§24.1 known_as, scope = session).
    The stem is never changed. A label two figures would share binds neither (§24.1/§24.7)."""
    natives = [c for c in (natives or []) if isinstance(c, dict)]
    owners: dict[str, set[str]] = {}
    labels: dict[str, str] = {}
    for e in session_language(session or {}):
        if e.get("art") == "name" and e.get("personId") and e.get("bezeichnung"):
            key = _norm_name(e["bezeichnung"])
            owners.setdefault(key, set()).add(str(e["personId"]))
            labels.setdefault(key, str(e["bezeichnung"]))
    if not owners:
        return natives
    out = []
    for c in natives:
        mine = [labels[k] for k, ids in owners.items() if ids == {str(c.get("id") or "")}]
        if mine:
            c = {**c, "sessionAliases": list(dict.fromkeys(list(c.get("sessionAliases") or []) + mine))}
        out.append(c)
    return out


def component_effect_checks(components: Any) -> list[int]:
    """V65J: indexes of planner components (avatar input, puppet) whose proposed
    body class changes another figure's body - they need the same reading."""
    out: list[int] = []
    for i, c in enumerate(components if isinstance(components, list) else []):   # V65Z (A04): every component
        if (isinstance(c, dict) and str(c.get("typ") or c.get("type") or "").strip().lower() == "handlung"
                and effect_check_needed({"art": c.get("wirkung")}, c.get("segment"))):
            out.append(i)
    return out


def own_body_check_indices(components: Any) -> list[int]:
    """V92 Paket 18: the act components whose change to the actor's OWN body is read (llm_contract.koerper_check) - every act
    component the blind Vollzugslesung says HAPPENS (an act that does not happen changes no body; no reading is spent on it)."""
    out: list[int] = []
    for i, c in enumerate(components if isinstance(components, list) else []):
        if (isinstance(c, dict) and str(c.get("typ") or c.get("type") or "").strip().lower() == "handlung"
                and isinstance(c.get("vollzugPruefung"), dict) and c["vollzugPruefung"].get("geschieht") is True):
            out.append(i)
    return out


def apply_own_body_readings(components: list, readings: dict) -> list:
    """V92 Paket 18: the components with the server's own-body readings (`koerperPruefung`). A reading that came with the plan
    (model- or client-supplied) is removed first; a component without a server reading carries none (its act changes no body)."""
    out = copy.deepcopy(components) if isinstance(components, list) else []
    for c in out:
        if isinstance(c, dict):
            c.pop("koerperPruefung", None)
    for i, r in (readings or {}).items():
        if isinstance(r, dict) and 0 <= int(i) < len(out) and isinstance(out[int(i)], dict):
            # V92 Paket 19: with the server's confirmation reading at the quote (`bestaetigung`, app._koerper_bestaetigen)
            out[int(i)]["koerperPruefung"] = {k: copy.deepcopy(r.get(k)) for k in ("haltung", "schlaf", "zeit", "beleg", "bestaetigung")}
    return out


def apply_component_effect_checks(components: list, readings: dict, *, figures: list[dict] | None = None) -> list:
    """V65J: the checked components; an unconfirmed body class becomes
    'ohne_koerperwirkung' with its audit ('wirkungPruefung'). Nothing else changes."""
    out = copy.deepcopy(components) if isinstance(components, list) else []
    for i in component_effect_checks(out):
        c = out[i]
        w = apply_effect_check({"art": c.get("wirkung"), "ziel": c.get("ziel")}, str(c.get("segment") or ""),
                               (readings or {}).get(i), figures=figures)
        c["wirkung"] = w.get("art")
        c["wirkungPruefung"] = w.get("pruefung")
    return out


def _locate_segment(raw: str, segment: str, taken: list[tuple[int, int]] | None = None) -> tuple[int, int] | None:
    """Structural check that a proposed component segment really occurs in
    the source text (no invented wording). Exact match first; otherwise a
    near-literal match (typing errors, punctuation) by character alignment.
    V67 (Audit7 V66-06 z03/z04; AMASTER §34.1 jede Komponente eigene Validierung, §68 Nr. 63 "nicht mehrfach angewendet"):
    `taken` are the places already bound to another component of the same reading - a place of the input is ONE act. The
    segment binds its first place not taken yet (the same words written twice are two places); none left -> None."""
    taken = list(taken or [])
    import difflib
    src = str(raw or "")
    seg = re.sub(r"\s+", " ", str(segment or "")).strip().strip(" .,;:!?-")
    if not src.strip() or len(seg) < 2:
        return None
    low, sl = src.casefold(), seg.casefold()
    # V65P (found while binding the literal Regie segment): casefold() can make a
    # character longer ("ß" -> "ss"), so a span found in the folded text was
    # shifted against the source after every such character (measured: "… stößt
    # Kvle und sagt du bist am Samstag da" -> "agt du bist …"). The match itself is
    # unchanged; only the span is mapped back to source positions.
    pos: list[int] = []
    for k, ch in enumerate(src):
        pos.extend([k] * len(ch.casefold()))
    pos.append(len(src))

    def _src(a: int, b: int) -> tuple[int, int]:
        return pos[a], (pos[b - 1] + 1 if b > 0 else 0)
    i = low.find(sl)
    while i >= 0:
        span = _src(i, i + len(sl))
        if not any(span[0] < b and a < span[1] for a, b in taken):
            return span
        i = low.find(sl, i + 1)
    if low.find(sl) >= 0:
        return None   # every place of these words is bound already
    sm = difflib.SequenceMatcher(None, low, sl, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 3]
    if not blocks:
        return None
    matched = sum(b.size for b in blocks)
    start, end = blocks[0].a, blocks[-1].a + blocks[-1].size
    if matched / max(1, len(sl)) < 0.85 or (end - start) > len(sl) * 1.5:
        return None
    span = _src(start, end)
    return None if any(span[0] < b and a < span[1] for a, b in taken) else span


_QUOTE_CLOSE = {"„": "“", "“": "”", "\"": "\"", "»": "«", "«": "»", "‚": "‘"}
_CLAUSE_END = re.compile(r"[.!?;:,…–—\n]")


def quoted_spans(text: Any) -> list[tuple[int, int]]:
    """V65Z (SPS-Audit V65Y A05): the regions of `text` inside paired quotation marks („…“, “…”, "…", »…«, ‚…‘) -
    punctuation of the text itself, no vocabulary. Read only."""
    raw, out, i = str(text or ""), [], 0
    while i < len(raw):
        close = _QUOTE_CLOSE.get(raw[i])
        j = raw.find(close, i + 1) if close else -1
        if close and j > i:
            out.append((i + 1, j))
            i = j + 1
            continue
        i += 1
    return out


def segment_binding_fault(raw: str, span: tuple[int, int], others: list[tuple[int, int]]) -> str | None:
    """V65Z (SPS-Audit V65Y A05; AMASTER §24.2 Z. 1110-1113 Validierung vor dem Writer, §34.1 jede Komponente eigene
    Validierung, §6.2 Z. 262 fail-closed): an act segment the planner located in the input is an act of the input only
    when the input itself carries it as one - checked on the original text, structurally:
    - not inside quotation marks (a quoted act is said, not done) -> `segment_im_zitat`;
    - its clause is complete: from the segment's end to the next clause mark (. ! ? ; : , … – — or line end) nothing of
      the input is left, except one connecting word right before the next component ("… Hand und küsse dich").
      "Ich küsse dich nicht." with the segment "Ich küsse dich" leaves "nicht" -> `segment_satz_unvollstaendig`.
    V65Y took any literal substring. Returns the fault or None. Read only."""
    a, b = span
    if any(qa <= a and b <= qb for qa, qb in quoted_spans(raw)):
        return "segment_im_zitat"
    if (a > 0 and raw[a - 1].isalnum() and raw[a].isalnum()) or (b < len(raw) and raw[b - 1].isalnum() and raw[b].isalnum()):
        # V66 (Audit5 E06 "Spannen"): the segment begins or ends inside a word ("Ich nehme deine Hand" in "... Handtasche")
        return "segment_wortgrenze"
    m = _CLAUSE_END.search(raw, b)
    end = m.start() if m else len(raw)
    nxt = min((x for x, _ in others if x >= b), default=None)
    stop = min(end, nxt) if nxt is not None else end
    words = re.findall(r"\w+", raw[b:stop])
    if not words or (len(words) == 1 and nxt is not None and nxt <= end):
        return None
    return "segment_satz_unvollstaendig"


def _residual_text(raw: str, spans: list[tuple[int, int]]) -> str | None:
    """Text outside the validated action spans stays expressed speech (§34.1:
    a valid component must not swallow another one)."""
    keep, pos = [], 0
    for a, b in sorted(spans):
        keep.append(raw[pos:a])
        pos = max(pos, b)
    keep.append(raw[pos:])
    rest = re.sub(r"\s+", " ", " ".join(keep)).strip(" ,;:-")
    rest = re.sub(r"\s+([,.;:!?])", r"\1", rest).strip()
    rest = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", rest)
    rest = re.sub(r"^[,.;:!?\s]+|[,;:\s]+$", "", rest)
    return rest if re.search(r"[^\W\d_]{2,}", rest) else None


# V66 (Audit5 E05; AMASTER §23 "Ziel", §24.1 Zielidentitaet gebunden, §46.2 "Actor und Target werden ausdruecklich
# gebunden", §6.2 Z. 262): a body effect acts ON a person - without a bound target person it is no valid effect. The one
# rule for the input path (bind_input_components) and the Regie path (bind_regie_components).
BODY_EFFECTS_NEED_TARGET = frozenset({"strike", "restrain", "free"})


def vollzug_reading_complete(r: Any) -> bool:
    """V92 (Paket-5-Pruefung 04.11.): a blind vollzug reading counts only when it is complete: bool `geschieht`, text `art`
    and a named doer (`taeter`, "figur" = the figure itself). Anything else is no reading."""
    return (isinstance(r, dict) and isinstance(r.get("geschieht"), bool) and isinstance(r.get("art"), str)
            and bool(r.get("art").strip()) and isinstance(r.get("taeter"), str) and bool(r.get("taeter").strip()))


def act_vollzug_fault(comp: dict, marked_texts: Any = None, announced_texts: Any = None) -> str | None:
    """V92: why an act component is NOT a performed act, or None. `geschieht` is the planner's mandatory declaration;
    `vollzugPruefung` is the independent, complete, server-side blind reading and is MANDATORY (fail-closed, AMASTER §6.2/§24.2):
    without it (no provider, invalid, incomplete answer) the act is unproven -> `vollzug_nicht_geprueft`, never an act.
    V92 Paket 9 (AMASTER §27.3 "vom Nutzer ausdruecklich gesetzte Handlung"): for the server's component of the input's own
    *marker* (`markierung`, marker_act_components) the user's explicit marking is the declaration - only when its segment IS
    the marked text of this input; the complete blind reading stays mandatory (happens? whose?)."""
    g = comp.get("geschieht")
    _texts = [str(t or "").strip() for t in (marked_texts if isinstance(marked_texts, (list, tuple)) else [marked_texts]) if str(t or "").strip()]
    _marked = (comp.get("markierung") is True and g is None
               and str(comp.get("segment") or "").replace("*", "").strip() in _texts)
    # V92 Paket 13: the server's component of an own act inside a validated announcement (announcement_act_components) - the
    # literal naming by the blind speaker reading is its declaration, only when its words stand inside such an announcement
    _ann = [str(t or "") for t in (announced_texts if isinstance(announced_texts, (list, tuple)) else [announced_texts]) if str(t or "").strip()]
    _marked = _marked or (comp.get("ansageHandlung") is True and g is None and bool(str(comp.get("segment") or "").strip())
                          and any(str(comp.get("segment")).strip() in t for t in _ann))
    if g is not True and not _marked:
        return "vollzug_nicht_angegeben" if g is None else "handlung_nicht_vollzogen"
    r = comp.get("vollzugPruefung")
    if not vollzug_reading_complete(r):
        return "vollzug_nicht_geprueft"
    # P22: when a second semantic reading had to repair a false SPEECH
    # proposal into an ACT, its independent actual-execution reading must
    # also cite the ORIGINAL act segment. A made-up quote is not evidence.
    # No fabricated claim about other independent readings elsewhere.
    if isinstance(comp.get("typPruefung"), dict) and comp["typPruefung"].get("art") == "handlung":
        _literal = str(r.get("beleg") or "").strip()
        if _literal and not _scene.literal_in(_literal, str(comp.get("segment") or "")):
            return "vollzug_beleg_nicht_woertlich"
    if r.get("geschieht") is not True or str(r.get("art") or "").strip().lower() != "tatsaechlich":
        return "handlung_nicht_vollzogen"
    return None


def marker_spans(raw: str) -> list[tuple[int, int, str]]:
    """V92 Paket 10: EVERY `*marker*` of the input as (start, end, marked words). Form only, no word list."""
    return [(m.start(), m.end(), (m.group("action") or "").strip()) for m in _ACTION_STAR_RE.finditer(str(raw or ""))
            if (m.group("action") or "").strip()]


# V92 Paket 11: the end of a sentence inside a part of the input (". ! ? ; …" followed by further words). Form only.
_SENTENCE_END_INSIDE = re.compile(r"(?<=[.!?;\u2026])\s+(?=\S)")


def speech_announcement(raw: str, rede_span: tuple[int, int], intro_span: tuple[int, int] | None, other_spans: list) -> str:
    """V92 Paket 11/12: the words of the input that announce a speech - its validated `einleitung`, else the words right before
    it (from the previous component) when they end in ':' or an opening quotation mark. Form only. One rule for the binder
    and the route's speaker reading."""
    if intro_span:
        return raw[intro_span[0]:intro_span[1]]
    prev = max([b for a, b in (other_spans or []) if b <= rede_span[0]] or [0])
    t = raw[prev:rede_span[0]]
    return t if re.search(r"[:\u201e\u201c\"\u00bb\u00ab]\s*$", t) else ""


def _speech_intro(raw: str, comp: dict, rede_span: tuple[int, int] | None) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """V92 Paket 14 (Paket-13-Pruefung, Entscheidung 3; live 05.11.: the reading gave the speech segment "und sage: Schön, euch zu
    sehen." with the `einleitung` "sage:" INSIDE it, and "und sage:" was stored as spoken words): (validated announcement span,
    span of the spoken words). The `einleitung` is validated where it stands directly before the speech (_intro_span) - or at the
    START of the speech segment (at most one connecting word before it) and followed by an announcement mark (':' or an opening
    quotation mark) and further words: then the spoken words begin after it. Never words from the start of a real utterance
    without such a mark ("Ich sage dir die Wahrheit" stays whole). Form only, no word list."""
    if not rede_span:
        return None, rede_span
    isp = _intro_span(raw, comp, rede_span)
    if isp:
        return isp, rede_span
    intro = str((comp or {}).get("einleitung") or "").strip()
    if not intro:
        return None, rede_span
    a, b = rede_span
    seg = raw[a:b]
    _marks = [(mm.start(), mm.end()) for mm in _ACTION_STAR_RE.finditer(raw)]
    for m in re.finditer(re.escape(intro), seg):
        pre = seg[:m.start()]
        if pre.strip() and not re.fullmatch(r"\s*\w+\s*", pre):
            continue
        sep = _INTRO_SEPARATOR.match(seg, m.end())
        if not re.search(r"[:\u201e\u201c\u00bb\u00ab\"]", intro[-1:] + seg[m.end():sep.end()]):
            continue
        if not re.search(r"\w", seg[sep.end():]) or any(a + m.start() < mb and ma < a + m.end() for ma, mb in _marks):
            continue
        return (a + m.start(), a + m.end()), (a + sep.end(), b)
    return None, rede_span


def speech_clause_announcement(raw: str, rede_span: tuple[int, int], intro_span: tuple[int, int] | None,
                               other_spans: list) -> tuple[int, int, bool] | None:
    """V92 Paket 14 (Paket-13-Pruefung N2/N3: "Johann Weber sagt: Hallo." read with the `einleitung` "sagt:" only, "Mara sagt zu
    Johann: ..." with "sagt zu Johann:" - the name right before the claimed announcement was never checked): the WHOLE announcing
    clause of a speech - its validated announcement (or the words before it ending in ':'/a quotation mark), extended backwards over
    the directly adjacent words of the same clause (blanks only, no punctuation, not into another component). Without any
    announcement, the adjacent words directly before the speech. (start, end, has_announcement) or None. Form only."""
    base = speech_announcement(raw, rede_span, intro_span, other_spans)
    if intro_span:
        a, b, has = intro_span[0], intro_span[1], True
    elif base:
        a, b, has = rede_span[0] - len(base), rede_span[0], True
    else:
        a = b = rede_span[0]
        has = False
    a = clause_start(raw, a, other_spans)
    return (a, b, has) if raw[a:b].strip() else None


def speaker_reading_needed(announcement: str, figures: list[dict] | None, has_announcement: bool = True,
                           base: int | None = None) -> tuple[bool, set[str], bool]:
    """V92 Paket 12/13: does the announcement of a speech need the server's blind speaker reading? (needed, ids, unclear).
    Needed when it names SEVERAL figures (speaker or addressee? - Paket-11-Pruefung) and - V92 Paket 13 (Paket-12-Pruefung,
    Bedingung D; live 05.11.: "Peter sagt: „Hallo.“" read with the puppet as speaker 1 of 2) - when it names NOBODY of the cast:
    then only the planner's speaker field would say who speaks; an unknown person ("Peter") is not the figure. An announcement
    naming exactly one figure decides by itself; one with an unclear or unknown name is rejected by its form. Read only."""
    if not str(announcement or "").strip():
        return False, set(), False
    occ = name_occurrences(announcement, figures, base=base)   # V92 Paket 17: answers at their place
    ids = {i for o in occ if o["state"] == "ok" and len(o["ids"]) == 1 for i in o["ids"]}
    amb = any(o["state"] != "ok" or len(o["ids"]) != 1 for o in occ)
    # V92 Paket 14: an unknown person or a name of unproven extent in the clause - only the literal reading can prove the speaker
    return (len(ids) > 1 or bool(unresolved_names(occ)) or (has_announcement and not ids and not amb)), ids, amb


def _announcement_address_ids(raw: str, announcement: str, base: int | None,
                              figures: list[dict] | None, reading: Any) -> set[str]:
    """P24: a proven *addressee* in the validated speech announcement.

    A single cast name in `einleitung` is NOT proof that it speaks. Only a source-bound
    semantic `anrede` / literal `adressat` can make that identity an addressee. A
    comma after the named person is a necessary syntax guard but never authority
    on its own; 'Mara sagt:' has no such boundary. No vocabulary of speech verbs.
    Unknown/ambiguous names are never promoted to an actor or addressee ID.
    """
    ann = str(announcement or "")
    if not ann or base is None:
        return set()
    r = reading if isinstance(reading, dict) else {}
    spoken_to = str(r.get("adressat") or "").strip()
    role = str(r.get("ansageRolle") or "").strip().lower()
    literal = str(r.get("ansageBeleg") or "").strip()
    role_verified = role == "anrede" and bool(literal) and literal in ann
    from_role = set()
    occurrences = name_occurrences(ann, figures, base=base)
    for o in occurrences:
        if o.get("state") != "ok" or len(o.get("ids") or ()) != 1:
            continue
        # The name closes a comma-delimited address, not a narrator's statement.
        if not re.fullmatch(r"\s*,\s*", ann[int(o['b']):]):
            continue
        fid = next(iter(o['ids']))
        begin, end = base + int(o['a']), base + int(o['b'])
        boundary_role = any(
            b.get("source") == raw and b.get("rolle") == "anrede"
            and b.get("na") == begin and b.get("nb") == end
            for f in (figures or []) if isinstance(f, dict)
            for b in (f.get("_name_boundary_readings") or [])
        )
        # A separate literal addressee result can also corroborate the role,
        # but only at this exact full-name span in the announcement.
        addressed_literal = bool(spoken_to) and (
            spoken_to.casefold() == ann[int(o['a']):int(o['b'])].casefold()
            or (figure_ids_for_name(spoken_to, figures) == {fid} and spoken_to in ann)
        )
        role_literal = role_verified and ann[int(o['a']):int(o['b'])].casefold() in literal.casefold()
        if boundary_role or addressed_literal or role_literal:
            from_role.add(fid)
    return from_role


def speaker_reading_indices(raw: str, components: Any, figures: list[dict] | None) -> list[int]:
    """V92 Paket 12/13: the speech components the route gives the server's blind speaker reading (llm_contract.sprecher_check):
    every one whose announcement needs it (speaker_reading_needed) and - V92 Paket 13 (live 05.11.: with the cast as context the
    planner put "Johann lächelt" into the `einleitung` of the speech, 2 of 2, after the prompt fix 1 of 3; the act vanished
    silently) - every one with a validated `einleitung`: the same reading names an own act inside it. Read only."""
    comps = components if isinstance(components, list) else []
    spans = {i: _locate_segment(raw, str(c.get("segment") or "")) for i, c in enumerate(comps) if isinstance(c, dict)}
    out = []
    for i, c in enumerate(comps):
        if not isinstance(c, dict) or str(c.get("typ") or c.get("type") or "").strip().lower() != "rede" or not spans.get(i):
            continue
        _isp, _rsp = _speech_intro(raw, c, spans[i])
        _cl = speech_clause_announcement(raw, _rsp, _isp, [sp for k, sp in spans.items() if sp and k != i])
        if _isp or (_cl and speaker_reading_needed(raw[_cl[0]:_cl[1]], figures, _cl[2], base=_cl[0])[0]):
            out.append(i)
    return out


def puppet_kind_cast(natives: list[dict] | None, present_ids: list[str] | None, actor_id: str) -> list[dict]:
    """P23: only canonical same-world characters visible in the semantic read.

    A chosen Puppet can enter on a successful commit, so her authenticated ID
    is included in the *read* cast even if absent. This does not mutate presence
    or grant witness knowledge; absent other figures remain excluded.
    """
    actor = str(actor_id or "")
    known = {str(f.get("id") or ""): f for f in (natives or [])
             if isinstance(f, dict) and str(f.get("id") or "")}
    if not actor or actor not in known:
        raise ValueError("puppet_actor_id_not_bound_to_authorized_cast")
    allowed = {str(i) for i in (present_ids or [])} | {actor}
    return [f for fid, f in known.items() if fid in allowed]


def component_kind_candidate_indices(raw: str, components: Any, figures: list[dict] | None, actor_id: str) -> list[int]:
    """P22: proposals of direct Puppet speech which might instead narrate a
    performed action, or whose speaker the planner assigned to the addressee.
    Candidate detection uses source positions and canonical cast names only;
    meaning is delegated to a separate semantic reading, never a word list.
    Simple direct speech without an actor-name lead is not read twice.
    """
    out = []
    for i, c in enumerate(components if isinstance(components, list) else []):
        if not isinstance(c, dict) or str(c.get("typ") or c.get("type") or "").lower() != "rede":
            continue
        seg = str(c.get("segment") or "").strip()
        if not seg or _locate_segment(raw, seg) is None:
            continue
        occ = name_occurrences(seg, figures)
        leading_actor = any(o.get("a") == 0 and o.get("ids") == {str(actor_id)} and o.get("state") == "ok" for o in occ)
        planner_ids = figure_ids_for_name(str(c.get("akteur") or ""), figures)
        foreign_speaker = bool(planner_ids and planner_ids != {str(actor_id)})
        if leading_actor or foreign_speaker:
            out.append(i)
    return out


def _source_vocative_for_actor(raw: str, segment: str, figures: list[dict] | None,
                               proposed_actor_ids: set[str]) -> bool:
    """P23: a sentence-leading, comma-delimited canonical address, by PLACE.

    The planner may return only 'setz dich.' while the original input says
    'Gustav, setz dich.'. Search the ORIGINAL text, never just that fragment.
    A repeated/ambiguous/unbound name or an announcement ('Mara sagt: ...')
    cannot authorise a speaker change. The model never chooses the ID.
    """
    src = str(raw or "")
    span = _locate_segment(src, str(segment or ""))
    if span is None or not proposed_actor_ids or not src:
        return False
    first = re.search(r"\w", src)
    if first is None:
        return False
    for occ in name_occurrences(src, figures):
        if occ.get("state") != "ok" or occ.get("ids") != proposed_actor_ids:
            continue
        # A source-token reading may prove a title/greeting before the name
        # ("Herr Pfeiffer", "Hallo Mara"). Its literal extents and role must
        # be validated by with_name_boundary_reading; no prefix word list.
        source_address = occ.get("a") == first.start()
        if not source_address:
            source_address = any(
                b.get("source") == src and b.get("rolle") == "anrede"
                and b.get("a") == first.start() and b.get("na") == occ.get("a")
                and b.get("nb") == occ.get("b")
                for fig in (figures or []) if isinstance(fig, dict)
                for b in (fig.get("_name_boundary_readings") or [])
            )
        if not source_address:
            continue
        end = int(occ["b"])
        # either the validated component includes the vocative, or the
        # planner dropped the vocative but kept the words immediately after it.
        if span[0] <= occ["a"] and span[1] > end:
            remainder = src[end:span[1]]
            if re.match(r"\s*,\s*\S", remainder):
                return True
        elif span[0] >= end and re.fullmatch(r"\s*,\s*", src[end:span[0]]):
            return True
    return False


def apply_component_kind_readings(raw: str, components: Any, readings: dict[int, Any],
                                  *, figures: list[dict] | None, actor_id: str, actor_name: str) -> list[dict]:
    """Semantic component type is a proposal. Bind it to the ORIGINAL words
    and actor ID; an unproven type cannot create a speech/action Fact.
    Converted acts still undergo the usual independent vollzug and effect checks
    in the same server route. Other-figure narration never becomes puppet speech.
    """
    out = [dict(c) if isinstance(c, dict) else c for c in (components or [])]
    for i in component_kind_candidate_indices(raw, out, figures, actor_id):
        c = out[i]
        seg = str(c.get("segment") or "").strip()
        reading = readings.get(i)
        art = str(reading.get("art") or "").lower() if isinstance(reading, dict) else ""
        beleg = str(reading.get("beleg") or "").strip() if isinstance(reading, dict) else ""
        if art not in ("rede", "handlung") or not beleg or not _scene.literal_in(beleg, seg):
            c.update({"typ": "unklar", "typPruefung": {"grund": "art_nicht_bestaetigt"}})
            continue
        occ = name_occurrences(seg, figures)
        lead = next((o for o in occ if o.get("a") == 0), None)
        own_lead = bool(lead and lead.get("state") == "ok" and lead.get("ids") == {str(actor_id)})
        if art == "handlung":
            if not own_lead:
                c.update({"typ": "unklar", "typPruefung": {"grund": "handlung_akteur_nicht_belegt"}})
                continue
            category = str(reading.get("wirkung") or "").strip()
            if category not in ("zaertlich", "gewalt", "fesseln", "befreien", "ortswechsel", "annaeherung", "entfernung", "ohne_koerperwirkung"):
                c.update({"typ": "unklar", "typPruefung": {"grund": "wirkungsklasse_fehlt"}})
                continue
            c.update({"typ": "handlung", "akteur": actor_name, "zeit": "jetzt", "wirkung": category,
                      "geschieht": True,  # second model's proposal, NOT a writer verdict
                      "typPruefung": {"art": "handlung", "beleg": beleg}})
            # A speech-classified planner omitted the act declaration. This
            # independently read proposal supplies it; the separate blind
            # VOLLZUG check remains mandatory before any canonical action.
            # If the independent check is missing/denies, no action is stored.
        elif art == "rede":
            planner_ids = figure_ids_for_name(str(c.get("akteur") or ""), figures)
            if planner_ids and planner_ids != {str(actor_id)}:
                # P23: identify a vocative at its ORIGINAL position, including
                # a prefix the planner omitted from the speech segment. A
                # comma-delimited, unambiguous canonical name in the source
                # is required; a quoted third-party announcement stays foreign.
                vocative = _source_vocative_for_actor(raw, seg, figures, planner_ids)
                if not vocative:
                    # P24: the earlier kind check must not permanently reject
                    # a planner's WRONG speaker in a separately declared
                    # `einleitung`. This literal intro is rechecked by the
                    # independent speaker-role reader and canonical ID binder
                    # later. Until then this is only an untrusted proposal.
                    _found = _locate_segment(raw, seg)
                    _intro_ok = bool(_found and _intro_span(raw, c, _found))
                    if not _intro_ok:
                        c.update({"typ": "unklar", "typPruefung": {"grund": "rede_sprecher_fremd"}})
                        continue
                    c["typPruefung"] = {"art": "rede", "beleg": beleg, "sprecherrolle_offen": True}
                    continue
                c["akteur"] = actor_name
                # Preserve the caller's actual address even if the planner
                # returned only the imperative fragment (P22 lost "Gustav,").
                # This joins only the leading verified vocative with that same
                # immediately adjacent source segment, never invented words.
                source_span = _locate_segment(raw, seg)
                if source_span and source_span[0] > 0:
                    c["segment"] = str(raw or "")[:source_span[1]].strip()
            c["typPruefung"] = {"art": "rede", "beleg": beleg}
    return out


def announcement_act_components(raw: str, components: Any, actor_name: str) -> list[dict]:
    """V92 Paket 13 (AMASTER §24.7 keine stille Kuerzung, §34.1 jede Komponente eigene Validierung; live 05.11.: "Johann lächelt und
    sagt: „Schön, dich zu sehen.“" read as ONE speech with the `einleitung` "Johann lächelt und sagt"): the own act the blind speaker
    reading names LITERALLY inside a validated announcement becomes a component of the server - like the component of an unread
    *marker* (marker_act_components): segment = these words of the input, actor = the figure, no body class, no target claim, no
    `geschieht`; the server's mandatory blind vollzug reading and the one binder decide. Not when an act component of the reading
    already covers these words. The announcement keeps only the part after it (bind_input_components). Read only."""
    comps = components if isinstance(components, list) else []
    acts = [str(c.get("segment") or "").replace("*", "").strip() for c in comps
            if isinstance(c, dict) and str(c.get("typ") or c.get("type") or "").strip().lower() == "handlung"]
    out = []
    for c in comps:
        if not isinstance(c, dict) or str(c.get("typ") or c.get("type") or "").strip().lower() != "rede":
            continue
        h = str(((c.get("sprecherPruefung") or {}) if isinstance(c.get("sprecherPruefung"), dict) else {}).get("handlung") or "").strip(" ,.;:")
        span = _locate_segment(raw, str(c.get("segment") or ""))
        isp = _speech_intro(raw, c, span)[0] if span else None
        if not h or not isp:
            continue
        intro = raw[isp[0]:isp[1]]
        m = re.search(re.escape(h), intro)
        if not m or m.end() >= len(intro.rstrip(" :,\u2013\u2014-")) or any(seg and (_scene.literal_in(seg, h) or _scene.literal_in(h, seg)) for seg in acts):
            # not inside, or reaching the end of the announcement (its speech verb is no act), or already an act component
            continue
        # the words of the announcement before the act are its subject ("Johann" + "lächelt"): the act is the clause up to its end
        out.append({"typ": "handlung", "segment": intro[:m.end()].strip(), "akteur": str(actor_name or ""), "ziel": None, "zeit": "jetzt",
                    "wirkung": None, "bezug": None, "ansageHandlung": True})
    return out


def split_compound_acts(components: Any) -> list:
    """V92 Paket 12 (Paket-11-Pruefung, Original-Gegenprobe Paket 10: two acts the reading gave as ONE component were rejected
    as a whole - safe, but not complete): BEFORE the server's readings, an act component over several sentences becomes one
    component per sentence (same declaration, actor, target and proposed class; no reading carried over). Each gets its own
    blind vollzug reading, its own validation and its own Fact (§34.1). Form only (sentence ends)."""
    out = []
    for c in components if isinstance(components, list) else []:
        if (isinstance(c, dict) and str(c.get("typ") or c.get("type") or "").strip().lower() == "handlung"
                and len(sentence_parts(str(c.get("segment") or "").replace("*", " "))) > 1):
            for part in sentence_parts(str(c.get("segment") or "").replace("*", " ")):
                d = {k: v for k, v in c.items() if k not in ("vollzugPruefung", "wirkungPruefung", "sprecherPruefung", "koerperPruefung")}
                d["segment"] = part
                out.append(d)
        else:
            out.append(c)
    return out


def sentence_parts(text: str) -> list[str]:
    """The sentences of a marked or segmented part (split at sentence ends only, no word list)."""
    return [p.strip() for p in _SENTENCE_END_INSIDE.split(str(text or "").strip()) if re.search(r"\w", p)]


def marker_act_components(raw: str, components: Any, actor_name: str) -> list[dict]:
    """V92 Paket 9/10 (live 05.11.: the avatar planner left out a bare `*lächelt*` / `*nickt*` in 6 of 6 readings; Paket-9-Pruefung
    P9-02: only the FIRST marker was seen; AMASTER §27.3 "vom Nutzer ausdruecklich gesetzte Handlung", §24.2, §34.1): for EVERY
    *marker* of the input in which the reading has NO act component at all, one component of the server - segment = the marked
    words, actor = the figure, no body class, no target claim, no `geschieht` (the marking is the declaration). It gets the same
    mandatory blind vollzug reading and the same binder as every act. A marker the reading covers only in part gets no
    component: its unread rest stays visible (rest_ohne_komponente), it is never added to a checked act. Read only."""
    acts = [str(c.get("segment") or "").replace("*", "").strip() for c in (components if isinstance(components, list) else [])
            if isinstance(c, dict) and str(c.get("typ") or c.get("type") or "").strip().lower() == "handlung"]
    out = []
    for _a, _b, marked in marker_spans(raw):
        if any(seg and (_scene.literal_in(seg, marked) or _scene.literal_in(marked, seg)) for seg in acts):
            continue
        # V92 Paket 11 (Paket-10-Pruefung): a marker with several sentences holds several acts - one component (and one reading,
        # one Fact) per sentence, never one joint event
        for part in sentence_parts(marked):
            out.append({"typ": "handlung", "segment": part, "akteur": str(actor_name or ""), "ziel": None, "zeit": "jetzt",
                        "wirkung": None, "bezug": None, "markierung": True})
    return out


def apply_component_vollzug(components: Any, readings: dict) -> list:
    """V92: attach the server's blind readings (index -> reading dict) as `vollzugPruefung` on a copy of the components.
    Every `vollzugPruefung` that came with the plan (model-supplied) is removed first; a component without a complete reading
    carries none (the binder then reports `vollzug_nicht_geprueft`)."""
    out = copy.deepcopy(components) if isinstance(components, list) else []
    for c in out:
        if isinstance(c, dict):
            c.pop("vollzugPruefung", None)
    for i, r in (readings or {}).items():
        if vollzug_reading_complete(r) and 0 <= int(i) < len(out) and isinstance(out[int(i)], dict):
            out[int(i)]["vollzugPruefung"] = {"geschieht": r.get("geschieht"), "art": r.get("art"), "beleg": r.get("beleg"),
                                              "taeter": str(r.get("taeter") or "").strip()[:80],
                                              # V92 Paket 13: the reading's literal target name (may be empty)
                                              **({"ziel": str(r.get("ziel") or "").strip()[:80]} if isinstance(r.get("ziel"), str) else {})}
    return out


def act_rejection_text(grund: str) -> str:
    """V92: plain wording of why a component of the input was not executed (for the error shown to the person)."""
    g = str(grund or "")
    if g == "akteur_ist_nicht_der_sprecher":
        return "die Handlung gehört einer anderen Figur als der geführten"
    if g == "rede_akteur_ist_nicht_der_sprecher":
        return "die Rede gehört einer anderen Figur als der geführten"
    if g in ("akteur_unklar", "rede_sprecher_unklar"):
        return "der Name passt auf mehrere Figuren, es ist nicht eindeutig, wer es tut oder sagt (bitte den vollen Namen verwenden)"
    if g == "rede_sprecher_fehlt":
        return "es ist nicht belegt, wer das sagt"
    if g in ("ziel_unklar", "ziel_widerspricht_text", "ziel_name_unklar"):
        return "es ist nicht eindeutig, wen die Handlung trifft"
    if g == "ziel_nicht_anwesend_oder_unbekannt":
        return "die genannte Zielperson ist unbekannt oder nicht in der Szene; die Handlung wurde nicht ausgefuehrt"
    if g in ("wirkung_ohne_gebundenes_ziel", "koerperwirkung_ohne_zielperson"):
        return "die Zielperson ist nicht eindeutig gebunden; es wurde keine Wirkung ausgefuehrt"
    if g == "akteur_name_unklar":
        return "ein genannter Name ist unbekannt oder nicht eindeutig, es ist nicht belegt, wer die Handlung ausführt"
    if g == "rede_sprecher_name_unklar":
        return "ein genannter Name ist unbekannt oder nicht eindeutig, es ist nicht belegt, wer das sagt"
    if g == "segment_mehrere_saetze":
        return "mehrere Sätze wurden als eine einzige Handlung gelesen"
    if g == "plan_fehlt":
        return "die Handlung konnte nicht geprüft werden (keine Lesung verfügbar)"
    if g == "koerper_laesst_es_nicht_zu":
        return "die Figur kann das jetzt nicht ausführen (sie schläft – möglich ist nur das eigene Aufwachen – oder ist bewusstlos oder bewegungsunfähig)"
    if g == "kann_jetzt_nicht_sprechen":
        return "die Figur kann jetzt nicht sprechen (sie schläft, ist bewusstlos, geknebelt oder stumm)"
    if g in ("zerlegung_unvollstaendig", "komponente_ungueltig", "rest_ohne_komponente", "rede_nicht_im_eingang"):
        return "dieser Teil wurde nicht als Rede oder Handlung gelesen"
    if g == "vollzug_nicht_geprueft":
        return "es konnte nicht geprüft werden, ob die Handlung wirklich geschieht (keine vollständige Prüfung verfügbar)"
    if g == "vollzug_beleg_nicht_woertlich":
        return "die unabhängige Vollzugsprüfung nennt eine Stelle, die nicht im tatsächlichen Handlungstext steht"
    if g in ("handlung_nicht_vollzogen", "vollzug_nicht_angegeben"):
        return "die Handlung geschieht nach dem Wortlaut nicht oder ist nicht belegt (verneint, gewünscht, gefragt, bedingt oder angekündigt)"
    if g.startswith(("zeit_", "satzzeit_")):
        return "die Handlung geschieht nicht jetzt"
    if g in _STRUCTURAL_ACT_FAULTS:
        return "der Satzteil ist keine vollständige Handlung der Eingabe"
    return "sie konnte nicht eindeutig als Handlung gelesen werden"


def input_rejection_text(ambiguous: list | None) -> str:
    """V92 (Paket-8-Pruefung): why NOTHING of a direct input (puppet, avatar) was executable - the rejected components first,
    otherwise the unread parts. One wording for both routes."""
    amb = [a for a in (ambiguous or []) if isinstance(a, dict) and a.get("grund")]
    rej = [a for a in amb if isinstance(a.get("vorschlag"), dict)] or [a for a in amb if a.get("grund") != "wirkung_unklar"]
    return "; ".join(f"„{str(a.get('segment') or '')[:80]}“ – {act_rejection_text(a.get('grund'))}" for a in rej[:3])


_STRUCTURAL_ACT_FAULTS = frozenset({"segment_satz_unvollstaendig", "segment_wortgrenze", "segment_nicht_im_eingang", "segment_bereits_gebunden"})


def bind_input_components(
    raw: str,
    components: Any,
    *,
    actor_id: str,
    actor_names: list[str],
    figures: list[dict] | None,
    present_ids: list[str],
    default_target: str | None,
    text_tense: str | None,
    addressee_id: str | None = None,
    cut: bool = False,
) -> dict[str, Any]:
    """Validate the planner's components of ONE input (AMASTER §24.2, §34.1).
    V65Z (A05): each act segment is checked against the original text (segment_binding_fault: quotation, complete clause),
    and a target the reading names must be named in the input itself or be the bound addressee (`default_target` / the
    route's `addressee_id`) - "Ich küsse dich." to Tammy is never bound to Kvle because a reading says so.

    Returns {"speech": str|None, "actions": [...], "ambiguous": [...],
    "used": bool}. A component that cannot be bound safely is never committed
    as world truth; it stays visible as an ambiguity record (§24.7) and its
    text remains expressed speech, so nothing the user typed is lost.
    """
    out: dict[str, Any] = {"speech": None, "actions": [], "ambiguous": [], "used": False}
    if cut:
        # V65Z (A04): the reading was cut at its token limit - what it lists is checked, what it lost stays speech, visibly
        out["ambiguous"].append({"segment": str(raw or "")[:160], "grund": "lesung_abgeschnitten"})
    if not isinstance(components, list) or not components:
        return out
    # V92 Paket 17 (Paket-16-Pruefung N1-N4): the operator's answers are placed in THIS input - each binds only the place it was
    # given for and only a figure that place offers (place_klaerungen); every reader below reads them at their place (`base`)
    figures = place_klaerungen(raw, figures)
    present = [f for f in (figures or []) if isinstance(f, dict) and str(f.get("id") or "") in set(present_ids)]
    own = {_norm_name(n) for n in actor_names if n} | {"ich"}
    # V92 Paket 10 (Paket-9-Pruefung P9-01/P9-02): the markers are known here, once, for the whole input. They never make an act
    # text and never cut one short; a marker no component reads at all is an unread act of its own (without the server's
    # reading: vollzug_nicht_geprueft) - the same component the routes add BEFORE the reading (marker_act_components).
    _marks = marker_spans(raw)
    components = list(components) + marker_act_components(raw, components, "")
    spans: list[tuple[int, int]] = []
    own_act_subject_spans: list[tuple[int, int]] = []   # P25: source spans checked against own canonical actor ID
    # V67 (Audit7 V66-06 z03/z04; §34.1, §68 Nr. 63): each act component binds its OWN place of the input - two components
    # with the same words bind two places if the input has them twice, otherwise the second is no second act (V66: both bound
    # the first place -> two acts from one sentence, and the second sentence stayed as speech)
    _place: dict[int, tuple[int, int] | None] = {}
    _dup: set[int] = set()
    _taken: list[tuple[int, int]] = []
    _intro: dict[int, tuple[int, int]] = {}
    for _ci, _c in enumerate(components):
        if not isinstance(_c, dict):
            continue
        _seg = str(_c.get("segment") or "")
        if str(_c.get("typ") or _c.get("type") or "").strip().lower() == "handlung":
            _sp = _locate_segment(raw, _seg, _taken)
            if _sp is None and _locate_segment(raw, _seg) is not None:
                _dup.add(_ci)
            if _sp:
                _taken.append(_sp)
        else:
            _sp = _locate_segment(raw, _seg)
            _isp = None
            if str(_c.get("typ") or _c.get("type") or "").strip().lower() == "rede":
                # V92 Paket 14: a validated announcement at the start of the speech segment is no spoken word (_speech_intro)
                _isp, _sp = _speech_intro(raw, _c, _sp)
            if _isp:
                _intro[_ci] = _isp
        _place[_ci] = _sp
    # V92 Paket 13: an own act inside a validated announcement (announcement_act_components) is its own component - the
    # announcement keeps only the part after that act ("Johann lächelt | und sagt:"); form only
    _intro_orig = dict(_intro)
    for _ci, (_ia, _ib) in list(_intro.items()):
        _inside = [b for k, sp in _place.items() if sp and k not in _intro and sp[0] >= _ia and sp[1] <= _ib
                   for a, b in [sp] if str((components[k] or {}).get("typ") or "").strip().lower() == "handlung"]
        if _inside:
            _na = max(_inside)
            while _na < _ib and raw[_na].isspace():
                _na += 1
            if _na < _ib:
                _intro[_ci] = (_na, _ib)
            else:
                _intro.pop(_ci)
    # V65Z (A05): where every component of this reading lies in the input (for the complete-clause check);
    # V92: a speech component begins where its validated introduction begins
    _all_spans = [((_intro[_k][0], _sp[1]) if _k in _intro else _sp) for _k, _sp in _place.items() if _sp]
    _named_ids = _named_in(raw, present, set()) if present else set()
    _rejected_idx: list[int] = []
    for comp_index, comp in enumerate(components):   # V65Z (A04, §24.2/§34.1): every act is checked on its own
        if not isinstance(comp, dict):
            continue
        typ = str(comp.get("typ") or comp.get("type") or "").strip().lower()
        if typ != "handlung":
            continue
        seg = str(comp.get("segment") or "")
        span = _place.get(comp_index)
        why = None
        if span is None:
            why = "segment_bereits_gebunden" if comp_index in _dup else "segment_nicht_im_eingang"
        else:
            why = segment_binding_fault(raw, span, [sp for sp in _all_spans if sp != span])
        if not why and len(sentence_parts(str(seg).replace("*", " "))) > 1:
            # V92 Paket 11 (Paket-10-Pruefung; §34.1): one act component over several sentences is not ONE act - it is never
            # committed as one joint event (the routes give the parts of a marker their own components and readings)
            why = "segment_mehrere_saetze"
        # V92 Paket 11 (Paket-10-Pruefung; §24.1, §46.2, §27.3/§27.4): whose act it is, is bound to the figure ID by the cast data
        # (component_party) - not by a shared first name, not by a user name or session alias. Someone else's act told by
        # the avatar/puppet is a claim, not an event of this figure; a name that fits several figures decides nothing.
        zeit = str(comp.get("zeit") or "jetzt").strip().lower()
        _vp = comp.get("vollzugPruefung") if isinstance(comp.get("vollzugPruefung"), dict) else {}
        _t = str(_vp.get("taeter") or "")
        _rz = str(_vp.get("ziel") or "").strip() if isinstance(_vp.get("ziel"), str) else ""
        # V92 Paket 13/14: the act's words, read ONCE by the one identity reading, with the reading's literal names (target, doer).
        # V92 Paket 14 (Paket-13-Pruefung "ein unmittelbar davorstehender, identitaetsbestimmender Teil"; live 05.11.: the planner
        # gave "reicht Mara Wasser." / "schubst Mara Schmidt." without the subject): the act's WHOLE clause - its segment extended
        # backwards over the directly adjacent words of the same clause (act_clause_span) - so a subject the segment leaves out
        # ("Johann Weber" before "winkt") is read too.
        _why_k = None   # V92 Paket 16: what the operator can be asked about this doer
        _cl_a = act_clause_span(raw, span, [sp for sp in _all_spans if sp != span]) if span else None
        # V92 Paket 15 (Paket-14-Pruefung): and forwards to the end of the written name/clause - a segment that stops inside a
        # name ("Johann schubst Mara Nowak" of "... Mara Nowak-Schmidt.") cannot hide the rest of it
        _cl_b = clause_end(raw, span[1], [sp for sp in _all_spans if sp != span]) if span else None
        _clause = raw[_cl_a:_cl_b] if span else ""
        # V92 Paket 17: at its place in the input (`base`) - an answer for the same name elsewhere does not bind here
        _seg_occ = name_occurrences(_clause, present, [n for n in (_rz, _t) if n.strip()], base=_cl_a) if span else []
        _opening = opening_name(_clause, _seg_occ)
        # V92 Paket 17: whose act - a name the operator answered at its place here decides by the chosen ID (_claimed_party)
        _party = (_claimed_party(_seg_occ, comp.get("akteur"), actor_id)
                  or component_party(str(comp.get("akteur") or ""), actor_id, present, actor_names))
        if not why and _party == "fremd":
            why = "akteur_ist_nicht_der_sprecher"
            # V92 Paket 17 (eigene Pruefung 06.11.; Paket 16 fragte nur bei der Blindlesung): the planner's doer is a name the
            # one identity reading leaves unbound at its place and that holds a cast name ("Anna Johann Bruckner") - the operator
            # is asked, as for the blind reading's doer
            _why_k = identity_klaerung([o for o in unresolved_names(_seg_occ) if o["words"] == _name_words(comp.get("akteur"))],
                                       _clause, base=_cl_a or 0)
        elif not why and _party == "unklar":
            why = "akteur_unklar"
        if not why:
            # V92 (Live-Befund 04.11. Puppet Mara, "Johann nimmt Mara an der Hand."): the planner's `akteur` is a model claim. The blind
            # vollzug reading names who does it according to the utterance ("figur" = the figure itself); a doer who is not this
            # figure makes it a foreign act.
            _tp = (_claimed_party(_seg_occ, _t, actor_id) or component_party(_t, actor_id, present, actor_names)) if _t.strip() else None
            if _tp == "fremd":
                why = "akteur_ist_nicht_der_sprecher"
                # V92 Paket 16: the reading's doer is a full name nobody carries that holds a cast name ("Anna Johann Bruckner") -
                # whether that is this figure only the operator can say
                _why_k = identity_klaerung([o for o in _seg_occ if o["state"] == "unbekannt" and o["words"] == _name_words(_t)], _clause, base=_cl_a)
            elif _tp == "unklar":
                why = "akteur_unklar"
        if not why and _opening is not None:
            # the clause opens with a name in subject position (no punctuation after it): that is the doer of a German statement -
            # another figure -> a foreign act; a name of several figures incl. this one -> unclear; an unknown name / unclear extent
            # -> unproven. The readings (planner `akteur`, blind `taeter`) cannot override what the text itself says here.
            if _opening["state"] != "ok":
                why = "akteur_name_unklar"
                _why_k = identity_klaerung([_opening], _clause, base=_cl_a)
            elif str(actor_id or "") not in _opening["ids"]:
                why = "akteur_ist_nicht_der_sprecher"
            elif len(_opening["ids"]) > 1:
                why = "akteur_unklar"
                _why_k = identity_klaerung([_opening], _clause, base=_cl_a)
        if not why and unresolved_names(_seg_occ) and _opening is None:
            # V92 Paket 14 (Paket-13-Pruefung; AMASTER §24.1, §24.7, §34.1, fail-closed §6.2): the act's words name an unknown person
            # or a name of unproven extent ("Johann Weber winkt.", "Johann schubst Mara Schmidt."). The doer is then proven only by
            # the text itself: the reading's literal doer stands there in full and binds this figure ("Johann", "ich") - or every such
            # name is the reading's full literal TARGET and does not open the clause. A shortened or nameless reading ("Johann" for
            # "Johann Weber", "figur") never makes it this figure's act.
            _first = next((m.start() for m in re.finditer(r"\w", _clause)), 0)
            # the first person that opens the clause is the figure itself (the contract word "ich" of component_party)
            if not (role_witnessed(_seg_occ, _t, str(actor_id or "")) or _opens_with_ich(_clause)
                    or names_accounted(unresolved_names(_seg_occ), _rz, _first)):
                why = "akteur_name_unklar"
                _why_k = identity_klaerung(unresolved_names(_seg_occ), _clause, base=_cl_a)
        # P25/R1: The planner may omit the subject from the act segment.
        # Count an immediately adjacent, complete source-bound OWN subject
        # as read, never an unbound cast name, an unknown extent, or another
        # person's name. The validated act remains separate from its subject.
        if (not why and span and _cl_a is not None and _cl_a < span[0] and
                _party == "eigen" and _opening is not None and
                _opening.get("state") == "ok" and _opening.get("ids") == {str(actor_id or "")} and
                not raw[_cl_a:_cl_a + int(_opening["a"])].strip() and
                not raw[_cl_a + int(_opening["b"]):span[0]].strip()):
            own_act_subject_spans.append((_cl_a, span[0]))
        if not why and zeit != "jetzt":
            why = f"zeit_{zeit}"
        if not why and text_tense in ("past", "future"):
            why = f"satzzeit_{text_tense}"
        if not why:
            # V92 (Gegenpruefung 04.11. Fall A; AMASTER §24.2, §34.1, fail-closed §6.2): an act is an event only when it HAPPENS.
            # The planner must declare it (`geschieht`), and the independent blind reading (`vollzugPruefung`, app.py) may not
            # contradict it. A missing declaration is an unproven act, a denied/wished/asked/conditional one is no act. No word list.
            why = act_vollzug_fault(comp, [p for _a, _b, t in _marks for p in sentence_parts(t)],
                                    [raw[a:b] for a, b in _intro_orig.values()])
        if why:
            # P25/R1: a complete independent non-event reading does not
            # license an act, but it IS a reading (not an omitted component).
            # Without that reading the former fail-closed behavior is kept.
            read_non_event = (why == "handlung_nicht_vollzogen" and
                              vollzug_reading_complete(_vp) and
                              (_vp.get("geschieht") is False or
                               str(_vp.get("art") or "").strip().lower() != "tatsaechlich"))
            out["ambiguous"].append({"segment": seg[:160], "grund": why, "vorschlag": copy.deepcopy(comp),
                                     **({"readNonEvent": True} if read_non_event else {}),
                                     **({"klaerung": _why_k} if _why_k and why in ("akteur_name_unklar", "akteur_unklar", "akteur_ist_nicht_der_sprecher") else {})})
            _rejected_idx.append(comp_index)
            continue
        valid_effect, effect = effect_kind_from_wirkung(comp.get("wirkung"))
        target = None
        ziel = str(comp.get("ziel") or "").strip()
        # V92 Paket 12 (Paket-11-Pruefung; AMASTER §24.1, §25 Namensnennung, §34.1, §46.2): the target is bound by the cast data
        # (one identity procedure) AND checked against the act's OWN words: when they name a figure (besides the actor), the
        # target must be that figure - a reading that claims another one ("Johann schubst Mara Schmidt" -> ziel Mara Nowak)
        # binds nobody; a name the act gives that fits several figures ("Mara" with two Maras present) binds nobody. Without
        # a bound person a body effect is not validated (V66 E05) - it can never reach the wrong body, runtime or memory.
        # V92 Paket 13 (Paket-12-Pruefung N1/N2, Bedingung B): the act's words are read by the one identity reading; the blind
        # vollzug reading's LITERAL target name tells where a name ends ("Mara" in "reicht Mara Wasser", "Mara Schmidt" whole) -
        # an unknown person named there makes the target unclear: the selected recipient never replaces a named other person.
        # V92 Paket 14 (Paket-13-Pruefung N1): a shorter literal target ("Mara") never overrides the longer name of the text
        # ("Mara Schmidt") - name_occurrences reads its extent; the occurrence is "unklar" and binds nobody.
        _seg_ids = {i for o in _seg_occ if o["state"] == "ok" and len(o["ids"]) == 1 for i in o["ids"]}
        _seg_amb = any(o["state"] != "ok" or len(o["ids"]) != 1 for o in _seg_occ)
        # the visible reason names what is unclear: a name of unproven extent, an unknown person, or a name several figures carry
        _seg_unclear = ("ziel_name_unklar" if any(o["state"] == "unklar" for o in _seg_occ)
                        else "ziel_nicht_anwesend_oder_unbekannt" if any(o["state"] == "unbekannt" for o in _seg_occ) else "ziel_unklar")
        _seg_ids.discard(str(actor_id or ""))
        # V92 Paket 16: the clarification an unbound target name offers (present figures only, never the doer itself)
        _seg_k = identity_klaerung([o for o in _seg_occ if o["ids"] != {str(actor_id or "")}], _clause,
                                   exclude=[str(actor_id or "")], allowed=present_ids, base=_cl_a or 0)
        _ziel_own = bool(ziel) and component_party(ziel, actor_id, present, actor_names) == "eigen"
        _tfault = None
        if ziel and not _ziel_own:
            _ids = figure_ids_for_name(ziel, present)
            # V92 Paket 16 (browser 05.11.: "Ich berühre Mara." answered "Mara Schmidt", the planner still claimed Mara Nowak ->
            # no target): a name of the act's words the OPERATOR bound by the clarification outranks the planner's claim
            _geklaert = {i for o in _seg_occ if o.get("geklaert") for i in o["ids"]} - {str(actor_id or "")}
            if len(_geklaert) == 1 and _geklaert <= set(present_ids or []):
                _ids = _geklaert
            if not _ids:
                _tfault = "ziel_nicht_anwesend_oder_unbekannt"
            elif len(_ids) > 1:
                _tfault = "ziel_unklar"
            else:
                target = next(iter(_ids))
                if _seg_ids and target not in _seg_ids:
                    _tfault = "ziel_widerspricht_text"
                elif not _seg_ids and _seg_amb:
                    _tfault = _seg_unclear
                elif not _seg_ids and target not in _named_ids and target not in {str(default_target or ""), str(addressee_id or "")}:
                    # V65Z (A05): the reading's target is neither named in the input nor the bound addressee - not bound
                    _tfault = "ziel_nicht_im_eingang"
                if _tfault:
                    target = None
            if _tfault:
                out["ambiguous"].append({"segment": seg[:160], "grund": _tfault, "ziel": ziel[:60],
                                         **({"klaerung": _seg_k} if _seg_k and _tfault in ("ziel_name_unklar", "ziel_unklar", "ziel_nicht_anwesend_oder_unbekannt") else {})})
        if target is None and not _tfault and default_target and (not ziel or _ziel_own):
            # the bound addressee only where the act's own words do not name someone else or an ambiguous name
            if (not _seg_ids or str(default_target) in _seg_ids) and not (_seg_amb and str(default_target) not in _seg_ids):
                target = default_target
            elif valid_effect and effect in BODY_EFFECTS_NEED_TARGET:
                out["ambiguous"].append({"segment": seg[:160], "grund": _seg_unclear if _seg_amb else "ziel_widerspricht_text",
                                         **({"klaerung": _seg_k} if _seg_k and _seg_amb and _seg_unclear in ("ziel_name_unklar", "ziel_unklar", "ziel_nicht_anwesend_oder_unbekannt") else {})})
        elif target is None and not _tfault and (not ziel or _ziel_own) and any(
                o["state"] != "ok" or len(o["ids"]) != 1 for o in _seg_occ if o["ids"] != {str(actor_id or "")}):
            # V92 Paket 14 (Paket-13-Pruefung: "kein Ambiguitaetsvermerk"): the act's words name someone who stays unbound - visible
            out["ambiguous"].append({"segment": seg[:160], "grund": _seg_unclear,
                                     **({"klaerung": _seg_k} if _seg_k and _seg_unclear in ("ziel_name_unklar", "ziel_unklar", "ziel_nicht_anwesend_oder_unbekannt") else {})})
        if target is None and ziel and not _ziel_own and valid_effect and effect not in (None, "move"):
            # V66 (Audit5 E05): the reading names a target this input does not bind ("Ich schlage Freya." - Freya unknown or
            # absent) - the act stays expressed and visible, its effect on that person is not validated (V65Z: strike,
            # effectValid True). A change of place ("move") and an act without effect need no person.
            out["ambiguous"].append({"segment": seg[:160], "grund": "wirkung_ohne_gebundenes_ziel", "wert": str(comp.get("wirkung"))[:40]})
            valid_effect, effect = False, None
        elif target is None and valid_effect and effect in BODY_EFFECTS_NEED_TARGET:
            out["ambiguous"].append({"segment": seg[:160], "grund": "koerperwirkung_ohne_zielperson", "wert": str(comp.get("wirkung"))[:40]})
            valid_effect, effect = False, None
        # The effect reader may have approved Mara Nowak while the operator
        # subsequently resolved the action to Mara Schmidt. The confirmed effect
        # is never transferred to a different or ambiguously named body.
        _wp = comp.get("wirkungPruefung") if isinstance(comp.get("wirkungPruefung"), dict) else None
        if valid_effect and target and _wp and (_wp.get("bestaetigt") is True or _wp.get("ersatz") == "zaertlich"):
            _verified_name = str(_wp.get("ziel") or comp.get("ziel") or "").strip()
            _verified_ids = figure_ids_for_name(_verified_name, present)
            _final_id = str(target)
            # A unique verified target must be the FINAL canonical recipient.
            # Where the effect reader said only "Mara" in a scene with two
            # Maras, the answer to the operator's specific name occurrence
            # supplies the missing ID. Never let an answer to another occurrence
            # in the same clause, or an unbound same-name claim, validate it.
            _verified_words = _name_words(_verified_name)
            _name_places = [o for o in _seg_occ if _verified_words and
                            _verified_words in (o.get("words"), o.get("klaert"))]
            _place_bound = (len(_name_places) == 1 and
                            _name_places[0].get("geklaert") is True and
                            _name_places[0].get("ids") == {_final_id})
            _verified_target = (_verified_ids == {_final_id} or
                                (len(_verified_ids) > 1 and _final_id in _verified_ids and _place_bound))
            if not _verified_target:
                valid_effect, effect = False, None
                out["ambiguous"].append({"segment": seg[:160], "grund": "wirkungsziel_nach_klaerung_abweichend",
                                         "pruefziel": _verified_name[:80], "gebundenesZielId": target})
        a, b = span
        spans.append(span)
        out["actions"].append({
            "text": raw[a:b].strip().strip("*").strip(),
            "targetId": target,
            "effectKind": effect,
            "effectValid": valid_effect,
            # A proposal whose named recipient could not be bound stays visible
            # to operator/UI, but it is NEVER a canonical performed action.
            "targetBindingInvalid": bool(
                (_tfault and ziel and not _ziel_own)
                or (target is None and _rz and any(
                    o.get("state") != "ok" and o.get("words") == _name_words(_rz)
                    for o in _seg_occ))),
            "wirkung": comp.get("wirkung"),
            # V65J: the separate body-effect reading of this component (audit).
            "wirkungPruefung": copy.deepcopy(comp.get("wirkungPruefung")) if isinstance(comp.get("wirkungPruefung"), dict) else None,
            # V92 Paket 18: the server's reading of the change this act makes to the actor's own body (validated by the writer's caller)
            "koerperPruefung": copy.deepcopy(comp.get("koerperPruefung")) if isinstance(comp.get("koerperPruefung"), dict) else None,
            # V65W (C1): the act readings against standing restricted boundaries (server-side, before the write)
            "grenzBezug": copy.deepcopy(comp.get("grenzBezug")) if isinstance(comp.get("grenzBezug"), list) else None,
            # V65W (C7): the act readings against his own requests she accepted (server-side, before the write)
            "bitteBezug": copy.deepcopy(comp.get("bitteBezug")) if isinstance(comp.get("bitteBezug"), list) else None,
            # V60 (AMASTER §35/§36.1): proposed reference to an open request;
            # the kernel validates it before binding (never guessed here).
            "bezug": str(comp.get("bezug") or "").strip()[:80] or None,
            # V61: the planner's component index, so a profile-rule binding
            # ("profilregeln".komponente) reaches exactly this act's Fact.
            "componentIndex": comp_index,
        })
        if not valid_effect and not any(x.get("segment") == seg[:160] and x.get("grund") in ("wirkung_ohne_gebundenes_ziel",
                                                                                            "koerperwirkung_ohne_zielperson")
                                        for x in out["ambiguous"]):
            out["ambiguous"].append({"segment": raw[a:b][:160], "grund": "wirkung_unklar", "wert": str(comp.get("wirkung"))[:40]})
    # V92 (Paket-8-Pruefung C5/C6; AMASTER §24.2, §24.7, §27.3/§27.4, §34.1; Kettenvertrag §6): what the figure SAYS is ALWAYS
    # the validated own speech of the reading - with or without an act, with a cut reading or not, for the puppet and the avatar
    # alike. Before, a reading without any act (pure speech) skipped the speaker check and the caller took the whole input as
    # speech ("Mara sagt: Lass mich in Ruhe!" became Johann's speech), and a cut reading made every unlisted rest speech
    # (V65Z A04 "Rest bleibt Rede" - withdrawn). What no validated component covers is no speech; it stays visible
    # (`rest_ohne_komponente`, `rede_*`, `lesung_abgeschnitten`). The words of a rejected component are visible under their
    # own rejection reason and are not listed a second time.
    _rejected_spans = [_place[i] for i in _rejected_idx if _place.get(i)]
    _addr: dict = {}
    out["speech"], _unassigned = _speech_from_components(raw, components, _place, spans, own, _intro, visible=_rejected_spans,
                                                         marked=[(a, b) for a, b, _t in _marks], actor_id=actor_id,
                                                         figures=present, actor_names=actor_names, addressee=_addr,
                                                         own_act_subject_spans=own_act_subject_spans, cut=bool(cut))
    out["ambiguous"].extend(_unassigned)
    if _addr.get("conflict"):
        out["speechTargetConflict"] = True
    if out["speech"] and _addr.get("set"):
        # V92 Paket 14: the speech's addressee decided by its own words (explicit, or unbound) - the routes use it instead of the
        # selected recipient for the speech Fact (commit_puppet target_id, commit_turn speech target)
        out["speechTargetSet"], out["speechTarget"] = True, _addr.get("id")
    out["used"] = bool(out["actions"] or out["speech"])
    return out


_INTRO_SEPARATOR = re.compile(r"[\s:\-\u2013\u2014\u201e\u201c\u201d\u00bb\u00ab\"']*")


def _intro_span(raw: str, comp: dict, rede_span: tuple[int, int] | None) -> tuple[int, int] | None:
    """V92 (Segment-Gate, Freigabe 04.11.): the clause part that ANNOUNCES a speech ("... und sagt leise: <Rede>") is a
    component of its own reading, not an unassigned rest. The planner names it as `einleitung` of the rede component; it is
    valid only when it stands literally in the input DIRECTLY before the speech (only blanks, colon, dash, quotation marks
    between). Anything else is no introduction (None) and the old completeness check applies. No word list: the form decides."""
    intro = str((comp or {}).get("einleitung") or "").strip()
    if not intro or not rede_span:
        return None
    ra = rede_span[0]
    # V92 Paket 9 (live 05.11.: the avatar planner gave "*lächelt*" as the `einleitung` of "Hallo Mara."): a part the person
    # marked with *stars* is by their explicit decision an act (§27.3), never the announcement of a speech. Form only.
    _marks = [(mm.start(), mm.end()) for mm in _ACTION_STAR_RE.finditer(raw)]
    for m in re.finditer(re.escape(intro), raw):
        if m.end() <= ra and _INTRO_SEPARATOR.fullmatch(raw[m.end():ra] or ""):
            if any(m.start() < mb and ma < m.end() for ma, mb in _marks):
                return None
            return (m.start(), m.end())
    return None


def _speech_from_components(raw: str, components: list, place: dict[int, tuple[int, int] | None], act_spans: list[tuple[int, int]],
                            own: set[str], intro: dict[int, tuple[int, int]] | None = None,
                            visible: list[tuple[int, int]] | None = None,
                            marked: list[tuple[int, int]] | None = None, actor_id: str = "",
                            figures: list[dict] | None = None, actor_names: Any = (),
                            addressee: dict | None = None,
                            own_act_subject_spans: list[tuple[int, int]] | None = None, cut: bool = False) -> tuple[str | None, list[dict]]:
    """V92 (AMASTER §34.1 jede Komponente eigene Validierung, §24.2/§24.7 keine geratene Wahrheit, keine stille Kuerzung; Kettenvertrag
    §6; live 04.11.: "Johann zieht Mara an sich und küsst sie." stored the speech "und." for Johann): what the figure SAYS is the
    text of the planner's validated `rede` components - each located literally in the input, by the figure itself, outside the
    validated acts. The text no component covers is NOT speech (V91 made every rest outside the acts speech); it stays visible as an
    ambiguity record (`rest_ohne_komponente`, `rede_*` for a speech component that could not be bound). The one structural
    tolerance is the one segment_binding_fault already has: a single word that stands alone between two components is their
    connection ("... an sich und küsst sie"), not an unassigned part. No word list.
    Returns (speech or None, ambiguity records)."""
    amb: list[dict] = []
    rede: list[tuple[int, int]] = []
    intro_cover: list[tuple[int, int]] = []
    # V92 (Paket-8-Pruefung): the parts of the input a rejected component stands on are visible under its rejection reason
    seen = [sp for sp in (visible or []) if sp]
    _abgewiesen: list[tuple[int, int]] = list(seen)   # Stand 11C: Stellen abgewiesener Komponenten (ihr Rest wird nie Rede)
    for ci, comp in enumerate(components):
        if not isinstance(comp, dict) or str(comp.get("typ") or comp.get("type") or "").strip().lower() != "rede":
            continue
        seg = str(comp.get("segment") or "")
        span = place.get(ci)
        if span is not None:
            # the sentence mark directly after the spoken words belongs to them ("Hallo Mara" + "." -> "Hallo Mara."); form only
            _m = re.match(r"[.!?\u2026]+", raw[span[1]:])
            if _m:
                span = (span[0], span[1] + _m.end())
        # V92 Paket 11 (Paket-10-Pruefung; §24.1, §27.3/§27.4, §34.1): the speaker of a speech component is bound to the figure
        # ID like an actor: missing -> unproven, another figure -> foreign, a name of several figures -> unclear. Independently
        # of the reading's field, the announcement of the speech in the input (its validated `einleitung`, or the words right
        # before it that end in ':' or an opening quotation mark) may not name only other figures ("Mara sagt: ...").
        _sp = component_party(str(comp.get("akteur") or ""), actor_id, figures, list(actor_names or []) + sorted(own))
        _ann_ids, _ann_amb, _need = set(), False, False
        _r = comp.get("sprecherPruefung") if isinstance(comp.get("sprecherPruefung"), dict) else None
        _sp_lit, _ad_lit = str((_r or {}).get("sprecher") or ""), str((_r or {}).get("adressat") or "")
        _name_fault, _occA, _unres, _others = None, [], [], list(act_spans) + [sp for k, sp in place.items() if sp and k != ci]
        _ich = False   # V92 Paket 14: the announcing clause opens with the first person - its names are addressees, not the speaker
        _address_ids: set[str] = set()
        if span is not None and figures:
            # V92 Paket 14 (Paket-13-Pruefung N2/N3): the WHOLE announcing clause, not only the part the reading called `einleitung`
            _cl = speech_clause_announcement(raw, span, intro[ci] if intro and ci in intro else None, _others)
            _ann = raw[_cl[0]:_cl[1]] if _cl else ""
            _ich = _opens_with_ich(_ann)
            _need, _ann_ids, _ann_amb = speaker_reading_needed(_ann, figures, bool(_cl and _cl[2]), base=_cl[0] if _cl else None)
            # V92 Paket 17: at its place in the input (`base`); a name the operator answered here decides the speaker by its ID
            _occA = name_occurrences(_ann, figures, [n for n in (_sp_lit, _ad_lit) if n.strip()], base=_cl[0] if _cl else None)
            _sp = _claimed_party(_occA, comp.get("akteur"), actor_id) or _sp
            _unres = unresolved_names(_occA)
            _ann_amb = any(o["state"] == "ok" and len(o["ids"]) != 1 for o in _occA)
            # P24: `Gustav,` is not a speaker declaration. The semantic
            # read must bind the address to the same literal name occurrence.
            _address_ids = _announcement_address_ids(raw, _ann, _cl[0] if _cl else None, figures, _r)
            if _address_ids and _ad_lit:
                # A validated title+name address ("Herr Pfeiffer") must not
                # turn into an *unknown other person* merely because the
                # second reading repeats its full literal address string.
                # It is proved only if the SAME source position binds an ID.
                _source_addresses = [o for o in name_occurrences(_ann, figures, base=_cl[0] if _cl else None)
                                     if o.get("state") == "ok" and o.get("ids") <= _address_ids]
                _unres = [o for o in _unres if not (
                    o.get("words") == _name_words(_ad_lit)
                    and any(int(o.get("a", -1)) <= int(addr["a"]) < int(addr["b"]) <= int(o.get("b", -1))
                            for addr in _source_addresses)
                )]
            _ann_ids -= _address_ids
            if _address_ids and not _ann_ids and not _unres and not _ann_amb:
                _need = False   # verified address, not a speaker announcement
                # The planner may have attributed speech to the person being
                # addressed. Only a *verified* source-bound role may override
                # that false proposal; identity still comes from canonical ID.
                if (_sp == "fremd" and figure_ids_for_name(str(comp.get("akteur") or ""), figures)
                        and figure_ids_for_name(str(comp.get("akteur") or ""), figures) <= _address_ids):
                    _sp = "eigen"
            if _unres:
                # an unknown person or a name of unproven extent in the clause: the speaker is proven by the text itself (the clause
                # opens with this figure's full name or with "ich") - or by the reading's literal full name of this figure - or the
                # unknown name is the reading's full literal addressee and does not open the clause. A shortened reading ("Johann"
                # for "Johann Weber") or "figur" is not.
                _first = next((m.start() for m in re.finditer(r"\w", _ann)), 0)
                _op = opening_name(_ann, _occA)
                if (_op is not None and _op["state"] == "ok" and _op["ids"] == {str(actor_id or "")}) or _ich:
                    _need = False   # the text proves the speaker; the names are addressees
                elif not (_r and (role_witnessed(_occA, _sp_lit, str(actor_id or ""))
                                  or (names_accounted(_unres, _ad_lit, _first)
                                      and (_claimed_party(_occA, _sp_lit, actor_id)
                                           or component_party(_sp_lit, actor_id, figures, list(actor_names or []) + sorted(own))) == "eigen"))):
                    _name_fault = "rede_sprecher_name_unklar"
        # V92 Paket 12: an announcement naming several figures ("Mara sagt zu Johann:") cannot tell speaker from addressee by
        # its form - the server's blind speaker reading decides (mandatory there; missing/invalid -> unproven).
        # V92 Paket 13: so does an announcement naming nobody of the cast ("Peter sagt:", "und sagt leise:") - the literal
        # reading names the speaker ("Peter" -> another person, "figur"/"Johann" -> the figure).
        _rd = None
        if _need:
            _rd = (_claimed_party(_occA, _sp_lit, actor_id)
                   or component_party(_sp_lit, actor_id, figures, list(actor_names or []) + sorted(own))) if _r else "fehlt"
        if span is None:
            amb.append({"segment": seg[:160], "grund": "rede_nicht_im_eingang"})
        elif any(span[0] < b and a < span[1] for a, b in list(act_spans) + list(marked or [])):
            # V92 Paket 10: also the words the person marked as an act (*...*) are never speech
            # Stand 11B (Geraet 08.11. 21:58): liest das Modell DIESELBEN Worte einmal als handlung und einmal als rede, ist das keine
            # zweite Aussage der Person, sondern eine Doppelung der Lesung - die gelesene Handlung zaehlt, kein Hinweis an die Person.
            # Ueberschneidungen mit anderen Worten oder mit einem *Marker* bleiben sichtbar wie bisher.
            if not any(_scene.literal_in(raw[a:b].strip(" .,!?;:"), raw[span[0]:span[1]].strip(" .,!?;:"))
                       and _scene.literal_in(raw[span[0]:span[1]].strip(" .,!?;:"), raw[a:b].strip(" .,!?;:"))
                       for a, b in act_spans):
                amb.append({"segment": seg[:160], "grund": "rede_ueberlappt_handlung"})
            seen.append(span)
        elif _sp == "fremd" or (_ann_ids and str(actor_id or "") not in _ann_ids and not _ich) or _rd == "fremd":
            # another figure's speech is no speech of this speaker (§27.3/§27.4); its words and its announcement stay visible once.
            # V92 Paket 16: the reading's speaker is a full name nobody carries that holds a cast name - the operator is asked
            _k = identity_klaerung([o for o in _occA if o["state"] == "unbekannt" and o["words"] == _name_words(_sp_lit)], _ann,
                                   base=_cl[0] if _cl else 0) if _occA else None
            amb.append({"segment": seg[:160], "grund": "rede_akteur_ist_nicht_der_sprecher", "vorschlag": copy.deepcopy(comp),
                        **({"klaerung": _k} if _k else {})})
            seen.append(((intro[ci][0] if intro and ci in intro else span[0]), span[1])); _abgewiesen.append(seen[-1])
        elif _name_fault:
            _k = identity_klaerung(_unres, _ann, base=_cl[0] if _cl else 0)
            amb.append({"segment": seg[:160], "grund": "rede_sprecher_name_unklar", "vorschlag": copy.deepcopy(comp),
                        **({"klaerung": _k} if _k else {})})
            seen.append(((intro[ci][0] if intro and ci in intro else span[0]), span[1])); _abgewiesen.append(seen[-1])
        elif _sp in ("fehlt", "unklar") or (_ann_amb and str(actor_id or "") not in _ann_ids and not _ich) or _rd in ("fehlt", "unklar"):
            _k = identity_klaerung([o for o in _occA if o["state"] == "ok" and len(o["ids"]) > 1], _ann,
                                   base=_cl[0] if _cl else 0) if _ann_amb else None
            amb.append({"segment": seg[:160], "grund": "rede_sprecher_fehlt" if _sp == "fehlt" else "rede_sprecher_unklar",
                        "vorschlag": copy.deepcopy(comp), **({"klaerung": _k} if _k else {})})
            seen.append(((intro[ci][0] if intro and ci in intro else span[0]), span[1])); _abgewiesen.append(seen[-1])
        elif not any(span == r for r in rede):
            # P24: an independently verified address is SPOKEN, not an
            # announcement by somebody else. Keep the entire source span of
            # the vocative (also "Ja, Gustav,") in the canonical speech Fact.
            _spoken_span = ((intro[ci][0], span[1]) if _address_ids and intro and ci in intro else span)
            if _spoken_span not in rede:
                rede.append(_spoken_span)
            # V92 Paket 14 (Paket-13-Pruefung, Entscheidung 1; AMASTER §25 Zielbindung, §24.1, §24.7): the person the speech is
            # explicitly addressed to in its own sentence ("sagt zu Mara Schmidt:") outranks the selected recipient - only when the
            # reading's literal addressee stands there in full and binds exactly one present figure. An unknown, unclear or
            # ambiguous addressee - or an unknown person in the announcing clause that is not the speaker - is never bent onto
            # the selected recipient: the speech is then addressed to nobody (visible).
            if addressee is not None:
                if len(_address_ids) == 1:
                    _addr_id = next(iter(_address_ids))
                    if addressee.get("conflict") or (addressee.get("set") and addressee.get("id") != _addr_id):
                        # P25/R2: one Fact has one recipient. Never let the
                        # first recipient silently win a second proven address.
                        addressee.update({"set": True, "id": None, "conflict": True})
                        amb.append({"segment": _ann[:160], "grund": "rede_adressat_unklar"})
                    else:
                        addressee.update({"set": True, "id": _addr_id})
                if not _address_ids:
                    _sent = max([m.end() for m in re.finditer(r"[.!?\u2026]\s+", raw[:span[0]])] or [0])
                    _ra = max([_sent] + [e for _s, e in _others if e <= span[0]])
                    _w = _name_words(_ad_lit)
                    _adtext = raw[_ra:span[0]]
                    _adocc = name_occurrences(_adtext, figures, [_ad_lit] if _w else [], base=_ra)
                    _hit = next((o for o in _adocc if _w and (o["words"] == _w or o["words"].startswith(_w + " ") or f" {_w} " in f" {o['words']} ")), None)
                    _dec = None
                    if _hit is not None:
                        _dec = (next(iter(_hit["ids"])) if _hit["state"] == "ok" and len(_hit["ids"]) == 1
                                and next(iter(_hit["ids"])) != str(actor_id or "") else "")
                    elif _unres:
                        _dec = ""
                    if _dec is not None:
                        if addressee.get("conflict") or (addressee.get("set") and addressee.get("id") != (_dec or None)):
                            addressee["conflict"] = True
                            _dec = ""
                        addressee.update({"set": True, "id": _dec or None})
                        if not _dec:
                            # V92 Paket 16: the clarification offers the present figures whose names stand in the addressee's name
                            _k = identity_klaerung([_hit] if _hit is not None else unresolved_names(_adocc), _adtext,
                                                   exclude=[str(actor_id or "")], base=_ra)
                            amb.append({"segment": (_ad_lit or seg)[:160], "grund": "rede_adressat_unklar", **({"klaerung": _k} if _k else {})})
            if intro and ci in intro and not _address_ids:
                intro_cover.append((intro[ci][0], span[1]))
                # V92 Paket 13: an own act the blind speaker reading names inside the announcement that no act component covers
                # (e.g. the reading reached into the speech verb: no server component) is never silently part of the announcement
                _h = str(((comp.get("sprecherPruefung") or {}) if isinstance(comp.get("sprecherPruefung"), dict) else {}).get("handlung") or "").strip(" ,.;:")
                _hm = re.search(re.escape(_h), raw[intro[ci][0]:intro[ci][1]]) if _h else None
                if _hm and not any(a <= intro[ci][0] + _hm.start() and intro[ci][0] + _hm.end() <= b for a, b in act_spans):
                    amb.append({"segment": _h[:160], "grund": "rest_ohne_komponente"})
    _alone = [r for r in rede if not any(ic[1] == r[1] and ic[0] <= r[0] for ic in intro_cover)]
    # P25/R1: full source-bound subject prefixes are structurally covered.
    # They are NOT appended to the stored action text or called speech.
    covered = sorted(set(list(act_spans) + _alone + intro_cover + seen + list(own_act_subject_spans or [])))
    pos, cursor = [], 0
    gaps: list[tuple[int, int, bool]] = []   # (a, b, stands between two components)
    for a, b in covered:
        if a > cursor:
            gaps.append((cursor, a, cursor > 0))
        cursor = max(cursor, b)
    if cursor < len(raw):
        gaps.append((cursor, len(raw), False))
    for a, b, between in gaps:
        text = raw[a:b]
        if between and re.fullmatch(r"\s*\w+\s*", text):
            continue   # the connection of two components, as in segment_binding_fault
        rest = _residual_text(text.replace("*", " "), [])   # the marker stars are no words of the rest
        if rest:
            # Stand 11B (Geraet 08.11. 21:58; AMASTER §24.7, §27.4; P24/P25-R1): ein ungelesener Rest wird NIE Rede (Paket-8-Pruefung
            # C6). Er kippt aber nur dann die ganze Eingabe (input_binding_outcome), wenn er ungekennzeichnet eine Person nennt - dann
            # koennte er eine Rede an jemand anderen sein (P24 "Gustav, setz dich.", R1 "Robert steht auf."). Sonst wird gespeichert,
            # was gelesen und gueltig ist, und der Rest bleibt sichtbar.
            _im_marker = any(a < mb and ma < b for ma, mb in (marked or []))
            _nennt = bool(name_occurrences(text, figures or [])) if figures else True
            _an_abgewiesen = any(sp[1] == a or sp[0] == b for sp in _abgewiesen)   # Wortrest einer abgewiesenen Komponente
            if not _im_marker and not _nennt and not cut and not _an_abgewiesen:
                # Stand 11C (AMASTER §27.4 "Die Puppet-Eingabe ist die tatsaechliche Rede oder Handlung dieser Figur", §34.1
                # "eine nicht validierte Komponente darf als sichtbare ... Redeprovenienz erhalten bleiben" - ohne Koerper-/Weltwirkung;
                # Nutzerentscheidung 08.11. 22:22, hebt Paket-8-Pruefung C6 fuer diesen Fall auf): ungekennzeichneter Text, den keine
                # geprufte Handlung deckt und der keine andere Person nennt, ist die eigene Rede der Figur - nichts geht verloren.
                _w = re.search(r"\w[\s\S]*\w[.!?\u2026]*|\w[.!?\u2026]*", text)   # Satzzeichen am Ende gehoeren zur Rede
                if _w:
                    rede.append((a + _w.start(), a + _w.end()))
                    amb.append({"segment": rest[:160], "grund": "rest_als_rede", "provenienz": True})
                continue
            amb.append({"segment": rest[:160], "grund": "rest_ohne_komponente",
                        **({"inMarkierung": True} if _im_marker else {}), **({"nenntPerson": True} if _nennt else {})})
    speech = " ".join(raw[a:b].strip() for a, b in sorted(rede) if raw[a:b].strip()) or None
    return speech, amb


def _named_by_name_part(text: str, figures: list[dict]) -> set[str]:
    """V65P: the figures a text names by ANY whole part of their cast name (>= 3
    letters), alias or session name - from the cast data, no word list. The
    address reader _name_roles knows only the full name and its first part;
    "Mara gibt Alrik einen Kuss" did not name "Priester Alrik" there (V65P
    Regie-Messung, falsch negativ).
    V92 Paket 13 (Paket-12-Pruefung, Bedingung B/C): by the one identity reading name_occurrences - a name word inside an
    unknown full name ("Mara Schmidt" with only Mara Nowak in the cast) names nobody, a full form names only its figure.
    A name that fits several figures still returns all of them (the callers decide on exactly one)."""
    out: set[str] = set()
    for o in name_occurrences(text, figures):
        if o["state"] == "ok":
            out |= o["ids"]
    return out


def _regie_possessive_name_ids(text: str, figures: list[dict]) -> set[str]:
    """V74/AMASTER §24.1, §25, §46.2: German possessive references from
    cast names, not lexical similarity: 'Maras Buch' identifies Mara.
    Accept only unique names/aliases, and never override a different exact
    cast name (e.g. a separate figure literally named 'Maras').
    """
    low = str(text or "").casefold()
    forms: dict[str, set[str]] = {}
    for c in figures or []:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        parts = [v for v in str(c.get("name") or "").split() if len(v) >= 3]
        parts += [str(a).strip() for a in (c.get("aliases") or []) + (c.get("sessionAliases") or []) if len(str(a).strip()) >= 3]
        for form in parts:
            forms.setdefault(form.casefold(), set()).add(cid)
    exact = _named_by_name_part(text, figures)
    out: set[str] = set()
    for form, ids in forms.items():
        if len(ids) != 1:
            continue
        cid = next(iter(ids))
        if cid in exact:
            continue
        # A name's inflected spelling must not collide with someone else's
        # direct name. Only the exact genitive suffix is allowed.
        for spelling in (form + 's', form + "'s", form + "s'"):
            if re.search(rf"(?<!\w){re.escape(spelling)}(?!\w)", low):
                if not any(spelling == other and cid not in other_ids for other, other_ids in forms.items()):
                    out.add(cid)
                break
    return out


def regie_order_line(segment: str, to: str | None) -> str:
    """V65S (AMASTER §27.5 Z. 1413 "Regie ist keine Figurenrede", §46.2 "Actor und Target werden ausdruecklich
    gebunden"): the ordered speech as the Regie's words TO the directed figure - its "du" is she herself - and the
    bound addressee. Before (V65P): "Sprich zu Alrik ..., wie angeordnet: „Sage alrik was du mit mara gemacht hast“"
    read as the line to say; Johann asked Alrik "Was hast du mit Mara gemacht?" in 3/3 (V65R 6/6) route runs; with this
    line he speaks as himself 6/6 (replay of the same stored requests, 30.10.)."""
    seg = str(segment or "").strip()
    head = f"Die Regie sagt zu DIR: „{seg}“ (das „du“ darin bist du selbst)"
    return f"{head} — sprich jetzt zu {to}, in deinen eigenen Worten" if to else f"{head} — sprich jetzt, in deinen eigenen Worten"


def regie_order_for(session: dict, directive: str, speaker_id: str) -> dict | None:
    """V65Q: the ordered speech of THIS figure in the Regie row the directive stems from
    (the same match as the prepare: last Regie row with this text and bound effects).
    Returns {regieFactId, regieTurn, targetId, segment, redeverb} or None (several orders
    for her or none -> None, nothing is guessed)."""
    raw = str(directive or "").strip()
    if not raw:
        return None
    for row in reversed(session.get("turns") or []):
        if not isinstance(row, dict) or row.get("role") != "regie":
            continue
        eff = row.get("regieEffects") if isinstance(row.get("regieEffects"), dict) else None
        if not eff or str(row.get("directiveText") or row.get("speech") or "").strip()[:300] != raw[:300]:
            continue
        own = [x for x in (eff.get("speech") or []) if isinstance(x, dict) and str(x.get("actorId") or "") == str(speaker_id)]
        if len(own) != 1:
            return None
        src = next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict)
                    and f.get("kind") == "regie" and f.get("turn") == row.get("turn")), None)
        return {"regieFactId": (src or {}).get("id"), "regieTurn": row.get("turn"), "targetId": own[0].get("targetId"),
                "segment": own[0].get("segment"), "redeverb": own[0].get("redeverb")}
    return None


def _norm_words(s: str) -> str:
    """Words only (casefold, punctuation removed) - for comparing two spans of the same text."""
    return " ".join(re.sub(r"[^\w]+", " ", str(s or "").casefold()).split())


def _named_in(part: str, figures: list[dict], exclude: set[str]) -> set[str]:
    """Figures a text part names (the existing name readers, incl. session names and name parts)."""
    if not str(part or "").strip():
        return set()
    return (set(_name_roles(part, figures, actor_id=None)) | _named_by_name_part(part, figures)
            | _regie_possessive_name_ids(part, figures)) - set(exclude)


def _words_in(text: str, words: str) -> bool:
    """V65R: the given word(s) occur in the text as consecutive words. A word counts as the same when one is an
    inflected form of the other (one starts with the other, both at least four letters: "erzähl"/"erzähle") -
    generic word form, no list of words."""
    tw = re.findall(r"[\w]+", str(text or "").casefold())
    ww = re.findall(r"[\w]+", str(words or "").casefold())
    if not ww or len(ww) > len(tw):
        return False

    def _same(a: str, b: str) -> bool:
        return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))
    return any(all(_same(a, b) for a, b in zip(tw[i:i + len(ww)], ww)) for i in range(len(tw) - len(ww) + 1))


def _regie_speech_binding(text: str, span: tuple[int, int], comp: dict, actor_id: str, target_id: str | None,
                          present: list[dict], ui_t: str | None, present_ids: set[str],
                          after_own_act: bool = False) -> tuple[str | None, str | None]:
    """V65R (AMASTER §27.5 Z. 1409-1415 "Regie ist keine Figurenrede ... keine nicht angeordnete
    Figurenentscheidung", §46.2 Z. 2547 "Actor und Target werden ausdruecklich gebunden", §46.6 Z. 2596,
    §25 Z. 1309-1320 Zielbindung: Namensnennung, UI-Auswahl, Szene; Pruefung v2.9 Q-A). Replaces the V65Q
    rule "auftrag must differ from the segment", which rejected your orders "Sage was du mit mara gemacht
    hast" (T27-T29: the reading gave the whole line as auftrag, as it did for "Ist die Tuer offen?").
    Structural checks of a proposed speech component, no word list:
    1) ORDERED: the short form "<Name der Figur>: <Zeile>", or the reading's `redeverb` (the word that
       orders the figure to say/ask/tell) occurs LITERALLY in the instruction (inflection tolerated), or the
       speech continues an ordered act of the same figure. A line written as it is ("Ist die Tuer offen?")
       has no such word in it and orders nobody (measured 29.-30.10.: 65/66 readings).
    2) ADDRESSEE, explicitly bound (§46.2), in this order: the reading's `adressat` when that person is
       NAMED in the instruction; else the chosen "Direktes Ziel" (not the actor); else the reading's `ziel`
       when that person is named OUTSIDE the speech segment (e.g. in the ordered act before it: "klare
       kippt Mara einen Stoss und sagt ..."); else the only other present figure (your T27-T29: Johann and
       Alrik). If the reading proposes an addressee that none of these binds (a pronoun it resolved itself,
       or a person only mentioned in what is to be said) -> unclear `ziel_nicht_belegt`. If it proposes
       none, the order is executed without a bound addressee.
    Returns (unclear reason or None, bound target or None)."""
    actor_id = str(actor_id)
    ordered = False
    head = text[:span[0]].rstrip()
    if head.endswith(":"):
        lead = re.split(r"[.!?;\n]", head[:-1])[-1].strip()
        if lead and actor_id in _named_in(lead, present, set()):
            ordered = True
    verb = str(comp.get("redeverb") or "").strip()
    if not ordered and verb and _words_in(text, verb):
        ordered = True
    if not ordered and after_own_act:
        ordered = True
    if not ordered:
        return "rede_nicht_angeordnet", None
    named = _named_in(text, present, {actor_id})
    others = [c for c in present_ids if c != actor_id]
    adr = str(comp.get("adressat") or "").strip()
    adr_fig = _match_figure(adr, present) if adr else None
    adr_id = str(adr_fig.get("id")) if adr_fig else None
    if adr_id and adr_id != actor_id and adr_id in present_ids and adr_id in named:
        return None, adr_id
    if ui_t and ui_t != actor_id and ui_t in present_ids:
        return None, ui_t
    if target_id and target_id != actor_id and target_id in present_ids and \
            target_id in _named_in(text[:span[0]] + " " + text[span[1]:], present, {actor_id}):
        return None, target_id
    if len(others) == 1:
        return None, others[0]
    if (adr_id and adr_id != actor_id) or (target_id and target_id != actor_id):
        return "ziel_nicht_belegt", None
    return None, None


_GENUS = {"m": "männlich", "f": "weiblich"}


def bind_pronoun_referent(session: dict, text: str, verweis: Any, *, speaker_id: Any, addressee_id: Any,
                          figures: list[dict] | None) -> dict:
    """V65T (AMASTER §24.1 Entity-/Alias-Resolver, §24.7 "Ambiguitaet bleibt sichtbar ungebunden", §25 Gespraechsbezug,
    §41.1; Plan v2 Schritt 2a; Gegenpruefung v3.2 Befund 2/3): WHOM a pronoun of this utterance means - conversational
    reference, not knowledge. The input reading only gives the signal (a pronoun for a third person, with genus; no name).
    The kernel builds the candidates itself from the lines the speaker heard in the running scene (_dialogue_visible_to,
    last 10 turns): the cast figures named in them (_named_by_name_part) and their speakers/actors/targets - without
    the speaker, the addressee and the operator - and filters by the cast's gender. Bound only for a masculine signal
    (er/ihn/ihm have no second grammatical reading; feminine and neuter forms do) with EXACTLY one male candidate and
    no candidate of unknown gender; otherwise unbound with the reason. Returns
    {pronomen, genus, kandidaten, gebunden, belegTurns, grund}. Read only; no model."""
    out: dict[str, Any] = {"pronomen": "", "genus": None, "kandidaten": [], "gebunden": None, "belegTurns": [], "grund": "kein_signal"}
    if not isinstance(verweis, dict):
        return out
    pron = str(verweis.get("pronomen") or "").strip()
    genus = str(verweis.get("genus") or "").strip().lower()[:1]
    out.update({"pronomen": pron[:20], "genus": genus or None})
    if not pron or not re.search(rf"(?<!\w){re.escape(pron.casefold())}(?!\w)", str(text or "").casefold()):
        out["grund"] = "pronomen_nicht_woertlich"
        return out
    if genus != "m":
        # §24.7: the feminine/neuter third-person forms coincide with the plural, the polite address (Sie/Ihnen) and
        # things (es) - measured 30.10.: "Haben Sie Angst?" and "haben sie angst?" came back as sie/f; such a signal
        # binds nobody (false negatives are reported, never guessed).
        out["grund"] = "genus_nicht_bindbar" if genus in ("f", "n") else "genus_ungeklaert"
        return out
    me, to = str(speaker_id or ""), str(addressee_id or "")
    cast = _session_cast(session, list(figures or []))
    gender = {str(c.get("id") or ""): str(c.get("gender") or "").strip().casefold() for c in cast if isinstance(c, dict)}
    excluded = {me, to, "", "regie", *_OPERATOR_IDS}
    seen: dict[str, list[int]] = {}
    facts = [f for f in session.get("facts") or [] if isinstance(f, dict)]
    for row in _dialogue_visible_to(session, me, list(session.get("turns") or [])):
        turn = row.get("turn")
        ids = _named_by_name_part(" ".join(str(row.get(k) or "") for k in ("speech", "action")), cast)
        for f in facts:
            if f.get("turn") == turn and f.get("kind") in ("speech", "action") and _scene.validiert(f):
                ids |= {str(f.get("actorId") or ""), str(f.get("targetId") or "")}
        for cid in ids - excluded:
            seen.setdefault(cid, []).append(int(turn or 0))
    out["kandidaten"] = sorted(seen)
    unknown = [cid for cid in seen if gender.get(cid) not in _GENUS.values()]
    match = [cid for cid in seen if gender.get(cid) == _GENUS[genus]]
    if unknown:
        out["grund"] = "geschlecht_unbekannt"
    elif len(match) == 1:
        out.update({"gebunden": match[0], "belegTurns": sorted(set(seen[match[0]])), "grund": "eindeutig"})
    else:
        out["grund"] = "kein_kandidat" if not match else "mehrdeutig"
    return out


def bind_referents(text: str, figures: list[dict] | None) -> list[str]:
    """V65S (AMASTER §24.1 Entity-/Alias-Resolver, §24.7 keine geratene Bindung, §25; Pruefung v3.1 §6 "Referentenbindung
    vor Recall ... kein Erraten aus dem maennlichen Pronomen und keine Woerterliste"): the cast figures an input NAMES -
    by a whole part of the cast name, an alias or a session name (_named_by_name_part, cast data only). A pronoun binds
    nothing (left unclear). Measured 30.10.: the input reading (gpt-4o-mini) resolved a pronoun from given lines in
    one wording and lost other bindings, in the other wording missed the pronoun - not reliable, so no model here."""
    # V92 Paket 13 (Paket-12-Pruefung, Bedingung C Memory; Avatar-Browserlauf 05.11.: "Ich reiche Mara ein Glas Wasser." bound
    # Mara Nowak AND the absent Mara Schmidt as `about_ids` of the memory): by the one identity reading - only names that fit
    # exactly one figure bind; a name several figures carry, or an unknown full name, binds nobody (§24.7)
    return sorted(figures_named_in_text(str(text or ""), list(figures or []))[0])[:4]


_REGIE_KEY_MAX = None   # V65X (E06): the keys are carried whole (V65W: 200)


def bind_regie_components(
    text: str,
    parsed: Any,
    *,
    directed_id: str | None,
    figures: list[dict] | None,
    present_ids: list[str],
    ui_target_id: str | None = None,
    avatar_id: str | None = None,
) -> dict[str, Any]:
    """Validate a Regie reading (AMASTER §27.5, §46.2, §46.6): actor and
    target are bound explicitly; only ordered effects; unclear stays unclear.

    V65P (AMASTER §46.2 "Actor und Target werden ausdrücklich gebunden", §23/§25
    UI-Bindung, §24.7, §27.3; V65M Naht 1, measured on your session T16/T22/T24/
    T26 and ses_3422): the reading is a proposal (§24.2); the kernel now checks
    WHO is bound, with the existing name reader `_name_roles` (incl. session
    names), no word list:
    - actor: named in the instruction, or the directed figure;
    - target: named in the instruction, or the chosen "Direktes Ziel" (when it
      is not the actor). Not named but such a UI target chosen -> the UI target
      (explicit binding by the operator). Otherwise unclear `ziel_nicht_belegt`;
    - speech of the user's avatar is never ordered (§27.3: the system does not
      formulate avatar speech) -> unclear `avatar_rede_nicht_anordenbar`;
    - a body class (gewalt/fesseln/befreien) without a target person is not
      applied (class unclear); the act itself is executed;
    - ordered speech keeps the LITERAL segment of the instruction for the brief."""
    out: dict[str, Any] = {"actions": [], "speech": [], "unclear": []}
    if not isinstance(parsed, dict):
        return out
    present = [f for f in (figures or []) if isinstance(f, dict) and str(f.get("id") or "") in set(present_ids)]
    named = (set(_name_roles(text, present, actor_id=None)) | _named_by_name_part(text, present)
             | _regie_possessive_name_ids(text, present))
    ui_t = str(ui_target_id or "") or None
    # V65Q: where the ordered acts of the reading end, and whose they are (for speech that
    # continues an ordered act of the same figure, see _regie_speech_binding).
    act_ends: list[tuple[int, str]] = []
    for _c in (parsed.get("komponenten") or []):   # V65Z (A04)
        if isinstance(_c, dict) and str(_c.get("typ") or "").strip().lower() == "handlung":
            _sp = _locate_segment(text, str(_c.get("segment") or ""))
            _ak = str(_c.get("akteur") or "").strip()
            _a = _match_figure(_ak, present) if _ak else None
            _aid = str(_a.get("id")) if _a else (str(directed_id) if directed_id and not _ak else "")
            if _sp is not None and _aid:
                act_ends.append((_sp[1], _aid))
    if parsed.get("_abgeschnitten"):
        out["unclear"].append({"grund": "lesung_abgeschnitten", "text": str(text or "")[:160]})   # V65Z (A04): visibly
    for item in (parsed.get("unklar") or []):   # V65Z (A04)
        if str(item or "").strip():
            out["unclear"].append({"grund": "vom_planer_unklar", "text": str(item)[:160]})
    _regie_spans = [sp for sp in (_locate_segment(text, str(c.get("segment") or "")) for c in (parsed.get("komponenten") or [])
                                  if isinstance(c, dict)) if sp]
    for comp in (parsed.get("komponenten") or []):   # V65Z (A04): every ordered component
        if not isinstance(comp, dict):
            continue
        typ = str(comp.get("typ") or "").strip().lower()
        if typ not in ("handlung", "rede"):
            continue
        span = _locate_segment(text, str(comp.get("segment") or ""))
        if span is None:
            out["unclear"].append({"grund": "segment_nicht_in_anweisung", "vorschlag": copy.deepcopy(comp)})
            continue
        if typ == "handlung":
            # V65Z (A05): an ordered act is checked on the instruction's own text like an input act (quotation, clause)
            _fault = segment_binding_fault(text, span, [sp for sp in _regie_spans if sp != span])
            if _fault:
                out["unclear"].append({"grund": _fault, "vorschlag": copy.deepcopy(comp)})
                continue
        akteur = str(comp.get("akteur") or "").strip()
        actor = _match_figure(akteur, present) if akteur else None
        actor_id = str(actor.get("id")) if actor else (str(directed_id) if directed_id and not akteur else "")
        if not actor_id or actor_id not in set(present_ids):
            out["unclear"].append({"grund": "akteur_nicht_anwesend_oder_unbekannt", "vorschlag": copy.deepcopy(comp)})
            continue
        if actor_id not in named and actor_id != str(directed_id or ""):
            out["unclear"].append({"grund": "akteur_nicht_belegt", "vorschlag": copy.deepcopy(comp)})
            continue
        if typ == "rede" and avatar_id and actor_id == str(avatar_id):
            out["unclear"].append({"grund": "avatar_rede_nicht_anordenbar", "vorschlag": copy.deepcopy(comp)})
            continue
        ziel = str(comp.get("ziel") or "").strip()
        target = _match_figure(ziel, present) if ziel else None
        target_id = str(target.get("id")) if target else None
        if ziel and target is None:
            out["unclear"].append({"grund": "ziel_nicht_anwesend_oder_unbekannt", "vorschlag": copy.deepcopy(comp)})
            continue
        if typ == "rede":
            # V65Q (AMASTER §27.5 Z. 1415, §46.2 Z. 2547, §46.6 Z. 2596, §25 Z. 1309-1316,
            # §24.7; Pruefung v2.8 P-07/P-08): speech is executed only when the
            # instruction ORDERS it, and it is addressed to the person the order
            # names - not to someone only mentioned in what is to be said.
            _after = any(a_end <= span[0] and a_actor == actor_id for a_end, a_actor in act_ends)
            why, target_id = _regie_speech_binding(text, span, comp, actor_id, target_id, present, ui_t, set(present_ids),
                                                   after_own_act=_after)
            if why:
                out["unclear"].append({"grund": why, "vorschlag": copy.deepcopy(comp)})
                continue
        elif target_id and target_id not in named and target_id != ui_t:
            if ui_t and ui_t != actor_id and ui_t in set(present_ids):
                target_id = ui_t
            else:
                out["unclear"].append({"grund": "ziel_nicht_belegt", "vorschlag": copy.deepcopy(comp)})
                continue
        if typ == "handlung":
            desc = str(comp.get("beschreibung") or "").strip()
            if not desc:
                out["unclear"].append({"grund": "handlung_ohne_beschreibung", "vorschlag": copy.deepcopy(comp)})
                continue
            if not target_id:
                # V65R (AMASTER §46.2 "Actor und Target werden ausdruecklich gebunden"; measured 30.10.:
                # with the speech fields the reading left `ziel` empty for "klare kippt Mara einen Stoss
                # und sagt ...", 2/2): the act's OWN wording names exactly one other present figure ->
                # that figure is the target (explicit naming in the ordered act, no guess).
                _in_act = _named_in(text[span[0]:span[1]], present, {actor_id}) & set(present_ids)
                if len(_in_act) == 1:
                    target_id = next(iter(_in_act))
            valid_effect, effect = effect_kind_from_wirkung(comp.get("wirkung"))
            if not valid_effect:
                out["unclear"].append({"grund": "wirkung_unklar", "wert": str(comp.get("wirkung"))[:40]})
            elif effect in BODY_EFFECTS_NEED_TARGET and not target_id:
                out["unclear"].append({"grund": "koerperwirkung_ohne_zielperson", "wert": str(comp.get("wirkung"))[:40]})
                valid_effect, effect = False, None
            act_row = {"actorId": actor_id, "targetId": target_id, "text": desc[:240],
                       "effectKind": effect, "effectValid": valid_effect}
            if isinstance(comp.get("wirkungPruefung"), dict):
                # V65Q: the check's audit (attempt / surface) reaches the Regie writer.
                act_row["pruefung"] = copy.deepcopy(comp["wirkungPruefung"])
            if isinstance(comp.get("grenzBezug"), list):
                act_row["grenzBezug"] = copy.deepcopy(comp["grenzBezug"])   # V65W (C1)
            # V92 Paket 19 (Pruefung P18, Regie-Koerperkette): the ordered act's LITERAL words in the instruction and the server's
            # body reading of them (reading + confirmation, app.kernel_regie) - the Regie writer validates against these words
            act_row["segment"] = text[span[0]:span[1]].strip()[:300]
            if isinstance(comp.get("koerperPruefung"), dict):
                act_row["koerperPruefung"] = copy.deepcopy(comp["koerperPruefung"])
            out["actions"].append(act_row)
        else:
            inhalt = str(comp.get("inhalt") or "").strip()
            if not inhalt:
                out["unclear"].append({"grund": "rede_ohne_inhalt", "vorschlag": copy.deepcopy(comp)})
                continue
            _tat = comp.get("taten") if isinstance(comp.get("taten"), dict) else None
            out["speech"].append({"actorId": actor_id, "targetId": target_id, "inhalt": inhalt[:240],
                                  "segment": text[span[0]:span[1]].strip()[:300],
                                  "redeverb": str(comp.get("redeverb") or "").strip()[:80] or None,
                                  # V65U (Codegutachten v1 N5): the reading's picked act labels [T#] and their Fact IDs (mapped
                                  # by the app from regie_act_candidates); validated in execute_regie_information
                                  **({"taten": {"von": str(_tat.get("von") or "").strip()[:80], "an": str(_tat.get("an") or "").strip()[:80],
                                                "vonId": _tat.get("vonId"), "anId": _tat.get("anId"),
                                                "ereignisse": [str(x).strip().strip("[]")[:8] for x in (_tat.get("ereignisse") or [])
                                                               if str(x).strip()][:12],
                                                "factIds": [str(x) for x in (_tat.get("factIds") or []) if str(x)][:12],
                                                "unbekannt": [str(x)[:8] for x in (_tat.get("unbekannt") or []) if str(x)][:12],
                                                **({"auswahl": copy.deepcopy(_tat["auswahl"])} if isinstance(_tat.get("auswahl"), dict) else {}),
                                                # V65W (C2/C3): label key over ALL pages + what it saw, content key - no 40 cut
                                                **({"kennungen": [str(x) for x in _tat["kennungen"]]} if isinstance(_tat.get("kennungen"), list) else {}),
                                                **({"kennungenGeprueft": [str(x) for x in _tat["kennungenGeprueft"]]}
                                                   if isinstance(_tat.get("kennungenGeprueft"), list) else {}),
                                                **({"inhalt": {"beleg": str((_tat["inhalt"] or {}).get("beleg") or "")[:160],
                                                               "factIds": [str(x) for x in (_tat["inhalt"].get("factIds") or [])],
                                                               "geprueft": [str(x) for x in (_tat["inhalt"].get("geprueft") or [])]}}
                                                   if isinstance(_tat.get("inhalt"), dict) else {})}}
                                     if _tat and str(_tat.get("von") or "").strip() else {})})
    return out


# V65c: _destination_from_text (free-text regex "zur/nach/in X") removed; its only reader,
# the move writer, binds the destination to a known world place (_known_destination).


def _known_destination(text: str, world: dict | None) -> str:
    """V65c (AMASTER §24.7 "Intelligente Verarbeitung darf nicht zu geratenen
    Weltfakten führen", §43.2 SpatialState, §10/§11 Orte und Unterorte): the
    destination of a validated move is bound to a place the world KNOWS (its
    places and subplaces, by name, leading article ignored). The last named
    known place in the act wins ("aus der Küche in den Schankraum"). No known
    place named: "" — no position is guessed from free text."""
    raw = str(text or "").casefold()
    if not raw or not isinstance(world, dict):
        return ""
    best, best_at = "", -1
    for p in list(world.get("places") or []) + list(world.get("subplaces") or []):
        name = str((p.get("name") if isinstance(p, dict) else p) or "").strip()
        if not name:
            continue
        forms = {name.casefold(), re.sub(r"^(der|die|das|den|dem|des)\s+", "", name.casefold())}
        for f in forms:
            if len(f) < 3:
                continue
            at = raw.rfind(f)
            if at > best_at:
                best, best_at = name, at
    return best


def _apply_physical(
    session: dict,
    *,
    actor_id: str | None = None,
    target_id: str | None = None,
    text: str,
    validated: bool,
    source_turn_id: str | None = None,
    authority: str = "character",
    truth: dict | None = None,
    turn: int | None = None,
    new_facts_out: list | None = None,
    effect_kind: Any = _LEXICAL,
    fact_id: str | None = None,
    world: dict | None = None,
) -> None:
    """Apply physical/relationship effect. B.3: jede Wirkung erzeugt einen
    SceneFact mit event_kind, sodass Audit-Trail und Timeline rekonstruierbar sind.

    B.4: Social-/Move-Operationen schreiben zusätzlich einen
    relationship_drift-Fact, sodass Relationship-Mutationen nicht unsichtbar bleiben.

    V59C: migrated callers pass the VALIDATED semantic class (effect_kind,
    None = no physical effect). Only unmigrated callers (God, Puppet) still
    fall back to the legacy lexical reading.
    """
    if not validated or not text:
        return
    kind = classify_physical_effect(text) if effect_kind is _LEXICAL else effect_kind
    if not kind:
        return
    # V59C (AMASTER §27.3, §68 Nr. 90): the system never writes the user
    # avatar's emotion, intent or relationship declaration. Objectively
    # suffered outer effects (pain, mobility, restraint) remain allowed.
    avatar_id = str(session.get("avatarId") or "")
    _AVATAR_INNER = ("fear", "anger", "stress", "intensity", "emotion", "activeCause", "shame", "trust", "lust")

    def _protect_avatar(cid: str | None, before_rt: dict) -> None:
        if not avatar_id or str(cid or "") != avatar_id:
            return
        rt_now = runtimes.get(cid)
        if not isinstance(rt_now, dict):
            return
        for key in _AVATAR_INNER:
            if key in before_rt:
                rt_now[key] = before_rt[key]
            else:
                rt_now.pop(key, None)
    runtimes = session.setdefault("runtimes", {})
    scene = session.get("scene") or {}
    # V36 (AMASTERv2 §22/§43): Körperliche Wirkung trifft nur, wer in der Szene ist.
    present_ids = list(scene.get("presentIds") or [])
    if target_id and present_ids and str(target_id) not in present_ids and str(target_id) != str(actor_id or ""):
        target_id = None
    # V65S (AMASTER §35, §36.5, §40; Plan S1): the body act is evidence of the Proposition
    # "Koerperkontakt actor -> target"; its own new Fact carries the consent state at the moment of the act.
    if fact_id and target_id and kind in _CONSENT_ACTS:
        _body_contact_matter(session, next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict)
                                            and f.get("id") == fact_id), None), actor_id, target_id, kind)

    def _rt(cid: str | None) -> dict | None:
        if not cid:
            return None
        cur = runtimes.get(cid)
        if not isinstance(cur, dict):
            cur = {"characterId": cid, "pain": 0.0, "mobility": 1.0, "consciousness": 1.0, "restrained": False, "gagged": False, "canSpeak": True}
            runtimes[cid] = cur
        return cur

    def _emit_runtime_fact(target_cid: str, before: dict) -> None:
        """B.3: jeder physische Effekt schreibt einen event_kind:physical Fact.
        before = RuntimeState vor Mutation; Payload enthält die Deltas."""
        if new_facts_out is None:
            return
        after = runtimes.get(target_cid) or {}
        delta = {}
        for k in ("pain", "mobility", "consciousness", "fear", "anger", "stress", "intensity", "emotion", "restrained", "gagged", "canSpeak", "position"):
            b = before.get(k)
            a = after.get(k)
            if b != a:
                delta[k] = {"from": b, "to": a}
        if not delta:
            return
        fact = make_fact(
            turn=turn or 0,
            actorId=actor_id or "",
            targetId=target_cid,
            kind="physical",
            event_kind="physical",
            text=text,
            authority=authority,
            sourceTurnId=source_turn_id or (truth or {}).get("id"),
            truth=truth or {},
            scene=scene,
            payload={"verb": kind, "delta": delta, "text": text, "kind": "physical"},
            validated=validated,
        )
        session.setdefault("facts", []).append(fact)
        new_facts_out.append(fact)

    def _emit_rel_fact(from_cid: str, to_cid: str, before_hit: dict, after_hit: dict) -> None:
        """B.4: Relationship-Drift wird eigener Fact (event_kind:relationship_drift)."""
        if new_facts_out is None:
            return
        delta = {}
        for k in ("trust", "closeness", "fear", "hostility", "note", "kind"):
            b = before_hit.get(k)
            a = after_hit.get(k)
            if b != a:
                delta[k] = {"from": b, "to": a}
        if not delta:
            return
        fact = make_fact(
            turn=turn or 0,
            actorId=from_cid,
            targetId=to_cid,
            kind="relation",
            event_kind="relationship_drift",
            text=text,
            authority=authority,
            sourceTurnId=source_turn_id or (truth or {}).get("id"),
            truth=truth or {},
            scene=scene,
            payload={"verb": kind, "delta": delta, "text": text, "kind": "relationship_drift"},
            validated=validated,
        )
        session.setdefault("facts", []).append(fact)
        new_facts_out.append(fact)

    if kind == "strike":
        rt = _rt(target_id)
        if not rt:
            return
        before = dict(rt)
        rt["pain"] = min(1.0, float(rt.get("pain") or 0) + 0.2)
        rt["mobility"] = max(0.0, float(rt.get("mobility") or 1) - 0.15)
        rt["fear"] = min(1.0, float(rt.get("fear") or 0) + 0.25)
        rt["anger"] = min(1.0, float(rt.get("anger") or 0) + 0.15)
        rt["stress"] = min(1.0, float(rt.get("stress") or 0) + 0.2)
        rt["intensity"] = min(1.0, float(rt.get("intensity") or 0.35) + 0.2)
        rt["emotion"] = "Schmerz" if float(rt["pain"]) >= 0.4 else "Angst"
        rt["activeCause"] = str(fact_id) if fact_id else (text or "")[:160]
        if fact_id:
            rt["physicalCauses"] = ([str(x) for x in (rt.get("physicalCauses") or [])] + [str(fact_id)])[-12:]
        _protect_avatar(target_id, before)
        _emit_runtime_fact(target_id, before)
        # V65P (AMASTER §43.1 Reichweite, §43.2 SpatialState; IST-Probe 1/2): a
        # validated blow or push reaches the target's body - the two are in
        # touch. Before, a strike set no spatial relation and the brief went on
        # saying "ihr seid auf Abstand" after "Ich drück dich zur mauer".
        if actor_id and str(actor_id) != str(target_id):
            _scene.set_spatial(session, str(actor_id), str(target_id), "beruehrung",
                               turn=int(turn or 0), fact_id=fact_id, text=text)
            _pin_against(session, str(actor_id), str(target_id), fact_id=fact_id, turn=turn, text=text)
    elif kind == "restrain":
        rt = _rt(target_id)
        if not rt:
            return
        before = dict(rt)
        rt["restrained"] = True
        rt["mobility"] = min(float(rt.get("mobility") or 1), 0.2)
        rt["fear"] = min(1.0, float(rt.get("fear") or 0) + 0.3)
        rt["stress"] = min(1.0, float(rt.get("stress") or 0) + 0.2)
        rt["emotion"] = "Angst"
        rt["activeCause"] = str(fact_id) if fact_id else (text or "")[:160]
        if fact_id:
            rt["physicalCauses"] = ([str(x) for x in (rt.get("physicalCauses") or [])] + [str(fact_id)])[-12:]
        if "knebel" in (text or "").lower():
            rt["gagged"] = True
            rt["canSpeak"] = False
        _protect_avatar(target_id, before)
        _emit_runtime_fact(target_id, before)
        # V65P (§43.1, §43.2; IST-Probe 3): holding or binding someone needs
        # reach - in touch, like a strike.
        if actor_id and str(actor_id) != str(target_id):
            _scene.set_spatial(session, str(actor_id), str(target_id), "beruehrung",
                               turn=int(turn or 0), fact_id=fact_id, text=text)
            _pin_against(session, str(actor_id), str(target_id), fact_id=fact_id, turn=turn, text=text)
    elif kind == "free":
        rt = _rt(target_id)
        if not rt:
            return
        before = dict(rt)
        rt["restrained"] = False
        rt["gagged"] = False
        rt["canSpeak"] = True
        rt["mobility"] = max(float(rt.get("mobility") or 0), 0.8)
        _emit_runtime_fact(target_id, before)
        # V65Q: freeing her ends a pressed-against position as well.
        _scene.release_position(session, str(target_id), turn=int(turn or 0), why="befreit")
    elif kind == "move":
        rt = _rt(actor_id or target_id)
        if not rt:
            return
        # V65Q (AMASTER §43 "Capability ... wirksam bei ... Commit", §43.1 blocked; Pruefung
        # v2.8 P-02): leaving the place is a movement like a withdrawal - resolved against
        # the same capability and the pressed-against position before the position changes.
        _ev_m = next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict) and fact_id and f.get("id") == fact_id), None)
        why_m = _movement_block(session, str(actor_id or target_id), None, "move")
        if why_m:
            if _ev_m is not None:
                _ev_m.setdefault("effect", {}).update({"outcome": "blocked", "blockedBy": why_m[0], **why_m[1]})
            return
        before = dict(rt)
        # V65c (measured, your session 27.10. T5): "Sie steht auf, geht zur Bar und
        # greift nach zwei Gläsern" set Tam's position to the free-text guess "Bar und
        # greift nach zwei Gläsern"; position != scene place, so from then on she was
        # no hearer (_scene_perception): no Erleben and no line of Tom in her brief
        # for 9 turns. The destination is now a KNOWN place or nothing (§24.7).
        current = str(rt.get("position") or scene.get("placeName") or "")
        dest = _known_destination(text, world)
        _ev = next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict) and fact_id and f.get("id") == fact_id), None)
        if _ev is not None:
            _ev.setdefault("effect", {})["destination"] = dest or None
            if not dest:
                _ev["effect"]["ambiguous"] = "ziel_ort_unbekannt"
        if dest and dest != current:
            if _ev is not None:
                _ev.setdefault("effect", {})["outcome"] = "completed"
            _scene.clear_spatial_for(session, str(actor_id or target_id), turn=int(turn or 0))
            rt["position"] = dest
            if scene.get("placeName") and dest.lower() not in str(scene.get("placeName") or "").lower():
                scene["notes"] = ((scene.get("notes") or "") + f" {dest}").strip()
            _emit_runtime_fact(actor_id or target_id, before)
    elif kind == "social":
        # V60 (AMASTER §68 Nr. 45/46/59, §42, §44): a tender touch is an
        # objective physical event — the two are now in touch (SpatialState).
        # It does NOT set the actor's emotion, nor raise trust or closeness by
        # fixed increments: shown nearness is not felt trust. The affected
        # figure's inner reaction comes from her own validated reply.
        if actor_id and target_id and str(actor_id) != str(target_id):
            _scene.set_spatial(session, str(actor_id), str(target_id), "beruehrung",
                                   turn=int(turn or 0), fact_id=fact_id, text=text)
    elif kind in ("approach", "withdraw"):
        # V65P (AMASTER §43 "Capability … wirksam bei … Commit", §43.1 Outcome
        # blocked/completed, §42 Versuch -> tatsaechlicher Ausgang; IST-Probe 3b):
        # a movement relative to a person is resolved against the mover's
        # current capability BEFORE the spatial state changes. Before, a held
        # or immobile figure "withdrew" successfully every time. The outcome is
        # written on the act's Fact; a blocked attempt leaves the room as it is.
        if actor_id and target_id and str(actor_id) != str(target_id):
            _ev = next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict) and fact_id and f.get("id") == fact_id), None)
            why = _movement_block(session, str(actor_id), str(target_id), kind)
            if why:
                if _ev is not None:
                    _ev.setdefault("effect", {}).update({"outcome": "blocked", "blockedBy": why[0], **why[1]})
                return
            if _ev is not None:
                _ev.setdefault("effect", {})["outcome"] = "completed"
            _row_now = ((session.get("sceneState") or {}).get("spatial") or {}).get("|".join(sorted((str(actor_id), str(target_id))))) or {}
            if kind == "approach" and _row_now.get("relation") == "beruehrung":
                # V65Q: coming closer to someone already in touch keeps the touch (no step back to "nah").
                return
            _scene.set_spatial(session, str(actor_id), str(target_id), "nah" if kind == "approach" else "abstand",
                               turn=int(turn or 0), fact_id=fact_id, text=text)


# V65P: labels of the two system movement classes for the mirrored outcome
# (system class names, not a reading of the text).
_MOVEMENT_LABEL = {"withdraw": "Rückzug", "approach": "Annäherung",
                   # V65Q: the other system classes, for an attempted or blocked act.
                   "move": "Ortswechsel", "strike": "Angriff", "restrain": "Festhalten", "free": "Befreien", "social": "Berührung"}


def _movement_blocked_reason(rt: dict | None) -> str | None:
    """V65P (AMASTER §43 Capability, §43.1 blocked): why a validated movement
    class cannot be carried out now - the SAME runtime thresholds as
    capability_blocks_action (consciousness < 0.5, canMove false, mobility
    < 0.3) plus a running fixation (`restrained`, §43 "Festhalten oder
    Fixierung"). Reads runtime state only, never the text."""
    rt = rt if isinstance(rt, dict) else {}
    if float(rt.get("consciousness") if rt.get("consciousness") is not None else 1) < 0.5:
        return "bewusstlos"
    if rt.get("restrained"):
        return "fixiert"
    if rt.get("canMove") is False or float(rt.get("mobility") if rt.get("mobility") is not None else 1) < 0.3:
        return "bewegungsunfähig"
    return None


def _pin_against(session: dict, actor_id: str, target_id: str, *, fact_id: str | None, turn: Any, text: str) -> None:
    """V65Q (AMASTER §20 Z. 926/947, §43.2, FOUNDATION H): a confirmed attack/binding whose
    check found the surface literally in the act presses the target against it."""
    ev = next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict) and fact_id and f.get("id") == fact_id), None)
    gegen = str(((ev or {}).get("effect") or {}).get("gegen") or "").strip()
    if gegen:
        _scene.set_position(session, str(target_id), gegen, by=str(actor_id), turn=int(turn or 0), fact_id=fact_id, text=text)


def _movement_block(session: dict, actor_id: str, target_id: str | None, kind: str) -> tuple[str, dict] | None:
    """V65Q (AMASTER §43.1 "Vor einem vollzogenen Action-Commit werden ... Capability, Position,
    Reichweite, ... Object-/Spatial-State, laufende Fixierungen ... geprueft"; Pruefung v2.8 P-02):
    why a validated movement of this figure cannot happen now - her capability (V65P), or she is
    pressed against a surface by someone still in touch with her (moving toward that very person
    is no escape and stays possible). Returns (reason, detail) or None. Read only."""
    why = _movement_blocked_reason((session.get("runtimes") or {}).get(str(actor_id)))
    if why:
        return why, {}
    pos = _scene.active_position(session, str(actor_id))
    if pos and not (kind == "approach" and target_id and str(target_id) == str(pos.get("by") or "")):
        return "gedrueckt_gegen", {"blockedGegen": pos.get("gegen"), "blockedPinBy": pos.get("by"), "blockedPinFactId": pos.get("factId")}
    return None


_CONSENT_ACTS = ("social", "strike", "restrain")


body_contact_proposition = _scene.body_contact_proposition   # V65S: one reader (scene_state)
body_contact_state = _scene.body_contact_state


def _body_contact_container(session: dict, actor_id: str, target_id: str, turn: int) -> dict:
    """V65S/V65T (AMASTER §35 "dieselbe Angelegenheit ueber mehrere Ereignisse"): the container Proposition
    "Koerperkontakt actor -> target" (one per directed pair), opened on first use. It holds the acts (evidence) and
    the giver's answers (lifecycle); it is no consent of its own (§36.5 Z. 1947/1974, act_consent)."""
    prop = _scene.body_contact_proposition(session, actor_id, target_id)
    if prop is None:
        # Names are rendered by the readers from the IDs (actorId/targetId); the stored wording names none.
        prop = {"id": _next_id("prop", session), "kind": "koerperkontakt", "status": "open",
                "text": "Körperkontakt", "matter": "Körperkontakt (Einwilligung der berührten Person)",
                "actors": [actor_id, target_id], "actorId": actor_id, "targetId": target_id, "turn": turn, "evidence": []}
        session.setdefault("propositions", []).append(prop)
    return prop


def _body_contact_matter(session: dict, fact: dict | None, actor_id: Any, target_id: Any, kind: str | None) -> None:
    """V65S (AMASTER §35 Z. 1847, §36.5 Z. 1947, §40; Plan V65S P1/S1): every validated body act X -> Y
    (social/strike/restrain) is evidence of the container "Koerperkontakt X -> Y". The act's own matter binding
    (proposition_id, e.g. an answer to an open request, §24.2) stays untouched.
    V65T (§36.5 Z. 1947 "an die betreffende ... Handlung gebunden", Z. 1974 "fruehere Zustimmung ist nicht automatisch
    aktuelle Zustimmung"; v3.2 Befund 1): the act's own new Fact records its time (`at`, §37) and the consent standing
    AT the act, reduced by scene_state.act_consent (bound request answered before, else a validated boundary in
    scope and window, else unknown) - never from the container's status, never from the act itself."""
    if not isinstance(fact, dict) or kind not in _CONSENT_ACTS or not actor_id or not target_id or str(actor_id) == str(target_id):
        return
    a, t = str(actor_id), str(target_id)
    turn = int(fact.get("turn") or session.get("turnIndex") or 0)
    prop = _body_contact_container(session, a, t, turn)
    eff = fact.setdefault("effect", {}) if isinstance(fact.get("effect"), dict) or fact.get("effect") is None else None
    entry = {"kind": "act", "factId": fact.get("id"), "by": a, "turn": turn, "text": str(fact.get("text") or "")[:160]}
    prop.setdefault("evidence", []).append(entry)
    if eff is None:
        return
    _now = session_clock(session)
    eff["consent"] = {"propositionId": prop.get("id"), "at": _now.isoformat(timespec="minutes") if _now else None}
    # V65W (Tiefenpruefung v1 P03/C4): the scene this act happens in (SceneState.sceneId), recorded with the act itself
    _sid = _scene.scene_id(session)
    if _sid:
        eff["consent"]["sceneId"] = _sid
        if _scene.scene_closed(session):
            eff["consent"]["sceneClosed"] = True
    c = _scene.act_consent(session, fact) or {"state": "unknown"}
    for k in ("state", "basis", "since", "causeFactId", "requestId", "einschraenkung", "grenzenEingeschraenkt", "grenzeAusnahme", "teilAusserhalb",
              "schaden"):   # V66 (Audit5 E06): a harmful act is recorded as such
        if c.get(k) is not None:
            eff["consent"][k] = c[k]
    entry["state"] = c.get("state")


def act_consent_text(session: dict, fact: dict | None, names: list[dict] | None, *, viewer: Any) -> str | None:
    """V65R, V65T: the consent of this one act as a mirrored phrase (no instruction), from scene_state.act_consent:
    "gegen ... Ablehnung" only when a boundary or a refused request stood against it AT the act; a withdrawal; and the
    giver's own later answer to exactly this act. None otherwise (unknown is not mirrored)."""
    c = _scene.act_consent(session, fact) if isinstance(fact, dict) else None
    if not isinstance(c, dict):
        return None
    mine = str((fact or {}).get("targetId") or "") == str(viewer or "")
    who = None if mine else _name_of(fact.get("targetId"), list(names or []), session)
    parts = []
    if c.get("state") == "declined":
        parts.append(f"gegen deine Ablehnung seit Turn {c.get('since')}" if mine else f"gegen die Ablehnung von {who} seit Turn {c.get('since')}")
    elif c.get("state") == "revoked":
        parts.append(f"nach deinem Widerruf in Turn {c.get('since')}" if mine else f"nach dem Widerruf von {who} in Turn {c.get('since')}")
    ans = c.get("answer") if isinstance(c.get("answer"), dict) else None
    if ans and ans.get("kind") == "refusal":
        parts.append(f"von dir in Turn {ans.get('turn')} abgelehnt" if mine else f"von {who} in Turn {ans.get('turn')} abgelehnt")
    elif ans and ans.get("kind") == "acceptance":
        parts.append(f"von dir in Turn {ans.get('turn')} angenommen" if mine else f"von {who} in Turn {ans.get('turn')} angenommen")
    return "; ".join(parts) or None


AUSSAGE_ARTEN = ("bestreitet_geschehen", "bestaetigt", "bewertet", "verweigert_antwort")


def _seg_norm(t: Any) -> str:
    return re.sub(r"\s+", " ", str(t or "").casefold()).strip(" .,!?;:…\"„“'")


def next_turn_index(session: dict) -> int:
    """V68 (Audit8 P1-7 "ses_3422: der naechste Turn bekommt eine Nummer, die schon ein Fact traegt"; AMASTER §23 TurnTruth,
    §34 Quellturn, §42 Ablauf): the number of the next turn. The turn counter is kernel-owned and follows the stored history:
    one above the counter AND above the highest turn the history carries (dialogue lines, SceneFacts, God facts). V67 counted
    from the counter alone, so a session whose counter an earlier chat reset had set back gave the next turn the number of
    an existing fact. The same rule as the envelope binding (repos.bind_session_envelope). Read only."""
    return max(int(session.get("turnIndex") or 0), _scene.history_turn(session)) + 1


_GEGENSTAND_UMFANG = {"person": "jede_beruehrung", "koerperstelle_oder_art": "eingeschraenkt", "diese_handlung": "diese_tat"}


def consent_check_verdict(res: Any) -> dict | None:
    """V65V: the scope reading (GRENZE_CHECK_RULES) as the verdict conjunctive.validate_grenze reads - the object of the
    boundary and its kind decide the action scope (the person as a whole -> every touch; a body part, kind or manner ->
    restricted, quoted; this act -> this act). Read only."""
    if not isinstance(res, dict):
        return None
    art = str(res.get("gegenstand_art") or "").strip().lower()
    gg = str(res.get("gegenstand") or "").strip()[:160] or None
    umfang = _GEGENSTAND_UMFANG.get(art)
    ri = str(res.get("richtung") or "").strip().lower()
    return {"umfang": umfang, "gegenstand": gg, "einschraenkung": gg if umfang == "eingeschraenkt" else None,
            "richtung": ri if ri in ("verboten", "erlaubt") else None,
            "geltung": res.get("geltung"), "geltung_beleg": res.get("geltung_beleg")}


def restricted_boundaries_for(session: dict, actor_id: Any, figures: list[dict] | None = None) -> list[dict]:
    """V65W (Tiefenpruefung v1 P06/C1): the restricted refusals standing NOW against acts of `actor_id`, per giver who is
    present - what a body act of this actor must be read against before its write (the app runs one act reading per
    entry; none -> no call). Read only."""
    a = str(actor_id or "")
    present = {str(x) for x in ((session.get("scene") or {}).get("presentIds") or [])}
    names = {str(c.get("id") or ""): str(c.get("name") or "") for c in _session_cast(session, list(figures or [])) if isinstance(c, dict)}
    _now = session_clock(session)
    out = []
    for p in session.get("propositions") or []:
        if not (isinstance(p, dict) and p.get("kind") == "koerperkontakt" and str(p.get("actorId") or "") == a):
            continue
        giver = str(p.get("targetId") or "")
        if not giver or giver == a or (present and giver not in present):
            continue
        for e in _scene.restricted_refusals_standing(session, p, at=_now.isoformat(timespec="minutes") if _now else None):
            out.append({"causeFactId": e["factId"], "targetId": giver, "targetName": names.get(giver, ""),
                        "einschraenkung": e["einschraenkung"], "beleg": e["beleg"]})
    return out   # V65X (E04): every standing restriction is read - no silent cut


def restricted_exceptions_for(session: dict, actor_id: Any, figures: list[dict] | None = None) -> list[dict]:
    """V65Y (Gesamtpruefung V65X N05): the parts a present giver later permitted, took back or named unconfirmed while her
    boundary for every touch against `actor_id` stands (body_contact_standing `ausnahmen`), and - with no such boundary -
    her standing restricted permissions. What a body act of this actor that names such a part is read against (the app
    runs one reading per entry only for an act naming it). Read only."""
    a = str(actor_id or "")
    present = {str(x) for x in ((session.get("scene") or {}).get("presentIds") or [])}
    names = {str(c.get("id") or ""): str(c.get("name") or "") for c in _session_cast(session, list(figures or [])) if isinstance(c, dict)}
    _now = session_clock(session)
    at = _now.isoformat(timespec="minutes") if _now else None
    out = []
    for p in session.get("propositions") or []:
        if not (isinstance(p, dict) and p.get("kind") == "koerperkontakt" and str(p.get("actorId") or "") == a):
            continue
        giver = str(p.get("targetId") or "")
        if not giver or giver == a or (present and giver not in present):
            continue
        texts = {str(e["factId"]): e for e in _scene.body_contact_entries(session, p)}
        st = _scene.body_contact_standing(session, p, at=at)
        if st is not None and st.get("state") == "declined":
            rows = [(x["causeFactId"], x.get("kind"), x["einschraenkung"]) for x in st.get("ausnahmen") or []]
        elif st is None:
            rows = [(e["factId"], "acceptance", e["einschraenkung"]) for e in _scene.restricted_permissions_standing(session, p, at=at)]
        else:
            rows = []
        for fid, kind, einschr in rows:
            e = texts.get(str(fid)) or {}
            out.append({"causeFactId": str(fid), "targetId": giver, "targetName": names.get(giver, ""), "kind": kind,
                        "einschraenkung": einschr, "beleg": str(e.get("beleg") or e.get("text") or "")[:240],
                        # V68 (Audit8 P0-1): the giver's own words and the persons' names - a part is inside only when they
                        # cover it (the reader checks the same again, scene_state.exception_verdict)
                        "wortlaut": str(e.get("text") or "")[:240], "namen": [n for n in names.values() if n]})
    return out


def permission_reference_verdict(res: Any, *, act_text: str, entry: dict, utterance: str | None = None) -> dict:
    """V65Y (N05; AMASTER §24.2 Z. 1110-1113, §34.1): the permission reading (ERLAUBNISBEZUG_CHECK_RULES) as the verdict
    scene_state.act_consent reads (art "ausnahme"): validiert only when every part is literal in the act and the parts
    cover the whole act; a part is inside only when the reading says so AND it names the permitted part's head word
    (scene_state.exception_verdict checks the same again against the act's Fact). Read only."""
    base = {"art": "ausnahme", "causeFactId": str(entry.get("causeFactId") or ""), "targetId": entry.get("targetId"),
            "einschraenkung": str(entry.get("einschraenkung") or "")[:160]}
    if not isinstance(res, dict) or not isinstance(res.get("teile"), list):
        return {**base, "status": "ungeprueft"}
    teile = _own_parts([t for t in res["teile"] if isinstance(t, dict) and str(t.get("wortlaut") or "").strip()], act_text, utterance)
    if not teile:
        return {**base, "status": "ungeprueft"}
    literal, rest = _teile_luecke(act_text, teile)
    if not literal:
        return {**base, "status": "unbestaetigt:teil_nicht_woertlich", "teile": [str(t.get("wortlaut"))[:80] for t in teile]}
    if rest:
        return {**base, "status": "unbestaetigt:teile_unvollstaendig", "teile": [str(t.get("wortlaut"))[:80] for t in teile], "rest": rest[:80]}
    rows = [{"wortlaut": str(t.get("wortlaut")).strip()[:160],
             "innerhalb": t.get("innerhalb") is True and _scene.names_restriction(t.get("wortlaut"), entry.get("einschraenkung"), exact=True)
             # V68 (Audit8 P0-1; AMASTER §36.5): the permission names its act - the giver's own words cover the part
             and _scene.covers_request(t.get("wortlaut"), [entry.get("wortlaut"), entry.get("beleg")], entry.get("namen") or ())}
            for t in teile]
    return {**base, "status": "validiert", "teile": rows}


def boundary_reference_verdict(res: Any, *, act_text: str, entry: dict) -> dict:
    """V65W (C1; AMASTER §24.2 Z. 1110-1113 Semantik -> Validierung, §36.5, §34.1 Z. 1807): the act reading
    (GRENZBEZUG_CHECK_RULES) as the verdict scene_state.act_consent reads: the act touches exactly the restriction only
    when the reading says so AND quotes the words of the act that do it, literally. Without a reading: ungeprueft (the
    act stays unknown). Read only."""
    base = {"causeFactId": str(entry.get("causeFactId") or ""), "targetId": entry.get("targetId"),
            "einschraenkung": str(entry.get("einschraenkung") or "")[:160], "betroffen": False}
    if not isinstance(res, dict):
        return {**base, "status": "ungeprueft"}
    q = str(res.get("beleg") or "").strip()[:160]
    if res.get("betroffen") is not True:
        return {**base, "status": "nicht_betroffen", "beleg": q or None}
    if not q or not _scene.literal_in(q, act_text):   # V66 (Audit5 E06): on word boundaries ("deine Hand" in "Handtasche")
        return {**base, "status": "unbestaetigt:beleg_nicht_woertlich", "beleg": q or None}
    if not _scene.names_restriction(q, entry.get("einschraenkung"), word=True):   # V66 (E06): the part itself, no other side
        # V65X (Nachpruefung V65W E02; AMASTER §24.2 Z. 1113, §24.7): the quoted words of the act must themselves name the
        # forbidden part or kind (the head word of the restriction's own quote, same stem) - a reading alone never makes
        # "Ich küsse dich" a shoulder violation. Kernel anchor, veto only: it never makes an act betroffen by itself.
        return {**base, "status": "unbestaetigt:tat_nennt_grenze_nicht", "beleg": q}
    return {**base, "betroffen": True, "status": "validiert", "beleg": q}


def statement_check_verdict(res: Any, tatbezug: dict | None = None) -> dict | None:
    """V65V: the statement reading (AUSSAGE_CHECK_RULES) as the verdict apply_statement_components reads.
    V65W (Tiefenpruefung v1 P04/C5): per event. An event the decomposition reads as denied (gegenstand geschehen, in
    `bestritten`) gets its row from the follow-up at that event (`tatbezug` = {label: AUSSAGE_TAT_RULES answer}):
    ausgeschlossen only when the follow-up says it denies exactly this act; without a follow-up the row is ungeprueft.
    Binding then needs the literal anchors, checked by apply_statement_components against the segment and the event's Fact.
    A raw value that already holds per-event rows ({"ereignisse": [...]}) is the normalized form. Read only."""
    if not isinstance(res, dict):
        return None
    if isinstance(res.get("ereignisse"), list):
        rows = []
        for r in res["ereignisse"]:
            if not isinstance(r, dict):
                continue
            lab = str(r.get("kennung") or "").strip().strip("[]")[:8]
            bez = str(r.get("bezug") or "").strip().lower()
            if not lab or bez not in ("ausgeschlossen", "vereinbar", "ungeprueft"):
                continue
            rows.append({"kennung": lab, "bezug": bez, "verneint": str(r.get("verneint") or "").strip()[:160] or None,
                         "tat": str(r.get("tat") or "").strip()[:160] or None})
        ex = [r["kennung"] for r in rows if r["bezug"] == "ausgeschlossen"]
        return {"ereignisse": rows, "bestritten": ex, "art": "bestreitet" if ex else ("vereinbar" if rows else "unklar"),
                "beleg": next((r["verneint"] for r in rows if r["bezug"] == "ausgeschlossen" and r["verneint"]), None)}
    if "gegenstand" not in res:
        return None
    gg = str(res.get("gegenstand") or "").strip().lower()
    labs = [str(x).strip().strip("[]") for x in (res.get("bestritten") or []) if str(x).strip()] if gg == "geschehen" else []
    tb = {str(k).strip().strip("[]"): v for k, v in (tatbezug or {}).items()} if isinstance(tatbezug, dict) else {}
    rows = []
    for lab in labs:
        f = tb.get(lab)
        if not isinstance(f, dict):
            rows.append({"kennung": lab, "bezug": "ungeprueft", "verneint": None, "tat": None})
            continue
        rows.append({"kennung": lab, "bezug": "ausgeschlossen" if f.get("bestreitet") is True else "vereinbar",
                     "verneint": str(f.get("verneint") or "").strip()[:160] or None, "tat": str(f.get("tat") or "").strip()[:160] or None})
    ex = [r["kennung"] for r in rows if r["bezug"] == "ausgeschlossen"]
    return {"ereignisse": rows, "bestritten": ex, "gegenstand": gg or None,
            "art": "bestreitet" if ex else {"bewertung": "bewertet", "gefuehl": "fuehlt", "geschehen": "nicht_am_ereignis"}.get(gg, "anderes"),
            "beleg": next((r["verneint"] for r in rows if r["bezug"] == "ausgeschlossen" and r["verneint"]), None)}


def apply_statement_components(session: dict, fact: dict | None, aussagen: Any, ereignisse: Any, *, speaker: dict,
                               hearers: list[dict], avatar_id: str | None, turn: int,
                               figures: list[dict] | None = None) -> list[dict]:
    """V65T (AMASTER §34.1 Komponenten je Teilaussage, §36.3 Z. 1937 Self-Claim/Irrtum/Luege, §36.4 Z. 1941 "Widerspruch
    erzeugt neue Evidenz", §50 Z. 2817 Figuren duerfen luegen, §24.2 LLM schlaegt vor - Kernel validiert; Plan v2
    Schritt 3; Gegenpruefung v3.2 Befund 4): the formulation's statement components of HER speech, checked one by one -
    the segment literally in the speech, the art from the closed set, each cited event [E#] resolved by the map of
    the brief she was given to a validated act she herself did, suffered or saw (her own accessible Fact). The checked
    list is kept on her own new speech Fact (statement provenance, for the Regie reaction and the UI). Only
    `bestreitet_geschehen` against such an act is new evidence: truth.register_denial (claim + contradiction Fact known
    to her; hearers who saw the act notice it). Evaluating, minimising or refusing to answer is never a contradiction.
    No filter, no retry, the speech stays as spoken. Returns the checked components.
    V65U (AMASTER §24.2 Z. 1110-1113 Semantik -> Validierung, §34.1 Z. 1803/1807-1815, §36.3 Z. 1937, §36.4 Z. 1941,
    §24.7 Z. 1252; Codegutachten v1 N2): the art is the reading's semantic proposal, never the evidence by itself. A
    denial of an EVENT is a statement about a deed and its doer ("Wer hat es getan?"); a subjective evaluation of her
    own experience ("Ich fuehle mich nicht belaestigt") names no doer. So a `bestreitet_geschehen` binds an act only
    when the segment itself names the act's doer - found by the kernel's own cast resolver (_named_by_name_part over
    _session_cast, cast data, no word list, no model field). Otherwise the component stays visible Redeprovenienz
    (status unbestaetigt:taeter_nicht_benannt) and the contradiction writer is not called.
    V65V (Nachpruefung v1 K3): the name gate is replaced - a named doer is no proof of a denial. A denial binds only when
    the separate statement reading (pruefung) names these events as not having taken place, with a literal quote."""
    if not isinstance(fact, dict) or not isinstance(aussagen, list):
        return []
    sid = str(speaker.get("id") or "")
    spoken = _seg_norm(fact.get("text"))
    labels = ereignisse if isinstance(ereignisse, dict) else {}
    by_id = {str(f.get("id") or ""): f for f in session.get("facts") or [] if isinstance(f, dict)}
    access = {str(w.get("fact_id") or w.get("factId") or "") for w in session.get("witnessKnowledge") or []
              if isinstance(w, dict) and str(w.get("character_id") or w.get("characterId") or "") == sid
              and w.get("access") in ("seen", "affected")}

    def own_event(fid: str) -> dict | None:
        f = by_id.get(fid)
        if not isinstance(f, dict) or f.get("kind") != "action" or not _scene.validiert(f):
            return None
        if sid in (str(f.get("actorId") or ""), str(f.get("targetId") or "")) or fid in access:
            return f
        return None

    checked: list[dict] = []
    for a in aussagen:   # V65X (E04): every component is checked, none silently dropped
        if not isinstance(a, dict):
            continue
        seg = str(a.get("segment") or "").strip()[:240]
        art = str(a.get("art") or "")
        row: dict[str, Any] = {"segment": seg, "art": art, "factIds": [], "status": "validiert"}
        if art not in AUSSAGE_ARTEN:
            row["status"] = "ungueltig:art"
        elif not seg or not _seg_norm(seg) or _seg_norm(seg) not in spoken:
            row["status"] = "ungueltig:segment_nicht_woertlich"
        else:
            ids = [str(labels.get(str(e).strip().strip("[]"))) for e in (a.get("ereignis") or []) if str(e).strip().strip("[]") in labels]
            evs = [f for f in (own_event(i) for i in dict.fromkeys(ids)) if f is not None]
            if not evs:
                row["status"] = "ungueltig:ereignis_nicht_eigen"
            elif art == "bestreitet_geschehen":
                # V65V (Nachpruefung v1 K3; AMASTER §24.2 Z. 1110-1113, §36.3/§36.4, §24.7): the second semantic key is
                # the separate statement reading (a["pruefung"], AUSSAGE_CHECK_RULES, set server-side before the write):
                # it must name exactly these events as denied - "did not take place" - with a literal quote of the
                # segment. A named doer proved nothing ("Ich fuehle mich durch Kvle nicht belaestigt"); an evaluation,
                # a feeling or minimising is no denial. Without that reading the component stays visible, unconfirmed.
                chk = a.get("pruefung") if isinstance(a.get("pruefung"), dict) else None
                lab_of = {str(v): str(k) for k, v in labels.items()}
                # V65W (Tiefenpruefung v1 P04/C5 "Negationsbezug am Ereignis validieren"): per cited event, the reading's
                # answer to "can the segment be true although this act took place?" - bound only when excluded AND both
                # literal anchors hold: the negating words in the segment, the denied words in the event's OWN Fact text.
                # A verdict without per-event rows (V65V shape) binds nothing.
                per = {str(r.get("kennung") or ""): r for r in ((chk or {}).get("ereignisse") or []) if isinstance(r, dict)}
                bound, why = [], None
                for f in evs:
                    r = per.get(lab_of.get(str(f.get("id"))) or "")
                    if r is None or r.get("bezug") != "ausgeschlossen":
                        why = why or ("ereignis_vereinbar" if r is not None and r.get("bezug") == "vereinbar" else "ereignis_ungeprueft")
                        continue
                    if not r.get("verneint") or _seg_norm(r.get("verneint")) not in _seg_norm(seg):
                        why = why or "verneinung_nicht_woertlich"
                        continue
                    if not r.get("tat") or _seg_norm(r.get("tat")) not in _seg_norm(f.get("text")):
                        why = why or "tat_nicht_woertlich"
                        continue
                    bound.append(f)
                if chk is None:
                    row["status"] = "unbestaetigt:ungeprueft"
                elif not isinstance(chk.get("ereignisse"), list):
                    row["status"] = "unbestaetigt:ohne_ereignisbezug"
                elif not bound:
                    row["status"] = f"unbestaetigt:{why or str(chk.get('art') or 'kein_bestreiten')[:20]}"
                row["pruefung"] = ({"art": chk.get("art"), "bestritten": [str(x) for x in (chk.get("bestritten") or [])],
                                    "ereignisse": copy.deepcopy(chk.get("ereignisse")) if isinstance(chk.get("ereignisse"), list) else None}
                                   if chk is not None else None)
                if row["status"] != "validiert":
                    row["vorschlagFactIds"] = [str(f.get("id")) for f in evs]
                evs = bound
            row["factIds"] = [str(f.get("id")) for f in evs]
        checked.append(row)
    if checked:
        fact["aussagen"] = checked
    denied = [r for r in checked if r["status"] == "validiert" and r["art"] == "bestreitet_geschehen"]
    if denied:
        items, seen_ids = [], set()
        for r in denied:
            for fid in r["factIds"]:
                if fid in seen_ids:
                    continue
                seen_ids.add(fid)
                f = by_id[fid]
                items.append({"factId": fid, "turn": f.get("turn"), "text": str(f.get("text") or "")[:160], "beleg": r["segment"]})
        if items:
            _truth.register_denial(session, speaker, fact, items, hearers=hearers, avatar_id=avatar_id, turn=turn)
    return checked


# V65W (Tiefenpruefung v1 P06/C1): the validated boundary scopes that reach beyond the answered act - every touch, or a
# restriction quoted literally (body part, kind or manner); both bound to one toucher, with their window
GRENZE_WIDE_SCOPES = ("jede_beruehrung", "eingeschraenkt")


def _resolve_grenze(session: dict, grenze: Any, figures: list[dict] | None, actor_id: Any) -> dict | None:
    """V65T (AMASTER §24.1 Entity-Resolver, §24.7 keine geratene Bindung, §34.1 Grenze): the person a validated
    boundary names (wer) -> exactly one cast ID other than the speaker (_named_by_name_part over _session_cast).
    0 or several -> status ungueltig (binds nothing, stays audit). Read only."""
    if not isinstance(grenze, dict):
        return None
    g = dict(grenze)
    if g.get("status") != "validiert" or g.get("gilt_fuer") not in GRENZE_WIDE_SCOPES:
        return g
    if (g.get("geltung") or {}).get("art") == "szene" and not g.get("fenster"):
        # V65V (Nachpruefung v1 K4): the default duration = this scene - place and turn of the answer (V65W: derived from
        # §36.5 Z. 1956/1974, §20 Z. 914 and §24.7; §46.5 governs the session God, it was cited wrongly)
        # V65W (Tiefenpruefung v1 P03/C4, AMASTER §20/§21): and the scene's own identity (SceneState.sceneId), so a scene
        # change at the same place ends it (scene_state._in_scene)
        _sid = _scene.ensure_state(session).get("sceneId")
        g["fenster"] = {"art": "szene", "placeId": (session.get("scene") or {}).get("placeId"), "seitTurn": int(session.get("turnIndex") or 0),
                        "label": "laufende Szene", **({"sceneId": str(_sid)} if _sid else {})}
    ids = _named_by_name_part(str(g.get("wer") or ""), _session_cast(session, list(figures or []))) - {str(actor_id or "")}
    if len(ids) == 1:
        g["werId"] = next(iter(ids))
    else:
        g.update({"status": "ungueltig", "grund": "wer_ungebunden" if not ids else "wer_mehrdeutig"})
    return g


def _body_contact_answer(session: dict, prop: dict, *, actor_id: str, fact_id: str | None, grenze: dict | None) -> dict:
    """V65T (§36.5 Z. 1947/1974, §34.1, §34.3 Provenienz): what one answer of the giver binds - the concrete acts of
    the line it answers that are evidence of this container (actFactIds), and its scope: diese_tat unless a
    validated boundary for every touch by exactly this toucher (werId == the container's actor), with its window.
    Read only; the lifecycle owner writes it with the answer."""
    line = _answered_line_facts(session, str(actor_id), fact_id)
    ev = {str(e.get("factId") or "") for e in prop.get("evidence") or [] if isinstance(e, dict) and e.get("kind") == "act"}
    out = {"actFactIds": [str(f.get("id")) for f in line if f.get("kind") == "action" and str(f.get("id") or "") in ev],
           "scope": "diese_tat", "window": None, "beleg": "", "grenze": "keine"}
    if isinstance(grenze, dict):
        if grenze.get("status") != "validiert":
            out["grenze"] = f"{grenze.get('status') or 'ungueltig'}:{grenze.get('grund') or ''}"
            if grenze.get("einschraenkung"):
                out["einschraenkung"] = str(grenze.get("einschraenkung"))[:160]
        elif grenze.get("gilt_fuer") in GRENZE_WIDE_SCOPES and str(grenze.get("werId") or "") != str(prop.get("actorId") or ""):
            out["grenze"] = "ungueltig:wer_nicht_beruehrender"
        else:
            out.update({"scope": grenze.get("gilt_fuer"), "beleg": str(grenze.get("beleg") or "")[:200], "grenze": "validiert",
                        "window": grenze.get("fenster") if grenze.get("gilt_fuer") in GRENZE_WIDE_SCOPES else None})
            if grenze.get("gilt_fuer") == "eingeschraenkt":
                # V65W (C1): the restriction's literal words are part of the answer (scene_state.restricted_refusals_standing)
                out["einschraenkung"] = str(grenze.get("einschraenkung") or "")[:160]
    if out.get("einschraenkung"):
        # V65X (live 30.10.: Maras "Du darfst meine Schulter wieder anfassen" was recorded as the answer to the kiss before
        # it; AMASTER §36.5 Z. 1947 an die betreffende Handlung gebunden, §34.3 Provenienz): an answer that names its own part
        # answers only the acts of the line that name that part (kernel anchor, same stem); the other acts get no answer
        _by = {str(f.get("id")): f for f in line if isinstance(f, dict)}
        out["actFactIds"] = [i for i in out["actFactIds"] if _scene.names_restriction((_by.get(i) or {}).get("text"), out["einschraenkung"])]
    return out


def act_outcome(session: dict, fact: dict | None) -> dict | None:
    """V65P (AMASTER §42 Versuch -> Ausgang, §43.1): the resolved outcome of a
    committed movement act, read from state: `blocked` (on the Fact), or
    `overcome` (the counterpart reached the figure again after this withdrawal).
    V65Q: also `attempted` (tried now, not achieved - on the Fact), and `overcome`
    from the overcoming act's own Fact (durable after a place change; the room
    row stays the fallback for rows written by V65P). None = completed or no
    such act. Read only."""
    if not isinstance(fact, dict) or fact.get("kind") != "action":
        return None
    eff = fact.get("effect") if isinstance(fact.get("effect"), dict) else {}
    kind = str(eff.get("effectKind") or "")
    if eff.get("outcome") == "attempted":
        return {"state": "attempted", "kind": str(eff.get("attemptedKind") or ""), "reason": ""}
    if eff.get("outcome") == "blocked":
        return {"state": "blocked", "reason": str(eff.get("blockedBy") or ""), "kind": kind,
                "gegen": eff.get("blockedGegen"), "pinBy": eff.get("blockedPinBy")}
    if kind == "withdraw" and fact.get("id"):
        hit = _scene.overcome_for_fact(session, str(fact.get("id")))
        if hit:
            return {"state": "overcome", "by": str(hit.get("by") or ""), "turn": hit.get("turn"), "text": str(hit.get("text") or ""), "kind": kind}
    return None


def act_outcome_text(session: dict, fact: dict | None, names: list[dict] | None, *, own: bool) -> str | None:
    """V65P: the outcome as a mirrored state phrase (no instruction)."""
    o = act_outcome(session, fact)
    if not o:
        return None
    label = _MOVEMENT_LABEL.get(o.get("kind") or "", "Handlung")
    if o["state"] == "attempted":
        return f"{label} versucht, ohne Wirkung"
    if o["state"] == "blocked":
        if o.get("reason") == "gedrueckt_gegen":
            who = _person_name(session, names, o.get("pinBy"))
            return f"{label} blieb ohne Wirkung: {who} drückt {'dich' if own else 'sie/ihn'} gegen „{o.get('gegen')}“"
        return f"{label} blieb ohne Wirkung: {o.get('reason') or 'nicht möglich'}"
    who = _person_name(session, names, o.get("by"))
    return (f"{who} hat {'dich' if own else 'sie/ihn'} danach wieder erreicht (Turn {o.get('turn')}: {str(o.get('text') or '')[:80]})")


def _open_request(session: dict, ref: Any) -> dict | None:
    """The open Proposition a reference names: its ID, or its exact text/matter."""
    key = str(ref or "").strip().strip("[]")
    if not key:
        return None
    for p in reversed(session.get("propositions") or []):
        if not isinstance(p, dict) or p.get("status") not in ("open", "active", "accepted"):
            continue
        if key == str(p.get("id") or "") or key in (str(p.get("text") or ""), str(p.get("matter") or "")):
            return p
    return None


def _bind_response_to_request(session: dict, fact: dict, ref: Any, *, turn: int) -> dict | None:
    """V60 (AMASTER §35, §36.1): a validated act of the RECIPIENT that the
    planner relates to an open request is evidence of the same Proposition.

    It is bound, not judged: whether it satisfies the request is decided by
    the requester's own later acceptance (lifecycle evidence), never here.
    """
    if fact.get("proposition_id") or fact.get("propositionId"):
        return None
    prop = _open_request(session, ref)
    if prop is None:
        _bind_act_to_goal(session, fact, ref)
        return None
    actor = str(fact.get("actorId") or "")
    if not actor or actor != str(prop.get("targetId") or "") or actor == str(prop.get("actorId") or ""):
        return None
    fact["proposition_id"] = prop.get("id")
    fact["propositionId"] = prop.get("id")
    gid = next((g.get("id") for g in session.get("goals") or [] if isinstance(g, dict)
                and (g.get("proposition_id") or g.get("propositionId")) == prop.get("id")), None)
    if gid:
        fact["goal_id"] = gid
        fact["goalId"] = gid
    prop.setdefault("evidence", []).append({
        "kind": "response_action" if fact.get("kind") == "action" else "response_speech",
        "factId": fact.get("id"), "by": actor, "turn": int(turn or 0), "text": str(fact.get("text") or "")[:160]})
    return prop


def accepted_requests_for(session: dict, actor_id: Any, figures: list[dict] | None = None) -> list[dict]:
    """V65W (Tiefenpruefung v1 Punkt 9 / C7; AMASTER §36.1, §36.3 Acceptance an konkrete offene Bitte gebunden, §36.5): the
    requests of `actor_id` to a present figure that SHE accepted (her lifecycle acceptance) and that no own act of his has
    carried out yet - what a body act of this actor is read against before its write (one reading per entry; none -> no
    call). Read only."""
    a = str(actor_id or "")
    present = {str(x) for x in ((session.get("scene") or {}).get("presentIds") or [])}
    names = {str(c.get("id") or ""): str(c.get("name") or "") for c in _session_cast(session, list(figures or [])) if isinstance(c, dict)}
    facts = _scene.lifecycle_events(session)   # V70 (Audit10 §2/§7): the one lifecycle contract (validated, bound, order)
    out = []
    for p in session.get("propositions") or []:
        if not (isinstance(p, dict) and p.get("kind") != "koerperkontakt" and str(p.get("actorId") or "") == a and p.get("status") == "accepted"):
            continue
        t = str(p.get("targetId") or "")
        if not t or t == a or (present and t not in present):
            continue
        if any(isinstance(e, dict) and e.get("kind") == "eigene_tat" for e in p.get("evidence") or []):
            continue
        if not any(str(f.get("propositionId") or f.get("proposition_id") or "") == str(p.get("id")) and str(f.get("actorId") or "") == t
                   and str(f.get("event_kind") or "").lower() in ("acceptance", "accept") for f in facts):
            continue
        out.append({"propositionId": str(p.get("id")), "targetId": t, "targetName": names.get(t, ""), "actorName": names.get(a, ""),
                    "bitte": str(p.get("matter") or p.get("text") or "")[:300],
                    # V67 (Audit7 V66-05): the requester's own words, for the coverage of the requested act
                    "bitteText": str(p.get("text") or "")[:300]})
    return out   # V65X (E04): no silent cut


def _own_parts(teile: list, act_text: Any, utterance: Any) -> list:
    """V65Y (live 31.10.; AMASTER §34.1 "Fuer jede Komponente ... eine eigene Validierung"): a reading of ONE act component
    sometimes decomposes the whole utterance. A part that is literal in the utterance but not in this act is another
    component of the same input (it has its own Fact and its own reading) and is dropped here; a part in neither stays and
    fails the literal check. The remaining parts must still cover the whole act (fail-closed). Read only."""
    if not utterance:
        return teile
    _w = lambda t: t.get("wortlaut") if isinstance(t, dict) else t   # noqa: E731
    # V66 (Audit5 E06): literal on word boundaries
    return [t for t in teile if _scene.literal_in(_w(t), act_text) or not _scene.literal_in(_w(t), utterance)]


def _teile_luecke(act_text: Any, teile: list) -> tuple[bool, str]:
    """V65X (Nachpruefung V65W E05): (every part literal in the act, what of the act no part covers).
    V67 (Audit7 V66-05): the one coverage rule `scene_state.parts_cover` - before the first part at most the doer, between
    parts at most one connecting word, after the last part nothing (V66: only leftover words of 4+ letters counted, so
    "und tu dir weh" passed). Grammar of the act's own words, no vocabulary."""
    return _scene.parts_cover(act_text, teile)


def request_reference_verdict(res: Any, *, act_text: str, entry: dict, utterance: str | None = None) -> dict:
    """V65W (C7): the request reading (BITTEBEZUG_CHECK_RULES) as a verdict - the act is the requested act only when the
    reading splits it into its parts, each quoted literally from the act, and EVERY part is the requested one (an act that
    also does something else is not what she agreed to). Read only."""
    base = {"propositionId": str(entry.get("propositionId") or ""), "targetId": entry.get("targetId"), "erfuellt": False}
    if not isinstance(res, dict) or not isinstance(res.get("teile"), list):
        return {**base, "status": "ungeprueft"}
    teile = _own_parts([t for t in res["teile"] if isinstance(t, dict) and str(t.get("wortlaut") or "").strip()], act_text, utterance)
    if not teile:
        return {**base, "status": "nicht_erbeten"}
    literal, rest = _teile_luecke(act_text, teile)
    if not literal:
        return {**base, "status": "unbestaetigt:teil_nicht_woertlich", "teile": [str(t.get("wortlaut"))[:80] for t in teile]}
    if rest:
        # V65X (Nachpruefung V65W E05; AMASTER §24.2 Z. 1113, §36.5 Z. 1947): the parts must cover the whole act - a reading
        # that leaves a word of the act out ("... und küsse sie") is an incomplete check, never a complete permission
        return {**base, "status": "unbestaetigt:teile_unvollstaendig", "teile": [str(t.get("wortlaut"))[:80] for t in teile],
                "rest": rest[:80]}
    if not all(t.get("erbeten") is True for t in teile):
        return {**base, "status": "nicht_erbeten" if not any(t.get("erbeten") is True for t in teile) else "mehr_als_erbeten",
                "teile": [str(t.get("wortlaut"))[:80] for t in teile]}
    _ex = (entry.get("actorName"), entry.get("targetName"))
    if not all(_scene.covers_request(t.get("wortlaut"), [entry.get("bitte"), entry.get("bitteText")], _ex) for t in teile):
        # V65X (live 30.10.; AMASTER §36.1 Request bindet angefragte Handlung, §24.2 Z. 1113): every part read as the requested
        # act must name something of the request's own wording (same stem, names of the persons not counted)
        return {**base, "status": "unbestaetigt:teil_nennt_bitte_nicht", "teile": [str(t.get("wortlaut"))[:80] for t in teile]}
    return {**base, "erfuellt": True, "status": "validiert", "beleg": "; ".join(str(t.get("wortlaut")).strip() for t in teile)[:160],
            "teile": [str(t.get("wortlaut")).strip()[:160] for t in teile]}


def _input_acts_incomplete(ambiguous: Any) -> bool:
    """V65X (Nachpruefung V65W E05 "vollstaendige Handlungskomposition bei angenommenen Bitten"; live 30.10.: in "Ich nehme
    deine Hand und küsse sie" the planner's second act "ich küsse sie" was not found literally in the input, so only the hand
    was committed as an act and bound as the accepted request): an act of the speaker that the reading planned for NOW but
    the kernel could not locate in the input means the input's acts are not completely known - no act of this input is then
    bound to an accepted request (it stays unknown, visibly). Read only."""
    # V65Z (A04/A05): a reading cut at its token limit or an act segment that is no complete clause leaves the input's acts
    # not completely known as well
    return any(isinstance(a, dict) and a.get("grund") in ("segment_nicht_im_eingang", "lesung_abgeschnitten",
                                                           "segment_satz_unvollstaendig") for a in ambiguous or [])


def _bind_own_act_to_request(session: dict, fact: dict, readings: Any, *, turn: int) -> dict | None:
    """V65W (Tiefenpruefung v1 Punkt 9 / C7; AMASTER §36.1/§36.3, §36.5 Z. 1947 "an die betreffende Proposition oder
    Handlung gebunden", Z. 1975 "das tatsaechliche Stattfinden erzeugt rueckwirkend keine Acceptance"): the productive
    writer the V65T reducer rule 1 lacked - the requester's OWN act is bound to his request when (1) she accepted exactly
    that request before (accepted_requests_for: her lifecycle acceptance, same actor -> same person, not yet carried out)
    and (2) the act's own reading names it as exactly the requested act with a literal quote. Then act_consent reads the
    act as accepted (basis bitte). Once only: the request records the act as evidence "eigene_tat". Writer (session)."""
    if not isinstance(fact, dict) or fact.get("proposition_id") or fact.get("propositionId") or not _scene.validiert(fact):
        return None
    a, t = str(fact.get("actorId") or ""), str(fact.get("targetId") or "")
    ok = {str(e["propositionId"]): e for e in accepted_requests_for(session, a) if str(e.get("targetId") or "") == t}
    for v in readings if isinstance(readings, list) else []:
        if not (isinstance(v, dict) and v.get("erfuellt") is True and v.get("status") == "validiert"):
            continue
        # V65X (Nachpruefung V65W E05): the writer itself re-checks the recorded parts against the act's own Fact text -
        # an incomplete or non-literal decomposition never becomes a complete permission (no binding, the act stays unknown)
        _tl = v.get("teile") if isinstance(v.get("teile"), list) else []
        _lit, _rest = _teile_luecke(fact.get("text"), _tl) if _tl else (False, "")
        if not _lit or _rest:
            continue
        _e = ok.get(str(v.get("propositionId") or "")) or {}
        if not all(_scene.covers_request(x.get("wortlaut") if isinstance(x, dict) else x, [_e.get("bitte"), _e.get("bitteText")],
                                         (_e.get("actorName"), _e.get("targetName"))) for x in _tl):
            continue   # V65X (live 30.10.): the writer re-checks the request anchor too; V67: every word of the act
        pid = str(v.get("propositionId") or "")
        if pid not in ok:
            continue
        p = next(x for x in session.get("propositions") or [] if isinstance(x, dict) and str(x.get("id")) == pid)
        fact["proposition_id"] = pid
        fact["propositionId"] = pid
        p.setdefault("evidence", []).append({"kind": "eigene_tat", "factId": fact.get("id"), "by": a, "turn": int(turn or 0),
                                             "text": str(fact.get("text") or "")[:160], "beleg": str(v.get("beleg") or "")[:160]})
        return p
    return None


def _open_goal(session: dict, ref: Any) -> dict | None:
    key = str(ref or "").strip().strip("[]")
    if not key:
        return None
    return next((g for g in session.get("goals") or [] if isinstance(g, dict) and str(g.get("id") or "") == key
                 and g.get("status") in ("open", "active", "accepted")), None)


def _bind_act_to_goal(session: dict, fact: dict, ref: Any) -> dict | None:
    """V60 (AMASTER §35, §41.3, §34.1 "Goal pro Komponente"): the semantic
    planner may relate an act or answer to an open goal of the figure it is
    directed at. The kernel validates owner = target of the act, goal open.
    The binding is evidence for that goal; it decides nothing about its exit."""
    goal = _open_goal(session, ref)
    if goal is None or fact.get("goal_id") or fact.get("goalId"):
        return None
    owner = str(goal.get("ownerId") or "")
    if not owner or owner != str(fact.get("targetId") or "") or owner == str(fact.get("actorId") or ""):
        return None
    fact["goal_id"] = goal.get("id")
    fact["goalId"] = goal.get("id")
    return goal


_RULE_KINDS = ("handlung", "worte", "wiederholung", "zustand", "sonstiges", "keine")


def _store_rule_kinds(session: dict, user_plan: dict, rules: list[str], owner_id: str) -> dict | None:
    """V61: keep the validated condition kinds of the owner's authored rules
    (session-derived, provenance rule_kind_compile; never written to the stem).
    Invalid numbers/kinds are dropped; a goal link must be an open-or-closed
    session goal of the owner."""
    cand = user_plan.get("regelarten") if isinstance(user_plan, dict) else None
    if not isinstance(cand, dict) or str(cand.get("ownerId") or "") != owner_id or not isinstance(cand.get("rules"), list):
        return None
    import hashlib as _hl
    if str(cand.get("hash") or "") != _hl.sha256("\n".join(rules).encode("utf-8")).hexdigest()[:16]:
        return None
    goal_ids = {str(g.get("id")) for g in session.get("goals") or [] if isinstance(g, dict) and str(g.get("ownerId") or "") == owner_id}
    kept, seen = [], set()
    for r in cand["rules"]:
        if not isinstance(r, dict):
            continue
        try:
            nr = int(r.get("nr"))
        except (TypeError, ValueError):
            continue
        art = str(r.get("art") or "").strip().lower()
        if nr < 1 or nr > len(rules) or nr in seen or art not in _RULE_KINDS:
            continue
        seen.add(nr)
        try:
            mx = int(r.get("max")) if r.get("max") is not None else None
        except (TypeError, ValueError):
            mx = None
        # The goal link is an ID from the offered list; the model may echo the
        # whole list line, so only a contained session goal ID is taken.
        _m = re.search(r"goal_[A-Za-z0-9_]+", str(r.get("ziel") or ""))
        ziel = _m.group(0) if _m else None
        row = {"nr": nr, "art": art, "max": mx, "ziel": ziel if ziel in goal_ids else None}
        # V65b: a condition that names a PARTICULAR act or utterance ("kniet vor
        # ihr") is not fulfilled by every act of its kind; only kept when true.
        if r.get("bestimmt") is True:
            row["bestimmt"] = True
        kept.append(row)
    entry = {"hash": cand.get("hash"), "rules": kept, "provenance": "rule_kind_compile", "turn": int(session.get("turnIndex") or 0)}
    session.setdefault("ruleKinds", {})[owner_id] = entry
    return entry


def _bind_profile_triggers(session: dict, user_plan: dict, new_facts: list[dict], *, input_actor: str,
                           owner_id: str, present: list[dict] | None, turn: int) -> list[dict]:
    """V61 (AMASTER §15, §24, §34.1, §35, §41.3): rule x fact, like Prolog.

    The addressee's AUTHORED reaction rules (stem `reactionRules`, canonical
    projection) are conditions over events. Their condition kind is classified
    once (session.ruleKinds). The kernel then evaluates the kinds it owns from
    committed Facts of THIS input, in the system's own categories (§34.1):

        handlung(R)     :- validated action Fact of the counterpart at the owner
        worte(R)        :- speech Fact, no action Fact, and an open demand of
                           the owner to the counterpart
        wiederholung(R) :- the owner's open demand to the counterpart restated
                           at least max (default 2) times
        R linked to a goal is only live while that goal is open (§35).

    When several live rules share one kind, only the rule a neutral per-input
    check names with the SAME kind is bound. Kinds "zustand"/"sonstiges" are
    not evaluated (measured unreliable). No word list, no rule-text parsing,
    no consequence executed: the binding is evidence on the Fact and a
    Foreground candidate for the owner's own reply.
    """
    out: list[dict] = []
    if not owner_id or owner_id == input_actor:
        return out
    if owner_id == str(session.get("avatarId") or "") or owner_id not in set((session.get("scene") or {}).get("presentIds") or []):
        return out
    owner = next((c for c in (present or []) if isinstance(c, dict) and str(c.get("id") or "") == owner_id), None)
    if owner is None:
        return out
    from matrix_api.learning import canonical_stem as _cstem
    rules = [str(r).strip() for r in (_cstem(owner).get("reactionRules") or []) if str(r or "").strip()]
    if not rules:
        return out
    _store_rule_kinds(session, user_plan, rules, owner_id)
    import hashlib as _hl
    known = (session.get("ruleKinds") or {}).get(owner_id) if isinstance(session.get("ruleKinds"), dict) else None
    kinds = {int(r["nr"]): r for r in (known or {}).get("rules") or []} if (known or {}).get("hash") == _hl.sha256("\n".join(rules).encode("utf-8")).hexdigest()[:16] else {}
    mine = [f for f in new_facts if isinstance(f, dict) and str(f.get("actorId") or "") == input_actor
            and f.get("kind") in ("speech", "action") and _scene.validiert(f)]
    if not mine:
        return out
    acts = [f for f in mine if f.get("kind") == "action" and str(f.get("targetId") or "") == owner_id]
    any_act = any(f.get("kind") == "action" for f in mine)
    speech = next((f for f in mine if f.get("kind") == "speech"), None)
    demands = [p for p in session.get("propositions") or [] if isinstance(p, dict)
               and str(p.get("actorId") or "") == owner_id and str(p.get("targetId") or "") == input_actor
               and p.get("status") in ("open", "active")]
    goals = {str(g.get("id")): g for g in session.get("goals") or [] if isinstance(g, dict)}

    def _live(rule: dict) -> bool:
        gid = rule.get("ziel")
        return not gid or (goals.get(gid) or {}).get("status") in ("open", "active", "accepted")

    def _add(nr: int, art: str, ev: dict, prop: dict | None = None, goal: dict | None = None, source: str = "kernel_fact_kind") -> None:
        trig = {"ownerId": owner_id, "rule": nr, "art": art, "text": rules[nr - 1][:240],
                "propositionRef": prop.get("id") if prop else None, "goalRef": goal.get("id") if goal else None,
                "factId": ev.get("id"), "turn": int(turn or 0), "provenance": source}
        ev.setdefault("profileTriggers", []).append(trig)
        if goal is not None and not (ev.get("goal_id") or ev.get("goalId")):
            # The rule belongs to this goal of the owner: the evidencing Fact
            # is goal experience (§35). The exit stays the owner's decision.
            ev["goal_id"] = goal.get("id")
            ev["goalId"] = goal.get("id")
        out.append(trig)

    rows = user_plan.get("profilregeln") if isinstance(user_plan, dict) else None
    confirmed = set()
    # V65D (V61 stored the planner's component index on each action Fact so a
    # confirmation "reaches exactly this act's Fact"; the binder still took
    # acts[0]): the act the neutral check names (komponente) is the evidence.
    named_comp: dict[int, int] = {}
    for row in (rows if isinstance(rows, list) else []):
        try:
            _n = int(row.get("nr"))
        except (TypeError, ValueError, AttributeError):
            continue
        # A confirmation counts only if it names the same condition kind.
        if _n in kinds and str(row.get("art") or "") == str(kinds[_n].get("art")):
            confirmed.add(_n)
            _k = row.get("komponente")
            if isinstance(_k, int) and not isinstance(_k, bool):
                named_comp[_n] = _k
    # A condition kind shared by several live rules does not say WHICH rule
    # applies; those rules need the neutral per-input confirmation as well.
    shared: dict[str, int] = {}
    for rule in kinds.values():
        if _live(rule):
            shared[str(rule.get("art"))] = shared.get(str(rule.get("art")), 0) + 1
    for nr, rule in sorted(kinds.items()):
        if not _live(rule):
            continue
        goal = goals.get(rule.get("ziel") or "")
        art = rule.get("art")
        # V65b (measured 27.10., Tam: a unique "handlung" rule "Liefert Tom sich
        # ihr aus (... kniet ...)" was bound to a kiss): the kernel knows the
        # KIND of an act, not whether it is the particular act a condition
        # names. Such a rule ("bestimmt") needs the same neutral per-input
        # confirmation as rules sharing one kind.
        if art in ("handlung", "worte", "wiederholung") and (shared.get(art, 0) > 1 or rule.get("bestimmt")) and nr not in confirmed:
            continue
        if art == "handlung" and acts:
            named = next((f for f in acts if nr in named_comp and f.get("componentIndex") == named_comp[nr]), None)
            _add(nr, art, named or acts[0], goal=goal)
        elif art == "worte" and speech is not None and not any_act and demands:
            _add(nr, art, speech, prop=demands[-1], goal=goal)
        elif art == "wiederholung" and demands:
            limit = rule.get("max") if isinstance(rule.get("max"), int) and rule.get("max") > 0 else 2
            hit = next((p for p in reversed(demands) if sum(1 for e in p.get("evidence") or []
                                                           if isinstance(e, dict) and e.get("kind") == "restated") >= limit), None)
            if hit is not None:
                _add(nr, art, speech or mine[0], prop=hit, goal=goal)
    # V61 (measured, live run 5 of the 22:52 inputs): a per-input guess for
    # conditions of kind "sonstiges"/"zustand" named "Aggressiv bei Kritik" in
    # 6 of 8 turns, with the model's own reason "ist eine Eigenschaft und hat
    # keine Bedingung". Such conditions are therefore NOT evaluated by the
    # system; they stay in the figure's profile for her own reading.
    return out


def apply_owner_goal_decision(session: dict, *, actor_id: str, ref: Any, kind: str, fact_id: str | None, turn: int,
                              source_turn_id: str | None = None) -> dict | None:
    """V60 (AMASTER §35, §34.1): the OWNER's own validated statement that her
    open goal is reached is lifecycle evidence for that goal (append-only fact,
    reduced current state). Nobody else's words and no wording/turn count can
    close it; an unvalidated or unreferenced utterance changes nothing."""
    goal = _open_goal(session, ref)
    if goal is None or str(goal.get("ownerId") or "") != str(actor_id) or kind != "acceptance":
        return None
    if goal.get("proposition_id") or goal.get("propositionId"):
        return None  # a request goal follows its Proposition lifecycle
    lf = make_fact(turn=int(turn or 0), actorId=str(actor_id), targetId=None, kind="lifecycle", event_kind="fulfill",
                   speech_act=None, text=str(goal.get("text") or "")[:160], authority="character",
                   # V66 (Audit5 E04; AMASTER §34 Quellturn, §34.1): the fulfilment is a component of her statement - its
                   # Quellturn (V65Z wrote None; under the V66 write boundary a fact without Quellturn is refused)
                   sourceTurnId=fact_provenance(session, fact_id).get("sourceTurnId") or source_turn_id or None,
                   goal_id=goal.get("id"), responds_to_fact_id=fact_id, validated=True,
                   payload={"kind": "lifecycle", "lifecycle": "fulfill", "goal_id": goal.get("id"), "decided_by": "owner"})
    lf["goalId"] = goal.get("id")
    lf["sessionId"] = session.get("id")
    lf["worldId"] = session.get("worldId")
    lf["userId"] = session.get("userId")
    session.setdefault("facts", []).append(lf)
    goal["status"] = "fulfilled"
    goal["lifecycleFactId"] = lf["id"]
    goal["lifecycleTurn"] = int(turn or 0)
    return goal


def disclosure_candidates(session: dict, owner_id: str, recipient_id: str, *, source_turn_id: str = "", plan: Any = None) -> list[dict]:
    """V65H (AMASTER §34.1, §35): her goals whose frame names exactly the person she
    now answers as the one who does not know yet (not yet disclosed) — checked when
    THIS turn addressed it (validated Themenbezug) or her own plan reads her speech
    as a disclosure / knowledge transition. Read only."""
    plan = plan if isinstance(plan, dict) else {}
    own_disc = (plan.get("event_kind") == "disclosure" or plan.get("speech_act") == "disclose"
                or plan.get("durability") == "knowledge_transition")
    turn_facts = {str(f.get("id")) for f in session.get("facts") or [] if isinstance(f, dict)
                  and source_turn_id and str(f.get("sourceTurnId") or "") == str(source_turn_id)}
    out = []
    for g in goal_theme_candidates(session, owner_id, recipient_id):
        # V65L: a validated Antwortbezug (his answer to her line of the bound exchange) touches it as well.
        touched = any(isinstance(e, dict) and e.get("via") in ("themenbezug", "antwortbezug") and str(e.get("sourceFactId") or "") in turn_facts
                      for e in g.get("recentExperiences") or [])
        if touched or own_disc:
            out.append(g)
    return out


def apply_owner_disclosure(session: dict, *, actor_id: str, goal_id: Any, fact: dict, turn: int, beleg: Any) -> dict | None:
    """V65H (AMASTER §34.1 "eine Offenbarung" als eigene Komponente, §35 Current
    State aus neuester Evidenz, §39; 171 KONJ-1 Offenbarungsstatus /
    goal_records completion 'disclosure'): HER validated speech that, by a model
    reading with a literal quote (llm_contract.goal_disclosure_check), says the
    unsaid part of her goal to exactly the person the goal frame names, is
    recorded on that goal (who, fact, turn) with an append-only lifecycle fact.
    The goal stays open — what it says stays true; only "not yet told to X" is
    superseded. The kernel checks owner, frame person = addressee of the speech,
    not yet disclosed, and that the quote is literally in her speech."""
    gid = re.search(r"goal_[A-Za-z0-9_]+", str(goal_id or ""))
    goal = _open_goal(session, gid.group(0) if gid else "")
    if goal is None or str(goal.get("ownerId") or "") != str(actor_id) or not _scene.validiert(fact):
        return None
    target = str(fact.get("targetId") or "")
    fr = goal.get("frame") if isinstance(goal.get("frame"), dict) else {}
    if not target or target == str(actor_id) or str(fr.get("wer") or "") != target or not fr.get("ungesagt"):
        return None
    q = " ".join(str(beleg or "").split())
    if not q or q.casefold() not in " ".join(str(fact.get("text") or "").split()).casefold():
        return None
    rows = goal.setdefault("disclosedTo", [])
    if any(isinstance(d, dict) and str(d.get("targetId") or "") == target for d in rows):
        return None
    lf = make_fact(turn=int(turn or 0), actorId=str(actor_id), targetId=target, kind="lifecycle", event_kind="disclose",
                   speech_act=None, text=str(fr.get("ungesagt") or goal.get("text") or "")[:160], authority="character",
                   # V65Y (AMASTER §34.1 "Alle Komponenten desselben Outputs tragen dieselbe source_turn_id"; Gesamtpruefung
                   # V65X N01): the disclosure is a component of her speech - same Quellturn (was None)
                   sourceTurnId=fact_provenance(session, fact.get("id")).get("sourceTurnId") or fact.get("sourceTurnId") or None,
                   goal_id=goal.get("id"), responds_to_fact_id=fact.get("id"), validated=True,
                   payload={"kind": "lifecycle", "lifecycle": "disclose", "goal_id": goal.get("id"), "recipient": target,
                            "beleg": q[:120], "decided_by": "owner"})
    lf["goalId"] = goal.get("id")
    lf["sessionId"] = session.get("id")
    lf["worldId"] = session.get("worldId")
    lf["userId"] = session.get("userId")
    session.setdefault("facts", []).append(lf)
    rows.append({"targetId": target, "factId": fact.get("id"), "lifecycleFactId": lf["id"], "turn": int(turn or 0), "beleg": q[:120]})
    return goal


def _goal_hash(goal: dict) -> str:
    import hashlib as _hl
    return _hl.sha256(str(goal.get("text") or "").encode("utf-8")).hexdigest()[:16]


def goal_frames_needed(session: dict, owner_id: str) -> list[dict]:
    """V65H (AMASTER §40): the owner's open stem goals whose frame is missing or
    belongs to another goal text (hash). Read only."""
    return [g for g in session.get("goals") or [] if isinstance(g, dict) and str(g.get("ownerId") or "") == str(owner_id)
            and g.get("kind") == "stamm" and g.get("status") in ("open", "active", "accepted") and str(g.get("text") or "").strip()
            and not (g.get("proposition_id") or g.get("propositionId"))
            and (g.get("frame") or {}).get("hash") != _goal_hash(g)]


def _cast_named_in(natives: list[dict] | None, name: Any, text: str, owner_id: str) -> str | None:
    """V65H (AMASTER §24.2 Namens-/Entity-Verankerung): the ONE cast member the
    model's ``name`` denotes AND whose own name or alias occurs in ``text`` (the
    goal). No vocabulary — names and aliases come from the figures' data."""
    want = _fold_space(name)
    if not want:
        return None
    words = {_fold_space(w) for w in re.findall(r"[^\W\d_]{3,}", str(text or ""))}
    hits = set()
    for c in natives or []:
        if not isinstance(c, dict) or not c.get("id") or str(c["id"]) == str(owner_id):
            continue
        labels = [str(c.get("name") or "")] + [str(a) for a in (c.get("aliases") or []) if a]
        toks = {_fold_space(t) for lab in labels for t in re.findall(r"[^\W\d_]{3,}", lab)}
        if (want in {_fold_space(lab) for lab in labels if lab} or want in toks) and toks & words:
            hits.add(str(c["id"]))
    return next(iter(hits)) if len(hits) == 1 else None


def apply_goal_frames(session: dict, owner_id: str, result: Any, natives: list[dict] | None) -> list[dict]:
    """V65H (AMASTER §40 Konjunktives Gedächtnis: Wer/Was/Wem, Wissende/Nicht-
    wissende; §24.2/§50 Validierung; 171 KONJ-1B Goal-Frame ohne dessen Regex):
    which part of her stem goal its own text marks as still unsaid, and to whom.
    Kept on the session goal with the text hash — a derived reading of author
    data, never the Stamm and never a new world fact. Kept only when the unsaid
    part is grounded in the goal text and the person is a cast member named in
    it. Without a model result nothing is written (asked again next time)."""
    if not isinstance(result, dict) or not isinstance(result.get("rahmen"), list):
        return []
    rows: dict[str, dict] = {}
    for r in result["rahmen"]:
        if isinstance(r, dict):
            m = re.search(r"goal_[A-Za-z0-9_]+", str(r.get("id") or ""))
            if m:
                rows[m.group(0)] = r
    proto = []
    for g in goal_frames_needed(session, owner_id):
        r = rows.get(str(g.get("id")))
        frame: dict[str, Any] = {"hash": _goal_hash(g), "source": "zielrahmen", "ungesagt": None, "wer": None, "thema": None}
        if r and r.get("ungesagt"):
            _gt = " ".join(str(g.get("text") or "").split())
            _hw = " ".join(str(r.get("hinweis") or "").split()).strip(" .,;")
            # the goal text itself must say it is unsaid: the model's quote of that
            # passage has to be literally in the goal text (no vocabulary of ours)
            _hw_ok = bool(_hw) and _hw.casefold() in _gt.casefold()
            _ung = " ".join(str(r.get("ungesagt") or "").split())
            if _hw_ok and _hw.casefold() in _ung.casefold():          # the "not yet said" passage is no content
                _i = _ung.casefold().index(_hw.casefold())
                _ung = (_ung[:_i] + _ung[_i + len(_hw):]).strip(" ,;")
                _ung = _ung if _ung.endswith((".", "!", "?")) else _ung + "."
            ung = _grounded_in(_ung, _gt)
            wer = _cast_named_in(natives, r.get("wer_weiss_es_nicht"), _gt, str(owner_id))
            if ung and wer and _hw_ok:
                frame.update({"ungesagt": ung, "wer": wer, "hinweis": _hw,
                              "thema": _grounded_in(str(r.get("thema") or ""), _gt, short=True) or None})
            else:
                frame["verworfen"] = ("hinweis_nicht_im_zieltext" if not _hw_ok else "nicht_im_zieltext" if not ung
                                      else "person_nicht_im_zieltext")
        g["frame"] = frame
        proto.append({"goalId": g.get("id"), **{k: frame.get(k) for k in ("ungesagt", "wer", "thema", "verworfen")}})
    return proto


def goal_theme_candidates(session: dict, owner_id: str, actor_id: str) -> list[dict]:
    """V65H: her open goals whose current frame names exactly this actor as the
    one who does not know yet, and not yet disclosed to him (§35 Current State)."""
    return [g for g in session.get("goals") or [] if isinstance(g, dict) and str(g.get("ownerId") or "") == str(owner_id)
            and g.get("status") in ("open", "active", "accepted") and isinstance(g.get("frame"), dict)
            and g["frame"].get("ungesagt") and str(g["frame"].get("wer") or "") == str(actor_id)
            and g["frame"].get("hash") == _goal_hash(g)
            and not any(isinstance(d, dict) and str(d.get("targetId") or "") == str(actor_id) for d in g.get("disclosedTo") or [])][:2]


def apply_goal_theme(session: dict, owner_id: str, actor_id: str, source_turn_id: str, goal_id: str, result: Any) -> dict:
    """V65H (AMASTER §41.1 Immediate Stimulus "ausdrücklich adressierte
    Proposition", §40, §41/§49.1; 171 KONJ-1A Cue + KONJ-1C Partner-Vertrag ohne
    Wortliste): the model only says whether THIS input addresses exactly the
    unsaid part and quotes the words. The kernel checks candidate goal (frame,
    person = actor, not yet disclosed), the input fact (this turn, actor -> her,
    validated) and that the quote is literally in the input, then binds the
    input fact as goal experience. Relevance only — no exit, no duty."""
    goal = next((g for g in goal_theme_candidates(session, owner_id, actor_id) if str(g.get("id")) == str(goal_id)), None)
    if goal is None:
        return {"status": "kein_kandidat"}
    fact = next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict)
                 and str(f.get("sourceTurnId") or "") == str(source_turn_id) and str(f.get("actorId") or "") == str(actor_id)
                 and str(f.get("targetId") or "") == str(owner_id) and f.get("kind") in ("speech", "action")
                 and _scene.validiert(f)), None)
    if fact is None:
        return {"status": "kein_eingangsfakt"}
    if not isinstance(result, dict) or result.get("angesprochen") is not True:
        return {"status": "nicht_angesprochen"}
    beleg = " ".join(str(result.get("beleg") or "").split())
    if not beleg or beleg.casefold() not in " ".join(str(fact.get("text") or "").split()).casefold():
        return {"status": "beleg_nicht_in_aeusserung", "beleg": beleg[:80]}
    fr = goal["frame"]
    out = apply_goal_experience(session, str(owner_id), fact, turn=int(fact.get("turn") or 0), goal_id=str(goal_id), reading={
        "via": "themenbezug", "gemeint": True, "unausgesprochen": True, "wahrheit": fr.get("ungesagt"),
        "thema": fr.get("thema"), "anlass": " ".join(str(result.get("thema") or "").split())[:60] or None, "beleg": beleg[:120]})
    return {"status": "gebunden" if out.get("goals") else "bindung_abgelehnt", "factId": fact.get("id"), "beleg": beleg[:80]}


# V65L (AMASTER §25 Zielbindung "letzten Sprecher, adressierte Frage … bestehende Turnbindung", §34 Antwortbezug,
# §34.1 responds_to je Komponente / Folgeturn als Fortsetzung des gebundenen Zustands, §41.1, §68 Nr. 35; Kettenvertrag
# §6.5 erste falsche Naht): his next input that answers HER line of an exchange already bound to her unsaid goal part.
# Structure decides which line he answers and that its exchange is bound; only whether he answers its theme part is read.
ANSWER_KINDS = ("zustimmung", "ablehnung", "rueckfrage", "aufforderung")


def _input_fact(session: dict, source_turn_id: str, actor_id: str, owner_id: str) -> dict | None:
    return next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict)
                 and str(f.get("sourceTurnId") or "") == str(source_turn_id) and str(f.get("actorId") or "") == str(actor_id)
                 and str(f.get("targetId") or "") == str(owner_id) and f.get("kind") in ("speech", "action")
                 and _scene.validiert(f)), None)


def answer_continuation(session: dict, owner_id: str, actor_id: str, source_turn_id: str, goal_id: str) -> dict | None:
    """Read only. The line his input answers (_answered_line_facts) is HER line toward him, and its exchange (same
    sourceTurnId) holds his fact bound to this still unsaid goal (via themenbezug or antwortbezug). Returns her fact
    (speech preferred), the bound fact it continues, and his input fact; else None."""
    goal = next((g for g in goal_theme_candidates(session, owner_id, actor_id) if str(g.get("id")) == str(goal_id)), None)
    fact = _input_fact(session, source_turn_id, actor_id, owner_id)
    if goal is None or fact is None:
        return None
    line = [f for f in _answered_line_facts(session, actor_id, str(fact.get("id"))) if _scene.validiert(f)]
    if not line or any(str(f.get("actorId") or "") != str(owner_id) for f in line):
        return None
    her = next((f for f in line if f.get("kind") == "speech" and str(f.get("text") or "").strip() not in ("", "—")), None) \
        or next((f for f in line if f.get("kind") == "action" and str(f.get("text") or "").strip()), None)
    if her is None or str(her.get("targetId") or "") != str(actor_id):
        return None
    exchange = {str(f.get("id")) for f in session.get("facts") or [] if isinstance(f, dict)
                and str(f.get("sourceTurnId") or "") == str(her.get("sourceTurnId") or "") and str(f.get("actorId") or "") == str(actor_id)}
    bound = next((e for e in reversed(goal.get("recentExperiences") or []) if isinstance(e, dict)
                  and e.get("via") in ("themenbezug", "antwortbezug") and str(e.get("sourceFactId") or "") in exchange), None)
    if bound is None:
        return None
    return {"goal": goal, "herFact": her, "boundFactId": str(bound.get("sourceFactId")), "bound": bound, "fact": fact}


def apply_answer_reference(session: dict, owner_id: str, actor_id: str, source_turn_id: str, goal_id: str, her_fact_id: str,
                           result: Any) -> dict:
    """Writer check for the Antwortbezug reading (llm_contract.answer_reference_check): the continuation is re-derived
    from the stored state (same her line, same bound exchange), the reading must say he answers its theme part with an
    allowed kind and quote both his and her words literally. Then HIS fact is bound to the goal with both references
    (antwortAuf = her fact, fortsetzungVon = the bound fact). Relevance only — no exit, no duty, no disclosure."""
    cont = answer_continuation(session, owner_id, actor_id, source_turn_id, goal_id)
    if cont is None:
        return {"status": "kein_fortsetzungsfall"}
    if str(cont["herFact"].get("id")) != str(her_fact_id):
        return {"status": "andere_zeile"}
    if not isinstance(result, dict) or result.get("antwortet") is not True:
        return {"status": "keine_antwort_darauf"}
    art = str(result.get("art") or "").strip().lower()
    if art not in ANSWER_KINDS:
        return {"status": f"art_{art[:20] or 'leer'}"}
    _norm = lambda v: " ".join(str(v or "").split())
    b_his, b_her = _norm(result.get("beleg_aeusserung")), _norm(result.get("beleg_ihre_zeile"))
    if not b_his or b_his.casefold() not in _norm(cont["fact"].get("text")).casefold():
        return {"status": "beleg_nicht_in_aeusserung", "beleg": b_his[:80]}
    if not b_her or b_her.casefold() not in _norm(cont["herFact"].get("text")).casefold():
        return {"status": "beleg_nicht_in_ihrer_zeile", "beleg": b_her[:80]}
    fr = cont["goal"]["frame"]
    out = apply_goal_experience(session, str(owner_id), cont["fact"], turn=int(cont["fact"].get("turn") or 0), goal_id=str(goal_id), reading={
        "via": "antwortbezug", "gemeint": True, "unausgesprochen": True, "wahrheit": fr.get("ungesagt"), "thema": fr.get("thema"),
        "anlass": cont["bound"].get("anlass"), "beleg": b_his[:120], "antwortAuf": str(cont["herFact"].get("id")),
        "belegIhreZeile": b_her[:120], "art": art, "fortsetzungVon": cont["boundFactId"]})
    return {"status": "gebunden" if out.get("goals") else "bindung_abgelehnt", "factId": cont["fact"].get("id"),
            "antwortAuf": cont["herFact"].get("id"), "fortsetzungVon": cont["boundFactId"], "art": art}


def _restate_request(session: dict, prop: dict, *, actor_id: str, fact_id: str | None, text: str, turn: int) -> None:
    """V60 (AMASTER §35, §41.3 "Wiederholung"): the requester asks for the
    SAME open matter again. Same Proposition, new evidence — no new request."""
    prop.setdefault("evidence", []).append({"kind": "restated", "factId": fact_id, "by": actor_id,
                                            "turn": int(turn or 0), "text": str(text or "")[:160]})
    for f in session.get("facts") or []:
        if isinstance(f, dict) and fact_id and f.get("id") == fact_id:
            f["proposition_id"] = prop.get("id")
            f["propositionId"] = prop.get("id")


def _add_request_proposition(
    session: dict,
    *,
    actor_id: str,
    text: str,
    target_id: str | None,
    time_window: str | None = None,
) -> dict:
    props = session.setdefault("propositions", [])
    goals = session.setdefault("goals", [])
    turn = int(session.get("turnIndex") or 0)
    pid = _next_id("prop", session)
    props.append(
        {
            "id": pid,
            "text": text,
            "status": "open",
            "actors": [actor_id] + ([target_id] if target_id else []),
            "turn": turn,
            "actorId": actor_id,
            "targetId": target_id,
            "time_window": time_window,
        }
    )
    goals.append(
        {
            "id": _next_id("goal", session),
            "ownerId": actor_id,
            "recipientId": target_id,
            "text": text,
            "status": "open",
            "proposition_id": pid,
            "priority": 0,
            "time_window": time_window,
            "layer": "session",
        }
    )
    return props[-1]


def _collect_fate_proposal(result: dict) -> Any:
    bits: list[Any] = []
    if result.get("fate") not in (None, ""):
        bits.append(result.get("fate"))
    for p in result.get("components") or []:
        if isinstance(p, dict) and (p.get("kind") == "fate" or p.get("event_kind") == "fate"):
            bits.append(p.get("text") or p)
    if not bits:
        return None
    if len(bits) == 1:
        return bits[0]
    return bits


def unanswered_appraisal_causes(session: dict, speaker_id: str, *, before_turn: int) -> list[str]:
    """Read-only causality join: which already-appraised foreign Facts happened
    after this figure's previous own line, before the reply being committed?

    The input and answer may have DIFFERENT TurnTruth IDs (Puppet/AutoChat).
    Do not use an answer's sourceTurnId as evidence of the preceding input.
    Derive from canonical Facts, appraisalCauses and the persisted turn order;
    no second flag/owner in RuntimeState. Unknown legacy ordering grants nothing.
    """
    sid = str(speaker_id or "")
    last_own = max((int(t.get("turn")) for t in (session.get("turns") or [])
                    if isinstance(t, dict) and str(t.get("speakerId") or "") == sid
                    and str(t.get("turn") or "").isdigit()
                    and int(t.get("turn")) < before_turn), default=0)
    rt = (session.get("runtimes") or {}).get(sid) or {}
    approved = {str(x) for x in (rt.get("appraisalCauses") or []) if x}
    if not approved:
        return []
    return list(dict.fromkeys(str(f.get("id")) for f in (session.get("facts") or [])
        if isinstance(f, dict) and str(f.get("id") or "") in approved
        and str(f.get("actorId") or "") != sid
        and f.get("kind") in ("speech", "action", "physical")
        and _scene.validiert(f)
        and str(f.get("turn") or "").isdigit()
        and last_own < int(f["turn"]) <= before_turn))


def is_figure_followup_turn(truth: dict | None) -> bool:
    """True only for a response turn, with no new user speech.

    AMASTER §27.8 / §28: God/Regie/Puppet may leave a scene event that
    a character reacts to. The reaction is the character's own turn,
    never another God/Regie/observer act. The normal kernel route still
    validates the selected speaker against canonical session presence.
    """
    row = truth if isinstance(truth, dict) else {}
    kind = str(row.get("input_kind") or row.get("inputKind") or "").strip().lower()
    return kind == "autochat" and not str(row.get("text") or "").strip()


def commit_turn(
    session: dict,
    *,
    truth: dict,
    speaker: dict,
    present: list[dict],
    result: dict,
    fired: list[dict] | None = None,
    accept_llm_state: bool = False,
    world: dict | None = None,
    proposals: dict | None = None,
    recall_count: int | None = None,
    user_plan: dict | None = None,
    contradictions: list[dict] | None = None,
    phase: str = "complete",
    koerper_lesung: dict | None = None,
) -> dict:
    """Canonical commit. Normal calls remain atomic; two-phase UI turns use
    input (before formulation) then response (same TurnTruth/turn number).
    Both phases write the existing session/children SQLite owners.
    V92 Paket 18: `koerper_lesung` = the SERVER's reading of the change the figure's action makes to her own body
    (llm_contract.koerper_check, read by the commit route); without it the figure's action changes nothing on her body.
    """
    if phase not in ("complete", "input", "response"):
        raise ValueError("unknown commit phase")
    s = copy.deepcopy(session)
    input_only = phase == "input"
    response_only = phase == "response"
    if response_only:
        source = str(truth.get("id") or "")
        if not source or s.get("pendingInputTurnId") != source:
            raise ValueError("response without matching committed input")
        stored_truth = next((row for row in (s.get("turnTruths") or []) if row.get("id") == source), None)
        if not isinstance(stored_truth, dict):
            raise ValueError("committed input TurnTruth missing")
        if str(stored_truth.get("speaker_id") or "") != str(speaker.get("id") or ""):
            raise ValueError("response speaker differs from committed TurnTruth")
        truth = dict(stored_truth)
        turn = int(s.get("turnIndex") or 0)
        # User input is already committed; do not write it a second time.
        truth["text"] = ""
        # Stand 08 / K-02 (AMASTER §26 "Anwesenheit ist ein kanonischer Szenenzustand", §39, §28 Schritt 5): the RESPONSE is
        # its own event - who is present, hears and sees it is bound from the SceneState at the time of the response, not
        # copied from the input's TurnTruth. Between input and response the scene can change (a figure leaves, falls
        # asleep, an override is set; the open input is answered later via "Antwort erneut erzeugen"). The stored input
        # TurnTruth keeps its own perception (history); only this response's writers (witness, memory, dialogue mirror,
        # claims/frames) read the response-time perception. Same owner as prepare (_scene_perception).
        _pres_now = list((s.get("scene") or {}).get("presentIds") or [])
        _hears_now, _sees_now = _scene_perception(s, _pres_now)
        truth["present_ids"], truth["hears_ids"], truth["sees_ids"] = _pres_now, list(_hears_now), list(_sees_now)
    else:
        if s.get("pendingInputTurnId"):
            raise ValueError("previous input awaits its response")
        s["turnIndex"] = next_turn_index(s)
        turn = s["turnIndex"]
        source = truth["id"]
        attach_turn_truth(s, truth)
        if input_only:
            s["pendingInputTurnId"] = source
    avatar_id = truth.get("avatar_id")
    input_actor = str(truth.get("input_actor_id") or default_input_actor_id(truth) or avatar_id or "user")
    # V63 (§24.1, §68 Nr. 51): the input actor's name in the dialogue line and in
    # the witnesses' memories — the avatar's identity name (one owner), the
    # operator's user name otherwise (unchanged).
    _input_name = (avatar_identity_name(s, present) if avatar_id and input_actor == str(avatar_id)
                   else operator_label(s, truth, present) if input_actor in _OPERATOR_IDS
                   else _name_of(input_actor, present, s))
    skip_figure = (
        str(truth.get("authority") or "") == "observer"
        or str(truth.get("role") or "") in ("beobachter",)
        or str(truth.get("input_kind") or "") in ("comment", "observer")
    )
    # AMASTER §28 / Kettenvertrag §6: never silently consume an actual
    # model response as an observer comment. This previously advanced the
    # Regie follow-up turn and dropped Mara's speech/action without a Fact.
    if skip_figure and isinstance(result, dict) and (
        str(result.get("speech") or "").strip()
        or str(result.get("action") or "").strip()
    ):
        raise ValueError("FIGURE_RESPONSE_AS_OBSERVER: generated figure output cannot be committed as observer")
    new_facts: list[dict] = []
    # R3.4 / B.7-Folge: Pre-Bind Time-Disambig, damit Speech-Facts
    # den time_tense/time_ambiguous kennen BEVOR Drift-Facts (B.4)
    # geschrieben werden. Wenn die Speech-Zeit past/ambiguous ist,
    # unterdrücken wir Runtime/Relationship-Drift, weil Vergangenheit
    # keine neuen Commitments auslösen darf (§37).
    _pre_text = truth.get("text") or ""
    _pre_speech, _pre_action = split_star_action(_pre_text)
    _pre_time = (copy.deepcopy(s.get("time") or {}) if response_only else bind_time(
        s,
        source_turn_id=source,
        relative=_pre_speech or _pre_text or None,
    ))
    _pre_tense = _pre_time.get("tense")
    _pre_ambiguous = _pre_time.get("ambiguous")
    _pre_past = _pre_tense == "past" or bool(_pre_ambiguous)
    # V57: resolve the input BEFORE selecting any Fact/Memory/effect writer.
    # The envelope input_kind describes the UI route, not the semantic event.
    # A validated semantic plan must not be attached to an already-wrong Fact.
    input_plan = None
    input_speech, input_action = None, None
    input_actions: list[dict] | None = None   # V59C validated action components
    input_component_diag: dict = {}
    _speech_target = truth.get("target_id")   # V92 Paket 14: the speech's addressee (its own words may name another one)
    if not response_only and not skip_figure and truth.get("text") and truth.get("input_kind") in ("speech", "user"):
        raw_input = str(truth["text"])
        if isinstance(user_plan, dict):
            input_plan = _conj.normalize_plan(
                user_plan, actor_id=input_actor,
                recipient_id=str(truth.get("target_id") or "") or None,
                text=raw_input, now=_session_now(s),
                present_ids=list((s.get("scene") or {}).get("presentIds") or []),
                figures=present,
            )
            if input_plan is None:
                input_plan = _conj.literal_plan(raw_input, actor_id=input_actor,
                    recipient_id=str(truth.get("target_id") or "") or None)
        else:
            # Existing explicit offline/direct-kernel caller compatibility.
            input_plan = _conj.local_plan(raw_input, actor_id=input_actor,
                recipient_id=str(truth.get("target_id") or "") or None, now=_session_now(s))
        marked_speech, marked_action = _split_star_marker(raw_input)
        # V59C (AMASTER §24.2/§34.1/§24.7): the planner's components are the
        # primary reading. One wrong plan label can no longer swallow an act.
        raw_components = user_plan.get("komponenten") if isinstance(user_plan, dict) else None
        component_binding = None
        if isinstance(raw_components, list) and raw_components:
            actor_fig = next((f for f in (present or []) if isinstance(f, dict) and str(f.get("id") or "") == input_actor), None)
            component_binding = bind_input_components(
                raw_input, raw_components, actor_id=input_actor,
                # V92 Paket 11 (Paket-10-Pruefung; §8, §27.2): a figure actor is that figure - its name, aliases and session
                # names; the user name and the session alias label the control, not the figure (only the operator has them)
                actor_names=([str(actor_fig.get("name") or "")] + list(actor_fig.get("aliases") or []) + list(actor_fig.get("sessionAliases") or [])
                             if actor_fig else [str(truth.get("user_name") or ""), str(s.get("alias") or ""),
                                                # V92 Paket 13: the canonical operator label the input reading was given (app._extract_user_plan)
                                                *( [operator_label(s, truth, present)] if input_actor in _OPERATOR_IDS else [] )]),
                figures=present,
                present_ids=list((s.get("scene") or {}).get("presentIds") or []),
                default_target=(str(truth.get("target_id")) if truth.get("target_id") else None),
                text_tense=_pre_tense if not _pre_ambiguous else "ambiguous",
                cut=bool(user_plan.get("_abgeschnitten")),
            )
            input_component_diag = {k: component_binding[k] for k in ("ambiguous",) if component_binding.get(k)}
        # V92 (Paket-8-Pruefung C1-C4; AMASTER §27.3 "Das System erzeugt fuer den Avatar nicht selbststaendig Rede ... koerperliche
        # Handlung", §24.2, §24.7, §34.1; Kettenvertrag §6): ONE rule for the avatar input, with the SAME owners as the puppet input
        # (bind_input_components -> input_binding_outcome). The avatar stores exactly the validated own
        # speech and the validated own acts of the reading; a rejected or foreign component is never re-labelled as the avatar's
        # speech, a marker never re-adds a rejected act, and no act is made from a whole-input label or a marker without a
        # validated component (before: `current_action`, the "everything typed is speech" rest and the substitute act).
        # Without any reading (no provider: the route's literal_plan, or a direct kernel caller without plan) the typed text
        # outside a marker is the avatar's own direct speech - the input field is the user's speech (§27.3 "vom Nutzer");
        # a marked act cannot be checked there (denied? whose?) and is not stored.
        _no_reading = not isinstance(user_plan, dict) or str(user_plan.get("validation_status") or "") == "source_only"
        _extra: list[dict] = []
        if component_binding is not None:
            _amb = list(component_binding.get("ambiguous") or [])
            _res = input_binding_outcome(component_binding, _amb, raw_input)
            _extra = [a for a in (_res.get("ambiguous") or []) if a not in _amb]
        elif _no_reading:
            # the text outside ALL markers is the avatar's direct speech; no marked act can be checked without a reading
            _off = (marked_speech if marked_action is not None else raw_input) or ""
            _off = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s+", " ", _off)).strip()   # the gaps the removed markers leave
            _res = {"speech": _off, "actions": []}
            _extra = [{"segment": _t[:160], "grund": "plan_fehlt", "vorschlag": {"typ": "handlung", "segment": _t[:160]}}
                      for _a, _b, _t in marker_spans(raw_input)]
        else:
            # a model reading without its components (the contract demands them): incomplete, as on the puppet path
            _res = {"speech": "", "actions": []}
            _extra = [{"segment": raw_input[:160], "grund": "zerlegung_unvollstaendig"}]
        if _extra:
            input_component_diag = {"ambiguous": list(input_component_diag.get("ambiguous") or []) + _extra}
        # An unresolved, explicitly named person is an unexecuted proposal,
        # never an actor's completed targetless deed in the world/Memory.
        input_actions = [dict(a) for a in (_res.get("actions") or [])
                         if isinstance(a, dict) and str(a.get("text") or "").strip()
                         and not a.get("targetBindingInvalid")]
        input_speech = str(_res.get("speech") or "").strip() or None
        _in_rt0 = (s.get("runtimes") or {}).get(str(input_actor))
        if input_speech and isinstance(_in_rt0, dict) and not can_speak_now(_in_rt0):
            # V92 Paket 19 (Pruefung P18 N2; AMASTER §43 Capability, §27.3): the avatar figure that sleeps, is unconscious,
            # gagged or mute speaks no words now - the same rule as for a figure's reply and the puppet. Its words stay visible
            # as not executable (no speech Fact); with nothing else executable the route writes nothing and says why.
            input_component_diag = {"ambiguous": list(input_component_diag.get("ambiguous") or [])
                                    + [{"segment": input_speech[:160], "grund": "kann_jetzt_nicht_sprechen",
                                        "vorschlag": {"typ": "rede", "segment": input_speech[:160]}}]}
            input_speech = None
        if not input_speech and input_actions and isinstance(_in_rt0, dict):
            # V92 Paket 19 (Pruefung P18 "blockierte Turns"): nothing of the input can be carried out with the body state at the
            # start of the turn (asleep: only her own validated waking; unconscious: nothing) - the input is not executable as a
            # whole; the route writes nothing and says why (as the puppet route). One act that can be carried out keeps the turn.
            _in_fig = next((f for f in (present or []) if isinstance(f, dict) and str(f.get("id") or "") == str(input_actor)), None)
            _gesperrt = [a for a in input_actions
                         if act_capability(_in_rt0, str(a.get("text") or "").strip(),
                                           *own_body_change(a.get("koerperPruefung"), str(a.get("text") or "").strip()),
                                           names=_figure_name_forms(_in_fig) if _in_fig else [])[0] is not None]
            if len(_gesperrt) == len(input_actions):
                input_component_diag = {"ambiguous": list(input_component_diag.get("ambiguous") or [])
                                        + [{"segment": str(a.get("text") or "")[:160], "grund": "koerper_laesst_es_nicht_zu",
                                            "vorschlag": {"typ": "handlung", "segment": str(a.get("text") or "")[:160]}} for a in _gesperrt]}
                input_actions = []
        if input_speech and _res.get("speechTargetSet"):
            # V92 Paket 14 (Entscheidung 1): the addressee the speech names in its own words outranks the selected recipient
            _speech_target = _res.get("speechTarget") or None
        input_action = " ".join(str(a["text"]) for a in input_actions) or None   # Stand 11D: Textreihenfolge, wie geschrieben
        if input_actions and not input_speech:
            input_plan = {**input_plan, "event_kind": "action", "speech_act": "act"}
        elif not input_actions and input_plan.get("event_kind") == "action":
            # no act of this input was validated: the plan's whole-input "action" label describes no stored act
            input_plan = {**input_plan, "reported_event_kind": "action",
                          "event_kind": "report", "speech_act": "report",
                          "durability": "utterance"}
        # nothing validated: the route writes nothing and shows why (input_event_kind "nicht_ausfuehrbar", kernel_prepare/commit)
        resolved = ("speech_action" if input_speech and input_action else ("action" if input_action else
                    ("speech" if input_speech else "nicht_ausfuehrbar")))
        for stored in s.get("turnTruths") or []:
            if stored.get("id") == source:
                stored["input_event_kind"] = resolved
                if input_component_diag:
                    stored["input_component_ambiguity"] = copy.deepcopy(input_component_diag.get("ambiguous"))
                break
    if truth.get("text") and truth.get("input_kind") in ("speech", "user", "comment", "observer"):
        auth = truth["authority"]
        if auth == "avatar" and truth.get("role") == "teilnehmer":
            auth = "teilnehmer"
        if skip_figure:
            auth = "observer"
        s.setdefault("turns", []).append(
            {
                "id": _next_id("ln", s),
                "turn": turn,
                "speakerId": input_actor,
                "speakerName": _input_name or ("Beobachter" if skip_figure else "User"),
                "role": auth,
                "speech": truth["text"],
                "firedSpaces": [],
            }
        )
        speech_text, action_text = ((str(truth["text"]), None) if skip_figure
                                    else (input_speech, input_action))
        # Original input is retained separately; the chat line no longer labels
        # a silent action as spoken words. Existing UI already renders action.
        if not skip_figure:
            s["turns"][-1]["inputText"] = truth["text"]
            s["turns"][-1]["speech"] = speech_text or ""
            s["turns"][-1]["action"] = action_text
        if skip_figure:
            uf = make_fact(
                turn=turn,
                actorId=input_actor,
                targetId=truth.get("target_id"),
                kind="narrator",
                speech_act=infer_speech_act(truth["text"]),
                text=truth["text"],
                authority=auth,
                sourceTurnId=source,
                truth=truth,
                scene=s.get("scene") or {},
                # R3.4 / B.7-Folge: Time-Kontext
                time_tense=_pre_tense,
                time_ambiguous=bool(_pre_ambiguous),
            )
            s.setdefault("facts", []).append(uf)
            new_facts.append(uf)
        else:
            if speech_text:
                uf = make_fact(
                    turn=turn,
                    actorId=input_actor,
                    targetId=_speech_target,
                    kind="speech",
                    speech_act=infer_speech_act(speech_text),
                    text=speech_text,
                    authority=auth,
                    sourceTurnId=source,
                    truth=truth,
                    scene=s.get("scene") or {},
                    # R3.4 / B.7-Folge: Time-Kontext aus pre-bind
                    time_tense=_pre_tense,
                    time_ambiguous=bool(_pre_ambiguous),
                )
                if input_plan is not None:
                    # A mixed *action* + spoken phrase needs separate semantics.
                    # V59C: an unresolved whole-input plan must not describe
                    # the speech part once an action component was split off.
                    separate = input_plan.get("event_kind") == "action" or (
                        bool(input_actions) and input_plan.get("validation_status") == "source_only")
                    uf["plan"] = (input_plan if not separate else
                                  _conj.literal_plan(speech_text, actor_id=input_actor,
                                      recipient_id=str(_speech_target or "") or None))
                    uf["speech_act"] = uf["plan"].get("speech_act")
                # V65K (AMASTER §24.1 known_as, §24.6 Sessionwortschatz): what the speaker
                # establishes about a name or a word meaning; validated, session scope only.
                if isinstance(user_plan, dict) and isinstance(user_plan.get("sprache"), list):
                    uf["sprache"] = bind_language(str(truth.get("text") or ""), user_plan.get("sprache"),
                                                  speaker_id=str(input_actor),
                                                  addressee_id=(str(_speech_target) if _speech_target else None),
                                                  figures=present)
                s.setdefault("facts", []).append(uf)
                new_facts.append(uf)
            _rel_to = _speech_target if speech_text else truth.get("target_id")
            if ((speech_text or action_text) and _rel_to in (s.get("scene") or {}).get("presentIds", []) and input_actor
                    and str(_rel_to) != str(input_actor)
                    # V65F (AMASTER §6 "RelationshipState: gerichtete aktuelle Beziehung zwischen
                    # zwei Figuren", §44, §8 "Der reale Nutzer ist nicht automatisch eine Figur",
                    # §68 Nr. 4): only figures stand in a RelationshipState. Session 05:33: the
                    # Bedienperson ("user") got Mara<->user "knows" 0.4/0.2 at "Hey schatz".
                    and str(input_actor) not in (*_OPERATOR_IDS, "observer")):
                # V30 (AMASTERv2 §44 Erstkontakt): Wer miteinander spricht, steht in einer gerichteten
                # Sessionbeziehung (Standardwerte, kein Drift) — sonst fehlt dem Folgeturn relationsHere.
                _ensure_directed_rel(s, str(input_actor), str(_rel_to), cause=truth.get("id"))
                _ensure_directed_rel(s, str(_rel_to), str(input_actor), cause=truth.get("id"))
            if action_text:
                # V59C (§34.1): every validated action component is its own
                # SceneFact with its own target and its own validation.
                # V92 Paket 19 (Pruefung P18 N1): the body state at the START of the turn decides every component's capability
                # (a waking act in this turn releases no other act of the same input).
                _rt_user0 = copy.deepcopy((s.get("runtimes") or {}).get(input_actor) or {})
                _actor_fig = next((f for f in (present or []) if isinstance(f, dict) and str(f.get("id") or "") == str(input_actor)), None)
                for comp in (input_actions or []):
                    comp_text = str(comp.get("text") or "").strip()
                    if not comp_text:
                        continue
                    comp_target = comp.get("targetId")
                    # V92 Paket 18/19: the change of his own body the server's readings validated for this act (reading + confirmation)
                    _kchg, _kaud = own_body_change(comp.get("koerperPruefung"), comp_text)
                    _cap, _kchg, _wake = act_capability(_rt_user0 if isinstance(_rt_user0, dict) else {}, comp_text, _kchg, _kaud,
                                                        authority=str(auth or ""), names=_figure_name_forms(_actor_fig) if _actor_fig else [])
                    blocked = _cap is not None
                    action_present = set((s.get("scene") or {}).get("presentIds") or [])
                    absent_target = bool(comp_target and comp_target not in action_present)
                    absent_actor = input_actor not in action_present
                    invalid_reason = "capability" if blocked else ("target_absent" if absent_target else ("actor_absent" if absent_actor else None))
                    af = make_fact(
                        turn=turn,
                        actorId=input_actor,
                        targetId=comp_target,
                        kind="action",
                        event_kind="action",
                        speech_act=None,
                        text=comp_text,
                        authority=auth,
                        sourceTurnId=source,
                        truth=truth,
                        scene=s.get("scene") or {},
                        validated=invalid_reason is None,
                        rejection_reason=invalid_reason,
                        time_tense=_pre_tense,
                        time_ambiguous=bool(_pre_ambiguous),
                        source_type="action",
                        witnessedBy=list(dict.fromkeys([input_actor] + [cid for cid in truth.get("sees_ids") or [] if cid in action_present])),
                    )
                    # V61 (AMASTER §34.1, §35, §36.1): a whole-input plan with
                    # event_kind "action" describes the ACT, also when a spoken
                    # part was split off (V59C keeps it away from the speech).
                    # Before V61 it was dropped for mixed input, and with it the
                    # planner's refers_to: Tom's kiss/kneeling never became a
                    # response to Tammy's open request (session 22:52, T2/T6).
                    if input_plan is not None and input_plan.get("event_kind") == "action":
                        af["plan"] = input_plan
                        af["speech_act"] = input_plan.get("speech_act")
                    else:
                        af["speech_act"] = "act"
                    af["effect"] = {"wirkung": comp.get("wirkung"), "effectKind": comp.get("effectKind"),
                                    "validated": bool(comp.get("effectValid"))}
                    if comp.get("wirkungPruefung"):
                        af["effect"]["pruefung"] = copy.deepcopy(comp.get("wirkungPruefung"))
                    if isinstance(comp.get("grenzBezug"), list):
                        af["effect"]["grenzBezug"] = copy.deepcopy(comp["grenzBezug"])   # V65W (C1)
                    _mark_outcome_from_check(af["effect"])
                    af["effect"]["koerperPruefung"] = _kaud
                    if _wake:
                        af["effect"]["nurAufwachen"] = True   # V92 Paket 19: the act of a sleeping figure is her waking, nothing else
                    if comp.get("componentIndex") is not None:
                        af["componentIndex"] = comp.get("componentIndex")
                    if invalid_reason is None and not _pre_past and _pre_tense != "future":
                        _bezug = comp.get("bezug") or ((af.get("plan") or {}).get("refers_to") if isinstance(af.get("plan"), dict) else None)
                        _bind_response_to_request(s, af, _bezug, turn=turn)
                        if isinstance(comp.get("bitteBezug"), list):
                            # V65W (C7): his own act that carries out his request she accepted (read server-side)
                            af["effect"]["bitteBezug"] = copy.deepcopy(comp["bitteBezug"])
                            if _input_acts_incomplete(input_component_diag.get("ambiguous")):
                                af["effect"]["bitteBindung"] = "eingabe_unvollstaendig"   # V65X (E05)
                            else:
                                _bind_own_act_to_request(s, af, comp["bitteBezug"], turn=turn)
                    s.setdefault("facts", []).append(af)
                    new_facts.append(af)
                    if invalid_reason is None and not _pre_past and _pre_tense != "future":
                        # R3.4 / B.7-Folge: past-Action ist Bericht, keine
                        # Runtime-Mutation. V59C: the physical class is the
                        # validated semantic class, never a word list.
                        if not _wake:   # V92 Paket 19: waking up has no effect on anybody else
                            _apply_physical(
                                s,
                                actor_id=input_actor,
                                target_id=comp_target,
                                text=comp_text,
                                validated=True,
                                source_turn_id=source,
                                authority=auth,
                                truth=truth,
                                turn=turn,
                                new_facts_out=new_facts,
                                effect_kind=comp.get("effectKind") if comp.get("effectValid") else None,
                                fact_id=af["id"],
                                world=world,
                            )
                        # V92 Paket 18/19: only the change of his own body the server's readings validated for this act - through
                        # the ONE writer entry
                        _w = write_body_change(s, str(input_actor), _kchg, fact_id=af["id"], turn=turn, authority=auth, text=comp_text,
                                               actor_name=_input_name)
                        if _w.get("fehler"):
                            af["effect"]["koerperFehler"] = _w["fehler"]
            if isinstance(user_plan, dict) and not _pre_past and _pre_tense != "future":
                _bind_profile_triggers(s, user_plan, new_facts, input_actor=str(input_actor),
                                       owner_id=str(truth.get("target_id") or ""), present=present, turn=turn)
            # V60 (AMASTER §24.6, §27.3, §68 Nr. 54): the former regex branch
            # (_THREAT_RE/_RESIGN_RE/_REQUEST_RE) wrote the addressee's emotion
            # and the speaker's (also the avatar's) relationship from words,
            # ignoring negation. Removed: the addressee's reaction comes from
            # her own validated reply; the avatar's state only from the user.
    speech = ""
    action = None
    gagged = False
    rt: dict = {}
    if skip_figure or input_only:
        comps = []
    else:
        rt = s.setdefault("runtimes", {}).setdefault(speaker["id"], {})
        # V92 Paket 19 (Pruefung P18 N1/N2; AMASTER §43 Capability, §43.1): the body state at the START of the turn decides.
        # An act of hers is validated with the change her own act makes to her body (server readings: koerper_check +
        # koerper_bestaetigung): asleep, the only act she can do is waking up (act_capability); she speaks no words while she
        # sleeps or is unconscious (can_speak_now) - the same rule as gagged.
        _rt0 = copy.deepcopy(rt)
        comps = []
        for c in split_output_components(truth, result, speaker):
            c = validate_component(c, rt)
            if c.get("event_kind") in ("action", "physical"):
                _kch, _kau = own_body_change(koerper_lesung, c.get("text") or "")
                _kcap, _kch, _kwake = act_capability(_rt0, c.get("text") or "", _kch, _kau, authority="character",
                                                     names=_figure_name_forms(speaker))
                c["validated"] = _kcap is None
                c["rejection_reason"] = _kcap
                c["_koerper"] = {"aenderung": _kch, "pruefung": _kau, "nurAufwachen": _kwake}
            comps.append(c)
        gagged = not can_speak_now(_rt0)
        if gagged:
            # Speech prohibited by this figure's body state is NOT a performed
            # speech component. V91 stored "—" as validated canonical speech.
            comps = [c for c in comps if c.get("kind") != "speech"]
        speech_comp = next((c for c in comps if c.get("kind") == "speech"), None)
        action_comp = next((c for c in comps if c.get("kind") in ("action", "physical") and c.get("validated")), None)
        # V65D: a speech that consisted only of a "*…*" act stays empty; the
        # raw provider text is not taken back in as words.
        speech = "" if gagged else ((speech_comp or {}).get("text") or ("" if (speech_comp or {}).get("markerStripped") else result.get("speech")) or "")
        action = (action_comp or {}).get("text") if action_comp else None
        if not str(speech or "").strip() and not action and (response_only or not str(truth.get("text") or "").strip()):
            # No executable answer. For the two-phase API, keep the committed
            # input pending so it can be retried. For pure AutoChat, do not
            # advance an empty turn or attach invented TurnTruth/Fact rows.
            return copy.deepcopy(session)
        # V60 (AMASTER §24.6, §45, §68 Nr. 54): only the semantic proposal,
        # validated against the figure's own compass threshold, may write. The
        # lexical lens list sent back by the client is a candidate, not a cause.
        fired_all = fire_from_proposals(speaker, proposals or (result.get("proposals") if isinstance(result, dict) else None), rt)
        if str(speech or "").strip() or action:
            s.setdefault("turns", []).append(
                {
                    "id": _next_id("ln", s),
                    "turn": turn,
                    "speakerId": speaker["id"],
                    "speakerName": speaker.get("name"),
                    "role": "character",
                    "speech": speech,
                    "action": action,
                    "firedSpaces": [f.get("space") for f in fired_all],
                    "synapses": [{"space": f.get("space"), "activation": f.get("activation"), "source": f.get("source") or "lexikalisch"} for f in fired_all[:4]],
                    "recallCount": int(recall_count) if recall_count is not None else None,
                }
            )
        fired = fired_all
    # V59C (AMASTER §28 Schritt 29/30, §24.6): the figure's action carries a
    # proposed semantic class; it is validated here before any writer.
    _out_props = proposals or (result.get("proposals") if isinstance(result, dict) else None) or {}
    _out_wirkung = _out_props.get("wirkung") if isinstance(_out_props, dict) and isinstance(_out_props.get("wirkung"), dict) else None
    _out_effect_valid, _out_effect = effect_kind_from_wirkung((_out_wirkung or {}).get("art"))
    _out_present = [c for c in (present or []) if isinstance(c, dict) and str(c.get("id") or "") in set((s.get("scene") or {}).get("presentIds") or [])]
    # V62 (AMASTER §25, §41.1): in a reaction turn without own input the
    # figure answers the author of the immediate stimulus. The frontend sends
    # the avatar as input actor for every reaction (speakAs "avatar"); live
    # 27.10.: Mara's "Oh Clara, ich kann am Samstag nicht arbeiten" was bound
    # to Alrik and refused HIS proposal.
    _interlocutor = str(truth.get("input_actor_id") or "")
    if str(truth.get("input_kind") or "") == "autochat" and not skip_figure:
        _lf = latest_foreign_line(s, str(speaker.get("id") or ""))
        if _lf is not None and str(_lf.get("actorId") or "") in set((s.get("scene") or {}).get("presentIds") or []):
            _interlocutor = str(_lf.get("actorId"))
    for comp in comps:
        text = comp.get("text") or ""
        # One speech/action target decision, based on the utterance and the
        # interlocutor, not the UI target of the previous input. LLM component
        # targetId is only a candidate; it cannot become authority by itself.
        if comp.get("kind") in ("speech", "action", "physical"):
            figures = [c for c in (present or []) if isinstance(c, dict) and c.get("id")]
            if isinstance(world, dict):
                figures.extend(c for c in (world.get("characters") or []) if isinstance(c, dict) and c.get("id") and c.get("id") not in {x.get("id") for x in figures})
            input_other = _interlocutor
            selected = input_other if input_other and input_other != str(speaker.get("id")) and input_other in (s.get("scene") or {}).get("presentIds", []) else None
            bound_target = resolve_target_detail(s, figures, text, ui_target_id=selected, input_actor_id=str(speaker.get("id")))
            target = bound_target.get("target_id")
            if input_other in _OPERATOR_IDS and not str(bound_target.get("reason") or "").startswith("explicit_address"):
                # V65Z (SPS-Audit V65Y A06; AMASTER §27.2 Z. 1374 "Ob er ueber einen Avatar spricht oder ausserhalb der Welt
                # bleibt, wird ausdruecklich gebunden", §23 Bedienperson getrennt): the figure answers the Bedienperson who
                # spoke to her. Her speech is addressed to the Bedienperson unless it names another figure by name; an act
                # is directed only at a figure it names (the Bedienperson is outside the world). Before, the resolver's
                # last fallback ("sole present interlocutor") gave Mara's answer to the present avatar Alrik.
                if comp.get("kind") == "speech":
                    target = input_other
                else:
                    _in_act = _named_in(text, [c for c in figures if str(c.get("id") or "") in set((s.get("scene") or {}).get("presentIds") or [])],
                                        {str(speaker.get("id") or "")})
                    target = next(iter(_in_act)) if len(_in_act) == 1 else None
            elif not target and not bound_target.get("ambiguous") and input_other in ("user", "operator"):
                target = input_other  # speaking to the operator is not witness knowledge
            if comp.get("kind") in ("action", "physical") and _out_wirkung and str(_out_wirkung.get("ziel") or "").strip():
                # Entity binding of the proposed affected figure (§25): only a
                # present figure other than the actor; otherwise keep binding.
                hit = _match_figure(str(_out_wirkung.get("ziel")), _out_present)
                if hit and str(hit.get("id")) != str(speaker.get("id")):
                    target = str(hit.get("id"))
            comp = {**comp, "targetId": target}
        # R3.4 / B.7-Folge: Time-Kontext für ALLE comps, nicht nur speech.
        # Wenn comp "speech" mit past-Text → kein Drift (via _pre_past-Gate).
        fact = make_fact(
            turn=turn,
            # Defense in depth for callers constructing components directly:
            # a normal figure commit can only act as its canonical speaker.
            actorId=speaker["id"],
            targetId=comp.get("targetId"),
            kind=comp.get("kind") or "speech",
            event_kind=comp.get("event_kind") or comp.get("kind") or "speech",
            speech_act=comp.get("speech_act"),
            text=text,
            authority="character",
            sourceTurnId=source,
            truth=truth,
            scene=s.get("scene") or {},
            validated=comp.get("validated", True),
            rejection_reason=comp.get("rejection_reason"),
            time_tense=_pre_tense,
            time_ambiguous=bool(_pre_ambiguous),
        )
        s.setdefault("facts", []).append(fact)
        new_facts.append(fact)
        if fact.get("kind") in ("action", "physical") and not _pre_past:
            # R3.4 / B.7-Folge: past/ambiguous Action darf keine
            # Runtime-Mutation triggern. "Ich habe gestern geschlagen"
            # ist Bericht, keine neue körperliche Handlung.
            _kk = comp.get("_koerper") if isinstance(comp.get("_koerper"), dict) else {}
            fact["effect"] = {"wirkung": copy.deepcopy(_out_wirkung), "effectKind": _out_effect,
                              "validated": bool(_out_effect_valid)}
            if _kk.get("nurAufwachen"):
                # V92 Paket 19: the act of a sleeping figure is her waking up - no effect on anybody else
                fact["effect"] = {"wirkung": None, "effectKind": None, "validated": False, "nurAufwachen": True}
            _mark_outcome_from_check(fact["effect"])
            if not _kk.get("nurAufwachen"):
                _apply_physical(
                    s,
                    actor_id=speaker.get("id"),
                    target_id=fact.get("targetId"),
                    text=fact.get("text") or "",
                    validated=bool(fact.get("validated")),
                    source_turn_id=source,
                    authority=fact.get("authority") or "character",
                    truth=truth,
                    turn=turn,
                    new_facts_out=new_facts,
                    effect_kind=_out_effect if _out_effect_valid else None,
                    fact_id=fact.get("id"),
                    world=world,
                )
            # V92 Paket 18/19 (unabhaengige Pruefung Paket 17 N1-N9, Paket 18 N3/N4): her action changes her own body only by the
            # change the server's readings validated for it (position, falling asleep, waking up; reading + confirmation at the
            # quote) - never by its words; the audit stays on the action fact; the ONE writer entry
            fact["effect"]["koerperPruefung"] = _kk.get("pruefung") if _kk else own_body_change(koerper_lesung, fact.get("text") or "")[1]
            if fact.get("validated") and _kk.get("aenderung"):
                _w = write_body_change(s, str(speaker.get("id")), _kk.get("aenderung"), fact_id=fact["id"], turn=turn,
                                       authority="character", text=fact.get("text") or "", actor_name=str(speaker.get("name") or ""))
                if _w.get("fehler"):
                    fact["effect"]["koerperFehler"] = _w["fehler"]
    # V65Q (AMASTER §46.6 Z. 2596 "Regie: Actor, Target und exakt angeordnete Szenenwirkung
    # binden und committen", §34 Z. 1767 Kausalprovenienz; Pruefung v2.8 P-09): the speech
    # of a Regie actor turn is the ORDERED speech - its addressee is the ordered target
    # and it carries the Regie Fact as its cause. No check of what she said (no filter).
    if not skip_figure and str(truth.get("directive") or "").strip():
        _ord = regie_order_for(s, str(truth.get("directive") or ""), str(speaker.get("id") or ""))
        if _ord is not None:
            _pres = {str(x) for x in ((s.get("scene") or {}).get("presentIds") or [])}
            for _sf in [f for f in new_facts if isinstance(f, dict) and f.get("kind") == "speech"
                        and str(f.get("actorId")) == str(speaker.get("id"))]:
                if _ord.get("targetId") and str(_ord["targetId"]) in _pres and str(_ord["targetId"]) != str(speaker.get("id")):
                    _sf["targetId"] = str(_ord["targetId"])
                if _ord.get("regieFactId"):
                    _sf["causeFactId"] = _ord["regieFactId"]
                _sf["regieOrder"] = {k: _ord.get(k) for k in ("segment", "redeverb", "regieTurn")}
    if not skip_figure and speech and speech != "—":
        sf = next((f for f in reversed(new_facts) if isinstance(f, dict) and f.get("kind") == "speech" and str(f.get("actorId")) == str(speaker.get("id"))), None)
        if sf is not None:
            props = proposals or (result.get("proposals") if isinstance(result, dict) else None) or {}
            plan = _conj.normalize_plan(props.get("plan") if isinstance(props, dict) else None, actor_id=str(speaker.get("id")), recipient_id=str(sf.get("targetId") or "") or None, text=speech, now=_session_now(s), present_ids=[str(p.get("id")) for p in (present or []) if isinstance(p, dict)], figures=present)
            # V60 (AMASTER §24.6, §68 Nr. 54): an invalid semantic plan is
            # not replaced by the regex speech-act reader; the speech stays
            # source-only ("unresolved") and visible, never a guessed lifecycle.
            if plan is None:
                plan = _conj.literal_plan(speech, actor_id=str(speaker.get("id")), recipient_id=str(sf.get("targetId") or "") or None)
            # AMASTER §34.1: this Fact is bound as SPOKEN text. An LLM
            # action classification may describe a separate action component,
            # but it cannot turn the already committed words into an act.
            if plan.get("event_kind") == "action" or plan.get("speech_act") == "act":
                sf["planAmbiguity"] = {"reason": "rede_als_handlung_klassifiziert", "candidate": copy.deepcopy(plan)}
                plan = _conj.literal_plan(speech, actor_id=str(speaker.get("id")),
                                          recipient_id=str(sf.get("targetId") or "") or None)
            sf["plan"] = plan
            sf["speech_act"] = plan.get("speech_act")
            hears_now = list(_scene_perception(s, list((s.get("scene") or {}).get("presentIds") or []))[0])   # Stand 07 / K-01: canonical perception (explicit empty list, position, canHear, consciousness)
            wit = list(dict.fromkeys(hears_now + [str(speaker.get("id"))]))
            selfc = [i for i in _truth.local_contradictions(s, speaker, utterer_id=str(speaker.get("id")), plan=plan, text=speech) if i.get("art") == "selbstwiderspruch"]
            reg = _truth.register_claim(s, plan, fact_id=sf["id"], turn=turn, witnesses=wit)
            if reg and selfc:
                reg["truthStatus"] = "self_contradiction"
                reg["conflictsWith"] = [i.get("claimId") for i in selfc if i.get("claimId")]
                sf["selfContradiction"] = selfc[:2]
            if not _pre_past or plan.get("event_kind") in ("claim", "disclosure", "report", "question", "smalltalk"):
                ch = _conj.apply_plan(s, plan, fact_id=sf["id"], turn=turn, witnesses=wit)
                if ch:
                    sf["frameChange"] = ch
                    if s.get("turns"):
                        s["turns"][-1]["frameChange"] = ch
    # V44: Synapsen sind Gegenwartsreaktion der Figur — auch wenn die Äußerung von Vergangenem
    # handelt ("wo warst du gestern Nacht?"); §37 sperrt nur Commitments/Handlungen aus Vergangenheitsform.
    # No direct reply-based relationship writer: §44 requires checked cause.
    # V62 (AMASTER §28 Schritt 13, §44 Idempotenz, "eine Ursache, eine Wirkung"):
    # when the appraisal step already evaluated what this figure perceived
    # before her reply, her reply's self-report (synapsen/emotion/beziehung) is
    # audit only (turn record, s["proposals"]); it stays the writer only when no
    # appraisal ran (no provider, failed call, direct kernel callers).
    _spk = str(speaker.get("id") or "")
    _stim_ids: set[str] = set()
    if not skip_figure and not input_only and _spk:
        _stim_ids = {str(f.get("id")) for f in (s.get("facts") or []) if isinstance(f, dict)
                     and str(f.get("sourceTurnId") or "") == str(source) and str(f.get("actorId") or "") not in ("", _spk)
                     and f.get("kind") in ("speech", "action", "physical")}
        if str(truth.get("input_kind") or "") == "autochat":
            _lf_r = latest_foreign_line(s, _spk)
            if _lf_r is not None:
                _stim_ids.add(str(_lf_r.get("id")))
    _rt_spk = (s.get("runtimes") or {}).get(_spk) or {}
    # An input was appraised before the answer and already changed Runtime.
    # Bind by CANONICAL cause Facts and reply order, not the answer's NEW
    # TurnTruth; the same cause may never be written a second time by synapses.
    _appraised_facts = unanswered_appraisal_causes(s, _spk, before_turn=turn) if _spk else []
    _appraised = bool(_appraised_facts) or bool(_stim_ids & {str(x) for x in (_rt_spk.get("appraisalCauses") or [])})
    if not skip_figure and not input_only and _spk and _appraised:
        if s.get("turns"):
            s["turns"][-1]["selfReportAudit"] = True
            s["turns"][-1]["selfReportCauseFactIds"] = _appraised_facts
    elif not skip_figure and speaker.get("id") and fired:
        cause = next((f.get("id") for f in new_facts if isinstance(f, dict) and f.get("kind") == "speech" and str(f.get("actorId")) == str(input_actor)), None) or source
        syn = apply_synapses(s, speaker, fired, cause_fact_id=cause, turn=turn, proposals=proposals or (result.get("proposals") if isinstance(result, dict) else None), present=present)
        if syn and s.get("turns"):
            s["turns"][-1]["synapseEffect"] = {k: syn.get(k) for k in ("runtimeDelta", "relationDelta")}
        if syn and _spk:
            # the reply path gave these causes their one effect: the next
            # appraisal must not apply them again (review finding 5)
            _rt_w = s.setdefault("runtimes", {}).setdefault(_spk, {})
            _rt_w["appraisedFactIds"] = ([str(x) for x in (_rt_w.get("appraisedFactIds") or [])] + sorted(_stim_ids | {str(cause)}))[-120:]
    if speech and speech != "—":
        # V34 (AMASTERv2 §16/§40/§41, Vertrag §10): Gehörtes hat für die anwesenden Zuhörer Bedeutung.
        # Die Kompass-Linse JEDES Zuhörers entscheidet, ob Runtime/Beziehung/Ziel sich bewegen
        # (Ursache = Rede-Fact). Avatar und Sprecher selbst bleiben aus (§27.3).
        speech_fact = next((f for f in reversed(new_facts) if isinstance(f, dict) and f.get("kind") == "speech" and f.get("actorId") == speaker.get("id")), None)
        # Hearing a report about the past happens NOW: it may change the
        # listener's present knowledge/emotion, never retroactively enact a
        # physical action or commitment in the reported past.
        if speech_fact and present:
            for listener in present:
                lid = str((listener or {}).get("id") or "")
                if not lid or lid == str(speaker.get("id")) or lid == str(s.get("avatarId") or ""):
                    continue
                if lid not in ((s.get("scene") or {}).get("hearsIds") or (s.get("scene") or {}).get("presentIds") or []):
                    continue
                # V60 (AMASTER §24.6, §68 Nr. 54/63): no lexical compass writer on
                # heard speech. The listener's reaction is her own validated
                # semantic synapse when she formulates (one cause, one effect).
                pass
        # V60 (AMASTER §38, §24.6, §68 Nr. 54): ONE memory of the own speech,
        # bound to its Fact. The speech act comes from the validated plan,
        # not from a word list; no second copy of the same sentence.
        _sf_mem = next((f for f in reversed(new_facts) if isinstance(f, dict) and f.get("kind") == "speech"
                        and str(f.get("actorId")) == str(speaker["id"])), None) or {}
        _sf_plan = _sf_mem.get("plan") if isinstance(_sf_mem.get("plan"), dict) else {}
        s.setdefault("memories", []).append(
            make_memory(
                characterId=speaker["id"],
                kind="gesagt",
                text=speech[:180],
                salience=0.55,
                turn=turn,
                witnesses=[speaker["id"]],
                layer="session",
                truthStatus="canon",
                source="commit_turn",
                sessionId=s.get("id"),
                worldId=s.get("worldId"),
                factId=_sf_mem.get("id"),
                sourceTurnId=source,
                speechAct=_sf_plan.get("speech_act") if _sf_plan.get("source") == "llm" else None,
                targetId=_sf_mem.get("targetId"),
            )
        )
        present_hear = set(truth.get("present_ids") or (s.get("scene") or {}).get("presentIds") or [])
        for hid in _effective_hears(s, truth):
            if not hid or hid == speaker["id"] or hid not in present_hear:
                continue
            s.setdefault("memories", []).append(
                make_memory(
                    characterId=hid,
                    kind="gehoert",
                    text=f"{speaker.get('name') or speaker['id']}: {speech[:180]}",
                    salience=0.5,
                    turn=turn,
                    witnesses=[hid],
                    layer="session",
                    truthStatus="canon",
                    source="commit_turn",
                    sessionId=s.get("id"),
                    worldId=s.get("worldId"),
                    factId=_sf_mem.get("id"),
                    sourceTurnId=source,
                )
            )
    if action:
        # V59C (AMASTER §25/§34.1): the affected person is the target of THIS
        # action component, not the target of the preceding user input.
        _act_fact = next((f for f in reversed(new_facts) if isinstance(f, dict) and f.get("kind") == "action"
                          and str(f.get("actorId")) == str(speaker["id"]) and _scene.validiert(f)), None)
        # V60 (AMASTER §38): own action = "getan" once, bound to its Fact;
        # "erlebt" is what happens TO a figure, never a copy of the own deed.
        s.setdefault("memories", []).append(
            make_memory(
                characterId=speaker["id"],
                kind="getan",
                text=str(action)[:180],
                salience=0.55,
                turn=turn,
                witnesses=[speaker["id"]],
                layer="session",
                truthStatus="canon",
                source="commit_turn",
                sessionId=s.get("id"),
                worldId=s.get("worldId"),
                factId=(_act_fact or {}).get("id"),
                sourceTurnId=source,
            )
        )
        tgt = (_act_fact or {}).get("targetId")
        if tgt and tgt != speaker["id"]:
            s.setdefault("memories", []).append(
                make_memory(
                    characterId=tgt,
                    kind="betroffen",
                    text=f"{speaker.get('name') or speaker['id']}: {str(action)[:170]}",
                    salience=0.5,
                    turn=turn,
                    witnesses=[tgt, speaker["id"]],
                    layer="session",
                    truthStatus="canon",
                    source="commit_turn",
                    sessionId=s.get("id"),
                    worldId=s.get("worldId"),
                    factId=(_act_fact or {}).get("id"),
                    sourceTurnId=source,
                )
            )
        for vid in _effective_sees(s, truth):
            if vid in (speaker["id"], tgt):
                continue
            s.setdefault("memories", []).append(
                make_memory(
                    characterId=vid,
                    kind="gesehen",
                    text=f"{speaker.get('name') or speaker['id']}: {str(action)[:140]}",
                    salience=0.45,
                    turn=turn,
                    witnesses=[vid],
                    layer="session",
                    truthStatus="canon",
                    source="commit_turn",
                    sessionId=s.get("id"),
                    worldId=s.get("worldId"),
                    factId=(_act_fact or {}).get("id"),
                    sourceTurnId=source,
                )
            )
    s["proposals"] = {
        "emotion": result.get("emotion"),
        "intent": result.get("intent"),
        "memoryNote": result.get("memoryNote"),
        "relationDeltas": result.get("relationDeltas") or [],
        "sceneChangePlace": result.get("sceneChangePlace"),
        "accepted": False,
    }
    fate_proposal = _collect_fate_proposal(result)
    if fate_proposal is not None:
        s["proposals"]["fate"] = fate_proposal
    if accept_llm_state:
        if result.get("emotion"):
            rt["emotion"] = result["emotion"]
        if result.get("intent"):
            rt["intent"] = result["intent"]
        s["proposals"]["accepted"] = True
        if result.get("memoryNote"):
            hear_ids = [
                i
                for i in (_effective_hears(s, truth) or [])
                if i != speaker["id"]
            ]
            mem = make_memory(
                characterId=speaker["id"],
                kind="erlebt",
                text=result["memoryNote"],
                salience=0.7,
                turn=turn,
                witnesses=hear_ids,
                layer="session",
                truthStatus="canon",
            )
            s.setdefault("memories", []).append(mem)
    # V57: input memories follow the committed component, never the raw UI
    # envelope. This keeps said/heard distinct from done/experienced/seen.
    present_set = set(truth.get("present_ids") or (s.get("scene") or {}).get("presentIds") or [])
    for source_fact in new_facts:
        if source_fact.get("actorId") != input_actor or source_fact.get("kind") not in ("speech", "action"):
            continue
        fact_text = str(source_fact.get("text") or "")
        is_action = source_fact.get("kind") == "action"
        valid_action = is_action and _scene.validiert(source_fact) and not _pre_past and _pre_tense != "future"
        if is_action:
            if input_actor in present_set:
                s.setdefault("memories", []).append(make_memory(
                    characterId=input_actor, kind="getan" if valid_action else "versucht",
                    text=fact_text, salience=0.65, turn=turn, witnesses=[input_actor],
                    layer="session", truthStatus="canon" if valid_action else "attempted",
                    source="kernel", factId=source_fact["id"], sourceTurnId=source,
                    sessionId=s.get("id"), worldId=s.get("worldId")))
            if not valid_action:
                continue
            for cid in present_set - {input_actor}:
                access = witness_access(truth, source_fact, cid)
                if access not in ("affected", "seen"):
                    continue
                s.setdefault("memories", []).append(make_memory(
                    characterId=cid, kind="erlebt" if access == "affected" else "gesehen",
                    text=f"{_input_name or input_actor}: {fact_text}",
                    salience=0.65, turn=turn, witnesses=[cid], layer="session",
                    truthStatus="canon", source="kernel", factId=source_fact["id"],
                    sourceTurnId=source, sessionId=s.get("id"), worldId=s.get("worldId")))
        else:
            for cid in _effective_hears(s, truth):
                if not cid or cid in (input_actor, avatar_id) or cid not in present_set:
                    continue
                s.setdefault("memories", []).append(make_memory(
                    characterId=cid, kind="gehoert",
                    text=f"{_input_name or 'Der Gast'} sagte: {fact_text[:180]}",
                    salience=0.65, turn=turn, witnesses=[cid], layer="session", truthStatus="canon",
                    source="kernel", factId=source_fact["id"], sourceTurnId=source,
                    sessionId=s.get("id"), worldId=s.get("worldId")))
    _record_fact_witnesses(s, truth, new_facts, turn)
    # V58 / AMASTER 35: perception updates attention. A goal experience needs
    # its own bound goal/proposition reference, not just the same addressee.
    for source_fact in new_facts:
        if source_fact.get("actorId") != input_actor:
            continue
        for listener in present or []:
            lid = str((listener or {}).get("id") or "")
            if lid and lid != input_actor:
                apply_goal_experience(s, lid, source_fact, turn=turn)
    # V36 (AMASTERv2 §16/§40): Auch die Rede des Eingabe-Akteurs (Avatar/Bedienperson) wirkt auf
    # die anwesenden Weltfiguren, die sie hören — nicht nur die Rede der antwortenden Figur.
    user_text = str(input_speech or "").strip()
    input_events = [f for f in new_facts if f.get("actorId") == input_actor and f.get("kind") in ("speech", "action")]
    for user_fact in input_events:
        if not _scene.validiert(user_fact):
            continue
        for listener in present or []:
            lid = str((listener or {}).get("id") or "")
            access = witness_access(truth, user_fact, lid)
            if not lid or lid in (input_actor, str(s.get("avatarId") or "")) or access not in ("heard", "seen", "affected"):
                continue
            # V60 (AMASTER §24.6, §68 Nr. 54/63): the former lexical compass
            # writer (apply_knowledge_effect on heard input) is removed for chat
            # speech/action; it set emotion, intent, a goal and relationship
            # from word hits and doubled the effect of the same input.
            continue
    # V39 Konjunktives Gedächtnis (§36/§37/§40): jede Nutzer-/Avatar-/Puppet-Rede bekommt einen
    # validierten Turn-Plan (LLM oder lokal) am Fact; dauerhafte Inhalte werden Frames.
    if user_text and truth.get("input_kind") in ("speech", "user"):
        uf = next((f for f in new_facts if isinstance(f, dict) and f.get("kind") == "speech" and str(f.get("actorId")) == str(input_actor)), None)
        if uf is not None:
            # Same pre-bound plan that selected the Fact writer, not a second
            # classifier after effects and memories have already been written.
            plan = uf.get("plan") or input_plan
            uf["plan"] = plan
            uf["speech_act"] = plan.get("speech_act")
            hears_now = list(_scene_perception(s, list((s.get("scene") or {}).get("presentIds") or []))[0])   # Stand 07 / K-01: canonical perception (explicit empty list, position, canHear, consciousness)
            wit = list(dict.fromkeys(hears_now + [str(input_actor)]))
            # V42: Widerspruch, den die antwortende Figur bemerkt — Prüfung gegen den Stand VOR der neuen
            # Behauptung, Registrierung danach (damit die neue Behauptung ihren Status bekommt)
            found = []
            if not skip_figure and speaker.get("id") and str(speaker.get("id")) != str(input_actor):
                found = _truth.local_contradictions(s, speaker, utterer_id=str(input_actor), plan=plan, text=user_text)
                # A model's contradiction is a hypothesis, never an owner
                # mutation. Only a structurally corroborated source may commit.
                found = _truth.validate_llm_contradictions(
                    {"widersprueche": contradictions or []}, s, speaker,
                    evidence=found, statement=user_text,
                ) or found
            _truth.register_claim(s, plan, fact_id=uf["id"], turn=turn, witnesses=wit)
            if found:
                eff = _truth.apply_contradictions(s, speaker, found, utterer_id=str(input_actor), cause_fact_id=uf["id"], turn=turn)
                if eff:
                    uf["contradiction"] = eff
                    if not skip_figure and s.get("turns") and str(s["turns"][-1].get("speakerId")) == str(speaker.get("id")):
                        s["turns"][-1]["contradiction"] = eff
            # §37: Vergangenheitsform erzeugt keine neuen Commitments (Vorschlag/Bitte/Versprechen);
            # Behauptungen/Offenbarungen werden dennoch als Frames festgehalten.
            if not _pre_past or plan.get("event_kind") in ("claim", "disclosure", "report", "question", "smalltalk"):
                ch = _conj.apply_plan(s, plan, fact_id=uf["id"], turn=turn, witnesses=wit)
                if ch:
                    uf["frameChange"] = ch
    # V44 Szenen-Zustandsmaschine: Beats aus diesem Commit (Nutzer-/Avatar-Turn und Figurenturn)
    try:
        _present_ids_now = [str(cid) for cid in (s.get("scene") or {}).get("presentIds") or []]
        # `present` parameter may carry the whole world cast for name lookup;
        # only the committed SceneState decides in-room participants.
        _utext = str(truth.get("text") or "").strip()
        if _utext and truth.get("input_kind") in ("speech", "user"):
            _ufact = next((f for f in new_facts if isinstance(f, dict) and f.get("kind") == "speech" and str(f.get("actorId")) == str(input_actor)), None)
            _uact = next((f for f in new_facts if isinstance(f, dict) and f.get("kind") == "action" and str(f.get("actorId")) == str(input_actor)), None)
            _scene.update_from_commit(
                s, speaker_id=str(input_actor), target_id=(str(truth.get("target_id")) if truth.get("target_id") in _present_ids_now else None), speech=str(input_speech or ""), action=(_uact or {}).get("text") if _scene.validiert(_uact) else None,
                fired=[], runtime=(s.get("runtimes") or {}).get(str(input_actor)), plan=(_ufact or _uact or {}).get("plan"),
                physical_changed=bool(_uact and any(f.get("event_kind") in ("body_state", "physical") and str(f.get("actorId")) == str(input_actor) for f in new_facts)),
                # V63: the validated action component decides the physical beat,
                # not the plan of the accompanying speech (mixed input).
                action_validated=bool(_uact and _scene.validiert(_uact)),
                act_outcomes=[(f.get("effect") or {}).get("outcome") for f in new_facts if isinstance(f, dict) and f.get("kind") == "action"
                              and str(f.get("actorId")) == str(input_actor) and _scene.validiert(f)],
                turn=turn, present_ids=_present_ids_now,
                effect_kinds=[str((f.get("effect") or {}).get("effectKind")) for f in new_facts if isinstance(f, dict)
                              and str(f.get("actorId")) == str(input_actor) and isinstance(f.get("effect"), dict)
                              and _scene.validiert(f.get("effect")) and _scene.validiert(f)],
            )
        # Silence does not remove a physical action from SceneState: action is
        # equal to speech in AMASTER, so use the action Fact if no speech exists.
        if not skip_figure and ((speech and speech != "—") or action):
            _sfact = next((f for f in reversed(new_facts) if isinstance(f, dict) and f.get("kind") == "speech" and str(f.get("actorId")) == str(speaker.get("id"))), None)
            _afact = next((f for f in reversed(new_facts) if isinstance(f, dict) and f.get("kind") == "action"
                           and str(f.get("actorId")) == str(speaker.get("id")) and _scene.validiert(f)), None)
            _lead = _sfact or _afact or {}
            _sch = _scene.update_from_commit(
                s, speaker_id=str(speaker.get("id")), target_id=str(_lead.get("targetId") or "") or None, speech=speech, action=action,
                fired=fired, runtime=(s.get("runtimes") or {}).get(str(speaker.get("id"))),
                plan={**((_lead.get("plan") or {}) if isinstance(_lead.get("plan"), dict) else {}),
                      "frameChange": _lead.get("frameChange")},
                physical_changed=any(f.get("event_kind") in ("body_state", "physical") and str(f.get("actorId")) == str(speaker.get("id")) for f in new_facts),
                action_validated=any(isinstance(f, dict) and f.get("kind") == "action" and _scene.validiert(f)
                                     and str(f.get("actorId")) == str(speaker.get("id")) for f in new_facts),
                act_outcomes=[(f.get("effect") or {}).get("outcome") for f in new_facts if isinstance(f, dict) and f.get("kind") == "action"
                              and str(f.get("actorId")) == str(speaker.get("id")) and _scene.validiert(f)],
                turn=turn, present_ids=_present_ids_now,
                effect_kinds=[str((f.get("effect") or {}).get("effectKind")) for f in new_facts if isinstance(f, dict)
                              and str(f.get("actorId")) == str(speaker.get("id")) and isinstance(f.get("effect"), dict)
                              and _scene.validiert(f.get("effect")) and _scene.validiert(f)],
            )
            if _sch and s.get("turns"):
                s["turns"][-1]["sceneDelta"] = _sch
    except Exception as _scene_exc:  # Szenenzustand ist Zusatz — nie ein Turnabbruch, aber sichtbar im Fact-Log
        s.setdefault("facts", []).append(make_fact(turn=turn, actorId="kernel", kind="diagnostic", event_kind="diagnostic", text=f"sceneState: {type(_scene_exc).__name__}: {str(_scene_exc)[:120]}", authority="kernel", sourceTurnId=source, truth=truth, scene=s.get("scene") or {}, validated=True))
    # V56: lifecycle reads the SAME interpreted speech Fact. A lexical
    # second pass must not turn a refusal/question into acceptance/request.
    lifecycle = {"request": "request", "proposal": "request", "promise": "commitment",
                 "acceptance": "acceptance", "refusal": "refusal", "revocation": "revoke"}
    for event in new_facts:
        if event.get("kind") != "speech":
            continue
        plan = event.get("plan") if isinstance(event.get("plan"), dict) else {}
        kind = lifecycle.get(plan.get("event_kind"))
        if plan.get("source") == "llm" and plan.get("refers_to"):
            # V60 (AMASTER §35, §34.1): a validated act in the same turn by the
            # same speaker, whose speech refers to a request addressed to her,
            # is bound as that request's response evidence.
            for af_ in s.get("facts") or []:
                if (isinstance(af_, dict) and af_.get("kind") == "action" and _scene.validiert(af_)
                        and str(af_.get("actorId")) == str(event.get("actorId"))
                        and str(af_.get("sourceTurnId") or "") == str(event.get("sourceTurnId") or "")
                        and not (af_.get("proposition_id") or af_.get("propositionId"))):
                    _bind_response_to_request(s, af_, plan.get("refers_to"), turn=turn)
        if (isinstance(proposals, dict) and isinstance(proposals.get("offenbarung"), list)
                and str(event.get("actorId") or "") == str(speaker.get("id") or "")):
            # V65H (AMASTER §34.1, §35): her speech, read with a literal quote
            # (app commit route, goal_disclosure_check), discloses the unsaid part.
            for _ob in proposals["offenbarung"][:2]:
                if isinstance(_ob, dict) and _ob.get("offenbart") is True:
                    _live = next((f for f in s.get("facts") or [] if isinstance(f, dict) and f.get("id") == event.get("id")), event)
                    apply_owner_disclosure(s, actor_id=str(event.get("actorId") or ""), goal_id=_ob.get("goalId"), fact=_live,
                                           turn=turn, beleg=_ob.get("beleg"))
        if (isinstance(proposals, dict) and isinstance(proposals.get("aussagen"), list)
                and str(event.get("actorId") or "") == str(speaker.get("id") or "")):
            # V65T (AMASTER §34.1, §36.3, §36.4; Plan v2 Schritt 3): her statement components, checked; a denial of an
            # event she experienced/saw/did is new evidence (truth.register_denial as executor).
            _live = next((f for f in s.get("facts") or [] if isinstance(f, dict) and f.get("id") == event.get("id")), event)
            _hear = [p for p in (present or []) if isinstance(p, dict) and str(p.get("id") or "") in set(_effective_hears(s, truth))]
            apply_statement_components(s, _live, proposals.get("aussagen"), proposals.get("ereignisse"), speaker=speaker,
                                       hearers=_hear, avatar_id=str(s.get("avatarId") or "") or None, turn=turn,
                                       figures=[p for p in (present or []) if isinstance(p, dict)])
        if plan.get("source") == "llm" and plan.get("refers_to") and _open_goal(s, plan.get("refers_to")) is not None:
            decided = apply_owner_goal_decision(s, actor_id=str(event.get("actorId") or ""), ref=plan.get("refers_to"),
                                                kind=str(plan.get("event_kind") or ""), fact_id=event.get("id"), turn=turn,
                                                source_turn_id=str(event.get("sourceTurnId") or "") or None)
            if decided is None:
                live = next((f for f in s.get("facts") or [] if isinstance(f, dict) and f.get("id") == event.get("id")), None)
                bound_goal = _bind_act_to_goal(s, live, plan.get("refers_to")) if live is not None else None
                if bound_goal is not None:
                    apply_goal_experience(s, str(bound_goal.get("ownerId") or ""), live, turn=turn)
            # V63 (AMASTER §34.1 "Effects je Komponente", §36.1): relating an
            # utterance to an open goal does not swallow its own lifecycle. Only
            # the owner's own goal decision, or an utterance without a lifecycle
            # kind, ends here. Session 13:39, T9: Tom's "Mach was riskantes"
            # (proposal, refers_to Tamara's stem goal) became goal evidence only;
            # no Proposition was opened, and Tamara's acceptance was bound to
            # the older open "Gehen wir ins kino".
            if decided is not None or not kind or plan.get("source") == "unresolved":
                continue
        if not kind and plan.get("source") == "llm" and plan.get("refers_to"):
            # V60 (AMASTER §35): a recipient's spoken answer the planner relates
            # to an open request is bound as evidence of that Proposition.
            live = next((f for f in s.get("facts") or [] if isinstance(f, dict) and f.get("id") == event.get("id")), None)
            if live is not None:
                _bind_response_to_request(s, live, plan.get("refers_to"), turn=turn)
            continue
        if not kind or plan.get("source") == "unresolved":
            continue
        if kind == "request" and plan.get("source") == "llm" and plan.get("refers_to"):
            # V61 (AMASTER §35 "dieselbe Angelegenheit", §36.1): an offer or
            # counter-request of the RECIPIENT that the planner relates to the
            # requester's open request answers that Proposition. It is bound as
            # response evidence; it does not open a second Proposition in the
            # other direction (session 22:52, T5: "ich mach alles was du sagst").
            _req = _open_request(s, plan.get("refers_to"))
            if (_req is not None and str(_req.get("targetId") or "") == str(event.get("actorId") or "")
                    and str(_req.get("actorId") or "") != str(event.get("actorId") or "")):
                live = next((f for f in s.get("facts") or [] if isinstance(f, dict) and f.get("id") == event.get("id")), None)
                if live is not None:
                    _bind_response_to_request(s, live, plan.get("refers_to"), turn=turn)
                continue
        ref = str(plan.get("refers_to") or "").strip().strip("[]")
        proposition_id = next((p.get("id") for p in s.get("propositions") or []
                               if ref and ref in (p.get("id"), p.get("text"), p.get("matter"))), None)
        if proposition_id is None and ref:
            # V63 (AMASTER §35 "Ein Goal bindet: … Proposition"): a reference
            # to a request goal names that goal's Proposition.
            _g_ref = next((g for g in s.get("goals") or [] if isinstance(g, dict) and str(g.get("id") or "") == ref), None)
            proposition_id = ((_g_ref or {}).get("proposition_id") or (_g_ref or {}).get("propositionId")) or None
        if proposition_id is None and not _conj.proposal_opens_matter(plan):
            # V62 (AMASTER §24.7 Ambiguität, §36.3 "an … ein Angebot gebunden"):
            # the planner's own durability says this "proposal" is a passing
            # remark or question, not an offer (PLAN_RULES: Vorschlag = commitment,
            # Frage/Smalltalk = utterance). Contradictory reading -> no NEW open
            # matter; answers to an existing matter (refers_to) are unaffected.
            # Comparison run 27.10.: "Ist das wirklich das, was du willst?"
            # became an open proposal that stayed in the brief.
            continue
        s = apply_proposition(s, actor_id=str(event.get("actorId") or ""),
                text=str(event.get("text") or ""), kind=kind,
                target_id=event.get("targetId"), proposition_id=proposition_id,
                source_turn_id=source, truth=truth, world=world,
                time_window=(plan.get("temporal") or {}).get("label") or None,
                fact_id=event.get("id"), turn=turn,
                matter=str(plan.get("summary") or "") if plan.get("source") == "llm" else None,
                grenze=_resolve_grenze(s, plan.get("grenze"), present, event.get("actorId")) if plan.get("source") == "llm" else None)
    # V62 (AMASTER §24.2/§24.6 "Lexikon nur Kandidat", §34.1 Proposition je
    # Komponente "soweit sie fachlich gelten", §41.5): the former word-overlap
    # binder (_bind_unattached_facts_to_proposition: two shared words of five
    # letters bind ANY speech to an open Proposition) is removed. It bound Mara's
    # unrelated answers to her own open matter, which then counted as "touched
    # by the current stimulus" and returned to the brief every turn. Bindings
    # now come only from the planner's validated refers_to and the lifecycle path.
    if not skip_figure and str(truth.get("directive") or "").strip():
        # V65T (Entscheidung A): after a Regie-Vollzug, her own words are her reaction - a second, separate outcome.
        for _rf in [f for f in s.get("facts") or [] if isinstance(f, dict) and f.get("kind") == "speech"
                    and str(f.get("actorId")) == str(speaker.get("id")) and str(f.get("sourceTurnId") or "") == str(source or "")
                    and isinstance(f.get("regieOrder"), dict)]:
            record_regie_reaction(s, _rf, turn=turn, truth=truth)
    if not skip_figure and speaker.get("id"):
        sync_runtime_trust(s, speaker["id"], to_id=truth.get("target_id"))
    # R3.4 / B.7-Folge: nutze die pre-bound time (deterministisch
    # gleich), vermeidet Doppel-Berechnung und garantiert dass
    # s["time"] und Fact-time_tense konsistent sind.
    s["time"] = _pre_time
    s["currentState"] = reduce_current_state(s)
    sync_scene_state(s, world=world)
    fate = dict(s.get("fate") or {})
    pipe_on = bool((s.get("pipeline") or {}).get("fate", True))
    if pipe_on and (fate.get("enabled") is not False):
        derived, pressure = _derive_fate(s, world=world)
        if derived:
            fate["beat"] = derived
            fate["derived"] = True
            fate["lastShiftTurn"] = turn
        fate["pressure"] = max(float(fate.get("pressure") or 0), pressure)
        fate["enabled"] = True if fate.get("enabled") is None else fate.get("enabled")
        # R4.2 / B.34-Folge: mustNot-Initialisierung via Helper (thread-safe).
        _ensure_fate_mustNot(fate, world)
        s["fate"] = fate
    if response_only:
        s["pendingInputTurnId"] = None
    annotate_turn_rows(s, session, turn)   # V65T: display line on the rows of this commit
    return s


def rekey_session_graph(session: dict) -> dict:
    """New session id + new child ids, rewrite internal references. Character ids stay."""
    s = copy.deepcopy(session)
    s["id"] = uid("ses")
    # V69 (Audit9 P0-2): ids are identity only (uid). The order of the copy is its event order: each child list is put in
    # (turn, its position) order - stable, a list without turns keeps its order - and written in that order, so the
    # persisted insertion sequence the readers order by (repos._session_child_query) is the event order. V68 counted the
    # ids' time part into the future instead (ids.ordered_uids), so the next normal fact sorted before the imported ones.
    def _turn_of(x: dict) -> int:
        t = x.get("turn")
        return t if isinstance(t, int) and not isinstance(t, bool) else 0
    # V70 (Audit10 §4): the rows keep the writer's event position `seq` they carry (repos copy semantics); the copy's lists are
    # put in the readers' order - turn, position (rows without one first, in their order) - so a file whose lists come in
    # another order is read in the order it was committed in
    def _pos_of(x: dict) -> tuple:
        q = x.get("seq")
        return (1, q) if isinstance(q, int) and not isinstance(q, bool) else (0, 0)
    for _key in ("facts", "memories", "godFacts", "turns", "turnTruths", "propositions", "goals", "witnessKnowledge"):
        if isinstance(s.get(_key), list):
            s[_key] = [x for _i, x in sorted(enumerate(s[_key]), key=lambda ix: ((_turn_of(ix[1]), *_pos_of(ix[1])) if isinstance(ix[1], dict)
                                                                                  else (0, 0, 0), ix[0]))]

    def _ids(key: str, prefix: str) -> dict[str, str]:
        return {str(x.get("id")): uid(prefix) for x in (s.get(key) or []) if isinstance(x, dict) and x.get("id")}
    fact_map = _ids("facts", "fact")
    mem_map = _ids("memories", "mem")
    god_map = _ids("godFacts", "god")
    turn_map = _ids("turns", "ln")
    prop_map = _ids("propositions", "prop")
    goal_map = _ids("goals", "goal")
    tt_map = _ids("turnTruths", "tt")
    # V65F (AMASTER §19 Session duplizieren, §23, §34 Quellturn, §68 Nr. 30
    # Isolation; v2.1 E12–E14): "sourceTurnId" holds the TurnTruth id (tt_…),
    # not the turn row id (ln_…) — it was mapped with the row map only and kept
    # pointing to the OLD session's TurnTruth; WitnessKnowledge rows kept their
    # ids and the copy failed (SESSION_CHILD_ID_CONFLICT) once a witness existed.
    src_map = {**turn_map, **tt_map}

    def _m(old: Any, mapping: dict[str, str]) -> Any:
        if old is None or old == "":
            return old
        key = str(old)
        return mapping.get(key, old)

    for f in s.get("facts") or []:
        if not isinstance(f, dict):
            continue
        f["id"] = _m(f.get("id"), fact_map)
        f["sessionId"] = s["id"]
        new_prop = _m(f.get("propositionId") or f.get("proposition_id"), prop_map)
        f["propositionId"] = new_prop
        f["proposition_id"] = new_prop
        new_goal = _m(f.get("goalId") or f.get("goal_id"), goal_map)
        f["goalId"] = new_goal
        f["goal_id"] = new_goal
        new_resp = _m(f.get("respondsToFactId") or f.get("responds_to_fact_id"), fact_map)
        f["respondsToFactId"] = new_resp
        f["responds_to_fact_id"] = new_resp
        new_src = _m(f.get("sourceTurnId") or f.get("source_turn_id"), src_map)
        f["sourceTurnId"] = new_src
        f["source_turn_id"] = new_src
        if f.get("cause_fact_id") or f.get("causeFactId"):   # V65Z (A01)
            f["cause_fact_id"] = _m(f.get("cause_fact_id") or f.get("causeFactId"), fact_map)
            f.pop("causeFactId", None)
    for m in s.get("memories") or []:
        if not isinstance(m, dict):
            continue
        m["id"] = _m(m.get("id"), mem_map)
        m["sessionId"] = s["id"]
        fid = _m(m.get("factId") or m.get("fact_id"), fact_map)
        m["factId"] = fid
        m["fact_id"] = fid
        src = m.get("source")
        if src and str(src) in fact_map:
            m["source"] = fact_map[str(src)]
        if m.get("sourceTurnId") or m.get("source_turn_id"):
            msrc = _m(m.get("sourceTurnId") or m.get("source_turn_id"), src_map)
            m["sourceTurnId"] = msrc
            if "source_turn_id" in m:
                m["source_turn_id"] = msrc
    for g in s.get("godFacts") or []:
        if not isinstance(g, dict):
            continue
        g["id"] = _m(g.get("id"), god_map)
        src = _m(g.get("sourceTurnId") or g.get("source_turn_id"), src_map)
        g["sourceTurnId"] = src
        g["source_turn_id"] = src
    for t in s.get("turns") or []:
        if not isinstance(t, dict):
            continue
        t["id"] = _m(t.get("id"), turn_map)
        t["sessionId"] = s["id"]
    for tt in s.get("turnTruths") or []:
        if not isinstance(tt, dict):
            continue
        tt["id"] = _m(tt.get("id"), tt_map)
        tt["session_id"] = s["id"]
        tt["sessionId"] = s["id"]
        src = _m(tt.get("source_turn_id") or tt.get("sourceTurnId"), src_map)
        tt["source_turn_id"] = src
        tt["sourceTurnId"] = src
    for p in s.get("propositions") or []:
        if not isinstance(p, dict):
            continue
        p["id"] = _m(p.get("id"), prop_map)
    for g in s.get("goals") or []:
        if not isinstance(g, dict):
            continue
        g["id"] = _m(g.get("id"), goal_map)
        pid = _m(g.get("proposition_id") or g.get("propositionId"), prop_map)
        g["proposition_id"] = pid
        g["propositionId"] = pid
    for w in s.get("witnessKnowledge") or []:
        if not isinstance(w, dict):
            continue
        if w.get("id"):
            w["id"] = uid("wk")   # V65F: a child id belongs to exactly one session
        fid = _m(w.get("fact_id") or w.get("factId"), fact_map)
        w["fact_id"] = fid
        w["factId"] = fid
        src = _m(w.get("source_turn_id") or w.get("sourceTurnId"), src_map)
        w["source_turn_id"] = src
        w["sourceTurnId"] = src
    focus = s.get("focus")
    if isinstance(focus, dict):
        last_f = _m(focus.get("lastFactId") or focus.get("last_fact_id"), fact_map)
        focus["lastFactId"] = last_f
        focus["last_fact_id"] = last_f
        topic = _m(focus.get("topicId") or focus.get("topic_id"), prop_map)
        focus["topicId"] = topic
        focus["topic_id"] = topic
        last_g = _m(focus.get("lastGoalId") or focus.get("last_goal_id"), goal_map)
        focus["lastGoalId"] = last_g
        focus["last_goal_id"] = last_g
    # V68 (Audit8 B "Current-State-Folgen", found by the independent checker in the E2E: imported and duplicated sessions
    # kept 96 references to the SOURCE session's facts, TurnTruths and propositions - proposition evidence, the current
    # state, scene state, runtimes (causes, appraisals, attention), frames, claims, goals). Every reference of the copy
    # follows its row: any value or key that IS an old child id becomes the new id. One rule for the whole graph; the
    # field-by-field mapping above named only some fields. Ids are unique tokens; no other text equals one.
    allmap = {**fact_map, **mem_map, **god_map, **turn_map, **prop_map, **goal_map, **tt_map}

    def _all(o: Any) -> Any:
        if isinstance(o, dict):
            return {(allmap.get(k, k) if isinstance(k, str) else k): _all(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_all(v) for v in o]
        if isinstance(o, str):
            return allmap.get(o, o)
        return o
    return _all(s)


_KNOWING = ("heard", "seen", "affected", "informed")


def _knows_fact(session: dict, character_id: str, fact: dict) -> bool:
    """The figure has the content of this Fact: she did it, or her WitnessKnowledge grants it (heard/seen/affected/informed)."""
    cid, fid = str(character_id or ""), str(fact.get("id") or "")
    if cid and cid == str(fact.get("actorId") or ""):
        return True
    return any(str(w.get("character_id") or w.get("characterId") or "") == cid and str(w.get("fact_id") or w.get("factId") or "") == fid
               and w.get("access") in _KNOWING for w in session.get("witnessKnowledge") or [] if isinstance(w, dict))


REGIE_ACT_CANDIDATES_MAX = 40   # V65V: only the size of the selection reading's list (payload), never the search base


def regie_act_pool(session: dict, directed_id: Any, *, von_id: Any = None, an_id: Any = None) -> list[dict]:
    """V65V (Nachpruefung v1 K6, AMASTER §46.6 Z. 2596, §39): ALL committed acts the directed figure knows, narrowed to
    the bound doer/person, in commit order (turn, id). The canonical search base of an informing order - no foreground
    window (13 acts: the first was unreachable behind a last-12 cut). Read only."""
    did = str(directed_id or "")
    if not did:
        return []
    acts = [f for f in session.get("facts") or [] if isinstance(f, dict) and f.get("kind") == "action"
            and _scene.validiert(f) and f.get("event_kind") != "regie_vollzug" and f.get("id")
            and _knows_fact(session, did, f)
            and (not von_id or str(f.get("actorId") or "") == str(von_id))
            and (not an_id or str(f.get("targetId") or "") == str(an_id))]
    acts.sort(key=lambda f: (int(f.get("turn") or 0), str(f.get("id"))))
    return acts


# V65V (Nachpruefung v1 K2; AMASTER §46.6 Z. 2596 exakt angeordnet, §37 "das System rechnet"): the place in the order an
# instruction names is read like a date: the reading gives the literal word, the kernel grounds it in the instruction and
# computes the acts from the commit order. Closed inventory of German ordinal stems and number words (the same layer as
# temporal_from_fields' {heute: 0, morgen: 1, ...}); a word outside it binds nothing.
_ORDINAL_STEMS = {"erst": 1, "zweit": 2, "dritt": 3, "viert": 4, "fuenft": 5, "fünft": 5, "sechst": 6, "siebt": 7,
                  "neunt": 9, "zehnt": 10, "letzt": -1, "vorletzt": -2}   # no "acht": "achten" is also a verb
_COUNT_WORDS = {"zwei": 2, "drei": 3, "vier": 4, "fuenf": 5, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10}


_ORDINAL_WORD_RE = re.compile(r"(?<!\w)(vorletzt|letzt|erst|zweit|dritt|viert|fuenft|fünft|sechst|siebt|neunt|zehnt)(e|en|er|es|em)(?!\w)", re.I)


def regie_ordinal_words(instruction: str) -> list[str]:
    """V65V (§24.2 Z. 1110 Kandidatenerkennung, §24.6 Systemwortschatz ohne Wahrheitshoheit): the ordinal words of an
    instruction (closed inventory, see _ORDINAL_STEMS) - a candidate that the instruction restricts by order. Used only
    as a consistency check of the selection reading, never to select by itself. Read only."""
    return [m.group(0).casefold() for m in _ORDINAL_WORD_RE.finditer(str(instruction or ""))]


def _labels_match_order(instruction: str, sel: dict, pool: list[dict]) -> bool:
    """V65V: the picked acts of a label selection equal the acts the kernel computes from the instruction's ONE literal
    ordinal word (and one literal count word, if any) - the closed inventory of regie_order_selection. Read only."""
    got, why = regie_order_selection(instruction, {}, pool)
    return got is not None and [str(f.get("id")) for f in got] == [str(x) for x in (sel.get("factIds") or [])]


def regie_order_selection(instruction: str, sel: Any, pool: list[dict]) -> tuple[list[dict] | None, str | None]:
    """V65V (Nachpruefung v1 K2; AMASTER §37 "das System rechnet", §24.2 Z. 1110-1113): acts selected by place in order.
    Two keys: the selection reading says the instruction selects by place (sel), AND the kernel reads the place from the
    instruction's own words - exactly one ordinal word and at most one count word of the closed inventory. A word the
    reading quotes must have the same stem (else contradiction); a count it gives must equal the count word. The acts are
    then computed from the commit order of the pool. Returns (acts, None) or (None, reason). Read only."""
    if not isinstance(sel, dict):
        return None, "reihenfolge_ungebunden"
    words = regie_ordinal_words(instruction)
    stems = {re.fullmatch(r"(vorletzt|letzt|erst|zweit|dritt|viert|fuenft|fünft|sechst|siebt|neunt|zehnt)(e|en|er|es|em)?", w).group(1) for w in words}
    if not stems:
        return None, "reihenfolge_nicht_woertlich"
    if len(stems) != 1:
        return None, "reihenfolge_unklar"
    stem = next(iter(stems))
    rw = re.fullmatch(r"(vorletzt|letzt|erst|zweit|dritt|viert|fuenft|fünft|sechst|siebt|neunt|zehnt)(e|en|er|es|em)?",
                      str(sel.get("wort") or "").strip().casefold())
    if rw and rw.group(1) != stem:
        return None, "reihenfolge_widerspruch"
    pos = _ORDINAL_STEMS[stem]
    counts = {w for w in re.findall(r"(?<!\w)(\w+)(?!\w)", str(instruction or "").casefold()) if w in _COUNT_WORDS or w.isdigit()}
    if len(counts) > 1:
        return None, "anzahl_unklar"
    n = 1
    if counts:
        c = next(iter(counts))
        n = int(c) if c.isdigit() else _COUNT_WORDS[c]
        if n < 1 or abs(pos) != 1:
            return None, "anzahl_unklar"            # "die zweiten drei" etc.: not read
    if sel.get("anzahl") not in (None, "", n):
        try:
            if int(sel.get("anzahl")) != n:
                return None, "anzahl_widerspruch"
        except (TypeError, ValueError):
            return None, "anzahl_widerspruch"
    if not pool:
        return [], None
    if abs(pos) == 1:
        return (pool[:n] if pos > 0 else pool[-n:]), None
    idx = pos - 1 if pos > 0 else pos
    try:
        return [pool[idx]], None
    except IndexError:
        return None, "reihenfolge_ausserhalb"


def regie_taten_persons(session: dict, comp: dict, *, directed_id: Any, figures: list[dict] | None) -> tuple[str | None, str | None]:
    """V65T binding of an informing order's persons, kept as it was measured (Regie reading taten.von/an): exactly one cast
    figure each ("du" in a Regie order = the directed figure, as regie_order_line tells her); an open "an" is the one
    further figure the ordered segment names besides the directed figure and the addressee - else (None, None): never
    "all his acts" (§46.3 Z. 2565). V65U: only narrows the act candidates; the acts are picked one by one. Read only."""
    tat = comp.get("taten") if isinstance(comp, dict) and isinstance(comp.get("taten"), dict) else None
    if not tat or not str(tat.get("von") or "").strip():
        return None, None
    did = str(directed_id or "")
    cast = _session_cast(session, list(figures or []))

    def one(name: str) -> str | None:
        if not name:
            return None
        if name.strip().casefold() in ("du", "dich", "dir", "dein", "deine"):
            return did or None
        ids = _named_by_name_part(name, cast)
        return next(iter(ids)) if len(ids) == 1 else None

    von = one(str(tat.get("von") or ""))
    an = one(str(tat.get("an") or "")) if str(tat.get("an") or "").strip() else None
    if von and not str(tat.get("an") or "").strip():
        to = one(str(comp.get("adressat") or comp.get("ziel") or ""))
        seg = _named_by_name_part(str(comp.get("segment") or ""), cast) - {did, to, von}
        an = next(iter(seg)) if len(seg) == 1 else None
    if not von or not an:
        return None, None
    return von, an


def regie_act_candidates(session: dict, directed_id: Any, figures: list[dict] | None, *, von_id: Any = None, an_id: Any = None,
                         limit: int | None = None) -> tuple[list[str], dict[str, str]]:
    """V65U (AMASTER §24.2 Z. 1110-1113 Kandidaten -> Semantik -> Validierung, §46.2 Z. 2549, §46.6 Z. 2596 "exakt
    angeordnete Szenenwirkung", §39 nur gekanntes Wissen; Codegutachten v1 N5): the committed acts the directed figure
    KNOWS (did, saw, suffered, was informed of), newest `limit`, labelled T1..Tn in turn order - the candidates the Regie
    reading may pick from, by label. The same pattern as the formulation's [E#] map: the reading names labels, the kernel
    maps them to Fact IDs and validates them. Returns (lines for the reading, {label: factId}). Read only, no model."""
    did = str(directed_id or "")
    if not did:
        return [], {}
    cast = _session_cast(session, list(figures or []))
    names = {str(c.get("id") or ""): str(c.get("name") or "") for c in cast if isinstance(c, dict)}
    # V65V (K6): the whole pool; `limit` only when a caller asks for it explicitly (never for the search base)
    acts = regie_act_pool(session, did, von_id=von_id, an_id=an_id)
    if limit is not None:
        acts = acts[-max(0, int(limit)):]
    # the order among the acts of the same doer on the same person, as data (measured 30.10.: without it the reading
    # picked all three acts for "nur seine erste Beruehrung")
    pair_n: dict[tuple[str, str], int] = {}
    for f in acts:
        k = (str(f.get("actorId") or ""), str(f.get("targetId") or ""))
        pair_n[k] = pair_n.get(k, 0) + 1
    seen: dict[tuple[str, str], int] = {}
    lines, labels = [], {}
    for i, f in enumerate(acts, 1):
        lab = f"T{i}"
        labels[lab] = str(f.get("id"))
        a, t = str(f.get("actorId") or ""), str(f.get("targetId") or "")
        seen[(a, t)] = seen.get((a, t), 0) + 1
        n, tot = seen[(a, t)], pair_n[(a, t)]
        nth = f"{n}. von {tot}" + (", letzte" if n == tot and tot > 1 else "")
        # the act's own validated effect class (its turn's EffectPlan, provenance) as data for a selection by kind
        eff = f.get("effect") if isinstance(f.get("effect"), dict) else {}
        cls = _EFFECT_WIRKUNG.get(str(eff.get("effectKind") or "")) if _scene.validiert(eff) else None
        lines.append(f"{lab}: Turn {f.get('turn')}, Täter {names.get(a, a)}" + (f", an {names.get(t, t)}" if t else "")
                     + f" ({nth} Tat {names.get(a, a)}" + (f" → {names.get(t, t)}" if t else "") + ")"
                     + (f", Wirkung {cls}" if cls else "") + f": „{str(f.get('text') or '')[:110]}“")
    return lines, labels


REGIE_LABEL_PAGES_MAX = None   # V65X (Nachpruefung V65W E06): no page limit - every act of the pool is on a page (+1 call per 40)


def regie_pages(lines: list[str], labels: dict[str, str], *, size: int | None = None,
                max_pages: int | None = None) -> list[tuple[list[str], list[str]]]:
    """V65W (Tiefenpruefung v1 P02/C3; AMASTER §46.6 Z. 2596, §24.7): the candidate lines of a reading split into pages of
    `size` lines (REGIE_ACT_CANDIDATES_MAX) in commit order, each with the Fact IDs it shows - every act of the pool is
    shown on exactly one page, labels stay global (T1..Tn). At most `max_pages`; acts beyond them are on no page, so the
    writer sees that the key did not cover them (coverage, never a silent last-40 cut).
    V65X (Nachpruefung V65W E06): by default no page limit (REGIE_LABEL_PAGES_MAX = None) - the whole pool is read, +1 call
    per 40 acts; `max_pages` stays only as an explicit argument. Read only."""
    size = max(1, int(size or REGIE_ACT_CANDIDATES_MAX))
    _mp = max_pages if max_pages is not None else REGIE_LABEL_PAGES_MAX
    max_pages = max(1, int(_mp)) if _mp is not None else 10 ** 9
    out = []
    for i in range(0, len(lines), size):
        if len(out) >= max_pages:
            break
        page = lines[i:i + size]
        out.append((page, [labels[ln.split(":", 1)[0]] for ln in page if ln.split(":", 1)[0] in labels]))
    return out


def regie_label_key(pages: list[tuple[list[str], list[str]]], answers: list[Any], labels: dict[str, str]) -> tuple[list[str], list[str]]:
    """V65W (C3): the label key over all pages - (Fact IDs named, Fact IDs the key SAW). A page whose reading failed or
    named a label it was not shown counts as not seen (its acts are not covered). Read only."""
    named, seen = [], []
    for (page, ids), ans in zip(pages, answers):
        shown = {ln.split(":", 1)[0] for ln in page}
        if not isinstance(ans, list) or not all(str(x) in shown for x in ans):
            continue
        seen += ids
        named += [labels[str(x)] for x in ans if str(x) in labels]
    return list(dict.fromkeys(named)), list(dict.fromkeys(seen))


def regie_content_candidates(session: dict, directed_id: Any, *, von_id: Any = None, an_id: Any = None,
                             wirkung: Any = None) -> tuple[list[str], dict[str, str]]:
    """V65W (Tiefenpruefung v1 P01/C2; AMASTER §46.6 Z. 2596 "exakt angeordnete Szenenwirkung", §24.2 Z. 1110-1113): the
    acts of the pool whose OWN validated effect class is the named kind - only their wording, labelled K1..Kn - for the
    separate content reading (does the instruction's word name exactly this act?). The class narrows, the content reading
    decides among acts of the same class (a pinch and a blow are both "gewalt"). Read only, no model."""
    cls = str(wirkung or "")
    if cls not in _WIRKUNG_EFFECT:
        return [], {}
    acts = [f for f in regie_act_pool(session, directed_id, von_id=von_id, an_id=an_id)
            if _EFFECT_WIRKUNG.get(str(((f.get("effect") or {}) if isinstance(f.get("effect"), dict) else {}).get("effectKind") or "")) == cls
            and _scene.validiert((f.get("effect") or {}) if isinstance(f.get("effect"), dict) else {})]
    lines, labels = [], {}
    for i, f in enumerate(acts, 1):
        lab = f"K{i}"
        labels[lab] = str(f.get("id"))
        lines.append(f"{lab}: „{str(f.get('text') or '')[:160]}“")
    return lines, labels


def execute_regie_information(session: dict, order: dict, *, regie_fact: dict, truth: dict, figures: list[dict] | None,
                              turn: int) -> dict:
    """V65T (AMASTER §27.5 Z. 1409-1415 "Regie bindend, keine Figurenrede", §46.2 "setzt oder erzwingt", §46.4, §46.6
    "exakt angeordnete Szenenwirkung ... committen", §34.2/§34.3 Provenienz, §39 WitnessKnowledge, §38 Memory;
    Entscheidung A mit Korrektur, 30.10.): an ordered INFORMING speech ("Johann informiert Alrik ueber seine Taten an
    Mara") is executed by this Regie writer as a visible scene effect - no invented words of the figure:
      - content: V65U (Codegutachten v1 N5, §46.3 Z. 2565 "Unklarer Scope darf nicht globalisiert werden", §24.7 Z. 1254):
        exactly the acts the reading picked by label from regie_act_candidates (taten.factIds, mapped in the app);
        each is checked here (committed, validated act, known to the informant). No label -> nothing is executed
        (inhalt_ungebunden); never "all acts from X to Y";
      - recipient: the bound addressee, present, not the informant;
      - writes: a visible action Fact "Regie-Vollzug: X informiert Y ueber ..." (causeFactId = Regie Fact, payload =
        the act IDs), WitnessKnowledge `informed` on every transferred act for the recipient and for present hearers
        who did not know it, their memories ("erfahren", factId = the act), the informant's own memory, a turn row
        marked byRegie; absent figures get nothing;
      - one lifecycle entry "regie_wirkung" at the Regie Fact: vollzogen | teilweise | nicht_vollzogen (+ Grund).
    The figure's own following speech is her reaction (lifecycle "figurenreaktion", see record_regie_reaction); a
    refusal there does not undo this effect. Returns the outcome."""
    actor = str(order.get("actorId") or "")
    to = str(order.get("targetId") or "")
    present = {str(x) for x in ((session.get("scene") or {}).get("presentIds") or [])}
    cast = _session_cast(session, list(figures or []))
    names = {str(c.get("id") or ""): str(c.get("name") or "") for c in cast if isinstance(c, dict)}
    out: dict[str, Any] = {"ergebnis": "nicht_vollzogen", "grund": None, "informantId": actor, "empfaengerId": to or None,
                           "actFactIds": [], "vollzugFactId": None, "regieFactId": regie_fact.get("id")}
    tat = order.get("taten") if isinstance(order.get("taten"), dict) else None
    # V65V (Nachpruefung v1 K2/K6; AMASTER §46.3 Z. 2565, §46.6 Z. 2596, §24.7 Z. 1254, §37 "das System rechnet"): the
    # acts are determined HERE from the canonical pool (all acts the informant knows, bound doer/person), by the
    # structure the selection reading gave: alle | reihenfolge (kernel computes the place in the commit order from the
    # literal ordinal) | bestimmte (picked labels, each checked against the act's own validated effect class). A valid
    # Fact ID alone never decides; without a bound selection nothing is executed.
    sel = (tat or {}).get("auswahl") if isinstance((tat or {}).get("auswahl"), dict) else None
    # V65V (Nachpruefung v1 K2): when the app read both keys (structure + labels), the acts must be the SAME by both;
    # `kennungen` = the label key's Fact IDs (None = not read, e.g. tests of a single key)
    _key2 = (tat or {}).get("kennungen") if isinstance((tat or {}).get("kennungen"), list) else None
    pool = regie_act_pool(session, actor, von_id=(tat or {}).get("vonId"), an_id=(tat or {}).get("anId")) if tat and (tat or {}).get("vonId") else []
    by_pool = {str(f.get("id")): f for f in pool}
    acts: list[dict] = []
    out["auswahl"] = {k: v for k, v in (sel or {}).items() if k in ("art", "wort", "anzahl_wort", "wirkung", "beleg")} or None
    if not tat:
        out["grund"] = "inhalt_ungebunden"
    elif not (tat or {}).get("vonId"):
        out["grund"] = "person_ungebunden"
    elif sel is None or sel.get("art") not in ("alle", "reihenfolge", "bestimmte"):
        out["grund"] = "auswahl_ungebunden"
    elif (sel["art"] != "reihenfolge" and regie_ordinal_words(str(order.get("segment") or ""))
          and _key2 is not None and _labels_match_order(str(order.get("segment") or ""), {"factIds": _key2}, pool)):
        # the instruction's literal place (kernel inventory) and the label key name the same acts; the structure key read it
        # otherwise - two of the three agree on exactly these acts, computed by the kernel from the commit order
        acts = list(regie_order_selection(str(order.get("segment") or ""), {}, pool)[0] or [])
        out["auswahlKorrigiert"] = "reihenfolge"
    elif sel["art"] != "reihenfolge" and regie_ordinal_words(str(order.get("segment") or "")) and not (
            sel["art"] == "bestimmte" and _labels_match_order(str(order.get("segment") or ""), sel, pool)):
        # V65V (Nachpruefung v1 K2): the instruction names a place in the order ("NUR ueber seine ERSTE Tat"); a reading
        # that selected otherwise is accepted only when its picked acts are EXACTLY the acts the kernel computes from that
        # literal place (two keys agree) - else nothing is executed (no guessed act)
        out["grund"] = "auswahl_widerspricht_reihenfolge"
    elif sel["art"] == "bestimmte" and regie_ordinal_words(str(order.get("segment") or "")):
        # the labels equal the place the instruction names: the selection is by place, not by kind (no kind check)
        acts = [by_pool[str(x)] for x in sel.get("factIds") or [] if str(x) in by_pool]
    elif sel["art"] == "alle":
        acts = list(pool)
    elif sel["art"] == "reihenfolge":
        got, why = regie_order_selection(str(order.get("segment") or ""), sel, pool)
        if got is None:
            out["grund"] = why
        else:
            acts = got
    else:
        picked = [str(x) for x in (sel.get("factIds") or []) if str(x)]
        cls = str(sel.get("wirkung") or "")
        beleg = str(sel.get("beleg") or "").strip()
        _cls_of = lambda f: _EFFECT_WIRKUNG.get(str(((f.get("effect") or {}) if isinstance(f.get("effect"), dict) else {}).get("effectKind") or ""))  # noqa: E731
        # V65W (Tiefenpruefung v1 P01/C2; AMASTER §46.6 Z. 2596 "exakt angeordnete Szenenwirkung", §24.2 Z. 1110-1113,
        # §24.7): a kind of act named by the instruction's own word is executed only for the acts whose CONTENT that word
        # names - the separate content reading (taten.inhalt, server-side) over all pool acts of the validated class. The
        # class alone cannot tell a pinch from a blow (both "gewalt"). Without that reading: nicht_vollzogen, visible.
        inh = (tat or {}).get("inhalt") if isinstance((tat or {}).get("inhalt"), dict) else None
        if sel.get("unvollstaendig"):
            out["grund"] = "auswahl_unvollstaendig"
        elif sel.get("unbekannt"):
            out["grund"] = "tat_kennung_ungueltig"
        elif (picked or sel.get("ereignisse")) and not picked:
            out["grund"] = "taten_nicht_einzeln_gebunden"
        elif not beleg or beleg.casefold() not in str(order.get("segment") or "").casefold():
            out["grund"] = "auswahl_beleg_nicht_woertlich"
        elif cls not in _WIRKUNG_EFFECT or not cls:
            out["grund"] = "tat_art_ungebunden"
        elif picked and any(i not in by_pool for i in picked):
            out["grund"] = "tat_kennung_ungueltig"
        elif picked and any(_cls_of(by_pool[i]) != cls for i in picked):
            # the named kind must be the acts' OWN validated effect class (their turn's EffectPlan), not only a label
            out["grund"] = "tat_art_widerspricht_fakt"
        else:
            _clines, _clabels = regie_content_candidates(session, actor, von_id=(tat or {}).get("vonId"), an_id=(tat or {}).get("anId"), wirkung=cls)
            of_kind = [by_pool[i] for i in _clabels.values() if i in by_pool]
            if inh is None:
                out["grund"] = "inhalt_ungeprueft"
            elif _seg_norm(inh.get("beleg")) != _seg_norm(beleg):
                out["grund"] = "inhalt_beleg_abweichend"
            elif not {str(f.get("id")) for f in of_kind} <= {str(x) for x in (inh.get("geprueft") or [])}:
                out["grund"] = "inhalt_unvollstaendig"
            else:
                meant_ids = {str(x) for x in (inh.get("factIds") or [])}
                meant = [f for f in of_kind if str(f.get("id")) in meant_ids]
                out["inhalt"] = {"beleg": beleg[:80], "factIds": [str(f.get("id")) for f in meant]}
                if picked and sorted(dict.fromkeys(picked)) != sorted(str(f.get("id")) for f in meant):
                    out["grund"] = "auswahl_schluessel_uneinig"
                else:
                    acts = meant
    acts.sort(key=lambda f: (int(f.get("turn") or 0), str(f.get("id"))))
    _cov = (tat or {}).get("kennungenGeprueft") if isinstance((tat or {}).get("kennungenGeprueft"), list) else None
    if out["grund"] is None and acts and _key2 is not None and _cov is not None and not (
            {str(f.get("id")) for f in pool} <= {str(x) for x in _cov}):
        # V65W (Tiefenpruefung v1 P02/C3): the label key did not see every act of the pool (a page not read, or more acts
        # than its pages) - its agreement cannot be judged, nothing is executed (no truncation taken as the truth)
        out["grund"] = "auswahl_unvollstaendig"
        out["kennungen"] = [str(x) for x in _key2][:12]
        acts = []
    if out["grund"] is None and acts and _key2 is not None:
        k2 = [str(x) for x in _key2]
        # V65V: when both keys were read, the acts must be the SAME by both. V65W (C2): also for a kind - the content key
        # already decided which acts of the class the word names; the label key must name exactly those (no narrowing)
        if sorted(dict.fromkeys(k2)) != sorted(str(f.get("id")) for f in acts):
            out["grund"] = "auswahl_schluessel_uneinig"
        if out["grund"] is not None:
            out["kennungen"] = k2[:12]
            acts = []
    out["gewaehlt"] = list((sel or {}).get("ereignisse") or [])[:12]
    if out["grund"] is None and not acts:
        out["grund"] = "keine_taten"
    elif out["grund"] is None and (not to or to == actor or to not in present):
        out["grund"] = "empfaenger_nicht_anwesend_oder_ungebunden"
    _pairs = {(str(f.get("actorId") or ""), str(f.get("targetId") or "")) for f in acts}
    von, an = next(iter(_pairs)) if len(_pairs) == 1 else (None, None)
    known = [f for f in acts if _knows_fact(session, actor, f)] if out["grund"] is None else []
    if out["grund"] is None and not known:
        out["grund"] = "informant_kennt_sie_nicht"
    if known:
        # V65U (AMASTER §39 Z. 2089 "Wer hoerte es?", Z. 2095; Codegutachten v1 N3): the turn's hearers from the one
        # reader (_effective_hears) - an explicitly empty list stays empty, it is not "missing".
        hearers = [h for h in _effective_hears(session, truth) if str(h) in present and str(h) not in (actor, "")]
        an_name = names.get(an or "", an or "")
        listing = "; ".join(f"Turn {f.get('turn')} „{str(f.get('text') or '')[:70]}“" for f in known[:6])
        if von:
            about = (f"die Taten von {names.get(von, von)}" if von != actor else "die eigenen Taten") + (f" an {an_name}" if an else "")
        else:
            about = "diese Taten"
        text = f"Regie-Vollzug: {names.get(actor, actor)} informiert {names.get(to, to)} über {about}: {listing}"
        vf = make_fact(turn=turn, actorId=actor, targetId=to, kind="action", event_kind="regie_vollzug", text=text[:600],
                       authority="regie", sourceTurnId=truth.get("id"), truth=truth, scene=session.get("scene") or {},
                       source_type="regie", witnessedBy=list(dict.fromkeys([actor, to, *[str(h) for h in hearers]])),
                       payload={"kind": "regie_vollzug", "regieFactId": regie_fact.get("id"), "actFactIds": [str(f.get("id")) for f in known],
                                "vonId": von, "anId": an, "empfaengerId": to})
        vf["speech_act"] = "act"
        vf["causeFactId"] = regie_fact.get("id")
        vf["effect"] = {"effectKind": None, "validated": False, "regieVollzug": True}
        session.setdefault("facts", []).append(vf)
        record_witness(session, character_id=actor, fact_id=vf["id"], access="performed", source_turn_id=truth.get("id"), turn=turn)
        for cid in dict.fromkeys([to, *[str(h) for h in hearers]]):
            if cid and cid != actor:
                record_witness(session, character_id=cid, fact_id=vf["id"], access="heard", source_turn_id=truth.get("id"), turn=turn)
        for cid in dict.fromkeys([to, *[str(h) for h in hearers]]):
            if not cid or cid == actor:
                continue
            for f in known:
                if _knows_fact(session, cid, f):
                    continue
                record_witness(session, character_id=cid, fact_id=str(f.get("id")), access="informed", source_turn_id=truth.get("id"), turn=turn)
                session.setdefault("memories", []).append(make_memory(
                    characterId=cid, kind="erfahren", salience=0.6, turn=turn, witnesses=[cid], layer="session", truthStatus="canon",
                    text=(f"{names.get(actor, actor)} (Regie-Vollzug, Turn {turn}): {names.get(von, von)} → {names.get(str(f.get('targetId') or ''), '')}"
                          f", Turn {f.get('turn')}: {str(f.get('text') or '')[:120]}")[:200],
                    source="regie_vollzug", factId=str(f.get("id")), sourceTurnId=truth.get("id"),
                    sessionId=session.get("id"), worldId=session.get("worldId")))
        session.setdefault("memories", []).append(make_memory(
            characterId=actor, kind="getan", salience=0.6, turn=turn, witnesses=[actor], layer="session", truthStatus="canon",
            text=text[:200], source="regie_vollzug", factId=vf["id"], sourceTurnId=truth.get("id"),
            sessionId=session.get("id"), worldId=session.get("worldId")))
        session.setdefault("turns", []).append({
            "id": _next_id("ln", session), "turn": turn, "speakerId": actor, "speakerName": names.get(actor, actor),
            "role": "character", "speech": "", "action": text[:300], "firedSpaces": [], "byRegie": True,
            "regieVollzug": {"factId": vf["id"], "actFactIds": [str(f.get("id")) for f in known], "empfaengerId": to}})
        out.update({"ergebnis": "vollzogen" if len(known) == len(acts) else "teilweise", "actFactIds": [str(f.get("id")) for f in known],
                    "vollzugFactId": vf["id"], "nichtGekannt": [str(f.get("id")) for f in acts if f not in known]})
    lf = make_fact(turn=turn, actorId="regie", targetId=actor, kind="lifecycle", event_kind="regie_wirkung",
                   text=f"Regie-Wirkung: {out['ergebnis']}" + (f" ({out['grund']})" if out.get("grund") else ""),
                   authority="regie", sourceTurnId=truth.get("id"), truth=truth, scene=session.get("scene") or {},
                   responds_to_fact_id=regie_fact.get("id"), validated=True,
                   payload={"kind": "lifecycle", "lifecycle": "regie_wirkung", **{k: out.get(k) for k in
                            ("ergebnis", "grund", "informantId", "empfaengerId", "actFactIds", "vollzugFactId", "regieFactId", "gewaehlt",
                             "auswahl", "inhalt")}})
    lf["causeFactId"] = regie_fact.get("id")
    lf["witnessedBy"] = []
    session.setdefault("facts", []).append(lf)
    out["lifecycleFactId"] = lf["id"]
    return out


def regie_outcomes(session: dict, regie_fact_id: Any) -> dict:
    """V65T: the two outcomes recorded at one Regie Fact (lifecycle entries regie_wirkung / figurenreaktion), newest
    each, for brief and UI. Read only."""
    rid = str(regie_fact_id or "")
    out: dict[str, Any] = {}
    for f in session.get("facts") or []:
        if not isinstance(f, dict) or f.get("kind") != "lifecycle" or str(f.get("causeFactId") or f.get("responds_to_fact_id") or "") != rid:
            continue
        if not _scene.validiert(f):   # V70 (Audit10 §2): only validated outcomes
            continue
        lc = str((f.get("payload") or {}).get("lifecycle") or f.get("event_kind") or "")
        if lc in ("regie_wirkung", "figurenreaktion"):
            out[lc] = {**{k: v for k, v in (f.get("payload") or {}).items() if k not in ("kind", "lifecycle")}, "factId": f.get("id"), "turn": f.get("turn")}
    return out


def record_regie_reaction(session: dict, speech_fact: dict, *, turn: int, truth: dict) -> dict | None:
    """V65T (Entscheidung A: zwei getrennte Ausgaenge; §27.5, §34.1, §36.3, §50): the directed figure's own words after a
    Regie-Vollzug are HER reaction, classified only from validated evidence of this speech - her plan's refusal, her
    statement components on exactly the transferred acts (apply_statement_components): widersprochen (bestreitet),
    verweigert (refusal), befolgt (bestaetigt every transferred act), ausgewichen (bewertet / verweigert_antwort /
    bestaetigt only some), else nicht_bestimmt. Lifecycle "figurenreaktion" at the Regie Fact; the Regie-Wirkung stays."""
    rid = str(speech_fact.get("causeFactId") or "")
    if not rid or not isinstance(speech_fact.get("regieOrder"), dict):
        return None
    w = regie_outcomes(session, rid).get("regie_wirkung")
    if not w or w.get("ergebnis") not in ("vollzogen", "teilweise"):
        return None
    acts = set(w.get("actFactIds") or [])
    comps = [a for a in speech_fact.get("aussagen") or [] if isinstance(a, dict) and a.get("status") == "validiert" and acts & set(a.get("factIds") or [])]
    plan = speech_fact.get("plan") if isinstance(speech_fact.get("plan"), dict) else {}
    confirmed = {i for a in comps if a.get("art") == "bestaetigt" for i in a.get("factIds") or []} & acts
    if any(a.get("art") == "bestreitet_geschehen" for a in comps):
        res = "widersprochen"
    elif plan.get("source") == "llm" and plan.get("event_kind") == "refusal":
        res = "verweigert"
    elif acts and confirmed == acts:
        res = "befolgt"
    elif comps:
        res = "ausgewichen"
    else:
        res = "nicht_bestimmt"
    lf = make_fact(turn=turn, actorId=str(speech_fact.get("actorId") or ""), targetId=speech_fact.get("targetId"), kind="lifecycle",
                   event_kind="figurenreaktion", text=f"Figurenreaktion: {res}", authority="character",
                   sourceTurnId=speech_fact.get("sourceTurnId"), truth=truth, scene=session.get("scene") or {},
                   responds_to_fact_id=speech_fact.get("id"), validated=True,
                   payload={"kind": "lifecycle", "lifecycle": "figurenreaktion", "ergebnis": res, "speechFactId": speech_fact.get("id"),
                            "regieFactId": rid, "aussagen": [{k: a.get(k) for k in ("art", "factIds")} for a in comps][:6]})
    lf["causeFactId"] = rid
    lf["witnessedBy"] = []
    session.setdefault("facts", []).append(lf)
    return {"ergebnis": res, "factId": lf["id"]}


def annotate_turn_rows(session: dict, before: dict, turn: int) -> None:
    """V65T (AMASTER §71.2.1/G12 Produktoberflaeche zeigt den kanonischen Stand, §34.3; Plan v2 Schritt 7): the outcome of
    this commit, read from its own Facts, as a display line (`ausgang`) on the turn rows THIS commit created - rows
    already in SQL are append-only and never rewritten (`before` = the session before this commit). Display only.
      - a body act: its consent standing AT the act when it was not unknown (act_consent: Grenze / Bitte / Widerruf);
      - her speech denying her own experience (gegenErleben);
      - the Regie-Vollzug row: the Regie-Wirkung; the directed figure's row: her Figurenreaktion;
      - a Regie row whose informing order was not executed: the reason."""
    old_ids = {str(t.get("id") or "") for t in (before.get("turns") or []) if isinstance(t, dict)}
    rows = [t for t in session.get("turns") or [] if isinstance(t, dict) and str(t.get("id") or "") not in old_ids]
    if not rows:
        return
    facts = [f for f in session.get("facts") or [] if isinstance(f, dict) and int(f.get("turn") or 0) == int(turn)]
    names = {str(c.get("id") or ""): str(c.get("name") or "") for c in _session_cast(session, [])}

    def add(row: dict, text: str) -> None:
        cur = [x for x in str(row.get("ausgang") or "").split(" · ") if x]
        if text not in cur:
            row["ausgang"] = " · ".join(cur + [text])

    def row_of(actor: str, *, regie: bool = False, vollzug: str | None = None) -> dict | None:
        for t in reversed(rows):
            if vollzug is not None:
                if (t.get("regieVollzug") or {}).get("factId") == vollzug:
                    return t
                continue
            if regie and t.get("role") == "regie":
                return t
            if not regie and str(t.get("speakerId") or "") == actor and not t.get("regieVollzug") and t.get("role") != "regie":
                return t
        return None

    for f in facts:
        k = f.get("kind")
        if k == "action" and f.get("event_kind") != "regie_vollzug":
            c = _scene.act_consent(session, f)
            if c and c.get("state") in ("declined", "accepted", "revoked"):
                who = names.get(str(f.get("targetId") or ""), "")
                txt = {"declined": f"Einwilligung: gegen die Grenze von {who} seit Turn {c.get('since')}",
                       "accepted": f"Einwilligung: von {who} erlaubt (Turn {c.get('since')})",
                       "revoked": f"Einwilligung: von {who} widerrufen (Turn {c.get('since')})"}[c["state"]]
                r = row_of(str(f.get("actorId") or ""))
                if r is not None:
                    add(r, txt)
        elif k == "speech" and isinstance(f.get("gegenErleben"), dict):
            r = row_of(str(f.get("actorId") or ""))
            if r is not None:
                _ts = [str(g.get("turn")) for g in session.get("facts") or [] if isinstance(g, dict) and str(g.get("id")) in set(f["gegenErleben"].get("factIds") or [])]
                add(r, "Aussage gegen eigenes Erleben (Turn " + ", ".join(_ts) + ")")
        elif k == "lifecycle" and f.get("event_kind") == "regie_wirkung":
            pl = f.get("payload") or {}
            if pl.get("vollzugFactId"):
                r = row_of("", vollzug=str(pl.get("vollzugFactId")))
                if r is not None:
                    add(r, f"Regie-Wirkung: {pl.get('ergebnis')} ({len(pl.get('actFactIds') or [])} Tat(en) an {names.get(str(pl.get('empfaengerId') or ''), '')})")
            else:
                r = row_of("", regie=True)
                if r is not None:
                    add(r, f"Regie-Wirkung: nicht vollzogen ({str(pl.get('grund') or '').replace('_', ' ')})")
        elif k == "lifecycle" and f.get("event_kind") == "figurenreaktion":
            r = row_of(str(f.get("actorId") or ""))
            if r is not None:
                add(r, f"Figurenreaktion auf die Regie: {str((f.get('payload') or {}).get('ergebnis') or '').replace('_', ' ')}")


def pending_attempts(session: dict) -> list[dict]:
    """V65U (Codegutachten v1 N4): the formulation attempts recorded for the OPEN input, oldest first. Each has its own
    id and the start id of the server process that ran it (repos.mark_pending_attempt). A V65T envelope (one unnamed
    attempt) reads as one attempt without process id - it can never count as running. Read only."""
    pid = str(session.get("pendingInputTurnId") or "")
    att = session.get("pendingInputAttempt") if isinstance(session.get("pendingInputAttempt"), dict) else {}
    if not pid or str(att.get("turnTruthId") or "") != pid:
        return []
    if isinstance(att.get("attempts"), list):
        return [dict(a) for a in att["attempts"] if isinstance(a, dict)]
    return [{k: att.get(k) for k in ("state", "error", "since", "at") if att.get(k) is not None}] if att.get("state") else []


def attempt_liveness(attempt: dict, *, boot_id: str | None = None, alive: Any = None) -> str:
    """V65W (Tiefenpruefung v1 P05/P07/C6; AMASTER §63 sichere Wiederaufnahme): whether the process of a `laeuft` attempt
    is still running - "ja" (this process, or another process proven alive by `alive`), "nein" (its process proven ended),
    "unklar" (not proven either way: a boot id alone is no proof of life). `alive(attempt)` -> True | False | None is the
    app's process proof (the start lock of that server process, app._attempt_alive); without it every attempt of another
    process is "unklar". Read only."""
    if not isinstance(attempt, dict) or attempt.get("state") != "laeuft":
        return "nein"
    if boot_id and str(attempt.get("boot") or "") == str(boot_id):
        return "ja"
    v = alive(attempt) if callable(alive) else None
    return "ja" if v is True else ("nein" if v is False else "unklar")


def pending_input_view(session: dict, now: datetime | None = None, *, boot_id: str | None = None, alive: Any = None) -> dict | None:
    """V65T (Plan v2 Schritt 6): the open input waiting for its response, with its attempt status, for the 409 message
    and the UI. Read only.
    V65U (AMASTER §24.2 Z. 1118 nicht bestaetigte Effects bleiben Audit, §63 Orchestrierung ohne Wahrheitshoheit;
    Codegutachten v1 N4): "running" is proven, not estimated - an attempt of THIS server process (boot_id) still in
    state laeuft. A restart ends every attempt of the old process; there is no timer. `attempt` = the newest attempt.
    V65W (Tiefenpruefung v1 P07/C6): an attempt of ANOTHER process counts as ended only when its end is proven
    (attempt_liveness, `alive`); proven alive or unclear it blocks closing (attemptRunning). `attemptUnklar` = only
    unclear attempts block: the UI says so and still offers to generate the answer again (the first commit of this
    TurnTruth wins, a second one is rejected by the existing pendingInputTurnId check)."""
    pid = str(session.get("pendingInputTurnId") or "")
    if not pid:
        return None
    tt = next((t for t in session.get("turnTruths") or [] if isinstance(t, dict) and str(t.get("id") or "") == pid), {}) or {}
    atts = pending_attempts(session)
    for a in atts:
        if a.get("state") == "laeuft":
            a["lebend"] = attempt_liveness(a, boot_id=boot_id, alive=alive)
    running = [a for a in atts if a.get("lebend") == "ja"]
    unclear = [a for a in atts if a.get("lebend") == "unklar"]
    return {"turnTruthId": pid, "text": str(tt.get("text") or "")[:200], "speakerId": tt.get("speaker_id"), "targetId": tt.get("target_id"),
            "turn": tt.get("turn") or session.get("turnIndex"), "attempt": (atts[-1] if atts else None), "attempts": atts[-8:],
            "attemptRunning": bool(running or unclear), "attemptUnklar": bool(unclear and not running)}


def close_pending_input(session: dict, turn_truth_id: str, *, now: datetime | None = None, boot_id: str | None = None,
                        alive: Any = None) -> dict:
    """V65T (AMASTER §24.2 Audit, §63; Plan v2 Schritt 6 "Eingabe ohne Antwort abschliessen", nur ausdruecklich und nur
    ohne laufenden Versuch): the open input stays committed as it was; its turn is closed WITHOUT a response, visibly
    (a turn row and an audit Fact naming the attempt state). No invented answer. A later response commit for this
    TurnTruth is then rejected by the existing check (pendingInputTurnId != source).
    V65W (C6): refused while any attempt is running in a live process or not proven ended (`alive`, attempt_liveness);
    the caller runs this inside its SQLite write transaction (app: _run_write, BEGIN IMMEDIATE)."""
    view = pending_input_view(session, now, boot_id=boot_id, alive=alive)
    if view is None or view["turnTruthId"] != str(turn_truth_id or ""):
        raise ValueError("no such open input")
    if view["attemptRunning"]:
        raise RuntimeError("attempt unclear" if view.get("attemptUnklar") else "attempt running")
    s = copy.deepcopy(session)
    turn = int(view.get("turn") or s.get("turnIndex") or 0)
    att = view.get("attempt") or {}
    why = {"provider_fehler": f"Provider-Fehler ({str(att.get('error') or '')[:80]})", "laeuft": "Versuch abgebrochen (Serverprozess beendet)",
           "formuliert": "formuliert, aber nicht gespeichert"}.get(str(att.get("state") or ""), "kein Antwortversuch erfasst")
    text = f"Eingabe ohne Antwort abgeschlossen — {why}."
    s.setdefault("facts", []).append(make_fact(turn=turn, actorId="kernel", kind="diagnostic", event_kind="antwort_ausgefallen", text=text,
                                               authority="kernel", sourceTurnId=view["turnTruthId"], scene=s.get("scene") or {}, validated=True,
                                               witnessedBy=[], payload={"kind": "antwort_ausgefallen", "attempt": att or None,
                                                                        "attempts": view.get("attempts") or []}))
    s.setdefault("turns", []).append({"id": _next_id("ln", s), "turn": turn, "speakerId": "system", "speakerName": "System",
                                      "role": "system", "speech": text, "firedSpaces": [], "closedInput": view["turnTruthId"]})
    s["pendingInputTurnId"] = None
    s["pendingInputAttempt"] = None
    return s


def apply_regie(
    session: dict,
    world: dict,
    text: str,
    *,
    target_id: str | None = None,
    place_name: str | None = None,
    actor_id: str | None = None,
    enter_name: str | None = None,
    enterName: str | None = None,
    present: list[dict] | None = None,
    components: dict | None = None,
    **_kw: Any,
) -> dict:
    """Director path. Authority=regie. Actor is the directed figure. enter_* never expands presentIds.

    V59C (AMASTER §27.5, §46.2, §46.6): with a planner reading (components),
    actor and target are bound explicitly and the ORDERED action is
    committed by this writer — Regie happens; it is not delegated to the
    language model. Ordered speech stays a directive for the figure's own
    wording. Explicit legacy syntax (Name: …, *…*) keeps the old path."""
    _ = (enter_name, enterName)
    s = copy.deepcopy(session)
    s["turnIndex"] = next_turn_index(s)
    turn = s["turnIndex"]
    figures = list(present or _kw.get("characters") or [])
    _ui_target = str(target_id or "") or None   # V65P: the operator's "Direktes Ziel" as chosen
    actor, target_id = resolve_regie_actor_target(
        actor_id=actor_id,
        target_id=target_id,
        text=text,
        figures=figures,
    )
    actor_name = next((f.get("name") for f in figures if f.get("id") == actor), None) or actor
    _sp0, _ac0 = parse_regie_components(text)
    directive_for = actor if (actor and not _sp0 and not _ac0 and str(text or "").strip()) else None
    regie_bound = None
    if not _sp0 and not _ac0 and isinstance(components, dict):
        _present_now = [str(x) for x in ((s.get("scene") or {}).get("presentIds") or [])]
        regie_bound = bind_regie_components(text, components, directed_id=actor, figures=figures,
                                            present_ids=_present_now, ui_target_id=_ui_target,
                                            avatar_id=str(s.get("avatarId") or "") or None)
        if regie_bound["actions"] or regie_bound["speech"]:
            first = (regie_bound["actions"] or regie_bound["speech"])[0]
            actor = first["actorId"]
            actor_name = next((f.get("name") for f in figures if f.get("id") == actor), None) or actor
            target_id = first.get("targetId") or None
            speakers = [x["actorId"] for x in regie_bound["speech"]]
            # V65J (AMASTER §46.2/§46.6, Prüfbericht v2.2 Kette D): only ORDERED
            # speech is formulated by a figure; acts are executed here and the
            # scene goes on through the gate. No figure is ordered otherwise.
            directive_for = speakers[0] if speakers else None
        else:
            # V65J (AMASTER §24.7 "nur sichtbarer Ambiguitätsstatus", §46.6): the
            # reading bound nothing - nothing happens, no figure gets the raw text
            # as an order (before: directiveFor stayed and the client forced the
            # figure to formulate the rejected instruction).
            regie_bound = {**regie_bound, "unused": True}
            directive_for = None
            # V65R (Pruefung v2.9 Q-A "Bindungsluecke"): nothing was bound, so the TurnTruth of
            # this Regie row names no target (before: the UI field, in your T27-T29 Johann himself).
            target_id = None
    truth = bind_from_session(
        s, role="regie", authority="regie", speaker_id=actor, target_id=target_id, input_kind="regie", text=text
    )
    attach_turn_truth(s, truth)
    s.setdefault("turns", []).append(
        {"id": _next_id("ln", s), "turn": turn, "speakerId": "regie", "speakerName": "Regie", "role": "regie", "speech": text, "firedSpaces": []}
    )
    _regie_unclear = bool(regie_bound is not None and regie_bound.get("unused"))
    _ueb = _kw.get("uebergang") if isinstance(_kw.get("uebergang"), dict) else None
    if not _regie_unclear:
        # V65W (C4): the scene transition of this instruction (V65Y: the director's explicit choice), never its words
        _scene.external_delta(s, kind="regie", text=text, turn=turn, target_id=actor, uebergang=_ueb)
    elif _ueb and _ueb.get("art") in ("neue_szene", "szene_endet"):
        # V65Y (Gesamtpruefung V65X N06; AMASTER §20 Z. 949, §46.2): the explicit transition holds also when the text bound
        # no figure act ("Später am Abend, im selben Saal.") - only the transition is applied, nothing else of the text
        _scene.external_delta(s, kind="uebergang", text=text, turn=turn, target_id=actor, uebergang=_ueb)
    if directive_for and s.get("turns"):
        s["turns"][-1]["directiveFor"] = directive_for
        s["turns"][-1]["directiveText"] = str(text).strip()[:300]
    fact = make_fact(
        turn=turn,
        actorId=actor,
        targetId=target_id,
        kind="regie",
        event_kind="regie",
        text=text,
        authority="regie",
        sourceTurnId=truth["id"],
        truth=truth,
        scene=s.get("scene") or {},
    )
    s.setdefault("facts", []).append(fact)
    new_facts: list[dict] = [fact]
    # B.3/B.4: Helper sammelt physical/relationship_drift-Facts für Audit-Trail
    if not _regie_unclear:
        s.setdefault("directorActions", []).append(
            {
                "id": uid("dir"),
                "actorId": actor,
                "targetId": target_id,
                "authority": "regie",
                "text": text,
                "turn": turn,
                "sourceTurnId": truth["id"],
            }
        )
    if regie_bound is not None and not regie_bound.get("unused"):
        executed: list[dict] = []
        _sees = [str(x) for x in (truth.get("sees_ids") or []) ]
        _present_now = set(str(x) for x in ((s.get("scene") or {}).get("presentIds") or []))
        # V92 Paket 19: the body state at the START of the instruction decides every ordered act's capability
        _rts0 = copy.deepcopy(s.get("runtimes") or {})
        for comp in regie_bound["actions"]:
            a_actor = str(comp["actorId"])
            a_target = comp.get("targetId")
            a_rt = _rts0.get(a_actor) or {}
            # V92 Paket 19 (Pruefung P18, die drei Regie-Wortfehler; AMASTER §46.2 "konkrete Szenenwirkung", §46.6 "exakt
            # angeordnete Szenenwirkung", §43.1): the body change of an ordered act is the change the server's reading and its
            # confirmation validated on the act's own words in the instruction, for exactly the bound actor - the former word
            # reading _regie_body_words is removed
            _seg = str(comp.get("segment") or comp["text"])
            _kchg, _kaud = authority_body_change(comp.get("koerperPruefung"), _seg, figur_id=a_actor, authority="regie")
            _wake = False
            if float(a_rt.get("consciousness") if a_rt.get("consciousness") is not None else 1) < 0.5:
                _a_fig = next((f for f in figures if isinstance(f, dict) and str(f.get("id") or "") == a_actor), None)
                _cap, _kchg, _wake = act_capability(a_rt, _seg, _kchg, _kaud, authority="regie",
                                                    names=_figure_name_forms(_a_fig) if _a_fig else [])
                impossible = _cap is not None
            else:
                impossible = capability_blocks_action(a_rt, comp["text"])
            absent_target = bool(a_target and a_target not in _present_now)
            invalid = "capability" if impossible else ("target_absent" if absent_target else None)
            # V79, AMASTER §§42, 43.1, 46.2: a parser's proposal is NOT a
            # completed director action. Reject objectively unresolved or
            # blocked physical effects *before* any physical/body writer.
            # A simple non-physical scene act may still be recorded when the
            # validated planner explicitly labelled it ohne_koerperwirkung.
            kind = comp.get("effectKind")
            # V92 Paket 19 (Pruefung P18 Entscheidung A: "Die eigene Koerperlage oder Schlaf kann ueber einen GETRENNTEN, validierten
            # eigenen Outcome wechseln"; §46.2/§46.6 exakt angeordnete Szenenwirkung): an ordered act whose effect class on ANOTHER
            # body is unclear is still the ordered outcome when its change of the actor's OWN body is validated (reading +
            # confirmation) - it is carried out with exactly that change and no effect on anybody else (effect class stays unclear)
            _nur_koerper = bool(_kchg) and not comp.get("effectValid")
            if invalid is None and not comp.get("effectValid") and not _nur_koerper:
                invalid = "wirkung_unklar"
            if invalid is None and kind in ("strike", "restrain", "free", "social", "approach", "withdraw"):
                if not a_target or str(a_target) == a_actor:
                    invalid = "zielperson_nicht_gebunden"
            if invalid is None and kind == "move":
                if not _known_destination(comp["text"], world):
                    invalid = "zielort_nicht_gebunden"
                else:
                    movement_block = _movement_block(s, a_actor, None, "move")
                    if movement_block:
                        invalid = "bewegung_blockiert:" + movement_block[0]
            if invalid is None and kind in ("approach", "withdraw"):
                movement_block = _movement_block(s, a_actor, str(a_target), kind)
                if movement_block:
                    invalid = "bewegung_blockiert:" + movement_block[0]
            af = make_fact(
                turn=turn,
                actorId=a_actor,
                targetId=a_target,
                kind="action",
                event_kind="action",
                text=comp["text"],
                authority="regie",
                sourceTurnId=truth["id"],
                truth=truth,
                scene=s.get("scene") or {},
                validated=invalid is None,
                rejection_reason=invalid,
                source_type="regie",
                witnessedBy=list(dict.fromkeys([a_actor] + [c for c in _sees if c in _present_now])),
            )
            af["speech_act"] = "act"
            af["effect"] = {"effectKind": comp.get("effectKind"),
                            "validated": bool(comp.get("effectValid")) and invalid is None}
            if invalid:
                af["effect"]["outcome"] = "blocked"
                af["effect"]["blockedBy"] = invalid
            if isinstance(comp.get("pruefung"), dict):
                af["effect"]["pruefung"] = copy.deepcopy(comp["pruefung"])
            if isinstance(comp.get("grenzBezug"), list):
                af["effect"]["grenzBezug"] = copy.deepcopy(comp["grenzBezug"])   # V65W (C1)
            if _wake:
                af["effect"]["nurAufwachen"] = True   # V92 Paket 19: an ordered waking - no effect on anybody else
            if _nur_koerper and invalid is None:
                af["effect"]["nurEigenerKoerper"] = True   # V92 Paket 19: the ordered outcome is the validated own-body change
            _mark_outcome_from_check(af["effect"])
            af["effect"]["koerperPruefung"] = _kaud
            s.setdefault("facts", []).append(af)
            new_facts.append(af)
            if invalid is None and not _wake:
                _apply_physical(
                    s, actor_id=a_actor, target_id=a_target, text=comp["text"], validated=True,
                    source_turn_id=truth["id"], authority="regie", truth=truth, turn=turn,
                    new_facts_out=new_facts,
                    effect_kind=comp.get("effectKind") if comp.get("effectValid") else None,
                    fact_id=af["id"],
                    world=world,
                )
                # Defense in depth: physical writer can fail closed as well.
                # Never call the body writer, create success memories, or call
                # record_physical after a blocked or unresolved outcome.
                effect_after = af.get("effect") or {}
                if effect_after.get("outcome") in ("blocked", "attempted"):
                    invalid = "wirkung_" + str(effect_after["outcome"])
                    af["validated"] = False
                    af["rejection_reason"] = invalid
                    af["effect"]["validated"] = False
                    af["effect"]["outcome"] = "blocked"
                    af["effect"]["blockedBy"] = invalid
                elif kind == "move" and not effect_after.get("destination"):
                    invalid = "zielort_nicht_gebunden"
                    af["validated"] = False
                    af["rejection_reason"] = invalid
                    af["effect"]["validated"] = False
                    af["effect"]["outcome"] = "blocked"
                    af["effect"]["blockedBy"] = invalid
            if invalid is None:
                # V92 Paket 19: the validated typed change of this ordered act through the ONE writer entry
                _w = write_body_change(s, a_actor, _kchg, fact_id=af["id"], turn=turn, authority="regie", text=comp["text"],
                                       actor_name=next((str(f.get("name") or "") for f in figures if isinstance(f, dict) and str(f.get("id") or "") == a_actor), None))
                if _w.get("fehler"):
                    af["effect"]["koerperFehler"] = _w["fehler"]
                # V63 (AMASTER §27.5): an executed Regie action is the scene's
                # latest physical beat (the same writer as for committed actions).
                _scene.record_physical(s, by=a_actor, target=(a_target if a_target in _present_now else None),
                                       text=comp["text"], turn=turn,
                                       effect_kinds=[str(comp.get("effectKind"))] if comp.get("effectValid") else [])
                a_name = next((f.get("name") for f in figures if f.get("id") == a_actor), None) or a_actor
                s.setdefault("memories", []).append(make_memory(
                    characterId=a_actor, kind="getan", text=comp["text"][:180], salience=0.65, turn=turn,
                    witnesses=[a_actor], layer="session", truthStatus="canon", source="regie",
                    factId=af["id"], sourceTurnId=truth["id"], sessionId=s.get("id"), worldId=s.get("worldId")))
                for cid in _present_now - {a_actor}:
                    access = witness_access(truth, af, cid)
                    if access not in ("affected", "seen"):
                        continue
                    s.setdefault("memories", []).append(make_memory(
                        characterId=cid, kind="erlebt" if access == "affected" else "gesehen",
                        text=comp["text"][:180] if access == "affected" else f"{a_name}: {comp['text'][:160]}",
                        salience=0.65, turn=turn, witnesses=[cid], layer="session", truthStatus="canon",
                        source="regie", factId=af["id"], sourceTurnId=truth["id"],
                        sessionId=s.get("id"), worldId=s.get("worldId")))
                s.setdefault("turns", []).append({
                    "id": _next_id("ln", s), "turn": turn, "speakerId": a_actor,
                    "speakerName": a_name, "role": "character", "speech": "",
                    "action": comp["text"], "firedSpaces": [], "byRegie": True,
                })
            executed.append({"actorId": a_actor, "targetId": a_target, "text": comp["text"],
                             "factId": af["id"], "validated": invalid is None, "rejection": invalid})
        # V65b (AMASTER §46.2 "Regie setzt ... eine konkrete Szenenwirkung", §15/
        # §44 the owner's authored rules interpret the events she experiences,
        # §46.6 no invented figure reaction): rule x fact also for an executed
        # Regie act, with the same kernel binding as for an input act. The
        # binding is evidence on the Fact and a Foreground candidate for the
        # owner's NEXT own reply (_active_reactions); nothing is executed.
        _rplans = _kw.get("rule_plans") if isinstance(_kw.get("rule_plans"), dict) else {}
        for e in executed:
            if not _scene.validiert(e) or not e.get("targetId"):
                continue
            _af = next((f for f in new_facts if isinstance(f, dict) and f.get("id") == e.get("factId")), None)
            if _af is not None:
                _bind_profile_triggers(s, _rplans.get(str(e["targetId"])) or {}, [_af], input_actor=str(e["actorId"]),
                                       owner_id=str(e["targetId"]), present=figures, turn=turn)
        # V65T (Entscheidung A): an ordered informing speech is executed here as a scene effect (no figure words).
        _vollzug = [execute_regie_information(s, sp_, regie_fact=fact, truth=truth, figures=figures, turn=turn)
                    for sp_ in regie_bound["speech"] if isinstance(sp_, dict) and sp_.get("taten")]
        regie_row = next((t for t in reversed(s.get("turns") or []) if t.get("role") == "regie" and t.get("turn") == turn), None)
        if regie_row is not None:
            regie_row["regieEffects"] = {"executed": executed,
                                          "speech": copy.deepcopy(regie_bound["speech"]),
                                          "unclear": copy.deepcopy(regie_bound["unclear"]),
                                          **({"vollzug": copy.deepcopy(_vollzug)} if _vollzug else {}),
                                          **({"uebergang": _ueb.get("art")} if _ueb and _ueb.get("art") != "keiner" else {})}
            regie_row["directiveFor"] = directive_for
            regie_row["directiveText"] = str(text).strip()[:300]
        spoken, action = None, None
    else:
        spoken, action = parse_regie_components(text)
        if regie_bound is not None:
            regie_row = next((t for t in reversed(s.get("turns") or []) if t.get("role") == "regie" and t.get("turn") == turn), None)
            if regie_row is not None:
                regie_row["regieEffects"] = {"executed": [], "speech": [], "unclear": copy.deepcopy(regie_bound.get("unclear") or []),
                                             **({"uebergang": _ueb.get("art")} if _ueb and _ueb.get("art") != "keiner" else {})}
    if regie_bound is not None:
        pass   # V65J: a semantic reading was made (bound or unclear) - no legacy delegation, no lexical body directive
    elif actor and not spoken and not action and str(text or "").strip():
        # V46: Eine Anweisung wie "Begrüße sie" wird von der Figur UMGESETZT (LLM-Turn mit verbindlicher
        # Anweisung, vom Client direkt nach diesem Commit gestartet) — nicht als leere Handlung verbucht.
        # Körperanweisungen (Handstand, hinsetzen …) wirken zusätzlich sofort über den Körper-Writer.
        directive_for = actor
        # V92 Paket 19 (Pruefung P18, Regie-Koerperkette): the former immediate body write from the instruction's words
        # (_BODY_*_RE + _regie_body_words) is removed - an instruction without a semantic reading changes no body state; the
        # figure carries the instruction out in her own turn, where her act is validated like every act.
    rt = copy.deepcopy((s.get("runtimes") or {}).get(actor) or {})
    gagged = not can_speak_now(rt)   # V92 Paket 19: one speech rule (asleep/unconscious/gagged/mute)
    if spoken and gagged:
        # V92 Paket 19 (Pruefung P18 N2): ordered words of a figure that cannot speak now are no speech - no "—" speech Fact
        # (V91 stored one as canonical speech); the Regie Fact shows why
        fact.setdefault("payload", {})["redeNichtMoeglich"] = {"text": str(spoken)[:200], "grund": "kann_jetzt_nicht_sprechen"}
        spoken = None
    if spoken:
        said = spoken
        s.setdefault("turns", []).append(
            {
                "id": _next_id("ln", s),
                "turn": turn,
                "speakerId": actor,
                "speakerName": actor_name,
                "role": "character",
                "speech": said,
                "action": None,
                "firedSpaces": [],
            }
        )
        sf = make_fact(
            turn=turn,
            actorId=actor,
            targetId=target_id,
            kind="speech",
            event_kind="speech",
            text=said,
            authority="character",
            sourceTurnId=truth["id"],
            truth=truth,
            scene=s.get("scene") or {},
        )
        s.setdefault("facts", []).append(sf)
        new_facts.append(sf)
    if action:
        # V92 Paket 19: the explicit *act* of the legacy syntax - its body change is the change the server's reading and its
        # confirmation validated on these words for exactly this actor (`koerper_lesung`); without them it changes no body
        _kchg, _kaud = authority_body_change(_kw.get("koerper_lesung"), action, figur_id=actor, authority="regie")
        _wake = False
        if float(rt.get("consciousness") if rt.get("consciousness") is not None else 1) < 0.5:
            _l_fig = next((f for f in figures if isinstance(f, dict) and str(f.get("id") or "") == str(actor or "")), None)
            _cap, _kchg, _wake = act_capability(rt, action, _kchg, _kaud, authority="regie",
                                                names=_figure_name_forms(_l_fig) if _l_fig else [])
            impossible = _cap is not None
        else:
            impossible = capability_blocks_action(rt, action)
        af = make_fact(
            turn=turn,
            actorId=actor,
            targetId=target_id,
            kind="action",
            event_kind="action",
            text=action,
            authority="character",
            sourceTurnId=truth["id"],
            truth=truth,
            scene=s.get("scene") or {},
            validated=not impossible,
            rejection_reason="capability" if impossible else None,
        )
        af["effect"] = {"koerperPruefung": _kaud, **({"nurAufwachen": True} if _wake else {})}
        s.setdefault("facts", []).append(af)
        new_facts.append(af)
        if not impossible:
            if not _wake:
                _apply_physical(
                    s,
                    actor_id=actor,
                    target_id=target_id,
                    text=action,
                    validated=True,
                    source_turn_id=truth["id"],
                    authority="regie",
                    truth=truth,
                    turn=turn,
                    new_facts_out=new_facts,
                    world=world,
                )
            _w = write_body_change(s, actor, _kchg, fact_id=af["id"], turn=turn, authority="regie", text=action, actor_name=actor_name)
            if _w.get("fehler"):
                af["effect"]["koerperFehler"] = _w["fehler"]
        if spoken:
            s["turns"][-1]["action"] = None if impossible else action
        else:
            s.setdefault("turns", []).append(
                {
                    "id": _next_id("ln", s),
                    "turn": turn,
                    "speakerId": actor,
                    "speakerName": actor_name,
                    "role": "character",
                    "speech": "",
                    "action": None if impossible else action,
                    "firedSpaces": [],
                }
            )
    if place_name:
        place = next((p for p in world.get("places") or [] if p.get("name", "").lower() == place_name.lower()), None)
        if place:
            s.setdefault("scene", {})["placeId"] = place["id"]
            s["scene"]["placeName"] = place["name"]
    if not _regie_unclear:
        s.setdefault("scene", {})["notes"] = text
    else:
        fact["validated"] = False
        fact["rejection_reason"] = "regie_unklar"
    _record_fact_witnesses(s, truth, new_facts, turn)
    commit_session_change(s, world=world, source_turn_id=truth["id"])
    annotate_turn_rows(s, session, turn)   # V65T
    return s


def regie_persisted_verdict(saved: dict, turn: int | None) -> dict:
    """Read-only Regie acceptance from the SAVED canonical scene, not an HTTP success.

    A model proposal or directive is not a fulfilled act. Verify the exact
    persisted SceneFact and physical scene beat; a speech order alone remains
    pending. A rejected/blocked act never becomes a successful result.
    """
    row = next((t for t in reversed(saved.get("turns") or []) if isinstance(t, dict)
                and t.get("role") == "regie" and t.get("turn") == turn), {}) or {}
    eff = row.get("regieEffects")
    if not isinstance(eff, dict):
        return {"status": "UNVERIFIED", "physicalActs": 0, "informingActs": 0, "pendingSpeech": 0, "unclear": 0}
    facts = {str(f.get("id")): f for f in saved.get("facts") or [] if isinstance(f, dict)}
    beat = (saved.get("sceneState") or {}).get("lastPhysicalBeat") or {}
    # One scene has ONE lastPhysicalBeat. Validating every action against that
    # single beat silently discards all but the final action of a multi-act
    # director instruction. Check each persisted byRegie action row separately
    # and anchor the LAST one to the current physical beat.
    action_rows = [t for t in (saved.get("turns") or []) if isinstance(t, dict)
                   and t.get("byRegie") is True and t.get("turn") == turn
                   and t.get("role") == "character" and t.get("action")]
    validated = []
    seen_rows = set()
    for e in eff.get("executed") or []:
        if not isinstance(e, dict) or e.get("validated") is not True:
            continue
        f = facts.get(str(e.get("factId") or ""))
        if (not isinstance(f, dict) or f.get("kind") != "action" or f.get("validated") is not True
                or f.get("rejection_reason") or str(f.get("actorId") or "") != str(e.get("actorId") or "")
                or str(f.get("targetId") or "") != str(e.get("targetId") or "")
                or str(f.get("text") or "") != str(e.get("text") or "")
                or f.get("turn") != turn):
            continue
        matching = next((j for j,t in enumerate(action_rows) if j not in seen_rows
                        and str(t.get("speakerId") or "") == str(e.get("actorId") or "")
                        and str(t.get("action") or "") == str(e.get("text") or "")), None)
        if matching is None:
            continue
        seen_rows.add(matching)
        validated.append(e)
    last = validated[-1] if validated else None
    beat_confirmed = bool(last and beat.get("turn") == turn
            and str(beat.get("by") or "") == str(last.get("actorId") or "")
            and str(beat.get("text") or "") == str(last.get("text") or "")[:160])
    valid = validated if beat_confirmed else []
    informing = []
    for item in eff.get("vollzug") or []:
        if not isinstance(item, dict) or item.get("ergebnis") not in ("vollzogen", "teilweise"):
            continue
        fid = str(item.get("vollzugFactId") or "")
        f = facts.get(fid)
        if f and f.get("validated") is True and f.get("event_kind") == "regie_vollzug":
            informing.append(item)
    pending = len(eff.get("speech") or [])
    rejected = bool(eff.get("unclear") or any(not isinstance(e, dict) or e.get("validated") is not True
                   for e in (eff.get("executed") or [])))
    committed = bool(valid or informing or eff.get("uebergang"))
    status = ("TEIL" if (pending or rejected) else "PASS") if committed else ("PENDING" if pending and not rejected else "REJECT")
    return {"status": status, "physicalActs": len(valid), "informingActs": len(informing),
            "pendingSpeech": pending, "unclear": len(eff.get("unclear") or []),
            "validatedActFactIds": [str(e.get("factId")) for e in valid]}


def _god_scope_key(scope: str) -> str:
    key = (scope or "").strip().lower()
    return _GOD_SCOPE_ALIAS.get(key, key)


def god_scope_axes(key: str) -> dict:
    """V65Y (AMASTER §46.4/§46.5): truth / persistence / epistemic scope and mutability of a God effect from its validated
    scope key (_god_scope_key). Read only."""
    k = str(key or "")
    return {"truthScope": "welt" if k == "world" else ("szene" if k in ("scene", "time", "action") else "session"),
            "persistenceScope": "dauerhaft" if k == "world" else "session",
            "epistemicScope": "ziel" if k in _GOD_PRIVATE_SCOPES else "anwesende",
            "mutability": "normal"}


def _write_god_relationship(session: dict, text: str, target_id: str, other_id: str, *, cause: Any = None) -> None:
    rels = session.setdefault("relations", [])
    rel = next((r for r in rels if r.get("fromId") == target_id and r.get("toId") == other_id), None)
    if rel is None:
        rel = {
            "fromId": target_id,
            "toId": other_id,
            "trust": 0.4,
            "closeness": 0.2,
            "fear": 0.1,
            "hostility": 0,
            "note": "",
            **({"sourceTurnId": str(cause)} if cause else {}),   # V65Y: the God turn that set it
        }
        rels.append(rel)
    low = (text or "").lower()
    if re.search(r"hass|feind|misstrau|ablehn", low):
        rel["hostility"] = max(float(rel.get("hostility") or 0), 0.4)
        rel["trust"] = min(float(rel.get("trust") or 0.4), max(0.0, float(rel.get("trust") or 0.4) - 0.2))
    elif re.search(r"liebe|vertraut|freund", low):
        rel["closeness"] = min(1.0, float(rel.get("closeness") or 0) + 0.3)
        rel["trust"] = min(1.0, float(rel.get("trust") or 0) + 0.2)
    else:
        rel["hostility"] = max(float(rel.get("hostility") or 0), 0.25)
        rel["note"] = text[:120]


def god_auto_state_scope(reading: Any) -> str:
    """Route a model's ambiguous `zustand` to the correct owner, fail closed.

    One wrong kind label cannot turn a body statement into a character-memory
    write with applied=true and an unchanged body. No keyword list is used.
    Returning body with no typed fields is intentional: the body writer rejects
    the fact with applied=false instead of claiming success.
    """
    if not isinstance(reading, dict):
        return "body"
    typed = ("schmerz", "beweglichkeit", "bewusstsein", "gefesselt", "geknebelt",
             "haltung", "schlaf", "sehen", "sprechen", "verletzung", "heilung")
    if any(reading.get(k) is not None for k in typed):
        return "body"
    return "character" if reading.get("bereich") == "nicht_koerper" else "body"


def apply_god(
    session: dict,
    text: str,
    scope: str,
    target_id: str | None = None,
    *,
    other_id: str | None = None,
    world: dict | None = None,
    natives: list[dict] | None = None,
    body_state: dict | None = None,
    uebergang: dict | None = None,
) -> dict:
    """Scope binds a canonical operation. Wirkung über zuständigen Owner (AMASTER 46).
    V65J: `body_state` = the typed body state a semantic reading took from this God
    body fact. V92 Paket 19: validated by authority_body_change (quote + confirmation + bound target) and written by the ONE
    body writer (write_body_change); {} = read, nothing typed (no numbers).
    V65W (C4): `uebergang` = the scene transition of this God instruction - V65Y (N06): the director's explicit choice;
    None = not read -> no scene transition (the text's words never decide it)."""
    s = copy.deepcopy(session)
    s["turnIndex"] = next_turn_index(s)
    turn = s["turnIndex"]
    truth = bind_from_session(s, role="god", authority="god", speaker_id="god", target_id=target_id, input_kind="god", text=text)
    attach_turn_truth(s, truth)
    key = _god_scope_key(scope)
    applied = False
    rejection = None
    if key == "knowledge":
        if target_id:
            s.setdefault("memories", []).append(
                make_memory(
                    characterId=target_id,
                    kind="gelesen",
                    text=text,
                    salience=0.8,
                    turn=turn,
                    witnesses=[target_id],
                    layer="session",
                    truthStatus="canon",
                )
            )
            applied = True
        else:
            rejection = "knowledge_requires_target"
    elif key == "relationship":
        if target_id and other_id:
            _write_god_relationship(s, text, target_id, other_id, cause=truth.get("id"))
            applied = True
        else:
            rejection = "relationship_requires_pair"
    elif key == "body":
        if not target_id:
            rejection = "body_requires_target"
        else:
            # V92 Paket 19 (Pruefung P18 N5-N7; AMASTER §46.1, §43, §43.1, §24.2/§24.7): God sets the body state through the
            # SAME contract and the ONE writer as every caller - the typed reading with its literal quote (mandatory) and the
            # confirmation reading at the quote, for exactly this target (authority_body_change), written by write_body_change
            # below with the God Fact as cause. The former direct runtime write (cur.update of god_body_values) is removed;
            # without a reading or with a rejected one the God fact is stored and the body state stays unchanged.
            _god_body = (authority_body_change(body_state, text, figur_id=target_id, authority="god")
                         if body_state is not None else (None, {"grund": "lesung_fehlt"}))
            applied = bool(_god_body[0])
            if not applied:
                rejection = "body_change_unconfirmed"
    elif key == "action":
        # V74 (AMASTER §46.1/§46.6): 'target_id' is the explicitly bound
        # ACTOR for an action, 'other_id' is its affected person. No action
        # is silently converted to a character memory or a free decision.
        cast = {str(c.get("id")) for c in (natives or []) if isinstance(c, dict)}
        present_ids = {str(i) for i in ((s.get("scene") or {}).get("presentIds") or [])}
        if not target_id or str(target_id) not in cast:
            rejection = "action_actor_unbound"
        elif str(target_id) not in present_ids:
            rejection = "action_actor_absent"
        elif other_id and (str(other_id) not in cast or str(other_id) not in present_ids):
            rejection = "action_target_absent_or_unknown"
        elif not text.strip():
            rejection = "action_empty"
        elif capability_blocks_action((s.get("runtimes") or {}).get(str(target_id)) or {}, text):
            rejection = "action_capability"
        else:
            applied = True
    elif key == "time":
        s.setdefault("scene", {})["time"] = text[:80]
        applied = True
    elif key == "scene":
        sc = s.setdefault("scene", {})
        sc["notes"] = text
        fg = list(sc.get("foreground") or [])
        if text and text not in fg:
            fg.append(text)
        sc["foreground"] = fg[-6:]
        applied = True
    elif key in ("world", "session", "character"):
        if key == "character" and not target_id:
            rejection = "character_requires_target"
        else:
            writes = s.setdefault("_godOwnerWrites", {})
            if key == "world":
                # B.5 (AMASTERv2 §46.1): God setzt eine bindende Tatsache.
                # Antwort muss ehrlich sein: applied=True mit konkretem Owner-Patch.
                # kernel_session_response liest _godOwnerWrites.worldCanon und patcht
                # worlds.canon. Kein "applied: False" mehr.
                writes["worldCanon"] = text
                applied = True
            elif key == "character" and target_id:
                writes["characterKnowledge"] = {"id": target_id, "text": text}
                s.setdefault("memories", []).append(
                    make_memory(
                        characterId=target_id,
                        kind="gelesen",
                        text=text,
                        salience=0.85,
                        turn=turn,
                        witnesses=[target_id],
                        layer="session",
                        truthStatus="canon",
                    )
                )
                applied = True
            elif key == "session":
                applied = True
            matters = list((s.get("scene") or {}).get("openMatters") or [])
            if text and text not in matters:
                s.setdefault("scene", {})["openMatters"] = matters[-5:] + [text]
    else:
        rejection = "unknown_scope"
    gf = {
        "id": uid("god"),
        "scope": scope,
        "targetId": target_id,
        "text": text,
        "turn": turn,
        "sourceTurnId": truth["id"],
        "applied": applied,
        # V65Y (Gesamtpruefung V65X N03; AMASTER §46.4 drei Scope-Achsen getrennt, §46.5 Session-Default, Welt/Dauer nur
        # bei ausdruecklicher Auswahl): the axes this God effect binds, derived from its validated scope key - the world
        # scope (UI choice) is objective and lasting, everything else holds in this session; a private scope (knowledge,
        # relationship, body, character) is known to its target only, the others to those who perceive it.
        **god_scope_axes(key),
    }
    if other_id:
        gf["otherId"] = other_id
    if key == "action":
        gf["actorId"] = target_id
        gf["targetId"] = other_id
    if rejection:
        gf["rejection_reason"] = rejection
    s.setdefault("godFacts", []).append(gf)
    fact = make_fact(
        turn=turn,
        actorId="god",
        targetId=target_id,
        kind="god",
        event_kind="god",
        text=f"[{scope}] {text}",
        authority="god",
        sourceTurnId=truth["id"],
        truth=truth,
        scene=s.get("scene") or {},
        payload={"text": text, "scope": scope, "kind": "god", "applied": applied},
        validated=applied,
        **({"witnessedBy": [target_id] if target_id else []} if key in _GOD_PRIVATE_SCOPES else {}),
    )
    s.setdefault("facts", []).append(fact)
    god_action_facts: list[dict] = []
    if applied and key == "action":
        # The God fact is the authoritative cause, the Action Fact the
        # actual scene event. The existing writers own beat and witness state.
        action_fact = make_fact(
            turn=turn, actorId=str(target_id), targetId=other_id,
            kind="action", event_kind="action", text=text, authority="god",
            sourceTurnId=truth["id"], truth=truth, scene=s.get("scene") or {},
            source_type="god", provenance="kernel", validated=True,
            payload={"kind": "action", "text": text, "sourceFactId": fact["id"],
                     "sourceTurnId": truth["id"], "godOrdered": True},
        )
        action_fact["cause_fact_id"] = fact["id"]
        s.setdefault("facts", []).append(action_fact)
        god_action_facts.append(action_fact)
        _scene.record_physical(s, by=str(target_id), target=other_id,
                               text=text, turn=turn, effect_kinds=[])
        actor_name = next((str(c.get("name") or "") for c in (natives or [])
                           if isinstance(c, dict) and str(c.get("id")) == str(target_id)), str(target_id))
        s.setdefault("memories", []).append(make_memory(
            characterId=str(target_id), kind="getan", text=text[:180],
            salience=0.65, turn=turn, witnesses=[str(target_id)],
            layer="session", truthStatus="canon", source="god",
            factId=action_fact["id"], sourceTurnId=truth["id"],
            sessionId=s.get("id"), worldId=s.get("worldId")))
        if other_id and str(other_id) != str(target_id):
            s.setdefault("memories", []).append(make_memory(
                characterId=str(other_id), kind="erlebt", text=text[:180],
                salience=0.65, turn=turn, witnesses=[str(other_id)],
                layer="session", truthStatus="canon", source="god",
                factId=action_fact["id"], sourceTurnId=truth["id"],
                sessionId=s.get("id"), worldId=s.get("worldId")))
        s.setdefault("turns", []).append({
            "id": uid("ln"), "turn": turn, "speakerId": str(target_id),
            "speakerName": actor_name, "role": "character", "speech": "",
            "action": text, "firedSpaces": [], "byGod": True,
            "sourceFactId": action_fact["id"],
        })
    # Only an actually applied God fact is a visible canonical dialogue turn.
    # Rejected proposals stay in the audit with validated=False, never as spoken truth.
    if applied and key != "body":
        s.setdefault("turns", []).append(
            {"id": uid("ln"), "turn": turn, "speakerId": "god", "speakerName": "Gott", "role": "god", "speech": text, "firedSpaces": []}
        )
    if god_action_facts:
        _record_fact_witnesses(s, truth, god_action_facts, turn)
    if applied:
        _record_fact_witnesses(s, truth, [fact], turn)
    # V25 UPL-B03/§16: Auch per God gesetztes Figurenwissen bekommt für genau
    # diese Figur Bedeutung (Runtime/Beziehung/Ziel), Ursache = God-Fact.
    if applied and key == "knowledge" and target_id and natives:
        stem = next((c for c in natives if isinstance(c, dict) and str(c.get("id")) == str(target_id)), None)
        if stem and str(target_id) != str(s.get("avatarId") or ""):
            apply_knowledge_effect(s, stem, text=text, fact_id=fact["id"], turn=turn, characters=natives, source="god", authority="god")
    # V34 (AMASTERv2 §46.1/§43): God-Tatsachen über den Körper werden kanonischer PhysicalState
    # mit Ursache (gebrochener Arm, Haltung, Bewusstsein, Sprech-/Sehfähigkeit), nicht nur Text.
    if key == "body" and target_id and body_state is None:
        # V92 Paket 18: no typed reading (no provider) - the God body fact stays a fact; its words set no body state. A
        # character-scope God fact ("zustand") never wrote a body state from a reading and now writes none from its words either.
        fact.setdefault("payload", {})["koerperNichtGelesen"] = True
    if key == "body" and target_id and body_state is not None:
        # V92 Paket 19: the validated typed God change through the ONE writer entry; the God Fact is its cause, the target the
        # only witness (a God fact about a body is not seen by the others); a rejected reading writes nothing (audit)
        _gchg, _gaud = _god_body
        fact.setdefault("payload", {})["koerper"] = copy.deepcopy(body_state)
        fact["payload"]["koerperPruefung"] = _gaud
        _w = write_body_change(s, str(target_id), _gchg, fact_id=fact["id"], turn=turn, authority="god", text=text,
                               vermerk=text, witnesses=[str(target_id)], actor_name=_name_of(str(target_id), natives or [], s))
        fact["payload"]["koerperGeschrieben"] = bool(_w.get("geschrieben"))
        if _w.get("fehler"):
            fact["payload"]["koerperFehler"] = _w["fehler"]
        # A successful reading is not a successful effect. The writer must
        # confirm the state mutation; there is no separate God body writer.
        if not _w.get("geschrieben"):
            applied = False
            rejection = "body_change_not_written"
    if key == "body":
        gf["applied"] = bool(applied)
        fact["validated"] = bool(applied)
        fact["payload"]["applied"] = bool(applied)
        if not applied:
            gf["rejection_reason"] = rejection or "body_change_unconfirmed"
            fact["rejection_reason"] = gf["rejection_reason"]
        else:
            _record_fact_witnesses(s, truth, [fact], turn)
            s.setdefault("turns", []).append(
                {"id": uid("ln"), "turn": turn, "speakerId": "god", "speakerName": "Gott", "role": "god", "speech": text,
                 "firedSpaces": [], "sourceFactId": fact["id"]}
            )
    if applied and key not in _GOD_PRIVATE_SCOPES:
        _scene.external_delta(s, kind="god", text=text, turn=turn, target_id=target_id, uebergang=uebergang)
    commit_session_change(s, world=world, source_turn_id=truth["id"])
    return s


def apply_fate(
    session: dict,
    *,
    seed_id: str | None = None,
    beat: str | None = None,
    pressure: float | None = None,
    proposal: dict | str | None = None,
    enabled: bool | None = None,
    world: dict | None = None,
) -> dict:
    """Story pressure / beat / seed only. No SceneFact, no speech, no world owner writes."""
    s = copy.deepcopy(session)
    fate = dict(s.get("fate") or {})
    if enabled is not None:
        fate["enabled"] = bool(enabled)
        pipe = dict(s.get("pipeline") or {})
        pipe["fate"] = bool(enabled)
        s["pipeline"] = pipe
    else:
        fate["enabled"] = True if fate.get("enabled") is None else fate.get("enabled")
    if seed_id is not None:
        fate["activeSeedId"] = seed_id
        fate["lastShiftTurn"] = int(s.get("turnIndex") or 0)
    if beat is not None:
        fate["beat"] = beat
    elif not fate.get("beat"):
        derived, pressure_boost = _derive_fate(s, world=world)
        if derived:
            fate["beat"] = derived
            fate["derived"] = True
            fate["pressure"] = max(float(fate.get("pressure") or 0), pressure_boost)
    # R4.2 / B.34-Folge: mustNot-Initialisierung via Helper (thread-safe).
    _ensure_fate_mustNot(fate, world)
    if pressure is not None:
        fate["pressure"] = max(0.0, min(1.0, float(pressure)))
    if proposal is not None:
        fate["proposal"] = dict(proposal) if isinstance(proposal, dict) else proposal
        fate["proposalCanonical"] = False
        props = dict(s.get("proposals") or {})
        props["fate"] = fate["proposal"]
        props["accepted"] = False
        s["proposals"] = props
    s["fate"] = fate
    return s


def _derive_fate(session: dict, world: dict | None = None) -> tuple[str | None, float]:
    """AMASTER §47: beat from world conflicts, goals, relations, memory, secrets, body, propositions, past beats."""
    bits: list[str] = []
    avatar_id = str(session.get("avatarId") or "")
    disrupt: list[str] = []
    for fact in reversed(list(session.get("facts") or [])):
        if not isinstance(fact, dict):
            continue
        auth = str(fact.get("authority") or "")
        kind = str(fact.get("kind") or "")
        if auth not in ("avatar", "teilnehmer") or kind not in ("speech", "action"):
            continue
        text = str(fact.get("text") or "").strip()
        if not text:
            continue
        actor = str(fact.get("actorId") or fact.get("actor_id") or "")
        if avatar_id and actor not in (avatar_id, "user") and auth != "avatar":
            continue
        if _RESIGN_RE.search(text) or re.search(r"gehe weg|nicht zurück", text, re.I):
            disrupt.append(f"Avataränderung: {text[:160]}")
        if len(disrupt) >= 2:
            break
    bits.extend(disrupt[:2])

    def _is_quote(txt: str) -> bool:
        # V31 (AMASTERv2 §47: Fate = Druck, nicht Rede): Romansätze/Zitate sind keine Beats.
        t = str(txt or "")
        return any(m in t for m in ('"', "„", "“", "”", "»", "«")) or bool(re.search(r"\b(beginnt|sagt|sagte|flüstert|fragt|antwortet|ruft)\s+(sie|er)\b", t, re.I))

    if isinstance(world, dict):
        for c in [x for x in list(world.get("conflicts") or []) if not _is_quote(str(x))][:4]:
            if c:
                bits.append(str(c)[:160])
        # V60b (AMASTER §47, §10 "Weltziele und Storyachsen", §68 Nr. 27): the
        # world editor writes `fateBeats` and `storyGoals`; Fate is their reader
        # (orientation and pressure, never figure knowledge, never avatar control).
        for seed in (list(world.get("fateSeeds") or []) + list(world.get("fateBeats") or []))[:4]:
            if isinstance(seed, dict) and seed.get("beat"):
                bits.append(str(seed["beat"])[:160])
            elif isinstance(seed, str) and seed.strip():
                bits.append(seed[:160])
        for goal in list(world.get("storyGoals") or world.get("worldGoals") or [])[:2]:
            if isinstance(goal, str) and goal.strip():
                bits.append(goal[:160])
            elif isinstance(goal, dict) and (goal.get("text") or goal.get("goal")):
                bits.append(str(goal.get("text") or goal.get("goal"))[:160])
        for secret in list(world.get("secretKnowledge") or world.get("secrets") or [])[:2]:
            if secret:
                bits.append(str(secret)[:160])
        for lim in list(world.get("knowledgeLimits") or world.get("knowledgeBounds") or [])[:2]:
            if lim:
                bits.append(str(lim)[:160])
    role = session.get("role")
    # V60 (AMASTER §27.3, §49.6): Fate reads figures' state by NAME, never
    # raw IDs, and never the avatar's own inner relationship (user-owned).
    _fn = lambda cid: (_name_of(cid, [], session) if "_name_of" in globals() else cid) or cid  # noqa: E731
    for r in session.get("relations") or []:
        if avatar_id and str(r.get("fromId") or "") == avatar_id:
            continue
        if float(r.get("hostility") or 0) >= 0.35:
            bits.append(f"Konflikt {_fn(r.get('fromId'))}/{_fn(r.get('toId'))}")
        elif float(r.get("fear") or 0) >= 0.5:
            bits.append(f"Angst {_fn(r.get('fromId'))} vor {_fn(r.get('toId'))}")
    # Goals are candidates only if a current, evidenced matter activates them.
    # Their mere presence cannot cycle Fate beats or cause obligatory dialogue.
    for p in session.get("propositions") or []:
        if p.get("status") == "open" and (p.get("matter") or p.get("text")):
            bits.append(str(p.get("matter") or p["text"]))
    for m in session.get("memories") or []:
        if m.get("kind") in ("unsicher", "verdraengt", "vergessen", "geglaubt", "bestritten"):
            if m.get("text"):
                bits.append(str(m["text"]))
    for cid, rt in (session.get("runtimes") or {}).items():
        if not isinstance(rt, dict):
            continue
        if float(rt.get("pain") or 0) >= 0.5:
            bits.append(f"Schmerz {_fn(cid)}")
        if float(rt.get("consciousness") or 1) < 0.5:
            bits.append(f"Bewusstsein {_fn(cid)}")
    matters = list((session.get("scene") or {}).get("openMatters") or [])
    bits.extend(str(x) for x in matters if x)
    # V31: Kein Zitat wird Beat — ein Romansatz im Fate-Feld verleitet das LLM, ihn nachzusprechen.
    bits = [b for b in bits if b and not _is_quote(str(b))]
    # V34 (AMASTERv2 §47: Fate liest Körperzustand, Wissenswirkung, Beziehungen): kanonische
    # Zustände der Anwesenden haben Vorrang vor Gesprächsabsichten.
    urgent: list[str] = []
    present_ids = list((session.get("scene") or {}).get("presentIds") or [])
    for cid in present_ids:
        rt = (session.get("runtimes") or {}).get(cid) or {}
        nm = _name_of(cid, [], session) if "_name_of" in globals() else cid
        if rt.get("injuries"):
            parts = ", ".join(str(i.get("part") or "") for i in rt["injuries"] if isinstance(i, dict))
            urgent.append(f"{nm} ist verletzt ({parts}) — Schmerz und Einschränkung wirken in jede Handlung")
        if rt.get("posture") in ("Handstand", "liegend", "kniend"):
            urgent.append(f"{nm} ist körperlich gebunden ({rt.get('posture')}) — jede Bewegung muss das erst ändern")
        if float(rt.get("consciousness") or 1) < 0.5:
            urgent.append(f"{nm} ist nicht bei Bewusstsein — die Szene kann nicht normal weitergehen")
        if float(rt.get("fear") or 0) >= 0.6 or float(rt.get("anger") or 0) >= 0.6:
            urgent.append(f"{nm} steht unter starkem Druck ({rt.get('emotion') or 'angespannt'}) — Flucht, Angriff oder Zusammenbruch liegen nahe")
    _st = session.get("sceneState") if isinstance(session.get("sceneState"), dict) else {}
    if _st and float(_st.get("escalation") or 0) >= 0.6:
        urgent.append(f"Die Szene ist eskaliert ({float(_st.get('escalation') or 0):.2f}) — der nächste Beat entscheidet, ob es kippt")
    recent_effects = [f for f in (session.get("facts") or []) if isinstance(f, dict) and f.get("event_kind") in ("knowledge_effect", "relationship_drift", "body_state")][-4:]
    for f in recent_effects:
        t = str(f.get("text") or "")
        if t and not _is_quote(t):
            urgent.append(f"Folge offen: {t[:120]}")
    bits = urgent + bits
    prev = (session.get("fate") or {}).get("beat")
    pressure = min(1.0, 0.2 + 0.08 * len(bits) + (0.05 if role else 0))
    if disrupt:
        pressure = min(1.0, max(pressure, 0.75))
        chosen = disrupt[0]
        if prev == chosen:
            return None, pressure
        return chosen, pressure
    # Do not jump to the second stored candidate simply because the first was
    # already used. A new causal stimulus is required even to change a beat.
    candidate = next((b for b in bits if b), None)
    if not candidate or candidate == prev:
        return None, pressure
    if prev:
        last_shift = int((session.get("fate") or {}).get("lastShiftTurn") or 0)
        new_effect = any(isinstance(f, dict)
                         and int(f.get("turn") or 0) > last_shift
                         and _scene.validiert(f)
                         and f.get("kind") in ("speech", "action", "presence", "god", "regie", "scene", "physical")
                         for f in (session.get("facts") or []))
        if not new_effect:
            return None, pressure
    return candidate, pressure


def apply_fate_pressure(
    session: dict,
    *,
    pressure: float | None = None,
    beat: str | None = None,
    seed_id: str | None = None,
    seed: str | None = None,
    proposal: dict | str | None = None,
) -> dict:
    """B8.3 control-state writer. Alias of apply_fate with seed synonym."""
    return apply_fate(
        session,
        seed_id=seed_id if seed_id is not None else seed,
        beat=beat,
        pressure=pressure,
        proposal=proposal,
    )


def reset_chat_only(session: dict) -> dict:
    s = copy.deepcopy(session)
    opening = (s.get("scene") or {}).get("notes") or "Die Szene steht."
    s["turns"] = [{"id": uid("ln"), "turn": 0, "speakerId": "narrator", "speakerName": "Szene", "role": "narrator", "speech": opening, "firedSpaces": []}]
    s["turnIndex"] = 0
    return s


def _sync_present(session: dict) -> None:
    place = (session.get("scene") or {}).get("placeName")
    present: list[str] = []
    avatar = session.get("avatarId")
    runtimes = session.get("runtimes") or {}
    if not isinstance(runtimes, dict):
        runtimes = {}
    for cid, rt in runtimes.items():
        if not cid:
            continue
        if isinstance(rt, dict) and (not place or rt.get("position") == place):
            present.append(str(cid))
    if avatar and avatar not in present:
        art = runtimes.get(avatar) if isinstance(runtimes.get(avatar), dict) else None
        if art is None or not place or art.get("position") == place:
            present.append(str(avatar))
    session.setdefault("scene", {})["presentIds"] = present


def apply_presence(session: dict, character_id: str, world: dict | None = None, natives: list[dict] | None = None) -> dict:
    """Canonical presence toggle with pre-effect TurnTruth and append-only SceneFact evidence."""
    if not character_id:
        return session
    s = copy.deepcopy(session)
    place_name = (s.get("scene") or {}).get("placeName") or ""

    # AMASTER §23: bind the ingress before the presence effect mutates runtime or
    # SceneState. A missing runtime behaves exactly as before (initial position
    # "anderswo"), but that runtime is not materialized until after TurnTruth.
    existing_runtimes = s.get("runtimes") if isinstance(s.get("runtimes"), dict) else {}
    existing_rt = existing_runtimes.get(character_id)
    before_position = str(existing_rt.get("position") or "") if isinstance(existing_rt, dict) else "anderswo"
    if before_position == place_name:
        # The runtime position (scene.placeName) is the presence authority.
        # Imported worlds may have a single place or id-less places, so a
        # different/missing placeId does NOT prove a different physical place.
        # Leave the scene when no genuinely different named place exists.
        other = next(
            (
                p for p in (world or {}).get("places") or []
                if isinstance(p, dict)
                and str(p.get("name") or "").strip()
                and str(p.get("name") or "") != place_name
            ),
            None,
        )
        planned_after_position = str((other or {}).get("name") or "anderswo")
    else:
        planned_after_position = str(place_name)
    text = (
        f"Präsenz {character_id}: {before_position or 'unbekannt'} -> "
        f"{planned_after_position or 'unbekannt'}"
    )
    truth = bind_from_session(
        s,
        role="teilnehmer",
        authority="teilnehmer",
        speaker_id=character_id,
        target_id=None,
        input_kind="presence",
        text=text,
        input_actor_id=character_id,
    )
    attach_turn_truth(s, truth)

    # V3 migration seam: old sessions persisted the derived default as a list
    # equal to pre-entry presence. Remove only that unmarked legacy shape before
    # presence changes; explicit marker/subset/empty restrictions stay intact.
    scene = s.setdefault("scene", {})
    before_present = [str(x) for x in (scene.get("presentIds") or []) if x]
    for key, marker, legacy in (
        ("hearsIds", "hearsExplicit", "hears_ids"),
        ("seesIds", "seesExplicit", "sees_ids"),
    ):
        if marker in scene:
            continue
        raw_key = key if key in scene else legacy if legacy in scene else None
        if raw_key is None:
            continue
        raw_ids = [str(x) for x in (scene.get(raw_key) or []) if x]
        if raw_ids == before_present:
            scene.pop(key, None)
            scene.pop(legacy, None)

    runtimes = s.setdefault("runtimes", {})
    rt = runtimes.get(character_id)
    if not isinstance(rt, dict):
        native = next((c for c in (natives or []) if c.get("id") == character_id), None)
        rt = {
            "characterId": character_id,
            "emotion": "wach",
            "position": "anderswo",
            "canSpeak": True,
            "gagged": False,
            "mobility": 1.0,
        }
        if isinstance(native, dict) and native.get("body"):
            body = native.get("body") or {}
            rt["pain"] = body.get("pain", 0)
            rt["mobility"] = body.get("mobility", 1)
        runtimes[character_id] = rt
    rt["position"] = planned_after_position
    _sync_present(s)

    # Presence is a scene-state control, not a chat turn. Preserve turnIndex.
    turn = int(s.get("turnIndex") or 0)
    after_position = str(rt.get("position") or "")
    is_present = character_id in ((s.get("scene") or {}).get("presentIds") or [])
    fact = make_fact(
        turn=turn,
        actorId=character_id,
        kind="presence",
        event_kind="presence",
        text=text,
        authority="teilnehmer",
        sourceTurnId=truth["id"],
        truth=truth,
        scene=s.get("scene") or {},
        affected_ids=[character_id],
        payload={
            "characterId": character_id,
            "fromPosition": before_position,
            "toPosition": after_position,
            "present": is_present,
        },
        validated=True,
    )
    s.setdefault("facts", []).append(fact)
    _record_fact_witnesses(s, truth, [fact], turn)
    commit_session_change(s, world=world, source_turn_id=truth["id"])
    return s


def apply_perception_override(session: dict, kind: str, ids: list[str] | None) -> dict:
    """Canonical scene-perception UI writer used by /api/kernel/perception.

    ``None`` clears the user override and returns to runtime/presence-derived
    perception. A list (including []) is an explicit user whitelist.
    """
    if kind not in ("hearsIds", "seesIds"):
        raise ValueError("invalid perception kind")
    s = copy.deepcopy(session)
    scene = s.setdefault("scene", {})
    marker = "hearsExplicit" if kind == "hearsIds" else "seesExplicit"
    legacy = "hears_ids" if kind == "hearsIds" else "sees_ids"
    scene.pop(legacy, None)
    if ids is None:
        scene.pop(kind, None)
        scene.pop(marker, None)
    else:
        unique: list[str] = []
        for raw in ids:
            cid = str(raw or "").strip()
            if cid and cid not in unique:
                unique.append(cid)
        scene[kind] = unique
        scene[marker] = True
    return s


def apply_move(
    session: dict,
    world: dict,
    place_id: str,
    mover_id: str,
    natives: list[dict] | None = None,
) -> dict:
    """Canonical place change with pre-effect TurnTruth and action evidence."""
    places = (world or {}).get("places") or []
    place = next((p for p in places if isinstance(p, dict) and p.get("id") == place_id), None)
    if not place:
        return session
    s = copy.deepcopy(session)
    runtimes = s.setdefault("runtimes", {})
    rt_live = runtimes.get(mover_id)
    rt_check = rt_live if isinstance(rt_live, dict) else {}
    text = f"betritt {place.get('name')}"

    # AMASTER §23: both the successful move and a capability-rejected attempt
    # bind and attach the same canonical ingress before any turn/runtime/scene
    # state is changed. The SceneFact then references this persisted truth.
    truth = bind_from_session(
        s,
        role="avatar",
        authority="avatar",
        speaker_id=mover_id,
        target_id=None,
        input_kind="action",
        text=text,
    )
    attach_turn_truth(s, truth)

    blocked = capability_blocks_action(rt_check, text) or capability_blocks_action(
        rt_check, f"geht nach {place.get('name')}"
    )
    if blocked:
        s["turnIndex"] = next_turn_index(s)
        turn = s["turnIndex"]
        s.setdefault("turns", []).append(
            {
                "id": uid("ln"),
                "turn": turn,
                "speakerId": mover_id,
                "speakerName": "Bewegung",
                "role": "avatar",
                "speech": "",
                "action": text,
                "firedSpaces": [],
                "source": "kernel",
            }
        )
        fact = make_fact(
            turn=turn,
            actorId=mover_id,
            kind="action",
            event_kind="action",
            text=text,
            authority="avatar",
            sourceTurnId=truth["id"],
            truth=truth,
            scene=s.get("scene") or {},
            validated=False,
            rejection_reason="capability",
        )
        s.setdefault("facts", []).append(fact)
        commit_session_change(s, world=world, source_turn_id=truth["id"])
        return s

    before_place_id = (s.get("scene") or {}).get("placeId")
    before_place_name = (s.get("scene") or {}).get("placeName")
    affected_ids: list[str] = [str(mover_id)] if mover_id else []
    if isinstance(rt_live, dict):
        rt_live["position"] = place.get("name")
        holding = rt_live.get("holding")
        if holding and isinstance(runtimes.get(holding), dict):
            runtimes[holding]["position"] = place.get("name")
            if str(holding) not in affected_ids:
                affected_ids.append(str(holding))
    s.setdefault("scene", {})["placeId"] = place["id"]
    s["scene"]["placeName"] = place["name"]
    for c in natives or []:
        cid = c.get("id") if isinstance(c, dict) else None
        if not cid or not isinstance(runtimes.get(cid), dict):
            continue
        tags = [str(t).lower() for t in (place.get("tags") or [])]
        first = str(c.get("name") or "").split(" ")[0].lower()
        if first and first in tags and runtimes[cid].get("position") == "anderswo":
            runtimes[cid]["position"] = place.get("name")
            if str(cid) not in affected_ids:
                affected_ids.append(str(cid))
    _sync_present(s)
    s["turnIndex"] = next_turn_index(s)
    turn = s["turnIndex"]
    s.setdefault("turns", []).append(
        {
            "id": uid("ln"),
            "turn": turn,
            "speakerId": mover_id,
            "speakerName": "Bewegung",
            "role": "avatar",
            "speech": f"geht nach {place.get('name')}.",
            "action": text,
            "firedSpaces": [],
            "source": "kernel",
        }
    )
    fact = make_fact(
        turn=turn,
        actorId=mover_id,
        kind="action",
        event_kind="action",
        text=text,
        authority="avatar",
        sourceTurnId=truth["id"],
        truth=truth,
        scene=s.get("scene") or {},
        affected_ids=affected_ids,
        payload={
            "fromPlaceId": before_place_id,
            "fromPlace": before_place_name,
            "toPlaceId": place.get("id"),
            "toPlace": place.get("name"),
            "movedIds": affected_ids,
        },
        validated=True,
    )
    s.setdefault("facts", []).append(fact)
    _record_fact_witnesses(s, truth, [fact], turn)
    commit_session_change(s, world=world, source_turn_id=truth["id"])
    return s


def resolve_target(
    session: dict,
    natives: list[dict],
    text: str,
    ui_target_id: str | None = None,
    last_speaker_id: str | None = None,
) -> str | None:
    detail = resolve_target_detail(
        session, natives, text, ui_target_id=ui_target_id, last_speaker_id=last_speaker_id
    )
    return detail.get("target_id")


def _address_segments(text: str, strip: str) -> list[tuple[str, int]]:
    """V92 Paket 17: the address segments of a text (split at , ; : ! ? . … and a spaced dash - as before) with their offset in the
    text, stripped of `strip` - so an answer the operator gave for a written place binds only there."""
    raw = str(text or "")
    out, pos = [], 0
    for m in [*re.finditer(r"[,;:!?.…]|\s[–—-]\s", raw), None]:
        part = raw[pos:(m.start() if m else len(raw))]
        out.append((part.strip(strip), pos + len(part) - len(part.lstrip(strip))))
        if m:
            pos = m.end()
    return out


def _name_roles(text: str, figures: list[dict], actor_id: str | None = None, base: int | None = None) -> dict[str, str]:
    """Name as direct address, ambiguous name, or mention. Merely naming someone
    does not make that person the addressee (BT2/FK14). A safe vocative is
    independent of presence; presence determines hearing, not addressing.
    V92 Paket 17: `base` = offset of `text` in the input - the operator's answers apply at their place.
    """
    ranks = {"mentioned": 1, "ambiguous": 2, "addressed": 3}
    roles: dict[str, str] = {}
    for _orig, _off in _address_segments(text, "\"'„“”«»‚‘’ \t"):
        seg = _orig.lower()
        if not seg:
            continue
        # V92 Paket 15/16 (Paket-14/15-Pruefung "andere Identitaetsreader"; AMASTER §24.1, §24.7): a name part that stands inside a
        # name the one identity reading leaves unbound (an unknown full name, a name of unproven extent), or inside a name it binds
        # to OTHER figures, names this figure nobody here either - same reading as name_occurrences, no second resolver
        _occ = name_occurrences(_orig, figures, base=(base + _off) if base is not None else None) if len(_orig) == len(seg) else []
        for c in figures:
            cid = str(c.get("id") or "")
            if not cid or cid == str(actor_id or ""):
                continue
            forms: list[str] = []
            for raw in [c.get("name"), *(c.get("aliases") or [])]:
                name = str(raw or "").strip().lower()
                if len(name) >= 2:
                    forms.extend([name, name.split()[0]])
            # V65K (§24.1 known_as): a session name is one whole label, never split.
            forms.extend(str(a).strip().lower() for a in (c.get("sessionAliases") or []) if len(str(a).strip()) >= 2)
            for name in dict.fromkeys(forms):
                found = next((m for m in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", seg)
                              if not any(o["a"] <= m.start() < o["b"] and (o["state"] != "ok" or cid not in o["ids"]) for o in _occ)), None)
                if not found:
                    continue
                role = ("addressed" if seg == name else
                        "ambiguous" if found.start() == 0 or found.end() == len(seg) else "mentioned")
                if ranks[role] > ranks.get(roles.get(cid, ""), 0):
                    roles[cid] = role
    return roles


def resolve_target_detail(
    session: dict,
    natives: list[dict],
    text: str,
    ui_target_id: str | None = None,
    last_speaker_id: str | None = None,
    input_actor_id: str | None = None,
) -> dict:
    """Canonical speech addressee, not a person merely mentioned in the text.

    A stale UI focus never wins against SQL presence. Explicitly addressing a
    non-present figure is possible, but it does NOT give that figure knowledge.
    """
    scene = session.get("scene") or {}
    present_ids = set(str(x) for x in scene.get("presentIds") or [])
    figures = [c for c in (natives or []) if isinstance(c, dict) and c.get("id")]
    valid_ids = {str(c["id"]) for c in figures}
    actor = str(input_actor_id or session.get("avatarId") or "")
    present_interlocutors = {cid for cid in present_ids & valid_ids if cid != actor}
    # V92 Paket 14 (Paket-13-Pruefung, Entscheidung 1; AMASTER §25, §24.1, §24.7): a direct address that is a name the cast does
    # not carry, or a name of unproven extent ("Mara Schmidt, komm her." with only Mara Nowak known), addresses nobody of the cast -
    # it is never bent onto a figure sharing the first name or onto the selected recipient.
    _vocative_full: list[dict] = []
    # V92 Paket 17 (Paket-16-Pruefung N3/N4): the operator's answers at their place in THIS text; each question names its place
    figures = place_klaerungen(str(text or ""), figures)
    # The same semantic boundary reading also distinguishes a direct address
    # from a mention. Never infer this from a fixed list of greeting words.
    # Ambiguous identical names remain unbound and are offered for clarification.
    semantic_addresses: list[tuple[str, list[str], int, int]] = []
    for f in figures:
        for bound in f.get("_name_boundary_readings") or []:
            if (bound.get("rolle") != "anrede" or bound.get("source") != str(text or "")):
                continue
            a0, b0 = bound["na"], bound["nb"]
            named = str(text or "")[a0:b0]
            # §26 / P20 live regression: only PRESENT interlocutors compete
            # for a direct address. An absent namesake in the world does not
            # make "Hallo Mara" ambiguous. A full name of an absent person
            # never falls back to a different present person with that first
            # name: the source span and canonical IDs remain authoritative.
            ids = sorted(figure_ids_for_name(named, figures) & present_interlocutors)
            if ids and (named, ids, a0, b0) not in semantic_addresses:
                semantic_addresses.append((named, ids, a0, b0))
    if semantic_addresses:
        # The operator's signed answer belongs to a particular original-text
        # place and has precedence over the proposed semantic name boundary.
        # A reply to "Hallo Mara" may cover the shorter name span "Mara".
        answered = []
        for named, ids, a0, b0 in semantic_addresses:
            for f in figures:
                fid = str(f.get("id") or "")
                if fid not in ids:
                    continue
                for claim in f.get("klaerung") or []:
                    if (isinstance(claim, dict) and type(claim.get("a")) is int
                            and type(claim.get("b")) is int
                            and claim["a"] <= a0 and b0 <= claim["b"]):
                        answered.append(fid)
        chosen = set(answered)
        if len(chosen) == 1:
            fid = next(iter(chosen))
            return {"target_id": fid, "ambiguous": False,
                    "reason": "explicit_address_clarified", "candidates": [fid]}
        # Never let a remembered UI selection replace an explicit address.
        if len(semantic_addresses) == 1 and len(semantic_addresses[0][1]) == 1:
            return {"target_id": semantic_addresses[0][1][0], "ambiguous": False,
                    "reason": "semantic_explicit_address", "candidates": semantic_addresses[0][1]}
        named, ids, a0, b0 = semantic_addresses[0]
        return {"target_id": None, "ambiguous": True, "reason": "semantic_address_ambiguous",
                "candidates": ids,
                "klaerung": {"text": named, "a": a0, "b": b0, "kandidaten": ids}}
    _clarified: list[str] = []
    for seg, _off in _address_segments(text, "\"'„“”«»‚‘’ \t*"):
        occ = name_occurrences(seg, figures, base=_off) if seg else []
        if len(occ) == 1 and occ[0].get("geklaert") and occ[0].get("klaert") == _name_words(seg):
            # V92 Paket 17 (eigene Pruefung 06.11.: "Hallo Mara" answered Mara Schmidt, the selected recipient Mara Nowak won): a
            # direct address the operator answered at this place names exactly the chosen figure
            _clarified.extend(sorted(occ[0]["ids"]))
            continue
        if len(occ) == 1 and occ[0]["words"] == _name_words(seg):
            if occ[0]["state"] in ("unbekannt", "unklar"):
                # V92 Paket 16 (Paket-15-Pruefung: "eine sichtbare Klartext-Rueckfrage muss die korrekte Figur-ID ermitteln koennen"):
                # the figures whose names stand in it are offered for a clarification - none is bound here
                _k = [c for c in occ[0].get("kandidaten") or [] if c in valid_ids and c != actor]
                return {"target_id": None, "ambiguous": True, "reason": "explicit_address_unknown", "candidates": [],
                        **({"klaerung": {"text": seg, "a": _off, "b": _off + len(seg), "kandidaten": _k}} if _k else {})}
            if occ[0]["state"] == "ok" and len(occ[0]["ids"]) > 1:
                _vocative_full.append({"text": seg, "a": _off, "b": _off + len(seg), "words": occ[0]["words"], "ids": sorted(occ[0]["ids"])})
    roles = _name_roles(text, figures, actor_id=actor, base=0)
    addressed = [cid for cid, role in roles.items() if role == "addressed"]
    if len(addressed) > 1:
        # V92 Paket 14 (Entscheidung 2): a direct address in the running scene may prefer the ONE present figure the name
        # fits (another one carrying the name is absent). V92 Paket 16 (Paket-15-Pruefung N4/N5; Entscheidung 2 "bei ausdruecklich
        # genannten vollstaendigen Namen darf dieser Vorrang nicht gelten"): never for a FULL name several figures carry - then
        # nobody is bound and the operator is asked.
        _here = [cid for cid in addressed if cid in present_ids]
        _full = any(len(v["words"].split()) > 1 for v in _vocative_full)
        if len(_here) == 1 and not _full:
            return {"target_id": _here[0], "ambiguous": False, "reason": "explicit_address_present", "candidates": addressed}
        _v = next(iter(_vocative_full), None)
        _k = [c for c in addressed if c != actor]
        return {"target_id": None, "ambiguous": True, "reason": "multiple_addressees", "candidates": addressed,
                **({"klaerung": {"text": _v["text"], "a": _v["a"], "b": _v["b"], "kandidaten": _k}} if _v and _k else {})}
    _cl_ids = set(_clarified) - {actor}
    if len(_cl_ids) == 1 and set(addressed) <= _cl_ids:
        # V92 Paket 17: the operator's answer for the direct address outranks the selected recipient (as for a target, Paket 16)
        return {"target_id": next(iter(_cl_ids)), "ambiguous": False, "reason": "explicit_address_clarified", "candidates": sorted(_cl_ids)}
    selected = str(ui_target_id or "")
    # A UI target that left the scene is invalid. The only exception is a
    # safe, explicit vocative in this utterance, not a remembered selection.
    if selected and selected not in present_interlocutors:
        selected = selected if selected in addressed else ""
    if addressed:
        # The utterance is fresher authority than a remembered UI choice.
        # Override the stale focus instead of creating an artificial conflict.
        return {"target_id": addressed[0], "ambiguous": False,
                "reason": "explicit_address_overrides_focus" if selected and selected != addressed[0] else "explicit_address",
                "candidates": addressed}
    if selected:
        return {"target_id": selected, "ambiguous": False, "reason": "selected_present", "candidates": [selected]}
    ambiguous_names = [cid for cid, role in roles.items() if role == "ambiguous"]
    if ambiguous_names:
        return {"target_id": None, "ambiguous": True, "reason": "ambiguous_name", "candidates": ambiguous_names}
    # A mentioned third party NEVER becomes an addressee. Contextual targets
    # are eligible only while present. No remote witness is manufactured.
    is_direct = bool(re.search(r"\b(du|dir|dich|ihr|euch|dein|deine)\b", str(text or ""), re.I))
    last_id = str(last_speaker_id or "")
    if not last_id:
        for f in reversed(session.get("facts") or []):
            if isinstance(f, dict) and f.get("kind") in ("speech", "action") and f.get("actorId"):
                last_id = str(f["actorId"])
                break
    if is_direct and last_id in present_interlocutors:
        return {"target_id": last_id, "ambiguous": False, "reason": "previous_present_speaker", "candidates": [last_id]}
    for collection in (session.get("propositions") or [], session.get("goals") or []):
        matches: list[str] = []
        for row in reversed(collection):
            if not isinstance(row, dict) or row.get("status") not in ("open", "active", "accepted"):
                continue
            cid = str(row.get("targetId") or "")
            if cid in present_interlocutors and cid not in matches:
                matches.append(cid)
        if len(matches) == 1:
            return {"target_id": matches[0], "ambiguous": False, "reason": "open_present_matter", "candidates": matches}
    if len(present_interlocutors) == 1:
        only = next(iter(present_interlocutors))
        return {"target_id": only, "ambiguous": False, "reason": "sole_present_interlocutor", "candidates": [only]}
    return {"target_id": None, "ambiguous": len(present_interlocutors) > 1, "reason": "unbound", "candidates": sorted(present_interlocutors)}


def _named_figures(text: str, figures: list[dict]) -> list[dict]:
    low = (text or "").lower()
    hits: list[dict] = []
    for c in figures:
        names = [str(c.get("name") or "")] + [str(a) for a in (c.get("aliases") or [])]
        for n in names:
            token = n.strip()
            if len(token) < 2:
                continue
            first = token.split()[0]
            if re.search(rf"\b{re.escape(first)}\b", low, re.I):
                hits.append(c)
                break
    return hits


def figure_speaker_eligible(session: dict, c: dict | None) -> bool:
    """Who may be the figure speaker of a turn at all (AMASTER §28 Schritt 16, §43 PhysicalState begrenzt Capability).

    Stand 07 / K-01: the former inner rule of pick_speaker, now one owner for the server's own choice AND for the check
    of a speaker the UI selected (prepare/commit took a selected speaker after a presence check only). Present in the
    scene, never the Avatar / God / Fate, conscious and able to speak. Position drift is pick_speaker's own preference."""
    if not isinstance(c, dict):
        return False
    cid = c.get("id")
    if not cid or cid == session.get("avatarId"):
        return False
    role = str(c.get("role") or "").lower()
    if cid in ("god", "fate") or role in ("god", "fate", "avatar"):
        return False
    present_ids = list((session.get("scene") or {}).get("presentIds") or [])
    if present_ids and cid not in present_ids:
        return False
    rt = (session.get("runtimes") or {}).get(cid) or {}
    if not isinstance(rt, dict):
        rt = {}
    # Stand 07: `consciousness or 1` read an unconscious figure (0.0) as fully conscious; only a missing value is 1
    # (same rule as _scene_perception).
    _cons = rt.get("consciousness")
    try:
        if float(1 if _cons is None else _cons) < 0.5:
            return False
    except (TypeError, ValueError):
        pass
    if rt.get("canSpeak") is False or rt.get("gagged"):
        return False
    return True


def pick_speaker(
    session: dict,
    natives: list[dict],
    stimulus: str,
    explicit_name: str | None = None,
    ui_target_id: str | None = None,
    autochat: bool = False,
    affected_ids: list[str] | None = None,
) -> dict | None:
    """Figure speaker only. Avatar / fate / god never speak. Scores AMASTER §28 factors."""
    place = (session.get("scene") or {}).get("placeName")

    def _eligible(c: dict, *, at_place: bool) -> bool:
        if not figure_speaker_eligible(session, c):
            return False
        rt = (session.get("runtimes") or {}).get(c.get("id")) or {}
        if not isinstance(rt, dict):
            rt = {}
        if at_place and place and rt.get("position") and rt.get("position") != place:
            return False
        return True

    # presentIds is canonical presence. Position drift must not hide an addressed figure.
    scene_present = [c for c in (natives or []) if _eligible(c, at_place=False)]
    present = [c for c in scene_present if _eligible(c, at_place=True)]
    if not present:
        present = scene_present
    if not scene_present:
        return None
    stim = (stimulus or "").lower()

    def _named_in(pool: list[dict], name: str | None) -> dict | None:
        n = str(name or "").lower().strip()
        if not n:
            return None
        return next(
            (
                c
                for c in pool
                if str(c.get("name") or "").lower() == n
                or n in [str(a).lower() for a in list(c.get("aliases") or []) + list(c.get("sessionAliases") or [])]
                or str(c.get("name") or "").lower().startswith(n)
            ),
            None,
        )

    voc_tok = re.match(r"^\s*([A-Za-zÄÖÜäöüß\-]+)\s*,", stimulus or "")
    if voc_tok:
        tok = voc_tok.group(1)
        voc = next(
            (
                c
                for c in scene_present
                if str(c.get("name") or "").split()[0].lower() == tok.lower()
                or any(str(a).lower() == tok.lower() for a in list(c.get("aliases") or []) + list(c.get("sessionAliases") or []))
            ),
            None,
        )
        if voc:
            return voc
    if ui_target_id:
        hit = next((c for c in scene_present if c.get("id") == ui_target_id), None)
        if hit:
            return hit
    if explicit_name:
        hit = _named_in(scene_present, explicit_name)
        if hit:
            return hit
    vocative = resolve_target(session, scene_present, stimulus or "", ui_target_id=ui_target_id)
    if vocative:
        hit = next((c for c in scene_present if c.get("id") == vocative), None)
        if hit and (str(hit.get("name") or "").split()[0].lower() in stim or any(
            str(a).lower() in stim for a in (hit.get("aliases") or [])
        ) or any(re.search(rf"(?<!\w){re.escape(str(a).lower())}(?!\w)", stim) for a in (hit.get("sessionAliases") or []))):
            # only treat as vocative speaker if the name is actually addressed
            if re.search(rf"^\s*{re.escape(str(hit.get('name') or '').split()[0])}\b", stim, re.I):
                return hit
    ranked = rank_speakers(session, present, stimulus, natives=natives, autochat=autochat, affected_ids=affected_ids)
    if ranked and (ranked[0]["score"] > 0.5 or autochat):
        return next((c for c in present if c.get("id") == ranked[0]["id"]), None)
    if not present:
        return None
    last_id = ranked[0].get("lastSpeakerId") if ranked else None
    turn = int(session.get("turnIndex") or 0)
    # Round-Robin-Index über ALLE present, nicht über others.
    rr_idx = (turn + _last_actor_count(session, last_id)) % len(present)
    return present[rr_idx]


# V40 Turn-Taking-Heuristik (Vorbild: Ursprungssystem turn_taking.py — Gewichte Dringlichkeit,
# Kontextbedeutung, Beziehungsrelevanz, emotionale Beteiligung, Agenda-Druck, Gesprächsfluss,
# Anrede/Frage; Cooldown und Limit aufeinanderfolgender Turns; Unterbrechung bei hoher
# emotionaler Dringlichkeit). AMASTERv2 §28: Sprecherwahl aus kanonischem Zustand, nie zufällig.
TURN_WEIGHTS = {
    "direct_address": 3.0,
    "question": 1.5,
    "urgency": 1.6,
    "context": 2.0,
    "relationship": 1.0,
    "emotion": 0.8,
    "agenda": 2.0,
    "flow": 0.6,
    "capability": -9.0,
}


def rank_speakers(session: dict, present: list[dict], stimulus: str, *, natives: list[dict] | None = None, exclude_ids: list[str] | None = None, autochat: bool = False, affected_ids: list[str] | None = None) -> list[dict]:
    """Bewertet alle anwesenden Weltfiguren als nächste Sprecherin; liefert Rangliste mit Gründen.
    autochat=True: Gesprächswechsel ist Pflicht (wer gerade sprach, spricht nicht wieder, solange
    jemand anderes kann); wen der letzte Sprecher angesprochen hat, ist dran; Fate-Nennung und eigene
    Ziele/Wünsche ziehen (AMASTERv2 §28/§47: Figuren reden aus Antrieb, nicht immer dieselbe)."""
    stim = (stimulus or "").lower()
    fate_beat = str(((session.get("fate") or {}).get("beat") or "")).lower() if isinstance(session.get("fate"), dict) else ""
    avatar = str(session.get("avatarId") or "")
    facts = [f for f in (session.get("facts") or []) if isinstance(f, dict)]
    # Sprecherfolge der letzten Figurenreden (ohne Avatar/Nutzer)
    recent: list[str] = []
    for f in reversed(facts):
        if f.get("kind") in ("speech", "action") and f.get("actorId") and str(f.get("actorId")) not in (avatar, "user", "operator", "narrator", "regie", "god"):
            recent.append(str(f.get("actorId")))
            if len(recent) >= 8:
                break
    last_id = recent[0] if recent else None
    # letzter Sprecher überhaupt (inkl. Avatar) für Beziehungsrelevanz
    last_any = next((str(f.get("actorId")) for f in reversed(facts) if f.get("kind") in ("speech", "action") and f.get("actorId")), None)
    is_question = bool(re.search(r"\?\s*$|^\s*(wer|was|wann|wo|wie|warum|wieso|weshalb|welche[rs]?)\b", (stimulus or ""), re.I))
    target_id = str((session.get("focus") or {}).get("addressedId") or "")
    frames = [f for f in (session.get("frames") or []) if isinstance(f, dict)]
    out: list[dict] = []
    for c in present:
        cid = str(c.get("id") or "")
        if not cid or cid == avatar or cid in set(exclude_ids or []):
            continue
        rt = (session.get("runtimes") or {}).get(cid) or {}
        parts: dict[str, float] = {}
        reasons: list[str] = []
        # Anrede / Frage
        first = str(c.get("name") or "").split()[0].lower() if c.get("name") else ""
        addressed = bool(first and re.search(rf"\b{re.escape(first)}\b", stim)) or any(str(a).lower() in stim for a in (c.get("aliases") or []) if len(str(a)) >= 3) \
            or any(re.search(rf"(?<!\w){re.escape(str(a).lower())}(?!\w)", stim) for a in (c.get("sessionAliases") or []) if len(str(a)) >= 2)
        if addressed:
            parts["direct_address"] = TURN_WEIGHTS["direct_address"]
            reasons.append("angesprochen")
        if is_question and (addressed or cid == target_id):
            parts["question"] = TURN_WEIGHTS["question"]
            reasons.append("gefragt")
        # Dringlichkeit (Zustand)
        urg = max(float(rt.get("fear") or 0), float(rt.get("anger") or 0), float(rt.get("stress") or 0), float(rt.get("pain") or 0) if rt.get("pain") else 0.0)
        if urg >= 0.5:
            parts["urgency"] = TURN_WEIGHTS["urgency"] * urg
            reasons.append(f"Druck {urg:.2f} ({rt.get('emotion') or 'angespannt'})")
        # Kontextbedeutung (Wissen/Ziele/Erinnerung treffen den Reiz)
        mems = [str(m.get("text") or "") for m in (session.get("memories") or []) if isinstance(m, dict) and m.get("characterId") == cid]
        blob = " ".join(str(x) for x in (*(c.get("knowledge") or []), *(c.get("goals") or []), c.get("occupation") or "", c.get("role") or "", *mems[:6])).lower()
        hits = sum(1 for w in set(re.findall(r"[a-zäöüß]{4,}", stim)) if w in blob)
        if hits:
            parts["context"] = min(TURN_WEIGHTS["context"], 0.7 * hits)
            reasons.append(f"betrifft sie ({hits} Treffer)")
        fired = fire_compass_lens(c, stimulus or "")
        if fired:
            parts["emotion"] = parts.get("emotion", 0.0) + float(fired[0].get("activation") or 0)
            reasons.append(f"Synapse {fired[0].get('space')}")
        # Beziehungsrelevanz zum letzten Sprecher
        if last_any and last_any != cid:
            rel = next((r for r in (session.get("relations") or []) if isinstance(r, dict) and r.get("fromId") == cid and r.get("toId") == last_any), None)
            if rel:
                strength = max(float(rel.get("closeness") or 0), float(rel.get("hostility") or 0), float(rel.get("fear") or 0))
                if strength >= 0.4:
                    parts["relationship"] = TURN_WEIGHTS["relationship"] * strength
                    reasons.append(f"Beziehung zu {last_any[:8]} {strength:.2f}")
        # emotionale Beteiligung
        emo = str(rt.get("emotion") or "")
        if emo and emo not in ("wach", "calm"):
            parts["emotion"] = parts.get("emotion", 0.0) + 0.2 + min(0.4, float(rt.get("intensity") or 0) * 0.4)
        # Agenda-Druck: offene Vereinbarungen/Bitten an sie, offene Propositionen, Ziele
        agenda = 0.0
        for fr in frames:
            if fr.get("status") in ("proposed", "requested") and str(fr.get("whom") or "") == cid:
                agenda += 1.0
        for pmt in session.get("propositions") or []:
            if isinstance(pmt, dict) and pmt.get("status") == "open" and pmt.get("targetId") == cid:
                agenda += 0.8
        if rt.get("intent") and str(rt.get("intent")).lower() in stim:
            agenda += 0.5
        _st = session.get("sceneState") if isinstance(session.get("sceneState"), dict) else {}
        if _st and str(_st.get("nextBeatOwner") or "") == cid:
            agenda += 1.0
            reasons.append("nächster Beat erwartet")
        for b in (_st.get("openBeats") or []) if _st else []:
            if isinstance(b, dict) and b.get("status") == "open" and str(b.get("owner") or "") == cid:
                agenda += 0.6
        if agenda:
            parts["agenda"] = min(TURN_WEIGHTS["agenda"], agenda)
            reasons.append("Agenda-Druck")
        # Gesprächsfluss: Cooldown, Limit aufeinanderfolgender Turns, Fairness
        streak = 0
        for r in recent:
            if r == cid:
                streak += 1
            else:
                break
        if streak >= 2:
            parts["flow"] = -TURN_WEIGHTS["flow"] * 2
            reasons.append("sprach zweimal in Folge")
        elif last_id == cid:
            parts["flow"] = -TURN_WEIGHTS["flow"]
        elif recent and cid not in recent[:4]:
            parts["flow"] = TURN_WEIGHTS["flow"] * 0.5
            reasons.append("lange still")
        # AutoChat: Antrieb aus Zielen/Wünschen/Fate; Gesprächswechsel
        if autochat:
            if last_id == cid and len(present) > 1:
                parts["flow"] = -6.0
                reasons.append("hat gerade gesprochen — Gesprächswechsel")
            if last_id and last_id != cid and first and re.search(rf"\b{re.escape(first)}\b", stim):
                parts["direct_address"] = max(parts.get("direct_address", 0.0), TURN_WEIGHTS["direct_address"])
                if "angesprochen" not in reasons:
                    reasons.append("vom letzten Sprecher angesprochen")
            # V65E (AMASTER §26 "direkt betroffen", §28 Sprecherwahl "Ziel",
            # §25): who is AFFECTED by the latest committed event (WitnessKnowledge
            # access "affected": target of a validated act, target of a God fact)
            # is addressed by that event — by ID, not by a name in a UI text.
            if affected_ids and cid in set(affected_ids) and last_id != cid:
                parts["direct_address"] = max(parts.get("direct_address", 0.0), TURN_WEIGHTS["direct_address"])
                reasons.append("vom letzten Ereignis betroffen")
            if fate_beat and first and re.search(rf"\b{re.escape(first)}\b", fate_beat):
                parts["agenda"] = min(TURN_WEIGHTS["agenda"] + 1.0, parts.get("agenda", 0.0) + 1.0)
                reasons.append("Fate nennt sie")
            own_goals = [g for g in (c.get("goals") or []) if g] + [g.get("text") for g in (session.get("goals") or []) if isinstance(g, dict) and g.get("ownerId") == cid and g.get("status") == "open"]
            if own_goals or rt.get("intent"):
                parts["agenda"] = parts.get("agenda", 0.0) + 0.4
                reasons.append("hat eigenes Ziel/Wunsch")
            if cid not in recent:
                parts["flow"] = parts.get("flow", 0.0) + 0.8
                if "lange still" not in reasons:
                    reasons.append("noch nicht zu Wort gekommen")
        # Fähigkeit
        if rt.get("canSpeak") is False or rt.get("gagged") or float(rt.get("consciousness") or 1) < 0.5:
            parts["capability"] = TURN_WEIGHTS["capability"]
            reasons.append("kann nicht sprechen")
        score = round(sum(parts.values()), 3)
        out.append({"id": cid, "name": c.get("name"), "score": score, "parts": {k: round(v, 3) for k, v in parts.items()}, "reasons": reasons, "lastSpeakerId": last_id})
    out.sort(key=lambda r: -r["score"])
    # Unterbrechung: hohe Dringlichkeit darf eine bloße Anrede überstimmen, wenn kein klarer Wille
    # Panik/Wut ≥ 0.9 (Dringlichkeit ≥ 1.44) unterbricht auch eine Anrede an jemand anderen —
    # die Angesprochene kommt im nächsten Turn wieder nach vorn (Anrede bleibt im Verlauf).
    if len(out) >= 2 and out[0]["parts"].get("direct_address") and not out[0]["parts"].get("urgency") and out[1]["parts"].get("urgency", 0) >= 1.44:
        out[0], out[1] = out[1], out[0]
        out[0]["reasons"].append("unterbricht (Dringlichkeit)")
    return out


def _last_actor_count(session: dict, last_id: str | None) -> int:
    """B.13: zähle, wie oft der Last-Speaker in den letzten Fakten auftaucht.

    Wenn last_id 2x hintereinander gesprochen hat, rotieren wir 1 weiter,
    damit wirklich gewechselt wird. Bei 0 → Standard-Round-Robin.
    """
    if not last_id:
        return 0
    count = 0
    for f in reversed(list(session.get("facts") or [])):
        if f.get("kind") in ("speech", "action") and f.get("actorId"):
            if f.get("actorId") == last_id:
                count += 1
                if count >= 3:
                    break
            else:
                break
    return count


def latest_event_stimulus(session: dict) -> tuple[str | None, list[str]]:
    """V65E (AMASTER §41.1, §34.1 Z. 1817, §26, §39): the latest committed event
    of the scene as speaker-selection input — the text of all validated
    speech/action components of its source turn (same actor), and the figures
    the event AFFECTED (WitnessKnowledge access "affected"). A God fact is not
    perceived as words (§46): no text, only whom it affected. (None, []) if no
    event exists; the caller then keeps its own stimulus."""
    facts = [f for f in (session.get("facts") or []) if isinstance(f, dict)]
    last = None
    for f in reversed(facts):
        if not _scene.validiert(f):
            continue
        if f.get("kind") in ("speech", "action") and f.get("actorId"):
            last = f
            break
        if f.get("kind") == "god":
            last = f
            break
    if last is None:
        return None, []
    src = str(last.get("sourceTurnId") or last.get("source_turn_id") or "")
    if last.get("kind") == "god":
        comps = [f for f in facts if f.get("kind") == "god" and _scene.validiert(f)
                 and src and str(f.get("sourceTurnId") or f.get("source_turn_id") or "") == src] or [last]
        text = ""
    else:
        comps = [f for f in facts if f.get("kind") in ("speech", "action") and _scene.validiert(f)
                 and str(f.get("actorId") or "") == str(last.get("actorId") or "")
                 and src and str(f.get("sourceTurnId") or f.get("source_turn_id") or "") == src] or [last]
        text = " ".join(str(f.get("text") or "").strip() for f in comps if str(f.get("text") or "").strip())
    ids = {str(f.get("id") or "") for f in comps}
    affected = list(dict.fromkeys(
        str(w.get("character_id") or w.get("characterId") or "") for w in (session.get("witnessKnowledge") or [])
        if isinstance(w, dict) and str(w.get("fact_id") or w.get("factId") or "") in ids and w.get("access") == "affected"))
    return text, [a for a in affected if a]


def autochat_gate(
    session: dict,
    natives: list[dict],
    remaining: int,
    *,
    user_decision: str | None = None,
    stimulus: str = "",
) -> dict:
    """Server stop for AutoChat. Same canonical path as a normal turn when it continues."""
    if user_decision in ("stop", "user_decision"):
        return {"ok": True, "stop": True, "reason": "user_decision", "remaining": int(remaining or 0)}
    try:
        left = int(remaining)
    except (TypeError, ValueError):
        left = 0
    if left <= 0:
        return {"ok": True, "stop": True, "reason": "turn_limit", "remaining": 0}
    # V65E (AMASTER §28 Schritte 20/23, §27.8, §48, §34.1 Z. 1817): the next
    # speaker is chosen from the latest COMMITTED event (its components and who
    # it affected), not from the UI's last speech text — after a Regie act the
    # UI sent "" (the act has no speech) and the affected figure was not seen.
    ev_text, ev_affected = latest_event_stimulus(session)
    if ev_text is not None:
        stimulus = ev_text
    speaker = pick_speaker(session, natives, stimulus or "", autochat=True, affected_ids=ev_affected)
    if not speaker:
        return {"ok": True, "stop": True, "reason": "no_speaker", "remaining": left}
    extra = autchat_should_stop(session, natives, remaining_turns=left)
    if extra:
        return {"ok": True, "stop": True, "reason": extra, "remaining": left}
    try:
        _pres = set((session.get("scene") or {}).get("presentIds") or [])
        candidates = rank_speakers(session, [c for c in (natives or []) if c.get("id") in _pres], stimulus or "", autochat=True, affected_ids=ev_affected)[:4]
    except Exception:
        candidates = []
    return {
        "ok": True,
        "stop": False,
        "reason": None,
        "speakerId": speaker.get("id"),
        "candidates": candidates,
        "remaining": left,
    }


def lifecycle_evidence_fact(session: dict, actor_id: str, fact_id: str | None = None) -> dict | None:
    """The SceneFact that evidences an answer (request, acceptance, refusal, commitment, revoke) of `actor_id`.

    Stand 07 / K-01 (W2; AMASTER §34 SceneFact bindet Quellturn und Actor, §35 dieselbe Angelegenheit, §36.3 "Sprecher und
    Empfaenger stimmen"): the evidence is the actor's OWN utterance or act. P25 bound a named fact without checking its
    actor and, without a fact id, the latest speech OF OR TO the actor - so a figure that said nothing "accepted" with
    the requester's question as its evidence (lifecycle back-dated to that turn). Not "actor == TurnTruth speaker": the
    Avatar / the operator answer in a turn whose response speaker is another figure, a touched figure answers a body
    contact, a Regie act is the ordered figure's own act - all of them are the actor's own fact."""
    facts = [f for f in (session.get("facts") or []) if isinstance(f, dict)]
    if fact_id:
        named = next((f for f in facts if str(f.get("id") or "") == str(fact_id)), None)
        if named is not None:
            return named if str(named.get("actorId") or named.get("actor_id") or "") == str(actor_id or "") else None
        # (P25 fell back to the positional search when the named fact was not in the session yet - kept, own facts only)
    for f in reversed(facts):
        if f.get("kind") in ("speech", "narrator") and str(f.get("actorId") or "") == str(actor_id or ""):
            return f
    return None


def _bind_lifecycle_evidence(
    session: dict,
    *,
    actor_id: str,
    text: str,
    kind: str,
    prop: dict | None,
    fact_id: str | None = None,
    body_contact: dict | None = None,
    stamp: bool = True,
) -> None:
    """Append-only lifecycle SceneFact bound to proposition/goal. Current status is reduced from this.
    V65T (§36.5 Z. 1947, §34.3): for a Koerperkontakt container the entry also names the answered acts and the
    validated scope/window (payload.koerperkontakt, see _body_contact_answer).
    V62 (§34.1/§35): when the caller names the speech Fact of this act, exactly
    that Fact is bound; the positional search (latest speech of/to the actor)
    stays only for callers without a Fact id."""
    if not prop:
        return
    pid = prop.get("id")
    gid = None
    for g in session.get("goals") or []:
        if g.get("proposition_id") == pid or g.get("propositionId") == pid:
            gid = g.get("id")
            break
    responds = None
    f = lifecycle_evidence_fact(session, actor_id, fact_id)
    if f is not None:
        if stamp:   # V65T: a second component of the same utterance keeps the Fact's own matter binding
            f["propositionId"] = pid
            f["proposition_id"] = pid
            f["goalId"] = gid
            f["goal_id"] = gid
        responds = f.get("id")
    elif kind != "request":
        # Stand 07 / K-01 (W2): no own utterance or act of this actor - no answer evidence, no lifecycle fact
        return
    if kind == "request":
        # Proposition is the request. Do not append a duplicate request lifecycle fact.
        return
    # V70 (Audit10 §7 Nr. 4 "Zeitruecklauf"; AMASTER §34.1 "Alle Komponenten desselben Outputs ... dieselbe Turn-Bindung"): the
    # lifecycle component belongs to the turn of the utterance it answers with (its Quellturn) - the counter is only the
    # fallback. V69 took the counter, so a lifecycle written for an utterance of a later turn than the counter fell below the
    # stored history.
    _resp = next((f for f in (session.get("facts") or []) if isinstance(f, dict) and responds and str(f.get("id") or "") == str(responds)), None)
    _rt = (_resp or {}).get("turn")
    lf = make_fact(
        turn=_rt if isinstance(_rt, int) and not isinstance(_rt, bool) else int(session.get("turnIndex") or 0),
        actorId=actor_id,
        targetId=prop.get("targetId"),
        kind="lifecycle",
        event_kind=kind,
        speech_act=None,
        text=text,
        authority="character",
        sourceTurnId=fact_provenance(session, responds).get("sourceTurnId"),   # V65Z (A01): the answer's Quellturn
        proposition_id=pid,
        goal_id=gid,
        responds_to_fact_id=responds,
        validated=True,
        payload={"kind": "lifecycle", "lifecycle": kind, "proposition_id": pid, "goal_id": gid,
                 **({"koerperkontakt": body_contact} if isinstance(body_contact, dict) else {})},
    )
    lf["propositionId"] = pid
    lf["goalId"] = gid
    session.setdefault("facts", []).append(lf)


def _answered_line_facts(session: dict, actor_id: str, fact_id: str | None) -> list[dict]:
    """V63 reader (moved unchanged out of _stimulus_prop_ids by V65L; AMASTER §25 "letzten Sprecher, adressierte Frage",
    §34 Antwortbezug, §41.1): all components of the line the actor answers — the latest validated line of ANOTHER actor
    before the answering Fact that the actor perceived (WitnessKnowledge heard/seen/affected; the avatar is the user and
    perceives the visible chat). Empty when the actor herself spoke after it. Read-only."""
    facts = [f for f in session.get("facts") or [] if isinstance(f, dict)]
    me = str(actor_id or "")
    idx = next((i for i, f in enumerate(facts) if fact_id and str(f.get("id") or "") == str(fact_id)), len(facts))
    own_src = str(facts[idx].get("sourceTurnId") or "") if idx < len(facts) else ""
    is_avatar = me and me == str(session.get("avatarId") or "")
    seen = {str(w.get("fact_id") or w.get("factId") or "") for w in session.get("witnessKnowledge") or []
            if isinstance(w, dict) and str(w.get("character_id") or w.get("characterId") or "") == me
            and w.get("access") in ("heard", "seen", "affected")}
    line: tuple[str, str] | None = None
    for f in reversed(facts[:idx]):
        if f.get("kind") not in ("speech", "action") or not f.get("actorId"):
            continue
        if str(f.get("actorId")) == me:
            if own_src and str(f.get("sourceTurnId") or "") == own_src:
                continue   # another component of the same answering line
            return []
        if not _scene.validiert(f):
            continue
        if is_avatar or str(f.get("id") or "") in seen:
            line = (str(f.get("actorId")), str(f.get("sourceTurnId") or f.get("id") or ""))
            break
    if line is None:
        return []
    return [f for f in facts[:idx] if str(f.get("actorId") or "") == line[0]
            and str(f.get("sourceTurnId") or f.get("id") or "") == line[1]]


def _stimulus_prop_ids(session: dict, actor_id: str, fact_id: str | None) -> set[str]:
    """V63 (AMASTER §41.1 Immediate Stimulus, §39): the Propositions raised,
    restated or answered by the line the actor answers (_answered_line_facts).
    Read-only."""
    line_facts = _answered_line_facts(session, actor_id, fact_id)
    if not line_facts:
        return set()
    ids = {str(f.get("proposition_id") or f.get("propositionId")) for f in line_facts
           if f.get("proposition_id") or f.get("propositionId")}
    line_ids = {str(f.get("id") or "") for f in line_facts}
    for p in session.get("propositions") or []:
        if isinstance(p, dict) and any(isinstance(e, dict) and str(e.get("factId") or "") in line_ids
                                       for e in p.get("evidence") or []):
            ids.add(str(p.get("id") or ""))
    return ids


def apply_proposition(
    session: dict,
    *,
    actor_id: str,
    text: str,
    kind: str,
    target_id: str | None = None,
    time_window: str | None = None,
    proposition_id: str | None = None,
    source_turn_id: str | None = None,
    authority: str = "character",
    truth: dict | None = None,
    turn: int | None = None,
    world: dict | None = None,
    fact_id: str | None = None,
    matter: str | None = None,
    grenze: dict | None = None,
) -> dict:
    s = copy.deepcopy(session)
    props = s.setdefault("propositions", [])
    goals = s.setdefault("goals", [])
    if kind == "request" and proposition_id:
        same = next((p for p in props if isinstance(p, dict) and p.get("id") == proposition_id
                     and p.get("status") in ("open", "active", "accepted")), None)
        if same is not None and str(same.get("actorId") or "") == str(actor_id) and (
                not target_id or str(same.get("targetId") or "") == str(target_id)):
            _restate_request(s, same, actor_id=str(actor_id), fact_id=fact_id, text=text,
                             turn=int(turn if turn is not None else s.get("turnIndex") or 0))
            s["currentState"] = reduce_current_state(s)
            return s
    if kind == "request":
        # B.7 (AMASTERv2 §37): Vergangenheit darf nicht als neue
        # Zukunftszusage interpretiert werden. Wenn die Request-Zeit
        # in der Vergangenheit liegt oder mehrdeutig ist, wird die
        # Proposition NICHT als offener Request angelegt — sie wandert
        # als Memory in den Stamm, nicht in den offenen Stack.
        bound = bind_time(s, relative=str(time_window or text or ""))
        if bound.get("tense") == "past" or bound.get("ambiguous"):
            s["time"] = bound
            s["currentState"] = reduce_current_state(s)
            return s
        prop = _add_request_proposition(s, actor_id=actor_id, text=text, target_id=target_id, time_window=time_window)
        if prop is not None and matter:
            prop["matter"] = str(matter)[:200]
            # V62 (AMASTER §35 "Ein Goal bindet: Owner, Ziel, ..."): the goal of a
            # request names the requested matter, never the raw wording of the
            # utterance (comparison run 27.10.: a goal read "Heute ist Mittwoch!
            # Also sind es nur noch drei Tage ..."). The wording stays on the
            # Proposition and its speech Fact.
            for g in goals:
                if g.get("proposition_id") == prop.get("id"):
                    g["wording"] = g.get("text")
                    g["text"] = str(matter)[:200]
        # B.7: persistiere Time-Disambig auf der Proposition, damit
        # spätere Aufrufer (acceptance/fulfill) den Kontext nicht neu
        # berechnen müssen.
        if prop is not None and isinstance(prop, dict):
            prop["time_tense"] = bound.get("tense")
            prop["time_ambiguous"] = bool(bound.get("ambiguous"))
            if bound.get("resolved_date"):
                prop["time_resolved_date"] = bound.get("resolved_date")
        _bind_lifecycle_evidence(s, actor_id=actor_id, text=text, kind="request", prop=prop, fact_id=fact_id)
        s["time"] = bound
        s["currentState"] = reduce_current_state(s)
        return s
    bound = bind_time(s, relative=str(time_window or text or ""))
    if kind in ("acceptance", "commitment") and (bound.get("tense") == "past" or bound.get("ambiguous")):
        s["time"] = bound
        s["currentState"] = reduce_current_state(s)
        return s
    # B.7: bei acceptance/commitment ohne eigene Time-Angabe, übernimm
    # die Time-Disambig aus der ursprünglichen Proposition (falls vorhanden).
    if kind in ("acceptance", "commitment") and (bound.get("tense") == "unbound") and proposition_id:
        orig = next((p for p in props if p.get("id") == proposition_id), None)
        if orig and isinstance(orig, dict) and orig.get("time_tense") in ("past", "ambiguous", None):
            if orig.get("time_tense") == "past" or orig.get("time_ambiguous"):
                s["time"] = bound
                s["currentState"] = reduce_current_state(s)
                return s

    def _match(p: dict) -> bool:
        if proposition_id and p.get("id") != proposition_id:
            return False
        status = p.get("status")
        if p.get("kind") == "koerperkontakt":
            # V65S/V65T (AMASTER §36.5 "fruehere Zustimmung ist nicht automatisch aktuelle Zustimmung", §35
            # append-only): every answer of the giver is new evidence of the container, whatever stood before.
            return kind in ("refusal", "acceptance", "revoke")
        if kind == "revoke":
            return status in ("open", "accepted", "active")
        return status == "open"

    candidates = [p for p in props if _match(p)]
    open_prop = None
    if proposition_id:
        open_prop = next((p for p in reversed(candidates) if p.get("id") == proposition_id), None)
    elif candidates:
        # V63 (AMASTER §36.2/§36.3 "an eine konkrete offene Frage oder ein
        # Angebot gebunden … semantisch den angefragten Inhalt", §41.1
        # Immediate Stimulus, §24.6 "Lexikon nur Kandidat"): without a validated
        # reference the answer belongs to the matter raised by the line it
        # answers — the latest perceived line of another actor — and to nothing
        # else. The former fallbacks bound to "the only open one" or by shared
        # words (session 13:39, T9: "gehen" in "wie weit du gehen kannst" bound
        # Tamara's acceptance of "Mach was riskantes" to "Gehen wir ins kino").
        _stim = _stimulus_prop_ids(s, str(actor_id), fact_id)
        _hits = [p for p in candidates if str(p.get("id") or "") in _stim]
        open_prop = _hits[0] if len(_hits) == 1 else None

    _g = grenze if isinstance(grenze, dict) and grenze.get("status") == "validiert" else None
    _kk_extra = None
    if (not open_prop and _g is not None and _g.get("gilt_fuer") in GRENZE_WIDE_SCOPES and _g.get("werId")
            and kind in ("refusal", "acceptance", "revoke") and str(_g.get("werId")) != str(actor_id)):
        # V65T (AMASTER §34.1 "ausdruecklich gesetzte Grenze" als eigene Komponente, §36.5): a validated boundary
        # for every touch by one bound person, set before (or without) an answered act, is her answer to the
        # container "Koerperkontakt wer -> sie".
        open_prop = _body_contact_container(s, str(_g.get("werId")), str(actor_id), int(turn if turn is not None else s.get("turnIndex") or 0))
    elif (open_prop is not None and open_prop.get("kind") != "koerperkontakt" and _g is not None
          and _g.get("gilt_fuer") in GRENZE_WIDE_SCOPES and _g.get("werId") and kind in ("refusal", "acceptance", "revoke")
          and str(_g.get("werId")) != str(actor_id)):
        # V65T (§34.1 several components of one utterance): "Nein - und fass mich nie wieder an" answers the request
        # AND sets the boundary; the boundary is bound to the container as its own entry below.
        _kk_extra = _body_contact_container(s, str(_g.get("werId")), str(actor_id), int(turn if turn is not None else s.get("turnIndex") or 0))
    if (not open_prop and isinstance(grenze, dict) and grenze.get("status") == "unbestaetigt" and grenze.get("einschraenkung")
            and kind in ("refusal", "acceptance", "revoke")):
        # V65X (live 30.10.: "Nur meine Hand darfst du halten" - the reading's direction contradicted the answer kind): an
        # UNCONFIRMED answer that names its own part is still the giver's evidence. When it names exactly one person whose
        # container toward her already exists, it is recorded there as an answer for no act (scope diese_tat, its words
        # kept, grenze unbestaetigt) - it binds nothing, but her standing refusal no longer declines an act naming that part
        # against her later words (scene_state.body_contact_standing `ausnahmen`). No container is created for it.
        _wids = _named_by_name_part(str(grenze.get("wer") or ""), _session_cast(s, [])) - {str(actor_id)}
        if len(_wids) == 1:
            open_prop = _scene.body_contact_proposition(s, next(iter(_wids)), str(actor_id))
    if not open_prop:
        commit_session_change(s, sync_scene=False)
        return s
    if open_prop.get("kind") == "koerperkontakt" and (kind not in ("refusal", "acceptance", "revoke")
                                                      or str(actor_id) != str(open_prop.get("targetId") or "")):
        # V65S (AMASTER §36.5 "giver"; "das tatsaechliche Stattfinden einer Handlung erzeugt rueckwirkend keine
        # Acceptance"): only the giver (the touched figure) accepts, refuses or revokes consent to body contact;
        # the actor cannot fulfil or accept it for her.
        commit_session_change(s, sync_scene=False)
        return s
    recipient = open_prop.get("targetId")
    # V60 (AMASTER §35, §36.3): the REQUESTER accepting the recipient's bound
    # response closes her own request as fulfilled. Without a bound response
    # of the recipient there is nothing to accept (no self-made deal).
    if kind == "acceptance" and str(actor_id) == str(open_prop.get("actorId") or "") and recipient and actor_id != recipient:
        if any(e.get("kind") in ("response_action", "response_speech") and str(e.get("by") or "") == str(recipient)
               for e in open_prop.get("evidence") or [] if isinstance(e, dict)):
            kind = "fulfill"
        else:
            commit_session_change(s, sync_scene=False)
            return s
    # V62 (AMASTER §36.2 "Eine Refusal gilt nur, wenn die antwortende Figur der
    # berechtigte Empfänger ist", §36.3 "Sprecher und Empfänger stimmen"): a
    # request WITHOUT a bound recipient cannot be refused, accepted or committed
    # to by anybody. Before V62 the missing recipient let any figure close it,
    # while the goal reducer (same §) rejected that — the commit failed with 409.
    if kind in ("refusal", "acceptance", "commitment") and (not recipient or str(actor_id) != str(recipient)):
        commit_session_change(s, sync_scene=False)
        return s
    if lifecycle_evidence_fact(s, str(actor_id), fact_id) is None:
        # Stand 07 / K-01 (W2; AMASTER §35 "Der aktuelle Zustand wird aus der neuesten gueltigen Evidenz reduziert"):
        # the stored status changed BEFORE the evidence was searched - an answer without the actor's own utterance or
        # act changed the matter. No evidence: nothing changes (fail-closed), no lifecycle fact.
        commit_session_change(s, sync_scene=False)
        return s
    if open_prop.get("kind") == "koerperkontakt":
        # V65T (§35 "Der aktuelle Zustand wird aus der neuesten gueltigen Evidenz reduziert", §36.5): the answer is
        # bound with its acts and scope; the container's status is the boundary standing now (open without one).
        _bind_lifecycle_evidence(s, actor_id=actor_id, text=text, kind=kind, prop=open_prop, fact_id=fact_id,
                                 body_contact=_body_contact_answer(s, open_prop, actor_id=str(actor_id), fact_id=fact_id, grenze=grenze))
        _now = session_clock(s)
        open_prop["status"] = (_scene.body_contact_standing(s, open_prop, at=_now.isoformat(timespec="minutes") if _now else None)
                               or {}).get("state") or "open"
        s["currentState"] = reduce_current_state(s)
        commit_session_change(s, sync_scene=False)
        return s
    if kind == "refusal":
        open_prop["status"] = "declined"
    elif kind == "acceptance":
        open_prop["status"] = "accepted"
    elif kind == "commitment":
        open_prop["status"] = "active"
    elif kind == "revoke":
        if actor_id not in (open_prop.get("actorId"), open_prop.get("targetId")):
            commit_session_change(s, sync_scene=False)
            return s
        open_prop["status"] = "revoked"
    elif kind == "fulfill":
        # B.7: Future-Prop kann nicht erfüllt werden, wenn die Zeit
        # noch nicht gekommen ist. "Morgen treffen" lässt sich nicht
        # heute erfüllen.
        if open_prop.get("time_tense") == "future":
            resolved = open_prop.get("time_resolved_date")
            if resolved:
                real_s = (s.get("time") or {}).get("real")
                parsed_real = _parse_real(real_s)
                if parsed_real and str(parsed_real.date()) < str(resolved):
                    commit_session_change(s, sync_scene=False)
                    return s
        open_prop["status"] = "fulfilled"
    _bind_lifecycle_evidence(s, actor_id=actor_id, text=text, kind=kind, prop=open_prop, fact_id=fact_id)
    if _kk_extra is not None:
        _bind_lifecycle_evidence(s, actor_id=actor_id, text=text, kind=kind, prop=_kk_extra, fact_id=fact_id, stamp=False,
                                 body_contact=_body_contact_answer(s, _kk_extra, actor_id=str(actor_id), fact_id=fact_id, grenze=grenze))
        _now = session_clock(s)
        _kk_extra["status"] = (_scene.body_contact_standing(s, _kk_extra, at=_now.isoformat(timespec="minutes") if _now else None)
                               or {}).get("state") or "open"
    # V62 (AMASTER §35 "Der aktuelle Zustand wird aus der neuesten gültigen
    # Evidenz reduziert"): the goal bound to this Proposition gets its current
    # state from the ONE goal reducer over the lifecycle fact just appended —
    # the same reducer the SQLite writer (repos.patch_session_goal) uses. Before
    # V62 the status was copied here directly and could disagree with the
    # writer's reduction (409 GOAL_EVIDENCE_REQUIRED, whole turn lost).
    _reduced = {str(g.get("id")): g for g in reduce_goal_state(s)}
    for g in goals:
        if g.get("proposition_id") == open_prop.get("id") or g.get("propositionId") == open_prop.get("id"):
            r = _reduced.get(str(g.get("id")))
            if r is not None:
                for key in ("status", "lifecycleFactId", "lifecycleTurn"):
                    if key in r:
                        g[key] = r[key]
    commit_session_change(s, world=world)
    return s


def bind_puppet_input(
    raw: str,
    plan: Any,
    figure: dict,
    figures: list[dict] | None,
    present_ids: list[str],
    *,
    client_speech: str | None = None,
    client_action: str | None = None,
    addressee_id: str | None = None,
) -> dict[str, Any]:
    """V65J (AMASTER §24.2/§24.6/§27.4; one entry -> one meaning, as the avatar input in
    commit_turn): what a puppet figure says and does, from the SAME planner components
    (bound by bind_input_components) and the explicit *marker*. Returns {"speech",
    "actions" (None = no reading: legacy client split, act without body effect),
    "ambiguous", "used"}."""
    raw = str(raw or "").strip()
    comps = plan.get("komponenten") if isinstance(plan, dict) else None
    # V92 (AMASTER §24.2 Semantikanalyse -> Validierung -> Writer, §24.7 keine stille Kuerzung, §27.4; Live-Diagnose 04.11.):
    # a reading of a non-empty puppet input WITHOUT any component (the contract demands the field) is an INCOMPLETE reading.
    # Before, it was bound as "everything typed is speech" and its machine proposition (a request with the direction reversed)
    # became a canonical open request. Now it is returned as incomplete; the route commits nothing. Not a word rule, no
    # "every input must be an act": a real component list with only `rede` stays speech.
    if raw and isinstance(plan, dict) and not (isinstance(comps, list) and any(isinstance(c, dict) and str(c.get("segment") or "").strip() for c in comps)):
        return {"speech": "", "actions": [], "ambiguous": [{"segment": raw[:160], "grund": "zerlegung_unvollstaendig"}],
                "used": False, "incomplete": True}
    if raw and not isinstance(plan, dict):
        # V92 (Paket-5-Pruefung D, Paket-6-Pruefung; AMASTER §24.2, §27.4, §6.2 fail-closed): no reading of the input (planner
        # failed / no provider): whether the text is speech or an act is UNPROVEN - also with a `*...*` marker or a separate
        # action field (they say THAT it is an act, not that it happens, by whom, or that it is not denied). Not re-labelled as
        # speech (the UI sends the whole text as `speech` too, which is no decision). Nothing is committed, the person sees
        # why and keeps the text.
        return {"speech": "", "actions": [], "ambiguous": [{"segment": raw[:160], "grund": "plan_fehlt"}],
                "used": False, "incomplete": True}
    names = [str(figure.get("name") or "")] + [str(a) for a in (figure.get("aliases") or []) if a]
    if names[0]:
        names.append(names[0].split()[0])
    binding = None
    if isinstance(comps, list) and comps:
        present = [f for f in (figures or []) if isinstance(f, dict) and str(f.get("id") or "") in set(present_ids)]
        binding = bind_input_components(raw, comps, actor_id=str(figure.get("id") or ""), actor_names=names,
                                        figures=present, present_ids=list(present_ids), default_target=None, text_tense=None,
                                        addressee_id=addressee_id,   # V65Z (A05): the route's addressee binds "dich"
                                        cut=bool(plan.get("_abgeschnitten")))   # V65Z (A04)
    amb = list((binding or {}).get("ambiguous") or [])
    # V92 Paket 10 (Paket-9-Pruefung P9-01/P9-02): no marker branch of its own any more - a *marker* neither widens a checked act
    # to the whole marked text nor hides the acts of further markers. The binder's validated speech and acts are the result.
    return input_binding_outcome(binding, amb, raw)


def input_binding_outcome(binding: dict | None, amb: list[dict], raw: str = "") -> dict:
    """V92 (Paket-8-Pruefung; AMASTER §24.2, §24.7, §27.3/§27.4, §34.1): the ONE result of a reading for a direct input (puppet and
    avatar): exactly the validated own speech and the validated own acts of the shared binder - never the raw input as a
    fallback. Nothing validated: a component the validation rejected (denied/foreign act, another figure's speech, ...) makes the
    input `nichts_ausfuehrbar`; a reading whose components validate nothing at all (unknown type, words not in the input) is
    `incomplete` (`komponente_ungueltig`). The caller writes nothing in both cases and shows why."""
    if binding is not None and binding.get("used"):
        # Unbound act proposals remain available to the UI and tests but do
        # not qualify as performed events. A route must refuse the entire
        # input when neither executable speech nor an executable act remains.
        _proposed_actions = list(binding.get("actions") or [])
        # P25/R2: a single speech Fact cannot simultaneously address two
        # different canonical people. Do not return it as executable speech
        # to EITHER puppet or avatar writers. The ambiguity stays visible.
        _validated_speech = "" if binding.get("speechTargetConflict") else str(binding.get("speech") or "")
        _nothing = not _validated_speech.strip() and not any(
            isinstance(a, dict) and not a.get("targetBindingInvalid") for a in _proposed_actions)
        _partial = any(isinstance(a, dict) and (
            a.get("grund") in ("lesung_abgeschnitten", "zerlegung_unvollstaendig")
            # Stand 11B: ein Rest kippt die Eingabe nur, wenn er ungekennzeichnet eine Person nennt (s. _speech_from_components)
            or (a.get("grund") == "rest_ohne_komponente" and a.get("nenntPerson") and not a.get("inMarkierung"))
            or (isinstance(a.get("vorschlag"), dict) and not a.get("readNonEvent")
                and a.get("grund") not in ("wirkung_unklar",))
        ) for a in amb) or bool(binding.get("speechTargetConflict"))
        return {"speech": _validated_speech, "actions": _proposed_actions, "ambiguous": amb, "used": True,
                **({"partial_rejection": True} if _partial else {}),
                **({"nichts_ausfuehrbar": True} if _nothing else {}),
                **({"speechTargetSet": True, "speechTarget": binding.get("speechTarget")} if binding.get("speechTargetSet") else {})}
    if any(isinstance(a, dict) and isinstance(a.get("vorschlag"), dict) for a in amb):
        return {"speech": "", "actions": [], "ambiguous": amb, "used": True, "nichts_ausfuehrbar": True}
    return {"speech": "", "actions": [], "ambiguous": amb + [{"segment": str(raw or "")[:160], "grund": "komponente_ungueltig"}],
            "used": False, "incomplete": True}


def commit_puppet(
    session: dict,
    figure: dict,
    speech: str,
    action: str | None = None,
    *,
    world: dict | None = None,
    plan: dict | None = None,
    target_id: str | None = None,
    action_target_id: str | None = None,
    actions: list[dict] | None = None,
    component_ambiguity: list[dict] | None = None,
    language: list[dict] | None = None,
    figures: list[dict] | None = None,
    wortlaut: str | None = None,
) -> dict:
    """V65J (AMASTER §24.2/§24.6/§27.4, Prüfbericht v2.2 Kette C): the acts of a
    puppet figure are the SAME validated components as an avatar input (planner
    reading -> bind_input_components -> body-effect reading), passed as `actions`
    ({text, targetId, effectKind, effectValid, wirkungPruefung}). A body effect is
    written only from a validated class - never from a word in the text: before,
    "Johann schlägt Mara nicht." and "... wird Mara später schlagen." hit Mara.
    The legacy `action` text (direct kernel callers, no reading) is committed as
    an act without a guessed body effect, as the avatar path does (§24.6)."""
    kwargs = {"plan": plan}
    s = copy.deepcopy(session)
    # V92 Paket 19 (Pruefung P18 N1/N2; AMASTER §43 Capability, §43.1): the body state at the START of the turn decides speech
    # and every act - asleep or unconscious the figure speaks no words (can_speak_now), and the only act a sleeping figure can do
    # is her own validated waking (act_capability); a waking act releases no other act of the same input.
    rt = copy.deepcopy((s.get("runtimes") or {}).get(str(figure["id"]), {}))
    gagged = not can_speak_now(rt)
    spoken = "" if gagged else str(speech or "")
    _acts = [a for a in (actions or []) if isinstance(a, dict) and str(a.get("text") or "").strip()
             and not a.get("targetBindingInvalid")]
    if actions is None and action:
        # Legacy input has no semantic effect reading; its physical result is
        # NOT inferred, but the actual performed action still belongs to the turn.
        _acts = [{"text": action, "targetId": action_target_id, "effectKind": None, "effectValid": False}]
    _names = _figure_name_forms(figure)
    _verdicts = []
    for a in _acts:
        _ch, _au = own_body_change(a.get("koerperPruefung"), str(a.get("text") or "").strip())
        _verdicts.append((*act_capability(rt, str(a.get("text") or "").strip(), _ch, _au, authority="puppet", names=_names), _au))
    executed_action_possible = any(v[0] is None for v in _verdicts)
    if not spoken.strip() and not executed_action_possible:
        # First false seam, V91: a gagged/non-speaking figure used to create
        # a fake speech turn "—", speech Fact, TurnTruth and two relationships.
        # An unexecuted input is not a canonical event and must not increment
        # the turn index. The API/UI may show an error; no fabricated follow-up.
        return s
    s["turnIndex"] = next_turn_index(s)
    turn = s["turnIndex"]
    # V62 (AMASTER §25, §36.1): the addressee bound by the route (canonical
    # resolver) is the TurnTruth target of the puppet speech.
    _tid = str(target_id or "") or None
    if _tid == str(figure.get("id") or ""):
        _tid = None
    truth = bind_from_session(
        s, role="puppet", authority="character", speaker_id=figure["id"], target_id=_tid, input_kind="puppet", text=speech
    )
    if str(wortlaut or "").strip():
        truth["wortlaut"] = str(wortlaut)[:1200]   # Stand 11C: die ganze Puppet-Aeusserung woertlich (Provenienz, keine Wahrheit)
    attach_turn_truth(s, truth)
    # Capability has already been decided against the canonical runtime before
    # the writer advances turnIndex; the same result is used for turn and Facts.
    impossible = capability_blocks_action(rt, action)
    s.setdefault("turns", []).append(
        {
            "id": uid("ln"),
            "turn": turn,
            "speakerId": figure["id"],
            "speakerName": figure.get("name"),
            "role": "character",
            "speech": spoken,
            "action": None if impossible else action,
            "firedSpaces": [],
        }
    )
    if component_ambiguity:
        for _tt in s.get("turnTruths") or []:
            if _tt.get("id") == truth["id"]:
                _tt["input_component_ambiguity"] = copy.deepcopy(component_ambiguity)   # V65Z (A04): all, visibly
                break
    new_facts: list[dict] = []
    # V65F (AMASTER §34 SceneFact bindet Actor UND Target, §25, §23): the
    # addressee the route bound into the TurnTruth is the speech Fact's target
    # (before: targetId None while TurnTruth target = Mara; v2.1 E10).
    sf = None
    if spoken.strip():
        sf = make_fact(
            turn=turn,
            actorId=figure["id"],
            targetId=truth.get("target_id"),
            kind="speech",
            event_kind="speech",
            text=spoken,
            authority="character",
            sourceTurnId=truth["id"],
            truth=truth,
            scene=s.get("scene") or {},
        )
        # Only speech the figure actually uttered is language and scene truth.
        if isinstance(language, list):
            sf["sprache"] = bind_language(str(speech or ""), language, speaker_id=str(figure["id"]),
                                          addressee_id=(str(truth.get("target_id")) if truth.get("target_id") else None),
                                          figures=figures if figures is not None else [figure])
        s.setdefault("facts", []).append(sf)
        new_facts.append(sf)
    # V65G (AMASTER §44 Erstkontakt wie V30, §23 ein Eingangsweg -> eine
    # Bedeutung, §27.4 Puppet ist Rede DER Figur): speech of a figure to a
    # present figure stands in a directed RelationshipState like every other
    # figure speech (commit_turn input phase). The puppet path skipped it:
    # Robert's "Hey schatz" to Mara left Mara->Robert absent; her brief showed
    # no relation to the one speaking, and her Erleben got trust/closeness 0
    # without a kind. Only figures; the Bedienperson never (V65F.2).
    _pt = str(truth.get("target_id") or "")
    if (spoken and _pt and _pt != str(figure["id"]) and _pt in ((s.get("scene") or {}).get("presentIds") or [])
            and _pt not in (*_OPERATOR_IDS, "observer") and str(figure["id"]) not in (*_OPERATOR_IDS, "observer")):
        _ensure_directed_rel(s, str(figure["id"]), _pt, cause=truth.get("id"))
        _ensure_directed_rel(s, _pt, str(figure["id"]), cause=truth.get("id"))
    _present_now = set((s.get("scene") or {}).get("presentIds") or [])
    _done: list[str] = []
    for comp, (_cap, _kchg, _wake, _kaud) in zip(_acts, _verdicts):
        a_text = str(comp.get("text") or "").strip()
        a_impossible = _cap is not None
        af = make_fact(
            turn=turn,
            actorId=figure["id"],
            kind="action",
            event_kind="action",
            text=a_text,
            authority="character",
            sourceTurnId=truth["id"],
            truth=truth,
            scene=s.get("scene") or {},
            validated=not a_impossible,
            rejection_reason="capability" if a_impossible else None,
        )
        af["speech_act"] = "act"
        af["effect"] = {"wirkung": comp.get("wirkung"), "effectKind": comp.get("effectKind"), "validated": bool(comp.get("effectValid"))}
        if comp.get("wirkungPruefung"):
            af["effect"]["pruefung"] = copy.deepcopy(comp.get("wirkungPruefung"))
        if isinstance(comp.get("grenzBezug"), list):
            af["effect"]["grenzBezug"] = copy.deepcopy(comp["grenzBezug"])   # V65W (C1)
        if _wake:
            # V92 Paket 19: the act of a sleeping figure is her waking up - no effect on anybody else
            af["effect"] = {"wirkung": None, "effectKind": None, "validated": False, "nurAufwachen": True}
        _mark_outcome_from_check(af["effect"])
        af["effect"]["koerperPruefung"] = _kaud
        s["facts"].append(af)
        new_facts.append(af)
        if a_impossible:
            continue
        # V62 (AMASTER §25, §34.1): the affected figure of the ACTION is bound
        # separately from the addressee of the speech (review: "Tom, sieh her!
        # *schlägt Tammy*" must not hit Tom). Without a bound target there is no
        # physical target.
        _atid = str(comp.get("targetId") or "") or None
        if _atid == str(figure.get("id") or "") or (_atid and _atid not in _present_now):
            _atid = None
        af["targetId"] = _atid
        # V92 (Kettenvertrag §6; make_fact default "affected_ids = [target]"): the target is bound only here, after make_fact,
        # so the Fact kept the empty list of the unbound state - the affected figure of the act is its bound target
        af["affected_ids"] = [_atid] if _atid else []
        if _atid and isinstance(comp.get("bitteBezug"), list):
            # V65W (C7): the puppet's own act that carries out its request she accepted (read server-side)
            af["effect"]["bitteBezug"] = copy.deepcopy(comp["bitteBezug"])
            if _input_acts_incomplete(component_ambiguity):
                af["effect"]["bitteBindung"] = "eingabe_unvollstaendig"   # V65X (E05)
            else:
                _bind_own_act_to_request(s, af, comp["bitteBezug"], turn=turn)
        if not _wake:
            _apply_physical(
                s,
                actor_id=figure["id"],
                target_id=_atid,
                text=a_text,
                validated=True,
                source_turn_id=truth["id"],
                authority="puppet",
                truth=truth,
                turn=turn,
                new_facts_out=new_facts,
                effect_kind=comp.get("effectKind") if comp.get("effectValid") else None,
                fact_id=af["id"],
                world=world,
            )
        # V92 Paket 18/19: only the change of its own body the server's readings validated for this act (reading + confirmation)
        _w = write_body_change(s, str(figure["id"]), _kchg, fact_id=af["id"], turn=turn, authority="puppet", text=a_text,
                               actor_name=str(figure.get("name") or ""))
        if _w.get("fehler"):
            af["effect"]["koerperFehler"] = _w["fehler"]
        # V65J (AMASTER §38 Memory mit Quelle und Fact, §34.2; "Wer hat es getan, wer
        # hat es erlebt"): the puppet figure remembers its act, the affected and the
        # seeing figures remember it too - the same writer rule as an executed Regie act.
        f_name = figure.get("name") or figure["id"]
        s.setdefault("memories", []).append(make_memory(
            characterId=figure["id"], kind="getan", text=a_text[:180], salience=0.6, turn=turn,
            witnesses=[figure["id"]], layer="session", truthStatus="canon", source="commit_puppet",
            factId=af["id"], sourceTurnId=truth["id"], sessionId=s.get("id"), worldId=s.get("worldId")))
        for cid in _present_now - {str(figure["id"])}:
            access = witness_access(truth, af, cid)
            if access not in ("affected", "seen"):
                continue
            s.setdefault("memories", []).append(make_memory(
                characterId=cid, kind="erlebt" if access == "affected" else "gesehen",
                text=a_text[:180] if access == "affected" else f"{f_name}: {a_text[:160]}",
                salience=0.6, turn=turn, witnesses=[cid], layer="session", truthStatus="canon",
                source="commit_puppet", factId=af["id"], sourceTurnId=truth["id"],
                sessionId=s.get("id"), worldId=s.get("worldId")))
        _done.append(a_text)
    if _acts and s.get("turns"):
        s["turns"][-1]["action"] = " ".join(_done) or None   # Stand 11D
    if spoken and spoken != "—":
        s.setdefault("memories", []).append(
            make_memory(
                characterId=figure["id"],
                kind="gesagt",
                text=spoken[:180],
                salience=0.55,
                turn=turn,
                witnesses=[figure["id"]],
                layer="session",
                truthStatus="canon",
                source="commit_puppet",
                # V65F (AMASTER §38 Memory: Quelle, Fact-ID; §34.2 cause): the
                # memory points to the speech Fact it remembers (v2.1 E17).
                factId=sf["id"], sourceTurnId=truth["id"], sessionId=s.get("id"), worldId=s.get("worldId"),
            )
        )
        present_hear = set(truth.get("present_ids") or (s.get("scene") or {}).get("presentIds") or [])
        for hid in _effective_hears(s, truth):
            if not hid or hid == figure["id"] or hid not in present_hear:
                continue
            s.setdefault("memories", []).append(
                make_memory(
                    characterId=hid,
                    kind="gehoert",
                    text=f"{figure.get('name') or figure['id']}: {spoken[:180]}",
                    salience=0.5,
                    turn=turn,
                    witnesses=[hid],
                    layer="session",
                    truthStatus="canon",
                    source="commit_puppet",
                    factId=sf["id"], sourceTurnId=truth["id"], sessionId=s.get("id"), worldId=s.get("worldId"),
                )
            )
    _record_fact_witnesses(s, truth, new_facts, turn)
    # V39: Puppet-Rede bekommt ebenfalls einen Turn-Plan (LLM-Plan aus kwargs oder lokal) → Frames
    if spoken:
        _pp = _conj.normalize_plan(kwargs.get("plan") if isinstance(kwargs, dict) else None, actor_id=str(figure["id"]), recipient_id=str(truth.get("target_id") or "") or None, text=spoken, now=_session_now(s), present_ids=list((s.get("scene") or {}).get("presentIds") or [])) if isinstance(kwargs, dict) and kwargs.get("plan") else None
        if _pp is None:
            # V60 (AMASTER §24.6, §68 Nr. 54): no regex speech-act reader.
            _pp = _conj.literal_plan(spoken, actor_id=str(figure["id"]), recipient_id=str(truth.get("target_id") or "") or None)
        sf["plan"] = _pp
        hears_now = list(_scene_perception(s, list((s.get("scene") or {}).get("presentIds") or []))[0])   # Stand 07 / K-01: canonical perception (explicit empty list, position, canHear, consciousness)
        ch = _conj.apply_plan(s, _pp, fact_id=sf["id"], turn=turn, witnesses=list(dict.fromkeys(hears_now + [str(figure["id"])])))
        if ch:
            sf["frameChange"] = ch
    if spoken and spoken != "—":
        # V60 (AMASTER §35/§36, §68 Nr. 54): lifecycle from the validated plan
        # of this speech, the same mapping as the normal commit — never a word list.
        _life = {"request": "request", "proposal": "request", "promise": "commitment",
                 "acceptance": "acceptance", "refusal": "refusal", "revocation": "revoke"}
        _pp_now = sf.get("plan") if isinstance(sf.get("plan"), dict) else {}
        life = _life.get(str(_pp_now.get("event_kind") or "")) if _pp_now.get("source") == "llm" else None
        if life:
            _ref = str(_pp_now.get("refers_to") or "").strip().strip("[]")
            _pid = next((p.get("id") for p in s.get("propositions") or [] if _ref and _ref in (p.get("id"), p.get("text"), p.get("matter"))), None)
            if _pid is None and _ref:   # V63 (§35): a request goal names its Proposition
                _g_ref = next((g for g in s.get("goals") or [] if isinstance(g, dict) and str(g.get("id") or "") == _ref), None)
                _pid = ((_g_ref or {}).get("proposition_id") or (_g_ref or {}).get("propositionId")) or None
            if _pid is None and not _conj.proposal_opens_matter(_pp_now):
                life = None  # V62 (§24.7, §36.3): "proposal" read as utterance opens no NEW matter
        if life:
            s = apply_proposition(
                s,
                actor_id=str(figure.get("id") or ""),
                text=spoken,
                kind=life,
                target_id=truth.get("target_id"),
                world=world,
                proposition_id=_pid,
                fact_id=sf.get("id"),
                matter=str(_pp_now.get("summary") or "") or None,
                time_window=(_pp_now.get("temporal") or {}).get("label") or None,
                grenze=_resolve_grenze(s, _pp_now.get("grenze"), [figure, *(figures or [])], figure.get("id")),
            )
    # V65P (AMASTER §28 Schritte 12–14 "eingehende Effects committen … SceneState
    # laden", §27.4 Puppet ist die tatsaechliche Handlung DER Figur; Pruefung
    # v2.5/v2.6 §4, IST-Probe 1): the puppet commit writes the scene state with
    # the SAME writer and the same arguments as the input phase of commit_turn
    # (speaker, bound addressee, validated acts and their effect classes). Before,
    # Johann's push left escalation 0.00 and the last beat at Mara's withdrawal.
    try:
        _pids = [str(x) for x in ((s.get("scene") or {}).get("presentIds") or [])]
        _pacts = [f for f in new_facts if isinstance(f, dict) and f.get("kind") == "action"
                  and str(f.get("actorId")) == str(figure["id"]) and _scene.validiert(f)]
        _ptid = (str(truth.get("target_id")) if truth.get("target_id") and str(truth.get("target_id")) in _pids
                 else next((str(f.get("targetId")) for f in _pacts if f.get("targetId") and str(f.get("targetId")) in _pids), None))
        _sch = _scene.update_from_commit(
            s, speaker_id=str(figure["id"]), target_id=_ptid, speech=str(spoken or "") if spoken != "—" else "",
            action=(" ".join(_done) or None), fired=[], runtime=(s.get("runtimes") or {}).get(str(figure["id"])),
            plan=(sf.get("plan") if isinstance(sf, dict) and isinstance(sf.get("plan"), dict) else None),
            physical_changed=any(isinstance(f, dict) and f.get("event_kind") in ("body_state", "physical")
                                 and str(f.get("actorId")) == str(figure["id"]) for f in new_facts),
            action_validated=bool(_pacts), turn=turn, present_ids=_pids,
            act_outcomes=[(f.get("effect") or {}).get("outcome") for f in _pacts],
            effect_kinds=[str((f.get("effect") or {}).get("effectKind")) for f in _pacts
                          if isinstance(f.get("effect"), dict) and (f.get("effect") or {}).get("validated")],
        )
        if _sch and s.get("turns"):
            s["turns"][-1]["sceneDelta"] = _sch
    except Exception as _scene_exc:  # as in commit_turn: never a turn abort, visible in the Fact log
        s.setdefault("facts", []).append(make_fact(turn=turn, actorId="kernel", kind="diagnostic", event_kind="diagnostic",
                                                   text=f"sceneState: {type(_scene_exc).__name__}: {str(_scene_exc)[:120]}",
                                                   authority="kernel", sourceTurnId=truth["id"], truth=truth, scene=s.get("scene") or {}, validated=True))
    commit_session_change(s, source_turn_id=truth["id"])
    annotate_turn_rows(s, session, turn)   # V65T
    return s


def normalize_truth(t: dict) -> dict:
    present = t.get("present_ids") or t.get("presentIds") or []
    hears = t.get("hears_ids") if "hears_ids" in t else t.get("hearsIds")
    sees = t.get("sees_ids") if "sees_ids" in t else t.get("seesIds")
    informed = t.get("informed_ids") if "informed_ids" in t else t.get("informedIds")
    affected = t.get("affected_ids") if "affected_ids" in t else t.get("affectedIds")
    bound = bind_turn_truth(
        user_id=t.get("user_id") or t.get("userId") or "",
        world_id=t.get("world_id") or t.get("worldId") or "",
        session_id=t.get("session_id") or t.get("sessionId") or "",
        role=t.get("role") or "teilnehmer",
        speaker_id=t.get("speaker_id") or t.get("speakerId"),
        avatar_id=t.get("avatar_id") if "avatar_id" in t else t.get("avatarId"),
        target_id=t.get("target_id") if "target_id" in t else t.get("targetId"),
        authority=t.get("authority") or "character",
        present_ids=list(present),
        input_kind=t.get("input_kind") or t.get("inputKind") or "speech",
        text=t.get("text") or "",
        source_turn_id=t.get("source_turn_id") or t.get("sourceTurnId"),
        hears_ids=list(hears) if hears is not None else None,
        sees_ids=list(sees) if sees is not None else None,
        informed_ids=list(informed) if informed is not None else None,
        affected_ids=list(affected) if affected is not None else None,
        scene_id=t.get("scene_id") or t.get("sceneId"),
        time_ref=t.get("time_ref") or t.get("timeRef"),
        upload_ref=t.get("upload_ref") or t.get("uploadRef"),
        input_actor_id=t.get("input_actor_id") or t.get("inputActorId"),
        response_speaker_id=t.get("response_speaker_id") or t.get("responseSpeakerId"),
        puppet_id=t.get("puppet_id") or t.get("puppetId"),
        speak_as=t.get("speak_as") or t.get("speakAs"),
        operator_id=t.get("operator_id") or t.get("operatorId") or t.get("user_id") or t.get("userId"),
    )
    if t.get("id"):
        bound["id"] = t.get("id")
    bound["user_name"] = t.get("user_name") or t.get("userName")
    if t.get("directive"):
        bound["directive"] = str(t.get("directive"))[:300]
    return bound


def seed_relations(characters: list[dict]) -> list[dict]:
    by_name = {(c.get("name") or "").lower(): c for c in characters if isinstance(c, dict) and c.get("id")}
    by_id = {str(c["id"]): c for c in characters if isinstance(c, dict) and c.get("id")}
    out: list[dict] = []
    for c in characters:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        for r in c.get("relations") or []:
            if not isinstance(r, dict):
                continue
            tid = r.get("targetId") or r.get("target_id")
            tname = str(r.get("targetName") or r.get("target_name") or "").lower()
            target = by_id.get(str(tid)) if tid else by_name.get(tname)
            if not target:
                continue
            fear = float(r.get("fear") or 0)
            out.append(
                {
                    "fromId": str(c["id"]),
                    "toId": str(target["id"]),
                    "trust": r.get("trust", 0.4),
                    "closeness": r.get("closeness", 0.4),
                    "fear": fear,
                    "hostility": r.get("hostility") if r.get("hostility") is not None else (0.2 if fear > 0.5 else 0),
                    "note": r.get("note") or "",
                    "kind": r.get("kind") or "knows",
                    "provenienz": {"quelle": "stamm", "characterId": str(c["id"])},   # V65Y: origin of the seed
                }
            )
    return out


SESSION_CLIENT_SELECTION_FIELDS = (
    "name",
    "avatarId",
    "alias",
    "role",
    "pipeline",
    "autoChat",
    "focus",
    "situationId",
    "placeId",
    "presentIds",
    "fateEnabled",
)


def build_new_session(
    world: dict,
    characters: list[dict],
    *,
    session_id: str,
    user_id: str,
    avatar_id: str | None = None,
    situation_id: str | None = None,
    place_id: str | None = None,
    present_ids: list[str] | None = None,
    name: str | None = None,
    role: str | None = None,
    alias: str | None = None,
    pipeline: dict | None = None,
    auto_chat: dict | None = None,
    focus: dict | None = None,
    fate_enabled: bool | None = None,
    now: str | None = None,
) -> dict:
    """V25 SES-01/SES-02 (AMASTERv2 §18/§20/§42/§47/§68.2/§68.3, Vertrag §4/§9).

    Der Server ist alleiniger Wahrheitsowner beim Sessionstart: Szene aus
    Welt (Startlage/Ort), Anwesenheit aus Nutzerauswahl (nur Weltfiguren +
    Avatar), Runtimes ausschließlich aus den Charakterstämmen (kein erlebter
    Zustand einer anderen Session), Ausgangsbeziehungen aus dem Stamm, Fate aus
    der Weltkonfiguration, turnIndex 0, Eröffnungsturn des Narrators.
    """
    now = now or datetime.now(timezone.utc).isoformat()
    world = world if isinstance(world, dict) else {}
    from matrix_api.learning import canonical_stem
    chars = [canonical_stem(c) for c in characters if isinstance(c, dict) and c.get("id")]
    by_id = {str(c["id"]): c for c in chars}
    avatar = by_id.get(str(avatar_id)) if avatar_id else None
    natives = [c for c in chars if c.get("isWorldNative") and str(c["id"]) != str(avatar_id or "")]
    situations = [s for s in (world.get("startSituations") or []) if isinstance(s, dict)]
    sit = next((s for s in situations if situation_id and str(s.get("id")) == str(situation_id)), None) or (situations[0] if situations else {})
    places = [p for p in (world.get("places") or []) if isinstance(p, dict)]
    place = (
        next((p for p in places if place_id and str(p.get("id")) == str(place_id)), None)
        or next((p for p in places if sit.get("placeId") and str(p.get("id")) == str(sit.get("placeId"))), None)
        or (places[0] if places else {"id": "", "name": str(world.get("name") or "Ort"), "description": "", "rules": []})
    )
    place_name = str(place.get("name") or "")
    if present_ids:
        wanted = [str(x) for x in present_ids if x]
        present = [c for c in natives if str(c["id"]) in wanted]
    else:
        names = {str(n).lower() for n in (sit.get("presentNames") or []) if n} or {str(c.get("name") or "").lower() for c in natives}
        present = [c for c in natives if str(c.get("name") or "").lower() in names]
    if not present and natives:
        present = [natives[0]]
    all_chars = natives + ([avatar] if avatar else [])
    present_out = [str(c["id"]) for c in present] + ([str(avatar["id"])] if avatar else [])
    opening = str(sit.get("opening") or f"{place_name}. Die Szene steht.")
    opening_low = opening.lower()
    scene_items = []
    for it in (world.get("items") or [])[:64]:
        key = str(it).split(":")[0].strip().lower()
        if len(key) >= 4 and (key in opening_low or key in str(place.get("description") or "").lower() or key in place_name.lower()):
            scene_items.append(str(it))
        if len(scene_items) >= 6:
            break
    seeds = [s for s in (world.get("fateSeeds") or []) if isinstance(s, dict)]
    fate_on = bool(world.get("fateEnabled")) if fate_enabled is None else bool(fate_enabled)
    session = {
        "id": session_id,
        "worldId": str(world.get("id") or ""),
        "userId": user_id,
        "name": str(name or "").strip() or f"{world.get('name') or 'Welt'} · {now[11:16]}",
        "createdAt": now,
        "updatedAt": now,
        "avatarId": str(avatar["id"]) if avatar else None,
        "alias": str(alias or (avatar.get("name") if avatar else "") or "Spieler"),
        "role": str(role or "teilnehmer"),
        "scene": {
            "placeId": str(place.get("id") or ""),
            "placeName": place_name,
            "time": str(sit.get("time") or "jetzt"),
            "presentIds": present_out,
            "tension": 0.35,
            "danger": 0.15,
            "openMatters": [m for m in [opening, *list((place.get("rules") or [])[:2])] if m],
            "notes": opening,
            "phase": "Anfang",
            "items": scene_items,
            "bounds": [str(x) for x in (world.get("knowledgeLimits") or world.get("knowledgeBounds") or [])[:4]],
            "conflicts": [str(x) for x in (world.get("conflicts") or [])[:4]],
        },
        "runtimes": {},
        "relations": [],
        "fate": {
            "enabled": fate_on,
            "pressure": 0.45 if fate_on else 0,
            "beat": str((seeds[0].get("beat") if seeds else "") or opening),
            "activeSeedId": seeds[0].get("id") if seeds else None,
            "lastShiftTurn": 0,
            "mustNot": str((seeds[0].get("mustNot") if seeds else "") or "Kein erfundenes Wissen. Abwesende wissen nichts. Avatar nicht steuern."),
        },
        "turnIndex": 0,
        "pipeline": pipeline if isinstance(pipeline, dict) else {"fate": True, "meta": True, "narrator": True},
        "autoChat": auto_chat if isinstance(auto_chat, dict) else {"enabled": False, "turns": 2, "delayMs": 5000, "contextTurns": 10},
        "focus": focus if isinstance(focus, dict) else {},
        "serverBuilt": True,
        "witnessKnowledge": [],
        "currentState": {},
    }
    session["fate"] = _ensure_fate_mustNot(session["fate"], world)
    # Runtimes/Relations ausschließlich aus dem Stamm (kein Sessiondrift).
    seeded = reset_runtime_only({**session, "runtimes": {str(c["id"]): {} for c in all_chars}}, all_chars)
    session["runtimes"] = seeded.get("runtimes") or {}
    for cid, rt in session["runtimes"].items():
        rt["position"] = place_name if cid in present_out else "anderswo"
    session["relations"] = seeded.get("relations") or []
    session["turns"] = [
        {
            "id": uid("ln"),
            "turn": 0,
            "speakerId": "narrator",
            "speakerName": "Szene",
            "role": "narrator",
            "speech": opening,
            "firedSpaces": [],
            "source": "engine",
        }
    ]
    session["goals"] = []
    for c in natives:
        # AMASTER 7/14/18/35: preserve the author's complete goal definition.
        # Presentation metadata (phase/next/exit) is not executable lifecycle.
        # A long-term goal is neither a current intent nor a speaking duty.
        for index, definition in enumerate(c.get("goals") or []):
            raw = definition if isinstance(definition, dict) else {}
            text = raw.get("text") if isinstance(definition, dict) else definition
            if not isinstance(text, str) or not text.strip():
                continue
            goal = {
                "id": uid("goal"), "ownerId": str(c["id"]), "text": text,
                "status": "open", "kind": "stamm",
                "sourceGoalId": str(raw.get("id") or ""),
                "sourceGoalIndex": index,
                "sourceDefinition": copy.deepcopy(definition),
            }
            # These are author-defined bindings, not guessed thresholds.
            for field in ("priority", "time_scope", "time_window", "recipientId",
                          "targetId", "proposition_id", "propositionId"):
                if field in raw:
                    goal[field] = copy.deepcopy(raw[field])
            session["goals"].append(goal)
    session["memories"] = []
    session["facts"] = []
    session["godFacts"] = []
    session["propositions"] = []
    return session


def initial_character_intent(character: dict) -> str:
    """AMASTER 7/42: no current intent can be inferred from goal order.

    Initial goals remain fully available in their owner. A current intention
    is written by the existing session-event/effect path, not by this reset.
    """
    return ""


def reset_runtime_only(session: dict, characters: list[dict]) -> dict:
    from matrix_api.learning import canonical_stem
    characters = [canonical_stem(c) for c in characters]
    s = copy.deepcopy(session)
    place = (s.get("scene") or {}).get("placeName") or ""
    runtimes = s.setdefault("runtimes", {})
    for c in characters:
        cid = c.get("id")
        if not cid:
            continue
        if cid in runtimes or cid in (s.get("scene") or {}).get("presentIds", []) or s.get("avatarId") == cid:
            body = c.get("body") or {}
            runtimes[cid] = {
                "characterId": cid,
                "emotion": "wach",
                "intensity": 0.35,
                "fear": 0.25 if c.get("fears") else 0.1,
                "trust": 0.4,
                "lust": 0.05,
                "pain": body.get("pain", 0),
                "shame": 0.1,
                "anger": 0.1,
                "fatigue": 0.2,
                "stress": 0.25,
                "intent": initial_character_intent(c),
                "mobility": body.get("mobility", 1),
                "consciousness": body.get("consciousness", 1),
                "position": place,
                "constraints": list(body.get("constraints") or []),
                "canSpeak": True,
                "restrained": False,
                "gagged": False,
            }
    s["relations"] = seed_relations(characters)
    return s


def reset_memory_only(session: dict) -> dict:
    s = copy.deepcopy(session)
    s["memories"] = []
    return s


def sync_runtime_trust(session: dict, character_id: str, to_id: str | None = None) -> dict:
    """Runtime.trust is a mirror of Relationship.trust (owner). Mutates session in place."""
    rels = session.get("relations") or []
    outgoing = [r for r in rels if r.get("fromId") == character_id]
    if to_id:
        outgoing = [r for r in outgoing if r.get("toId") == to_id]
    if not outgoing:
        return session
    chosen = outgoing[0]
    rt = (session.get("runtimes") or {}).get(character_id)
    if isinstance(rt, dict) and "trust" in chosen:
        rt["trust"] = chosen.get("trust")
    return session


_CUE_STOP = frozenset(
    {
        "woran",
        "erinnerst",
        "erinnern",
        "meiner",
        "meinen",
        "vorhin",
        "nicht",
        "anderen",
        "andere",
        "sache",
        "gerade",
        "etwas",
        "diese",
        "dieser",
        "einem",
        "einer",
        "nochmal",
    }
)
_MATTER_HINT = re.compile(
    r"bitte|kündig|verlass|brief|\babend\b|\bhaus\b|nichts sag|nichts von|deal|schicht|\barbeit",
    re.I,
)


def _negated_terms(cue: str) -> set[str]:
    found: set[str] = set()
    for m in re.finditer(
        r"nicht\s+(?:vom|von\s+der|von\s+dem|von\s+den|von|der|die|das)\s+([A-Za-zÄÖÜäöüß]{3,})",
        cue or "",
        re.I,
    ):
        found.add(m.group(1).lower())
    return found


def _relevance_score(
    item: dict,
    cue: str | None,
    *,
    lifecycle_boost: bool = False,
    open_texts: list[str] | None = None,
) -> tuple:
    text = str(item.get("text") or item.get("summary") or "")
    low = text.lower()
    cue_l = (cue or "").lower()
    rel = 0.0
    negated = _negated_terms(cue or "")
    if any(n in low for n in negated):
        rel -= 14.0
    if _GREET_LINE_RE.search(low):
        rel -= 8.0
    if cue_l:
        for w in re.findall(r"[a-zäöüß]{4,}", cue_l):
            if w in _CUE_STOP or w in negated:
                continue
            if w in low:
                rel += 2.0
    rel += float(item.get("salience") or 0)
    if lifecycle_boost or item.get("kind") == "lifecycle" or item.get("proposition_id") or item.get("propositionId"):
        rel += 8.0
    if item.get("status") in ("open", "active", "accepted") or item.get("kind") in ("request", "lifecycle"):
        rel += 6.0
    if open_texts:
        for ot in open_texts:
            ol = str(ot or "").lower().strip()
            if len(ol) < 8:
                continue
            if not _MATTER_HINT.search(ol) and not re.search(r"\bbitte\b|bleib|kündig", ol):
                continue
            if ol[:48] in low or any(tok in low for tok in re.findall(r"[a-zäöüß]{5,}", ol)[:8] if tok not in _CUE_STOP):
                rel += 12.0
                break
    if re.search(r"bitte|vorhin|erinner|kündig|verlass", cue_l) and _MATTER_HINT.search(low):
        rel += 10.0
    turn = int(item.get("turn") or 0)
    retrospective = bool(re.search(r"vorhin|bitte|andere sache|erinner", cue_l))
    recency = -turn if retrospective else turn
    return (rel, recency)


_SPIEGEL_FACT_LIMIT = 10
_PFLICHT_KINDS = frozenset({"lifecycle", "request"})
_PFLICHT_EVENTS = frozenset(
    {
        "refusal",
        "acceptance",
        "commitment",
        "fulfill",
        "revoke",
        "request",
        "ask",
        "consequence",
    }
)
_CHAIN_PROP_STATUS = frozenset({"open", "active", "accepted", "declined", "revoked", "fulfilled"})


def _fact_prop_id(fact: dict) -> str:
    return str(fact.get("propositionId") or fact.get("proposition_id") or "")


def _is_lifecycle_pflicht(fact: dict) -> bool:
    kind = str(fact.get("kind") or "")
    event = str(fact.get("event_kind") or fact.get("eventKind") or "")
    return kind in _PFLICHT_KINDS or event in _PFLICHT_EVENTS


def _is_consequence_pflicht(fact: dict) -> bool:
    event = str(fact.get("event_kind") or fact.get("eventKind") or "")
    if event in ("consequence", "fulfill"):
        return True
    return bool(_RESIGN_RE.search(str(fact.get("text") or "")))


def _is_world_pflicht(fact: dict) -> bool:
    kind = str(fact.get("kind") or fact.get("event_kind") or fact.get("eventKind") or "")
    if kind not in ("god", "regie", "scene"):
        return False
    return _scene.validiert(fact)


def _select_conjunctive_facts(
    facts: list[dict],
    *,
    stimulus: str,
    open_texts: list[str] | None = None,
    propositions: list | None = None,
    limit: int = _SPIEGEL_FACT_LIMIT,
    bound_pids: set[str] | None = None,
    bound_fact_ids: set[str] | None = None,
    answerer_id: str | None = None,
) -> list[dict]:
    """Keep Ursache/Ablehnung/Beteiligte/Konsequenz of live chains first, then fill by relevance.

    V65T (AMASTER §40 "dieselbe Proposition", §41.1-§41.3, §41.2 Limit; Plan v2 Schritt 2d; Gegenpruefung v3.3
    Selektor-Befund): ONE bound tier - the facts of the matter the stimulus is bound to (own propositionId) and the
    given bound fact IDs (the matter's evidence, e.g. the acts of a Koerperkontakt container, and the facts of the
    bound referent she knows) - ordered cause first: acts between them and the answerer, other acts, the answers
    (lifecycle), then the rest, each newest first. Before, the evidence acts came after every stamped speech of the
    matter, and with a small limit not at all.

    V65S (AMASTER §41.1/§41.3): members of the matter the immediate stimulus is bound to (bound_pids, by ID)
    come before every other chain; inside, the episode in its order (newest first), lifecycle copies last.
    Then the facts of the persons the stimulus is about (bound_fact_ids, by referent ID), newest first.

    `facts[-10:]` after a descending relevance sort dropped the strongest
    lifecycle members. A blind `facts[:10]` would still drop an older cause
    when unrelated recent lifecycle rows fill the window. Chain members of
    the same proposition stay in the reader even when they outnumber the
    leftover relevance slots.
    """
    if not facts or limit <= 0:
        return []
    props = [p for p in (propositions or []) if isinstance(p, dict)]
    cue_l = (stimulus or "").lower()
    cue_toks = [w for w in re.findall(r"[a-zäöüß]{4,}", cue_l) if w not in _CUE_STOP][:8]
    live_pids = {str(p.get("id") or "") for p in props if p.get("status") in _CHAIN_PROP_STATUS and p.get("id")}
    for p in props:
        pid = str(p.get("id") or "")
        if not pid:
            continue
        blob = str(p.get("text") or "").lower()
        if _MATTER_HINT.search(blob) or (cue_toks and any(t in blob for t in cue_toks)):
            live_pids.add(pid)
    chain_pids = set(live_pids)

    def is_chain_member(f: dict) -> bool:
        pid = _fact_prop_id(f)
        if pid and pid in chain_pids:
            return True
        return _is_consequence_pflicht(f)

    scored = [
        (i, f, _relevance_score(f, stimulus, lifecycle_boost=True, open_texts=open_texts or []))
        for i, f in enumerate(facts)
    ]
    chain = [(i, f, s) for i, f, s in scored if is_chain_member(f)]
    world_pflicht = [(i, f, s) for i, f, s in scored if not is_chain_member(f) and _is_world_pflicht(f)]
    other_pflicht = [
        (i, f, s)
        for i, f, s in scored
        if not is_chain_member(f) and not _is_world_pflicht(f) and _is_lifecycle_pflicht(f)
    ]
    rest = [
        (i, f, s)
        for i, f, s in scored
        if not is_chain_member(f) and not _is_world_pflicht(f) and not _is_lifecycle_pflicht(f)
    ]

    def chain_priority(item: tuple) -> tuple:
        _i, f, s = item
        event = str(f.get("event_kind") or f.get("eventKind") or "")
        kind = str(f.get("kind") or "")
        text = str(f.get("text") or "").lower()
        if event == "refusal" or "lehne" in text or text.startswith("nein"):
            tier = 4
        elif event in ("fulfill", "consequence") or "verlass" in text or "kündig" in text:
            tier = 3
        elif event in ("request", "ask") or kind == "request" or "bitte" in text:
            tier = 2
        else:
            tier = 1
        return (tier, s)

    selected_idx: list[int] = []
    seen: set[int] = set()
    _bp = {str(x) for x in (bound_pids or set())}
    bound = [(i, f, sc) for i, f, sc in scored if _bp and _fact_prop_id(f) in _bp]

    def take(rows: list, *, key) -> None:
        for i, _f, _s in sorted(rows, key=key, reverse=True):
            if len(selected_idx) >= limit:
                return
            if i in seen:
                continue
            seen.add(i)
            selected_idx.append(i)

    _bf = {str(x) for x in (bound_fact_ids or set())}
    _me = str(answerer_id or "")

    def bound_rank(item: tuple) -> tuple:
        _i, f, _s = item
        kind = str(f.get("kind") or "")
        if kind == "action":
            rank = 0 if _me and _me in (str(f.get("actorId") or ""), str(f.get("targetId") or "")) else 1
        elif kind == "lifecycle":
            rank = 2
        else:
            rank = 3
        return (-rank, int(f.get("turn") or 0), _i)   # sorted descending by take(): rank 0 first, newest first

    take(bound + [(i, f, sc) for i, f, sc in scored if _bf and str(f.get("id") or "") in _bf and not (_bp and _fact_prop_id(f) in _bp)],
         key=bound_rank)
    take(chain, key=chain_priority)
    take(world_pflicht, key=lambda item: item[2])
    take(other_pflicht, key=lambda item: item[2])
    take(rest, key=lambda item: item[2])
    return [facts[i] for i in selected_idx]


_EPISODIC_FIRST = re.compile(r"\b(erste[rns]?|zuerst|am anfang|anfangs|als erstes|ganz am anfang|begonnen|angefangen|zu beginn)\b", re.I)
_EPISODIC_BEFORE = re.compile(r"\b(davor|vorher|vorhin|vorletzte[rns]?|zuvor|eben noch|gerade eben|gerade)\b", re.I)
_EPISODIC_LAST = re.compile(r"\b(zuletzt|letzte[rns]?|zum schluss|eben)\b", re.I)
_EPISODIC_HINT = re.compile(r"\b(frage|gesagt|gefragt|gesprochen|erzählt|erzaehlt|geantwortet|gemeint|thema|gespräch|gespraech|erinner|weißt du noch|weisst du noch)\b", re.I)


def episodic_cue(cue: str | None) -> str | None:
    """AMASTERv2 §15/§41: Fragen nach dem Gesprächsverlauf ('was war meine erste Frage',
    'was hast du vorhin gesagt') sind zeitliche Recall-Cues, keine Stichwortsuche."""
    c = str(cue or "")
    if not c.strip():
        return None
    if _EPISODIC_FIRST.search(c):
        return "first"
    if _EPISODIC_BEFORE.search(c):
        return "before"
    if _EPISODIC_LAST.search(c) and _EPISODIC_HINT.search(c):
        return "last"
    if _EPISODIC_HINT.search(c) and re.search(r"\b(was|wann|wie)\b", c, re.I):
        return "any"
    return None


def _episodic_memories(memories: list[dict], mode: str, turn_now: int, limit: int = 4) -> list[dict]:
    """Chronologisch geordnete Dialogerinnerungen (gehört/gesagt) statt Relevanz-Ranking."""
    dialog = [m for m in memories if str(m.get("kind") or m.get("epistemic") or "") in ("gehoert", "gehört", "gesagt", "heard", "said")]
    dialog = sorted(dialog, key=lambda m: (int(m.get("turn") or 0), 0 if str(m.get("kind") or "").startswith("geh") else 1))
    if not dialog:
        return []
    if mode == "first":
        return dialog[:limit]
    if mode == "last":
        return dialog[-limit:]
    if mode == "before":
        prev = [m for m in dialog if int(m.get("turn") or 0) < turn_now]
        return prev[-limit:]
    return dialog[:2] + dialog[-2:]


def recall(session: dict, character_id: str, cue: str | None = None) -> dict:
    """Read mirror. Never writes. No leak of unknown secrets or others' knowledge.

    Presence-only access is not knowledge of speech/action content.
    heard/seen/affected/informed grant fact bodies. God/regie/scene may be
    known by presence because they change the shared world the figure occupies.
    Lifecycle-relevant evidence is ranked above recency-only slices.
    """
    wk = [copy.deepcopy(w) for w in (session.get("witnessKnowledge") or []) if w.get("character_id") == character_id]
    knowing = {"heard", "seen", "affected", "informed"}
    # V60 (AMASTER §26, §46.2): a Regie INSTRUCTION is not a world event a
    # figure perceives; what Regie executed is its own witnessed action Fact.
    world_kinds = {"god", "scene", "narrator"}
    facts_by_id = {f.get("id"): f for f in (session.get("facts") or []) if isinstance(f, dict) and f.get("id")}
    allowed: set[str] = set()
    for w in wk:
        fid = w.get("fact_id")
        access = w.get("access") or ""
        fact = facts_by_id.get(fid) or {}
        kind = str(fact.get("kind") or fact.get("event_kind") or "")
        if access in knowing or (access == "present" and kind in world_kinds):
            if fid:
                allowed.add(fid)
    facts = [
        copy.deepcopy(f)
        for f in (session.get("facts") or [])
        if (f.get("id") in allowed or f.get("actorId") == character_id or f.get("actor_id") == character_id)
        and str(f.get("kind") or "") != "regie"
    ]
    memories = [copy.deepcopy(m) for m in (session.get("memories") or []) if m.get("characterId") == character_id]
    open_texts = [
        str(p.get("text") or "")
        for p in (session.get("propositions") or [])
        if isinstance(p, dict) and p.get("status") in ("open", "active", "accepted") and p.get("text")
    ]
    facts = sorted(
        facts,
        key=lambda f: _relevance_score(f, cue, lifecycle_boost=True, open_texts=open_texts),
        reverse=True,
    )
    memories = sorted(memories, key=lambda m: _relevance_score(m, cue, open_texts=open_texts), reverse=True)
    episodic_mode = episodic_cue(cue)
    if episodic_mode:
        chron = _episodic_memories(memories, episodic_mode, int(session.get("turnIndex") or 0))
        seen_ids = {id(m) for m in chron}
        memories = chron + [m for m in memories if id(m) not in seen_ids]
    props = sorted(
        [
            copy.deepcopy(p)
            for p in (session.get("propositions") or [])
            if character_id in (p.get("actors") or [])
            or p.get("actorId") == character_id
            or p.get("targetId") == character_id
        ],
        key=lambda p: _relevance_score(p, cue, lifecycle_boost=True, open_texts=open_texts),
        reverse=True,
    )
    relations = [copy.deepcopy(r) for r in (session.get("relations") or []) if r.get("fromId") == character_id]
    goals = [
        copy.deepcopy(g)
        for g in reduce_goal_state(session)
        if g.get("ownerId") == character_id or g.get("recipientId") == character_id
    ]
    runtime = copy.deepcopy((session.get("runtimes") or {}).get(character_id) or {})
    god_facts = []
    fact_ids = {f["id"] for f in facts}
    for gf in session.get("godFacts") or []:
        src = gf.get("sourceTurnId")
        if any(f.get("sourceTurnId") == src or f.get("source_turn_id") == src for f in facts) or any(
            f.get("kind") == "god" and f.get("id") in fact_ids for f in facts
        ):
            god_facts.append(copy.deepcopy(gf))
    frames = []
    for p in props:
        frames.append(
            {
                "who": p.get("actorId"),
                "whom": p.get("targetId"),
                "what": p.get("text"),
                "when": p.get("time_window"),
            }
        )
    return {
        "character_id": character_id,
        "memories": memories,
        "facts": facts,
        "witnessKnowledge": wk,
        "relations": relations,
        "propositions": props,
        "goals": goals,
        "runtime": runtime,
        "time": copy.deepcopy(session.get("time") or bind_time(session)),
        "godFacts": god_facts,
        "frames": frames,
        "currentState": reduce_current_state(session),
        "episodic": episodic_mode,
    }


_COMPASS_TRIGGERS: dict[str, tuple[str, ...]] = {
    # B.26: Backend ist Source of Truth. Frontend (src/lib/matrix/compass.ts)
    # liest diese Liste via /api/compass/triggers, damit es keine Drift gibt.
    "Bedrohung": ("bedroh", "gefahr", "angriff", "konfront", "kontroll", "ueberfall", "waffe", "mess", "schlag", "packt", "zieht"),
    "Angst": ("angst", "fuercht", "furcht", "panik", "scheu", "schreck", "unsicher", "sorge", "schmerz"),
    "Verrat": ("verrat", "verriet", "luege", "lüge", "belog", "belüg", "belueg", "betrug", "betrog", "hintergeh", "hinterging", "hintergang", "untreu", "misstrau", "geheim", "täusch", "taeusch"),
    "Lust": ("lust", "begehr", "verlangen", "anziehung", "intim", "kuss", "nah", "berühr", "beruehr", "schatz", "liebling"),
    "Geld": ("geld", "zahl", "kasse", "bezahl", "schuld", "lohn", "preis", "schnaps"),
    "Trennung": ("trennung", "verlass", "verlass mich", "ende", "allein", "allein gelassen", "geh weg"),
    "Gewalt": ("gewalt", "schlag", "kampf", "wunde", "faust", "zwang", "droh", "haaren", "packt", "fessel"),
    "Mord": ("mord", "tot", "toet", "töt", "leiche", "umbring", "gestorben"),
    "Eifersucht": ("eifersucht", "neid", "rival", "andere", "besitz"),
    "Verlust": ("verlust", "verloren", "trauer", "vermiss", "weggenommen"),
    "Abhaengigkeit": ("abhaeng", "abhäng", "job", "arbeit", "dach", "lohn", "rauswerfen"),
    "Moral": ("recht", "unrecht", "gewissen", "anstand", "anständig", "ehre", "sollte nicht"),
    "Risiko": ("risik", "wagn", "chance", "was wenn", "stehlen", "kasse"),
    "Schutz": ("schuetz", "schutz", "verteidig", "sicher", "bewahr", "haus"),
    "Macht": ("macht", "kontrolle", "befehl", "herrsch", "autoritaet", "anweisung", "regel"),
}


# B.12 (AMASTERv2 §15): Trigger-Klassen → Compass-MeaningSpace-Mapping.
# Wenn das Persona-Compass für einen Space feuert, wird dessen reaction/drive
# als Emotion-Wahl genutzt. Sonst: AMASTER-Default.
_TRIGGER_TO_SPACES: dict[str, tuple[str, ...]] = {
    "resign": ("Trennung", "Verlust"),
    "threat": ("Bedrohung", "Angst", "Gewalt"),
    "request": ("Macht", "Schutz"),
}

# Wenn kein Compass feuert, fallen wir auf diese Defaults zurück. Das ist
# akzeptabel für Avatare (kein Persona-Compass) und als Sicherheitsnetz
# gegen Lücken in Stämmen mit unvollständigem Compass.
_TRIGGER_FALLBACK_EMOTION: dict[str, str] = {
    "resign": "Sorge",
    "threat": "Angst",
    "request": "Verpflichtung",
}


def _emotion_for_trigger(
    speaker: dict | None,
    trigger: str,
    stimulus: str,
) -> str:
    """B.12: Compass-Drive-basierte Emotion-Wahl.

    Wenn speaker.compass für einen der _TRIGGER_TO_SPACES[trigger] feuert,
    wird die cell.drive oder cell.reaction als Emotion-Label verwendet.
    Andernfalls fällt auf _TRIGGER_FALLBACK_EMOTION[trigger] zurück.
    """
    spaces = _TRIGGER_TO_SPACES.get(trigger, ())
    if speaker and spaces:
        fired = fire_compass_lens(speaker, stimulus)
        for f in fired:
            if f.get("space") in spaces and isinstance(f.get("cell"), dict):
                # Compass-Drive (kurz, menschenlesbar) hat Vorrang vor reaction.
                drive = (f.get("cell", {}).get("drive") or "").strip()
                reaction = (f.get("cell", {}).get("reaction") or "").strip()
                # Wenn weder drive noch reaction etwas Substantielles hat, skip.
                chosen = drive or reaction
                if chosen:
                    # Kürze auf max 60 Zeichen fürs Emotion-Label.
                    return chosen[:60]
    return _TRIGGER_FALLBACK_EMOTION.get(trigger, "wach")


def _norm_cue(text: str) -> str:
    return (
        (text or "")
        .lower()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def fire_compass_lens(
    speaker: dict,
    stimulus: str,
    *,
    runtime: dict | None = None,
    scene: dict | None = None,
    relation: dict | None = None,
    fate_tags: list[str] | None = None,
) -> list[dict]:
    """B.26: Compasses als Verhaltens-Lens nach TurnTruth. Niemals als Owner persistiert.

    Backend ist Source of Truth. Frontend spiegelt diese Funktion in
    src/lib/matrix/compass.ts::fireSynapses, liest die Trigger-Liste
    aber via /api/compass/triggers (kein Drift).

    Activation-Formel (deterministisch, dokumentiert):
        base = 0.28 + hits * 0.22        (lexical hit density)
        + abs(cell.stance) * 0.12         (Persona-Disposition)
        + 0.18 falls fate_tags enthält space
        + scene/runtime/relation-Boni (siehe unten)
        cap 1.0

    Space-spezifische Boni:
        Angst          : + runtime.fear    * 0.25
        Lust           : + runtime.lust    * 0.20
        Gewalt/Bedrohung: + scene.danger   * 0.30
                        + runtime.pain    * 0.20
        Macht/Schutz   : + scene.tension   * 0.15
        Abhaengigkeit  : + runtime.pain    * 0.12

    Relations-Boni:
        Lust/closeness > 0.45 : + closeness * 0.22
        Angst/fear           : + fear * 0.22
        Schutz/closeness > 0.4: + 0.14
        Eifersucht/closeness > 0.4: + 0.10
        Verrat/trust < 0.3   : + 0.14
        Gewalt/hostility > 0.35: + 0.16
    """
    compass = speaker.get("compass") if isinstance(speaker, dict) else None
    if not isinstance(compass, dict):
        return []
    blob = _norm_cue(stimulus)
    rt = runtime if isinstance(runtime, dict) else {}
    sc = scene if isinstance(scene, dict) else {}
    rel = relation if isinstance(relation, dict) else {}
    fate = set(fate_tags or [])
    fired: list[dict] = []
    for space, cell in compass.items():
        if not isinstance(cell, dict):
            continue
        words = _COMPASS_TRIGGERS.get(str(space), ())
        # B.26: Substring-Match (1:1 mit Frontend-Fallback, das auf
        # `in n`-Äquivalent läuft). Wir akzeptieren auch "unbedroht" als
        # Treffer — Verneinungs-Erkennung ist Aufgabe des Persona-Compass.
        hits = sum(1 for w in words if w and w in blob)
        if not hits and _norm_cue(str(space)) not in blob:
            continue
        # Lexical base
        a = 0.28 + hits * 0.22
        # Persona stance
        a += abs(float(cell.get("stance") or 0)) * 0.12
        # Fate tags
        if space in fate:
            a += 0.18
        # Runtime/Scene-Boni
        if space == "Angst":
            a += float(rt.get("fear") or 0) * 0.25
        elif space == "Lust":
            a += float(rt.get("lust") or 0) * 0.20
        elif space in ("Gewalt", "Bedrohung"):
            a += float(sc.get("danger") or 0) * 0.30
            a += float(rt.get("pain") or 0) * 0.20
        elif space in ("Macht", "Schutz"):
            a += float(sc.get("tension") or 0) * 0.15
        elif space == "Abhaengigkeit":
            a += float(rt.get("pain") or 0) * 0.12
        # Relations-Boni
        if rel:
            if space == "Lust" and float(rel.get("closeness") or 0) > 0.45:
                a += float(rel.get("closeness") or 0) * 0.22
            if space == "Angst":
                a += float(rel.get("fear") or 0) * 0.22
            if space == "Schutz" and float(rel.get("closeness") or 0) > 0.4:
                a += 0.14
            if space == "Eifersucht" and float(rel.get("closeness") or 0) > 0.4:
                a += 0.10
            if space == "Verrat" and float(rel.get("trust") or 0) < 0.3:
                a += 0.14
            if space == "Gewalt" and float(rel.get("hostility") or 0) > 0.35:
                a += 0.16
            if space == "Abhaengigkeit":
                rel_blob = f"{rel.get('kind') or ''} {rel.get('note') or ''}"
                if re.search(r"dienst|druck|besitz", rel_blob, re.I):
                    a += 0.12
        a = max(0.0, min(1.0, a))
        try:
            _thr = float(cell.get("threshold") if cell.get("threshold") is not None else 0.42)
        except (TypeError, ValueError):
            _thr = 0.42
        fired.append(
            {
                "space": space,
                "activation": round(a, 4),
                "threshold": _thr,
                "source": "lexikalisch",
                "cell": {
                    "reaction": cell.get("reaction") or "",
                    "bodyCue": cell.get("bodyCue") or "",
                    "drive": cell.get("drive") or "",
                    "speech": cell.get("speech"),
                },
            }
        )
    fired.sort(key=lambda row: -float(row.get("activation") or 0))
    return fired[:6]


def latest_foreign_line(session: dict, speaker_id: str | None) -> dict | None:
    """V62 (AMASTER §41.1, §39): the latest validated speech/action Fact of
    ANOTHER actor after the speaker's own last line that she PERCEIVED
    (WitnessKnowledge heard/seen/affected) — the immediate stimulus of a
    reaction turn without own input (puppet line, AutoChat). None if she spoke last."""
    sid = str(speaker_id or "")
    seen = _perceived_fact_ids(session, sid)
    for f in reversed(session.get("facts") or []):
        if not isinstance(f, dict) or f.get("kind") not in ("speech", "action") or not f.get("actorId"):
            continue
        if str(f.get("actorId")) == sid:
            return None
        if _scene.validiert(f) and str(f.get("id") or "") in seen:
            return f
    return None


def _perceived_fact_ids(session: dict, speaker_id: str) -> set[str]:
    """Fact ids the figure perceived (WitnessKnowledge heard/seen/affected, §39)."""
    return {str(w.get("fact_id") or w.get("factId") or "") for w in session.get("witnessKnowledge") or []
            if isinstance(w, dict) and str(w.get("character_id") or w.get("characterId") or "") == str(speaker_id or "")
            and w.get("access") in ("heard", "seen", "affected")}


def foreign_stimulus_facts(session: dict, speaker_id: str | None, last: dict | None = None) -> list[dict]:
    """V65E (AMASTER §41.1 Immediate Stimulus, §34.1 Z. 1817 "Der zuständige
    Reader muss alle zum Quellturn gehörenden validierten Komponenten erreichen
    können", §28 Schritt 20, §27.8): the immediate stimulus of a reaction turn
    without own input is the SOURCE TURN of the latest perceived foreign line —
    all its validated speech/action components by the same actor that the
    speaker perceived (a Regie act, a puppet line, an AutoChat reply). Before,
    the reaction turn mirrored its own empty AutoChat truth (text "", actor =
    avatar): after "Johann schlägt Mara" Mara's stimulus was empty."""
    last = last if last is not None else latest_foreign_line(session, speaker_id)
    if not last:
        return []
    src = str(last.get("sourceTurnId") or last.get("source_turn_id") or "")
    actor = str(last.get("actorId") or "")
    seen = _perceived_fact_ids(session, str(speaker_id or ""))
    return [f for f in (session.get("facts") or []) if isinstance(f, dict) and src
            and f.get("kind") in ("speech", "action") and str(f.get("actorId") or "") == actor
            and str(f.get("sourceTurnId") or f.get("source_turn_id") or "") == src
            and _scene.validiert(f) and str(f.get("id") or "") in seen]


def _session_now(session: dict) -> datetime | None:
    """Bezugszeit für Zeitangaben: das gebundene Sessiondatum (V62, §37)."""
    return session_clock(session)


def _last_foreign_line(speaker: dict, speaker_id: str, dialogue: list[dict]) -> str:
    """Reaktionsturn ohne neue Nutzerrede: die Äußerung ist die letzte Dialogzeile einer anderen Figur."""
    own = str((speaker or {}).get("name") or speaker_id)
    for row in reversed(list(dialogue or [])):
        if str(row.get("name") or "") and str(row.get("name")) != own and str(row.get("speech") or "").strip():
            return str(row.get("speech")).strip()
    return ""


def _utterer_name(session: dict, truth: dict, speaker: dict, present: list[dict], dialogue: list[dict]) -> str:
    """V36 (AMASTERv2 §27/§41): Wer hat die aktuelle Äußerung gesagt? Avatar/Bedienperson,
    eine gesteuerte Figur (Puppet) oder — bei Reaktionsturns ohne neue Nutzerrede — der
    Sprecher der letzten Dialogzeile. Der Prompt nennt den Äußerer ausdrücklich."""
    kind = str(truth.get("input_kind") or truth.get("inputKind") or "").lower()
    actor = str(truth.get("input_actor_id") or truth.get("inputActorId") or "")
    speaker_id = str((speaker or {}).get("id") or "")
    if kind == "autochat" or not str(truth.get("text") or "").strip():
        avatar_name = _name_of(str(session.get("avatarId") or ""), present, session) if session.get("avatarId") else ""
        for row in reversed(list(dialogue or [])):
            nm = str(row.get("name") or "")
            if nm and nm != str((speaker or {}).get("name") or speaker_id):
                # V59C (AMASTER §27.3): the avatar stays marked as avatar.
                return f"{nm} (Avatar)" if avatar_name and nm == avatar_name else nm
        return ""
    if actor in ("user", "operator", ""):
        # V65F (§8, §27.2): the alias must not erase the Bedienperson marker.
        return operator_label(session, truth, present)
    if actor == "observer":
        return "Beobachter (außerhalb der Welt)"
    if actor == str(session.get("avatarId") or ""):
        nm = _name_of(actor, present, session)
        return f"{nm} (Avatar)" if nm and nm != actor else f"{avatar_identity_name(session, present) or 'Spieler'} (Avatar)"
    nm = _name_of(actor, present, session)
    return nm if nm != actor else str(truth.get("user_name") or actor)


def _name_of(fid: str | None, present: list[dict], session: dict) -> str:
    if not fid:
        return ""
    if str(fid) in _OPERATOR_IDS:
        # V65F (§8, §27.2, §23): the Bedienperson has one name in every reader
        # (before: a follow-up after his line named him by the bare alias).
        return operator_label(session, None, present)
    for row in present or []:
        if str(row.get("id") or "") == str(fid):
            return str(row.get("name") or fid)
    # Fallback aus dem Sessionverlauf (Turns tragen speakerName)
    for t in reversed(list((session or {}).get("turns") or [])):
        if isinstance(t, dict) and str(t.get("speakerId") or "") == str(fid) and t.get("speakerName"):
            return str(t["speakerName"])
    for r in (session or {}).get("relations") or []:
        if isinstance(r, dict):
            if str(r.get("fromId") or "") == str(fid) and r.get("fromName"):
                return str(r["fromName"])
            if str(r.get("toId") or "") == str(fid) and r.get("toName"):
                return str(r["toName"])
    return str(fid)


def _dialogue_visible_to(session: dict, speaker_id: str | None, turns: list, avatar_name: str | None = None,
                         operator_name: str | None = None) -> list[dict]:
    """AMASTER §41: Spiegel dialogue is witnessed speech, not the last 10 turns.
    V63 (§24.1, §68 Nr. 51): the avatar's lines carry the avatar's identity
    name (avatar_identity_name) — also for lines stored earlier under the
    control label (alias)."""
    out: list[dict] = []
    if not speaker_id:
        return out
    _av = str(session.get("avatarId") or "")
    def _nm(t: dict):
        if avatar_name and _av and str(t.get("speakerId") or t.get("speaker_id") or "") == _av:
            return avatar_name
        if operator_name and str(t.get("speakerId") or t.get("speaker_id") or "") in _OPERATOR_IDS:
            return operator_name   # V65F (§8, §27.2): Bedienperson, no figure
        return t.get("speakerName") or t.get("speakerId")
    facts = [f for f in (session.get("facts") or []) if isinstance(f, dict)]
    # V65Q: names for an outcome phrase, from the speakers of the turns (no extra source).
    _row_names = [{"id": str(t.get("speakerId") or t.get("speaker_id") or ""), "name": _nm(t)}
                  for t in (turns or []) if isinstance(t, dict) and (t.get("speakerId") or t.get("speaker_id"))]

    def _row(t: dict, sid: Any) -> dict:
        # V65P (AMASTER §43.1 "Handlungstext allein beweist noch keinen
        # erfolgreichen Vollzug"): a committed attempt of this turn that stayed
        # without effect carries its outcome (from the Fact); else unchanged.
        d = {"name": _nm(t), "speech": t.get("speech") or "", "action": t.get("action"), "turn": t.get("turn")}
        if t.get("speech") and str(sid or "") == str(speaker_id or ""):
            # V65R/V65T (AMASTER §34.1, §36.3): her OWN words that denied what she experienced, saw or did carry that
            # state in her own view (only hers - the hearers heard a claim).
            for f in facts:
                ge = f.get("gegenErleben") if f.get("kind") == "speech" and f.get("turn") == t.get("turn") and str(f.get("actorId") or "") == str(sid or "") else None
                if isinstance(ge, dict) and ge.get("factIds"):
                    _ts = [str(g.get("turn")) for g in facts if str(g.get("id")) in set(ge["factIds"])]
                    d["speechNote"] = "gegen dein eigenes Erleben: Turn " + ", ".join(_ts)
                    break
        if t.get("action"):
            # V65Q (AMASTER §43.1, §34.1 Z. 1817; Pruefung v2.8 P-03/P-04): every
            # canonical outcome of this act - blocked, attempted, overcome later.
            for f in facts:
                if (f.get("kind") == "action" and f.get("turn") == t.get("turn")
                        and str(f.get("actorId") or "") == str(sid or "")):
                    txt = act_outcome_text(session, f, _row_names, own=str(sid or "") == str(speaker_id or ""))
                    # V65R (AMASTER §36.5): an act against a declined consent says so with the act.
                    ctx = act_consent_text(session, f, _row_names, viewer=speaker_id)
                    if txt or ctx:
                        d["actionOutcome"] = "; ".join(x for x in (txt, ctx) if x)
                        break
        return d

    for t in (turns or [])[-10:]:
        if not isinstance(t, dict):
            continue
        if t.get("role") not in ("character", "avatar", "observer", "teilnehmer"):
            continue
        sid = t.get("speakerId") or t.get("speaker_id")
        if sid == speaker_id:
            out.append(_row(t, sid))
            continue
        turn = t.get("turn")
        heard = False
        for f in facts:
            if f.get("kind") not in ("speech", "action"):
                continue
            if turn is not None and f.get("turn") != turn:
                continue
            if f.get("actorId") not in (sid, None) and sid:
                if f.get("actorId") != sid:
                    continue
            if speaker_id in (f.get("witnessedBy") or []):
                heard = True
                break
        if heard:
            out.append(_row(t, sid))
    return out


def _arbitrate_goal_foreground(session: dict, speaker_id: str, truth: dict,
                               profile: dict, runtime: dict, goals: list[dict]) -> dict:
    """AMASTER 41/49, read-only: select situational goals, never change ownership.

    Unselected goal IDs remain in the same SQL/session Goal owner; this is a
    transient projection, not a second Goal store or an instruction to act.
    Names/addresses alone do not make a long-term goal current. In particular,
    a fresh greeting is not evidence that all relationship goals are active.
    """
    stimulus = str(truth.get("text") or "")
    current_turn_id = str(truth.get("id") or "")
    # General language terms only, never character names or scenario-specific
    # triggers. An existing direct entity binding overrides lexical matching.
    def terms(value: str) -> set[str]:
        common = {"ich", "dich", "mich", "dein", "deine", "deinen", "mein",
                  "meine", "meinen", "dass", "wenn", "dann", "doch", "aber",
                  "auch", "noch", "euch", "euer", "eine", "einer", "einem",
                  "einen", "sich", "sein", "seine", "seinen", "haben", "wird",
                  "werden", "nicht", "jetzt", "heute", "morgen", "schon",
                  "will", "möchte", "kann", "soll", "wirklich", "gerade",
                  "bitte", "hallo", "guten", "geht", "hier"}
        return {w for w in re.findall(r"[a-zäöüß]{4,}", str(value or "").casefold())
                if w not in common and w not in _CUE_STOP}
    # Exclude the participant names so mentioning a person cannot drag every
    # goal about that person into the immediate foreground.
    names = {w for c in (profile, ) if isinstance(c, dict)
             for w in terms(str(c.get("name") or ""))}
    names |= terms(str(session.get("alias") or ""))
    for c in session.get("characters") or []:
        if isinstance(c, dict):
            names |= terms(str(c.get("name") or ""))
    for row in (session.get("turns") or [])[-8:]:
        if isinstance(row, dict):
            names |= terms(str(row.get("speakerName") or ""))
    cue = terms(stimulus) - names
    # Explicit attention/engagement comes from existing Runtime/Current-State,
    # not from arbitrary proximity of stored goals.
    focus = runtime.get("attentional_focus") or runtime.get("attentionalFocus")
    preoccupation = runtime.get("preoccupation")
    engagement = runtime.get("engagementState") or runtime.get("engagement_state") or {}
    focused = {str(v) for v in (focus, preoccupation) if isinstance(v, str) and v}
    for item in (focus, preoccupation):
        if isinstance(item, dict):
            focused.update(str(item.get(k)) for k in ("topic_ref", "goalId", "goal_id", "ref") if item.get(k))
    deferred = set()
    if isinstance(engagement, dict):
        entries = engagement.get("topics") if isinstance(engagement.get("topics"), list) else [engagement]
    elif isinstance(engagement, list):
        entries = engagement
    else:
        entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ref = str(entry.get("topic_ref") or entry.get("goalId") or entry.get("goal_id") or "")
        status = str(entry.get("status") or entry.get("state") or "").lower()
        if ref and status in ("deferred", "disengaged", "withdrawn"):
            deferred.add(ref)
        elif ref and status == "engaged":
            focused.add(ref)
    # Use the actual current input's committed Fact graph, not historical
    # recollection of a long-term goal from an earlier turn.
    direct_goals = set()
    current_fact_ids = set()
    for fact in session.get("facts") or []:
        if not isinstance(fact, dict) or str(fact.get("sourceTurnId") or fact.get("source_turn_id") or "") != current_turn_id:
            continue
        if _scene.validiert(fact) and fact.get("id"):
            current_fact_ids.add(str(fact.get("id")))
        gid = fact.get("goal_id") or fact.get("goalId")
        if gid and _scene.validiert(fact):
            direct_goals.add(str(gid))
    # V65D (AMASTER §41 Constraint Context "Current State von unmittelbar
    # betroffenen … Goals", §41.3, §35): the kernel's own validated binding of
    # THIS input to one of her goals (_bind_act_to_goal -> apply_goal_experience)
    # is kept on the goal. When the same input also opens a request, the Fact's
    # goal_id is re-pointed to the request goal, so the binding to her goal was
    # lost here. Measured 28.10. (Gasthaus wie 171): "Hast du schon mal
    # nachgedacht, ob wir ein Kind bekommen sollten?" was bound by the planner
    # to Mara's goal "… im 3ten Monat schwanger von Alrik …", yet in 0 of 26
    # replies any goal reached her brief (171 shows all goals every turn).
    for g in goals:
        if isinstance(g, dict) and any(isinstance(e, dict) and str(e.get("sourceFactId") or "") in current_fact_ids
                                       for e in g.get("recentExperiences") or []):
            direct_goals.add(str(g.get("id") or ""))
    ranked = []
    for g in goals:
        if not isinstance(g, dict) or not g.get("text"):
            continue
        gid = str(g.get("id") or "")
        if g.get("status") not in ("open", "active", "accepted"):
            continue
        if gid in deferred and gid not in direct_goals:
            continue
        score = 0
        if gid in direct_goals:
            score += 100
        if gid in focused:
            score += 20
        words = terms(str(g.get("text") or "")) - names
        shared = cue & words
        # One generic word alone is not a causal tie; accept two specific
        # topic terms, or a single term that uniquely represents this goal.
        if len(shared) >= 2:
            score += 12 + len(shared)
        elif len(shared) == 1 and len(words) == 1:
            score += 9
        if score:
            ranked.append((score, gid, g))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    # A bounded reader budget, never a limit on the stored goals. An available
    # attentional capacity can reduce the number of simultaneous topics.
    capacity = runtime.get("attention_capacity", runtime.get("attentionCapacity"))
    try:
        budget = max(1, min(3, round(float(capacity) * 3))) if capacity is not None else 2
    except (TypeError, ValueError):
        budget = 2
    selected = [copy.deepcopy(g) for _, _, g in ranked[:budget]]
    # V65H (AMASTER §41 Constraint Context "Current State von unmittelbar
    # betroffenen Goals", §49.1/§49.3): a goal whose unsaid part THIS input
    # addresses (validated Themenbezug) carries that reading (who, truth,
    # theme); the renderer mirrors it. Selection is unchanged (direct = 100).
    for g in selected:
        _hit = next((e for e in reversed(g.get("recentExperiences") or []) if isinstance(e, dict)
                     and e.get("via") in ("themenbezug", "antwortbezug")
                     and str(e.get("sourceFactId") or "") in current_fact_ids), None)
        if _hit is not None:
            g["touchedNow"] = {k: _hit.get(k) for k in ("actorId", "sourceFactId", "gemeint", "unausgesprochen", "wahrheit", "thema",
                                                       "anlass", "beleg", "turn")}
            if _hit.get("via") == "antwortbezug":
                # V65L: provenance of the continuation (diagnosis; the renderer reads the same keys as for V65H)
                g["touchedNow"].update({k: _hit.get(k) for k in ("via", "antwortAuf", "fortsetzungVon", "art")})
    selected_ids = {str(g.get("id")) for g in selected}
    # Only IDs and lifecycle of unselected goals; their content cannot bias
    # expression and there is no duplicate memory owner.
    reservoir = [{"id": g.get("id"), "status": g.get("status"), "kind": g.get("kind")}
                 for g in goals if isinstance(g, dict) and str(g.get("id")) not in selected_ids]
    return {"goals": selected, "background": reservoir,
            "deferred": sorted(deferred), "stimulus": stimulus}


def _active_reactions(session: dict, speaker_id: str, truth: dict, present: list[dict] | None) -> list[dict]:
    """V65b (AMASTER §15, §41.3, §44, §46.2/§46.6, §49.3): the speaker's own
    authored reaction rules bound (kernel, _bind_profile_triggers) to a
    validated Fact she has not answered yet: Facts of the current input and
    Facts after her last own contribution (speech or action of her own turn
    row; a Regie-ordered act of hers is not her contribution). Read only."""
    sid = str(speaker_id or "")
    own = [int(r.get("turn") or 0) for r in (session.get("turns") or []) if isinstance(r, dict)
           and str(r.get("speakerId") or "") == sid and r.get("role") == "character" and not r.get("byRegie")
           and (str(r.get("speech") or "").strip() or r.get("action"))]
    since = max(own) if own else -1
    cur = str((truth or {}).get("id") or "")
    rows: list[dict] = []
    for f in session.get("facts") or []:
        if not isinstance(f, dict) or not _scene.validiert(f):
            continue
        if str(f.get("sourceTurnId") or "") != cur and int(f.get("turn") or 0) <= since:
            continue
        for t in f.get("profileTriggers") or []:
            if isinstance(t, dict) and str(t.get("ownerId") or "") == sid:
                rows.append({"rule": t.get("rule"), "art": t.get("art"), "text": t.get("text"), "turn": f.get("turn"),
                             "by": _name_of(str(f.get("actorId") or ""), present or [], session) if f.get("actorId") else "",
                             "kind": f.get("kind"), "factText": str(f.get("text") or "")[:160],
                             "propositionRef": t.get("propositionRef")})
    return rows[-4:]


def _current_stimulus_facts(session: dict, truth: dict, speaker_id: str) -> list[dict]:
    """V60b/V62 reader (moved unchanged out of bind_formulation_spiegel by V65S so that the fact and memory
    selection and the open matters read ONE stimulus): the facts of this TurnTruth; in a reaction turn without
    new user input (after a puppet line, AutoChat) also the latest line of ANOTHER figure (AMASTER §41.1)."""
    _cur_src = str(truth.get("id") or "")
    cur = [f for f in (session.get("facts") or []) if isinstance(f, dict)
           and _cur_src and str(f.get("sourceTurnId") or f.get("source_turn_id") or "") == _cur_src]
    if str(truth.get("input_kind") or truth.get("inputKind") or "").lower() == "autochat":
        _last_foreign = latest_foreign_line(session, speaker_id)
        _lf_src = str((_last_foreign or {}).get("sourceTurnId") or (_last_foreign or {}).get("source_turn_id") or "")
        if _lf_src:
            cur += [f for f in (session.get("facts") or []) if isinstance(f, dict)
                    and str(f.get("sourceTurnId") or f.get("source_turn_id") or "") == _lf_src and f not in cur]
    return cur


def stimulus_bound_props(session: dict, truth: dict, speaker_id: str) -> set[str]:
    """V65S (AMASTER §41.1 Immediate Stimulus "eine ausdruecklich adressierte Proposition", §24.2 Effect bindet
    cause/Bezug, §41.3 Foreground Arbitration nach gebundenen Zustaenden; Plan S3): the Propositions the immediate
    stimulus is bound to - the matter its facts are evidence of (propositionId or the matter's evidence), or the matter another actor's
    validated plan refers to (refers_to [prop_...]) - and only those the speaker is a party of. No words. Read only."""
    # only what OTHERS said or did is her stimulus (§41.1); her own line of the same TurnTruth is not
    cur = [f for f in _current_stimulus_facts(session, truth, speaker_id) if str(f.get("actorId") or "") != str(speaker_id or "")]
    ids = {str(f.get("proposition_id") or f.get("propositionId") or "") for f in cur} - {""}
    cur_ids = {str(f.get("id") or "") for f in cur} - {""}
    for p in session.get("propositions") or []:   # the matter whose evidence names a stimulus fact (e.g. a body act)
        if isinstance(p, dict) and any(isinstance(e, dict) and str(e.get("factId") or "") in cur_ids for e in p.get("evidence") or []):
            ids.add(str(p.get("id") or ""))
    for f in cur:
        plan = f.get("plan") if isinstance(f.get("plan"), dict) else {}
        if plan.get("source") == "llm" and str(f.get("actorId") or "") != str(speaker_id):
            ref = str(plan.get("refers_to") or "").strip().strip("[]")
            if ref:
                ids.add(ref)
    me = str(speaker_id or "")
    return {str(p.get("id")) for p in session.get("propositions") or [] if isinstance(p, dict) and str(p.get("id") or "") in ids
            and me in (str(p.get("actorId") or ""), str(p.get("targetId") or ""))}


def stimulus_referents(session: dict, truth: dict, speaker_id: str, figures: list[dict] | None = None) -> set[str]:
    """V65S (AMASTER §24.1/§25, §41.1): the third persons the immediate stimulus is ABOUT - the IDs another actor's
    validated input plan bound (plan.about_ids, kernel.bind_referents) - without the speaker and the stimulus' own
    actors (they are the parties of the exchange, not its subject). For a Regie order to this figure (§46.2, §50
    "angeordneter Inhalt"; Pruefung v3.1 §6 "aus bestaetigten eigenen Tatsachen"): the cast figures its ordered
    segment names, without her and the addressee ("Sage Alrik was du mit Mara gemacht hast" -> Mara). Read only."""
    cur = _current_stimulus_facts(session, truth, speaker_id)
    me = str(speaker_id or "")
    ids: set[str] = set()
    actors = {str(f.get("actorId") or "") for f in cur}
    for f in cur:
        plan = f.get("plan") if isinstance(f.get("plan"), dict) else {}
        if plan.get("source") == "llm" and str(f.get("actorId") or "") != me:
            ids |= {str(x) for x in (plan.get("about_ids") or []) if x}
    _ord = regie_order_for(session, str(truth.get("directive") or ""), me) if str(truth.get("directive") or "").strip() else None
    if isinstance(_ord, dict) and _ord.get("segment"):
        ids |= _named_by_name_part(str(_ord.get("segment") or ""), _session_cast(session, figures)) - {str(_ord.get("targetId") or "")}
    return ids - actors - {me, ""}


def _session_cast(session: dict, figures: list[dict] | None) -> list[dict]:
    """V65S: the figures known in this session with their names - the given (present) figures, then the speakers of
    its turns and the persons of its relations (the same sources _name_of reads), so an absent figure named in an
    order binds too. Read only, existing data only."""
    out, seen = [], set()
    for f in figures or []:
        if isinstance(f, dict) and f.get("id") and str(f["id"]) not in seen:
            seen.add(str(f["id"])); out.append(f)
    rows = [(t.get("speakerId"), t.get("speakerName")) for t in session.get("turns") or [] if isinstance(t, dict)]
    for r in session.get("relations") or []:
        if isinstance(r, dict):
            rows += [(r.get("fromId"), r.get("fromName")), (r.get("toId"), r.get("toName"))]
    for fid, name in rows:
        if fid and name and str(fid) not in seen and str(fid) not in _OPERATOR_IDS and str(fid) != "regie":
            seen.add(str(fid)); out.append({"id": str(fid), "name": str(name)})
    return out


def _referent_fact_ids(session: dict, refs: set[str]) -> set[str]:
    """V65S (§40 Wer/Wem): the facts in which a bound referent is actor or target. Read only."""
    if not refs:
        return set()
    return {str(f.get("id")) for f in session.get("facts") or [] if isinstance(f, dict) and f.get("id")
            and (str(f.get("actorId") or "") in refs or str(f.get("targetId") or "") in refs)}


def _bound_chain_fact_ids(session: dict, pids: set[str]) -> set[str]:
    """V65S: the facts that are evidence of these Propositions (propositionId or the Proposition's evidence). Read only."""
    if not pids:
        return set()
    out = {str(f.get("id")) for f in session.get("facts") or [] if isinstance(f, dict)
           and str(f.get("proposition_id") or f.get("propositionId") or "") in pids}
    for p in session.get("propositions") or []:
        if isinstance(p, dict) and str(p.get("id") or "") in pids:
            out |= {str(e.get("factId")) for e in p.get("evidence") or [] if isinstance(e, dict) and e.get("factId")}
    return out - {"None", ""}


def bind_formulation_spiegel(
    session: dict,
    truth: dict,
    *,
    speaker: dict | None = None,
    present: list[dict] | None = None,
    world: dict | None = None,
    ctx: dict | None = None,
) -> dict:
    """Formulation view of already-bound BrainContext. No owner writes. No secret leak."""
    from matrix_api.learning import canonical_stem
    speaker = canonical_stem(speaker or {})
    present = [canonical_stem(c) for c in (present or [])]
    world = world or {}
    speaker_id = str(truth.get("speaker_id") or speaker.get("id") or "")
    ctx = ctx or (brain_context(session, speaker_id) if speaker_id else {})
    rt_raw = ctx.get("runtime") if isinstance(ctx.get("runtime"), dict) else {}
    rt = {
        "characterId": speaker_id,
        "emotion": rt_raw.get("emotion") or "wach",
        "intensity": float(rt_raw.get("intensity") if rt_raw.get("intensity") is not None else 0.35),
        "fear": float(rt_raw.get("fear") or 0),
        "trust": float(rt_raw.get("trust") if rt_raw.get("trust") is not None else 0.4),
        "lust": float(rt_raw.get("lust") or 0),
        "pain": float(rt_raw.get("pain") or 0),
        "shame": float(rt_raw.get("shame") or 0),
        "anger": float(rt_raw.get("anger") or 0),
        "fatigue": float(rt_raw.get("fatigue") or 0),
        "stress": float(rt_raw.get("stress") or 0),
        "intent": rt_raw.get("intent") or "",
        # V25 UPL-B03: kanonische Ursache der aktuellen Emotion bleibt im Spiegel sichtbar.
        "activeCause": rt_raw.get("activeCause") or None,
        "activeCauseText": rt_raw.get("activeCauseText") or "",
        # V62 (AMASTER §42): direction of the current affect and the other
        # still active directed affects (owner state, mirrored read-only).
        "emotionToward": _person_name(session, present, rt_raw.get("emotionToward")) if rt_raw.get("emotionToward") else "",
        "affects": [{"type": a.get("type"), "toward": _person_name(session, present, a.get("targetId")) if a.get("targetId") else "",
                     "intensity": _affect_now(a, int(session.get("turnIndex") or 0)), "since": a.get("startedTurn")}
                    for a in (rt_raw.get("affects") or []) if isinstance(a, dict)][:4],
        "mobility": float(rt_raw.get("mobility") if rt_raw.get("mobility") is not None else 1),
        "consciousness": float(rt_raw.get("consciousness") if rt_raw.get("consciousness") is not None else 1),
        "position": rt_raw.get("position") or (session.get("scene") or {}).get("placeName") or "",
        "constraints": list(rt_raw.get("constraints") or []),
        "canSpeak": can_speak_now(rt_raw),   # V92 Paket 19: one speech rule (asleep/unconscious speak no words)
        "restrained": bool(rt_raw.get("restrained")),
        "gagged": bool(rt_raw.get("gagged")),
        "heldBy": rt_raw.get("heldBy"),
        "holding": rt_raw.get("holding"),
    }
    cannot = list(rt["constraints"])
    body = speaker.get("body") if isinstance(speaker.get("body"), dict) else {}
    cannot.extend(body.get("constraints") or [])
    if rt["mobility"] < 0.35:
        cannot.append("kann sich nicht frei bewegen")
    # V92 Paket 19 (Pruefung P18 N1/N2, "BrainContext pruefen"): the mirror says what the capability rule does - asleep she can
    # only wake up, unconscious she can do nothing; neither speaks (can_speak_now). Before, a sleeping figure was told
    # "sprechen, sitzen bleiben" while the writer blocked all her acts.
    _asleep = bool(rt_raw.get("schlaeft")) and rt["consciousness"] < 0.5
    if _asleep:
        cannot.append("schläft – sprechen und handeln erst nach dem Aufwachen")
    elif rt["consciousness"] < 0.5:
        cannot.append("ist bewusstlos – kann weder sprechen noch handeln")
    if rt["pain"] > 0.7:
        cannot.append("starke Schmerzen begrenzen jede Handlung")
    if rt["restrained"]:
        cannot.append("ist gefesselt oder festgehalten")
    if not can_speak_now(rt_raw) and rt["consciousness"] >= 0.5:
        cannot.append("kann jetzt nicht sprechen")
    cannot = [c for c in cannot if c]
    can: list[str] = []
    if _asleep:
        can = ["aufwachen"]
    elif rt["consciousness"] < 0.5:
        can = []
    elif rt["gagged"] or not rt["canSpeak"]:
        can = ["schweigen", "mit dem Blick antworten"]
    elif rt["mobility"] >= 0.5 and rt["consciousness"] >= 0.6:
        can = ["sprechen", "gehen", "gestikulieren"]
    else:
        can = ["sprechen", "sitzen bleiben"]
    facts = []
    for fact in ctx.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        facts.append(
            {
                "id": fact.get("id"),
                "actor": _name_of(fact.get("actorId") or fact.get("actor_id"), present, session),
                "actorId": fact.get("actorId") or fact.get("actor_id"),
                "target": _name_of(fact.get("targetId") or fact.get("target_id"), present, session) or None,
                "targetId": fact.get("targetId") or fact.get("target_id"),
                "kind": fact.get("kind") or "",
                "event_kind": fact.get("event_kind") or fact.get("eventKind") or "",
                "text": fact.get("text") or "",
                "turn": int(fact.get("turn") or 0),
                "salience": float(fact.get("salience") or 0),
                "propositionId": fact.get("propositionId") or fact.get("proposition_id"),
                "proposition_id": fact.get("proposition_id") or fact.get("propositionId"),
                "status": fact.get("status"),
                "authority": fact.get("authority"),
                "source_type": fact.get("source_type"),
                "sourceTurnId": fact.get("sourceTurnId") or fact.get("source_turn_id"),
                "speech_act": fact.get("speech_act"),
                "plan": copy.deepcopy(fact.get("plan")),
                "witnessedBy": list(fact.get("witnessedBy") or fact.get("witnessed_by") or []),
            }
        )
    memories = []
    for mem in ctx.get("memories") or []:
        if not isinstance(mem, dict):
            continue
        memories.append(
            {
                "text": mem.get("text") or "",
                "kind": mem.get("kind") or "erlebt",
                "salience": float(mem.get("salience") or 0),
                "truth": mem.get("truthStatus") or mem.get("truth") or "canon",
                "turn": int(mem.get("turn") or 0),
                "factId": mem.get("factId"),
                "source": mem.get("source"),
            }
        )
    # The immediate stimulus is reconstructed from committed, validated facts
    # BEFORE memory selection and compass activation. The raw operator envelope
    # is not a world event and must never be used as proof of a denied act.
    stimulus = truth.get("text") or ""
    # V59C (AMASTER §41.1 Immediate Stimulus, §34.1): mirror the COMMITTED
    # components of the current input, not the raw envelope text.
    _src = str(truth.get("id") or "")
    _in_actor = str(truth.get("input_actor_id") or "")
    _in_facts = [f for f in (session.get("facts") or []) if isinstance(f, dict) and _src
                 and str(f.get("sourceTurnId") or f.get("source_turn_id") or "") == _src
                 and str(f.get("actorId") or "") == _in_actor and f.get("kind") in ("speech", "action")
                 and _scene.validiert(f)]
    # V65E (AMASTER §41.1, §34.1 Z. 1817, §28 Schritt 20, §27.8): a reaction
    # turn (AutoChat after Regie act, puppet line or another figure) has no own
    # input facts; its immediate stimulus is the perceived foreign source turn.
    # A Regie actor turn (directive) keeps its own path (§27.5/§46.6).
    _react = None
    if (not _in_facts and str(truth.get("input_kind") or truth.get("inputKind") or "").lower() == "autochat"
            and not str(truth.get("directive") or "").strip()):
        _react = latest_foreign_line(session, speaker_id)
        if _react is not None:
            _in_facts = foreign_stimulus_facts(session, speaker_id, _react)
            if not _in_facts:
                _react = None
    stimulus_speech = " ".join(str(f.get("text") or "") for f in _in_facts if f.get("kind") == "speech").strip()
    stimulus_action = " ".join(str(f.get("text") or "") for f in _in_facts
                                 if f.get("kind") == "action" and _scene.validiert(f)).strip()
    _fact_stimulus = " ".join(x for x in (stimulus_speech, stimulus_action) if x).strip()
    # Stand 11C (AMASTER §27.4, §34.1; Nutzer 08.11. 22:22/22:37): die Figur hoert die GANZE Aeusserung der anderen Person -
    # woertlich, wie sie gesagt bzw. geschrieben wurde (direkte Eingabe: Avatar, Teilnehmer, Puppet). Was davon als Handlung
    # wirklich geschehen ist, bleibt allein die Liste der validierten Facts (stimulusAction) - der Wortlaut ist kein Beweis einer Tat.
    stimulus_wortlaut = ""
    _src_ids = {str(f.get("sourceTurnId") or f.get("source_turn_id") or "") for f in _in_facts}
    for _tt in reversed(session.get("turnTruths") or []):
        if (isinstance(_tt, dict) and str(_tt.get("id") or "") in _src_ids
                and str(_tt.get("input_kind") or _tt.get("inputKind") or "").lower() in ("speech", "user", "puppet")):
            stimulus_wortlaut = str(_tt.get("wortlaut") or _tt.get("text") or "").strip()
            break
    if stimulus_wortlaut and " ".join(stimulus_wortlaut.split()) == " ".join(_fact_stimulus.split()):
        stimulus_wortlaut = ""   # nichts ausser dem Gespeicherten - keine zweite Zeile
    if _in_facts:
        stimulus = _fact_stimulus
    elif str(truth.get("input_kind") or truth.get("inputKind") or "").lower() == "autochat" and not str(truth.get("directive") or "").strip():
        stimulus = ""   # no canonical incoming event, never the prior raw text
    open_texts = [
        str(p.get("text") or "")
        for p in (ctx.get("propositions") or [])
        if isinstance(p, dict) and p.get("status") in ("open", "active", "accepted") and p.get("text")
    ]
    memories = sorted(
        memories,
        key=lambda m: _relevance_score(m, stimulus, open_texts=open_texts),
        reverse=True,
    )
    episodic_mode = episodic_cue(stimulus)
    if episodic_mode:
        chron = _episodic_memories(memories, episodic_mode, int(session.get("turnIndex") or 0))
        keys = {(m.get("text"), m.get("turn")) for m in chron}
        memories = chron + [m for m in memories if (m.get("text"), m.get("turn")) not in keys]
    # V65S (AMASTER §41.1/§41.3, Plan S3): what the immediate stimulus is bound to (its matter by ID) comes first -
    # the evidence of that matter (the act, her answer, its consequence) before word-relevance. Your session T32:
    # 0 of 7 episode facts and 0 of 3 experienced acts reached Mara's brief, the selection was by shared words.
    _stim_pids = stimulus_bound_props(session, truth, speaker_id)
    _bound_ids = _bound_chain_fact_ids(session, _stim_pids)
    # V65S (AMASTER §24.1/§25 gebundene Referenten, §40 "dieselben Beteiligten", §38 "selbst betroffen", §41.3;
    # Pruefung v3.1 §6 Schritt 2): the third persons the stimulus is about (bound IDs) activate her OWN memories of
    # exactly those persons - first the acts between her and them (action Facts, done to her or by her), then the
    # rest, newest first - before word-relevance. Only her memories (recall decided her access); the rest unchanged.
    _ref_ids = _referent_fact_ids(session, stimulus_referents(session, truth, speaker_id, present))
    if _bound_ids or _ref_ids:
        _fid = lambda m: str(m.get("factId") or "")
        _fk = {str(f.get("id")): f for f in session.get("facts") or [] if isinstance(f, dict) and str(f.get("id") or "") in _ref_ids}
        _act_with_me = lambda m: (_fk.get(_fid(m)) or {}).get("kind") == "action" and speaker_id in (
            str((_fk.get(_fid(m)) or {}).get("actorId") or ""), str((_fk.get(_fid(m)) or {}).get("targetId") or ""))
        _first = [m for m in memories if _fid(m) in _bound_ids]
        _refm = sorted([m for m in memories if _fid(m) in _ref_ids and _fid(m) not in _bound_ids],
                       key=lambda m: (0 if _act_with_me(m) else 1, -int(m.get("turn") or 0)))
        memories = _first + _refm + [m for m in memories if _fid(m) not in _bound_ids and _fid(m) not in _ref_ids]
    # V60: the window cut happens after de-duplication against the dialogue.
    facts = _select_conjunctive_facts(
        facts,
        stimulus=stimulus,
        open_texts=open_texts,
        propositions=list(ctx.get("propositions") or []),
        limit=_SPIEGEL_FACT_LIMIT,
        bound_pids=_stim_pids,
        bound_fact_ids=_bound_ids | _ref_ids,
        answerer_id=str(speaker_id or ""),
    )
    relations_here = []
    present_ids = set((session.get("scene") or {}).get("presentIds") or [])
    for rel in ctx.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        to_id = rel.get("toId") or rel.get("to_id")
        if to_id and present_ids and to_id not in present_ids:
            continue
        relations_here.append(
            {
                "name": _name_of(to_id, present, session),
                "kind": rel.get("kind"),
                "trust": float(rel.get("trust") or 0),
                "closeness": float(rel.get("closeness") or 0),
                "fear": float(rel.get("fear") or 0),
                "hostility": float(rel.get("hostility") or 0),
                "note": rel.get("note") or "",
            }
        )
    turns = session.get("turns") or []
    _av_name = avatar_identity_name(session, present)   # V63: one name owner (§24.1)
    _op_name = operator_label(session, truth, present)   # V65F: one name of the Bedienperson (§8, §27.2)
    dialogue = _dialogue_visible_to(session, speaker_id, turns, _av_name, _op_name)
    # V60 (AMASTER §41.3 "Wiederholung", §41.5, §49): the same evidence is
    # mirrored once. Own and heard words of turns that are already in the
    # visible dialogue are not repeated as memories; experienced/affected
    # memories keep their own meaning (it happened TO the figure).
    _visible_turns = {int(d.get("turn")) for d in dialogue if isinstance(d, dict) and str(d.get("turn") or "").isdigit()}
    # Own words that restated an open matter are represented by that matter
    # (with its restatement count); replaying them would re-amplify it (§41.5).
    _prop_bound = {str(f.get("id")) for f in (session.get("facts") or []) if isinstance(f, dict)
                   and (f.get("proposition_id") or f.get("propositionId")) and str(f.get("actorId") or "") == str(speaker_id)}
    _seen_mem = set()
    _mem_out = []
    for m in memories:
        if m.get("kind") in ("gesagt", "gehoert", "getan", "gesehen") and int(m.get("turn") or 0) in _visible_turns:
            continue
        if m.get("kind") == "gesagt" and str(m.get("factId") or "") in _prop_bound:
            continue
        key = (m.get("factId") or m.get("text"), m.get("kind"))
        if key in _seen_mem:
            continue
        _seen_mem.add(key)
        if m.get("kind") in ("erlebt", "gesehen") and m.get("factId"):
            # V65R (AMASTER §38 "Memory besitzt ... Beteiligte", "direkt betroffen"; Pruefung v2.9 Q-C):
            # what happened TO her is remembered with WHO did it, read from the Fact (the Puppet writer stored
            # Johann's "Ich fasse dir auf den Arsch" without him), and with the consent state of that act.
            _ef = next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict) and str(f.get("id") or "") == str(m.get("factId"))), None)
            if _ef is not None and str(_ef.get("actorId") or "") not in ("", str(speaker_id)):
                _who = _name_of(_ef.get("actorId"), present, session)
                # only the Puppet writer stored the act without its actor (the input writer names the
                # speaker, the Regie writer stores a third-person description with the name)
                if _who and m.get("kind") == "erlebt" and m.get("source") == "commit_puppet" and not str(m.get("text") or "").startswith(_who):
                    m = {**m, "text": f"{_who}: {m.get('text')}"}
                _mc = act_consent_text(session, _ef, present, viewer=speaker_id)
                if _mc:
                    m = {**m, "hinweis": _mc}
        if m.get("kind") == "gesagt" and m.get("factId"):
            # V65R/V65T (§34.1, §36.3): an own statement that denied an own experienced/seen/done event - from the speech Fact.
            _sf = next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict) and str(f.get("id") or "") == str(m.get("factId"))), None)
            _ge = (_sf or {}).get("gegenErleben") if isinstance(_sf, dict) else None
            if isinstance(_ge, dict) and _ge.get("factIds"):
                _acts = [f for f in (session.get("facts") or []) if isinstance(f, dict) and str(f.get("id")) in set(_ge["factIds"])]
                m = {**m, "hinweis": "gegen dein eigenes Erleben: " + ", ".join(f"Turn {f.get('turn')} ({str(f.get('text') or '')[:50]})" for f in _acts[:4])}
        if m.get("kind") == "getan" and m.get("factId"):
            # V65Q (AMASTER §34.1 Z. 1817 "Der Folgeturn muss deren getrennte Wirkungen
            # weitertragen", §38, §42; Pruefung v2.8 P-04): a remembered own act carries
            # its canonical outcome (attempted / blocked / overcome later), also after
            # a place change - read from the Facts, not from the memory text.
            _mf = next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict) and str(f.get("id") or "") == str(m.get("factId"))), None)
            _mo = act_outcome_text(session, _mf, present, own=True) if _mf is not None else None
            if _mo:
                m = {**m, "ausgang": _mo}
        _mem_out.append({k: v for k, v in m.items() if k != "source"})   # V65R: source only read above
    memories = _mem_out[:8]
    # V30 (§41/§49): Der Spiegel trägt zusätzlich den Beginn des Gesprächs und den Umfang,
    # damit Verlaufsfragen ("erste Frage", "davor") aus kanonischem Verlauf beantwortet
    # werden und nicht erfunden werden müssen.
    all_visible = _dialogue_visible_to(session, speaker_id, [t for t in (turns or []) if isinstance(t, dict)][:10], _av_name, _op_name) if len(turns or []) > 10 else []
    # V60 (AMASTER §41.3): the start of the conversation is mirrored only
    # when it is no longer inside the visible dialogue window.
    _first_visible = min(_visible_turns) if _visible_turns else None
    dialogue_summary = {
        "turnsTotal": int(session.get("turnIndex") or 0),
        "linesVisible": len(dialogue),
        # V30's purpose: answer history questions ("erste Frage", "davor").
        "start": ((all_visible or dialogue)[:3] if episodic_mode else []),
        "episodicCue": episodic_mode,
    }
    goals = []
    for g in (ctx.get("goals") or []):
        if not isinstance(g, dict) or not g.get("text") or g.get("status") not in ("open", "active", "accepted"):
            continue
        # V60 (AMASTER §35 Owner, §49.3): the Character Foreground holds the
        # speaker's OWN goals. A request addressed to her is another owner's
        # goal; it is mirrored once as an open matter (OFFENE ANGELEGENHEITEN).
        if g.get("ownerId") and str(g.get("ownerId")) != str(speaker_id):
            continue
        # The goal of an open request IS that Proposition; it is mirrored once
        # with its evidence as an open matter, not again as a goal text.
        if g.get("proposition_id") or g.get("propositionId"):
            continue
        # Background goal state is not a foreground/intent assignment.
        _def = g.get("sourceDefinition") if isinstance(g.get("sourceDefinition"), dict) else {}
        entry = {"id": g.get("id"), "kind": g.get("kind"), "text": g.get("text"),
                 "exit": str(_def.get("exit") or "")[:200] or None,
                 "status": g.get("status"), "priority": g.get("priority"),
                 "lifecycleFactId": g.get("lifecycleFactId"),
                 "recentExperiences": copy.deepcopy(g.get("recentExperiences") or []),
                 # V65H (§35 Current State, §34.1 Offenbarung): her recorded disclosure(s)
                 "disclosedTo": copy.deepcopy(g.get("disclosedTo") or [])}
        goals.append(entry)
    arbitration = _arbitrate_goal_foreground(session, speaker_id, truth, speaker, rt_raw, goals)
    foreground_goals = arbitration["goals"]
    # V65H: names for the renderer (it stays self-contained; no lookups there)
    for _g in foreground_goals:
        if isinstance(_g.get("touchedNow"), dict):
            _g["touchedNow"]["actorName"] = _name_of(str(_g["touchedNow"].get("actorId") or ""), present or [], session)
        for _d in _g.get("disclosedTo") or []:
            if isinstance(_d, dict):
                _d["name"] = _name_of(str(_d.get("targetId") or ""), present or [], session)
    fate = copy.deepcopy(session.get("fate") or {})
    # V60 (AMASTER §38/§39): DU WEISST is stem knowledge. Episodic memories
    # (own speech, heard lines) are memories with their kind, not knowledge.
    knowledge = list(speaker.get("knowledge") or [])[:8]
    # B.9: Stammwissen ist der einzige Reader (AMASTERv2 §9 / §39).
    # Kein Volltext-Nachladen aus world.sourceText/world.long — das war
    # ein zweiter Wissensowner und ist hier ersatzlos entfernt.
    knowledge = [k for k in knowledge if k][:12]
    unknown = [
        "kennt keine fremden Gedanken",
        "kennt nur, was sie selbst erlebt, gehört oder gesehen hat",
    ]
    for limit in list(world.get("knowledgeLimits") or [])[:2] + list(world.get("knowledgeBounds") or [])[:2]:
        if isinstance(limit, str) and not re.search(r"affäre|affare|unterschlag|vorstrafe|geldquelle", limit, re.I):
            unknown.append(limit)
    unknown.append("kennt die Geheimnisse anderer nicht, sofern nicht selbst bezeugt")
    world_rules: list[str] = []
    for rule in (world.get("rules") or [])[:8]:
        if isinstance(rule, str) and rule.strip():
            world_rules.append(rule.strip())
        elif isinstance(rule, dict):
            txt = str(rule.get("text") or rule.get("name") or rule.get("rule") or "").strip()
            if txt:
                world_rules.append(txt)
    stimulus = truth.get("text") or ""
    # V60 (AMASTER §15 Hemmschwelle, §24.6, §68 Nr. 81): the word lens is a
    # candidate source only; a candidate below the figure's own threshold is
    # not mirrored as something that "springs on" in her.
    fired = [r for r in fire_compass_lens(speaker, stimulus)
             if float(r.get("activation") or 0) >= float(r.get("threshold") or 0.42)]
    # V56: BrainContext mirrors committed Runtime; no second preview mutation.
    # _in_facts/_react/stimulus_* were bound before all relevance selection above.
    stimulus_split = bool(stimulus_action)
    # V59C (AMASTER §27.5, §46.6): a Regie action already committed by the
    # Regie writer is mirrored as done; only the still ordered speech remains
    # a directive. No stale earlier utterance is presented as "now".
    directive_raw = str(truth.get("directive") or "").strip()
    directive_eff = directive_raw or None
    directive_done: list[str] = []
    _regie_src = None
    if directive_raw:
        _names = {str(p.get("id")): str(p.get("name") or p.get("id")) for p in (present or []) if isinstance(p, dict)}
        for row in reversed(session.get("turns") or []):
            if not isinstance(row, dict) or row.get("role") != "regie":
                continue
            eff = row.get("regieEffects") if isinstance(row.get("regieEffects"), dict) else None
            if eff and str(row.get("directiveText") or row.get("speech") or "").strip()[:300] == directive_raw[:300]:
                # V65E (AMASTER §27.5, §23): the stimulus of a Regie actor turn
                # is the Regie source turn, not the avatar's empty envelope.
                _regie_src = next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict)
                                   and f.get("kind") == "regie" and f.get("turn") == row.get("turn")), None)
                directive_done = [str(e.get("text") or "") for e in (eff.get("executed") or []) if e.get("validated")]
                own = [x for x in (eff.get("speech") or []) if str(x.get("actorId") or "") == speaker_id]
                if eff.get("executed") or eff.get("speech"):
                    # V65P (AMASTER §46.2/§46.6 "exakt angeordnete Szenenwirkung";
                    # Pruefung v2.7 statt V65M P2): the ordered speech reaches the
                    # figure as the validated LITERAL segment of the Regie text, not
                    # as the reading's "sinngemaess" paraphrase. Measured V65M: "Clara
                    # fragt Alrik, was er mit Mara besprochen hat" became "Sprich zu
                    # Priester Alrik …: Was hast du mit Mara besprochen?" and Clara
                    # answered the question herself 3/3. Rows without a segment
                    # (before V65P) keep the old line.
                    _vz = [v for v in (eff.get("vollzug") or []) if isinstance(v, dict) and str(v.get("informantId") or "") == speaker_id
                           and v.get("ergebnis") in ("vollzogen", "teilweise") and v.get("vollzugFactId")]
                    _vz_txt = "; ".join(str(next((f.get("text") for f in session.get("facts") or [] if isinstance(f, dict)
                                                  and str(f.get("id") or "") == str(v.get("vollzugFactId"))), "") or "") for v in _vz)

                    def _order(x: dict) -> str:
                        seg = str(x.get("segment") or "").strip()
                        to = _names.get(str(x.get('targetId')), str(x.get('targetId'))) if x.get("targetId") else None
                        if seg:
                            # V65T (Entscheidung A): the ordered information is already executed by the Regie writer;
                            # mirrored as done (state), what she says now is her own reaction.
                            return regie_order_line(seg, to) + (f" — Bereits durch die Regie vollzogen ({_vz_txt})." if _vz_txt else "")
                        what = str(x.get("inhalt") or "")
                        return f"Sprich zu {to} in deinen eigenen Worten: {what}" if to else f"Sprich in deinen eigenen Worten: {what}"
                    directive_eff = "; ".join(_order(x) for x in own) or None
            break
    if _in_facts or _react is not None:
        _utterance = stimulus_speech
    elif directive_raw and not str(stimulus).strip():
        _utterance = ""
    else:
        _utterance = None  # legacy reader below
    # V65E: who said/did the stimulus and where it comes from — one origin for
    # userUtterance, utteredBy, stimulusAction and immediateStimulus.
    _stim_origin = {"sourceTurnId": truth.get("id"), "actorId": truth.get("input_actor_id"),
                    "targetId": truth.get("target_id"), "factIds": [str(f.get("id")) for f in _in_facts if f.get("id")]}
    _react_by = ""
    if _regie_src is not None:
        _stim_origin = {"sourceTurnId": _regie_src.get("sourceTurnId") or _regie_src.get("source_turn_id"), "actorId": "regie",
                        "targetId": _regie_src.get("targetId"),
                        "factIds": [str(_regie_src.get("id"))] + [str(f.get("id")) for f in (session.get("facts") or [])
                                    if isinstance(f, dict) and f.get("kind") == "action" and f.get("authority") == "regie"
                                    and f.get("sourceTurnId") == _regie_src.get("sourceTurnId") and f.get("id")]}
    if _react is not None:
        _ra = str(_react.get("actorId") or "")
        _stim_origin = {"sourceTurnId": _react.get("sourceTurnId") or _react.get("source_turn_id"), "actorId": _ra,
                        "targetId": next((f.get("targetId") for f in _in_facts if f.get("targetId")), None),
                        "factIds": [str(f.get("id")) for f in _in_facts if f.get("id")]}
        _rn = _name_of(_ra, present, session)
        if _ra and _ra == str(session.get("avatarId") or ""):
            _react_by = f"{_rn} (Avatar)" if _rn and _rn != _ra else f"{avatar_identity_name(session, present) or 'Spieler'} (Avatar)"
        else:
            _react_by = _rn
    # V65G (171 S41b-1, AMASTER §44/§41): the relationship frame toward the ONE
    # whose line or act is her stimulus (171: puppet speaker, else the avatar).
    _ap_frame = action_permission_frame(session, speaker, str(_stim_origin.get("actorId") or ""), present)
    # V65P: `lastOwnTowardOther` (only reader: the removed 171-Fix4 line) is no
    # longer computed.
    # V60 (AMASTER §35, §36.1, §41.3, §49.3): open matters of the speaker,
    # mirrored ONCE from the Proposition owner with their bound evidence —
    # who asked whom, since when, how often restated, what answered it.
    _nm = {str(p.get("id")): str(p.get("name") or p.get("id")) for p in (present or []) if isinstance(p, dict)}
    if session.get("avatarId"):
        _nm.setdefault(str(session.get("avatarId")), avatar_identity_name(session, present))
    for _oid in _OPERATOR_IDS:
        _nm.setdefault(_oid, _op_name)
    # V60b (AMASTER §7, §41.3, §41.4, §41.5, §49.3/49.4): an open matter is in
    # the Character Foreground only when the CURRENT stimulus touches it (new
    # this turn, answered/referenced by a fact of this turn). Otherwise it stays
    # in the Background Reservoir (ID/status in the read state) — mere recall
    # must not re-serve it every turn.
    _cur_facts = _current_stimulus_facts(session, truth, speaker_id)   # V65S: one stimulus reader
    _cur_ids = {str(f.get("id")) for f in _cur_facts}
    _cur_props = {str(f.get("proposition_id") or f.get("propositionId") or "") for f in _cur_facts} - {""}
    open_matters = []
    for p in (ctx.get("propositions") or []):
        if not isinstance(p, dict) or speaker_id not in (str(p.get("actorId") or ""), str(p.get("targetId") or "")):
            continue
        _touched = (str(p.get("id")) in _cur_props
                    or any(str(e.get("factId") or "") in _cur_ids for e in (p.get("evidence") or []) if isinstance(e, dict)))
        if not _touched:
            continue
        status = str(p.get("status") or "open")
        if p.get("kind") == "koerperkontakt" and status == "open":
            # V65S (AMASTER §36.5 "unknown", §49 "Aufmerksamkeit nicht allein durch Aufnahme in den Prompt verstaerken"):
            # an act opens the body-contact matter with consent unknown; that binds nothing and is not served as a
            # matter (a caress between lovers would otherwise read "Einwilligung: nicht gegeben" at every touch).
            # Her refusal binds through the line it answers; a declined state is the ABLEHNUNG line (Constraint).
            continue
        recent_closed = status not in ("open", "active", "accepted") and int(session.get("turnIndex") or 0) - int(
            next((e.get("turn") for e in reversed(p.get("evidence") or []) if isinstance(e, dict) and e.get("turn") is not None), p.get("turn") or 0) or 0) <= 2
        if status not in ("open", "active", "accepted") and not recent_closed:
            continue
        ev = [e for e in (p.get("evidence") or []) if isinstance(e, dict)]
        open_matters.append({
            "id": p.get("id"), "status": status, "kind": p.get("kind"),
            "byMe": str(p.get("actorId") or "") == speaker_id,
            "other": _nm.get(str(p.get("targetId") if str(p.get("actorId") or "") == speaker_id else p.get("actorId")) or "", ""),
            "matter": str(p.get("matter") or p.get("text") or "")[:200],
            "wording": str(p.get("text") or "")[:200],
            "since": p.get("turn"),
            "restatedTurns": [e.get("turn") for e in ev if e.get("kind") == "restated"],
            "responses": [{"turn": e.get("turn"), "kind": e.get("kind"), "by": _nm.get(str(e.get("by") or ""), ""), "text": e.get("text")}
                          for e in ev if e.get("kind") in ("response_action", "response_speech")][-3:],
        })
    open_matters = open_matters[-6:]
    # V62 (AMASTER §41.2–§41.5, §49.3/§49.4): agreement frames enter the
    # expressive brief like open matters do (V60b) — as Character Foreground
    # only when (a) they bind the figure now (accepted agreement, given
    # promise: Constraint Context), (b) a fact of THIS turn created or changed
    # them, or (c) the current input is about time or an earlier agreement
    # (time question, planner time reading, planner refers_to). Everything else stays in
    # the Background Reservoir (spiegel["frames"], not rendered). Comparison run
    # 27.10.: the unanswered "proposal" frames about a child were rendered in
    # every turn and Mara returned to them in 4 of 13 answers.
    _in_plans = [f.get("plan") for f in _cur_facts if isinstance(f.get("plan"), dict)
                 and str(f.get("actorId") or "") != str(speaker_id)]
    _llm_plans = [p for p in _in_plans if p.get("source") == "llm"]
    def _planner_time(p: dict) -> bool:
        t = p.get("temporal") if isinstance(p.get("temporal"), dict) else {}
        return bool(t.get("source") == "planner" and t.get("label"))
    # temporalQuestion keeps its V61 reader (local text reading of the input,
    # to be replaced by the planner's structured time reading in the time cut)
    # and additionally holds when the planner reads a question with a time.
    # refers_to alone does NOT make a time question: an answer about an open
    # request must never be mirrored as "nothing agreed".
    _temporal_q = bool(_conj.temporal_question(stimulus)) or any(
        p.get("event_kind") == "question" and _planner_time(p) for p in _llm_plans)
    # The cue selects by binding, not by words (§41.3 "relevante Evidenz"):
    # a time in the input brings the dated agreements; a general question
    # about agreements brings all; refers_to brings the referenced one.
    # Live smoke run 27.10.: "Samstag" pulled the undated child proposal in and
    # Mara returned to it ("können wir auch über das Kind reden?").
    _time_cue = (any(_planner_time(p) for p in _llm_plans) if _llm_plans
                 else bool((_conj.parse_temporal(stimulus, _session_now(session)) or {}).get("label")) if stimulus else False)
    _refs = {str(p.get("refers_to") or "").strip().strip("[]") for p in _llm_plans} - {""}
    _ref_facts = {str(f.get("id")) for f in (session.get("facts") or []) if isinstance(f, dict)
                  and _refs and str(f.get("proposition_id") or f.get("propositionId") or "") in _refs}
    _all_frames = [f for f in (session.get("frames") or []) if isinstance(f, dict)]
    _by_frame = {str(f.get("id") or ""): f for f in _all_frames}
    _cur_frame_ids = {str(f.get("id")) for f in _all_frames if {str(x) for x in (f.get("sourceFactIds") or [])} & _cur_ids}

    def _live_conflicts(f: dict) -> list[dict]:
        # §37: a conflict holds while the other side is still open; its live
        # status is read from its owner (read-only, no mutation here).
        out_c = []
        for c in f.get("timeConflicts") or []:
            o = _by_frame.get(str((c or {}).get("id") or ""))
            if o is not None and o.get("status") in ("proposed", "accepted", "committed", "requested"):
                out_c.append({**c, "status": o.get("status"), "what": o.get("what") or c.get("what")})
        return out_c

    def _frame_in_foreground(f: dict) -> bool:
        if f.get("status") in ("accepted", "committed"):
            return True
        if f.get("kind") in ("fakt", "zustand") and f.get("status") == "current":
            return True
        src_ids = {str(x) for x in (f.get("sourceFactIds") or [])}
        if src_ids & _cur_ids:
            return True
        if any(str(c.get("id")) in _cur_frame_ids for c in _live_conflicts(f)):
            return True   # a double booking created/touched by this turn
        if str(f.get("id") or "") in _refs or (src_ids & _ref_facts):
            return True
        if _temporal_q or _time_cue:
            if _time_cue:
                w_ = f.get("when") if isinstance(f.get("when"), dict) else {}
                return bool(w_.get("label") or w_.get("start"))
            return True
        return False
    # V65K (AMASTER §24.1/§24.6; V60.10 "jede Evidenz einmal"): what the speaker heard or said about
    # names and word meanings in this session; a frame made only from those same Facts is not shown twice.
    _lang = session_language(session, for_figure=speaker_id)
    _lang_facts = {str(e.get("factId") or "") for e in _lang}
    frames_foreground = [{**f, "timeConflicts": _live_conflicts(f)} for f in _conj.frames_for(session, speaker_id)
                         if f.get("kind") != "bitte" and _frame_in_foreground(f)
                         and not ({str(x) for x in (f.get("sourceFactIds") or [])} and {str(x) for x in (f.get("sourceFactIds") or [])} <= _lang_facts)]
    # V60b (AMASTER §15 Z. 732–746): the figure's Chathere-Kompass is the
    # behaviour lens over her profile — tone, expression, inhibition threshold,
    # approach, withdrawal, escalation/calming. It is profile data and goes to
    # the formulation as such (it creates no fact, no state, no event).
    compass_lens = []
    # V63 (§15 Z. 732/758): only cells that are her lens; a placeholder compass
    # (never derived or edited) is not mirrored as her behaviour.
    _cp = authored_compass(speaker)
    # V65G (171 S41b-3 Fix3b "Kompass-Raum partner-scopen", AMASTER §41.3 Linsenauswahl
    # ist Reader-Selektion, §15): is intimate closeness NOT carried toward the current
    # counterpart, the intimate rooms of the policy (Naehe/Lust) are no lens for this
    # turn — their name stays, their reaction text is not mirrored.
    # V65P (§36.5, §41.3): keyed to the policy flag for intimate ROOMS
    # (allows_intimate_room) - a reader selection by relationship, not a
    # consent. Same values as before for every type in the policy file.
    _pol = relationship_policy()
    _scope_out = bool(_ap_frame) and not _ap_frame.get("intimateRoomsLens")
    for _space, _cell in _cp.items():
        if not isinstance(_cell, dict):
            continue
        _reaction = str(_cell.get("reaction") or "").strip()
        if not _reaction:
            continue
        if _scope_out and _norm_kind(_cell.get("space") or _space) in (((_pol or {}).get("intimate_rooms")) or {"naehe", "nähe", "lust"}):
            compass_lens.append({"space": str(_cell.get("space") or _space), "reaction": "", "scopedOut": True})
            continue
        # V65P (§15): the reaction is mirrored complete (was cut at 220).
        compass_lens.append({"space": str(_cell.get("space") or _space), "reaction": _reaction,
                             "bodyCue": str(_cell.get("bodyCue") or "").strip()[:100],
                             "drive": str(_cell.get("drive") or "").strip()[:80],
                             "stance": _cell.get("stance"), "threshold": _cell.get("threshold")})
    # V60b (AMASTER §10 Z. 375–410, §66 Z. 3310): the world the figure acts in —
    # name, genre, tone, epoch, description, pre-history — and the current place.
    # It steers formulation (genre/tone/content frame); it is not a list of
    # secrets: world secrets and knowledge limits stay with their owners.
    _w = world if isinstance(world, dict) else {}
    _hist = _w.get("history")
    world_frame = {
        "name": str(_w.get("name") or "")[:80],
        "genre": str(_w.get("genre") or "")[:80],
        "tone": str(_w.get("tone") or "")[:80],
        "epoch": str(_w.get("epoch") or "")[:60],
        "short": str(_w.get("short") or "")[:200],
        "long": str(_w.get("long") or "")[:900],
        "history": "; ".join(str(x) for x in _hist if str(x).strip())[:600] if isinstance(_hist, list) else str(_hist or "")[:600],
    }
    _sc = session.get("scene") or {}
    _place = next((pl for pl in (_w.get("places") or []) if isinstance(pl, dict) and (
        (_sc.get("placeId") and str(pl.get("id") or "") == str(_sc.get("placeId")))
        or (str(pl.get("name") or "").strip().lower() == str(_sc.get("placeName") or "").strip().lower() and pl.get("name")))), None)
    place_frame = ({"name": str(_place.get("name") or ""), "description": str(_place.get("description") or "")[:400],
                    "rules": [str(r) for r in (_place.get("rules") or []) if str(r).strip()][:4]} if _place else None)
    mode = truth.get("role") or session.get("role") or "teilnehmer"
    fate_on = bool((session.get("pipeline") or {}).get("fate", True)) and bool(
        True if fate.get("enabled") is None else fate.get("enabled")
    )
    # R4.2 / B.34-Folge: Validation-Gate — wenn fate_on und mustNot
    # leer ist, einmalig via Helper initialisieren. Verhindert dass
    # LLM einen leeren mustNot sieht und dann doch erfundenes Wissen
    # produziert (R4.2 Race-Fix).
    if fate_on and not fate.get("mustNot"):
        _ensure_fate_mustNot(fate, world)
    scene_present_ids = list((session.get("scene") or {}).get("presentIds") or [])
    effective_hears, effective_sees = _scene_perception(session, scene_present_ids)
    return {
        "sessionId": session.get("id"),
        "worldId": session.get("worldId"),
        "sourceTurnId": truth.get("id"),
        "speakerId": speaker_id,
        "speakerName": speaker.get("name") or speaker_id,
        "mode": mode,
        "profile": {
            "name": speaker.get("name") or speaker_id,
            "role": speaker.get("role") or "character",
            "speechRegister": speaker.get("speechRegister") or "",
            "typicalPhrases": list(speaker.get("typicalPhrases") or []),
            "taboos": list(speaker.get("taboos") or [])[:6],
            "values": list(speaker.get("values") or [])[:6],
            "reactionRules": list(speaker.get("reactionRules") or []),
            "relevantCanon": list(speaker.get("canon") or [])[:6],
            "ownSecrets": list(speaker.get("secrets") or speaker.get("ownSecrets") or [])[:4],
            "species": speaker.get("species") or "",
            "coreFacts": list(speaker.get("coreFacts") or [])[:6],
            "bindingPatterns": list(speaker.get("bindingPatterns") or [])[:4],
            "lastingAbilities": list(speaker.get("lastingAbilities") or [])[:4],
            "humor": speaker.get("humor") or "",
            "favoriteWords": list(speaker.get("favoriteWords") or [])[:6],
            "fears": list(speaker.get("fears") or [])[:4],
            "likes": list(speaker.get("likes") or [])[:4],
            "dislikes": list(speaker.get("dislikes") or [])[:4],
            # Full definitions remain accessible to editors/readers; the LLM
            # serializer does not include the raw profile or render this list.
            "goals": copy.deepcopy(speaker.get("goals") or []),
            "conflictStyle": speaker.get("conflictStyle") or "",
            "biography": str(speaker.get("biography") or "")[:800],
            "personality": speaker.get("personality") or "",
            "age": speaker.get("age") or "",
            "gender": speaker.get("gender") or "",
            "occupation": speaker.get("occupation") or "",
            "dialect": speaker.get("dialect") or "",
            "appearance": str(speaker.get("appearance") or "")[:240],
            "origin": speaker.get("origin") or "",
        },
        "fired": fired,
        "runtime": rt,
        "body": {
            "position": rt["position"],
            "mobility": rt["mobility"],
            "pain": rt["pain"],
            "consciousness": rt["consciousness"],
            "canDo": can,
            "cannotDo": list(dict.fromkeys(list(cannot) + [str(x) for x in (rt_raw.get("cannotDo") or [])])),
            # V34 §43: Haltung/Verletzungen mit Ursache — bindend bis zu einer neuen Handlung
            "posture": rt_raw.get("posture") or "",
            "injuries": [i for i in (rt_raw.get("injuries") or []) if isinstance(i, dict)][:6],
            "canSpeak": can_speak_now(rt_raw),
            "asleep": bool(rt_raw.get("schlaeft")) and rt["consciousness"] < 0.5,   # V92 Paket 19
            "canSee": rt_raw.get("canSee", True),
            "handsFree": rt_raw.get("handsFree", True),
            "since": rt_raw.get("bodySince"),
            "cause": rt_raw.get("bodyCauseText") or "",
        },
        "scene": {
            "place": (session.get("scene") or {}).get("placeName") or "",
            "time": (session.get("scene") or {}).get("time") or "",
            "notes": (session.get("scene") or {}).get("notes") or "",
            "foreground": list((session.get("scene") or {}).get("foreground") or []),
            "present": [_name_of(i, present, session) for i in (session.get("scene") or {}).get("presentIds") or []],
            "tension": float((session.get("scene") or {}).get("tension") or 0),
            "danger": float((session.get("scene") or {}).get("danger") or 0),
            "open": [m for m in ((session.get("scene") or {}).get("openMatters") or [])
                     if m not in {str(p.get("text") or "") for p in (session.get("propositions") or []) if isinstance(p, dict)}],
            "hears": [_name_of(i, present, session) for i in effective_hears],
            "sees": [_name_of(i, present, session) for i in effective_sees],
            # V65F (AMASTER §23 TurnTruth trennt Bedienperson und anwesende
            # Figuren, §27.2 Teilnehmer außerhalb der Welt nimmt am Dialog teil):
            # the bound participant of this turn when he is no figure — named
            # apart from the present figures (replay 28.10.: Mara answered Clara
            # about the Spieler's Saturday surprise; he was in no scene reader).
            "outsideWorld": [_op_name] if str(truth.get("input_actor_id") or "") in _OPERATOR_IDS else [],
            "items": list((session.get("scene") or {}).get("items") or [])[:6],
            "aftereffects": list((session.get("scene") or {}).get("aftereffects") or [])[-4:],
            "questions": list((session.get("scene") or {}).get("openQuestions") or [])[:4],
            "demands": list((session.get("scene") or {}).get("openDemands") or [])[:4],
            "promises": list((session.get("scene") or {}).get("openPromises") or [])[:4],
        },
        "relationsHere": relations_here,
        # V65G (171 S40b/S41b: Person-Scope, PARTNERBINDUNG-BESTEHT, ACTION-PERMISSION;
        # AMASTER §44, §26/§41, §8/§6, §36.5): the relationship frame toward the
        # current counterpart. Replaces the V65F operator-only line (same truth,
        # now for every counterpart, the Bedienperson included).
        "actionPermission": _ap_frame,
        "memories": memories[:8],
        "facts": facts,
        "dialogue": dialogue,
        "dialogueSummary": dialogue_summary,
        "directive": directive_eff,
        "directiveDone": directive_done,
        "stimulusSpeech": stimulus_speech if stimulus_split else None,
        "stimulusAction": stimulus_action or None,
        "stimulusWortlaut": stimulus_wortlaut[:600] or None,   # Stand 11C
        "turnMode": ("autochat" if str(truth.get("input_kind") or truth.get("inputKind") or "").lower() == "autochat" else "reply"),
        # V65G (AMASTER §26 / §68 Nr. 6 "Anwesenheit, Hören und Sehen bestimmen
        # Wissen", §44 gerichtet pro Person, §41.2): "present" of a Stamm bond is
        # the SCENE presence of that person. Before it was matched against
        # `present` — in prepare that is every figure of the world (app.py:
        # present = natives) — so an absent partner was never marked absent.
        # Session 05:33: Alrik absent, Mara's brief "Priester Alrik: lover —
        # Vertrauen 0.75" without "[nicht anwesend]" while "Spieler" said
        # "Hey schatz".
        "stemRelations": [
            {"name": r.get("targetName"), "kind": r.get("kind"), "trust": float(r.get("trust") or 0), "closeness": float(r.get("closeness") or 0), "fear": float(r.get("fear") or 0), "note": str(r.get("note") or "")[:100],
             "present": any(str(p.get("name") or "").lower() == str(r.get("targetName") or "").lower()
                            and str(p.get("id") or "") in set((session.get("scene") or {}).get("presentIds") or [])
                            for p in (present or []) if isinstance(p, dict))}
            for r in ((speaker or {}).get("relations") or []) if isinstance(r, dict) and r.get("targetName")
        ][:8],
        "sceneState": copy.deepcopy(session.get("sceneState")) if isinstance(session.get("sceneState"), dict) else None,
        "sceneLines": _scene.prompt_lines(session, speaker_id, {str(c.get("id")): str(c.get("name")) for c in _session_cast(session, list(present or [])) if isinstance(c, dict) and c.get("name")} | ({str(session.get("avatarId")): avatar_identity_name(session, present)} if session.get("avatarId") else {}) | {k: _op_name for k in _OPERATOR_IDS}, now=(session_clock(session).isoformat(timespec="minutes") if session_clock(session) else None)),
        "contradictions": (_truth.local_contradictions(session, speaker, utterer_id=str(_stim_origin["actorId"] or ""), plan=next((f.get("plan") for f in _in_facts if f.get("kind") == "speech" and isinstance(f.get("plan"), dict)), None), text=stimulus_speech)
                           if _react is not None else
                           _truth.local_contradictions(session, speaker, utterer_id=str(truth.get("input_actor_id") or ""), plan=next((f.get("plan") for f in ctx.get("facts") or [] if f.get("sourceTurnId") == truth.get("id") and f.get("actorId") == truth.get("input_actor_id")), None), text=stimulus)),
        "conflictedClaims": _truth.claims_for(session, speaker_id),
        "openMatters": open_matters,
        # V61 (AMASTER §15, §41.3, §49.3): the speaker's own authored reaction
        # rules whose condition a validated Fact fulfils (kernel binding, see
        # _bind_profile_triggers). Foreground, not an order.
        # V65b (AMASTER §46.2/§46.6, §44): not only Facts of THIS turn but every
        # bound Fact since her last own contribution — an event she has not
        # reacted to yet, e.g. a Regie-ordered act of the previous turn (§46.6:
        # the Regie turn itself invents no figure reaction).
        "activeReactions": _active_reactions(session, speaker_id, truth, present),
        "compassLens": compass_lens,
        "worldFrame": world_frame,
        "placeFrame": place_frame,
        "frames": _conj.frames_for(session, speaker_id),
        # V65K (AMASTER §24.1 known_as, §24.6 Sessionwortschatz, §26): validated names and word meanings
        # of THIS session the speaker perceived or said - state, not an instruction; never the stem.
        "sprache": [{"art": e.get("art"), "bezeichnung": e.get("bezeichnung"), "person": e.get("personName"),
                     "bedeutung": e.get("bedeutung"), "turn": e.get("turn"),
                     "von": ({str(p.get("id")): str(p.get("name")) for p in (present or []) if isinstance(p, dict)}
                             | ({str(session.get("avatarId")): avatar_identity_name(session, present)} if session.get("avatarId") else {})
                             ).get(str(e.get("actorId") or ""), "")} for e in _lang][-8:],
        # V60 (AMASTER §68 Nr. 24): requests are mirrored from the Proposition
        # owner (openMatters); their frame copy is not rendered a second time.
        "framesText": _conj.render_frames(frames_foreground, {str(p.get("id")): str(p.get("name")) for p in (present or []) if isinstance(p, dict)} | ({str(session.get("avatarId")): avatar_identity_name(session, present)} if session.get("avatarId") else {}) | {k: _op_name for k in _OPERATOR_IDS}, _session_now(session)),
        "temporalQuestion": _temporal_q,
        # The browser contract requires goals: string[]. Detailed committed
        # goal evidence is a separate read-only Spiegel projection.
        "goals": [str(g.get("text") or "") for g in foreground_goals],
        "goalEvidence": [g for g in foreground_goals if g.get("recentExperiences")],
        "propositions": [
            {
                "text": p.get("text"),
                "status": p.get("status"),
                "who": p.get("actorId"),
                "whom": p.get("targetId"),
                "when": p.get("time_window"),
            }
            for p in (ctx.get("propositions") or [])
            if isinstance(p, dict) and p.get("text")
        ][:6],
        "hauptsache": [str(p.get("text")) for p in (ctx.get("propositions") or [])
                       if isinstance(p, dict) and p.get("text") and
                       p.get("status") in ("open", "active", "accepted")],
        "goalState": copy.deepcopy(foreground_goals),
        "immediateStimulus": {"text": (_fact_stimulus if _in_facts else stimulus),
                              "sourceTurnId": _stim_origin["sourceTurnId"],
                              "actorId": _stim_origin["actorId"],
                              "targetId": _stim_origin["targetId"],
                              "factIds": _stim_origin["factIds"],
                              "speech": stimulus_speech or None,
                              "action": stimulus_action or None},
        "constraintContext": {"authority": truth.get("authority"), "mode": mode,
                              "presentIds": list(scene_present_ids),
                              "worldRules": copy.deepcopy(world_rules),
                              "body": {"canSpeak": can_speak_now(rt_raw),
                                       "cannotDo": list(dict.fromkeys(cannot)),
                                       "position": rt["position"],
                                       "consciousness": rt["consciousness"]}},
        "characterForeground": {"goals": copy.deepcopy(foreground_goals),
                                 "attention": copy.deepcopy(rt_raw.get("attentional_focus") or rt_raw.get("attentionalFocus")),
                                 "engagement": copy.deepcopy(rt_raw.get("engagementState") or rt_raw.get("engagement_state")),
                                 "preoccupation": copy.deepcopy(rt_raw.get("preoccupation"))},
        "backgroundReservoir": {"goals": arbitration["background"]},
        "deferredTopics": arbitration["deferred"],
        "witnessKnowledge": copy.deepcopy(ctx.get("witnessKnowledge") or []),
        "godFacts": copy.deepcopy(ctx.get("godFacts") or []),
        "fate": {
            "pressure": float(fate.get("pressure") or 0) if fate_on else 0,
            "beat": (fate.get("beat") or "") if fate_on else "",
            "mustNot": (fate.get("mustNot") or "") if fate_on else "",
        },
        "knowledge": knowledge,
        "unknown": unknown,
        "worldRules": world_rules,
        "userUtterance": _utterance if _utterance is not None else (stimulus or _last_foreign_line(speaker, speaker_id, dialogue)),
        "utteredBy": (_react_by if _react is not None else "" if _regie_src is not None
                      else _utterer_name(session, truth, speaker, present, dialogue)),
        "query": _utterance if _utterance is not None else (stimulus or _last_foreign_line(speaker, speaker_id, dialogue)),
        "lastOwnSpeech": next(
            (
                str(row.get("speech") or "")
                for row in reversed(dialogue)
                if str(row.get("name") or "") == str(speaker.get("name") or speaker_id)
            ),
            "",
        ),
        "addressedTo": _name_of(truth.get("target_id"), present, session) or None,
        "topic": stimulus or None,
        # V62 (AMASTER §37): the bound session date, mirrored (not guessed).
        "today": today_view(session),
        "source": "kernel_prepare",
        "writable": False,
        "currentState": {
            "turn": int(session.get("turnIndex") or 0),
            "placeId": (session.get("scene") or {}).get("placeId"),
            "placeName": (session.get("scene") or {}).get("placeName"),
            "time": copy.deepcopy(session.get("time") or {}),
            "goals": copy.deepcopy(foreground_goals),
            "openPropositions": [copy.deepcopy(p) for p in ctx.get("propositions") or []
                                 if p.get("status") in ("open", "active", "accepted")],
            "closedPropositions": [copy.deepcopy(p) for p in ctx.get("propositions") or []
                                   if p.get("status") not in ("open", "active", "accepted")],
        },
    }


def brain_context(session: dict, character_id: str, cue: str | None = None) -> dict:
    rec = recall(session, character_id, cue=cue)
    ctx = {
        **rec,
        "kind": "brain_context",
        "writable": False,
        "currentState": copy.deepcopy(reduce_current_state(session)),
        "fate": copy.deepcopy(session.get("fate") or {}),
    }
    return ctx


def prepare_turn(
    session: dict,
    *,
    truth: dict,
    speaker: dict | None = None,
    present: list[dict] | None = None,
    world: dict | None = None,
) -> dict:
    """Bind TurnTruth, read-only BrainContext, formulation Spiegel. No owner writes."""
    bound = normalize_truth(dict(truth or {}))
    speaker_id = bound.get("speaker_id") or (speaker or {}).get("id")
    cue = bound.get("text") or ""
    ctx = (
        brain_context(session, str(speaker_id), cue=cue)
        if speaker_id
        else {
            "kind": "brain_context",
            "writable": False,
            "currentState": copy.deepcopy(reduce_current_state(session)),
            "fate": copy.deepcopy(session.get("fate") or {}),
        }
    )
    spiegel = bind_formulation_spiegel(
        session,
        bound,
        speaker=speaker,
        present=present,
        world=world,
        ctx=ctx,
    )
    ctx["spiegel"] = spiegel
    ctx["writable"] = False
    ctx["kind"] = "brain_context"
    return {
        "truth": bound,
        "brainContext": ctx,
        "spiegel": spiegel,
        "fired": spiegel.get("fired") or [],
        "session": session,
        "writable": False,
    }


def autchat_should_stop(
    session: dict,
    natives: list[dict],
    *,
    remaining_turns: int = 1,
    need_user: bool = False,
    mode: str | None = None,
    target_id: str | None = None,
) -> str | None:
    if remaining_turns <= 0:
        return "turn_limit"
    if need_user:
        return "user_decision"
    if (mode or "").upper() == "A" and not target_id:
        return "missing_target"
    scene = session.get("scene") or {}
    present = list(scene.get("presentIds") or [])
    avatar = session.get("avatarId")
    figures = [cid for cid in present if cid and cid != avatar]
    if not figures:
        return "no_speaker"
    speaker = pick_speaker(session, natives, "")
    if speaker is None:
        return "no_speaker"
    rt = (session.get("runtimes") or {}).get(speaker.get("id") or "") or {}
    if float(rt.get("consciousness") or 1) < 0.5 or rt.get("canSpeak") is False:
        return "capability"
    if float(scene.get("danger") or 0) >= 0.95:
        return "danger"
    turns = [t for t in (session.get("turns") or []) if t.get("role") == "character"]
    if len(turns) >= 2:
        a = (turns[-1].get("speech") or "").strip()
        b = (turns[-2].get("speech") or "").strip()
        if a and a == b:
            return "repetition"
    runtimes = session.get("runtimes") or {}
    if figures and all(float((runtimes.get(cid) or {}).get("consciousness") or 1) < 0.5 for cid in figures):
        return "unconscious"
    last = (session.get("turns") or [])[-1] if session.get("turns") else {}
    # V65E (AMASTER §48 Stoppgründe: Userentscheidung, unklarer Avatarvollzug,
    # fehlende Zielbindung, harte Konfliktauflösung, Turnlimit, Fehler; §27.8
    # AutoChat darf "keine God- oder Regiefakten verlieren"; §4 "Folgeturn liest
    # den fortgeschriebenen Zustand"): a COMMITTED God/Regie effect is no stop
    # reason. Before, every God/Regie turn stopped the gate ("god_regie") — the
    # last turn's role, and a Regie action fact never carries "applied" — so the
    # scene could not go on after God at all and after a Regie act only through
    # the forced actor turn. An authority input that was NOT applied still stops.
    facts = list(session.get("facts") or [])
    if facts:
        lf = facts[-1]
        if lf.get("authority") in ("god", "regie") and not _scene.validiert(lf):
            return "god_regie"
        if not _scene.validiert(lf) or lf.get("rejection_reason"):
            return "error"
    if last.get("role") in ("avatar", "teilnehmer", "user") and last.get("needsReply"):
        return "interruption"
    fate = session.get("fate") or {}
    if fate.get("enabled") and float(fate.get("pressure") or 0) >= 0.9 and fate.get("requiresUser"):
        return "fate"
    opens = [p for p in (session.get("propositions") or []) if p.get("status") == "open"]
    if opens and any(p.get("targetId") in (avatar, session.get("userId"), "user") for p in opens):
        if last.get("role") == "character" and (
            "?" in (last.get("speech") or "") or infer_speech_act(last.get("speech") or "") == "ask"
        ):
            return "await_user"
    windows = [str(p.get("time_window") or p.get("text") or "") for p in opens]
    if len(opens) >= 2 and any("samstag" in w.lower() for w in windows) and any("sonntag" in w.lower() for w in windows):
        return "hard_conflict"
    return None


def autchat_step(
    session: dict,
    natives: list[dict],
    *,
    result: dict,
    remaining_turns: int = 1,
    mode: str | None = None,
    target_id: str | None = None,
    need_user: bool = False,
) -> dict:
    stop = autchat_should_stop(
        session,
        natives,
        remaining_turns=remaining_turns,
        need_user=need_user,
        mode=mode,
        target_id=target_id,
    )
    if stop:
        s = copy.deepcopy(session)
        s["autochatStop"] = stop
        return s
    speaker = pick_speaker(session, natives, result.get("speech") or "")
    if speaker is None:
        s = copy.deepcopy(session)
        s["autochatStop"] = "no_speaker"
        return s
    truth = bind_from_session(
        session,
        role="character",
        authority="character",
        speaker_id=speaker["id"],
        target_id=target_id,
        input_kind="autochat",
        text="",
    )
    out = commit_turn(session, truth=truth, speaker=speaker, present=natives, result=result)
    out["autochatStop"] = None
    return out
