import sys, json, os, tempfile
root = sys.argv[1]
sys.path.insert(0, root)
os.environ.pop("ANTHROPIC_API_KEY", None)
from matrix_api.app import create_app
db = os.path.join(tempfile.mkdtemp(), "p.db")
app = create_app(db)
c = app.test_client()
H = {"X-Matrix-Actor": "u1", "Content-Type": "application/json"}
def r(m, u, b=None, h=H):
    resp = getattr(c, m)(u, data=json.dumps(b) if b is not None else None, headers=h)
    try:
        j = resp.get_json()
    except Exception:
        j = None
    return resp.status_code, j
out = {}
out["user"] = r("post", "/api/users", {"id": "u1", "name": "U", "language": "en"})[0]
out["world"] = r("post", "/api/worlds", {"id": "w1", "name": "W", "places": [{"id": "p1", "name": "Stube"}], "canon": "K0", "factions": [{"name": "F"}]})[0]
mara = {"id": "c1", "worldId": "w1", "name": "Mara", "isWorldNative": True, "personality": "P_ALT", "fears": ["Dunkel"], "goals": ["Ziel_A"], "canBeAvatar": False,
        "compass": {"Angst": {"space": "Angst", "stance": 0.5, "threshold": 0.3, "reaction": "R_ANGST", "bodyCue": "", "drive": "D"}}, "canon": ["CANON_X"], "species": "Elf"}
alr = {"id": "c2", "worldId": "w1", "name": "Alrik", "isWorldNative": True, "canBeAvatar": False}
out["c1"] = r("post", "/api/characters", mara)[0]
out["c2"] = r("post", "/api/characters", alr)[0]
out["patch"] = r("patch", "/api/characters/c1", {"personality": "P_NEU", "goals": ["Ziel_B"]})[0]
st, ch = r("get", "/api/characters/c1")
out["reload_personality"] = ch.get("personality") if ch else None
before = json.dumps(ch, sort_keys=True)
# avatar c2 although canBeAvatar False
st, s = r("post", "/api/sessions", {"id": "s1", "worldId": "w1", "avatarId": "c2", "presentIds": ["c1"]})
out["session_with_nonavatar"] = st
sess = (s or {}).get("session") or {}
out["session_goals"] = [g.get("text") for g in sess.get("goals") or []]
out["runtime_fear_c1"] = (sess.get("runtimes") or {}).get("c1", {}).get("fear")
st, ch2 = r("get", "/api/characters/c1")
out["stem_unchanged_after_session"] = json.dumps(ch2, sort_keys=True) == before
# stem edit after session start
r("patch", "/api/characters/c1", {"personality": "P_DRITT", "goals": ["Ziel_C"]})
st, s2 = r("get", "/api/sessions/s1")
out["running_session_goals_after_stem_edit"] = [g.get("text") for g in ((s2 or {}).get("goals") or (s2 or {}).get("session", {}).get("goals") or [])]
# formulation spiegel via canonical_formulation_context: use kernel.prepare_turn directly on stored state
from matrix_api import kernel
st, ch3 = r("get", "/api/characters/c1")
sess2 = s2.get("session") if isinstance(s2, dict) and "session" in s2 else s2
st, wd = r("get", "/api/worlds/w1")
truth = kernel.bind_from_session(sess2, role="teilnehmer", authority="character", speaker_id="c1", target_id=None, input_kind="autochat", text="Ich habe Angst im Dunkel")
prep = kernel.prepare_turn(sess2, truth=truth, speaker=ch3, present=[ch3], world=wd)
sp = prep["spiegel"]
out["spiegel_personality"] = sp["profile"].get("personality")
out["spiegel_compassLens"] = [x.get("space") for x in sp.get("compassLens") or []]
out["spiegel_fired"] = [(x.get("space"), x.get("activation")) for x in sp.get("fired") or []]
out["spiegel_has_canon"] = sp["profile"].get("relevantCanon")
from matrix_api.llm_contract import render_persona_brief
brief = render_persona_brief(sp, "Ich habe Angst im Dunkel", "Alrik", "")
out["brief_has_P_DRITT"] = "P_DRITT" in brief
out["brief_has_CANON_X"] = "CANON_X" in brief
out["brief_has_Elf"] = "Elf" in brief
out["brief_has_K0_worldcanon"] = "K0" in brief
out["brief_has_faction_F"] = "F" in [w for w in brief.split()]
out["brief_has_R_ANGST"] = "R_ANGST" in brief
out["brief_Ziel_C"] = "Ziel_C" in brief
ranked = kernel.rank_speakers(sess2, [ch3], "Dunkel Angst", natives=[ch3])
out["rank"] = [(x.get("id"), x.get("score"), x.get("reasons")) for x in ranked] if isinstance(ranked, list) else str(ranked)[:300]
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
