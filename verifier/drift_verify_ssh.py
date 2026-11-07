#!/usr/bin/env python3
"""OpenSSH signature verification helper for verifier/drift_verify.py (D265)."""

import hashlib
import shutil
import subprocess
from pathlib import Path


def _valid_verify_time(ts: str) -> str:
    raw = ts.strip()
    if not raw.endswith(("Z", "z")):
        return ""
    clean = raw[:-1]
    if len(clean) != 14 or not clean.isdigit():
        return ""
    return f"{clean}Z"


def _has_temporal_bounds(text: str) -> tuple[bool, bool]:
    has_bounds = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for opt in ('valid-after="', 'valid-before="'):
            if opt in line:
                has_bounds = True
                val = line.split(opt, 1)[1].split('"', 1)[0]
                if not _valid_verify_time(val):
                    return True, True
    return has_bounds, False


def verify_openssh_trust(payload_path: Path | None, sig_path: Path | None, namespace: str, trust_root: Path | None, verify_time: str = "") -> dict:
    if trust_root is None and sig_path is None and not verify_time:
        return {"active": False}
    norm_root = trust_root.as_posix() if trust_root is not None else ""
    if trust_root is None or not trust_root.is_file() or trust_root.name == "config.toml" or norm_root.startswith(".drift/") or "/.drift/" in norm_root:
        return {
            "active": True,
            "reason": "trust.root_required",
            "trust_root_ref": "none",
            "namespace": namespace,
            "signature_valid": False,
            "signer_authorized": False,
            "human_intervention": "unattested_key_use",
        }
    trust_text = trust_root.read_text(encoding="utf-8")
    trust_ref = "sha256:" + hashlib.sha256(trust_text.strip().encode("utf-8")).hexdigest()
    has_temp, invalid_temp = _has_temporal_bounds(trust_text)
    if invalid_temp or (has_temp and not verify_time):
        return {
            "active": True,
            "reason": "trust.verify_time_required",
            "trust_root_ref": trust_ref,
            "namespace": namespace,
            "signature_valid": False,
            "signer_authorized": False,
            "human_intervention": "unattested_key_use",
        }
    v_opt = ""
    if verify_time:
        v_opt = _valid_verify_time(verify_time)
        if not v_opt:
            return {
                "active": True,
                "reason": "trust.verify_time_required",
                "trust_root_ref": trust_ref,
                "namespace": namespace,
                "signature_valid": False,
                "signer_authorized": False,
                "human_intervention": "unattested_key_use",
            }
    eff_sig = sig_path or (Path(f"{payload_path}.sig") if payload_path else None)
    if payload_path is None or not payload_path.is_file() or eff_sig is None or not eff_sig.is_file():
        return {
            "active": True,
            "reason": "trust.signature_invalid",
            "trust_root_ref": trust_ref,
            "namespace": namespace,
            "signature_valid": False,
            "signer_authorized": False,
            "human_intervention": "unattested_key_use",
        }
    ssh_keygen = shutil.which("ssh-keygen") or "/usr/bin/ssh-keygen"
    payload_bytes = payload_path.read_bytes()
    chk = subprocess.run(
        [ssh_keygen, "-Y", "check-novalidate", "-q", "-n", namespace, "-s", str(eff_sig)],
        input=payload_bytes,
        capture_output=True,
    )
    if chk.returncode != 0:
        return {
            "active": True,
            "reason": "trust.signature_invalid",
            "trust_root_ref": trust_ref,
            "namespace": namespace,
            "signature_valid": False,
            "signer_authorized": False,
            "human_intervention": "unattested_key_use",
        }
    fp_cmd = [ssh_keygen, "-Y", "find-principals", "-f", str(trust_root), "-s", str(eff_sig)]
    if v_opt:
        fp_cmd.extend(["-O", f"verify-time={v_opt}"])
    fp = subprocess.run(fp_cmd, capture_output=True, text=True)
    principals = [ln.strip() for ln in fp.stdout.strip().splitlines() if ln.strip()] if fp.returncode == 0 else []
    if not principals:
        return {
            "active": True,
            "reason": "trust.signer_unauthorized",
            "trust_root_ref": trust_ref,
            "namespace": namespace,
            "signature_valid": True,
            "signer_authorized": False,
            "human_intervention": "unattested_key_use",
        }
    verified = False
    for principal in principals:
        ver_cmd = [ssh_keygen, "-Y", "verify", "-q", "-f", str(trust_root), "-I", principal, "-n", namespace, "-s", str(eff_sig)]
        if v_opt:
            ver_cmd.extend(["-O", f"verify-time={v_opt}"])
        ver = subprocess.run(ver_cmd, input=payload_bytes, capture_output=True)
        if ver.returncode == 0:
            verified = True
            break
    if not verified:
        return {
            "active": True,
            "reason": "trust.signer_unauthorized",
            "trust_root_ref": trust_ref,
            "namespace": namespace,
            "signature_valid": True,
            "signer_authorized": False,
            "human_intervention": "unattested_key_use",
        }
    return {
        "active": True,
        "reason": "",
        "trust_root_ref": trust_ref,
        "namespace": namespace,
        "signature_valid": True,
        "signer_authorized": True,
        "human_intervention": "unattested_key_use",
        "verify_time": verify_time,
    }


def apply_openssh_trust_verdicts(verdicts: list[dict], args) -> list[dict]:
    tv = verify_openssh_trust(args.attest, args.attest_sig, "drift-attestation@v1", args.trust_root, args.verify_time)
    if tv.get("active"):
        for v in verdicts:
            if tv.get("reason") and tv["reason"] not in v["reasons"]:
                v["reasons"].append(tv["reason"])
                v["ok"] = False
            v["trust_verification"] = {k: tv[k] for k in ("trust_root_ref", "namespace", "signature_valid", "signer_authorized", "human_intervention") if k in tv}
    return verdicts

