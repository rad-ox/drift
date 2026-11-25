// Single-command CLI runner and test-file selection for the DRIFT JavaScript bridge.

import { ensureExportGeneration, runPrecheckTestLiterals, validateShadowStateDir } from './drift_ui_collector.mjs';
import { tightenThenMapBySumResiduals } from './drift_ui_surface.mjs';
export { tightenThenMapBySumResiduals };

const throwError = (message) => {
  throw new Error(message);
};

const isStr = (v) => typeof v === 'string';
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const rd = (fs, p) => fs.readFileSync(p, 'utf8');
const gitOut = (ex, dir, args, env) => ex('git', ['-C', dir, ...args], { ...(env ? { env } : {}), encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });

export function normalizeBytes(buf) {
 let crlf = false;
 for (let i = 0; i < buf.length; i += 1) {
  if (buf[i] === 0) return buf;
  if (buf[i] === 13 && buf[i + 1] === 10) crlf = true;
 }
 if (!crlf) return buf;
 const out = Buffer.allocUnsafe(buf.length);
 let pos = 0;
 for (let i = 0; i < buf.length; i += 1) {
  if (buf[i] === 13 && buf[i + 1] === 10) { out[pos++] = 10; i += 1; } else out[pos++] = buf[i];
 }
 return out.subarray(0, pos);
}

export function resolveSelectedFiles(raw, rootDir, fs, path) {
  if (!isObj(raw) || raw.all) return [];
  if (Array.isArray(raw.test_files)) return [...raw.test_files];
  const out = new Set(), dirCache = new Map(), miss = new Set();
  const entryType = (dir, name) => {
    let map = dirCache.get(dir);
    if (!map) {
      map = new Map();
      try {
        for (const d of fs.readdirSync(dir, { withFileTypes: true })) map.set(d.name, d.isDirectory() ? 2 : (d.isFile() ? 1 : 0));
      } catch {}
      dirCache.set(dir, map);
    }
    return map.get(name) || 0;
  };
  const findRel = (cur, rel, rem) => {
    const mk = `${cur}\u0000${rem}`;
    if (miss.has(mk)) return '';
    if (!rem.includes('/')) {
      if (entryType(cur, rem) === 1) return rel ? `${rel}/${rem}` : rem;
    } else if (fs.existsSync(path.join(cur, rem)) && fs.statSync(path.join(cur, rem)).isFile()) return rel ? `${rel}/${rem}` : rem;
    for (let pos = 0, dot = rem.indexOf('.', 0); dot > 0; pos = dot + 1, dot = rem.indexOf('.', pos)) {
      const seg = rem.slice(0, dot), res = entryType(cur, seg) === 2 ? findRel(path.join(cur, seg), rel ? `${rel}/${seg}` : seg, rem.slice(dot + 1)) : '';
      if (res) return res;
    }
    miss.add(mk);
    return '';
  };
  for (const tid of Array.isArray(raw.tests) ? raw.tests : []) {
    const cls = isStr(tid) ? tid.split('#', 1)[0].split('\\').join('/') : '', hit = cls ? findRel(rootDir, '', cls) : '';
    if (hit) out.add(hit);
  }
  return [...out].sort();
}

export function mergePriorInventory(out, inv, isShard, fs, path, rootDir, env = null) {
  if (!inv.mc) inv.mc = new Set();
  if (isShard && inv.classes.size > 0 && [...inv.classes].every((c) => inv.mc.has(c))) return;
  const self = `${out.slice(0, -6)}.meta.json`, dir = path.dirname(out);
  const files = isShard ? (fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => f.endsWith('.meta.json')).sort().reverse().map((f) => path.join(dir, f)).filter((p) => p !== self) : []) : (fs.existsSync(self) ? [self] : []);
  if (!files.length) return;
  const pend = isShard ? new Set([...inv.classes].filter((c) => !inv.mc.has(c))) : null, cm = new Map();
  const snap = (env?.DRIFT_SNAPSHOT || '').trim(), eref = (env?.DRIFT_EXECUTION_REF || '').trim();
  const clsMt = (c) => {
    if (!cm.has(c)) {
      const f = resolveSelectedFiles({ all: false, tests: [`${c}#_`] }, rootDir, fs, path)[0];
      cm.set(c, f ? fs.statSync(path.join(rootDir, f), { bigint: true }).mtimeNs : -1n);
    }
    return cm.get(c);
  };
  for (const mf of files) {
    if (pend && !pend.size) break;
    try {
      const m = JSON.parse(rd(fs, mf));
      if (!isObj(m)) continue;
      if (!isShard && ((snap && isStr(m.snapshot) && m.snapshot !== snap) || (eref && isStr(m.execution_ref) && m.execution_ref !== eref))) continue;
      const mc = Array.isArray(m.classes) ? m.classes.filter(isStr) : [];
      if (pend && !mc.some((c) => pend.has(c))) continue;
      const mt = fs.statSync(mf, { bigint: true }).mtimeNs, take = new Set();
      for (const c of mc) {
        const t = clsMt(c), ok = t >= 0n && t <= mt;
        if (isShard ? (pend.has(c) && ok) : (ok || (!inv.classes.has(c) && t >= 0n))) { inv.classes.add(c); take.add(c); }
        if (pend && pend.has(c)) { pend.delete(c); inv.mc.add(c); }
      }
      for (const tid of Array.isArray(m.tests) ? m.tests : []) if (isStr(tid) && take.has(tid.split('#', 1)[0])) inv.tests.add(tid);
      if (isObj(m.inputs)) for (const [tid, fm] of Object.entries(m.inputs)) {
        if (!inv.tests.has(tid) || !isObj(fm)) continue;
        const cur = inv.inputs.get(tid) || inv.inputs.set(tid, new Map()).get(tid);
        for (const [fp, d] of Object.entries(fm)) if (!cur.has(fp) && isStr(d)) cur.set(fp, d);
      }
    } catch {}
  }
  if (pend) for (const c of pend) inv.mc.add(c);
}

export function writeSidecar(out, inv, isShard, buildFn, fs, path, rootDir, env) {
  const meta = `${out.slice(0, -6)}.meta.json`, lock = `${meta}.lock`;
  const run = () => {
    mergePriorInventory(out, inv, isShard, fs, path, rootDir, env);
    writeAtomicUtf8(fs, meta, JSON.stringify(buildFn()) + '\n', `${process.pid}.${Math.random().toString(36).slice(2, 8)}`);
  };
  if (isShard) { run(); return; }
  const sb = new Int32Array(new SharedArrayBuffer(4));
  let fd = -1;
  for (let i = 0; i < 600; i += 1) {
    try { fd = fs.openSync(lock, 'wx'); break; } catch (e) {
      if (e?.code !== 'EEXIST') throw e;
      try { if (Date.now() - fs.statSync(lock).mtimeMs > 10000) fs.unlinkSync(lock); } catch {}
      Atomics.wait(sb, 0, 0, 5);
    }
  }
  try { if (fd >= 0) fs.closeSync(fd); run(); } finally { if (fd >= 0) try { fs.unlinkSync(lock); } catch {} }
}

function captureWorktreeSnapshot(area, execFileSync, fs, path, process) {
  try {
    const isHex = (s) => /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/u.test(s);
    if (!gitOut(execFileSync, area, ['status', '--porcelain', '--untracked-files=normal']).trim()) {
      const tr = gitOut(execFileSync, area, ['rev-parse', '--verify', '--quiet', 'HEAD^{tree}']).trim();
      if (isHex(tr)) return tr;
    }
    const rev = gitOut(execFileSync, area, ['rev-parse', '--show-toplevel', '--git-dir']).trim().split(/\r?\n/u);
    if (rev.length < 2) return '';
    const top = path.resolve(area, rev[0].trim()), realIdx = path.join(path.resolve(area, rev[1].trim()), 'index'), tmpIdx = path.join(area, '.drift-work', `.git-index-${process.pid}`);
    try {
      if (fs.existsSync(realIdx)) fs.copyFileSync(realIdx, tmpIdx); else fs.rmSync(tmpIdx, { force: true });
      const env = { ...process.env, GIT_INDEX_FILE: tmpIdx };
      const ex = ['.drift-work', '.build', 'target'].filter((d) => {
        try { execFileSync('git', ['-C', top, 'check-ignore', '-q', '--', `${d}/`], { stdio: 'ignore' }); return false; } catch { return true; }
      }).map((d) => `:(exclude)${d}`);
      execFileSync('git', ['-C', top, '-c', 'core.safecrlf=false', 'add', '-A', '--', '.', ...ex], { env, stdio: 'ignore' });
      const tr = gitOut(execFileSync, top, ['write-tree'], env).trim();
      if (isHex(tr)) return tr;
    } finally { fs.rmSync(tmpIdx, { force: true }); }
  } catch {}
  return '';
}

export function parseTestCommand(raw) {
  const s = isStr(raw) ? raw.trim() : '';
  if (!s) return [];
  if (s.startsWith('[')) {
    let arr = null;
    try { arr = JSON.parse(s); } catch { throwError('invalid JSON in DRIFT_TEST_CMD'); }
    if (!Array.isArray(arr) || !arr.every(isStr)) throwError('DRIFT_TEST_CMD JSON must be an array of strings');
    return arr.filter(Boolean);
  }
  const out = [];
  let cur = '', inQ = false, q = '', hasTok = false;
  for (let i = 0; i < s.length; i += 1) {
    const ch = s[i];
    if (inQ) {
      if (ch === '\\' && q === '"' && i + 1 < s.length && (s[i + 1] === '"' || s[i + 1] === '\\')) cur += s[++i];
      else if (ch === q) inQ = false;
      else cur += ch;
    } else if (ch === "'" || ch === '"') {
      inQ = true; q = ch; hasTok = true;
    } else if (ch === '\\' && i + 1 < s.length && (s[i + 1] === '"' || s[i + 1] === "'" || /\s/u.test(s[i + 1]))) {
      cur += s[++i]; hasTok = true;
    } else if (/\s/u.test(ch)) {
      if (hasTok) { out.push(cur); cur = ''; hasTok = false; }
    } else {
      cur += ch; hasTok = true;
    }
  }
  if (inQ) throwError('unterminated quote in DRIFT_TEST_CMD');
  if (hasTok) out.push(cur);
  return out;
}

export function precheckTestLiterals(f, r, a, fs, p) { return runPrecheckTestLiterals(f, r, a, fs, p); }

export function resolveCliWorkPaths(cwd, env, fs, path) {
  const sd = validateShadowStateDir(cwd, env, fs, path);
  let area = cwd;
  if (sd) {
    const mf = path.join(sd, 'shadow.toml'), sr = fs.existsSync(mf) ? ((env.DRIFT_SOURCE_ROOT || '').trim() || (rd(fs, mf).match(/^\s*source_root\s*=\s*"([^"]*)"/mu) || [])[1] || '') : '';
    if (sr) area = fs.realpathSync(path.resolve(sd, sr));
  } else while (!fs.existsSync(path.join(area, '.drift', 'contracts')) && path.dirname(area) !== area) area = path.dirname(area);
  const stateArea = sd || area, workRoot = path.join(stateArea, '.drift-work');
  const rk = ((env.DRIFT_RUN_ID || '').trim() || (env.DRIFT_PACK_REF || '').trim()).replace(/[^A-Za-z0-9._-]+/gu, '_').replace(/^_+|_+$/gu, '');
  return { area, stateArea, workRoot, runRoot: rk ? path.join(workRoot, 'runs', rk) : workRoot, hasRunScope: Boolean(rk), isShadow: Boolean(sd && path.resolve(sd) !== path.resolve(area)) };
}

function writeAtomicUtf8(fs, p, s, pid) { const t = `${p}.tmp.${pid}`; fs.writeFileSync(t, s, 'utf8'); fs.renameSync(t, p); }

export function runDriftCli(argv, execFileSync, fs, path, process) {
  let mode = 'gate', jsonOut = false, allGate = false, forceMut = false, mutWhen = false, mutBudget = '', baseRef = '', wantChanged = false;
  const changedPaths = [], targets = [];
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (i === 0 && (a === 'test' || a === 'prove' || a === 'gate')) mode = a;
    else if (a === '--test' || a === '--prove' || a === '--gate') mode = a.slice(2);
    else if (a === '--all-gate') allGate = true;
    else if (a === '--mutants') forceMut = true;
    else if (a === '--when') { mutWhen = true; forceMut = true; }
    else if (a === '--budget' && i + 1 < argv.length) { mutBudget = argv[++i]; forceMut = true; }
    else if (a === '--json') jsonOut = true;
    else if (a === '--base' && i + 1 < argv.length) baseRef = argv[++i];
    else if (a === '--changed') {
      wantChanged = true;
      if (i + 1 < argv.length && !argv[i + 1].startsWith('-')) changedPaths.push(argv[++i]);
    } else if (a && !a.startsWith('-')) targets.push(a);
  }
  const { area, stateArea, workRoot, runRoot, hasRunScope, isShadow } = resolveCliWorkPaths(process.cwd(), process.env, fs, path);
  const sdArgs = isShadow ? ['--state-dir', stateArea] : [];
  const has = (p) => fs.existsSync(p), cDir = path.join(stateArea, '.drift', 'contracts');
  if (!has(cDir)) throwError(`no .drift/contracts found from ${process.cwd()}`);
  if (!targets.length) for (const fn of fs.readdirSync(cDir).filter((f) => f.endsWith('.toml')).sort()) targets.push(path.basename(fn, '.toml'));
  if (!targets.length) throwError('usage: node drift.mjs [test|prove|gate] [<contract...>] [--base <ref>] [--changed [<file>]] [--prove|--gate] [--json]');
  const home = process.env.HOME || process.env.USERPROFILE || '';
  const cli = [(process.env.DRIFT_CLI || '').trim(), path.join(area, '.build', 'drift'), 'drift', home ? path.join(home, '.local', 'bin', 'drift') : ''].filter(Boolean).find((c) => { try { execFileSync(c, ['version'], { cwd: area, stdio: 'ignore' }); return true; } catch { return false; } }) || throwError('drift CLI not found on PATH or DRIFT_CLI');
  if (wantChanged && !baseRef) baseRef = 'HEAD';
  if (wantChanged && !changedPaths.length) {
    try {
      const seen = new Set(), dOut = gitOut(execFileSync, area, ['diff', '--name-only', '--relative', baseRef]), uOut = gitOut(execFileSync, area, ['ls-files', '--others', '--exclude-standard']);
      for (const ln of `${dOut}\n${uOut}`.split('\n')) { const p = ln.trim(); if (p && !p.startsWith('.drift-work/') && !seen.has(p)) { seen.add(p); changedPaths.push(p); } }
    } catch {}
  }
  const resDir = path.join(runRoot, 'resolved'), evDir = path.join(runRoot, 'events');
  fs.mkdirSync(resDir, { recursive: true });
  fs.mkdirSync(evDir, { recursive: true });
  const ids = [], idSet = new Set(), tomls = [], tomlSet = new Set(), relSrcs = [];
  const addTarget = (id, direct) => { if (!idSet.has(id)) { idSet.add(id); ids.push(id); } if (!tomlSet.has(direct)) { tomlSet.add(direct); tomls.push(direct); } };
  for (const t of targets) {
    const id = path.basename(t).endsWith('.toml') ? path.basename(t, '.toml') : t;
    const direct = has(path.resolve(area, t)) && t.endsWith('.toml') ? path.resolve(area, t) : path.join(cDir, `${id}.toml`);
    if (!has(direct)) {
      const candSrc = has(path.resolve(area, t)) ? path.resolve(area, t) : (has(path.resolve(process.cwd(), t)) ? path.resolve(process.cwd(), t) : '');
      if (candSrc && !candSrc.endsWith('.toml')) {
        const relSrc = path.relative(area, candSrc).split(path.sep).join('/');
        if (!changedPaths.includes(relSrc)) changedPaths.push(relSrc);
        relSrcs.push({ raw: t, direct, relSrc });
        continue;
      }
      throwError(`contract "${t}" not found at ${direct}`);
    }
    addTarget(id, direct);
  }
  if (relSrcs.length) {
    try {
      const impObj = JSON.parse(execFileSync(cli, ['impact', ...relSrcs.map((x) => x.relSrc), '--json'], { cwd: area, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }));
      const unm = new Set(Array.isArray(impObj?.unmatched_code) ? impObj.unmatched_code : []), miss = relSrcs.find((x) => unm.has(x.relSrc));
      if (miss) throwError(`contract "${miss.raw}" not found at ${miss.direct}`);
      for (const mc of impObj?.contracts || []) { const mDirect = path.join(cDir, `${mc.id}.toml`); if (mc.id && has(mDirect)) addTarget(mc.id, mDirect); }
    } catch (e) { if (String(e?.message || '').includes('not found at')) throw e; }
    if (!ids.length) throwError(`contract "${relSrcs[0].raw}" not found at ${relSrcs[0].direct}`);
  }
  const genDir = ensureExportGeneration(stateArea, cli, ids, tomls, resDir, execFileSync, fs, path);
  const chgArgs = changedPaths.length ? changedPaths.flatMap((cp) => ['--changed', cp]) : (wantChanged ? ['--changed'] : []);
  let selFile = '', narrowedFiles = null, selectWidened = false, selectReasons = [];
  if (baseRef) {
    const baseEvArgs = hasRunScope && has(path.join(workRoot, 'events')) ? ['--events', evDir, '--events', path.join(workRoot, 'events')] : ['--events', evDir];
    const selArgs = ['select', tomls.length === 1 ? tomls[0] : cDir, ...sdArgs, '--base', baseRef, ...baseEvArgs, '--files', '--json', ...chgArgs];
    let selOut = '', selStatus = 0, selErr = '';
    try { selOut = execFileSync(cli, selArgs, { cwd: area, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }); } catch (e) {
      selStatus = typeof e?.status === 'number' ? e.status : 2;
      selOut = String(e?.stdout || '');
      selErr = String(e?.stderr || '').trim();
    }
    if (selStatus > 1) throwError(selErr || `drift select failed with status ${selStatus}`);
    let selObj = null;
    try { selObj = JSON.parse(selOut); } catch {}
    if (!isObj(selObj)) throwError(selErr || 'drift select returned invalid JSON');
    writeAtomicUtf8(fs, selFile = path.join(runRoot, 'select.json'), selOut, process.pid);
    if (selObj.all === false && Array.isArray(selObj.test_files)) narrowedFiles = selObj.test_files;
    else {
      selectWidened = true;
      selectReasons = Array.isArray(selObj.reasons) ? selObj.reasons.map(String) : [];
      if (!jsonOut) process.stderr.write(`drift: select widened to all tests (${selectReasons.join(', ') || 'all'})\n`);
    }
  }
  const testFiles = new Set(), missingIds = [];
  if (narrowedFiles !== null) {
    for (const f of narrowedFiles) testFiles.add(f);
  } else {
    const byCid = new Map(ids.map((id) => [id, new Set()]));
    for (const dir of [evDir, path.join(workRoot, 'events'), path.join(stateArea, '.drift', 'events')]) {
      if (!fs.existsSync(dir)) continue;
      for (const fn of fs.readdirSync(dir).filter((f) => f.endsWith('.jsonl')).sort()) {
        for (const line of rd(fs, path.join(dir, fn)).split('\n')) {
          if (!line.trim()) continue;
          try {
            const ev = JSON.parse(line);
            if (idSet.has(ev.contract) && isStr(ev.test)) {
              for (const tf of resolveSelectedFiles({ all: false, tests: [ev.test] }, area, fs, path)) byCid.get(ev.contract).add(tf);
            }
          } catch {}
        }
      }
    }
    for (const id of ids) {
      const set = byCid.get(id);
      if (set && set.size) for (const f of set) testFiles.add(f); else missingIds.push(id);
    }
  }
  if (narrowedFiles === null && missingIds.length) {
    const isJs = /\.(?:[mc]?[jt]s|tsx)$/u, isTf = (p) => /(?:\.(?:test|spec|e2e)|_test)\.(?:[mc]?[jt]s|tsx)$/u.test(p), isTd = (p) => /(?:^|\/)tests?\//u.test(p) && isJs.test(p), bindRx = /\brunDriftCase\b|drift\.mjs/u, escRx = (s) => s.replace(/[.+^${}()|[\]\\]/gu, '\\$&'), globParts = [];
    for (const id of [...missingIds]) {
      const vf = path.join(resDir, `${id}.json`);
      if (!fs.existsSync(vf)) continue;
      for (const g of JSON.parse(rd(fs, vf))?.scope?.code || []) {
        const clean = String(g).split('#', 1)[0].replace(/\\/gu, '/').replace(/\/+$/u, '');
        if (!clean) continue;
        const abs = path.join(area, clean);
        if (!clean.includes('*') && fs.existsSync(abs) && (isTf(clean) || (isTd(clean) && bindRx.test(rd(fs, abs))))) {
          testFiles.add(clean);
          const idx = missingIds.indexOf(id);
          if (idx >= 0) missingIds.splice(idx, 1);
        } else globParts.push(escRx(clean).replace(/\*\*/gu, '\u0000').replace(/\*/gu, '[^/]*').replace(/\u0000/gu, '.*'));
      }
    }
    if (missingIds.length) {
      const globRx = globParts.length ? new RegExp(`^(?:${globParts.join('|')})(?:$|/)`, 'u') : null;
      const idRx = new RegExp(`['"](?:${missingIds.map(escRx).join('|')})['"]`, 'u');
      const skip = new Set(['.git', '.drift', '.drift-work', 'node_modules', 'target', '.build']);
      const walk = (dir) => {
        for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
          if (skip.has(e.name)) continue;
          const full = path.join(dir, e.name);
          if (e.isDirectory() && !e.isSymbolicLink()) walk(full);
          else if (e.isFile()) {
            const rel = path.relative(area, full).split(path.sep).join('/');
            if (isTf(e.name)) {
              if ((globRx && globRx.test(rel)) || idRx.test(rd(fs, full))) testFiles.add(rel);
            } else if (isTd(rel)) {
              const src = rd(fs, full);
              if (idRx.test(src) && bindRx.test(src)) testFiles.add(rel);
            }
          }
        }
      };
      walk(area);
    }
  }
  const runFiles = [...testFiles].sort();
  let autoSnap = (process.env.DRIFT_SNAPSHOT || '').trim() || (runFiles.length ? captureWorktreeSnapshot(area, execFileSync, fs, path, process) : '');
  let autoTouched = (process.env.DRIFT_TOUCHED || '').trim();
  if (!autoTouched && (process.env.DRIFT_PACK_REF || '').trim() && runFiles.length) {
    try {
      autoTouched = gitOut(execFileSync, area, ['diff', '--name-only', '--relative', 'HEAD']).split('\n').map((s) => s.trim()).filter((s) => s && !s.startsWith('.drift/') && !s.startsWith('.drift-work/')).join(',');
    } catch {}
  }
  const cfgPath = path.join(stateArea, '.drift', 'config.toml');
  const needMut = forceMut
    || (fs.existsSync(cfgPath) && /proof\s*=\s*"killed"/u.test(rd(fs, cfgPath)))
    || ids.some((id) => { const vf = path.join(resDir, `${id}.json`); return fs.existsSync(vf) && JSON.parse(rd(fs, vf))?.requires?.proof === 'killed'; });
  const mutFile = path.join(runRoot, 'mutants.json'), mutEvDir = path.join(runRoot, 'mut-events');
  if (needMut) {
    fs.rmSync(mutEvDir, { recursive: true, force: true });
    fs.mkdirSync(mutEvDir, { recursive: true });
    const mArgs = ['mutants', ...tomls, ...sdArgs, ...(baseRef ? ['--base', baseRef] : []), ...chgArgs, ...(mutWhen ? ['--when'] : []), ...(mutBudget ? ['--budget', mutBudget, '--events', evDir] : []), '--out', mutFile];
    try { execFileSync(cli, mArgs, { cwd: area, stdio: ['ignore', 'pipe', 'pipe'] }); } catch {}
  }
  let testStatus = 0;
  if (runFiles.length) {
    const pre = runPrecheckTestLiterals(runFiles, genDir, area, fs, path);
    if (!pre.ok) throwError(pre.findings.map((f) => `${f.file}: ${f.code}: ${f.message}`).join('\n'));
    const cmdParts = parseTestCommand(process.env.DRIFT_TEST_CMD || '');
    const runnerBin = cmdParts.length ? cmdParts[0] : process.execPath;
    const runnerArgs = cmdParts.length ? [...cmdParts.slice(1), ...runFiles] : ['--test', ...runFiles];
    try {
      execFileSync(runnerBin, runnerArgs, {
        cwd: area,
        env: {
          ...process.env, DRIFT_RESOLVED: genDir, DRIFT_EVENTS: evDir, DRIFT_CONTRACTS: ids.join(','),
          ...(autoSnap ? { DRIFT_SNAPSHOT: autoSnap } : {}), ...(autoTouched ? { DRIFT_TOUCHED: autoTouched } : {}),
          ...(selFile ? { DRIFT_SELECT: selFile } : {}), ...(needMut && fs.existsSync(mutFile) ? { DRIFT_MUTANTS: mutFile, DRIFT_MUTATION_EVENTS: mutEvDir } : {}),
        },
        stdio: jsonOut ? ['ignore', 'pipe', 'pipe'] : 'inherit',
      });
    } catch (e) { testStatus = typeof e?.status === 'number' && e.status !== 0 ? e.status : 1; }
  }
  if (mode === 'test') {
    const miss = narrowedFiles === null && !runFiles.length;
    const act = selectWidened ? 'widened' : (runFiles.length ? 'narrowed' : (miss ? 'none' : 'skip'));
    if (miss && !testStatus) testStatus = 1;
    if (jsonOut) process.stdout.write(JSON.stringify({ ok: testStatus === 0, action: act, ran: runFiles.length, selected_files: runFiles, ...(baseRef ? { widened: selectWidened, reasons: selectReasons } : {}) }) + '\n');
    else if (!runFiles.length) process.stdout.write('drift test: 0 test file(s) selected\n');
    return testStatus;
  }
  const baseArgs = baseRef ? ['--base', baseRef, ...(changedPaths.length ? changedPaths.flatMap((cp) => ['--changed', cp]) : ['--changed-none'])] : [];
  const gateArgs = [mode, ...(allGate ? [cDir] : tomls), ...sdArgs, '--events', evDir, ...baseArgs, ...(needMut && fs.existsSync(mutFile) ? ['--mutants', mutFile, '--mutation-events', mutEvDir] : []), ...(jsonOut ? ['--json'] : [])];
  try { execFileSync(cli, gateArgs, { cwd: area, stdio: 'inherit' }); return testStatus; } catch (e) { return typeof e?.status === 'number' && e.status !== 0 ? e.status : 1; }
}
