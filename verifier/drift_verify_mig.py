#!/usr/bin/env python3
"""DRIFT Independent Reference DB Migration Receipt Verifier (MIT License)."""

from __future__ import annotations
import re
from pathlib import Path
from typing import Any
SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MIG_KEYS = frozenset(("schema", "contract", "digest", "resource", "migration_id", "phase", "tool", "tool_ref", "subject_ref", "code_snapshot", "epoch_manifest_ref", "covered_scope", "cases", "epoch_compatibility", "data_correctness", "operational_safety", "outcome"))
MIG_PHASES = frozenset(("expand", "backfill", "contract"))
def collect_receipt_files(events_paths: list[Path], suffix: str) -> list[Path]:
  out, seen = [], set()
  for p in events_paths:
    for f in (sorted(p.glob(f"*{suffix}")) if p.is_dir() else ([p] if p.is_file() and p.name.endswith(suffix) else [])):
      if f not in seen: seen.add(f); out.append(f)
  return out
def load_migration_receipts_core(events_paths: list[Path], decode_fn: Any, valid_rel_scope_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
  out, errs = [], []
  for mf in collect_receipt_files(events_paths, ".migration.json"):
    try:
      doc = decode_fn(mf.read_text(encoding="utf-8"))
      if not isinstance(doc, dict) or set(doc) != MIG_KEYS or doc.get("schema") != "drift.migration-receipt/1": raise ValueError("mig_keys")
      cid, dig, res = str(doc.get("contract", "")), str(doc.get("digest", "")), str(doc.get("resource", ""))
      mid, ph, tool = str(doc.get("migration_id", "")), str(doc.get("phase", "")), str(doc.get("tool", ""))
      tref, sref, csnap, emref, outc = str(doc.get("tool_ref", "")), str(doc.get("subject_ref", "")), str(doc.get("code_snapshot", "")), str(doc.get("epoch_manifest_ref", "")), str(doc.get("outcome", ""))
      if not cid or not dig or not res.strip() or not mid.strip() or ph not in MIG_PHASES or not tool.strip() or not SHA256_REF_RE.match(tref) or not SHA256_REF_RE.match(sref) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", csnap) or not SHA256_REF_RE.match(emref) or outc not in ("passed", "violated", "inconclusive"): raise ValueError("mig_envelope")
      cov, cs, ec, dc, osaf = doc.get("covered_scope"), doc.get("cases"), doc.get("epoch_compatibility"), doc.get("data_correctness"), doc.get("operational_safety")
      if not isinstance(cov, list) or not cov or len(set(cov)) != len(cov) or not all(valid_rel_scope_fn(x) for x in cov) or not isinstance(cs, list) or not cs or not all(isinstance(x, str) and x.strip() for x in cs) or not isinstance(ec, dict) or not isinstance(dc, dict) or not isinstance(osaf, dict): raise ValueError("mig_tables")
      act_ep, cmp_ep = [str(x) for x in ec.get("active_epochs", []) if isinstance(x, str) and x.strip()], [str(x) for x in ec.get("compatible_epochs", []) if isinstance(x, str) and x.strip()]
      inc_ep = ec.get("incompatible_epochs", [])
      if not isinstance(inc_ep, list) or any(not isinstance(ie, dict) or set(ie) != {"epoch", "operation", "detail"} for ie in inc_ep): raise ValueError("incompatible_epochs")
      inv_chk, rows_v, viols = [str(x) for x in dc.get("invariants_checked", []) if isinstance(x, str) and x.strip()], dc.get("rows_verified"), dc.get("violations")
      if not isinstance(rows_v, int) or isinstance(rows_v, bool) or rows_v < 0 or not isinstance(viols, int) or isinstance(viols, bool) or viols < 0: raise ValueError("data_correctness")
      lmode, mlock, lbud, dms, dbud, cref = str(osaf.get("lock_mode", "")), osaf.get("max_lock_ms"), osaf.get("lock_budget_ms"), osaf.get("duration_ms"), osaf.get("duration_budget_ms"), str(osaf.get("context_ref", ""))
      if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in (mlock, lbud, dms, dbud)): raise ValueError("operational_safety")
      out.append({
        "schema": "drift.migration-receipt/1", "contract": cid, "digest": dig, "resource": res, "migration_id": mid, "phase": ph, "tool": tool, "tool_ref": tref, "subject_ref": sref, "code_snapshot": csnap, "epoch_manifest_ref": emref, "covered_scope": sorted(set(cov)), "cases": sorted(set(cs)),
        "epoch_compatibility": {"active_epochs": sorted(set(act_ep)), "compatible_epochs": sorted(set(cmp_ep)), "incompatible_epochs": [{"detail": str(x["detail"]), "epoch": str(x["epoch"]), "operation": str(x["operation"])} for x in inc_ep]},
        "data_correctness": {"invariants_checked": sorted(set(inv_chk)), "rows_verified": rows_v, "violations": viols},
        "operational_safety": {"context_ref": cref, "duration_budget_ms": dbud, "duration_ms": dms, "lock_budget_ms": lbud, "lock_mode": lmode, "max_lock_ms": mlock},
        "outcome": outc,
      })
    except Exception as exc: errs.append(f"{mf.name}: {exc}")
  return out, errs
def evaluate_contract_migration_core(contract: dict[str, Any], mig_receipts: list[dict[str, Any]], policy: dict[str, Any] | None, expected_snapshot: str, expected_subject_ref: str, digest_matches_fn: Any, cov_matches_fn: Any) -> tuple[list[str], list[dict[str, Any]]]:
  pol = policy or {}
  req_mig = pol.get("pack") == "core@1" and pol.get("migration") == "required"
  scope_code = contract.get("scope_code") or []
  res_set = {str(r).strip() for r in (contract.get("scope_reads") or []) + (contract.get("scope_writes") or []) if str(r).strip()}
  raw_cases = contract.get("cases") or {}
  active_cases = {cid for cid, cm in raw_cases.items() if isinstance(cm, dict) and "status" not in cm}
  inv_keys = set(contract.get("invariants") or ())
  by_target: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
  for r in mig_receipts:
    if r["contract"] == contract["id"] and digest_matches_fn(r["digest"], contract["digest"]):
      tkey = (r["resource"], r["migration_id"])
      ikey = repr((r["phase"], r["tool"], r["tool_ref"], r["subject_ref"], r["code_snapshot"], r["epoch_manifest_ref"], r["covered_scope"], r["cases"], r["epoch_compatibility"], r["data_correctness"], r["operational_safety"], r["outcome"]))
      by_target.setdefault(tkey, {})[ikey] = r
  if not by_target and not (req_mig and res_set): return [], []
  if not by_target and req_mig and res_set: return ["migration.missing"], []
  eval_list, reasons, has_viol, has_inc = [], [], False, False
  for tkey in sorted(by_target):
    bucket = by_target[tkey]
    group = [bucket[k] for k in sorted(bucket)]
    has_conflict, grp_viol, grp_evals = len(group) > 1, False, []
    for rec in group:
      eff, rsn, r_res = rec["outcome"], "", rec["resource"].strip()
      res_ok = bool(r_res) and (r_res in res_set or ("#" in r_res and r_res.split("#", 1)[0].strip() in res_set))
      ec, dc, osaf = rec["epoch_compatibility"], rec["data_correctness"], rec["operational_safety"]
      if not res_ok or not scope_code or not all(any(cov_matches_fn(c, sc) for c in rec["covered_scope"]) for sc in scope_code) or not active_cases or not all(c in active_cases for c in rec["cases"]): eff, rsn = ("inconclusive" if eff == "passed" else eff), "migration.incomplete_scope"
      elif expected_snapshot and rec["code_snapshot"] != expected_snapshot: eff, rsn = ("inconclusive" if eff == "passed" else eff), "migration.snapshot_mismatch"
      elif expected_subject_ref and rec["subject_ref"] != expected_subject_ref: eff, rsn = ("inconclusive" if eff == "passed" else eff), "migration.subject_mismatch"
      elif ec["incompatible_epochs"]: eff, rsn = "violated", "migration.epoch_incompatible"
      elif dc["violations"] > 0: eff, rsn = "violated", "migration.data_invariant_violated"
      elif osaf["lock_budget_ms"] > 0 and osaf["duration_budget_ms"] > 0 and (osaf["max_lock_ms"] > osaf["lock_budget_ms"] or osaf["duration_ms"] > osaf["duration_budget_ms"]): eff, rsn = "violated", "migration.lock_budget_exceeded"
      elif not ec["active_epochs"] or not set(ec["active_epochs"]).issubset(set(ec["compatible_epochs"])): eff, rsn = ("inconclusive" if eff == "passed" else eff), "migration.epoch_incomplete"
      elif not inv_keys.issubset(set(dc["invariants_checked"])) or (rec["phase"] == "backfill" and dc["rows_verified"] <= 0): eff, rsn = ("inconclusive" if eff == "passed" else eff), "migration.invariants_incomplete"
      elif not osaf["lock_mode"] or osaf["lock_budget_ms"] <= 0 or osaf["duration_budget_ms"] <= 0 or not SHA256_REF_RE.match(osaf["context_ref"]): eff, rsn = ("inconclusive" if eff == "passed" else eff), "migration.operational_unmeasured"
      elif eff == "violated" and not rsn: rsn = "migration.violated"
      if eff == "violated": grp_viol = True
      grp_evals.append((rec, eff, rsn))
    for rec, eff0, rsn0 in grp_evals:
      eff, rsn = eff0, rsn0
      if has_conflict:
        if grp_viol: eff, rsn = "violated", (rsn0 if (rsn0 and rsn0 != "migration.violated") else "migration.conflicting_receipts")
        else: eff, rsn = "inconclusive", "migration.conflicting_receipts"
      item = {**rec, "effective_outcome": eff, "provenance": "measured", **({"reason": rsn} if rsn else {})}
      eval_list.append(item)
      if eff == "violated":
        has_viol = True
        if rsn and rsn not in reasons: reasons.append(rsn)
        if has_conflict and "migration.conflicting_receipts" not in reasons: reasons.append("migration.conflicting_receipts")
      elif eff != "passed":
        has_inc = True
        if rsn and rsn not in reasons: reasons.append(rsn)
  if has_viol and "migration.violated" not in reasons: reasons.append("migration.violated")
  if has_inc and not has_viol and "migration.inconclusive" not in reasons:
    reasons.append("migration.inconclusive")
  return reasons, eval_list
from drift_verify_sim import evaluate_contract_composition_core, load_composition_manifests_core
def run_mig_parity_self_test(ck: dict[str, Any], digest_matches_fn: Any) -> None:
  from drift_verify_ssh import evaluate_contract_parity_impl
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
def verify_ssh_sig_envelope_impl(payload: dict[str, Any], sig_text: str, trust_root: Path | None, verify_time: str, canonical_json_fn: Any) -> tuple[bool, str]:
  import os, subprocess, tempfile
  from drift_verify_ssh import _has_temporal_bounds, _valid_verify_time
  norm_root = trust_root.as_posix() if trust_root is not None else ""
  if trust_root is None or not trust_root.is_file() or trust_root.name == "config.toml" or norm_root.startswith(".drift/") or "/.drift/" in norm_root:
    return False, "trust.root_required"
  has_temp, invalid_temp = _has_temporal_bounds(trust_root.read_text("utf-8"))
  if invalid_temp or (has_temp and not verify_time):
    return False, "trust.verify_time_required"
  v_opt = _valid_verify_time(verify_time) if verify_time else ""
  if verify_time and not v_opt:
    return False, "trust.verify_time_required"
  payload_bytes = canonical_json_fn(payload).encode("utf-8")
  with tempfile.NamedTemporaryFile("w", suffix=".sig", encoding="utf-8", delete=False) as tf:
    tf.write(sig_text if sig_text.endswith("\n") else sig_text + "\n")
    tmp_sig = tf.name
  try:
    keygen = os.environ.get("DRIFT_SSH_KEYGEN", "ssh-keygen")
    if subprocess.run([keygen, "-Y", "check-novalidate", "-q", "-n", "drift-signature@v1", "-s", tmp_sig], input=payload_bytes, capture_output=True).returncode != 0:
      return False, "signature.invalid"
    v_args = [keygen, "-Y", "verify", "-q", "-f", str(trust_root), "-I", str(payload["signer"]), "-n", "drift-signature@v1", "-s", tmp_sig, *(["-O", f"verify-time={v_opt}"] if v_opt else [])]
    return (True, "") if subprocess.run(v_args, input=payload_bytes, capture_output=True).returncode == 0 else (False, "signature.invalid")
  finally:
    try: os.remove(tmp_sig)
    except OSError: pass
def run_ra_self_test_impl(ck: dict[str, Any], digest_matches_fn: Any) -> None:
  from drift_verify_ra import VC_KEYS, evaluate_contract_controls_core, evaluate_contract_evaluations_core, evaluate_contract_studies_core
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
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DIGEST_RE = re.compile(r"^(?:dr1|dr2b):(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})$")
THEN_MUT_OPS = frozenset(("negate", "add-one", "minus-one", "set-one", "multiply-two", "divide-two", "append-tilde", "drop-last", "seed-array", "swap-peer-then", "zero-sum-shear", "drop-forbid-key", "pick-forbidden-value", "break-monotonicity", "skew-sum-total", "exceed-step-delta", "shift-approx-target", "flip-balance-sign"))
WHEN_MUT_OPS = frozenset(("swap-case-when", "perturb-case-when"))
def validate_mutation_manifest_core(text: str, decode_fn: Any) -> dict[str, Any]:
  import hashlib
  doc = decode_fn(text)
  if not isinstance(doc, dict) or set(doc) != {"version", "contracts"} or doc.get("version") != 1 or isinstance(doc.get("version"), bool) or not isinstance(cs := doc["contracts"], list) or not cs: raise ValueError("manifest")
  by_id, targets, prev_c = {}, {}, ""
  for c in cs:
    if not isinstance(c, dict) or set(c) != {"id", "digest", "mutants"}: raise ValueError("contract")
    cid, cdig, muts = c["id"], c["digest"], c["mutants"]
    if not isinstance(cid, str) or not ID_RE.match(cid) or not isinstance(cdig, str) or not DIGEST_RE.match(cdig) or not isinstance(muts, list) or (prev_c and cid <= prev_c): raise ValueError("contract")
    prev_c, prev_m, m_list = cid, "", []
    for m in muts:
      if not isinstance(m, dict) or any(k not in ("id", "case", "path", "operator", "before", "after", "witness") for k in m) or any(r not in m for r in ("id", "case", "path", "operator", "before", "after")): raise ValueError("mutant")
      mid, mc, mp, mop = m["id"], m["case"], m["path"], m["operator"]
      if not all(isinstance(x, str) for x in (mid, mc, mp, mop)) or not ID_RE.match(mc) or mid != f"{mc}:{mp}" or (prev_m and mid <= prev_m): raise ValueError("mutant")
      esc = mc.replace("~", "~0").replace("/", "~1")
      tp, wp = f"/cases/{esc}/then/", f"/cases/{esc}/when/"
      if not ((mp.startswith(tp) and len(mp) > len(tp) and mop in THEN_MUT_OPS) or (mp.startswith(wp) and len(mp) > len(wp) and mop in WHEN_MUT_OPS)): raise ValueError("mutant")
      prev_m = mid; targets[(cid, mid)] = rec = {"id": mid, "contract": cid, "digest": cdig, "case": mc, "path": mp}; m_list.append(rec)
    by_id[cid] = {"id": cid, "digest": cdig, "mutants": m_list}
  return {"digest": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(), "contracts": by_id, "targets": targets}
def run_sec_self_test_core(ck: dict[str, Any], digest_matches_fn: Any, eval_sec_fn: Any) -> None:
  import tempfile, drift_verify as _dv
  run_mig_parity_self_test(ck, digest_matches_fn)
  sec_ck = {**ck, "profile_security": ["sast"], "scope_code": ["src/api.rs#authorize"]}
  b_rec = {"category": "sast", "tool": "semgrep", "tool_ref": "sha256:" + "1" * 64, "ruleset_ref": "sha256:" + "2" * 64, "contract": "svc", "digest": ck["ref"], "code_snapshot": "a" * 40, "covered_scope": ["src/api.rs#authorize"], "cases": ["ok"], "outcome": "passed"}
  assert eval_sec_fn(sec_ck, [b_rec], {}, "a" * 40, digest_matches_fn)[0] == []
  for bad in ({"covered_scope": ["src/api.rs#unrelated"]}, {"cases": ["nonexistent"]}): assert "security.inconclusive" in eval_sec_fn(sec_ck, [{**b_rec, **bad}], {}, "a" * 40, digest_matches_fn)[0]
  assert "security.inconclusive" in eval_sec_fn(sec_ck, [b_rec], {}, "", digest_matches_fn)[0]
  r_viol = {**b_rec, "ruleset_ref": "sha256:" + "3" * 64, "outcome": "violated"}
  c1, c2 = eval_sec_fn(sec_ck, [r_viol, b_rec], {}, "a" * 40, digest_matches_fn), eval_sec_fn(sec_ck, [b_rec, r_viol], {}, "a" * 40, digest_matches_fn)
  assert c1 == c2 and "security.violated" in c1[0] and all(x.get("reason") == "security.conflicting_receipts" for x in c1[1])
  with tempfile.TemporaryDirectory() as td:
    tp = Path(td)
    (tp / "p@1.toml").write_text('drift = "0.2"\nprofile = "p@1"\n[vocabulary]\nwhen = ["op"]\nthen = ["status", "inv_p"]\n[projections.then]\nstatus = "/status"\ninv_p = "/ip"\n[concepts."orders.c"]\nmeans = "Cancel order."\n', "utf-8")
    for fn_n, u_c in (("c1.toml", 'concepts = ["orders.c"]\n'), ("c2.toml", "")):
      (tp / fn_n).write_text(f'drift = "0.2"\nid = "c"\nintent = "C."\n[use]\nprofile = "p@1"\n{u_c}[scope]\nwrites = []\nreads = []\nindirect = "none"\n[invariants]\ninv_p = 1\n[cases.ok]\nwhen.op = "x"\nthen.status = 200\n', "utf-8")
    assert _dv.verify_contract_toml(tp / "c1.toml", tp)["digest"] == _dv.verify_contract_toml(tp / "c2.toml", tp)["digest"]
  from drift_verify_ssh import run_03_self_test; run_03_self_test(_dv)
def parse_security_lock_core(text: str, decode_fn: Any, canon_fn: Any, sec_str_fn: Any, sec_cats: Any) -> dict[str, Any]:
  import hashlib
  doc = decode_fn(text)
  if not isinstance(doc, dict) or any(k not in ("schema", "lock_ref", "tools") for k in doc) or doc.get("schema") != "drift.security-lock/1" or not isinstance(raw_tools := doc.get("tools"), dict) or not raw_tools: raise ValueError("security_lock")
  tools: dict[str, dict[str, str]] = {}
  for tkey, tval in raw_tools.items():
    if not isinstance(tkey, str) or ":" not in tkey or not isinstance(tval, dict) or set(tval) != {"tool_ref", "ruleset_ref"}: raise ValueError("security_lock_entry")
    cat, tool = tkey.split(":", 1)
    tref, rref = sec_str_fn(tval, "tool_ref"), sec_str_fn(tval, "ruleset_ref")
    if cat not in sec_cats or not tool.strip() or tool.strip() != tool or not SHA256_REF_RE.match(tref) or not SHA256_REF_RE.match(rref): raise ValueError("security_lock_fields")
    tools[tkey] = {"ruleset_ref": rref, "tool_ref": tref}
  comp_ref = "sha256:" + hashlib.sha256(canon_fn({"schema": "drift.security-lock/1", "tools": tools}).encode("utf-8")).hexdigest()
  if "lock_ref" in doc and sec_str_fn(doc, "lock_ref") != comp_ref: raise ValueError("lock_ref_mismatch")
  return {"active": True, "lock_ref": comp_ref, "tools": tools}
def classify_sec_reproducer_core(repro: Any, raw_cases: dict[str, Any], active_cases: set[str]) -> str:
  if repro is None: return ""
  if not isinstance(repro, dict) or not isinstance(wit := repro.get("witness"), dict): return "unreproducible"
  wm, tm = wit.get("when"), wit.get("then")
  if not isinstance(wm, dict) or not wm or not isinstance(tm, dict) or not tm: return "unreproducible"
  cid = repro.get("case", "")
  if not isinstance(cid, str) or cid not in active_cases or not (cw := (raw_cases.get(cid) or {}).get("when") or {}): return "draft_case_required"
  for wk, wv in cw.items():
    if wk not in wm: return "draft_case_required"
    av = wm[wk]
    if isinstance(wv, dict):
      if ("eq" in wv and av != wv["eq"]) or ("in" in wv and av not in wv["in"]) or ("not_in" in wv and av in wv["not_in"]) or ("min" in wv and (not isinstance(av, int) or isinstance(av, bool) or av < wv["min"])) or ("max" in wv and (not isinstance(av, int) or isinstance(av, bool) or av > wv["max"])):
        return "draft_case_required"
    elif av != wv: return "draft_case_required"
  return "bound_cex"
def check_sec_stage1_core(rec: dict[str, Any], expected_snapshot: str, exp_sub: dict[str, Any]) -> tuple[bool, str]:
  if not expected_snapshot or rec["code_snapshot"] != expected_snapshot: return False, "security.snapshot_mismatch"
  esr, ear = exp_sub.get("subject_ref", ""), exp_sub.get("binary_ref", "")
  if esr and rec.get("subject_ref") and rec["subject_ref"] != esr: return False, "security.subject_mismatch"
  if exp_sub.get("artifact_mismatch") or (ear and rec.get("artifact_ref") and rec["artifact_ref"] != ear): return False, "security.artifact_mismatch"
  slock = exp_sub.get("security_lock") or {}
  if slock.get("active"):
    pin = (slock.get("tools") or {}).get(f"{rec['category']}:{rec['tool']}")
    if not pin or rec["tool_ref"] != pin["tool_ref"]: return False, "security.tool_unpinned"
    if rec["ruleset_ref"] != pin["ruleset_ref"]: return False, "security.ruleset_stale"
  return True, ""
def resolve_verifier_subject_cli(args: Any, decode_fn: Any, canon_fn: Any, parse_sub_fn: Any, parse_lock_fn: Any) -> tuple[dict[str, Any], Any]:
  import hashlib
  sec_lock = parse_lock_fn(args.security_lock.read_text("utf-8"), decode_fn, canon_fn) if getattr(args, "security_lock", None) else {}
  bin_ref, sub_ref, man_srcs, has_man, art_mismatch = "", "", None, False, False
  if args.subject_artifact:
    bin_ref = args.subject_artifact if args.subject_artifact.startswith("sha256:") else ("sha256:" + hashlib.sha256(Path(args.subject_artifact).read_bytes()).hexdigest())
  if args.subject:
    st = args.subject.read_text("utf-8", errors="ignore")
    if '"drift.subject-manifest/1"' in st:
      sm = parse_sub_fn(st, decode_fn, canon_fn)
      has_man, sub_ref, man_srcs, man_art = True, sm["subject_ref"], sm["sources"], sm.get("artifact_ref", "")
      if man_art and bin_ref and man_art != bin_ref: art_mismatch = True
      if not bin_ref and man_art: bin_ref = man_art
    else:
      bin_ref = "sha256:" + hashlib.sha256(args.subject.read_bytes()).hexdigest()
  return {"subject_ref": sub_ref, "artifact_ref": sub_ref or bin_ref, "binary_ref": bin_ref, "has_manifest": has_man, "artifact_mismatch": art_mismatch, "source_tree": args.subject_tree, "run_id": args.run_id, "security_lock": sec_lock}, man_srcs
def verify_tool_pin_cli_core(argv: list[str], parse_lock_fn: Any) -> int:
  import argparse, hashlib, json
  ap = argparse.ArgumentParser(prog="drift_verify_sec.py")
  ap.add_argument("--verify-tool", required=True); ap.add_argument("--tool-bin", type=Path, required=True); ap.add_argument("--security-lock", type=Path, required=True)
  args = ap.parse_args(argv)
  try:
    from drift_verify import _decode_no_dup_keys, canonical_json
    lock = parse_lock_fn(args.security_lock.read_text("utf-8"), _decode_no_dup_keys, canonical_json)
    if not args.tool_bin.is_file(): raise ValueError("missing_tool_bin")
    actual_ref = "sha256:" + hashlib.sha256(args.tool_bin.read_bytes()).hexdigest()
  except Exception as exc:
    print(json.dumps({"ok": False, "reason": "security.tool_unpinned", "error": str(exc)}, sort_keys=True)); return 2
  pin = (lock.get("tools") or {}).get(args.verify_tool)
  if not pin or pin.get("tool_ref") != actual_ref:
    print(json.dumps({"ok": False, "reason": "security.tool_unpinned", "tool": args.verify_tool, "actual_ref": actual_ref, "expected_ref": (pin or {}).get("tool_ref", ""), "lock_ref": lock["lock_ref"]}, sort_keys=True)); return 1
  print(json.dumps({"ok": True, "tool": args.verify_tool, "tool_ref": actual_ref, "ruleset_ref": pin["ruleset_ref"], "lock_ref": lock["lock_ref"]}, sort_keys=True))
  return 0
def eval_sim_opt_blocks(rec: dict[str, Any], eff: str) -> tuple[str, str]:
 import math
 if isinstance(ts := rec.get("trajectory_stability"), dict):
  if ts["non_finite_count"] > 0: return "violated", "sim.non_finite_state"
  if ts.get("forbid_subnormals") and ts["subnormal_count"] > 0: return "violated", "sim.subnormal_state"
  if ts["max_abs_drift"] > ts["max_allowed_drift"] + 1e-12: return "violated", "sim.drift_exceeded"
 if isinstance(oc := rec.get("observed_convergence"), dict):
  gs, es, rf, mo, vp = oc["grid_steps"], oc["errors"], oc["roundoff_floor"], oc["min_expected_order"], 0
  for i in range(len(gs) - 1):
   if es[i] <= rf or es[i + 1] <= rf: continue
   vp += 1
   if es[i + 1] >= es[i] or (math.log(es[i] / es[i + 1]) / math.log(gs[i] / gs[i + 1])) + 1e-9 < mo: return "violated", "sim.convergence_degraded"
  if vp == 0: return ("inconclusive" if eff == "passed" else eff), "sim.roundoff_masked"
 return eff, ""
