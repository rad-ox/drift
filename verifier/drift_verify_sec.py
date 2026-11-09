#!/usr/bin/env python3
"""DRIFT Independent Reference Security Evidence Verifier (MIT License)."""

from __future__ import annotations
import hashlib,math,re
from pathlib import Path
from typing import Any,Callable
SNAPSHOT_RE=re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
ID_RE=re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEC_CATEGORIES=frozenset(("sast","fuzz","policy","deps"))
SEC_OUTCOMES=frozenset(("passed","violated","inconclusive"))
SEC_REQ_KEYS=frozenset(("kind","category","tool","tool_ref","ruleset_ref","contract","digest","code_snapshot","covered_scope","cases","outcome"))
SEC_KEYS=SEC_REQ_KEYS | frozenset(("subject_ref","artifact_ref","reproducer"))
SHA256_REF_RE=re.compile(r"^sha256:[0-9a-f]{64}$")
DIGEST_RE=re.compile(r"^dr1:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})$")
from drift_verify_mig import check_sec_stage1_core,classify_sec_reproducer_core,collect_receipt_files,parse_security_lock_core,run_sec_self_test_core,validate_mutation_manifest_core,verify_tool_pin_cli_core
def validate_mutation_manifest_impl(text: str, decode_fn: Callable[[str], Any]) -> dict[str, Any]:
 return validate_mutation_manifest_core(text,decode_fn)
def _sec_str(m: dict[str, Any], k: str) -> str:
 v=m.get(k)
 if not isinstance(v,str) or not v.strip() or v.strip()!=v:
  raise ValueError(k)
 return v
def _valid_rel_scope(raw: Any) -> bool:
 if not isinstance(raw,str) or not raw or raw.strip()!=raw or raw.startswith("/") or "\\" in raw or "://" in raw:
  return False
 base=raw.split("#",1)[0]
 return bool(base) and not any(s in ("",".","..") for s in base.split("/"))
def _split_scope_anchor(s: str) -> tuple[str, str]:
 norm=s.replace("\\","/")
 if "#" in norm:
  base,anchor = norm.split("#",1)
  return base.rstrip("/"),anchor.strip()
 return norm.rstrip("/"),""
def _wild_tok(pat: str, txt: str) -> bool:
 if pat in ("*",txt):return True
 if "*" not in pat:return False
 parts=pat.split("*")
 if not txt.startswith(parts[0]) or not txt.endswith(parts[-1]) or len(parts[0]) > len(txt) - len(parts[-1]):return False
 pos,end_lim=len(parts[0]),len(txt) - len(parts[-1])
 for piece in parts[1:-1]:
  if piece:
   idx=txt.find(piece,pos,end_lim)
   if idx < 0:return False
   pos=idx+len(piece)
 return True
def _match_segs(pat: list[str], path: list[str], pi: int = 0, si: int = 0) -> bool:
 if pi==len(pat):return si==len(path)
 if pat[pi]=="**":return _match_segs(pat,path,pi+1,si) or (si < len(path) and _match_segs(pat,path,pi,si+1))
 return si < len(path) and _wild_tok(pat[pi],path[si]) and _match_segs(pat,path,pi+1,si+1)
def _cov_matches(cov_raw: str, sc_raw: str) -> bool:
 cov,cov_anchor=_split_scope_anchor(cov_raw)
 sc,sc_anchor=_split_scope_anchor(sc_raw)
 if not cov or not sc:return False
 if cov_anchor:return bool(sc_anchor and _wild_tok(cov_anchor,sc_anchor) and (cov==sc or _match_segs(cov.split("/"),sc.split("/"))))
 return True if (cov in (sc,"**","*") or sc.startswith(cov+"/")) else _match_segs(cov.split("/"),sc.split("/"))
def _receipt_identity_key(r: dict[str, Any]) -> tuple[Any, ...]:
 return (r["category"],r["tool"],r["tool_ref"],r["ruleset_ref"],r["code_snapshot"],r.get("subject_ref",""),r.get("artifact_ref",""),tuple(r["covered_scope"]),tuple(r["cases"]),r["outcome"])
def parse_security_lock_impl(text: str, decode_fn: Callable[[str], Any], canon_fn: Callable[[Any], str]) -> dict[str, Any]:
 return parse_security_lock_core(text,decode_fn,canon_fn,_sec_str,SEC_CATEGORIES)
def load_security_receipts_impl(events_paths: list[Path], decode_fn: Callable[[str], Any]) -> tuple[list[dict[str, Any]], list[str]]:
 out,errs=[],[]
 for sf in collect_receipt_files(events_paths,".security.json"):
  try:
   doc=decode_fn(sf.read_text(encoding="utf-8"))
   if not isinstance(doc,dict) or not SEC_REQ_KEYS.issubset(doc) or any(k not in SEC_KEYS for k in doc) or doc.get("kind")!="security_check":
    raise ValueError("sec_keys")
   cat,tool=_sec_str(doc,"category"),_sec_str(doc,"tool")
   tref,rref=_sec_str(doc,"tool_ref"),_sec_str(doc,"ruleset_ref")
   cid,dig=_sec_str(doc,"contract"),_sec_str(doc,"digest")
   csnap,outc=_sec_str(doc,"code_snapshot"),_sec_str(doc,"outcome")
   sref=_sec_str(doc,"subject_ref") if "subject_ref" in doc else ""
   aref=_sec_str(doc,"artifact_ref") if "artifact_ref" in doc else ""
   if cat not in SEC_CATEGORIES or not SHA256_REF_RE.match(tref) or not SHA256_REF_RE.match(rref) or not ID_RE.match(cid) or not DIGEST_RE.match(dig) or not SNAPSHOT_RE.match(csnap) or outc not in SEC_OUTCOMES or (sref and not SHA256_REF_RE.match(sref)) or (aref and not SHA256_REF_RE.match(aref)):
    raise ValueError("sec_fields")
   cov,cs=doc.get("covered_scope"),doc.get("cases")
   if not isinstance(cov,list) or not cov or len(set(cov))!=len(cov) or not all(_valid_rel_scope(x) for x in cov):
    raise ValueError("covered_scope")
   if not isinstance(cs,list) or not cs or not all(isinstance(x,str) and ID_RE.match(x) for x in cs):
    raise ValueError("cases")
   rec={"category":cat,"tool":tool,"tool_ref":tref,"ruleset_ref":rref,"contract":cid,"digest":dig,"code_snapshot":csnap,"covered_scope":sorted(set(cov)),"cases":sorted(set(cs)),"outcome":outc}
   if sref:rec["subject_ref"]=sref
   if aref:rec["artifact_ref"]=aref
   if "reproducer" in doc:rec["reproducer"]=doc["reproducer"]
   out.append(rec)
  except Exception as exc:
   errs.append(f"{sf.name}: {exc}")
 return out,errs
def evaluate_contract_security_impl(contract: dict[str, Any], sec_receipts: list[dict[str, Any]], policy: dict[str, Any] | None, expected_snapshot: str, digest_matches_fn: Callable[[str, str], bool], expected_subject: dict[str, Any] | None = None, allow_exec_reuse: bool = False, base_contract: dict[str, Any] | None = None) -> tuple[list[str], list[dict[str, Any]]]:
 pol,exp_sub=policy or {},expected_subject or {}
 req_cats=set(contract.get("profile_security") or [])
 if pol.get("pack")=="core@1" and isinstance(pol.get("security"),list):req_cats.update(str(x) for x in pol["security"] if isinstance(x,str))
 scope_code,raw_cases=contract.get("scope_code") or [],contract.get("cases") or {}
 base_cases,base_dig=(base_contract or {}).get("cases") or {},(base_contract or {}).get("digest","")
 active_cases={cid for cid,cm in raw_cases.items() if isinstance(cm,dict) and "status" not in cm}
 current_by_key:dict[tuple[str,str],dict[tuple[Any,...],dict[str,Any]]]={}
 base_by_key:dict[tuple[str,str],dict[tuple[Any,...],dict[str,Any]]]={}
 for r in sec_receipts:
  if r["contract"]!=contract["id"]:continue
  tkey=(r["category"],r["tool"])
  if digest_matches_fn(r["digest"],contract["digest"]):current_by_key.setdefault(tkey,{})[_receipt_identity_key(r)]=r
  elif allow_exec_reuse and base_dig and digest_matches_fn(r["digest"],base_dig) and all(cid in base_cases and {k:v for k,v in (raw_cases.get(cid) or {}).items() if k!="note"}=={k:v for k,v in (base_cases.get(cid) or {}).items() if k!="note"} for cid in r["cases"] if cid in active_cases):base_by_key.setdefault(tkey,{})[_receipt_identity_key(r)]=r
 all_keys=sorted(set(current_by_key) | set(base_by_key))
 if not all_keys and not req_cats:return [],[]
 eval_list,cat_states,has_viol,spec_rsns=[],{},False,[]
 for key in all_keys:
  is_cur = key in current_by_key
  src_map = current_by_key[key] if is_cur else base_by_key[key]
  prov = "measured" if is_cur else "reused"
  group = [src_map[rk] for rk in sorted(src_map)]
  s1_ok,s1_bad,bad_viol = [],[],False
  for rec in group:
   rdisp=classify_sec_reproducer_core(rec.get("reproducer"),raw_cases,active_cases)
   ok1,rsn1=check_sec_stage1_core(rec,expected_snapshot,exp_sub)
   if ok1:s1_ok.append((rec,rdisp))
   else:
    keep_v = rec["outcome"]=="violated" and rsn1 not in ("security.subject_mismatch","security.artifact_mismatch")
    if keep_v:bad_viol = True
    it = {**rec,"kind":"security_check","effective_outcome":"violated" if keep_v else "inconclusive","provenance":prov,"reason":rsn1}
    if rdisp:it["reproducer_disposition"] = rdisp
    s1_bad.append(it)
  if not s1_ok:
   if len(s1_bad) > 1:
    for it in s1_bad:
     it["effective_outcome"]="violated" if (bad_viol and it["effective_outcome"]=="violated") else "inconclusive"
     it["reason"]="security.conflicting_receipts"
   grp_evals=s1_bad
  else:
   grp_evals,grp_viol=[],False
   for rec,rdisp in s1_ok:
    eff_out,rsn = rec["outcome"],""
    valid_cs = bool(active_cases) and all(c in active_cases for c in rec["cases"])
    full_sc = bool(scope_code) and all(any(_cov_matches(c,sc) for c in rec["covered_scope"]) for sc in scope_code)
    if not valid_cs:
     if eff_out!="violated":
      eff_out,rsn = "inconclusive","security.incomplete_scope"
    elif not full_sc:
     if eff_out=="violated" and (not scope_code or any(_cov_matches(c,sc) for sc in scope_code for c in rec["covered_scope"])):
      eff_out = "violated"
     elif eff_out!="violated":
      eff_out,rsn = "inconclusive","security.incomplete_scope"
    if eff_out=="violated":grp_viol = True
    it = {**rec,"kind":"security_check","effective_outcome":eff_out,"provenance":prov}
    if rdisp:it["reproducer_disposition"] = rdisp
    if rsn:it["reason"] = rsn
    grp_evals.append(it)
   if len(grp_evals) > 1:
    for it in grp_evals:
     it["effective_outcome"]="violated" if (grp_viol and it["effective_outcome"]=="violated") else "inconclusive"
     it["reason"]="security.conflicting_receipts"
  for item in grp_evals:
   eval_list.append(item); eff_out,rsn=item["effective_outcome"],item.get("reason","")
   if rsn in ("security.subject_mismatch","security.artifact_mismatch","security.tool_unpinned","security.ruleset_stale") and rsn not in spec_rsns:spec_rsns.append(rsn)
   if eff_out=="violated":has_viol=True; cat_states[item["category"]]="violated"
   elif eff_out=="inconclusive" and cat_states.get(item["category"])!="violated":cat_states[item["category"]]="inconclusive"
   elif eff_out=="passed" and cat_states.get(item["category"]) not in ("violated","inconclusive"):cat_states[item["category"]]="reused" if (prov=="reused" or cat_states.get(item["category"])=="reused") else "passed"
 reasons=["security.violated"] if has_viol else []
 if exp_sub.get("artifact_mismatch") and "security.artifact_mismatch" not in spec_rsns:spec_rsns.append("security.artifact_mismatch")
 for sr in spec_rsns:
  if sr not in reasons:reasons.append(sr)
 has_inc,has_miss=False,False
 for rc in sorted(req_cats):
  st = cat_states.get(rc,"missing")
  if st=="violated" and "security.violated" not in reasons:reasons.append("security.violated")
  elif st=="inconclusive":has_inc = True
  elif st=="missing":has_miss = True
 if has_inc:reasons.append("security.inconclusive")
 if has_miss:reasons.append("security.missing")
 return reasons,eval_list
def run_sec_self_test(ck: dict[str, Any], digest_matches_fn: Callable[[str, str], bool]) -> None:
 run_sec_self_test_core(ck,digest_matches_fn,evaluate_contract_security_impl)
FORMAL_VERIFIERS=frozenset(("kani","loom","tlc","cbmc","alloy","spin","shuttle","stateright","dafny","qcec","gappa"))
FORMAL_EVIDENCES={"sampled_exploration":1,"bounded_exhaustive":2,"deductive":3}
FORMAL_COMPLETIONS=frozenset(("proven","exhausted_within_bounds","sampled_budget_met","truncated_unwind","truncated_oom","truncated_timeout"))
FORMAL_LINKAGES=frozenset(("in_code_harness","conformance_traced","declared_model"))
FORMAL_BOUND_KEYS=frozenset(("loop_unwind","max_preemptions","max_steps","max_threads","input_bytes","qubits","ansatz_layers","circuit_depth"))
FORMAL_KEYS=frozenset(("schema","contract","digest","formal_id","requirement_ref","verifier","verifier_ref","subject_ref","subject_identity","execution_determinism","code_snapshot","covered_scope","cases","verified_properties","evidence_kind","completion","linkage","harness","domain_bounds","cover_checks","fairness","assumptions","source_digests","arithmetic_model","equivalence","reproducer","outcome"))
def extract_contract_formal(raw: dict[str, Any], use_tbl: Any, dr1_digest_fn: Callable[[Any], str]) -> tuple[dict[str, Any], bool]:
 f_raw=raw.get("formal")
 if not isinstance(f_raw,dict) or not f_raw:return {},False
 params={k:str(v) for k,v in use_tbl.items() if k not in ("profile","waive","vocabulary","concepts") and isinstance(v,(str,int,bool))} if isinstance(use_tbl,dict) else {}
 def _sub(val:Any) -> Any:
  if isinstance(val,str):
   for pk,pv in params.items():
    if val==f"${{{pk}}}":return pv
    val = val.replace(f"${{{pk}}}",pv)
   return val
  return [_sub(x) for x in val] if isinstance(val,list) else ({k:_sub(v) for k,v in val.items()} if isinstance(val,dict) else val)
 trimmed,resolved={},{}
 for fid,fm in f_raw.items():
  if isinstance(fm,dict):
   trimmed[fid]={k:v for k,v in fm.items() if k not in ("note","requirement_ref")}
   sub_m=_sub(dict(fm))
   sub_m["requirement_ref"]=dr1_digest_fn({k:v for k,v in sub_m.items() if k not in ("note","requirement_ref")})
   resolved[fid]=sub_m
 raw["formal"]=trimmed
 return resolved,True
def parse_subject_manifest_impl(text: str, decode_fn: Callable[[str], Any], canon_fn: Callable[[Any], str]) -> dict[str, Any]:
 from drift_verify_ssh import parse_subject_manifest_core
 return parse_subject_manifest_core(text,decode_fn,canon_fn,_sec_str,_valid_rel_scope,SHA256_REF_RE)
def _formal_identity_key(r: dict[str, Any]) -> tuple[Any, ...]:
 db=tuple(sorted((r.get("domain_bounds") or {}).items()))
 cc=tuple(sorted((r.get("cover_checks") or {}).items()))
 return (r["formal_id"],r["requirement_ref"],r["verifier"],r["verifier_ref"],r["subject_ref"],r["code_snapshot"],tuple(r["covered_scope"]),tuple(r["cases"]),tuple(r["verified_properties"]),r["evidence_kind"],r["completion"],r["linkage"],r.get("harness",""),db,cc,r.get("fairness",""),r["outcome"])
def load_formal_receipts_impl(events_paths: list[Path], decode_fn: Callable[[str], Any]) -> tuple[list[dict[str, Any]], list[str]]:
 out,errs=[],[]
 for ff in collect_receipt_files(events_paths,".formal.json"):
  try:
   doc=decode_fn(ff.read_text(encoding="utf-8"))
   if not isinstance(doc,dict) or any(k not in FORMAL_KEYS for k in doc) or doc.get("schema")!="drift.formal-receipt/1":
    raise ValueError("formal_keys")
   cid,dig,fid,rref=_sec_str(doc,"contract"),_sec_str(doc,"digest"),_sec_str(doc,"formal_id"),_sec_str(doc,"requirement_ref")
   ver,vref,sref=_sec_str(doc,"verifier"),_sec_str(doc,"verifier_ref"),_sec_str(doc,"subject_ref")
   sid,edet,csnap=_sec_str(doc,"subject_identity"),_sec_str(doc,"execution_determinism"),_sec_str(doc,"code_snapshot")
   evk,comp,lnk,outc=_sec_str(doc,"evidence_kind"),_sec_str(doc,"completion"),_sec_str(doc,"linkage"),_sec_str(doc,"outcome")
   if not ID_RE.match(cid) or not DIGEST_RE.match(dig) or not ID_RE.match(fid) or not re.fullmatch(r"dr1:sha256:[0-9a-f]{64}",rref) or ver not in FORMAL_VERIFIERS or not SHA256_REF_RE.match(vref) or not SHA256_REF_RE.match(sref) or sid not in ("pinned","opaque_external") or edet not in ("bitwise","statistical") or not SNAPSHOT_RE.match(csnap) or evk not in FORMAL_EVIDENCES or comp not in FORMAL_COMPLETIONS or lnk not in FORMAL_LINKAGES or outc not in SEC_OUTCOMES:
    raise ValueError("formal_fields")
   cov,cs,vps=doc.get("covered_scope"),doc.get("cases"),doc.get("verified_properties")
   if not isinstance(cov,list) or not cov or len(set(cov))!=len(cov) or not all(_valid_rel_scope(x) for x in cov):raise ValueError("covered_scope")
   if not isinstance(cs,list) or not cs or not all(isinstance(x,str) and ID_RE.match(x) for x in cs):raise ValueError("cases")
   if not isinstance(vps,list) or not vps or not all(isinstance(x,str) and bool(re.fullmatch(r"[a-z][a-z0-9_-]*",x)) for x in vps):raise ValueError("verified_properties")
   harn=_sec_str(doc,"harness") if "harness" in doc else ""
   if harn and (not _valid_rel_scope(harn) or "#" not in harn):raise ValueError("harness")
   db,cc=doc.get("domain_bounds") or {},doc.get("cover_checks") or {}
   if "domain_bounds" in doc and (not isinstance(db,dict) or not db or any(k not in FORMAL_BOUND_KEYS or not isinstance(v,int) or isinstance(v,bool) or v < 1 for k,v in db.items())):raise ValueError("domain_bounds")
   if "cover_checks" in doc and (not isinstance(cc,dict) or not cc or any(not isinstance(k,str) or not k.strip() or v not in ("satisfied","unsatisfied","unreachable") for k,v in cc.items())):raise ValueError("cover_checks")
   fair=_sec_str(doc,"fairness") if "fairness" in doc else ""
   if fair and fair not in ("none","weak","strong"):raise ValueError("fairness")
   amod=_sec_str(doc,"arithmetic_model") if "arithmetic_model" in doc else ""
   if amod and amod not in ("ieee754_binary64","ieee754_binary32","int_bounded","real_exact"):raise ValueError("arithmetic_model")
   assump,sdigs=doc.get("assumptions") or [],doc.get("source_digests") or {}
   if "assumptions" in doc and (not isinstance(assump,list) or not all(isinstance(x,str) and x.strip() for x in assump)):raise ValueError("assumptions")
   if "source_digests" in doc and (not isinstance(sdigs,dict) or not sdigs or any(not _valid_rel_scope(sp) or "#" in sp or not isinstance(sh,str) or not SHA256_REF_RE.match(sh) for sp,sh in sdigs.items())):raise ValueError("source_digests")
   eq_m=doc.get("equivalence")
   if "equivalence" in doc:
    if not isinstance(eq_m,dict) or any(k not in ("reference_artifact_ref","compiled_artifact_ref","relation","method","numerical_tolerance","max_allowed_tolerance") for k in eq_m) or not SHA256_REF_RE.match(str(eq_m.get("reference_artifact_ref",""))) or not SHA256_REF_RE.match(str(eq_m.get("compiled_artifact_ref",""))) or eq_m.get("relation") not in ("unitary_exact","unitary_up_to_global_phase","unitary_within_tolerance") or eq_m.get("method") not in ("decision_diagram","zx_calculus","stabilizer","random_simulation") or isinstance(eq_m.get("numerical_tolerance"),bool) or not isinstance(eq_m.get("numerical_tolerance"),(int,float)) or not math.isfinite(float(eq_m["numerical_tolerance"])) or float(eq_m["numerical_tolerance"]) < 0.0 or ("max_allowed_tolerance" in eq_m and (isinstance(eq_m.get("max_allowed_tolerance"),bool) or not isinstance(eq_m.get("max_allowed_tolerance"),(int,float)) or not math.isfinite(float(eq_m["max_allowed_tolerance"])) or float(eq_m["max_allowed_tolerance"]) < 0.0)):
     raise ValueError("equivalence")
   repro=doc.get("reproducer")
   if repro is not None:
    if not isinstance(repro,dict) or any(k not in ("kind","command","witness","artifact_path") for k in repro) or repro.get("kind")!="counterexample_witness" or not isinstance(repro.get("command"),str) or not repro["command"].strip() or not isinstance(w := repro.get("witness"),dict) or set(w)!={"when","then"} or not isinstance(w.get("when"),dict) or not isinstance(w.get("then"),dict):
     raise ValueError("reproducer")
   out.append({"schema":"drift.formal-receipt/1","contract":cid,"digest":dig,"formal_id":fid,"requirement_ref":rref,"verifier":ver,"verifier_ref":vref,"subject_ref":sref,"subject_identity":sid,"execution_determinism":edet,"code_snapshot":csnap,"covered_scope":sorted(set(cov)),"cases":sorted(set(cs)),"verified_properties":sorted(set(vps)),"evidence_kind":evk,"completion":comp,"linkage":lnk,"harness":harn,"domain_bounds":dict(db),"cover_checks":dict(cc),"fairness":fair,"assumptions":sorted(set(assump)),"source_digests":dict(sdigs),**({"arithmetic_model":amod} if amod else {}),**({"equivalence":dict(eq_m)} if eq_m else {}),"reproducer":repro,"outcome":outc})
  except Exception as exc:
   errs.append(f"{ff.name}: {exc}")
 return out,errs
def validate_formal_equivalence(rec: dict[str, Any], ob_ver: str, ob_pkind: str, ob_minev: str, raw_cases: dict[str, Any]) -> str:
 db=rec.get("domain_bounds") or {}
 for cid in rec.get("cases",()):
  wm = (raw_cases.get(cid) or {}).get("when") if isinstance(raw_cases.get(cid),dict) else None
  if isinstance(wm,dict):
   for bk in FORMAL_BOUND_KEYS:
    wv = wm.get(bk)
    if isinstance(wv,int) and not isinstance(wv,bool) and wv >= 1 and int(db.get(bk,0)) < wv:return "formal.bound_insufficient"
 if ob_ver=="gappa" and rec.get("arithmetic_model") not in ("ieee754_binary64","ieee754_binary32"):return "formal.arithmetic_model_mismatch"
 eq=rec.get("equivalence")
 if not (ob_ver=="qcec" or ob_pkind=="unitary_equivalence" or eq):return ""
 if not isinstance(eq,dict):return "formal.property_mismatch"
 if eq.get("method")=="random_simulation" and (rec["evidence_kind"] in ("deductive","bounded_exhaustive") or ob_minev in ("deductive","bounded_exhaustive")):return "formal.exploration_incomplete"
 tol,max_t=float(eq.get("numerical_tolerance",0.0)),float(eq.get("max_allowed_tolerance",0.0))
 if eq.get("relation") in ("unitary_exact","unitary_up_to_global_phase") and tol > 0.0:return "formal.tolerance_incompatible"
 if eq.get("relation")=="unitary_within_tolerance" and (max_t <= 0.0 or tol > max_t):return "formal.tolerance_incompatible"
 return ""
def evaluate_contract_formal_impl(
 contract:dict[str,Any],
 formal_receipts:list[dict[str,Any]],
 phase:str,
 expected_subject_ref:str,
 expected_snapshot:str,
 shard_subject_refs:set[str],
 area_root:Path | None,
 manifest_sources:dict[str,str] | None,
 digest_matches_fn:Callable[[str,str],bool],
) -> tuple[list[str],list[str],list[dict[str,Any]]]:
 formal_tbl=contract.get("formal") or {}
 scope_code=contract.get("scope_code") or []
 raw_cases=contract.get("cases") or {}
 active_cases={cid for cid,cm in raw_cases.items() if isinstance(cm,dict) and "status" not in cm}
 by_fid:dict[str,dict[tuple[Any,...],dict[str,Any]]]={}
 for r in formal_receipts:
  if r["contract"]==contract["id"] and digest_matches_fn(r["digest"],contract["digest"]):
   by_fid.setdefault(r["formal_id"],{})[_formal_identity_key(r)]=r
 if not formal_tbl and not by_fid:
  return [],[],[]
 man_dirty=False
 if area_root and manifest_sources:
  for rp,eh in manifest_sources.items():
   cp=area_root / rp
   if cp.is_file() and ("sha256:"+hashlib.sha256(cp.read_bytes()).hexdigest())!=eh:
    man_dirty = True
    break
 eval_list,pending=[],[]
 has_cand_mismatch=has_violated=has_inconclusive=has_missing=False
 for fid in sorted(formal_tbl):
  fm = formal_tbl[fid]
  ob_cases = [str(x) for x in (fm.get("cases") or [])]
  ob_ver,ob_prop = str(fm.get("verifier","")),str(fm.get("property",""))
  ob_pkind,ob_minev = str(fm.get("property_kind","safety")),str(fm.get("min_evidence",""))
  ob_lnk,ob_harn = str(fm.get("linkage","")),str(fm.get("harness",""))
  ob_fair,ob_enf = str(fm.get("fairness","")),str(fm.get("enforce","release"))
  ob_rref,ob_bnds = str(fm.get("requirement_ref","")),(fm.get("domain_bounds") or {})
  enforced_now = ob_enf=="execution" or phase=="release"
  bucket = by_fid.get(fid,{})
  group = [bucket[k] for k in sorted(bucket)]
  if not group:
   if enforced_now:
    has_missing = True
   else:
    pending.append(fid)
   continue
  rec_eff,rec_rsn,rec_prov = [],[],[]
  any_viol = False
  for rec in group:
   eff,rsn,prov=rec["outcome"],"","measured"
   c_dirty=man_dirty or bool(area_root and any((area_root / sp).is_file() and ("sha256:"+hashlib.sha256((area_root / sp).read_bytes()).hexdigest())!=sh for sp,sh in (rec.get("source_digests") or {}).items()))
   sh_agrees=rec["subject_ref"] in shard_subject_refs
   if c_dirty or (expected_subject_ref and rec["subject_ref"]!=expected_subject_ref and sh_agrees):
    eff,rsn,has_cand_mismatch = "inconclusive","subject.candidate_mismatch",True
   elif expected_subject_ref and rec["subject_ref"]!=expected_subject_ref:
    eff,rsn = "inconclusive","subject.mismatch"
   elif not expected_subject_ref and expected_snapshot and rec["code_snapshot"]!=expected_snapshot:
    eff,rsn = "inconclusive","subject.mismatch"
   elif rec["requirement_ref"]!=ob_rref or rec["verifier"]!=ob_ver or ob_prop not in rec["verified_properties"] or rec["linkage"]!=ob_lnk or (ob_harn and rec["harness"]!=ob_harn):
    eff,rsn = "inconclusive","formal.property_mismatch"
   elif not scope_code or not all(any(_cov_matches(c,sc) for c in rec["covered_scope"]) for sc in scope_code) or not rec["cases"] or not all(c in active_cases for c in rec["cases"]) or not all(c not in active_cases or c in rec["cases"] for c in ob_cases):
    eff,rsn = "inconclusive","formal.incomplete_scope"
   else:
    if expected_snapshot and rec["code_snapshot"]!=expected_snapshot and rec["subject_identity"]=="pinned" and expected_subject_ref and rec["subject_ref"]==expected_subject_ref:
     prov="reused_subject"
    if rec["outcome"]=="violated":
     eff,rsn,any_viol="violated","formal.violated",True
    elif rec["outcome"]=="inconclusive":
     eff,rsn="inconclusive",("formal.exploration_incomplete" if rec["completion"].startswith("truncated_") else "formal.inconclusive")
    else:
     cc=rec.get("cover_checks") or {}
     bad_cov=(ob_lnk=="in_code_harness" and not cc) or any(v!="satisfied" for v in cc.values())
     comp_ok=(rec["evidence_kind"]=="deductive" and rec["completion"]=="proven") or (rec["evidence_kind"]=="bounded_exhaustive" and rec["completion"] in ("proven","exhausted_within_bounds")) or (rec["evidence_kind"]=="sampled_exploration" and rec["completion"] in ("proven","exhausted_within_bounds","sampled_budget_met"))
     if rec["completion"].startswith("truncated_") or FORMAL_EVIDENCES.get(rec["evidence_kind"],0) < FORMAL_EVIDENCES.get(ob_minev,0) or not comp_ok:
      eff,rsn = "inconclusive","formal.exploration_incomplete"
     elif any(rec.get("domain_bounds",{}).get(bk,0) < int(bv) for bk,bv in ob_bnds.items()):
      eff,rsn = "inconclusive","formal.bound_insufficient"
     elif bad_cov:
      eff,rsn = "inconclusive","formal.vacuous_cover"
     elif ob_pkind=="liveness" and (not rec.get("fairness") or rec.get("fairness")!=ob_fair):
      eff,rsn = "inconclusive","formal.missing_fairness_assumption"
     elif eq_r := validate_formal_equivalence(rec,ob_ver,ob_pkind,ob_minev,raw_cases):
      eff,rsn = "inconclusive",eq_r
   rec_eff.append(eff); rec_rsn.append(rsn); rec_prov.append(prov)
  has_conf = len(group) > 1
  for idx,rec in enumerate(group):
   eff,rsn,prov=rec_eff[idx],rec_rsn[idx],rec_prov[idx]
   if has_conf:
    if any_viol and eff=="violated":
     rsn="formal.conflicting_receipts"
    else:
     eff,rsn="inconclusive","formal.conflicting_receipts"
   item={k:v for k,v in rec.items() if k not in ("harness","domain_bounds","cover_checks","fairness","assumptions","source_digests","reproducer") or (k in ("harness","fairness") and v) or (k in ("domain_bounds","cover_checks","assumptions") and v) or (k=="reproducer" and v is not None)}
   item.update({"effective_outcome":eff,"provenance":prov})
   if rsn:
    item["reason"] = rsn
   eval_list.append(item)
  if any_viol and enforced_now:has_violated = True
  elif (has_conf or rec_eff[0]!="passed") and enforced_now:has_inconclusive = True
 reasons = [*(['subject.candidate_mismatch'] if has_cand_mismatch else []),*(['formal.violated'] if has_violated else []),*(['formal.inconclusive'] if has_inconclusive else []),*(['formal.missing'] if has_missing else [])]
 return reasons,pending,eval_list
def load_migration_receipts_impl(events_paths: list[Path], decode_fn: Callable[[str], Any]) -> tuple[list[dict[str, Any]], list[str]]:
 from drift_verify_mig import load_migration_receipts_core
 return load_migration_receipts_core(events_paths,decode_fn,_valid_rel_scope)
def evaluate_contract_migration_impl(contract: dict[str, Any], mig_receipts: list[dict[str, Any]], policy: dict[str, Any] | None, expected_snapshot: str, expected_subject_ref: str, digest_matches_fn: Callable[[str, str], bool]) -> tuple[list[str], list[dict[str, Any]]]:
 from drift_verify_mig import evaluate_contract_migration_core
 return evaluate_contract_migration_core(contract,mig_receipts,policy,expected_snapshot,expected_subject_ref,digest_matches_fn,_cov_matches)
def verify_tool_pin_cli(argv: list[str]) -> int:
 return verify_tool_pin_cli_core(argv,parse_security_lock_impl)
if __name__=="__main__":
 import sys
 sys.exit(verify_tool_pin_cli(sys.argv[1:]))
