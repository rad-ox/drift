"""Zero-dependency Python 3 bridge for DRIFT (unittest / pytest)."""
from __future__ import annotations

import atexit
import contextvars
import hashlib
import importlib.util
import json
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

try:
    from . import drift_checks as _checks
except ImportError:
    try:
        import drift_checks as _checks  # type: ignore[no-redef]
    except ImportError:
        _spec = importlib.util.spec_from_file_location('drift_checks', Path(__file__).with_name('drift_checks.py'))
        assert _spec is not None and _spec.loader is not None
        _checks = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_checks)
_probes = _checks._uic

ThenView = _checks.ThenView
expand_domain = _checks.expand_domain
_escape_ptr = _checks.escape_pointer
_apply_mutation = _checks.apply_mutation

_VIEWS, _TOML_DIRS, _WARMED, _BATCH = {}, {}, set(), {}
_cli_key = _cli_bin = ''
_METRICS, _DIGESTS, _INVS = {}, {}, {}
_env_cache = _sel_cache = _fc_cache = _mut_cache = _ev_dir_cache = _shard_path = _mut_shard_path = None
_shard_seq = 0
_DISC_CLASSES, _DISC_TESTS = set(), set()
_CTX_VAR = contextvars.ContextVar('drift_ctx', default=None)
_MUT_VAR = contextvars.ContextVar('drift_mut', default=())
_IO_LOCK, _exit_hook = threading.RLock(), False

_BAD_CLS = frozenset(('/', '\\', '#', '[', ']'))
_BAD_MTH = frozenset(('#', '[', ']'))
_ENV_KEYS = ('adapter', 'config', 'deps', 'drift', 'policy', 'runner', 'toolchain')


_strip_bom = _checks._ce.strip_bom
_read_json = _checks._ce.read_json
_dump_json = _checks._ce.dump_json
_hash_bytes = _checks._ce.hash_bytes


def _input_digest(abs_p, pre=None):
    key, st = str(abs_p), abs_p.stat()
    sig = (st.st_mtime_ns, st.st_size)
    if pre is None and st.st_size > 65536 and _DIGESTS.get(key, (None, ''))[0] == sig: return _DIGESTS[key][1]
    dig = _hash_bytes(pre if pre is not None else abs_p.read_bytes())
    _DIGESTS[key] = (sig, dig)
    return dig


def _resolve_env():
    global _env_cache
    raw, pk = os.environ.get('DRIFT_ENV', '').strip(), os.environ.get('DRIFT_PROOF_KEY', '').strip()
    if not raw and pk not in ('1', 'true'): return None
    cache_key = f'{pk}\x00{raw}'
    if _env_cache is not None and _env_cache[0] == cache_key: return _env_cache[1]
    base = _probes.build_env_dict('drift.py@0.10.0', raw, _strip_bom, _ENV_KEYS)
    _env_cache = (cache_key, base)
    return base


def _flush_inventory(out, inv):
    if not inv.get('dirty'): return
    inv['dirty'], inv['flushed'] = False, True
    _checks.merge_prior_inventory(out, inv, _shard_path is not None and out == str(_shard_path), Path.cwd())
    sidecar = _checks.sidecar_head(os.environ, inv['classes'], inv['tests'])
    raw_in = inv.get('inputs') or {}
    if raw_in: sidecar['inputs'] = {t: {fp: raw_in[t][fp] for fp in sorted(raw_in[t])} for t in sorted(raw_in) if raw_in[t]}
    env_obj = _resolve_env()
    if env_obj is not None: sidecar['env'] = env_obj
    Path(out[:-6] + '.meta.json').write_text(_dump_json(sidecar) + '\n', encoding='utf-8')


def flush_all_inventories() -> None:
    with _IO_LOCK:
        for out, inv in list(_INVS.items()): _flush_inventory(out, inv)


_CLI_STATE = ['', '']


def _auto_resolve(contract_id, target_json=None):
    return _checks.auto_resolve_contract(contract_id, _BATCH, _TOML_DIRS, _WARMED, _CLI_STATE, _read_json, _strip_bom, target_json)


def _resolve_stub_contract(id_or_res, case_id, base=None):
    up, cur = _checks.find_upstream_contract(id_or_res), _CTX_VAR.get()
    if up is not None and cur is not None and id_or_res != cur.contract_id:
        cur.record_input(up[1])
    v = up[0] if up is not None else _load_view(id_or_res)
    resolved_id = _checks.resolve_stub_case_id(v, id_or_res, case_id, base)
    if cur is not None:
        if id_or_res == cur.contract_id or (up is None and v.get('id') == cur.contract_id):
            cur.record_input(f'.drift/self-stub/{cur.contract_id}', 'sha256:self-stub')
        else:
            cur.record_input(f'.drift/seam-stub/{v.get("id") or id_or_res}#{resolved_id}', str(v.get('ref') or v.get('digest') or 'sha256:seam-stub'))
    return (v, resolved_id)


def build_stub(id_or_res, case_id, base=None):
    v, resolved_id = _resolve_stub_contract(id_or_res, case_id, base)
    mut_then = _checks._up.resolve_seam_mutated_then(_CTX_VAR.get(), v, id_or_res, resolved_id, _escape_ptr, _apply_mutation)
    return _checks.build_projected_output(v, resolved_id, base, mut_then)


def build_stub_variants(id_or_res, case_id, base=None):
    v, resolved_id = _resolve_stub_contract(id_or_res, case_id, base)
    return _checks.build_projected_variants(v, resolved_id, base)


def verify_stub(id_or_res, case_id, payload):
    v, resolved_id = _resolve_stub_contract(id_or_res, case_id)
    proj = _checks.extract_projection_map(v, 'then')
    for k, exp in (v['cases'][resolved_id].get('then') or {}).items():
        _checks.check_projected_leaf(v.get('id') or id_or_res, resolved_id, k, exp, payload, proj, None, True, 'no projection for')
    return True


def _load_view(contract_id):
    return _probes.load_view_doc(contract_id, _VIEWS, os.environ, _auto_resolve, _checks.attach_bridge_plan_file, _read_json)


def _load_selection():
    global _sel_cache
    if _sel_cache is not None: return _sel_cache
    sel = os.environ.get('DRIFT_SELECT', '').strip()
    if not sel or not Path(sel).is_file():
        _sel_cache = {'all': True, 'tests': set(), 'by_c': {}, 'tagged': set()}
        return _sel_cache
    _sel_cache = _checks.parse_selection_doc(_read_json(Path(sel)))
    return _sel_cache


def should_run(contract_id, test_id, cases=()):
    global _fc_cache
    _record_discovery(test_id)
    fc = os.environ.get('DRIFT_CONTRACTS', '').strip()
    if fc:
        if _fc_cache is None or _fc_cache[0] != fc:
            _fc_cache = (fc, {x.strip() for x in fc.split(',') if x.strip()})
        if contract_id not in _fc_cache[1]: return False
    sel = _load_selection()
    if sel['all'] or test_id in sel['tests'] or contract_id in sel['tagged']: return True
    ch = sel['by_c'].get(contract_id)
    return bool(ch and any(c in ch for c in cases))


def _discover_events_dir():
    global _ev_dir_cache
    if _ev_dir_cache is None:
        _ev_dir_cache = _checks._up.discover_events_dir(Path.cwd(), os.environ)
    return _ev_dir_cache


def _resolve_events_file():
    global _shard_path, _shard_seq
    tgt = os.environ.get('DRIFT_EVENTS', '').strip() or _discover_events_dir()
    if not tgt: return ''
    if tgt.endswith('.jsonl'): Path(tgt).parent.mkdir(parents=True, exist_ok=True); return tgt
    if _shard_path is None:
        Path(tgt).mkdir(parents=True, exist_ok=True); _shard_seq += 1
        _shard_path = Path(tgt) / f'{int(time.time() * 1000):013d}-{os.getpid()}-{_shard_seq}.jsonl'
    return str(_shard_path)


def _ensure_inventory(out):
    return _INVS.setdefault(out, {'classes': set(_DISC_CLASSES), 'tests': set(_DISC_TESTS), 'inputs': {}, 'dirty': True, 'flushed': False})


def _ensure_exit_hook():
    global _exit_hook
    if not _exit_hook:
        _exit_hook = True
        atexit.register(flush_all_inventories)


def _record_discovery(test_id, active_out=''):
    _probes.record_discovery_into(test_id, active_out, os.environ, _discover_events_dir, _shard_path, _BAD_CLS, _BAD_MTH, _DISC_CLASSES, _DISC_TESTS, _ensure_inventory, _flush_inventory, _ensure_exit_hook)


def _write_event(ev):
    with _IO_LOCK:
        out = _resolve_events_file()
        if not out:
            return
        inv = _ensure_inventory(out)
        _record_discovery(ev['test'], out)
        if inv.get('dirty'):
            _flush_inventory(out, inv)
        with Path(out).open('a', encoding='utf-8') as fh:
            fh.write(_dump_json(ev) + '\n')


def _load_mutants():
    global _mut_cache
    mf, out_t = os.environ.get('DRIFT_MUTANTS', '').strip(), os.environ.get('DRIFT_MUTATION_EVENTS', '').strip()
    if not mf and not out_t:
        return None
    if not mf or not out_t:
        raise ValueError('DRIFT_MUTANTS and DRIFT_MUTATION_EVENTS must be set together')
    if _mut_cache is not None and _mut_cache['file'] == mf and _mut_cache['out_t'] == out_t:
        return _mut_cache
    raw = Path(mf).read_bytes()
    _mut_cache = _checks.parse_mutation_manifest_doc(mf, out_t, f'sha256:{hashlib.sha256(raw).hexdigest()}', json.loads(_strip_bom(raw.decode('utf-8'))))
    return _mut_cache


def _resolve_mutation_file(output_target):
    global _mut_shard_path
    if output_target.endswith('.jsonl'):
        p = Path(output_target)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    td = Path(output_target)
    if _mut_shard_path is None or _mut_shard_path.parent != td:
        td.mkdir(parents=True, exist_ok=True)
        _mut_shard_path = td / 'results.jsonl'
    return _mut_shard_path


def mutation_depth():
    return len(_MUT_VAR.get())


def observe(contract='', case='', test='', when=None, then=None, at=None):
    tgt = os.environ.get('DRIFT_OBSERVE', '').strip()
    if not tgt or not isinstance(then, Mapping) or not then:
        return False
    out = Path(tgt) if tgt.endswith('.jsonl') else Path(tgt) / f'trace-{os.getpid()}.jsonl'
    out.parent.mkdir(parents=True, exist_ok=True)
    row = {'kind': 'trace', 'version': 1, **({k: v for k, v in (('contract', contract), ('case', case), ('test', test)) if v}), **({'at': list(at)} if at else {}), 'when': dict(when) if isinstance(when, Mapping) else {}, 'then': dict(then)}
    with _IO_LOCK, out.open('a', encoding='utf-8') as fh:
        fh.write(_dump_json(row) + '\n')
    return True


def with_mutation(target, fn):
    if not isinstance(target, Mapping) or not all(isinstance(target.get(k), str) for k in ('contract', 'case', 'path')):
        raise ValueError('invalid mutation target')
    tok = _MUT_VAR.set((*_MUT_VAR.get(), dict(target)))
    try:
        return fn()
    finally:
        _MUT_VAR.reset(tok)


def _active_mutation_for(contract_id, cases):
    for m in reversed(_MUT_VAR.get()):
        if m.get('contract') == contract_id and m.get('case') in cases:
            return m
    return None


class DriftContext:

    def __init__(self, contract_id, test_id, cases, level='unit', mutation_override=None):
        if not cases:
            raise ValueError(f'@DriftCase for "{test_id}" requires at least one case id')
        self.contract_id, self.test_id, self.cases, self.level = contract_id, test_id, list(cases), level or 'unit'
        eff_mut = mutation_override if mutation_override is not None else _active_mutation_for(contract_id, self.cases)
        self.view, self.mutation_override = _load_view(contract_id), eff_mut
        self.reads, self.unobserved_cases, self._input_files, self._obs = {}, set(), {}, {}
        vc = self.view.get('cases') or {}
        for c in self.cases:
            if c not in vc:
                raise ValueError(f'contract "{contract_id}" has no case "{c}"')
            self.reads[c] = set()
        m = eff_mut
        mp = m.get('path') if isinstance(m, Mapping) and isinstance(m.get('path'), str) else ''
        mc = _escape_ptr(str(m.get('case', ''))) if isinstance(m, Mapping) else ''
        is_w = bool(m is not None and m.get('contract') == contract_id and (m.get('is_when') is True or mp.startswith(f'/cases/{mc}/when/')))
        is_s = bool(m is not None and mp.startswith(f'/cases/{mc}/seam/'))
        self._mutated_when = _apply_mutation(dict(vc[m['case']].get('when') or {}), contract_id, m['case'], mp, m['after'], 'when', m.get('segments')) if is_w and m is not None else None
        self._mutated_then = _apply_mutation(dict(vc[m['case']].get('then') or {}), contract_id, m['case'], mp, m['after'], 'then', m.get('segments')) if m is not None and m.get('contract') == contract_id and not is_w and not is_s else None

    def _require_tagged(self, c):
        if c not in self.reads:
            raise ValueError(f'test "{self.test_id}" is not tagged with case "{c}"')

    def _when_table(self, c):
        if self._mutated_when is not None and self.mutation_override is not None and self.mutation_override['case'] == c:
            return self._converted_table('when', self._mutated_when)
        return self._converted_table('when', self.view['cases'][c].get('when') or {})

    def _then_table(self, c):
        if self._mutated_then is not None and self.mutation_override is not None and self.mutation_override['case'] == c:
            return self._converted_table('then', self._mutated_then)
        return self._converted_table('then', self.view['cases'][c].get('then') or {})

    def _converted_table(self, side, table):
        return _checks._ce.converted_table(self.view, side, table)

    def _when_env(self, c, payload=None, explicit_when=None):
        return _checks._uis.build_when_env(self._when_table(c), self._proj_map('when'), self._then_table(c), self._proj_map('then'), payload, explicit_when, _checks.read_pointer, _checks.check_relational_leaf, self.contract_id, c)

    def _u03(self, v):
        return _checks._uis.unwrap_03_eq(v) if self.view.get('drift') == '0.3' else v

    def when(self, c, k):
        self._require_tagged(c)
        w = self._when_table(c)
        if k not in w: raise KeyError(f'case "{c}" has no when.{k}')
        return self._u03(w[k])

    def find_when(self, c, k, fb=None):
        self._require_tagged(c)
        w = self._when_table(c)
        return self._u03(w[k]) if k in w else fb

    def when_table(self, c):
        self._require_tagged(c)
        return {k: self._u03(v) for k, v in _checks.clone_json(self._when_table(c)).items()}

    def for_each_case(self, fn):
        for c in self.cases: fn(c, self.when_table(c))

    def expect(self, c, k):
        self._require_tagged(c)
        t = self._then_table(c)
        if k not in t: raise KeyError(f'case "{c}" has no then.{k}')
        self.reads[c].add(k)
        return self._u03(t[k])

    def find_then(self, c, k, fb=None):
        self._require_tagged(c)
        t = self._then_table(c)
        if k not in t: return fb
        self.reads[c].add(k)
        return self._u03(t[k])

    def then(self, c: str) -> ThenView:
        self._require_tagged(c)
        return ThenView({k: self._u03(v) for k, v in self._then_table(c).items()}, self.reads[c])

    def record_input(self, fp: str | Path, pre: bytes | str | None = None) -> str:
        return _probes.record_context_input(self, fp, pre, _input_digest, _resolve_events_file, _record_discovery, _INVS)

    def read_fixture(self, fp: str | Path, encoding: str = 'utf-8') -> str:
        raw = Path(os.path.normpath(Path(os.getcwd()) / fp)).read_bytes()
        self.record_input(fp, raw)
        return _strip_bom(raw.decode(encoding))

    def bind_ui_environment(self, p: str | Path, o: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return _checks._ui.bind_ui_environment(self, p, o)

    def check(self, case_id, checks, when=None):
        self._require_tagged(case_id)
        tt = self._then_table(case_id)
        _checks.run_simple_checks(self.contract_id, case_id, tt, self.reads[case_id], checks, self._when_env(case_id, checks, when))
        if self.view.get('drift') == '0.3' and self.mutation_override is None and not self._proj_map('then') and not _checks._sec.forbidden_writes_of(self.view, case_id) and not any(k[0] == f'.drift/self-stub/{self.contract_id}' for k in self._input_files.values()):
            src = checks.get('then') if isinstance(checks, Mapping) and isinstance(checks.get('then'), Mapping) and not any(k in checks for k in tt) else checks
            if isinstance(src, Mapping) and not any(callable(src.get(k)) for k in tt):
                def _e(v, d=0):
                    if d > 6 or (isinstance(v, str) and len(v) > 1024) or (isinstance(v, (list, tuple, Mapping)) and len(v) > 64): raise ValueError
                    if v is None or isinstance(v, (bool, str)): return v
                    if isinstance(v, int) and -(1 << 53) < v < (1 << 53): return v
                    if isinstance(v, float) and _checks.is_finite_num(v): return v
                    if isinstance(v, (list, tuple)): return [_e(x, d + 1) for x in v]
                    if isinstance(v, Mapping): return {('$' + k if k.startswith('$') else k): _e(val, d + 1) for k, val in v.items() if isinstance(k, str)}
                    raise ValueError
                try:
                    ep = _e({k: src[k] for k in tt})
                    if len(_dump_json(ep)) <= 4096: self._obs[case_id] = {'schema': 'drift.observation/1', 'payload': ep}
                except ValueError: pass

    def check_bounds(self, case_id, domain, checks):
        self._require_tagged(case_id)
        _checks.run_domain_bounds_check(self.contract_id, case_id, self._then_table(case_id), self.reads[case_id], domain, checks, self.mutation_override is not None)

    def _dom_spec(self, p): return _checks.resolve_param_spec(self.contract_id, self.view, p)
    def profile_domain(self, p): return expand_domain(self._dom_spec(p), self.mutation_override is not None)
    def check_profile_bounds(self, case_id, p, checks): self.check_bounds(case_id, self._dom_spec(p), checks)
    def _proj_map(self, side): return _checks.extract_projection_map(self.view, side)

    def build_input(self, case_id, base=None):
        self._require_tagged(case_id)
        return _checks.build_projected_input(self.view, self._when_table(case_id), base)

    def build_output(self, case_id, base=None):
        self._require_tagged(case_id)
        self.record_input(f'.drift/self-stub/{self.contract_id}', 'sha256:self-stub')
        return _checks.build_projected_output(self.view, case_id, base, self._then_table(case_id))

    def check_projection(self, case_id, payload, checks=None, when=None): _checks.run_projection_checks(self, case_id, payload, checks, when)
    def check_adverse(self, case_id, harness, checks=None): _checks.run_adverse_checks(self, case_id, harness, checks)
    def check_seam_bounds(self, case_id, id_or_res, prod_case, checks, base=None): _checks._up.run_seam_bounds_checks(self, case_id, id_or_res, prod_case, checks, base, _resolve_stub_contract, _checks.build_projected_variants)
    def check_frame(self, case_id, frame_obs): _checks._sec.verify_case_frame(self, case_id, frame_obs, _checks.values_mismatch, True)
    def check_idempotency(self, case_id, obs): return _checks._sec.run_idempotency_probe(self, case_id, obs, _checks.values_mismatch, lambda ctx, cid, p, ch: _checks.run_projection_checks(ctx, cid, p, ch))
    def check_seam_probe(self, case_id, obs): return _checks._sec.run_seam_probe(self, case_id, obs)
    def check_rollback(self, case_id, obs): return _checks._sec.run_rollback_probe(self, case_id, obs, _checks.values_mismatch)
    def check_log_sink(self, case_id, obs): return _checks._sec.run_log_sink_probe(self, case_id, obs)
    def check_view(self, case_id, view, checks=None, when=None):
        self._require_tagged(case_id)
        _checks.check_view_table(self.contract_id, case_id, self._then_table(case_id), self.reads[case_id], view, checks, self.mutation_override, _METRICS, lambda: self._proj_map('then'), self._when_env(case_id, view, when))

    def fully_read_cases(self) -> list[str]:
        out: list[str] = []
        unobs = getattr(self, 'unobserved_cases', set())
        for c in self.cases:
            if c in unobs: continue
            t_keys = list((self.view['cases'][c].get('then') or {}).keys())
            f_res, r_probes, seen = _checks._sec.forbidden_writes_of(self.view, c), _checks._sec.required_probes_of(self.view, c), self.reads[c]
            if t_keys and all(k in seen for k in t_keys) and all(f'@frame:{r}' in seen for r in f_res) and all(f'@probe:{p}' in seen for p in r_probes):
                out.append(c)
        return out


def select_files(sel: Any = None, root_dir: str | Path | None = None) -> list[str]:
    raw_sel = os.environ.get('DRIFT_SELECT', '').strip() if sel is None else sel
    raw = _read_json(Path(raw_sel)) if isinstance(raw_sel, (str, Path)) and str(raw_sel) and Path(raw_sel).is_file() else raw_sel
    return _checks.resolve_selected_files(raw, Path(root_dir or Path.cwd()).resolve())


def reset_drift_cache() -> None:
    global _env_cache, _sel_cache, _fc_cache, _mut_cache, _ev_dir_cache, _shard_path, _mut_shard_path
    flush_all_inventories()
    _checks.clear_upstream_cache()
    for cache_coll in (_VIEWS, _TOML_DIRS, _WARMED, _BATCH, _METRICS, _DIGESTS, _DISC_CLASSES, _DISC_TESTS): cache_coll.clear()
    _MUT_VAR.set(())
    _env_cache = _sel_cache = _fc_cache = _mut_cache = _ev_dir_cache = _shard_path = _mut_shard_path = None


def run_drift_case(contract: str, test: str, cases: list[str] | tuple[str, ...], fn: Callable[[DriftContext], Any], level: str = 'unit') -> str:
    if not should_run(contract, test, cases): return 'skipped-by-select'
    if sys.flags.optimize > 0:
        _write_event({'test': test, 'contract': contract, 'cases': list(cases), 'level': level, 'outcome': 'failed', 'read': []})
        raise AssertionError('DRIFT proof runs require Python assertions to be enabled (do not run with -O or PYTHONOPTIMIZE)')
    try: ctx = DriftContext(contract, test, cases, level)
    except Exception:
        _write_event({'test': test, 'contract': contract, 'cases': list(cases), 'level': level, 'outcome': 'failed', 'read': []})
        raise
    version, mut_cfg, start, passed, control_err = (ctx.view.get('ref') or ctx.view.get('digest') or ''), _load_mutants(), time.perf_counter(), False, None
    tok = _CTX_VAR.set(ctx)
    try:
        fn(ctx)
        _probes.verify_recorded_inputs(contract, test, ctx._input_files, _DIGESTS, _hash_bytes)
        passed = True
    except BaseException as err: control_err = err
    finally: _CTX_VAR.reset(tok)
    ev: dict[str, Any] = {'test': test, 'contract': contract, 'cases': ctx.cases, 'level': ctx.level, 'outcome': 'passed' if passed else 'failed', 'read': ctx.fully_read_cases()}
    if version: ev['digest'] = version
    if ctx.view.get('drift') == '0.3':
        for rc in (ctx.view.get('required_capabilities') or ()):
            if rc not in _checks.CAPS_03: raise AssertionError(f'bridge.capability_unsupported:{rc}')
        ev['schema'], ev['capabilities'] = '0.3', list(_checks.CAPS_03)
        if passed and ctx._obs: ev['observations'] = ctx._obs
    _write_event(ev)
    elapsed = max(0.001, time.perf_counter() - start)
    if mut_cfg is not None:
        _checks._up.run_case_mutants(mut_cfg, _resolve_mutation_file(mut_cfg['out_t']), ctx, contract, passed, elapsed, time, with_mutation, lambda t: DriftContext(contract, test, cases, level, t), fn, _dump_json)
    if not passed and control_err is not None: raise control_err
    return 'passed'


if __name__ == '__main__':
    sys.exit(_checks.run_drift_cli(sys.argv[1:]))


