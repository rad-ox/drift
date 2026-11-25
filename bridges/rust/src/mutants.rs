use super::*;
use std::sync::atomic::{AtomicU64, Ordering};

static SUBPROC_MUT_SEQ: AtomicU64 = AtomicU64::new(0);

pub(crate) fn apply_mutant_to_view(
    base_view: &BTreeMap<String, JsonValue>,
    cid: &str,
    path: &str,
    after: &JsonValue,
) -> Result<BTreeMap<String, JsonValue>, TestError> {
    let mut cloned = base_view.clone();
    let esc_cid = escape_pointer(cid);
    let (wp, tp) = (format!("/cases/{esc_cid}/when/"), format!("/cases/{esc_cid}/then/"));
    let (side, prefix) = if path.starts_with(&wp) { ("when", wp) } else if path.starts_with(&tp) { ("then", tp) }
        else { return Err(herr(format!("unsupported mutant path '{path}'"))); };
    let segs: Vec<String> = path[prefix.len()..].split('/').map(unescape_pointer).collect();
    if segs.is_empty() || segs[0].is_empty() { return Err(herr(format!("empty segment in mutant path '{path}'"))); }
    let side_map = cloned.get_mut("cases").and_then(JsonValue::as_object_mut).ok_or_else(|| herr("contract view missing cases"))?
        .get_mut(cid).and_then(JsonValue::as_object_mut).ok_or_else(|| herr(format!("contract view missing case '{cid}'")))?
        .get_mut(side).and_then(JsonValue::as_object_mut).ok_or_else(|| herr(format!("case '{cid}' missing '{side}' table")))?;

    if segs.len() == 2 {
        let (k0, k1) = (&segs[0], &segs[1]);
        if let Some(am) = after.as_object() {
            if side_map.contains_key(k0) && side_map.contains_key(k1) && am.contains_key(k0) && am.contains_key(k1) {
                for k in [k0, k1] { if let Some(v) = am.get(k) { side_map.insert(k.clone(), v.clone()); } }
                return Ok(cloned);
            }
        }
    }
    let mut cur = side_map;
    for seg in &segs[..segs.len() - 1] {
        cur = cur.get_mut(seg).and_then(JsonValue::as_object_mut)
            .ok_or_else(|| herr(format!("cannot apply mutant path '{path}' on non-table key '{seg}'")))?;
    }
    if let Some(last) = segs.last() { cur.insert(last.clone(), after.clone()); }
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
        Err(payload) => {
            let msg = format!(
                "test panicked: {}",
                panic_payload_message(payload.as_ref())
            );
            if ctx.in_mutation {
                Err(TestError::Harness(msg))
            } else {
                Err(TestError::Assertion(msg))
            }
        }
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

fn read_manifest_doc(mut_file: &str) -> Result<(String, JsonValue), TestError> {
    let raw = fs::read(mut_file).map_err(ctx_err("cannot read DRIFT_MUTANTS"))?;
    let id = format!("sha256:{}", sha256_hex(&raw));
    let txt = String::from_utf8(raw).map_err(ctx_err("DRIFT_MUTANTS not UTF-8"))?;
    let doc = parse_json(&txt).map_err(ctx_err("invalid DRIFT_MUTANTS JSON"))?;
    Ok((id, doc))
}

pub(crate) fn find_single_mutant_in_manifest(contract_id: &str, mid_target: &str) -> Result<Option<(String, String, JsonValue)>, TestError> {
    let mut_file = env_trim("DRIFT_MUTANTS");
    if mut_file.is_empty() { return Ok(None); }
    let (_, doc) = read_manifest_doc(&mut_file)?;
    let Some(contracts) = doc.as_object().and_then(|m| m.get("contracts")).and_then(JsonValue::as_array) else { return Ok(None); };
    for cm in contracts.iter().filter_map(JsonValue::as_object) {
        if cm.get("id").and_then(JsonValue::as_str) != Some(contract_id) { continue; }
        for mm in cm.get("mutants").and_then(JsonValue::as_array).into_iter().flatten().filter_map(JsonValue::as_object) {
            if mm.get("id").and_then(JsonValue::as_str) == Some(mid_target) {
                let s = |k| mm.get(k).and_then(JsonValue::as_str).unwrap_or_default().to_string();
                return Ok(Some((s("case"), s("path"), mm.get("after").cloned().unwrap_or(JsonValue::Null))));
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
    let mut_file = env_trim("DRIFT_MUTANTS");
    if !opts.events_dir.is_empty() && opts.mutation_events_dir.is_empty() { return Ok(()); }
    let mut_dir = if !opts.mutation_events_dir.trim().is_empty() { opts.mutation_events_dir.trim().into() } else { env_trim("DRIFT_MUTATION_EVENTS") };
    if mut_file.is_empty() || mut_dir.is_empty() { return Ok(()); }
    if !Path::new(&mut_file).is_file() { return Err(herr(format!("DRIFT_MUTANTS file '{mut_file}' does not exist"))); }
    let (manifest_id, doc) = read_manifest_doc(&mut_file)?;
    let Some(contracts) = doc.as_object().and_then(|m| m.get("contracts")).and_then(JsonValue::as_array) else { return Ok(()); };
    fs::create_dir_all(&mut_dir).map_err(ctx_err("cannot create mutation events dir"))?;
    let stem = process_shard_stem();
    let out_file = Path::new(&mut_dir).join(format!("{stem}-mutants.jsonl"));
    let mut f = OpenOptions::new().create(true).append(true).open(&out_file).map_err(ctx_err("cannot open mutant shard"))?;

    let mode = effective_mutant_mode(opts);
    for cm in contracts.iter().filter_map(JsonValue::as_object) {
        if cm.get("id").and_then(JsonValue::as_str) != Some(opts.contract.as_str()) { continue; }
        let cdig = cm.get("digest").and_then(JsonValue::as_str).unwrap_or_default();
        for mm in cm.get("mutants").and_then(JsonValue::as_array).into_iter().flatten().filter_map(JsonValue::as_object) {
            let mcase = mm.get("case").and_then(JsonValue::as_str).unwrap_or_default();
            let mid = mm.get("id").and_then(JsonValue::as_str).unwrap_or_default();
            let mpath = mm.get("path").and_then(JsonValue::as_str).unwrap_or_default();
            let Some(mafter) = mm.get("after") else { continue; };
            if !opts.cases.iter().any(|c| c == mcase) || mid.is_empty() { continue; }
            let killed = match mode {
                MutantMode::Subprocess => {
                    let seq = SUBPROC_MUT_SEQ.fetch_add(1, Ordering::Relaxed);
                    let outcome_file = Path::new(&mut_dir).join(format!(".{stem}-{seq}-single-mutant.json"));
                    let exe = env::current_exe().map_err(ctx_err("current_exe failed"))?;
                    let filters = derive_libtest_filters(cls, mth, &opts.cargo_test_filter);
                    let mut matched_status = None;
                    for flt in &filters {
                        let _ = fs::remove_file(&outcome_file);
                        let st = Command::new(&exe).args(["--exact", flt, "--nocapture"])
                            .env("DRIFT_SINGLE_MUTANT", mid).env("DRIFT_SINGLE_MUTANT_OUT", &outcome_file)
                            .output().map_err(ctx_err("subprocess mutant spawn failed"))?;
                        if !String::from_utf8_lossy(&st.stdout).contains("running 0 tests") { matched_status = Some(st); break; }
                    }
                    let Some(status) = matched_status else {
                        let _ = fs::remove_file(&outcome_file);
                        return Err(herr(format!("subprocess mutant filters {filters:?} matched 0 tests")));
                    };
                    let outcome_raw = fs::read_to_string(&outcome_file).map_err(|_| {
                        herr(format!("subprocess mutant '{mid}' terminated abnormally without structured outcome (status: {}, stderr: {})", status.status, String::from_utf8_lossy(&status.stderr).trim()))
                    })?;
                    let _ = fs::remove_file(&outcome_file);
                    let outcome_doc = parse_json(&outcome_raw).map_err(ctx_err("invalid subprocess mutant outcome"))?;
                    let out_obj = outcome_doc.as_object().ok_or_else(|| herr(format!("subprocess mutant '{mid}' outcome not object")))?;
                    if out_obj.get("mutant").and_then(JsonValue::as_str) != Some(mid) {
                        return Err(herr(format!("subprocess mutant '{mid}' outcome mutant mismatch")));
                    }
                    match out_obj.get("status").and_then(JsonValue::as_str).unwrap_or_default() {
                        "survived" => {
                            if !status.status.success() { return Err(herr(format!("subprocess mutant '{mid}' survived with status {}", status.status))); }
                            false
                        }
                        "killed" => {
                            if status.status.code().is_none() { return Err(herr(format!("subprocess mutant '{mid}' terminated by signal ({})", status.status))); }
                            true
                        }
                        "harness_error" => {
                            let msg = out_obj.get("message").and_then(JsonValue::as_str).unwrap_or("harness error");
                            return Err(herr(format!("subprocess mutant '{mid}' harness error: {msg}")));
                        }
                        other => return Err(herr(format!("subprocess mutant '{mid}' unknown status '{other}'"))),
                    }
                }
                _ => {
                    let mutated_view = apply_mutant_to_view(base_view, mcase, mpath, mafter)?;
                    let mut mut_ctx = DriftContext::new(opts, canon_test.into(), mutated_view, true);
                    match execute_callback_with_fixture(&mut mut_ctx, setup, cb) {
                        Ok(()) => false,
                        Err(TestError::Assertion(_)) => true,
                        Err(TestError::Harness(msg)) => return Err(TestError::Harness(msg)),
                    }
                }
            };
            let ev: BTreeMap<String, JsonValue> = [
                ("manifest", manifest_id.as_str()), ("contract", opts.contract.as_str()), ("digest", cdig),
                ("mutant", mid), ("case", mcase), ("outcome", if killed { "killed" } else { "survived" }), ("control", "passed"),
            ].into_iter().map(|(k, v)| (k.into(), JsonValue::Str(v.into()))).collect();
            f.write_all(format!("{}\n", JsonValue::Object(ev).to_json_string()).as_bytes()).map_err(ctx_err("failed writing mutant event"))?;
        }
    }
    f.flush().map_err(ctx_err("failed flushing mutant events"))
}
