//! One identity/provenance predicate for the EXISTING Matrix10 writers, deletion
//! guard and read-only audit. SQL ownership, transactions and canonical storage
//! remain with repos.py; this module never creates a second state store.
//!
//! Normative: AMASTER original sections 6, 8, 18, 23, 34, 39, 44, 46, 63, 68.
//! Implementation reference: V67 repos.py common boundary, SPS V67/V66/V65Z.
//! IMPORTANT: this is structural validation, NOT semantic effect authorization.

use std::collections::BTreeSet;
use crate::value::{object, text, Value};

const SYSTEM_ACTORS: &[&str] = &["kernel", "god", "regie", "observer"];
const PERSON_KEYS: &[&str] = &[
    "speaker_id", "speakerId", "target_id", "targetId", "input_actor_id",
    "avatar_id", "puppet_id", "response_speaker_id",
];
const PERCEPTION_KEYS: &[&str] = &["present_ids", "hears_ids", "sees_ids"];
const SOURCE_KEYS: &[(&str, &str)] = &[
    ("sourceTurnId", "turnTruth"), ("source_turn_id", "turnTruth"),
    ("responds_to_fact_id", "fact"), ("respondsToFactId", "fact"),
    ("cause_fact_id", "fact"), ("causeFactId", "fact"),
    ("sourceUploadId", "upload"), ("source_upload_id", "upload"),
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Violation {
    pub code: String,
    pub message: String,
    pub status: i64,
}

type Check = Result<(), Violation>;

fn fail(code: &str, message: impl Into<String>) -> Violation {
    Violation { code: code.into(), message: message.into(), status: 422 }
}
fn protocol(message: impl Into<String>) -> Violation {
    Violation { code: "NATIVE_CONTRACT_INVALID".into(), message: message.into(), status: 503 }
}

pub fn failure(code: &str, message: &str, status: i64) -> Value {
    object(vec![
        ("ok", Value::Bool(false)), ("code", text(code)),
        ("message", text(message)), ("status", Value::Integer(status)),
    ])
}
fn outcome(result: Check) -> Value {
    match result {
        Ok(()) => object(vec![("ok", Value::Bool(true)), ("abi", Value::Integer(crate::ABI_VERSION as i64))]),
        Err(e) => failure(&e.code, &e.message, e.status),
    }
}

#[derive(Debug)]
struct UserId(String);
#[derive(Debug)]
struct WorldId(String);
#[derive(Debug)]
struct SessionId(String);

struct Context<'a> {
    // Distinct wrappers prevent accidental substitution inside this core.
    _user: UserId,
    _world: WorldId,
    _session: SessionId,
    cast: BTreeSet<&'a str>,
    operators: BTreeSet<&'a str>,
    sources: &'a Value,
    raw: &'a Value,
}

fn strings<'a>(v: &'a Value, field: &str) -> Result<BTreeSet<&'a str>, Violation> {
    let list = v.list().ok_or_else(|| protocol(format!("{field} must be an array")))?;
    let mut out = BTreeSet::new();
    for x in list {
        let s = x.text().ok_or_else(|| protocol(format!("{field} contains a non-string identity")))?;
        out.insert(s);
    }
    Ok(out)
}

impl<'a> Context<'a> {
    fn read(raw: &'a Value) -> Result<Self, Violation> {
        fn scope(raw: &Value, key: &str) -> Result<String, Violation> {
            let s = raw.get(key).text().filter(|s| !s.is_empty())
                .ok_or_else(|| protocol(format!("server scope {key} missing")))?;
            Ok(s.to_owned())
        }
        Ok(Self {
            _user: UserId(scope(raw, "user_id")?),
            _world: WorldId(scope(raw, "world_id")?),
            _session: SessionId(scope(raw, "session_id")?),
            cast: strings(raw.get("cast"), "cast")?,
            operators: strings(raw.get("operators"), "operators")?,
            sources: raw.get("sources"),
            raw,
        })
    }
    fn bound(&self, v: &Value, system: bool, operator: bool) -> bool {
        match v.text() {
            Some(id) if !id.is_empty() => self.cast.contains(id)
                || (system && SYSTEM_ACTORS.contains(&id))
                || (operator && self.operators.contains(id)),
            _ => false,
        }
    }
    fn has_source(&self, kind: &str, id: &str) -> Result<bool, Violation> {
        Ok(strings(self.sources.get(kind), kind)?.contains(id))
    }
}

fn alias<'a>(p: &'a Value, a: &str, b: &str, code: &str) -> Result<&'a Value, Violation> {
    let first = p.get(a);
    let second = p.get(b);
    if !first.absent() && !second.absent() && first != second {
        return Err(fail(code, format!("conflicting identity aliases {a}/{b}")));
    }
    Ok(if !first.absent() { first } else { second })
}

fn check_sources(ctx: &Context, payload: &Value, keys: &[(&str, &str)], required: bool, code: &str) -> Check {
    let own = payload.get("id").text().unwrap_or("");
    let invalid = code.replace("UNBOUND", "INVALID");
    let mut has_primary_source = false;
    for (key, kind) in keys {
        let v = payload.get(key);
        if v.absent() { continue; }
        let id = v.text().ok_or_else(|| fail(&invalid, format!("source {key} must be a string identity")))?;
        if !ctx.has_source(kind, id)? || (*kind == "fact" && id == own) {
            return Err(fail(&invalid, format!("source {key} is not a {kind} of this session")));
        }
        if *kind == "turnTruth" || *kind == "upload" { has_primary_source = true; }
    }
    if required && !has_primary_source {
        return Err(fail(code, "row needs a TurnTruth or upload of this session; a cause alone is not a source"));
    }
    Ok(())
}

fn fact(ctx: &Context, p: &Value) -> Check {
    let actor = alias(p, "actorId", "actor_id", "FACT_ACTOR_UNBOUND")?;
    if !ctx.bound(actor, true, true) { return Err(fail("FACT_ACTOR_UNBOUND", "fact actor is not bound to this world")); }
    let target = alias(p, "targetId", "target_id", "FACT_TARGET_UNBOUND")?;
    if !target.absent() && !ctx.bound(target, false, true) {
        return Err(fail("FACT_TARGET_UNBOUND", "fact target is not bound to this world"));
    }
    // Both spellings may exist, but may never refer to different canonical rows.
    for (a, b) in [("sourceTurnId", "source_turn_id"), ("sourceUploadId", "source_upload_id"),
                   ("causeFactId", "cause_fact_id"), ("respondsToFactId", "responds_to_fact_id")] {
        alias(p, a, b, "FACT_SOURCE_INVALID")?;
    }
    check_sources(ctx, p, SOURCE_KEYS, true, "FACT_SOURCE_UNBOUND")
}

fn truth(ctx: &Context, p: &Value) -> Check {
    let role = p.get("role").text().unwrap_or("").trim();
    let auth = p.get("authority").text().unwrap_or("").trim();
    if role.is_empty() || auth.is_empty() { return Err(fail("TURNTRUTH_UNBOUND", "turn truth needs role and authority")); }
    alias(p, "speaker_id", "speakerId", "TURNTRUTH_PERSON_UNBOUND")?;
    alias(p, "target_id", "targetId", "TURNTRUTH_PERSON_UNBOUND")?;
    for key in PERSON_KEYS {
        let v = p.get(key);
        if !v.absent() && !ctx.bound(v, true, true) {
            return Err(fail("TURNTRUTH_PERSON_UNBOUND", format!("turn truth {key} is not bound to this world")));
        }
    }
    for key in PERCEPTION_KEYS {
        let v = p.get(key);
        if matches!(v, Value::Null) { continue; }
        // Intentional strengthening: V67 silently skipped a scalar/object here.
        let people = v.list().ok_or_else(|| fail("TURNTRUTH_PERSON_UNBOUND", format!("{key} must be an identity array")))?;
        for who in people {
            if !ctx.bound(who, false, false) {
                return Err(fail("TURNTRUTH_PERSON_UNBOUND", format!("{key} names no figure of this world")));
            }
        }
    }
    let speaker = alias(p, "speaker_id", "speakerId", "TURNTRUTH_PERSON_UNBOUND")?;
    if (auth == "god") != (role == "god")
        || (auth == "god" && !speaker.absent() && speaker.text() != Some("god")) {
        return Err(fail("TURNTRUTH_AUTHORITY", "god authority requires the God role and God speaker"));
    }
    if auth == "regie" && role != "regie" {
        return Err(fail("TURNTRUTH_AUTHORITY", "regie authority requires the Regie role"));
    }
    Ok(())
}

fn god_fact(ctx: &Context, p: &Value) -> Check {
    let source = alias(p, "sourceTurnId", "source_turn_id", "GODFACT_SOURCE_UNBOUND")?;
    let id = source.text().filter(|x| !x.is_empty())
        .ok_or_else(|| fail("GODFACT_SOURCE_UNBOUND", "god fact has no TurnTruth source"))?;
    let tt = ctx.raw.get("god_truth");
    if tt.map().is_none() || ctx.raw.get("god_truth_id").text() != Some(id) {
        return Err(fail("GODFACT_SOURCE_UNBOUND", "god fact source is not a TurnTruth of this session"));
    }
    if tt.get("role").text() != Some("god") || tt.get("authority").text() != Some("god") {
        return Err(fail("GODFACT_AUTHORITY_UNBOUND", "source has no God role/authority"));
    }
    if p.get("scope").text().unwrap_or("").trim().is_empty() {
        return Err(fail("GODFACT_SCOPE_UNBOUND", "god fact needs explicit scope"));
    }
    // The existing kernel's canonical scope resolver remains authoritative in this
    // migration slice. These axes are constructed by the server adapter, not UI.
    let wanted = ctx.raw.get("god_axes");
    for key in ["truthScope", "persistenceScope", "epistemicScope"] {
        if wanted.get(key).absent() { return Err(protocol("canonical God scope axes missing")); }
        if p.get(key) != wanted.get(key) {
            return Err(fail("GODFACT_SCOPE_AXES", "God scope axes disagree with the canonical scope resolver"));
        }
    }
    let target = alias(p, "targetId", "target_id", "GODFACT_TARGET_UNBOUND")?;
    if !target.absent() && !ctx.bound(target, false, false) {
        return Err(fail("GODFACT_TARGET_UNBOUND", "God target must be a figure of this world"));
    }
    Ok(())
}

fn relation(ctx: &Context, p: &Value, opt: &Value) -> Check {
    let from = opt.get("from_id");
    let to = opt.get("to_id");
    if from == to || !ctx.bound(from, false, false) || !ctx.bound(to, false, false) {
        return Err(fail("RELATION_UNBOUND", "directed relationship requires two different figures of this world"));
    }
    let is_new = opt.get("new").boolean().ok_or_else(|| protocol("relationship new flag missing"))?;
    if !is_new { return Ok(()); } // V67 legacy read policy: no rewrite of old provenance.
    let provenance = p.get("provenienz").get("quelle").text().unwrap_or("");
    if ["stamm", "manuell", "duplikat", "import"].contains(&provenance) {
        return Ok(()); // Stamp is supplied only by the existing canonical writer.
    }
    let mut has_origin = false;
    for (key, kind) in [("sourceFactId", "fact"), ("sourceTurnId", "turnTruth")] {
        if !p.get(key).absent() {
            check_sources(ctx, p, &[(key, kind)], false, "RELATION_SOURCE_UNBOUND")?;
            has_origin = true;
        }
    }
    let causes = p.get("appliedCauses");
    if !matches!(causes, Value::Null) {
        let causes = causes.list().ok_or_else(|| fail("RELATION_SOURCE_INVALID", "appliedCauses must be an array"))?;
        for c in causes {
            let id = if c.map().is_some() { c.get("factId") } else { c };
            if id.absent() { continue; }
            let id = id.text().ok_or_else(|| fail("RELATION_SOURCE_INVALID", "cause must name a fact identity"))?;
            if !ctx.has_source("fact", id)? {
                return Err(fail("RELATION_SOURCE_INVALID", "relationship cause is not a fact of this session"));
            }
            has_origin = true;
        }
    }
    if !has_origin { return Err(fail("RELATION_SOURCE_UNBOUND", "relationship has no canonical origin")); }
    Ok(())
}

fn witness(ctx: &Context, p: &Value) -> Check {
    let who = alias(p, "characterId", "character_id", "WITNESS_PERSON_UNBOUND")?;
    if !ctx.bound(who, false, false) {
        return Err(fail("WITNESS_PERSON_UNBOUND", "witness must be a figure of this world"));
    }
    let fid = alias(p, "factId", "fact_id", "WITNESS_FACT_UNBOUND")?;
    if fid.absent() { return Err(fail("WITNESS_FACT_UNBOUND", "witness row has no fact")); }
    let id = fid.text().ok_or_else(|| fail("WITNESS_FACT_INVALID", "witness fact must be a string identity"))?;
    if !ctx.has_source("fact", id)? { return Err(fail("WITNESS_FACT_INVALID", "witness fact is not in this session")); }
    // Perception authorization remains in the existing TurnTruth/Witness writer;
    // existence alone is explicitly NOT claimed to prove who saw/heard the fact.
    Ok(())
}

fn ids(ctx: &Context, p: &Value, opt: &Value, patch: bool) -> Check {
    let keys = strings(opt.get("keys"), "keys")?;
    let required = strings(opt.get("required"), "required")?;
    let system = strings(opt.get("system"), "system")?;
    let code = opt.get("code").text().filter(|s| !s.is_empty()).ok_or_else(|| protocol("identity error code missing"))?;
    let old = opt.get("existing");
    for key in keys {
        let v = p.get(key);
        if patch && (v == old.get(key) || (v.absent() && old.get(key).absent())) { continue; }
        if v.absent() && !required.contains(key) { continue; }
        if !ctx.bound(v, false, false) && !v.text().or_else(|| if matches!(v, Value::Null) { Some("") } else { None }).is_some_and(|id| system.contains(id)) {
            return Err(fail(code, format!("{key} is not an allowed identity of this world")));
        }
    }
    Ok(())
}

fn source_operation(ctx: &Context, p: &Value, opt: &Value) -> Check {
    let raw_keys = opt.get("keys").list().ok_or_else(|| protocol("source keys missing"))?;
    let mut keys = Vec::new();
    for pair in raw_keys {
        let a = pair.list().filter(|a| a.len() == 2).ok_or_else(|| protocol("invalid source key pair"))?;
        let key = a[0].text().ok_or_else(|| protocol("source key is not text"))?;
        let kind = a[1].text().ok_or_else(|| protocol("source kind is not text"))?;
        if !["turnTruth", "fact", "upload"].contains(&kind) { return Err(protocol("unknown source kind")); }
        keys.push((key, kind));
    }
    let required = opt.get("required").boolean().ok_or_else(|| protocol("source required flag missing"))?;
    let code = opt.get("code").text().ok_or_else(|| protocol("source error code missing"))?;
    check_sources(ctx, p, &keys, required, code)
}

fn validate(request: &Value) -> Check {
    if request.map().is_none() { return Err(protocol("request must be an object")); }
    let operation = request.get("operation").text().ok_or_else(|| protocol("operation missing"))?;
    let payload = request.get("payload");
    if payload.map().is_none() { return Err(fail("BOUNDARY_PAYLOAD_INVALID", "canonical payload must be an object")); }
    let ctx = Context::read(request.get("context"))?;
    let options = request.get("options");
    match operation {
        "fact" => fact(&ctx, payload),
        "truth" => truth(&ctx, payload),
        "god" => god_fact(&ctx, payload),
        "relation" => relation(&ctx, payload, options),
        "witness" => witness(&ctx, payload),
        "ids" => ids(&ctx, payload, options, false),
        "patch_ids" => ids(&ctx, payload, options, true),
        "sources" => source_operation(&ctx, payload, options),
        _ => Err(protocol("unsupported boundary operation")),
    }
}

/// Read-only predicate invoked only by the existing consent/restriction reader.
/// A successful predicate is NOT a successful authorization or SQL write.
fn restriction_match(request: &Value) -> Value {
    let payload=request.get("payload");
    let options=request.get("options");
    let (Some(text),Some(restriction),Some(mode))=(payload.get("text").text(),
        payload.get("restriction").text(), options.get("mode").text()) else {
        return failure("NATIVE_CONTRACT_INVALID", "restriction query requires two literal strings and a mode", 503);
    };
    let same=match mode {
        "same" => crate::restriction::same_restriction(text,restriction),
        "exact" => crate::restriction::names_restriction(text,restriction,true,false),
        "word" => crate::restriction::names_restriction(text,restriction,false,true),
        "veto" => crate::restriction::names_restriction(text,restriction,false,false),
        _ => return failure("NATIVE_CONTRACT_INVALID", "unknown restriction query mode", 503),
    };
    object(vec![("ok",Value::Bool(true)), ("abi",Value::Integer(crate::ABI_VERSION as i64)), ("match",Value::Bool(same))])
}

pub fn evaluate(request: &Value) -> Value {
    if request.get("operation").text() == Some("restricted_refusals") {
        return crate::consent::reduce(request);
    }
    if request.get("operation").text() == Some("body_contact_standing") {
        return crate::consent::reduce_standing(request);
    }
    if request.get("operation").text() == Some("restricted_permissions") {
        return crate::consent::reduce_permissions(request);
    }
    if request.get("operation").text() == Some("restriction_match") {
        return restriction_match(request);
    }
    outcome(validate(request))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn list(items: &[&str]) -> Value { Value::List(items.iter().map(|s| text(*s)).collect()) }
    fn context() -> Value {
        object(vec![
            ("user_id", text("usr_A")), ("world_id", text("world_A")), ("session_id", text("session_A")),
            ("cast", list(&["alice", "bob"])), ("operators", list(&["user", "operator"])),
            ("sources", object(vec![("turnTruth", list(&["tt_A"])), ("fact", list(&["f_A"])), ("upload", list(&["up_A"]))])),
        ])
    }
    fn request(op: &str, payload: Value, options: Value) -> Value {
        object(vec![("operation", text(op)), ("context", context()), ("payload", payload), ("options", options)])
    }
    fn f() -> Value { object(vec![("id", text("f_new")), ("actorId", text("alice")), ("targetId", text("bob")), ("sourceTurnId", text("tt_A"))]) }
    fn replace(v: &mut Value, k: &str, x: Value) { if let Value::Map(m) = v { m.insert(k.into(), x); } else { panic!("map required"); } }
    fn code(r: Value) -> String { evaluate(&r).get("code").text().unwrap_or("OK").to_owned() }
    fn truth_row() -> Value {
        object(vec![("role", text("avatar")), ("authority", text("avatar")), ("speaker_id", text("alice")), ("present_ids", list(&["alice", "bob"]))])
    }
    #[test] fn valid_fact() { assert_eq!(code(request("fact", f(), Value::Null)), "OK"); }
    #[test] fn restriction_query_is_not_a_writer_authorization() {
        let query=request("restriction_match",object(vec![("text",text("rechte Hand")),
            ("restriction",text("linke Hand"))]),object(vec![("mode",text("same"))]));
        let r=evaluate(&query);
        assert_eq!(r.get("ok").boolean(),Some(true));
        assert_eq!(r.get("match").boolean(),Some(false));
        // A query is never accepted by the ordinary writer operation switch.
        assert_eq!(validate(&query).err().unwrap().code,"NATIVE_CONTRACT_INVALID");
    }
    #[test] fn restriction_query_fails_closed_for_missing_mode() {
        let query=request("restriction_match",object(vec![("text",text("rechte Hand")),
            ("restriction",text("linke Hand"))]),Value::Null);
        let r=evaluate(&query);
        assert_eq!(r.get("ok").boolean(),Some(false));
        assert_eq!(r.get("code").text(),Some("NATIVE_CONTRACT_INVALID"));
    }
    #[test] fn restriction_query_explicit_side_is_accepted_only_in_its_own_scope() {
        let query=request("restriction_match",object(vec![("text",text("deine rechte Hand")),
            ("restriction",text("rechte Hand"))]),object(vec![("mode",text("exact"))]));
        assert_eq!(evaluate(&query).get("match").boolean(),Some(true));
    }

    #[test] fn rejects_fact_id_as_turn_truth() { let mut p=f(); replace(&mut p,"sourceTurnId",text("f_A")); assert_eq!(code(request("fact",p,Value::Null)),"FACT_SOURCE_INVALID"); }
    #[test] fn rejects_foreign_session_source() { let mut p=f(); replace(&mut p,"sourceTurnId",text("tt_B")); assert_eq!(code(request("fact",p,Value::Null)),"FACT_SOURCE_INVALID"); }
    #[test] fn correct_source_does_not_hide_wrong_source() { let mut p=f(); replace(&mut p,"sourceUploadId",text("up_B")); assert_eq!(code(request("fact",p,Value::Null)),"FACT_SOURCE_INVALID"); }
    #[test] fn cause_alone_is_not_source() { let mut p=f(); replace(&mut p,"sourceTurnId",Value::Null); replace(&mut p,"cause_fact_id",text("f_A")); assert_eq!(code(request("fact",p,Value::Null)),"FACT_SOURCE_UNBOUND"); }
    #[test] fn self_cause_is_invalid() { let mut p=f(); replace(&mut p,"id",text("f_A")); replace(&mut p,"cause_fact_id",text("f_A")); assert_eq!(code(request("fact",p,Value::Null)),"FACT_SOURCE_INVALID"); }
    #[test] fn upload_is_valid_primary_source() { let mut p=f(); replace(&mut p,"sourceTurnId",Value::Null); replace(&mut p,"sourceUploadId",text("up_A")); assert_eq!(code(request("fact",p,Value::Null)),"OK"); }
    #[test] fn real_user_id_is_not_figure() { let mut p=f(); replace(&mut p,"actorId",text("usr_A")); assert_eq!(code(request("fact",p,Value::Null)),"FACT_ACTOR_UNBOUND"); }
    #[test] fn kernel_operator_is_not_real_user_id() { let mut p=f(); replace(&mut p,"actorId",text("user")); assert_eq!(code(request("fact",p,Value::Null)),"OK"); }
    #[test] fn authority_is_not_target_figure() { let mut p=f(); replace(&mut p,"targetId",text("god")); assert_eq!(code(request("fact",p,Value::Null)),"FACT_TARGET_UNBOUND"); }
    #[test] fn conflicting_actor_alias_rejected() { let mut p=f(); replace(&mut p,"actor_id",text("bob")); assert_eq!(code(request("fact",p,Value::Null)),"FACT_ACTOR_UNBOUND"); }
    #[test] fn equal_aliases_accepted() { let mut p=f(); replace(&mut p,"actor_id",text("alice")); assert_eq!(code(request("fact",p,Value::Null)),"OK"); }
    #[test] fn turn_truth_valid() { assert_eq!(code(request("truth",truth_row(),Value::Null)),"OK"); }
    #[test] fn scalar_perception_rejected() { let mut p=truth_row(); replace(&mut p,"present_ids",text("outsider")); assert_eq!(code(request("truth",p,Value::Null)),"TURNTRUTH_PERSON_UNBOUND"); }
    #[test] fn foreign_witness_rejected() { let mut p=truth_row(); replace(&mut p,"hears_ids",list(&["foreign"])); assert_eq!(code(request("truth",p,Value::Null)),"TURNTRUTH_PERSON_UNBOUND"); }
    #[test] fn god_authority_cannot_be_forged_by_avatar() { let mut p=truth_row(); replace(&mut p,"authority",text("god")); assert_eq!(code(request("truth",p,Value::Null)),"TURNTRUTH_AUTHORITY"); }
    #[test] fn god_cannot_speak_as_character_via_alias() { let p=object(vec![("role",text("god")),("authority",text("god")),("speakerId",text("alice"))]); assert_eq!(code(request("truth",p,Value::Null)),"TURNTRUTH_AUTHORITY"); }
    #[test] fn directed_relation_requires_two_figures() { let opt=object(vec![("from_id",text("alice")),("to_id",text("alice")),("new",Value::Bool(false))]); assert_eq!(code(request("relation",object(vec![]),opt)),"RELATION_UNBOUND"); }
    #[test] fn relation_cannot_use_user_as_character() { let opt=object(vec![("from_id",text("alice")),("to_id",text("user")),("new",Value::Bool(false))]); assert_eq!(code(request("relation",object(vec![]),opt)),"RELATION_UNBOUND"); }
    #[test] fn new_relation_needs_origin() { let opt=object(vec![("from_id",text("alice")),("to_id",text("bob")),("new",Value::Bool(true))]); assert_eq!(code(request("relation",object(vec![]),opt)),"RELATION_SOURCE_UNBOUND"); }
    #[test] fn relation_accepts_canonical_cause() { let opt=object(vec![("from_id",text("alice")),("to_id",text("bob")),("new",Value::Bool(true))]); let p=object(vec![("appliedCauses",list(&["f_A"]))]); assert_eq!(code(request("relation",p,opt)),"OK"); }
    #[test] fn witness_requires_local_fact() { let p=object(vec![("characterId",text("bob")),("factId",text("foreign"))]); assert_eq!(code(request("witness",p,Value::Null)),"WITNESS_FACT_INVALID"); }
    #[test] fn witness_operator_has_no_figure_memory() { let p=object(vec![("characterId",text("user")),("factId",text("f_A"))]); assert_eq!(code(request("witness",p,Value::Null)),"WITNESS_PERSON_UNBOUND"); }
    #[test] fn witness_valid() { let p=object(vec![("characterId",text("bob")),("factId",text("f_A"))]); assert_eq!(code(request("witness",p,Value::Null)),"OK"); }
    #[test] fn patch_keeps_unchanged_legacy_identity() { let p=object(vec![("characterId",text("legacy"))]); let opt=object(vec![("keys",list(&["characterId"])),("required",list(&[])),("system",list(&[])),("code",text("MEMORY_OWNER_UNBOUND")),("existing",p.clone())]); assert_eq!(code(request("patch_ids",p,opt)),"OK"); }
    #[test] fn patch_cannot_change_to_foreign_identity() { let p=object(vec![("characterId",text("foreign"))]); let opt=object(vec![("keys",list(&["characterId"])),("required",list(&[])),("system",list(&[])),("code",text("MEMORY_OWNER_UNBOUND")),("existing",object(vec![("characterId",text("alice"))]))]); assert_eq!(code(request("patch_ids",p,opt)),"MEMORY_OWNER_UNBOUND"); }
    #[test] fn unsupported_operation_never_succeeds() { assert_eq!(code(request("unknown",f(),Value::Null)),"NATIVE_CONTRACT_INVALID"); }
    #[test] fn no_first_six_limit_in_perception_validation() { let mut p=truth_row(); let mut people=vec![text("alice");8]; people.push(text("foreign")); replace(&mut p,"sees_ids",Value::List(people)); assert_eq!(code(request("truth",p,Value::Null)),"TURNTRUTH_PERSON_UNBOUND"); }
    #[test] fn boolean_never_counts_as_identity() { let mut p=f(); replace(&mut p,"actorId",Value::Bool(true)); assert_eq!(code(request("fact",p,Value::Null)),"FACT_ACTOR_UNBOUND"); }
    fn god_request() -> Value {
        let p=object(vec![("sourceTurnId",text("tt_A")),("scope",text("scene")),
            ("truthScope",text("szene")),("persistenceScope",text("session")),
            ("epistemicScope",text("anwesende")),("targetId",text("alice"))]);
        let mut req=request("god",p,Value::Null);
        let mut ctx=context();
        replace(&mut ctx,"god_truth_id",text("tt_A"));
        replace(&mut ctx,"god_truth",object(vec![("role",text("god")),("authority",text("god"))]));
        replace(&mut ctx,"god_axes",object(vec![("truthScope",text("szene")),
            ("persistenceScope",text("session")),("epistemicScope",text("anwesende"))]));
        replace(&mut req,"context",ctx); req
    }
    #[test] fn god_scope_matches_canonical_kernel() { assert_eq!(code(god_request()),"OK"); }
    #[test] fn god_scope_does_not_silently_become_global() {
        let mut req=god_request(); let mut p=req.get("payload").clone();
        replace(&mut p,"truthScope",text("welt")); replace(&mut req,"payload",p);
        assert_eq!(code(req),"GODFACT_SCOPE_AXES");
    }
    #[test] fn god_needs_real_source_row() {
        let mut req=god_request(); let mut ctx=req.get("context").clone();
        replace(&mut ctx,"god_truth",Value::Null); replace(&mut req,"context",ctx);
        assert_eq!(code(req),"GODFACT_SOURCE_UNBOUND");
    }
    #[test] fn god_needs_source_authority_not_just_a_turn_id() {
        let mut req=god_request(); let mut ctx=req.get("context").clone();
        replace(&mut ctx,"god_truth",truth_row()); replace(&mut req,"context",ctx);
        assert_eq!(code(req),"GODFACT_AUTHORITY_UNBOUND");
    }
    #[test] fn god_target_cannot_be_operator() {
        let mut req=god_request(); let mut p=req.get("payload").clone();
        replace(&mut p,"targetId",text("user")); replace(&mut req,"payload",p);
        assert_eq!(code(req),"GODFACT_TARGET_UNBOUND");
    }
    #[test] fn god_needs_explicit_scope() {
        let mut req=god_request(); let mut p=req.get("payload").clone();
        replace(&mut p,"scope",text("")); replace(&mut req,"payload",p);
        assert_eq!(code(req),"GODFACT_SCOPE_UNBOUND");
    }
    #[test] fn source_aliases_cannot_disagree() {
        let mut p=f(); replace(&mut p,"source_turn_id",text("tt_B"));
        assert_eq!(code(request("fact",p,Value::Null)),"FACT_SOURCE_INVALID");
    }
    #[test] fn unknown_source_kind_is_a_contract_error() {
        let opt=object(vec![("keys",Value::List(vec![Value::List(vec![text("sourceTurnId"),text("anything")])])),
            ("required",Value::Bool(true)),("code",text("FACT_SOURCE_UNBOUND"))]);
        assert_eq!(code(request("sources",f(),opt)),"NATIVE_CONTRACT_INVALID");
    }

}
