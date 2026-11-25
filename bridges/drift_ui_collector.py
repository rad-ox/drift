"""Three-stage live UI sequence collector for the DRIFT Python bridge."""
from __future__ import annotations

import copy
import re
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

try: from . import drift_probes as _pm
except ImportError: import drift_probes as _pm  # type: ignore[no-redef]
_ui, _uir = _pm.sib(__package__, __file__, 'drift_ui', 'drift_ui_recovery')
_map, _pick = _uir._map, _uir._pick


def collect_playwright_sequence(options: Mapping[str, Any] | None) -> dict[str, Any]:
    opts = dict(options) if isinstance(options, Mapping) else {}
    resolve_root = opts.get('resolve_root') or opts.get('resolveRoot')
    root = resolve_root() if callable(resolve_root) else opts.get('root')
    root_map: dict[str, Any] = dict(root) if isinstance(root, Mapping) else {}
    if root is None or root_map.get('surfaceFound') is False or root_map.get('surface_found') is False:
        return _ui.observe_ui_sequence({'surface_found': False, 'adapter': {'name': 'playwright-collector', 'capabilities': []}, 'evidence': {'unverifiable_checks': 1, 'unverifiable_reasons': ['surface.missing']}})
    now_fn = opts.get('now') if callable(opts.get('now')) else (lambda: time.monotonic() * 1000.0)
    before_in = _map(opts, 'before')
    def _snap(base, a, b, focus):
        out = {**base, 'input_focus_role': focus}
        for k in ('selected_entity_id', 'scroll_anchor_id'):
            if k in a or k in b: out[k] = a.get(k, b.get(k))
        for k in ('dirty_inputs', 'step_data'):
            v = a.get(k) or b.get(k)
            if isinstance(v, Mapping): out[k] = copy.deepcopy(v)
        return out
    before_snap = _snap({}, before_in, root_map, before_in.get('input_focus_role') or root_map.get('input_focus_role') or root_map.get('activeFocusRole') or '')

    focus_trace: list[str] = []
    listeners_attached = False
    listeners_detached = False
    async_requests: list[dict[str, Any]] = []
    optimistic_ops: list[dict[str, Any]] = []

    def emit_focus(role_id: str) -> None:
        if role_id:
            focus_trace.append(str(role_id))
            root_map['input_focus_role'] = str(role_id)

    class _Scope:
        def __init__(self) -> None:
            self.root = root_map
            self.emit_focus = emit_focus
            self.emitFocus = emit_focus

        @property
        def listeners_attached(self) -> bool:
            return listeners_attached

        def record_request(self, req: Mapping[str, Any]) -> None:
            async_requests.append(dict(req))

        def record_optimistic_op(self, op: Mapping[str, Any]) -> None:
            optimistic_ops.append(dict(op))

    scope = _Scope()
    t0 = float(now_fn())
    settle_timed_out = False
    listeners_attached = True
    try:
        action_fn = opts.get('action')
        if callable(action_fn):
            action_fn(scope)
        wait_until = opts.get('wait_until') or opts.get('waitUntil')
        if callable(wait_until):
            timeout_ms = float(_pick(opts, 'timeout_ms', 'timeoutMs', 1000.0))
            poll_ms = float(_pick(opts, 'poll_interval_ms', 'pollIntervalMs', 5.0))
            advance_fn = opts.get('advance_time') or opts.get('advanceTime')
            settled = bool(wait_until(scope))
            while not settled and (float(now_fn()) - t0) < timeout_ms:
                if callable(advance_fn): advance_fn(poll_ms)
                else: time.sleep(poll_ms / 1000.0)
                settled = bool(wait_until(scope))
            if not settled: settle_timed_out = True
    finally:
        listeners_attached, listeners_detached = False, True

    t1 = float(now_fn())
    obs_dur = _pick(opts, 'observed_duration_ms', 'observedDurationMs')
    observed_duration_ms = int(obs_dur) if isinstance(obs_dur, (int, float)) else max(0, round(t1 - t0))

    after_in, root_after = _map(opts, 'after'), _map(root_map, 'after')
    after_snap = _snap({**after_in, **root_after}, root_map, {}, root_map.get('input_focus_role') or after_in.get('input_focus_role') or before_snap['input_focus_role'])

    ev_in = _map(opts, 'evidence')
    unv_reasons = list(ev_in.get('unverifiable_reasons') or [])
    unv_checks = int(ev_in.get('unverifiable_checks') or 0)
    if settle_timed_out:
        unv_checks += 1; unv_reasons.append('ui.settle_timeout')

    roles_after = _map(root_map, 'roles', opts.get('roles') or {})
    elements_after = root_map.get('elements') if isinstance(root_map.get('elements'), list) else (opts.get('elements') or [])
    trans_in = _map(opts, 'transition')
    conf_ms = _pick(opts, 'configured_duration_ms', 'configuredDurationMs', root_map.get('configuredDurationMs'))

    obs = _ui.observe_ui_sequence({
        **opts,
        'roles': roles_after,
        'elements': elements_after,
        'before': before_snap,
        'action': opts.get('action_meta') or {'kind': opts.get('action_name') or 'collected_action'},
        'transition': {
            **trans_in,
            **({'configured_duration_ms': conf_ms} if conf_ms is not None else {}),
            'observed_duration_ms': None if settle_timed_out else observed_duration_ms,
            'focus_trace': focus_trace,
        },
        'after': after_snap,
        **({'async_requests': async_requests} if async_requests else {}),
        **({'optimistic_ops': optimistic_ops} if optimistic_ops else {}),
        'evidence': {
            'unverifiable_checks': unv_checks,
            'unverifiable_reasons': unv_reasons,
        },
    })
    obs['collector'] = {
        'stages_completed': ['before', 'during'] if settle_timed_out else ['before', 'during', 'after'],
        'listeners_detached': listeners_detached and not listeners_attached,
        'settle_timed_out': settle_timed_out,
    }
    return obs


collect_ui_sequence = collect_playwright_sequence

_VIEW_PLANS: dict[int, dict[str, Any]] = {}


def register_bridge_plan(view: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    if isinstance(plan, Mapping) and plan.get('schema') == 'drift.bridge-plan/1':
        _VIEW_PLANS[id(view)] = dict(plan)


def get_bridge_plan(view: Mapping[str, Any]) -> dict[str, Any] | None:
    return _VIEW_PLANS.get(id(view))


def clear_bridge_plans() -> None:
    _VIEW_PLANS.clear()


def attach_bridge_plan_file(doc: dict[str, Any], fp: Path | None, read_json_fn: Callable[[Path], Any]) -> dict[str, Any]:
    if fp is not None and isinstance(doc, dict):
        pf = fp.parent / '.plans' / f"{doc.get('id') or fp.stem}.plan.json"
        if pf.is_file():
            try:
                pl = read_json_fn(pf)
                if isinstance(pl, dict) and pl.get('digest') and pl['digest'] in (doc.get('digest'), doc.get('ref')):
                    register_bridge_plan(doc, pl)
            except Exception:
                pass
    return doc


def eval_plan_case_impl(contract_id: str, case_id: str, plan_case: Mapping[str, Any], payload: Any, seen: set[str] | None, escape_pointer: Callable[[str], str], read_pointer: Callable[[Any, str], tuple[bool, Any]], check_relational_leaf: Callable[..., bool], proj: Mapping[str, str] | None = None) -> bool:
    clauses = plan_case.get('clauses') if isinstance(plan_case, Mapping) else None
    if not isinstance(clauses, (list, tuple)):
        return False
    pfx = f'{contract_id}.{case_id}'
    for cl in clauses:
        if not isinstance(cl, Mapping) or not isinstance(cl.get('constraint'), Mapping):
            continue
        pred, ptr, conv = str(cl.get('pred') or ''), str(cl.get('pointer') or f"/{escape_pointer(str(cl.get('pred') or ''))}"), float(cl.get('conv', 1.0))
        peer_ptrs = {str(k): str(v) for k, v in (cl.get('peer_pointers') or {}).items()}
        for pk, pv in list(peer_ptrs.items()):
            if pk.startswith('then.'): peer_ptrs[pk[5:]] = pv
        when_env = {**(plan_case.get('when') or {}), **(cl.get('when_peers') or {})}
        for wk, wv in list(when_env.items()):
            if str(wk).startswith('when.'): when_env[str(wk)[5:]] = wv
        raw_c = dict(cl['constraint'])
        fake_c = {'units': {'__u->target': conv}, 'schema': {'then': {pred: {'unit': 'target'}}}} if conv != 1.0 else {}
        exp = {**raw_c, 'convert_from': '__u'} if conv != 1.0 else raw_c
        if isinstance(raw_c.get('keys'), Mapping) or 'allowed_keys' in raw_c or 'forbid_keys' in raw_c:
            if (proj is not None and pred in proj) or ptr != f'/{escape_pointer(pred)}':
                found, act = read_pointer(payload, ptr)
                if not found: raise AssertionError(f'{pfx}: missing projected path "{ptr}" for then.{pred}')
            elif isinstance(payload, Mapping) and pred in payload:
                act = payload[pred]
            else:
                act = payload
            if not isinstance(act, Mapping): raise AssertionError(f'{pfx}: expected mapping for then.{pred}')
        else:
            found, act = read_pointer(payload, ptr)
            if not found:
                raise AssertionError(f'{pfx}: missing projected path "{ptr}" for then.{pred}')
        check_relational_leaf(contract_id, case_id, pred, exp, act, payload, peer_ptrs, None, when_env, fake_c)
        if seen is not None and str(cl.get('clause') or '').startswith('then.'):
            seen.add(pred)
    return True


def build_env_dict(adapter_id, raw, strip_bom, env_keys):
    import json, os, platform, sys
    rn = 'pytest' if (os.environ.get('PYTEST_CURRENT_TEST') or re.search(r'\bpytest\b', f"{os.environ.get('DRIFT_TEST_CMD', '')} {sys.argv[0] if sys.argv else ''}", re.I)) else 'python-unittest'
    base = {'adapter': adapter_id, 'config': 'default', 'deps': 'none', 'drift': '0.11.0', 'policy': 'core@1', 'runner': rn, 'toolchain': f'python@{platform.python_version()}'}
    if raw:
        parsed = json.loads(strip_bom(raw))
        if not isinstance(parsed, dict):
            raise ValueError('DRIFT_ENV must be a JSON object')
        for k, v in parsed.items():
            if k not in env_keys or not isinstance(v, str) or not v.strip():
                raise ValueError(f'invalid DRIFT_ENV key "{k}"')
            base[k] = v.strip()
    return base


def _split_tid(t):
    s = t.strip() if isinstance(t, str) else ''
    h = s.find('#')
    return (s[:h], re.split(r'[(\[]', s[h + 1:], maxsplit=1)[0]) if h > 0 else ('', '')


def load_view_doc(contract_id, views, environ, auto_resolve_fn, attach_plan_fn, read_json_fn):
    if contract_id in views:
        return views[contract_id]
    res = environ.get('DRIFT_RESOLVED', '').strip()
    if not res:
        doc = auto_resolve_fn(contract_id)
        if doc is None:
            raise RuntimeError(f'DRIFT_RESOLVED is not set and contract "{contract_id}" could not be auto-resolved from .drift/')
        if doc.get('id') != contract_id:
            raise ValueError(f'resolved view for "{contract_id}" has id "{doc.get("id")}"')
        views[contract_id] = doc
        return doc
    fp = Path(res) if res.endswith('.json') else Path(res) / f'{contract_id}.json'
    if not res.endswith('.json'):
        synced = auto_resolve_fn(contract_id, fp.resolve())
        if isinstance(synced, dict) and synced.get('id') == contract_id:
            views[contract_id] = attach_plan_fn(synced, fp.resolve(), read_json_fn)
            return views[contract_id]
    if not fp.is_file():
        raise FileNotFoundError(f'contract "{contract_id}" was not found at {fp}')
    doc = attach_plan_fn(read_json_fn(fp), fp, read_json_fn)
    if doc.get('id') != contract_id:
        raise ValueError(f'resolved view {fp} has id "{doc.get("id")}", exp "{contract_id}"')
    views[contract_id] = doc
    return doc


def record_discovery_into(test_id, active_out, environ, discover_dir_fn, shard_path, bad_cls, bad_mth, disc_classes, disc_tests, ensure_inv_fn, flush_inv_fn, ensure_exit_fn):
    tgt = active_out or environ.get('DRIFT_EVENTS', '').strip() or discover_dir_fn()
    if not tgt:
        return
    _pm.sidecar_head(environ, (), ())
    cls, mth = _split_tid(test_id)
    if not cls or not mth or any(c.isspace() or c in bad_cls for c in cls) or any(c.isspace() or c in bad_mth for c in mth):
        raise ValueError(f'DRIFT_EVENTS requires a test id in Class#method form: "{test_id}"')
    canon = f'{cls}#{mth}'
    disc_classes.add(cls)
    disc_tests.add(canon)
    out = active_out or (str(shard_path) if shard_path is not None else (tgt if tgt.endswith('.jsonl') and Path(tgt).is_file() else ''))
    if not out:
        return
    inv = ensure_inv_fn(out)
    before = len(inv['classes']) + len(inv['tests'])
    inv['classes'].add(cls)
    inv['tests'].add(canon)
    if before == len(inv['classes']) + len(inv['tests']) and inv['flushed'] and not inv['dirty']:
        return
    inv['dirty'] = True
    ensure_exit_fn()
    if active_out:
        flush_inv_fn(out, inv)


def record_context_input(ctx, fp, pre, input_digest_fn, resolve_events_fn, record_disc_fn, invs):
    import os
    is_self = isinstance(pre, str)
    cwd = Path(os.path.normpath(os.getcwd()))
    abs_p = Path(fp) if is_self else Path(os.path.normpath(cwd / fp))
    try:
        rel = str(fp) if is_self else abs_p.relative_to(cwd).as_posix()
    except ValueError:
        rel = Path(fp).as_posix()
    dig = pre if is_self else input_digest_fn(abs_p, pre)
    if ctx.mutation_override is None:
        if is_self and rel == f'.drift/self-stub/{ctx.contract_id}':
            ctx._self_stub = True
        elif not is_self:
            ctx._input_files[abs_p] = (rel, dig)
        out = resolve_events_fn()
        if out:
            record_disc_fn(ctx.test_id, out)
            inv = invs.get(out)
            if inv is not None:
                cls, mth = _split_tid(ctx.test_id)
                canon = f'{cls}#{mth}' if cls and mth else ctx.test_id
                fm = inv['inputs'].setdefault(canon, {})
                if fm.get(rel) != dig:
                    fm[rel] = dig
                    inv['dirty'] = True
    return dig


def verify_recorded_inputs(contract, test, input_files, digests, hash_bytes_fn):
    for abs_p, (rel, dig) in input_files.items():
        if not abs_p.is_file():
            raise AssertionError(f'{contract}: recorded input "{rel}" was mutated during test "{test}"')
        st = abs_p.stat()
        ok = (digests.get(str(abs_p), (None, '')) == ((st.st_mtime_ns, st.st_size), dig)) if st.st_size > 65536 else (hash_bytes_fn(abs_p.read_bytes()) == dig)
        if not ok:
            raise AssertionError(f'{contract}: recorded input "{rel}" was mutated during test "{test}"')

