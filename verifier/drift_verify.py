#!/usr/bin/env python3
"""DRIFT Independent Reference Proof Verifier (MIT License).
Zero-dependency Python 3.11+ RFC 8785 (JCS), event/sidecar schema, and gate verifier.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

SAFE_INT = (1 << 53) - 1
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORD_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DIGEST_RE = re.compile(r"^dr1:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})$")
PACK_REF_RE = re.compile(r"^dr1:[0-9a-f]{12}$")
SNAPSHOT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
CLASS_TOKEN_RE = re.compile(r"^[^# \t\r\n/\\\[\]]+$")
METHOD_TOKEN_RE = re.compile(r"^[^# \t\r\n\[\]]+$")
OUTCOMES = frozenset(("passed", "failed", "skipped", "disabled", "interrupted", "timeout"))
EVENT_KEYS = frozenset(("test", "contract", "cases", "level", "outcome", "read", "digest"))
META_KEYS = frozenset(("version", "classes", "tests", "snapshot", "pack_ref", "touched", "self_stubbed", "inputs", "env"))
ENV_KEYS = frozenset(("toolchain", "deps", "config", "runner", "drift", "adapter", "policy"))


_ESC_MAP = {0x22: '\\"', 0x5C: "\\\\", 0x08: "\\b", 0x0C: "\\f", 0x0A: "\\n", 0x0D: "\\r", 0x09: "\\t"}


def jcs_string(s: str) -> str:
    return '"' + "".join(_ESC_MAP.get(cp := ord(c), f"\\u{cp:04x}" if cp < 0x20 else c) for c in s) + '"'


def jcs_number(val: int | float) -> str:
    if isinstance(val, int) and not isinstance(val, bool):
        if val < -SAFE_INT or val > SAFE_INT:
            raise ValueError(f"integer {val} is outside +-(2^53-1)")
        return str(val)
    f = float(val)
    if math.isnan(f) or math.isinf(f):
        raise ValueError("NaN and Infinity are not valid in RFC 8785 JSON")
    if f == 0.0:
        return "0"
    neg, f = f < 0.0, abs(f)
    s = repr(f)
    if "e" in s or "E" in s:
        mant, exp_str = s.lower().split("e", 1)
        digits, n = mant.replace(".", "").rstrip("0") or "0", int(exp_str) + 1
    elif "." in s:
        int_p, frac_p = s.split(".", 1)
        digits = (int_p + frac_p).lstrip("0").rstrip("0") or "0"
        n = len(int_p) if int_p != "0" else -(len(frac_p) - len(frac_p.lstrip("0")))
    else:
        digits, n = s.rstrip("0") or "0", len(s)
    k = len(digits)
    if k <= n <= 21:
        body = digits + ("0" * (n - k))
    elif 0 < n <= 21:
        body = f"{digits[:n]}.{digits[n:]}"
    elif -6 < n <= 0:
        body = f"0.{'0' * (-n)}{digits}"
    else:
        m = digits if k == 1 else f"{digits[0]}.{digits[1:]}"
        body = f"{m}e{'+' if n >= 1 else '-'}{abs(n - 1)}"
    return f"-{body}" if neg else body


def canonical_json(obj: Any) -> str:
    if obj is None or isinstance(obj, bool):
        return "null" if obj is None else ("true" if obj else "false")
    if isinstance(obj, (int, float)):
        return jcs_number(obj)
    if isinstance(obj, str):
        return jcs_string(obj)
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(canonical_json(x) for x in obj) + "]"
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: str(kv[0]).encode("utf-16-be"))
        return "{" + ",".join(f"{jcs_string(str(k))}:{canonical_json(v)}" for k, v in items) + "}"
    raise TypeError(f"unsupported type for RFC 8785 JSON: {type(obj).__name__}")


def dr1_digest(obj: Any) -> str:
    return "dr1:sha256:" + hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def dr1_ref(digest: str) -> str:
    return "dr1:" + digest[11:23] if digest.startswith("dr1:sha256:") else ""


def digest_matches(event_digest: str, full_digest: str) -> bool:
    return bool(full_digest) and (event_digest == full_digest or event_digest == dr1_ref(full_digest))


def _decode_no_dup_keys(text: str) -> Any:
    depth, in_str, esc = 0, False, False
    for ch in text:
        if in_str:
            esc = (not esc) if ch == "\\" else False
            if ch == '"' and not esc: in_str = False
        elif ch == '"': in_str = True
        elif ch in "{[":
            depth += 1
            if depth > 64: raise ValueError("JSON nesting depth exceeds 64")
        elif ch in "}]": depth = max(0, depth - 1)

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in pairs:
            if k in out: raise ValueError(f'duplicate key "{k}"')
            out[k] = v
        return out
    return json.loads(text, object_pairs_hook=hook)


def validate_event_line(line: str) -> dict[str, Any]:
    doc = _decode_no_dup_keys(line)
    if not isinstance(doc, dict) or any(k not in EVENT_KEYS for k in doc) or any(r not in doc for r in ("test", "contract", "cases", "level", "outcome")):
        raise ValueError("invalid event object")
    cases, read, digest = doc["cases"], doc.get("read", []), doc.get("digest", "")
    if not isinstance(doc["test"], str) or not doc["test"].strip() or not isinstance(doc["contract"], str) or not ID_RE.match(doc["contract"]):
        raise ValueError("invalid test or contract")
    if not isinstance(cases, list) or not cases or len(set(cases)) != len(cases) or not all(isinstance(c, str) and ID_RE.match(c) for c in cases):
        raise ValueError("invalid cases")
    if not isinstance(doc["level"], str) or not WORD_RE.match(doc["level"]) or doc["outcome"] not in OUTCOMES:
        raise ValueError("invalid level or outcome")
    if not isinstance(read, list) or len(set(read)) != len(read) or not all(isinstance(r, str) and r in cases for r in read):
        raise ValueError("invalid read")
    if digest != "" and (not isinstance(digest, str) or not DIGEST_RE.match(digest)):
        raise ValueError("invalid digest")
    return {"test": doc["test"], "contract": doc["contract"], "cases": cases, "level": doc["level"], "outcome": doc["outcome"], "read": read, "digest": digest}


def validate_inventory_text(text: str) -> dict[str, Any]:
    doc = _decode_no_dup_keys(text)
    if not isinstance(doc, dict) or any(k not in META_KEYS for k in doc) or doc.get("version") != 1 or isinstance(doc.get("version"), bool):
        raise ValueError("invalid inventory header")
    classes, tests = doc.get("classes"), doc.get("tests")
    if not isinstance(classes, list) or not all(isinstance(x, str) and CLASS_TOKEN_RE.match(x) for x in classes) or classes != sorted(set(classes)):
        raise ValueError("invalid classes")
    c_set = set(classes)
    if not isinstance(tests, list) or not all(isinstance(x, str) and "#" in x for x in tests) or tests != sorted(set(tests)):
        raise ValueError("invalid tests")
    if any((p := t.split("#", 1))[0] not in c_set or not METHOD_TOKEN_RE.match(p[1]) for t in tests):
        raise ValueError("invalid test name")
    t_set, snap, pack_ref = set(tests), doc.get("snapshot", ""), doc.get("pack_ref", "")
    if ("snapshot" in doc and (not isinstance(snap, str) or not SNAPSHOT_RE.match(snap))) or ("pack_ref" in doc and (not isinstance(pack_ref, str) or not PACK_REF_RE.match(pack_ref))):
        raise ValueError("invalid snapshot or pack_ref")
    if "touched" in doc:
        tc = doc["touched"]
        if not isinstance(tc, list) or not all(isinstance(x, str) and x.strip() for x in tc) or tc != sorted(set(tc)) or any(tp.startswith("/") or "\\" in tp or any(s in ("", ".", "..") for s in tp.split("/")) for tp in tc):
            raise ValueError("invalid touched")
    if "self_stubbed" in doc and (not isinstance(doc["self_stubbed"], list) or any(not isinstance(x, str) or x not in t_set for x in doc["self_stubbed"])):
        raise ValueError("invalid self_stubbed")
    if "inputs" in doc:
        ri = doc["inputs"]
        if not isinstance(ri, dict) or any(tid not in t_set or not isinstance(fm, dict) or any(not isinstance(fp, str) or not fp.strip() or not isinstance(ov, str) or not ov.strip() for fp, ov in fm.items()) for tid, fm in ri.items()):
            raise ValueError("invalid inputs")
    if "env" in doc:
        re_env = doc["env"]
        if not isinstance(re_env, dict) or set(re_env) != ENV_KEYS or any(not isinstance(ev, str) or not ev.strip() for ev in re_env.values()):
            raise ValueError("invalid env")
    return {"classes": c_set, "tests": t_set, "snapshot": snap, "pack_ref": pack_ref}


def validate_inventory_sidecar(path: Path) -> dict[str, Any]:
    return validate_inventory_text(path.read_text(encoding="utf-8"))


def verify_config_toml(path: Path) -> tuple[str, str, dict[str, Any]]:
    if not path.is_file(): return "missing", "", {}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    appr, dig, pol = raw.pop("approval", None), dr1_digest(raw), (raw.get("policy") if isinstance(raw.get("policy"), dict) else {})
    if not isinstance(appr, dict) or not appr.get("ref"): return "absent", dig, pol
    st = "current" if appr["ref"] == dr1_ref(dig) else "stale"
    return st, dig, (pol if st == "current" else {})


def _is_unanchored_prose_source(raw: str) -> bool:
    s = raw.strip()
    if not s or s.startswith("ADR-") or ";" in s or "://" in s: return False
    if " " in s: return True
    if ":" in s: return False
    base = s.split("@sha256:", 1)[0].replace("\\", "/")
    if not base or base.startswith(("note:", "cite:")) or any(c in base for c in " \t\n\r;"): return True
    dot = base.rfind(".")
    if 0 < dot < len(base) - 1 and base[dot + 1:].isalnum() and any(c.isalpha() for c in base[dot + 1:]): return False
    return not ("/" in base and any("a" <= c <= "z" for c in base))


def _contains_todo(val: Any) -> bool:
    return val == "todo" if isinstance(val, str) else (any(_contains_todo(x) for x in val) if isinstance(val, list) else (any(_contains_todo(v) for v in val.values()) if isinstance(val, dict) else False))


def _has_approval_blocker(raw: dict[str, Any], prof: dict[str, Any]) -> bool:
    scope = raw.get("scope")
    if isinstance(scope, dict) and scope.get("indirect") == "unknown": return True
    if any(_contains_todo(raw.get(sec)) for sec in ("use", "scope", "cases")): return True
    open_tbl = raw.get("open")
    if isinstance(open_tbl, dict) and any(isinstance(qm, dict) and qm.get("blocks", "approval") == "approval" for qm in open_tbl.values()): return True
    return any(isinstance(dm, dict) and dm.get("pick", "") == "" and dm.get("decide_by", "approval") == "approval" for dec_src in (raw.get("decisions"), prof.get("decisions")) if isinstance(dec_src, dict) for dm in dec_src.values())


def _load_merged_profile(prof_ref: str, profiles_dir: Path) -> dict[str, Any]:
    p0 = profiles_dir / f"{prof_ref}.toml"
    if not prof_ref or not p0.is_file():
        return {}
    prof = tomllib.loads(p0.read_text(encoding="utf-8"))
    exts = prof.pop("extends", None)
    if not isinstance(exts, list) or not exts:
        return prof
    m: dict[str, Any] = {"drift": prof.get("drift", "0.2"), "profile": prof.get("profile", prof_ref)}
    vw, vt, prm, pw, pt, req, cs, dc = [], [], {}, {}, {}, {}, {}, {}
    rk_ord = {"bound": 1, "verified": 2, "killed": 3}
    for r in [*exts, prof_ref]:
        bp = prof if r == prof_ref else (tomllib.loads(p.read_text(encoding="utf-8")) if (p := profiles_dir / f"{r}.toml").is_file() else {})
        bv = bp.get("vocabulary") if isinstance(bp.get("vocabulary"), dict) else {}
        vw.extend(w for w in bv.get("when", []) if w not in vw)
        vt.extend(t for t in bv.get("then", []) if t not in vt)
        for s, d in (("params", prm), ("cases", cs), ("decisions", dc)):
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
                if k != "proof" or "proof" not in req or rk_ord.get(str(v), 0) > rk_ord.get(str(req["proof"]), 0):
                    req[k] = v
        if "kit" in bp:
            m["kit"] = bp["kit"]
    m["vocabulary"] = {"when": vw, "then": vt}
    for k, v in (("params", prm), ("requires", req), ("cases", cs), ("decisions", dc)):
        if v: m[k] = v
    if pw or pt: m["projections"] = {**({"when": pw} if pw else {}), **({"then": pt} if pt else {})}
    return m


def _strip_outside_digest(cases: dict[str, Any], decs: Any) -> None:
    for cm in (cases or {}).values():
        if isinstance(cm, dict): cm.pop("note", None)
    if isinstance(decs, dict):
        for dm in decs.values():
            if isinstance(dm, dict):
                dm.pop("owner", None)
                dm.pop("note", None)
                if dm.get("evidence") == "observed" and _is_unanchored_prose_source(str(dm.get("source", ""))): dm.pop("source", None)


def verify_contract_toml(path: Path, profiles_dir: Path) -> dict[str, Any]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    cid, appr = raw.get("id", path.stem), raw.pop("approval", None)
    raw.pop("note", None)
    if isinstance(raw.get("scope"), dict):
        raw["scope"] = {k: v for k, v in raw["scope"].items() if k not in ("code", "max_lines", "forbid_imports")}
    cases = raw.get("cases", {})
    _strip_outside_digest(cases, raw.get("decisions"))
    if isinstance(raw.get("open"), dict):
        for qm in raw["open"].values():
            if isinstance(qm, dict): qm.pop("owner", None)
    use_tbl = raw.get("use")
    prof_ref = use_tbl.get("profile", "") if isinstance(use_tbl, dict) else ""
    prof = _load_merged_profile(prof_ref, profiles_dir)
    waived = use_tbl.get("waive", {}) if isinstance(use_tbl, dict) and isinstance(use_tbl.get("waive"), dict) else {}
    _strip_outside_digest(prof.get("cases", {}), prof.get("decisions"))
    own_w = {k for cm in cases.values() if isinstance(cm, dict) for k in cm.get("when", {})}
    own_t = {k for cm in cases.values() if isinstance(cm, dict) for k in cm.get("then", {})}
    inh_cases = {k: cm for k, cm in (prof.get("cases") or {}).items() if k not in waived and isinstance(cm, dict)}
    used_w, used_t = own_w | {k for cm in inh_cases.values() for k in cm.get("when", {})}, own_t | {k for cm in inh_cases.values() for k in cm.get("then", {})}
    if isinstance(use_tbl, dict) and isinstance(uv := use_tbl.get("vocabulary"), dict):
        nw, nt = [w for w in uv.get("when", []) if w in own_w], [t for t in uv.get("then", []) if t in own_t]
        nvoc = {**({"when": nw} if nw else {}), **({"then": nt} if nt else {})}
        if nvoc: use_tbl["vocabulary"] = nvoc
        else: use_tbl.pop("vocabulary", None)
    profile_proof = ""
    if isinstance(prof.get("requires"), dict):
        profile_proof = str(prof["requires"].get("proof", ""))
        req_trim = {k: v for k, v in prof["requires"].items() if k not in ("max_lines", "forbid_imports")}
        if req_trim: prof["requires"] = req_trim
        else: prof.pop("requires", None)
    if "vocabulary" in prof:
        prof["vocabulary"] = {"when": [w for w in prof["vocabulary"].get("when", []) if w in used_w], "then": [t for t in prof["vocabulary"].get("then", []) if t in used_t]}
    if isinstance(raw_proj := prof.get("projections"), dict):
        pw_map = {k: v for k, v in (raw_proj.get("when") or {}).items() if k in used_w} if isinstance(raw_proj.get("when"), dict) else {}
        pt_map = {k: v for k, v in (raw_proj.get("then") or {}).items() if k in used_t} if isinstance(raw_proj.get("then"), dict) else {}
        for k, v in raw_proj.items():
            if k not in ("when", "then") and not isinstance(v, dict):
                if k in used_t and k not in pt_map: pt_map[k] = v
                elif k in used_w and k not in pw_map: pw_map[k] = v
        nproj = {**({"when": pw_map} if pw_map else {}), **({"then": pt_map} if pt_map else {})}
        if nproj: prof["projections"] = nproj
        else: prof.pop("projections", None)
    dig = dr1_digest({"contract": raw, "profiles": ({prof_ref: prof} if prof_ref else {})})
    blocked = _has_approval_blocker(raw, prof)
    appr_state = "blocked" if blocked else ("current" if isinstance(appr, dict) and appr.get("ref") == dr1_ref(dig) else ("stale" if isinstance(appr, dict) and appr.get("ref") else "absent"))
    approver = str(appr.get("by", "")) if isinstance(appr, dict) and appr.get("ref") else ""
    open_m = raw.get("open") if isinstance(raw.get("open"), dict) else {}
    own_decs = [dm for dm in (raw.get("decisions") or {}).values() if isinstance(dm, dict)] if isinstance(raw.get("decisions"), dict) else []
    decs_l = [dm for s in (raw.get("decisions"), prof.get("decisions")) if isinstance(s, dict) for dm in s.values() if isinstance(dm, dict)]
    open_cnt = len(open_m) + sum(1 for dm in own_decs if dm.get("pick", "") == "")
    exec_blk = any(isinstance(qm, dict) and qm.get("blocks") == "execution" for qm in open_m.values()) or any(dm.get("pick", "") == "" and dm.get("decide_by") == "execution" for dm in decs_l)
    rel_blk = any(isinstance(qm, dict) and qm.get("blocks") == "release" for qm in open_m.values()) or any(dm.get("pick", "") == "" and dm.get("decide_by") == "release" for dm in decs_l) or any(isinstance(cm, dict) and cm.get("status") == "deferred" for cm in cases.values())
    return {"id": cid, "digest": dig, "ref": dr1_ref(dig), "approval": appr_state, "approver": approver, "profile_proof": profile_proof, "cases": {**inh_cases, **cases}, "open_cnt": open_cnt, "exec_blk": exec_blk, "rel_blk": rel_blk}


def load_proof_events(events_paths: list[Path]) -> tuple[list[dict[str, Any]], dict[str, int], int, list[str]]:
    shards = [f for p in events_paths for f in (sorted(p.glob("*.jsonl")) if p.is_dir() else ([p] if p.is_file() else []))]
    events, gone_by_contract, incomplete_shards, errors = [], {}, 0, []
    for sf in shards:
        mp = sf.with_suffix(".meta.json")
        has_inv, c_set, t_set, snap = mp.is_file(), set(), set(), ""
        if has_inv:
            try:
                inv = validate_inventory_sidecar(mp)
                c_set, t_set, snap = inv["classes"], inv["tests"], inv["snapshot"]
            except Exception as exc:
                errors.append(f"{mp.name}: {exc}")
                continue
        ev_cnt = 0
        for idx, line in enumerate(sf.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip(): continue
            try: ev = validate_event_line(line)
            except Exception as exc:
                errors.append(f"events:{sf.name}:{idx}: DR-E701 {exc}")
                continue
            ev_cnt += 1
            tid = ev["test"].split("[", 1)[0]
            cls = tid.split("#", 1)[0] if "#" in tid else ""
            if not has_inv or cls not in c_set or tid not in t_set:
                gone_by_contract[ev["contract"]] = gone_by_contract.get(ev["contract"], 0) + 1
            else: events.append(ev)
        if has_inv and snap and t_set and ev_cnt == 0: incomplete_shards += 1
    return events, gone_by_contract, incomplete_shards, errors


def _proof_rank(floor: str) -> int:
    return {"killed": 3, "verified": 2, "bound": 1}.get(floor, 0)


def evaluate_contract(contract: dict[str, Any], cfg_state: str, events: list[dict[str, Any]], gone: int, incomplete_shards: int, ev_errors: list[str], policy: dict[str, Any] | None = None, min_proof: str = "verified", phase: str = "", total_open: int | None = None) -> dict[str, Any]:
    cid, dig, pol = contract["id"], contract["digest"], policy or {}
    pol_active = pol.get("pack") == "core@1"
    matching, ignored = [], 0
    for ev in events:
        if ev["contract"] == cid:
            if digest_matches(ev["digest"], dig):
                matching.append(ev)
            else:
                ignored += 1
    latest: dict[str, dict[str, Any]] = {}
    superseded = 0
    for ev in matching:
        superseded += 1 if ev["test"] in latest else 0
        latest[ev["test"]] = ev
    active = list(latest.values())
    results: list[dict[str, Any]] = []
    for case_id in sorted(contract["cases"]):
        cm = contract["cases"][case_id]
        if isinstance(cm, dict) and "status" in cm:
            continue
        for lv in (cm.get("at") or ["*"]):
            cov = [ev for ev in active if case_id in ev["cases"] and (lv == "*" or ev["level"] == lv)]
            st = "missing" if not cov else ("red" if any(ev["outcome"] != "passed" for ev in cov) else ("verified" if any(case_id in ev["read"] for ev in cov) else "bound"))
            results.append({"case": case_id, "level": lv, "state": st})
    reasons: list[str] = []
    if cfg_state == "missing": reasons.append("config.missing")
    elif cfg_state != "current": reasons.extend((["config.findings"] if cfg_state == "stale" else []) + [f"config.approval.{cfg_state}"])
    if contract["approval"] != "current": reasons.extend((["contract.findings"] if contract["approval"] == "stale" else []) + [f"contract.approval.{contract['approval']}"])
    elif pol_active and isinstance(pol.get("approvers"), list) and pol["approvers"] and contract.get("approver", "") not in pol["approvers"]: reasons.append("contract.approval.unlisted")
    tot_open = contract.get("open_cnt", 0) if total_open is None else total_open
    if pol_active and isinstance(pol.get("max_open"), int) and not isinstance(pol.get("max_open"), bool) and pol["max_open"] > 0 and contract.get("open_cnt", 0) > 0 and tot_open > pol["max_open"]: reasons.append("policy.max_open")
    if contract.get("exec_blk"): reasons.append("contract.blocked.execution")
    if phase == "release" and contract.get("rel_blk"): reasons.append("contract.blocked.release")
    if ev_errors: reasons.append("events.invalid")
    if incomplete_shards > 0: reasons.append("shard.incomplete")
    eff_rank = max(_proof_rank(min_proof), _proof_rank(str(pol.get("proof", "")) if pol_active else ""), _proof_rank(str(contract.get("profile_proof", ""))))
    allowed = ("verified",) if eff_rank >= 2 else ("verified", "bound")
    if gone > 0 or incomplete_shards > 0 or not results or any(r["state"] not in allowed for r in results): reasons.append("proof.not_green")
    return {"id": cid, "digest": dig, "ref": contract["ref"], "approval": contract["approval"], "ok": not reasons, "reasons": reasons, "ignored": ignored, "superseded": superseded, "gone": gone, "results": results}


def run_self_test() -> int:
    assert canonical_json(-0.0) == "0" and canonical_json(1e21) == "1e+21" and canonical_json(1e-6) == "0.000001" and canonical_json(1e-7) == "1e-7"
    assert canonical_json({"\ue000": 1, "\U0001f600": 2}) == '{"\U0001f600":2,"\ue000":1}'
    for bad in (1 << 53, -(1 << 53), float("nan"), float("inf")):
        try:
            canonical_json(bad)
            raise AssertionError(f"expected ValueError for {bad}")
        except ValueError:
            pass
    for bad_ev in (
        '{"test":"t#1","test":"t#2","contract":"a","cases":["c"],"level":"unit","outcome":"passed"}',
        '{"test":"t#1","contract":"a","cases":["c"],"level":"unit","outcome":"passed","extra":1}',
        '{"test":"t#1","contract":"a","cases":["c"],"level":"unit","outcome":"passed","read":["other"]}',
        '{"test":"t#1","contract":"Bad_Id","cases":["c"],"level":"unit","outcome":"passed"}',
        '{"test":"t#1","contract":"a","cases":["c"],"level":"Unit","outcome":"passed"}',
        '{"test":"t#1","contract":"a","cases":["c"],"level":"unit","outcome":"passed","digest":"dr1:UPPER0000000"}',
        '{"a":' * 65 + '1' + '}' * 65,
    ):
        try:
            validate_event_line(bad_ev)
            raise AssertionError(f"expected ValueError for {bad_ev}")
        except ValueError:
            pass
    valid_inv = json.dumps({"version": 1, "classes": ["a.mjs", "b.mjs"], "tests": ["a.mjs#t1", "b.mjs#t2"], "snapshot": "0123456789abcdef0123456789abcdef01234567", "pack_ref": "dr1:0123456789ab", "touched": ["src/a.mjs", "src/b.mjs"], "inputs": {"a.mjs#t1": {"src/a.mjs": "sha256:111"}}, "env": {"toolchain": "v1", "deps": "d1", "config": "c1", "runner": "r1", "drift": "0.3.0", "adapter": "js", "policy": "none"}})
    assert len(validate_inventory_text(valid_inv)["tests"]) == 2
    for bad_inv in (
        '{"version":2,"classes":[],"tests":[]}',
        '{"version":true,"classes":[],"tests":[]}',
        '{"version":1,"classes":["b","a"],"tests":[]}',
        '{"version":1,"classes":["a/b"],"tests":[]}',
        '{"version":1,"classes":["a"],"tests":["other#t1"]}',
        '{"version":1,"classes":["a"],"tests":["a#t1"],"snapshot":"not-a-hex-oid"}',
        '{"version":1,"classes":["a"],"tests":["a#t1"],"pack_ref":"dr1:bad"}',
        '{"version":1,"classes":["a"],"tests":["a#t1"],"touched":["/abs/path"]}',
        '{"version":1,"classes":["a"],"tests":["a#t1"],"touched":["../escape"]}',
        '{"version":1,"classes":["a"],"tests":["a#t1"],"inputs":{"unknown#t":{"f":"1"}}}',
        '{"version":1,"classes":["a"],"tests":["a#t1"],"env":{"toolchain":"v1"}}',
        '{"version":1,"classes":["a"],"tests":["a#t1"],"extra":1}',
    ):
        try:
            validate_inventory_text(bad_inv)
            raise AssertionError(f"expected ValueError for {bad_inv}")
        except ValueError:
            pass
    assert _is_unanchored_prose_source("observed in legacy prod traffic") and _is_unanchored_prose_source("SPEC.md#D209")
    assert not _is_unanchored_prose_source("src/main/java/example/items/ItemServer.java") and not _is_unanchored_prose_source("ADR-0012")
    assert _has_approval_blocker({"open": {"q": {"ask": "?", "blocks": "approval"}}}, {}) and not _has_approval_blocker({"open": {"q": {"ask": "?", "blocks": "execution"}}}, {})
    assert _has_approval_blocker({"scope": {"indirect": "unknown"}}, {}) and _has_approval_blocker({"cases": {"c": {"then": {"x": "todo"}}}}, {})
    print("drift_verify.py self-test: ok (RFC 8785 JCS, event & full inventory schema vectors passed)")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return run_self_test()
    ap = argparse.ArgumentParser(prog="drift_verify.py")
    ap.add_argument("targets", nargs="+", type=Path)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--profiles", type=Path)
    ap.add_argument("--events", type=Path, action="append", required=True)
    ap.add_argument("--min-proof", choices=("bound", "verified"), default="verified")
    ap.add_argument("--phase", choices=("execution", "release"), default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    cfg_state, _, pol = verify_config_toml(args.config)
    profiles_dir = args.profiles or (args.config.parent / "profiles")
    contracts_files: list[Path] = []
    for t in args.targets:
        contracts_files.extend(sorted(t.glob("*.toml")) if t.is_dir() else [t])
    events, gone_map, inc_shards, ev_errors = load_proof_events(args.events)
    by_contract: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        by_contract.setdefault(ev["contract"], []).append(ev)
    parsed_contracts = [verify_contract_toml(cf, profiles_dir) for cf in contracts_files]
    tot_open = sum(c.get("open_cnt", 0) for c in parsed_contracts)
    verdicts = [evaluate_contract(c, cfg_state, by_contract.get(c["id"], []), gone_map.get(c["id"], 0), inc_shards, ev_errors, pol, args.min_proof, args.phase, tot_open) for c in parsed_contracts]
    all_ok = bool(verdicts) and all(v["ok"] for v in verdicts)
    if args.json:
        print(json.dumps({"ok": all_ok, "contracts": verdicts}, indent=2, sort_keys=True))
    else:
        for v in verdicts:
            st = "green" if v["ok"] else f"not green ({', '.join(v['reasons'])})"
            print(f"{v['id']} {v['ref']}: {st}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
