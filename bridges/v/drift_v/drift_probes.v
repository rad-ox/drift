// Reusable observable behavioral probes for the DRIFT V bridge.
module drift_v

import x.json2

const default_volatile_keys = ['request_id', 'timestamp', 'trace_id', 'audit_id']!
const default_allowed_second_writes = ['AUDIT_LOG', 'audit_log', 'METRICS', 'metrics']!

pub fn has_key_recursive(val json2.Any, fk string, is_root bool) bool {
	if arr := j_arr(val) {
		return arr.any(has_key_recursive(it, fk, false))
	}
	m := j_map(val) or { return false }
	if fk in m {
		return true
	}
	for k, v in m {
		if is_root && k in ['_frame', '_when_env'] && fk != k && v is map[string]json2.Any {
			continue
		}
		if has_key_recursive(v, fk, false) {
			return true
		}
	}
	return false
}

fn (mut ctx DriftContext) unverified_or_error(case_id string, strict bool, reason string, detail string) !bool {
	ctx.read_keys[case_id] = map[string]bool{}
	return if strict { error('${ctx.contract_id}.${case_id}: ${reason}: ${detail}') } else { false }
}

fn is_non_neg_json_int(v json2.Any) ?i64 {
	if v is bool {
		return none
	}
	f := as_finite_f64(v) or { return none }
	return if f >= 0.0 && f == f64(i64(f)) { i64(f) } else { none }
}

fn parse_probe_map(mut ctx DriftContext, case_id string, obs_json string, unobs_code string, unobs_msg string) !(map[string]json2.Any, bool, bool) {
	_ := ctx.case_map(case_id)!
	doc := json2.decode[json2.Any](obs_json) or { return error('obs_json is not valid JSON') }
	m := j_map(doc) or {
		_ = ctx.unverified_or_error(case_id, true, unobs_code, 'expected JSON object')!
		return map[string]json2.Any{}, true, false
	}
	strict := j_bool(m['strict'] or { json2.Any(true) }) or { true }
	if !(j_bool(m['observed'] or { json2.Any(true) }) or { true }) {
		_ = ctx.unverified_or_error(case_id, strict, unobs_code, unobs_msg)!
		return m, strict, true
	}
	return m, strict, false
}

pub fn (mut ctx DriftContext) check_idempotency(case_id string, obs_json string) !bool {
	m, strict, skipped := parse_probe_map(mut ctx, case_id, obs_json, 'idempotency.unobserved',
		'collector reported unobserved state')!
	if skipped {
		return false
	}
	s1 := m['stateAfterFirst'] or { m['state_after_first'] or { json2.Null{} } }
	s2 := m['stateAfterSecond'] or { m['state_after_second'] or { json2.Null{} } }
	has_state := s1 !is json2.Null && s2 !is json2.Null
	sw_map := j_map(m['secondWrites'] or { m['second_writes'] or { json2.Null{} } })
	if !has_state && sw_map == none {
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
		return error('${pfx}: idempotency.domain_state_mutated')
	}
	if sw := sw_map {
		mut allowed2 := default_allowed_second_writes[..].clone()
		if raw_al := j_arr(m['allowedSecondWrites'] or { json2.Null{} }) {
			allowed2 = raw_al.filter(it is string).map(it.str())
		}
		for res, wv in sw {
			if res in allowed2 || res.all_before('#') in allowed2 {
				continue
			}
			cnt := if arr := j_arr(wv) { i64(arr.len) } else { is_non_neg_json_int(wv) or { -1 } }
			if cnt != 0 {
				return error('${pfx}: idempotency.duplicate_write on resource "${res}"')
			}
		}
	}
	if f1 := j_map(m['first'] or { json2.Null{} }) {
		if f2 := j_map(m['second'] or { json2.Null{} }) {
			for k, v1 in f1 {
				if k !in default_volatile_keys && k != '_frame' {
					if v2 := f2[k] {
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
	m, strict, skipped := parse_probe_map(mut ctx, case_id, obs_json, 'seam.unobserved',
		'seam collector is unobserved')!
	if skipped {
		return false
	}
	has_retry := 'retryable' in m || 'maxAttempts' in m || 'max_attempts' in m
	has_timeout := j_bool(m['timedOut'] or { json2.Any(false) }) or { false }
	has_query := 'maxQueries' in m || 'max_queries' in m
	if !has_retry && !has_timeout && !has_query {
		return ctx.unverified_or_error(case_id, strict, 'seam.unobserved',
			'probe specifies neither retry, timeout, nor query bounds')
	}
	pfx := '${ctx.contract_id}.${case_id}'
	if has_retry {
		att := is_non_neg_json_int(m['attempts'] or { json2.Null{} }) or { -1 }
		if att <= 0 {
			return ctx.unverified_or_error(case_id, strict, 'seam.unobserved', 'missing attempts')
		}
		if r_v := j_bool(m['retryable'] or { json2.Null{} }) {
			if !r_v && att > 1 {
				return error('${pfx}: seam.non_retryable_retried')
			}
			if r_v && att < 2 {
				return error('${pfx}: seam.retry_missing')
			}
		}
		if ma_v := m['maxAttempts'] {
			ma := is_non_neg_json_int(ma_v) or { -1 }
			if ma < 0 || att > ma {
				return error('${pfx}: seam.max_attempts_exceeded')
			}
		}
	}
	if has_timeout {
		lw := is_non_neg_json_int(m['lateWrites'] or { json2.Any(0) }) or { -1 }
		if lw < 0 {
			return ctx.unverified_or_error(case_id, strict, 'seam.unobserved', 'invalid lateWrites')
		}
		if lw > 0 {
			return error('${pfx}: seam.timeout_late_write')
		}
	}
	if has_query {
		mq := is_non_neg_json_int(m['maxQueries'] or { m['max_queries'] or { json2.Null{} } }) or {
			-1
		}
		q := is_non_neg_json_int(m['queries'] or { json2.Null{} }) or { -1 }
		if q < 0 || mq < 0 {
			return ctx.unverified_or_error(case_id, strict, 'queries.unobserved', 'missing queries')
		}
		if q > mq {
			return error('${pfx}: seam.query_budget_exceeded')
		}
	}
	return true
}

pub fn (mut ctx DriftContext) check_rollback(case_id string, obs_json string) !bool {
	m, strict, skipped := parse_probe_map(mut ctx, case_id, obs_json, 'rollback.unobserved',
		'missing before/after snapshot on primary resource')!
	if skipped {
		return false
	}
	bef := m['before'] or { json2.Null{} }
	aft := m['after'] or { json2.Null{} }
	if 'before' !in m || 'after' !in m || bef is json2.Null || aft is json2.Null {
		return ctx.unverified_or_error(case_id, strict, 'rollback.unobserved', 'missing snapshots')
	}
	comp := j_bool(m['compensated'] or { json2.Any(false) }) or { false }
	res := j_str(m['resource'] or { json2.Any('primary') }) or { 'primary' }
	if !values_equal(bef, aft) && !comp {
		return error('${ctx.contract_id}.${case_id}: rollback.dirty_partial_write on "${res}"')
	}
	return true
}

pub fn check_bola_variant_pair(pfx string, v_doc json2.Any) !bool {
	vm := j_map(v_doc) or { return false }
	b := j_map(vm['bola'] or { json2.Null{} }) or { vm }
	if 'actor_owner' !in b && 'resource_owner' !in b {
		return false
	}
	actor := (j_str(b['actor_owner'] or { json2.Any('') }) or { '' }).trim_space()
	owner := (j_str(b['resource_owner'] or { json2.Any('') }) or { '' }).trim_space()
	if actor == '' || owner == '' || actor == owner {
		return error('${pfx}: bola.invalid_fixture')
	}
	return true
}

fn contains_str_leaf(val json2.Any, needle string) bool {
	return match val {
		string { val.contains(needle) }
		[]json2.Any { val.any(contains_str_leaf(it, needle)) }
		map[string]json2.Any { val.values().any(contains_str_leaf(it, needle)) }
		else { false }
	}
}

pub fn (mut ctx DriftContext) check_log_sink(case_id string, obs_json string) !bool {
	m, strict, skipped := parse_probe_map(mut ctx, case_id, obs_json, 'log_sink.unobserved',
		'log sink collector is unobserved')!
	if skipped {
		return false
	}
	secrets := (j_arr(m['secretValues'] or { m['secret_values'] or { json2.Null{} } }) or {
		[]json2.Any{}
	}).filter(it is string && it.str().trim_space() != '').map(it.str())
	logs := m['logLines'] or { m['log_lines'] or { json2.Null{} } }
	has_logs := logs is string || logs is []json2.Any
	payload := m['payload'] or { json2.Null{} }
	has_payload := 'payload' in m && payload !is json2.Null
	if secrets.len == 0 || (!has_logs && !has_payload) {
		return ctx.unverified_or_error(case_id, strict, 'log_sink.unobserved',
			'missing secretValues')
	}
	for s in secrets {
		if (has_logs && contains_str_leaf(logs, s))
			|| (has_payload && contains_str_leaf(payload, s)) {
			return error('${ctx.contract_id}.${case_id}: log_sink.secret_leaked')
		}
	}
	return true
}
