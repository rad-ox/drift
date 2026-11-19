#!/usr/bin/env python3
import sys
if sys.version_info < (3, 11):
 sys.stderr.write(f"drift_verify: Python 3.11+ required (found {sys.version_info.major}.{sys.version_info.minor})\n")
 sys.exit(2)
import argparse,hashlib,json,os,tomllib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from drift_verify_base import DIGEST_RE,ENV_KEYS,ID_RE,SAFE_INT,SNAPSHOT_RE,WORD_RE,_decode_no_dup_keys,_has_approval_blocker,_is_unanchored_prose_source,_proof_rank,canonical_json,digest_matches,dr1_digest,dr1_ref,jcs_number,jcs_string
from drift_verify_03 import verify_contract_03_toml
from drift_verify_obs import obs03,red03
from drift_verify_subject import lookup_registered_shadow_py,order_shadow_shards_py,parse_security_lock_impl,parse_subject_manifest_impl,resolve_shadow_roots_impl,resolve_verifier_subject_cli,shadow_inputs_fresh,strip_outside_digest_impl,validate_inventory_text_impl,verify_config_toml_impl
from drift_verify_mutation import evaluate_contract_mutations_impl,load_mutation_events_impl,validate_mutation_manifest_impl
from drift_verify_parity import evaluate_contract_composition_core,evaluate_contract_parity_impl,extract_contract_cutover,load_composition_manifests_core,load_parity_receipts_impl
from drift_verify_perf import evaluate_contract_budgets,extract_contract_budgets,load_measurement_bundle
from drift_verify_sec import evaluate_contract_formal_impl,evaluate_contract_migration_impl,evaluate_contract_security_impl,extract_contract_formal,load_formal_receipts_impl,load_migration_receipts_impl,load_security_receipts_impl
from drift_verify_sim import evaluate_contract_simulation_impl,load_simulation_receipts_impl
from drift_verify_ssh import apply_openssh_trust_verdicts,load_merged_profile_impl
from drift_verify_ra import evaluate_contract_ra_bundle,evaluate_detached_signatures_core,extract_contract_risks_and_controls,load_ra_receipts_core
from drift_verify_grant import evaluate_grant_verdicts_py
from drift_verify_pact import evaluate_pact_verdicts_py
from drift_verify_dist import evaluate_break_glass_py,evaluate_containment_py,evaluate_role_signatures_py,evaluate_shard_bundles_py
from drift_verify_selftest import run_ra_self_test_impl as run_ra_self_test,run_sec_self_test_core,run_verifier_self_test as _run_verifier_self_test
OUTCOMES = {"passed","failed","skipped","disabled","interrupted","timeout"}
EVENT_KEYS = {"test","contract","cases","level","outcome","read","digest","schema","capabilities","observations"}
def run_sec_self_test(ck, digest_matches_fn): return run_sec_self_test_core(ck, digest_matches_fn, evaluate_contract_security_impl, sys.modules[__name__])
def run_verifier_self_test(): return _run_verifier_self_test(sys.modules[__name__])
def validate_event_line(line):
 doc = _decode_no_dup_keys(line)
 if not isinstance(doc,dict) or any(k not in EVENT_KEYS for k in doc) or any(r not in doc for r in ("test","contract","cases","level","outcome")):raise ValueError("event")
 cs,rd,dig,sch,caps = doc["cases"],doc.get("read",[]),doc.get("digest",""),doc.get("schema",""),doc.get("capabilities",[])
 if not isinstance(doc["test"],str) or not doc["test"].strip() or not isinstance(doc["contract"],str) or not ID_RE.match(doc["contract"]) or not isinstance(cs,list) or not cs or len(set(cs)) != len(cs) or not all(isinstance(c,str) and ID_RE.match(c) for c in cs) or not isinstance(doc["level"],str) or not WORD_RE.match(doc["level"]) or doc["outcome"] not in OUTCOMES or not isinstance(rd,list) or len(set(rd)) != len(rd) or not all(isinstance(r,str) and r in cs for r in rd) or (dig != "" and (not isinstance(dig,str) or not DIGEST_RE.match(dig))) or (sch != "" and sch != "0.3") or not isinstance(caps,list) or not all(isinstance(cp,str) and cp.strip() for cp in caps):raise ValueError("event")
 return {"test":doc["test"],"contract":doc["contract"],"cases":cs,"level":doc["level"],"outcome":doc["outcome"],"read":rd,"digest":dig,"schema":sch,"capabilities":caps,**obs03(doc,cs,sch)}
def validate_inventory_text(text): return validate_inventory_text_impl(text, _decode_no_dup_keys)
def validate_inventory_sidecar(path): return validate_inventory_text(path.read_text("utf-8"))
def resolve_shadow_roots(path, state_dir=""): return resolve_shadow_roots_impl(path, state_dir)
def verify_config_toml(path): return verify_config_toml_impl(path, dr1_digest, dr1_ref)
def _load_merged_profile(prof_ref, profiles_dir): return load_merged_profile_impl(prof_ref, profiles_dir, _proof_rank)
def _strip_outside_digest(cases, decs): strip_outside_digest_impl(cases, decs, _is_unanchored_prose_source)
def verify_contract_toml(path, profiles_dir):
 raw = tomllib.loads(path.read_text("utf-8"))
 if raw.get("drift") != "0.3":
  roots = resolve_shadow_roots(path)
  return {"drift":str(raw.get("drift","")),"id":str(raw.get("id",path.stem)),"digest":"","ref":"","approval":"invalid","approver":"","profile_proof":"","profile_security":[],"profile_simulation":False,"scope_code":[],"scope_reads":[],"scope_writes":[],"invariants":[],"cases":{},"budgets":{},"formal":{},"cutover":{},"risks":{},"controls":{},"required_capabilities":[],"area_root":roots["source_root"],"shadow_area_root":roots["area_root"],"open_cnt":0,"exec_blk":False,"rel_blk":False}
 return verify_contract_03_toml(raw,path,profiles_dir,canonical_json,dr1_ref,_proof_rank,resolve_shadow_roots)
def load_proof_events(events_paths, area_root=None, target_run_id=""):
 shards = [f for p in events_paths for f in (sorted(p.glob("*.jsonl")) if p.is_dir() else ([p] if p.is_file() and p.name.endswith(".jsonl") else []))]
 events,gone,inc,errs,snaps,ssub,all_snap,sh_hashes,pshs,cl_l = [],{},0,[],set(),set(),bool(shards),[],[],{}
 for sf in shards:
  raw,mp = sf.read_bytes(),sf.with_suffix(".meta.json")
  sh_hashes.append("sha256:" + hashlib.sha256(raw).hexdigest())
  has_inv,c_set,t_set,snap,sr,sref,unev,cont_s = mp.is_file(),set(),set(),"",None,"",[],set()
  if has_inv:
   try:
    inv = validate_inventory_sidecar(mp); c_set,t_set,snap,sr,sref,cont_s = set(inv["classes"]),set(inv["tests"]),inv["snapshot"],inv.get("shadow_run"),inv.get("subject_ref",""),set(inv.get("containment") or ())
    unev = [*(["touched"] if "touched" in inv else []),*(["pack_ref"] if inv.get("pack_ref") else [])]
   except Exception as exc: errs.append(f"{mp.name}: {exc}"); all_snap = False; continue
  else:all_snap = False
  if sr and not shadow_inputs_fresh(sr,sf,area_root):continue
  pshs.append((sf,raw,has_inv,c_set,t_set,snap,sr,sref,unev,cont_s))
 ordered_shards,sh_errs = order_shadow_shards_py([x[:8] for x in pshs],target_run_id)
 unev_by_sf = {x[0]:x[8] for x in pshs}
 cont_by_sf = {x[0]:x[9] for x in pshs}
 errs.extend(sh_errs)
 snap_union = {}
 for _,_,has_inv,c_set,t_set,snap,sr,_ in ordered_shards:
  if has_inv and snap and not sr:
   uc,ut = snap_union.setdefault(snap,(set(),set())); uc |= c_set; ut |= t_set
 eff_shards = []
 for sf,raw,has_inv,c_set,t_set,snap,sr,sref in ordered_shards:
  if has_inv and snap and not sr and snap in snap_union:c_set,t_set = set(snap_union[snap][0]),set(snap_union[snap][1])
  else:c_set,t_set = set(c_set),set(t_set)
  sel_t = set(sr.get("selected_tests") or ()) if isinstance(sr,dict) else set()
  by_cl = {}
  for t in t_set:
   if "#" in t:by_cl.setdefault(t.split("#",1)[0],set()).add(t)
  for cls in c_set:
   cur_t = by_cl.get(cls,set())
   if sel_t and (prev_t := cl_l.get(cls)):
    keep = {pt for pt in prev_t if pt not in sel_t}
    t_set |= keep; cur_t = cur_t | keep
   cl_l[cls] = cur_t
  eff_shards.append((sf,raw,has_inv,c_set,t_set,snap,sref))
 for sf,raw,has_inv,c_set,t_set,snap,sref in eff_shards:
  if snap:snaps.add(snap)
  else:all_snap = False
  if sref:ssub.add(sref)
  cnt,u_toks = 0,unev_by_sf.get(sf,())
  for idx,line in enumerate(raw.decode("utf-8").splitlines(),1):
   if not line.strip():continue
   try:ev = validate_event_line(line)
   except Exception as exc: errs.append(f"events:{sf.name}:{idx}: DR-E701 {exc}"); continue
   if u_toks:ev["_unev"] = u_toks
   ev["_containment"] = cont_by_sf.get(sf,set())
   cnt += 1; tid = ev["test"].split("[",1)[0]; cls = tid.split("#",1)[0] if "#" in tid else ""
   if not has_inv or cls not in c_set or tid not in t_set or tid not in cl_l.get(cls,()):gone[ev["contract"]] = gone.get(ev["contract"],0) + 1
   else:events.append(ev)
  if has_inv and snap and t_set and cnt == 0:inc += 1
 (sec_recs,sec_errs),(form_recs,form_errs),(par_recs,par_errs),(mig_recs,mig_errs),(sim_recs,sim_errs) = (fn(events_paths,_decode_no_dup_keys) for fn in (load_security_receipts_impl,load_formal_receipts_impl,load_parity_receipts_impl,load_migration_receipts_impl,load_simulation_receipts_impl))
 errs.extend(sec_errs + form_errs + par_errs + mig_errs + sim_errs)
 return events,gone,inc,errs,sec_recs,form_recs,par_recs,mig_recs,ssub,(next(iter(snaps)) if all_snap and inc == 0 and events and len(snaps) == 1 else ""),sh_hashes,sorted(snaps),bool(all_snap and shards)
def validate_mutation_manifest(text): return validate_mutation_manifest_impl(text, _decode_no_dup_keys)
def load_mutation_events(paths, manifest): return load_mutation_events_impl(paths, manifest, _decode_no_dup_keys)
def evaluate_contract_mutations(contract, manifest, latest_mut, mut_errors): return evaluate_contract_mutations_impl(contract, manifest, latest_mut, mut_errors, digest_matches)
def evaluate_contract(contract, cfg_state, events, gone, incomplete_shards, ev_errors, policy=None, min_proof="verified", phase="", total_open=None, mutations_ok=False, perf_bundle=None, expected_subject=None, sec_receipts=None, expected_snapshot="", formal_receipts=None, shard_subject_refs=None, manifest_sources=None, parity_receipts=None, mig_receipts=None, allow_exec_reuse=False, base_contract=None, release_attest=False, sim_receipts=None, ra_receipts=None, comp_manifests=None):
 cid,dig,pol = contract["id"],contract["digest"],policy or {}
 is_03,req_caps = contract.get("drift") == "0.3",set(contract.get("required_capabilities") or ())
 pol_on,curr_m,base_m,ignored,latest,sup,hs_bad,unev_s = pol.get("pack") == "core@1",[],[],0,{},0,False,set()
 base_dig = base_contract.get("digest","") if isinstance(base_contract,dict) else ""
 base_caps = set((base_contract or {}).get("required_capabilities") or ())
 same_env = bool(allow_exec_reuse and base_contract and base_contract.get("id") == cid and base_dig and base_dig != dig and contract.get("reuse_env") and contract.get("reuse_env") == base_contract.get("reuse_env"))
 for ev in events:
  if ev["contract"] == cid:
   unev_s.update(ev.get("_unev") or ())
   if digest_matches(ev["digest"],dig):
    if is_03 and (ev.get("schema") != "0.3" or not req_caps.issubset(set(ev.get("capabilities") or ()))):hs_bad = True; continue
    curr_m.append(ev)
   elif allow_exec_reuse and base_dig and digest_matches(ev["digest"],base_dig):
    if base_contract.get("drift") == "0.3" and (ev.get("schema") != "0.3" or not base_caps.issubset(set(ev.get("capabilities") or ()))):ignored += 1; continue
    base_m.append(ev)
   else:ignored += 1
 for ev in curr_m:sup += 1 if ev["test"] in latest else 0; latest[ev["test"]] = red03(contract,ev)
 if same_env and base_m:
  b_lat,t_sigs,b_sigs = {},contract.get("case_reuse_sigs") or {},base_contract.get("case_reuse_sigs") or {}
  for bev in base_m:b_lat[bev["test"]] = red03(base_contract,bev)
  curr_cov = {(kc,ev["level"]) for ev in latest.values() for kc in ev["cases"]}
  unch = {kc for kc,sg in t_sigs.items() if sg and sg == b_sigs.get(kc)}
  for tid,bev in b_lat.items():
   if tid not in latest and bev["outcome"] == "passed" and not bev["red"] and all(kc in unch for kc in bev["cases"]):
    if any((kc,lv) not in curr_cov and (lv == "*" or bev["level"] == lv) for kc in bev["cases"] for lv in (contract["cases"][kc].get("at") or ["*"])):latest[tid] = bev
 active,res,rsn,by_case = list(latest.values()),[],[],{}
 has_orphan = any(kc not in contract["cases"] for ev in active for kc in ev["cases"])
 for ev in active:
  for kc in ev["cases"]:by_case.setdefault(kc,[]).append(ev)
 for case_id in sorted(contract["cases"]):
  cm = contract["cases"][case_id]
  if isinstance(cm,dict) and "status" in cm:continue
  c_evs = by_case.get(case_id,())
  for lv in (cm.get("at") or ["*"]):
   cov = c_evs if lv == "*" else [ev for ev in c_evs if ev["level"] == lv]
   res.append({"case":case_id,"level":lv,"state":"missing" if not cov else ("red" if any(ev["outcome"] != "passed" or case_id in ev["red"] for ev in cov) else ("verified" if any(case_id in ev["read"] for ev in cov) else "bound"))})
 if cfg_state == "missing":rsn.append("config.missing")
 elif cfg_state != "current":rsn.extend((["config.findings"] if cfg_state == "stale" else []) + [f"config.approval.{cfg_state}"])
 if contract["approval"] != "current":rsn.extend((["contract.findings"] if contract["approval"] == "stale" else []) + [f"contract.approval.{contract['approval']}"])
 elif pol_on and isinstance(pol.get("approvers"),list) and pol["approvers"] and contract.get("approver","") not in pol["approvers"]:rsn.append("contract.approval.unlisted")
 if pol_on and isinstance(pol.get("max_open"),int) and not isinstance(pol.get("max_open"),bool) and pol["max_open"] > 0 and contract.get("open_cnt",0) > 0 and (contract.get("open_cnt",0) if total_open is None else total_open) > pol["max_open"]:rsn.append("policy.max_open")
 if contract.get("exec_blk"):rsn.append("contract.blocked.execution")
 if phase == "release" and contract.get("rel_blk"):rsn.append("contract.blocked.release")
 if ev_errors or hs_bad:rsn.append("events.invalid")
 if incomplete_shards > 0:rsn.append("shard.incomplete")
 eff_rank = max(_proof_rank(min_proof),_proof_rank(str(pol.get("proof","")) if pol_on else ""),_proof_rank(str(contract.get("profile_proof","")))) or 1
 if has_orphan or incomplete_shards > 0 or not res or any(r["state"] not in (("verified",) if eff_rank >= 2 else ("verified","bound")) for r in res) or (eff_rank >= 3 and not mutations_ok):rsn.append("proof.not_green")
 p_rsn,pend_b,p_sum = evaluate_contract_budgets(contract,phase,perf_bundle,expected_subject,digest_matches,pol)
 s_rsn,s_checks = evaluate_contract_security_impl(contract,sec_receipts or [],pol if pol_on else {},expected_snapshot,digest_matches,expected_subject,allow_exec_reuse and phase != "release",base_contract)
 exp_sref = (expected_subject or {}).get("artifact_ref","")
 f_rsn,pend_f,f_checks = evaluate_contract_formal_impl(contract,formal_receipts or [],phase,exp_sref,expected_snapshot,shard_subject_refs or set(),contract.get("area_root"),manifest_sources,digest_matches)
 m_rsn,m_checks = evaluate_contract_migration_impl(contract,mig_receipts or [],pol if pol_on else {},expected_snapshot,exp_sref,digest_matches)
 sim_rsn,sim_checks = evaluate_contract_simulation_impl(contract,sim_receipts or [],pol if pol_on else {},expected_snapshot,exp_sref,digest_matches)
 par_rsn,par_checks = evaluate_contract_parity_impl(contract,parity_receipts or [],phase,digest_matches,exp_sref,shard_subject_refs or set(),m_checks)
 comp_rsn,comp_checks = evaluate_contract_composition_core(contract,comp_manifests or [])
 ra_rsn,ra_extra = evaluate_contract_ra_bundle(contract,res,s_checks,f_checks,m_checks,ra_receipts,exp_sref,phase,mutations_ok,digest_matches)
 for r in (*p_rsn,*s_rsn,*f_rsn,*par_rsn,*m_rsn,*sim_rsn,*comp_rsn,*ra_rsn):
  if r not in rsn:rsn.append(r)
 if phase == "release" and release_attest and (expected_subject or {}).get("has_manifest") and not (expected_subject or {}).get("binary_ref") and "trust.artifact_required" not in rsn:rsn.append("trust.artifact_required")
 out = {"id":cid,"digest":dig,"ref":contract["ref"],"approval":contract["approval"],"ok":not rsn,"reasons":rsn,"ignored":ignored,"superseded":sup,"gone":gone,"results":res,**ra_extra}
 for k,v in (("assurance_digest",contract.get("assurance_digest")),("assurance_ref",contract.get("assurance_ref")),("performance",p_sum),("pending_budgets",pend_b),("pending_formal",pend_f),("security_checks",s_checks),("formal_checks",f_checks),("parity_checks",par_checks),("migration_checks",m_checks),("simulation_checks",sim_checks),("composition_checks",comp_checks),("unevaluated",sorted(unev_s))):
  if v:out[k] = v
 return out
def main(argv):
 if "--self-test" in argv:
  return run_verifier_self_test()
 ap = argparse.ArgumentParser(prog="drift_verify.py")
 ap.add_argument("targets",nargs="*",type=Path)
 for fl in ("--state-dir","--config","--profiles","--mutants","--measurements","--subject","--security-lock","--base","--attest","--attest-sig","--trust-root","--signatures","--signature-policy","--grant-lock"):ap.add_argument(fl,type=Path)
 for fl in ("--events","--mutation-events","--pact-lock"):ap.add_argument(fl,type=Path,action="append")
 ap.add_argument("--changed",action="append",default=[])
 for fl in ("--changed-none","--json","--allow-break-glass"):ap.add_argument(fl,action="store_true")
 for fl in ("--subject-artifact","--subject-tree","--run-id","--verify-time","--phase"):ap.add_argument(fl,default="")
 ap.add_argument("--min-proof",choices=("bound","verified","killed"),default="")
 a = ap.parse_args(argv)
 ex_sd = str(a.state_dir) if a.state_dir else ""
 sd_p = Path(sd_e) if (sd_e := ex_sd or os.environ.get("DRIFT_STATE_DIR","").strip() or lookup_registered_shadow_py(Path.cwd())) else None
 tgts,cfg_p,ev_p = a.targets or ([sd_p / ".drift" / "contracts"] if sd_p else []),a.config or ((sd_p / ".drift" / "config.toml") if sd_p else None),a.events or ([sd_p / ".drift-work" / "events"] if sd_p and (sd_p / ".drift-work" / "events").is_dir() else [])
 if not tgts or not cfg_p or not ev_p: ap.error("targets, --config and --events are required")
 if bool(a.mutants) != bool(a.mutation_events):ap.error("--mutants and --mutation-events must be supplied together")
 try:roots = resolve_shadow_roots(tgts[0],ex_sd)
 except Exception as exc: print(f"drift_verify.py: {exc}", file=sys.stderr); return 2
 cfg_st,cfg_dig,pol = verify_config_toml(cfg_p)
 p_dir,c_files = a.profiles or (cfg_p.parent / "profiles"),[cf for t in tgts for cf in (sorted(t.glob("*.toml")) if t.is_dir() else [t])]
 evs,gone,inc,ev_errs,sec_recs,form_recs,par_recs,mig_recs,ssub,exp_snap,sh_h,sn_l,sn_ok = load_proof_events(ev_p,roots["area_root"],"" if a.measurements else a.run_id)
 ra_recs,ra_errs = load_ra_receipts_core(ev_p,_decode_no_dup_keys)
 comp_mans,comp_errs = load_composition_manifests_core(ev_p,_decode_no_dup_keys)
 ev_errs.extend(ra_errs + comp_errs); sim_recs,_ = load_simulation_receipts_impl(ev_p,_decode_no_dup_keys); m_man,lat_m,m_errs = None,{},[]
 if a.mutants and a.mutation_events:
  try:m_man = validate_mutation_manifest(a.mutants.read_text("utf-8")); lat_m,m_errs = load_mutation_events(a.mutation_events,m_man)
  except Exception as exc:m_errs.append(str(exc))
 exp_sub,man_srcs = resolve_verifier_subject_cli(a,_decode_no_dup_keys,canonical_json,parse_subject_manifest_impl,parse_security_lock_impl)
 perf_b,by_c = load_measurement_bundle(a.measurements,_decode_no_dup_keys,digest_matches),{}
 for ev in evs:by_c.setdefault(ev["contract"],[]).append(ev)
 parsed = [{**verify_contract_toml(cf,p_dir),"file_stem":cf.stem} for cf in c_files]
 base_by_id = {bc["id"]:bc for bf in ((sorted(a.base.glob("*.toml")) if a.base.is_dir() else [a.base]) if a.base else ()) for bc in (verify_contract_toml(bf,p_dir),)}
 tot_open,reuse_ok = sum(c.get("open_cnt",0) for c in parsed),bool(a.base and a.changed_none and not a.allow_break_glass)
 raw_v = [evaluate_contract(c,cfg_st,by_c.get(c["id"],[]),gone.get(c["id"],0),inc,ev_errs,pol,a.min_proof,a.phase,tot_open,evaluate_contract_mutations(c,m_man,lat_m,m_errs),perf_b,exp_sub,sec_recs,exp_snap,form_recs,ssub,man_srcs,par_recs,mig_recs,reuse_ok,base_by_id.get(c["id"]),bool(a.attest),sim_recs,ra_recs,comp_mans) for c in parsed]
 single_f = len(tgts) == 1 and tgts[0].is_file()
 raw_v,has_gsig = evaluate_grant_verdicts_py(raw_v,parsed,a,cfg_p,pol,roots["source_root"],_decode_no_dup_keys,canonical_json,digest_matches,_proof_rank,single_f)
 raw_v,has_psig = evaluate_pact_verdicts_py(raw_v,parsed,c_files,p_dir,a,cfg_p,pol,roots["source_root"],_decode_no_dup_keys,canonical_json,jcs_string,jcs_number,digest_matches,_proof_rank,verify_contract_toml)
 raw_v,bundle_list = evaluate_shard_bundles_py(raw_v,ev_p,sn_l,_decode_no_dup_keys,canonical_json)
 raw_v = evaluate_containment_py(raw_v,parsed,by_c,digest_matches)
 has_ev_sig = any((ep.is_file() and ep.name.endswith(".sig.json")) or (ep.is_dir() and any(ch.name.endswith(".sig.json") for ch in ep.iterdir())) for ep in ev_p)
 verdicts = raw_v if ((a.signatures or a.signature_policy or has_gsig or has_psig or has_ev_sig or a.allow_break_glass or pol.get("require_signed_approval") is True) and not a.attest and not a.attest_sig) else apply_openssh_trust_verdicts(raw_v,a,cfg_st,cfg_dig,sh_h,sn_l,sn_ok,inc,m_man,perf_b,_decode_no_dup_keys,exp_sub)
 verdicts = evaluate_detached_signatures_core(verdicts,parsed,a,cfg_dig,_decode_no_dup_keys,canonical_json,digest_matches)
 verdicts = evaluate_role_signatures_py(verdicts,parsed,bundle_list,a,pol,cfg_dig,_decode_no_dup_keys,canonical_json,digest_matches)
 verdicts = evaluate_break_glass_py(verdicts,parsed,a,cfg_st,cfg_dig,_decode_no_dup_keys,canonical_json,digest_matches)
 ok = bool(verdicts) and all(v["ok"] for v in verdicts)
 sw_pol = pol.get("sweep") if pol.get("pack") == "core@1" else None
 if sw_pol == "soundness" or (isinstance(sw_pol, list) and "soundness" in sw_pol):
  print('drift_verify: warning: policy.sweep = "soundness" is not evaluated by the offline verifier; run DRIFT Pro for area soundness gating', file=sys.stderr)
 if a.json:print(json.dumps({"ok":ok,"contracts":verdicts},indent=2,sort_keys=True))
 else:
  for v in verdicts: print(f"{v['id']} {v['ref']}: {'green' if v['ok'] else 'not green (' + ', '.join(v['reasons']) + ')'}")
 return 0 if ok else 1
if __name__ == "__main__":sys.exit(main(sys.argv[1:]))
