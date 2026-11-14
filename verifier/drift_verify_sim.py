#!/usr/bin/env python3
"""DRIFT Independent Reference Simulation Receipt Verifier (MIT License)."""

from __future__ import annotations
import re
from pathlib import Path
from typing import Any
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DIGEST_RE = re.compile(r"^(?:dr1|dr2b):(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})$")
SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SIM_OPT_KEYS = frozenset(("observed_convergence","trajectory_stability"))
SIM_KEYS = frozenset((
    "schema","contract","digest","simulation_id","runner","runner_ref",
    "subject_ref","code_snapshot","covered_scope","cases",
    "tick_determinism","rollback_invariance","save_epoch_compatibility","outcome",
))
def _req_str_list(m: dict[str, Any], k: str) -> list[str]:
 v = m.get(k,[])
 if not isinstance(v,list) or any(not isinstance(x,str) or not x.strip() for x in v):raise ValueError(k)
 return [x.strip() for x in v]
def collect_sim_receipt_files(events_paths: list[Path]) -> list[Path]:
 out,seen = [],set()
 for p in events_paths:
  for f in (sorted(p.glob("*.sim.json")) if p.is_dir() else ([p] if p.is_file() and p.name.endswith(".sim.json") else [])):
   if f not in seen:seen.add(f); out.append(f)
 return out
def load_simulation_receipts_core(events_paths: list[Path], decode_fn: Any, valid_rel_scope_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
 from drift_verify_perf import parse_sim_opt_blocks
 out,errs = [],[]
 for sf in collect_sim_receipt_files(events_paths):
  try:
   doc = decode_fn(sf.read_text(encoding="utf-8"))
   if not isinstance(doc,dict) or not SIM_KEYS.issubset(doc) or any(k not in SIM_KEYS and k not in SIM_OPT_KEYS for k in doc) or doc.get("schema")!="drift.sim-receipt/1":raise ValueError("sim_keys")
   cid,dig,sid = str(doc.get("contract","")),str(doc.get("digest","")),str(doc.get("simulation_id",""))
   runner,rref,sref,csnap,outc = str(doc.get("runner","")),str(doc.get("runner_ref","")),str(doc.get("subject_ref","")),str(doc.get("code_snapshot","")),str(doc.get("outcome",""))
   if not ID_RE.match(cid) or not DIGEST_RE.match(dig) or not sid.strip() or not runner.strip() or not SHA256_REF_RE.match(rref) or not SHA256_REF_RE.match(sref) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})",csnap) or outc not in ("passed","violated","inconclusive"):raise ValueError("sim_envelope")
   cov,cs = doc.get("covered_scope"),doc.get("cases")
   if not isinstance(cov,list) or len(set(cov))!=len(cov) or not all(valid_rel_scope_fn(x) for x in cov):raise ValueError("covered_scope")
   if not isinstance(cs,list) or not cs or not all(isinstance(x,str) and ID_RE.match(x) for x in cs):raise ValueError("cases")
   td,ri,se = doc.get("tick_determinism"),doc.get("rollback_invariance"),doc.get("save_epoch_compatibility")
   if not isinstance(td,dict) or not isinstance(ri,dict) or not isinstance(se,dict):raise ValueError("sim_tables")
   seed_ref,inp_ref,traj_ref = str(td.get("seed_corpus_ref","")),str(td.get("input_stream_ref","")),str(td.get("trajectory_digest",""))
   ticks_exec,plats,div_ticks = td.get("ticks_executed"),_req_str_list(td,"platforms_compared"),td.get("divergent_ticks",[])
   if not SHA256_REF_RE.match(seed_ref) or not SHA256_REF_RE.match(inp_ref) or not SHA256_REF_RE.match(traj_ref) or not isinstance(ticks_exec,int) or isinstance(ticks_exec,bool) or ticks_exec < 0 or not isinstance(div_ticks,list) or any(not isinstance(dt,dict) or set(dt)!={"tick","case","expected_hash","observed_hash"} or isinstance(dt.get("tick"),bool) or not isinstance(dt.get("tick"),int) or dt["tick"] < 0 for dt in div_ticks):raise ValueError("tick_determinism")
   win_t,max_rb,resim_m,leaked_m = ri.get("windows_tested"),ri.get("max_rollback_frames"),ri.get("resim_mismatches"),ri.get("leaked_ambient_mutations")
   if any(not isinstance(v,int) or isinstance(v,bool) or v < 0 for v in (win_t,max_rb,resim_m,leaked_m)):raise ValueError("rollback_invariance")
   act_ep,cmp_ep,inc_ep,inv_chk = _req_str_list(se,"active_save_epochs"),_req_str_list(se,"compatible_epochs"),_req_str_list(se,"incompatible_epochs"),_req_str_list(se,"invariants_checked")
   opt_b = parse_sim_opt_blocks(doc)
   out.append({"schema":"drift.sim-receipt/1","contract":cid,"digest":dig,"simulation_id":sid,"runner":runner,"runner_ref":rref,"subject_ref":sref,"code_snapshot":csnap,"covered_scope":sorted(set(cov)),"cases":sorted(set(cs)),"tick_determinism":{"seed_corpus_ref":seed_ref,"input_stream_ref":inp_ref,"ticks_executed":ticks_exec,"platforms_compared":sorted(set(plats)),"trajectory_digest":traj_ref,"divergent_ticks":[{"case":str(x["case"]),"expected_hash":str(x["expected_hash"]),"observed_hash":str(x["observed_hash"]),"tick":int(x["tick"])} for x in div_ticks]},"rollback_invariance":{"leaked_ambient_mutations":leaked_m,"max_rollback_frames":max_rb,"resim_mismatches":resim_m,"windows_tested":win_t},"save_epoch_compatibility":{"active_save_epochs":sorted(set(act_ep)),"compatible_epochs":sorted(set(cmp_ep)),"incompatible_epochs":sorted(set(inc_ep)),"invariants_checked":sorted(set(inv_chk))},**opt_b,"outcome":outc})
  except Exception as exc:errs.append(f"{sf.name}: {exc}")
 return out,errs
def evaluate_contract_simulation_core(
    contract:dict[str,Any],sim_receipts:list[dict[str,Any]],policy:dict[str,Any] | None,
    expected_snapshot:str,expected_subject_ref:str,digest_matches_fn:Any,cov_matches_fn:Any,
) -> tuple[list[str],list[dict[str,Any]]]:
    pol = policy or {}
    req_sim = bool(contract.get("profile_simulation")) or (pol.get("pack")=="core@1" and pol.get("simulation")=="required")
    scope_code = contract.get("scope_code") or []
    raw_cases = contract.get("cases") or {}
    active_cases = {cid for cid,cm in raw_cases.items() if isinstance(cm,dict) and "status" not in cm}
    inv_keys = set(contract.get("invariants") or ())
    by_target:dict[str,dict[str,dict[str,Any]]] = {}
    for r in sim_receipts:
        if r["contract"]==contract["id"] and digest_matches_fn(r["digest"],contract["digest"]):
            tkey = r["simulation_id"]
            ikey = repr((r["runner"],r["runner_ref"],r["subject_ref"],r["code_snapshot"],r["covered_scope"],r["cases"],r["tick_determinism"],r["rollback_invariance"],r["save_epoch_compatibility"],r["outcome"]))
            by_target.setdefault(tkey,{})[ikey] = r
    if not by_target and not req_sim:
        return [],[]
    if not by_target and req_sim:
        return ["sim.missing"],[]
    eval_list,reasons,has_viol,has_inc = [],[],False,False
    for tkey in sorted(by_target):
        bucket = by_target[tkey]
        group = [bucket[k] for k in sorted(bucket)]
        has_conflict = len(group) > 1
        grp_viol,grp_evals = False,[]
        for rec in group:
            eff,rsn = rec["outcome"],""
            td,ri,se = rec["tick_determinism"],rec["rollback_invariance"],rec["save_epoch_compatibility"]
            if not scope_code or not all(any(cov_matches_fn(c,sc) for c in rec["covered_scope"]) for sc in scope_code) or not active_cases or not all(c in active_cases for c in rec["cases"]):
                eff,rsn = ("inconclusive" if eff=="passed" else eff),"sim.incomplete_scope"
            elif expected_snapshot and rec["code_snapshot"]!=expected_snapshot:
                eff,rsn = ("inconclusive" if eff=="passed" else eff),"sim.snapshot_mismatch"
            elif expected_subject_ref and rec["subject_ref"]!=expected_subject_ref:
                eff,rsn = ("inconclusive" if eff=="passed" else eff),"sim.subject_mismatch"
            elif td["divergent_ticks"]:
                eff,rsn = "violated","sim.desync_detected"
            elif ri["resim_mismatches"] > 0 or ri["leaked_ambient_mutations"] > 0:
                eff,rsn = "violated","sim.rollback_drift"
            elif se["incompatible_epochs"]:
                eff,rsn = "violated","sim.save_epoch_incompatible"
            elif td["ticks_executed"] <= 0 or not td["platforms_compared"] or ri["windows_tested"] <= 0 or ri["max_rollback_frames"] <= 0:
                eff,rsn = ("inconclusive" if eff=="passed" else eff),"sim.incomplete_scope"
            elif not se["active_save_epochs"] or not set(se["active_save_epochs"]).issubset(set(se["compatible_epochs"])) or not inv_keys.issubset(set(se["invariants_checked"])):
                eff,rsn = ("inconclusive" if eff=="passed" else eff),"sim.invariants_incomplete"
            else:
                from drift_verify_mig import eval_sim_opt_blocks
                eff,rsn = eval_sim_opt_blocks(rec,eff)
                if eff=="violated" and not rsn: rsn = "sim.violated"
            if eff=="violated":
                grp_viol = True
            grp_evals.append((rec,eff,rsn))
        for rec,eff0,rsn0 in grp_evals:
            eff,rsn = eff0,rsn0
            if has_conflict:
                if grp_viol:
                    eff = "violated"
                    rsn = rsn0 if (rsn0 and rsn0!="sim.violated") else "sim.conflicting_receipts"
                else:
                    eff,rsn = "inconclusive","sim.conflicting_receipts"
            item = {**rec,"effective_outcome":eff,"provenance":"measured"}
            if rsn:
                item["reason"] = rsn
            eval_list.append(item)
            if eff=="violated":
                has_viol = True
                if rsn and rsn not in reasons:
                    reasons.append(rsn)
                if has_conflict and "sim.conflicting_receipts" not in reasons:
                    reasons.append("sim.conflicting_receipts")
            elif eff!="passed":
                has_inc = True
                if rsn and rsn not in reasons:
                    reasons.append(rsn)
    if has_viol and "sim.violated" not in reasons:
        reasons.append("sim.violated")
    if has_inc and not has_viol and "sim.inconclusive" not in reasons:
        reasons.append("sim.inconclusive")
    return reasons,eval_list
def load_simulation_receipts_impl(events_paths: list[Path], decode_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
    from drift_verify_sec import _valid_rel_scope
    return load_simulation_receipts_core(events_paths,decode_fn,_valid_rel_scope)
def evaluate_contract_simulation_impl(
    contract:dict[str,Any],sim_receipts:list[dict[str,Any]],policy:dict[str,Any] | None,
    expected_snapshot:str,expected_subject_ref:str,digest_matches_fn:Any,
) -> tuple[list[str],list[dict[str,Any]]]:
    from drift_verify_sec import _cov_matches
    return evaluate_contract_simulation_core(contract,sim_receipts,policy,expected_snapshot,expected_subject_ref,digest_matches_fn,_cov_matches)
def order_shadow_shards_py(parsed_shards: list[Any], target_run_id: str = "") -> tuple[list[Any], list[str]]:
    sh_idxs,run_to_idx,dup_errs = [],{},[]
    for idx,item in enumerate(parsed_shards):
        sr = item[6]
        if item[2] and isinstance(sr,dict):
            rid = sr.get("run_id","")
            if rid in run_to_idx:
                dup_errs.append(f'shadow.duplicate_run_id: "{rid}"')
            run_to_idx[rid] = idx
            sh_idxs.append(idx)
    non_shadow = [s for s in parsed_shards if not (s[2] and isinstance(s[6],dict))]
    if dup_errs:
        return non_shadow,dup_errs
    clean_target = (target_run_id or "").strip()
    if not sh_idxs:
        return parsed_shards,[]
    rids = [parsed_shards[i][6]["run_id"] for i in sh_idxs]
    n,rid_pos = len(rids),{r:i for i,r in enumerate(rids)}
    prec = [[False] * n for _ in range(n)]
    for i,s_idx in enumerate(sh_idxs):
        for sup_id in (parsed_shards[s_idx][6].get("supersedes") or ()):
            if sup_id in rid_pos:
                prec[rid_pos[sup_id]][i] = True
    for i,s_i in enumerate(sh_idxs):
        seq_i = int(parsed_shards[s_i][6].get("sequence") or 0)
        for j,s_j in enumerate(sh_idxs):
            seq_j = int(parsed_shards[s_j][6].get("sequence") or 0)
            if i!=j and seq_i > 0 and seq_j > 0 and seq_i < seq_j and not prec[j][i]:
                prec[i][j] = True
    for k in range(n):
        for i in range(n):
            if prec[i][k]:
                for j in range(n):
                    if prec[k][j]:
                        prec[i][j] = True
    for i in range(n):
        if prec[i][i]:
            return non_shadow, [f'shadow.supersession_cycle: "{rids[i]}"']
    if clean_target:
        if clean_target not in rid_pos:
            return non_shadow, [f'shadow.unknown_run_id: "{clean_target}"']
        t_pos = rid_pos[clean_target]
        t_sr = parsed_shards[sh_idxs[t_pos]][6]
        keep_pos = [i for i in range(n) if i==t_pos or prec[i][t_pos]] if t_sr.get("selected_tests") else [t_pos]
    else:
        keep_pos = list(range(n))
    def _act_t(item:Any) -> set[str]:
        sel = set(item[6].get("selected_tests") or ())
        return sel if sel else set(item[4])
    for a_i,i in enumerate(keep_pos):
        t_i = _act_t(parsed_shards[sh_idxs[i]])
        for j in keep_pos[a_i + 1:]:
            if not prec[i][j] and not prec[j][i] and (t_i & _act_t(parsed_shards[sh_idxs[j]])):
                return non_shadow, [f'shadow.ambiguous_run_order: "{rids[i]}" and "{rids[j]}" touch common tests without supersession or --run-id']
    ordered_pos,placed = [],set()
    while len(ordered_pos) < len(keep_pos):
        ready = [p for p in keep_pos if p not in placed and not any(q not in placed and prec[q][p] for q in keep_pos)]
        if not ready:
            break
        ready.sort(key=lambda p:(int(parsed_shards[sh_idxs[p]][6].get("sequence") or 0),rids[p]))
        placed.add(ready[0])
        ordered_pos.append(ready[0])
    return non_shadow + [parsed_shards[sh_idxs[p]] for p in ordered_pos],[]
def _resolve_canon_res_py(area_id: str, raw_res: str, aliases: dict[str, str]) -> str:
 t = raw_res.strip()
 if not t:return ""
 if t in aliases and aliases[t].strip():return aliases[t].strip()
 if "#" in t:
  base,part = t.split("#",1)
  if base in aliases and aliases[base].strip():return f"{aliases[base].strip()}#{part}"
 return t if t.startswith("urn:") else f"urn:area:{area_id.strip() or 'default'}:{t}"
def _parse_comp_bundles_py(raw: Any) -> list[dict[str, Any]]:
 if not isinstance(raw,list):raise ValueError("composition_bundles")
 out = []
 for item in raw:
  if not isinstance(item,dict) or ("schema" in item and item["schema"]!="drift.boundary-bundle/1"):raise ValueError("composition_bundle")
  aid,ver,al_raw = str(item.get("area_id","")).strip(),str(item.get("version","")).strip(),item.get("resource_aliases") or {}
  if not aid or not ver or not isinstance(al_raw,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v.strip() for k,v in al_raw.items()):raise ValueError("composition_bundle_id")
  aliases = {k:v.strip() for k,v in al_raw.items()}
  def _specs(lst:Any) -> list[dict[str,Any]]:
   if not isinstance(lst,list):raise ValueError("behavior_specs")
   res_l = []
   for s in lst:
    if not isinstance(s,dict) or not str(s.get("operation","")).strip() or not str(s.get("resource","")).strip() or not isinstance(s.get("when_domain",[]),list) or not isinstance(s.get("then_domain",[]),list):raise ValueError("behavior_spec")
    res_l.append({"operation":str(s["operation"]).strip(),"resource":_resolve_canon_res_py(aid,str(s["resource"]).strip(),aliases),"when_domain":[str(x) for x in s.get("when_domain",[])],"then_domain":[str(x) for x in s.get("then_domain",[])]})
   return res_l
  sw,sr = item.get("shared_writes",[]),item.get("shared_reads",[])
  if not isinstance(sw,list) or not isinstance(sr,list):raise ValueError("shared_effects")
  out.append({"area_id":aid,"version":ver,"offers":_specs(item.get("offers",[])),"requires":_specs(item.get("requires",[])),"shared_writes":[_resolve_canon_res_py(aid,str(w),aliases) for w in sw],"shared_reads":[_resolve_canon_res_py(aid,str(r),aliases) for r in sr]})
 return out
def load_composition_manifests_core(events_paths: list[Path], decode_fn: Any) -> tuple[list[dict[str, Any]], list[str]]:
 from drift_verify_mig import collect_receipt_files
 out,errs,allowed = [],[],{"schema","contract","active_producers","active_consumers","retained_events","rollback_targets","declared_coordinators","critical_paths","pact_refs"}
 for cf in collect_receipt_files(events_paths,".composition.json"):
  try:
   doc = decode_fn(cf.read_text(encoding="utf-8"))
   if not isinstance(doc,dict) or any(k not in allowed for k in doc) or doc.get("schema")!="drift.composition-manifest/1":raise ValueError("composition_schema")
   pr_raw = doc.get("pact_refs",[])
   if not isinstance(pr_raw,list):raise ValueError("pact_refs")
   bad_pr = bool("pact_refs" in doc and (len(set(pr_raw))!=len(pr_raw) or any(not isinstance(x,str) or not re.fullmatch(r"dr2p:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})",x.strip()) for x in pr_raw)))
   cid = str(doc.get("contract","")).strip() if "contract" in doc else ""
   if "contract" in doc and not cid:raise ValueError("composition_contract")
   prods,cons,rbs = _parse_comp_bundles_py(doc.get("active_producers",[])),_parse_comp_bundles_py(doc.get("active_consumers",[])),_parse_comp_bundles_py(doc.get("rollback_targets",[]))
   ret_raw,coords_raw,cp_raw = doc.get("retained_events",[]),doc.get("declared_coordinators",{}),doc.get("critical_paths",[])
   if not isinstance(ret_raw,list) or not isinstance(coords_raw,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v.strip() for k,v in coords_raw.items()) or not isinstance(cp_raw,list):raise ValueError("composition_tables")
   ret_evs = [{"resource":str(re_it["resource"]).strip(),"epoch":str(re_it["epoch"]).strip(),"emitted_then":[str(x) for x in re_it["emitted_then"]]} for re_it in ret_raw if isinstance(re_it,dict) and str(re_it.get("resource","")).strip() and str(re_it.get("epoch","")).strip() and isinstance(re_it.get("emitted_then",[]),list)]
   if len(ret_evs)!=len(ret_raw):raise ValueError("retained_event")
   cpaths = []
   for cp in cp_raw:
    if not isinstance(cp,dict) or not str(cp.get("id","")).strip() or not isinstance(cp.get("stages"),list) or not isinstance(cp.get("budget_ms",0),int) or isinstance(cp.get("budget_ms",0),bool) or cp.get("budget_ms",0) < 0:raise ValueError("critical_path")
    stages = [{"area_id":str(st["area_id"]).strip(),"operation":str(st["operation"]).strip(),"p95_ms":st["p95_ms"],"idempotent":bool(st.get("idempotent",True)),"max_executions":st["max_executions"],"timeout_compensated":bool(st.get("timeout_compensated",True)),"confirmed_before_completion":bool(st.get("confirmed_before_completion",True))} for st in cp["stages"] if isinstance(st,dict) and str(st.get("area_id","")).strip() and str(st.get("operation","")).strip() and isinstance(st.get("p95_ms"),int) and not isinstance(st.get("p95_ms"),bool) and st["p95_ms"] >= 0 and isinstance(st.get("max_executions"),int) and not isinstance(st.get("max_executions"),bool) and st["max_executions"] >= 0]
    if len(stages)!=len(cp["stages"]):raise ValueError("stage")
    cpaths.append({"id":str(cp["id"]).strip(),"budget_ms":cp.get("budget_ms",0),"stages":stages})
   out.append({"schema":"drift.composition-manifest/1","contract":cid,"active_producers":prods,"active_consumers":cons,"retained_events":ret_evs,"rollback_targets":rbs,"declared_coordinators":{k:v.strip() for k,v in coords_raw.items()},"critical_paths":cpaths,"bad_pact_ref":bad_pr})
  except Exception as exc:errs.append(f"{cf.name}: {exc}")
 return out,errs
def evaluate_federated_composition_py(m: dict[str, Any]) -> dict[str, Any]:
 reasons:list[str] = []
 def _add(r:str) -> None:
  if r and r not in reasons:reasons.append(r)
 if m.get("schema")!="drift.composition-manifest/1":_add("federation.invalid_manifest_schema")
 if m.get("bad_pact_ref"):_add("federation.invalid_pact_ref")
 checked_pairs = 0
 def _check_pair(prod:dict[str,Any],cons:dict[str,Any],is_rb:bool) -> int:
  pairs,p_lbl,c_lbl = 0,f"{prod['area_id']}@{prod['version']}",f"{cons['area_id']}@{cons['version']}"
  for req in cons.get("requires",()):
   for off in prod.get("offers",()):
    if req["resource"]!=off["resource"] or req["operation"]!=off["operation"]:continue
    pairs += 1
    for w in req["when_domain"]:
     if w not in off["when_domain"]:_add(f"federation.rollback_incompatible:{p_lbl}:{c_lbl}:{req['resource']}" if is_rb else f"federation.request_rejected:{c_lbl}->{p_lbl}:{req['resource']}:{w}")
    for t in off["then_domain"]:
     if t not in req["then_domain"]:_add(f"federation.rollback_incompatible:{p_lbl}:{c_lbl}:{req['resource']}" if is_rb else f"federation.response_unhandled:{p_lbl}->{c_lbl}:{req['resource']}:{t}")
  return pairs
 for p in m.get("active_producers",()):
  for c in m.get("active_consumers",()):checked_pairs += _check_pair(p,c,False)
 all_cons = list(m.get("active_consumers",())) + [rb for rb in m.get("rollback_targets",()) if rb.get("requires")]
 for ev in m.get("retained_events",()):
  for c in all_cons:
   c_lbl = f"{c['area_id']}@{c['version']}"
   for req in c.get("requires",()):
    if req["resource"]==ev["resource"]:
     for t in ev["emitted_then"]:
      if t not in req["then_domain"]:_add(f"federation.retained_event_incompatible:{c_lbl}:{ev['resource']}:{ev['epoch']}:{t}")
 for rb in m.get("rollback_targets",()):
  if rb.get("offers"):
   for c in m.get("active_consumers",()):checked_pairs += _check_pair(rb,c,True)
  if rb.get("requires"):
   for p in m.get("active_producers",()):checked_pairs += _check_pair(p,rb,True)
 writers_by_res:dict[str,set[str]] = {}
 for b in [*m.get("active_producers",()),*m.get("active_consumers",())]:
  for w in b.get("shared_writes",()):writers_by_res.setdefault(w,set()).add(b["area_id"])
 shared_conflicts:list[str] = []
 coords = m.get("declared_coordinators") or {}
 for res in sorted(writers_by_res):
  writers = sorted(writers_by_res[res])
  if len(writers) > 1 and res not in coords:
   code = f"federation.shared_effect_conflict:{res}:{','.join(writers)}"; shared_conflicts.append(code); _add(code)
 cp_results:dict[str,bool] = {}
 for cp in m.get("critical_paths",()):
  p_ok,tot_p95 = True,0
  for st in cp.get("stages",()):
   tot_p95 += int(st["p95_ms"])
   for cond,tag in ((int(st["max_executions"]) > 1 and not st.get("idempotent",True),"double_effect"),(not st.get("timeout_compensated",True),"uncompensated_timeout"),(not st.get("confirmed_before_completion",True),"premature_confirmation")):
    if cond:p_ok = False; _add(f"federation.critical_path_violated:{cp['id']}:{tag}:{st['operation']}")
  if int(cp.get("budget_ms",0)) > 0 and tot_p95 > int(cp["budget_ms"]):
   p_ok = False; _add(f"federation.path_budget_exceeded:{cp['id']}:{tot_p95}>{cp['budget_ms']}")
  cp_results[cp["id"]] = p_ok
 reasons.sort()
 return {"schema":"drift.composition-manifest/1","ok":not reasons,"reasons":reasons,"checked_pairs":checked_pairs,"shared_effect_conflicts":shared_conflicts,"critical_path_results":cp_results}
def evaluate_contract_composition_core(contract: dict[str, Any], manifests: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
 cid = contract["id"]
 applicable = [m for m in (manifests or ()) if not m.get("contract") or m.get("contract")==cid]
 if not applicable:return [],[]
 reasons,verdicts = [],[]
 for m in applicable:
  v = evaluate_federated_composition_py(m); verdicts.append(v)
  for r in v["reasons"]:
   if r not in reasons:reasons.append(r)
 return reasons,verdicts
def evaluate_detached_signatures_impl(verdicts: list[dict[str, Any]], parsed_contracts: list[dict[str, Any]], args: Any, cfg_dig: str, decode_fn: Any, canonical_json_fn: Any, digest_matches_fn: Any, collect_files_fn: Any, verify_sig_fn: Any, sig_env_keys: Any, sig_payload_keys: Any) -> list[dict[str, Any]]:
 sig_paths = list(args.events or []) + ([args.signatures] if getattr(args,"signatures",None) else [])
 sig_files,sig_pol_file = collect_files_fn(sig_paths,".sig.json"),getattr(args,"signature_policy",None)
 if not sig_files and not sig_pol_file:return verdicts
 envelopes = []
 for sf in sig_files:
  doc = decode_fn(sf.read_text("utf-8"))
  if not isinstance(doc,dict) or set(doc)!=sig_env_keys or doc.get("schema")!="drift.signature-envelope/1":raise ValueError("sig_env")
  pl,sig_arm = doc.get("payload"),str(doc.get("signature","")).strip()
  if not isinstance(pl,dict) or set(pl)!=sig_payload_keys or pl.get("schema")!="drift.signature-payload/1" or not sig_arm.startswith("-----BEGIN SSH SIGNATURE-----"):raise ValueError("sig_payload")
  norm_pl = {k:str(pl[k]).strip() for k in sig_payload_keys}
  if any(not norm_pl[k] for k in sig_payload_keys) or norm_pl["target_kind"] not in ("contract","review_snapshot","attestation"):raise ValueError("sig_fields")
  envelopes.append((norm_pl,sig_arm))
 pol_spec = {"active":False,"required_meanings":[],"min_signers":1,"distinct_signers":True,"enforce":"release"}
 if sig_pol_file:
  if not sig_pol_file.is_file():raise ValueError("missing_sig_policy")
  pdoc = decode_fn(sig_pol_file.read_text("utf-8"))
  if not isinstance(pdoc,dict) or pdoc.get("schema")!="drift.signature-policy/1":raise ValueError("invalid_sig_policy")
  enf = str(pdoc.get("enforce","release")).strip()
  pol_spec = {"active":True,"required_meanings":[str(x).strip() for x in (pdoc.get("required_meanings") or []) if str(x).strip()],"min_signers":max(1,int(pdoc.get("min_signers",1))),"distinct_signers":bool(pdoc.get("distinct_signers",True)),"enforce":(enf if enf in ("execution","release") else "release")}
 by_id,phase = {c["id"]:c for c in parsed_contracts},(getattr(args,"phase","") or "")
 enforced_now = phase=="release" or (pol_spec["active"] and pol_spec["enforce"]=="execution")
 for v in verdicts:
  c = by_id.get(v["id"],{})
  if not enforced_now and not envelopes:
   v["signature_verification"] = {"ok":True,"reasons":[],"signatures":[],"status":"pending_release","total":0}; continue
  ctrls_m = c.get("controls") or {}
  exp_ctx = next((str(ctrls_m[k].get("context_ref","")).strip() for k in sorted(ctrls_m) if isinstance(ctrls_m[k],dict) and str(ctrls_m[k].get("context_ref","")).strip()),"")
  eval_sigs,rsn,valid_signers,cov_meanings,valid_cnt = [],[],{},set(),0
  has_own_env = any(pl["target_kind"]=="contract" and (digest_matches_fn(pl["target_ref"],v["digest"]) or pl["target_ref"]==v["digest"]) for pl,_ in envelopes)
  for pl,sig_txt in envelopes:
   if pl["target_kind"]!="contract" or (has_own_env and not digest_matches_fn(pl["target_ref"],v["digest"]) and pl["target_ref"]!=v["digest"]):continue
   ok,s_rsn = verify_sig_fn(pl,sig_txt,getattr(args,"trust_root",None),getattr(args,"verify_time",""),canonical_json_fn)
   if ok and ((not digest_matches_fn(pl["target_ref"],v["digest"]) and pl["target_ref"]!=v["digest"]) or (cfg_dig and not digest_matches_fn(pl["policy_ref"],cfg_dig) and pl["policy_ref"]!=cfg_dig) or (exp_ctx and pl["context_ref"] not in ("none",exp_ctx))):ok,s_rsn = False,"signature.target_mismatch"
   if ok:valid_cnt += 1; valid_signers[pl["signer"]] = valid_signers.get(pl["signer"],0) + 1; cov_meanings.add(pl["meaning"])
   elif s_rsn and s_rsn not in rsn:rsn.append(s_rsn)
   eval_sigs.append({**{k:pl[k] for k in ("context_ref","meaning","policy_ref","signed_at","signer","target_kind","target_ref")},"valid":ok,**({"reason":s_rsn} if s_rsn else {})})
  if pol_spec["active"]:
   for tag,cond in (("signature.duplicate_signer",pol_spec["distinct_signers"] and any(cnt > 1 for cnt in valid_signers.values())),("signature.meaning_missing",any(m not in cov_meanings for m in pol_spec["required_meanings"])),("signature.quorum_unmet",(len(valid_signers) if pol_spec["distinct_signers"] else valid_cnt) < pol_spec["min_signers"])):
    if cond and tag not in rsn:rsn.append(tag)
  elif valid_cnt==0 and "signature.invalid" not in rsn:rsn.append("signature.invalid")
  if enforced_now:
   for r in rsn:
    if r not in v["reasons"]:v["reasons"].append(r)
   v["ok"] = not v["reasons"] and valid_cnt > 0
  v["signature_verification"] = {"ok":not rsn and valid_cnt > 0,"reasons":([] if not enforced_now else rsn),"signatures":eval_sigs,"status":("verified" if not rsn and valid_cnt > 0 else ("pending_release" if not enforced_now else "violated")),"total":len(eval_sigs)}
 return verdicts
