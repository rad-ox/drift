// Bounded formal verification harness, conservative subject manifest builder,
// and counterexample fixture replay for the DRIFT Rust bridge (SPEC §§4.2, 9.2, D269).

use crate::checks::{escape_pointer, resolve_pointer, unescape_pointer, values_equal, write_pointer};
use crate::json::{parse_json, sha256_hex, JsonValue};
use crate::{DriftContext, TestError};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

pub const KANI_VERIFIER_REF: &str =
    "sha256:6b616e692d727573742d626f756e6465642d76657269666965722d7630333230";

#[derive(Clone, Debug)]
pub struct SubjectManifestInput {
    pub area_root: String,
    pub source_paths: Vec<String>,
    pub lockfile_ref: String,
    pub toolchain: String,
    pub target: String,
    pub features: Vec<String>,
    pub flags: Vec<String>,
    pub harness: String,
    pub verifier_ref: String,
}

#[derive(Clone, Debug)]
pub struct BuiltSubjectManifest {
    pub subject_ref: String,
    pub json: String,
    pub source_digests: BTreeMap<String, String>,
}

/// Builds a conservative `drift.subject-manifest/1` JSON document and computes
/// its canonical `sha256:<64hex>` `subject_ref`.
pub fn build_subject_manifest(input: &SubjectManifestInput) -> Result<BuiltSubjectManifest, TestError> {
    if input.source_paths.is_empty() {
        return Err(TestError::harness("subject manifest requires at least one source path"));
    }
    let root = Path::new(&input.area_root);
    let mut sources_map = BTreeMap::new();
    let mut source_digests = BTreeMap::new();
    for rel in &input.source_paths {
        let norm = rel.replace('\\', "/").trim_start_matches('/').to_string();
        let full = root.join(&norm);
        let bytes = fs::read(&full).map_err(|e| {
            TestError::harness(format!("cannot read subject source '{}': {}", norm, e))
        })?;
        let dig = format!("sha256:{}", sha256_hex(&bytes));
        sources_map.insert(norm.clone(), JsonValue::Str(dig.clone()));
        source_digests.insert(norm, dig);
    }
    let mut core_map = BTreeMap::new();
    core_map.insert(
        "features".to_string(),
        JsonValue::Array(input.features.iter().cloned().map(JsonValue::Str).collect()),
    );
    core_map.insert(
        "flags".to_string(),
        JsonValue::Array(input.flags.iter().cloned().map(JsonValue::Str).collect()),
    );
    core_map.insert("harness".to_string(), JsonValue::Str(input.harness.clone()));
    core_map.insert(
        "lockfile_ref".to_string(),
        JsonValue::Str(input.lockfile_ref.clone()),
    );
    core_map.insert(
        "schema".to_string(),
        JsonValue::Str("drift.subject-manifest/1".to_string()),
    );
    core_map.insert("sources".to_string(), JsonValue::Object(sources_map));
    core_map.insert("target".to_string(), JsonValue::Str(input.target.clone()));
    core_map.insert(
        "toolchain".to_string(),
        JsonValue::Str(input.toolchain.clone()),
    );
    core_map.insert(
        "verifier_ref".to_string(),
        JsonValue::Str(input.verifier_ref.clone()),
    );
    let core_json = JsonValue::Object(core_map.clone()).to_json_string();
    let subject_ref = format!("sha256:{}", sha256_hex(core_json.as_bytes()));
    core_map.insert(
        "subject_ref".to_string(),
        JsonValue::Str(subject_ref.clone()),
    );
    let full_json = JsonValue::Object(core_map).to_json_string();
    Ok(BuiltSubjectManifest {
        subject_ref,
        json: full_json,
        source_digests,
    })
}

#[derive(Clone, Debug)]
pub struct BoundedPointerVerifyResult {
    pub outcome: String,
    pub completion: String,
    pub loop_unwind: i64,
    pub cover_checks: BTreeMap<String, String>,
    pub counterexample: Option<(String, String)>,
}

/// Bounded exhaustive verification of RFC 6901 JSON Pointer escaping,
/// round-trip resolution, and leading-zero array index rejection up to
/// `loop_unwind` segments. When `inject_fault` is true, simulates an
/// unescaped `~1` defect to produce a concrete counterexample witness.
pub fn verify_pointer_roundtrip_bounded(
    loop_unwind: usize,
    max_bound_required: usize,
    inject_fault: bool,
    restrict_cover: bool,
) -> BoundedPointerVerifyResult {
    let mut cover_checks = BTreeMap::new();
    cover_checks.insert(
        "escaped_tilde_and_slash".to_string(),
        "unsatisfied".to_string(),
    );
    cover_checks.insert(
        "leading_zero_array_index_rejected".to_string(),
        "unsatisfied".to_string(),
    );
    cover_checks.insert(
        "nested_object_roundtrip".to_string(),
        "unsatisfied".to_string(),
    );

    let alphabet: &[&str] = if restrict_cover {
        &["plain", "item"]
    } else {
        &["plain", "a~b", "c/d", "a~b/c", "0", "01", "layout"]
    };

    let mut counterexample: Option<(String, String)> = None;
    let bound = loop_unwind.min(alphabet.len());
    for i in 0..bound {
        let seg = alphabet[i];
        let escaped = if inject_fault && seg.contains('/') {
            seg.to_string()
        } else {
            escape_pointer(seg)
        };
        let unescaped = unescape_pointer(&escaped);
        if seg.contains('~') && seg.contains('/') {
            cover_checks.insert(
                "escaped_tilde_and_slash".to_string(),
                "satisfied".to_string(),
            );
        }
        let mut root = BTreeMap::new();
        let ptr = format!("/{}", escaped);
        let expected = JsonValue::Number(200.0);
        write_pointer(&mut root, &ptr, expected.clone());
        let doc = JsonValue::Object(root);
        let resolved = resolve_pointer(&doc, &format!("/{}", escape_pointer(seg)));
        let roundtrip_ok = unescaped == seg && resolved.is_some_and(|v| values_equal(v, &expected));
        if !roundtrip_ok && counterexample.is_none() {
            counterexample = Some((seg.to_string(), ptr));
        }

        for j in 0..bound {
            let sub = alphabet[j];
            let nested_ptr = format!("/{}/{}", escape_pointer(seg), escape_pointer(sub));
            let mut nested_root = BTreeMap::new();
            write_pointer(&mut nested_root, &nested_ptr, JsonValue::Bool(true));
            let nested_doc = JsonValue::Object(nested_root);
            if resolve_pointer(&nested_doc, &nested_ptr) == Some(&JsonValue::Bool(true)) {
                cover_checks.insert(
                    "nested_object_roundtrip".to_string(),
                    "satisfied".to_string(),
                );
            }
        }
    }

    if !restrict_cover {
        let arr_doc = JsonValue::Array(vec![JsonValue::Number(10.0), JsonValue::Number(20.0)]);
        if resolve_pointer(&arr_doc, "/01").is_none()
            && resolve_pointer(&arr_doc, "/1") == Some(&JsonValue::Number(20.0))
        {
            cover_checks.insert(
                "leading_zero_array_index_rejected".to_string(),
                "satisfied".to_string(),
            );
        }
    }

    let truncated = loop_unwind < max_bound_required;
    // Precedence rule: a valid counterexample stays "violated" even if exploration truncates.
    let outcome = if counterexample.is_some() {
        "violated".to_string()
    } else if truncated {
        "inconclusive".to_string()
    } else {
        "passed".to_string()
    };
    let completion = if truncated {
        "truncated_unwind".to_string()
    } else {
        "exhausted_within_bounds".to_string()
    };

    BoundedPointerVerifyResult {
        outcome,
        completion,
        loop_unwind: loop_unwind as i64,
        cover_checks,
        counterexample,
    }
}

/// Writes a reproducible counterexample witness fixture (`.cex.json`) so bound
/// tests can replay and assert the failure without editing `.drift/contracts/`.
pub fn write_counterexample_fixture(
    path: &Path,
    seg: &str,
    expected_roundtrip: bool,
) -> Result<(), TestError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| {
            TestError::harness(format!("cannot create counterexample dir: {}", e))
        })?;
    }
    let mut when_m = BTreeMap::new();
    when_m.insert("op".to_string(), JsonValue::Str("flex-row".to_string()));
    when_m.insert("pointer_seg".to_string(), JsonValue::Str(seg.to_string()));
    let mut then_m = BTreeMap::new();
    then_m.insert(
        "roundtrip_ok".to_string(),
        JsonValue::Bool(expected_roundtrip),
    );
    let mut witness = BTreeMap::new();
    witness.insert("when".to_string(), JsonValue::Object(when_m));
    witness.insert("then".to_string(), JsonValue::Object(then_m));
    let mut doc = BTreeMap::new();
    doc.insert(
        "kind".to_string(),
        JsonValue::Str("counterexample_witness".to_string()),
    );
    doc.insert(
        "command".to_string(),
        JsonValue::Str("cargo kani --harness verify_pointer_roundtrip_and_resolve".to_string()),
    );
    doc.insert("witness".to_string(), JsonValue::Object(witness));
    let text = JsonValue::Object(doc).to_json_string();
    fs::write(path, format!("{}\n", text))
        .map_err(|e| TestError::harness(format!("cannot write counterexample fixture: {}", e)))
}

/// Replays a counterexample witness fixture inside an existing `run_drift_case`
/// execution, recording the fixture input and failing with `TestError::Assertion`
/// if `inject_fault` is still active.
pub fn replay_counterexample_fixture(
    ctx: &mut DriftContext,
    rel_fixture_path: &str,
    inject_fault: bool,
) -> Result<(), TestError> {
    let text = ctx.read_fixture(rel_fixture_path)?;
    let doc = parse_json(&text)
        .map_err(|e| TestError::harness(format!("invalid counterexample JSON: {}", e)))?;
    let obj = doc
        .as_object()
        .ok_or_else(|| TestError::harness("counterexample root must be an object"))?;
    let witness = obj
        .get("witness")
        .and_then(|v| v.as_object())
        .ok_or_else(|| TestError::harness("counterexample missing witness"))?;
    let when_m = witness
        .get("when")
        .and_then(|v| v.as_object())
        .ok_or_else(|| TestError::harness("counterexample missing witness.when"))?;
    let then_m = witness
        .get("then")
        .and_then(|v| v.as_object())
        .ok_or_else(|| TestError::harness("counterexample missing witness.then"))?;
    let seg = when_m
        .get("pointer_seg")
        .and_then(|v| v.as_str())
        .ok_or_else(|| TestError::harness("counterexample missing pointer_seg"))?;
    let expected_ok = then_m
        .get("roundtrip_ok")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);

    let escaped = if inject_fault && seg.contains('/') {
        seg.to_string()
    } else {
        escape_pointer(seg)
    };
    let mut root = BTreeMap::new();
    write_pointer(&mut root, &format!("/{}", escaped), JsonValue::Number(1.0));
    let actual_ok = unescape_pointer(&escaped) == seg
        && resolve_pointer(
            &JsonValue::Object(root),
            &format!("/{}", escape_pointer(seg)),
        ) == Some(&JsonValue::Number(1.0));
    if actual_ok != expected_ok {
        return Err(TestError::assertion(format!(
            "counterexample fixture '{}' violated: pointer_seg '{}' roundtrip_ok={}, expected={}",
            rel_fixture_path, seg, actual_ok, expected_ok
        )));
    }
    Ok(())
}

#[cfg(kani)]
mod kani_proofs {
    use super::*;

    #[kani::proof]
    #[kani::unwind(8)]
    pub fn verify_pointer_roundtrip_and_resolve() {
        let idx: usize = kani::any();
        kani::assume(idx < 4);
        let samples = ["plain", "a~b", "c/d", "a~1b~0c"];
        let seg = samples[idx];
        let escaped = escape_pointer(seg);
        let unescaped = unescape_pointer(&escaped);
        kani::cover!(seg.contains('~') && seg.contains('/'), "escaped_tilde_and_slash");
        assert_eq!(unescaped, seg);
    }
}
