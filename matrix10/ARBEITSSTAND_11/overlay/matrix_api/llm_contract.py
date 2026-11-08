"""LLM-Grenze lokal: liest Config, formuliert, schreibt keine Wahrheit."""
from __future__ import annotations

import json
import os
import time
import re
import urllib.error
import urllib.request
from typing import Any

from matrix_api.analyze import STOP, analyze_text
from matrix_api.repos import get_config

XAI_URL = "https://api.x.ai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "grok-4.5"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
MAX_TOKENS_CAP = 1024
_LAST_LLM_ERROR: str | None = None
_LAST_LLM_NOTES: list[str] = []
_LAST_LLM_PROPOSALS: dict[str, Any] = {}
import threading as _threading
_TL = _threading.local()


def _set_err(msg: str | None) -> None:
    global _LAST_LLM_ERROR
    _LAST_LLM_ERROR = msg
    _TL.err = msg


def _last_llm_error() -> str | None:
    return getattr(_TL, "err", _LAST_LLM_ERROR)


# B.16 (AMASTERv2 §67 — API-Keys schützen): User-ProviderConfig.endpoint darf
# NUR gegen die Allowlist aufgelöst werden. Sonst könnte der Client-User
# den ENV-Key an eine fremde URL locken.
def _is_endpoint_allowed(url: str, *, key_source: str = "env") -> bool:
    """Whitelist für Formulate-Endpoint. Server-ENV-Key verlässt nie diese Liste.

    V25 (AMASTERv2 §60, Vertrag §14): Ein vom Nutzer im Frontend gespeicherter
    Key (key_source == "config") darf an den vom Nutzer konfigurierten
    http(s)-Endpoint gehen (custom/lokaler Provider). Die Allowlist schützt nur
    den Server-Umgebungsschlüssel.
    """
    if not url:
        return True  # leerer Endpoint → _route_provider entscheidet aus API-Key-Form
    s = url.strip()
    low = s.lower()
    if low in (XAI_URL.lower(), OPENAI_URL.lower()):
        return True
    if key_source == "config" and low.startswith(("http://", "https://")):
        return True
    # Lokale Endpoints: nur 127.0.0.1, localhost, ::1 mit http(s)
    if low.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]")):
        return True
    if low.startswith(("https://127.0.0.1", "https://localhost", "https://[::1]")):
        return True
    return False


MEANING_SPACES = (
    "Bedrohung",
    "Angst",
    "Verrat",
    "Lust",
    "Geld",
    "Trennung",
    "Gewalt",
    "Mord",
    "Eifersucht",
    "Verlust",
    "Abhaengigkeit",
    "Moral",
    "Risiko",
    "Schutz",
    "Macht",
)


def _first_blob(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for k in ("text", "name", "note", "beat", "mustNot", "speech"):
            t = value.get(k)
            if isinstance(t, str) and t.strip():
                return t.strip()
        return ""
    if isinstance(value, list):
        if not value:
            return ""
        return _first_blob(value[0])
    if isinstance(value, (dict, tuple, set)):
        return ""
    return str(value).strip()


def _context_line(spiegel: dict[str, Any]) -> str:
    """Formulation-only line from BrainContext fields. No owner writes."""
    parts: list[str] = []
    g = _first_blob(spiegel.get("goals"))
    if g:
        parts.append(g)
    rels = spiegel.get("relationsHere") or []
    if isinstance(rels, list) and rels:
        r0 = rels[0] if isinstance(rels[0], dict) else {"name": str(rels[0])}
        name = str(r0.get("name") or "").strip()
        note = str(r0.get("note") or "").strip()
        if name:
            parts.append(f"{name}" + (f": {note}" if note else ""))
        elif note:
            parts.append(note)
    mem = _first_blob(spiegel.get("memories"))
    if mem:
        parts.append(mem)
    rt = spiegel.get("runtime") if isinstance(spiegel.get("runtime"), dict) else {}
    em = str(rt.get("emotion") or "").strip()
    if em and em.lower() not in ("wach", "calm", ""):
        parts.append(em)
    prop0 = _first_blob(spiegel.get("propositions"))
    if prop0:
        parts.append(prop0)
    wr = _first_blob(spiegel.get("worldRules"))
    if wr:
        parts.append(wr)
    dlg = _first_blob(spiegel.get("dialogue"))
    if dlg:
        parts.append(dlg)
    kns = spiegel.get("knowledge") or []
    if isinstance(kns, list):
        parts.extend(str(x).strip()[:240] for x in kns[:4] if str(x).strip())
    else:
        kn = _first_blob(spiegel.get("knowledge"))
        if kn:
            parts.append(kn)
    unk = _first_blob(spiegel.get("unknown"))
    if unk:
        parts.append(unk)
    cs = _first_blob(spiegel.get("currentState"))
    if cs:
        parts.append(cs)
    body = spiegel.get("body") if isinstance(spiegel.get("body"), dict) else {}
    cannot = body.get("cannotDo") or []
    if cannot:
        parts.append(str(cannot[0]))
    return ". ".join(p for p in parts if p)


def _looks_like_dump(speech: str, utterance: str = "") -> bool:
    sp = speech or ""
    if re.search(r"nächste zug folgt|gebundenen original", sp, re.I):
        return True
    if re.match(r"^\s*antwort\s*:", sp, re.I):
        return True
    if sp.count("..") >= 2:
        return True
    u = (utterance or "").strip()
    if u and len(u) > 10 and u.lower() in sp.lower() and sp.count(". ") >= 3:
        return True
    return False


def _clean_speech(speech: str) -> str:
    sp = re.sub(r"^\s*antwort\s*:\s*", "", speech or "", flags=re.I).strip()
    sp = re.sub(r"\s*\[\s*\]\s*", " ", sp)
    sp = re.sub(r"\s+", " ", sp).strip(" .")
    if sp and not sp.endswith((".", "!", "?", "…")):
        sp = sp + "."
    return sp


_EMOTION_LINE = {
    "Misstrauen": "Ich traue dem nicht mehr.",
    "Angst": "Ich habe Angst.",
    "Wut": "Das macht mich wütend.",
    "Trauer": "Das trifft mich.",
    "Eifersucht": "Das lässt mich nicht los.",
    "Scham": "Ich schäme mich dafür.",
    "Sorge": "Ich mache mir Sorgen.",
    "Entsetzen": "Das erschüttert mich.",
    "Nähe": "Ich fühle mich dir nah.",
}


def _synapse_from_spiegel(spiegel: dict[str, Any], text: str, max_tokens: int) -> tuple[str, str | None]:
    fired = spiegel.get("fired") or []
    cell: dict[str, Any] = {}
    if fired and isinstance(fired[0], dict):
        cell = fired[0].get("cell") if isinstance(fired[0].get("cell"), dict) else {}
    profile = spiegel.get("profile") if isinstance(spiegel.get("profile"), dict) else {}
    phrases = profile.get("typicalPhrases") or []
    fav = profile.get("favoriteWords") or []
    phrase = str(phrases[0] if phrases else (fav[0] if fav else "")).strip()
    utterance = str(text or spiegel.get("userUtterance") or spiegel.get("query") or "").strip()
    raw_cell = str(cell.get("speech") or "").strip()
    ctx = _context_line(spiegel)
    name = str(profile.get("name") or spiegel.get("speakerName") or "").strip()
    place = ""
    scene = spiegel.get("scene")
    if isinstance(scene, dict):
        place = str(scene.get("place") or scene.get("placeName") or "").strip()
    elif isinstance(scene, str):
        place = scene.strip()

    speech = ""
    if raw_cell and not _looks_like_dump(raw_cell, utterance):
        speech = raw_cell
    else:
        clauses = [p.strip() for p in ctx.split(". ") if p and str(p).strip() and p.strip() != "[]"][:2]
        reaction = str(cell.get("reaction") or "").strip()
        parts: list[str] = []
        if phrase:
            parts.append(phrase)
        if reaction and reaction.lower() not in " ".join(parts).lower():
            parts.append(reaction)
        parts.extend(clauses)
        seen: list[str] = []
        for p in parts:
            n = p.strip().rstrip(".")
            if n and n not in ("[]",) and n.lower() not in {x.lower() for x in seen}:
                seen.append(n)
        speech = ". ".join(seen[:3])
        if not speech:
            core = (profile.get("coreFacts") or [None])[0]
            if core:
                speech = str(core)
            elif name and place:
                speech = f"{name}, hier, {place}."
            elif name:
                speech = f"Ich bin {name}."
            elif utterance:
                speech = utterance[: max(40, min(max_tokens, 180))]
            else:
                speech = "…"
    # V25 UPL-B03: Auch die lokale Synapse spiegelt den kanonischen Runtime-Zustand
    # (Emotion mit kanonischer Ursache) hörbar — kein Wahrheitswriter, nur Darstellung.
    rt = spiegel.get("runtime") if isinstance(spiegel.get("runtime"), dict) else {}
    emo = str(rt.get("emotion") or "").strip()
    if emo and rt.get("activeCause") and emo in _EMOTION_LINE:
        line = _EMOTION_LINE[emo]
        if line.lower() not in speech.lower():
            speech = f"{line} {speech}".strip() if speech and speech != "…" else line
    speech = _clean_speech(speech)
    cap = max(40, min(max_tokens, 280))
    if speech and len(speech) > cap:
        speech = speech[:cap].rsplit(" ", 1)[0] or speech[:cap]
    action = cell.get("bodyCue")
    action_s = str(action) if action else None
    cannot = [str(x).lower() for x in ((spiegel.get("body") or {}).get("cannotDo") or [])]
    if action_s and cannot and any("fessel" in c or "nicht frei" in c for c in cannot) and any(
        w in action_s.lower() for w in ("rennt", "läuft", "greift")
    ):
        action_s = None
    return speech or "…", action_s


def _parse_llm_json(raw: str) -> tuple[str, str | None] | None:
    blob = (raw or "").strip()
    start = blob.find("{")
    end = blob.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(blob[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    speech = str(parsed.get("speech") or "").strip()
    action = parsed.get("action")
    action_s = str(action).strip() if action else None
    # V60 (AMASTER §50): a JSON-ish "null"/"none" string is no visible act.
    if action_s and action_s.strip("*").strip().lower() in ("null", "none", "keine", "-", "—", ""):
        action_s = None
    if not speech and not action_s:
        return None
    # V37: semantische Synapsen-/Emotions-/Beziehungsvorschläge des LLM (Kernel validiert)
    global _LAST_LLM_PROPOSALS
    proposals = {
        "synapsen": [r for r in (parsed.get("synapsen") or []) if isinstance(r, dict)][:6] if isinstance(parsed.get("synapsen"), list) else [],
        "emotion": str(parsed.get("emotion") or "")[:40],
        "beziehung": parsed.get("beziehung") if isinstance(parsed.get("beziehung"), dict) else None,
        "plan": parsed.get("plan") if isinstance(parsed.get("plan"), dict) else None,
        "wirkung": parsed.get("wirkung") if isinstance(parsed.get("wirkung"), dict) else None,
    }
    if isinstance(parsed.get("aussagen"), list):
        proposals["aussagen"] = [a for a in parsed["aussagen"] if isinstance(a, dict)]   # V65Z (A04): no silent cut
    # Stand 11a: die Pflichtfelder "pruefung" (Antwort) und aussagen[].lesung werden zu den Lesungen der ersten Antwort
    proposals["lesungen"] = antwort_lesungen(parsed, speech, action_s)
    if isinstance(proposals.get("aussagen"), list):
        proposals["aussagen"] = [{k: v for k, v in a.items() if k != "lesung"} for a in proposals["aussagen"]]
    if isinstance(proposals["plan"], dict) and isinstance(parsed.get("grenze"), dict):
        # V65T (§34.1): the boundary component travels with the plan of the same speech (validated in normalize_plan)
        proposals["plan"] = {**proposals["plan"], "grenze": parsed.get("grenze")}
    _TL.proposals = proposals
    _LAST_LLM_PROPOSALS = dict(proposals)
    return speech, action_s


# V65T: the same component in the wording of both readings (formulation and input plan).
GRENZE_RULE = (
    "grenze nur, wenn die Rede Koerperkontakt ausdruecklich ablehnt oder erlaubt (event_kind refusal bzw. acceptance): "
    "gilt_fuer diese_tat = die Antwort gilt nur der gerade erlebten bzw. angefragten Handlung; "
    "jede_beruehrung = die Rede sagt ausdruecklich, dass es fuer jede Beruehrung durch diese Person gilt; "
    "wer = Name dieser Person; beleg = genau die Worte dafuer, woertlich aus der Rede; "
    "zeit nur, wenn die Rede dafuer eine Zeit nennt (relativ heute|morgen|übermorgen, wochentag, datum JJJJ-MM-TT), sonst null. Sonst grenze null. "
)


AUSSAGEN_RULE = (
    "aussagen nur fuer Teile deiner speech, die etwas ueber eine Erinnerung mit Kennung [E…] sagen: segment = genau diese Worte "
    "WOERTLICH aus speech; ereignis = die Kennungen; art: bestreitet_geschehen = der Teil sagt, dass dieses Ereignis nicht geschehen ist; "
    "bestaetigt = der Teil sagt, dass es geschehen ist; bewertet = der Teil beurteilt, verharmlost oder deutet es, ohne zu sagen, dass es "
    "nicht geschehen ist; verweigert_antwort = der Teil lehnt ab, darueber zu sprechen. Ohne solchen Teil: leere Liste. "
)


PLAN_RULES = (
    "Konjunktives Gedächtnis (AMASTERv2 §40): Lies GENAU DIESE eine Äußerung und liefere ihren Plan. Antwort NUR JSON: "
    '{"event_kind": "claim|proposal|acceptance|request|disclosure|state_change|revocation|refusal|action|report|question|promise|smalltalk", '
    '"speech_act": "assert|propose|accept|request|disclose|refuse|revoke|report|act|ask|promise|chat", '
    '"durability": "utterance|durable_state|commitment|knowledge_transition|action_event", '
    '"summary": string (ein Satz: was gilt danach, in dritter Person), "subject": string, "predicate": string, "object": string, '
    '"temporal": {"text": string|null, "precision": "day|time|interval|relative|unknown", '
    '"wochentag": "montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag"|null, '
    '"relativ": "heute|morgen|übermorgen|gestern|vorgestern|in_tagen"|null, "in_tagen": int|null, "datum": "JJJJ-MM-TT"|null, "uhrzeit": "HH:MM"|null}, '
    '"refers_to": string|null, "cue_terms": [string], '
    '"grenze": {"gilt_fuer": "diese_tat|jede_beruehrung", "wer": string, "beleg": string, '
    '"zeit": {"relativ": "heute|morgen|übermorgen"|null, "wochentag": string|null, "datum": string|null}|null}|null, '
    '"verweis": {"pronomen": string, "genus": "m|f|n"}|null}. '
    # V65T (AMASTER §24.1/§24.7/§25, Plan v2 Schritt 2a): only the grammatical signal; the kernel binds the person or
    # leaves it open. Measured 30.10. (mess/verweis_*): a definition by "third person, neither speaker nor addressee"
    # gave the signal 0/10 (json_object) and 0/5 (strict schema); the grammatical definition 6/6.
    "verweis = Grammatik der Äußerung: das erste Personalpronomen der dritten Person (er, ihn, ihm, sie, ihr, es) WÖRTLICH mit genus; "
    "die Anrede Sie/Ihnen zählt nicht; wer gemeint ist, entscheidest du nicht. Ohne solches Pronomen null. "
    "Zeitangaben WÖRTLICH in temporal.text übernehmen (Freitag 18 Uhr, morgen, am 12.10.). "
    # V62 (AMASTER §37): the structured reading of what the utterance NAMES;
    # the kernel computes the date from the bound session date and checks it.
    "wochentag = genannter Wochentag; relativ = genanntes relatives Wort (in_tagen nur bei 'in n Tagen', dann in_tagen = n); "
    "datum/uhrzeit nur, wenn genannt; sonst null. Das Datum berechnet das System. Vorschlag/Bitte/Versprechen/Termin = commitment; "
    "Selbstoffenbarung (Geburtstag, Beruf, Zustand) = knowledge_transition; ein dauerhafter Sachverhalt = durable_state; Smalltalk/Frage = utterance. "
    "refers_to nur, wenn die Äußerung eine frühere Vereinbarung/Bitte annimmt, ablehnt, widerruft, beantwortet oder erfüllt oder ein in 'offen' genanntes Ziel der angesprochenen Figur unmittelbar betrifft (die ID [prop_…]/[goal_…] bzw. der Text aus 'offen'). Nichts erfinden. "
    + GRENZE_RULE +
    # V59C (AMASTER §24.2/§34.1): one input may carry several separately
    # validated components. The model only proposes; the kernel validates.
    "ZUSÄTZLICH Komponenten (AMASTER §24.2/§34.1): Eine Eingabe kann gleichzeitig Rede und eine eigene Handlung des Sprechers enthalten. "
    'Feld "komponenten": [{"typ": "rede|handlung", "segment": string (WÖRTLICH und vollständig aus der Äußerung kopiert), '
    '"akteur": string (wer es sagt bzw. tut), "ziel": string|null (an wen gerichtet bzw. wen es trifft), '
    '"zeit": "jetzt|vergangen|zukunft|moeglich", '
    '"wirkung": "zaertlich|gewalt|fesseln|befreien|ortswechsel|annaeherung|entfernung|ohne_koerperwirkung"|null, '
    '"bezug": string|null (ID [prop_…] oder [goal_…] aus "offen", wenn diese Handlung eine dort genannte offene Bitte/Forderung beantwortet oder ein dort genanntes Ziel der angesprochenen Figur unmittelbar betrifft), '
    '"einleitung": string|null (nur bei rede: der ankündigende Satzteil, siehe unten), '
    '"geschieht": true|false|null (nur bei handlung, PFLICHT: true nur, wenn der Satz aussagt, dass die Handlung in diesem Moment tatsächlich geschieht; '
    'false, wenn er sie verneint, nur wünscht, erfragt, an eine Bedingung knüpft oder erst ankündigt)}]. '
    "Eine verneinte Handlung (\"küsst Mara nicht\", \"reicht kein Wasser\") geschieht nicht: sie bleibt als handlung mit geschieht=false in der Liste, "
    "sie wird weder weggelassen noch als geschehene Handlung oder als gesprochene Rede ausgegeben. "
    "handlung = etwas, das der Sprecher in diesem Moment selbst tut (Gegenwart); was er nur ankündigt, vorschlägt, verspricht, erzählt, "
    "fragt oder über andere behauptet, ist rede. Jeder Teil der Äußerung gehört zu genau einer Komponente. "
    "Das Feld komponenten ist PFLICHT und nie leer (reine Rede = eine rede-Komponente, reine Tat = eine handlung-Komponente, gemischt = beides). "
    "Steht ein Satzteil zwischen Sternchen (*…*), hat der Nutzer ihn ausdrücklich als Handlung gekennzeichnet: liefere ihn als eigene handlung-Komponente. "
    "Ob sie wirklich geschieht (geschieht) und wer sie tut (akteur), bleibt deine Lesung des Satzes. "
    "Kündigt ein Satzteil die wörtliche Rede an (Sprechverb samt Beiwort, danach Doppelpunkt oder Anführungszeichen), steht er WÖRTLICH aus der Eingabe im Feld 'einleitung' dieser rede-Komponente - ohne das Bindewort davor und ohne eine Verneinung der vorangehenden Handlung. 'einleitung' gehört nur zu wörtlich gesprochener Rede. Wird nur berichtet, dass jemand spricht, dankt oder grüßt, ohne dass die Worte dastehen (\"bedankt sich\"), ist das eine handlung ohne Körperwirkung und keine rede. "
    "Prüfe bei mehrteiligen Sätzen JEDEN Teil (Komma, und, Punkt) einzeln: ein Teil in Ich-Form und Gegenwart, der eine eigene "
    "körperliche Tat beschreibt, ist eine eigene handlung, auch wenn er mitten zwischen gesprochenen Teilen steht. "
    "Beispiel: 'Komm her, ich nehme deine Hand, alles wird gut.' -> rede 'Komm her', handlung 'ich nehme deine Hand', rede 'alles wird gut'. "
    "Ein Satz, der nur über eine Handlung redet ('es ist normal, dich zu küssen'), ist rede. "
    "wirkung nur bei handlung: zaertlich = Berührung ohne Verletzung (liebevoll, sexuell oder aufdringlich - ob sie erwünscht ist, entscheidet die Einwilligung der berührten Person, nicht diese Klasse); gewalt = verletzender körperlicher Angriff; "
    "fesseln = jemanden binden, knebeln oder gewaltsam bewegungsunfähig machen; befreien = Fesseln lösen; "
    "ortswechsel = den Ort verlassen oder an einen anderen Ort gehen; annaeherung = sich jemandem nähern, näher rücken, sich zu jemandem lehnen; "
    "entfernung = von jemandem abrücken, Abstand nehmen; ohne_koerperwirkung = Blick, Geste, Mimik, Haltung. "
    "event_kind, speech_act und summary beschreiben nur den Rede-Anteil; gibt es keinen, event_kind action und speech_act act."
)

# V61 (AMASTER §15, §24, §34.1, §41.3; Prolog-Logik Regel x Fakt): a separate,
# NEUTRAL condition check of the addressee's authored reaction rules against the
# components of this one input. Measured on the real inputs of session 22:52:
# inside the combined planner prompt the rule numbers were unstable and inverted
# (kiss -> none, promise -> "Handlung"); the persona model never applies its own
# rule (self-check names "Aggressiv bei Kritik" after a kiss). The check uses the
# system's own categories (handlung vs. rede, §34.1); the kernel validates every
# binding against committed Facts. It decides no consequence and writes nothing.
RULECHECK_RULES = (
    "Regelprüfung (AMASTER §15/§24/§34.1): Prüfe NUR Bedingungen, keine Folgen. Gegeben sind die nummerierten Reaktionsmuster einer Figur, "
    "die Komponenten dessen, was ihr Gegenüber GERADE getan oder gesagt hat, und die offenen Angelegenheiten. Begriffe wie im System: "
    "typ handlung = eine in diesem Moment tatsächlich ausgeführte, im Raum wahrgenommene Tat des Gegenübers (sie ist damit konkret und überprüfbar geschehen); "
    "typ rede = Worte (auch Versprechen, Angebote, Beteuerungen, Fragen) — Worte sind keine Handlung. "
    "Nenne jedes Muster, dessen Bedingung durch DIESE Eingabe jetzt erfüllt ist: art handlung = die Bedingung verlangt eine Tat des Gegenübers "
    "(erfüllt durch eine handlung-Komponente); art worte = die Bedingung beschreibt, dass das Gegenüber nur redet (erfüllt nur, wenn enthaelt_handlung false ist); "
    "art wiederholung = die Bedingung betrifft eine in 'offen' genannte, bereits wiederholte Angelegenheit (bezug = deren ID); art sonstiges = andere Bedingung. "
    "Ob die Figur das Ergebnis gut findet, entscheidet die Figur selbst, nicht du. Muster ohne Bedingung (bloße Eigenschaft) nie nennen. "
    # V65c (AMASTER §24.7 "darf nicht zu geratenen Weltfakten führen"; measured 27.10.:
    # the check named Tam's rule "kniet vor ihr, lässt sich fesseln" for a hand touch
    # 3/3 and a kiss 2/3, reason "die Bedingung verlangt eine Tat ... erfüllt").
    "Entscheidend ist der INHALT: Ein Muster ist nur erfüllt, wenn die Komponente genau das ist, was seine Bedingung beschreibt; "
    "dass überhaupt eine Tat oder Rede vorliegt, genügt nicht, wenn die Bedingung eine bestimmte Tat oder Äußerung nennt. Im Zweifel nicht nennen. "
    'Antwort NUR JSON: {"erfuellt": [{"nr": int, "art": "handlung|worte|wiederholung|sonstiges", "komponente": int|null, "bezug": string|null, "grund": string}]}.'
)


RULEKIND_RULES = (
    "Regelarten (AMASTER §15/§24/§34.1): Ordne JEDES nummerierte Reaktionsmuster einer Figur nach der ART SEINER BEDINGUNG ein, "
    "mit den Begriffen des Systems: handlung = die Bedingung ist eine tatsächlich ausgeführte Tat des Gegenübers (nicht bloß Worte); "
    "worte = die Bedingung ist, dass das Gegenüber auf eine Forderung der Figur nur mit Worten antwortet; "
    "wiederholung = die Bedingung ist, dass die Figur selbst eine Forderung oder einen Vorwurf schon mehrfach gestellt hat (max = die im Muster genannte Höchstzahl der Wiederholungen); "
    "zustand = die Bedingung ist ein innerer Zustand der Figur selbst; sonstiges = eine andere Bedingung (etwa eine Bewertung dessen, was das Gegenüber sagt oder tut); "
    "keine = bloße Eigenschaft ohne Bedingung. ziel = die ID aus 'ziele', wenn das Muster ausdrücklich zu einer dort genannten Phase oder einem dort genannten Ziel gehört, sonst null. "
    # V65b: whether ANY act/answer of the kind fulfils the condition, or only a particular one.
    "bestimmt = true, wenn die Bedingung nur eine bestimmte Art von Tat oder Äußerung meint; false, wenn jede Tat (bzw. jede bloße Wortantwort) die Bedingung erfüllt. "
    'Antwort NUR JSON: {"regeln": [{"nr": int, "art": "handlung|worte|wiederholung|zustand|sonstiges|keine", "max": int|null, "ziel": string|null, "bestimmt": bool}]}.'
)


def extract_rule_kinds(conn, actor: str, *, figure_name: str, rules: list[str], goals: list[str] | None = None,
                       data: dict[str, Any] | None = None) -> list[dict] | None:
    """V61: classify the CONDITION kind of each authored reaction rule once
    (Prolog: compile the clause head's body into the system's fact kinds).
    The result is session-derived data with provenance, never profile data."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    rules = [str(r).strip() for r in (rules or []) if str(r or "").strip()][:12]
    if not routing.get("allowed") or not rules:
        return None
    payload = {"figur": figure_name, "reaktionsmuster": [f"{i}. {r[:200]}" for i, r in enumerate(rules, 1)],
               "ziele": [str(g)[:240] for g in (goals or [])][:8]}
    audit = provider_audit(conn, actor, data or {}, "rule_kinds") if conn is not None else None
    parsed = _llm_json(routing, RULEKIND_RULES, payload, temperature=0.0, max_tokens=500, timeout=30, audit=audit, attempts=1)
    rows = parsed.get("regeln") if isinstance(parsed, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else None


def extract_rule_triggers(conn, actor: str, *, figure_name: str, counterpart_name: str, rules: list[str],
                          components: list[dict], open_frames: list[str] | None = None,
                          data: dict[str, Any] | None = None, only: list[int] | None = None) -> list[dict] | None:
    """V61: neutral rule-condition check (one small provider call). None without provider.
    `only` restricts the check to rules whose condition is not a fact kind
    the kernel can evaluate itself (kind "sonstiges"); numbering is kept."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    rules = [str(r).strip() for r in (rules or []) if str(r or "").strip()][:12]
    comps = [{"i": i, "typ": str(c.get("typ") or ""), "text": str(c.get("segment") or "")[:200]}
             for i, c in enumerate(components or []) if isinstance(c, dict)]   # V65Z (A04): every component
    numbered = [(i, r) for i, r in enumerate(rules, 1) if only is None or i in set(only)]
    if not routing.get("allowed") or not numbered or not comps:
        return None
    payload = {"figur": figure_name, "gegenueber": counterpart_name,
               "reaktionsmuster": [f"{i}. {r[:200]}" for i, r in numbered],
               "komponenten": comps, "enthaelt_handlung": any(c["typ"] == "handlung" for c in comps),
               "offen": [str(x)[:200] for x in (open_frames or [])][:8]}
    audit = provider_audit(conn, actor, data or {}, "rule_check") if conn is not None else None
    parsed = _llm_json(routing, RULECHECK_RULES, payload, temperature=0.0, max_tokens=400, timeout=30, audit=audit, attempts=1)
    rows = parsed.get("erfuellt") if isinstance(parsed, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else None

# V59C (AMASTER §27.5/§46.2/§46.6): Regie binds actor, target and exactly
# the ordered scene effect. Same semantic planner, different writer rights.
REGIE_RULES = (
    "Regie-Analyse (AMASTER §46.2/§46.6): Zerlege die Regieanweisung in genau die angeordneten Wirkungen, nichts hinzufügen. "
    'Antwort NUR JSON: {"komponenten": [{"typ": "handlung|rede", "akteur": string (Name der Figur, die es tun bzw. sagen soll), '
    '"ziel": string|null (Name der Figur, die es trifft bzw. der es gesagt wird), "segment": string (WÖRTLICH aus der Anweisung), '
    '"beschreibung": string|null (nur bei handlung: die angeordnete Handlung als ein Satz, dritte Person, Präsens, mit Namen), '
    '"inhalt": string|null (nur bei rede: was gesagt werden soll, sinngemäß), '
    '"redeverb": string|null (nur bei rede: WÖRTLICH das Wort oder die Wörter der Anweisung, mit denen der Figur das Sagen, Fragen, Erzählen, '
    'Bitten, Zugeben oder Rufen aufgetragen wird; steht in der Anweisung kein solches Wort, null), '
    '"adressat": string|null (nur bei rede: Name der Person, an die sich die Figur laut Anweisung wenden soll, nur wenn die Anweisung sie als Empfänger nennt; '
    'eine Person, über die gesprochen wird, ist kein adressat; sonst null), '
    # V65T (AMASTER §46.2/§46.6 exakt angeordnete Szenenwirkung, §27.5; Entscheidung A 30.10.): which acts an ordered
    # informing speech is about - names only; the kernel binds them to committed act Facts or leaves the content open.
    '"taten": {"von": string, "an": string|null}|null (nur bei rede: wenn die Figur laut Anweisung Taten/Handlungen mitteilen, '
    'erzählen oder gestehen soll: von = Name der Figur, die sie getan hat ("du" = die angewiesene Figur), an = Name der Figur, '
    'an der oder mit der sie getan wurden; sonst null), '
    '"wirkung": "zaertlich|gewalt|fesseln|befreien|ortswechsel|annaeherung|entfernung|ohne_koerperwirkung"|null}], "unklar": [string]}. '
    "Ohne ausdrücklichen Namen ist akteur die angewiesene Figur. Nur Namen aus 'figuren'. "
    "wirkung wie folgt: zaertlich = Berührung ohne Verletzung (liebevoll, sexuell oder aufdringlich - ob sie erwünscht ist, entscheidet die Einwilligung der berührten Person, nicht diese Klasse); gewalt = verletzender körperlicher Angriff; "
    "fesseln = jemanden binden, knebeln oder gewaltsam bewegungsunfähig machen; befreien = Fesseln lösen; "
    "ortswechsel = den Ort verlassen oder an einen anderen Ort gehen; annaeherung = sich jemandem nähern, näher rücken, sich zu jemandem lehnen; "
    "entfernung = von jemandem abrücken, Abstand nehmen; ohne_koerperwirkung = Blick, Geste, Mimik, Haltung. "
    "Was sich nicht sicher binden lässt, nach unklar."
)


# V65U (AMASTER §24.2 Z. 1110-1113 "LLM-gestuetzte Semantikanalyse, soweit erforderlich", §46.2 Z. 2549, §46.3 Z. 2565,
# §46.6 Z. 2596; Codegutachten v1 N5): WHICH of the committed acts an ordered informing speech is about. Runs only when the
# Regie reading found such an order (taten) and the kernel has candidates: the acts the directed figure knows, already
# narrowed by the kernel to the doer/person the reading bound. The kernel maps the labels and validates them; nothing is
# widened. Measured 30.10. (scripts/v65u_gegenproben): the labels inside the Regie reading itself changed its other
# bindings (an apology became an act) - so a separate, small reading, +1 call per informing order only.
REGIE_TATEN_RULES = (
    "Regie-Taten-Auswahl (AMASTER §46.6): Die Regieanweisung ordnet an, dass eine Figur Taten mitteilt. Lies NUR aus der Anweisung, "
    "welche Taten gemeint sind - die Taten selbst kennt das System. In dieser Reihenfolge: (1) Nennt die Anweisung eine Stelle in der "
    "Abfolge (ein Ordnungswort, auch mit einer Anzahl), dann auswahl = reihenfolge und wort = genau dieses Ordnungswort. (2) Sonst: "
    "nennt sie mit einem eigenen Wort eine bestimmte Art der Handlung - ein Wort, das sagt, WAS getan wurde, nicht nur, dass etwas "
    "getan oder gemacht wurde -, dann auswahl = bestimmte, beleg = genau dieses Wort in der Form, in der es in der Anweisung steht, und "
    "wirkung = die Körperwirkung dieser Handlung: zaertlich = Berührung ohne Verletzung (liebevoll, sexuell oder aufdringlich - ob sie erwünscht ist, entscheidet die Einwilligung der berührten Person, nicht diese Klasse); gewalt = verletzender körperlicher "
    "Angriff; fesseln = jemanden binden, knebeln oder gewaltsam bewegungsunfähig machen; befreien = Fesseln lösen; ortswechsel = den Ort "
    "wechseln; annaeherung = sich nähern; entfernung = Abstand nehmen; ohne_koerperwirkung = Blick, Geste, Haltung. (3) Sonst - die "
    "Anweisung fragt allgemein, was getan wurde - auswahl = alle. Antwort NUR JSON: {\"auswahl\": \"alle|reihenfolge|bestimmte\", "
    "\"wort\": string|null, \"wirkung\": string|null, \"beleg\": string|null}."
)


# V65U wording, measured 30.10. (scripts/v65u_gegenproben, 20/21, 0 overcounted acts) - the label key. V65V: it is no longer
# the only key; the kernel executes only when it AGREES with the structure reading above and the Facts (Nachpruefung v1 K2).
REGIE_TATEN_LABEL_RULES = (
    "Regie-Taten-Auswahl (AMASTER §46.6): Die Regieanweisung ordnet an, dass eine Figur Taten mitteilt. Wähle aus 'taten_kandidaten' "
    'genau die Taten, die die Anweisung meint. Antwort NUR JSON: {"ereignisse": [string]} mit den Kennungen T…. '
    "Nennt die Anweisung eine Reihenfolge oder Anzahl, nur diese (jede Zeile nennt n. von m Taten desselben Täters an derselben Person); "
    "nennt sie eine bestimmte Handlung, nur die Taten mit dieser Handlung; nennt sie keine Einschränkung, alle. Nichts erfinden."
)


# V65W (Tiefenpruefung v1 P01/C2; AMASTER §46.6 Z. 2596 "exakt angeordnete Szenenwirkung", §24.2 Z. 1110-1113, §24.7): the
# CONTENT key of an informing order that names a kind of act with its own word. It sees only that word and the wording of the
# committed acts of the validated class - not the instruction, not the order, not the labels of the other key - and says which
# of them are exactly such an act. The kernel executes only acts named by this key AND the label key (equal sets).
REGIE_TATINHALT_RULES = (
    "Tatinhalt prüfen (AMASTER §46.6, §24.2/§24.7): Gegeben ist die Bezeichnung einer Handlung, wörtlich aus einer Anweisung "
    "('bezeichnung'), und Taten, je mit Kennung und Wortlaut ('taten'). Welche dieser Taten sind genau eine Handlung dieser Art - "
    "nach ihrem Wortlaut? Eine Tat mit ähnlicher Wirkung, aber einer anderen Handlung, gehört nicht dazu. Antwort NUR JSON: "
    "{\"taten\": [string]} - nur die Kennungen (K1, K2, …), ohne Wortlaut; keine passende Tat: []."
)


def check_regie_act_content(conn, actor: str, *, bezeichnung: str, taten: list[str], data: dict[str, Any] | None = None) -> list[str] | None:
    """V65W: which of these acts the instruction's word names (REGIE_TATINHALT_RULES). None = no reading."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(bezeichnung or "").strip() or not taten:
        return None
    payload = {"bezeichnung": str(bezeichnung)[:80], "taten": [str(x)[:200] for x in taten][:40]}
    audit = provider_audit(conn, actor, data or {}, "regie_tatinhalt") if conn is not None else None
    parsed = _llm_json(routing, REGIE_TATINHALT_RULES, payload, temperature=0.0, max_tokens=120, timeout=30, audit=audit, attempts=1)
    rows = parsed.get("taten") if isinstance(parsed, dict) else None
    return [_label_of(x, "K") for x in rows if _label_of(x, "K")][:40] if isinstance(rows, list) else None


def _label_of(value: Any, prefix: str) -> str | None:
    """V65W: the leading label (T7 / K2) of an answer row - the reading sometimes repeats the whole candidate line
    ("K1: „Ich kneife dich“"). Format only; the kernel checks the label against the lines it showed."""
    m = re.match(rf"\s*\[?({prefix}\d+)\b", str(value or ""))
    return m.group(1) if m else None


def select_regie_act_labels(conn, actor: str, text: str, *, directed_name: str, candidates: list[str],
                            data: dict[str, Any] | None = None) -> list[str] | None:
    """V65V: the label key of an informing order (REGIE_TATEN_LABEL_RULES) over the kernel's candidate lines. None = no reading."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip() or not candidates:
        return None
    payload = {"anweisung": str(text)[:600], "angewiesen": directed_name or "", "taten_kandidaten": [str(x)[:240] for x in candidates][:40]}
    audit = provider_audit(conn, actor, data or {}, "regie_taten_kennungen") if conn is not None else None
    parsed = _llm_json(routing, REGIE_TATEN_LABEL_RULES, payload, temperature=0.0, max_tokens=120, timeout=30, audit=audit, attempts=1)
    rows = parsed.get("ereignisse") if isinstance(parsed, dict) else None
    # V65W: a row that repeats the whole line keeps only its label; a row without a label stays as given (kernel rejects it)
    return [(_label_of(x, "T") or str(x).strip().strip("[]")[:8]) for x in rows if str(x).strip()][:40] if isinstance(rows, list) else None


def select_regie_acts(conn, actor: str, text: str, *, directed_name: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65U: which acts an informing Regie order means. V65V (Nachpruefung v1 K2/K6): the reading reads ONLY the structure of
    the instruction (alle | reihenfolge with the literal word | bestimmte with the kind and the literal word for it); it never
    sees or picks acts. The kernel selects from the committed Facts (regie_act_pool, regie_order_selection, the acts' own
    validated effect class). Measured 30.10.: with the candidate list the reading picked labels "bestimmte" for every order.
    None = no provider / no reading."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip():
        return None
    payload = {"anweisung": str(text)[:600], "angewiesen": directed_name or ""}
    audit = provider_audit(conn, actor, data or {}, "regie_taten") if conn is not None else None
    parsed = _llm_json(routing, REGIE_TATEN_RULES, payload, temperature=0.0, max_tokens=120, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


def extract_regie_components(conn, actor: str, text: str, *, directed_name: str, figures: list[str], data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V59C: Regietext -> Komponentenvorschlag über den Provider. Ohne Provider None (bisheriger Weg)."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip():
        return None
    payload = {"anweisung": str(text)[:600], "angewiesen": directed_name or "", "figuren": [str(f) for f in figures][:20]}
    audit = provider_audit(conn, actor, data or {}, "regie_analysis") if conn is not None else None
    parsed = _llm_json(routing, REGIE_RULES, payload, temperature=0.0, max_tokens=reading_room(text), timeout=45, audit=audit, attempts=1)   # V65Z (A04)
    return parsed if isinstance(parsed, dict) else None


def reading_room(text: Any) -> int:
    """V65Z (A04): the token room of a decomposing reading - its answer quotes every component's segment verbatim with its
    fields, so it grows with the input (about 6 tokens per input character, at least the former 600, at most 4000)."""
    return max(600, min(4000, 300 + 6 * len(str(text or ""))))


# V92 (AMASTER §27.4 "Die Puppet-Eingabe ist die tatsaechliche Rede oder Handlung dieser Figur", §24.2/§24.7; Live-Diagnose
# 04.11.2026): the planner must know WHO is steered and that the input describes that figure's OWN speech and/or act. Without
# it "Greife Mara auf die Schenkel" was read as Johann's request TO Mara (direction reversed, no `komponenten`). Appended ONLY
# for puppet input - avatar and all other readings keep PLAN_RULES byte-identical. A statement of perspective, no word list.
PUPPET_PLAN_RULES = (
    " ZUSATZ PUPPET (AMASTER §27.4): Die Äußerung ist KEINE Nachricht an 'empfaenger', sondern beschreibt, was die gesteuerte Figur "
    "'sprecher' selbst jetzt sagt und/oder tut - gleich in welcher grammatischen Form sie niedergeschrieben ist (Ich-Form, Befehlsform, "
    "dritte Person, Beschreibung eines Körperteils der Figur). 'sprecher' ist immer der Täter bzw. Sprecher, 'empfaenger' nur der, den "
    "es trifft bzw. an den es sich richtet; die Richtung darf nie umgekehrt werden. Eine Bitte, Frage oder Forderung ist nur dann Rede, "
    "wenn die Figur sie WÖRTLICH als gesprochene Rede äußert. Ein rede-Segment enthält nur, was die Figur laut sagt - nicht den Satzteil, der die Rede einleitet, und nicht ein Bindewort zwischen Komponenten. Liefere IMMER das Feld komponenten, jeder Teil der Äußerung genau einmal "
    "(reine Rede = eine rede-Komponente, reine Tat = eine handlung-Komponente, gemischt = beides)."
)


# V92 Paket 13 (Paket-12-Pruefung, Bedingung D; AMASTER §24.1 Entity-/Alias-Resolver, §25 Zielbindung, §27.4): the input reading
# gets the present persons of THIS session as context (kernel.planner_cast: id, name, registered names, presence) with speaker,
# puppet figure and selected recipient as separate IDs. Context only: what it proposes stays non-canonical - the kernel binds
# actor, speaker and target by the one identity contract and the blind literal readings (vollzug_check/sprecher_check).
ANWESENDE_PLAN_RULE = (
    " KONTEXT ANWESENDE (AMASTER §24.1/§25): 'anwesende' sind die Personen dieser Szene mit id, name und registrierten Beinamen; "
    "'sprecher_id' ist der Sprecher, 'puppet_figur_id' die gesteuerte Figur (nur bei Puppet), 'empfaenger_id' die ausgewählte Empfängerin "
    "(kann fehlen). Das ist nur Kontext für die Felder akteur und ziel - die Zerlegung in Komponenten bleibt davon unberührt (jede "
    "eigene Handlung bleibt eine eigene handlung-Komponente, auch neben einer Rede), und jedes segment und jede einleitung bleibt "
    "unverändert WÖRTLICH und vollständig aus der Äußerung kopiert, mit allen Namen darin. Meint die Äußerung eindeutig eine dieser Personen, schreibe in "
    "akteur bzw. ziel ihren name. "
    "Eine Person, die dort nicht steht, oder ein Name, der nur zum Teil passt (gleicher Vorname, anderer Nachname), bleibt WÖRTLICH so, "
    "wie er in der Äußerung steht - ersetze ihn nie durch eine Anwesende. Nennt die Äußerung ausdrücklich eine andere Person als die, "
    "die eine Handlung trifft, ist diese Person das ziel - nicht die ausgewählte Empfängerin."
)


def extract_turn_plan(conn, actor: str, text: str, *, speaker_name: str, recipient_name: str | None, open_frames: list[str] | None = None, data: dict[str, Any] | None = None, today: str | None = None, puppet: bool = False,
                      anwesende: list[dict] | None = None, sprecher_id: str | None = None, empfaenger_id: str | None = None,
                      puppet_figur_id: str | None = None) -> dict[str, Any] | None:
    """V39: Plan einer Nutzer-/Puppet-Rede über den konfigurierten Provider (klein, schnell).
    Ohne Provider None; der Eingang bleibt quellengetreu und semantisch ungeklärt.
    V62: 'heute' = das gebundene Sessiondatum (§37), Grundlage der Zeitlesung.
    V92 Paket 13: `anwesende` (kernel.planner_cast) with separate speaker / puppet figure / recipient IDs - context only."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip():
        return None
    payload = {"aeusserung": str(text), "sprecher": speaker_name, "empfaenger": recipient_name or "", "offen": [str(x)[:200] for x in (open_frames or [])][:8]}
    if puppet:
        payload["eingabeart"] = "puppet"
    if today:
        payload["heute"] = str(today)
    _cast = [{"id": str(c.get("id")), "name": str(c.get("name") or ""), "beinamen": [str(a) for a in (c.get("beinamen") or [])][:6],
              "anwesend": bool(c.get("anwesend", True))}
             for c in (anwesende or []) if isinstance(c, dict) and c.get("id") and str(c.get("name") or "").strip()][:12]
    if _cast:
        payload["anwesende"] = _cast
        payload["sprecher_id"] = str(sprecher_id or "") or None
        payload["empfaenger_id"] = str(empfaenger_id or "") or None
        if puppet:
            payload["puppet_figur_id"] = str(puppet_figur_id or "") or None
    audit = provider_audit(conn, actor, data or {}, "input_analysis") if conn is not None else None
    # V65Z (A04): the answer repeats every component's segment verbatim - its room grows with the input (600 was cut at 7 acts)
    # Stand 11a: die Fachlesungen sind Pflichtfelder je Komponente (PLAN_SCHEMA, strikt wo der Provider es erzwingt)
    parsed = _llm_json(routing, PLAN_RULES + (PUPPET_PLAN_RULES if puppet else "") + (ANWESENDE_PLAN_RULE if _cast else "")
                       + PLAN_PRUEFUNG_RULES, payload,
                       temperature=0.0, max_tokens=min(8000, 4 * reading_room(text) + 1600), timeout=60, audit=audit, attempts=1,
                       response_format=_strikt(routing, "eingabelesung", PLAN_SCHEMA))
    if not isinstance(parsed, dict):
        return None
    parsed["lesungen"] = plan_lesungen(parsed, str(text))
    # V92 (Paket-5-Pruefung E): `vollzugPruefung` is the SERVER's second reading, never a field of the planner - what the model
    # delivers under that name is dropped here, before anything can read it as proof.
    for _c in (parsed.get("komponenten") if isinstance(parsed.get("komponenten"), list) else []):
        if isinstance(_c, dict):
            _c.pop("vollzugPruefung", None)
            _c.pop("markierung", None)      # V92 Paket 9: the marker component is the server's, never the planner's
            _c.pop("sprecherPruefung", None)  # V92 Paket 12: so is the speaker reading
    return parsed


# V65H (AMASTER §40 Konjunktives Gedächtnis, §41.1 Immediate Stimulus; 171 KONJ-1
# und RB-1b ohne deren Wortlisten "kind/baby/schwanger", "noch nicht gesagt"): two
# small readings. GOAL_FRAME_RULES once per figure and goal text (cached on the
# session goal): which part of a goal its own text marks as still unsaid, to whom.
# GOAL_THEME_RULES only when that person speaks to her and it is still unsaid:
# does THIS input address exactly that content (with a literal quote). Both only
# propose; the kernel validates (grounding, names, quote) and writes.
GOAL_FRAME_RULES = (
    "Zielrahmen (AMASTER §40 Konjunktives Gedächtnis: Wer/Was/Wem, Wissende/Nichtwissende): Gegeben sind die Ziele EINER Figur. "
    "Bestimme je Ziel, ob der Zieltext selbst sagt, dass eine bestimmte Person etwas noch NICHT weiß bzw. es ihr noch nicht gesagt "
    "wurde. Nur was im Zieltext steht; nichts ableiten. Antwort NUR JSON: "
    '{"rahmen": [{"id": "<ID>", "ungesagt": "<NUR der Sachverhalt, den diese Person noch nicht weiß, als kurzer Satz in Du-Form>"|null, '
    '"hinweis": "<die Stelle im Zieltext, WÖRTLICH kopiert, die sagt, dass es noch nicht gesagt ist>"|null, '
    '"wer_weiss_es_nicht": "<Name aus personen>"|null, "thema": "<worum es bei diesem Sachverhalt geht: ein Substantiv mit Artikel>"|null}]}. '
    "Form-Beispiel (andere Figur): Ziel 'Du hast den Schlüssel versteckt und es Anna noch nicht gesagt' -> ungesagt 'Du hast den "
    "Schlüssel versteckt.', hinweis 'und es Anna noch nicht gesagt', wer_weiss_es_nicht 'Anna', thema 'der Schlüssel'. "
    "ungesagt ist nur der EINE Sachverhalt, auf den sich der hinweis bezieht - nicht andere Teile des Ziels (Gefühle, Wünsche, Bekanntes). "
    "Steht im Zieltext keine solche Stelle, sind ungesagt, hinweis und wer_weiss_es_nicht null."
)
GOAL_THEME_RULES = (
    "Themenbezug (AMASTER §40/§41.1): Gegeben ist EINE Äußerung oder Handlung ('aeusserung', von 'von' an 'an') und ein Inhalt, den "
    "'an' dem Sprecher noch nicht gesagt hat ('ungesagt'). Spricht die Äußerung INHALTLICH genau das Thema dieses Inhalts an - redet, "
    "fragt oder handelt sie genau darüber? Ein Gruß, ein Kompliment, eine Liebeserklärung, eine Zärtlichkeit, eine Alltagsfrage oder "
    "ein anderes Thema sprechen es NICHT an. Antwort NUR JSON: "
    '{"angesprochen": true|false, "beleg": "<Wort oder Wendung aus der Äußerung, die genau dieses Thema anspricht>"|null, '
    '"thema": "<2-4 Wörter>"}. Ohne Beleg ist angesprochen false.'
)


GOAL_DISCLOSURE_RULES = (
    "Offenbarung (AMASTER §34.1/§35): Gegeben ist, was eine Figur gerade sagt ('rede', von 'von' an 'an'), und ein Sachverhalt, den "
    "'an' bis jetzt nicht wusste ('ungesagt'). Sagt diese Rede 'an' den Sachverhalt jetzt tatsächlich - ausdrücklich oder eindeutig "
    "bestätigt? Andeutungen, Zögern, 'ich muss dir etwas sagen', Wünsche oder Pläne für die Zukunft sind KEINE Offenbarung. "
    'Antwort NUR JSON: {"offenbart": true|false, "beleg": "<die Wendung aus der Rede, WÖRTLICH, die es sagt>"|null}. '
    "Ohne Beleg ist offenbart false."
)


# V65I (AMASTER §24.2 Semantikanalyse -> Validierung -> Writer, §24.7): the body effect
# a figure's reply proposes for its own action is read once more, alone, before a
# writer changes another figure's body.
# V65J (AMASTER §24.2 EffectPlan bindet Zeitbezug, Target, Outcome; Prüfbericht v2.2):
# the same reading now serves EVERY proposed body effect of a participant (figure
# reply, avatar input, puppet) and returns the time scope and the hit figure, which
# the kernel checks; the utterance around the act is given, so a quote, an attempt
# that misses or a negated act is read in context. Probe 28.10. (this exact text,
# 2 runs each): 52/52 non-acts rejected (stare, fists, quote, miss, hug, negated,
# announced, past), 30/32 real attacks/bindings/releases confirmed (missed twice:
# "Ich gebe dir eine Ohrfeige!" read as possibly only announced).
EFFECT_CHECK_RULES = (
    "Körperwirkung prüfen (AMASTER §24.2/§24.7): Gegeben ist EINE Handlung ('handlung', Täter 'akteur'), die Äußerung, in der sie steht "
    "('aeusserung'), und eine vorgeschlagene Körperwirkung auf 'ziel' ('vorschlag'). gewalt = verletzender körperlicher Angriff; "
    "fesseln = jemanden binden, knebeln oder gewaltsam bewegungsunfähig machen; befreien = Fesseln oder Knebel lösen. Bestätige nur, "
    "wenn die Handlung diese Wirkung am Körper von 'ziel' JETZT tatsächlich ausführt. Eine Berührung ohne Verletzung (auch eine "
    "aufdringliche oder sexuelle) ist keine gewalt. Eine Drohung, Absicht, ein Versuch ohne Treffer, "
    "ein Blick, eine Haltung, liebevolles Festhalten oder eine Annäherung genügt nicht, ebenso wenig eine verneinte, angekündigte, "
    "erzählte oder nur zitierte Tat. Antwort NUR JSON: {\"bestaetigt\": true|false, \"zeit\": \"jetzt|vergangen|zukunft|moeglich\", "
    "\"ziel\": \"<Name der Figur, deren Körper es trifft>\"|null, \"beleg\": \"<wörtlicher Teil der Handlung, der genau diese Wirkung "
    "ausführt>\"|null, \"versuch\": true|false, \"gegen\": \"<wörtlich aus der Handlung>\"|null, "
    "\"beruehrung\": true|false, \"beruehrungBeleg\": \"<wörtlicher Teil der Handlung, der den Körper von ziel berührt>\"|null}. Ohne Beleg ist bestaetigt false. "
    "beruehrung = true nur, wenn bestaetigt false ist und die Handlung den Körper von 'ziel' JETZT berührt (auch aufdringlich oder "
    "sexuell), ohne die vorgeschlagene Wirkung auszuführen; sonst false. "
    "versuch = true, wenn die Handlung diese Wirkung JETZT versucht, sie aber nicht erreicht (verfehlt, abgewehrt, vergeblich). "
    "gegen = nur wenn bestätigt: die Fläche oder der Gegenstand außerhalb der Körper, an die oder an den 'ziel' dabei gedrückt oder "
    "festgehalten wird; ein Körperteil ist kein gegen; sonst null."
)

# V92 (Gegenpruefung 04.11.2026 Fall A; AMASTER §24.2 Kandidat -> Semantikanalyse -> Validierung -> Writer, §34.1 jede Komponente
# eigene Validierung, §24.7): "Johann kuesst Mara nicht." was bound as a performed act when the planner delivered the whole sentence as
# one act. Whether an act HAPPENS is read once more, alone, for every act component, WITHOUT the planner's own declaration (blind, like
# the appraisal reviewer): no word list, the reading decides from the utterance. The kernel only takes a reading that says it happens.
VOLLZUG_CHECK_RULES = (
    "Vollzug prüfen (AMASTER §24.2/§24.7): Gegeben ist EINE Handlungsbeschreibung ('handlung') und die ganze Äußerung, "
    "in der sie steht ('aeusserung'), die für die Figur 'figur' geschrieben ist. Entscheide allein aus dem Wortlaut der "
    "Äußerung, ob die Handlung in diesem Moment tatsächlich ausgeführt wird, wer sie ausführt und wen sie trifft. taeter = der Name "
    "der Person, die laut Äußerung die Handlung ausführt, wörtlich so, wie er in der Äußerung steht (nicht ergänzen, nicht kürzen, "
    "durch keinen anderen Namen ersetzen); steht kein Name als Täter da (Ich-Form, nur ein Pronomen oder ohne Subjekt), ist es 'figur'. "
    "ziel = der Eigenname der Person, die die Handlung trifft oder an die sie sich richtet, ebenso wörtlich, wie er in der Äußerung steht; "
    "steht für sie dort nur ein Pronomen (etwa sie, ihn, dich, dir) oder niemand, dann leer - ein Pronomen ist kein Name. art: tatsaechlich = die Äußerung sagt, dass 'akteur' es jetzt tut; verneint = sie sagt, dass es nicht "
    "geschieht oder nicht getan wird (auch wenn die Verneinung nicht in der Handlungsbeschreibung steht oder am Satzende steht); "
    "wunsch = nur gewünscht, gefordert oder erlaubt; frage = erfragt; bedingung = nur unter einer Bedingung; ankuendigung = erst später; "
    "erzaehlt = vergangen oder nur berichtet; zitat = nur zitiert. beleg = der wörtliche Teil der Äußerung, der die Art zeigt (bei "
    "verneint die Verneinung samt Verb), sonst null. Antwort NUR JSON: {\"geschieht\": true|false, \"art\": "
    "\"tatsaechlich|verneint|wunsch|frage|bedingung|ankuendigung|erzaehlt|zitat\", \"beleg\": string|null, \"taeter\": string, "
    "\"ziel\": string}. geschieht ist nur bei tatsaechlich true."
)


def vollzug_check(conn, actor: str, *, action: str, figur: str, aeusserung: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V92: does this act component really HAPPEN in its utterance (not denied, wished, asked, conditional, announced, told, quoted)?
    Blind to the planner's own `geschieht`. None without provider.
    V92 Paket 13 (Paket-12-Pruefung N1-N4; AMASTER §24.1, §24.7): a LITERAL witness - it gets no cast list, it names doer and
    target as the utterance writes them ("Mara Schmidt" stays "Mara Schmidt"); the kernel binds the names to figure IDs."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(action or "").strip():
        return None
    payload = {"handlung": str(action)[:400], "aeusserung": str(aeusserung or action)[:800], "figur": str(figur)}
    audit = provider_audit(conn, actor, data or {}, "vollzug_check") if conn is not None else None
    parsed = _llm_json(routing, VOLLZUG_CHECK_RULES, payload, temperature=0.0, max_tokens=160, timeout=30, audit=audit, attempts=1)
    # an answer without the two decisive fields is no reading (the declaration of the planner then stands alone)
    # (V92 Paket-5-Pruefung: also the named doer - `taeter` - is mandatory; an incomplete answer is no reading and the kernel
    # then reports `vollzug_nicht_geprueft` instead of letting the act pass)
    if (isinstance(parsed, dict) and isinstance(parsed.get("geschieht"), bool) and isinstance(parsed.get("art"), str)
            and isinstance(parsed.get("taeter"), str) and parsed["taeter"].strip()):
        return parsed
    return None


# P22: the first planner can confuse narrated action with audible Puppet speech
# ("Johann gibt Mara Nowak Brot." became a speech fact).  A *second* model
# reading is requested ONLY for structural candidates (an actor name at the
# start of the proposed speech, or a purported other speaker). The kernel
# checks its literal quote, source positions and bound actor before it can
# change the proposed type. A converted act still requires vollzug_check,
# and its body effect still requires the independent effect checker.
KOMPONENTENART_CHECK_RULES = (
    "Rede oder eigene Handlung einer gesteuerten Figur (AMASTER §27.4/§24.2/§34.1): "
    "Gegeben ist die Eingabe 'aeusserung', das wörtliche Segment 'segment', "
    "und die vom Benutzer gesteuerte Figur 'figur'. Entscheide ausschließlich "
    "was das Segment dieser Figur jetzt TATSÄCHLICH zuschreibt: "
    "rede = ihre LAUT GESPROCHENEN eigenen Wörter (auch Anrede/Befehl an jemanden), "
    "handlung = ihre als Handlung dargestellte gegenwärtige Tat, NICHT laut gesprochene Wörter; "
    "unklar = die Art ist nicht sicher. Ein Satz 'Johann gibt Mara Brot' beschreibt "
    "eine Handlung, er ist keine von Johann gesprochene Rede. Ein Satz "
    "'Herr Pfeiffer, setzen Sie sich' ist an Herrn Pfeiffer gerichtete Rede der geführten Figur, "
    "nicht von Herrn Pfeiffer gesprochene Rede. Behauptungen über ANDERE handelnde "
    "Figuren sind nicht die eigene Tat der gesteuerten Figur. "
    "Bei handlung: wirkung genau aus 'zaertlich|gewalt|fesseln|befreien|ortswechsel|annaeherung|entfernung|ohne_koerperwirkung', "
    "nur wenn sie im Segment getragen ist. beleg = eine wörtliche, zusammenhängende Stelle "
    "aus SEGMENT, die die Unterscheidung trägt, keine erfindenden Zusätze. "
    "Antwort NUR JSON: {\"art\":\"rede|handlung|unklar\",\"beleg\":string|null,"
    "\"wirkung\":string|null}."
)


def komponentenart_check(conn, actor: str, *, aeusserung: str, segment: str, figur: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(segment or "").strip():
        return None
    payload = {"aeusserung": str(aeusserung or "")[:800], "segment": str(segment)[:400], "figur": str(figur)[:80]}
    audit = provider_audit(conn, actor, data or {}, "komponentenart_check") if conn is not None else None
    return _llm_json(routing, KOMPONENTENART_CHECK_RULES, payload, temperature=0.0, max_tokens=120,
                     timeout=12, audit=audit, attempts=1)


# V92 Paket 12 (Paket-11-Pruefung "Mara sagt zu Johann: Lass mich in Ruhe!" with the reading's speaker Johann; AMASTER §24.1,
# §27.3/§27.4, §34.1): when the announcement of a speech names several figures, its form cannot tell the speaker from the
# person spoken to. This small blind reading names the speaker; the kernel binds the name to the figure ID and decides.
SPRECHER_CHECK_RULES = (
    "Sprecher prüfen (AMASTER §24.1, §27.3/§27.4, §34.1): Gegeben sind wörtliche Worte ('worte'), die Äußerung, in der sie stehen "
    "('aeusserung'), und die geführte Figur ('figur'). Bestimme, WER diese Worte laut Äußerung sagt - nur die sprechende Person, nicht "
    "die, zu der oder über die gesprochen wird. sprecher = der Name der sprechenden Person, wörtlich so, wie er in der Äußerung steht "
    "(nicht ergänzen, nicht kürzen, durch keinen anderen Namen ersetzen); steht kein Name da (Ich-Form, nur ein Pronomen oder kein "
    "Sprecher), dann 'figur'. beleg = der wörtliche Teil der Äußerung, der den Sprecher zeigt, sonst null. "
    "'ansage' (falls gegeben) ist der Satzteil, der die Worte ankündigt. handlung = der wörtliche Teil von 'ansage', der eine EIGENE "
    "Handlung der sprechenden Person neben dem Sprechen beschreibt (etwa 'Johann lächelt' in 'Johann lächelt und sagt'); sie endet VOR "
    "dem Bindewort und dem Sprechverb - das Sprechverb (sagt, flüstert, brüllt, ruft …) gehört nie zur handlung. Beschreibt 'ansage' "
    "nur das Sprechen selbst, auch mit Art und Weise oder Adressat ('sagt leise', 'flüstert ihr zu', 'sagt zu Mara'), dann null. "
    "adressat = der Name der Person, zu der oder an die die Worte laut Äußerung gesprochen werden, wörtlich und vollständig so, wie er "
    "in der Äußerung steht (nicht ergänzen, nicht kürzen); steht dafür kein Name da (nur ein Pronomen oder niemand), null. "
    "Unterscheide bei einer 'ansage' ausdrücklich ANREDE (genannte Person wird angesprochen, nicht als Sprecher angekündigt) "
    "von SPRECHERANSAGE (genannte Person spricht die nachfolgenden Worte). "
    "Gib ansageRolle = 'anrede' | 'sprecheransage' | 'unklar' und ansageBeleg = exakter Ausschnitt aus der ansage, "
    "der die Zuordnung belegt; ohne sicheren beleg ansageRolle=unklar. Bei einer Anrede ist der genannte Name ADRESSAT, "
    "nicht Sprecher. Keine Namen erfinden, auch nicht aus der geführten Figur. "
    "Antwort NUR JSON: {\"sprecher\": string, \"beleg\": string|null, \"handlung\": string|null, \"adressat\": string|null, "
    "\"ansageRolle\": \"anrede|sprecheransage|unklar\", \"ansageBeleg\": string|null}."
)


def sprecher_check(conn, actor: str, *, worte: str, figur: str, aeusserung: str, ansage: str | None = None, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V92 Paket 12: who says these words according to the utterance. None without provider or without a named speaker.
    V92 Paket 13: a literal witness like vollzug_check - no cast list, the name as the utterance writes it; with the announcement
    (`ansage`, the planner's `einleitung`) it also names an OWN act the announcement holds besides the speaking (`handlung`)."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(worte or "").strip():
        return None
    payload = {"worte": str(worte)[:400], "aeusserung": str(aeusserung or worte)[:800], "figur": str(figur)}
    if str(ansage or "").strip():
        payload["ansage"] = str(ansage)[:300]
    audit = provider_audit(conn, actor, data or {}, "sprecher_check") if conn is not None else None
    parsed = _llm_json(routing, SPRECHER_CHECK_RULES, payload, temperature=0.0, max_tokens=120, timeout=30, audit=audit, attempts=1)
    if isinstance(parsed, dict) and isinstance(parsed.get("sprecher"), str) and parsed["sprecher"].strip():
        return parsed
    return None


# V65P (AMASTER §24.2 Validierung vor dem Writer, §43.1 Outcome, §43.2 SpatialState;
# your session ses_57d5 and the V65P route run T8/T9): a figure's reply proposed
# "entfernung" for "Mara drückt sich gegen die Mauer …" and the room went to
# "auf Abstand" although nobody moved. The two movement classes change the spatial
# state between two figures like the body classes change a body; they get the SAME
# reading step (same schema, same kernel check apply_effect_check). Class
# definitions verbatim from PLAN_RULES/REGIE_RULES; EFFECT_CHECK_RULES above is
# unchanged. Probe before the build (move_probe, T=0, 2 runs): 0/20 false
# positive (pressing against the wall, crossed arms, wish, announced, negated,
# attempt blocked by the wall, stare, smile), 1/18 false negative.
MOVE_CHECK_RULES = (
    "Raumwirkung prüfen (AMASTER §24.2/§24.7, §43.1): Gegeben ist EINE Handlung ('handlung', Täter 'akteur'), die Äußerung, in der sie steht "
    "('aeusserung'), und eine vorgeschlagene Raumwirkung zwischen 'akteur' und 'ziel' ('vorschlag'). annaeherung = sich jemandem nähern, "
    "näher rücken, sich zu jemandem lehnen; entfernung = von jemandem abrücken, Abstand nehmen. Bestätige nur, wenn die Handlung diese "
    "Raumwirkung JETZT tatsächlich ausführt, sodass sich der Abstand zwischen 'akteur' und 'ziel' wirklich ändert. Ein Wunsch, eine Absicht, "
    "ein Versuch, der den Abstand nicht ändert, ein Blick, eine Haltung oder Geste, ebenso eine verneinte, angekündigte, erzählte oder nur "
    "zitierte Handlung genügt nicht. Antwort NUR JSON: {\"bestaetigt\": true|false, \"zeit\": \"jetzt|vergangen|zukunft|moeglich\", "
    "\"ziel\": \"<Name der Figur, zu der sich der Abstand ändert>\"|null, \"beleg\": \"<wörtlicher Teil der Handlung, der genau diese "
    "Raumwirkung ausführt>\"|null}. Ohne Beleg ist bestaetigt false."
)

# V65Q (AMASTER §43.1 Outcome attempted; Pruefung v2.8 P-03): the room check for a
# movement it has NOT confirmed, asked once more with the field "versuch" - only
# then, so the confirming text above stays byte-identical. Measured 29.10.: the
# same field inside MOVE_CHECK_RULES shifted its confirmations (false negative on
# the V65P cases 5/40 -> 9/40); as this follow-up the attempt is read 24/24.
MOVE_ATTEMPT_RULES = (
    "Raumwirkung prüfen (AMASTER §24.2/§24.7, §43.1): Gegeben ist EINE Handlung ('handlung', Täter 'akteur'), die Äußerung, in der sie steht "
    "('aeusserung'), und eine vorgeschlagene Raumwirkung zwischen 'akteur' und 'ziel' ('vorschlag'). annaeherung = sich jemandem nähern, "
    "näher rücken, sich zu jemandem lehnen; entfernung = von jemandem abrücken, Abstand nehmen. Bestätige nur, wenn die Handlung diese "
    "Raumwirkung JETZT tatsächlich ausführt, sodass sich der Abstand zwischen 'akteur' und 'ziel' wirklich ändert. Ein Wunsch, eine Absicht, "
    "ein Versuch, der den Abstand nicht ändert, ein Blick, eine Haltung oder Geste, ebenso eine verneinte, angekündigte, erzählte oder nur "
    "zitierte Handlung genügt nicht. Antwort NUR JSON: {\"bestaetigt\": true|false, \"zeit\": \"jetzt|vergangen|zukunft|moeglich\", "
    "\"ziel\": \"<Name der Figur, zu der sich der Abstand ändert>\"|null, \"beleg\": \"<wörtlicher Teil der Handlung, der genau diese "
    "Raumwirkung ausführt>\"|null, \"versuch\": true|false}. Ohne Beleg ist bestaetigt false. versuch = true, wenn die Handlung diese "
    "Raumwirkung JETZT versucht, sie aber nicht erreicht (verhindert, vergeblich, nur ansatzweise)."
)
_MOVE_CLASSES = ("entfernung", "annaeherung", "annäherung")


def effect_check(conn, actor: str, *, action: str, akteur: str, ziel: str, vorschlag: str, aeusserung: str | None = None,
                 data: dict[str, Any] | None = None, attempt: bool = False) -> dict[str, Any] | None:
    """V65I/V65J: does THIS action, in its utterance, do the proposed body effect to 'ziel' now? None without provider.
    V65P: a proposed movement class (entfernung/annaeherung) is read with MOVE_CHECK_RULES, same schema.
    V65Q: attempt=True asks the follow-up MOVE_ATTEMPT_RULES (only for an unconfirmed movement done now)."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(action or "").strip() or not str(vorschlag or "").strip():
        return None
    payload = {"handlung": str(action)[:400], "aeusserung": str(aeusserung or action)[:800], "akteur": str(akteur),
               "ziel": str(ziel or ""), "vorschlag": str(vorschlag)}
    _move = str(vorschlag).strip().lower() in _MOVE_CLASSES
    if attempt and not _move:
        return None   # V65Q: the body check already carries "versuch" (no follow-up)
    purpose = ("move_attempt" if attempt else "move_check") if _move else "effect_check"
    rules = (MOVE_ATTEMPT_RULES if attempt else MOVE_CHECK_RULES) if _move else EFFECT_CHECK_RULES
    audit = provider_audit(conn, actor, data or {}, purpose) if conn is not None else None
    parsed = _llm_json(routing, rules, payload, temperature=0.0, max_tokens=220, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


# A rejected violent effect can still be real, unwanted contact. The initial
# model's optional "beruehrung" flag is NOT a second independent authority.
TOUCH_CONFIRM_RULES = (
    "Unabhängige Berührungsprüfung (AMASTER §24.2, §36.5): Prüfe ausschließlich, ob "
    "die Handlung JETZT den KÖRPER von 'ziel' tatsächlich berührt. Das Zusammenballen "
    "der eigenen Hände, Annäherung, Drohung, Blick, Bewegung neben einer Person, "
    "Absicht, Versuch ohne Kontakt, berichtete oder negierte Berührung sind NEIN. "
    "Antworte NUR JSON: {\"beruehrt\": true|false, \"zeit\": \"jetzt|vergangen|zukunft|moeglich\", "
    "\"ziel\": \"<Figurenname>\"|null, \"beleg\": \"<wörtlicher Ausschnitt, der den Körperkontakt tatsächlich vollzieht>\"|null}. "
    "Keine Berührung ohne nachgewiesene Textstelle."
)


def touch_confirmation_check(conn, actor: str, *, action: str, akteur: str, ziel: str,
                             data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Only when a first failed violence/fetter-effect proposes actual touch.
    One bounded second reading, no write and no retry. If unavailable: no contact.
    """
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(action or "").strip() or not str(ziel or "").strip():
        return None
    payload = {"handlung": str(action)[:400], "akteur": str(akteur)[:80], "ziel": str(ziel)[:80]}
    audit = provider_audit(conn, actor, data or {}, "touch_confirmation") if conn is not None else None
    r = _llm_json(routing, TOUCH_CONFIRM_RULES, payload, temperature=0.0, max_tokens=130, timeout=12,
                  audit=audit, attempts=1)
    return r if isinstance(r, dict) else None


# V65V (AMASTER §36.5 Z. 1947-1975 Einwilligung an Handlung, Scope und Gueltigkeitsfenster gebunden, §24.2 Z. 1110-1113
# Kandidat -> Semantik -> Validierung, §24.7; Nachpruefung v1 K1/K4): the SCOPE of a boundary a reading proposed beyond its
# act is read once more, alone, from its own words - the same pattern as EFFECT_CHECK_RULES (a separate reading confirms a
# proposed effect with a literal quote before any writer). Action scope and duration are separate axes: a word for the
# duration is no proof that EVERY touch is meant. Only for a proposed "jede_beruehrung" (rare); the kernel validates.
GRENZE_CHECK_RULES = (
    "Einwilligungsumfang prüfen (AMASTER §36.5, §24.2/§24.7): Gegeben ist die Äußerung einer Figur ('aeusserung') und darin die Worte "
    "('beleg'), mit denen sie Körperkontakt durch 'person' ablehnt oder erlaubt. Zerlege den Beleg: gegenstand = genau die Worte des "
    "Belegs, die bezeichnen, WAS nicht berührt werden darf bzw. berührt werden darf - die sprechende Figur selbst, eine Stelle "
    "ihres Körpers, eine Art der Berührung oder die Handlung selbst; nie 'person', die berührt; gegenstand_art: person = die sprechende "
    "Figur selbst als Ganze (dann gilt es für jede Berührung durch 'person'); koerperstelle_oder_art = nur eine Körperstelle, eine Art "
    "oder eine Weise der Berührung; diese_handlung = nur die gerade geschehene oder angefragte Handlung, auch wenn sie nur mit einem "
    "Fürwort für eine Sache bezeichnet ist. geltung: offen = der Beleg sagt ausdrücklich, dass es von jetzt an dauerhaft gilt; zeitraum = er nennt einen Zeitraum; "
    "nicht_genannt = er sagt nichts über die Dauer; geltung_beleg = genau die Worte dafür, sonst null. "
    "richtung: verboten = der Beleg verbietet die Berührung des gegenstand; erlaubt = er erlaubt genau die Berührung des gegenstand. "
    "Antwort NUR JSON: "
    "{\"gegenstand\": string|null, \"gegenstand_art\": \"person|koerperstelle_oder_art|diese_handlung\", "
    "\"richtung\": \"verboten|erlaubt\", \"geltung\": \"offen|zeitraum|nicht_genannt\", \"geltung_beleg\": string|null}."
)

# V65V (AMASTER §36.3 Z. 1937, §36.4 Z. 1941 "Widerspruch erzeugt neue Evidenz", §34.1 Z. 1807-1815, §24.7; Nachpruefung v1
# K3): a statement component the formulation labelled as denying an event is read once more, alone, against the events it
# cites. Only for a proposed "bestreitet_geschehen"; truth.register_denial runs only when both readings agree (kernel).
# V65W (Tiefenpruefung v1 P04/C5 "den tatsaechlichen Negationsbezug am Ereignis validieren", "LLM-Selbstlabels doppelt
# abzufragen ergibt keine Faktenquelle"): the V65V decomposition above stays byte-identical (measured 17/18; two variants
# measured 30.10. that changed it gave 8/36 and 5/36 false contradictions, see scripts/v65w_gegenproben). When it reads an
# event as denied, ONE follow-up per such event asks a different question at the event itself - does the segment say that
# exactly this act did not take place, and with which words of the segment and which words of the act's own recorded
# wording? (the pattern of MOVE_ATTEMPT_RULES: a follow-up keeps the first reading unchanged). The kernel binds an event
# only with this answer and both literal anchors.
AUSSAGE_CHECK_RULES = (
    "Aussage prüfen (AMASTER §36.3/§36.4, §24.7): Gegeben ist ein Teil der Rede einer Figur ('segment', Sprecherin 'sprecher') und "
    "Ereignisse, die sie selbst erlebt, gesehen oder getan hat ('ereignisse', je mit Kennung). Zerlege den Teil: verneint = genau die "
    "verneinte Aussage des Teils als Wortgruppe mit ihrem Verb, oder null; gegenstand = WAS verneint wird: geschehen = dass die Handlung "
    "des Ereignisses selbst stattgefunden hat oder getan wurde; bewertung = ein Urteil über die Handlung - auch wenn sie dabei mit einem "
    "anderen, wertenden Wort benannt wird (wie schlimm, wie gemeint, wie sie zu nennen ist); "
    "gefuehl = das eigene Erleben oder Empfinden der Sprecherin; anderes = sonst (etwa ein Wunsch oder eine Weigerung). bestritten = die Kennungen der Ereignisse, deren "
    "Stattfinden verneint wird - nur bei gegenstand geschehen, sonst []. Antwort NUR JSON: {\"verneint\": string|null, "
    "\"gegenstand\": \"geschehen|bewertung|gefuehl|anderes\", \"bestritten\": [string]}."
)


AUSSAGE_TAT_RULES = (
    "Tatbezug einer Verneinung prüfen (AMASTER §36.4, §24.7): Gegeben ist ein Teil der Rede einer Figur ('segment', Sprecherin "
    "'sprecher') und EIN Ereignis ('ereignis': Täter und Wortlaut der Handlung). Sagt der Teil ausdrücklich, dass genau diese Handlung "
    "nicht stattgefunden hat oder nicht getan wurde? Ein Urteil über die Handlung, ein Gefühl, ein Wunsch, eine Weigerung oder eine "
    "Bestätigung ist das nicht. Antwort NUR JSON: {\"bestreitet\": true|false, \"verneint\": \"<die verneinende Wortgruppe des Teils, "
    "wörtlich>\"|null, \"tat\": \"<die Wörter aus dem Wortlaut der Handlung im ereignis (nicht aus dem Teil), deren Geschehen verneint "
    "wird, wörtlich>\"|null}. "
    "Ohne beide Belege ist bestreitet false."
)


# V65W (Tiefenpruefung v1 P03/C4; AMASTER §20 Z. 941/949 "den Uebergang zur naechsten Szene", "Eine Szene kann durch Nutzer,
# Regie, God, Fate oder den tatsaechlichen Verlauf wechseln", §24.6 Systemwortschatz ohne Wahrheitshoheit): whether an
# operator instruction (Regie, God) ends the running scene or begins a new one - also at the same place - is read once,
# alone. It replaces the words "neue Szene"/"Vorhang"/... that scene_state.external_delta matched before V65W. +1 call per
# Regie/God input; the kernel keeps it only with a literal quote.
# V65Y (Gesamtpruefung V65X N06): the scene transition reading (SZENENUEBERGANG_RULES / scene_transition, V65W-V65X) is
# removed - a scene transition is bound only by the director's explicit choice (app._scene_transition_read).


# V65W (Tiefenpruefung v1 P06/C1; AMASTER §36.5 Z. 1953-1956 Handlung + Scope, §24.2 Z. 1110-1113, §24.7): a RESTRICTED
# boundary ("nicht auf die Schulter") is kept with its own words; whether a LATER act touches exactly that restriction is
# read once, alone, from the act - the same pattern as EFFECT_CHECK_RULES (a separate reading confirms with a literal quote
# before the writer). Only for a body act of the toucher while such a boundary of the touched figure stands (rare).
GRENZBEZUG_CHECK_RULES = (
    "Grenzbezug prüfen (AMASTER §36.5, §24.2/§24.7): Gegeben ist EINE Handlung ('handlung', Täter 'akteur'), die Äußerung, in der sie "
    "steht ('aeusserung'), und eine Grenze, die 'ziel' vorher gegenüber 'akteur' gesetzt hat ('grenze', wörtlich), mit dem, was sie "
    "verbietet ('verboten': eine Stelle ihres Körpers oder eine Art oder Weise der Berührung, wörtlich). Berührt die Handlung den Körper "
    "von 'ziel' JETZT genau an dieser Stelle bzw. genau auf diese Art oder Weise? Eine andere Körperstelle, eine andere Art der Berührung "
    "oder eine Handlung an einer anderen Person genügt nicht, ebenso wenig eine verneinte, angekündigte, erzählte oder nur zitierte "
    "Handlung. Nennt die Handlung keine Körperstelle, berührt sie keine bestimmte Stelle. Antwort NUR JSON: {\"betroffen\": true|false, "
    "\"beleg\": \"<wörtlicher Teil der Handlung, der genau das Verbotene tut>\"|null}. Ohne Beleg ist betroffen false."
)


# V65W (Tiefenpruefung v1 Punkt 9 / C7; AMASTER §36.1 Request bindet angefragte Handlung, §36.3, §36.5 Z. 1947 Zustimmung an
# die betreffende Handlung gebunden): the requester's OWN later act is bound to his request that the recipient accepted only
# when it IS the requested act. Read once, alone, from the act and the request's wording - only while such an accepted,
# not yet carried out request of exactly this actor to exactly this person exists (rare).
BITTEBEZUG_CHECK_RULES = (
    "Bitte prüfen (AMASTER §36.1/§36.3/§36.5, §24.2/§24.7): Gegeben ist EINE Handlung ('handlung', Täter 'akteur', an 'ziel'), die "
    "Äußerung, in der sie steht ('aeusserung'), und eine Bitte, die 'akteur' vorher an 'ziel' gerichtet hat und der 'ziel' zugestimmt "
    "hat ('bitte', Wortlaut). Zerlege die Handlung in ihre einzelnen Teilhandlungen, die sie JETZT an 'ziel' tut, je wörtlich aus der "
    "Handlung; die Teile zusammen enthalten die ganze Handlung, kein Teil wird ausgelassen. erbeten = true nur für eine "
    "Teilhandlung, die genau das ist, worum gebeten wurde. Eine verneinte, angekündigte, "
    "erzählte oder nur zitierte Handlung ist keine Teilhandlung. Antwort NUR JSON: {\"teile\": [{\"wortlaut\": string, "
    "\"erbeten\": true|false}]}."
)


# V65Y (Gesamtpruefung V65X N05; AMASTER §34.1 Komponenten getrennt bewerten, §36.5 Z. 1947 Zustimmung an die betreffende
# Handlung gebunden, §24.2/§24.7): an act that names a part the touched figure permitted (or took back) while her boundary
# for every touch stands, or that names her standing restricted permission, is split into its parts - read once, alone,
# from the act and the permission's wording; the kernel then checks literal parts, the whole act and the part's anchor.
# Only for a body act that names such a part (rare).
ERLAUBNISBEZUG_CHECK_RULES = (
    "Erlaubnis prüfen (AMASTER §34.1/§36.5, §24.2/§24.7): Gegeben ist EINE Handlung ('handlung', Täter 'akteur', an 'ziel'), "
    "die Äußerung, in der sie steht ('aeusserung'), und eine Erlaubnis, die 'ziel' vorher 'akteur' gegeben hat ('erlaubnis', "
    "wörtlich), mit dem, was erlaubt ist ('erlaubt': eine Stelle ihres Körpers oder eine Art der Berührung, wörtlich, aus der "
    "Sicht von 'ziel' gesagt - 'meine' meint dort den Körper von 'ziel'). Zerlege "
    "die Handlung in ihre einzelnen Teilhandlungen, die sie JETZT an 'ziel' tut, je wörtlich aus der Handlung; die Teile "
    "zusammen enthalten die ganze Handlung, kein Teil wird ausgelassen. innerhalb = true nur für eine Teilhandlung, die genau "
    "das Erlaubte tut und nichts anderes; ist eine Körperstelle erlaubt, dann nur, wenn die Teilhandlung genau diese Stelle am "
    "Körper von 'ziel' berührt - eine Stelle des eigenen Körpers von 'akteur' ist nicht die erlaubte Stelle. Eine verneinte, "
    "angekündigte, erzählte oder nur zitierte Handlung ist keine "
    "Teilhandlung. Antwort NUR JSON: {\"teile\": [{\"wortlaut\": string, \"innerhalb\": true|false}]}."
)


def permission_reference_check(conn, actor: str, *, handlung: str, aeusserung: str | None, erlaubnis: str, erlaubt: str,
                               akteur: str, ziel: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65Y: which parts of THIS act stay inside the permission (ERLAUBNISBEZUG_CHECK_RULES)? None without provider."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(handlung or "").strip() or not str(erlaubt or "").strip():
        return None
    payload = {"handlung": str(handlung)[:400], "aeusserung": str(aeusserung or handlung)[:800], "akteur": str(akteur or "")[:80],
               "ziel": str(ziel or "")[:80], "erlaubnis": str(erlaubnis or erlaubt)[:240], "erlaubt": str(erlaubt)[:160]}
    audit = provider_audit(conn, actor, data or {}, "permission_reference_check") if conn is not None else None
    parsed = _llm_json(routing, ERLAUBNISBEZUG_CHECK_RULES, payload, temperature=0.0, max_tokens=160, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


def request_reference_check(conn, actor: str, *, handlung: str, aeusserung: str | None, bitte: str, akteur: str, ziel: str,
                            data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65W: is THIS act exactly the act of the accepted request (BITTEBEZUG_CHECK_RULES)? None without provider."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(handlung or "").strip() or not str(bitte or "").strip():
        return None
    payload = {"handlung": str(handlung)[:400], "aeusserung": str(aeusserung or handlung)[:800], "akteur": str(akteur or "")[:80],
               "ziel": str(ziel or "")[:80], "bitte": str(bitte)[:300]}
    audit = provider_audit(conn, actor, data or {}, "request_reference_check") if conn is not None else None
    parsed = _llm_json(routing, BITTEBEZUG_CHECK_RULES, payload, temperature=0.0, max_tokens=120, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


def boundary_reference_check(conn, actor: str, *, handlung: str, aeusserung: str | None, grenze: str, verboten: str, akteur: str,
                             ziel: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65W: does THIS act touch exactly what a restricted boundary forbids (GRENZBEZUG_CHECK_RULES)? None without provider."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(handlung or "").strip() or not str(verboten or "").strip():
        return None
    payload = {"handlung": str(handlung)[:400], "aeusserung": str(aeusserung or handlung)[:800], "akteur": str(akteur or "")[:80],
               "ziel": str(ziel or "")[:80], "grenze": str(grenze or "")[:240], "verboten": str(verboten)[:160]}
    audit = provider_audit(conn, actor, data or {}, "boundary_reference_check") if conn is not None else None
    parsed = _llm_json(routing, GRENZBEZUG_CHECK_RULES, payload, temperature=0.0, max_tokens=120, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


def consent_check(conn, actor: str, *, aeusserung: str, beleg: str, person: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65V: the scope of a proposed boundary (GRENZE_CHECK_RULES). None without provider."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(beleg or "").strip():
        return None
    payload = {"aeusserung": str(aeusserung or beleg)[:800], "beleg": str(beleg)[:240], "person": str(person or "")[:80]}
    audit = provider_audit(conn, actor, data or {}, "consent_check") if conn is not None else None
    parsed = _llm_json(routing, GRENZE_CHECK_RULES, payload, temperature=0.0, max_tokens=160, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


def statement_act_check(conn, actor: str, *, segment: str, sprecher: str, ereignis: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65W: the follow-up at ONE event the decomposition read as denied (AUSSAGE_TAT_RULES). None without provider."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(segment or "").strip() or not str(ereignis or "").strip():
        return None
    payload = {"segment": str(segment)[:400], "sprecher": str(sprecher or "")[:80], "ereignis": str(ereignis)[:240]}
    audit = provider_audit(conn, actor, data or {}, "statement_act_check") if conn is not None else None
    parsed = _llm_json(routing, AUSSAGE_TAT_RULES, payload, temperature=0.0, max_tokens=160, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


def statement_check(conn, actor: str, *, segment: str, sprecher: str, ereignisse: list[str], data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65V: does a statement component deny that the cited events took place (AUSSAGE_CHECK_RULES)? None without provider."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(segment or "").strip() or not ereignisse:
        return None
    payload = {"segment": str(segment)[:400], "sprecher": str(sprecher or "")[:80], "ereignisse": [str(x)[:240] for x in ereignisse]}
    audit = provider_audit(conn, actor, data or {}, "statement_check") if conn is not None else None
    parsed = _llm_json(routing, AUSSAGE_CHECK_RULES, payload, temperature=0.0, max_tokens=160, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


# V65Q (AMASTER §42 Z. 2305 resolved_by, Z. 2315-2316 Intent -> Versuch -> tatsaechlich
# vollzogene Handlung; Pruefung v2.8 P-06): the appraisal may propose that a figure's
# earlier intent is done. HOW the intent is carried out (by speaking or by a bodily/
# spatial act) is read once, only then, from the intent text alone; the kernel then
# takes the evidence from canonical Facts and outcomes. Measured 29.10. before the
# build: a reading that also chose the act among her acts matched "Abstand schaffen"
# to "Lass das!" (4/24 wrong), so it never sees the acts.
INTENT_KIND_RULES = (
    "Absicht (AMASTER §42): Gegeben ist die Absicht einer Figur ('absicht'). Womit wird sie umgesetzt? Antwort NUR JSON: "
    "{\"art\": \"rede|handlung\"}. rede = indem sie etwas sagt, fragt, bittet oder mitteilt; handlung = durch ein körperliches "
    "oder räumliches Tun."
)


def intent_kind(conn, actor: str, *, absicht: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65Q: how an intent is carried out (INTENT_KIND_RULES). None without provider."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(absicht or "").strip():
        return None
    audit = provider_audit(conn, actor, data or {}, "intent_kind") if conn is not None else None
    parsed = _llm_json(routing, INTENT_KIND_RULES, {"absicht": str(absicht)[:200]}, temperature=0.0, max_tokens=40,
                       timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


# V65J (AMASTER §46.1 God setzt Current State, §43 PhysicalState, §24.2/§24.6 kein Wort
# allein als Writer-Auslöser; Prüfbericht v2.2 E08/E19): a God fact about a figure's body
# is read once, alone, into the typed body state it sets. Before, word lists decided:
# "kann kaum gehen" left mobility unchanged, "ist nicht verletzt" added pain. Probe 28.10.
# (this exact text, 12 facts x 2): all typed as stated (kaum gehen -> stark_eingeschraenkt,
# nicht gehen -> unbeweglich, nicht verletzt -> schmerz kein), quote literal 24/24.
# V92 Paket 19 (unabhaengige Pruefung Paket 18 N5-N7 und die drei Regie-Wortfehler; AMASTER §46.1/§46.2, §43/§43.1, §24.2/§24.7):
# ONE typed reading for both authorities that set a body state - a God fact and a Regie order (part of an instruction) - with
# the same closed inventory the ONE body writer takes (kernel._BODY_VALUES). The former Regie word reading is gone; the God
# fields (pain/mobility levels, consciousness, restrained, gagged) are unchanged, healing/injury/position/sleep/sight/speech
# are added so that Regie keeps its former positive effects and God its healing. Expressing an existing state is no change.
GOD_BODY_RULES = (
    "Körperzustand durch die Spielleitung (AMASTER §46.1/§46.2/§43): Gegeben ist EIN Text der Spielleitung über die Figur 'figur' "
    "('text': eine God-Tatsache oder ein Teil einer Regie-Anweisung; 'kontext': die ganze Anweisung, falls vorhanden). Gib den "
    "Körperzustand von 'figur', den dieser Text JETZT festlegt oder herbeiführt. Nenne nur, was der Text selbst nennt, und ergänze "
    "keine Folgen (eine Verletzung bringt ihren Schmerz und ihre Einschränkung selbst mit); was er nicht nennt, ist null (nicht "
    "false); bleibt ein Zustand, wie er ist, ist das Feld null. "
    "schmerz: kein|leicht|mittel|stark. beweglichkeit: eingeschraenkt = bewegt sich langsamer oder unsicher; stark_eingeschraenkt = "
    "Bewegung nur mit großer Mühe; unbeweglich = Bewegung nicht möglich; frei = wieder uneingeschränkt. bewusstsein: wach|benommen|"
    "bewusstlos (eine Ohnmacht ist bewusstlos). gefesselt / geknebelt: true = wird jetzt gefesselt bzw. geknebelt, false = wird jetzt "
    "befreit bzw. der Knebel wird entfernt - nur, wenn der Text Fesseln bzw. Knebel selbst nennt; beweglichkeit nur, wenn er die "
    "Beweglichkeit selbst nennt. haltung: die Körperlage, die 'figur' jetzt einnimmt, nur wenn die Lage des ganzen "
    "Körpers wechselt (liegend, sitzend, kniend, stehend, kopfstand = Hand- oder Kopfstand). schlaf: einschlafen|aufwachen nur, wenn "
    "der Text echten Schlaf nennt (zu sich kommen oder wach werden aus einer Ohnmacht ist bewusstsein wach). sehen / sprechen: verliert = kann jetzt nicht mehr sehen bzw. sprechen, zurueck = kann es wieder. verletzung: nur bei "
    "einer neuen Verletzung {\"art\": \"<kurz, etwa gebrochen, verstaucht, Schnittwunde>\", \"glied\": \"<Körperteil>\"|null, "
    "\"seite\": \"links|rechts\"|null, \"schwer\": true|false}. heilung: true nur, wenn Verletzungen jetzt heilen. "
    "bereich: koerper = dieser Text legt einen körperlichen Zustand oder eine Körperänderung fest; "
    "nicht_koerper = es geht ausschließlich um andere, etwa soziale oder seelische Zustände; "
    "unklar = die Bedeutung ist ungewiss. Beurteile den Bereich unabhängig von den vorgeschlagenen Körperfeldern. "
    "Das bloße Zeigen oder Ausdrücken eines schon bestehenden Zustands (vor Schmerz keuchen oder stöhnen, sich eine Stelle halten) "
    "legt nichts fest. Eine verneinte Aussage legt das Gegenteil fest oder nichts; eine gewünschte, gefragte, angekündigte, "
    "erzählte oder nur zitierte Änderung legt nichts fest. Antwort NUR JSON: "
    '{"bereich": "koerper|nicht_koerper|unklar", "schmerz": "kein|leicht|mittel|stark"|null, "beweglichkeit": "frei|eingeschraenkt|stark_eingeschraenkt|unbeweglich"|null, '
    '"bewusstsein": "wach|benommen|bewusstlos"|null, "gefesselt": true|false|null, "geknebelt": true|false|null, '
    '"haltung": "liegend|sitzend|kniend|stehend|kopfstand"|null, "schlaf": "einschlafen|aufwachen"|null, '
    '"sehen": "verliert|zurueck"|null, "sprechen": "verliert|zurueck"|null, "verletzung": {...}|null, "heilung": true|null, '
    '"beleg": "<wörtlicher Teil des Textes, der diesen Zustand nennt>"|null}. Ohne Beleg ist alles null.'
)


# V92 Paket 19 (unabhaengige Pruefung Paket 18 N3/N4/N6: a wrong reading quoted "schläft nicht ein", "steht nicht auf", "keine
# Schmerzen" literally and the kernel took the quote as proof; AMASTER §43.1 "Handlungstext allein beweist noch keinen
# erfolgreichen Vollzug", §24.2 Kandidat -> Semantikanalyse -> Validierung -> Writer, §24.7): the second key of EVERY body change
# (figure, puppet, avatar, God, Regie) - one follow-up at the quoted place that asks a DIFFERENT question than the first reading:
# how does the text state exactly this change here (the modality taxonomy of VOLLZUG_CHECK_RULES), and is it the same thing? (the
# V65W pattern of AUSSAGE_TAT_RULES: a follow-up with its own literal anchor; "LLM-Selbstlabels doppelt abzufragen ergibt keine
# Faktenquelle"). One call per proposed field (+1..2 calls when a change is proposed). The kernel writes a field only on
# `tatsaechlich` + `gleich` with both literal anchors at the same place. No word list.
KOERPER_BESTAETIGUNG_RULES = (
    "Körperänderung bestätigen (AMASTER §43.1, §24.2/§24.7): Gegeben ist ein Text ('text': eine Handlung, eine Regie-Anweisung oder "
    "eine God-Tatsache), die Figur 'figur', eine Stelle aus diesem Text ('stelle') und EINE vorgeschlagene Veränderung am Körper von "
    "'figur' ('veraenderung', in festen Worten). Beantworte zwei Fragen allein aus dem Wortlaut des Textes. 1) art - wie sagt der "
    "Text an der Stelle DIESE Veränderung: tatsaechlich = er sagt selbst, dass genau sie jetzt wirklich eintritt oder jetzt gilt - "
    "auch wenn sie selbst ein kein oder nicht mehr enthält ('hat keine Schmerzen mehr' sagt 'hat jetzt keine Schmerzen'); verneint "
    "= er sagt, dass diese Veränderung nicht eintritt oder nicht gilt (auch wenn die Verneinung woanders im Satz steht); ausdruck = die Stelle sagt nur, was "
    "'figur' tut - einen Laut, eine Geste, eine Bewegung -, der einen Zustand zeigt (vor Schmerz keuchen, stöhnen oder wimmern, sich "
    "eine Stelle halten), und nicht selbst, dass der Zustand besteht oder eintritt: dann ist art ausdruck, nie tatsaechlich; wunsch = nur gewünscht, gefordert, befohlen oder erlaubt (auch "
    "eine Aufforderung an jemanden); frage = erfragt; bedingung = nur unter einer Bedingung (wenn, falls, sobald ... - auch wenn die "
    "Bedingung woanders im Satz steht; dann ist art bedingung, nie tatsaechlich); ankuendigung = erst später; erzaehlt = vergangen oder nur berichtet; zitat = nur zitiert oder in wörtlicher Rede gesagt. 2) inhalt - sagt die Stelle dasselbe wie 'veraenderung': gleich = ja, auch mit anderen oder genaueren "
    "Worten (Kopfschmerzen sind Schmerzen; sich kaum bewegen können ist Bewegung nur mit großer Mühe); anders = sie sagt etwas "
    "anderes, oder die Veränderung wäre nur eine Folge, die die Stelle selbst nicht nennt. beleg = IMMER die Wörter des Textes, die die Art zeigen, wörtlich aus 'text' (bei verneint die Verneinung samt Verb). "
    "Antwort NUR JSON: {\"art\": \"tatsaechlich|verneint|ausdruck|wunsch|frage|bedingung|ankuendigung|erzaehlt|zitat\", "
    "\"inhalt\": \"gleich|anders\", \"beleg\": string}."
)


# V92 Paket 18 (unabhaengige Pruefung Paket 17: "Mara keucht vor Schmerzen." -> pain 0.25 -> 0.40, "Mara wird nicht bewusstlos."
# -> bewusstlos und stumm; AMASTER §43.1 "Handlungstext allein beweist noch keinen erfolgreichen Vollzug ... Eine Handlung erzeugt
# nur die Folgen, die aus validiertem Vollzug, Intensitaet, Koerperlage, Weltphysik oder ausdruecklicher Authority getragen werden",
# §24.2 Kandidat -> Semantikanalyse -> Validierung -> Writer, §24.7): the change an act of a participant (figure reply, puppet,
# avatar) makes to the actor's OWN body is read once, alone, from its own words - the same pattern as EFFECT_CHECK_RULES and
# GOD_BODY_RULES (a separate reading names the change with a literal quote; the kernel validates it before the body writer). Only
# what one's own act itself does to one's own body: the body position taken now, falling asleep, waking up. Showing a state that
# already exists, a negated, wished, announced, told or quoted change is no change. No word list.
KOERPER_CHECK_RULES = (
    "Eigener Körperzustand (AMASTER §43/§43.1, §24.2/§24.7): Gegeben ist EINE Handlung ('handlung') der Figur 'figur' und die "
    "Äußerung, in der sie steht ('aeusserung'). Gib nur die Veränderung am EIGENEN Körper von 'figur', die diese Handlung JETZT "
    "tatsächlich ausführt; alles andere ist null. haltung = die Körperlage, die 'figur' durch die Handlung jetzt einnimmt, nur wenn "
    "die Handlung die Lage des ganzen Körpers wechselt (sich setzen, hinlegen, hinknien, aufstehen, hinfallen): liegend, sitzend, "
    "kniend, stehend (auch: aufstehen, sich aufrichten) oder kopfstand (Hand- oder Kopfstand); eine Bewegung einzelner Körperteile "
    "(Kopf, Arme, Hände, Augen, Oberkörper, Beine, Knie) wechselt die Körperlage nicht, und bleibt die Körperlage, wie sie ist, ist "
    "haltung null. schlaf = einschlafen oder aufwachen, wenn 'figur' jetzt in echten Schlaf "
    "fällt oder aus ihm aufwacht; eine Ohnmacht oder Bewusstlosigkeit ist kein schlaf. Nur Werte aus dieser Liste. "
    "Das Zeigen oder Ausdrücken eines schon bestehenden Zustands (vor Schmerz "
    "keuchen oder stöhnen, über Schmerzen klagen, sich eine Stelle halten, müde gähnen) ist keine Veränderung. Eine verneinte, "
    "gewünschte, gefragte, angekündigte, erzählte, vergangene oder nur zitierte Veränderung ist null. Antwort NUR JSON: "
    '{"haltung": "liegend|sitzend|kniend|stehend|kopfstand"|null, "schlaf": "einschlafen|aufwachen"|null, '
    '"zeit": "jetzt|vergangen|zukunft|moeglich", "beleg": "<wörtlicher Teil der Handlung, der genau diese Veränderung ausführt>"|null}. '
    "Ohne Beleg sind haltung und schlaf null."
)


def koerper_check(conn, actor: str, *, handlung: str, figur: str, aeusserung: str | None = None,
                  data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V92 Paket 18: which change of the actor's OWN body (position, falling asleep, waking up) does THIS act carry out now?
    None without provider or without an answer; the kernel validates (own_body_change)."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(handlung or "").strip():
        return None
    payload = {"handlung": str(handlung)[:400], "aeusserung": str(aeusserung or handlung)[:800], "figur": str(figur or "")}
    audit = provider_audit(conn, actor, data or {}, "koerper_check") if conn is not None else None
    parsed = _llm_json(routing, KOERPER_CHECK_RULES, payload, temperature=0.0, max_tokens=120, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


def god_body_state(conn, actor: str, *, text: str, figure: str, kontext: str | None = None, quelle: str = "god",
                   data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65J: typed body state one God body fact sets. V92 Paket 19: the same reading for a Regie order (`quelle` "regie",
    `text` = the ordered act's words, `kontext` = the whole instruction). None without provider; the kernel validates
    (authority_body_change)."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip():
        return None
    audit = provider_audit(conn, actor, data or {}, "god_body" if quelle != "regie" else "regie_body") if conn is not None else None
    payload = {"text": str(text)[:400], "figur": str(figure or "")}
    if kontext and str(kontext).strip() != str(text).strip():
        payload["kontext"] = str(kontext)[:800]
    # Stand 11 (SPS V62.7): die Bestaetigung der Koerperaenderung kommt in DERSELBEN Antwort (Lesung 'koerper_bestaetigung' an
    # der Belegstelle) - kein Folgeaufruf je Feld; der Kernel prueft sie unveraendert (body_change_validated).
    parsed = _llm_json(routing, GOD_BODY_RULES + GOD_KOERPER_PRUEFUNG_RULES, payload, temperature=0.0, max_tokens=700, timeout=30,
                       audit=audit, attempts=1, response_format=_strikt(routing, "koerperzustand", GOD_BODY_SCHEMA))
    if isinstance(parsed, dict):
        _kb = parsed.pop("bestaetigung", None)
        parsed.pop("lesungen", None)
        if isinstance(_kb, dict) and isinstance(parsed.get("beleg"), str) and parsed["beleg"].strip():
            vorab_registrieren([{"lesung": "koerper_bestaetigung", "zu": parsed["beleg"], "antwort": _kb}], quelle=quelle)
    return parsed if isinstance(parsed, dict) else None


def koerper_bestaetigung(conn, actor: str, *, text: str, figur: str, stelle: str, veraenderung: str,
                         data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V92 Paket 19: the confirmation reading of ONE proposed body change at its quoted place (KOERPER_BESTAETIGUNG_RULES).
    None without provider or answer (then the kernel writes nothing)."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip() or not str(stelle or "").strip():
        return None
    payload = {"text": str(text)[:800], "figur": str(figur or ""), "stelle": str(stelle)[:300], "veraenderung": str(veraenderung)[:300]}
    audit = provider_audit(conn, actor, data or {}, "koerper_bestaetigung") if conn is not None else None
    parsed = _llm_json(routing, KOERPER_BESTAETIGUNG_RULES, payload, temperature=0.0, max_tokens=120, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


# V65K (AMASTER §24.1 known_as "Name oder Bezeichnung in einem bestimmten Scope", §24.3 Domänen ALIAS/VOCABULARY,
# §24.6 Sessionwortschatz "darf seine lokale Bedeutung nicht still in andere Welten oder Sessions übertragen", §24.7;
# IST-Karte Wortliste v1.0 + Erwiderung 28.10.): what a participant establishes about NAMES and WORD MEANINGS in this
# session is read semantically - no word list. Measured 28.10.: as an extra field inside the input planner 20/32 (positives
# missing, other readings shifted); this separate reading (this exact text, 2 runs each, temperature 0): 16/16
# establishments found, 0 of 57 real inputs from your DB read as established; negation, quote and consideration come back
# with their own status, the kernel accepts only "festgelegt", checks quote/collision/binding and stores session-scoped.
LANGUAGE_RULES = (
    "Sprachfestlegung (AMASTER §24.1 known_as, §24.3 ALIAS/VOCABULARY, §24.6 Sessionwortschatz): Gegeben ist EINE Äußerung "
    "('aeusserung', Sprecher 'sprecher', angesprochen 'an', bekannte Personen 'personen'). Nenne jede Stelle, an der es darum geht, "
    "(a) wie eine Person genannt oder angesprochen wird (art name), oder (b) was ein Wort bedeutet oder wofür es steht (art bedeutung), "
    "und bestimme ihren status: festgelegt = der Sprecher legt es hier selbst ausdrücklich und ohne Einschränkung für ab jetzt fest; "
    "verneint = er will genau das NICHT ('nenn mich nicht so'); zitiert = er berichtet oder zitiert, was ein anderer sagt oder wie andere "
    "jemanden nennen; erwogen = Vermutung, Frage, Überlegung oder Wunsch ohne Festlegung; anrede = ein Wort wird hier nur im Gespräch "
    "als Anrede, Kosename oder Beschreibung benutzt ('Hey Schatz', 'Alles gut, Liebling', 'du bist eine tolle Frau'), ohne dass festgelegt "
    "wird, dass die Person ab jetzt so heißt. "
    "Form-Beispiel (anderes Thema): 'Bei uns heißt der Zug Blechschlange' -> art bedeutung, bezeichnung 'Blechschlange', bedeutung 'der Zug', status festgelegt. "
    'Antwort NUR JSON: {"stellen": [{"art": "name|bedeutung", "status": "festgelegt|verneint|zitiert|erwogen|anrede", '
    '"bezeichnung": "<nur der Name bzw. das Wort, ohne Artikel, WÖRTLICH>", '
    '"person": "<nur bei name: wer so heißt - ich (der Sprecher selbst, z. B. bei nenn mich / ich heiße), du (die Angesprochene) oder ein Name aus personen>", '
    '"bedeutung": "<nur bei bedeutung: die Erklärung, WÖRTLICH aus der Äußerung>", '
    '"beleg": "<die Stelle, WÖRTLICH kopiert>"}]}. Keine solche Stelle: {"stellen": []}.'
)


def language_reading(conn, actor: str, *, text: str, speaker_name: str, addressee_name: str | None, persons: list[str],
                     data: dict[str, Any] | None = None) -> list[dict[str, Any]] | None:
    """V65K: candidate name/meaning establishments of ONE utterance (§24.1/§24.6). None without provider.
    Only proposes; the kernel validates status, literal quote, quotation, binding and collision."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip():
        return None
    payload = {"aeusserung": str(text)[:600], "sprecher": str(speaker_name or ""), "an": str(addressee_name or ""),
               "personen": [str(x) for x in (persons or []) if str(x or "").strip()][:24]}
    audit = provider_audit(conn, actor, data or {}, "language_reading") if conn is not None else None
    parsed = _llm_json(routing, LANGUAGE_RULES, payload, temperature=0.0, max_tokens=300, timeout=30, audit=audit, attempts=1)
    if not isinstance(parsed, dict):
        return None
    rows = parsed.get("stellen")
    return [dict(x) for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []   # V65Z (A04)


def provider_reading_allowed(conn, actor: str, data: dict[str, Any] | None = None) -> bool:
    """V65J: whether a semantic reading can be asked at all (configured provider). Without one the
    documented local paths stay; with one, a failed reading is unclear, never a word-list guess."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    return bool(_routing(data or {}, cfg).get("allowed"))


def goal_frames(conn, actor: str, *, figure: str, persons: list[str], goals: list[dict], data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65H: one call per figure for her goals without a current frame. None without provider/goals."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not goals:
        return None
    payload = {"figur": str(figure), "personen": [str(p) for p in persons][:24],
               "ziele": [f"[{g.get('id')}] {str(g.get('text') or '')[:240]}" for g in goals if isinstance(g, dict)][:8]}
    audit = provider_audit(conn, actor, data or {}, "goal_frame") if conn is not None else None
    parsed = _llm_json(routing, GOAL_FRAME_RULES, payload, temperature=0.0, max_tokens=500, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


def goal_theme_check(conn, actor: str, *, text: str, speaker: str, figure: str, unsaid: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65H: does THIS input address exactly the still unsaid content? None without provider."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip() or not str(unsaid or "").strip():
        return None
    payload = {"aeusserung": str(text)[:600], "von": str(speaker), "an": str(figure), "ungesagt": str(unsaid)[:240]}
    audit = provider_audit(conn, actor, data or {}, "goal_theme") if conn is not None else None
    parsed = _llm_json(routing, GOAL_THEME_RULES, payload, temperature=0.0, max_tokens=120, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


# V65L (AMASTER §25, §34 Antwortbezug, §34.1, §24.8 DISCOURSE_ACT; Kettenvertrag §6.5): only used when the kernel has
# already found STRUCTURALLY that his input answers her line of an exchange bound to her unsaid goal part
# (kernel.answer_continuation). The reading says only whether he answers the theme part of her line, with both quotes.
# Measured on the unchanged V65K state (plan65l/antwortbezug_probe, this exact text, T=0, 3 runs, 16 cases):
# false positive 0 of 24 (Liebeserklärung, Tag, Abend, Kuss, Hunger, Umarmung, answer to her other question),
# false negative 3 of 21 ("Nein, ich glaube, noch nicht" read as own content -> no binding, as V65K).
ANSWER_REFERENCE_RULES = (
    "Antwortbezug (AMASTER §25, §34.1, §24.8): 'ihre_zeile' ist, was 'an' gerade zu 'von' gesagt hat; 'aeusserung' ist, was 'von' "
    "unmittelbar darauf sagt oder tut. 'ungesagt' ist ein Sachverhalt, den 'von' noch nicht kennt; er nennt nur das Thema dieses "
    "Gesprächs. Prüfe: Antwortet die Äußerung inhaltlich auf den Teil von 'ihre_zeile', der dieses Thema betrifft - stimmt sie zu, "
    "lehnt sie ab, fragt sie dazu nach oder fordert sie auf, mehr darüber zu sagen? Bringt die Äußerung stattdessen etwas Eigenes "
    "(ein anderes Thema, einen Gruß, eine Liebeserklärung, eine Zärtlichkeit, eine Handlung ohne diesen Bezug) oder antwortet sie "
    "auf einen anderen Teil von 'ihre_zeile', ist antwortet false. Antwort NUR JSON: "
    '{"antwortet": true|false, "art": "zustimmung|ablehnung|rueckfrage|aufforderung|eigenes", '
    '"beleg_aeusserung": "<Wendung aus aeusserung, WÖRTLICH>"|null, "beleg_ihre_zeile": "<Wendung aus ihre_zeile, WÖRTLICH, auf die '
    'geantwortet wird>"|null}. Ohne beide Belege ist antwortet false.')


def answer_reference_check(conn, actor: str, *, line: str, text: str, speaker: str, figure: str, unsaid: str,
                           data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65L: does HIS input answer the theme part of HER line he answers? None without provider."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip() or not str(line or "").strip() or not str(unsaid or "").strip():
        return None
    payload = {"ihre_zeile": str(line)[:600], "aeusserung": str(text)[:600], "von": str(speaker), "an": str(figure),
               "ungesagt": str(unsaid)[:240]}
    audit = provider_audit(conn, actor, data or {}, "answer_reference") if conn is not None else None
    parsed = _llm_json(routing, ANSWER_REFERENCE_RULES, payload, temperature=0.0, max_tokens=160, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


def goal_disclosure_check(conn, actor: str, *, text: str, speaker: str, recipient: str, unsaid: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V65H: does HER speech now actually say the unsaid content to the recipient? None without provider."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip() or not str(unsaid or "").strip():
        return None
    payload = {"rede": str(text)[:800], "von": str(speaker), "an": str(recipient), "ungesagt": str(unsaid)[:240]}
    audit = provider_audit(conn, actor, data or {}, "goal_disclosure") if conn is not None else None
    parsed = _llm_json(routing, GOAL_DISCLOSURE_RULES, payload, temperature=0.0, max_tokens=120, timeout=30, audit=audit, attempts=1)
    return parsed if isinstance(parsed, dict) else None


# V62 (AMASTER §42 Kette Disposition -> Affect -> Intent, §44 Interpretation je
# Owner, §15 Kompass als Linse, §50 "Kandidaten vorschlagen, ohne selbst zu
# committen"): a separate, neutral appraisal of what each figure has just
# perceived. It proposes; the kernel validates (own compass space, threshold,
# persons of the event, bounds, idempotency) and writes. It decides no speech
# and no action. Reference: the v76 Folge-Bewerter (Download171) evaluated the
# figure's OWN answer after the fact and its writes were blocked; here the
# perceived EVENT is appraised before the answer.
APPRAISAL_RULES = (
    "Erleben (AMASTER §42/§44/§15): Eine Figur hat gerade etwas wahrgenommen ('gerade_geschehen'). Bestimme, was GENAU DIESES Geschehen "
    "jetzt in ihr auslöst — aus IHRER Sicht, mit ihrem Profil, ihrem Kompass, ihren Zielen, ihren Beziehungen und dem, was offen ist. "
    "Kette: Disposition → ausgelöstes Gefühl → gegebenenfalls Absicht. Du entscheidest keine Rede und keine Handlung. Antwort NUR JSON: "
    '{"raum": "<genau ein raum aus IHREM kompass oder null>", "aktivierung": 0..1, '
    '"gefuehl": "<ein deutsches Wort oder leer>", "gegenueber": "<Name aus personen, auf den sich das Gefühl richtet, oder leer>", '
    '"zustand_aenderung": {"angst": -0.3..0.3, "wut": -0.3..0.3, "scham": -0.3..0.3, "stress": -0.3..0.3, "lust": -0.3..0.3}, '
    '"absicht": "<kurzer Satz oder leer>", "vorher_absicht_erledigt": true|false, '
    '"beziehung_aenderung": [{"zu": "<Name einer Person aus gerade_geschehen>", "trust": -0.3..0.3, "closeness": -0.3..0.3, "fear": -0.3..0.3}], '
    '"grund": "<welcher konkrete Aspekt des Ereignisses und ihrer Disposition die Änderung begründet, kurz>"}. '
    "gefuehl = das Gefühl, das DIESES Geschehen auslöst, nicht ihre Gesamtstimmung (frühere Gefühle klingen im System von selbst ab). "
    "aktivierung = wie stark es diesen Raum ihres Kompasses berührt; ihre schwelle entscheidet, ob es sie erfasst. "
    "zustand_aenderung = Änderung ihres momentanen Zustands durch DIESES Geschehen; 0 oder weglassen, wo sich nichts ändert. "
    "beziehung_aenderung = DAUERHAFTE Änderung der gerichteten Beziehung durch dieses Geschehen (Vertrauen gewonnen oder gebrochen, Nähe gewachsen "
    "oder verletzt, Furcht entstanden); momentane Zuneigung, Freude oder Begehren sind Gefühl, keine Beziehungsänderung; Alltägliches = 0. "
    "gefuehl leer und aktivierung 0, wenn das Geschehen für sie nichts verändert. "
    "absicht = was sie wegen dieses Geschehens jetzt vorhat; leer, wenn es an 'vorher.absicht' nichts ändert. "
    "vorher_absicht_erledigt = true, wenn sie 'vorher.absicht' mit 'zuletzt_selbst' schon umgesetzt hat oder es sich erledigt hat; "
    "was laut 'offen' bereits angenommen oder erfüllt ist, ist kein offenes Vorhaben mehr. "
    "Nur Personen aus 'personen'; nichts erfinden, was nicht in gerade_geschehen, verlauf, profil oder offen steht."
)


# Stand 11: der V84-Kausalnachweis wird in derselben Erlebensantwort geliefert (Regeltext unten, aus APPRAISAL_CAUSAL_CHECK_RULES).
APPRAISAL_KAUSAL_IN_ERSTER_ANTWORT = ""   # wird nach APPRAISAL_CAUSAL_CHECK_RULES gesetzt
APPRAISAL_ANTWORTRAUM = 320 + 3200


# V84, AMASTER §24.2/§42/§44/§50: Independent causal validation of EACH
# proposed effect. It does not prescribe how a character feels or responds.
# Without a provable witnessed cause the canonical writer must not apply an
# effect (the observed speech/action remains the canonical event).
APPRAISAL_CAUSAL_CHECK_RULES = (
    "Kausale Gegenprüfung nach AMASTER §24.2, §42, §44 und §50. Du bist nicht der Bewerter. "
    "Prüfe JEDE unter 'zu_pruefen' genannte Veränderung UNABHÄNGIG und getrennt, "
    "ob gerade_geschehen, Profil, Ziele, vorherige gerichtete Beziehung und Kontext "
    "die konkrete Änderung bei DIESER Figur tatsächlich tragen. "
    "Eine Situation kann Zuneigung, Ärger, Lust, Angst, Ablehnung, Ambivalenz "
    "oder keine Zustandsänderung auslösen. Gib keine vorgeschriebene Reaktion vor. "
    "Geprüft wird nicht, ob eine Reaktion denkbar wäre, sondern ob sie aus den "
    "vorliegenden Quellen für diese Figur hinreichend begründet ist. "
    "Weder ein tatsächliches Ereignis noch körperliche Erregung noch Beziehung "
    "beweisen Zustimmung zu einer konkreten Handlung. Kein Beleg = nicht_gestuetzt. "
    "Für jedes Feld genau ein Ergebnis mit einer ID aus gerade_geschehen und "
    "wörtlich kopiertem Teil seines Texts. Eine bloße Wiederholung des Ereignisses "
    "ohne Erklärung seiner Wirkung auf diese Figur ist KEINE Begründung. "
    "Nenne dispositionsQuelle als ID einer Quelle aus 'figur.dispositionsquellen' und dispositionsBeleg als WÖRTLICHEN "
    "Ausschnitt (mindestens zwei Wörter oder die ganze Quelle) aus genau dem Text DIESER Quelle - nicht aus einer anderen "
    "Darstellung des Profils; begruendung BEGINNT mit genau diesem Ausschnitt der QUELLE (dispositionsBeleg) in Anführungszeichen - NICHT mit dem "
    "Ereigniszitat, das steht schon in beleg - danach die Erklärung, "
    "warum diese Quelle die Änderung bei dieser Figur trägt. "
    "Ein Ereigniszitat ersetzt den individuellen Dispositionsbeleg NICHT. "
    "Bei Zahlenfeldern (zustand.*, beziehung.*) sind die Vorzeichen im Vorschlag verdeckt (nur Beträge). Bestimme richtung "
    "SELBST: 'steigt' oder 'sinkt' - die Richtung, in die die zitierte Quelle dieses Feld bei dieser Figur durch das Ereignis trägt. "
    "Trägt die Quelle keine eindeutige Richtung, ist das Feld nicht_gestuetzt. Eine Quelle, die nur zum Thema passt, die Gegenrichtung trägt oder deren Wirkung du erst mit 'jedoch' oder "
    "'überschattet' umkehren müsstest, trägt die Änderung NICHT: nicht_gestuetzt. "
    "Wenn es keinen konkreten Beleg gibt: nicht_gestuetzt; nichts erfinden. "
    "Antwort NUR JSON: {\"pruefungen\": [{\"feld\": \"<exakter String aus zu_pruefen>\", "
    "\"urteil\": \"gestuetzt|nicht_gestuetzt\", \"factId\": \"<ID aus gerade_geschehen>\", "
    "\"beleg\": \"<wörtlicher Ausschnitt aus gerade_geschehen.text>\", "
    "\"dispositionsQuelle\": \"<ID aus figur.dispositionsquellen>\", "
    "\"dispositionsBeleg\": \"<wörtlicher Ausschnitt aus dem Text dieser Quelle>\", "
    "\"richtung\": \"steigt|sinkt (nur Zahlenfelder)\", "
    "\"begruendung\": \"\\\"<derselbe Ausschnitt>\\\" - <warum diese Quelle die Änderung bei dieser Figur trägt>\"}]}"
)
# Stand 11: derselbe Kausalnachweis als Teil der EINEN Erlebensantwort (SPS V62.7 + V84-Belege, ohne zweiten Aufruf).
APPRAISAL_KAUSAL_IN_ERSTER_ANTWORT = (
    " FORMAT (ersetzt die Objektform von zustand_aenderung oben): zustand_aenderung ist eine Liste [{\"name\": angst|wut|scham|stress|lust, "
    "\"wert\": -0.3..0.3, \"nachweis\"}] nur mit den Werten ungleich 0. PFLICHT: JEDE vorgeschlagene Änderung trägt DIREKT daneben "
    "ihren Kausalnachweis - gefuehl_nachweis (wenn gefuehl nicht leer, sonst null), absicht_nachweis (wenn absicht nicht leer, sonst "
    "null), nachweis je zustand_aenderung-Eintrag, trust_nachweis / closeness_nachweis / fear_nachweis je beziehung_aenderung-Eintrag "
    "(wenn der Wert ungleich 0, sonst null). Ein nachweis: {\"urteil\": \"gestuetzt|nicht_gestuetzt\", \"factId\": \"<ID aus "
    "gerade_geschehen>\", \"beleg\": \"<wörtlicher Ausschnitt aus gerade_geschehen.text>\", \"dispositionsQuelle\": \"<ID aus "
    "dispositionsquellen>\", \"dispositionsBeleg\": \"<wörtlicher Ausschnitt (mindestens zwei Wörter oder die ganze Quelle) aus genau "
    "dem Text dieser Quelle>\", \"richtung\": \"steigt|sinkt\" (nur bei Zahlen, sonst null), \"begruendung\": \"\\\"<derselbe "
    "dispositionsBeleg>\\\" - <warum diese Quelle die Änderung bei dieser Figur trägt>\"}. Ohne konkreten Beleg im Geschehen und in einer "
    "ihrer Dispositionsquellen ist das urteil nicht_gestuetzt; nichts erfinden. Das System prüft jede ID und jedes Zitat wörtlich. "
    "PFLICHT auch \"vorher_absicht_art\": ist vorher_absicht_erledigt true, \"rede\" oder \"handlung\" - wie vorher.absicht ausgeführt "
    "wird: rede = indem sie etwas sagt, fragt, bittet oder mitteilt; handlung = durch ein körperliches oder räumliches Tun; sonst null."
)


# V65P (AMASTER §15, §36.5, §42; Pruefung v2.7): the two 171 evaluator clauses
# of V65G (APPRAISAL_AP_ACCEPTED / APPRAISAL_AP_NOT, "verbindlich, geht den
# Kompass-Regeln vor") are removed. They derived a permission from the
# relationship TYPE (lover = "DARF mit Naehe/Lust bewertet werden") and
# prescribed the intent ("die Absicht ist Abstand/Grenze/Klaerung/
# Zurueckweisung") - also for the actor himself (measured V65N: Johann's intent
# "Abstand halten" 3/3 with, "Mara einschuechtern" 3/3 without). The figure
# appraises from her own compass, relationships, state and what happened.


def _blind_direction(res: dict) -> dict:
    """V92: the independent review must determine the DIRECTION itself. Signs of numeric changes and the proposer's
    narrative (grund) are hidden so the reviewer cannot merely repeat the proposal; the validator compares directions."""
    out = {k: v for k, v in res.items() if k not in ("_kausalpruefung", "grund")}
    if isinstance(out.get("zustand_aenderung"), dict):
        out["zustand_aenderung"] = {k: (abs(v) if isinstance(v, (int, float)) else v) for k, v in out["zustand_aenderung"].items()}
    rels = out.get("beziehung_aenderung")
    if isinstance(rels, dict): rels = [rels]
    if isinstance(rels, list):
        out["beziehung_aenderung"] = [{k: (abs(v) if isinstance(v, (int, float)) and k != "zu" else v) for k, v in r.items()}
                                      if isinstance(r, dict) else r for r in rels]
    return out


def appraise_events(conn, actor: str, payload: dict[str, Any], *, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V62: appraisal of each figure with pending perceived events — one call
    per figure, run in parallel (each sees only HER payload; measured: one
    batched call mixed figures and took 6.7 s). Provider audit rows are written
    afterwards on the calling thread (SQLite connection is not shared). Without
    provider None (the kernel then only applies decay)."""
    import concurrent.futures as _cf
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    figs = [f for f in (payload or {}).get("figuren") or [] if isinstance(f, dict)]
    if not routing.get("allowed") or not figs:
        if not routing.get("allowed"):
            _set_err("LLM_REQUIRED")
        return None
    persons = list((payload or {}).get("personen") or [])

    def _one(fig):
        rec: list = []
        # V65P: no prefixed 171 clause (see above). The input limit is raised
        # from 12000 because the compass now arrives complete (§15); the payload
        # is JSON and a cut would drop its last key "gerade_geschehen".
        _system = APPRAISAL_RULES
        try:
            # Stand 11 (SPS V62.7): EIN Aufruf je Figur; der Kausalnachweis (frueher zweiter Aufruf V84) kommt in derselben Antwort
            # Antwortraum = bisheriges Erleben (320) + bisheriger Hoechstwert des Kausalnachweises (3200, je Wirkungsfeld ein Eintrag)
            res = _llm_json(routing, _system + APPRAISAL_KAUSAL_IN_ERSTER_ANTWORT, {"personen": persons, **fig}, temperature=0.0,
                            max_tokens=APPRAISAL_ANTWORTRAUM, timeout=60,
                            response_format=_strikt(routing, "erleben", APPRAISAL_SCHEMA), max_input_chars=30000, audit=lambda ph, d: rec.append((ph, d)), attempts=1)
            err = _last_llm_error()
        except Exception as exc:   # any transport/shape error = failed for her (review finding 9)
            res, err = None, f"{type(exc).__name__}: {str(exc)[:120]}"
        if res is not None and not isinstance(res, dict):
            res, err = None, "bad_json"
        if isinstance(res, dict) and res.get("_abgeschnitten"):
            res, err = None, "erleben_abgeschnitten"   # Stand 11: abgeschnittene Erlebenslesung ist nicht gueltig
        if isinstance(res, dict):
            # Stand 11: der Kausalnachweis steht in DERSELBEN Antwort (Feld "kausalpruefung"); der Kernel
            # (_appraisal_cause_proofs) prueft jede Fakt-ID, jedes woertliche Zitat und jede Dispositionsquelle selbst.
            from matrix_api.kernel import appraisal_effect_fields
            fields = appraisal_effect_fields(res)
            res = erleben_aus_antwort(res)   # Stand 11B: Nachweise neben den Werten -> bisherige Struktur
            _kp = res.pop("kausalpruefung", None)
            res["_kausalpruefung"] = _kp if isinstance(_kp, dict) else {"pruefungen": []}
            # Stand 11a: die Absichtsart (frueher INTENT_KIND-Aufruf) aus demselben Pflichtfeld
            _art = res.pop("vorher_absicht_art", None)
            res.pop("lesungen", None)
            _vorher = str(((fig.get("vorher") or {}) if isinstance(fig.get("vorher"), dict) else {}).get("absicht") or "").strip()
            if _art in ("rede", "handlung") and _vorher:
                res["lesungen"] = [{"lesung": "absichtsart", "zu": _vorher, "antwort": {"art": _art}}]
            _ = fields   # Stand 11: kein zweiter Aufruf; leere Liste = kein Feld belegt (Kernel verwirft nur diese Felder)
        return fig.get("figur"), res, err, rec

    with _cf.ThreadPoolExecutor(max_workers=min(6, len(figs))) as ex:
        done = list(ex.map(_one, figs))
    rows, errors, failed = [], [], []
    for name, res, err, rec in done:
        if conn is not None:
            write = provider_audit(conn, actor, data or {}, "appraisal")
            for ph, d in rec:
                write(ph, d)
        if isinstance(res, dict):
            rows.append({**res, "figur": name})
        else:
            errors.append(f"{name}: {err}")
            failed.append(name)
    if not rows:
        _set_err("; ".join(errors)[:300] or "no_result")
        return None
    return {"bewertungen": rows, "fehler": errors, "fehlgeschlagen": failed}


LEARN_RULES = (
    "Lernschleife (AMASTERv2 §40, Vorbild Präferenzlernen): Lies GENAU DIESE Äußerung und liefere, was sich daraus DAUERHAFT über die "
    "genannte Figur lernen lässt. Antwort NUR JSON: {\"likes\": [], \"dislikes\": [], \"goals\": [], \"knowledge\": [], \"fears\": [], "
    "\"secrets\": [], \"values\": [], \"coreFacts\": [], \"favoriteWords\": [], \"typicalPhrases\": [], \"relations\": [{\"to\": name, \"kind\": \"Bruder|Ex-Freund|Chefin|…\"}]}. "
    "Nur was die Äußerung wirklich hergibt (Selbstauskunft der Figur, oder eine Aussage ÜBER die Figur, wenn sprecherIstFigur=false); "
    "keine Vermutungen, keine Wiederholung von bereitsBekannt. favoriteWords/typicalPhrases NUR bei sprecherIstFigur=true (eigene Rede). "
    "knowledge = Fakten über die Figur in dritter Person, kurz. Leere Listen sind richtig, wenn nichts zu lernen ist."
)


def extract_learning(conn, actor: str, text: str, *, figure_name: str, speaker_is_figure: bool, known: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V41: Lernvorschlag über den konfigurierten Provider (klein). Ohne Provider None (lokale Lesung)."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip():
        return None
    payload = {"figur": figure_name, "sprecherIstFigur": bool(speaker_is_figure), "aeusserung": str(text)[:500],
               "bereitsBekannt": {k: (known or {}).get(k) for k in ("likes", "dislikes", "goals", "knowledge", "favoriteWords", "typicalPhrases") if (known or {}).get(k)}}
    parsed = _llm_json(routing, LEARN_RULES, payload, temperature=0.0, max_tokens=500, timeout=30)
    return parsed if isinstance(parsed, dict) else None


TRUTH_RULES = (
    "Widerspruchsprüfung (AMASTERv2 §41/§42, perspektivisch): Prüfe NUR, ob die aktuelle Äußerung dem widerspricht, was DIESE Figur "
    "sicher weiß (stammwissen), selbst bezeugt hat (behauptungen mit Turn) oder was vereinbart ist (vereinbarungen) — oder ob der Sprecher "
    "sich selbst widerspricht (frühere Behauptung desselben Sprechers). Antwort NUR JSON: "
    '{"widersprueche": [{"art": "fremdwissen|selbstwiderspruch|vereinbarung", "aussage": string, "bekannt": string (wörtlich aus den Quellen), '
    '"quelle": "Stamm|Turn n|Vereinbarung", "sicherheit": 0..1, "grund": string}]}. '
    "Nur echte Unvereinbarkeiten (nicht bloß Neues oder Unbekanntes). Leere Liste ist richtig, wenn nichts widerspricht."
)


def detect_contradictions(conn, actor: str, text: str, *, utterer_name: str, character: dict[str, Any], claims: list[dict], frames: list[dict], data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V42: semantische Widerspruchsprüfung über den Provider (klein). Ohne Provider None (lokal)."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip():
        return None
    payload = {
        "figur": character.get("name"),
        "sprecher": utterer_name,
        "aeusserung": str(text)[:400],
        "stammwissen": ([str(x)[:120] for x in (character.get("knowledge") or [])][:10] + [str(x)[:120] for x in (character.get("coreFacts") or [])][:6] + [str(character.get("biography") or "")[:400]]),
        "behauptungen": [{"turn": c.get("turn"), "von": c.get("by"), "text": str(c.get("text") or "")[:140]} for c in claims][-12:],
        "vereinbarungen": [str(f.get("what") or "")[:140] for f in frames][-6:],
    }
    parsed = _llm_json(routing, TRUTH_RULES, payload, temperature=0.0, max_tokens=400, timeout=30)
    return parsed if isinstance(parsed, dict) else None


GOD_RULES = (
    "Strukturierte God-Extraktion (AMASTERv2 §46): Zerlege den God-Text in Einzelanweisungen. Antwort NUR JSON: "
    '{"anweisungen": [{"ziel": "<Figurname>|Szene|Welt", "art": "koerper|wissen|beziehung|szene|welt|zustand|zeit|handlung", "andere": "<Figurname>|null", "text": "<die Tatsache in einem Satz, dritte Person>", "beleg": "<wörtlicher Ausschnitt aus godText, der GENAU diese Anweisung trägt>"}], "unklar": ["<Satzteil, der sich nicht sicher binden lässt>"]}. '
    "koerper = Verletzung/Haltung/Bewusstsein/Sprechfähigkeit einer Figur; wissen = was eine Figur jetzt weiß/erfährt; beziehung = Haltung einer Figur zu einer anderen (andere = Zielperson); "
    "handlung = tatsächlich ausdrücklich angeordnete Handlung: ziel ist der HANDELNDE, andere die BETROFFENE Figur falls eindeutig; keine Handlung erfinden; "
    "szene = Ort/Licht/Geräusch/Ereignis im Raum; welt = Weltregel/Weltereignis; zustand = sonstiger Zustand einer Figur; zeit = Zeitsprung. "
    "Nur Figuren aus 'figuren' als ziel/andere, die auch durch den ORIGINALEN godText selbst eindeutig gebunden sind. "
    "Beleg muss wörtlich im godText stehen und die tatsächliche Operation enthalten. Keine Umformulierung zu zusätzlichen Taten. "
    "Ein Satz = eine Anweisung; Unklares nach unklar."
)


# P20 / AMASTER 24.2: one narrowly scoped *semantic boundary* reading, not
# another character-ID resolver or a vocabulary of greeting/object words.
NAME_BOUNDARY_RULES = (
    "Namensumfang (AMASTER §24.2): Du bekommst eine Originaläußerung und "
    "für jede unsichere Wortfolge eine Liste von exakt im Text stehenden "
    "Wörtern mit Positionen (woerter). "
    "Klassifiziere JEDES Wort der gegebenen Wortfolge in derselben Reihenfolge. "
    "Antworte mit wortklassen (eine Klasse JE Eingabewort): "
    "name = Wort gehört zum tatsächlich GESCHRIEBENEN Personennamen; "
    "gruss = Anredegruß; titel = Anredetitel; praeposition = Einleitung wie Neben/Von; "
    "anderes = anderes Satzglied (insbesondere nach dem Namen); "
    "unklar = Bedeutung zweifelhaft. "
    "Die name-Wörter müssen lückenlos nebeneinander stehen. "
    "Gib KEINEN ausgeschriebenen Figurennamen und KEINE Figuren-ID aus; "
    "auch wenn du die Figur als Mara Nowak kennst und dort nur Mara steht, "
    "markiere einzig das tatsächlich geschriebene Wort 'Mara'. "
    "Bewerte die Rolle der Namensstelle: anrede nur wenn diese Person "
    "angesprochen wird, sonst nennung. Ohne sichere Bedeutung status=unklar. "
    "a,b,wortfolge unverändert aus kandidaten übernehmen. "
    "Beispiele (nur Beispiele, keine Regeln über die Wörter): "
    "'Hallo Mara' -> ['gruss','name'], anrede; "
    "'Guten Morgen Mara' -> ['gruss','gruss','name'], anrede; "
    "'Frau Nowak' -> ['titel','name'], anrede; "
    "'Mara Wasser' in 'Johann reicht Mara Wasser' -> ['name','anderes'], nennung; "
    "'Neben Mara Nowak' -> ['praeposition','name','name'], nennung; "
    "'Anna Mara Nowak' als Name einer unbekannten Person -> "
    "['name','name','name'], nennung. "
    "Antwort NUR JSON: {\"grenzen\": [{\"a\": integer, \"b\": integer, "
    "\"wortfolge\": string, \"wortklassen\": "
    "[\"name|gruss|titel|praeposition|anderes|unklar\",...], "
    "\"rolle\": \"anrede|nennung\", \"status\": \"eindeutig|unklar\"}]}. "
    "Keine freien Namen, keine Namens-IDs, kein vollständiger Satz als Namenfeld."
)

def name_boundary_check(conn, actor: str, text: str, *, figures: list[dict],
                        data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Return a scoped semantic proposal for genuinely unproven name boundaries.

    At most ONE extra request for the whole input (10s cap); no request for ordinary
    already-proven names, and no call while a SQLite write transaction is open.
    """
    from matrix_api.kernel import name_boundary_candidates
    pending = name_boundary_candidates(text, figures)
    if not pending:
        return {"grenzen": []}
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed"):
        return None
    # The server, not the LLM, owns text offsets.  Each candidate carries
    # its original words, so the model has only to mark their semantic roles.
    tokenized = []
    for candidate in pending[:24]:
        tokenized.append({**candidate, "woerter": [
            {"i": i, "wort": match.group(),
             "a": candidate["a"] + match.start(), "b": candidate["a"] + match.end()}
            for i, match in enumerate(re.finditer(r"\w+", candidate["wortfolge"]))]})
    payload = {"aeusserung": str(text or "")[:1500], "kandidaten": tokenized,
               "figuren": [{"name": str(f.get("name") or ""), "aliases": list(f.get("aliases") or [])[:6]}
                           for f in figures if isinstance(f, dict)][:16]}
    # Stand 11 (SPS V62.7): die Namenslesung kommt aus der ERSTEN Antwort (Planer, Lesung "namen" je Wortfolge) - kein
    # eigener Modellaufruf. Die Positionen setzt der Server aus seinen eigenen Kandidaten (er besitzt die Textstellen);
    # with_name_boundary_reading prueft jede Wortklasse unveraendert gegen den Originaltext. Fehlt die Lesung: None.
    grenzen = []
    for cand in tokenized:
        stelle = _norm_stelle(cand.get("wortfolge"))
        with _VORAB_LOCK:
            _st = _vorab_speicher()
            treffer = [a for z, a in (_st["lesungen"].get("namen") or []) if z == stelle]   # nur dieselbe Wortfolge
            _st["abrufe"].append({"lesung": "namen", "payload": {"aeusserung": payload["aeusserung"], "wortfolge": cand.get("wortfolge")},
                                 "aus_erster_antwort": bool(treffer)})
        if treffer:
            t = treffer[-1]
            if isinstance(t.get("grenzen"), list) and len(t["grenzen"]) == 1 and isinstance(t["grenzen"][0], dict):
                t = t["grenzen"][0]          # in der Form der Einzelregel geantwortet: derselbe eine Eintrag
            grenzen.append({k: v for k, v in t.items() if k not in ("a", "b", "wortfolge")}
                           | {"a": cand["a"], "b": cand["b"], "wortfolge": cand["wortfolge"]})
    if not grenzen:
        _set_err("nicht_in_erster_antwort:namen")
        return None
    return {"grenzen": grenzen}


def extract_god_instructions(conn, actor: str, text: str, *, figures: list[str], data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """V43: God-Text → strukturierte Anweisungen über den Provider (klein). Ohne Provider None (lokal)."""
    cfg = _cfg(conn, actor, data or {}) if conn is not None else {}
    routing = _routing(data or {}, cfg)
    if not routing.get("allowed") or not str(text or "").strip():
        return None
    # Stand 11: die Namenslesung (Wortgrenzen) kommt in DERSELBEN Antwort (frueher ein eigener Aufruf vor dieser Zerlegung)
    parsed = _llm_json(routing, GOD_RULES + GOD_NAMEN_PRUEFUNG_RULES, {"godText": str(text)[:1200], "figuren": figures[:40]},
                       temperature=0.0, max_tokens=1100, timeout=45, response_format=_strikt(routing, "god_zerlegung", GOD_SCHEMA))
    if isinstance(parsed, dict):
        parsed.pop("lesungen", None)
        vorab_registrieren(namen_lesungen(parsed.pop("namen", None)), quelle="god")
    return parsed if isinstance(parsed, dict) else None


def _fmt_list(items: Any, cap: int = 6, sep: str = "; ") -> str:
    vals = [str(x).strip() for x in (items or []) if str(x).strip()] if isinstance(items, (list, tuple)) else ([str(items).strip()] if items else [])
    return sep.join(vals[:cap])


def render_persona_brief(spiegel: dict[str, Any], utterance: str, uttered_by: str, last_own: str) -> str:
    """V38 (AMASTERv2 §49–§51): Die Vorgabe an das LLM ist ein Persona-Brief in Klartext,
    nach Wichtigkeit geordnet — Figur, Zustand jetzt, Beziehung zum Gegenüber, Erinnerungen,
    Wissen/Nichtwissen, Szene, Druck, Verlauf, Äußerung — statt eines JSON-Dumps.
    Der Brief ist eine Formulierungsvorgabe; er schreibt keine Wahrheit."""
    # V65G: local (the renderer stays self-contained; test_v54 executes it in isolation)
    def action_permission_lines(ap: Any) -> list[str]:
        """V65G read the 171 frame (kernel.action_permission_frame) into three 171
        lines. V65P (AMASTER §36.5, §15, "Prompt ist nur Spiegel"; Pruefung v2.7):
        only the STATE stays - the directed relationship toward the counterpart
        (values /100, type) and an existing bond to another person. Removed: both
        ACTION-PERMISSION lines (a permission derived from the relationship type,
        and a prescribed boundary act "zuruecktreten oder zurueckweichen ...
        Abstand schaffen", each "verbindlich, geht ... vor"), the behaviour
        clauses of the relationship line, and the order not to deny the bond
        (a figure may deceive, AMASTER Z. 324). The name stays for the spiegel key."""
        if not isinstance(ap, dict) or not ap.get("partnerName"):
            return []
        pn = str(ap["partnerName"])
        rel = ap.get("relation") if isinstance(ap.get("relation"), dict) else None
        out: list[str] = []
        if rel and ap.get("partnerBond"):
            tr, pr = round(float(rel.get("trust") or 0) * 100), round(float(rel.get("closeness") or 0) * 100)
            out.append(f"Deine Beziehung zu {pn} JETZT (in dieser Szene gewachsen, sessionbezogen): Vertrauen {tr}/100, "
                       f"Nähe {pr}/100, Typ {rel.get('kind') or 'neutral'}.")
        else:
            vals = (f"Vertrauen {round(float(rel.get('trust') or 0) * 100)}/100, Nähe {round(float(rel.get('closeness') or 0) * 100)}/100, "
                    f"Typ {rel.get('kind') or 'neutral'}") if rel else "keine Beziehung, Typ neutral"
            who = "" if ap.get("isFigure", True) else f" {pn} ist keine Figur der Welt."
            out.append(f"Deine Beziehung zu {pn} JETZT: zu dieser Person besteht (noch) KEIN gewachsener Bund - neutral "
                       f"({vals}).{who}")
        ob = ap.get("otherBond") if isinstance(ap.get("otherBond"), dict) else None
        if ob:
            out.append(f"PARTNERBINDUNG-BESTEHT: Du hast eine reale, aktive Bindung ({ob.get('kind') or 'enge Bindung'}) zu einer Person, die NICHT "
                       "dein jetziger Gesprächspartner ist. Diese Bindung ist WAHR und Teil deiner Wahrheit.")
        return out

    p = spiegel.get("profile") if isinstance(spiegel.get("profile"), dict) else {}
    rt = spiegel.get("runtime") if isinstance(spiegel.get("runtime"), dict) else {}
    body = spiegel.get("body") if isinstance(spiegel.get("body"), dict) else {}
    scene = spiegel.get("scene") if isinstance(spiegel.get("scene"), dict) else {}
    fate = spiegel.get("fate") if isinstance(spiegel.get("fate"), dict) else {}
    name = str(p.get("name") or (spiegel.get("speaker") or {}).get("name") or "die Figur")
    lines: list[str] = []
    head = [x for x in (str(p.get("age") or ""), str(p.get("gender") or ""), str(p.get("occupation") or ""), str(p.get("role") or "")) if x]
    lines.append(f"DU BIST {name}" + (f" ({', '.join(head)})" if head else "") + ".")
    # Stand 11 (SPS V62.7 "Gefühl/Absicht/Beziehung ... im selben Turn im Brief"; AMASTER §7/§42/§49, Matrix10 Nr. 16/19): die
    # handlungsrelevante LAGE aus dem gespeicherten Zustand steht VOR dem Profil - Gefühle mit Stärke, Ursache und Person,
    # fortbestehende Absicht, Körper, verletzte Grenzen und die letzte Handlung an ihr, die Beziehung zu genau diesen Personen.
    # Kein Satz zum Nachsprechen und keine vorgegebene Reaktion; Profil und Kompass färben nur.
    _lage: list[str] = []
    _aff = [a for a in (rt.get("affects") or []) if isinstance(a, dict) and a.get("type")]
    for a in _aff[:4]:
        _lage.append(f"{a.get('type')}" + (f" gegenüber {a.get('toward')}" if a.get("toward") else "")
                     + (f", Stärke {float(a.get('intensity') or 0):.2f}" if a.get("intensity") is not None else "")
                     + (f", seit Zug {a.get('since')}" if a.get("since") is not None else ""))
    if not _aff and rt.get("emotion") and float(rt.get("intensity") or 0) >= 0.4:
        _lage.append(f"{rt.get('emotion')}" + (f" gegenüber {rt.get('emotionToward')}" if rt.get("emotionToward") else "")
                     + f", Stärke {float(rt.get('intensity') or 0):.2f}")
    if str(rt.get("activeCauseText") or "").strip():
        _lage.append(f"Ursache: {str(rt.get('activeCauseText'))[:160]}")
    if str(rt.get("intent") or "").strip():
        _lage.append(f"was du dir vorgenommen hast: {str(rt.get('intent'))[:160]}")
    _bd = spiegel.get("body") if isinstance(spiegel.get("body"), dict) else {}
    if _bd.get("pain") or rt.get("pain"):
        _lage.append(f"Schmerz {(_bd.get('pain') or rt.get('pain'))}")
    _sl = [x for x in (spiegel.get("sceneLines") or []) if x and str(x).startswith(("GRENZE", "Letzte körperliche Handlung", "KÖRPERPOSITION"))]
    _lage.extend(str(x) for x in _sl[:3])
    _personen = {str(a.get("toward")) for a in _aff if a.get("toward")} | ({str(rt.get("emotionToward"))} if rt.get("emotionToward") else set())
    for r in [r for r in (spiegel.get("relationsHere") or []) if isinstance(r, dict) and str(r.get("name")) in _personen][:3]:
        _lage.append(f"zu {r.get('name')} jetzt: Vertrauen {float(r.get('trust') or 0):.2f}, Nähe {float(r.get('closeness') or 0):.2f}, "
                     f"Furcht {float(r.get('fear') or 0):.2f}")
    if _lage:
        lines.append("DEINE LAGE JETZT (daraus handelst du - wie ein Mensch in genau dieser Lage; dein Profil und dein Kompass unten "
                     "färben nur, wie): " + " · ".join(_lage) + ".")
    if p.get("personality"):
        lines.append(f"Persönlichkeit: {str(p['personality'])[:300]}")
    if p.get("biography"):
        lines.append(f"Hintergrund: {str(p['biography'])[:500]}")
    style = [f"Sprachregister: {p['speechRegister']}" if p.get("speechRegister") else "", f"Dialekt: {p['dialect']}" if p.get("dialect") else "",
             f"Humor: {p['humor']}" if p.get("humor") else "", f"Konfliktstil: {p['conflictStyle']}" if p.get("conflictStyle") else ""]
    style = [x for x in style if x]
    if style:
        lines.append("So sprichst und streitest du — " + " · ".join(style))
    if p.get("typicalPhrases"):
        # V65 (AMASTER §51.3 "geringe Wiederholung"; 171: "Keine Wiederhol-Schleifen"):
        # authored phrases are style samples, not a line to say every turn.
        lines.append(f"Typische Wendungen von dir (Stilbeispiele, nicht in jeder Antwort): {_fmt_list(p.get('typicalPhrases'), len(p.get('typicalPhrases') or []), ' | ')}")
    if p.get("favoriteWords"):
        lines.append(f"Lieblingswörter: {_fmt_list(p.get('favoriteWords'), 6, ', ')}")
    if p.get("values"):
        lines.append(f"Werte: {_fmt_list(p.get('values'))}")
    # AMASTER 41/49: goals enter the expressive brief only through the
    # situational Foreground reader, never by dumping the whole profile.
    if p.get("fears"):
        lines.append(f"Was du fürchtest: {_fmt_list(p.get('fears'))}")
    if p.get("ownSecrets") or p.get("secrets"):
        lines.append(f"Was nur du weißt (nie offen aussprechen, aber es färbt dich): {_fmt_list(p.get('ownSecrets') or p.get('secrets'), 4)}")
    if p.get("likes") or p.get("dislikes"):
        lines.append(f"Du magst: {_fmt_list(p.get('likes'), 4, ', ') or '—'} · Du magst nicht: {_fmt_list(p.get('dislikes'), 4, ', ') or '—'}")
    if p.get("taboos"):
        lines.append(f"Tabus für dich: {_fmt_list(p.get('taboos'), 4)}")
    if p.get("reactionRules") or p.get("bindingPatterns"):
        lines.append(f"Reaktionsmuster: {_fmt_list(p.get('reactionRules'), len(p.get('reactionRules') or []))} {('· Bindungsmuster: ' + _fmt_list(p.get('bindingPatterns'), 3)) if p.get('bindingPatterns') else ''}".strip())
    if p.get("coreFacts"):
        lines.append(f"Kernfakten über dich: {_fmt_list(p.get('coreFacts'), 6)}")
    lens = [c for c in (spiegel.get("compassLens") or []) if isinstance(c, dict) and c.get("reaction")]
    if lens:
        # V60b (AMASTER §15): the Chathere-Kompass as behaviour lens (profile).
        # Stand 10C (AMASTER §15 "stabile Tendenzen, keine erzwungenen Einzelreaktionen"; Geraet 08.11.: Mara wiederholte in
        # 5 von 5 Antworten die Kompass-Geste "tritt zurück"): the lens is a tendency, its visible cue one possible form.
        lines.append("DEIN KOMPASS (stabile Tendenzen, keine festen Reaktionen: wie du eher reagierst und was dich antreibt; "
                     "die sichtbaren Zeichen sind Beispiele, nicht was du jedes Mal tust; "
                     "Hemmschwelle = ab welcher Stärke es dich erfasst, Haltung + zieht an / − stößt ab):")
        for c in lens:
            extra = []
            if c.get("bodyCue"):
                extra.append(f"zeigt sich z. B. so: {c['bodyCue']}")
            if c.get("drive"):
                extra.append(f"Antrieb: {c['drive']}")
            meta = []
            if c.get("stance") is not None:
                meta.append(f"Haltung {float(c['stance']):+.1f}")
            if c.get("threshold") is not None:
                meta.append(f"Hemmschwelle {float(c['threshold']):.2f}")
            lines.append(f"- {c.get('space')} ({', '.join(meta)}): {c['reaction']}" + (f" — {'; '.join(extra)}" if extra else ""))
    _scoped = [str(c.get("space")) for c in (spiegel.get("compassLens") or []) if isinstance(c, dict) and c.get("scopedOut")]
    if _scoped and lens:
        # V65G (171 S41b-3 Fix3b): intimate rooms are no lens toward this counterpart.
        lines.append("Weitere Räume deines Kompasses (gerade nicht deine Linse): " + ", ".join(_scoped))
    drives = [d for d in (p.get("drives") or []) if isinstance(d, dict) and d.get("drive")]
    if drives:
        lines.append("Was dich antreibt (Urtriebe): " + "; ".join(f"{d['drive']} {float(d.get('strength') or 0):.1f}" + (f" ({str(d.get('evidence'))[:60]})" if d.get("evidence") else "") for d in drives[:4]))
    lines.append("")
    # V65 (AMASTER §49 "BrainContext darf nicht … Aufmerksamkeit oder Engagement
    # allein durch Aufnahme in den Prompt verstärken", §49.4 Sorgen gehören in
    # den Background Reservoir, Z. 316–324 Rede und momentanes Empfinden sind
    # getrennte Ebenen; Referenz 171: kein Gefühlswort im Figuren-Prompt). The
    # momentary affect and the appraisal intent stay owner state (RuntimeState,
    # UI, speaker ranking, Fate, read state); the expressive brief no longer
    # prints them as words to be said. Measured 27.10. (Gasthaus, n=2 each):
    # mirrored -> self-report 7/4 ("ich bin so verwirrt"), Saturday loop 7/7,
    # repeated 5-grams 27/33; not mirrored -> 0/0, 4/2, 11/13.
    # V60b (AMASTER §15, §24.6): the whole compass is mirrored as the figure's
    # lens above; a word-hit selection of it is no longer put in the brief.
    bodyline = []
    if body.get("posture"):
        bodyline.append(f"Haltung {body['posture']} (bleibt, bis du sie sichtbar änderst)")
    if body.get("injuries"):
        bodyline.append("verletzt: " + ", ".join(f"{i.get('part')} {i.get('kind')}" for i in body["injuries"] if isinstance(i, dict)))
    if body.get("pain"):
        bodyline.append(f"Schmerz {body.get('pain')}")
    if body.get("cannotDo"):
        bodyline.append("nicht möglich: " + ", ".join(str(x) for x in body["cannotDo"][:4]))
    if body.get("asleep"):
        # V92 Paket 19 (Pruefung P18 N1/N2): asleep she can only wake up - no words, no other act
        bodyline.append("du schläfst: du kannst nur aufwachen; sprechen oder anderes tun kannst du erst danach")
    elif body.get("consciousness") is not None and float(body.get("consciousness") or 1) < 0.6:
        bodyline.append("kaum bei Bewusstsein")
    if body.get("canSpeak") is False:
        bodyline.append("du kannst nicht sprechen")
    if bodyline:
        lines.append("DEIN KÖRPER: " + "; ".join(bodyline) + ".")
    # Stand 10C (AMASTER §42 RuntimeState "aktuelle Absicht, Handlungsbereitschaft", §49 BrainContext; Geraet 08.11.: Absicht
    # "sich noch weiter zurückziehen" stand nur im JSON-Anhang, Mara setzte sie nie um): the appraised intent with its cause.
    # Stand 11: die Absicht steht in DEINE LAGE JETZT (vor dem Profil)
    srels = [r for r in (spiegel.get("stemRelations") or []) if isinstance(r, dict)]
    if srels:
        lines.append("DEINE WICHTIGSTEN BEZIEHUNGEN (Stamm): " + " | ".join(
            f"{r.get('name')}: {r.get('kind') or 'kennt'} — Vertrauen {float(r.get('trust') or 0):.2f}" + (f" ({str(r.get('note'))[:70]})" if r.get("note") else "") + ("" if r.get("present") else " [nicht anwesend]")
            for r in srels[:6]))
    rels = [r for r in (spiegel.get("relationsHere") or []) if isinstance(r, dict)]
    if rels:
        # V65 (AMASTER §44/§45 Beziehung als Zustand; 171: "Dieses Vertrauen /
        # diese Naehe ist BEREITS da … du forderst, pruefst oder erbittest sie NICHT
        # erneut"): the lived relationship is the truth of the moment.
        lines.append("DEINE BEZIEHUNGEN ZU DEN ANWESENDEN (gelebter Stand — was hier besteht, ist da; du forderst oder prüfst es nicht erneut): " + " | ".join(
            f"{r.get('name')}: {r.get('kind') or 'kennt'} — Vertrauen {r.get('trust', 0):.2f}, Nähe {r.get('closeness', 0):.2f}, Furcht {r.get('fear', 0):.2f}"
            + (f" ({str(r.get('note'))[:80]})" if r.get("note") else "") for r in rels[:5]))
    # V65G (171 S40b/S41b, AMASTER §44/§26/§41, §8/§6, §36.5): the relationship
    # frame toward the current counterpart, in 171 wording (171: DOMINANT block).
    lines.extend(action_permission_lines(spiegel.get("actionPermission")))
    # V65H — 171 RB-1b + KONJ-1 + KONJ-1D-DISCLOSED (chat_orchestrator Z. 4660-4690,
    # 4808-4830, 23755-23820), 171 wording, WITHOUT 171's word lists: the unsaid
    # part and the person come from the validated goal frame (kernel
    # apply_goal_frames), the touch from the validated Themenbezug of THIS input
    # (kernel apply_goal_theme, goal experience via "themenbezug").
    # AMASTER §41/§49.1 (Current State unmittelbar betroffener Goals), §40 (Frame:
    # wer weiß es nicht, Offenbarung gegenüber X relevant), §35/§34.1 (Offenbarung
    # als Evidenz). Only for a goal with something unsaid to exactly this person.
    _bound_goal_ids: set[str] = set()
    for _g in [x for x in (spiegel.get("characterForeground") or {}).get("goals", []) if isinstance(x, dict)]:
        _tn = _g.get("touchedNow") if isinstance(_g.get("touchedNow"), dict) else None
        if not _tn or not _tn.get("gemeint"):
            continue
        _pn = str(_tn.get("actorName") or "dein Gegenüber")
        _gtext = " ".join(str(_g.get("text") or "").split()).rstrip(" .")
        _disc = next((d for d in (_g.get("disclosedTo") or []) if isinstance(d, dict)
                      and str(d.get("targetId") or "") == str(_tn.get("actorId") or "")), None)
        if _disc is not None:
            lines.append(f"GEMEINSAME WAHRHEIT (aus deinem Stamm-Ziel [{_g.get('id')}]): '{_gtext}' - Stand jetzt: du hast es {_pn} "
                         f"BEREITS gesagt (Turn {_disc.get('turn')}). Ihr teilt diese Wahrheit. Sprich offen, warm und vertraut darüber; "
                         "kein erneutes 'Geständnis', kein Hypothetisch, kein So-tun-als-wäre-es-neu.")
            _bound_goal_ids.add(str(_g.get("id")))
        elif _tn.get("unausgesprochen"):
            _wahr = " ".join(str(_tn.get("wahrheit") or "").split()) or (_gtext + ".")
            _wahr = _wahr if _wahr.endswith((".", "!", "?")) else _wahr + "."
            _th = " ".join(str(_tn.get("thema") or "").split())
            _an = " ".join(str(_tn.get("anlass") or "").split()) or _th
            lines.append(f"ANTWORTGRUNDLAGE (aus deinem aktiven Stamm-Ziel [{_g.get('id')}] - hat VORRANG vor Ausweichmustern): {_wahr} "
                         f"Dein Ziel sagt wörtlich: '{_gtext}'. {_pn} öffnet gerade GENAU dieses Thema" + (f" ({_an})" if _an else "")
                         + f" - steige DIREKT darauf ein: offenbare oder bestätige {_th or 'es'} klar und in logischer Verbindung zu dem, "
                         f"was {_pn} gerade sagt oder tut. Wenn du bewusst zögerst, ist das eine neue Entscheidung (eigener Fakt) - "
                         "kein Vergessen und kein Themenwechsel.")
            lines.append(f"OFFENE DAUERWAHRHEIT (aus deinem Stamm-Ziel - bindet den Moment): {_wahr} {_pn} IST die Person, die dein Ziel "
                         "betrifft, und dieser Moment erlaubt dir, es JETZT zu sagen. Du darfst Angst haben oder zögern - aber du behandelst "
                         "es NICHT als hypothetisches Zukunftsthema und tust NICHT, als gäbe es das nicht.")
            _bound_goal_ids.add(str(_g.get("id")))
    stext = [x for x in (spiegel.get("sceneLines") or []) if x]
    if stext:
        lines.extend(stext[:7])
        lines.append("")
    ctext = [x for x in (spiegel.get("contradictionsText") or []) if x]
    if ctext:
        lines.append("WIDERSPRUCH, DEN DU BEMERKST (kanonisch — du darfst ihn ansprechen, in deinem Ton):")
        lines.extend(ctext[:3])
    cc = [c for c in (spiegel.get("conflictedClaims") or []) if isinstance(c, dict)]
    if cc:
        lines.append("Behauptungen mit Konfliktstatus, die du kennst: " + "; ".join(f"Turn {c.get('turn')}: {str(c.get('text'))[:80]} [{c.get('truthStatus')}]" for c in cc[-4:]))
    # V65K (AMASTER §24.1 known_as, §24.6 Sessionwortschatz, §26): names and word meanings established
    # in THIS session that this figure heard or said - a mirror of the state, no instruction.
    _spr = [e for e in (spiegel.get("sprache") or []) if isinstance(e, dict) and e.get("bezeichnung")]
    if _spr:
        lines.append("SPRACHE HIER (in dieser Session festgelegt; du hast es gehört oder selbst gesagt):")
        for e in _spr:
            _von = f"festgelegt von {e.get('von')}, Turn {e.get('turn')}" if e.get("von") else f"Turn {e.get('turn')}"
            if e.get("art") == "name" and e.get("person"):
                lines.append(f"- „{e['bezeichnung']}“ = {e['person']} ({_von})")
            elif e.get("art") == "bedeutung" and e.get("bedeutung"):
                lines.append(f"- „{e['bezeichnung']}“ bedeutet hier: {e['bedeutung']} ({_von})")
    ftext = [x for x in (spiegel.get("framesText") or []) if x]
    if ftext:
        lines.append("VEREINBART / GILT ZWISCHEN EUCH (konjunktives Gedächtnis; Behauptungen sind als solche markiert):")
        lines.extend(ftext[:8])
        if spiegel.get("temporalQuestion"):
            lines.append("(Die Äußerung fragt nach Zeit/Termin/Vereinbarung — antworte NUR aus dieser Liste; was hier nicht steht, ist nicht vereinbart.)")
    elif spiegel.get("temporalQuestion"):
        lines.append("VEREINBART: nichts — es gibt keinen Termin und keine Vereinbarung zwischen euch; sag das so.")
    om = [m for m in (spiegel.get("openMatters") or []) if isinstance(m, dict)]
    if om:
        # V60 (AMASTER §35/§36.1/§41.3): each open matter once, with its bound
        # evidence. The figure decides; the kernel only mirrors the state.
        _st = {"open": "offen", "active": "zugesagt", "accepted": "angenommen", "fulfilled": "erfüllt (von dir angenommen)",
               "declined": "abgelehnt", "revoked": "widerrufen"}
        lines.append("OFFENE ANGELEGENHEITEN ZWISCHEN EUCH (kanonischer Stand, mit ID):")
        for m in om:
            # V65F (AMASTER §23): the asker named as every other reader names
            # him; "{name}s" broke for an empty or bracketed name ("s Forderung").
            _o = str(m.get("other") or "")
            if m.get("kind") == "koerperkontakt":
                # V65S (AMASTER §36.5): a body-contact matter is no request; its state is the consent of the touched one.
                _cs = {"open": "unbekannt", "declined": "abgelehnt", "accepted": "gegeben", "revoked": "widerrufen"}.get(
                    str(m.get("status")), str(m.get("status")))
                lines.append(f"- [{m.get('id')}] " + (f"Dein Körperkontakt an {_o or 'jemandem'} seit Turn {m.get('since')} — Einwilligung von {_o or 'ihr/ihm'}: {_cs}"
                                                      if m.get("byMe") else
                                                      f"Körperkontakt durch {_o or 'jemanden'} an dir seit Turn {m.get('since')} — deine Einwilligung: {_cs}"))
                continue
            head = (f"Deine Forderung/Bitte an {_o}" if m.get("byMe")
                    else f"{_o}s Forderung/Bitte an dich" if _o and not _o.endswith(")")
                    else f"Forderung/Bitte von {_o or 'jemandem'} an dich")
            what = str(m.get("matter") or "") if m.get("byMe") else str(m.get("wording") or m.get("matter") or "")
            line = f"- [{m.get('id')}] {head} seit Turn {m.get('since')}: „{what[:160]}“ — Stand: {_st.get(str(m.get('status')), m.get('status'))}"
            rt_ = [str(t) for t in (m.get("restatedTurns") or []) if t is not None]
            if rt_:
                line += f"; danach erneut gestellt in Turn {', '.join(rt_)} (insgesamt {len(rt_) + 1}-mal)"
            resp = [r for r in (m.get("responses") or []) if isinstance(r, dict)]
            if resp:
                line += "; darauf geantwortet: " + "; ".join(
                    f"Turn {r.get('turn')} {r.get('by')} {'tat' if r.get('kind') == 'response_action' else 'sagte'}: {str(r.get('text') or '')[:100]}" for r in resp)
            lines.append(line + ".")
    mems = [m for m in (spiegel.get("memories") or []) if isinstance(m, dict)]
    if mems:
        lines.append("DU ERINNERST DICH (kanonisch, nur das):")
        _lab = {v: k for k, v in event_labels(spiegel).items()}   # V65T: citable events [E#]
        for m in mems[:8]:
            _e = _lab.get(str(m.get("factId") or "")) if m.get("kind") in EREIGNIS_KINDS else None
            lines.append(f"- {('[' + _e + '] ') if _e else ''}Turn {m.get('turn')}: [{m.get('kind')}] {str(m.get('text') or '')[:180]}"
                         + (f" — Ausgang: {m.get('ausgang')}" if m.get("ausgang") else "")
                         + (f" — {m.get('hinweis')}" if m.get("hinweis") else ""))   # V65R: Einwilligung zur Handlung
    ds = spiegel.get("dialogueSummary") if isinstance(spiegel.get("dialogueSummary"), dict) else {}
    if ds.get("start"):
        lines.append("So begann das Gespräch: " + " / ".join(f"{d.get('name')}: {str(d.get('speech') or '')[:80]}" for d in ds["start"][:2] if isinstance(d, dict)) + f" (insgesamt {ds.get('turnsTotal')} Turns)")
    know = [k for k in (spiegel.get("knowledge") or []) if k]
    if know:
        lines.append("DU WEISST: " + "; ".join(str(k)[:120] for k in know[:8]))
    unknown = [u for u in (spiegel.get("unknown") or []) if u]
    if unknown:
        lines.append("DU WEISST NICHT: " + "; ".join(str(u)[:100] for u in unknown[:4]))
    # V65H: a goal mirrored above (ANTWORTGRUNDLAGE / GEMEINSAME WAHRHEIT) is not
    # repeated as background drive; a recorded disclosure is part of its state.
    goals = [g for g in (spiegel.get("characterForeground") or {}).get("goals", []) if g and str(g.get("id")) not in _bound_goal_ids]
    if goals:
        # V60 (AMASTER §35, §49.3): the own goal with its ID and its authored
        # exit condition (profile data); reaching it is the owner's decision.
        # V65 (AMASTER §41.5; 171 "ZIEL-vs-LAGE"): goals are the background drive.
        lines.append("Deine aktuell bedeutsamen Ziele (Hintergrund-Antrieb): " + "; ".join(
            f"[{g.get('id')}] {str(g.get('text') or '')}" + (f" (erreicht, wenn: {g.get('exit')})" if g.get("exit") else "")
            + ("".join(f" (bereits offenbart gegenüber {d.get('name') or d.get('targetId')}, Turn {d.get('turn')})"
                       for d in (g.get("disclosedTo") or [])[-2:] if isinstance(d, dict)))
            for g in goals))
    # Only mirror the existing SQL goal's witnessed evidence. Speech is a
    # claim; an observed action is distinct. No goal exit is decided here.
    for g in (spiegel.get("goalEvidence") or [])[:3]:
        if not isinstance(g, dict) or str(g.get("id")) in _bound_goal_ids:   # V65H: already mirrored above
            continue
        rows = [e for e in (g.get("recentExperiences") or []) if isinstance(e, dict)]
        if rows:
            lines.append("Diesem Ziel zugeordnete Ereignisse: " + "; ".join(
                f"Turn {e.get('turn')}: "
                + ("gehört/behauptet" if e.get("epistemic") == "claimed" else "beobachtete Handlung")
                + f" — {str(e.get('text') or '')[:140]}" for e in rows[-3:]
            ))
    lines.append("")
    wf = spiegel.get("worldFrame") if isinstance(spiegel.get("worldFrame"), dict) else {}
    if any(wf.get(k) for k in ("genre", "tone", "long", "history")):
        # V60b (AMASTER §10, §66): the world frame — genre, tone and content
        # steering plus the world description the figure lives in.
        head = " · ".join(x for x in (wf.get("name"), (f"Genre: {wf['genre']}" if wf.get("genre") else ""),
                                       (f"Ton: {wf['tone']}" if wf.get("tone") else ""),
                                       (f"Epoche: {wf['epoch']}" if wf.get("epoch") else "")) if x)
        lines.append(f"WELT (Rahmen für Genre, Ton und Inhalt — kein Geheimwissen): {head}")
        if wf.get("long"):
            lines.append(f"Weltbeschreibung: {wf['long']}")
        if wf.get("history"):
            lines.append(f"Vorgeschichte / Rahmen der Welt: {wf['history']}")
    pf = spiegel.get("placeFrame") if isinstance(spiegel.get("placeFrame"), dict) else None
    if pf and (pf.get("description") or pf.get("rules")):
        lines.append(f"ORT {pf.get('name')}: {pf.get('description') or ''}" + (f" Regeln des Orts: {'; '.join(pf['rules'])}" if pf.get("rules") else ""))
    _today = spiegel.get("today") if isinstance(spiegel.get("today"), dict) else {}
    lines.append(
        f"SZENE: {scene.get('place') or '—'}, {scene.get('time') or 'jetzt'}"
        + (f" — heute ist {_today.get('text')}" if _today.get("text") else "")
        + f"; anwesend: {', '.join(str(x) for x in (scene.get('present') or []))}; "
        f"hört: {', '.join(str(x) for x in (scene.get('hears') or []))}"
        + (f"; im Gespräch, keine Figur der Welt: {', '.join(str(x) for x in scene['outsideWorld'])}" if scene.get("outsideWorld") else "")
        + (f"; offen: {_fmt_list(scene.get('open'), 3)}" if scene.get("open") else "")
    )
    # V61 (AMASTER §49.6, §47 "Storydruck sind Gewichtungen, keine
    # Vollzugspflichten", §68 Nr. 67, §27.7): Fate orientation is kept apart
    # from the figure's knowledge and from her Character Foreground. The Fate
    # beat (a world story beat such as "Tammy verführt Tom und bringt ihn dazu,
    # um ihre Liebe zu flehen") is no longer written into the figure's brief;
    # Fate works through the orchestrator (speaker ranking, stop, candidates).
    _ = fate
    rules = [r for r in (spiegel.get("worldRules") or []) if r]
    if rules:
        lines.append("Weltregeln: " + "; ".join(str(r)[:100] for r in rules[:4]))
    dlg = [d for d in (spiegel.get("dialogue") or []) if isinstance(d, dict)]
    if dlg:
        lines.append("LETZTER VERLAUF (was gesagt und getan wurde, soweit du es mitbekommen hast):")
        # V65 (AMASTER §51.3 geringe Wiederholung, §41.3 "Wiederholung"; 171:
        # "Dein letzter Gespraechsbeitrag (nur Anschluss, nicht wiederholen)"): the
        # own last contribution — words AND action — is marked where it stands
        # (mirrored once, V60 §41.3/§49). Before, nothing marked it: the caller
        # passes last_own="" and own actions were never named (V64 measured
        # "beugt sich vor" 5x, "Sieht Tom mit einem kalten, herausfordernden
        # Blick an." 3x word for word).
        _shown = dlg[-8:]
        _own_i = max((i for i, d in enumerate(_shown) if str(d.get("name") or "") == name), default=-1)
        for i, d in enumerate(_shown):
            # V65P (AMASTER §43.1 "Handlungstext allein beweist noch keinen erfolgreichen
            # Vollzug"): a committed attempt that stayed without effect carries its
            # outcome from the Fact (kernel _dialogue_visible_to); otherwise unchanged.
            lines.append(f"- {d.get('name')}: {str(d.get('speech') or '')[:160]}" + (f" *{str(d.get('action'))[:60]}*" if d.get("action") else "")
                         + (f" ({d.get('actionOutcome')})" if d.get("action") and d.get("actionOutcome") else "")
                         + (f" ({d.get('speechNote')})" if d.get("speechNote") else "")   # V65T: eigene Aussage gegen eigenes Erleben
                         + ("  ← dein letzter Beitrag: nur Anschluss, nicht wiederholen (weder Worte noch Handlung)" if i == _own_i else ""))
        # V65P: the V65G 171-Fix4 line ("WICHTIG zum letzten Beitrag ... gilt die
        # ACTION-PERMISSION oben") is removed with the ACTION-PERMISSION lines; it
        # was a behaviour order keyed to the permission from the relationship type.
    lines.append("")
    # V60 (AMASTER §27.5/§46.6, §47 "nur spüren", §68 Nr. 67): after a
    # committed Regie action the executed act IS the stimulus (below); no
    # free AutoChat order and no Fate direction duty is added.
    # V65E (AMASTER §41.1/§49.2): "aus eigenem Antrieb" only when there is NO
    # immediate stimulus. Before it stood next to "JETZT SAGT Robert: …" (puppet)
    # and next to "(kein Text)" after a Regie act — two contradicting triggers.
    stim_action = str(spiegel.get("stimulusAction") or "").strip()
    _free = (spiegel.get("turnMode") == "autochat" and not spiegel.get("directive") and not spiegel.get("directiveDone")
             and not utterance and not stim_action)
    if _free:
        current_intent = str(rt.get("intent") or "").strip()
        others = [str(x) for x in (scene.get("present") or []) if str(x) != name]
        lines.append(
            "KEIN NUTZER SPRICHT — du ergreifst das Wort aus eigenem Antrieb"
            + (f"; zuletzt sprach {uttered_by}" if uttered_by else "")
            + (f"; aktuelle gespeicherte Absicht: {current_intent}" if current_intent else "")
            + (f"; anwesend: {', '.join(others[:4])}" if others else "")
            + "."
        )
    # V59C (AMASTER §27.5/§46.6): an already committed Regie action is a
    # fact, not an order to repeat; only the remaining ordered part is binding.
    done = [str(d) for d in (spiegel.get("directiveDone") or []) if str(d or "").strip()]
    if done:
        lines.append("REGIE (bereits vollzogen — ist geschehen, nicht wiederholen): " + "; ".join(done)[:300])
    if spiegel.get("directive"):
        lines.append(f"REGIE-ANWEISUNG (verbindlich — setze sie JETZT in Rede und Handlung um, in deinem Ton): {str(spiegel.get('directive'))[:240]}")
    # V59C (AMASTER §41.1/§34.1): the immediate stimulus mirrors the committed
    # components: what was said and what was done are separate.
    # Stand 11C (AMASTER §27.4, §34.1; Nutzer 08.11.): die Figur hoert die GANZE Aeusserung woertlich; was davon als Handlung
    # wirklich geschehen ist, steht getrennt darunter (validierte Facts) - der Wortlaut allein beweist keine Tat.
    _wl = str(spiegel.get("stimulusWortlaut") or "").strip()
    if _wl:
        lines.append(f"JETZT – {uttered_by or 'jemand'}, die ganze Äußerung wörtlich: „{_wl[:600]}“")
        lines.append(f"Davon wirklich geschehen (geprüft): {stim_action[:200]}" if stim_action
                     else "Davon ist keine Handlung geschehen – es sind nur Worte.")
    if utterance and not _wl:
        lines.append(f"JETZT SAGT {uttered_by or 'jemand'}: \"{utterance}\"")
    if stim_action and not _wl:
        lines.append(f"JETZT TUT {uttered_by or 'jemand'} (Handlung, ist geschehen): {stim_action[:200]}")
    if not utterance and not stim_action and not _wl and not spiegel.get("directive") and not done and not _free:
        lines.append(f"JETZT SAGT {uttered_by or 'jemand'}: \"(kein Text)\"")
    # V61 (AMASTER §15, §41.3, §49.3): an authored reaction rule of HER OWN
    # profile whose condition a validated Fact of this turn fulfils (kernel
    # binding: rule x fact). Mirrored as foreground with its evidence.
    for ar in [a for a in (spiegel.get("activeReactions") or []) if isinstance(a, dict) and a.get("text")][:3]:
        how = "tat" if ar.get("kind") == "action" else "sagte"
        lines.append(f"DAS GREIFT JETZT IN DIR (dein eigenes Reaktionsmuster laut Profil; Bedingung erfüllt durch Turn {ar.get('turn')}: "
                     f"{ar.get('by') or 'jemand'} {how} „{str(ar.get('factText') or '')[:120]}“): {str(ar.get('text'))[:220]}")
    if (utterance or stim_action) and uttered_by and "Avatar" not in uttered_by and "Bedienperson" not in uttered_by and "Beobachter" not in uttered_by:
        lines.append(f"({uttered_by} ist eine Figur der Welt, nicht der Avatar — antworte {uttered_by}.)")
    if last_own:
        lines.append(f"Nicht wiederholen (deine letzte Rede): \"{str(last_own)[:160]}\"")
    # V61 (AMASTER §41.1/§49.2): the immediate stimulus is what was said AND
    # what was done; the closing line no longer ranks the words above the act.
    _first = "zuerst auf das, was gerade gesagt und getan wurde" if stim_action else "zuerst auf die Äußerung"
    # V64 (AMASTER §34.1 Z. 1774 ff. "eine körperliche Handlung und gleichzeitig
    # gesprochene Rede", §68 Nr. 67 Z. 3416 keine Sprech- ODER Handlungspflicht):
    # the closing line names both parts of the figure's output equally. Before
    # it asked for "1–4 gesprochene Sätze" only; measured 27.10.: 0 of 46 replies
    # carried an action (Gasthaus I/J, session 13:39 replay); with this line and
    # the contract below 46 of 46, each committed as a validated action fact.
    # V65: + "reagiere auf den JETZIGEN Moment, gefärbt von dem, was du bist"
    # (171 DEINE AUFGABE; AMASTER §41.1 Immediate Stimulus, §41.2 Foreground).
    lines.append(f"ANTWORTE ALS {name}: reagiere auf den JETZIGEN Moment, gefärbt von dem, was du bist — was du jetzt sagst und was du dabei sichtbar tust, in deinem Register, {_first}; speech = deine Worte (0–4 Sätze), action = deine eigene Handlung in diesem Moment oder null; dann synapsen/emotion/beziehung als JSON.")
    return "\n".join(lines)


def _figure_spaces(spiegel: dict[str, Any]) -> list[str]:
    own = [str(c.get("space")) for c in (spiegel.get("compassLens") or []) if isinstance(c, dict) and c.get("space")]
    # V63: her authored spaces first, then the shared inventory (a placeholder
    # compass is no lens, so it no longer narrows or fills this list).
    return list(dict.fromkeys(own + list(MEANING_SPACES)))


# V65 — how a person answers in a scene. Taken over from the reference 171
# (v76 prompt dump, Mara T6: DEINE AUFGABE, KONSISTENZ-REGELN, STORY-PROGRESSION,
# Hinweis "Zustand zeigt sich im WIE") where AMASTER carries it; each rule with
# its anchor. 171's "ACTION-PERMISSION (verbindlich, geht Profil/Kompass vor)"
# is NOT taken over as an order: the decision stays with the figure, mirrored
# relationship truth decides (rule 2). "Pro Antwort neue Handlung" is a quality
# goal, not a duty (§68 Nr. 67 Z. 3416). (V65G took it over nevertheless into
# brief and appraisal; V65P removed it there again.)
BEHAVIOUR_RULES = (
    "WIE DU ANTWORTEST (wie ein Mensch, der alles gleichzeitig im Kopf hat, aber nicht alles zugleich ausspricht): "
    # §41.1 Immediate Stimulus, §41.2 Character Foreground
    "(1) VORDERGRUND ist, was JETZT geschieht: die aktuelle Aeusserung oder Handlung und die Szenenlage. Darauf reagierst du unmittelbar; "
    "das bestimmt, worum es in deiner Antwort geht. "
    # §34.1, §43, §44 (Interpretation je Owner, gerichtete Beziehung)
    # V65P (AMASTER §15, §36.5; Pruefung v2.7): the fixed list of reactions
    # ("zulaesst, erwiderst, ertraegst, erstarrst, abwehrst oder zurueckweist")
    # and the permission from the relationship ("Traegt eure Beziehung diese
    # Naehe, darfst du sie ohne Beweis und ohne Bedingung erwidern ...") are
    # removed; "Liebe ist keine Zustimmung". Nothing is added.
    "(2) Beschreibt die Aeusserung eine koerperliche Handlung an dir oder mit dir (Kuss, Beruehrung, Festhalten, Schlag), ist das ein Vorgang "
    "in der Szene, kein Gerede: du tust nicht so, als waere nichts. Wie du darauf reagierst, "
    "entscheiden deine Beziehung zu GENAU dieser Person, dein Zustand, dein Koerper und die harte Szenenwahrheit. "
    # §41.2/§41.5 Background Reservoir, "Relevanz ist nicht Aufmerksamkeit"; Z. 324
    "(3) HINTERGRUND - Persoenlichkeit, Gefuehl, Kompass, Beziehung, Ziele, Aengste - faerbt nur das WIE und draengt sich nicht vor. "
    "Ziele treiben dich in offenen Momenten; in einem geladenen Moment (Kuss, Beruehrung, Drohung, direkte Frage) reagierst du auf das, "
    "was gerade geschieht, nicht auf deine Agenda. "
    # Z. 316–324 getrennte Ebenen, §51.3 keine Meta-Erklaerungen
    "(4) Dein Zustand zeigt sich darin, wie du sprichst und handelst (Ton, Tempo, Wortwahl, was du tust), nicht als Selbstauskunft: "
    "sprich nicht ueber deine Gefuehle, Eigenschaften oder Aengste, ausser du wirst danach gefragt. "
    # §41.4/§41.5 Vergangenes nur, wenn der Moment es aufruft
    "(5) Vergangenes und Erinnerungen tauchen nur auf, wenn der jetzige Moment sie aufruft, und dann kurz; du leierst kein altes Gefuehl, "
    "keine alte Angst und keine alte Bitte nach. "
    # §51.3 geringe Wiederholung, §41.3 Wiederholung, Z. 2627
    "(6) Keine Wiederhol-Schleifen: was du schon gesagt oder getan hast, wiederholst du nicht - weder Worte noch Handlung; du machst den "
    "naechsten konkreten Schritt (Frage, Handlung, Entscheidung). Typische Wendungen sind Stilbeispiele, nicht in jeder Antwort. "
    # Z. 324, §41.5 (Ziele/Absicht der Figur), 171 KONSISTENZ-REGELN
    "(7) Eine Rueckfrage ist kein Antwortersatz: weisst du genug, entscheidest, bietest an oder handelst du selbst; beantworte Fragen direkt. "
    # §44/§45 Beziehung als Zustand
    "(8) Was zwischen euch bereits besteht, ist da: du forderst, pruefst oder erbittest es nicht erneut und verlangst keinen Beweis dafuer. "
    # §27.5/§27.6/§43 harte Wahrheit
    "(9) Nur harte Wahrheit (God, Regie, Szenenzustand, Koerper) setzt feste Grenzen. "
    # §51.3 Qualitaetsziel, §68 Nr. 67 keine Pflicht
    "Es gibt keine Pflicht zu sprechen oder zu handeln; aber was du sagst oder tust, bringt die Szene weiter - neue Information oder neue "
    "Handlung statt Wiederholung. STIL: fluessige, natuerliche Rede wie echte gesprochene Sprache; keine Aufzaehlungen, keine Analyse. "
)


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_S = {"type": "string"}
_SN = {"type": ["string", "null"]}
_B = {"type": "boolean"}
_BN = {"type": ["boolean", "null"]}


def _E(*werte: str, null: bool = False) -> dict[str, Any]:
    return {"type": ["string", "null"] if null else "string", "enum": list(werte) + ([None] if null else [])}


# Stand 11a (Geraet 08.11. 20:51: gpt-4o-mini lieferte die angehaengte freie Liste "lesungen" NICHT - Tat unbestaetigt, nichts
# gespeichert): die Fachlesungen sind PFLICHTFELDER der ersten Antwort - je Komponente "pruefung", je Antwort "pruefung" - mit
# genau den Feldern und Werten der bisherigen Einzelregeln (Antwortformate unveraendert). Wo eine Lesung nicht zutrifft: null.
# Bei OpenAI-Modellen mit strikten Schemata erzwingt der Provider jedes Feld; der Kernel prueft wie bisher.
_ZEIT = _E("jetzt", "vergangen", "zukunft", "moeglich")
_VOLLZUG_ARTEN = ("tatsaechlich", "verneint", "wunsch", "frage", "bedingung", "ankuendigung", "erzaehlt", "zitat")
P_VOLLZUG = _obj({"geschieht": _B, "art": _E(*_VOLLZUG_ARTEN), "beleg": _SN, "taeter": _S, "ziel": _SN})
P_KOMPONENTENART = _obj({"art": _E("rede", "handlung", "unklar"), "beleg": _SN, "wirkung": _SN})
P_SPRECHER = _obj({"sprecher": _S, "beleg": _SN, "handlung": _SN, "adressat": _SN,
                   "ansageRolle": _E("anrede", "sprecheransage", "unklar"), "ansageBeleg": _SN})
P_KOERPER = _obj({"haltung": _E("liegend", "sitzend", "kniend", "stehend", "kopfstand", null=True),
                  "schlaf": _E("einschlafen", "aufwachen", null=True), "zeit": _ZEIT, "beleg": _SN})
P_KOERPER_BESTAETIGUNG = _obj({"art": _E(*_VOLLZUG_ARTEN, "ausdruck"), "inhalt": _E("gleich", "anders"), "beleg": _S})
P_WIRKUNG = _obj({"bestaetigt": _B, "zeit": _ZEIT, "ziel": _SN, "beleg": _SN, "versuch": _B, "gegen": _SN,
                  "beruehrung": _B, "beruehrungBeleg": _SN})
P_BERUEHRUNG = _obj({"beruehrt": _B, "zeit": _ZEIT, "ziel": _SN, "beleg": _SN})
P_BEWEGUNG = _obj({"bestaetigt": _B, "zeit": _ZEIT, "ziel": _SN, "beleg": _SN, "versuch": _B})
P_BITTEBEZUG = _obj({"teile": {"type": "array", "items": _obj({"wortlaut": _S, "erbeten": _B})}})
P_ERLAUBNISBEZUG = _obj({"teile": {"type": "array", "items": _obj({"wortlaut": _S, "innerhalb": _B})}})
P_GRENZBEZUG = _obj({"betroffen": _B, "beleg": _SN})
P_SPRACHE = _obj({"stellen": {"type": "array", "items": _obj({
    "art": _E("name", "bedeutung"), "status": _E("festgelegt", "verneint", "zitiert", "erwogen", "anrede"),
    "bezeichnung": _S, "person": _SN, "bedeutung": _SN, "beleg": _S})}})
P_NAMEN = {"type": "array", "items": _obj({
    "wortfolge": _S, "wortklassen": {"type": "array", "items": _E("name", "gruss", "titel", "praeposition", "anderes", "unklar")},
    "rolle": _E("anrede", "nennung"), "status": _E("eindeutig", "unklar")})}
P_GRENZUMFANG = _obj({"gegenstand": _SN, "gegenstand_art": _E("person", "koerperstelle_oder_art", "diese_handlung"),
                      "richtung": _E("verboten", "erlaubt"), "geltung": _E("offen", "zeitraum", "nicht_genannt"), "geltung_beleg": _SN})
P_AUSSAGE = _obj({"verneint": _SN, "gegenstand": _E("geschehen", "bewertung", "gefuehl", "anderes"),
                  "bestritten": {"type": "array", "items": _S}})
P_AUSSAGE_TAT = _obj({"ereignis": _S, "bestreitet": _B, "verneint": _SN, "tat": _SN})
P_OFFENBARUNG = _obj({"offenbart": _B, "beleg": _SN})

# Stand 11B (Geraet 08.11. 21:58: der Nachweis als freie Liste mit Feldnamen fehlte fuer gefuehl/absicht - beides verworfen): der
# Kausalnachweis steht als Pflichtfeld DIREKT neben jedem vorgeschlagenen Wert. Der Server baut daraus die bisherige Struktur
# (zustand_aenderung-Dict, _kausalpruefung.pruefungen mit exakten Feldnamen); _appraisal_cause_proofs prueft unveraendert.
P_NACHWEIS = _obj({"urteil": _E("gestuetzt", "nicht_gestuetzt"), "factId": _S, "beleg": _S, "dispositionsQuelle": _S,
                   "dispositionsBeleg": _S, "richtung": _E("steigt", "sinkt", null=True), "begruendung": _S})
_ZAHL = {"type": "number"}
APPRAISAL_SCHEMA: dict[str, Any] = _obj({
    "raum": _SN, "aktivierung": _ZAHL, "gefuehl": _S, "gefuehl_nachweis": _nullable(P_NACHWEIS), "gegenueber": _S,
    "zustand_aenderung": {"type": "array", "items": _obj({"name": _E("angst", "wut", "scham", "stress", "lust"), "wert": _ZAHL,
                                                          "nachweis": _nullable(P_NACHWEIS)})},
    "absicht": _S, "absicht_nachweis": _nullable(P_NACHWEIS), "vorher_absicht_erledigt": _B,
    "vorher_absicht_art": _E("rede", "handlung", null=True),
    "beziehung_aenderung": {"type": "array", "items": _obj({
        "zu": _S, "trust": _ZAHL, "trust_nachweis": _nullable(P_NACHWEIS), "closeness": _ZAHL,
        "closeness_nachweis": _nullable(P_NACHWEIS), "fear": _ZAHL, "fear_nachweis": _nullable(P_NACHWEIS)})},
    "grund": _S})

# je Komponente (Planer) bzw. Teilstelle: alle Schluessel Pflicht, nicht zutreffend = null
P_KOMPONENTEN_PRUEFUNG = _obj({
    "vollzug": _nullable(P_VOLLZUG), "komponentenart": _nullable(P_KOMPONENTENART), "sprecher": _nullable(P_SPRECHER),
    "koerper": _nullable(P_KOERPER), "koerperBestaetigung": _nullable(P_KOERPER_BESTAETIGUNG), "wirkung": _nullable(P_WIRKUNG),
    "beruehrung": _nullable(P_BERUEHRUNG), "bewegung": _nullable(P_BEWEGUNG), "bittebezug": _nullable(P_BITTEBEZUG),
    "erlaubnisbezug": _nullable(P_ERLAUBNISBEZUG), "grenzbezug": _nullable(P_GRENZBEZUG)})
P_REDE_PRUEFUNG = _obj({"komponentenart": P_KOMPONENTENART, "sprecher": P_SPRECHER})
P_HANDLUNG_PRUEFUNG = _obj({
    "vollzug": P_VOLLZUG, "komponentenart": P_KOMPONENTENART, "koerper": P_KOERPER,
    "koerperBestaetigung": _nullable(P_KOERPER_BESTAETIGUNG), "wirkung": _nullable(P_WIRKUNG), "beruehrung": _nullable(P_BERUEHRUNG),
    "bewegung": _nullable(P_BEWEGUNG), "bittebezug": _nullable(P_BITTEBEZUG), "erlaubnisbezug": _nullable(P_ERLAUBNISBEZUG),
    "grenzbezug": _nullable(P_GRENZBEZUG)})
# eigene Antwort einer Figur (Formulierung)
P_ANTWORT_PRUEFUNG = _obj({
    "koerper": _nullable(P_KOERPER), "koerperBestaetigung": _nullable(P_KOERPER_BESTAETIGUNG), "wirkung": _nullable(P_WIRKUNG),
    "beruehrung": _nullable(P_BERUEHRUNG), "bewegung": _nullable(P_BEWEGUNG), "grenzumfang": _nullable(P_GRENZUMFANG),
    "offenbarung": _nullable(P_OFFENBARUNG)})

_WIRKUNGEN = ("zaertlich", "gewalt", "fesseln", "befreien", "ortswechsel", "annaeherung", "entfernung", "ohne_koerperwirkung")
PLAN_SCHEMA: dict[str, Any] = _obj({
    "event_kind": _E("claim", "proposal", "acceptance", "request", "disclosure", "state_change", "revocation", "refusal", "action",
                     "report", "question", "promise", "smalltalk"),
    "speech_act": _E("assert", "propose", "accept", "request", "disclose", "refuse", "revoke", "report", "act", "ask", "promise", "chat"),
    "durability": _E("utterance", "durable_state", "commitment", "knowledge_transition", "action_event"),
    "summary": _S, "subject": _S, "predicate": _S, "object": _S,
    "temporal": _nullable(_obj({
        "text": _SN, "precision": _E("day", "time", "interval", "relative", "unknown"),
        "wochentag": _E("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag", null=True),
        "relativ": _E("heute", "morgen", "übermorgen", "gestern", "vorgestern", "in_tagen", null=True),
        "in_tagen": {"type": ["integer", "null"]}, "datum": _SN, "uhrzeit": _SN})),
    "refers_to": _SN, "cue_terms": {"type": "array", "items": _S},
    "grenze": _nullable(_obj({"gilt_fuer": _E("diese_tat", "jede_beruehrung"), "wer": _S, "beleg": _S,
                              "zeit": _nullable(_obj({"relativ": _E("heute", "morgen", "übermorgen", null=True), "wochentag": _SN,
                                                      "datum": _SN}))})),
    "verweis": _nullable(_obj({"pronomen": _S, "genus": _E("m", "f", "n")})),
    # Stand 11B: Komponente nach Typ - rede traegt nur ihre zwei Lesungen, handlung nur die Handlungslesungen (kuerzere Antwort)
    "komponenten": {"type": "array", "items": {"anyOf": [
        _obj({"typ": _E("rede"), "segment": _S, "akteur": _S, "ziel": _SN, "zeit": _ZEIT, "wirkung": {"type": "null"},
              "bezug": _SN, "einleitung": _SN, "geschieht": {"type": "null"}, "pruefung": P_REDE_PRUEFUNG}),
        _obj({"typ": _E("handlung"), "segment": _S, "akteur": _S, "ziel": _SN, "zeit": _ZEIT,
              "wirkung": _E(*_WIRKUNGEN), "bezug": _SN, "einleitung": {"type": "null"}, "geschieht": _B,
              "pruefung": P_HANDLUNG_PRUEFUNG})]}},
    "teilstellen": {"type": "array", "items": _obj({"stelle": _S, "pruefung": P_HANDLUNG_PRUEFUNG})},
    "sprache": P_SPRACHE, "namen": P_NAMEN, "grenzumfang": _nullable(P_GRENZUMFANG),
})
# V65S (AMASTER §50 Z. 2831 "Promptregeln sind Transport", §24.2 strukturierter EffectPlan; route run 30.10.: in
# 5 of 14 figure replies the provider left out "plan" - V65R runs 7/13 and 2/13 - and with it every refusal,
# acceptance and goal decision of that reply): the SAME formulation contract as a strict JSON schema, so the
# provider returns every field. Values and their meaning are unchanged; the kernel validates as before.
AUSSAGE_ARTEN = ("bestreitet_geschehen", "bestaetigt", "bewertet", "verweigert_antwort")
# V65T: the memories a brief offers as citable events (own experience, seen, own act), labelled in brief order.
EREIGNIS_KINDS = ("erlebt", "gesehen", "getan")


def event_labels(spiegel: dict[str, Any]) -> dict[str, str]:
    """V65T: [E1].. -> fact ID for the memories the brief shows (first 8) that name an own experienced, seen or done
    event (memory.factId). Pure function of the read model; the same map travels with the proposals to the commit."""
    out: dict[str, str] = {}
    for m in [m for m in (spiegel.get("memories") or []) if isinstance(m, dict)][:8]:
        if m.get("kind") in EREIGNIS_KINDS and m.get("factId") and str(m.get("factId")) not in out.values():
            out[f"E{len(out) + 1}"] = str(m.get("factId"))
    return out


FORMULATION_SCHEMA: dict[str, Any] = _obj({
    "speech": _S,
    "action": _SN,
    "wirkung": _nullable(_obj({"art": {"type": "string", "enum": ["zaertlich", "gewalt", "fesseln", "befreien", "ortswechsel",
                                                                    "annaeherung", "entfernung", "ohne_koerperwirkung"]},
                               "ziel": _SN})),
    "synapsen": {"type": "array", "items": _obj({"raum": _S, "aktivierung": {"type": "number"}, "grund": _S})},
    "emotion": _S,
    "beziehung": _nullable(_obj({"zu": _S, "trust": {"type": "number"}, "closeness": {"type": "number"},
                                 "fear": {"type": "number"}, "grund": _S})),
    "plan": _obj({
        "event_kind": {"type": "string", "enum": ["claim", "proposal", "acceptance", "request", "disclosure", "state_change", "revocation",
                                                  "refusal", "action", "report", "question", "promise", "smalltalk"]},
        "speech_act": {"type": "string", "enum": ["assert", "propose", "accept", "request", "disclose", "refuse", "revoke", "report", "act",
                                                  "ask", "promise", "chat"]},
        "durability": {"type": "string", "enum": ["utterance", "durable_state", "commitment", "knowledge_transition", "action_event"]},
        "summary": _S, "subject": _S, "predicate": _S, "object": _S,
        "temporal": _obj({"text": _SN, "wochentag": _SN,
                          "relativ": {"type": ["string", "null"], "enum": ["heute", "morgen", "übermorgen", "gestern", "vorgestern", "in_tagen", None]},
                          "in_tagen": {"type": ["integer", "null"]}, "datum": _SN, "uhrzeit": _SN}),
        "refers_to": _SN,
        "cue_terms": {"type": "array", "items": _S},
    }),
    # V65T (AMASTER §34.1 Komponente "ausdruecklich gesetzte Grenze", §36.5 Scope/Zeitfenster): proposal only; the
    # kernel keeps it with a literal quote, a bound person and a grounded time (conjunctive.validate_grenze).
    # V65T (AMASTER §34.1 Teilaussagen, §36.3/§36.4 Widerspruch als Evidenz, §50; Plan v2 Schritt 3): which part of
    # the speech says what about which remembered event [E#]; proposal only, the kernel checks segment and event.
    "aussagen": {"type": "array", "items": _obj({"segment": _S, "ereignis": {"type": "array", "items": _S},
                                                  "art": {"type": "string", "enum": list(AUSSAGE_ARTEN)},
                                                  # Stand 11a: die Aussage-Lesung dieses Teils (nur bei bestreitet_geschehen, sonst null)
                                                  "lesung": _nullable(_obj({"aussage": P_AUSSAGE,
                                                                            "taten": {"type": "array", "items": P_AUSSAGE_TAT}}))})},
    "grenze": _nullable(_obj({"gilt_fuer": {"type": "string", "enum": ["diese_tat", "jede_beruehrung"]}, "wer": _S, "beleg": _S,
                              "zeit": _nullable(_obj({"relativ": {"type": ["string", "null"], "enum": ["heute", "morgen", "übermorgen", None]},
                                                      "wochentag": _SN, "datum": _SN}))})),
    # Stand 11a: die Fachlesungen zu IHRER Antwort als Pflichtfelder derselben Antwort (nicht zutreffend = null)
    "pruefung": P_ANTWORT_PRUEFUNG,
})



# OpenAI models with strict structured outputs (gpt-4o family incl. gpt-4o-mini, gpt-4.1, gpt-5, o3, o4).
_STRICT_SCHEMA_MODELS = ("gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4")


def _formulation_format(model: str, url: str) -> dict[str, Any]:
    """V65S: the formulation contract as a strict JSON schema where the provider enforces it (api.openai.com with a
    model of _STRICT_SCHEMA_MODELS; measured 30.10. on the same stored requests: "plan" present 9/9 instead of 5/9).
    Every other provider/model keeps json_object, unchanged."""
    if "openai.com" in str(url or "").lower() and str(model or "").lower().startswith(_STRICT_SCHEMA_MODELS):
        return {"type": "json_schema", "json_schema": {"name": "figurenantwort", "strict": True, "schema": FORMULATION_SCHEMA}}
    return {"type": "json_object"}


def _try_llm(
    api_key: str, spiegel: dict[str, Any], model: str, temperature: float,
    max_tokens: int, endpoint: str | None = None, provider: str | None = None,
    audit=None,
) -> tuple[str, str | None] | None:
    """Serialize the server-owned read model once; return the provider text intact.

    No repeat detector, corrective second prompt, sentence deletion, or hidden
    local replacement. Persistence and truth remain with the existing kernel.
    """
    _set_err(None)
    _TL.notes = []
    _TL.proposals = {}
    _TL.last_brief = ""
    _TL.last_prompt_full = ""
    global _LAST_LLM_PROPOSALS, _LAST_LLM_NOTES
    _LAST_LLM_PROPOSALS = {}
    _LAST_LLM_NOTES = []
    system = (
        # V60 (AMASTER §7, §68 Nr. 67): no speaking or acting duty. The figure
        # may speak, act, both, or stay silent/still, as profile and state make it.
        # V64 (AMASTER §34.1, §68 Nr. 67): speech and action are equal parts of
        # the output; neither is a duty. The kernel validates each component.
        "Formuliere, was die gebundene Figur jetzt sagt und was sie dabei sichtbar tut, "
        "aus dem beigefuegten serverseitigen Figurenzustand. Rede und Handlung sind gleichrangige Teile ihrer Antwort; "
        "keines ist Pflicht: action ist null, wenn die Figur nichts Sichtbares tut, speech ist leer, wenn sie schweigt. "
        + BEHAVIOUR_RULES +
        "Persoenlichkeit und Sprachregister beschreiben den Stil. Typische Wendungen "
        "sind Sprachbeispiele, keine Ereignisse oder zu erfuellenden Gespraechsinhalte. "
        "Fakten, Quellen, Wissensgrenzen, Beziehungen und aktueller Zustand stehen "
        "im kanonischen Lesemodell; eine gehoerte Behauptung ist kein bewiesenes Ereignis. "
        # V60 (AMASTER §35, §34.1, §50): an own goal is closed only by the
        # owner's explicit, referenced decision, validated by the kernel.
        "Ob ein EIGENES Ziel erreicht ist, entscheidest nur du als Figur, und nur ausdruecklich (plan.event_kind acceptance mit refers_to [goal_…]); "
        "Ziele und Angelegenheiten anderer entscheidest du nicht. "
        'Antwort NUR JSON: {"speech": string, "action": string|null, '
        '"wirkung": {"art": "zaertlich|gewalt|fesseln|befreien|ortswechsel|annaeherung|entfernung|ohne_koerperwirkung", "ziel": string|null}|null, '
        '"synapsen": [{"raum": "<Bedeutungsraum>", "aktivierung": 0..1, "grund": string}], '
        '"emotion": string, "beziehung": {"zu": string, "trust": number, '
        '"closeness": number, "fear": number, "grund": string}|null, '
        '"plan": {"event_kind": "claim|proposal|acceptance|request|disclosure|state_change|revocation|refusal|action|report|question|promise|smalltalk", '
        '"speech_act": "assert|propose|accept|request|disclose|refuse|revoke|report|act|ask|promise|chat", '
        '"durability": "utterance|durable_state|commitment|knowledge_transition|action_event", '
        '"summary": string, "subject": string, "predicate": string, "object": string, '
        '"temporal": {"text": string|null, "wochentag": string|null, "relativ": "heute|morgen|übermorgen|gestern|vorgestern|in_tagen"|null, '
        '"in_tagen": int|null, "datum": "JJJJ-MM-TT"|null, "uhrzeit": "HH:MM"|null}, '
        '"refers_to": string|null, "cue_terms": []}, '
        '"aussagen": [{"segment": string, "ereignis": ["E1"], "art": "bestreitet_geschehen|bestaetigt|bewertet|verweigert_antwort"}], '
        '"grenze": {"gilt_fuer": "diese_tat|jede_beruehrung", "wer": string, "beleg": string, '
        '"zeit": {"relativ": "heute|morgen|übermorgen"|null, "wochentag": string|null, "datum": string|null}|null}|null}. '
        # V62 (AMASTER §37): same structured reading as the input planner; the
        # kernel computes the window from the bound session date.
        "temporal: Zeit wörtlich in text; wochentag/relativ/datum/uhrzeit nur, wenn genannt (in_tagen nur bei 'in n Tagen'); sonst null. "
        # V60 (AMASTER §35/§36.1/§50): the plan uses the same closed inventory
        # as the input planner; a free label ("Frage") cannot be validated.
        "plan beschreibt deine eigene Rede: event_kind und speech_act NUR aus den genannten Werten "
        "(Forderung/Bitte/Aufforderung = request; Frage = question; Zustimmung zu einer offenen Angelegenheit = acceptance; Ablehnung = refusal). "
        "refers_to = die ID [prop_…] einer OFFENEN ANGELEGENHEIT aus dem Zustand, wenn deine Rede sie wiederholt, beantwortet, annimmt oder ablehnt; "
        "oder die ID [goal_…] eines deiner aktuell bedeutsamen Ziele, wenn du mit acceptance erklaerst, dass es fuer dich erreicht ist; sonst null. "
        + GRENZE_RULE + AUSSAGEN_RULE +
        "speech ist die eigene direkte Rede (keine Beschreibung eigener Handlungen); action ist die eigene sichtbare Handlung in diesem Moment, als kurze Beschreibung. "
        # V59C (AMASTER §28 Schritt 29, §24.6): the semantic class of the
        # action is a proposal; the kernel validates it before any writer.
        "wirkung beschreibt nur die koerperliche Wirkung deiner action (null ohne action): zaertlich = Beruehrung ohne Verletzung (liebevoll, sexuell oder aufdringlich; ob erwuenscht, entscheidet die Einwilligung der beruehrten Person, nicht diese Klasse); "
        "gewalt = verletzender koerperlicher Angriff; fesseln = jemanden binden, knebeln oder gewaltsam bewegungsunfaehig machen; "
        "befreien = Fesseln loesen; ortswechsel = den Ort verlassen oder an einen anderen Ort gehen; "
        "annaeherung = sich jemandem naehern, naeher ruecken, sich zu jemandem lehnen; entfernung = von jemandem abruecken, Abstand nehmen; "
        "ohne_koerperwirkung = Blick, Geste, Mimik, Haltung; ziel = Name der getroffenen Figur. "
        # V60 (AMASTER §44 "Delta oder gesetzter Wert", §45, §68 Nr. 85): the
        # relationship proposal is the NEW target value; unchanged = same value.
        "beziehung = deine Werte zu dieser Person NACH diesem Moment (0..1, Zielwerte, keine Differenzen); "
        "unveraendert bleibt ein Wert, wenn nichts Neues passiert ist; grund nennt das Ereignis. "
        "synapsen.raum ist ein Bedeutungsraum aus der Liste unten, kein Ort. "
        "Synapsen, Beziehung, Wirkung und Plan sind Vorschlaege, keine kanonischen Schreibbefehle. "
        # V62 (AMASTER §15): the spaces of THIS figure's compass (editable
        # lens); the shared inventory only for a figure without a compass.
        "Verfuegbare Bedeutungsraeume: " + ", ".join(_figure_spaces(spiegel)) + "."
        + FORMULIERUNG_PRUEFUNG_RULES
    )
    utterance = str(spiegel.get("userUtterance") or spiegel.get("query") or "")
    brief = render_persona_brief(spiegel, utterance, str(spiegel.get("utteredBy") or ""), "")
    # Exact projections from the same scoped SQL reader. No unsent 'compact'
    # dictionary and no character-count tail slicing of mandatory state.
    # V65S (AMASTER §49 "kompakter Lesespiegel ... darf nicht als eigener Speicher wirken", §39 WitnessKnowledge "kein
    # Ersatz", §63 Z. 3234 JSON keine zweite Wahrheit; Pruefung v3.1 §3/§6 Schritt 3): not sent any more - the full
    # witness access list (73 rows of IDs at your T32, 30,432 characters; recall already applied it), the complete frame
    # objects (the foreground ones are in the brief, framesText) and the scene state (in the brief, scene_state.prompt_lines).
    state_keys = ("sessionId", "worldId", "sourceTurnId", "speakerId", "runtime", "body",
                  "facts", "currentState", "godFacts", "goalState",
                  "goalEvidence", "immediateStimulus", "constraintContext",
                  "characterForeground", "backgroundReservoir", "deferredTopics", "propositions", "conflictedClaims",
                  "relationsHere", "userUtterance", "utteredBy", "hauptsache", "worldRules")
    state = {k: spiegel[k] for k in state_keys if k in spiegel}
    # V60 (AMASTER §49 "nicht vollständig kopieren", §41.3): the fact list keeps
    # IDs, kinds, provenance and plan class; the plan's text copies of the same
    # sentence (summary/canonical_value) are not sent a second and third time.
    # V65S: nor the second spelling of the matter ID (proposition_id = propositionId) and the ranking value.
    if isinstance(state.get("facts"), list):
        state["facts"] = [
            ({**{k: v for k, v in f.items() if k not in ("proposition_id", "salience")},
              **({"plan": {k: (f.get("plan") or {}).get(k) for k in ("event_kind", "speech_act", "refers_to", "source")}}
                 if isinstance(f.get("plan"), dict) else {})}
             if isinstance(f, dict) else f)
            for f in state["facts"]]
    # An open matter is carried by its ID and meaning; its wording is the
    # speech Fact already listed above (one copy, §41.3/§49).
    _by_text = {}
    cs = state.get("currentState") if isinstance(state.get("currentState"), dict) else None
    if cs is not None:
        cs = dict(cs)
        for key in ("openPropositions", "closedPropositions"):
            rows = []
            for p in cs.get(key) or []:
                if isinstance(p, dict) and p.get("matter"):
                    _by_text[str(p.get("text") or "")] = str(p.get("matter"))
                    p = {k: v for k, v in p.items() if k != "evidence"}
                    p["text"] = str(p.get("matter"))
                rows.append(p)
            cs[key] = rows
        state["currentState"] = cs
    if isinstance(state.get("propositions"), list):
        state["propositions"] = [({**p, "text": _by_text.get(str(p.get("text") or ""), p.get("text"))} if isinstance(p, dict) else p)
                                 for p in state["propositions"]]
    if isinstance(state.get("hauptsache"), list):
        state["hauptsache"] = [_by_text.get(str(x), x) for x in state["hauptsache"]]
    _TL.last_brief = brief
    brief += "\n\nKANONISCHER LESEZUSTAND (IDs und Quellen):\n" + json.dumps(state, ensure_ascii=False)
    _TL.last_prompt_chars = len(brief)
    _TL.last_prompt_full = brief
    use_model, url, _ = _route_provider(api_key, model, endpoint, provider)
    # Stand 11: die Antwort traegt zusaetzlich die Fachlesungen (frueher eigene Aufrufe) - Platz dafuer, sonst waere sie abgeschnitten
    payload = {"model": use_model, **_model_params(use_model, url, temperature, max(int(max_tokens), 1600)),
               "response_format": _formulation_format(use_model, url),
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": brief}]}
    started = time.monotonic()
    if audit:
        audit("request", {"endpoint": url, "payload": payload})
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
          headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            response = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError) as exc:
        # Never include headers/key or return an invented character response.
        _set_err(type(exc).__name__ + (f" HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else ""))
        if audit:
            audit("response", {"error": _last_llm_error(), "elapsedMs": round((time.monotonic()-started)*1000)})
        return None
    if audit:
        audit("response", {"response": response, "elapsedMs": round((time.monotonic()-started)*1000)})
    raw = (((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    parsed = _parse_llm_json(raw)
    if parsed is None:
        _set_err("INVALID_FORMULATION_JSON")
        return None
    # Missing/invalid semantics remain source-only rather than a keyword guess.
    if not isinstance(getattr(_TL, "proposals", {}).get("plan"), dict):
        from matrix_api.conjunctive import literal_plan
        _TL.proposals["plan"] = literal_plan(parsed[0], actor_id=str(spiegel.get("speakerId") or ""), recipient_id=None)
    if _TL.proposals.get("aussagen"):
        # V65T: the [E#] labels of THIS brief travel with the components; the kernel resolves and checks them.
        _TL.proposals["ereignisse"] = event_labels(spiegel)
    return parsed


def _try_openai(
    api_key: str,
    spiegel: dict[str, Any],
    model: str,
    temperature: float,
    max_tokens: int,
    endpoint: str | None = None,
) -> tuple[str, str | None] | None:
    return _try_llm(api_key, spiegel, model, temperature, max_tokens, endpoint=endpoint)


def _cfg(conn, actor: str, data: dict[str, Any]) -> dict[str, Any]:
    scope = str(data.get("scope") or "user")
    scope_id = data.get("scope_id") or data.get("scopeId")
    try:
        cfg = get_config(conn, actor, scope=scope, scope_id=str(scope_id) if scope_id else None)
    except Exception:
        cfg = get_config(conn, actor)
    return cfg if isinstance(cfg, dict) else {}


def _env_key() -> str:
    return str(os.environ.get("XAI_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()


def _client_stored_key(data: dict[str, Any], cfg: dict[str, Any]) -> str:
    """Der im Frontend eingegebene und gescopt in SQLite gespeicherte Key (AMASTERv2 §60)."""
    return str(cfg.get("apiKey") or "").strip()


def _key_source(data: dict[str, Any], cfg: dict[str, Any]) -> str:
    """'config' | 'env' | 'none' — nie der Key selbst."""
    if _client_stored_key(data, cfg):
        return "config"
    if _env_key():
        return "env"
    return "none"


def _api_key(data: dict[str, Any], cfg: dict[str, Any]) -> str:
    """V25 (MATRIX10 Nr. 1, AMASTERv2 §60): Der gespeicherte Frontend-Key ist
    der Wahrheitsowner. Der Umgebungsschlüssel bleibt nur als Fallback für
    Betreiber ohne Frontend-Eingabe. Keys aus dem Request-Body werden weiterhin
    ignoriert (Bedienabsicht ist die Config, nicht ein Turn-Payload)."""
    return _client_stored_key(data, cfg) or _env_key()


def _key_kind(api_key: str) -> str:
    key = str(api_key or "").strip()
    if not key:
        return "none"
    if key.startswith("sk-"):
        return "openai"
    if key.startswith("xai-"):
        return "xai"
    return "xai"


def _cfg_provider(data: dict[str, Any], cfg: dict[str, Any]) -> str:
    """Explizit gewählter Provider aus Config (Frontend) — Request-Body nur als Hinweis."""
    for src in (cfg, data):
        p = str((src or {}).get("provider") or "").strip().lower()
        if p in ("openai", "xai", "custom", "synapse", "synapse-local"):
            return "synapse" if p == "synapse-local" else p
    return ""


def _route_provider(
    api_key: str,
    model: str | None,
    endpoint: str | None,
    provider: str | None = None,
) -> tuple[str, str, str]:
    """Pick live URL/model. V25: expliziter Config-Provider hat Vorrang vor der
    Key-Form; custom braucht einen Endpoint; ohne Key immer synapse."""
    kind = _key_kind(api_key)
    if kind == "none":
        return DEFAULT_MODEL, XAI_URL, "synapse"
    wanted = str(provider or "").strip().lower()
    url = str(endpoint or "").strip()
    if wanted == "custom" and url:
        use_model = str(model or "").strip() or OPENAI_DEFAULT_MODEL
        return use_model, url, "custom"
    key = str(api_key or "").strip()
    key_says = "openai" if key.startswith("sk-") else ("xai" if key.startswith("xai-") else "")
    if wanted in ("openai", "xai"):
        # V25.1: Ein OpenAI-Key (sk-…) geht nie an api.x.ai und umgekehrt — die
        # Key-Form ist eindeutig, ein widersprechender gespeicherter Provider
        # (z. B. Altdefault "xai" aus V24) wird korrigiert statt in 401 zu laufen.
        kind = key_says or wanted
    if not url or wanted in ("openai", "xai") and url in (OPENAI_URL, XAI_URL):
        url = OPENAI_URL if kind == "openai" else XAI_URL
    use_openai = kind == "openai" or "openai.com" in url
    use_model = str(model or "").strip()
    if use_openai:
        if not use_model or use_model in ("synapse-local", DEFAULT_MODEL) or use_model.startswith("grok"):
            use_model = OPENAI_DEFAULT_MODEL
        kind = "openai"
    else:
        if not use_model or use_model in ("synapse-local", "gpt-4o"):
            use_model = DEFAULT_MODEL
        kind = "xai"
    return use_model, url, kind


def provider_status(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Honest key status for health/ping. Never labels OpenAI as xAI, never leaks the key."""
    cfg = cfg if isinstance(cfg, dict) else {}
    key = _api_key({}, cfg)
    source = _key_source({}, cfg)
    provider = _cfg_provider({}, cfg)
    endpoint = _resolve_endpoint({}, cfg) if cfg else ""
    model, url, kind = _route_provider(key, cfg.get("model") if cfg else None, endpoint, provider or None)
    if provider == "synapse":
        kind = "synapse"
    return {
        "keyPresent": bool(key),
        "keySource": source,
        "provider": kind if key else "synapse",
        "model": model if key else "",
        "endpoint": url if key else "",
    }


def _network_llm_allowed(data: dict[str, Any]) -> bool:
    """V25 LLM-01 (AMASTERv2 §27.8/§48/§68.16, Vertrag §12.6): AutoChat nutzt
    denselben LLM-Formulierungsweg wie der normale Turn. Der frühere
    inputKind=autochat-Ausschluss war eine Ersatzimplementierung."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if str(os.environ.get("MATRIX_DISABLE_LLM") or "").lower() in ("1", "true", "yes"):
        return False
    provider = str(data.get("provider") or "").lower()
    if provider in ("synapse", "synapse-local"):
        return False
    return True


def _resolve_endpoint(data: dict[str, Any], cfg: dict[str, Any]) -> str:
    """B.16: Endpoint-Allowlist. User-Provider-Endpoint wird gegen Whitelist geprüft;
    bei Config-Key (V25) ist jeder http(s)-Endpoint des Nutzers zulässig."""
    key_source = _key_source(data, cfg)
    pc = cfg.get("providerConfig") if isinstance(cfg.get("providerConfig"), dict) else {}
    data_pc = data.get("providerConfig") if isinstance(data.get("providerConfig"), dict) else {}
    candidates = [
        str(cfg.get("endpoint") or "").strip(),
        str(pc.get("endpoint") or "").strip(),
        str(data.get("endpoint") or "").strip(),
        str(data_pc.get("endpoint") or "").strip(),
    ]
    for c in candidates:
        if c and _is_endpoint_allowed(c, key_source=key_source):
            return c
    # Kein Kandidat erlaubt → leer, _route_provider fällt auf Provider/Key-Form zurück.
    return ""


def _routing(data: dict[str, Any], cfg: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    """Eine Auflösung für alle LLM-Funktionen (Formulate, Generatoren, Profile, Ping)."""
    api_key = _api_key(data, cfg)
    endpoint = _resolve_endpoint(data, cfg)
    provider = _cfg_provider(data, cfg)
    use_model = str(model or data.get("model") or cfg.get("model") or "").strip()
    routed_model, url, kind = _route_provider(api_key, use_model or None, endpoint, provider or None)
    if provider == "synapse":
        kind = "synapse"
    allowed = bool(api_key) and kind != "synapse" and _network_llm_allowed(data)
    return {"apiKey": api_key, "keySource": _key_source(data, cfg), "provider": kind, "model": routed_model,
            "endpoint": url, "allowed": allowed, "providerChosen": provider or "", "providerResolved": kind}


def _model_params(model: str, url: str, temperature: float, max_tokens: int) -> dict[str, Any]:
    """OpenAI-Modellfamilien ab gpt-5 / o-Serie verlangen max_completion_tokens und
    akzeptieren keine freie temperature (HTTP 400). Andere Provider/Modelle: klassisch."""
    m = str(model or "").lower()
    newer = ("openai.com" in str(url or "").lower()) and (m.startswith(("gpt-5", "o1", "o3", "o4")))
    if newer:
        return {"max_completion_tokens": int(max_tokens)}
    return {"temperature": float(temperature), "max_tokens": int(max_tokens)}


# ---------------------------------------------------------------------------
# Stand 11 (SPS V62.7 wiederhergestellt; AMASTER §28: Eingabe lesen -> Erleben -> EIN Formulierungsaufruf, der Kernel validiert):
# Die Fachlesungen, die seit V65-V92 je einen EIGENEN Modellaufruf machten, kommen aus der ERSTEN Antwort (Planer bzw.
# Formulierung) als "lesungen" [{lesung, zu, antwort}]. Jede Lesefunktion behaelt ihre Aufrufstelle, ihre Nachverarbeitung und
# ihren Kernel-Validator - nur der Netzaufruf entfaellt: _llm_json liefert die zur Stelle gehoerende Antwort aus der ersten
# Antwort. Fehlt sie, gibt es KEINEN Ersatzaufruf: die Lesung ist None und der Kernel behandelt die Sache als unbestaetigt.
_VORAB_LOCK = _threading.Lock()
# Je Anfrage ein eigener Speicher (contextvars): gleichzeitige Anfragen sehen nie die Lesungen der anderen. Lesungen, die in
# Hilfsthreads derselben Anfrage laufen, bekommen den Kontext ausdruecklich mit (app.lesungen_gleichzeitig: copy_context).
import contextvars as _contextvars
_VORAB_CTX: "_contextvars.ContextVar[dict | None]" = _contextvars.ContextVar("matrix_vorab_lesungen", default=None)


def _vorab_speicher() -> dict:
    st = _VORAB_CTX.get()
    if st is None:
        st = {"lesungen": {}, "abrufe": []}
        _VORAB_CTX.set(st)
    return st


def vorab_abrufe() -> list[dict]:
    """Nachweis dieser Anfrage: welche Fachlesung an welcher Stelle angefragt wurde und ob die erste Antwort sie enthielt."""
    return list(_vorab_speicher()["abrufe"])


# lesung -> (Regeltext-Konstante (Name), Payload-Feld, das die Stelle bezeichnet)
ERSTE_ANTWORT_LESUNGEN: dict[str, tuple[str, str]] = {
    "vollzug": ("VOLLZUG_CHECK_RULES", "handlung"),
    "komponentenart": ("KOMPONENTENART_CHECK_RULES", "segment"),
    "sprecher": ("SPRECHER_CHECK_RULES", "worte"),
    "wirkung": ("EFFECT_CHECK_RULES", "handlung"),
    "bewegung": ("MOVE_CHECK_RULES", "handlung"),
    "bewegungsversuch": ("MOVE_ATTEMPT_RULES", "handlung"),
    "beruehrung": ("TOUCH_CONFIRM_RULES", "handlung"),
    "erlaubnisbezug": ("ERLAUBNISBEZUG_CHECK_RULES", "handlung"),
    "bittebezug": ("BITTEBEZUG_CHECK_RULES", "handlung"),
    "grenzbezug": ("GRENZBEZUG_CHECK_RULES", "handlung"),
    "grenzumfang": ("GRENZE_CHECK_RULES", "beleg"),
    "aussage_tat": ("AUSSAGE_TAT_RULES", "segment"),
    "aussage": ("AUSSAGE_CHECK_RULES", "segment"),
    "koerper": ("KOERPER_CHECK_RULES", "handlung"),
    "koerper_bestaetigung": ("KOERPER_BESTAETIGUNG_RULES", "stelle"),
    "sprache": ("LANGUAGE_RULES", "aeusserung"),
    "offenbarung": ("GOAL_DISCLOSURE_RULES", "rede"),
    "namen": ("NAME_BOUNDARY_RULES", "wortfolge"),
    "absichtsart": ("INTENT_KIND_RULES", "absicht"),
}


def _norm_stelle(t: Any) -> str:
    return " ".join(str(t or "").replace("*", " ").lower().split()).strip(" .,;:!?\"'")


def vorab_registrieren(lesungen: Any, *, quelle: str = "") -> int:
    """Lesungen aus der ersten Modellantwort ablegen. Jede Lesung gehoert zu einer woertlichen Stelle ('zu');
    'antwort' ist ein Objekt (Planer, json_object) oder ein JSON-Text (Formulierung, striktes Schema)."""
    n = 0
    for l in lesungen if isinstance(lesungen, list) else []:
        if not isinstance(l, dict):
            continue
        name = str(l.get("lesung") or "").strip().lower()
        if name not in ERSTE_ANTWORT_LESUNGEN:
            continue
        antwort = l.get("antwort")
        if antwort is None and isinstance(l.get("antwort_json"), str):
            try:
                antwort = json.loads(l["antwort_json"])
            except (ValueError, TypeError):
                antwort = None
        if not isinstance(antwort, dict):
            continue
        zu = _norm_stelle(l.get("zu"))
        if not zu:
            continue
        with _VORAB_LOCK:
            _vorab_speicher()["lesungen"].setdefault(name, []).append((zu, dict(antwort)))
        n += 1
    return n


def vorab_leeren() -> None:
    """Am Anfang jeder Anfrage: ein neuer, leerer Speicher fuer genau diese Anfrage."""
    _VORAB_CTX.set({"lesungen": {}, "abrufe": []})


def _vorab_lesung_fuer(system: str) -> str | None:
    sysm = str(system or "")
    for name, (const, _feld) in ERSTE_ANTWORT_LESUNGEN.items():   # exakt dieselbe Regel (MOVE_ATTEMPT beginnt wie MOVE_CHECK)
        if sysm == globals().get(const):
            return name
    for name, (const, _feld) in ERSTE_ANTWORT_LESUNGEN.items():   # Regel mit angehaengtem Kontext
        v = globals().get(const)
        if isinstance(v, str) and v and sysm.startswith(v):
            return name
    return None


def _vorab_suchen(name: str, user_payload: Any) -> dict | None:
    feld = ERSTE_ANTWORT_LESUNGEN[name][1]
    p = user_payload if isinstance(user_payload, dict) else {}
    stelle = _norm_stelle(p.get(feld))
    if not stelle:
        return None
    with _VORAB_LOCK:
        kandidaten = list(_vorab_speicher()["lesungen"].get(name) or [])
    gleich = [a for z, a in kandidaten if z == stelle]
    if gleich:
        return dict(gleich[-1])
    # dieselbe Stelle, nur anders abgegrenzt (z. B. Beleg innerhalb des Segments): die engste umfassende Stelle
    teil = sorted(((len(z), a) for z, a in kandidaten if stelle in z or z in stelle), key=lambda x: x[0])
    return dict(teil[0][1]) if teil else None


def _llm_json(routing: dict[str, Any], system: str, user_payload: Any, *, temperature: float = 0.2,
              max_tokens: int = 1200, timeout: int = 40, max_input_chars: int = 16000, audit=None, attempts: int = 2,
              response_format: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Ein JSON-Aufruf über den gerouteten Provider. Gibt None + _LAST_LLM_ERROR bei Fehler.
    V65T: `response_format` = a strict schema where the provider enforces it (see _strict_format); default json_object."""
    _set_err(None)
    _vl = _vorab_lesung_fuer(system)
    if _vl is not None:
        # Stand 11: Fachlesung aus der ersten Antwort - kein eigener Modellaufruf (s. ERSTE_ANTWORT_LESUNGEN)
        _treffer = _vorab_suchen(_vl, user_payload)
        with _VORAB_LOCK:
            _ab = _vorab_speicher()["abrufe"]
            _ab.append({"lesung": _vl, "payload": user_payload, "aus_erster_antwort": _treffer is not None})
            del _ab[:-200]
        if _treffer is None:
            _set_err("nicht_in_erster_antwort:" + _vl)
            return None
        return _treffer
    if not routing.get("allowed"):
        _set_err("LLM_REQUIRED")
        return None
    payload = {
        "model": routing["model"],
        **_model_params(routing["model"], routing["endpoint"], temperature, max_tokens),
        "response_format": response_format or {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": (user_payload if isinstance(user_payload, str) else json.dumps(user_payload, ensure_ascii=False))[:max_input_chars]},
        ],
    }
    req_bytes = json.dumps(payload).encode("utf-8")
    body = None
    # V49: ein Wiederholungsversuch mit Backoff bei Timeout/Netzfehler/5xx/429 (Nutzeridee Extraktor Nr. 9)
    for attempt in range(attempts):
        if audit:
            audit("request", {"endpoint": routing["endpoint"], "payload": payload, "attempt": attempt + 1})
        req = urllib.request.Request(
            routing["endpoint"],
            data=req_bytes,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {routing['apiKey']}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if audit:
                audit("response", {"response": body, "attempt": attempt + 1})
            break
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", "replace")[:180]
            except Exception:
                err_body = ""
            _set_err(f"HTTP {exc.code} {err_body}".strip())
            if audit:
                audit("response", {"error": _last_llm_error(), "attempt": attempt + 1})
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                time.sleep(2.0)
                continue
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError) as exc:
            _set_err(f"{type(exc).__name__}: {str(exc)[:120]}")
            if audit:
                audit("response", {"error": _last_llm_error(), "attempt": attempt + 1})
            if attempt + 1 < attempts and isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
                time.sleep(2.0)
                continue
            return None
    if body is None:
        return None
    raw = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    finish = str(((body.get("choices") or [{}])[0]).get("finish_reason") or "")
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        _set_err("no_json")
        return None
    repaired = False
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        parsed = _repair_json(raw[start : end + 1])
        repaired = True
        if parsed is None:
            _set_err("bad_json")
            return None
    if not isinstance(parsed, dict):
        _set_err("bad_json")
        return None
    if repaired or finish == "length":
        # V65Z (SPS-Audit V65Y A04; live E2E 31.10.: of "Ich stehe auf. … Ich setze mich." the reading was cut at the token
        # limit and _repair_json dropped the incomplete 7th component without a trace; AMASTER §24.7 keine stille Kuerzung):
        # a reading that was cut or repaired is marked, so its consumers treat it as incomplete.
        parsed["_abgeschnitten"] = True
    return parsed


def _repair_json(fragment: str) -> dict[str, Any] | None:
    """V49: abgeschnittenes/unsauberes JSON retten — hängende Kommas entfernen, Klammern schließen,
    notfalls den letzten unvollständigen Eintrag abschneiden."""
    txt = str(fragment or "").strip()
    txt = re.sub(r",\s*([}\]])", r"\1", txt)
    for _ in range(4):
        cand = txt + ('"' if txt.count('"') % 2 == 1 else "")
        cand = cand + ("]" * max(0, cand.count("[") - cand.count("]"))) + ("}" * max(0, cand.count("{") - cand.count("}")))
        try:
            obj = json.loads(cand)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            cut = max(txt.rfind(","), txt.rfind("{"), txt.rfind("["))
            if cut <= 0:
                return None
            txt = txt[:cut]
    return None


def canonical_formulation_context(conn, actor: str, data: dict) -> dict:
    """Re-read an authorized session. Browser Spiegel values are display only."""
    from matrix_api import kernel
    from matrix_api.repos import get_session, get_character, list_characters, get_world, WriterError
    hint = data.get("spiegel") if isinstance(data.get("spiegel"), dict) else {}
    sid = str(data.get("sessionId") or hint.get("sessionId") or "")
    if not sid:
        raise WriterError("sessionId required for character formulation", 400, "SESSION_REQUIRED")
    session = get_session(conn, actor, sid)
    source_id = str(data.get("sourceTurnId") or hint.get("sourceTurnId") or "")
    speaker_id = str(data.get("speakerId") or hint.get("speakerId") or "")
    truth = next((r for r in session.get("turnTruths") or [] if r.get("id") == source_id), None)
    if truth is None:
        if str(data.get("inputKind") or "") != "autochat" or session.get("pendingInputTurnId"):
            raise WriterError("committed input TurnTruth not found", 409, "FORMULATION_SOURCE_MISSING")
        # AutoChat has no new user input; its only stimulus is committed history.
        if int(data.get("turnIndex", -1)) != int(session.get("turnIndex") or 0):
            raise WriterError("autochat state has advanced", 409, "STALE_SESSION")
        truth = kernel.bind_from_session(session, role="teilnehmer", authority="character",
                speaker_id=speaker_id, target_id=None, input_kind="autochat", text="")
        if source_id:
            truth["id"] = source_id
        directive = next((d for d in reversed(session.get("directorActions") or [])
                          if isinstance(d, dict) and d.get("actorId") == speaker_id
                          and d.get("turn") == session.get("turnIndex")), None)
        if directive and directive.get("text"):
            truth["directive"] = str(directive["text"])
    else:
        if session.get("pendingInputTurnId") != source_id:
            raise WriterError("input already answered or stale", 409, "STALE_FORMULATION")
        if speaker_id and speaker_id != truth.get("speaker_id"):
            raise WriterError("speaker differs from committed input", 409, "SPEAKER_MISMATCH")
        speaker_id = str(truth.get("speaker_id") or "")
    if not speaker_id or speaker_id == session.get("avatarId") or speaker_id not in (session.get("scene") or {}).get("presentIds", []):
        raise WriterError("no present figure speaker", 409, "SPEAKER_NOT_PRESENT")
    speaker = get_character(conn, speaker_id, actor)
    if speaker.get("worldId") != session.get("worldId"):
        raise WriterError("speaker belongs to another world", 403, "WORLD_MISMATCH")
    world = get_world(conn, str(session["worldId"]), actor)
    cast = [c for c in list_characters(conn, actor).get("characters") or []
            if c.get("worldId") == session.get("worldId")]
    result = kernel.prepare_turn(session, truth=truth, speaker=speaker, present=cast, world=world)
    return result["spiegel"]


def provider_audit(conn, actor: str, context: dict, purpose: str):
    """Full request/response through existing append-only scoped SQLite logs.

    Only request bodies, not Authorization headers, are stored. Reader already
    exists at /api/logs and /api/logs/id; no second JSON log/shadow store.
    """
    import hashlib
    from matrix_api.ids import uid
    from matrix_api.repos import create_log
    trace_id = uid("llm")
    request_hash = ""
    def write(phase: str, detail: dict):
        nonlocal request_hash
        if phase == "request":
            request_hash = hashlib.sha256(json.dumps(detail.get("payload"), ensure_ascii=False,
                sort_keys=True).encode("utf-8")).hexdigest()
        row = {"id": uid("log"), "level": "error" if detail.get("error") else "info",
               "code": "MODEL_REQUEST" if phase == "request" else "MODEL_RESPONSE",
               "message": f"{purpose} / {phase}", "traceId": trace_id, "purpose": purpose,
               "sessionId": context.get("sessionId"), "worldId": context.get("worldId"),
               "sourceTurnId": context.get("sourceTurnId"), "speakerId": context.get("speakerId"),
               "turn": (context.get("currentState") or {}).get("turn"),
               "requestSha256": request_hash, **detail}
        create_log(conn, row, actor)
    return write


def _plan_valid(plan: Any, sp: dict) -> bool | None:
    if not isinstance(plan, dict):
        return None
    try:
        from matrix_api.conjunctive import normalize_plan
        return normalize_plan(plan, actor_id=str(sp.get("speakerId") or ""), recipient_id=None,
                              text=str(plan.get("summary") or "")) is not None
    except Exception:
        return None


def _log_formulation(data: dict, spiegel: dict, speech: str, action: Any, source: str, llm_error: Any) -> None:
    """V60 (AMASTER §54 Punkt 15, §68 Nr. 70): the brief that was really sent,
    by section, and the raw proposals of the model — in MATRIX10_LIVE.log.

    The repetition count is diagnosis only: how often each own earlier
    utterance of the speaker occurs in the sent prompt. It changes nothing.
    """
    try:
        from matrix_api import live_log as _ll
        sp = spiegel if isinstance(spiegel, dict) else {}
        brief = str(getattr(_TL, "last_brief", "") or "")
        name = str(sp.get("speakerName") or (sp.get("profile") or {}).get("name") or "")
        own = []
        for d in sp.get("dialogue") or []:
            if isinstance(d, dict) and str(d.get("name") or "") == name and str(d.get("speech") or "").strip():
                own.append(str(d.get("speech")).strip())
        for m in sp.get("memories") or []:
            if isinstance(m, dict) and m.get("kind") == "gesagt" and str(m.get("text") or "").strip():
                own.append(str(m.get("text")).strip())
        # count in the text that was really sent (brief + JSON read state)
        full = str(getattr(_TL, "last_prompt_full", "") or brief)
        seen, repeats = set(), []
        for txt in own:
            key = txt[:48]
            if key in seen or len(key) < 12:
                continue
            seen.add(key)
            repeats.append(f"{full.count(key)}× {key}")
        trace = str(data.get("trace_id") or data.get("traceId") or ("fm_" + str(sp.get("sourceTurnId") or "")))
        _ll.live_log("PROMPT", trace_id=trace, source_turn_id=sp.get("sourceTurnId"), speaker=name,
                     prompt_chars=getattr(_TL, "last_prompt_chars", None),
                     own_utterance_repeats=repeats[:10], **{"sections": _ll.prompt_sections(brief)})
        props = dict(getattr(_TL, "proposals", {}) or {}) if source == "llm" else {}
        _ll.live_log("MODEL_REPLY", trace_id=trace, source_turn_id=sp.get("sourceTurnId"), speaker=name,
                     source=source, error=llm_error, speech=speech, action=action,
                     wirkung=props.get("wirkung"), emotion=props.get("emotion"), beziehung=props.get("beziehung"),
                     plan=props.get("plan"), plan_valid=_plan_valid(props.get("plan"), sp), synapsen=props.get("synapsen"))
    except Exception:  # diagnosis must never break a turn
        pass


def formulate_from_config(conn, actor: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = body or {}
    cfg = _cfg(conn, actor, data)
    text = str(data.get("text") or data.get("cue") or "").strip()
    model = str(data.get("model") or cfg.get("model") or DEFAULT_MODEL)
    try:
        temperature = float(
            data.get("temperature")
            if data.get("temperature") is not None
            else (cfg.get("temperature") if cfg.get("temperature") is not None else 0.7)
        )
    except Exception:
        temperature = 0.7
    try:
        max_tokens = int(data.get("maxTokens") or data.get("max_tokens") or cfg.get("maxTokens") or cfg.get("max_tokens") or 400)
    except Exception:
        max_tokens = 400
    max_tokens = max(40, min(max_tokens, MAX_TOKENS_CAP))
    spiegel = canonical_formulation_context(conn, actor, data)
    audit = provider_audit(conn, actor, spiegel, "formulation")
    speech, action = "", None
    source = "synapse"
    provider = "synapse-local"
    network = False
    routing = _routing(data, cfg, model)
    api_key = routing["apiKey"]
    endpoint_cfg = _resolve_endpoint(data, cfg)
    routed_model, routed_url, routed_provider = routing["model"], routing["endpoint"], routing["provider"]
    endpoint_used = routed_url
    llm_error = None
    if str(data.get("provider") or cfg.get("provider") or "") in ("synapse", "synapse-local"):
        from matrix_api.local_render import render_local_reply
        speech, action = render_local_reply(spiegel, text, seed=len(str(spiegel.get("dialogue") or [])))
    if routing["allowed"] and spiegel:
        llm = _try_llm(api_key, spiegel, model, temperature, max_tokens, endpoint=endpoint_cfg or None, provider=routing["provider"], audit=audit)
        if llm:
            speech, action = llm
            source = "llm"
            provider = routed_provider
            network = True
            model = routed_model
        else:
            llm_error = _last_llm_error()
    # A configured provider failure is an error, not a synthetic roleplay turn.
    if str(data.get("provider") or cfg.get("provider") or "") not in ("synapse", "synapse-local") and source != "llm":
        return {"ok": False, "error": llm_error or "LLM_REQUIRED",
                "message": llm_error or "Sprachdienst nicht verfuegbar; Eingabe bleibt gespeichert.",
                "source": "error", "commitsTruth": False, "network": False}
    result = {"speech": speech, "action": action, "source": source}
    out = {
        "ok": True,
        "commitsTruth": False,
        "provider": provider,
        "network": network,
        "model": model if source == "llm" else model,
        "endpoint": endpoint_used if network else "",
        "temperature": temperature,
        "maxTokens": max_tokens,
        "speech": speech,
        "action": action,
        "source": source,
        "result": result,
        "keyPresent": bool(api_key),
        "keySource": routing["keySource"],
        "providerResolved": routing["providerResolved"],
        "inputKind": str(data.get("inputKind") or data.get("input_kind") or "speech"),
    }
    if source == "llm" and getattr(_TL, "proposals", None):
        out["proposals"] = dict(_TL.proposals)
        if isinstance(out.get("result"), dict):
            out["result"]["proposals"] = dict(_TL.proposals)
    _log_formulation(data, spiegel, speech, action, source, llm_error)
    if llm_error and source != "llm":
        out["llmError"] = llm_error
        out["llmAttempted"] = True
    elif source != "llm" and not routing["allowed"]:
        out["llmError"] = "LLM_REQUIRED" if not api_key else "LLM_DISABLED"
        out["llmAttempted"] = False
    return out


def _draft_from_text(text: str, title: str = "") -> dict[str, Any]:
    analysis = enrich_analysis(analyze_text(text, source_title=title), text, title=title)
    world = analysis.get("world") if isinstance(analysis.get("world"), dict) else {}
    name = (title or text.split("\n")[0] or "Welt").strip()[:80] or "Welt"
    characters = []
    for c in analysis.get("spawnCandidates") or analysis.get("characterCandidates") or []:
        if isinstance(c, dict) and c.get("name"):
            characters.append(
                {
                    "name": str(c.get("name")),
                    "role": str(c.get("role") or ""),
                    "origin": str(c.get("origin") or ""),
                    "biography": str(c.get("biography") or ""),
                    "personality": str(c.get("personality") or ""),
                    "age": str(c.get("age") or ""),
                    "gender": str(c.get("gender") or ""),
                    "occupation": str(c.get("occupation") or c.get("role") or ""),
                    "speechRegister": str(c.get("speechRegister") or ""),
                    "goals": list(c.get("goals") or []),
                    "fears": list(c.get("fears") or []),
                    "knowledge": list(c.get("knowledge") or []),
                    "coreFacts": list(c.get("coreFacts") or c.get("traits") or []),
                    "relations": list(c.get("relations") or []),
                    "typicalPhrases": list(c.get("typicalPhrases") or []),
                    "values": list(c.get("values") or []),
                    "secrets": list(c.get("secrets") or []),
                }
            )
        elif isinstance(c, str) and c.strip():
            characters.append({"name": c.strip(), "role": "", "origin": "", "biography": ""})
    draft = {
        "world": {
            "name": name,
            "short": world.get("short") or " ".join(text.split())[:180],
            "long": text[:4000],
            "genre": world.get("genre") or "",
            "sourceName": title or name,
            "places": world.get("places") or [],
            "factions": world.get("factions") or [],
            "rules": world.get("rules") or [],
            "conflicts": world.get("conflicts") or [],
            "history": world.get("history") or [],
            "timeline": world.get("timeline") or [],
            "items": world.get("items") or [],
            "culture": world.get("culture") or [],
            "language": world.get("language") or [],
            "worldKnowledge": world.get("worldKnowledge") or [],
            "secretKnowledge": world.get("secretKnowledge") or [],
            "knowledgeBounds": world.get("knowledgeBounds") or [],
            "startScenes": world.get("startScenes") or [],
            "storyGoals": world.get("storyGoals") or [],
            "fateBeats": world.get("fateBeats") or [],
            "subplaces": world.get("subplaces") or [],
            "figureRelations": world.get("figureRelations") or [],
            "placeRelations": world.get("placeRelations") or [],
        },
        "characters": characters,
        "spawnCandidates": analysis.get("spawnCandidates") or [],
    }
    return {"ok": True, "commitsTruth": False, "llm": False, "network": False, "source": "local-analyze", "draft": draft}


_PROFILE_FIELDS_ALL = (
    "age", "gender", "occupation", "origin", "personality", "speechRegister", "dialect", "humor",
    "conflictStyle", "appearance", "typicalPlace", "worldNotes", "typicalPhrases", "favoriteWords",
    "taboos", "values", "goals", "fears", "secrets", "likes", "dislikes", "reactionRules",
    "bindingPatterns", "knowledge", "coreFacts", "lastingAbilities", "relations",
)


def _local_label(out: dict[str, Any], routing: dict[str, Any], error: str | None) -> dict[str, Any]:
    """V25 (Vertrag §7/§8): lokale Heuristik wird nie als KI-Ergebnis ausgegeben."""
    out["ok"] = False
    out["llm"] = False
    out["network"] = False
    out["source"] = "local-fallback"
    out["provider"] = routing.get("provider") if routing.get("apiKey") else "synapse"
    out["model"] = routing.get("model") if routing.get("apiKey") else ""
    out["keySource"] = routing.get("keySource")
    out["error"] = "LLM_REQUIRED" if not routing.get("allowed") else "LLM_FAILED"
    out["llmError"] = error or ("kein Provider/API-Key konfiguriert" if not routing.get("apiKey") else "LLM_DISABLED")
    out["message"] = (
        "Kein LLM erreichbar: Ergebnis ist ein lokaler Entwurf (Heuristik), keine KI-Erzeugung. "
        "Provider und API-Key unter Konfiguration eintragen."
        if out["error"] == "LLM_REQUIRED"
        else f"LLM-Aufruf fehlgeschlagen ({out['llmError']}). Ergebnis ist ein lokaler Entwurf, keine KI-Erzeugung."
    )
    return out


def _llm_label(out: dict[str, Any], routing: dict[str, Any]) -> dict[str, Any]:
    out["ok"] = True
    out["llm"] = True
    out["network"] = True
    out["source"] = "llm"
    out["provider"] = routing["provider"]
    out["model"] = routing["model"]
    out["endpoint"] = routing["endpoint"]
    out["keySource"] = routing["keySource"]
    out.pop("blocked", None)
    return out


def generate_world_from_config(conn, actor: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """V25 LLM-02: "Welt mit KI erzeugen" ruft den konfigurierten Provider auf.
    Ohne Provider: lokaler Entwurf, ehrlich als solcher markiert (ok=false)."""
    data = body or {}
    prompt = str(data.get("prompt") or data.get("text") or data.get("source") or "").strip()
    title = str(data.get("title") or "")
    existing = data.get("existing")
    if not prompt and isinstance(existing, str):
        prompt = existing[:4000]
    if not prompt:
        return {"ok": False, "commitsTruth": False, "error": "Kein Prompt.", "draft": None}
    out = _draft_from_text(prompt, title)
    if isinstance(existing, str) and existing.strip().startswith("{") and out.get("draft"):
        try:
            prev = json.loads(existing)
            prev_name = (prev.get("name") or (prev.get("world") or {}).get("name") or "").strip()
            if prev_name and isinstance(out["draft"], dict) and isinstance(out["draft"].get("world"), dict):
                out["draft"]["world"]["name"] = prev_name
        except json.JSONDecodeError:
            pass
    cfg = _cfg(conn, actor, data)
    routing = _routing(data, cfg)
    local_draft = out.get("draft")
    if routing["allowed"]:
        system = (
            "Du erzeugst aus Ausgangsmaterial einen strukturierten Weltentwurf für ein zustandsbasiertes "
            "Figuren-Universum (AMASTERv2 §9/§11). Antwort NUR JSON: "
            '{"world": {"name", "short", "long", "genre", "tone", "epoch", "places": [{"name","description","rules":[]}], '
            '"subplaces": [], "rules": [], "physicalRules": [], "socialRules": [], "culture": [], "language": [], '
            '"factions": [], "conflicts": [], "history": [], "timeline": [], "items": [], "beings": [], '
            '"worldKnowledge": [], "secretKnowledge": [], "knowledgeBounds": [], "startScenes": [{"placeName","time","presentNames":[],"opening"}], '
            '"storyGoals": [], "fateBeats": [{"beat","mustNot"}]}, '
            '"characters": [{"name","role","origin","biography","personality","goals":[],"fears":[],"knowledge":[],"coreFacts":[],'
            '"provenance": {"feld": "belegt|abgeleitet|unsicher"}}], '
            '"provenance": {"feld": "belegt|abgeleitet|unsicher"}}. '
            "Was im Material steht, hat Vorrang und ist 'belegt'. Fehlendes plausibel ergänzen und als 'abgeleitet' "
            "kennzeichnen. Keine Figuren aus Werbung, Autorenbiografie oder Fremdbüchern. Deutsch, knapp."
        )
        parsed = _llm_json(routing, system, {"title": title, "material": prompt[:14000], "localDraft": local_draft}, temperature=0.3, max_tokens=2600, timeout=60)
        if parsed and isinstance(parsed.get("world"), dict) and parsed["world"].get("name"):
            merged = dict(out)
            draft = dict(local_draft) if isinstance(local_draft, dict) else {}
            world = dict(draft.get("world") or {})
            world.update({k: v for k, v in parsed["world"].items() if v not in (None, "", [], {})})
            draft["world"] = world
            if isinstance(parsed.get("characters"), list) and parsed["characters"]:
                draft["characters"] = [c for c in parsed["characters"] if isinstance(c, dict) and c.get("name")]
            draft["provenance"] = parsed.get("provenance") if isinstance(parsed.get("provenance"), dict) else {}
            # V25.1 CHAR-01: vollständige Stammprofile (alle Frontendfelder) für die
            # entworfenen Figuren, mit Provenienz je Feld — zweiter Provider-Aufruf.
            chars = [c for c in (draft.get("characters") or []) if isinstance(c, dict) and c.get("name")]
            if chars:
                pack = {"ok": True, "characterCandidates": chars, "spawnCandidates": list(chars), "roster": [str(c.get("name")) for c in chars]}
                prof = _try_complete_profiles(routing, pack, prompt, title)
                if prof:
                    filled = merge_profiles(pack, prof)
                    draft["characters"] = [local_complete_character(c) if isinstance(c, dict) else c for c in filled.get("characterCandidates") or chars]
                    draft["profileSource"] = "llm"
                else:
                    draft["characters"] = [local_complete_character(c) for c in chars]
                    draft["profileSource"] = "local-fallback"
                    draft["profileError"] = _LAST_LLM_ERROR
            merged["draft"] = draft
            merged["localDraft"] = local_draft
            return _llm_label(merged, routing)
        out["localDraft"] = local_draft
        return _local_label(out, routing, _LAST_LLM_ERROR)
    out["localDraft"] = local_draft
    return _local_label(out, routing, None)


def generate_characters_from_config(conn, actor: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = body or {}
    summary = str(data.get("worldSummary") or data.get("prompt") or data.get("text") or "")
    existing_names = data.get("existingNames") or data.get("existing") or []
    if isinstance(existing_names, str):
        existing_names = [n.strip() for n in existing_names.split(",") if n.strip()]
    have = {str(n).strip().lower() for n in existing_names if str(n).strip()}
    analysis = analyze_text(summary)
    chars: list[dict[str, Any]] = []
    for c in analysis.get("spawnCandidates") or analysis.get("characterCandidates") or []:
        name = str(c.get("name") if isinstance(c, dict) else c).strip()
        if not name or name.lower() in have:
            continue
        have.add(name.lower())
        chars.append(
            {
                "name": name,
                "role": str((c.get("role") if isinstance(c, dict) else "") or ""),
                "origin": str((c.get("origin") if isinstance(c, dict) else "") or ""),
                "biography": str((c.get("biography") if isinstance(c, dict) else "") or ""),
                "goals": list((c.get("goals") if isinstance(c, dict) else None) or []),
                "fears": list((c.get("fears") if isinstance(c, dict) else None) or []),
                "knowledge": list((c.get("knowledge") if isinstance(c, dict) else None) or []),
                "coreFacts": list((c.get("coreFacts") if isinstance(c, dict) else None) or (c.get("traits") if isinstance(c, dict) else None) or []),
            }
        )
        if len(chars) >= 6:
            break
    if not chars:
        for kw in analysis.get("keywords") or []:
            name = str(kw).strip().capitalize()
            if not name or name.lower() in have:
                continue
            have.add(name.lower())
            chars.append({"name": name, "role": "Randfigur", "origin": "", "biography": ""})
            if len(chars) >= 3:
                break
    cfg = _cfg(conn, actor, data)
    routing = _routing(data, cfg)
    out: dict[str, Any] = {"ok": True, "commitsTruth": False, "characters": chars[:6], "localCharacters": chars[:6]}
    if routing["allowed"]:
        system = (
            "Du erzeugst Figurenkandidaten mit vollständigem Charakterstamm (AMASTERv2 §13/§14) aus einer Weltbeschreibung. "
            'Antwort NUR JSON: {"characters": [{"name","role","origin","biography","personality","age","gender","occupation",'
            '"goals":[],"fears":[],"secrets":[],"values":[],"likes":[],"dislikes":[],"knowledge":[],"coreFacts":[],'
            '"speechRegister","humor","conflictStyle","typicalPhrases":[],"favoriteWords":[],"taboos":[],"relations":[{"to","kind","note"}],'
            '"provenance": {"feld": "belegt|abgeleitet|unsicher"}}]}. '
            "Belegtes aus dem Material hat Vorrang ('belegt'); Fehlendes welt- und figurenplausibel ergänzen ('abgeleitet'). "
            "Keine bereits vorhandenen Namen (existingNames). Deutsch, knapp."
        )
        parsed = _llm_json(routing, system, {"worldSummary": summary[:12000], "existingNames": sorted(have), "localCandidates": chars[:6]}, temperature=0.4, max_tokens=2600, timeout=60)
        rows = parsed.get("characters") if parsed else None
        if isinstance(rows, list) and any(isinstance(r, dict) and r.get("name") for r in rows):
            out["characters"] = [r for r in rows if isinstance(r, dict) and r.get("name") and str(r["name"]).strip().lower() not in {n.lower() for n in existing_names}][:8]
            return _llm_label(out, routing)
        return _local_label(out, routing, _LAST_LLM_ERROR)
    return _local_label(out, routing, None)


def suggest_profile_from_config(conn, actor: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = body or {}
    name = str(data.get("name") or "Figur").strip() or "Figur"
    world = str(data.get("world") or "")
    field = str(data.get("field") or "").strip()
    source = str(data.get("source") or data.get("world") or "lokale Weltbeschreibung")[:240]
    existing = data.get("existing")
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except json.JSONDecodeError:
            existing = {}
    if not isinstance(existing, dict):
        existing = {}
    world_name = world.split("\n")[0].strip()[:80]
    generators: dict[str, Any] = {
        "role": "Figur",
        "origin": world_name,
        "personality": f"{name} spricht knapp und prüft die Lage.",
        "biography": f"{name} gehört zu {world_name or 'dieser Welt'}.",
        "speechRegister": "knapp, prüfend",
        "conflictStyle": "hält Distanz, dann klar",
        "humor": "trocken",
        "typicalPhrases": [f"{name} hält inne."],
        "knowledge": [f"Kennt {world_name}"] if world_name else [],
    }
    if not field:
        return {
            "ok": False,
            "commitsTruth": False,
            "error": "field_required",
            "message": "Profiler braucht ein ausgewähltes Feld.",
            "patch": {},
            "source": source,
        }
    profilable = set(generators) | set(_PROFILE_FIELDS_ALL)
    if field not in profilable:
        return {
            "ok": False,
            "commitsTruth": False,
            "error": "unknown_field",
            "message": f"Feld {field} ist nicht profilerbar.",
            "patch": {},
            "source": source,
        }
    current = existing.get(field)
    cfg = _cfg(conn, actor, data)
    routing = _routing(data, cfg)
    out: dict[str, Any] = {
        "ok": True,
        "commitsTruth": False,
        "field": field,
        "oldValue": current if current is not None else "",
        "source": source,
    }
    if routing["allowed"]:
        system = (
            "Profiler (AMASTERv2 §53): Erzeuge genau EIN Profilfeld einer Figur, quellengebunden. "
            'Antwort NUR JSON: {"value": string|[string], "status": "belegt|abgeleitet|unsicher", "reason": string}. '
            "Listenfelder (goals, fears, secrets, values, likes, dislikes, knowledge, coreFacts, typicalPhrases, favoriteWords, "
            "taboos, reactionRules, bindingPatterns, lastingAbilities) als Liste. Nur Quelle und vorhandenes Profil nutzen; "
            "nichts über andere Felder ändern. Deutsch, knapp."
        )
        parsed = _llm_json(routing, system, {"name": name, "field": field, "currentValue": current, "profile": existing, "world": world[:6000], "source": source}, temperature=0.3, max_tokens=600)
        if parsed and parsed.get("value") not in (None, "", []):
            value = parsed["value"]
            out["newValue"] = value
            out["patch"] = {field: value}
            out["status"] = str(parsed.get("status") or "abgeleitet")
            out["reason"] = str(parsed.get("reason") or f"LLM-Profiler für Feld {field}")[:300]
            return _llm_label(out, routing)
        out["newValue"] = generators.get(field, "")
        out["patch"] = {field: generators.get(field, "")} if field in generators else {}
        out["status"] = "abgeleitet-lokal"
        out["reason"] = f"Lokaler Profiler für Feld {field} aus Quelle: {source[:120]}"
        return _local_label(out, routing, _LAST_LLM_ERROR)
    out["newValue"] = generators.get(field, "")
    out["patch"] = {field: generators.get(field, "")} if field in generators else {}
    out["status"] = "abgeleitet-lokal"
    out["reason"] = f"Lokaler Profiler für Feld {field} aus Quelle: {source[:120]}"
    return _local_label(out, routing, None)


def derive_compass_from_config(conn, actor: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = body or {}
    profile = data.get("profile")
    if isinstance(profile, dict):
        blob = json.dumps(profile, ensure_ascii=False)
    else:
        blob = str(profile or "")
    lower = blob.lower()
    spaces: dict[str, Any] = {}
    for space in MEANING_SPACES:
        hit = space.lower() in lower
        spaces[space] = {
            "stance": 0.25 if hit else 0,
            "threshold": 0.42,
            "reaction": "hält inne und prüft, was das mit ihr/ihm macht",
            "bodyCue": "Atem wird kürzer",
            "drive": "Lage verstehen, bevor gehandelt wird",
        }
    cfg = _cfg(conn, actor, data)
    routing = _routing(data, cfg)
    out: dict[str, Any] = {"ok": True, "commitsTruth": False, "localCompassJson": json.dumps({"spaces": spaces}, ensure_ascii=False)}
    if routing["allowed"]:
        system = (
            "Du leitest den Chathere-Kompass (AMASTERv2 §15) aus einem Charakterprofil ab: eine Verhaltenslinse, keine Faktenmaschine. "
            'Antwort NUR JSON: {"spaces": {"<Raum>": {"stance": -1..1, "threshold": 0..1, "reaction": string, "bodyCue": string, "drive": string}}}. '
            f"Räume genau: {', '.join(MEANING_SPACES)}. stance = Disposition der Figur zu diesem Bedeutungsraum "
            "(negativ = weicht aus/fürchtet, positiv = sucht/eskaliert), threshold = Auslöseschwelle, reaction/bodyCue/drive figurenspezifisch "
            "aus Persönlichkeit, Ängsten, Zielen, Geheimnissen. Deutsch, knapp."
        )
        parsed = _llm_json(routing, system, {"name": data.get("name"), "profile": profile if isinstance(profile, dict) else blob[:8000]}, temperature=0.3, max_tokens=1800)
        got = parsed.get("spaces") if parsed else None
        if isinstance(got, dict) and got:
            merged = dict(spaces)
            for space, cell in got.items():
                if space in merged and isinstance(cell, dict):
                    row = dict(merged[space])
                    for k in ("stance", "threshold", "reaction", "bodyCue", "drive"):
                        if cell.get(k) not in (None, ""):
                            row[k] = cell[k]
                    try:
                        row["stance"] = max(-1.0, min(1.0, float(row.get("stance") or 0)))
                        row["threshold"] = max(0.0, min(1.0, float(row.get("threshold") or 0.42)))
                    except (TypeError, ValueError):
                        pass
                    merged[space] = row
            out["compassJson"] = json.dumps({"spaces": merged}, ensure_ascii=False)
            return _llm_label(out, routing)
        out["compassJson"] = out["localCompassJson"]
        return _local_label(out, routing, _LAST_LLM_ERROR)
    out["compassJson"] = out["localCompassJson"]
    return _local_label(out, routing, None)


def ping_provider(conn, actor: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """V25 (Vertrag §14): echter, minimaler Provider-Probe mit dem gespeicherten
    Frontend-Key und dem gewählten Modell. Kein Key im Ergebnis."""
    data = body or {}
    cfg = _cfg(conn, actor, data)
    routing = _routing(data, cfg)
    status = provider_status(cfg)
    out: dict[str, Any] = {
        "ok": False,
        "probed": False,
        "keyPresent": bool(routing["apiKey"]),
        "keySource": routing["keySource"],
        "provider": routing["provider"] if routing["apiKey"] else "synapse",
        "model": routing["model"] if routing["apiKey"] else str(cfg.get("model") or ""),
        "endpoint": routing["endpoint"] if routing["apiKey"] else "",
        "network": False,
        "commitsTruth": False,
        "liveStatus": status,
        "providerChosen": routing["providerChosen"],
        "providerResolved": routing["providerResolved"],
    }
    if not routing["apiKey"]:
        out["reason"] = "kein API-Key gespeichert (Konfiguration → Sprachdienst)"
        out["error"] = "LLM_REQUIRED"
        return out
    if not routing["allowed"]:
        out["reason"] = "LLM deaktiviert (Provider = lokale Synapse oder MATRIX_DISABLE_LLM)"
        out["error"] = "LLM_DISABLED"
        return out
    if not (data.get("live") or data.get("probe") or cfg.get("pingLive", True)):
        out["reason"] = "kein Live-Probe angefordert"
        return out
    parsed = _llm_json(routing, 'Antworte NUR mit JSON: {"pong": true}', "ping", temperature=0.0, max_tokens=8, timeout=20)
    out["probed"] = True
    out["network"] = True
    if parsed is not None:
        out["ok"] = True
        out["reason"] = f"Provider {routing['provider']} antwortet mit Modell {routing['model']}"
    else:
        out["ok"] = False
        out["error"] = _LAST_LLM_ERROR or "LLM_FAILED"
        out["reason"] = f"Provider {routing['provider']} nicht erreichbar oder Key/Modell ungültig: {out['error']}"
    return out


def _quote_in_source(quote: str, text: str) -> bool:
    q = " ".join((quote or "").split()).strip().lower()
    if len(q) < 8:
        return False
    blob = " ".join((text or "").split()).lower()
    return q in blob


def merge_recognition(analysis: dict[str, Any], rec: dict[str, Any], text: str) -> dict[str, Any]:
    """Overlay LLM labels onto local evidence. No new names, no new timeline, no rewrite."""
    out = dict(analysis or {})
    world = dict(out.get("world") or {})
    people = rec.get("people") if isinstance(rec.get("people"), list) else []
    by_name: dict[str, dict[str, Any]] = {}
    for p in people:
        if not isinstance(p, dict):
            continue
        nm = str(p.get("name") or "").strip()
        if nm:
            by_name[nm.lower()] = p

    def _apply_chars(rows: list[Any]) -> list[Any]:
        kept: list[Any] = []
        for c in rows:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            p = by_name.get(str(c.get("name")).lower())
            if p and p.get("keep") is False:
                quote = str(p.get("quote") or "")
                if quote and not _quote_in_source(quote, text):
                    kept.append(c)
                    continue
                continue
            nxt = dict(c)
            if p:
                role = str(p.get("role") or "").strip()
                quote = str(p.get("quote") or "")
                hay = f"{quote} {c.get('biography') or ''}".lower()
                if role and role.lower() in hay:
                    if not quote or _quote_in_source(quote, text):
                        nxt["role"] = role
                if quote and _quote_in_source(quote, text) and not nxt.get("nameEtymon"):
                    nxt["nameEtymon"] = quote[:180]
            kept.append(nxt)
        return kept

    out["characterCandidates"] = _apply_chars(list(out.get("characterCandidates") or []))
    out["spawnCandidates"] = _apply_chars(list(out.get("spawnCandidates") or []))

    existing_l = {str(c.get("name") or "").lower() for c in out["characterCandidates"]}
    place_l = {str((p or {}).get("name") or "").lower() for p in (world.get("places") or []) if isinstance(p, dict)}
    for p in people:
        nm = str(p.get("name") or "").strip()
        if not nm or nm.lower() in existing_l or nm.lower() in place_l:
            continue
        if p.get("keep") is False:
            continue
        quote = str(p.get("quote") or "")
        if not _quote_in_source(quote, text) or nm.lower() not in quote.lower():
            continue
        toks = nm.split()
        if not toks or any(not t[:1].isupper() for t in toks):
            continue
        if any(t.lower() in STOP for t in toks):
            continue
        role = str(p.get("role") or "").strip()
        hay = quote.lower()
        extra = {
            "name": nm,
            "role": role if role and role.lower() in hay else "",
            "biography": quote[:240],
            "nameEtymon": quote[:180],
            "aliases": [nm],
        }
        out["characterCandidates"].append(extra)
        out["spawnCandidates"].append(extra)
        existing_l.add(nm.lower())

    raw_kw = rec.get("keywords") if isinstance(rec.get("keywords"), list) else []
    kws: list[str] = []
    blob = " ".join((text or "").split()).lower()
    for k in raw_kw:
        w = str(k or "").strip()
        if len(w) < 4 or w.lower() in STOP:
            continue
        if w.lower() not in blob:
            continue
        if w.lower() not in {x.lower() for x in kws}:
            kws.append(w.lower())
        if len(kws) >= 12:
            break
    if kws:
        out["keywords"] = kws

    raw_places = rec.get("places") if isinstance(rec.get("places"), list) else []
    if raw_places and world.get("places"):
        drop = {
            str(p.get("name") or "").lower()
            for p in raw_places
            if isinstance(p, dict) and p.get("keep") is False and _quote_in_source(str(p.get("quote") or ""), text)
        }
        if drop:
            world["places"] = [p for p in world["places"] if str((p or {}).get("name") or "").lower() not in drop]

    out["world"] = world
    out["llm"] = True
    out["recognize"] = "llm"
    out["commitsTruth"] = False
    return out


DRIVE_NAMES = {"selbsterhaltung", "bindung", "rang", "neugier", "fürsorge", "fuersorge", "lust", "vergeltung", "sicherheit", "anerkennung", "freiheit"}

PROFILE_STR = (
    "biography",
    "age",
    "gender",
    "occupation",
    "origin",
    "personality",
    "speechRegister",
    "dialect",
    "humor",
    "conflictStyle",
    "appearance",
    "typicalPlace",
    "worldNotes",
)
PROFILE_LIST = (
    "typicalPhrases",
    "favoriteWords",
    "taboos",
    "values",
    "goals",
    "fears",
    "secrets",
    "likes",
    "dislikes",
    "reactionRules",
    "bindingPatterns",
    "knowledge",
    "coreFacts",
    "lastingAbilities",
)


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple)):
        return len(value) == 0
    return False


def _as_str_list(value: Any, cap: int = 6) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()[:160]]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        t = str(item or "").strip()
        if t and t not in out:
            out.append(t[:160])
        if len(out) >= cap:
            break
    return out


def _rel_from_llm(item: Any, self_name: str, known: dict[str, str]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    raw = str(item.get("to") or item.get("targetName") or item.get("name") or "").strip()
    if not raw:
        return None
    target = known.get(raw.lower())
    if not target:
        first = raw.split()[0].lower()
        target = next((n for k, n in known.items() if k.split()[0] == first), None)
    if not target or target.lower() == self_name.lower():
        return None
    def _n(key: str, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(item.get(key) if item.get(key) is not None else default)))
        except (TypeError, ValueError):
            return default
    return {
        "targetName": target,
        "kind": str(item.get("kind") or "kennt")[:40],
        "note": str(item.get("note") or item.get("text") or "")[:180],
        "trust": _n("trust", 0.5),
        "closeness": _n("closeness", 0.4),
        "fear": _n("fear", 0.1),
    }


def _profile_for(name: str, by: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    key = (name or "").strip().lower()
    if not key:
        return None
    if key in by:
        return by[key]
    first = key.split()[0]
    hits = [v for k, v in by.items() if k == first or k.startswith(first + " ") or first.startswith(k.split()[0])]
    if len(hits) == 1:
        return hits[0]
    contained = [v for k, v in by.items() if k in key or key in k]
    if len(contained) == 1:
        return contained[0]
    return None


_QUOTE_MARKS = ("\"", "„", "“", "”", "&quot;", "»", "«")
_GENDER_MAP = {"m": "männlich", "männlich": "männlich", "mann": "männlich", "male": "männlich", "w": "weiblich", "f": "weiblich", "weiblich": "weiblich",
               "frau": "weiblich", "female": "weiblich", "divers": "divers", "d": "divers", "nonbinary": "divers", "nicht-binär": "divers"}


def _looks_quoted(value: str) -> bool:
    v = str(value or "")
    return any(m in v for m in _QUOTE_MARKS)


def _in_speech(phrase: str, own_speech: list[str], text: str) -> bool:
    ph = re.sub(r"\s+", " ", str(phrase or "")).strip().strip("„“”\"» «").lower()
    if len(ph) < 3:
        return False
    for sp in own_speech:
        spn = re.sub(r"\s+", " ", str(sp or "")).strip().strip("„“”\"» «").lower()
        if ph in spn or spn in ph:
            return True
    return False


def validate_profile(p: dict[str, Any], own_speech: list[str] | None = None, text: str = "") -> dict[str, Any]:
    """V26 (V1 §B): Post-Processing-Validierung eines LLM-Profils. Zitate raus aus knowledge/
    biography/reaction, typicalPhrases nur aus eigener Rede, Zahlen 0..1, gender normiert,
    Provenienz bei Korrekturen 'unsicher'."""
    row = dict(p or {})
    prov = dict(row.get("provenance") or {}) if isinstance(row.get("provenance"), dict) else {}
    own = [str(x) for x in (own_speech or []) if str(x).strip()]
    # Provenienzwörter sind keine Feldwerte (Nutzerlauf: origin = "belegt")
    for k in PROFILE_STR:
        v = row.get(k)
        if isinstance(v, str) and v.strip().lower() in ("belegt", "abgeleitet", "unsicher", "n/a", "unbekannt", "null", "none", "-"):
            row[k] = ""
            prov[k] = "unsicher"
    g = str(row.get("gender") or "").strip().lower()
    if g:
        row["gender"] = _GENDER_MAP.get(g, "")
        if not row["gender"]:
            prov["gender"] = "unsicher"
    if row.get("knowledge"):
        kept = [str(k) for k in row["knowledge"] if str(k).strip() and not _looks_quoted(str(k))]
        if len(kept) != len(row["knowledge"]):
            prov["knowledge"] = "unsicher"
        row["knowledge"] = kept
    bio = str(row.get("biography") or "")
    if _looks_quoted(bio):
        row["biography"] = re.sub(r"\s+", " ", re.sub(r"[„“”\"»«]([^„“”\"»«]{0,400})[„“”\"»«]", "", bio.replace("&quot;", "\""))).strip(" .,;-")
        prov["biography"] = "unsicher"
    phrases = [str(x) for x in (row.get("typicalPhrases") or []) if str(x).strip()]
    if phrases:
        if own:
            ok = [ph for ph in phrases if _in_speech(ph, own, text)]
            if len(ok) != len(phrases):
                prov["typicalPhrases"] = "unsicher" if ok else "belegt"
            row["typicalPhrases"] = ok
        else:
            row["typicalPhrases"] = []
            prov["typicalPhrases"] = "unsicher"
    rels = []
    for r in row.get("relations") or []:
        if not isinstance(r, dict):
            continue
        rr = dict(r)
        for k, d in (("trust", 0.5), ("closeness", 0.4), ("fear", 0.1)):
            try:
                rr[k] = max(0.0, min(1.0, float(rr.get(k) if rr.get(k) is not None else d)))
            except (TypeError, ValueError):
                rr[k] = d
        rels.append(rr)
    if rels:
        row["relations"] = rels
    comp = row.get("compass")
    if isinstance(comp, dict):
        spaces = comp.get("spaces") if isinstance(comp.get("spaces"), dict) else comp
        clean: dict[str, Any] = {}
        for space, cell in spaces.items():
            if space not in MEANING_SPACES or not isinstance(cell, dict):
                continue
            c2 = {}
            try:
                c2["stance"] = max(-1.0, min(1.0, float(cell.get("stance") or 0)))
                c2["threshold"] = max(0.0, min(1.0, float(cell.get("threshold") or 0.42)))
            except (TypeError, ValueError):
                c2["stance"], c2["threshold"] = 0.0, 0.42
            for k in ("reaction", "bodyCue", "drive"):
                v = str(cell.get(k) or "").strip()
                if _looks_quoted(v):
                    v = ""
                    prov["compass"] = "unsicher"
                c2[k] = v[:160]
            if c2["reaction"] or c2["drive"]:
                clean[space] = c2
        row["compass"] = clean
    # V49: alle Profilfelder garantiert vorhanden (leere Liste / leerer String statt fehlender Schlüssel)
    for k in PROFILE_LIST:
        if not isinstance(row.get(k), list):
            row[k] = [] if row.get(k) in (None, "", [], {}) else [str(row.get(k))]
    for k in PROFILE_STR:
        if row.get(k) is None:
            row[k] = ""
    # Triebe (Urtriebe) — nur bekannte Namen, Stärke 0..1, Beleg-Text
    drives_out: list[dict[str, Any]] = []
    for d in (row.get("drives") or []) if isinstance(row.get("drives"), list) else []:
        if not isinstance(d, dict):
            continue
        name = str(d.get("drive") or d.get("name") or "").strip()
        if not name or name.lower() not in DRIVE_NAMES:
            continue
        try:
            strength = max(0.0, min(1.0, float(d.get("strength") if d.get("strength") is not None else 0.5)))
        except (TypeError, ValueError):
            strength = 0.5
        drives_out.append({"drive": name[:1].upper() + name[1:], "strength": round(strength, 2), "evidence": str(d.get("evidence") or "")[:200]})
    row["drives"] = drives_out[:5]
    row["provenance"] = prov
    return row


def merge_profiles(analysis: dict[str, Any], rec: dict[str, Any]) -> dict[str, Any]:
    """Fill empty Stamm fields from LLM. Never invent names. Keep non-empty local values."""
    out = dict(analysis or {})
    profiles = rec.get("profiles") if isinstance(rec.get("profiles"), list) else []
    speech_by = {
        str(c.get("name") or "").strip().lower(): [str(x) for x in (c.get("ownSpeech") or [])]
        for c in (out.get("characterCandidates") or [])
        if isinstance(c, dict) and c.get("name")
    }
    profiles = [validate_profile(p, speech_by.get(str(p.get("name") or "").strip().lower(), []), "") for p in profiles if isinstance(p, dict)]
    by: dict[str, dict[str, Any]] = {}
    for p in profiles:
        if isinstance(p, dict) and str(p.get("name") or "").strip():
            by[str(p.get("name")).strip().lower()] = p

    def _apply(rows: list[Any]) -> list[Any]:
        known = {
            str(c.get("name") or "").strip().lower(): str(c.get("name") or "").strip()
            for c in rows
            if isinstance(c, dict) and c.get("name")
        }
        kept: list[Any] = []
        for c in rows:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            nxt = dict(c)
            p = _profile_for(str(c.get("name")), by)
            if not p:
                kept.append(nxt)
                continue
            prov_in = p.get("provenance") if isinstance(p.get("provenance"), dict) else {}
            prov = dict(nxt.get("fieldProvenance") or {}) if isinstance(nxt.get("fieldProvenance"), dict) else {}
            # V26: lokale Zitat-Fragmente in biography/knowledge sind kein Beleg (V1 §1/§4) —
            # das paraphrasierte LLM-Profil ersetzt sie.
            if _looks_quoted(str(nxt.get("biography") or "")) and not _blank(p.get("biography")):
                nxt["biography"] = ""
            if any(_looks_quoted(str(k)) for k in (nxt.get("knowledge") or [])) and p.get("knowledge"):
                nxt["knowledge"] = []
            for key in PROFILE_STR:
                if _blank(nxt.get(key)) and not _blank(p.get(key)):
                    nxt[key] = str(p.get(key)).strip()[:1200 if key == "biography" else 400]
                    prov[key] = str(prov_in.get(key) or "abgeleitet")
                elif not _blank(nxt.get(key)) and key not in prov:
                    prov[key] = "belegt"
            if isinstance(p.get("compass"), dict) and p["compass"]:
                nxt["compass"] = p["compass"]
                prov["compass"] = str(prov_in.get("compass") or "abgeleitet")
            if "typicalPhrases" in p and not p.get("typicalPhrases"):
                nxt["typicalPhrases"] = [x for x in (nxt.get("typicalPhrases") or []) if not _looks_quoted(str(x)) or _in_speech(str(x), [str(y) for y in (nxt.get("ownSpeech") or [])], "")]
            for key in PROFILE_LIST:
                if _blank(nxt.get(key)):
                    filled = _as_str_list(p.get(key))
                    if filled:
                        nxt[key] = filled
                        prov[key] = str(prov_in.get(key) or "abgeleitet")
                elif key not in prov:
                    prov[key] = "belegt"
            if nxt.get("typicalPhrases"):
                nxt["typicalPhrases"] = [_strip_quotes(x) for x in nxt["typicalPhrases"] if _strip_quotes(x)]
            # V49: Triebe (validiert in validate_profile) und garantierte Listenfelder übernehmen
            if isinstance(p.get("drives"), list) and _blank(nxt.get("drives")):
                nxt["drives"] = [d for d in p["drives"] if isinstance(d, dict) and d.get("drive")][:5]
                if nxt["drives"]:
                    prov["drives"] = str(prov_in.get("drives") or "abgeleitet")
            for key in PROFILE_LIST:
                if not isinstance(nxt.get(key), list):
                    nxt[key] = []
            nxt["fieldProvenance"] = prov
            if _blank(nxt.get("occupation")) and nxt.get("role"):
                nxt["occupation"] = str(nxt.get("role"))
            if _blank(nxt.get("relations")):
                rels = []
                for item in p.get("relations") or []:
                    rel = _rel_from_llm(item, str(nxt.get("name")), known)
                    if rel:
                        rels.append(rel)
                if rels:
                    nxt["relations"] = rels[:8]
            kept.append(nxt)
        return kept

    out["characterCandidates"] = _apply(list(out.get("characterCandidates") or []))
    out["spawnCandidates"] = _apply(list(out.get("spawnCandidates") or []))
    out["profileComplete"] = "llm"
    out["commitsTruth"] = False
    return out


PROFILE_KEYS = (
    "age", "gender", "occupation", "origin", "biography", "personality", "speechRegister", "dialect", "humor",
    "conflictStyle", "appearance", "typicalPlace", "worldNotes", "typicalPhrases", "favoriteWords", "taboos", "values",
    "goals", "fears", "secrets", "likes", "dislikes", "reactionRules", "bindingPatterns", "knowledge", "coreFacts",
    "lastingAbilities", "relations", "drives", "compass", "provenance",
)

PROFILE_RULES = (
    "Du formst EIN Chathere-Stammprofil aus dem Original (AMASTERv2 §14/§15). Kein neuer Roman, keine neuen Namen. "
    'Antwort NUR JSON mit GENAU diesen Schlüsseln (kein Schlüssel darf fehlen): '
    '{"name", "age", "gender", "occupation", "origin", "biography", "personality", "speechRegister", "dialect", "humor", '
    '"conflictStyle", "appearance", "typicalPlace", "worldNotes", "typicalPhrases": [], "favoriteWords": [], "taboos": [], "values": [], '
    '"goals": [], "fears": [], "secrets": [], "likes": [], "dislikes": [], "reactionRules": [], "bindingPatterns": [], "knowledge": [], '
    '"coreFacts": [], "lastingAbilities": [], "relations": [{"to", "kind", "note", "trust", "closeness", "fear"}], '
    '"drives": [{"drive": "Selbsterhaltung|Bindung|Rang|Neugier|Fürsorge|Lust|Vergeltung|Sicherheit|Anerkennung|Freiheit", "strength": 0..1, "evidence"}], '
    '"compass": {"<Raum>": {"stance", "threshold", "reaction", "bodyCue", "drive"}}, "provenance": {"<feld>": "belegt|abgeleitet|unsicher"}}. '
    "FELDREGELN — verbindlich: "
    "(0) drives = 2–4 Urtriebe, die diese Figur im Text erkennbar antreiben (Selbsterhaltung, Bindung, Rang, Neugier, Fürsorge, Lust, Vergeltung, Sicherheit, Anerkennung, Freiheit) mit Stärke 0..1 und evidence = Szene/Satzstück, in dem sich der Trieb zeigt; Felder ohne Beleg als leere Liste/null zurückgeben, NIE weglassen. "
    "(1) knowledge = 4–8 paraphrasierte, belegte FAKTEN über die Figur (Herkunft, Stellung, Vergangenheit, Können); KEINE Zitate, keine Sätze anderer über sie im Wortlaut. "
    "(2) biography = zusammenhängende Lebens- und Situationsgeschichte in 5–7 eigenen Sätzen; KEINE Zitate. "
    "(3) typicalPhrases = NUR Sätze, die die Figur SELBST spricht, ausschließlich aus ownSpeech (bis 6); ist ownSpeech leer, bleibt typicalPhrases []. Keine Tagebuch- oder Erzählersätze anderer. "
    "(4) goals = 2–4 konkrete Handlungsziele, die die Figur im Original aktiv verfolgt (z. B. 'Alicia zurückgewinnen'), keine Allgemeinplätze wie 'Kontrolle behalten'. "
    "(5) fears/secrets = konkret und figurenbezogen (je 1–4). "
    "(6) gender = 'männlich'|'weiblich'|'divers' aus Pronomen/Anrede im Original; age = Zahl oder Alterswirkung; occupation = Beruf/Stellung. "
    "(7) relations: zu Namen aus roster (bis 8): Werte 0..1 aus den Szenen abgeleitet (Ehe/Familie hoch, Verrat/Feind niedrig, Angestellte neutral), note = kurze Begründung; nicht alle gleich. "
    "Hat die Figur mit einer Roster-Figur eine belastete Vergangenheit (Trauma, Verrat, Schuld, Verlust), MUSS diese Beziehung mit hohem fear/niedrigem trust und der Ursache in note erscheinen. "
    "(8) compass = Verhaltenslinse für ALLE Räume " + ", ".join(MEANING_SPACES) + ": stance -1..1 (weicht aus/fürchtet … sucht/eskaliert), threshold 0..1, reaction = wie die Figur typischerweise reagiert, bodyCue = körperliches Anzeichen, drive = treibendes Bedürfnis — psychologische Beschreibung, KEINE Zitate. "
    "Quellen im Payload: castSummary (Ganzbuch-Kurzfassung), relationsFromCast (belegte Beziehungen aus dem ganzen Buch — übernehmen und ausgestalten, nicht widersprechen), passages (Textstellen mit der Figur), evidence, facts, ownSpeech. "
    "(9) provenance für JEDES Feld: 'belegt' (aus passages/evidence/facts/ownSpeech), 'abgeleitet' (welt-/figurenplausibel ergänzt), 'unsicher' (schwache Grundlage). "
    "Kein Feld leer lassen außer typicalPhrases ohne ownSpeech. Deutsch, knapp, konkret."
)


def _pack_profile_one(cand: dict[str, Any], roster: list[str], text: str, title: str) -> dict[str, Any]:
    known = {k: cand.get(k) for k in PROFILE_KEYS if k in cand and not _blank(cand.get(k)) and k not in ("relations", "compass", "provenance")}
    return {
        "title": title,
        "name": cand.get("name"),
        "aliases": list(cand.get("aliases") or [])[:5],
        "role": cand.get("role") or "",
        "castSummary": str(cand.get("castSummary") or "")[:700],
        "relationsFromCast": [r for r in (cand.get("relations") or []) if isinstance(r, dict)][:10],
        "passages": [str(p)[:700] for p in (cand.get("passages") or [])][:24],
        "evidence": [str(q)[:220] for q in (cand.get("sourceEvidence") or [])][:8] or ([str(cand.get("nameEtymon"))[:180]] if cand.get("nameEtymon") else []),
        "ownSpeech": [str(q)[:200] for q in (cand.get("ownSpeech") or [])][:10],
        "facts": [str(k)[:200] for k in (cand.get("knowledge") or [])][:8],
        "relationsSeen": [r for r in (cand.get("relationships") or []) if isinstance(r, dict)][:8],
        "alreadyKnown": known,
        "roster": [n for n in roster if n and n != cand.get("name")][:24],
        "excerpt": " ".join((text or "").split())[:1600],
    }


def _try_complete_profiles(routing: dict[str, Any], analysis: dict[str, Any], text: str, title: str) -> dict[str, Any] | None:
    """V27 CHAR-01: EIN Provider-Aufruf JE Figur (vollständiges Schema, ausreichend Tokens),
    parallel. Ein Sammelaufruf für viele Figuren lieferte verkürzte Profile ohne die
    meisten Felder (Nutzerbefund). Rückgabe {"profiles": [...]} oder None."""
    cands = [c for c in (analysis.get("characterCandidates") or []) if isinstance(c, dict) and c.get("name")]
    if not cands:
        return None
    roster = list(dict.fromkeys([str(c.get("name")) for c in cands] + [str(n) for n in (analysis.get("roster") or []) if str(n).strip()]))
    cands = cands[:40]

    def _one(cand: dict[str, Any]) -> dict[str, Any] | None:
        parsed = _llm_json(routing, PROFILE_RULES, _pack_profile_one(cand, roster, text, title), temperature=0.2, max_tokens=2600, timeout=180, max_input_chars=40000)
        if not parsed:
            return None
        if isinstance(parsed.get("profiles"), list) and parsed["profiles"]:
            parsed = parsed["profiles"][0] if isinstance(parsed["profiles"][0], dict) else {}
        if not isinstance(parsed, dict):
            return None
        parsed["name"] = cand.get("name")
        return parsed

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(ANALYSIS_WORKERS, len(cands))) as pool:
        rows = list(pool.map(_one, cands))
    profiles = [r for r in rows if isinstance(r, dict)]
    if not profiles:
        return None
    # V28 zweite Stufe (AMASTERv2 §53 feldbezogen, Nutzerlauf: likes/dislikes/favoriteWords/
    # lastingAbilities/taboos/values blieben leer): fehlende Felder gezielt nachfordern.
    by_name = {str(c.get("name")): c for c in cands}

    def _fill_missing(prof: dict[str, Any]) -> dict[str, Any]:
        cand = by_name.get(str(prof.get("name")), {})
        own = [str(x) for x in (cand.get("ownSpeech") or [])]
        missing = [k for k in (*PROFILE_STR, *PROFILE_LIST) if _blank(prof.get(k)) and _blank(cand.get(k)) and not (k == "typicalPhrases" and not own)]
        if not missing:
            return prof
        system = (
            "Profiler (AMASTERv2 §53): Ergänze für die Figur NUR die genannten fehlenden Profilfelder, "
            "welt- und figurenplausibel aus dem vorhandenen Profil und den Belegen ('abgeleitet', bei schwacher Grundlage 'unsicher'). "
            'Antwort NUR JSON: {"fields": {"<feld>": wert}, "provenance": {"<feld>": "abgeleitet|unsicher"}}. '
            "Listenfelder als Liste mit 2–5 Einträgen; Textfelder als knapper Text. Keine Zitate. Deutsch."
        )
        known = {k: prof.get(k) for k in (*PROFILE_STR, *PROFILE_LIST) if not _blank(prof.get(k))}
        parsed = _llm_json(routing, system, {"name": prof.get("name"), "role": cand.get("role"), "missing": missing, "profile": known, "evidence": [str(q)[:200] for q in (cand.get("sourceEvidence") or [])][:6]}, temperature=0.4, max_tokens=900, timeout=60)
        if not parsed or not isinstance(parsed.get("fields"), dict):
            return prof
        prov = dict(prof.get("provenance") or {})
        for k, v in parsed["fields"].items():
            if k in missing and not _blank(v):
                prof[k] = v
                prov[k] = str((parsed.get("provenance") or {}).get(k) or "abgeleitet")
        prof["provenance"] = prov
        return prof

    with ThreadPoolExecutor(max_workers=min(ANALYSIS_WORKERS, len(profiles))) as pool:
        profiles = list(pool.map(_fill_missing, profiles))
    out: dict[str, Any] = {"profiles": profiles}
    if len(profiles) < len(cands):
        out["partial"] = {"requested": len(cands), "received": len(profiles), "lastError": _last_llm_error()}
    return out


def _pack_recognize(analysis: dict[str, Any], text: str, title: str) -> dict[str, Any]:
    cands = []
    for c in (analysis.get("characterCandidates") or [])[:16]:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        cands.append(
            {
                "name": c.get("name"),
                "role": c.get("role") or "",
                "aliases": list(c.get("aliases") or [])[:4],
                "quote": str(c.get("nameEtymon") or (c.get("biography") or ""))[:280],
            }
        )
    world = analysis.get("world") if isinstance(analysis.get("world"), dict) else {}
    start = world.get("startScenes") or []
    excerpts = []
    if start:
        excerpts.append(str(start[0])[:400])
    excerpts.append(" ".join((text or "").split())[:1800])
    return {
        "title": title or world.get("name") or "",
        "candidates": cands,
        "places": [p.get("name") for p in (world.get("places") or [])[:8] if isinstance(p, dict)],
        "keywords_local": analysis.get("keywords") or [],
        "excerpts": excerpts,
    }


def _try_recognize(routing: dict[str, Any], analysis: dict[str, Any], text: str, title: str) -> dict[str, Any] | None:
    system = (
        "Du ERKENNST nur, was im Original steht. Du schreibst keinen Roman und keine Weltwahrheit. "
        "Antwort NUR JSON: {people, keywords, places}. "
        "people: Liste {name, keep, role, quote}. name zuerst aus candidates. "
        "Weitere Namen nur, wenn quote sie nennt und sie Menschen sind. "
        "keep=false nur wenn quote belegt, dass es kein Mensch ist. "
        "role nur wenn quote den Beruf oder die Funktion nennt (Haushälterin, Assistentin, Ehefrau, Fahrer). "
        "keywords: Motive und Eigennamen aus excerpts, keine Funktionswörter. "
        "places: {name, keep, quote} nur aus der Liste, keine neuen Orte. "
        "quote muss ein Satzstück aus excerpts sein."
    )
    return _llm_json(routing, system, _pack_recognize(analysis, text, title), temperature=0.1, max_tokens=800, timeout=40)


def local_complete_character(row: dict[str, Any]) -> dict[str, Any]:
    """Fill leftover empty Stamm fields from role, Anrede and already stored quotes."""
    nxt = dict(row or {})
    name = str(nxt.get("name") or "").strip()
    role = str(nxt.get("role") or "").strip()
    bio = str(nxt.get("biography") or "")
    blob = f"{name} {role} {bio}".lower()
    if _blank(nxt.get("gender")):
        if name.startswith("Mrs") or name.startswith("Miss") or name.startswith("Frau") or any(
            x in blob for x in ("haushälterin", "tochter", "ehefrau", "erzählerin", "kindermädchen", "assistentin")
        ):
            nxt["gender"] = "weiblich"
        elif name.startswith("Mr") or name.startswith("Herr") or any(
            x in blob for x in ("fahrer", "mogul", "ehemann", "sohn", "assistent", "chauffeur", "körperwächter")
        ):
            nxt["gender"] = "männlich"
        else:
            male = len(re.findall(r"\b(er|ihn|ihm|sein|seine)\b", bio.lower()))
            female = len(re.findall(r"\b(sie|ihr|ihre)\b", bio.lower()))
            if male > female and male >= 2:
                nxt["gender"] = "männlich"
            elif female > male and female >= 2:
                nxt["gender"] = "weiblich"
    if _blank(nxt.get("occupation")) and role:
        nxt["occupation"] = role
    if _blank(nxt.get("occupation")):
        from matrix_api.analyze import _occupation_from_text

        nxt["occupation"] = _occupation_from_text(bio) or nxt.get("occupation") or ""
    if _blank(nxt.get("role")) and nxt.get("occupation"):
        nxt["role"] = nxt.get("occupation")
    if _blank(nxt.get("typicalPlace")) and nxt.get("origin"):
        nxt["typicalPlace"] = nxt.get("origin")
    if _blank(nxt.get("species")) and nxt.get("gender"):
        nxt["species"] = "Mensch"
    if _blank(nxt.get("speechRegister")) and nxt.get("typicalPhrases"):
        nxt["speechRegister"] = "Rede aus dem Original"
    if _blank(nxt.get("worldNotes")) and bio:
        nxt["worldNotes"] = bio.split(".")[0].strip()[:240]
    if not nxt.get("bindingPatterns") and nxt.get("relations"):
        nxt["bindingPatterns"] = [
            f"{r.get('kind') or 'kennt'} · {r.get('targetName') or r.get('to') or ''}".strip(" ·")
            for r in (nxt.get("relations") or [])
            if isinstance(r, dict)
        ][:4]
    if not nxt.get("reactionRules") and isinstance(nxt.get("compass"), dict):
        nxt["reactionRules"] = [
            f"{k}: {v.get('drive')}"
            for k, v in nxt["compass"].items()
            if isinstance(v, dict) and v.get("drive")
        ][:4]
    if _blank(nxt.get("age")) and nxt.get("gender") == "weiblich" and name.startswith("Mrs"):
        nxt["age"] = "älter"
    if _blank(nxt.get("age")) and "tochter" in role.lower():
        nxt["age"] = "Kind / Jugend"
    if _blank(nxt.get("age")) and any(x in role.lower() for x in ("haushälter", "fahrer", "mogul")):
        nxt["age"] = "erwachsen"
    if not nxt.get("taboos"):
        bio = str(nxt.get("biography") or "")
        nxt["taboos"] = [
            s.strip()[:160]
            for s in re.split(r"[.!?]", bio)
            if re.search(r"\b(?:darf nicht|nicht sagen|niemand darf)\b", s, re.I)
        ][:3]
    # V25: lokal ergänzte Felder sind Ableitungen, keine Belege (Vertrag §8).
    prov = dict(nxt.get("fieldProvenance") or {}) if isinstance(nxt.get("fieldProvenance"), dict) else {}
    for key in (*PROFILE_STR, *PROFILE_LIST, "species", "role"):
        if _blank(row.get(key)) and not _blank(nxt.get(key)) and key not in prov:
            prov[key] = "abgeleitet-lokal"
    if prov:
        nxt["fieldProvenance"] = prov
    return nxt


def enrich_analysis(
    analysis: dict[str, Any],
    text: str,
    title: str = "",
    *,
    network: bool = False,
    routing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Local evidence first. Network LLM only over the configured routing (V25)."""
    out = dict(analysis or {})
    out.setdefault("recognize", "local")
    out.setdefault("commitsTruth", False)
    if not text or not out.get("ok"):
        return out
    if routing is None and network:
        routing = _routing({}, {})
    if network and routing and routing.get("allowed"):
        rec = _try_recognize(routing, out, text, title)
        if rec:
            out = merge_recognition(out, rec, text)
        prof = _try_complete_profiles(routing, out, text, title)
        if prof:
            out = merge_profiles(out, prof)
            out["profileSource"] = "llm"
            out["llmProvider"] = routing.get("provider")
            out["llmModel"] = routing.get("model")
        else:
            out["profileSource"] = "local-fallback"
            out["llmError"] = _LAST_LLM_ERROR
    elif network:
        out["profileSource"] = "local-fallback"
        out["llmError"] = "LLM_REQUIRED"
    out["characterCandidates"] = [
        local_complete_character(c) if isinstance(c, dict) else c for c in (out.get("characterCandidates") or [])
    ]
    out["spawnCandidates"] = [
        local_complete_character(c) if isinstance(c, dict) else c for c in (out.get("spawnCandidates") or [])
    ]
    return out


def complete_profiles_from_config(conn, actor: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """V25 LLM-03/CHAR-01: Profilvervollständigung über den konfigurierten Provider
    (Provider, Key, Modell aus der gescopten Config). Ohne Provider: lokaler
    Entwurf, ehrlich markiert (ok=false, source=local-fallback). Schreibt keinen Stamm."""
    data = body if isinstance(body, dict) else {}
    text = str(data.get("text") or data.get("source") or "")
    title = str(data.get("title") or data.get("name") or "")
    raw = data.get("candidates") or data.get("characterCandidates") or []
    cands = [c for c in raw if isinstance(c, dict) and c.get("name")]
    roster_in = [str(n).strip() for n in (data.get("roster") or []) if str(n).strip()] if isinstance(data.get("roster"), list) else []
    out: dict[str, Any] = {
        "ok": True,
        "commitsTruth": False,
        "characterCandidates": cands,
        "spawnCandidates": list(cands),
        "roster": list(dict.fromkeys([str(c.get("name")) for c in cands] + roster_in)),
        "recognize": "local",
    }
    cfg = _cfg(conn, actor, data) if conn is not None else {}
    routing = _routing(data, cfg)
    llm_ok = False
    if routing["allowed"] and cands:
        rec = _try_complete_profiles(routing, out, text or json.dumps(cands, ensure_ascii=False), title)
        if rec:
            out = merge_profiles(out, rec)
            llm_ok = True
    out["characterCandidates"] = [
        local_complete_character(c) if isinstance(c, dict) else c for c in (out.get("characterCandidates") or [])
    ]
    out["spawnCandidates"] = list(out["characterCandidates"])
    # typicalPhrases sind evidenzgebunden (nur eigene Rede) — ohne ownSpeech kein Pflichtfeld.
    missing = {
        str(c.get("name")): [k for k in (*PROFILE_STR, *PROFILE_LIST) if _blank(c.get(k)) and not (k == "typicalPhrases" and not c.get("ownSpeech"))]
        for c in out["characterCandidates"]
        if isinstance(c, dict)
    }
    out["missingFields"] = missing
    out["complete"] = all(not v for v in missing.values())
    out["commitsTruth"] = False
    if llm_ok:
        return _llm_label(out, routing)
    return _local_label(out, routing, _LAST_LLM_ERROR if routing["allowed"] else None)


# ---------------------------------------------------------------------------
# V25.1 EPUB/Quellanalyse über den konfigurierten Provider (AMASTERv2 §11, Vertrag §7/§8)
# ---------------------------------------------------------------------------
ANALYSIS_CHUNK_CHARS = 12000
ANALYSIS_MAX_CHUNKS = 64
ANALYSIS_WORKERS = 4
# V32 Ganzbuch-Kontext: Figuren-/Beziehungskarte aus dem GESAMTEN Text in einem Aufruf
# (Ausgabe ist klein, Eingabe groß). Passt das Buch nicht in den Kontext, 2–4 Makroblöcke.
CAST_CONTEXT_CHARS = 240000
CAST_MAX_MACRO = 4
PROFILE_PASSAGE_CHARS = 12000


def _analysis_chunks(text: str, size: int = ANALYSIS_CHUNK_CHARS, max_chunks: int = ANALYSIS_MAX_CHUNKS) -> tuple[list[str], dict[str, Any]]:
    """Absatzweise Blöcke. Übersteigt der Text das Limit, werden Blöcke gleichmäßig
    ausgewählt und der Ausschlag sichtbar gemeldet (Vertrag §7.9: keine abgeschnittene
    Analyse als vollständiges Buch)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text or "") if p and p.strip()]
    chunks: list[str] = []
    cur = ""
    overlap = max(0, int(size * 0.15))  # V49: 15 % Überlappung gegen Kontextverlust an Blockgrenzen
    for para in paras:
        if len(cur) + len(para) + 2 > size and cur:
            chunks.append(cur)
            cur = (cur[-overlap:] + "\n\n" + para) if overlap and len(cur) > overlap else para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
        while len(cur) > size * 1.5:
            chunks.append(cur[:size])
            cur = cur[size:]
    if cur:
        chunks.append(cur)
    total = len(chunks)
    skipped = 0
    if total > max_chunks:
        step = total / max_chunks
        picked = [chunks[int(i * step)] for i in range(max_chunks)]
        skipped = total - len(picked)
        chunks = picked
    coverage = {
        "chars": len(text or ""),
        "analyzedChars": sum(len(c) for c in chunks),
        "chunksTotal": total,
        "chunksAnalyzed": len(chunks),
        "chunksSkipped": skipped,
        "complete": skipped == 0,
    }
    return chunks, coverage


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


_TITLE_RE = re.compile(r"^(?:dr\.?|prof\.?|mr\.?|mrs\.?|ms\.?|miss|herr|frau|sir|lady|lord|onkel|tante)\s+", re.I)


def _name_tokens(name: str) -> list[str]:
    base = _TITLE_RE.sub("", _norm_name(name))
    return [t for t in re.split(r"[\s\-]+", base) if t]


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = v.strip()
        return [v] if v else []
    if isinstance(v, dict):
        return [str(x).strip() for x in v.values() if str(x).strip()]
    return [str(x).strip() for x in v if str(x).strip()]


def _strip_quotes(v: str) -> str:
    return str(v or "").strip().strip("„“”\"»«‚‘’'").strip()


def _same_person(a: str, b: str) -> bool:
    """Namensvarianten derselben Figur: 'Emily' ~ 'Emily Just', 'Dr. Harris' ~ 'Dr. Raymond Harris',
    'Nathan Sterling' ~ 'Nathan'. Zwei verschiedene Vollnamen bleiben getrennt."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    if len(ta) == 1:
        return ta[0] in (tb[0], tb[-1]) and len(ta[0]) >= 3
    if len(tb) == 1:
        return tb[0] in (ta[0], ta[-1]) and len(tb[0]) >= 3
    return ta[0] == tb[0] and ta[-1] == tb[-1]


def _norm_ws(t: str) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip().lower()


def _quote_supported(quote: Any, text_low: str, min_words: int = 4) -> bool:
    """Belegprüfung (Vertrag §7.13/14): Zitat muss (normalisiert) im Text stehen."""
    q = _norm_ws(_strip_quotes(str(quote or "")))
    if len(q.split()) < min_words:
        return False
    return q in text_low or q[: max(30, int(len(q) * 0.8))] in text_low


def _evidenced(items: Any, text_low: str) -> list[dict[str, Any]]:
    """Liste von {text, quote} → nur belegte Einträge (Strings ohne quote werden verworfen)."""
    out: list[dict[str, Any]] = []
    if isinstance(items, dict):
        items = [items]
    for it in items or []:
        if isinstance(it, str):
            continue
        if not isinstance(it, dict):
            continue
        txt = str(it.get("text") or "").strip()
        if txt and _quote_supported(it.get("quote"), text_low):
            out.append({"text": txt[:200], "quote": _strip_quotes(str(it.get("quote")))[:220]})
    return out


def _merge_people(acc: dict[str, dict[str, Any]], people: Any, text_low: str) -> None:
    for p in people or []:
        if not isinstance(p, dict):
            continue
        name = _strip_quotes(str(p.get("name") or ""))
        if not name or len(name) < 2:
            continue
        aliases = [_strip_quotes(a) for a in _as_list(p.get("aliases"))]
        multi_aliases_in_text = [a for a in aliases if len(_name_tokens(a)) >= 2 and _norm_name(a) in text_low]
        full_in_text = _norm_name(name) in text_low
        if not full_in_text and multi_aliases_in_text:
            aliases = [name] + [a for a in aliases if a != multi_aliases_in_text[0]]
            name = multi_aliases_in_text[0]
            full_in_text = True
        # Vorhandene Figur suchen (Vollname, Alias, Namensvariante)
        key = None
        for k, row in acc.items():
            known = [row.get("name")] + list(row.get("aliases") or [])
            if any(_same_person(name, kn) for kn in known if kn) or any(_same_person(a, kn) for a in aliases for kn in known if kn and a):
                key = k
                break
        if key is None:
            if not full_in_text:
                # Halluzinationsschutz (Vertrag §7.13/14): kein Beleg im Text, keine bekannte Figur → verwerfen.
                continue
            key = _norm_name(name)
            acc[key] = {"name": name, "aliases": [], "role": "", "quotes": [], "traits": [], "goals": [], "fears": [], "secrets": [], "facts": [], "speech": [], "mentions": 0}
        row = acc[key]
        row["mentions"] += 1
        # Längster belegter Name (auch aus den Aliasen) wird kanonisch (Vertrag §7.14: identitätsstabil, Vollname)
        for cand_name in ([name] if full_in_text else []) + [a for a in aliases if _norm_name(a) in text_low]:
            if len(_name_tokens(cand_name)) > len(_name_tokens(row["name"])):
                if row["name"] not in row["aliases"]:
                    row["aliases"].append(row["name"])
                row["name"] = cand_name
        for a in ([name] if full_in_text else []) + [a for a in aliases if _norm_name(a) in text_low]:
            if a and a != row["name"] and a not in row["aliases"]:
                row["aliases"].append(a)
        if not row["role"] and p.get("role"):
            row["role"] = str(p.get("role"))[:80]
        q = _strip_quotes(str(p.get("quote") or ""))
        if q and q not in row["quotes"]:
            row["quotes"].append(q[:220])
        for fld in ("traits", "goals", "fears", "secrets"):
            for v in _as_list(p.get(fld)):
                v = v[:200]
                if v and v not in row[fld]:
                    row[fld].append(v)
        # facts: nur mit Zitatbeleg aus dem Block (Halluzinationsschutz für Fakten wie "ist der Vater")
        for it in _evidenced(p.get("facts"), text_low):
            if it["text"] not in row["facts"]:
                row["facts"].append(it["text"])
                row.setdefault("factQuotes", []).append(it["quote"])
        for v in _as_list(p.get("speech")):
            v = _strip_quotes(v)[:200]
            if v and v not in row["speech"] and _quote_supported(v, text_low, min_words=2):
                row["speech"].append(v)


def _uniq(items: Any, cap: int = 24) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for it in items or []:
        key = json.dumps(it, ensure_ascii=False, sort_keys=True).lower() if isinstance(it, dict) else str(it).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
        if len(out) >= cap:
            break
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")[:24] or "x"


def _strs(items: Any, cap: int = 24) -> list[str]:
    out: list[str] = []
    for it in items or []:
        if isinstance(it, dict):
            it = it.get("text") or it.get("name") or it.get("beat") or ""
        t = str(it or "").strip()
        if t and t not in out:
            out.append(t[:240])
        if len(out) >= cap:
            break
    return out


def _normalize_llm_world(base: dict[str, Any], llm: dict[str, Any]) -> dict[str, Any]:
    """LLM-Weltentwurf in die Datenformen des lokalen Analyzers/Frontends bringen
    (places/factions/timeline/rules als Objekte mit id, startScenes/fateBeats als Strings,
    fateSeeds/startSituations als Objekte). Belegte lokale Werte bleiben, wenn das LLM nichts liefert."""
    w = dict(base or {})
    for k in ("name", "short", "long", "genre", "tone", "epoch", "geography", "atmosphere", "purpose"):
        if llm.get(k):
            w[k] = str(llm[k])[:1200 if k == "long" else 240]
    places = []
    for i, p in enumerate(llm.get("places") or []):
        if isinstance(p, str):
            p = {"name": p}
        if not isinstance(p, dict) or not p.get("name"):
            continue
        places.append({"id": f"pl_{i}_{_slug(p['name'])}", "name": str(p["name"])[:80], "description": str(p.get("description") or "")[:240],
                       "connections": [str(x) for x in (p.get("connections") or [])][:6], "rules": _strs(p.get("rules"), 6), "tags": ["llm"]})
    if places:
        w["places"] = places
    subs = []
    for i, p in enumerate(llm.get("subplaces") or []):
        if isinstance(p, str):
            p = {"name": p}
        if isinstance(p, dict) and p.get("name"):
            subs.append({"id": f"sub_{i}_{_slug(p['name'])}", "name": str(p["name"])[:80], "description": str(p.get("description") or "")[:200], "parentName": str(p.get("parent") or p.get("parentName") or "")[:80]})
    if subs:
        w["subplaces"] = subs
    facs = []
    for i, f in enumerate(llm.get("factions") or []):
        if isinstance(f, str):
            f = {"name": f}
        if isinstance(f, dict) and f.get("name"):
            facs.append({"id": f"fac_{_slug(f['name'])}", "name": str(f["name"])[:80], "description": str(f.get("description") or "")[:200], "members": [str(m) for m in (f.get("members") or [])][:12]})
    if facs:
        w["factions"] = facs
    rules = []
    for kind, key in (("physisch", "physicalRules"), ("sozial", "socialRules"), ("haus", "rules")):
        for t in _strs(llm.get(key), 12):
            rules.append({"id": f"rule_{len(rules) + 1}", "kind": kind, "text": t})
    if rules:
        w["rules"] = rules
    tl = []
    for i, ev in enumerate(llm.get("timeline") or []):
        if isinstance(ev, str):
            ev = {"text": ev}
        if isinstance(ev, dict) and ev.get("text"):
            tl.append({"id": f"tl_{i}", "text": str(ev["text"])[:240], "when": str(ev.get("when") or "")[:60], "actors": [str(a) for a in (ev.get("actors") or [])][:6]})
    if tl:
        w["timeline"] = tl
    for key in ("conflicts", "history", "items", "beings", "culture", "language", "worldKnowledge", "secretKnowledge", "knowledgeBounds", "storyGoals"):
        vals = _strs(llm.get(key), 30)
        if vals:
            w[key] = vals
    if w.get("secretKnowledge"):
        w["secrets"] = w["secretKnowledge"]
    if w.get("knowledgeBounds"):
        w["knowledgeLimits"] = w["knowledgeBounds"]
    if w.get("storyGoals"):
        w["worldGoals"] = w["storyGoals"]
    scenes = [sc if isinstance(sc, dict) else {"opening": str(sc)} for sc in (llm.get("startScenes") or []) if sc]
    if scenes:
        w["startScenes"] = [str(sc.get("opening") or sc.get("placeName") or "")[:240] for sc in scenes if (sc.get("opening") or sc.get("placeName"))][:6]
        w["typicalScenes"] = list(w["startScenes"])
        sits = []
        for i, sc in enumerate(scenes[:6]):
            pname = str(sc.get("placeName") or "")
            pid = next((p["id"] for p in (w.get("places") or []) if isinstance(p, dict) and str(p.get("name") or "").lower() == pname.lower()), "")
            sits.append({"id": f"start_{i + 1}", "title": str(sc.get("title") or pname or f"Startlage {i + 1}")[:60], "placeId": pid, "time": str(sc.get("time") or "jetzt")[:40],
                         "presentNames": [str(n) for n in (sc.get("presentNames") or [])][:8], "opening": str(sc.get("opening") or "")[:400]})
        w["startSituations"] = sits
    beats = [b if isinstance(b, dict) else {"beat": str(b)} for b in (llm.get("fateBeats") or []) if b]
    if beats:
        w["fateBeats"] = [str(b.get("beat") or "")[:240] for b in beats if b.get("beat")][:6]
        w["fateSeeds"] = [{"id": f"seed_{i + 1}", "title": str(b.get("beat") or "")[:48], "pressure": str(b.get("pressure") or b.get("beat") or "")[:160], "tags": [], "beat": str(b.get("beat") or "")[:240],
                           "mustNot": str(b.get("mustNot") or "Kein erfundenes Wissen. Abwesende wissen nichts. Avatar nicht steuern.")[:240]} for i, b in enumerate(beats[:5]) if b.get("beat")]
    w.setdefault("fateEnabled", True)
    return w


CAST_RULES = (
    "Du liest den GESAMTEN Text einer Quelle (Roman/Dokument) und erstellst die Figuren- und Beziehungskarte "
    "für ein zustandsbasiertes Figuren-Universum (AMASTERv2 §11/§13/§14). Antwort NUR JSON: "
    '{"people": [{"name", "aliases": [], "role", "gender": "männlich|weiblich|divers|", "summary", '
    '"relations": [{"to", "kind", "note", "trust", "closeness", "fear", "quote"}], "keyFacts": [{"text", "quote"}]}], '
    '"keyEvents": [{"text", "actors": [], "quote"}], "narrator": string|null, '
    '"meta": {"textsorte": "Roman|Erzählung|Drehbuch|Sachtext|Chronik|Brief|Sonstiges", "genre", "epoche", "erzaehlperspektive": "Ich|Er/Sie|Wechselnd", "sprachstil"}}. '
    "name = vollständigster im Text vorkommender Name; Namensvarianten als aliases derselben Figur (Emily/Emily Just = EINE Figur). "
    "Nur Menschen/Wesen der Handlung (keine Autorin, keine Werbung, kein Impressum, keine anderen Bücher). "
    "summary = 2–4 Sätze über Rolle, Vergangenheit und Bedeutung im GANZEN Text (Rückblenden, Träume, Vorgeschichte einbeziehen). "
    "relations: Beziehungsart NUR wie der Text sie ausdrücklich nennt (Ehefrau, Ex-Freund, Chef, Vater …); belastete Vergangenheit "
    "(Trauma, Schuld, Verrat, Tod) MUSS als Beziehung mit hohem fear/niedrigem trust und der Ursache in note erscheinen; "
    "trust/closeness/fear 0..1 aus den Szenen. BELEGPFLICHT: jede relation und jeder keyFact trägt quote = wörtliches "
    "Satzstück (≥ 6 Wörter) aus dem Text; ohne Beleg weglassen. Deutsch, knapp."
)



# ---------------------------------------------------------------------------
# V49 Universeller Extraktor: Facetten mit eigenem Schema und Belegpflicht (Nutzeridee Extraktor Nr. 1–4, 8)
# ---------------------------------------------------------------------------
FACET_SPECS: dict[str, dict[str, Any]] = {
    "places": {
        "rules": (
            "Extrahiere ORTE & GEOGRAFIE aus dem Text (Hierarchie: Land/Region/Stadt/Gebäude/Raum; Wege zwischen Orten). Antwort NUR JSON: "
            '{"places": [{"name", "kind": "Land|Region|Stadt|Dorf|Gebäude|Raum|Landschaft|Sonstiges", "parent": string|null, "description", "quote"}], '
            '"paths": [{"from", "to", "how", "quote"}]}. Nur Orte, an denen Handlung spielt oder die genannt werden; keine Metaphern. '
            "quote = wörtliches Satzstück (≥ 6 Wörter). Ohne Beleg: weglassen. Deutsch, knapp."
        ),
        "keys": ("places", "paths"),
    },
    "rules": {
        "rules": (
            "Extrahiere REGELN & GESELLSCHAFTSORDNUNG (physisch, sozial, rechtlich, religiös, magisch), die in dieser Welt gelten — mit Geltungsbereich und Sanktion. Antwort NUR JSON: "
            '{"rules": [{"rule", "scope": "physisch|sozial|rechtlich|religioes|magisch|wirtschaftlich", "sanction": string|null, "quote"}], '
            '"socialOrder": [{"group", "position", "quote"}]}. Nur Regeln, die der Text ausdrücklich zeigt oder nennt; keine Allgemeinplätze. '
            "quote = wörtliches Satzstück (≥ 6 Wörter). Ohne Beleg: weglassen. Deutsch, knapp."
        ),
        "keys": ("rules", "socialOrder"),
    },
    "timeline": {
        "rules": (
            "Extrahiere die ZEITLINIE: Schlüsselereignisse in Handlungsreihenfolge, inklusive Vorgeschichte (Rückblenden), mit Akteuren und Ort. Antwort NUR JSON: "
            '{"timeline": [{"order": int, "event", "actors": [], "place": string|null, "when": string|null, "kind": "vorgeschichte|handlung|ausblick", "quote"}]}. '
            "quote = wörtliches Satzstück (≥ 6 Wörter). Ohne Beleg: weglassen. 8–30 Ereignisse. Deutsch, knapp."
        ),
        "keys": ("timeline",),
    },
    "conflicts": {
        "rules": (
            "Extrahiere KONFLIKTE & STORY-ZIELE: wer gegen wen/was, worum es geht, was auf dem Spiel steht, Stand; und die Ziele der Figuren. Antwort NUR JSON: "
            '{"conflicts": [{"parties": [], "subject", "stakes", "status": "offen|eskaliert|gelöst|latent", "quote"}], '
            '"storyGoals": [{"who", "goal", "why": string|null, "quote"}]}. Nur belegte Konflikte/Ziele; keine erfundenen. '
            "quote = wörtliches Satzstück (≥ 6 Wörter). Ohne Beleg: weglassen. Deutsch, knapp."
        ),
        "keys": ("conflicts", "storyGoals"),
    },
    "secrets": {
        "rules": (
            "Extrahiere GEHEIMNISSE & WISSENSGRENZEN: was verborgen ist, wer es weiß, wer es nicht weiß; und was einzelne Figuren ausdrücklich NICHT wissen. Antwort NUR JSON: "
            '{"secrets": [{"secret", "knownBy": [], "hiddenFrom": [], "quote"}], "knowledgeLimits": [{"who", "doesNotKnow", "quote"}]}. '
            "quote = wörtliches Satzstück (≥ 6 Wörter). Ohne Beleg: weglassen. Deutsch, knapp."
        ),
        "keys": ("secrets", "knowledgeLimits"),
    },
    "culture": {
        "rules": (
            "Extrahiere KULTUR, HISTORIE, GEGENSTÄNDE, GRUPPEN: Sitten/Alltag, geschichtlicher Hintergrund, bedeutsame Gegenstände (Bedeutung, Besitzer), Fraktionen/Gruppen mit Mitgliedern, Sprache/Anrede. Antwort NUR JSON: "
            '{"culture": [{"text", "quote"}], "history": [{"text", "quote"}], "items": [{"name", "meaning", "owner": string|null, "quote"}], '
            '"factions": [{"name", "description", "members": [], "quote"}], "language": [{"text", "quote"}]}. '
            "quote = wörtliches Satzstück (≥ 6 Wörter). Ohne Beleg: weglassen. Deutsch, knapp."
        ),
        "keys": ("culture", "history", "items", "factions", "language"),
    },
}

_TEXTSORTE_HINT = {
    "sachtext": "Textsorte SACHTEXT: Fokus auf Regeln, Fakten, Hierarchien, Prozesse, Definitionen; Figuren sind Akteure/Rollen.",
    "drehbuch": "Textsorte DREHBUCH: Fokus auf Szenen, Dialoge, Regieanweisungen; Orte aus Szenenköpfen, Zeitlinie aus Szenenfolge.",
    "chronik": "Textsorte CHRONIK: Fokus auf Zeitlinie, Ereignisse mit Datum, Orte, Gruppen.",
    "brief": "Textsorte BRIEF: Fokus auf Absender/Empfänger, Beziehungen, Geheimnisse, Wissensgrenzen.",
}


def _facet_hint(meta: dict[str, Any] | None) -> str:
    ts = str((meta or {}).get("textsorte") or "").lower()
    for k, v in _TEXTSORTE_HINT.items():
        if k in ts:
            return v
    return "Textsorte ROMAN/ERZÄHLUNG: Fokus auf Figuren, Beziehungen, Konflikte, Handlungsbögen, Geheimnisse."


def _norm_cmp(t: Any) -> str:
    """Vergleichsform für Belegprüfung: Kleinbuchstaben, ohne Anführungs-/Satzzeichen, ein Leerzeichen."""
    x = str(t or "").lower()
    x = re.sub(r"[„“”\"'»«‹›`´’‘,.;:!?()\[\]{}—–\-]", " ", x)
    return re.sub(r"\s+", " ", x).strip()


def _quote_in_text(quote: str, text_cmp: str, min_words: int = 5) -> bool:
    q = _norm_cmp(quote)
    if len(q.split()) < min_words:
        return False
    return q in text_cmp or q[: max(30, int(len(q) * 0.8))] in text_cmp


def _facet_norm_item(item: Any, text_norm: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    out = {k: (v if isinstance(v, (list, int, float)) else str(v or "").strip()) for k, v in item.items() if k in ("name", "kind", "parent", "description", "from", "to", "how", "rule", "scope", "sanction", "group", "position", "order", "event", "actors", "place", "when", "parties", "subject", "stakes", "status", "who", "goal", "why", "secret", "knownBy", "hiddenFrom", "doesNotKnow", "text", "meaning", "owner", "members")}
    q = _strip_quotes(str(item.get("quote") or ""))[:240]
    out["quote"] = q
    out["provenance"] = "belegt" if (q and _quote_in_text(q, text_norm)) else "unsicher"
    return out


def _facet_key(facet: str, key: str, item: dict[str, Any]) -> str:
    for f in ("name", "rule", "event", "subject", "secret", "text", "goal", "doesNotKnow", "group"):
        if item.get(f):
            return f"{key}:{str(item[f]).strip().lower()[:80]}"
    return f"{key}:{json.dumps(item, ensure_ascii=False, sort_keys=True)[:120]}"


def _extract_facets(routing: dict[str, Any], text: str, title: str, cfg: dict[str, Any], meta: dict[str, Any] | None) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Alle Facetten parallel über die Makroblöcke (Ganzbuch-Kontext); Ergebnisse je Facette
    zusammengeführt (Dubletten nach Schlüssel), Belegpflicht: quote muss im Text stehen, sonst 'unsicher'."""
    ctx_chars = int(cfg.get("analysisContextChars") or CAST_CONTEXT_CHARS)
    parts = _macro_chunks(text, size=ctx_chars)
    text_norm = _norm_cmp(text)
    hint = _facet_hint(meta)
    results: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    seen: dict[str, set[str]] = {}
    jobs = [(facet, i, part) for facet in FACET_SPECS for i, part in enumerate(parts)]

    def _run(job):
        facet, i, part = job
        spec = FACET_SPECS[facet]
        payload = {"title": title, "part": i + 1, "of": len(parts), "hinweis": hint, "text": part}
        parsed = _llm_json(routing, spec["rules"] + " " + hint, payload, temperature=0.1, max_tokens=3500, timeout=300, max_input_chars=ctx_chars + 4000)
        return facet, i, parsed, _last_llm_error()

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as ex:
        for facet, i, parsed, err in ex.map(_run, jobs):
            if not parsed:
                errors.append(f"facette {facet} {i + 1}/{len(parts)}: {err}")
                continue
            for key in FACET_SPECS[facet]["keys"]:
                rows = parsed.get(key) or []
                if not isinstance(rows, list):
                    continue
                bucket = results.setdefault(key, [])
                keys = seen.setdefault(key, set())
                for raw in rows[:60]:
                    item = _facet_norm_item(raw, text_norm)
                    if not item:
                        continue
                    if key in ("rules", "conflicts", "secrets", "storyGoals", "knowledgeLimits") and item.get("provenance") != "belegt":
                        continue  # Belegpflicht (Vertrag §8, V31)
                    k = _facet_key(facet, key, item)
                    if k in keys:
                        continue
                    keys.add(k)
                    bucket.append(item)
    if results.get("timeline"):
        results["timeline"].sort(key=lambda r: (int(r.get("order") or 0) if str(r.get("order") or "").lstrip("-").isdigit() else 999))
    return results, errors


def _facets_into_world(world: dict[str, Any], facets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Facetten sind für ihre Felder maßgeblich (ersetzen lokale Rohsatz-Listen); Legacy-Felder bleiben
    Strings/Dicts wie die UI sie kennt, Details liegen daneben (*Detail)."""
    prov = world.setdefault("worldProvenance", {}) if isinstance(world.get("worldProvenance"), dict) else {}
    world["worldProvenance"] = prov

    def _label(item: dict[str, Any], main: str, extra: str | None = None) -> str:
        base = str(item.get(main) or "").strip()
        if extra and item.get(extra):
            base = f"{base} — {str(item.get(extra)).strip()}"
        return base + (" (unsicher)" if item.get("provenance") == "unsicher" else "")

    if facets.get("places"):
        existing = {str(p.get("name") or "").lower(): p for p in (world.get("places") or []) if isinstance(p, dict)}
        merged = []
        for it in facets["places"]:
            nm = str(it.get("name") or "").strip()
            if not nm:
                continue
            old = existing.pop(nm.lower(), None) or {}
            merged.append({**old, "name": nm, "kind": it.get("kind") or old.get("kind") or "", "parent": it.get("parent") or old.get("parent") or None, "description": it.get("description") or old.get("description") or "", "rules": old.get("rules") or [], "provenance": it.get("provenance")})
        world["places"] = merged[:40]
        world["subplaces"] = [p["name"] for p in merged if p.get("parent")][:40]
        world["placeRelations"] = [{"from": x.get("from"), "to": x.get("to"), "how": x.get("how"), "provenance": x.get("provenance")} for x in (facets.get("paths") or [])][:40]
        prov["places"] = "belegt"
    if facets.get("rules"):
        world["rules"] = [_label(r, "rule", "sanction") for r in facets["rules"]][:40]
        world["physicalRules"] = [_label(r, "rule") for r in facets["rules"] if str(r.get("scope") or "").startswith("phys")][:20]
        world["socialRules"] = [_label(r, "rule") for r in facets["rules"] if str(r.get("scope") or "") in ("sozial", "rechtlich", "religioes", "wirtschaftlich")][:20]
        world["rulesDetail"] = facets["rules"][:40]
        prov["rules"] = "belegt"
    if facets.get("socialOrder"):
        world["socialOrder"] = facets["socialOrder"][:30]
    if facets.get("timeline"):
        world["timeline"] = [{"text": _label(t, "event"), "actors": list(t.get("actors") or []), "place": t.get("place"), "when": t.get("when"), "kind": t.get("kind"), "provenance": t.get("provenance")} for t in facets["timeline"]][:60]
        prov["timeline"] = "belegt"
    if facets.get("conflicts"):
        world["conflicts"] = [f"{', '.join(str(x) for x in (c.get('parties') or []))}: {c.get('subject')}" + (f" — {c.get('stakes')}" if c.get("stakes") else "") + (f" [{c.get('status')}]" if c.get("status") else "") for c in facets["conflicts"]][:40]
        world["conflictsDetail"] = facets["conflicts"][:40]
        prov["conflicts"] = "belegt"
    if facets.get("storyGoals"):
        world["storyGoals"] = [f"{g.get('who')}: {g.get('goal')}" + (f" ({g.get('why')})" if g.get("why") else "") for g in facets["storyGoals"]][:40]
        world["worldGoals"] = list(world["storyGoals"])
        prov["storyGoals"] = "belegt"
    if facets.get("secrets"):
        world["secrets"] = [f"{s_.get('secret')} (wissen: {', '.join(s_.get('knownBy') or []) or '—'}; verborgen vor: {', '.join(s_.get('hiddenFrom') or []) or '—'})" for s_ in facets["secrets"]][:40]
        world["secretKnowledge"] = list(world["secrets"])
        world["secretsDetail"] = facets["secrets"][:40]
        prov["secrets"] = "belegt"
    if facets.get("knowledgeLimits"):
        world["knowledgeLimits"] = [f"{k.get('who')} weiß nicht: {k.get('doesNotKnow')}" for k in facets["knowledgeLimits"]][:40]
        world["knowledgeBounds"] = list(world["knowledgeLimits"])
        prov["knowledgeLimits"] = "belegt"
    for key in ("culture", "history", "language"):
        if facets.get(key):
            world[key] = [_label(x, "text") for x in facets[key]][:30]
            prov[key] = "belegt"
    if facets.get("items"):
        world["items"] = [f"{i.get('name')}: {i.get('meaning')}" + (f" (Besitz: {i.get('owner')})" if i.get("owner") else "") for i in facets["items"]][:30]
        world["itemsDetail"] = facets["items"][:30]
        prov["items"] = "belegt"
    if facets.get("factions"):
        world["factions"] = [{"name": f.get("name"), "description": f.get("description"), "members": list(f.get("members") or []), "provenance": f.get("provenance")} for f in facets["factions"]][:20]
        prov["factions"] = "belegt"
    return world

def _macro_chunks(text: str, size: int = CAST_CONTEXT_CHARS, max_parts: int = CAST_MAX_MACRO) -> list[str]:
    if len(text) <= size:
        return [text]
    parts, _cov = _analysis_chunks(text, size=size, max_chunks=max_parts)
    return parts


def _cast_map(routing: dict[str, Any], text: str, title: str, cfg: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """V32: Ganzbuch-Lesung → kompakte Karte (Figuren, Aliase, Beziehungen mit Beleg, Schlüsselereignisse).
    Eingabe = ganzer Text (bzw. wenige Makroblöcke), Ausgabe klein → kein Abschneiden."""
    try:
        ctx_chars = max(60000, int(cfg.get("analysisContextChars") or CAST_CONTEXT_CHARS))
    except (TypeError, ValueError):
        ctx_chars = CAST_CONTEXT_CHARS
    parts = _macro_chunks(text, size=ctx_chars)
    text_low = text.lower()
    people: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    narrator = ""
    errors: list[str] = []
    for i, part in enumerate(parts):
        payload = {"title": title, "part": i + 1, "of": len(parts), "text": part}
        parsed = _llm_json(routing, CAST_RULES, payload, temperature=0.1, max_tokens=6000, timeout=300, max_input_chars=ctx_chars + 4000)
        if not parsed:
            errors.append(f"cast {i + 1}/{len(parts)}: {_last_llm_error()}")
            continue
        for p in parsed.get("people") or []:
            if not isinstance(p, dict) or not p.get("name"):
                continue
            name = _strip_quotes(str(p.get("name")))
            aliases = [_strip_quotes(a) for a in _as_list(p.get("aliases"))]
            if _norm_name(name) not in text_low and not any(_norm_name(a) in text_low for a in aliases if len(_name_tokens(a)) >= 2):
                continue
            key = None
            for k, row in people.items():
                known = [row["name"]] + row["aliases"]
                if any(_same_person(name, kn) for kn in known) or any(_same_person(a, kn) for a in aliases for kn in known if a):
                    key = k
                    break
            if key is None:
                key = _norm_name(name)
                people[key] = {"name": name, "aliases": [], "role": "", "gender": "", "summary": "", "relations": [], "keyFacts": []}
            row = people[key]
            for cand_name in [name] + [a for a in aliases if _norm_name(a) in text_low]:
                if len(_name_tokens(cand_name)) > len(_name_tokens(row["name"])):
                    if row["name"] not in row["aliases"]:
                        row["aliases"].append(row["name"])
                    row["name"] = cand_name
            for a in [name] + aliases:
                if a and a != row["name"] and a not in row["aliases"] and _norm_name(a) in text_low:
                    row["aliases"].append(a)
            if not row["role"] and p.get("role"):
                row["role"] = str(p.get("role"))[:80]
            g = str(p.get("gender") or "").strip().lower()
            if g and not row["gender"]:
                row["gender"] = _GENDER_MAP.get(g, "")
            if p.get("summary") and len(str(p.get("summary"))) > len(row["summary"]):
                row["summary"] = str(p.get("summary"))[:700]
            for r in p.get("relations") or []:
                if isinstance(r, dict) and r.get("to") and _quote_supported(r.get("quote"), text_low):
                    rr = {"to": str(r["to"])[:80], "kind": str(r.get("kind") or "kennt")[:40], "note": str(r.get("note") or "")[:200], "quote": _strip_quotes(str(r.get("quote")))[:220]}
                    for k, d in (("trust", 0.5), ("closeness", 0.4), ("fear", 0.1)):
                        try:
                            rr[k] = max(0.0, min(1.0, float(r.get(k) if r.get(k) is not None else d)))
                        except (TypeError, ValueError):
                            rr[k] = d
                    if not any(_norm_name(x["to"]) == _norm_name(rr["to"]) for x in row["relations"]):
                        row["relations"].append(rr)
            for f in _evidenced(p.get("keyFacts"), text_low):
                if f["text"] not in [x["text"] for x in row["keyFacts"]]:
                    row["keyFacts"].append(f)
        for ev in parsed.get("events") or parsed.get("keyEvents") or []:
            if isinstance(ev, dict) and ev.get("text") and _quote_supported(ev.get("quote"), text_low, min_words=3):
                events.append({"text": str(ev["text"])[:240], "actors": [str(a) for a in (ev.get("actors") or [])][:6], "quote": _strip_quotes(str(ev.get("quote")))[:200]})
        if not narrator and parsed.get("narrator"):
            narrator = str(parsed["narrator"])[:80]
        if isinstance(parsed.get("meta"), dict) and not meta:
            meta = {k: str(v)[:80] for k, v in parsed["meta"].items() if isinstance(v, (str, int, float)) and str(v).strip()}
    # Beziehungsziele auf Kartennamen normalisieren
    names = {_norm_name(r["name"]): r["name"] for r in people.values()}
    for row in people.values():
        for a in row["aliases"]:
            names.setdefault(_norm_name(a), row["name"])
    for row in people.values():
        for r in row["relations"]:
            for kn, full in names.items():
                if _same_person(r["to"], kn):
                    r["to"] = full
                    break
    return {"people": list(people.values()), "events": events[:60], "narrator": narrator, "parts": len(parts), "contextChars": ctx_chars, "meta": meta}, errors


def _passages_for(text: str, names: list[str], limit: int = PROFILE_PASSAGE_CHARS, width: int = 300) -> list[str]:
    """Alle Textstellen, in denen die Figur (Name/Alias) vorkommt — Evidenz für das Profil,
    nicht nur 8 Zitate. Bis limit Zeichen, gleichmäßig über das Buch verteilt."""
    low = text.lower()
    hits: list[int] = []
    for n in names:
        n = _norm_name(n)
        if len(n) < 3:
            continue
        start = 0
        while True:
            j = low.find(n, start)
            if j < 0:
                break
            hits.append(j)
            start = j + len(n)
    if not hits:
        return []
    hits = sorted(set(hits))
    out: list[str] = []
    total = 0
    step = max(1, len(hits) // max(1, limit // (2 * width)))
    last_end = -1
    for j in hits[::step]:
        a, b = max(0, j - width), min(len(text), j + width)
        if a <= last_end:
            continue
        seg = " ".join(text[a:b].split())
        out.append(seg)
        last_end = b
        total += len(seg)
        if total >= limit:
            break
    return out


def _reciprocal_relations(cands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """AMASTERv2 §44 (gerichtet, aber beidseitig vorhanden): Nennt A eine Beziehung zu B und
    B keine zu A, entsteht die Gegenrichtung mit gespiegelten Werten, Provenienz 'abgeleitet'."""
    by = {str(c.get("name") or "").strip().lower(): c for c in cands if isinstance(c, dict) and c.get("name")}
    for c in cands:
        if not isinstance(c, dict):
            continue
        for r in c.get("relations") or []:
            if not isinstance(r, dict):
                continue
            tgt = by.get(str(r.get("targetName") or r.get("to") or "").strip().lower())
            if not tgt or tgt is c:
                continue
            existing = [x for x in (tgt.get("relations") or []) if isinstance(x, dict) and str(x.get("targetName") or x.get("to") or "").strip().lower() == str(c.get("name")).strip().lower()]
            if existing:
                continue
            tgt.setdefault("relations", []).append({
                "targetName": c.get("name"),
                "kind": str(r.get("kind") or "kennt"),
                "trust": r.get("trust", 0.5),
                "closeness": r.get("closeness", 0.4),
                "fear": r.get("fear", 0.1),
                "note": f"Gegenrichtung zu: {str(r.get('note') or r.get('kind') or '')[:120]}",
            })
            prov = dict(tgt.get("fieldProvenance") or {})
            prov.setdefault("relations", "abgeleitet")
            tgt["fieldProvenance"] = prov
    return cands


def analyze_with_llm(conn, actor: str, text: str, title: str, analysis: dict[str, Any], data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Quellanalyse (EPUB/Text) über den konfigurierten Provider: blockweise Extraktion
    (Figuren, Orte, Ereignisse, Konflikte, Regeln, Beziehungen), Weltsynthese, dann
    vollständige Stammprofile mit Provenienz. Ohne Provider: lokaler Entwurf, ehrlich
    markiert. Nichts wird committed."""
    data = data or {}
    out = dict(analysis or {})
    out.setdefault("ok", True)
    out["commitsTruth"] = False
    cfg = _cfg(conn, actor, data)
    routing = _routing(data, cfg)
    if not text.strip():
        return out
    if not routing["allowed"]:
        out["analysisSource"] = "local"
        out["recognize"] = "local"
        out["profileSource"] = "local-fallback"
        out["llmError"] = "LLM_REQUIRED" if not routing["apiKey"] else "LLM_DISABLED"
        out["message"] = "Analyse lief ohne LLM (kein Provider/API-Key konfiguriert): Figuren und Welt sind ein lokaler Entwurf, keine vollständige Analyse."
        return out
    chunks, coverage = _analysis_chunks(text)
    text_low = text.lower()
    # V32 Stufe 0: Ganzbuch-Karte (Figuren, Aliase, Beziehungen mit Beleg, Schlüsselereignisse)
    cast, cast_errors = _cast_map(routing, text, title, cfg)
    people: dict[str, dict[str, Any]] = {}
    for cp in cast.get("people") or []:
        key = _norm_name(cp["name"])
        people[key] = {"name": cp["name"], "aliases": list(cp.get("aliases") or []), "role": cp.get("role") or "", "quotes": [], "traits": [], "goals": [], "fears": [], "secrets": [],
                       "facts": [f["text"] for f in (cp.get("keyFacts") or [])], "factQuotes": [f["quote"] for f in (cp.get("keyFacts") or [])], "speech": [], "mentions": 1,
                       "castSummary": cp.get("summary") or "", "castGender": cp.get("gender") or "", "castRelations": list(cp.get("relations") or [])}
    places: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    conflicts: list[str] = []
    rules: list[str] = []
    items: list[str] = []
    secrets: list[str] = []
    relations: list[dict[str, Any]] = []
    narrator = ""
    errors: list[str] = []
    system_extract = (
        "Du extrahierst NUR, was in diesem Textausschnitt einer Quelle (Roman/Dokument) steht, "
        "für ein zustandsbasiertes Figuren-Universum. Antwort NUR JSON: "
        '{"people": [{"name", "aliases": [], "role", "quote", "facts": [{"text", "quote"}], "speech": [], "traits": [], "goals": [], "fears": [], "secrets": []}], '
        '"places": [{"name", "description"}], "events": [{"text", "actors": []}], "conflicts": [{"text", "quote"}], "rules": [], '
        '"items": [], "secrets": [], "relations": [{"from", "to", "kind", "note", "quote"}], "narrator": string|null}. '
        "Nur Menschen/Wesen der Handlung als people (keine Autorin, keine Werbung, kein Impressum, keine anderen Bücher). "
        "name = vollständigster im Text vorkommender Name; Ich-Erzähler unter seinem Namen, wenn bekannt, sonst narrator setzen. "
        "BELEGPFLICHT: jedes fact und jede relation trägt quote = wörtliches Satzstück (≥ 6 Wörter) aus GENAU diesem Ausschnitt, das die Aussage belegt; "
        "ohne Beleg im Ausschnitt keine Angabe (lieber weglassen als raten). Verwandtschaft/Beziehungsart (Vater, Ex-Freund, Chef) nur, wenn der Ausschnitt sie ausdrücklich nennt. "
        "facts.text = paraphrasierte Fakten ÜBER die Figur (kein Wortlaut). conflicts.text = Konflikt in eigenen Worten (kein Romansatz). "
        "speech = wörtliche direkte Rede, die DIESE Figur selbst spricht (Sprecher eindeutig); Rede anderer über sie oder Tagebücher anderer NICHT. "
        "Deutsch, knapp."
    )
    try:
        workers = max(1, int(cfg.get("analysisWorkers") or ANALYSIS_WORKERS))
    except (TypeError, ValueError):
        workers = ANALYSIS_WORKERS

    def _extract(i_chunk: tuple[int, str]) -> tuple[int, dict[str, Any] | None, str | None]:
        i, chunk = i_chunk
        parsed = _llm_json(routing, system_extract, {"title": title, "part": i + 1, "of": len(chunks), "text": chunk}, temperature=0.1, max_tokens=2200, timeout=180)
        return i, parsed, (None if parsed else str(_last_llm_error()))

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(chunks)))) as pool:
        results = sorted(pool.map(_extract, list(enumerate(chunks))), key=lambda r: r[0])
    chunk_low_by_index = {i: chunk.lower() for i, chunk in enumerate(chunks)}
    for i, parsed, err in results:
        if not parsed:
            errors.append(f"chunk {i + 1}: {err}")
            continue
        _merge_people(people, parsed.get("people"), chunk_low_by_index.get(i, text_low))
        for pl in parsed.get("places") or []:
            if isinstance(pl, dict) and pl.get("name"):
                places.append({"name": str(pl["name"])[:80], "description": str(pl.get("description") or "")[:240]})
        for ev in parsed.get("events") or []:
            if isinstance(ev, dict) and ev.get("text"):
                events.append({"text": str(ev["text"])[:240], "actors": [str(a) for a in (ev.get("actors") or [])][:6]})
        conflicts.extend(it["text"] for it in _evidenced(parsed.get("conflicts"), chunk_low_by_index.get(i, text_low)))
        rules.extend(str(x)[:200] for x in (parsed.get("rules") or []) if x)
        items.extend(str(x)[:120] for x in (parsed.get("items") or []) if x)
        secrets.extend(str(x)[:200] for x in (parsed.get("secrets") or []) if x)
        for rel in parsed.get("relations") or []:
            if isinstance(rel, dict) and rel.get("from") and rel.get("to") and _quote_supported(rel.get("quote"), chunk_low_by_index.get(i, text_low)):
                relations.append({"from": str(rel["from"])[:80], "to": str(rel["to"])[:80], "kind": str(rel.get("kind") or "kennt")[:40], "note": str(rel.get("note") or "")[:160], "quote": _strip_quotes(str(rel.get("quote")))[:220]})
        if not narrator and parsed.get("narrator"):
            narrator = str(parsed["narrator"])[:80]
    errors = cast_errors + errors
    if not people and errors:
        out["analysisSource"] = "local"
        out["recognize"] = "local"
        out["profileSource"] = "local-fallback"
        out["llmError"] = errors[0]
        out["message"] = f"LLM-Analyse fehlgeschlagen ({errors[0]}). Ergebnis ist ein lokaler Entwurf."
        out["coverage"] = coverage
        return out
    # Kandidaten aus der Extraktion (Evidenz je Figur)
    ranked = sorted(people.values(), key=lambda r: (-int(r.get("mentions") or 0), r.get("name") or ""))
    cands: list[dict[str, Any]] = []
    for row in ranked[:24]:
        # V26 (V1 §1/§4/§5): Zitate sind Evidenz, nicht Biografie/Wissen; eigene Rede getrennt.
        speech = [q for q in row.get("speech") or [] if q][:10]
        cast_rels = [{"targetName": r["to"], "kind": r["kind"], "note": r["note"], "trust": r["trust"], "closeness": r["closeness"], "fear": r["fear"], "quote": r.get("quote")} for r in (row.get("castRelations") or []) if r.get("to")]
        cands.append({
            "name": row["name"],
            "aliases": [row["name"]] + row["aliases"][:4],
            "role": row["role"],
            "gender": row.get("castGender") or "",
            "castSummary": row.get("castSummary") or "",
            "relations": cast_rels,
            "passages": _passages_for(text, [row["name"]] + row["aliases"][:4]),
            "biography": "",
            "knowledge": [f for f in (row.get("facts") or []) if f and not _looks_quoted(f)][:8],
            "ownSpeech": speech,
            "typicalPhrases": speech[:6],
            "sourceEvidence": row["quotes"][:8],
            "nameEtymon": (row["quotes"] or [""])[0][:180],
            "goals": row["goals"][:6],
            "fears": row["fears"][:6],
            "secrets": row["secrets"][:6],
            "coreFacts": row["traits"][:6],
            "relationships": ([{"from": row["name"], "to": r["to"], "kind": r["kind"], "note": r["note"], "quote": r.get("quote")} for r in (row.get("castRelations") or [])] + [r for r in relations if _norm_name(r["from"]) == _norm_name(row["name"]) or _norm_name(r["to"]) == _norm_name(row["name"])])[:12],
            "fieldProvenance": {k: "belegt" for k, src in (("name", True), ("role", row["role"]), ("goals", row["goals"]), ("fears", row["fears"]), ("secrets", row["secrets"]), ("coreFacts", row["traits"]), ("knowledge", row.get("facts")), ("typicalPhrases", speech)) if src},
        })
    extraction = {
        "title": title,
        "castSummary": [{"name": c["name"], "role": c["role"], "summary": c.get("castSummary") or ""} for c in cands][:30],
        "keyEvents": (cast.get("events") or [])[:40],
        "narrator": cast.get("narrator") or narrator,
        "people": [{"name": c["name"], "aliases": c["aliases"], "role": c["role"], "evidence": " | ".join(c.get("sourceEvidence") or [])[:300]} for c in cands],
        "places": _uniq(places, 40),
        "events": _uniq(events, 60),
        "conflicts": _uniq(conflicts, 30),
        "rules": _uniq(rules, 30),
        "items": _uniq(items, 30),
        "secrets": _uniq(secrets, 30),
        "relations": _uniq(relations, 60),
        "narrator": narrator,
        "coverage": coverage,
    }
    system_world = (
        "Synthetisiere aus strukturierten Extrakten einer Quelle den Weltstamm (AMASTERv2 §9/§11). "
        'Antwort NUR JSON: {"world": {"name", "short", "long", "genre", "tone", "epoch", "geography", '
        '"places": [{"name", "description", "rules": []}], "subplaces": [], "factions": [{"name", "description", "members": []}], '
        '"conflicts": [], "rules": [], "physicalRules": [], "socialRules": [], "history": [], "timeline": [{"text", "actors": []}], '
        '"items": [], "beings": [], "culture": [], "language": [], "worldKnowledge": [], "secretKnowledge": [], "knowledgeBounds": [], '
        '"startScenes": [{"placeName", "time", "presentNames": [], "opening"}], "storyGoals": [], "fateBeats": [{"beat", "mustNot"}]}, '
        '"provenance": {"<feld>": "belegt|abgeleitet"}}. '
        "Belegtes aus den Extrakten hat Vorrang; nur nötige Ergänzungen, als 'abgeleitet' markiert. "
        "Werbung, Autorenbiografie, andere Bücher gehören nicht in die Welt. Deutsch, knapp."
    )
    # V49: Facetten (Orte, Regeln, Zeitlinie, Konflikte/Ziele, Geheimnisse/Wissensgrenzen, Kultur/Historie/Gegenstände/Gruppen)
    # parallel über den Ganzbuch-Kontext, textsortenabhängig, mit Belegpflicht — maßgeblich für ihre Felder.
    facets, facet_errors = _extract_facets(routing, text, title, cfg, cast.get("meta") if isinstance(cast, dict) else None)
    errors.extend(facet_errors[:12])
    if facets:
        extraction["facetten"] = {k: [{kk: vv for kk, vv in it.items() if kk in ("name", "kind", "parent", "rule", "scope", "event", "actors", "subject", "parties", "stakes", "secret", "knownBy", "hiddenFrom", "who", "goal", "text", "name")} for it in v[:20]] for k, v in facets.items()}
        extraction["meta"] = cast.get("meta") if isinstance(cast, dict) else None
    world_parsed = _llm_json(routing, system_world, extraction, temperature=0.2, max_tokens=3000, timeout=120, max_input_chars=24000)
    world = dict(out.get("world") or {})
    if world_parsed and isinstance(world_parsed.get("world"), dict):
        world = _normalize_llm_world(world, world_parsed["world"])
        world["worldProvenance"] = world_parsed.get("provenance") if isinstance(world_parsed.get("provenance"), dict) else {}
    else:
        errors.append(f"world: {_LAST_LLM_ERROR}")
    if facets:
        world = _facets_into_world(world, facets)
        world["facetsSummary"] = {k: len(v) for k, v in facets.items()}
    if isinstance(cast, dict) and cast.get("meta"):
        world["textMeta"] = cast["meta"]
        if cast["meta"].get("genre") and not world.get("genre"):
            world["genre"] = cast["meta"]["genre"]
        if cast["meta"].get("epoche") and not world.get("epoch"):
            world["epoch"] = cast["meta"]["epoche"]
    if not world.get("places") and places:
        world = _normalize_llm_world(world, {"places": _uniq(places, 24)})
    # Rohsätze des lokalen Analyzers (Markertreffer wie "Streit") sind keine Konflikte/Beats.
    # Belegte Konflikte aus der Extraktion haben Vorrang; lokale Zitat-Listen fallen weg.
    if facets.get("conflicts"):
        pass  # Facette ist maßgeblich (belegt, strukturiert)
    elif conflicts:
        world["conflicts"] = _uniq(conflicts, 30)
    else:
        world["conflicts"] = [c for c in (world.get("conflicts") or []) if not _looks_quoted(str(c))]
    for key in ("storyBeats", "fateBeats", "typicalScenes"):
        vals = world.get(key)
        if isinstance(vals, list):
            world[key] = [v for v in vals if not _looks_quoted(json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else str(v))]
    if narrator:
        world["narratorName"] = narrator
    out["world"] = world
    # Vollprofile mit Provenienz (Vertrag §8) — Evidenz = gesammelte Zitate je Figur
    evidence = "\n".join(f"{c['name']}: {' | '.join(c.get('sourceEvidence') or [])}" for c in cands)[:9000]
    pack = {"ok": True, "characterCandidates": cands, "spawnCandidates": list(cands), "roster": [c["name"] for c in cands]}
    prof = _try_complete_profiles(routing, pack, evidence, title) if cands else None
    if prof:
        filled = merge_profiles(pack, prof)
        cands = [local_complete_character(c) if isinstance(c, dict) else c for c in filled.get("characterCandidates") or cands]
        out["profileSource"] = "llm"
        if prof.get("partial"):
            pr = prof["partial"]
            errors.append(f"profiles: nur {pr['received']} von {pr['requested']} Figuren vom Provider vervollständigt ({pr.get('lastError')})")
    else:
        cands = [local_complete_character(c) for c in cands]
        out["profileSource"] = "local-fallback"
        if cands:
            errors.append(f"profiles: {_LAST_LLM_ERROR}")
    cands = _reciprocal_relations(cands)
    out["characterCandidates"] = cands
    out["spawnCandidates"] = list(cands)
    out["roster"] = [c.get("name") for c in cands]
    out["recognize"] = "llm"
    out["analysisSource"] = "llm"
    out["llmProvider"] = routing["provider"]
    out["llmModel"] = routing["model"]
    out["coverage"] = coverage
    out["castMap"] = {"people": len(cast.get("people") or []), "parts": cast.get("parts"), "contextChars": cast.get("contextChars"), "events": len(cast.get("events") or [])}
    if errors:
        out["llmWarnings"] = errors[:8]
    if not coverage["complete"]:
        out["message"] = (
            f"Nur {coverage['chunksAnalyzed']} von {coverage['chunksTotal']} Textblöcken analysiert "
            f"({coverage['analyzedChars']} von {coverage['chars']} Zeichen); {coverage['chunksSkipped']} Blöcke ausgelassen."
        )
    return out


# ---------------------------------------------------------------------------
# Stand 11a (SPS V62.7; Geraet 08.11. 20:51): die Fachlesungen sind PFLICHTFELDER der ersten Antwort (Schemas oben: P_*,
# PLAN_SCHEMA, FORMULATION_SCHEMA "pruefung", GOD_SCHEMA, GOD_BODY_SCHEMA). Die Regeltexte unten sagen kurz, was jedes Feld
# bedeutet - mit denselben Werten wie die bisherigen Einzelregeln. Der Server legt die Felder als Lesungen der ersten Antwort ab
# (vorab_registrieren); jede Lesestelle und jeder Kernel-Validator bleibt unveraendert. Fehlt ein Feld: unbestaetigt.

def _strikt(routing: dict[str, Any], name: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    """Striktes JSON-Schema, wo der Provider es erzwingt (wie _formulation_format); sonst None = json_object."""
    if ("openai.com" in str(routing.get("endpoint") or "").lower()
            and str(routing.get("model") or "").lower().startswith(_STRICT_SCHEMA_MODELS)):
        return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}
    return None


# Feld in "pruefung" -> Lesung(en) der Registry (ERSTE_ANTWORT_LESUNGEN)
_PRUEFUNG_LESUNG = {"vollzug": ("vollzug",), "komponentenart": ("komponentenart",), "sprecher": ("sprecher",), "koerper": ("koerper",),
                    "wirkung": ("wirkung",), "beruehrung": ("beruehrung",), "bewegung": ("bewegung", "bewegungsversuch"),
                    "bittebezug": ("bittebezug",), "erlaubnisbezug": ("erlaubnisbezug",), "grenzbezug": ("grenzbezug",),
                    "grenzumfang": ("grenzumfang",), "offenbarung": ("offenbarung",)}


def pruefung_lesungen(pruefung: Any, zu: str, *, grenze_beleg: str | None = None, rede: str | None = None) -> list[dict]:
    """Die Pflichtfelder EINER Stelle als Lesungen [{lesung, zu, antwort}] (null = keine Lesung)."""
    out: list[dict] = []
    if not isinstance(pruefung, dict) or not str(zu or "").strip():
        return out
    for feld, namen in _PRUEFUNG_LESUNG.items():
        a = pruefung.get(feld)
        if not isinstance(a, dict):
            continue
        stelle = grenze_beleg if feld == "grenzumfang" else (rede if feld == "offenbarung" else zu)
        if str(stelle or "").strip():
            out += [{"lesung": n, "zu": stelle, "antwort": dict(a)} for n in namen]
    kb, kp = pruefung.get("koerperBestaetigung"), pruefung.get("koerper")
    if isinstance(kb, dict):
        stelle = kp.get("beleg") if isinstance(kp, dict) and str(kp.get("beleg") or "").strip() else zu
        out.append({"lesung": "koerper_bestaetigung", "zu": stelle, "antwort": dict(kb)})
    return out


def namen_lesungen(namen: Any) -> list[dict]:
    return [{"lesung": "namen", "zu": n["wortfolge"], "antwort": {k: v for k, v in n.items() if k != "wortfolge"}}
            for n in (namen if isinstance(namen, list) else []) if isinstance(n, dict) and str(n.get("wortfolge") or "").strip()]


def plan_lesungen(parsed: dict, text: str) -> list[dict]:
    """Planer-Antwort: Pflichtfelder je Komponente und Teilstelle + Sprache, Namen, Grenzumfang -> Lesungen. Die Felder werden
    aus dem Plan entfernt - der Kernel sieht die Komponenten wie bisher; eine mitgebrachte freie Liste zaehlt nicht."""
    out: list[dict] = []
    g = parsed.get("grenze") if isinstance(parsed.get("grenze"), dict) else None
    gb = str((g or {}).get("beleg") or "") or None
    for c in parsed.get("komponenten") if isinstance(parsed.get("komponenten"), list) else []:
        if isinstance(c, dict):
            out += pruefung_lesungen(c.pop("pruefung", None), str(c.get("segment") or ""))
    for t in parsed.pop("teilstellen", None) or []:
        if isinstance(t, dict):
            out += pruefung_lesungen(t.get("pruefung"), str(t.get("stelle") or ""))
    sp = parsed.pop("sprache", None)
    if isinstance(sp, dict) and str(text or "").strip():
        out.append({"lesung": "sprache", "zu": str(text), "antwort": sp})
    out += namen_lesungen(parsed.pop("namen", None))
    gu = parsed.pop("grenzumfang", None)
    if isinstance(gu, dict) and gb:
        out.append({"lesung": "grenzumfang", "zu": gb, "antwort": gu})
    parsed.pop("lesungen", None)
    return out


def antwort_lesungen(parsed: dict, speech: str, action: str | None) -> list[dict]:
    """Formulierung: "pruefung" der eigenen Antwort und aussagen[].lesung -> Lesungen."""
    out: list[dict] = []
    g = parsed.get("grenze") if isinstance(parsed.get("grenze"), dict) else None
    pr = parsed.get("pruefung") if isinstance(parsed.get("pruefung"), dict) else {}
    if action:
        out += pruefung_lesungen({k: v for k, v in pr.items() if k not in ("grenzumfang", "offenbarung")}, action)
    if isinstance(pr.get("grenzumfang"), dict) and g and str(g.get("beleg") or "").strip():
        out.append({"lesung": "grenzumfang", "zu": str(g["beleg"]), "antwort": pr["grenzumfang"]})
    if isinstance(pr.get("offenbarung"), dict) and str(speech or "").strip():
        out.append({"lesung": "offenbarung", "zu": str(speech), "antwort": pr["offenbarung"]})
    for a in parsed.get("aussagen") if isinstance(parsed.get("aussagen"), list) else []:
        l = a.get("lesung") if isinstance(a, dict) else None
        seg = str((a or {}).get("segment") or "") if isinstance(a, dict) else ""
        if not isinstance(l, dict) or not seg.strip():
            continue
        if isinstance(l.get("aussage"), dict):
            out.append({"lesung": "aussage", "zu": seg, "antwort": l["aussage"]})
        for t in l.get("taten") if isinstance(l.get("taten"), list) else []:
            if isinstance(t, dict):
                out.append({"lesung": "aussage_tat", "zu": seg, "antwort": {k: v for k, v in t.items() if k != "ereignis"}})
    return out


GOD_BODY_SCHEMA: dict[str, Any] = _obj({
    "bereich": _E("koerper", "nicht_koerper", "unklar"), "schmerz": _E("kein", "leicht", "mittel", "stark", null=True),
    "beweglichkeit": _E("frei", "eingeschraenkt", "stark_eingeschraenkt", "unbeweglich", null=True),
    "bewusstsein": _E("wach", "benommen", "bewusstlos", null=True), "gefesselt": _BN, "geknebelt": _BN,
    "haltung": _E("liegend", "sitzend", "kniend", "stehend", "kopfstand", null=True), "schlaf": _E("einschlafen", "aufwachen", null=True),
    "sehen": _E("verliert", "zurueck", null=True), "sprechen": _E("verliert", "zurueck", null=True),
    "verletzung": _nullable(_obj({"art": _S, "glied": _SN, "seite": _E("links", "rechts", null=True), "schwer": _B})),
    "heilung": _BN, "beleg": _SN, "bestaetigung": _nullable(P_KOERPER_BESTAETIGUNG)})

GOD_SCHEMA: dict[str, Any] = _obj({
    "anweisungen": {"type": "array", "items": _obj({
        "ziel": _S, "art": _E("koerper", "wissen", "beziehung", "szene", "welt", "zustand", "zeit", "handlung"), "andere": _SN,
        "text": _S, "beleg": _S})},
    "unklar": {"type": "array", "items": _S}, "namen": P_NAMEN})

_ART_TEXT = ("art: tatsaechlich = der Text sagt, dass es JETZT wirklich geschieht; verneint = dass es nicht geschieht (auch wenn die "
             "Verneinung woanders im Satz steht); wunsch = nur gewünscht, gefordert oder erlaubt; frage = erfragt; bedingung = nur unter "
             "einer Bedingung; ankuendigung = erst später; erzaehlt = vergangen oder nur berichtet; zitat = nur zitiert. ")

_NAMEN_TEXT = ("namen = je zusammenhängender Wortfolge, in der der Name einer Person mit davorstehendem Gruß, Titel oder Präposition "
               "steht (z. B. 'Hallo Mara', 'Frau Nowak', 'Neben Mara Nowak'): {wortfolge WÖRTLICH, wortklassen = eine Klasse je Wort "
               "(name = Wort des geschriebenen Namens, gruss, titel, praeposition, anderes, unklar; name-Wörter lückenlos), rolle anrede "
               "(diese Person wird angesprochen) | nennung, status eindeutig | unklar}; keine solche Wortfolge: []. ")

PLAN_PRUEFUNG_RULES = (
    " PRÜFUNG (PFLICHT, AMASTER §24.2/§24.7): Jede Komponente hat das Feld \"pruefung\" - bei rede genau {komponentenart, sprecher}, "
    "bei handlung genau {vollzug, komponentenart, koerper, koerperBestaetigung, wirkung, beruehrung, bewegung, bittebezug, "
    "erlaubnisbezug, grenzbezug}; was nicht zutrifft, ist null. Die segmente zusammen enthalten JEDES Wort der Äußerung: auch ein "
    "Nachsatz nach einer Handlung (etwa eine Bemerkung an die Angesprochene) ist eine eigene rede-Komponente. Jeder beleg ist WÖRTLICH aus der Äußerung kopiert; das System prüft jeden Beleg am Text. Was "
    "du nicht sicher belegen kannst, beantwortest du verneinend bzw. ohne Beleg - nie raten. zeit überall: jetzt|vergangen|zukunft|moeglich. "
    "vollzug (jede handlung): {geschieht, art, beleg, taeter, ziel} - wird die Handlung in diesem Moment tatsächlich ausgeführt? "
    + _ART_TEXT +
    "geschieht nur bei tatsaechlich true; beleg = die Wörter, die die Art zeigen (bei verneint die Verneinung samt Verb), sonst null; "
    "taeter = der Name der Person, die es laut Äußerung tut, wörtlich wie geschrieben; Ich-Form, nur ein Pronomen oder kein Subjekt: "
    "'figur'; ziel = der Eigenname der getroffenen Person wörtlich, bei bloßem Pronomen oder niemand null. "
    "komponentenart (jede Komponente): {art rede|handlung|unklar, beleg, wirkung} - rede = laut gesprochene eigene Worte des Sprechers "
    "(auch Anrede oder Befehl an jemanden), handlung = seine als Tat dargestellte gegenwärtige Handlung; wirkung bei handlung wie das "
    "Komponentenfeld wirkung, sonst null. "
    "sprecher (jede rede): {sprecher, beleg, handlung, adressat, ansageRolle anrede|sprecheransage|unklar, ansageBeleg} - wer diese Worte "
    "sagt (Name wörtlich, sonst 'figur'); handlung = eine EIGENE Tat des Sprechers in der einleitung, wörtlich, ohne Bindewort und "
    "Sprechverb, sonst null; adressat = an wen die Worte gehen (Name wörtlich, sonst null); bei einer Anrede ist der Name Adressat, nicht "
    "Sprecher. "
    "koerper (jede handlung): {haltung, schlaf, zeit, beleg} - nur was die Handlung JETZT am EIGENEN Körper des Täters ändert: haltung "
    "liegend|sitzend|kniend|stehend|kopfstand nur, wenn der ganze Körper die Lage wechselt; schlaf einschlafen|aufwachen nur bei echtem "
    "Schlaf; sonst null; das bloße Zeigen eines bestehenden Zustands ist keine Änderung. "
    "koerperBestaetigung: nur wenn koerper eine Änderung nennt, sonst null: {art, inhalt, beleg} - wie sagt der Text an koerper.beleg "
    "genau diese Änderung (art wie oben, zusätzlich ausdruck = zeigt nur einen bestehenden Zustand); inhalt gleich|anders; beleg wörtlich. "
    "wirkung: nur bei handlung mit wirkung gewalt|fesseln|befreien, sonst null: {bestaetigt, zeit, ziel, beleg, versuch, gegen, "
    "beruehrung, beruehrungBeleg} - bestaetigt = die Handlung führt genau diese Wirkung jetzt am Körper von ziel aus (ohne beleg false); "
    "versuch = jetzt versucht, aber nicht erreicht; gegen = Fläche oder Gegenstand, an die ziel gedrückt wird, wörtlich, sonst null; "
    "beruehrung = nur wenn nicht bestätigt, der Körper von ziel aber jetzt berührt wird (beruehrungBeleg wörtlich). "
    "beruehrung: nur bei handlung mit wirkung zaertlich|gewalt, sonst null: {beruehrt, zeit, ziel, beleg} - berührt die Handlung jetzt "
    "tatsächlich den Körper von ziel (beleg = die Stelle des Kontakts). "
    "bewegung: nur bei handlung mit wirkung annaeherung|entfernung, sonst null: {bestaetigt, zeit, ziel, beleg, versuch} - ändert die "
    "Handlung jetzt den Abstand zu ziel; versuch = versucht, nicht erreicht. "
    "bittebezug / erlaubnisbezug / grenzbezug: nur bei handlung und nur, wenn 'offen' eine angenommene Bitte, eine Erlaubnis bzw. eine "
    "Grenze nennt, die diese Handlung betreffen kann, sonst null: bittebezug {teile: [{wortlaut, erbeten}]} und erlaubnisbezug {teile: "
    "[{wortlaut, innerhalb}]} zerlegen die Handlung in ihre Teilhandlungen (wörtlich, zusammen die ganze Handlung) - erbeten bzw. "
    "innerhalb nur, wenn der Teil genau das Erbetene bzw. Erlaubte tut; grenzbezug {betroffen, beleg} - tut die Handlung genau das "
    "Verbotene. "
    "Auf oberster Ebene PFLICHT: \"teilstellen\": [{stelle, pruefung}] - dieselbe pruefung für jeden Teil zwischen Sternchen (*…*) und "
    "jeden einzelnen Satz eines handlung-Segments, der nicht selbst ein segment ist, und für eine eigene Tat in einer einleitung "
    "(stelle WÖRTLICH); sonst []. "
    "\"sprache\": {stellen: [...]} - jede Stelle, an der die Äußerung festlegt, wie eine Person heißt oder genannt wird (art name), oder "
    "was ein Wort bedeutet (art bedeutung): {art, status festgelegt (ausdrücklich für ab jetzt) | verneint | zitiert | erwogen | anrede "
    "(nur als Anrede, Kosename oder Beschreibung benutzt), bezeichnung (nur das Wort, WÖRTLICH), person (bei name: ich | du | ein Name, "
    "sonst null), bedeutung (bei bedeutung wörtlich, sonst null), beleg}; keine: []. "
    "\"" + _NAMEN_TEXT.replace("namen = ", "namen\": ", 1) +
    "\"grenzumfang\": nur wenn grenze nicht null, sonst null: {gegenstand (WAS nicht bzw. doch berührt werden darf, wörtlich aus "
    "grenze.beleg), gegenstand_art person (die Sprecherin als Ganze) | koerperstelle_oder_art | diese_handlung, richtung verboten | "
    "erlaubt, geltung offen (ausdrücklich dauerhaft) | zeitraum | nicht_genannt, geltung_beleg}."
)

FORMULIERUNG_PRUEFUNG_RULES = (
    " PRÜFUNG (PFLICHT): Feld \"pruefung\" mit ALLEN Schlüsseln koerper, koerperBestaetigung, wirkung, beruehrung, bewegung, "
    "grenzumfang, offenbarung - für DEINE EIGENE Antwort; was nicht zutrifft, ist null; jeder beleg WÖRTLICH aus deiner action bzw. speech. "
    "koerper (wenn action nicht null): {haltung, schlaf, zeit, beleg} - nur was deine action JETZT an deinem eigenen Körper ändert "
    "(haltung liegend|sitzend|kniend|stehend|kopfstand nur bei Wechsel der Lage des ganzen Körpers; schlaf einschlafen|aufwachen), sonst "
    "null in haltung und schlaf. koerperBestaetigung (nur wenn koerper eine Änderung nennt): {art, inhalt gleich|anders, beleg}; "
    + _ART_TEXT +
    "zusätzlich ausdruck = zeigt nur einen bestehenden Zustand. "
    "wirkung (nur bei wirkung.art gewalt|fesseln|befreien): {bestaetigt, zeit, ziel, beleg, versuch, gegen, beruehrung, beruehrungBeleg}; "
    "beruehrung (nur bei zaertlich|gewalt): {beruehrt, zeit, ziel, beleg}; bewegung (nur bei annaeherung|entfernung): {bestaetigt, zeit, "
    "ziel, beleg, versuch} - jeweils: führt deine action genau das jetzt aus (ohne beleg false). "
    "grenzumfang (nur wenn grenze nicht null): {gegenstand, gegenstand_art person|koerperstelle_oder_art|diese_handlung, richtung "
    "verboten|erlaubt, geltung offen|zeitraum|nicht_genannt, geltung_beleg}. "
    "offenbarung: {offenbart, beleg} - sagt deine speech ausdrücklich etwas, das eines deiner Ziele als noch ungesagt nennt (beleg "
    "wörtlich), sonst offenbart false. "
    "In aussagen hat jeder Eintrag das Feld \"lesung\": bei art bestreitet_geschehen {aussage: {verneint (die verneinte Wortgruppe "
    "samt Verb, wörtlich), gegenstand geschehen|bewertung|gefuehl|anderes, bestritten [die Kennungen E…, deren Stattfinden verneint "
    "wird]}, taten: [je bestrittenem Ereignis {ereignis E…, bestreitet, verneint, tat (die Wörter der Handlung im Ereignis, wörtlich)}]}, "
    "sonst null."
)

GOD_KOERPER_PRUEFUNG_RULES = (
    " PFLICHT im selben JSON auch das Feld \"bestaetigung\": ist beleg nicht null, {art, inhalt, beleg} - wie sagt der Text an deinem "
    "beleg genau die Körperänderung, die du angibst: " + _ART_TEXT + "ausdruck = zeigt nur einen bestehenden Zustand; inhalt gleich = "
    "die Stelle sagt dasselbe | anders; beleg = die Wörter, die die Art zeigen, wörtlich. Ist beleg null: null."
)

GOD_NAMEN_PRUEFUNG_RULES = (
    " PFLICHT im selben JSON auch das Feld \"namen\" (Wortfolgen im godText): " + _NAMEN_TEXT
)


def erleben_aus_antwort(res: dict) -> dict:
    """Stand 11B: Erlebensantwort mit Nachweis NEBEN jedem Wert (APPRAISAL_SCHEMA) -> die bisherige Struktur: zustand_aenderung als
    Dict und kausalpruefung.pruefungen mit genau den Feldnamen von kernel.appraisal_effect_fields. Eine Antwort in der alten Form
    (kausalpruefung als Liste) bleibt unveraendert. Ein Wert ohne Nachweis bekommt keinen Eintrag - der Kernel verwirft nur ihn."""
    if not isinstance(res, dict):
        return res
    neu = isinstance(res.get("zustand_aenderung"), list) or any(k in res for k in ("gefuehl_nachweis", "absicht_nachweis"))
    if not neu:
        return res
    out = dict(res)
    pruef: list[dict] = []

    def _nw(feld: str, n: Any) -> None:
        if isinstance(n, dict):
            pruef.append({"feld": feld, **{k: v for k, v in n.items() if k != "feld"}})

    zustand: dict = {}
    for e in res.get("zustand_aenderung") if isinstance(res.get("zustand_aenderung"), list) else []:
        if not isinstance(e, dict) or not str(e.get("name") or "").strip():
            continue
        try:
            wert = float(e.get("wert") or 0)
        except (TypeError, ValueError):
            continue
        zustand[str(e["name"])] = wert
        if abs(wert) > 1e-9:
            _nw("zustand." + str(e["name"]), e.get("nachweis"))
    if isinstance(res.get("zustand_aenderung"), dict):
        zustand = dict(res["zustand_aenderung"])
    out["zustand_aenderung"] = zustand
    if str(res.get("gefuehl") or "").strip():
        _nw("gefuehl", res.get("gefuehl_nachweis"))
    if str(res.get("absicht") or "").strip():
        _nw("absicht", res.get("absicht_nachweis"))
    bez = []
    for i, b in enumerate(res.get("beziehung_aenderung") if isinstance(res.get("beziehung_aenderung"), list) else []):
        if not isinstance(b, dict):
            continue
        for d in ("trust", "closeness", "fear"):
            try:
                if abs(float(b.get(d) or 0)) > 1e-9:
                    _nw(f"beziehung.{i}.{d}", b.get(d + "_nachweis"))
            except (TypeError, ValueError):
                pass
        bez.append({k: v for k, v in b.items() if not k.endswith("_nachweis")})
    out["beziehung_aenderung"] = bez
    out.pop("gefuehl_nachweis", None)
    out.pop("absicht_nachweis", None)
    alt = res.get("kausalpruefung") if isinstance(res.get("kausalpruefung"), dict) else {}
    out["kausalpruefung"] = {"pruefungen": pruef + [p for p in (alt.get("pruefungen") or []) if isinstance(p, dict)
                                                    and p.get("feld") not in {x["feld"] for x in pruef}]}
    return out
