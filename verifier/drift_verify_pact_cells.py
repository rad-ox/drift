#!/usr/bin/env python3
"""Clause IR atom algebra and cut-point cell decomposition for drift_verify_pact.py (MIT License)."""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any, Callable

UNIT_BASE = {
    "ns": ("time", 1),
    "us": ("time", 1000),
    "ms": ("time", 1000000),
    "s": ("time", 1000000000),
    "b": ("bytes", 1),
    "bytes": ("bytes", 1),
    "kib": ("bytes", 1024),
    "mib": ("bytes", 1048576),
    "kb": ("bytes", 1000),
    "mb": ("bytes", 1000000),
}


def _canon_pretty_py(v: Any, jcs_str_fn: Callable[[str], str], jcs_num_fn: Callable[[Any], str], depth: int = 0) -> str:
    if v is None or isinstance(v, bool):
        return "null" if v is None else ("true" if v else "false")
    if isinstance(v, (int, float)):
        return jcs_num_fn(v)
    if isinstance(v, str):
        return jcs_str_fn(v)
    pad, inner = "  " * depth, "  " * (depth + 1)
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[\n" + ",\n".join(f"{inner}{_canon_pretty_py(x, jcs_str_fn, jcs_num_fn, depth + 1)}" for x in v) + f"\n{pad}]"
    if isinstance(v, dict):
        if not v:
            return "{}"
        items = sorted(v.items(), key=lambda kv: str(kv[0]).encode("utf-16-be"))
        return "{\n" + ",\n".join(f"{inner}{jcs_str_fn(str(k))}: {_canon_pretty_py(val, jcs_str_fn, jcs_num_fn, depth + 1)}" for k, val in items) + f"\n{pad}}}"
    raise ValueError("type")


def _has_peers(b: dict[str, Any]) -> bool:
    return bool(b.get("peer_le") or b.get("peer_ge") or b.get("peer_eq"))


def _merge_peers(a: dict[str, Any], b: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for pk in ("peer_le", "peer_ge", "peer_eq"):
        m = sorted(set(a.get(pk, ())) | set(b.get(pk, ())))
        if m:
            out[pk] = m
    return out


def _unify_units_py(a: dict[str, Any], b: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    ua, ub = a.get("unit", ""), b.get("unit", "")
    if ua == ub:
        return dict(a), dict(b), ua
    if not ua or not ub or ua not in UNIT_BASE or ub not in UNIT_BASE or UNIT_BASE[ua][0] != UNIT_BASE[ub][0]:
        return None
    fa, fb = UNIT_BASE[ua][1], UNIT_BASE[ub][1]
    fm, u_out = (fa, ua) if fa <= fb else (fb, ub)
    if fa % fm != 0 or fb % fm != 0:
        return None
    ca, cb = dict(a), dict(b)
    for d, f in ((ca, fa // fm), (cb, fb // fm)):
        if "min" in d:
            d["min"] *= f
        if "max" in d:
            d["max"] *= f
        d["unit"] = u_out
    return ca, cb, u_out


def _meet_int_enum_py(rng: dict[str, Any], en: dict[str, Any]) -> dict[str, Any] | None:
    kept = []
    for s in en.get("in", ()):
        try:
            iv = int(s)
        except Exception:
            continue
        if ("min" not in rng or iv >= rng["min"]) and ("max" not in rng or iv <= rng["max"]):
            kept.append(str(iv))
    return {"kind": "enum_set", "in": sorted(set(kept)), **_merge_peers(rng, en)} if kept else None


def _atom_meet_py(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    ka, kb = a.get("kind", "any"), b.get("kind", "any")
    if ka == "any":
        return {**b, **_merge_peers(a, b)}
    if kb == "any":
        return {**a, **_merge_peers(a, b)}
    if ka == "bool_val" or kb == "bool_val":
        sa = {"true" if a.get("eq") else "false"} if ka == "bool_val" else (set(a.get("in", ())) if ka == "enum_set" else None)
        sb = {"true" if b.get("eq") else "false"} if kb == "bool_val" else (set(b.get("in", ())) if kb == "enum_set" else None)
        if sa is None or sb is None:
            return None
        inter = sorted(sa & sb)
        return {"kind": "enum_set", "in": inter, **_merge_peers(a, b)} if inter else None
    if ka in ("int_range", "len_range") and kb == ka:
        if a.get("unit", "") or b.get("unit", ""):
            un = _unify_units_py(a, b)
            if un is None:
                return None
            ca, cb, u_out = un
        else:
            ca, cb, u_out = dict(a), dict(b), ""
        has_lo = ("min" in ca) or ("min" in cb)
        lo = max(ca["min"], cb["min"]) if ("min" in ca and "min" in cb) else ca.get("min", cb.get("min", 0))
        has_hi = ("max" in ca) or ("max" in cb)
        hi = min(ca["max"], cb["max"]) if ("max" in ca and "max" in cb) else ca.get("max", cb.get("max", 0))
        if has_lo and has_hi and lo > hi:
            return None
        res: dict[str, Any] = {"kind": ka, **_merge_peers(ca, cb)}
        if has_lo:
            res["min"] = lo
        if has_hi:
            res["max"] = hi
        if u_out:
            res["unit"] = u_out
        return res
    if ka == "int_range" and kb == "enum_set":
        return _meet_int_enum_py(a, b)
    if ka == "enum_set" and kb == "int_range":
        return _meet_int_enum_py(b, a)
    if ka == "enum_set" and kb == "enum_set":
        inter = sorted(set(a.get("in", ())) & set(b.get("in", ())))
        return {"kind": "enum_set", "in": inter, **_merge_peers(a, b)} if inter else None
    if ka == "enum_set" and kb == "not_in":
        rem = sorted(set(a.get("in", ())) - set(b.get("not_in", ())))
        return {"kind": "enum_set", "in": rem, **_merge_peers(a, b)} if rem else None
    if ka == "not_in" and kb == "enum_set":
        rem = sorted(set(b.get("in", ())) - set(a.get("not_in", ())))
        return {"kind": "enum_set", "in": rem, **_merge_peers(a, b)} if rem else None
    if ka == "not_in" and kb == "not_in":
        return {"kind": "not_in", "not_in": sorted(set(a.get("not_in", ())) | set(b.get("not_in", ()))), **_merge_peers(a, b)}
    if ka == "keys_guard" and kb == "keys_guard":
        forb = set(a.get("keys_forbid", ())) | set(b.get("keys_forbid", ()))
        al_a, al_b = a.get("keys_allow", []), b.get("keys_allow", [])
        if al_a or al_b:
            allow = (set(al_a) & set(al_b)) if (al_a and al_b) else set(al_a or al_b)
            allow -= forb
            return {"kind": "keys_guard", "keys_allow": sorted(allow), "keys_forbid": sorted(forb)} if allow else None
        return {"kind": "keys_guard", "keys_forbid": sorted(forb)}
    return None


def _peers_subsume_py(sub: dict[str, Any], sup: dict[str, Any]) -> bool:
    for pk in ("peer_le", "peer_ge", "peer_eq"):
        req_p = set(sup.get(pk, ()))
        if req_p and not req_p.issubset(set(sub.get(pk, ())) | set(sub.get("peer_eq", ())) ):
            return False
    return True


def _atom_subsumes_py(sub: dict[str, Any], sup: dict[str, Any]) -> bool:
    ks, kp = sub.get("kind", "any"), sup.get("kind", "any")
    if not _peers_subsume_py(sub, sup):
        return False
    if kp == "any":
        return True
    if ks == "any":
        return False
    if ks == "bool_val" or kp == "bool_val":
        ss = {"true" if sub.get("eq") else "false"} if ks == "bool_val" else (set(sub.get("in", ())) if ks == "enum_set" else None)
        sp = {"true" if sup.get("eq") else "false"} if kp == "bool_val" else (set(sup.get("in", ())) if kp == "enum_set" else None)
        return bool(ss is not None and sp is not None and ss.issubset(sp))
    if ks in ("int_range", "len_range") and kp == ks:
        if sub.get("unit", "") or sup.get("unit", ""):
            un = _unify_units_py(sub, sup)
            if un is None:
                return False
            cs, cp, _ = un
        else:
            cs, cp = dict(sub), dict(sup)
        if "min" in cp and ("min" not in cs or cs["min"] < cp["min"]):
            return False
        if "max" in cp and ("max" not in cs or cs["max"] > cp["max"]):
            return False
        return True
    if ks == "int_range" and kp == "enum_set":
        if "min" not in sub or "max" not in sub or sub["max"] - sub["min"] > 256:
            return False
        sup_s = set(sup.get("in", ()))
        return all(str(v) in sup_s for v in range(sub["min"], sub["max"] + 1))
    if ks == "enum_set" and kp == "int_range":
        for v in sub.get("in", ()):
            try:
                iv = int(v)
            except Exception:
                return False
            if ("min" in kp and "min" in sup and iv < sup["min"]) or ("max" in sup and iv > sup["max"]):
                return False
            if ("min" in sup and iv < sup["min"]) or ("max" in sup and iv > sup["max"]):
                return False
        return True
    if ks == "int_range" and kp == "not_in":
        for v in sup.get("not_in", ()):
            try:
                iv = int(v)
            except Exception:
                continue
            if ("min" not in sub or iv >= sub["min"]) and ("max" not in sub or iv <= sub["max"]):
                return False
        return True
    if ks == "enum_set" and kp == "enum_set":
        return set(sub.get("in", ())).issubset(set(sup.get("in", ())))
    if ks == "enum_set" and kp == "not_in":
        return not (set(sub.get("in", ())) & set(sup.get("not_in", ())))
    if ks == "not_in" and kp == "not_in":
        return set(sup.get("not_in", ())).issubset(set(sub.get("not_in", ())))
    if ks == "keys_guard" and kp == "keys_guard":
        sf, pf = set(sub.get("keys_forbid", ())), set(sup.get("keys_forbid", ()))
        sa, pa = sub.get("keys_allow", []), sup.get("keys_allow", [])
        if pa:
            return bool(sa) and (set(sa) - sf).issubset(set(pa) - pf)
        return pf.issubset(sf) or (bool(sa) and not (set(sa) & pf))
    return False


def _when_meet_py(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    out = dict(a)
    for k, vb in b.items():
        if k in out:
            m = _atom_meet_py(out[k], vb)
            if m is None:
                return None
            out[k] = m
        else:
            out[k] = dict(vb)
    return out


def _when_box_subsumes_py(cell: dict[str, Any], cover: dict[str, Any]) -> bool:
    for k, cb in cover.items():
        if cb.get("kind", "any") == "any" and not _has_peers(cb):
            continue
        if k not in cell or not _atom_subsumes_py(cell[k], cb):
            return False
    return True


def _clause_then_subsumes_py(sub: dict[str, Any], sup: dict[str, Any]) -> bool:
    if sub.get("outcome_class", "ok") != sup.get("outcome_class", "ok"):
        return False
    if not set(sup.get("presence", ())).issubset(set(sub.get("presence", ()))):
        return False
    st, pt = sub.get("then", {}), sup.get("then", {})
    for pk, pb in pt.items():
        if pb.get("kind", "any") == "any" and not _has_peers(pb):
            continue
        if pk not in st or not _atom_subsumes_py(st[pk], pb):
            return False
    return True


def _norm_bool_atom(b: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "enum_set", "in": ["true" if b.get("eq") else "false"], **{k: b[k] for k in ("peer_le", "peer_ge", "peer_eq") if k in b}} if b.get("kind") == "bool_val" else dict(b)


def _universe_atom_py(key: str, cell: dict[str, Any], schema: dict[str, Any], raw_covers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if key in cell and cell[key].get("kind", "any") != "any":
        return dict(cell[key])
    sc = schema.get(key)
    if isinstance(sc, dict):
        if sc.get("type") == "bool":
            return {"kind": "enum_set", "in": ["false", "true"]}
        if sc.get("enum"):
            return {"kind": "enum_set", "in": sorted(set(sc["enum"]))}
        if sc.get("type") == "int" and "min" in sc and "max" in sc:
            return {"kind": "int_range", "min": sc["min"], "max": sc["max"], **({"unit": sc["unit"]} if sc.get("unit") else {})}
    if any(cw.get(key, {}).get("kind") == "bool_val" for cw in raw_covers):
        return {"kind": "enum_set", "in": ["false", "true"]}
    return None


def _check_when_cell_coverage_py(target: dict[str, Any], covers: list[dict[str, Any]], schema: dict[str, Any], max_cells: int = 4096) -> str:
    nt = {k: _norm_bool_atom(v) for k, v in target.items()}
    ncs = [{k: _norm_bool_atom(v) for k, v in cw.items()} for cw in covers]
    stack: list[tuple[dict[str, Any], list[dict[str, Any]]]] = [(nt, ncs)]
    visited = 0
    while stack:
        visited += 1
        if visited > max_cells:
            return "undecided"
        cell, cur_covs = stack.pop()
        if any(_when_box_subsumes_py(cell, cw) for cw in cur_covs):
            continue
        active = [cw for cw in cur_covs if _when_meet_py(cell, cw) is not None]
        if not active:
            return "uncovered"
        cand_keys = sorted({k for cw in active for k, cb in cw.items() if not (cb.get("kind", "any") == "any" and not _has_peers(cb)) and (k not in cell or not _atom_subsumes_py(cell[k], cb))})
        if not cand_keys:
            return "uncovered"
        sk = cand_keys[0]
        base = _universe_atom_py(sk, cell, schema, covers)
        if base is None:
            return "uncovered"
        bk = base.get("kind")
        children: list[dict[str, Any]] = []
        if bk in ("int_range", "len_range") and "min" in base and "max" in base:
            if base["min"] >= base["max"]:
                return "uncovered"
            cut_atom = dict(base)
            cut = base["min"] + (base["max"] - base["min"]) // 2
            for cw in active:
                cb = cw.get(sk)
                if cb and cb.get("kind") == bk:
                    un = _unify_units_py(base, cb) if (base.get("unit") or cb.get("unit")) else (dict(base), dict(cb), "")
                    if un is None:
                        continue
                    ua, ub, _ = un
                    if "min" in ub and ua["min"] < ub["min"] <= ua["max"]:
                        cut_atom, cut = ua, ub["min"] - 1
                        break
                    if "max" in ub and ua["min"] <= ub["max"] < ua["max"]:
                        cut_atom, cut = ua, ub["max"]
                        break
            c_left, c_right = dict(cell), dict(cell)
            c_left[sk] = {**cut_atom, "max": cut}
            c_right[sk] = {**cut_atom, "min": cut + 1}
            children = [c_left, c_right]
        elif bk == "enum_set":
            vals = list(base.get("in", ()))
            sigs: dict[tuple[bool, ...], list[str]] = {}
            for v in vals:
                sig = tuple(_atom_meet_py({"kind": "enum_set", "in": [v]}, cw[sk]) is not None if sk in cw else True for cw in active)
                sigs.setdefault(sig, []).append(v)
            if len(sigs) <= 1:
                return "uncovered"
            for grp in sigs.values():
                c2 = dict(cell)
                c2[sk] = {"kind": "enum_set", "in": sorted(grp)}
                children.append(c2)
        else:
            return "uncovered"
        if len(children) <= 1:
            return "uncovered"
        for ch in reversed(children):
            stack.append((ch, active))
    return "covered"


OUTCOME_CLASSES = {"ok", "validation_fatal", "conflict_state", "rate_limited", "transient_retryable", "unknown_outcome"}


def _is_int_c(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _expr_03_to_atom_py(raw: Any, ptr_map: dict[str, str], unit: str, canon_fn: Callable[[Any], str]) -> dict[str, Any]:
    if isinstance(raw, bool):
        return {"kind": "bool_val", "eq": raw}
    if _is_int_c(raw):
        return {"kind": "int_range", "min": raw, "max": raw, **({"unit": unit} if unit else {})}
    if isinstance(raw, str):
        return {"kind": "enum_set", "in": [raw]}
    if not isinstance(raw, dict):
        return {"kind": "any"}
    peers: dict[str, list[str]] = {}
    if isinstance(pm := raw.get("peer"), dict):
        for pk, out_k in (("le", "peer_le"), ("ge", "peer_ge"), ("eq", "peer_eq")):
            if isinstance(pm.get(pk), str) and pm[pk]:
                cl = pm[pk][5:] if pm[pk].startswith(("when.", "then.")) else pm[pk]
                peers[out_k] = [ptr_map.get(cl, f"/{cl}")]
    if "keys" in raw and isinstance(km := raw["keys"], dict):
        return {"kind": "keys_guard", **({"keys_allow": sorted(set(km["allow"]))} if km.get("keys_allow") or km.get("allow") else {}), **({"keys_forbid": sorted(set(km["forbid"]))} if km.get("forbid") else {})}
    if "len" in raw and isinstance(lm := raw["len"], dict):
        return {"kind": "len_range", **({"min": int(lm["min"])} if "min" in lm else {}), **({"max": int(lm["max"])} if "max" in lm else {}), **peers}
    if "eq" in raw:
        ev = raw["eq"]
        if isinstance(ev, bool):
            return {"kind": "bool_val", "eq": ev}
        if _is_int_c(ev):
            return {"kind": "int_range", "min": ev, "max": ev, **({"unit": unit} if unit else {}), **peers}
        if isinstance(ev, str):
            return {"kind": "enum_set", "in": [ev], **peers}
    for sk, kind in (("in", "enum_set"), ("not_in", "not_in")):
        if sk in raw and isinstance(raw[sk], list):
            vals = sorted({x if isinstance(x, str) else (("true" if x else "false") if isinstance(x, bool) else (str(x) if _is_int_c(x) else canon_fn(x))) for x in raw[sk]})
            return {"kind": kind, sk: vals, **peers}
    if "min" in raw or "max" in raw:
        return {"kind": "int_range", **({"min": int(raw["min"])} if "min" in raw and _is_int_c(raw["min"]) else {}), **({"max": int(raw["max"])} if "max" in raw and _is_int_c(raw["max"]) else {}), **({"unit": unit} if unit else {}), **peers}
    return {"kind": "any", **peers}


def _infer_outcome_py(tm: dict[str, Any], roles: dict[str, str]) -> str:
    for ptr, role in roles.items():
        if role == "classification" and (b := tm.get(ptr)) and b.get("kind") == "enum_set" and len(b.get("in", ())) == 1 and b["in"][0] in OUTCOME_CLASSES:
            return b["in"][0]
    st = tm.get("/status")
    if st and st.get("kind") == "int_range" and "min" in st and "max" in st:
        lo, hi = st["min"], st["max"]
        if hi < 400:
            return "ok"
        if lo == 429 and hi == 429:
            return "rate_limited"
        if lo == 409 and hi == 409:
            return "conflict_state"
        if lo == 504 and hi == 504:
            return "unknown_outcome"
        if 400 <= lo and hi < 500:
            return "validation_fatal"
        if lo >= 500:
            return "transient_retryable"
    return "ok"


def _norm_ptr_py(raw_p: str, fb: str) -> str:
    if not raw_p:
        return f"/{fb}"
    if ":" in raw_p and (af := raw_p.split(":", 1)[1]).startswith("/"):
        return af
    return raw_p if raw_p.startswith("/") else f"/{raw_p}"


_ACK_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ACK_DR2P_RE = re.compile(r"^dr2p:(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})$")
_ACK_SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _parse_pact_ack_py(text: str, decode_fn: Callable[[str], Any], canon_fn: Callable[[Any], str], jcs_str_fn: Callable[[str], str], jcs_num_fn: Callable[[Any], str]) -> dict[str, Any]:
    doc = decode_fn(text)
    req = {"schema", "pact_id", "retired_revision", "active_lock_ref", "area_id", "subject_ref", "digest"}
    if not isinstance(doc, dict) or set(doc) != req or doc["schema"] != "drift.pact-ack/1":
        raise ValueError("ack_keys")
    if not isinstance(doc["pact_id"], str) or not _ACK_ID_RE.match(doc["pact_id"]) or not _is_int_c(doc["retired_revision"]) or doc["retired_revision"] < 1 or not isinstance(doc["active_lock_ref"], str) or not _ACK_DR2P_RE.match(doc["active_lock_ref"]) or not isinstance(doc["digest"], str) or not _ACK_SHA_RE.match(doc["digest"]):
        raise ValueError("ack_fields")
    if _canon_pretty_py(doc, jcs_str_fn, jcs_num_fn) != text.replace("\r\n", "\n").rstrip("\n"):
        raise ValueError("ack_canon")
    unsigned = {k: v for k, v in doc.items() if k != "digest"}
    exp_dg = "sha256:" + hashlib.sha256(b"drift.pact-ack/2\x00" + canon_fn(unsigned).encode("utf-8")).hexdigest()
    if exp_dg != doc["digest"]:
        raise ValueError("ack_digest")
    return doc


def _extract_sshsig_fp_py(armored: str) -> str | None:
    b64 = "".join(ln.strip() for ln in armored.splitlines() if ln.strip() and not ln.strip().startswith("-----"))
    if not b64:
        return None
    try:
        blob = base64.b64decode(b64, validate=True)
    except Exception:
        return None
    if len(blob) < 14 or blob[:6] != b"SSHSIG":
        return None
    ver = int.from_bytes(blob[6:10], "big")
    pk_len = int.from_bytes(blob[10:14], "big")
    if ver != 1 or pk_len <= 0 or 14 + pk_len > len(blob):
        return None
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob[14 : 14 + pk_len]).digest()).decode("ascii").rstrip("=")
