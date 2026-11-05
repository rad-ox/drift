// Single-command CLI runner and test-file selection for the DRIFT JavaScript bridge.

const REL_KEYS = new Set([
  'min', 'max', 'min_len', 'max_len', 'non_empty', 'le_field', 'ge_field', 'eq_field', 'in',
  'sum_fields', 'contains', 'prefix', 'suffix',
]);
const throwError = (message) => {
  throw new Error(message);
};

const isStr = (v) => typeof v === 'string';
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isRelationalMap = (v) => isObj(v) && Object.keys(v).length > 0 && Object.keys(v).every((k) => REL_KEYS.has(k));
const cloneJson = (val) => (Array.isArray(val) ? val.map(cloneJson) : (isObj(val) ? Object.fromEntries(Object.entries(val).map(([k, v]) => [k, cloneJson(v)])) : val));
const stripRes = (p) => {
  const s = String(p || '');
  const st = s[0] === '/' ? 1 : 0;
  const col = s.indexOf(':/', st);
  return (col > st && /^[A-Za-z0-9][A-Za-z0-9._-]*$/u.test(s.slice(st, col))) ? s.slice(col + 1) : s;
};

function canonicalStubRef(ref, wp, tp) {
  if (!isStr(ref) || !ref.trim()) return '';
  const s = ref.trim();
  return stripRes(s.startsWith('/') ? s : (tp?.[s] || wp?.[s] || ('/' + s)));
}

const roundTightenedMin = (curMin, curMax, rawLo) => (Number.isInteger(curMin) || Number.isInteger(curMax) || Number.isInteger(rawLo)) ? Math.ceil(rawLo - 1e-9) : rawLo;
const roundTightenedMax = (curMin, curMax, rawHi) => (Number.isInteger(curMin) || Number.isInteger(curMax) || Number.isInteger(rawHi)) ? Math.floor(rawHi + 1e-9) : rawHi;

function peerOrderRelation(ckA, ckB, thenMap, wp, tp) {
  if (!ckA || !ckB || ckA === ckB || !isObj(thenMap)) return 0;
  for (const [k, v] of Object.entries(thenMap)) {
    if (!isRelationalMap(v)) continue;
    const ck = canonicalStubRef(k, wp, tp);
    if (ck === ckA) {
      if ('eq_field' in v && canonicalStubRef(v.eq_field, wp, tp) === ckB) return 3;
      if ('le_field' in v && canonicalStubRef(v.le_field, wp, tp) === ckB) return 1;
      if ('ge_field' in v && canonicalStubRef(v.ge_field, wp, tp) === ckB) return 2;
    } else if (ck === ckB) {
      if ('eq_field' in v && canonicalStubRef(v.eq_field, wp, tp) === ckA) return 3;
      if ('ge_field' in v && canonicalStubRef(v.ge_field, wp, tp) === ckA) return 1;
      if ('le_field' in v && canonicalStubRef(v.le_field, wp, tp) === ckA) return 2;
    }
  }
  return 0;
}

export function tightenThenMapBySumResiduals(whenMap, rawThen, wp, tp) {
  if (!isObj(rawThen)) return {};
  if (!Object.values(rawThen).some((v) => isRelationalMap(v) && ((Array.isArray(v.sum_fields) && v.sum_fields.length >= 2) || 'le_field' in v || 'ge_field' in v || 'eq_field' in v))) return rawThen;
  const out = cloneJson(rawThen);
  const lookupBounds = (ref) => {
    const ck = canonicalStubRef(ref, wp, tp), bare = isStr(ref) ? ref.trim().replace(/^\/+/u, '') : '';
    for (const [m, pm] of [[out, tp], [whenMap || {}, wp]]) {
      for (const [k, v] of Object.entries(m)) {
        if (k === ref || k === bare || canonicalStubRef(k, wp, pm) === ck) {
          if (typeof v === 'number') return { lo: v, hi: v };
          if (isRelationalMap(v)) return { lo: typeof v.min === 'number' ? v.min : undefined, hi: typeof v.max === 'number' ? v.max : undefined };
        }
      }
    }
    return { lo: undefined, hi: undefined };
  };
  const maxU = (a, b) => (a === undefined ? b : Math.max(a, b));
  const minU = (a, b) => (a === undefined ? b : Math.min(a, b));
  for (let pass = 0; pass < 3; pass++) {
    for (const [tk, tv] of Object.entries(out)) {
      if (!isRelationalMap(tv)) continue;
      const ckTarget = canonicalStubRef(tk, wp, tp);
      let loK = typeof tv.min === 'number' ? tv.min : undefined, hiK = typeof tv.max === 'number' ? tv.max : undefined;
      for (const pk of ['eq_field', 'le_field', 'ge_field']) {
        if (!(pk in tv)) continue;
        const pb = lookupBounds(tv[pk]);
        if ((pk === 'eq_field' || pk === 'ge_field') && pb.lo !== undefined) loK = maxU(loK, pb.lo);
        if ((pk === 'eq_field' || pk === 'le_field') && pb.hi !== undefined) hiK = minU(hiK, pb.hi);
      }
      for (const [pk, pv] of Object.entries(out)) {
        if (pk === tk || !isRelationalMap(pv)) continue;
        const pLo = typeof pv.min === 'number' ? pv.min : undefined, pHi = typeof pv.max === 'number' ? pv.max : undefined;
        if ('eq_field' in pv && canonicalStubRef(pv.eq_field, wp, tp) === ckTarget) {
          if (pLo !== undefined) loK = maxU(loK, pLo);
          if (pHi !== undefined) hiK = minU(hiK, pHi);
        }
        if ('le_field' in pv && canonicalStubRef(pv.le_field, wp, tp) === ckTarget && pLo !== undefined) loK = maxU(loK, pLo);
        if ('ge_field' in pv && canonicalStubRef(pv.ge_field, wp, tp) === ckTarget && pHi !== undefined) hiK = minU(hiK, pHi);
      }
      for (const [sk, sv] of Object.entries(out)) {
        if (sk === tk || !isRelationalMap(sv) || !Array.isArray(sv.sum_fields) || sv.sum_fields.length < 2) continue;
        const sLo = typeof sv.min === 'number' ? sv.min : undefined, sHi = typeof sv.max === 'number' ? sv.max : undefined;
        if (sLo === undefined && sHi === undefined) continue;
        const mult = new Map(), rep = new Map();
        for (const sf of sv.sum_fields) {
          const ck = canonicalStubRef(sf, wp, tp);
          if (ck) { mult.set(ck, (mult.get(ck) || 0) + 1); if (!rep.has(ck)) rep.set(ck, sf); }
        }
        const mk = mult.get(ckTarget) || 0;
        if (mk < 1) continue;
        let remLo = 0, remHi = 0, allRemLo = true, allRemHi = true;
        for (const [ck, mp] of mult.entries()) {
          if (ck === ckTarget) continue;
          const b = lookupBounds(rep.get(ck));
          if (b.lo !== undefined) remLo += mp * b.lo; else allRemLo = false;
          if (b.hi !== undefined) remHi += mp * b.hi; else allRemHi = false;
        }
        for (const [ckP, mp] of mult.entries()) {
          const ord = ckP === ckTarget ? 0 : peerOrderRelation(ckTarget, ckP, out, wp, tp);
          if (ord === 0) continue;
          let oLo = 0, oHi = 0, oAllLo = true, oAllHi = true;
          for (const [ckQ, mq] of mult.entries()) {
            if (ckQ === ckTarget || ckQ === ckP) continue;
            const b = lookupBounds(rep.get(ckQ));
            if (b.lo !== undefined) oLo += mq * b.lo; else oAllLo = false;
            if (b.hi !== undefined) oHi += mq * b.hi; else oAllHi = false;
          }
          if ((ord === 1 || ord === 3) && sHi !== undefined && oAllLo) hiK = minU(hiK, roundTightenedMax(loK, hiK, (sHi - oLo) / (mk + mp)));
          if ((ord === 2 || ord === 3) && sLo !== undefined && oAllHi) loK = maxU(loK, roundTightenedMin(loK, hiK, (sLo - oHi) / (mk + mp)));
        }
        for (const [bk, bv] of Object.entries(out)) {
          if (bk === sk || bk === tk || !isRelationalMap(bv) || !Array.isArray(bv.sum_fields) || bv.sum_fields.length < 2 || bv.sum_fields.length >= sv.sum_fields.length) continue;
          const bLo = typeof bv.min === 'number' ? bv.min : undefined, bHi = typeof bv.max === 'number' ? bv.max : undefined;
          if (bLo === undefined && bHi === undefined) continue;
          const multB = new Map();
          let okSub = true;
          for (const sf of bv.sum_fields) {
            const ck = canonicalStubRef(sf, wp, tp);
            if (!ck || ck === ckTarget) { okSub = false; break; }
            multB.set(ck, (multB.get(ck) || 0) + 1);
          }
          if (!okSub || ![...multB.entries()].every(([ck, m]) => (mult.get(ck) || 0) >= m)) continue;
          let exLo = 0, exHi = 0, exAllLo = true, exAllHi = true;
          for (const [ck, mp] of mult.entries()) {
            const d = ck === ckTarget ? 0 : (mp - (multB.get(ck) || 0));
            if (d <= 0) continue;
            const b = lookupBounds(rep.get(ck));
            if (b.lo !== undefined) exLo += d * b.lo; else exAllLo = false;
            if (b.hi !== undefined) exHi += d * b.hi; else exAllHi = false;
          }
          if (bLo !== undefined && exAllLo) { remLo = allRemLo ? Math.max(remLo, bLo + exLo) : (bLo + exLo); allRemLo = true; }
          if (bHi !== undefined && exAllHi) { remHi = allRemHi ? Math.min(remHi, bHi + exHi) : (bHi + exHi); allRemHi = true; }
        }
        if (sLo !== undefined && allRemHi) loK = maxU(loK, roundTightenedMin(loK, hiK, (sLo - remHi) / mk));
        if (sHi !== undefined && allRemLo) hiK = minU(hiK, roundTightenedMax(loK, hiK, (sHi - remLo) / mk));
        for (const [bk, bv] of Object.entries(out)) {
          if (bk === sk || bk === tk || !isRelationalMap(bv) || !Array.isArray(bv.sum_fields) || bv.sum_fields.length < 2) continue;
          const bLo = typeof bv.min === 'number' ? bv.min : undefined, bHi = typeof bv.max === 'number' ? bv.max : undefined;
          if (bLo === undefined && bHi === undefined) continue;
          const multB = new Map();
          for (const sf of bv.sum_fields) { const ck = canonicalStubRef(sf, wp, tp); if (ck) multB.set(ck, (multB.get(ck) || 0) + 1); }
          if (multB.has(ckTarget) || mult.size !== 2 || multB.size !== 2) continue;
          const yCk = [...mult.keys()].find((x) => x !== ckTarget);
          if (!yCk || mult.get(yCk) !== 1 || multB.get(yCk) !== 1) continue;
          const zCk = [...multB.keys()].find((x) => x !== yCk);
          for (const [ck3, cv3] of Object.entries(out)) {
            if (ck3 === sk || ck3 === bk || ck3 === tk || !isRelationalMap(cv3) || !Array.isArray(cv3.sum_fields) || cv3.sum_fields.length !== sv.sum_fields.length) continue;
            const multC = new Map();
            for (const sf of cv3.sum_fields) { const ck = canonicalStubRef(sf, wp, tp); if (ck) multC.set(ck, (multC.get(ck) || 0) + 1); }
            if (multC.size === 2 && multC.get(ckTarget) === mk && multC.get(zCk) === 1) {
              const cLo = typeof cv3.min === 'number' ? cv3.min : undefined, cHi = typeof cv3.max === 'number' ? cv3.max : undefined;
              if (sLo !== undefined && cLo !== undefined && bHi !== undefined) loK = maxU(loK, roundTightenedMin(loK, hiK, (sLo + cLo - bHi) / (2 * mk)));
              if (sHi !== undefined && cHi !== undefined && bLo !== undefined) hiK = minU(hiK, roundTightenedMax(loK, hiK, (sHi + cHi - bLo) / (2 * mk)));
            }
          }
        }
      }
      if (loK !== undefined && (hiK === undefined || loK <= hiK)) tv.min = loK;
      if (hiK !== undefined && (loK === undefined || loK <= hiK)) tv.max = hiK;
    }
  }
  return out;
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
    } else {
      const direct = path.join(cur, rem);
      if (fs.existsSync(direct) && fs.statSync(direct).isFile()) return rel ? `${rel}/${rem}` : rem;
    }
    for (let pos = 0, dot = rem.indexOf('.', 0); dot > 0; pos = dot + 1, dot = rem.indexOf('.', pos)) {
      const seg = rem.slice(0, dot);
      if (entryType(cur, seg) === 2) {
        const res = findRel(path.join(cur, seg), rel ? `${rel}/${seg}` : seg, rem.slice(dot + 1));
        if (res) return res;
      }
    }
    miss.add(mk);
    return '';
  };
  for (const tid of Array.isArray(raw.tests) ? raw.tests : []) {
    const cls = isStr(tid) ? tid.split('#', 1)[0].split('\\').join('/') : '';
    const hit = cls ? findRel(rootDir, '', cls) : '';
    if (hit) out.add(hit);
  }
  return [...out].sort();
}

export function mergePriorInventory(out, inv, isShard, fs, path, rootDir) {
  if (!inv.mergedClasses) inv.mergedClasses = new Set();
  if ((isShard && inv.classes.size > 0 && [...inv.classes].every((c) => inv.mergedClasses.has(c))) || (!isShard && inv.mergedSingle)) return;
  const selfMeta = `${out.slice(0, -6)}.meta.json`, dir = path.dirname(out);
  const files = isShard
    ? (fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => f.endsWith('.meta.json')).sort().reverse().map((f) => path.join(dir, f)).filter((p) => p !== selfMeta) : [])
    : (fs.existsSync(selfMeta) ? [selfMeta] : []);
  if (!files.length) return;
  const pending = isShard ? new Set([...inv.classes].filter((c) => !inv.mergedClasses.has(c))) : null;
  const clsOk = new Map();
  const hasCls = (cls) => {
    if (!clsOk.has(cls)) clsOk.set(cls, resolveSelectedFiles({ all: false, tests: [`${cls}#_`] }, rootDir, fs, path).length > 0);
    return clsOk.get(cls);
  };
  for (const mf of files) {
    if (pending && !pending.size) break;
    try {
      const m = JSON.parse(fs.readFileSync(mf, 'utf8'));
      if (!isObj(m)) continue;
      const mClasses = Array.isArray(m.classes) ? m.classes.filter(isStr) : [];
      if (pending && !mClasses.some((c) => pending.has(c))) continue;
      const takeCls = new Set();
      for (const c of mClasses) {
        if (isShard ? (pending.has(c) && hasCls(c)) : (inv.classes.has(c) || hasCls(c))) { inv.classes.add(c); takeCls.add(c); }
        if (pending && pending.has(c)) { pending.delete(c); inv.mergedClasses.add(c); }
      }
      for (const tid of Array.isArray(m.tests) ? m.tests : []) {
        const cls = isStr(tid) ? tid.split('#', 1)[0] : '';
        if (cls && takeCls.has(cls)) inv.tests.add(tid);
      }
      if (isObj(m.inputs)) {
        for (const [tid, fmap] of Object.entries(m.inputs)) {
          if (!inv.tests.has(tid) || !isObj(fmap)) continue;
          if (!inv.inputs.has(tid)) inv.inputs.set(tid, new Map());
          const cur = inv.inputs.get(tid);
          for (const [fp, dig] of Object.entries(fmap)) if (!cur.has(fp) && isStr(dig)) cur.set(fp, dig);
        }
      }
    } catch {}
  }
  if (pending) for (const c of pending) inv.mergedClasses.add(c);
  else inv.mergedSingle = true;
}

function captureWorktreeSnapshot(area, execFileSync, fs, path, process) {
  try {
    const st = execFileSync('git', ['-C', area, 'status', '--porcelain', '--untracked-files=normal'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    if (!st) {
      const tr = execFileSync('git', ['-C', area, 'rev-parse', '--verify', '--quiet', 'HEAD^{tree}'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
      if (/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/u.test(tr)) return tr;
    }
    const rev = execFileSync('git', ['-C', area, 'rev-parse', '--show-toplevel', '--git-dir'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim().split(/\r?\n/u);
    if (rev.length < 2) return '';
    const top = path.resolve(area, rev[0].trim()), realIdx = path.join(path.resolve(area, rev[1].trim()), 'index'), tmpIdx = path.join(area, '.drift-work', `.git-index-${process.pid}`);
    try {
      if (fs.existsSync(realIdx)) fs.copyFileSync(realIdx, tmpIdx); else fs.rmSync(tmpIdx, { force: true });
      const env = { ...process.env, GIT_INDEX_FILE: tmpIdx };
      execFileSync('git', ['-C', top, '-c', 'core.safecrlf=false', 'add', '-A', '--', '.', ':(exclude).drift-work', ':(exclude).build', ':(exclude)target'], { env, stdio: 'ignore' });
      const tr = execFileSync('git', ['-C', top, 'write-tree'], { env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
      if (/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/u.test(tr)) return tr;
    } finally { fs.rmSync(tmpIdx, { force: true }); }
  } catch {}
  return '';
}

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
  let area = process.cwd();
  while (!fs.existsSync(path.join(area, '.drift', 'contracts')) && path.dirname(area) !== area) area = path.dirname(area);
  const cDir = path.join(area, '.drift', 'contracts');
  if (!fs.existsSync(cDir)) throwError(`no .drift/contracts found from ${process.cwd()}`);
  if (!targets.length) for (const fn of fs.readdirSync(cDir).filter((f) => f.endsWith('.toml')).sort()) targets.push(path.basename(fn, '.toml'));
  if (!targets.length) throwError('usage: node drift.mjs [test|prove|gate] [<contract...>] [--base <ref>] [--changed [<file>]] [--prove|--gate] [--json]');
  const home = process.env.HOME || process.env.USERPROFILE || '';
  const clis = [(process.env.DRIFT_CLI || '').trim(), path.join(area, '.build', 'drift'), 'drift', home ? path.join(home, '.local', 'bin', 'drift') : ''].filter(Boolean);
  let cli = '';
  for (const cand of clis) {
    try { execFileSync(cand, ['version'], { cwd: area, stdio: 'ignore' }); cli = cand; break; } catch {}
  }
  if (!cli) throwError('drift CLI not found on PATH or DRIFT_CLI');
  if (wantChanged && !baseRef) baseRef = 'HEAD';
  if (wantChanged && !changedPaths.length) {
    try {
      const seen = new Set();
      const dOut = execFileSync('git', ['-C', area, 'diff', '--name-only', '--relative', baseRef], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
      const uOut = execFileSync('git', ['-C', area, 'ls-files', '--others', '--exclude-standard'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
      for (const ln of `${dOut}\n${uOut}`.split('\n')) {
        const p = ln.trim();
        if (p && !p.startsWith('.drift-work/') && !seen.has(p)) { seen.add(p); changedPaths.push(p); }
      }
    } catch {}
  }
  const resDir = path.join(area, '.drift-work', 'resolved'), evDir = path.join(area, '.drift-work', 'events');
  fs.mkdirSync(resDir, { recursive: true });
  fs.mkdirSync(evDir, { recursive: true });
  const ids = [], idSet = new Set(), tomls = [], tomlSet = new Set(), relSrcs = [];
  const addTarget = (id, direct) => {
    if (!idSet.has(id)) { idSet.add(id); ids.push(id); }
    if (!tomlSet.has(direct)) { tomlSet.add(direct); tomls.push(direct); }
  };
  for (const t of targets) {
    const id = path.basename(t).endsWith('.toml') ? path.basename(t, '.toml') : t;
    const direct = fs.existsSync(path.resolve(area, t)) && t.endsWith('.toml') ? path.resolve(area, t) : path.join(cDir, `${id}.toml`);
    if (!fs.existsSync(direct)) {
      const candSrc = fs.existsSync(path.resolve(area, t)) ? path.resolve(area, t) : (fs.existsSync(path.resolve(process.cwd(), t)) ? path.resolve(process.cwd(), t) : '');
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
      const unm = new Set(Array.isArray(impObj?.unmatched_code) ? impObj.unmatched_code : []);
      const miss = relSrcs.find((x) => unm.has(x.relSrc));
      if (miss) throwError(`contract "${miss.raw}" not found at ${miss.direct}`);
      for (const mc of impObj?.contracts || []) {
        const mDirect = path.join(cDir, `${mc.id}.toml`);
        if (mc.id && fs.existsSync(mDirect)) addTarget(mc.id, mDirect);
      }
    } catch (e) { if (String(e?.message || '').includes('not found at')) throw e; }
    if (!ids.length) throwError(`contract "${relSrcs[0].raw}" not found at ${relSrcs[0].direct}`);
  }
  try { execFileSync(cli, ['show', ...tomls, '--out', resDir], { cwd: area, stdio: ['ignore', 'pipe', 'pipe'] }); } catch {}
  let selFile = '', narrowedFiles = null;
  if (baseRef) {
    const selArgs = ['select', tomls.length === 1 ? tomls[0] : cDir, '--base', baseRef, '--events', evDir, '--files', '--json', ...(changedPaths.length ? changedPaths.flatMap((cp) => ['--changed', cp]) : (wantChanged ? ['--changed'] : []))];
    try {
      const selOut = execFileSync(cli, selArgs, { cwd: area, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
      const selObj = JSON.parse(selOut);
      if (selObj && selObj.all === false && Array.isArray(selObj.test_files)) {
        selFile = path.join(area, '.drift-work', 'select.json');
        fs.writeFileSync(selFile, selOut, 'utf8');
        narrowedFiles = selObj.test_files;
      }
    } catch {}
  }
  const testFiles = new Set(), missingIds = [];
  if (narrowedFiles !== null) {
    for (const f of narrowedFiles) testFiles.add(f);
  } else {
    const byCid = new Map(ids.map((id) => [id, new Set()]));
    for (const dir of [evDir, path.join(area, '.drift', 'events')]) {
      if (!fs.existsSync(dir)) continue;
      for (const fn of fs.readdirSync(dir).filter((f) => f.endsWith('.jsonl')).sort()) {
        for (const line of fs.readFileSync(path.join(dir, fn), 'utf8').split('\n')) {
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
    const isTestFile = (p) => /\.(?:test|spec|e2e)\.(?:mjs|js|cjs|ts|tsx|mts|cts)$/u.test(p) || /_test\.(?:mjs|js|cjs|ts|tsx|mts|cts)$/u.test(p);
    const globParts = [];
    for (const id of [...missingIds]) {
      const vf = path.join(resDir, `${id}.json`);
      if (!fs.existsSync(vf)) continue;
      for (const g of JSON.parse(fs.readFileSync(vf, 'utf8'))?.scope?.code || []) {
        const clean = String(g).split('#', 1)[0].replace(/\\/gu, '/').replace(/\/+$/u, '');
        if (!clean) continue;
        if (!clean.includes('*') && isTestFile(clean) && fs.existsSync(path.join(area, clean))) {
          testFiles.add(clean);
          const idx = missingIds.indexOf(id);
          if (idx >= 0) missingIds.splice(idx, 1);
        } else globParts.push(clean.replace(/[.+^${}()|[\]\\]/gu, '\\$&').replace(/\*\*/gu, '\u0000').replace(/\*/gu, '[^/]*').replace(/\u0000/gu, '.*'));
      }
    }
    if (missingIds.length) {
      const globRx = globParts.length ? new RegExp(`^(?:${globParts.join('|')})(?:$|/)`, 'u') : null;
      const idRx = new RegExp(`['"](?:${missingIds.map((id) => id.replace(/[.+^${}()|[\]\\]/gu, '\\$&')).join('|')})['"]`, 'u');
      const skip = new Set(['.git', '.drift', '.drift-work', 'node_modules', 'target', '.build']);
      const walk = (dir) => {
        for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
          if (skip.has(e.name)) continue;
          const full = path.join(dir, e.name);
          if (e.isDirectory() && !e.isSymbolicLink()) walk(full);
          else if (e.isFile() && isTestFile(e.name)) {
            const rel = path.relative(area, full).split(path.sep).join('/');
            if ((globRx && globRx.test(rel)) || idRx.test(fs.readFileSync(full, 'utf8'))) testFiles.add(rel);
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
      const diffOut = execFileSync('git', ['-C', area, 'diff', '--name-only', '--relative', 'HEAD'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
      autoTouched = diffOut.split('\n').map((s) => s.trim()).filter((s) => s && !s.startsWith('.drift/') && !s.startsWith('.drift-work/')).join(',');
    } catch {}
  }
  const cfgPath = path.join(area, '.drift', 'config.toml');
  const needMut = forceMut
    || (fs.existsSync(cfgPath) && /proof\s*=\s*"killed"/u.test(fs.readFileSync(cfgPath, 'utf8')))
    || ids.some((id) => { const vf = path.join(resDir, `${id}.json`); return fs.existsSync(vf) && JSON.parse(fs.readFileSync(vf, 'utf8'))?.requires?.proof === 'killed'; });
  const mutFile = path.join(area, '.drift-work', 'mutants.json'), mutEvDir = path.join(area, '.drift-work', 'mut-events');
  if (needMut) {
    fs.rmSync(mutEvDir, { recursive: true, force: true });
    fs.mkdirSync(mutEvDir, { recursive: true });
    const mArgs = ['mutants', ...tomls, ...(baseRef ? ['--base', baseRef] : []), ...(changedPaths.length ? changedPaths.flatMap((cp) => ['--changed', cp]) : (wantChanged ? ['--changed'] : [])), ...(mutWhen ? ['--when'] : []), ...(mutBudget ? ['--budget', mutBudget, '--events', evDir] : []), '--out', mutFile];
    try { execFileSync(cli, mArgs, { cwd: area, stdio: ['ignore', 'pipe', 'pipe'] }); } catch {}
  }
  let testStatus = 0;
  if (runFiles.length) {
    const cmdParts = (process.env.DRIFT_TEST_CMD || '').trim().split(/\s+/u).filter(Boolean);
    const runnerBin = cmdParts.length ? cmdParts[0] : process.execPath;
    const runnerArgs = cmdParts.length ? [...cmdParts.slice(1), ...runFiles] : ['--test', ...runFiles];
    try {
      execFileSync(runnerBin, runnerArgs, {
        cwd: area,
        env: {
          ...process.env, DRIFT_RESOLVED: resDir, DRIFT_EVENTS: evDir, DRIFT_CONTRACTS: ids.join(','),
          ...(autoSnap ? { DRIFT_SNAPSHOT: autoSnap } : {}), ...(autoTouched ? { DRIFT_TOUCHED: autoTouched } : {}),
          ...(selFile ? { DRIFT_SELECT: selFile } : {}), ...(needMut && fs.existsSync(mutFile) ? { DRIFT_MUTANTS: mutFile, DRIFT_MUTATION_EVENTS: mutEvDir } : {}),
        },
        stdio: jsonOut ? ['ignore', 'pipe', 'pipe'] : 'inherit',
      });
    } catch (e) { testStatus = typeof e?.status === 'number' && e.status !== 0 ? e.status : 1; }
  }
  if (mode === 'test') {
    if (jsonOut) process.stdout.write(JSON.stringify({ ok: testStatus === 0, ran: runFiles.length, selected_files: runFiles }) + '\n');
    else if (!runFiles.length) process.stdout.write('drift test: 0 test file(s) selected\n');
    return testStatus;
  }
  const baseArgs = baseRef ? ['--base', baseRef, ...(changedPaths.length ? changedPaths.flatMap((cp) => ['--changed', cp]) : ['--changed-none'])] : [];
  const gateArgs = [mode, ...(allGate ? [cDir] : tomls), '--events', evDir, ...baseArgs, ...(needMut && fs.existsSync(mutFile) ? ['--mutants', mutFile, '--mutation-events', mutEvDir] : []), ...(jsonOut ? ['--json'] : [])];
  try { execFileSync(cli, gateArgs, { cwd: area, stdio: 'inherit' }); return 0; } catch (e) { return typeof e?.status === 'number' && e.status !== 0 ? e.status : 1; }
}
