// Upstream boundary discovery, stub synthesis, and auto-resolve helpers for the DRIFT JavaScript bridge.
import {
  REL_KEYS,
  cloneJson,
  isObj,
  isStr,
  readPointer,
  splitResourcePointer,
  writePointer,
} from './drift_checks.mjs';
import { tightenThenMapBySumResiduals } from './drift_cli.mjs';

const isRelationalMap = (v) => isObj(v) && Object.keys(v).length > 0 && Object.keys(v).every((k) => REL_KEYS.has(k));
const stripRes = (p) => splitResourcePointer(String(p || ''))[1];
const relPeerRank = (v) => (!isRelationalMap(v) ? 0 : (Array.isArray(v.sum_fields) ? 2 + v.sum_fields.length : (('eq_field' in v || 'ge_field' in v || 'le_field' in v) ? 1 : 0)));

function buildPeerIndex(whenMap, rawThenMap, whenProjections, thenProjections) {
  const thenMap = tightenThenMapBySumResiduals(whenMap, rawThenMap, whenProjections, thenProjections);
  const idx = new Map();
  for (const [wk, rawWv] of Object.entries(whenMap || {})) {
    const wv = isObj(rawWv) && Object.keys(rawWv).length === 1 && 'eq' in rawWv ? rawWv.eq : rawWv;
    if (isRelationalMap(wv)) continue;
    idx.set(wk, wv);
    idx.set(`when.${wk}`, wv);
    const wp = stripRes(whenProjections?.[wk] || '');
    if (wp.startsWith('/')) idx.set(wp, wv);
  }
  const relEntries = [];
  for (const [tk, rawTv] of Object.entries(thenMap || {})) {
    const tv = isObj(rawTv) && Object.keys(rawTv).length === 1 && 'eq' in rawTv ? rawTv.eq : rawTv;
    if (isRelationalMap(tv)) {
      relEntries.push([tk, tv]);
      continue;
    }
    idx.set(tk, tv);
    idx.set(`then.${tk}`, tv);
    const tp = stripRes(thenProjections?.[tk] || '');
    if (tp.startsWith('/')) idx.set(tp, tv);
  }
  if (relEntries.length) {
    relEntries.sort((a, b) => (relPeerRank(a[1]) - relPeerRank(b[1])) || a[0].localeCompare(b[0]));
    const peerFn = (ref) => resolveStubPeer(ref, {}, idx, whenProjections, thenProjections);
    for (let pass = 0; pass < 8; pass++) {
      let progress = false;
      for (const [tk, tv] of relEntries) {
        if (idx.has(tk)) continue;
        if (('eq_field' in tv && !peerFn(tv.eq_field).found)
          || ('ge_field' in tv && !peerFn(tv.ge_field).found)
          || ('le_field' in tv && !peerFn(tv.le_field).found)
          || (Array.isArray(tv.sum_fields) && tv.sum_fields.some((sf) => !peerFn(sf).found))) continue;
        const w = witnessValue(tv, peerFn);
        idx.set(tk, w);
        idx.set(`then.${tk}`, w);
        const tp = stripRes(thenProjections?.[tk] || '');
        if (tp.startsWith('/')) idx.set(tp, w);
        progress = true;
      }
      if (!progress) break;
    }
  }
  return idx;
}

function resolveStubPeer(ref, base, peerIdx, whenProjections, thenProjections) {
  if (!isStr(ref) || !ref.trim()) return { found: false, value: undefined };
  const s = ref.trim();
  const bare = s.replace(/^\/+/u, '');
  if (s.startsWith('/')) {
    const r = readPointer(base, s);
    if (r.found && !isRelationalMap(r.value)) return r;
  } else {
    if (isObj(base) && s in base && !isRelationalMap(base[s])) return { found: true, value: base[s] };
    for (const pm of [thenProjections, whenProjections]) {
      if (s in pm) {
        const r = readPointer(base, pm[s]);
        if (r.found && !isRelationalMap(r.value)) return r;
      }
    }
    const r = readPointer(base, '/' + bare);
    if (r.found && !isRelationalMap(r.value)) return r;
  }
  const tgt = stripRes(s.startsWith('/') ? s : (thenProjections?.[s] || whenProjections?.[s] || ('/' + bare)));
  for (const cand of [s, bare, tgt]) {
    if (cand && peerIdx.has(cand)) return { found: true, value: peerIdx.get(cand) };
  }
  return { found: false, value: undefined };
}

function resolveRelPeerBounds(val, peerFn) {
  if (isObj(val) && 'eq' in val && !('balance_fields' in val) && !('sum_fields' in val) && !('peer' in val)) {
    return { eqFound: true, eqVal: val.eq, min: undefined, max: undefined };
  }
  if (!isRelationalMap(val) || !peerFn) return { eqFound: false, eqVal: undefined, min: val?.min, max: val?.max };
  if ('eq_field' in val) {
    const pr = peerFn(val.eq_field);
    if (pr.found) return { eqFound: true, eqVal: pr.value, min: undefined, max: undefined };
  }
  let lo = typeof val.min === 'number' ? val.min : undefined;
  let hi = typeof val.max === 'number' ? val.max : undefined;
  if (typeof val.approx === 'number') {
    lo = lo === undefined ? val.approx : Math.max(lo, val.approx);
    hi = hi === undefined ? val.approx : Math.min(hi, val.approx);
  }
  if ('ge_field' in val) {
    const pr = peerFn(val.ge_field);
    if (pr.found && typeof pr.value === 'number') lo = lo === undefined ? pr.value : Math.max(lo, pr.value);
  }
  if ('le_field' in val) {
    const pr = peerFn(val.le_field);
    if (pr.found && typeof pr.value === 'number') hi = hi === undefined ? pr.value : Math.min(hi, pr.value);
  }
  if (Array.isArray(val.sum_fields) && val.sum_fields.length >= 2) {
    let sum = 0;
    let ok = true;
    for (const sf of val.sum_fields) {
      const pr = peerFn(sf);
      if (!pr.found || typeof pr.value !== 'number') {
        ok = false;
        break;
      }
      sum += pr.value;
    }
    if (ok) {
      sum = Number.isInteger(sum) ? sum : Math.round(sum * 1e12) / 1e12;
      lo = lo === undefined ? sum : Math.max(lo, sum);
      hi = hi === undefined ? sum : Math.min(hi, sum);
    }
  }
  return { eqFound: false, eqVal: undefined, min: lo, max: hi };
}

function buildAffixString(val, len) {
  const pfx = isStr(val.prefix) ? val.prefix : '';
  const sfx = isStr(val.suffix) ? val.suffix : '';
  const target = Math.max(len, pfx.length + sfx.length);
  const pad = Math.max(0, target - pfx.length - sfx.length);
  return `${pfx}${'x'.repeat(pad)}${sfx}`;
}

export function witnessValue(val, peerFn = null) {
  if (isRelationalMap(val)) {
    const b = resolveRelPeerBounds(val, peerFn);
    if (b.eqFound) return cloneJson(b.eqVal);
    if (Array.isArray(val.in) && val.in.length) {
      const filt = val.in.filter((x) => (b.min === undefined || (typeof x === 'number' && x >= b.min))
        && (b.max === undefined || (typeof x === 'number' && x <= b.max)));
      return cloneJson((filt.length ? filt : val.in)[0]);
    }
    if (typeof b.min === 'number') return b.min;
    if (typeof b.max === 'number') return b.max;
    if (Array.isArray(val.contains) && val.contains.length) {
      const out = val.contains.map(cloneJson);
      const minL = Math.max(val.non_empty === true ? 1 : 0, Number(val.min_len || 0));
      while (out.length < minL) out.push(cloneJson(val.contains[0]));
      return out;
    }
    if (isStr(val.prefix) || isStr(val.suffix) || typeof val.min_len === 'number' || val.non_empty === true) {
      const minL = Math.max(val.non_empty === true ? 1 : 0, Number(val.min_len || 0));
      return buildAffixString(val, minL);
    }
    if ('sum_total' in val || 'monotonic' in val || 'step_max_delta' in val) {
      const st = val.sum_total;
      const tgt = typeof st === 'number' ? st : (isObj(st) && typeof st.eq === 'number' ? st.eq : (isObj(st) && typeof st.min === 'number' && typeof st.max === 'number' ? (st.min + st.max) / 2 : (isObj(st) && typeof st.min === 'number' ? st.min : (isObj(st) && typeof st.max === 'number' ? st.max : 1.0))));
      const eps = typeof val.step_max_delta === 'number' && val.step_max_delta > 0 ? Math.min(0.2, val.step_max_delta / 2) : 0.2;
      const mode = String(val.monotonic || '');
      if (mode === 'strictly_decreasing' || mode === 'non_increasing') {
        const a = Math.round((tgt / 2 + eps / 2) * 1e12) / 1e12;
        return 'sum_total' in val ? [a, Math.round((tgt - a) * 1e12) / 1e12] : [Math.round((1 + eps) * 1e12) / 1e12, 1];
      }
      if (mode === 'strictly_increasing' || mode === 'non_decreasing') {
        const a = Math.round((tgt / 2 - eps / 2) * 1e12) / 1e12;
        return 'sum_total' in val ? [a, Math.round((tgt - a) * 1e12) / 1e12] : [1, Math.round((1 + eps) * 1e12) / 1e12];
      }
      return [tgt / 2, tgt - tgt / 2];
    }
    return '';
  }
  return cloneJson(val);
}

export function witnessVariants(val, peerFn = null) {
  if (isRelationalMap(val)) {
    const b = resolveRelPeerBounds(val, peerFn);
    if (b.eqFound) return [cloneJson(b.eqVal)];
    if (Array.isArray(val.in) && val.in.length) {
      const filt = val.in.filter((x) => (b.min === undefined || (typeof x === 'number' && x >= b.min))
        && (b.max === undefined || (typeof x === 'number' && x <= b.max)));
      return (filt.length ? filt : val.in).map(cloneJson);
    }
    if (typeof b.min === 'number' && typeof b.max === 'number') {
      return b.min === b.max ? [b.min] : [b.min, b.max];
    }
    if (typeof b.min === 'number') return [b.min];
    if (typeof b.max === 'number') return [b.max];
    if (Array.isArray(val.contains) && val.contains.length) {
      return [witnessValue(val, peerFn)];
    }
    if (isStr(val.prefix) || isStr(val.suffix) || typeof val.min_len === 'number' || typeof val.max_len === 'number' || val.non_empty === true) {
      const pfxLen = isStr(val.prefix) ? val.prefix.length : 0;
      const sfxLen = isStr(val.suffix) ? val.suffix.length : 0;
      const lo = Math.max(val.non_empty === true ? 1 : 0, Number(val.min_len ?? 0), pfxLen + sfxLen);
      const hi = typeof val.max_len === 'number' ? Number(val.max_len) : lo;
      return hi > lo ? [buildAffixString(val, lo), buildAffixString(val, hi)] : [buildAffixString(val, lo)];
    }
    if ('sum_total' in val || 'monotonic' in val || 'step_max_delta' in val) {
      return [witnessValue(val, peerFn)];
    }
    return [''];
  }
  return [cloneJson(val)];
}

export function extractProjectionMap(view, side) {
  const raw = view?.projections;
  if (!isObj(raw)) return {};
  const out = {};
  for (const [k, v] of Object.entries(raw)) {
    if (k !== 'when' && k !== 'then' && isStr(v)) out[k] = v;
  }
  if (isObj(raw[side])) {
    for (const [k, v] of Object.entries(raw[side])) {
      if (isStr(v)) out[k] = v;
    }
  }
  return out;
}

const HOMOLOGOUS_PAIRS = new Set([
  '1:2', '2:1', 'a:b', 'b:a', 'x:y', 'y:x', 'left:right', 'right:left',
  'src:dst', 'dst:src', 'source:target', 'target:source', 'from:to', 'to:from',
  'primary:secondary', 'secondary:primary', 'first:second', 'second:first',
]);

function isHomologousKey(a, b) {
  if (a === b) return false;
  const la = a.toLowerCase();
  const lb = b.toLowerCase();
  const ta = la.split('_');
  const tb = lb.split('_');
  if (ta.length === tb.length && ta.length >= 2) {
    let diff = 0;
    let ok = true;
    for (let i = 0; i < ta.length; i++) {
      if (ta[i] === tb[i]) continue;
      diff++;
      if (!HOMOLOGOUS_PAIRS.has(`${ta[i]}:${tb[i]}`)) ok = false;
    }
    if (ok && diff === 1) return true;
  }
  return la.length === lb.length && la.length >= 2
    && la.slice(0, -1) === lb.slice(0, -1)
    && '12abxy'.includes(la.at(-1)) && '12abxy'.includes(lb.at(-1));
}

export function synthesizeViewOutput(view, caseId, base = {}, thenMap = null) {
  const pc = view?.__plan?.cases?.[caseId];
  if (pc?.stub_output && (!isObj(base) || !Object.keys(base).length) && (!thenMap || thenMap === view?.cases?.[caseId]?.then)) {
    return cloneJson(pc.stub_output);
  }
  const whenProjections = extractProjectionMap(view, 'when');
  const thenProjections = extractProjectionMap(view, 'then');
  const whenMap = view?.cases?.[caseId]?.when || {};
  const rawThen = tightenThenMapBySumResiduals(whenMap, view?.cases?.[caseId]?.then || {}, whenProjections, thenProjections);
  const tbl = thenMap ? tightenThenMapBySumResiduals(whenMap, thenMap, whenProjections, thenProjections) : rawThen;
  let out = cloneJson(isObj(base) ? base : {});
  const peerIdx = buildPeerIndex(whenMap, tbl, whenProjections, thenProjections);
  const peerFn = (ref) => resolveStubPeer(ref, out, peerIdx, whenProjections, thenProjections);
  const entries = Object.entries(tbl).sort((a, b) => (relPeerRank(a[1]) - relPeerRank(b[1])) || a[0].localeCompare(b[0]));
  const resolved = new Map();
  for (const [k, v] of entries) {
    const vars = witnessVariants(v, peerFn);
    let w = vars[0];
    if (vars.length > 1 && !(isObj(v) && 'eq_field' in v)) {
      for (const [pk, pv] of resolved.entries()) {
        if (isHomologousKey(pk, k) && JSON.stringify(pv) === JSON.stringify(w)) {
          const alt = vars.find((cand) => JSON.stringify(cand) !== JSON.stringify(pv));
          if (alt !== undefined) w = alt;
          break;
        }
      }
    }
    resolved.set(k, w);
    peerIdx.set(k, w);
    const tp = stripRes(thenProjections?.[k] || '');
    if (tp.startsWith('/')) peerIdx.set(tp, w);
    if (k in thenProjections) out = writePointer(out, thenProjections[k], w);
  }
  for (const k of Object.keys(tbl)) {
    if (!(k in thenProjections) && isObj(out)) out[k] = resolved.get(k);
  }
  return out;
}

function lookupWhenInput(whenInput, wk, whenProjections) {
  if (!isObj(whenInput)) return { found: false, value: undefined };
  if (wk in whenInput) return { found: true, value: whenInput[wk] };
  const rawP = whenProjections?.[wk] || '';
  const bareP = stripRes(rawP);
  for (const p of [rawP, bareP, '/' + wk]) {
    if (!p) continue;
    if (p in whenInput) return { found: true, value: whenInput[p] };
    const r = readPointer(whenInput, p);
    if (r.found) return r;
  }
  return { found: false, value: undefined };
}

export function resolveStubCaseId(view, idOrRes, caseIdOrWhen, base, errFn) {
  if (isStr(caseIdOrWhen)) {
    const cm = view?.cases?.[caseIdOrWhen];
    if (!isObj(cm)) errFn(`contract "${idOrRes}" has no case "${caseIdOrWhen}"`);
    if ('status' in cm) errFn(`case "${caseIdOrWhen}" of contract "${idOrRes}" is ${cm.status} and cannot be stubbed`);
    return caseIdOrWhen;
  }
  if (!isObj(caseIdOrWhen) || !isObj(view?.cases)) errFn(`contract "${idOrRes}" has no case matching when input`);
  const whenProjections = extractProjectionMap(view, 'when');
  const thenProjections = extractProjectionMap(view, 'then');
  let bestScore = 0;
  let bestCases = [];
  for (const caseId of Object.keys(view.cases).sort()) {
    const cm = view.cases[caseId];
    if (!isObj(cm) || 'status' in cm || !isObj(cm.when)) continue;
    let matched = 0;
    let compat = true;
    for (const [wk, wv] of Object.entries(cm.when)) {
      const hit = lookupWhenInput(caseIdOrWhen, wk, whenProjections);
      if (!hit.found) continue;
      if (JSON.stringify(hit.value) !== JSON.stringify(wv)) {
        compat = false;
        break;
      }
      matched++;
    }
    if (compat && matched > 0) {
      if (matched > bestScore) {
        bestScore = matched;
        bestCases = [caseId];
      } else if (matched === bestScore) {
        bestCases.push(caseId);
      }
    }
  }
  if (!bestCases.length) errFn(`contract "${idOrRes}" has no case matching when input`);
  if (bestCases.length >= 2) {
    const varsByCase = bestCases.map((c) => {
      const cm = view.cases[c] || {};
      const tTbl = cm.then || {};
      const pIdx = buildPeerIndex(cm.when || {}, tTbl, whenProjections, thenProjections);
      const pFn = (ref) => resolveStubPeer(ref, base, pIdx, whenProjections, thenProjections);
      const m = new Map();
      for (const tk of Object.keys(tTbl).sort()) {
        const ptr = stripRes(thenProjections[tk] || '') || tk;
        if (!m.has(ptr)) m.set(ptr, JSON.stringify(witnessVariants(tTbl[tk], pFn)));
      }
      return m;
    });
    for (let i = 0; i < bestCases.length; i++) {
      for (let j = i + 1; j < bestCases.length; j++) {
        for (const [ptr, v1] of varsByCase[i].entries()) {
          if (varsByCase[j].has(ptr) && varsByCase[j].get(ptr) !== v1) {
            errFn(`ambiguous boundary projection on "${idOrRes}" (${ptr}) across ${bestCases[i]}, ${bestCases[j]}`);
          }
        }
      }
    }
  }
  return bestCases[0];
}

export function synthesizeViewVariants(view, caseId, base = {}) {
  const pc = view?.__plan?.cases?.[caseId];
  if (Array.isArray(pc?.stub_variants) && pc.stub_variants.length && (!isObj(base) || !Object.keys(base).length)) {
    return pc.stub_variants.map(cloneJson);
  }
  const whenProjections = extractProjectionMap(view, 'when');
  const thenProjections = extractProjectionMap(view, 'then');
  const whenMap = view?.cases?.[caseId]?.when || {};
  const tbl = tightenThenMapBySumResiduals(whenMap, view?.cases?.[caseId]?.then || {}, whenProjections, thenProjections);
  const peerIdx = buildPeerIndex(whenMap, tbl, whenProjections, thenProjections);
  const peerFn = (ref) => resolveStubPeer(ref, base, peerIdx, whenProjections, thenProjections);
  const keys = Object.keys(tbl).sort();
  const d = keys.length;
  const varsByKey = keys.map((k) => witnessVariants(tbl[k], peerFn));
  const cur = {};
  for (let i = 0; i < d; i++) cur[keys[i]] = varsByKey[i][0];
  const maxExcursions = d >= 3 ? 2 : d;
  const out = [];
  const dfs = (pos, exc) => {
    if (pos === d || exc >= maxExcursions) {
      const eff = Object.fromEntries(keys.map((k, i) => [k, relPeerRank(tbl[k]) > 0 && cur[k] === varsByKey[i][0] ? tbl[k] : cur[k]]));
      out.push(synthesizeViewOutput(view, caseId, base, eff));
      return;
    }
    dfs(pos + 1, exc);
    const vars = varsByKey[pos];
    const k = keys[pos];
    for (let i = 1; i < vars.length; i++) {
      cur[k] = vars[i];
      dfs(pos + 1, exc + 1);
    }
    cur[k] = vars[0];
  };
  dfs(0, 0);
  return out;
}

const UP_CACHE = new Map();
const PROF_MTIME_CACHE = new Map();

export function clearUpstreamCache() {
  UP_CACHE.clear();
  PROF_MTIME_CACHE.clear();
}

export function findUpstreamContract(idOrRes, cwd, fs, path) {
  let cur = path.resolve(cwd);
  let upDir = '';
  while (true) {
    const cand = path.join(cur, '.drift', 'upstream');
    if (fs.existsSync(cand) && fs.statSync(cand).isDirectory()) {
      upDir = cand;
      break;
    }
    const p = path.dirname(cur);
    if (p === cur) break;
    cur = p;
  }
  if (!upDir) return null;
  let idx = UP_CACHE.get(upDir);
  if (!idx) {
    const byKey = new Map();
    for (const fn of fs.readdirSync(upDir).sort()) {
      if (!fn.endsWith('.json')) continue;
      const fp = path.join(upDir, fn);
      try {
        const doc = JSON.parse(fs.readFileSync(fp, 'utf8').replace(/^\uFEFF/u, ''));
        const area = isStr(doc?.area) ? doc.area : '';
        const list = doc?.kind === 'boundary' && Array.isArray(doc.contracts)
          ? doc.contracts
          : (isObj(doc) && isStr(doc.id) ? [doc] : []);
        for (const c of list) {
          if (!isObj(c)) continue;
          const hit = { view: c, file: fp };
          if (isStr(c.id) && !byKey.has(c.id)) byKey.set(c.id, hit);
          if (area && isStr(c.id) && !byKey.has(`${area}:${c.id}`)) byKey.set(`${area}:${c.id}`, hit);
          const resList = [
            ...(Array.isArray(c.scope?.out) ? c.scope.out : []),
            ...(Array.isArray(c.scope?.writes) ? c.scope.writes : []),
            ...(Array.isArray(c.scope?.reads) ? c.scope.reads : []),
          ];
          for (const r of resList) {
            const rs = String(r);
            const [base] = rs.split('#', 1);
            if (!byKey.has(rs)) byKey.set(rs, hit);
            if (base && !byKey.has(base)) byKey.set(base, hit);
          }
        }
      } catch {}
    }
    idx = byKey;
    UP_CACHE.set(upDir, idx);
  }
  if (idx.has(idOrRes)) return idx.get(idOrRes);
  const [base] = String(idOrRes).split('#', 1);
  return idx.get(base) || null;
}

function indexTomls(dir, out, fs, path) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const full = path.join(dir, e.name);
    if (e.isDirectory() && !e.isSymbolicLink()) indexTomls(full, out, fs, path);
    else if (e.isFile() && e.name.endsWith('.toml') && !out.has(e.name.slice(0, -5))) out.set(e.name.slice(0, -5), full);
  }
}

export function findTomlInDir(dir, id, tomlDirs, fs, path) {
  if (!fs.existsSync(dir)) return '';
  const direct = path.join(dir, `${id}.toml`);
  if (fs.existsSync(direct) && fs.statSync(direct).isFile()) return direct;
  let idx = tomlDirs.get(dir);
  if (!idx) {
    idx = new Map();
    indexTomls(dir, idx, fs, path);
    tomlDirs.set(dir, idx);
  }
  const cand = idx.get(id) || '';
  return cand && fs.existsSync(cand) ? cand : '';
}

function maxSourceMtime(cur, toml, fs, path) {
  let m = toml && fs.existsSync(toml) ? fs.statSync(toml).mtimeMs : 0;
  const pDir = path.join(cur, '.drift', 'profiles');
  let profMax = PROF_MTIME_CACHE.get(pDir);
  if (profMax === undefined) {
    profMax = 0;
    if (fs.existsSync(pDir) && fs.statSync(pDir).isDirectory()) {
      for (const fn of fs.readdirSync(pDir)) {
        if (fn.endsWith('.toml')) {
          try {
            const pm = fs.statSync(path.join(pDir, fn)).mtimeMs;
            if (pm > profMax) profMax = pm;
          } catch {}
        }
      }
    }
    PROF_MTIME_CACHE.set(pDir, profMax);
  }
  return profMax > m ? profMax : m;
}

export function autoResolveView(id, state, fs, path, execFileSync, readJson, parseJson, targetJson = '') {
  if (!targetJson && state.batch.has(id)) return state.batch.get(id);
  let cur = targetJson ? path.dirname(targetJson) : process.cwd();
  const home = process.env.HOME || process.env.USERPROFILE || '';
  const lCli = home ? path.join(home, '.local', 'bin', 'drift') : '';
  const appD = process.env.LOCALAPPDATA || (home ? path.join(home, 'AppData', 'Local') : '');
  const wCli = appD ? path.join(appD, 'Programs', 'drift', 'bin', 'drift.exe') : '';
  while (true) {
    const rc = targetJson
      ? (fs.existsSync(targetJson) ? targetJson : '')
      : ([
        path.join('.drift', 'resolved', `${id}.json`),
        path.join('.drift', 'views', `${id}.json`),
        path.join('.drift-work', 'resolved', `${id}.json`),
        path.join('target', 'drift', 'resolved', `${id}.json`),
      ].map((r) => path.join(cur, r)).find((c) => fs.existsSync(c)) || '');
    const cDir = path.join(cur, '.drift', 'contracts');
    const toml = fs.existsSync(cDir) ? findTomlInDir(cDir, id, state.tomlDirs, fs, path) : '';
    const srcMtime = toml ? maxSourceMtime(cur, toml, fs, path) : 0;
    if (targetJson && !toml) {
      if (fs.existsSync(path.join(cur, '.drift')) || fs.existsSync(path.join(cur, '.git'))) return null;
      const p = path.dirname(cur);
      if (p === cur) return null;
      cur = p;
      continue;
    }
    const isViewsDir = Boolean(targetJson && /[/\\]\.drift[/\\](?:views|resolved)[/\\][^/\\]+\.json$/u.test(targetJson));
    if (rc && (!toml || (targetJson && !isViewsDir ? fs.statSync(rc).mtimeMs >= srcMtime : fs.statSync(rc).mtimeMs > srcMtime))) {
      return readJson(rc);
    }
    if (toml) {
      const envCli = (process.env.DRIFT_CLI || '').trim();
      const ck = `${envCli}\u0000${cur}`;
      const bCli = path.join(cur, '.build', 'drift');
      const clis = [];
      for (const c of [
        state.cachedCliKey === ck ? state.cachedCliPath : '',
        envCli,
        fs.existsSync(bCli) ? bCli : '',
        'drift',
        lCli && fs.existsSync(lCli) ? lCli : '',
        wCli && fs.existsSync(wCli) ? wCli : '',
      ]) {
        if (c && !clis.includes(c)) clis.push(c);
      }
      const warm = !targetJson && state.warmed.has(cDir);
      if (!targetJson) state.warmed.add(cDir);
      for (const cli of clis) {
        if (warm) {
          let tmp = '';
          try {
            tmp = fs.mkdtempSync(path.join(process.env.TMPDIR || '/tmp', 'drift-resolved-'));
            execFileSync(cli, ['show', cDir, '--out', tmp], { cwd: cur, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
            for (const fn of fs.readdirSync(tmp)) {
              if (fn.endsWith('.json')) {
                const d = readJson(path.join(tmp, fn));
                const pf = path.join(tmp, '.plans', `${fn.slice(0, -5)}.plan.json`);
                if (fs.existsSync(pf)) {
                  try { Object.defineProperty(d, '__plan', { value: readJson(pf), enumerable: false, configurable: true }); } catch {}
                }
                state.batch.set(fn.slice(0, -5), d);
              }
            }
            if (state.batch.has(id)) {
              state.cachedCliKey = ck;
              state.cachedCliPath = cli;
              return state.batch.get(id);
            }
          } catch {} finally {
            if (tmp) {
              try { fs.rmSync(tmp, { recursive: true, force: true }); } catch {}
            }
          }
        }
        try {
          const out = execFileSync(cli, ['show', toml, '--as', 'json'], { cwd: cur, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
          state.cachedCliKey = ck;
          state.cachedCliPath = cli;
          const parsed = parseJson(out);
          const rDir = path.join(cur, '.drift', 'resolved');
          const vDir = path.join(cur, '.drift', 'views');
          const wDir = path.join(cur, '.drift-work', 'resolved');
          if (!targetJson && !rc && !fs.existsSync(rDir) && !fs.existsSync(vDir) && !fs.existsSync(wDir)) {
            try { fs.mkdirSync(wDir, { recursive: true }); } catch {}
          }
          const tgt = targetJson || rc || (fs.existsSync(rDir) ? path.join(rDir, `${id}.json`) : (fs.existsSync(vDir) ? path.join(vDir, `${id}.json`) : (fs.existsSync(wDir) ? path.join(wDir, `${id}.json`) : '')));
          if (tgt) {
            try {
              fs.mkdirSync(path.dirname(tgt), { recursive: true });
              fs.writeFileSync(tgt, out, 'utf8');
            } catch {}
          }
          return parsed;
        } catch {}
      }
    }
    if (rc) return readJson(rc);
    if (targetJson && (fs.existsSync(path.join(cur, '.drift')) || fs.existsSync(path.join(cur, '.git')))) return null;
    const parent = path.dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  return targetJson ? null : (findUpstreamContract(id, process.cwd(), fs, path)?.view || null);
}

export async function runCaseMutants(mutCfg, mutOut, ctx, contract, passed, elapsed, performance, isAssertErr, withMutation, makeCtx, fn, fs) {
  if (!mutCfg) return;
  const targets = ctx.cases.flatMap((cid) => mutCfg.byCase.get(`${contract}\u0000${cid}`) || []);
  if (!targets.length) return;
  const budget = Math.max(250 * targets.length, 20 * targets.length * elapsed);
  const mutStart = performance.now();
  let over = false;
  const lines = [];
  for (const target of targets) {
    let outcome = 'inconclusive';
    if (!passed || over || (performance.now() - mutStart) > budget) {
      if (passed) over = true;
    } else {
      let thrown = null;
      let failed = false;
      try {
        await withMutation(target, async () => {
          await fn(makeCtx(target));
        });
      } catch (e) {
        failed = true;
        thrown = e;
      }
      if ((performance.now() - mutStart) > budget) over = true;
      else if (!failed) outcome = 'survived';
      else if (isAssertErr(thrown)) outcome = 'killed';
    }
    lines.push(JSON.stringify({
      manifest: mutCfg.manifestId,
      contract: target.contract,
      digest: target.digest,
      mutant: target.id,
      case: target.case,
      outcome,
      control: passed ? 'passed' : 'failed',
    }));
  }
  fs.appendFileSync(mutOut, lines.join('\n') + '\n', 'utf8');
}
