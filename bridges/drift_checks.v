// Zero-dependency native V bridge projection, relational, and stub helpers (SPEC §§9, 25, D224, D245).
module drift_v

import math
import x.json2

const rel_keys = [
	'min',
	'max',
	'min_len',
	'max_len',
	'non_empty',
	'le_field',
	'ge_field',
	'eq_field',
	'in',
	'not_in',
	'contains',
	'prefix',
	'suffix',
	'sum_fields',
	'allowed_keys',
	'forbid_keys',
]!

pub fn escape_pointer(seg string) string {
	return seg.replace('~', '~0').replace('/', '~1')
}

pub fn unescape_pointer(seg string) string {
	return seg.replace('~1', '/').replace('~0', '~')
}

pub fn normalize_pointer(raw string) string {
	if raw == '' {
		return ''
	}
	if raw.starts_with('/') {
		colon := raw.index_u8(`:`)
		if colon > 1 && colon + 1 < raw.len && raw[colon + 1] == `/` {
			return raw[colon + 1..]
		}
		return raw
	}
	colon := raw.index_u8(`:`)
	if colon > 0 && colon + 1 < raw.len && raw[colon + 1] == `/` {
		return raw[colon + 1..]
	}
	return '/' + escape_pointer(raw)
}

pub fn resolve_pointer(root json2.Any, ptr string) ?json2.Any {
	norm := normalize_pointer(ptr)
	if norm == '' {
		return root
	}
	if !norm.starts_with('/') {
		return none
	}
	mut cur := root
	for raw_seg in norm[1..].split('/') {
		seg := unescape_pointer(raw_seg)
		match cur {
			map[string]json2.Any {
				if val := cur[seg] {
					cur = val
				} else {
					return none
				}
			}
			[]json2.Any {
				idx := seg.int()
				if seg != idx.str() || idx < 0 || idx >= cur.len {
					return none
				}
				cur = cur[idx]
			}
			else {
				return none
			}
		}
	}
	return cur
}

pub fn write_pointer(mut root map[string]json2.Any, ptr string, val json2.Any) {
	norm := normalize_pointer(ptr)
	if !norm.starts_with('/') || norm == '/' {
		return
	}
	segs := norm[1..].split('/').map(unescape_pointer(it))
	write_pointer_segs(mut root, segs, val)
}

fn write_pointer_segs(mut cur map[string]json2.Any, segs []string, val json2.Any) {
	if segs.len == 0 {
		return
	}
	head := segs[0]
	if segs.len == 1 {
		cur[head] = val
		return
	}
	mut child := map[string]json2.Any{}
	if existing := cur[head] {
		if existing is map[string]json2.Any {
			child = existing.clone()
		}
	}
	write_pointer_segs(mut child, segs[1..], val)
	cur[head] = json2.Any(child)
}

pub fn is_finite_num(v json2.Any) bool {
	return match v {
		i64, int, u64 { true }
		f64 { !math.is_nan(v) && !math.is_inf(v, 0) }
		f32 { !math.is_nan(f64(v)) && !math.is_inf(f64(v), 0) }
		else { false }
	}
}

pub fn as_finite_f64(v json2.Any) ?f64 {
	return match v {
		i64 {
			f64(v)
		}
		int {
			f64(v)
		}
		u64 {
			f64(v)
		}
		f64 {
			if !math.is_nan(v) && !math.is_inf(v, 0) {
				v
			} else {
				none
			}
		}
		f32 {
			f := f64(v)
			if !math.is_nan(f) && !math.is_inf(f, 0) {
				f
			} else {
				none
			}
		}
		else {
			none
		}
	}
}

pub fn values_equal(a json2.Any, b json2.Any) bool {
	if a is bool || b is bool {
		if a is bool && b is bool {
			return a == b
		}
		return false
	}
	if is_finite_num(a) || is_finite_num(b) {
		fa := as_finite_f64(a) or { return false }
		fb := as_finite_f64(b) or { return false }
		return math.abs(fa - fb) <= 1e-9
	}
	if a is json2.Null || b is json2.Null {
		return a is json2.Null && b is json2.Null
	}
	if a is string && b is string {
		return a == b
	}
	if a is []json2.Any && b is []json2.Any {
		if a.len != b.len {
			return false
		}
		for i := 0; i < a.len; i++ {
			if !values_equal(a[i], b[i]) {
				return false
			}
		}
		return true
	}
	if a is map[string]json2.Any && b is map[string]json2.Any {
		if a.len != b.len {
			return false
		}
		for k, va in a {
			vb := b[k] or { return false }
			if !values_equal(va, vb) {
				return false
			}
		}
		return true
	}
	return false
}

pub fn is_relational_table(v json2.Any) bool {
	if v is map[string]json2.Any {
		if v.len == 0 {
			return false
		}
		for k, _ in v {
			if k !in rel_keys {
				return false
			}
		}
		return true
	}
	return false
}

fn resolve_peer_target(doc json2.Any, proj_then map[string]string, ref string) ?json2.Any {
	ptr := if ref.starts_with('/') {
		ref
	} else if mapped := proj_then[ref] {
		mapped
	} else {
		'/' + escape_pointer(ref)
	}
	return resolve_pointer(doc, ptr)
}

pub fn check_relational_leaf(doc json2.Any, actual json2.Any, rel map[string]json2.Any, proj_then map[string]string, pred string) ! {
	if 'allowed_keys' in rel || 'forbid_keys' in rel {
		if actual !is map[string]json2.Any {
			return error('${pred}: expected JSON object for allowed_keys/forbid_keys')
		}
		act_map := actual.as_map()
		if ak_v := rel['allowed_keys'] {
			if ak_v is []json2.Any {
				mut allowed := map[string]bool{}
				for item in ak_v {
					if item is string {
						allowed[item] = true
					}
				}
				for act_k, _ in act_map {
					if act_k !in allowed {
						return error('${pred}: unexpected key "${act_k}" outside allowed_keys')
					}
				}
			} else {
				return error('${pred}: invalid allowed_keys')
			}
		}
		if fk_v := rel['forbid_keys'] {
			if fk_v is []json2.Any {
				for item in fk_v {
					if item is string {
						if item in act_map {
							return error('${pred}: forbidden key "${item}" present on ${pred}')
						}
					}
				}
			} else if fk_v is string {
				if fk_v !in act_map {
					return error('${pred}: drop-forbid-key mutant on forbid_keys killed')
				}
			} else {
				return error('${pred}: invalid forbid_keys')
			}
		}
		return
	}
	if ni_v := rel['not_in'] {
		if actual is json2.Null {
			return error('${pred}: expected non-null value for not_in')
		}
		if ni_v is []json2.Any {
			for item in ni_v {
				if values_equal(actual, item) {
					return error('${pred}: forbidden value ${actual.json_str()} in not_in')
				}
			}
		} else if !values_equal(actual, ni_v) {
			return error('${pred}: pick-forbidden-value mutant on not_in killed')
		}
	}
	if min_v := rel['min'] {
		af := as_finite_f64(actual) or { return error('${pred}: expected finite number for min') }
		mf := as_finite_f64(min_v) or { return error('${pred}: invalid min bound') }
		if af < mf - 1e-9 {
			return error('${pred}: ${af} < min ${mf}')
		}
	}
	if max_v := rel['max'] {
		af := as_finite_f64(actual) or { return error('${pred}: expected finite number for max') }
		mf := as_finite_f64(max_v) or { return error('${pred}: invalid max bound') }
		if af > mf + 1e-9 {
			return error('${pred}: ${af} > max ${mf}')
		}
	}
	if ml_v := rel['min_len'] {
		ml := int(as_finite_f64(ml_v) or { return error('${pred}: invalid min_len') })
		al := match actual {
			string { actual.len }
			[]json2.Any { actual.len }
			else { return error('${pred}: expected string or array for min_len') }
		}

		if al < ml {
			return error('${pred}: length ${al} < min_len ${ml}')
		}
	}
	if xl_v := rel['max_len'] {
		xl := int(as_finite_f64(xl_v) or { return error('${pred}: invalid max_len') })
		al := match actual {
			string { actual.len }
			[]json2.Any { actual.len }
			else { return error('${pred}: expected string or array for max_len') }
		}

		if al > xl {
			return error('${pred}: length ${al} > max_len ${xl}')
		}
	}
	if ne_v := rel['non_empty'] {
		if ne_v is bool {
			al := match actual {
				string { actual.len }
				[]json2.Any { actual.len }
				else { return error('${pred}: expected string or array for non_empty') }
			}

			if ne_v && al == 0 {
				return error('${pred}: expected non-empty value')
			}
			if !ne_v && al > 0 {
				return error('${pred}: expected empty value')
			}
		}
	}
	if pf_v := rel['prefix'] {
		if pf_v is string {
			if actual is string {
				if !actual.starts_with(pf_v) {
					return error('${pred}: "${actual}" does not start with "${pf_v}"')
				}
			} else {
				return error('${pred}: expected string for prefix')
			}
		}
	}
	if sf_v := rel['suffix'] {
		if sf_v is string {
			if actual is string {
				if !actual.ends_with(sf_v) {
					return error('${pred}: "${actual}" does not end with "${sf_v}"')
				}
			} else {
				return error('${pred}: expected string for suffix')
			}
		}
	}
	if in_v := rel['in'] {
		if in_v is []json2.Any {
			mut matched := false
			for cand in in_v {
				if values_equal(actual, cand) {
					matched = true
					break
				}
			}
			if !matched {
				return error('${pred}: value not in allowed set')
			}
		}
	}
	if ct_v := rel['contains'] {
		if ct_v is []json2.Any {
			for needle in ct_v {
				if actual is []json2.Any {
					mut found := false
					for item in actual {
						if values_equal(item, needle) {
							found = true
							break
						}
					}
					if !found {
						return error('${pred}: array missing required element')
					}
				} else if actual is string && needle is string {
					if !actual.contains(needle) {
						return error('${pred}: string missing "${needle}"')
					}
				} else {
					return error('${pred}: invalid contains target')
				}
			}
		}
	}
	if eq_v := rel['eq_field'] {
		if eq_v is string {
			peer := resolve_peer_target(doc, proj_then, eq_v) or {
				return error('${pred}: missing eq_field target "${eq_v}"')
			}
			if !values_equal(actual, peer) {
				return error('${pred}: does not equal eq_field "${eq_v}"')
			}
		}
	}
	if le_v := rel['le_field'] {
		if le_v is string {
			peer := resolve_peer_target(doc, proj_then, le_v) or {
				return error('${pred}: missing le_field target "${le_v}"')
			}
			af := as_finite_f64(actual) or { return error('${pred}: non-numeric le_field source') }
			pf := as_finite_f64(peer) or { return error('${pred}: non-numeric le_field target') }
			if af > pf + 1e-9 {
				return error('${pred}: ${af} > le_field ${pf}')
			}
		}
	}
	if ge_v := rel['ge_field'] {
		if ge_v is string {
			peer := resolve_peer_target(doc, proj_then, ge_v) or {
				return error('${pred}: missing ge_field target "${ge_v}"')
			}
			af := as_finite_f64(actual) or { return error('${pred}: non-numeric ge_field source') }
			pf := as_finite_f64(peer) or { return error('${pred}: non-numeric ge_field target') }
			if af < pf - 1e-9 {
				return error('${pred}: ${af} < ge_field ${pf}')
			}
		}
	}
	if sum_v := rel['sum_fields'] {
		if sum_v is []json2.Any {
			af := as_finite_f64(actual) or {
				return error('${pred}: non-numeric sum_fields target')
			}
			mut total := 0.0
			for item in sum_v {
				if item is string {
					peer := resolve_peer_target(doc, proj_then, item) or {
						return error('${pred}: missing sum_fields operand "${item}"')
					}
					pf := as_finite_f64(peer) or {
						return error('${pred}: non-numeric sum_fields operand "${item}"')
					}
					total += pf
				}
			}
			if math.abs(af - total) > 1e-9 {
				return error('${pred}: ${af} != sum_fields ${total}')
			}
		}
	}
}

pub fn round_decimal_witness(v f64) f64 {
	return math.round(v * 1e12) / 1e12
}

pub fn synthesize_leaf_witness(expected json2.Any, built map[string]json2.Any, proj_then map[string]string) json2.Any {
	if !is_relational_table(expected) {
		return expected
	}
	rel := expected.as_map()
	if in_v := rel['in'] {
		if in_v is []json2.Any && in_v.len > 0 {
			return in_v[0]
		}
	}
	if sum_v := rel['sum_fields'] {
		if sum_v is []json2.Any {
			mut total := 0.0
			doc := json2.Any(built)
			for item in sum_v {
				if item is string {
					if peer := resolve_peer_target(doc, proj_then, item) {
						if pf := as_finite_f64(peer) {
							total += pf
						}
					}
				}
			}
			rounded := round_decimal_witness(total)
			if math.floor(rounded) == rounded && math.abs(rounded) <= 9007199254740991.0 {
				return json2.Any(i64(rounded))
			}
			return json2.Any(rounded)
		}
	}
	if min_v := rel['min'] {
		return min_v
	}
	if max_v := rel['max'] {
		return max_v
	}
	if pf_v := rel['prefix'] {
		if pf_v is string {
			if sf_v := rel['suffix'] {
				if sf_v is string {
					return json2.Any(pf_v + sf_v)
				}
			}
			return json2.Any(pf_v)
		}
	}
	if ct_v := rel['contains'] {
		if ct_v is []json2.Any {
			return json2.Any(ct_v)
		}
	}
	if ne_v := rel['non_empty'] {
		if ne_v is bool && ne_v {
			return json2.Any('x')
		}
	}
	return json2.Any(0)
}
