#!/usr/bin/env python3
"""Standalone self-test vectors for verifier/drift_verify.py (MIT License)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from drift_verify_base import (
    ENV_KEYS,
    _has_approval_blocker,
    _is_unanchored_prose_source,
    canonical_json,
    digest_matches,
)
from drift_verify_pact_cells import _atom_meet_py, _atom_subsumes_py, _check_when_cell_coverage_py
from drift_verify_parity import evaluate_contract_composition_core, evaluate_contract_parity_impl
from drift_verify_ra import VC_KEYS, evaluate_contract_controls_core, evaluate_contract_evaluations_core, evaluate_contract_studies_core
from drift_verify_sec import evaluate_contract_security_impl


def _expect_err(fn: Any, arg: Any) -> None:
    try:
        fn(arg)
        raise AssertionError(arg)
    except ValueError:
        pass


def run_03_self_test(dv_mod: Any) -> None:
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td)
        (tp / "p03@1.toml").write_text('drift = "0.3"\nprofile = "p03@1"\n[schema.when]\nbalance = { type = "int", min = 0 }\n[schema.then]\nbalance = { type = "int", min = 0 }\n', "utf-8")
        (tp / "c03.toml").write_text('drift = "0.3"\nid = "c03"\nintent = "C03."\n[use]\nprofile = "p03@1"\n[scope]\nwrites = []\nreads = []\nindirect = "none"\n[cases.ok]\nat = ["unit"]\nwhen.balance = 100\nthen.balance = { peer = { eq = "when.balance", balance = { add = ["when.balance"] } } }\n', "utf-8")
        v03_u = dv_mod.verify_contract_toml(tp / "c03.toml", tp)
        assert v03_u["digest"].startswith("dr2b:sha256:") and v03_u["approval"] == "absent" and v03_u["required_capabilities"] == ["rel-linear-balance/1"]
        (tp / "c03.toml").write_text((tp / "c03.toml").read_text("utf-8") + f'[approval]\nbehavior_ref = "{v03_u["ref"]}"\nassurance_ref = "{v03_u["assurance_ref"]}"\nby = "o"\nat = 2026-11-09T18:25:00Z\n', "utf-8")
        v03 = dv_mod.verify_contract_toml(tp / "c03.toml", tp)
        assert v03["approval"] == "current" and v03["digest"] == v03_u["digest"]
        ev03_ok = [{"test": "T#ok", "contract": "c03", "cases": ["ok"], "read": ["ok"], "level": "unit", "outcome": "passed", "digest": v03["ref"], "schema": "0.3", "capabilities": ["rel-linear-balance/1"]}]
        ev03_bad = [{**ev03_ok[0], "capabilities": []}]
        assert dv_mod.evaluate_contract(v03, "current", ev03_ok, 0, 0, [])["ok"] and "events.invalid" in dv_mod.evaluate_contract(v03, "current", ev03_bad, 0, 0, [])["reasons"]
        assert "contract.approval.unlisted" in dv_mod.evaluate_contract(v03, "current", ev03_ok, 0, 0, [], {"pack": "core@1", "approvers": ["alice"]})["reasons"]
        v03_sec = {**v03, "profile_security": ["sast"], "profile_simulation": True}
        r_sec_sim = dv_mod.evaluate_contract(v03_sec, "current", ev03_ok, 0, 0, [])["reasons"]
        assert "security.missing" in r_sec_sim and "sim.missing" in r_sec_sim


def run_mig_parity_self_test(ck: dict[str, Any], digest_matches_fn: Any) -> None:
    h1, h2, h3 = "sha256:" + "1" * 64, "sha256:" + "2" * 64, "sha256:" + "3" * 64
    p_ck = {**ck, "scope_reads": ["db#orders"], "scope_writes": ["db#users"], "scope_code": ["src/svc.py"], "invariants": [], "cutover": {"legacy_target": "leg", "candidate_target": "cand", "normalization_ref": h1, "corpus_ref": h1, "requirement_ref": ck["digest"], "migration_ids": ["mig-1"], "rollback_readback": "required", "enforce": "always"}}
    p_rec = {"schema": "drift.parity-receipt/1", "contract": "svc", "digest": ck["digest"], "requirement_ref": ck["digest"], "legacy_target": "leg", "candidate_target": "cand", "legacy_subject_ref": h1, "candidate_subject_ref": h2, "normalization_ref": h1, "corpus_ref": h1, "legacy_cases": ["ok"], "candidate_cases": ["ok"], "diverged_observations": [], "effect_violations": [], "frame_verified": True, "rollback_readback": "verified", "outcome": "passed"}
    assert "parity.migration_unverified" in evaluate_contract_parity_impl(p_ck, [p_rec], "release", digest_matches_fn, h2, set(), [])[0]
    assert "parity.subject_mismatch" in evaluate_contract_parity_impl(p_ck, [p_rec], "release", digest_matches_fn, h3, set(), [])[0]
    p_b = {"area_id": "cat", "version": "v1", "offers": [{"operation": "GET /items", "resource": "urn:http:cat", "when_domain": ["id"], "then_domain": ["200"]}], "requires": [], "shared_writes": [], "shared_reads": []}
    c_b = lambda wd: {"area_id": "chk", "version": "v1", "offers": [], "requires": [{"operation": "GET /items", "resource": "urn:http:cat", "when_domain": wd, "then_domain": ["200"]}], "shared_writes": [], "shared_reads": []}
    cm_base = {"schema": "drift.composition-manifest/1", "active_producers": [p_b], "retained_events": [], "rollback_targets": [], "declared_coordinators": {}, "critical_paths": []}
    assert evaluate_contract_composition_core(ck, [{**cm_base, "active_consumers": [c_b(["id"])]}])[0] == []
    assert "federation.request_rejected:chk@v1->cat@v1:urn:http:cat:sku" in evaluate_contract_composition_core(ck, [{**cm_base, "active_consumers": [c_b(["id", "sku"])]}])[0]


def run_sec_self_test_core(ck: dict[str, Any], digest_matches_fn: Any, eval_sec_fn: Any, dv_mod: Any = None) -> None:
    run_mig_parity_self_test(ck, digest_matches_fn)
    sec_ck = {**ck, "profile_security": ["sast"], "scope_code": ["src/api.rs#authorize"]}
    b_rec = {"category": "sast", "tool": "semgrep", "tool_ref": "sha256:" + "1" * 64, "ruleset_ref": "sha256:" + "2" * 64, "contract": "svc", "digest": ck["ref"], "code_snapshot": "a" * 40, "covered_scope": ["src/api.rs#authorize"], "cases": ["ok"], "outcome": "passed"}
    assert eval_sec_fn(sec_ck, [b_rec], {}, "a" * 40, digest_matches_fn)[0] == []
    for bad in ({"covered_scope": ["src/api.rs#unrelated"]}, {"cases": ["nonexistent"]}):
        assert "security.inconclusive" in eval_sec_fn(sec_ck, [{**b_rec, **bad}], {}, "a" * 40, digest_matches_fn)[0]
    assert "security.inconclusive" in eval_sec_fn(sec_ck, [b_rec], {}, "", digest_matches_fn)[0]
    r_viol = {**b_rec, "ruleset_ref": "sha256:" + "3" * 64, "outcome": "violated"}
    c1, c2 = eval_sec_fn(sec_ck, [r_viol, b_rec], {}, "a" * 40, digest_matches_fn), eval_sec_fn(sec_ck, [b_rec, r_viol], {}, "a" * 40, digest_matches_fn)
    assert c1 == c2 and "security.violated" in c1[0] and all(x.get("reason") == "security.conflicting_receipts" for x in c1[1])
    if dv_mod is not None:
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td)
            (tp / "p@1.toml").write_text('drift = "0.3"\nprofile = "p@1"\n[schema.when]\nop = { type = "string" }\n[schema.then]\nstatus = { type = "int", ptr = "/status" }\ninv_p = { type = "int", ptr = "/ip" }\n[concepts."orders.c"]\nmeans = "Cancel order."\n', "utf-8")
            for fn_n, u_c in (("c1.toml", 'concepts = ["orders.c"]\n'), ("c2.toml", "")):
                (tp / fn_n).write_text(f'drift = "0.3"\nid = "c"\nintent = "C."\n[use]\nprofile = "p@1"\n{u_c}[scope]\nwrites = []\nreads = []\nindirect = "none"\n[invariants]\ninv_p = 1\n[cases.ok]\nwhen.op = "x"\nthen.status = 200\n', "utf-8")
            assert dv_mod.verify_contract_toml(tp / "c1.toml", tp)["digest"] == dv_mod.verify_contract_toml(tp / "c2.toml", tp)["digest"]
        run_03_self_test(dv_mod)


def run_ra_self_test_impl(ck: dict[str, Any], digest_matches_fn: Any) -> None:
    h1, h2 = "sha256:" + "1" * 64, "sha256:" + "2" * 64
    vc1, ac1 = {k: h1 for k in VC_KEYS}, {"report_ref": h1, "report_uri": "vault://rep/1", "retention_class": "10y-qms", "adapter_version": "0.3.4", "verifier_version": "0.3.4"}
    c_ra = {**ck, "controls": {"c1": {"kind": "software", "mitigates": ["r1"], "cases": ["ok"], "implementation_evidence": ["case_killed"], "effectiveness_evidence": ["study:s1", "evaluation:e1"], "context_ref": h1, "criteria_ref": h1, "enforce": "release", "requirement_ref": ck["digest"]}}}
    res_ok = [{"case": "ok", "level": "unit", "state": "verified"}]
    rsn_exec, pend_exec, _ = evaluate_contract_controls_core(c_ra, res_ok, [], [], [], [], [], "execution", True)
    rsn_rel, _, _ = evaluate_contract_controls_core(c_ra, res_ok, [], [], [], [], [], "release", True)
    assert not rsn_exec and pend_exec == ["c1"] and "study.missing" in rsn_rel
    s_rec = {"schema": "drift.study-receipt/1", "contract": "svc", "digest": ck["digest"], "study_id": "s1", "subject_ref": h1, "protocol_ref": h1, "user_groups": ["nurses"], "environment_ref": h1, "validity_context": {**vc1, "context_ref": h2}, "critical_tasks": [{"task_id": "t1", "cases": ["ok"], "participants": 15, "completed": 15, "use_errors": 0, "hazards_observed": 0, "outcome": "supported"}], "limitations": ["sim"], "archival": ac1, "outcome": "supported"}
    assert "evidence.context_mismatch" in evaluate_contract_studies_core(c_ra, [s_rec], h1, digest_matches_fn)[0]
    e_rec = {"schema": "drift.evaluation-receipt/1", "contract": "svc", "digest": ck["digest"], "evaluation_id": "e1", "subject_ref": h1, "config_ref": h1, "corpus_ref": h1, "protocol_ref": h1, "preprocessing_ref": h1, "reference_labels_ref": h1, "criteria_ref": h1, "criteria": {"min_metrics": {"sens": 0.90}, "max_metrics": {}, "required_subgroups": ["pediatric"]}, "aggregate": {"sample_size": 500, "metrics": {"sens": 0.96}, "ci_lower": {"sens": 0.94}, "ci_upper": {"sens": 0.98}}, "subgroups": [{"id": "pediatric", "sample_size": 40, "min_sample_size": 30, "metrics": {"sens": 0.82}, "ci_lower": {"sens": 0.75}, "ci_upper": {"sens": 0.88}, "outcome": "supported"}], "validity_context": vc1, "archival": ac1, "outcome": "supported"}
    assert "evaluation.subgroup_violated" in evaluate_contract_evaluations_core(c_ra, [e_rec], h1, digest_matches_fn)[0]


def run_verifier_self_test(dv_mod: Any) -> int:
    assert canonical_json(-0.0) == "0" and canonical_json(1e21) == "1e+21" and canonical_json(1e-6) == "0.000001" and canonical_json(1e-7) == "1e-7" and canonical_json({"\ue000": 1, "\U0001f600": 2}) == '{"\U0001f600":2,"\ue000":1}'
    for b in (1 << 53, -(1 << 53), float("nan"), float("inf")):
        _expect_err(canonical_json, b)
    eb = '"contract":"a","cases":["c"],"level":"unit","outcome":"passed"'
    for b in (f'"test":"t#1","test":"t#2",{eb}', f'"test":"t#1",{eb},"extra":1', f'"test":"t#1",{eb},"read":["other"]', '"test":"t#1","contract":"Bad_Id","cases":["c"],"level":"unit","outcome":"passed"', '"test":"t#1","contract":"a","cases":["c"],"level":"Unit","outcome":"passed"', f'"test":"t#1",{eb},"digest":"dr1:UPPER0000000"'):
        _expect_err(dv_mod.validate_event_line, "{" + b + "}")
    _expect_err(dv_mod.validate_event_line, '{"a":' * 65 + "1" + "}" * 65)
    assert len(dv_mod.validate_inventory_text(json.dumps({"version": 1, "classes": ["a.mjs", "b.mjs"], "tests": ["a.mjs#t1", "b.mjs#t2"], "snapshot": "0" * 40, "pack_ref": "dr1:" + "0" * 12, "touched": ["src/a.mjs", "src/b.mjs"], "inputs": {"a.mjs#t1": {"src/a.mjs": "sha256:111"}}, "env": dict.fromkeys(ENV_KEYS, "v")}))["tests"]) == 2
    assert dv_mod.validate_inventory_text(json.dumps({"version": 2, "classes": ["a"], "tests": ["a#t"], "execution_ref": "sha256:" + "a" * 64, "touched": []}))["version"] == 2
    ib = '"version":1,"classes":["a"],"tests":["a#t1"]'
    for sfx in ('"version":2,"classes":[],"tests":[]', '"version":true,"classes":[],"tests":[]', '"version":1,"classes":["b","a"],"tests":[]', '"version":1,"classes":["a/b"],"tests":[]', '"version":1,"classes":["a"],"tests":["other#t1"]', f'{ib},"snapshot":"bad"', f'{ib},"pack_ref":"dr1:bad"', f'{ib},"touched":["/abs"]', f'{ib},"touched":["../e"]', f'{ib},"inputs":{{"u#t":{{"f":"1"}}}}', f'{ib},"env":{{"toolchain":"v1"}}', f'{ib},"extra":1'):
        _expect_err(dv_mod.validate_inventory_text, "{" + sfx + "}")
    assert _is_unanchored_prose_source("observed in prod") and not _is_unanchored_prose_source("src/a/Item.java") and _has_approval_blocker({"scope": {"indirect": "unknown"}}, {})
    ck = {"id": "svc", "digest": "dr1:sha256:" + "a" * 64, "ref": "dr1:" + "a" * 12, "approval": "current", "approver": "o", "profile_proof": "killed", "cases": {"ok": {"at": ["unit"], "then": {"status": 200}}}, "open_cnt": 0, "exec_blk": False, "rel_blk": False}
    ev = [{"test": "T#ok", "contract": "svc", "cases": ["ok"], "read": ["ok"], "level": "unit", "outcome": "passed", "digest": ck["ref"]}]
    assert not dv_mod.evaluate_contract(ck, "current", ev, 0, 0, [])["ok"] and dv_mod.evaluate_contract(ck, "current", ev, 0, 0, [], mutations_ok=True)["ok"]
    run_sec_self_test_core(ck, digest_matches, evaluate_contract_security_impl, dv_mod)
    run_ra_self_test_impl(ck, digest_matches)
    tz, sz = {"/z": {"kind": "enum_set", "in": ["a", "b"]}}, {"/z": {"type": "string", "enum": ["a", "b"]}}
    ca, cb, cu = {"/z": {"kind": "enum_set", "in": ["a"]}}, {"/z": {"kind": "enum_set", "in": ["b"]}}, {"/a_open": {"kind": "int_range", "min": 0}, "/z": {"kind": "enum_set", "in": ["a"]}}
    assert _check_when_cell_coverage_py(tz, [ca, cb, cu], sz, 64) == "covered" and _check_when_cell_coverage_py(tz, [ca, cu], sz, 64) == "uncovered"
    mc = [{"/zr": {"kind": "bool_val", "eq": False}}, {"/zr": {"kind": "bool_val", "eq": True}}] + [{"/as": {"kind": "int_range", "min": i, "max": i}, "/zr": {"kind": "bool_val", "eq": False}} for i in range(80)]
    assert _check_when_cell_coverage_py({"/as": {"kind": "int_range", "min": 0, "max": 1000}, "/zr": {"kind": "enum_set", "in": ["false", "true"]}}, mc, {}, 64) == "covered"
    rc = [{"/zs": {"kind": "int_range", "min": i, "max": i}} for i in range(32)] + [{f"/a_r{j:02d}": {"kind": "bool_val", "eq": True}, "/zs": {"kind": "int_range", "min": 0, "max": 0}} for j in range(16)]
    assert _check_when_cell_coverage_py({"/zs": {"kind": "int_range", "min": 0, "max": 31}}, rc, {f"/a_r{j:02d}": {"type": "bool"} for j in range(16)}, 256) == "covered"
    assert _check_when_cell_coverage_py({"/x": {"kind": "int_range", "min": 0, "max": 7}}, [{"/x": {"kind": "int_range", "min": i, "max": i}} for i in range(7)], {}, 2) == "undecided"
    lo64, hi64 = -(1 << 63), (1 << 63) - 1
    sx = {"/x": {"type": "int"}}
    left = {"/x": {"kind": "int_range", "max": 0}}
    right = {"/x": {"kind": "int_range", "min": 1}}
    assert _check_when_cell_coverage_py({}, [left, right], sx, 3) == "covered"
    assert _check_when_cell_coverage_py({}, [left, right], sx, 2) == "undecided"
    assert _check_when_cell_coverage_py({}, [left, {"/x": {"kind": "int_range", "min": 2}}], sx, 8) == "uncovered"
    excluded = {"/x": {"kind": "not_in", "not_in": ["0"]}}
    assert _check_when_cell_coverage_py({}, [excluded], sx, 8) == "uncovered"
    assert _check_when_cell_coverage_py({}, [excluded, {"/x": {"kind": "int_range", "min": 0, "max": 0}}], sx, 8) == "covered"
    assert _check_when_cell_coverage_py({}, [{"/x": {"kind": "int_range", "max": hi64}}], sx, 8) == "undecided"
    assert _check_when_cell_coverage_py({}, [{"/x": {"kind": "any", "peer_eq": ["/y"]}}], sx, 8) == "undecided"
    assert _check_when_cell_coverage_py({"/x": {"kind": "any", "peer_eq": ["/y"]}}, [], sx, 8) == "undecided"
    assert _check_when_cell_coverage_py({}, [right], {"/x": {"type": "int", "min": 1}}, 1) == "covered"
    assert _check_when_cell_coverage_py({"/x": {"kind": "enum_set", "in": ["a"]}}, [{"/x": {"kind": "unrepresentable"}}], {}, 8) == "undecided"
    assert _atom_meet_py({"kind": "int_range", "min": hi64, "max": hi64}, {"kind": "not_in", "not_in": [str(hi64)]}) is None and _atom_meet_py({"kind": "int_range", "min": lo64, "max": lo64}, {"kind": "not_in", "not_in": [str(lo64)]}) is None
    assert _atom_meet_py({"kind": "int_range", "min": lo64, "max": hi64, "peer_le": ["/y"]}, {"kind": "not_in", "not_in": ["0"]}) == {"kind": "unrepresentable", "peer_le": ["/y"]} and not _atom_subsumes_py({"kind": "int_range", "min": lo64, "max": hi64}, {"kind": "enum_set", "in": ["0"]})
    en64 = _atom_meet_py({"kind": "int_range", "min": hi64 - 64, "max": hi64}, {"kind": "not_in", "not_in": [str(hi64 - 1)]})
    assert en64 is not None and en64["kind"] == "enum_set" and len(en64["in"]) == 64 and _atom_subsumes_py({"kind": "int_range", "min": hi64, "max": hi64}, en64) and _atom_meet_py({"kind": "int_range", "min": hi64 - 65, "max": hi64}, {"kind": "not_in", "not_in": [str(hi64 - 1)]}) == {"kind": "unrepresentable"}
    print("drift_verify.py self-test: ok (RFC 8785 JCS, event & full inventory schema vectors passed)")
    return 0
