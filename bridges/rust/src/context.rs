use super::*;

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

pub(crate) fn process_shard_stem() -> String {
    if let Ok(raw) = env::var("DRIFT_SHARD_NAME") {
        let s: String = raw.trim().chars().map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' }).collect();
        if !s.is_empty() { return s; }
    }
    let bn = env::current_exe().ok().and_then(|p| p.file_stem().map(|s| s.to_string_lossy().into_owned())).unwrap_or_else(|| "rust".to_string());
    let clean: String = bn.chars().map(|c| if c.is_ascii_alphanumeric() || c == '-' || c == '_' { c } else { '_' }).collect();
    format!("rust-{}-{}", clean, process::id())
}

pub(crate) fn env_trim(k: &str) -> String {
    env::var(k).unwrap_or_default().trim().to_string()
}

pub(crate) fn validated_snapshot() -> Result<String, TestError> {
    let snap = env_trim("DRIFT_SNAPSHOT");
    if !snap.is_empty()
        && !((snap.len() == 40 || snap.len() == 64)
            && snap
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)))
    {
        return Err(TestError::harness(
            "invalid DRIFT_SNAPSHOT: expected 40 or 64 lowercase hex chars",
        ));
    }
    Ok(snap)
}

fn resolve_shard_target(ev_t: &str) -> Result<(std::path::PathBuf, String, bool), TestError> {
    let single = ev_t.ends_with(".jsonl");
    let (dir, stem) = if single {
        let jp = Path::new(ev_t);
        let st = jp.file_stem().and_then(|s| s.to_str()).filter(|s| !s.is_empty()).ok_or_else(|| herr("invalid DRIFT_EVENTS .jsonl path"))?;
        (jp.parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or_else(|| Path::new(".")), st.into())
    } else {
        (Path::new(ev_t), process_shard_stem())
    };
    fs::create_dir_all(dir).map_err(ctx_err("cannot create events dir"))?;
    Ok((dir.to_path_buf(), stem, single))
}

fn str_arr(it: impl IntoIterator<Item = String>) -> JsonValue {
    JsonValue::Array(it.into_iter().map(JsonValue::Str).collect())
}

fn build_meta_json(ev_dir: &Path, stem: &str, st: &ProcessShardState, single: bool, snap: &str) -> Result<String, TestError> {
    let (mut classes, mut tests, mut inputs, mut self_stubbed) = (st.classes.clone(), st.tests.clone(), st.inputs.clone(), st.self_stubbed.clone());
    if single {
        let fp = ev_dir.join(format!("{stem}.meta.json"));
        if fp.is_file() {
            let doc = parse_json(&fs::read_to_string(&fp).map_err(ctx_err("cannot read meta file"))?)
                .map_err(ctx_err("invalid meta JSON"))?;
            let prev = doc.as_object().ok_or_else(|| herr("meta JSON is not an object"))?;
            let ps = prev.get("snapshot").and_then(JsonValue::as_str).unwrap_or("");
            if ps != snap { return Err(herr(format!("snapshot mismatch for '{}': '{ps}' vs '{snap}'", fp.display()))); }
            let arr_s = |k| prev.get(k).and_then(JsonValue::as_array).into_iter().flatten().filter_map(JsonValue::as_str);
            for c in arr_s("classes") { if !st.classes.contains(c) { classes.insert(c.into()); } }
            for t in arr_s("tests") { if !st.classes.contains(t.split('#').next().unwrap_or("")) { tests.insert(t.into()); } }
            for t in arr_s("self_stubbed") { if tests.contains(t) { self_stubbed.insert(t.into()); } }
            if let Some(obj) = prev.get("inputs").and_then(JsonValue::as_object) {
                for (t, v) in obj {
                    if tests.contains(t) && !inputs.contains_key(t) {
                        if let Some(im) = v.as_object() {
                            let m: BTreeMap<String, String> = im.iter().filter_map(|(k, vv)| vv.as_str().map(|s| (k.clone(), s.into()))).collect();
                            if !m.is_empty() { inputs.insert(t.clone(), m); }
                        }
                    }
                }
            }
        }
    }
    let mut m = BTreeMap::new();
    m.insert("version".into(), JsonValue::Number(1.0));
    m.insert("classes".into(), str_arr(classes));
    m.insert("tests".into(), str_arr(tests));
    if !snap.is_empty() { m.insert("snapshot".into(), JsonValue::Str(snap.into())); }
    if !inputs.is_empty() {
        let ai = inputs.into_iter().map(|(t, im)| (t, JsonValue::Object(im.into_iter().map(|(k, v)| (k, JsonValue::Str(v))).collect()))).collect();
        m.insert("inputs".into(), JsonValue::Object(ai));
    }
    if !self_stubbed.is_empty() { m.insert("self_stubbed".into(), str_arr(self_stubbed)); }
    let env_map = resolve_env_map()?;
    if !env_map.is_empty() {
        m.insert("env".into(), JsonValue::Object(env_map.into_iter().map(|(k, v)| (k, JsonValue::Str(v))).collect()));
    }
    Ok(format!("{}\n", JsonValue::Object(m).to_json_string()))
}

fn write_meta_atomic(ev_dir: &Path, stem: &str, seq: u64, meta_json: &str) -> Result<(), TestError> {
    let tmp = ev_dir.join(format!("{stem}.meta.json.tmp.{}.{seq}", process::id()));
    let fin = ev_dir.join(format!("{stem}.meta.json"));
    fs::write(&tmp, meta_json.as_bytes()).map_err(ctx_err("failed to write meta tmp"))?;
    fs::rename(&tmp, &fin).map_err(ctx_err("failed to rename meta file"))
}

pub(crate) fn record_discovered_inventory(events_dir: &str, classes: &[String], tests: &[String]) -> Result<(), TestError> {
    let snap = validated_snapshot()?;
    let (ev_path, stem, single) = resolve_shard_target(events_dir)?;
    let mut all = shard_states().lock().map_err(|_| herr("shard state mutex poisoned"))?;
    let st = all.entry(events_dir.into()).or_default();
    st.seq += 1;
    st.classes.extend(classes.iter().cloned());
    st.tests.extend(tests.iter().cloned());
    let meta_json = build_meta_json(&ev_path, &stem, st, single, &snap)?;
    let jp = ev_path.join(format!("{stem}.jsonl"));
    if !jp.exists() { fs::write(&jp, b"").map_err(ctx_err("cannot create shard jsonl"))?; }
    write_meta_atomic(&ev_path, &stem, st.seq, &meta_json)
}

pub(crate) fn update_shard_and_meta(
    events_dir: &str,
    event_line: &str,
    cls: &str,
    canon_test: &str,
    inputs: &BTreeMap<String, String>,
    self_stubbed: bool,
) -> Result<(), TestError> {
    let snap = validated_snapshot()?;
    let (ev_path, stem, single) = resolve_shard_target(events_dir)?;
    let mut all = shard_states().lock().map_err(|_| herr("shard state mutex poisoned"))?;
    let st = all.entry(events_dir.into()).or_default();
    st.seq += 1;
    st.classes.insert(cls.into());
    st.tests.insert(canon_test.into());
    if !inputs.is_empty() { st.inputs.entry(canon_test.into()).or_default().extend(inputs.iter().map(|(k, v)| (k.clone(), v.clone()))); }
    if self_stubbed { st.self_stubbed.insert(canon_test.into()); }
    let meta_json = build_meta_json(&ev_path, &stem, st, single, &snap)?;
    let jp = ev_path.join(format!("{stem}.jsonl"));
    let mut f = OpenOptions::new().create(true).append(true).open(&jp).map_err(ctx_err("cannot open shard jsonl"))?;
    f.write_all(format!("{event_line}\n").as_bytes()).map_err(ctx_err("cannot append event line"))?;
    f.flush().map_err(ctx_err("cannot flush event line"))?;
    write_meta_atomic(&ev_path, &stem, st.seq, &meta_json)
}

fn extract_projections(view: &BTreeMap<String, JsonValue>, side: &str) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    if let Some(proj) = view.get("projections").and_then(|v| v.as_object()) {
        for (k, v) in proj {
            if k != "when" && k != "then" { if let Some(s) = v.as_str() { out.insert(k.clone(), s.into()); } }
        }
        if let Some(sm) = proj.get(side).and_then(|v| v.as_object()) {
            for (k, v) in sm { if let Some(s) = v.as_str() { out.insert(k.clone(), s.into()); } }
        }
    }
    out
}
pub(crate) fn extract_then_projections(v: &BTreeMap<String, JsonValue>) -> BTreeMap<String, String> { extract_projections(v, "then") }
pub(crate) fn extract_when_projections(v: &BTreeMap<String, JsonValue>) -> BTreeMap<String, String> { extract_projections(v, "when") }

pub(crate) fn build_projected_json(view: &BTreeMap<String, JsonValue>, case_id: &str) -> Result<String, TestError> {
    let cm = view.get("cases").and_then(|v| v.as_object()).ok_or_else(|| TestError::assertion("contract has no cases"))?
        .get(case_id).and_then(|v| v.as_object()).ok_or_else(|| TestError::assertion(format!("unknown case '{}'", case_id)))?;
    if let Some(st) = cm.get("status").and_then(|v| v.as_str()).filter(|s| !s.is_empty()) {
        return Err(TestError::assertion(format!("cannot synthesize stub for {} case '{}'", st, case_id)));
    }
    let then_map = cm.get("then").and_then(|v| v.as_object()).ok_or_else(|| TestError::assertion(format!("case '{}' has no then table", case_id)))?;
    let proj_then = extract_then_projections(view);
    let is_sum_rel = |e: &JsonValue| e.as_object().is_some_and(|m| m.contains_key("sum_fields") || m.get("peer").and_then(|p| p.as_object()).is_some_and(|p| p.contains_key("sum")));
    let mut built = BTreeMap::new();
    for sum_pass in [false, true] {
        for (pred, expected) in then_map {
            if is_sum_rel(expected) != sum_pass { continue; }
            let dp = format!("/{}", escape_pointer(pred));
            let ptr = normalize_pointer(proj_then.get(pred).unwrap_or(&dp));
            let v = synthesize_leaf_witness(expected, &built, &proj_then);
            write_pointer(&mut built, &ptr, v);
        }
    }
    Ok(JsonValue::Object(built).to_json_string())
}

pub(crate) fn allowed_write_sets_of<'a>(
    view: &'a BTreeMap<String, JsonValue>,
    case_id: &str,
) -> (BTreeSet<&'a str>, BTreeSet<&'a str>, bool) {
    let scope_writes = view
        .get("scope")
        .and_then(|v| v.as_object())
        .and_then(|s| s.get("writes"))
        .and_then(|v| v.as_array());
    let case_writes = view
        .get("cases")
        .and_then(|v| v.as_object())
        .and_then(|cs| cs.get(case_id))
        .and_then(|v| v.as_object())
        .and_then(|cm| cm.get("writes"))
        .and_then(|v| v.as_array());
    let has_case_writes = case_writes.is_some();
    let raw_list = case_writes.or(scope_writes);
    let mut allowed = BTreeSet::new();
    let mut allowed_bases = BTreeSet::new();
    if let Some(arr) = raw_list {
        for item in arr {
            if let Some(w) = item.as_str() {
                allowed.insert(w);
                allowed_bases.insert(w.split('#').next().unwrap_or(w));
            }
        }
    }
    (allowed, allowed_bases, has_case_writes)
}

pub(crate) fn is_write_resource_allowed(
    res: &str,
    allowed: &BTreeSet<&str>,
    allowed_bases: &BTreeSet<&str>,
) -> bool {
    let base = res.split('#').next().unwrap_or(res);
    allowed.contains(res)
        || allowed.contains(base)
        || (!res.contains('#') && allowed_bases.contains(res))
}

pub(crate) fn forbidden_writes_of(view: &BTreeMap<String, JsonValue>, case_id: &str) -> Vec<String> {
    let Some(scope_writes) = view
        .get("scope")
        .and_then(|v| v.as_object())
        .and_then(|s| s.get("writes"))
        .and_then(|v| v.as_array())
    else {
        return Vec::new();
    };
    let (allowed, allowed_bases, has_case_writes) = allowed_write_sets_of(view, case_id);
    if !has_case_writes {
        return Vec::new();
    }
    let mut out = Vec::new();
    for item in scope_writes {
        if let Some(r) = item.as_str() {
            if !is_write_resource_allowed(r, &allowed, &allowed_bases) {
                out.push(r.to_string());
            }
        }
    }
    out
}

pub(crate) fn verify_single_frame_obs(cid: &str, case_id: &str, res: &str, obs: &JsonValue, ambient: bool) -> Result<(), TestError> {
    let mut checked = false;
    let pfx = format!("{}.{}", cid, case_id);
    let wl = if ambient { format!("undeclared write on perimeter resource '{}'", res) } else { format!("frame violation on resource '{}'", res) };
    let sl = if ambient { format!("undeclared state mutation on perimeter resource '{}'", res) } else { format!("frame state mutation on resource '{}'", res) };
    let chk_n = |n: f64, wk: &str| -> Result<(), TestError> {
        if !n.is_finite() || n < 0.0 || n.fract() != 0.0 {
            return Err(TestError::assertion(format!("{}: invalid frame {} for '{}': expected non-negative integer, got {}", pfx, wk, res, n)));
        }
        if n > 0.0 { return Err(TestError::assertion(format!("{}: {}: expected 0 writes, observed {}", pfx, wl, n))); }
        Ok(())
    };
    if let Some(n) = obs.as_f64() {
        if n.is_finite() && n >= 0.0 && n.fract() == 0.0 { checked = true; chk_n(n, "writes")?; }
    } else if let Some(om) = obs.as_object() {
        for wk in ["writes", "operations", "events"] {
            if let Some(wv) = om.get(wk) {
                if let Some(wn) = wv.as_f64() { checked = true; chk_n(wn, wk)?; }
                else if let Some(arr) = wv.as_array() {
                    checked = true;
                    if !arr.is_empty() { return Err(TestError::assertion(format!("{}: {}: expected 0 writes, observed {}", pfx, wl, arr.len()))); }
                } else {
                    return Err(TestError::assertion(format!("{}: invalid frame {} for '{}': expected non-negative integer", pfx, wk, res)));
                }
            }
        }
        if let (Some(bef), Some(aft)) = (om.get("before"), om.get("after")) {
            checked = true;
            if !values_equal(bef, aft) { return Err(TestError::assertion(format!("{}: {}: before and after snapshots differ", pfx, sl))); }
        }
    }
    if !checked {
        return Err(TestError::assertion(format!("{}: frame observation for '{}' must supply writes/operations/events or before/after snapshots", pfx, res)));
    }
    Ok(())
}

pub(crate) fn required_ui_capability_for(pred: &str, ptr: &str) -> Option<&'static str> {
    let leaf = ptr.rsplit('/').next().unwrap_or("");
    for k in [pred, leaf] {
        match k {
            "min_contrast_ratio"
            | "min_contrast_wcag22"
            | "min_contrast_text_normal"
            | "min_contrast_text_large"
            | "min_contrast_ui_component"
            | "contrast_violations_count" => return Some("wcag22_contrast"),
            "assistive_announcement" | "active_assistive_focus" => return Some("assistive_focus"),
            "observed_transition_ms" | "max_transition_ms" | "observed_duration_ms" => {
                return Some("observed_transition")
            }
            "scroll_context_preserved" => return Some("scroll_state"),
            "horizontal_overflow_px"
            | "min_target_px"
            | "clipped_elements"
            | "unintentional_clipped_count"
            | "obscured_focus_elements"
            | "fully_obscured_focus_count"
            | "partially_obscured_focus_count"
            | "notice_precedes_detail" => return Some("geometry"),
            "after_focus_role"
            | "active_focus"
            | "trigger_restored"
            | "unexpected_focus_steals"
            | "input_focus_role" => return Some("input_focus"),
            _ => {}
        }
    }
    None
}

impl DriftContext {
    pub(crate) fn case_map(&self, case_id: &str) -> Result<&BTreeMap<String, JsonValue>, TestError> {
        self.accessed_view.set(true);
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

    pub(crate) fn mark_read(&mut self, case_id: &str, key: &str) {
        self.read_keys
            .entry(case_id.to_string())
            .or_default()
            .insert(key.to_string());
    }

    pub fn when_any(&self, case_id: &str, key: &str) -> Result<&JsonValue, TestError> {
        let cm = self.case_map(case_id)?;
        let val = cm.get("when").and_then(|v| v.as_object())
            .ok_or_else(|| TestError::assertion(format!("case '{}' has no when table", case_id)))?
            .get(key).ok_or_else(|| TestError::assertion(format!("case '{}' has no when.'{}'", case_id, key)))?;
        self.when_reads.borrow_mut().entry(case_id.into()).or_default().insert(key.into());
        if self.view.get("drift").and_then(|v| v.as_str()) == Some("0.3") {
            if let Some(eq_v) = val.as_object().filter(|m| m.len() == 1).and_then(|m| m.get("eq")) {
                return Ok(eq_v);
            }
        }
        Ok(val)
    }

    pub fn unread_when(&self, case_id: &str) -> Result<Vec<String>, TestError> {
        let cm = self.case_map(case_id)?;
        let Some(wm) = cm.get("when").and_then(|v| v.as_object()) else { return Ok(Vec::new()); };
        let rd = self.when_reads.borrow();
        let seen = rd.get(case_id);
        Ok(wm.keys().filter(|k| seen.map_or(true, |s| !s.contains(k.as_str()))).cloned().collect())
    }

    pub fn when_str(&self, c: &str, k: &str) -> Result<String, TestError> {
        self.when_any(c, k)?.as_str().map(str::to_string).ok_or_else(|| TestError::assertion(format!("when.'{}' is not a string", k)))
    }
    pub fn when_int(&self, c: &str, k: &str) -> Result<i64, TestError> {
        strict_i64(self.when_any(c, k)?, "when", k)
    }
    pub fn find_when_str(&self, c: &str, k: &str, fb: &str) -> String {
        self.when_str(c, k).unwrap_or_else(|_| fb.into())
    }

    pub fn then_any(&mut self, case_id: &str, key: &str) -> Result<JsonValue, TestError> {
        let is_03 = self.view.get("drift").and_then(|v| v.as_str()) == Some("0.3");
        let val = {
            let cm = self.case_map(case_id)?;
            let raw = cm.get("then").and_then(|v| v.as_object()).ok_or_else(|| TestError::assertion(format!("case '{}' has no then table", case_id)))?
                .get(key).ok_or_else(|| TestError::assertion(format!("case '{}' has no then.'{}'", case_id, key)))?;
            if is_03 {
                raw.as_object().filter(|m| m.len() == 1).and_then(|m| m.get("eq")).unwrap_or(raw).clone()
            } else {
                raw.clone()
            }
        };
        self.mark_read(case_id, key);
        Ok(val)
    }

    pub fn then_str(&mut self, c: &str, k: &str) -> Result<String, TestError> {
        self.then_any(c, k)?.as_str().map(str::to_string).ok_or_else(|| TestError::assertion(format!("then.'{}' is not a string", k)))
    }
    pub fn then_int(&mut self, c: &str, k: &str) -> Result<i64, TestError> {
        strict_i64(&self.then_any(c, k)?, "then", k)
    }
    pub fn then_bool(&mut self, c: &str, k: &str) -> Result<bool, TestError> {
        self.then_any(c, k)?.as_bool().ok_or_else(|| TestError::assertion(format!("then.'{}' is not a bool", k)))
    }
    pub fn record_input(&mut self, rel_path: &str, digest: &str) {
        if !self.in_mutation {
            self.inputs.insert(rel_path.replace('\\', "/").trim_start_matches('/').into(), digest.into());
        }
    }
    pub fn read_fixture(&mut self, rel_path: &str) -> Result<String, TestError> {
        let raw = fs::read(rel_path).map_err(ctx_err("cannot read fixture"))?;
        self.record_input(rel_path, &hash_fixture_bytes(&raw));
        String::from_utf8(raw).map_err(ctx_err("fixture is not UTF-8"))
    }
    pub fn verify_golden(&mut self, rel_path: &str, actual: &str) -> Result<(), TestError> {
        let raw = fs::read(rel_path).map_err(ctx_err("cannot read golden"))?;
        let exp = hash_fixture_bytes(&raw);
        self.record_input(rel_path, &exp);
        let act = hash_fixture_bytes(actual.as_bytes());
        if exp != act { return Err(aerr(format!("golden mismatch for '{rel_path}': expected {exp}, got {act}"))); }
        Ok(())
    }

    pub fn check_adverse<E>(&mut self, case_id: &str, variants_json: &[&str], exec: E) -> Result<(), TestError>
    where E: Fn(&str) -> Result<String, TestError> {
        if variants_json.is_empty() { return Err(aerr(format!("check_adverse for {}.{} requires at least one variant", self.contract_id, case_id))); }
        let when_map = self.case_map(case_id)?.get("when").and_then(JsonValue::as_object).cloned().unwrap_or_default();
        let pfx = format!("{}.{}", self.contract_id, case_id);
        let proj_when = extract_when_projections(&self.view);
        for v_json in variants_json {
            let v_doc = parse_json(v_json).map_err(|e| aerr(format!("variant is not valid JSON: {e}")))?;
            let _ = crate::probes::check_bola_variant_pair(&pfx, &v_doc)?;
            if v_doc.as_object().is_some() {
                for (wk, wexp) in &when_map {
                    let dp = format!("/{}", escape_pointer(wk));
                    let ptr = proj_when.get(wk).unwrap_or(&dp);
                    if let Some(va) = resolve_pointer(&v_doc, ptr) {
                        if !values_equal(va, wexp) {
                            return Err(aerr(format!("{pfx}.when.{wk} fixture mismatch: got {}, expected {}", va.to_json_string(), wexp.to_json_string())));
                        }
                    }
                }
            }
            let obs_json = exec(v_json)?;
            self.check_projection(case_id, &obs_json)?;
        }
        Ok(())
    }

    fn build_self_stub(&mut self, case_id: &str) -> Result<String, TestError> {
        if !self.in_mutation {
            self.self_stubbed = true;
            self.record_input(&format!(".drift/self-stub/{}", self.contract_id), "sha256:self-stub");
            if let Some(stub) = load_contract_plan_stub(&self.contract_id, &self.resolved_dir, &self.view, case_id) {
                return Ok(stub);
            }
        }
        build_projected_json(&self.view, case_id)
    }

    pub fn build_output(&mut self, case_id: &str) -> Result<String, TestError> {
        self.accessed_view.set(true);
        if !self.cases.iter().any(|c| c == case_id) {
            return Err(TestError::assertion(format!("case '{}' is not tagged on test '{}'", case_id, self.test_id)));
        }
        self.build_self_stub(case_id)
    }

    pub fn build_stub(&mut self, target: &str, case_id: &str, resolved_dir: &str) -> Result<String, TestError> {
        self.accessed_view.set(true);
        if target == self.contract_id { return self.build_self_stub(case_id); }
        let eff = if !resolved_dir.is_empty() { resolved_dir } else { &self.resolved_dir };
        let up = load_contract_view(target, eff)?;
        if up.get("id").and_then(|v| v.as_str()) == Some(self.contract_id.as_str()) {
            return self.build_self_stub(case_id);
        }
        let stub = if !self.in_mutation { load_contract_plan_stub(target, eff, &up, case_id) } else { None };
        if !self.in_mutation {
            let pid = up.get("id").and_then(|v| v.as_str()).unwrap_or(target);
            let pref = up.get("ref").or_else(|| up.get("digest")).and_then(|v| v.as_str()).unwrap_or("sha256:seam-stub");
            self.record_input(&format!(".drift/seam-stub/{}#{}", pid, case_id), pref);
            if let Some(s) = stub { return Ok(s); }
        }
        build_projected_json(&up, case_id)
    }

    pub(crate) fn fully_read_cases(&self) -> Vec<String> {
        let mut out = Vec::new();
        let Some(cm) = self.view.get("cases").and_then(|v| v.as_object()) else { return out; };
        for cid in &self.cases {
            let Some(tm) = cm.get(cid).and_then(|v| v.as_object()).and_then(|c| c.get("then")).and_then(|v| v.as_object()) else { continue; };
            let Some(rs) = self.read_keys.get(cid).filter(|_| !tm.is_empty()) else { continue; };
            if tm.keys().all(|k| rs.contains(k)) && forbidden_writes_of(&self.view, cid).iter().all(|r| rs.contains(&format!("@frame:{}", r))) {
                out.push(cid.clone());
            }
        }
        out.sort();
        out
    }
}

fn strict_i64(v: &JsonValue, side: &str, k: &str) -> Result<i64, TestError> {
    v.as_f64()
        .filter(|f| f.fract() == 0.0 && *f >= (i64::MIN as f64) && *f < 9223372036854775808.0)
        .map(|f| f as i64)
        .ok_or_else(|| TestError::assertion(format!("{}.'{}' is not an integer", side, k)))
}
