"""Reusable observable behavioral probes for the DRIFT Python bridge."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from pathlib import Path
import re
from typing import Any

DEFAULT_VOLATILE_KEYS = frozenset(('request_id', 'timestamp', 'trace_id', 'audit_id'))
DEFAULT_ALLOWED_SECOND_WRITES = frozenset(('AUDIT_LOG', 'audit_log', 'METRICS', 'metrics'))
FRAME_ENTRY_KEYS = frozenset(('writes', 'operations', 'events', 'before', 'after', 'observed'))


def validate_shadow_state_dir(cwd: Path, environ: Mapping[str, str]) -> str:
  raw = environ.get('DRIFT_STATE_DIR', '').strip()
  if not raw:
    return ''
  sd, rc = (Path(raw).resolve() if Path(raw).exists() else (cwd / raw).resolve()), cwd.resolve()
  mf = sd / 'shadow.toml'
  if mf.is_symlink():
    raise ValueError('symlink shadow.toml')
  if mf.exists():
    txt = mf.read_text(encoding='utf-8')
    m = re.search(r'^\s*source_root\s*=\s*"([^"]*)"', txt, re.M)
    sr = environ.get('DRIFT_SOURCE_ROOT', '').strip() or (m.group(1) if m else '')
    rs = (sd / sr).resolve() if sr else None
    if '"drift.shadow-area/1"' not in txt or rs is None or sd == rs or rs in sd.parents or not (rc == rs or rs in rc.parents):
      raise ValueError('state_dir mismatch')
  return str(sd)


def resolve_cli_work_paths(cwd: Path, environ: Mapping[str, str]) -> tuple[Path, Path, Path, Path, bool, bool]:
  sd = validate_shadow_state_dir(cwd, environ)
  area = cwd.resolve()
  if sd:
    sd_p, mf = Path(sd), Path(sd) / 'shadow.toml'
    m = re.search(r'^\s*source_root\s*=\s*"([^"]*)"', mf.read_text(encoding='utf-8'), re.M) if mf.is_file() else None
    sr = environ.get('DRIFT_SOURCE_ROOT', '').strip() or (m.group(1) if m else '')
    area, state_area = ((sd_p / sr).resolve() if sr else area), sd_p
  else:
    while not (area / '.drift' / 'contracts').is_dir() and area.parent != area:
      area = area.parent
    state_area = area
  wk = state_area / '.drift-work'
  rk = re.sub(r'[^A-Za-z0-9._-]+', '_', (environ.get('DRIFT_RUN_ID', '').strip() or environ.get('DRIFT_PACK_REF', '').strip())).strip('_')
  return area, state_area, wk, ((wk / 'runs' / rk) if rk else wk), bool(rk), bool(sd and state_area != area)


def write_atomic_utf8(target: Path, text: str) -> None:
  target.parent.mkdir(parents=True, exist_ok=True)
  t = target.parent / f'{target.name}.tmp.{os.getpid()}'
  t.write_text(text, encoding='utf-8')
  t.replace(target)


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


def run_idempotency_probe(ctx: Any, case_id: str, obs: Any, values_mismatch: Callable[[Any, Any], bool], run_projection_fn: Callable[..., None] | None = None) -> dict[str, Any]:
  ctx._require_tagged(case_id)
  pfx, strict = f'{ctx.contract_id}.{case_id}', not isinstance(obs, Mapping) or obs.get('strict') is not False
  if not isinstance(obs, Mapping):
    return _unverified_or_raise(ctx, case_id, strict, 'idempotency.unobserved', 'unobserved')
  s1, s2 = obs.get('stateAfterFirst', obs.get('state_after_first')), obs.get('stateAfterSecond', obs.get('state_after_second'))
  has_state = s1 is not None and s2 is not None
  sw = obs.get('secondWrites', obs.get('second_writes'))
  second_writes = sw if isinstance(sw, Mapping) else None
  if has_state and values_mismatch(s1, s2):
    raise AssertionError(f'{pfx}: idempotency.domain_state_mutated')
  if second_writes is not None:
    ra = obs.get('allowedSecondWrites', obs.get('allowed_second_writes'))
    a2 = {str(x) for x in ra} if isinstance(ra, (list, tuple)) else set(DEFAULT_ALLOWED_SECOND_WRITES)
    for res, wv in second_writes.items():
      rs = str(res)
      if rs in a2 or rs.partition('#')[0] in a2:
        continue
      cnt = len(wv) if isinstance(wv, (list, tuple)) else wv
      if not _is_non_neg_int(cnt) or int(cnt) > 0:
        raise AssertionError(f'{pfx}: idempotency.duplicate_write on "{rs}": {cnt}')
  fp, sp = obs.get('first'), obs.get('second')
  if isinstance(fp, Mapping) and isinstance(sp, Mapping):
    rv = obs.get('volatileKeys', obs.get('volatile_keys'))
    vol = {str(x) for x in rv} if isinstance(rv, (list, tuple)) else set(DEFAULT_VOLATILE_KEYS)
    for k, v1 in fp.items():
      ks = str(k)
      if ks not in vol and ks != '_frame' and k in sp and values_mismatch(v1, sp[k]):
        raise AssertionError(f'{pfx}: idempotency.response_diverged on "{ks}"')
  if obs.get('observed') is False or (not has_state and second_writes is None):
    return _unverified_or_raise(ctx, case_id, strict, 'idempotency.unobserved', 'unobserved')
  if 'first' in obs and obs['first'] is not None and run_projection_fn is not None:
    run_projection_fn(ctx, case_id, obs['first'], obs.get('checks') if isinstance(obs.get('checks'), Mapping) else {})
  if hasattr(ctx, 'reads') and isinstance(ctx.reads, Mapping) and case_id in ctx.reads:
    ctx.reads[case_id].add('@probe:idempotency')
  return {'observed': True, 'reason': ''}


def run_seam_probe(ctx: Any, case_id: str, obs: Any) -> dict[str, Any]:
  ctx._require_tagged(case_id)
  pfx, strict = f'{ctx.contract_id}.{case_id}', not isinstance(obs, Mapping) or obs.get('strict') is not False
  if not isinstance(obs, Mapping):
    return _unverified_or_raise(ctx, case_id, strict, 'seam.unobserved', 'unobserved')
  ma, mq = obs.get('maxAttempts', obs.get('max_attempts')), obs.get('maxQueries', obs.get('max_queries'))
  has_r, has_t, has_q, att = ('retryable' in obs or ma is not None), (obs.get('timedOut', obs.get('timed_out')) is True), (mq is not None), obs.get('attempts')
  if has_r and _is_non_neg_int(att) and int(att) > 0:
    if obs.get('retryable') is False and int(att) > 1:
      raise AssertionError(f'{pfx}: seam.non_retryable_retried')
    if obs.get('retryable') is True and int(att) < 2:
      raise AssertionError(f'{pfx}: seam.retry_missing')
    if ma is not None and (not _is_non_neg_int(ma) or int(att) > int(ma)):
      raise AssertionError(f'{pfx}: seam.max_attempts_exceeded')
  if has_t and _is_non_neg_int(obs.get('lateWrites', obs.get('late_writes', 0))) and int(obs.get('lateWrites', obs.get('late_writes', 0))) > 0:
    raise AssertionError(f'{pfx}: seam.timeout_late_write')
  if has_q and _is_non_neg_int(obs.get('queries')) and _is_non_neg_int(mq) and int(obs.get('queries')) > int(mq):
    raise AssertionError(f'{pfx}: seam.query_budget_exceeded')
  if obs.get('observed') is False or (not has_r and not has_t and not has_q) or (has_r and (not _is_non_neg_int(att) or int(att) <= 0)):
    return _unverified_or_raise(ctx, case_id, strict, 'seam.unobserved', 'unobserved')
  if has_t and not _is_non_neg_int(obs.get('lateWrites', obs.get('late_writes', 0))):
    return _unverified_or_raise(ctx, case_id, strict, 'seam.unobserved', 'unobserved')
  if has_q and (not _is_non_neg_int(obs.get('queries')) or not _is_non_neg_int(mq)):
    return _unverified_or_raise(ctx, case_id, strict, 'queries.unobserved', 'unobserved')
  if hasattr(ctx, 'reads') and isinstance(ctx.reads, Mapping) and case_id in ctx.reads:
    ctx.reads[case_id].add('@probe:seam')
  return {'observed': True, 'reason': ''}


def run_rollback_probe(ctx: Any, case_id: str, obs: Any, values_mismatch: Callable[[Any, Any], bool]) -> dict[str, Any]:
  ctx._require_tagged(case_id)
  pfx, strict = f'{ctx.contract_id}.{case_id}', not isinstance(obs, Mapping) or obs.get('strict') is not False
  if isinstance(obs, Mapping) and obs.get('before') is not None and obs.get('after') is not None:
    res = str(obs.get('resource') or 'primary')
    if values_mismatch(obs['before'], obs['after']) and obs.get('compensated') is not True:
      raise AssertionError(f'{pfx}: rollback.dirty_partial_write on "{res}"')
  if not isinstance(obs, Mapping) or obs.get('observed') is False or obs.get('before') is None or obs.get('after') is None:
    return _unverified_or_raise(ctx, case_id, strict, 'rollback.unobserved', 'unobserved')
  if hasattr(ctx, 'reads') and isinstance(ctx.reads, Mapping) and case_id in ctx.reads:
    ctx.reads[case_id].add('@probe:rollback')
  return {'observed': True, 'reason': ''}


def check_bola_variant_pair(pfx: str, variant: Any) -> bool:
  if not isinstance(variant, Mapping):
    return False
  b = variant.get('bola') if isinstance(variant.get('bola'), Mapping) else variant
  if 'actor_owner' not in b and 'resource_owner' not in b:
    return False
  a, o = str(b.get('actor_owner') or '').strip(), str(b.get('resource_owner') or '').strip()
  if not a or not o or a == o:
    raise AssertionError(f'{pfx}: bola.invalid_fixture')
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
  pfx, strict = f'{ctx.contract_id}.{case_id}', not isinstance(obs, Mapping) or obs.get('strict') is not False
  if not isinstance(obs, Mapping):
    return _unverified_or_raise(ctx, case_id, strict, 'log_sink.unobserved', 'unobserved')
  rs = obs.get('secretValues', obs.get('secret_values'))
  sec = [s for s in (rs if isinstance(rs, (list, tuple)) else ()) if isinstance(s, str) and s.strip()]
  logs = obs.get('logLines', obs.get('log_lines'))
  hl, hp = isinstance(logs, (str, list, tuple)), ('payload' in obs and obs['payload'] is not None)
  for s in sec:
    if (hl and _contains_str_leaf(logs, s)) or (hp and _contains_str_leaf(obs['payload'], s)):
      raise AssertionError(f'{pfx}: log_sink.secret_leaked')
  if obs.get('observed') is False or not sec or (not hl and not hp):
    return _unverified_or_raise(ctx, case_id, strict, 'log_sink.unobserved', 'unobserved')
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
  src_dir = gen_dir
  if not warm_ok:
    gen_root.mkdir(parents=True, exist_ok=True)
    src_dir = gen_root / f'.tmp-{os.getpid()}'
    shutil.rmtree(src_dir, ignore_errors=True)
    src_dir.mkdir(parents=True, exist_ok=True)
    show_p = subprocess.run([cli, 'show', *tomls, '--out', str(src_dir)], cwd=str(area_p), capture_output=True, text=True, check=False)
    if show_p.returncode != 0:
      shutil.rmtree(src_dir, ignore_errors=True)
      raise RuntimeError((show_p.stderr or show_p.stdout or '').strip() or f'drift show failed with status {show_p.returncode}')
    f_map = {cid: hashlib.sha256((src_dir / f'{cid}.json').read_bytes()).hexdigest() for cid in ids if (src_dir / f'{cid}.json').is_file()}
    (src_dir / 'manifest.json').write_text(json.dumps({'schema': 'drift.export-generation/1', 'generation': gen_id, 'files': f_map}) + '\n', encoding='utf-8')
  (res_p / '.plans').mkdir(parents=True, exist_ok=True)
  for cid in ids:
    gf, pf = src_dir / f'{cid}.json', src_dir / '.plans' / f'{cid}.plan.json'
    if gf.is_file(): shutil.copyfile(gf, res_p / f'{cid}.json')
    if pf.is_file(): shutil.copyfile(pf, res_p / '.plans' / f'{cid}.plan.json')
  if src_dir != gen_dir:
    try: src_dir.rename(gen_dir)
    except OSError: shutil.rmtree(src_dir, ignore_errors=True)
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

