#!/usr/bin/env python3
import argparse,hashlib,json,math,os,re,sys,tomllib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from drift_verify_perf import evaluate_contract_budgets,evaluate_contract_mutations_impl,extract_contract_budgets,load_measurement_bundle,load_mutation_events_impl
from drift_verify_sec import evaluate_contract_formal_impl,evaluate_contract_migration_impl,evaluate_contract_security_impl,extract_contract_formal,load_formal_receipts_impl,load_migration_receipts_impl,load_security_receipts_impl,parse_security_lock_impl,parse_subject_manifest_impl,run_sec_self_test,validate_mutation_manifest_impl
from drift_verify_sim import evaluate_contract_simulation_impl,load_simulation_receipts_impl
from drift_verify_ssh import _has_approval_blocker,_is_unanchored_prose_source,apply_openssh_trust_verdicts,evaluate_contract_parity_impl,extract_contract_cutover,load_merged_profile_impl,load_parity_receipts_impl,verify_contract_03_toml
from drift_verify_ra import evaluate_contract_ra_bundle,evaluate_detached_signatures_core,extract_contract_risks_and_controls,load_ra_receipts_core,run_ra_self_test
SAFE_INT = (1 << 53) - 1
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORD_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DIGEST_RE = re.compile(r"^(?:dr1:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})|dr2b:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12}))$")
PACK_REF_RE = re.compile(r"^dr1:[0-9a-f]{12}$")
SNAPSHOT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
CLASS_TOKEN_RE = re.compile(r"^[^# \t\r\n/\\\[\]]+$")
METHOD_TOKEN_RE = re.compile(r"^[^# \t\r\n\[\]]+$")
OUTCOMES = frozenset(("passed","failed","skipped","disabled","interrupted","timeout"))
EVENT_KEYS = frozenset(("test","contract","cases","level","outcome","read","digest","schema","capabilities"))
META_KEYS = frozenset(("version","classes","tests","snapshot","pack_ref","touched","self_stubbed","inputs","env","execution_ref","subject_ref","shadow_run"))
ENV_KEYS = frozenset(("toolchain","deps","config","runner","drift","adapter","policy"))
_ESC_MAP = {0x22:'\\"',0x5C:"\\\\",0x08:"\\b",0x0C:"\\f",0x0A:"\\n",0x0D:"\\r",0x09:"\\t"}
def jcs_string(s):
 return '"' + "".join(_ESC_MAP.get(cp := ord(c),f"\\u{cp:04x}" if cp < 0x20 else c) for c in s) + '"'
def jcs_number(val):
 if isinstance(val,int) and not isinstance(val,bool):
  if not (-SAFE_INT <= val <= SAFE_INT):raise ValueError("int")
  return str(val)
 f = float(val)
 if not math.isfinite(f):raise ValueError("nan")
 if f == 0.0:return "0"
 neg,f,s = f < 0.0,abs(f),repr(abs(float(val)))
 if "e" in s or "E" in s:m,e = s.lower().split("e",1); d,n = m.replace(".","").rstrip("0") or "0",int(e) + 1
 elif "." in s:ip,fp = s.split(".",1); d,n = (ip + fp).lstrip("0").rstrip("0") or "0",(len(ip) if ip != "0" else -(len(fp) - len(fp.lstrip("0"))))
 else:d,n = s.rstrip("0") or "0",len(s)
 k = len(d)
 b = d + ("0" * (n - k)) if k <= n <= 21 else (f"{d[:n]}.{d[n:]}" if 0 < n <= 21 else (f"0.{'0' * (-n)}{d}" if -6 < n <= 0 else f"{d if k == 1 else f'{d[0]}.{d[1:]}'}e{'+' if n >= 1 else '-'}{abs(n - 1)}"))
 return f"-{b}" if neg else b
def canonical_json(obj):
 if obj is None or isinstance(obj,bool):return "null" if obj is None else ("true" if obj else "false")
 if isinstance(obj,(int,float)):return jcs_number(obj)
 if isinstance(obj,str):return jcs_string(obj)
 if isinstance(obj,(list,tuple)):return "[" + ",".join(canonical_json(x) for x in obj) + "]"
 if isinstance(obj,dict):return "{" + ",".join(f"{jcs_string(str(k))}:{canonical_json(v)}" for k,v in sorted(obj.items(),key=lambda kv:str(kv[0]).encode("utf-16-be"))) + "}"
 raise TypeError(type(obj).__name__)
def dr1_digest(obj): return "dr1:sha256:" + hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
def dr1_ref(d):
 if d.startswith("dr1:sha256:"): return "dr1:" + d[11:23]
 for p in ("dr2b:sha256:","dr2a:sha256:","dr2r:sha256:","dr2x:sha256:"):
  if d.startswith(p): return p[:5] + d[len(p):len(p)+12]
 return ""
def digest_matches(ed, fd): return bool(fd) and (ed == fd or ed == dr1_ref(fd))
def _decode_no_dup_keys(text):
 d,ins,esc = 0,False,False
 for ch in text:
  if ins:
   esc = (not esc) if ch == "\\" else False
   if ch == '"' and not esc:ins = False
  elif ch == '"':ins = True
  elif ch in "{[":
   d += 1
   if d > 64:raise ValueError("depth")
  elif ch in "}]":d = max(0,d - 1)
 def hook(pairs):
  out = {}
  for k,v in pairs:
   if k in out:raise ValueError(k)
   out[k] = v
  return out
 return json.loads(text,object_pairs_hook=hook)
def validate_event_line(line):
 doc = _decode_no_dup_keys(line)
 if not isinstance(doc,dict) or any(k not in EVENT_KEYS for k in doc) or any(r not in doc for r in ("test","contract","cases","level","outcome")):raise ValueError("event")
 cs,rd,dig,sch,caps = doc["cases"],doc.get("read",[]),doc.get("digest",""),doc.get("schema",""),doc.get("capabilities",[])
 if not isinstance(doc["test"],str) or not doc["test"].strip() or not isinstance(doc["contract"],str) or not ID_RE.match(doc["contract"]) or not isinstance(cs,list) or not cs or len(set(cs)) != len(cs) or not all(isinstance(c,str) and ID_RE.match(c) for c in cs) or not isinstance(doc["level"],str) or not WORD_RE.match(doc["level"]) or doc["outcome"] not in OUTCOMES or not isinstance(rd,list) or len(set(rd)) != len(rd) or not all(isinstance(r,str) and r in cs for r in rd) or (dig != "" and (not isinstance(dig,str) or not DIGEST_RE.match(dig))) or (sch != "" and sch not in ("0.2","0.3")) or not isinstance(caps,list) or not all(isinstance(cp,str) and cp.strip() for cp in caps):raise ValueError("event")
 return {"test":doc["test"],"contract":doc["contract"],"cases":cs,"level":doc["level"],"outcome":doc["outcome"],"read":rd,"digest":dig,"schema":sch,"capabilities":caps}
def validate_inventory_text(text):
 doc = _decode_no_dup_keys(text)
 if not isinstance(doc,dict) or any(k not in META_KEYS for k in doc) or doc.get("version") not in (1,2) or isinstance(doc.get("version"),bool):raise ValueError("inv")
 ex_ref,s_ref = doc.get("execution_ref",""),doc.get("subject_ref","")
 if (doc["version"] == 2 and not re.fullmatch(r"sha256:[0-9a-f]{64}",str(ex_ref))) or (doc["version"] == 1 and "execution_ref" in doc) or ("subject_ref" in doc and not re.fullmatch(r"sha256:[0-9a-f]{64}",str(s_ref))):raise ValueError("ref")
 cls,tsts = doc.get("classes"),doc.get("tests")
 if not isinstance(cls,list) or not all(isinstance(x,str) and CLASS_TOKEN_RE.match(x) for x in cls) or cls != sorted(set(cls)):raise ValueError("cls")
 c_set = set(cls)
 if not isinstance(tsts,list) or not all(isinstance(x,str) and "#" in x for x in tsts) or tsts != sorted(set(tsts)) or any((p := t.split("#",1))[0] not in c_set or not METHOD_TOKEN_RE.match(p[1]) for t in tsts):raise ValueError("tst")
 t_set,snap,pref = set(tsts),doc.get("snapshot",""),doc.get("pack_ref","")
 if ("snapshot" in doc and (not isinstance(snap,str) or not SNAPSHOT_RE.match(snap))) or ("pack_ref" in doc and (not isinstance(pref,str) or not PACK_REF_RE.match(pref))) or ("touched" in doc and (not isinstance(tc := doc["touched"],list) or not all(isinstance(x,str) and x.strip() for x in tc) or tc != sorted(set(tc)) or any(tp.startswith("/") or "\\" in tp or any(s in ("",".","..") for s in tp.split("/")) for tp in tc))) or ("self_stubbed" in doc and (not isinstance(doc["self_stubbed"],list) or any(not isinstance(x,str) or x not in t_set for x in doc["self_stubbed"]))) or ("inputs" in doc and (not isinstance(ri := doc["inputs"],dict) or any(tid not in t_set or not isinstance(fm,dict) or any(not isinstance(fp,str) or not fp.strip() or not isinstance(ov,str) or not ov.strip() for fp,ov in fm.items()) for tid,fm in ri.items()))) or ("env" in doc and (not isinstance(re_e := doc["env"],dict) or set(re_e) != ENV_KEYS or any(not isinstance(ev,str) or not ev.strip() for ev in re_e.values()))):raise ValueError("inv")
 if "shadow_run" in doc:
  from drift_shadow_junit import validate_shadow_run_dict; validate_shadow_run_dict(doc["shadow_run"])
 return {"classes":c_set,"tests":t_set,"snapshot":snap,"pack_ref":pref,"version":doc["version"],"execution_ref":ex_ref,"subject_ref":s_ref,"touched":set(doc.get("touched",[])),"shadow_run":doc.get("shadow_run")}
def validate_inventory_sidecar(path): return validate_inventory_text(path.read_text("utf-8"))
def resolve_shadow_roots(path, state_dir=""):
 from drift_shadow_junit import resolve_shadow_roots_impl; return resolve_shadow_roots_impl(path,state_dir)
def verify_config_toml(path):
 if not path.is_file():return "missing","",{}
 raw = tomllib.loads(path.read_text("utf-8"))
 appr,dig,pol = raw.pop("approval",None),dr1_digest(raw),(raw.get("policy") if isinstance(raw.get("policy"),dict) else {})
 if not isinstance(appr,dict) or not appr.get("ref"):return "absent",dig,pol
 st = "current" if appr["ref"] == dr1_ref(dig) else "stale"
 return st,dig,(pol if st == "current" else {})
def _load_merged_profile(prof_ref, profiles_dir): return load_merged_profile_impl(prof_ref, profiles_dir, _proof_rank)
def _strip_outside_digest(cases, decs):
 for cm in (cases or {}).values():
  if isinstance(cm,dict):cm.pop("note",None)
 for dm in (decs or {}).values() if isinstance(decs,dict) else ():
  if isinstance(dm,dict):
   dm.pop("owner",None); dm.pop("note",None)
   if dm.get("evidence") == "observed" and _is_unanchored_prose_source(str(dm.get("source",""))):dm.pop("source",None)
def verify_contract_toml(path, profiles_dir):
 raw = tomllib.loads(path.read_text("utf-8"))
 if raw.get("drift") == "0.3":return verify_contract_03_toml(raw,path,profiles_dir,canonical_json,dr1_ref,_proof_rank,resolve_shadow_roots)
 cid,appr,_ = raw.get("id",path.stem),raw.pop("approval",None),raw.pop("note",None)
 raw_sc = raw.get("scope") if isinstance(raw.get("scope"),dict) else {}
 sc_code,sc_reads,sc_writes = ([str(x) for x in raw_sc.get(k,[]) if isinstance(x,str)] if isinstance(raw_sc.get(k),list) else [] for k in ("code","reads","writes"))
 if isinstance(raw.get("scope"),dict):raw["scope"] = {k:v for k,v in raw["scope"].items() if k not in ("code","max_lines","forbid_imports")}
 cases,use_tbl = raw.get("cases",{}),raw.get("use")
 if isinstance(use_tbl,dict):use_tbl.pop("concepts",None)
 _strip_outside_digest(cases,raw.get("decisions"))
 for qm in (raw.get("open") or {}).values() if isinstance(raw.get("open"),dict) else ():
  if isinstance(qm,dict):qm.pop("owner",None)
 prof_ref = use_tbl.get("profile","") if isinstance(use_tbl,dict) else ""
 prof = _load_merged_profile(prof_ref,profiles_dir)
 prof.pop("concepts",None)
 waived = use_tbl.get("waive",{}) if isinstance(use_tbl,dict) and isinstance(use_tbl.get("waive"),dict) else {}
 _strip_outside_digest(prof.get("cases",{}),prof.get("decisions"))
 sw_set,sw_base = set(sc_writes),{w.split("#",1)[0] for w in sc_writes}
 inh = {k:{**cm,**({"writes":[w for w in cm["writes"] if isinstance(w,str) and (w in sw_set or w.split("#",1)[0] in sw_set or ("#" not in w and w in sw_base))]} if isinstance(cm.get("writes"),list) else {})} for k,cm in (prof.get("cases") or {}).items() if k not in waived and isinstance(cm,dict)}
 eff = {**inh,**cases}
 own_inv,prof_inv = (set((d.get("invariants") or {}).keys()) if isinstance(d.get("invariants"),dict) else set() for d in (raw,prof))
 inv_k = sorted(own_inv | prof_inv)
 keys_of = lambda m,s:{k for cm in m.values() if isinstance(cm,dict) for k in cm.get(s,{})}
 own_w,own_t,used_w,used_t = keys_of(cases,"when"),keys_of(cases,"then") | own_inv,keys_of(eff,"when"),keys_of(eff,"then") | own_inv | prof_inv
 if isinstance(use_tbl,dict) and isinstance(uv := use_tbl.get("vocabulary"),dict):
  nw,nt = [w for w in uv.get("when",[]) if w in own_w],[t for t in uv.get("then",[]) if t in own_t]
  if nvoc := {**({"when":nw} if nw else {}),**({"then":nt} if nt else {})}:use_tbl["vocabulary"] = nvoc
  else:use_tbl.pop("vocabulary",None)
 req_d = prof.get("requires") if isinstance(prof.get("requires"),dict) else {}
 p_proof,p_sec,p_sim = str(req_d.get("proof","")),([str(x) for x in req_d["security"]] if isinstance(req_d.get("security"),list) else []),req_d.get("simulation") == "required"
 if req_d:
  if rt := {k:v for k,v in req_d.items() if k not in ("max_lines","forbid_imports")}:prof["requires"] = rt
  else:prof.pop("requires",None)
 if "vocabulary" in prof:
  prof["vocabulary"] = {"when":[w for w in prof["vocabulary"].get("when",[]) if w in used_w],"then":[t for t in prof["vocabulary"].get("then",[]) if t in used_t]}
 if isinstance(rp := prof.get("projections"),dict):
  pw,pt = ({k:v for k,v in (rp.get(s) or {}).items() if k in u} if isinstance(rp.get(s),dict) else {} for s,u in (("when",used_w),("then",used_t)))
  for k,v in rp.items():
   if k not in ("when","then") and not isinstance(v,dict):
    if k in used_t and k not in pt:pt[k] = v
    elif k in used_w and k not in pw:pw[k] = v
  if np := {**({"when":pw} if pw else {}),**({"then":pt} if pt else {})}:prof["projections"] = np
  else:prof.pop("projections",None)
 budgets,has_b = extract_contract_budgets(raw,use_tbl,dr1_digest)
 formal,has_f = extract_contract_formal(raw,use_tbl,dr1_digest)
 cutover,has_c = extract_contract_cutover(raw,use_tbl,dr1_digest)
 risks,controls = extract_contract_risks_and_controls(raw,prof,use_tbl,dr1_digest)
 d_in = {"contract":raw,"profiles":({prof_ref:prof} if prof_ref else {})}
 if protos := [*(['formal-evidence/1'] if has_f else []),*(['parity-evidence/1'] if has_c else []),*(['performance-evidence/1'] if has_b else [])]:d_in["evidence_protocols"] = protos
 dig,has_ref = dr1_digest(d_in),isinstance(appr,dict) and bool(appr.get("ref"))
 st = "blocked" if _has_approval_blocker(raw,prof) else ("current" if has_ref and appr["ref"] == dr1_ref(dig) else ("stale" if has_ref else "absent"))
 open_m = raw.get("open") if isinstance(raw.get("open"),dict) else {}
 own_d = [d for d in (raw.get("decisions") or {}).values() if isinstance(d,dict)] if isinstance(raw.get("decisions"),dict) else []
 decs = [d for s in (raw.get("decisions"),prof.get("decisions")) if isinstance(s,dict) for d in s.values() if isinstance(d,dict)]
 blk = lambda ph:any(isinstance(q,dict) and q.get("blocks") == ph for q in open_m.values()) or any(d.get("pick","") == "" and d.get("decide_by") == ph for d in decs)
 roots = resolve_shadow_roots(path)
 return {"drift":str(raw.get("drift","0.2")),"id":cid,"digest":dig,"ref":dr1_ref(dig),"approval":st,"approver":str(appr.get("by","")) if has_ref else "","profile_proof":p_proof,"profile_security":p_sec,"profile_simulation":p_sim,"scope_code":sc_code,"scope_reads":sc_reads,"scope_writes":sc_writes,"invariants":inv_k,"cases":eff,"budgets":budgets,"formal":formal,"cutover":cutover,"risks":risks,"controls":controls,"required_capabilities":list(raw.get("required_capabilities",[])),"area_root":roots["source_root"],"shadow_area_root":roots["area_root"],"open_cnt":len(open_m) + sum(1 for d in own_d if d.get("pick","") == ""),"exec_blk":blk("execution"),"rel_blk":blk("release") or any(isinstance(c,dict) and c.get("status") == "deferred" for c in eff.values())}
def load_proof_events(events_paths, area_root=None, target_run_id=""):
 from drift_shadow_junit import order_shadow_shards_py,shadow_inputs_fresh
 shards = [f for p in events_paths for f in (sorted(p.glob("*.jsonl")) if p.is_dir() else ([p] if p.is_file() and p.name.endswith(".jsonl") else []))]
 events,gone,inc,errs,snaps,shard_subs,all_snap,sh_hashes,parsed_shards,class_latest = [],{},0,[],set(),set(),bool(shards),[],[],{}
 for sf in shards:
  raw,mp = sf.read_bytes(),sf.with_suffix(".meta.json")
  sh_hashes.append("sha256:" + hashlib.sha256(raw).hexdigest())
  has_inv,c_set,t_set,snap,sr,sref = mp.is_file(),set(),set(),"",None,""
  if has_inv:
   try:inv = validate_inventory_sidecar(mp); c_set,t_set,snap,sr,sref = set(inv["classes"]),set(inv["tests"]),inv["snapshot"],inv.get("shadow_run"),inv.get("subject_ref","")
   except Exception as exc: errs.append(f"{mp.name}: {exc}"); all_snap = False; continue
  else:all_snap = False
  if sr and not shadow_inputs_fresh(sr,sf,area_root):continue
  parsed_shards.append((sf,raw,has_inv,c_set,t_set,snap,sr,sref))
 ordered_shards,sh_errs = order_shadow_shards_py(parsed_shards,target_run_id)
 errs.extend(sh_errs)
 for sf,raw,has_inv,c_set,t_set,snap,sr,sref in ordered_shards:
  if snap:snaps.add(snap)
  else:all_snap = False
  if sref:shard_subs.add(sref)
  sel_t = set(sr.get("selected_tests") or ()) if isinstance(sr,dict) else set()
  for cls in c_set:
   if sel_t and (prev_t := class_latest.get(cls,set())):t_set |= {pt for pt in prev_t if pt.startswith(f"{cls}#") and pt not in sel_t}
   class_latest[cls] = {t for t in t_set if t.startswith(f"{cls}#")}
  cnt = 0
  for idx,line in enumerate(raw.decode("utf-8").splitlines(),1):
   if not line.strip():continue
   try:ev = validate_event_line(line)
   except Exception as exc: errs.append(f"events:{sf.name}:{idx}: DR-E701 {exc}"); continue
   cnt += 1; tid = ev["test"].split("[",1)[0]; cls = tid.split("#",1)[0] if "#" in tid else ""
   if not has_inv or cls not in c_set or tid not in t_set or tid not in class_latest.get(cls,t_set):gone[ev["contract"]] = gone.get(ev["contract"],0) + 1
   else:events.append(ev)
  if has_inv and snap and t_set and cnt == 0:inc += 1
 (sec_recs,sec_errs),(form_recs,form_errs),(par_recs,par_errs),(mig_recs,mig_errs),(sim_recs,sim_errs) = (fn(events_paths,_decode_no_dup_keys) for fn in (load_security_receipts_impl,load_formal_receipts_impl,load_parity_receipts_impl,load_migration_receipts_impl,load_simulation_receipts_impl))
 errs.extend(sec_errs + form_errs + par_errs + mig_errs + sim_errs)
 return events,gone,inc,errs,sec_recs,form_recs,par_recs,mig_recs,shard_subs,(next(iter(snaps)) if all_snap and inc == 0 and events and len(snaps) == 1 else ""),sh_hashes,sorted(snaps),bool(all_snap and shards)
def _proof_rank(floor): return {"killed": 3, "verified": 2, "bound": 1}.get(floor, 0)
def validate_mutation_manifest(text): return validate_mutation_manifest_impl(text, _decode_no_dup_keys)
def load_mutation_events(paths, manifest): return load_mutation_events_impl(paths, manifest, _decode_no_dup_keys)
def evaluate_contract_mutations(contract, manifest, latest_mut, mut_errors): return evaluate_contract_mutations_impl(contract, manifest, latest_mut, mut_errors, digest_matches)
def evaluate_contract(contract, cfg_state, events, gone, incomplete_shards, ev_errors, policy=None, min_proof="verified", phase="", total_open=None, mutations_ok=False, perf_bundle=None, expected_subject=None, sec_receipts=None, expected_snapshot="", formal_receipts=None, shard_subject_refs=None, manifest_sources=None, parity_receipts=None, mig_receipts=None, allow_exec_reuse=False, base_contract=None, release_attest=False, sim_receipts=None, ra_receipts=None, comp_manifests=None):
 from drift_verify_mig import evaluate_contract_composition_core
 cid,dig,pol = contract["id"],contract["digest"],policy or {}
 is_03,req_caps = contract.get("drift") == "0.3",set(contract.get("required_capabilities") or ())
 pol_on,matching,ignored,latest,sup,hs_bad = pol.get("pack") == "core@1",[],0,{},0,False
 for ev in events:
  if ev["contract"] == cid:
   if digest_matches(ev["digest"],dig) or (allow_exec_reuse and base_contract and digest_matches(ev["digest"],base_contract.get("digest",""))):
    if is_03 and (ev.get("schema") != "0.3" or not req_caps.issubset(set(ev.get("capabilities") or ()))):hs_bad = True; continue
    matching.append(ev)
   else:ignored += 1
 for ev in matching:sup += 1 if ev["test"] in latest else 0; latest[ev["test"]] = ev
 active,res,rsn = list(latest.values()),[],[]
 for case_id in sorted(contract["cases"]):
  cm = contract["cases"][case_id]
  if isinstance(cm,dict) and "status" in cm:continue
  for lv in (cm.get("at") or ["*"]):
   cov = [ev for ev in active if case_id in ev["cases"] and (lv == "*" or ev["level"] == lv)]
   res.append({"case":case_id,"level":lv,"state":"missing" if not cov else ("red" if any(ev["outcome"] != "passed" for ev in cov) else ("verified" if any(case_id in ev["read"] for ev in cov) else "bound"))})
 if cfg_state == "missing":rsn.append("config.missing")
 elif cfg_state != "current":rsn.extend((["config.findings"] if cfg_state == "stale" else []) + [f"config.approval.{cfg_state}"])
 if contract["approval"] != "current":rsn.extend((["contract.findings"] if contract["approval"] == "stale" else []) + [f"contract.approval.{contract['approval']}"])
 elif pol_on and isinstance(pol.get("approvers"),list) and pol["approvers"] and contract.get("approver","") not in pol["approvers"]:rsn.append("contract.approval.unlisted")
 if pol_on and isinstance(pol.get("max_open"),int) and not isinstance(pol.get("max_open"),bool) and pol["max_open"] > 0 and contract.get("open_cnt",0) > 0 and (contract.get("open_cnt",0) if total_open is None else total_open) > pol["max_open"]:rsn.append("policy.max_open")
 if contract.get("exec_blk"):rsn.append("contract.blocked.execution")
 if phase == "release" and contract.get("rel_blk"):rsn.append("contract.blocked.release")
 if ev_errors or hs_bad:rsn.append("events.invalid")
 if incomplete_shards > 0:rsn.append("shard.incomplete")
 eff_rank = max(_proof_rank(min_proof),_proof_rank(str(pol.get("proof","")) if pol_on else ""),_proof_rank(str(contract.get("profile_proof","")))) or 2
 if gone > 0 or incomplete_shards > 0 or not res or any(r["state"] not in (("verified",) if eff_rank >= 2 else ("verified","bound")) for r in res) or (eff_rank >= 3 and not mutations_ok):rsn.append("proof.not_green")
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
 for k,v in (("assurance_digest",contract.get("assurance_digest")),("assurance_ref",contract.get("assurance_ref")),("performance",p_sum),("pending_budgets",pend_b),("pending_formal",pend_f),("security_checks",s_checks),("formal_checks",f_checks),("parity_checks",par_checks),("migration_checks",m_checks),("simulation_checks",sim_checks),("composition_checks",comp_checks)):
  if v:out[k] = v
 return out
def main(argv):
 if "--self-test" in argv:
  from drift_shadow_junit import run_verifier_self_test; return run_verifier_self_test()
 ap = argparse.ArgumentParser(prog="drift_verify.py")
 ap.add_argument("targets",nargs="*",type=Path)
 for fl in ("--state-dir","--config","--profiles","--mutants","--measurements","--subject","--security-lock","--base","--attest","--attest-sig","--trust-root","--signatures","--signature-policy"):ap.add_argument(fl,type=Path)
 for fl in ("--events","--mutation-events"):ap.add_argument(fl,type=Path,action="append")
 ap.add_argument("--changed",action="append",default=[])
 for fl in ("--changed-none","--json"):ap.add_argument(fl,action="store_true")
 for fl in ("--subject-artifact","--subject-tree","--run-id","--verify-time","--phase"):ap.add_argument(fl,default="")
 ap.add_argument("--min-proof",choices=("bound","verified","killed"),default="")
 a = ap.parse_args(argv)
 from drift_shadow_junit import lookup_registered_shadow_py
 ex_sd = str(a.state_dir) if a.state_dir else ""
 sd_p = Path(sd_e) if (sd_e := ex_sd or os.environ.get("DRIFT_STATE_DIR","").strip() or lookup_registered_shadow_py(Path.cwd())) else None
 tgts,cfg_p,ev_p = a.targets or ([sd_p / ".drift" / "contracts"] if sd_p else []),a.config or ((sd_p / ".drift" / "config.toml") if sd_p else None),a.events or ([sd_p / ".drift-work" / "events"] if sd_p and (sd_p / ".drift-work" / "events").is_dir() else [])
 if not tgts or not cfg_p or not ev_p: ap.error("targets, --config and --events are required")
 if bool(a.mutants) != bool(a.mutation_events):ap.error("--mutants and --mutation-events must be supplied together")
 try:roots = resolve_shadow_roots(tgts[0],ex_sd)
 except Exception as exc: print(f"drift_verify.py: {exc}", file=sys.stderr); return 2
 cfg_st,cfg_dig,pol = verify_config_toml(cfg_p)
 p_dir,c_files = a.profiles or (cfg_p.parent / "profiles"),[cf for t in tgts for cf in (sorted(t.glob("*.toml")) if t.is_dir() else [t])]
 evs,gone,inc,ev_errs,sec_recs,form_recs,par_recs,mig_recs,shard_subs,exp_snap,sh_h,sn_l,sn_ok = load_proof_events(ev_p,roots["area_root"],"" if a.measurements else a.run_id)
 from drift_verify_mig import load_composition_manifests_core,resolve_verifier_subject_cli
 ra_recs,ra_errs = load_ra_receipts_core(ev_p,_decode_no_dup_keys)
 comp_mans,comp_errs = load_composition_manifests_core(ev_p,_decode_no_dup_keys)
 ev_errs.extend(ra_errs + comp_errs)
 sim_recs,_ = load_simulation_receipts_impl(ev_p,_decode_no_dup_keys)
 m_man,lat_m,m_errs = None,{},[]
 if a.mutants and a.mutation_events:
  try:m_man = validate_mutation_manifest(a.mutants.read_text("utf-8")); lat_m,m_errs = load_mutation_events(a.mutation_events,m_man)
  except Exception as exc:m_errs.append(str(exc))
 exp_sub,man_srcs = resolve_verifier_subject_cli(a,_decode_no_dup_keys,canonical_json,parse_subject_manifest_impl,parse_security_lock_impl)
 perf_b,by_c = load_measurement_bundle(a.measurements,_decode_no_dup_keys,digest_matches),{}
 for ev in evs:by_c.setdefault(ev["contract"],[]).append(ev)
 parsed = [verify_contract_toml(cf,p_dir) for cf in c_files]
 base_by_id = {bc["id"]:bc for bf in ((sorted(a.base.glob("*.toml")) if a.base.is_dir() else [a.base]) if a.base else ()) for bc in (verify_contract_toml(bf,p_dir),)}
 tot_open,reuse_ok = sum(c.get("open_cnt",0) for c in parsed),bool(a.base and (a.changed_none or not a.changed))
 raw_v = [evaluate_contract(c,cfg_st,by_c.get(c["id"],[]),gone.get(c["id"],0),inc,ev_errs,pol,a.min_proof,a.phase,tot_open,evaluate_contract_mutations(c,m_man,lat_m,m_errs),perf_b,exp_sub,sec_recs,exp_snap,form_recs,shard_subs,man_srcs,par_recs,mig_recs,reuse_ok,base_by_id.get(c["id"]),bool(a.attest),sim_recs,ra_recs,comp_mans) for c in parsed]
 verdicts = raw_v if ((a.signatures or a.signature_policy) and not a.attest and not a.attest_sig) else apply_openssh_trust_verdicts(raw_v,a,cfg_st,cfg_dig,sh_h,sn_l,sn_ok,inc,m_man,perf_b,_decode_no_dup_keys,exp_sub)
 verdicts = evaluate_detached_signatures_core(verdicts,parsed,a,cfg_dig,_decode_no_dup_keys,canonical_json,digest_matches)
 ok = bool(verdicts) and all(v["ok"] for v in verdicts)
 if a.json:print(json.dumps({"ok":ok,"contracts":verdicts},indent=2,sort_keys=True))
 else:
  for v in verdicts: print(f"{v['id']} {v['ref']}: {'green' if v['ok'] else 'not green (' + ', '.join(v['reasons']) + ')'}")
 return 0 if ok else 1
if __name__ == "__main__":sys.exit(main(sys.argv[1:]))
