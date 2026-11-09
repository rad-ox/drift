// Reusable observable behavioral probes for the DRIFT V bridge.
module drift_v

import x.json2

const default_volatile_keys = ['request_id', 'timestamp', 'trace_id', 'audit_id']!
const default_allowed_second_writes = ['AUDIT_LOG', 'audit_log', 'METRICS', 'metrics']!

pub fn has_key_recursive(val json2.Any, fk string, is_root bool) bool {
	if val is []json2.Any {
		for item in val {
			if has_key_recursive(item, fk, false) {
				return true
			}
		}
		return false
	}
	if val !is map[string]json2.Any {
		return false
	}
	m := val.as_map()
	if fk in m {
		return true
	}
	for k, v in m {
		if is_root && k == '_frame' && fk != '_frame' && v is map[string]json2.Any {
			continue
		}
		if has_key_recursive(v, fk, false) {
			return true
		}
	}
	return false
}

fn (mut ctx DriftContext) clear_case_reads(case_id string) {
	ctx.read_keys[case_id] = map[string]bool{}
}

fn (mut ctx DriftContext) unverified_or_error(case_id string, strict bool, reason string, detail string) !bool {
	ctx.clear_case_reads(case_id)
	if strict {
		return error('${ctx.contract_id}.${case_id}: ${reason}: ${detail}')
	}
	return false
}

fn is_non_neg_json_int(v json2.Any) ?i64 {
	if v is bool {
		return none
	}
	f := as_finite_f64(v) or { return none }
	if f < 0.0 || f != f64(i64(f)) {
		return none
	}
	return i64(f)
}

pub fn (mut ctx DriftContext) check_idempotency(case_id string, obs_json string) !bool {
	_ := ctx.case_map(case_id)!
	doc := json2.decode[json2.Any](obs_json) or { return error('obs_json is not valid JSON') }
	if doc !is map[string]json2.Any {
		return ctx.unverified_or_error(case_id, true, 'idempotency.unobserved',
			'expected JSON object')
	}
	m := doc.as_map()
	strict := if st := m['strict'] { !(st is bool && !(st as bool)) } else { true }
	if ob := m['observed'] {
		if ob is bool && !(ob as bool) {
			return ctx.unverified_or_error(case_id, strict, 'idempotency.unobserved',
				'collector reported unobserved state')
		}
	}
	s1 := m['stateAfterFirst'] or { m['state_after_first'] or { json2.Null{} } }
	s2 := m['stateAfterSecond'] or { m['state_after_second'] or { json2.Null{} } }
	has_state := s1 !is json2.Null && s2 !is json2.Null
	sw_any := m['secondWrites'] or { m['second_writes'] or { json2.Null{} } }
	has_sw := sw_any is map[string]json2.Any
	if !has_state && !has_sw {
		return ctx.unverified_or_error(case_id, strict, 'idempotency.unobserved',
			'missing state snapshots and secondWrites observations')
	}
	if first_any := m['first'] {
		if first_any !is json2.Null {
			ctx.check_projection(case_id, first_any.json_str())!
		}
	}
	pfx := '${ctx.contract_id}.${case_id}'
	if has_state && !values_equal(s1, s2) {
		return error('${pfx}: idempotency.domain_state_mutated: stateAfterFirst and stateAfterSecond differ')
	}
	if has_sw {
		mut allowed2 := map[string]bool{}
		for a in default_allowed_second_writes {
			allowed2[a] = true
		}
		if raw_al := m['allowedSecondWrites'] {
			if raw_al is []json2.Any {
				allowed2 = map[string]bool{}
				for item in raw_al {
					if item is string {
						allowed2[item] = true
					}
				}
			}
		}
		for res, wv in sw_any.as_map() {
			base := res.all_before('#')
			if res in allowed2 || base in allowed2 {
				continue
			}
			cnt := if wv is []json2.Any {
				i64(wv.len)
			} else {
				is_non_neg_json_int(wv) or { -1 }
			}
			if cnt < 0 || cnt > 0 {
				return error('${pfx}: idempotency.duplicate_write on resource "${res}": expected 0 writes on replay, observed ${cnt}')
			}
		}
	}
	if first_any := m['first'] {
		if second_any := m['second'] {
			if first_any is map[string]json2.Any && second_any is map[string]json2.Any {
				for k, v1 in first_any {
					if k in default_volatile_keys || k == '_frame' {
						continue
					}
					if v2 := second_any[k] {
						if !values_equal(v1, v2) {
							return error('${pfx}: idempotency.response_diverged on key "${k}"')
						}
					}
				}
			}
		}
	}
	return true
}

pub fn (mut ctx DriftContext) check_seam_probe(case_id string, obs_json string) !bool {
	_ := ctx.case_map(case_id)!
	doc := json2.decode[json2.Any](obs_json) or { return error('obs_json is not valid JSON') }
	if doc !is map[string]json2.Any {
		return ctx.unverified_or_error(case_id, true, 'seam.unobserved', 'expected JSON object')
	}
	m := doc.as_map()
	strict := if st := m['strict'] { !(st is bool && !(st as bool)) } else { true }
	if ob := m['observed'] {
		if ob is bool && !(ob as bool) {
			return ctx.unverified_or_error(case_id, strict, 'seam.unobserved',
				'seam collector is unobserved')
		}
	}
	has_retry := 'retryable' in m || 'maxAttempts' in m || 'max_attempts' in m
	has_timeout := if to_v := m['timedOut'] { to_v is bool && (to_v as bool) } else { false }
	has_query := 'maxQueries' in m || 'max_queries' in m
	if !has_retry && !has_timeout && !has_query {
		return ctx.unverified_or_error(case_id, strict, 'seam.unobserved',
			'probe specifies neither retry, timeout, nor query bounds')
	}
	pfx := '${ctx.contract_id}.${case_id}'
	if has_retry {
		att := is_non_neg_json_int(m['attempts'] or { json2.Null{} }) or { -1 }
		if att <= 0 {
			return ctx.unverified_or_error(case_id, strict, 'seam.unobserved',
				'missing positive attempts count from seam spy')
		}
		if r_v := m['retryable'] {
			if r_v is bool {
				if !(r_v as bool) && att > 1 {
					return error('${pfx}: seam.non_retryable_retried: expected 1 attempt on terminal fault, observed ${att}')
				}
				if (r_v as bool) && att < 2 {
					return error('${pfx}: seam.retry_missing: expected >= 2 attempts on transient fault, observed ${att}')
				}
			}
		}
		if ma_v := m['maxAttempts'] {
			ma := is_non_neg_json_int(ma_v) or { -1 }
			if ma < 0 || att > ma {
				return error('${pfx}: seam.max_attempts_exceeded: observed ${att} > maxAttempts ${ma}')
			}
		}
	}
	if has_timeout {
		lw := is_non_neg_json_int(m['lateWrites'] or { json2.Any(0) }) or { -1 }
		if lw < 0 {
			return ctx.unverified_or_error(case_id, strict, 'seam.unobserved',
				'invalid lateWrites observation')
		}
		if lw > 0 {
			return error('${pfx}: seam.timeout_late_write: expected 0 writes after timeout, observed ${lw}')
		}
	}
	if has_query {
		mq_raw := m['maxQueries'] or { m['max_queries'] or { json2.Null{} } }
		q := is_non_neg_json_int(m['queries'] or { json2.Null{} }) or { -1 }
		mq := is_non_neg_json_int(mq_raw) or { -1 }
		if q < 0 || mq < 0 {
			return ctx.unverified_or_error(case_id, strict, 'queries.unobserved',
				'missing non-negative queries count from SQL listener')
		}
		if q > mq {
			return error('${pfx}: seam.query_budget_exceeded: observed ${q} > maxQueries ${mq}')
		}
	}
	return true
}

pub fn (mut ctx DriftContext) check_rollback(case_id string, obs_json string) !bool {
	_ := ctx.case_map(case_id)!
	doc := json2.decode[json2.Any](obs_json) or { return error('obs_json is not valid JSON') }
	if doc !is map[string]json2.Any {
		return ctx.unverified_or_error(case_id, true, 'rollback.unobserved', 'expected JSON object')
	}
	m := doc.as_map()
	strict := if st := m['strict'] { !(st is bool && !(st as bool)) } else { true }
	if ob := m['observed'] {
		if ob is bool && !(ob as bool) {
			return ctx.unverified_or_error(case_id, strict, 'rollback.unobserved',
				'missing before/after snapshot on primary resource')
		}
	}
	bef := m['before'] or { json2.Null{} }
	aft := m['after'] or { json2.Null{} }
	if 'before' !in m || 'after' !in m || bef is json2.Null || aft is json2.Null {
		return ctx.unverified_or_error(case_id, strict, 'rollback.unobserved',
			'missing before/after snapshot on primary resource')
	}
	comp := if c_v := m['compensated'] { c_v is bool && (c_v as bool) } else { false }
	res := if r_v := m['resource'] {
		if r_v is string && r_v != '' { r_v } else { 'primary' }
	} else {
		'primary'
	}
	if !values_equal(bef, aft) && !comp {
		return error('${ctx.contract_id}.${case_id}: rollback.dirty_partial_write on "${res}": before and after snapshots differ after downstream failure')
	}
	return true
}

pub fn check_bola_variant_pair(pfx string, v_doc json2.Any) !bool {
	if v_doc !is map[string]json2.Any {
		return false
	}
	vm := v_doc.as_map()
	mut b := vm.clone()
	if sub := vm['bola'] {
		if sub is map[string]json2.Any {
			b = sub.clone()
		}
	}
	if 'actor_owner' !in b && 'resource_owner' !in b {
		return false
	}
	actor := if a_v := b['actor_owner'] {
		if a_v is string { a_v.trim_space() } else { '' }
	} else {
		''
	}
	owner := if o_v := b['resource_owner'] {
		if o_v is string { o_v.trim_space() } else { '' }
	} else {
		''
	}
	if actor == '' || owner == '' || actor == owner {
		return error('${pfx}: bola.invalid_fixture: cross-owner probe requires distinct non-empty actor_owner and resource_owner')
	}
	return true
}

fn contains_str_leaf(val json2.Any, needle string) bool {
	return match val {
		string {
			val.contains(needle)
		}
		[]json2.Any {
			val.any(contains_str_leaf(it, needle))
		}
		map[string]json2.Any {
			mut hit := false
			for _, v in val {
				if contains_str_leaf(v, needle) {
					hit = true
					break
				}
			}
			hit
		}
		else {
			false
		}
	}
}

pub fn (mut ctx DriftContext) check_log_sink(case_id string, obs_json string) !bool {
	_ := ctx.case_map(case_id)!
	doc := json2.decode[json2.Any](obs_json) or { return error('obs_json is not valid JSON') }
	if doc !is map[string]json2.Any {
		return ctx.unverified_or_error(case_id, true, 'log_sink.unobserved', 'expected JSON object')
	}
	m := doc.as_map()
	strict := if st := m['strict'] { !(st is bool && !(st as bool)) } else { true }
	if ob := m['observed'] {
		if ob is bool && !(ob as bool) {
			return ctx.unverified_or_error(case_id, strict, 'log_sink.unobserved',
				'log sink collector is unobserved')
		}
	}
	raw_sec := m['secretValues'] or { m['secret_values'] or { json2.Null{} } }
	mut secrets := []string{}
	if raw_sec is []json2.Any {
		for item in raw_sec {
			if item is string && item.trim_space() != '' {
				secrets << item
			}
		}
	}
	logs := m['logLines'] or { m['log_lines'] or { json2.Null{} } }
	has_logs := logs is string || logs is []json2.Any
	payload := m['payload'] or { json2.Null{} }
	has_payload := 'payload' in m && payload !is json2.Null
	if secrets.len == 0 || (!has_logs && !has_payload) {
		return ctx.unverified_or_error(case_id, strict, 'log_sink.unobserved',
			'missing secretValues or observed logLines/payload')
	}
	for s in secrets {
		if (has_logs && contains_str_leaf(logs, s))
			|| (has_payload && contains_str_leaf(payload, s)) {
			return error('${ctx.contract_id}.${case_id}: log_sink.secret_leaked: secret canary leaked in observed sink')
		}
	}
	return true
}
