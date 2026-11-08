#!/usr/bin/env python3
"""DRIFT Independent Reference Performance Evidence Verifier (MIT License)."""

from __future__ import annotations
import hashlib, math, re
from pathlib import Path
from typing import Any, Callable

MAX_MEASUREMENT_BYTES = 4 * 1024 * 1024
ARTIFACT_REF_RE = re.compile(r"^(?:sha256:[0-9a-f]{64}|dr1:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12}))$")
SNAPSHOT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CONF_METHODS = frozenset(("bootstrap_bca", "student_t", "wilcoxon", "binomial_exact", "direct_observed"))
BUDGET_METRICS = frozenset(("request_latency", "successful_throughput", "process_rss", "frame_time", "cold_start", "artifact_bytes", "work_units"))
BUDGET_AGGS = frozenset(("p99", "rate", "max_observed"))

def extract_contract_budgets(
 raw: dict[str, Any],
 use_tbl: dict[str, Any] | None,
 dr1_digest_fn: Callable[[Any], str],
) -> tuple[dict[str, dict[str, Any]], bool]:
 raw_b = raw.get("budgets")
 if not isinstance(raw_b, dict) or not raw_b:
  return {}, False
 params = (
  {
   k: v
   for k, v in use_tbl.items()
   if k not in ("profile", "waive", "vocabulary", "concepts")
  }
  if isinstance(use_tbl, dict)
  else {}
 )
 digest_budgets: dict[str, Any] = {}
 resolved_budgets: dict[str, dict[str, Any]] = {}
 for bid, bval in raw_b.items():
  if not isinstance(bval, dict):
   continue
  trimmed = {k: v for k, v in bval.items() if k not in ("note", "warn_ratio", "requirement_ref")}
  digest_budgets[bid] = trimmed
  sub_b = {}
  for k, v in trimmed.items():
   if isinstance(v, str) and "${" in v and params:
    s = v
    for pk, pv in params.items():
     if s == f"${{{pk}}}":
      s = pv
      break
     s = s.replace(f"${{{pk}}}", str(pv))
    sub_b[k] = s
   else:
    sub_b[k] = v
  req_ref = dr1_digest_fn(sub_b)
  res_entry = dict(sub_b)
  if "warn_ratio" in bval:
   res_entry["warn_ratio"] = bval["warn_ratio"]
  res_entry["requirement_ref"] = req_ref
  resolved_budgets[bid] = res_entry
 raw["budgets"] = digest_budgets
 return resolved_budgets, bool(resolved_budgets)
def _perf_str(m: dict[str, Any], k: str) -> str:
 v = m.get(k)
 if not isinstance(v, str) or not v.strip() or v.strip() != v:
  raise ValueError(k)
 return v
def _perf_int(m: dict[str, Any], k: str, lo: int = 0) -> int:
 v = m.get(k)
 if isinstance(v, bool) or not isinstance(v, int) or v < lo or v > (1 << 53) - 1:
  raise ValueError(k)
 return v
def _perf_num(m: dict[str, Any], k: str) -> float:
 v = m.get(k)
 if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
  raise ValueError(k)
 return float(v)
def _perf_scalar(v: Any) -> str:
 if isinstance(v, bool):
  return "true" if v else "false"
 if isinstance(v, int):
  if not (-((1 << 53) - 1) <= v <= (1 << 53) - 1):
   raise ValueError("int")
  return str(v)
 if isinstance(v, str) and v.strip():
  return v
 raise ValueError("env")
def _parse_env_map(raw: Any) -> dict[str, str]:
 if not isinstance(raw, dict):
  raise ValueError("env")
 return {k: _perf_scalar(v) for k, v in raw.items() if isinstance(k, str) and k.strip()}
def _parse_subject(m: dict[str, Any]) -> tuple[str, str]:
 sub = m.get("subject")
 if not isinstance(sub, dict) or set(sub) != {"artifact_ref", "source_tree"}:
  raise ValueError("subject")
 art, tree = _perf_str(sub, "artifact_ref"), _perf_str(sub, "source_tree")
 if not ARTIFACT_REF_RE.match(art) or not SNAPSHOT_RE.match(tree):
  raise ValueError("subject")
 return art, tree
def _parse_interval(raw: Any) -> dict[str, float]:
 if not isinstance(raw, dict) or set(raw) != {"lower", "upper", "confidence"}:
  raise ValueError("interval")
 lo, hi, conf = _perf_num(raw, "lower"), _perf_num(raw, "upper"), _perf_num(raw, "confidence")
 if lo > hi or not (0.0 < conf < 1.0):
  raise ValueError("interval")
 return {"lower": lo, "upper": hi, "confidence": conf}
def _parse_protocol(doc: dict[str, Any]) -> dict[str, Any]:
 allowed = {"schema", "workload_ref", "sampling_unit", "warmup_runs", "min_runs", "min_samples", "aggregation", "error_policy", "confidence_method", "environment_keys", "adapter_ref"}
 if set(doc) != allowed or doc.get("schema") != "drift.performance-protocol/1":
  raise ValueError("protocol")
 w_ref, a_ref = _perf_str(doc, "workload_ref"), _perf_str(doc, "adapter_ref")
 s_unit, agg = _perf_str(doc, "sampling_unit"), _perf_str(doc, "aggregation")
 ep, cm = _perf_str(doc, "error_policy"), _perf_str(doc, "confidence_method")
 if (not ARTIFACT_REF_RE.match(w_ref) or not ARTIFACT_REF_RE.match(a_ref) or s_unit not in ("request", "batch", "process", "frame", "artifact") or agg not in BUDGET_AGGS or ep != "fail_run" or cm not in CONF_METHODS):
  raise ValueError("protocol")
 eks = doc.get("environment_keys")
 if (not isinstance(eks, list) or not eks or len(set(eks)) != len(eks) or not all(isinstance(x, str) and x.strip() for x in eks)):
  raise ValueError("environment_keys")
 return {"workload_ref": w_ref, "sampling_unit": s_unit, "warmup_runs": _perf_int(doc, "warmup_runs", 0), "min_runs": _perf_int(doc, "min_runs", 1), "min_samples": _perf_int(doc, "min_samples", 1), "aggregation": agg, "error_policy": ep, "confidence_method": cm, "environment_keys": eks, "adapter_ref": a_ref}
def _parse_receipt(doc: dict[str, Any]) -> dict[str, Any]:
 allowed = {"schema", "run_id", "run_status", "contract", "contract_ref", "subject", "workload_ref", "protocol_ref", "environment_ref", "environment_observed", "adapter_ref", "results", "raw_artifacts"}
 if any(k not in allowed for k in doc) or doc.get("schema") != "drift.performance-receipt/1":
  raise ValueError("receipt")
 run_id, status = _perf_str(doc, "run_id"), _perf_str(doc, "run_status")
 cid, c_ref = _perf_str(doc, "contract"), _perf_str(doc, "contract_ref")
 if status not in ("passed", "failed", "incomplete") or not ID_RE.match(cid) or not ARTIFACT_REF_RE.match(c_ref):
  raise ValueError("receipt")
 sub_art, sub_tree = _parse_subject(doc)
 w_ref, p_ref = _perf_str(doc, "workload_ref"), _perf_str(doc, "protocol_ref")
 e_ref, a_ref = _perf_str(doc, "environment_ref"), _perf_str(doc, "adapter_ref")
 if not all(ARTIFACT_REF_RE.match(x) for x in (w_ref, p_ref, e_ref, a_ref)):
  raise ValueError("receipt_refs")
 env_obs = _parse_env_map(doc.get("environment_observed"))
 res_raw = doc.get("results")
 if not isinstance(res_raw, list) or not res_raw:
  raise ValueError("results")
 seen_b: set[str] = set()
 results = []
 for rm in res_raw:
  if not isinstance(rm, dict) or any(
   k not in {"budget", "case", "requirement_ref", "metric", "unit", "aggregation", "evidence", "estimate", "interval", "sample_count", "run_count", "failed_requests", "comparison"}
   for k in rm
  ):
   raise ValueError("result")
  bid, case_id, req_ref = _perf_str(rm, "budget"), _perf_str(rm, "case"), _perf_str(rm, "requirement_ref")
  if not ID_RE.match(bid) or not ID_RE.match(case_id) or not ARTIFACT_REF_RE.match(req_ref) or bid in seen_b:
   raise ValueError("result_id")
  seen_b.add(bid)
  metric, unit = _perf_str(rm, "metric"), _perf_str(rm, "unit")
  agg, ev = _perf_str(rm, "aggregation"), _perf_str(rm, "evidence")
  est = _perf_num(rm, "estimate")
  if est < 0.0:
   raise ValueError("estimate")
  sc, rc = _perf_int(rm, "sample_count", 0), _perf_int(rm, "run_count", 0)
  fr = _perf_int(rm, "failed_requests", 0) if "failed_requests" in rm else 0
  iv = None
  if "interval" in rm:
   if ev == "observed":
    raise ValueError("observed_interval")
   iv = _parse_interval(rm["interval"])
   if not (iv["lower"] <= est <= iv["upper"]):
    raise ValueError("est_interval")
  elif ev == "statistical":
   raise ValueError("missing_interval")
  comp = None
  if "comparison" in rm:
   cm = rm["comparison"]
   if not isinstance(cm, dict) or any(k not in {"baseline_ref", "regression", "interval"} for k in cm):
    raise ValueError("comparison")
   b_ref, reg = _perf_str(cm, "baseline_ref"), _perf_num(cm, "regression")
   if not ARTIFACT_REF_RE.match(b_ref):
    raise ValueError("baseline_ref")
   c_iv = None
   if "interval" in cm:
    if ev == "observed":
     raise ValueError("observed_comp_interval")
    c_iv = _parse_interval(cm["interval"])
    if not (c_iv["lower"] <= reg <= c_iv["upper"]):
     raise ValueError("reg_interval")
   elif ev == "statistical":
    raise ValueError("missing_comp_interval")
   comp = {"baseline_ref": b_ref, "regression": reg, "interval": c_iv}
  results.append({"contract": cid, "contract_ref": c_ref, "run_id": run_id, "run_status": status, "subject_artifact": sub_art, "subject_tree": sub_tree, "workload_ref": w_ref, "protocol_ref": p_ref, "environment_ref": e_ref, "environment_obs": env_obs, "adapter_ref": a_ref, "budget": bid, "case": case_id, "requirement_ref": req_ref, "metric": metric, "unit": unit, "aggregation": agg, "evidence": ev, "estimate": est, "sample_count": sc, "run_count": rc, "failed_requests": fr, "interval": iv, "comparison": comp})
 return {"run_id": run_id, "run_status": status, "contract": cid, "contract_ref": c_ref, "subject_artifact": sub_art, "subject_tree": sub_tree, "workload_ref": w_ref, "protocol_ref": p_ref, "environment_ref": e_ref, "environment_obs": env_obs, "adapter_ref": a_ref, "results": results}
def _read_confined_file(bundle_dir: Path, real_root: Path, rel_path: str) -> tuple[str, str, str]:
 if not rel_path or rel_path.startswith("/") or "\\" in rel_path or ":" in rel_path or "\x00" in rel_path:
  raise ValueError("path")
 segs = rel_path.split("/")
 if any(s in ("", ".", "..") for s in segs):
  raise ValueError("path")
 cur = bundle_dir
 for s in segs:
  cur = cur / s
  if cur.is_symlink():
   raise ValueError("symlink")
 if not cur.is_file():
  raise ValueError("missing")
 resolved = cur.resolve()
 if real_root not in resolved.parents:
  raise ValueError("escape")
 raw_bytes = resolved.read_bytes()
 if len(raw_bytes) > MAX_MEASUREMENT_BYTES:
  raise ValueError("size")
 text = raw_bytes.decode("utf-8")
 h = hashlib.sha256(raw_bytes).hexdigest()
 return text, f"sha256:{h}", f"dr1:sha256:{h}"
def load_measurement_bundle(
 manifest_path: Path | None,
 decode_fn: Callable[[str], Any],
 digest_matches_fn: Callable[[str, str], bool],
) -> dict[str, Any]:
 if manifest_path is None:
  return {"active": False, "invalid": False}
 try:
  if manifest_path.is_symlink() or not manifest_path.is_file():
   raise ValueError("manifest_file")
  raw_bytes = manifest_path.read_bytes()
  if len(raw_bytes) > MAX_MEASUREMENT_BYTES:
   raise ValueError("manifest_size")
  m_doc = decode_fn(raw_bytes.decode("utf-8"))
  if not isinstance(m_doc, dict) or any(
   k not in {"schema", "run_id", "subject", "expected_budgets", "objects", "receipts"}
   for k in m_doc
  ):
   raise ValueError("manifest_keys")
  if _perf_str(m_doc, "schema") != "drift.performance-run/1":
   raise ValueError("manifest_schema")
  run_id = _perf_str(m_doc, "run_id")
  sub_art, sub_tree = _parse_subject(m_doc)
  eb_raw = m_doc.get("expected_budgets")
  if not isinstance(eb_raw, list):
   raise ValueError("expected_budgets")
  exp_b: dict[tuple[str, str], str] = {}
  prev_cb = ("", "")
  for em in eb_raw:
   if not isinstance(em, dict) or set(em) != {"contract", "budget", "requirement_ref"}:
    raise ValueError("eb_entry")
   cid, bid, rref = _perf_str(em, "contract"), _perf_str(em, "budget"), _perf_str(em, "requirement_ref")
   if not ID_RE.match(cid) or not ID_RE.match(bid) or not ARTIFACT_REF_RE.match(rref):
    raise ValueError("eb_id")
   cb = (cid, bid)
   if cb in exp_b or (prev_cb != ("", "") and cb <= prev_cb):
    raise ValueError("eb_dup")
   prev_cb = cb
   exp_b[cb] = rref
  bundle_dir = manifest_path.parent
  real_root = bundle_dir.resolve()
  objs_raw = m_doc.get("objects", {})
  recs_raw = m_doc.get("receipts")
  if not isinstance(objs_raw, dict) or not isinstance(recs_raw, list) or len(objs_raw) + len(recs_raw) > 1024:
   raise ValueError("objects_receipts")
  protocols, environments, baselines = {}, {}, {}
  for ref_k, rel_p in objs_raw.items():
   if not isinstance(ref_k, str) or not ARTIFACT_REF_RE.match(ref_k) or not isinstance(rel_p, str):
    raise ValueError("obj_ref")
   txt, s_dig, d_dig = _read_confined_file(bundle_dir, real_root, rel_p)
   if ref_k != s_dig and ref_k != d_dig and not digest_matches_fn(ref_k, d_dig):
    raise ValueError("obj_digest")
   odoc = decode_fn(txt)
   if not isinstance(odoc, dict):
    raise ValueError("obj_json")
   sch = _perf_str(odoc, "schema")
   if sch == "drift.performance-protocol/1":
    protocols[ref_k] = _parse_protocol(odoc)
   elif sch == "drift.performance-environment/1":
    if set(odoc) != {"schema", "attributes"}:
     raise ValueError("env_schema")
    environments[ref_k] = _parse_env_map(odoc["attributes"])
   elif sch == "drift.performance-receipt/1":
    baselines[ref_k] = _parse_receipt(odoc)
  seen_p, seen_d, res_by_cb = set(), set(), {}
  for rm in recs_raw:
   if not isinstance(rm, dict) or set(rm) != {"path", "digest"}:
    raise ValueError("rec_entry")
   rp, rd = _perf_str(rm, "path"), _perf_str(rm, "digest")
   if rp in seen_p or rd in seen_d or not ARTIFACT_REF_RE.match(rd):
    raise ValueError("rec_dup")
   seen_p.add(rp)
   seen_d.add(rd)
   rtxt, s_dig, _ = _read_confined_file(bundle_dir, real_root, rp)
   if rd != s_dig:
    raise ValueError("rec_digest")
   rec = _parse_receipt(decode_fn(rtxt))
   if rec["run_id"] != run_id or rec["subject_artifact"] != sub_art or rec["subject_tree"] != sub_tree:
    raise ValueError("rec_subject")
   for r_item in rec["results"]:
    cb = (r_item["contract"], r_item["budget"])
    if cb in res_by_cb:
     raise ValueError("dup_cb_result")
    res_by_cb[cb] = r_item
  return {"active": True, "invalid": False, "run_id": run_id, "subject_artifact": sub_art, "subject_tree": sub_tree, "expected_budgets": exp_b, "protocols": protocols, "environments": environments, "baselines": baselines, "results_by_cb": res_by_cb}
 except Exception as exc:
  return {"active": True, "invalid": True, "error": str(exc)}
def _env_ok(keys: list[str], d_map: dict[str, str], o_map: dict[str, str]) -> bool:
 return bool(keys) and all(bool(d_map.get(k, "").strip()) and d_map.get(k) == o_map.get(k) for k in keys)
def _eval_one_budget(
 bid: str,
 bm: dict[str, Any],
 cid: str,
 c_dig: str,
 bundle: dict[str, Any],
 exp_sub: dict[str, str],
 digest_matches_fn: Callable[[str, str], bool],
) -> dict[str, Any]:
 case_id, metric = str(bm.get("case", "")), str(bm.get("metric", ""))
 unit, agg = str(bm.get("unit", "")), str(bm.get("aggregation", ""))
 op, ev = str(bm.get("op", "le")), str(bm.get("evidence", ""))
 enf, req_ref = str(bm.get("enforce", "release")), str(bm.get("requirement_ref", ""))
 w_ref, p_ref = str(bm.get("workload_ref", "")), str(bm.get("protocol_ref", ""))
 e_ref, b_ref = str(bm.get("environment_ref", "")), str(bm.get("baseline_ref", ""))
 lim = float(bm.get("limit", 0.0))
 min_conf = float(bm.get("min_confidence", 0.0))
 max_reg = float(bm.get("max_regression", 0.0))
 out: dict[str, Any] = {"aggregation": agg, "budget": bid, "case": case_id, "enforce": enf, "evidence": ev, "metric": metric, "requirement_ref": req_ref, "unit": unit}
 def done(st: str, rsn: str = "") -> dict[str, Any]:
  out["state"] = st
  if rsn:
   out["reason"] = rsn
  return out
 if bundle.get("invalid"):
  return done("invalid", "measurements.invalid")
 cb = (cid, bid)
 exp_req = bundle["expected_budgets"].get(cb)
 if exp_req is None:
  return done("missing", "performance.inventory_mismatch")
 if not digest_matches_fn(exp_req, req_ref):
  return done("stale", "performance.subject_changed")
 rec = bundle["results_by_cb"].get(cb)
 if rec is None:
  return done("missing", "performance.evidence_missing")
 if rec["metric"] not in BUDGET_METRICS:
  return done("unsupported", "performance.unsupported")
 if (rec["unit"], rec["metric"], rec["aggregation"], rec["evidence"], rec["case"]) != (unit, metric, agg, ev, case_id):
  return done("invalid", "measurements.invalid")
 proto = bundle["protocols"].get(p_ref)
 if proto is None:
  return done("unsupported", "performance.unsupported")
 if (not digest_matches_fn(rec["contract_ref"], c_dig) or not digest_matches_fn(rec["requirement_ref"], req_ref) or (exp_sub.get("artifact_ref") and bundle["subject_artifact"] != exp_sub["artifact_ref"]) or (exp_sub.get("source_tree") and bundle["subject_tree"] != exp_sub["source_tree"]) or (exp_sub.get("run_id") and bundle["run_id"] != exp_sub["run_id"])):
  return done("stale", "performance.subject_changed")
 if (rec["workload_ref"] != w_ref or rec["protocol_ref"] != p_ref or proto["workload_ref"] != w_ref or proto["aggregation"] != agg or rec["adapter_ref"] != proto["adapter_ref"] or rec["environment_ref"] != e_ref):
  return done("stale", "performance.protocol_mismatch")
 env_def = bundle["environments"].get(e_ref)
 if env_def is None or not _env_ok(proto["environment_keys"], env_def, rec["environment_obs"]):
  return done("not_comparable", "performance.environment_mismatch")
 if rec["run_status"] == "incomplete":
  return done("inconclusive", "performance.run_incomplete")
 if rec["run_status"] == "failed" or rec["failed_requests"] > 0:
  return done("violated", "performance.benchmark_failed")
 out["estimate"] = rec["estimate"]
 if (rec["run_count"] < proto["min_runs"] or rec["sample_count"] < proto["min_samples"] or (ev == "statistical" and rec["interval"]["confidence"] < min_conf)):
  return done("inconclusive", "performance.insufficient_evidence")
 if ev == "statistical":
  iv = rec["interval"]
  if op == "le":
   abs_st, abs_r = ("passed", "") if iv["upper"] <= lim else (("violated", "performance.limit_exceeded") if iv["lower"] > lim else ("inconclusive", "performance.insufficient_evidence"))
  else:
   abs_st, abs_r = ("passed", "") if iv["lower"] >= lim else (("violated", "performance.limit_exceeded") if iv["upper"] < lim else ("inconclusive", "performance.insufficient_evidence"))
 else:
  abs_st, abs_r = ("passed", "") if ((op == "le" and rec["estimate"] <= lim) or (op == "ge" and rec["estimate"] >= lim)) else ("violated", "performance.limit_exceeded")
 if not b_ref:
  if rec["comparison"] is not None:
   out.pop("estimate", None)
   return done("invalid", "measurements.invalid")
  return done(abs_st, abs_r)
 comp = rec["comparison"]
 if comp is None or comp["baseline_ref"] != b_ref:
  return done("missing", "performance.baseline_missing")
 base_rec = bundle["baselines"].get(b_ref)
 if (base_rec is None or base_rec["run_status"] != "passed" or base_rec["workload_ref"] != w_ref or base_rec["protocol_ref"] != p_ref or base_rec["adapter_ref"] != rec["adapter_ref"]):
  return done("missing", "performance.baseline_missing")
 if not _env_ok(proto["environment_keys"], env_def, base_rec["environment_obs"]):
  return done("not_comparable", "performance.environment_mismatch")
 b_item = next((br for br in base_rec["results"] if (br["metric"], br["unit"], br["aggregation"], br["evidence"]) == (metric, unit, agg, ev)), None)
 if b_item is None or b_item["failed_requests"] > 0:
  return done("missing", "performance.baseline_missing")
 if b_item["run_count"] < proto["min_runs"] or b_item["sample_count"] < proto["min_samples"]:
  return done("inconclusive", "performance.insufficient_evidence")
 if b_item["estimate"] <= 0.0:
  return done("unsupported", "performance.unsupported")
 r_pt = (rec["estimate"] / b_item["estimate"] - 1.0) if op == "le" else (1.0 - rec["estimate"] / b_item["estimate"])
 if abs(comp["regression"] - r_pt) > 1e-9:
  out.pop("estimate", None)
  return done("invalid", "measurements.invalid")
 out["regression"] = comp["regression"]
 if ev == "statistical":
  civ = comp["interval"]
  if civ["confidence"] < min_conf:
   reg_st, reg_r = "inconclusive", "performance.insufficient_evidence"
  elif civ["upper"] <= max_reg + 1e-9:
   reg_st, reg_r = "passed", ""
  elif civ["lower"] > max_reg + 1e-9:
   reg_st, reg_r = "violated", "performance.regression_exceeded"
  else:
   reg_st, reg_r = "inconclusive", "performance.insufficient_evidence"
 else:
  reg_st, reg_r = ("passed", "") if r_pt <= max_reg + 1e-9 else ("violated", "performance.regression_exceeded")
 if abs_st == "violated":
  return done(abs_st, abs_r)
 if reg_st == "violated":
  return done(reg_st, reg_r)
 return done(abs_st, abs_r) if abs_st != "passed" else done(reg_st, reg_r)
def evaluate_contract_budgets(
 contract: dict[str, Any],
 phase: str = "",
 perf_bundle: dict[str, Any] | None = None,
 expected_subject: dict[str, str] | None = None,
 digest_matches_fn: Callable[[str, str], bool] | None = None,
 policy: dict[str, Any] | None = None,
) -> tuple[list[str], list[str], dict[str, Any] | None]:
 budgets = contract.get("budgets")
 if not isinstance(budgets, dict) or not budgets:
  if perf_bundle and perf_bundle.get("active") and perf_bundle.get("invalid"):
   return ["measurements.invalid"], [], None
  return [], [], None
 reasons, pending, results, all_passed = [], [], [], True
 active_b = bool(perf_bundle and perf_bundle.get("active"))
 exp_sub = expected_subject or {}
 dm_fn = digest_matches_fn or (lambda a, b: a == b)
 pol_wr = float((policy or {}).get("warn_ratio", 0.0)) if (policy or {}).get("pack") == "core@1" else 0.0
 for bid in sorted(budgets):
  bm = budgets[bid]
  enf = str(bm.get("enforce", "release"))
  if not active_b:
   prov = "pending" if (enf == "release" and phase != "release") else "unverified"
   assur = "at_risk" if prov == "pending" else "unverifiable"
   res = {"aggregation": bm.get("aggregation", ""), "assurance": assur, "budget": bid, "case": bm.get("case", ""), "enforce": enf, "evidence": bm.get("evidence", ""), "metric": bm.get("metric", ""), "provenance": prov, "reason": "performance.evidence_missing", "requirement_ref": bm.get("requirement_ref", ""), "state": "missing", "unit": bm.get("unit", "")}
  elif phase == "release" and not exp_sub.get("artifact_ref") and not perf_bundle.get("invalid"):
   res = {"aggregation": bm.get("aggregation", ""), "assurance": "unverifiable", "budget": bid, "case": bm.get("case", ""), "enforce": enf, "evidence": bm.get("evidence", ""), "metric": bm.get("metric", ""), "provenance": "unverified", "reason": "performance.subject_changed", "requirement_ref": bm.get("requirement_ref", ""), "state": "stale", "unit": bm.get("unit", "")}
  else:
   res = _eval_one_budget(bid, bm, contract["id"], contract["digest"], perf_bundle, exp_sub, dm_fn)
   if res["state"] == "passed":
    res["provenance"] = res.get("provenance", "measured")
    res["assurance"] = "at_risk" if res["provenance"] == "reused" else res.get("assurance", "verified")
    b_wr = float(bm.get("warn_ratio", 0.0))
    eff_wr = b_wr if 0.0 < b_wr < 1.0 else (pol_wr if 0.0 < pol_wr < 1.0 else 0.0)
    rec = perf_bundle["results_by_cb"].get((contract["id"], bid)) if perf_bundle else None
    if eff_wr > 0.0 and rec is not None:
     op, lim, m_reg = str(bm.get("op", "le")), float(bm.get("limit", 0.0)), float(bm.get("max_regression", 0.0))
     obs_v = (rec["interval"]["upper"] if op == "le" else rec["interval"]["lower"]) if res["evidence"] == "statistical" and rec.get("interval") else res["estimate"]
     w_tok = "performance.near_limit" if lim > 0.0 and ((op == "le" and obs_v >= eff_wr * lim) or (op == "ge" and obs_v <= lim / eff_wr)) else ""
     if not w_tok and m_reg > 0.0 and "regression" in res:
      obs_r = rec["comparison"]["interval"]["upper"] if res["evidence"] == "statistical" and rec.get("comparison") and rec["comparison"].get("interval") else res["regression"]
      if obs_r >= eff_wr * m_reg: w_tok = "performance.regression_drift"
     if w_tok: res["assurance"], res["warning"] = "at_risk", w_tok
   elif enf == "release" and phase != "release" and res["state"] == "missing":
    res["provenance"], res["assurance"] = "pending", "at_risk"
   else:
    res["provenance"], res["assurance"] = ("measured" if "estimate" in res else "unverified"), "unverifiable"
  results.append(res)
  st, rsn = res["state"], res.get("reason", "")
  if st != "passed":
   all_passed = False
   if enf == "execution" or phase == "release" or st == "invalid":
    if rsn and rsn not in reasons: reasons.append(rsn)
   else: pending.append(bid)
 s_assur = "unverifiable" if any(r.get("assurance") == "unverifiable" for r in results) else ("at_risk" if any(r.get("assurance") == "at_risk" for r in results) else "verified")
 perf_summary: dict[str, Any] = {"assurance": s_assur, "ok": all_passed and not (perf_bundle and perf_bundle.get("invalid")), "results": results}
 if phase:
  perf_summary["phase"] = phase
 if pending:
  perf_summary["pending_budgets"] = pending
 return reasons, pending, perf_summary

MUT_EVENT_KEYS = frozenset(("manifest", "contract", "digest", "mutant", "case", "outcome", "control"))
def _count_then_leaves(val): return sum(_count_then_leaves(v) for v in val.values()) if isinstance(val, dict) else 1
def load_mutation_events_impl(paths, manifest, decode_fn):
 files = [f for p in paths for f in (sorted(p.glob("*.jsonl")) if p.is_dir() else ([p] if p.is_file() else []))]
 latest, errs, tgts = {}, [], manifest["targets"]
 for mf in files:
  for idx, line in enumerate(mf.read_text(encoding="utf-8").splitlines(), 1):
   if not line.strip(): continue
   try:
    ev = decode_fn(line)
    if not isinstance(ev, dict) or set(ev) != MUT_EVENT_KEYS or not all(isinstance(v, str) and v.strip() for v in ev.values()): raise ValueError("mut")
    t = tgts.get((ev["contract"], ev["mutant"]))
    if t is None or ev["manifest"] != manifest["digest"] or ev["digest"] != t["digest"] or ev["case"] != t["case"] or ev["outcome"] not in ("killed", "survived", "inconclusive") or ev["control"] not in ("passed", "failed") or (ev["outcome"] in ("killed", "survived") and ev["control"] != "passed"): raise ValueError("mut")
    latest[(ev["contract"], ev["mutant"])] = ev
   except Exception as exc: errs.append(f"mutation-events:{mf.name}:{idx}: {exc}")
 return latest, errs
def evaluate_contract_mutations_impl(contract, manifest, latest_mut, mut_errors, digest_matches_fn):
 if manifest is None or mut_errors or (mc := manifest["contracts"].get(contract["id"])) is None or not digest_matches_fn(mc["digest"], contract["digest"]): return False
 tc = {}
 for m in mc["mutants"]:
  if "/when/" not in m["path"]: tc[m["case"]] = tc.get(m["case"], 0) + 1
  if (ev := latest_mut.get((contract["id"], m["id"]))) is None or ev["outcome"] != "killed": return False
 return all(tc.get(cid, 0) >= _count_then_leaves(cm.get("then", {})) for cid, cm in contract["cases"].items() if isinstance(cm, dict) and "status" not in cm)

