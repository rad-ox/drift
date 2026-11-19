#!/usr/bin/env python3
"""DRIFT Independent Reference Security Evidence Verifier (MIT License)."""

from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Callable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from drift_verify_base import (
    DIGEST_RE,
    ID_RE,
    SHA256_REF_RE,
    SNAPSHOT_RE,
    _cov_matches,
    _req_str as _sec_str,
    _valid_rel_scope,
    collect_receipt_files,
)
from drift_verify_formal import (
    evaluate_contract_formal_core,
    extract_contract_formal,
    load_formal_receipts_impl,
    validate_formal_equivalence_core,
)
from drift_verify_mig import evaluate_contract_migration_core, load_migration_receipts_core
from drift_verify_mutation import validate_mutation_manifest_impl
from drift_verify_subject import (
    SEC_CATEGORIES,
    parse_security_lock_impl,
    parse_subject_manifest_impl,
    verify_tool_pin_cli_core,
)

SEC_OUTCOMES = frozenset(("passed", "violated", "inconclusive"))
SEC_REQ_KEYS = frozenset(("kind", "category", "tool", "tool_ref", "ruleset_ref", "contract", "digest", "code_snapshot", "covered_scope", "cases", "outcome"))
SEC_KEYS = SEC_REQ_KEYS | frozenset(("subject_ref", "artifact_ref", "reproducer"))


def _receipt_identity_key(r: dict[str, Any]) -> tuple[Any, ...]:
    return (r["category"], r["tool"], r["tool_ref"], r["ruleset_ref"], r["code_snapshot"], r.get("subject_ref", ""), r.get("artifact_ref", ""), tuple(r["covered_scope"]), tuple(r["cases"]), r["outcome"])


def load_security_receipts_impl(events_paths: list[Path], decode_fn: Callable[[str], Any]) -> tuple[list[dict[str, Any]], list[str]]:
    out, errs = [], []
    for sf in collect_receipt_files(events_paths, ".security.json"):
        try:
            doc = decode_fn(sf.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or not SEC_REQ_KEYS.issubset(doc) or any(k not in SEC_KEYS for k in doc) or doc.get("kind") != "security_check":
                raise ValueError("sec_keys")
            cat, tool, tref, rref = _sec_str(doc, "category"), _sec_str(doc, "tool"), _sec_str(doc, "tool_ref"), _sec_str(doc, "ruleset_ref")
            cid, dig, csnap, outc = _sec_str(doc, "contract"), _sec_str(doc, "digest"), _sec_str(doc, "code_snapshot"), _sec_str(doc, "outcome")
            sref = _sec_str(doc, "subject_ref") if "subject_ref" in doc else ""
            aref = _sec_str(doc, "artifact_ref") if "artifact_ref" in doc else ""
            if cat not in SEC_CATEGORIES or not SHA256_REF_RE.match(tref) or not SHA256_REF_RE.match(rref) or not ID_RE.match(cid) or not DIGEST_RE.match(dig) or not SNAPSHOT_RE.match(csnap) or outc not in SEC_OUTCOMES or (sref and not SHA256_REF_RE.match(sref)) or (aref and not SHA256_REF_RE.match(aref)):
                raise ValueError("sec_fields")
            cov, cs = doc.get("covered_scope"), doc.get("cases")
            if not isinstance(cov, list) or not cov or len(set(cov)) != len(cov) or not all(_valid_rel_scope(x) for x in cov):
                raise ValueError("covered_scope")
            if not isinstance(cs, list) or not cs or not all(isinstance(x, str) and ID_RE.match(x) for x in cs):
                raise ValueError("cases")
            rec: dict[str, Any] = {"category": cat, "tool": tool, "tool_ref": tref, "ruleset_ref": rref, "contract": cid, "digest": dig, "code_snapshot": csnap, "covered_scope": sorted(set(cov)), "cases": sorted(set(cs)), "outcome": outc}
            if sref:
                rec["subject_ref"] = sref
            if aref:
                rec["artifact_ref"] = aref
            if "reproducer" in doc:
                rec["reproducer"] = doc["reproducer"]
            out.append(rec)
        except Exception as exc:
            errs.append(f"{sf.name}: {exc}")
    return out, errs


def classify_sec_reproducer_core(repro: Any, raw_cases: dict[str, Any], active_cases: set[str]) -> str:
    if repro is None:
        return ""
    if not isinstance(repro, dict) or not isinstance(wit := repro.get("witness"), dict):
        return "unreproducible"
    wm, tm = wit.get("when"), wit.get("then")
    if not isinstance(wm, dict) or not wm or not isinstance(tm, dict) or not tm:
        return "unreproducible"
    cid = repro.get("case", "")
    if not isinstance(cid, str) or cid not in active_cases or not (cw := (raw_cases.get(cid) or {}).get("when") or {}):
        return "draft_case_required"
    for wk, wv in cw.items():
        if wk not in wm:
            return "draft_case_required"
        av = wm[wk]
        if isinstance(wv, dict):
            if ("eq" in wv and av != wv["eq"]) or ("in" in wv and av not in wv["in"]) or ("not_in" in wv and av in wv["not_in"]) or ("min" in wv and (not isinstance(av, int) or isinstance(av, bool) or av < wv["min"])) or ("max" in wv and (not isinstance(av, int) or isinstance(av, bool) or av > wv["max"])):
                return "draft_case_required"
        elif av != wv:
            return "draft_case_required"
    return "bound_cex"


def check_sec_stage1_core(rec: dict[str, Any], expected_snapshot: str, exp_sub: dict[str, Any]) -> tuple[bool, str]:
    if not expected_snapshot or rec["code_snapshot"] != expected_snapshot:
        return False, "security.snapshot_mismatch"
    esr, ear = exp_sub.get("subject_ref", ""), exp_sub.get("binary_ref", "")
    if esr and rec.get("subject_ref") and rec["subject_ref"] != esr:
        return False, "security.subject_mismatch"
    if exp_sub.get("artifact_mismatch") or (ear and rec.get("artifact_ref") and rec["artifact_ref"] != ear):
        return False, "security.artifact_mismatch"
    slock = exp_sub.get("security_lock") or {}
    if slock.get("active"):
        pin = (slock.get("tools") or {}).get(f"{rec['category']}:{rec['tool']}")
        if not pin or rec["tool_ref"] != pin["tool_ref"]:
            return False, "security.tool_unpinned"
        if rec["ruleset_ref"] != pin["ruleset_ref"]:
            return False, "security.ruleset_stale"
    return True, ""


def evaluate_contract_security_impl(contract: dict[str, Any], sec_receipts: list[dict[str, Any]], policy: dict[str, Any] | None, expected_snapshot: str, digest_matches_fn: Callable[[str, str], bool], expected_subject: dict[str, Any] | None = None, allow_exec_reuse: bool = False, base_contract: dict[str, Any] | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    pol, exp_sub = policy or {}, expected_subject or {}
    req_cats = set(contract.get("profile_security") or [])
    if pol.get("pack") == "core@1" and isinstance(pol.get("security"), list):
        req_cats.update(str(x) for x in pol["security"] if isinstance(x, str))
    scope_code, raw_cases = contract.get("scope_code") or [], contract.get("cases") or {}
    base_cases, base_dig = (base_contract or {}).get("cases") or {}, (base_contract or {}).get("digest", "")
    active_cases = {cid for cid, cm in raw_cases.items() if isinstance(cm, dict) and "status" not in cm}
    current_by_key: dict[tuple[str, str], dict[tuple[Any, ...], dict[str, Any]]] = {}
    base_by_key: dict[tuple[str, str], dict[tuple[Any, ...], dict[str, Any]]] = {}
    for r in sec_receipts:
        if r["contract"] != contract["id"]:
            continue
        tkey = (r["category"], r["tool"])
        if digest_matches_fn(r["digest"], contract["digest"]):
            current_by_key.setdefault(tkey, {})[_receipt_identity_key(r)] = r
        elif allow_exec_reuse and base_dig and digest_matches_fn(r["digest"], base_dig) and all(cid in base_cases and {k: v for k, v in (raw_cases.get(cid) or {}).items() if k != "note"} == {k: v for k, v in (base_cases.get(cid) or {}).items() if k != "note"} for cid in r["cases"] if cid in active_cases):
            base_by_key.setdefault(tkey, {})[_receipt_identity_key(r)] = r
    all_keys = sorted(set(current_by_key) | set(base_by_key))
    if not all_keys and not req_cats:
        return [], []
    eval_list, cat_states, has_viol, spec_rsns = [], {}, False, []
    for key in all_keys:
        is_cur = key in current_by_key
        src_map = current_by_key[key] if is_cur else base_by_key[key]
        prov = "measured" if is_cur else "reused"
        group = [src_map[rk] for rk in sorted(src_map)]
        s1_ok, s1_bad, bad_viol = [], [], False
        for rec in group:
            rdisp = classify_sec_reproducer_core(rec.get("reproducer"), raw_cases, active_cases)
            ok1, rsn1 = check_sec_stage1_core(rec, expected_snapshot, exp_sub)
            if ok1:
                s1_ok.append((rec, rdisp))
            else:
                keep_v = rec["outcome"] == "violated" and rsn1 not in ("security.subject_mismatch", "security.artifact_mismatch")
                if keep_v:
                    bad_viol = True
                it = {**rec, "kind": "security_check", "effective_outcome": "violated" if keep_v else "inconclusive", "provenance": prov, "reason": rsn1}
                if rdisp:
                    it["reproducer_disposition"] = rdisp
                s1_bad.append(it)
        if not s1_ok:
            if len(s1_bad) > 1:
                for it in s1_bad:
                    it["effective_outcome"] = "violated" if (bad_viol and it["effective_outcome"] == "violated") else "inconclusive"
                    it["reason"] = "security.conflicting_receipts"
            grp_evals = s1_bad
        else:
            grp_evals, grp_viol = [], False
            for rec, rdisp in s1_ok:
                eff_out, rsn = rec["outcome"], ""
                valid_cs = bool(active_cases) and all(c in active_cases for c in rec["cases"])
                full_sc = bool(scope_code) and all(any(_cov_matches(c, sc) for c in rec["covered_scope"]) for sc in scope_code)
                if not valid_cs:
                    if eff_out != "violated":
                        eff_out, rsn = "inconclusive", "security.incomplete_scope"
                elif not full_sc:
                    if eff_out == "violated" and (not scope_code or any(_cov_matches(c, sc) for sc in scope_code for c in rec["covered_scope"])):
                        eff_out = "violated"
                    elif eff_out != "violated":
                        eff_out, rsn = "inconclusive", "security.incomplete_scope"
                if eff_out == "violated":
                    grp_viol = True
                it = {**rec, "kind": "security_check", "effective_outcome": eff_out, "provenance": prov}
                if rdisp:
                    it["reproducer_disposition"] = rdisp
                if rsn:
                    it["reason"] = rsn
                grp_evals.append(it)
            if len(grp_evals) > 1:
                for it in grp_evals:
                    it["effective_outcome"] = "violated" if (grp_viol and it["effective_outcome"] == "violated") else "inconclusive"
                    it["reason"] = "security.conflicting_receipts"
        for item in grp_evals:
            eval_list.append(item)
            eff_out, rsn = item["effective_outcome"], item.get("reason", "")
            if rsn in ("security.subject_mismatch", "security.artifact_mismatch", "security.tool_unpinned", "security.ruleset_stale") and rsn not in spec_rsns:
                spec_rsns.append(rsn)
            if eff_out == "violated":
                has_viol = True
                cat_states[item["category"]] = "violated"
            elif eff_out == "inconclusive" and cat_states.get(item["category"]) != "violated":
                cat_states[item["category"]] = "inconclusive"
            elif eff_out == "passed" and cat_states.get(item["category"]) not in ("violated", "inconclusive"):
                cat_states[item["category"]] = "reused" if (prov == "reused" or cat_states.get(item["category"]) == "reused") else "passed"
    reasons = ["security.violated"] if has_viol else []
    if exp_sub.get("artifact_mismatch") and "security.artifact_mismatch" not in spec_rsns:
        spec_rsns.append("security.artifact_mismatch")
    for sr in spec_rsns:
        if sr not in reasons:
            reasons.append(sr)
    has_inc, has_miss = False, False
    for rc in sorted(req_cats):
        st = cat_states.get(rc, "missing")
        if st == "violated" and "security.violated" not in reasons:
            reasons.append("security.violated")
        elif st == "inconclusive":
            has_inc = True
        elif st == "missing":
            has_miss = True
    if has_inc:
        reasons.append("security.inconclusive")
    if has_miss:
        reasons.append("security.missing")
    return reasons, eval_list


def validate_formal_equivalence(rec: dict[str, Any], ob_ver: str, ob_pkind: str, ob_minev: str, raw_cases: dict[str, Any]) -> str:
    return validate_formal_equivalence_core(rec, ob_ver, ob_pkind, ob_minev, raw_cases)


def evaluate_contract_formal_impl(
    contract: dict[str, Any],
    formal_receipts: list[dict[str, Any]],
    phase: str,
    expected_subject_ref: str,
    expected_snapshot: str,
    shard_subject_refs: set[str],
    area_root: Path | None,
    manifest_sources: dict[str, str] | None,
    digest_matches_fn: Callable[[str, str], bool],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    return evaluate_contract_formal_core(contract, formal_receipts, phase, expected_subject_ref, expected_snapshot, shard_subject_refs, area_root, manifest_sources, digest_matches_fn)


def load_migration_receipts_impl(events_paths: list[Path], decode_fn: Callable[[str], Any]) -> tuple[list[dict[str, Any]], list[str]]:
    return load_migration_receipts_core(events_paths, decode_fn, _valid_rel_scope)


def evaluate_contract_migration_impl(contract: dict[str, Any], mig_receipts: list[dict[str, Any]], policy: dict[str, Any] | None, expected_snapshot: str, expected_subject_ref: str, digest_matches_fn: Callable[[str, str], bool]) -> tuple[list[str], list[dict[str, Any]]]:
    return evaluate_contract_migration_core(contract, mig_receipts, policy, expected_snapshot, expected_subject_ref, digest_matches_fn, _cov_matches)


def verify_tool_pin_cli(argv: list[str]) -> int:
    return verify_tool_pin_cli_core(argv, parse_security_lock_impl)


if __name__ == "__main__":
    sys.exit(verify_tool_pin_cli(sys.argv[1:]))
