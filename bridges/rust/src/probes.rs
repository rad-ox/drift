// Reusable observable behavioral probes for the DRIFT Rust bridge.

use crate::checks::values_equal;
use crate::context::{
    allowed_write_sets_of, forbidden_writes_of, is_write_resource_allowed, verify_single_frame_obs,
};
use crate::json::{parse_json, JsonValue};
use crate::{DriftContext, TestError};
use std::collections::BTreeSet;

const DEFAULT_VOLATILE_KEYS: &[&str] = &["request_id", "timestamp", "trace_id", "audit_id"];
const DEFAULT_ALLOWED_SECOND_WRITES: &[&str] = &["AUDIT_LOG", "audit_log", "METRICS", "metrics"];

pub(crate) fn is_unobserved_frame_entry(obs: &JsonValue) -> bool {
    let Some(m) = obs.as_object() else {
        return false;
    };
    m.get("observed").and_then(|v| v.as_bool()) == Some(false)
}

fn has_frame_metrics_entry(obs: &JsonValue) -> bool {
    let Some(m) = obs.as_object() else {
        return false;
    };
    m.contains_key("writes")
        || m.contains_key("operations")
        || m.contains_key("events")
        || (m.contains_key("before") && m.contains_key("after"))
}

pub fn has_key_recursive(val: &JsonValue, fk: &str, is_root: bool) -> bool {
    match val {
        JsonValue::Array(arr) => arr.iter().any(|item| has_key_recursive(item, fk, false)),
        JsonValue::Object(map) => {
            if map.contains_key(fk) {
                return true;
            }
            for (k, v) in map {
                if is_root && k == "_frame" && fk != "_frame" && v.as_object().is_some() {
                    continue;
                }
                if has_key_recursive(v, fk, false) {
                    return true;
                }
            }
            false
        }
        _ => false,
    }
}

fn as_non_neg_int(v: &JsonValue) -> Option<i64> {
    let n = v.as_f64()?;
    if n.is_finite() && n >= 0.0 && n.fract() == 0.0 {
        Some(n as i64)
    } else {
        None
    }
}

pub fn check_bola_variant_pair(pfx: &str, v_doc: &JsonValue) -> Result<bool, TestError> {
    let Some(vm) = v_doc.as_object() else {
        return Ok(false);
    };
    let b = vm.get("bola").and_then(|v| v.as_object()).unwrap_or(vm);
    if !b.contains_key("actor_owner") && !b.contains_key("resource_owner") {
        return Ok(false);
    }
    let actor = b
        .get("actor_owner")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .unwrap_or("");
    let owner = b
        .get("resource_owner")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .unwrap_or("");
    if actor.is_empty() || owner.is_empty() || actor == owner {
        return Err(TestError::assertion(format!(
            "{}: bola.invalid_fixture: cross-owner probe requires distinct non-empty actor_owner and resource_owner",
            pfx
        )));
    }
    Ok(true)
}

fn contains_str_leaf(val: &JsonValue, needle: &str) -> bool {
    match val {
        JsonValue::Str(s) => s.contains(needle),
        JsonValue::Array(arr) => arr.iter().any(|x| contains_str_leaf(x, needle)),
        JsonValue::Object(map) => map.values().any(|v| contains_str_leaf(v, needle)),
        _ => false,
    }
}

impl DriftContext {
    pub fn check_frame(&mut self, case_id: &str, frame_json: &str) -> Result<(), TestError> {
        self.check_frame_with_mode(case_id, frame_json, true)
    }

    pub(crate) fn check_frame_with_mode(
        &mut self,
        case_id: &str,
        frame_json: &str,
        strict: bool,
    ) -> Result<(), TestError> {
        let _ = self.case_map(case_id)?;
        let forbidden = forbidden_writes_of(&self.view, case_id);
        let doc = parse_json(frame_json)
            .map_err(|e| TestError::assertion(format!("frame_json is not valid JSON: {}", e)))?;
        let fmap = doc
            .as_object()
            .ok_or_else(|| TestError::assertion("frame_json must be a JSON object"))?;
        let mut checked_keys = BTreeSet::new();
        for res in &forbidden {
            let base_res = res.split('#').next().unwrap_or(res.as_str());
            checked_keys.insert(res.as_str());
            checked_keys.insert(base_res);
            let Some(obs) = fmap.get(res).or_else(|| fmap.get(base_res)) else {
                if strict {
                    return Err(TestError::assertion(format!(
                        "{}.{}: missing frame observation for forbidden write resource '{}'",
                        self.contract_id, case_id, res
                    )));
                }
                continue;
            };
            if has_frame_metrics_entry(obs) {
                verify_single_frame_obs(&self.contract_id, case_id, res, obs, false)?;
            }
            if is_unobserved_frame_entry(obs) {
                if strict {
                    return Err(TestError::assertion(format!(
                        "{}.{}: frame.observer_missing for forbidden write resource '{}'",
                        self.contract_id, case_id, res
                    )));
                }
                continue;
            }
            if !has_frame_metrics_entry(obs) {
                verify_single_frame_obs(&self.contract_id, case_id, res, obs, false)?;
            }
            self.mark_read(case_id, &format!("@frame:{}", res));
        }
        let extra_obs: Vec<(String, JsonValue)> = {
            let (allowed, allowed_bases, _) = allowed_write_sets_of(&self.view, case_id);
            fmap.iter()
                .filter(|(k, _)| {
                    !checked_keys.contains(k.as_str())
                        && !is_write_resource_allowed(k.as_str(), &allowed, &allowed_bases)
                })
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect()
        };
        for (k, obs_k) in &extra_obs {
            if has_frame_metrics_entry(obs_k) {
                verify_single_frame_obs(&self.contract_id, case_id, k, obs_k, true)?;
            }
            if is_unobserved_frame_entry(obs_k) {
                if strict {
                    return Err(TestError::assertion(format!(
                        "{}.{}: frame.observer_missing for perimeter resource '{}'",
                        self.contract_id, case_id, k
                    )));
                }
                continue;
            }
            if !has_frame_metrics_entry(obs_k) {
                verify_single_frame_obs(&self.contract_id, case_id, k, obs_k, true)?;
            }
        }
        Ok(())
    }

    fn unverified_or_err(
        &mut self,
        case_id: &str,
        strict: bool,
        reason: &str,
        detail: &str,
    ) -> Result<bool, TestError> {
        self.read_keys.remove(case_id);
        if strict {
            Err(TestError::assertion(format!(
                "{}.{}: {}: {}",
                self.contract_id, case_id, reason, detail
            )))
        } else {
            Ok(false)
        }
    }

    pub fn check_idempotency(&mut self, case_id: &str, obs_json: &str) -> Result<bool, TestError> {
        let _ = self.case_map(case_id)?;
        let doc = parse_json(obs_json)
            .map_err(|e| TestError::assertion(format!("obs_json is not valid JSON: {}", e)))?;
        let Some(m) = doc.as_object() else {
            return self.unverified_or_err(case_id, true, "idempotency.unobserved", "expected JSON object");
        };
        let strict = m.get("strict").and_then(|v| v.as_bool()) != Some(false);
        if m.get("observed").and_then(|v| v.as_bool()) == Some(false) {
            return self.unverified_or_err(
                case_id,
                strict,
                "idempotency.unobserved",
                "collector reported unobserved state",
            );
        }
        let s1 = m.get("stateAfterFirst").or_else(|| m.get("state_after_first"));
        let s2 = m.get("stateAfterSecond").or_else(|| m.get("state_after_second"));
        let has_state = s1.is_some_and(|v| !matches!(v, JsonValue::Null))
            && s2.is_some_and(|v| !matches!(v, JsonValue::Null));
        let sw_map = m
            .get("secondWrites")
            .or_else(|| m.get("second_writes"))
            .and_then(|v| v.as_object());
        if !has_state && sw_map.is_none() {
            return self.unverified_or_err(
                case_id,
                strict,
                "idempotency.unobserved",
                "missing state snapshots and secondWrites observations",
            );
        }
        if let Some(first_val) = m.get("first") {
            if !matches!(first_val, JsonValue::Null) {
                self.check_projection(case_id, &first_val.to_json_string())?;
            }
        }
        let pfx = format!("{}.{}", self.contract_id, case_id);
        if let (Some(v1), Some(v2)) = (s1, s2) {
            if has_state && !values_equal(v1, v2) {
                return Err(TestError::assertion(format!(
                    "{}: idempotency.domain_state_mutated: stateAfterFirst and stateAfterSecond differ",
                    pfx
                )));
            }
        }
        if let Some(sw) = sw_map {
            let allowed2: BTreeSet<&str> = m
                .get("allowedSecondWrites")
                .and_then(|v| v.as_array())
                .map(|arr| arr.iter().filter_map(|x| x.as_str()).collect())
                .unwrap_or_else(|| DEFAULT_ALLOWED_SECOND_WRITES.iter().copied().collect());
            for (res, wv) in sw {
                let base = res.split('#').next().unwrap_or(res.as_str());
                if allowed2.contains(res.as_str()) || allowed2.contains(base) {
                    continue;
                }
                let cnt = if let Some(arr) = wv.as_array() {
                    arr.len() as i64
                } else {
                    as_non_neg_int(wv).unwrap_or(-1)
                };
                if cnt != 0 {
                    return Err(TestError::assertion(format!(
                        "{}: idempotency.duplicate_write on resource '{}': expected 0 writes on replay, observed {}",
                        pfx, res, cnt
                    )));
                }
            }
        }
        if let (Some(fmap), Some(smap)) = (
            m.get("first").and_then(|v| v.as_object()),
            m.get("second").and_then(|v| v.as_object()),
        ) {
            for (k, v1) in fmap {
                if DEFAULT_VOLATILE_KEYS.contains(&k.as_str()) || k == "_frame" {
                    continue;
                }
                if let Some(v2) = smap.get(k) {
                    if !values_equal(v1, v2) {
                        return Err(TestError::assertion(format!(
                            "{}: idempotency.response_diverged on key '{}'",
                            pfx, k
                        )));
                    }
                }
            }
        }
        Ok(true)
    }

    pub fn check_seam_probe(&mut self, case_id: &str, obs_json: &str) -> Result<bool, TestError> {
        let _ = self.case_map(case_id)?;
        let doc = parse_json(obs_json)
            .map_err(|e| TestError::assertion(format!("obs_json is not valid JSON: {}", e)))?;
        let Some(m) = doc.as_object() else {
            return self.unverified_or_err(case_id, true, "seam.unobserved", "expected JSON object");
        };
        let strict = m.get("strict").and_then(|v| v.as_bool()) != Some(false);
        if m.get("observed").and_then(|v| v.as_bool()) == Some(false) {
            return self.unverified_or_err(
                case_id,
                strict,
                "seam.unobserved",
                "seam collector is unobserved",
            );
        }
        let has_retry = m.contains_key("retryable")
            || m.contains_key("maxAttempts")
            || m.contains_key("max_attempts");
        let has_timeout = m
            .get("timedOut")
            .or_else(|| m.get("timed_out"))
            .and_then(|v| v.as_bool())
            == Some(true);
        let has_query = m.contains_key("maxQueries") || m.contains_key("max_queries");
        if !has_retry && !has_timeout && !has_query {
            return self.unverified_or_err(
                case_id,
                strict,
                "seam.unobserved",
                "probe specifies neither retry, timeout, nor query bounds",
            );
        }
        let pfx = format!("{}.{}", self.contract_id, case_id);
        if has_retry {
            let att = m.get("attempts").and_then(as_non_neg_int).unwrap_or(-1);
            if att <= 0 {
                return self.unverified_or_err(
                    case_id,
                    strict,
                    "seam.unobserved",
                    "missing positive attempts count from seam spy",
                );
            }
            if m.get("retryable").and_then(|v| v.as_bool()) == Some(false) && att > 1 {
                return Err(TestError::assertion(format!(
                    "{}: seam.non_retryable_retried: expected 1 attempt on terminal fault, observed {}",
                    pfx, att
                )));
            }
            if m.get("retryable").and_then(|v| v.as_bool()) == Some(true) && att < 2 {
                return Err(TestError::assertion(format!(
                    "{}: seam.retry_missing: expected >= 2 attempts on transient fault, observed {}",
                    pfx, att
                )));
            }
            if let Some(ma_v) = m.get("maxAttempts").or_else(|| m.get("max_attempts")) {
                let ma = as_non_neg_int(ma_v).unwrap_or(-1);
                if ma < 0 || att > ma {
                    return Err(TestError::assertion(format!(
                        "{}: seam.max_attempts_exceeded: observed {} > maxAttempts {}",
                        pfx, att, ma
                    )));
                }
            }
        }
        if has_timeout {
            let lw = m
                .get("lateWrites")
                .or_else(|| m.get("late_writes"))
                .map_or(Some(0), as_non_neg_int)
                .unwrap_or(-1);
            if lw < 0 {
                return self.unverified_or_err(
                    case_id,
                    strict,
                    "seam.unobserved",
                    "invalid lateWrites observation",
                );
            }
            if lw > 0 {
                return Err(TestError::assertion(format!(
                    "{}: seam.timeout_late_write: expected 0 writes after timeout, observed {}",
                    pfx, lw
                )));
            }
        }
        if has_query {
            let q = m.get("queries").and_then(as_non_neg_int).unwrap_or(-1);
            let mq = m
                .get("maxQueries")
                .or_else(|| m.get("max_queries"))
                .and_then(as_non_neg_int)
                .unwrap_or(-1);
            if q < 0 || mq < 0 {
                return self.unverified_or_err(
                    case_id,
                    strict,
                    "queries.unobserved",
                    "missing non-negative queries count from SQL listener",
                );
            }
            if q > mq {
                return Err(TestError::assertion(format!(
                    "{}: seam.query_budget_exceeded: observed {} > maxQueries {}",
                    pfx, q, mq
                )));
            }
        }
        Ok(true)
    }

    pub fn check_rollback(&mut self, case_id: &str, obs_json: &str) -> Result<bool, TestError> {
        let _ = self.case_map(case_id)?;
        let doc = parse_json(obs_json)
            .map_err(|e| TestError::assertion(format!("obs_json is not valid JSON: {}", e)))?;
        let Some(m) = doc.as_object() else {
            return self.unverified_or_err(case_id, true, "rollback.unobserved", "expected JSON object");
        };
        let strict = m.get("strict").and_then(|v| v.as_bool()) != Some(false);
        if m.get("observed").and_then(|v| v.as_bool()) == Some(false) {
            return self.unverified_or_err(
                case_id,
                strict,
                "rollback.unobserved",
                "missing before/after snapshot on primary resource",
            );
        }
        let (Some(bef), Some(aft)) = (m.get("before"), m.get("after")) else {
            return self.unverified_or_err(
                case_id,
                strict,
                "rollback.unobserved",
                "missing before/after snapshot on primary resource",
            );
        };
        if matches!(bef, JsonValue::Null) || matches!(aft, JsonValue::Null) {
            return self.unverified_or_err(
                case_id,
                strict,
                "rollback.unobserved",
                "missing before/after snapshot on primary resource",
            );
        }
        let comp = m.get("compensated").and_then(|v| v.as_bool()) == Some(true);
        let res = m
            .get("resource")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or("primary");
        if !values_equal(bef, aft) && !comp {
            return Err(TestError::assertion(format!(
                "{}.{}: rollback.dirty_partial_write on '{}': before and after snapshots differ after downstream failure",
                self.contract_id, case_id, res
            )));
        }
        Ok(true)
    }

    pub fn check_log_sink(&mut self, case_id: &str, obs_json: &str) -> Result<bool, TestError> {
        let _ = self.case_map(case_id)?;
        let doc = parse_json(obs_json)
            .map_err(|e| TestError::assertion(format!("obs_json is not valid JSON: {}", e)))?;
        let Some(m) = doc.as_object() else {
            return self.unverified_or_err(case_id, true, "log_sink.unobserved", "expected JSON object");
        };
        let strict = m.get("strict").and_then(|v| v.as_bool()) != Some(false);
        if m.get("observed").and_then(|v| v.as_bool()) == Some(false) {
            return self.unverified_or_err(
                case_id,
                strict,
                "log_sink.unobserved",
                "log sink collector is unobserved",
            );
        }
        let secrets: Vec<&str> = m
            .get("secretValues")
            .or_else(|| m.get("secret_values"))
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|x| x.as_str().filter(|s| !s.trim().is_empty()))
                    .collect()
            })
            .unwrap_or_default();
        let logs = m.get("logLines").or_else(|| m.get("log_lines"));
        let has_logs = logs.is_some_and(|v| v.as_str().is_some() || v.as_array().is_some());
        let payload = m.get("payload");
        let has_payload = payload.is_some_and(|v| !matches!(v, JsonValue::Null));
        if secrets.is_empty() || (!has_logs && !has_payload) {
            return self.unverified_or_err(
                case_id,
                strict,
                "log_sink.unobserved",
                "missing secretValues or observed logLines/payload",
            );
        }
        for s in secrets {
            if logs.is_some_and(|l| contains_str_leaf(l, s))
                || payload.is_some_and(|p| contains_str_leaf(p, s))
            {
                return Err(TestError::assertion(format!(
                    "{}.{}: log_sink.secret_leaked: secret canary leaked in observed sink",
                    self.contract_id, case_id
                )));
            }
        }
        Ok(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recursive_forbid_keys_and_bola_pair_validation() {
        let nested = parse_json(r#"{"status":200,"details":{"token":"leak"}}"#).unwrap();
        assert!(has_key_recursive(&nested, "token", true));
        let prose = parse_json(r#"{"status":200,"message":"token=ok"}"#).unwrap();
        assert!(!has_key_recursive(&prose, "token", true));
        let same_owner = parse_json(r#"{"actor_owner":"t1","resource_owner":"t1"}"#).unwrap();
        assert!(check_bola_variant_pair("c.deny", &same_owner).is_err());
        let cross_owner = parse_json(r#"{"actor_owner":"t1","resource_owner":"t2"}"#).unwrap();
        assert_eq!(check_bola_variant_pair("c.deny", &cross_owner).unwrap(), true);
    }
}
