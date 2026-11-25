// Zero-dependency compile-once Rust test bridge for DRIFT.

pub mod checks;
mod context;
pub mod formal;
pub mod json;
mod mutants;
pub mod probes;

use checks::{
    check_relational_leaf, escape_pointer, is_relational_table, normalize_pointer, resolve_pointer,
    synthesize_leaf_witness, unescape_pointer, values_equal, write_pointer,
};
use context::*;
use json::{hash_fixture_bytes, parse_json, sha256_hex, JsonValue};
use mutants::*;
use std::any::Any;
use std::cell::{Cell, RefCell};
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::panic::{self, AssertUnwindSafe};
use std::path::Path;
use std::process::{self, Command};
use std::sync::{Mutex, OnceLock};

pub const ADAPTER_ID: &str = "drift_rust@0.11.0";
pub const BRIDGE_VERSION: &str = "0.11.0";

const ENV_KEYS: &[&str] = &[
    "adapter",
    "config",
    "deps",
    "drift",
    "policy",
    "runner",
    "toolchain",
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MutantMode {
    Auto,
    InProcess,
    Subprocess,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TestError {
    Assertion(String),
    Harness(String),
}

impl TestError {
    pub fn assertion(msg: impl Into<String>) -> Self { TestError::Assertion(msg.into()) }
    pub fn harness(msg: impl Into<String>) -> Self { TestError::Harness(msg.into()) }
    pub fn message(&self) -> &str { match self { TestError::Assertion(s) | TestError::Harness(s) => s.as_str() } }
}

impl std::fmt::Display for TestError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self { TestError::Assertion(s) => write!(f, "{}", s), TestError::Harness(s) => write!(f, "harness error: {}", s) }
    }
}

impl From<String> for TestError { fn from(s: String) -> Self { TestError::Assertion(s) } }
impl From<&str> for TestError { fn from(s: &str) -> Self { TestError::Assertion(s.to_string()) } }

#[derive(Clone, Debug)]
pub struct RunOptions {
    pub contract: String,
    pub test: String,
    pub cases: Vec<String>,
    pub level: String,
    pub resolved_dir: String,
    pub events_dir: String,
    pub mutation_events_dir: String,
    pub mutant_mode: MutantMode,
    pub cargo_test_filter: String,
    pub strict_when: bool,
}

impl Default for RunOptions {
    fn default() -> Self {
        Self { contract: String::new(), test: String::new(), cases: Vec::new(), level: "unit".into(), resolved_dir: String::new(), events_dir: String::new(), mutation_events_dir: String::new(), mutant_mode: MutantMode::Auto, cargo_test_filter: String::new(), strict_when: false }
    }
}

pub struct DriftContext {
    pub contract_id: String,
    pub test_id: String,
    pub canonical_test: String,
    pub cases: Vec<String>,
    pub level: String,
    pub view: BTreeMap<String, JsonValue>,
    pub read_keys: BTreeMap<String, BTreeSet<String>>,
    pub inputs: BTreeMap<String, String>,
    pub self_stubbed: bool,
    pub in_mutation: bool,
    pub resolved_dir: String,
    pub(crate) accessed_view: Cell<bool>,
    pub(crate) when_reads: RefCell<BTreeMap<String, BTreeSet<String>>>,
    pub(crate) observations: BTreeMap<String, JsonValue>,
    pub(crate) obs_frames: BTreeMap<String, Vec<String>>,
}

impl DriftContext {
    pub(crate) fn new(opts: &RunOptions, canon: String, view: BTreeMap<String, JsonValue>, in_mutation: bool) -> Self {
        Self {
            contract_id: opts.contract.clone(),
            test_id: opts.test.clone(),
            canonical_test: canon,
            cases: opts.cases.clone(),
            level: if opts.level.is_empty() { "unit".into() } else { opts.level.clone() },
            view,
            read_keys: BTreeMap::new(),
            inputs: BTreeMap::new(),
            self_stubbed: false,
            in_mutation,
            resolved_dir: opts.resolved_dir.clone(),
            accessed_view: Cell::new(false),
            when_reads: RefCell::new(BTreeMap::new()),
            observations: BTreeMap::new(),
            obs_frames: BTreeMap::new(),
        }
    }
}

fn sanitize_obs_value(v: &JsonValue, d: usize, root: bool) -> Option<JsonValue> {
    if d > 6 { return None; }
    match v {
        JsonValue::Null | JsonValue::Bool(_) => Some(v.clone()),
        JsonValue::Number(n) if n.is_finite() => Some(JsonValue::Number(*n)),
        JsonValue::Str(s) if s.chars().count() <= 1024 => Some(JsonValue::Str(s.clone())),
        JsonValue::Array(a) if a.len() <= 64 => a.iter().map(|x| sanitize_obs_value(x, d + 1, false)).collect::<Option<Vec<_>>>().map(JsonValue::Array),
        JsonValue::Object(m) if m.len() <= 64 => {
            let mut o = BTreeMap::new();
            for (k, val) in m {
                if root && (k == "_when_env" || k == "_frame") { continue; }
                let ek = if k.starts_with('$') { format!("${}", k) } else { k.clone() };
                o.insert(ek, sanitize_obs_value(val, d + 1, false)?);
            }
            Some(JsonValue::Object(o))
        }
        _ => None,
    }
}

pub(crate) fn herr(m: impl Into<String>) -> TestError { TestError::Harness(m.into()) }
pub(crate) fn aerr(m: impl Into<String>) -> TestError { TestError::Assertion(m.into()) }
pub(crate) fn ctx_err<E: std::fmt::Display>(ctx: &str) -> impl FnOnce(E) -> TestError + '_ {
    move |e| herr(format!("{ctx}: {e}"))
}

fn ptr_hits_array(root: &JsonValue, ptr: &str) -> bool {
    let norm = normalize_pointer(ptr);
    let Some(rest) = norm.strip_prefix('/') else { return false; };
    let mut cur = root;
    for raw_seg in rest.split('/') {
        match cur {
            JsonValue::Object(m) => match m.get(&unescape_pointer(raw_seg)) { Some(n) => cur = n, None => return false },
            JsonValue::Array(_) => return true,
            _ => return false,
        }
    }
    false
}

fn project_obs_doc(doc: &JsonValue, then_map: &BTreeMap<String, JsonValue>, proj_then: &BTreeMap<String, String>) -> JsonValue {
    let needs_root = then_map.iter().any(|(p, e)| {
        !proj_then.contains_key(p)
            && e.as_object().is_some_and(|m| m.contains_key("allowed_keys") || m.contains_key("forbid_keys") || m.contains_key("keys"))
            && doc.as_object().and_then(|o| o.get(p)).and_then(|v| v.as_object()).is_none()
    });
    if needs_root { return doc.clone(); }
    let mut out = BTreeMap::new();
    let ptrs = then_map.keys().map(|p| proj_then.get(p).cloned().unwrap_or_else(|| format!("/{}", escape_pointer(p))))
        .chain(proj_then.iter().filter(|(k, _)| !then_map.contains_key(*k)).map(|(_, v)| v.clone()));
    for ptr in ptrs {
        if ptr_hits_array(doc, &ptr) { return doc.clone(); }
        if let Some(v) = resolve_pointer(doc, &ptr) { write_pointer(&mut out, &ptr, v.clone()); }
    }
    JsonValue::Object(out)
}

pub use probes::{
    canonical_rust_test_id, canonical_test_id, discover_binary_tests, parse_list_terse_output,
};
pub(crate) use checks::load_contract_plan_stub;
pub(crate) use probes::load_contract_view;

fn resolve_env_map() -> Result<BTreeMap<String, String>, TestError> {
    let (raw, pk) = (env_trim("DRIFT_ENV"), env_trim("DRIFT_PROOF_KEY"));
    if raw.is_empty() && pk != "1" && pk != "true" { return Ok(BTreeMap::new()); }
    let mut base: BTreeMap<String, String> = [
        ("adapter", ADAPTER_ID), ("config", "default"), ("deps", "none"),
        ("drift", BRIDGE_VERSION), ("policy", "core@1"), ("runner", "cargo-test"), ("toolchain", "rustc"),
    ].into_iter().map(|(k, v)| (k.into(), v.into())).collect();
    if !raw.is_empty() {
        let doc = parse_json(&raw).map_err(|_| herr("DRIFT_ENV must be valid JSON"))?;
        let obj = doc.as_object().ok_or_else(|| herr("DRIFT_ENV must be a JSON object"))?;
        for (k, v) in obj {
            let s = v.as_str().map(str::trim).filter(|s| !s.is_empty() && ENV_KEYS.contains(&k.as_str()))
                .ok_or_else(|| herr(format!("invalid DRIFT_ENV key '{k}'")))?;
            base.insert(k.clone(), s.into());
        }
    }
    Ok(base)
}

impl DriftContext {
    pub fn check_projection(&mut self, case_id: &str, payload_json: &str) -> Result<(), TestError> {
        self.observations.remove(case_id);
        let (when_map, then_map) = {
            let cm = self.case_map(case_id)?;
            let wm = cm.get("when").and_then(|v| v.as_object()).cloned().unwrap_or_default();
            let tm = cm
                .get("then")
                .and_then(|v| v.as_object())
                .cloned()
                .ok_or_else(|| {
                    TestError::assertion(format!("case '{}' has no then table", case_id))
                })?;
            (wm, tm)
        };
        let mut doc = parse_json(payload_json)
            .map_err(|e| TestError::assertion(format!("payload is not valid JSON: {}", e)))?;
        if let JsonValue::Object(ref mut obj) = doc {
            if !obj.contains_key("when") && !obj.contains_key("before") {
                let mut w_env = BTreeMap::new();
                for (wk, wv) in &when_map {
                    if let Some(wm) = wv.as_object() {
                        if let Some(eq_v) = wm.get("eq") {
                            if !wm.contains_key("peer") && !wm.contains_key("eq_field") {
                                w_env.insert(wk.clone(), eq_v.clone());
                            }
                        }
                    } else {
                        w_env.insert(wk.clone(), wv.clone());
                    }
                }
                obj.insert("_when_env".to_string(), JsonValue::Object(w_env));
            }
        }
        let is_ui_obs = doc.as_object().and_then(|o| o.get("schema")).and_then(|v| v.as_str()) == Some("drift.ui-observation/1");
        if let Some(obj) = doc.as_object() {
            let sf = obj.get("surface_found").or_else(|| obj.get("surfaceFound")).and_then(|v| v.as_bool());
            if sf == Some(false) || (is_ui_obs && sf != Some(true)) {
                return Err(TestError::assertion(format!("{}.{}: surface.missing", self.contract_id, case_id)));
            }
            let sto = obj.get("collector").and_then(|c| c.as_object()).and_then(|c| c.get("settle_timed_out")).and_then(|v| v.as_bool()) == Some(true)
                || obj.get("evidence").and_then(|e| e.as_object()).and_then(|e| e.get("unverifiable_reasons")).and_then(|r| r.as_array()).is_some_and(|a| a.iter().any(|x| x.as_str() == Some("ui.settle_timeout")));
            if sto { return Err(TestError::assertion(format!("{}.{}: ui.settle_timeout", self.contract_id, case_id))); }
        }
        let adapter_caps: Option<Vec<String>> = doc.as_object().and_then(|o| o.get("adapter")).and_then(|a| a.as_object()).and_then(|a| a.get("capabilities")).and_then(|c| c.as_array())
            .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect());
        let proj_then = extract_then_projections(&self.view);
        let mut used_plan = false;
        if !self.in_mutation && !is_ui_obs && adapter_caps.is_none() {
            if let Some(pc) = checks::load_contract_plan_case(&self.contract_id, &self.resolved_dir, &self.view, case_id) {
                let (ok, preds) = checks::eval_compiled_plan_case(&self.contract_id, case_id, &pc, &doc).map_err(TestError::assertion)?;
                if ok { for p in preds { self.mark_read(case_id, &p); } used_plan = true; }
            }
        }
        if !used_plan {
        for (pred, expected) in &then_map {
            let lowered;
            let expected = if let Some(raw) = expected.as_object().filter(|_| is_relational_table(expected)) {
                lowered = JsonValue::Object(checks::normalize_constraint_03(raw, Some(&self.view), pred).map_err(TestError::assertion)?);
                &lowered
            } else { expected };
            self.mark_read(case_id, pred);
            let default_ptr = format!("/{}", escape_pointer(pred));
            let ptr = proj_then.get(pred).unwrap_or(&default_ptr);
            if let Some(ref caps) = adapter_caps {
                if let Some(rc) = required_ui_capability_for(pred, ptr) {
                    if !caps.iter().any(|c| c == rc) {
                        return Err(TestError::assertion(format!("{}.{}: ui.capability_unverifiable:{} for then.{}", self.contract_id, case_id, rc, pred)));
                    }
                }
            }
            if is_relational_table(expected) && expected.as_object().is_some_and(|m| m.contains_key("allowed_keys") || m.contains_key("forbid_keys")) && !proj_then.contains_key(pred) {
                let target = doc.as_object().and_then(|o| o.get(pred)).filter(|s| s.as_object().is_some()).unwrap_or(&doc);
                let rm = expected.as_object().ok_or_else(|| TestError::harness(format!("invalid relational table on '{}'", pred)))?;
                check_relational_leaf(&doc, target, rm, &proj_then, pred).map_err(TestError::assertion)?;
                continue;
            }
            let actual = resolve_pointer(&doc, ptr).ok_or_else(|| TestError::assertion(format!("missing pointer '{}' for predicate '{}'", ptr, pred)))?;
            if is_ui_obs && !matches!(expected, JsonValue::Null) && matches!(actual, JsonValue::Null) {
                return Err(TestError::assertion(format!(
                    "{}.{}: unverifiable then.{}: unmeasured value at \"{}\"",
                    self.contract_id, case_id, pred, ptr
                )));
            }
            if is_relational_table(expected) {
                let rel_map = expected.as_object().ok_or_else(|| {
                    TestError::harness(format!("invalid relational table on '{}'", pred))
                })?;
                check_relational_leaf(&doc, actual, rel_map, &proj_then, pred)
                    .map_err(TestError::assertion)?;
            } else if !values_equal(actual, expected) {
                return Err(TestError::assertion(format!(
                    "mismatch on '{}' ({}): got {}, expected {}",
                    pred,
                    ptr,
                    actual.to_json_string(),
                    expected.to_json_string()
                )));
            }
        }
        }
        if let Some(fr_obj) = doc.as_object().and_then(|m| m.get("_frame")) {
            if let Some(fmap) = fr_obj.as_object() {
                let strict = !fmap.values().any(probes::is_unobserved_frame_entry);
                self.check_frame_with_mode(case_id, &fr_obj.to_json_string(), strict)?;
            }
        }
        if !self.in_mutation
            && !self.self_stubbed
            && !is_ui_obs
            && self.view.get("drift").and_then(|v| v.as_str()) == Some("0.3")
        {
            let proj_doc = project_obs_doc(&doc, &then_map, &proj_then);
            if let Some(clean) = sanitize_obs_value(&proj_doc, 0, true) {
                if clean.to_json_string().len() <= 4096 {
                    self.observations.insert(case_id.to_string(), clean);
                }
            }
        }
        Ok(())
    }
}

pub fn run_drift_case<F>(opts: RunOptions, cb: F) -> Result<String, TestError>
where
    F: Fn(&mut DriftContext) -> Result<(), TestError>,
{
    run_drift_case_with_fixture(opts, || Ok(()), |ctx, ()| cb(ctx))
}

pub fn run_drift_case_with_fixture<T, S, F>(
    opts: RunOptions,
    setup: S,
    cb: F,
) -> Result<String, TestError>
where
    S: Fn() -> Result<T, TestError>,
    F: Fn(&mut DriftContext, T) -> Result<(), TestError>,
{
    if opts.contract.trim().is_empty() || opts.cases.is_empty() {
        return Err(TestError::harness("contract and cases are required"));
    }
    let (cls, mth, canon_test) = canonical_test_id(&opts.test)?;
    let base_view = load_contract_view(&opts.contract, &opts.resolved_dir)?;

    // Isolated subprocess single-mutant execution (DRIFT_SINGLE_MUTANT):
    let single_mid = env_trim("DRIFT_SINGLE_MUTANT");
    if !single_mid.is_empty() {
        let abort = |msg: &str| -> ! {
            write_single_mutant_outcome(&single_mid, "harness_error", msg);
            eprintln!("harness error: {msg}");
            process::exit(99);
        };
        let found = find_single_mutant_in_manifest(&opts.contract, &single_mid).unwrap_or_else(|e| abort(e.message()));
        let Some((mcase, mpath, mafter)) = found else { return Ok("skipped".into()); };
        if !opts.cases.iter().any(|c| c == &mcase) { return Ok("skipped".into()); }
        let mut_view = apply_mutant_to_view(&base_view, &mcase, &mpath, &mafter).unwrap_or_else(|e| abort(e.message()));
        let mut mut_ctx = DriftContext::new(&opts, canon_test, mut_view, true);
        return match execute_callback_with_fixture(&mut mut_ctx, &setup, &cb) {
            Ok(()) => { write_single_mutant_outcome(&single_mid, "survived", ""); Ok("survived".into()) }
            Err(TestError::Assertion(msg)) => { write_single_mutant_outcome(&single_mid, "killed", &msg); Err(TestError::Assertion(msg)) }
            Err(TestError::Harness(msg)) => abort(&msg),
        };
    }

    let digest = base_view
        .get("digest")
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .to_string();
    let ev_raw = if !opts.events_dir.trim().is_empty() {
        opts.events_dir.trim().to_string()
    } else {
        env_trim("DRIFT_EVENTS")
    };
    let ev_dir = if !ev_raw.is_empty() {
        ev_raw
    } else if opts.resolved_dir.trim().is_empty() && env_trim("DRIFT_RESOLVED").is_empty() {
        if let Ok(cwd) = env::current_dir() {
            if let Some(sd) = probes::resolve_state_root(&cwd)? {
                let d1 = sd.join(".drift").join("events");
                if d1.is_dir() {
                    d1.to_string_lossy().into_owned()
                } else {
                    sd.join(".drift-work").join("events").to_string_lossy().into_owned()
                }
            } else {
                String::new()
            }
        } else {
            String::new()
        }
    } else {
        String::new()
    };

    let mut ctx = DriftContext::new(&opts, canon_test.clone(), base_view.clone(), false);

    let mut res = execute_callback_with_fixture(&mut ctx, &setup, &cb);
    if res.is_ok() && (opts.strict_when || matches!(env::var("DRIFT_STRICT_WHEN").as_deref(), Ok("1" | "true"))) {
        for cid in &ctx.cases {
            if let Ok(u) = ctx.unread_when(cid) {
                if !u.is_empty() {
                    let ks = u.iter().map(|k| format!("when.{}", k)).collect::<Vec<_>>().join(", ");
                    res = Err(TestError::assertion(format!("{}.{}: unread {}", opts.contract, cid, ks)));
                    break;
                }
            }
        }
    }
    if let Err(TestError::Harness(msg)) = &res { return Err(TestError::Harness(msg.clone())); }
    let outcome = if res.is_ok() { "passed" } else { "failed" };
    if res.is_ok() { run_mutants(&opts, &base_view, &cls, &canon_test, &mth, &setup, &cb)?; }

    if !ev_dir.is_empty() {
        let mut ev = BTreeMap::new();
        ev.insert("cases".into(), JsonValue::Array(opts.cases.iter().cloned().map(JsonValue::Str).collect()));
        ev.insert("contract".into(), JsonValue::Str(opts.contract.clone()));
        if !digest.is_empty() { ev.insert("digest".into(), JsonValue::Str(digest)); }
        ev.insert("level".into(), JsonValue::Str(ctx.level.clone()));
        ev.insert("outcome".into(), JsonValue::Str(outcome.into()));
        let read_list = if outcome == "passed" { ctx.fully_read_cases() } else { Vec::new() };
        if !read_list.is_empty() {
            ev.insert("read".into(), JsonValue::Array(read_list.iter().cloned().map(JsonValue::Str).collect()));
        }
        if base_view.get("drift").and_then(|v| v.as_str()) == Some("0.3") {
            const S03: &[&str] = &["rel-keys-guard/1", "rel-linear-balance/1", "rel-peer-sum/1", "rel-series/1", "rel-tol/1", "unit-conversion/1"];
            if let Some(ra) = base_view.get("required_capabilities").and_then(|v| v.as_array()) {
                for s in ra.iter().filter_map(|x| x.as_str()) {
                    if !S03.contains(&s) { return Err(TestError::harness(format!("bridge.capability_unsupported:{}", s))); }
                }
            }
            ev.insert("schema".into(), JsonValue::Str("0.3".into()));
            ev.insert("capabilities".into(), JsonValue::Array(S03.iter().map(|s| JsonValue::Str((*s).into())).collect()));
            if outcome == "passed" && !ctx.self_stubbed && !read_list.is_empty() {
                let mut obs_out = BTreeMap::new();
                for cid in &read_list {
                    let Some(pay) = ctx.observations.get(cid) else { continue };
                    let fw = ctx.obs_frames.get(cid);
                    if !forbidden_writes_of(&base_view, cid).is_empty() && fw.is_none() { continue; }
                    let mut eo = BTreeMap::new();
                    eo.insert("schema".into(), JsonValue::Str("drift.observation/1".into()));
                    eo.insert("outcome".into(), JsonValue::Str("returned".into()));
                    eo.insert("payload".into(), pay.clone());
                    if let Some(ws) = fw {
                        let mut fm = BTreeMap::new();
                        fm.insert("writes".into(), JsonValue::Array(ws.iter().cloned().map(JsonValue::Str).collect()));
                        eo.insert("frame".into(), JsonValue::Object(fm));
                    }
                    obs_out.insert(cid.clone(), JsonValue::Object(eo));
                }
                if !obs_out.is_empty() { ev.insert("observations".into(), JsonValue::Object(obs_out)); }
            }
        }
        ev.insert("test".into(), JsonValue::Str(opts.test.clone()));
        update_shard_and_meta(&ev_dir, &JsonValue::Object(ev).to_json_string(), &cls, &canon_test, &ctx.inputs, ctx.self_stubbed)?;
    }

    if let Err(err) = res {
        return Err(err);
    }

    Ok(outcome.to_string())
}

pub const BRIDGE_RUNTIME_BASELINE: &str = "rust-2024";

pub const BRIDGE_CAPABILITIES: &[&str] = &[
    "allowed_keys",
    "case_frames",
    "counterexample_replay",
    "forbid_keys",
    "inventory_sidecar",
    "mutants",
    "not_in",
    "predicates",
    "projections",
    "relational_bounds",
    "stubs",
];

pub fn require_capabilities(required: &[&str]) -> Result<(), TestError> {
    for cap in required {
        let k = cap.trim();
        if k.is_empty() || !BRIDGE_CAPABILITIES.contains(&k) {
            return Err(TestError::harness(format!(
                "bridge.capability_unsupported:{}",
                k
            )));
        }
    }
    Ok(())
}

