// Reusable observable behavioral probes for the DRIFT Rust bridge.

use crate::checks::values_equal;
use crate::context::{
    allowed_write_sets_of, env_trim, forbidden_writes_of, is_write_resource_allowed,
    record_discovered_inventory, verify_single_frame_obs,
};
use crate::json::{parse_json, JsonValue};
use crate::{DriftContext, TestError};
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Mutex, OnceLock};

const DEFAULT_VOLATILE_KEYS: &[&str] = &["request_id", "timestamp", "trace_id", "audit_id"];
const DEFAULT_ALLOWED_SECOND_WRITES: &[&str] = &["AUDIT_LOG", "audit_log", "METRICS", "metrics"];

pub(crate) fn is_unobserved_frame_entry(obs: &JsonValue) -> bool {
    obs.as_object().and_then(|m| m.get("observed")).and_then(|v| v.as_bool()) == Some(false)
}

fn has_frame_metrics_entry(obs: &JsonValue) -> bool {
    obs.as_object().is_some_and(|m| m.contains_key("writes") || m.contains_key("operations") || m.contains_key("events") || (m.contains_key("before") && m.contains_key("after")))
}

pub fn has_key_recursive(val: &JsonValue, fk: &str, is_root: bool) -> bool {
    match val {
        JsonValue::Array(arr) => arr.iter().any(|item| has_key_recursive(item, fk, false)),
        JsonValue::Object(map) => map.contains_key(fk) || map.iter().any(|(k, v)| !(is_root && (k == "_frame" || k == "_when_env") && fk != k && v.as_object().is_some()) && has_key_recursive(v, fk, false)),
        _ => false,
    }
}

fn as_non_neg_int(v: &JsonValue) -> Option<i64> {
    v.as_f64().filter(|n| n.is_finite() && *n >= 0.0 && n.fract() == 0.0).map(|n| n as i64)
}

pub fn check_bola_variant_pair(pfx: &str, v_doc: &JsonValue) -> Result<bool, TestError> {
    let Some(vm) = v_doc.as_object() else { return Ok(false) };
    let b = vm.get("bola").and_then(|v| v.as_object()).unwrap_or(vm);
    if !b.contains_key("actor_owner") && !b.contains_key("resource_owner") { return Ok(false); }
    let a = b.get("actor_owner").and_then(|v| v.as_str()).map(str::trim).unwrap_or("");
    let o = b.get("resource_owner").and_then(|v| v.as_str()).map(str::trim).unwrap_or("");
    if a.is_empty() || o.is_empty() || a == o { return Err(TestError::assertion(format!("{}: bola.invalid_fixture", pfx))); }
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

fn frame_entry_wrote(obs: &JsonValue) -> bool {
    if as_non_neg_int(obs).is_some_and(|n| n > 0) {
        return true;
    }
    let Some(om) = obs.as_object() else { return false };
    for wk in ["writes", "operations", "events"] {
        if let Some(wv) = om.get(wk) {
            if as_non_neg_int(wv).is_some_and(|n| n > 0) || wv.as_array().is_some_and(|a| !a.is_empty()) {
                return true;
            }
        }
    }
    om.get("before").zip(om.get("after")).is_some_and(|(b, a)| !values_equal(b, a))
}

impl DriftContext {
    pub fn check_frame(&mut self, case_id: &str, frame_json: &str) -> Result<(), TestError> {
        self.check_frame_with_mode(case_id, frame_json, true)
    }

    pub(crate) fn check_frame_with_mode(&mut self, case_id: &str, frame_json: &str, strict: bool) -> Result<(), TestError> {
        let _ = self.case_map(case_id)?;
        let forbidden = forbidden_writes_of(&self.view, case_id);
        let doc = parse_json(frame_json).map_err(|e| TestError::assertion(format!("bad frame_json: {}", e)))?;
        let fmap = doc.as_object().ok_or_else(|| TestError::assertion("frame_json must be object"))?;
        let mut checked = BTreeSet::new();
        let mut all_obs = true;
        let mut obs_writes = Vec::new();
        for res in &forbidden {
            let base = res.split('#').next().unwrap_or(res.as_str());
            checked.insert(res.as_str());
            checked.insert(base);
            let Some(obs) = fmap.get(res).or_else(|| fmap.get(base)) else {
                all_obs = false;
                if strict { return Err(TestError::assertion(format!("{}.{}: missing frame for '{}'", self.contract_id, case_id, res))); }
                continue;
            };
            if has_frame_metrics_entry(obs) { verify_single_frame_obs(&self.contract_id, case_id, res, obs, false)?; }
            if is_unobserved_frame_entry(obs) {
                all_obs = false;
                if strict { return Err(TestError::assertion(format!("{}.{}: frame.observer_missing '{}'", self.contract_id, case_id, res))); }
                continue;
            }
            if !has_frame_metrics_entry(obs) { verify_single_frame_obs(&self.contract_id, case_id, res, obs, false)?; }
            self.mark_read(case_id, &format!("@frame:{}", res));
        }
        let extra: Vec<(String, JsonValue)> = {
            let (al, ab, _) = allowed_write_sets_of(&self.view, case_id);
            fmap.iter().filter(|(k, obs_k)| {
                if is_unobserved_frame_entry(obs_k) { all_obs = false; }
                if frame_entry_wrote(obs_k) { obs_writes.push((*k).clone()); }
                !checked.contains(k.as_str()) && !is_write_resource_allowed(k.as_str(), &al, &ab)
            }).map(|(k, v)| (k.clone(), v.clone())).collect()
        };
        for (k, obs_k) in &extra {
            if has_frame_metrics_entry(obs_k) { verify_single_frame_obs(&self.contract_id, case_id, k, obs_k, true)?; }
            if is_unobserved_frame_entry(obs_k) {
                all_obs = false;
                if strict { return Err(TestError::assertion(format!("{}.{}: frame.observer_missing '{}'", self.contract_id, case_id, k))); }
                continue;
            }
            if !has_frame_metrics_entry(obs_k) { verify_single_frame_obs(&self.contract_id, case_id, k, obs_k, true)?; }
        }
        if !self.in_mutation && all_obs && (!forbidden.is_empty() || !obs_writes.is_empty()) {
            self.obs_frames.insert(case_id.to_string(), obs_writes);
        } else {
            self.obs_frames.remove(case_id);
        }
        Ok(())
    }

    fn unverified_or_err(&mut self, case_id: &str, strict: bool, reason: &str, detail: &str) -> Result<bool, TestError> {
        self.read_keys.remove(case_id);
        if strict { Err(TestError::assertion(format!("{}.{}: {}: {}", self.contract_id, case_id, reason, detail))) } else { Ok(false) }
    }

    fn parse_probe_obs(&mut self, case_id: &str, obs_json: &str, code: &str, msg: &str) -> Result<Option<(BTreeMap<String, JsonValue>, bool)>, TestError> {
        let _ = self.case_map(case_id)?;
        let doc = parse_json(obs_json).map_err(|e| TestError::assertion(format!("bad obs_json: {}", e)))?;
        let Some(m) = doc.as_object() else { self.unverified_or_err(case_id, true, code, "object")?; return Ok(None); };
        let strict = m.get("strict").and_then(|v| v.as_bool()) != Some(false);
        if m.get("observed").and_then(|v| v.as_bool()) == Some(false) { self.unverified_or_err(case_id, strict, code, msg)?; return Ok(None); }
        Ok(Some((m.clone(), strict)))
    }

    pub fn check_idempotency(&mut self, case_id: &str, obs_json: &str) -> Result<bool, TestError> {
        let Some((m, strict)) = self.parse_probe_obs(case_id, obs_json, "idempotency.unobserved", "unobserved")? else { return Ok(false) };
        let (s1, s2) = (m.get("stateAfterFirst").or_else(|| m.get("state_after_first")), m.get("stateAfterSecond").or_else(|| m.get("state_after_second")));
        let has_s = s1.is_some_and(|v| !matches!(v, JsonValue::Null)) && s2.is_some_and(|v| !matches!(v, JsonValue::Null));
        let sw = m.get("secondWrites").or_else(|| m.get("second_writes")).and_then(|v| v.as_object());
        if !has_s && sw.is_none() { return self.unverified_or_err(case_id, strict, "idempotency.unobserved", "unobserved"); }
        if let Some(fv) = m.get("first").filter(|v| !matches!(v, JsonValue::Null)) { self.check_projection(case_id, &fv.to_json_string())?; }
        let pfx = format!("{}.{}", self.contract_id, case_id);
        if let (Some(v1), Some(v2)) = (s1, s2) { if has_s && !values_equal(v1, v2) { return Err(TestError::assertion(format!("{}: idempotency.domain_state_mutated", pfx))); } }
        if let Some(swm) = sw {
            let a2: BTreeSet<&str> = m.get("allowedSecondWrites").and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|x| x.as_str()).collect()).unwrap_or_else(|| DEFAULT_ALLOWED_SECOND_WRITES.iter().copied().collect());
            for (res, wv) in swm {
                if a2.contains(res.as_str()) || a2.contains(res.split('#').next().unwrap_or(res.as_str())) { continue; }
                let cnt = wv.as_array().map(|a| a.len() as i64).or_else(|| as_non_neg_int(wv)).unwrap_or(-1);
                if cnt != 0 { return Err(TestError::assertion(format!("{}: idempotency.duplicate_write '{}'", pfx, res))); }
            }
        }
        if let (Some(fm), Some(sm)) = (m.get("first").and_then(|v| v.as_object()), m.get("second").and_then(|v| v.as_object())) {
            for (k, v1) in fm {
                if !DEFAULT_VOLATILE_KEYS.contains(&k.as_str()) && k != "_frame" && sm.get(k).is_some_and(|v2| !values_equal(v1, v2)) {
                    return Err(TestError::assertion(format!("{}: idempotency.response_diverged '{}'", pfx, k)));
                }
            }
        }
        Ok(true)
    }

    pub fn check_seam_probe(&mut self, case_id: &str, obs_json: &str) -> Result<bool, TestError> {
        let Some((m, strict)) = self.parse_probe_obs(case_id, obs_json, "seam.unobserved", "unobserved")? else { return Ok(false) };
        let has_r = m.contains_key("retryable") || m.contains_key("maxAttempts") || m.contains_key("max_attempts");
        let has_t = m.get("timedOut").or_else(|| m.get("timed_out")).and_then(|v| v.as_bool()) == Some(true);
        let has_q = m.contains_key("maxQueries") || m.contains_key("max_queries");
        if !has_r && !has_t && !has_q { return self.unverified_or_err(case_id, strict, "seam.unobserved", "unobserved"); }
        let pfx = format!("{}.{}", self.contract_id, case_id);
        if has_r {
            let att = m.get("attempts").and_then(as_non_neg_int).unwrap_or(-1);
            if att <= 0 { return self.unverified_or_err(case_id, strict, "seam.unobserved", "unobserved"); }
            if m.get("retryable").and_then(|v| v.as_bool()) == Some(false) && att > 1 { return Err(TestError::assertion(format!("{}: seam.non_retryable_retried", pfx))); }
            if m.get("retryable").and_then(|v| v.as_bool()) == Some(true) && att < 2 { return Err(TestError::assertion(format!("{}: seam.retry_missing", pfx))); }
            if let Some(ma_v) = m.get("maxAttempts").or_else(|| m.get("max_attempts")) {
                let ma = as_non_neg_int(ma_v).unwrap_or(-1);
                if ma < 0 || att > ma { return Err(TestError::assertion(format!("{}: seam.max_attempts_exceeded", pfx))); }
            }
        }
        if has_t {
            let lw = m.get("lateWrites").or_else(|| m.get("late_writes")).map_or(Some(0), as_non_neg_int).unwrap_or(-1);
            if lw < 0 { return self.unverified_or_err(case_id, strict, "seam.unobserved", "unobserved"); }
            if lw > 0 { return Err(TestError::assertion(format!("{}: seam.timeout_late_write", pfx))); }
        }
        if has_q {
            let q = m.get("queries").and_then(as_non_neg_int).unwrap_or(-1);
            let mq = m.get("maxQueries").or_else(|| m.get("max_queries")).and_then(as_non_neg_int).unwrap_or(-1);
            if q < 0 || mq < 0 { return self.unverified_or_err(case_id, strict, "queries.unobserved", "unobserved"); }
            if q > mq { return Err(TestError::assertion(format!("{}: seam.query_budget_exceeded", pfx, ))); }
        }
        Ok(true)
    }

    pub fn check_rollback(&mut self, case_id: &str, obs_json: &str) -> Result<bool, TestError> {
        let Some((m, strict)) = self.parse_probe_obs(case_id, obs_json, "rollback.unobserved", "unobserved")? else { return Ok(false) };
        let (Some(bef), Some(aft)) = (m.get("before"), m.get("after")) else { return self.unverified_or_err(case_id, strict, "rollback.unobserved", "unobserved"); };
        if matches!(bef, JsonValue::Null) || matches!(aft, JsonValue::Null) { return self.unverified_or_err(case_id, strict, "rollback.unobserved", "unobserved"); }
        let comp = m.get("compensated").and_then(|v| v.as_bool()) == Some(true);
        let res = m.get("resource").and_then(|v| v.as_str()).filter(|s| !s.is_empty()).unwrap_or("primary");
        if !values_equal(bef, aft) && !comp { return Err(TestError::assertion(format!("{}.{}: rollback.dirty_partial_write '{}'", self.contract_id, case_id, res))); }
        Ok(true)
    }

    pub fn check_log_sink(&mut self, case_id: &str, obs_json: &str) -> Result<bool, TestError> {
        let Some((m, strict)) = self.parse_probe_obs(case_id, obs_json, "log_sink.unobserved", "unobserved")? else { return Ok(false) };
        let sec: Vec<&str> = m.get("secretValues").or_else(|| m.get("secret_values")).and_then(|v| v.as_array()).map(|a| a.iter().filter_map(|x| x.as_str().filter(|s| !s.trim().is_empty())).collect()).unwrap_or_default();
        let logs = m.get("logLines").or_else(|| m.get("log_lines"));
        let hl = logs.is_some_and(|v| v.as_str().is_some() || v.as_array().is_some());
        let p = m.get("payload");
        let hp = p.is_some_and(|v| !matches!(v, JsonValue::Null));
        if sec.is_empty() || (!hl && !hp) { return self.unverified_or_err(case_id, strict, "log_sink.unobserved", "unobserved"); }
        for s in sec {
            if logs.is_some_and(|l| contains_str_leaf(l, s)) || p.is_some_and(|x| contains_str_leaf(x, s)) {
                return Err(TestError::assertion(format!("{}.{}: log_sink.secret_leaked", self.contract_id, case_id)));
            }
        }
        Ok(true)
    }
}

pub fn canonical_rust_test_id(c: &str, m: &str, f: &str) -> String {
    let (cc, cm, cf) = (c.trim().replace('-', "_"), m.trim().trim_matches(':'), f.trim());
    if cm.is_empty() || cm == cc { format!("{}#{}", cc, cf) }
    else if cm.starts_with(&format!("{}::", cc)) { format!("{}#{}", cm, cf) }
    else { format!("{}::{}#{}", cc, cm, cf) }
}

pub fn canonical_test_id(test: &str) -> Result<(String, String, String), TestError> {
    let t = test.trim();
    let Some(h) = t.find('#') else { return Err(TestError::harness(format!("bad test id '{}'", test))); };
    if h == 0 || h + 1 >= t.len() { return Err(TestError::harness(format!("bad test id '{}'", test))); }
    let cls = &t[..h];
    let mut mth = &t[h + 1..];
    for ch in ['(', '['] {
        if let Some(idx) = mth.find(ch) { mth = &mth[..idx]; }
    }
    let mth = mth.trim();
    if cls.is_empty() || mth.is_empty() || cls.contains('#') || mth.contains('#') {
        return Err(TestError::harness(format!("invalid test id '{}'", test)));
    }
    Ok((cls.to_string(), mth.to_string(), format!("{}#{}", cls, mth)))
}

pub fn parse_list_terse_output(crate_name: &str, list_stdout: &str) -> (Vec<String>, Vec<String>) {
    let clean_crate = crate_name.trim().replace('-', "_");
    let mut classes = BTreeSet::new();
    let mut tests = BTreeSet::new();
    for raw_line in list_stdout.lines() {
        let line = raw_line.trim();
        let Some(test_path) = line.strip_suffix(": test") else {
            continue;
        };
        let test_path = test_path.trim();
        if test_path.is_empty() {
            continue;
        }
        let (mod_part, fn_part) = match test_path.rfind("::") {
            Some(idx) if idx > 0 && idx + 2 < test_path.len() => {
                (&test_path[..idx], &test_path[idx + 2..])
            }
            _ => ("", test_path),
        };
        let cls = if mod_part.is_empty() {
            clean_crate.clone()
        } else if clean_crate.is_empty() {
            mod_part.to_string()
        } else {
            format!("{}::{}", clean_crate, mod_part)
        };
        let tid = format!("{}#{}", cls, fn_part);
        classes.insert(cls);
        tests.insert(tid);
    }
    (classes.into_iter().collect(), tests.into_iter().collect())
}

fn run_list_terse(exe: &Path, extra: Option<&str>) -> Result<String, TestError> {
    let mut cmd = Command::new(exe);
    if let Some(a) = extra { cmd.arg(a); }
    let out = cmd.args(["--list", "--format=terse"]).env("DRIFT_IN_LIST_DISCOVERY", "1")
        .output().map_err(crate::ctx_err("failed --list discovery"))?;
    if !out.status.success() { return Err(crate::herr(format!("--list discovery exited {}", out.status))); }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

pub fn discover_binary_tests(crate_name: &str, events_dir: &str) -> Result<(Vec<String>, Vec<String>), TestError> {
    if env::var("DRIFT_IN_LIST_DISCOVERY").as_deref() == Ok("1") { return Ok((Vec::new(), Vec::new())); }
    let exe = env::current_exe().map_err(crate::ctx_err("current_exe"))?;
    let args: Vec<String> = env::args().collect();
    let inc_ign = args.iter().any(|a| a == "--include-ignored");
    let only_ign = !inc_ign && args.iter().any(|a| a == "--ignored");
    let all_out = run_list_terse(&exe, None)?;
    let (classes, all_tests) = parse_list_terse_output(crate_name, &all_out);
    let tests = if inc_ign {
        all_tests
    } else {
        let ign_out = run_list_terse(&exe, Some("--ignored"))?;
        if only_ign {
            parse_list_terse_output(crate_name, &ign_out).1
        } else {
            let ign: BTreeSet<&str> = ign_out.lines().map(str::trim).filter(|l| l.ends_with(": test")).collect();
            let active: String = all_out.lines().filter(|l| !ign.contains(l.trim())).collect::<Vec<_>>().join("\n");
            parse_list_terse_output(crate_name, &active).1
        }
    };
    let ev_dir = if !events_dir.trim().is_empty() { events_dir.trim().into() } else { env_trim("DRIFT_EVENTS") };
    if !ev_dir.is_empty() && (!classes.is_empty() || !tests.is_empty()) {
        record_discovered_inventory(&ev_dir, &classes, &tests)?;
    }
    Ok((classes, tests))
}

fn find_drift_cli() -> String {
    if let Ok(cli) = env::var("DRIFT_CLI") {
        let t = cli.trim();
        if !t.is_empty() {
            return t.to_string();
        }
    }
    if let Ok(mut dir) = env::current_dir() {
        loop {
            let cand = dir.join(".build").join("drift");
            if cand.is_file() {
                return cand.to_string_lossy().into_owned();
            }
            if !dir.pop() {
                break;
            }
        }
    }
    "drift".to_string()
}

fn fallback_view_cache() -> &'static Mutex<BTreeMap<String, BTreeMap<String, JsonValue>>> {
    static CACHE: OnceLock<Mutex<BTreeMap<String, BTreeMap<String, JsonValue>>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(BTreeMap::new()))
}

pub fn resolve_state_root(cwd: &Path) -> Result<Option<PathBuf>, TestError> {
    let raw = env_trim("DRIFT_STATE_DIR");
    if raw.is_empty() { return Ok(None); }
    let p = PathBuf::from(&raw);
    let sd = fs::canonicalize(&p).unwrap_or_else(|_| if p.is_absolute() { p } else { cwd.join(p) });
    let rc = fs::canonicalize(cwd).unwrap_or_else(|_| cwd.to_path_buf());
    let mf = sd.join("shadow.toml");
    if let Ok(md) = fs::symlink_metadata(&mf) {
        if md.file_type().is_symlink() || !md.is_file() { return Err(crate::herr("bad shadow.toml")); }
        let txt = fs::read_to_string(&mf).map_err(crate::ctx_err("shadow.toml"))?;
        let mut sr = crate::context::env_trim("DRIFT_SOURCE_ROOT");
        if sr.is_empty() {
            for ln in txt.lines() {
                let s = ln.trim();
                if s.starts_with("source_root") {
                    if let (Some(a), Some(b)) = (s.find('"'), s.rfind('"')) { if b > a { sr = s[a + 1..b].into(); } }
                }
            }
        }
        let rs = fs::canonicalize(sd.join(&sr)).unwrap_or_else(|_| sd.join(&sr));
        if !txt.contains("\"drift.shadow-area/1\"") || sr.is_empty() || sd.starts_with(&rs) || !rc.starts_with(&rs) {
            return Err(crate::herr("state_dir mismatch"));
        }
    }
    Ok(Some(sd))
}

pub(crate) fn load_contract_view(contract_id: &str, resolved_dir: &str) -> Result<BTreeMap<String, JsonValue>, TestError> {
    let cwd = env::current_dir().map_err(crate::ctx_err("current_dir"))?;
    let state_root = resolve_state_root(&cwd)?;
    let rdir = if !resolved_dir.trim().is_empty() { resolved_dir.trim().into() } else { env_trim("DRIFT_RESOLVED") };
    // Fail-closed when DRIFT_RESOLVED / resolved_dir is explicitly configured.
    if !rdir.is_empty() {
        let p = Path::new(&rdir).join(format!("{contract_id}.json"));
        let txt = fs::read_to_string(&p).map_err(crate::ctx_err("cannot read resolved view"))?;
        return match parse_json(&txt).map_err(crate::ctx_err("invalid resolved JSON"))? {
            JsonValue::Object(m) => Ok(m),
            _ => Err(crate::herr(format!("resolved view '{}' is not a JSON object", p.display()))),
        };
    }

    if state_root.is_none() {
        if let Ok(g) = fallback_view_cache().lock() {
            if let Some(cached) = g.get(contract_id) { return Ok(cached.clone()); }
        }
    }

    let mut dir = state_root.clone().unwrap_or(cwd);
    let mut toml_path = None;
    loop {
        let cand = dir.join(".drift").join("contracts").join(format!("{contract_id}.toml"));
        if cand.is_file() { toml_path = Some(cand); break; }
        if state_root.is_some() || !dir.pop() { break; }
    }
    let toml_path = toml_path.ok_or_else(|| {
        crate::herr(format!("cannot locate contract '{contract_id}.toml' and DRIFT_RESOLVED is not set (mark DRIFT #[test] with #[ignore] and run via --include-ignored or drift select --cmd)"))
    })?;
    let cli = find_drift_cli();
    let mut cmd = Command::new(&cli);
    cmd.arg("show").arg(&toml_path);
    if let Some(ref sd) = state_root { cmd.arg("--state-dir").arg(sd); }
    let out = cmd.args(["--as", "json"]).output().map_err(crate::ctx_err("failed to invoke drift"))?;
    if !out.status.success() {
        return Err(crate::herr(format!("drift show failed for '{}': {}", toml_path.display(), String::from_utf8_lossy(&out.stderr))));
    }
    let JsonValue::Object(map) = parse_json(&String::from_utf8_lossy(&out.stdout)).map_err(crate::ctx_err("invalid drift show JSON"))? else {
        return Err(crate::herr("drift show output is not a JSON object"));
    };
    if let Ok(mut g) = fallback_view_cache().lock() { g.insert(contract_id.into(), map.clone()); }
    Ok(map)
}

#[cfg(test)]
#[path = "probes_test.rs"]
mod tests;
