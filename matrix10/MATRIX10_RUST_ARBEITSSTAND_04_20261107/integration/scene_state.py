"""V44 Szenen-Zustandsmaschine (Vorbild: Ursprungssystem services/scene_state_machine.py —
„so follow-up prompts read from scene state, not only the last utterance“; AMASTERv2 §21/§23/§47).

Kanonischer Szenenzustand je Session (`session["sceneState"]`, kernel-owned):
- status: open | escalated | aftermath | closed
- actorIds / targetIds der laufenden Szene (wer handelt an wem), nextBeatOwner
- lastPhysicalBeat, lastEmotionalBeat (mit Turn), openEmotions je Figur (Emotionsspur)
- openBeats: offene Fragen/Bitten/Vorschläge/Angriffe mit Besitzer, bis beantwortet/erledigt
- escalation 0..1 (steigt mit physischen/emotionalen Beats, fällt mit ruhigen Turns)
Fortschreibung mechanisch aus den Commits (Rede, Handlung, Synapsen, Turn-Plan) — keine
Wortlisten für Verhalten; Klassifikation kommt aus den bereits vorhandenen Ownern (Körper-
Writer, Synapsen, Plan). Der Persona-Brief bekommt den Block „OFFENE SZENE“.
"""
from __future__ import annotations

import re
from typing import Any

from .ids import uid

DECAY_TURNS = 3


def ensure_state(session: dict) -> dict:
    st = session.get("sceneState")
    if not isinstance(st, dict) or not st.get("sceneId"):
        st = {
            "sceneId": uid("scn"),
            "status": "open",
            "actorIds": [],
            "targetIds": [],
            "nextBeatOwner": "",
            "lastPhysicalBeat": None,
            "lastEmotionalBeat": None,
            "openEmotions": {},
            "openBeats": [],
            "escalation": 0.0,
            "updatedTurn": int(session.get("turnIndex") or 0),
            "history": [],
        }
        session["sceneState"] = st
    return st


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _note(st: dict, turn: int, what: str) -> None:
    hist = st.setdefault("history", [])
    hist.append({"turn": turn, "event": what[:120]})
    if len(hist) > 40:
        del hist[: len(hist) - 40]


_ESCALATING_EFFECTS = frozenset({"strike", "restrain"})


def _pair(a: str, b: str) -> str:
    return "|".join(sorted((str(a), str(b))))


def set_spatial(session: dict, a: str, b: str, relation: str, *, turn: int, fact_id: str | None, text: str) -> None:
    """V60 (AMASTER §43.2 SpatialState): the current spatial relation between two
    figures, set only by a validated effect class (never by words). It is the
    addressable current state; history stays in the Facts."""
    if not a or not b or str(a) == str(b):
        return
    st = ensure_state(session)
    sp = st.setdefault("spatial", {})
    key = _pair(a, b)
    prev = sp.get(key) if isinstance(sp.get(key), dict) else None
    if prev and prev.get("relation") == relation:
        prev["lastTurn"] = turn
        prev["lastFactId"] = fact_id
        prev["lastText"] = str(text or "")[:120]
        prev["repeats"] = int(prev.get("repeats") or 0) + 1
        return
    row = {"relation": relation, "since": turn, "factId": fact_id, "text": str(text or "")[:120],
           "lastTurn": turn, "lastFactId": fact_id, "lastText": str(text or "")[:120], "repeats": 0,
           # V65P (AMASTER §43.2): who set this relation.
           "by": str(a)}
    # V65P (AMASTER §42 Versuch -> tatsaechlicher Ausgang -> Folgen, §43.1): a
    # distance that the OTHER person ends by touching or coming close again
    # means the withdrawals of that phase were overcome. The outcome stays with
    # the pair (before, it was lost when the row was replaced: IST-Probe 4).
    # Who withdrew, and which acts, comes from the committed Facts (canonical
    # history; also for rows written before V65P), never from text.
    overcome = [e for e in ((prev or {}).get("overcome") or []) if isinstance(e, dict)]
    if prev and prev.get("relation") == "abstand" and relation in ("beruehrung", "nah"):
        facts = [f for f in (session.get("facts") or []) if isinstance(f, dict)]
        setter = str(prev.get("by") or next((f.get("actorId") for f in facts if prev.get("factId") and f.get("id") == prev.get("factId")), "") or "")
        if setter and setter == str(b):   # b withdrew from a; a now reaches b again
            other = str(a)
            wf = [f for f in facts if f.get("kind") == "action" and str(f.get("actorId") or "") == setter
                  and str(f.get("targetId") or "") == other and isinstance(f.get("effect"), dict)
                  and f["effect"].get("effectKind") == "withdraw" and f["effect"].get("outcome") != "blocked"
                  and f.get("validated") is not False and int(prev.get("since") or 0) <= int(f.get("turn") or 0) <= int(turn)]
            if wf:
                overcome.append({"withdrawer": setter, "withdrawals": len(wf),
                                 "withdrawFacts": [str(f.get("id")) for f in wf if f.get("id")][-6:],
                                 "since": prev.get("since"), "by": other, "turn": turn, "factId": fact_id,
                                 "text": str(text or "")[:120], "relation": relation})
                _note(st, turn, f"Raum: Rückzug von {setter[:8]} überwunden ({str(text or '')[:40]})")
                # V65Q (AMASTER §34 Z. 1767 Kausalprovenienz, §34.3 Z. 1831 "Historische
                # Evidenz wird nicht heimlich geloescht", §34.1 Z. 1817; Pruefung v2.8 P-04):
                # the act that reached her again carries WHICH withdrawals it overcame -
                # new evidence on its own Fact, readable after the room row is gone
                # (place change). The withdrawal Facts themselves stay unchanged.
                ev = next((f for f in reversed(facts) if fact_id and str(f.get("id") or "") == str(fact_id)), None)
                if ev is not None:
                    if not isinstance(ev.get("effect"), dict):
                        ev["effect"] = {}
                    eff = ev["effect"]
                    eff["overcomes"] = list(dict.fromkeys([str(x) for x in (eff.get("overcomes") or [])]
                                                          + [str(f.get("id")) for f in wf if f.get("id")]))[-12:]
    if overcome:
        row["overcome"] = overcome[-6:]
    sp[key] = row
    if relation == "abstand":
        # V65Q: distance between the two ends a pressed-against position of one by the other.
        for cid, other in ((str(a), str(b)), (str(b), str(a))):
            pos = (st.get("positions") or {}).get(cid)
            if isinstance(pos, dict) and str(pos.get("by") or "") == other:
                release_position(session, cid, turn=turn, why="Abstand")
    _note(st, turn, f"Raum: {relation} ({str(text or '')[:50]})")


def set_position(session: dict, cid: str, gegen: str, *, by: str, turn: int, fact_id: str | None, text: str) -> None:
    """V65Q (AMASTER §20 Z. 926 Koerperpositionen, Z. 947 raeumliche Relationen zu
    Gegenstaenden, §43.2, FOUNDATION H; Pruefung v2.8 P-02): a figure is pressed or
    held against a surface by another figure - written only by a CONFIRMED body act
    whose check found the surface literally in the act. Addressable current state."""
    if not cid or not by or str(cid) == str(by) or not str(gegen or "").strip():
        return
    st = ensure_state(session)
    st.setdefault("positions", {})[str(cid)] = {"gegen": str(gegen)[:80], "by": str(by), "since": turn,
                                                "factId": fact_id, "text": str(text or "")[:120]}
    _note(st, turn, f"Position: {str(cid)[:8]} an {str(gegen)[:30]} gedrückt")


def release_position(session: dict, cid: str, *, turn: int, why: str) -> None:
    st = session.get("sceneState") if isinstance(session.get("sceneState"), dict) else None
    if st and isinstance(st.get("positions"), dict) and st["positions"].pop(str(cid), None) is not None:
        _note(st, turn, f"Position: {str(cid)[:8]} frei ({why})")


def active_position(session: dict, cid: str) -> dict | None:
    """The figure's current pressed-against position while the presser is present and still in
    touch with her (the pair's spatial relation); otherwise None. Read only."""
    st = session.get("sceneState") if isinstance(session.get("sceneState"), dict) else None
    pos = ((st or {}).get("positions") or {}).get(str(cid)) if st else None
    if not isinstance(pos, dict):
        return None
    by = str(pos.get("by") or "")
    present = {str(x) for x in ((session.get("scene") or {}).get("presentIds") or [])}
    row = ((st.get("spatial") or {}).get(_pair(cid, by)) or {}) if by else {}
    if not by or (present and by not in present) or row.get("relation") != "beruehrung":
        return None
    return pos


def body_contact_proposition(session: dict, actor_id: str | None, target_id: str | None) -> dict | None:
    """V65S (AMASTER §35, §36.5): the Proposition "Koerperkontakt actor -> target" (one per directed pair), or None.
    Written only by the kernel's Proposition owner (_body_contact_matter / apply_proposition). Read only."""
    a, t = str(actor_id or ""), str(target_id or "")
    return next((p for p in session.get("propositions") or [] if isinstance(p, dict) and p.get("kind") == "koerperkontakt"
                 and str(p.get("actorId") or "") == a and str(p.get("targetId") or "") == t), None)


_KK_KIND = {"acceptance": "acceptance", "accept": "acceptance", "refusal": "refusal", "refuse": "refusal",
            "revoke": "revoke", "revocation": "revoke"}


def body_contact_entries(session: dict, prop: dict | None) -> list[dict]:
    """V65T (AMASTER §35 "Historische Evidenz bleibt append-only", §36.5 Z. 1947 "an die betreffende Proposition oder
    Handlung gebunden", Z. 1974 "fruehere Zustimmung ist nicht automatisch aktuelle Zustimmung"): the giver's answers
    to the Koerperkontakt container, in commit order, each with the concrete acts it answers (actFactIds), its
    validated scope (diese_tat | jede_beruehrung, §34.1 Grenze) and window. Written only by the lifecycle owner
    (kernel.apply_proposition). Entries without a recorded scope (V65S) count for no act (data is not reinterpreted).
    Read only."""
    if not isinstance(prop, dict):
        return []
    pid = str(prop.get("id") or "")
    out = []
    by_id = {str(f.get("id") or ""): f for f in session.get("facts") or [] if isinstance(f, dict)}
    for i, f in enumerate(session.get("facts") or []):
        if not isinstance(f, dict) or f.get("kind") != "lifecycle" or f.get("validated") is False:
            continue
        if str(f.get("propositionId") or f.get("proposition_id") or "") != pid:
            continue
        kind = _KK_KIND.get(str(f.get("event_kind") or "").lower())
        if kind is None:
            continue
        pl = f.get("payload") if isinstance(f.get("payload"), dict) else {}
        kk = pl.get("koerperkontakt") if isinstance(pl.get("koerperkontakt"), dict) else {}
        acts = [str(x) for x in kk.get("actFactIds") or []]
        # Stand 05 (AMASTER §34.1/§35): the persisted texts of the concrete acts this answer is bound to. Only
        # transported; Rust decides which part an act names. Bound only if every named act exists in this session.
        found = [by_id[a] for a in acts if a in by_id]
        out.append({"index": i, "factId": f.get("id"), "kind": kind, "turn": int(f.get("turn") or 0), "text": str(f.get("text") or ""),
                    "by": str(f.get("actorId") or ""), "acts": acts,
                    "actTexts": [str(x.get("text") or "") for x in found], "actsBound": bool(acts) and len(found) == len(acts),
                    "scope": kk.get("scope") if kk.get("scope") in ("diese_tat", "jede_beruehrung", "eingeschraenkt") else None,
                    "einschraenkung": str(kk.get("einschraenkung") or "")[:160] if kk.get("scope") == "eingeschraenkt" else None,
                    # V65X: the words of a part an UNCONFIRMED answer named (grenze unbestaetigt, kept for visibility)
                    "einschraenkungOffen": str(kk.get("einschraenkung") or "")[:160] if kk.get("scope") != "eingeschraenkt"
                    and kk.get("einschraenkung") else None,
                    "window": kk.get("window") if isinstance(kk.get("window"), dict) else None,
                    "beleg": str(kk.get("beleg") or ""), "responds": f.get("responds_to_fact_id")})
    return sorted(out, key=lambda e: (e["turn"], e["index"]))   # commit order: turn first (the reader orders Facts by ID)


def _in_window(window: dict | None, at: str | None, *, session: dict | None = None, act: dict | None = None) -> bool:
    if not window:
        return True
    if window.get("art") == "szene":
        return _in_scene(session, window, act)
    if not at:
        return False   # an act without its time is not covered by a time-limited boundary
    return str(window.get("start") or "") <= str(at)[:16] <= str(window.get("end") or "")


def scene_id(session: dict | None) -> str | None:
    """V65W (Tiefenpruefung v1 P03/C4; AMASTER §20 "Eine Szene ist der aktuelle kausale Raum", SceneState mit "Uebergang
    zur naechsten Szene", Z. 949): the identity of the current scene - SceneState.sceneId, the existing owner (written by
    ensure_state and renewed by the scene transition writer external_delta). None without a SceneState. Read only."""
    st = (session or {}).get("sceneState") if isinstance(session, dict) else None
    return str(st.get("sceneId")) if isinstance(st, dict) and st.get("sceneId") else None


def scene_closed(session: dict | None) -> bool:
    """V65W (C4): the current scene was ended (SceneState status closed, external_delta). Read only."""
    st = (session or {}).get("sceneState") if isinstance(session, dict) else None
    return bool(isinstance(st, dict) and st.get("status") == "closed")


def act_scene_id(act: dict | None) -> str | None:
    """V65W (C4): the scene an act was committed in, as its own Fact recorded it at commit (effect.consent.sceneId,
    kernel._body_contact_matter). None for acts committed before V65W (not reinterpreted). Read only."""
    eff = (act or {}).get("effect") if isinstance(act, dict) and isinstance(act.get("effect"), dict) else {}
    c = eff.get("consent") if isinstance(eff.get("consent"), dict) else {}
    return str(c.get("sceneId")) if c.get("sceneId") else None


def _in_scene(session: dict | None, window: dict, act: dict | None) -> bool:
    """V65V (Nachpruefung v1 K4; AMASTER §36.5 Gueltigkeitsfenster; V65W: abgeleitet aus §36.5 Z. 1956/1974, §20 Z. 914, §24.7 -
    nicht aus §46.5, das den Session-God regelt): a
    boundary without a named duration holds in the scene it was set in - the same place, without a place change in
    between (every Fact carries the scene's placeId at its commit). `act` = the later act (its turn and place); without
    it the session's current scene. Read only.
    V65W (Tiefenpruefung v1 P03/C4; AMASTER §20 Z. 949 "Eine Szene kann durch Nutzer, Regie, God, Fate oder den
    tatsaechlichen Verlauf wechseln", §21 Szene und Ort getrennt): the scene is no longer read from the place. A window
    that recorded its scene (sceneId) holds only while the act's own recorded scene - or, without an act, the current
    SceneState - is the same scene; a scene change at the same place ends it, a place change still ends it too. A window
    without sceneId (V65V) keeps its V65V reading (place + turn), the data is not reinterpreted."""
    if not isinstance(session, dict):
        return False
    place = str(window.get("placeId") or "")
    since = int(window.get("seitTurn") or 0)
    if isinstance(act, dict):
        until, here = int(act.get("turn") or 0), str(act.get("placeId") or "")
    else:
        until, here = 10 ** 9, str((session.get("scene") or {}).get("placeId") or "")
    if here != place:
        return False
    if window.get("sceneId"):
        now_scene = act_scene_id(act) if isinstance(act, dict) else scene_id(session)
        closed = bool(((act.get("effect") or {}).get("consent") or {}).get("sceneClosed")) if isinstance(act, dict) and isinstance(act.get("effect"), dict) else scene_closed(session)
        if isinstance(act, dict) and now_scene is None:
            now_scene = scene_id(session)   # the act being committed now: its scene is the current one
            closed = scene_closed(session)
        if closed or str(now_scene or "") != str(window.get("sceneId")):
            return False
    return not any(isinstance(f, dict) and since < int(f.get("turn") or 0) <= until and str(f.get("placeId") or place) != place
                   for f in session.get("facts") or [])


def body_contact_standing(session: dict, prop: dict | None, *, before: tuple[int, int] | None = None, at: str | None = None,
                          act: dict | None = None) -> dict | None:
    """Current broad consent is reduced in Rust, never inferred by text.

    The existing canonical SceneState reader owns `_in_window` (scene/time)
    and projects the returned indices onto append-only Fact evidence.
    Every event is scoped to the giver AND checked for validity before it
    may replace an earlier state. A timed-out permission cannot erase a
    still-active refusal. No second persistence owner and no Python fallback.
    """
    if not isinstance(prop, dict):
        return None
    giver = str(prop.get("targetId") or "")
    entries = sorted((e for e in body_contact_entries(session, prop)
                      if before is None or (e["turn"], e["index"]) < before),
                     key=lambda e: (e["turn"], e["index"]))
    active = [_in_window(e.get("window"), at, session=session, act=act) for e in entries]
    from .native_boundary import reduce_body_contact_standing
    result = reduce_body_contact_standing(giver, entries, active)
    if result["standing"] is not None:
        standing = entries[result["standing"]]
        exceptions = []
        for item in result["exceptions"]:
            event = entries[item["index"]]
            exceptions.append({"causeFactId": event["factId"], "kind": item["kind"],
                               "einschraenkung": event["einschraenkungOffen"] if item["kind"] == "unbestaetigt"
                               else event["einschraenkung"], "turn": event["turn"]})
        return {"state": "declined" if standing["kind"] == "refusal" else "accepted", "since": standing["turn"],
                "causeFactId": standing["factId"], "beleg": standing["beleg"], "window": standing.get("window"),
                "text": standing["text"], "ausnahmen": exceptions}
    if result["ended"] is not None:
        old, latest = (entries[i] for i in result["ended"])
        if old["kind"] == "acceptance" and latest["kind"] == "revoke":
            return {"state": "revoked", "since": latest["turn"], "causeFactId": latest["factId"],
                    "beleg": old["beleg"], "grantedTurn": old["turn"], "text": latest["text"]}
    return None


_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "ss"})


def _word_tokens(text: Any) -> list[str]:
    return [w.translate(_FOLD) for w in re.findall(r"[a-zäöüß]+", str(text or "").casefold())]


def _same_stem(a: str, b: str) -> bool:
    n = len(a) if len(a) <= 3 else max(3, len(a) - 2)
    return len(b) >= n and a[:n] == b[:n]


def _same_word(a: str, b: str) -> bool:
    """V65Z (A05): `b` is the head word `a` itself, only inflected (same stem, at most two letters more or less):
    Hand / Hände / Händen, Schulter / Schultern, küssen / Kuss / küsse - not a compound like Handtasche or Haarspange."""
    return _same_stem(a, b) and abs(len(b) - len(a)) <= 2


def _voice_match(a: str, b: str) -> bool:
    """V66: two words are the same word for a restriction - inflected (_same_word), or the same word in the other person's
    voice: the giver quotes her own part ("meine"), the act addresses her ("deine") - same length, same letters after the
    first. Grammar of the two words, no list. Read only."""
    return _same_word(a, b) or (len(a) == len(b) >= 4 and a[1:] == b[1:])


def names_restriction(text: Any, restriction: Any, *, exact: bool = False, word: bool = False) -> bool:
    """Canonical reader: native restriction anchor, never a consent by itself."""
    from .native_boundary import restriction_match
    # The text/restriction types are fixed by the existing reader's canonical
    # string coercion; booleans and None never authorize an exact positive.
    return restriction_match(str(text or ""), str(restriction or ""),
                             "exact" if exact else "word" if word else "veto")


def literal_in(part: Any, text: Any) -> bool:
    """V66 (Audit5 E06 "Spannen"; AMASTER §24.2 Z. 1113, §34.1): `part` stands in `text` literally AND on word boundaries -
    "deine Hand" is not literal in "deine Handtasche" (V65Z took any substring). Normalized like _norm_seg. Read only."""
    p, t = _norm_seg(part), _norm_seg(text)
    return bool(p) and re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", t) is not None


def parts_cover(act_text: Any, parts: list) -> tuple[bool, str]:
    """V67 (Audit7 V66-05 "Ich nehme deine Hand und tu dir weh"; AMASTER §24.2 Z. 1113, §34.1 jede Komponente, §36.5 an die
    konkrete Handlung gebunden): (every part literal in the act on word boundaries - each at its own place, one place is
    never read twice -, what of the act no part covers). The parts must cover the whole act: before the first part at most
    one word (the doer: "Ich", a name), between two parts at most one connecting word ("und"), after the last part nothing.
    V65X/V66 counted only leftover words of 4+ letters, so "und tu dir weh" (all short) passed as covered. Grammar of the
    act's own words, no list. Read only."""
    act = _norm_seg(act_text)
    words = [(m.start(), m.end(), m.group(0)) for m in re.finditer(r"\w+", act)]
    taken: list[tuple[int, int]] = []
    for t in parts:
        p = _norm_seg(t.get("wortlaut") if isinstance(t, dict) else t)
        if not p:
            return False, ""
        hit = None
        for m in re.finditer(r"(?<!\w)" + re.escape(p) + r"(?!\w)", act):
            if not any(m.start() < b and a < m.end() for a, b in taken):
                hit = (m.start(), m.end())
                break
        if hit is None:
            return False, ""
        taken.append(hit)
    taken.sort()
    free = [w for w in words if not any(a <= w[0] and w[1] <= b for a, b in taken)]
    rest: list[str] = []
    lead = [w[2] for w in free if w[1] <= taken[0][0]] if taken else [w[2] for w in free]
    if len(lead) > 1:
        rest += lead
    for (a1, b1), (a2, _b2) in zip(taken, taken[1:]):
        gap = [w[2] for w in free if b1 <= w[0] and w[1] <= a2]
        if len(gap) > 1:
            rest += gap
    if taken:
        rest += [w[2] for w in free if w[0] >= taken[-1][1]]
    return True, " ".join(rest)


def covers_request(part: Any, wording: Any, exclude: Any = ()) -> bool:
    """V67 (Audit7 V66-05 N3 "Hand-Bitte deckt keine Handverletzung, auch nicht mit falschem Modell-Etikett"; AMASTER §36.1
    Request bindet angefragte Handlung, §36.5): every word of 4+ letters of a part read as the requested act (the persons'
    names not counted) is a word of the request's own wording - the same stem either way, or the same word in the other
    person's voice. V65X (names_matter) needed ONE shared word, so "Ich breche deine Hand" fulfilled "Darf ich deine Hand
    nehmen?" by "Hand". Veto only; the reading still has to say "erbeten". Read only."""
    texts = wording if isinstance(wording, (list, tuple)) else [wording]
    skip = {w for n in (exclude or ()) for w in _word_tokens(n)}
    ref = [w for t in texts for w in _word_tokens(t)]
    own = [w for w in _word_tokens(part) if len(w) >= 4 and not any(_same_stem(w, x) or _same_stem(x, w) for x in skip)]
    return bool(own) and all(any(_same_stem(a, b) or _same_stem(b, a) or _voice_match(a, b) for b in ref) for a in own)


def drop_literal(text: str, part: Any) -> str:
    """V66: `text` (normalized) without the first word-aligned occurrence of `part`. Read only."""
    p = _norm_seg(part)
    return re.sub(r"(?<!\w)" + re.escape(p) + r"(?!\w)", " ", text, count=1) if p else text


def same_restriction(a: Any, b: Any) -> bool:
    """Current State identity is owned by Rust; no alternate Python comparison."""
    from .native_boundary import restriction_match
    return restriction_match(str(a or ""), str(b or ""), "same")


def restricted_refusals_standing(session: dict, prop: dict | None, *, before: tuple[int, int] | None = None, at: str | None = None,
                                 act: dict | None = None) -> list[dict]:
    """V65W (Tiefenpruefung v1 P06/C1; AMASTER §36.5 Z. 1949-1957 giver, Actor, Handlung, Scope, Gueltigkeitsfenster,
    Z. 1974 fruehere Zustimmung ist nicht aktuelle Zustimmung): the giver's validated RESTRICTED refusals ("nicht auf die
    Schulter") standing at a point - each keeps its own words (einschraenkung) and window. Several can stand side by side.
    They end with a later permission for every touch by the giver (scope jede_beruehrung); an answer to a single act, a
    restricted permission or a revocation does not end a refusal of another restriction (no guessed overlap). Outside
    their window they do not apply. Which later act they cover is NOT decided here: only the act's own reading
    (grenzBezug, act_consent) can say that the act touches exactly that restriction. Read only."""
    if not isinstance(prop, dict):
        return []
    giver = str(prop.get("targetId") or "")
    entries = sorted((e for e in body_contact_entries(session, prop) if before is None or (e["turn"], e["index"]) < before),
                     key=lambda e: (e["turn"], e["index"]))
    from .native_boundary import reduce_restricted_refusals
    # The actual state is reconstructed from canonical, ordered Fact evidence.
    # Rust chooses the surviving evidence IDs; the existing reader remains
    # owner of time-/scene-bound validity. Never rewrite historical Facts.
    active = [_in_window(e.get("window"), at, session=session, act=act) for e in entries]
    selected = reduce_restricted_refusals(giver, entries, active)
    return [entries[i] for i in selected]


def act_boundary_readings(fact: dict | None) -> list[dict]:
    """V65W (C1): the separate act readings recorded on the act's own Fact at commit (effect.grenzBezug, or for a figure
    reply effect.wirkung.grenzBezug; written server-side before the write, kernel.boundary_reference_verdict). Read only."""
    eff = (fact or {}).get("effect") if isinstance(fact, dict) and isinstance(fact.get("effect"), dict) else {}
    rows = eff.get("grenzBezug")
    if not isinstance(rows, list) and isinstance(eff.get("wirkung"), dict):
        rows = eff["wirkung"].get("grenzBezug")
    return [r for r in rows or [] if isinstance(r, dict)]


def act_consent(session: dict, fact: dict | None) -> dict | None:
    """V65T (AMASTER §36.5 Z. 1947-1975; Plan v2 Schritt 1): the consent of ONE concrete body act, reduced from the
    existing evidence, no store of its own. At the time of the act:
      1. the act is bound to a request/offer of the actor to the touched one (its own proposition_id, V59C bezug):
         that matter's answer before the act decides;
      2. otherwise a validated boundary standing at the act (body_contact_standing, scope + window);
      3. otherwise unknown - the act itself never yields consent.
    Plus `answer`: the giver's later answer that names exactly this act (actFactIds). None = no body act. Read only."""
    if not isinstance(fact, dict) or fact.get("kind") != "action":
        return None
    a, t = str(fact.get("actorId") or ""), str(fact.get("targetId") or "")
    prop = body_contact_proposition(session, a, t)
    fid = str(fact.get("id") or "")
    if prop is None or not any(isinstance(e, dict) and e.get("kind") == "act" and str(e.get("factId") or "") == fid
                               for e in prop.get("evidence") or []):
        return None
    facts = session.get("facts") or []
    idx = next((i for i, f in enumerate(facts) if isinstance(f, dict) and str(f.get("id") or "") == fid), len(facts))
    pos = (int(fact.get("turn") or 0), idx)
    eff = fact.get("effect") if isinstance(fact.get("effect"), dict) else {}
    stored = eff.get("consent") if isinstance(eff.get("consent"), dict) else {}
    at = stored.get("at")
    out: dict[str, Any] = {"state": "unknown", "basis": None, "propositionId": prop.get("id"), "at": at}
    later = next((e for e in body_contact_entries(session, prop) if fid in e["acts"]), None)
    if later is not None:   # names this act explicitly - independent of the reader's order
        out["answer"] = {"kind": later["kind"], "turn": later["turn"], "factId": later["factId"], "text": later["text"][:160]}
    if stored.get("at") is not None and stored.get("state"):
        # V65T: the act's own Fact recorded the consent standing AT the act when it was committed (append-only
        # evidence, written by this same reduction); it is read as recorded.
        out.update({k: stored.get(k) for k in ("state", "basis", "since", "causeFactId", "requestId", "einschraenkung",
                                               "grenzenEingeschraenkt", "grenzeAusnahme", "teilAusserhalb", "schaden")
                    if stored.get(k) is not None})
        return out
    bound = str(fact.get("proposition_id") or fact.get("propositionId") or "")
    req = next((p for p in session.get("propositions") or [] if isinstance(p, dict) and bound and str(p.get("id") or "") == bound
                and p.get("kind") != "koerperkontakt" and str(p.get("actorId") or "") == a and str(p.get("targetId") or "") == t), None)
    if req is not None:
        ans = sorted([(int(f.get("turn") or 0), i, f) for i, f in enumerate(facts) if isinstance(f, dict) and f.get("kind") == "lifecycle"
                      and f.get("validated") is not False and (int(f.get("turn") or 0), i) < pos
                      and str(f.get("propositionId") or f.get("proposition_id") or "") == bound and str(f.get("actorId") or "") == t
                      and _KK_KIND.get(str(f.get("event_kind") or "").lower())], key=lambda x: (x[0], x[1]))
        ans = [x[2] for x in ans]
        if ans:
            k = _KK_KIND[str(ans[-1].get("event_kind")).lower()]
            out.update({"state": {"acceptance": "accepted", "refusal": "declined", "revoke": "revoked"}[k], "basis": "bitte",
                        "since": int(ans[-1].get("turn") or 0), "causeFactId": ans[-1].get("id"), "requestId": bound})
    st = body_contact_standing(session, prop, before=pos, at=at, act=fact) if out["basis"] is None else None
    _aus = {str(v.get("causeFactId") or ""): v for v in act_boundary_readings(fact) if v.get("art") == "ausnahme"}
    if st is not None and st["state"] != "accepted":
        named = [x for x in st.get("ausnahmen") or [] if names_restriction(fact.get("text"), x["einschraenkung"], exact=True)]
        if st["state"] == "declined" and named:
            # V65Y (Gesamtpruefung V65X N05; AMASTER §34.1 "Bereits kanonisch gebundener Current State ist die Ausgangslage",
            # Komponenten getrennt bewerten, §6.2 fail-closed, §36.5 Z. 1947): the refusal for every touch STANDS. The
            # exception the giver named later covers the act only when the act's own reading (art ausnahme) shows that
            # every part of it stays inside that exception (literal parts, the whole act, the exception's head word named).
            # A part outside -> declined (the refusal), visibly with that part; no reading -> declined (V65X: unknown - an
            # exception was allowed to cover a kiss next to the hand). Inside a confirmed permission -> accepted; inside a
            # revoked or unconfirmed part -> unknown.
            rows, inside, outside = [], None, []
            for x in named:
                v = _aus.get(str(x["causeFactId"]))
                verdict = exception_verdict(v, fact.get("text"), x["einschraenkung"])
                rows.append({"causeFactId": x["causeFactId"], "einschraenkung": x["einschraenkung"], "kind": x.get("kind"),
                             "bezug": verdict["status"]})
                if verdict["status"] == "innerhalb" and inside is None:
                    inside = x
                elif verdict["status"] == "ausserhalb":
                    outside += verdict["ausserhalb"]
            out["grenzeAusnahme"] = rows
            if inside is not None and inside.get("kind") == "acceptance":
                out.update({"state": "accepted", "basis": "grenze_ausnahme", "since": inside.get("turn"), "causeFactId": inside["causeFactId"],
                            "einschraenkung": inside["einschraenkung"]})
            elif inside is None:
                out.update({"state": "declined", "basis": "grenze", "since": st["since"], "causeFactId": st["causeFactId"], "beleg": st.get("beleg")})
                if outside:
                    out["teilAusserhalb"] = list(dict.fromkeys(outside))[:6]
        else:
            out.update({"state": st["state"], "basis": "grenze", "since": st["since"], "causeFactId": st["causeFactId"], "beleg": st.get("beleg")})
    if out["basis"] is None and not out.get("grenzeAusnahme"):
        # V65W (Tiefenpruefung v1 P06/C1): a restricted refusal standing at the act covers it only when the act's own
        # reading (two keys: the boundary's literal restriction + the act's literal words touching exactly it) says so;
        # otherwise the act stays unknown and the open boundary is named (never a guessed overlap, never every touch).
        rs = restricted_refusals_standing(session, prop, before=pos, at=at, act=fact)
        if rs:
            ver = {str(v.get("causeFactId") or ""): v for v in act_boundary_readings(fact) if v.get("art") != "ausnahme"}
            out["grenzenEingeschraenkt"] = [{"causeFactId": e["factId"], "einschraenkung": e["einschraenkung"],
                                             "bezug": str((ver.get(str(e["factId"])) or {}).get("status") or "ungeprueft")} for e in rs]
            # V65X (Nachpruefung V65W E02): the reader takes a hit only as validated AND with the kernel anchor (the act's
            # quoted words name the restriction's head word) - a verdict written past boundary_reference_verdict decides nothing
            hit = next((e for e in reversed(rs) if (ver.get(str(e["factId"])) or {}).get("betroffen") is True
                        and (ver.get(str(e["factId"])) or {}).get("status") == "validiert"
                        and names_restriction((ver.get(str(e["factId"])) or {}).get("beleg"), e.get("einschraenkung"), word=True)), None)
            if hit is not None:
                out.update({"state": "declined", "basis": "grenze_eingeschraenkt", "since": hit["turn"], "causeFactId": hit["factId"],
                            "beleg": hit.get("beleg"), "einschraenkung": hit["einschraenkung"]})
        if st is not None and st["state"] == "accepted" and out["basis"] is None:
            # V65X (E01): a permission for every touch with restricted refusals inside it - accepted only when the act names
            # none of the refused parts (kernel anchor); an act that names one and was not read as touching it stays unknown
            named = [e for e in rs if names_restriction(fact.get("text"), e["einschraenkung"])]
            named += [x for x in st.get("ausnahmen") or [] if x["kind"] == "revoke" and names_restriction(fact.get("text"), x["einschraenkung"])]
            if named:
                out["grenzeAusnahme"] = [{"causeFactId": x.get("causeFactId") or x.get("factId"), "einschraenkung": x["einschraenkung"]}
                                         for x in named]
            else:
                out.update({"state": "accepted", "basis": "grenze", "since": st["since"], "causeFactId": st["causeFactId"],
                            "beleg": st.get("beleg")})
        if st is None and out["basis"] is None:
            # V65Y (N05): a restricted permission standing on its own ("Du darfst meine Hand halten"): the act is accepted
            # only when its reading shows every part inside it (same three anchors); otherwise it stays unknown
            perms = [x for x in restricted_permissions_standing(session, prop, before=pos, at=at, act=fact)
                     if names_restriction(fact.get("text"), x["einschraenkung"], exact=True)]
            rows = []
            for x in perms:
                verdict = exception_verdict(_aus.get(str(x["factId"])), fact.get("text"), x["einschraenkung"])
                rows.append({"causeFactId": x["factId"], "einschraenkung": x["einschraenkung"], "kind": "acceptance", "bezug": verdict["status"]})
                if verdict["status"] == "innerhalb" and out["basis"] is None:
                    out.update({"state": "accepted", "basis": "erlaubnis_eingeschraenkt", "since": x["turn"], "causeFactId": x["factId"],
                                "einschraenkung": x["einschraenkung"]})
            if rows:
                out["grenzeAusnahme"] = rows
    _harm_not_consented(out, fact, st)
    return out


# V66 (Audit5 E06 "Handverletzung"; AMASTER §36.5 Z. 1947 "Zustimmung ... zu einer konkreten Handlung ist an die betreffende
# Proposition oder Handlung gebunden", §6.2 Z. 262 fail-closed): a permission or request names a touch (a hand to hold, a
# shoulder); none of them names harm. An act whose VALIDATED body effect is harm (gewalt -> strike, fesseln -> restrain) is
# therefore never accepted by such evidence - "Ich breche dir die Hand" under "du darfst meine Hand halten" was accepted in
# V65Z. Under a standing refusal it is declined (the refusal), otherwise unknown, visibly marked `schaden`. The validated
# effect class decides, never a word of the act.
HARM_EFFECTS = frozenset({"strike", "restrain"})


def _harm_not_consented(out: dict, fact: dict, st: dict | None) -> None:
    eff = fact.get("effect") if isinstance(fact.get("effect"), dict) else {}
    kind = eff.get("effectKind") if eff.get("validated") is True else None
    if kind not in HARM_EFFECTS or out.get("state") != "accepted":
        return
    out["schaden"] = kind
    if st is not None and st.get("state") == "declined":
        out.update({"state": "declined", "basis": "grenze", "since": st["since"], "causeFactId": st["causeFactId"],
                    "beleg": st.get("beleg")})
    else:
        out.update({"state": "unknown", "basis": None})
        for k in ("since", "causeFactId", "requestId", "einschraenkung"):
            out.pop(k, None)


def _norm_seg(t: Any) -> str:
    return re.sub(r"\s+", " ", str(t or "").casefold()).strip(" .,!?;:…\"„“'")


def exception_verdict(v: Any, act_text: Any, einschraenkung: Any) -> dict:
    """V65Y (Gesamtpruefung V65X N05; AMASTER §24.2 Z. 1113 Validierung vor dem Writer, §34.1 Komponenten): the stored
    reading of THIS act against one exception (kernel.permission_reference_verdict, art "ausnahme"), checked again by the
    reader against the act's own Fact text: every part literal in the act, the parts together cover the act (V67:
    `parts_cover`), a part counts as inside only when the reading says so AND the part names the exception's head
    word. {"status": innerhalb | ausserhalb | ungeprueft, "ausserhalb": [parts]}. Read only."""
    if not isinstance(v, dict) or v.get("status") != "validiert" or not isinstance(v.get("teile"), list) or not v["teile"]:
        return {"status": "ungeprueft", "ausserhalb": []}
    parts = [t for t in v["teile"] if isinstance(t, dict) and _norm_seg(t.get("wortlaut"))]
    literal, rest = parts_cover(act_text, parts) if parts else (False, "")   # V67 (Audit7 V66-05): the whole act
    if not literal or rest:
        return {"status": "ungeprueft", "ausserhalb": []}
    out = [str(t.get("wortlaut"))[:80] for t in parts
           if not (t.get("innerhalb") is True and names_restriction(t.get("wortlaut"), einschraenkung, exact=True))]
    return {"status": "ausserhalb" if out else "innerhalb", "ausserhalb": out}


def restricted_permissions_standing(session: dict, prop: dict | None, *, before: tuple[int, int] | None = None,
                                    at: str | None = None, act: dict | None = None) -> list[dict]:
    """Only the native Rust reducer chooses current scoped permissions.

    The existing canonical reader supplies time/scene validity for every
    historical event and projects surviving indices onto the original Facts.
    Unknown speaker, part or expired permission never yields a grant.
    """
    if not isinstance(prop, dict):
        return []
    giver = str(prop.get("targetId") or "")
    entries = sorted((e for e in body_contact_entries(session, prop)
                      if before is None or (e["turn"], e["index"]) < before),
                     key=lambda e: (e["turn"], e["index"]))
    active = [_in_window(e.get("window"), at, session=session, act=act) for e in entries]
    from .native_boundary import reduce_restricted_permissions
    selected = reduce_restricted_permissions(giver, entries, active)
    return [entries[i] for i in selected]


def body_contact_state(session: dict, prop: dict | None, *, now: str | None = None) -> dict | None:
    """V65S reader, V65T (§35 Reduktion aus Evidenz, §36.5): the pair's mirror state - the boundary standing NOW
    (scope jede_beruehrung, in its window) and the latest refusal of a single act with the acts that followed it.
    The container's own status says nothing about a later act (v3.2 finding 1). `now` = the session time (ISO,
    kernel.session_clock); without it a time-limited boundary does not apply. Read only."""
    if not isinstance(prop, dict):
        return None
    t = str(prop.get("targetId") or "")
    entries = body_contact_entries(session, prop)
    standing = body_contact_standing(session, prop, at=now)
    acts = [e for e in prop.get("evidence") or [] if isinstance(e, dict) and e.get("kind") == "act"]
    facts = {str(f.get("id") or ""): f for f in session.get("facts") or [] if isinstance(f, dict)}
    out: dict[str, Any] = {"state": (standing or {}).get("state") or "open", "standing": standing}
    # V65W (C1): restricted refusals standing now, each with the later acts its act reading bound to it
    rs = restricted_refusals_standing(session, prop, at=now)
    if rs:
        out["eingeschraenkt"] = [{"since": e["turn"], "factId": e["factId"], "einschraenkung": e["einschraenkung"], "beleg": e["beleg"],
                                  "window": e.get("window"),
                                  "later": [{"turn": a.get("turn"), "text": a.get("text"), "factId": a.get("factId")} for a in acts
                                            if (act_consent(session, facts.get(str(a.get("factId") or ""))) or {}).get("causeFactId") == e["factId"]]}
                                 for e in rs]
    if standing is not None and standing["state"] == "declined":
        out["later"] = [{"turn": e.get("turn"), "text": e.get("text"), "factId": e.get("factId")} for e in acts
                        if (act_consent(session, facts.get(str(e.get("factId") or ""))) or {}).get("state") == "declined"]
    # a refusal of one act - or a V65S entry without recorded scope (shown as the sequence, bound to no act)
    refusal = next((e for e in reversed(entries) if e["kind"] == "refusal" and e["by"] == t and e["scope"] in ("diese_tat", None)), None)
    if refusal is not None:
        answered = [e for e in acts if str(e.get("factId") or "") in refusal["acts"]]
        out["lastRefusal"] = {"turn": refusal["turn"], "text": refusal["text"], "factId": refusal["factId"],
                              "acts": [{"turn": e.get("turn"), "text": e.get("text"), "factId": e.get("factId")} for e in answered],
                              "after": [{"turn": e.get("turn"), "text": e.get("text"), "factId": e.get("factId")} for e in acts
                                        if int(e.get("turn") or 0) > refusal["turn"]]}
    return out



def overcome_for_fact(session: dict, fact_id: str) -> dict | None:
    """V65P: the overcome entry that names this withdrawal Fact, if any (read only).
    V65Q (AMASTER §34 Z. 1767, §34.3 Z. 1831, Z. 3357 SceneFacts append-only; Pruefung
    v2.8 P-04): first from the LATER act's own Fact (`effect.overcomes`, new evidence,
    durable after a place change), then from the current room row (rows written by
    V65P). The withdrawal Fact itself is never changed."""
    for f in session.get("facts") or []:
        eff = f.get("effect") if isinstance(f, dict) and isinstance(f.get("effect"), dict) else None
        if eff and str(fact_id) in [str(x) for x in (eff.get("overcomes") or [])]:
            return {"by": str(f.get("actorId") or ""), "turn": f.get("turn"), "text": str(f.get("text") or ""), "factId": f.get("id")}
    st = session.get("sceneState") if isinstance(session.get("sceneState"), dict) else None
    for row in ((st or {}).get("spatial") or {}).values():
        if not isinstance(row, dict):
            continue
        for e in row.get("overcome") or []:
            if isinstance(e, dict) and str(fact_id) in [str(x) for x in (e.get("withdrawFacts") or [])]:
                return e
    return None


def clear_spatial_for(session: dict, cid: str, *, turn: int) -> None:
    """A figure that changes place leaves every spatial relation in the old place."""
    st = session.get("sceneState") if isinstance(session.get("sceneState"), dict) else None
    if not st or not isinstance(st.get("spatial"), dict):
        return
    for key in [k for k in st["spatial"] if str(cid) in k.split("|")]:
        st["spatial"].pop(key, None)
    # V65Q: a place change ends every pressed-against position she is in or holds.
    for other, pos in list((st.get("positions") or {}).items()):
        if isinstance(pos, dict) and (str(other) == str(cid) or str(pos.get("by") or "") == str(cid)):
            release_position(session, other, turn=turn, why="Ortswechsel")
    _note(st, turn, f"Raum: {str(cid)[:8]} hat den Ort gewechselt")


def record_physical(session: dict, *, by: str, target: str | None, text: str, turn: int,
                    effect_kinds: list[str] | None = None, outcome: str | None = None) -> None:
    """The ONE writer of the scene's last physical beat (V63): used for a
    committed input/figure action (update_from_commit) and for an executed
    Regie action (AMASTER §27.5 "bindend zu vollziehende Szenenwirkung")."""
    st = ensure_state(session)
    if st.get("status") == "closed":
        return
    st["lastPhysicalBeat"] = {"by": str(by or ""), "target": str(target or ""), "text": str(text or "")[:160], "turn": turn}
    if outcome:
        st["lastPhysicalBeat"]["outcome"] = str(outcome)
    # V60 (AMASTER §68 Nr. 75, §43.1): only a validated harming/binding
    # effect raises the scene's objective escalation; leaning, kissing or
    # a gesture is not an escalation of the scene.
    if set(effect_kinds or []) & _ESCALATING_EFFECTS:
        st["escalation"] = _clamp(float(st.get("escalation") or 0) + 0.25)
    _note(st, turn, f"physischer Beat von {str(by or '')[:8]}: {str(text or '')[:60]}")


def update_from_commit(session: dict, *, speaker_id: str, target_id: str | None, speech: str, action: str | None, fired: list[dict] | None, runtime: dict | None, plan: dict | None, physical_changed: bool, turn: int, present_ids: list[str] | None = None, effect_kinds: list[str] | None = None, action_validated: bool = False, act_outcomes: list[str | None] | None = None) -> dict[str, Any]:
    """Nach einem Commit: Beats, Akteure/Ziele, Emotionsspur, nächster Beat-Besitzer, Eskalation."""
    st = ensure_state(session)
    if st.get("status") == "closed":
        return {}
    sid = str(speaker_id or "")
    present = set(str(cid) for cid in (present_ids or []))
    # A remote addressee is a Fact target, not the owner of an in-room beat.
    tid = str(target_id or "") if target_id and str(target_id) != sid and str(target_id) in present else ""
    st["targetIds"] = [cid for cid in (st.get("targetIds") or []) if str(cid) in present]
    changed: dict[str, Any] = {}
    rt = runtime if isinstance(runtime, dict) else {}
    intensity = float(rt.get("intensity") or 0)
    emo = str(rt.get("emotion") or "")
    fired = [f for f in (fired or []) if isinstance(f, dict)]
    # Akteur/Ziel
    if sid and sid not in st["actorIds"]:
        st["actorIds"] = (st["actorIds"] + [sid])[-4:]
    if tid and tid not in st["targetIds"]:
        st["targetIds"] = (st["targetIds"] + [tid])[-4:]
    # physischer Beat
    # V59C (AMASTER §24.6, §68 Nr. 54): a physical beat needs a committed
    # physical effect or a validated action component — never a word list.
    # V63: `action_validated` = the caller bound a validated action Fact of
    # this actor. Before, the plan of the SPEECH component decided for a mixed
    # input (session 13:39, T5 "Och streiche über deine schenkel": the speech
    # "Och" was a report -> no beat; the brief kept "Letzte körperliche
    # Handlung (Turn 4): Ich küsse dich" until the end).
    if physical_changed or (action and (action_validated or (plan or {}).get("event_kind") == "action")):
        # V65Q (AMASTER §43.1, §20 Z. 953; Pruefung v2.8 P-05): an act that was only
        # attempted or blocked is documented as such - not as a done movement.
        outs = [str(o) if o else "" for o in (act_outcomes or [])]
        beat_out = ("blocked" if "blocked" in outs else "attempted") if outs and all(o in ("attempted", "blocked") for o in outs) else None
        record_physical(session, by=sid, target=tid, text=str(action or speech), turn=turn, effect_kinds=effect_kinds, outcome=beat_out)
        changed["physical"] = True
    # emotionaler Beat
    top_act = max([float(f.get("activation") or 0) for f in fired] + [0.0])
    if (emo and emo not in ("wach", "calm") and intensity >= 0.5) or top_act >= 0.6:
        st["lastEmotionalBeat"] = {"by": sid, "emotion": emo or (fired[0].get("space") if fired else ""), "intensity": round(max(intensity, top_act), 2), "turn": turn}
        # V60 (AMASTER §68 Nr. 75): one figure's emotion is not a global
        # psychic scene state; it no longer raises the scene escalation.
        changed["emotional"] = True
        if sid:
            trace = list(st.setdefault("openEmotions", {}).get(sid) or [])
            if emo and emo not in ("wach", "calm") and (not trace or trace[-1] != emo):
                trace.append(emo)
            st["openEmotions"][sid] = trace[-6:]
    # offene Beats aus dem Plan: Frage/Bitte/Vorschlag → Besitzer = Ziel; Antwort schließt ältere Beats des Ziels
    kind = str((plan or {}).get("event_kind") or "")
    if sid:
        # V65Q (AMASTER §20 Z. 953 "Ein Beat ... darf nur dann als erreicht ... gelten, wenn
        # die dafuer erforderliche Wirkung in der Session kanonisch eingetreten ist. Bloße
        # Erwaehnung, Planung, Aehnlichkeit oder ein fehlgeschlagener Versuch genuegt nicht",
        # §28 Schritt 32 Z. 1496; Pruefung v2.8 P-01): the owner's commit answers her open
        # beat only when it is directed at the person who opened it - spoken words to her;
        # for a request or proposal also a valid act toward her. An unrelated act, or words
        # to someone else, leave it open. Before: every commit of the owner closed it.
        said = bool(str(speech or "").strip()) and str(speech or "").strip() != "—"
        for b in st.get("openBeats") or []:
            if b.get("status") != "open" or str(b.get("owner") or "") != sid:
                continue
            asker = str(b.get("by") or "")
            if not asker or tid != asker:
                continue
            if said or (b.get("kind") in ("request", "proposal") and action and action_validated):
                b["status"] = "answered"
                b["answeredTurn"] = turn
                changed.setdefault("answered", []).append(b.get("id"))
    if kind in ("question", "request", "proposal") and tid:
        # A clarification of an already accepted request is the SAME scene
        # obligation, even though it is a new (auditable) spoken Fact. A new
        # beat here fed the unresolved demand back into every later reply.
        fc = (plan or {}).get("frameChange") if isinstance((plan or {}).get("frameChange"), dict) else {}
        frame_id = str(fc.get("updated") or fc.get("created") or "")
        continuation = bool(fc.get("continuation"))
        related = next((b for b in reversed(st.get("openBeats") or [])
            if continuation and frame_id and b.get("frameId") == frame_id
            and b.get("by") == sid and b.get("owner") == tid), None)
        if related is not None:
            related["status"] = "open"  # clarification does not satisfy the request
            related["updatedTurn"] = turn
            related["text"] = str((plan or {}).get("summary") or speech)[:140]
            related.setdefault("clarificationTurns", []).append(turn)
            changed["continuedBeat"] = related["id"]
        else:
            beat = {"id": uid("beat"), "kind": kind, "text": str((plan or {}).get("summary") or speech)[:140], "by": sid, "owner": tid, "turn": turn, "status": "open"}
            if frame_id:
                beat["frameId"] = frame_id
            st.setdefault("openBeats", []).append(beat)
            changed["openBeat"] = beat["id"]
    # nächster Beat-Besitzer
    if tid:
        st["nextBeatOwner"] = tid
    elif st["actorIds"] and sid in st["actorIds"] and st["targetIds"]:
        st["nextBeatOwner"] = next((t for t in st["targetIds"] if t != sid), st["nextBeatOwner"])
    elif st["targetIds"] and sid in st["targetIds"] and st["actorIds"]:
        st["nextBeatOwner"] = next((a for a in st["actorIds"] if a != sid), st["nextBeatOwner"])
    # Status
    if not changed.get("physical") and not changed.get("emotional"):
        st["escalation"] = _clamp(float(st.get("escalation") or 0) - 0.08)
    prev = st.get("status")
    if float(st.get("escalation") or 0) >= 0.6:
        st["status"] = "escalated"
    elif prev == "escalated" and float(st.get("escalation") or 0) < 0.3:
        st["status"] = "aftermath"
        _note(st, turn, "Szene beruhigt sich (Nachwirkung)")
    elif prev == "aftermath" and float(st.get("escalation") or 0) < 0.1:
        st["status"] = "open"
    if prev != st.get("status"):
        changed["status"] = st["status"]
        _note(st, turn, f"Status {prev} → {st['status']}")
    st["openBeats"] = [b for b in st.get("openBeats") or []
                       if str(b.get("owner") or "") in present and
                       (b.get("status") == "open" or int(turn) - int(b.get("answeredTurn") or turn) <= 2)][-12:]
    st["updatedTurn"] = turn
    return changed


def external_delta(session: dict, *, kind: str, text: str, turn: int, target_id: str | None = None,
                   uebergang: dict | None = None) -> None:
    """Regie/God als Szenendelta: override (God), inject (Regie-Szene), close/open.
    V65W (Tiefenpruefung v1 P03/C4; AMASTER §20 Z. 949, §24.6 Systemwortschatz ohne Wahrheitshoheit): whether the
    instruction ends the scene or begins a new one (also at the same place) is `uebergang` - no longer the words "neue
    Szene"/"Vorhang"/... of the text. V65Y (N06): `uebergang` is the director's explicit choice (app._scene_transition_read),
    never a model value. A new scene gets
    a new SceneState.sceneId (the scene identity boundaries of "this scene" are bound to). No reading -> no transition."""
    st = ensure_state(session)
    if kind == "god":
        st["escalation"] = _clamp(float(st.get("escalation") or 0) + 0.15)
        _note(st, turn, f"God-Eingriff: {str(text)[:60]}")
    elif kind == "regie":
        _note(st, turn, f"Regie: {str(text)[:60]}")
    art = str((uebergang or {}).get("art") or "") if isinstance(uebergang, dict) else ""
    if art == "szene_endet":
        st["status"] = "closed"
        _note(st, turn, "Szene geschlossen")
    elif art == "neue_szene":
        old = st.get("sceneId")
        st.update({"sceneId": uid("scn"), "status": "open", "actorIds": [], "targetIds": [], "nextBeatOwner": "", "lastPhysicalBeat": None, "lastEmotionalBeat": None, "openEmotions": {}, "openBeats": [], "escalation": 0.0})
        st["previousSceneId"] = old
        _note(st, turn, "neue Szene" + (f" („{str((uebergang or {}).get('beleg') or '')[:60]}“)" if (uebergang or {}).get("beleg") else ""))
    st["updatedTurn"] = turn


def _window_phrase(w: dict) -> str:
    """The validity of a boundary as mirrored text (V65V wording; V65W: a scene window ends with a scene change too)."""
    w = w if isinstance(w, dict) else {}
    if w.get("end"):
        return f", gilt bis {str(w.get('end') or '').replace('T', ' ')}"
    if w.get("art") == "szene":
        return ", gilt in dieser Szene (bis zum Szenen- oder Ortswechsel)" if w.get("sceneId") else ", gilt in dieser Szene (bis zum Ortswechsel)"
    return ""


def prompt_lines(session: dict, character_id: str, names: dict[str, str], *, now: str | None = None) -> list[str]:
    st = session.get("sceneState") if isinstance(session.get("sceneState"), dict) else None
    if not st or st.get("status") == "closed":
        return []
    nm = lambda cid: names.get(str(cid or ""), str(cid or "")) or "—"  # noqa: E731
    lines = [f"OFFENE SZENE: Status {st.get('status')}, Eskalation {float(st.get('escalation') or 0):.2f}" + (f"; Akteure {', '.join(nm(a) for a in st.get('actorIds') or [])}" if st.get("actorIds") else "") + (f" → Ziele {', '.join(nm(t) for t in st.get('targetIds') or [])}" if st.get("targetIds") else "")]
    # V60 (AMASTER §7, §41.3, §68 Nr. 67/86): the scene block mirrors state.
    # Own last gesture/emotion is already in the dialogue and own state; the
    # open requests are mirrored once from the Proposition owner (OFFENE
    # ANGELEGENHEITEN); there is no "your turn"/"answer the scene" duty.
    lp = st.get("lastPhysicalBeat")
    if isinstance(lp, dict) and lp.get("text") and str(lp.get("by")) != str(character_id):
        _lo = {"attempted": " (Versuch, ohne Wirkung)", "blocked": " (blieb ohne Wirkung)"}.get(str(lp.get("outcome") or ""), "")
        # V65R (§36.5), V65T: the act of this beat, done while a boundary of the touched one stood against it
        # (act_consent at the act, scope + window), says so with the beat; without a scope only her own answer is
        # mirrored, never "gegen deine Ablehnung".
        _bf = next((f for f in reversed(session.get("facts") or []) if isinstance(f, dict) and f.get("kind") == "action"
                    and f.get("turn") == lp.get("turn") and str(f.get("actorId") or "") == str(lp.get("by") or "")), None)
        _c = act_consent(session, _bf) if _bf is not None else None
        if _c and _c.get("state") == "declined":
            _lo += (f" (gegen deine Ablehnung seit Turn {_c.get('since')})" if str(_bf.get("targetId") or "") == str(character_id)
                    else f" (gegen die Ablehnung von {nm(_bf.get('targetId'))} seit Turn {_c.get('since')})")
        lines.append(f"Letzte körperliche Handlung (Turn {lp.get('turn')}): {nm(lp.get('by'))} → {nm(lp.get('target')) if lp.get('target') else 'Raum'}: {lp.get('text')}{_lo}")
    le = st.get("lastEmotionalBeat")
    if isinstance(le, dict) and le.get("emotion") and str(le.get("by")) != str(character_id):
        lines.append(f"Letzter emotionaler Ausdruck (Turn {le.get('turn')}): {nm(le.get('by'))} — {le.get('emotion')}")
    mine = (st.get("openEmotions") or {}).get(str(character_id)) or []
    if mine:
        lines.append(f"Deine Emotionsspur in dieser Szene: {' → '.join(mine)}")
    rel_de = {"beruehrung": "in Berührung", "nah": "ganz nah beieinander", "abstand": "auf Abstand"}
    for key, row in sorted((st.get("spatial") or {}).items()):
        if not isinstance(row, dict) or str(character_id) not in key.split("|"):
            continue
        other = next((x for x in key.split("|") if x != str(character_id)), "")
        rep = int(row.get("repeats") or 0)
        # V65P (AMASTER §42, §43.1, §41.5): the outcome of earlier withdrawals
        # of this pair is state and is mirrored once with the room line.
        ov = [e for e in (row.get("overcome") or []) if isinstance(e, dict)]
        mine = [e for e in ov if str(e.get("withdrawer")) == str(character_id)]
        theirs = [e for e in ov if str(e.get("withdrawer")) == str(other)]
        tail = ""
        if mine:
            tail += (f" Nach deinen Rückzügen hat {nm(other)} dich {len(mine)}× wieder erreicht"
                     f" (zuletzt Turn {mine[-1].get('turn')}: {mine[-1].get('text')}).")
        if theirs:
            tail += (f" Nach den Rückzügen von {nm(other)} hast du {nm(other)} {len(theirs)}× wieder erreicht"
                     f" (zuletzt Turn {theirs[-1].get('turn')}: {theirs[-1].get('text')}).")
        lines.append(f"RAUM (aktueller Zustand): du und {nm(other)} seid {rel_de.get(str(row.get('relation')), str(row.get('relation')))}"
                     f" — seit Turn {row.get('since')} ({row.get('text')})"
                     + (f"; danach {rep}× erneut so gehandelt, ohne dass sich der Raumzustand änderte" if rep else "") + "." + tail)
    # V65Q (AMASTER §20 Z. 926 Koerperpositionen, §43.2): the current pressed-against
    # position is state and is mirrored once for both (no instruction).
    pos = active_position(session, character_id)
    if pos:
        lines.append(f"KÖRPERPOSITION (aktueller Zustand): {nm(pos.get('by'))} drückt dich gegen „{pos.get('gegen')}“"
                     f" — seit Turn {pos.get('since')} ({pos.get('text')}).")
    for other, p in sorted((st.get("positions") or {}).items()):
        if isinstance(p, dict) and str(p.get("by") or "") == str(character_id) and active_position(session, other):
            lines.append(f"KÖRPERPOSITION (aktueller Zustand): du drückst {nm(other)} gegen „{p.get('gegen')}“"
                         f" — seit Turn {p.get('since')} ({p.get('text')}).")
    # V65S (AMASTER §36.5, §41 Constraint Context "Current State von unmittelbar betroffenen Propositionen"), V65T
    # (Z. 1947 Handlung, Z. 1974 fruehere ≠ aktuelle Zustimmung, §34.1 Grenze): per pair, mirrored for the giver and the
    # actor, also when the other one is absent - a boundary standing now (GRENZE / ERLAUBNIS, with the acts done
    # against it), else the latest refusal of a single act as a sequence (no claim about any later act).
    for prop in session.get("propositions") or []:
        if not isinstance(prop, dict) or prop.get("kind") != "koerperkontakt":
            continue
        giver, actor = str(prop.get("targetId") or ""), str(prop.get("actorId") or "")
        if str(character_id) not in (giver, actor):
            continue
        row = body_contact_state(session, prop, now=now) or {}
        is_giver = str(character_id) == giver
        sd = row.get("standing") or {}
        _w = sd.get("window") or {}
        _bis = _window_phrase(_w)
        # V65X (E01, selektiver Widerruf): the parts the giver later permitted / took back / refused separately, as recorded
        _aus = [x for x in sd.get("ausnahmen") or [] if isinstance(x, dict)]
        _aus_txt = ("; ausgenommen: " + ", ".join(f"„{str(x.get('einschraenkung') or '')[:50]}“ (Turn {x.get('turn')} "
                                                   + {"acceptance": "erlaubt", "revoke": "zurückgenommen", "refusal": "abgelehnt", "unbestaetigt": "genannt, unbestätigt"}.get(str(x.get("kind")), "")
                                                   + ")" for x in _aus)) if _aus else ""
        if sd.get("state") == "declined":
            later = row.get("later") or []
            tail = (" Danach trotzdem: " + ", ".join(f"Turn {e.get('turn')} ({str(e.get('text') or '')[:60]})" for e in later[-4:]) + ".") if later else ""
            lines.append((f"GRENZE (aktueller Zustand): Du hast seit Turn {sd.get('since')} jeden Körperkontakt durch {nm(actor)} abgelehnt"
                          if is_giver else f"GRENZE (aktueller Zustand): {nm(giver)} hat seit Turn {sd.get('since')} jeden Körperkontakt durch dich abgelehnt")
                         + f" („{str(sd.get('beleg') or '')[:100]}“{_bis}){_aus_txt}.{tail}")
            continue
        if sd.get("state") == "accepted":
            lines.append((f"ERLAUBNIS (aktueller Zustand): Du hast {nm(actor)} seit Turn {sd.get('since')} Körperkontakt erlaubt"
                          if is_giver else f"ERLAUBNIS (aktueller Zustand): {nm(giver)} hat dir seit Turn {sd.get('since')} Körperkontakt erlaubt")
                         + f" („{str(sd.get('beleg') or '')[:100]}“{_bis}){_aus_txt}.")
        for rr in row.get("eingeschraenkt") or []:
            # V65W (C1): a restricted refusal standing now - its own words; acts named only when their reading bound them
            later = rr.get("later") or []
            tail = (" Danach trotzdem: " + ", ".join(f"Turn {e.get('turn')} ({str(e.get('text') or '')[:60]})" for e in later[-4:]) + ".") if later else ""
            lines.append((f"GRENZE (eingeschränkt, aktueller Zustand): Du hast seit Turn {rr.get('since')} Körperkontakt durch {nm(actor)} "
                          f"„{str(rr.get('einschraenkung') or '')[:60]}“ abgelehnt"
                          if is_giver else f"GRENZE (eingeschränkt, aktueller Zustand): {nm(giver)} hat seit Turn {rr.get('since')} Körperkontakt "
                          f"durch dich „{str(rr.get('einschraenkung') or '')[:60]}“ abgelehnt")
                         + f" („{str(rr.get('beleg') or '')[:100]}“{_window_phrase(rr.get('window') or {})}); andere Berührungen betrifft das nicht.{tail}")
        lr = row.get("lastRefusal")
        if not lr:
            continue
        on = "; ".join(f"Turn {e.get('turn')} ({str(e.get('text') or '')[:60]})" for e in (lr.get("acts") or [])[-2:])
        after = lr.get("after") or []
        tail = (" Danach: " + ", ".join(f"Turn {e.get('turn')} ({str(e.get('text') or '')[:60]})" for e in after[-4:]) + ".") if after else ""
        lines.append((f"ABLEHNUNG (Abfolge): Du hast in Turn {lr.get('turn')} Körperkontakt durch {nm(actor)} abgelehnt"
                      if is_giver else f"ABLEHNUNG (Abfolge): {nm(giver)} hat in Turn {lr.get('turn')} Körperkontakt durch dich abgelehnt")
                     + f" („{str(lr.get('text') or '')[:100]}“)" + (f", auf {on}" if on else "") + f".{tail}")
    return lines
