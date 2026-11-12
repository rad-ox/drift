module drift_v

import x.json2

fn required_ui_capability_for(pred string, ptr string) string {
	for k in [pred, ptr.all_after_last('/')] {
		match k {
			'min_contrast_ratio', 'min_contrast_wcag22', 'min_contrast_text_normal',
			'min_contrast_text_large', 'min_contrast_ui_component', 'contrast_violations_count' {
				return 'wcag22_contrast'
			}
			'assistive_announcement', 'active_assistive_focus' {
				return 'assistive_focus'
			}
			'observed_transition_ms', 'max_transition_ms', 'observed_duration_ms' {
				return 'observed_transition'
			}
			'scroll_context_preserved' {
				return 'scroll_state'
			}
			'horizontal_overflow_px', 'min_target_px', 'clipped_elements',
			'unintentional_clipped_count', 'obscured_focus_elements', 'fully_obscured_focus_count',
			'partially_obscured_focus_count', 'notice_precedes_detail' {
				return 'geometry'
			}
			'after_focus_role', 'active_focus', 'trigger_restored', 'unexpected_focus_steals',
			'input_focus_role' {
				return 'input_focus'
			}
			else {}
		}
	}
	return ''
}

fn check_ui_projection_guards(contract string, case_id string, doc json2.Any, proj_then map[string]string, then_map map[string]json2.Any) ! {
	dm := j_map(doc) or { return }
	is_ui_obs := (j_str(dm['schema'] or { json2.Any('') }) or { '' }) == 'drift.ui-observation/1'
	if !(j_bool(dm['surface_found'] or { json2.Any(true) }) or { true }) || !(j_bool(dm['surfaceFound'] or {
		json2.Any(true)
	}) or { true }) {
		return error('${contract}.${case_id}: surface.missing')
	}
	if is_ui_obs && !(j_bool(dm['surface_found'] or { json2.Any(false) }) or { false }) && !(j_bool(dm['surfaceFound'] or {
		json2.Any(false)
	}) or { false }) {
		return error('${contract}.${case_id}: surface.missing')
	}
	if coll := j_map(dm['collector'] or { json2.Null{} }) {
		if j_bool(coll['settle_timed_out'] or { json2.Any(false) }) or { false } {
			return error('${contract}.${case_id}: ui.settle_timeout')
		}
	}
	if ev := j_map(dm['evidence'] or { json2.Null{} }) {
		if (j_arr(ev['unverifiable_reasons'] or { json2.Null{} }) or { []json2.Any{} }).any(
			it is string && it.str() == 'ui.settle_timeout')
		{
			return error('${contract}.${case_id}: ui.settle_timeout')
		}
	}
	mut has_caps := false
	mut caps := map[string]bool{}
	if ad := j_map(dm['adapter'] or { json2.Null{} }) {
		if ca := j_arr(ad['capabilities'] or { json2.Null{} }) {
			has_caps = true
			for it in ca {
				if s := j_str(it) {
					caps[s] = true
				}
			}
		}
	}
	for pred, exp in then_map {
		ptr := proj_then[pred] or { '/' + escape_pointer(pred) }
		if has_caps {
			req_cap := required_ui_capability_for(pred, ptr)
			if req_cap != '' && req_cap !in caps {
				return error('${contract}.${case_id}: ui.capability_unverifiable:${req_cap} for then.${pred}')
			}
		}
		if is_ui_obs && exp !is json2.Null {
			if (resolve_pointer(doc, ptr) or { json2.Any(0) }) is json2.Null {
				return error('${contract}.${case_id}: unverifiable then.${pred}: unmeasured value at "${ptr}"')
			}
		}
	}
}
