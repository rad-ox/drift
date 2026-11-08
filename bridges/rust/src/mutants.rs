use super::*;

pub(crate) fn apply_mutant_to_view(
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

fn panic_payload_message(payload: &(dyn Any + Send)) -> String {
    if let Some(s) = payload.downcast_ref::<&str>() {
        (*s).to_string()
    } else if let Some(s) = payload.downcast_ref::<String>() {
        s.clone()
    } else {
        "test panicked".to_string()
    }
}

pub(crate) fn execute_callback_with_fixture<T, S, F>(
    ctx: &mut DriftContext,
    setup: &S,
    cb: &F,
) -> Result<(), TestError>
where
    S: Fn() -> Result<T, TestError>,
    F: Fn(&mut DriftContext, T) -> Result<(), TestError>,
{
    let fixture = match panic::catch_unwind(AssertUnwindSafe(setup)) {
        Ok(Ok(val)) => val,
        Ok(Err(e)) => {
            return Err(TestError::harness(format!(
                "fixture setup failed: {}",
                e.message()
            )))
        }
        Err(payload) => {
            return Err(TestError::harness(format!(
                "fixture setup panicked: {}",
                panic_payload_message(payload.as_ref())
            )))
        }
    };
    match panic::catch_unwind(AssertUnwindSafe(|| cb(ctx, fixture))) {
        Ok(Ok(())) => Ok(()),
        Ok(Err(TestError::Assertion(msg))) => {
            if ctx.in_mutation && !ctx.accessed_view.get() {
                Err(TestError::harness(format!(
                    "mutant failed before reading contract view: {}",
                    msg
                )))
            } else {
                Err(TestError::Assertion(msg))
            }
        }
        Ok(Err(TestError::Harness(msg))) => Err(TestError::Harness(msg)),
        Err(payload) => Err(TestError::harness(format!(
            "test panicked: {}",
            panic_payload_message(payload.as_ref())
        ))),
    }
}

pub(crate) fn write_single_mutant_outcome(mid: &str, status: &str, message: &str) {
    if let Ok(out_path) = env::var("DRIFT_SINGLE_MUTANT_OUT") {
        let trimmed = out_path.trim();
        if !trimmed.is_empty() {
            let mut obj = BTreeMap::new();
            obj.insert("mutant".to_string(), JsonValue::Str(mid.to_string()));
            obj.insert("status".to_string(), JsonValue::Str(status.to_string()));
            if !message.is_empty() {
                obj.insert("message".to_string(), JsonValue::Str(message.to_string()));
            }
            let _ = fs::write(
                trimmed,
                format!("{}\n", JsonValue::Object(obj).to_json_string()),
            );
        }
    }
}

pub(crate) fn find_single_mutant_in_manifest(
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

pub(crate) fn run_mutants<T, S, F>(
    opts: &RunOptions,
    base_view: &BTreeMap<String, JsonValue>,
    cls: &str,
    canon_test: &str,
    mth: &str,
    setup: &S,
    cb: &F,
) -> Result<(), TestError>
where
    S: Fn() -> Result<T, TestError>,
    F: Fn(&mut DriftContext, T) -> Result<(), TestError>,
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
    let outcome_file = Path::new(&mut_dir).join(format!(".{}-single-mutant.json", stem));
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
                        let _ = fs::remove_file(&outcome_file);
                        let st = Command::new(&exe)
                            .args(["--exact", flt, "--nocapture"])
                            .env("DRIFT_SINGLE_MUTANT", mid)
                            .env("DRIFT_SINGLE_MUTANT_OUT", &outcome_file)
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
                        let _ = fs::remove_file(&outcome_file);
                        return Err(TestError::harness(format!(
                            "subprocess mutant filters {:?} matched 0 tests",
                            filters
                        )));
                    };
                    let outcome_raw = fs::read_to_string(&outcome_file).map_err(|_| {
                        TestError::harness(format!(
                            "subprocess mutant '{}' terminated abnormally without structured bridge outcome (status: {}, stderr: {})",
                            mid,
                            status.status,
                            String::from_utf8_lossy(&status.stderr).trim()
                        ))
                    })?;
                    let _ = fs::remove_file(&outcome_file);
                    let outcome_doc = parse_json(&outcome_raw).map_err(|e| {
                        TestError::harness(format!(
                            "subprocess mutant '{}' wrote invalid structured outcome: {}",
                            mid, e
                        ))
                    })?;
                    let Some(out_obj) = outcome_doc.as_object() else {
                        return Err(TestError::harness(format!(
                            "subprocess mutant '{}' structured outcome is not an object",
                            mid
                        )));
                    };
                    if out_obj.get("mutant").and_then(|v| v.as_str()) != Some(mid) {
                        return Err(TestError::harness(format!(
                            "subprocess mutant '{}' structured outcome mutant mismatch",
                            mid
                        )));
                    };
                    match out_obj.get("status").and_then(|v| v.as_str()).unwrap_or_default() {
                        "survived" => {
                            if !status.status.success() {
                                return Err(TestError::harness(format!(
                                    "subprocess mutant '{}' survived in bridge but process exited abnormally (status: {})",
                                    mid, status.status
                                )));
                            }
                            false
                        }
                        "killed" => {
                            if status.status.code().is_none() {
                                return Err(TestError::harness(format!(
                                    "subprocess mutant '{}' terminated by signal ({})",
                                    mid, status.status
                                )));
                            }
                            true
                        }
                        "harness_error" => {
                            let msg = out_obj
                                .get("message")
                                .and_then(|v| v.as_str())
                                .unwrap_or("harness error");
                            return Err(TestError::harness(format!(
                                "subprocess mutant '{}' failed with harness error: {}",
                                mid, msg
                            )));
                        }
                        other => {
                            return Err(TestError::harness(format!(
                                "subprocess mutant '{}' reported unknown status '{}'",
                                mid, other
                            )));
                        }
                    }
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
                        accessed_view: Cell::new(false),
                    };
                    match execute_callback_with_fixture(&mut mut_ctx, setup, cb) {
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
