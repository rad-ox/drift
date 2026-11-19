"""Distributed multi-machine shard-bundle, role-bound signature, break-glass, and containment verifiers (MIT License)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable

from drift_verify_base import (
    SHA256_REF_RE as _SHA256_RE,
    SNAPSHOT_RE as _SNAP_RE,
    _valid_ext_trust_root_py,
    _valid_verify_time,
    collect_receipt_files,
    valid_verify_time_py,
)
from drift_verify_ssh import verify_ssh_sig_envelope_impl

BUNDLE_DOMAIN = b"drift.shard-bundle/2\x00"
_TOK_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_DR2S_RE = re.compile(r"^dr2s:sha256:[0-9a-f]{64}$")
_PREF_RE = re.compile(r"^dr(?:1|2b):[0-9a-f]{12}$")


def _collect_bundle_files(event_paths: list[Path]) -> tuple[list[Path], dict[str, tuple[str, str]]]:
 bundles: list[Path] = []
 seen_b: set[Path] = set()
 actual_shards: dict[str, tuple[str, str]] = {}
 for ep in event_paths:
  if ep.is_dir():
   for child in sorted(ep.iterdir()):
    if child.is_file() and child.name.endswith(".bundle.json"):
     rp = child.resolve()
     if rp not in seen_b:
      seen_b.add(rp)
      bundles.append(child)
    elif child.is_file() and child.name.endswith(".jsonl"):
     meta = child.with_suffix(".meta.json")
     if meta.is_file():
      j_sha = "sha256:" + hashlib.sha256(child.read_bytes()).hexdigest()
      m_sha = "sha256:" + hashlib.sha256(meta.read_bytes()).hexdigest()
      actual_shards[child.name[:-6]] = (j_sha, m_sha)
  elif ep.is_file():
   if ep.name.endswith(".bundle.json"):
    rp = ep.resolve()
    if rp not in seen_b:
     seen_b.add(rp)
     bundles.append(ep)
   elif ep.name.endswith(".jsonl"):
    meta = ep.with_suffix(".meta.json")
    if meta.is_file():
     j_sha = "sha256:" + hashlib.sha256(ep.read_bytes()).hexdigest()
     m_sha = "sha256:" + hashlib.sha256(meta.read_bytes()).hexdigest()
     actual_shards[ep.name[:-6]] = (j_sha, m_sha)
 return bundles, actual_shards


def parse_shard_bundle_py(text: str, decode_fn: Callable[[str], Any], canon_fn: Callable[[Any], str]) -> dict[str, Any]:
 doc = decode_fn(text)
 allowed = {"schema", "attempt_id", "candidate_snapshot", "digest", "execution_ref", "fence_seq", "pack_ref", "receipts", "shards"}
 if not isinstance(doc, dict) or any(k not in allowed for k in doc) or doc.get("schema") != "drift.shard-bundle/1":
  raise ValueError("bundle")
 att, csnap, dig = doc.get("attempt_id"), doc.get("candidate_snapshot"), doc.get("digest")
 ex_ref, fseq, pref = doc.get("execution_ref"), doc.get("fence_seq"), doc.get("pack_ref")
 if not isinstance(att, str) or not _TOK_RE.match(att) or not isinstance(csnap, str) or not _SNAP_RE.match(csnap) or not isinstance(dig, str) or not _DR2S_RE.match(dig) or not isinstance(ex_ref, str) or not _SHA256_RE.match(ex_ref) or not isinstance(pref, str) or not _PREF_RE.match(pref) or not isinstance(fseq, int) or isinstance(fseq, bool) or fseq < 0:
  raise ValueError("bundle_fields")
 sh = doc.get("shards")
 if not isinstance(sh, dict) or not sh:
  raise ValueError("shards")
 for stem, pair in sh.items():
  if not isinstance(stem, str) or not _TOK_RE.match(stem) or not isinstance(pair, dict) or set(pair) != {"jsonl_sha256", "meta_sha256"} or not isinstance(pair["jsonl_sha256"], str) or not _SHA256_RE.match(pair["jsonl_sha256"]) or not isinstance(pair["meta_sha256"], str) or not _SHA256_RE.match(pair["meta_sha256"]):
   raise ValueError("shard_pair")
 if "receipts" in doc:
  rec = doc["receipts"]
  if not isinstance(rec, dict) or any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not _SHA256_RE.match(v) for k, v in rec.items()):
   raise ValueError("receipts")
 unsigned = {k: v for k, v in doc.items() if k != "digest"}
 exp_dig = "dr2s:sha256:" + hashlib.sha256(BUNDLE_DOMAIN + canon_fn(unsigned).encode("utf-8")).hexdigest()
 return {**doc, "_digest_valid": dig == exp_dig}


def evaluate_shard_bundles_py(verdicts: list[dict[str, Any]], event_paths: list[Path], event_snapshots: list[str], decode_fn: Callable[[str], Any], canon_fn: Callable[[Any], str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
 b_files, actual_shards = _collect_bundle_files(event_paths)
 if not b_files:
  return verdicts, []
 parsed_bundles: list[dict[str, Any]] = []
 invalid_schema = False
 for bf in b_files:
  try:
   parsed_bundles.append(parse_shard_bundle_py(bf.read_text("utf-8"), decode_fn, canon_fn))
  except Exception:
   invalid_schema = True
 reasons: list[str] = []
 if invalid_schema:
  reasons.append("events.invalid")
 else:
  seen_att: dict[str, str] = {}
  seen_snaps = {s for s in event_snapshots if s}
  hash_bad = False
  conflict_bad = False
  for b in parsed_bundles:
   seen_snaps.add(b["candidate_snapshot"])
   akey = f"{b['pack_ref']}\x00{b['attempt_id']}"
   if akey in seen_att:
    if seen_att[akey] != b["digest"]:
     conflict_bad = True
    elif b["_digest_valid"]:
     continue
   else:
    seen_att[akey] = b["digest"]
   if not b["_digest_valid"]:
    hash_bad = True
    continue
   for stem, pair in b["shards"].items():
    act = actual_shards.get(stem)
    if act is None or act != (pair["jsonl_sha256"], pair["meta_sha256"]):
     hash_bad = True
  if hash_bad:
   reasons.append("shard.bundle_hash_mismatch")
  if conflict_bad:
   reasons.append("shard.conflicting_bundle")
  if len(seen_snaps) > 1:
   reasons.append("shard.snapshot_mismatch")
 if reasons:
  for v in verdicts:
   for r in reasons:
    if r not in v["reasons"]:
     v["reasons"].append(r)
   v["ok"] = False
 return verdicts, parsed_bundles


def evaluate_role_signatures_py(verdicts: list[dict[str, Any]], parsed_contracts: list[dict[str, Any]], bundles: list[dict[str, Any]], args: Any, pol: dict[str, Any], cfg_dig: str, decode_fn: Callable[[str], Any], canon_fn: Callable[[Any], str], digest_matches_fn: Callable[[str, str], bool]) -> list[dict[str, Any]]:
 sig_paths = list(args.events or []) + ([args.signatures] if getattr(args, "signatures", None) else [])
 sig_files = collect_receipt_files(sig_paths, ".sig.json")
 req_owner = pol.get("pack") == "core@1" and pol.get("require_signed_approval") is True
 if not sig_files and not req_owner:
  return verdicts
 p_keys = {"schema", "signer", "meaning", "signed_at", "target_kind", "target_ref", "policy_ref", "context_ref"}
 envelopes: list[tuple[dict[str, str], str]] = []
 for sf in sig_files:
  doc = decode_fn(sf.read_text("utf-8"))
  pl, sig_arm = doc.get("payload"), str(doc.get("signature", "")).strip()
  if isinstance(pl, dict) and set(pl) == p_keys:
   envelopes.append(({k: str(pl[k]).strip() for k in p_keys}, sig_arm))
 trust_root: Path | None = getattr(args, "trust_root", None)
 verify_time: str = getattr(args, "verify_time", "") or ""
 bundle_envs = [(pl, st) for pl, st in envelopes if pl["target_kind"] == "shard_bundle"]
 runner_rsns: list[str] = []
 valid_bdigs = {b["digest"] for b in bundles if b.get("_digest_valid")}
 covered_bdigs: set[str] = set()
 for pl, sig_txt in bundle_envs:
  if not pl["signer"].startswith("runner:") or len(pl["signer"]) <= 7 or pl["meaning"] != "runner_attestation":
   if "signature.unauthorized_role" not in runner_rsns:
    runner_rsns.append("signature.unauthorized_role")
   continue
  ok, rsn = verify_ssh_sig_envelope_impl(pl, sig_txt, trust_root, verify_time, canon_fn)
  if not ok:
   if rsn and rsn not in runner_rsns:
    runner_rsns.append(rsn)
   continue
  matched = next((bd for bd in valid_bdigs if bd == pl["target_ref"] or digest_matches_fn(pl["target_ref"], bd)), "")
  if not matched:
   if "signature.target_mismatch" not in runner_rsns:
    runner_rsns.append("signature.target_mismatch")
   continue
  covered_bdigs.add(matched)
 runner_attested = bool(bundles) and not runner_rsns and len(covered_bdigs) == len(bundles)
 by_id = {c["id"]: c for c in parsed_contracts}
 for v in verdicts:
  c = by_id.get(v["id"], {})
  approver = str(c.get("approver", ""))
  adig = str(c.get("assurance_digest", ""))
  extra = list(runner_rsns)
  if req_owner:
   if not _valid_ext_trust_root_py(trust_root):
    if "trust.root_required" not in extra:
     extra.append("trust.root_required")
   else:
    found_valid = False
    o_rsns: list[str] = []
    for pl, sig_txt in envelopes:
     if pl["target_kind"] != "contract":
      continue
     m_tgt = digest_matches_fn(pl["target_ref"], v["digest"]) or pl["target_ref"] == v["digest"]
     if not m_tgt and pl["meaning"] != "owner_approval":
      continue
     if not pl["signer"].startswith("owner:") or len(pl["signer"]) <= 6:
      if (pl["meaning"] == "owner_approval" or m_tgt) and "signature.unauthorized_role" not in o_rsns:
       o_rsns.append("signature.unauthorized_role")
      continue
     if pl["meaning"] != "owner_approval":
      continue
     ok, rsn = verify_ssh_sig_envelope_impl(pl, sig_txt, trust_root, verify_time, canon_fn)
     if not ok:
      if rsn and rsn not in o_rsns:
       o_rsns.append(rsn)
      continue
     if not m_tgt or (cfg_dig and not digest_matches_fn(pl["policy_ref"], cfg_dig) and pl["policy_ref"] != cfg_dig) or (pl["context_ref"] != "none" and adig and not digest_matches_fn(pl["context_ref"], adig) and pl["context_ref"] != adig):
      if "signature.target_mismatch" not in o_rsns:
       o_rsns.append("signature.target_mismatch")
      continue
     if not approver or pl["signer"][6:] != approver:
      if "signature.owner_approval_missing" not in o_rsns:
       o_rsns.append("signature.owner_approval_missing")
      continue
     found_valid = True
    if not found_valid:
     if "signature.owner_approval_missing" not in o_rsns:
      o_rsns.append("signature.owner_approval_missing")
     for r in o_rsns:
      if r not in extra:
       extra.append(r)
  if runner_attested:
   cs = dict(v.get("claim_scope") or {})
   cs["runner_provenance"] = "attested"
   cs.setdefault("runner_isolation", "unattested")
   v["claim_scope"] = cs
  if extra:
   for r in extra:
    if r not in v["reasons"]:
     v["reasons"].append(r)
   v["ok"] = False
 return verdicts


def _iso_to_compact_utc(ts: str, valid_fn: Callable[[str], str]) -> str:
 raw = ts.strip()
 if c := valid_fn(raw):
  return c
 if len(raw) == 20 and raw.endswith(("Z", "z")) and raw[4] == "-" and raw[7] == "-" and raw[10] in ("T", "t") and raw[13] == ":" and raw[16] == ":":
  return valid_fn(raw[:4] + raw[5:7] + raw[8:10] + raw[11:13] + raw[14:16] + raw[17:19] + "Z")
 return ""


def _signer_valid_before_py(trust_text: str, signer: str, valid_fn: Callable[[str], str]) -> str:
 for raw in trust_text.splitlines():
  ln = raw.strip()
  if not ln or ln.startswith("#"):
   continue
  principals = ln.split()[0].split(",")
  if signer in principals and 'valid-before="' in ln:
   return valid_fn(ln.split('valid-before="', 1)[1].split('"', 1)[0])
 return ""


def _collect_verified_signal_refs_py(event_paths: list[Path], decode_fn: Callable[[str], Any]) -> dict[str, set[str]]:
 deps: dict[str, str] = {}
 for df in collect_receipt_files(event_paths, ".deployment.json"):
  try:
   doc = decode_fn(df.read_text("utf-8"))
   if isinstance(doc, dict) and doc.get("schema") == "drift.deployment-receipt/1":
    deps[str(doc["deployment_id"])] = str(doc["subject_ref"])
  except Exception:
   pass
 out: dict[str, set[str]] = {}
 for sf in collect_receipt_files(event_paths, ".signal.json"):
  try:
   raw_b = sf.read_bytes()
   doc = decode_fn(raw_b.decode("utf-8"))
   if isinstance(doc, dict) and doc.get("schema") == "drift.production-signal/1":
    did, sref, cid = str(doc["deployment_id"]), str(doc["subject_ref"]), str(doc["contract"])
    if deps.get(did) == sref:
     out.setdefault(cid, set()).add("sha256:" + hashlib.sha256(raw_b).hexdigest())
  except Exception:
   pass
 return out


def evaluate_break_glass_py(verdicts: list[dict[str, Any]], parsed_contracts: list[dict[str, Any]], args: Any, cfg_state: str, cfg_dig: str, decode_fn: Callable[[str], Any], canon_fn: Callable[[Any], str], digest_matches_fn: Callable[[str, str], bool]) -> list[dict[str, Any]]:
 if not getattr(args, "allow_break_glass", False):
  return verdicts
 sig_paths = list(args.events or []) + ([args.signatures] if getattr(args, "signatures", None) else [])
 sig_files = collect_receipt_files(sig_paths, ".sig.json")
 p_keys = {"schema", "signer", "meaning", "signed_at", "target_kind", "target_ref", "policy_ref", "context_ref"}
 envelopes: list[tuple[dict[str, str], str]] = []
 for sf in sig_files:
  doc = decode_fn(sf.read_text("utf-8"))
  pl, sig_arm = doc.get("payload"), str(doc.get("signature", "")).strip()
  if isinstance(pl, dict) and set(pl) == p_keys:
   envelopes.append(({k: str(pl[k]).strip() for k in p_keys}, sig_arm))
 valid_sigs = _collect_verified_signal_refs_py(list(args.events or []), decode_fn)
 trust_root: Path | None = getattr(args, "trust_root", None)
 verify_time_raw: str = getattr(args, "verify_time", "") or ""
 by_id = {c["id"]: c for c in parsed_contracts}
 for v in verdicts:
  c = by_id.get(v["id"], {})
  if v.get("approval") != "stale" or not c.get("digest") or cfg_state != "current":
   continue
  if not _valid_ext_trust_root_py(trust_root):
   if "trust.root_required" not in v["reasons"]:
    v["reasons"].append("trust.root_required")
   v["ok"] = False
   continue
  v_time = _valid_verify_time(verify_time_raw)
  if not v_time:
   if "trust.verify_time_required" not in v["reasons"]:
    v["reasons"].append("trust.verify_time_required")
   v["ok"] = False
   continue
  trust_text = trust_root.read_text("utf-8")
  bg_ok = False
  bg_rsns: list[str] = []
  for pl, sig_txt in envelopes:
   if pl["target_kind"] != "contract" or pl["meaning"] != "break_glass":
    continue
   if not digest_matches_fn(pl["target_ref"], v["digest"]) and pl["target_ref"] != v["digest"]:
    continue
   if not pl["signer"].startswith("emergency:") or len(pl["signer"]) <= 10:
    if "signature.unauthorized_role" not in bg_rsns:
     bg_rsns.append("signature.unauthorized_role")
    continue
   vb = _signer_valid_before_py(trust_text, pl["signer"], _valid_verify_time)
   if not vb:
    if "signature.unauthorized_role" not in bg_rsns:
     bg_rsns.append("signature.unauthorized_role")
    continue
   issued_utc = _iso_to_compact_utc(pl["signed_at"], _valid_verify_time)
   if not issued_utc or v_time < issued_utc:
    if "signature.invalid" not in bg_rsns:
     bg_rsns.append("signature.invalid")
    continue
   if v_time >= vb:
    if "approval.break_glass_expired" not in bg_rsns:
     bg_rsns.append("approval.break_glass_expired")
    continue
   ok, rsn = verify_ssh_sig_envelope_impl(pl, sig_txt, trust_root, v_time, canon_fn)
   if not ok:
    if rsn and rsn not in bg_rsns:
     bg_rsns.append(rsn)
    continue
   if (cfg_dig and not digest_matches_fn(pl["policy_ref"], cfg_dig) and pl["policy_ref"] != cfg_dig) or pl["context_ref"] not in valid_sigs.get(v["id"], set()):
    if "signature.target_mismatch" not in bg_rsns:
     bg_rsns.append("signature.target_mismatch")
    continue
   bg_ok = True
  if not bg_ok:
   for r in bg_rsns:
    if r not in v["reasons"]:
     v["reasons"].append(r)
   v["ok"] = False
   continue
  v["reasons"] = [r for r in v["reasons"] if r not in ("contract.findings", "contract.approval.stale", "signature.owner_approval_missing")]
  cs = dict(v.get("claim_scope") or {})
  cs["authority"] = "break_glass_pending_ratification"
  v["claim_scope"] = cs
  v["ok"] = not v["reasons"]
 return verdicts


def evaluate_containment_py(verdicts: list[dict[str, Any]], parsed_contracts: list[dict[str, Any]], events_by_contract: dict[str, list[dict[str, Any]]], digest_matches_fn: Callable[[str, str], bool]) -> list[dict[str, Any]]:
 by_id = {c["id"]: c for c in parsed_contracts}
 for v in verdicts:
  c = by_id.get(v["id"], {})
  req_c = c.get("require_containment") or []
  if not req_c:
   continue
  c_evs = [ev for ev in events_by_contract.get(v["id"], ()) if digest_matches_fn(ev["digest"], v["digest"])]
  if not c_evs or any(not set(req_c).issubset(ev.get("_containment") or set()) for ev in c_evs):
   if "containment.missing" not in v["reasons"]:
    v["reasons"].append("containment.missing")
   v["ok"] = False
  else:
   cs = dict(v.get("claim_scope") or {})
   cs["runner_containment"] = "enforced"
   v["claim_scope"] = cs
 return verdicts


__all__ = [
    "_collect_bundle_files",
    "_collect_verified_signal_refs_py",
    "_iso_to_compact_utc",
    "_signer_valid_before_py",
    "evaluate_break_glass_py",
    "evaluate_containment_py",
    "evaluate_role_signatures_py",
    "evaluate_shard_bundles_py",
    "parse_shard_bundle_py",
    "valid_verify_time_py",
]


