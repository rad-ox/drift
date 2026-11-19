#!/usr/bin/env python3
"""DRIFT Independent Reference Regulated Assurance Verifier (MIT License)."""

from __future__ import annotations
from typing import Any
from drift_verify_base import collect_receipt_files as _collect_files
from drift_verify_ra_io import (
    ARCH_KEYS,
    VC_KEYS,
    _arch_complete,
    extract_contract_risks_and_controls,
    load_evaluation_receipts_core,
    load_ra_receipts_core,
    load_study_receipts_core,
)
from drift_verify_ssh import evaluate_detached_signatures_impl, verify_ssh_sig_envelope_impl as _verify_ssh_sig_envelope

SIG_ENV_KEYS = frozenset(("schema", "payload", "signature"))
SIG_PAYLOAD_KEYS = frozenset(("schema", "signer", "meaning", "signed_at", "target_kind", "target_ref", "policy_ref", "context_ref"))
def validate_stochastic_experiment(se: dict[str, Any] | None, agg_n: int, agg_m: dict[str, float], active_cases: set[str]) -> str:
 if not se:return ""
 if not active_cases or any(c not in active_cases for c in se.get("target_cases",())):return "evaluation.incomplete_scope"
 if se.get("stopping_rule")=="fixed_shots" and se.get("observed_shots")!=se.get("planned_shots"):return "evaluation.stopping_rule_violated"
 a_idx,m_att=int(se.get("attempt_index",1)),int(se.get("max_attempts",1))
 if a_idx > m_att or (se.get("aggregation_rule")=="single_precommitted_run" and (a_idx > 1 or m_att > 1)) or (se.get("aggregation_rule")=="pooled_batches" and len((se.get("acquisition") or {}).get("job_ids") or ()) < a_idx):return "evaluation.unpooled_retry_rejected"
 h,n=int(se.get("target_hits",-1)),int(se.get("observed_shots",0))
 return "evaluation.counts_mismatch" if (h < 0 or n <= 0 or h > n or n!=agg_n or "target_probability" not in agg_m or abs(h / n - agg_m["target_probability"]) > 1e-6) else ""
def evaluate_contract_studies_core(contract: dict[str, Any], study_receipts: list[dict[str, Any]], expected_subject_ref: str, digest_matches_fn: Any) -> tuple[list[str], list[dict[str, Any]]]:
 ctrls=contract.get("controls") or {}
 exp_ctx={tok[6:]:str(cm.get("context_ref","")).strip() for cm in ctrls.values() if isinstance(cm,dict) for tok in (cm.get("effectiveness_evidence") or []) if isinstance(tok,str) and tok.startswith("study:") and str(cm.get("context_ref","")).strip()}
 eval_list,reasons=[],[]
 for rec in (r for r in study_receipts if r["contract"]==contract["id"] and digest_matches_fn(r["digest"],contract["digest"])):
  eff,rsn,req_ctx = rec["outcome"],"",exp_ctx.get(rec["study_id"],"")
  t_viol = any(t["outcome"]=="violated" for t in rec["critical_tasks"])
  t_ins = any(t["outcome"]=="insufficient_evidence" or t["completed"] > t["participants"] for t in rec["critical_tasks"])
  if not _arch_complete(rec["archival"]):eff,rsn = ("violated" if eff=="violated" else "inconclusive"),"evidence.archival_incomplete"
  elif expected_subject_ref and rec["subject_ref"]!=expected_subject_ref:eff,rsn = ("violated" if eff=="violated" else "inconclusive"),"study.subject_mismatch"
  elif req_ctx and rec["validity_context"]["context_ref"]!=req_ctx:eff,rsn = ("violated" if eff=="violated" else "inconclusive"),"evidence.context_mismatch"
  elif t_viol or eff=="violated":eff,rsn = "violated","study.violated"
  elif t_ins or eff=="insufficient_evidence":eff,rsn = "insufficient_evidence","study.insufficient_evidence"
  if rsn and rsn not in reasons:reasons.append(rsn)
  eval_list.append({**rec,"effective_outcome":eff,**({"reason":rsn} if rsn else {})})
 return reasons,eval_list
def _chk_metric_bounds(m_dict: dict[str, float], cil: dict[str, float], ciu: dict[str, float], min_m: dict[str, float], max_m: dict[str, float]) -> tuple[bool, bool, bool]:
 viol=ins=False
 if any((k in cil and cil[k] > v+1e-9) or (k in ciu and ciu[k]+1e-9 < v) for k,v in m_dict.items()):return False,False,True
 for mn,mv in min_m.items():
  obs = m_dict.get(mn)
  if obs is None:ins = True
  elif mn in cil and mn in ciu:
   viol,ins=viol or ciu[mn] < mv,ins or (ciu[mn] >= mv and cil[mn] < mv)
  else:viol,ins = viol or obs < mv,ins or (obs >= mv and cil.get(mn,mv) < mv)
 for mn,mv in max_m.items():
  obs = m_dict.get(mn)
  if obs is None:ins = True
  elif mn in cil and mn in ciu:
   viol,ins=viol or cil[mn] > mv,ins or (cil[mn] <= mv and ciu[mn] > mv)
  else:viol,ins = viol or obs > mv,ins or (obs <= mv and ciu.get(mn,mv) > mv)
 return viol,ins,False
def evaluate_contract_evaluations_core(contract: dict[str, Any], eval_receipts: list[dict[str, Any]], expected_subject_ref: str, digest_matches_fn: Any, phase: str = "") -> tuple[list[str], list[dict[str, Any]]]:
 ctrls=contract.get("controls") or {}
 act_cases={cid for cid,cm in (contract.get("cases") or {}).items() if isinstance(cm,dict) and "status" not in cm}
 exp_ctx={tok[11:]:str(cm["context_ref"]).strip() for cm in ctrls.values() if isinstance(cm,dict) and str(cm.get("context_ref","")).strip() for tok in (cm.get("effectiveness_evidence") or []) if isinstance(tok,str) and tok.startswith("evaluation:")}
 exp_crit={tok[11:]:str(cm["criteria_ref"]).strip() for cm in ctrls.values() if isinstance(cm,dict) and str(cm.get("criteria_ref","")).strip() for tok in (cm.get("effectiveness_evidence") or []) if isinstance(tok,str) and tok.startswith("evaluation:")}
 matching=[r for r in eval_receipts if r["contract"]==contract["id"] and digest_matches_fn(r["digest"],contract["digest"])]
 eval_list,reasons=[],[]
 for rec in matching:
  eff,rsn = rec["outcome"],""
  req_ctx,req_crit = exp_ctx.get(rec["evaluation_id"],""),exp_crit.get(rec["evaluation_id"],"")
  min_m,max_m,req_sgs = rec["criteria"]["min_metrics"],rec["criteria"]["max_metrics"],rec["criteria"]["required_subgroups"]
  agg = rec["aggregate"]
  sg_viol,sg_ins,bad_int = _chk_metric_bounds(agg["metrics"],agg["ci_lower"],agg["ci_upper"],min_m,max_m)
  seen_sgs = set()
  for sg in rec["subgroups"]:
   seen_sgs.add(sg["id"])
   v2,i2,inv2=_chk_metric_bounds(sg["metrics"],sg["ci_lower"],sg["ci_upper"],min_m,max_m)
   sg_viol=sg_viol or v2 or sg["outcome"]=="violated"
   sg_ins=sg_ins or i2 or sg["outcome"]=="insufficient_evidence" or sg["sample_size"] < sg["min_sample_size"]
   bad_int=bad_int or inv2
  if any(rsg not in seen_sgs for rsg in req_sgs):sg_ins = True
  se = rec.get("stochastic_experiment")
  stoch_rsn = validate_stochastic_experiment(se,agg["sample_size"],agg["metrics"],act_cases)
  if not _arch_complete(rec["archival"]):eff,rsn = ("violated" if eff=="violated" or sg_viol else "inconclusive"),"evidence.archival_incomplete"
  elif expected_subject_ref and rec["subject_ref"]!=expected_subject_ref:eff,rsn = ("violated" if eff=="violated" or sg_viol else "inconclusive"),"evaluation.subject_mismatch"
  elif req_crit and rec["criteria_ref"]!=req_crit:eff,rsn = ("violated" if eff=="violated" or sg_viol else "inconclusive"),"evaluation.criteria_mismatch"
  elif req_ctx and rec["validity_context"]["context_ref"]!=req_ctx:eff,rsn = ("violated" if eff=="violated" or sg_viol else "inconclusive"),"evidence.context_mismatch"
  elif bad_int:eff,rsn = ("violated" if eff=="violated" or sg_viol else "inconclusive"),"evaluation.invalid_interval"
  elif stoch_rsn:eff,rsn = ("violated" if eff=="violated" or sg_viol else "inconclusive"),stoch_rsn
  elif sg_viol or eff=="violated":eff,rsn = "violated","evaluation.subgroup_violated"
  elif sg_ins or eff=="insufficient_evidence":eff,rsn = "insufficient_evidence","evaluation.insufficient_evidence"
  item = {**rec,"effective_outcome":eff,**({"claim_scope":{"independence_and_stability":"protocol_assumption","omitted_runs":"unverifiable_from_receipt_alone"}} if se else {})}
  if rsn:
   item["reason"]=rsn
   if not (se and se.get("enforce","release")=="release" and phase=="execution" and eff=="insufficient_evidence") and rsn not in reasons:reasons.append(rsn)
  eval_list.append(item)
 return reasons,eval_list
def evaluate_contract_ra_bundle(contract: dict[str, Any], res: list[dict[str, Any]], s_checks: list[dict[str, Any]], f_checks: list[dict[str, Any]], m_checks: list[dict[str, Any]], ra_receipts: dict[str, list[dict[str, Any]]] | None, exp_sref: str, phase: str, mutations_ok: bool, digest_matches_fn: Any) -> tuple[list[str], dict[str, Any]]:
 ra=ra_receipts or {}
 st_rsn,st_checks=evaluate_contract_studies_core(contract,ra.get("studies") or [],exp_sref,digest_matches_fn)
 ev_rsn,ev_checks=evaluate_contract_evaluations_core(contract,ra.get("evaluations") or [],exp_sref,digest_matches_fn,phase)
 ctrl_rsn,pend_c,ctrl_checks=evaluate_contract_controls_core(contract,res,s_checks,f_checks,m_checks,st_checks,ev_checks,phase,mutations_ok)
 extra:dict[str,Any]={}
 if pend_c:extra["pending_controls"]=pend_c
 if st_checks:extra["study_checks"]=st_checks
 if ev_checks:extra["evaluation_checks"]=ev_checks
 if ctrl_checks:extra["control_checks"]=ctrl_checks
 return [*st_rsn,*ev_rsn,*ctrl_rsn],extra
_OUT_RANK={"violated":3,"insufficient_evidence":2,"inconclusive":1,"missing":1,"unverified":1}
def _worst_rec(by_id: dict[str, Any], key: str, rec: dict[str, Any]) -> None:
 prev=by_id.get(key)
 if prev is None or _OUT_RANK.get(rec["effective_outcome"],0) > _OUT_RANK.get(prev["effective_outcome"],0):
  by_id[key] = rec
def evaluate_contract_controls_core(contract: dict[str, Any], res: list[dict[str, Any]], sec_checks: list[dict[str, Any]], formal_checks: list[dict[str, Any]], mig_checks: list[dict[str, Any]], study_checks: list[dict[str, Any]], eval_checks: list[dict[str, Any]], phase: str, mutations_ok: bool) -> tuple[list[str], list[str], list[dict[str, Any]]]:
 ctrls=contract.get("controls") or {}
 if not ctrls:
  return [],[],[]
 case_ver,case_red,case_seen={},{},set()
 for r in res:
  c = r["case"]
  if c not in case_seen:
   case_seen.add(c); case_ver[c]=True
  if r["state"]!="verified":case_ver[c] = False
  if r["state"]=="red":case_red[c] = True
 sec_by_cat:dict[str,str]={}
 for r in sec_checks:
  if _OUT_RANK.get(r["effective_outcome"],0) >= _OUT_RANK.get(sec_by_cat.get(r["category"],""),-1):sec_by_cat[r["category"]] = r["effective_outcome"]
 form_by_id:dict[str,str]={}
 for r in formal_checks:
  if _OUT_RANK.get(r["effective_outcome"],0) >= _OUT_RANK.get(form_by_id.get(r["formal_id"],""),-1):form_by_id[r["formal_id"]] = r["effective_outcome"]
 mig_by_id:dict[str,str]={}
 for r in mig_checks:
  if _OUT_RANK.get(r["effective_outcome"],0) >= _OUT_RANK.get(mig_by_id.get(r["migration_id"],""),-1):mig_by_id[r["migration_id"]] = r["effective_outcome"]
 study_by_id:dict[str,Any]={}
 for r in study_checks:_worst_rec(study_by_id,r["study_id"],r)
 eval_by_id:dict[str,Any]={}
 for r in eval_checks:_worst_rec(eval_by_id,r["evaluation_id"],r)
 reasons,pending,out_ctrls=[],[],[]
 for cid in sorted(ctrls):
  cm = ctrls[cid]
  if not isinstance(cm,dict):continue
  kind,mitigates,cases = str(cm.get("kind","software")),list(cm.get("mitigates") or []),list(cm.get("cases") or [])
  impl_ev,eff_ev,enforce = list(cm.get("implementation_evidence") or []),list(cm.get("effectiveness_evidence") or []),str(cm.get("enforce","release"))
  enforced_now = phase=="release" or enforce=="execution"
  impl_st,impl_rsn = ("not_applicable" if not impl_ev else "verified"),""
  for tok in impl_ev:
   if tok in ("case_verified","ui_observation","case_killed"):
    if not cases:impl_st,impl_rsn = "missing","control.implementation_unverified"
    for c_id in cases:
     if case_red.get(c_id):impl_st,impl_rsn="violated","control.violated"
     elif not case_ver.get(c_id) and impl_st!="violated":impl_st,impl_rsn="missing","control.implementation_unverified"
    if tok=="case_killed" and not mutations_ok and impl_st!="violated":impl_st,impl_rsn = "missing","control.implementation_unverified"
   else:
    st_map = {"formal:":(form_by_id,("passed","reused_subject")),"security:":(sec_by_cat,("passed","reused")),"migration:":(mig_by_id,("passed",))}
    for pfx,(lkp,ok_set) in st_map.items():
     if tok.startswith(pfx):
      vst = lkp.get(tok[len(pfx):],"missing")
      if vst=="violated":impl_st,impl_rsn = "violated","control.violated"
      elif vst not in ok_set and impl_st!="violated":impl_st,impl_rsn = ("missing" if vst in ("missing","pending") else "inconclusive"),"control.implementation_unverified"
  eff_st,eff_rsn,eff_rsns = ("not_required" if not eff_ev else "supported"),"",[]
  for tok in eff_ev:
   srec=study_by_id.get(tok[6:]) if tok.startswith("study:") else (eval_by_id.get(tok[11:]) if tok.startswith("evaluation:") else None)
   def_miss="study.missing" if tok.startswith("study:") else ("evaluation.missing" if tok.startswith("evaluation:") else "control.effectiveness_unverified")
   def_viol="study.violated" if tok.startswith("study:") else "evaluation.subgroup_violated"
   def_ins="study.insufficient_evidence" if tok.startswith("study:") else "evaluation.insufficient_evidence"
   if srec:
    eo = srec["effective_outcome"]
    if eo=="violated":
     r=srec.get("reason",def_viol); eff_st,eff_rsn="violated",r; eff_rsns.append(r)
    elif eo=="insufficient_evidence" and eff_st!="violated":
     r=srec.get("reason",def_ins); eff_st,eff_rsn="insufficient_evidence",(eff_rsn or r); eff_rsns.append(r)
    elif eo!="supported" and eff_st not in ("violated","insufficient_evidence"):
     r=srec.get("reason","control.effectiveness_unverified"); eff_st,eff_rsn="inconclusive",(eff_rsn or r); eff_rsns.append(r)
   elif eff_st not in ("violated","insufficient_evidence"):
    eff_st,eff_rsn = ("missing" if enforced_now else "pending_release"),(eff_rsn or def_miss); eff_rsns.append(def_miss)
  impl_ok,eff_ok = impl_st in ("verified","not_applicable"),eff_st in ("supported","not_required")
  overall,ctrl_rsn = "satisfied",""
  if impl_st=="violated" or eff_st=="violated":overall,ctrl_rsn = "violated",(eff_rsn if eff_st=="violated" and eff_rsn else "control.violated")
  elif not enforced_now and (not impl_ok or not eff_ok):overall = "pending_release"; pending.append(cid)
  elif eff_st=="insufficient_evidence":overall,ctrl_rsn = "insufficient_evidence",(eff_rsn or "control.insufficient_evidence")
  elif not impl_ok:overall,ctrl_rsn = ("missing" if impl_st=="missing" else "inconclusive"),(impl_rsn or "control.implementation_unverified")
  elif not eff_ok:overall,ctrl_rsn = ("missing" if eff_st=="missing" else "inconclusive"),(eff_rsn or "control.effectiveness_unverified")
  if overall not in ("satisfied","pending_release"):
   for r in (ctrl_rsn,*eff_rsns):
    if r and r not in reasons:reasons.append(r)
   for tag,cond in (("control.violated",overall=="violated"),("control.insufficient_evidence",overall=="insufficient_evidence"),("control.implementation_unverified",not impl_ok and overall not in ("violated","insufficient_evidence")),("control.effectiveness_unverified",impl_ok and not eff_ok and overall not in ("violated","insufficient_evidence"))):
    if cond and tag not in reasons:reasons.append(tag)
  entry = {"cases":cases,"control_id":cid,"effectiveness_evidence":eff_ev,"effectiveness_status":eff_st,"enforce":enforce,"implementation_evidence":impl_ev,"implementation_status":impl_st,"kind":kind,"mitigates":mitigates,"requirement_ref":str(cm.get("requirement_ref","")),"status":overall}
  for opt_k in ("context_ref","criteria_ref"):
   if cm.get(opt_k):entry[opt_k]=str(cm[opt_k])
  if ctrl_rsn:entry["reason"] = ctrl_rsn
  out_ctrls.append(entry)
 return reasons,pending,out_ctrls
def evaluate_detached_signatures_core(verdicts: list[dict[str, Any]], parsed_contracts: list[dict[str, Any]], args: Any, cfg_dig: str, decode_fn: Any, canonical_json_fn: Any, digest_matches_fn: Any) -> list[dict[str, Any]]:
 return evaluate_detached_signatures_impl(verdicts,parsed_contracts,args,cfg_dig,decode_fn,canonical_json_fn,digest_matches_fn,_collect_files,_verify_ssh_sig_envelope,SIG_ENV_KEYS,SIG_PAYLOAD_KEYS)

__all__ = [
    "ARCH_KEYS",
    "VC_KEYS",
    "evaluate_contract_controls_core",
    "evaluate_contract_evaluations_core",
    "evaluate_contract_ra_bundle",
    "evaluate_contract_studies_core",
    "evaluate_detached_signatures_core",
    "extract_contract_risks_and_controls",
    "load_evaluation_receipts_core",
    "load_ra_receipts_core",
    "load_study_receipts_core",
    "validate_stochastic_experiment",
]
