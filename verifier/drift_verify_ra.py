#!/usr/bin/env python3
"""DRIFT Independent Reference Regulated Assurance Verifier (MIT License)."""

from __future__ import annotations
import copy,math,re
from pathlib import Path
from typing import Any
SHA256_REF_RE=re.compile(r"^sha256:[0-9a-f]{64}$")
ID_RE=re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORD_RE=re.compile(r"^[a-z][a-z0-9_]*$")
VC_KEYS=frozenset(("context_ref","intended_use_ref","population_ref","environment_ref","assumptions_ref"))
ARCH_KEYS=frozenset(("report_ref","report_uri","retention_class","adapter_version","verifier_version"))
STUDY_KEYS=frozenset(("schema","contract","digest","study_id","subject_ref","artifact_ref","protocol_ref","user_groups","environment_ref","validity_context","critical_tasks","limitations","archival","outcome"))
EVAL_KEYS=frozenset(("schema","contract","digest","evaluation_id","subject_ref","artifact_ref","config_ref","corpus_ref","protocol_ref","preprocessing_ref","reference_labels_ref","criteria_ref","criteria","aggregate","subgroups","stochastic_experiment","validity_context","archival","outcome"))
SIG_ENV_KEYS=frozenset(("schema","payload","signature"))
SIG_PAYLOAD_KEYS=frozenset(("schema","signer","meaning","signed_at","target_kind","target_ref","policy_ref","context_ref"))
def _collect_files(paths: list[Path], suffix: str) -> list[Path]:
 out,seen=[],set()
 for p in paths:
  if p:
   for f in (sorted(p.glob(f"*{suffix}")) if p.is_dir() else ([p] if p.is_file() and p.name.endswith(suffix) else [])):
    if f not in seen:seen.add(f); out.append(f)
 return out
def _sub_val(val: Any, params: dict[str, Any]) -> Any:
 if isinstance(val,str) and val.startswith("$") and val[1:] in params:return params[val[1:]]
 return [_sub_val(x,params) for x in val] if isinstance(val,list) else ({k:_sub_val(v,params) for k,v in val.items()} if isinstance(val,dict) else val)
def extract_contract_risks_and_controls(raw: dict[str, Any], prof: dict[str, Any], use_tbl: Any, dr1_digest_fn: Any) -> tuple[dict[str, Any], dict[str, Any]]:
 raw_risks,raw_ctrls,prof_risks,prof_ctrls=raw.pop("risks",None),raw.pop("controls",None),prof.pop("risks",None),prof.pop("controls",None)
 params={k:v for k,v in (use_tbl.items() if isinstance(use_tbl,dict) else ()) if k not in ("profile","concepts","waive","vocabulary")}
 eff_r={str(k):_sub_val(copy.deepcopy(v),params) for src in (prof_risks,raw_risks) if isinstance(src,dict) for k,v in src.items() if isinstance(v,dict)}
 eff_c={str(k):_sub_val(copy.deepcopy(v),params) for src in (prof_ctrls,raw_ctrls) if isinstance(src,dict) for k,v in src.items() if isinstance(v,dict)}
 res_c={cid:{**cm,"enforce":cm.get("enforce","release"),"requirement_ref":dr1_digest_fn({k:v for k,v in {**cm,"enforce":cm.get("enforce","release")}.items() if k not in ("note","requirement_ref")})} for cid,cm in eff_c.items()}
 return eff_r,res_c
def _parse_vc(vc: Any) -> dict[str, str]:
 if not isinstance(vc,dict) or set(vc)!=VC_KEYS or any(not isinstance(vc.get(k),str) or not SHA256_REF_RE.match(vc[k]) for k in VC_KEYS):
  raise ValueError("validity_context")
 return {k:str(vc[k]) for k in sorted(VC_KEYS)}
def _parse_arch(ac: Any) -> dict[str, str]:
 if not isinstance(ac,dict) or any(k not in ARCH_KEYS for k in ac):
  raise ValueError("archival")
 return {k:str(ac.get(k,"")).strip() for k in sorted(ARCH_KEYS)}
def _arch_complete(ac: dict[str, str]) -> bool:
 return bool(SHA256_REF_RE.match(ac.get("report_ref","")) and all(ac.get(k,"") for k in ("report_uri","retention_class","adapter_version","verifier_version")))
def load_study_receipts_core(events_paths: list[Path], decode_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
 out,errs=[],[]
 for sf in _collect_files(events_paths,".study.json"):
  try:
   doc=decode_fn(sf.read_text("utf-8"))
   if not isinstance(doc,dict) or any(k not in STUDY_KEYS for k in doc) or doc.get("schema")!="drift.study-receipt/1":raise ValueError("study_keys")
   cid,dig,sid=str(doc.get("contract","")),str(doc.get("digest","")),str(doc.get("study_id",""))
   sref,aref,pref,eref,outc=str(doc.get("subject_ref","")),str(doc.get("artifact_ref","")),str(doc.get("protocol_ref","")),str(doc.get("environment_ref","")),str(doc.get("outcome",""))
   if not ID_RE.match(cid) or not dig or not (ID_RE.match(sid) or WORD_RE.match(sid)) or not SHA256_REF_RE.match(sref) or (aref and not SHA256_REF_RE.match(aref)) or not SHA256_REF_RE.match(pref) or not SHA256_REF_RE.match(eref) or outc not in ("supported","insufficient_evidence","violated"):raise ValueError("study_envelope")
   ug=[str(x).strip() for x in (doc.get("user_groups") or []) if isinstance(x,str) and x.strip()]
   lims=[str(x).strip() for x in (doc.get("limitations") or []) if isinstance(x,str) and x.strip()]
   tasks_raw=doc.get("critical_tasks")
   if not ug or not lims or not isinstance(tasks_raw,list) or not tasks_raw:raise ValueError("study_lists")
   tasks=[]
   for t in tasks_raw:
    if not isinstance(t,dict) or set(t)!={"task_id","cases","participants","completed","use_errors","hazards_observed","outcome"} or not str(t["task_id"]).strip() or not isinstance(t["cases"],list):raise ValueError("study_task")
    part,comp,uerr,haz,tout = t["participants"],t["completed"],t["use_errors"],t["hazards_observed"],t["outcome"]
    if any(not isinstance(v,int) or isinstance(v,bool) or v < 0 for v in (part,comp,uerr,haz)) or part <= 0 or tout not in ("supported","insufficient_evidence","violated"):raise ValueError("study_task_vals")
    tasks.append({"cases":sorted({str(c) for c in t["cases"] if isinstance(c,str) and c.strip()}),"completed":comp,"hazards_observed":haz,"outcome":str(tout),"participants":part,"task_id":str(t["task_id"]).strip(),"use_errors":uerr})
   out.append({"schema":"drift.study-receipt/1","contract":cid,"digest":dig,"study_id":sid,"subject_ref":sref,**({"artifact_ref":aref} if aref else {}),"protocol_ref":pref,"user_groups":sorted(set(ug)),"environment_ref":eref,"validity_context":_parse_vc(doc.get("validity_context")),"critical_tasks":tasks,"limitations":lims,"archival":_parse_arch(doc.get("archival")),"outcome":outc})
  except Exception as exc: errs.append(f"{sf.name}: {exc}")
 return out,errs
def load_evaluation_receipts_core(events_paths: list[Path], decode_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
 out,errs=[],[]
 for ef in _collect_files(events_paths,".evaluation.json"):
  try:
   doc=decode_fn(ef.read_text("utf-8"))
   if not isinstance(doc,dict) or any(k not in EVAL_KEYS for k in doc) or doc.get("schema")!="drift.evaluation-receipt/1":raise ValueError("eval_keys")
   cid,dig,eid,sref,aref=str(doc.get("contract","")),str(doc.get("digest","")),str(doc.get("evaluation_id","")),str(doc.get("subject_ref","")),str(doc.get("artifact_ref",""))
   refs=[str(doc.get(k,"")) for k in ("config_ref","corpus_ref","protocol_ref","preprocessing_ref","reference_labels_ref","criteria_ref")]
   outc,crit,agg,sgs_raw=str(doc.get("outcome","")),doc.get("criteria"),doc.get("aggregate"),doc.get("subgroups")
   if not ID_RE.match(cid) or not dig or not (ID_RE.match(eid) or WORD_RE.match(eid)) or not SHA256_REF_RE.match(sref) or (aref and not SHA256_REF_RE.match(aref)) or not all(SHA256_REF_RE.match(r) for r in refs) or outc not in ("supported","insufficient_evidence","violated") or not isinstance(crit,dict) or not isinstance(agg,dict) or not isinstance(agg.get("sample_size"),int) or isinstance(agg.get("sample_size"),bool) or agg["sample_size"] <= 0 or not isinstance(sgs_raw,list) or not sgs_raw:raise ValueError("eval_envelope")
   nm=lambda m:{str(k):float(v) for k,v in (m or {}).items() if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(float(v))}
   if any(isinstance(m,dict) and len(nm(m))!=len(m) for m in (crit.get("min_metrics"),crit.get("max_metrics"),agg.get("metrics"),agg.get("ci_lower"),agg.get("ci_upper"))):raise ValueError("eval_metrics")
   sgs=[{"id":str(sg["id"]).strip(),"sample_size":sg["sample_size"],"min_sample_size":sg["min_sample_size"],"metrics":nm(sg.get("metrics")),"ci_lower":nm(sg.get("ci_lower")),"ci_upper":nm(sg.get("ci_upper")),"outcome":str(sg["outcome"])} for sg in sgs_raw if isinstance(sg,dict) and str(sg.get("id","")).strip() and isinstance(sg.get("sample_size"),int) and not isinstance(sg.get("sample_size"),bool) and sg["sample_size"] >= 0 and isinstance(sg.get("min_sample_size"),int) and not isinstance(sg.get("min_sample_size"),bool) and sg["min_sample_size"] > 0 and sg.get("outcome") in ("supported","insufficient_evidence","violated") and all(not isinstance(sg.get(mk),dict) or len(nm(sg.get(mk)))==len(sg[mk]) for mk in ("metrics","ci_lower","ci_upper"))]
   if len(sgs)!=len(sgs_raw):raise ValueError("eval_sg")
   se=_parse_stoch_exp(doc["stochastic_experiment"]) if "stochastic_experiment" in doc else None
   out.append({"schema":"drift.evaluation-receipt/1","contract":cid,"digest":dig,"evaluation_id":eid,"subject_ref":sref,**({"artifact_ref":aref} if aref else {}),"config_ref":refs[0],"corpus_ref":refs[1],"protocol_ref":refs[2],"preprocessing_ref":refs[3],"reference_labels_ref":refs[4],"criteria_ref":refs[5],"criteria":{"min_metrics":nm(crit.get("min_metrics")),"max_metrics":nm(crit.get("max_metrics")),"required_subgroups":sorted({str(x) for x in (crit.get("required_subgroups") or []) if isinstance(x,str) and x.strip()})},"aggregate":{"sample_size":int(agg["sample_size"]),"metrics":nm(agg.get("metrics")),"ci_lower":nm(agg.get("ci_lower")),"ci_upper":nm(agg.get("ci_upper"))},"subgroups":sgs,**({"stochastic_experiment":se} if se else {}),"validity_context":_parse_vc(doc.get("validity_context")),"archival":_parse_arch(doc.get("archival")),"outcome":outc})
  except Exception as exc: errs.append(f"{ef.name}: {exc}")
 return out,errs
STOCH_EXP_KEYS=frozenset(("experiment_id","experiment_plan_ref","data_ref","target_cases","target_outcomes","support_size","planned_shots","observed_shots","target_hits","stopping_rule","attempt_index","max_attempts","aggregation_rule","confidence_level","enforce","acquisition"))
STOCH_ACQ_KEYS=frozenset(("backend_id","backend_kind","config_ref","calibration_ref","batch_id","job_ids"))
def _parse_stoch_exp(se: Any) -> dict[str, Any]:
 if not isinstance(se,dict) or any(k not in STOCH_EXP_KEYS for k in se) or not isinstance(acq := se.get("acquisition"),dict) or set(acq)!=STOCH_ACQ_KEYS:raise ValueError("stoch_exp")
 eid,enf=str(se.get("experiment_id","")),str(se.get("enforce","release")).strip()
 tc,to,jbs=[x for x in (se.get("target_cases") or []) if isinstance(x,str) and ID_RE.match(x)],[x.strip() for x in (se.get("target_outcomes") or []) if isinstance(x,str) and x.strip()],[x.strip() for x in (acq.get("job_ids") or []) if isinstance(x,str) and x.strip()]
 ivals=[se.get(k) for k in ("support_size","planned_shots","observed_shots","target_hits","attempt_index","max_attempts")]
 cl=se.get("confidence_level")
 if not (ID_RE.match(eid) or WORD_RE.match(eid)) or not all(SHA256_REF_RE.match(str( r)) for r in (se.get("experiment_plan_ref"),se.get("data_ref"),acq.get("config_ref"),acq.get("calibration_ref"))) or not tc or len(tc)!=len(se.get("target_cases") or []) or not to or len(set(to))!=len(se.get("target_outcomes") or []) or not jbs or any(not isinstance(v,int) or isinstance(v,bool) for v in ivals) or ivals[0] <= len(to) or ivals[1] <= 0 or ivals[2] <= 0 or ivals[3] < 0 or ivals[3] > ivals[2] or ivals[4] < 1 or ivals[5] < 1 or ivals[4] > ivals[5] or se.get("stopping_rule") not in ("fixed_shots","sequential_confidence") or se.get("aggregation_rule") not in ("single_precommitted_run","pooled_batches") or isinstance(cl,bool) or not isinstance(cl,(int,float)) or not math.isfinite(float(cl)) or not (0.0 < float(cl) < 1.0) or enf not in ("execution","release") or not str(acq.get("backend_id","")).strip() or acq.get("backend_kind") not in ("hardware_qpu","noisy_simulator","statevector_simulator") or not str(acq.get("batch_id","")).strip():raise ValueError("stoch_fields")
 return {**se,"confidence_level":float(cl),"enforce":enf,"target_cases":sorted(set(tc)),"target_outcomes":sorted(set(to)),"acquisition":{**acq,"job_ids":sorted(set(jbs))}}
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
def load_ra_receipts_core(events_paths: list[Path], decode_fn: Any) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
 st_recs,st_errs=load_study_receipts_core(events_paths,decode_fn)
 ev_recs,ev_errs=load_evaluation_receipts_core(events_paths,decode_fn)
 return {"studies":st_recs,"evaluations":ev_recs},st_errs+ev_errs
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
from drift_verify_mig import run_ra_self_test_impl as run_ra_self_test,verify_ssh_sig_envelope_impl as _verify_ssh_sig_envelope
from drift_verify_sim import evaluate_detached_signatures_impl
def evaluate_detached_signatures_core(verdicts: list[dict[str, Any]], parsed_contracts: list[dict[str, Any]], args: Any, cfg_dig: str, decode_fn: Any, canonical_json_fn: Any, digest_matches_fn: Any) -> list[dict[str, Any]]:
 return evaluate_detached_signatures_impl(verdicts,parsed_contracts,args,cfg_dig,decode_fn,canonical_json_fn,digest_matches_fn,_collect_files,_verify_ssh_sig_envelope,SIG_ENV_KEYS,SIG_PAYLOAD_KEYS)
