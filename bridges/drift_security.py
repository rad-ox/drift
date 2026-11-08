"""Security probing and pre-projection payload checks for the DRIFT Python bridge (D249)."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from pathlib import Path
import re
from typing import Any


def sidecar_head(environ: Mapping[str, str], classes: Any, tests: Any) -> dict[str, Any]:
    snap = environ.get('DRIFT_SNAPSHOT', '').strip()
    if snap and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', snap) is None:
        raise ValueError(f'invalid DRIFT_SNAPSHOT "{snap}"')
    ref = environ.get('DRIFT_EXECUTION_REF', '').strip()
    if ref and re.fullmatch(r'sha256:[0-9a-f]{64}', ref) is None:
        raise ValueError('invalid DRIFT_EXECUTION_REF')
    head: dict[str, Any] = {'version': 2 if ref else 1, 'classes': sorted(classes), 'tests': sorted(tests)}
    for key, value in (('execution_ref', ref), ('snapshot', snap), ('pack_ref', environ.get('DRIFT_PACK_REF', '').strip())):
        if value:
            head[key] = value
    touched = sorted({p.strip() for p in re.split(r'[\n,]+', environ.get('DRIFT_TOUCHED', '')) if p.strip()})
    if touched or ref:
        head['touched'] = touched
    return head


def merge_prior_inventory(out: str, inv: dict[str, Any], is_shard: bool, root_dir: Path, resolve_selected_files: Callable[..., Any]) -> None:
    merged_cls: set[str] = inv.setdefault('merged_classes', set())
    if is_shard and inv['classes'] and all(c in merged_cls for c in inv['classes']):
        return
    if not is_shard and inv.get('merged_single'):
        return
    self_meta = Path(out[:-6] + '.meta.json')
    d = self_meta.parent
    files = ([p for p in sorted(d.glob('*.meta.json'), reverse=True) if p != self_meta] if d.is_dir() else []) if is_shard else ([self_meta] if self_meta.is_file() else [])
    if not files:
        return
    pending = {c for c in inv['classes'] if c not in merged_cls} if is_shard else None
    cls_ok: dict[str, bool] = {}

    def has_cls(cls: str) -> bool:
        if cls not in cls_ok:
            cls_ok[cls] = len(resolve_selected_files({'all': False, 'tests': [f'{cls}#_']}, root_dir)) > 0
        return cls_ok[cls]

    raw_in = inv.setdefault('inputs', {})
    for mf in files:
        if pending is not None and not pending:
            break
        try:
            m = json.loads(mf.read_text(encoding='utf-8').lstrip('\ufeff'))
            if not isinstance(m, Mapping):
                continue
            m_classes = [c for c in (m.get('classes') or ()) if isinstance(c, str)]
            if pending is not None and not any(c in pending for c in m_classes):
                continue
            take_cls: set[str] = set()
            for c in m_classes:
                if (c in pending and has_cls(c)) if pending is not None else (c in inv['classes'] or has_cls(c)):
                    inv['classes'].add(c)
                    take_cls.add(c)
                if pending is not None and c in pending:
                    pending.remove(c)
                    merged_cls.add(c)
            for tid in m.get('tests') or ():
                if isinstance(tid, str):
                    cls = tid.partition('#')[0]
                    if cls and cls in take_cls:
                        inv['tests'].add(tid)
            if isinstance(m.get('inputs'), Mapping):
                for tid, fmap in m['inputs'].items():
                    if tid in inv['tests'] and isinstance(fmap, Mapping):
                        cur = raw_in.setdefault(tid, {})
                        for fp, dig in fmap.items():
                            if fp not in cur and isinstance(dig, str):
                                cur[fp] = dig
        except Exception:
            pass
    if pending is not None:
        merged_cls.update(pending)
    else:
        inv['merged_single'] = True


def forbidden_writes_of(view: Mapping[str, Any], case_id: str) -> list[str]:
    scope = view.get('scope') if isinstance(view, Mapping) else None
    scope_writes = [str(x) for x in (scope.get('writes') or ())] if isinstance(scope, Mapping) else []
    cases = view.get('cases') if isinstance(view, Mapping) else None
    case_map = cases.get(case_id) if isinstance(cases, Mapping) else None
    case_writes = case_map.get('writes') if isinstance(case_map, Mapping) else None
    if not isinstance(case_writes, (list, tuple)):
        return []
    allowed = {str(x) for x in case_writes}
    allowed_bases = {str(x).partition('#')[0] for x in case_writes}
    return [r for r in scope_writes if r not in allowed and r.partition('#')[0] not in allowed and r not in allowed_bases]


def verify_case_frame(ctx: Any, case_id: str, frame_obs: Any, values_mismatch: Callable[[Any, Any], bool], strict: bool = True) -> None:
    ctx._require_tagged(case_id)
    forbidden = forbidden_writes_of(ctx.view, case_id)
    if not forbidden:
        return
    seen = ctx.reads[case_id]
    for res in forbidden:
        base_res = res.partition('#')[0]
        obs = (frame_obs.get(res) if res in frame_obs else frame_obs.get(base_res)) if isinstance(frame_obs, Mapping) else None
        if obs is None:
            if strict:
                raise AssertionError(f'{ctx.contract_id}.{case_id}: missing frame observation for forbidden write resource "{res}"')
            continue
        checked_any = False
        if isinstance(obs, int) and not isinstance(obs, bool):
            checked_any = True
            if obs > 0:
                raise AssertionError(f'{ctx.contract_id}.{case_id}: frame violation on resource "{res}": expected 0 writes, observed {obs}')
        elif isinstance(obs, Mapping):
            w_count: int | None = None
            for w_key in ('writes', 'operations', 'events'):
                if w_key in obs:
                    wv = obs[w_key]
                    if isinstance(wv, int) and not isinstance(wv, bool):
                        w_count = wv
                        break
                    if isinstance(wv, (list, tuple)):
                        w_count = len(wv)
                        break
            if w_count is not None:
                checked_any = True
                if w_count > 0:
                    raise AssertionError(f'{ctx.contract_id}.{case_id}: frame violation on resource "{res}": expected 0 writes, observed {w_count}')
            if 'before' in obs and 'after' in obs:
                checked_any = True
                if values_mismatch(obs['before'], obs['after']):
                    raise AssertionError(f'{ctx.contract_id}.{case_id}: frame state mutation on resource "{res}": before and after snapshots differ')
        if not checked_any:
            raise AssertionError(f'{ctx.contract_id}.{case_id}: frame observation for "{res}" must supply writes/operations/events or before/after snapshots')
        seen.add(f'@frame:{res}')


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
                    if str(act_key) not in allowed_set:
                        raise AssertionError(f'{ctx.contract_id}.{case_id}: unexpected key "{act_key}" outside allowed_keys {list(exp["allowed_keys"])!r}')
            if 'forbid_keys' in exp:
                if isinstance(exp.get('forbid_keys'), (list, tuple)):
                    for fk in exp['forbid_keys']:
                        if str(fk) in target_obj:
                            raise AssertionError(f'{ctx.contract_id}.{case_id}: forbidden key "{fk}" present on then.{k}')
                elif str(exp['forbid_keys']) not in target_obj:
                    raise AssertionError(f'{ctx.contract_id}.{case_id}: drop-forbid-key mutant killed on then.{k}.forbid_keys')
        else:
            check_projected_leaf(ctx.contract_id, case_id, k, exp, payload, proj, ctx.mutation_override, True, 'no check or projection for')
        seen.add(k)
    frame_obs = checks.get('frame') if isinstance(checks, Mapping) and isinstance(checks.get('frame'), Mapping) else (payload.get('_frame') if isinstance(payload, Mapping) and isinstance(payload.get('_frame'), Mapping) else None)
    if frame_obs is not None:
        verify_case_frame(ctx, case_id, frame_obs, lambda a, b: a != b, True)


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
    when_tbl = ctx._when_table(case_id)
    when_proj = ctx._proj_map('when')
    for variant in variants:
        if isinstance(variant, Mapping):
            for wk, wexp in when_tbl.items():
                ptr = when_proj.get(wk) or f'/{escape_pointer(wk)}'
                found, val = read_pointer(variant, ptr)
                if found and values_mismatch(val, wexp):
                    raise AssertionError(f'{ctx.contract_id}.{case_id}.when.{wk} fixture mismatch: expected {wexp!r}, got {val!r}')
        run_projection_checks(ctx, case_id, execute(variant), checks, invoke_verified_callback, check_projected_leaf, read_pointer)


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
        'version': '0.3.3',
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

