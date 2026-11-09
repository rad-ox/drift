"""Reusable observable behavioral probes for the DRIFT Python bridge."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

DEFAULT_VOLATILE_KEYS = frozenset(('request_id', 'timestamp', 'trace_id', 'audit_id'))
DEFAULT_ALLOWED_SECOND_WRITES = frozenset(('AUDIT_LOG', 'audit_log', 'METRICS', 'metrics'))
FRAME_ENTRY_KEYS = frozenset(('writes', 'operations', 'events', 'before', 'after', 'observed'))


def is_frame_metadata_envelope(v: Any) -> bool:
  if not isinstance(v, Mapping):
    return False
  if not v:
    return True
  for e in v.values():
    if isinstance(e, int) and not isinstance(e, bool) and e >= 0:
      continue
    if isinstance(e, Mapping) and all(str(k) in FRAME_ENTRY_KEYS for k in e.keys()):
      continue
    return False
  return True


def required_probes_of(view: Any, case_id: str) -> list[str]:
  if not isinstance(view, Mapping):
    return []
  cases = view.get('cases') if isinstance(view.get('cases'), Mapping) else {}
  c_map = cases.get(case_id) if isinstance(cases.get(case_id), Mapping) else {}
  req = view.get('requires') if isinstance(view.get('requires'), Mapping) else {}
  out: list[str] = []
  for src in (c_map.get('probes'), req.get('probes')):
    if isinstance(src, (list, tuple)):
      for p in src:
        if isinstance(p, str) and p.strip() and p.strip() not in out:
          out.append(p.strip())
  return out


class ThenView(Mapping[str, Any]):
  def __init__(self, values: Mapping[str, Any], seen: set[str]) -> None:
    self._values, self._seen = values, seen

  def __getitem__(self, key: str) -> Any:
    if key in self._values:
      self._seen.add(key)
    return self._values[key]

  def __getattr__(self, key: str) -> Any:
    if key in self._values:
      self._seen.add(key)
      return self._values[key]
    raise AttributeError(key)

  def __iter__(self):
    return iter(self._values)

  def __len__(self) -> int:
    return len(self._values)


def has_key_recursive(val: Any, fk: str, is_root: bool = True, depth: int = 0) -> bool:
  if depth > 64:
    raise AssertionError('observation.incomplete: max_depth_exceeded (> 64)')
  if isinstance(val, (list, tuple)):
    return any(has_key_recursive(item, fk, False, depth + 1) for item in val)
  if isinstance(val, Mapping):
    if val.get('_truncated') is True or val.get('__truncated__') is True:
      raise AssertionError('observation.incomplete: truncated_capture')
    for k, v in val.items():
      ks = str(k)
      if ks == fk:
        if is_root and ks == '_frame' and fk != '_frame' and is_frame_metadata_envelope(v):
          continue
        return True
      if is_root and ks == '_frame' and fk != '_frame' and is_frame_metadata_envelope(v):
        continue
      if has_key_recursive(v, fk, False, depth + 1):
        return True
    return False
  if val is not None and not isinstance(val, (bool, int, float, str)):
    raise AssertionError('observation.incomplete: non_traversable_object')
  return False


def _is_non_neg_int(v: Any) -> bool:
  return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _unverified_or_raise(ctx: Any, case_id: str, strict: bool, reason: str, detail: str) -> dict[str, Any]:
  if hasattr(ctx, 'reads') and isinstance(ctx.reads, Mapping) and case_id in ctx.reads:
    ctx.reads[case_id].clear()
  if not hasattr(ctx, 'unobserved_cases') or not isinstance(getattr(ctx, 'unobserved_cases'), set):
    try:
      ctx.unobserved_cases = set()
    except Exception:
      pass
  if hasattr(ctx, 'unobserved_cases') and isinstance(ctx.unobserved_cases, set):
    ctx.unobserved_cases.add(case_id)
  if strict:
    raise AssertionError(f'{ctx.contract_id}.{case_id}: {reason}: {detail}')
  return {'observed': False, 'reason': reason}


def run_idempotency_probe(
  ctx: Any,
  case_id: str,
  obs: Any,
  values_mismatch: Callable[[Any, Any], bool],
  run_projection_fn: Callable[..., None] | None = None,
) -> dict[str, Any]:
  ctx._require_tagged(case_id)
  pfx = f'{ctx.contract_id}.{case_id}'
  strict = not isinstance(obs, Mapping) or obs.get('strict') is not False
  if not isinstance(obs, Mapping):
    return _unverified_or_raise(ctx, case_id, strict, 'idempotency.unobserved', 'collector reported unobserved state')
  s1 = obs.get('stateAfterFirst', obs.get('state_after_first'))
  s2 = obs.get('stateAfterSecond', obs.get('state_after_second'))
  has_state = s1 is not None and s2 is not None
  sw = obs.get('secondWrites', obs.get('second_writes'))
  second_writes = sw if isinstance(sw, Mapping) else None
  if has_state and values_mismatch(s1, s2):
    raise AssertionError(f'{pfx}: idempotency.domain_state_mutated: stateAfterFirst and stateAfterSecond differ')
  if second_writes is not None:
    raw_allow = obs.get('allowedSecondWrites', obs.get('allowed_second_writes'))
    allowed2 = {str(x) for x in raw_allow} if isinstance(raw_allow, (list, tuple)) else set(DEFAULT_ALLOWED_SECOND_WRITES)
    for res, wv in second_writes.items():
      res_s = str(res)
      base = res_s.partition('#')[0]
      if res_s in allowed2 or base in allowed2:
        continue
      cnt = len(wv) if isinstance(wv, (list, tuple)) else wv
      if not _is_non_neg_int(cnt) or int(cnt) > 0:
        raise AssertionError(f'{pfx}: idempotency.duplicate_write on resource "{res_s}": expected 0 writes on replay, observed {cnt}')
  first_p, second_p = obs.get('first'), obs.get('second')
  if isinstance(first_p, Mapping) and isinstance(second_p, Mapping):
    raw_vol = obs.get('volatileKeys', obs.get('volatile_keys'))
    vol = {str(x) for x in raw_vol} if isinstance(raw_vol, (list, tuple)) else set(DEFAULT_VOLATILE_KEYS)
    for k, v1 in first_p.items():
      ks = str(k)
      if ks in vol or ks == '_frame':
        continue
      if k in second_p and values_mismatch(v1, second_p[k]):
        raise AssertionError(f'{pfx}: idempotency.response_diverged on key "{ks}"')
  if obs.get('observed') is False or (not has_state and second_writes is None):
    return _unverified_or_raise(ctx, case_id, strict, 'idempotency.unobserved', 'missing state snapshots and secondWrites observations')
  if 'first' in obs and obs['first'] is not None and run_projection_fn is not None:
    run_projection_fn(ctx, case_id, obs['first'], obs.get('checks') if isinstance(obs.get('checks'), Mapping) else {})
  if hasattr(ctx, 'reads') and isinstance(ctx.reads, Mapping) and case_id in ctx.reads:
    ctx.reads[case_id].add('@probe:idempotency')
  return {'observed': True, 'reason': ''}


def run_seam_probe(ctx: Any, case_id: str, obs: Any) -> dict[str, Any]:
  ctx._require_tagged(case_id)
  pfx = f'{ctx.contract_id}.{case_id}'
  strict = not isinstance(obs, Mapping) or obs.get('strict') is not False
  if not isinstance(obs, Mapping):
    return _unverified_or_raise(ctx, case_id, strict, 'seam.unobserved', 'seam collector is unobserved')
  max_att = obs.get('maxAttempts', obs.get('max_attempts'))
  has_retry = 'retryable' in obs or max_att is not None
  has_timeout = obs.get('timedOut', obs.get('timed_out')) is True
  max_q = obs.get('maxQueries', obs.get('max_queries'))
  has_query = max_q is not None
  att = obs.get('attempts')
  if has_retry and _is_non_neg_int(att) and int(att) > 0:
    if obs.get('retryable') is False and int(att) > 1:
      raise AssertionError(f'{pfx}: seam.non_retryable_retried: expected 1 attempt on terminal fault, observed {att}')
    if obs.get('retryable') is True and int(att) < 2:
      raise AssertionError(f'{pfx}: seam.retry_missing: expected >= 2 attempts on transient fault, observed {att}')
    if max_att is not None and (not _is_non_neg_int(max_att) or int(att) > int(max_att)):
      raise AssertionError(f'{pfx}: seam.max_attempts_exceeded: observed {att} > maxAttempts {max_att}')
  if has_timeout:
    lw_v = obs.get('lateWrites', obs.get('late_writes', 0))
    if _is_non_neg_int(lw_v) and int(lw_v) > 0:
      raise AssertionError(f'{pfx}: seam.timeout_late_write: expected 0 writes after timeout, observed {lw_v}')
  if has_query:
    q_v = obs.get('queries')
    if _is_non_neg_int(q_v) and _is_non_neg_int(max_q) and int(q_v) > int(max_q):
      raise AssertionError(f'{pfx}: seam.query_budget_exceeded: observed {q_v} > maxQueries {max_q}')
  if obs.get('observed') is False or (not has_retry and not has_timeout and not has_query):
    return _unverified_or_raise(ctx, case_id, strict, 'seam.unobserved', 'seam collector is unobserved')
  if has_retry and (not _is_non_neg_int(att) or int(att) <= 0):
    return _unverified_or_raise(ctx, case_id, strict, 'seam.unobserved', 'missing positive attempts count from seam spy')
  if has_timeout and not _is_non_neg_int(obs.get('lateWrites', obs.get('late_writes', 0))):
    return _unverified_or_raise(ctx, case_id, strict, 'seam.unobserved', 'invalid lateWrites observation')
  if has_query and (not _is_non_neg_int(obs.get('queries')) or not _is_non_neg_int(max_q)):
    return _unverified_or_raise(ctx, case_id, strict, 'queries.unobserved', 'missing non-negative queries count from SQL listener')
  if hasattr(ctx, 'reads') and isinstance(ctx.reads, Mapping) and case_id in ctx.reads:
    ctx.reads[case_id].add('@probe:seam')
  return {'observed': True, 'reason': ''}


def run_rollback_probe(
  ctx: Any,
  case_id: str,
  obs: Any,
  values_mismatch: Callable[[Any, Any], bool],
) -> dict[str, Any]:
  ctx._require_tagged(case_id)
  pfx = f'{ctx.contract_id}.{case_id}'
  strict = not isinstance(obs, Mapping) or obs.get('strict') is not False
  if isinstance(obs, Mapping) and 'before' in obs and 'after' in obs and obs['before'] is not None and obs['after'] is not None:
    res = str(obs.get('resource') or 'primary')
    if values_mismatch(obs['before'], obs['after']) and obs.get('compensated') is not True:
      raise AssertionError(f'{pfx}: rollback.dirty_partial_write on "{res}": before and after snapshots differ after downstream failure')
  if not isinstance(obs, Mapping) or obs.get('observed') is False or 'before' not in obs or 'after' not in obs or obs['before'] is None or obs['after'] is None:
    return _unverified_or_raise(ctx, case_id, strict, 'rollback.unobserved', 'missing before/after snapshot on primary resource')
  if hasattr(ctx, 'reads') and isinstance(ctx.reads, Mapping) and case_id in ctx.reads:
    ctx.reads[case_id].add('@probe:rollback')
  return {'observed': True, 'reason': ''}


def check_bola_variant_pair(pfx: str, variant: Any) -> bool:
  if not isinstance(variant, Mapping):
    return False
  b = variant.get('bola') if isinstance(variant.get('bola'), Mapping) else variant
  if 'actor_owner' not in b and 'resource_owner' not in b:
    return False
  actor = str(b.get('actor_owner') or '').strip()
  owner = str(b.get('resource_owner') or '').strip()
  if not actor or not owner or actor == owner:
    raise AssertionError(f'{pfx}: bola.invalid_fixture: cross-owner probe requires distinct non-empty actor_owner and resource_owner')
  return True


def _contains_str_leaf(val: Any, needle: str, depth: int = 0) -> bool:
  if depth > 64:
    raise AssertionError('observation.incomplete: max_depth_exceeded (> 64)')
  if isinstance(val, str):
    return needle in val
  if isinstance(val, (list, tuple)):
    return any(_contains_str_leaf(x, needle, depth + 1) for x in val)
  if isinstance(val, Mapping):
    if val.get('_truncated') is True or val.get('__truncated__') is True:
      raise AssertionError('observation.incomplete: truncated_capture')
    return any(_contains_str_leaf(v, needle, depth + 1) for v in val.values())
  return False


def run_log_sink_probe(ctx: Any, case_id: str, obs: Any) -> dict[str, Any]:
  ctx._require_tagged(case_id)
  pfx = f'{ctx.contract_id}.{case_id}'
  strict = not isinstance(obs, Mapping) or obs.get('strict') is not False
  if not isinstance(obs, Mapping):
    return _unverified_or_raise(ctx, case_id, strict, 'log_sink.unobserved', 'log sink collector is unobserved')
  raw_sec = obs.get('secretValues', obs.get('secret_values'))
  secrets = [s for s in (raw_sec if isinstance(raw_sec, (list, tuple)) else ()) if isinstance(s, str) and s.strip()]
  logs = obs.get('logLines', obs.get('log_lines'))
  has_logs = isinstance(logs, (str, list, tuple))
  has_payload = 'payload' in obs and obs['payload'] is not None
  for s in secrets:
    if (has_logs and _contains_str_leaf(logs, s)) or (has_payload and _contains_str_leaf(obs['payload'], s)):
      raise AssertionError(f'{pfx}: log_sink.secret_leaked: secret canary leaked in observed sink')
  if obs.get('observed') is False or not secrets or (not has_logs and not has_payload):
    return _unverified_or_raise(ctx, case_id, strict, 'log_sink.unobserved', 'missing secretValues or observed logLines/payload')
  if hasattr(ctx, 'reads') and isinstance(ctx.reads, Mapping) and case_id in ctx.reads:
    ctx.reads[case_id].add('@probe:log_sink')
  return {'observed': True, 'reason': ''}


def parse_test_command_str(raw: str) -> list[str]:
  import json
  s = (raw or '').strip()
  if not s:
    return []
  if s.startswith('['):
    arr = json.loads(s)
    if not isinstance(arr, list) or not all(isinstance(x, str) for x in arr):
      raise ValueError('DRIFT_TEST_CMD JSON must be an array of strings')
    return [x for x in arr if x]
  out: list[str] = []
  cur, in_q, q, has_tok, i = '', False, '', False, 0
  while i < len(s):
    ch = s[i]
    if in_q:
      if ch == '\\' and q == '"' and i + 1 < len(s) and s[i + 1] in ('"', '\\'):
        i += 1
        cur += s[i]
      elif ch == q:
        in_q = False
      else:
        cur += ch
    elif ch in ("'", '"'):
      in_q, q, has_tok = True, ch, True
    elif ch == '\\' and i + 1 < len(s) and (s[i + 1] in ("'", '"') or s[i + 1].isspace()):
      i += 1
      cur += s[i]
      has_tok = True
    elif ch.isspace():
      if has_tok:
        out.append(cur)
        cur, has_tok = '', False
    else:
      cur += ch
      has_tok = True
    i += 1
  if in_q:
    raise ValueError('unterminated quote in DRIFT_TEST_CMD')
  if has_tok:
    out.append(cur)
  return out


def ensure_export_generation(area: Any, cli: str, ids: list[str], tomls: list[str], res_dir: Any) -> Any:
  import hashlib
  import json
  import os
  from pathlib import Path
  import shutil
  import subprocess
  area_p, res_p = Path(area), Path(res_dir)
  h = hashlib.sha256(b'drift.export-generation/1\n')
  cfg_f = area_p / '.drift' / 'config.toml'
  if cfg_f.is_file():
    h.update(b'cfg:')
    h.update(cfg_f.read_bytes())
  p_dir = area_p / '.drift' / 'profiles'
  if p_dir.is_dir():
    for pf in sorted(p_dir.glob('*.toml')):
      h.update(f'p:{pf.name}:'.encode('utf-8'))
      h.update(pf.read_bytes())
  for cid, tf in zip(ids, tomls):
    tp = Path(tf)
    if tp.is_file():
      h.update(f'c:{cid}:'.encode('utf-8'))
      h.update(tp.read_bytes())
  gen_id = f'gen-{h.hexdigest()[:16]}'
  gen_root = area_p / '.drift-work' / 'resolved-gen'
  gen_dir = gen_root / gen_id
  man_p = gen_dir / 'manifest.json'
  warm_ok = False
  if man_p.is_file():
    try:
      man = json.loads(man_p.read_text(encoding='utf-8'))
      m_files = man.get('files') if isinstance(man, Mapping) else None
      if isinstance(man, Mapping) and man.get('generation') == gen_id and isinstance(m_files, Mapping):
        warm_ok = all((gen_dir / f'{cid}.json').is_file() and hashlib.sha256((gen_dir / f'{cid}.json').read_bytes()).hexdigest() == m_files.get(cid) for cid in ids)
    except Exception:
      warm_ok = False
  if not warm_ok:
    gen_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = gen_root / f'.tmp-{os.getpid()}'
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    show_p = subprocess.run([cli, 'show', *tomls, '--out', str(tmp_dir)], cwd=str(area_p), capture_output=True, text=True, check=False)
    if show_p.returncode != 0:
      shutil.rmtree(tmp_dir, ignore_errors=True)
      raise RuntimeError((show_p.stderr or show_p.stdout or '').strip() or f'drift show failed with status {show_p.returncode}')
    f_map = {cid: hashlib.sha256((tmp_dir / f'{cid}.json').read_bytes()).hexdigest() for cid in ids if (tmp_dir / f'{cid}.json').is_file()}
    (tmp_dir / 'manifest.json').write_text(json.dumps({'schema': 'drift.export-generation/1', 'generation': gen_id, 'files': f_map}) + '\n', encoding='utf-8')
    try:
      if gen_dir.exists():
        shutil.rmtree(gen_dir, ignore_errors=True)
      tmp_dir.rename(gen_dir)
    except Exception:
      shutil.rmtree(tmp_dir, ignore_errors=True)
  for cid in ids:
    gf = gen_dir / f'{cid}.json'
    if gf.is_file():
      shutil.copyfile(gf, res_p / f'{cid}.json')
  return gen_dir


def sidecar_head(environ: Mapping[str, str], classes: Any, tests: Any) -> dict[str, Any]:
  import re
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


def merge_prior_inventory(out: str, inv: dict[str, Any], is_shard: bool, root_dir: Any, resolve_selected_files: Callable[..., Any]) -> None:
  import json
  from pathlib import Path
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

