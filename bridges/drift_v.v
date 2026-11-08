// Zero-dependency native V test bridge for DRIFT (SPEC §§9, 25, D245).
module drift_v

import crypto.sha256
import os
import x.json2

pub const adapter_id = 'drift_v.v@0.4.0'
pub const bridge_version = '0.4.0'

const env_keys = ['adapter', 'config', 'deps', 'drift', 'policy', 'runner', 'toolchain']!

pub struct RunOptions {
pub:
	contract            string
	test                string
	cases               []string
	level               string = 'unit'
	resolved_dir        string
	events_dir          string
	mutation_events_dir string
}

pub struct DriftContext {
pub:
	contract_id    string
	test_id        string
	canonical_test string
	cases          []string
	level          string
pub mut:
	view         map[string]json2.Any
	read_keys    map[string]map[string]bool
	inputs       map[string]string
	self_stubbed bool
	in_mutation  bool
}

pub fn normalize_crlf_bytes(raw []u8) []u8 {
	for b in raw {
		if b == 0 {
			return raw
		}
	}
	mut has_crlf := false
	for i := 0; i + 1 < raw.len; i++ {
		if raw[i] == 13 && raw[i + 1] == 10 {
			has_crlf = true
			break
		}
	}
	if !has_crlf {
		return raw
	}
	mut out := []u8{cap: raw.len}
	mut i := 0
	for i < raw.len {
		if i + 1 < raw.len && raw[i] == 13 && raw[i + 1] == 10 {
			out << 10
			i += 2
		} else {
			out << raw[i]
			i++
		}
	}
	return out
}

pub fn hash_fixture_bytes(raw []u8) string {
	norm := normalize_crlf_bytes(raw)
	return 'sha256:${sha256.hexhash(norm.bytestr())}'
}

pub fn canonical_test_id(test string) !(string, string, string) {
	trimmed := test.trim_space()
	hash := trimmed.index_u8(`#`)
	if hash <= 0 || hash + 1 >= trimmed.len {
		return error('test id "${test}" must have form <class>#<method>')
	}
	cls := trimmed[..hash]
	raw_mth := trimmed[hash + 1..]
	mut mth := raw_mth
	for ch in [`(`, `[`] {
		idx := mth.index_u8(ch)
		if idx >= 0 {
			mth = mth[..idx]
		}
	}
	mth = mth.trim_space()
	if cls == '' || mth == '' || cls.contains('#') || mth.contains('#') {
		return error('invalid test id "${test}"')
	}
	return cls, mth, '${cls}#${mth}'
}

fn resolve_env_map() !map[string]string {
	raw := os.getenv('DRIFT_ENV').trim_space()
	pk := os.getenv('DRIFT_PROOF_KEY').trim_space()
	if raw == '' && pk !in ['1', 'true'] {
		return map[string]string{}
	}
	mut base := {
		'adapter':   adapter_id
		'config':    'default'
		'deps':      'none'
		'drift':     bridge_version
		'policy':    'core@1'
		'runner':    'v-test'
		'toolchain': 'v@0.5.1'
	}
	if raw != '' {
		doc := json2.decode[json2.Any](raw) or { return error('DRIFT_ENV must be valid JSON') }
		if doc !is map[string]json2.Any {
			return error('DRIFT_ENV must be a JSON object')
		}
		for k, v in doc.as_map() {
			if k !in env_keys || v !is string || v.str().trim_space() == '' {
				return error('invalid DRIFT_ENV key "${k}"')
			}
			base[k] = v.str().trim_space()
		}
	}
	return base
}

fn find_drift_cli() string {
	env_cli := os.getenv('DRIFT_CLI').trim_space()
	if env_cli != '' {
		return env_cli
	}
	mut dir := os.getwd()
	for {
		cand := os.join_path(dir, '.build', 'drift')
		if os.is_executable(cand) {
			return cand
		}
		parent := os.dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return 'drift'
}

fn load_contract_view(contract_id string, resolved_dir string) !map[string]json2.Any {
	rdir := if resolved_dir != '' {
		resolved_dir
	} else {
		os.getenv('DRIFT_RESOLVED').trim_space()
	}
	if rdir != '' {
		p := os.join_path(rdir, '${contract_id}.json')
		txt := os.read_file(p) or { return error('cannot read resolved view ${p}') }
		doc := json2.decode[json2.Any](txt) or { return error('invalid JSON in ${p}') }
		if doc !is map[string]json2.Any {
			return error('resolved view ${p} is not a JSON object')
		}
		return doc.as_map()
	}
	mut dir := os.getwd()
	mut toml_path := ''
	for {
		cand := os.join_path(dir, '.drift', 'contracts', '${contract_id}.toml')
		if os.is_file(cand) {
			toml_path = cand
			break
		}
		parent := os.dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	if toml_path == '' {
		return error('cannot locate contract ${contract_id}.toml')
	}
	cli := find_drift_cli()
	res := os.execute('"${cli}" show "${toml_path}" --as json')
	if res.exit_code != 0 {
		return error('drift show failed for ${toml_path}: ${res.output}')
	}
	doc := json2.decode[json2.Any](res.output) or {
		return error('invalid JSON from drift show ${toml_path}')
	}
	if doc !is map[string]json2.Any {
		return error('drift show output is not a JSON object')
	}
	return doc.as_map()
}

fn (ctx &DriftContext) case_map(case_id string) !map[string]json2.Any {
	if case_id !in ctx.cases {
		return error('case "${case_id}" is not tagged on test "${ctx.test_id}"')
	}
	cases_any := ctx.view['cases'] or { return error('contract "${ctx.contract_id}" has no cases') }
	if cases_any !is map[string]json2.Any {
		return error('missing case "${case_id}"')
	}
	c_any := cases_any.as_map()[case_id] or {
		return error('contract "${ctx.contract_id}" has no case "${case_id}"')
	}
	if c_any !is map[string]json2.Any {
		return error('missing case "${case_id}"')
	}
	return c_any.as_map()
}

fn (mut ctx DriftContext) mark_read(case_id string, key string) {
	if case_id !in ctx.read_keys {
		ctx.read_keys[case_id] = map[string]bool{}
	}
	ctx.read_keys[case_id][key] = true
}

pub fn (ctx &DriftContext) when_any(case_id string, key string) !json2.Any {
	cm := ctx.case_map(case_id)!
	w_any := cm['when'] or { return error('case "${case_id}" has no when table') }
	if w_any is map[string]json2.Any {
		if val := w_any[key] {
			return val
		}
	}
	return error('case "${case_id}" has no when."${key}"')
}

pub fn (ctx &DriftContext) when_str(case_id string, key string) !string {
	v := ctx.when_any(case_id, key)!
	if v is string {
		return v
	}
	return error('when."${key}" is not a string')
}

pub fn (ctx &DriftContext) when_int(case_id string, key string) !i64 {
	v := ctx.when_any(case_id, key)!
	f := as_finite_f64(v) or { return error('when."${key}" is not a number') }
	return i64(f)
}

pub fn (ctx &DriftContext) find_when_str(case_id string, key string, fallback string) string {
	return ctx.when_str(case_id, key) or { fallback }
}

pub fn (mut ctx DriftContext) then_any(case_id string, key string) !json2.Any {
	cm := ctx.case_map(case_id)!
	t_any := cm['then'] or { return error('case "${case_id}" has no then table') }
	if t_any is map[string]json2.Any {
		if val := t_any[key] {
			ctx.mark_read(case_id, key)
			return val
		}
	}
	return error('case "${case_id}" has no then."${key}"')
}

pub fn (mut ctx DriftContext) then_str(case_id string, key string) !string {
	v := ctx.then_any(case_id, key)!
	if v is string {
		return v
	}
	return error('then."${key}" is not a string')
}

pub fn (mut ctx DriftContext) then_int(case_id string, key string) !i64 {
	v := ctx.then_any(case_id, key)!
	f := as_finite_f64(v) or { return error('then."${key}" is not a number') }
	return i64(f)
}

pub fn (mut ctx DriftContext) then_bool(case_id string, key string) !bool {
	v := ctx.then_any(case_id, key)!
	if v is bool {
		return v
	}
	return error('then."${key}" is not a bool')
}

pub fn (mut ctx DriftContext) record_input(rel_path string, digest string) {
	if !ctx.in_mutation {
		norm := rel_path.replace('\\', '/').trim_left('/')
		ctx.inputs[norm] = digest
	}
}

pub fn (mut ctx DriftContext) read_fixture(rel_path string) !string {
	raw := os.read_bytes(rel_path) or { return error('cannot read fixture "${rel_path}"') }
	ctx.record_input(rel_path, hash_fixture_bytes(raw))
	return raw.bytestr()
}

pub fn (mut ctx DriftContext) verify_golden(rel_path string, actual string) ! {
	expected_raw := os.read_bytes(rel_path) or { return error('cannot read golden "${rel_path}"') }
	exp_dig := hash_fixture_bytes(expected_raw)
	ctx.record_input(rel_path, exp_dig)
	act_dig := hash_fixture_bytes(actual.bytes())
	if exp_dig != act_dig {
		return error('golden mismatch for "${rel_path}": expected ${exp_dig}, got ${act_dig}')
	}
}

fn extract_then_projections(view map[string]json2.Any) map[string]string {
	mut out := map[string]string{}
	if proj_any := view['projections'] {
		if proj_any is map[string]json2.Any {
			for k, v in proj_any {
				if k !in ['when', 'then'] && v is string {
					out[k] = v
				}
			}
			if t_any := proj_any['then'] {
				if t_any is map[string]json2.Any {
					for k, v in t_any {
						if v is string {
							out[k] = v
						}
					}
				}
			}
		}
	}
	return out
}

fn extract_when_projections(view map[string]json2.Any) map[string]string {
	mut out := map[string]string{}
	if proj_any := view['projections'] {
		if proj_any is map[string]json2.Any {
			for k, v in proj_any {
				if k !in ['when', 'then'] && v is string {
					out[k] = v
				}
			}
			if w_any := proj_any['when'] {
				if w_any is map[string]json2.Any {
					for k, v in w_any {
						if v is string {
							out[k] = v
						}
					}
				}
			}
		}
	}
	return out
}

pub type AdverseExecuteFn = fn (string) !string

pub fn (mut ctx DriftContext) check_adverse(case_id string, variants_json []string, exec AdverseExecuteFn) ! {
	if variants_json.len == 0 {
		return error('check_adverse for ${ctx.contract_id}.${case_id} requires at least one variant')
	}
	cm := ctx.case_map(case_id)!
	proj_when := extract_when_projections(ctx.view)
	mut when_map := map[string]json2.Any{}
	if w_any := cm['when'] {
		if w_any is map[string]json2.Any {
			when_map = w_any.clone()
		}
	}
	for v_json in variants_json {
		v_doc := json2.decode[json2.Any](v_json) or { return error('variant is not valid JSON') }
		if v_doc is map[string]json2.Any {
			for wk, wexp in when_map {
				ptr := proj_when[wk] or { '/' + escape_pointer(wk) }
				if v_act := resolve_pointer(v_doc, ptr) {
					if !values_equal(v_act, wexp) {
						return error('${ctx.contract_id}.${case_id}.when.${wk} fixture mismatch: got ${v_act.json_str()}, expected ${wexp.json_str()}')
					}
				}
			}
		}
		obs_json := exec(v_json)!
		ctx.check_projection(case_id, obs_json)!
	}
}

pub fn (mut ctx DriftContext) check_frame(case_id string, frame_json string) ! {
	_ := ctx.case_map(case_id)!
	forbidden := forbidden_writes_of(ctx.view, case_id)
	doc := json2.decode[json2.Any](frame_json) or { return error('frame_json is not valid JSON') }
	if doc !is map[string]json2.Any {
		return error('frame_json must be a JSON object')
	}
	fmap := doc.as_map()
	pfx := '${ctx.contract_id}.${case_id}'
	mut checked_keys := map[string]bool{}
	for res in forbidden {
		base_res := res.all_before('#')
		checked_keys[res] = true
		checked_keys[base_res] = true
		obs := fmap[res] or {
			fmap[base_res] or {
				return error('${pfx}: missing frame observation for forbidden write resource "${res}"')
			}
		}
		verify_single_frame_obs(pfx, res, obs, false)!
		ctx.mark_read(case_id, '@frame:${res}')
	}
	allowed, allowed_bases, _ := allowed_write_sets_of(ctx.view, case_id)
	mut fkeys := fmap.keys()
	fkeys.sort()
	for k in fkeys {
		if k in checked_keys || is_write_resource_allowed(k, allowed, allowed_bases) {
			continue
		}
		if obs_k := fmap[k] {
			verify_single_frame_obs(pfx, k, obs_k, true)!
		}
	}
}

pub fn (mut ctx DriftContext) check_projection(case_id string, payload_json string) ! {
	cm := ctx.case_map(case_id)!
	t_any := cm['then'] or { return error('case "${case_id}" has no then table') }
	if t_any !is map[string]json2.Any {
		return error('case "${case_id}" then is not a table')
	}
	doc := json2.decode[json2.Any](payload_json) or { return error('payload is not valid JSON') }
	proj_then := extract_then_projections(ctx.view)
	check_ui_projection_guards(ctx.contract_id, case_id, doc, proj_then, t_any.as_map())!
	for pred, expected in t_any.as_map() {
		ctx.mark_read(case_id, pred)
		if is_relational_table(expected) && ('allowed_keys' in expected.as_map()
			|| 'forbid_keys' in expected.as_map()) && pred !in proj_then {
			mut target := doc
			if doc is map[string]json2.Any {
				if sub := doc[pred] {
					if sub is map[string]json2.Any {
						target = json2.Any(sub.clone())
					}
				}
			}
			check_relational_leaf(doc, target, expected.as_map(), proj_then, pred)!
			continue
		}
		ptr := proj_then[pred] or { '/' + escape_pointer(pred) }
		actual := resolve_pointer(doc, ptr) or {
			return error('missing pointer "${ptr}" for predicate "${pred}"')
		}
		if is_relational_table(expected) {
			check_relational_leaf(doc, actual, expected.as_map(), proj_then, pred)!
		} else if !values_equal(actual, expected) {
			return error('mismatch on "${pred}" (${ptr}): got ${actual.json_str()}, expected ${expected.json_str()}')
		}
	}
	if doc is map[string]json2.Any {
		if fr_any := doc['_frame'] {
			if fr_any is map[string]json2.Any {
				ctx.check_frame(case_id, json2.Any(fr_any).json_str())!
			}
		}
	}
}

fn build_projected_json(view map[string]json2.Any, case_id string) !string {
	cases_any := view['cases'] or { return error('contract has no cases') }
	if cases_any !is map[string]json2.Any {
		return error('invalid cases map')
	}
	c_any := cases_any.as_map()[case_id] or { return error('unknown case "${case_id}"') }
	if c_any !is map[string]json2.Any {
		return error('invalid case "${case_id}"')
	}
	cm := c_any.as_map()
	if st_any := cm['status'] {
		if st_any is string && st_any != '' {
			return error('cannot synthesize stub for ${st_any} case "${case_id}"')
		}
	}
	t_any := cm['then'] or { return error('case "${case_id}" has no then table') }
	if t_any !is map[string]json2.Any {
		return error('case "${case_id}" has invalid then table')
	}
	proj_then := extract_then_projections(view)
	then_map := t_any.as_map()
	mut built := map[string]json2.Any{}
	for pred, expected in then_map {
		if is_relational_table(expected) && 'sum_fields' in expected.as_map() {
			continue
		}
		ptr := normalize_pointer(proj_then[pred] or { '/' + escape_pointer(pred) })
		val := synthesize_leaf_witness(expected, built, proj_then)
		write_pointer(mut built, ptr, val)
	}
	for pred, expected in then_map {
		if !is_relational_table(expected) || 'sum_fields' !in expected.as_map() {
			continue
		}
		ptr := normalize_pointer(proj_then[pred] or { '/' + escape_pointer(pred) })
		val := synthesize_leaf_witness(expected, built, proj_then)
		write_pointer(mut built, ptr, val)
	}
	return json2.Any(built).json_str()
}

pub fn (mut ctx DriftContext) build_output(case_id string) !string {
	if case_id !in ctx.cases {
		return error('case "${case_id}" is not tagged on test "${ctx.test_id}"')
	}
	if !ctx.in_mutation {
		ctx.self_stubbed = true
		ctx.record_input('.drift/self-stub/${ctx.contract_id}', 'sha256:self-stub')
	}
	return build_projected_json(ctx.view, case_id)
}

pub fn (mut ctx DriftContext) build_stub(target string, case_id string, resolved_dir string) !string {
	if target == ctx.contract_id {
		if !ctx.in_mutation {
			ctx.self_stubbed = true
			ctx.record_input('.drift/self-stub/${ctx.contract_id}', 'sha256:self-stub')
		}
		return build_projected_json(ctx.view, case_id)
	}
	up_view := load_contract_view(target, resolved_dir)!
	if !ctx.in_mutation {
		prod_id := if id_any := up_view['id'] { id_any.str() } else { target }
		prod_ref := if r_any := up_view['ref'] {
			r_any.str()
		} else if d_any := up_view['digest'] {
			d_any.str()
		} else {
			'sha256:seam-stub'
		}
		ctx.record_input('.drift/seam-stub/${prod_id}#${case_id}', prod_ref)
	}
	return build_projected_json(up_view, case_id)
}

fn (ctx &DriftContext) fully_read_cases() []string {
	mut out := []string{}
	cases_any := ctx.view['cases'] or { return out }
	if cases_any !is map[string]json2.Any {
		return out
	}
	cm_all := cases_any.as_map()
	for cid in ctx.cases {
		c_any := cm_all[cid] or { continue }
		if c_any !is map[string]json2.Any {
			continue
		}
		t_any := c_any.as_map()['then'] or { continue }
		if t_any !is map[string]json2.Any {
			continue
		}
		t_map := t_any.as_map()
		if t_map.len == 0 {
			continue
		}
		if cid !in ctx.read_keys {
			continue
		}
		mut all_read := true
		for k, _ in t_map {
			if !(ctx.read_keys[cid][k] or { false }) {
				all_read = false
				break
			}
		}
		if all_read {
			for fr in forbidden_writes_of(ctx.view, cid) {
				if !(ctx.read_keys[cid]['@frame:${fr}'] or { false }) {
					all_read = false
					break
				}
			}
		}
		if all_read {
			out << cid
		}
	}
	out.sort()
	return out
}

fn update_shard_and_meta(events_dir string, event_line string, cls string, canon_test string, inputs map[string]string, self_stubbed bool) ! {
	os.mkdir_all(events_dir)!
	shard := os.join_path(events_dir, 'v-shard.jsonl')
	meta := os.join_path(events_dir, 'v-shard.meta.json')
	mut existing := if os.is_file(shard) { os.read_file(shard) or { '' } } else { '' }
	existing += event_line + '\n'
	os.write_file(shard, existing)!

	mut classes := [cls]
	mut tests := [canon_test]
	mut all_inputs := map[string]json2.Any{}
	mut stub_list := []string{}
	if os.is_file(meta) {
		if m_txt := os.read_file(meta) {
			if m_doc := json2.decode[json2.Any](m_txt) {
				if m_doc is map[string]json2.Any {
					mm := m_doc.clone()
					if c_arr := mm['classes'] {
						if c_arr is []json2.Any {
							for item in c_arr {
								s := item.str()
								if s !in classes {
									classes << s
								}
							}
						}
					}
					if t_arr := mm['tests'] {
						if t_arr is []json2.Any {
							for item in t_arr {
								s := item.str()
								if s !in tests {
									tests << s
								}
							}
						}
					}
					if inp_any := mm['inputs'] {
						if inp_any is map[string]json2.Any {
							for k, v in inp_any {
								all_inputs[k] = v
							}
						}
					}
					if sb_any := mm['self_stubbed'] {
						if sb_any is []json2.Any {
							for item in sb_any {
								s := item.str()
								if s !in stub_list {
									stub_list << s
								}
							}
						}
					}
				}
			}
		}
	}
	classes.sort()
	tests.sort()
	if inputs.len > 0 {
		mut my_inps := map[string]json2.Any{}
		if prev := all_inputs[canon_test] {
			if prev is map[string]json2.Any {
				for k, v in prev {
					my_inps[k] = v
				}
			}
		}
		for k, v in inputs {
			my_inps[k] = json2.Any(v)
		}
		all_inputs[canon_test] = json2.Any(my_inps)
	}
	if self_stubbed && canon_test !in stub_list {
		stub_list << canon_test
		stub_list.sort()
	}
	mut meta_obj := map[string]json2.Any{}
	meta_obj['version'] = json2.Any(1)
	meta_obj['classes'] = json2.Any(classes.map(json2.Any(it)))
	meta_obj['tests'] = json2.Any(tests.map(json2.Any(it)))
	snap := os.getenv('DRIFT_SNAPSHOT').trim_space()
	if snap.len in [40, 64] {
		meta_obj['snapshot'] = json2.Any(snap)
	}
	if all_inputs.len > 0 {
		meta_obj['inputs'] = json2.Any(all_inputs)
	}
	if stub_list.len > 0 {
		meta_obj['self_stubbed'] = json2.Any(stub_list.map(json2.Any(it)))
	}
	env_map := resolve_env_map()!
	if env_map.len > 0 {
		mut em := map[string]json2.Any{}
		for k, v in env_map {
			em[k] = json2.Any(v)
		}
		meta_obj['env'] = json2.Any(em)
	}
	os.write_file(meta, json2.Any(meta_obj).json_str() + '\n')!
}

fn apply_mutant_to_view(base_view map[string]json2.Any, cid string, path string, after json2.Any) map[string]json2.Any {
	raw_json := json2.Any(base_view).json_str()
	cloned_any := json2.decode[json2.Any](raw_json) or { return base_view }
	if cloned_any !is map[string]json2.Any {
		return base_view
	}
	mut cloned := cloned_any.as_map()
	side := if path.starts_with('/cases/${escape_pointer(cid)}/when/') { 'when' } else { 'then' }
	prefix := '/cases/${escape_pointer(cid)}/${side}/'
	if !path.starts_with(prefix) {
		return cloned
	}
	segs := path[prefix.len..].split('/').map(unescape_pointer(it))
	if segs.len == 0 || segs[0] == '' {
		return cloned
	}
	mut cases_map := (cloned['cases'] or { return cloned }).as_map()
	mut case_obj := (cases_map[cid] or { return cloned }).as_map()
	mut side_map := (case_obj[side] or { return cloned }).as_map()
	k0 := segs[0]
	if segs.len == 1 {
		side_map[k0] = after
	} else if segs.len == 2 {
		k1 := segs[1]
		if after is map[string]json2.Any {
			am := after.clone()
			if k0 in side_map && k1 in side_map && k0 in am && k1 in am {
				side_map[k0] = am[k0] or { json2.Null{} }
				side_map[k1] = am[k1] or { json2.Null{} }
				case_obj[side] = json2.Any(side_map)
				cases_map[cid] = json2.Any(case_obj)
				cloned['cases'] = json2.Any(cases_map)
				return cloned
			}
		}
		if cur_rel := side_map[k0] {
			if cur_rel is map[string]json2.Any {
				mut rel_m := cur_rel.clone()
				rel_m[k1] = after
				side_map[k0] = json2.Any(rel_m)
			}
		}
	}
	case_obj[side] = json2.Any(side_map)
	cases_map[cid] = json2.Any(case_obj)
	cloned['cases'] = json2.Any(cases_map)
	return cloned
}

fn run_in_process_mutants(opts RunOptions, base_view map[string]json2.Any, cb fn (mut DriftContext) !) ! {
	mut_file := os.getenv('DRIFT_MUTANTS').trim_space()
	if opts.events_dir != '' && opts.mutation_events_dir == '' {
		return
	}
	mut_dir := if opts.mutation_events_dir != '' {
		opts.mutation_events_dir
	} else {
		os.getenv('DRIFT_MUTATION_EVENTS').trim_space()
	}
	if mut_file == '' || mut_dir == '' || !os.is_file(mut_file) {
		return
	}
	raw_bytes := os.read_bytes(mut_file)!
	manifest_id := 'sha256:${sha256.hexhash(raw_bytes.bytestr())}'
	doc := json2.decode[json2.Any](raw_bytes.bytestr()) or {
		return error('invalid DRIFT_MUTANTS JSON')
	}
	if doc !is map[string]json2.Any {
		return
	}
	contracts_any := doc.as_map()['contracts'] or { return }
	if contracts_any !is []json2.Any {
		return
	}
	contracts_arr := contracts_any.as_array()
	os.mkdir_all(mut_dir)!
	out_file := os.join_path(mut_dir, 'v-mutants.jsonl')
	mut lines := if os.is_file(out_file) { os.read_file(out_file) or { '' } } else { '' }
	_, _, canon_test := canonical_test_id(opts.test)!
	for c_item in contracts_arr {
		if c_item !is map[string]json2.Any {
			continue
		}
		cm := c_item.as_map()
		mc := (cm['id'] or { json2.Any('') }).str()
		cdig := (cm['digest'] or { json2.Any('') }).str()
		if mc != opts.contract {
			continue
		}
		muts_any := cm['mutants'] or { continue }
		if muts_any !is []json2.Any {
			continue
		}
		for item in muts_any.as_array() {
			if item !is map[string]json2.Any {
				continue
			}
			mm := item.as_map()
			mcase := (mm['case'] or { json2.Any('') }).str()
			mid := (mm['id'] or { json2.Any('') }).str()
			mpath := (mm['path'] or { json2.Any('') }).str()
			mafter := mm['after'] or { continue }
			if mcase !in opts.cases || mid == '' {
				continue
			}
			mut mut_ctx := DriftContext{
				contract_id:    opts.contract
				test_id:        opts.test
				canonical_test: canon_test
				cases:          opts.cases
				level:          opts.level
				view:           apply_mutant_to_view(base_view, mcase, mpath, mafter)
				read_keys:      map[string]map[string]bool{}
				inputs:         map[string]string{}
				in_mutation:    true
			}
			mut killed := false
			cb(mut mut_ctx) or { killed = true }
			outcome := if killed { 'killed' } else { 'survived' }
			mut ev := map[string]json2.Any{}
			ev['manifest'] = json2.Any(manifest_id)
			ev['contract'] = json2.Any(opts.contract)
			ev['digest'] = json2.Any(cdig)
			ev['mutant'] = json2.Any(mid)
			ev['case'] = json2.Any(mcase)
			ev['outcome'] = json2.Any(outcome)
			ev['control'] = json2.Any('passed')
			lines += json2.Any(ev).json_str() + '\n'
		}
	}
	os.write_file(out_file, lines)!
}

pub fn run_drift_case(opts RunOptions, cb fn (mut DriftContext) !) !string {
	if opts.contract.trim_space() == '' || opts.cases.len == 0 {
		return error('contract and cases are required')
	}
	cls, _, canon_test := canonical_test_id(opts.test)!
	view := load_contract_view(opts.contract, opts.resolved_dir)!
	digest := (view['digest'] or { json2.Any('') }).str()
	ev_dir := if opts.events_dir != '' {
		opts.events_dir
	} else {
		os.getenv('DRIFT_EVENTS').trim_space()
	}
	mut ctx := DriftContext{
		contract_id:    opts.contract
		test_id:        opts.test
		canonical_test: canon_test
		cases:          opts.cases
		level:          if opts.level != '' { opts.level } else { 'unit' }
		view:           view
		read_keys:      map[string]map[string]bool{}
		inputs:         map[string]string{}
	}
	mut outcome := 'passed'
	mut run_err := ''
	cb(mut ctx) or {
		outcome = 'failed'
		run_err = err.msg()
	}
	if ev_dir != '' {
		mut ev := map[string]json2.Any{}
		ev['cases'] = json2.Any(opts.cases.map(json2.Any(it)))
		ev['contract'] = json2.Any(opts.contract)
		if digest != '' {
			ev['digest'] = json2.Any(digest)
		}
		ev['level'] = json2.Any(ctx.level)
		ev['outcome'] = json2.Any(outcome)
		if outcome == 'passed' {
			read_list := ctx.fully_read_cases()
			if read_list.len > 0 {
				ev['read'] = json2.Any(read_list.map(json2.Any(it)))
			}
		}
		ev['test'] = json2.Any(opts.test)
		update_shard_and_meta(ev_dir, json2.Any(ev).json_str(), cls, canon_test, ctx.inputs,
			ctx.self_stubbed)!
	}
	if outcome != 'passed' {
		return error(run_err)
	}
	run_in_process_mutants(opts, view, cb)!
	return outcome
}

pub const bridge_runtime_baseline = 'v-0.5.2'

pub const bridge_capabilities_list = [
	'allowed_keys',
	'case_frames',
	'counterexample_replay',
	'forbid_keys',
	'inventory_sidecar',
	'mutants',
	'not_in',
	'predicates',
	'projections',
	'relational_bounds',
	'stubs',
]!

pub fn require_capabilities(required []string) ! {
	for cap in required {
		k := cap.trim_space()
		if k == '' || k !in bridge_capabilities_list {
			return error('bridge.capability_unsupported:${k}')
		}
	}
}
