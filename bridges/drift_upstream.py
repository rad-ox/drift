"""Upstream boundary bundle discovery and stub synthesis for DRIFT Python."""
from __future__ import annotations

import importlib.util
import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

try:
    from . import drift_cli as _cli
except ImportError:
    try:
        import drift_cli as _cli  # type: ignore[no-redef]
    except ImportError:
        _s = importlib.util.spec_from_file_location('drift_cli', Path(__file__).with_name('drift_cli.py'))
        assert _s is not None and _s.loader is not None
        _cli = importlib.util.module_from_spec(_s)
        _s.loader.exec_module(_cli)

from drift_security import (
    _canon_stub_ref,
    _is_num,
    _is_relational_map,
    _peer_order_relation,
    _round_num,
    clone_json,
    split_resource_pointer,
    tighten_then_by_sum_residuals as _tighten_then_by_sum_residuals,
)


def write_pointer(target: Any, raw_ptr: str, value: Any) -> Any:
    _, ptr = split_resource_pointer(raw_ptr)
    if ptr == '': return clone_json(value)
    if not isinstance(ptr, str) or not ptr.startswith('/'): raise ValueError(f'invalid RFC 6901 JSON Pointer "{raw_ptr}"')
    segs = [s.replace('~1', '/').replace('~0', '~') for s in ptr[1:].split('/')]

    def put_at(cur: Any, idx: int) -> Any:
        seg, last = segs[idx], idx == len(segs) - 1
        n_idx = not last and (segs[idx + 1] == '0' or (segs[idx + 1].isdigit() and not segs[idx + 1].startswith('0')))
        if (seg == '0' or (seg.isdigit() and not seg.startswith('0'))) and isinstance(cur, list):
            ai, arr = int(seg), list(cur)
            while len(arr) <= ai: arr.append(None)
            arr[ai] = clone_json(value) if last else put_at(arr[ai] if isinstance(arr[ai], (dict, list)) else ([] if n_idx else {}), idx + 1)
            return arr
        obj = dict(cur) if isinstance(cur, Mapping) else {}
        obj[seg] = clone_json(value) if last else put_at(obj[seg] if isinstance(obj.get(seg), (Mapping, list)) else ([] if n_idx else {}), idx + 1)
        return obj

    return put_at(target, 0)


def _rel_peer_rank(val: Any, rk: frozenset[str]) -> int:
    if not _is_relational_map(val, rk): return 0
    if isinstance(val.get('sum_fields'), (list, tuple)): return 2 + len(val['sum_fields'])
    return 1 if any(k in val for k in ('eq_field', 'ge_field', 'le_field')) else 0


def read_pointer(target: Any, raw_ptr: str) -> tuple[bool, Any]:
    if not isinstance(raw_ptr, str): return (False, None)
    res, ptr = split_resource_pointer(raw_ptr)
    cur = target[res] if res and isinstance(target, Mapping) and res in target else target
    if ptr == '': return (True, cur)
    if not ptr.startswith('/'): return (False, None)
    for seg in (s.replace('~1', '/').replace('~0', '~') if '~' in s else s for s in ptr[1:].split('/')):
        if isinstance(cur, (list, tuple)):
            if not (seg == '0' or (seg.isdigit() and not seg.startswith('0'))): return (False, None)
            idx = int(seg)
            if idx < 0 or idx >= len(cur): return (False, None)
            cur = cur[idx]
        elif isinstance(cur, Mapping) and seg in cur:
            cur = cur[seg]
        elif callable(cur):
            cur = cur(seg)
            if cur is None: return (False, None)
        elif hasattr(cur, 'getAttribute') and callable(getattr(cur, 'getAttribute')):
            if seg == 'dataset':
                el = cur
                cur = lambda k, e=el: e.getAttribute('data-' + re.sub(r'[A-Z]', lambda m: '-' + m.group(0).lower(), k))
            else:
                cur = cur.getAttribute(seg)
                if cur is None: return (False, None)
        else:
            return (False, None)
    return (True, cur)


def _build_peer_index(when_map: Mapping[str, Any], raw_then_map: Mapping[str, Any], wp: Mapping[str, str], tp: Mapping[str, str], rk: frozenset[str]) -> dict[str, Any]:
    then_map = _tighten_then_by_sum_residuals(when_map, raw_then_map, wp, tp, rk)
    idx: dict[str, Any] = {}
    for wk, wv in when_map.items():
        if not _is_relational_map(wv, rk):
            idx[wk] = wv
            p = split_resource_pointer(wp.get(wk, ''))[1]
            if p.startswith('/'): idx[p] = wv
    rel_entries: list[tuple[str, Mapping[str, Any]]] = []
    for tk, tv in then_map.items():
        if _is_relational_map(tv, rk):
            rel_entries.append((tk, tv))
        else:
            idx[tk] = tv
            p = split_resource_pointer(tp.get(tk, ''))[1]
            if p.startswith('/'): idx[p] = tv
    if rel_entries:
        rel_entries.sort(key=lambda e: (_rel_peer_rank(e[1], rk), e[0]))
        peer_fn = lambda ref: _resolve_stub_peer(ref, {}, idx, wp, tp, rk)
        for _ in range(8):
            progress = False
            for tk, tv in rel_entries:
                if tk not in idx and not any(k in tv and not peer_fn(tv[k])[0] for k in ('eq_field', 'ge_field', 'le_field')) and not (isinstance(tv.get('sum_fields'), (list, tuple)) and any(not peer_fn(sf)[0] for sf in tv['sum_fields'])):
                    w = witness_value(tv, rk, lambda x: x, peer_fn)
                    idx[tk] = w
                    p = split_resource_pointer(tp.get(tk, ''))[1]
                    if p.startswith('/'): idx[p] = w
                    progress = True
            if not progress: break
    return idx


def _resolve_stub_peer(ref: Any, base: Any, peer_idx: Mapping[str, Any], wp: Mapping[str, str], tp: Mapping[str, str], rk: frozenset[str]) -> tuple[bool, Any]:
    if not isinstance(ref, str) or not ref.strip(): return (False, None)
    s, bare = ref.strip(), ref.strip().lstrip('/')
    if s.startswith('/'):
        ok, val = read_pointer(base, s)
        if ok and not _is_relational_map(val, rk): return (True, val)
    else:
        if isinstance(base, Mapping) and s in base and not _is_relational_map(base[s], rk): return (True, base[s])
        for pm in (tp, wp):
            if s in pm:
                ok, val = read_pointer(base, pm[s])
                if ok and not _is_relational_map(val, rk): return (True, val)
        ok, val = read_pointer(base, '/' + bare)
        if ok and not _is_relational_map(val, rk): return (True, val)
    tgt = split_resource_pointer(s if s.startswith('/') else (tp.get(s) or wp.get(s) or ('/' + bare)))[1]
    for cand in (s, bare, tgt):
        if cand and cand in peer_idx: return (True, peer_idx[cand])
    return (False, None)


def _resolve_rel_bounds(val: Mapping[str, Any], peer_fn: Callable[[Any], tuple[bool, Any]] | None) -> tuple[bool, Any, int | float | None, int | float | None]:
    if peer_fn is not None and 'eq_field' in val:
        ok, eq_v = peer_fn(val['eq_field'])
        if ok: return (True, eq_v, None, None)
    lo: int | float | None = val['min'] if _is_num(val.get('min')) else None
    hi: int | float | None = val['max'] if _is_num(val.get('max')) else None
    if peer_fn is not None and 'ge_field' in val:
        ok, ge_v = peer_fn(val['ge_field'])
        if ok and _is_num(ge_v): lo = ge_v if lo is None or ge_v > lo else lo
    if peer_fn is not None and 'le_field' in val:
        ok, le_v = peer_fn(val['le_field'])
        if ok and _is_num(le_v): hi = le_v if hi is None or le_v < hi else hi
    if peer_fn is not None and isinstance(val.get('sum_fields'), (list, tuple)) and len(val['sum_fields']) >= 2:
        s_val, all_ok = 0, True
        for sf in val['sum_fields']:
            ok, sv = peer_fn(sf)
            if not ok or not _is_num(sv):
                all_ok = False
                break
            s_val = s_val + sv
        if all_ok:
            if isinstance(s_val, float): s_val = round(s_val, 12)
            lo = s_val if lo is None or s_val > lo else lo
            hi = s_val if hi is None or s_val < hi else hi
    return (False, None, lo, hi)


def _build_affix_str(val: Mapping[str, Any], length: int) -> str:
    pfx, sfx = (val['prefix'] if isinstance(val.get('prefix'), str) else ''), (val['suffix'] if isinstance(val.get('suffix'), str) else '')
    return f"{pfx}{'x' * max(0, length - len(pfx) - len(sfx))}{sfx}"


def witness_value(val: Any, rk: frozenset[str], clone_fn: Callable[[Any], Any], peer_fn: Callable[[Any], tuple[bool, Any]] | None = None) -> Any:
    return witness_variants(val, rk, clone_fn, peer_fn)[0]


def witness_variants(val: Any, rk: frozenset[str], clone_fn: Callable[[Any], Any], peer_fn: Callable[[Any], tuple[bool, Any]] | None = None) -> list[Any]:
    if _is_relational_map(val, rk):
        eq_ok, eq_v, lo, hi = _resolve_rel_bounds(val, peer_fn)
        if eq_ok: return [clone_fn(eq_v)]
        if isinstance(val.get('in'), (list, tuple)) and val['in']:
            filt = [x for x in val['in'] if (lo is None or (_is_num(x) and x >= lo)) and (hi is None or (_is_num(x) and x <= hi))]
            return [clone_fn(x) for x in (filt or val['in'])]
        if lo is not None and hi is not None: return [lo] if lo == hi else [lo, hi]
        if lo is not None or hi is not None: return [lo if lo is not None else hi]
        if isinstance(val.get('contains'), (list, tuple)) and val['contains']:
            out = [clone_fn(x) for x in val['contains']]
            min_l = max(1 if val.get('non_empty') is True else 0, int(val.get('min_len') or 0) if type(val.get('min_len')) is int else 0)
            while len(out) < min_l: out.append(clone_fn(val['contains'][0]))
            return [out]
        if isinstance(val.get('prefix'), str) or isinstance(val.get('suffix'), str) or type(val.get('min_len')) is int or type(val.get('max_len')) is int or val.get('non_empty') is True:
            pfx_len, sfx_len = (len(val['prefix']) if isinstance(val.get('prefix'), str) else 0), (len(val['suffix']) if isinstance(val.get('suffix'), str) else 0)
            llo = max(1 if val.get('non_empty') is True else 0, int(val.get('min_len') or 0) if type(val.get('min_len')) is int else 0, pfx_len + sfx_len)
            lhi = int(val['max_len']) if type(val.get('max_len')) is int else llo
            return [_build_affix_str(val, llo), _build_affix_str(val, lhi)] if lhi > llo else [_build_affix_str(val, llo)]
        return ['']
    return [clone_fn(val)]


_HOMOLOGOUS_PAIRS = frozenset({
    '1:2', '2:1', 'a:b', 'b:a', 'x:y', 'y:x', 'left:right', 'right:left',
    'src:dst', 'dst:src', 'source:target', 'target:source', 'from:to', 'to:from',
    'primary:secondary', 'secondary:primary', 'first:second', 'second:first',
})


def _is_homologous_key(a: str, b: str) -> bool:
    if a == b: return False
    la, lb = a.lower(), b.lower()
    ta, tb = la.split('_'), lb.split('_')
    if len(ta) == len(tb) and len(ta) >= 2:
        diffs = [f'{ta[i]}:{tb[i]}' for i in range(len(ta)) if ta[i] != tb[i]]
        if len(diffs) == 1 and diffs[0] in _HOMOLOGOUS_PAIRS: return True
    return len(la) == len(lb) and len(la) >= 2 and la[:-1] == lb[:-1] and la[-1] in '12abxy' and lb[-1] in '12abxy'


def synthesize_view_output(view: Mapping[str, Any], case_id: str, base: Mapping[str, Any] | None, then_map: Mapping[str, Any] | None, extract_proj_fn: Callable[[Mapping[str, Any], str], dict[str, str]], write_ptr_fn: Callable[[Any, str, Any], Any], clone_fn: Callable[[Any], Any], rk: frozenset[str]) -> Any:
    wp, tp = extract_proj_fn(view, 'when'), extract_proj_fn(view, 'then')
    case_m = (view.get('cases') or {}).get(case_id) or {}
    when_map, raw_then_0 = case_m.get('when') or {}, case_m.get('then') or {}
    raw_then = _tighten_then_by_sum_residuals(when_map, raw_then_0, wp, tp, rk)
    tbl = _tighten_then_by_sum_residuals(when_map, then_map, wp, tp, rk) if then_map is not None else raw_then
    out = clone_fn(base if isinstance(base, Mapping) else {})
    peer_idx = _build_peer_index(when_map, tbl, wp, tp, rk)
    peer_fn = lambda ref: _resolve_stub_peer(ref, out, peer_idx, wp, tp, rk)
    resolved: dict[str, Any] = {}
    for k, v in sorted(tbl.items(), key=lambda e: (_rel_peer_rank(e[1], rk), e[0])):
        vars_v = witness_variants(v, rk, clone_fn, peer_fn)
        w = vars_v[0]
        if len(vars_v) > 1 and not (isinstance(v, Mapping) and 'eq_field' in v):
            for pk, pv in resolved.items():
                if _is_homologous_key(pk, k) and pv == w and type(pv) is type(w):
                    w = next((c for c in vars_v[1:] if c != pv or type(c) is not type(pv)), w)
                    break
        resolved[k] = peer_idx[k] = w
        p = split_resource_pointer(tp.get(k, ''))[1]
        if p.startswith('/'): peer_idx[p] = w
        if k in tp: out = write_ptr_fn(out, tp[k], w)
    for k in tbl:
        if k not in tp and isinstance(out, dict): out[k] = resolved[k]
    return out


def _lookup_when_input(when_input: Mapping[str, Any], wk: str, wp: Mapping[str, str]) -> tuple[bool, Any]:
    if wk in when_input: return (True, when_input[wk])
    raw_p = wp.get(wk, '')
    for p in (raw_p, split_resource_pointer(raw_p)[1], '/' + wk):
        if p:
            if p in when_input: return (True, when_input[p])
            ok, val = read_pointer(when_input, p)
            if ok: return (True, val)
    return (False, None)


def resolve_stub_case_id(view: Mapping[str, Any], id_or_res: str, case_or_when: str | Mapping[str, Any], base: Mapping[str, Any] | None, extract_proj_fn: Callable[[Mapping[str, Any], str], dict[str, str]], write_ptr_fn: Callable[[Any, str, Any], Any], clone_fn: Callable[[Any], Any], rk: frozenset[str]) -> str:
    cases = view.get('cases') if isinstance(view, Mapping) else None
    if isinstance(case_or_when, str):
        cm = cases.get(case_or_when) if isinstance(cases, Mapping) else None
        if not isinstance(cm, Mapping): raise KeyError(f'contract "{id_or_res}" has no case "{case_or_when}"')
        if 'status' in cm: raise ValueError(f'case "{case_or_when}" of contract "{id_or_res}" is {cm["status"]} and cannot be stubbed')
        return case_or_when
    if not isinstance(case_or_when, Mapping) or not isinstance(cases, Mapping): raise KeyError(f'contract "{id_or_res}" has no case matching when input')
    wp, tp, best_score, best_cases = extract_proj_fn(view, 'when'), extract_proj_fn(view, 'then'), 0, []
    for cid in sorted(cases.keys()):
        cm = cases[cid]
        if not isinstance(cm, Mapping) or 'status' in cm or not isinstance(cm.get('when'), Mapping): continue
        matched, compat = 0, True
        for wk, wv in cm['when'].items():
            ok, actual = _lookup_when_input(case_or_when, wk, wp)
            if ok:
                if actual != wv or type(actual) is not type(wv): compat = False; break
                matched += 1
        if compat and matched > 0:
            if matched > best_score: best_score, best_cases = matched, [cid]
            elif matched == best_score: best_cases.append(cid)
    if not best_cases: raise KeyError(f'contract "{id_or_res}" has no case matching when input')
    if len(best_cases) >= 2:
        vars_by_c: list[dict[str, list[Any]]] = []
        for c in best_cases:
            cm, t_tbl = cases[c], cases[c].get('then') or {}
            p_idx = _build_peer_index(cm.get('when') or {}, t_tbl, wp, tp, rk)
            p_fn = lambda ref, idx=p_idx: _resolve_stub_peer(ref, base, idx, wp, tp, rk)
            m: dict[str, list[Any]] = {}
            for tk in sorted(t_tbl.keys()): m.setdefault(split_resource_pointer(tp.get(tk, ''))[1] or tk, witness_variants(t_tbl[tk], rk, clone_fn, p_fn))
            vars_by_c.append(m)
        for i, c1 in enumerate(best_cases):
            for j in range(i + 1, len(best_cases)):
                for ptr, v1 in vars_by_c[i].items():
                    if ptr in vars_by_c[j]:
                        v2 = vars_by_c[j][ptr]
                        if v1 != v2 or [type(x) for x in v1] != [type(x) for x in v2]: raise ValueError(f'ambiguous boundary projection on "{id_or_res}" ({ptr}) across {c1}, {best_cases[j]}')
    return best_cases[0]


def synthesize_view_variants(view: Mapping[str, Any], case_id: str, base: Mapping[str, Any] | None, extract_proj_fn: Callable[[Mapping[str, Any], str], dict[str, str]], write_ptr_fn: Callable[[Any, str, Any], Any], clone_fn: Callable[[Any], Any], rk: frozenset[str]) -> list[Any]:
    wp, tp = extract_proj_fn(view, 'when'), extract_proj_fn(view, 'then')
    case_m = (view.get('cases') or {}).get(case_id) or {}
    when_map, raw_tbl = case_m.get('when') or {}, case_m.get('then') or {}
    tbl = _tighten_then_by_sum_residuals(when_map, raw_tbl, wp, tp, rk)
    peer_idx = _build_peer_index(when_map, tbl, wp, tp, rk)
    peer_fn = lambda ref: _resolve_stub_peer(ref, base, peer_idx, wp, tp, rk)
    keys = sorted(tbl.keys())
    d, vars_by_key = len(keys), [witness_variants(tbl[k], rk, clone_fn, peer_fn) for k in keys]
    cur, max_exc, out = {keys[i]: vars_by_key[i][0] for i in range(d)}, (2 if d >= 3 else d), []

    def dfs(pos: int, exc: int) -> None:
        if pos == d or exc >= max_exc:
            eff = {k: (tbl[k] if _rel_peer_rank(tbl[k], rk) > 0 and cur[k] == vars_by_key[i][0] else cur[k]) for i, k in enumerate(keys)}
            out.append(synthesize_view_output(view, case_id, base, eff, extract_proj_fn, write_ptr_fn, clone_fn, rk))
            return
        dfs(pos + 1, exc)
        vars_p, k = vars_by_key[pos], keys[pos]
        for idx in range(1, len(vars_p)):
            cur[k] = vars_p[idx]
            dfs(pos + 1, exc + 1)
        cur[k] = vars_p[0]

    dfs(0, 0)
    return out


def discover_events_dir(cwd: Path, environ: Mapping[str, str]) -> str:
    sd = environ.get('DRIFT_STATE_DIR', '').strip()
    if sd:
        sd_p = Path(sd).resolve()
        for sub in ('.drift', '.drift-work'):
            cand = sd_p / sub / 'events'
            if cand.is_dir():
                return str(cand)
        if not environ.get('DRIFT_RESOLVED', '').strip():
            return str(sd_p / '.drift-work' / 'events')
    cur = cwd.resolve()
    area_root: Path | None = None
    while True:
        for sub in ('.drift', '.drift-work'):
            cand = cur / sub / 'events'
            if cand.is_dir():
                return str(cand)
        if (cur / '.drift' / 'config.toml').is_file() or (cur / '.drift' / 'contracts').is_dir():
            area_root = cur
            break
        if cur.parent == cur:
            break
        cur = cur.parent
    return str(area_root / '.drift-work' / 'events') if area_root is not None and not environ.get('DRIFT_RESOLVED', '').strip() else ''



def resolve_seam_mutated_then(cur_ctx: Any, prod_view: Mapping[str, Any], id_or_res: str, resolved_case_id: str, escape_ptr_fn: Callable[[str], str], apply_mut_fn: Callable[..., dict[str, Any]]) -> dict[str, Any] | None:
    m = getattr(cur_ctx, 'mutation_override', None) if cur_ctx is not None else None
    if not isinstance(m, Mapping) or not isinstance(m.get('path'), str):
        return None
    prod_id = str(prod_view.get('id') or id_or_res)
    pfx = f"/cases/{escape_ptr_fn(str(m.get('case', '')))}/seam/{escape_ptr_fn(prod_id)}#{escape_ptr_fn(resolved_case_id)}/"
    if not m['path'].startswith(pfx):
        return None
    sub_path = f"/cases/{escape_ptr_fn(resolved_case_id)}/then/{m['path'][len(pfx):]}"
    raw_then = dict(((prod_view.get('cases') or {}).get(resolved_case_id) or {}).get('then') or {})
    return apply_mut_fn(raw_then, prod_id, resolved_case_id, sub_path, m.get('after'), 'then', None)


def run_seam_bounds_checks(ctx: Any, case_id: str, id_or_res: str, prod_case_or_when: Any, checks: Any, base: Mapping[str, Any] | None, resolve_stub_fn: Callable[..., tuple[dict[str, Any], str]], build_variants_fn: Callable[..., list[Any]]) -> None:
    ctx._require_tagged(case_id)
    prod_view, prod_case_id = resolve_stub_fn(id_or_res, prod_case_or_when, base)
    prod_id = str(prod_view.get('id') or id_or_res)
    variants = build_variants_fn(prod_view, prod_case_id, base)
    exec_fn = checks if callable(checks) else (checks.get('execute') if isinstance(checks, Mapping) and callable(checks.get('execute')) else None)
    if exec_fn is None:
        raise ValueError(f'check_seam_bounds for {ctx.contract_id}.{case_id} requires an execute callable or mapping with execute')
    proj_checks = checks if isinstance(checks, Mapping) else None
    for variant in variants:
        try:
            observed = exec_fn(variant)
            ctx.check_projection(case_id, observed, proj_checks)
        except AssertionError as e:
            if '[seam counterexample:' not in str(e):
                raise AssertionError(f'{ctx.contract_id}.{case_id} failed on seam {prod_id}#{prod_case_id} [seam counterexample: {json.dumps(variant, sort_keys=True)}]: {e}') from e
            raise


def run_case_mutants(mut_cfg: Mapping[str, Any], mut_out: Any, ctx: Any, contract: str, passed: bool, elapsed: float, time_mod: Any, with_mut_fn: Callable[..., Any], make_ctx_fn: Callable[[Any], Any], fn: Callable[[Any], Any], dump_json_fn: Callable[[Any], str]) -> None:
    targets = [m for cid in ctx.cases for m in mut_cfg['by_case'].get(f'{contract}\x00{cid}', ())]
    if not targets:
        return
    budget_s, mut_start, over, lines = max(0.25 * len(targets), 20.0 * len(targets) * elapsed), time_mod.perf_counter(), False, []
    for target in targets:
        outcome = 'inconclusive'
        if not passed or over or time_mod.perf_counter() - mut_start > budget_s:
            over = over or passed
        else:
            thrown: BaseException | None = None
            failed = False
            try:
                with_mut_fn(target, lambda t=target: fn(make_ctx_fn(t)))
            except BaseException as m_err:
                failed, thrown = True, m_err
            if time_mod.perf_counter() - mut_start > budget_s:
                over = True
            elif not failed:
                outcome = 'survived'
            elif isinstance(thrown, AssertionError):
                outcome = 'killed'
        lines.append(dump_json_fn({'manifest': mut_cfg['manifest_id'], 'contract': target['contract'], 'digest': target['digest'], 'mutant': target['id'], 'case': target['case'], 'outcome': outcome, 'control': 'passed' if passed else 'failed'}))
    with mut_out.open('a', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')




