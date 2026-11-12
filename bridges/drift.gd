# Zero-dependency GDScript 4.3+ forward verification bridge for DRIFT (Godot Engine).
# Conforms to drift.bridge-capabilities/1.
class_name DriftBridge
extends RefCounted

const VERSION: String = "drift.gdscript@0.6.0"
const BRIDGE_RUNTIME_BASELINE: String = "gdscript-4.3"
const CAPABILITIES: Array[String] = [
	"predicates",
	"forbid_keys",
	"not_in",
	"tuning_invariants",
	"case_frames",
	"counterexample_replay",
	"sim_receipt",
]

static func bridge_capabilities() -> Dictionary:
	return {
		"schema": "drift.bridge-capabilities/1",
		"bridge": "drift.gdscript",
		"version": VERSION,
		"runtime_baseline": BRIDGE_RUNTIME_BASELINE,
		"capabilities": CAPABILITIES,
	}

static func require_capabilities(required: Array) -> void:
	for cap in required:
		if not CAPABILITIES.has(str(cap)):
			push_error("bridge.capability_unsupported:" + str(cap))

static func has_key_recursive(val: Variant, fk: String, is_root: bool = true) -> bool:
	if typeof(val) == TYPE_ARRAY:
		for item in (val as Array):
			if has_key_recursive(item, fk, false):
				return true
		return false
	if typeof(val) != TYPE_DICTIONARY:
		return false
	var d: Dictionary = val as Dictionary
	if d.has(fk):
		return true
	for k in d.keys():
		if is_root and str(k) == "_frame" and fk != "_frame" and typeof(d[k]) == TYPE_DICTIONARY:
			continue
		if has_key_recursive(d[k], fk, false):
			return true
	return false

static func check_value(key: String, actual: Variant, expected: Variant) -> bool:
	if typeof(expected) == TYPE_DICTIONARY:
		if (expected as Dictionary).is_empty():
			return false
		var known: Array[String] = ["min", "max", "len", "min_len", "max_len", "non_empty", "prefix", "suffix", "contains", "in", "not_in", "forbid_keys", "allowed_keys", "monotonic", "step_max_delta", "sum_total", "approx", "abs_tol", "rel_tol", "balance_fields", "unit", "unit_conversion"]
		for k in expected.keys():
			if not known.has(str(k)):
				return false
		if expected.has("approx"):
			if not expected.has("abs_tol") and not expected.has("rel_tol"):
				return false
			var ap: float = float(expected["approx"])
			var at: float = float(expected["abs_tol"]) if expected.has("abs_tol") else 0.0
			var rt: float = float(expected["rel_tol"]) if expected.has("rel_tol") else 0.0
			if at < 0.0 or rt < 0.0 or absf(float(actual) - ap) > at + rt * absf(ap):
				return false
		if expected.has("min") and float(actual) + 1e-9 < float(expected["min"]):
			return false
		if expected.has("max") and float(actual) - 1e-9 > float(expected["max"]):
			return false
		if expected.has("non_empty"):
			var act_len: int = (actual as String).length() if typeof(actual) == TYPE_STRING else ((actual as Array).size() if typeof(actual) == TYPE_ARRAY else -1)
			if act_len < 0 or (act_len <= 0 if bool(expected["non_empty"]) else act_len != 0):
				return false
		if expected.has("prefix") and (typeof(actual) != TYPE_STRING or not (actual as String).begins_with(str(expected["prefix"]))):
			return false
		if expected.has("suffix") and (typeof(actual) != TYPE_STRING or not (actual as String).ends_with(str(expected["suffix"]))):
			return false
		if expected.has("contains"):
			if typeof(actual) == TYPE_STRING and not (actual as String).contains(str(expected["contains"])):
				return false
			elif typeof(actual) == TYPE_ARRAY and not (actual as Array).has(expected["contains"]):
				return false
			elif typeof(actual) != TYPE_STRING and typeof(actual) != TYPE_ARRAY:
				return false
		if expected.has("not_in") and (actual == null or (expected["not_in"] as Array).has(actual)):
			return false
		if expected.has("forbid_keys"):
			if typeof(actual) != TYPE_DICTIONARY:
				return false
			if typeof(expected["forbid_keys"]) == TYPE_STRING:
				if not has_key_recursive(actual, str(expected["forbid_keys"]), true):
					return false
			else:
				for fk in expected["forbid_keys"]:
					if has_key_recursive(actual, str(fk), true):
						return false
		if expected.has("monotonic"):
			var mode: String = str(expected["monotonic"])
			if typeof(actual) != TYPE_ARRAY or actual.is_empty():
				return false
			for i in range(1, actual.size()):
				var prev: float = float(actual[i - 1])
				var cur: float = float(actual[i])
				var ok: bool = (
					prev - 1e-9 <= cur if mode == "non_decreasing"
					else prev + 1e-9 < cur if mode == "strictly_increasing"
					else prev + 1e-9 >= cur if mode == "non_increasing"
					else prev - 1e-9 > cur if mode == "strictly_decreasing"
					else false
				)
				if not ok:
					return false
		if expected.has("step_max_delta"):
			var delta: float = float(expected["step_max_delta"])
			if delta <= 0.0 or typeof(actual) != TYPE_ARRAY or actual.is_empty():
				return false
			for i in range(1, actual.size()):
				if absf(float(actual[i]) - float(actual[i - 1])) > delta + 1e-9:
					return false
		if expected.has("sum_total"):
			if typeof(actual) == TYPE_DICTIONARY and not (actual as Dictionary).is_empty() and (actual as Dictionary).keys().all(func(k): return known.has(str(k))):
				return false
			var vals: Array = actual if typeof(actual) == TYPE_ARRAY else ((actual as Dictionary).values() if typeof(actual) == TYPE_DICTIONARY else [])
			if vals.is_empty():
				return false
			var total: float = 0.0
			for item in vals:
				total += float(item)
			var st: Variant = expected["sum_total"]
			if typeof(st) == TYPE_DICTIONARY:
				var stm: Dictionary = st as Dictionary
				if stm.has("eq") and absf(total - float(stm["eq"])) > 1e-9:
					return false
				if stm.has("min") and total + 1e-9 < float(stm["min"]):
					return false
				if stm.has("max") and total - 1e-9 > float(stm["max"]):
					return false
			elif absf(total - float(st)) > 1e-9:
				return false
		return true
	return actual == expected

static func check_frame(scope_writes: Array, allowed_writes: Array, frames: Dictionary, read_keys: Array) -> bool:
	for res in frames.keys():
		if typeof(frames[res]) == TYPE_DICTIONARY and frames[res].has("writes"):
			var wv: Variant = frames[res].get("writes", null)
			if typeof(wv) != TYPE_INT or int(wv) < 0:
				return false
			if not allowed_writes.has(res) and int(wv) != 0:
				return false
		if typeof(frames[res]) == TYPE_DICTIONARY and frames[res].get("observed", true) == false:
			continue
		var wv_req: Variant = frames[res].get("writes", null)
		if typeof(wv_req) != TYPE_INT or int(wv_req) < 0:
			return false
		if not allowed_writes.has(res) and int(wv_req) != 0:
			return false
	for res in scope_writes:
		if not allowed_writes.has(res):
			if frames.has(res):
				if typeof(frames[res]) == TYPE_DICTIONARY and frames[res].has("writes"):
					var wv2: Variant = frames[res].get("writes", null)
					if typeof(wv2) != TYPE_INT or int(wv2) != 0:
						return false
				if typeof(frames[res]) == TYPE_DICTIONARY and frames[res].get("observed", true) == false:
					continue
				var wv3: Variant = frames[res].get("writes", null)
				if typeof(wv3) != TYPE_INT or int(wv3) != 0:
					return false
				read_keys.append("@frame:" + str(res))
		else:
			read_keys.append("@frame:" + str(res))
	return true

static func check_plan_case(plan_case: Dictionary, observed: Dictionary, frames: Dictionary = {}) -> bool:
	for raw_cl in plan_case.get("clauses", []):
		if typeof(raw_cl) != TYPE_DICTIONARY:
			continue
		var cl: Dictionary = raw_cl as Dictionary
		var pred: String = str(cl.get("pred", ""))
		var ptr: String = str(cl.get("pointer", "/" + pred))
		var conv: float = float(cl.get("conv", 1.0))
		var cur: Variant = observed
		for seg in ptr.trim_prefix("/").split("/", false):
			var key_seg: String = seg.replace("~1", "/").replace("~0", "~")
			if typeof(cur) != TYPE_DICTIONARY or not (cur as Dictionary).has(key_seg):
				return false
			cur = (cur as Dictionary)[key_seg]
		var c: Dictionary = cl.get("constraint", {}) as Dictionary
		if c.has("eq"):
			var eq_v: Variant = float(c["eq"]) * conv if (typeof(c["eq"]) == TYPE_FLOAT or typeof(c["eq"]) == TYPE_INT) and conv != 1.0 else c["eq"]
			if c.has("tol"):
				var tm: Dictionary = c["tol"] as Dictionary
				var at: float = float(tm.get("abs", 0.0)) * conv
				var rt: float = float(tm.get("rel", 0.0))
				if absf(float(cur) - float(eq_v)) > at + rt * absf(float(eq_v)):
					return false
			elif (absf(float(cur) - float(eq_v)) > 1e-9 if (typeof(eq_v) == TYPE_FLOAT or typeof(eq_v) == TYPE_INT) else cur != eq_v):
				return false
		if c.has("min") and float(cur) + 1e-9 < float(c["min"]) * conv:
			return false
		if c.has("max") and float(cur) - 1e-9 > float(c["max"]) * conv:
			return false
		if c.has("peer") and (c["peer"] as Dictionary).has("balance"):
			var bm: Dictionary = (c["peer"] as Dictionary)["balance"] as Dictionary
			var pp: Dictionary = cl.get("peer_pointers", {}) as Dictionary
			var tot: float = 0.0
			for side in ["add", "sub"]:
				var sgn: float = 1.0 if side == "add" else -1.0
				for r in bm.get(side, []):
					var r_ptr: String = str(pp.get(str(r), "/" + str(r)))
					var pv: Variant = observed
					for seg2 in r_ptr.trim_prefix("/").split("/", false):
						pv = (pv as Dictionary).get(seg2, null) if typeof(pv) == TYPE_DICTIONARY else null
					if pv == null:
						return false
					tot += sgn * float(pv)
			if absf(float(cur) - tot) > 1e-9:
				return false
	if bool(plan_case.get("enforces_frame", false)):
		var dummy_reads: Array = []
		if not check_frame(frames.keys(), plan_case.get("permitted_writes", []), frames, dummy_reads):
			return false
	return true

static func replay_counterexamples(contract_id: String, case_id: String, fixtures: Array, runner: Callable) -> int:
	var count: int = 0
	for fx in fixtures:
		if str(fx.get("contract", "")) == contract_id and str(fx.get("case", "")) == case_id:
			runner.call(fx.get("witness", {}).get("when", {}))
			count += 1
	return count
