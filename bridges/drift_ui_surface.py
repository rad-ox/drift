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
