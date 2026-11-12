// Zero-dependency native V test bridge for DRIFT consuming precompiled .plans/<id>.plan.json.
module drift_v

import crypto.sha256
import os
import x.json2

pub const adapter_id = 'drift_v.v@0.6.0'
pub const bridge_version = '0.6.0'
pub const bridge_runtime_baseline = 'v-0.5.2'
pub const bridge_capabilities_list = ['allowed_keys', 'case_frames', 'counterexample_replay',
	'forbid_keys', 'inventory_sidecar', 'mutants', 'not_in', 'predicates', 'projections',
	'relational_bounds', 'stubs']!

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
	plan         map[string]json2.Any
	read_keys    map[string]map[string]bool
	inputs       map[string]string
	self_stubbed bool
	in_mutation  bool
}

pub fn normalize_crlf_bytes(raw []u8) []u8 {
	if 0 in raw {
		return raw
	}
	mut out := []u8{cap: raw.len}
	for i := 0; i < raw.len; i++ {
		if i + 1 < raw.len && raw[i] == 13 && raw[i + 1] == 10 {
			out << 10
			i++
		} else {
			out << raw[i]
		}
	}
	return out
}

pub fn hash_fixture_bytes(raw []u8) string {
	return 'sha256:${sha256.hexhash(normalize_crlf_bytes(raw).bytestr())}'
}

pub fn canonical_test_id(test string) !(string, string, string) {
	trimmed := test.trim_space()
	hash := trimmed.index_u8(`#`)
	if hash <= 0 || hash + 1 >= trimmed.len {
		return error('test id "${test}" must have form <class>#<method>')
	}
	cls := trimmed[..hash]
	mut mth := trimmed[hash + 1..]
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
		'toolchain': 'v@0.6.0'
	}
	if raw != '' {
		doc := json2.decode[json2.Any](raw) or { return error('DRIFT_ENV must be valid JSON') }
		dm := j_map(doc) or { return error('DRIFT_ENV must be a JSON object') }
		for k, v in dm {
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

fn load_contract_plan(contract_id string, resolved_dir string, view map[string]json2.Any) map[string]json2.Any {
	rdir := if resolved_dir != '' { resolved_dir } else { os.getenv('DRIFT_RESOLVED').trim_space() }
	if rdir == '' {
		return map[string]json2.Any{}
	}
	p := os.join_path(rdir, '.plans', '${contract_id}.plan.json')
	txt := os.read_file(p) or { return map[string]json2.Any{} }
	doc := json2.decode[json2.Any](txt) or { return map[string]json2.Any{} }
	pm := j_map(doc) or { return map[string]json2.Any{} }
	pdig := (pm['digest'] or { json2.Any('') }).str()
	vdig := (view['digest'] or { json2.Any('') }).str()
	vref := (view['ref'] or { json2.Any('') }).str()
	if pdig == '' || (pdig != vdig && pdig != vref) {
		return map[string]json2.Any{}
	}
	return pm
}

fn load_contract_view(contract_id string, resolved_dir string) !map[string]json2.Any {
	rdir := if resolved_dir != '' { resolved_dir } else { os.getenv('DRIFT_RESOLVED').trim_space() }
	if rdir != '' {
		p := os.join_path(rdir, '${contract_id}.json')
		txt := os.read_file(p) or { return error('cannot read resolved view ${p}') }
		doc := json2.decode[json2.Any](txt) or { return error('invalid JSON in ${p}') }
		return j_map(doc) or { error('resolved view ${p} is not a JSON object') }
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
	res := os.execute('"${find_drift_cli()}" show "${toml_path}" --as json')
	if res.exit_code != 0 {
		return error('drift show failed for ${toml_path}: ${res.output}')
	}
	doc := json2.decode[json2.Any](res.output) or { return error('invalid JSON from drift show') }
	return j_map(doc) or { error('drift show output is not a JSON object') }
}

fn (ctx &DriftContext) case_map(case_id string) !map[string]json2.Any {
	if case_id !in ctx.cases {
		return error('case "${case_id}" is not tagged on test "${ctx.test_id}"')
	}
	cm_all := j_map(ctx.view['cases'] or { json2.Null{} }) or {
		return error('contract "${ctx.contract_id}" has no cases')
	}
	return j_map(cm_all[case_id] or { json2.Null{} }) or {
		error('contract "${ctx.contract_id}" has no case "${case_id}"')
	}
}

fn (mut ctx DriftContext) mark_read(case_id string, key string) {
	if case_id !in ctx.read_keys {
		ctx.read_keys[case_id] = map[string]bool{}
	}
	ctx.read_keys[case_id][key] = true
}

fn (ctx &DriftContext) unwrap_if_03(val json2.Any) json2.Any {
	if (ctx.view['drift'] or { json2.Any('') }).str() == '0.3' {
		if m := j_map(val) {
			if m.len == 1 {
				if eq_v := m['eq'] {
					return eq_v
				}
			}
		}
	}
	return val
}

pub fn (ctx &DriftContext) when_any(case_id string, key string) !json2.Any {
	cm := ctx.case_map(case_id)!
	wm := j_map(cm['when'] or { json2.Null{} }) or { return error('case "${case_id}" has no when') }
	if val := wm[key] {
		return ctx.unwrap_if_03(val)
	}
	return error('case "${case_id}" has no when."${key}"')
}

pub fn (ctx &DriftContext) when_str(case_id string, key string) !string {
	return j_str(ctx.when_any(case_id, key)!) or { error('when."${key}" is not a string') }
}

pub fn (ctx &DriftContext) when_int(case_id string, key string) !i64 {
	return i64(as_finite_f64(ctx.when_any(case_id, key)!) or {
		return error('when."${key}" is not a number')
	})
}

pub fn (ctx &DriftContext) find_when_str(case_id string, key string, fallback string) string {
	return ctx.when_str(case_id, key) or { fallback }
}

pub fn (mut ctx DriftContext) then_any(case_id string, key string) !json2.Any {
	cm := ctx.case_map(case_id)!
	tm := j_map(cm['then'] or { json2.Null{} }) or { return error('case "${case_id}" has no then') }
	if val := tm[key] {
		ctx.mark_read(case_id, key)
		return ctx.unwrap_if_03(val)
	}
	return error('case "${case_id}" has no then."${key}"')
}

pub fn (mut ctx DriftContext) then_str(case_id string, key string) !string {
	return j_str(ctx.then_any(case_id, key)!) or { error('then."${key}" is not a string') }
}

pub fn (mut ctx DriftContext) then_int(case_id string, key string) !i64 {
	return i64(as_finite_f64(ctx.then_any(case_id, key)!) or {
		return error('then."${key}" is not a number')
	})
}

pub fn (mut ctx DriftContext) then_bool(case_id string, key string) !bool {
	return j_bool(ctx.then_any(case_id, key)!) or { error('then."${key}" is not a bool') }
}

pub fn (mut ctx DriftContext) record_input(rel_path string, digest string) {
	if !ctx.in_mutation {
		ctx.inputs[rel_path.replace('\\', '/').trim_left('/')] = digest
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
	if exp_dig != hash_fixture_bytes(actual.bytes()) {
		return error('golden mismatch for "${rel_path}"')
	}
}

pub type AdverseExecuteFn = fn (string) !string

pub fn (mut ctx DriftContext) check_adverse(case_id string, variants_json []string, exec AdverseExecuteFn) ! {
	if variants_json.len == 0 {
		return error('check_adverse for ${ctx.contract_id}.${case_id} requires at least one variant')
	}
	cm := ctx.case_map(case_id)!
	proj_when := extract_side_projections(ctx.view, 'when')
	when_map := j_map(cm['when'] or { json2.Null{} }) or {
		map[string]json2.Any{}
	}
	pfx := '${ctx.contract_id}.${case_id}'
	for v_json in variants_json {
		v_doc := json2.decode[json2.Any](v_json) or { return error('variant is not valid JSON') }
		_ = check_bola_variant_pair(pfx, v_doc)!
		if v_doc is map[string]json2.Any {
			for wk, wexp in when_map {
				ptr := proj_when[wk] or { '/' + escape_pointer(wk) }
				if v_act := resolve_pointer(v_doc, ptr) {
					if !values_equal(v_act, wexp) {
						return error('${pfx}.when.${wk} fixture mismatch')
					}
				}
			}
		}
		ctx.check_projection(case_id, exec(v_json)!)!
	}
}

fn is_unobserved_frame_entry(obs json2.Any) bool {
	if m := j_map(obs) {
		return !(j_bool(m['observed'] or { json2.Any(true) }) or { true })
	}
	return false
}

fn has_frame_metrics_entry(obs json2.Any) bool {
	if m := j_map(obs) {
		return 'writes' in m || 'operations' in m || 'events' in m
			|| ('before' in m && 'after' in m)
	}
	return false
}

pub fn (mut ctx DriftContext) check_frame(case_id string, frame_json string) ! {
	ctx.check_frame_with_mode(case_id, frame_json, true)!
}

fn (mut ctx DriftContext) check_frame_with_mode(case_id string, frame_json string, strict bool) ! {
	_ := ctx.case_map(case_id)!
	forbidden := forbidden_writes_of(ctx.view, case_id)
	doc := json2.decode[json2.Any](frame_json) or { return error('frame_json is not valid JSON') }
	fmap := j_map(doc) or { return error('frame_json must be a JSON object') }
	pfx := '${ctx.contract_id}.${case_id}'
	mut checked := map[string]bool{}
	for res in forbidden {
		base_res := res.all_before('#')
		checked[res] = true
		checked[base_res] = true
		obs := fmap[res] or {
			fmap[base_res] or {
				if strict {
					return error('${pfx}: missing frame observation for "${res}"')
				}
				continue
			}
		}
		if has_frame_metrics_entry(obs) {
			verify_single_frame_obs(pfx, res, obs, false)!
		}
		if is_unobserved_frame_entry(obs) {
			if strict {
				return error('${pfx}: frame.observer_missing for "${res}"')
			}
			continue
		}
		if !has_frame_metrics_entry(obs) {
			verify_single_frame_obs(pfx, res, obs, false)!
		}
		ctx.mark_read(case_id, '@frame:${res}')
	}
	allowed, bases, _ := allowed_write_sets_of(ctx.view, case_id)
	mut fkeys := fmap.keys()
	fkeys.sort()
	for k in fkeys {
		if k in checked || is_write_resource_allowed(k, allowed, bases) {
			continue
		}
		obs_k := fmap[k] or { continue }
		if has_frame_metrics_entry(obs_k) {
			verify_single_frame_obs(pfx, k, obs_k, true)!
		}
		if is_unobserved_frame_entry(obs_k) {
			if strict {
				return error('${pfx}: frame.observer_missing for perimeter resource "${k}"')
			}
			continue
		}
		if !has_frame_metrics_entry(obs_k) {
			verify_single_frame_obs(pfx, k, obs_k, true)!
		}
	}
}

pub fn (mut ctx DriftContext) check_projection(case_id string, payload_json string) ! {
	cm := ctx.case_map(case_id)!
	t_map := j_map(cm['then'] or { json2.Null{} }) or {
		return error('case "${case_id}" has no then table')
	}
	mut doc := json2.decode[json2.Any](payload_json) or {
		return error('payload is not valid JSON')
	}
	if dm_orig := j_map(doc) {
		mut dm := dm_orig.clone()
		if 'when' !in dm && 'before' !in dm {
			mut w_env := map[string]json2.Any{}
			for wk, wv in map_field(cm, 'when') {
				if wm := j_map(wv) {
					if eq_v := wm['eq'] {
						if 'peer' !in wm && 'eq_field' !in wm {
							w_env[wk] = eq_v
						}
					}
				} else {
					w_env[wk] = wv
				}
			}
			dm['_when_env'] = json2.Any(w_env)
			doc = json2.Any(dm)
		}
	}
	proj_then := extract_side_projections(ctx.view, 'then')
	check_ui_projection_guards(ctx.contract_id, case_id, doc, proj_then, t_map)!
	mut used_plan := false
	if !ctx.in_mutation && ctx.plan.len > 0 {
		if pc := j_map((j_map(ctx.plan['cases'] or { json2.Null{} }) or {
			map[string]json2.Any{}
		})[case_id] or { json2.Null{} })
		{
			ok, preds := eval_compiled_plan_case(ctx.contract_id, case_id, pc, doc)!
			if ok {
				for p in preds {
					ctx.mark_read(case_id, p)
				}
				used_plan = true
			}
		}
	}
	if !used_plan {
		for pred, raw_expected in t_map {
			expected := if is_relational_table(raw_expected) {
				json2.Any(normalize_constraint_03(raw_expected.as_map(), ctx.view, pred)!)
			} else {
				raw_expected
			}
			ctx.mark_read(case_id, pred)
			if is_relational_table(expected) && ('allowed_keys' in expected.as_map()
				|| 'forbid_keys' in expected.as_map()) && pred !in proj_then {
				mut target := doc
				if dm := j_map(doc) {
					if sub := j_map(dm[pred] or { json2.Null{} }) {
						target = json2.Any(sub)
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
	}
	if dm := j_map(doc) {
		if fr := j_map(dm['_frame'] or { json2.Null{} }) {
			mut has_unobs := false
			for _, fv in fr {
				if is_unobserved_frame_entry(fv) {
					has_unobs = true
					break
				}
			}
			ctx.check_frame_with_mode(case_id, json2.Any(fr).json_str(), !has_unobs)!
		}
	}
}

fn build_projected_json(view map[string]json2.Any, plan map[string]json2.Any, case_id string, in_mutation bool) !string {
	cm_all := j_map(view['cases'] or { json2.Null{} }) or { return error('contract has no cases') }
	cm := j_map(cm_all[case_id] or { json2.Null{} }) or {
		return error('unknown case "${case_id}"')
	}
	if st := j_str(cm['status'] or { json2.Null{} }) {
		if st != '' {
			return error('cannot synthesize stub for ${st} case "${case_id}"')
		}
	}
	if !in_mutation && plan.len > 0 {
		if pc := j_map((j_map(plan['cases'] or { json2.Null{} }) or {
			map[string]json2.Any{}
		})[case_id] or { json2.Null{} })
		{
			if stub_out := pc['stub_output'] {
				return stub_out.json_str()
			}
		}
	}
	then_map := j_map(cm['then'] or { json2.Null{} }) or {
		return error('case "${case_id}" has no then table')
	}
	proj_then := extract_side_projections(view, 'then')
	mut built := map[string]json2.Any{}
	for pass in 0 .. 2 {
		for pred, expected in then_map {
			is_sum := is_relational_table(expected) && 'sum_fields' in expected.as_map()
			if (pass == 0 && is_sum) || (pass == 1 && !is_sum) {
				continue
			}
			ptr := normalize_pointer(proj_then[pred] or { '/' + escape_pointer(pred) })
			write_pointer(mut built, ptr, synthesize_leaf_witness(expected, built, proj_then))
		}
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
	return build_projected_json(ctx.view, ctx.plan, case_id, ctx.in_mutation)
}

pub fn (mut ctx DriftContext) build_stub(target string, case_id string, resolved_dir string) !string {
	if target == ctx.contract_id {
		if !ctx.in_mutation {
			ctx.self_stubbed = true
			ctx.record_input('.drift/self-stub/${ctx.contract_id}', 'sha256:self-stub')
		}
		return build_projected_json(ctx.view, ctx.plan, case_id, ctx.in_mutation)
	}
	up_view := load_contract_view(target, resolved_dir)!
	up_plan := load_contract_plan(target, resolved_dir, up_view)
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
	return build_projected_json(up_view, up_plan, case_id, ctx.in_mutation)
}

fn (ctx &DriftContext) fully_read_cases() []string {
	mut out := []string{}
	cm_all := j_map(ctx.view['cases'] or { json2.Null{} }) or { return out }
	for cid in ctx.cases {
		cm := j_map(cm_all[cid] or { continue }) or { continue }
		t_map := j_map(cm['then'] or { continue }) or { continue }
		if t_map.len == 0 || cid !in ctx.read_keys {
			continue
		}
		mut all_read := t_map.keys().all(ctx.read_keys[cid][it] or { false })
		if all_read {
			all_read = forbidden_writes_of(ctx.view, cid).all(ctx.read_keys[cid]['@frame:${it}'] or {
				false
			})
		}
		if all_read {
			out << cid
		}
	}
	out.sort()
	return out
}

fn append_unique_strs(mut dst []string, arr_any json2.Any) {
	for item in j_arr(arr_any) or { []json2.Any{} } {
		s := item.str()
		if s !in dst {
			dst << s
		}
	}
}

fn update_shard_and_meta(events_dir string, event_line string, cls string, canon_test string, inputs map[string]string, self_stubbed bool) ! {
	os.mkdir_all(events_dir)!
	shard := os.join_path(events_dir, 'v-shard.jsonl')
	meta := os.join_path(events_dir, 'v-shard.meta.json')
	existing := if os.is_file(shard) { os.read_file(shard) or { '' } } else { '' }
	os.write_file(shard, existing + event_line + '\n')!

	mut classes := [cls]
	mut tests := [canon_test]
	mut all_inputs := map[string]json2.Any{}
	mut stub_list := []string{}
	if os.is_file(meta) {
		if mm := j_map(json2.decode[json2.Any](os.read_file(meta) or { '' }) or { json2.Null{} }) {
			append_unique_strs(mut classes, mm['classes'] or { json2.Null{} })
			append_unique_strs(mut tests, mm['tests'] or { json2.Null{} })
			append_unique_strs(mut stub_list, mm['self_stubbed'] or { json2.Null{} })
			for k, v in map_field(mm, 'inputs') {
				all_inputs[k] = v
			}
		}
	}
	classes.sort()
	tests.sort()
	if inputs.len > 0 {
		mut my_inps := (j_map(all_inputs[canon_test] or { json2.Null{} }) or {
			map[string]json2.Any{}
		}).clone()
		for k, v in inputs {
			my_inps[k] = json2.Any(v)
		}
		all_inputs[canon_test] = json2.Any(my_inps)
	}
	if self_stubbed && canon_test !in stub_list {
		stub_list << canon_test
		stub_list.sort()
	}
	mut meta_obj := {
		'version': json2.Any(1)
		'classes': json2.Any(classes.map(json2.Any(it)))
		'tests':   json2.Any(tests.map(json2.Any(it)))
	}
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
	cloned_any := json2.decode[json2.Any](json2.Any(base_view).json_str()) or { return base_view }
	mut cloned := (j_map(cloned_any) or { return base_view }).clone()
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
		if am := j_map(after) {
			if k0 in side_map && k1 in side_map && k0 in am && k1 in am {
				side_map[k0] = am[k0] or { json2.Null{} }
				side_map[k1] = am[k1] or { json2.Null{} }
				case_obj[side] = json2.Any(side_map)
				cases_map[cid] = json2.Any(case_obj)
				cloned['cases'] = json2.Any(cases_map)
				return cloned
			}
		}
		if cur_rel := j_map(side_map[k0] or { json2.Null{} }) {
			mut rel_m := cur_rel.clone()
			rel_m[k1] = after
			side_map[k0] = json2.Any(rel_m)
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
	doc := j_map(json2.decode[json2.Any](raw_bytes.bytestr()) or {
		return error('invalid DRIFT_MUTANTS JSON')
	}) or { return }
	contracts_arr := j_arr(doc['contracts'] or { return }) or { return }
	os.mkdir_all(mut_dir)!
	out_file := os.join_path(mut_dir, 'v-mutants.jsonl')
	mut lines := if os.is_file(out_file) { os.read_file(out_file) or { '' } } else { '' }
	_, _, canon_test := canonical_test_id(opts.test)!
	for c_item in contracts_arr {
		cm := j_map(c_item) or { continue }
		if (cm['id'] or { json2.Any('') }).str() != opts.contract {
			continue
		}
		cdig := (cm['digest'] or { json2.Any('') }).str()
		for item in j_arr(cm['mutants'] or { continue }) or { continue } {
			mm := j_map(item) or { continue }
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
			ev := {
				'manifest': json2.Any(manifest_id)
				'contract': json2.Any(opts.contract)
				'digest':   json2.Any(cdig)
				'mutant':   json2.Any(mid)
				'case':     json2.Any(mcase)
				'outcome':  json2.Any(if killed { 'killed' } else { 'survived' })
				'control':  json2.Any('passed')
			}
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
	plan := load_contract_plan(opts.contract, opts.resolved_dir, view)
	digest := if r_any := view['ref'] {
		r_any.str()
	} else {
		(view['digest'] or { json2.Any('') }).str()
	}
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
		plan:           plan
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
		mut ev := {
			'cases':    json2.Any(opts.cases.map(json2.Any(it)))
			'contract': json2.Any(opts.contract)
			'level':    json2.Any(ctx.level)
			'outcome':  json2.Any(outcome)
			'test':     json2.Any(opts.test)
		}
		if digest != '' {
			ev['digest'] = json2.Any(digest)
		}
		if outcome == 'passed' {
			read_list := ctx.fully_read_cases()
			if read_list.len > 0 {
				ev['read'] = json2.Any(read_list.map(json2.Any(it)))
			}
		}
		if (view['drift'] or { json2.Any('') }).str() == '0.3' {
			supported_03 := ['rel-keys-guard/1', 'rel-linear-balance/1', 'rel-peer-sum/1',
				'rel-series/1', 'rel-tol/1', 'unit-conversion/1']
			for item in arr_field(view, 'required_capabilities') {
				if item.str() !in supported_03 {
					return error('bridge.capability_unsupported:${item.str()}')
				}
			}
			ev['schema'] = json2.Any('0.3')
			ev['capabilities'] = json2.Any(supported_03.map(json2.Any(it)))
		}
		update_shard_and_meta(ev_dir, json2.Any(ev).json_str(), cls, canon_test, ctx.inputs,
			ctx.self_stubbed)!
	}
	if outcome != 'passed' {
		return error(run_err)
	}
	run_in_process_mutants(opts, view, cb)!
	return outcome
}

pub fn require_capabilities(required []string) ! {
	for cap in required {
		k := cap.trim_space()
		if k == '' || k !in bridge_capabilities_list {
			return error('bridge.capability_unsupported:${k}')
		}
	}
}
