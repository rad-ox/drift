#!/usr/bin/env python3
"""OpenSSH signature verification helper for verifier/drift_verify.py (D265)."""

import hashlib
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Callable

SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ATTEST_TOP_KEYS = frozenset(("version", "predicate_type", "ok", "configs", "contracts", "evidence"))
ATTEST_CFG_KEYS = frozenset(("approval", "digest", "file", "ref"))
ATTEST_CONTRACT_REQ = frozenset(("approval", "bound", "digest", "file", "id", "ok", "reasons", "ref", "reused", "verified"))
ATTEST_CONTRACT_OPT = frozenset(("claim_scope", "formal_checks", "migration_checks", "parity_checks", "performance", "production_signals", "security_checks"))
ATTEST_EVIDENCE_REQ = frozenset(("event_shards", "snapshots", "snapshots_complete"))
ATTEST_EVIDENCE_OPT = frozenset(("incomplete_shards", "mutations_manifest", "performance_environments", "performance_manifest", "performance_run_id", "performance_subject"))


def load_merged_profile_impl(prof_ref: str, profiles_dir: Path, proof_rank_fn: Callable[[str], int]) -> dict[str, Any]:
    p0 = profiles_dir / f"{prof_ref}.toml"
    if not prof_ref or not p0.is_file():
        return {}
    prof = tomllib.loads(p0.read_text(encoding="utf-8"))
    prof.pop("concepts", None)
    exts = prof.pop("extends", None)
    if not isinstance(exts, list) or not exts:
        return prof
    m, vw, vt, prm, pw, pt, req, cs, dc, inv = {"drift": prof.get("drift", "0.2"), "profile": prof.get("profile", prof_ref)}, [], [], {}, {}, {}, {}, {}, {}, {}
    for r in [*exts, prof_ref]:
        bp = prof if r == prof_ref else (tomllib.loads(p.read_text(encoding="utf-8")) if (p := profiles_dir / f"{r}.toml").is_file() else {})
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
    if payload_path is None and trust_root is None and sig_path is None and not verify_time:
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


def _is_non_bool_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def validate_and_match_attestation(
    payload_path: Path | None,
    verdicts: list[dict[str, Any]],
    cfg_state: str = "",
    cfg_digest: str = "",
    shard_hashes: list[str] | None = None,
    snapshots: list[str] | None = None,
    snapshots_complete: bool | None = None,
    incomplete_shards: int = 0,
    m_man: dict[str, Any] | None = None,
    perf_b: dict[str, Any] | None = None,
    decode_fn: Callable[[str], Any] | None = None,
) -> tuple[bool, str]:
    if payload_path is None or not payload_path.is_file():
        return False, "trust.attestation_invalid"
    parser = decode_fn or json.loads
    try:
        doc = parser(payload_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "trust.attestation_invalid"
    if not isinstance(doc, dict) or set(doc) != ATTEST_TOP_KEYS:
        return False, "trust.attestation_invalid"
    if doc.get("version") != 1 or isinstance(doc.get("version"), bool) or doc.get("predicate_type") != "https://drift.dev/attestation/gate/v1" or not isinstance(doc.get("ok"), bool):
        return False, "trust.attestation_invalid"
    cfgs, cnts, ev = doc.get("configs"), doc.get("contracts"), doc.get("evidence")
    if not isinstance(cfgs, list) or not cfgs or not isinstance(cnts, list) or not cnts or not isinstance(ev, dict):
        return False, "trust.attestation_invalid"
    for c in cfgs:
        if not isinstance(c, dict) or set(c) != ATTEST_CFG_KEYS or not all(isinstance(c[k], str) for k in ATTEST_CFG_KEYS):
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
    if "incomplete_shards" in ev and not _is_non_bool_int(ev["incomplete_shards"]):
        return False, "trust.attestation_invalid"
    if "mutations_manifest" in ev and (not isinstance(ev["mutations_manifest"], str) or not SHA256_REF_RE.match(ev["mutations_manifest"])):
        return False, "trust.attestation_invalid"
    by_id: dict[str, dict[str, Any]] = {}
    for c in cnts:
        if not isinstance(c, dict) or not ATTEST_CONTRACT_REQ.issubset(c) or any(k not in (ATTEST_CONTRACT_REQ | ATTEST_CONTRACT_OPT) for k in c):
            return False, "trust.attestation_invalid"
        if not all(isinstance(c[k], str) for k in ("approval", "digest", "file", "id", "ref")) or not isinstance(c["ok"], bool):
            return False, "trust.attestation_invalid"
        if not all(_is_non_bool_int(c[k]) for k in ("bound", "reused", "verified")):
            return False, "trust.attestation_invalid"
        if not isinstance(c["reasons"], list) or not all(isinstance(r, str) for r in c["reasons"]) or c["id"] in by_id:
            return False, "trust.attestation_invalid"
        by_id[c["id"]] = c

    if cfg_digest:
        if not any(c["digest"] == cfg_digest and c["approval"] == cfg_state for c in cfgs):
            return False, "trust.subject_mismatch"
    if shard_hashes is not None and sorted(att_shard_hashes) != sorted(shard_hashes):
        return False, "trust.subject_mismatch"
    if snapshots is not None and ev_snaps != list(snapshots):
        return False, "trust.subject_mismatch"
    if snapshots_complete is not None and ev_comp != bool(snapshots_complete):
        return False, "trust.subject_mismatch"
    if ev.get("incomplete_shards", 0) != incomplete_shards:
        return False, "trust.subject_mismatch"
    exp_mut_dig = m_man["digest"] if isinstance(m_man, dict) and "digest" in m_man else ""
    if ev.get("mutations_manifest", "") != exp_mut_dig:
        return False, "trust.subject_mismatch"
    exp_perf_dig = perf_b.get("manifest_digest", "") if isinstance(perf_b, dict) and perf_b.get("active") and not perf_b.get("invalid") else ""
    if ev.get("performance_manifest", "") != exp_perf_dig:
        return False, "trust.subject_mismatch"
    if set(by_id) != {v["id"] for v in verdicts} or len(cnts) != len(verdicts):
        return False, "trust.subject_mismatch"
    expected_all_ok = bool(verdicts) and all(v["ok"] for v in verdicts)
    if doc["ok"] != expected_all_ok:
        return False, "trust.subject_mismatch"
    for v in verdicts:
        ac = by_id[v["id"]]
        ver_cnt = sum(1 for r in v.get("results", []) if r.get("state") == "verified")
        bnd_cnt = sum(1 for r in v.get("results", []) if r.get("state") == "bound")
        if (
            ac["digest"] != v["digest"]
            or ac["ref"] != v["ref"]
            or ac["approval"] != v["approval"]
            or ac["ok"] != v["ok"]
            or ac["reasons"] != v["reasons"]
            or ac["verified"] != ver_cnt
            or ac["bound"] != bnd_cnt
        ):
            return False, "trust.subject_mismatch"
    return True, ""


def apply_openssh_trust_verdicts(
    verdicts: list[dict],
    args,
    cfg_state: str = "",
    cfg_digest: str = "",
    shard_hashes: list[str] | None = None,
    snapshots: list[str] | None = None,
    snapshots_complete: bool | None = None,
    incomplete_shards: int = 0,
    m_man: dict[str, Any] | None = None,
    perf_b: dict[str, Any] | None = None,
    decode_fn: Callable[[str], Any] | None = None,
) -> list[dict]:
    tv = verify_openssh_trust(args.attest, args.attest_sig, "drift-attestation@v1", args.trust_root, args.verify_time)
    if tv.get("active"):
        if not tv.get("reason"):
            subj_ok, subj_rsn = validate_and_match_attestation(
                args.attest,
                verdicts,
                cfg_state=cfg_state,
                cfg_digest=cfg_digest,
                shard_hashes=shard_hashes,
                snapshots=snapshots,
                snapshots_complete=snapshots_complete,
                incomplete_shards=incomplete_shards,
                m_man=m_man,
                perf_b=perf_b,
                decode_fn=decode_fn,
            )
            if not subj_ok:
                tv["reason"] = subj_rsn
                tv["signature_valid"] = False
                tv["signer_authorized"] = False
        for v in verdicts:
            if tv.get("reason") and tv["reason"] not in v["reasons"]:
                v["reasons"].append(tv["reason"])
                v["ok"] = False
            v["trust_verification"] = {k: tv[k] for k in ("trust_root_ref", "namespace", "signature_valid", "signer_authorized", "human_intervention") if k in tv}
    return verdicts


PARITY_KEYS = frozenset(("schema", "contract", "digest", "requirement_ref", "legacy_target", "candidate_target", "legacy_subject_ref", "candidate_subject_ref", "normalization_ref", "corpus_ref", "legacy_cases", "candidate_cases", "diverged_observations", "effect_violations", "frame_verified", "rollback_readback", "outcome"))
ARTIFACT_REF_RE = re.compile(r"^(?:sha256:[0-9a-f]{64}|dr1:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12}))$")


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
        if pf in seen:
            continue
        seen.add(pf)
        try:
            doc = decode_fn(pf.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or set(doc) != PARITY_KEYS or doc.get("schema") != "drift.parity-receipt/1":
                raise ValueError("parity_keys")
            if any(not isinstance(doc.get(k), str) or not doc[k].strip() for k in str_keys):
                raise ValueError("parity_str_types")
            s = {k: doc[k].strip() for k in str_keys}
            cid, dig, rref, leg, cand = s["contract"], s["digest"], s["requirement_ref"], s["legacy_target"], s["candidate_target"]
            lref, cref, nref, cpref, rb, outc = s["legacy_subject_ref"], s["candidate_subject_ref"], s["normalization_ref"], s["corpus_ref"], s["rollback_readback"], s["outcome"]
            fv = doc.get("frame_verified")
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", cid) or not ARTIFACT_REF_RE.match(dig) or not ARTIFACT_REF_RE.match(rref) or leg == cand or not ARTIFACT_REF_RE.match(lref) or not ARTIFACT_REF_RE.match(cref) or not ARTIFACT_REF_RE.match(nref) or not ARTIFACT_REF_RE.match(cpref) or not isinstance(fv, bool) or rb not in ("verified", "not_applicable", "unverified", "failed") or outc not in ("passed", "failed"):
                raise ValueError("parity_fields")
            lists = {}
            for lk in ("legacy_cases", "candidate_cases", "diverged_observations", "effect_violations"):
                arr = doc.get(lk)
                if not isinstance(arr, list) or not all(isinstance(x, str) and x.strip() for x in arr):
                    raise ValueError(lk)
                lists[lk] = sorted({x.strip() for x in arr})
            out.append({"schema": "drift.parity-receipt/1", **s, "frame_verified": fv, **lists})
        except Exception as exc:
            errs.append(f"{pf.name}: {exc}")
    return out, errs


def evaluate_contract_parity_impl(contract: dict[str, Any], parity_receipts: list[dict[str, Any]], phase: str, digest_matches_fn: Callable[[str, str], bool], expected_subject_ref: str = "", shard_subject_refs: set[str] | None = None, mig_checks: list[dict[str, Any]] | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    cm = contract.get("cutover") or {}
    if not cm:
        return [], []
    enf = str(cm.get("enforce", "release"))
    enforced_now = enf == "always" or phase == "release"
    matching = [r for r in parity_receipts if r["contract"] == contract["id"] and digest_matches_fn(r["digest"], contract["digest"])]
    if not matching:
        return (["parity.missing"] if enforced_now else []), []
    if len(matching) > 1:
        f = matching[0]
        if any(r != f for r in matching[1:]):
            return ["parity.conflicting_receipts"], [{**r, "effective_outcome": "failed", "reason": "parity.conflicting_receipts"} for r in matching]
    rec = matching[0]
    raw_cases = contract.get("cases") or {}
    active = sorted(cid for cid, c in raw_cases.items() if isinstance(c, dict) and "status" not in c)
    needs_frames = bool((contract.get("scope_writes") or []) or any(isinstance(c, dict) and "writes" in c for c in raw_cases.values()))
    allowed = set(cm.get("intentional_diffs") or [])
    comp_ok = rec["legacy_subject_ref"] != rec["candidate_subject_ref"] and all(ac in rec["legacy_cases"] and ac in rec["candidate_cases"] for ac in active)
    sh_refs = shard_subject_refs or set()
    sub_ok = (not expected_subject_ref or digest_matches_fn(rec["candidate_subject_ref"], expected_subject_ref)) and (not sh_refs or any(digest_matches_fn(rec["candidate_subject_ref"], s) for s in sh_refs))
    norm_ok = rec["legacy_target"] == cm.get("legacy_target") and rec["candidate_target"] == cm.get("candidate_target") and digest_matches_fn(rec["normalization_ref"], str(cm.get("normalization_ref", ""))) and digest_matches_fn(rec["corpus_ref"], str(cm.get("corpus_ref", ""))) and (not cm.get("requirement_ref") or digest_matches_fn(rec["requirement_ref"], cm["requirement_ref"]))
    obs_ok = all(d in allowed for d in rec["diverged_observations"])
    eff_ok = not rec["effect_violations"] and (not needs_frames or rec["frame_verified"])
    rb_ok = cm.get("rollback_readback", "not_applicable") != "required" or rec["rollback_readback"] == "verified"
    req_migs = cm.get("migration_ids") or []
    m_list = mig_checks or []
    migs_ok = all(
        any(mr.get("migration_id") == mid and mr.get("effective_outcome") == "passed" and digest_matches_fn(str(mr.get("subject_ref", "")), rec["candidate_subject_ref"]) for mr in m_list)
        and not any(mr.get("migration_id") == mid and mr.get("effective_outcome") != "passed" for mr in m_list)
        for mid in req_migs
    )
    reasons = []
    if not comp_ok:
        reasons.append("parity.incomplete_target")
    if not sub_ok:
        reasons.append("parity.subject_mismatch")
    if not norm_ok:
        reasons.append("parity.normalization_mismatch")
    if not obs_ok:
        reasons.append("parity.observation_mismatch")
    if not eff_ok:
        reasons.append("parity.effect_mismatch")
    if not rb_ok:
        reasons.append("parity.rollback_incompatible")
    if not migs_ok:
        reasons.append("parity.migration_unverified")
    if rec["outcome"] != "passed" and not reasons:
        reasons.append("parity.observation_mismatch")
    eff_out = "passed" if not reasons and rec["outcome"] == "passed" else "failed"
    item = {**rec, "effective_outcome": eff_out}
    if reasons:
        item["reason"] = reasons[0]
    return reasons, [item]


