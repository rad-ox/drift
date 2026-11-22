#!/usr/bin/env python3
"""Single-contract proof verdict evaluation for drift_verify.py (MIT License)."""

from __future__ import annotations

from typing import Any

from drift_verify_base import _proof_rank, digest_matches
from drift_verify_obs import red03
from drift_verify_parity import (
    evaluate_contract_composition_core,
    evaluate_contract_parity_impl,
)
from drift_verify_perf import evaluate_contract_budgets
from drift_verify_ra import evaluate_contract_ra_bundle
from drift_verify_sec import (
    evaluate_contract_formal_impl,
    evaluate_contract_migration_impl,
    evaluate_contract_security_impl,
)
from drift_verify_sim import evaluate_contract_simulation_impl


def _collect_contract_events(
    contract: dict[str, Any],
    events: list[dict[str, Any]],
    allow_exec_reuse: bool,
    base_contract: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, bool, set[str]]:
    cid = contract["id"]
    digest = contract["digest"]
    is_03 = contract.get("drift") == "0.3"
    req_caps = set(contract.get("required_capabilities") or ())
    base_dig = base_contract.get("digest", "") if isinstance(base_contract, dict) else ""
    base_caps = set((base_contract or {}).get("required_capabilities") or ())

    curr_matches: list[dict[str, Any]] = []
    base_matches: list[dict[str, Any]] = []
    ignored = 0
    handshake_bad = False
    unevaluated: set[str] = set()

    for ev in events:
        if ev["contract"] != cid:
            continue
        unevaluated.update(ev.get("_unev") or ())
        if digest_matches(ev["digest"], digest):
            ev_caps = set(ev.get("capabilities") or ())
            if is_03 and (ev.get("schema") != "0.3" or not req_caps.issubset(ev_caps)):
                handshake_bad = True
                ignored += 1
                continue
            curr_matches.append(ev)
        elif allow_exec_reuse and base_dig and digest_matches(ev["digest"], base_dig):
            ev_caps = set(ev.get("capabilities") or ())
            if base_contract and base_contract.get("drift") == "0.3" and (
                ev.get("schema") != "0.3" or not base_caps.issubset(ev_caps)
            ):
                ignored += 1
                continue
            base_matches.append(ev)
        else:
            ignored += 1

    return curr_matches, base_matches, ignored, handshake_bad, unevaluated


def _merge_latest_events(
    contract: dict[str, Any],
    curr_matches: list[dict[str, Any]],
    base_matches: list[dict[str, Any]],
    allow_exec_reuse: bool,
    base_contract: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], int]:
    latest: dict[str, dict[str, Any]] = {}
    superseded = 0
    for ev in curr_matches:
        if ev["test"] in latest:
            superseded += 1
        latest[ev["test"]] = red03(contract, ev)

    base_dig = base_contract.get("digest", "") if isinstance(base_contract, dict) else ""
    same_env = bool(
        allow_exec_reuse
        and base_contract
        and base_contract.get("id") == contract["id"]
        and base_dig
        and base_dig != contract["digest"]
        and contract.get("reuse_env")
        and contract.get("reuse_env") == base_contract.get("reuse_env")
    )
    if not (same_env and base_matches and base_contract):
        return latest, superseded

    base_latest: dict[str, dict[str, Any]] = {}
    for bev in base_matches:
        base_latest[bev["test"]] = red03(base_contract, bev)

    target_sigs = contract.get("case_reuse_sigs") or {}
    base_sigs = base_contract.get("case_reuse_sigs") or {}
    curr_covered = {(kc, ev["level"]) for ev in latest.values() for kc in ev["cases"]}
    unchanged = {kc for kc, sig in target_sigs.items() if sig and sig == base_sigs.get(kc)}

    for tid, bev in base_latest.items():
        if tid in latest or bev["outcome"] != "passed" or bev["red"]:
            continue
        if not all(kc in unchanged for kc in bev["cases"]):
            continue
        fills_gap = any(
            (kc, lv) not in curr_covered and (lv == "*" or bev["level"] == lv)
            for kc in bev["cases"]
            for lv in (contract["cases"][kc].get("at") or ["*"])
        )
        if fills_gap:
            latest[tid] = bev

    return latest, superseded


def _evaluate_case_states(
    contract: dict[str, Any],
    active_events: list[dict[str, Any]],
    require_observations: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    has_orphan = any(kc not in contract["cases"] for ev in active_events for kc in ev["cases"])
    by_case: dict[str, list[dict[str, Any]]] = {}
    for ev in active_events:
        for kc in ev["cases"]:
            by_case.setdefault(kc, []).append(ev)

    results: list[dict[str, Any]] = []
    for case_id in sorted(contract["cases"]):
        case_meta = contract["cases"][case_id]
        if isinstance(case_meta, dict) and "status" in case_meta:
            continue
        case_events = by_case.get(case_id, ())
        for level in case_meta.get("at") or ["*"]:
            covered = case_events if level == "*" else [ev for ev in case_events if ev["level"] == level]
            any_obs = any(
                ev["outcome"] == "passed"
                and case_id not in ev["red"]
                and case_id in (ev.get("observations") or {})
                for ev in covered
            )
            if not covered:
                state = "missing"
            else:
                worst = 4
                for ev in covered:
                    if case_id in ev["red"]:
                        rank = 0
                    else:
                        rank = {"failed": 0, "interrupted": 1, "timeout": 2, "skipped": 3, "disabled": 3}.get(ev["outcome"], 4)
                    if rank < worst:
                        worst = rank
                if worst == 0:
                    state = "red"
                elif worst == 1:
                    state = "interrupted"
                elif worst == 2:
                    state = "timeout"
                elif worst == 3:
                    state = "skipped"
                elif any(case_id in ev["read"] for ev in covered) and (not require_observations or any_obs):
                    state = "verified"
                else:
                    state = "bound"
            results.append({"case": case_id, "level": level, "state": state, "_obs": any_obs})

    return results, has_orphan


def _core_gate_reasons(
    contract: dict[str, Any],
    cfg_state: str,
    policy: dict[str, Any],
    min_proof: str,
    phase: str,
    total_open: int | None,
    mutations_ok: bool,
    ev_errors: list[str],
    handshake_bad: bool,
    incomplete_shards: int,
    has_orphan: bool,
    results: list[dict[str, str]],
) -> list[str]:
    reasons: list[str] = []
    pol_on = policy.get("pack") == "core@1"

    if cfg_state == "missing":
        reasons.append("config.missing")
    elif cfg_state != "current":
        if cfg_state == "stale":
            reasons.append("config.findings")
        reasons.append(f"config.approval.{cfg_state}")

    approval_state = contract["approval"]
    if approval_state != "current":
        if approval_state == "stale":
            reasons.append("contract.findings")
        reasons.append(f"contract.approval.{approval_state}")
    elif (
        pol_on
        and isinstance(policy.get("approvers"), list)
        and policy["approvers"]
        and contract.get("approver", "") not in policy["approvers"]
    ):
        reasons.append("contract.approval.unlisted")

    max_open = policy.get("max_open")
    if (
        pol_on
        and isinstance(max_open, int)
        and not isinstance(max_open, bool)
        and max_open > 0
        and contract.get("open_cnt", 0) > 0
        and (contract.get("open_cnt", 0) if total_open is None else total_open) > max_open
    ):
        reasons.append("policy.max_open")

    if contract.get("exec_blk"):
        reasons.append("contract.blocked.execution")
    if phase == "release" and contract.get("rel_blk"):
        reasons.append("contract.blocked.release")
    if ev_errors or handshake_bad:
        reasons.append("events.invalid")
    if incomplete_shards > 0:
        reasons.append("shard.incomplete")

    eff_rank = (
        max(
            _proof_rank(min_proof),
            _proof_rank(str(policy.get("proof", "")) if pol_on else ""),
            _proof_rank(str(contract.get("profile_proof", ""))),
        )
        or 1
    )
    req_obs = pol_on and policy.get("require_observations") is True
    allowed_states = ("verified",) if eff_rank >= 2 else ("verified", "bound")
    if (
        has_orphan
        or incomplete_shards > 0
        or not results
        or any(r["state"] not in allowed_states for r in results)
        or (req_obs and not all(r.get("_obs") for r in results))
        or (eff_rank >= 3 and not mutations_ok)
    ):
        reasons.append("proof.not_green")

    return reasons


def evaluate_contract_impl(
    contract: dict[str, Any],
    cfg_state: str,
    events: list[dict[str, Any]],
    gone: int,
    incomplete_shards: int,
    ev_errors: list[str],
    policy: dict[str, Any] | None = None,
    min_proof: str = "verified",
    phase: str = "",
    total_open: int | None = None,
    mutations_ok: bool = False,
    perf_bundle: Any = None,
    expected_subject: dict[str, Any] | None = None,
    sec_receipts: list[dict[str, Any]] | None = None,
    expected_snapshot: str = "",
    formal_receipts: list[dict[str, Any]] | None = None,
    shard_subject_refs: set[str] | None = None,
    manifest_sources: Any = None,
    parity_receipts: list[dict[str, Any]] | None = None,
    mig_receipts: list[dict[str, Any]] | None = None,
    allow_exec_reuse: bool = False,
    base_contract: dict[str, Any] | None = None,
    release_attest: bool = False,
    sim_receipts: list[dict[str, Any]] | None = None,
    ra_receipts: Any = None,
    comp_manifests: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pol = policy or {}
    pol_on = pol.get("pack") == "core@1"
    active_pol = pol if pol_on else {}

    curr_m, base_m, ignored, hs_bad, unev_s = _collect_contract_events(
        contract, events, allow_exec_reuse, base_contract
    )
    latest, superseded = _merge_latest_events(
        contract, curr_m, base_m, allow_exec_reuse, base_contract
    )
    req_obs = bool(pol_on and pol.get("require_observations") is True)
    results_raw, has_orphan = _evaluate_case_states(contract, list(latest.values()), require_observations=req_obs)
    reasons = _core_gate_reasons(
        contract,
        cfg_state,
        pol,
        min_proof,
        phase,
        total_open,
        mutations_ok,
        ev_errors,
        hs_bad,
        incomplete_shards,
        has_orphan,
        results_raw,
    )
    results = [{"case": r["case"], "level": r["level"], "state": r["state"]} for r in results_raw]

    exp_sref = (expected_subject or {}).get("artifact_ref", "")
    p_rsn, pend_b, p_sum = evaluate_contract_budgets(
        contract, phase, perf_bundle, expected_subject, digest_matches, pol
    )
    s_rsn, s_checks = evaluate_contract_security_impl(
        contract,
        sec_receipts or [],
        active_pol,
        expected_snapshot,
        digest_matches,
        expected_subject,
        allow_exec_reuse and phase != "release",
        base_contract,
    )
    f_rsn, pend_f, f_checks = evaluate_contract_formal_impl(
        contract,
        formal_receipts or [],
        phase,
        exp_sref,
        expected_snapshot,
        shard_subject_refs or set(),
        contract.get("area_root"),
        manifest_sources,
        digest_matches,
    )
    m_rsn, m_checks = evaluate_contract_migration_impl(
        contract, mig_receipts or [], active_pol, expected_snapshot, exp_sref, digest_matches
    )
    sim_rsn, sim_checks = evaluate_contract_simulation_impl(
        contract, sim_receipts or [], active_pol, expected_snapshot, exp_sref, digest_matches
    )
    par_rsn, par_checks = evaluate_contract_parity_impl(
        contract,
        parity_receipts or [],
        phase,
        digest_matches,
        exp_sref,
        shard_subject_refs or set(),
        m_checks,
    )
    comp_rsn, comp_checks = evaluate_contract_composition_core(contract, comp_manifests or [])
    ra_rsn, ra_extra = evaluate_contract_ra_bundle(
        contract,
        results,
        s_checks,
        f_checks,
        m_checks,
        ra_receipts,
        exp_sref,
        phase,
        mutations_ok,
        digest_matches,
    )

    for reason in (*p_rsn, *s_rsn, *f_rsn, *par_rsn, *m_rsn, *sim_rsn, *comp_rsn, *ra_rsn):
        if reason not in reasons:
            reasons.append(reason)

    if (
        phase == "release"
        and release_attest
        and (expected_subject or {}).get("has_manifest")
        and not (expected_subject or {}).get("binary_ref")
        and "trust.artifact_required" not in reasons
    ):
        reasons.append("trust.artifact_required")

    out: dict[str, Any] = {
        "id": contract["id"],
        "digest": contract["digest"],
        "ref": contract["ref"],
        "approval": contract["approval"],
        "ok": not reasons,
        "reasons": reasons,
        "ignored": ignored,
        "superseded": superseded,
        "gone": gone,
        "results": results,
        **ra_extra,
    }
    optional_fields = (
        ("assurance_digest", contract.get("assurance_digest")),
        ("assurance_ref", contract.get("assurance_ref")),
        ("performance", p_sum),
        ("pending_budgets", pend_b),
        ("pending_formal", pend_f),
        ("security_checks", s_checks),
        ("formal_checks", f_checks),
        ("parity_checks", par_checks),
        ("migration_checks", m_checks),
        ("simulation_checks", sim_checks),
        ("composition_checks", comp_checks),
        ("unevaluated", sorted(unev_s)),
    )
    for key, val in optional_fields:
        if val:
            out[key] = val
    return out
