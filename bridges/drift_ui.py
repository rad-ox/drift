"""Cross-platform UI surface, interaction sequence, and adapter normalization for DRIFT (D282-D284)."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ALLOWED_DRIFT_ENV_KEYS = frozenset(('adapter', 'config', 'deps', 'drift', 'policy', 'runner', 'toolchain'))

PREDICATE_CAPABILITY: dict[str, str] = {
    'min_contrast_ratio': 'wcag22_contrast',
    'min_contrast_wcag22': 'wcag22_contrast',
    'min_contrast_text_normal': 'wcag22_contrast',
    'min_contrast_text_large': 'wcag22_contrast',
    'min_contrast_ui_component': 'wcag22_contrast',
    'contrast_violations_count': 'wcag22_contrast',
    'assistive_announcement': 'assistive_focus',
    'active_assistive_focus': 'assistive_focus',
    'observed_transition_ms': 'observed_transition',
    'max_transition_ms': 'observed_transition',
    'scroll_context_preserved': 'scroll_state',
    'horizontal_overflow_px': 'geometry',
    'min_target_px': 'geometry',
    'clipped_elements': 'geometry',
    'unintentional_clipped_count': 'geometry',
    'obscured_focus_elements': 'geometry',
    'fully_obscured_focus_count': 'geometry',
    'partially_obscured_focus_count': 'geometry',
    'notice_precedes_detail': 'geometry',
    'after_focus_role': 'input_focus',
    'active_focus': 'input_focus',
    'trigger_restored': 'input_focus',
    'unexpected_focus_steals': 'input_focus',
}


def _is_fin_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def is_element_hidden(el: Any) -> bool:
    if not isinstance(el, Mapping):
        return False
    pres = str(el.get('presence') or el.get('state') or '').strip().lower()
    if pres in ('hidden', 'absent', 'collapsed'):
        return True
    if el.get('hidden') is True or el.get('ariaHidden') is True or el.get('aria-hidden') == 'true':
        return True
    style = el.get('style') if isinstance(el.get('style'), Mapping) else {}
    disp = str(el.get('display') or style.get('display') or '').strip().lower()
    vis = str(el.get('visibility') or style.get('visibility') or '').strip().lower()
    return disp == 'none' or vis in ('hidden', 'collapse')


def is_element_scrollable(el: Any, axis: str = 'both') -> bool:
    if not isinstance(el, Mapping):
        return False
    if el.get('scrollable') is True:
        return True
    if el.get('scrollable') is False:
        return False
    style = el.get('style') if isinstance(el.get('style'), Mapping) else {}
    ox = str(el.get('overflowX') or style.get('overflowX') or el.get('overflow') or style.get('overflow') or '').strip().lower()
    oy = str(el.get('overflowY') or style.get('overflowY') or el.get('overflow') or style.get('overflow') or '').strip().lower()
    if axis == 'x':
        return ox in ('auto', 'scroll') or el.get('horizontallyScrollable') is True
    if axis == 'y':
        return oy in ('auto', 'scroll') or el.get('verticallyScrollable') is True
    return ox in ('auto', 'scroll') or oy in ('auto', 'scroll') or el.get('horizontallyScrollable') is True or el.get('verticallyScrollable') is True


def evaluate_element_clipping(el: Any) -> dict[str, Any]:
    if not isinstance(el, Mapping) or is_element_hidden(el):
        return {'clipped': False, 'scrollable': False, 'status': 'not_applicable'}
    sw = float(el.get('scrollWidth') or 0.0)
    cw = float(el.get('clientWidth') or 0.0)
    sh = float(el.get('scrollHeight') or 0.0)
    ch = float(el.get('clientHeight') or 0.0)
    over_x = sw > cw
    over_y = sh > ch
    scroll_x = is_element_scrollable(el, 'x')
    scroll_y = is_element_scrollable(el, 'y')
    return {
        'clipped': (over_x and not scroll_x) or (over_y and not scroll_y),
        'scrollable': scroll_x or scroll_y,
        'status': 'measured',
    }


def evaluate_focus_obscuration(el: Any) -> dict[str, Any]:
    if not isinstance(el, Mapping) or is_element_hidden(el) or el.get('focusable') is False:
        return {'fullyObscured': False, 'partiallyObscured': False, 'status': 'not_applicable'}
    if isinstance(el.get('fullyObscured'), bool) or isinstance(el.get('partiallyObscured'), bool):
        full = bool(el.get('fullyObscured'))
        part = bool(el.get('partiallyObscured') or full)
        return {'fullyObscured': full, 'partiallyObscured': part, 'status': 'measured'}
    pts = el.get('hitPoints')
    if isinstance(pts, list) and pts:
        total = len(pts)
        covered = sum(1 for p in pts if p is True or (isinstance(p, Mapping) and p.get('covered') is True))
        return {'fullyObscured': covered == total, 'partiallyObscured': covered > 0, 'status': 'measured'}
    if 'obscured' in el or 'focusObscured' in el:
        obs = bool(el.get('obscured') is True or el.get('focusObscured') is True)
        return {'fullyObscured': obs, 'partiallyObscured': obs, 'status': 'measured'}
    return {'fullyObscured': False, 'partiallyObscured': False, 'status': 'unverifiable'}


def evaluate_wcag22_contrast(elements: Any) -> dict[str, Any]:
    text_normal_min = math.inf
    text_large_min = math.inf
    ui_component_min = math.inf
    overall_min = math.inf
    violations = 0
    unverifiable = 0
    measured = 0
    for el in elements if isinstance(elements, list) else ():
        if not isinstance(el, Mapping) or is_element_hidden(el):
            continue
        if el.get('contrastUnverifiable') is True or el.get('backgroundUnverifiable') is True:
            unverifiable += 1
            continue
        ratio = el.get('contrastRatio') if 'contrastRatio' in el else el.get('contrast_ratio')
        if not _is_fin_num(ratio):
            continue
        r_val = float(ratio)
        measured += 1
        overall_min = min(overall_min, r_val)
        cat = str(el.get('contrastCategory') or el.get('category') or 'text_normal').strip().lower()
        floor = 3.0 if cat in ('text_large', 'ui_component') else 4.5
        if cat == 'text_large':
            text_large_min = min(text_large_min, r_val)
        elif cat == 'ui_component':
            ui_component_min = min(ui_component_min, r_val)
        else:
            text_normal_min = min(text_normal_min, r_val)
        if r_val + 1e-9 < floor:
            violations += 1
    return {
        'measuredCount': measured,
        'overallMin': overall_min if math.isfinite(overall_min) else None,
        'textNormalMin': text_normal_min if math.isfinite(text_normal_min) else None,
        'textLargeMin': text_large_min if math.isfinite(text_large_min) else None,
        'uiComponentMin': ui_component_min if math.isfinite(ui_component_min) else None,
        'violationsCount': violations,
        'unverifiableCount': unverifiable,
    }


def derive_non_color_cue(node: Any) -> dict[str, bool]:
    if not isinstance(node, Mapping):
        return {'has_visible_text': False, 'has_graphic_icon': False, 'has_semantic_role': False, 'non_color_encoded': False}
    cues = node.get('content_cues')
    role = str(node.get('semantic_role') or node.get('role') or '').strip().lower()
    if isinstance(cues, Mapping):
        has_text = bool(cues.get('has_visible_text'))
        has_icon = bool(cues.get('has_graphic_icon'))
        has_sem = bool(cues.get('has_semantic_role', role in ('alert', 'alertdialog', 'status')))
        return {
            'has_visible_text': has_text,
            'has_graphic_icon': has_icon,
            'has_semantic_role': has_sem,
            'non_color_encoded': has_text and (has_icon or has_sem),
        }
    txt = str(node.get('text') or node.get('textContent') or node.get('label') or '').strip()
    has_text = bool(txt) and not is_element_hidden(node)
    children = node.get('children') if isinstance(node.get('children'), list) else []
    has_icon = bool(
        node.get('hasIcon') is True
        or node.get('icon') is True
        or any(
            isinstance(c, Mapping)
            and not is_element_hidden(c)
            and (str(c.get('tagName') or '').upper() == 'SVG' or str(c.get('role') or '').lower() == 'img' or bool(c.get('isIcon')))
            for c in children
        )
    )
    has_sem = role in ('alert', 'alertdialog', 'status')
    return {
        'has_visible_text': has_text,
        'has_graphic_icon': has_icon,
        'has_semantic_role': has_sem,
        'non_color_encoded': has_text and (has_icon or has_sem),
    }


def observe_ui_sequence(spec: Mapping[str, Any] | None) -> dict[str, Any]:
    s = dict(spec) if isinstance(spec, Mapping) else {}
    surface_found = s.get('surface_found') is not False and s.get('surfaceFound') is not False
    adapter_raw = s.get('adapter')
    adapter_name = str(adapter_raw.get('name') if isinstance(adapter_raw, Mapping) else (adapter_raw or 'playwright-web'))
    caps_raw = (adapter_raw.get('capabilities') if isinstance(adapter_raw, Mapping) else None) or s.get('capabilities')
    capabilities = list(caps_raw) if isinstance(caps_raw, list) else [
        'geometry', 'input_focus', 'assistive_focus', 'wcag22_contrast', 'observed_transition', 'scroll_state',
    ]

    raw_roles = s.get('roles') if isinstance(s.get('roles'), Mapping) else {}
    roles: dict[str, dict[str, Any]] = {}
    ev_in = s.get('evidence') if isinstance(s.get('evidence'), Mapping) else {}
    unverifiable_checks = int(ev_in.get('unverifiable_checks') or s.get('unverifiableChecks') or 0)
    unverifiable_reasons = list(ev_in.get('unverifiable_reasons') or [])
    measured_checks = 0
    not_applicable_checks = 0

    if not surface_found:
        unverifiable_checks += 1
        unverifiable_reasons.append('surface.missing')

    for role_id, r_raw in raw_roles.items():
        r = dict(r_raw) if isinstance(r_raw, Mapping) else {'presence': 'absent'}
        pres = str(r.get('presence') or ('hidden' if is_element_hidden(r) else 'visible')).strip().lower()
        r['presence'] = pres
        exp_pres = str(r.get('expected_presence')).strip().lower() if r.get('expected_presence') else None
        if exp_pres == 'visible' and pres != 'visible':
            unverifiable_checks += 1
            unverifiable_reasons.append(f'missing_expected_visible:{role_id}')
        if pres != 'visible':
            r['status'] = 'not_applicable'
            not_applicable_checks += 1
        else:
            geom = r.get('geometry') if isinstance(r.get('geometry'), Mapping) else None
            w = float((geom or {}).get('width', r.get('width', -1)))
            h = float((geom or {}).get('height', r.get('height', -1)))
            if (geom is not None or 'width' in r or 'height' in r or exp_pres == 'visible') and (w <= 0 or h <= 0):
                r['status'] = 'unverifiable'
                unverifiable_checks += 1
                unverifiable_reasons.append(f'unverifiable_geometry:{role_id}')
            else:
                r['status'] = 'measured'
                measured_checks += 1
        if role_id == 'notice' or any(k in r for k in ('content_cues', 'nonColorCue', 'text', 'semantic_role')):
            r['content_cues'] = derive_non_color_cue(r)
        roles[role_id] = r

    seq_in = s.get('sequence') if isinstance(s.get('sequence'), Mapping) else {}
    before = dict(seq_in.get('before') or s.get('before') or {})
    action = dict(seq_in.get('action') or s.get('action') or {})
    trans_raw = dict(seq_in.get('transition') or s.get('transition') or {})
    after_raw = dict(seq_in.get('after') or s.get('after') or {})

    configured_ms = float(trans_raw.get('configured_duration_ms', trans_raw.get('configuredDurationMs', 0)))
    observed_ms = float(trans_raw.get('observed_duration_ms', trans_raw.get('observedDurationMs', configured_ms)))
    focus_trace = list(trans_raw.get('focus_trace') or trans_raw.get('focusTrace') or [])

    notice_role = roles.get('notice') or {}
    detail_role = roles.get('detail') or {}
    summary_role = roles.get('summary') or {}
    notice_sem = str(notice_role.get('semantic_role') or notice_role.get('role') or '').strip().lower()

    unexpected_steals = int(trans_raw.get('unexpected_focus_steals', trans_raw.get('unexpectedFocusSteals', 0)))
    if notice_role.get('presence') == 'visible' and notice_sem == 'alert':
        if 'notice' in focus_trace or after_raw.get('input_focus_role') == 'notice':
            unexpected_steals += 1

    sel_before = before.get('selected_entity_id', before.get('selectedEntityId'))
    sel_after = after_raw.get('selected_entity_id', after_raw.get('selectedEntityId', summary_role.get('selected_entity_id', sel_before)))
    sel_preserved = bool(after_raw['selection_preserved']) if 'selection_preserved' in after_raw else (sel_before == sel_after if sel_before is not None else True)

    dirty_before = before.get('dirty_inputs') or before.get('dirtyInputs')
    dirty_after = after_raw.get('dirty_inputs') or after_raw.get('dirtyInputs') or dirty_before
    dirty_preserved = bool(after_raw['dirty_inputs_preserved']) if 'dirty_inputs_preserved' in after_raw else (dirty_before == dirty_after if isinstance(dirty_before, Mapping) else True)

    anchor_before = before.get('scroll_anchor_id', before.get('scrollAnchorId'))
    anchor_after = after_raw.get('scroll_anchor_id', after_raw.get('scrollAnchorId', anchor_before))
    scroll_delta = float(after_raw.get('scroll_offset_delta') or 0.0)
    scroll_preserved = bool(after_raw['scroll_context_preserved']) if 'scroll_context_preserved' in after_raw else (anchor_before == anchor_after and abs(scroll_delta) <= 2.0 if anchor_before is not None else True)

    after_focus = str(after_raw.get('input_focus_role') or after_raw.get('inputFocusRole') or '')
    before_focus = str(before.get('input_focus_role') or before.get('inputFocusRole') or '')
    trigger_restored = bool(after_raw['trigger_restored']) if 'trigger_restored' in after_raw else bool(before_focus and after_focus == before_focus)

    notice_precedes = bool(after_raw.get('notice_precedes_detail', True))
    if notice_role.get('presence') == 'visible' and detail_role.get('presence') == 'visible':
        n_geom = notice_role.get('geometry') if isinstance(notice_role.get('geometry'), Mapping) else {}
        d_geom = detail_role.get('geometry') if isinstance(detail_role.get('geometry'), Mapping) else {}
        if _is_fin_num(n_geom.get('reading_order_rank')) and _is_fin_num(d_geom.get('reading_order_rank')):
            notice_precedes = float(n_geom['reading_order_rank']) < float(d_geom['reading_order_rank'])
        elif _is_fin_num(n_geom.get('y')) and _is_fin_num(d_geom.get('y')):
            notice_precedes = float(n_geom['y']) < float(d_geom['y'])

    detail_matches = bool(after_raw['detail_matches_selection']) if 'detail_matches_selection' in after_raw else (
        detail_role.get('bound_entity_id') == sel_after
        if detail_role.get('presence') == 'visible' and detail_role.get('bound_entity_id') is not None and sel_after is not None
        else True
    )

    elements = s.get('elements') if isinstance(s.get('elements'), list) else []
    c_sum = evaluate_wcag22_contrast(elements)
    pres_in = s.get('presentation') if isinstance(s.get('presentation'), Mapping) else {}
    clip_in = pres_in.get('clipping') if isinstance(pres_in.get('clipping'), Mapping) else {}
    foc_in = pres_in.get('focus_visibility') if isinstance(pres_in.get('focus_visibility'), Mapping) else {}
    cw_in = pres_in.get('contrast_wcag22') if isinstance(pres_in.get('contrast_wcag22'), Mapping) else {}

    unintentional_clipped = int(clip_in.get('unintentional_clipped_count') or 0)
    scrollable_containers = int(clip_in.get('scrollable_containers_count') or 0)
    if elements and not clip_in:
        unintentional_clipped = sum(1 for el in elements if evaluate_element_clipping(el)['clipped'])
        scrollable_containers = sum(1 for el in elements if evaluate_element_clipping(el)['scrollable'])

    fully_obscured = int(foc_in.get('fully_obscured_count') or 0)
    partially_obscured = int(foc_in.get('partially_obscured_count') or 0)
    if elements and not foc_in:
        fully_obscured = sum(1 for el in elements if evaluate_focus_obscuration(el)['fullyObscured'])
        partially_obscured = sum(1 for el in elements if evaluate_focus_obscuration(el)['partiallyObscured'])

    contrast_unverifiable = int(cw_in.get('unverifiable_count', c_sum['unverifiableCount']))
    if contrast_unverifiable > 0:
        unverifiable_checks += contrast_unverifiable
        unverifiable_reasons.append(f'contrast_unverifiable:{contrast_unverifiable}')

    return {
        'schema': 'drift.ui-observation/1',
        'surface_found': surface_found,
        'surfaceFound': surface_found,
        'adapter': {'name': adapter_name, 'capabilities': capabilities},
        **({'environment_ref': s['environment_ref']} if s.get('environment_ref') else {}),
        'roles': roles,
        'sequence': {
            'before': {
                **before,
                **({'input_focus_role': before_focus} if before_focus else {}),
                **({'selected_entity_id': sel_before} if sel_before is not None else {}),
                **({'scroll_anchor_id': anchor_before} if anchor_before is not None else {}),
                **({'dirty_inputs': dirty_before} if isinstance(dirty_before, Mapping) else {}),
            },
            'action': action,
            'transition': {
                'configured_duration_ms': int(configured_ms) if configured_ms.is_integer() else configured_ms,
                'observed_duration_ms': int(observed_ms) if observed_ms.is_integer() else observed_ms,
                'unexpected_focus_steals': unexpected_steals,
            },
            'after': {
                **after_raw,
                'input_focus_role': after_focus,
                'selection_preserved': sel_preserved,
                'dirty_inputs_preserved': dirty_preserved,
                'scroll_context_preserved': scroll_preserved,
                'trigger_restored': trigger_restored,
                'notice_precedes_detail': notice_precedes,
                'detail_matches_selection': detail_matches,
            },
        },
        'presentation': {
            'horizontal_overflow_px': float(pres_in.get('horizontal_overflow_px', max(0.0, float(s.get('documentWidth') or 0) - float(s.get('viewportWidth') or 0)))),
            'clipping': {
                'unintentional_clipped_count': unintentional_clipped,
                'scrollable_containers_count': scrollable_containers,
            },
            'focus_visibility': {
                'fully_obscured_count': fully_obscured,
                'partially_obscured_count': partially_obscured,
            },
            'contrast_wcag22': {
                'text_normal_min': cw_in.get('text_normal_min', c_sum['textNormalMin'] if c_sum['textNormalMin'] is not None else 7.0),
                'text_large_min': cw_in.get('text_large_min', c_sum['textLargeMin'] if c_sum['textLargeMin'] is not None else 7.0),
                'ui_component_min': cw_in.get('ui_component_min', c_sum['uiComponentMin'] if c_sum['uiComponentMin'] is not None else 4.5),
                'violations_count': int(cw_in.get('violations_count', c_sum['violationsCount'])),
                'unverifiable_count': contrast_unverifiable,
            },
        },
        'evidence': {
            'measured_checks': measured_checks,
            'not_applicable_checks': not_applicable_checks,
            'unverifiable_checks': unverifiable_checks,
            'unverifiable_reasons': unverifiable_reasons,
        },
        **({'elements': elements} if elements else {}),
    }


def bind_ui_environment(ctx: Any, manifest_path: str | Path, raw_env_override: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(raw_env_override, Mapping):
        for k in raw_env_override:
            if k not in ALLOWED_DRIFT_ENV_KEYS:
                raise ValueError(f'unsupported DRIFT_ENV key "{k}"; bind UI rendering environment via config manifest and record_input')
    if not manifest_path:
        raise ValueError('bind_ui_environment requires a non-empty manifest path')
    p_str = str(manifest_path)
    content = ctx.read_fixture(p_str) if ctx is not None and hasattr(ctx, 'read_fixture') else Path(p_str).read_text(encoding='utf-8')
    parsed = json.loads(content)
    if not isinstance(parsed, Mapping) or (not parsed.get('platform') and not parsed.get('browser')):
        raise ValueError(f'invalid UI environment manifest "{p_str}": missing platform/browser')
    norm = content.replace('\r\n', '\n').encode('utf-8')
    digest = f'sha256:{hashlib.sha256(norm).hexdigest()}'
    ref = f"fixture:{Path(p_str).as_posix()}@{digest}"
    if ctx is not None and hasattr(ctx, 'record_input'):
        ctx.record_input(p_str)
    import os
    raw_e = os.environ.get('DRIFT_ENV', '').strip()
    cur_e = json.loads(raw_e) if raw_e else {}
    os.environ['DRIFT_PROOF_KEY'] = '1'
    os.environ['DRIFT_ENV'] = json.dumps({**cur_e, 'config': ref}, separators=(',', ':'))
    return {'config': ref, 'environment_ref': ref, 'manifest': parsed}


def adapt_playwright_surface(raw: Mapping[str, Any]) -> dict[str, Any]:
    return observe_ui_sequence(raw)


def adapt_compose_semantics(raw: Mapping[str, Any]) -> dict[str, Any]:
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
    return observe_ui_sequence({
        'surface_found': raw.get('surfaceFound') is not False,
        'adapter': raw.get('adapter') or {'name': 'compose-semantics'},
        'environment_ref': raw.get('environment_ref'),
        'roles': roles,
        'before': raw.get('before'),
        'action': raw.get('action'),
        'transition': raw.get('transition'),
        'after': raw.get('after'),
        'documentWidth': float(raw.get('viewportWidthDp', 412)),
        'viewportWidth': float(raw.get('viewportWidthDp', 412)),
    })


def adapt_uia_snapshot(raw: Mapping[str, Any]) -> dict[str, Any]:
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
    return observe_ui_sequence({
        'surface_found': raw.get('surfaceFound') is not False,
        'adapter': raw.get('adapter') or {'name': 'windows-uia'},
        'environment_ref': raw.get('environment_ref'),
        'roles': roles,
        'before': raw.get('before'),
        'action': raw.get('action'),
        'transition': raw.get('transition'),
        'after': raw.get('after'),
        'documentWidth': float(raw.get('windowWidthDip', 1280)),
        'viewportWidth': float(raw.get('windowWidthDip', 1280)),
    })


def check_required_adapter_capability(contract_id: str, case_id: str, key: str, view: Mapping[str, Any], proj: Mapping[str, str] | None) -> None:
    adapter = view.get('adapter') if isinstance(view, Mapping) else None
    caps = adapter.get('capabilities') if isinstance(adapter, Mapping) else None
    if not isinstance(caps, list):
        return
    ptr = proj.get(key, '') if isinstance(proj, Mapping) else ''
    leaf = [seg for seg in ptr.split('/') if seg][-1] if ptr else ''
    req_cap = PREDICATE_CAPABILITY.get(key) or PREDICATE_CAPABILITY.get(leaf)
    if req_cap and req_cap not in caps:
        ev = view.get('evidence') if isinstance(view, Mapping) else None
        if isinstance(ev, dict) and isinstance(ev.get('unverifiable_checks'), int):
            ev['unverifiable_checks'] += 1
        raise AssertionError(f'{contract_id}.{case_id}: ui.capability_unverifiable:{req_cap} for then.{key}')
