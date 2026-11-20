#!/usr/bin/env python3
"""Zero-dependency TUF v1.0-aligned metadata generator and fail-closed verifier (MIT License).

Protects DRIFT release updates against rollback, freeze, mix-and-match, endless-data,
and arbitrary-package attacks using standard TUF role separation (root, timestamp,
snapshot, targets) with OpenSSH Ed25519 signatures (ssh-keygen -Y sign/verify).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SPEC_VERSION = "1.0.31"
TUF_ROLES = ("root", "timestamp", "snapshot", "targets")
ROOT_EXPIRY_DAYS = 730
TARGETS_EXPIRY_DAYS = 365
SNAPSHOT_EXPIRY_DAYS = 180
TIMESTAMP_EXPIRY_DAYS = 180
MAX_META_BYTES = {
    "root": 65536,
    "timestamp": 16384,
    "snapshot": 65536,
    "targets": 262144,
}


def _ssh_keygen() -> str:
    return shutil.which("ssh-keygen") or "/usr/bin/ssh-keygen"


def canonical_tuf_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def keyid_from_pubkey(pubkey_line: str) -> str:
    parts = pubkey_line.strip().split()
    if len(parts) < 2 or not parts[0].startswith("ssh-"):
        raise ValueError("invalid OpenSSH public key")
    normalized = f"{parts[0]} {parts[1]}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_utc(iso_ts: str) -> dt.datetime:
    if not isinstance(iso_ts, str) or not iso_ts.endswith("Z"):
        raise ValueError(f"invalid UTC timestamp: {iso_ts!r}")
    return dt.datetime.fromisoformat(iso_ts[:-1]).replace(tzinfo=dt.timezone.utc)


def format_utc(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sign_tuf_payload(signed_obj: dict[str, Any], role: str, key_path: Path, pubkey_line: str) -> dict[str, str]:
    if role not in TUF_ROLES:
        raise ValueError(f"unknown TUF role: {role}")
    payload = canonical_tuf_bytes(signed_obj)
    kid = keyid_from_pubkey(pubkey_line)
    with tempfile.TemporaryDirectory(prefix="drift-tuf-sign-") as td:
        msg_p = Path(td) / "payload.json"
        msg_p.write_bytes(payload)
        res = subprocess.run(
            [_ssh_keygen(), "-Y", "sign", "-f", str(key_path), "-n", f"drift-tuf-{role}", str(msg_p)],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise ValueError(f"ssh-keygen sign failed for {role}: {res.stderr.strip() or res.stdout.strip()}")
        sig_text = (Path(td) / "payload.json.sig").read_text(encoding="utf-8")
    return {"keyid": kid, "sig": sig_text}


def _verify_role_signatures(
    envelope: dict[str, Any],
    role: str,
    keys_map: dict[str, Any],
    role_spec: dict[str, Any],
) -> None:
    if not isinstance(envelope, dict) or not isinstance(envelope.get("signed"), dict) or not isinstance(envelope.get("signatures"), list):
        raise ValueError(f"malformed {role} TUF envelope")
    threshold = role_spec.get("threshold")
    allowed_kids = role_spec.get("keyids")
    if type(threshold) is not int or threshold < 1 or not isinstance(allowed_kids, list):
        raise ValueError(f"invalid role threshold for {role}")
    allowed_set = set(allowed_kids)
    payload = canonical_tuf_bytes(envelope["signed"])
    valid_kids: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="drift-tuf-ver-") as td:
        td_p = Path(td)
        for idx, sig_entry in enumerate(envelope["signatures"]):
            if not isinstance(sig_entry, dict):
                continue
            kid = sig_entry.get("keyid")
            sig_text = sig_entry.get("sig")
            if not isinstance(kid, str) or not isinstance(sig_text, str) or kid not in allowed_set or kid in valid_kids:
                continue
            key_info = keys_map.get(kid)
            if not isinstance(key_info, dict) or not isinstance(key_info.get("keyval"), dict):
                continue
            pub = key_info["keyval"].get("public")
            if not isinstance(pub, str) or keyid_from_pubkey(pub) != kid:
                continue
            principal = f"tuf-{role}-{kid[:16]}@drift"
            signers_p = td_p / f"signers-{idx}"
            sig_p = td_p / f"sig-{idx}.sig"
            signers_p.write_text(f"{principal} {pub.strip()}\n", encoding="utf-8")
            sig_p.write_text(sig_text, encoding="utf-8")
            res = subprocess.run(
                [_ssh_keygen(), "-Y", "verify", "-f", str(signers_p), "-I", principal, "-n", f"drift-tuf-{role}", "-s", str(sig_p)],
                input=payload,
                capture_output=True,
                check=False,
            )
            if res.returncode == 0:
                valid_kids.add(kid)
    if len(valid_kids) < threshold:
        raise ValueError(f"tuf.{role}.signature_threshold: got {len(valid_kids)}, need {threshold}")


def _load_bounded_json(path: Path, role: str) -> tuple[bytes, dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"tuf.{role}.missing: {path.name}")
    raw = path.read_bytes()
    cap = MAX_META_BYTES[role]
    if len(raw) > cap:
        raise ValueError(f"tuf.{role}.too_large: {len(raw)} > {cap}")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"tuf.{role}.malformed: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("signed"), dict):
        raise ValueError(f"tuf.{role}.malformed")
    signed = doc["signed"]
    if signed.get("_type") != role:
        raise ValueError(f"tuf.{role}.wrong_type: {signed.get('_type')!r}")
    ver = signed.get("version")
    if type(ver) is not int or ver < 1:
        raise ValueError(f"tuf.{role}.invalid_version: {ver!r}")
    return raw, doc


def is_root_provisioned(root_path: Path) -> bool:
    if not root_path.is_file():
        return False
    try:
        doc = json.loads(root_path.read_text(encoding="utf-8"))
        signed = doc.get("signed", {})
        return type(signed.get("version")) is int and signed["version"] >= 1 and bool(signed.get("keys"))
    except (OSError, ValueError):
        return False


def create_signed_root(
    root_key: Path,
    root_pub: str,
    role_pubs: dict[str, list[str]],
    *,
    version: int = 1,
    expires_days: int = ROOT_EXPIRY_DAYS,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now_dt = now or dt.datetime.now(dt.timezone.utc)
    keys_map: dict[str, Any] = {}
    roles_map: dict[str, Any] = {}
    all_role_pubs = {"root": [root_pub], **role_pubs}
    for role in TUF_ROLES:
        pubs = all_role_pubs.get(role) or []
        if not pubs:
            raise ValueError(f"missing public key(s) for TUF role {role}")
        kids: list[str] = []
        for pub in pubs:
            parts = pub.strip().split()
            norm = f"{parts[0]} {parts[1]}"
            kid = keyid_from_pubkey(norm)
            keys_map[kid] = {"keytype": parts[0], "scheme": "openssh-sshsig", "keyval": {"public": norm}}
            if kid not in kids:
                kids.append(kid)
        roles_map[role] = {"keyids": kids, "threshold": 1}
    signed = {
        "_type": "root",
        "spec_version": SPEC_VERSION,
        "consistent_snapshot": True,
        "version": version,
        "expires": format_utc(now_dt + dt.timedelta(days=expires_days)),
        "keys": keys_map,
        "roles": roles_map,
    }
    return {"signed": signed, "signatures": [sign_tuf_payload(signed, "root", root_key, root_pub)]}


def rotate_signed_root(
    prev_root_envelope: dict[str, Any],
    prev_root_key: Path,
    prev_root_pub: str,
    new_root_key: Path,
    new_root_pub: str,
    role_pubs: dict[str, list[str]],
    *,
    expires_days: int = ROOT_EXPIRY_DAYS,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    prev_ver = int(prev_root_envelope["signed"]["version"])
    next_env = create_signed_root(
        new_root_key,
        new_root_pub,
        role_pubs,
        version=prev_ver + 1,
        expires_days=expires_days,
        now=now,
    )
    prev_sig = sign_tuf_payload(next_env["signed"], "root", prev_root_key, prev_root_pub)
    if prev_sig["keyid"] != next_env["signatures"][0]["keyid"]:
        next_env["signatures"].append(prev_sig)
    return next_env


def generate_tuf_release_metadata(
    root_envelope: dict[str, Any],
    assets_dir: Path,
    release_version: str,
    out_dir: Path,
    role_keys: dict[str, tuple[Path, str]],
    *,
    meta_version: int = 1,
    now: dt.datetime | None = None,
) -> dict[str, Path]:
    now_dt = now or dt.datetime.now(dt.timezone.utc)
    out_dir.mkdir(parents=True, exist_ok=True)
    targets_map: dict[str, Any] = {}
    for p in sorted(assets_dir.iterdir()):
        if not p.is_file() or p.name.startswith("tuf-"):
            continue
        raw = p.read_bytes()
        targets_map[p.name] = {
            "length": len(raw),
            "hashes": {"sha256": hashlib.sha256(raw).hexdigest()},
            "custom": {
                "version": release_version,
                "channel": "stable",
                "release_tag": f"v{release_version}",
            },
        }
    if not targets_map:
        raise ValueError(f"no release assets found in {assets_dir}")

    targets_signed = {
        "_type": "targets",
        "spec_version": SPEC_VERSION,
        "version": meta_version,
        "expires": format_utc(now_dt + dt.timedelta(days=TARGETS_EXPIRY_DAYS)),
        "targets": targets_map,
    }
    t_key, t_pub = role_keys["targets"]
    targets_env = {"signed": targets_signed, "signatures": [sign_tuf_payload(targets_signed, "targets", t_key, t_pub)]}
    targets_bytes = json.dumps(targets_env, indent=2, sort_keys=True).encode("utf-8") + b"\n"

    snapshot_signed = {
        "_type": "snapshot",
        "spec_version": SPEC_VERSION,
        "version": meta_version,
        "expires": format_utc(now_dt + dt.timedelta(days=SNAPSHOT_EXPIRY_DAYS)),
        "meta": {
            "targets.json": {
                "version": meta_version,
                "length": len(targets_bytes),
                "hashes": {"sha256": hashlib.sha256(targets_bytes).hexdigest()},
            }
        },
    }
    s_key, s_pub = role_keys["snapshot"]
    snapshot_env = {"signed": snapshot_signed, "signatures": [sign_tuf_payload(snapshot_signed, "snapshot", s_key, s_pub)]}
    snapshot_bytes = json.dumps(snapshot_env, indent=2, sort_keys=True).encode("utf-8") + b"\n"

    timestamp_signed = {
        "_type": "timestamp",
        "spec_version": SPEC_VERSION,
        "version": meta_version,
        "expires": format_utc(now_dt + dt.timedelta(days=TIMESTAMP_EXPIRY_DAYS)),
        "snapshot_meta": {
            "version": meta_version,
            "length": len(snapshot_bytes),
            "hashes": {"sha256": hashlib.sha256(snapshot_bytes).hexdigest()},
        },
    }
    ts_key, ts_pub = role_keys["timestamp"]
    timestamp_env = {"signed": timestamp_signed, "signatures": [sign_tuf_payload(timestamp_signed, "timestamp", ts_key, ts_pub)]}
    timestamp_bytes = json.dumps(timestamp_env, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    root_bytes = json.dumps(root_envelope, indent=2, sort_keys=True).encode("utf-8") + b"\n"

    written = {
        "root": out_dir / "tuf-root.json",
        "targets": out_dir / "tuf-targets.json",
        "snapshot": out_dir / "tuf-snapshot.json",
        "timestamp": out_dir / "tuf-timestamp.json",
    }
    written["root"].write_bytes(root_bytes)
    written["targets"].write_bytes(targets_bytes)
    written["snapshot"].write_bytes(snapshot_bytes)
    written["timestamp"].write_bytes(timestamp_bytes)
    return written


def _resolve_meta_file(meta_dir: Path, role: str) -> Path:
    prefixed = meta_dir / f"tuf-{role}.json"
    plain = meta_dir / f"{role}.json"
    return prefixed if prefixed.is_file() else plain


def verify_tuf_update(
    trusted_root_path: Path,
    meta_dir: Path,
    *,
    state_path: Path | None = None,
    target_checks: dict[str, Path] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now_dt = now or dt.datetime.now(dt.timezone.utc)
    _, trusted_root = _load_bounded_json(trusted_root_path, "root")
    tr_signed = trusted_root["signed"]
    _verify_role_signatures(trusted_root, "root", tr_signed["keys"], tr_signed["roles"]["root"])

    active_root = trusted_root
    candidate_root_p = _resolve_meta_file(meta_dir, "root")
    if candidate_root_p.is_file() and candidate_root_p.resolve() != trusted_root_path.resolve():
        _, cand_root = _load_bounded_json(candidate_root_p, "root")
        cs = cand_root["signed"]
        if cs["version"] < tr_signed["version"]:
            raise ValueError(f"tuf.root.rollback: {cs['version']} < {tr_signed['version']}")
        if cs["version"] > tr_signed["version"]:
            if cs["version"] != tr_signed["version"] + 1:
                raise ValueError(f"tuf.root.non_contiguous_rotation: {tr_signed['version']} -> {cs['version']}")
            _verify_role_signatures(cand_root, "root", tr_signed["keys"], tr_signed["roles"]["root"])
            _verify_role_signatures(cand_root, "root", cs["keys"], cs["roles"]["root"])
            active_root = cand_root
        elif canonical_tuf_bytes(cs) != canonical_tuf_bytes(tr_signed):
            raise ValueError("tuf.root.equivocation: same version with different payload")

    root_signed = active_root["signed"]
    if parse_utc(root_signed["expires"]) <= now_dt:
        raise ValueError("tuf.root.expired")
    keys_map, roles_map = root_signed["keys"], root_signed["roles"]

    prev_state: dict[str, int] = {}
    if state_path is not None and state_path.is_file():
        prev_state = json.loads(state_path.read_text(encoding="utf-8"))

    # 1. Timestamp (anti-freeze + anti-rollback)
    _, ts_doc = _load_bounded_json(_resolve_meta_file(meta_dir, "timestamp"), "timestamp")
    _verify_role_signatures(ts_doc, "timestamp", keys_map, roles_map["timestamp"])
    ts_signed = ts_doc["signed"]
    if parse_utc(ts_signed["expires"]) <= now_dt:
        raise ValueError("tuf.timestamp.expired")
    if ts_signed["version"] < prev_state.get("timestamp_version", 0):
        raise ValueError(f"tuf.timestamp.rollback: {ts_signed['version']} < {prev_state['timestamp_version']}")
    snap_meta = ts_signed.get("snapshot_meta")
    if not isinstance(snap_meta, dict) or not isinstance(snap_meta.get("hashes"), dict):
        raise ValueError("tuf.timestamp.malformed_snapshot_meta")

    # 2. Snapshot (anti-mix-and-match + anti-rollback)
    snap_raw, snap_doc = _load_bounded_json(_resolve_meta_file(meta_dir, "snapshot"), "snapshot")
    if len(snap_raw) != snap_meta.get("length") or hashlib.sha256(snap_raw).hexdigest() != snap_meta["hashes"].get("sha256"):
        raise ValueError("tuf.snapshot.hash_mismatch")
    _verify_role_signatures(snap_doc, "snapshot", keys_map, roles_map["snapshot"])
    snap_signed = snap_doc["signed"]
    if snap_signed["version"] != snap_meta.get("version"):
        raise ValueError("tuf.snapshot.version_mismatch")
    if parse_utc(snap_signed["expires"]) <= now_dt:
        raise ValueError("tuf.snapshot.expired")
    if snap_signed["version"] < prev_state.get("snapshot_version", 0):
        raise ValueError(f"tuf.snapshot.rollback: {snap_signed['version']} < {prev_state['snapshot_version']}")
    tgt_meta = (snap_signed.get("meta") or {}).get("targets.json")
    if not isinstance(tgt_meta, dict) or not isinstance(tgt_meta.get("hashes"), dict):
        raise ValueError("tuf.snapshot.missing_targets_meta")

    # 3. Targets (anti-mix-and-match + anti-rollback)
    tgt_raw, tgt_doc = _load_bounded_json(_resolve_meta_file(meta_dir, "targets"), "targets")
    if len(tgt_raw) != tgt_meta.get("length") or hashlib.sha256(tgt_raw).hexdigest() != tgt_meta["hashes"].get("sha256"):
        raise ValueError("tuf.targets.hash_mismatch")
    _verify_role_signatures(tgt_doc, "targets", keys_map, roles_map["targets"])
    tgt_signed = tgt_doc["signed"]
    if tgt_signed["version"] != tgt_meta.get("version"):
        raise ValueError("tuf.targets.version_mismatch")
    if parse_utc(tgt_signed["expires"]) <= now_dt:
        raise ValueError("tuf.targets.expired")
    if tgt_signed["version"] < prev_state.get("targets_version", 0):
        raise ValueError(f"tuf.targets.rollback: {tgt_signed['version']} < {prev_state['targets_version']}")

    targets = tgt_signed.get("targets")
    if not isinstance(targets, dict):
        raise ValueError("tuf.targets.malformed")

    # 4. Target artifact verification
    for target_name, artifact_path in (target_checks or {}).items():
        entry = targets.get(target_name)
        if not isinstance(entry, dict) or not isinstance(entry.get("hashes"), dict):
            raise ValueError(f"tuf.target.unknown: {target_name}")
        if not artifact_path.is_file():
            raise ValueError(f"tuf.target.missing_file: {artifact_path}")
        art_raw = artifact_path.read_bytes()
        if len(art_raw) != entry.get("length") or hashlib.sha256(art_raw).hexdigest() != entry["hashes"].get("sha256"):
            raise ValueError(f"tuf.target.hash_mismatch: {target_name}")

    new_state = {
        "root_version": root_signed["version"],
        "timestamp_version": ts_signed["version"],
        "snapshot_version": snap_signed["version"],
        "targets_version": tgt_signed["version"],
    }
    if state_path is not None:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(new_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {"ok": True, "state": new_state, "targets": targets}


def _gen_ed25519(dst: Path) -> tuple[Path, str]:
    subprocess.run([_ssh_keygen(), "-q", "-t", "ed25519", "-N", "", "-f", str(dst)], check=True)
    pub = Path(f"{dst}.pub").read_text(encoding="utf-8").strip()
    return dst, pub


def run_self_test() -> int:
    fixed_now = dt.datetime(2026, 11, 20, 0, 0, 0, tzinfo=dt.timezone.utc)
    with tempfile.TemporaryDirectory(prefix="drift-tuf-selftest-") as td:
        tp = Path(td)
        keys_dir, assets_dir, meta_dir = tp / "keys", tp / "assets", tp / "meta"
        keys_dir.mkdir()
        assets_dir.mkdir()
        r_key, r_pub = _gen_ed25519(keys_dir / "root")
        ts_key, ts_pub = _gen_ed25519(keys_dir / "timestamp")
        s_key, s_pub = _gen_ed25519(keys_dir / "snapshot")
        t_key, t_pub = _gen_ed25519(keys_dir / "targets")
        rogue_key, rogue_pub = _gen_ed25519(keys_dir / "rogue")

        root_env = create_signed_root(r_key, r_pub, {"timestamp": [ts_pub], "snapshot": [s_pub], "targets": [t_pub]}, now=fixed_now)
        trusted_root = tp / "trusted-root.json"
        trusted_root.write_text(json.dumps(root_env, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        arc = assets_dir / "drift-0.8.1-linux-x64.tar.gz"
        arc.write_bytes(b"deterministic-release-bytes")
        role_keys = {"timestamp": (ts_key, ts_pub), "snapshot": (s_key, s_pub), "targets": (t_key, t_pub)}
        generate_tuf_release_metadata(root_env, assets_dir, "0.8.1", meta_dir, role_keys, meta_version=2, now=fixed_now)

        state_p = tp / "state.json"
        res = verify_tuf_update(trusted_root, meta_dir, state_path=state_p, target_checks={arc.name: arc}, now=fixed_now)
        assert res["ok"] is True and res["state"]["targets_version"] == 2

        # 1. Freeze attack (expired timestamp beyond 180-day window)
        try:
            verify_tuf_update(trusted_root, meta_dir, now=fixed_now + dt.timedelta(days=TIMESTAMP_EXPIRY_DAYS + 1))
            raise AssertionError("expected expired timestamp rejection")
        except ValueError as exc:
            assert "tuf.timestamp.expired" in str(exc), exc

        # 1b. Contiguous root rotation (v1 -> v2 signed by both old and new root keys)
        r2_key, r2_pub = _gen_ed25519(keys_dir / "root_v2")
        rot_root = rotate_signed_root(
            root_env, r_key, r_pub, r2_key, r2_pub,
            {"timestamp": [ts_pub], "snapshot": [s_pub], "targets": [t_pub]},
            now=fixed_now,
        )
        rot_dir = tp / "rotated"
        generate_tuf_release_metadata(rot_root, assets_dir, "0.8.2", rot_dir, role_keys, meta_version=3, now=fixed_now)
        rot_res = verify_tuf_update(trusted_root, rot_dir, target_checks={arc.name: arc}, now=fixed_now)
        assert rot_res["ok"] is True and rot_res["state"]["root_version"] == 2

        # 2. Rollback attack (version 1 after state recorded version 2)
        rb_dir = tp / "rollback"
        generate_tuf_release_metadata(root_env, assets_dir, "0.8.0", rb_dir, role_keys, meta_version=1, now=fixed_now)
        try:
            verify_tuf_update(trusted_root, rb_dir, state_path=state_p, now=fixed_now)
            raise AssertionError("expected rollback rejection")
        except ValueError as exc:
            assert "rollback" in str(exc), exc

        # 3. Mix-and-match attack (swap targets.json from another build)
        mm_dir = tp / "mixmatch"
        shutil.copytree(meta_dir, mm_dir)
        shutil.copy2(rb_dir / "tuf-targets.json", mm_dir / "tuf-targets.json")
        try:
            verify_tuf_update(trusted_root, mm_dir, now=fixed_now)
            raise AssertionError("expected mix-and-match rejection")
        except ValueError as exc:
            assert "tuf.targets.hash_mismatch" in str(exc), exc

        # 4. Tampered archive bytes
        bad_arc = tp / "bad.tar.gz"
        bad_arc.write_bytes(b"tampered-bytes")
        try:
            verify_tuf_update(trusted_root, meta_dir, target_checks={arc.name: bad_arc}, now=fixed_now)
            raise AssertionError("expected target hash mismatch")
        except ValueError as exc:
            assert "tuf.target.hash_mismatch" in str(exc), exc

        # 5. Untrusted signer
        rogue_dir = tp / "rogue"
        generate_tuf_release_metadata(root_env, assets_dir, "0.8.1", rogue_dir, {**role_keys, "timestamp": (rogue_key, rogue_pub)}, meta_version=3, now=fixed_now)
        try:
            verify_tuf_update(trusted_root, rogue_dir, now=fixed_now)
            raise AssertionError("expected untrusted signer rejection")
        except ValueError as exc:
            assert "signature_threshold" in str(exc), exc

    print("tuf_verify.py self-test: ok (happy path, freeze, rollback, mix-and-match, tamper, untrusted signer)")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="tuf_verify.py")
    p.add_argument("--self-test", action="store_true")
    sub = p.add_subparsers(dest="cmd")

    vp = sub.add_parser("verify")
    vp.add_argument("--root", type=Path, required=True)
    vp.add_argument("--meta-dir", type=Path, required=True)
    vp.add_argument("--state", type=Path)
    vp.add_argument("--target")
    vp.add_argument("--file", type=Path)
    vp.add_argument("--now")

    gp = sub.add_parser("generate")
    gp.add_argument("--root", type=Path, required=True)
    gp.add_argument("--assets-dir", type=Path, required=True)
    gp.add_argument("--version", required=True)
    gp.add_argument("--out-dir", type=Path, required=True)
    gp.add_argument("--timestamp-key", type=Path, required=True)
    gp.add_argument("--snapshot-key", type=Path, required=True)
    gp.add_argument("--targets-key", type=Path, required=True)
    gp.add_argument("--meta-version", type=int, default=1)

    a = p.parse_args(argv)
    if a.self_test:
        return run_self_test()
    if a.cmd == "verify":
        checks = {a.target: a.file} if a.target and a.file else None
        now_dt = parse_utc(a.now) if a.now else None
        res = verify_tuf_update(a.root, a.meta_dir, state_path=a.state, target_checks=checks, now=now_dt)
        print(json.dumps(res, sort_keys=True))
        return 0
    if a.cmd == "generate":
        root_env = json.loads(a.root.read_text(encoding="utf-8"))
        role_keys = {
            r: (kp, Path(f"{kp}.pub").read_text(encoding="utf-8").strip())
            for r, kp in (("timestamp", a.timestamp_key), ("snapshot", a.snapshot_key), ("targets", a.targets_key))
        }
        written = generate_tuf_release_metadata(root_env, a.assets_dir, a.version, a.out_dir, role_keys, meta_version=a.meta_version)
        print(json.dumps({k: str(v) for k, v in written.items()}, sort_keys=True))
        return 0
    p.print_help()
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ValueError as err:
        print(f"tuf_verify: {err}", file=sys.stderr)
        sys.exit(1)
