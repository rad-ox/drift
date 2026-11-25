#!/usr/bin/env python3
"""Independent zero-dependency DRIFT proof protocol verifier CLI and facade (MIT License)."""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    sys.stderr.write(
        f"drift_verify: Python 3.11+ required (found {sys.version_info.major}.{sys.version_info.minor})\n"
    )
    sys.exit(2)

import argparse
import json
import os
import tomllib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from drift_verify_03 import verify_contract_03_toml
from drift_verify_base import (
    DIGEST_RE,
    ENV_KEYS,
    ID_RE,
    SAFE_INT,
    SNAPSHOT_RE,
    WORD_RE,
    _decode_no_dup_keys,
    _has_approval_blocker,
    _is_unanchored_prose_source,
    _proof_rank,
    canonical_json,
    digest_matches,
    dr1_digest,
    dr1_ref,
    jcs_number,
    jcs_string,
)
from drift_verify_dist import (
    evaluate_break_glass_py,
    evaluate_containment_py,
    evaluate_role_signatures_py,
    evaluate_shard_bundles_py,
)
from drift_verify_eval import evaluate_contract_impl
from drift_verify_events import (
    EVENT_KEYS,
    OUTCOMES,
    load_proof_events_impl,
    validate_event_line_impl,
)
from drift_verify_grant import evaluate_grant_verdicts_py
from drift_verify_mutation import (
    evaluate_contract_mutations_impl,
    load_mutation_events_impl,
    validate_mutation_manifest_impl,
)
from drift_verify_obs import obs03, red03
from drift_verify_pact import evaluate_pact_verdicts_py
from drift_verify_parity import (
    evaluate_contract_composition_core,
    evaluate_contract_parity_impl,
    extract_contract_cutover,
    load_composition_manifests_core,
    load_parity_receipts_impl,
)
from drift_verify_perf import (
    evaluate_contract_budgets,
    extract_contract_budgets,
    load_measurement_bundle,
)
from drift_verify_ra import (
    evaluate_contract_ra_bundle,
    evaluate_detached_signatures_core,
    extract_contract_risks_and_controls,
    load_ra_receipts_core,
)
from drift_verify_sec import (
    evaluate_contract_formal_impl,
    evaluate_contract_migration_impl,
    evaluate_contract_security_impl,
    extract_contract_formal,
    load_formal_receipts_impl,
    load_migration_receipts_impl,
    load_security_receipts_impl,
)
from drift_verify_selftest import (
    run_ra_self_test_impl as run_ra_self_test,
    run_sec_self_test_core,
    run_verifier_self_test as _run_verifier_self_test,
)
from drift_verify_sim import (
    evaluate_contract_simulation_impl,
    load_simulation_receipts_impl,
)
from drift_verify_ssh import apply_openssh_trust_verdicts, load_merged_profile_impl
from drift_verify_subject import (
    lookup_registered_shadow_py,
    order_shadow_shards_py,
    parse_security_lock_impl,
    parse_subject_manifest_impl,
    resolve_shadow_roots_impl,
    resolve_verifier_subject_cli,
    shadow_inputs_fresh,
    strip_outside_digest_impl,
    validate_inventory_text_impl,
    verify_config_toml_impl,
)

SWEEP_SOUNDNESS_WARNING = (
    'drift_verify: warning: policy.sweep = "soundness" is not evaluated by the '
    "offline verifier; run DRIFT Pro for area soundness gating"
)
_CORE_POLICY_KEYS = frozenset((
    "approvers", "proof", "ignore", "uncovered", "sweep", "max_lines", "max_open",
    "warn_ratio", "performance_reuse", "forbid_imports", "security", "simulation",
    "priority_weights", "companion_edits", "patch_scope", "require_signed_approval",
    "require_observations", "block_redundancy_erosion", "grant_lock", "pact_locks",
    "signatures", "autonomy",
))


def _opaque_core_policy_keys(pol: dict[str, Any]) -> list[str]:
    if not isinstance(pol, dict) or pol.get("pack") == "core@1":
        return []
    return sorted(k for k in pol if k in _CORE_POLICY_KEYS)


def compare_gate_parity(cli_doc: dict[str, Any], verdicts: list[dict[str, Any]], py_ok: bool) -> list[str]:
    mismatches: list[str] = []
    if not isinstance(cli_doc, dict):
        return ["cli gate JSON root must be an object"]
    cli_ok = bool(cli_doc.get("ok"))
    if cli_ok != py_ok:
        mismatches.append(f"top-level ok mismatch: cli={cli_ok} py={py_ok}")
    raw_cli_contracts = cli_doc.get("contracts") if isinstance(cli_doc.get("contracts"), list) else (
        [cli_doc] if ("contract" in cli_doc or "id" in cli_doc) else []
    )
    cli_by_id = {
        str(c.get("contract") or c.get("id") or ""): c
        for c in raw_cli_contracts
        if isinstance(c, dict) and (c.get("contract") or c.get("id"))
    }
    py_by_id = {str(v["id"]): v for v in verdicts}
    if sorted(cli_by_id) != sorted(py_by_id):
        mismatches.append(f"contract set mismatch: cli={sorted(cli_by_id)} py={sorted(py_by_id)}")
    for cid in sorted(set(cli_by_id) & set(py_by_id)):
        cc, pc = cli_by_id[cid], py_by_id[cid]
        for fld in ("ok", "approval", "superseded", "gone", "ignored"):
            if fld in cc and cc.get(fld) != pc.get(fld):
                mismatches.append(f"{cid}.{fld}: cli={cc.get(fld)!r} py={pc.get(fld)!r}")
        cr = sorted(str(x) for x in (cc.get("reasons") or []))
        pr = sorted(str(x) for x in (pc.get("reasons") or []))
        if cr != pr:
            mismatches.append(f"{cid}.reasons: cli={cr} py={pr}")
        c_res = {
            (str(r.get("case", "")), str(r.get("level", ""))): str(r.get("state", ""))
            for r in (cc.get("results") or [])
            if isinstance(r, dict)
        }
        p_res = {
            (str(r.get("case", "")), str(r.get("level", ""))): str(r.get("state", ""))
            for r in (pc.get("results") or [])
            if isinstance(r, dict)
        }
        for key in sorted(set(c_res) | set(p_res)):
            if c_res.get(key) != p_res.get(key):
                mismatches.append(f"{cid}#{key[0]}({key[1]}): cli={c_res.get(key)!r} py={p_res.get(key)!r}")
    return mismatches


def run_sec_self_test(ck: dict[str, Any], digest_matches_fn: Any) -> None:
    run_sec_self_test_core(ck, digest_matches_fn, evaluate_contract_security_impl, sys.modules[__name__])


def run_verifier_self_test() -> int:
    return _run_verifier_self_test(sys.modules[__name__])


validate_event_line = validate_event_line_impl


def validate_inventory_text(text: str) -> dict[str, Any]:
    return validate_inventory_text_impl(text, _decode_no_dup_keys)


def validate_inventory_sidecar(path: Path) -> dict[str, Any]:
    return validate_inventory_text(path.read_text("utf-8"))


def resolve_shadow_roots(path: Path, state_dir: str = "") -> dict[str, Any]:
    return resolve_shadow_roots_impl(path, state_dir)


def verify_config_toml(path: Path) -> tuple[str, str, dict[str, Any]]:
    return verify_config_toml_impl(path, dr1_digest, dr1_ref)


def _load_merged_profile(prof_ref: str, profiles_dir: Path) -> dict[str, Any]:
    return load_merged_profile_impl(prof_ref, profiles_dir, _proof_rank)


def _strip_outside_digest(cases: Any, decs: Any) -> None:
    strip_outside_digest_impl(cases, decs, _is_unanchored_prose_source)


def verify_contract_toml(path: Path, profiles_dir: Path) -> dict[str, Any]:
    raw = tomllib.loads(path.read_text("utf-8"))
    if raw.get("drift") != "0.3":
        roots = resolve_shadow_roots(path)
        return {
            "drift": str(raw.get("drift", "")),
            "id": str(raw.get("id", path.stem)),
            "digest": "",
            "ref": "",
            "approval": "invalid",
            "approver": "",
            "profile_proof": "",
            "profile_security": [],
            "profile_simulation": False,
            "scope_code": [],
            "scope_reads": [],
            "scope_writes": [],
            "invariants": [],
            "cases": {},
            "budgets": {},
            "formal": {},
            "cutover": {},
            "risks": {},
            "controls": {},
            "required_capabilities": [],
            "area_root": roots["source_root"],
            "shadow_area_root": roots["area_root"],
            "open_cnt": 0,
            "exec_blk": False,
            "rel_blk": False,
        }
    return verify_contract_03_toml(
        raw, path, profiles_dir, canonical_json, dr1_ref, _proof_rank, resolve_shadow_roots
    )


load_proof_events = load_proof_events_impl


def validate_mutation_manifest(text: str) -> dict[str, Any]:
    return validate_mutation_manifest_impl(text, _decode_no_dup_keys)


def load_mutation_events(paths: list[Path], manifest: dict[str, Any]) -> tuple[Any, list[str]]:
    return load_mutation_events_impl(paths, manifest, _decode_no_dup_keys)


def evaluate_contract_mutations(
    contract: dict[str, Any],
    manifest: Any,
    latest_mut: Any,
    mut_errors: list[str],
) -> bool:
    return evaluate_contract_mutations_impl(contract, manifest, latest_mut, mut_errors, digest_matches)


evaluate_contract = evaluate_contract_impl


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="drift_verify.py")
    parser.add_argument("targets", nargs="*", type=Path)
    path_flags = (
        "--state-dir",
        "--config",
        "--profiles",
        "--mutants",
        "--measurements",
        "--subject",
        "--security-lock",
        "--base",
        "--attest",
        "--attest-sig",
        "--trust-root",
        "--signatures",
        "--signature-policy",
        "--grant-lock",
        "--compare-gate",
    )
    for flag in path_flags:
        parser.add_argument(flag, type=Path)
    for flag in ("--events", "--mutation-events", "--pact-lock"):
        parser.add_argument(flag, type=Path, action="append")
    parser.add_argument("--changed", action="append", default=[])
    for flag in ("--changed-none", "--json", "--allow-break-glass"):
        parser.add_argument(flag, action="store_true")
    for flag in ("--subject-artifact", "--subject-tree", "--run-id", "--verify-time", "--phase"):
        parser.add_argument(flag, default="")
    parser.add_argument("--min-proof", choices=("bound", "verified", "killed"), default="")
    return parser


def _resolve_cli_inputs(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> tuple[list[Path], Path, list[Path], str]:
    explicit_state_dir = str(args.state_dir) if args.state_dir else ""
    state_dir_env = (
        explicit_state_dir
        or os.environ.get("DRIFT_STATE_DIR", "").strip()
        or lookup_registered_shadow_py(Path.cwd())
    )
    state_dir_path = Path(state_dir_env) if state_dir_env else None
    targets = args.targets or ([state_dir_path / ".drift" / "contracts"] if state_dir_path else [])
    config_path = args.config or ((state_dir_path / ".drift" / "config.toml") if state_dir_path else None)
    default_events = (
        [state_dir_path / ".drift-work" / "events"]
        if state_dir_path and (state_dir_path / ".drift-work" / "events").is_dir()
        else []
    )
    events_paths = args.events or default_events

    if not targets or not config_path or not events_paths:
        parser.error("targets, --config and --events are required")
    if bool(args.mutants) != bool(args.mutation_events):
        parser.error("--mutants and --mutation-events must be supplied together")
    return targets, config_path, events_paths, explicit_state_dir


def _has_event_signature_files(events_paths: list[Path]) -> bool:
    for ep in events_paths:
        if ep.is_file() and ep.name.endswith(".sig.json"):
            return True
        if ep.is_dir() and any(ch.name.endswith(".sig.json") for ch in ep.iterdir()):
            return True
    return False


def _render_verdicts(
    verdicts: list[dict[str, Any]],
    ok: bool,
    pol: dict[str, Any],
    as_json: bool,
    parity_mismatches: list[str] | None = None,
) -> None:
    opaque_keys = _opaque_core_policy_keys(pol)
    if opaque_keys:
        print(
            f'drift_verify: warning: [policy] sets core@1 key(s) [{", ".join(opaque_keys)}] '
            'without pack = "core@1"; area policy is inactive until pack = "core@1" is declared',
            file=sys.stderr,
        )
    sweep_pol = pol.get("sweep") if pol.get("pack") == "core@1" else None
    if sweep_pol == "soundness" or (isinstance(sweep_pol, list) and "soundness" in sweep_pol):
        print(SWEEP_SOUNDNESS_WARNING, file=sys.stderr)
    if as_json:
        out: dict[str, Any] = {"ok": ok, "contracts": verdicts}
        if parity_mismatches is not None:
            out["parity"] = {"ok": len(parity_mismatches) == 0, "mismatches": parity_mismatches}
        print(json.dumps(out, indent=2, sort_keys=True))
        return
    for v in verdicts:
        status = "green" if v["ok"] else f"not green ({', '.join(v['reasons'])})"
        print(f"{v['id']} {v['ref']}: {status}")
    if parity_mismatches is not None:
        if parity_mismatches:
            for mm in parity_mismatches:
                print(f"drift_verify: parity mismatch: {mm}", file=sys.stderr)
        else:
            print("parity: MATCH (cli <-> verifier)")


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return run_verifier_self_test()

    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    targets, config_path, events_paths, explicit_state_dir = _resolve_cli_inputs(parser, args)

    try:
        roots = resolve_shadow_roots(targets[0], explicit_state_dir)
    except Exception as exc:
        print(f"drift_verify.py: {exc}", file=sys.stderr)
        return 2

    cfg_state, cfg_digest, policy = verify_config_toml(config_path)
    profiles_dir = args.profiles or (config_path.parent / "profiles")
    contract_files = [
        cf
        for t in targets
        for cf in (sorted(t.glob("*.toml")) if t.is_dir() else [t])
    ]

    (
        events,
        gone,
        incomplete_shards,
        ev_errors,
        sec_recs,
        form_recs,
        par_recs,
        mig_recs,
        shard_subjects,
        exp_snap,
        shard_hashes,
        snap_list,
        snaps_ok,
    ) = load_proof_events(events_paths, roots["area_root"], "" if args.measurements else args.run_id)

    ra_recs, ra_errs = load_ra_receipts_core(events_paths, _decode_no_dup_keys)
    comp_mans, comp_errs = load_composition_manifests_core(events_paths, _decode_no_dup_keys)
    ev_errors.extend(ra_errs + comp_errs)
    sim_recs, _ = load_simulation_receipts_impl(events_paths, _decode_no_dup_keys)

    mut_manifest: Any = None
    latest_mut: dict[str, Any] = {}
    mut_errors: list[str] = []
    if args.mutants and args.mutation_events:
        try:
            mut_manifest = validate_mutation_manifest(args.mutants.read_text("utf-8"))
            latest_mut, mut_errors = load_mutation_events(args.mutation_events, mut_manifest)
        except Exception as exc:
            mut_errors.append(str(exc))

    exp_sub, man_srcs = resolve_verifier_subject_cli(
        args, _decode_no_dup_keys, canonical_json, parse_subject_manifest_impl, parse_security_lock_impl
    )
    perf_bundle = load_measurement_bundle(args.measurements, _decode_no_dup_keys, digest_matches)

    events_by_contract: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        events_by_contract.setdefault(ev["contract"], []).append(ev)

    parsed = [{**verify_contract_toml(cf, profiles_dir), "file_stem": cf.stem} for cf in contract_files]
    base_files = (
        (sorted(args.base.glob("*.toml")) if args.base.is_dir() else [args.base])
        if args.base
        else ()
    )
    base_by_id = {
        bc["id"]: bc
        for bf in base_files
        for bc in (verify_contract_toml(bf, profiles_dir),)
    }

    total_open = sum(c.get("open_cnt", 0) for c in parsed)
    reuse_ok = bool(args.base and args.changed_none and not args.allow_break_glass)

    raw_verdicts = [
        evaluate_contract(
            c,
            cfg_state,
            events_by_contract.get(c["id"], []),
            gone.get(c["id"], 0),
            incomplete_shards,
            ev_errors,
            policy,
            args.min_proof,
            args.phase,
            total_open,
            evaluate_contract_mutations(c, mut_manifest, latest_mut, mut_errors),
            perf_bundle,
            exp_sub,
            sec_recs,
            exp_snap,
            form_recs,
            shard_subjects,
            man_srcs,
            par_recs,
            mig_recs,
            reuse_ok,
            base_by_id.get(c["id"]),
            bool(args.attest),
            sim_recs,
            ra_recs,
            comp_mans,
        )
        for c in parsed
    ]

    single_file = len(targets) == 1 and targets[0].is_file()
    raw_verdicts, has_gsig = evaluate_grant_verdicts_py(
        raw_verdicts,
        parsed,
        args,
        config_path,
        policy,
        roots["source_root"],
        _decode_no_dup_keys,
        canonical_json,
        digest_matches,
        _proof_rank,
        single_file,
    )
    raw_verdicts, has_psig = evaluate_pact_verdicts_py(
        raw_verdicts,
        parsed,
        contract_files,
        profiles_dir,
        args,
        config_path,
        policy,
        roots["source_root"],
        _decode_no_dup_keys,
        canonical_json,
        jcs_string,
        jcs_number,
        digest_matches,
        _proof_rank,
        verify_contract_toml,
    )
    raw_verdicts, bundle_list = evaluate_shard_bundles_py(
        raw_verdicts, events_paths, snap_list, _decode_no_dup_keys, canonical_json
    )
    raw_verdicts = evaluate_containment_py(raw_verdicts, parsed, events_by_contract, digest_matches)
    aut_cfg = policy.get("autonomy") if isinstance(policy.get("autonomy"), dict) else {}
    agent_cnt = sum(1 for c in parsed if c.get("approval") == "current" and c.get("approver", "").startswith("agent:"))
    if agent_cnt > 0 and (not aut_cfg or agent_cnt > int(aut_cfg.get("max_targets", 0))):
        by_id_p = {c["id"]: c for c in parsed}
        for rv in raw_verdicts:
            if by_id_p.get(rv["id"], {}).get("approver", "").startswith("agent:") and "autonomy.out_of_envelope" not in rv["reasons"]:
                rv["reasons"].append("autonomy.out_of_envelope")
                rv["ok"] = False

    has_ev_sig = _has_event_signature_files(events_paths)
    skip_legacy_openssh = (
        args.signatures
        or args.signature_policy
        or has_gsig
        or has_psig
        or has_ev_sig
        or args.allow_break_glass
        or policy.get("require_signed_approval") is True
    ) and not args.attest and not args.attest_sig

    verdicts = (
        raw_verdicts
        if skip_legacy_openssh
        else apply_openssh_trust_verdicts(
            raw_verdicts,
            args,
            cfg_state,
            cfg_digest,
            shard_hashes,
            snap_list,
            snaps_ok,
            incomplete_shards,
            mut_manifest,
            perf_bundle,
            _decode_no_dup_keys,
            exp_sub,
        )
    )
    verdicts = evaluate_detached_signatures_core(
        verdicts, parsed, args, cfg_digest, _decode_no_dup_keys, canonical_json, digest_matches
    )
    verdicts = evaluate_role_signatures_py(
        verdicts, parsed, bundle_list, args, policy, cfg_digest, _decode_no_dup_keys, canonical_json, digest_matches
    )
    verdicts = evaluate_break_glass_py(
        verdicts, parsed, args, cfg_state, cfg_digest, _decode_no_dup_keys, canonical_json, digest_matches
    )

    ok = bool(verdicts) and all(v["ok"] for v in verdicts)
    parity_mismatches: list[str] | None = None
    if args.compare_gate:
        try:
            cli_doc = json.loads(args.compare_gate.read_text("utf-8"))
        except Exception as exc:
            print(f"drift_verify.py: cannot read --compare-gate {args.compare_gate}: {exc}", file=sys.stderr)
            return 2
        parity_mismatches = compare_gate_parity(cli_doc, verdicts, ok)
    _render_verdicts(verdicts, ok, policy, args.json, parity_mismatches)
    if parity_mismatches:
        return 2
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
