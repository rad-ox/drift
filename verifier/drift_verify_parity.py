#!/usr/bin/env python3
"""Cutover parity receipts (drift.parity-receipt/1) and federated composition (drift.composition-manifest/1)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from drift_verify_base import ARTIFACT_REF_RE, ID_RE, collect_receipt_files, sub_use_text_params

PARITY_KEYS = frozenset((
    "schema", "contract", "digest", "requirement_ref", "legacy_target", "candidate_target",
    "legacy_subject_ref", "candidate_subject_ref", "normalization_ref", "corpus_ref",
    "legacy_cases", "candidate_cases", "diverged_observations", "effect_violations",
    "frame_verified", "rollback_readback", "outcome",
))


def extract_contract_cutover(raw: dict[str, Any], use_tbl: Any, dr1_digest_fn: Callable[[Any], str]) -> tuple[dict[str, Any], bool]:
    c_raw = raw.get("cutover")
    if not isinstance(c_raw, dict) or not c_raw:
        return {}, False
    no_note = {k: v for k, v in c_raw.items() if k not in ("note", "requirement_ref")}
    raw["cutover"] = no_note
    sub_m = sub_use_text_params(dict(c_raw), use_tbl)
    sw = (raw.get("scope") or {}).get("writes") or []
    if "rollback_readback" not in sub_m:
        sub_m["rollback_readback"] = "required" if sw else "not_applicable"
    if "enforce" not in sub_m:
        sub_m["enforce"] = "release"
    sub_no_note = {k: v for k, v in sub_m.items() if k not in ("note", "requirement_ref")}
    sub_m["requirement_ref"] = dr1_digest_fn(sub_no_note)
    return sub_m, True


def load_parity_receipts_impl(events_paths: list[Path], decode_fn: Callable[[str], Any]) -> tuple[list[dict[str, Any]], list[str]]:
    out, errs = [], []
    str_keys = ("contract", "digest", "requirement_ref", "legacy_target", "candidate_target", "legacy_subject_ref", "candidate_subject_ref", "normalization_ref", "corpus_ref", "rollback_readback", "outcome")
    for pf in collect_receipt_files(events_paths, ".parity.json"):
        try:
            doc = decode_fn(pf.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or set(doc) != PARITY_KEYS or doc.get("schema") != "drift.parity-receipt/1" or any(not isinstance(doc.get(k), str) or not doc[k].strip() for k in str_keys):
                raise ValueError("parity_keys")
            s = {k: doc[k].strip() for k in str_keys}
            cid, dig, rref, leg, cand, lref, cref, nref, cpref, rb, outc = (s[k] for k in str_keys)
            fv = doc.get("frame_verified")
            if not ID_RE.match(cid) or not ARTIFACT_REF_RE.match(dig) or not ARTIFACT_REF_RE.match(rref) or leg == cand or not ARTIFACT_REF_RE.match(lref) or not ARTIFACT_REF_RE.match(cref) or not ARTIFACT_REF_RE.match(nref) or not ARTIFACT_REF_RE.match(cpref) or not isinstance(fv, bool) or rb not in ("verified", "not_applicable", "unverified", "failed") or outc not in ("passed", "failed"):
                raise ValueError("parity_fields")
            lists = {}
            for lk in ("legacy_cases", "candidate_cases", "diverged_observations", "effect_violations"):
                arr = doc.get(lk)
                if not isinstance(arr, list) or not all(isinstance(x, str) and x.strip() for x in arr):
                    raise ValueError(lk)
                lists[lk] = sorted({x.strip() for x in arr})
            out.append({"schema": "drift.parity-receipt/1", **s, "frame_verified": fv, **lists})
        except Exception as exc:
            errs.append(f"{pf.name}: {exc}")
    return out, errs


def evaluate_contract_parity_impl(contract: dict[str, Any], parity_receipts: list[dict[str, Any]], phase: str, digest_matches_fn: Callable[[str, str], bool], expected_subject_ref: str = "", shard_subject_refs: set[str] | None = None, mig_checks: list[dict[str, Any]] | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    cm = contract.get("cutover") or {}
    if not cm:
        return [], []
    enforced_now = str(cm.get("enforce", "release")) == "always" or phase == "release"
    matching = [r for r in parity_receipts if r["contract"] == contract["id"] and digest_matches_fn(r["digest"], contract["digest"])]
    if not matching:
        return (["parity.missing"] if enforced_now else []), []
    if len(matching) > 1 and any(r != matching[0] for r in matching[1:]):
        return ["parity.conflicting_receipts"], [{**r, "effective_outcome": "failed", "reason": "parity.conflicting_receipts"} for r in matching]
    rec, raw_cases = matching[0], contract.get("cases") or {}
    active = sorted(cid for cid, c in raw_cases.items() if isinstance(c, dict) and "status" not in c)
    needs_frames = bool((contract.get("scope_writes") or []) or any(isinstance(c, dict) and "writes" in c for c in raw_cases.values()))
    allowed, sh_refs, m_list = set(cm.get("intentional_diffs") or []), shard_subject_refs or set(), mig_checks or []
    comp_ok = rec["legacy_subject_ref"] != rec["candidate_subject_ref"] and all(ac in rec["legacy_cases"] and ac in rec["candidate_cases"] for ac in active)
    sub_ok = (not expected_subject_ref or digest_matches_fn(rec["candidate_subject_ref"], expected_subject_ref)) and (not sh_refs or any(digest_matches_fn(rec["candidate_subject_ref"], s) for s in sh_refs))
    norm_ok = rec["legacy_target"] == cm.get("legacy_target") and rec["candidate_target"] == cm.get("candidate_target") and digest_matches_fn(rec["normalization_ref"], str(cm.get("normalization_ref", ""))) and digest_matches_fn(rec["corpus_ref"], str(cm.get("corpus_ref", ""))) and (not cm.get("requirement_ref") or digest_matches_fn(rec["requirement_ref"], cm["requirement_ref"]))
    obs_ok = all(d in allowed for d in rec["diverged_observations"])
    eff_ok = not rec["effect_violations"] and (not needs_frames or rec["frame_verified"])
    rb_ok = cm.get("rollback_readback", "not_applicable") != "required" or rec["rollback_readback"] == "verified"
    migs_ok = all(any(mr.get("migration_id") == mid and mr.get("effective_outcome") == "passed" and digest_matches_fn(str(mr.get("subject_ref", "")), rec["candidate_subject_ref"]) for mr in m_list) and not any(mr.get("migration_id") == mid and mr.get("effective_outcome") != "passed" for mr in m_list) for mid in (cm.get("migration_ids") or []))
    reasons = [tag for cond, tag in ((not comp_ok, "parity.incomplete_target"), (not sub_ok, "parity.subject_mismatch"), (not norm_ok, "parity.normalization_mismatch"), (not obs_ok, "parity.observation_mismatch"), (not eff_ok, "parity.effect_mismatch"), (not rb_ok, "parity.rollback_incompatible"), (not migs_ok, "parity.migration_unverified")) if cond]
    if rec["outcome"] != "passed" and not reasons:
        reasons.append("parity.observation_mismatch")
    eff_out = "passed" if not reasons and rec["outcome"] == "passed" else "failed"
    return reasons, [{**rec, "effective_outcome": eff_out, **({"reason": reasons[0]} if reasons else {})}]


def _resolve_canon_res_py(area_id: str, raw_res: str, aliases: dict[str, str]) -> str:
    t = raw_res.strip()
    if not t:
        return ""
    if t in aliases and aliases[t].strip():
        return aliases[t].strip()
    if "#" in t:
        base, part = t.split("#", 1)
        if base in aliases and aliases[base].strip():
            return f"{aliases[base].strip()}#{part}"
    return t if t.startswith("urn:") else f"urn:area:{area_id.strip() or 'default'}:{t}"


def parse_comp_bundles_py(raw: Any, resolve_res_fn: Callable[[str, str, dict[str, str]], str] = _resolve_canon_res_py) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("composition_bundles")
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or ("schema" in item and item["schema"] != "drift.boundary-bundle/1"):
            raise ValueError("composition_bundle")
        aid, ver, al_raw = str(item.get("area_id", "")).strip(), str(item.get("version", "")).strip(), item.get("resource_aliases") or {}
        if not aid or not ver or not isinstance(al_raw, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() for k, v in al_raw.items()):
            raise ValueError("composition_bundle_id")
        aliases = {k: v.strip() for k, v in al_raw.items()}

        def _specs(lst: Any) -> list[dict[str, Any]]:
            if not isinstance(lst, list):
                raise ValueError("behavior_specs")
            res_l: list[dict[str, Any]] = []
            for s in lst:
                if not isinstance(s, dict) or not str(s.get("operation", "")).strip() or not str(s.get("resource", "")).strip() or not isinstance(s.get("when_domain", []), list) or not isinstance(s.get("then_domain", []), list):
                    raise ValueError("behavior_spec")
                res_l.append({"operation": str(s["operation"]).strip(), "resource": resolve_res_fn(aid, str(s["resource"]).strip(), aliases), "when_domain": [str(x) for x in s.get("when_domain", [])], "then_domain": [str(x) for x in s.get("then_domain", [])]})
            return res_l

        sw, sr = item.get("shared_writes", []), item.get("shared_reads", [])
        if not isinstance(sw, list) or not isinstance(sr, list):
            raise ValueError("shared_effects")
        auth = str(item.get("authority", "")).strip() if "authority" in item else ""
        out.append({"area_id": aid, "version": ver, "authority": auth, "offers": _specs(item.get("offers", [])), "requires": _specs(item.get("requires", [])), "shared_writes": [resolve_res_fn(aid, str(w), aliases) for w in sw], "shared_reads": [resolve_res_fn(aid, str(r), aliases) for r in sr]})
    return out


def load_composition_manifests_core(events_paths: list[Path], decode_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
    out, errs = [], []
    allowed = {"schema", "contract", "active_producers", "active_consumers", "retained_events", "rollback_targets", "declared_coordinators", "critical_paths", "pact_refs"}
    for cf in collect_receipt_files(events_paths, ".composition.json"):
        try:
            doc = decode_fn(cf.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or any(k not in allowed for k in doc) or doc.get("schema") != "drift.composition-manifest/1":
                raise ValueError("composition_schema")
            pr_raw = doc.get("pact_refs", [])
            if not isinstance(pr_raw, list):
                raise ValueError("pact_refs")
            bad_pr = bool("pact_refs" in doc and (len(set(pr_raw)) != len(pr_raw) or any(not isinstance(x, str) or not re.fullmatch(r"dr2p:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})", x.strip()) for x in pr_raw)))
            cid = str(doc.get("contract", "")).strip() if "contract" in doc else ""
            if "contract" in doc and not cid:
                raise ValueError("composition_contract")
            prods, cons, rbs = parse_comp_bundles_py(doc.get("active_producers", [])), parse_comp_bundles_py(doc.get("active_consumers", [])), parse_comp_bundles_py(doc.get("rollback_targets", []))
            ret_raw, coords_raw, cp_raw = doc.get("retained_events", []), doc.get("declared_coordinators", {}), doc.get("critical_paths", [])
            if not isinstance(ret_raw, list) or not isinstance(coords_raw, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() for k, v in coords_raw.items()) or not isinstance(cp_raw, list):
                raise ValueError("composition_tables")
            ret_evs = [{"resource": str(re_it["resource"]).strip(), "epoch": str(re_it["epoch"]).strip(), "emitted_then": [str(x) for x in re_it["emitted_then"]]} for re_it in ret_raw if isinstance(re_it, dict) and str(re_it.get("resource", "")).strip() and str(re_it.get("epoch", "")).strip() and isinstance(re_it.get("emitted_then", []), list)]
            if len(ret_evs) != len(ret_raw):
                raise ValueError("retained_event")
            cpaths = []
            for cp in cp_raw:
                if not isinstance(cp, dict) or not str(cp.get("id", "")).strip() or not isinstance(cp.get("stages"), list) or not isinstance(cp.get("budget_ms", 0), int) or isinstance(cp.get("budget_ms", 0), bool) or cp.get("budget_ms", 0) < 0:
                    raise ValueError("critical_path")
                stages = [{"area_id": str(st["area_id"]).strip(), "operation": str(st["operation"]).strip(), "p95_ms": st["p95_ms"], "idempotent": bool(st.get("idempotent", True)), "max_executions": st["max_executions"], "timeout_compensated": bool(st.get("timeout_compensated", True)), "confirmed_before_completion": bool(st.get("confirmed_before_completion", True))} for st in cp["stages"] if isinstance(st, dict) and str(st.get("area_id", "")).strip() and str(st.get("operation", "")).strip() and isinstance(st.get("p95_ms"), int) and not isinstance(st.get("p95_ms"), bool) and st["p95_ms"] >= 0 and isinstance(st.get("max_executions"), int) and not isinstance(st.get("max_executions"), bool) and st["max_executions"] >= 0]
                if len(stages) != len(cp["stages"]):
                    raise ValueError("stage")
                cpaths.append({"id": str(cp["id"]).strip(), "budget_ms": cp.get("budget_ms", 0), "stages": stages})
            out.append({"schema": "drift.composition-manifest/1", "contract": cid, "active_producers": prods, "active_consumers": cons, "retained_events": ret_evs, "rollback_targets": rbs, "declared_coordinators": {k: v.strip() for k, v in coords_raw.items()}, "critical_paths": cpaths, "bad_pact_ref": bad_pr})
        except Exception as exc:
            errs.append(f"{cf.name}: {exc}")
    return out, errs


def evaluate_federated_composition_py(m: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []

    def _add(r: str) -> None:
        if r and r not in reasons:
            reasons.append(r)

    if m.get("schema") != "drift.composition-manifest/1":
        _add("federation.invalid_manifest_schema")
    if m.get("bad_pact_ref"):
        _add("federation.invalid_pact_ref")
    checked_pairs = 0

    def _check_pair(prod: dict[str, Any], cons: dict[str, Any], is_rb: bool) -> int:
        pairs, p_lbl, c_lbl = 0, f"{prod['area_id']}@{prod['version']}", f"{cons['area_id']}@{cons['version']}"
        for req in cons.get("requires", ()):
            for off in prod.get("offers", ()):
                if req["resource"] != off["resource"] or req["operation"] != off["operation"]:
                    continue
                pairs += 1
                for w in req["when_domain"]:
                    if w not in off["when_domain"]:
                        _add(f"federation.rollback_incompatible:{p_lbl}:{c_lbl}:{req['resource']}" if is_rb else f"federation.request_rejected:{c_lbl}->{p_lbl}:{req['resource']}:{w}")
                for t in off["then_domain"]:
                    if t not in req["then_domain"]:
                        _add(f"federation.rollback_incompatible:{p_lbl}:{c_lbl}:{req['resource']}" if is_rb else f"federation.response_unhandled:{p_lbl}->{c_lbl}:{req['resource']}:{t}")
        return pairs

    for p in m.get("active_producers", ()):
        if p.get("authority") == "break_glass_pending_ratification":
            _add(f"federation.break_glass_tainted:{p['area_id']}")
        for c in m.get("active_consumers", ()):
            checked_pairs += _check_pair(p, c, False)
    all_cons = list(m.get("active_consumers", ())) + [rb for rb in m.get("rollback_targets", ()) if rb.get("requires")]
    for ev in m.get("retained_events", ()):
        for c in all_cons:
            c_lbl = f"{c['area_id']}@{c['version']}"
            for req in c.get("requires", ()):
                if req["resource"] == ev["resource"]:
                    for t in ev["emitted_then"]:
                        if t not in req["then_domain"]:
                            _add(f"federation.retained_event_incompatible:{c_lbl}:{ev['resource']}:{ev['epoch']}:{t}")
    for rb in m.get("rollback_targets", ()):
        if rb.get("offers"):
            for c in m.get("active_consumers", ()):
                checked_pairs += _check_pair(rb, c, True)
        if rb.get("requires"):
            for p in m.get("active_producers", ()):
                checked_pairs += _check_pair(p, rb, True)
    writers_by_res: dict[str, set[str]] = {}
    for b in [*m.get("active_producers", ()), *m.get("active_consumers", ())]:
        for w in b.get("shared_writes", ()):
            writers_by_res.setdefault(w, set()).add(b["area_id"])
    shared_conflicts: list[str] = []
    coords = m.get("declared_coordinators") or {}
    for res in sorted(writers_by_res):
        writers = sorted(writers_by_res[res])
        if len(writers) > 1 and res not in coords:
            code = f"federation.shared_effect_conflict:{res}:{','.join(writers)}"
            shared_conflicts.append(code)
            _add(code)
    cp_results: dict[str, bool] = {}
    for cp in m.get("critical_paths", ()):
        p_ok, tot_p95 = True, 0
        for st in cp.get("stages", ()):
            tot_p95 += int(st["p95_ms"])
            for cond, tag in ((int(st["max_executions"]) > 1 and not st.get("idempotent", True), "double_effect"), (not st.get("timeout_compensated", True), "uncompensated_timeout"), (not st.get("confirmed_before_completion", True), "premature_confirmation")):
                if cond:
                    p_ok = False
                    _add(f"federation.critical_path_violated:{cp['id']}:{tag}:{st['operation']}")
        if int(cp.get("budget_ms", 0)) > 0 and tot_p95 > int(cp["budget_ms"]):
            p_ok = False
            _add(f"federation.path_budget_exceeded:{cp['id']}:{tot_p95}>{cp['budget_ms']}")
        cp_results[cp["id"]] = p_ok
    reasons.sort()
    return {"schema": "drift.composition-manifest/1", "ok": not reasons, "reasons": reasons, "checked_pairs": checked_pairs, "shared_effect_conflicts": shared_conflicts, "critical_path_results": cp_results}


def evaluate_contract_composition_core(contract: dict[str, Any], manifests: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    cid = contract["id"]
    applicable = [m for m in (manifests or ()) if not m.get("contract") or m.get("contract") == cid]
    if not applicable:
        return [], []
    reasons, verdicts = [], []
    for m in applicable:
        v = evaluate_federated_composition_py(m)
        verdicts.append(v)
        for r in v["reasons"]:
            if r not in reasons:
                reasons.append(r)
    return reasons, verdicts
