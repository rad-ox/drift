use super::desugar_03_rel;
use crate::json::JsonValue;
use std::collections::BTreeMap;

pub(crate) fn normalize_constraint_03(
    raw: &BTreeMap<String, JsonValue>,
    context: Option<&BTreeMap<String, JsonValue>>,
    pred: &str,
) -> Result<BTreeMap<String, JsonValue>, String> {
    let mut out = desugar_03_rel(raw);
    let Some(from) = raw.get("convert_from").and_then(JsonValue::as_str) else {
        return Ok(out);
    };
    let units = context
        .and_then(|m| m.get("units"))
        .and_then(JsonValue::as_object)
        .or_else(|| raw.get("unit_conversion").and_then(JsonValue::as_object));
    let target = context
        .and_then(|m| m.get("schema"))
        .and_then(JsonValue::as_object)
        .and_then(|m| m.get("then"))
        .and_then(JsonValue::as_object)
        .and_then(|m| m.get(pred))
        .and_then(JsonValue::as_object)
        .and_then(|m| m.get("unit"))
        .and_then(JsonValue::as_str)
        .or_else(|| raw.get("unit").and_then(JsonValue::as_str));
    let ratio = if target == Some(from) {
        Some(1.0)
    } else if let Some(target) = target {
        units
            .and_then(|m| m.get(&format!("{}->{}", from, target)))
            .and_then(JsonValue::as_f64)
    } else {
        let matches: Vec<_> = units
            .into_iter()
            .flat_map(|m| m.iter())
            .filter(|(k, _)| k.starts_with(&format!("{}->", from)))
            .collect();
        if matches.len() == 1 {
            matches.first().and_then(|(_, v)| v.as_f64())
        } else {
            None
        }
    }
    .filter(|r| r.is_finite() && *r > 0.0)
    .ok_or_else(|| format!("{}: missing unit conversion from {}", pred, from))?;
    let scale = |v: &mut JsonValue| {
        if let JsonValue::Number(n) = v {
            *n *= ratio;
        }
    };
    for k in ["eq", "approx", "min", "max", "abs_tol", "step_max_delta"] {
        if let Some(v) = out.get_mut(k) {
            scale(v);
        }
    }
    for k in ["in", "not_in"] {
        if let Some(JsonValue::Array(a)) = out.get_mut(k) {
            for v in a {
                scale(v);
            }
        }
    }
    if let Some(st) = out.get_mut("sum_total") {
        if let JsonValue::Object(m) = st {
            for v in m.values_mut() {
                scale(v);
            }
        } else {
            scale(st);
        }
    }
    Ok(out)
}
