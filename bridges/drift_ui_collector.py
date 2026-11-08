"""Three-stage live UI sequence collector for the DRIFT Python bridge."""
from __future__ import annotations

import copy
import importlib.util
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

try:
    from . import drift_ui as _ui
    from . import drift_ui_recovery as _uir
except ImportError:
    try:
        import drift_ui as _ui  # type: ignore[no-redef]
        import drift_ui_recovery as _uir  # type: ignore[no-redef]
    except ImportError:
        _ui_spec = importlib.util.spec_from_file_location('drift_ui', Path(__file__).with_name('drift_ui.py'))
        assert _ui_spec is not None and _ui_spec.loader is not None
        _ui = importlib.util.module_from_spec(_ui_spec)
        _ui_spec.loader.exec_module(_ui)
        _uir_spec = importlib.util.spec_from_file_location('drift_ui_recovery', Path(__file__).with_name('drift_ui_recovery.py'))
        assert _uir_spec is not None and _uir_spec.loader is not None
        _uir = importlib.util.module_from_spec(_uir_spec)
        _uir_spec.loader.exec_module(_uir)


def collect_playwright_sequence(options: Mapping[str, Any] | None) -> dict[str, Any]:
    opts = dict(options) if isinstance(options, Mapping) else {}
    resolve_root = opts.get('resolve_root') or opts.get('resolveRoot')
    root = resolve_root() if callable(resolve_root) else opts.get('root')
    if not isinstance(root, Mapping) and root is None:
        return _ui.observe_ui_sequence({
            'surface_found': False,
            'adapter': {'name': 'playwright-collector', 'capabilities': []},
            'evidence': {'unverifiable_checks': 1, 'unverifiable_reasons': ['surface.missing']},
        })
    root_map: dict[str, Any] = dict(root) if isinstance(root, Mapping) else {}
    if root_map.get('surfaceFound') is False or root_map.get('surface_found') is False:
        return _ui.observe_ui_sequence({
            'surface_found': False,
            'adapter': {'name': 'playwright-collector', 'capabilities': []},
            'evidence': {'unverifiable_checks': 1, 'unverifiable_reasons': ['surface.missing']},
        })

    now_fn = opts.get('now') if callable(opts.get('now')) else (lambda: time.monotonic() * 1000.0)
    before_in = opts.get('before') if isinstance(opts.get('before'), Mapping) else {}
    before_snap: dict[str, Any] = {
        'input_focus_role': before_in.get('input_focus_role') or root_map.get('input_focus_role') or root_map.get('activeFocusRole') or '',
        **(
            {'selected_entity_id': before_in.get('selected_entity_id', root_map.get('selected_entity_id'))}
            if ('selected_entity_id' in before_in or 'selected_entity_id' in root_map)
            else {}
        ),
        **(
            {'scroll_anchor_id': before_in.get('scroll_anchor_id', root_map.get('scroll_anchor_id'))}
            if ('scroll_anchor_id' in before_in or 'scroll_anchor_id' in root_map)
            else {}
        ),
        **(
            {'dirty_inputs': copy.deepcopy(before_in.get('dirty_inputs') or root_map.get('dirty_inputs'))}
            if isinstance(before_in.get('dirty_inputs') or root_map.get('dirty_inputs'), Mapping)
            else {}
        ),
        **(
            {'step_data': copy.deepcopy(before_in.get('step_data') or root_map.get('step_data'))}
            if isinstance(before_in.get('step_data') or root_map.get('step_data'), Mapping)
            else {}
        ),
    }

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
            timeout_ms = float(opts.get('timeout_ms', opts.get('timeoutMs', 1000.0)))
            poll_ms = float(opts.get('poll_interval_ms', opts.get('pollIntervalMs', 5.0)))
            advance_fn = opts.get('advance_time') or opts.get('advanceTime')
            settled = bool(wait_until(scope))
            while not settled and (float(now_fn()) - t0) < timeout_ms:
                if callable(advance_fn):
                    advance_fn(poll_ms)
                else:
                    time.sleep(poll_ms / 1000.0)
                settled = bool(wait_until(scope))
            if not settled:
                settle_timed_out = True
    finally:
        listeners_attached = False
        listeners_detached = True

    t1 = float(now_fn())
    obs_dur = opts.get('observed_duration_ms', opts.get('observedDurationMs'))
    observed_duration_ms = int(obs_dur) if isinstance(obs_dur, (int, float)) else max(0, round(t1 - t0))

    after_in = opts.get('after') if isinstance(opts.get('after'), Mapping) else {}
    root_after = root_map.get('after') if isinstance(root_map.get('after'), Mapping) else {}
    after_snap: dict[str, Any] = {
        **after_in,
        **root_after,
        'input_focus_role': root_map.get('input_focus_role') or after_in.get('input_focus_role') or before_snap['input_focus_role'],
        **({'selected_entity_id': root_map['selected_entity_id']} if 'selected_entity_id' in root_map else {}),
        **({'scroll_anchor_id': root_map['scroll_anchor_id']} if 'scroll_anchor_id' in root_map else {}),
        **({'dirty_inputs': copy.deepcopy(root_map['dirty_inputs'])} if isinstance(root_map.get('dirty_inputs'), Mapping) else {}),
        **({'step_data': copy.deepcopy(root_map['step_data'])} if isinstance(root_map.get('step_data'), Mapping) else {}),
    }

    ev_in = opts.get('evidence') if isinstance(opts.get('evidence'), Mapping) else {}
    unv_reasons = list(ev_in.get('unverifiable_reasons') or [])
    unv_checks = int(ev_in.get('unverifiable_checks') or 0)
    if settle_timed_out:
        unv_checks += 1
        unv_reasons.append('ui.settle_timeout')

    roles_after = root_map.get('roles') if isinstance(root_map.get('roles'), Mapping) else (opts.get('roles') or {})
    elements_after = root_map.get('elements') if isinstance(root_map.get('elements'), list) else (opts.get('elements') or [])
    trans_in = opts.get('transition') if isinstance(opts.get('transition'), Mapping) else {}
    conf_ms = opts.get('configured_duration_ms', opts.get('configuredDurationMs', root_map.get('configuredDurationMs')))

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
