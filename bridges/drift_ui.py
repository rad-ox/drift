"""Cross-platform UI surface, interaction sequence, and adapter normalization for DRIFT."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

try:
    from . import drift_ui_recovery as _uir
except ImportError:
    try:
        import drift_ui_recovery as _uir  # type: ignore[no-redef]
    except ImportError:
        _uir_spec = importlib.util.spec_from_file_location('drift_ui_recovery', Path(__file__).with_name('drift_ui_recovery.py'))
        assert _uir_spec is not None and _uir_spec.loader is not None
        _uir = importlib.util.module_from_spec(_uir_spec)
        _uir_spec.loader.exec_module(_uir)

ALLOWED_DRIFT_ENV_KEYS = frozenset(('adapter', 'config', 'deps', 'drift', 'policy', 'runner', 'toolchain'))
DEFAULT_CAPS = ('geometry', 'input_focus', 'assistive_focus', 'wcag22_contrast', 'observed_transition', 'scroll_state')
PREDICATE_CAPABILITY: dict[str, str] = {
    **dict.fromkeys(('min_contrast_ratio', 'min_contrast_wcag22', 'min_contrast_text_normal', 'min_contrast_text_large', 'min_contrast_ui_component', 'contrast_violations_count'), 'wcag22_contrast'),
    **dict.fromkeys(('assistive_announcement', 'active_assistive_focus'), 'assistive_focus'),
    **dict.fromkeys(('observed_transition_ms', 'max_transition_ms'), 'observed_transition'),
    'scroll_context_preserved': 'scroll_state',
    **dict.fromkeys(('horizontal_overflow_px', 'min_target_px', 'clipped_elements', 'unintentional_clipped_count', 'obscured_focus_elements', 'fully_obscured_focus_count', 'partially_obscured_focus_count', 'notice_precedes_detail'), 'geometry'),
    **dict.fromkeys(('after_focus_role', 'active_focus', 'trigger_restored', 'unexpected_focus_steals'), 'input_focus'),
}


def _is_fin_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _num_or_none(v: Any) -> int | float | None:
    if not _is_fin_num(v):
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def _bool_or(v: Any, fb: bool | None) -> bool | None:
    return v if isinstance(v, bool) else fb


def _opt_surface_flag(raw: Mapping[str, Any]) -> dict[str, bool]:
    if 'surfaceFound' in raw:
        return {'surface_found': bool(raw['surfaceFound'])}
    return {'surface_found': bool(raw['surface_found'])} if 'surface_found' in raw else {}


def is_element_hidden(el: Any) -> bool:
    if not isinstance(el, Mapping):
        return False
    pres = str(el.get('presence') or el.get('state') or '').strip().lower()
    if pres in ('hidden', 'absent', 'collapsed') or el.get('hidden') is True or el.get('ariaHidden') is True or el.get('aria-hidden') == 'true':
        return True
    style = el.get('style') if isinstance(el.get('style'), Mapping) else {}
    return str(el.get('display') or style.get('display') or '').strip().lower() == 'none' or str(el.get('visibility') or style.get('visibility') or '').strip().lower() in ('hidden', 'collapse')


def is_element_scrollable(el: Any, axis: str = 'both') -> bool:
    if not isinstance(el, Mapping):
        return False
    if isinstance(el.get('scrollable'), bool):
        return bool(el['scrollable'])
    style = el.get('style') if isinstance(el.get('style'), Mapping) else {}
    ox = str(el.get('overflowX') or style.get('overflowX') or el.get('overflow') or style.get('overflow') or '').strip().lower()
    oy = str(el.get('overflowY') or style.get('overflowY') or el.get('overflow') or style.get('overflow') or '').strip().lower()
    sx = ox in ('auto', 'scroll') or el.get('horizontallyScrollable') is True
    sy = oy in ('auto', 'scroll') or el.get('verticallyScrollable') is True
    return sx if axis == 'x' else (sy if axis == 'y' else (sx or sy))


def evaluate_element_clipping(el: Any) -> dict[str, Any]:
    if not isinstance(el, Mapping) or is_element_hidden(el):
        return {'clipped': False, 'scrollable': False, 'status': 'not_applicable'}
    sw, cw = float(el.get('scrollWidth') or 0.0), float(el.get('clientWidth') or 0.0)
    sh, ch = float(el.get('scrollHeight') or 0.0), float(el.get('clientHeight') or 0.0)
    sx, sy = is_element_scrollable(el, 'x'), is_element_scrollable(el, 'y')
    return {'clipped': (sw > cw and not sx) or (sh > ch and not sy), 'scrollable': sx or sy, 'status': 'measured'}


def evaluate_focus_obscuration(el: Any) -> dict[str, Any]:
    if not isinstance(el, Mapping) or is_element_hidden(el) or el.get('focusable') is False:
        return {'fullyObscured': False, 'partiallyObscured': False, 'status': 'not_applicable'}
    if isinstance(el.get('fullyObscured'), bool) or isinstance(el.get('partiallyObscured'), bool):
        full = bool(el.get('fullyObscured'))
        return {'fullyObscured': full, 'partiallyObscured': bool(el.get('partiallyObscured') or full), 'status': 'measured'}
    pts = el.get('hitPoints')
    if isinstance(pts, list) and pts:
        cov = sum(1 for p in pts if p is True or (isinstance(p, Mapping) and p.get('covered') is True))
        return {'fullyObscured': cov == len(pts), 'partiallyObscured': cov > 0, 'status': 'measured'}
    overlays = el.get('visualOverlays') if isinstance(el.get('visualOverlays'), list) else []
    rect = el.get('rect') if isinstance(el.get('rect'), Mapping) else el
    w, h = float(el.get('width', rect.get('width', 0)) or 0), float(el.get('height', rect.get('height', 0)) or 0)
    if w > 0 and h > 0 and overlays:
        left, top = float(rect.get('left', rect.get('x', 0)) or 0), float(rect.get('top', rect.get('y', 0)) or 0)
        ix, iy = min(2.0, w / 4.0), min(2.0, h / 4.0)
        sample_pts = ((left + w / 2.0, top + h / 2.0), (left + ix, top + iy), (left + w - ix, top + iy), (left + ix, top + h - iy), (left + w - ix, top + h - iy))
        cov = sum(1 for px, py in sample_pts if _uir.is_point_covered_by_visual_overlays(px, py, el, overlays))
        return {'fullyObscured': cov == len(sample_pts), 'partiallyObscured': cov > 0, 'status': 'measured'}
    if 'obscured' in el or 'focusObscured' in el:
        obs = bool(el.get('obscured') is True or el.get('focusObscured') is True)
        return {'fullyObscured': obs, 'partiallyObscured': obs, 'status': 'measured'}
    return {'fullyObscured': False, 'partiallyObscured': False, 'status': 'unverifiable'}


def evaluate_wcag22_contrast(elements: Any) -> dict[str, Any]:
    tn, tl, uc, ov = math.inf, math.inf, math.inf, math.inf
    violations = unverifiable = measured = 0
    for el in elements if isinstance(elements, list) else ():
        if not isinstance(el, Mapping) or is_element_hidden(el):
            continue
        if el.get('contrastUnverifiable') is True or el.get('backgroundUnverifiable') is True:
            unverifiable += 1
            continue
        ratio = el.get('contrastRatio', el.get('contrast_ratio'))
        if not _is_fin_num(ratio):
            continue
        r_val = float(ratio)
        measured += 1
        ov = min(ov, r_val)
        cat = str(el.get('contrastCategory') or el.get('category') or 'text_normal').strip().lower()
        if cat == 'text_large':
            tl = min(tl, r_val)
        elif cat == 'ui_component':
            uc = min(uc, r_val)
        else:
            tn = min(tn, r_val)
        if r_val + 1e-9 < (3.0 if cat in ('text_large', 'ui_component') else 4.5):
            violations += 1
    return {
        'measuredCount': measured,
        'overallMin': ov if math.isfinite(ov) else None,
        'textNormalMin': tn if math.isfinite(tn) else None,
        'textLargeMin': tl if math.isfinite(tl) else None,
        'uiComponentMin': uc if math.isfinite(uc) else None,
        'violationsCount': violations,
        'unverifiableCount': unverifiable,
    }


def derive_non_color_cue(node: Any) -> dict[str, bool]:
    if not isinstance(node, Mapping):
        return {'has_visible_text': False, 'has_graphic_icon': False, 'has_semantic_role': False, 'non_color_encoded': False}
    cues = node.get('content_cues')
    role = str(node.get('semantic_role') or node.get('role') or '').strip().lower()
    if isinstance(cues, Mapping):
        ht, hi = bool(cues.get('has_visible_text')), bool(cues.get('has_graphic_icon'))
        hs = bool(cues.get('has_semantic_role', role in ('alert', 'alertdialog', 'status')))
        return {'has_visible_text': ht, 'has_graphic_icon': hi, 'has_semantic_role': hs, 'non_color_encoded': ht and (hi or hs)}
    ht = bool(str(node.get('text') or node.get('textContent') or node.get('label') or '').strip()) and not is_element_hidden(node)
    children = node.get('children') if isinstance(node.get('children'), list) else []
    hi = bool(node.get('hasIcon') is True or node.get('icon') is True or any(isinstance(c, Mapping) and not is_element_hidden(c) and (str(c.get('tagName') or '').upper() == 'SVG' or str(c.get('role') or '').lower() == 'img' or bool(c.get('isIcon'))) for c in children))
    hs = role in ('alert', 'alertdialog', 'status')
    return {'has_visible_text': ht, 'has_graphic_icon': hi, 'has_semantic_role': hs, 'non_color_encoded': ht and (hi or hs)}


def observe_ui_sequence(spec: Mapping[str, Any] | None) -> dict[str, Any]:
    s = dict(spec) if isinstance(spec, Mapping) else {}
    raw_roles = s.get('roles') if isinstance(s.get('roles'), Mapping) else {}
    elements = s.get('elements') if isinstance(s.get('elements'), list) else []
    has_explicit_missing = s.get('surface_found') is False or s.get('surfaceFound') is False
    has_roles_or_elements = bool(raw_roles) or bool(elements)
    surface_found = not has_explicit_missing and has_roles_or_elements
    adapter_raw = s.get('adapter')
    adapter_name = str(adapter_raw.get('name') if isinstance(adapter_raw, Mapping) else (adapter_raw or 'playwright-web'))
    caps_raw = (adapter_raw.get('capabilities') if isinstance(adapter_raw, Mapping) else None) or s.get('capabilities')
    explicit_caps = list(caps_raw) if isinstance(caps_raw, list) else None

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
            w = _num_or_none((geom or {}).get('width', r.get('width'))) or -1.0
            h = _num_or_none((geom or {}).get('height', r.get('height'))) or -1.0
            if not (w > 0 and h > 0):
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

    configured_ms = _num_or_none(trans_raw.get('configured_duration_ms', trans_raw.get('configuredDurationMs')))
    observed_ms = _num_or_none(trans_raw.get('observed_duration_ms', trans_raw.get('observedDurationMs')))
    raw_ft = trans_raw.get('focus_trace', trans_raw.get('focusTrace'))
    focus_trace = list(raw_ft) if isinstance(raw_ft, list) else []

    notice_role = roles.get('notice') or {}
    detail_role = roles.get('detail') or {}
    summary_role = roles.get('summary') or {}
    notice_sem = str(notice_role.get('semantic_role') or notice_role.get('role') or '').strip().lower()

    after_focus = str(after_raw.get('input_focus_role') or after_raw.get('inputFocusRole') or '')
    before_focus = str(before.get('input_focus_role') or before.get('inputFocusRole') or '')
    raw_steals = trans_raw.get('unexpected_focus_steals', trans_raw.get('unexpectedFocusSteals'))
    has_focus_obs = _is_fin_num(raw_steals) or isinstance(raw_ft, list) or bool(after_focus or before_focus)
    unexpected_steals: int | None = int(raw_steals) if _is_fin_num(raw_steals) else (0 if has_focus_obs else None)
    if notice_role.get('presence') == 'visible' and notice_sem == 'alert' and ('notice' in focus_trace or after_focus == 'notice'):
        unexpected_steals = (unexpected_steals or 0) + 1

    sel_before = before.get('selected_entity_id', before.get('selectedEntityId'))
    sel_after = after_raw.get('selected_entity_id', after_raw.get('selectedEntityId', summary_role.get('selected_entity_id')))
    sel_preserved = _bool_or(after_raw.get('selection_preserved'), sel_before == sel_after if sel_before is not None and sel_after is not None else None)

    dirty_before = before.get('dirty_inputs') if isinstance(before.get('dirty_inputs'), Mapping) else (before.get('dirtyInputs') if isinstance(before.get('dirtyInputs'), Mapping) else None)
    dirty_after = after_raw.get('dirty_inputs') if isinstance(after_raw.get('dirty_inputs'), Mapping) else (after_raw.get('dirtyInputs') if isinstance(after_raw.get('dirtyInputs'), Mapping) else None)
    dirty_preserved = _bool_or(after_raw.get('dirty_inputs_preserved'), dirty_before == dirty_after if dirty_before is not None and dirty_after is not None else None)

    anchor_before = before.get('scroll_anchor_id', before.get('scrollAnchorId'))
    anchor_after = after_raw.get('scroll_anchor_id', after_raw.get('scrollAnchorId'))
    scroll_delta = float(after_raw.get('scroll_offset_delta') or 0.0)
    scroll_preserved = _bool_or(after_raw.get('scroll_context_preserved'), anchor_before == anchor_after and abs(scroll_delta) <= 2.0 if anchor_before is not None and anchor_after is not None else None)
    trigger_restored = _bool_or(after_raw.get('trigger_restored'), after_focus == before_focus if before_focus and after_focus else None)
    notice_precedes = _bool_or(after_raw.get('notice_precedes_detail'), None)
    if notice_role.get('presence') == 'visible' and detail_role.get('presence') == 'visible':
        n_geom = notice_role.get('geometry') if isinstance(notice_role.get('geometry'), Mapping) else {}
        d_geom = detail_role.get('geometry') if isinstance(detail_role.get('geometry'), Mapping) else {}
        if _is_fin_num(n_geom.get('reading_order_rank')) and _is_fin_num(d_geom.get('reading_order_rank')):
            notice_precedes = float(n_geom['reading_order_rank']) < float(d_geom['reading_order_rank'])
        elif _is_fin_num(n_geom.get('y')) and _is_fin_num(d_geom.get('y')):
            notice_precedes = float(n_geom['y']) < float(d_geom['y'])

    detail_matches = _bool_or(
        after_raw.get('detail_matches_selection'),
        detail_role.get('bound_entity_id') == sel_after if detail_role.get('presence') == 'visible' and detail_role.get('bound_entity_id') is not None and sel_after is not None else None,
    )

    c_sum = evaluate_wcag22_contrast(elements)
    pres_in = s.get('presentation') if isinstance(s.get('presentation'), Mapping) else {}
    clip_in = pres_in.get('clipping') if isinstance(pres_in.get('clipping'), Mapping) else {}
    foc_in = pres_in.get('focus_visibility') if isinstance(pres_in.get('focus_visibility'), Mapping) else {}
    cw_in = pres_in.get('contrast_wcag22') if isinstance(pres_in.get('contrast_wcag22'), Mapping) else {}

    unintentional_clipped = int(clip_in['unintentional_clipped_count']) if _is_fin_num(clip_in.get('unintentional_clipped_count')) else None
    scrollable_containers = int(clip_in['scrollable_containers_count']) if _is_fin_num(clip_in.get('scrollable_containers_count')) else None
    if elements and unintentional_clipped is None and scrollable_containers is None:
        unintentional_clipped = sum(1 for el in elements if evaluate_element_clipping(el)['clipped'])
        scrollable_containers = sum(1 for el in elements if evaluate_element_clipping(el)['scrollable'])

    fully_obscured = int(foc_in['fully_obscured_count']) if _is_fin_num(foc_in.get('fully_obscured_count')) else None
    partially_obscured = int(foc_in['partially_obscured_count']) if _is_fin_num(foc_in.get('partially_obscured_count')) else None
    if elements and fully_obscured is None and partially_obscured is None:
        m_evals = [r for r in (evaluate_focus_obscuration(el) for el in elements) if r['status'] == 'measured']
        if m_evals:
            fully_obscured = sum(1 for r in m_evals if r['fullyObscured'])
            partially_obscured = sum(1 for r in m_evals if r['partiallyObscured'])

    contrast_unverifiable = int(cw_in.get('unverifiable_count', c_sum['unverifiableCount']))
    if contrast_unverifiable > 0:
        unverifiable_checks += contrast_unverifiable
        unverifiable_reasons.append(f'contrast_unverifiable:{contrast_unverifiable}')
    if surface_found and measured_checks == 0 and c_sum['measuredCount'] == 0:
        unverifiable_checks += 1
        unverifiable_reasons.append('ui.unmeasured_surface')

    has_vp_dims = _is_fin_num(s.get('documentWidth')) and _is_fin_num(s.get('viewportWidth')) and float(s['viewportWidth']) > 0
    horiz_ov = float(pres_in['horizontal_overflow_px']) if _is_fin_num(pres_in.get('horizontal_overflow_px')) else (
        max(0.0, float(s['documentWidth']) - float(s['viewportWidth'])) if has_vp_dims else None
    )
    recovery = _uir.evaluate_task_recovery(s, before, after_raw)
    capabilities = explicit_caps if explicit_caps is not None else _uir.derive_observed_capabilities(
        s, raw_roles, elements, before, trans_raw, after_raw, c_sum
    )

    return {
        'schema': 'drift.ui-observation/1', 'surface_found': surface_found, 'surfaceFound': surface_found,
        'adapter': {'name': adapter_name, 'capabilities': capabilities},
        **({'environment_ref': s['environment_ref']} if s.get('environment_ref') else {}),
        'roles': roles,
        'sequence': {
            'before': {**before, **({'input_focus_role': before_focus} if before_focus else {}), **({'selected_entity_id': sel_before} if sel_before is not None else {}), **({'scroll_anchor_id': anchor_before} if anchor_before is not None else {}), **({'dirty_inputs': dirty_before} if isinstance(dirty_before, Mapping) else {})},
            'action': action,
            'transition': {'configured_duration_ms': configured_ms, 'observed_duration_ms': observed_ms, 'unexpected_focus_steals': unexpected_steals},
            'after': {**after_raw, 'input_focus_role': after_focus, 'selection_preserved': sel_preserved, 'dirty_inputs_preserved': dirty_preserved, 'scroll_context_preserved': scroll_preserved, 'trigger_restored': trigger_restored, 'notice_precedes_detail': notice_precedes, 'detail_matches_selection': detail_matches, **recovery},
        },
        'presentation': {
            'horizontal_overflow_px': horiz_ov,
            'clipping': {'unintentional_clipped_count': unintentional_clipped, 'scrollable_containers_count': scrollable_containers},
            'focus_visibility': {'fully_obscured_count': fully_obscured, 'partially_obscured_count': partially_obscured},
            'contrast_wcag22': {
                'text_normal_min': float(cw_in['text_normal_min']) if _is_fin_num(cw_in.get('text_normal_min')) else c_sum['textNormalMin'],
                'text_large_min': float(cw_in['text_large_min']) if _is_fin_num(cw_in.get('text_large_min')) else c_sum['textLargeMin'],
                'ui_component_min': float(cw_in['ui_component_min']) if _is_fin_num(cw_in.get('ui_component_min')) else c_sum['uiComponentMin'],
                'violations_count': int(cw_in['violations_count']) if _is_fin_num(cw_in.get('violations_count')) else (c_sum['violationsCount'] if c_sum['measuredCount'] > 0 else None),
                'unverifiable_count': contrast_unverifiable,
            },
        },
        'evidence': {'measured_checks': measured_checks, 'not_applicable_checks': not_applicable_checks, 'unverifiable_checks': unverifiable_checks, 'unverifiable_reasons': unverifiable_reasons},
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
    return observe_ui_sequence(_uir.build_compose_payload(raw))


def adapt_uia_snapshot(raw: Mapping[str, Any]) -> dict[str, Any]:
    return observe_ui_sequence(_uir.build_uia_payload(raw))


def check_required_adapter_capability(contract_id: str, case_id: str, key: str, view: Mapping[str, Any], proj: Mapping[str, str] | None) -> None:
    if isinstance(view, Mapping):
        coll = view.get('collector') if isinstance(view.get('collector'), Mapping) else {}
        ev_r = (view.get('evidence') if isinstance(view.get('evidence'), Mapping) else {}).get('unverifiable_reasons')
        if coll.get('settle_timed_out') is True or (isinstance(ev_r, list) and 'ui.settle_timeout' in ev_r):
            raise AssertionError(f'{contract_id}.{case_id}: ui.settle_timeout')
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
