#!/usr/bin/env python3
"""Schema 0.3 lossless observation decoder and relational re-judge (drift.observation/1)."""

from __future__ import annotations

import re
from decimal import Decimal as D
from typing import Any

_OPS = {"eq", "min", "max", "in", "not_in", "len", "prefix", "suffix", "keys", "peer", "tol", "convert_from"}
_ABS = object()
_d = lambda x: D(repr(x)) if isinstance(x, float) else D(x)
_nm = lambda x: isinstance(x, (int, float, D)) and not isinstance(x, bool)


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
            return float(x)
        if t == "bytes":
            return bytes.fromhex(x)
        raise ValueError(t)
    o: dict[str, Any] = {}
    for k, x in v.items():
        if (k.startswith("$") and not k.startswith("$$")) or (k.lstrip("$") in o and k.startswith("$$")):
            raise ValueError(k)
        o[k[1:] if k.startswith("$$") else k] = _ob(x)
    return o


def _env(e: Any) -> tuple[Any, ...]:
    if not isinstance(e, dict) or e.get("schema") != "drift.observation/1" or e.get("outcome", "returned") not in ("returned", "thrown", "timeout", "interrupted"):
        raise ValueError("observation")
    ts = e.get("touched_symbols") or []
    io = e.get("init_only_symbols") or []
    if not isinstance(ts, list) or not all(isinstance(x, str) for x in ts) or not isinstance(io, list) or not all(isinstance(x, str) for x in io):
        raise ValueError("touched_symbols")
    return e.get("outcome", "returned"), _ob(e["payload"]) if "payload" in e else _ABS, e.get("presence", {}), e.get("frame", {}), ts, io


def obs03(d: dict[str, Any], cs: list[str], sch: str) -> dict[str, Any]:
    if "observations" not in d:
        return {}
    if sch != "0.3" or not isinstance(d["observations"], dict) or any(k not in cs for k in d["observations"]):
        raise ValueError("observations")
    return {"observations": d["observations"], "_obs_dec": {k: _env(e) for k, e in d["observations"].items()}}


def _cmp(a: Any, b: Any, cv: D = D(1)) -> int | None:
    a, b = _d(a), _d(b) * cv
    return None if a.is_nan() or b.is_nan() or not (_nm(a) and _nm(b)) else (a > b) - (a < b)


def _eq(o: Any, l: Any, cv: D = D(1), tol: tuple[Any, Any] = (0, 0)) -> bool:
    if l is None or isinstance(l, bool):
        return o is l
    if isinstance(l, str):
        return o == l if not isinstance(o, D) else (re.fullmatch(r"[+-]?\d+\.?\d*", l) is not None and D(l) == o)
    if _nm(l):
        return _nm(o) and abs(_d(o) - _d(l) * cv) <= tol[0] + tol[1] * abs(_d(l) * cv)
    if isinstance(l, list):
        return isinstance(o, list) and len(o) == len(l) and all(map(_eq, o, l))
    return isinstance(l, dict) and isinstance(o, dict) and o.keys() == l.keys() and all(_eq(o[k], x) for k, x in l.items())


def _fk(o: Any, fs: Any) -> bool:
    return (isinstance(o, dict) and any((k in fs and v is not _ABS) or _fk(v, fs) for k, v in o.items())) or (isinstance(o, list) and any(_fk(x, fs) for x in o))


def _peer(pm: dict[str, Any], o: Any, g: Any) -> bool:
    vs = [g(r) for r in [*(pm.get("sum") or []), *[pm[k] for k in ("le", "ge", "eq") if k in pm]]]
    if not all(map(_nm, [o, *vs])):
        return "eq" in pm and len(pm) == 1 and o == g(pm["eq"])
    return not any(k in pm and ((c := _cmp(o, g(pm[k]))) is None or c * s > 0) for k, s in (("le", 1), ("ge", -1))) and ("eq" not in pm or _cmp(o, g(pm["eq"])) == 0) and ("sum" not in pm or _d(o) == sum(_d(g(r)) for r in pm["sum"]))


def _cl(n: dict[str, Any], o: Any, p: str, pres: dict[str, Any], un: dict[str, Any], pu: str, g: Any) -> str:
    m, k, ki, pm = pres.get(p, pres.get("*", "exact")), n.get("keys"), n.get("in"), n.get("peer")
    if any(x not in _OPS for x in n) or m == "unobservable" or (o is _ABS and m != "exact") or (isinstance(pm, dict) and (any(x not in ("le", "ge", "eq", "sum") for x in pm) or "tol" in n)):
        return "inconclusive"
    if o is _ABS or (_nm(o) and _d(o).is_nan()):
        return "violated"
    cv = _d(un.get(f"{n['convert_from']}->{pu}", 1)) if n.get("convert_from") and pu else D(1)
    t = n.get("tol")
    tol = (_d(t.get("abs", 0)) * cv, _d(t.get("rel", 0))) if isinstance(t, dict) else (0, 0)
    if "eq" in n and (n["eq"] is None or o is None) and m != "exact":
        return "inconclusive"
    for x in ((o if isinstance(o, list) else [o]) if "min" in n or "max" in n else ()):
        if not (isinstance(o, list) and not _nm(x)) and any(b in n and ((c := _cmp(x, n[b], cv)) is None or c * s > 0) for b, s in (("min", -1), ("max", 1))):
            return "violated"
    if ("eq" in n and not _eq(o, n["eq"], cv, tol)) or ("in" in n and not (isinstance(ki, list) and any(_eq(o, x, cv) for x in ki))) or ("not_in" in n and (not isinstance(n["not_in"], list) or any(_eq(o, x, cv) for x in n["not_in"]))):
        return "violated"
    if (isinstance(n.get("len"), dict) and (not isinstance(o, (str, bytes, list, dict)) or len(o) < n["len"].get("min", 0) or len(o) > n["len"].get("max", len(o)))) or ("prefix" in n and not (isinstance(o, str) and o.startswith(n["prefix"]))) or ("suffix" in n and not (isinstance(o, str) and o.endswith(n["suffix"]))):
        return "violated"
    if (isinstance(k, dict) and (not isinstance(o, dict) or ("allow" in k and m == "exact" and any(x not in k["allow"] and v is not _ABS for x, v in o.items())) or ("forbid" in k and _fk(o, k["forbid"])))) or (isinstance(pm, dict) and not _peer(pm, o, g)):
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
    ws, ps = fr.get("writes") or [], cm["writes"] if isinstance(cm.get("writes"), list) else cx["w"]
    if not isinstance(ws, list) or not all(isinstance(w, str) for w in ws):
        return "inconclusive"
    if out != "returned" or any(not (w in ps or w.split("#")[0] in ps or ("#" not in w and any(x.split("#")[0] == w for x in ps))) for w in ws):
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
        peers = {f"when.{k}": _ob(x["eq"]) for k, x in (cm.get("when") or {}).items() if list(x) == ["eq"]}
        for k in {*th, *cx["proj"]}:
            peers[f"then.{k}"] = peers[k] = at(k)
    rs = {_cl(n, at(k), ptr(k), pres, cx["units"], cx["unit"].get(k, ""), lambda r: peers.get(r, _ABS)) for k, n in th.items()}
    return "violated" if "violated" in rs else ("inconclusive" if "inconclusive" in rs else "passed")


def red03(c: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any]:
    try:
        dec_m = ev.get("_obs_dec") or {}
        ev["red"] = {k for k, e in (ev.get("observations") or {}).items() if ev["outcome"] == "passed" and ("obs" not in c or _judge(c, k, e, dec_m.get(k)) != "passed")}
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
        ev["red"] = set(ev["cases"])
    return ev
