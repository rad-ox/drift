#!/usr/bin/env python3
"""Bilateral pact-lock (drift.pact-lock/1) & D305 quorum verifier helper (MIT License)."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Callable

from drift_verify_pact_cells import _canon_pretty_py, _check_when_cell_coverage_py, _clause_then_subsumes_py, _expr_03_to_atom_py, _extract_sshsig_fp_py, _infer_outcome_py, _norm_ptr_py, _parse_pact_ack_py, _when_meet_py

PACT_LOCK_SCHEMA = "drift.pact-lock/1"
PACT_LOCK_DOMAIN = b"drift.pact-lock/2\x00"
SIG_NAMESPACE = "drift-signature@v1"

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DR2P_FULL_RE = re.compile(r"^dr2p:sha256:[0-9a-f]{64}$")
DR2P_REF_RE = re.compile(r"^dr2p:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})$")
DR2R_FULL_RE = re.compile(r"^dr2r:sha256:[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OUTCOME_CLASSES = {"ok", "validation_fatal", "conflict_state", "rate_limited", "transient_retryable", "unknown_outcome"}


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
    if not isinstance(doc["policy_ref"], str) or not SHA256_RE.match(doc["policy_ref"]):
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
    from drift_verify_ssh import _has_temporal_bounds, _valid_verify_time

    parent, base = lock_path.resolve().parent, lock_path.name
    sig_files = sorted(f for f in parent.iterdir() if not f.is_symlink() and f.is_file() and f.name.startswith(base + ".") and f.name.endswith(".sig.json")) if parent.is_dir() else []
    if not sig_files:
        return (["pact.quorum_missing"], True) if trust_root is not None else ([], False)
    reasons: list[str] = []
    meanings_ok: dict[str, tuple[str, str]] = {}
    ssh_keygen = os.environ.get("DRIFT_SSH_KEYGEN") or shutil.which("ssh-keygen") or "/usr/bin/ssh-keygen"
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


def _extract_contract_seam_py(c: dict[str, Any], cf_path: Path, profiles_dir: Path, canon_fn: Callable[[Any], str]) -> dict[str, Any] | None:
    if c.get("drift") != "0.3" or not cf_path.is_file():
        return None
    raw_c = tomllib.loads(cf_path.read_text("utf-8"))
    sc = raw_c.get("scope") if isinstance(raw_c.get("scope"), dict) else {}
    out_res = [str(x) for x in sc.get("out", []) if isinstance(x, str)] if isinstance(sc.get("out"), list) else []
    surface = str(sc.get("surface", "")) if isinstance(sc.get("surface"), str) else ""
    prof_ref = str((raw_c.get("use") or {}).get("profile", "")) if isinstance(raw_c.get("use"), dict) else ""
    w_ptr, t_ptr, w_unit, t_unit, roles, ptr_schema = {}, {}, {}, {}, {}, {}
    p0 = profiles_dir / f"{prof_ref}.toml" if prof_ref else None
    if p0 and p0.is_file():
        from drift_verify_03 import _merge_pred_03

        pdoc = tomllib.loads(p0.read_text("utf-8"))
        exts = [str(x) for x in (pdoc.get("extends") or ()) if isinstance(x, str)]
        merged_w, merged_t = {}, {}
        for r in [*exts, prof_ref]:
            bp = pdoc if r == prof_ref else (tomllib.loads(pf.read_text("utf-8")) if (pf := profiles_dir / f"{r}.toml").is_file() else {})
            sm = bp.get("schema") if isinstance(bp.get("schema"), dict) else {}
            for k, pm in (sm.get("when") or {}).items():
                if isinstance(pm, dict):
                    merged_w[k] = _merge_pred_03(merged_w[k], pm) if k in merged_w else dict(pm)
            for k, pm in (sm.get("then") or {}).items():
                if isinstance(pm, dict):
                    merged_t[k] = _merge_pred_03(merged_t[k], pm) if k in merged_t else dict(pm)
        for side, m_src, pmap, umap in (("when", merged_w, w_ptr, w_unit), ("then", merged_t, t_ptr, t_unit)):
            for k, pm in m_src.items():
                ptr = _norm_ptr_py(str(pm.get("ptr", "")), k)
                pmap[k] = ptr
                umap[k] = str(pm.get("unit", ""))
                if pm.get("role"):
                    roles[ptr] = str(pm["role"])
                sc_e: dict[str, Any] = {"type": str(pm.get("type", "any"))}
                if sc_e["type"] == "int" and "min" in pm:
                    sc_e["min"] = int(pm["min"])
                if sc_e["type"] == "int" and "max" in pm:
                    sc_e["max"] = int(pm["max"])
                if pm.get("unit"):
                    sc_e["unit"] = str(pm["unit"])
                if pm.get("enum"):
                    sc_e["enum"] = sorted(set(pm["enum"]))
                ptr_schema[ptr] = sc_e
    clauses = []
    for case_id in sorted(c.get("cases") or {}):
        cm = c["cases"][case_id]
        if not isinstance(cm, dict) or "status" in cm:
            continue
        wm = {w_ptr.get(wk, f"/{wk}"): _expr_03_to_atom_py(wv, w_ptr, w_unit.get(wk, ""), canon_fn) for wk, wv in (cm.get("when") or {}).items()}
        tm, pres = {}, []
        for tk, tv in (cm.get("then") or {}).items():
            ptr = t_ptr.get(tk, f"/{tk}")
            tm[ptr] = _expr_03_to_atom_py(tv, t_ptr, t_unit.get(tk, ""), canon_fn)
            pres.append(ptr)
        c_writes = [str(x) for x in cm["writes"]] if isinstance(cm.get("writes"), list) else list(c.get("scope_writes") or ())
        cl_id = "cl-" + hashlib.sha256(canon_fn(wm).encode("utf-8")).hexdigest()[:12]
        clauses.append({"id": cl_id, "when": wm, "then": tm, "presence": sorted(set(pres)), "outcome_class": _infer_outcome_py(tm, roles), "writes": sorted(set(c_writes))})
    cid = c["id"]
    d2r = lambda tag, obj: "dr2r:sha256:" + hashlib.sha256(tag.encode("utf-8") + b"\x00" + canon_fn(obj).encode("utf-8")).hexdigest()
    obs, lims = {}, {}
    assur = raw_c.get("assurance") if isinstance(raw_c.get("assurance"), dict) else {}
    for kind_k, pfx in (("budgets", "budget:"), ("formal", "formal:"), ("controls", "control:")):
        for oid, oval in (assur.get(kind_k) or {}).items():
            if not isinstance(oval, dict):
                continue
            cl_o = {k: v for k, v in oval.items() if k not in ("note", "requirement_ref", "warn_ratio")}
            if kind_k == "budgets":
                raw_lim = cl_o.pop("limit", 0)
                op_s = str(cl_o.get("op", "le"))
                is_milli = isinstance(raw_lim, float) and not raw_lim.is_integer()
                lim_sc = round(float(raw_lim) * 1000.0) if is_milli else int(raw_lim)
                signed_b = -lim_sc if op_s == "ge" else lim_sc
                sfx = ":bound_milli" if is_milli else ":bound"
                obs[f"{cid}:{pfx}{oid}"] = d2r("drift.pact-obligation/2", {"contract": cid, "entry": cl_o, "id": oid, "kind": kind_k})
                obs[f"{cid}:{pfx}{oid}{sfx}"] = d2r("drift.pact-budget-bound/2", {"milli": is_milli, "signed": signed_b})
                lims[f"{cid}:{pfx}{oid}{sfx}"] = signed_b
            else:
                obs[f"{cid}:{pfx}{oid}"] = d2r("drift.pact-obligation/2", {"contract": cid, "entry": cl_o, "id": oid, "kind": kind_k})
    return {"contract_id": cid, "surface": surface, "reads": list(c.get("scope_reads") or ()), "writes": list(c.get("scope_writes") or ()), "out": out_res, "clauses": clauses, "schema": ptr_schema, "obligations": obs, "budget_limits": lims, "proof_floor": str(c.get("profile_proof", "")), "security": list(c.get("profile_security") or ())}


def evaluate_pact_verdicts_py(
    verdicts: list[dict[str, Any]],
    parsed_contracts: list[dict[str, Any]],
    c_files: list[Path],
    profiles_dir: Path,
    args: Any,
    cfg_path: Path,
    pol: dict[str, Any],
    area_root: str | Path | None,
    decode_fn: Callable[[str], Any],
    canon_fn: Callable[[Any], str],
    jcs_str_fn: Callable[[str], str],
    jcs_num_fn: Callable[[Any], str],
    digest_matches_fn: Callable[[str, str], bool],
    proof_rank_fn: Callable[[str], int],
    verify_contract_fn: Callable[[Path, Path], dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    pol_on = pol.get("pack") == "core@1"
    pinned = [str(x) for x in pol.get("pact_locks", []) if isinstance(x, str)] if pol_on and isinstance(pol.get("pact_locks"), list) else []
    explicit_locks: list[Path] = list(getattr(args, "pact_lock", None) or [])
    pacts_dir = cfg_path.parent / "pacts"
    lock_paths = explicit_locks if explicit_locks else (sorted(pacts_dir.rglob("*.lock.json")) if pacts_dir.is_dir() else [])
    ack_paths = [] if explicit_locks else (sorted(pacts_dir.rglob("*.ack.json")) if pacts_dir.is_dir() else [])
    if not explicit_locks and not pinned and not lock_paths:
        return verdicts, False
    if not lock_paths:
        for v in verdicts:
            if "pact.lock_missing" not in v["reasons"]:
                v["reasons"].append("pact.lock_missing")
                v["ok"] = False
        return verdicts, bool(explicit_locks)

    global_rsns: list[str] = []
    locks: list[dict[str, Any]] = []
    acks: list[dict[str, Any]] = []
    has_pact_sig = bool(explicit_locks)
    for lp in lock_paths:
        if not lp.is_file():
            if "pact.lock_missing" not in global_rsns:
                global_rsns.append("pact.lock_missing")
            continue
        try:
            pl = _parse_pact_lock_py(lp.read_text("utf-8"), decode_fn, canon_fn, jcs_str_fn, jcs_num_fn)
        except Exception:
            if "pact.lock_invalid" not in global_rsns:
                global_rsns.append("pact.lock_invalid")
            continue
        srs, hsig = _verify_pact_sigs_py(lp, pl, getattr(args, "trust_root", None), getattr(args, "verify_time", ""), decode_fn, canon_fn, digest_matches_fn)
        has_pact_sig = has_pact_sig or hsig
        for sr in srs:
            if sr not in global_rsns:
                global_rsns.append(sr)
        locks.append(pl)
    for ap in ack_paths:
        try:
            acks.append(_parse_pact_ack_py(ap.read_text("utf-8"), decode_fn, canon_fn, jcs_str_fn, jcs_num_fn))
        except Exception:
            if "pact.lock_invalid" not in global_rsns:
                global_rsns.append("pact.lock_invalid")
    if not locks:
        for v in verdicts:
            for gr in global_rsns:
                if gr not in v["reasons"]:
                    v["reasons"].append(gr)
            v["ok"] = not v["reasons"]
        return verdicts, has_pact_sig

    if not explicit_locks and pinned:
        for pin in pinned:
            if not any(digest_matches_fn(pin, pl["digest"]) for pl in locks) and "pact.lock_mismatch" not in global_rsns:
                global_rsns.append("pact.lock_mismatch")

    cfg_raw = tomllib.loads(cfg_path.read_text("utf-8")) if cfg_path.is_file() else {}
    area_tbl = cfg_raw.get("area") if isinstance(cfg_raw.get("area"), dict) else {}
    area_id = next((str(area_tbl[k]).strip() for k in ("id", "name", "owner") if isinstance(area_tbl.get(k), str) and str(area_tbl[k]).strip()), Path(area_root).name if area_root else cfg_path.parent.parent.name)

    by_pact: dict[str, list[dict[str, Any]]] = {}
    for pl in locks:
        by_pact.setdefault(pl["pact_id"], []).append(pl)
    for pid, revs in sorted(by_pact.items()):
        revs.sort(key=lambda x: x["revision"])
        for i in range(len(revs)):
            if i + 1 < len(revs) and revs[i]["revision"] == revs[i + 1]["revision"] and revs[i]["digest"] != revs[i + 1]["digest"]:
                if "pact.revision_fork" not in global_rsns:
                    global_rsns.append("pact.revision_fork")
            if i > 0 and revs[i]["revision"] == revs[i - 1]["revision"] + 1:
                if not digest_matches_fn(revs[i].get("supersedes", ""), revs[i - 1]["digest"]) and "pact.lock_mismatch" not in global_rsns:
                    global_rsns.append("pact.lock_mismatch")
                for pk in ("producer", "consumer"):
                    prev_k, cur_k = set(revs[i - 1][pk].get("authorized_keys", ())), set(revs[i][pk].get("authorized_keys", ()))
                    if prev_k and not (prev_k & cur_k) and "pact.signer_unauthorized" not in global_rsns:
                        global_rsns.append("pact.signer_unauthorized")
        lo_rev = revs[0]
        if lo_rev["revision"] > 1:
            cp = lo_rev["consumer"]["area_id"] if lo_rev["producer"]["area_id"] == area_id else lo_rev["producer"]["area_id"]
            if not any(ak["pact_id"] == pid and ak["retired_revision"] == lo_rev["revision"] - 1 and ak["area_id"] == cp and digest_matches_fn(ak["active_lock_ref"], lo_rev["digest"]) for ak in acks):
                if "pact.unacked_retirement" not in global_rsns:
                    global_rsns.append("pact.unacked_retirement")

    all_pairs = list(zip(parsed_contracts, c_files))
    seen_res = {cf.resolve() for cf in c_files}
    sib_dir = cfg_path.parent / "contracts"
    if verify_contract_fn is not None and sib_dir.is_dir():
        for sf in sorted(sib_dir.glob("*.toml")):
            if sf.resolve() not in seen_res:
                seen_res.add(sf.resolve())
                all_pairs.append((verify_contract_fn(sf, profiles_dir), sf))
    extracted = [ex for c, cf in all_pairs if (ex := _extract_contract_seam_py(c, cf, profiles_dir, canon_fn)) is not None]
    cfg_rank = proof_rank_fn(str(pol.get("proof", ""))) if pol_on else 0
    pol_sec = {str(x) for x in pol.get("security", []) if isinstance(x, str)} if pol_on and isinstance(pol.get("security"), list) else set()
    by_contract: dict[str, list[str]] = {}
    add_g = lambda r: global_rsns.append(r) if r not in global_rsns else None
    d2r_b = lambda s_v, mil: "dr2r:sha256:" + hashlib.sha256(b"drift.pact-budget-bound/2\x00" + canon_fn({"milli": mil, "signed": s_v}).encode("utf-8")).hexdigest()

    for pl in locks:
        is_prod, is_cons = pl["producer"]["area_id"] == area_id, pl["consumer"]["area_id"] == area_id
        if not is_prod and not is_cons:
            add_g("pact.party_mismatch")
            continue
        if is_prod:
            req_r, req_s = proof_rank_fn(pl["producer"].get("requires_proof", "")), set(pl["producer"].get("requires_security", ()))
            for seam in pl["seams"]:
                m_ex = [ex for ex in extracted if seam["resource"] in ex["out"] or seam["resource"] in ex["writes"] or seam["operation"] == ex["surface"]]
                if not m_ex:
                    add_g("pact.contract_missing")
                    continue
                if len(m_ex) > pl["producer"]["attested_max_direct_slices"]:
                    add_g("pact.local_claim_violated")
                p_cls, p_whens = [], []
                for ex in m_ex:
                    if max(proof_rank_fn(ex["proof_floor"]), cfg_rank) < req_r or not req_s.issubset(set(ex["security"]) | pol_sec):
                        add_g("pact.posture_lowered")
                        by_contract.setdefault(ex["contract_id"], []).append("pact.posture_lowered")
                    for cl in ex["clauses"]:
                        p_cls.append(cl)
                        p_whens.append(cl["when"])
                        if cl["outcome_class"] != "ok" and cl["writes"]:
                            add_g("pact.clean_error_frame_violated")
                for pcl in seam["clauses"]:
                    st = _check_when_cell_coverage_py(pcl["when"], p_whens, seam.get("schema", {}))
                    if st == "undecided":
                        add_g("pact.coverage_undecided")
                    elif st == "uncovered":
                        add_g("pact.producer_when_narrowed")
                    for icl in p_cls:
                        if _when_meet_py(icl["when"], pcl["when"]) is not None and not _clause_then_subsumes_py(icl, pcl):
                            add_g("pact.producer_then_widened")
        if is_cons:
            req_r, req_s = proof_rank_fn(pl["consumer"].get("requires_proof", "")), set(pl["consumer"].get("requires_security", ()))
            for seam in pl["seams"]:
                m_ex = [ex for ex in extracted if seam["resource"] in ex["reads"] or seam["operation"] == ex["surface"]]
                if not m_ex:
                    add_g("pact.contract_missing")
                    continue
                if len(m_ex) > pl["consumer"]["attested_max_direct_slices"]:
                    add_g("pact.local_claim_violated")
                p_whens = [pcl["when"] for pcl in seam["clauses"]]
                req_errs = {pcl["outcome_class"] for pcl in seam["clauses"] if pcl["outcome_class"] != "ok"}
                handled: dict[str, str] = {}
                for ex in m_ex:
                    if max(proof_rank_fn(ex["proof_floor"]), cfg_rank) < req_r or not req_s.issubset(set(ex["security"]) | pol_sec):
                        add_g("pact.posture_lowered")
                        by_contract.setdefault(ex["contract_id"], []).append("pact.posture_lowered")
                    t_schema = {**seam.get("schema", {}), **ex.get("schema", {})}
                    for cl in ex["clauses"]:
                        st = _check_when_cell_coverage_py(cl["when"], p_whens, t_schema)
                        if st == "undecided":
                            add_g("pact.coverage_undecided")
                        elif st == "uncovered":
                            add_g("pact.consumer_when_exceeded")
                        for pcl in seam["clauses"]:
                            if _when_meet_py(cl["when"], pcl["when"]) is not None:
                                if cl["outcome_class"] != pcl["outcome_class"] or not _clause_then_subsumes_py(pcl, cl):
                                    add_g("pact.consumer_then_overassumed")
                                elif pcl["outcome_class"] != "ok":
                                    handled[pcl["outcome_class"]] = canon_fn(cl)
                if any(ec not in handled for ec in req_errs):
                    add_g("pact.unhandled_error_class")
        local_obs = {f"{area_id}:{k}": v for ex in extracted for k, v in ex["obligations"].items()}
        local_lims = {f"{area_id}:{k}": v for ex in extracted for k, v in ex["budget_limits"].items()}
        for ok, exp_v in pl["obligations"].items():
            if not ok.startswith(f"{area_id}:"):
                continue
            got = local_obs.get(ok, "")
            if got == exp_v:
                continue
            is_m = ok.endswith(":bound_milli")
            if (ok.endswith(":bound") or is_m) and got and ok in local_lims and ok in pl["seam_metrics"]:
                b_key = ok[:-12] if is_m else ok[:-6]
                s_val = pl["seam_metrics"][ok]
                if local_obs.get(b_key, "") == pl["obligations"].get(b_key, "") and d2r_b(s_val, is_m) == exp_v and local_lims[ok] <= s_val:
                    continue
            add_g("pact.obligation_tampered")

    lock_digests = sorted({pl["digest"] for pl in locks})
    out_v = []
    for v in verdicts:
        nr = list(v["reasons"])
        for r in (*global_rsns, *by_contract.get(v["id"], ())):
            if r not in nr:
                nr.append(r)
        cs = dict(v.get("claim_scope") or {})
        cs["pact_lock_refs"] = lock_digests
        out_v.append({**v, "reasons": nr, "ok": not nr, "claim_scope": cs})
    return out_v, has_pact_sig
