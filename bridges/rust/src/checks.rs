// RFC 6901 JSON Pointer, cross-bridge equality, relational bounds, and stub synthesis (SPEC §§9, 25, D224, D253).

use crate::json::JsonValue;
use std::collections::BTreeMap;

const REL_KEYS: &[&str] = &[
    "min",
    "max",
    "min_len",
    "max_len",
    "non_empty",
    "le_field",
    "ge_field",
    "eq_field",
    "in",
    "not_in",
    "contains",
    "prefix",
    "suffix",
    "sum_fields",
    "allowed_keys",
    "forbid_keys",
];

pub fn escape_pointer(seg: &str) -> String {
    seg.replace('~', "~0").replace('/', "~1")
}

pub fn unescape_pointer(seg: &str) -> String {
    seg.replace("~1", "/").replace("~0", "~")
}

pub fn normalize_pointer(raw: &str) -> String {
    if raw.is_empty() {
        return String::new();
    }
    if raw.starts_with('/') {
        if let Some(colon) = raw.find(':') {
            if colon > 1 && raw.as_bytes().get(colon + 1) == Some(&b'/') {
                return raw[colon + 1..].to_string();
            }
        }
        return raw.to_string();
    }
    if let Some(colon) = raw.find(':') {
        if colon > 0 && raw.as_bytes().get(colon + 1) == Some(&b'/') {
            return raw[colon + 1..].to_string();
        }
    }
    format!("/{}", escape_pointer(raw))
}

pub fn resolve_pointer<'a>(root: &'a JsonValue, ptr: &str) -> Option<&'a JsonValue> {
    let norm = normalize_pointer(ptr);
    if norm.is_empty() {
        return Some(root);
    }
    if !norm.starts_with('/') {
        return None;
    }
    let mut cur = root;
    for raw_seg in norm[1..].split('/') {
        let seg = unescape_pointer(raw_seg);
        match cur {
            JsonValue::Object(map) => {
                cur = map.get(&seg)?;
            }
            JsonValue::Array(arr) => {
                let idx: usize = seg.parse().ok()?;
                if seg != idx.to_string() || idx >= arr.len() {
                    return None;
                }
                cur = arr.get(idx)?;
            }
            _ => return None,
        }
    }
    Some(cur)
}

pub fn write_pointer(root: &mut BTreeMap<String, JsonValue>, ptr: &str, val: JsonValue) {
    let norm = normalize_pointer(ptr);
    if !norm.starts_with('/') || norm == "/" {
        return;
    }
    let segs: Vec<String> = norm[1..].split('/').map(unescape_pointer).collect();
    write_pointer_segs(root, &segs, val);
}

fn write_pointer_segs(cur: &mut BTreeMap<String, JsonValue>, segs: &[String], val: JsonValue) {
    let Some((head, tail)) = segs.split_first() else {
        return;
    };
    if tail.is_empty() {
        cur.insert(head.clone(), val);
        return;
    }
    let mut child = match cur.get(head) {
        Some(JsonValue::Object(existing)) => existing.clone(),
        _ => BTreeMap::new(),
    };
    write_pointer_segs(&mut child, tail, val);
    cur.insert(head.clone(), JsonValue::Object(child));
}

pub fn values_equal(a: &JsonValue, b: &JsonValue) -> bool {
    match (a, b) {
        (JsonValue::Bool(ba), JsonValue::Bool(bb)) => ba == bb,
        (JsonValue::Bool(_), _) | (_, JsonValue::Bool(_)) => false,
        (JsonValue::Number(na), JsonValue::Number(nb)) => {
            na.is_finite() && nb.is_finite() && (na - nb).abs() <= 1e-9
        }
        (JsonValue::Null, JsonValue::Null) => true,
        (JsonValue::Null, _) | (_, JsonValue::Null) => false,
        (JsonValue::Str(sa), JsonValue::Str(sb)) => sa == sb,
        (JsonValue::Array(aa), JsonValue::Array(ab)) => {
            aa.len() == ab.len()
                && aa
                    .iter()
                    .zip(ab.iter())
                    .all(|(va, vb)| values_equal(va, vb))
        }
        (JsonValue::Object(ma), JsonValue::Object(mb)) => {
            ma.len() == mb.len()
                && ma
                    .iter()
                    .all(|(k, va)| mb.get(k).is_some_and(|vb| values_equal(va, vb)))
        }
        _ => false,
    }
}

pub fn is_relational_table(v: &JsonValue) -> bool {
    let Some(map) = v.as_object() else {
        return false;
    };
    !map.is_empty() && map.keys().all(|k| REL_KEYS.contains(&k.as_str()))
}

fn resolve_peer_target<'a>(
    doc: &'a JsonValue,
    proj_then: &BTreeMap<String, String>,
    reference: &str,
) -> Option<&'a JsonValue> {
    let ptr = if reference.starts_with('/') {
        reference.to_string()
    } else if let Some(mapped) = proj_then.get(reference) {
        mapped.clone()
    } else {
        format!("/{}", escape_pointer(reference))
    };
    resolve_pointer(doc, &ptr)
}

pub fn check_relational_leaf(
    doc: &JsonValue,
    actual: &JsonValue,
    rel: &BTreeMap<String, JsonValue>,
    proj_then: &BTreeMap<String, String>,
    pred: &str,
) -> Result<(), String> {
    if rel.contains_key("allowed_keys") || rel.contains_key("forbid_keys") {
        let act_obj = actual
            .as_object()
            .ok_or_else(|| format!("{}: expected JSON object for allowed_keys/forbid_keys", pred))?;
        if let Some(ak_v) = rel.get("allowed_keys") {
            let arr = ak_v
                .as_array()
                .ok_or_else(|| format!("{}: invalid allowed_keys", pred))?;
            let allowed: std::collections::BTreeSet<&str> =
                arr.iter().filter_map(|v| v.as_str()).collect();
            for act_k in act_obj.keys() {
                if !allowed.contains(act_k.as_str()) {
                    return Err(format!(
                        "{}: unexpected key \"{}\" outside allowed_keys",
                        pred, act_k
                    ));
                }
            }
        }
        if let Some(fk_v) = rel.get("forbid_keys") {
            if let Some(arr) = fk_v.as_array() {
                for fk in arr.iter().filter_map(|v| v.as_str()) {
                    if act_obj.contains_key(fk) {
                        return Err(format!("{}: forbidden key \"{}\" present on {}", pred, fk, pred));
                    }
                }
            } else if let Some(fk_s) = fk_v.as_str() {
                if !act_obj.contains_key(fk_s) {
                    return Err(format!("{}: drop-forbid-key mutant on forbid_keys killed", pred));
                }
            } else {
                return Err(format!("{}: invalid forbid_keys", pred));
            }
        }
        return Ok(());
    }
    if let Some(ni_v) = rel.get("not_in") {
        if matches!(actual, JsonValue::Null) {
            return Err(format!("{}: expected non-null value for not_in", pred));
        }
        if let Some(arr) = ni_v.as_array() {
            if arr.iter().any(|item| values_equal(actual, item)) {
                return Err(format!(
                    "{}: forbidden value {} in not_in",
                    pred,
                    actual.to_json_string()
                ));
            }
        } else if !values_equal(actual, ni_v) {
            return Err(format!("{}: pick-forbidden-value mutant on not_in killed", pred));
        }
    }
    if let Some(min_v) = rel.get("min") {
        let af = actual
            .as_f64()
            .ok_or_else(|| format!("{}: expected finite number for min", pred))?;
        let mf = min_v
            .as_f64()
            .ok_or_else(|| format!("{}: invalid min bound", pred))?;
        if af < mf - 1e-9 {
            return Err(format!("{}: {} < min {}", pred, af, mf));
        }
    }
    if let Some(max_v) = rel.get("max") {
        let af = actual
            .as_f64()
            .ok_or_else(|| format!("{}: expected finite number for max", pred))?;
        let mf = max_v
            .as_f64()
            .ok_or_else(|| format!("{}: invalid max bound", pred))?;
        if af > mf + 1e-9 {
            return Err(format!("{}: {} > max {}", pred, af, mf));
        }
    }
    if let Some(ml_v) = rel.get("min_len") {
        let ml = ml_v
            .as_f64()
            .ok_or_else(|| format!("{}: invalid min_len", pred))? as usize;
        let al = match actual {
            JsonValue::Str(s) => s.chars().count(),
            JsonValue::Array(a) => a.len(),
            _ => return Err(format!("{}: expected string or array for min_len", pred)),
        };
        if al < ml {
            return Err(format!("{}: length {} < min_len {}", pred, al, ml));
        }
    }
    if let Some(xl_v) = rel.get("max_len") {
        let xl = xl_v
            .as_f64()
            .ok_or_else(|| format!("{}: invalid max_len", pred))? as usize;
        let al = match actual {
            JsonValue::Str(s) => s.chars().count(),
            JsonValue::Array(a) => a.len(),
            _ => return Err(format!("{}: expected string or array for max_len", pred)),
        };
        if al > xl {
            return Err(format!("{}: length {} > max_len {}", pred, al, xl));
        }
    }
    if let Some(ne_v) = rel.get("non_empty") {
        if ne_v.as_bool() == Some(true) {
            let empty = match actual {
                JsonValue::Str(s) => s.is_empty(),
                JsonValue::Array(a) => a.is_empty(),
                JsonValue::Object(m) => m.is_empty(),
                _ => true,
            };
            if empty {
                return Err(format!("{}: expected non_empty value", pred));
            }
        }
    }
    if let Some(in_v) = rel.get("in") {
        let arr = in_v
            .as_array()
            .ok_or_else(|| format!("{}: invalid in array", pred))?;
        if !arr.iter().any(|item| values_equal(actual, item)) {
            return Err(format!(
                "{}: {} not in allowed set",
                pred,
                actual.to_json_string()
            ));
        }
    }
    if let Some(c_v) = rel.get("contains") {
        match actual {
            JsonValue::Str(s) => {
                let needle = c_v
                    .as_str()
                    .ok_or_else(|| format!("{}: contains on string requires string", pred))?;
                if !s.contains(needle) {
                    return Err(format!("{}: '{}' does not contain '{}'", pred, s, needle));
                }
            }
            JsonValue::Array(arr) => {
                if !arr.iter().any(|item| values_equal(item, c_v)) {
                    return Err(format!("{}: array does not contain expected item", pred));
                }
            }
            _ => return Err(format!("{}: expected string or array for contains", pred)),
        }
    }
    if let Some(p_v) = rel.get("prefix") {
        let s = actual
            .as_str()
            .ok_or_else(|| format!("{}: expected string for prefix", pred))?;
        let pfx = p_v
            .as_str()
            .ok_or_else(|| format!("{}: invalid prefix", pred))?;
        if !s.starts_with(pfx) {
            return Err(format!("{}: '{}' does not start with '{}'", pred, s, pfx));
        }
    }
    if let Some(s_v) = rel.get("suffix") {
        let s = actual
            .as_str()
            .ok_or_else(|| format!("{}: expected string for suffix", pred))?;
        let sfx = s_v
            .as_str()
            .ok_or_else(|| format!("{}: invalid suffix", pred))?;
        if !s.ends_with(sfx) {
            return Err(format!("{}: '{}' does not end with '{}'", pred, s, sfx));
        }
    }
    if let Some(le_v) = rel.get("le_field") {
        let ref_name = le_v
            .as_str()
            .ok_or_else(|| format!("{}: invalid le_field", pred))?;
        let peer = resolve_peer_target(doc, proj_then, ref_name)
            .ok_or_else(|| format!("{}: missing le_field target '{}'", pred, ref_name))?;
        let af = actual
            .as_f64()
            .ok_or_else(|| format!("{}: non-numeric value for le_field", pred))?;
        let pf = peer
            .as_f64()
            .ok_or_else(|| format!("{}: non-numeric peer '{}' for le_field", pred, ref_name))?;
        if af > pf + 1e-9 {
            return Err(format!("{}: {} > le_field {} ({})", pred, af, ref_name, pf));
        }
    }
    if let Some(ge_v) = rel.get("ge_field") {
        let ref_name = ge_v
            .as_str()
            .ok_or_else(|| format!("{}: invalid ge_field", pred))?;
        let peer = resolve_peer_target(doc, proj_then, ref_name)
            .ok_or_else(|| format!("{}: missing ge_field target '{}'", pred, ref_name))?;
        let af = actual
            .as_f64()
            .ok_or_else(|| format!("{}: non-numeric value for ge_field", pred))?;
        let pf = peer
            .as_f64()
            .ok_or_else(|| format!("{}: non-numeric peer '{}' for ge_field", pred, ref_name))?;
        if af < pf - 1e-9 {
            return Err(format!("{}: {} < ge_field {} ({})", pred, af, ref_name, pf));
        }
    }
    if let Some(eq_v) = rel.get("eq_field") {
        let ref_name = eq_v
            .as_str()
            .ok_or_else(|| format!("{}: invalid eq_field", pred))?;
        let peer = resolve_peer_target(doc, proj_then, ref_name)
            .ok_or_else(|| format!("{}: missing eq_field target '{}'", pred, ref_name))?;
        if !values_equal(actual, peer) {
            return Err(format!("{}: does not equal eq_field '{}'", pred, ref_name));
        }
    }
    if let Some(sf_v) = rel.get("sum_fields") {
        let af = actual
            .as_f64()
            .ok_or_else(|| format!("{}: expected finite number for sum_fields", pred))?;
        let arr = sf_v
            .as_array()
            .ok_or_else(|| format!("{}: invalid sum_fields array", pred))?;
        let mut sum = 0.0;
        for item in arr {
            let ref_name = item
                .as_str()
                .ok_or_else(|| format!("{}: invalid sum_fields entry", pred))?;
            let peer = resolve_peer_target(doc, proj_then, ref_name)
                .ok_or_else(|| format!("{}: missing sum_fields peer '{}'", pred, ref_name))?;
            let pf = peer.as_f64().ok_or_else(|| {
                format!("{}: non-numeric sum_fields peer '{}'", pred, ref_name)
            })?;
            sum += pf;
        }
        let rounded_sum = (sum * 1e12).round() / 1e12;
        if (af - rounded_sum).abs() > 1e-9 {
            return Err(format!(
                "{}: {} != sum_fields {}",
                pred, af, rounded_sum
            ));
        }
    }
    Ok(())
}

pub fn synthesize_leaf_witness(
    expected: &JsonValue,
    built_root: &BTreeMap<String, JsonValue>,
    proj_then: &BTreeMap<String, String>,
) -> JsonValue {
    if !is_relational_table(expected) {
        return expected.clone();
    }
    let Some(rel) = expected.as_object() else {
        return expected.clone();
    };
    let doc = JsonValue::Object(built_root.clone());
    if let Some(sf_v) = rel.get("sum_fields") {
        if let Some(arr) = sf_v.as_array() {
            let mut sum = 0.0;
            let mut ok = !arr.is_empty();
            for item in arr {
                if let Some(r_str) = item.as_str() {
                    if let Some(peer) = resolve_peer_target(&doc, proj_then, r_str) {
                        if let Some(pf) = peer.as_f64() {
                            sum += pf;
                            continue;
                        }
                    }
                }
                ok = false;
                break;
            }
            if ok {
                let rounded = (sum * 1e12).round() / 1e12;
                return JsonValue::Number(rounded);
            }
        }
    }
    if let Some(in_v) = rel.get("in") {
        if let Some(arr) = in_v.as_array() {
            if let Some(first) = arr.first() {
                return first.clone();
            }
        }
    }
    let has_pfx = rel.contains_key("prefix");
    let has_sfx = rel.contains_key("suffix");
    let has_cnt = rel.contains_key("contains");
    if has_pfx || has_sfx || has_cnt {
        let pfx = rel.get("prefix").and_then(|v| v.as_str()).unwrap_or("");
        let sfx = rel.get("suffix").and_then(|v| v.as_str()).unwrap_or("");
        let mid = rel
            .get("contains")
            .and_then(|v| v.as_str())
            .unwrap_or("x");
        let mut s = format!("{}{}{}", pfx, mid, sfx);
        if let Some(ml) = rel.get("min_len").and_then(|v| v.as_f64()) {
            let min_l = ml as usize;
            while s.chars().count() < min_l {
                s.push('x');
            }
        }
        return JsonValue::Str(s);
    }
    if let Some(eq_ref) = rel.get("eq_field").and_then(|v| v.as_str()) {
        if let Some(peer) = resolve_peer_target(&doc, proj_then, eq_ref) {
            return peer.clone();
        }
    }
    if let Some(ge_ref) = rel.get("ge_field").and_then(|v| v.as_str()) {
        if let Some(peer) = resolve_peer_target(&doc, proj_then, ge_ref) {
            if let Some(pf) = peer.as_f64() {
                return JsonValue::Number(pf);
            }
        }
    }
    if let Some(le_ref) = rel.get("le_field").and_then(|v| v.as_str()) {
        if let Some(peer) = resolve_peer_target(&doc, proj_then, le_ref) {
            if let Some(pf) = peer.as_f64() {
                return JsonValue::Number(pf);
            }
        }
    }
    if let Some(min_v) = rel.get("min").and_then(|v| v.as_f64()) {
        if let Some(max_v) = rel.get("max").and_then(|v| v.as_f64()) {
            let mid = ((min_v + max_v) / 2.0 * 1e12).round() / 1e12;
            return JsonValue::Number(mid);
        }
        return JsonValue::Number(min_v);
    }
    if let Some(max_v) = rel.get("max").and_then(|v| v.as_f64()) {
        return JsonValue::Number(max_v);
    }
    if let Some(ml) = rel.get("min_len").and_then(|v| v.as_f64()) {
        let n = (ml as usize).max(1);
        return JsonValue::Str("a".repeat(n));
    }
    if rel.get("non_empty").and_then(|v| v.as_bool()) == Some(true) {
        return JsonValue::Str("a".to_string());
    }
    JsonValue::Null
}
