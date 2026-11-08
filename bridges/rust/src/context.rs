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

pub(crate) fn record_discovered_inventory(
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

pub(crate) fn update_shard_and_meta(
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

pub(crate) fn extract_then_projections(view: &BTreeMap<String, JsonValue>) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    if let Some(proj) = view.get("projections").and_then(|v| v.as_object()) {
        for (k, v) in proj {
            if k != "when" && k != "then" {
                if let Some(s) = v.as_str() {
                    out.insert(k.clone(), s.to_string());
                }
            }
        }
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

pub(crate) fn extract_when_projections(view: &BTreeMap<String, JsonValue>) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    if let Some(proj) = view.get("projections").and_then(|v| v.as_object()) {
        for (k, v) in proj {
            if k != "when" && k != "then" {
                if let Some(s) = v.as_str() {
                    out.insert(k.clone(), s.to_string());
                }
            }
        }
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

pub(crate) fn build_projected_json(
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

fn verify_single_frame_obs(
    contract_id: &str,
    case_id: &str,
    res: &str,
    obs: &JsonValue,
    is_ambient: bool,
) -> Result<(), TestError> {
    let mut checked = false;
    let write_lbl = if is_ambient {
        format!("undeclared write on perimeter resource '{}'", res)
    } else {
        format!("frame violation on resource '{}'", res)
    };
    let snap_lbl = if is_ambient {
        format!("undeclared state mutation on perimeter resource '{}'", res)
    } else {
        format!("frame state mutation on resource '{}'", res)
    };
    if let Some(n) = obs.as_f64() {
        if n.is_finite() && n >= 0.0 {
            checked = true;
            if n > 0.0 {
                return Err(TestError::assertion(format!(
                    "{}.{}: {}: expected 0 writes, observed {}",
                    contract_id, case_id, write_lbl, n
                )));
            }
        }
    } else if let Some(om) = obs.as_object() {
        for wk in ["writes", "operations", "events"] {
            if let Some(wv) = om.get(wk) {
                if let Some(wn) = wv.as_f64() {
                    if wn.is_finite() && wn >= 0.0 {
                        checked = true;
                        if wn > 0.0 {
                            return Err(TestError::assertion(format!(
                                "{}.{}: {}: expected 0 writes, observed {}",
                                contract_id, case_id, write_lbl, wn
                            )));
                        }
                    }
                } else if let Some(arr) = wv.as_array() {
                    checked = true;
                    if !arr.is_empty() {
                        return Err(TestError::assertion(format!(
                            "{}.{}: {}: expected 0 writes, observed {}",
                            contract_id,
                            case_id,
                            write_lbl,
                            arr.len()
                        )));
                    }
                }
            }
        }
        if let (Some(bef), Some(aft)) = (om.get("before"), om.get("after")) {
            checked = true;
            if !values_equal(bef, aft) {
                return Err(TestError::assertion(format!(
                    "{}.{}: {}: before and after snapshots differ",
                    contract_id, case_id, snap_lbl
                )));
            }
        }
    }
    if !checked {
        return Err(TestError::assertion(format!(
            "{}.{}: frame observation for '{}' must supply writes/operations/events or before/after snapshots",
            contract_id, case_id, res
        )));
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
    pub fn check_frame(&mut self, case_id: &str, frame_json: &str) -> Result<(), TestError> {
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
            let obs = fmap.get(res).or_else(|| fmap.get(base_res)).ok_or_else(|| {
                TestError::assertion(format!(
                    "{}.{}: missing frame observation for forbidden write resource '{}'",
                    self.contract_id, case_id, res
                ))
            })?;
            verify_single_frame_obs(&self.contract_id, case_id, res, obs, false)?;
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
            verify_single_frame_obs(&self.contract_id, case_id, k, obs_k, true)?;
        }
        Ok(())
    }

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
        self.accessed_view.set(true);
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
        self.accessed_view.set(true);
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
        if !self.in_mutation {
            let prod_id = up_view.get("id").and_then(|v| v.as_str()).unwrap_or(target);
            let prod_ref = up_view
                .get("ref")
                .and_then(|v| v.as_str())
                .or_else(|| up_view.get("digest").and_then(|v| v.as_str()))
                .unwrap_or("sha256:seam-stub");
            let seam_key = format!(".drift/seam-stub/{}#{}", prod_id, case_id);
            self.record_input(&seam_key, prod_ref);
        }
        build_projected_json(&up_view, case_id)
    }

    pub(crate) fn fully_read_cases(&self) -> Vec<String> {
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
            let forbidden = forbidden_writes_of(&self.view, cid);
            if t_map.keys().all(|k| read_set.contains(k))
                && forbidden
                    .iter()
                    .all(|r| read_set.contains(&format!("@frame:{}", r)))
            {
                out.push(cid.clone());
            }
        }
        out.sort();
        out
    }
}
