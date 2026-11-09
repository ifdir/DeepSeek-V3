//! Private, bounded in-process transport. No database, cache, network or truth owner.
//! The transport preserves JSON types: a boolean is never a turn number, a scalar
//! is never an identity list. Limits fail explicitly, never truncate components.

use std::collections::BTreeMap;

pub const MAGIC: &[u8; 6] = b"MXRB\x01\x00";
pub const MAX_BYTES: usize = 32 * 1024 * 1024;
const MAX_DEPTH: usize = 64;
const MAX_NODES: usize = 1_000_000;

#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Integer(i64),
    Float(f64),
    Text(String),
    List(Vec<Value>),
    Map(BTreeMap<String, Value>),
}

static NULL: Value = Value::Null;

impl Value {
    pub fn get(&self, key: &str) -> &Value {
        match self {
            Value::Map(m) => m.get(key).unwrap_or(&NULL),
            _ => &NULL,
        }
    }
    pub fn has(&self, key: &str) -> bool {
        matches!(self, Value::Map(m) if m.contains_key(key))
    }
    pub fn text(&self) -> Option<&str> {
        if let Value::Text(s) = self { Some(s) } else { None }
    }
    pub fn list(&self) -> Option<&[Value]> {
        if let Value::List(v) = self { Some(v) } else { None }
    }
    pub fn map(&self) -> Option<&BTreeMap<String, Value>> {
        if let Value::Map(m) = self { Some(m) } else { None }
    }
    pub fn integer(&self) -> Option<i64> {
        if let Value::Integer(n) = self { Some(*n) } else { None }
    }
    pub fn boolean(&self) -> Option<bool> {
        if let Value::Bool(b) = self { Some(*b) } else { None }
    }
    pub fn absent(&self) -> bool {
        matches!(self, Value::Null) || matches!(self, Value::Text(s) if s.is_empty())
    }
}

pub fn text(s: impl Into<String>) -> Value { Value::Text(s.into()) }
pub fn object(items: Vec<(&str, Value)>) -> Value {
    Value::Map(items.into_iter().map(|(k, v)| (k.to_owned(), v)).collect())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CodecError(pub &'static str);

type Result<T> = std::result::Result<T, CodecError>;

struct Decoder<'a> {
    data: &'a [u8],
    pos: usize,
    nodes: usize,
}

impl<'a> Decoder<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8]> {
        let end = self.pos.checked_add(n).ok_or(CodecError("length overflow"))?;
        if end > self.data.len() { return Err(CodecError("truncated frame")); }
        let bytes = &self.data[self.pos..end];
        self.pos = end;
        Ok(bytes)
    }
    fn u32(&mut self) -> Result<usize> {
        let mut n = [0; 4];
        n.copy_from_slice(self.take(4)?);
        Ok(u32::from_le_bytes(n) as usize)
    }
    fn string(&mut self) -> Result<String> {
        let len = self.u32()?;
        let bytes = self.take(len)?;
        String::from_utf8(bytes.to_vec()).map_err(|_| CodecError("invalid UTF-8"))
    }
    fn value(&mut self, depth: usize) -> Result<Value> {
        if depth > MAX_DEPTH { return Err(CodecError("nesting limit")); }
        self.nodes += 1;
        if self.nodes > MAX_NODES { return Err(CodecError("node limit")); }
        let tag = self.take(1)?[0];
        match tag {
            0 => Ok(Value::Null),
            1 => Ok(Value::Bool(false)),
            2 => Ok(Value::Bool(true)),
            3 => {
                let mut n = [0; 8]; n.copy_from_slice(self.take(8)?);
                Ok(Value::Integer(i64::from_le_bytes(n)))
            }
            4 => {
                let mut n = [0; 8]; n.copy_from_slice(self.take(8)?);
                let f = f64::from_le_bytes(n);
                if !f.is_finite() { return Err(CodecError("non-finite number")); }
                Ok(Value::Float(f))
            }
            5 => Ok(Value::Text(self.string()?)),
            6 => {
                let n = self.u32()?;
                if n > MAX_NODES - self.nodes || n > self.data.len() - self.pos {
                    return Err(CodecError("impossible list length"));
                }
                let mut a = Vec::with_capacity(n);
                for _ in 0..n { a.push(self.value(depth + 1)?); }
                Ok(Value::List(a))
            }
            7 => {
                let n = self.u32()?;
                if n > MAX_NODES - self.nodes || n > (self.data.len() - self.pos) / 5 {
                    return Err(CodecError("impossible map length"));
                }
                let mut m = BTreeMap::new();
                for _ in 0..n {
                    let key = self.string()?;
                    if m.contains_key(&key) { return Err(CodecError("duplicate key")); }
                    m.insert(key, self.value(depth + 1)?);
                }
                Ok(Value::Map(m))
            }
            _ => Err(CodecError("unknown value tag")),
        }
    }
}

pub fn decode(data: &[u8]) -> Result<Value> {
    if data.len() > MAX_BYTES { return Err(CodecError("frame size limit")); }
    if !data.starts_with(MAGIC) { return Err(CodecError("unsupported protocol")); }
    let mut d = Decoder { data, pos: MAGIC.len(), nodes: 0 };
    let v = d.value(0)?;
    if d.pos != data.len() { return Err(CodecError("trailing bytes")); }
    Ok(v)
}

fn put_len(out: &mut Vec<u8>, n: usize) -> Result<()> {
    let n = u32::try_from(n).map_err(|_| CodecError("length overflow"))?;
    out.extend_from_slice(&n.to_le_bytes());
    Ok(())
}
fn put_string(out: &mut Vec<u8>, s: &str) -> Result<()> {
    put_len(out, s.len())?;
    if out.len().saturating_add(s.len()) > MAX_BYTES { return Err(CodecError("frame size limit")); }
    out.extend_from_slice(s.as_bytes());
    Ok(())
}
fn put(out: &mut Vec<u8>, v: &Value, depth: usize, nodes: &mut usize) -> Result<()> {
    if depth > MAX_DEPTH { return Err(CodecError("nesting limit")); }
    *nodes += 1;
    if *nodes > MAX_NODES { return Err(CodecError("node limit")); }
    match v {
        Value::Null => out.push(0),
        Value::Bool(false) => out.push(1),
        Value::Bool(true) => out.push(2),
        Value::Integer(n) => { out.push(3); out.extend_from_slice(&n.to_le_bytes()); }
        Value::Float(f) => {
            if !f.is_finite() { return Err(CodecError("non-finite number")); }
            out.push(4); out.extend_from_slice(&f.to_le_bytes());
        }
        Value::Text(s) => { out.push(5); put_string(out, s)?; }
        Value::List(a) => {
            out.push(6); put_len(out, a.len())?;
            for x in a { put(out, x, depth + 1, nodes)?; }
        }
        Value::Map(m) => {
            out.push(7); put_len(out, m.len())?;
            for (k, v) in m { put_string(out, k)?; put(out, v, depth + 1, nodes)?; }
        }
    }
    if out.len() > MAX_BYTES { return Err(CodecError("frame size limit")); }
    Ok(())
}

pub fn encode(value: &Value) -> Result<Vec<u8>> {
    let mut out = MAGIC.to_vec();
    let mut nodes = 0;
    put(&mut out, value, 0, &mut nodes)?;
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn all_json_types_roundtrip() {
        let v = object(vec![
            ("n", Value::Null), ("b", Value::Bool(true)),
            ("i", Value::Integer(-42)), ("f", Value::Float(0.125)),
            ("unicode", text("Gr\u{fc}\u{df}e \u{1f44b}")),
            ("a", Value::List(vec![text("x"), Value::Bool(false)])),
        ]);
        assert_eq!(decode(&encode(&v).unwrap()).unwrap(), v);
    }
    #[test]
    fn every_truncated_prefix_fails() {
        let frame = encode(&object(vec![("scope", text("session-A"))])).unwrap();
        for end in 0..frame.len() { assert!(decode(&frame[..end]).is_err()); }
    }
    #[test]
    fn rejects_trailing_and_non_finite() {
        let mut frame = encode(&Value::Null).unwrap(); frame.push(0);
        assert!(decode(&frame).is_err());
        assert!(encode(&Value::Float(f64::NAN)).is_err());
    }
    #[test]
    fn boolean_is_not_integer() { assert_eq!(Value::Bool(true).integer(), None); }
    #[test]
    fn rejects_duplicate_keys() {
        let mut frame = MAGIC.to_vec();
        frame.extend_from_slice(&[7, 2, 0, 0, 0, 1, 0, 0, 0, b'x', 0, 1, 0, 0, 0, b'x', 0]);
        assert!(decode(&frame).is_err());
    }
}
