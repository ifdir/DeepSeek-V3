//! Literal restriction identity and noun-anchored scope (AMASTER 24.2, 34.1, 36.5).
//! No semantic permission, model inference, state, or separate store lives here.

const DETERMINERS: &[&str] = &[
    "der","die","das","den","dem","des","ein","eine","einen","einem","einer","eines",
    "mein","meine","meinen","meinem","meiner","meines",
    "dein","deine","deinen","deinem","deiner","deines",
    "sein","seine","seinen","seinem","seiner","seines",
    "ihr","ihre","ihren","ihrem","ihrer","ihres",
    "unser","unsere","unseren","unserem","unserer","unseres",
    "euer","eure","euren","eurem","eurer","eures",
];

fn words(s: &str) -> Vec<String> {
    let mut result = vec![];
    let mut word = String::new();
    for ch in s.chars().flat_map(char::to_lowercase) {
        match ch {
            'a'..='z' | '0'..='9' => word.push(ch),
            'ä' => word.push('a'), 'ö' => word.push('o'), 'ü' => word.push('u'),
            'ß' => word.push_str("ss"),
            _ => if !word.is_empty() { result.push(std::mem::take(&mut word)); },
        }
    }
    if !word.is_empty() { result.push(word); }
    result
}
fn same_stem(a: &str, b: &str) -> bool {
    // AMASTER 24: explicit numeric part qualifiers must not be normalized away.
    // Finger 1 != Finger 10 and segment-A1 != segment-A2.
    if a.bytes().any(|c| c.is_ascii_digit()) || b.bytes().any(|c| c.is_ascii_digit()) {
        return a == b;
    }
    let n = if a.len() <= 3 { a.len() } else { (a.len()-2).max(3) };
    b.len() >= n && b.as_bytes()[..n] == a.as_bytes()[..n]
}
fn same_word(a: &str, b: &str) -> bool {
    same_stem(a,b) && a.len().abs_diff(b.len()) <= 2
}
fn voice_match(a: &str, b: &str) -> bool {
    if a.bytes().any(|c| c.is_ascii_digit()) || b.bytes().any(|c| c.is_ascii_digit()) {
        return a == b;
    }
    same_word(a,b) || (a.len() == b.len() && a.len() >= 4 && a.as_bytes()[1..] == b.as_bytes()[1..])
}
fn determiner(w: &str) -> bool { DETERMINERS.contains(&w) }

#[derive(Debug)]
struct Parts { head: Option<String>, attrs: Vec<String> }
fn parts(s: &str) -> Parts {
    let toks=words(s);
    if toks.is_empty() { return Parts { head: None, attrs: vec![] }; }
    let end = toks.len()-1;
    let start = toks[..end].iter().position(|t| determiner(t)).map(|i|i+1).unwrap_or(0);
    let attrs = toks[start..end].iter().filter(|t| t.len() >= 4 && !determiner(t)).cloned().collect();
    Parts { head: toks.last().cloned(), attrs }
}
fn qualifiers_at<'a>(toks: &'a [String], index: usize) -> Vec<&'a str> {
    let mut out=vec![];
    for offset in 1..=index.min(4) {
        let w=toks[index-offset].as_str();
        if determiner(w) || w.len() < 4 { break; }
        out.push(w);
    }
    out
}
fn attribute_conflict(text: &str, restriction: &str) -> bool {
    let p=parts(restriction);
    let Some(head) = p.head.as_deref() else { return false; };
    if p.attrs.is_empty() { return false; }
    let toks=words(text);
    let heads: Vec<_> = toks.iter().enumerate().filter_map(|(i,t)|
        if same_word(head,t) {Some(i)} else {None}).collect();
    !heads.is_empty() && heads.iter().all(|i| {
        let q=qualifiers_at(&toks,*i);
        !q.is_empty() && !p.attrs.iter().all(|a| q.iter().any(|x| voice_match(a,x)))
    })
}

/// Same literal qualified part; a bare adjective is NOT a determiner.
pub fn same_restriction(a: &str, b: &str) -> bool {
    let x=parts(a); let y=parts(b);
    let (Some(ha),Some(hb))=(x.head.as_deref(),y.head.as_deref()) else {return false;};
    (same_word(ha,hb)||same_word(hb,ha))
        && x.attrs.iter().all(|a| y.attrs.iter().any(|b|voice_match(a,b)))
        && y.attrs.iter().all(|b| x.attrs.iter().any(|a|voice_match(b,a)))
}

/// A literal anchor, NOT an authorization. `exact` requires the qualifier next
/// to the SAME noun, never borrowed from a different action component.
pub fn names_restriction(text: &str, restriction: &str, exact: bool, word: bool) -> bool {
    let p=parts(restriction);
    let Some(head)=p.head.as_deref() else {return false;};
    let toks=words(text);
    if !toks.iter().any(|t| if exact||word {same_word(head,t)} else {same_stem(head,t)}) {
        return false;
    }
    if exact {
        return toks.iter().enumerate().any(|(i,t)| same_word(head,t)
            && p.attrs.iter().all(|a| qualifiers_at(&toks,i).iter().any(|q|voice_match(a,q))));
    }
    !attribute_conflict(text,restriction)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn b04_opposite_sides_are_distinct() {
        for (a,b) in [("rechte Hand","linke Hand"),("die rechte Hand","meine linke Hand"),
                      ("meine rechte Hand","meine linke Hand"),("Hand","rechte Hand")] {
            assert!(!same_restriction(a,b), "{a} and {b} are distinct");
        }
    }
    #[test] fn same_scope_across_articles_and_grammatical_voice() {
        for (a,b) in [("rechte Hand","meine rechte Hand"), ("die linke Hand","deine linke Hand"),
                      ("meiner rechten Hand","mit deiner rechten Hand"),("die Schulter","meine Schulter")]{
            assert!(same_restriction(a,b),"{a} vs {b}");
            assert!(same_restriction(b,a),"{b} vs {a}");
        }
    }
    #[test] fn no_compound_identity() {
        assert!(!same_restriction("die Schulter","meine Schultertasche"));
        assert!(!same_restriction("meine Hand","die Handtasche"));
    }
    #[test] fn adjective_from_other_component_never_authorizes() {
        let text="Ich halte deine rechte Hand und beruehre deinen linken Arm";
        assert!(!names_restriction(text,"meine linke Hand",true,false));
        assert!(!names_restriction(text,"meine linke Hand",false,true));
        assert!(names_restriction(text,"meine rechte Hand",true,false));
    }
    #[test] fn uncertain_scope_does_not_grant_permission() {
        assert!(!names_restriction("deine Hand","rechte Hand",true,false));
        assert!(names_restriction("deine Hand","rechte Hand",false,true));
        assert!(!names_restriction("deine rechte Hand","linke Hand",false,true));
    }
    #[test] fn explicit_numbered_parts_are_distinct() {
        assert!(!same_restriction("Finger 1", "Finger 2"));
        assert!(!same_restriction("Finger 1", "Finger 10"));
        assert!(same_restriction("meinen Finger 1", "Finger 1"));
        assert!(!names_restriction("Ich beruehre Finger 10", "Finger 1", true, false));
        assert!(names_restriction("Ich beruehre Finger 1", "Finger 1", true, false));
    }
    #[test] fn v66_compound_veto_preserved() {
        assert!(names_restriction("deine Schultertasche","meine Schulter",false,false));
        assert!(!names_restriction("deine Schultertasche","meine Schulter",false,true));
    }
}
