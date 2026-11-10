module drift_v

import x.json2

fn parity_check(expected string, actual string, context string) bool {
	raw := json2.decode[json2.Any](expected) or { return false }
	act := json2.decode[json2.Any](actual) or { return false }
	doc := json2.decode[json2.Any](context) or { return false }
	check_relational_leaf(doc, act, raw.as_map(), map[string]string{}, 'value') or { return false }
	return true
}

fn test_conversion_uses_schema_or_unique_ratio() {
	raw := '{"eq":2000,"min":1000,"max":3000,"in":[2000,"opaque"],"not_in":[1000],"tol":{"abs":10},"convert_from":"ms"}'
	context := '{"units":{"ms->s":0.001,"ms->us":1000},"schema":{"then":{"value":{"unit":"s"}}}}'
	assert parity_check(raw, '2', context)
	assert !parity_check(raw, '2000', context)
	assert parity_check('{"min":1000,"convert_from":"ms"}', '2', '{"units":{"ms->s":0.001}}')
	assert !parity_check('{"min":1000,"convert_from":"ms"}', '2',
		'{"units":{"ms->s":0.001,"ms->us":1000}}')
	assert parity_check('{"series":{"sum_total":3000,"step_max_delta":1000},"convert_from":"ms"}',
		'[1,2]', context)
}

fn test_keys_conjoin_eq_lengths_and_membership() {
	assert parity_check('{"keys":{"allow":["a"],"forbid":["secret"]},"eq":{"a":1},"len":{"min":1,"max":1},"in":[{"a":1}]}',
		'{"a":1}', '{}')
	for raw in [
		'{"keys":{"allow":["a"]},"eq":{"a":2}}',
		'{"allowed_keys":["a"],"min_len":2}',
		'{"allowed_keys":["a"],"not_in":[{"a":1}]}',
		'{"allowed_keys":["b"]}',
	] {
		assert !parity_check(raw, '{"a":1}', '{}')
	}
}

fn test_contains_unicode_and_empty_maps() {
	for raw in ['{"contains":"😀","len":{"min":3,"max":3}}', '{"contains":["😀","b"]}'] {
		assert parity_check(raw, '"a😀b"', '{}')
	}
	for raw in ['{"contains":2}', '{"contains":[1,2]}'] {
		assert parity_check(raw, '[1,2,3]', '{}')
	}
	assert !parity_check('{"contains":["missing"]}', '"a😀b"', '{}')
	assert parity_check('{"non_empty":false}', '{}', '{}')
	assert !parity_check('{"non_empty":false}', '{"a":1}', '{}')
}
