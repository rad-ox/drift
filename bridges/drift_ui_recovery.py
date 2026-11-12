"""Task-completion recovery invariants (async-action-feedback@1, wizard-form@1), observed capability derivation, and UI scenario matrices."""
from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from typing import Any

DEFAULT_CURATED_UI_SCENARIOS: tuple[str, ...] = ('keyboard_only', 'narrow_viewport', 'long_localized_text', 'reduced_motion', 'slow_or_failed_async')


def _is_fin(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _bool_or_none(v: Any, fb: bool | None) -> bool | None:
    return v if isinstance(v, bool) else fb


def _is_hidden_basic(el: Any) -> bool:
    if not isinstance(el, Mapping): return False
    pres = str(el.get('presence') or el.get('state') or '').strip().lower()
    if pres in ('hidden', 'absent', 'collapsed') or el.get('hidden') is True or el.get('ariaHidden') is True or el.get('aria-hidden') == 'true': return True
    style = el.get('style') if isinstance(el.get('style'), Mapping) else {}
    return str(el.get('display') or style.get('display') or '').strip().lower() == 'none' or str(el.get('visibility') or style.get('visibility') or '').strip().lower() in ('hidden', 'collapse')


def derive_observed_capabilities(s: Mapping[str, Any], raw_roles: Mapping[str, Any], elements: list[Any], before: Mapping[str, Any], trans_raw: Mapping[str, Any], after_raw: Mapping[str, Any], c_sum: Mapping[str, Any]) -> list[str]:
    caps: list[str] = []
    has_rg = any(isinstance(r, Mapping) and not _is_hidden_basic(r) and _is_fin((g := (r.get('geometry') if isinstance(r.get('geometry'), Mapping) else r)).get('width')) and _is_fin(g.get('height')) and float(g['width']) > 0 and float(g['height']) > 0 for r in raw_roles.values())
    has_eg = any(isinstance(el, Mapping) and not _is_hidden_basic(el) and _is_fin(el.get('width')) and _is_fin(el.get('height')) and float(el['width']) > 0 and float(el['height']) > 0 for el in elements)
    if has_rg or has_eg or (_is_fin(s.get('viewportWidth')) and float(s['viewportWidth']) > 0 and _is_fin(s.get('documentWidth'))): caps.append('geometry')
    if before.get('input_focus_role') or before.get('inputFocusRole') or after_raw.get('input_focus_role') or after_raw.get('inputFocusRole') or isinstance(trans_raw.get('focus_trace'), list) or isinstance(trans_raw.get('focusTrace'), list) or _is_fin(trans_raw.get('unexpected_focus_steals')) or _is_fin(trans_raw.get('unexpectedFocusSteals')) or any(isinstance(el, Mapping) and ('focused' in el or el.get('focusable') is True) for el in elements):
        caps.append('input_focus')
    if 'assistive_announcement' in s or 'active_assistive_focus' in s or 'assistive_announcement' in after_raw or 'active_assistive_focus' in after_raw or isinstance(s.get('assistive_trace'), list) or isinstance(trans_raw.get('assistive_trace'), list):
        caps.append('assistive_focus')
    pres = s.get('presentation') if isinstance(s.get('presentation'), Mapping) else {}
    cw = pres.get('contrast_wcag22') if isinstance(pres.get('contrast_wcag22'), Mapping) else {}
    if int(c_sum.get('measuredCount') or 0) > 0 or any(_is_fin(cw.get(k)) for k in ('text_normal_min', 'text_large_min', 'ui_component_min', 'violations_count')) or _is_fin(s.get('min_contrast_ratio')) or _is_fin(s.get('min_contrast_wcag22')):
        caps.append('wcag22_contrast')
    if any(_is_fin(trans_raw.get(k)) for k in ('observed_duration_ms', 'observedDurationMs', 'configured_duration_ms', 'configuredDurationMs')):
        caps.append('observed_transition')
    if any(k in before or k in after_raw for k in ('scroll_anchor_id', 'scrollAnchorId')) or _is_fin(after_raw.get('scroll_offset_delta')) or isinstance(after_raw.get('scroll_context_preserved'), bool) or any(isinstance(el, Mapping) and (any(k in el for k in ('scrollable', 'horizontallyScrollable', 'verticallyScrollable')) or _is_fin(el.get('scrollWidth')) or _is_fin(el.get('scrollHeight'))) for el in elements):
        caps.append('scroll_state')
    return caps


def is_point_covered_by_visual_overlays(px: float, py: float, el: Mapping[str, Any], overlays: list[Any]) -> bool:
    if not overlays: return False
    el_style = el.get('style') if isinstance(el.get('style'), Mapping) else {}
    el_z = float(el.get('zIndex', el_style.get('zIndex', 0)) or 0)
    for ov in overlays:
        if not isinstance(ov, Mapping) or ov is el or _is_hidden_basic(ov): continue
        ov_style = ov.get('style') if isinstance(ov.get('style'), Mapping) else {}
        if float(ov.get('opacity', ov_style.get('opacity', 1)) or 1) <= 0: continue
        if float(ov.get('zIndex', ov_style.get('zIndex', 1)) or 1) < el_z and ov.get('blocksVisualFocus') is not True and ov.get('isOverlay') is not True: continue
        r = ov.get('rect') if isinstance(ov.get('rect'), Mapping) else ov
        left, top, w, h = float(r.get('left', r.get('x', 0)) or 0), float(r.get('top', r.get('y', 0)) or 0), float(r.get('width', 0) or 0), float(r.get('height', 0) or 0)
        if w > 0 and h > 0 and left <= px <= left + w and top <= py <= top + h: return True
    return False


def _opt_surface_flag(raw: Mapping[str, Any]) -> dict[str, bool]:
    return {'surface_found': bool(raw['surfaceFound'])} if 'surfaceFound' in raw else ({'surface_found': bool(raw['surface_found'])} if 'surface_found' in raw else {})


def build_compose_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    nodes = raw.get('nodes') if isinstance(raw.get('nodes'), Mapping) else {}
    roles: dict[str, Any] = {}
    for role_id, n in nodes.items():
        if not isinstance(n, Mapping): continue
        vis = n.get('visible') is not False and n.get('displayed') is not False
        b = n.get('boundsInRoot') or n.get('bounds') or {}
        sem = ('alertdialog' if n.get('isModal') is True else 'alert') if (str(n.get('liveRegion') or '').lower() == 'assertive' or n.get('isDialog') is True) else str(n.get('role') or 'region').lower()
        roles[role_id] = {
            'presence': n.get('presence', 'visible' if vis else 'hidden'), 'semantic_role': sem,
            **({'selected_entity_id': n['selectedEntityId']} if 'selectedEntityId' in n else {}),
            **({'bound_entity_id': n['boundEntityId']} if 'boundEntityId' in n else {}),
            **({'container_mode': n['containerMode']} if 'containerMode' in n else {}),
            'actions': list(n.get('actions') or []),
            'content_cues': {'has_visible_text': bool(vis and str(n.get('text') or '').strip()), 'has_graphic_icon': bool(vis and (n.get('hasIcon') is True or n.get('contentDescription'))), 'has_semantic_role': sem in ('alert', 'alertdialog', 'status')},
            'geometry': {'unit': 'dp', 'x': float(b.get('left', b.get('x', 0))), 'y': float(b.get('top', b.get('y', 0))), 'width': float(b.get('width', 0)), 'height': float(b.get('height', 0)), 'reading_order_rank': int(n.get('traversalIndex', n.get('readingOrderRank', 0)))},
        }
    has_vp = _is_fin(raw.get('viewportWidthDp'))
    return {**_opt_surface_flag(raw), 'adapter': raw.get('adapter') or {'name': 'compose-semantics'}, 'environment_ref': raw.get('environment_ref'), 'roles': roles, 'before': raw.get('before'), 'action': raw.get('action'), 'transition': raw.get('transition'), 'after': raw.get('after'), **({'documentWidth': float(raw['viewportWidthDp']), 'viewportWidth': float(raw['viewportWidthDp'])} if has_vp else {})}


def build_uia_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    ctrls = raw.get('elements') or raw.get('controls') or {}
    roles: dict[str, Any] = {}
    if isinstance(ctrls, Mapping):
        for role_id, c in ctrls.items():
            if not isinstance(c, Mapping): continue
            off = bool(c.get('IsOffscreen') is True or c.get('presence') in ('hidden', 'absent'))
            r = c.get('BoundingRectangle') or c.get('rect') or {}
            ctype = str(c.get('ControlType') or c.get('semantic_role') or 'Pane')
            sem = 'alertdialog' if (ctype == 'Window.AlertDialog' or c.get('isModal') is True) else ('alert' if ctype in ('StatusBar', 'Alert') else 'region')
            roles[role_id] = {
                'presence': c.get('presence', 'hidden') if off else 'visible', 'semantic_role': sem,
                **({'selected_entity_id': c['selectedEntityId']} if 'selectedEntityId' in c else {}),
                **({'bound_entity_id': c['boundEntityId']} if 'boundEntityId' in c else {}),
                **({'container_mode': c['containerMode']} if 'containerMode' in c else {}),
                'actions': list(c.get('patterns') or []),
                'content_cues': {'has_visible_text': bool(not off and str(c.get('Name') or c.get('text') or '').strip()), 'has_graphic_icon': bool(not off and c.get('hasIcon') is True), 'has_semantic_role': sem in ('alert', 'alertdialog')},
                'geometry': {'unit': 'dip', 'x': float(r.get('x', r.get('left', 0))), 'y': float(r.get('y', r.get('top', 0))), 'width': float(r.get('width', 0)), 'height': float(r.get('height', 0)), 'reading_order_rank': int(c.get('readingOrderRank', 0))},
            }
    has_w = _is_fin(raw.get('windowWidthDip'))
    return {**_opt_surface_flag(raw), 'adapter': raw.get('adapter') or {'name': 'windows-uia'}, 'environment_ref': raw.get('environment_ref'), 'roles': roles, 'before': raw.get('before'), 'action': raw.get('action'), 'transition': raw.get('transition'), 'after': raw.get('after'), **({'documentWidth': float(raw['windowWidthDip']), 'viewportWidth': float(raw['windowWidthDip'])} if has_w else {})}


def evaluate_task_recovery(s: Mapping[str, Any], before: Mapping[str, Any], after_raw: Mapping[str, Any]) -> dict[str, Any]:
    reqs = s.get('async_requests') if isinstance(s.get('async_requests'), list) else (after_raw.get('async_requests') if isinstance(after_raw.get('async_requests'), list) else None)
    applied_req_id = after_raw.get('applied_request_id', after_raw.get('appliedRequestId'))
    stale_suppressed = _bool_or_none(after_raw.get('stale_response_suppressed', after_raw.get('staleResponseSuppressed')), None)
    if reqs:
        latest_seq, latest_id, max_com, stale_over = -math.inf, None, -math.inf, False
        for r in reqs:
            if not isinstance(r, Mapping): continue
            seq, rid = float(r.get('seq', r.get('request_seq', 0)) or 0), str(r.get('id', r.get('request_id', '')))
            if seq > latest_seq: latest_seq, latest_id = seq, rid
            if r.get('applied') is True or r.get('overwrote_state') is True:
                if seq < max_com: stale_over = True
                max_com, applied_req_id = max(max_com, seq), rid
            elif r.get('committed') is True and seq > max_com:
                max_com = seq
                if not applied_req_id: applied_req_id = rid
        applied_req_id = after_raw.get('applied_request_id', after_raw.get('appliedRequestId', applied_req_id))
        if stale_suppressed is None and latest_id is not None and applied_req_id is not None:
            stale_suppressed = (applied_req_id == latest_id) and not stale_over
    elif stale_suppressed is None and 'latest_request_id' in after_raw and applied_req_id is not None:
        stale_suppressed = applied_req_id == after_raw.get('latest_request_id')
    ops = s.get('optimistic_ops') if isinstance(s.get('optimistic_ops'), list) else (after_raw.get('optimistic_ops') if isinstance(after_raw.get('optimistic_ops'), list) else None)
    sel_rollback = _bool_or_none(after_raw.get('selective_rollback_preserved', after_raw.get('selectiveRollbackPreserved')), None)
    if ops and sel_rollback is None:
        st_raw = after_raw.get('entity_state') if isinstance(after_raw.get('entity_state'), Mapping) else (after_raw.get('state') if isinstance(after_raw.get('state'), Mapping) else {})
        has_f = has_c = False
        ok = True
        for op in ops:
            if not isinstance(op, Mapping): continue
            fld = str(op.get('field', op.get('id', '')))
            act, st = (st_raw[fld] if fld in st_raw else op.get('after')), str(op.get('status', op.get('outcome', '')))
            if st == 'failed':
                has_f = True
                if act != op.get('before'): ok = False
            elif st in ('committed', 'succeeded'):
                has_c = True
                if act != op.get('committed_value', op.get('optimistic')): ok = False
        if has_f and has_c: sel_rollback = ok
    ig, disp = after_raw.get('in_flight_ignored_submits'), after_raw.get('dispatched_submits')
    rp, di = after_raw.get('retry_payload'), before.get('dirty_inputs')
    b_steps, a_steps = before.get('step_data', before.get('stepData')), after_raw.get('step_data', after_raw.get('stepData'))
    inv_f = after_raw.get('invalid_fields', after_raw.get('invalidFields'))
    blk_f = after_raw.get('blocking_fields', after_raw.get('blockingFields'))
    act_step = after_raw.get('active_step', after_raw.get('activeStep', before.get('active_step')))
    return {
        **({'applied_request_id': applied_req_id} if applied_req_id is not None else {}),
        'stale_response_suppressed': stale_suppressed,
        'selective_rollback_preserved': sel_rollback,
        'duplicate_submit_prevented': _bool_or_none(after_raw.get('duplicate_submit_prevented', after_raw.get('duplicateSubmitPrevented')), (float(ig) > 0 and int(disp) == 1) if (_is_fin(ig) and _is_fin(disp)) else None),
        'retry_coherent': _bool_or_none(after_raw.get('retry_coherent', after_raw.get('retryCoherent')), (json.dumps(rp, sort_keys=True) == json.dumps(di, sort_keys=True)) if (isinstance(rp, Mapping) and isinstance(di, Mapping)) else None),
        'step_data_preserved': _bool_or_none(after_raw.get('step_data_preserved', after_raw.get('stepDataPreserved')), all(json.dumps(b_steps.get(k), sort_keys=True) == json.dumps(a_steps.get(k), sort_keys=True) for k in b_steps) if (isinstance(b_steps, Mapping) and isinstance(a_steps, Mapping)) else None),
        'field_linked_errors': _bool_or_none(after_raw.get('field_linked_errors', after_raw.get('fieldLinkedErrors')), all(isinstance(f, Mapping) and bool(f.get('field_id', f.get('fieldId'))) and bool(f.get('error_id', f.get('errorId'))) and f.get('error_visible', f.get('errorVisible')) is True for f in inv_f) if (isinstance(inv_f, list) and len(inv_f) > 0) else None),
        'blocking_gate_scoped': _bool_or_none(after_raw.get('blocking_gate_scoped', after_raw.get('blockingGateScoped')), all(isinstance(f, Mapping) and f.get('step', f.get('step_id')) == act_step for f in blk_f) if (isinstance(blk_f, list) and act_step is not None) else None),
        'resumed_from_interruption': _bool_or_none(after_raw.get('resumed_from_interruption', after_raw.get('resumedFromInterruption')), None),
    }


def evaluate_scenario_matrix(spec: Mapping[str, Any], check_view_table_fn: Callable[..., Any] | None = None) -> dict[str, Any]:
    s = dict(spec) if isinstance(spec, Mapping) else {}
    contract_id, case_id = str(s.get('contract') or 'ui-contract'), str(s.get('caseId') or s.get('case_id') or 'scenario-matrix')
    req_raw = s.get('required_scenarios', s.get('requiredScenarios'))
    required = list(req_raw) if isinstance(req_raw, list) else list(DEFAULT_CURATED_UI_SCENARIOS)
    scenarios = s.get('scenarios') if isinstance(s.get('scenarios'), Mapping) else {}
    verified_scenarios: list[str] = []
    verified_envs: list[str] = []
    for sc_name in required:
        entry = scenarios.get(sc_name)
        if not isinstance(entry, Mapping): raise AssertionError(f'{contract_id}.{case_id}: scenario_matrix.missing:{sc_name}')
        obs = entry.get('observation') if isinstance(entry.get('observation'), Mapping) else entry
        sf = obs.get('surface_found') is True or obs.get('surfaceFound') is True
        unv = int((obs.get('evidence') if isinstance(obs.get('evidence'), Mapping) else {}).get('unverifiable_checks') or obs.get('unverifiable_checks') or 0)
        if not sf or unv > 0: raise AssertionError(f"{contract_id}.{case_id}: scenario_matrix.unverifiable:{sc_name}:{'surface.missing' if not sf else f'unverifiable_checks={unv}'}")
        then_tbl = entry.get('then') if isinstance(entry.get('then'), Mapping) else (s.get('then') if isinstance(s.get('then'), Mapping) else None)
        if then_tbl and callable(check_view_table_fn):
            proj = entry.get('projections') if isinstance(entry.get('projections'), Mapping) else (s.get('projections') if isinstance(s.get('projections'), Mapping) else {})
            check_view_table_fn(contract_id, f'{case_id}[{sc_name}]', then_tbl, set(), obs, None, None, {}, lambda p=proj: p)
        verified_scenarios.append(str(sc_name))
        env_ref = obs.get('environment_ref')
        if isinstance(env_ref, str) and env_ref and env_ref not in verified_envs: verified_envs.append(env_ref)
    return {'schema': 'drift.ui-scenario-matrix/1', 'contract': contract_id, 'case_id': case_id, 'verified_scenarios': verified_scenarios, 'verified_environments': verified_envs, 'all_scenarios_passed': len(verified_scenarios) == len(required), 'claim_scope': 'verified_in_declared_scenarios_and_environments'}


def strip_bom(text: str) -> str:
    return text[1:] if text.startswith('\ufeff') else text


def read_json(path: Any) -> Any:
    import json
    return json.loads(strip_bom(path.read_text(encoding='utf-8')))


def dump_json(obj: Any) -> str:
    import json
    return json.dumps(obj, separators=(',', ':'))


def hash_bytes(raw: bytes) -> str:
    import hashlib
    normalized = raw if b'\x00' in raw else raw.replace(b'\r\n', b'\n')
    return f'sha256:{hashlib.sha256(normalized).hexdigest()}'


def _is_finite_num_03(v: Any) -> bool:
    import math
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _qualify_peer_03(s: Any) -> Any:
    return (s if s.startswith(('when.', 'then.', '/')) else f'then.{s}') if isinstance(s, str) and s.strip() else s


def desugar_03_rel(raw: Mapping[str, Any], units: Mapping[str, Any] | None = None, pred_unit: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k == 'tol' and isinstance(v, Mapping):
            if 'abs' in v: out['abs_tol'] = v['abs']
            if 'rel' in v: out['rel_tol'] = v['rel']
        elif k == 'len' and isinstance(v, Mapping):
            if 'min' in v: out['min_len'] = v['min']
            if 'max' in v: out['max_len'] = v['max']
        elif k == 'keys' and isinstance(v, Mapping):
            if 'allow' in v: out['allowed_keys'] = v['allow']
            if 'forbid' in v: out['forbid_keys'] = v['forbid']
        elif k == 'peer' and isinstance(v, Mapping):
            if 'le' in v: out['le_field'] = _qualify_peer_03(v['le'])
            if 'ge' in v: out['ge_field'] = _qualify_peer_03(v['ge'])
            if 'eq' in v: out['eq_field'] = _qualify_peer_03(v['eq'])
            if isinstance(v.get('sum'), list): out['sum_fields'] = [_qualify_peer_03(x) for x in v['sum']]
            if isinstance(v.get('balance'), Mapping):
                b = v['balance']
                out['balance_fields'] = {
                    **({'add': [_qualify_peer_03(x) for x in b['add']]} if isinstance(b.get('add'), list) else {}),
                    **({'sub': [_qualify_peer_03(x) for x in b['sub']]} if isinstance(b.get('sub'), list) else {}),
                }
        elif k == 'series' and isinstance(v, Mapping):
            out.update(v)
            if out.get('monotonic') in ('increasing', 'decreasing'):
                out['monotonic'] = f"strictly_{out['monotonic']}"
        elif k != 'convert_from':
            out[k] = v
    if 'convert_from' in raw:
        units = units or {}
        cf = raw['convert_from']
        matches = [k for k in units if k.startswith(f'{cf}->')]
        target = pred_unit or raw.get('unit')
        ratio = 1 if target == cf else units.get(f'{cf}->{target}' if target else (matches[0] if len(matches) == 1 else ''))
        if not _is_finite_num_03(ratio) or ratio <= 0:
            raise AssertionError(f'missing unit conversion from {cf} to {target}')
        scale = lambda v: v * ratio if _is_finite_num_03(v) else v
        for k in ('eq', 'min', 'max', 'approx', 'abs_tol', 'step_max_delta'):
            if k in out: out[k] = scale(out[k])
        for k in ('in', 'not_in'):
            if isinstance(out.get(k), (list, tuple)): out[k] = [scale(v) for v in out[k]]
        if 'sum_total' in out:
            st = out['sum_total']
            out['sum_total'] = {k: scale(v) for k, v in st.items()} if isinstance(st, Mapping) else scale(st)
    if 'eq' in out and ('abs_tol' in out or 'rel_tol' in out) and 'balance_fields' not in out and 'sum_fields' not in out:
        out['approx'] = out.pop('eq')
    return out


def converted_table(view: Mapping[str, Any], side: str, table: dict[str, Any]) -> dict[str, Any]:
    if not any(isinstance(v, Mapping) and 'convert_from' in v for v in table.values()):
        return table
    return {k: desugar_03_rel(v, view.get('units', {}), view.get('schema', {}).get(side, {}).get(k, {}).get('unit'))
            if isinstance(v, Mapping) and 'convert_from' in v else v for k, v in table.items()}

