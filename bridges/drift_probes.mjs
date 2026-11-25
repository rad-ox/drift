// Reusable observable behavioral probes for the DRIFT JavaScript bridge.
import { isFinNum, isObj, isStr, sidecarHead, throwAssertionError as fail, valuesEqual } from './drift_checks.mjs';

const DEFAULT_VOLATILE_KEYS = new Set(['request_id', 'timestamp', 'trace_id', 'audit_id']);
const DEFAULT_ALLOWED_SECOND_WRITES = new Set(['AUDIT_LOG', 'audit_log', 'METRICS', 'metrics']);
const FRAME_ENTRY_KEYS = new Set(['writes', 'operations', 'events', 'before', 'after', 'observed']);

export function isFrameMetadataEnvelope(v) {
  if (!isObj(v)) return false;
  const entries = Object.values(v);
  if (!entries.length) return true;
  return entries.every((e) => (typeof e === 'number' && Number.isSafeInteger(e) && e >= 0)
    || (isObj(e) && Object.keys(e).every((k) => FRAME_ENTRY_KEYS.has(k))));
}

export function requiredProbesOf(view, caseId) {
  const cProbes = view?.cases?.[caseId]?.probes;
  const rProbes = view?.requires?.probes;
  const out = new Set();
  for (const src of [cProbes, rProbes]) {
    if (Array.isArray(src)) for (const p of src) if (isStr(p) && p.trim()) out.add(p.trim());
  }
  return [...out];
}

export function hasKeyRecursive(val, fk, isRoot = true, depth = 0) {
  if (depth > 64) {
    fail('observation.incomplete: max_depth_exceeded (> 64)');
  }
  if (Array.isArray(val)) {
    return val.some((item) => hasKeyRecursive(item, fk, false, depth + 1));
  }
  if (val !== null && typeof val === 'object') {
    const proto = Object.getPrototypeOf(val);
    if (proto !== null && proto !== Object.prototype) {
      fail('observation.incomplete: non_traversable_object');
    }
    if (val._truncated === true || val.__truncated__ === true) {
      fail('observation.incomplete: truncated_capture');
    }
  }
  if (!isObj(val)) return false;
  if (Object.hasOwn(val, fk)) {
    if (!isRoot || fk === '_frame' || !isFrameMetadataEnvelope(val._frame)) return true;
    if (fk !== '_frame') return true;
  }
  for (const [k, v] of Object.entries(val)) {
    if (isRoot && k === '_frame' && fk !== '_frame' && isFrameMetadataEnvelope(v)) continue;
    if (hasKeyRecursive(v, fk, false, depth + 1)) return true;
  }
  return false;
}

function unverifiedOrThrow(ctx, caseId, strict, reason, detail) {
  ctx?.reads?.get(caseId)?.clear();
  if (ctx && !(ctx.unobservedCases instanceof Set)) ctx.unobservedCases = new Set();
  ctx?.unobservedCases?.add(caseId);
  if (strict) {
    fail(`${ctx.contractId}.${caseId}: ${reason}: ${detail}`);
  }
  return { observed: false, reason };
}

export async function runIdempotencyProbe(ctx, caseId, obs, runProjectionFn) {
  ctx._tag(caseId);
  const pfx = `${ctx.contractId}.${caseId}`, strict = !isObj(obs) || obs.strict !== false;
  if (!isObj(obs)) return unverifiedOrThrow(ctx, caseId, strict, 'idempotency.unobserved', 'unobserved');
  const hasState = obs.stateAfterFirst !== undefined && obs.stateAfterSecond !== undefined;
  const sw = isObj(obs.secondWrites) ? obs.secondWrites : null;
  if (hasState && !valuesEqual(obs.stateAfterFirst, obs.stateAfterSecond)) fail(`${pfx}: idempotency.domain_state_mutated`);
  if (sw) {
    const a2 = new Set(Array.isArray(obs.allowedSecondWrites) ? obs.allowedSecondWrites.map(String) : DEFAULT_ALLOWED_SECOND_WRITES);
    for (const [res, wv] of Object.entries(sw)) {
      if (a2.has(res) || a2.has(res.split('#')[0])) continue;
      const c = Array.isArray(wv) ? wv.length : Number(wv);
      if (!Number.isSafeInteger(c) || c !== 0) fail(`${pfx}: idempotency.duplicate_write on "${res}": ${c}`);
    }
  }
  if (isObj(obs.first) && isObj(obs.second)) {
    const vol = new Set(Array.isArray(obs.volatileKeys) ? obs.volatileKeys.map(String) : DEFAULT_VOLATILE_KEYS);
    for (const k of Object.keys(obs.first)) {
      if (!vol.has(k) && k !== '_frame' && k in obs.second && !valuesEqual(obs.first[k], obs.second[k])) fail(`${pfx}: idempotency.response_diverged on "${k}"`);
    }
  }
  if (obs.observed === false || (!hasState && !sw)) return unverifiedOrThrow(ctx, caseId, strict, 'idempotency.unobserved', 'unobserved');
  if (obs.first !== undefined && typeof runProjectionFn === 'function') await runProjectionFn(ctx, caseId, obs.first, isObj(obs.checks) ? obs.checks : {});
  ctx?.reads?.get(caseId)?.add('@probe:idempotency');
  return { observed: true, reason: '' };
}

export function runSeamProbe(ctx, caseId, obs) {
  ctx._tag(caseId);
  const pfx = `${ctx.contractId}.${caseId}`, strict = !isObj(obs) || obs.strict !== false;
  if (!isObj(obs)) return unverifiedOrThrow(ctx, caseId, strict, 'seam.unobserved', 'unobserved');
  const hasR = 'retryable' in obs || 'maxAttempts' in obs, hasT = obs.timedOut === true, hasQ = 'maxQueries' in obs, isInt = Number.isSafeInteger;
  if (hasR && isInt(obs.attempts) && obs.attempts > 0) {
    if (obs.retryable === false && obs.attempts > 1) fail(`${pfx}: seam.non_retryable_retried`);
    if (obs.retryable === true && obs.attempts < 2) fail(`${pfx}: seam.retry_missing`);
    if ('maxAttempts' in obs && (!isInt(obs.maxAttempts) || obs.attempts > obs.maxAttempts)) fail(`${pfx}: seam.max_attempts_exceeded`);
  }
  if (hasT && isInt(obs.lateWrites) && obs.lateWrites > 0) fail(`${pfx}: seam.timeout_late_write`);
  if (hasQ && isInt(obs.queries) && isInt(obs.maxQueries) && obs.queries > obs.maxQueries) fail(`${pfx}: seam.query_budget_exceeded`);
  if (obs.observed === false || (!hasR && !hasT && !hasQ) || (hasR && (!isInt(obs.attempts) || obs.attempts <= 0))) return unverifiedOrThrow(ctx, caseId, strict, 'seam.unobserved', 'unobserved');
  if (hasT && (!isInt(obs.lateWrites ?? 0) || (obs.lateWrites ?? 0) < 0)) return unverifiedOrThrow(ctx, caseId, strict, 'seam.unobserved', 'invalid lateWrites');
  if (hasQ && (!isInt(obs.queries) || obs.queries < 0 || !isInt(obs.maxQueries) || obs.maxQueries < 0)) return unverifiedOrThrow(ctx, caseId, strict, 'queries.unobserved', 'unobserved');
  ctx?.reads?.get(caseId)?.add('@probe:seam');
  return { observed: true, reason: '' };
}

export function runRollbackProbe(ctx, caseId, obs) {
  ctx._tag(caseId);
  const pfx = `${ctx.contractId}.${caseId}`, strict = !isObj(obs) || obs.strict !== false;
  if (isObj(obs) && obs.before !== undefined && obs.after !== undefined) {
    const res = isStr(obs.resource) && obs.resource ? obs.resource : 'primary';
    if (!valuesEqual(obs.before, obs.after) && obs.compensated !== true) fail(`${pfx}: rollback.dirty_partial_write on "${res}"`);
  }
  if (!isObj(obs) || obs.observed === false || obs.before === undefined || obs.after === undefined) return unverifiedOrThrow(ctx, caseId, strict, 'rollback.unobserved', 'unobserved');
  ctx?.reads?.get(caseId)?.add('@probe:rollback');
  return { observed: true, reason: '' };
}

export function checkBolaVariantPair(pfx, variant) {
  if (!isObj(variant)) return false;
  const b = isObj(variant.bola) ? variant.bola : variant;
  if (!('actor_owner' in b) && !('resource_owner' in b)) return false;
  const a = isStr(b.actor_owner) ? b.actor_owner.trim() : '', o = isStr(b.resource_owner) ? b.resource_owner.trim() : '';
  if (!a || !o || a === o) fail(`${pfx}: bola.invalid_fixture`);
  return true;
}

function containsStringLeaf(val, needle, depth = 0) {
  if (depth > 64) fail('observation.incomplete: max_depth_exceeded (> 64)');
  if (isStr(val)) return val.includes(needle);
  if (Array.isArray(val)) return val.some((x) => containsStringLeaf(x, needle, depth + 1));
  if (isObj(val)) {
    if (val._truncated === true || val.__truncated__ === true) fail('observation.incomplete: truncated_capture');
    return Object.values(val).some((v) => containsStringLeaf(v, needle, depth + 1));
  }
  return false;
}

export function runLogSinkProbe(ctx, caseId, obs) {
  ctx._tag(caseId);
  const pfx = `${ctx.contractId}.${caseId}`, strict = !isObj(obs) || obs.strict !== false;
  if (!isObj(obs)) return unverifiedOrThrow(ctx, caseId, strict, 'log_sink.unobserved', 'unobserved');
  const rs = Array.isArray(obs.secretValues) ? obs.secretValues : (Array.isArray(obs.secret_values) ? obs.secret_values : []);
  const sec = rs.filter((s) => isStr(s) && s.trim() !== ''), logs = obs.logLines ?? obs.log_lines;
  const hl = Array.isArray(logs) || isStr(logs), hp = obs.payload !== undefined && obs.payload !== null;
  for (const s of sec) {
    if ((hl && containsStringLeaf(logs, s)) || (hp && containsStringLeaf(obs.payload, s))) fail(`${pfx}: log_sink.secret_leaked`);
  }
  if (obs.observed === false || !sec.length || (!hl && !hp)) return unverifiedOrThrow(ctx, caseId, strict, 'log_sink.unobserved', 'unobserved');
  ctx?.reads?.get(caseId)?.add('@probe:log_sink');
  return { observed: true, reason: '' };
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

export function maxSourceMtime(cur, toml, fs, path) {
  let m = toml && fs.existsSync(toml) ? fs.statSync(toml).mtimeMs : 0;
  const pDir = path.join(cur, '.drift', 'profiles');
  let pmx = PROF_MTIME_CACHE.get(pDir);
  if (pmx === undefined) {
    pmx = 0;
    if (fs.existsSync(pDir) && fs.statSync(pDir).isDirectory()) {
      for (const fn of fs.readdirSync(pDir)) if (fn.endsWith('.toml')) try { pmx = Math.max(pmx, fs.statSync(path.join(pDir, fn)).mtimeMs); } catch {}
    }
    PROF_MTIME_CACHE.set(pDir, pmx);
  }
  return pmx > m ? pmx : m;
}

export async function runCaseMutants(mutCfg, mutOut, ctx, contract, passed, elapsed, performance, isAssertErr, withMutation, makeCtx, fn, fs) {
  if (!mutCfg) return;
  const targets = ctx.cases.flatMap((cid) => mutCfg.byCase.get(`${contract}\u0000${cid}`) || []);
  if (!targets.length) return;
  const budget = Math.max(250 * targets.length, 20 * targets.length * elapsed), t0 = performance.now(), lines = [];
  let over = false;
  for (const t of targets) {
    let outcome = 'inconclusive';
    if (!passed || over || (performance.now() - t0) > budget) { if (passed) over = true; }
    else {
      let err = null, failed = false;
      try { await withMutation(t, async () => { await fn(makeCtx(t)); }); } catch (e) { failed = true; err = e; }
      if ((performance.now() - t0) > budget) over = true;
      else if (!failed) outcome = 'survived';
      else if (isAssertErr(err)) outcome = 'killed';
    }
    lines.push(JSON.stringify({ manifest: mutCfg.manifestId, contract: t.contract, digest: t.digest, mutant: t.id, case: t.case, outcome, control: passed ? 'passed' : 'failed' }));
  }
  fs.appendFileSync(mutOut, lines.join('\n') + '\n', 'utf8');
}

export function buildEnvObj(adapterId, raw, nodeVer, parseJson, envKeys, errFn) {
  const m = /\b(mocha|vitest|jest|playwright)\b/iu.exec(`${process.env.DRIFT_TEST_CMD || ''} ${process.argv[1] || ''}`);
  const base = { adapter: adapterId, config: 'default', deps: 'none', drift: '0.11.0', policy: 'core@1', runner: m ? m[1].toLowerCase() : 'node:test', toolchain: `node@${nodeVer}` };
  if (raw) {
    const parsed = parseJson(raw);
    if (!isObj(parsed)) errFn('DRIFT_ENV must be a JSON object');
    for (const [k, v] of Object.entries(parsed)) {
      if (!envKeys.includes(k) || !isStr(v) || !v.trim()) errFn(`invalid DRIFT_ENV key "${k}"`);
      base[k] = v.trim();
    }
  }
  return base;
}

export function loadViewFromEnv(id, views, env, autoResolveFn, attachPlanFn, fs, path, readJson, errFn) {
  if (views.has(id)) return views.get(id);
  const res = env.DRIFT_RESOLVED || '';
  if (!res) {
    const d = autoResolveFn(id);
    if (!d) errFn(`DRIFT_RESOLVED is not set and contract "${id}" could not be auto-resolved from .drift/`);
    if (d.id !== id) errFn(`resolved view for "${id}" has id "${d.id}"`);
    return views.set(id, d).get(id);
  }
  const f = res.endsWith('.json') ? res : path.join(res, `${id}.json`);
  if (!res.endsWith('.json')) {
    const synced = autoResolveFn(id, path.resolve(f));
    if (synced && synced.id === id) return views.set(id, attachPlanFn(synced, path.resolve(f), fs, path, readJson)).get(id);
  }
  if (!fs.existsSync(f)) errFn(`contract "${id}" was not found at ${f}`);
  const d = attachPlanFn(readJson(f), f, fs, path, readJson);
  if (d.id !== id) errFn(`resolved view ${f} has id "${d.id}", expected "${id}"`);
  return views.set(id, d).get(id);
}

export function parseSelectionJson(raw) {
  const byC = new Map(), tagged = new Set();
  for (const c of Array.isArray(raw.contracts) ? raw.contracts : (isStr(raw.contract) ? [raw] : [])) {
    const rep = Array.isArray(c.replayed_cases) ? c.replayed_cases : [];
    if (c.code_hit === true || (c.resource_hit === true && !rep.length)) tagged.add(c.contract);
    byC.set(c.contract, new Set([...(c.cases || []).filter((ch) => ch.change !== 'removed').map((ch) => ch.case), ...rep]));
  }
  return { all: Boolean(raw.all), tests: new Set(Array.isArray(raw.tests) ? raw.tests : []), byC, tagged };
}

import { validateShadowStateDir } from './drift_ui_collector.mjs';
export { validateShadowStateDir };

export function discoverEventsDirFrom(cwd, env, fs, path) {
  const sd = validateShadowStateDir(cwd, env, fs, path);
  if (sd) {
    for (const sub of ['.drift', '.drift-work']) {
      const c = path.join(sd, sub, 'events');
      if (fs.existsSync(c) && fs.statSync(c).isDirectory()) return c;
    }
    if (!(env.DRIFT_RESOLVED || '').trim()) return path.join(sd, '.drift-work', 'events');
  }
  let cur = cwd, areaRoot = '';
  while (true) {
    for (const sub of ['.drift', '.drift-work']) {
      const c = path.join(cur, sub, 'events');
      if (fs.existsSync(c) && fs.statSync(c).isDirectory()) return c;
    }
    if (fs.existsSync(path.join(cur, '.drift', 'config.toml')) || fs.existsSync(path.join(cur, '.drift', 'contracts'))) { areaRoot = cur; break; }
    const p = path.dirname(cur);
    if (p === cur) break;
    cur = p;
  }
  return (areaRoot && !(env.DRIFT_RESOLVED || '').trim()) ? path.join(areaRoot, '.drift-work', 'events') : '';
}

export function recordDiscoveryInto(testId, activeOut, env, discoverDirFn, shardPath, discClasses, discTests, ensureInvFn, flushInvFn, ensureExitFn, fs, errFn) {
  const tgt = activeOut || env.DRIFT_EVENTS || discoverDirFn();
  if (!tgt) return;
  sidecarHead(env, [], []);
  const raw = isStr(testId) ? testId.trim() : '', h = raw.indexOf('#'), cls = h > 0 ? raw.slice(0, h) : '', mth = (h > 0 ? raw.slice(h + 1) : '').split(/[([]/u, 1)[0];
  if (!cls || !mth || /[\s/\\#[\]]/u.test(cls) || /[\s#[\]]/u.test(mth)) errFn(`DRIFT_EVENTS requires a test id in Class#method form: "${testId}"`);
  const canon = `${cls}#${mth}`, out = activeOut || shardPath || (tgt.endsWith('.jsonl') && fs.existsSync(tgt) ? tgt : '');
  discClasses.add(cls); discTests.add(canon);
  if (!out) return;
  const inv = ensureInvFn(out), before = inv.classes.size + inv.tests.size;
  inv.classes.add(cls); inv.tests.add(canon);
  if (before === inv.classes.size + inv.tests.size && !inv.dirty && fs.existsSync(out.slice(0, -6) + '.meta.json')) return;
  inv.dirty = true;
  ensureExitFn();
  if (!inv.scheduled) { inv.scheduled = true; queueMicrotask(() => flushInvFn(out, inv)); }
}

export function parseMutantsManifest(file, outputTarget, bytes, crypto, parseJson, escapePointer, parseMutationSegments, errFn) {
  const manifest = parseJson(bytes.toString('utf8'));
  if (manifest.version !== 1 || !Array.isArray(manifest.contracts)) errFn(`invalid mutation manifest ${file}`);
  const manifestId = `sha256:${crypto.createHash('sha256').update(bytes).digest('hex')}`, byCase = new Map();
  for (const c of manifest.contracts) {
    for (const m of c.mutants || []) {
      const k = `${c.id}\u0000${m.case}`, isWhen = isStr(m.path) && m.path.startsWith(`/cases/${escapePointer(m.case)}/when/`);
      if (!byCase.has(k)) byCase.set(k, []);
      byCase.get(k).push({ id: m.id, contract: c.id, digest: c.digest, case: m.case, path: m.path, after: m.after, isWhen, segments: parseMutationSegments(c.id, m.case, m.path, isWhen ? 'when' : 'then') });
    }
  }
  return { file, outT: outputTarget, manifestId, byCase };
}

export function recordContextInput(ctx, filePath, pre, cwd, inputDigestFn, resolveEventsFn, recordDiscFn, inventories, flushInvFn, path) {
  const isSelf = pre === 'sha256:self-stub' || (typeof pre === 'string' && String(filePath).startsWith('.drift/seam-stub/'));
  const abs = isSelf ? String(filePath) : path.resolve(cwd, String(filePath));
  const relRaw = isSelf ? abs : path.relative(cwd, abs).split(path.sep).join('/');
  const rel = relRaw && !relRaw.startsWith('..') ? relRaw : String(filePath).split(path.sep).join('/');
  const dig = isSelf ? pre : inputDigestFn(abs, pre);
  if (!ctx.mutationOverride) {
    if (pre === 'sha256:self-stub') ctx.selfStub = true;
    if (!isSelf) ctx.inputFiles.set(abs, { rel, dig });
    const out = resolveEventsFn();
    if (out) {
      recordDiscFn(ctx.testId, out);
      const inv = inventories.get(out);
      if (inv) {
        const raw = ctx.testId.trim(), h = raw.indexOf('#');
        const canon = h > 0 ? `${raw.slice(0, h)}#${raw.slice(h + 1).split(/[([]/u, 1)[0]}` : raw;
        let fm = inv.inputs.get(canon);
        if (!fm) { fm = new Map(); inv.inputs.set(canon, fm); }
        if (fm.get(rel) !== dig) {
          fm.set(rel, dig);
          inv.dirty = true;
          if (!inv.scheduled) { inv.scheduled = true; queueMicrotask(() => flushInvFn(out, inv)); }
        }
      }
    }
  }
  return dig;
}

export function verifyRecordedInputs(contract, test, inputFiles, digests, fs, hashBuf, aErr) {
  for (const [abs, { rel, dig }] of inputFiles) {
    if (!fs.existsSync(abs)) aErr(`${contract}: recorded input "${rel}" was mutated during test "${test}"`);
    const st = fs.statSync(abs), c = digests.get(abs);
    const ok = st.size > 65536 ? Boolean(c && c.sig === `${st.mtimeMs}:${st.size}` && c.hex === dig) : hashBuf(fs.readFileSync(abs)) === dig;
    if (!ok) aErr(`${contract}: recorded input "${rel}" was mutated during test "${test}"`);
  }
}
