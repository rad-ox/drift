module drift_v

import math
import x.json2

fn scale_constraint_number(v json2.Any, ratio f64) json2.Any {
	if n := as_finite_f64(v) {
		return json2.Any(n * ratio)
	}
	return v
}

fn normalize_constraint_03(raw map[string]json2.Any, contract map[string]json2.Any, pred string) !map[string]json2.Any {
	mut out := desugar_03_rel(raw)
	cf := raw['convert_from'] or { return out }
	from := cf.str()
	mut units := map[string]json2.Any{}
	if u := contract['units'] {
		if u is map[string]json2.Any {
			units = u.clone()
		}
	} else if u := raw['unit_conversion'] {
		if u is map[string]json2.Any {
			units = u.clone()
		}
	}
	mut target := (raw['unit'] or { json2.Any('') }).str()
	if schema := contract['schema'] {
		if schema is map[string]json2.Any {
			if then_schema := schema['then'] {
				if then_schema is map[string]json2.Any {
					if ps := then_schema[pred] {
						if ps is map[string]json2.Any {
							if unit := ps['unit'] {
								target = unit.str()
							}
						}
					}
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
		mut count := 0
		for k, r in units {
			if k.starts_with('${from}->') {
				count++
				ratio = as_finite_f64(r) or { 0.0 }
			}
		}
		if count != 1 {
			ratio = 0.0
		}
	}
	if ratio <= 0 || math.is_inf(ratio, 0) || math.is_nan(ratio) {
		return error('${pred}: missing unit conversion from ${from}')
	}
	for k in ['eq', 'approx', 'min', 'max', 'abs_tol', 'step_max_delta'] {
		if v := out[k] {
			out[k] = scale_constraint_number(v, ratio)
		}
	}
	for k in ['in', 'not_in'] {
		if v := out[k] {
			if v is []json2.Any {
				out[k] = json2.Any(v.map(scale_constraint_number(it, ratio)))
			}
		}
	}
	if st := out['sum_total'] {
		if st is map[string]json2.Any {
			mut scaled := map[string]json2.Any{}
			for k, v in st {
				scaled[k] = scale_constraint_number(v, ratio)
			}
			out['sum_total'] = json2.Any(scaled)
		} else {
			out['sum_total'] = scale_constraint_number(st, ratio)
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
