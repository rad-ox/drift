"""Zero-dependency predicate, 0.3 desugaring, and write-frame checks for COBOL bridge."""
from __future__ import annotations

import math
from typing import Any

SUPPORTED_REL_KEYS = frozenset((
    "eq", "in", "not_in", "min", "max", "len", "min_len", "max_len",
    "non_empty", "prefix", "suffix", "contains", "forbid_keys", "allowed_keys",
    "le_field", "ge_field", "eq_field", "sum_fields", "monotonic",
    "step_max_delta", "sum_total", "approx", "abs_tol", "rel_tol",
    "balance_fields", "unit", "unit_conversion",
))


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _is_u64(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _is_seq(v: Any) -> bool:
    return isinstance(v, (list, tuple))


_is_finite_num = _is_num
_is_nonneg_int = _is_u64


def _resolve_pointer(doc: dict[str, Any], pointer: str) -> tuple[bool, Any]:
    if not pointer or pointer == "/": return True, doc
    if not pointer.startswith("/"): return (pointer in doc), doc.get(pointer)
    cur: Any = doc
    for raw_seg in pointer[1:].split("/"):
        seg = raw_seg.replace("~1", "/").replace("~0", "~")
        if not isinstance(cur, dict) or seg not in cur: return False, None
        cur = cur[seg]
    return True, cur


def resolve_observed_field(obs: dict[str, Any], key: str, ptr: str, exp: Any) -> tuple[bool, Any]:
    ok_p, act = _resolve_pointer(obs, ptr or f"/{key}")
    if not ok_p and key in obs: ok_p, act = True, obs[key]
    if not ok_p and isinstance(exp, dict) and ("forbid_keys" in exp or "allowed_keys" in exp): ok_p, act = True, obs
    return ok_p, act


def _values_equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool): return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_num(a) or _is_num(b): return _is_num(a) and _is_num(b) and abs(float(a) - float(b)) <= 1e-9
    if a is None or b is None: return a is None and b is None
    if _is_seq(a) and _is_seq(b): return len(a) == len(b) and all(_values_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict): return set(a) == set(b) and all(_values_equal(a[k], b[k]) for k in a)
    return a == b


def _resolve_peer(
    obs: dict[str, Any], proj_then: dict[str, str], ref: Any, when_env: dict[str, Any] | None = None,
) -> tuple[bool, Any]:
    if not isinstance(ref, str) or not ref.strip(): return False, None
    if ref.startswith("when."):
        key = ref[5:]
        if ref in obs: return True, obs[ref]
        inp = dict(when_env or {})
        for side in ("_when_env", "before", "when"):
            if isinstance(obs.get(side), dict): inp.update(obs[side])
        return (key in inp, inp.get(key))
    if ref.startswith("then."): ref = ref[5:]
    if ref.startswith("/") or ref in proj_then:
        return _resolve_pointer(obs, ref if ref.startswith("/") else proj_then[ref])
    return (ref in obs, obs.get(ref)) if isinstance(obs, dict) else (False, None)


def _has_key_recursive(val: Any, fk: str, is_root: bool = True) -> bool:
    if _is_seq(val): return any(_has_key_recursive(x, fk, False) for x in val)
    if not isinstance(val, dict): return False
    return fk in val or any(
        not (is_root and k == "_frame" and fk != "_frame" and isinstance(v, dict)) and _has_key_recursive(v, fk, False)
        for k, v in val.items()
    )


def _req(ok: bool, key: str, msg: str) -> None:
    if not ok: raise RuntimeError(f"then.{key}: {msg}")


def _has_eq(items: Any, target: Any) -> bool:
    return _is_seq(items) and any(_values_equal(x, target) for x in items)


def _check_bounds(key: str, val: Any, spec: dict[str, Any], label: str = "") -> None:
    if "min" in spec:
        _req(_is_num(val) and _is_num(spec["min"]) and float(val) + 1e-9 >= float(spec["min"]), key, label or "< min")
    if "max" in spec:
        _req(_is_num(val) and _is_num(spec["max"]) and float(val) - 1e-9 <= float(spec["max"]), key, label or "> max")


def check_value(
    key: str, act: Any, exp: Any, actual_present: bool = True,
    observed: dict[str, Any] | None = None, proj_then: dict[str, str] | None = None,
    when_env: dict[str, Any] | None = None,
) -> None:
    _req(not (isinstance(act, float) and not math.isfinite(act)), key, "non-finite float")
    if not isinstance(exp, dict):
        _req(actual_present and _values_equal(act, exp), key, f"expected {exp!r}, got {act!r}")
        return
    _req(bool(exp), key, "empty predicate")
    for op in exp: _req(op in SUPPORTED_REL_KEYS, key, f"unsupported predicate operator {op!r}")
    obs_doc = observed if isinstance(observed, dict) else {}
    proj_map = proj_then if isinstance(proj_then, dict) else {}
    act_len = len(act) if isinstance(act, (str, list, tuple, dict)) else -1
    if "eq" in exp: _req(actual_present and _values_equal(act, exp["eq"]), key, "eq mismatch")
    if "in" in exp: _req(actual_present and _has_eq(exp["in"], act), key, "not in set")
    if "not_in" in exp:
        fi = exp["not_in"]
        _req(actual_present and act is not None, key, "null in not_in")
        _req(not _has_eq(fi, act), key, "forbidden by not_in") if _is_seq(fi) else _req(_values_equal(act, fi), key, "mutant killed")
    if "approx" in exp:
        at = float(exp["abs_tol"]) if _is_num(exp.get("abs_tol")) else 0.0
        rt = float(exp["rel_tol"]) if _is_num(exp.get("rel_tol")) else 0.0
        _req(_is_num(act) and _is_num(exp["approx"]) and ("abs_tol" in exp or "rel_tol" in exp) and at >= 0.0 and rt >= 0.0, key, "bad approx")
        ap = float(exp["approx"])
        _req(abs(float(act) - ap) <= at + rt * abs(ap), key, "outside approx")
    for v in (act if _is_seq(act) and any(k in exp for k in ("monotonic", "sum_total", "step_max_delta")) else [act]):
        _check_bounds(key, v, exp)
    if "len" in exp: _req(_is_u64(exp["len"]) and act_len == int(exp["len"]), key, "len mismatch")
    if "min_len" in exp: _req(_is_u64(exp["min_len"]) and act_len >= int(exp["min_len"]), key, "< min_len")
    if "max_len" in exp: _req(_is_u64(exp["max_len"]) and 0 <= act_len <= int(exp["max_len"]), key, "> max_len")
    if "non_empty" in exp:
        ne = exp["non_empty"]
        _req(isinstance(ne, bool) and act_len >= 0 and (act_len > 0 if ne else act_len == 0), key, "non_empty")
    for op, fn in (("prefix", str.startswith), ("suffix", str.endswith)):
        if op in exp: _req(isinstance(exp[op], str) and isinstance(act, str) and fn(act, exp[op]), key, op)
    if "contains" in exp:
        ce = exp["contains"]
        rl = ce if _is_seq(ce) else (ce,)
        ok_c = all(isinstance(x, str) and x in act for x in rl) if isinstance(act, str) else (all(_has_eq(act, r) for r in rl) if _is_seq(act) else False)
        _req(ok_c, key, "contains")
    if "forbid_keys" in exp:
        _req(isinstance(act, dict), key, "expected dict")
        fk_l, ir = exp["forbid_keys"], act is obs_doc
        if _is_seq(fk_l):
            for fk in fk_l: _req(not _has_key_recursive(act, str(fk), ir), key, f"forbidden key {fk!r}")
        else:
            _req(isinstance(fk_l, str) and _has_key_recursive(act, fk_l, ir), key, "forbid_keys")
    if "allowed_keys" in exp:
        _req(isinstance(act, dict) and _is_seq(exp["allowed_keys"]), key, "allowed_keys")
        for ak, av in act.items():
            if not (ak == "_frame" and isinstance(av, dict)): _req(ak in exp["allowed_keys"], key, f"key {ak!r}")
    for fk, op_sym in (("le_field", "<="), ("ge_field", ">="), ("eq_field", "==")):
        if fk not in exp: continue
        fp, pv = _resolve_peer(obs_doc, proj_map, exp[fk], when_env)
        ok_p = fp and (_values_equal(act, pv) if op_sym == "==" else (
            _is_num(act) and _is_num(pv) and (float(act) - 1e-9 <= float(pv) if op_sym == "<=" else float(act) + 1e-9 >= float(pv))
        ))
        _req(ok_p, key, fk)
    for op, min_n in (("sum_fields", 2), ("balance_fields", 0)):
        if op not in exp: continue
        sub_e = exp[op]
        _req(_is_num(act) and ((_is_seq(sub_e) and len(sub_e) >= min_n) if op == "sum_fields" else isinstance(sub_e, dict)), key, op)
        sides, tot = ({"add": sub_e} if op == "sum_fields" else sub_e), 0.0
        for side, sgn in (("add", 1.0), ("sub", -1.0)):
            for ref in sides.get(side, []):
                fp, pv = _resolve_peer(obs_doc, proj_map, ref, when_env)
                _req(fp and _is_num(pv), key, f"missing peer {ref!r}")
                tot += sgn * float(pv)
        _req(abs(float(act) - tot) <= float(exp.get("abs_tol", 1e-9)), key, f"{op} mismatch")
    if "monotonic" in exp:
        mode = str(exp["monotonic"])
        _req(_is_seq(act) and bool(act) and all(_is_num(x) for x in act), key, "monotonic")
        for idx in range(1, len(act)):
            pv, cv = float(act[idx - 1]), float(act[idx])
            ok_m = (
                pv - 1e-9 <= cv if mode == "non_decreasing" else pv + 1e-9 < cv if mode == "strictly_increasing"
                else pv + 1e-9 >= cv if mode == "non_increasing" else pv - 1e-9 > cv if mode == "strictly_decreasing" else False
            )
            _req(ok_m, key, f"monotonic {idx}")
    if "step_max_delta" in exp:
        d = exp["step_max_delta"]
        ok_d = (
            _is_num(d) and float(d) > 0.0 and _is_seq(act) and bool(act) and all(_is_num(x) for x in act)
            and all(abs(float(act[i]) - float(act[i - 1])) <= float(d) + 1e-9 for i in range(1, len(act)))
        )
        _req(ok_d, key, "step_max_delta")
    if "sum_total" in exp:
        _req(not (isinstance(act, dict) and act and all(rk in SUPPORTED_REL_KEYS for rk in act)), key, "rel table")
        vals = list(act) if _is_seq(act) else (list(act.values()) if isinstance(act, dict) else [])
        _req(bool(vals) and all(_is_num(x) for x in vals), key, "sum_total")
        tot, ste = sum(float(x) for x in vals), exp["sum_total"]
        if _is_num(ste):
            _req(abs(tot - float(ste)) <= 1e-9, key, "sum_total")
        else:
            _req(isinstance(ste, dict), key, "sum_total")
            if "eq" in ste: _req(_is_num(ste["eq"]) and abs(tot - float(ste["eq"])) <= 1e-9, key, "sum_total")
            _check_bounds(key, tot, ste, "sum_total")


_NESTED_03 = {
    "len": (("min", "min_len"), ("max", "max_len")),
    "keys": (("allow", "allowed_keys"), ("forbid", "forbid_keys")),
    "tol": (("abs", "abs_tol"), ("rel", "rel_tol")),
}


def _unwrap_or_desugar_03(raw: Any) -> Any:
    if not isinstance(raw, dict): return raw
    if len(raw) == 1 and "eq" in raw and not isinstance(raw["eq"], dict): return raw["eq"]
    out: dict[str, Any] = {}
    sp = lambda s: str(s) if str(s).startswith(("when.", "then.", "/")) else f"then.{s}"
    for k, v in raw.items():
        if k == "convert_from": continue
        if k == "eq": out["approx" if "tol" in raw else "eq"] = v
        elif k in _NESTED_03 and isinstance(v, dict):
            for sk, dk in _NESTED_03[k]:
                if sk in v: out[dk] = v[sk]
        elif k == "series" and isinstance(v, dict):
            out.update(v)
            if out.get("monotonic") in ("increasing", "decreasing"): out["monotonic"] = f"strictly_{out['monotonic']}"
        elif k == "peer" and isinstance(v, dict):
            for pk, rk in (("eq", "eq_field"), ("le", "le_field"), ("ge", "ge_field")):
                if pk in v: out[rk] = sp(v[pk]) if isinstance(v[pk], str) else v[pk]
            if isinstance(v.get("sum"), list): out["sum_fields"] = [sp(x) for x in v["sum"]]
            if isinstance(v.get("balance"), dict):
                out["balance_fields"] = {bs: [sp(x) for x in bv] for bs, bv in v["balance"].items() if isinstance(bv, list)}
        else: out[k] = v
    return out


def _scale_03_exp(exp: Any, conv: float) -> Any:
    if conv == 1.0: return exp
    if _is_num(exp): return float(exp) * conv
    if isinstance(exp, list): return [_scale_03_exp(x, conv) for x in exp]
    if not isinstance(exp, dict): return exp
    out = dict(exp)
    for k in ("eq", "approx", "min", "max", "abs_tol", "step_max_delta", "in", "not_in"):
        if k in out: out[k] = _scale_03_exp(out[k], conv)
    if "sum_total" in out:
        st = out["sum_total"]
        out["sum_total"] = {sk: _scale_03_exp(sv, conv) for sk, sv in st.items()} if isinstance(st, dict) else _scale_03_exp(st, conv)
    return out


def _write_permitted(res: str, allowed: set[str], allowed_bases: set[str]) -> bool:
    return res in allowed or res.partition("#")[0] in allowed or ("#" not in res and res in allowed_bases)


def _verify_cobol_single_frame(res: str, obs: Any, is_ambient: bool) -> bool:
    checked, label = False, f"undeclared write on perimeter resource {res!r}" if is_ambient else f"frame.violation:{res}"
    if _is_u64(obs):
        if obs > 0: raise RuntimeError(f"{label}: expected 0 writes, got {obs}")
        return True
    if isinstance(obs, dict):
        for wk in ("writes", "operations", "events"):
            if wk in obs:
                wv = obs[wk]
                if not (_is_u64(wv) or _is_seq(wv)):
                    raise RuntimeError(f"frame.invalid:{res}: {wk} must be a non-negative integer, got {wv!r}")
                checked = True
                if (wv if _is_u64(wv) else len(wv)) > 0: raise RuntimeError(f"{label}: expected 0 writes")
        if "before" in obs and "after" in obs:
            checked = True
            if not _values_equal(obs["before"], obs["after"]): raise RuntimeError(f"{label}: before and after snapshots differ")
        if not is_ambient and obs.get("observed") is False: return False
        if checked: return True
    raise RuntimeError(f"frame.invalid:{res}: must supply non-negative integer writes or before/after snapshots")


def verify_case_write_frames(
    scope_writes: list[str], case_writes: list[Any] | None,
    frames: dict[str, dict[str, Any]] | None, read_keys: list[str],
) -> None:
    eff_f = frames if isinstance(frames, dict) else {}
    has_cw = isinstance(case_writes, list)
    al = {str(x) for x in case_writes} if has_cw and case_writes is not None else set(scope_writes)
    ab, checked_f = {w.partition("#")[0] for w in al}, set()
    if has_cw:
        for r in scope_writes:
            br = r.partition("#")[0]
            if not _write_permitted(r, al, ab):
                checked_f.update((r, br))
                if (r in eff_f or br in eff_f) and _verify_cobol_single_frame(r, eff_f[r] if r in eff_f else eff_f[br], False):
                    read_keys.append(f"@frame:{r}")
            else:
                read_keys.append(f"@frame:{r}")
    for fk in sorted(eff_f):
        if fk not in checked_f and not _write_permitted(fk, al, ab): _verify_cobol_single_frame(fk, eff_f[fk], True)
