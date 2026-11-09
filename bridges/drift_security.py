"""Security probing and pre-projection payload checks for the DRIFT Python bridge."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import importlib.util
import json
from pathlib import Path
import re
from typing import Any
try:
  from .drift_probes import ThenView, check_bola_variant_pair, has_key_recursive, is_frame_metadata_envelope, merge_prior_inventory, required_probes_of, run_idempotency_probe, run_log_sink_probe, run_rollback_probe, run_seam_probe, sidecar_head
except ImportError:
  try:
    from drift_probes import ThenView, check_bola_variant_pair, has_key_recursive, is_frame_metadata_envelope, merge_prior_inventory, required_probes_of, run_idempotency_probe, run_log_sink_probe, run_rollback_probe, run_seam_probe, sidecar_head  # type: ignore[no-redef]
  except ImportError:
    _ps = importlib.util.spec_from_file_location('drift_probes', Path(__file__).with_name('drift_probes.py'))
    assert _ps is not None and _ps.loader is not None
    _pm = importlib.util.module_from_spec(_ps)
    _ps.loader.exec_module(_pm)
    ThenView, check_bola_variant_pair, has_key_recursive, is_frame_metadata_envelope, merge_prior_inventory, required_probes_of, run_idempotency_probe, run_log_sink_probe, run_rollback_probe, run_seam_probe, sidecar_head = _pm.ThenView, _pm.check_bola_variant_pair, _pm.has_key_recursive, _pm.is_frame_metadata_envelope, _pm.merge_prior_inventory, _pm.required_probes_of, _pm.run_idempotency_probe, _pm.run_log_sink_probe, _pm.run_rollback_probe, _pm.run_seam_probe, _pm.sidecar_head
def _allowed_write_sets_of(view: Mapping[str, Any], case_id: str) -> tuple[set[str], set[str]]:
  scope = view.get('scope') if isinstance(view, Mapping) else None
  scope_writes = [str(x) for x in (scope.get('writes') or ())] if isinstance(scope, Mapping) else []
  cases = view.get('cases') if isinstance(view, Mapping) else None
  case_map = cases.get(case_id) if isinstance(cases, Mapping) else None
  case_writes = case_map.get('writes') if isinstance(case_map, Mapping) else None
  raw_allowed = [str(x) for x in case_writes] if isinstance(case_writes, (list, tuple)) else scope_writes
  allowed = set(raw_allowed)
  allowed_bases = {w.partition('#')[0] for w in raw_allowed}
  return allowed, allowed_bases
def _is_write_resource_allowed(res: str, allowed: set[str], allowed_bases: set[str]) -> bool:
  base = res.partition('#')[0]
  return res in allowed or base in allowed or ('#' not in res and res in allowed_bases)
def forbidden_writes_of(view: Mapping[str, Any], case_id: str) -> list[str]:
  scope = view.get('scope') if isinstance(view, Mapping) else None
  scope_writes = [str(x) for x in (scope.get('writes') or ())] if isinstance(scope, Mapping) else []
  cases = view.get('cases') if isinstance(view, Mapping) else None
  case_map = cases.get(case_id) if isinstance(cases, Mapping) else None
  case_writes = case_map.get('writes') if isinstance(case_map, Mapping) else None
  if not isinstance(case_writes, (list, tuple)):
    return []
  allowed, allowed_bases = _allowed_write_sets_of(view, case_id)
  return [r for r in scope_writes if not _is_write_resource_allowed(r, allowed, allowed_bases)]
def _verify_single_frame_obs(pfx: str, res: str, obs: Any, values_mismatch: Callable[[Any, Any], bool], is_ambient: bool) -> None:
  checked_any = False
  write_label = f'undeclared write on perimeter resource "{res}"' if is_ambient else f'frame violation on resource "{res}"'
  snap_label = f'undeclared state mutation on perimeter resource "{res}"' if is_ambient else f'frame state mutation on resource "{res}"'
  if isinstance(obs, int) and not isinstance(obs, bool) and obs >= 0:
    checked_any = True
    if obs > 0:
      raise AssertionError(f'{pfx}: {write_label}: expected 0 writes, observed {obs}')
  elif isinstance(obs, Mapping):
    w_count: int | None = None
    for w_key in ('writes', 'operations', 'events'):
      if w_key in obs:
        wv = obs[w_key]
        if isinstance(wv, int) and not isinstance(wv, bool) and wv >= 0:
          w_count = wv
          break
        if isinstance(wv, (list, tuple)):
          w_count = len(wv)
          break
        raise AssertionError(f'{pfx}: invalid frame {w_key} for "{res}": expected non-negative integer, got {wv!r}')
    if w_count is not None:
      checked_any = True
      if w_count > 0:
        raise AssertionError(f'{pfx}: {write_label}: expected 0 writes, observed {w_count}')
    if 'before' in obs and 'after' in obs:
      checked_any = True
      if values_mismatch(obs['before'], obs['after']):
        raise AssertionError(f'{pfx}: {snap_label}: before and after snapshots differ')
  if not checked_any:
    raise AssertionError(f'{pfx}: frame observation for "{res}" must supply writes/operations/events or before/after snapshots')
def verify_case_frame(ctx: Any, case_id: str, frame_obs: Any, values_mismatch: Callable[[Any, Any], bool], strict: bool = True) -> None:
  ctx._require_tagged(case_id)
  forbidden = forbidden_writes_of(ctx.view, case_id)
  pfx = f'{ctx.contract_id}.{case_id}'
  seen = ctx.reads[case_id]
  checked_keys: set[str] = set()
  for res in forbidden:
    base_res = res.partition('#')[0]
    checked_keys.add(res)
    checked_keys.add(base_res)
    obs = (frame_obs.get(res) if res in frame_obs else frame_obs.get(base_res)) if isinstance(frame_obs, Mapping) else None
    has_metrics = isinstance(obs, Mapping) and (any(k in obs for k in ('writes', 'operations', 'events')) or ('before' in obs and 'after' in obs))
    if has_metrics:
      _verify_single_frame_obs(pfx, res, obs, values_mismatch, False)
    if obs is None or (isinstance(obs, Mapping) and obs.get('observed') is False):
      if not hasattr(ctx, 'unobserved_cases') or not isinstance(getattr(ctx, 'unobserved_cases'), set):
        try:
          ctx.unobserved_cases = set()
        except Exception:
          pass
      if hasattr(ctx, 'unobserved_cases') and isinstance(ctx.unobserved_cases, set):
        ctx.unobserved_cases.add(case_id)
      if strict:
        msg = f'missing frame observation for forbidden write resource "{res}"' if obs is None else f'frame.observer_missing for forbidden write resource "{res}"'
        raise AssertionError(f'{pfx}: {msg}')
      continue
    if not has_metrics:
      _verify_single_frame_obs(pfx, res, obs, values_mismatch, False)
    seen.add(f'@frame:{res}')
  if isinstance(frame_obs, Mapping):
    allowed, allowed_bases = _allowed_write_sets_of(ctx.view, case_id)
    for k in sorted(str(x) for x in frame_obs.keys()):
      if k in checked_keys or _is_write_resource_allowed(k, allowed, allowed_bases):
        continue
      obs_k = frame_obs.get(k)
      has_k_metrics = isinstance(obs_k, Mapping) and (any(x in obs_k for x in ('writes', 'operations', 'events')) or ('before' in obs_k and 'after' in obs_k))
      if has_k_metrics:
        _verify_single_frame_obs(pfx, k, obs_k, values_mismatch, True)
      if isinstance(obs_k, Mapping) and obs_k.get('observed') is False:
        if strict:
          raise AssertionError(f'{pfx}: frame.observer_missing for perimeter resource "{k}"')
        continue
      if not has_k_metrics:
        _verify_single_frame_obs(pfx, k, obs_k, values_mismatch, True)
def run_projection_checks(
  ctx: Any,
  case_id: str,
  payload: Any,
  checks: Mapping[str, Callable[[Any], Any]] | None,
  invoke_verified_callback: Callable[..., None],
  check_projected_leaf: Callable[..., None],
  read_pointer: Callable[[Any, str], tuple[bool, Any]] | None = None,
) -> None:
  ctx._require_tagged(case_id)
  seen = ctx.reads[case_id]
  proj = ctx._proj_map('then')
  for k, exp in ctx._then_table(case_id).items():
    if isinstance(checks, Mapping) and callable(checks.get(k)):
      invoke_verified_callback(checks[k], ctx.contract_id, case_id, k, exp)
    elif isinstance(exp, Mapping) and (isinstance(exp.get('allowed_keys'), (list, tuple)) or 'forbid_keys' in exp):
      target_obj = payload
      if k in proj and read_pointer is not None:
        found, val = read_pointer(payload, proj[k])
        if not found:
          raise AssertionError(f'{ctx.contract_id}.{case_id}: missing projected path "{proj[k]}" for then.{k}')
        target_obj = val
      elif isinstance(payload, Mapping) and k in payload and isinstance(payload[k], Mapping):
        target_obj = payload[k]
      if not isinstance(target_obj, Mapping):
        raise AssertionError(f'{ctx.contract_id}.{case_id}: expected mapping for then.{k}')
      if isinstance(exp.get('allowed_keys'), (list, tuple)):
        allowed_set = {str(x) for x in exp['allowed_keys']}
        for act_key in target_obj:
          if target_obj is payload and str(act_key) == '_frame' and is_frame_metadata_envelope(target_obj.get('_frame')):
            continue
          if str(act_key) not in allowed_set:
            raise AssertionError(f'{ctx.contract_id}.{case_id}: unexpected key "{act_key}" outside allowed_keys {list(exp["allowed_keys"])!r}')
      if 'forbid_keys' in exp:
        is_root_t = target_obj is payload
        if isinstance(exp.get('forbid_keys'), (list, tuple)):
          for fk in exp['forbid_keys']:
            if has_key_recursive(target_obj, str(fk), is_root_t):
              raise AssertionError(f'{ctx.contract_id}.{case_id}: forbidden key "{fk}" present on then.{k}')
        elif not has_key_recursive(target_obj, str(exp['forbid_keys']), is_root_t):
          raise AssertionError(f'{ctx.contract_id}.{case_id}: drop-forbid-key mutant killed on then.{k}.forbid_keys')
    else:
      check_projected_leaf(ctx.contract_id, case_id, k, exp, payload, proj, ctx.mutation_override, True, 'no check or projection for')
    seen.add(k)
  frame_obs = checks.get('frame') if isinstance(checks, Mapping) and isinstance(checks.get('frame'), Mapping) else (payload.get('_frame') if isinstance(payload, Mapping) and is_frame_metadata_envelope(payload.get('_frame')) else None)
  if frame_obs is not None:
    strict_frame = bool(isinstance(checks, Mapping) and checks.get('strictFrame') is True) or not any(isinstance(v, Mapping) and v.get('observed') is False for v in frame_obs.values())
    verify_case_frame(ctx, case_id, frame_obs, lambda a, b: a != b, strict_frame)
def run_adverse_checks(
  ctx: Any,
  case_id: str,
  harness: Mapping[str, Any],
  checks: Mapping[str, Callable[[Any], Any]] | None,
  escape_pointer: Callable[[str], str],
  read_pointer: Callable[[Any, str], tuple[bool, Any]],
  values_mismatch: Callable[[Any, Any], bool],
  invoke_verified_callback: Callable[..., None],
  check_projected_leaf: Callable[..., None],
) -> None:
  ctx._require_tagged(case_id)
  variants = harness.get('variants') if isinstance(harness, Mapping) else None
  execute = harness.get('execute') if isinstance(harness, Mapping) else None
  if not isinstance(variants, (list, tuple)) or not variants or not callable(execute):
    raise ValueError(f'check_adverse for {ctx.contract_id}.{case_id} requires non-empty variants and an execute callback')
  pfx = f'{ctx.contract_id}.{case_id}'
  when_tbl = ctx._when_table(case_id)
  when_proj = ctx._proj_map('when')
  saw_cross_owner = False
  for variant in variants:
    if check_bola_variant_pair(pfx, variant):
      saw_cross_owner = True
    if isinstance(variant, Mapping):
      for wk, wexp in when_tbl.items():
        ptr = when_proj.get(wk) or f'/{escape_pointer(wk)}'
        found, val = read_pointer(variant, ptr)
        if found and values_mismatch(val, wexp):
          raise AssertionError(f'{ctx.contract_id}.{case_id}.when.{wk} fixture mismatch: expected {wexp!r}, got {val!r}')
    run_projection_checks(ctx, case_id, execute(variant), checks, invoke_verified_callback, check_projected_leaf, read_pointer)
  if (harness.get('requireCrossOwner') is True or harness.get('require_cross_owner') is True or harness.get('bola') is True) and not saw_cross_owner:
    ctx.reads[case_id].clear()
    if harness.get('strict') is not False:
      raise AssertionError(f'{pfx}: bola.unobserved: no cross-owner variant with distinct actor_owner and resource_owner supplied')
BRIDGE_CAPABILITIES: tuple[str, ...] = (
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
)
def bridge_capabilities() -> dict[str, Any]:
  return {
    'bridge': 'drift.py',
    'capabilities': list(BRIDGE_CAPABILITIES),
    'runtime_baseline': 'python-3.14',
    'schema': 'drift.bridge-capabilities/1',
    'version': '0.5.0',
  }
def require_capabilities(required: list[str] | tuple[str, ...]) -> None:
  if not isinstance(required, (list, tuple)):
    raise RuntimeError('bridge.capability_unsupported:invalid')
  for cap in required:
    k = cap.strip() if isinstance(cap, str) else ''
    if not k or k not in BRIDGE_CAPABILITIES:
      raise RuntimeError(f'bridge.capability_unsupported:{k}')
def replay_counterexamples(
  ctx: Any,
  case_id: str,
  fixtures: list[Mapping[str, Any]],
  sut: Callable[[Mapping[str, Any]], Any],
  invoke_verified_callback: Callable[..., None],
  check_projected_leaf: Callable[..., None],
  read_pointer: Callable[[Any, str], tuple[bool, Any]] | None = None,
  checks: Mapping[str, Any] | None = None,
) -> int:
  ctx._require_tagged(case_id)
  count = 0
  for fx in fixtures:
    if not isinstance(fx, Mapping) or fx.get('contract') != ctx.contract_id:
      continue
    if fx.get('case') and fx.get('case') != case_id:
      continue
    wit = fx.get('witness')
    if not isinstance(wit, Mapping) or not isinstance(wit.get('when'), Mapping):
      raise ValueError('counterexample fixture missing witness.when')
    actual = sut(wit['when'])
    run_projection_checks(ctx, case_id, actual, checks, invoke_verified_callback, check_projected_leaf, read_pointer)
    count += 1
  return count
_RES_PFX_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
def split_resource_pointer(ptr: str) -> tuple[str, str]:
  if not isinstance(ptr, str) or not ptr: return ('', ptr)
  st, col = (1 if ptr.startswith('/') else 0), ptr.find(':/', 1 if ptr.startswith('/') else 0)
  return (ptr[st:col], ptr[col + 1:]) if col > st and _RES_PFX_RE.match(ptr[st:col]) else ('', ptr)
def clone_json(val: Any) -> Any:
  return [clone_json(x) for x in val] if isinstance(val, (list, tuple)) else ({str(k): clone_json(v) for k, v in val.items()} if isinstance(val, Mapping) else val)
def _is_relational_map(val: Any, rk: frozenset[str]) -> bool:
  return isinstance(val, Mapping) and bool(val) and all(k in rk for k in val)
def _is_num(val: Any) -> bool:
  return isinstance(val, (int, float)) and not isinstance(val, bool)
def _canon_stub_ref(ref: Any, wp: Mapping[str, str], tp: Mapping[str, str]) -> str:
  if not isinstance(ref, str) or not ref.strip(): return ''
  s = ref.strip()
  return split_resource_pointer(s if s.startswith('/') else (tp.get(s) or wp.get(s) or ('/' + s)))[1]
def _round_num(cur_lo: Any, cur_hi: Any, raw_v: float, is_min: bool) -> int | float:
  import math
  if isinstance(cur_lo, int) or isinstance(cur_hi, int) or float(raw_v).is_integer():
    return int(math.ceil(raw_v - 1e-9) if is_min else math.floor(raw_v + 1e-9))
  return raw_v
def _peer_order_relation(ck_a: str, ck_b: str, then_map: Mapping[str, Any], wp: Mapping[str, str], tp: Mapping[str, str], rk: frozenset[str]) -> int:
  if not ck_a or not ck_b or ck_a == ck_b or not isinstance(then_map, Mapping): return 0
  for k, v in then_map.items():
    if not _is_relational_map(v, rk): continue
    ck = _canon_stub_ref(k, wp, tp)
    if ck == ck_a:
      for fk, code in (('eq_field', 3), ('le_field', 1), ('ge_field', 2)):
        if fk in v and _canon_stub_ref(v[fk], wp, tp) == ck_b: return code
    elif ck == ck_b:
      for fk, code in (('eq_field', 3), ('ge_field', 1), ('le_field', 2)):
        if fk in v and _canon_stub_ref(v[fk], wp, tp) == ck_a: return code
  return 0
def tighten_then_by_sum_residuals(when_map: Mapping[str, Any], raw_then: Mapping[str, Any], wp: Mapping[str, str], tp: Mapping[str, str], rk: frozenset[str]) -> dict[str, Any]:
  if not isinstance(raw_then, Mapping) or not any(_is_relational_map(v, rk) and ((isinstance(v.get('sum_fields'), (list, tuple)) and len(v['sum_fields']) >= 2) or any(pk in v for pk in ('le_field', 'ge_field', 'eq_field'))) for v in raw_then.values()):
    return dict(raw_then) if isinstance(raw_then, Mapping) else {}
  out: dict[str, Any] = clone_json(raw_then)
  def lb(ref: Any) -> tuple[int | float | None, int | float | None]:
    ck, bare = _canon_stub_ref(ref, wp, tp), (ref.strip().lstrip('/') if isinstance(ref, str) else '')
    for m, pm in ((out, tp), (when_map or {}, wp)):
      for k, v in m.items():
        if k in (ref, bare) or _canon_stub_ref(k, wp, pm) == ck:
          if _is_num(v): return (v, v)
          if _is_relational_map(v, rk): return (v['min'] if _is_num(v.get('min')) else None, v['max'] if _is_num(v.get('max')) else None)
    return (None, None)
  for _ in range(3):
    for tk, tv in list(out.items()):
      if not _is_relational_map(tv, rk): continue
      ck_tgt, lo_k, hi_k = _canon_stub_ref(tk, wp, tp), (tv['min'] if _is_num(tv.get('min')) else None), (tv['max'] if _is_num(tv.get('max')) else None)
      for pk in ('eq_field', 'le_field', 'ge_field'):
        if pk in tv:
          pb_lo, pb_hi = lb(tv[pk])
          if pk in ('eq_field', 'ge_field') and pb_lo is not None: lo_k = pb_lo if lo_k is None else max(lo_k, pb_lo)
          if pk in ('eq_field', 'le_field') and pb_hi is not None: hi_k = pb_hi if hi_k is None else min(hi_k, pb_hi)
      for pk, pv in out.items():
        if pk == tk or not _is_relational_map(pv, rk): continue
        p_lo, p_hi = (pv['min'] if _is_num(pv.get('min')) else None), (pv['max'] if _is_num(pv.get('max')) else None)
        if 'eq_field' in pv and _canon_stub_ref(pv['eq_field'], wp, tp) == ck_tgt:
          if p_lo is not None: lo_k = p_lo if lo_k is None else max(lo_k, p_lo)
          if p_hi is not None: hi_k = p_hi if hi_k is None else min(hi_k, p_hi)
        if 'le_field' in pv and _canon_stub_ref(pv['le_field'], wp, tp) == ck_tgt and p_lo is not None: lo_k = p_lo if lo_k is None else max(lo_k, p_lo)
        if 'ge_field' in pv and _canon_stub_ref(pv['ge_field'], wp, tp) == ck_tgt and p_hi is not None: hi_k = p_hi if hi_k is None else min(hi_k, p_hi)
      for sk, sv in out.items():
        if sk == tk or not _is_relational_map(sv, rk) or not isinstance(sv.get('sum_fields'), (list, tuple)) or len(sv['sum_fields']) < 2: continue
        s_lo, s_hi = (sv['min'] if _is_num(sv.get('min')) else None), (sv['max'] if _is_num(sv.get('max')) else None)
        if s_lo is None and s_hi is None: continue
        mult: dict[str, int] = {}
        rep: dict[str, Any] = {}
        for sf in sv['sum_fields']:
          ck = _canon_stub_ref(sf, wp, tp)
          if ck: mult[ck], rep[ck] = mult.get(ck, 0) + 1, rep.get(ck, sf)
        mk = mult.get(ck_tgt, 0)
        if mk < 1: continue
        rem_lo, rem_hi, all_lo, all_hi = 0.0, 0.0, True, True
        for ck, mp in mult.items():
          if ck == ck_tgt: continue
          b_lo, b_hi = lb(rep[ck])
          if b_lo is not None: rem_lo += mp * b_lo
          else: all_lo = False
          if b_hi is not None: rem_hi += mp * b_hi
          else: all_hi = False
        for ck_p, mp in mult.items():
          if ck_p == ck_tgt: continue
          ord_rel = _peer_order_relation(ck_tgt, ck_p, out, wp, tp, rk)
          if ord_rel == 0: continue
          o_lo, o_hi, o_all_lo, o_all_hi = 0.0, 0.0, True, True
          for ck_q, mq in mult.items():
            if ck_q in (ck_tgt, ck_p): continue
            b_lo, b_hi = lb(rep[ck_q])
            if b_lo is not None: o_lo += mq * b_lo
            else: o_all_lo = False
            if b_hi is not None: o_hi += mq * b_hi
            else: o_all_hi = False
          if ord_rel in (1, 3) and s_hi is not None and o_all_lo:
            cnd = _round_num(lo_k, hi_k, (s_hi - o_lo) / (mk + mp), False)
            hi_k = cnd if hi_k is None else min(hi_k, cnd)
          if ord_rel in (2, 3) and s_lo is not None and o_all_hi:
            cnd = _round_num(lo_k, hi_k, (s_lo - o_hi) / (mk + mp), True)
            lo_k = cnd if lo_k is None else max(lo_k, cnd)
        for bk, bv in out.items():
          if bk in (sk, tk) or not _is_relational_map(bv, rk) or not isinstance(bv.get('sum_fields'), (list, tuple)) or len(bv['sum_fields']) < 2: continue
          b_lo, b_hi = (bv['min'] if _is_num(bv.get('min')) else None), (bv['max'] if _is_num(bv.get('max')) else None)
          if b_lo is None and b_hi is None: continue
          mult_b: dict[str, int] = {}
          for sf in bv['sum_fields']:
            ck = _canon_stub_ref(sf, wp, tp)
            if ck: mult_b[ck] = mult_b.get(ck, 0) + 1
          if ck_tgt in mult_b: continue
          if len(bv['sum_fields']) < len(sv['sum_fields']) and all(mult.get(ck, 0) >= m for ck, m in mult_b.items()):
            ex_lo, ex_hi, ex_all_lo, ex_all_hi = 0.0, 0.0, True, True
            for ck, mp in mult.items():
              if ck != ck_tgt and mp > mult_b.get(ck, 0):
                d, (r_lo, r_hi) = mp - mult_b.get(ck, 0), lb(rep[ck])
                if r_lo is not None: ex_lo += d * r_lo
                else: ex_all_lo = False
                if r_hi is not None: ex_hi += d * r_hi
                else: ex_all_hi = False
            if b_lo is not None and ex_all_lo: rem_lo, all_lo = (max(rem_lo, b_lo + ex_lo) if all_lo else (b_lo + ex_lo)), True
            if b_hi is not None and ex_all_hi: rem_hi, all_hi = (min(rem_hi, b_hi + ex_hi) if all_hi else (b_hi + ex_hi)), True
          if len(mult) == 2 and len(mult_b) == 2:
            y_ck = next((x for x in mult if x != ck_tgt), '')
            if y_ck and mult.get(y_ck) == 1 and mult_b.get(y_ck) == 1:
              z_ck = next((x for x in mult_b if x != y_ck), '')
              for ck3, cv3 in out.items():
                if ck3 in (sk, bk, tk) or not _is_relational_map(cv3, rk) or not isinstance(cv3.get('sum_fields'), (list, tuple)) or len(cv3['sum_fields']) != len(sv['sum_fields']): continue
                mult_c: dict[str, int] = {}
                for sf in cv3['sum_fields']:
                  ck = _canon_stub_ref(sf, wp, tp)
                  if ck: mult_c[ck] = mult_c.get(ck, 0) + 1
                if len(mult_c) == 2 and mult_c.get(ck_tgt) == mk and mult_c.get(z_ck) == 1:
                  c_lo, c_hi = (cv3['min'] if _is_num(cv3.get('min')) else None), (cv3['max'] if _is_num(cv3.get('max')) else None)
                  if s_lo is not None and c_lo is not None and b_hi is not None: lo_k = _round_num(lo_k, hi_k, (s_lo + c_lo - b_hi) / (2 * mk), True) if lo_k is None else max(lo_k, _round_num(lo_k, hi_k, (s_lo + c_lo - b_hi) / (2 * mk), True))
                  if s_hi is not None and c_hi is not None and b_lo is not None: hi_k = _round_num(lo_k, hi_k, (s_hi + c_hi - b_lo) / (2 * mk), False) if hi_k is None else min(hi_k, _round_num(lo_k, hi_k, (s_hi + c_hi - b_lo) / (2 * mk), False))
        if s_lo is not None and all_hi: lo_k = _round_num(lo_k, hi_k, (s_lo - rem_hi) / mk, True) if lo_k is None else max(lo_k, _round_num(lo_k, hi_k, (s_lo - rem_hi) / mk, True))
        if s_hi is not None and all_lo: hi_k = _round_num(lo_k, hi_k, (s_hi - rem_lo) / mk, False) if hi_k is None else min(hi_k, _round_num(lo_k, hi_k, (s_hi - rem_lo) / mk, False))
      if lo_k is not None and (hi_k is None or lo_k <= hi_k): tv['min'] = lo_k
      if hi_k is not None and (lo_k is None or lo_k <= hi_k): tv['max'] = hi_k
  return out
def capture_worktree_snapshot(area: Path) -> str:
  import os, shutil, subprocess
  try:
    st_p = subprocess.run(['git', '-C', str(area), 'status', '--porcelain', '--untracked-files=normal'], capture_output=True, text=True, check=False)
    if st_p.returncode == 0 and not st_p.stdout.strip():
      tr_p = subprocess.run(['git', '-C', str(area), 'rev-parse', '--verify', '--quiet', 'HEAD^{tree}'], capture_output=True, text=True, check=False)
      tr = tr_p.stdout.strip()
      if len(tr) in (40, 64):
        return tr
    rev_p = subprocess.run(['git', '-C', str(area), 'rev-parse', '--show-toplevel', '--git-dir'], capture_output=True, text=True, check=False)
    rev_lines = [ln.strip() for ln in rev_p.stdout.splitlines() if ln.strip()]
    if rev_p.returncode != 0 or len(rev_lines) < 2:
      return ''
    top = (area / rev_lines[0]).resolve()
    git_dir = (area / rev_lines[1]).resolve()
    real_idx = git_dir / 'index'
    tmp_idx = area / '.drift-work' / f'.git-index-{os.getpid()}'
    try:
      if real_idx.is_file():
        shutil.copy2(real_idx, tmp_idx)
      elif tmp_idx.exists():
        tmp_idx.unlink()
      env = {**os.environ, 'GIT_INDEX_FILE': str(tmp_idx)}
      subprocess.run(['git', '-C', str(top), '-c', 'core.safecrlf=false', 'add', '-A', '--', '.', ':(exclude).drift-work', ':(exclude).build', ':(exclude)target'], env=env, capture_output=True, check=False)
      tr_p = subprocess.run(['git', '-C', str(top), 'write-tree'], env=env, capture_output=True, text=True, check=False)
      tr = tr_p.stdout.strip()
      if tr_p.returncode == 0 and len(tr) in (40, 64):
        return tr
    finally:
      if tmp_idx.exists():
        tmp_idx.unlink()
  except Exception:
    pass
  return ''
