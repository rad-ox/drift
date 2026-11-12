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
        if not isinstance(rm, dict) or any(rk not in ("proof", "security", "simulation") for rk in rm):
            raise ValueError("requires")
        if "proof" in rm and rm["proof"] not in ("bound", "verified", "killed"):
            raise ValueError("proof")
        if "security" in rm:
            sec_l = rm["security"]
            if not isinstance(sec_l, list) or any(not isinstance(x, str) or x not in SEC_CATS for x in sec_l) or sec_l != sorted(set(sec_l)):
                raise ValueError("security")
        if "simulation" in rm and rm["simulation"] != "required":
            raise ValueError("simulation")
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
            if any(s not in c_sec for s in (req.get("security") or ())) or (req.get("simulation") == "required" and not c.get("profile_simulation")):
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
