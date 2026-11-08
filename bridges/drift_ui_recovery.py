"""Task-completion recovery invariants (async-action-feedback@1, wizard-form@1), observed capability derivation, and UI scenario matrices."""
from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from typing import Any

DEFAULT_CURATED_UI_SCENARIOS: tuple[str, ...] = (
    'keyboard_only',
    'narrow_viewport',
    'long_localized_text',
    'reduced_motion',
    'slow_or_failed_async',
)


def _is_fin(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _bool_or_none(v: Any, fb: bool | None) -> bool | None:
    return v if isinstance(v, bool) else fb


def _is_hidden_basic(el: Any) -> bool:
    if not isinstance(el, Mapping):
        return False
    pres = str(el.get('presence') or el.get('state') or '').strip().lower()
    if pres in ('hidden', 'absent', 'collapsed') or el.get('hidden') is True or el.get('ariaHidden') is True or el.get('aria-hidden') == 'true':
        return True
    style = el.get('style') if isinstance(el.get('style'), Mapping) else {}
    return str(el.get('display') or style.get('display') or '').strip().lower() == 'none' or str(el.get('visibility') or style.get('visibility') or '').strip().lower() in ('hidden', 'collapse')


def derive_observed_capabilities(
    s: Mapping[str, Any],
    raw_roles: Mapping[str, Any],
    elements: list[Any],
    before: Mapping[str, Any],
    trans_raw: Mapping[str, Any],
    after_raw: Mapping[str, Any],
    c_sum: Mapping[str, Any],
) -> list[str]:
    caps: list[str] = []
    has_role_geom = any(
        isinstance(r, Mapping)
        and not _is_hidden_basic(r)
        and _is_fin((r.get('geometry') if isinstance(r.get('geometry'), Mapping) else r).get('width'))
        and _is_fin((r.get('geometry') if isinstance(r.get('geometry'), Mapping) else r).get('height'))
        and float((r.get('geometry') if isinstance(r.get('geometry'), Mapping) else r).get('width')) > 0
        and float((r.get('geometry') if isinstance(r.get('geometry'), Mapping) else r).get('height')) > 0
        for r in raw_roles.values()
    )
    has_el_geom = any(
        isinstance(el, Mapping)
        and not _is_hidden_basic(el)
        and _is_fin(el.get('width'))
        and _is_fin(el.get('height'))
        and float(el['width']) > 0
        and float(el['height']) > 0
        for el in elements
    )
    has_vp_geom = _is_fin(s.get('viewportWidth')) and float(s['viewportWidth']) > 0 and _is_fin(s.get('documentWidth'))
    if has_role_geom or has_el_geom or has_vp_geom:
        caps.append('geometry')

    if (
        before.get('input_focus_role')
        or before.get('inputFocusRole')
        or after_raw.get('input_focus_role')
        or after_raw.get('inputFocusRole')
        or isinstance(trans_raw.get('focus_trace'), list)
        or isinstance(trans_raw.get('focusTrace'), list)
        or _is_fin(trans_raw.get('unexpected_focus_steals'))
        or _is_fin(trans_raw.get('unexpectedFocusSteals'))
        or any(isinstance(el, Mapping) and ('focused' in el or el.get('focusable') is True) for el in elements)
    ):
        caps.append('input_focus')

    if (
        'assistive_announcement' in s
        or 'active_assistive_focus' in s
        or 'assistive_announcement' in after_raw
        or 'active_assistive_focus' in after_raw
        or isinstance(s.get('assistive_trace'), list)
        or isinstance(trans_raw.get('assistive_trace'), list)
    ):
        caps.append('assistive_focus')

    pres = s.get('presentation') if isinstance(s.get('presentation'), Mapping) else {}
    cw = pres.get('contrast_wcag22') if isinstance(pres.get('contrast_wcag22'), Mapping) else {}
    if (
        int(c_sum.get('measuredCount') or 0) > 0
        or _is_fin(cw.get('text_normal_min'))
        or _is_fin(cw.get('text_large_min'))
        or _is_fin(cw.get('ui_component_min'))
        or _is_fin(cw.get('violations_count'))
        or _is_fin(s.get('min_contrast_ratio'))
        or _is_fin(s.get('min_contrast_wcag22'))
    ):
        caps.append('wcag22_contrast')

    if (
        _is_fin(trans_raw.get('observed_duration_ms'))
        or _is_fin(trans_raw.get('observedDurationMs'))
        or _is_fin(trans_raw.get('configured_duration_ms'))
        or _is_fin(trans_raw.get('configuredDurationMs'))
    ):
        caps.append('observed_transition')

    if (
        'scroll_anchor_id' in before
        or 'scrollAnchorId' in before
        or 'scroll_anchor_id' in after_raw
        or 'scrollAnchorId' in after_raw
        or _is_fin(after_raw.get('scroll_offset_delta'))
        or isinstance(after_raw.get('scroll_context_preserved'), bool)
        or any(
            isinstance(el, Mapping)
            and (
                'scrollable' in el
                or 'horizontallyScrollable' in el
                or 'verticallyScrollable' in el
                or _is_fin(el.get('scrollWidth'))
                or _is_fin(el.get('scrollHeight'))
            )
            for el in elements
        )
    ):
        caps.append('scroll_state')
    return caps


def is_point_covered_by_visual_overlays(px: float, py: float, el: Mapping[str, Any], overlays: list[Any]) -> bool:
    if not overlays:
        return False
    el_style = el.get('style') if isinstance(el.get('style'), Mapping) else {}
    el_z = float(el.get('zIndex', el_style.get('zIndex', 0)) or 0)
    for ov in overlays:
        if not isinstance(ov, Mapping) or ov is el or _is_hidden_basic(ov):
            continue
        ov_style = ov.get('style') if isinstance(ov.get('style'), Mapping) else {}
        opacity = float(ov.get('opacity', ov_style.get('opacity', 1)) or 1)
        if opacity <= 0:
            continue
        ov_z = float(ov.get('zIndex', ov_style.get('zIndex', 1)) or 1)
        if ov_z < el_z and ov.get('blocksVisualFocus') is not True and ov.get('isOverlay') is not True:
            continue
        r = ov.get('rect') if isinstance(ov.get('rect'), Mapping) else ov
        left = float(r.get('left', r.get('x', 0)) or 0)
        top = float(r.get('top', r.get('y', 0)) or 0)
        width = float(r.get('width', 0) or 0)
        height = float(r.get('height', 0) or 0)
        if width > 0 and height > 0 and left <= px <= left + width and top <= py <= top + height:
            return True
    return False


def _opt_surface_flag(raw: Mapping[str, Any]) -> dict[str, bool]:
    if 'surfaceFound' in raw:
        return {'surface_found': bool(raw['surfaceFound'])}
    return {'surface_found': bool(raw['surface_found'])} if 'surface_found' in raw else {}


def build_compose_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    nodes = raw.get('nodes') if isinstance(raw.get('nodes'), Mapping) else {}
    roles: dict[str, Any] = {}
    for role_id, n in nodes.items():
        if not isinstance(n, Mapping):
            continue
        vis = n.get('visible') is not False and n.get('displayed') is not False
        bounds = n.get('boundsInRoot') or n.get('bounds') or {}
        live = str(n.get('liveRegion') or '').lower()
        sem = ('alertdialog' if n.get('isModal') is True else 'alert') if (live == 'assertive' or n.get('isDialog') is True) else str(n.get('role') or 'region').lower()
        roles[role_id] = {
            'presence': n.get('presence', 'visible' if vis else 'hidden'),
            'semantic_role': sem,
            **({'selected_entity_id': n['selectedEntityId']} if 'selectedEntityId' in n else {}),
            **({'bound_entity_id': n['boundEntityId']} if 'boundEntityId' in n else {}),
            **({'container_mode': n['containerMode']} if 'containerMode' in n else {}),
            'actions': list(n.get('actions') or []),
            'content_cues': {
                'has_visible_text': bool(vis and str(n.get('text') or '').strip()),
                'has_graphic_icon': bool(vis and (n.get('hasIcon') is True or n.get('contentDescription'))),
                'has_semantic_role': sem in ('alert', 'alertdialog', 'status'),
            },
            'geometry': {
                'unit': 'dp',
                'x': float(bounds.get('left', bounds.get('x', 0))),
                'y': float(bounds.get('top', bounds.get('y', 0))),
                'width': float(bounds.get('width', 0)),
                'height': float(bounds.get('height', 0)),
                'reading_order_rank': int(n.get('traversalIndex', n.get('readingOrderRank', 0))),
            },
        }
    has_vp = _is_fin(raw.get('viewportWidthDp'))
    return {
        **_opt_surface_flag(raw),
        'adapter': raw.get('adapter') or {'name': 'compose-semantics'},
        'environment_ref': raw.get('environment_ref'),
        'roles': roles,
        'before': raw.get('before'),
        'action': raw.get('action'),
        'transition': raw.get('transition'),
        'after': raw.get('after'),
        **({'documentWidth': float(raw['viewportWidthDp']), 'viewportWidth': float(raw['viewportWidthDp'])} if has_vp else {}),
    }


def build_uia_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    ctrls = raw.get('elements') or raw.get('controls') or {}
    roles: dict[str, Any] = {}
    if isinstance(ctrls, Mapping):
        for role_id, c in ctrls.items():
            if not isinstance(c, Mapping):
                continue
            off = bool(c.get('IsOffscreen') is True or c.get('presence') in ('hidden', 'absent'))
            rect = c.get('BoundingRectangle') or c.get('rect') or {}
            ctype = str(c.get('ControlType') or c.get('semantic_role') or 'Pane')
            sem = 'alertdialog' if (ctype == 'Window.AlertDialog' or c.get('isModal') is True) else ('alert' if ctype in ('StatusBar', 'Alert') else 'region')
            roles[role_id] = {
                'presence': c.get('presence', 'hidden') if off else 'visible',
                'semantic_role': sem,
                **({'selected_entity_id': c['selectedEntityId']} if 'selectedEntityId' in c else {}),
                **({'bound_entity_id': c['boundEntityId']} if 'boundEntityId' in c else {}),
                **({'container_mode': c['containerMode']} if 'containerMode' in c else {}),
                'actions': list(c.get('patterns') or []),
                'content_cues': {
                    'has_visible_text': bool(not off and str(c.get('Name') or c.get('text') or '').strip()),
                    'has_graphic_icon': bool(not off and c.get('hasIcon') is True),
                    'has_semantic_role': sem in ('alert', 'alertdialog'),
                },
                'geometry': {
                    'unit': 'dip',
                    'x': float(rect.get('x', rect.get('left', 0))),
                    'y': float(rect.get('y', rect.get('top', 0))),
                    'width': float(rect.get('width', 0)),
                    'height': float(rect.get('height', 0)),
                    'reading_order_rank': int(c.get('readingOrderRank', 0)),
                },
            }
    has_win_w = _is_fin(raw.get('windowWidthDip'))
    return {
        **_opt_surface_flag(raw),
        'adapter': raw.get('adapter') or {'name': 'windows-uia'},
        'environment_ref': raw.get('environment_ref'),
        'roles': roles,
        'before': raw.get('before'),
        'action': raw.get('action'),
        'transition': raw.get('transition'),
        'after': raw.get('after'),
        **({'documentWidth': float(raw['windowWidthDip']), 'viewportWidth': float(raw['windowWidthDip'])} if has_win_w else {}),
    }


def evaluate_task_recovery(s: Mapping[str, Any], before: Mapping[str, Any], after_raw: Mapping[str, Any]) -> dict[str, Any]:
    reqs = s.get('async_requests') if isinstance(s.get('async_requests'), list) else (
        after_raw.get('async_requests') if isinstance(after_raw.get('async_requests'), list) else None
    )
    applied_req_id = after_raw.get('applied_request_id', after_raw.get('appliedRequestId'))
    stale_suppressed = _bool_or_none(after_raw.get('stale_response_suppressed', after_raw.get('staleResponseSuppressed')), None)

    if reqs:
        latest_seq = -math.inf
        latest_id: str | None = None
        max_committed_so_far = -math.inf
        stale_overwrote = False
        for r in reqs:
            if not isinstance(r, Mapping):
                continue
            seq = float(r.get('seq', r.get('request_seq', 0)) or 0)
            rid = str(r.get('id', r.get('request_id', '')))
            if seq > latest_seq:
                latest_seq = seq
                latest_id = rid
            if r.get('applied') is True or r.get('overwrote_state') is True:
                if seq < max_committed_so_far:
                    stale_overwrote = True
                if seq > max_committed_so_far:
                    max_committed_so_far = seq
                applied_req_id = rid
            elif r.get('committed') is True and seq > max_committed_so_far:
                max_committed_so_far = seq
                if not applied_req_id:
                    applied_req_id = rid
        final_applied = after_raw.get('applied_request_id', after_raw.get('appliedRequestId', applied_req_id))
        applied_req_id = final_applied
        if stale_suppressed is None and latest_id is not None and final_applied is not None:
            stale_suppressed = (final_applied == latest_id) and not stale_overwrote
    elif stale_suppressed is None and 'latest_request_id' in after_raw and applied_req_id is not None:
        stale_suppressed = applied_req_id == after_raw.get('latest_request_id')

    ops = s.get('optimistic_ops') if isinstance(s.get('optimistic_ops'), list) else (
        after_raw.get('optimistic_ops') if isinstance(after_raw.get('optimistic_ops'), list) else None
    )
    sel_rollback = _bool_or_none(after_raw.get('selective_rollback_preserved', after_raw.get('selectiveRollbackPreserved')), None)
    if ops and sel_rollback is None:
        st_raw = after_raw.get('entity_state') if isinstance(after_raw.get('entity_state'), Mapping) else (
            after_raw.get('state') if isinstance(after_raw.get('state'), Mapping) else {}
        )
        has_failed = has_committed = False
        all_valid = True
        for op in ops:
            if not isinstance(op, Mapping):
                continue
            field = str(op.get('field', op.get('id', '')))
            actual = st_raw[field] if field in st_raw else op.get('after')
            status = str(op.get('status', op.get('outcome', '')))
            if status == 'failed':
                has_failed = True
                if actual != op.get('before'):
                    all_valid = False
            elif status in ('committed', 'succeeded'):
                has_committed = True
                exp_val = op.get('committed_value', op.get('optimistic'))
                if actual != exp_val:
                    all_valid = False
        if has_failed and has_committed:
            sel_rollback = all_valid

    ig = after_raw.get('in_flight_ignored_submits')
    disp = after_raw.get('dispatched_submits')
    dup_prev = _bool_or_none(
        after_raw.get('duplicate_submit_prevented', after_raw.get('duplicateSubmitPrevented')),
        (float(ig) > 0 and int(disp) == 1) if (_is_fin(ig) and _is_fin(disp)) else None,
    )

    rp = after_raw.get('retry_payload')
    di = before.get('dirty_inputs')
    retry_coh = _bool_or_none(
        after_raw.get('retry_coherent', after_raw.get('retryCoherent')),
        (json.dumps(rp, sort_keys=True) == json.dumps(di, sort_keys=True)) if (isinstance(rp, Mapping) and isinstance(di, Mapping)) else None,
    )

    b_steps = before.get('step_data', before.get('stepData'))
    a_steps = after_raw.get('step_data', after_raw.get('stepData'))
    step_pres = _bool_or_none(
        after_raw.get('step_data_preserved', after_raw.get('stepDataPreserved')),
        all(json.dumps(b_steps.get(k), sort_keys=True) == json.dumps(a_steps.get(k), sort_keys=True) for k in b_steps)
        if (isinstance(b_steps, Mapping) and isinstance(a_steps, Mapping))
        else None,
    )

    inv_fields = after_raw.get('invalid_fields', after_raw.get('invalidFields'))
    field_errs = _bool_or_none(
        after_raw.get('field_linked_errors', after_raw.get('fieldLinkedErrors')),
        all(
            isinstance(f, Mapping)
            and bool(f.get('field_id', f.get('fieldId')))
            and bool(f.get('error_id', f.get('errorId')))
            and f.get('error_visible', f.get('errorVisible')) is True
            for f in inv_fields
        )
        if (isinstance(inv_fields, list) and len(inv_fields) > 0)
        else None,
    )

    blk_fields = after_raw.get('blocking_fields', after_raw.get('blockingFields'))
    act_step = after_raw.get('active_step', after_raw.get('activeStep', before.get('active_step')))
    gate_scoped = _bool_or_none(
        after_raw.get('blocking_gate_scoped', after_raw.get('blockingGateScoped')),
        all(isinstance(f, Mapping) and f.get('step', f.get('step_id')) == act_step for f in blk_fields)
        if (isinstance(blk_fields, list) and act_step is not None)
        else None,
    )

    return {
        **({'applied_request_id': applied_req_id} if applied_req_id is not None else {}),
        'stale_response_suppressed': stale_suppressed,
        'selective_rollback_preserved': sel_rollback,
        'duplicate_submit_prevented': dup_prev,
        'retry_coherent': retry_coh,
        'step_data_preserved': step_pres,
        'field_linked_errors': field_errs,
        'blocking_gate_scoped': gate_scoped,
        'resumed_from_interruption': _bool_or_none(after_raw.get('resumed_from_interruption', after_raw.get('resumedFromInterruption')), None),
    }


def evaluate_scenario_matrix(spec: Mapping[str, Any], check_view_table_fn: Callable[..., Any] | None = None) -> dict[str, Any]:
    s = dict(spec) if isinstance(spec, Mapping) else {}
    contract_id = str(s.get('contract') or 'ui-contract')
    case_id = str(s.get('caseId') or s.get('case_id') or 'scenario-matrix')
    req_raw = s.get('required_scenarios', s.get('requiredScenarios'))
    required = list(req_raw) if isinstance(req_raw, list) else list(DEFAULT_CURATED_UI_SCENARIOS)
    scenarios = s.get('scenarios') if isinstance(s.get('scenarios'), Mapping) else {}
    verified_scenarios: list[str] = []
    verified_envs: list[str] = []

    for sc_name in required:
        entry = scenarios.get(sc_name)
        if not isinstance(entry, Mapping):
            raise AssertionError(f'{contract_id}.{case_id}: scenario_matrix.missing:{sc_name}')
        obs = entry.get('observation') if isinstance(entry.get('observation'), Mapping) else entry
        sf = obs.get('surface_found') is True or obs.get('surfaceFound') is True
        ev = obs.get('evidence') if isinstance(obs.get('evidence'), Mapping) else {}
        unv = int(ev.get('unverifiable_checks') or obs.get('unverifiable_checks') or 0)
        if not sf or unv > 0:
            reason = 'surface.missing' if not sf else f'unverifiable_checks={unv}'
            raise AssertionError(f'{contract_id}.{case_id}: scenario_matrix.unverifiable:{sc_name}:{reason}')
        then_tbl = entry.get('then') if isinstance(entry.get('then'), Mapping) else (
            s.get('then') if isinstance(s.get('then'), Mapping) else None
        )
        if then_tbl and callable(check_view_table_fn):
            proj = entry.get('projections') if isinstance(entry.get('projections'), Mapping) else (
                s.get('projections') if isinstance(s.get('projections'), Mapping) else {}
            )
            check_view_table_fn(contract_id, f'{case_id}[{sc_name}]', then_tbl, set(), obs, None, None, {}, lambda p=proj: p)
        verified_scenarios.append(str(sc_name))
        env_ref = obs.get('environment_ref')
        if isinstance(env_ref, str) and env_ref and env_ref not in verified_envs:
            verified_envs.append(env_ref)

    return {
        'schema': 'drift.ui-scenario-matrix/1',
        'contract': contract_id,
        'case_id': case_id,
        'verified_scenarios': verified_scenarios,
        'verified_environments': verified_envs,
        'all_scenarios_passed': len(verified_scenarios) == len(required),
        'claim_scope': 'verified_in_declared_scenarios_and_environments',
    }
