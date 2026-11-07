#!/usr/bin/env python3
"""DRIFT Independent Reference Proof Verifier (MIT License)."""
import argparse, hashlib, json, math, re, sys, tomllib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from drift_verify_perf import evaluate_contract_budgets, evaluate_contract_mutations_impl, extract_contract_budgets, load_measurement_bundle, load_mutation_events_impl
from drift_verify_sec import evaluate_contract_security_impl, load_security_receipts_impl, validate_mutation_manifest_impl
from drift_verify_ssh import apply_openssh_trust_verdicts

SAFE_INT = (1 << 53) - 1
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORD_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DIGEST_RE = re.compile(r"^dr1:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})$")
PACK_REF_RE = re.compile(r"^dr1:[0-9a-f]{12}$")
SNAPSHOT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
CLASS_TOKEN_RE = re.compile(r"^[^# \t\r\n/\\\[\]]+$")
METHOD_TOKEN_RE = re.compile(r"^[^# \t\r\n\[\]]+$")
OUTCOMES = frozenset(("passed", "failed", "skipped", "disabled", "interrupted", "timeout"))
EVENT_KEYS = frozenset(("test", "contract", "cases", "level", "outcome", "read", "digest"))
META_KEYS = frozenset(("version", "classes", "tests", "snapshot", "pack_ref", "touched", "self_stubbed", "inputs", "env", "execution_ref"))
ENV_KEYS = frozenset(("toolchain", "deps", "config", "runner", "drift", "adapter", "policy"))
_ESC_MAP = {0x22: '\\"', 0x5C: "\\\\", 0x08: "\\b", 0x0C: "\\f", 0x0A: "\\n", 0x0D: "\\r", 0x09: "\\t"}


def jcs_string(s):
 return '"' + "".join(_ESC_MAP.get(cp := ord(c), f"\\u{cp:04x}" if cp < 0x20 else c) for c in s) + '"'


def jcs_number(val):
 if isinstance(val, int) and not isinstance(val, bool):
  if not (-SAFE_INT <= val <= SAFE_INT): raise ValueError("int")
  return str(val)
 f = float(val)
 if not math.isfinite(f): raise ValueError("nan")
 if f == 0.0: return "0"
 neg, f = f < 0.0, abs(f)
 s = repr(f)
 if "e" in s or "E" in s:
  m, e = s.lower().split("e", 1)
  d, n = m.replace(".", "").rstrip("0") or "0", int(e) + 1
 elif "." in s:
  ip, fp = s.split(".", 1)
  d, n = (ip + fp).lstrip("0").rstrip("0") or "0", (len(ip) if ip != "0" else -(len(fp) - len(fp.lstrip("0"))))
 else: d, n = s.rstrip("0") or "0", len(s)
 k = len(d)
 b = d + ("0" * (n - k)) if k <= n <= 21 else (f"{d[:n]}.{d[n:]}" if 0 < n <= 21 else (f"0.{'0' * (-n)}{d}" if -6 < n <= 0 else f"{d if k == 1 else f'{d[0]}.{d[1:]}'}e{'+' if n >= 1 else '-'}{abs(n - 1)}"))
 return f"-{b}" if neg else b


def canonical_json(obj):
 if obj is None or isinstance(obj, bool): return "null" if obj is None else ("true" if obj else "false")
 if isinstance(obj, (int, float)): return jcs_number(obj)
 if isinstance(obj, str): return jcs_string(obj)
 if isinstance(obj, (list, tuple)): return "[" + ",".join(canonical_json(x) for x in obj) + "]"
 if isinstance(obj, dict):
  return "{" + ",".join(f"{jcs_string(str(k))}:{canonical_json(v)}" for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]).encode("utf-16-be"))) + "}"
 raise TypeError(type(obj).__name__)


def dr1_digest(obj): return "dr1:sha256:" + hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
def dr1_ref(d): return "dr1:" + d[11:23] if d.startswith("dr1:sha256:") else ""
def digest_matches(ed, fd): return bool(fd) and (ed == fd or ed == dr1_ref(fd))


def _decode_no_dup_keys(text):
 d, ins, esc = 0, False, False
 for ch in text:
  if ins:
   esc = (not esc) if ch == "\\" else False
   if ch == '"' and not esc: ins = False
  elif ch == '"': ins = True
  elif ch in "{[":
   d += 1
   if d > 64: raise ValueError("depth")
  elif ch in "}]": d = max(0, d - 1)
 def hook(pairs):
  out = {}
  for k, v in pairs:
   if k in out: raise ValueError(k)
   out[k] = v
  return out
 return json.loads(text, object_pairs_hook=hook)


def validate_event_line(line):
 doc = _decode_no_dup_keys(line)
 if not isinstance(doc, dict) or any(k not in EVENT_KEYS for k in doc) or any(r not in doc for r in ("test", "contract", "cases", "level", "outcome")): raise ValueError("event")
 cs, rd, dig = doc["cases"], doc.get("read", []), doc.get("digest", "")
 if not isinstance(doc["test"], str) or not doc["test"].strip() or not isinstance(doc["contract"], str) or not ID_RE.match(doc["contract"]): raise ValueError("test")
 if not isinstance(cs, list) or not cs or len(set(cs)) != len(cs) or not all(isinstance(c, str) and ID_RE.match(c) for c in cs): raise ValueError("cases")
 if not isinstance(doc["level"], str) or not WORD_RE.match(doc["level"]) or doc["outcome"] not in OUTCOMES: raise ValueError("level")
 if not isinstance(rd, list) or len(set(rd)) != len(rd) or not all(isinstance(r, str) and r in cs for r in rd): raise ValueError("read")
 if dig != "" and (not isinstance(dig, str) or not DIGEST_RE.match(dig)): raise ValueError("digest")
 return {"test": doc["test"], "contract": doc["contract"], "cases": cs, "level": doc["level"], "outcome": doc["outcome"], "read": rd, "digest": dig}


def validate_inventory_text(text):
 doc = _decode_no_dup_keys(text)
 if not isinstance(doc, dict) or any(k not in META_KEYS for k in doc) or doc.get("version") not in (1, 2) or isinstance(doc.get("version"), bool): raise ValueError("inv")
 execution_ref = doc.get("execution_ref", "")
 if (doc["version"] == 2 and (not isinstance(execution_ref, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", execution_ref))) or (doc["version"] == 1 and "execution_ref" in doc): raise ValueError("execution_ref")
 cls, tsts = doc.get("classes"), doc.get("tests")
 if not isinstance(cls, list) or not all(isinstance(x, str) and CLASS_TOKEN_RE.match(x) for x in cls) or cls != sorted(set(cls)): raise ValueError("cls")
 c_set = set(cls)
 if not isinstance(tsts, list) or not all(isinstance(x, str) and "#" in x for x in tsts) or tsts != sorted(set(tsts)) or any((p := t.split("#", 1))[0] not in c_set or not METHOD_TOKEN_RE.match(p[1]) for t in tsts): raise ValueError("tst")
 t_set, snap, pref = set(tsts), doc.get("snapshot", ""), doc.get("pack_ref", "")
 if ("snapshot" in doc and (not isinstance(snap, str) or not SNAPSHOT_RE.match(snap))) or ("pack_ref" in doc and (not isinstance(pref, str) or not PACK_REF_RE.match(pref))): raise ValueError("snap")
 if "touched" in doc and (not isinstance(tc := doc["touched"], list) or not all(isinstance(x, str) and x.strip() for x in tc) or tc != sorted(set(tc)) or any(tp.startswith("/") or "\\" in tp or any(s in ("", ".", "..") for s in tp.split("/")) for tp in tc)): raise ValueError("touched")
 if "self_stubbed" in doc and (not isinstance(doc["self_stubbed"], list) or any(not isinstance(x, str) or x not in t_set for x in doc["self_stubbed"])): raise ValueError("stub")
 if "inputs" in doc and (not isinstance(ri := doc["inputs"], dict) or any(tid not in t_set or not isinstance(fm, dict) or any(not isinstance(fp, str) or not fp.strip() or not isinstance(ov, str) or not ov.strip() for fp, ov in fm.items()) for tid, fm in ri.items())): raise ValueError("in")
 if "env" in doc and (not isinstance(re_e := doc["env"], dict) or set(re_e) != ENV_KEYS or any(not isinstance(ev, str) or not ev.strip() for ev in re_e.values())): raise ValueError("env")
 return {"classes": c_set, "tests": t_set, "snapshot": snap, "pack_ref": pref, "version": doc["version"], "execution_ref": execution_ref, "touched": set(doc.get("touched", []))}


def validate_inventory_sidecar(path): return validate_inventory_text(path.read_text(encoding="utf-8"))


def verify_config_toml(path):
 if not path.is_file(): return "missing", "", {}
 raw = tomllib.loads(path.read_text(encoding="utf-8"))
 appr, dig, pol = raw.pop("approval", None), dr1_digest(raw), (raw.get("policy") if isinstance(raw.get("policy"), dict) else {})
 if not isinstance(appr, dict) or not appr.get("ref"): return "absent", dig, pol
 st = "current" if appr["ref"] == dr1_ref(dig) else "stale"
 return st, dig, (pol if st == "current" else {})


def _is_unanchored_prose_source(raw):
 s = raw.strip()
 if not s or s.startswith("ADR-") or ";" in s or "://" in s: return False
 if " " in s: return True
 if ":" in s: return False
 b = s.split("@sha256:", 1)[0].replace("\\", "/")
 if not b or b.startswith(("note:", "cite:")) or any(c in b for c in " \t\n\r;"): return True
 dot = b.rfind(".")
 if 0 < dot < len(b) - 1 and b[dot + 1:].isalnum() and any(c.isalpha() for c in b[dot + 1:]): return False
 return not ("/" in b and any("a" <= c <= "z" for c in b))


def _contains_todo(v):
 return v == "todo" if isinstance(v, str) else (any(_contains_todo(x) for x in v) if isinstance(v, list) else (any(_contains_todo(x) for x in v.values()) if isinstance(v, dict) else False))


def _has_approval_blocker(raw, prof):
 if isinstance(sc := raw.get("scope"), dict) and sc.get("indirect") == "unknown": return True
 if any(_contains_todo(raw.get(s)) for s in ("use", "scope", "cases", "budgets")): return True
 if isinstance(ot := raw.get("open"), dict) and any(isinstance(q, dict) and q.get("blocks", "approval") == "approval" for q in ot.values()): return True
 return any(isinstance(d, dict) and d.get("pick", "") == "" and d.get("decide_by", "approval") == "approval" for s in (raw.get("decisions"), prof.get("decisions")) if isinstance(s, dict) for d in s.values())


def _load_merged_profile(prof_ref, profiles_dir):
 p0 = profiles_dir / f"{prof_ref}.toml"
 if not prof_ref or not p0.is_file(): return {}
 prof = tomllib.loads(p0.read_text(encoding="utf-8"))
 exts = prof.pop("extends", None)
 if not isinstance(exts, list) or not exts: return prof
 m, vw, vt, prm, pw, pt, req, cs, dc = {"drift": prof.get("drift", "0.2"), "profile": prof.get("profile", prof_ref)}, [], [], {}, {}, {}, {}, {}, {}
 for r in [*exts, prof_ref]:
  bp = prof if r == prof_ref else (tomllib.loads(p.read_text(encoding="utf-8")) if (p := profiles_dir / f"{r}.toml").is_file() else {})
  bv = bp.get("vocabulary") if isinstance(bp.get("vocabulary"), dict) else {}
  vw.extend(w for w in bv.get("when", []) if w not in vw)
  vt.extend(t for t in bv.get("then", []) if t not in vt)
  for s, d in (("params", prm), ("cases", cs), ("decisions", dc)):
   if isinstance(bp.get(s), dict): d.update(bp[s])
  if isinstance(bpr := bp.get("projections"), dict):
   pw.update(bpr["when"] if isinstance(bpr.get("when"), dict) else {})
   pt.update(bpr["then"] if isinstance(bpr.get("then"), dict) else {})
   for pk, pv in bpr.items():
    if pk not in ("when", "then") and isinstance(pv, str): (pt if pk in vt else pw)[pk] = pv
  if isinstance(bp.get("requires"), dict):
   for k, v in bp["requires"].items():
    if k == "security" and isinstance(v, list):
     req["security"] = list(dict.fromkeys([*req.get("security", []), *(str(x) for x in v)]))
    elif k != "proof" or "proof" not in req or _proof_rank(str(v)) > _proof_rank(str(req["proof"])): req[k] = v
  if "kit" in bp: m["kit"] = bp["kit"]
 m["vocabulary"] = {"when": vw, "then": vt}
 for k, v in (("params", prm), ("requires", req), ("cases", cs), ("decisions", dc)):
  if v: m[k] = v
 if pw or pt: m["projections"] = {**({"when": pw} if pw else {}), **({"then": pt} if pt else {})}
 return m


def _strip_outside_digest(cases, decs):
 for cm in (cases or {}).values():
  if isinstance(cm, dict): cm.pop("note", None)
 if isinstance(decs, dict):
  for dm in decs.values():
   if isinstance(dm, dict):
    dm.pop("owner", None)
    dm.pop("note", None)
    if dm.get("evidence") == "observed" and _is_unanchored_prose_source(str(dm.get("source", ""))): dm.pop("source", None)


def verify_contract_toml(path, profiles_dir):
 raw = tomllib.loads(path.read_text(encoding="utf-8"))
 cid, appr = raw.get("id", path.stem), raw.pop("approval", None)
 raw.pop("note", None)
 raw_sc = raw.get("scope") if isinstance(raw.get("scope"), dict) else {}
 sc_code = [str(x) for x in raw_sc.get("code", []) if isinstance(x, str)] if isinstance(raw_sc.get("code"), list) else []
 if isinstance(raw.get("scope"), dict): raw["scope"] = {k: v for k, v in raw["scope"].items() if k not in ("code", "max_lines", "forbid_imports")}
 cases, use_tbl = raw.get("cases", {}), raw.get("use")
 _strip_outside_digest(cases, raw.get("decisions"))
 if isinstance(raw.get("open"), dict):
  for qm in raw["open"].values():
   if isinstance(qm, dict): qm.pop("owner", None)
 prof_ref = use_tbl.get("profile", "") if isinstance(use_tbl, dict) else ""
 prof = _load_merged_profile(prof_ref, profiles_dir)
 waived = use_tbl.get("waive", {}) if isinstance(use_tbl, dict) and isinstance(use_tbl.get("waive"), dict) else {}
 _strip_outside_digest(prof.get("cases", {}), prof.get("decisions"))
 inh = {k: cm for k, cm in (prof.get("cases") or {}).items() if k not in waived and isinstance(cm, dict)}
 eff = {**inh, **cases}
 keys_of = lambda m, s: {k for cm in m.values() if isinstance(cm, dict) for k in cm.get(s, {})}
 own_w, own_t, used_w, used_t = keys_of(cases, "when"), keys_of(cases, "then"), keys_of(eff, "when"), keys_of(eff, "then")
 if isinstance(use_tbl, dict) and isinstance(uv := use_tbl.get("vocabulary"), dict):
  nw, nt = [w for w in uv.get("when", []) if w in own_w], [t for t in uv.get("then", []) if t in own_t]
  if nvoc := {**({"when": nw} if nw else {}), **({"then": nt} if nt else {})}: use_tbl["vocabulary"] = nvoc
  else: use_tbl.pop("vocabulary", None)
 p_proof, p_sec = "", []
 if isinstance(prof.get("requires"), dict):
  p_proof = str(prof["requires"].get("proof", ""))
  if isinstance(prof["requires"].get("security"), list): p_sec = [str(x) for x in prof["requires"]["security"]]
  if rt := {k: v for k, v in prof["requires"].items() if k not in ("max_lines", "forbid_imports")}: prof["requires"] = rt
  else: prof.pop("requires", None)
 if "vocabulary" in prof:
  prof["vocabulary"] = {"when": [w for w in prof["vocabulary"].get("when", []) if w in used_w], "then": [t for t in prof["vocabulary"].get("then", []) if t in used_t]}
 if isinstance(rp := prof.get("projections"), dict):
  pw = {k: v for k, v in (rp.get("when") or {}).items() if k in used_w} if isinstance(rp.get("when"), dict) else {}
  pt = {k: v for k, v in (rp.get("then") or {}).items() if k in used_t} if isinstance(rp.get("then"), dict) else {}
  for k, v in rp.items():
   if k not in ("when", "then") and not isinstance(v, dict):
    if k in used_t and k not in pt: pt[k] = v
    elif k in used_w and k not in pw: pw[k] = v
  if np := {**({"when": pw} if pw else {}), **({"then": pt} if pt else {})}: prof["projections"] = np
  else: prof.pop("projections", None)
 budgets, has_b = extract_contract_budgets(raw, use_tbl, dr1_digest)
 d_in = {"contract": raw, "profiles": ({prof_ref: prof} if prof_ref else {})}
 if has_b: d_in["evidence_protocols"] = ["performance-evidence/1"]
 dig = dr1_digest(d_in)
 has_ref = isinstance(appr, dict) and bool(appr.get("ref"))
 st = "blocked" if _has_approval_blocker(raw, prof) else ("current" if has_ref and appr["ref"] == dr1_ref(dig) else ("stale" if has_ref else "absent"))
 open_m = raw.get("open") if isinstance(raw.get("open"), dict) else {}
 own_d = [d for d in (raw.get("decisions") or {}).values() if isinstance(d, dict)] if isinstance(raw.get("decisions"), dict) else []
 decs = [d for s in (raw.get("decisions"), prof.get("decisions")) if isinstance(s, dict) for d in s.values() if isinstance(d, dict)]
 blk = lambda ph: any(isinstance(q, dict) and q.get("blocks") == ph for q in open_m.values()) or any(d.get("pick", "") == "" and d.get("decide_by") == ph for d in decs)
 return {"id": cid, "digest": dig, "ref": dr1_ref(dig), "approval": st, "approver": str(appr.get("by", "")) if has_ref else "", "profile_proof": p_proof, "profile_security": p_sec, "scope_code": sc_code, "cases": eff, "budgets": budgets, "open_cnt": len(open_m) + sum(1 for d in own_d if d.get("pick", "") == ""), "exec_blk": blk("execution"), "rel_blk": blk("release") or any(isinstance(c, dict) and c.get("status") == "deferred" for c in eff.values())}


def load_proof_events(events_paths):
 shards = [f for p in events_paths for f in (sorted(p.glob("*.jsonl")) if p.is_dir() else ([p] if p.is_file() else []))]
 events, gone, inc, errs, snaps, all_snap = [], {}, 0, [], set(), bool(shards)
 for sf in shards:
  mp = sf.with_suffix(".meta.json")
  has_inv, c_set, t_set, snap = mp.is_file(), set(), set(), ""
  if has_inv:
   try:
    inv = validate_inventory_sidecar(mp)
    c_set, t_set, snap = inv["classes"], inv["tests"], inv["snapshot"]
    if snap: snaps.add(snap)
    else: all_snap = False
   except Exception as exc:
    errs.append(f"{mp.name}: {exc}")
    all_snap = False
    continue
  else: all_snap = False
  cnt = 0
  for idx, line in enumerate(sf.read_text(encoding="utf-8").splitlines(), 1):
   if not line.strip(): continue
   try: ev = validate_event_line(line)
   except Exception as exc:
    errs.append(f"events:{sf.name}:{idx}: DR-E701 {exc}")
    continue
   cnt += 1
   tid = ev["test"].split("[", 1)[0]
   if not has_inv or (tid.split("#", 1)[0] if "#" in tid else "") not in c_set or tid not in t_set: gone[ev["contract"]] = gone.get(ev["contract"], 0) + 1
   else: events.append(ev)
  if has_inv and snap and t_set and cnt == 0: inc += 1
 sec_recs, sec_errs = load_security_receipts_impl(events_paths, _decode_no_dup_keys)
 errs.extend(sec_errs)
 exp_snap = next(iter(snaps)) if all_snap and inc == 0 and events and len(snaps) == 1 else ""
 return events, gone, inc, errs, sec_recs, exp_snap


def _proof_rank(floor): return {"killed": 3, "verified": 2, "bound": 1}.get(floor, 0)
def validate_mutation_manifest(text): return validate_mutation_manifest_impl(text, _decode_no_dup_keys)
def load_mutation_events(paths, manifest): return load_mutation_events_impl(paths, manifest, _decode_no_dup_keys)
def evaluate_contract_mutations(contract, manifest, latest_mut, mut_errors): return evaluate_contract_mutations_impl(contract, manifest, latest_mut, mut_errors, digest_matches)


def evaluate_contract(contract, cfg_state, events, gone, incomplete_shards, ev_errors, policy=None, min_proof="verified", phase="", total_open=None, mutations_ok=False, perf_bundle=None, expected_subject=None, sec_receipts=None, expected_snapshot=""):
 cid, dig, pol = contract["id"], contract["digest"], policy or {}
 pol_on = pol.get("pack") == "core@1"
 matching, ignored, latest, sup = [], 0, {}, 0
 for ev in events:
  if ev["contract"] == cid:
   if digest_matches(ev["digest"], dig): matching.append(ev)
   else: ignored += 1
 for ev in matching:
  sup += 1 if ev["test"] in latest else 0
  latest[ev["test"]] = ev
 active, res, rsn = list(latest.values()), [], []
 for case_id in sorted(contract["cases"]):
  cm = contract["cases"][case_id]
  if isinstance(cm, dict) and "status" in cm: continue
  for lv in (cm.get("at") or ["*"]):
   cov = [ev for ev in active if case_id in ev["cases"] and (lv == "*" or ev["level"] == lv)]
   st = "missing" if not cov else ("red" if any(ev["outcome"] != "passed" for ev in cov) else ("verified" if any(case_id in ev["read"] for ev in cov) else "bound"))
   res.append({"case": case_id, "level": lv, "state": st})
 if cfg_state == "missing": rsn.append("config.missing")
 elif cfg_state != "current": rsn.extend((["config.findings"] if cfg_state == "stale" else []) + [f"config.approval.{cfg_state}"])
 if contract["approval"] != "current": rsn.extend((["contract.findings"] if contract["approval"] == "stale" else []) + [f"contract.approval.{contract['approval']}"])
 elif pol_on and isinstance(pol.get("approvers"), list) and pol["approvers"] and contract.get("approver", "") not in pol["approvers"]: rsn.append("contract.approval.unlisted")
 tot_open = contract.get("open_cnt", 0) if total_open is None else total_open
 if pol_on and isinstance(pol.get("max_open"), int) and not isinstance(pol.get("max_open"), bool) and pol["max_open"] > 0 and contract.get("open_cnt", 0) > 0 and tot_open > pol["max_open"]: rsn.append("policy.max_open")
 if contract.get("exec_blk"): rsn.append("contract.blocked.execution")
 if phase == "release" and contract.get("rel_blk"): rsn.append("contract.blocked.release")
 if ev_errors: rsn.append("events.invalid")
 if incomplete_shards > 0: rsn.append("shard.incomplete")
 eff_rank = max(_proof_rank(min_proof), _proof_rank(str(pol.get("proof", "")) if pol_on else ""), _proof_rank(str(contract.get("profile_proof", ""))))
 allowed = ("verified",) if eff_rank >= 2 else ("verified", "bound")
 if gone > 0 or incomplete_shards > 0 or not res or any(r["state"] not in allowed for r in res) or (eff_rank >= 3 and not mutations_ok): rsn.append("proof.not_green")
 p_rsn, pend_b, p_sum = evaluate_contract_budgets(contract, phase, perf_bundle, expected_subject, digest_matches, pol)
 rsn.extend(r for r in p_rsn if r not in rsn)
 s_rsn, s_checks = evaluate_contract_security_impl(contract, sec_receipts or [], pol if pol_on else {}, expected_snapshot, digest_matches)
 rsn.extend(r for r in s_rsn if r not in rsn)
 out = {"id": cid, "digest": dig, "ref": contract["ref"], "approval": contract["approval"], "ok": not rsn, "reasons": rsn, "ignored": ignored, "superseded": sup, "gone": gone, "results": res}
 if p_sum is not None: out["performance"] = p_sum
 if pend_b: out["pending_budgets"] = pend_b
 if s_checks: out["security_checks"] = s_checks
 return out


def _expect_err(fn, arg):
 try:
  fn(arg)
  raise AssertionError(arg)
 except ValueError: pass


def run_self_test():
 assert canonical_json(-0.0) == "0" and canonical_json(1e21) == "1e+21" and canonical_json(1e-6) == "0.000001" and canonical_json(1e-7) == "1e-7" and canonical_json({"\ue000": 1, "\U0001f600": 2}) == '{"\U0001f600":2,"\ue000":1}'
 for bad in (1 << 53, -(1 << 53), float("nan"), float("inf")): _expect_err(canonical_json, bad)
 ev_b = '"contract":"a","cases":["c"],"level":"unit","outcome":"passed"'
 for b in (f'"test":"t#1","test":"t#2",{ev_b}', f'"test":"t#1",{ev_b},"extra":1', f'"test":"t#1",{ev_b},"read":["other"]', '"test":"t#1","contract":"Bad_Id","cases":["c"],"level":"unit","outcome":"passed"', '"test":"t#1","contract":"a","cases":["c"],"level":"Unit","outcome":"passed"', f'"test":"t#1",{ev_b},"digest":"dr1:UPPER0000000"'):
  _expect_err(validate_event_line, "{" + b + "}")
 _expect_err(validate_event_line, '{"a":' * 65 + '1' + '}' * 65)
 assert len(validate_inventory_text(json.dumps({"version": 1, "classes": ["a.mjs", "b.mjs"], "tests": ["a.mjs#t1", "b.mjs#t2"], "snapshot": "0" * 40, "pack_ref": "dr1:" + "0" * 12, "touched": ["src/a.mjs", "src/b.mjs"], "inputs": {"a.mjs#t1": {"src/a.mjs": "sha256:111"}}, "env": dict.fromkeys(ENV_KEYS, "v")}))["tests"]) == 2
 v2 = validate_inventory_text(json.dumps({"version": 2, "classes": ["a"], "tests": ["a#t"], "execution_ref": "sha256:" + "a" * 64, "touched": []}))
 assert v2["version"] == 2 and v2["execution_ref"] == "sha256:" + "a" * 64 and not v2["touched"]
 ib = '"version":1,"classes":["a"],"tests":["a#t1"]'
 for sfx in ('"version":2,"classes":[],"tests":[]', '"version":true,"classes":[],"tests":[]', '"version":1,"classes":["b","a"],"tests":[]', '"version":1,"classes":["a/b"],"tests":[]', '"version":1,"classes":["a"],"tests":["other#t1"]', f'{ib},"snapshot":"bad"', f'{ib},"pack_ref":"dr1:bad"', f'{ib},"touched":["/abs"]', f'{ib},"touched":["../e"]', f'{ib},"inputs":{{"u#t":{{"f":"1"}}}}', f'{ib},"env":{{"toolchain":"v1"}}', f'{ib},"extra":1'):
  _expect_err(validate_inventory_text, "{" + sfx + "}")
 assert _is_unanchored_prose_source("observed in prod") and _is_unanchored_prose_source("SPEC.md#D209") and not _is_unanchored_prose_source("src/a/Item.java") and not _is_unanchored_prose_source("ADR-0012")
 assert _has_approval_blocker({"open": {"q": {"ask": "?", "blocks": "approval"}}}, {}) and not _has_approval_blocker({"open": {"q": {"ask": "?", "blocks": "execution"}}}, {}) and _has_approval_blocker({"scope": {"indirect": "unknown"}}, {}) and _has_approval_blocker({"cases": {"c": {"then": {"x": "todo"}}}}, {})
 ck = {"id": "svc", "digest": "dr1:sha256:" + "a" * 64, "ref": "dr1:" + "a" * 12, "approval": "current", "approver": "o", "profile_proof": "killed", "cases": {"ok": {"at": ["unit"], "then": {"status": 200}}}, "open_cnt": 0, "exec_blk": False, "rel_blk": False}
 ev = [{"test": "T#ok", "contract": "svc", "cases": ["ok"], "read": ["ok"], "level": "unit", "outcome": "passed", "digest": ck["ref"]}]
 assert not evaluate_contract(ck, "current", ev, 0, 0, [])["ok"] and evaluate_contract(ck, "current", ev, 0, 0, [], mutations_ok=True)["ok"]
 mid = "ok:/cases/ok/then/status"
 md = validate_mutation_manifest(json.dumps({"version": 1, "contracts": [{"id": "svc", "digest": ck["digest"], "mutants": [{"id": mid, "case": "ok", "path": "/cases/ok/then/status", "operator": "add-one", "before": 200, "after": 201}]}]}))
 me = {"manifest": md["digest"], "contract": "svc", "digest": ck["digest"], "mutant": mid, "case": "ok", "outcome": "killed", "control": "passed"}
 assert evaluate_contract_mutations(ck, md, {("svc", mid): me}, []) and not evaluate_contract_mutations(ck, md, {("svc", mid): {**me, "outcome": "survived"}}, [])
 print("drift_verify.py self-test: ok (RFC 8785 JCS, event & full inventory schema vectors passed)")
 return 0


def main(argv):
 if "--self-test" in argv: return run_self_test()
 ap = argparse.ArgumentParser(prog="drift_verify.py")
 ap.add_argument("targets", nargs="+", type=Path)
 ap.add_argument("--config", type=Path, required=True)
 ap.add_argument("--profiles", type=Path)
 ap.add_argument("--events", type=Path, action="append", required=True)
 ap.add_argument("--mutants", type=Path)
 ap.add_argument("--mutation-events", type=Path, action="append")
 ap.add_argument("--measurements", type=Path)
 ap.add_argument("--subject", type=Path)
 ap.add_argument("--subject-artifact", default="")
 ap.add_argument("--subject-tree", default="")
 ap.add_argument("--run-id", default="")
 ap.add_argument("--min-proof", choices=("bound", "verified", "killed"), default="verified")
 ap.add_argument("--phase", choices=("execution", "release"), default="")
 for fl in ("--attest", "--attest-sig", "--trust-root"): ap.add_argument(fl, type=Path)
 ap.add_argument("--verify-time", default="")
 ap.add_argument("--json", action="store_true")
 args = ap.parse_args(argv)
 if bool(args.mutants) != bool(args.mutation_events): ap.error("--mutants and --mutation-events must be supplied together")
 cfg_st, _, pol = verify_config_toml(args.config)
 p_dir = args.profiles or (args.config.parent / "profiles")
 c_files = [cf for t in args.targets for cf in (sorted(t.glob("*.toml")) if t.is_dir() else [t])]
 evs, gone, inc, ev_errs, sec_recs, exp_snap = load_proof_events(args.events)
 m_man, lat_m, m_errs = None, {}, []
 if args.mutants and args.mutation_events:
  try:
   m_man = validate_mutation_manifest(args.mutants.read_text(encoding="utf-8"))
   lat_m, m_errs = load_mutation_events(args.mutation_events, m_man)
  except Exception as exc: m_errs.append(str(exc))
 s_art = args.subject_artifact or (("sha256:" + hashlib.sha256(args.subject.read_bytes()).hexdigest()) if args.subject else "")
 exp_sub = {"artifact_ref": s_art, "source_tree": args.subject_tree, "run_id": args.run_id}
 perf_b = load_measurement_bundle(args.measurements, _decode_no_dup_keys, digest_matches)
 by_c = {}
 for ev in evs: by_c.setdefault(ev["contract"], []).append(ev)
 parsed = [verify_contract_toml(cf, p_dir) for cf in c_files]
 tot_open = sum(c.get("open_cnt", 0) for c in parsed)
 verdicts = apply_openssh_trust_verdicts([evaluate_contract(c, cfg_st, by_c.get(c["id"], []), gone.get(c["id"], 0), inc, ev_errs, pol, args.min_proof, args.phase, tot_open, evaluate_contract_mutations(c, m_man, lat_m, m_errs), perf_b, exp_sub, sec_recs, exp_snap) for c in parsed], args)
 ok = bool(verdicts) and all(v["ok"] for v in verdicts)
 if args.json: print(json.dumps({"ok": ok, "contracts": verdicts}, indent=2, sort_keys=True))
 else:
  for v in verdicts: print(f"{v['id']} {v['ref']}: {'green' if v['ok'] else 'not green (' + ', '.join(v['reasons']) + ')'}")
 return 0 if ok else 1


if __name__ == "__main__":
 sys.exit(main(sys.argv[1:]))
