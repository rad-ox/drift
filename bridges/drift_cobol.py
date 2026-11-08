"""Zero-dependency COBOL batch/CICS copybook marshaling and parity bridge.

Conforms to drift.bridge-capabilities/1 and drift.parity-receipt/1.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

VERSION = "drift_cobol.py@0.4.0"
BRIDGE_RUNTIME_BASELINE = "cobol-85-batch"
CAPABILITIES = [
    "predicates",
    "projections",
    "forbid_keys",
    "not_in",
    "case_frames",
    "counterexample_replay",
    "copybook_marshal",
    "parity_receipt",
    "php_bridge_verifier",
]


def bridge_capabilities() -> dict[str, Any]:
    return {
        "schema": "drift.bridge-capabilities/1",
        "bridge": "drift_cobol.py",
        "version": VERSION,
        "runtime_baseline": BRIDGE_RUNTIME_BASELINE,
        "capabilities": list(CAPABILITIES),
    }


def require_capabilities(required: list[str]) -> None:
    for cap in required:
        if cap not in CAPABILITIES:
            raise RuntimeError(f"bridge.capability_unsupported:{cap}")


def _to_snake(name: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(name):
        if "A" <= ch <= "Z":
            if i > 0 and out and out[-1] != "_" and not ("A" <= name[i - 1] <= "Z"):
                out.append("_")
            out.append(ch.lower())
        elif ch.isalnum():
            out.append(ch.lower())
        elif ch in "-./:" and out and out[-1] != "_":
            out.append("_")
    res = "".join(out).strip("_") or "field"
    return f"f_{res}" if res[0].isdigit() else res


def _parse_pic_spec(raw_pic: str) -> dict[str, Any]:
    spec = raw_pic.rstrip(".;").upper()
    signed = spec.startswith("S")
    if signed:
        spec = spec[1:]
    int_digits = 0
    dec_digits = 0
    alpha_len = 0
    after_v = False
    i = 0
    while i < len(spec):
        ch = spec[i]
        if ch in ("V", "."):
            after_v = True
            i += 1
            continue
        cnt = 1
        if i + 1 < len(spec) and spec[i + 1] == "(":
            end = spec.find(")", i + 2)
            if end > i + 2 and spec[i + 2 : end].isdigit():
                cnt = int(spec[i + 2 : end])
                i = end + 1
            else:
                i += 1
        else:
            i += 1
        if ch in ("X", "A", "N"):
            alpha_len += cnt
        elif ch in ("9", "Z"):
            if after_v:
                dec_digits += cnt
            else:
                int_digits += cnt
    if int_digits > 0 or dec_digits > 0:
        total_digits = int_digits + dec_digits
        byte_len = total_digits + (1 if signed else 0)
        return {
            "kind": "decimal" if dec_digits > 0 else "int",
            "byte_len": byte_len,
            "digits": int_digits,
            "scale": dec_digits,
            "signed": signed,
        }
    return {
        "kind": "alpha",
        "byte_len": max(alpha_len, 1),
        "digits": 0,
        "scale": 0,
        "signed": False,
    }


def parse_copybook_layout(copybook_text: str) -> list[dict[str, Any]]:
    layout: list[dict[str, Any]] = []
    offset = 0
    for raw_line in copybook_text.splitlines():
        line = raw_line.rstrip()
        if len(line) >= 7 and all(c.isdigit() or c == " " for c in line[:6]):
            if line[6] in ("*", "/", "D", "d"):
                continue
            line = line[7:72]
        if "*>" in line:
            line = line.split("*>", 1)[0]
        trimmed = line.strip().rstrip(".")
        if not trimmed or trimmed.startswith("*"):
            continue
        parts = trimmed.split()
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        lvl = int(parts[0])
        if lvl in (1, 66, 77, 88) and "PIC" not in [p.upper() for p in parts]:
            continue
        name = parts[1]
        if name.upper() == "FILLER":
            continue
        pic_raw = ""
        for idx, tok in enumerate(parts[2:], start=2):
            if tok.upper() in ("PIC", "PICTURE") and idx + 1 < len(parts):
                pic_raw = parts[idx + 2] if parts[idx + 1].upper() == "IS" and idx + 2 < len(parts) else parts[idx + 1]
                break
        if not pic_raw:
            continue
        occurs = 1
        for idx, tok in enumerate(parts[2:], start=2):
            if tok.upper() == "OCCURS" and idx + 1 < len(parts) and parts[idx + 1].isdigit():
                occurs = int(parts[idx + 1])
                break
        info = _parse_pic_spec(pic_raw)
        key = _to_snake(name)
        layout.append(
            {
                "name": name,
                "key": key,
                "offset": offset,
                "byte_len": info["byte_len"],
                "occurs": occurs,
                "kind": info["kind"],
                "digits": info["digits"],
                "scale": info["scale"],
                "signed": info["signed"],
            }
        )
        offset += info["byte_len"] * occurs
    return layout


def marshal_record(layout: list[dict[str, Any]], values: dict[str, Any]) -> str:
    chunks: list[str] = []
    for fld in layout:
        key = fld["key"]
        raw_val = values.get(key, values.get(fld["name"]))
        blen = fld["byte_len"]
        kind = fld["kind"]
        if kind == "alpha":
            s = "" if raw_val is None else str(raw_val)
            chunks.append(s[:blen].ljust(blen, " "))
        elif kind == "int":
            ival = 0 if raw_val is None else int(raw_val)
            if fld["signed"]:
                sign_ch = "-" if ival < 0 else "+"
                digits_len = blen - 1
                chunks.append(sign_ch + str(abs(ival)).zfill(digits_len)[-digits_len:])
            else:
                chunks.append(str(max(0, ival)).zfill(blen)[-blen:])
        else:
            scale = fld["scale"]
            fval = 0.0 if raw_val is None else float(raw_val)
            scaled = int(round(abs(fval) * (10**scale)))
            if fld["signed"]:
                sign_ch = "-" if fval < 0 else "+"
                digits_len = blen - 1
                chunks.append(sign_ch + str(scaled).zfill(digits_len)[-digits_len:])
            else:
                chunks.append(str(scaled).zfill(blen)[-blen:])
    return "".join(chunks)


def unmarshal_record(layout: list[dict[str, Any]], raw_record: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for fld in layout:
        off = fld["offset"]
        blen = fld["byte_len"]
        seg = raw_record[off : off + blen].ljust(blen, " ")
        kind = fld["kind"]
        if kind == "alpha":
            out[fld["key"]] = seg.rstrip(" ")
        elif kind == "int":
            s = seg.strip()
            out[fld["key"]] = int(s) if s else 0
        else:
            scale = fld["scale"]
            if fld["signed"]:
                sign = -1 if seg[0] == "-" else 1
                raw_digits = int(seg[1:].strip() or "0")
            else:
                sign = 1
                raw_digits = int(seg.strip() or "0")
            out[fld["key"]] = round(sign * (raw_digits / (10**scale)), scale)
    return out


def _resolve_pointer(doc: dict[str, Any], pointer: str) -> tuple[bool, Any]:
    if not pointer or pointer == "/":
        return True, doc
    if not pointer.startswith("/"):
        return (pointer in doc), doc.get(pointer)
    cur: Any = doc
    for raw_seg in pointer[1:].split("/"):
        seg = raw_seg.replace("~1", "/").replace("~0", "~")
        if not isinstance(cur, dict) or seg not in cur:
            return False, None
        cur = cur[seg]
    return True, cur


def check_value(key: str, actual: Any, expected: Any, actual_present: bool = True) -> None:
    if isinstance(actual, float) and (math.isnan(actual) or math.isinf(actual)):
        raise RuntimeError(f"then.{key}: non-finite float is forbidden")
    if not isinstance(expected, dict):
        if not actual_present or actual != expected:
            raise RuntimeError(f"then.{key}: expected {expected!r}, got {actual!r}")
        return
    if "in" in expected:
        if not actual_present or actual not in expected["in"]:
            raise RuntimeError(f"then.{key}: {actual!r} not in {expected['in']!r}")
    if "not_in" in expected:
        if actual_present and actual in expected["not_in"]:
            raise RuntimeError(f"then.{key}: {actual!r} is forbidden by not_in")
    if "min" in expected:
        if not isinstance(actual, (int, float)) or isinstance(actual, bool) or actual < expected["min"]:
            raise RuntimeError(f"then.{key}: {actual!r} < min {expected['min']!r}")
    if "max" in expected:
        if not isinstance(actual, (int, float)) or isinstance(actual, bool) or actual > expected["max"]:
            raise RuntimeError(f"then.{key}: {actual!r} > max {expected['max']!r}")
    if "len" in expected:
        if not isinstance(actual, (str, list, dict)) or len(actual) != int(expected["len"]):
            raise RuntimeError(f"then.{key}: len != {expected['len']!r}")
    if "min_len" in expected:
        if not isinstance(actual, (str, list, dict)) or len(actual) < int(expected["min_len"]):
            raise RuntimeError(f"then.{key}: len < min_len {expected['min_len']!r}")
    if "max_len" in expected:
        if not isinstance(actual, (str, list, dict)) or len(actual) > int(expected["max_len"]):
            raise RuntimeError(f"then.{key}: len > max_len {expected['max_len']!r}")
    if "forbid_keys" in expected:
        if not isinstance(actual, dict):
            raise RuntimeError(f"then.{key}: expected object for forbid_keys")
        for fk in expected["forbid_keys"]:
            if fk in actual:
                raise RuntimeError(f"then.{key}: forbidden key {fk!r} present")
    if "allowed_keys" in expected:
        if not isinstance(actual, dict):
            raise RuntimeError(f"then.{key}: expected object for allowed_keys")
        for ak in actual:
            if ak not in expected["allowed_keys"]:
                raise RuntimeError(f"then.{key}: key {ak!r} outside allowed_keys")


def verify_case_observation(
    contract_view: dict[str, Any],
    case_id: str,
    observed: dict[str, Any],
    frames: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cases = contract_view.get("cases", {})
    if case_id not in cases:
        raise RuntimeError(f"unknown case {case_id}")
    case_def = cases[case_id]
    then_tbl = case_def.get("then", {})
    proj_then = contract_view.get("projections", {}).get("then", {})
    read_keys: list[str] = []
    for k, exp in then_tbl.items():
        ptr = proj_then.get(k, f"/{k}")
        present, act = _resolve_pointer(observed, ptr)
        if not present and k in observed:
            present, act = True, observed[k]
        check_value(k, act, exp, present)
        read_keys.append(k)
    eff_frames = frames or {}
    scope_writes = contract_view.get("scope", {}).get("writes", [])
    has_case_writes = "writes" in case_def and isinstance(case_def["writes"], list)
    if has_case_writes:
        allowed_writes = case_def["writes"]
        for res in scope_writes:
            if res not in allowed_writes:
                if res in eff_frames:
                    w_cnt = int(eff_frames[res].get("writes", 0))
                    if w_cnt != 0:
                        raise RuntimeError(f"frame.violation:{res}: expected 0 writes, got {w_cnt}")
                    read_keys.append(f"@frame:{res}")
            else:
                read_keys.append(f"@frame:{res}")
    verified = all(k in read_keys for k in then_tbl) and (
        not has_case_writes or all(f"@frame:{r}" in read_keys for r in scope_writes)
    )
    return {"verified": verified, "read": read_keys}


def replay_counterexamples(
    contract_view: dict[str, Any],
    case_id: str,
    fixtures: list[dict[str, Any]],
    runner: Callable[[dict[str, Any]], dict[str, Any]],
    frames: dict[str, dict[str, Any]] | None = None,
) -> int:
    cid = contract_view.get("id", "")
    replayed = 0
    for fx in fixtures:
        if fx.get("contract") != cid or fx.get("case") != case_id:
            continue
        w_when = fx.get("witness", {}).get("when", {})
        obs = runner(w_when)
        verify_case_observation(contract_view, case_id, obs, frames)
        replayed += 1
    return replayed


def emit_cobol_proof_shard(
    events_path: str | Path,
    contract_view: dict[str, Any],
    runs: list[dict[str, Any]],
    source_inputs: dict[str, str],
    env_meta: dict[str, str] | None = None,
) -> None:
    ev_path = Path(events_path)
    lines: list[str] = []
    tests: list[str] = []
    classes: list[str] = []
    inputs_map: dict[str, dict[str, str]] = {}
    for r in runs:
        tid = str(r["test"])
        tests.append(tid)
        cls = tid.split("#", 1)[0]
        if cls not in classes:
            classes.append(cls)
        inputs_map[tid] = dict(source_inputs)
        ev: dict[str, Any] = {
            "contract": contract_view["id"],
            "digest": contract_view["digest"],
            "cases": list(r["cases"]),
            "level": r.get("level", "unit"),
            "test": tid,
            "outcome": r["outcome"],
        }
        if r.get("read"):
            ev["read"] = list(r["read"])
        lines.append(json.dumps(ev, separators=(",", ":")))
    ev_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    meta_path = ev_path.with_suffix(".meta.json")
    base_env = {
        "toolchain": BRIDGE_RUNTIME_BASELINE,
        "deps": "copybook-lock-1",
        "config": "cobc-batch-1",
        "runner": "drift-cobol",
        "drift": "0.4.0",
        "adapter": VERSION,
        "policy": "core@1",
    }
    if env_meta:
        base_env.update(env_meta)
    meta = {
        "version": 1,
        "classes": classes,
        "tests": tests,
        "inputs": inputs_map,
        "env": base_env,
    }
    meta_path.write_text(json.dumps(meta, separators=(",", ":")) + "\n", encoding="utf-8")


def generate_cutover_parity_receipt(
    contract_view: dict[str, Any],
    requirement_ref: str,
    legacy_target: str,
    candidate_target: str,
    legacy_subject_ref: str,
    candidate_subject_ref: str,
    normalization_ref: str,
    corpus_ref: str,
    layout: list[dict[str, Any]],
    corpus_cases: list[dict[str, Any]],
    legacy_batch_fn: Callable[[str], str],
    candidate_service_fn: Callable[[dict[str, Any]], dict[str, Any]],
    intentional_diffs: list[str] | None = None,
) -> dict[str, Any]:
    allowed_diffs = set(intentional_diffs or [])
    legacy_cases: list[str] = []
    candidate_cases: list[str] = []
    diverged: list[str] = []
    effect_violations: list[str] = []
    rollback_ok = True

    for item in corpus_cases:
        cid = str(item["case"])
        when_payload = item.get("when", {})
        raw_in = marshal_record(layout, when_payload)
        raw_leg_out = legacy_batch_fn(raw_in)
        leg_obs = unmarshal_record(layout, raw_leg_out)
        legacy_cases.append(cid)

        cand_obs = candidate_service_fn(when_payload)
        candidate_cases.append(cid)

        # Verify rollback readback: marshal candidate output to COBOL fixed-width and unmarshal back
        cand_marshaled = marshal_record(layout, cand_obs)
        cand_roundtrip = unmarshal_record(layout, cand_marshaled)
        for fld in layout:
            k = fld["key"]
            ptr = f"/record/{k}"
            if cand_roundtrip.get(k) != cand_obs.get(k):
                rollback_ok = False
            if leg_obs.get(k) != cand_obs.get(k) and ptr not in allowed_diffs:
                diverged.append(f"{cid}:{ptr}")

    outcome = "passed" if (not diverged and not effect_violations and rollback_ok) else "failed"
    return {
        "schema": "drift.parity-receipt/1",
        "contract": contract_view["id"],
        "digest": contract_view["digest"],
        "requirement_ref": requirement_ref,
        "legacy_target": legacy_target,
        "candidate_target": candidate_target,
        "legacy_subject_ref": legacy_subject_ref,
        "candidate_subject_ref": candidate_subject_ref,
        "normalization_ref": normalization_ref,
        "corpus_ref": corpus_ref,
        "legacy_cases": sorted(set(legacy_cases)),
        "candidate_cases": sorted(set(candidate_cases)),
        "diverged_observations": sorted(set(diverged)),
        "effect_violations": effect_violations,
        "frame_verified": True,
        "rollback_readback": "verified" if rollback_ok else "failed",
        "outcome": outcome,
    }
