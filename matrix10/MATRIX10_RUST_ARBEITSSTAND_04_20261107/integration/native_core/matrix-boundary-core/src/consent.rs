//! Read-only reducers over canonical, ordered lifecycle evidence.
//!
//! Contract: AMASTER 34/35/36.2-36.4/37/68, the pinned SPS, and the
//! original repair chain. These reducers neither authorize a new act nor
//! mutate historical Facts. The existing SceneState reader supplies an
//! explicit temporal/scene applicability decision for EVERY event, not just
//! the final surviving refusal. Only the named giver can affect consent.

use crate::boundary::failure;
use crate::restriction::same_restriction;
use crate::value::{object, text, Value};

fn invalid(msg: &str) -> Value {
    failure("NATIVE_CONTRACT_INVALID", msg, 503)
}

#[derive(Clone, Copy)]
struct Evidence<'a> {
    index: usize,
    by: &'a str,
    kind: &'a str,
    scope: &'a str,
    part: &'a str,
    unconfirmed: &'a str,
    active: bool,
}

fn evidence<'a>(request: &'a Value) -> Result<(&'a str, Vec<Evidence<'a>>), Value> {
    let payload = request.get("payload");
    let giver = payload.get("giver").text()
        .filter(|s| !s.is_empty())
        .ok_or_else(|| invalid("consent giver must be a nonempty bound identity"))?;
    let entries = payload.get("entries").list()
        .ok_or_else(|| invalid("consent evidence must be an array"))?;
    let mut result = Vec::with_capacity(entries.len());
    for (index, entry) in entries.iter().enumerate() {
        if entry.map().is_none() {
            return Err(invalid("consent evidence entry must be an object"));
        }
        let by = entry.get("by").text().ok_or_else(|| invalid("consent speaker must be text"))?;
        let kind = entry.get("kind").text().ok_or_else(|| invalid("consent event kind must be text"))?;
        let scope = entry.get("scope").text().ok_or_else(|| invalid("consent scope must be text"))?;
        let part = entry.get("einschraenkung").text()
            .ok_or_else(|| invalid("consent restriction must be text"))?;
        let unconfirmed = entry.get("einschraenkungOffen").text()
            .ok_or_else(|| invalid("consent unconfirmed restriction must be text"))?;
        let active = entry.get("active").boolean()
            .ok_or_else(|| invalid("consent window applicability must be boolean"))?;
        if !["refusal", "acceptance", "revoke"].contains(&kind)
            || !["", "diese_tat", "eingeschraenkt", "jede_beruehrung"].contains(&scope) {
            return Err(invalid("unknown canonical consent kind/scope"));
        }
        result.push(Evidence { index, by, kind, scope, part, unconfirmed, active });
    }
    Ok((giver, result))
}

fn eligible<'a>(giver: &str, e: Evidence<'a>) -> bool {
    // An empty or unrelated actor never becomes the giver by default.
    e.active && e.by == giver
}

fn response(items: Vec<(&str, Value)>) -> Value {
    let mut result = vec![("ok", Value::Bool(true)), ("abi", Value::Integer(crate::ABI_VERSION as i64))];
    result.extend(items);
    object(result)
}

/// Surviving restricted refusal indices. All input events are preserved by
/// the existing writer; the response is only a projection into their order.
/// Inactive (expired / other-scene) events cannot supersede active refusals.
pub fn reduce(request: &Value) -> Value {
    let (giver, entries) = match evidence(request) { Ok(v) => v, Err(v) => return v };
    let mut standing: Vec<(usize, &str)> = Vec::new();
    for e in entries {
        if !eligible(giver, e) { continue; }
        if e.scope == "eingeschraenkt" && !e.part.is_empty() {
            match e.kind {
                "refusal" => {
                    standing.retain(|(_, old)| !same_restriction(old, e.part));
                    standing.push((e.index, e.part));
                }
                "acceptance" | "revoke" => {
                    standing.retain(|(_, old)| !same_restriction(old, e.part));
                }
                _ => unreachable!(),
            }
        } else if e.scope == "jede_beruehrung" && e.kind == "acceptance" {
            standing.clear();
        }
    }
    response(vec![("indices", Value::List(standing.into_iter()
        .map(|(i, _)| Value::Integer(i as i64)).collect()))])
}

/// Surviving restricted permissions: each is an explicit, scoped consent
/// evidence item. Expired, unrelated, or unnamed speakers never grant consent.
/// A later refusal/revocation of that exact part supersedes that permission;
/// a new broad boundary replaces all standalone narrow permissions.
pub fn reduce_permissions(request: &Value) -> Value {
    let (giver, entries) = match evidence(request) { Ok(v) => v, Err(v) => return v };
    let mut standing: Vec<(usize, &str)> = Vec::new();
    for e in entries {
        if !eligible(giver, e) { continue; }
        if e.scope == "eingeschraenkt" && !e.part.is_empty() {
            standing.retain(|(_, old)| !same_restriction(old, e.part));
            if e.kind == "acceptance" { standing.push((e.index, e.part)); }
        } else if e.scope == "jede_beruehrung" {
            standing.clear();
        }
    }
    response(vec![("indices", Value::List(standing.into_iter()
        .map(|(i, _)| Value::Integer(i as i64)).collect()))])
}

/// The standing broad boundary and its selective exceptions, expressed only
/// as indices into the canonical events. The Python adapter projects existing
/// fields (causeFactId, beleg, etc.) without independently deciding state.
pub fn reduce_standing(request: &Value) -> Value {
    let (giver, entries) = match evidence(request) { Ok(v) => v, Err(v) => return v };
    let mut standing: Option<(usize, &str)> = None;
    let mut ended: Option<(usize, usize, &str, &str)> = None;
    let mut exceptions: Vec<(usize, &str, &str)> = Vec::new();
    for e in entries {
        if !eligible(giver, e) { continue; }
        if e.scope == "jede_beruehrung" && ["acceptance", "refusal"].contains(&e.kind) {
            standing = Some((e.index, e.kind));
            ended = None;
            exceptions.clear();
            continue;
        }
        let Some((old_index, broad_kind)) = standing else { continue };
        if broad_kind == "refusal" && !e.unconfirmed.is_empty()
            && ["acceptance", "refusal"].contains(&e.kind) {
            exceptions.retain(|(_, _, part)| !same_restriction(part, e.unconfirmed));
            exceptions.push((e.index, "unbestaetigt", e.unconfirmed));
            continue;
        }
        if e.scope == "eingeschraenkt" && !e.part.is_empty() {
            exceptions.retain(|(_, _, part)| !same_restriction(part, e.part));
            let opposite = (broad_kind == "refusal" && ["acceptance", "revoke"].contains(&e.kind))
                || (broad_kind == "acceptance" && ["refusal", "revoke"].contains(&e.kind));
            if opposite { exceptions.push((e.index, e.kind, e.part)); }
            continue;
        }
        if broad_kind == "refusal" && e.kind == "acceptance" && e.scope == "diese_tat" {
            continue;
        }
        if (broad_kind == "acceptance" && ["refusal", "revoke"].contains(&e.kind))
            || (broad_kind == "refusal" && ["acceptance", "revoke"].contains(&e.kind)) {
            standing = None;
            ended = Some((old_index, e.index, broad_kind, e.kind));
            exceptions.clear();
        }
    }
    let standing_index = standing.map(|(i, _)| Value::Integer(i as i64)).unwrap_or(Value::Null);
    let ending = match ended {
        Some((from, to, _, _)) => Value::List(vec![Value::Integer(from as i64), Value::Integer(to as i64)]),
        None => Value::Null,
    };
    let exception_rows = exceptions.into_iter().map(|(i, kind, _)| {
        object(vec![("index", Value::Integer(i as i64)), ("kind", text(kind))])
    }).collect();
    response(vec![("standing", standing_index), ("ended", ending), ("exceptions", Value::List(exception_rows))])
}

#[cfg(test)]
mod tests {
    use super::*;
    fn e(by: &str, scope: &str, kind: &str, part: &str, open: &str, active: bool) -> Value {
        object(vec![("by", text(by)), ("scope", text(scope)), ("kind", text(kind)),
                    ("einschraenkung", text(part)), ("einschraenkungOffen", text(open)),
                    ("active", Value::Bool(active))])
    }
    fn event(by: &str, scope: &str, kind: &str, part: &str) -> Value { e(by,scope,kind,part,"",true) }
    fn query(rows: Vec<Value>) -> Value {
        object(vec![("payload",object(vec![("giver",text("bob")), ("entries",Value::List(rows))]))])
    }
    fn indices(rows: Vec<Value>) -> Vec<i64> {
        let r = reduce(&query(rows));
        assert_eq!(r.get("ok").boolean(),Some(true));
        r.get("indices").list().unwrap().iter().map(|v|v.integer().unwrap()).collect()
    }
    fn broad(rows: Vec<Value>) -> Value { reduce_standing(&query(rows)) }
    #[test] fn b04_other_side_does_not_revoke() {
        assert_eq!(indices(vec![event("bob","eingeschraenkt","refusal","rechte Hand"),
            event("bob","eingeschraenkt","acceptance","linke Hand")]),vec![0]);
    }
    #[test] fn same_scope_replaces_exact_restriction() {
        assert_eq!(indices(vec![event("bob","eingeschraenkt","refusal","rechte Hand"),
            event("bob","eingeschraenkt","acceptance","meine rechte Hand")]),vec![]);
    }
    #[test] fn different_speaker_cannot_undo_narrow_refusal() {
        assert_eq!(indices(vec![event("bob","eingeschraenkt","refusal","rechte Hand"),
            event("alice","eingeschraenkt","acceptance","rechte Hand")]),vec![0]);
    }
    #[test] fn empty_actor_cannot_undo_narrow_refusal() {
        assert_eq!(indices(vec![event("bob","eingeschraenkt","refusal","rechte Hand"),
            event("","jede_beruehrung","acceptance","")]),vec![0]);
    }
    #[test] fn inactive_acceptance_cannot_undo_narrow_refusal() {
        assert_eq!(indices(vec![event("bob","eingeschraenkt","refusal","rechte Hand"),
            e("bob","eingeschraenkt","acceptance","rechte Hand","",false)]),vec![0]);
    }
    #[test] fn time_expired_refusal_does_not_remain_active() {
        assert_eq!(indices(vec![e("bob","eingeschraenkt","refusal","rechte Hand","",false)]),vec![]);
    }
    #[test] fn no_truncation_after_six_entries() {
        let parts=["Hand","Arm","Schulter","Knie","Fuss","Nase","Ohr","Lippe","Mund","Zehe","Bein"];
        assert_eq!(indices(parts.iter().map(|p|event("bob","eingeschraenkt","refusal",p)).collect()),
                   (0..11).collect::<Vec<i64>>());
    }
    #[test] fn single_act_acceptance_cannot_clear_narrow_refusal() {
        assert_eq!(indices(vec![event("bob","eingeschraenkt","refusal","rechte Hand"),
           event("bob","diese_tat","acceptance","rechte Hand")]),vec![0]);
    }
    #[test] fn broad_acceptance_clears_narrow_refusal() {
        assert_eq!(indices(vec![event("bob","eingeschraenkt","refusal","rechte Hand"),
           event("bob","jede_beruehrung","acceptance","")]),vec![]);
    }
    #[test] fn narrow_permission_is_scoped_to_the_giver() {
        let r=query(vec![event("alice","eingeschraenkt","acceptance","rechte Hand"),
                        event("bob","eingeschraenkt","acceptance","linke Hand")]);
        assert_eq!(reduce_permissions(&r).get("indices").list().unwrap(),&[Value::Integer(1)]);
    }
    #[test] fn expired_narrow_permission_is_not_carried_forward() {
        let r=query(vec![e("bob","eingeschraenkt","acceptance","rechte Hand","",false)]);
        assert_eq!(reduce_permissions(&r).get("indices").list().unwrap(),&[]);
    }
    #[test] fn broad_refusal_ends_prior_standalone_narrow_permission() {
        let r=query(vec![event("bob","eingeschraenkt","acceptance","rechte Hand"),
                        event("bob","jede_beruehrung","refusal","")]);
        assert_eq!(reduce_permissions(&r).get("indices").list().unwrap(),&[]);
    }
    #[test] fn other_part_refusal_keeps_earlier_permission() {
        let r=query(vec![event("bob","eingeschraenkt","acceptance","rechte Hand"),
                        event("bob","eingeschraenkt","refusal","linke Hand")]);
        assert_eq!(reduce_permissions(&r).get("indices").list().unwrap(),&[Value::Integer(0)]);
    }
    #[test] fn same_part_refusal_ends_only_its_permission() {
        let r=query(vec![event("bob","eingeschraenkt","acceptance","rechte Hand"),
                        event("bob","eingeschraenkt","acceptance","linke Hand"),
                        event("bob","eingeschraenkt","refusal","rechte Hand")]);
        assert_eq!(reduce_permissions(&r).get("indices").list().unwrap(),&[Value::Integer(1)]);
    }
    #[test] fn different_speaker_cannot_undo_broad_refusal() {
        let r=broad(vec![event("bob","jede_beruehrung","refusal",""),
                         event("alice","jede_beruehrung","acceptance","")]);
        assert_eq!(r.get("standing").integer(),Some(0));
    }
    #[test] fn expired_broad_acceptance_does_not_undo_broad_refusal() {
        let r=broad(vec![event("bob","jede_beruehrung","refusal",""),
            e("bob","jede_beruehrung","acceptance","","",false)]);
        assert_eq!(r.get("standing").integer(),Some(0));
    }
    #[test] fn broad_accepted_then_revoked_has_historical_end() {
        let r=broad(vec![event("bob","jede_beruehrung","acceptance",""),
                        event("bob","diese_tat","revoke","")]);
        assert_eq!(r.get("standing"),&Value::Null);
        assert_eq!(r.get("ended").list().unwrap(),&[Value::Integer(0),Value::Integer(1)]);
    }
    #[test] fn restricted_permission_is_a_narrow_exception_to_broad_refusal() {
        let r=broad(vec![event("bob","jede_beruehrung","refusal",""),
            event("bob","eingeschraenkt","acceptance","linke Hand")]);
        assert_eq!(r.get("standing").integer(),Some(0));
        assert_eq!(r.get("exceptions").list().unwrap()[0].get("index").integer(),Some(1));
        assert_eq!(r.get("exceptions").list().unwrap()[0].get("kind").text(),Some("acceptance"));
    }
    #[test] fn unknown_exception_is_not_promoted_to_consent() {
        let r=broad(vec![event("bob","jede_beruehrung","refusal",""),
            e("bob","","acceptance","","Hand",true)]);
        assert_eq!(r.get("standing").integer(),Some(0));
        assert_eq!(r.get("exceptions").list().unwrap()[0].get("kind").text(),Some("unbestaetigt"));
    }
    #[test] fn incomplete_window_flag_never_defaults_to_active() {
        let mut row=event("bob","jede_beruehrung","refusal","");
        if let Value::Map(ref mut fields)=row { fields.remove("active"); }
        assert_eq!(reduce_standing(&query(vec![row])).get("code").text(),Some("NATIVE_CONTRACT_INVALID"));
    }
    #[test] fn empty_giver_refused() {
        let r=object(vec![("payload", object(vec![("giver", text("")),
           ("entries", Value::List(vec![]))]))]);
        assert_eq!(reduce(&r).get("ok").boolean(), Some(false));
    }
    #[test] fn invalid_unknown_kind_refused() {
        assert_eq!(reduce(&query(vec![event("bob","eingeschraenkt","guess","Hand")]))
                  .get("code").text(), Some("NATIVE_CONTRACT_INVALID"));
    }
}
