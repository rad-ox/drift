#!/usr/bin/env python3
"""DRIFT Independent Reference DB Migration Receipt Verifier (MIT License)."""

from __future__ import annotations
from pathlib import Path
from typing import Any
from drift_verify_base import SHA256_REF_RE, SNAPSHOT_RE, check_receipt_scope_snap_subj, collect_receipt_files, reduce_receipt_groups
from drift_verify_parity import evaluate_contract_composition_core, load_composition_manifests_core
from drift_verify_sim import eval_sim_opt_blocks

MIG_KEYS = frozenset(("schema", "contract", "digest", "resource", "migration_id", "phase", "tool", "tool_ref", "subject_ref", "code_snapshot", "epoch_manifest_ref", "covered_scope", "cases", "epoch_compatibility", "data_correctness", "operational_safety", "outcome"))
MIG_PHASES = frozenset(("expand", "backfill", "contract"))


def load_migration_receipts_core(events_paths: list[Path], decode_fn: Any, valid_rel_scope_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
  out, errs = [], []
  for mf in collect_receipt_files(events_paths, ".migration.json"):
    try:
      doc = decode_fn(mf.read_text(encoding="utf-8"))
      if not isinstance(doc, dict) or set(doc) != MIG_KEYS or doc.get("schema") != "drift.migration-receipt/1": raise ValueError("mig_keys")
      cid, dig, res = str(doc.get("contract", "")), str(doc.get("digest", "")), str(doc.get("resource", ""))
      mid, ph, tool = str(doc.get("migration_id", "")), str(doc.get("phase", "")), str(doc.get("tool", ""))
      tref, sref, csnap, emref, outc = str(doc.get("tool_ref", "")), str(doc.get("subject_ref", "")), str(doc.get("code_snapshot", "")), str(doc.get("epoch_manifest_ref", "")), str(doc.get("outcome", ""))
      if not cid or not dig or not res.strip() or not mid.strip() or ph not in MIG_PHASES or not tool.strip() or not SHA256_REF_RE.match(tref) or not SHA256_REF_RE.match(sref) or not SNAPSHOT_RE.match(csnap) or not SHA256_REF_RE.match(emref) or outc not in ("passed", "violated", "inconclusive"): raise ValueError("mig_envelope")
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
  def _eval_rec(rec: dict[str, Any]) -> tuple[str, str]:
    eff, r_res = rec["outcome"], rec["resource"].strip()
    res_ok = bool(r_res) and (r_res in res_set or ("#" in r_res and r_res.split("#", 1)[0].strip() in res_set))
    if chk := check_receipt_scope_snap_subj(rec, scope_code, active_cases, expected_snapshot, expected_subject_ref, cov_matches_fn, "migration", res_ok):
      return chk
    ec, dc, osaf = rec["epoch_compatibility"], rec["data_correctness"], rec["operational_safety"]
    if ec["incompatible_epochs"]: return "violated", "migration.epoch_incompatible"
    if dc["violations"] > 0: return "violated", "migration.data_invariant_violated"
    if osaf["lock_budget_ms"] > 0 and osaf["duration_budget_ms"] > 0 and (osaf["max_lock_ms"] > osaf["lock_budget_ms"] or osaf["duration_ms"] > osaf["duration_budget_ms"]): return "violated", "migration.lock_budget_exceeded"
    deg = "inconclusive" if eff == "passed" else eff
    if not ec["active_epochs"] or not set(ec["active_epochs"]).issubset(set(ec["compatible_epochs"])): return deg, "migration.epoch_incomplete"
    if not inv_keys.issubset(set(dc["invariants_checked"])) or (rec["phase"] == "backfill" and dc["rows_verified"] <= 0): return deg, "migration.invariants_incomplete"
    if not osaf["lock_mode"] or osaf["lock_budget_ms"] <= 0 or osaf["duration_budget_ms"] <= 0 or not SHA256_REF_RE.match(osaf["context_ref"]): return deg, "migration.operational_unmeasured"
    return eff, ("migration.violated" if eff == "violated" else "")
  return reduce_receipt_groups(by_target, _eval_rec, "migration")

__all__ = ["collect_receipt_files", "eval_sim_opt_blocks", "evaluate_contract_composition_core", "evaluate_contract_migration_core", "load_composition_manifests_core", "load_migration_receipts_core"]
