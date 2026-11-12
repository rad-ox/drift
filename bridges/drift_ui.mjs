// Cross-platform UI surface, interaction sequence, and adapter normalization for DRIFT.
import crypto from 'node:crypto';
import fs from 'node:fs';
import { buildComposePayload, buildUiaPayload, deriveObservedCapabilities, evaluateTaskRecovery, isPointCoveredByVisualOverlays, optAdapter } from './drift_ui_recovery.mjs';

const ALLOWED_DRIFT_ENV_KEYS = new Set(['adapter', 'config', 'deps', 'drift', 'policy', 'runner', 'toolchain']);
const PREDICATE_CAPABILITY = {
  ...Object.fromEntries(['min_contrast_ratio', 'min_contrast_wcag22', 'min_contrast_text_normal', 'min_contrast_text_large', 'min_contrast_ui_component', 'contrast_violations_count'].map((k) => [k, 'wcag22_contrast'])),
  ...Object.fromEntries(['assistive_announcement', 'active_assistive_focus'].map((k) => [k, 'assistive_focus'])),
  ...Object.fromEntries(['observed_transition_ms', 'max_transition_ms'].map((k) => [k, 'observed_transition'])),
  scroll_context_preserved: 'scroll_state',
  ...Object.fromEntries(['horizontal_overflow_px', 'min_target_px', 'clipped_elements', 'unintentional_clipped_count', 'obscured_focus_elements', 'fully_obscured_focus_count', 'partially_obscured_focus_count', 'notice_precedes_detail'].map((k) => [k, 'geometry'])),
  ...Object.fromEntries(['after_focus_role', 'active_focus', 'trigger_restored', 'unexpected_focus_steals'].map((k) => [k, 'input_focus'])),
};
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isFinNum = (v) => typeof v === 'number' && Number.isFinite(v);
const finOrNull = (v) => (isFinNum(v) ? Number(v) : null);
const boolOrNull = (v, fb) => (typeof v === 'boolean' ? v : fb);

export function isElementHidden(el) {
  if (!isObj(el)) return false;
  const pres = String(el.presence ?? el.state ?? '').toLowerCase();
  if (['hidden', 'absent', 'collapsed'].includes(pres) || el.hidden === true || el.ariaHidden === true || el['aria-hidden'] === 'true') return true;
  return String(el.display ?? el.style?.display ?? '').toLowerCase() === 'none' || ['hidden', 'collapse'].includes(String(el.visibility ?? el.style?.visibility ?? '').toLowerCase());
}

export function isElementScrollable(el, axis = 'both') {
  if (!isObj(el)) return false;
  if (typeof el.scrollable === 'boolean') return el.scrollable;
  const ox = String(el.overflowX ?? el.style?.overflowX ?? el.overflow ?? el.style?.overflow ?? '').toLowerCase();
  const oy = String(el.overflowY ?? el.style?.overflowY ?? el.overflow ?? el.style?.overflow ?? '').toLowerCase();
  const sx = ox === 'auto' || ox === 'scroll' || el.horizontallyScrollable === true;
  const sy = oy === 'auto' || oy === 'scroll' || el.verticallyScrollable === true;
  return axis === 'x' ? sx : (axis === 'y' ? sy : (sx || sy));
}

export function evaluateElementClipping(el) {
  if (!isObj(el) || isElementHidden(el)) return { clipped: false, scrollable: false, status: 'not_applicable' };
  const sx = isElementScrollable(el, 'x'), sy = isElementScrollable(el, 'y');
  return { clipped: (Number(el.scrollWidth ?? 0) > Number(el.clientWidth ?? 0) && !sx) || (Number(el.scrollHeight ?? 0) > Number(el.clientHeight ?? 0) && !sy), scrollable: sx || sy, status: 'measured' };
}

export function evaluateFocusObscuration(el, ownerDoc) {
  if (!isObj(el) || isElementHidden(el) || el.focusable === false) return { fullyObscured: false, partiallyObscured: false, status: 'not_applicable' };
  if (typeof el.fullyObscured === 'boolean' || typeof el.partiallyObscured === 'boolean') {
    const full = Boolean(el.fullyObscured);
    return { fullyObscured: full, partiallyObscured: Boolean(el.partiallyObscured || full), status: 'measured' };
  }
  if (Array.isArray(el.hitPoints) && el.hitPoints.length > 0) {
    const cov = el.hitPoints.filter((p) => p === true || (isObj(p) && p.covered === true)).length;
    return { fullyObscured: cov === el.hitPoints.length, partiallyObscured: cov > 0, status: 'measured' };
  }
  const rect = typeof el.getBoundingClientRect === 'function' ? el.getBoundingClientRect() : el.rect;
  const w = Number(el.width ?? rect?.width ?? el.clientWidth ?? 0), h = Number(el.height ?? rect?.height ?? el.clientHeight ?? 0);
  const overlays = Array.isArray(el.visualOverlays) ? el.visualOverlays : (Array.isArray(ownerDoc?.visualOverlays) ? ownerDoc.visualOverlays : []);
  const hasHitFn = Boolean(ownerDoc && typeof ownerDoc.elementFromPoint === 'function');
  if (rect && w > 0 && h > 0 && (hasHitFn || overlays.length > 0)) {
    const left = Number(rect.left ?? rect.x ?? 0), top = Number(rect.top ?? rect.y ?? 0), ix = Math.min(2, w / 4), iy = Math.min(2, h / 4);
    const pts = [[left + w / 2, top + h / 2], [left + ix, top + iy], [left + w - ix, top + iy], [left + ix, top + h - iy], [left + w - ix, top + h - iy]];
    let covered = 0;
    for (const [px, py] of pts) {
      const hitEl = hasHitFn ? ownerDoc.elementFromPoint(px, py) : null;
      const hitCov = Boolean(hitEl && hitEl !== el && (typeof el.contains !== 'function' || !el.contains(hitEl)) && (typeof hitEl.contains !== 'function' || !hitEl.contains(el)));
      if (hitCov || isPointCoveredByVisualOverlays(px, py, el, overlays)) covered += 1;
    }
    return { fullyObscured: covered === pts.length, partiallyObscured: covered > 0, status: 'measured' };
  }
  if ('obscured' in el || 'focusObscured' in el) {
    const obs = Boolean(el.obscured ?? el.focusObscured);
    return { fullyObscured: obs, partiallyObscured: obs, status: 'measured' };
  }
  return { fullyObscured: false, partiallyObscured: false, status: 'unverifiable' };
}

export function evaluateWcag22Contrast(elements) {
  let tn = Infinity, tl = Infinity, uc = Infinity, ov = Infinity, violationsCount = 0, unverifiableCount = 0, measuredCount = 0;
  for (const el of Array.isArray(elements) ? elements : []) {
    if (!isObj(el) || isElementHidden(el)) continue;
    if (el.contrastUnverifiable === true || el.backgroundUnverifiable === true) { unverifiableCount += 1; continue; }
    const ratio = el.contrastRatio ?? el.contrast_ratio;
    if (!isFinNum(ratio)) continue;
    measuredCount += 1;
    if (ratio < ov) ov = ratio;
    const cat = String(el.contrastCategory ?? el.category ?? 'text_normal').toLowerCase();
    if (cat === 'text_large') tl = Math.min(tl, ratio);
    else if (cat === 'ui_component') uc = Math.min(uc, ratio);
    else tn = Math.min(tn, ratio);
    if (ratio + 1e-9 < (cat === 'text_large' || cat === 'ui_component' ? 3.0 : 4.5)) violationsCount += 1;
  }
  return { measuredCount, overallMin: Number.isFinite(ov) ? ov : null, textNormalMin: Number.isFinite(tn) ? tn : null, textLargeMin: Number.isFinite(tl) ? tl : null, uiComponentMin: Number.isFinite(uc) ? uc : null, violationsCount, unverifiableCount };
}

export function deriveNonColorCue(node) {
  if (!isObj(node)) return { has_visible_text: false, has_graphic_icon: false, has_semantic_role: false, non_color_encoded: false };
  const role = String(node.semantic_role ?? node.role ?? '').toLowerCase();
  if (isObj(node.content_cues)) {
    const ht = Boolean(node.content_cues.has_visible_text), hi = Boolean(node.content_cues.has_graphic_icon);
    const hs = Boolean(node.content_cues.has_semantic_role ?? ['alert', 'alertdialog', 'status'].includes(role));
    return { has_visible_text: ht, has_graphic_icon: hi, has_semantic_role: hs, non_color_encoded: ht && (hi || hs) };
  }
  const ht = String(node.text ?? node.textContent ?? node.label ?? '').trim().length > 0 && !isElementHidden(node);
  const hi = Boolean(node.hasIcon === true || node.icon === true || (Array.isArray(node.children) && node.children.some((c) => isObj(c) && !isElementHidden(c) && (String(c.tagName ?? '').toUpperCase() === 'SVG' || String(c.role ?? '').toLowerCase() === 'img' || Boolean(c.isIcon)))));
  const hs = ['alert', 'alertdialog', 'status'].includes(role);
  return { has_visible_text: ht, has_graphic_icon: hi, has_semantic_role: hs, non_color_encoded: ht && (hi || hs) };
}

export function observeUiSequence(spec) {
  const s = isObj(spec) ? spec : {};
  const rawRoles = isObj(s.roles) ? s.roles : {};
  const elements = Array.isArray(s.elements) ? s.elements : [];
  const hasExplicitMissing = s.surface_found === false || s.surfaceFound === false;
  const surfaceFound = !hasExplicitMissing && (Object.keys(rawRoles).length > 0 || elements.length > 0);
  const adapterName = String(s.adapter?.name ?? s.adapter ?? 'playwright-web');
  const explicitCaps = Array.isArray(s.adapter?.capabilities ?? s.capabilities)
    ? [...(s.adapter?.capabilities ?? s.capabilities)]
    : null;

  const roles = {};
  let unverifiableChecks = Number(s.evidence?.unverifiable_checks ?? s.unverifiableChecks ?? 0);
  const unverifiableReasons = Array.isArray(s.evidence?.unverifiable_reasons) ? [...s.evidence.unverifiable_reasons] : [];
  let measuredChecks = 0;
  let notApplicableChecks = 0;

  if (!surfaceFound) {
    unverifiableChecks += 1;
    unverifiableReasons.push('surface.missing');
  }

  for (const [roleId, rRaw] of Object.entries(rawRoles)) {
    const r = isObj(rRaw) ? { ...rRaw } : { presence: 'absent' };
    const presence = String(r.presence ?? (isElementHidden(r) ? 'hidden' : 'visible')).toLowerCase();
    r.presence = presence;
    const expectedPresence = r.expected_presence ? String(r.expected_presence).toLowerCase() : null;
    if (expectedPresence === 'visible' && presence !== 'visible') {
      unverifiableChecks += 1;
      unverifiableReasons.push(`missing_expected_visible:${roleId}`);
    }
    if (presence !== 'visible') {
      r.status = 'not_applicable';
      notApplicableChecks += 1;
    } else {
      const geom = isObj(r.geometry) ? r.geometry : null;
      const w = Number(geom?.width ?? r.width ?? -1);
      const h = Number(geom?.height ?? r.height ?? -1);
      if (!(w > 0 && h > 0)) {
        r.status = 'unverifiable';
        unverifiableChecks += 1;
        unverifiableReasons.push(`unverifiable_geometry:${roleId}`);
      } else {
        r.status = 'measured';
        measuredChecks += 1;
      }
    }
    if (roleId === 'notice' || 'content_cues' in r || 'nonColorCue' in r || 'text' in r || 'semantic_role' in r) {
      r.content_cues = deriveNonColorCue(r);
    }
    roles[roleId] = r;
  }

  const before = isObj(s.sequence?.before ?? s.before) ? { ...(s.sequence?.before ?? s.before) } : {};
  const action = isObj(s.sequence?.action ?? s.action) ? { ...(s.sequence?.action ?? s.action) } : {};
  const transRaw = isObj(s.sequence?.transition ?? s.transition) ? { ...(s.sequence?.transition ?? s.transition) } : {};
  const afterRaw = isObj(s.sequence?.after ?? s.after) ? { ...(s.sequence?.after ?? s.after) } : {};

  const configuredMs = finOrNull(transRaw.configured_duration_ms ?? transRaw.configuredDurationMs);
  const observedMs = finOrNull(transRaw.observed_duration_ms ?? transRaw.observedDurationMs);
  const rawFocusTrace = transRaw.focus_trace ?? transRaw.focusTrace;
  const focusTrace = Array.isArray(rawFocusTrace) ? rawFocusTrace : [];

  const noticeRole = roles.notice;
  const detailRole = roles.detail;
  const summaryRole = roles.summary;
  const noticeSem = String(noticeRole?.semantic_role ?? noticeRole?.role ?? '').toLowerCase();

  const afterFocusRole = String(afterRaw.input_focus_role ?? afterRaw.inputFocusRole ?? '');
  const beforeFocusRole = String(before.input_focus_role ?? before.inputFocusRole ?? '');
  const rawSteals = transRaw.unexpected_focus_steals ?? transRaw.unexpectedFocusSteals;
  const hasFocusObs = isFinNum(rawSteals) || Array.isArray(rawFocusTrace) || Boolean(afterFocusRole || beforeFocusRole);
  let unexpectedFocusSteals = isFinNum(rawSteals) ? Number(rawSteals) : (hasFocusObs ? 0 : null);
  if (noticeRole?.presence === 'visible' && noticeSem === 'alert' && (focusTrace.includes('notice') || afterFocusRole === 'notice')) {
    unexpectedFocusSteals = (unexpectedFocusSteals ?? 0) + 1;
  }

  const selectedBefore = before.selected_entity_id ?? before.selectedEntityId;
  const selectedAfter = afterRaw.selected_entity_id ?? afterRaw.selectedEntityId ?? summaryRole?.selected_entity_id;
  const selectionPreserved = boolOrNull(
    afterRaw.selection_preserved,
    selectedBefore !== undefined && selectedAfter !== undefined ? selectedBefore === selectedAfter : null,
  );

  const dirtyBefore = isObj(before.dirty_inputs ?? before.dirtyInputs) ? (before.dirty_inputs ?? before.dirtyInputs) : null;
  const dirtyAfter = isObj(afterRaw.dirty_inputs ?? afterRaw.dirtyInputs) ? (afterRaw.dirty_inputs ?? afterRaw.dirtyInputs) : null;
  const dirtyInputsPreserved = boolOrNull(
    afterRaw.dirty_inputs_preserved,
    dirtyBefore && dirtyAfter ? JSON.stringify(dirtyBefore) === JSON.stringify(dirtyAfter) : null,
  );

  const anchorBefore = before.scroll_anchor_id ?? before.scrollAnchorId;
  const anchorAfter = afterRaw.scroll_anchor_id ?? afterRaw.scrollAnchorId;
  const scrollDelta = Number(afterRaw.scroll_offset_delta ?? 0);
  const scrollContextPreserved = boolOrNull(
    afterRaw.scroll_context_preserved,
    anchorBefore !== undefined && anchorAfter !== undefined ? (anchorBefore === anchorAfter && Math.abs(scrollDelta) <= 2) : null,
  );

  const triggerRestored = boolOrNull(
    afterRaw.trigger_restored,
    beforeFocusRole && afterFocusRole ? afterFocusRole === beforeFocusRole : null,
  );

  let noticePrecedesDetail = boolOrNull(afterRaw.notice_precedes_detail, null);
  if (noticeRole?.presence === 'visible' && detailRole?.presence === 'visible') {
    const nRank = noticeRole.geometry?.reading_order_rank;
    const dRank = detailRole.geometry?.reading_order_rank;
    if (isFinNum(nRank) && isFinNum(dRank)) {
      noticePrecedesDetail = nRank < dRank;
    } else if (isFinNum(noticeRole.geometry?.y) && isFinNum(detailRole.geometry?.y)) {
      noticePrecedesDetail = noticeRole.geometry.y < detailRole.geometry.y
        || (noticeRole.geometry.y === detailRole.geometry.y && Number(noticeRole.geometry?.x ?? 0) <= Number(detailRole.geometry?.x ?? 0));
    }
  }

  const detailMatchesSelection = boolOrNull(
    afterRaw.detail_matches_selection,
    detailRole?.presence === 'visible' && detailRole.bound_entity_id !== undefined && selectedAfter !== undefined
      ? detailRole.bound_entity_id === selectedAfter
      : null,
  );

  const contrastSummary = evaluateWcag22Contrast(elements);
  const rawClip = s.presentation?.clipping;
  let unintentionalClipped = finOrNull(rawClip?.unintentional_clipped_count);
  let scrollableContainers = finOrNull(rawClip?.scrollable_containers_count);
  const rawFocusVis = s.presentation?.focus_visibility;
  let fullyObscured = finOrNull(rawFocusVis?.fully_obscured_count);
  let partiallyObscured = finOrNull(rawFocusVis?.partially_obscured_count);

  if (elements.length > 0 && unintentionalClipped === null && scrollableContainers === null) {
    unintentionalClipped = 0;
    scrollableContainers = 0;
    for (const el of elements) {
      const cRes = evaluateElementClipping(el);
      if (cRes.clipped) unintentionalClipped += 1;
      if (cRes.scrollable) scrollableContainers += 1;
    }
  }
  if (elements.length > 0 && fullyObscured === null && partiallyObscured === null) {
    let fFull = 0;
    let fPart = 0;
    let mFocus = 0;
    for (const el of elements) {
      const fRes = evaluateFocusObscuration(el, null);
      if (fRes.status === 'measured') {
        mFocus += 1;
        if (fRes.fullyObscured) fFull += 1;
        if (fRes.partiallyObscured) fPart += 1;
      }
    }
    if (mFocus > 0) {
      fullyObscured = fFull;
      partiallyObscured = fPart;
    }
  }

  const contrastUnverifiable = Number(s.presentation?.contrast_wcag22?.unverifiable_count ?? contrastSummary.unverifiableCount);
  if (contrastUnverifiable > 0) {
    unverifiableChecks += contrastUnverifiable;
    unverifiableReasons.push(`contrast_unverifiable:${contrastUnverifiable}`);
  }
  if (surfaceFound && measuredChecks === 0 && contrastSummary.measuredCount === 0) {
    unverifiableChecks += 1;
    unverifiableReasons.push('ui.unmeasured_surface');
  }

  const hasVp = isFinNum(s.documentWidth) && isFinNum(s.viewportWidth) && Number(s.viewportWidth) > 0;
  const rawContrast = s.presentation?.contrast_wcag22;
  const presentation = {
    horizontal_overflow_px: finOrNull(s.presentation?.horizontal_overflow_px) ?? (hasVp ? Math.max(0, Number(s.documentWidth) - Number(s.viewportWidth)) : null),
    clipping: { unintentional_clipped_count: unintentionalClipped, scrollable_containers_count: scrollableContainers },
    focus_visibility: { fully_obscured_count: fullyObscured, partially_obscured_count: partiallyObscured },
    contrast_wcag22: {
      text_normal_min: finOrNull(rawContrast?.text_normal_min) ?? contrastSummary.textNormalMin,
      text_large_min: finOrNull(rawContrast?.text_large_min) ?? contrastSummary.textLargeMin,
      ui_component_min: finOrNull(rawContrast?.ui_component_min) ?? contrastSummary.uiComponentMin,
      violations_count: finOrNull(rawContrast?.violations_count) ?? (contrastSummary.measuredCount > 0 ? contrastSummary.violationsCount : null),
      unverifiable_count: contrastUnverifiable,
    },
  };

  const recovery = evaluateTaskRecovery(s, before, afterRaw);
  const capabilities = explicitCaps ?? deriveObservedCapabilities(s, rawRoles, elements, before, transRaw, afterRaw, contrastSummary);

  return {
    schema: 'drift.ui-observation/1', surface_found: surfaceFound, surfaceFound,
    adapter: { name: adapterName, capabilities },
    ...(s.environment_ref ? { environment_ref: s.environment_ref } : {}),
    roles,
    sequence: {
      before: { ...before, ...(beforeFocusRole ? { input_focus_role: beforeFocusRole } : {}), ...(selectedBefore !== undefined ? { selected_entity_id: selectedBefore } : {}), ...(anchorBefore !== undefined ? { scroll_anchor_id: anchorBefore } : {}), ...(dirtyBefore ? { dirty_inputs: dirtyBefore } : {}) },
      action,
      transition: { configured_duration_ms: configuredMs, observed_duration_ms: observedMs, unexpected_focus_steals: unexpectedFocusSteals },
      after: { ...afterRaw, input_focus_role: afterFocusRole, selection_preserved: selectionPreserved, dirty_inputs_preserved: dirtyInputsPreserved, scroll_context_preserved: scrollContextPreserved, trigger_restored: triggerRestored, notice_precedes_detail: noticePrecedesDetail, detail_matches_selection: detailMatchesSelection, ...recovery },
    },
    presentation,
    evidence: { measured_checks: measuredChecks, not_applicable_checks: notApplicableChecks, unverifiable_checks: unverifiableChecks, unverifiable_reasons: unverifiableReasons },
    ...(elements.length ? { elements } : {}),
  };
}

export function bindUiEnvironment(ctx, manifestPath, rawEnvOverride) {
  if (isObj(rawEnvOverride)) {
    for (const k of Object.keys(rawEnvOverride)) if (!ALLOWED_DRIFT_ENV_KEYS.has(k)) throw new Error(`unsupported DRIFT_ENV key "${k}"; bind UI rendering environment via config manifest and recordInput`);
  }
  if (!manifestPath || typeof manifestPath !== 'string') throw new Error('bindUiEnvironment requires a non-empty manifest path');
  const content = ctx && typeof ctx.readFixture === 'function' ? ctx.readFixture(manifestPath) : fs.readFileSync(manifestPath, 'utf8');
  const parsed = JSON.parse(content);
  if (!isObj(parsed) || (!parsed.platform && !parsed.browser)) throw new Error(`invalid UI environment manifest "${manifestPath}": missing platform/browser`);
  const digest = `sha256:${crypto.createHash('sha256').update(Buffer.from(content.replace(/\r\n/g, '\n'), 'utf8')).digest('hex')}`;
  const ref = `fixture:${manifestPath.replace(/\\/g, '/')}@${digest}`;
  if (ctx && typeof ctx.recordInput === 'function') ctx.recordInput(manifestPath);
  const existingEnv = (process.env.DRIFT_ENV || '').trim() ? JSON.parse(process.env.DRIFT_ENV) : {};
  process.env.DRIFT_PROOF_KEY = '1';
  process.env.DRIFT_ENV = JSON.stringify({ ...existingEnv, config: ref });
  return { config: ref, environment_ref: ref, manifest: parsed };
}

export const adaptPlaywrightSurface = (raw) => observeUiSequence({ ...raw, adapter: optAdapter(raw, 'playwright-web') });
export const adaptComposeSemantics = (raw) => observeUiSequence(buildComposePayload(raw));
export const adaptUiaSnapshot = (raw) => observeUiSequence(buildUiaPayload(raw));

export function evalPlanCaseImpl(contractId, caseId, planCase, payload, seen, escapePointer, readPointer, checkRelationalLeaf, throwAssertionError) {
  if (!isObj(planCase) || !Array.isArray(planCase.clauses)) return false;
  const pfx = `${contractId}.${caseId}`;
  for (const cl of planCase.clauses) {
    if (!isObj(cl) || !isObj(cl.constraint)) continue;
    const pred = String(cl.pred || ''), ptr = String(cl.pointer || `/${escapePointer(pred)}`), conv = Number(cl.conv ?? 1), rawC = cl.constraint;
    const peerPtrs = isObj(cl.peer_pointers) ? { ...cl.peer_pointers } : {};
    for (const [pk, pv] of Object.entries(peerPtrs)) if (pk.startsWith('then.')) peerPtrs[pk.slice(5)] = pv;
    const whenEnv = { ...(isObj(planCase.when) ? planCase.when : {}), ...(isObj(cl.when_peers) ? cl.when_peers : {}) };
    for (const [wk, wv] of Object.entries({ ...whenEnv })) if (wk.startsWith('when.')) whenEnv[wk.slice(5)] = wv;
    const fakeContract = conv !== 1 ? { units: { '__u->target': conv }, schema: { then: { [pred]: { unit: 'target' } } } } : {};
    const exp = conv !== 1 ? { ...rawC, convert_from: '__u' } : rawC;
    let act;
    if ((isObj(rawC.keys) || 'allowed_keys' in rawC || 'forbid_keys' in rawC) && ptr === `/${escapePointer(pred)}`) {
      act = isObj(payload) && isObj(payload[pred]) ? payload[pred] : payload;
    } else {
      const rd = readPointer(payload, ptr);
      if (!rd.found) throwAssertionError(`${pfx}: missing projected path "${ptr}" for then.${pred}`);
      act = rd.value;
    }
    checkRelationalLeaf(contractId, caseId, pred, exp, act, payload, peerPtrs, null, whenEnv, fakeContract);
    if (seen && String(cl.clause || '').startsWith('then.')) seen.add(pred);
  }
  return true;
}

export function checkRequiredAdapterCapability(contractId, caseId, key, view, proj) {
  const v = isObj(view) ? view : {};
  if (v.collector?.settle_timed_out === true || (Array.isArray(v.evidence?.unverifiable_reasons) && v.evidence.unverifiable_reasons.includes('ui.settle_timeout'))) {
    const err = new Error(`${contractId}.${caseId}: ui.settle_timeout`);
    err.name = 'AssertionError';
    err.code = 'ERR_ASSERTION';
    throw err;
  }
  const caps = v.adapter?.capabilities;
  if (!Array.isArray(caps)) return;
  const ptr = isObj(proj) && typeof proj[key] === 'string' ? proj[key] : '';
  const leaf = ptr.split('/').filter(Boolean).pop() || '';
  const reqCap = PREDICATE_CAPABILITY[key] || PREDICATE_CAPABILITY[leaf];
  if (reqCap && !caps.includes(reqCap)) {
    if (isObj(v.evidence) && typeof v.evidence.unverifiable_checks === 'number') {
      v.evidence.unverifiable_checks += 1;
    }
    const err = new Error(`${contractId}.${caseId}: ui.capability_unverifiable:${reqCap} for then.${key}`);
    err.name = 'AssertionError';
    throw err;
  }
}
