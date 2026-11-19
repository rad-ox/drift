#!/usr/bin/env python3
"""Pact lock/ack JSON parsers and bilateral OpenSSH quorum signature verifier."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from drift_verify_base import ID_RE, SHA256_REF_RE, _has_temporal_bounds, _valid_verify_time, ssh_keygen_executable
from drift_verify_pact_cells import _canon_pretty_py, _extract_sshsig_fp_py, _parse_pact_ack_py, _when_meet_py

PACT_LOCK_SCHEMA = "drift.pact-lock/1"
PACT_LOCK_DOMAIN = b"drift.pact-lock/2\x00"
SIG_NAMESPACE = "drift-signature@v1"

DR2P_FULL_RE = re.compile(r"^dr2p:sha256:[0-9a-f]{64}$")
DR2P_REF_RE = re.compile(r"^dr2p:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})$")
DR2R_FULL_RE = re.compile(r"^dr2r:sha256:[0-9a-f]{64}$")


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _parse_pact_lock_py(text: str, decode_fn: Callable[[str], Any], canon_fn: Callable[[Any], str], jcs_str_fn: Callable[[str], str], jcs_num_fn: Callable[[Any], str]) -> dict[str, Any]:
    doc = decode_fn(text)
    if not isinstance(doc, dict):
        raise ValueError("object")
    allowed = {"schema", "pact_id", "revision", "supersedes", "deploy_order", "policy_ref", "producer", "consumer", "seams", "obligations", "seam_metrics", "digest"}
    req = {"schema", "pact_id", "revision", "deploy_order", "policy_ref", "producer", "consumer", "seams", "obligations", "seam_metrics", "digest"}
    if any(k not in allowed for k in doc) or not req.issubset(doc):
        raise ValueError("keys")
    if doc["schema"] != PACT_LOCK_SCHEMA or not isinstance(doc["pact_id"], str) or not ID_RE.match(doc["pact_id"]):
        raise ValueError("header")
    rev = doc["revision"]
    if not _is_int(rev) or rev < 1:
        raise ValueError("revision")
    if "supersedes" in doc:
        if rev == 1 or not isinstance(doc["supersedes"], str) or not DR2P_REF_RE.match(doc["supersedes"]):
            raise ValueError("supersedes")
    elif rev > 1:
        raise ValueError("supersedes_missing")
    if doc["deploy_order"] not in ("initial", "none", "producer_first", "consumer_first", "two_step_expand_contract"):
        raise ValueError("deploy_order")
    if not isinstance(doc["policy_ref"], str) or not SHA256_REF_RE.match(doc["policy_ref"]):
        raise ValueError("policy_ref")
    if not isinstance(doc["digest"], str) or not DR2P_FULL_RE.match(doc["digest"]):
        raise ValueError("digest")
    for pk, exp_role in (("producer", "producer"), ("consumer", "consumer")):
        pm = doc[pk]
        if not isinstance(pm, dict) or pm.get("role") != exp_role or not isinstance(pm.get("area_id"), str) or not pm["area_id"].strip() or not _is_int(pm.get("attested_max_direct_slices")) or pm["attested_max_direct_slices"] < 1:
            raise ValueError(pk)
    if not isinstance(doc["seams"], list) or not doc["seams"]:
        raise ValueError("seams")
    for sm in doc["seams"]:
        if not isinstance(sm, dict) or sm.get("kind") not in ("behavior.request", "behavior.event") or not isinstance(sm.get("clauses"), list) or not sm["clauses"] or not isinstance(sm.get("operations"), dict):
            raise ValueError("seam")
        ops = sm["operations"]
        dl, cap, sz, dv = ops.get("deadline", {}), ops.get("capacity", {}), ops.get("size", {}), ops.get("delivery", {})
        if any(not _is_int(v) or v < 0 for v in (dl.get("attempt_timeout_ns"), dl.get("backoff_total_ns"), dl.get("caller_deadline_ns"), dl.get("wire_reserve_ns"), cap.get("sustained_rps"), cap.get("burst"), cap.get("max_concurrency"), sz.get("max_request_bytes"), sz.get("max_response_bytes"), sz.get("max_items"), dv.get("idempotency_retention_ns"), dv.get("max_retry_horizon_ns"))) or not _is_int(dl.get("max_attempts")) or dl["max_attempts"] < 1:
            raise ValueError("ops")
        cls = sm["clauses"]
        for i in range(len(cls)):
            for j in range(i + 1, len(cls)):
                if _when_meet_py(cls[i].get("when", {}), cls[j].get("when", {})) is not None:
                    raise ValueError("disjoint")
    if not isinstance(doc["obligations"], dict) or any(not isinstance(ov, str) or not DR2R_FULL_RE.match(ov) for ov in doc["obligations"].values()):
        raise ValueError("obligations")
    if not isinstance(doc["seam_metrics"], dict) or any(not _is_int(mv) for mv in doc["seam_metrics"].values()):
        raise ValueError("seam_metrics")
    norm_txt = text.replace("\r\n", "\n").rstrip("\n")
    if _canon_pretty_py(doc, jcs_str_fn, jcs_num_fn) != norm_txt:
        raise ValueError("non_canonical")
    unsigned = {k: v for k, v in doc.items() if k != "digest"}
    exp_dg = "dr2p:sha256:" + hashlib.sha256(PACT_LOCK_DOMAIN + canon_fn(unsigned).encode("utf-8")).hexdigest()
    if exp_dg != doc["digest"]:
        raise ValueError("digest_mismatch")
    return doc


def _verify_pact_sigs_py(lock_path: Path, plock: dict[str, Any], trust_root: Path | None, verify_time: str, decode_fn: Callable[[str], Any], canon_fn: Callable[[Any], str], digest_matches_fn: Callable[[str, str], bool]) -> tuple[list[str], bool]:
    parent, base = lock_path.resolve().parent, lock_path.name
    sig_files = sorted(f for f in parent.iterdir() if not f.is_symlink() and f.is_file() and f.name.startswith(base + ".") and f.name.endswith(".sig.json")) if parent.is_dir() else []
    if not sig_files:
        return (["pact.quorum_missing"], True) if trust_root is not None else ([], False)
    reasons: list[str] = []
    meanings_ok: dict[str, tuple[str, str]] = {}
    ssh_keygen = ssh_keygen_executable()
    for sf in sig_files:
        try:
            env_doc = decode_fn(sf.read_text("utf-8"))
            pm = env_doc["payload"]
            armored = str(env_doc["signature"]).strip()
            pk_fp = _extract_sshsig_fp_py(armored)
            if env_doc.get("schema") != "drift.signature-envelope/1" or not pk_fp or pm.get("schema") != "drift.signature-payload/1" or pm.get("target_kind") != "pact_lock":
                raise ValueError("sig_env")
            signer, meaning, tref, pref = str(pm["signer"]).strip(), str(pm["meaning"]).strip(), str(pm["target_ref"]).strip(), str(pm["policy_ref"]).strip()
            payload_raw = canon_fn({"context_ref": str(pm.get("context_ref", "")).strip(), "meaning": meaning, "policy_ref": pref, "schema": "drift.signature-payload/1", "signed_at": str(pm.get("signed_at", "")).strip(), "signer": signer, "target_kind": "pact_lock", "target_ref": tref}).encode("utf-8")
        except Exception:
            if "pact.signature_invalid" not in reasons:
                reasons.append("pact.signature_invalid")
            continue
        if not digest_matches_fn(tref, plock["digest"]) or pref != plock["policy_ref"]:
            if "pact.signature_invalid" not in reasons:
                reasons.append("pact.signature_invalid")
            continue
        party_keys = plock["producer"].get("authorized_keys", []) if meaning == "pact.producer" else (plock["consumer"].get("authorized_keys", []) if meaning == "pact.consumer" else [])
        if party_keys and pk_fp not in party_keys and signer not in party_keys:
            if "pact.signer_unauthorized" not in reasons:
                reasons.append("pact.signer_unauthorized")
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".sig", encoding="utf-8", delete=False) as tf:
            tf.write(armored + "\n")
            tmp_sig = tf.name
        try:
            if subprocess.run([ssh_keygen, "-Y", "check-novalidate", "-q", "-n", SIG_NAMESPACE, "-s", tmp_sig], input=payload_raw, capture_output=True).returncode != 0:
                if "pact.signature_invalid" not in reasons:
                    reasons.append("pact.signature_invalid")
                continue
            if trust_root is not None:
                norm_r = trust_root.as_posix()
                if trust_root.is_symlink() or not trust_root.is_file() or trust_root.name == "config.toml" or norm_r.startswith(".drift/") or "/.drift/" in norm_r:
                    if "trust.root_required" not in reasons:
                        reasons.append("trust.root_required")
                    continue
                has_temp, invalid_temp = _has_temporal_bounds(trust_root.read_text("utf-8"))
                v_opt = _valid_verify_time(verify_time) if verify_time else ""
                if invalid_temp or (has_temp and not verify_time) or (verify_time and not v_opt):
                    if "trust.verify_time_required" not in reasons:
                        reasons.append("trust.verify_time_required")
                    continue
                vf_cmd = [ssh_keygen, "-Y", "verify", "-q", "-f", str(trust_root), "-I", signer, "-n", SIG_NAMESPACE, "-s", tmp_sig, *(["-O", f"verify-time={v_opt}"] if v_opt else [])]
                if subprocess.run(vf_cmd, input=payload_raw, capture_output=True).returncode != 0:
                    if "pact.signer_unauthorized" not in reasons:
                        reasons.append("pact.signer_unauthorized")
                    continue
        finally:
            try:
                os.remove(tmp_sig)
            except OSError:
                pass
        if meanings_ok.get(meaning) == (signer, pk_fp):
            continue
        if any(mk != meaning and (ex_s == signer or ex_fp == pk_fp) for mk, (ex_s, ex_fp) in meanings_ok.items()):
            if "pact.quorum_missing" not in reasons:
                reasons.append("pact.quorum_missing")
            continue
        meanings_ok[meaning] = (signer, pk_fp)
    if not reasons and ("pact.producer" not in meanings_ok or "pact.consumer" not in meanings_ok):
        reasons.append("pact.quorum_missing")
    return reasons, True


__all__ = ["_parse_pact_ack_py", "_parse_pact_lock_py", "_verify_pact_sigs_py"]
