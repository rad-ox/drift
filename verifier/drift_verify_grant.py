#!/usr/bin/env python3
"""Clean-room grant-lock (drift.grant-lock/1) & drift-grant@v1 verifier helper."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable
import tomllib

GRANT_NAMESPACE = "drift-grant@v1"
GRANT_SCHEMA = "drift.grant-lock/1"
GRANT_DOMAIN = b"drift.grant-lock/2\x00"
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_WORD03_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def tok_str_03(s: str, params: dict[str, Any], allow_lookup: bool = True) -> Any:
    if "$" not in s:
        return s
    if allow_lookup and s.startswith("${") and s.endswith("}") and not s.startswith("$${") and _WORD03_RE.match(s[2:-1]):
        return params.get(s[2:-1], s)
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i : i + 3] == "$${" and (cl := s.find("}", i + 3)) > i + 3 and _WORD03_RE.match(s[i + 3 : cl]):
            out.append("${" + s[i + 3 : cl] + "}")
            i = cl + 1
            continue
        if allow_lookup and s[i : i + 2] == "${" and (cl := s.find("}", i + 2)) > i + 2:
            nm = s[i + 2 : cl]
            if nm in params:
                v = params[nm]
                out.append(("true" if v else "false") if isinstance(v, bool) else str(v))
            i = cl + 1
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def unesc_lit_03(v: Any) -> Any:
    if isinstance(v, str):
        return tok_str_03(v, {}, False)
    if isinstance(v, list):
        return [unesc_lit_03(x) for x in v]
    return {k: unesc_lit_03(val) for k, val in v.items()} if isinstance(v, dict) else v
DR2G_FULL_RE = re.compile(r"^dr2g:sha256:[0-9a-f]{64}$")
DR2G_REF_RE = re.compile(r"^dr2g:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})$")
DR2B_FULL_RE = re.compile(r"^dr2b:sha256:[0-9a-f]{64}$")
DR2R_FULL_RE = re.compile(r"^dr2r:sha256:[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SEC_CATS = {"sast", "fuzz", "policy", "deps"}


def _valid_rel_source(p: str) -> bool:
    if not p or p.strip() != p or p.startswith(("/", "\\")) or "\\" in p or ":" in p:
        return False
    return all(seg not in ("", ".", "..") for seg in p.split("/"))


def _parse_grant_lock_py(text: str, decode_fn: Callable[[str], Any], canon_fn: Callable[[Any], str]) -> dict[str, Any]:
    doc = decode_fn(text)
    if not isinstance(doc, dict):
        raise ValueError("object")
    allowed = {"schema", "grant_id", "revision", "supersedes", "contracts", "sources", "digest"}
    if any(k not in allowed for k in doc) or any(r not in doc for r in ("schema", "grant_id", "revision", "contracts", "sources", "digest")):
        raise ValueError("keys")
    if doc["schema"] != GRANT_SCHEMA or not isinstance(doc["grant_id"], str) or not ID_RE.match(doc["grant_id"]):
        raise ValueError("header")
    rev = doc["revision"]
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 1:
        raise ValueError("revision")
    if "supersedes" in doc:
        if rev == 1 or not isinstance(doc["supersedes"], str) or not DR2G_REF_RE.match(doc["supersedes"]):
            raise ValueError("supersedes")
    elif rev > 1:
        raise ValueError("supersedes_missing")
    dg = doc["digest"]
    if not isinstance(dg, str) or not DR2G_FULL_RE.match(dg):
        raise ValueError("digest")
    cm = doc["contracts"]
    if not isinstance(cm, dict) or not cm:
        raise ValueError("contracts")
    for cid, ce in cm.items():
        if not isinstance(cid, str) or not ID_RE.match(cid) or not isinstance(ce, dict):
            raise ValueError("contract_entry")
        if set(ce) != {"behavior_digest", "requires", "obligations"}:
            raise ValueError("contract_keys")
        if not isinstance(ce["behavior_digest"], str) or not DR2B_FULL_RE.match(ce["behavior_digest"]):
            raise ValueError("behavior_digest")
        rm, om = ce["requires"], ce["obligations"]
        if not isinstance(rm, dict) or any(rk not in ("proof", "security", "simulation", "budgets") for rk in rm):
            raise ValueError("requires")
        if "proof" in rm and rm["proof"] not in ("bound", "verified", "killed"):
            raise ValueError("proof")
        if "security" in rm:
            sec_l = rm["security"]
            if not isinstance(sec_l, list) or any(not isinstance(x, str) or x not in SEC_CATS for x in sec_l) or sec_l != sorted(set(sec_l)):
                raise ValueError("security")
        if "simulation" in rm and rm["simulation"] != "required":
            raise ValueError("simulation")
        if "budgets" in rm and rm["budgets"] != "required":
            raise ValueError("budgets")
        if not isinstance(om, dict) or any(not isinstance(ok, str) or not ok.strip() or not isinstance(ov, str) or not DR2R_FULL_RE.match(ov) for ok, ov in om.items()):
            raise ValueError("obligations")
    sm = doc["sources"]
    if not isinstance(sm, dict) or any(not isinstance(sk, str) or not _valid_rel_source(sk) or not isinstance(sv, str) or not SHA256_RE.match(sv) for sk, sv in sm.items()):
        raise ValueError("sources")
    unsigned = {k: v for k, v in doc.items() if k != "digest"}
    exp_dg = "dr2g:sha256:" + hashlib.sha256(GRANT_DOMAIN + canon_fn(unsigned).encode("utf-8")).hexdigest()
    if exp_dg != dg:
        raise ValueError("digest_mismatch")
    return doc


def _verify_grant_sig_py(lock_path: Path, explicit_lock: bool, trust_root: Path | None, verify_time: str) -> tuple[str, bool]:
    from drift_verify_ssh import _has_temporal_bounds, _valid_verify_time
    sig_path = Path(f"{lock_path}.sig")
    has_sig_file = sig_path.is_file()
    ssh_keygen = shutil.which("ssh-keygen") or "/usr/bin/ssh-keygen"
    if has_sig_file:
        if subprocess.run([ssh_keygen, "-Y", "check-novalidate", "-q", "-n", GRANT_NAMESPACE, "-s", str(sig_path)], input=lock_path.read_bytes(), capture_output=True).returncode != 0:
            return "grant.signature_invalid", True
    if trust_root is None or (not explicit_lock and not has_sig_file):
        return "", False
    norm_root = trust_root.as_posix()
    if not trust_root.is_file() or trust_root.name == "config.toml" or norm_root.startswith(".drift/") or "/.drift/" in norm_root:
        return "trust.root_required", True
    has_temp, invalid_temp = _has_temporal_bounds(trust_root.read_text(encoding="utf-8"))
    v_opt = _valid_verify_time(verify_time) if verify_time else ""
    if invalid_temp or (has_temp and not verify_time) or (verify_time and not v_opt):
        return "trust.verify_time_required", True
    if not has_sig_file:
        return "grant.signature_invalid", True
    payload = lock_path.read_bytes()
    fp = subprocess.run([ssh_keygen, "-Y", "find-principals", "-f", str(trust_root), "-s", str(sig_path), *(["-O", f"verify-time={v_opt}"] if v_opt else [])], capture_output=True, text=True)
    principals = [ln.strip() for ln in fp.stdout.strip().splitlines() if ln.strip()] if fp.returncode == 0 else []
    if not principals:
        return "grant.signer_unauthorized", True
    for principal in principals:
        if subprocess.run([ssh_keygen, "-Y", "verify", "-q", "-f", str(trust_root), "-I", principal, "-n", GRANT_NAMESPACE, "-s", str(sig_path), *(["-O", f"verify-time={v_opt}"] if v_opt else [])], input=payload, capture_output=True).returncode == 0:
            return "", True
    return "grant.signer_unauthorized", True


def _collect_contract_obligations_py(c: dict[str, Any], canon_fn: Callable[[Any], str]) -> dict[str, str]:
    cid, out = c["id"], {}
    for tag, tbl in (("budget", c.get("budgets")), ("formal", c.get("formal")), ("control", c.get("controls"))):
        if isinstance(tbl, dict):
            for oid, om in tbl.items():
                if isinstance(om, dict) and om.get("requirement_ref"):
                    out[f"{tag}:{oid}"] = str(om["requirement_ref"])
    if isinstance(cut := c.get("cutover"), dict) and cut.get("requirement_ref"):
        out["cutover"] = str(cut["requirement_ref"])
    if isinstance(risks := c.get("risks"), dict):
        for rid, rm in risks.items():
            if isinstance(rm, dict):
                cl = {rk: rv for rk, rv in rm.items() if rk not in ("note", "requirement_ref")}
                payload = {"contract": cid, "kind": "risk", "id": rid, "entry": cl}
                out[f"risk:{rid}"] = "dr2r:sha256:" + hashlib.sha256(b"drift.requirement/2\x00" + canon_fn(payload).encode("utf-8")).hexdigest()
    return out


def evaluate_grant_verdicts_py(
    verdicts: list[dict[str, Any]],
    parsed_contracts: list[dict[str, Any]],
    args: Any,
    cfg_path: Path,
    pol: dict[str, Any],
    area_root: str | Path | None,
    decode_fn: Callable[[str], Any],
    canon_fn: Callable[[Any], str],
    digest_matches_fn: Callable[[str, str], bool],
    proof_rank_fn: Callable[[str], int],
    single_file: bool,
) -> tuple[list[dict[str, Any]], bool]:
    pol_on = pol.get("pack") == "core@1"
    pinned = str(pol.get("grant_lock", "")) if pol_on and isinstance(pol.get("grant_lock"), str) else ""
    explicit_lock: Path | None = getattr(args, "grant_lock", None)
    lock_path = explicit_lock if explicit_lock is not None else (cfg_path.parent / "grant.lock.json")
    has_file = lock_path.is_file()
    if explicit_lock is None and not pinned and not has_file:
        return verdicts, False
    has_grant_sig = bool(explicit_lock is not None or Path(f"{lock_path}.sig").is_file())
    if not has_file:
        for v in verdicts:
            if "grant.lock_missing" not in v["reasons"]:
                v["reasons"].append("grant.lock_missing")
                v["ok"] = False
        return verdicts, bool(explicit_lock is not None)
    sig_rsn, has_grant_sig = _verify_grant_sig_py(lock_path, explicit_lock is not None, getattr(args, "trust_root", None), getattr(args, "verify_time", ""))
    try:
        glock = _parse_grant_lock_py(lock_path.read_text("utf-8"), decode_fn, canon_fn)
    except Exception:
        for v in verdicts:
            if "grant.lock_invalid" not in v["reasons"]:
                v["reasons"].append("grant.lock_invalid")
                v["ok"] = False
        return verdicts, has_grant_sig

    global_rsns: list[str] = []
    if sig_rsn:
        global_rsns.append(sig_rsn)
    if explicit_lock is None and pinned and not digest_matches_fn(pinned, glock["digest"]):
        global_rsns.append("grant.lock_mismatch")

    src_root = Path(area_root) if area_root else cfg_path.parent.parent
    for spath, want_sha in sorted(glock["sources"].items()):
        sp_full = src_root / spath
        if sp_full.is_symlink() or not sp_full.is_file() or ("sha256:" + hashlib.sha256(sp_full.read_bytes()).hexdigest()) != want_sha:
            if "source.digest_mismatch" not in global_rsns:
                global_rsns.append("source.digest_mismatch")

    id_counts: dict[str, int] = {}
    for c in parsed_contracts:
        id_counts[c["id"]] = id_counts.get(c["id"], 0) + 1

    valid_present: set[str] = set()
    out_v = []
    for v, c in zip(verdicts, parsed_contracts):
        cid = c["id"]
        crs: list[str] = []
        stem_ok = c.get("file_stem", cid) == cid
        if cid in glock["contracts"]:
            exp = glock["contracts"][cid]
            if id_counts.get(cid, 0) > 1 or not stem_ok or c.get("drift") != "0.3" or c.get("digest") != exp["behavior_digest"]:
                crs.append("grant.behavior_tampered")
            else:
                valid_present.add(cid)
            req = exp["requires"]
            c_pr = str(c.get("profile_proof", ""))
            eff_pr = max(proof_rank_fn(str(pol.get("proof", ""))), proof_rank_fn(c_pr)) if pol_on else proof_rank_fn(c_pr)
            if proof_rank_fn(c_pr) < proof_rank_fn(req.get("proof", "")) or eff_pr < proof_rank_fn(req.get("proof", "")):
                crs.append("grant.posture_lowered")
            c_sec = set(c.get("profile_security") or ())
            if any(s not in c_sec for s in (req.get("security") or ())) or (req.get("simulation") == "required" and not c.get("profile_simulation")) or (req.get("budgets") == "required" and not c.get("profile_budgets")):
                if "grant.posture_lowered" not in crs:
                    crs.append("grant.posture_lowered")
            act_obs = _collect_contract_obligations_py(c, canon_fn)
            if any(act_obs.get(ok) != ov for ok, ov in exp["obligations"].items()):
                crs.append("grant.obligation_tampered")
        elif id_counts.get(cid, 0) > 1 or not stem_ok:
            crs.append("grant.behavior_tampered")
        nr = list(v["reasons"])
        for gr in (*global_rsns, *crs):
            if gr not in nr:
                nr.append(gr)
        cs = dict(v.get("claim_scope") or {})
        cs["grant_lock_ref"] = glock["digest"]
        out_v.append({**v, "reasons": nr, "ok": not nr, "claim_scope": cs})

    if not single_file:
        for cid in sorted(glock["contracts"]):
            if cid not in id_counts:
                mr = [*global_rsns]
                if "grant.contract_missing" not in mr:
                    mr.append("grant.contract_missing")
                out_v.append({"id": cid, "digest": "", "ref": "", "approval": "missing", "ok": False, "reasons": mr, "ignored": 0, "superseded": 0, "gone": 0, "results": [], "claim_scope": {"grant_lock_ref": glock["digest"]}})
    return out_v, has_grant_sig


def verify_config_toml_impl(path: Path, dr1_digest_fn: Callable[[Any], str], dr1_ref_fn: Callable[[str], str]) -> tuple[str, str, dict[str, Any]]:
    if not path.is_file():
        return "missing", "", {}
    raw = tomllib.loads(path.read_text("utf-8"))
    if raw.get("drift") != "0.3":
        return "invalid", "", {}
    appr = raw.pop("approval", None)
    dig = dr1_digest_fn(raw)
    pol = raw.get("policy") if isinstance(raw.get("policy"), dict) else {}
    if not isinstance(appr, dict) or not appr.get("ref"):
        return "absent", dig, pol
    st = "current" if appr["ref"] == dr1_ref_fn(dig) else "stale"
    return st, dig, (pol if st == "current" else {})


def strip_outside_digest_impl(cases: Any, decs: Any, is_prose_fn: Callable[[str], bool]) -> None:
    for cm in (cases or {}).values():
        if isinstance(cm, dict):
            cm.pop("note", None)
    for dm in (decs or {}).values() if isinstance(decs, dict) else ():
        if isinstance(dm, dict):
            dm.pop("owner", None)
            dm.pop("note", None)
            if dm.get("evidence") == "observed" and is_prose_fn(str(dm.get("source", ""))):
                dm.pop("source", None)


_META_KEYS = {"version", "classes", "tests", "snapshot", "pack_ref", "touched", "self_stubbed", "inputs", "env", "execution_ref", "subject_ref", "shadow_run"}
_ENV_KEYS = frozenset(("toolchain", "deps", "config", "runner", "drift", "adapter", "policy"))
_SNAP_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_PREF_RE = re.compile(r"^dr(?:1|2b):[0-9a-f]{12}$")
_CLS_RE = re.compile(r"^[^# \t\r\n/\\\[\]]+$")
_MTH_RE = re.compile(r"^[^# \t\r\n\[\]]+$")


def validate_inventory_text_impl(text: str, decode_fn: Callable[[str], Any]) -> dict[str, Any]:
    doc = decode_fn(text)
    if not isinstance(doc, dict) or any(k not in _META_KEYS for k in doc) or doc.get("version") not in (1, 2) or isinstance(doc.get("version"), bool):
        raise ValueError("inv")
    ex_ref, s_ref = doc.get("execution_ref", ""), doc.get("subject_ref", "")
    if (doc["version"] == 2 and not SHA256_RE.match(str(ex_ref))) or (doc["version"] == 1 and "execution_ref" in doc) or ("subject_ref" in doc and not SHA256_RE.match(str(s_ref))):
        raise ValueError("ref")
    cls, tsts = doc.get("classes"), doc.get("tests")
    if not isinstance(cls, list) or not all(isinstance(x, str) and _CLS_RE.match(x) for x in cls) or cls != sorted(set(cls)):
        raise ValueError("cls")
    c_set = set(cls)
    if not isinstance(tsts, list) or not all(isinstance(x, str) and "#" in x for x in tsts) or tsts != sorted(set(tsts)) or any((p := t.split("#", 1))[0] not in c_set or not _MTH_RE.match(p[1]) for t in tsts):
        raise ValueError("tst")
    t_set, snap, pref = set(tsts), doc.get("snapshot", ""), doc.get("pack_ref", "")
    if ("snapshot" in doc and (not isinstance(snap, str) or not _SNAP_RE.match(snap))) or ("pack_ref" in doc and (not isinstance(pref, str) or not _PREF_RE.match(pref))) or ("touched" in doc and (not isinstance(tc := doc["touched"], list) or not all(isinstance(x, str) and x.strip() for x in tc) or tc != sorted(set(tc)) or any(tp.startswith("/") or "\\" in tp or any(s in ("", ".", "..") for s in tp.split("/")) for tp in tc))) or ("self_stubbed" in doc and (not isinstance(doc["self_stubbed"], list) or any(not isinstance(x, str) or x not in t_set for x in doc["self_stubbed"]))) or ("inputs" in doc and (not isinstance(ri := doc["inputs"], dict) or any(tid not in t_set or not isinstance(fm, dict) or any(not isinstance(fp, str) or not fp.strip() or not isinstance(ov, str) or not ov.strip() for fp, ov in fm.items()) for tid, fm in ri.items()))) or ("env" in doc and (not isinstance(re_e := doc["env"], dict) or set(re_e) != _ENV_KEYS or any(not isinstance(ev, str) or not ev.strip() for ev in re_e.values()))):
        raise ValueError("inv")
    if "shadow_run" in doc:
        from drift_shadow_junit import validate_shadow_run_dict
        validate_shadow_run_dict(doc["shadow_run"])
    return {"classes": c_set, "tests": t_set, "snapshot": snap, "pack_ref": pref, "version": doc["version"], "execution_ref": ex_ref, "subject_ref": s_ref, "touched": set(doc.get("touched", [])), "shadow_run": doc.get("shadow_run")}


from decimal import Decimal as D

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
 ts = e.get("touched_symbols") or []
 io = e.get("init_only_symbols") or []
 if not isinstance(ts, list) or not all(isinstance(x, str) for x in ts) or not isinstance(io, list) or not all(isinstance(x, str) for x in io):
  raise ValueError("touched_symbols")
 return e.get("outcome", "returned"), _ob(e["payload"]) if "payload" in e else _ABS, e.get("presence", {}), e.get("frame", {}), ts, io


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


def _match_ft(sym: str, pat: str) -> bool:
 s, p = sym.strip(), pat.strip()
 if not s or not p or "#" not in s or "#" not in p:
  return False
 if s == p:
  return True
 sp, ss = s.split("#", 1)
 pp, ps = p.split("#", 1)
 pok = sp.startswith(pp[:-3] + "/") if pp.endswith("/**") else (sp.startswith(pp.rstrip("*")) if pp.endswith("*") else sp == pp)
 return pok and (ss.startswith(ps.rstrip("*")) if ps.endswith("*") else ss == ps)


def _judge(c, cid, e, dec=None):
 out, pay, pres, fr, ts, io = dec if dec is not None else _env(e)
 cm, cx = c["cases"][cid], c["obs"]
 ws, ps = fr.get("writes") or [], cm["writes"] if isinstance(cm.get("writes"), list) else cx["w"]
 if not isinstance(ws, list) or not all(isinstance(w, str) for w in ws):
  return "inconclusive"
 if out != "returned" or any(not (w in ps or w.split("#")[0] in ps or "#" not in w and any(x.split("#")[0] == w for x in ps)) for w in ws):
  return "violated"
 init_s = {x.strip() for x in io}
 fts = cx.get("ft") or ()
 if fts and any(_match_ft(s, pat) for s in ts if s.strip() and s.strip() not in init_s for pat in fts):
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
