"""Surface key evaluation helper for the DRIFT Python bridge."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

try:
    from . import drift_ui as _ui
except ImportError:
    import drift_ui as _ui  # type: ignore[no-redef]


def _is_fin(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def unwrap_03_eq(v: Any) -> Any:
    return v['eq'] if isinstance(v, Mapping) and len(v) == 1 and 'eq' in v else v


def build_when_env(when_table: Mapping[str, Any] | None, when_proj: Mapping[str, str] | None, then_table: Mapping[str, Any] | None, then_proj: Mapping[str, str] | None, payload: Any = None, explicit_when: Mapping[str, Any] | None = None, read_pointer: Any = None, check_rel_fn: Any = None, contract_id: str = '', case_id: str = '') -> dict[str, Any]:
    env: dict[str, Any] = {}
    has_exp = isinstance(explicit_when, Mapping) or (isinstance(payload, Mapping) and (isinstance(payload.get('when'), Mapping) or isinstance(payload.get('before'), Mapping)))
    if not has_exp:
        for wk, wv in (when_table or {}).items():
            if not isinstance(wv, Mapping):
                env[str(wk)] = wv
            elif 'eq' in wv and 'peer' not in wv and 'eq_field' not in wv:
                env[str(wk)] = wv['eq']
    if isinstance(explicit_when, Mapping):
        for wk, ov in explicit_when.items():
            env[str(wk)] = ov
    if isinstance(payload, Mapping):
        for sub_k in ('when', 'before'):
            sub = payload.get(sub_k)
            if isinstance(sub, Mapping):
                for wk, ov in sub.items():
                    env[str(wk)] = ov
        for pk, pv in payload.items():
            if isinstance(pk, str) and pk.startswith('when.') and len(pk) > 5:
                env[pk[5:]] = pv
        if isinstance(when_proj, Mapping) and when_proj and read_pointer is not None:
            t_ptrs = set((then_proj or {}).values()) | {f'/{tk}' for tk in (then_table or ())}
            for wk, w_ptr in when_proj.items():
                for src in (explicit_when, payload.get('when') if isinstance(payload.get('when'), Mapping) else None, payload.get('before') if isinstance(payload.get('before'), Mapping) else None):
                    if isinstance(src, Mapping):
                        ok, val = read_pointer(src, w_ptr)
                        if ok:
                            env[str(wk)] = val
                            break
                else:
                    if not has_exp and w_ptr and w_ptr not in t_ptrs and wk not in (then_table or ()):
                        ok, val = read_pointer(payload, w_ptr)
                        if ok:
                            env[str(wk)] = val
    if has_exp and isinstance(when_table, Mapping) and check_rel_fn is not None:
        for wk, wexp in when_table.items():
            if wk in env:
                act_w = env[wk]
                if isinstance(wexp, Mapping):
                    check_rel_fn(contract_id, case_id, f'when.{wk}', wexp, act_w, env, when_proj or {}, None, env)
                elif act_w != wexp:
                    raise AssertionError(f'{contract_id}.{case_id}: exp when.{wk}={wexp!r}, got {act_w!r}')
    return env


def resolve_peer_value(ref: Any, payload: Any, proj: Mapping[str, str], when_env: Mapping[str, Any] | None, read_pointer: Any) -> tuple[bool, Any]:
    if not isinstance(ref, str) or not ref.strip():
        return (False, None)
    r = ref.strip()
    if r.startswith('when.'):
        wk = r[5:]
        if not wk:
            return (False, None)
        if isinstance(when_env, Mapping):
            if wk in when_env:
                return (True, when_env[wk])
            if r in when_env:
                return (True, when_env[r])
        if isinstance(payload, Mapping) and when_env is None:
            if r in payload:
                return (True, payload[r])
            for sub_k in ('when', 'before'):
                sub = payload.get(sub_k)
                if isinstance(sub, Mapping) and wk in sub:
                    return (True, sub[wk])
        return (False, None)
    if r.startswith('then.'):
        tk = r[5:]
        if not tk:
            return (False, None)
        t_src = payload.get('then') if isinstance(payload, Mapping) and isinstance(payload.get('then'), Mapping) and tk not in payload else payload
        if tk in proj:
            ok, pv = read_pointer(t_src, proj[tk])
            if ok:
                return (True, pv)
        if isinstance(t_src, Mapping) and tk in t_src:
            return (True, t_src[tk])
        if isinstance(payload, Mapping) and r in payload:
            return (True, payload[r])
        return (False, None)
    if r.startswith('/'):
        return read_pointer(payload, r)
    if r in proj:
        return read_pointer(payload, proj[r])
    if isinstance(payload, Mapping) and r in payload:
        return (True, payload[r])
    if isinstance(when_env, Mapping) and r in when_env:
        return (True, when_env[r])
    return (False, None)


def check_surface_key(
    contract_id: str,
    case_id: str,
    key: str,
    exp: Any,
    v: Mapping[str, Any],
    then_table: Mapping[str, Any],
    proj: Mapping[str, str] | None,
    mutation_override: Any,
    check_rel_fn: Any,
) -> bool:
    pfx = f'{contract_id}.{case_id}'

    def fail_unverifiable(msg: str) -> None:
        ev_map = v.get('evidence') if isinstance(v, Mapping) else None
        if isinstance(ev_map, dict) and isinstance(ev_map.get('unverifiable_checks'), int):
            ev_map['unverifiable_checks'] += 1
            if isinstance(ev_map.get('unverifiable_reasons'), list):
                ev_map['unverifiable_reasons'].append(f'unverifiable_then:{key}')
        raise AssertionError(msg)

    def assert_eq(k: str, expected: Any, act: Any) -> None:
        if act != expected:
            raise AssertionError(f'{pfx}: exp {k}={expected}, got {act}')

    def assert_bound(k: str, op: str, expected: Any, act: float) -> None:
        if not _is_fin(expected) or not _is_fin(act):
            raise AssertionError(f'{pfx}: exp {k}{op}{expected}, got {act}')
        target = float(expected)
        if (act > target) if op == '<=' else (act < target):
            raise AssertionError(f'{pfx}: exp {k}{op}{expected}, got {act}')

    if isinstance(v.get('adapter'), Mapping) and isinstance(v['adapter'].get('capabilities'), list):
        _ui.check_required_adapter_capability(contract_id, case_id, key, v, proj)
    els = list(v.get('elements') or ())
    pres_obj = v.get('presentation') if isinstance(v.get('presentation'), Mapping) else {}

    if key in ('clipped_elements', 'unintentional_clipped_count'):
        clip_sub = pres_obj.get('clipping') if isinstance(pres_obj.get('clipping'), Mapping) else {}
        exp_clip = v.get(key, clip_sub.get('unintentional_clipped_count'))
        if not els and not _is_fin(exp_clip):
            fail_unverifiable(f'{pfx}: unverifiable then.{key}: empty surface view')
        clipped = int(exp_clip) if (_is_fin(exp_clip) and not els) else sum(1 for el in els if _ui.evaluate_element_clipping(el)['clipped'])
        assert_eq(key, exp, clipped)
        return True
    if key == 'horizontal_overflow_px':
        exp_ov = v.get('horizontal_overflow_px', pres_obj.get('horizontal_overflow_px'))
        has_vp = _is_fin(v.get('viewportWidth')) and float(v['viewportWidth']) > 0 and _is_fin(v.get('documentWidth'))
        if not has_vp and not _is_fin(exp_ov):
            fail_unverifiable(f'{pfx}: unverifiable then.horizontal_overflow_px: missing viewportWidth')
        act_ov = float(exp_ov) if (_is_fin(exp_ov) and not has_vp) else max(0.0, float(v.get('documentWidth') or 0) - float(v.get('viewportWidth') or 0))
        assert_bound(key, '<=', exp, act_ov)
        return True
    if key in ('min_contrast_ratio', 'min_contrast_wcag22', 'min_contrast_text_normal', 'min_contrast_text_large', 'min_contrast_ui_component'):
        c_sum = _ui.evaluate_wcag22_contrast(els)
        if c_sum['unverifiableCount'] > 0 and 'contrast_unverifiable_count' not in then_table and 'unverifiable_checks' not in then_table:
            fail_unverifiable(f"{pfx}: unverifiable then.{key}: {c_sum['unverifiableCount']} element(s) have indeterminate background")
        cw = pres_obj.get('contrast_wcag22') if isinstance(pres_obj.get('contrast_wcag22'), Mapping) else {}
        if key == 'min_contrast_text_normal':
            act_c = c_sum['textNormalMin'] if c_sum['textNormalMin'] is not None else cw.get('text_normal_min', v.get(key))
        elif key == 'min_contrast_text_large':
            act_c = c_sum['textLargeMin'] if c_sum['textLargeMin'] is not None else cw.get('text_large_min', v.get(key))
        elif key == 'min_contrast_ui_component':
            act_c = c_sum['uiComponentMin'] if c_sum['uiComponentMin'] is not None else cw.get('ui_component_min', v.get(key))
        else:
            act_c = c_sum['overallMin'] if c_sum['overallMin'] is not None else v.get(key, v.get('min_contrast_ratio'))
        if not _is_fin(act_c):
            fail_unverifiable(f'{pfx}: unverifiable then.{key}: no measured elements')
        if isinstance(exp, Mapping) and ('min' in exp or 'max' in exp):
            check_rel_fn(contract_id, case_id, key, exp, float(act_c), v, proj or {}, mutation_override)
        else:
            assert_bound(key, '>=', exp, float(act_c))
        return True
    if key in ('contrast_violations_count', 'contrast_unverifiable_count'):
        c_sum = _ui.evaluate_wcag22_contrast(els)
        cw = pres_obj.get('contrast_wcag22') if isinstance(pres_obj.get('contrast_wcag22'), Mapping) else {}
        has_exp = _is_fin(v.get(key)) or (_is_fin(cw.get('violations_count')) if key == 'contrast_violations_count' else _is_fin(cw.get('unverifiable_count')))
        if c_sum['measuredCount'] == 0 and c_sum['unverifiableCount'] == 0 and not has_exp:
            fail_unverifiable(f'{pfx}: unverifiable then.{key}: no measured elements')
        act_cnt = int(v.get(key, cw.get('violations_count', c_sum['violationsCount']))) if key == 'contrast_violations_count' else int(v.get(key, cw.get('unverifiable_count', c_sum['unverifiableCount'])))
        assert_eq(key, exp, act_cnt)
        return True
    if key == 'min_target_px':
        measured_targets = [
            min(float(el['width']), float(el['height']))
            for el in els
            if isinstance(el, Mapping)
            and not _ui.is_element_hidden(el)
            and el.get('spacingException') is not True
            and _is_fin(el.get('width'))
            and _is_fin(el.get('height'))
            and float(el['width']) > 0
            and float(el['height']) > 0
        ]
        ts_sub = pres_obj.get('target_size') if isinstance(pres_obj.get('target_size'), Mapping) else {}
        exp_t = v.get('min_target_px', ts_sub.get('min_target_size'))
        if not measured_targets and not _is_fin(exp_t):
            fail_unverifiable(f'{pfx}: unverifiable then.min_target_px: no measured elements')
        target_px = min(measured_targets) if measured_targets else float(exp_t)
        assert_bound(key, '>=', exp, target_px)
        return True
    if key in ('obscured_focus_elements', 'fully_obscured_focus_count', 'partially_obscured_focus_count'):
        applicable = [el for el in els if isinstance(el, Mapping) and not _ui.is_element_hidden(el) and bool(el.get('focusable', True))]
        evaluated = [_ui.evaluate_focus_obscuration(el) for el in applicable]
        measured_evals = [r for r in evaluated if r['status'] == 'measured']
        fv_sub = pres_obj.get('focus_visibility') if isinstance(pres_obj.get('focus_visibility'), Mapping) else {}
        exp_f = v.get(key, fv_sub.get('partially_obscured_count' if key == 'partially_obscured_focus_count' else 'fully_obscured_count'))
        if not measured_evals and not _is_fin(exp_f):
            fail_unverifiable(f'{pfx}: unverifiable then.{key}: no measured elements')
        obscured = sum(1 for r in measured_evals if (r['partiallyObscured'] if key == 'partially_obscured_focus_count' else r['fullyObscured'])) if measured_evals else int(exp_f)
        assert_eq(key, exp, obscured)
        return True
    if key in ('unverified_elements', 'unverifiable_checks'):
        ev_sub = v.get('evidence') if isinstance(v.get('evidence'), Mapping) else {}
        raw_u = v.get('unverified_elements', v.get('unverifiable_checks', ev_sub.get('unverifiable_checks')))
        if not _is_fin(raw_u) and not els:
            fail_unverifiable(f'{pfx}: unverifiable then.{key}: empty surface view')
        assert_eq(key, exp, int(raw_u or 0))
        return True
    return False


def check_tuning_and_numeric_rel(pfx: str, key: str, exp: Mapping[str, Any], act: Any, peer_of: Any, is_num: Any, rk: frozenset[str]) -> None:
    tol = float(exp['abs_tol']) if is_num(exp.get('abs_tol')) and float(exp['abs_tol']) >= 0.0 else 1e-9
    if 'approx' in exp:
        ap = exp['approx']
        at = float(exp['abs_tol']) if 'abs_tol' in exp and is_num(exp['abs_tol']) else 0.0
        rt = float(exp['rel_tol']) if 'rel_tol' in exp and is_num(exp['rel_tol']) else 0.0
        if not is_num(act) or not is_num(ap) or ('abs_tol' not in exp and 'rel_tol' not in exp) or at < 0.0 or rt < 0.0:
            raise AssertionError(f'{pfx}: invalid approx on then.{key}')
        if abs(float(act) - float(ap)) > at + rt * abs(float(ap)):
            raise AssertionError(f'{pfx}: exp then.{key} approx {ap} (+/- {at + rt * abs(float(ap))}), got {act!r}')
    if 'balance_fields' in exp:
        bf = exp['balance_fields']
        if not isinstance(bf, Mapping): raise AssertionError(f'{pfx}: invalid balance_fields on then.{key}')
        tot = 0.0
        for sgn, k_side in ((1.0, 'add'), (-1.0, 'sub')):
            for ref in (bf.get(k_side) or ()):
                found, pv = peer_of(ref)
                if not found or not is_num(pv): raise AssertionError(f'{pfx}: missing numeric peer "{ref}" for then.{key}.balance_fields')
                tot += sgn * float(pv)
        if not is_num(act) or abs(float(act) - tot) > tol:
            raise AssertionError(f'{pfx}: exp then.{key} == balance ({tot}), got {act!r}')
    if 'monotonic' in exp or 'step_max_delta' in exp or 'sum_total' in exp:
        if isinstance(act, (list, tuple)) and ('min' in exp or 'max' in exp):
            for v in act:
                if not is_num(v) or ('min' in exp and float(v) + tol < float(exp['min'])) or ('max' in exp and float(v) - tol > float(exp['max'])):
                    raise AssertionError(f'{pfx}: sequence element {v!r} outside [min, max] on then.{key}')
    if 'monotonic' in exp:
        mode = str(exp['monotonic'])
        if not isinstance(act, (list, tuple)) or not act or not all(is_num(x) for x in act):
            raise AssertionError(f'{pfx}: exp numeric sequence for then.{key}.monotonic')
        for idx in range(1, len(act)):
            p, c = float(act[idx - 1]), float(act[idx])
            if not (p - tol <= c if mode == 'non_decreasing' else p + tol < c if mode == 'strictly_increasing' else p + tol >= c if mode == 'non_increasing' else p - tol > c if mode == 'strictly_decreasing' else False):
                raise AssertionError(f'{pfx}: monotonic={mode} violated at {idx}')
    if 'step_max_delta' in exp:
        d_raw = exp['step_max_delta']
        if not is_num(d_raw) or float(d_raw) <= 0.0 or not isinstance(act, (list, tuple)) or not act or not all(is_num(x) for x in act):
            raise AssertionError(f'{pfx}: invalid step_max_delta on then.{key}')
        if any(abs(float(act[i]) - float(act[i - 1])) > float(d_raw) + tol for i in range(1, len(act))):
            raise AssertionError(f'{pfx}: step_max_delta exceeded on then.{key}')
    if 'sum_total' in exp:
        if isinstance(act, Mapping) and act and all(k in rk for k in act):
            raise AssertionError(f'{pfx}: literal relational table cannot satisfy then.{key}.sum_total')
        vals = list(act) if isinstance(act, (list, tuple)) else (list(act.values()) if isinstance(act, Mapping) else [])
        if not vals or not all(is_num(x) for x in vals):
            raise AssertionError(f'{pfx}: invalid sequence for then.{key}.sum_total')
        tot, st = sum(float(x) for x in vals), exp['sum_total']
        if is_num(st):
            if abs(tot - float(st)) > tol: raise AssertionError(f'{pfx}: sum_total {tot}!={st}')
        elif isinstance(st, Mapping):
            if ('eq' in st and (not is_num(st['eq']) or abs(tot - float(st['eq'])) > tol)) or ('min' in st and (not is_num(st['min']) or tot + tol < float(st['min']))) or ('max' in st and (not is_num(st['max']) or tot - tol > float(st['max']))):
                raise AssertionError(f'{pfx}: sum_total {tot} outside {st!r}')
        else:
            raise AssertionError(f'{pfx}: invalid sum_total on then.{key}')


def _collect_case_key_policy(then_tbl: Mapping[str, Any], proj_tbl: Mapping[str, Any]) -> tuple[bool, set[str], set[str], set[str]]:
    allowed: set[str] = set()
    forbidden: set[str] = set()
    peers: set[str] = set()
    has_closed = False
    for exp in then_tbl.values():
        if not isinstance(exp, Mapping):
            continue
        if isinstance(exp.get('allowed_keys'), (list, tuple)):
            has_closed = True
            allowed.update(str(x) for x in exp['allowed_keys'])
        if isinstance(exp.get('forbid_keys'), (list, tuple)):
            forbidden.update(str(x) for x in exp['forbid_keys'])
        elif isinstance(exp.get('forbid_keys'), str):
            forbidden.add(exp['forbid_keys'])
        for pk in ('le_field', 'ge_field', 'eq_field'):
            if isinstance(exp.get(pk), str):
                peers.add(exp[pk].lstrip('/'))
        if isinstance(exp.get('sum_fields'), (list, tuple)):
            for sf in exp['sum_fields']:
                if isinstance(sf, str):
                    peers.add(sf.lstrip('/'))
        bf = exp.get('balance_fields')
        if isinstance(bf, Mapping):
            for side in ('add', 'sub'):
                if isinstance(bf.get(side), (list, tuple)):
                    for item in bf[side]:
                        if isinstance(item, str):
                            peers.add(item.lstrip('/'))
    if has_closed:
        allowed.update(str(k) for k in then_tbl.keys())
        allowed.update(str(k) for k in proj_tbl.keys())
        allowed.update(peers)
    return has_closed, allowed, forbidden, peers


def run_precheck_test_literals(test_files: list[str], res_dir: Any, area: Any) -> dict[str, Any]:
    import ast
    import json
    from pathlib import Path
    res_dir, area = Path(res_dir), Path(area)
    views: dict[str, Mapping[str, Any]] = {}
    known: set[str] = set()
    for d in (res_dir, area / '.drift' / 'upstream'):
        if d.is_dir():
            for jf in d.glob('*.json'):
                try:
                    v = json.loads(jf.read_text(encoding='utf-8'))
                    cid = str(v.get('id') or jf.stem)
                    views.setdefault(cid, v)
                    known.add(cid)
                except Exception:
                    pass
    c_dir = area / '.drift' / 'contracts'
    if c_dir.is_dir():
        for tf in c_dir.glob('*.toml'):
            known.add(tf.stem)
    findings: list[dict[str, str]] = []
    advisory: list[dict[str, str]] = []
    unverified = 0
    other_methods = {'expect', 'then', 'find_then', 'check_projection', 'check_view', 'check_bounds', 'check_profile_bounds', 'check_adverse', 'check_seam_bounds'}
    for rel in test_files:
        fp = Path(rel) if Path(rel).is_absolute() else (area / rel)
        if not fp.is_file():
            continue
        try:
            tree = ast.parse(fp.read_text(encoding='utf-8'))
        except Exception:
            continue
        fn_defs = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn_name = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else '')
            if fn_name != 'run_drift_case':
                continue
            kw_map = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            c_node = node.args[0] if len(node.args) >= 1 else kw_map.get('contract')
            if not (isinstance(c_node, ast.Constant) and isinstance(c_node.value, str)):
                unverified += 1
                continue
            cid = c_node.value
            if cid not in known:
                findings.append({'code': 'test.unknown_contract', 'file': rel, 'contract': cid, 'message': f'unknown contract "{cid}"'})
                continue
            view = views.get(cid)
            cases_tbl = view.get('cases') if isinstance(view, Mapping) else None
            if not isinstance(cases_tbl, Mapping):
                unverified += 1
                continue
            cs_node = node.args[2] if len(node.args) >= 3 else kw_map.get('cases')
            if isinstance(cs_node, (ast.List, ast.Tuple)):
                for elt in cs_node.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        if elt.value not in cases_tbl:
                            findings.append({'code': 'test.unknown_case', 'file': rel, 'contract': cid, 'case': elt.value, 'message': f'contract "{cid}" has no case "{elt.value}"'})
                    else:
                        unverified += 1
            elif cs_node is not None:
                unverified += 1
            cb_node = node.args[3] if len(node.args) >= 4 else kw_map.get('fn')
            target_ast = fn_defs.get(cb_node.id) if isinstance(cb_node, ast.Name) else cb_node
            if target_ast is None:
                continue
            ctx_param = ''
            if isinstance(target_ast, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)) and target_ast.args.args:
                ctx_param = target_ast.args.args[0].arg
            if not ctx_param:
                unverified += 1
                continue
            has_other = False
            checked_by_case: dict[str, set[str]] = {}
            dyn_cases: set[str] = set()
            for sub in ast.walk(target_ast):
                if not isinstance(sub, ast.Call) or not isinstance(sub.func, ast.Attribute):
                    continue
                if not (isinstance(sub.func.value, ast.Name) and sub.func.value.id == ctx_param):
                    continue
                m_name = sub.func.attr
                if m_name in other_methods:
                    has_other = True
                    continue
                if m_name != 'check':
                    continue
                if len(sub.args) < 2 or sub.keywords:
                    unverified += 1
                    continue
                ca_node, map_node = sub.args[0], sub.args[1]
                if not (isinstance(ca_node, ast.Constant) and isinstance(ca_node.value, str)):
                    unverified += 1
                    continue
                case_id = ca_node.value
                if case_id not in cases_tbl:
                    findings.append({'code': 'test.unknown_case', 'file': rel, 'contract': cid, 'case': case_id, 'message': f'contract "{cid}" has no case "{case_id}"'})
                    continue
                if not isinstance(map_node, ast.Dict) or any(k is None or not (isinstance(k, ast.Constant) and isinstance(k.value, str)) for k in map_node.keys) or len(sub.args) > 2:
                    unverified += 1
                    dyn_cases.add(case_id)
                    continue
                then_tbl = (cases_tbl.get(case_id) or {}).get('then') or {}
                proj_tbl = ((view.get('projections') or {}).get('then') or {}) if isinstance(view.get('projections'), Mapping) else {}
                has_closed, allowed_k, forbid_k, peer_k = _collect_case_key_policy(then_tbl, proj_tbl)
                seen_k = checked_by_case.setdefault(case_id, set())
                for k_node in map_node.keys:
                    assert isinstance(k_node, ast.Constant) and isinstance(k_node.value, str)
                    k_str = k_node.value
                    if k_str == '_frame':
                        continue
                    seen_k.add(k_str)
                    if k_str not in then_tbl and k_str not in proj_tbl and k_str not in peer_k:
                        if k_str in forbid_k or (has_closed and k_str not in allowed_k):
                            findings.append({'code': 'test.then_key_mismatch', 'file': rel, 'contract': cid, 'case': case_id, 'key': k_str, 'message': f'{cid}.{case_id}: unknown then.{k_str}'})
                        else:
                            advisory.append({'code': 'test.extra_check_key', 'file': rel, 'contract': cid, 'case': case_id, 'key': k_str, 'message': f'{cid}.{case_id}: extra key "{k_str}" in check literal'})
            if not has_other:
                for case_id, seen_k in checked_by_case.items():
                    if case_id in dyn_cases:
                        continue
                    then_tbl = (cases_tbl.get(case_id) or {}).get('then') or {}
                    for req_k in then_tbl:
                        if req_k not in seen_k:
                            findings.append({'code': 'test.then_key_mismatch', 'file': rel, 'contract': cid, 'case': case_id, 'key': req_k, 'message': f'{cid}.{case_id}: missing required then.{req_k}'})
    return {'ok': len(findings) == 0, 'findings': findings, 'advisory_findings': advisory, 'unverified_static': unverified}


