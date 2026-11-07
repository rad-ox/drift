// Zero-dependency Node.js / TypeScript / Vitest / Jest bridge for DRIFT.
import { AsyncLocalStorage } from 'node:async_hooks';
import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import {
  applyMutation,
  captureSurfaceView,
  checkProjectedLeaf,
  checkViewTable,
  cloneJson,
  escapePointer,
  expandDomain,
  invokeVerifiedCallback,
  isAssertErr,
  isObj,
  isStr,
  mergePriorInventory,
  parseMutationSegments,
  resolveSelectedFiles,
  runDriftCli,
  throwAssertionError as aErr,
  throwError as err,
  writePointer,
} from './drift_checks.mjs';
import {
  autoResolveView,
  clearUpstreamCache,
  extractProjectionMap,
  findUpstreamContract,
  resolveStubCaseId,
  runCaseMutants,
  synthesizeViewOutput,
  synthesizeViewVariants,
} from './drift_upstream.mjs';

export { captureSurfaceView, expandDomain };

const VIEWS = new Map();
const METRICS = new Map();
const DIGESTS = new Map();
const TOML_DIRS = new Map();
const WARMED = new Set();
const BATCH = new Map();
const INVENTORIES = new Map();
const DERIVED = new Map();
const DISCOVERED_CLASSES = new Set();
const DISCOVERED_TESTS = new Set();
const CTX_ALS = new AsyncLocalStorage();
const MUT_ALS = new AsyncLocalStorage();
let envCache = null;
let selectionCache = null;
let fastContractCache = null;
let mutationCache = null;
let eventsDirCache = null;
let shardPath = null;
let mutationShardPath = null;
let shardSeq = 0;
let exitHook = false;

const ENV_KEYS = ['adapter', 'config', 'deps', 'drift', 'policy', 'runner', 'toolchain'];
const stripBom = (t) => (t.charCodeAt(0) === 0xfeff ? t.slice(1) : t);
const parseJson = (s) => JSON.parse(stripBom(s));
const isValidSnapshot = (v) => /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/u.test(v);
const readJson = (p) => parseJson(fs.readFileSync(p, 'utf8'));

function normalizeBytes(buf) {
  let crlf = false;
  for (let i = 0; i < buf.length; i += 1) {
    if (buf[i] === 0) return buf;
    if (buf[i] === 13 && buf[i + 1] === 10) crlf = true;
  }
  if (!crlf) return buf;
  const out = Buffer.allocUnsafe(buf.length);
  let pos = 0;
  for (let i = 0; i < buf.length; i += 1) {
    if (buf[i] === 13 && buf[i + 1] === 10) {
      out[pos++] = 10;
      i += 1;
    } else {
      out[pos++] = buf[i];
    }
  }
  return out.subarray(0, pos);
}

const hashBuf = (buf) => `sha256:${crypto.createHash('sha256').update(normalizeBytes(buf)).digest('hex')}`;

function inputDigest(abs, pre = null) {
  const st = fs.statSync(abs);
  const sig = `${st.mtimeMs}:${st.size}`;
  const cached = DIGESTS.get(abs);
  if (pre === null && st.size > 65536 && cached && cached.sig === sig) return cached.hex;
  const hex = hashBuf(pre ?? fs.readFileSync(abs));
  DIGESTS.set(abs, { sig, hex });
  return hex;
}

function resolveEnv() {
  const raw = (process.env.DRIFT_ENV || '').trim();
  const pk = (process.env.DRIFT_PROOF_KEY || '').trim();
  if (!raw && pk !== '1' && pk !== 'true') return null;
  const key = `${pk}\u0000${raw}`;
  if (envCache && envCache.key === key) return envCache.value;
  const base = {
    adapter: 'drift.mjs@0.3.1',
    config: 'default',
    deps: 'none',
    drift: '0.3.1',
    policy: 'core@1',
    runner: 'node:test',
    toolchain: `node@${process.versions.node}`,
  };
  if (raw) {
    const parsed = parseJson(raw);
    if (!isObj(parsed)) err('DRIFT_ENV must be a JSON object');
    for (const [k, v] of Object.entries(parsed)) {
      if (!ENV_KEYS.includes(k) || !isStr(v) || !v.trim()) err(`invalid DRIFT_ENV key "${k}"`);
      base[k] = v.trim();
    }
  }
  return (envCache = { key, value: base }).value;
}

function flushInventory(out, inv) {
  inv.scheduled = false;
  if (!inv.dirty) return;
  inv.dirty = false;
  mergePriorInventory(out, inv, out === shardPath, fs, path, process.cwd());
  const snapshot = (process.env.DRIFT_SNAPSHOT || '').trim();
  if (snapshot && !isValidSnapshot(snapshot)) err(`invalid DRIFT_SNAPSHOT "${snapshot}"`);
  const packRef = (process.env.DRIFT_PACK_REF || '').trim();
  const touched = [...new Set((process.env.DRIFT_TOUCHED || '').split(/[\n,]+/).map((s) => s.trim()).filter(Boolean))].sort();
  const inputs = {};
  for (const tid of [...inv.inputs.keys()].sort()) {
    const fm = inv.inputs.get(tid);
    if (fm && fm.size) {
      inputs[tid] = Object.fromEntries([...fm.keys()].sort().map((fp) => [fp, fm.get(fp)]));
    }
  }
  const env = resolveEnv();
  const sidecar = {
    version: 1,
    classes: [...inv.classes].sort(),
    tests: [...inv.tests].sort(),
    ...(snapshot ? { snapshot } : {}),
    ...(packRef ? { pack_ref: packRef } : {}),
    ...(touched.length ? { touched } : {}),
    ...(Object.keys(inputs).length ? { inputs } : {}),
    ...(env ? { env } : {}),
  };
  fs.writeFileSync(out.slice(0, -6) + '.meta.json', JSON.stringify(sidecar) + '\n', 'utf8');
}

function flushAllInventories() {
  for (const [out, inv] of INVENTORIES.entries()) flushInventory(out, inv);
}

const AUTO_STATE = { batch: BATCH, tomlDirs: TOML_DIRS, warmed: WARMED, cachedCliKey: '', cachedCliPath: '' };

function autoResolve(id, targetJson = '') {
  return autoResolveView(id, AUTO_STATE, fs, path, execFileSync, readJson, parseJson, targetJson);
}

function resolveStubContract(idOrRes, caseId, base = {}) {
  const up = findUpstreamContract(idOrRes, process.cwd(), fs, path);
  const curCtx = CTX_ALS.getStore();
  if (up && curCtx && up.file && idOrRes !== curCtx.contractId) curCtx.recordInput(up.file);
  const v = up ? up.view : loadView(idOrRes);
  if (curCtx && (idOrRes === curCtx.contractId || (!up && v.id === curCtx.contractId))) {
    curCtx.recordInput(`.drift/self-stub/${curCtx.contractId}`, 'sha256:self-stub');
  }
  const resolvedId = resolveStubCaseId(v, idOrRes, caseId, base, err);
  return [v, resolvedId];
}

export function buildStub(idOrRes, caseId, base = {}) {
  const [v, resolvedId] = resolveStubContract(idOrRes, caseId, base);
  return synthesizeViewOutput(v, resolvedId, base);
}

export function buildStubVariants(idOrRes, caseId, base = {}) {
  const [v, resolvedId] = resolveStubContract(idOrRes, caseId, base);
  return synthesizeViewVariants(v, resolvedId, base);
}

export function verifyStub(idOrRes, caseId, payload) {
  const [v, resolvedId] = resolveStubContract(idOrRes, caseId);
  const proj = extractProjectionMap(v, 'then');
  for (const [k, exp] of Object.entries(v.cases[resolvedId].then || {})) {
    checkProjectedLeaf(v.id || idOrRes, resolvedId, k, exp, payload, proj, null, true, 'no projection for');
  }
  return true;
}

function loadView(id) {
  if (VIEWS.has(id)) return VIEWS.get(id);
  const res = process.env.DRIFT_RESOLVED || '';
  if (!res) {
    const d = autoResolve(id);
    if (!d) err(`DRIFT_RESOLVED is not set and contract "${id}" could not be auto-resolved from .drift/`);
    if (d.id !== id) err(`resolved view for "${id}" has id "${d.id}"`);
    return VIEWS.set(id, d).get(id);
  }
  const f = res.endsWith('.json') ? res : path.join(res, `${id}.json`);
  if (!res.endsWith('.json')) {
    const synced = autoResolve(id, path.resolve(f));
    if (synced && synced.id === id) return VIEWS.set(id, synced).get(id);
  }
  if (!fs.existsSync(f)) err(`contract "${id}" was not found at ${f}`);
  const d = readJson(f);
  if (d.id !== id) err(`resolved view ${f} has id "${d.id}", expected "${id}"`);
  return VIEWS.set(id, d).get(id);
}

function loadSelection() {
  if (selectionCache !== null) return selectionCache;
  const f = process.env.DRIFT_SELECT || '';
  if (!f || !fs.existsSync(f)) {
    return (selectionCache = { all: true, tests: new Set(), byC: new Map(), tagged: new Set() });
  }
  const raw = readJson(f);
  const byC = new Map();
  const tagged = new Set();
  for (const c of Array.isArray(raw.contracts) ? raw.contracts : (isStr(raw.contract) ? [raw] : [])) {
    const rep = Array.isArray(c.replayed_cases) ? c.replayed_cases : [];
    if (c.code_hit === true || (c.resource_hit === true && !rep.length)) tagged.add(c.contract);
    byC.set(c.contract, new Set([...(c.cases || []).filter((ch) => ch.change !== 'removed').map((ch) => ch.case), ...rep]));
  }
  return (selectionCache = {
    all: Boolean(raw.all),
    tests: new Set(Array.isArray(raw.tests) ? raw.tests : []),
    byC,
    tagged,
  });
}

export function shouldRun(contractId, testId, cases = []) {
  recordDiscovery(testId);
  const fc = (process.env.DRIFT_CONTRACTS || '').trim();
  if (fc) {
    if (!fastContractCache || fastContractCache.raw !== fc) {
      fastContractCache = { raw: fc, set: new Set(fc.split(',').map((x) => x.trim()).filter(Boolean)) };
    }
    if (!fastContractCache.set.has(contractId)) return false;
  }
  const s = loadSelection();
  if (s.all || s.tests.has(testId) || s.tagged.has(contractId)) return true;
  const ch = s.byC.get(contractId);
  return Boolean(ch && cases.some((c) => ch.has(c)));
}

function discoverEventsDir() {
  if (eventsDirCache !== null) return eventsDirCache;
  let cur = process.cwd();
  let areaRoot = '';
  while (true) {
    for (const sub of ['.drift', '.drift-work']) {
      const c = path.join(cur, sub, 'events');
      if (fs.existsSync(c) && fs.statSync(c).isDirectory()) return (eventsDirCache = c);
    }
    if (fs.existsSync(path.join(cur, '.drift', 'config.toml')) || fs.existsSync(path.join(cur, '.drift', 'contracts'))) {
      areaRoot = cur;
      break;
    }
    const p = path.dirname(cur);
    if (p === cur) break;
    cur = p;
  }
  return (eventsDirCache = (areaRoot && !(process.env.DRIFT_RESOLVED || '').trim()) ? path.join(areaRoot, '.drift-work', 'events') : '');
}

function resolveEventsFile() {
  const tgt = process.env.DRIFT_EVENTS || discoverEventsDir();
  if (!tgt) return '';
  if (tgt.endsWith('.jsonl')) {
    fs.mkdirSync(path.dirname(tgt), { recursive: true });
    return tgt;
  }
  if (!shardPath) {
    fs.mkdirSync(tgt, { recursive: true });
    shardPath = path.join(tgt, `${String(Date.now()).padStart(13, '0')}-${process.pid}-${++shardSeq}.jsonl`);
  }
  return shardPath;
}

function ensureInventory(out) {
  let inv = INVENTORIES.get(out);
  if (!inv) {
    inv = { classes: new Set(DISCOVERED_CLASSES), tests: new Set(DISCOVERED_TESTS), inputs: new Map(), dirty: true, scheduled: false };
    INVENTORIES.set(out, inv);
  }
  return inv;
}

function writeEvent(ev) {
  const out = resolveEventsFile();
  if (out) {
    ensureInventory(out);
    recordDiscovery(ev.test, out);
    fs.appendFileSync(out, JSON.stringify(ev) + '\n', 'utf8');
  }
}

function recordDiscovery(testId, activeOut = '') {
  const tgt = activeOut || process.env.DRIFT_EVENTS || discoverEventsDir();
  if (!tgt) return;
  const h = isStr(testId) ? testId.indexOf('#') : -1;
  const cls = h > 0 ? testId.slice(0, h) : '';
  const mth = (h > 0 ? testId.slice(h + 1) : '').split('[', 1)[0];
  if (!cls || !mth || /[\s/\\#[\]]/u.test(cls) || /[\s#[\]]/u.test(mth)) {
    err(`DRIFT_EVENTS requires a test id in Class#method form: "${testId}"`);
  }
  const canon = `${cls}#${mth}`;
  DISCOVERED_CLASSES.add(cls);
  DISCOVERED_TESTS.add(canon);
  const out = activeOut || shardPath || (tgt.endsWith('.jsonl') && fs.existsSync(tgt) ? tgt : '');
  if (!out) return;
  const inv = ensureInventory(out);
  const before = inv.classes.size + inv.tests.size;
  inv.classes.add(cls);
  inv.tests.add(canon);
  if (before === inv.classes.size + inv.tests.size && !inv.dirty && fs.existsSync(out.slice(0, -6) + '.meta.json')) return;
  inv.dirty = true;
  if (!exitHook) {
    exitHook = true;
    process.once('exit', flushAllInventories);
  }
  if (!inv.scheduled) {
    inv.scheduled = true;
    queueMicrotask(() => flushInventory(out, inv));
  }
}

function loadMutants() {
  const file = (process.env.DRIFT_MUTANTS || '').trim();
  const outputTarget = (process.env.DRIFT_MUTATION_EVENTS || '').trim();
  if (!file && !outputTarget) return null;
  if (!file || !outputTarget) err('DRIFT_MUTANTS and DRIFT_MUTATION_EVENTS must be set together');
  if (mutationCache && mutationCache.file === file && mutationCache.outT === outputTarget) return mutationCache;
  const bytes = fs.readFileSync(file);
  const manifest = parseJson(bytes.toString('utf8'));
  if (manifest.version !== 1 || !Array.isArray(manifest.contracts)) err(`invalid mutation manifest ${file}`);
  const manifestId = `sha256:${crypto.createHash('sha256').update(bytes).digest('hex')}`;
  const byCase = new Map();
  for (const c of manifest.contracts) {
    for (const m of c.mutants || []) {
      const k = `${c.id}\u0000${m.case}`;
      const isWhen = isStr(m.path) && m.path.startsWith(`/cases/${escapePointer(m.case)}/when/`);
      if (!byCase.has(k)) byCase.set(k, []);
      byCase.get(k).push({
        id: m.id,
        contract: c.id,
        digest: c.digest,
        case: m.case,
        path: m.path,
        after: m.after,
        isWhen,
        segments: parseMutationSegments(c.id, m.case, m.path, isWhen ? 'when' : 'then'),
      });
    }
  }
  return (mutationCache = { file, outT: outputTarget, manifestId, byCase });
}

function resolveMutationFile(outputTarget) {
  if (outputTarget.endsWith('.jsonl')) {
    fs.mkdirSync(path.dirname(outputTarget), { recursive: true });
    return outputTarget;
  }
  if (!mutationShardPath || !mutationShardPath.startsWith(outputTarget)) {
    fs.mkdirSync(outputTarget, { recursive: true });
    mutationShardPath = path.join(outputTarget, 'results.jsonl');
  }
  return mutationShardPath;
}

export function mutationDepth() {
  return (MUT_ALS.getStore() || []).length;
}

export function observe(rec) {
  const tgt = (process.env.DRIFT_OBSERVE || '').trim();
  if (!tgt || !isObj(rec) || !isObj(rec.then)) return false;
  const out = tgt.endsWith('.jsonl') ? tgt : path.join(tgt, `trace-${process.pid}.jsonl`);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const row = {
    kind: 'trace',
    version: 1,
    ...(isStr(rec.contract) && rec.contract ? { contract: rec.contract } : {}),
    ...(isStr(rec.case) && rec.case ? { case: rec.case } : {}),
    ...(isStr(rec.test) && rec.test ? { test: rec.test } : {}),
    ...(Array.isArray(rec.at) && rec.at.length ? { at: rec.at } : {}),
    when: isObj(rec.when) ? rec.when : {},
    then: rec.then,
  };
  fs.appendFileSync(out, JSON.stringify(row) + '\n', 'utf8');
  return true;
}

export async function withMutation(target, fn) {
  if (!isObj(target) || !isStr(target.contract) || !isStr(target.case) || !isStr(target.path)) {
    err('invalid mutation target');
  }
  return MUT_ALS.run([...(MUT_ALS.getStore() || []), target], fn);
}

function activeMutationFor(contractId, cases) {
  const stack = MUT_ALS.getStore() || [];
  for (let i = stack.length - 1; i >= 0; i -= 1) {
    const m = stack[i];
    if (m && m.contract === contractId && cases.includes(m.case)) return m;
  }
  return null;
}

export class DriftContext {
  constructor(contractId, testId, cases, level, mutationOverride = null) {
    if (!Array.isArray(cases) || !cases.length) {
      err(`@DriftCase for "${testId}" requires at least one case id`);
    }
    this.contractId = contractId;
    this.testId = testId;
    this.cases = [...cases];
    this.level = level || 'unit';
    const effMut = mutationOverride ?? activeMutationFor(contractId, this.cases);
    this.view = loadView(contractId);
    this.mutationOverride = effMut;
    const m = effMut;
    const isW = Boolean(
      m && m.contract === contractId && (m.isWhen === true || (isStr(m.path) && m.path.startsWith(`/cases/${escapePointer(m.case)}/when/`))),
    );
    this.mutatedWhen = isW
      ? applyMutation(this.view.cases[m.case]?.when || {}, contractId, m.case, m.path, m.after, 'when', m.segments || null)
      : null;
    this.mutatedThen = (m && m.contract === contractId && !isW)
      ? applyMutation(this.view.cases[m.case]?.then || {}, contractId, m.case, m.path, m.after, 'then', m.segments || null)
      : null;
    this.reads = new Map();
    this.inputFiles = new Map();
    for (const c of this.cases) {
      if (!this.view.cases || !(c in this.view.cases)) err(`contract "${contractId}" has no case "${c}"`);
      this.reads.set(c, new Set());
    }
  }

  _wt(c) {
    return (this.mutatedWhen && this.mutationOverride.case === c) ? this.mutatedWhen : (this.view.cases[c]?.when || {});
  }

  _tt(c) {
    return (this.mutatedThen && this.mutationOverride.case === c) ? this.mutatedThen : (this.view.cases[c]?.then || {});
  }

  _tag(c) {
    if (!this.reads.has(c)) err(`test "${this.testId}" is not tagged with case "${c}"`);
  }

  when(c, k) {
    this._tag(c);
    const w = this._wt(c);
    if (!(k in w)) err(`case "${c}" has no when.${k}`);
    return w[k];
  }

  findWhen(c, k, fb = undefined) {
    this._tag(c);
    const w = this._wt(c);
    return k in w ? w[k] : fb;
  }

  whenTable(c) {
    this._tag(c);
    return cloneJson(this._wt(c));
  }

  async forEachCase(fn) {
    for (const c of this.cases) {
      await fn(c, this.whenTable(c));
    }
  }

  expect(c, k) {
    this._tag(c);
    const t = this._tt(c);
    if (!(k in t)) err(`case "${c}" has no then.${k}`);
    this.reads.get(c).add(k);
    return t[k];
  }

  findThen(c, k, fb = undefined) {
    this._tag(c);
    const t = this._tt(c);
    if (k in t) {
      this.reads.get(c).add(k);
      return t[k];
    }
    return fb;
  }

  then(c) {
    this._tag(c);
    const seen = this.reads.get(c);
    return new Proxy(this._tt(c), {
      get(tgt, prop, recv) {
        if (isStr(prop) && prop in tgt) seen.add(prop);
        return Reflect.get(tgt, prop, recv);
      },
    });
  }

  recordInput(filePath, pre = null) {
    const isSelf = pre === 'sha256:self-stub';
    const abs = isSelf ? String(filePath) : path.resolve(process.cwd(), String(filePath));
    const relRaw = isSelf ? abs : path.relative(process.cwd(), abs).split(path.sep).join('/');
    const rel = relRaw && !relRaw.startsWith('..') ? relRaw : String(filePath).split(path.sep).join('/');
    const dig = isSelf ? pre : inputDigest(abs, pre);
    if (!this.mutationOverride) {
      if (!isSelf) this.inputFiles.set(abs, { rel, dig });
      const out = resolveEventsFile();
      if (out) {
        recordDiscovery(this.testId, out);
        const inv = INVENTORIES.get(out);
        if (inv) {
          const h = this.testId.indexOf('#');
          const canon = h > 0 ? `${this.testId.slice(0, h)}#${this.testId.slice(h + 1).split('[', 1)[0]}` : this.testId;
          let fm = inv.inputs.get(canon);
          if (!fm) {
            fm = new Map();
            inv.inputs.set(canon, fm);
          }
          if (fm.get(rel) !== dig) {
            fm.set(rel, dig);
            inv.dirty = true;
            if (!inv.scheduled) {
              inv.scheduled = true;
              queueMicrotask(() => flushInventory(out, inv));
            }
          }
        }
      }
    }
    return dig;
  }

  readFixture(filePath, encoding = 'utf8') {
    const raw = fs.readFileSync(path.resolve(process.cwd(), String(filePath)));
    this.recordInput(filePath, raw);
    return encoding ? stripBom(raw.toString(encoding)) : raw;
  }

  async check(caseId, checks) {
    this._tag(caseId);
    const seen = this.reads.get(caseId);
    for (const [k, exp] of Object.entries(this._tt(caseId))) {
      if (!isObj(checks) || !(k in checks)) aErr(`${this.contractId}.${caseId}: no check for then.${k}`);
      const fn = checks[k];
      if (typeof fn === 'function') {
        await invokeVerifiedCallback(fn, this.contractId, caseId, k, exp);
      } else {
        checkProjectedLeaf(this.contractId, caseId, k, exp, checks, {}, this.mutationOverride, false, 'no check for');
      }
      seen.add(k);
    }
  }

  async checkBounds(caseId, domain, checks) {
    this._tag(caseId);
    const samples = expandDomain(domain, false);
    const seen = this.reads.get(caseId);
    const list = [];
    for (const [k, exp] of Object.entries(this._tt(caseId))) {
      const fn = isObj(checks) ? checks[k] : undefined;
      if (typeof fn !== 'function') aErr(`${this.contractId}.${caseId}: no check for then.${k}`);
      list.push([k, exp, fn]);
    }
    for (const s of samples) {
      for (const [k, exp, fn] of list) {
        try {
          await invokeVerifiedCallback(fn, this.contractId, caseId, k, exp, s);
        } catch (e) {
          if (isAssertErr(e) && !String(e.message || '').includes('[counterexample:')) {
            aErr(`${this.contractId}.${caseId}.then.${k} failed [counterexample: ${JSON.stringify(s)}]: ${e.message}`);
          }
          throw e;
        }
      }
    }
    for (const [k] of list) seen.add(k);
  }

  _domSpec(p) {
    const specs = this.view.param_specs;
    if (!isObj(specs)) err(`contract "${this.contractId}" has no param_specs`);
    if (Array.isArray(p)) {
      if (!p.length) err('profile parameter array must not be empty');
      return Object.fromEntries(p.map((k) => {
        if (!isStr(k) || !(k in specs)) err(`contract "${this.contractId}" has no bounded param_specs.${k}`);
        return [k, specs[k]];
      }));
    }
    if (!isStr(p) || !(p in specs)) err(`contract "${this.contractId}" has no bounded param_specs.${p}`);
    return specs[p];
  }

  profileDomain(p) {
    return expandDomain(this._domSpec(p), Boolean(this.mutationOverride));
  }

  async checkProfileBounds(caseId, p, checks) {
    return this.checkBounds(caseId, this._domSpec(p), checks);
  }

  _projMap(side) {
    return extractProjectionMap(this.view, side);
  }

  buildInput(caseId, base = {}) {
    this._tag(caseId);
    const whenProj = this._projMap('when');
    let out = cloneJson(isObj(base) ? base : {});
    for (const [k, v] of Object.entries(this._wt(caseId))) {
      if (k in whenProj) out = writePointer(out, whenProj[k], v);
      else if (isObj(out)) out[k] = cloneJson(v);
    }
    return out;
  }

  buildOutput(caseId, base = {}) {
    this._tag(caseId);
    this.recordInput(`.drift/self-stub/${this.contractId}`, 'sha256:self-stub');
    return synthesizeViewOutput(this.view, caseId, base, this._tt(caseId));
  }

  async checkProjection(caseId, payload, checks = {}) {
    this._tag(caseId);
    const seen = this.reads.get(caseId);
    const proj = this._projMap('then');
    for (const [k, exp] of Object.entries(this._tt(caseId))) {
      if (checks && typeof checks[k] === 'function') {
        await invokeVerifiedCallback(checks[k], this.contractId, caseId, k, exp, payload);
      } else {
        checkProjectedLeaf(this.contractId, caseId, k, exp, payload, proj, this.mutationOverride, true, 'no check or projection for');
      }
      seen.add(k);
    }
  }

  async checkView(caseId, view, checks = {}) {
    this._tag(caseId);
    await checkViewTable(
      this.contractId,
      caseId,
      this._tt(caseId),
      this.reads.get(caseId),
      view,
      checks,
      this.mutationOverride,
      METRICS,
      () => this._projMap('then'),
    );
  }

  fullyReadCases() {
    return this.cases.filter((c) => {
      const keys = Object.keys(this.view.cases[c]?.then || {});
      const seen = this.reads.get(c);
      return keys.length > 0 && seen.size >= keys.length && keys.every((k) => seen.has(k));
    });
  }
}

export function resetDriftCache() {
  flushAllInventories();
  clearUpstreamCache();
  for (const m of [VIEWS, TOML_DIRS, WARMED, BATCH, METRICS, DIGESTS, DERIVED, DISCOVERED_CLASSES, DISCOVERED_TESTS]) {
    m.clear();
  }
  envCache = selectionCache = fastContractCache = mutationCache = eventsDirCache = shardPath = mutationShardPath = null;
}

export function selectFiles(sel = process.env.DRIFT_SELECT || '', rootDir = process.cwd()) {
  const raw = isStr(sel) ? (sel && fs.existsSync(sel) ? readJson(sel) : null) : sel;
  return resolveSelectedFiles(raw, rootDir, fs, path);
}

function extractTestOrigin(t) {
  if (!t || typeof t !== 'object') return ['', ''];
  if (isStr(t.filePath) && t.filePath) {
    return [t.filePath, isStr(t.fullName) && t.fullName ? t.fullName : String(t.name ?? '')];
  }
  if (isStr(t.file) && t.file) {
    const tp = Array.isArray(t.titlePath)
      ? t.titlePath.filter((s) => isStr(s) && s && !/\.(?:spec|test|e2e)\.[A-Za-z0-9]+$/u.test(s))
      : [];
    const title = tp.length ? tp.join(' > ') : String(t.title ?? t.name ?? '');
    return [t.file, title];
  }
  if (isObj(t.task) && isStr(t.task.file?.filepath)) {
    return [t.task.file.filepath, String(t.task.name ?? t.name ?? '')];
  }
  if (isStr(t.testPath) && t.testPath) {
    return [t.testPath, String(t.currentTestName ?? t.name ?? '')];
  }
  return ['', ''];
}

export function testIdOf(t) {
  const [file, name] = extractTestOrigin(t);
  if (!file) {
    err('runDriftCase needs t (pass the node:test TestContext: async (t) => runDriftCase({ ..., t }, ...)) or test ("Class#method")');
  }
  const rel = path.relative(process.cwd(), file);
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) {
    err(`run the tests from the project root or pass test: ${file} is outside ${process.cwd()}`);
  }
  const unsafe = /[\s#[\]]+/gu;
  const cls = rel.split(/[\\/]/u).join('.').replace(unsafe, '_');
  return `${cls}#${name.split(' > ').join('/').replace(unsafe, '_')}`;
}

function derivedTestId(t, contract) {
  const id = testIdOf(t);
  const [file, name] = extractTestOrigin(t);
  const origin = `${file} > ${name}`;
  const key = `${contract}\u0000${id}`;
  const first = DERIVED.get(key);
  if (first === origin) {
    err(`test "${origin}" runs contract ${contract} twice: call runDriftCase once per contract or pass distinct test ids`);
  }
  if (first !== undefined) {
    err(`"${first}" and "${origin}" both map to test id ${id} for contract ${contract}: rename one test or pass test`);
  }
  DERIVED.set(key, origin);
  return id;
}

export async function runDriftCase({ contract, test, t, cases, level = 'unit' } = {}, fn) {
  if (!test) test = derivedTestId(t, contract);
  if (!shouldRun(contract, test, cases)) return 'skipped-by-select';
  let ctx;
  try {
    ctx = new DriftContext(contract, test, cases, level);
  } catch (e) {
    writeEvent({ test, contract, cases, level, outcome: 'failed', read: [] });
    throw e;
  }
  const version = ctx.view.ref || ctx.view.digest || '';
  const mutCfg = loadMutants();
  const start = performance.now();
  let passed = false;
  let controlErr = null;
  try {
    await CTX_ALS.run(ctx, () => fn(ctx));
    for (const [abs, { rel, dig }] of ctx.inputFiles) {
      if (!fs.existsSync(abs)) aErr(`${contract}: recorded input "${rel}" was mutated during test "${test}"`);
      const st = fs.statSync(abs);
      const c = DIGESTS.get(abs);
      const ok = st.size > 65536
        ? Boolean(c && c.sig === `${st.mtimeMs}:${st.size}` && c.hex === dig)
        : hashBuf(fs.readFileSync(abs)) === dig;
      if (!ok) aErr(`${contract}: recorded input "${rel}" was mutated during test "${test}"`);
    }
    passed = true;
  } catch (e) {
    controlErr = e;
  }
  writeEvent({
    test,
    contract,
    cases: ctx.cases,
    level: ctx.level,
    outcome: passed ? 'passed' : 'failed',
    read: ctx.fullyReadCases(),
    ...(version ? { digest: version } : {}),
  });
  const elapsed = Math.max(1, performance.now() - start);
  if (mutCfg) {
    await runCaseMutants(
      mutCfg,
      resolveMutationFile(mutCfg.outT),
      ctx,
      contract,
      passed,
      elapsed,
      performance,
      isAssertErr,
      withMutation,
      (target) => new DriftContext(contract, test, cases, level, target),
      fn,
      fs,
    );
  }
  if (!passed) throw controlErr;
  return 'passed';
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(runDriftCli(process.argv.slice(2), execFileSync, fs, path, process));
}


