module drift_v

import x.json2

fn required_ui_capability_for(pred string, ptr string) string {
	leaf := ptr.all_after_last('/')
	for k in [pred, leaf] {
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
	if doc !is map[string]json2.Any {
		return
	}
	dm := doc.as_map()
	if sf := dm['surface_found'] {
		if sf is bool && !sf {
			return error('${contract}.${case_id}: surface.missing')
		}
	}
	if sf2 := dm['surfaceFound'] {
		if sf2 is bool && !sf2 {
			return error('${contract}.${case_id}: surface.missing')
		}
	}
	mut has_caps := false
	mut caps := map[string]bool{}
	if ad_any := dm['adapter'] {
		if ad_any is map[string]json2.Any {
			if caps_any := ad_any['capabilities'] {
				if caps_any is []json2.Any {
					has_caps = true
					for c_item in caps_any {
						if c_item is string {
							caps[c_item] = true
						}
					}
				}
			}
		}
	}
	if !has_caps {
		return
	}
	for pred, _ in then_map {
		ptr := proj_then[pred] or { '/' + escape_pointer(pred) }
		req_cap := required_ui_capability_for(pred, ptr)
		if req_cap != '' && req_cap !in caps {
			return error('${contract}.${case_id}: ui.capability_unverifiable:${req_cap} for then.${pred}')
		}
	}
}
