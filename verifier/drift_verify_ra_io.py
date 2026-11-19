#!/usr/bin/env python3
"""Regulated assurance study and evaluation receipt loaders (drift.study-receipt/1, drift.evaluation-receipt/1)."""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any

from drift_verify_base import ID_RE, SHA256_REF_RE, WORD_RE, collect_receipt_files

VC_KEYS = frozenset(("context_ref", "intended_use_ref", "population_ref", "environment_ref", "assumptions_ref"))
ARCH_KEYS = frozenset(("report_ref", "report_uri", "retention_class", "adapter_version", "verifier_version"))
STUDY_KEYS = frozenset(("schema", "contract", "digest", "study_id", "subject_ref", "artifact_ref", "protocol_ref", "user_groups", "environment_ref", "validity_context", "critical_tasks", "limitations", "archival", "outcome"))
EVAL_KEYS = frozenset(("schema", "contract", "digest", "evaluation_id", "subject_ref", "artifact_ref", "config_ref", "corpus_ref", "protocol_ref", "preprocessing_ref", "reference_labels_ref", "criteria_ref", "criteria", "aggregate", "subgroups", "stochastic_experiment", "validity_context", "archival", "outcome"))
STOCH_EXP_KEYS = frozenset(("experiment_id", "experiment_plan_ref", "data_ref", "target_cases", "target_outcomes", "support_size", "planned_shots", "observed_shots", "target_hits", "stopping_rule", "attempt_index", "max_attempts", "aggregation_rule", "confidence_level", "enforce", "acquisition"))
STOCH_ACQ_KEYS = frozenset(("backend_id", "backend_kind", "config_ref", "calibration_ref", "batch_id", "job_ids"))


def _sub_val(val: Any, params: dict[str, Any]) -> Any:
    if isinstance(val, str) and val.startswith("$") and val[1:] in params:
        return params[val[1:]]
    return [_sub_val(x, params) for x in val] if isinstance(val, list) else ({k: _sub_val(v, params) for k, v in val.items()} if isinstance(val, dict) else val)


def extract_contract_risks_and_controls(raw: dict[str, Any], prof: dict[str, Any], use_tbl: Any, dr1_digest_fn: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_risks, raw_ctrls, prof_risks, prof_ctrls = raw.pop("risks", None), raw.pop("controls", None), prof.pop("risks", None), prof.pop("controls", None)
    params = {k: v for k, v in (use_tbl.items() if isinstance(use_tbl, dict) else ()) if k not in ("profile", "concepts", "waive", "vocabulary")}
    eff_r = {str(k): _sub_val(copy.deepcopy(v), params) for src in (prof_risks, raw_risks) if isinstance(src, dict) for k, v in src.items() if isinstance(v, dict)}
    eff_c = {str(k): _sub_val(copy.deepcopy(v), params) for src in (prof_ctrls, raw_ctrls) if isinstance(src, dict) for k, v in src.items() if isinstance(v, dict)}
    res_c = {cid: {**cm, "enforce": cm.get("enforce", "release"), "requirement_ref": dr1_digest_fn({k: v for k, v in {**cm, "enforce": cm.get("enforce", "release")}.items() if k not in ("note", "requirement_ref")})} for cid, cm in eff_c.items()}
    return eff_r, res_c


def _parse_vc(vc: Any) -> dict[str, str]:
    if not isinstance(vc, dict) or set(vc) != VC_KEYS or any(not isinstance(vc.get(k), str) or not SHA256_REF_RE.match(vc[k]) for k in VC_KEYS):
        raise ValueError("validity_context")
    return {k: str(vc[k]) for k in sorted(VC_KEYS)}


def _parse_arch(ac: Any) -> dict[str, str]:
    if not isinstance(ac, dict) or any(k not in ARCH_KEYS for k in ac):
        raise ValueError("archival")
    return {k: str(ac.get(k, "")).strip() for k in sorted(ARCH_KEYS)}


def _arch_complete(ac: dict[str, str]) -> bool:
    return bool(SHA256_REF_RE.match(ac.get("report_ref", "")) and all(ac.get(k, "") for k in ("report_uri", "retention_class", "adapter_version", "verifier_version")))


def _parse_stoch_exp(se: Any) -> dict[str, Any]:
    if not isinstance(se, dict) or any(k not in STOCH_EXP_KEYS for k in se) or not isinstance(acq := se.get("acquisition"), dict) or set(acq) != STOCH_ACQ_KEYS:
        raise ValueError("stoch_exp")
    eid, enf = str(se.get("experiment_id", "")), str(se.get("enforce", "release")).strip()
    tc = [x for x in (se.get("target_cases") or []) if isinstance(x, str) and ID_RE.match(x)]
    to = [x.strip() for x in (se.get("target_outcomes") or []) if isinstance(x, str) and x.strip()]
    jbs = [x.strip() for x in (acq.get("job_ids") or []) if isinstance(x, str) and x.strip()]
    ivals = [se.get(k) for k in ("support_size", "planned_shots", "observed_shots", "target_hits", "attempt_index", "max_attempts")]
    cl = se.get("confidence_level")
    if not (ID_RE.match(eid) or WORD_RE.match(eid)) or not all(SHA256_REF_RE.match(str(r)) for r in (se.get("experiment_plan_ref"), se.get("data_ref"), acq.get("config_ref"), acq.get("calibration_ref"))) or not tc or len(tc) != len(se.get("target_cases") or []) or not to or len(set(to)) != len(se.get("target_outcomes") or []) or not jbs or any(not isinstance(v, int) or isinstance(v, bool) for v in ivals) or ivals[0] <= len(to) or ivals[1] <= 0 or ivals[2] <= 0 or ivals[3] < 0 or ivals[3] > ivals[2] or ivals[4] < 1 or ivals[5] < 1 or ivals[4] > ivals[5] or se.get("stopping_rule") not in ("fixed_shots", "sequential_confidence") or se.get("aggregation_rule") not in ("single_precommitted_run", "pooled_batches") or isinstance(cl, bool) or not isinstance(cl, (int, float)) or not math.isfinite(float(cl)) or not (0.0 < float(cl) < 1.0) or enf not in ("execution", "release") or not str(acq.get("backend_id", "")).strip() or acq.get("backend_kind") not in ("hardware_qpu", "noisy_simulator", "statevector_simulator") or not str(acq.get("batch_id", "")).strip():
        raise ValueError("stoch_fields")
    return {**se, "confidence_level": float(cl), "enforce": enf, "target_cases": sorted(set(tc)), "target_outcomes": sorted(set(to)), "acquisition": {**acq, "job_ids": sorted(set(jbs))}}


def load_study_receipts_core(events_paths: list[Path], decode_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
    out, errs = [], []
    for sf in collect_receipt_files(events_paths, ".study.json"):
        try:
            doc = decode_fn(sf.read_text("utf-8"))
            if not isinstance(doc, dict) or any(k not in STUDY_KEYS for k in doc) or doc.get("schema") != "drift.study-receipt/1":
                raise ValueError("study_keys")
            cid, dig, sid = str(doc.get("contract", "")), str(doc.get("digest", "")), str(doc.get("study_id", ""))
            sref, aref, pref, eref, outc = str(doc.get("subject_ref", "")), str(doc.get("artifact_ref", "")), str(doc.get("protocol_ref", "")), str(doc.get("environment_ref", "")), str(doc.get("outcome", ""))
            if not ID_RE.match(cid) or not dig or not (ID_RE.match(sid) or WORD_RE.match(sid)) or not SHA256_REF_RE.match(sref) or (aref and not SHA256_REF_RE.match(aref)) or not SHA256_REF_RE.match(pref) or not SHA256_REF_RE.match(eref) or outc not in ("supported", "insufficient_evidence", "violated"):
                raise ValueError("study_envelope")
            ug = [str(x).strip() for x in (doc.get("user_groups") or []) if isinstance(x, str) and x.strip()]
            lims = [str(x).strip() for x in (doc.get("limitations") or []) if isinstance(x, str) and x.strip()]
            tasks_raw = doc.get("critical_tasks")
            if not ug or not lims or not isinstance(tasks_raw, list) or not tasks_raw:
                raise ValueError("study_lists")
            tasks = []
            for t in tasks_raw:
                if not isinstance(t, dict) or set(t) != {"task_id", "cases", "participants", "completed", "use_errors", "hazards_observed", "outcome"} or not str(t["task_id"]).strip() or not isinstance(t["cases"], list):
                    raise ValueError("study_task")
                part, comp, uerr, haz, tout = t["participants"], t["completed"], t["use_errors"], t["hazards_observed"], t["outcome"]
                if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in (part, comp, uerr, haz)) or part <= 0 or tout not in ("supported", "insufficient_evidence", "violated"):
                    raise ValueError("study_task_vals")
                tasks.append({"cases": sorted({str(c) for c in t["cases"] if isinstance(c, str) and c.strip()}), "completed": comp, "hazards_observed": haz, "outcome": str(tout), "participants": part, "task_id": str(t["task_id"]).strip(), "use_errors": uerr})
            out.append({"schema": "drift.study-receipt/1", "contract": cid, "digest": dig, "study_id": sid, "subject_ref": sref, **({"artifact_ref": aref} if aref else {}), "protocol_ref": pref, "user_groups": sorted(set(ug)), "environment_ref": eref, "validity_context": _parse_vc(doc.get("validity_context")), "critical_tasks": tasks, "limitations": lims, "archival": _parse_arch(doc.get("archival")), "outcome": outc})
        except Exception as exc:
            errs.append(f"{sf.name}: {exc}")
    return out, errs


def load_evaluation_receipts_core(events_paths: list[Path], decode_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
    out, errs = [], []
    for ef in collect_receipt_files(events_paths, ".evaluation.json"):
        try:
            doc = decode_fn(ef.read_text("utf-8"))
            if not isinstance(doc, dict) or any(k not in EVAL_KEYS for k in doc) or doc.get("schema") != "drift.evaluation-receipt/1":
                raise ValueError("eval_keys")
            cid, dig, eid, sref, aref = str(doc.get("contract", "")), str(doc.get("digest", "")), str(doc.get("evaluation_id", "")), str(doc.get("subject_ref", "")), str(doc.get("artifact_ref", ""))
            refs = [str(doc.get(k, "")) for k in ("config_ref", "corpus_ref", "protocol_ref", "preprocessing_ref", "reference_labels_ref", "criteria_ref")]
            outc, crit, agg, sgs_raw = str(doc.get("outcome", "")), doc.get("criteria"), doc.get("aggregate"), doc.get("subgroups")
            if not ID_RE.match(cid) or not dig or not (ID_RE.match(eid) or WORD_RE.match(eid)) or not SHA256_REF_RE.match(sref) or (aref and not SHA256_REF_RE.match(aref)) or not all(SHA256_REF_RE.match(r) for r in refs) or outc not in ("supported", "insufficient_evidence", "violated") or not isinstance(crit, dict) or not isinstance(agg, dict) or not isinstance(agg.get("sample_size"), int) or isinstance(agg.get("sample_size"), bool) or agg["sample_size"] <= 0 or not isinstance(sgs_raw, list) or not sgs_raw:
                raise ValueError("eval_envelope")
            nm = lambda m: {str(k): float(v) for k, v in (m or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))}
            if any(isinstance(m, dict) and len(nm(m)) != len(m) for m in (crit.get("min_metrics"), crit.get("max_metrics"), agg.get("metrics"), agg.get("ci_lower"), agg.get("ci_upper"))):
                raise ValueError("eval_metrics")
            sgs = [{"id": str(sg["id"]).strip(), "sample_size": sg["sample_size"], "min_sample_size": sg["min_sample_size"], "metrics": nm(sg.get("metrics")), "ci_lower": nm(sg.get("ci_lower")), "ci_upper": nm(sg.get("ci_upper")), "outcome": str(sg["outcome"])} for sg in sgs_raw if isinstance(sg, dict) and str(sg.get("id", "")).strip() and isinstance(sg.get("sample_size"), int) and not isinstance(sg.get("sample_size"), bool) and sg["sample_size"] >= 0 and isinstance(sg.get("min_sample_size"), int) and not isinstance(sg.get("min_sample_size"), bool) and sg["min_sample_size"] > 0 and sg.get("outcome") in ("supported", "insufficient_evidence", "violated") and all(not isinstance(sg.get(mk), dict) or len(nm(sg.get(mk))) == len(sg[mk]) for mk in ("metrics", "ci_lower", "ci_upper"))]
            if len(sgs) != len(sgs_raw):
                raise ValueError("eval_sg")
            se = _parse_stoch_exp(doc["stochastic_experiment"]) if "stochastic_experiment" in doc else None
            out.append({"schema": "drift.evaluation-receipt/1", "contract": cid, "digest": dig, "evaluation_id": eid, "subject_ref": sref, **({"artifact_ref": aref} if aref else {}), "config_ref": refs[0], "corpus_ref": refs[1], "protocol_ref": refs[2], "preprocessing_ref": refs[3], "reference_labels_ref": refs[4], "criteria_ref": refs[5], "criteria": {"min_metrics": nm(crit.get("min_metrics")), "max_metrics": nm(crit.get("max_metrics")), "required_subgroups": sorted({str(x) for x in (crit.get("required_subgroups") or []) if isinstance(x, str) and x.strip()})}, "aggregate": {"sample_size": int(agg["sample_size"]), "metrics": nm(agg.get("metrics")), "ci_lower": nm(agg.get("ci_lower")), "ci_upper": nm(agg.get("ci_upper"))}, "subgroups": sgs, **({"stochastic_experiment": se} if se else {}), "validity_context": _parse_vc(doc.get("validity_context")), "archival": _parse_arch(doc.get("archival")), "outcome": outc})
        except Exception as exc:
            errs.append(f"{ef.name}: {exc}")
    return out, errs


def load_ra_receipts_core(events_paths: list[Path], decode_fn: Any) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    st_recs, st_errs = load_study_receipts_core(events_paths, decode_fn)
    ev_recs, ev_errs = load_evaluation_receipts_core(events_paths, decode_fn)
    return {"studies": st_recs, "evaluations": ev_recs}, st_errs + ev_errs
