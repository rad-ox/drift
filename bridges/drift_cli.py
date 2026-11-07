"""Auto-resolution and CLI runner for the DRIFT Python bridge."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


_PROF_MTIME_CACHE: dict[str, float] = {}


def escape_pointer(s: str) -> str: return s.replace('~', '~0').replace('/', '~1')
def unescape_pointer(s: str) -> str: return s.replace('~1', '/').replace('~0', '~') if '~' in s else s
def is_array_index(s: str) -> bool: return s == '0' or (s.isdigit() and not s.startswith('0'))
def is_finite_num(v: Any) -> bool: return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
def values_mismatch(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool): return type(a) is not type(b) or a != b
    if isinstance(a, (int, float)) or isinstance(b, (int, float)): return not (is_finite_num(a) and is_finite_num(b)) or abs(float(a) - float(b)) > 1e-9
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)): return len(a) != len(b) or any(values_mismatch(x, y) for x, y in zip(a, b))
    if isinstance(a, Mapping) and isinstance(b, Mapping): return len(a) != len(b) or any(k not in b or values_mismatch(v, b[k]) for k, v in a.items())
    return a != b


def extract_projection_map(view: Mapping[str, Any], side: str) -> dict[str, str]:
    raw = view.get('projections')
    if not isinstance(raw, Mapping):
        return {}
    out = {str(k): v for k, v in raw.items() if k not in ('when', 'then') and isinstance(v, str)}
    if isinstance(raw.get(side), Mapping):
        out.update({str(k): v for k, v in raw[side].items() if isinstance(v, str)})
    return out


def resolve_param_spec(contract_id: str, view: Mapping[str, Any], p: str | list[str] | tuple[str, ...]) -> Any:
    specs = view.get('param_specs')
    if not isinstance(specs, Mapping) or not specs:
        raise KeyError(f'contract "{contract_id}" has no param_specs')
    if isinstance(p, (list, tuple)):
        if not p:
            raise ValueError('profile parameter sequence must not be empty')
        for k in p:
            if not isinstance(k, str) or k not in specs:
                raise KeyError(f'contract "{contract_id}" has no bounded param_specs.{k}')
        return {k: specs[k] for k in p}
    if not isinstance(p, str) or p not in specs:
        raise KeyError(f'contract "{contract_id}" has no bounded param_specs.{p}')
    return specs[p]


def parse_mutation_segments(contract_id: str, case_id: str, ptr: str, sec: str) -> list[str]:
    pfx = f'/cases/{escape_pointer(case_id)}/{sec}/'
    if not ptr.startswith(pfx):
        raise ValueError(f'mutation path {ptr} is outside {contract_id}.{case_id}.{sec}')
    raw = ptr[len(pfx):].split('/')
    if not raw or not raw[0]:
        raise ValueError(f'mutation path {ptr} has no {sec} leaf')
    return [unescape_pointer(s) for s in raw]


def apply_mutation(tbl: dict[str, Any], contract_id: str, case_id: str, ptr: str, after: Any, sec: str = 'then', pre: list[str] | None = None) -> dict[str, Any]:
    segs = pre if pre is not None else parse_mutation_segments(contract_id, case_id, ptr, sec)
    def replace(t: dict[str, Any], idx: int) -> dict[str, Any]:
        k = segs[idx]
        if not isinstance(t, dict) or k not in t:
            raise ValueError(f'mutation path has no predicate {k}')
        if idx == len(segs) - 1:
            return {**t, k: after}
        if idx == 0 and len(segs) == 2 and isinstance(after, dict) and segs[1] in t and k in after and segs[1] in after:
            return {**t, k: after[k], segs[1]: after[segs[1]]}
        if not isinstance(t[k], dict):
            raise ValueError(f'mutation path crosses a non-table value at {k}')
        return {**t, k: replace(t[k], idx + 1)}
    return replace(tbl, 0)


def resolve_selected_files(raw: Any, root: Any) -> list[str]:
    if not isinstance(raw, Mapping) or raw.get('all'):
        return []
    if isinstance(raw.get('test_files'), list):
        return list(raw['test_files'])
    out, dir_cache, miss = set(), {}, set()
    def entry_type(cur: Any, name: str) -> int:
        if (m := dir_cache.get(cur)) is None:
            m = {p.name: (2 if p.is_dir() else (1 if p.is_file() else 0)) for p in cur.iterdir()} if cur.is_dir() else {}
            dir_cache[cur] = m
        return m.get(name, 0)

    def find_rel(cur: Any, rel: str, rem: str) -> str:
        mk = (cur, rem)
        if mk in miss:
            return ''
        if '/' not in rem:
            if entry_type(cur, rem) == 1:
                return f'{rel}/{rem}' if rel else rem
        elif (cur / rem).is_file():
            return f'{rel}/{rem}' if rel else rem
        pos = 0
        while pos < len(rem):
            dot = rem.find('.', pos)
            if dot <= 0:
                break
            seg = rem[:dot]
            if entry_type(cur, seg) == 2:
                res = find_rel(cur / seg, f'{rel}/{seg}' if rel else seg, rem[dot + 1:])
                if res:
                    return res
            pos = dot + 1
        miss.add(mk)
        return ''

    for tid in raw.get('tests') or ():
        cls = tid.split('#', 1)[0].replace('\\', '/') if isinstance(tid, str) else ''
        if cls and (hit := find_rel(root, '', cls)):
            out.add(hit)
    return sorted(out)


def parse_selection_doc(raw: Any) -> dict[str, Any]:
    by_c: dict[str, set[str]] = {}
    tagged: set[str] = set()
    items = raw['contracts'] if isinstance(raw.get('contracts'), list) else ([raw] if isinstance(raw.get('contract'), str) else [])
    for c in items:
        cid = c.get('contract', '')
        rep = c.get('replayed_cases') or ()
        if c.get('code_hit') is True or (c.get('resource_hit') is True and not rep):
            tagged.add(cid)
        by_c[cid] = {ch['case'] for ch in c.get('cases') or () if ch.get('change') != 'removed'} | set(rep)
    return {'all': bool(raw.get('all')), 'tests': set(raw.get('tests') or ()), 'by_c': by_c, 'tagged': tagged}


def parse_mutation_manifest_doc(mf: str, out_t: str, manifest_id: str, manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, Mapping) or manifest.get('version') != 1 or not isinstance(manifest.get('contracts'), list):
        raise ValueError(f'invalid mutation manifest {mf}')
    by_case: dict[str, list[dict[str, Any]]] = {}
    for c in manifest['contracts']:
        cid, cdig = c['id'], c['digest']
        for m in c.get('mutants') or ():
            is_w = isinstance(m.get('path'), str) and m['path'].startswith(f"/cases/{escape_pointer(m['case'])}/when/")
            by_case.setdefault(f"{cid}\x00{m['case']}", []).append({
                'id': m['id'], 'contract': cid, 'digest': cdig, 'case': m['case'],
                'path': m['path'], 'after': m['after'], 'is_when': is_w,
                'segments': parse_mutation_segments(cid, m['case'], m['path'], 'when' if is_w else 'then'),
            })
    return {'file': mf, 'out_t': out_t, 'manifest_id': manifest_id, 'by_case': by_case}


def _max_source_mtime(cur: Path, tf: Path, warmed: set[str]) -> float:
    m = tf.stat().st_mtime if tf.is_file() else 0.0
    p_dir = cur / '.drift' / 'profiles'
    pk = str(p_dir)
    if not warmed:
        _PROF_MTIME_CACHE.clear()
    prof_max = _PROF_MTIME_CACHE.get(pk)
    if prof_max is None:
        prof_max = max((pf.stat().st_mtime for pf in p_dir.glob('*.toml') if pf.is_file()), default=0.0) if p_dir.is_dir() else 0.0
        _PROF_MTIME_CACHE[pk] = prof_max
    return prof_max if prof_max > m else m


def auto_resolve_contract(contract_id: str, batch: dict[str, dict[str, Any]], toml_dirs: dict[str, dict[str, Path]], warmed: set[str], cli_state: list[str], read_json: Callable[[Path], Any], strip_bom: Callable[[str], str], find_upstream_fn: Callable[[str], tuple[dict[str, Any], Path] | None], target_json: Path | None = None) -> dict[str, Any] | None:
    if target_json is None and contract_id in batch:
        return batch[contract_id]
    cur = target_json.parent if target_json is not None else Path.cwd().resolve()
    home = os.environ.get('HOME') or os.environ.get('USERPROFILE') or ''
    linux_cli = str(Path(home) / '.local' / 'bin' / 'drift') if home else ''
    app_data = os.environ.get('LOCALAPPDATA') or (str(Path(home) / 'AppData' / 'Local') if home else '')
    win_cli = str(Path(app_data) / 'Programs' / 'drift' / 'bin' / 'drift.exe') if app_data else ''
    rels = (Path('.drift') / 'resolved' / f'{contract_id}.json', Path('.drift') / 'views' / f'{contract_id}.json', Path('.drift-work') / 'resolved' / f'{contract_id}.json', Path('target') / 'drift' / f'resolved/{contract_id}.json')
    while True:
        rc = (target_json if target_json.is_file() else None) if target_json is not None else next((cur / rel for rel in rels if (cur / rel).is_file()), None)
        c_dir = cur / '.drift' / 'contracts'
        tf: Path | None = None
        if c_dir.is_dir():
            direct = c_dir / f'{contract_id}.toml'
            if direct.is_file():
                tf = direct
            else:
                dk = str(c_dir)
                if dk not in toml_dirs:
                    toml_dirs[dk] = {p.stem: p for p in sorted(c_dir.rglob('*.toml')) if p.is_file()}
                cand_t = toml_dirs[dk].get(contract_id)
                if cand_t is not None and cand_t.is_file():
                    tf = cand_t
        if target_json is not None and tf is None:
            if (cur / '.drift').exists() or (cur / '.git').exists() or cur.parent == cur:
                return None
            cur = cur.parent
            continue
        src_mtime = _max_source_mtime(cur, tf, warmed) if tf is not None else 0.0
        is_views_dir = target_json is not None and bool(re.search(r'[/\\]\.drift[/\\](?:views|resolved)[/\\][^/\\]+\.json$', str(target_json)))
        if rc is not None and (tf is None or (rc.stat().st_mtime >= src_mtime if (target_json is not None and not is_views_dir) else rc.stat().st_mtime > src_mtime)):
            return read_json(rc)
        if tf is not None:
            env_cli = os.environ.get('DRIFT_CLI', '').strip()
            ck, b_cli = f'{env_cli}\x00{cur}', cur / '.build' / 'drift'
            clis = [c for c in (cli_state[1] if cli_state[0] == ck else '', env_cli, str(b_cli) if b_cli.is_file() else '', 'drift', linux_cli if linux_cli and Path(linux_cli).is_file() else '', win_cli if win_cli and Path(win_cli).is_file() else '') if c]
            dir_str, warm = str(c_dir), target_json is None and str(c_dir) in warmed
            if target_json is None:
                warmed.add(dir_str)
            for cli in dict.fromkeys(clis):
                if warm:
                    tmp = tempfile.mkdtemp(prefix='drift-resolved-')
                    try:
                        subprocess.run([cli, 'show', dir_str, '--out', tmp], cwd=str(cur), capture_output=True, text=True, check=False)
                        for pj in Path(tmp).glob('*.json'):
                            try:
                                batch[pj.stem] = read_json(pj)
                            except Exception:
                                pass
                        if contract_id in batch:
                            cli_state[0], cli_state[1] = (ck, cli)
                            return batch[contract_id]
                    except Exception:
                        pass
                    finally:
                        shutil.rmtree(tmp, ignore_errors=True)
                try:
                    proc = subprocess.run([cli, 'show', str(tf), '--as', 'json'], cwd=str(cur), capture_output=True, text=True, check=True)
                    cli_state[0], cli_state[1] = (ck, cli)
                    parsed = json.loads(strip_bom(proc.stdout))
                    r_dir, v_dir, w_dir = cur / '.drift' / 'resolved', cur / '.drift' / 'views', cur / '.drift-work' / 'resolved'
                    if target_json is None and rc is None and not r_dir.is_dir() and not v_dir.is_dir() and not w_dir.is_dir():
                        w_dir.mkdir(parents=True, exist_ok=True)
                    tgt = target_json or rc or (r_dir / f'{contract_id}.json' if r_dir.is_dir() else (v_dir / f'{contract_id}.json' if v_dir.is_dir() else (w_dir / f'{contract_id}.json' if w_dir.is_dir() else None)))
                    if tgt is not None:
                        tgt.parent.mkdir(parents=True, exist_ok=True)
                        tgt.write_text(proc.stdout, encoding='utf-8')
                    return parsed
                except Exception:
                    continue
        if rc is not None:
            return read_json(rc)
        if target_json is not None and ((cur / '.drift').exists() or (cur / '.git').exists()):
            return None
        if cur.parent == cur:
            break
        cur = cur.parent
    if target_json is not None:
        return None
    up = find_upstream_fn(contract_id)
    return up[0] if up is not None else None


def _capture_worktree_snapshot(area: Path) -> str:
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


def run_drift_cli_runner(argv: list[str], resolve_selected_files: Callable[[Any, Any], list[str]]) -> int:
    mode, json_out, all_gate, force_mut, mut_when, mut_budget, base_ref, want_changed = 'gate', False, False, False, False, '', '', False
    changed_paths, targets, i = [], [], 0
    while i < len(argv):
        a = argv[i]
        if i == 0 and a in ('test', 'prove', 'gate'):
            mode = a
        elif a in ('--test', '--prove', '--gate'):
            mode = a[2:]
        elif a == '--all-gate':
            all_gate = True
        elif a == '--mutants':
            force_mut = True
        elif a == '--when':
            mut_when = force_mut = True
        elif a == '--budget' and i + 1 < len(argv):
            i += 1
            mut_budget, force_mut = argv[i], True
        elif a == '--json':
            json_out = True
        elif a == '--base' and i + 1 < len(argv):
            i += 1
            base_ref = argv[i]
        elif a == '--changed':
            want_changed = True
            if i + 1 < len(argv) and not argv[i + 1].startswith('-'):
                i += 1
                changed_paths.append(argv[i])
        elif a and not a.startswith('-'):
            targets.append(a)
        i += 1
    area = Path.cwd().resolve()
    while not (area / '.drift' / 'contracts').is_dir() and area.parent != area:
        area = area.parent
    c_dir = area / '.drift' / 'contracts'
    if not c_dir.is_dir():
        raise FileNotFoundError(f'no .drift/contracts found from {Path.cwd()}')
    if not targets:
        targets = [p.stem for p in sorted(c_dir.glob('*.toml'))]
    if not targets:
        raise ValueError('usage: python3 drift.py [test|prove|gate] [<contract...>] [--base <ref>] [--changed [<file>]] [--prove|--gate] [--json]')
    home = os.environ.get('HOME') or os.environ.get('USERPROFILE') or ''
    cli = ''
    for cand in (os.environ.get('DRIFT_CLI', '').strip(), str(area / '.build' / 'drift'), 'drift', str(Path(home) / '.local' / 'bin' / 'drift') if home else ''):
        if cand:
            try:
                subprocess.run([cand, 'version'], cwd=str(area), capture_output=True, check=True)
                cli = cand
                break
            except Exception:
                pass
    if not cli:
        raise FileNotFoundError('drift CLI not found on PATH or DRIFT_CLI')
    if want_changed and not base_ref:
        base_ref = 'HEAD'
    if want_changed and not changed_paths:
        try:
            seen_changed: set[str] = set()
            d_proc = subprocess.run(['git', '-C', str(area), 'diff', '--name-only', '--relative', base_ref], capture_output=True, text=True, check=False)
            u_proc = subprocess.run(['git', '-C', str(area), 'ls-files', '--others', '--exclude-standard'], capture_output=True, text=True, check=False)
            for ln in f'{d_proc.stdout}\n{u_proc.stdout}'.splitlines():
                p = ln.strip()
                if p and not p.startswith('.drift-work/') and p not in seen_changed:
                    seen_changed.add(p)
                    changed_paths.append(p)
        except Exception:
            pass
    res_dir, ev_dir = area / '.drift-work' / 'resolved', area / '.drift-work' / 'events'
    res_dir.mkdir(parents=True, exist_ok=True)
    ev_dir.mkdir(parents=True, exist_ok=True)
    ids, tomls, rel_srcs = [], [], []
    id_set, toml_set = set(), set()
    for t in targets:
        cid = Path(t).stem if t.endswith('.toml') else t
        direct = (area / t).resolve() if t.endswith('.toml') and (area / t).is_file() else (c_dir / f'{cid}.toml')
        if not direct.is_file():
            cand_src = (area / t).resolve() if (area / t).is_file() else (Path(t).resolve() if Path(t).is_file() else None)
            if cand_src is not None and not str(cand_src).endswith('.toml'):
                rel_src = cand_src.relative_to(area).as_posix()
                if rel_src not in changed_paths:
                    changed_paths.append(rel_src)
                rel_srcs.append((t, direct, rel_src))
                continue
            raise FileNotFoundError(f'contract "{t}" not found at {direct}')
        if cid not in id_set:
            id_set.add(cid)
            ids.append(cid)
        s_dir = str(direct)
        if s_dir not in toml_set:
            toml_set.add(s_dir)
            tomls.append(s_dir)
    if rel_srcs:
        imp_p = subprocess.run([cli, 'impact', *[x[2] for x in rel_srcs], '--json'], cwd=str(area), capture_output=True, text=True, check=False)
        imp_obj = json.loads(imp_p.stdout) if imp_p.returncode == 0 and imp_p.stdout.strip() else {}
        unm = set(imp_obj.get('unmatched_code') or ())
        for raw_t, direct_t, r_src in rel_srcs:
            if r_src in unm:
                raise FileNotFoundError(f'contract "{raw_t}" not found at {direct_t}')
        for mc in imp_obj.get('contracts') or ():
            m_id = mc.get('id') if isinstance(mc, Mapping) else ''
            m_direct = c_dir / f'{m_id}.toml'
            if m_id and m_direct.is_file():
                if m_id not in id_set:
                    id_set.add(m_id)
                    ids.append(m_id)
                if str(m_direct) not in toml_set:
                    toml_set.add(str(m_direct))
                    tomls.append(str(m_direct))
        if not ids:
            raise FileNotFoundError(f'contract "{rel_srcs[0][0]}" not found at {rel_srcs[0][1]}')
    subprocess.run([cli, 'show', *tomls, '--out', str(res_dir)], cwd=str(area), capture_output=True, check=False)
    sel_file, narrowed_files, select_widened, select_reasons = '', None, False, []
    if base_ref:
        sel_cmd = [cli, 'select', tomls[0] if len(tomls) == 1 else str(c_dir), '--base', base_ref, '--events', str(ev_dir), '--files', '--json', *([x for cp in changed_paths for x in ('--changed', cp)] if changed_paths else (['--changed'] if want_changed else []))]
        sel_proc = subprocess.run(sel_cmd, cwd=str(area), capture_output=True, text=True, check=False)
        if sel_proc.returncode not in (0, 1):
            raise RuntimeError((sel_proc.stderr or '').strip() or f'drift select failed with status {sel_proc.returncode}')
        try:
            sel_obj = json.loads(sel_proc.stdout.lstrip('\ufeff')) if sel_proc.stdout.strip() else None
        except Exception:
            sel_obj = None
        if not isinstance(sel_obj, Mapping):
            raise RuntimeError((sel_proc.stderr or '').strip() or 'drift select returned invalid JSON')
        sf_p = area / '.drift-work' / 'select.json'
        sf_p.write_text(sel_proc.stdout, encoding='utf-8')
        sel_file = str(sf_p)
        if sel_obj.get('all') is False and isinstance(sel_obj.get('test_files'), list):
            narrowed_files = [str(x) for x in sel_obj['test_files']]
        else:
            select_widened = True
            select_reasons = [str(r) for r in (sel_obj.get('reasons') or ()) if r is not None]
            if not json_out:
                sys.stderr.write(f"drift: select widened to all tests ({', '.join(select_reasons) or 'all'})\n")
    if narrowed_files is not None:
        test_files = set(narrowed_files)
        missing = []
    else:
        found: dict[str, set[str]] = {cid: set() for cid in ids}
        for d in (ev_dir, area / '.drift' / 'events'):
            if d.is_dir():
                for jf in sorted(d.glob('*.jsonl')):
                    for line in jf.read_text(encoding='utf-8').splitlines():
                        if line.strip():
                            try:
                                ev = json.loads(line)
                                if ev.get('contract') in found and isinstance(ev.get('test'), str):
                                    found[ev['contract']].update(resolve_selected_files({'all': False, 'tests': [ev['test']]}, area))
                            except Exception:
                                pass
        test_files = {tf for cid in ids for tf in found[cid]}
        missing = [cid for cid in ids if not found[cid]]
    if missing:
        g_parts: list[str] = []
        for cid in list(missing):
            vf = res_dir / f'{cid}.json'
            if vf.is_file():
                for g in (json.loads(vf.read_text(encoding='utf-8')).get('scope') or {}).get('code') or ():
                    cl = str(g).split('#', 1)[0].replace('\\', '/').rstrip('/')
                    if cl and not cl.startswith('..'):
                        if '*' not in cl and (cl.endswith('_test.py') or Path(cl).name.startswith('test_')) and (area / cl).is_file():
                            test_files.add(cl)
                            if cid in missing:
                                missing.remove(cid)
                        else:
                            g_parts.append(re.escape(cl).replace(r'\*\*', '\x00').replace(r'\*', '[^/]*').replace('\x00', '.*'))
        if missing:
            g_rx = re.compile('^(?:' + '|'.join(g_parts) + r')(?:$|/)') if g_parts else None
            id_rx = re.compile('[\'"](?:' + '|'.join(re.escape(c) for c in missing) + ')[\'"]')
            skip = {'.git', '.drift', '.drift-work', '__pycache__', '.venv', 'target', '.build'}
            for p in sorted(area.rglob('*.py')):
                if not any(part in skip for part in p.parts) and (p.name.startswith('test_') or p.name.endswith('_test.py')):
                    rel = p.relative_to(area).as_posix()
                    if (g_rx is not None and g_rx.match(rel)) or id_rx.search(p.read_text(encoding='utf-8', errors='ignore')):
                        test_files.add(rel)
    cfg_p = area / '.drift' / 'config.toml'
    need_mut = force_mut or (cfg_p.is_file() and 'proof = "killed"' in cfg_p.read_text(encoding='utf-8'))
    mut_f, mut_ev = area / '.drift-work' / 'mutants.json', area / '.drift-work' / 'mut-events'
    if need_mut:
        shutil.rmtree(mut_ev, ignore_errors=True)
        mut_ev.mkdir(parents=True, exist_ok=True)
        m_cmd = (
            [cli, 'mutants', *tomls]
            + (['--base', base_ref] if base_ref else [])
            + ([x for cp in changed_paths for x in ('--changed', cp)] if changed_paths else (['--changed'] if want_changed else []))
            + (['--when'] if mut_when else [])
            + (['--budget', mut_budget, '--events', str(ev_dir)] if mut_budget else [])
            + ['--out', str(mut_f)]
        )
        subprocess.run(m_cmd, cwd=str(area), capture_output=True, check=False)
    env = {**os.environ, 'DRIFT_RESOLVED': str(res_dir), 'DRIFT_EVENTS': str(ev_dir), 'DRIFT_CONTRACTS': ','.join(ids)}
    if not env.get('DRIFT_SNAPSHOT', '').strip() and test_files:
        snap = _capture_worktree_snapshot(area)
        if snap:
            env['DRIFT_SNAPSHOT'] = snap
    if env.get('DRIFT_PACK_REF', '').strip() and not env.get('DRIFT_TOUCHED', '').strip() and test_files:
        try:
            df_p = subprocess.run(['git', '-C', str(area), 'diff', '--name-only', '--relative', 'HEAD'], capture_output=True, text=True, check=False)
            if df_p.returncode == 0 and df_p.stdout.strip():
                t_list = [ln.strip() for ln in df_p.stdout.splitlines() if ln.strip() and not ln.strip().startswith(('.drift/', '.drift-work/'))]
                if t_list:
                    env['DRIFT_TOUCHED'] = ','.join(t_list)
        except Exception:
            pass
    if sel_file:
        env['DRIFT_SELECT'] = sel_file
    if need_mut and mut_f.is_file():
        env['DRIFT_MUTANTS'], env['DRIFT_MUTATION_EVENTS'] = str(mut_f), str(mut_ev)
    test_rc, run_list = 0, sorted(test_files)
    custom_cmd = os.environ.get('DRIFT_TEST_CMD', '').strip()
    if custom_cmd and run_list:
        cmd_parts = custom_cmd.split()
        rc = subprocess.run([*cmd_parts, *(str(area / tf) for tf in run_list)], cwd=str(area), env=env, capture_output=json_out, check=False).returncode
        if rc != 0:
            test_rc = rc
    else:
        for tf in run_list:
            rc = subprocess.run([sys.executable, str(area / tf)], cwd=str(area), env=env, capture_output=json_out, check=False).returncode
            if rc != 0:
                test_rc = rc
    if mode == 'test':
        if json_out:
            test_rep: dict[str, Any] = {'ok': test_rc == 0, 'ran': len(run_list), 'selected_files': run_list}
            if base_ref:
                test_rep['widened'] = select_widened
                test_rep['reasons'] = select_reasons
            sys.stdout.write(json.dumps(test_rep) + '\n')
        elif not run_list:
            sys.stdout.write('drift test: 0 test file(s) selected\n')
        return test_rc
    base_args = (['--base', base_ref] + ([x for cp in changed_paths for x in ('--changed', cp)] if changed_paths else ['--changed-none'])) if base_ref else []
    mut_args = ['--mutants', str(mut_f), '--mutation-events', str(mut_ev)] if need_mut and mut_f.is_file() else []
    gate_targets = [str(c_dir)] if all_gate else tomls
    cmd = [cli, mode, *gate_targets, '--events', str(ev_dir), *base_args, *mut_args] + (['--json'] if json_out else [])
    return subprocess.run(cmd, cwd=str(area), check=False).returncode

