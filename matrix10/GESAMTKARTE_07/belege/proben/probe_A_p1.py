import sys, json
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1]+"/tests")
import test_v84_kausal_chain as K
from matrix_api import kernel, god_extract as ge
s,_,_ = K.scene("Probe")
figs = K.NATIVES
for txt in ["Mara ist traurig.", "Mara ist die Schwester von Johann Bruckner.", "Mara Nowak kennt Johann Bruckner seit der Schulzeit.", "Der König hat ein neues Gesetz erlassen.", "Mara Nowak setzt sich."]:
    ins, unc = ge.local_god_instructions(txt, figs, s["scene"]["presentIds"])
    print("LOCAL", txt, "->", [(i["art"], ge.ART_TO_SCOPE.get(i["art"]), i.get("targetName"), i.get("otherName")) for i in ins], unc)
# relationship write neutral text
out = kernel.apply_god(s, "Mara ist die Schwester von Johann.", "relationship", K.MARA["id"], other_id=K.JOHANN["id"], natives=figs)
r = [x for x in out["relations"] if x["fromId"]==K.MARA["id"] and x["toId"]==K.JOHANN["id"]]
print("REL", r)
out2 = kernel.apply_god(s, "Mara ist traurig.", "character", K.MARA["id"], natives=figs)
print("CHAR ownerWrites", out2.get("_godOwnerWrites"), out2["godFacts"][-1].get("persistenceScope"))
out3 = kernel.apply_god(s, "Der König hat ein neues Gesetz erlassen.", "world", None, natives=figs)
print("WORLD ownerWrites", out3.get("_godOwnerWrites"))
# autochat gate
g = kernel.autochat_gate(s, figs, 2)
print("GATE", {k:g.get(k) for k in ("stop","reason","speakerId")}, [(c["name"],c["score"],c["reasons"]) for c in g.get("candidates") or []])
s2 = dict(s); s2["propositions"]=[{"status":"open","text":"Treffen am Samstag","time_window":"Samstag","targetId":"x"},{"status":"open","text":"oder Sonntag","time_window":"Sonntag","targetId":"y"}]
print("STOP_SAMSTAG", kernel.autchat_should_stop(s2, figs, remaining_turns=2))
s3 = dict(s); s3["propositions"]=[{"status":"open","text":"Treffen am Freitag","time_window":"Freitag 18 Uhr","targetId":"x"},{"status":"open","text":"Treffen Freitag 18 Uhr woanders","time_window":"Freitag 18 Uhr","targetId":"y"}]
print("STOP_FREITAG", kernel.autchat_should_stop(s3, figs, remaining_turns=2))
print("RESIGN", kernel._derive_fate({"facts":[{"authority":"avatar","kind":"speech","text":"Ich kündige.","actorId":"u"}],"avatarId":"u"}, {}))
