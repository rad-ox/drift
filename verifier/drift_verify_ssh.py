#!/usr/bin/env python3
"""OpenSSH signature verification helper for verifier/drift_verify.py."""

import hashlib
import json
import os
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Callable

from drift_verify_base import (
    SHA256_REF_RE,
    _contains_todo,
    _has_approval_blocker,
    _has_temporal_bounds,
    _is_unanchored_prose_source,
    _valid_ext_trust_root_py,
    _valid_verify_time,
    ssh_keygen_executable,
)
from drift_verify_parity import (
    evaluate_contract_parity_impl,
    extract_contract_cutover,
    load_parity_receipts_impl,
)
from drift_verify_subject import parse_subject_manifest_core

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


def verify_openssh_trust(payload_path: Path | None, sig_path: Path | None, namespace: str, trust_root: Path | None, verify_time: str = "") -> dict:
 if payload_path is None and trust_root is None and sig_path is None and not verify_time: return {"active": False}
 fail = lambda rsn, tr="none", sv=False: {"active": True, "reason": rsn, "trust_root_ref": tr, "namespace": namespace, "signature_valid": sv, "signer_authorized": False, "human_intervention": "unattested_key_use"}
 norm_root = trust_root.as_posix() if trust_root is not None else ""
 if trust_root is None or trust_root.is_symlink() or not trust_root.is_file() or trust_root.name == "config.toml" or norm_root.startswith(".drift/") or "/.drift/" in norm_root or trust_root.resolve().name == "config.toml" or "/.drift/" in trust_root.resolve().as_posix():
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
 ssh_keygen = ssh_keygen_executable()
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


def verify_ssh_sig_envelope_impl(payload: dict[str, Any], sig_text: str, trust_root: Path | None, verify_time: str, canonical_json_fn: Any) -> tuple[bool, str]:
 if not _valid_ext_trust_root_py(trust_root):
  return False, "trust.root_required"
 has_temp, invalid_temp = _has_temporal_bounds(trust_root.read_text("utf-8"))
 if invalid_temp or (has_temp and not verify_time):
  return False, "trust.verify_time_required"
 v_opt = _valid_verify_time(verify_time) if verify_time else ""
 if verify_time and not v_opt:
  return False, "trust.verify_time_required"
 ns = "drift-signature@v2" if payload.get("schema") == "drift.signature-payload/2" else "drift-signature@v1"
 payload_bytes = canonical_json_fn(payload).encode("utf-8")
 with tempfile.NamedTemporaryFile("w", suffix=".sig", encoding="utf-8", delete=False) as tf:
  tf.write(sig_text if sig_text.endswith("\n") else sig_text + "\n")
  tmp_sig = tf.name
 try:
  keygen = ssh_keygen_executable()
  if subprocess.run([keygen, "-Y", "check-novalidate", "-q", "-n", ns, "-s", tmp_sig], input=payload_bytes, capture_output=True).returncode != 0:
   return False, "signature.invalid"
  v_args = [keygen, "-Y", "verify", "-q", "-f", str(trust_root), "-I", str(payload["signer"]), "-n", ns, "-s", tmp_sig, *(["-O", f"verify-time={v_opt}"] if v_opt else [])]
  return (True, "") if subprocess.run(v_args, input=payload_bytes, capture_output=True).returncode == 0 else (False, "signature.invalid")
 finally:
  try:
   os.remove(tmp_sig)
  except OSError:
   pass


def evaluate_detached_signatures_impl(verdicts: list[dict[str, Any]], parsed_contracts: list[dict[str, Any]], args: Any, cfg_dig: str, decode_fn: Any, canonical_json_fn: Any, digest_matches_fn: Any, collect_files_fn: Any, verify_sig_fn: Any, sig_env_keys: Any, sig_payload_keys: Any) -> list[dict[str, Any]]:
 sig_paths = list(args.events or []) + ([args.signatures] if getattr(args, "signatures", None) else [])
 sig_files, sig_pol_file = collect_files_fn(sig_paths, ".sig.json"), getattr(args, "signature_policy", None)
 if not sig_files and not sig_pol_file:
  return verdicts
 v2_keys = set(sig_payload_keys) | {"class", "packet_ref", "surface_tier"}
 req_tier_map = {"C0": 0, "C1": 0, "C2": 1, "C3": 2, "C4": 2}
 snap_by_ref: dict[str, tuple[str, list[str]]] = {}
 for sp in collect_files_fn(sig_paths, ".snapshot.json"):
  try:
   sdoc = decode_fn(sp.read_text("utf-8"))
   if isinstance(sdoc, dict) and sdoc.get("schema") == "drift.review-snapshot/1":
    body = {k: val for k, val in sdoc.items() if k != "review_ref"}
    recomp = "sha256:" + hashlib.sha256(canonical_json_fn(body).encode("utf-8")).hexdigest()
    if sdoc.get("review_ref") in (None, "", recomp):
     snap_by_ref[recomp] = (str(sdoc.get("policy_ref", "")), [str(t.get("digest", "")) for t in (sdoc.get("targets") or []) if isinstance(t, dict) and t.get("digest")])
  except Exception:
   pass
 envelopes = []
 for sf in sig_files:
  doc = decode_fn(sf.read_text("utf-8"))
  if not isinstance(doc, dict) or set(doc) != sig_env_keys or doc.get("schema") != "drift.signature-envelope/1":
   raise ValueError("sig_env")
  pl, sig_arm = doc.get("payload"), str(doc.get("signature", "")).strip()
  if not isinstance(pl, dict) or not sig_arm.startswith("-----BEGIN SSH SIGNATURE-----"):
   raise ValueError("sig_payload")
  if pl.get("schema") == "drift.signature-payload/2":
   st = pl.get("surface_tier")
   if set(pl) != v2_keys or pl.get("target_kind") != "review_snapshot" or pl.get("class") not in req_tier_map or isinstance(st, bool) or not isinstance(st, int) or st not in (0, 1, 2) or not SHA256_REF_RE.match(str(pl.get("packet_ref", ""))):
    raise ValueError("sig_payload")
   norm_pl: dict[str, Any] = {k: (st if k == "surface_tier" else str(pl[k]).strip()) for k in v2_keys}
   if any(k != "surface_tier" and not norm_pl[k] for k in v2_keys):
    raise ValueError("sig_fields")
  elif set(pl) == sig_payload_keys and pl.get("schema") == "drift.signature-payload/1":
   norm_pl = {k: str(pl[k]).strip() for k in sig_payload_keys}
   if any(not norm_pl[k] for k in sig_payload_keys) or norm_pl["target_kind"] not in ("contract", "review_snapshot", "attestation", "pact_lock", "shard_bundle"):
    raise ValueError("sig_fields")
  else:
   raise ValueError("sig_payload")
  envelopes.append((norm_pl, sig_arm))
 pol_spec = {"active": False, "required_meanings": [], "min_signers": 1, "distinct_signers": True, "enforce": "release"}
 if sig_pol_file:
  if not sig_pol_file.is_file():
   raise ValueError("missing_sig_policy")
  pdoc = decode_fn(sig_pol_file.read_text("utf-8"))
  if not isinstance(pdoc, dict) or pdoc.get("schema") != "drift.signature-policy/1":
   raise ValueError("invalid_sig_policy")
  enf = str(pdoc.get("enforce", "release")).strip()
  pol_spec = {"active": True, "required_meanings": [str(x).strip() for x in (pdoc.get("required_meanings") or []) if str(x).strip()], "min_signers": max(1, int(pdoc.get("min_signers", 1))), "distinct_signers": bool(pdoc.get("distinct_signers", True)), "enforce": (enf if enf in ("execution", "release") else "release")}
 if not pol_spec["active"] and not any(((pl["target_kind"] == "contract" and pl["schema"] == "drift.signature-payload/1") or (pl["target_kind"] == "review_snapshot" and pl["schema"] == "drift.signature-payload/2")) and pl["meaning"] != "break_glass" for pl, _ in envelopes):
  return verdicts
 by_id, phase = {c["id"]: c for c in parsed_contracts}, (getattr(args, "phase", "") or "")
 enforced_now = phase == "release" or (pol_spec["active"] and pol_spec["enforce"] == "execution")
 for v in verdicts:
  c = by_id.get(v["id"], {})
  if not enforced_now and not envelopes:
   v["signature_verification"] = {"ok": True, "reasons": [], "signatures": [], "status": "pending_release", "total": 0}
   continue
  ctrls_m = c.get("controls") or {}
  exp_ctx = next((str(ctrls_m[k].get("context_ref", "")).strip() for k in sorted(ctrls_m) if isinstance(ctrls_m[k], dict) and str(ctrls_m[k].get("context_ref", "")).strip()), "")
  eval_sigs, rsn, valid_signers, cov_meanings, valid_cnt = [], [], {}, set(), 0
  has_own_env = any(pl["target_kind"] == "contract" and pl["meaning"] != "break_glass" and (digest_matches_fn(pl["target_ref"], v["digest"]) or pl["target_ref"] == v["digest"]) for pl, _ in envelopes)
  for pl, sig_txt in envelopes:
   is_v2_snap = pl["schema"] == "drift.signature-payload/2" and pl["target_kind"] == "review_snapshot"
   if (not is_v2_snap and pl["target_kind"] != "contract") or pl["meaning"] == "break_glass" or (not is_v2_snap and has_own_env and not digest_matches_fn(pl["target_ref"], v["digest"]) and pl["target_ref"] != v["digest"]):
    continue
   ok, s_rsn = verify_sig_fn(pl, sig_txt, getattr(args, "trust_root", None), getattr(args, "verify_time", ""), canonical_json_fn)
   if pl["signer"].startswith("runner:") or (is_v2_snap and pl["signer"].startswith("agent:") and pl["meaning"] == "owner_approval"):
    ok, s_rsn = False, "signature.unauthorized_role"
   elif ok and is_v2_snap:
    snap_entry = snap_by_ref.get(pl["target_ref"])
    if pl["surface_tier"] < req_tier_map[pl["class"]] or not snap_entry or not any(digest_matches_fn(d, v["digest"]) or d == v["digest"] for d in snap_entry[1]) or (cfg_dig and not digest_matches_fn(pl["policy_ref"], cfg_dig) and pl["policy_ref"] != cfg_dig and pl["policy_ref"] != snap_entry[0]):
     ok, s_rsn = False, "signature.target_mismatch"
   elif ok and ((not digest_matches_fn(pl["target_ref"], v["digest"]) and pl["target_ref"] != v["digest"]) or (cfg_dig and not digest_matches_fn(pl["policy_ref"], cfg_dig) and pl["policy_ref"] != cfg_dig) or (exp_ctx and pl["context_ref"] not in ("none", exp_ctx))):
    ok, s_rsn = False, "signature.target_mismatch"
   if ok:
    valid_cnt += 1
    valid_signers[pl["signer"]] = valid_signers.get(pl["signer"], 0) + 1
    cov_meanings.add(pl["meaning"])
   elif s_rsn and s_rsn not in rsn:
    rsn.append(s_rsn)
   eval_sigs.append({**{k: pl[k] for k in ("context_ref", "meaning", "policy_ref", "signed_at", "signer", "target_kind", "target_ref")}, "valid": ok, **({"reason": s_rsn} if s_rsn else {})})
  if pol_spec["active"]:
   for tag, cond in (("signature.duplicate_signer", pol_spec["distinct_signers"] and any(cnt > 1 for cnt in valid_signers.values())), ("signature.meaning_missing", any(m not in cov_meanings for m in pol_spec["required_meanings"])), ("signature.quorum_unmet", (len(valid_signers) if pol_spec["distinct_signers"] else valid_cnt) < pol_spec["min_signers"])):
    if cond and tag not in rsn:
     rsn.append(tag)
  elif valid_cnt == 0 and "signature.invalid" not in rsn:
   rsn.append("signature.invalid")
  if enforced_now:
   for r in rsn:
    if r not in v["reasons"]:
     v["reasons"].append(r)
   v["ok"] = not v["reasons"] and valid_cnt > 0
  v["signature_verification"] = {"ok": not rsn and valid_cnt > 0, "reasons": ([] if not enforced_now else rsn), "signatures": eval_sigs, "status": ("verified" if not rsn and valid_cnt > 0 else ("pending_release" if not enforced_now else "violated")), "total": len(eval_sigs)}
 return verdicts


__all__ = [
    "_contains_todo",
    "_has_approval_blocker",
    "_has_temporal_bounds",
    "_is_unanchored_prose_source",
    "_valid_verify_time",
    "apply_openssh_trust_verdicts",
    "evaluate_contract_parity_impl",
    "evaluate_detached_signatures_impl",
    "extract_contract_cutover",
    "load_merged_profile_impl",
    "load_parity_receipts_impl",
    "parse_subject_manifest_core",
    "validate_and_match_attestation",
    "verify_openssh_trust",
    "verify_ssh_sig_envelope_impl",
]


