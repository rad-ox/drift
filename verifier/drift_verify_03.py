#!/usr/bin/env python3
"""Schema 0.3 typed IR, dr2b/dr2a/dr2r digest, and capability helper for verifier/drift_verify.py."""

from __future__ import annotations
import hashlib
import re
import tomllib
from decimal import Decimal as D
from pathlib import Path
from typing import Any, Callable
from drift_verify_grant import tok_str_03 as _tok_str_03, unesc_lit_03 as _unesc_lit_03

_RES03_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

def _norm_num_03(v: Any, typ: str) -> Any:
 if isinstance(v, bool): return v
 if typ == "num" and isinstance(v, (int, float)): return 0.0 if float(v) == 0.0 else float(v)
 if typ == "int" and isinstance(v, (int, float)) and float(v).is_integer(): return int(v)
 return 0.0 if isinstance(v, float) and v == 0.0 else v

def _canon_ptr_03(s: str) -> str:
 st = 1 if s.startswith("/") else 0; col = s.find(":/", st)
 return f"{s[st:col]}:{s[col + 1:]}" if col > st and _RES03_RE.match(s[st:col]) else s

def _canon_pred_03(sp: dict[str, Any]) -> dict[str, Any]:
 typ = str(sp.get("type", "")); m: dict[str, Any] = {"type": typ}
 for bk in ("min", "max"):
  if bk in sp: m[bk] = int(sp[bk]) if typ == "int" else float(sp[bk])
 if isinstance(sp.get("len"), dict) and (lm := {k: int(sp["len"][k]) for k in ("min", "max") if k in sp["len"]}): m["len"] = lm
 for k in ("enum", "unit", "role", "transient", "compensating"):
  if sp.get(k): m[k] = sp[k]
 if sp.get("ptr"): m["ptr"] = _canon_ptr_03(str(sp["ptr"]))
 return m

def _merge_pred_03(b: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
 out = {**b, "type": c.get("type", b.get("type", ""))}
 if "min" in b or "min" in c: out["min"] = max(b["min"], c["min"]) if ("min" in b and "min" in c) else c.get("min", b.get("min"))
 if "max" in b or "max" in c: out["max"] = min(b["max"], c["max"]) if ("max" in b and "max" in c) else c.get("max", b.get("max"))
 bl, cl = b.get("len") or {}, c.get("len") or {}; lm = {}
 if "min" in bl or "min" in cl: lm["min"] = max(bl["min"], cl["min"]) if ("min" in bl and "min" in cl) else cl.get("min", bl.get("min"))
 if "max" in bl or "max" in cl: lm["max"] = min(bl["max"], cl["max"]) if ("max" in bl and "max" in cl) else cl.get("max", bl.get("max"))
 if lm: out["len"] = lm
 for k in ("enum", "unit", "role", "transient", "compensating", "ptr"):
  if c.get(k): out[k] = c[k]
 return out


def _norm_expr_03(raw, pred, side, units, params):
 p_typ, p_unit = (str(pred.get("type", "")), str(pred.get("unit", ""))) if isinstance(pred, dict) else ("", "")
 if not isinstance(raw, dict):
  lit = _tok_str_03(raw, params, True) if isinstance(raw, str) else (_unesc_lit_03(raw) if isinstance(raw, list) else raw)
  return {"eq": _norm_num_03(lit, p_typ)}, [], set()
 norm, prefs, caps, conv = {}, [], set(), 1.0
 if "convert_from" in raw:
  cf = str(raw["convert_from"]); conv = float(units.get(f"{cf}->{p_unit}", 1.0)); norm["convert_from"] = cf; caps.add("unit-conversion/1")
 res_p = lambda v, wi=False: (int(rv) if wi else float(rv)) if isinstance(rv := (_tok_str_03(v, params, True) if isinstance(v, str) else v), (int, float)) and not isinstance(rv, bool) else rv
 if isinstance(raw.get("tol"), dict):
  caps.add("rel-tol/1"); norm["tol"] = {tk: float(res_p(tv)) for tk, tv in raw["tol"].items() if tk in ("abs", "rel")}
 if "eq" in raw:
  norm["eq"] = _norm_num_03(_tok_str_03(raw["eq"], params, True) if isinstance(raw["eq"], str) else _unesc_lit_03(raw["eq"]), p_typ)
 wi = bool(pred and p_typ == "int" and conv == 1.0)
 for bk in ("min", "max"):
  if bk in raw: norm[bk] = res_p(raw[bk], wi)
 if isinstance(raw.get("len"), dict): norm["len"] = {lk: int(res_p(lv, True)) for lk, lv in raw["len"].items() if lk in ("min", "max")}
 for aff in ("prefix", "suffix"):
  if aff in raw: norm[aff] = str(raw[aff])
 for sk in ("in", "not_in"):
  if isinstance(raw.get(sk), list): norm[sk] = [_norm_num_03(_unesc_lit_03(it), p_typ) for it in raw[sk]]
 if isinstance(raw.get("contains"), list): norm["contains"] = _unesc_lit_03(raw["contains"])
 if isinstance(raw.get("keys"), dict):
  caps.add("rel-keys-guard/1"); norm["keys"] = {kk: [str(x) for x in kv] for kk, kv in raw["keys"].items() if kk in ("allow", "forbid") and isinstance(kv, list)}
 if isinstance(raw.get("peer"), dict):
  qual = lambda r: r.strip() if r.strip().startswith(("when.", "then.")) else f"{side}.{r.strip()}"
  np: dict[str, Any] = {}
  for pk in ("le", "ge", "eq"):
   if pk in raw["peer"]: q = qual(str(raw["peer"][pk])); prefs.append(q); np[pk] = q
  if isinstance(raw["peer"].get("sum"), list):
   caps.add("rel-peer-sum/1"); qs = [qual(str(x)) for x in raw["peer"]["sum"]]; prefs.extend(qs); np["sum"] = qs
  if isinstance(raw["peer"].get("balance"), dict):
   caps.add("rel-linear-balance/1"); nb = {}
   for bk in ("add", "sub"):
    if isinstance(raw["peer"]["balance"].get(bk), list): qs = [qual(str(x)) for x in raw["peer"]["balance"][bk]]; prefs.extend(qs); nb[bk] = qs
   np["balance"] = nb
  norm["peer"] = np
 if isinstance(raw.get("series"), dict):
  caps.add("rel-series/1")
  norm["series"] = {sk: (str(sv) if sk == "monotonic" else float(res_p(sv))) for sk, sv in raw["series"].items() if sk in ("monotonic", "sum_total", "step_max_delta")}
 return norm, prefs, caps


_P03_CACHE: dict[Any, Any] = {}
def _read_p03(pf: Path) -> dict[str, Any]:
 st = pf.stat(); k = (str(pf), st.st_mtime_ns, st.st_size)
 if k not in _P03_CACHE: _P03_CACHE[k] = tomllib.loads(pf.read_text("utf-8"))
 return _P03_CACHE[k]

def verify_contract_03_toml(raw, path, profiles_dir, canon_fn, ref_fn, proof_rank_fn, resolve_roots_fn, has_blocker_fn, is_prose_fn, contains_todo_fn):
 cid, appr, _ = str(raw.get("id", path.stem)), raw.pop("approval", None), raw.pop("note", None)
 raw_sc, raw_bind, use_tbl = (raw.get(k) if isinstance(raw.get(k), dict) else {} for k in ("scope", "bind", "use"))
 sc_code = [str(x) for x in raw_bind.get("code", []) if isinstance(x, str)] if isinstance(raw_bind.get("code"), list) else []
 sc_reads, sc_writes = ([str(x) for x in raw_sc.get(k, []) if isinstance(x, str)] if isinstance(raw_sc.get(k), list) else [] for k in ("reads", "writes"))
 prof_ref = str(use_tbl.get("profile", ""))
 use_params = {**(use_tbl["params"] if isinstance(use_tbl.get("params"), dict) else {}), **{k: v for k, v in use_tbl.items() if k not in ("profile", "concepts", "waive", "params")}}
 waived = use_tbl.get("waive") if isinstance(use_tbl.get("waive"), dict) else {}
 units, w_sch, t_sch, m_inv, m_cases, m_decs, m_risks, m_ctrls, p_proof, p_sec, p_sim, has_g, g_max, g_forb = {}, {}, {}, {}, {}, {}, {}, {}, "", [], False, False, 0, []
 p0 = profiles_dir / f"{prof_ref}.toml" if prof_ref else None
 if p0 and p0.is_file():
  prof_doc = _read_p03(p0)
  exts = [str(x) for x in (prof_doc.get("extends") or []) if isinstance(x, str)] if isinstance(prof_doc.get("extends"), list) else []
  for r in [*exts, prof_ref]:
   bp = prof_doc if r == prof_ref else (_read_p03(pf) if (pf := profiles_dir / f"{r}.toml").is_file() else {})
   units.update({str(uk): float(uv) for uk, uv in (bp.get("units") or {}).items() if isinstance(uv, (int, float)) and not isinstance(uv, bool)})
   sm = bp.get("schema") if isinstance(bp.get("schema"), dict) else {}
   for wk, wp in (sm.get("when") or {}).items():
    if isinstance(wp, dict): w_sch[wk] = _merge_pred_03(w_sch[wk], wp) if wk in w_sch else dict(wp)
   for tk, tp in (sm.get("then") or {}).items():
    if isinstance(tp, dict): t_sch[tk] = _merge_pred_03(t_sch[tk], tp) if tk in t_sch else dict(tp)
   for ik, iv in (bp.get("invariants") or {}).items():
    ne, _, _ = _norm_expr_03(iv, t_sch.get(ik), "then", units, {})
    m_inv[ik] = {**m_inv[ik], **ne} if ik in m_inv else ne
   for bcid, bcm in (bp.get("cases") or {}).items():
    if isinstance(bcm, dict): tc = dict(bcm); tc["from"] = r if r == prof_ref or "from" not in tc else tc["from"]; m_cases[bcid] = tc
   for bdid, bdm in (bp.get("decisions") or {}).items():
    if isinstance(bdm, dict): td = dict(bdm); td["from"] = r if r == prof_ref or "from" not in td else td["from"]; m_decs[bdid] = td
   b_ass = bp.get("assurance") if isinstance(bp.get("assurance"), dict) else {}
   m_risks.update(b_ass.get("risks") or {}); m_ctrls.update(b_ass.get("controls") or {})
   req = bp.get("requires") if isinstance(bp.get("requires"), dict) else {}
   if req.get("proof") and proof_rank_fn(str(req["proof"])) > proof_rank_fn(p_proof): p_proof = str(req["proof"])
   for sc in (req.get("security") or ()):
    if str(sc) not in p_sec: p_sec.append(str(sc))
   if req.get("simulation") == "required": p_sim = True
   if isinstance(rg := req.get("guards"), dict):
    has_g = True
    if isinstance(rg.get("max_lines"), int) and rg["max_lines"] > 0: g_max = rg["max_lines"] if g_max == 0 or rg["max_lines"] < g_max else g_max
    for fi in (rg.get("forbid_imports") or ()):
     if str(fi) not in g_forb: g_forb.append(str(fi))
 norm_inv, p_deps, all_caps = {}, {}, set()
 for ik, iv in m_inv.items():
  ne, pr, cp = _norm_expr_03(iv, t_sch.get(ik), "then", units, use_params)
  norm_inv[ik] = ne
  p_deps.setdefault(f"then.{ik}", []).extend(pr)
  all_caps.update(cp)
 for ik, iv in (raw.get("invariants") or {}).items():
  ne, pr, cp = _norm_expr_03(iv, t_sch.get(ik), "then", units, use_params)
  norm_inv[ik] = {**norm_inv[ik], **ne} if ik in norm_inv else ne
  p_deps[f"then.{ik}"] = list(pr)
  all_caps.update(cp)
 norm_cases: dict[str, dict[str, Any]] = {}
 for src_c in ({k: v for k, v in m_cases.items() if k not in waived}, raw.get("cases") or {}):
  for case_id, cm in src_c.items():
   if not isinstance(cm, dict):
    continue
   nc = dict(cm)
   if isinstance(cm.get("when"), dict):
    nw = {}
    for wk, wv in cm["when"].items():
     ne, pr, cp = _norm_expr_03(wv, w_sch.get(wk), "when", units, use_params)
     nw[wk] = ne
     p_deps.setdefault(f"when.{wk}", []).extend(pr)
     all_caps.update(cp)
    nc["when"] = nw
   if isinstance(cm.get("then"), dict):
    nt = {}
    for tk, tv in cm["then"].items():
     ne, pr, cp = _norm_expr_03(tv, t_sch.get(tk), "then", units, use_params)
     nt[tk] = {**norm_inv[tk], **ne} if tk in norm_inv else ne
     p_deps.setdefault(f"then.{tk}", []).extend(pr)
     all_caps.update(cp)
    for ik, iv in norm_inv.items():
     nt.setdefault(ik, iv)
    nc["then"] = nt
   norm_cases[case_id] = nc
 need_w, need_t, q = set(), set(norm_inv), [f"then.{ik}" for ik in norm_inv]
 for cm in norm_cases.values():
  if "status" in cm:
   continue
  for wk in (cm.get("when") or ()):
   if wk not in need_w:
    need_w.add(wk)
    q.append(f"when.{wk}")
  for tk in (cm.get("then") or ()):
   if tk not in need_t:
    need_t.add(tk)
    q.append(f"then.{tk}")
 while q:
  for dep in p_deps.get(q.pop(), ()):
   if dep.startswith("when.") and dep[5:] not in need_w:
    need_w.add(dep[5:])
    q.append(dep)
   elif dep.startswith("then.") and dep[5:] not in need_t:
    need_t.add(dep[5:])
    q.append(dep)
 sch_w = {wk: _canon_pred_03(w_sch[wk]) for wk in need_w if wk in w_sch}
 sch_t = {tk: _canon_pred_03(t_sch[tk]) for tk in need_t if tk in t_sch}
 need_u = {str(s.get("unit", "")) for s in (*(w_sch[w] for w in need_w if w in w_sch), *(t_sch[t] for t in need_t if t in t_sch)) if s.get("unit")}
 act_u = {uk: uv for uk, uv in units.items() if len(pts := uk.split("->")) == 2 and (pts[0] in need_u or pts[1] in need_u)}
 prof_clos: dict[str, Any] = {}
 if sch_w or sch_t:
  prof_clos["schema"] = {**({"when": sch_w} if sch_w else {}), **({"then": sch_t} if sch_t else {})}
 if act_u:
  prof_clos["units"] = act_u
 if use_params:
  prof_clos["params"] = use_params
 beh_cases = {k: {ck: cv for ck, cv in cm.items() if ck not in ("note", "scenario")} for k, cm in norm_cases.items()}
 loc_decs: dict[str, Any] = {}
 for did, dm in {**m_decs, **(raw.get("decisions") if isinstance(raw.get("decisions"), dict) else {})}.items():
  if isinstance(dm, dict):
   td = {k: v for k, v in dm.items() if k not in ("owner", "note")}
   if td.get("evidence") == "observed" and is_prose_fn(str(td.get("source", ""))): td.pop("source", None)
   pk, opts = str(td.get("pick", "")), td.get("options") if isinstance(td.get("options"), dict) else {}
   if pk and len(opts) > 1 and pk in opts: td["options"] = {pk: opts[pk]}
   loc_decs[did] = td
 clean_open = {oid: {k: v for k, v in om.items() if k != "owner"} for oid, om in (raw.get("open") or {}).items() if isinstance(om, dict)} if isinstance(raw.get("open"), dict) else {}
 beh_c: dict[str, Any] = {"drift": "0.3", "id": cid, "intent": raw.get("intent", ""), "scope": raw.get("scope"), "cases": beh_cases}
 if norm_inv: beh_c["invariants"] = norm_inv
 if waived: beh_c["waived"] = sorted(waived)
 if loc_decs: beh_c["decisions"] = loc_decs
 if clean_open: beh_c["open"] = clean_open
 d2_fn = lambda pfx, tag, obj: pfx + hashlib.sha256(tag.encode("utf-8") + b"\x00" + canon_fn(obj).encode("utf-8")).hexdigest()
 beh_dig = d2_fn("dr2b:sha256:", "drift.behavior/2", {"contract": beh_c, "profile": prof_clos})
 raw_ass = raw.get("assurance") if isinstance(raw.get("assurance"), dict) else {}
 assur = {**raw_ass, **({"risks": {**m_risks, **(raw_ass.get("risks") or {})}} if (m_risks or raw_ass.get("risks")) else {}), **({"controls": {**m_ctrls, **(raw_ass.get("controls") or {})}} if (m_ctrls or raw_ass.get("controls")) else {})}
 need_cd = {*(str(c) for tk in ("formal", "controls") if isinstance(assur.get(tk), dict) for m in assur[tk].values() if isinstance(m, dict) for c in (m.get("cases") or ())), *(str(m.get("case", "")) for m in (assur.get("budgets") or {}).values() if isinstance(assur.get("budgets"), dict) and isinstance(m, dict))}
 exp_peers = lambda ex: [*(ex["peer"].get(k) for k in ("le", "ge", "eq") if isinstance(ex["peer"].get(k), str) and ex["peer"].get(k)), *(ex["peer"].get("sum") or ()), *((ex["peer"].get("balance") or {}).get("add") or ()), *((ex["peer"].get("balance") or {}).get("sub") or ())] if isinstance(ex, dict) and isinstance(ex.get("peer"), dict) else []
 case_digs: dict[str, str] = {}
 for k in need_cd:
  if k not in beh_cases: continue
  cl_c, ss = beh_cases[k], {}
  for wk, wv in (cl_c.get("when") or {}).items():
   if wk in w_sch: ss[f"when.{wk}"] = _canon_pred_03(w_sch[wk])
   for pr in exp_peers(wv):
    if pr.startswith("when.") and pr[5:] in w_sch: ss[pr] = _canon_pred_03(w_sch[pr[5:]])
  for tk, tv in (cl_c.get("then") or {}).items():
   if tk in t_sch: ss[f"then.{tk}"] = _canon_pred_03(t_sch[tk])
   for pr in exp_peers(tv):
    if pr.startswith("when.") and pr[5:] in w_sch: ss[pr] = _canon_pred_03(w_sch[pr[5:]])
    elif pr.startswith("then.") and pr[5:] in t_sch: ss[pr] = _canon_pred_03(t_sch[pr[5:]])
  case_digs[k] = d2_fn("dr2b:sha256:", "drift.case-behavior/2", {"contract": cid, "case_id": k, "case": cl_c, "schema": ss, "units": dict(units)})
 dig_assur, res_budgets, res_formal, res_cutover, res_risks, res_ctrls, f_rrefs = {}, {}, {}, {}, {}, {}, {}
 if "guards" in assur or has_g:
  gm = assur.get("guards") if isinstance(assur.get("guards"), dict) else {}
  ml = gm.get("max_lines", g_max)
  fb = sorted(set(g_forb) | {str(x) for x in (gm.get("forbid_imports") or ()) if isinstance(x, str)})
  tgts = sorted({str(x) for x in (gm.get("target") or ()) if isinstance(x, str)})
  dig_assur["guards"] = {"target": tgts, **({"max_lines": ml} if isinstance(ml, int) and ml > 0 else {}), **({"forbid_imports": fb} if fb else {})}
 if isinstance(assur.get("formal"), dict):
  df = {}
  for fid, fm in assur["formal"].items():
   if not isinstance(fm, dict):
    continue
   cl = {k: v for k, v in fm.items() if k not in ("note", "requirement_ref")}
   cl.setdefault("property_kind", "safety")
   tc = {str(c): case_digs.get(str(c), "") for c in (cl.get("cases") or ())}
   rr = d2_fn("dr2r:sha256:", "drift.requirement/2", {"contract": cid, "kind": "formal", "id": fid, "entry": cl, "target_cases": tc})
   f_rrefs[fid] = rr
   df[fid] = cl
   res_formal[fid] = {**cl, "enforce": cl.get("enforce", "execution"), "requirement_ref": rr}
  dig_assur["formal"] = df
 if isinstance(assur.get("budgets"), dict):
  db = {}
  for bid, bm in assur["budgets"].items():
   if not isinstance(bm, dict):
    continue
   cl = {k: v for k, v in bm.items() if k not in ("note", "warn_ratio", "requirement_ref")}
   rr = d2_fn("dr2r:sha256:", "drift.requirement/2", {"contract": cid, "kind": "budget", "id": bid, "entry": cl, "target_case": case_digs.get(str(cl.get("case", "")), "")})
   db[bid] = cl
   res_budgets[bid] = {**cl, **({"warn_ratio": bm["warn_ratio"]} if "warn_ratio" in bm else {}), "requirement_ref": rr}
  dig_assur["budgets"] = db
 if isinstance(assur.get("cutover"), dict) and assur["cutover"]:
  cm = assur["cutover"]
  cl = {k: v for k, v in cm.items() if k not in ("note", "requirement_ref")}
  rr = d2_fn("dr2r:sha256:", "drift.requirement/2", {"contract": cid, "kind": "cutover", "entry": cl})
  dig_assur["cutover"] = cl
  res_cutover = {**cl, "rollback_readback": cl.get("rollback_readback", "required" if sc_writes else "not_applicable"), "enforce": cl.get("enforce", "release"), "requirement_ref": rr}
 if isinstance(assur.get("risks"), dict):
  res_risks = {k: dict(v) for k, v in assur["risks"].items() if isinstance(v, dict)}
  dig_assur["risks"] = {k: {rk: rv for rk, rv in v.items() if rk != "note"} for k, v in res_risks.items()}
 if isinstance(assur.get("controls"), dict):
  dc = {}
  for ctrl_id, cm in assur["controls"].items():
   if not isinstance(cm, dict):
    continue
   cl = {k: v for k, v in cm.items() if k not in ("note", "requirement_ref")}
   cl.setdefault("enforce", "release")
   tc = {str(c): case_digs.get(str(c), "") for c in (cl.get("cases") or ())}
   lnk = {str(t): f_rrefs.get(str(t)[7:], "") for t in (cl.get("implementation_evidence") or ()) if str(t).startswith("formal:")}
   rr = d2_fn("dr2r:sha256:", "drift.requirement/2", {"contract": cid, "kind": "control", "id": ctrl_id, "entry": cl, "target_cases": tc, "linked_obligations": lnk})
   dc[ctrl_id] = cl
   res_ctrls[ctrl_id] = {**cl, "requirement_ref": rr}
  dig_assur["controls"] = dc
 req_pos = {**({"proof": p_proof} if p_proof else {}), **({"security": sorted(p_sec)} if p_sec else {}), **({"simulation": "required"} if p_sim else {})}
 assur_dig = d2_fn("dr2a:sha256:", "drift.assurance/2", {"contract": cid, "requires": req_pos, "assurance": dig_assur})
 d_match = lambda r, fd: isinstance(r, str) and bool(re.fullmatch(rf"{fd[:5]}(?:sha256:[0-9a-f]{{64}}|[0-9a-f]{{12}})", r)) and (r == fd or r == ref_fn(fd))
 has_blk = has_blocker_fn({**raw, "budgets": assur.get("budgets"), "formal": assur.get("formal"), "cutover": assur.get("cutover")}, {"decisions": m_decs}) or contains_todo_fn(raw.get("bind")) or contains_todo_fn(raw.get("invariants")) or contains_todo_fn(assur)
 has_any_ref = isinstance(appr, dict) and any(appr.get(k) for k in ("behavior_ref", "assurance_ref", "ref", "digest"))
 cur_ok = isinstance(appr, dict) and set(appr) <= {"behavior_ref", "assurance_ref", "by", "at"} and d_match(appr.get("behavior_ref"), beh_dig) and d_match(appr.get("assurance_ref"), assur_dig)
 st = "blocked" if has_blk else ("current" if cur_ok else ("stale" if has_any_ref else "absent"))
 open_m = raw.get("open") if isinstance(raw.get("open"), dict) else {}
 own_d = [d for d in (raw.get("decisions") or {}).values() if isinstance(d, dict)] if isinstance(raw.get("decisions"), dict) else []
 decs = [d for s in (raw.get("decisions"), m_decs) if isinstance(s, dict) for d in s.values() if isinstance(d, dict)]
 blk = lambda ph: any(isinstance(q, dict) and q.get("blocks") == ph for q in open_m.values()) or any(d.get("pick", "") == "" and d.get("decide_by") == ph for d in decs)
 roots = resolve_roots_fn(path)
 return {"drift": "0.3", "id": cid, "digest": beh_dig, "ref": ref_fn(beh_dig), "assurance_digest": assur_dig, "assurance_ref": ref_fn(assur_dig), "approval": st, "approver": str(appr.get("by", "")) if isinstance(appr, dict) and cur_ok else (str(appr.get("by", "")) if has_any_ref else ""), "profile_proof": p_proof, "profile_security": p_sec, "profile_simulation": p_sim, "scope_code": sc_code, "scope_reads": sc_reads, "scope_writes": sc_writes, "invariants": sorted(norm_inv), "cases": beh_cases, "budgets": res_budgets, "formal": res_formal, "cutover": res_cutover, "risks": res_risks, "controls": res_ctrls, "required_capabilities": sorted(all_caps), "obs": {"proj": {k: re.sub(r"^/?[\w.-]+:(?=/)", "", p["ptr"]) for k, p in t_sch.items() if p.get("ptr")}, "units": units, "unit": {k: p["unit"] for k, p in t_sch.items() if p.get("unit")}, "w": sc_writes}, "area_root": roots["source_root"], "shadow_area_root": roots["area_root"], "open_cnt": len(open_m) + sum(1 for d in own_d if d.get("pick", "") == ""), "exec_blk": blk("execution"), "rel_blk": blk("release") or any(isinstance(c, dict) and c.get("status") == "deferred" for c in beh_cases.values())}


_OPS = {"eq", "min", "max", "in", "not_in", "len", "prefix", "suffix", "keys", "peer", "tol", "convert_from"}
_ABS = object()
_d = lambda x: D(repr(x)) if isinstance(x, float) else D(x)
_nm = lambda x: isinstance(x, (int, float, D)) and not isinstance(x, bool)


def _ob(v):
 if isinstance(v, list):
  return [_ob(x) for x in v]
 if not isinstance(v, dict):
  return v
 if "$t" in v:
  t, x = v["$t"], v.get("v")
  if t in ("absent", "null"):
   return _ABS if t == "absent" else None
  if t in ("i64", "u64"):
   n = int(x) if isinstance(x, (int, str)) and not isinstance(x, bool) else int("x")
   if not (-2**63 if t == "i64" else 0) <= n < (2**63 if t == "i64" else 2**64):
    raise ValueError(t)
   return n
  if t == "dec" and isinstance(x, str) and re.fullmatch(r"[+-]?(?=\.?\d)\d*\.?\d*", x.strip()):
   return D(x.strip())
  if t in ("f32", "f64"):
   return float(x)
  if t == "bytes":
   return bytes.fromhex(x)
  raise ValueError(t)
 o = {}
 for k, x in v.items():
  if k.startswith("$") and not k.startswith("$$") or k.lstrip("$") in o and k.startswith("$$"):
   raise ValueError(k)
  o[k[1:] if k.startswith("$$") else k] = _ob(x)
 return o


def _env(e):
 if not isinstance(e, dict) or e.get("schema") != "drift.observation/1" or e.get("outcome", "returned") not in ("returned", "thrown", "timeout", "interrupted"):
  raise ValueError("observation")
 return e.get("outcome", "returned"), _ob(e["payload"]) if "payload" in e else _ABS, e.get("presence", {}), e.get("frame", {})


def obs03(d, cs, sch):
 if "observations" not in d: return {}
 if sch != "0.3" or not isinstance(d["observations"], dict) or any(k not in cs for k in d["observations"]): raise ValueError("observations")
 return {"observations": d["observations"], "_obs_dec": {k: _env(e) for k, e in d["observations"].items()}}


def _cmp(a, b, cv=D(1)):
 a, b = _d(a), _d(b) * cv
 return None if a.is_nan() or b.is_nan() or not (_nm(a) and _nm(b)) else (a > b) - (a < b)


def _eq(o, l, cv=D(1), tol=(0, 0)):
 if l is None or isinstance(l, bool):
  return o is l
 if isinstance(l, str):
  return o == l if not isinstance(o, D) else (re.fullmatch(r"[+-]?\d+\.?\d*", l) is not None and D(l) == o)
 if _nm(l):
  return _nm(o) and abs(_d(o) - _d(l) * cv) <= tol[0] + tol[1] * abs(_d(l) * cv)
 if isinstance(l, list):
  return isinstance(o, list) and len(o) == len(l) and all(map(_eq, o, l))
 return isinstance(l, dict) and isinstance(o, dict) and o.keys() == l.keys() and all(_eq(o[k], x) for k, x in l.items())


def _fk(o, fs):
 return (isinstance(o, dict) and any(k in fs and v is not _ABS or _fk(v, fs) for k, v in o.items())) or (isinstance(o, list) and any(_fk(x, fs) for x in o))


def _peer(pm, o, g):
 vs = [g(r) for r in [*(pm.get("sum") or []), *[pm[k] for k in ("le", "ge", "eq") if k in pm]]]
 if not all(map(_nm, [o, *vs])):
  return "eq" in pm and len(pm) == 1 and o == g(pm["eq"])
 return not any(k in pm and ((c := _cmp(o, g(pm[k]))) is None or c * s > 0) for k, s in (("le", 1), ("ge", -1))) and ("eq" not in pm or _cmp(o, g(pm["eq"])) == 0) and ("sum" not in pm or _d(o) == sum(_d(g(r)) for r in pm["sum"]))


def _cl(n, o, p, pres, un, pu, g):
 m, k, ki, pm = pres.get(p, pres.get("*", "exact")), n.get("keys"), n.get("in"), n.get("peer")
 if any(x not in _OPS for x in n) or m == "unobservable" or (o is _ABS and m != "exact") or (isinstance(pm, dict) and (any(x not in ("le", "ge", "eq", "sum") for x in pm) or "tol" in n)):
  return "inconclusive"
 if o is _ABS or (_nm(o) and _d(o).is_nan()):
  return "violated"
 cv = _d(un.get(f"{n['convert_from']}->{pu}", 1)) if n.get("convert_from") and pu else D(1)
 t = n.get("tol")
 tol = (_d(t.get("abs", 0)) * cv, _d(t.get("rel", 0))) if isinstance(t, dict) else (0, 0)
 if "eq" in n and (n["eq"] is None or o is None) and m != "exact":
  return "inconclusive"
 for x in (o if isinstance(o, list) else [o]) if "min" in n or "max" in n else ():
  if not (isinstance(o, list) and not _nm(x)) and any(b in n and ((c := _cmp(x, n[b], cv)) is None or c * s > 0) for b, s in (("min", -1), ("max", 1))):
   return "violated"
 if ("eq" in n and not _eq(o, n["eq"], cv, tol)) or ("in" in n and not (isinstance(ki, list) and any(_eq(o, x, cv) for x in ki))) or ("not_in" in n and (not isinstance(n["not_in"], list) or any(_eq(o, x, cv) for x in n["not_in"]))):
  return "violated"
 if (isinstance(n.get("len"), dict) and (not isinstance(o, (str, bytes, list, dict)) or len(o) < n["len"].get("min", 0) or len(o) > n["len"].get("max", len(o)))) or ("prefix" in n and not (isinstance(o, str) and o.startswith(n["prefix"]))) or ("suffix" in n and not (isinstance(o, str) and o.endswith(n["suffix"]))):
  return "violated"
 if (isinstance(k, dict) and (not isinstance(o, dict) or ("allow" in k and m == "exact" and any(x not in k["allow"] and v is not _ABS for x, v in o.items())) or ("forbid" in k and _fk(o, k["forbid"])))) or (isinstance(pm, dict) and not _peer(pm, o, g)):
  return "violated"
 return "inconclusive" if isinstance(k, dict) and m != "exact" else "passed"


def _judge(c, cid, e, dec=None):
 out, pay, pres, fr = dec if dec is not None else _env(e)
 cm, cx = c["cases"][cid], c["obs"]
 ws, ps = fr.get("writes") or [], cm["writes"] if isinstance(cm.get("writes"), list) else cx["w"]
 if not isinstance(ws, list) or not all(isinstance(w, str) for w in ws):
  return "inconclusive"
 if out != "returned" or any(not (w in ps or w.split("#")[0] in ps or "#" not in w and any(x.split("#")[0] == w for x in ps)) for w in ws):
  return "violated"
 ptr = lambda k: cx["proj"].get(k, "/" + k.replace("~", "~0").replace("/", "~1"))
 def at(k):
  v = pay
  for s in ptr(k)[1:].split("/") if ptr(k) else ():
   s = s.replace("~1", "/").replace("~0", "~")
   v = v[s] if isinstance(v, dict) and s in v else (v[int(s)] if isinstance(v, list) and s.isdigit() and str(int(s)) == s and int(s) < len(v) else _ABS)
  return v
 th = cm.get("then") or {}
 peers = {}
 if any(isinstance(n, dict) and "peer" in n for n in th.values()):
  peers = {f"when.{k}": _ob(x["eq"]) for k, x in (cm.get("when") or {}).items() if list(x) == ["eq"]}
  for k in {*th, *cx["proj"]}: peers[f"then.{k}"] = peers[k] = at(k)
 rs = {_cl(n, at(k), ptr(k), pres, cx["units"], cx["unit"].get(k, ""), lambda r: peers.get(r, _ABS)) for k, n in th.items()}
 return "violated" if "violated" in rs else ("inconclusive" if "inconclusive" in rs else "passed")


def red03(c, ev):
 try:
  dec_m = ev.get("_obs_dec") or {}
  ev["red"] = {k for k, e in (ev.get("observations") or {}).items() if ev["outcome"] == "passed" and ("obs" not in c or _judge(c, k, e, dec_m.get(k)) != "passed")}
 except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
  ev["red"] = set(ev["cases"])
 return ev
