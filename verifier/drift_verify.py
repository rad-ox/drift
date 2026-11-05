#!/usr/bin/env python3
"""DRIFT Independent Reference Proof Verifier (MIT License).

Zero-dependency Python 3.11+ implementation of the DRIFT Proof Protocol:
1. Full RFC 8785 (JCS) Canonical JSON serialization (UTF-16 code unit key sorting,
   ECMAScript Number::toString float formatting, and +-(2^53-1) safe integer bounds).
2. Strict JSON Schema validation for <shard>.jsonl events and <shard>.meta.json sidecars.
3. Deterministic requirement state evaluation (missing, red, bound, verified) and gate verdicts.
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
META_KEYS = frozenset(("version", "classes", "tests", "snapshot", "pack_ref", "touched", "inputs", "env"))
ENV_KEYS = frozenset(("toolchain", "deps", "config", "runner", "drift", "adapter", "policy"))


def jcs_string(s: str) -> str:
    out = ['"']
    for ch in s:
        cp = ord(ch)
        if cp == 0x22:
            out.append('\\"')
        elif cp == 0x5C:
            out.append("\\\\")
        elif cp == 0x08:
            out.append("\\b")
        elif cp == 0x0C:
            out.append("\\f")
        elif cp == 0x0A:
            out.append("\\n")
        elif cp == 0x0D:
            out.append("\\r")
        elif cp == 0x09:
            out.append("\\t")
        elif cp < 0x20:
            out.append(f"\\u{cp:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


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
    neg = f < 0.0
    if neg:
        f = -f
    s = repr(f)
    if "e" in s or "E" in s:
        mant, exp_str = s.lower().split("e", 1)
        digits = mant.replace(".", "").rstrip("0") or "0"
        n = int(exp_str) + 1
    else:
        if "." in s:
            int_p, frac_p = s.split(".", 1)
            raw = (int_p + frac_p).lstrip("0")
            digits = raw.rstrip("0") or "0"
            n = len(int_p) if int_p != "0" else -(len(frac_p) - len(frac_p.lstrip("0")))
        else:
            digits = s.rstrip("0") or "0"
            n = len(s)
    k = len(digits)
    if k <= n <= 21:
        body = digits + ("0" * (n - k))
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + ("0" * (-n)) + digits
    else:
        m = digits if k == 1 else (digits[0] + "." + digits[1:])
        sign = "+" if (n - 1) >= 0 else "-"
        body = f"{m}e{sign}{abs(n - 1)}"
    return f"-{body}" if neg else body


def canonical_json(obj: Any) -> str:
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
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
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in pairs:
            if k in out:
                raise ValueError(f'duplicate key "{k}"')
            out[k] = v
        return out
    return json.loads(text, object_pairs_hook=hook)


def validate_event_line(line: str) -> dict[str, Any]:
    doc = _decode_no_dup_keys(line)
    if not isinstance(doc, dict):
        raise ValueError("not a JSON object")
    for k in doc:
        if k not in EVENT_KEYS:
            raise ValueError(f'unknown key "{k}"')
    for req in ("test", "contract", "cases", "level", "outcome"):
        if req not in doc:
            raise ValueError(f'missing required key "{req}"')
    if not isinstance(doc["test"], str) or not doc["test"].strip():
        raise ValueError("test must be a non-empty string")
    if not isinstance(doc["contract"], str) or not ID_RE.match(doc["contract"]):
        raise ValueError(f'contract "{doc.get("contract")}" is not a valid id')
    cases = doc["cases"]
    if not isinstance(cases, list) or not cases or len(set(cases)) != len(cases) or not all(isinstance(c, str) and ID_RE.match(c) for c in cases):
        raise ValueError("cases must be a non-empty array of unique case ids")
    if not isinstance(doc["level"], str) or not WORD_RE.match(doc["level"]):
        raise ValueError(f'level "{doc.get("level")}" is not a snake_case word')
    if doc["outcome"] not in OUTCOMES:
        raise ValueError(f'invalid outcome "{doc.get("outcome")}"')
    read = doc.get("read", [])
    if not isinstance(read, list) or len(set(read)) != len(read) or not all(isinstance(r, str) and r in cases for r in read):
        raise ValueError("read must be a unique subset of cases")
    digest = doc.get("digest", "")
    if digest != "" and (not isinstance(digest, str) or not DIGEST_RE.match(digest)):
        raise ValueError(f'invalid digest "{digest}"')
    return {"test": doc["test"], "contract": doc["contract"], "cases": cases, "level": doc["level"], "outcome": doc["outcome"], "read": read, "digest": digest}


def validate_inventory_text(text: str) -> dict[str, Any]:
    doc = _decode_no_dup_keys(text)
    if not isinstance(doc, dict):
        raise ValueError("inventory is not a JSON object")
    for k in doc:
        if k not in META_KEYS:
            raise ValueError(f'unknown inventory key "{k}"')
    if doc.get("version") != 1 or isinstance(doc.get("version"), bool):
        raise ValueError("inventory version must be 1")
    classes, tests = doc.get("classes"), doc.get("tests")
    if not isinstance(classes, list) or not all(isinstance(x, str) and CLASS_TOKEN_RE.match(x) for x in classes) or classes != sorted(set(classes)):
        raise ValueError("classes must be a sorted unique array of valid class names")
    c_set = set(classes)
    if not isinstance(tests, list) or not all(isinstance(x, str) and "#" in x for x in tests) or tests != sorted(set(tests)):
        raise ValueError("tests must be a sorted unique <class>#<method> array")
    for t in tests:
        cls, method = t.split("#", 1)
        if cls not in c_set or not METHOD_TOKEN_RE.match(method):
            raise ValueError(f'invalid test name "{t}"')
    t_set = set(tests)
    snap = doc.get("snapshot", "")
    if "snapshot" in doc and (not isinstance(snap, str) or not SNAPSHOT_RE.match(snap)):
        raise ValueError(f'invalid snapshot "{snap}"')
    pack_ref = doc.get("pack_ref", "")
    if "pack_ref" in doc and (not isinstance(pack_ref, str) or not PACK_REF_RE.match(pack_ref)):
        raise ValueError(f'invalid pack_ref "{pack_ref}"')
    if "touched" in doc:
        touched = doc["touched"]
        if not isinstance(touched, list) or not all(isinstance(x, str) and x.strip() for x in touched) or touched != sorted(set(touched)):
            raise ValueError("touched must be a sorted unique string array")
        for tp in touched:
            if tp.startswith("/") or "\\" in tp or any(seg in ("", ".", "..") for seg in tp.split("/")):
                raise ValueError(f'invalid touched path "{tp}"')
    if "inputs" in doc:
        raw_inputs = doc["inputs"]
        if not isinstance(raw_inputs, dict):
            raise ValueError("inputs must be an object")
        for tid, fmap in raw_inputs.items():
            if tid not in t_set or not isinstance(fmap, dict):
                raise ValueError(f'invalid inputs entry for "{tid}"')
            for fpath, oid_val in fmap.items():
                if not isinstance(fpath, str) or not fpath.strip() or not isinstance(oid_val, str) or not oid_val.strip():
                    raise ValueError(f'invalid input digest for "{tid}:{fpath}"')
    if "env" in doc:
        raw_env = doc["env"]
        if not isinstance(raw_env, dict):
            raise ValueError("env must be an object")
        for ek, ev in raw_env.items():
            if ek not in ENV_KEYS or not isinstance(ev, str) or not ev.strip():
                raise ValueError(f'invalid env key "{ek}"')
        for req_k in ENV_KEYS:
            if req_k not in raw_env:
                raise ValueError(f"env.{req_k} is missing")
    return {"classes": c_set, "tests": t_set, "snapshot": snap, "pack_ref": pack_ref}


def validate_inventory_sidecar(path: Path) -> dict[str, Any]:
    return validate_inventory_text(path.read_text(encoding="utf-8"))


def verify_config_toml(path: Path) -> tuple[str, str, dict[str, Any]]:
    if not path.is_file():
        return "missing", "", {}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    appr = raw.pop("approval", None)
    dig = dr1_digest(raw)
    pol = raw.get("policy") if isinstance(raw.get("policy"), dict) else {}
    if not isinstance(appr, dict) or not appr.get("ref"):
        return "absent", dig, pol
    st = "current" if appr["ref"] == dr1_ref(dig) else "stale"
    return st, dig, (pol if st == "current" else {})


def _is_unanchored_prose_source(raw: str) -> bool:
    s = raw.strip()
    if not s or s.startswith("ADR-") or ";" in s or "://" in s:
        return False
    if " " in s:
        return True
    if ":" in s:
        return False
    base = s.split("@", 1)[0].split("#", 1)[0].replace("\\", "/")
    dot = base.rfind(".")
    return not (0 < dot < len(base) - 1 and base[dot + 1:].isalnum() and any(c.isalpha() for c in base[dot + 1:]))


def verify_contract_toml(path: Path, profiles_dir: Path) -> dict[str, Any]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    cid = raw.get("id", path.stem)
    appr = raw.pop("approval", None)
    raw.pop("note", None)
    if isinstance(raw.get("scope"), dict):
        raw["scope"] = {k: v for k, v in raw["scope"].items() if k not in ("code", "max_lines", "forbid_imports")}
    cases = raw.get("cases", {})
    for cm in cases.values():
        if isinstance(cm, dict):
            cm.pop("note", None)
    if isinstance(raw.get("decisions"), dict):
        for dm in raw["decisions"].values():
            if isinstance(dm, dict):
                dm.pop("owner", None)
                dm.pop("note", None)
                if dm.get("evidence") == "observed" and _is_unanchored_prose_source(str(dm.get("source", ""))):
                    dm.pop("source", None)
    if isinstance(raw.get("open"), dict):
        for qm in raw["open"].values():
            if isinstance(qm, dict):
                qm.pop("owner", None)
    used_w = {k for cm in cases.values() if isinstance(cm, dict) for k in cm.get("when", {})}
    used_t = {k for cm in cases.values() if isinstance(cm, dict) for k in cm.get("then", {})}
    use_tbl = raw.get("use")
    if isinstance(use_tbl, dict) and isinstance(use_tbl.get("vocabulary"), dict):
        uv = use_tbl["vocabulary"]
        nw = [w for w in uv.get("when", []) if w in used_w]
        nt = [t for t in uv.get("then", []) if t in used_t]
        nvoc: dict[str, Any] = {}
        if nw:
            nvoc["when"] = nw
        if nt:
            nvoc["then"] = nt
        if nvoc:
            use_tbl["vocabulary"] = nvoc
        else:
            use_tbl.pop("vocabulary", None)
    prof_ref = use_tbl.get("profile", "") if isinstance(use_tbl, dict) else ""
    prof_path = profiles_dir / f"{prof_ref}.toml"
    prof = tomllib.loads(prof_path.read_text(encoding="utf-8")) if (prof_ref and prof_path.is_file()) else {}
    prof.pop("extends", None)
    profile_proof = ""
    if isinstance(prof.get("requires"), dict):
        profile_proof = str(prof["requires"].get("proof", ""))
        req_trim = {k: v for k, v in prof["requires"].items() if k not in ("max_lines", "forbid_imports")}
        if req_trim:
            prof["requires"] = req_trim
        else:
            prof.pop("requires", None)
    if "vocabulary" in prof:
        prof["vocabulary"] = {
            "when": [w for w in prof["vocabulary"].get("when", []) if w in used_w],
            "then": [t for t in prof["vocabulary"].get("then", []) if t in used_t],
        }
    dig = dr1_digest({"contract": raw, "profiles": ({prof_ref: prof} if prof_ref else {})})
    appr_state = "absent"
    approver = ""
    if isinstance(appr, dict) and appr.get("ref"):
        appr_state = "current" if appr["ref"] == dr1_ref(dig) else "stale"
        approver = str(appr.get("by", ""))
    return {
        "id": cid,
        "digest": dig,
        "ref": dr1_ref(dig),
        "approval": appr_state,
        "approver": approver,
        "profile_proof": profile_proof,
        "cases": cases,
    }


def load_proof_events(events_paths: list[Path]) -> tuple[list[dict[str, Any]], dict[str, int], int, list[str]]:
    shards: list[Path] = []
    for p in events_paths:
        if p.is_dir():
            shards.extend(sorted(p.glob("*.jsonl")))
        elif p.is_file():
            shards.append(p)
    events: list[dict[str, Any]] = []
    gone_by_contract: dict[str, int] = {}
    incomplete_shards = 0
    errors: list[str] = []
    for sf in shards:
        meta_path = sf.with_suffix(".meta.json")
        has_inv = meta_path.is_file()
        c_set, t_set, snap = set(), set(), ""
        if has_inv:
            try:
                inv = validate_inventory_sidecar(meta_path)
                c_set, t_set, snap = inv["classes"], inv["tests"], inv["snapshot"]
            except Exception as exc:
                errors.append(f"{meta_path.name}: {exc}")
                continue
        shard_ev_count = 0
        for idx, line in enumerate(sf.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                ev = validate_event_line(line)
            except Exception as exc:
                errors.append(f"events:{sf.name}:{idx}: DR-E701 {exc}")
                continue
            shard_ev_count += 1
            tid = ev["test"].split("[", 1)[0]
            cls = tid.split("#", 1)[0] if "#" in tid else ""
            if not has_inv or cls not in c_set or tid not in t_set:
                cid = ev["contract"]
                gone_by_contract[cid] = gone_by_contract.get(cid, 0) + 1
                continue
            events.append(ev)
        if has_inv and snap != "" and len(t_set) > 0 and shard_ev_count == 0:
            incomplete_shards += 1
    return events, gone_by_contract, incomplete_shards, errors


def _proof_rank(floor: str) -> int:
    return {"verified": 2, "bound": 1}.get(floor, 0)


def evaluate_contract(contract: dict[str, Any], cfg_state: str, events: list[dict[str, Any]], gone: int, incomplete_shards: int, ev_errors: list[str], policy: dict[str, Any] | None = None, min_proof: str = "verified") -> dict[str, Any]:
    cid, dig = contract["id"], contract["digest"]
    pol = policy or {}
    pol_active = pol.get("pack") == "core@1"
    matching: list[dict[str, Any]] = []
    ignored = 0
    for ev in events:
        if ev["contract"] != cid:
            continue
        if digest_matches(ev["digest"], dig):
            matching.append(ev)
        else:
            ignored += 1
    latest_by_test: dict[str, dict[str, Any]] = {}
    superseded = 0
    for ev in matching:
        tid = ev["test"]
        if tid in latest_by_test:
            superseded += 1
        latest_by_test[tid] = ev
    active_events = list(latest_by_test.values())
    results: list[dict[str, Any]] = []
    for case_id in sorted(contract["cases"]):
        cm = contract["cases"][case_id]
        levels = cm.get("at") or ["*"]
        for lv in levels:
            cov = [ev for ev in active_events if case_id in ev["cases"] and (lv == "*" or ev["level"] == lv)]
            if not cov:
                state = "missing"
            elif any(ev["outcome"] != "passed" for ev in cov):
                state = "red"
            elif any(case_id in ev["read"] for ev in cov):
                state = "verified"
            else:
                state = "bound"
            results.append({"case": case_id, "level": lv, "state": state})
    reasons: list[str] = []
    if cfg_state == "missing":
        reasons.append("config.missing")
    elif cfg_state != "current":
        if cfg_state == "stale":
            reasons.append("config.findings")
        reasons.append(f"config.approval.{cfg_state}")
    if contract["approval"] != "current":
        if contract["approval"] == "stale":
            reasons.append("contract.findings")
        reasons.append(f"contract.approval.{contract['approval']}")
    elif pol_active and isinstance(pol.get("approvers"), list) and pol["approvers"]:
        if contract.get("approver", "") not in pol["approvers"]:
            reasons.append("contract.approval.unlisted")
    if ev_errors:
        reasons.append("events.invalid")
    if incomplete_shards > 0:
        reasons.append("shard.incomplete")
    pol_floor = str(pol.get("proof", "")) if pol_active else ""
    prof_floor = str(contract.get("profile_proof", ""))
    eff_rank = max(_proof_rank(min_proof), _proof_rank(pol_floor), _proof_rank(prof_floor))
    allowed_states = ("verified",) if eff_rank >= 2 else ("verified", "bound")
    if gone > 0 or incomplete_shards > 0 or not results or any(r["state"] not in allowed_states for r in results):
        reasons.append("proof.not_green")
    return {
        "id": cid,
        "digest": dig,
        "ref": contract["ref"],
        "approval": contract["approval"],
        "ok": len(reasons) == 0,
        "reasons": reasons,
        "ignored": ignored,
        "superseded": superseded,
        "gone": gone,
        "results": results,
    }


def run_self_test() -> int:
    assert canonical_json(-0.0) == "0"
    assert canonical_json(1e21) == "1e+21"
    assert canonical_json(1e-6) == "0.000001"
    assert canonical_json(1e-7) == "1e-7"
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
    ):
        try:
            validate_event_line(bad_ev)
            raise AssertionError(f"expected ValueError for {bad_ev}")
        except ValueError:
            pass
    valid_inv = json.dumps({
        "version": 1,
        "classes": ["a.mjs", "b.mjs"],
        "tests": ["a.mjs#t1", "b.mjs#t2"],
        "snapshot": "0123456789abcdef0123456789abcdef01234567",
        "pack_ref": "dr1:0123456789ab",
        "touched": ["src/a.mjs", "src/b.mjs"],
        "inputs": {"a.mjs#t1": {"src/a.mjs": "sha256:111"}},
        "env": {"toolchain": "v1", "deps": "d1", "config": "c1", "runner": "r1", "drift": "0.3.0", "adapter": "js", "policy": "none"},
    })
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
    assert _is_unanchored_prose_source("observed in legacy prod traffic") is True
    assert _is_unanchored_prose_source("src/main/java/example/items/ItemServer.java") is False
    assert _is_unanchored_prose_source("ADR-0012") is False
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
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    cfg_state, _, pol = verify_config_toml(args.config)
    profiles_dir = args.profiles or (args.config.parent / "profiles")
    contracts_files: list[Path] = []
    for t in args.targets:
        contracts_files.extend(sorted(t.glob("*.toml")) if t.is_dir() else [t])
    events, gone_map, inc_shards, ev_errors = load_proof_events(args.events)
    verdicts = [evaluate_contract(verify_contract_toml(cf, profiles_dir), cfg_state, events, gone_map.get(cf.stem, 0), inc_shards, ev_errors, pol, args.min_proof) for cf in contracts_files]
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
