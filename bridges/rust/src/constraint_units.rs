use super::{check_relational_leaf, desugar_03_rel, escape_pointer, resolve_pointer};
use crate::json::{parse_json, JsonValue};
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::Path;

pub(crate) fn load_contract_plan_case(
    contract_id: &str,
    resolved_dir: &str,
    view: &BTreeMap<String, JsonValue>,
    case_id: &str,
) -> Option<BTreeMap<String, JsonValue>> {
    let rdir = if !resolved_dir.trim().is_empty() {
        resolved_dir.trim().to_string()
    } else {
        env::var("DRIFT_RESOLVED").unwrap_or_default().trim().to_string()
    };
    if rdir.is_empty() {
        return None;
    }
    let txt = fs::read_to_string(Path::new(&rdir).join(".plans").join(format!("{}.plan.json", contract_id))).ok()?;
    let doc = parse_json(&txt).ok()?;
    let pm = doc.as_object()?;
    if pm.get("schema").and_then(|v| v.as_str()) != Some("drift.bridge-plan/1") {
        return None;
    }
    let pdig = pm.get("digest").and_then(|v| v.as_str()).unwrap_or("");
    let vdig = view.get("digest").and_then(|v| v.as_str()).unwrap_or("");
    let vref = view.get("ref").and_then(|v| v.as_str()).unwrap_or("");
    if pdig.is_empty() || (pdig != vdig && pdig != vref) {
        return None;
    }
    pm.get("cases")?.as_object()?.get(case_id)?.as_object().cloned()
}

pub(crate) fn load_contract_plan_stub(
    contract_id: &str,
    resolved_dir: &str,
    view: &BTreeMap<String, JsonValue>,
    case_id: &str,
) -> Option<String> {
    let pc = load_contract_plan_case(contract_id, resolved_dir, view, case_id)?;
    if pc.get("exempt").and_then(|v| v.as_bool()) == Some(true) {
        return None;
    }
    Some(pc.get("stub_output")?.to_json_string())
}

pub(crate) fn eval_compiled_plan_case_impl(
    contract_id: &str,
    case_id: &str,
    plan_case: &BTreeMap<String, JsonValue>,
    doc: &JsonValue,
) -> Result<(bool, Vec<String>), String> {
    let Some(clauses) = plan_case.get("clauses").and_then(|v| v.as_array()) else {
        return Ok((false, Vec::new()));
    };
    let mut read_preds = Vec::new();
    for c_any in clauses {
        let Some(cm) = c_any.as_object() else { continue };
        let pred = cm.get("pred").and_then(|v| v.as_str()).unwrap_or("");
        let default_ptr = format!("/{}", escape_pointer(pred));
        let ptr = cm.get("pointer").and_then(|v| v.as_str()).unwrap_or(&default_ptr);
        let conv = cm.get("conv").and_then(|v| v.as_f64()).unwrap_or(1.0);
        let Some(raw_c) = cm.get("constraint").and_then(|v| v.as_object()) else { continue };
        let mut rel = raw_c.clone();
        let mut fake_view = BTreeMap::new();
        if (conv - 1.0).abs() > 0.0 {
            let mut units = BTreeMap::new();
            units.insert("__u->target".to_string(), JsonValue::Number(conv));
            let mut p_schema = BTreeMap::new();
            p_schema.insert("unit".to_string(), JsonValue::Str("target".to_string()));
            let mut then_schema = BTreeMap::new();
            then_schema.insert(pred.to_string(), JsonValue::Object(p_schema));
            let mut schema = BTreeMap::new();
            schema.insert("then".to_string(), JsonValue::Object(then_schema));
            fake_view.insert("units".to_string(), JsonValue::Object(units));
            fake_view.insert("schema".to_string(), JsonValue::Object(schema));
            rel.insert("convert_from".to_string(), JsonValue::Str("__u".to_string()));
        }
        let lowered = normalize_constraint_03(&rel, if fake_view.is_empty() { None } else { Some(&fake_view) }, pred)?;
        let mut peer_ptrs = BTreeMap::new();
        if let Some(pp) = cm.get("peer_pointers").and_then(|v| v.as_object()) {
            for (k, v) in pp {
                if let Some(s) = v.as_str() {
                    peer_ptrs.insert(k.clone(), s.to_string());
                    if let Some(rest) = k.strip_prefix("then.") {
                        peer_ptrs.insert(rest.to_string(), s.to_string());
                    }
                }
            }
        }
        let has_key_guard = lowered.contains_key("allowed_keys") || lowered.contains_key("forbid_keys");
        let actual = if has_key_guard && ptr == default_ptr {
            doc.as_object().and_then(|o| o.get(pred)).filter(|v| v.as_object().is_some()).unwrap_or(doc)
        } else {
            resolve_pointer(doc, ptr).ok_or_else(|| format!("{}.{}: missing pointer '{}' for predicate '{}'", contract_id, case_id, ptr, pred))?
        };
        check_relational_leaf(doc, actual, &lowered, &peer_ptrs, pred)?;
        if cm.get("clause").and_then(|v| v.as_str()).unwrap_or("").starts_with("then.") && !read_preds.iter().any(|p| p == pred) {
            read_preds.push(pred.to_string());
        }
    }
    Ok((true, read_preds))
}

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
