import { mergePriorInventory, resolveSelectedFiles, runDriftCli } from './drift_cli.mjs';
export { mergePriorInventory, resolveSelectedFiles, runDriftCli };

// Projection, relational domain, and UI view checks for the DRIFT JavaScript bridge.
export const REL_KEYS = new Set([
  'min', 'max', 'min_len', 'max_len', 'non_empty', 'le_field', 'ge_field', 'eq_field', 'in',
  'sum_fields', 'contains', 'prefix', 'suffix',
]);
export const NON_VERIFIED_OP_STATES = new Set([
  'prepared', 'accepted', 'queued', 'running', 'in_progress',
  'partial_failure', 'cancellation_requested', 'unknown',
]);
export const TERMINAL_UI_CLAIMS = new Set([
  'completed', 'complete', 'verified', 'done', 'fulfilled',
  'available', 'sent', 'paid', 'approved',
]);

export const isStr = (v) => typeof v === 'string';
export const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
export const lowStr = (x) => String(x ?? '').trim().toLowerCase();
export const escapePointer = (s) => s.replace(/~/gu, '~0').replace(/\//gu, '~1');
export const unescapePointer = (s) => (s.includes('~') ? s.replace(/~1/gu, '/').replace(/~0/gu, '~') : s);
export const isArrayIndex = (s) => s === '0' || /^[1-9][0-9]*$/u.test(s);
export const isAssertErr = (e) => Boolean(e && (e.code === 'ERR_ASSERTION' || e.name === 'AssertionError'));

export function throwError(message) {
  throw new Error(message);
}

export function throwAssertionError(message) {
  const err = new Error(message);
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
      if (!isArrayIndex(seg) || idx < 0 || idx >= cur.length) {
        return { found: false, value: undefined };
      }
      cur = cur[idx];
    } else if (isObj(cur) && seg in cur) {
      cur = cur[seg];
    } else if (isObj(cur) && typeof cur.__domDatasetAttr === 'function') {
      const attr = cur.__domDatasetAttr(seg);
      if (attr === null || attr === undefined) return { found: false, value: undefined };
      cur = attr;
    } else if (isObj(cur) && typeof cur.getAttribute === 'function') {
      if (seg === 'dataset') {
        const el = cur;
        cur = { __domDatasetAttr: (k) => el.getAttribute(`data-${k.replace(/[A-Z]/gu, (m) => `-${m.toLowerCase()}`)}`) };
      } else {
        const attr = cur.getAttribute(seg);
        if (attr === null || attr === undefined) return { found: false, value: undefined };
        cur = attr;
      }
    } else {
      return { found: false, value: undefined };
    }
  }
  return { found: true, value: cur };
}

export function cloneJson(val) {
  if (Array.isArray(val)) return val.map(cloneJson);
  if (isObj(val)) {
    return Object.fromEntries(Object.entries(val).map(([k, v]) => [k, cloneJson(v)]));
  }
  return val;
}

export const isFinNum = (v) => typeof v === 'number' && Number.isFinite(v);

export function valuesEqual(a, b) {
  if (typeof a === 'number' || typeof b === 'number') {
    return isFinNum(a) && isFinNum(b) && Math.abs(a - b) <= 1e-9;
  }
  if (a === b) return true;
  if (a === null || b === null || a === undefined || b === undefined) return false;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((v, i) => valuesEqual(v, b[i]));
  }
  if (isObj(a) && isObj(b)) {
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => k in b && valuesEqual(a[k], b[k]));
  }
  return false;
}

export function writePointer(target, rawPtr, value) {
  const [, ptr] = splitResourcePointer(rawPtr);
  if (ptr === '') return cloneJson(value);
  if (!isStr(ptr) || !ptr.startsWith('/')) {
    throwError(`invalid RFC 6901 JSON Pointer "${rawPtr}"`);
  }
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
    if (last) {
      obj[seg] = cloneJson(value);
      return obj;
    }
    const child = seg in obj && obj[seg] !== null && typeof obj[seg] === 'object' ? obj[seg] : (nextIdx ? [] : {});
    obj[seg] = putAt(child, i + 1);
    return obj;
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

function expandSingleDomain(spec, first = false) {
  if (Array.isArray(spec)) {
    if (!spec.length) throwError('domain sample array must not be empty');
    return first ? [spec[0]] : [...spec];
  }
  if (!isObj(spec)) throwError('domain specification must be an array or an object');
  if (spec.type === 'int') {
    const min = Number(spec.min);
    const max = Number(spec.max);
    if (!Number.isSafeInteger(min) || !Number.isSafeInteger(max) || min > max) {
      throwError(`invalid int domain [${spec.min}, ${spec.max}]`);
    }
    if (first) return [min < 0 && max > 0 ? 0 : min];
    return [
      ...new Set([
        ...(min < 0 && max > 0 ? [0] : []),
        min,
        min < max ? min + 1 : min,
        Math.trunc((min + max) / 2),
        max > min ? max - 1 : max,
        max,
      ]),
    ];
  }
  if (spec.type === 'string' && Array.isArray(spec.enum) && spec.enum.length) {
    return first ? [String(spec.enum[0])] : [...new Set(spec.enum.map(String))];
  }
  if (spec.type === 'bool') {
    return first ? [false] : [false, true];
  }
  return null;
}

export function expandDomain(domain, first = false) {
  const single = expandSingleDomain(domain, first);
  if (single !== null) return single;
  const keys = Object.keys(domain).sort();
  const d = keys.length;
  if (!d) throwError('Cartesian domain map must not be empty');
  const valsByKey = keys.map((k) => {
    const vals = expandSingleDomain(domain[k], first);
    if (vals === null) throwError(`invalid domain specification for key "${k}"`);
    return vals;
  });
  const cur = {};
  let prod = 1;
  for (let i = 0; i < d; i++) {
    cur[keys[i]] = valsByKey[i][0];
    if (prod <= 16) prod *= valsByKey[i].length;
  }
  if (first) return [cur];
  const maxExcursions = prod <= 16 ? d : (d >= 3 ? 2 : d);
  const out = [];
  const dfs = (pos, exc) => {
    if (pos === d || exc >= maxExcursions) {
      out.push({ ...cur });
      return;
    }
    dfs(pos + 1, exc);
    const vals = valsByKey[pos];
    const k = keys[pos];
    for (let i = 1; i < vals.length; i++) {
      cur[k] = vals[i];
      dfs(pos + 1, exc + 1);
    }
    cur[k] = vals[0];
  };
  dfs(0, 0);
  return out;
}

export function checkRelationalLeaf(contractId, caseId, key, exp, act, payload, proj, mutationOverride) {
  if (!isObj(exp)) return false;
  const ks = Object.keys(exp);
  if (!ks.length || !ks.every((rk) => REL_KEYS.has(rk))) return false;
  const pfx = `${contractId}.${caseId}`;
  const peerOf = (ref) => {
    if (!isStr(ref) || !ref.trim()) return { found: false };
    if (ref.startsWith('/')) return readPointer(payload, ref);
    if (ref in proj) return readPointer(payload, proj[ref]);
    return isObj(payload) && ref in payload ? { found: true, value: payload[ref] } : { found: false };
  };
  const actLen = (isStr(act) || Array.isArray(act)) ? act.length : (isObj(act) ? Object.keys(act).length : -1);
  if ('min' in exp && (!isFinNum(act) || !isFinNum(Number(exp.min)) || act + 1e-9 < Number(exp.min))) {
    throwAssertionError(`${pfx}: expected then.${key}>=${exp.min}, got ${JSON.stringify(act)}`);
  }
  if ('max' in exp && (!isFinNum(act) || !isFinNum(Number(exp.max)) || act - 1e-9 > Number(exp.max))) {
    throwAssertionError(`${pfx}: expected then.${key}<=${exp.max}, got ${JSON.stringify(act)}`);
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
    if (!Array.isArray(act) || !Array.isArray(exp.contains) || !exp.contains.every((req) => act.some((x) => valuesEqual(x, req)))) {
      throwAssertionError(`${pfx}: expected then.${key} to contain ${JSON.stringify(exp.contains)}, got ${JSON.stringify(act)}`);
    }
  }
  if ('prefix' in exp && (!isStr(act) || !act.startsWith(String(exp.prefix)))) {
    throwAssertionError(`${pfx}: expected then.${key} to start with ${JSON.stringify(exp.prefix)}, got ${JSON.stringify(act)}`);
  }
  if ('suffix' in exp && (!isStr(act) || !act.endsWith(String(exp.suffix)))) {
    throwAssertionError(`${pfx}: expected then.${key} to end with ${JSON.stringify(exp.suffix)}, got ${JSON.stringify(act)}`);
  }
  return true;
}

export function checkProjectedLeaf(contractId, caseId, key, exp, payload, proj, mutationOverride, withAt, missMsg) {
  const pfx = `${contractId}.${caseId}`;
  if (key in proj) {
    const ptr = proj[key];
    const res = readPointer(payload, ptr);
    if (!res.found) throwAssertionError(`${pfx}: missing projected path "${ptr}" for then.${key}`);
    if (checkRelationalLeaf(contractId, caseId, key, exp, res.value, payload, proj, mutationOverride)) return;
    if (!valuesEqual(res.value, exp)) {
      throwAssertionError(`${pfx}: expected then.${key}=${JSON.stringify(exp)}${withAt ? ` at "${ptr}"` : ''}, got ${JSON.stringify(res.value)}`);
    }
    return;
  }
  if (isObj(payload) && key in payload) {
    if (checkRelationalLeaf(contractId, caseId, key, exp, payload[key], payload, proj, mutationOverride)) return;
    if (!valuesEqual(payload[key], exp)) {
      throwAssertionError(`${pfx}: expected then.${key}=${JSON.stringify(exp)}, got ${JSON.stringify(payload[key])}`);
    }
    return;
  }
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
    const pStr = isStr(proj?.[tk]) ? proj[tk] : '';
    if (pStr) {
      for (const seg of pStr.split('/')) {
        if (seg && ctrlSet.has(seg)) obs.add(seg);
      }
    }
  }
  return ctrls.filter((c) => !obs.has(c));
}

export async function invokeVerifiedCallback(fn, contractId, caseId, key, exp, extra) {
  const src = Function.prototype.toString.call(fn).trim();
  const body = src.includes('=>') ? src.slice(src.indexOf('=>') + 2).trim() : src;
  if (/^\{\s*\}$/u.test(body)) {
    throwAssertionError(`${contractId}.${caseId}: check for then.${key} must inspect the expected value`);
  }
  const res = await fn(exp, extra);
  if (res === false) throwAssertionError(`${contractId}.${caseId}: check for then.${key} returned false`);
  if (res !== true && !/\b(?:assert|expect|throw|check|reject|fail)\b|[!=]==?|[<>]=?/u.test(body)) {
    throwAssertionError(`${contractId}.${caseId}: check for then.${key} must inspect and assert the expected value`);
  }
}

export async function checkViewTable(contractId, caseId, thenTable, seen, view, checks, mutationOverride, metricsStore, getProj) {
  const v = isObj(view) ? view : {};
  const pfx = `${contractId}.${caseId}`;
  const isMut = Boolean(mutationOverride);
  const assertEq = (k, exp, act) => {
    if (act !== exp) throwAssertionError(`${pfx}: expected ${k}=${exp}, got ${act}`);
  };
  const assertBound = (k, op, exp, act) => {
    if (!isFinNum(act) || !isFinNum(Number(exp)) || (op === '<=' ? act > Number(exp) : act < Number(exp))) {
      throwAssertionError(`${pfx}: expected ${k}${op}${exp}, got ${act}`);
    }
  };
  let proj = null;
  for (const [k, exp] of Object.entries(thenTable)) {
    if (checks && typeof checks[k] === 'function') {
      await invokeVerifiedCallback(checks[k], contractId, caseId, k, exp, v);
      seen.add(k);
      continue;
    }
    const els = Array.isArray(v.elements) ? v.elements : [];
    if (k === 'baseline_state') {
      const hasB = Boolean(v.hasBaseline ?? (v.baseline !== undefined && v.baseline !== null));
      const lbl = lowStr(v.baselineLabel ?? v.deltaLabel);
      if (!hasB && /^(?:invariato|unchanged|same|nessuna variazione|[+-]\s*\d)/u.test(lbl)) {
        throwAssertionError(`${pfx}: comparative baseline label "${lbl}" without baseline`);
      }
      const act = v.baseline_state ?? (hasB ? 'compared' : 'first_observation');
      if (act !== exp) {
        throwAssertionError(`${pfx}: expected baseline_state=${JSON.stringify(exp)}, got ${JSON.stringify(act)}`);
      }
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
    } else if (k === 'clipped_elements') {
      const clipped = els.filter(
        (el) => Number(el?.scrollWidth ?? 0) > Number(el?.clientWidth ?? 0)
          || Number(el?.scrollHeight ?? 0) > Number(el?.clientHeight ?? 0),
      ).length;
      assertEq(k, exp, clipped);
    } else if (k === 'horizontal_overflow_px') {
      assertBound(k, '<=', exp, Math.max(0, Number(v.documentWidth ?? 0) - Number(v.viewportWidth ?? 0)));
    } else if (k === 'min_contrast_ratio') {
      let act = Infinity;
      for (const el of els) {
        if (typeof el?.contrastRatio === 'number' && el.contrastRatio < act) act = el.contrastRatio;
      }
      assertBound(k, '>=', exp, Number.isFinite(act) ? act : Number(v.min_contrast_ratio ?? 21));
    } else if (k === 'min_target_px') {
      let act = Infinity;
      for (const el of els) {
        if (el && typeof el.width === 'number' && typeof el.height === 'number' && el.spacingException !== true) {
          act = Math.min(act, Number(el.width), Number(el.height));
        }
      }
      assertBound(k, '>=', exp, Number.isFinite(act) ? act : Number(v.min_target_px ?? 44));
    } else if (k === 'obscured_focus_elements') {
      const tag = els.filter((el) => el && ('obscured' in el || 'focusObscured' in el));
      const obscured = tag.length
        ? tag.filter((el) => (el.focusable ?? true) && (el.obscured === true || el.focusObscured === true)).length
        : Number(v.obscured_focus_elements ?? 0);
      assertEq(k, exp, obscured);
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
      checkProjectedLeaf(contractId, caseId, k, exp, v, proj, mutationOverride, false, 'no check for');
    }
    seen.add(k);
  }
  if (isObj(v.controls) && !Array.isArray(v.unobservedControls)) {
    if (proj === null) proj = getProj();
    v.unobservedControls = computeUnobservedControls(v.controls, thenTable, proj);
  }
}

export function captureSurfaceView(rootOrSelector) {
  const doc = typeof globalThis !== 'undefined' ? globalThis.document : null;
  const win = typeof globalThis !== 'undefined' ? globalThis.window : null;
  const root = typeof rootOrSelector === 'string'
    ? (doc && typeof doc.querySelector === 'function' ? doc.querySelector(rootOrSelector) : null)
    : (rootOrSelector || (doc ? doc.documentElement || doc.body : null));
  if (!root) {
    return { documentWidth: 0, viewportWidth: 0, elements: [], controls: {} };
  }
  const docEl = (root.ownerDocument && root.ownerDocument.documentElement) || (doc && doc.documentElement) || root;
  const documentWidth = Number(docEl.scrollWidth ?? root.scrollWidth ?? 0);
  const viewportWidth = Number(win?.innerWidth ?? docEl.clientWidth ?? root.clientWidth ?? documentWidth);
  const getAttr = (el, k) => (el && typeof el.getAttribute === 'function' ? el.getAttribute(k) : (el && el.attributes && k in el.attributes ? el.attributes[k] : null));
  const rawNodes = typeof root.querySelectorAll === 'function'
    ? [root, ...Array.from(root.querySelectorAll('*'))]
    : [root, ...(Array.isArray(root.children) ? root.children : [])];
  const elements = [];
  const controls = {};
  const INTERACTIVE_TAGS = new Set(['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'A']);
  const INTERACTIVE_ROLES = new Set(['button', 'link', 'textbox', 'combobox', 'checkbox', 'radio', 'tab', 'switch', 'menuitem']);
  const ownerDoc = root.ownerDocument || doc;
  for (const el of rawNodes) {
    if (!el || typeof el !== 'object') continue;
    const tag = String(el.tagName || '').toUpperCase();
    const role = getAttr(el, 'role') || '';
    const dDrift = getAttr(el, 'data-drift');
    const dTestId = dDrift ? null : getAttr(el, 'data-testid');
    const fCtrl = dDrift || dTestId ? null : getAttr(el, 'formcontrolname');
    const key = dDrift || dTestId || fCtrl || getAttr(el, 'name') || getAttr(el, 'id') || '';
    const focusable = Boolean(el.focusable ?? (INTERACTIVE_TAGS.has(tag) || INTERACTIVE_ROLES.has(role) || getAttr(el, 'tabindex') !== null));
    const needRect = focusable || (el.width === undefined && el.clientWidth === undefined) || (el.height === undefined && el.clientHeight === undefined);
    const rect = needRect && typeof el.getBoundingClientRect === 'function' ? el.getBoundingClientRect() : null;
    const width = Number(el.width ?? rect?.width ?? el.clientWidth ?? 44);
    const height = Number(el.height ?? rect?.height ?? el.clientHeight ?? 44);
    const scrollWidth = Number(el.scrollWidth ?? width);
    const clientWidth = Number(el.clientWidth ?? width);
    const scrollHeight = Number(el.scrollHeight ?? height);
    const clientHeight = Number(el.clientHeight ?? height);
    let obscured = Boolean(el.obscured ?? el.focusObscured ?? false);
    if (!obscured && focusable && rect && width > 0 && height > 0 && ownerDoc && typeof ownerDoc.elementFromPoint === 'function') {
      const hitEl = ownerDoc.elementFromPoint(Number(rect.left ?? 0) + width / 2, Number(rect.top ?? 0) + height / 2);
      if (hitEl && hitEl !== el && (typeof el.contains !== 'function' || !el.contains(hitEl)) && (typeof hitEl.contains !== 'function' || !hitEl.contains(el))) {
        obscured = true;
      }
    }
    elements.push({
      ...(key ? { id: key } : {}),
      scrollWidth,
      clientWidth,
      scrollHeight,
      clientHeight,
      width,
      height,
      focusable,
      obscured,
      ...(typeof el.contrastRatio === 'number' ? { contrastRatio: el.contrastRatio } : {}),
    });
    const isControl = Boolean(key && (focusable || dDrift || dTestId || fCtrl));
    if (isControl && !(key in controls)) {
      const hidden = Boolean(el.hidden === true || getAttr(el, 'hidden') !== null || getAttr(el, 'aria-hidden') === 'true');
      const disabled = Boolean(el.disabled === true || getAttr(el, 'disabled') !== null || getAttr(el, 'aria-disabled') === 'true');
      const readonly = Boolean(el.readOnly === true || getAttr(el, 'readonly') !== null || getAttr(el, 'aria-readonly') === 'true');
      const state = hidden ? 'hidden' : (disabled ? 'disabled' : (readonly ? 'readonly' : 'enabled'));
      const entry = {
        state,
        disabled,
        readonly,
        hidden,
        ...(role ? { role } : {}),
      };
      if (typeof el.checked === 'boolean') entry.checked = el.checked;
      else if (getAttr(el, 'aria-checked') !== null) entry.checked = getAttr(el, 'aria-checked') === 'true';
      const val = el.value !== undefined ? el.value : getAttr(el, 'value');
      if (val !== null && val !== undefined) entry.value = val;
      const href = getAttr(el, 'href');
      if (href !== null && href !== undefined) entry.href = href;
      const txt = typeof el.textContent === 'string' ? el.textContent.trim() : (typeof el.innerText === 'string' ? el.innerText.trim() : '');
      if (txt) entry.text = txt;
      let scannedAttrs = false;
      if (el.attributes) {
        if (typeof el.attributes[Symbol.iterator] === 'function') {
          scannedAttrs = true;
          for (const a of el.attributes) {
            if (a && isStr(a.name) && (a.name.startsWith('data-') || a.name.startsWith('aria-'))) entry[a.name] = a.value;
          }
        } else if (isObj(el.attributes)) {
          for (const [ak, av] of Object.entries(el.attributes)) {
            if ((ak.startsWith('data-') || ak.startsWith('aria-')) && av !== null && av !== undefined) entry[ak] = av;
          }
        }
      }
      if (!scannedAttrs) {
        for (const dk of ['data-mode', 'data-phase', 'data-status', 'aria-expanded', 'aria-invalid']) {
          if (!(dk in entry)) {
            const dv = getAttr(el, dk);
            if (dv !== null && dv !== undefined) entry[dk] = dv;
          }
        }
      }
      controls[key] = entry;
    }
  }
  return { documentWidth, viewportWidth, elements, controls };
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
