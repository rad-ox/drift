#!/usr/bin/env python3
"""Schema 0.3 lossless observation decoder and relational re-judge (drift.observation/1)."""

from __future__ import annotations

import math
import re
import struct
from decimal import Decimal as D
from typing import Any

_OPS = {"eq", "min", "max", "in", "not_in", "contains", "len", "prefix", "suffix", "keys", "peer", "series", "tol", "convert_from", "exact_scale"}
_ABS = object()
_d = lambda x: D(repr(x)) if isinstance(x, float) else D(x)
_nm = lambda x: isinstance(x, (int, float, D)) and not isinstance(x, bool)
_dec_scale = lambda d: (-d.as_tuple().exponent if isinstance(d.as_tuple().exponent, int) and d.as_tuple().exponent < 0 else 0)


def _ob(v: Any) -> Any:
    if isinstance(v, list):
        return [_ob(x) for x in v]
    if not isinstance(v, dict):
        return v
    if "$t" in v:
        t, x = v["$t"], v.get("v")
        if t in ("absent", "null"):
            return _ABS if t == "absent" else None
        if t in ("i64", "u64"):
            n = int(x) if isinstance(x, (int, str)) and not isinstance(x, bool) else int("x")
            if not (-2**63 if t == "i64" else 0) <= n < (2**63 if t == "i64" else 2**64):
                raise ValueError(t)
            return n
        if t == "dec" and isinstance(x, str) and re.fullmatch(r"[+-]?(?=\.?\d)\d*\.?\d*", x.strip()):
            return D(x.strip())
        if t in ("f32", "f64"):
            if "bits" in v:
                bs = v["bits"]
                if not isinstance(bs, str):
                    raise ValueError(t)
                hs = bs[2:] if bs.startswith("0x") else bs
                if not re.fullmatch(r"[0-9a-fA-F]{1," + ("8" if t == "f32" else "16") + r"}", hs):
                    raise ValueError(t)
                nbytes = 4 if t == "f32" else 8
                return struct.unpack(">f" if t == "f32" else ">d", int(hs, 16).to_bytes(nbytes, "big"))[0]
            if "v" not in v or isinstance(x, bool):
                raise ValueError(t)
            if isinstance(x, str):
                if "_" in x:
                    raise ValueError(t)
                if x in ("-0.0", "-0"):
                    f = -0.0
                elif x in ("NaN", "nan"):
                    f = math.nan
                elif x in ("+Inf", "Inf", "+Infinity", "Infinity"):
                    f = math.inf
                elif x in ("-Inf", "-Infinity"):
                    f = -math.inf
                else:
                    f = float(x)
            elif isinstance(x, (int, float)):
                f = float(x)
            else:
                raise ValueError(t)
            if t == "f32":
                try:
                    return struct.unpack(">f", struct.pack(">f", f))[0]
                except OverflowError:
                    return math.copysign(math.inf, f)
            return f
        if t == "bytes":
            return bytes.fromhex(x)
        raise ValueError(t)
    o: dict[str, Any] = {}
    for k, x in v.items():
        if k.startswith("$") and not k.startswith("$$"):
            raise ValueError(k)
        dk = k[1:] if k.startswith("$$") else k
        if dk in o:
            raise ValueError(k)
        o[dk] = _ob(x)
    return o


def _env(e: Any) -> tuple[Any, ...]:
    if not isinstance(e, dict) or e.get("schema") != "drift.observation/1" or e.get("outcome", "returned") not in ("returned", "thrown", "timeout", "interrupted"):
        raise ValueError("observation")
    ts = e["touched_symbols"] if "touched_symbols" in e else []
    io = e["init_only_symbols"] if "init_only_symbols" in e else []
    if not isinstance(ts, list) or not all(isinstance(x, str) for x in ts) or not isinstance(io, list) or not all(isinstance(x, str) for x in io):
        raise ValueError("touched_symbols")
    pr = e["presence"] if "presence" in e else {}
    if not isinstance(pr, dict) or not all(isinstance(k, str) and v in ("exact", "null_collapsed", "absent_collapsed", "unobservable") for k, v in pr.items()):
        raise ValueError("presence")
    fr = e["frame"] if "frame" in e else {}
    if not isinstance(fr, dict):
        raise ValueError("frame")
    return e.get("outcome", "returned"), _ob(e["payload"]) if "payload" in e else _ABS, pr, fr, ts, io


def obs03(d: dict[str, Any], cs: list[str], sch: str) -> dict[str, Any]:
    if "observations" not in d:
        return {}
    if sch != "0.3" or not isinstance(d["observations"], dict) or any(k not in cs for k in d["observations"]):
        raise ValueError("observations")
    return {"observations": d["observations"], "_obs_dec": {k: _env(e) for k, e in d["observations"].items()}}


def _cmp(a: Any, b: Any, cv: D = D(1)) -> int | None:
    a, b = _d(a), _d(b) * cv
    return None if a.is_nan() or b.is_nan() or not (_nm(a) and _nm(b)) else (a > b) - (a < b)


def _eq(o: Any, l: Any, cv: D = D(1), tol: tuple[Any, Any] = (0, 0), exact_scale: bool = False) -> bool:
    if l is None or isinstance(l, bool):
        return o is l
    if isinstance(l, str):
        if not isinstance(o, D):
            return o == l
        if re.fullmatch(r"[+-]?(?=\.?\d)\d*\.?\d*", l.strip()) is None:
            return False
        td = D(l.strip())
        if exact_scale and _dec_scale(o) != _dec_scale(td):
            return False
        return abs(o - td * cv) <= tol[0] + tol[1] * abs(td * cv)
    if _nm(l):
        if not _nm(o):
            return False
        do, dl = _d(o), _d(l)
        if do.is_nan() or dl.is_nan():
            return False
        if exact_scale and isinstance(o, D) and isinstance(l, int) and not isinstance(l, bool) and _dec_scale(o) != 0:
            return False
        return abs(do - dl * cv) <= tol[0] + tol[1] * abs(dl * cv)
    if isinstance(l, list):
        return isinstance(o, list) and len(o) == len(l) and all(_eq(a, b, exact_scale=exact_scale) for a, b in zip(o, l))
    return isinstance(l, dict) and isinstance(o, dict) and o.keys() == l.keys() and all(_eq(o[k], x, exact_scale=exact_scale) for k, x in l.items())


def _fk(o: Any, fs: Any) -> bool:
    return (isinstance(o, dict) and any((k in fs and v is not _ABS) or _fk(v, fs) for k, v in o.items())) or (isinstance(o, list) and any(_fk(x, fs) for x in o))


def _contains(cont: Any, o: Any, exact_scale: bool) -> bool:
    if isinstance(o, str):
        if isinstance(cont, str):
            return cont in o
        return isinstance(cont, list) and all(isinstance(x, str) and x in o for x in cont)
    if isinstance(o, list):
        reqs = cont if isinstance(cont, list) else [cont]
        return all(any(_eq(elem, req, exact_scale=exact_scale) for elem in o) for req in reqs)
    return False


def _linear_peer(o: Any, add_refs: list[str], sub_refs: list[str], g: Any, has_tol: bool, tol: tuple[Any, Any]) -> bool:
    if not _nm(o) or _d(o).is_nan():
        return False
    adds, subs = [], []
    for refs, dst in ((add_refs, adds), (sub_refs, subs)):
        for r in refs:
            po = g(r)
            if po is _ABS or not _nm(po) or _d(po).is_nan():
                return False
            dst.append(po)
    if not has_tol and type(o) is int and all(type(x) is int for x in (*adds, *subs)):
        return o == sum(adds) - sum(subs)
    if not has_tol and isinstance(o, D) and all(isinstance(x, D) for x in (*adds, *subs)):
        return o == sum(adds, D(0)) - sum(subs, D(0))
    obs_n, s_tot, mag = float(o), 0.0, 0.0
    for x in adds:
        pv = float(x); s_tot += pv; mag += abs(pv)
    for x in subs:
        pv = float(x); s_tot -= pv; mag += abs(pv)
    return abs(obs_n - s_tot) <= float(tol[0]) + float(tol[1]) * mag


def _peer(pm: dict[str, Any], o: Any, g: Any, has_tol: bool = False, tol: tuple[Any, Any] = (0, 0), exact_scale: bool = False) -> bool:
    for k, s in (("le", 1), ("ge", -1)):
        if k in pm:
            po = g(pm[k])
            if po is _ABS or not (_nm(o) and _nm(po)) or (c := _cmp(o, po)) is None or c * s > 0:
                return False
    if "eq" in pm:
        po = g(pm["eq"])
        if po is _ABS:
            return False
        if has_tol:
            if not (_nm(o) and _nm(po)) or _d(o).is_nan() or _d(po).is_nan():
                return False
            if abs(_d(o) - _d(po)) > tol[0] + tol[1] * abs(_d(po)):
                return False
        elif _nm(o) and _nm(po):
            if _d(o) != _d(po) or (exact_scale and isinstance(o, D) and isinstance(po, D) and _dec_scale(o) != _dec_scale(po)):
                return False
        elif o != po:
            return False
    if "sum" in pm:
        if not isinstance(pm["sum"], list) or not _linear_peer(o, pm["sum"], [], g, has_tol, tol):
            return False
    if "balance" in pm:
        bm = pm["balance"]
        if not isinstance(bm, dict) or not _linear_peer(o, bm.get("add") or [], bm.get("sub") or [], g, has_tol, tol):
            return False
    return True


def _series(sm: dict[str, Any], o: Any, cv: D, has_tol: bool, tol: tuple[Any, Any]) -> bool:
    if not isinstance(o, list):
        return False
    nums: list[D] = []
    for x in o:
        if not _nm(x):
            return False
        dx = _d(x)
        if dx.is_nan() or dx.is_infinite():
            return False
        nums.append(dx)
    if "monotonic" in sm:
        mono = sm["monotonic"]
        for i in range(1, len(nums)):
            a, b = nums[i - 1], nums[i]
            ok = (a <= b) if mono == "non_decreasing" else (a < b) if mono == "increasing" else (a >= b) if mono == "non_increasing" else (a > b) if mono == "decreasing" else False
            if not ok:
                return False
    if "sum_total" in sm:
        v_star = _d(sm["sum_total"]) * cv
        if abs(sum(nums, D(0)) - v_star) > tol[0] + tol[1] * abs(v_star):
            return False
    if "step_max_delta" in sm:
        max_d = _d(sm["step_max_delta"]) * cv + (tol[0] if has_tol else D(0))
        if any(abs(nums[i] - nums[i - 1]) > max_d for i in range(1, len(nums))):
            return False
    return True


def _cl(n: dict[str, Any], o: Any, p: str, pres: dict[str, Any], un: dict[str, Any], pu: str, g: Any) -> str:
    m, k, ki, pm, sm = pres.get(p, pres.get("*", "exact")), n.get("keys"), n.get("in"), n.get("peer"), n.get("series")
    if any(x not in _OPS for x in n) or m == "unobservable" or (o is _ABS and m != "exact") or (isinstance(pm, dict) and any(x not in ("le", "ge", "eq", "sum", "balance") for x in pm)) or ("series" in n and not isinstance(sm, dict)):
        return "inconclusive"
    if o is _ABS or (_nm(o) and _d(o).is_nan()):
        return "violated"
    cv = _d(un.get(f"{n['convert_from']}->{pu}", 1)) if n.get("convert_from") and pu else D(1)
    t = n.get("tol")
    tol = (_d(t.get("abs", 0)) * cv, _d(t.get("rel", 0))) if isinstance(t, dict) else (D(0), D(0))
    has_tol = isinstance(t, dict) and (tol[0] > 0 or tol[1] > 0)
    exact_scale = n.get("exact_scale") is True
    if "eq" in n and (n["eq"] is None or o is None) and m != "exact":
        return "inconclusive"
    for x in ((o if isinstance(o, list) else [o]) if "min" in n or "max" in n else ()):
        if not (isinstance(o, list) and not _nm(x)) and any(b in n and ((c := _cmp(x, n[b], cv)) is None or c * s > 0) for b, s in (("min", -1), ("max", 1))):
            return "violated"
    if ("eq" in n and not _eq(o, n["eq"], cv, tol, exact_scale)) or ("in" in n and not (isinstance(ki, list) and any(_eq(o, x, cv, exact_scale=exact_scale) for x in ki))) or ("not_in" in n and (not isinstance(n["not_in"], list) or any(_eq(o, x, cv, exact_scale=exact_scale) for x in n["not_in"]))):
        return "violated"
    if "contains" in n and not _contains(n["contains"], o, exact_scale):
        return "violated"
    if (isinstance(n.get("len"), dict) and (not isinstance(o, (str, bytes, list, dict)) or len(o) < n["len"].get("min", 0) or len(o) > n["len"].get("max", len(o)))) or ("prefix" in n and not (isinstance(o, str) and o.startswith(n["prefix"]))) or ("suffix" in n and not (isinstance(o, str) and o.endswith(n["suffix"]))):
        return "violated"
    if (isinstance(k, dict) and (not isinstance(o, dict) or ("allow" in k and m == "exact" and any(x not in k["allow"] and v is not _ABS for x, v in o.items())) or ("forbid" in k and _fk(o, k["forbid"])))) or (isinstance(pm, dict) and not _peer(pm, o, g, has_tol, tol, exact_scale)) or (isinstance(sm, dict) and not _series(sm, o, cv, has_tol, tol)):
        return "violated"
    return "inconclusive" if isinstance(k, dict) and m != "exact" else "passed"


def _match_ft(sym: str, pat: str) -> bool:
    s, p = sym.strip(), pat.strip()
    if not s or not p or "#" not in s or "#" not in p:
        return False
    if s == p:
        return True
    sp, ss = s.split("#", 1)
    pp, ps = p.split("#", 1)
    pok = sp.startswith(pp[:-3] + "/") if pp.endswith("/**") else (sp.startswith(pp.rstrip("*")) if pp.endswith("*") else sp == pp)
    return pok and (ss.startswith(ps.rstrip("*")) if ps.endswith("*") else ss == ps)


def _judge(c: dict[str, Any], cid: str, e: Any, dec: Any = None) -> str:
    out, pay, pres, fr, ts, io = dec if dec is not None else _env(e)
    cm, cx = c["cases"][cid], c["obs"]
    cw = cm.get("writes")
    ps = cw if isinstance(cw, list) else cx["w"]
    wp = lambda w: w in ps or w.split("#")[0] in ps or ("#" not in w and any(x.split("#")[0] == w for x in ps))
    has_fr = "writes" in fr
    ws = fr["writes"] if has_fr else []
    if not isinstance(ws, list) or not all(isinstance(w, str) for w in ws):
        return "inconclusive"
    if out != "returned" or any(not wp(w) for w in ws):
        return "violated"
    init_s = {x.strip() for x in io}
    fts = cx.get("ft") or ()
    if fts and any(_match_ft(s, pat) for s in ts if s.strip() and s.strip() not in init_s for pat in fts):
        return "violated"
    ptr = lambda k: cx["proj"].get(k, "/" + k.replace("~", "~0").replace("/", "~1"))

    def at(k: str) -> Any:
        v = pay
        for s in (ptr(k)[1:].split("/") if ptr(k) else ()):
            s = s.replace("~1", "/").replace("~0", "~")
            v = v[s] if isinstance(v, dict) and s in v else (v[int(s)] if isinstance(v, list) and s.isdigit() and str(int(s)) == s and int(s) < len(v) else _ABS)
        return v

    th = cm.get("then") or {}
    peers: dict[str, Any] = {}
    if any(isinstance(n, dict) and "peer" in n for n in th.values()):
        peers = {f"when.{k}": x["eq"] for k, x in (cm.get("when") or {}).items() if list(x) == ["eq"]}
        for k in {*th, *cx["proj"]}:
            peers[f"then.{k}"] = peers[k] = at(k)
    rs = {_cl(n, at(k), ptr(k), pres, cx["units"], cx["unit"].get(k, ""), lambda r: peers.get(r, _ABS)) for k, n in th.items()}
    if not has_fr and isinstance(cw, list) and any(not wp(w) for w in cx["w"]):
        rs.add("inconclusive")
    return "violated" if "violated" in rs else ("inconclusive" if "inconclusive" in rs else "passed")


def red03(c: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any]:
    try:
        dec_m = ev.get("_obs_dec") or {}
        ev["red"] = {k for k, e in (ev.get("observations") or {}).items() if ev["outcome"] == "passed" and ("obs" not in c or _judge(c, k, e, dec_m.get(k)) != "passed")}
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
        ev["red"] = set(ev["cases"])
    return ev
