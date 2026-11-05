"""Zero-dependency Python 3 bridge for DRIFT (unittest / pytest)."""
from __future__ import annotations

import atexit
import contextvars
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
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

ThenView = _checks.ThenView
expand_domain = _checks.expand_domain
_escape_ptr = _checks.escape_pointer
_apply_mutation = _checks.apply_mutation

_VIEWS: dict[str, dict[str, Any]] = {}
_TOML_DIRS: dict[str, dict[str, Path]] = {}
_WARMED: set[str] = set()
_BATCH: dict[str, dict[str, Any]] = {}
_cli_key = ''
_cli_bin = ''
_METRICS: dict[str, dict[str, Any]] = {}
_DIGESTS: dict[str, tuple[tuple[int, int] | None, str]] = {}
_env_cache: tuple[str, dict[str, str]] | None = None
_sel_cache: dict[str, Any] | None = None
_fc_cache: tuple[str, set[str]] | None = None
_mut_cache: dict[str, Any] | None = None
_ev_dir_cache: str | None = None
_shard_path: Path | None = None
_mut_shard_path: Path | None = None
_shard_seq = 0
_INVS: dict[str, dict[str, Any]] = {}
_DISC_CLASSES: set[str] = set()
_DISC_TESTS: set[str] = set()
_CTX_VAR: contextvars.ContextVar[Any] = contextvars.ContextVar('drift_ctx', default=None)
_MUT_VAR: contextvars.ContextVar[tuple[dict[str, Any], ...]] = contextvars.ContextVar('drift_mut', default=())
_IO_LOCK = threading.RLock()
_exit_hook = False

_SNAP_RE = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$')
_BAD_CLS = frozenset(('/', '\\', '#', '[', ']'))
_BAD_MTH = frozenset(('#', '[', ']'))
_ENV_KEYS = ('adapter', 'config', 'deps', 'drift', 'policy', 'runner', 'toolchain')


def _strip_bom(text: str) -> str:
    return text[1:] if text.startswith('\ufeff') else text


def _read_json(path: Path) -> Any:
    return json.loads(_strip_bom(path.read_text(encoding='utf-8')))


def _dump_json(obj: Any) -> str:
    return json.dumps(obj, separators=(',', ':'))


def _hash_bytes(raw: bytes) -> str:
    normalized = raw if b'\x00' in raw else raw.replace(b'\r\n', b'\n')
    return f'sha256:{hashlib.sha256(normalized).hexdigest()}'


def _input_digest(abs_p: Path, pre: bytes | None = None) -> str:
    key = str(abs_p)
    st = abs_p.stat()
    sig = (st.st_mtime_ns, st.st_size)
    if pre is None and st.st_size > 65536 and _DIGESTS.get(key, (None, ''))[0] == sig:
        return _DIGESTS[key][1]
    dig = _hash_bytes(pre if pre is not None else abs_p.read_bytes())
    _DIGESTS[key] = (sig, dig)
    return dig


def _resolve_env() -> dict[str, str] | None:
    global _env_cache
    raw = os.environ.get('DRIFT_ENV', '').strip()
    pk = os.environ.get('DRIFT_PROOF_KEY', '').strip()
    if not raw and pk not in ('1', 'true'):
        return None
    cache_key = f'{pk}\x00{raw}'
    if _env_cache is not None and _env_cache[0] == cache_key:
        return _env_cache[1]
    base = {
        'adapter': 'drift.py@0.3.0',
        'config': 'default',
        'deps': 'none',
        'drift': '0.3.0',
        'policy': 'core@1',
        'runner': 'python-unittest',
        'toolchain': f'python@{platform.python_version()}',
    }
    if raw:
        parsed = json.loads(_strip_bom(raw))
        if not isinstance(parsed, dict):
            raise ValueError('DRIFT_ENV must be a JSON object')
        for k, v in parsed.items():
            if k not in _ENV_KEYS or not isinstance(v, str) or not v.strip():
                raise ValueError(f'invalid DRIFT_ENV key "{k}"')
            base[k] = v.strip()
    _env_cache = (cache_key, base)
    return base


def _flush_inventory(out: str, inv: dict[str, Any]) -> None:
    if not inv.get('dirty'):
        return
    inv['dirty'] = False
    inv['flushed'] = True
    _checks.merge_prior_inventory(out, inv, _shard_path is not None and out == str(_shard_path), Path.cwd())
    snap = os.environ.get('DRIFT_SNAPSHOT', '').strip()
    if snap and _SNAP_RE.match(snap) is None:
        raise ValueError(f'invalid DRIFT_SNAPSHOT "{snap}"')
    sidecar: dict[str, Any] = {'version': 1, 'classes': sorted(inv['classes']), 'tests': sorted(inv['tests'])}
    if snap:
        sidecar['snapshot'] = snap
    pack_ref = os.environ.get('DRIFT_PACK_REF', '').strip()
    if pack_ref:
        sidecar['pack_ref'] = pack_ref
    touched = sorted({p.strip() for p in re.split(r'[\n,]+', os.environ.get('DRIFT_TOUCHED', '')) if p.strip()})
    if touched:
        sidecar['touched'] = touched
    raw_in = inv.get('inputs') or {}
    if raw_in:
        sidecar['inputs'] = {t: {fp: raw_in[t][fp] for fp in sorted(raw_in[t])} for t in sorted(raw_in) if raw_in[t]}
    env_obj = _resolve_env()
    if env_obj is not None:
        sidecar['env'] = env_obj
    Path(out[:-6] + '.meta.json').write_text(_dump_json(sidecar) + '\n', encoding='utf-8')


def flush_all_inventories() -> None:
    with _IO_LOCK:
        for out, inv in list(_INVS.items()):
            _flush_inventory(out, inv)


_CLI_STATE = ['', '']


def _auto_resolve(contract_id: str, target_json: Path | None = None) -> dict[str, Any] | None:
    return _checks.auto_resolve_contract(contract_id, _BATCH, _TOML_DIRS, _WARMED, _CLI_STATE, _read_json, _strip_bom, target_json)


def _resolve_stub_contract(id_or_res: str, case_id: str | Mapping[str, Any], base: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    up = _checks.find_upstream_contract(id_or_res)
    cur_ctx = _CTX_VAR.get()
    if up is not None and cur_ctx is not None:
        cur_ctx.record_input(up[1])
    v = up[0] if up is not None else _load_view(id_or_res)
    resolved_id = _checks.resolve_stub_case_id(v, id_or_res, case_id, base)
    return (v, resolved_id)


def build_stub(id_or_res: str, case_id: str | Mapping[str, Any], base: Mapping[str, Any] | None = None) -> Any:
    v, resolved_id = _resolve_stub_contract(id_or_res, case_id, base)
    return _checks.build_projected_output(v, resolved_id, base)


def build_stub_variants(id_or_res: str, case_id: str | Mapping[str, Any], base: Mapping[str, Any] | None = None) -> list[Any]:
    v, resolved_id = _resolve_stub_contract(id_or_res, case_id, base)
    return _checks.build_projected_variants(v, resolved_id, base)


def verify_stub(id_or_res: str, case_id: str | Mapping[str, Any], payload: Any) -> bool:
    v, resolved_id = _resolve_stub_contract(id_or_res, case_id)
    proj = _checks.extract_projection_map(v, 'then')
    for k, exp in (v['cases'][resolved_id].get('then') or {}).items():
        _checks.check_projected_leaf(v.get('id') or id_or_res, resolved_id, k, exp, payload, proj, None, True, 'no projection for')
    return True


def _load_view(contract_id: str) -> dict[str, Any]:
    if contract_id in _VIEWS:
        return _VIEWS[contract_id]
    res = os.environ.get('DRIFT_RESOLVED', '').strip()
    if not res:
        doc = _auto_resolve(contract_id)
        if doc is None:
            raise RuntimeError(f'DRIFT_RESOLVED is not set and contract "{contract_id}" could not be auto-resolved from .drift/')
        if doc.get('id') != contract_id:
            raise ValueError(f'resolved view for "{contract_id}" has id "{doc.get("id")}"')
        _VIEWS[contract_id] = doc
        return doc
    fp = Path(res) if res.endswith('.json') else Path(res) / f'{contract_id}.json'
    if not res.endswith('.json'):
        synced = _auto_resolve(contract_id, fp.resolve())
        if isinstance(synced, dict) and synced.get('id') == contract_id:
            _VIEWS[contract_id] = synced
            return synced
    if not fp.is_file():
        raise FileNotFoundError(f'contract "{contract_id}" was not found at {fp}')
    doc = _read_json(fp)
    if doc.get('id') != contract_id:
        raise ValueError(f'resolved view {fp} has id "{doc.get("id")}", exp "{contract_id}"')
    _VIEWS[contract_id] = doc
    return doc


def _load_selection() -> dict[str, Any]:
    global _sel_cache
    if _sel_cache is not None:
        return _sel_cache
    sel = os.environ.get('DRIFT_SELECT', '').strip()
    if not sel or not Path(sel).is_file():
        _sel_cache = {'all': True, 'tests': set(), 'by_c': {}, 'tagged': set()}
        return _sel_cache
    _sel_cache = _checks.parse_selection_doc(_read_json(Path(sel)))
    return _sel_cache


def should_run(contract_id: str, test_id: str, cases: tuple[str, ...] | list[str] = ()) -> bool:
    global _fc_cache
    _record_discovery(test_id)
    fc = os.environ.get('DRIFT_CONTRACTS', '').strip()
    if fc:
        if _fc_cache is None or _fc_cache[0] != fc:
            _fc_cache = (fc, {x.strip() for x in fc.split(',') if x.strip()})
        if contract_id not in _fc_cache[1]:
            return False
    sel = _load_selection()
    if sel['all'] or test_id in sel['tests'] or contract_id in sel['tagged']:
        return True
    ch = sel['by_c'].get(contract_id)
    return bool(ch and any(c in ch for c in cases))


def _discover_events_dir() -> str:
    global _ev_dir_cache
    if _ev_dir_cache is not None:
        return _ev_dir_cache
    cur = Path.cwd().resolve()
    area_root: Path | None = None
    while True:
        for sub in ('.drift', '.drift-work'):
            cand = cur / sub / 'events'
            if cand.is_dir():
                _ev_dir_cache = str(cand)
                return _ev_dir_cache
        if (cur / '.drift' / 'config.toml').is_file() or (cur / '.drift' / 'contracts').is_dir():
            area_root = cur
            break
        if cur.parent == cur:
            break
        cur = cur.parent
    _ev_dir_cache = str(area_root / '.drift-work' / 'events') if area_root is not None and not os.environ.get('DRIFT_RESOLVED', '').strip() else ''
    return _ev_dir_cache


def _resolve_events_file() -> str:
    global _shard_path, _shard_seq
    tgt = os.environ.get('DRIFT_EVENTS', '').strip() or _discover_events_dir()
    if not tgt:
        return ''
    if tgt.endswith('.jsonl'):
        Path(tgt).parent.mkdir(parents=True, exist_ok=True)
        return tgt
    if _shard_path is None:
        Path(tgt).mkdir(parents=True, exist_ok=True)
        _shard_seq += 1
        _shard_path = Path(tgt) / f'{int(time.time() * 1000):013d}-{os.getpid()}-{_shard_seq}.jsonl'
    return str(_shard_path)


def _ensure_inventory(out: str) -> dict[str, Any]:
    inv = _INVS.get(out)
    if inv is None:
        inv = {
            'classes': set(_DISC_CLASSES),
            'tests': set(_DISC_TESTS),
            'inputs': {},
            'dirty': True,
            'flushed': False,
        }
        _INVS[out] = inv
    return inv


def _record_discovery(test_id: str, active_out: str = '') -> None:
    global _exit_hook
    tgt = active_out or os.environ.get('DRIFT_EVENTS', '').strip() or _discover_events_dir()
    if not tgt:
        return
    h = test_id.find('#') if isinstance(test_id, str) else -1
    cls = test_id[:h] if h > 0 else ''
    mth = (test_id[h + 1:] if h > 0 else '').split('[', 1)[0]
    if (
        not cls
        or not mth
        or any(c.isspace() or c in _BAD_CLS for c in cls)
        or any(c.isspace() or c in _BAD_MTH for c in mth)
    ):
        raise ValueError(f'DRIFT_EVENTS requires a test id in Class#method form: "{test_id}"')
    canon = f'{cls}#{mth}'
    _DISC_CLASSES.add(cls)
    _DISC_TESTS.add(canon)
    out = active_out or (str(_shard_path) if _shard_path is not None else (tgt if tgt.endswith('.jsonl') and Path(tgt).is_file() else ''))
    if not out:
        return
    inv = _ensure_inventory(out)
    before = len(inv['classes']) + len(inv['tests'])
    inv['classes'].add(cls)
    inv['tests'].add(canon)
    if before == len(inv['classes']) + len(inv['tests']) and inv['flushed'] and not inv['dirty']:
        return
    inv['dirty'] = True
    if not _exit_hook:
        _exit_hook = True
        atexit.register(flush_all_inventories)
    if active_out:
        _flush_inventory(out, inv)


def _write_event(ev: dict[str, Any]) -> None:
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


def _load_mutants() -> dict[str, Any] | None:
    global _mut_cache
    mf = os.environ.get('DRIFT_MUTANTS', '').strip()
    out_t = os.environ.get('DRIFT_MUTATION_EVENTS', '').strip()
    if not mf and not out_t:
        return None
    if not mf or not out_t:
        raise ValueError('DRIFT_MUTANTS and DRIFT_MUTATION_EVENTS must be set together')
    if _mut_cache is not None and _mut_cache['file'] == mf and _mut_cache['out_t'] == out_t:
        return _mut_cache
    raw = Path(mf).read_bytes()
    manifest = json.loads(_strip_bom(raw.decode('utf-8')))
    manifest_id = f'sha256:{hashlib.sha256(raw).hexdigest()}'
    _mut_cache = _checks.parse_mutation_manifest_doc(mf, out_t, manifest_id, manifest)
    return _mut_cache


def _resolve_mutation_file(output_target: str) -> Path:
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


def mutation_depth() -> int:
    return len(_MUT_VAR.get())


def with_mutation(target: Mapping[str, Any], fn: Callable[[], Any]) -> Any:
    if (
        not isinstance(target, Mapping)
        or not isinstance(target.get('contract'), str)
        or not isinstance(target.get('case'), str)
        or not isinstance(target.get('path'), str)
    ):
        raise ValueError('invalid mutation target')
    tok = _MUT_VAR.set((*_MUT_VAR.get(), dict(target)))
    try:
        return fn()
    finally:
        _MUT_VAR.reset(tok)


def _active_mutation_for(contract_id: str, cases: list[str]) -> dict[str, Any] | None:
    for m in reversed(_MUT_VAR.get()):
        if m.get('contract') == contract_id and m.get('case') in cases:
            return m
    return None


class DriftContext:

    def __init__(self, contract_id: str, test_id: str, cases: list[str] | tuple[str, ...], level: str = 'unit', mutation_override: dict[str, Any] | None = None) -> None:
        if not cases:
            raise ValueError(f'@DriftCase for "{test_id}" requires at least one case id')
        self.contract_id = contract_id
        self.test_id = test_id
        self.cases = list(cases)
        self.level = level or 'unit'
        eff_mut = mutation_override if mutation_override is not None else _active_mutation_for(contract_id, self.cases)
        self.view = _load_view(contract_id)
        self.mutation_override = eff_mut
        self.reads: dict[str, set[str]] = {}
        self._input_files: dict[Path, tuple[str, str]] = {}
        vc = self.view.get('cases') or {}
        for c in self.cases:
            if c not in vc:
                raise ValueError(f'contract "{contract_id}" has no case "{c}"')
            self.reads[c] = set()
        m = eff_mut
        is_w = bool(
            m is not None
            and m.get('contract') == contract_id
            and (
                m.get('is_when') is True
                or (isinstance(m.get('path'), str) and m['path'].startswith(f"/cases/{_escape_ptr(m['case'])}/when/"))
            )
        )
        self._mutated_when = (
            _apply_mutation(dict(vc[m['case']].get('when') or {}), contract_id, m['case'], m['path'], m['after'], 'when', m.get('segments'))
            if is_w and m is not None
            else None
        )
        self._mutated_then = (
            _apply_mutation(dict(vc[m['case']].get('then') or {}), contract_id, m['case'], m['path'], m['after'], 'then', m.get('segments'))
            if m is not None and m.get('contract') == contract_id and not is_w
            else None
        )

    def _require_tagged(self, c: str) -> None:
        if c not in self.reads:
            raise ValueError(f'test "{self.test_id}" is not tagged with case "{c}"')

    def _when_table(self, c: str) -> dict[str, Any]:
        if self._mutated_when is not None and self.mutation_override is not None and self.mutation_override['case'] == c:
            return self._mutated_when
        return self.view['cases'][c].get('when') or {}

    def _then_table(self, c: str) -> dict[str, Any]:
        if self._mutated_then is not None and self.mutation_override is not None and self.mutation_override['case'] == c:
            return self._mutated_then
        return self.view['cases'][c].get('then') or {}

    def when(self, c: str, k: str) -> Any:
        self._require_tagged(c)
        w = self._when_table(c)
        if k not in w:
            raise KeyError(f'case "{c}" has no when.{k}')
        return w[k]

    def find_when(self, c: str, k: str, fb: Any = None) -> Any:
        self._require_tagged(c)
        w = self._when_table(c)
        return w[k] if k in w else fb

    def when_table(self, c: str) -> dict[str, Any]:
        self._require_tagged(c)
        return dict(_checks.clone_json(self._when_table(c)))

    def for_each_case(self, fn: Callable[[str, dict[str, Any]], Any]) -> None:
        for c in self.cases:
            fn(c, self.when_table(c))

    def expect(self, c: str, k: str) -> Any:
        self._require_tagged(c)
        t = self._then_table(c)
        if k not in t:
            raise KeyError(f'case "{c}" has no then.{k}')
        self.reads[c].add(k)
        return t[k]

    def find_then(self, c: str, k: str, fb: Any = None) -> Any:
        self._require_tagged(c)
        t = self._then_table(c)
        if k in t:
            self.reads[c].add(k)
            return t[k]
        return fb

    def then(self, c: str) -> ThenView:
        self._require_tagged(c)
        return ThenView(self._then_table(c), self.reads[c])

    def record_input(self, fp: str | Path, pre: bytes | None = None) -> str:
        cwd = Path(os.path.normpath(os.getcwd()))
        abs_p = Path(os.path.normpath(cwd / fp))
        try:
            rel = abs_p.relative_to(cwd).as_posix()
        except ValueError:
            rel = Path(fp).as_posix()
        dig = _input_digest(abs_p, pre)
        if self.mutation_override is None:
            self._input_files[abs_p] = (rel, dig)
            out = _resolve_events_file()
            if out:
                _record_discovery(self.test_id, out)
                inv = _INVS.get(out)
                if inv is not None:
                    h = self.test_id.find('#')
                    canon = f"{self.test_id[:h]}#{self.test_id[h + 1:].split('[', 1)[0]}" if h > 0 else self.test_id
                    fm = inv['inputs'].setdefault(canon, {})
                    if fm.get(rel) != dig:
                        fm[rel] = dig
                        inv['dirty'] = True
        return dig

    def read_fixture(self, fp: str | Path, encoding: str = 'utf-8') -> str:
        raw = Path(os.path.normpath(Path(os.getcwd()) / fp)).read_bytes()
        self.record_input(fp, raw)
        return _strip_bom(raw.decode(encoding))

    def check(self, case_id: str, checks: Mapping[str, Callable[[Any], Any]]) -> None:
        self._require_tagged(case_id)
        _checks.run_simple_checks(self.contract_id, case_id, self._then_table(case_id), self.reads[case_id], checks)

    def check_bounds(self, case_id: str, domain: Any, checks: Mapping[str, Callable[[Any, Any], Any]]) -> None:
        self._require_tagged(case_id)
        _checks.run_domain_bounds_check(self.contract_id, case_id, self._then_table(case_id), self.reads[case_id], domain, checks, self.mutation_override is not None)

    def _dom_spec(self, p: str | list[str] | tuple[str, ...]) -> Any:
        return _checks.resolve_param_spec(self.contract_id, self.view, p)

    def profile_domain(self, p: str | list[str] | tuple[str, ...]) -> list[Any]:
        return expand_domain(self._dom_spec(p), self.mutation_override is not None)

    def check_profile_bounds(self, case_id: str, p: str | list[str] | tuple[str, ...], checks: Mapping[str, Callable[[Any, Any], Any]]) -> None:
        self.check_bounds(case_id, self._dom_spec(p), checks)

    def _proj_map(self, side: str) -> dict[str, str]:
        return _checks.extract_projection_map(self.view, side)

    def build_input(self, case_id: str, base: Mapping[str, Any] | None = None) -> Any:
        self._require_tagged(case_id)
        return _checks.build_projected_input(self.view, self._when_table(case_id), base)

    def build_output(self, case_id: str, base: Mapping[str, Any] | None = None) -> Any:
        self._require_tagged(case_id)
        return _checks.build_projected_output(self.view, case_id, base, self._then_table(case_id))

    def check_projection(self, case_id: str, payload: Any, checks: Mapping[str, Callable[[Any], Any]] | None = None) -> None:
        self._require_tagged(case_id)
        seen = self.reads[case_id]
        proj = self._proj_map('then')
        for k, exp in self._then_table(case_id).items():
            if isinstance(checks, Mapping) and callable(checks.get(k)):
                _checks.invoke_verified_callback(checks[k], self.contract_id, case_id, k, exp)
            else:
                _checks.check_projected_leaf(self.contract_id, case_id, k, exp, payload, proj, self.mutation_override, True, 'no check or projection for')
            seen.add(k)

    def check_view(self, case_id: str, view: Any, checks: Mapping[str, Callable[[Any], Any]] | None = None) -> None:
        self._require_tagged(case_id)
        _checks.check_view_table(self.contract_id, case_id, self._then_table(case_id), self.reads[case_id], view, checks, self.mutation_override, _METRICS, lambda: self._proj_map('then'))

    def fully_read_cases(self) -> list[str]:
        return [c for c in self.cases if (n := len(self.view['cases'][c].get('then') or {})) > 0 and len(self.reads[c]) >= n]


def select_files(sel: Any = None, root_dir: str | Path | None = None) -> list[str]:
    raw_sel = os.environ.get('DRIFT_SELECT', '').strip() if sel is None else sel
    raw = _read_json(Path(raw_sel)) if isinstance(raw_sel, (str, Path)) and str(raw_sel) and Path(raw_sel).is_file() else raw_sel
    return _checks.resolve_selected_files(raw, Path(root_dir or Path.cwd()).resolve())


def reset_drift_cache() -> None:
    global _env_cache, _sel_cache, _fc_cache, _mut_cache, _ev_dir_cache, _shard_path, _mut_shard_path
    flush_all_inventories()
    _checks.clear_upstream_cache()
    for cache_coll in (_VIEWS, _TOML_DIRS, _WARMED, _BATCH, _METRICS, _DIGESTS, _DISC_CLASSES, _DISC_TESTS):
        cache_coll.clear()
    _MUT_VAR.set(())
    _env_cache = _sel_cache = _fc_cache = _mut_cache = _ev_dir_cache = _shard_path = _mut_shard_path = None


def run_drift_case(contract: str, test: str, cases: list[str] | tuple[str, ...], fn: Callable[[DriftContext], Any], level: str = 'unit') -> str:
    if not should_run(contract, test, cases):
        return 'skipped-by-select'
    if sys.flags.optimize > 0:
        _write_event({'test': test, 'contract': contract, 'cases': list(cases), 'level': level, 'outcome': 'failed', 'read': []})
        raise AssertionError('DRIFT proof runs require Python assertions to be enabled (do not run with -O or PYTHONOPTIMIZE)')
    try:
        ctx = DriftContext(contract, test, cases, level)
    except Exception:
        _write_event({'test': test, 'contract': contract, 'cases': list(cases), 'level': level, 'outcome': 'failed', 'read': []})
        raise
    version = ctx.view.get('ref') or ctx.view.get('digest') or ''
    mut_cfg = _load_mutants()
    start = time.perf_counter()
    passed = False
    control_err: BaseException | None = None
    tok = _CTX_VAR.set(ctx)
    try:
        fn(ctx)
        for abs_p, (rel, dig) in ctx._input_files.items():
            if not abs_p.is_file():
                raise AssertionError(f'{contract}: recorded input "{rel}" was mutated during test "{test}"')
            st = abs_p.stat()
            if st.st_size > 65536:
                ok = _DIGESTS.get(str(abs_p), (None, '')) == ((st.st_mtime_ns, st.st_size), dig)
            else:
                ok = _hash_bytes(abs_p.read_bytes()) == dig
            if not ok:
                raise AssertionError(f'{contract}: recorded input "{rel}" was mutated during test "{test}"')
        passed = True
    except BaseException as err:
        control_err = err
    finally:
        _CTX_VAR.reset(tok)
    ev: dict[str, Any] = {
        'test': test,
        'contract': contract,
        'cases': ctx.cases,
        'level': ctx.level,
        'outcome': 'passed' if passed else 'failed',
        'read': ctx.fully_read_cases(),
    }
    if version:
        ev['digest'] = version
    _write_event(ev)
    elapsed = max(0.001, time.perf_counter() - start)
    if mut_cfg is not None:
        targets = [m for cid in ctx.cases for m in mut_cfg['by_case'].get(f'{contract}\x00{cid}', ())]
        if targets:
            mut_out = _resolve_mutation_file(mut_cfg['out_t'])
            budget_s, mut_start, over, lines = max(0.25 * len(targets), 20.0 * len(targets) * elapsed), time.perf_counter(), False, []
            for target in targets:
                outcome = 'inconclusive'
                if not passed or over or time.perf_counter() - mut_start > budget_s:
                    over = over or passed
                else:
                    thrown: BaseException | None = None
                    failed = False
                    try:
                        with_mutation(target, lambda t=target: fn(DriftContext(contract, test, cases, level, t)))
                    except BaseException as m_err:
                        failed, thrown = True, m_err
                    if time.perf_counter() - mut_start > budget_s:
                        over = True
                    elif not failed:
                        outcome = 'survived'
                    elif isinstance(thrown, AssertionError):
                        outcome = 'killed'
                lines.append(_dump_json({'manifest': mut_cfg['manifest_id'], 'contract': target['contract'], 'digest': target['digest'], 'mutant': target['id'], 'case': target['case'], 'outcome': outcome, 'control': 'passed' if passed else 'failed'}))
            with mut_out.open('a', encoding='utf-8') as fh:
                fh.write('\n'.join(lines) + '\n')
    if not passed and control_err is not None:
        raise control_err
    return 'passed'


if __name__ == '__main__':
    sys.exit(_checks.run_drift_cli(sys.argv[1:]))


