// Surface key evaluation and DOM capture helper for DRIFT JS bridge.
import {
  checkRequiredAdapterCapability,
  evaluateElementClipping,
  evaluateFocusObscuration,
  evaluateWcag22Contrast,
  isElementHidden,
  isElementScrollable,
} from './drift_ui.mjs';

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isStr = (v) => typeof v === 'string';
const isFinNum = (v) => typeof v === 'number' && Number.isFinite(v);

export function checkSurfaceKey(contractId, caseId, k, exp, v, thenTable, proj, mutationOverride, checkRelationalLeaf, throwAssertionError) {
  const pfx = `${contractId}.${caseId}`;
  const failUnverifiable = (msg) => {
    if (isObj(v.evidence) && typeof v.evidence.unverifiable_checks === 'number') {
      v.evidence.unverifiable_checks += 1;
      if (Array.isArray(v.evidence.unverifiable_reasons)) {
        v.evidence.unverifiable_reasons.push(`unverifiable_then:${k}`);
      }
    }
    throwAssertionError(msg);
  };
  const assertEq = (key, expected, act) => { if (act !== expected) throwAssertionError(`${pfx}: expected ${key}=${expected}, got ${act}`); };
  const assertBound = (key, op, expected, act) => {
    if (!isFinNum(act) || !isFinNum(Number(expected)) || (op === '<=' ? act > Number(expected) : act < Number(expected))) {
      throwAssertionError(`${pfx}: expected ${key}${op}${expected}, got ${act}`);
    }
  };
  if (v.adapter?.capabilities) {
    checkRequiredAdapterCapability(contractId, caseId, k, v, proj);
  }
  const els = Array.isArray(v.elements) ? v.elements : [];
  if (k === 'clipped_elements' || k === 'unintentional_clipped_count') {
    const explicitClipped = v[k] ?? v.presentation?.clipping?.unintentional_clipped_count;
    if (els.length === 0 && !isFinNum(explicitClipped)) {
      failUnverifiable(`${pfx}: unverifiable then.${k}: empty surface view`);
    }
    const clipped = isFinNum(explicitClipped) && els.length === 0
      ? Number(explicitClipped)
      : els.filter((el) => evaluateElementClipping(el).clipped).length;
    assertEq(k, exp, clipped);
    return true;
  }
  if (k === 'horizontal_overflow_px') {
    const explicitOverflow = v.horizontal_overflow_px ?? v.presentation?.horizontal_overflow_px;
    const hasViewport = isFinNum(v.viewportWidth) && Number(v.viewportWidth) > 0 && isFinNum(v.documentWidth);
    if (!hasViewport && !isFinNum(explicitOverflow)) {
      failUnverifiable(`${pfx}: unverifiable then.horizontal_overflow_px: missing viewportWidth`);
    }
    const actOverflow = isFinNum(explicitOverflow) && !hasViewport
      ? Number(explicitOverflow)
      : Math.max(0, Number(v.documentWidth ?? 0) - Number(v.viewportWidth ?? 0));
    assertBound(k, '<=', exp, actOverflow);
    return true;
  }
  if (
    k === 'min_contrast_ratio'
    || k === 'min_contrast_wcag22'
    || k === 'min_contrast_text_normal'
    || k === 'min_contrast_text_large'
    || k === 'min_contrast_ui_component'
  ) {
    const cSum = evaluateWcag22Contrast(els);
    if (cSum.unverifiableCount > 0 && !('contrast_unverifiable_count' in thenTable) && !('unverifiable_checks' in thenTable)) {
      failUnverifiable(`${pfx}: unverifiable then.${k}: ${cSum.unverifiableCount} element(s) have indeterminate background`);
    }
    const cPres = v.presentation?.contrast_wcag22;
    let act = null;
    if (k === 'min_contrast_text_normal') {
      act = cSum.textNormalMin ?? cPres?.text_normal_min ?? (isFinNum(v[k]) ? Number(v[k]) : null);
    } else if (k === 'min_contrast_text_large') {
      act = cSum.textLargeMin ?? cPres?.text_large_min ?? (isFinNum(v[k]) ? Number(v[k]) : null);
    } else if (k === 'min_contrast_ui_component') {
      act = cSum.uiComponentMin ?? cPres?.ui_component_min ?? (isFinNum(v[k]) ? Number(v[k]) : null);
    } else {
      act = cSum.overallMin ?? (isFinNum(v[k]) ? Number(v[k]) : (isFinNum(v.min_contrast_ratio) ? Number(v.min_contrast_ratio) : null));
    }
    if (!isFinNum(act)) {
      failUnverifiable(`${pfx}: unverifiable then.${k}: no measured elements`);
    }
    if (isObj(exp) && ('min' in exp || 'max' in exp)) {
      checkRelationalLeaf(contractId, caseId, k, exp, act, v, proj || {}, mutationOverride);
    } else {
      assertBound(k, '>=', exp, act);
    }
    return true;
  }
  if (k === 'contrast_violations_count' || k === 'contrast_unverifiable_count') {
    const cSum = evaluateWcag22Contrast(els);
    const cPres = v.presentation?.contrast_wcag22;
    const hasExplicit = isFinNum(v[k]) || (k === 'contrast_violations_count' ? isFinNum(cPres?.violations_count) : isFinNum(cPres?.unverifiable_count));
    if (cSum.measuredCount === 0 && cSum.unverifiableCount === 0 && !hasExplicit) {
      failUnverifiable(`${pfx}: unverifiable then.${k}: no measured elements`);
    }
    const act = k === 'contrast_violations_count'
      ? Number(v[k] ?? cPres?.violations_count ?? cSum.violationsCount)
      : Number(v[k] ?? cPres?.unverifiable_count ?? cSum.unverifiableCount);
    assertEq(k, exp, act);
    return true;
  }
  if (k === 'min_target_px') {
    let act = Infinity;
    for (const el of els) {
      if (!isObj(el) || isElementHidden(el) || el.spacingException === true) continue;
      if (isFinNum(el.width) && isFinNum(el.height) && el.width > 0 && el.height > 0) {
        act = Math.min(act, Number(el.width), Number(el.height));
      }
    }
    if (!Number.isFinite(act)) {
      const explicitTarget = v.min_target_px ?? v.presentation?.target_size?.min_target_size;
      if (!isFinNum(explicitTarget)) {
        failUnverifiable(`${pfx}: unverifiable then.min_target_px: no measured elements`);
      }
      act = Number(explicitTarget);
    }
    assertBound(k, '>=', exp, act);
    return true;
  }
  if (k === 'obscured_focus_elements' || k === 'fully_obscured_focus_count' || k === 'partially_obscured_focus_count') {
    const applicable = els.filter((el) => isObj(el) && !isElementHidden(el) && (el.focusable ?? true));
    const evaluated = applicable.map((el) => evaluateFocusObscuration(el, null)).filter((r) => r.status === 'measured');
    const explicitVal = v[k] ?? (
      k === 'partially_obscured_focus_count'
        ? v.presentation?.focus_visibility?.partially_obscured_count
        : v.presentation?.focus_visibility?.fully_obscured_count
    );
    if (evaluated.length === 0 && !isFinNum(explicitVal)) {
      failUnverifiable(`${pfx}: unverifiable then.${k}: no measured elements`);
    }
    const obscured = evaluated.length > 0
      ? evaluated.filter((r) => (k === 'partially_obscured_focus_count' ? r.partiallyObscured : r.fullyObscured)).length
      : Number(explicitVal);
    assertEq(k, exp, obscured);
    return true;
  }
  if (k === 'unverified_elements' || k === 'unverifiable_checks') {
    const rawU = v.unverified_elements ?? v.unverifiable_checks ?? v.evidence?.unverifiable_checks;
    if (!isFinNum(rawU) && els.length === 0) {
      failUnverifiable(`${pfx}: unverifiable then.${k}: empty surface view`);
    }
    assertEq(k, exp, Number(rawU ?? 0));
    return true;
  }
  return false;
}

export function captureSurfaceDom(rootOrSelector, options) {
  const doc = typeof globalThis !== 'undefined' ? globalThis.document : null;
  const win = typeof globalThis !== 'undefined' ? globalThis.window : null;
  const root = typeof rootOrSelector === 'string'
    ? (doc && typeof doc.querySelector === 'function' ? doc.querySelector(rootOrSelector) : null)
    : (rootOrSelector || (doc ? doc.documentElement || doc.body : null));
  if (!root) {
    return {
      surfaceFound: false,
      surface_found: false,
      documentWidth: 0,
      viewportWidth: 0,
      elements: [],
      controls: {},
      unverifiableChecks: 1,
      unverifiable_checks: 1,
      unverified_elements: 1,
      unverifiableReasons: ['surface.missing'],
    };
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
  let unverifiableChecks = 0;
  const unverifiableReasons = [];
  for (const el of rawNodes) {
    if (!el || typeof el !== 'object') continue;
    const tag = String(el.tagName || '').toUpperCase();
    const role = getAttr(el, 'role') || '';
    const dDrift = getAttr(el, 'data-drift');
    const dTestId = dDrift ? null : getAttr(el, 'data-testid');
    const fCtrl = dDrift || dTestId ? null : getAttr(el, 'formcontrolname');
    const key = dDrift || dTestId || fCtrl || getAttr(el, 'name') || getAttr(el, 'id') || '';
    const hidden = Boolean(
      el.hidden === true
      || getAttr(el, 'hidden') !== null
      || getAttr(el, 'aria-hidden') === 'true'
      || el.presence === 'hidden'
      || el.presence === 'absent'
      || el.style?.display === 'none',
    );
    const presence = el.presence || (hidden ? 'hidden' : 'visible');
    const focusable = Boolean(el.focusable ?? (INTERACTIVE_TAGS.has(tag) || INTERACTIVE_ROLES.has(role) || getAttr(el, 'tabindex') !== null));
    const rect = typeof el.getBoundingClientRect === 'function' ? el.getBoundingClientRect() : el.rect;
    const rawW = el.width ?? rect?.width ?? el.clientWidth;
    const rawH = el.height ?? rect?.height ?? el.clientHeight;
    const hasMeasuredSize = isFinNum(Number(rawW)) && isFinNum(Number(rawH)) && Number(rawW) > 0 && Number(rawH) > 0;
    const width = hasMeasuredSize ? Number(rawW) : undefined;
    const height = hasMeasuredSize ? Number(rawH) : undefined;
    const scrollWidth = Number(el.scrollWidth ?? width ?? 0);
    const clientWidth = Number(el.clientWidth ?? width ?? 0);
    const scrollHeight = Number(el.scrollHeight ?? height ?? 0);
    const clientHeight = Number(el.clientHeight ?? height ?? 0);
    const focusEval = evaluateFocusObscuration({ ...el, rect, width, height, focusable, hidden, presence }, ownerDoc);
    const obscured = focusEval.fullyObscured;
    const partiallyObscured = focusEval.partiallyObscured;
    const scrollable = isElementScrollable(el);
    if (!hidden && (el.contrastUnverifiable === true || el.backgroundUnverifiable === true)) {
      unverifiableChecks += 1;
      unverifiableReasons.push(`contrast_unverifiable:${key || tag || 'element'}`);
    }
    elements.push({
      ...(key ? { id: key } : {}),
      presence,
      hidden,
      status: hidden ? 'not_applicable' : (hasMeasuredSize ? 'measured' : 'unverifiable'),
      scrollWidth,
      clientWidth,
      scrollHeight,
      clientHeight,
      ...(width !== undefined ? { width } : {}),
      ...(height !== undefined ? { height } : {}),
      ...(scrollable ? { scrollable: true } : {}),
      ...(el.overflowX ? { overflowX: el.overflowX } : {}),
      ...(el.overflowY ? { overflowY: el.overflowY } : {}),
      focusable,
      obscured,
      fullyObscured: obscured,
      partiallyObscured,
      ...(typeof el.contrastRatio === 'number' ? { contrastRatio: el.contrastRatio } : {}),
      ...(el.contrastCategory ? { contrastCategory: el.contrastCategory } : {}),
      ...(el.backgroundUnverifiable === true || el.contrastUnverifiable === true ? { contrastUnverifiable: true } : {}),
    });
    const isControl = Boolean(key && (focusable || dDrift || dTestId || fCtrl));
    if (isControl && !(key in controls)) {
      const disabled = Boolean(el.disabled === true || getAttr(el, 'disabled') !== null || getAttr(el, 'aria-disabled') === 'true');
      const readonly = Boolean(el.readOnly === true || getAttr(el, 'readonly') !== null || getAttr(el, 'aria-readonly') === 'true');
      const state = hidden ? 'hidden' : (disabled ? 'disabled' : (readonly ? 'readonly' : 'enabled'));
      const entry = {
        state,
        presence,
        evidence_status: hidden ? 'not_applicable' : (hasMeasuredSize ? 'measured' : 'unverifiable'),
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
  const expectedCtrls = isObj(options?.expectedControls) ? options.expectedControls : null;
  if (expectedCtrls) {
    for (const [ctrlId, expPres] of Object.entries(expectedCtrls)) {
      const want = String(expPres).toLowerCase();
      const ctrl = controls[ctrlId];
      const elMatch = elements.find((e) => e.id === ctrlId);
      if (want === 'visible' && (!ctrl || ctrl.hidden || (elMatch && elMatch.status === 'unverifiable'))) {
        unverifiableChecks += 1;
        unverifiableReasons.push(`expected_visible_unverifiable:${ctrlId}`);
      }
    }
  }
  return {
    surfaceFound: true,
    surface_found: true,
    documentWidth,
    viewportWidth,
    elements,
    controls,
    unverifiableChecks,
    unverifiable_checks: unverifiableChecks,
    unverified_elements: unverifiableChecks,
    unverifiableReasons,
  };
}

const REL_KEYS = new Set([
  'min', 'max', 'min_len', 'max_len', 'non_empty', 'le_field', 'ge_field', 'eq_field', 'in',
  'not_in', 'sum_fields', 'contains', 'prefix', 'suffix', 'allowed_keys', 'forbid_keys',
]);
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
  const out = cloneJson(rawThen), maxU = (a, b) => (a === undefined ? b : Math.max(a, b)), minU = (a, b) => (a === undefined ? b : Math.min(a, b));
  const numB = (v, k) => (isRelationalMap(v) && typeof v[k] === 'number' ? v[k] : undefined);
  const countMap = (arr) => { const m = new Map(); for (const s of arr) { const c = canonicalStubRef(s, wp, tp); if (c) m.set(c, (m.get(c) || 0) + 1); } return m; };
  const lookupBounds = (ref) => {
    const ck = canonicalStubRef(ref, wp, tp), bare = isStr(ref) ? ref.trim().replace(/^\/+/u, '') : '';
    for (const [m, pm] of [[out, tp], [whenMap || {}, wp]]) {
      for (const [k, v] of Object.entries(m)) {
        if (k === ref || k === bare || canonicalStubRef(k, wp, pm) === ck) {
          if (typeof v === 'number') return { lo: v, hi: v };
          if (isRelationalMap(v)) return { lo: numB(v, 'min'), hi: numB(v, 'max') };
        }
      }
    }
    return { lo: undefined, hi: undefined };
  };
  for (let pass = 0; pass < 3; pass++) {
    for (const [tk, tv] of Object.entries(out)) {
      if (!isRelationalMap(tv)) continue;
      const ckTarget = canonicalStubRef(tk, wp, tp);
      let loK = numB(tv, 'min'), hiK = numB(tv, 'max');
      for (const pk of ['eq_field', 'le_field', 'ge_field']) {
        if (!(pk in tv)) continue;
        const pb = lookupBounds(tv[pk]);
        if ((pk === 'eq_field' || pk === 'ge_field') && pb.lo !== undefined) loK = maxU(loK, pb.lo);
        if ((pk === 'eq_field' || pk === 'le_field') && pb.hi !== undefined) hiK = minU(hiK, pb.hi);
      }
      for (const [pk, pv] of Object.entries(out)) {
        if (pk === tk || !isRelationalMap(pv)) continue;
        const pLo = numB(pv, 'min'), pHi = numB(pv, 'max');
        if ('eq_field' in pv && canonicalStubRef(pv.eq_field, wp, tp) === ckTarget) {
          if (pLo !== undefined) loK = maxU(loK, pLo);
          if (pHi !== undefined) hiK = minU(hiK, pHi);
        }
        if ('le_field' in pv && canonicalStubRef(pv.le_field, wp, tp) === ckTarget && pLo !== undefined) loK = maxU(loK, pLo);
        if ('ge_field' in pv && canonicalStubRef(pv.ge_field, wp, tp) === ckTarget && pHi !== undefined) hiK = minU(hiK, pHi);
      }
      for (const [sk, sv] of Object.entries(out)) {
        if (sk === tk || !isRelationalMap(sv) || !Array.isArray(sv.sum_fields) || sv.sum_fields.length < 2) continue;
        const sLo = numB(sv, 'min'), sHi = numB(sv, 'max');
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
          const bLo = numB(bv, 'min'), bHi = numB(bv, 'max');
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
          const bLo = numB(bv, 'min'), bHi = numB(bv, 'max');
          if (bLo === undefined && bHi === undefined) continue;
          const multB = countMap(bv.sum_fields);
          if (multB.has(ckTarget) || mult.size !== 2 || multB.size !== 2) continue;
          const yCk = [...mult.keys()].find((x) => x !== ckTarget);
          if (!yCk || mult.get(yCk) !== 1 || multB.get(yCk) !== 1) continue;
          const zCk = [...multB.keys()].find((x) => x !== yCk);
          for (const [ck3, cv3] of Object.entries(out)) {
            if (ck3 === sk || ck3 === bk || ck3 === tk || !isRelationalMap(cv3) || !Array.isArray(cv3.sum_fields) || cv3.sum_fields.length !== sv.sum_fields.length) continue;
            const multC = countMap(cv3.sum_fields);
            if (multC.size === 2 && multC.get(ckTarget) === mk && multC.get(zCk) === 1) {
              const cLo = numB(cv3, 'min'), cHi = numB(cv3, 'max');
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
