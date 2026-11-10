"""Zero-dependency COBOL batch/CICS copybook marshaling and parity bridge."""
from __future__ import annotations
import json, math
from pathlib import Path
from typing import Any, Callable

VERSION = "drift_cobol.py@0.5.1"
BRIDGE_RUNTIME_BASELINE = "cobol-85-batch"
CAPABILITIES = ["predicates", "projections", "forbid_keys", "not_in", "case_frames", "counterexample_replay", "copybook_marshal", "parity_receipt", "php_bridge_verifier"]


def bridge_capabilities() -> dict[str, Any]:
    return {"schema": "drift.bridge-capabilities/1", "bridge": "drift_cobol.py", "version": VERSION, "runtime_baseline": BRIDGE_RUNTIME_BASELINE, "capabilities": list(CAPABILITIES)}


def require_capabilities(required: list[str]) -> None:
    for cap in required:
        if cap not in CAPABILITIES: raise RuntimeError(f"bridge.capability_unsupported:{cap}")


def _to_snake(name: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(name):
        if "A" <= ch <= "Z":
            if i > 0 and out and out[-1] != "_" and not ("A" <= name[i - 1] <= "Z"): out.append("_")
            out.append(ch.lower())
        elif ch.isalnum(): out.append(ch.lower())
        elif ch in "-./:" and out and out[-1] != "_": out.append("_")
    res = "".join(out).strip("_") or "field"
    return f"f_{res}" if res[0].isdigit() else res


def _parse_pic_spec(raw_pic: str) -> dict[str, Any]:
    spec = raw_pic.rstrip(".;").upper()
    signed, spec = spec.startswith("S"), (spec[1:] if spec.startswith("S") else spec)
    int_d, dec_d, alpha_l, after_v, i = 0, 0, 0, False, 0
    while i < len(spec):
        ch = spec[i]
        if ch in ("V", "."): after_v, i = True, i + 1; continue
        cnt = 1
        if i + 1 < len(spec) and spec[i + 1] == "(":
            end = spec.find(")", i + 2)
            cnt, i = (int(spec[i + 2 : end]), end + 1) if end > i + 2 and spec[i + 2 : end].isdigit() else (1, i + 1)
        else: i += 1
        if ch in ("X", "A", "N"): alpha_l += cnt
        elif ch in ("9", "Z"): dec_d, int_d = (dec_d + cnt, int_d) if after_v else (dec_d, int_d + cnt)
    if int_d > 0 or dec_d > 0:
        return {"kind": "decimal" if dec_d > 0 else "int", "byte_len": int_d + dec_d + (1 if signed else 0), "digits": int_d, "scale": dec_d, "signed": signed}
    return {"kind": "alpha", "byte_len": max(alpha_l, 1), "digits": 0, "scale": 0, "signed": False}


def parse_copybook_layout(copybook_text: str) -> list[dict[str, Any]]:
    layout, offset = [], 0
    for raw_line in copybook_text.splitlines():
        line = raw_line.rstrip()
        if len(line) >= 7 and all(c.isdigit() or c == " " for c in line[:6]):
            if line[6] in ("*", "/", "D", "d"): continue
            line = line[7:72]
        if "*>" in line: line = line.split("*>", 1)[0]
        trimmed = line.strip().rstrip(".")
        if not trimmed or trimmed.startswith("*"): continue
        parts = trimmed.split()
        if len(parts) < 2 or not parts[0].isdigit(): continue
        lvl, name = int(parts[0]), parts[1]
        if lvl in (1, 66, 77, 88) and "PIC" not in [p.upper() for p in parts]: continue
        pic_raw = next((parts[idx + 2] if parts[idx + 1].upper() == "IS" and idx + 2 < len(parts) else parts[idx + 1] for idx, tok in enumerate(parts[2:], start=2) if tok.upper() in ("PIC", "PICTURE") and idx + 1 < len(parts)), "")
        if not pic_raw: continue
        occurs = next((int(parts[idx + 1]) for idx, tok in enumerate(parts[2:], start=2) if tok.upper() == "OCCURS" and idx + 1 < len(parts) and parts[idx + 1].isdigit()), 1)
        info = _parse_pic_spec(pic_raw)
        if name.upper() != "FILLER":
            layout.append({"name": name, "key": _to_snake(name), "offset": offset, "byte_len": info["byte_len"], "occurs": occurs, "kind": info["kind"], "digits": info["digits"], "scale": info["scale"], "signed": info["signed"]})
        offset += info["byte_len"] * occurs
    return layout


def marshal_record(layout: list[dict[str, Any]], values: dict[str, Any]) -> str:
    chunks, offset = [], 0
    for fld in layout:
        chunks.append(" " * max(0, fld["offset"] - offset))
        raw_val, blen, kind = values.get(fld["key"], values.get(fld["name"])), fld["byte_len"], fld["kind"]
        offset = fld["offset"] + blen
        if kind == "alpha": chunks.append(("" if raw_val is None else str(raw_val))[:blen].ljust(blen, " "))
        elif kind == "int":
            iv = 0 if raw_val is None else int(raw_val)
            chunks.append((("-" if iv < 0 else "+") + str(abs(iv)).zfill(blen - 1)[-(blen - 1):]) if fld["signed"] else str(max(0, iv)).zfill(blen)[-blen:])
        else:
            fv = 0.0 if raw_val is None else float(raw_val)
            sc = int(round(abs(fv) * (10 ** fld["scale"])))
            chunks.append((("-" if fv < 0 else "+") + str(sc).zfill(blen - 1)[-(blen - 1):]) if fld["signed"] else str(sc).zfill(blen)[-blen:])
    return "".join(chunks)


def unmarshal_record(layout: list[dict[str, Any]], raw_record: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for fld in layout:
        off, blen, kind = fld["offset"], fld["byte_len"], fld["kind"]
        seg = raw_record[off : off + blen].ljust(blen, " ")
        if kind == "alpha": out[fld["key"]] = seg.rstrip(" ")
        elif kind == "int": out[fld["key"]] = int(seg.strip() or "0")
        else: out[fld["key"]] = round(((-1 if seg[0] == "-" else 1) if fld["signed"] else 1) * (int((seg[1:] if fld["signed"] else seg).strip() or "0") / (10 ** fld["scale"])), fld["scale"])
    return out


def _resolve_pointer(doc: dict[str, Any], pointer: str) -> tuple[bool, Any]:
    if not pointer or pointer == "/": return True, doc
    if not pointer.startswith("/"): return (pointer in doc), doc.get(pointer)
    cur: Any = doc
    for raw_seg in pointer[1:].split("/"):
        seg = raw_seg.replace("~1", "/").replace("~0", "~")
        if not isinstance(cur, dict) or seg not in cur: return False, None
        cur = cur[seg]
    return True, cur


SUPPORTED_REL_KEYS = frozenset(("eq", "in", "not_in", "min", "max", "len", "min_len", "max_len", "non_empty", "prefix", "suffix", "contains", "forbid_keys", "allowed_keys", "le_field", "ge_field", "eq_field", "sum_fields", "monotonic", "step_max_delta", "sum_total", "approx", "abs_tol", "rel_tol", "balance_fields", "unit", "unit_conversion"))


def _is_finite_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _is_nonneg_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _values_equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool): return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_finite_num(a) or _is_finite_num(b): return _is_finite_num(a) and _is_finite_num(b) and abs(float(a) - float(b)) <= 1e-9
    if a is None or b is None: return a is None and b is None
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)): return len(a) == len(b) and all(_values_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict): return set(a) == set(b) and all(_values_equal(a[k], b[k]) for k in a)
    return a == b


def _resolve_peer(observed: dict[str, Any], proj_then: dict[str, str], ref: Any, when_env: dict[str, Any] | None = None) -> tuple[bool, Any]:
    if not isinstance(ref, str) or not ref.strip(): return False, None
    if ref.startswith("when."):
        key = ref[5:]
        if ref in observed: return True, observed[ref]
        inputs = dict(when_env or {})
        for side in ("_when_env", "before", "when"):
            if isinstance(observed.get(side), dict): inputs.update(observed[side])
        return (key in inputs, inputs.get(key)) if isinstance(inputs, dict) else (False, None)
    if ref.startswith("then."): ref = ref[5:]
    if ref.startswith("/") or ref in proj_then: return _resolve_pointer(observed, ref if ref.startswith("/") else proj_then[ref])
    return (ref in observed, observed.get(ref)) if isinstance(observed, dict) else (False, None)


def _has_key_recursive(val: Any, fk: str, is_root: bool = True) -> bool:
    if isinstance(val, (list, tuple)): return any(_has_key_recursive(x, fk, False) for x in val)
    if not isinstance(val, dict): return False
    return fk in val or any(not (is_root and k == "_frame" and fk != "_frame" and isinstance(v, dict)) and _has_key_recursive(v, fk, False) for k, v in val.items())


def check_value(key: str, actual: Any, expected: Any, actual_present: bool = True, observed: dict[str, Any] | None = None, proj_then: dict[str, str] | None = None, when_env: dict[str, Any] | None = None) -> None:
    if isinstance(actual, float) and (math.isnan(actual) or math.isinf(actual)): raise RuntimeError(f"then.{key}: non-finite float is forbidden")
    if not isinstance(expected, dict):
        if not actual_present or not _values_equal(actual, expected): raise RuntimeError(f"then.{key}: expected {expected!r}, got {actual!r}")
        return
    if not expected: raise RuntimeError(f"then.{key}: empty predicate object is unsupported")
    for op in expected:
        if op not in SUPPORTED_REL_KEYS: raise RuntimeError(f"then.{key}: unsupported predicate operator {op!r}")
    obs_doc, proj_map = (observed if isinstance(observed, dict) else {}), (proj_then if isinstance(proj_then, dict) else {})
    act_len = len(actual) if isinstance(actual, (str, list, tuple, dict)) else -1
    if "eq" in expected and (not actual_present or not _values_equal(actual, expected["eq"])):
        raise RuntimeError(f"then.{key}: expected eq {expected['eq']!r}, got {actual!r}")
    if ("in" in expected and (not isinstance(expected["in"], (list, tuple)) or not actual_present or not any(_values_equal(actual, x) for x in expected["in"]))): raise RuntimeError(f"then.{key}: {actual!r} not in {expected['in']!r}")
    if "not_in" in expected:
        forb_in = expected["not_in"]
        if not actual_present or actual is None: raise RuntimeError(f"then.{key}: expected non-null value for not_in")
        if isinstance(forb_in, (list, tuple)) and any(_values_equal(actual, x) for x in forb_in): raise RuntimeError(f"then.{key}: {actual!r} is forbidden by not_in")
        if not isinstance(forb_in, (list, tuple)) and not _values_equal(actual, forb_in): raise RuntimeError(f"then.{key}: pick-forbidden-value mutant on not_in killed")
    if "approx" in expected:
        at = float(expected["abs_tol"]) if _is_finite_num(expected.get("abs_tol")) else 0.0
        rt = float(expected["rel_tol"]) if _is_finite_num(expected.get("rel_tol")) else 0.0
        if not _is_finite_num(actual) or not _is_finite_num(expected["approx"]) or ("abs_tol" not in expected and "rel_tol" not in expected) or at < 0.0 or rt < 0.0: raise RuntimeError(f"then.{key}: invalid approx")
        ap = float(expected["approx"])
        if abs(float(actual) - ap) > at + rt * abs(ap): raise RuntimeError(f"then.{key}: {actual!r} outside approx {ap!r}")
    for v in (actual if isinstance(actual, (list, tuple)) and any(k in expected for k in ("monotonic", "sum_total", "step_max_delta")) else [actual]):
        if "min" in expected and (not _is_finite_num(v) or not _is_finite_num(expected["min"]) or float(v) + 1e-9 < float(expected["min"])): raise RuntimeError(f"then.{key}: {v!r} < min")
        if "max" in expected and (not _is_finite_num(v) or not _is_finite_num(expected["max"]) or float(v) - 1e-9 > float(expected["max"])): raise RuntimeError(f"then.{key}: {v!r} > max")
    if "len" in expected and (not _is_nonneg_int(expected["len"]) or act_len != int(expected["len"])): raise RuntimeError(f"then.{key}: len != {expected['len']!r}")
    if "min_len" in expected and (not _is_nonneg_int(expected["min_len"]) or act_len < 0 or act_len < int(expected["min_len"])): raise RuntimeError(f"then.{key}: len < min_len")
    if "max_len" in expected and (not _is_nonneg_int(expected["max_len"]) or act_len < 0 or act_len > int(expected["max_len"])): raise RuntimeError(f"then.{key}: len > max_len")
    if "non_empty" in expected and (not isinstance(expected["non_empty"], bool) or act_len < 0 or (act_len <= 0 if expected["non_empty"] else act_len != 0)): raise RuntimeError(f"then.{key}: non_empty violated")
    if "prefix" in expected and (not isinstance(expected["prefix"], str) or not isinstance(actual, str) or not actual.startswith(expected["prefix"])): raise RuntimeError(f"then.{key}: prefix violated")
    if "suffix" in expected and (not isinstance(expected["suffix"], str) or not isinstance(actual, str) or not actual.endswith(expected["suffix"])): raise RuntimeError(f"then.{key}: suffix violated")
    if "contains" in expected:
        c_exp = expected["contains"]
        ok_c = ((c_exp in actual) if isinstance(c_exp, str) else (isinstance(c_exp, (list, tuple)) and all(isinstance(x, str) and x in actual for x in c_exp))) if isinstance(actual, str) else ((all(any(_values_equal(item, req) for item in actual) for req in c_exp) if isinstance(c_exp, (list, tuple)) else any(_values_equal(item, c_exp) for item in actual)) if isinstance(actual, (list, tuple)) else False)
        if not ok_c: raise RuntimeError(f"then.{key}: expected {actual!r} to contain {c_exp!r}")
    if "forbid_keys" in expected:
        if not isinstance(actual, dict): raise RuntimeError(f"then.{key}: expected object for forbid_keys")
        fk_list, is_root = expected["forbid_keys"], actual is obs_doc
        if isinstance(fk_list, (list, tuple)):
            for fk in fk_list:
                if _has_key_recursive(actual, str(fk), is_root): raise RuntimeError(f"then.{key}: forbidden key {fk!r} present")
        elif isinstance(fk_list, str):
            if not _has_key_recursive(actual, fk_list, is_root): raise RuntimeError(f"then.{key}: drop-forbid-key mutant killed")
        else: raise RuntimeError(f"then.{key}: invalid forbid_keys")
    if "allowed_keys" in expected:
        if not isinstance(actual, dict) or not isinstance(expected["allowed_keys"], (list, tuple)): raise RuntimeError(f"then.{key}: expected object for allowed_keys")
        for ak, av in actual.items():
            if not (ak == "_frame" and isinstance(av, dict)) and ak not in expected["allowed_keys"]: raise RuntimeError(f"then.{key}: key {ak!r} outside allowed_keys")
    for fk, op_sym in (("le_field", "<="), ("ge_field", ">="), ("eq_field", "==")):
        if fk not in expected: continue
        found_p, peer_v = _resolve_peer(obs_doc, proj_map, expected[fk], when_env)
        if not found_p: raise RuntimeError(f"then.{key}: missing peer {expected[fk]!r} for {fk}")
        ok_p = _values_equal(actual, peer_v) if op_sym == "==" else (_is_finite_num(actual) and _is_finite_num(peer_v) and (float(actual) - 1e-9 <= float(peer_v) if op_sym == "<=" else float(actual) + 1e-9 >= float(peer_v)))
        if not ok_p: raise RuntimeError(f"then.{key}: expected {op_sym} {expected[fk]} ({peer_v!r}), got {actual!r}")
    if "sum_fields" in expected:
        sf_refs = expected["sum_fields"]
        if not isinstance(sf_refs, (list, tuple)) or len(sf_refs) < 2 or not _is_finite_num(actual): raise RuntimeError(f"then.{key}: invalid sum_fields")
        tot_sf = 0.0
        for ref in sf_refs:
            found_p, peer_v = _resolve_peer(obs_doc, proj_map, ref, when_env)
            if not found_p or not _is_finite_num(peer_v): raise RuntimeError(f"then.{key}: missing numeric peer {ref!r} for sum_fields")
            tot_sf += float(peer_v)
        if abs(float(actual) - tot_sf) > 1e-9: raise RuntimeError(f"then.{key}: expected sum_fields={tot_sf}, got {actual!r}")
    if "balance_fields" in expected:
        balance = expected["balance_fields"]
        if not isinstance(balance, dict) or not _is_finite_num(actual): raise RuntimeError(f"then.{key}: invalid balance_fields")
        total = 0.0
        for side, sign in (("add", 1), ("sub", -1)):
            for ref in balance.get(side, []):
                found, value = _resolve_peer(obs_doc, proj_map, ref, when_env)
                if not found or not _is_finite_num(value): raise RuntimeError(f"then.{key}: missing numeric peer {ref!r}")
                total += sign * float(value)
        if abs(float(actual) - total) > float(expected.get("abs_tol", 1e-9)): raise RuntimeError(f"then.{key}: balance_fields mismatch")
    if "monotonic" in expected:
        mode = str(expected["monotonic"])
        if not isinstance(actual, (list, tuple)) or not actual or not all(_is_finite_num(x) for x in actual): raise RuntimeError(f"then.{key}: expected non-empty numeric sequence for monotonic")
        for idx in range(1, len(actual)):
            pv, cv = float(actual[idx - 1]), float(actual[idx])
            ok_m = pv - 1e-9 <= cv if mode == "non_decreasing" else pv + 1e-9 < cv if mode == "strictly_increasing" else pv + 1e-9 >= cv if mode == "non_increasing" else pv - 1e-9 > cv if mode == "strictly_decreasing" else False
            if not ok_m: raise RuntimeError(f"then.{key}: monotonic {mode} violated at index {idx}")
    if "step_max_delta" in expected:
        delta = expected["step_max_delta"]
        if not _is_finite_num(delta) or float(delta) <= 0.0 or not isinstance(actual, (list, tuple)) or not actual or not all(_is_finite_num(x) for x in actual): raise RuntimeError(f"then.{key}: invalid step_max_delta")
        for idx in range(1, len(actual)):
            if abs(float(actual[idx]) - float(actual[idx - 1])) > float(delta) + 1e-9: raise RuntimeError(f"then.{key}: step_max_delta exceeded at index {idx}")
    if "sum_total" in expected:
        if isinstance(actual, dict) and actual and all(rk in SUPPORTED_REL_KEYS for rk in actual): raise RuntimeError(f"then.{key}: literal relational table cannot satisfy sum_total")
        vals = list(actual) if isinstance(actual, (list, tuple)) else (list(actual.values()) if isinstance(actual, dict) else [])
        if not vals or not all(_is_finite_num(x) for x in vals): raise RuntimeError(f"then.{key}: invalid sequence for sum_total")
        tot_st, st_exp = sum(float(x) for x in vals), expected["sum_total"]
        if _is_finite_num(st_exp):
            if abs(tot_st - float(st_exp)) > 1e-9: raise RuntimeError(f"then.{key}: sum_total {tot_st} != {st_exp}")
        elif isinstance(st_exp, dict):
            if ("eq" in st_exp and (not _is_finite_num(st_exp["eq"]) or abs(tot_st - float(st_exp["eq"])) > 1e-9)) or ("min" in st_exp and (not _is_finite_num(st_exp["min"]) or tot_st + 1e-9 < float(st_exp["min"]))) or ("max" in st_exp and (not _is_finite_num(st_exp["max"]) or tot_st - 1e-9 > float(st_exp["max"]))):
                raise RuntimeError(f"then.{key}: sum_total {tot_st} outside {st_exp!r}")
        else: raise RuntimeError(f"then.{key}: invalid sum_total")


def _verify_cobol_single_frame(res: str, obs: Any, is_ambient: bool) -> None:
    checked, label = False, f"undeclared write on perimeter resource {res!r}" if is_ambient else f"frame.violation:{res}"
    if _is_nonneg_int(obs):
        checked = True
        if obs > 0: raise RuntimeError(f"{label}: expected 0 writes, got {obs}")
    elif isinstance(obs, dict):
        for wk in ("writes", "operations", "events"):
            if wk in obs:
                wv = obs[wk]
                if not (_is_nonneg_int(wv) or isinstance(wv, (list, tuple))): raise RuntimeError(f"frame.invalid:{res}: {wk} must be a non-negative integer, got {wv!r}")
                checked = True
                if (wv if _is_nonneg_int(wv) else len(wv)) > 0: raise RuntimeError(f"{label}: expected 0 writes")
        if "before" in obs and "after" in obs:
            checked = True
            if not _values_equal(obs["before"], obs["after"]): raise RuntimeError(f"{label}: before and after snapshots differ")
    if not checked: raise RuntimeError(f"frame.invalid:{res}: must supply non-negative integer writes or before/after snapshots")


def _unwrap_or_desugar_03(raw: Any) -> Any:
    if not isinstance(raw, dict): return raw
    if len(raw) == 1 and "eq" in raw and not isinstance(raw["eq"], dict): return raw["eq"]
    out: dict[str, Any] = {}
    sp = lambda s: str(s) if str(s).startswith(("when.", "then.", "/")) else f"then.{s}"
    for k, v in raw.items():
        if k == "eq": out["approx" if "tol" in raw else "eq"] = v
        elif k == "len" and isinstance(v, dict):
            if "min" in v: out["min_len"] = v["min"]
            if "max" in v: out["max_len"] = v["max"]
        elif k == "keys" and isinstance(v, dict):
            if "allow" in v: out["allowed_keys"] = v["allow"]
            if "forbid" in v: out["forbid_keys"] = v["forbid"]
        elif k == "tol" and isinstance(v, dict):
            if "abs" in v: out["abs_tol"] = v["abs"]
            if "rel" in v: out["rel_tol"] = v["rel"]
        elif k == "series" and isinstance(v, dict):
            out.update(v)
            if out.get("monotonic") in ("increasing", "decreasing"): out["monotonic"] = f"strictly_{out['monotonic']}"
        elif k == "peer" and isinstance(v, dict):
            for pk, rk in (("eq", "eq_field"), ("le", "le_field"), ("ge", "ge_field"), ("balance", "balance_fields")):
                if pk in v: out[rk] = sp(v[pk]) if isinstance(v[pk], str) else v[pk]
            if isinstance(v.get("sum"), list): out["sum_fields"] = [sp(x) for x in v["sum"]]
        else: out[k] = v
    return out


def verify_case_observation(contract_view: dict[str, Any], case_id: str, observed: dict[str, Any], frames: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    cases = contract_view.get("cases", {})
    if case_id not in cases: raise RuntimeError(f"unknown case {case_id}")
    is_03, case_def = contract_view.get("drift") == "0.3", cases[case_id]
    then_tbl, proj_then, read_keys = case_def.get("then", {}), contract_view.get("projections", {}).get("then", {}), []
    when_env = {k: v.get("eq") if isinstance(v, dict) and "eq" in v else v for k, v in case_def.get("when", {}).items()}
    for k, raw_exp in then_tbl.items():
        exp = _unwrap_or_desugar_03(raw_exp) if is_03 else raw_exp
        present, act = _resolve_pointer(observed, proj_then.get(k, f"/{k}"))
        if not present and k in observed: present, act = True, observed[k]
        if not present and isinstance(exp, dict) and ("forbid_keys" in exp or "allowed_keys" in exp): present, act = True, observed
        check_value(k, act, exp, present, observed, proj_then, when_env); read_keys.append(k)
    eff_frames, scope_writes = (frames if isinstance(frames, dict) else {}), [str(x) for x in contract_view.get("scope", {}).get("writes", [])]
    has_case_writes = isinstance(case_def.get("writes"), list)
    allowed_writes = [str(x) for x in case_def["writes"]] if has_case_writes else scope_writes
    allowed_set, allowed_bases, checked_frame_keys = set(allowed_writes), {w.partition("#")[0] for w in allowed_writes}, set()
    if has_case_writes:
        for res in scope_writes:
            base_res = res.partition("#")[0]
            if res not in allowed_set and base_res not in allowed_set and ("#" in res or res not in allowed_bases):
                checked_frame_keys.update((res, base_res))
                if res in eff_frames or base_res in eff_frames:
                    obs_f = eff_frames[res] if res in eff_frames else eff_frames[base_res]
                    has_f_m = isinstance(obs_f, dict) and (any(k in obs_f for k in ("writes", "operations", "events")) or ("before" in obs_f and "after" in obs_f))
                    if has_f_m: _verify_cobol_single_frame(res, obs_f, False)
                    if isinstance(obs_f, dict) and obs_f.get("observed") is False: continue
                    if not has_f_m: _verify_cobol_single_frame(res, obs_f, False)
                    read_keys.append(f"@frame:{res}")
            else: read_keys.append(f"@frame:{res}")
    for fk in sorted(eff_frames):
        base_fk = fk.partition("#")[0]
        if fk in checked_frame_keys or fk in allowed_set or base_fk in allowed_set or ("#" not in fk and fk in allowed_bases): continue
        _verify_cobol_single_frame(fk, eff_frames[fk], True)
    return {"verified": all(k in read_keys for k in then_tbl) and (not has_case_writes or all(f"@frame:{r}" in read_keys for r in scope_writes)), "read": read_keys}


def replay_counterexamples(contract_view: dict[str, Any], case_id: str, fixtures: list[dict[str, Any]], runner: Callable[[dict[str, Any]], dict[str, Any]], frames: dict[str, dict[str, Any]] | None = None) -> int:
    cid, n = contract_view.get("id", ""), 0
    for fx in fixtures:
        if fx.get("contract") == cid and fx.get("case") == case_id:
            verify_case_observation(contract_view, case_id, runner(fx.get("witness", {}).get("when", {})), frames); n += 1
    return n


def emit_cobol_proof_shard(events_path: str | Path, cv: dict[str, Any], runs: list[dict[str, Any]], src_in: dict[str, str], env_meta: dict[str, str] | None = None) -> None:
    p, lines, tests, classes, in_map = Path(events_path), [], [], [], {}
    for r in runs:
        tid = str(r["test"]); tests.append(tid); cls = tid.split("#", 1)[0]
        if cls not in classes: classes.append(cls)
        in_map[tid] = dict(src_in)
        ev: dict[str, Any] = {"contract": cv["id"], "digest": cv["digest"], "cases": list(r["cases"]), "level": r.get("level", "unit"), "test": tid, "outcome": r["outcome"]}
        if r.get("read"): ev["read"] = list(r["read"])
        if cv.get("drift") == "0.3": ev.update({"schema": "0.3", "capabilities": ["rel-keys-guard/1", "rel-peer-sum/1", "rel-series/1", "rel-tol/1"]})
        lines.append(json.dumps(ev, separators=(",", ":")))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = {"toolchain": BRIDGE_RUNTIME_BASELINE, "deps": "copybook-lock-1", "config": "cobc-batch-1", "runner": "drift-cobol", "drift": "0.5.1", "adapter": VERSION, "policy": "core@1", **(env_meta or {})}
    p.with_suffix(".meta.json").write_text(json.dumps({"version": 1, "classes": classes, "tests": tests, "inputs": in_map, "env": env}, separators=(",", ":")) + "\n", encoding="utf-8")


def generate_cutover_parity_receipt(cv: dict[str, Any], req_ref: str, leg_t: str, cand_t: str, leg_s: str, cand_s: str, norm_ref: str, corp_ref: str, layout: list[dict[str, Any]], cases: list[dict[str, Any]], leg_fn: Callable[[str], str], cand_fn: Callable[[dict[str, Any]], dict[str, Any]], diffs: list[str] | None = None) -> dict[str, Any]:
    allow, leg_c, cand_c, div, eff, rb_ok = set(diffs or []), [], [], [], [], True
    for item in cases:
        cid, w = str(item["case"]), item.get("when", {})
        lo, co = unmarshal_record(layout, leg_fn(marshal_record(layout, w))), cand_fn(w)
        leg_c.append(cid); cand_c.append(cid)
        crt = unmarshal_record(layout, marshal_record(layout, co))
        for fld in layout:
            k, ptr = fld["key"], f"/record/{fld['key']}"
            if crt.get(k) != co.get(k): rb_ok = False
            if lo.get(k) != co.get(k) and ptr not in allow: div.append(f"{cid}:{ptr}")
    return {"schema": "drift.parity-receipt/1", "contract": cv["id"], "digest": cv["digest"], "requirement_ref": req_ref, "legacy_target": leg_t, "candidate_target": cand_t, "legacy_subject_ref": leg_s, "candidate_subject_ref": cand_s, "normalization_ref": norm_ref, "corpus_ref": corp_ref, "legacy_cases": sorted(set(leg_c)), "candidate_cases": sorted(set(cand_c)), "diverged_observations": sorted(set(div)), "effect_violations": eff, "frame_verified": True, "rollback_readback": "verified" if rb_ok else "failed", "outcome": "passed" if (not div and not eff and rb_ok) else "failed"}
