"""Projection, relational domain, and UI view checks for the DRIFT Python bridge."""
from __future__ import annotations

import importlib.util
import json
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

try:
    from . import drift_upstream as _up, drift_security as _sec, drift_ui as _ui, drift_ui_surface as _uis, drift_ui_recovery as _ce, drift_ui_collector as _uic
except ImportError:
    try:
        import drift_upstream as _up, drift_security as _sec, drift_ui as _ui, drift_ui_surface as _uis, drift_ui_recovery as _ce, drift_ui_collector as _uic  # type: ignore[no-redef]
    except ImportError:
        def _ld(n: str) -> Any:
            s = importlib.util.spec_from_file_location(n, Path(__file__).with_name(f'{n}.py'))
            assert s is not None and s.loader is not None
            m = importlib.util.module_from_spec(s)
            s.loader.exec_module(m)
            return m
        _up, _sec, _ui, _uis = _ld('drift_upstream'), _ld('drift_security'), _ld('drift_ui'), _ld('drift_ui_surface')
        _ce, _uic = _ld('drift_ui_recovery'), _ld('drift_ui_collector')

REL_KEYS = frozenset(('min', 'max', 'min_len', 'max_len', 'non_empty', 'le_field', 'ge_field', 'eq_field', 'in', 'not_in', 'sum_fields', 'contains', 'prefix', 'suffix', 'allowed_keys', 'forbid_keys', 'monotonic', 'sum_total', 'step_max_delta', 'approx', 'abs_tol', 'rel_tol', 'balance_fields', 'unit', 'unit_conversion', 'eq', 'len', 'keys', 'peer', 'series', 'tol', 'convert_from'))
CAPS_03 = ('rel-keys-guard/1', 'rel-linear-balance/1', 'rel-peer-sum/1', 'rel-series/1', 'rel-tol/1', 'unit-conversion/1')


desugar_03_rel = _ce.desugar_03_rel
NON_VERIFIED_OP_STATES = frozenset(('prepared', 'accepted', 'queued', 'running', 'in_progress', 'partial_failure', 'cancellation_requested', 'unknown'))
TERMINAL_UI_CLAIMS = frozenset(('completed', 'complete', 'verified', 'done', 'fulfilled', 'available', 'sent', 'paid', 'approved'))
COMPARATIVE_BASELINE_RE = re.compile(r'^(?:invariato|unchanged|same|nessuna variazione|[+-]\s*\d)')
escape_pointer = _up._cli.escape_pointer
unescape_pointer = _up._cli.unescape_pointer
is_array_index = _up._cli.is_array_index
is_finite_num = _up._cli.is_finite_num
values_mismatch = _up._cli.values_mismatch
read_pointer = _up.read_pointer
clone_json = _up.clone_json
write_pointer = _up.write_pointer
parse_mutation_segments = _up._cli.parse_mutation_segments
apply_mutation = _up._cli.apply_mutation
resolve_selected_files = _up._cli.resolve_selected_files
parse_selection_doc = _up._cli.parse_selection_doc
parse_mutation_manifest_doc = _up._cli.parse_mutation_manifest_doc
resolve_param_spec = _up._cli.resolve_param_spec
extract_projection_map = _up._cli.extract_projection_map


def invoke_verified_callback(fn: Callable[..., Any], contract_id: str, case_id: str, k: str, exp: Any, *extra: Any) -> None:
    import dis
    code = getattr(fn, '__code__', None)
    ops = [i.opname for i in dis.get_instructions(code)] if code is not None else ['LOAD_FAST', 'CALL']
    if not any(op.startswith(('LOAD_FAST', 'LOAD_DEREF')) for op in ops):
        raise AssertionError(f'{contract_id}.{case_id}: check for then.{k} must inspect the expected value')
    res = fn(exp, *extra)
    if res is False:
        raise AssertionError(f'{contract_id}.{case_id}: check for then.{k} returned False')
    if res is not True and not any(op.startswith(('RAISE_VARARGS', 'CALL', 'COMPARE_OP', 'CONTAINS_OP', 'IS_OP')) for op in ops):
        raise AssertionError(f'{contract_id}.{case_id}: check for then.{k} must inspect and assert the expected value')


def run_simple_checks(contract_id: str, case_id: str, then_table: Mapping[str, Any], seen: set[str], checks: Mapping[str, Any], when_env: Mapping[str, Any] | None = None) -> None:
    src = checks.get('then') if isinstance(checks, Mapping) and isinstance(checks.get('then'), Mapping) and not any(k in checks for k in then_table) else checks
    for k, exp in then_table.items():
        if not isinstance(src, Mapping) or k not in src:
            raise AssertionError(f'{contract_id}.{case_id}: no check for then.{k}')
        fn = src[k]
        if callable(fn):
            invoke_verified_callback(fn, contract_id, case_id, k, _uis.unwrap_03_eq(exp))
        elif not check_relational_leaf(contract_id, case_id, k, exp, fn, checks, {}, None, when_env) and values_mismatch(fn, exp):
            raise AssertionError(f'{contract_id}.{case_id}: expected then.{k}={exp!r}, got {fn!r}')
        seen.add(k)


def build_projected_input(view: Mapping[str, Any], when_table: Mapping[str, Any], base: Mapping[str, Any] | None = None) -> Any:
    when_proj = extract_projection_map(view, 'when')
    out = clone_json(base if isinstance(base, Mapping) else {})
    for k, raw_v in when_table.items():
        v = _uis.unwrap_03_eq(raw_v)
        if k in when_proj:
            out = write_pointer(out, when_proj[k], v)
        elif isinstance(out, dict):
            out[k] = clone_json(v)
    return out


def run_domain_bounds_check(contract_id: str, case_id: str, then_table: Mapping[str, Any], seen: set[str], domain: Any, checks: Mapping[str, Callable[[Any, Any], Any]], is_mut: bool) -> None:
    _ = is_mut
    samples = expand_domain(domain, False)
    b_checks: list[tuple[str, Any, Callable[[Any, Any], Any]]] = []
    for k, exp in then_table.items():
        fn = checks.get(k) if isinstance(checks, Mapping) else None
        if not callable(fn):
            raise AssertionError(f'{contract_id}.{case_id}: no check for then.{k}')
        b_checks.append((k, _uis.unwrap_03_eq(exp), fn))
    for s in samples:
        for k, exp, fn in b_checks:
            try:
                invoke_verified_callback(fn, contract_id, case_id, k, exp, s)
            except AssertionError as exc:
                if '[counterexample:' not in str(exc):
                    ce = json.dumps(s, separators=(',', ':'), sort_keys=True)
                    raise AssertionError(f'{contract_id}.{case_id}.then.{k} failed [counterexample: {ce}]: {exc}') from exc
                raise
    for k, _, _ in b_checks:
        seen.add(k)


def expand_single_domain(spec: Any, first: bool = False) -> list[Any] | None:
    if isinstance(spec, (list, tuple)):
        if not spec: raise ValueError('domain sample sequence must not be empty')
        return [spec[0]] if first else list(spec)
    if not isinstance(spec, Mapping): raise ValueError('domain specification must be a sequence or mapping')
    dt = spec.get('type')
    if dt == 'int':
        lo, hi = spec.get('min'), spec.get('max')
        if isinstance(lo, bool) or isinstance(hi, bool) or not isinstance(lo, int) or not isinstance(hi, int) or lo > hi: raise ValueError(f'invalid int domain [{lo}, {hi}]')
        return [0 if lo < 0 < hi else lo] if first else list(dict.fromkeys(([0] if lo < 0 < hi else []) + [lo, min(hi, lo + 1), int((lo + hi) / 2), max(lo, hi - 1), hi]))
    if dt == 'string' and isinstance(spec.get('enum'), (list, tuple)) and spec['enum']:
        return [str(spec['enum'][0])] if first else list(dict.fromkeys(str(v) for v in spec['enum']))
    return ([False] if first else [False, True]) if dt == 'bool' else None


def expand_domain(domain: Any, first: bool = False) -> list[Any]:
    single = expand_single_domain(domain, first)
    if single is not None: return single
    if not isinstance(domain, Mapping) or not domain: raise ValueError('Cartesian domain mapping must not be empty')
    keys = sorted(domain.keys())
    d, vals_by_key = len(keys), []
    for key in keys:
        vals = expand_single_domain(domain[key], first)
        if vals is None: raise ValueError(f'invalid domain specification for key "{key}"')
        vals_by_key.append(vals)
    cur = {keys[i]: vals_by_key[i][0] for i in range(d)}
    if first: return [cur]
    prod = 1
    for v in vals_by_key:
        prod *= len(v)
        if prod > 16: break
    max_exc, out = (d if prod <= 16 else (2 if d >= 3 else d)), []
    def dfs(pos: int, exc: int) -> None:
        if pos == d or exc >= max_exc: out.append(dict(cur)); return
        dfs(pos + 1, exc)
        for idx in range(1, len(vals_by_key[pos])):
            cur[keys[pos]] = vals_by_key[pos][idx]; dfs(pos + 1, exc + 1)
        cur[keys[pos]] = vals_by_key[pos][0]
    dfs(0, 0)
    return out


ThenView = _sec.ThenView


register_bridge_plan = _uic.register_bridge_plan
get_bridge_plan = _uic.get_bridge_plan
clear_bridge_plans = _uic.clear_bridge_plans
attach_bridge_plan_file = _uic.attach_bridge_plan_file


def eval_compiled_plan_case(contract_id: str, case_id: str, plan_case: Mapping[str, Any], payload: Any, seen: set[str] | None = None) -> bool:
    return _uic.eval_plan_case_impl(contract_id, case_id, plan_case, payload, seen, escape_pointer, read_pointer, check_relational_leaf)


def check_relational_leaf(contract_id: str, case_id: str, key: str, raw_exp: Any, act: Any, payload: Any, proj: Mapping[str, str], mutation_override: Mapping[str, Any] | None, when_env: Mapping[str, Any] | None = None, contract: Mapping[str, Any] | None = None) -> bool:
    if not isinstance(raw_exp, Mapping) or not raw_exp or not all(rk in REL_KEYS for rk in raw_exp):
        return False
    context = contract if contract is not None else (payload if isinstance(payload, Mapping) else {})
    exp = desugar_03_rel(raw_exp, context.get('units', {}), context.get('schema', {}).get('then', {}).get(key, {}).get('unit'))
    pfx = f'{contract_id}.{case_id}'
    if 'eq' in exp:
        if values_mismatch(act, exp['eq']):
            raise AssertionError(f"{pfx}: exp then.{key}={exp['eq']!r}, got {act!r}")
        if len(exp) == 1:
            return True
    is_num = is_finite_num
    act_len = len(act) if isinstance(act, (str, list, tuple, Mapping)) else -1
    peer_of = lambda ref: _uis.resolve_peer_value(ref, payload, proj, when_env, read_pointer)

    is_seq_tuning = 'monotonic' in exp or 'step_max_delta' in exp or 'sum_total' in exp
    if not is_seq_tuning:
        if 'min' in exp and (not is_num(act) or not is_num(exp['min']) or float(act) + 1e-9 < float(exp['min'])):
            raise AssertionError(f"{pfx}: exp then.{key}>={exp['min']}, got {act!r}")
        if 'max' in exp and (not is_num(act) or not is_num(exp['max']) or float(act) - 1e-9 > float(exp['max'])):
            raise AssertionError(f"{pfx}: exp then.{key}<={exp['max']}, got {act!r}")
    if 'min_len' in exp and (act_len < 0 or act_len < int(exp['min_len'])):
        raise AssertionError(f"{pfx}: exp len(then.{key})>={exp['min_len']}, got {act_len}")
    if 'max_len' in exp and (act_len < 0 or act_len > int(exp['max_len'])):
        raise AssertionError(f"{pfx}: exp len(then.{key})<={exp['max_len']}, got {act_len}")
    if 'non_empty' in exp and (act_len < 0 or (act_len <= 0 if exp['non_empty'] else act_len != 0)):
        raise AssertionError(f"{pfx}: exp then.{key}.non_empty={exp['non_empty']}, got len={act_len}")
    for fk, op in (('le_field', '<='), ('ge_field', '>='), ('eq_field', '==')):
        if fk not in exp:
            continue
        found, pv = peer_of(exp[fk])
        if not found:
            raise AssertionError(f'{pfx}: missing peer "{exp[fk]}" for then.{key}.{fk}')
        if op == '==':
            ok = not values_mismatch(act, pv)
        else:
            ok = is_num(act) and is_num(pv) and (float(act) - 1e-9 <= float(pv) if op == '<=' else float(act) + 1e-9 >= float(pv))
        if not ok:
            raise AssertionError(f'{pfx}: exp then.{key} {op} {exp[fk]} ({pv!r}), got {act!r}')
    if 'in' in exp and (not isinstance(exp['in'], (list, tuple)) or not any(not values_mismatch(act, x) for x in exp['in'])):
        raise AssertionError(f"{pfx}: exp then.{key} in {exp['in']!r}, got {act!r}")
    if 'not_in' in exp:
        if act is None:
            raise AssertionError(f'{pfx}: exp non-null value for then.{key}.not_in')
        if isinstance(exp['not_in'], (list, tuple)):
            if any(not values_mismatch(act, x) for x in exp['not_in']):
                raise AssertionError(f"{pfx}: forbidden value {act!r} in then.{key}.not_in {exp['not_in']!r}")
        elif values_mismatch(act, exp['not_in']):
            raise AssertionError(f'{pfx}: pick-forbidden-value mutant on then.{key}.not_in killed (got {act!r})')
    if 'allowed_keys' in exp:
        if not isinstance(act, Mapping) or not isinstance(exp['allowed_keys'], (list, tuple)):
            raise AssertionError(f'{pfx}: expected mapping and allowed_keys list for then.{key}')
        for k in act:
            if act is payload and k == '_frame' and isinstance(act[k], Mapping):
                continue
            if k not in exp['allowed_keys']:
                raise AssertionError(f'{pfx}: unexpected key "{k}" on then.{key}')
    if 'forbid_keys' in exp:
        if not isinstance(act, Mapping):
            raise AssertionError(f'{pfx}: exp mapping for then.{key}.forbid_keys')
        if isinstance(exp['forbid_keys'], (list, tuple)):
            for fk in exp['forbid_keys']:
                if _sec.has_key_recursive(act, str(fk), act is payload):
                    raise AssertionError(f'{pfx}: forbidden key "{fk}" present on then.{key}')
        elif not _sec.has_key_recursive(act, str(exp['forbid_keys']), act is payload):
            raise AssertionError(f'{pfx}: drop-forbid-key mutant killed on then.{key}.forbid_keys')
    if 'sum_fields' in exp:
        if not isinstance(exp['sum_fields'], (list, tuple)) or len(exp['sum_fields']) < 2:
            raise AssertionError(f'{pfx}: invalid sum_fields on then.{key}')
        total = 0.0
        for ref in exp['sum_fields']:
            found, pv = peer_of(ref)
            if not found or not is_num(pv):
                raise AssertionError(f'{pfx}: missing numeric peer "{ref}" for then.{key}.sum_fields')
            total += float(pv)
        if not is_num(act) or not is_num(total) or abs(float(act) - total) > 1e-9:
            raise AssertionError(f'{pfx}: exp then.{key} == sum({exp["sum_fields"]!r}) ({total}), got {act!r}')
    if 'contains' in exp:
        reqs = exp['contains'] if isinstance(exp['contains'], (list, tuple)) else [exp['contains']]
        ok = all(isinstance(req, str) and req in act for req in reqs) if isinstance(act, str) else isinstance(act, (list, tuple)) and all(any(not values_mismatch(x, req) for x in act) for req in reqs)
        if not ok:
            raise AssertionError(f"{pfx}: exp then.{key} to contain {exp['contains']!r}, got {act!r}")
    if 'prefix' in exp and (not isinstance(act, str) or not act.startswith(str(exp['prefix']))):
        raise AssertionError(f"{pfx}: exp then.{key} to start with {exp['prefix']!r}, got {act!r}")
    if 'suffix' in exp and (not isinstance(act, str) or not act.endswith(str(exp['suffix']))):
        raise AssertionError(f"{pfx}: exp then.{key} to end with {exp['suffix']!r}, got {act!r}")
    _uis.check_tuning_and_numeric_rel(pfx, key, exp, act, peer_of, is_num, REL_KEYS)
    return True


def check_projected_leaf(contract_id: str, case_id: str, key: str, exp: Any, payload: Any, proj: Mapping[str, str], mutation_override: Mapping[str, Any] | None, with_at: bool, miss_msg: str, when_env: Mapping[str, Any] | None = None, contract: Mapping[str, Any] | None = None) -> None:
    pfx = f'{contract_id}.{case_id}'
    is_ui = isinstance(payload, Mapping) and (payload.get('schema') == 'drift.ui-observation/1' or isinstance(payload.get('evidence'), Mapping))
    t_pay = payload.get('then') if isinstance(payload, Mapping) and isinstance(payload.get('then'), Mapping) and key not in payload else payload
    def bump() -> None:
        ev = payload.get('evidence') if isinstance(payload, Mapping) else None
        if isinstance(ev, dict) and isinstance(ev.get('unverifiable_checks'), int):
            ev['unverifiable_checks'] += 1
            if isinstance(ev.get('unverifiable_reasons'), list): ev['unverifiable_reasons'].append(f'unverifiable_then:{key}')
    if key in proj:
        ptr = proj[key]
        found, act = read_pointer(t_pay, ptr)
        if not found and t_pay is not payload: found, act = read_pointer(payload, ptr)
        if not found: bump(); raise AssertionError(f'{pfx}: missing projected path "{ptr}" for then.{key}')
        if is_ui and exp is not None and (act is None or (act == '' and isinstance(exp, str) and exp != '')): bump(); raise AssertionError(f'{pfx}: unverifiable then.{key}: unmeasured value at "{ptr}"')
        if check_relational_leaf(contract_id, case_id, key, exp, act, payload, proj, mutation_override, when_env, contract): return
        if values_mismatch(act, exp): raise AssertionError(f'{pfx}: exp then.{key}={exp!r}{f" at \"{ptr}\"" if with_at else ""}, got {act!r}')
        return
    if isinstance(t_pay, Mapping) and key in t_pay:
        if is_ui and exp is not None and t_pay[key] is None: bump(); raise AssertionError(f'{pfx}: unverifiable then.{key}: unmeasured value')
        if check_relational_leaf(contract_id, case_id, key, exp, t_pay[key], payload, proj, mutation_override, when_env, contract): return
        if values_mismatch(t_pay[key], exp): raise AssertionError(f'{pfx}: exp then.{key}={exp!r}, got {t_pay[key]!r}')
        return
    bump(); raise AssertionError(f'{pfx}: {miss_msg} then.{key}')


def _unobserved_controls(controls: Any, then_table: Mapping[str, Any], proj: Mapping[str, str] | None) -> list[str]:
    if not isinstance(controls, Mapping) or not controls: return []
    ctrls = sorted(controls.keys())
    cset, obs = set(ctrls), set()
    for tk in then_table:
        if tk == 'unobserved_controls': continue
        if tk in cset: obs.add(tk)
        for seg in (proj.get(tk, '') if isinstance(proj, Mapping) else '').split('/'):
            if seg in cset: obs.add(seg)
    return [c for c in ctrls if c not in obs]


def check_view_table(contract_id: str, case_id: str, then_table: Mapping[str, Any], seen: set[str], view: Any, checks: Mapping[str, Callable[[Any], Any]] | None, mutation_override: Mapping[str, Any] | None, metrics_store: dict[str, dict[str, Any]], proj_loader: Callable[[], Mapping[str, str]], when_env: Mapping[str, Any] | None = None) -> None:
    v = dict(view) if isinstance(view, Mapping) else {}
    pfx = f'{contract_id}.{case_id}'
    is_mut = mutation_override is not None
    proj: Mapping[str, str] | None = None

    if (
        v.get('surfaceFound') is False
        or v.get('surface_found') is False
        or (v.get('schema') == 'drift.ui-observation/1' and v.get('surface_found') is not True and v.get('surfaceFound') is not True)
    ):
        raise AssertionError(f'{pfx}: surface.missing')

    def assert_eq(key: str, exp: Any, act: Any) -> None:
        if act != exp:
            raise AssertionError(f'{pfx}: exp {key}={exp}, got {act}')

    def assert_bound(key: str, op: str, exp: Any, act: float) -> None:
        if not is_finite_num(exp) or not is_finite_num(act):
            raise AssertionError(f'{pfx}: exp {key}{op}{exp}, got {act}')
        target = float(exp)
        failed = act > target if op == '<=' else act < target
        if failed:
            raise AssertionError(f'{pfx}: exp {key}{op}{exp}, got {act}')

    state_first = {'baseline_state', 'duplicate_figures', 'single_metric_source', 'preserved_input_on_error', 'claim_matches_evidence'}
    unverif_last = {'unverifiable_checks', 'unverified_elements'}
    ordered_items = [
        *(item for item in then_table.items() if item[0] in state_first),
        *(item for item in then_table.items() if item[0] not in state_first and item[0] not in unverif_last),
        *(item for item in then_table.items() if item[0] in unverif_last),
    ]
    for key, raw_exp in ordered_items:
        exp = _uis.unwrap_03_eq(raw_exp)
        if isinstance(checks, Mapping) and callable(checks.get(key)):
            invoke_verified_callback(checks[key], contract_id, case_id, key, exp)
            seen.add(key)
            continue
        if isinstance(v.get('adapter'), Mapping) and proj is None:
            proj = proj_loader()
        if _uis.check_surface_key(contract_id, case_id, key, exp, v, then_table, proj, mutation_override, check_relational_leaf):
            seen.add(key)
            continue
        if key == 'baseline_state':
            has_b = bool(v.get('hasBaseline') if 'hasBaseline' in v else v.get('baseline') is not None)
            lbl = str(v.get('baselineLabel') or v.get('deltaLabel') or '').strip().lower()
            if not has_b and COMPARATIVE_BASELINE_RE.match(lbl):
                raise AssertionError(f'{pfx}: comparative baseline label "{lbl}" without baseline')
            act = v.get('baseline_state') or ('compared' if has_b else 'first_observation')
            if act != exp:
                raise AssertionError(f'{pfx}: exp baseline_state={exp!r}, got {act!r}')
        elif key == 'duplicate_figures':
            if isinstance(v.get('figures'), list):
                figs = [str(f) for f in v['figures']]
            elif isinstance(v.get('metrics'), list):
                figs = [f"{m.get('label') or m.get('metric') or ''}:{m.get('value')}" for m in v['metrics']]
            else:
                figs = []
            assert_eq(key, exp, len(figs) - len(set(figs)))
        elif key == 'single_metric_source':
            conflict = False
            local_seen: dict[str, dict[str, Any]] = {}
            for m in v.get('metrics') or ():
                mk = f"{m.get('entity') or v.get('entity') or 'default'}\x00{m.get('metric') or m.get('name') or ''}"
                entry = {'value': m.get('value'), 'source': str(m.get('source') or '')}
                prev = local_seen.get(mk) or metrics_store.get(mk)
                if prev is not None and (prev['value'] != entry['value'] or (prev['source'] and entry['source'] and prev['source'] != entry['source'])):
                    conflict = True
                local_seen[mk] = entry
                if not is_mut:
                    metrics_store[mk] = entry
            assert_eq(key, exp, not conflict)
        elif key == 'preserved_input_on_error':
            act_preserved = bool(v.get('preserved_input_on_error', True))
            dirty = v.get('dirtyInputs')
            if bool(v.get('error') or v.get('hasError')) and isinstance(dirty, Mapping):
                cur_raw = v.get('currentInputs') if isinstance(v.get('currentInputs'), Mapping) else v.get('inputs')
                cur = cur_raw if isinstance(cur_raw, Mapping) else {}
                act_preserved = all(cur.get(ik) == iv for ik, iv in dirty.items())
            assert_eq(key, exp, act_preserved)
        elif key == 'claim_matches_evidence':
            op_state = str(v.get('operationState') or v.get('evidenceState') or '').strip().lower()
            ui_claim = str(v.get('uiClaim') or v.get('statusLabel') or v.get('completionState') or '').strip().lower()
            claimed_done = bool(v.get('claimedComplete') is True) or ui_claim in TERMINAL_UI_CLAIMS
            act_claim = False if (op_state in NON_VERIFIED_OP_STATES and claimed_done) else bool(v.get('claim_matches_evidence', True))
            assert_eq(key, exp, act_claim)
        elif key == 'unobserved_controls':
            if proj is None:
                proj = proj_loader()
            unobs = _unobserved_controls(v.get('controls'), then_table, proj)
            if isinstance(view, dict):
                view['unobservedControls'] = unobs
            act_unobs: Any = unobs if isinstance(exp, list) else len(unobs)
            if values_mismatch(act_unobs, exp):
                raise AssertionError(f'{pfx}: exp unobserved_controls={exp!r}, got {act_unobs!r} ({unobs!r})')
        else:
            if proj is None:
                proj = proj_loader()
            check_projected_leaf(contract_id, case_id, key, exp, v, proj, mutation_override, False, 'no check for', when_env)
        seen.add(key)
    if isinstance(v.get('controls'), Mapping) and isinstance(view, dict) and not isinstance(view.get('unobservedControls'), list):
        if proj is None:
            proj = proj_loader()
        view['unobservedControls'] = _unobserved_controls(v.get('controls'), then_table, proj)


def build_projected_output(view: Mapping[str, Any], case_id: str, base: Mapping[str, Any] | None = None, then_map: Mapping[str, Any] | None = None) -> Any:
    pc = ((get_bridge_plan(view) or {}).get('cases') or {}).get(case_id)
    rt = ((view.get('cases') or {}).get(case_id) or {}).get('then')
    if isinstance(pc, Mapping) and 'stub_output' in pc and not base and (then_map is None or then_map == rt or then_map == _ce.converted_table(view, 'then', rt or {})):
        return clone_json(pc['stub_output'])
    return _up.synthesize_view_output(view, case_id, base, then_map, extract_projection_map, write_pointer, clone_json, REL_KEYS)


def build_projected_variants(view: Mapping[str, Any], case_id: str, base: Mapping[str, Any] | None = None) -> list[Any]:
    pc = ((get_bridge_plan(view) or {}).get('cases') or {}).get(case_id)
    if isinstance(pc, Mapping) and isinstance(pc.get('stub_variants'), list) and pc['stub_variants'] and not base:
        return [clone_json(x) for x in pc['stub_variants']]
    return _up.synthesize_view_variants(view, case_id, base, extract_projection_map, write_pointer, clone_json, REL_KEYS)


resolve_stub_case_id = lambda v, i, c, b=None: _up.resolve_stub_case_id(v, i, c, b, extract_projection_map, write_pointer, clone_json, REL_KEYS)
find_upstream_contract = _up.find_upstream_contract
auto_resolve_contract = lambda cid, b, td, w, cs, rj, sb, tj=None: _up._cli.auto_resolve_contract(cid, b, td, w, cs, rj, sb, find_upstream_contract, tj)
run_drift_cli = lambda argv: _up._cli.run_drift_cli_runner(argv, resolve_selected_files)
sidecar_head = _sec.sidecar_head
merge_prior_inventory = lambda out, inv, sh, rd: _sec.merge_prior_inventory(out, inv, sh, rd, resolve_selected_files)
run_adverse_checks = lambda ctx, cid, h, ch=None: _sec.run_adverse_checks(ctx, cid, h, ch, escape_pointer, read_pointer, values_mismatch, invoke_verified_callback, check_projected_leaf)


def clear_upstream_cache() -> None:
    clear_bridge_plans(); _up.clear_upstream_cache()


def run_projection_checks(ctx: Any, case_id: str, payload: Any, checks: Mapping[str, Callable[[Any], Any]] | None = None, when_obs: Mapping[str, Any] | None = None) -> None:
    ctx._require_tagged(case_id)
    has_cb = isinstance(checks, Mapping) and any(k not in ('frame', 'strictFrame') and callable(v) for k, v in checks.items())
    is_ui = isinstance(payload, Mapping) and (payload.get('schema') == 'drift.ui-observation/1' or isinstance(payload.get('evidence'), Mapping))
    pc = ((get_bridge_plan(ctx.view) or {}).get('cases') or {}).get(case_id) if getattr(ctx, 'mutation_override', None) is None and not has_cb and when_obs is None and not is_ui else None
    if isinstance(pc, Mapping) and eval_compiled_plan_case(ctx.contract_id, case_id, pc, payload, ctx.reads[case_id]):
        fo = checks.get('frame') if isinstance(checks, Mapping) and isinstance(checks.get('frame'), Mapping) else (payload.get('_frame') if isinstance(payload, Mapping) and _sec.is_frame_metadata_envelope(payload.get('_frame')) else None)
        if fo is not None: _sec.verify_case_frame(ctx, case_id, fo, values_mismatch, bool(isinstance(checks, Mapping) and checks.get('strictFrame') is True) or not any(isinstance(v, Mapping) and v.get('observed') is False for v in fo.values()))
        return
    _sec.run_projection_checks(ctx, case_id, payload, checks, invoke_verified_callback, check_projected_leaf, read_pointer, when_obs)

