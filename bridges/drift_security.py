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
        elif isinstance(exp, Mapping) and isinstance(exp.get('allowed_keys'), (list, tuple)):
            target_obj = payload
            if k in proj and read_pointer is not None:
                found, val = read_pointer(payload, proj[k])
                if not found:
                    raise AssertionError(f'{ctx.contract_id}.{case_id}: missing projected path "{proj[k]}" for then.{k}')
                target_obj = val
            elif isinstance(payload, Mapping) and k in payload and isinstance(payload[k], Mapping):
                target_obj = payload[k]
            if not isinstance(target_obj, Mapping):
                raise AssertionError(f'{ctx.contract_id}.{case_id}: expected mapping for then.{k}.allowed_keys')
            allowed_set = {str(x) for x in exp['allowed_keys']}
            for act_key in target_obj:
                if str(act_key) not in allowed_set:
                    raise AssertionError(f'{ctx.contract_id}.{case_id}: unexpected key "{act_key}" outside allowed_keys {list(exp["allowed_keys"])!r}')
        else:
            check_projected_leaf(ctx.contract_id, case_id, k, exp, payload, proj, ctx.mutation_override, True, 'no check or projection for')
        seen.add(k)


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
