import { mergePriorInventory, resolveSelectedFiles, runDriftCli } from './drift_cli.mjs';
import {
  adaptComposeSemantics,
  adaptPlaywrightSurface,
  adaptUiaSnapshot,
  bindUiEnvironment,
  evalPlanCaseImpl,
  observeUiSequence,
} from './drift_ui.mjs';
import { attachBridgePlan, collectPlaywrightSequence, collectUiSequence } from './drift_ui_collector.mjs';
import { buildWhenEnv, CAPS_03, desugar03Rel, evaluateScenarioMatrix, evaluateTaskRecovery, expandDomain, resolvePeerValue, unwrap03Eq } from './drift_ui_recovery.mjs';
import { captureSurfaceDom, checkSurfaceKey } from './drift_ui_surface.mjs';
export {
  adaptComposeSemantics,
  adaptPlaywrightSurface,
  adaptUiaSnapshot,
  attachBridgePlan,
  bindUiEnvironment,
  buildWhenEnv,
  CAPS_03,
  collectPlaywrightSequence,
  collectUiSequence,
  evaluateScenarioMatrix,
  evaluateTaskRecovery,
  expandDomain,
  mergePriorInventory,
  observeUiSequence,
  resolvePeerValue,
  resolveSelectedFiles,
  runDriftCli,
  unwrap03Eq,
};

// Projection, relational domain, and UI view checks for the DRIFT JS bridge.
export const REL_KEYS = new Set(['min', 'max', 'min_len', 'max_len', 'non_empty', 'le_field', 'ge_field', 'eq_field', 'in', 'not_in', 'sum_fields', 'contains', 'prefix', 'suffix', 'allowed_keys', 'forbid_keys', 'monotonic', 'sum_total', 'step_max_delta', 'approx', 'abs_tol', 'rel_tol', 'balance_fields', 'unit', 'unit_conversion', 'eq', 'len', 'keys', 'peer', 'series', 'tol', 'convert_from']);
export const NON_VERIFIED_OP_STATES = new Set(['prepared', 'accepted', 'queued', 'running', 'in_progress', 'partial_failure', 'cancellation_requested', 'unknown']);
export const TERMINAL_UI_CLAIMS = new Set(['completed', 'complete', 'verified', 'done', 'fulfilled', 'available', 'sent', 'paid', 'approved']);

export const isStr = (v) => typeof v === 'string';
export const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
export const lowStr = (x) => String(x ?? '').trim().toLowerCase();
export const escapePointer = (s) => s.replace(/~/gu, '~0').replace(/\//gu, '~1');
export const unescapePointer = (s) => (s.includes('~') ? s.replace(/~1/gu, '/').replace(/~0/gu, '~') : s);
export const isArrayIndex = (s) => s === '0' || /^[1-9][0-9]*$/u.test(s);
export const isAssertErr = (e) => Boolean(e && (e.code === 'ERR_ASSERTION' || e.name === 'AssertionError'));

export function throwError(msg) { throw new Error(msg); }

export function throwAssertionError(msg) {
  const err = new Error(msg);
  err.name = 'AssertionError';
  err.code = 'ERR_ASSERTION';
  throw err;
}

export function splitResourcePointer(ptr) {
  if (!isStr(ptr) || !ptr) return ['', ptr];
  const start = ptr[0] === '/' ? 1 : 0;
  const col = ptr.indexOf(':/', start);
  if (col > start && /^[A-Za-z0-9][A-Za-z0-9._-]*$/u.test(ptr.slice(start, col))) {
    return [ptr.slice(start, col), ptr.slice(col + 1)];
  }
  return ['', ptr];
}

export function readPointer(target, rawPtr) {
  if (!isStr(rawPtr)) return { found: false, value: undefined };
  const [res, ptr] = splitResourcePointer(rawPtr);
  let cur = res && isObj(target) && res in target ? target[res] : target;
  if (ptr === '') return { found: true, value: cur };
  if (!ptr.startsWith('/')) return { found: false, value: undefined };
  for (const seg of ptr.slice(1).split('/').map(unescapePointer)) {
    if (Array.isArray(cur)) {
      const idx = Number(seg);
      if (!isArrayIndex(seg) || idx < 0 || idx >= cur.length) return { found: false, value: undefined };
      cur = cur[idx];
    } else if (isObj(cur) && seg in cur) {
      cur = cur[seg];
    } else if (isObj(cur) && typeof cur.__domDatasetAttr === 'function') {
      const attr = cur.__domDatasetAttr(seg);
      if (attr == null) return { found: false, value: undefined };
      cur = attr;
    } else if (isObj(cur) && typeof cur.getAttribute === 'function') {
      if (seg === 'dataset') {
        const el = cur;
        cur = { __domDatasetAttr: (k) => el.getAttribute(`data-${k.replace(/[A-Z]/gu, (m) => `-${m.toLowerCase()}`)}`) };
      } else {
        const attr = cur.getAttribute(seg);
        if (attr == null) return { found: false, value: undefined };
        cur = attr;
      }
    } else return { found: false, value: undefined };
  }
  return { found: true, value: cur };
}

export function cloneJson(val) {
  if (Array.isArray(val)) return val.map(cloneJson);
  return isObj(val) ? Object.fromEntries(Object.entries(val).map(([k, v]) => [k, cloneJson(v)])) : val;
}

export const isFinNum = (v) => typeof v === 'number' && Number.isFinite(v);

export function valuesEqual(a, b) {
  if (typeof a === 'number' || typeof b === 'number') return isFinNum(a) && isFinNum(b) && Math.abs(a - b) <= 1e-9;
  if (a === b) return true;
  if (a == null || b == null) return false;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => valuesEqual(v, b[i]));
  if (isObj(a) && isObj(b)) {
    const ka = Object.keys(a);
    return ka.length === Object.keys(b).length && ka.every((k) => k in b && valuesEqual(a[k], b[k]));
  }
  return false;
}

export function writePointer(target, rawPtr, value) {
  const [, ptr] = splitResourcePointer(rawPtr);
  if (ptr === '') return cloneJson(value);
  if (!isStr(ptr) || !ptr.startsWith('/')) throwError(`invalid RFC 6901 JSON Pointer "${rawPtr}"`);
  const segs = ptr.slice(1).split('/').map(unescapePointer);
  const putAt = (cur, i) => {
    const seg = segs[i];
    const last = i === segs.length - 1;
    const nextIdx = !last && isArrayIndex(segs[i + 1]);
    if (isArrayIndex(seg) && Array.isArray(cur)) {
      const idx = Number(seg);
      const copy = [...cur];
      while (copy.length <= idx) copy.push(null);
      copy[idx] = last ? cloneJson(value) : putAt(copy[idx] ?? (nextIdx ? [] : {}), i + 1);
      return copy;
    }
    const obj = isObj(cur) ? { ...cur } : {};
    if (last) return { ...obj, [seg]: cloneJson(value) };
    const child = seg in obj && obj[seg] !== null && typeof obj[seg] === 'object' ? obj[seg] : (nextIdx ? [] : {});
    return { ...obj, [seg]: putAt(child, i + 1) };
  };
  return putAt(target, 0);
}

export function parseMutationSegments(contractId, caseId, ptr, sec) {
  const pfx = `/cases/${escapePointer(caseId)}/${sec}/`;
  if (!ptr.startsWith(pfx)) throwError(`mutation path ${ptr} is outside ${contractId}.${caseId}.${sec}`);
  const raw = ptr.slice(pfx.length).split('/');
  if (!raw.length || !raw[0]) throwError(`mutation path ${ptr} has no ${sec} leaf`);
  return raw.map(unescapePointer);
}

export function applyMutation(tbl, contractId, caseId, ptr, after, sec = 'then', pre = null) {
  const segs = pre || parseMutationSegments(contractId, caseId, ptr, sec);
  const replace = (t, i) => {
    const k = segs[i];
    if (!isObj(t) || !(k in t)) throwError(`mutation path has no predicate ${k}`);
    if (i === segs.length - 1) return { ...t, [k]: after };
    if (i === 0 && segs.length === 2 && isObj(after) && segs[1] in t && k in after && segs[1] in after) {
      return { ...t, [k]: after[k], [segs[1]]: after[segs[1]] };
    }
    if (!isObj(t[k])) {
      throwError(`mutation path crosses a non-table value at ${k}`);
    }
    return { ...t, [k]: replace(t[k], i + 1) };
  };
  return replace(tbl, 0);
}

export function checkRelationalLeaf(contractId, caseId, key, rawExp, act, payload, proj, mutationOverride, whenEnv = null, contract = null) {
  if (!isObj(rawExp)) return false;
  const ks = Object.keys(rawExp);
  if (!ks.length || !ks.every((rk) => REL_KEYS.has(rk))) return false;
  const context = contract ?? payload;
  const exp = desugar03Rel(rawExp, context?.units ?? {}, context?.schema?.then?.[key]?.unit);
  const pfx = `${contractId}.${caseId}`;
  if ('eq' in exp) {
    if (!valuesEqual(act, exp.eq)) {
      throwAssertionError(`${pfx}: expected then.${key}=${JSON.stringify(exp.eq)}, got ${JSON.stringify(act)}`);
    }
    if (Object.keys(exp).length === 1) return true;
  }
  const peerOf = (ref) => resolvePeerValue(ref, payload, proj, whenEnv, readPointer);
  const actLen = isStr(act) ? Array.from(act).length : (Array.isArray(act) ? act.length : (isObj(act) ? Object.keys(act).length : -1));
  const isSeqTuning = 'monotonic' in exp || 'step_max_delta' in exp || 'sum_total' in exp;
  const tol = ('abs_tol' in exp && isFinNum(Number(exp.abs_tol)) && Number(exp.abs_tol) >= 0) ? Number(exp.abs_tol) : 1e-9;
  if (!isSeqTuning) {
    if ('min' in exp && (!isFinNum(act) || !isFinNum(Number(exp.min)) || act + 1e-9 < Number(exp.min))) {
      throwAssertionError(`${pfx}: expected then.${key}>=${exp.min}, got ${JSON.stringify(act)}`);
    }
    if ('max' in exp && (!isFinNum(act) || !isFinNum(Number(exp.max)) || act - 1e-9 > Number(exp.max))) {
      throwAssertionError(`${pfx}: expected then.${key}<=${exp.max}, got ${JSON.stringify(act)}`);
    }
  }
  if ('approx' in exp) {
    const ap = Number(exp.approx);
    const at = 'abs_tol' in exp ? Number(exp.abs_tol) : 0;
    const rt = 'rel_tol' in exp ? Number(exp.rel_tol) : 0;
    if (!isFinNum(act) || !isFinNum(ap) || (!('abs_tol' in exp) && !('rel_tol' in exp)) || !isFinNum(at) || at < 0 || !isFinNum(rt) || rt < 0) {
      throwAssertionError(`${pfx}: invalid approx on then.${key}`);
    }
    const rad = at + rt * Math.abs(ap);
    if (!isFinNum(rad) || Math.abs(act - ap) > rad) {
      throwAssertionError(`${pfx}: expected then.${key} approx ${ap} (+/- ${rad}), got ${JSON.stringify(act)}`);
    }
  }
  if ('balance_fields' in exp) {
    if (!isObj(exp.balance_fields)) throwAssertionError(`${pfx}: invalid balance_fields on then.${key}`);
    let bal = 0;
    for (const [sgn, side] of [[1, 'add'], [-1, 'sub']]) {
      for (const ref of (exp.balance_fields[side] || [])) {
        const pr = peerOf(ref);
        if (!pr.found || !isFinNum(pr.value)) throwAssertionError(`${pfx}: missing numeric peer "${ref}" for then.${key}.balance_fields`);
        bal += sgn * pr.value;
      }
    }
    if (!isFinNum(act) || !isFinNum(bal) || Math.abs(act - bal) > tol) {
      throwAssertionError(`${pfx}: expected then.${key} == balance (${bal}), got ${JSON.stringify(act)}`);
    }
  }
  if ('min_len' in exp && (actLen < 0 || actLen < Number(exp.min_len))) {
    throwAssertionError(`${pfx}: expected len(then.${key})>=${exp.min_len}, got ${actLen}`);
  }
  if ('max_len' in exp && (actLen < 0 || actLen > Number(exp.max_len))) {
    throwAssertionError(`${pfx}: expected len(then.${key})<=${exp.max_len}, got ${actLen}`);
  }
  if ('non_empty' in exp && (actLen < 0 || (exp.non_empty ? actLen <= 0 : actLen !== 0))) {
    throwAssertionError(`${pfx}: expected then.${key}.non_empty=${exp.non_empty}, got len=${actLen}`);
  }
  for (const [fk, op] of [['le_field', '<='], ['ge_field', '>='], ['eq_field', '==']]) {
    if (!(fk in exp)) continue;
    const pr = peerOf(exp[fk]);
    if (!pr.found) throwAssertionError(`${pfx}: missing peer "${exp[fk]}" for then.${key}.${fk}`);
    const ok = op === '=='
      ? valuesEqual(act, pr.value)
      : (isFinNum(act) && isFinNum(pr.value) && (op === '<=' ? act - 1e-9 <= pr.value : act + 1e-9 >= pr.value));
    if (!ok) {
      throwAssertionError(`${pfx}: expected then.${key} ${op} ${exp[fk]} (${JSON.stringify(pr.value)}), got ${JSON.stringify(act)}`);
    }
  }
  if ('in' in exp && (!Array.isArray(exp.in) || !exp.in.some((x) => valuesEqual(act, x)))) {
    throwAssertionError(`${pfx}: expected then.${key} in ${JSON.stringify(exp.in)}, got ${JSON.stringify(act)}`);
  }
  if ('not_in' in exp) {
    if (act === null || act === undefined) throwAssertionError(`${pfx}: expected non-null value for then.${key}.not_in`);
    if (Array.isArray(exp.not_in) ? exp.not_in.some((x) => valuesEqual(act, x)) : !valuesEqual(act, exp.not_in)) {
      throwAssertionError(`${pfx}: forbidden value ${JSON.stringify(act)} in then.${key}.not_in`);
    }
  }
  if ('allowed_keys' in exp) {
    if (!isObj(act) || !Array.isArray(exp.allowed_keys)) throwAssertionError(`${pfx}: expected object and allowed_keys list for then.${key}`);
    for (const k of Object.keys(act)) {
      if (act === payload && k === '_frame' && isObj(act[k])) continue;
      if (!exp.allowed_keys.includes(k)) throwAssertionError(`${pfx}: unexpected key "${k}" on then.${key}`);
    }
  }
  if ('forbid_keys' in exp) {
    if (!isObj(act)) throwAssertionError(`${pfx}: expected object for then.${key}.forbid_keys`);
    const hasKeyRec = (v, fk, root = true) => Array.isArray(v)
      ? v.some((x) => hasKeyRec(x, fk, false))
      : (isObj(v) && (Object.hasOwn(v, fk) || Object.entries(v).some(([ck, cv]) => !(root && ck === '_frame' && fk !== '_frame' && isObj(cv)) && hasKeyRec(cv, fk, false))));
    if (Array.isArray(exp.forbid_keys)) {
      for (const fk of exp.forbid_keys.map(String)) {
        if (hasKeyRec(act, fk, act === payload)) throwAssertionError(`${pfx}: forbidden key "${fk}" present on then.${key}`);
      }
    } else if (!hasKeyRec(act, String(exp.forbid_keys), act === payload)) {
      throwAssertionError(`${pfx}: drop-forbid-key mutant killed on then.${key}.forbid_keys`);
    }
  }
  if ('sum_fields' in exp) {
    if (!Array.isArray(exp.sum_fields) || exp.sum_fields.length < 2) {
      throwAssertionError(`${pfx}: invalid sum_fields on then.${key}`);
    }
    let sum = 0;
    for (const ref of exp.sum_fields) {
      const pr = peerOf(ref);
      if (!pr.found || !isFinNum(pr.value)) {
        throwAssertionError(`${pfx}: missing numeric peer "${ref}" for then.${key}.sum_fields`);
      }
      sum += pr.value;
    }
    if (!isFinNum(act) || !isFinNum(sum) || Math.abs(act - sum) > 1e-9) {
      throwAssertionError(`${pfx}: expected then.${key} == sum(${exp.sum_fields.join('+')}) (${sum}), got ${JSON.stringify(act)}`);
    }
  }
  if ('contains' in exp) {
    const reqs = Array.isArray(exp.contains) ? exp.contains : [exp.contains];
    const ok = isStr(act) ? reqs.every((req) => isStr(req) && act.includes(req))
      : Array.isArray(act) && reqs.every((req) => act.some((x) => valuesEqual(x, req)));
    if (!ok) {
      throwAssertionError(`${pfx}: expected then.${key} to contain ${JSON.stringify(exp.contains)}, got ${JSON.stringify(act)}`);
    }
  }
  if ('prefix' in exp && (!isStr(act) || !act.startsWith(String(exp.prefix)))) {
    throwAssertionError(`${pfx}: expected then.${key} to start with ${JSON.stringify(exp.prefix)}, got ${JSON.stringify(act)}`);
  }
  if ('suffix' in exp && (!isStr(act) || !act.endsWith(String(exp.suffix)))) {
    throwAssertionError(`${pfx}: expected then.${key} to end with ${JSON.stringify(exp.suffix)}, got ${JSON.stringify(act)}`);
  }
  if (isSeqTuning && Array.isArray(act) && ('min' in exp || 'max' in exp)) {
    for (const v of act) {
      if (!isFinNum(v) || ('min' in exp && v + tol < Number(exp.min)) || ('max' in exp && v - tol > Number(exp.max))) {
        throwAssertionError(`${pfx}: sequence element ${v} outside [min, max] on then.${key}`);
      }
    }
  }
  if ('monotonic' in exp) {
    const mode = String(exp.monotonic);
    if (!Array.isArray(act) || !act.length || !act.every(isFinNum)) throwAssertionError(`${pfx}: expected non-empty numeric array for then.${key}.monotonic`);
    for (let i = 1; i < act.length; i++) {
      const p = act[i - 1], c = act[i];
      const ok = mode === 'non_decreasing' ? p - tol <= c : mode === 'strictly_increasing' ? p + tol < c : mode === 'non_increasing' ? p + tol >= c : mode === 'strictly_decreasing' ? p - tol > c : false;
      if (!ok) throwAssertionError(`${pfx}: expected then.${key}.monotonic=${mode}, violated at index ${i} (${p} -> ${c})`);
    }
  }
  if ('step_max_delta' in exp) {
    const d = Number(exp.step_max_delta);
    if (!isFinNum(d) || d <= 0 || !Array.isArray(act) || !act.length || !act.every(isFinNum)) throwAssertionError(`${pfx}: invalid or non-numeric sequence for then.${key}.step_max_delta=${exp.step_max_delta}`);
    for (let i = 1; i < act.length; i++) {
      if (Math.abs(act[i] - act[i - 1]) > d + tol) throwAssertionError(`${pfx}: expected then.${key}.step_max_delta<=${d}, observed step ${Math.abs(act[i] - act[i - 1])} at index ${i}`);
    }
  }
  if ('sum_total' in exp) {
    if (isObj(act) && Object.keys(act).length > 0 && Object.keys(act).every((rk) => REL_KEYS.has(rk))) throwAssertionError(`${pfx}: literal relational table cannot satisfy then.${key}.sum_total`);
    const vals = Array.isArray(act) ? act : (isObj(act) ? Object.values(act) : []);
    if (!vals.length || !vals.every(isFinNum)) throwAssertionError(`${pfx}: expected non-empty numeric array or map for then.${key}.sum_total`);
    const total = vals.reduce((acc, v) => acc + v, 0), st = exp.sum_total;
    if (isFinNum(st)) {
      if (Math.abs(total - st) > tol) throwAssertionError(`${pfx}: expected then.${key}.sum_total==${st}, got ${total}`);
    } else if (isObj(st)) {
      if (('eq' in st && (!isFinNum(st.eq) || Math.abs(total - st.eq) > tol)) || ('min' in st && (!isFinNum(st.min) || total + tol < st.min)) || ('max' in st && (!isFinNum(st.max) || total - tol > st.max))) {
        throwAssertionError(`${pfx}: sum_total ${total} outside ${JSON.stringify(st)} on then.${key}`);
      }
    } else throwAssertionError(`${pfx}: invalid sum_total on then.${key}`);
  }
  return true;
}

export function evalCompiledPlanCase(contractId, caseId, planCase, payload, seen = null) {
  return evalPlanCaseImpl(contractId, caseId, planCase, payload, seen, escapePointer, readPointer, checkRelationalLeaf, throwAssertionError);
}

export function checkProjectedLeaf(contractId, caseId, key, exp, payload, proj, mutationOverride, withAt, missMsg, whenEnv = null, contract = null) {
  const pfx = `${contractId}.${caseId}`;
  const isUiObs = isObj(payload) && (payload.schema === 'drift.ui-observation/1' || isObj(payload.evidence));
  const tPay = isObj(payload) && isObj(payload.then) && !(key in payload) ? payload.then : payload;
  const bumpUnverifiable = () => {
    if (isObj(payload?.evidence) && typeof payload.evidence.unverifiable_checks === 'number') {
      payload.evidence.unverifiable_checks += 1;
      if (Array.isArray(payload.evidence.unverifiable_reasons)) {
        payload.evidence.unverifiable_reasons.push(`unverifiable_then:${key}`);
      }
    }
  };
  if (key in proj) {
    const ptr = proj[key];
    let res = readPointer(tPay, ptr);
    if (!res.found && tPay !== payload) res = readPointer(payload, ptr);
    if (!res.found) {
      bumpUnverifiable();
      throwAssertionError(`${pfx}: missing projected path "${ptr}" for then.${key}`);
    }
    if (isUiObs && exp !== null && (res.value === null || res.value === undefined || (res.value === '' && typeof exp === 'string' && exp !== ''))) {
      bumpUnverifiable();
      throwAssertionError(`${pfx}: unverifiable then.${key}: unmeasured value at "${ptr}"`);
    }
    if (checkRelationalLeaf(contractId, caseId, key, exp, res.value, payload, proj, mutationOverride, whenEnv, contract)) return;
    if (!valuesEqual(res.value, exp)) {
      throwAssertionError(`${pfx}: expected then.${key}=${JSON.stringify(exp)}${withAt ? ` at "${ptr}"` : ''}, got ${JSON.stringify(res.value)}`);
    }
    return;
  }
  if (isObj(tPay) && key in tPay) {
    if (isUiObs && exp !== null && (tPay[key] === null || tPay[key] === undefined)) {
      bumpUnverifiable();
      throwAssertionError(`${pfx}: unverifiable then.${key}: unmeasured value`);
    }
    if (checkRelationalLeaf(contractId, caseId, key, exp, tPay[key], payload, proj, mutationOverride, whenEnv, contract)) return;
    if (!valuesEqual(tPay[key], exp)) {
      throwAssertionError(`${pfx}: expected then.${key}=${JSON.stringify(exp)}, got ${JSON.stringify(tPay[key])}`);
    }
    return;
  }
  bumpUnverifiable();
  throwAssertionError(`${pfx}: ${missMsg} then.${key}`);
}

function computeUnobservedControls(controls, thenTable, proj) {
  if (!isObj(controls)) return [];
  const ctrls = Object.keys(controls).sort();
  if (!ctrls.length) return [];
  const ctrlSet = new Set(ctrls);
  const obs = new Set();
  for (const tk of Object.keys(thenTable)) {
    if (tk === 'unobserved_controls') continue;
    if (ctrlSet.has(tk)) obs.add(tk);
    for (const seg of (isStr(proj?.[tk]) ? proj[tk] : '').split('/')) {
      if (seg && ctrlSet.has(seg)) obs.add(seg);
    }
  }
  return ctrls.filter((c) => !obs.has(c));
}

export async function invokeVerifiedCallback(fn, contractId, caseId, key, exp, extra) {
  const src = Function.prototype.toString.call(fn).trim();
  const body = src.includes('=>') ? src.slice(src.indexOf('=>') + 2).trim() : src;
  if (/^\{\s*\}$/u.test(body)) throwAssertionError(`${contractId}.${caseId}: check for then.${key} must inspect the expected value`);
  const res = await fn(exp, extra);
  if (res === false) throwAssertionError(`${contractId}.${caseId}: check for then.${key} returned false`);
  if (res !== true && !/\b(?:assert|expect|throw|check|reject|fail)\b|[!=]==?|[<>]=?/u.test(body)) {
    throwAssertionError(`${contractId}.${caseId}: check for then.${key} must inspect and assert the expected value`);
  }
}

export async function checkViewTable(contractId, caseId, thenTable, seen, view, checks, mutationOverride, metricsStore, getProj, whenEnv = null) {
  const v = isObj(view) ? view : {};
  const pfx = `${contractId}.${caseId}`;
  if (
    v.surfaceFound === false
    || v.surface_found === false
    || (v.schema === 'drift.ui-observation/1' && v.surface_found !== true && v.surfaceFound !== true)
  ) {
    throwAssertionError(`${pfx}: surface.missing`);
  }
  const isMut = Boolean(mutationOverride);
  const assertEq = (k, exp, act) => { if (act !== exp) throwAssertionError(`${pfx}: expected ${k}=${exp}, got ${act}`); };
  let proj = null;
  const STATE_FIRST = new Set(['baseline_state', 'duplicate_figures', 'single_metric_source', 'preserved_input_on_error', 'claim_matches_evidence']);
  const UNVERIF_LAST = new Set(['unverifiable_checks', 'unverified_elements']);
  const ordered = [
    ...Object.entries(thenTable).filter(([k]) => STATE_FIRST.has(k)),
    ...Object.entries(thenTable).filter(([k]) => !STATE_FIRST.has(k) && !UNVERIF_LAST.has(k)),
    ...Object.entries(thenTable).filter(([k]) => UNVERIF_LAST.has(k)),
  ];
  for (const [k, rawExp] of ordered) {
    const exp = unwrap03Eq(rawExp);
    if (checks && typeof checks[k] === 'function') {
      await invokeVerifiedCallback(checks[k], contractId, caseId, k, exp, v);
      seen.add(k);
      continue;
    }
    if (v.adapter?.capabilities && proj === null) proj = getProj();
    if (checkSurfaceKey(contractId, caseId, k, exp, v, thenTable, proj, mutationOverride, checkRelationalLeaf, throwAssertionError)) {
      seen.add(k);
      continue;
    }
    if (k === 'baseline_state') {
      const hasB = Boolean(v.hasBaseline ?? (v.baseline !== undefined && v.baseline !== null));
      const lbl = lowStr(v.baselineLabel ?? v.deltaLabel);
      if (!hasB && /^(?:invariato|unchanged|same|nessuna variazione|[+-]\s*\d)/u.test(lbl)) {
        throwAssertionError(`${pfx}: comparative baseline label "${lbl}" without baseline`);
      }
      const act = v.baseline_state ?? (hasB ? 'compared' : 'first_observation');
      if (act !== exp) throwAssertionError(`${pfx}: expected baseline_state=${JSON.stringify(exp)}, got ${JSON.stringify(act)}`);
    } else if (k === 'duplicate_figures') {
      const figs = Array.isArray(v.figures)
        ? v.figures.map(String)
        : (Array.isArray(v.metrics) ? v.metrics.map((m) => `${m.label ?? m.metric ?? ''}:${m.value}`) : []);
      assertEq(k, exp, figs.length - new Set(figs).size);
    } else if (k === 'single_metric_source') {
      let conflict = false;
      const loc = new Map();
      for (const m of Array.isArray(v.metrics) ? v.metrics : []) {
        const mk = `${m.entity ?? v.entity ?? 'default'}\u0000${m.metric ?? m.name ?? ''}`;
        const entry = { value: m.value, source: String(m.source ?? '') };
        const prev = loc.get(mk) ?? metricsStore.get(mk);
        if (prev && (prev.value !== entry.value || (prev.source && entry.source && prev.source !== entry.source))) {
          conflict = true;
        }
        loc.set(mk, entry);
        if (!isMut) metricsStore.set(mk, entry);
      }
      assertEq(k, exp, !conflict);
    } else if (k === 'preserved_input_on_error') {
      let act = Boolean(v.preserved_input_on_error ?? true);
      if (Boolean(v.error ?? v.hasError) && isObj(v.dirtyInputs)) {
        const raw = v.currentInputs ?? v.inputs;
        const cur = isObj(raw) ? raw : {};
        act = Object.entries(v.dirtyInputs).every(([ik, iv]) => JSON.stringify(cur[ik]) === JSON.stringify(iv));
      }
      assertEq(k, exp, act);
    } else if (k === 'claim_matches_evidence') {
      const op = lowStr(v.operationState ?? v.evidenceState);
      const ui = lowStr(v.uiClaim ?? v.statusLabel ?? v.completionState);
      const act = (op && NON_VERIFIED_OP_STATES.has(op) && (Boolean(v.claimedComplete === true) || TERMINAL_UI_CLAIMS.has(ui)))
        ? false
        : Boolean(v.claim_matches_evidence ?? true);
      assertEq(k, exp, act);
    } else if (k === 'unobserved_controls') {
      if (proj === null) proj = getProj();
      const unobs = computeUnobservedControls(v.controls, thenTable, proj);
      v.unobservedControls = unobs;
      const act = Array.isArray(exp) ? unobs : unobs.length;
      if (JSON.stringify(act) !== JSON.stringify(exp)) {
        throwAssertionError(`${pfx}: expected unobserved_controls=${JSON.stringify(exp)}, got ${JSON.stringify(act)} (${JSON.stringify(unobs)})`);
      }
    } else {
      if (proj === null) proj = getProj();
      checkProjectedLeaf(contractId, caseId, k, exp, v, proj, mutationOverride, false, 'no check for', whenEnv);
    }
    seen.add(k);
  }
  if (isObj(v.controls) && !Array.isArray(v.unobservedControls)) {
    if (proj === null) proj = getProj();
    v.unobservedControls = computeUnobservedControls(v.controls, thenTable, proj);
  }
}

export function captureSurfaceView(rootOrSelector, options) {
  return captureSurfaceDom(rootOrSelector, options);
}

// Inventory sidecar fields from DRIFT_SNAPSHOT, DRIFT_EXECUTION_REF, DRIFT_PACK_REF and DRIFT_TOUCHED.
export function sidecarHead(env, classes, tests) {
  const snapshot = (env.DRIFT_SNAPSHOT || '').trim();
  if (snapshot && !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/u.test(snapshot)) throwError(`invalid DRIFT_SNAPSHOT "${snapshot}"`);
  const ref = (env.DRIFT_EXECUTION_REF || '').trim();
  if (ref && !/^sha256:[0-9a-f]{64}$/u.test(ref)) throwError('invalid DRIFT_EXECUTION_REF');
  const packRef = (env.DRIFT_PACK_REF || '').trim();
  const touched = [...new Set((env.DRIFT_TOUCHED || '').split(/[\n,]+/).map((s) => s.trim()).filter(Boolean))].sort();
  return {
    version: ref ? 2 : 1,
    classes: [...classes].sort(),
    tests: [...tests].sort(),
    ...(ref ? { execution_ref: ref } : {}),
    ...(snapshot ? { snapshot } : {}),
    ...(packRef ? { pack_ref: packRef } : {}),
    ...(touched.length || ref ? { touched } : {}),
  };
}
