// Zero-dependency native V bridge plan interpreter, relational checks, and pointers.
module drift_v

import math
import x.json2

const rel_keys = ['min', 'max', 'min_len', 'max_len', 'non_empty', 'le_field', 'ge_field', 'eq_field',
	'in', 'not_in', 'contains', 'prefix', 'suffix', 'sum_fields', 'allowed_keys', 'forbid_keys',
	'monotonic', 'sum_total', 'step_max_delta', 'approx', 'abs_tol', 'rel_tol', 'balance_fields',
	'unit', 'unit_conversion', 'eq', 'len', 'keys', 'peer', 'series', 'tol', 'convert_from']!

fn j_map(v json2.Any) ?map[string]json2.Any {
	return if v is map[string]json2.Any { v } else { none }
}

fn j_arr(v json2.Any) ?[]json2.Any {
	return if v is []json2.Any { v } else { none }
}

fn j_str(v json2.Any) ?string {
	return if v is string { v } else { none }
}

fn j_bool(v json2.Any) ?bool {
	return if v is bool { v } else { none }
}

fn map_field(m map[string]json2.Any, k string) map[string]json2.Any {
	return j_map(m[k] or { return map[string]json2.Any{} }) or {
		map[string]json2.Any{}
	}
}

fn arr_field(m map[string]json2.Any, k string) []json2.Any {
	return j_arr(m[k] or { return []json2.Any{} }) or { []json2.Any{} }
}

fn qualify_peer_03(s string) string {
	t := s.trim_space()
	return if t == '' || t.starts_with('when.') || t.starts_with('then.') || t.starts_with('/') {
		t
	} else {
		'then.${t}'
	}
}

fn desugar_03_rel(raw map[string]json2.Any) map[string]json2.Any {
	mut out := map[string]json2.Any{}
	for k, v in raw {
		if k == 'tol' {
			if m := j_map(v) {
				if a := m['abs'] {
					out['abs_tol'] = a
				}
				if r := m['rel'] {
					out['rel_tol'] = r
				}
			}
		} else if k == 'len' {
			if m := j_map(v) {
				if l := m['min'] {
					out['min_len'] = l
				}
				if u := m['max'] {
					out['max_len'] = u
				}
			}
		} else if k == 'keys' {
			if m := j_map(v) {
				if al := m['allow'] {
					out['allowed_keys'] = al
				}
				if fb := m['forbid'] {
					out['forbid_keys'] = fb
				}
			}
		} else if k == 'peer' {
			if m := j_map(v) {
				for pk in ['le', 'ge', 'eq'] {
					if ps := j_str(m[pk] or { json2.Null{} }) {
						out['${pk}_field'] = json2.Any(qualify_peer_03(ps))
					}
				}
				if sf := j_arr(m['sum'] or { json2.Null{} }) {
					out['sum_fields'] = json2.Any(sf.map(json2.Any(qualify_peer_03(it.str()))))
				}
				if bm := j_map(m['balance'] or { json2.Null{} }) {
					mut nb := map[string]json2.Any{}
					for side in ['add', 'sub'] {
						if arr := j_arr(bm[side] or { json2.Null{} }) {
							nb[side] = json2.Any(arr.map(json2.Any(qualify_peer_03(it.str()))))
						}
					}
					out['balance_fields'] = json2.Any(nb)
				}
			}
		} else if k == 'series' {
			if m := j_map(v) {
				for sk, sv in m {
					out[sk] = if sk == 'monotonic' && sv.str() in ['increasing', 'decreasing'] {
						json2.Any('strictly_${sv.str()}')
					} else {
						sv
					}
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

fn scale_num_any(v json2.Any, ratio f64) json2.Any {
	return if n := as_finite_f64(v) { json2.Any(n * ratio) } else { v }
}

fn normalize_constraint_03(raw map[string]json2.Any, contract map[string]json2.Any, pred string) !map[string]json2.Any {
	mut out := desugar_03_rel(raw)
	cf := raw['convert_from'] or { return out }
	from := cf.str()
	units := j_map(contract['units'] or { raw['unit_conversion'] or { json2.Null{} } }) or {
		map[string]json2.Any{}
	}
	mut target := (raw['unit'] or { json2.Any('') }).str()
	if sch := j_map(contract['schema'] or { json2.Null{} }) {
		if tsch := j_map(sch['then'] or { json2.Null{} }) {
			if ps := j_map(tsch[pred] or { json2.Null{} }) {
				if u := ps['unit'] {
					target = u.str()
				}
			}
		}
	}
	mut ratio := 0.0
	if target == from {
		ratio = 1.0
	} else if target != '' {
		if r := units['${from}->${target}'] {
			ratio = as_finite_f64(r) or { 0.0 }
		}
	} else {
		mut cnt := 0
		for k, r in units {
			if k.starts_with('${from}->') {
				cnt++
				ratio = as_finite_f64(r) or { 0.0 }
			}
		}
		if cnt != 1 {
			ratio = 0.0
		}
	}
	if ratio <= 0 || math.is_inf(ratio, 0) || math.is_nan(ratio) {
		return error('${pred}: missing unit conversion from ${from}')
	}
	return apply_conv_scale(mut out, ratio)
}

fn apply_conv_scale(mut out map[string]json2.Any, ratio f64) map[string]json2.Any {
	if ratio == 1.0 {
		return out
	}
	for k in ['eq', 'approx', 'min', 'max', 'abs_tol', 'step_max_delta'] {
		if v := out[k] {
			out[k] = scale_num_any(v, ratio)
		}
	}
	for k in ['in', 'not_in'] {
		if arr := j_arr(out[k] or { json2.Null{} }) {
			out[k] = json2.Any(arr.map(scale_num_any(it, ratio)))
		}
	}
	if st := out['sum_total'] {
		if stm := j_map(st) {
			mut sc := map[string]json2.Any{}
			for k, v in stm {
				sc[k] = scale_num_any(v, ratio)
			}
			out['sum_total'] = json2.Any(sc)
		} else {
			out['sum_total'] = scale_num_any(st, ratio)
		}
	}
	return out
}

fn extract_side_projections(view map[string]json2.Any, side string) map[string]string {
	mut out := map[string]string{}
	proj := j_map(view['projections'] or { json2.Null{} }) or { return out }
	for k, v in proj {
		if k !in ['when', 'then'] && v is string {
			out[k] = v
		}
	}
	for k, v in map_field(proj, side) {
		if v is string {
			out[k] = v
		}
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
	colon := raw.index_u8(`:`)
	if colon > 0 && colon + 1 < raw.len && raw[colon + 1] == `/` {
		return raw[colon + 1..]
	}
	return if raw.starts_with('/') { raw } else { '/' + escape_pointer(raw) }
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
		if m := j_map(cur) {
			cur = m[seg] or { return none }
		} else if a := j_arr(cur) {
			idx := seg.int()
			if seg != idx.str() || idx < 0 || idx >= a.len {
				return none
			}
			cur = a[idx]
		} else {
			return none
		}
	}
	return cur
}

pub fn write_pointer(mut root map[string]json2.Any, ptr string, val json2.Any) {
	norm := normalize_pointer(ptr)
	if norm.starts_with('/') && norm != '/' {
		write_pointer_segs(mut root, norm[1..].split('/').map(unescape_pointer(it)), val)
	}
}

fn write_pointer_segs(mut cur map[string]json2.Any, segs []string, val json2.Any) {
	if segs.len == 0 {
		return
	}
	if segs.len == 1 {
		cur[segs[0]] = val
		return
	}
	mut child := (j_map(cur[segs[0]] or { json2.Null{} }) or {
		map[string]json2.Any{}
	}).clone()
	write_pointer_segs(mut child, segs[1..], val)
	cur[segs[0]] = json2.Any(child)
}

pub fn is_finite_num(v json2.Any) bool {
	return as_finite_f64(v) != none
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
			if !math.is_nan(f64(v)) && !math.is_inf(f64(v), 0) {
				f64(v)
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
		return a is bool && b is bool && a == b
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
	if aa := j_arr(a) {
		ba := j_arr(b) or { return false }
		return aa.len == ba.len && json_arrays_eq(aa, ba)
	}
	if am := j_map(a) {
		bm := j_map(b) or { return false }
		if am.len != bm.len {
			return false
		}
		for k, va in am {
			if !values_equal(va, bm[k] or { return false }) {
				return false
			}
		}
		return true
	}
	return false
}

fn json_arrays_eq(aa []json2.Any, ba []json2.Any) bool {
	for i in 0 .. aa.len {
		if !values_equal(aa[i], ba[i]) {
			return false
		}
	}
	return true
}

pub fn is_relational_table(v json2.Any) bool {
	m := j_map(v) or { return false }
	return m.len > 0 && m.keys().all(it in rel_keys)
}

fn resolve_peer_target(doc json2.Any, proj_then map[string]string, ref string) ?json2.Any {
	if ref.starts_with('when.') {
		wk := ref[5..]
		dm := j_map(doc) or { return none }
		if v := dm[ref] {
			return v
		}
		for sk in ['when', 'before', '_when_env'] {
			if sm := j_map(dm[sk] or { json2.Null{} }) {
				if v := sm[wk] {
					return v
				}
			}
		}
		return none
	}
	eff := if ref.starts_with('then.') { ref[5..] } else { ref }
	if eff == '' {
		return none
	}
	ptr := if eff.starts_with('/') { eff } else { proj_then[eff] or { '/' + escape_pointer(eff) } }
	return resolve_pointer(doc, ptr)
}

fn len_of_actual(actual json2.Any) ?int {
	return match actual {
		string { actual.runes().len }
		[]json2.Any { actual.len }
		map[string]json2.Any { actual.len }
		else { none }
	}
}

pub fn check_relational_leaf(doc json2.Any, actual json2.Any, raw_rel map[string]json2.Any, proj_then map[string]string, pred string) ! {
	context := j_map(doc) or {
		map[string]json2.Any{}
	}
	rel := normalize_constraint_03(raw_rel, context, pred)!
	check_desugared_rel(doc, actual, rel, proj_then, pred)!
}

// eval_compiled_plan_case evaluates a precompiled drift.bridge-plan/1 case in memory
// with zero unit-table or dialect desugaring overhead.
pub fn eval_compiled_plan_case(contract_id string, case_id string, plan_case map[string]json2.Any, doc json2.Any) !(bool, []string) {
	clauses := j_arr(plan_case['clauses'] or { return false, []string{} }) or {
		return false, []string{}
	}
	mut read_preds := []string{}
	for c_any in clauses {
		cm := j_map(c_any) or { continue }
		pred := (cm['pred'] or { json2.Any('') }).str()
		ptr := (cm['pointer'] or { json2.Any('/' + escape_pointer(pred)) }).str()
		conv := as_finite_f64(cm['conv'] or { json2.Any(1.0) }) or { 1.0 }
		raw_c := j_map(cm['constraint'] or { continue }) or { continue }
		mut rel := desugar_03_rel(raw_c)
		rel = apply_conv_scale(mut rel, conv)
		mut peer_ptrs := map[string]string{}
		if pp := j_map(cm['peer_pointers'] or { json2.Null{} }) {
			for k, v in pp {
				peer_ptrs[k] = v.str()
				if k.starts_with('then.') {
					peer_ptrs[k[5..]] = v.str()
				}
			}
		}
		mut eval_doc := doc
		if wp := j_map(cm['when_peers'] or { json2.Null{} }) {
			if dm := j_map(doc) {
				mut copy_m := dm.clone()
				mut wenv := (j_map(copy_m['_when_env'] or { json2.Null{} }) or {
					map[string]json2.Any{}
				}).clone()
				for wk, wv in wp {
					clean := if wk.starts_with('when.') { wk[5..] } else { wk }
					wenv[clean] = wv
					copy_m['when.${clean}'] = wv
				}
				copy_m['_when_env'] = json2.Any(wenv)
				eval_doc = json2.Any(copy_m)
			}
		}
		mut actual := json2.Any(json2.Null{})
		if ('allowed_keys' in rel || 'forbid_keys' in rel) && ptr == '/' + escape_pointer(pred) {
			if dm := j_map(eval_doc) {
				actual = if sub := j_map(dm[pred] or { json2.Null{} }) {
					json2.Any(sub)
				} else {
					eval_doc
				}
			} else {
				actual = eval_doc
			}
		} else {
			actual = resolve_pointer(eval_doc, ptr) or {
				return error('${contract_id}.${case_id}: missing pointer "${ptr}" for predicate "${pred}"')
			}
		}
		check_desugared_rel(eval_doc, actual, rel, peer_ptrs, pred)!
		if (cm['clause'] or { json2.Any('') }).str().starts_with('then.') && pred !in read_preds {
			read_preds << pred
		}
	}
	return true, read_preds
}

fn check_desugared_rel(doc json2.Any, actual json2.Any, rel map[string]json2.Any, proj_then map[string]string, pred string) ! {
	if eq_v := rel['eq'] {
		if !values_equal(actual, eq_v) {
			return error('${pred}: mismatch on eq: got ${actual.json_str()}, expected ${eq_v.json_str()}')
		}
		if rel.len == 1 {
			return
		}
	}
	if 'allowed_keys' in rel || 'forbid_keys' in rel {
		act_map := j_map(actual) or {
			return error('${pred}: expected JSON object for allowed_keys/forbid_keys')
		}
		if ak_v := rel['allowed_keys'] {
			ak_arr := j_arr(ak_v) or { return error('${pred}: invalid allowed_keys') }
			allowed := ak_arr.filter(it is string).map(it.str())
			for act_k, act_v in act_map {
				if act_k in ['_frame', '_when_env'] && act_v is map[string]json2.Any {
					continue
				}
				if act_k !in allowed {
					return error('${pred}: unexpected key "${act_k}" outside allowed_keys')
				}
			}
		}
		if fk_v := rel['forbid_keys'] {
			is_root_t := actual.json_str() == doc.json_str()
			if fk_arr := j_arr(fk_v) {
				for item in fk_arr {
					if s := j_str(item) {
						if has_key_recursive(actual, s, is_root_t) {
							return error('${pred}: forbidden key "${s}" present on ${pred}')
						}
					}
				}
			} else if fk_s := j_str(fk_v) {
				if !has_key_recursive(actual, fk_s, is_root_t) {
					return error('${pred}: drop-forbid-key mutant on forbid_keys killed')
				}
			} else {
				return error('${pred}: invalid forbid_keys')
			}
		}
	}
	if ni_v := rel['not_in'] {
		if actual is json2.Null {
			return error('${pred}: expected non-null value for not_in')
		}
		if ni_arr := j_arr(ni_v) {
			if ni_arr.any(values_equal(actual, it)) {
				return error('${pred}: forbidden value ${actual.json_str()} in not_in')
			}
		} else if !values_equal(actual, ni_v) {
			return error('${pred}: pick-forbidden-value mutant on not_in killed')
		}
	}
	is_seq_tuning := 'monotonic' in rel || 'step_max_delta' in rel || 'sum_total' in rel
	mut tol := 1e-9
	if at_f := as_finite_f64(rel['abs_tol'] or { json2.Null{} }) {
		if at_f >= 0.0 {
			tol = at_f
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
		at := if 'abs_tol' in rel {
			as_finite_f64(rel['abs_tol'] or { json2.Null{} }) or {
				return error('${pred}: invalid abs_tol')
			}
		} else {
			0.0
		}
		rt := if 'rel_tol' in rel {
			as_finite_f64(rel['rel_tol'] or { json2.Null{} }) or {
				return error('${pred}: invalid rel_tol')
			}
		} else {
			0.0
		}
		if at < 0.0 || rt < 0.0 || math.abs(af - apf) > at + rt * math.abs(apf) {
			return error('${pred}: ${af} outside approx ${apf}')
		}
	}
	if bf_v := rel['balance_fields'] {
		bm := j_map(bf_v) or { return error('${pred}: invalid balance_fields') }
		af := as_finite_f64(actual) or {
			return error('${pred}: non-numeric balance_fields target')
		}
		mut total := 0.0
		for sgn_idx, side in ['add', 'sub'] {
			sgn := if sgn_idx == 0 { 1.0 } else { -1.0 }
			for item in arr_field(bm, side) {
				if s := j_str(item) {
					peer := resolve_peer_target(doc, proj_then, s) or {
						return error('${pred}: missing balance_fields operand "${s}"')
					}
					total += sgn * (as_finite_f64(peer) or {
						return error('${pred}: non-numeric balance_fields operand "${s}"')
					})
				}
			}
		}
		if math.abs(af - total) > tol {
			return error('${pred}: ${af} != balance_fields ${total}')
		}
	}
	if ml_v := rel['min_len'] {
		ml := int(as_finite_f64(ml_v) or { return error('${pred}: invalid min_len') })
		al := len_of_actual(actual) or { return error('${pred}: invalid type for min_len') }
		if al < ml {
			return error('${pred}: length ${al} < min_len ${ml}')
		}
	}
	if xl_v := rel['max_len'] {
		xl := int(as_finite_f64(xl_v) or { return error('${pred}: invalid max_len') })
		al := len_of_actual(actual) or { return error('${pred}: invalid type for max_len') }
		if al > xl {
			return error('${pred}: length ${al} > max_len ${xl}')
		}
	}
	if ne := j_bool(rel['non_empty'] or { json2.Null{} }) {
		al := len_of_actual(actual) or { return error('${pred}: invalid type for non_empty') }
		if (ne && al == 0) || (!ne && al > 0) {
			return error('${pred}: non_empty=${ne} violated (len=${al})')
		}
	}
	if pf := j_str(rel['prefix'] or { json2.Null{} }) {
		s := j_str(actual) or { return error('${pred}: expected string for prefix') }
		if !s.starts_with(pf) {
			return error('${pred}: "${s}" does not start with "${pf}"')
		}
	}
	if sf := j_str(rel['suffix'] or { json2.Null{} }) {
		s := j_str(actual) or { return error('${pred}: expected string for suffix') }
		if !s.ends_with(sf) {
			return error('${pred}: "${s}" does not end with "${sf}"')
		}
	}
	if in_arr := j_arr(rel['in'] or { json2.Null{} }) {
		if !in_arr.any(values_equal(actual, it)) {
			return error('${pred}: value not in allowed set')
		}
	}
	if ct_v := rel['contains'] {
		reqs := j_arr(ct_v) or { [ct_v] }
		for needle in reqs {
			if arr := j_arr(actual) {
				if !arr.any(values_equal(it, needle)) {
					return error('${pred}: array missing required element')
				}
			} else if s := j_str(actual) {
				ns := j_str(needle) or { return error('${pred}: invalid contains needle') }
				if !s.contains(ns) {
					return error('${pred}: string missing "${ns}"')
				}
			} else {
				return error('${pred}: invalid contains target')
			}
		}
	}
	if eq_s := j_str(rel['eq_field'] or { json2.Null{} }) {
		peer := resolve_peer_target(doc, proj_then, eq_s) or {
			return error('${pred}: missing eq_field "${eq_s}"')
		}
		if !values_equal(actual, peer) {
			return error('${pred}: does not equal eq_field "${eq_s}"')
		}
	}
	for fk in ['le_field', 'ge_field'] {
		if ref_s := j_str(rel[fk] or { json2.Null{} }) {
			peer := resolve_peer_target(doc, proj_then, ref_s) or {
				return error('${pred}: missing ${fk} "${ref_s}"')
			}
			af := as_finite_f64(actual) or { return error('${pred}: non-numeric ${fk} source') }
			pf := as_finite_f64(peer) or { return error('${pred}: non-numeric ${fk} target') }
			if (fk == 'le_field' && af > pf + 1e-9) || (fk == 'ge_field' && af < pf - 1e-9) {
				return error('${pred}: ${af} violates ${fk} ${pf}')
			}
		}
	}
	if sum_arr := j_arr(rel['sum_fields'] or { json2.Null{} }) {
		af := as_finite_f64(actual) or { return error('${pred}: non-numeric sum_fields target') }
		mut total := 0.0
		for item in sum_arr {
			if s := j_str(item) {
				peer := resolve_peer_target(doc, proj_then, s) or {
					return error('${pred}: missing sum_fields "${s}"')
				}
				total += as_finite_f64(peer) or {
					return error('${pred}: non-numeric sum_fields "${s}"')
				}
			}
		}
		if math.abs(af - total) > 1e-9 {
			return error('${pred}: ${af} != sum_fields ${total}')
		}
	}
	if is_seq_tuning {
		if arr := j_arr(actual) {
			if min_v := rel['min'] {
				mf := as_finite_f64(min_v) or { return error('${pred}: invalid min') }
				for it in arr {
					if (as_finite_f64(it) or { return error('${pred}: non-numeric') }) + tol < mf {
						return error('${pred}: sequence element < min ${mf}')
					}
				}
			}
			if max_v := rel['max'] {
				mf := as_finite_f64(max_v) or { return error('${pred}: invalid max') }
				for it in arr {
					if (as_finite_f64(it) or { return error('${pred}: non-numeric') }) - tol > mf {
						return error('${pred}: sequence element > max ${mf}')
					}
				}
			}
		}
	}
	if mono_v := rel['monotonic'] {
		mode := j_str(mono_v) or { '' }
		arr := j_arr(actual) or { return error('${pred}: expected array for monotonic') }
		if arr.len == 0 {
			return error('${pred}: empty array for monotonic')
		}
		mut prev := as_finite_f64(arr[0]) or { return error('${pred}: non-numeric') }
		for i := 1; i < arr.len; i++ {
			cur := as_finite_f64(arr[i]) or { return error('${pred}: non-numeric') }
			ok := match mode {
				'non_decreasing' { prev - tol <= cur }
				'strictly_increasing' { prev + tol < cur }
				'non_increasing' { prev + tol >= cur }
				'strictly_decreasing' { prev - tol > cur }
				else { false }
			}

			if !ok {
				return error('${pred}: monotonic ${mode} violated at index ${i}')
			}
			prev = cur
		}
	}
	if delta_v := rel['step_max_delta'] {
		delta := as_finite_f64(delta_v) or { return error('${pred}: invalid step_max_delta') }
		arr := j_arr(actual) or { return error('${pred}: expected array for step_max_delta') }
		if delta <= 0.0 || arr.len == 0 {
			return error('${pred}: invalid step_max_delta sequence')
		}
		mut prev := as_finite_f64(arr[0]) or { return error('${pred}: non-numeric') }
		for i := 1; i < arr.len; i++ {
			cur := as_finite_f64(arr[i]) or { return error('${pred}: non-numeric') }
			if math.abs(cur - prev) > delta + tol {
				return error('${pred}: step_max_delta ${delta} exceeded at index ${i}')
			}
			prev = cur
		}
	}
	if st_v := rel['sum_total'] {
		if is_relational_table(actual) {
			return error('${pred}: literal relational table cannot satisfy sum_total')
		}
		mut vals := []json2.Any{}
		if arr := j_arr(actual) {
			vals = arr.clone()
		} else if mp := j_map(actual) {
			for _, v in mp {
				vals << v
			}
		} else {
			return error('${pred}: expected array or map for sum_total')
		}
		if vals.len == 0 {
			return error('${pred}: empty container for sum_total')
		}
		mut total := 0.0
		for it in vals {
			total += as_finite_f64(it) or { return error('${pred}: non-numeric sum_total element') }
		}
		if tgt := as_finite_f64(st_v) {
			if math.abs(total - tgt) > tol {
				return error('${pred}: sum_total ${total} != ${tgt}')
			}
		} else if stm := j_map(st_v) {
			if eq_v := stm['eq'] {
				if math.abs(total - (as_finite_f64(eq_v) or { return error('${pred}: bad eq') })) > tol {
					return error('${pred}: sum_total mismatch')
				}
			}
			if min_v := stm['min'] {
				if total + tol < (as_finite_f64(min_v) or { return error('${pred}: bad min') }) {
					return error('${pred}: sum_total < min')
				}
			}
			if max_v := stm['max'] {
				if total - tol > (as_finite_f64(max_v) or { return error('${pred}: bad max') }) {
					return error('${pred}: sum_total > max')
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
	if sc := j_map(view['scope'] or { json2.Null{} }) {
		for it in arr_field(sc, 'writes') {
			if s := j_str(it) {
				scope_writes << s
			}
		}
	}
	mut has_cw := false
	mut raw_allowed := scope_writes.clone()
	if cm := j_map((j_map(view['cases'] or { json2.Null{} }) or {
		map[string]json2.Any{}
	})[case_id] or { json2.Null{} })
	{
		if cw := j_arr(cm['writes'] or { json2.Null{} }) {
			has_cw = true
			raw_allowed = cw.filter(it is string).map(it.str())
		}
	}
	mut allowed := map[string]bool{}
	mut bases := map[string]bool{}
	for item in raw_allowed {
		allowed[item] = true
		bases[item.all_before('#')] = true
	}
	return allowed, bases, has_cw
}

fn is_write_resource_allowed(res string, allowed map[string]bool, bases map[string]bool) bool {
	base := res.all_before('#')
	return res in allowed || base in allowed || (!res.contains('#') && res in bases)
}

fn forbidden_writes_of(view map[string]json2.Any, case_id string) []string {
	allowed, bases, has_cw := allowed_write_sets_of(view, case_id)
	if !has_cw {
		return []string{}
	}
	mut out := []string{}
	if sc := j_map(view['scope'] or { json2.Null{} }) {
		for it in arr_field(sc, 'writes') {
			if s := j_str(it) {
				if !is_write_resource_allowed(s, allowed, bases) {
					out << s
				}
			}
		}
	}
	return out
}

fn verify_single_frame_obs(pfx string, res string, obs json2.Any, is_ambient bool) ! {
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
			if n > 0 {
				return error('${pfx}: ${write_lbl}: expected 0 writes, observed ${n}')
			}
			return
		}
	}
	if m := j_map(obs) {
		mut checked := false
		for wk in ['writes', 'operations', 'events'] {
			if wv := m[wk] {
				if wn := as_finite_f64(wv) {
					if wn < 0 || wn != math.trunc(wn) {
						return error('${pfx}: invalid frame ${wk} for "${res}"')
					}
					checked = true
					if wn > 0 {
						return error('${pfx}: ${write_lbl}: expected 0 writes, observed ${wn}')
					}
				} else if arr := j_arr(wv) {
					checked = true
					if arr.len > 0 {
						return error('${pfx}: ${write_lbl}: expected 0 writes, observed ${arr.len}')
					}
				} else {
					return error('${pfx}: invalid frame ${wk} for "${res}"')
				}
			}
		}
		if bef := m['before'] {
			if aft := m['after'] {
				checked = true
				if !values_equal(bef, aft) {
					return error('${pfx}: ${snap_lbl}: before and after snapshots differ')
				}
			}
		}
		if checked {
			return
		}
	}
	return error('${pfx}: frame observation for "${res}" must supply writes/operations/events or before/after snapshots')
}

pub fn synthesize_leaf_witness(expected json2.Any, built map[string]json2.Any, proj_then map[string]string) json2.Any {
	if !is_relational_table(expected) {
		return expected
	}
	rel := desugar_03_rel(expected.as_map())
	if in_arr := j_arr(rel['in'] or { json2.Null{} }) {
		if in_arr.len > 0 {
			return in_arr[0]
		}
	}
	if sum_arr := j_arr(rel['sum_fields'] or { json2.Null{} }) {
		mut total := 0.0
		doc := json2.Any(built)
		for item in sum_arr {
			if s := j_str(item) {
				if peer := resolve_peer_target(doc, proj_then, s) {
					total += as_finite_f64(peer) or { 0.0 }
				}
			}
		}
		r := round_decimal_witness(total)
		return if math.floor(r) == r && math.abs(r) <= 9007199254740991.0 {
			json2.Any(i64(r))
		} else {
			json2.Any(r)
		}
	}
	for k in ['eq', 'approx', 'min', 'max'] {
		if v := rel[k] {
			return v
		}
	}
	if pf := j_str(rel['prefix'] or { json2.Null{} }) {
		return json2.Any(pf + (j_str(rel['suffix'] or { json2.Null{} }) or { '' }))
	}
	if ct := j_arr(rel['contains'] or { json2.Null{} }) {
		return json2.Any(ct)
	}
	if ne := j_bool(rel['non_empty'] or { json2.Null{} }) {
		if ne {
			return json2.Any('x')
		}
	}
	return json2.Any(0)
}
