// Zero-dependency compile-once Rust test bridge for DRIFT (SPEC §§9, 25, D253).

pub mod checks;
pub mod json;

use checks::{
    check_relational_leaf, escape_pointer, is_relational_table, normalize_pointer, resolve_pointer,
    synthesize_leaf_witness, unescape_pointer, values_equal, write_pointer,
};
use json::{hash_fixture_bytes, parse_json, sha256_hex, JsonValue};
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::panic::{self, AssertUnwindSafe};
use std::path::{Path, PathBuf};
use std::process::{self, Command};
use std::sync::{Mutex, OnceLock};

pub const ADAPTER_ID: &str = "drift_rust@0.3.2";
pub const BRIDGE_VERSION: &str = "0.3.2";

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
    pub fn assertion(msg: impl Into<String>) -> Self {
        TestError::Assertion(msg.into())
    }

    pub fn harness(msg: impl Into<String>) -> Self {
        TestError::Harness(msg.into())
    }

    pub fn message(&self) -> &str {
        match self {
            TestError::Assertion(s) | TestError::Harness(s) => s.as_str(),
        }
    }
}

impl std::fmt::Display for TestError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TestError::Assertion(s) => write!(f, "{}", s),
            TestError::Harness(s) => write!(f, "harness error: {}", s),
        }
    }
}

impl From<String> for TestError {
    fn from(s: String) -> Self {
        TestError::Assertion(s)
    }
}

impl From<&str> for TestError {
    fn from(s: &str) -> Self {
        TestError::Assertion(s.to_string())
    }
}

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
        Self {
            contract: String::new(),
            test: String::new(),
            cases: Vec::new(),
            level: "unit".to_string(),
            resolved_dir: String::new(),
            events_dir: String::new(),
            mutation_events_dir: String::new(),
            mutant_mode: MutantMode::Auto,
            cargo_test_filter: String::new(),
        }
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
    // Fail-closed when DRIFT_RESOLVED / resolved_dir is explicitly configured (D253).
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

#[derive(Default)]
struct ProcessShardState {
    classes: BTreeSet<String>,
    tests: BTreeSet<String>,
    inputs: BTreeMap<String, BTreeMap<String, String>>,
    self_stubbed: BTreeSet<String>,
    seq: u64,
}

fn shard_states() -> &'static Mutex<BTreeMap<String, ProcessShardState>> {
    static STATES: OnceLock<Mutex<BTreeMap<String, ProcessShardState>>> = OnceLock::new();
    STATES.get_or_init(|| Mutex::new(BTreeMap::new()))
}

fn process_shard_stem() -> String {
    let pid = process::id();
    let bin_name = env::current_exe()
        .ok()
        .and_then(|p| p.file_stem().map(|s| s.to_string_lossy().into_owned()))
        .unwrap_or_else(|| "rust".to_string());
    let clean: String = bin_name
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' })
        .collect();
    format!("rust-{}-{}", clean, pid)
}

fn write_meta_atomic(
    ev_dir: &Path,
    stem: &str,
    st: &ProcessShardState,
) -> Result<(), TestError> {
    let mut meta_obj = BTreeMap::new();
    meta_obj.insert("version".to_string(), JsonValue::Number(1.0));
    meta_obj.insert(
        "classes".to_string(),
        JsonValue::Array(st.classes.iter().cloned().map(JsonValue::Str).collect()),
    );
    meta_obj.insert(
        "tests".to_string(),
        JsonValue::Array(st.tests.iter().cloned().map(JsonValue::Str).collect()),
    );
    let snap = env::var("DRIFT_SNAPSHOT")
        .unwrap_or_default()
        .trim()
        .to_string();
    if snap.len() == 40 || snap.len() == 64 {
        meta_obj.insert("snapshot".to_string(), JsonValue::Str(snap));
    }
    if !st.inputs.is_empty() {
        let mut all_inps = BTreeMap::new();
        for (t, m) in &st.inputs {
            let mut inner = BTreeMap::new();
            for (k, v) in m {
                inner.insert(k.clone(), JsonValue::Str(v.clone()));
            }
            all_inps.insert(t.clone(), JsonValue::Object(inner));
        }
        meta_obj.insert("inputs".to_string(), JsonValue::Object(all_inps));
    }
    if !st.self_stubbed.is_empty() {
        meta_obj.insert(
            "self_stubbed".to_string(),
            JsonValue::Array(st.self_stubbed.iter().cloned().map(JsonValue::Str).collect()),
        );
    }
    let env_map = resolve_env_map()?;
    if !env_map.is_empty() {
        let mut em = BTreeMap::new();
        for (k, v) in env_map {
            em.insert(k, JsonValue::Str(v));
        }
        meta_obj.insert("env".to_string(), JsonValue::Object(em));
    }
    let meta_json = format!("{}\n", JsonValue::Object(meta_obj).to_json_string());
    let tmp_path = ev_dir.join(format!("{}.meta.json.tmp.{}", stem, st.seq));
    let final_path = ev_dir.join(format!("{}.meta.json", stem));
    fs::write(&tmp_path, meta_json.as_bytes())
        .map_err(|e| TestError::harness(format!("failed to write meta tmp: {}", e)))?;
    fs::rename(&tmp_path, &final_path)
        .map_err(|e| TestError::harness(format!("failed to rename meta file: {}", e)))?;
    Ok(())
}

fn record_discovered_inventory(
    events_dir: &str,
    classes: &[String],
    tests: &[String],
) -> Result<(), TestError> {
    let ev_path = Path::new(events_dir);
    fs::create_dir_all(ev_path)
        .map_err(|e| TestError::harness(format!("cannot create events dir: {}", e)))?;
    let stem = process_shard_stem();
    let mut all_states = shard_states()
        .lock()
        .map_err(|_| TestError::harness("shard state mutex poisoned"))?;
    let st = all_states.entry(events_dir.to_string()).or_default();
    st.seq += 1;
    for c in classes {
        st.classes.insert(c.clone());
    }
    for t in tests {
        st.tests.insert(t.clone());
    }
    let jsonl_path = ev_path.join(format!("{}.jsonl", stem));
    if !jsonl_path.exists() {
        fs::write(&jsonl_path, b"")
            .map_err(|e| TestError::harness(format!("cannot create shard jsonl: {}", e)))?;
    }
    write_meta_atomic(ev_path, &stem, st)
}

fn update_shard_and_meta(
    events_dir: &str,
    event_line: &str,
    cls: &str,
    canon_test: &str,
    inputs: &BTreeMap<String, String>,
    self_stubbed: bool,
) -> Result<(), TestError> {
    let ev_path = Path::new(events_dir);
    fs::create_dir_all(ev_path)
        .map_err(|e| TestError::harness(format!("cannot create events dir: {}", e)))?;
    let stem = process_shard_stem();
    let mut all_states = shard_states()
        .lock()
        .map_err(|_| TestError::harness("shard state mutex poisoned"))?;
    let st = all_states.entry(events_dir.to_string()).or_default();
    st.seq += 1;
    st.classes.insert(cls.to_string());
    st.tests.insert(canon_test.to_string());
    if !inputs.is_empty() {
        let entry = st.inputs.entry(canon_test.to_string()).or_default();
        for (k, v) in inputs {
            entry.insert(k.clone(), v.clone());
        }
    }
    if self_stubbed {
        st.self_stubbed.insert(canon_test.to_string());
    }

    let jsonl_path = ev_path.join(format!("{}.jsonl", stem));
    let mut f = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&jsonl_path)
        .map_err(|e| TestError::harness(format!("cannot open shard jsonl: {}", e)))?;
    f.write_all(format!("{}\n", event_line).as_bytes())
        .map_err(|e| TestError::harness(format!("cannot append event line: {}", e)))?;
    f.flush()
        .map_err(|e| TestError::harness(format!("cannot flush event line: {}", e)))?;

    write_meta_atomic(ev_path, &stem, st)
}

fn extract_then_projections(view: &BTreeMap<String, JsonValue>) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    if let Some(proj) = view.get("projections").and_then(|v| v.as_object()) {
        if let Some(t_map) = proj.get("then").and_then(|v| v.as_object()) {
            for (k, v) in t_map {
                if let Some(s) = v.as_str() {
                    out.insert(k.clone(), s.to_string());
                }
            }
        }
    }
    out
}

fn extract_when_projections(view: &BTreeMap<String, JsonValue>) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    if let Some(proj) = view.get("projections").and_then(|v| v.as_object()) {
        if let Some(w_map) = proj.get("when").and_then(|v| v.as_object()) {
            for (k, v) in w_map {
                if let Some(s) = v.as_str() {
                    out.insert(k.clone(), s.to_string());
                }
            }
        }
    }
    out
}

fn build_projected_json(
    view: &BTreeMap<String, JsonValue>,
    case_id: &str,
) -> Result<String, TestError> {
    let cases = view
        .get("cases")
        .and_then(|v| v.as_object())
        .ok_or_else(|| TestError::assertion("contract has no cases"))?;
    let cm = cases
        .get(case_id)
        .and_then(|v| v.as_object())
        .ok_or_else(|| TestError::assertion(format!("unknown case '{}'", case_id)))?;
    if let Some(st) = cm.get("status").and_then(|v| v.as_str()) {
        if !st.is_empty() {
            return Err(TestError::assertion(format!(
                "cannot synthesize stub for {} case '{}'",
                st, case_id
            )));
        }
    }
    let then_map = cm
        .get("then")
        .and_then(|v| v.as_object())
        .ok_or_else(|| TestError::assertion(format!("case '{}' has no then table", case_id)))?;
    let proj_then = extract_then_projections(view);
    let mut built = BTreeMap::new();
    for (pred, expected) in then_map {
        if is_relational_table(expected)
            && expected
                .as_object()
                .is_some_and(|m| m.contains_key("sum_fields"))
        {
            continue;
        }
        let default_ptr = format!("/{}", escape_pointer(pred));
        let ptr = normalize_pointer(proj_then.get(pred).unwrap_or(&default_ptr));
        let val = synthesize_leaf_witness(expected, &built, &proj_then);
        write_pointer(&mut built, &ptr, val);
    }
    for (pred, expected) in then_map {
        if !is_relational_table(expected)
            || !expected
                .as_object()
                .is_some_and(|m| m.contains_key("sum_fields"))
        {
            continue;
        }
        let default_ptr = format!("/{}", escape_pointer(pred));
        let ptr = normalize_pointer(proj_then.get(pred).unwrap_or(&default_ptr));
        let val = synthesize_leaf_witness(expected, &built, &proj_then);
        write_pointer(&mut built, &ptr, val);
    }
    Ok(JsonValue::Object(built).to_json_string())
}

impl DriftContext {
    fn case_map(&self, case_id: &str) -> Result<&BTreeMap<String, JsonValue>, TestError> {
        if !self.cases.iter().any(|c| c == case_id) {
            return Err(TestError::assertion(format!(
                "case '{}' is not tagged on test '{}'",
                case_id, self.test_id
            )));
        }
        let cases = self
            .view
            .get("cases")
            .and_then(|v| v.as_object())
            .ok_or_else(|| {
                TestError::assertion(format!("contract '{}' has no cases", self.contract_id))
            })?;
        cases
            .get(case_id)
            .and_then(|v| v.as_object())
            .ok_or_else(|| {
                TestError::assertion(format!(
                    "contract '{}' has no case '{}'",
                    self.contract_id, case_id
                ))
            })
    }

    fn mark_read(&mut self, case_id: &str, key: &str) {
        self.read_keys
            .entry(case_id.to_string())
            .or_default()
            .insert(key.to_string());
    }

    pub fn when_any(&self, case_id: &str, key: &str) -> Result<&JsonValue, TestError> {
        let cm = self.case_map(case_id)?;
        let w = cm
            .get("when")
            .and_then(|v| v.as_object())
            .ok_or_else(|| TestError::assertion(format!("case '{}' has no when table", case_id)))?;
        w.get(key).ok_or_else(|| {
            TestError::assertion(format!("case '{}' has no when.'{}'", case_id, key))
        })
    }

    pub fn when_str(&self, case_id: &str, key: &str) -> Result<String, TestError> {
        self.when_any(case_id, key)?
            .as_str()
            .map(|s| s.to_string())
            .ok_or_else(|| TestError::assertion(format!("when.'{}' is not a string", key)))
    }

    pub fn when_int(&self, case_id: &str, key: &str) -> Result<i64, TestError> {
        self.when_any(case_id, key)?
            .as_f64()
            .map(|f| f as i64)
            .ok_or_else(|| TestError::assertion(format!("when.'{}' is not a number", key)))
    }

    pub fn find_when_str(&self, case_id: &str, key: &str, fallback: &str) -> String {
        self.when_str(case_id, key)
            .unwrap_or_else(|_| fallback.to_string())
    }

    pub fn then_any(&mut self, case_id: &str, key: &str) -> Result<JsonValue, TestError> {
        let val = {
            let cm = self.case_map(case_id)?;
            let t = cm.get("then").and_then(|v| v.as_object()).ok_or_else(|| {
                TestError::assertion(format!("case '{}' has no then table", case_id))
            })?;
            t.get(key)
                .cloned()
                .ok_or_else(|| TestError::assertion(format!("case '{}' has no then.'{}'", case_id, key)))?
        };
        self.mark_read(case_id, key);
        Ok(val)
    }

    pub fn then_str(&mut self, case_id: &str, key: &str) -> Result<String, TestError> {
        self.then_any(case_id, key)?
            .as_str()
            .map(|s| s.to_string())
            .ok_or_else(|| TestError::assertion(format!("then.'{}' is not a string", key)))
    }

    pub fn then_int(&mut self, case_id: &str, key: &str) -> Result<i64, TestError> {
        self.then_any(case_id, key)?
            .as_f64()
            .map(|f| f as i64)
            .ok_or_else(|| TestError::assertion(format!("then.'{}' is not a number", key)))
    }

    pub fn then_bool(&mut self, case_id: &str, key: &str) -> Result<bool, TestError> {
        self.then_any(case_id, key)?
            .as_bool()
            .ok_or_else(|| TestError::assertion(format!("then.'{}' is not a bool", key)))
    }

    pub fn record_input(&mut self, rel_path: &str, digest: &str) {
        if !self.in_mutation {
            let norm = rel_path.replace('\\', "/").trim_start_matches('/').to_string();
            self.inputs.insert(norm, digest.to_string());
        }
    }

    pub fn read_fixture(&mut self, rel_path: &str) -> Result<String, TestError> {
        let raw = fs::read(rel_path).map_err(|e| {
            TestError::harness(format!("cannot read fixture '{}': {}", rel_path, e))
        })?;
        self.record_input(rel_path, &hash_fixture_bytes(&raw));
        String::from_utf8(raw)
            .map_err(|e| TestError::harness(format!("fixture '{}' is not UTF-8: {}", rel_path, e)))
    }

    pub fn verify_golden(&mut self, rel_path: &str, actual: &str) -> Result<(), TestError> {
        let expected_raw = fs::read(rel_path).map_err(|e| {
            TestError::harness(format!("cannot read golden '{}': {}", rel_path, e))
        })?;
        let exp_dig = hash_fixture_bytes(&expected_raw);
        self.record_input(rel_path, &exp_dig);
        let act_dig = hash_fixture_bytes(actual.as_bytes());
        if exp_dig != act_dig {
            return Err(TestError::assertion(format!(
                "golden mismatch for '{}': expected {}, got {}",
                rel_path, exp_dig, act_dig
            )));
        }
        Ok(())
    }

    pub fn check_projection(&mut self, case_id: &str, payload_json: &str) -> Result<(), TestError> {
        let then_map = {
            let cm = self.case_map(case_id)?;
            cm.get("then")
                .and_then(|v| v.as_object())
                .cloned()
                .ok_or_else(|| {
                    TestError::assertion(format!("case '{}' has no then table", case_id))
                })?
        };
        let doc = parse_json(payload_json)
            .map_err(|e| TestError::assertion(format!("payload is not valid JSON: {}", e)))?;
        let proj_then = extract_then_projections(&self.view);
        for (pred, expected) in &then_map {
            self.mark_read(case_id, pred);
            if is_relational_table(expected)
                && expected
                    .as_object()
                    .is_some_and(|m| m.contains_key("allowed_keys"))
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
        Ok(())
    }

    pub fn check_adverse<E>(
        &mut self,
        case_id: &str,
        variants_json: &[&str],
        exec: E,
    ) -> Result<(), TestError>
    where
        E: Fn(&str) -> Result<String, TestError>,
    {
        if variants_json.is_empty() {
            return Err(TestError::assertion(format!(
                "check_adverse for {}.{} requires at least one variant",
                self.contract_id, case_id
            )));
        }
        let when_map = {
            let cm = self.case_map(case_id)?;
            cm.get("when")
                .and_then(|v| v.as_object())
                .cloned()
                .unwrap_or_default()
        };
        let proj_when = extract_when_projections(&self.view);
        for v_json in variants_json {
            let v_doc = parse_json(v_json)
                .map_err(|e| TestError::assertion(format!("variant is not valid JSON: {}", e)))?;
            if v_doc.as_object().is_some() {
                for (wk, wexp) in &when_map {
                    let default_ptr = format!("/{}", escape_pointer(wk));
                    let ptr = proj_when.get(wk).unwrap_or(&default_ptr);
                    if let Some(v_act) = resolve_pointer(&v_doc, ptr) {
                        if !values_equal(v_act, wexp) {
                            return Err(TestError::assertion(format!(
                                "{}.{}.when.{} fixture mismatch: got {}, expected {}",
                                self.contract_id,
                                case_id,
                                wk,
                                v_act.to_json_string(),
                                wexp.to_json_string()
                            )));
                        }
                    }
                }
            }
            let obs_json = exec(v_json)?;
            self.check_projection(case_id, &obs_json)?;
        }
        Ok(())
    }

    pub fn build_output(&mut self, case_id: &str) -> Result<String, TestError> {
        if !self.cases.iter().any(|c| c == case_id) {
            return Err(TestError::assertion(format!(
                "case '{}' is not tagged on test '{}'",
                case_id, self.test_id
            )));
        }
        if !self.in_mutation {
            self.self_stubbed = true;
            let self_key = format!(".drift/self-stub/{}", self.contract_id);
            self.record_input(&self_key, "sha256:self-stub");
        }
        build_projected_json(&self.view, case_id)
    }

    pub fn build_stub(
        &mut self,
        target: &str,
        case_id: &str,
        resolved_dir: &str,
    ) -> Result<String, TestError> {
        if target == self.contract_id {
            if !self.in_mutation {
                self.self_stubbed = true;
                let self_key = format!(".drift/self-stub/{}", self.contract_id);
                self.record_input(&self_key, "sha256:self-stub");
            }
            return build_projected_json(&self.view, case_id);
        }
        let eff_rdir = if !resolved_dir.is_empty() {
            resolved_dir
        } else {
            &self.resolved_dir
        };
        let up_view = load_contract_view(target, eff_rdir)?;
        build_projected_json(&up_view, case_id)
    }

    fn fully_read_cases(&self) -> Vec<String> {
        let mut out = Vec::new();
        let Some(cases_map) = self.view.get("cases").and_then(|v| v.as_object()) else {
            return out;
        };
        for cid in &self.cases {
            let Some(t_map) = cases_map
                .get(cid)
                .and_then(|v| v.as_object())
                .and_then(|cm| cm.get("then"))
                .and_then(|v| v.as_object())
            else {
                continue;
            };
            if t_map.is_empty() {
                continue;
            }
            let Some(read_set) = self.read_keys.get(cid) else {
                continue;
            };
            if t_map.keys().all(|k| read_set.contains(k)) {
                out.push(cid.clone());
            }
        }
        out.sort();
        out
    }
}

fn apply_mutant_to_view(
    base_view: &BTreeMap<String, JsonValue>,
    cid: &str,
    path: &str,
    after: &JsonValue,
) -> Result<BTreeMap<String, JsonValue>, TestError> {
    let mut cloned = base_view.clone();
    let esc_cid = escape_pointer(cid);
    let when_pfx = format!("/cases/{}/when/", esc_cid);
    let then_pfx = format!("/cases/{}/then/", esc_cid);
    let (side, prefix) = if path.starts_with(&when_pfx) {
        ("when", when_pfx)
    } else if path.starts_with(&then_pfx) {
        ("then", then_pfx)
    } else {
        return Err(TestError::harness(format!(
            "unsupported mutant path '{}'",
            path
        )));
    };
    let segs: Vec<String> = path[prefix.len()..].split('/').map(unescape_pointer).collect();
    if segs.is_empty() || segs[0].is_empty() {
        return Err(TestError::harness(format!(
            "empty segment in mutant path '{}'",
            path
        )));
    }
    let cases_map = cloned
        .get_mut("cases")
        .and_then(|v| v.as_object_mut())
        .ok_or_else(|| TestError::harness("contract view missing cases"))?;
    let case_obj = cases_map
        .get_mut(cid)
        .and_then(|v| v.as_object_mut())
        .ok_or_else(|| TestError::harness(format!("contract view missing case '{}'", cid)))?;
    let side_map = case_obj
        .get_mut(side)
        .and_then(|v| v.as_object_mut())
        .ok_or_else(|| TestError::harness(format!("case '{}' missing '{}' table", cid, side)))?;

    let k0 = &segs[0];
    if segs.len() == 1 {
        side_map.insert(k0.clone(), after.clone());
    } else if segs.len() == 2 {
        let k1 = &segs[1];
        if let Some(am) = after.as_object() {
            if side_map.contains_key(k0)
                && side_map.contains_key(k1)
                && am.contains_key(k0)
                && am.contains_key(k1)
            {
                if let Some(v0) = am.get(k0) {
                    side_map.insert(k0.clone(), v0.clone());
                }
                if let Some(v1) = am.get(k1) {
                    side_map.insert(k1.clone(), v1.clone());
                }
                return Ok(cloned);
            }
        }
        if let Some(rel_m) = side_map.get_mut(k0).and_then(|v| v.as_object_mut()) {
            rel_m.insert(k1.clone(), after.clone());
            return Ok(cloned);
        }
        return Err(TestError::harness(format!(
            "cannot apply 2-segment mutant path '{}' on non-table key '{}'",
            path, k0
        )));
    } else {
        return Err(TestError::harness(format!(
            "unsupported mutant path depth '{}'",
            path
        )));
    }
    Ok(cloned)
}

fn derive_libtest_filters(cls: &str, mth: &str, explicit_filter: &str) -> Vec<String> {
    let trimmed = explicit_filter.trim();
    if !trimmed.is_empty() && trimmed != "*" {
        return vec![trimmed.to_string()];
    }
    let mut out = Vec::new();
    let segs: Vec<&str> = cls.split("::").filter(|s| !s.is_empty()).collect();
    for start in 1..segs.len() {
        let cand = format!("{}::{}", segs[start..].join("::"), mth);
        if !out.contains(&cand) {
            out.push(cand);
        }
    }
    if !segs.is_empty() {
        let full = format!("{}::{}", segs.join("::"), mth);
        if !out.contains(&full) {
            out.push(full);
        }
    }
    let bare = mth.to_string();
    if !out.contains(&bare) {
        out.push(bare);
    }
    out
}

fn effective_mutant_mode(opts: &RunOptions) -> MutantMode {
    if opts.mutant_mode != MutantMode::Auto {
        return opts.mutant_mode;
    }
    match env::var("DRIFT_MUTANT_MODE").unwrap_or_default().trim() {
        "subprocess" => MutantMode::Subprocess,
        _ => MutantMode::InProcess,
    }
}

fn execute_callback<F>(ctx: &mut DriftContext, cb: &F) -> Result<(), TestError>
where
    F: Fn(&mut DriftContext) -> Result<(), TestError>,
{
    match panic::catch_unwind(AssertUnwindSafe(|| cb(ctx))) {
        Ok(Ok(())) => Ok(()),
        Ok(Err(e)) => Err(e),
        Err(payload) => {
            let msg = if let Some(s) = payload.downcast_ref::<&str>() {
                (*s).to_string()
            } else if let Some(s) = payload.downcast_ref::<String>() {
                s.clone()
            } else {
                "test panicked".to_string()
            };
            Err(TestError::assertion(msg))
        }
    }
}

fn find_single_mutant_in_manifest(
    contract_id: &str,
    mid_target: &str,
) -> Result<Option<(String, String, JsonValue)>, TestError> {
    let mut_file = env::var("DRIFT_MUTANTS").unwrap_or_default().trim().to_string();
    if mut_file.is_empty() {
        return Ok(None);
    }
    let raw = fs::read_to_string(&mut_file).map_err(|e| {
        TestError::harness(format!("cannot read DRIFT_MUTANTS '{}': {}", mut_file, e))
    })?;
    let doc = parse_json(&raw)
        .map_err(|e| TestError::harness(format!("invalid DRIFT_MUTANTS JSON: {}", e)))?;
    let Some(contracts) = doc.as_object().and_then(|m| m.get("contracts")).and_then(|v| v.as_array()) else {
        return Ok(None);
    };
    for c_item in contracts {
        let Some(cm) = c_item.as_object() else { continue };
        if cm.get("id").and_then(|v| v.as_str()) != Some(contract_id) {
            continue;
        }
        let Some(muts) = cm.get("mutants").and_then(|v| v.as_array()) else {
            continue;
        };
        for item in muts {
            let Some(mm) = item.as_object() else { continue };
            if mm.get("id").and_then(|v| v.as_str()) == Some(mid_target) {
                let mcase = mm
                    .get("case")
                    .and_then(|v| v.as_str())
                    .unwrap_or_default()
                    .to_string();
                let mpath = mm
                    .get("path")
                    .and_then(|v| v.as_str())
                    .unwrap_or_default()
                    .to_string();
                let mafter = mm.get("after").cloned().unwrap_or(JsonValue::Null);
                return Ok(Some((mcase, mpath, mafter)));
            }
        }
    }
    Ok(None)
}

fn run_mutants<F>(
    opts: &RunOptions,
    base_view: &BTreeMap<String, JsonValue>,
    cls: &str,
    canon_test: &str,
    mth: &str,
    cb: &F,
) -> Result<(), TestError>
where
    F: Fn(&mut DriftContext) -> Result<(), TestError>,
{
    let mut_file = env::var("DRIFT_MUTANTS").unwrap_or_default().trim().to_string();
    if !opts.events_dir.is_empty() && opts.mutation_events_dir.is_empty() {
        return Ok(());
    }
    let mut_dir = if !opts.mutation_events_dir.trim().is_empty() {
        opts.mutation_events_dir.trim().to_string()
    } else {
        env::var("DRIFT_MUTATION_EVENTS")
            .unwrap_or_default()
            .trim()
            .to_string()
    };
    if mut_file.is_empty() || mut_dir.is_empty() {
        return Ok(());
    }
    if !Path::new(&mut_file).is_file() {
        return Err(TestError::harness(format!(
            "DRIFT_MUTANTS file '{}' does not exist",
            mut_file
        )));
    }
    let raw_bytes = fs::read(&mut_file).map_err(|e| {
        TestError::harness(format!("cannot read DRIFT_MUTANTS '{}': {}", mut_file, e))
    })?;
    let manifest_id = format!("sha256:{}", sha256_hex(&raw_bytes));
    let raw_str = String::from_utf8(raw_bytes)
        .map_err(|e| TestError::harness(format!("DRIFT_MUTANTS not UTF-8: {}", e)))?;
    let doc = parse_json(&raw_str)
        .map_err(|e| TestError::harness(format!("invalid DRIFT_MUTANTS JSON: {}", e)))?;
    let Some(contracts) = doc
        .as_object()
        .and_then(|m| m.get("contracts"))
        .and_then(|v| v.as_array())
    else {
        return Ok(());
    };
    fs::create_dir_all(&mut_dir)
        .map_err(|e| TestError::harness(format!("cannot create mutation events dir: {}", e)))?;
    let stem = process_shard_stem();
    let out_file = Path::new(&mut_dir).join(format!("{}-mutants.jsonl", stem));
    let mut f = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&out_file)
        .map_err(|e| TestError::harness(format!("cannot open mutant shard: {}", e)))?;

    let mode = effective_mutant_mode(opts);
    for c_item in contracts {
        let Some(cm) = c_item.as_object() else { continue };
        let mc = cm.get("id").and_then(|v| v.as_str()).unwrap_or_default();
        let cdig = cm.get("digest").and_then(|v| v.as_str()).unwrap_or_default();
        if mc != opts.contract {
            continue;
        }
        let Some(muts) = cm.get("mutants").and_then(|v| v.as_array()) else {
            continue;
        };
        for item in muts {
            let Some(mm) = item.as_object() else { continue };
            let mcase = mm.get("case").and_then(|v| v.as_str()).unwrap_or_default();
            let mid = mm.get("id").and_then(|v| v.as_str()).unwrap_or_default();
            let mpath = mm.get("path").and_then(|v| v.as_str()).unwrap_or_default();
            let Some(mafter) = mm.get("after") else {
                continue;
            };
            if !opts.cases.iter().any(|c| c == mcase) || mid.is_empty() {
                continue;
            }
            let killed = match mode {
                MutantMode::Subprocess => {
                    let exe = env::current_exe()
                        .map_err(|e| TestError::harness(format!("current_exe failed: {}", e)))?;
                    let filters = derive_libtest_filters(cls, mth, &opts.cargo_test_filter);
                    let mut matched_status = None;
                    for flt in &filters {
                        let st = Command::new(&exe)
                            .args(["--exact", flt, "--nocapture"])
                            .env("DRIFT_SINGLE_MUTANT", mid)
                            .output()
                            .map_err(|e| {
                                TestError::harness(format!("subprocess mutant spawn failed: {}", e))
                            })?;
                        let stdout_s = String::from_utf8_lossy(&st.stdout);
                        if !stdout_s.contains("running 0 tests") {
                            matched_status = Some(st);
                            break;
                        }
                    }
                    let Some(status) = matched_status else {
                        return Err(TestError::harness(format!(
                            "subprocess mutant filters {:?} matched 0 tests",
                            filters
                        )));
                    };
                    if status.status.code() == Some(99) {
                        return Err(TestError::harness(format!(
                            "subprocess mutant '{}' failed with harness error: {}",
                            mid,
                            String::from_utf8_lossy(&status.stderr)
                        )));
                    }
                    !status.status.success()
                }
                _ => {
                    let mutated_view = apply_mutant_to_view(base_view, mcase, mpath, mafter)?;
                    let mut mut_ctx = DriftContext {
                        contract_id: opts.contract.clone(),
                        test_id: opts.test.clone(),
                        canonical_test: canon_test.to_string(),
                        cases: opts.cases.clone(),
                        level: opts.level.clone(),
                        view: mutated_view,
                        read_keys: BTreeMap::new(),
                        inputs: BTreeMap::new(),
                        self_stubbed: false,
                        in_mutation: true,
                        resolved_dir: opts.resolved_dir.clone(),
                    };
                    match execute_callback(&mut mut_ctx, cb) {
                        Ok(()) => false,
                        Err(TestError::Assertion(_)) => true,
                        Err(TestError::Harness(msg)) => return Err(TestError::Harness(msg)),
                    }
                }
            };
            let outcome = if killed { "killed" } else { "survived" };
            let mut ev = BTreeMap::new();
            ev.insert("manifest".to_string(), JsonValue::Str(manifest_id.clone()));
            ev.insert(
                "contract".to_string(),
                JsonValue::Str(opts.contract.clone()),
            );
            ev.insert("digest".to_string(), JsonValue::Str(cdig.to_string()));
            ev.insert("mutant".to_string(), JsonValue::Str(mid.to_string()));
            ev.insert("case".to_string(), JsonValue::Str(mcase.to_string()));
            ev.insert("outcome".to_string(), JsonValue::Str(outcome.to_string()));
            ev.insert("control".to_string(), JsonValue::Str("passed".to_string()));
            let line = format!("{}\n", JsonValue::Object(ev).to_json_string());
            f.write_all(line.as_bytes()).map_err(|e| {
                TestError::harness(format!("failed writing mutant event: {}", e))
            })?;
        }
    }
    f.flush()
        .map_err(|e| TestError::harness(format!("failed flushing mutant events: {}", e)))?;
    Ok(())
}

pub fn run_drift_case<F>(opts: RunOptions, cb: F) -> Result<String, TestError>
where
    F: Fn(&mut DriftContext) -> Result<(), TestError>,
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
            let Some((mcase, mpath, mafter)) =
                find_single_mutant_in_manifest(&opts.contract, single_mid)?
            else {
                return Ok("skipped".to_string());
            };
            if !opts.cases.iter().any(|c| c == &mcase) {
                return Ok("skipped".to_string());
            }
            let mut_view = apply_mutant_to_view(&base_view, &mcase, &mpath, &mafter)?;
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
            };
            match execute_callback(&mut mut_ctx, &cb) {
                Ok(()) => return Ok("survived".to_string()),
                Err(TestError::Assertion(msg)) => return Err(TestError::Assertion(msg)),
                Err(TestError::Harness(msg)) => {
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
    };

    let res = execute_callback(&mut ctx, &cb);
    if let Err(TestError::Harness(msg)) = &res {
        return Err(TestError::Harness(msg.clone()));
    }
    let outcome = if res.is_ok() { "passed" } else { "failed" };

    if res.is_ok() {
        run_mutants(&opts, &base_view, &cls, &canon_test, &mth, &cb)?;
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
