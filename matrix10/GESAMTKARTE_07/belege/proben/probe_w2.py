"""Probe W2 on kernel level (no route): which actor/TurnTruth pairs does the lifecycle binding produce?"""
import copy, os, sys, json
ROOT = sys.argv[1]
sys.path.insert(0, ROOT)
from matrix_api import kernel as K
from matrix_api import scene_state as SC

J, M = "char_j", "char_m"
def base():
    return {"id": "ses", "worldId": "w", "userId": "admin", "avatarId": J, "turnIndex": 2,
            "scene": {"presentIds": [J, M]}, "facts": [], "turnTruths": [], "propositions": [], "goals": [], "runtimes": {}}

# TurnTruth A (turn 1): Mara asks Johann (Mara is input? no: Mara's response turn) - speaker Mara
ttA = {"id": "ttA", "role": "teilnehmer", "speaker_id": M, "input_actor_id": J, "avatar_id": J}
# TurnTruth B (turn 2): avatar Johann answers; response speaker planned = Mara (prepare binds the NPC response speaker)
ttB = {"id": "ttB", "role": "teilnehmer", "speaker_id": M, "input_actor_id": J, "avatar_id": J}

def scenario(with_fact_id: bool, johann_answer: bool):
    s = base(); s["turnTruths"] = [ttA, ttB]
    s["facts"].append({"id": "fM", "kind": "speech", "actorId": M, "targetId": J, "text": "Kommst du mit ins Kino?",
                       "turn": 1, "sourceTurnId": "ttA", "validated": True})
    s["propositions"].append({"id": "p1", "kind": "request", "actorId": M, "targetId": J, "status": "open", "text": "Kino"})
    if johann_answer:
        s["facts"].append({"id": "fJ", "kind": "speech", "actorId": J, "targetId": M, "text": "Ja, gern.",
                           "turn": 2, "sourceTurnId": "ttB", "validated": True})
    out = K.apply_proposition(s, actor_id=J, text="Ja, gern.", kind="acceptance", target_id=M, proposition_id="p1",
                              fact_id=("fJ" if with_fact_id else None), turn=2)
    lf = [f for f in out["facts"] if f.get("kind") == "lifecycle"]
    for f in lf:
        tt = next((t for t in out["turnTruths"] if t["id"] == f.get("sourceTurnId")), {})
        print(json.dumps({"with_fact_id": with_fact_id, "johann_answer_fact": johann_answer, "lf_actor": f.get("actorId"),
                          "responds_to": f.get("responds_to_fact_id"), "sourceTurnId": f.get("sourceTurnId"), "turn": f.get("turn"),
                          "tt_speaker": tt.get("speaker_id"), "tt_input_actor": tt.get("input_actor_id"),
                          "lifecycle_bound": SC.lifecycle_bound(out, f),
                          "stamped_fM_prop": next(x for x in out["facts"] if x["id"] == "fM").get("propositionId"),
                          "prop_status": out["propositions"][0]["status"]}, ensure_ascii=False))
    if not lf:
        print("no lifecycle", with_fact_id, johann_answer, out["propositions"][0]["status"])

scenario(True, True)    # product path: avatar input, fact id given
scenario(False, True)   # positional: Johann's own fact exists
scenario(False, False)  # positional: only Mara's speech TO Johann exists -> W2
