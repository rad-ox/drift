// Surface key evaluation and DOM capture helper for DRIFT JS bridge (D282).
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
  const hasSurfaceEvidence = v.surfaceFound === true || v.surface_found === true || els.length > 0;
  if (k === 'clipped_elements' || k === 'unintentional_clipped_count') {
    const explicitClipped = v[k] ?? v.presentation?.clipping?.unintentional_clipped_count;
    if (!hasSurfaceEvidence && !isFinNum(explicitClipped)) {
      throwAssertionError(`${pfx}: unverifiable then.${k}: empty surface view`);
    }
    const clipped = isFinNum(explicitClipped) && els.length === 0
      ? Number(explicitClipped)
      : els.filter((el) => evaluateElementClipping(el).clipped).length;
    assertEq(k, exp, clipped);
    return true;
  }
  if (k === 'horizontal_overflow_px') {
    const explicitOverflow = v.horizontal_overflow_px ?? v.presentation?.horizontal_overflow_px;
    const hasViewport = (isFinNum(v.viewportWidth) && Number(v.viewportWidth) > 0) || v.surfaceFound === true || v.surface_found === true;
    if (!hasViewport && !isFinNum(explicitOverflow)) {
      throwAssertionError(`${pfx}: unverifiable then.horizontal_overflow_px: missing viewportWidth`);
    }
    const actOverflow = isFinNum(explicitOverflow) && !(isFinNum(v.viewportWidth) && Number(v.viewportWidth) > 0)
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
      throwAssertionError(`${pfx}: unverifiable then.${k}: ${cSum.unverifiableCount} element(s) have indeterminate background`);
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
      throwAssertionError(`${pfx}: unverifiable then.${k}: no measured elements`);
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
    if (cSum.measuredCount === 0 && cSum.unverifiableCount === 0 && !isFinNum(v[k]) && !isObj(cPres)) {
      throwAssertionError(`${pfx}: unverifiable then.${k}: no measured elements`);
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
        throwAssertionError(`${pfx}: unverifiable then.min_target_px: no measured elements`);
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
    if (evaluated.length === 0 && !hasSurfaceEvidence && !isFinNum(explicitVal)) {
      throwAssertionError(`${pfx}: unverifiable then.${k}: no measured elements`);
    }
    const obscured = evaluated.length > 0
      ? evaluated.filter((r) => (k === 'partially_obscured_focus_count' ? r.partiallyObscured : r.fullyObscured)).length
      : Number(explicitVal ?? 0);
    assertEq(k, exp, obscured);
    return true;
  }
  if (k === 'unverified_elements' || k === 'unverifiable_checks') {
    const act = Number(v.unverified_elements ?? v.unverifiable_checks ?? v.evidence?.unverifiable_checks ?? 0);
    assertEq(k, exp, act);
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
