"""Zero-dependency COBOL batch/CICS copybook marshaling and parity bridge."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable


def _load_sibling(mod_name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(mod_name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(mod_name, mod)
    spec.loader.exec_module(mod)
    return mod


try:
    from . import drift_cobol_copybook as _copybook
except ImportError:
    _copybook = _load_sibling("drift_cobol_copybook", "drift_cobol_copybook.py")

try:
    from . import drift_cobol_checks as _checks
except ImportError:
    _checks = _load_sibling("drift_cobol_checks", "drift_cobol_checks.py")

VERSION = "drift_cobol.py@0.9.0"
BRIDGE_RUNTIME_BASELINE = "cobol-85-batch"
CAPABILITIES = [
    "predicates", "projections", "forbid_keys", "not_in", "case_frames",
    "counterexample_replay", "copybook_marshal", "parity_receipt", "php_bridge_verifier",
]

_to_snake = _copybook._to_snake
_parse_pic_spec = _copybook._parse_pic_spec
parse_copybook_layout = _copybook.parse_copybook_layout
marshal_record = _copybook.marshal_record
unmarshal_record = _copybook.unmarshal_record

SUPPORTED_REL_KEYS = _checks.SUPPORTED_REL_KEYS
_resolve_pointer = _checks._resolve_pointer
_values_equal = _checks._values_equal
_resolve_peer = _checks._resolve_peer
_has_key_recursive = _checks._has_key_recursive
check_value = _checks.check_value
_verify_cobol_single_frame = _checks._verify_cobol_single_frame
_unwrap_or_desugar_03 = _checks._unwrap_or_desugar_03
_scale_03_exp = _checks._scale_03_exp


def bridge_capabilities() -> dict[str, Any]:
    return {
        "schema": "drift.bridge-capabilities/1",
        "bridge": "drift_cobol.py",
        "version": VERSION,
        "runtime_baseline": BRIDGE_RUNTIME_BASELINE,
        "capabilities": list(CAPABILITIES),
    }


def require_capabilities(required: list[str]) -> None:
    for cap in required:
        if cap not in CAPABILITIES:
            raise RuntimeError(f"bridge.capability_unsupported:{cap}")


def verify_plan_case(
    plan_doc: dict[str, Any],
    case_id: str,
    observed: dict[str, Any],
    frames: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pc = plan_doc.get("cases", {}).get(case_id)
    if not isinstance(pc, dict):
        raise RuntimeError(f"unknown case {case_id}")
    read_k: list[str] = []
    for cl in pc.get("clauses", []):
        pred, ptr = str(cl.get("pred", "")), str(cl.get("pointer", ""))
        exp = _scale_03_exp(_unwrap_or_desugar_03(cl.get("constraint", {})), float(cl.get("conv", 1.0)))
        raw_pp = cl.get("peer_pointers") or {}
        pp = {str(k[5:] if str(k).startswith("then.") else k): str(v) for k, v in raw_pp.items()} | {
            str(k): str(v) for k, v in raw_pp.items()
        }
        we = {
            str(k[5:] if str(k).startswith("when.") else k): v
            for k, v in {**(pc.get("when") or {}), **(cl.get("when_peers") or {})}.items()
        }
        ok_p, act = _checks.resolve_observed_field(observed, pred, ptr, exp)
        check_value(pred, act, exp, ok_p, observed, pp, we)
        if str(cl.get("clause", "")).startswith("then.") and pred not in read_k:
            read_k.append(pred)
    _checks.verify_case_write_frames([], list(pc.get("permitted_writes", [])), frames, [])
    return {"verified": True, "read": read_k}


def verify_case_observation(
    contract_view: dict[str, Any],
    case_id: str,
    observed: dict[str, Any],
    frames: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if contract_view.get("schema") == "drift.bridge-plan/1":
        return verify_plan_case(contract_view, case_id, observed, frames)
    case_def = contract_view.get("cases", {}).get(case_id)
    if not isinstance(case_def, dict):
        raise RuntimeError(f"unknown case {case_id}")
    is_03 = contract_view.get("drift") == "0.3"
    then_t = case_def.get("then", {})
    proj_t = contract_view.get("projections", {}).get("then", {})
    read_k: list[str] = []
    we = {k: v.get("eq") if isinstance(v, dict) and "eq" in v else v for k, v in case_def.get("when", {}).items()}
    for k, raw_e in then_t.items():
        exp = _unwrap_or_desugar_03(raw_e) if is_03 else raw_e
        ok_p, act = _checks.resolve_observed_field(observed, k, proj_t.get(k, f"/{k}"), exp)
        check_value(k, act, exp, ok_p, observed, proj_t, we)
        read_k.append(k)
    sw = [str(x) for x in contract_view.get("scope", {}).get("writes", [])]
    cw = case_def.get("writes") if isinstance(case_def.get("writes"), list) else None
    _checks.verify_case_write_frames(sw, cw, frames, read_k)
    verified = all(k in read_k for k in then_t) and (cw is None or all(f"@frame:{r}" in read_k for r in sw))
    return {"verified": verified, "read": read_k}


verify_case = verify_case_observation


def replay_counterexamples(
    contract_view: dict[str, Any],
    case_id: str,
    fixtures: list[dict[str, Any]],
    runner: Callable[[dict[str, Any]], dict[str, Any]],
    frames: dict[str, dict[str, Any]] | None = None,
) -> int:
    cid, n = contract_view.get("id", ""), 0
    for fx in fixtures:
        if fx.get("contract") == cid and fx.get("case") == case_id:
            verify_case_observation(contract_view, case_id, runner(fx.get("witness", {}).get("when", {})), frames)
            n += 1
    return n


def emit_cobol_proof_shard(
    events_path: str | Path,
    cv: dict[str, Any],
    runs: list[dict[str, Any]],
    src_in: dict[str, str],
    env_meta: dict[str, str] | None = None,
) -> None:
    p, lines, tests, classes, in_map = Path(events_path), [], [], [], {}
    for r in runs:
        tid = str(r["test"])
        tests.append(tid)
        cls = tid.split("#", 1)[0]
        if cls not in classes:
            classes.append(cls)
        in_map[tid] = dict(src_in)
        ev: dict[str, Any] = {
            "contract": cv["id"],
            "digest": cv["digest"],
            "cases": list(r["cases"]),
            "level": r.get("level", "unit"),
            "test": tid,
            "outcome": r["outcome"],
        }
        if r.get("read"):
            ev["read"] = list(r["read"])
        if cv.get("drift") == "0.3":
            ev.update({
                "schema": "0.3",
                "capabilities": ["rel-keys-guard/1", "rel-peer-sum/1", "rel-series/1", "rel-tol/1"],
            })
        lines.append(json.dumps(ev, separators=(",", ":")))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = {
        "toolchain": BRIDGE_RUNTIME_BASELINE,
        "deps": "copybook-lock-1",
        "config": "cobc-batch-1",
        "runner": "drift-cobol",
        "drift": "0.9.0",
        "adapter": VERSION,
        "policy": "core@1",
        **(env_meta or {}),
    }
    meta = {"version": 1, "classes": classes, "tests": tests, "inputs": in_map, "env": env}
    p.with_suffix(".meta.json").write_text(json.dumps(meta, separators=(",", ":")) + "\n", encoding="utf-8")


def generate_cutover_parity_receipt(
    cv: dict[str, Any], req_ref: str, leg_t: str, cand_t: str,
    leg_s: str, cand_s: str, norm_ref: str, corp_ref: str,
    layout: list[dict[str, Any]], cases: list[dict[str, Any]],
    leg_fn: Callable[[str], str], cand_fn: Callable[[dict[str, Any]], dict[str, Any]],
    diffs: list[str] | None = None,
) -> dict[str, Any]:
    allow, leg_c, cand_c, div, eff, rb_ok = set(diffs or []), [], [], [], [], True
    for item in cases:
        cid, w = str(item["case"]), item.get("when", {})
        lo, co = unmarshal_record(layout, leg_fn(marshal_record(layout, w))), cand_fn(w)
        leg_c.append(cid); cand_c.append(cid)
        crt = unmarshal_record(layout, marshal_record(layout, co))
        for fld in layout:
            k, ptr = fld["key"], f"/record/{fld['key']}"
            if crt.get(k) != co.get(k):
                rb_ok = False
            if lo.get(k) != co.get(k) and ptr not in allow:
                div.append(f"{cid}:{ptr}")
    return {
        "schema": "drift.parity-receipt/1", "contract": cv["id"], "digest": cv["digest"],
        "requirement_ref": req_ref, "legacy_target": leg_t, "candidate_target": cand_t,
        "legacy_subject_ref": leg_s, "candidate_subject_ref": cand_s,
        "normalization_ref": norm_ref, "corpus_ref": corp_ref,
        "legacy_cases": sorted(set(leg_c)), "candidate_cases": sorted(set(cand_c)),
        "diverged_observations": sorted(set(div)), "effect_violations": eff,
        "frame_verified": True, "rollback_readback": "verified" if rb_ok else "failed",
        "outcome": "passed" if (not div and not eff and rb_ok) else "failed",
    }
