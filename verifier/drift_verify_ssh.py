#!/usr/bin/env python3
"""OpenSSH signature verification helper for verifier/drift_verify.py."""

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Callable

SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ATTEST_TOP_KEYS = frozenset(("version", "predicate_type", "ok", "configs", "contracts", "evidence"))
ATTEST_CFG_KEYS = frozenset(("approval", "digest", "file", "ref"))
ATTEST_CONTRACT_REQ = frozenset(("approval", "bound", "digest", "file", "id", "ok", "reasons", "ref", "reused", "verified"))
ATTEST_CONTRACT_OPT = frozenset(("assurance_digest", "assurance_ref", "claim_scope", "formal_checks", "migration_checks", "parity_checks", "performance", "production_signals", "security_checks"))
ATTEST_EVIDENCE_REQ = frozenset(("event_shards", "snapshots", "snapshots_complete"))
ATTEST_EVIDENCE_OPT = frozenset(("incomplete_shards", "mutations_manifest", "performance_environments", "performance_manifest", "performance_run_id", "performance_subject", "subject_ref", "artifact_ref", "security_lock"))


def _project_profile_03_to_02_dict(prof: dict[str, Any]) -> dict[str, Any]:
    if prof.get("drift") != "0.3":
        return prof
    out: dict[str, Any] = {"drift": "0.2", "profile": prof.get("profile", "")}
    if "extends" in prof:
        out["extends"] = prof["extends"]
    if "params" in prof:
        out["params"] = prof["params"]
    sm = prof.get("schema") if isinstance(prof.get("schema"), dict) else {}
    vw, vt, units_m, pw, pt = [], [], {}, {}, {}
    for side, arr, pm_out in (("when", vw, pw), ("then", vt, pt)):
        for pname, pval in (sm.get(side) if isinstance(sm.get(side), dict) else {}).items():
            arr.append(pname)
            if isinstance(pval, dict):
                if "unit" in pval:
                    units_m[pname] = pval["unit"]
                if "ptr" in pval:
                    pm_out[pname] = pval["ptr"]
    voc: dict[str, Any] = {"when": vw, "then": vt}
    if units_m:
        voc["units"] = units_m
    out["vocabulary"] = voc
    if pw or pt:
        out["projections"] = {**({"when": pw} if pw else {}), **({"then": pt} if pt else {})}
    if isinstance(req := prof.get("requires"), dict):
        nreq = {k: v for k, v in req.items() if k != "guards"}
        if isinstance(gm := req.get("guards"), dict):
            nreq.update(gm)
        if nreq:
            out["requires"] = nreq
    if "kit" in prof:
        out["kit"] = prof["kit"]
    for k in ("concepts", "invariants", "cases", "decisions"):
        if k in prof:
            out[k] = prof[k]
    if isinstance(assur := prof.get("assurance"), dict):
        for k in ("risks", "controls"):
            if k in assur:
                out[k] = assur[k]
    return out


def load_merged_profile_impl(prof_ref: str, profiles_dir: Path, proof_rank_fn: Callable[[str], int]) -> dict[str, Any]:
    p0 = profiles_dir / f"{prof_ref}.toml"
    if not prof_ref or not p0.is_file():
        return {}
    prof = _project_profile_03_to_02_dict(tomllib.loads(p0.read_text(encoding="utf-8")))
    prof.pop("concepts", None)
    exts = prof.pop("extends", None)
    if not isinstance(exts, list) or not exts:
        return prof
    m, vw, vt, prm, pw, pt, req, cs, dc, inv = {"drift": prof.get("drift", "0.2"), "profile": prof.get("profile", prof_ref)}, [], [], {}, {}, {}, {}, {}, {}, {}
    for r in [*exts, prof_ref]:
        bp = prof if r == prof_ref else (_project_profile_03_to_02_dict(tomllib.loads(p.read_text(encoding="utf-8"))) if (p := profiles_dir / f"{r}.toml").is_file() else {})
        bv = bp.get("vocabulary") if isinstance(bp.get("vocabulary"), dict) else {}
        vw.extend(w for w in bv.get("when", []) if w not in vw)
        vt.extend(t for t in bv.get("then", []) if t not in vt)
        for s, d in (("params", prm), ("cases", cs), ("decisions", dc), ("invariants", inv)):
            if isinstance(bp.get(s), dict):
                d.update(bp[s])
        if isinstance(bpr := bp.get("projections"), dict):
            pw.update(bpr["when"] if isinstance(bpr.get("when"), dict) else {})
            pt.update(bpr["then"] if isinstance(bpr.get("then"), dict) else {})
            for pk, pv in bpr.items():
                if pk not in ("when", "then") and isinstance(pv, str):
                    (pt if pk in vt else pw)[pk] = pv
        if isinstance(bp.get("requires"), dict):
            for k, v in bp["requires"].items():
                if k == "security" and isinstance(v, list):
                    req["security"] = list(dict.fromkeys([*req.get("security", []), *(str(x) for x in v)]))
                elif k != "proof" or "proof" not in req or proof_rank_fn(str(v)) > proof_rank_fn(str(req["proof"])):
                    req[k] = v
        if "kit" in bp:
            m["kit"] = bp["kit"]
    m["vocabulary"] = {"when": vw, "then": vt}
    for k, v in (("params", prm), ("requires", req), ("invariants", inv), ("cases", cs), ("decisions", dc)):
        if v:
            m[k] = v
    if pw or pt:
        m["projections"] = {**({"when": pw} if pw else {}), **({"then": pt} if pt else {})}
    return m


def _valid_verify_time(ts: str) -> str:
 raw = ts.strip()
 if not raw.endswith(("Z", "z")): return ""
 clean = raw[:-1]
 return f"{clean}Z" if len(clean) == 14 and clean.isdigit() else ""


def _has_temporal_bounds(text: str) -> tuple[bool, bool]:
 has_bounds = False
 for raw in text.splitlines():
  line = raw.strip()
  if not line or line.startswith("#"): continue
  for opt in ('valid-after="', 'valid-before="'):
   if opt in line:
    has_bounds = True
    if not _valid_verify_time(line.split(opt, 1)[1].split('"', 1)[0]): return True, True
 return has_bounds, False


def verify_openssh_trust(payload_path: Path | None, sig_path: Path | None, namespace: str, trust_root: Path | None, verify_time: str = "") -> dict:
 if payload_path is None and trust_root is None and sig_path is None and not verify_time: return {"active": False}
 fail = lambda rsn, tr="none", sv=False: {"active": True, "reason": rsn, "trust_root_ref": tr, "namespace": namespace, "signature_valid": sv, "signer_authorized": False, "human_intervention": "unattested_key_use"}
 norm_root = trust_root.as_posix() if trust_root is not None else ""
 if trust_root is None or not trust_root.is_file() or trust_root.name == "config.toml" or norm_root.startswith(".drift/") or "/.drift/" in norm_root:
  return fail("trust.root_required")
 trust_text = trust_root.read_text(encoding="utf-8")
 trust_ref = "sha256:" + hashlib.sha256(trust_text.strip().encode("utf-8")).hexdigest()
 has_temp, invalid_temp = _has_temporal_bounds(trust_text)
 v_opt = _valid_verify_time(verify_time) if verify_time else ""
 if invalid_temp or (has_temp and not verify_time) or (verify_time and not v_opt):
  return fail("trust.verify_time_required", trust_ref)
 eff_sig = sig_path or (Path(f"{payload_path}.sig") if payload_path else None)
 if payload_path is None or not payload_path.is_file() or eff_sig is None or not eff_sig.is_file():
  return fail("trust.signature_invalid", trust_ref)
 ssh_keygen = shutil.which("ssh-keygen") or "/usr/bin/ssh-keygen"
 payload_bytes = payload_path.read_bytes()
 if subprocess.run([ssh_keygen, "-Y", "check-novalidate", "-q", "-n", namespace, "-s", str(eff_sig)], input=payload_bytes, capture_output=True).returncode != 0:
  return fail("trust.signature_invalid", trust_ref)
 fp_cmd = [ssh_keygen, "-Y", "find-principals", "-f", str(trust_root), "-s", str(eff_sig), *(["-O", f"verify-time={v_opt}"] if v_opt else [])]
 fp = subprocess.run(fp_cmd, capture_output=True, text=True)
 principals = [ln.strip() for ln in fp.stdout.strip().splitlines() if ln.strip()] if fp.returncode == 0 else []
 if not principals: return fail("trust.signer_unauthorized", trust_ref, True)
 for principal in principals:
  ver_cmd = [ssh_keygen, "-Y", "verify", "-q", "-f", str(trust_root), "-I", principal, "-n", namespace, "-s", str(eff_sig), *(["-O", f"verify-time={v_opt}"] if v_opt else [])]
  if subprocess.run(ver_cmd, input=payload_bytes, capture_output=True).returncode == 0:
   return {"active": True, "reason": "", "trust_root_ref": trust_ref, "namespace": namespace, "signature_valid": True, "signer_authorized": True, "human_intervention": "unattested_key_use", "verify_time": verify_time}
 return fail("trust.signer_unauthorized", trust_ref, True)


def _is_non_bool_int(v: Any) -> bool:
 return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def validate_and_match_attestation(payload_path: Path | None, verdicts: list[dict[str, Any]], cfg_state: str = "", cfg_digest: str = "", shard_hashes: list[str] | None = None, snapshots: list[str] | None = None, snapshots_complete: bool | None = None, incomplete_shards: int = 0, m_man: dict[str, Any] | None = None, perf_b: dict[str, Any] | None = None, decode_fn: Callable[[str], Any] | None = None, expected_subject: dict[str, Any] | None = None) -> tuple[bool, str]:
 if payload_path is None or not payload_path.is_file(): return False, "trust.attestation_invalid"
 parser = decode_fn or json.loads
 try: doc = parser(payload_path.read_text(encoding="utf-8"))
 except Exception: return False, "trust.attestation_invalid"
 if not isinstance(doc, dict) or set(doc) != ATTEST_TOP_KEYS or doc.get("version") != 1 or isinstance(doc.get("version"), bool) or doc.get("predicate_type") != "https://drift.dev/attestation/gate/v1" or not isinstance(doc.get("ok"), bool):
  return False, "trust.attestation_invalid"
 cfgs, cnts, ev = doc.get("configs"), doc.get("contracts"), doc.get("evidence")
 if not isinstance(cfgs, list) or not cfgs or not isinstance(cnts, list) or not cnts or not isinstance(ev, dict):
  return False, "trust.attestation_invalid"
 if any(not isinstance(c, dict) or set(c) != ATTEST_CFG_KEYS or not all(isinstance(c[k], str) for k in ATTEST_CFG_KEYS) for c in cfgs):
  return False, "trust.attestation_invalid"
 if not ATTEST_EVIDENCE_REQ.issubset(ev) or any(k not in (ATTEST_EVIDENCE_REQ | ATTEST_EVIDENCE_OPT) for k in ev):
  return False, "trust.attestation_invalid"
 ev_shards, ev_snaps, ev_comp = ev.get("event_shards"), ev.get("snapshots"), ev.get("snapshots_complete")
 if not isinstance(ev_shards, list) or not isinstance(ev_snaps, list) or not all(isinstance(s, str) for s in ev_snaps) or not isinstance(ev_comp, bool):
  return False, "trust.attestation_invalid"
 att_shard_hashes = []
 for sh in ev_shards:
  if not isinstance(sh, dict) or set(sh) != {"file", "sha256"} or not isinstance(sh.get("file"), str) or not isinstance(sh.get("sha256"), str) or not SHA256_REF_RE.match(sh["sha256"]):
   return False, "trust.attestation_invalid"
  att_shard_hashes.append(sh["sha256"])
 if ("incomplete_shards" in ev and not _is_non_bool_int(ev["incomplete_shards"])) or ("mutations_manifest" in ev and (not isinstance(ev["mutations_manifest"], str) or not SHA256_REF_RE.match(ev["mutations_manifest"]))):
  return False, "trust.attestation_invalid"
 by_id: dict[str, dict[str, Any]] = {}
 for c in cnts:
  if not isinstance(c, dict) or not ATTEST_CONTRACT_REQ.issubset(c) or any(k not in (ATTEST_CONTRACT_REQ | ATTEST_CONTRACT_OPT) for k in c) or not all(isinstance(c[k], str) for k in ("approval", "digest", "file", "id", "ref")) or not isinstance(c["ok"], bool) or not all(_is_non_bool_int(c[k]) for k in ("bound", "reused", "verified")) or not isinstance(c["reasons"], list) or not all(isinstance(r, str) for r in c["reasons"]) or c["id"] in by_id:
   return False, "trust.attestation_invalid"
  by_id[c["id"]] = c
 exp_mut_dig = m_man["digest"] if isinstance(m_man, dict) and "digest" in m_man else ""
 exp_perf_dig = perf_b.get("manifest_digest", "") if isinstance(perf_b, dict) and perf_b.get("active") and not perf_b.get("invalid") else ""
 exp_sub = expected_subject or {}
 exp_lock_ref = (exp_sub.get("security_lock") or {}).get("lock_ref", "") if (exp_sub.get("security_lock") or {}).get("active") else ""
 if (cfg_digest and not any(c["digest"] == cfg_digest and c["approval"] == cfg_state for c in cfgs)) or (shard_hashes is not None and sorted(att_shard_hashes) != sorted(shard_hashes)) or (snapshots is not None and ev_snaps != list(snapshots)) or (snapshots_complete is not None and ev_comp != bool(snapshots_complete)) or ev.get("incomplete_shards", 0) != incomplete_shards or ev.get("mutations_manifest", "") != exp_mut_dig or ev.get("performance_manifest", "") != exp_perf_dig or ev.get("subject_ref", "") != exp_sub.get("subject_ref", "") or ev.get("artifact_ref", "") != exp_sub.get("binary_ref", "") or ev.get("security_lock", "") != exp_lock_ref or set(by_id) != {v["id"] for v in verdicts} or len(cnts) != len(verdicts) or doc["ok"] != (bool(verdicts) and all(v["ok"] for v in verdicts)):
  return False, "trust.subject_mismatch"
 for v in verdicts:
  ac = by_id[v["id"]]
  ver_cnt = sum(1 for r in v.get("results", []) if r.get("state") == "verified")
  bnd_cnt = sum(1 for r in v.get("results", []) if r.get("state") == "bound")
  if ac["digest"] != v["digest"] or ac["ref"] != v["ref"] or ac.get("assurance_digest", "") != v.get("assurance_digest", "") or ac.get("assurance_ref", "") != v.get("assurance_ref", "") or ac["approval"] != v["approval"] or ac["ok"] != v["ok"] or ac["reasons"] != v["reasons"] or ac["verified"] != ver_cnt or ac["bound"] != bnd_cnt or any(ac.get(ck_k) != v.get(ck_k) for ck_k in ("security_checks", "formal_checks", "parity_checks", "migration_checks")):
   return False, "trust.subject_mismatch"
 return True, ""


def apply_openssh_trust_verdicts(verdicts: list[dict], args, cfg_state: str = "", cfg_digest: str = "", shard_hashes: list[str] | None = None, snapshots: list[str] | None = None, snapshots_complete: bool | None = None, incomplete_shards: int = 0, m_man: dict[str, Any] | None = None, perf_b: dict[str, Any] | None = None, decode_fn: Callable[[str], Any] | None = None, expected_subject: dict[str, Any] | None = None) -> list[dict]:
 tv = verify_openssh_trust(args.attest, args.attest_sig, "drift-attestation@v1", args.trust_root, args.verify_time)
 if tv.get("active"):
  if not tv.get("reason"):
   subj_ok, subj_rsn = validate_and_match_attestation(args.attest, verdicts, cfg_state=cfg_state, cfg_digest=cfg_digest, shard_hashes=shard_hashes, snapshots=snapshots, snapshots_complete=snapshots_complete, incomplete_shards=incomplete_shards, m_man=m_man, perf_b=perf_b, decode_fn=decode_fn, expected_subject=expected_subject)
   if not subj_ok: tv["reason"], tv["signature_valid"], tv["signer_authorized"] = subj_rsn, False, False
  for v in verdicts:
   if tv.get("reason") and tv["reason"] not in v["reasons"]: v["reasons"].append(tv["reason"]); v["ok"] = False
   v["trust_verification"] = {k: tv[k] for k in ("trust_root_ref", "namespace", "signature_valid", "signer_authorized", "human_intervention") if k in tv}
 return verdicts


PARITY_KEYS = frozenset(("schema", "contract", "digest", "requirement_ref", "legacy_target", "candidate_target", "legacy_subject_ref", "candidate_subject_ref", "normalization_ref", "corpus_ref", "legacy_cases", "candidate_cases", "diverged_observations", "effect_violations", "frame_verified", "rollback_readback", "outcome"))
ARTIFACT_REF_RE = re.compile(r"^(?:sha256:[0-9a-f]{64}|(?:dr1|dr2b|dr2r):(?:sha256:[0-9a-f]{64}|[0-9a-f]{12}))$")


def verify_contract_03_toml(raw: dict[str, Any], path: Path, profiles_dir: Path, canon_fn: Callable[[Any], str], ref_fn: Callable[[str], str], proof_rank_fn: Callable[[str], int], resolve_roots_fn: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
 from drift_verify_03 import verify_contract_03_toml as _v03
 return _v03(raw, path, profiles_dir, canon_fn, ref_fn, proof_rank_fn, resolve_roots_fn, _has_approval_blocker, _is_unanchored_prose_source, _contains_todo)


def _is_unanchored_prose_source(raw: str) -> bool:
    s = raw.strip()
    if not s or s.startswith("ADR-") or ";" in s or "://" in s:
        return False
    if " " in s:
        return True
    if ":" in s:
        return False
    b = s.split("@sha256:", 1)[0].replace("\\", "/")
    if not b or b.startswith(("note:", "cite:")) or any(c in b for c in " \t\n\r;"):
        return True
    dot = b.rfind(".")
    if 0 < dot < len(b) - 1 and b[dot + 1 :].isalnum() and any(c.isalpha() for c in b[dot + 1 :]):
        return False
    return not ("/" in b and any("a" <= c <= "z" for c in b))


def _contains_todo(v: Any) -> bool:
    return v == "todo" if isinstance(v, str) else (any(_contains_todo(x) for x in v) if isinstance(v, list) else (any(_contains_todo(x) for x in v.values()) if isinstance(v, dict) else False))


def _has_approval_blocker(raw: dict[str, Any], prof: dict[str, Any]) -> bool:
    if isinstance(sc := raw.get("scope"), dict) and sc.get("indirect") == "unknown":
        return True
    if any(_contains_todo(raw.get(s)) for s in ("use", "scope", "cases", "budgets", "formal", "cutover")):
        return True
    if isinstance(ot := raw.get("open"), dict) and any(isinstance(q, dict) and q.get("blocks", "approval") == "approval" for q in ot.values()):
        return True
    return any(isinstance(d, dict) and d.get("pick", "") == "" and d.get("decide_by", "approval") == "approval" for s in (raw.get("decisions"), prof.get("decisions")) if isinstance(s, dict) for d in s.values())


def extract_contract_cutover(raw: dict[str, Any], use_tbl: Any, dr1_digest_fn: Callable[[Any], str]) -> tuple[dict[str, Any], bool]:
    c_raw = raw.get("cutover")
    if not isinstance(c_raw, dict) or not c_raw:
        return {}, False
    params = {k: str(v) for k, v in use_tbl.items() if k not in ("profile", "waive", "vocabulary", "concepts") and isinstance(v, (str, int, bool))} if isinstance(use_tbl, dict) else {}
    def _sub(val: Any) -> Any:
        if isinstance(val, str):
            for pk, pv in params.items():
                if val == f"${{{pk}}}":
                    return pv
                val = val.replace(f"${{{pk}}}", pv)
            return val
        if isinstance(val, list):
            return [_sub(x) for x in val]
        if isinstance(val, dict):
            return {k: _sub(v) for k, v in val.items()}
        return val
    no_note = {k: v for k, v in c_raw.items() if k not in ("note", "requirement_ref")}
    raw["cutover"] = no_note
    sub_m = _sub(dict(c_raw))
    sw = (raw.get("scope") or {}).get("writes") or []
    if "rollback_readback" not in sub_m:
        sub_m["rollback_readback"] = "required" if sw else "not_applicable"
    if "enforce" not in sub_m:
        sub_m["enforce"] = "release"
    sub_no_note = {k: v for k, v in sub_m.items() if k not in ("note", "requirement_ref")}
    sub_m["requirement_ref"] = dr1_digest_fn(sub_no_note)
    return sub_m, True


def load_parity_receipts_impl(events_paths: list[Path], decode_fn: Callable[[str], Any]) -> tuple[list[dict[str, Any]], list[str]]:
 files = [f for p in events_paths for f in (sorted(p.glob("*.parity.json")) if p.is_dir() else ([p] if p.is_file() and p.name.endswith(".parity.json") else []))]
 out, errs, seen = [], [], set()
 str_keys = ("contract", "digest", "requirement_ref", "legacy_target", "candidate_target", "legacy_subject_ref", "candidate_subject_ref", "normalization_ref", "corpus_ref", "rollback_readback", "outcome")
 for pf in files:
  if pf in seen:continue
  seen.add(pf)
  try:
   doc = decode_fn(pf.read_text(encoding="utf-8"))
   if not isinstance(doc, dict) or set(doc) != PARITY_KEYS or doc.get("schema") != "drift.parity-receipt/1" or any(not isinstance(doc.get(k), str) or not doc[k].strip() for k in str_keys):raise ValueError("parity_keys")
   s = {k: doc[k].strip() for k in str_keys}
   cid, dig, rref, leg, cand, lref, cref, nref, cpref, rb, outc = (s[k] for k in str_keys)
   fv = doc.get("frame_verified")
   if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", cid) or not ARTIFACT_REF_RE.match(dig) or not ARTIFACT_REF_RE.match(rref) or leg == cand or not ARTIFACT_REF_RE.match(lref) or not ARTIFACT_REF_RE.match(cref) or not ARTIFACT_REF_RE.match(nref) or not ARTIFACT_REF_RE.match(cpref) or not isinstance(fv, bool) or rb not in ("verified", "not_applicable", "unverified", "failed") or outc not in ("passed", "failed"):raise ValueError("parity_fields")
   lists = {}
   for lk in ("legacy_cases", "candidate_cases", "diverged_observations", "effect_violations"):
    arr = doc.get(lk)
    if not isinstance(arr, list) or not all(isinstance(x, str) and x.strip() for x in arr):raise ValueError(lk)
    lists[lk] = sorted({x.strip() for x in arr})
   out.append({"schema": "drift.parity-receipt/1", **s, "frame_verified": fv, **lists})
  except Exception as exc:errs.append(f"{pf.name}: {exc}")
 return out, errs
def evaluate_contract_parity_impl(contract: dict[str, Any], parity_receipts: list[dict[str, Any]], phase: str, digest_matches_fn: Callable[[str, str], bool], expected_subject_ref: str = "", shard_subject_refs: set[str] | None = None, mig_checks: list[dict[str, Any]] | None = None) -> tuple[list[str], list[dict[str, Any]]]:
 cm = contract.get("cutover") or {}
 if not cm:return [], []
 enforced_now = str(cm.get("enforce", "release")) == "always" or phase == "release"
 matching = [r for r in parity_receipts if r["contract"] == contract["id"] and digest_matches_fn(r["digest"], contract["digest"])]
 if not matching:return (["parity.missing"] if enforced_now else []), []
 if len(matching) > 1 and any(r != matching[0] for r in matching[1:]):return ["parity.conflicting_receipts"], [{**r, "effective_outcome": "failed", "reason": "parity.conflicting_receipts"} for r in matching]
 rec, raw_cases = matching[0], contract.get("cases") or {}
 active = sorted(cid for cid, c in raw_cases.items() if isinstance(c, dict) and "status" not in c)
 needs_frames = bool((contract.get("scope_writes") or []) or any(isinstance(c, dict) and "writes" in c for c in raw_cases.values()))
 allowed, sh_refs, m_list = set(cm.get("intentional_diffs") or []), shard_subject_refs or set(), mig_checks or []
 comp_ok = rec["legacy_subject_ref"] != rec["candidate_subject_ref"] and all(ac in rec["legacy_cases"] and ac in rec["candidate_cases"] for ac in active)
 sub_ok = (not expected_subject_ref or digest_matches_fn(rec["candidate_subject_ref"], expected_subject_ref)) and (not sh_refs or any(digest_matches_fn(rec["candidate_subject_ref"], s) for s in sh_refs))
 norm_ok = rec["legacy_target"] == cm.get("legacy_target") and rec["candidate_target"] == cm.get("candidate_target") and digest_matches_fn(rec["normalization_ref"], str(cm.get("normalization_ref", ""))) and digest_matches_fn(rec["corpus_ref"], str(cm.get("corpus_ref", ""))) and (not cm.get("requirement_ref") or digest_matches_fn(rec["requirement_ref"], cm["requirement_ref"]))
 obs_ok, eff_ok, rb_ok = all(d in allowed for d in rec["diverged_observations"]), not rec["effect_violations"] and (not needs_frames or rec["frame_verified"]), cm.get("rollback_readback", "not_applicable") != "required" or rec["rollback_readback"] == "verified"
 migs_ok = all(any(mr.get("migration_id") == mid and mr.get("effective_outcome") == "passed" and digest_matches_fn(str(mr.get("subject_ref", "")), rec["candidate_subject_ref"]) for mr in m_list) and not any(mr.get("migration_id") == mid and mr.get("effective_outcome") != "passed" for mr in m_list) for mid in (cm.get("migration_ids") or []))
 reasons = [tag for cond, tag in ((not comp_ok, "parity.incomplete_target"), (not sub_ok, "parity.subject_mismatch"), (not norm_ok, "parity.normalization_mismatch"), (not obs_ok, "parity.observation_mismatch"), (not eff_ok, "parity.effect_mismatch"), (not rb_ok, "parity.rollback_incompatible"), (not migs_ok, "parity.migration_unverified")) if cond]
 if rec["outcome"] != "passed" and not reasons:reasons.append("parity.observation_mismatch")
 eff_out = "passed" if not reasons and rec["outcome"] == "passed" else "failed"
 return reasons, [{**rec, "effective_outcome": eff_out, **({"reason": reasons[0]} if reasons else {})}]
def parse_subject_manifest_core(text: str, decode_fn: Any, canon_fn: Any, sec_str_fn: Any, valid_rel_scope_fn: Any, sha256_re: Any) -> dict[str, Any]:
 import hashlib
 doc = decode_fn(text)
 if not isinstance(doc,dict) or any(k not in ("schema","subject_ref","artifact_ref","sources","lockfile_ref","toolchain","target","features","flags","harness","verifier_ref") for k in doc) or doc.get("schema") != "drift.subject-manifest/1":raise ValueError("subject_manifest")
 aref,lref,vref = (sec_str_fn(doc,"artifact_ref") if "artifact_ref" in doc else ""),sec_str_fn(doc,"lockfile_ref"),sec_str_fn(doc,"verifier_ref")
 tc,tgt,harn = sec_str_fn(doc,"toolchain"),sec_str_fn(doc,"target"),sec_str_fn(doc,"harness")
 if (aref and not sha256_re.match(aref)) or not sha256_re.match(lref) or not sha256_re.match(vref) or not valid_rel_scope_fn(harn) or "#" not in harn:raise ValueError("subject_manifest_fields")
 feats = [sec_str_fn({"x":x},"x") for x in doc.get("features",[])] if isinstance(doc.get("features",[]),list) else None
 flgs = [sec_str_fn({"x":x},"x") for x in doc.get("flags",[])] if isinstance(doc.get("flags",[]),list) else None
 srcs = doc.get("sources")
 if feats is None or flgs is None or not isinstance(srcs,dict) or not srcs or any(not valid_rel_scope_fn(sp) or "#" in sp or not isinstance(sh,str) or not sha256_re.match(sh) for sp,sh in srcs.items()):raise ValueError("subject_manifest_sources")
 c_obj = {"features":feats,"flags":flgs,"harness":harn,"lockfile_ref":lref,"schema":"drift.subject-manifest/1","sources":dict(srcs),"target":tgt,"toolchain":tc,"verifier_ref":vref}
 comp_ref = "sha256:" + hashlib.sha256(canon_fn(c_obj).encode("utf-8")).hexdigest()
 if "subject_ref" in doc and sec_str_fn(doc,"subject_ref") != comp_ref:raise ValueError("subject_ref_mismatch")
 return {**c_obj,"subject_ref":comp_ref,**({"artifact_ref":aref} if aref else {})}


def run_03_self_test(dv_mod: Any) -> None:
 with tempfile.TemporaryDirectory() as td:
  tp = Path(td)
  (tp / "p03@1.toml").write_text('drift = "0.3"\nprofile = "p03@1"\n[schema.when]\nbalance = { type = "int", min = 0 }\n[schema.then]\nbalance = { type = "int", min = 0 }\n', "utf-8")
  (tp / "c03.toml").write_text('drift = "0.3"\nid = "c03"\nintent = "C03."\n[use]\nprofile = "p03@1"\n[scope]\nwrites = []\nreads = []\nindirect = "none"\n[cases.ok]\nat = ["unit"]\nwhen.balance = 100\nthen.balance = { peer = { eq = "when.balance", balance = { add = ["when.balance"] } } }\n', "utf-8")
  v03_u = dv_mod.verify_contract_toml(tp / "c03.toml", tp)
  assert v03_u["digest"].startswith("dr2b:sha256:") and v03_u["approval"] == "absent" and v03_u["required_capabilities"] == ["rel-linear-balance/1"]
  (tp / "c03.toml").write_text((tp / "c03.toml").read_text("utf-8") + f'[approval]\nbehavior_ref = "{v03_u["ref"]}"\nassurance_ref = "{v03_u["assurance_ref"]}"\nby = "o"\nat = 2026-11-09T18:25:00Z\n', "utf-8")
  v03 = dv_mod.verify_contract_toml(tp / "c03.toml", tp)
  assert v03["approval"] == "current" and v03["digest"] == v03_u["digest"]
  ev03_ok = [{"test": "T#ok", "contract": "c03", "cases": ["ok"], "read": ["ok"], "level": "unit", "outcome": "passed", "digest": v03["ref"], "schema": "0.3", "capabilities": ["rel-linear-balance/1"]}]
  ev03_bad = [{**ev03_ok[0], "capabilities": []}]
  assert dv_mod.evaluate_contract(v03, "current", ev03_ok, 0, 0, [])["ok"] and "events.invalid" in dv_mod.evaluate_contract(v03, "current", ev03_bad, 0, 0, [])["reasons"]
  assert "contract.approval.unlisted" in dv_mod.evaluate_contract(v03, "current", ev03_ok, 0, 0, [], {"pack": "core@1", "approvers": ["alice"]})["reasons"]
  v03_sec = {**v03, "profile_security": ["sast"], "profile_simulation": True}
  r_sec_sim = dv_mod.evaluate_contract(v03_sec, "current", ev03_ok, 0, 0, [])["reasons"]
  assert "security.missing" in r_sec_sim and "sim.missing" in r_sec_sim

