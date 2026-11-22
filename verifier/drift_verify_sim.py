#!/usr/bin/env python3
"""DRIFT Independent Reference Simulation Receipt Verifier (MIT License)."""

from __future__ import annotations
import math
from pathlib import Path
from typing import Any
from drift_verify_base import (
    DIGEST_RE,
    ID_RE,
    SHA256_REF_RE,
    SNAPSHOT_RE,
    _cov_matches,
    _valid_rel_scope,
    collect_receipt_files,
)

SIM_OPT_KEYS = frozenset(("observed_convergence", "trajectory_stability"))
SIM_KEYS = frozenset((
    "schema", "contract", "digest", "simulation_id", "runner", "runner_ref",
    "subject_ref", "code_snapshot", "covered_scope", "cases",
    "tick_determinism", "rollback_invariance", "save_epoch_compatibility", "outcome",
))


def _req_str_list(m: dict[str, Any], k: str) -> list[str]:
    v = m.get(k, [])
    if not isinstance(v, list) or any(not isinstance(x, str) or not x.strip() for x in v):
        raise ValueError(k)
    return [x.strip() for x in v]


def parse_sim_opt_blocks(doc: dict[str, Any]) -> dict[str, Any]:
    ex: dict[str, Any] = {}
    if "observed_convergence" in doc:
        oc = doc["observed_convergence"]
        if not isinstance(oc, dict) or set(oc) != {"grid_steps", "errors", "norm", "reference_kind", "roundoff_floor", "min_expected_order", "horizon"}:
            raise ValueError("observed_convergence")
        gs, es, rf, mo, hz = oc["grid_steps"], oc["errors"], float(oc["roundoff_floor"]), float(oc["min_expected_order"]), float(oc["horizon"])
        if not isinstance(gs, list) or not isinstance(es, list) or len(gs) < 2 or len(gs) != len(es) or oc["norm"] not in ("L1", "L2", "L_inf") or oc["reference_kind"] not in ("exact_analytic", "fine_grid_self") or rf <= 0 or mo <= 0 or hz <= 0 or any(float(gs[i]) <= 0 or float(es[i]) < 0 or (i > 0 and float(gs[i]) >= float(gs[i - 1])) for i in range(len(gs))):
            raise ValueError("observed_convergence")
        ex["observed_convergence"] = {"errors": [float(x) for x in es], "grid_steps": [float(x) for x in gs], "horizon": hz, "min_expected_order": mo, "norm": str(oc["norm"]), "reference_kind": str(oc["reference_kind"]), "roundoff_floor": rf}
    if "trajectory_stability" in doc:
        ts = doc["trajectory_stability"]
        if not isinstance(ts, dict) or not set(ts).issubset({"horizon", "max_abs_drift", "max_allowed_drift", "non_finite_count", "subnormal_count", "forbid_subnormals"}):
            raise ValueError("trajectory_stability")
        hz, md, ad, nf, sb, fs = float(ts["horizon"]), float(ts["max_abs_drift"]), float(ts["max_allowed_drift"]), int(ts["non_finite_count"]), int(ts["subnormal_count"]), bool(ts.get("forbid_subnormals", False))
        if hz <= 0 or md < 0 or ad < 0 or nf < 0 or sb < 0:
            raise ValueError("trajectory_stability")
        ex["trajectory_stability"] = {"forbid_subnormals": fs, "horizon": hz, "max_abs_drift": md, "max_allowed_drift": ad, "non_finite_count": nf, "subnormal_count": sb}
    return ex


def eval_sim_opt_blocks(rec: dict[str, Any], eff: str) -> tuple[str, str]:
    if isinstance(ts := rec.get("trajectory_stability"), dict):
        if ts["non_finite_count"] > 0:
            return "violated", "sim.non_finite_state"
        if ts.get("forbid_subnormals") and ts["subnormal_count"] > 0:
            return "violated", "sim.subnormal_state"
        if ts["max_abs_drift"] > ts["max_allowed_drift"] + 1e-12:
            return "violated", "sim.drift_exceeded"
    if isinstance(oc := rec.get("observed_convergence"), dict):
        gs, es, rf, mo, vp = oc["grid_steps"], oc["errors"], oc["roundoff_floor"], oc["min_expected_order"], 0
        for i in range(len(gs) - 1):
            if es[i] <= rf:
                if es[i + 1] > rf:
                    return "violated", "sim.convergence_degraded"
                continue
            if es[i + 1] <= rf:
                continue
            vp += 1
            if es[i + 1] >= es[i] or (math.log(es[i] / es[i + 1]) / math.log(gs[i] / gs[i + 1])) + 1e-9 < mo:
                return "violated", "sim.convergence_degraded"
        if vp == 0:
            return ("inconclusive" if eff == "passed" else eff), "sim.roundoff_masked"
    return eff, ""


def collect_sim_receipt_files(events_paths: list[Path]) -> list[Path]:
    return collect_receipt_files(events_paths, ".sim.json")


def load_simulation_receipts_core(events_paths: list[Path], decode_fn: Any, valid_rel_scope_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
    out, errs = [], []
    for sf in collect_sim_receipt_files(events_paths):
        try:
            doc = decode_fn(sf.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or not SIM_KEYS.issubset(doc) or any(k not in SIM_KEYS and k not in SIM_OPT_KEYS for k in doc) or doc.get("schema") != "drift.sim-receipt/1":
                raise ValueError("sim_keys")
            cid, dig, sid = str(doc.get("contract", "")), str(doc.get("digest", "")), str(doc.get("simulation_id", ""))
            runner, rref, sref, csnap, outc = str(doc.get("runner", "")), str(doc.get("runner_ref", "")), str(doc.get("subject_ref", "")), str(doc.get("code_snapshot", "")), str(doc.get("outcome", ""))
            if not ID_RE.match(cid) or not DIGEST_RE.match(dig) or not sid.strip() or not runner.strip() or not SHA256_REF_RE.match(rref) or not SHA256_REF_RE.match(sref) or not SNAPSHOT_RE.match(csnap) or outc not in ("passed", "violated", "inconclusive"):
                raise ValueError("sim_envelope")
            cov, cs = doc.get("covered_scope"), doc.get("cases")
            if not isinstance(cov, list) or len(set(cov)) != len(cov) or not all(valid_rel_scope_fn(x) for x in cov):
                raise ValueError("covered_scope")
            if not isinstance(cs, list) or not cs or not all(isinstance(x, str) and ID_RE.match(x) for x in cs):
                raise ValueError("cases")
            td, ri, se = doc.get("tick_determinism"), doc.get("rollback_invariance"), doc.get("save_epoch_compatibility")
            if not isinstance(td, dict) or not isinstance(ri, dict) or not isinstance(se, dict):
                raise ValueError("sim_tables")
            seed_ref, inp_ref, traj_ref = str(td.get("seed_corpus_ref", "")), str(td.get("input_stream_ref", "")), str(td.get("trajectory_digest", ""))
            ticks_exec, plats, div_ticks = td.get("ticks_executed"), _req_str_list(td, "platforms_compared"), td.get("divergent_ticks", [])
            if not SHA256_REF_RE.match(seed_ref) or not SHA256_REF_RE.match(inp_ref) or not SHA256_REF_RE.match(traj_ref) or not isinstance(ticks_exec, int) or isinstance(ticks_exec, bool) or ticks_exec < 0 or not isinstance(div_ticks, list) or any(not isinstance(dt, dict) or set(dt) != {"tick", "case", "expected_hash", "observed_hash"} or isinstance(dt.get("tick"), bool) or not isinstance(dt.get("tick"), int) or dt["tick"] < 0 for dt in div_ticks):
                raise ValueError("tick_determinism")
            win_t, max_rb, resim_m, leaked_m = ri.get("windows_tested"), ri.get("max_rollback_frames"), ri.get("resim_mismatches"), ri.get("leaked_ambient_mutations")
            if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in (win_t, max_rb, resim_m, leaked_m)):
                raise ValueError("rollback_invariance")
            act_ep, cmp_ep, inc_ep, inv_chk = _req_str_list(se, "active_save_epochs"), _req_str_list(se, "compatible_epochs"), _req_str_list(se, "incompatible_epochs"), _req_str_list(se, "invariants_checked")
            opt_b = parse_sim_opt_blocks(doc)
            out.append({"schema": "drift.sim-receipt/1", "contract": cid, "digest": dig, "simulation_id": sid, "runner": runner, "runner_ref": rref, "subject_ref": sref, "code_snapshot": csnap, "covered_scope": sorted(set(cov)), "cases": sorted(set(cs)), "tick_determinism": {"seed_corpus_ref": seed_ref, "input_stream_ref": inp_ref, "ticks_executed": ticks_exec, "platforms_compared": sorted(set(plats)), "trajectory_digest": traj_ref, "divergent_ticks": [{"case": str(x["case"]), "expected_hash": str(x["expected_hash"]), "observed_hash": str(x["observed_hash"]), "tick": int(x["tick"])} for x in div_ticks]}, "rollback_invariance": {"leaked_ambient_mutations": leaked_m, "max_rollback_frames": max_rb, "resim_mismatches": resim_m, "windows_tested": win_t}, "save_epoch_compatibility": {"active_save_epochs": sorted(set(act_ep)), "compatible_epochs": sorted(set(cmp_ep)), "incompatible_epochs": sorted(set(inc_ep)), "invariants_checked": sorted(set(inv_chk))}, **opt_b, "outcome": outc})
        except Exception as exc:
            errs.append(f"{sf.name}: {exc}")
    return out, errs


def evaluate_contract_simulation_core(
    contract: dict[str, Any], sim_receipts: list[dict[str, Any]], policy: dict[str, Any] | None,
    expected_snapshot: str, expected_subject_ref: str, digest_matches_fn: Any, cov_matches_fn: Any,
) -> tuple[list[str], list[dict[str, Any]]]:
    pol = policy or {}
    req_sim = bool(contract.get("profile_simulation")) or (pol.get("pack") == "core@1" and pol.get("simulation") == "required")
    scope_code = contract.get("scope_code") or []
    raw_cases = contract.get("cases") or {}
    active_cases = {cid for cid, cm in raw_cases.items() if isinstance(cm, dict) and "status" not in cm}
    inv_keys = set(contract.get("invariants") or ())
    by_target: dict[str, dict[str, dict[str, Any]]] = {}
    for r in sim_receipts:
        if r["contract"] == contract["id"] and digest_matches_fn(r["digest"], contract["digest"]):
            tkey = r["simulation_id"]
            ikey = repr((r["runner"], r["runner_ref"], r["subject_ref"], r["code_snapshot"], r["covered_scope"], r["cases"], r["tick_determinism"], r["rollback_invariance"], r["save_epoch_compatibility"], r["outcome"]))
            by_target.setdefault(tkey, {})[ikey] = r
    if not by_target and not req_sim:
        return [], []
    if not by_target and req_sim:
        return ["sim.missing"], []
    eval_list, reasons, has_viol, has_inc = [], [], False, False
    for tkey in sorted(by_target):
        bucket = by_target[tkey]
        group = [bucket[k] for k in sorted(bucket)]
        has_conflict = len(group) > 1
        grp_viol, grp_evals = False, []
        for rec in group:
            eff, rsn = rec["outcome"], ""
            td, ri, se = rec["tick_determinism"], rec["rollback_invariance"], rec["save_epoch_compatibility"]
            if not scope_code or not all(any(cov_matches_fn(c, sc) for c in rec["covered_scope"]) for sc in scope_code) or not active_cases or not all(c in active_cases for c in rec["cases"]):
                eff, rsn = ("inconclusive" if eff == "passed" else eff), "sim.incomplete_scope"
            elif expected_snapshot and rec["code_snapshot"] != expected_snapshot:
                eff, rsn = ("inconclusive" if eff == "passed" else eff), "sim.snapshot_mismatch"
            elif expected_subject_ref and rec["subject_ref"] != expected_subject_ref:
                eff, rsn = ("inconclusive" if eff == "passed" else eff), "sim.subject_mismatch"
            elif td["divergent_ticks"]:
                eff, rsn = "violated", "sim.desync_detected"
            elif ri["resim_mismatches"] > 0 or ri["leaked_ambient_mutations"] > 0:
                eff, rsn = "violated", "sim.rollback_drift"
            elif se["incompatible_epochs"]:
                eff, rsn = "violated", "sim.save_epoch_incompatible"
            elif td["ticks_executed"] <= 0 or not td["platforms_compared"] or ri["windows_tested"] <= 0 or ri["max_rollback_frames"] <= 0:
                eff, rsn = ("inconclusive" if eff == "passed" else eff), "sim.incomplete_scope"
            elif not se["active_save_epochs"] or not set(se["active_save_epochs"]).issubset(set(se["compatible_epochs"])) or not inv_keys.issubset(set(se["invariants_checked"])):
                eff, rsn = ("inconclusive" if eff == "passed" else eff), "sim.invariants_incomplete"
            else:
                eff, rsn = eval_sim_opt_blocks(rec, eff)
                if eff == "violated" and not rsn:
                    rsn = "sim.violated"
            if eff == "violated":
                grp_viol = True
            grp_evals.append((rec, eff, rsn))
        for rec, eff0, rsn0 in grp_evals:
            eff, rsn = eff0, rsn0
            if has_conflict:
                if grp_viol:
                    eff = "violated"
                    rsn = rsn0 if (rsn0 and rsn0 != "sim.violated") else "sim.conflicting_receipts"
                else:
                    eff, rsn = "inconclusive", "sim.conflicting_receipts"
            item = {**rec, "effective_outcome": eff, "provenance": "measured"}
            if rsn:
                item["reason"] = rsn
            eval_list.append(item)
            if eff == "violated":
                has_viol = True
                if rsn and rsn not in reasons:
                    reasons.append(rsn)
                if has_conflict and "sim.conflicting_receipts" not in reasons:
                    reasons.append("sim.conflicting_receipts")
            elif eff != "passed":
                has_inc = True
                if rsn and rsn not in reasons:
                    reasons.append(rsn)
    if has_viol and "sim.violated" not in reasons:
        reasons.append("sim.violated")
    if has_inc and not has_viol and "sim.inconclusive" not in reasons:
        reasons.append("sim.inconclusive")
    return reasons, eval_list


def load_simulation_receipts_impl(events_paths: list[Path], decode_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
    return load_simulation_receipts_core(events_paths, decode_fn, _valid_rel_scope)


def evaluate_contract_simulation_impl(
    contract: dict[str, Any], sim_receipts: list[dict[str, Any]], policy: dict[str, Any] | None,
    expected_snapshot: str, expected_subject_ref: str, digest_matches_fn: Any,
) -> tuple[list[str], list[dict[str, Any]]]:
    return evaluate_contract_simulation_core(contract, sim_receipts, policy, expected_snapshot, expected_subject_ref, digest_matches_fn, _cov_matches)
