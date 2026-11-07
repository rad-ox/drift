#!/usr/bin/env python3
"""DRIFT Independent Reference Security Evidence Verifier (MIT License)."""

from __future__ import annotations
import hashlib, re
from pathlib import Path
from typing import Any, Callable

SNAPSHOT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEC_CATEGORIES = frozenset(("sast", "fuzz", "policy", "deps"))
SEC_OUTCOMES = frozenset(("passed", "violated", "inconclusive"))
SEC_KEYS = frozenset(("kind", "category", "tool", "tool_ref", "ruleset_ref", "contract", "digest", "code_snapshot", "covered_scope", "cases", "outcome"))
SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
DIGEST_RE = re.compile(r"^dr1:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})$")
THEN_MUT_OPS = frozenset(("negate", "add-one", "minus-one", "set-one", "multiply-two", "divide-two", "append-tilde", "drop-last", "seed-array", "swap-peer-then", "zero-sum-shear"))
WHEN_MUT_OPS = frozenset(("swap-case-when", "perturb-case-when"))


def validate_mutation_manifest_impl(text: str, decode_fn: Callable[[str], Any]) -> dict[str, Any]:
 doc = decode_fn(text)
 if not isinstance(doc, dict) or set(doc) != {"version", "contracts"} or doc.get("version") != 1 or isinstance(doc.get("version"), bool) or not isinstance(cs := doc["contracts"], list) or not cs:
  raise ValueError("manifest")
 by_id, targets, prev_c = {}, {}, ""
 for c in cs:
  if not isinstance(c, dict) or set(c) != {"id", "digest", "mutants"}:
   raise ValueError("contract")
  cid, cdig, muts = c["id"], c["digest"], c["mutants"]
  if not isinstance(cid, str) or not ID_RE.match(cid) or not isinstance(cdig, str) or not DIGEST_RE.match(cdig) or not isinstance(muts, list) or (prev_c and cid <= prev_c):
   raise ValueError("contract")
  prev_c, prev_m, m_list = cid, "", []
  for m in muts:
   if not isinstance(m, dict) or any(k not in ("id", "case", "path", "operator", "before", "after", "witness") for k in m) or any(r not in m for r in ("id", "case", "path", "operator", "before", "after")):
    raise ValueError("mutant")
   mid, mc, mp, mop = m["id"], m["case"], m["path"], m["operator"]
   if not all(isinstance(x, str) for x in (mid, mc, mp, mop)) or not ID_RE.match(mc) or mid != f"{mc}:{mp}" or (prev_m and mid <= prev_m):
    raise ValueError("mutant")
   esc = mc.replace("~", "~0").replace("/", "~1")
   tp, wp = f"/cases/{esc}/then/", f"/cases/{esc}/when/"
   if not ((mp.startswith(tp) and len(mp) > len(tp) and mop in THEN_MUT_OPS) or (mp.startswith(wp) and len(mp) > len(wp) and mop in WHEN_MUT_OPS)):
    raise ValueError("mutant")
   prev_m = mid
   targets[(cid, mid)] = rec = {"id": mid, "contract": cid, "digest": cdig, "case": mc, "path": mp}
   m_list.append(rec)
  by_id[cid] = {"id": cid, "digest": cdig, "mutants": m_list}
 return {"digest": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(), "contracts": by_id, "targets": targets}


def _sec_str(m: dict[str, Any], k: str) -> str:
 v = m.get(k)
 if not isinstance(v, str) or not v.strip() or v.strip() != v:
  raise ValueError(k)
 return v


def _valid_rel_scope(raw: Any) -> bool:
 if not isinstance(raw, str) or not raw or raw.strip() != raw or raw.startswith("/") or "\\" in raw or "://" in raw:
  return False
 base = raw.split("#", 1)[0]
 return bool(base) and not any(s in ("", ".", "..") for s in base.split("/"))


def _strip_anchor(s: str) -> str:
 return s.split("#", 1)[0].replace("\\", "/").rstrip("/")


def _wild_tok(pat: str, txt: str) -> bool:
 if pat == "*" or pat == txt:
  return True
 if "*" not in pat:
  return False
 parts = pat.split("*")
 if not txt.startswith(parts[0]) or not txt.endswith(parts[-1]):
  return False
 pos, end_lim = len(parts[0]), len(txt) - len(parts[-1])
 if pos > end_lim:
  return False
 for piece in parts[1:-1]:
  if not piece:
   continue
  idx = txt.find(piece, pos, end_lim)
  if idx < 0:
   return False
  pos = idx + len(piece)
 return True


def _match_segs(pat: list[str], path: list[str], pi: int = 0, si: int = 0) -> bool:
 if pi == len(pat):
  return si == len(path)
 if pat[pi] == "**":
  return _match_segs(pat, path, pi + 1, si) or (si < len(path) and _match_segs(pat, path, pi, si + 1))
 return si < len(path) and _wild_tok(pat[pi], path[si]) and _match_segs(pat, path, pi + 1, si + 1)


def _cov_matches(cov_raw: str, sc_raw: str) -> bool:
 cov, sc = _strip_anchor(cov_raw), _strip_anchor(sc_raw)
 if not cov or not sc:
  return False
 if cov in (sc, "**", "*") or sc.startswith(cov + "/"):
  return True
 return _match_segs(cov.split("/"), sc.split("/"))


def load_security_receipts_impl(events_paths: list[Path], decode_fn: Callable[[str], Any]) -> tuple[list[dict[str, Any]], list[str]]:
 files = [f for p in events_paths for f in (sorted(p.glob("*.security.json")) if p.is_dir() else ([p] if p.is_file() and p.name.endswith(".security.json") else []))]
 out, errs, seen = [], [], set()
 for sf in files:
  if sf in seen:
   continue
  seen.add(sf)
  try:
   doc = decode_fn(sf.read_text(encoding="utf-8"))
   if not isinstance(doc, dict) or set(doc) != SEC_KEYS or doc.get("kind") != "security_check":
    raise ValueError("sec_keys")
   cat, tool = _sec_str(doc, "category"), _sec_str(doc, "tool")
   tref, rref = _sec_str(doc, "tool_ref"), _sec_str(doc, "ruleset_ref")
   cid, dig = _sec_str(doc, "contract"), _sec_str(doc, "digest")
   csnap, outc = _sec_str(doc, "code_snapshot"), _sec_str(doc, "outcome")
   if cat not in SEC_CATEGORIES or not SHA256_REF_RE.match(tref) or not SHA256_REF_RE.match(rref) or not ID_RE.match(cid) or not DIGEST_RE.match(dig) or not SNAPSHOT_RE.match(csnap) or outc not in SEC_OUTCOMES:
    raise ValueError("sec_fields")
   cov, cs = doc.get("covered_scope"), doc.get("cases")
   if not isinstance(cov, list) or not cov or len(set(cov)) != len(cov) or not all(_valid_rel_scope(x) for x in cov):
    raise ValueError("covered_scope")
   if not isinstance(cs, list) or not cs or not all(isinstance(x, str) and ID_RE.match(x) for x in cs):
    raise ValueError("cases")
   out.append({"category": cat, "tool": tool, "tool_ref": tref, "ruleset_ref": rref, "contract": cid, "digest": dig, "code_snapshot": csnap, "covered_scope": sorted(set(cov)), "cases": sorted(set(cs)), "outcome": outc})
  except Exception as exc:
   errs.append(f"{sf.name}: {exc}")
 return out, errs


def evaluate_contract_security_impl(
 contract: dict[str, Any],
 sec_receipts: list[dict[str, Any]],
 policy: dict[str, Any] | None,
 expected_snapshot: str,
 digest_matches_fn: Callable[[str, str], bool],
) -> tuple[list[str], list[dict[str, Any]]]:
 pol = policy or {}
 req_cats = set(contract.get("profile_security") or [])
 if pol.get("pack") == "core@1" and isinstance(pol.get("security"), list):
  req_cats.update(str(x) for x in pol["security"] if isinstance(x, str))
 scope_code = contract.get("scope_code") or []
 current_by_key: dict[tuple[str, str], dict[str, Any]] = {}
 for r in sec_receipts:
  if r["contract"] == contract["id"] and digest_matches_fn(r["digest"], contract["digest"]):
   current_by_key[(r["category"], r["tool"])] = r
 if not current_by_key and not req_cats:
  return [], []
 eval_list, cat_states, has_viol = [], {}, False
 for key in sorted(current_by_key):
  rec = current_by_key[key]
  eff_out, rsn = rec["outcome"], ""
  if expected_snapshot and rec["code_snapshot"] != expected_snapshot:
   if eff_out == "passed":
    eff_out = "inconclusive"
   rsn = "security.snapshot_mismatch"
  elif not scope_code or not all(any(_cov_matches(c, sc) for c in rec["covered_scope"]) for sc in scope_code):
   if eff_out == "passed":
    eff_out = "inconclusive"
   rsn = "security.incomplete_scope"
  item = {**rec, "kind": "security_check", "effective_outcome": eff_out, "provenance": "measured"}
  if rsn:
   item["reason"] = rsn
  eval_list.append(item)
  if eff_out == "violated":
   has_viol = True
   cat_states[rec["category"]] = "violated"
  elif eff_out == "inconclusive" and cat_states.get(rec["category"]) != "violated":
   cat_states[rec["category"]] = "inconclusive"
  elif eff_out == "passed" and cat_states.get(rec["category"]) not in ("violated", "inconclusive"):
   cat_states[rec["category"]] = "passed"
 reasons = ["security.violated"] if has_viol else []
 has_inc, has_miss = False, False
 for rc in sorted(req_cats):
  st = cat_states.get(rc, "missing")
  if st == "violated" and "security.violated" not in reasons:
   reasons.append("security.violated")
  elif st == "inconclusive":
   has_inc = True
  elif st == "missing":
   has_miss = True
 if has_inc:
  reasons.append("security.inconclusive")
 if has_miss:
  reasons.append("security.missing")
 return reasons, eval_list
