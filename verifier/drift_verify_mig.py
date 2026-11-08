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
        cands = sorted(p.glob(f"*{suffix}")) if p.is_dir() else ([p] if p.is_file() and p.name.endswith(suffix) else [])
        for f in cands:
            if f not in seen:
                seen.add(f)
                out.append(f)
    return out


def load_migration_receipts_core(events_paths: list[Path], decode_fn: Any, valid_rel_scope_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
    out, errs = [], []
    for mf in collect_receipt_files(events_paths, ".migration.json"):
        try:
            doc = decode_fn(mf.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or set(doc) != MIG_KEYS or doc.get("schema") != "drift.migration-receipt/1":
                raise ValueError("mig_keys")
            cid, dig, res = str(doc.get("contract", "")), str(doc.get("digest", "")), str(doc.get("resource", ""))
            mid, ph, tool = str(doc.get("migration_id", "")), str(doc.get("phase", "")), str(doc.get("tool", ""))
            tref, sref, csnap, emref, outc = str(doc.get("tool_ref", "")), str(doc.get("subject_ref", "")), str(doc.get("code_snapshot", "")), str(doc.get("epoch_manifest_ref", "")), str(doc.get("outcome", ""))
            if not cid or not dig or not res.strip() or not mid.strip() or ph not in MIG_PHASES or not tool.strip() or not SHA256_REF_RE.match(tref) or not SHA256_REF_RE.match(sref) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", csnap) or not SHA256_REF_RE.match(emref) or outc not in ("passed", "violated", "inconclusive"):
                raise ValueError("mig_envelope")
            cov, cs = doc.get("covered_scope"), doc.get("cases")
            if not isinstance(cov, list) or not cov or len(set(cov)) != len(cov) or not all(valid_rel_scope_fn(x) for x in cov):
                raise ValueError("covered_scope")
            if not isinstance(cs, list) or not cs or not all(isinstance(x, str) and x.strip() for x in cs):
                raise ValueError("cases")
            ec, dc, osaf = doc.get("epoch_compatibility"), doc.get("data_correctness"), doc.get("operational_safety")
            if not isinstance(ec, dict) or not isinstance(dc, dict) or not isinstance(osaf, dict):
                raise ValueError("mig_tables")
            act_ep = [str(x) for x in ec.get("active_epochs", []) if isinstance(x, str) and x.strip()]
            cmp_ep = [str(x) for x in ec.get("compatible_epochs", []) if isinstance(x, str) and x.strip()]
            inc_ep = ec.get("incompatible_epochs", [])
            if not isinstance(inc_ep, list) or any(not isinstance(ie, dict) or set(ie) != {"epoch", "operation", "detail"} for ie in inc_ep):
                raise ValueError("incompatible_epochs")
            inv_chk = [str(x) for x in dc.get("invariants_checked", []) if isinstance(x, str) and x.strip()]
            rows_v, viols = dc.get("rows_verified"), dc.get("violations")
            if not isinstance(rows_v, int) or isinstance(rows_v, bool) or rows_v < 0 or not isinstance(viols, int) or isinstance(viols, bool) or viols < 0:
                raise ValueError("data_correctness")
            lmode, mlock, lbud, dms, dbud, cref = str(osaf.get("lock_mode", "")), osaf.get("max_lock_ms"), osaf.get("lock_budget_ms"), osaf.get("duration_ms"), osaf.get("duration_budget_ms"), str(osaf.get("context_ref", ""))
            if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in (mlock, lbud, dms, dbud)):
                raise ValueError("operational_safety")
            out.append({
                "schema": "drift.migration-receipt/1", "contract": cid, "digest": dig, "resource": res, "migration_id": mid, "phase": ph, "tool": tool, "tool_ref": tref, "subject_ref": sref, "code_snapshot": csnap, "epoch_manifest_ref": emref, "covered_scope": sorted(set(cov)), "cases": sorted(set(cs)),
                "epoch_compatibility": {"active_epochs": sorted(set(act_ep)), "compatible_epochs": sorted(set(cmp_ep)), "incompatible_epochs": [{"detail": str(x["detail"]), "epoch": str(x["epoch"]), "operation": str(x["operation"])} for x in inc_ep]},
                "data_correctness": {"invariants_checked": sorted(set(inv_chk)), "rows_verified": rows_v, "violations": viols},
                "operational_safety": {"context_ref": cref, "duration_budget_ms": dbud, "duration_ms": dms, "lock_budget_ms": lbud, "lock_mode": lmode, "max_lock_ms": mlock},
                "outcome": outc,
            })
        except Exception as exc:
            errs.append(f"{mf.name}: {exc}")
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
    if not by_target and not (req_mig and res_set):
        return [], []
    if not by_target and req_mig and res_set:
        return ["migration.missing"], []
    eval_list, reasons, has_viol, has_inc = [], [], False, False
    for tkey in sorted(by_target):
        bucket = by_target[tkey]
        group = [bucket[k] for k in sorted(bucket)]
        has_conflict = len(group) > 1
        grp_viol, grp_evals = False, []
        for rec in group:
            eff, rsn = rec["outcome"], ""
            r_res = rec["resource"].strip()
            res_ok = bool(r_res) and (r_res in res_set or ("#" in r_res and r_res.split("#", 1)[0].strip() in res_set))
            ec, dc, osaf = rec["epoch_compatibility"], rec["data_correctness"], rec["operational_safety"]
            if not res_ok or not scope_code or not all(any(cov_matches_fn(c, sc) for c in rec["covered_scope"]) for sc in scope_code) or not active_cases or not all(c in active_cases for c in rec["cases"]):
                eff, rsn = ("inconclusive" if eff == "passed" else eff), "migration.incomplete_scope"
            elif expected_snapshot and rec["code_snapshot"] != expected_snapshot:
                eff, rsn = ("inconclusive" if eff == "passed" else eff), "migration.snapshot_mismatch"
            elif expected_subject_ref and rec["subject_ref"] != expected_subject_ref:
                eff, rsn = ("inconclusive" if eff == "passed" else eff), "migration.subject_mismatch"
            elif ec["incompatible_epochs"]:
                eff, rsn = "violated", "migration.epoch_incompatible"
            elif dc["violations"] > 0:
                eff, rsn = "violated", "migration.data_invariant_violated"
            elif osaf["lock_budget_ms"] > 0 and osaf["duration_budget_ms"] > 0 and (osaf["max_lock_ms"] > osaf["lock_budget_ms"] or osaf["duration_ms"] > osaf["duration_budget_ms"]):
                eff, rsn = "violated", "migration.lock_budget_exceeded"
            elif not ec["active_epochs"] or not set(ec["active_epochs"]).issubset(set(ec["compatible_epochs"])):
                eff, rsn = ("inconclusive" if eff == "passed" else eff), "migration.epoch_incomplete"
            elif not inv_keys.issubset(set(dc["invariants_checked"])) or (rec["phase"] == "backfill" and dc["rows_verified"] <= 0):
                eff, rsn = ("inconclusive" if eff == "passed" else eff), "migration.invariants_incomplete"
            elif not osaf["lock_mode"] or osaf["lock_budget_ms"] <= 0 or osaf["duration_budget_ms"] <= 0 or not SHA256_REF_RE.match(osaf["context_ref"]):
                eff, rsn = ("inconclusive" if eff == "passed" else eff), "migration.operational_unmeasured"
            elif eff == "violated" and not rsn:
                rsn = "migration.violated"
            if eff == "violated":
                grp_viol = True
            grp_evals.append((rec, eff, rsn))
        for rec, eff0, rsn0 in grp_evals:
            eff, rsn = eff0, rsn0
            if has_conflict:
                if grp_viol:
                    eff = "violated"
                    rsn = rsn0 if (rsn0 and rsn0 != "migration.violated") else "migration.conflicting_receipts"
                else:
                    eff, rsn = "inconclusive", "migration.conflicting_receipts"
            item = {**rec, "effective_outcome": eff, "provenance": "measured"}
            if rsn:
                item["reason"] = rsn
            eval_list.append(item)
            if eff == "violated":
                has_viol = True
                if rsn and rsn not in reasons:
                    reasons.append(rsn)
                if has_conflict and "migration.conflicting_receipts" not in reasons:
                    reasons.append("migration.conflicting_receipts")
            elif eff != "passed":
                has_inc = True
                if rsn and rsn not in reasons:
                    reasons.append(rsn)
    if has_viol and "migration.violated" not in reasons:
        reasons.append("migration.violated")
    if has_inc and not has_viol and "migration.inconclusive" not in reasons:
        reasons.append("migration.inconclusive")
    return reasons, eval_list


def run_mig_parity_self_test(ck: dict[str, Any], digest_matches_fn: Any) -> None:
    from drift_verify_ssh import evaluate_contract_parity_impl
    h1, h2, h3 = "sha256:" + "1" * 64, "sha256:" + "2" * 64, "sha256:" + "3" * 64
    p_ck = {**ck, "scope_reads": ["db#orders"], "scope_writes": ["db#users"], "scope_code": ["src/svc.py"], "invariants": [], "cutover": {"legacy_target": "leg", "candidate_target": "cand", "normalization_ref": h1, "corpus_ref": h1, "requirement_ref": ck["digest"], "migration_ids": ["mig-1"], "rollback_readback": "required", "enforce": "always"}}
    p_rec = {"schema": "drift.parity-receipt/1", "contract": "svc", "digest": ck["digest"], "requirement_ref": ck["digest"], "legacy_target": "leg", "candidate_target": "cand", "legacy_subject_ref": h1, "candidate_subject_ref": h2, "normalization_ref": h1, "corpus_ref": h1, "legacy_cases": ["ok"], "candidate_cases": ["ok"], "diverged_observations": [], "effect_violations": [], "frame_verified": True, "rollback_readback": "verified", "outcome": "passed"}
    rsn_miss, _ = evaluate_contract_parity_impl(p_ck, [p_rec], "release", digest_matches_fn, h2, set(), [])
    rsn_sub, _ = evaluate_contract_parity_impl(p_ck, [p_rec], "release", digest_matches_fn, h3, set(), [])
    assert "parity.migration_unverified" in rsn_miss and "parity.subject_mismatch" in rsn_sub



ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DIGEST_RE = re.compile(r"^dr1:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})$")
THEN_MUT_OPS = frozenset(("negate", "add-one", "minus-one", "set-one", "multiply-two", "divide-two", "append-tilde", "drop-last", "seed-array", "swap-peer-then", "zero-sum-shear"))
WHEN_MUT_OPS = frozenset(("swap-case-when", "perturb-case-when"))


def validate_mutation_manifest_core(text: str, decode_fn: Any) -> dict[str, Any]:
    import hashlib
    doc = decode_fn(text)
    if not isinstance(doc, dict) or set(doc) != {"version", "contracts"} or doc.get("version") != 1 or isinstance(doc.get("version"), bool) or not isinstance(cs := doc["contracts"], list) or not cs:
        raise ValueError("manifest")
    by_id, targets, prev_c = {}, {}, ""
    for c in cs:
        if not isinstance(c, dict) or set(c) != {"id", "digest", "mutants"}:
            raise ValueError("contract")
        cid, cdig, muts = c["id"], c["digest"], c["mutants"]
        if not isinstance(cid, str) or not ID_RE.match(cid) or not isinstance(cdig, str) or not DIGEST_RE.match(cdig) or not isinstance(muts, list) or (prev_c and cid <= prev_c):
            raise ValueError("contract")
        prev_c, prev_m, m_list = cid, "", []
        for m in muts:
            if not isinstance(m, dict) or any(k not in ("id", "case", "path", "operator", "before", "after", "witness") for k in m) or any(r not in m for r in ("id", "case", "path", "operator", "before", "after")):
                raise ValueError("mutant")
            mid, mc, mp, mop = m["id"], m["case"], m["path"], m["operator"]
            if not all(isinstance(x, str) for x in (mid, mc, mp, mop)) or not ID_RE.match(mc) or mid != f"{mc}:{mp}" or (prev_m and mid <= prev_m):
                raise ValueError("mutant")
            esc = mc.replace("~", "~0").replace("/", "~1")
            tp, wp = f"/cases/{esc}/then/", f"/cases/{esc}/when/"
            if not ((mp.startswith(tp) and len(mp) > len(tp) and mop in THEN_MUT_OPS) or (mp.startswith(wp) and len(mp) > len(wp) and mop in WHEN_MUT_OPS)):
                raise ValueError("mutant")
            prev_m = mid
            targets[(cid, mid)] = rec = {"id": mid, "contract": cid, "digest": cdig, "case": mc, "path": mp}
            m_list.append(rec)
        by_id[cid] = {"id": cid, "digest": cdig, "mutants": m_list}
    return {"digest": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(), "contracts": by_id, "targets": targets}


def run_sec_self_test_core(ck: dict[str, Any], digest_matches_fn: Any, eval_sec_fn: Any) -> None:
    import tempfile, drift_verify as _dv
    run_mig_parity_self_test(ck, digest_matches_fn)
    sec_ck = {**ck, "profile_security": ["sast"], "scope_code": ["src/api.rs#authorize"]}
    base_rec = {"category": "sast", "tool": "semgrep", "tool_ref": "sha256:" + "1" * 64, "ruleset_ref": "sha256:" + "2" * 64, "contract": "svc", "digest": ck["ref"], "code_snapshot": "a" * 40, "covered_scope": ["src/api.rs#authorize"], "cases": ["ok"], "outcome": "passed"}
    assert eval_sec_fn(sec_ck, [base_rec], {}, "a" * 40, digest_matches_fn)[0] == []
    for bad in ({"covered_scope": ["src/api.rs#unrelated"]}, {"cases": ["nonexistent"]}):
        assert "security.inconclusive" in eval_sec_fn(sec_ck, [{**base_rec, **bad}], {}, "a" * 40, digest_matches_fn)[0]
    assert "security.inconclusive" in eval_sec_fn(sec_ck, [base_rec], {}, "", digest_matches_fn)[0]
    r_viol = {**base_rec, "ruleset_ref": "sha256:" + "3" * 64, "outcome": "violated"}
    c1 = eval_sec_fn(sec_ck, [r_viol, base_rec], {}, "a" * 40, digest_matches_fn)
    c2 = eval_sec_fn(sec_ck, [base_rec, r_viol], {}, "a" * 40, digest_matches_fn)
    assert c1 == c2 and "security.inconclusive" in c1[0] and all(x.get("reason") == "security.conflicting_receipts" for x in c1[1])
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td)
        (tp / "p@1.toml").write_text('drift = "0.2"\nprofile = "p@1"\n[vocabulary]\nwhen = ["op"]\nthen = ["status", "inv_p"]\n[projections.then]\nstatus = "/status"\ninv_p = "/ip"\n[concepts."orders.c"]\nmeans = "Cancel order."\n', "utf-8")
        for fn_n, u_c in (("c1.toml", 'concepts = ["orders.c"]\n'), ("c2.toml", "")):
            (tp / fn_n).write_text(f'drift = "0.2"\nid = "c"\nintent = "C."\n[use]\nprofile = "p@1"\n{u_c}[scope]\nwrites = []\nreads = []\nindirect = "none"\n[invariants]\ninv_p = 1\n[cases.ok]\nwhen.op = "x"\nthen.status = 200\n', "utf-8")
        assert _dv.verify_contract_toml(tp / "c1.toml", tp)["digest"] == _dv.verify_contract_toml(tp / "c2.toml", tp)["digest"]

