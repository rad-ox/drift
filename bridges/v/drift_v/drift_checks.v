// Zero-dependency native V bridge projection, relational, and stub helpers.
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
	'monotonic',
	'sum_total',
	'step_max_delta',
	'approx',
	'abs_tol',
	'rel_tol',
	'balance_fields',
	'unit',
	'unit_conversion',
	'eq',
	'len',
	'keys',
	'peer',
	'series',
	'tol',
	'convert_from',
]!

fn strip_side_03(s string) string {
	if s.starts_with('when.') || s.starts_with('then.') {
		return s.all_after('.')
	}
	return s
}

fn desugar_03_rel(raw map[string]json2.Any) map[string]json2.Any {
	mut out := map[string]json2.Any{}
	for k, v in raw {
		if k == 'tol' && v is map[string]json2.Any {
			if a := v['abs'] {
				out['abs_tol'] = a
			}
			if r := v['rel'] {
				out['rel_tol'] = r
			}
		} else if k == 'len' && v is map[string]json2.Any {
			if l := v['min'] {
				out['min_len'] = l
			}
			if u := v['max'] {
				out['max_len'] = u
			}
		} else if k == 'keys' && v is map[string]json2.Any {
			if al := v['allow'] {
				out['allowed_keys'] = al
			}
			if fb := v['forbid'] {
				out['forbid_keys'] = fb
			}
		} else if k == 'peer' && v is map[string]json2.Any {
			for pk in ['le', 'ge', 'eq'] {
				if pv := v[pk] {
					if pv is string {
						out['${pk}_field'] = json2.Any(strip_side_03(pv))
					}
				}
			}
			if sf := v['sum'] {
				if sf is []json2.Any {
					out['sum_fields'] = json2.Any(sf.map(json2.Any(strip_side_03(it.str()))))
				}
			}
			if bf := v['balance'] {
				if bf is map[string]json2.Any {
					mut nb := map[string]json2.Any{}
					for side in ['add', 'sub'] {
						if arr := bf[side] {
							if arr is []json2.Any {
								nb[side] = json2.Any(arr.map(json2.Any(strip_side_03(it.str()))))
							}
						}
					}
					out['balance_fields'] = json2.Any(nb)
				}
			}
		} else if k == 'series' && v is map[string]json2.Any {
			for sk, sv in v {
				if sk == 'monotonic' && sv.str() in ['increasing', 'decreasing'] {
					out[sk] = json2.Any('strictly_${sv.str()}')
				} else {
					out[sk] = sv
				}
			}
		} else if k != 'convert_from' {
			out[k] = v
		}
	}
	if 'eq' in out && ('abs_tol' in out || 'rel_tol' in out) && 'balance_fields' !in out
		&& 'sum_fields' !in out {
		if eq_v := out['eq'] {
			out['approx'] = eq_v
		}
		out.delete('eq')
	}
	return out
}

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

pub fn check_relational_leaf(doc json2.Any, actual json2.Any, raw_rel map[string]json2.Any, proj_then map[string]string, pred string) ! {
	rel := desugar_03_rel(raw_rel)
	if 'eq' in rel {
		if eq_v := rel['eq'] {
			if !values_equal(actual, eq_v) {
				return error('${pred}: mismatch on eq: got ${actual.json_str()}, expected ${eq_v.json_str()}')
			}
		}
		if rel.len == 1 {
			return
		}
	}
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
				for act_k, act_v in act_map {
					if act_k == '_frame' && act_v is map[string]json2.Any {
						continue
					}
					if act_k !in allowed {
						return error('${pred}: unexpected key "${act_k}" outside allowed_keys')
					}
				}
			} else {
				return error('${pred}: invalid allowed_keys')
			}
		}
		if fk_v := rel['forbid_keys'] {
			is_root_t := actual.json_str() == doc.json_str()
			if fk_v is []json2.Any {
				for item in fk_v {
					if item is string {
						if has_key_recursive(actual, item, is_root_t) {
							return error('${pred}: forbidden key "${item}" present on ${pred}')
						}
					}
				}
			} else if fk_v is string {
				if !has_key_recursive(actual, fk_v, is_root_t) {
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
	is_seq_tuning := 'monotonic' in rel || 'step_max_delta' in rel || 'sum_total' in rel
	mut tol := 1e-9
	if at_v := rel['abs_tol'] {
		if at_f := as_finite_f64(at_v) {
			if at_f >= 0.0 {
				tol = at_f
			}
		}
	}
	if !is_seq_tuning {
		if min_v := rel['min'] {
			af := as_finite_f64(actual) or {
				return error('${pred}: expected finite number for min')
			}
			mf := as_finite_f64(min_v) or { return error('${pred}: invalid min bound') }
			if af < mf - 1e-9 {
				return error('${pred}: ${af} < min ${mf}')
			}
		}
		if max_v := rel['max'] {
			af := as_finite_f64(actual) or {
				return error('${pred}: expected finite number for max')
			}
			mf := as_finite_f64(max_v) or { return error('${pred}: invalid max bound') }
			if af > mf + 1e-9 {
				return error('${pred}: ${af} > max ${mf}')
			}
		}
	}
	if ap_v := rel['approx'] {
		af := as_finite_f64(actual) or {
			return error('${pred}: expected finite number for approx')
		}
		apf := as_finite_f64(ap_v) or { return error('${pred}: invalid approx target') }
		if 'abs_tol' !in rel && 'rel_tol' !in rel {
			return error('${pred}: approx requires abs_tol or rel_tol')
		}
		mut at := 0.0
		if at_v := rel['abs_tol'] {
			at = as_finite_f64(at_v) or { return error('${pred}: invalid abs_tol') }
			if at < 0.0 {
				return error('${pred}: abs_tol must be >= 0')
			}
		}
		mut rt := 0.0
		if rt_v := rel['rel_tol'] {
			rt = as_finite_f64(rt_v) or { return error('${pred}: invalid rel_tol') }
			if rt < 0.0 {
				return error('${pred}: rel_tol must be >= 0')
			}
		}
		rad := at + rt * math.abs(apf)
		if math.abs(af - apf) > rad {
			return error('${pred}: ${af} outside approx ${apf} +/- ${rad}')
		}
	}
	if bf_v := rel['balance_fields'] {
		if bf_v is map[string]json2.Any {
			af := as_finite_f64(actual) or {
				return error('${pred}: non-numeric balance_fields target')
			}
			mut total := 0.0
			if add_v := bf_v['add'] {
				if add_v is []json2.Any {
					for item in add_v {
						if item is string {
							peer := resolve_peer_target(doc, proj_then, item) or {
								return error('${pred}: missing balance_fields operand "${item}"')
							}
							pf := as_finite_f64(peer) or {
								return error('${pred}: non-numeric balance_fields operand "${item}"')
							}
							total += pf
						}
					}
				}
			}
			if sub_v := bf_v['sub'] {
				if sub_v is []json2.Any {
					for item in sub_v {
						if item is string {
							peer := resolve_peer_target(doc, proj_then, item) or {
								return error('${pred}: missing balance_fields operand "${item}"')
							}
							pf := as_finite_f64(peer) or {
								return error('${pred}: non-numeric balance_fields operand "${item}"')
							}
							total -= pf
						}
					}
				}
			}
			if math.abs(af - total) > tol {
				return error('${pred}: ${af} != balance_fields ${total}')
			}
		} else {
			return error('${pred}: invalid balance_fields')
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
	if is_seq_tuning {
		if actual is []json2.Any {
			if min_v := rel['min'] {
				mf := as_finite_f64(min_v) or { return error('${pred}: invalid min bound') }
				for item in actual {
					cur := as_finite_f64(item) or { return error('${pred}: non-numeric element') }
					if cur + tol < mf {
						return error('${pred}: element ${cur} < min ${mf}')
					}
				}
			}
			if max_v := rel['max'] {
				mf := as_finite_f64(max_v) or { return error('${pred}: invalid max bound') }
				for item in actual {
					cur := as_finite_f64(item) or { return error('${pred}: non-numeric element') }
					if cur - tol > mf {
						return error('${pred}: element ${cur} > max ${mf}')
					}
				}
			}
		}
	}
	if mono_v := rel['monotonic'] {
		mode := if mono_v is string { mono_v } else { '' }
		if actual is []json2.Any {
			if actual.len == 0 {
				return error('${pred}: empty array for monotonic')
			}
			mut prev := as_finite_f64(actual[0]) or {
				return error('${pred}: non-numeric element in monotonic array')
			}
			for i := 1; i < actual.len; i++ {
				cur := as_finite_f64(actual[i]) or {
					return error('${pred}: non-numeric element in monotonic array')
				}
				ok := match mode {
					'non_decreasing' { prev - tol <= cur }
					'strictly_increasing' { prev + tol < cur }
					'non_increasing' { prev + tol >= cur }
					'strictly_decreasing' { prev - tol > cur }
					else { false }
				}

				if !ok {
					return error('${pred}: monotonic ${mode} violated at index ${i} (${prev} -> ${cur})')
				}
				prev = cur
			}
		} else {
			return error('${pred}: expected array for monotonic')
		}
	}
	if delta_v := rel['step_max_delta'] {
		delta := as_finite_f64(delta_v) or { return error('${pred}: invalid step_max_delta') }
		if delta <= 0.0 {
			return error('${pred}: step_max_delta must be > 0')
		}
		if actual is []json2.Any {
			if actual.len == 0 {
				return error('${pred}: empty array for step_max_delta')
			}
			mut prev := as_finite_f64(actual[0]) or {
				return error('${pred}: non-numeric element in step_max_delta array')
			}
			for i := 1; i < actual.len; i++ {
				cur := as_finite_f64(actual[i]) or {
					return error('${pred}: non-numeric element in step_max_delta array')
				}
				if math.abs(cur - prev) > delta + tol {
					return error('${pred}: step_max_delta ${delta} exceeded at index ${i}')
				}
				prev = cur
			}
		} else {
			return error('${pred}: expected array for step_max_delta')
		}
	}
	if st_v := rel['sum_total'] {
		if is_relational_table(actual) {
			return error('${pred}: literal relational table cannot satisfy sum_total')
		}
		mut total := 0.0
		if actual is []json2.Any {
			if actual.len == 0 {
				return error('${pred}: empty array for sum_total')
			}
			for item in actual {
				n := as_finite_f64(item) or {
					return error('${pred}: non-numeric element in sum_total')
				}
				total += n
			}
		} else if actual is map[string]json2.Any {
			if actual.len == 0 {
				return error('${pred}: empty map for sum_total')
			}
			for _, item in actual {
				n := as_finite_f64(item) or {
					return error('${pred}: non-numeric value in sum_total')
				}
				total += n
			}
		} else {
			return error('${pred}: expected array or map for sum_total')
		}
		if target := as_finite_f64(st_v) {
			if math.abs(total - target) > tol {
				return error('${pred}: sum_total ${total} != ${target}')
			}
		} else if st_v is map[string]json2.Any {
			if eq_v := st_v['eq'] {
				eq_n := as_finite_f64(eq_v) or { return error('${pred}: invalid sum_total.eq') }
				if math.abs(total - eq_n) > tol {
					return error('${pred}: sum_total ${total} != ${eq_n}')
				}
			}
			if min_v := st_v['min'] {
				min_n := as_finite_f64(min_v) or { return error('${pred}: invalid sum_total.min') }
				if total + tol < min_n {
					return error('${pred}: sum_total ${total} < ${min_n}')
				}
			}
			if max_v := st_v['max'] {
				max_n := as_finite_f64(max_v) or { return error('${pred}: invalid sum_total.max') }
				if total - tol > max_n {
					return error('${pred}: sum_total ${total} > ${max_n}')
				}
			}
		} else {
			return error('${pred}: invalid sum_total')
		}
	}
}

pub fn round_decimal_witness(v f64) f64 {
	return math.round(v * 1e12) / 1e12
}

fn allowed_write_sets_of(view map[string]json2.Any, case_id string) (map[string]bool, map[string]bool, bool) {
	mut scope_writes := []string{}
	if sc_any := view['scope'] {
		if sc_any is map[string]json2.Any {
			if sw_any := sc_any['writes'] {
				if sw_any is []json2.Any {
					for item in sw_any {
						if item is string {
							scope_writes << item
						}
					}
				}
			}
		}
	}
	mut has_case_writes := false
	mut raw_allowed := scope_writes.clone()
	if cases_any := view['cases'] {
		if cases_any is map[string]json2.Any {
			if c_any := cases_any[case_id] {
				if c_any is map[string]json2.Any {
					if cw_any := c_any['writes'] {
						if cw_any is []json2.Any {
							has_case_writes = true
							raw_allowed = []string{}
							for item in cw_any {
								if item is string {
									raw_allowed << item
								}
							}
						}
					}
				}
			}
		}
	}
	mut allowed := map[string]bool{}
	mut allowed_bases := map[string]bool{}
	for item in raw_allowed {
		allowed[item] = true
		allowed_bases[item.all_before('#')] = true
	}
	return allowed, allowed_bases, has_case_writes
}

fn is_write_resource_allowed(res string, allowed map[string]bool, allowed_bases map[string]bool) bool {
	base := res.all_before('#')
	return res in allowed || base in allowed || (!res.contains('#') && res in allowed_bases)
}

fn forbidden_writes_of(view map[string]json2.Any, case_id string) []string {
	mut scope_writes := []string{}
	if sc_any := view['scope'] {
		if sc_any is map[string]json2.Any {
			if sw_any := sc_any['writes'] {
				if sw_any is []json2.Any {
					for item in sw_any {
						if item is string {
							scope_writes << item
						}
					}
				}
			}
		}
	}
	if scope_writes.len == 0 {
		return []string{}
	}
	allowed, allowed_bases, has_case_writes := allowed_write_sets_of(view, case_id)
	if !has_case_writes {
		return []string{}
	}
	mut out := []string{}
	for r in scope_writes {
		if !is_write_resource_allowed(r, allowed, allowed_bases) {
			out << r
		}
	}
	return out
}

fn verify_single_frame_obs(pfx string, res string, obs json2.Any, is_ambient bool) ! {
	mut checked := false
	write_lbl := if is_ambient {
		'undeclared write on perimeter resource "${res}"'
	} else {
		'frame violation on resource "${res}"'
	}
	snap_lbl := if is_ambient {
		'undeclared state mutation on perimeter resource "${res}"'
	} else {
		'frame state mutation on resource "${res}"'
	}
	if n := as_finite_f64(obs) {
		if n >= 0 && n == math.trunc(n) {
			checked = true
			if n > 0 {
				return error('${pfx}: ${write_lbl}: expected 0 writes, observed ${n}')
			}
		}
	} else if obs is map[string]json2.Any {
		for wk in ['writes', 'operations', 'events'] {
			if wv := obs[wk] {
				if wn := as_finite_f64(wv) {
					if wn >= 0 && wn == math.trunc(wn) {
						checked = true
						if wn > 0 {
							return error('${pfx}: ${write_lbl}: expected 0 writes, observed ${wn}')
						}
					} else {
						return error('${pfx}: invalid frame ${wk} for "${res}": expected non-negative integer, got ${wn}')
					}
				} else if wv is []json2.Any {
					checked = true
					if wv.len > 0 {
						return error('${pfx}: ${write_lbl}: expected 0 writes, observed ${wv.len}')
					}
				} else {
					return error('${pfx}: invalid frame ${wk} for "${res}": expected non-negative integer')
				}
			}
		}
		if bef := obs['before'] {
			if aft := obs['after'] {
				checked = true
				if !values_equal(bef, aft) {
					return error('${pfx}: ${snap_lbl}: before and after snapshots differ')
				}
			}
		}
	}
	if !checked {
		return error('${pfx}: frame observation for "${res}" must supply writes/operations/events or before/after snapshots')
	}
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
	if ap_v := rel['approx'] {
		return ap_v
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
	if 'sum_total' in rel || 'monotonic' in rel || 'step_max_delta' in rel {
		mut tgt := 1.0
		if st_v := rel['sum_total'] {
			if f := as_finite_f64(st_v) {
				tgt = f
			} else if st_v is map[string]json2.Any {
				if eq_v := st_v['eq'] {
					if f := as_finite_f64(eq_v) {
						tgt = f
					}
				} else if min_v := st_v['min'] {
					if f := as_finite_f64(min_v) {
						tgt = f
					}
				} else if max_v := st_v['max'] {
					if f := as_finite_f64(max_v) {
						tgt = f
					}
				}
			}
		}
		mut eps := 0.2
		if d_v := rel['step_max_delta'] {
			if df := as_finite_f64(d_v) {
				if df > 0.0 && df / 2.0 < eps {
					eps = df / 2.0
				}
			}
		}
		mut mode := ''
		if m_v := rel['monotonic'] {
			if m_v is string {
				mode = m_v
			}
		}
		if mode in ['strictly_decreasing', 'non_increasing'] {
			if 'sum_total' in rel {
				a := round_decimal_witness(tgt / 2.0 + eps / 2.0)
				return json2.Any([json2.Any(a), json2.Any(round_decimal_witness(tgt - a))])
			}
			return json2.Any([json2.Any(round_decimal_witness(1.0 + eps)), json2.Any(1.0)])
		}
		if mode in ['strictly_increasing', 'non_decreasing'] {
			if 'sum_total' in rel {
				a := round_decimal_witness(tgt / 2.0 - eps / 2.0)
				return json2.Any([json2.Any(a), json2.Any(round_decimal_witness(tgt - a))])
			}
			return json2.Any([json2.Any(1.0), json2.Any(round_decimal_witness(1.0 + eps))])
		}
		return json2.Any([json2.Any(tgt / 2.0), json2.Any(tgt - tgt / 2.0)])
	}
	return json2.Any(0)
}
