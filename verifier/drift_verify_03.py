#!/usr/bin/env python3
"""Schema 0.3 typed IR, dr2b/dr2a/dr2r digest, and capability helper for verifier/drift_verify.py."""

from __future__ import annotations
import hashlib
import re
import tomllib
from pathlib import Path
from typing import Any, Callable
from drift_verify_base import (
    BUDGET_METRICS,
    _budget_metrics_closure_ok,
    _canon_pred_03,
    _canon_ptr_03,
    _contains_todo,
    _has_approval_blocker,
    _is_unanchored_prose_source,
    _merge_pred_03,
    _norm_num_03,
    tok_str_03 as _tok_str_03,
    unesc_lit_03 as _unesc_lit_03,
)
from drift_verify_obs import obs03, red03


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
 if isinstance(raw.get("contains"), (list, str)): norm["contains"] = _unesc_lit_03(raw["contains"])
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
_PROF_MERGED_03_CACHE: dict[Any, Any] = {}
_OBS_PTR_RE = re.compile(r"^/?[\w.-]+:(?=/)")

def _read_p03_stat(pf: Path) -> tuple[tuple[int, int] | None, dict[str, Any]]:
 try: st = pf.stat()
 except OSError: return None, {}
 k = (str(pf), st.st_mtime_ns, st.st_size)
 if k not in _P03_CACHE: _P03_CACHE[k] = tomllib.loads(pf.read_text("utf-8"))
 return (st.st_mtime_ns, st.st_size), _P03_CACHE[k]

def _empty_prof_03(missing: str = "") -> tuple[Any, ...]:
 return {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, "", [], False, False, [], False, False, 0, [], [], [], {}, {}, ({}, {}, set()), missing

def _merged_profile_03(profiles_dir: Path, prof_ref: str, proof_rank_fn: Callable[[str], int]) -> tuple[Any, ...]:
 if not prof_ref:
  return _empty_prof_03()
 st0, prof_doc = _read_p03_stat(profiles_dir / f"{prof_ref}.toml")
 if st0 is None:
  return _empty_prof_03(prof_ref)
 exts = [str(x) for x in (prof_doc.get("extends") or []) if isinstance(x, str)] if isinstance(prof_doc.get("extends"), list) else []
 chain_docs: list[tuple[str, dict[str, Any]]] = []
 chain_stats: list[tuple[str, int | None, int | None]] = []
 ext_miss = ""
 for r in exts:
  st_r, doc_r = _read_p03_stat(profiles_dir / f"{r}.toml")
  if st_r is None and not ext_miss: ext_miss = r
  chain_docs.append((r, doc_r))
  chain_stats.append((r, st_r[0] if st_r else None, st_r[1] if st_r else None))
 chain_docs.append((prof_ref, prof_doc))
 chain_stats.append((prof_ref, st0[0], st0[1]))
 mkey = (str(profiles_dir), prof_ref, tuple(chain_stats))
 if mkey in _PROF_MERGED_03_CACHE:
  return _PROF_MERGED_03_CACHE[mkey]
 units, w_sch, t_sch, m_inv, m_cases, m_decs, m_risks, m_ctrls, p_proof, p_sec, p_sim, p_buds, p_bmetrics, p_bm_bad, has_g, g_max, g_forb, g_forb_t, g_cont = {}, {}, {}, {}, {}, {}, {}, {}, "", [], False, False, [], False, False, 0, [], [], []
 for r, bp in chain_docs:
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
  if req.get("budgets") == "required": p_buds = True
  elif req.get("budgets") == "optional" and (p_buds or p_bmetrics): p_bm_bad = True
  if "budget_metrics" in req:
   bms = req["budget_metrics"]
   if not isinstance(bms, list) or not bms or len(set(str(x) for x in bms)) != len(bms) or any(not isinstance(x, str) or x not in BUDGET_METRICS for x in bms) or any(m not in bms for m in p_bmetrics) or req.get("budgets") == "optional": p_bm_bad = True
   else:
    for m in bms:
     if m not in p_bmetrics: p_bmetrics.append(m)
    p_bmetrics.sort(); p_buds = True
  if isinstance(rg := req.get("guards"), dict):
   has_g = True
   if isinstance(rg.get("max_lines"), int) and rg["max_lines"] > 0: g_max = rg["max_lines"] if g_max == 0 or rg["max_lines"] < g_max else g_max
   for fi in (rg.get("forbid_imports") or ()):
    if str(fi) not in g_forb: g_forb.append(str(fi))
   for ft in (rg.get("forbid_touched") or ()):
    if str(ft) not in g_forb_t: g_forb_t.append(str(ft))
   for rc_m in (rg.get("require_containment") or ()):
    if str(rc_m) not in g_cont: g_cont.append(str(rc_m))
 sch_w_canon = {wk: _canon_pred_03(wp) for wk, wp in w_sch.items()}
 sch_t_canon = {tk: _canon_pred_03(tp) for tk, tp in t_sch.items()}
 obs_proj = {k: _OBS_PTR_RE.sub("", p["ptr"]) for k, p in t_sch.items() if p.get("ptr")}
 obs_unit = {k: p["unit"] for k, p in t_sch.items() if p.get("unit")}
 inv_0, deps_0, caps_0 = {}, {}, set()
 for ik, iv in m_inv.items():
  ne, pr, cp = _norm_expr_03(iv, t_sch.get(ik), "then", units, {})
  inv_0[ik] = ne; deps_0.setdefault(f"then.{ik}", []).extend(pr); caps_0.update(cp)
 merged = (units, w_sch, t_sch, sch_w_canon, sch_t_canon, m_inv, m_cases, m_decs, m_risks, m_ctrls, p_proof, p_sec, p_sim, p_buds, p_bmetrics, p_bm_bad, has_g, g_max, g_forb, g_forb_t, g_cont, obs_proj, obs_unit, (inv_0, deps_0, caps_0), ext_miss)
 _PROF_MERGED_03_CACHE[mkey] = merged
 return merged

def verify_contract_03_toml(raw, path, profiles_dir, canon_fn, ref_fn, proof_rank_fn, resolve_roots_fn, has_blocker_fn=_has_approval_blocker, is_prose_fn=_is_unanchored_prose_source, contains_todo_fn=_contains_todo):
 cid, appr, _ = str(raw.get("id", path.stem)), raw.pop("approval", None), raw.pop("note", None)
 raw_sc, raw_bind, use_tbl = (raw.get(k) if isinstance(raw.get(k), dict) else {} for k in ("scope", "bind", "use"))
 sc_code = [str(x) for x in raw_bind.get("code", []) if isinstance(x, str)] if isinstance(raw_bind.get("code"), list) else []
 sc_reads, sc_writes = ([str(x) for x in raw_sc.get(k, []) if isinstance(x, str)] if isinstance(raw_sc.get(k), list) else [] for k in ("reads", "writes"))
 prof_ref = str(use_tbl.get("profile", ""))
 use_params = {**(use_tbl["params"] if isinstance(use_tbl.get("params"), dict) else {}), **{k: v for k, v in use_tbl.items() if k not in ("profile", "concepts", "waive", "params")}}
 waived = use_tbl.get("waive") if isinstance(use_tbl.get("waive"), dict) else {}
 units, w_sch, t_sch, sch_w_canon, sch_t_canon, m_inv, m_cases, m_decs, m_risks, m_ctrls, p_proof, p_sec, p_sim, p_buds, p_bmetrics, p_bm_bad, has_g, g_max, g_forb, g_forb_t, g_cont, obs_proj, obs_unit, inv_base, prof_missing = _merged_profile_03(profiles_dir, prof_ref, proof_rank_fn)
 if use_params:
  norm_inv, p_deps, all_caps = {}, {}, set()
  for ik, iv in m_inv.items():
   ne, pr, cp = _norm_expr_03(iv, t_sch.get(ik), "then", units, use_params)
   norm_inv[ik] = ne
   p_deps.setdefault(f"then.{ik}", []).extend(pr)
   all_caps.update(cp)
 else:
  norm_inv = {k: dict(v) for k, v in inv_base[0].items()}
  p_deps = {k: list(v) for k, v in inv_base[1].items()}
  all_caps = set(inv_base[2])
 for ik, iv in (raw.get("invariants") or {}).items():
  ne, pr, cp = _norm_expr_03(iv, t_sch.get(ik), "then", units, use_params)
  norm_inv[ik] = {**norm_inv[ik], **ne} if ik in norm_inv else ne
  p_deps[f"then.{ik}"] = list(pr)
  all_caps.update(cp)
 sw_set, sw_base = set(sc_writes), {sw.split("#", 1)[0] for sw in sc_writes}
 norm_cases: dict[str, dict[str, Any]] = {}
 for is_inh, src_c in ((True, {k: v for k, v in m_cases.items() if k not in waived}), (False, raw.get("cases") or {})):
  for case_id, cm in src_c.items():
   if not isinstance(cm, dict):
    continue
   nc = dict(cm)
   if is_inh and isinstance(nc.get("writes"), list) and nc["writes"]:
    nc["writes"] = [w for w in nc["writes"] if isinstance(w, str) and (w in sw_set or (bw := w.split("#", 1)[0]) in sw_set or (w == bw and bw in sw_base))]
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
     nt[tk] = {**norm_inv[tk], **ne} if ("status" not in cm and tk in norm_inv) else ne
     p_deps.setdefault(f"then.{tk}", []).extend(pr)
     all_caps.update(cp)
    if "status" not in cm:
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
 sch_w = {wk: sch_w_canon[wk] for wk in need_w if wk in sch_w_canon}
 sch_t = {tk: sch_t_canon[tk] for tk in need_t if tk in sch_t_canon}
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
   if wk in sch_w_canon: ss[f"when.{wk}"] = sch_w_canon[wk]
   for pr in exp_peers(wv):
    if pr.startswith("when.") and pr[5:] in sch_w_canon: ss[pr] = sch_w_canon[pr[5:]]
  for tk, tv in (cl_c.get("then") or {}).items():
   if tk in sch_t_canon: ss[f"then.{tk}"] = sch_t_canon[tk]
   for pr in exp_peers(tv):
    if pr.startswith("when.") and pr[5:] in sch_w_canon: ss[pr] = sch_w_canon[pr[5:]]
    elif pr.startswith("then.") and pr[5:] in sch_t_canon: ss[pr] = sch_t_canon[pr[5:]]
  case_digs[k] = d2_fn("dr2b:sha256:", "drift.case-behavior/2", {"contract": cid, "case_id": k, "case": cl_c, "schema": ss, "units": dict(units)})
 dig_assur, res_budgets, res_formal, res_cutover, res_risks, res_ctrls, f_rrefs, eff_forb_t, eff_cont = {}, {}, {}, {}, {}, {}, {}, [], []
 if "guards" in assur or has_g:
  gm = assur.get("guards") if isinstance(assur.get("guards"), dict) else {}
  ml = gm.get("max_lines", g_max)
  fb = sorted(set(g_forb) | {str(x) for x in (gm.get("forbid_imports") or ()) if isinstance(x, str)})
  eff_forb_t = sorted(set(g_forb_t) | {str(x) for x in (gm.get("forbid_touched") or ()) if isinstance(x, str)})
  eff_cont = sorted(set(g_cont) | {str(x) for x in (gm.get("require_containment") or ()) if isinstance(x, str)})
  tgts = sorted({str(x) for x in (gm.get("target") or ()) if isinstance(x, str)})
  dig_assur["guards"] = {"target": tgts, **({"max_lines": ml} if isinstance(ml, int) and ml > 0 else {}), **({"forbid_imports": fb} if fb else {}), **({"forbid_touched": eff_forb_t} if eff_forb_t else {}), **({"require_containment": eff_cont} if eff_cont else {})}
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
 req_pos = {**({"proof": p_proof} if p_proof else {}), **({"security": sorted(p_sec)} if p_sec else {}), **({"simulation": "required"} if p_sim else {}), **({"budgets": "required"} if p_buds else {}), **({"budget_metrics": sorted(p_bmetrics)} if p_bmetrics else {})}
 assur_dig = d2_fn("dr2a:sha256:", "drift.assurance/2", {"contract": cid, "requires": req_pos, "assurance": dig_assur})
 d_match = lambda r, fd: isinstance(r, str) and bool(re.fullmatch(rf"{fd[:5]}(?:sha256:[0-9a-f]{{64}}|[0-9a-f]{{12}})", r)) and (r == fd or r == ref_fn(fd))
 has_blk = has_blocker_fn({**raw, "budgets": assur.get("budgets"), "formal": assur.get("formal"), "cutover": assur.get("cutover")}, {"decisions": m_decs}) or contains_todo_fn(raw.get("bind")) or contains_todo_fn(raw.get("invariants")) or contains_todo_fn(assur)
 has_any_ref = isinstance(appr, dict) and any(appr.get(k) for k in ("behavior_ref", "assurance_ref", "ref", "digest"))
 cur_ok = isinstance(appr, dict) and set(appr) <= {"behavior_ref", "assurance_ref", "by", "at"} and d_match(appr.get("behavior_ref"), beh_dig) and d_match(appr.get("assurance_ref"), assur_dig)
 act_cids = {k for k, cm in beh_cases.items() if isinstance(cm, dict) and "status" not in cm}
 st = "invalid" if (prof_missing or p_bm_bad or (p_buds and not res_budgets) or not _budget_metrics_closure_ok(p_bmetrics, res_budgets, act_cids)) else ("blocked" if has_blk else ("current" if cur_ok else ("stale" if has_any_ref else "absent")))
 open_m = raw.get("open") if isinstance(raw.get("open"), dict) else {}
 own_d = [d for d in (raw.get("decisions") or {}).values() if isinstance(d, dict)] if isinstance(raw.get("decisions"), dict) else []
 decs = [d for s in (raw.get("decisions"), m_decs) if isinstance(s, dict) for d in s.values() if isinstance(d, dict)]
 blk = lambda ph: any(isinstance(q, dict) and q.get("blocks") == ph for q in open_m.values()) or any(d.get("pick", "") == "" and d.get("decide_by") == ph for d in decs)
 roots = resolve_roots_fn(path)
 reuse_env = canon_fn({"id": cid, "intent": raw.get("intent", ""), "scope": raw.get("scope"), "waived": sorted(waived), "open": clean_open, "profile": prof_clos})
 case_reuse_sigs = {k: canon_fn({"case": beh_cases[k], "cards": {did: {**dm, "cases": [rc for rc in (dm.get("cases") or ()) if rc in act_cids]} for did, dm in loc_decs.items() if k in (dm.get("cases") or ())}}) for k in act_cids}
 return {"drift": "0.3", "id": cid, "digest": "" if prof_missing else beh_dig, "ref": "" if prof_missing else ref_fn(beh_dig), "assurance_digest": "" if prof_missing else assur_dig, "assurance_ref": "" if prof_missing else ref_fn(assur_dig), "approval": st, "approver": str(appr.get("by", "")) if isinstance(appr, dict) and cur_ok else (str(appr.get("by", "")) if has_any_ref else ""), **({"profile_missing": prof_missing} if prof_missing else {}), "profile_proof": p_proof, "profile_security": list(p_sec), "profile_simulation": p_sim, "profile_budgets": p_buds, "profile_budget_metrics": sorted(p_bmetrics), "require_containment": eff_cont, "scope_code": sc_code, "scope_reads": sc_reads, "scope_writes": sc_writes, "invariants": sorted(norm_inv), "cases": {} if prof_missing else beh_cases, "reuse_env": reuse_env, "case_reuse_sigs": case_reuse_sigs, "budgets": res_budgets, "formal": res_formal, "cutover": res_cutover, "risks": res_risks, "controls": res_ctrls, "required_capabilities": sorted(all_caps), "obs": {"proj": dict(obs_proj), "units": dict(units), "unit": dict(obs_unit), "w": sc_writes, "ft": eff_forb_t}, "area_root": roots["source_root"], "shadow_area_root": roots["area_root"], "open_cnt": len(open_m) + sum(1 for d in own_d if d.get("pick", "") == ""), "exec_blk": blk("execution"), "rel_blk": blk("release") or any(isinstance(c, dict) and c.get("status") == "deferred" for c in beh_cases.values())}

