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
use std::cell::Cell;
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::panic::{self, AssertUnwindSafe};
use std::path::{Path, PathBuf};
use std::process::{self, Command};
use std::sync::{Mutex, OnceLock};

pub const ADAPTER_ID: &str = "drift_rust@0.7.0";
pub const BRIDGE_VERSION: &str = "0.7.0";

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
}

impl Default for RunOptions {
    fn default() -> Self {
        Self { contract: String::new(), test: String::new(), cases: Vec::new(), level: "unit".to_string(), resolved_dir: String::new(), events_dir: String::new(), mutation_events_dir: String::new(), mutant_mode: MutantMode::Auto, cargo_test_filter: String::new() }
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
}

pub fn canonical_rust_test_id(crate_name: &str, module_path: &str, fn_name: &str) -> String {
    let clean_crate = crate_name.trim().replace('-', "_");
    let clean_mod = module_path.trim().trim_matches(':');
    let clean_fn = fn_name.trim();
    if clean_mod.is_empty() || clean_mod == clean_crate {
        format!("{}#{}", clean_crate, clean_fn)
    } else if clean_mod.starts_with(&format!("{}::", clean_crate)) {
        format!("{}#{}", clean_mod, clean_fn)
    } else {
        format!("{}::{}#{}", clean_crate, clean_mod, clean_fn)
    }
}

pub fn canonical_test_id(test: &str) -> Result<(String, String, String), TestError> {
    let trimmed = test.trim();
    let Some(hash_idx) = trimmed.find('#') else {
        return Err(TestError::harness(format!(
            "test id '{}' must have form <class>#<method>",
            test
        )));
    };
    if hash_idx == 0 || hash_idx + 1 >= trimmed.len() {
        return Err(TestError::harness(format!(
            "test id '{}' must have form <class>#<method>",
            test
        )));
    }
    let cls = &trimmed[..hash_idx];
    let mut mth = &trimmed[hash_idx + 1..];
    for ch in ['(', '['] {
        if let Some(idx) = mth.find(ch) {
            mth = &mth[..idx];
        }
    }
    let mth = mth.trim();
    if cls.is_empty() || mth.is_empty() || cls.contains('#') || mth.contains('#') {
        return Err(TestError::harness(format!("invalid test id '{}'", test)));
    }
    Ok((
        cls.to_string(),
        mth.to_string(),
        format!("{}#{}", cls, mth),
    ))
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
        } else if mod_part.starts_with(&format!("{}::", clean_crate)) || clean_crate.is_empty() {
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

pub fn discover_binary_tests(crate_name: &str, events_dir: &str) -> Result<(Vec<String>, Vec<String>), TestError> {
    if env::var("DRIFT_IN_LIST_DISCOVERY").as_deref() == Ok("1") {
        return Ok((Vec::new(), Vec::new()));
    }
    let exe = env::current_exe().map_err(|e| TestError::harness(e.to_string()))?;
    let out = Command::new(&exe)
        .args(["--list", "--format=terse"])
        .env("DRIFT_IN_LIST_DISCOVERY", "1")
        .output()
        .map_err(|e| TestError::harness(format!("failed to run --list discovery: {}", e)))?;
    let stdout = String::from_utf8_lossy(&out.stdout);
    let (classes, tests) = parse_list_terse_output(crate_name, &stdout);
    let ev_dir = if !events_dir.trim().is_empty() {
        events_dir.trim().to_string()
    } else {
        env::var("DRIFT_EVENTS").unwrap_or_default().trim().to_string()
    };
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

fn load_contract_view(
    contract_id: &str,
    resolved_dir: &str,
) -> Result<BTreeMap<String, JsonValue>, TestError> {
    let rdir = if !resolved_dir.trim().is_empty() {
        resolved_dir.trim().to_string()
    } else {
        env::var("DRIFT_RESOLVED")
            .unwrap_or_default()
            .trim()
            .to_string()
    };
    // Fail-closed when DRIFT_RESOLVED / resolved_dir is explicitly configured.
    if !rdir.is_empty() {
        let p = Path::new(&rdir).join(format!("{}.json", contract_id));
        let txt = fs::read_to_string(&p).map_err(|e| {
            TestError::harness(format!(
                "cannot read resolved view '{}': {}",
                p.display(),
                e
            ))
        })?;
        let doc = parse_json(&txt).map_err(|e| {
            TestError::harness(format!("invalid JSON in '{}': {}", p.display(), e))
        })?;
        return match doc {
            JsonValue::Object(m) => Ok(m),
            _ => Err(TestError::harness(format!(
                "resolved view '{}' is not a JSON object",
                p.display()
            ))),
        };
    }

    if let Ok(guard) = fallback_view_cache().lock() {
        if let Some(cached) = guard.get(contract_id) {
            return Ok(cached.clone());
        }
    }

    let mut dir = env::current_dir().map_err(|e| TestError::harness(e.to_string()))?;
    let mut toml_path: Option<PathBuf> = None;
    loop {
        let cand = dir
            .join(".drift")
            .join("contracts")
            .join(format!("{}.toml", contract_id));
        if cand.is_file() {
            toml_path = Some(cand);
            break;
        }
        if !dir.pop() {
            break;
        }
    }
    let toml_path = toml_path.ok_or_else(|| {
        TestError::harness(format!("cannot locate contract '{}.toml'", contract_id))
    })?;
    let cli = find_drift_cli();
    let out = Command::new(&cli)
        .arg("show")
        .arg(&toml_path)
        .arg("--as")
        .arg("json")
        .output()
        .map_err(|e| TestError::harness(format!("failed to invoke '{}': {}", cli, e)))?;
    if !out.status.success() {
        return Err(TestError::harness(format!(
            "drift show failed for '{}': {}",
            toml_path.display(),
            String::from_utf8_lossy(&out.stderr)
        )));
    }
    let stdout = String::from_utf8_lossy(&out.stdout);
    let doc = parse_json(&stdout).map_err(|e| {
        TestError::harness(format!(
            "invalid JSON from drift show '{}': {}",
            toml_path.display(),
            e
        ))
    })?;
    let JsonValue::Object(map) = doc else {
        return Err(TestError::harness(
            "drift show output is not a JSON object".to_string(),
        ));
    };
    if let Ok(mut guard) = fallback_view_cache().lock() {
        guard.insert(contract_id.to_string(), map.clone());
    }
    Ok(map)
}

pub(crate) use checks::load_contract_plan_stub;

fn resolve_env_map() -> Result<BTreeMap<String, String>, TestError> {
    let raw = env::var("DRIFT_ENV").unwrap_or_default().trim().to_string();
    let pk = env::var("DRIFT_PROOF_KEY")
        .unwrap_or_default()
        .trim()
        .to_string();
    if raw.is_empty() && pk != "1" && pk != "true" {
        return Ok(BTreeMap::new());
    }
    let mut base = BTreeMap::new();
    base.insert("adapter".to_string(), ADAPTER_ID.to_string());
    base.insert("config".to_string(), "default".to_string());
    base.insert("deps".to_string(), "none".to_string());
    base.insert("drift".to_string(), BRIDGE_VERSION.to_string());
    base.insert("policy".to_string(), "core@1".to_string());
    base.insert("runner".to_string(), "cargo-test".to_string());
    base.insert("toolchain".to_string(), "rustc".to_string());
    if !raw.is_empty() {
        let doc = parse_json(&raw)
            .map_err(|_| TestError::harness("DRIFT_ENV must be valid JSON"))?;
        let Some(obj) = doc.as_object() else {
            return Err(TestError::harness("DRIFT_ENV must be a JSON object"));
        };
        for (k, v) in obj {
            let Some(s) = v.as_str() else {
                return Err(TestError::harness(format!("invalid DRIFT_ENV key '{}'", k)));
            };
            if !ENV_KEYS.contains(&k.as_str()) || s.trim().is_empty() {
                return Err(TestError::harness(format!("invalid DRIFT_ENV key '{}'", k)));
            }
            base.insert(k.clone(), s.trim().to_string());
        }
    }
    Ok(base)
}

impl DriftContext {
    pub fn check_projection(&mut self, case_id: &str, payload_json: &str) -> Result<(), TestError> {
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
        let is_ui_obs = doc
            .as_object()
            .and_then(|o| o.get("schema"))
            .and_then(|v| v.as_str())
            == Some("drift.ui-observation/1");
        if let Some(obj) = doc.as_object() {
            let sf_false = obj.get("surface_found").and_then(|v| v.as_bool()) == Some(false)
                || obj.get("surfaceFound").and_then(|v| v.as_bool()) == Some(false);
            let sf_true = obj.get("surface_found").and_then(|v| v.as_bool()) == Some(true)
                || obj.get("surfaceFound").and_then(|v| v.as_bool()) == Some(true);
            if sf_false || (is_ui_obs && !sf_true) {
                return Err(TestError::assertion(format!(
                    "{}.{}: surface.missing",
                    self.contract_id, case_id
                )));
            }
            let settle_timed_out = obj
                .get("collector")
                .and_then(|c| c.as_object())
                .and_then(|c| c.get("settle_timed_out"))
                .and_then(|v| v.as_bool())
                == Some(true)
                || obj
                    .get("evidence")
                    .and_then(|e| e.as_object())
                    .and_then(|e| e.get("unverifiable_reasons"))
                    .and_then(|r| r.as_array())
                    .is_some_and(|arr| arr.iter().any(|x| x.as_str() == Some("ui.settle_timeout")));
            if settle_timed_out {
                return Err(TestError::assertion(format!(
                    "{}.{}: ui.settle_timeout",
                    self.contract_id, case_id
                )));
            }
        }
        let adapter_caps: Option<Vec<String>> = doc
            .as_object()
            .and_then(|o| o.get("adapter"))
            .and_then(|a| a.as_object())
            .and_then(|a| a.get("capabilities"))
            .and_then(|c| c.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            });
        let proj_then = extract_then_projections(&self.view);
        let mut used_plan = false;
        if !self.in_mutation && !is_ui_obs && adapter_caps.is_none() {
            if let Some(pc) = checks::load_contract_plan_case(&self.contract_id, &self.resolved_dir, &self.view, case_id) {
                let (ok, preds) = checks::eval_compiled_plan_case(&self.contract_id, case_id, &pc, &doc)
                    .map_err(TestError::assertion)?;
                if ok {
                    for p in preds {
                        self.mark_read(case_id, &p);
                    }
                    used_plan = true;
                }
            }
        }
        if !used_plan {
        for (pred, expected) in &then_map {
            let lowered;
            let expected = if let Some(raw) = expected.as_object().filter(|_| is_relational_table(expected)) {
                lowered = JsonValue::Object(checks::normalize_constraint_03(raw, Some(&self.view), pred)
                    .map_err(TestError::assertion)?);
                &lowered
            } else {
                expected
            };
            self.mark_read(case_id, pred);
            let default_ptr = format!("/{}", escape_pointer(pred));
            let ptr = proj_then.get(pred).unwrap_or(&default_ptr);
            if let Some(ref caps) = adapter_caps {
                if let Some(req_cap) = required_ui_capability_for(pred, ptr) {
                    if !caps.iter().any(|c| c == req_cap) {
                        return Err(TestError::assertion(format!(
                            "{}.{}: ui.capability_unverifiable:{} for then.{}",
                            self.contract_id, case_id, req_cap, pred
                        )));
                    }
                }
            }
            if is_relational_table(expected)
                && expected
                    .as_object()
                    .is_some_and(|m| m.contains_key("allowed_keys") || m.contains_key("forbid_keys"))
                && !proj_then.contains_key(pred)
            {
                let mut target = &doc;
                if let Some(obj) = doc.as_object() {
                    if let Some(sub) = obj.get(pred) {
                        if sub.as_object().is_some() {
                            target = sub;
                        }
                    }
                }
                let rel_map = expected.as_object().ok_or_else(|| {
                    TestError::harness(format!("invalid relational table on '{}'", pred))
                })?;
                check_relational_leaf(&doc, target, rel_map, &proj_then, pred)
                    .map_err(TestError::assertion)?;
                continue;
            }
            let default_ptr = format!("/{}", escape_pointer(pred));
            let ptr = proj_then.get(pred).unwrap_or(&default_ptr);
            let actual = resolve_pointer(&doc, ptr).ok_or_else(|| {
                TestError::assertion(format!(
                    "missing pointer '{}' for predicate '{}'",
                    ptr, pred
                ))
            })?;
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
    if let Ok(single_mid) = env::var("DRIFT_SINGLE_MUTANT") {
        let single_mid = single_mid.trim();
        if !single_mid.is_empty() {
            let found = match find_single_mutant_in_manifest(&opts.contract, single_mid) {
                Ok(v) => v,
                Err(e) => {
                    write_single_mutant_outcome(single_mid, "harness_error", e.message());
                    eprintln!("harness error: {}", e.message());
                    process::exit(99);
                }
            };
            let Some((mcase, mpath, mafter)) = found else {
                return Ok("skipped".to_string());
            };
            if !opts.cases.iter().any(|c| c == &mcase) {
                return Ok("skipped".to_string());
            }
            let mut_view = match apply_mutant_to_view(&base_view, &mcase, &mpath, &mafter) {
                Ok(v) => v,
                Err(e) => {
                    write_single_mutant_outcome(single_mid, "harness_error", e.message());
                    eprintln!("harness error: {}", e.message());
                    process::exit(99);
                }
            };
            let mut mut_ctx = DriftContext {
                contract_id: opts.contract.clone(),
                test_id: opts.test.clone(),
                canonical_test: canon_test,
                cases: opts.cases.clone(),
                level: if opts.level.is_empty() {
                    "unit".to_string()
                } else {
                    opts.level.clone()
                },
                view: mut_view,
                read_keys: BTreeMap::new(),
                inputs: BTreeMap::new(),
                self_stubbed: false,
                in_mutation: true,
                resolved_dir: opts.resolved_dir.clone(),
                accessed_view: Cell::new(false),
            };
            match execute_callback_with_fixture(&mut mut_ctx, &setup, &cb) {
                Ok(()) => {
                    write_single_mutant_outcome(single_mid, "survived", "");
                    return Ok("survived".to_string());
                }
                Err(TestError::Assertion(msg)) => {
                    write_single_mutant_outcome(single_mid, "killed", &msg);
                    return Err(TestError::Assertion(msg));
                }
                Err(TestError::Harness(msg)) => {
                    write_single_mutant_outcome(single_mid, "harness_error", &msg);
                    eprintln!("harness error: {}", msg);
                    process::exit(99);
                }
            }
        }
    }

    let digest = base_view
        .get("digest")
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .to_string();
    let ev_dir = if !opts.events_dir.trim().is_empty() {
        opts.events_dir.trim().to_string()
    } else {
        env::var("DRIFT_EVENTS")
            .unwrap_or_default()
            .trim()
            .to_string()
    };

    let mut ctx = DriftContext {
        contract_id: opts.contract.clone(),
        test_id: opts.test.clone(),
        canonical_test: canon_test.clone(),
        cases: opts.cases.clone(),
        level: if opts.level.is_empty() {
            "unit".to_string()
        } else {
            opts.level.clone()
        },
        view: base_view.clone(),
        read_keys: BTreeMap::new(),
        inputs: BTreeMap::new(),
        self_stubbed: false,
        in_mutation: false,
        resolved_dir: opts.resolved_dir.clone(),
        accessed_view: Cell::new(false),
    };

    let res = execute_callback_with_fixture(&mut ctx, &setup, &cb);
    if let Err(TestError::Harness(msg)) = &res {
        return Err(TestError::Harness(msg.clone()));
    }
    let outcome = if res.is_ok() { "passed" } else { "failed" };

    if res.is_ok() {
        run_mutants(&opts, &base_view, &cls, &canon_test, &mth, &setup, &cb)?;
    }

    if !ev_dir.is_empty() {
        let mut ev = BTreeMap::new();
        ev.insert(
            "cases".to_string(),
            JsonValue::Array(opts.cases.iter().cloned().map(JsonValue::Str).collect()),
        );
        ev.insert(
            "contract".to_string(),
            JsonValue::Str(opts.contract.clone()),
        );
        if !digest.is_empty() {
            ev.insert("digest".to_string(), JsonValue::Str(digest));
        }
        ev.insert("level".to_string(), JsonValue::Str(ctx.level.clone()));
        ev.insert("outcome".to_string(), JsonValue::Str(outcome.to_string()));
        if outcome == "passed" {
            let read_list = ctx.fully_read_cases();
            if !read_list.is_empty() {
                ev.insert(
                    "read".to_string(),
                    JsonValue::Array(read_list.into_iter().map(JsonValue::Str).collect()),
                );
            }
        }
        if base_view.get("drift").and_then(|v| v.as_str()) == Some("0.3") {
            let supported_03 = [
                "rel-keys-guard/1",
                "rel-linear-balance/1",
                "rel-peer-sum/1",
                "rel-series/1",
                "rel-tol/1",
                "unit-conversion/1",
            ];
            if let Some(req_arr) = base_view.get("required_capabilities").and_then(|v| v.as_array()) {
                for item in req_arr {
                    if let Some(s) = item.as_str() {
                        if !supported_03.contains(&s) {
                            return Err(TestError::harness(format!("bridge.capability_unsupported:{}", s)));
                        }
                    }
                }
            }
            ev.insert("schema".to_string(), JsonValue::Str("0.3".to_string()));
            ev.insert(
                "capabilities".to_string(),
                JsonValue::Array(supported_03.iter().map(|s| JsonValue::Str((*s).to_string())).collect()),
            );
        }
        ev.insert("test".to_string(), JsonValue::Str(opts.test.clone()));
        update_shard_and_meta(
            &ev_dir,
            &JsonValue::Object(ev).to_json_string(),
            &cls,
            &canon_test,
            &ctx.inputs,
            ctx.self_stubbed,
        )?;
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

