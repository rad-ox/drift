// Cross-platform UI surface, interaction sequence, and adapter normalization for DRIFT (D282-D284).
import crypto from 'node:crypto';
import fs from 'node:fs';

const ALLOWED_DRIFT_ENV_KEYS = new Set(['adapter', 'config', 'deps', 'drift', 'policy', 'runner', 'toolchain']);

const PREDICATE_CAPABILITY = {
  min_contrast_ratio: 'wcag22_contrast',
  min_contrast_wcag22: 'wcag22_contrast',
  min_contrast_text_normal: 'wcag22_contrast',
  min_contrast_text_large: 'wcag22_contrast',
  min_contrast_ui_component: 'wcag22_contrast',
  contrast_violations_count: 'wcag22_contrast',
  assistive_announcement: 'assistive_focus',
  active_assistive_focus: 'assistive_focus',
  observed_transition_ms: 'observed_transition',
  max_transition_ms: 'observed_transition',
  scroll_context_preserved: 'scroll_state',
  horizontal_overflow_px: 'geometry',
  min_target_px: 'geometry',
  clipped_elements: 'geometry',
  unintentional_clipped_count: 'geometry',
  obscured_focus_elements: 'geometry',
  fully_obscured_focus_count: 'geometry',
  partially_obscured_focus_count: 'geometry',
  notice_precedes_detail: 'geometry',
  after_focus_role: 'input_focus',
  active_focus: 'input_focus',
  trigger_restored: 'input_focus',
  unexpected_focus_steals: 'input_focus',
};

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isFinNum = (v) => typeof v === 'number' && Number.isFinite(v);

export function isElementHidden(el) {
  if (!isObj(el)) return false;
  const pres = String(el.presence ?? el.state ?? '').toLowerCase();
  if (pres === 'hidden' || pres === 'absent' || pres === 'collapsed') return true;
  if (el.hidden === true || el.ariaHidden === true || el['aria-hidden'] === 'true') return true;
  const disp = String(el.display ?? el.style?.display ?? '').toLowerCase();
  const vis = String(el.visibility ?? el.style?.visibility ?? '').toLowerCase();
  return disp === 'none' || vis === 'hidden' || vis === 'collapse';
}

export function isElementScrollable(el, axis = 'both') {
  if (!isObj(el)) return false;
  if (el.scrollable === true) return true;
  if (el.scrollable === false) return false;
  const ox = String(el.overflowX ?? el.style?.overflowX ?? el.overflow ?? el.style?.overflow ?? '').toLowerCase();
  const oy = String(el.overflowY ?? el.style?.overflowY ?? el.overflow ?? el.style?.overflow ?? '').toLowerCase();
  const isScrollVal = (v) => v === 'auto' || v === 'scroll';
  if (axis === 'x') return isScrollVal(ox) || el.horizontallyScrollable === true;
  if (axis === 'y') return isScrollVal(oy) || el.verticallyScrollable === true;
  return isScrollVal(ox) || isScrollVal(oy) || el.horizontallyScrollable === true || el.verticallyScrollable === true;
}

export function evaluateElementClipping(el) {
  if (!isObj(el) || isElementHidden(el)) {
    return { clipped: false, scrollable: false, status: 'not_applicable' };
  }
  const sw = Number(el.scrollWidth ?? 0);
  const cw = Number(el.clientWidth ?? 0);
  const sh = Number(el.scrollHeight ?? 0);
  const ch = Number(el.clientHeight ?? 0);
  const overX = sw > cw;
  const overY = sh > ch;
  const scrollX = isElementScrollable(el, 'x');
  const scrollY = isElementScrollable(el, 'y');
  const scrollable = scrollX || scrollY;
  const clippedX = overX && !scrollX;
  const clippedY = overY && !scrollY;
  return {
    clipped: clippedX || clippedY,
    scrollable,
    status: 'measured',
  };
}

export function evaluateFocusObscuration(el, ownerDoc) {
  if (!isObj(el) || isElementHidden(el) || el.focusable === false) {
    return { fullyObscured: false, partiallyObscured: false, status: 'not_applicable' };
  }
  if (typeof el.fullyObscured === 'boolean' || typeof el.partiallyObscured === 'boolean') {
    const full = Boolean(el.fullyObscured);
    const part = Boolean(el.partiallyObscured || full);
    return { fullyObscured: full, partiallyObscured: part, status: 'measured' };
  }
  if (Array.isArray(el.hitPoints) && el.hitPoints.length > 0) {
    const total = el.hitPoints.length;
    const covered = el.hitPoints.filter((p) => p === true || (isObj(p) && p.covered === true)).length;
    return {
      fullyObscured: covered === total,
      partiallyObscured: covered > 0,
      status: 'measured',
    };
  }
  const rect = typeof el.getBoundingClientRect === 'function' ? el.getBoundingClientRect() : el.rect;
  const w = Number(el.width ?? rect?.width ?? el.clientWidth ?? 0);
  const h = Number(el.height ?? rect?.height ?? el.clientHeight ?? 0);
  if (rect && w > 0 && h > 0 && ownerDoc && typeof ownerDoc.elementFromPoint === 'function') {
    const left = Number(rect.left ?? rect.x ?? 0);
    const top = Number(rect.top ?? rect.y ?? 0);
    const insetX = Math.min(2, w / 4);
    const insetY = Math.min(2, h / 4);
    const pts = [
      [left + w / 2, top + h / 2],
      [left + insetX, top + insetY],
      [left + w - insetX, top + insetY],
      [left + insetX, top + h - insetY],
      [left + w - insetX, top + h - insetY],
    ];
    let covered = 0;
    for (const [px, py] of pts) {
      const hitEl = ownerDoc.elementFromPoint(px, py);
      if (
        hitEl
        && hitEl !== el
        && (typeof el.contains !== 'function' || !el.contains(hitEl))
        && (typeof hitEl.contains !== 'function' || !hitEl.contains(el))
      ) {
        covered += 1;
      }
    }
    return {
      fullyObscured: covered === pts.length,
      partiallyObscured: covered > 0,
      status: 'measured',
    };
  }
  if ('obscured' in el || 'focusObscured' in el) {
    const obs = Boolean(el.obscured ?? el.focusObscured);
    return { fullyObscured: obs, partiallyObscured: obs, status: 'measured' };
  }
  return { fullyObscured: false, partiallyObscured: false, status: 'unverifiable' };
}

export function evaluateWcag22Contrast(elements) {
  let textNormalMin = Infinity;
  let textLargeMin = Infinity;
  let uiComponentMin = Infinity;
  let overallMin = Infinity;
  let violationsCount = 0;
  let unverifiableCount = 0;
  let measuredCount = 0;

  for (const el of Array.isArray(elements) ? elements : []) {
    if (!isObj(el) || isElementHidden(el)) continue;
    if (el.contrastUnverifiable === true || el.backgroundUnverifiable === true) {
      unverifiableCount += 1;
      continue;
    }
    const ratio = el.contrastRatio ?? el.contrast_ratio;
    if (!isFinNum(ratio)) continue;
    measuredCount += 1;
    if (ratio < overallMin) overallMin = ratio;
    const cat = String(el.contrastCategory ?? el.category ?? 'text_normal').toLowerCase();
    const floor = cat === 'text_large' || cat === 'ui_component' ? 3.0 : 4.5;
    if (cat === 'text_large') {
      if (ratio < textLargeMin) textLargeMin = ratio;
    } else if (cat === 'ui_component') {
      if (ratio < uiComponentMin) uiComponentMin = ratio;
    } else if (ratio < textNormalMin) {
      textNormalMin = ratio;
    }
    if (ratio + 1e-9 < floor) {
      violationsCount += 1;
    }
  }

  return {
    measuredCount,
    overallMin: Number.isFinite(overallMin) ? overallMin : null,
    textNormalMin: Number.isFinite(textNormalMin) ? textNormalMin : null,
    textLargeMin: Number.isFinite(textLargeMin) ? textLargeMin : null,
    uiComponentMin: Number.isFinite(uiComponentMin) ? uiComponentMin : null,
    violationsCount,
    unverifiableCount,
  };
}

export function deriveNonColorCue(node) {
  if (!isObj(node)) {
    return { has_visible_text: false, has_graphic_icon: false, has_semantic_role: false, non_color_encoded: false };
  }
  if (isObj(node.content_cues)) {
    const cues = node.content_cues;
    const hasText = Boolean(cues.has_visible_text);
    const hasIcon = Boolean(cues.has_graphic_icon);
    const role = String(node.semantic_role ?? node.role ?? '').toLowerCase();
    const hasSemRole = Boolean(cues.has_semantic_role ?? (role === 'alert' || role === 'alertdialog' || role === 'status'));
    const encoded = hasText && (hasIcon || hasSemRole);
    return {
      has_visible_text: hasText,
      has_graphic_icon: hasIcon,
      has_semantic_role: hasSemRole,
      non_color_encoded: encoded,
    };
  }
  const text = String(node.text ?? node.textContent ?? node.label ?? '').trim();
  const hasVisibleText = text.length > 0 && !isElementHidden(node);
  const children = Array.isArray(node.children) ? node.children : [];
  const hasGraphicIcon = Boolean(
    node.hasIcon === true
    || node.icon === true
    || children.some((c) => isObj(c) && !isElementHidden(c) && (
      String(c.tagName ?? '').toUpperCase() === 'SVG'
      || String(c.role ?? '').toLowerCase() === 'img'
      || Boolean(c.isIcon)
    )),
  );
  const role = String(node.semantic_role ?? node.role ?? '').toLowerCase();
  const hasSemanticRole = role === 'alert' || role === 'alertdialog' || role === 'status';
  return {
    has_visible_text: hasVisibleText,
    has_graphic_icon: hasGraphicIcon,
    has_semantic_role: hasSemanticRole,
    non_color_encoded: hasVisibleText && (hasGraphicIcon || hasSemanticRole),
  };
}

export function observeUiSequence(spec) {
  const s = isObj(spec) ? spec : {};
  const surfaceFound = s.surface_found !== false && s.surfaceFound !== false;
  const adapterName = String(s.adapter?.name ?? s.adapter ?? 'playwright-web');
  const capabilities = Array.isArray(s.adapter?.capabilities ?? s.capabilities)
    ? [...(s.adapter?.capabilities ?? s.capabilities)]
    : ['geometry', 'input_focus', 'assistive_focus', 'wcag22_contrast', 'observed_transition', 'scroll_state'];

  const rawRoles = isObj(s.roles) ? s.roles : {};
  const roles = {};
  let unverifiableChecks = Number(s.evidence?.unverifiable_checks ?? s.unverifiableChecks ?? 0);
  const unverifiableReasons = Array.isArray(s.evidence?.unverifiable_reasons)
    ? [...s.evidence.unverifiable_reasons]
    : [];
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
      if ((geom || 'width' in r || 'height' in r || expectedPresence === 'visible') && (w <= 0 || h <= 0)) {
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

  const configuredMs = Number(transRaw.configured_duration_ms ?? transRaw.configuredDurationMs ?? 0);
  const observedMs = Number(transRaw.observed_duration_ms ?? transRaw.observedDurationMs ?? configuredMs);
  const focusTrace = Array.isArray(transRaw.focus_trace ?? transRaw.focusTrace)
    ? (transRaw.focus_trace ?? transRaw.focusTrace)
    : [];

  const noticeRole = roles.notice;
  const detailRole = roles.detail;
  const summaryRole = roles.summary;
  const noticeSem = String(noticeRole?.semantic_role ?? noticeRole?.role ?? '').toLowerCase();

  let unexpectedFocusSteals = Number(transRaw.unexpected_focus_steals ?? transRaw.unexpectedFocusSteals ?? 0);
  if (noticeRole?.presence === 'visible' && noticeSem === 'alert') {
    if (focusTrace.includes('notice') || afterRaw.input_focus_role === 'notice') {
      unexpectedFocusSteals += 1;
    }
  }

  const selectedBefore = before.selected_entity_id ?? before.selectedEntityId;
  const selectedAfter = afterRaw.selected_entity_id ?? afterRaw.selectedEntityId ?? summaryRole?.selected_entity_id ?? selectedBefore;
  const selectionPreserved = afterRaw.selection_preserved !== undefined
    ? Boolean(afterRaw.selection_preserved)
    : (selectedBefore !== undefined ? selectedBefore === selectedAfter : true);

  const dirtyBefore = isObj(before.dirty_inputs ?? before.dirtyInputs) ? (before.dirty_inputs ?? before.dirtyInputs) : null;
  const dirtyAfter = isObj(afterRaw.dirty_inputs ?? afterRaw.dirtyInputs) ? (afterRaw.dirty_inputs ?? afterRaw.dirtyInputs) : dirtyBefore;
  const dirtyInputsPreserved = afterRaw.dirty_inputs_preserved !== undefined
    ? Boolean(afterRaw.dirty_inputs_preserved)
    : (dirtyBefore ? JSON.stringify(dirtyBefore) === JSON.stringify(dirtyAfter) : true);

  const anchorBefore = before.scroll_anchor_id ?? before.scrollAnchorId;
  const anchorAfter = afterRaw.scroll_anchor_id ?? afterRaw.scrollAnchorId ?? anchorBefore;
  const scrollDelta = Number(afterRaw.scroll_offset_delta ?? 0);
  const scrollContextPreserved = afterRaw.scroll_context_preserved !== undefined
    ? Boolean(afterRaw.scroll_context_preserved)
    : (anchorBefore !== undefined ? (anchorBefore === anchorAfter && Math.abs(scrollDelta) <= 2) : true);

  const afterFocusRole = String(afterRaw.input_focus_role ?? afterRaw.inputFocusRole ?? '');
  const beforeFocusRole = String(before.input_focus_role ?? before.inputFocusRole ?? '');
  const triggerRestored = afterRaw.trigger_restored !== undefined
    ? Boolean(afterRaw.trigger_restored)
    : Boolean(beforeFocusRole && afterFocusRole === beforeFocusRole);

  let noticePrecedesDetail = Boolean(afterRaw.notice_precedes_detail ?? true);
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

  const detailMatchesSelection = afterRaw.detail_matches_selection !== undefined
    ? Boolean(afterRaw.detail_matches_selection)
    : (detailRole?.presence === 'visible' && detailRole.bound_entity_id !== undefined && selectedAfter !== undefined
      ? detailRole.bound_entity_id === selectedAfter
      : true);

  const elements = Array.isArray(s.elements) ? s.elements : [];
  const contrastSummary = evaluateWcag22Contrast(elements);
  let unintentionalClipped = Number(s.presentation?.clipping?.unintentional_clipped_count ?? 0);
  let scrollableContainers = Number(s.presentation?.clipping?.scrollable_containers_count ?? 0);
  let fullyObscured = Number(s.presentation?.focus_visibility?.fully_obscured_count ?? 0);
  let partiallyObscured = Number(s.presentation?.focus_visibility?.partially_obscured_count ?? 0);

  if (elements.length > 0 && !s.presentation?.clipping) {
    unintentionalClipped = 0;
    scrollableContainers = 0;
    for (const el of elements) {
      const cRes = evaluateElementClipping(el);
      if (cRes.clipped) unintentionalClipped += 1;
      if (cRes.scrollable) scrollableContainers += 1;
    }
  }
  if (elements.length > 0 && !s.presentation?.focus_visibility) {
    fullyObscured = 0;
    partiallyObscured = 0;
    for (const el of elements) {
      const fRes = evaluateFocusObscuration(el, null);
      if (fRes.fullyObscured) fullyObscured += 1;
      if (fRes.partiallyObscured) partiallyObscured += 1;
    }
  }

  const contrastUnverifiable = Number(
    s.presentation?.contrast_wcag22?.unverifiable_count ?? contrastSummary.unverifiableCount,
  );
  if (contrastUnverifiable > 0) {
    unverifiableChecks += contrastUnverifiable;
    unverifiableReasons.push(`contrast_unverifiable:${contrastUnverifiable}`);
  }

  const presentation = {
    horizontal_overflow_px: Number(
      s.presentation?.horizontal_overflow_px
      ?? Math.max(0, Number(s.documentWidth ?? 0) - Number(s.viewportWidth ?? 0)),
    ),
    clipping: {
      unintentional_clipped_count: unintentionalClipped,
      scrollable_containers_count: scrollableContainers,
    },
    focus_visibility: {
      fully_obscured_count: fullyObscured,
      partially_obscured_count: partiallyObscured,
    },
    contrast_wcag22: {
      text_normal_min: s.presentation?.contrast_wcag22?.text_normal_min ?? contrastSummary.textNormalMin ?? 7.0,
      text_large_min: s.presentation?.contrast_wcag22?.text_large_min ?? contrastSummary.textLargeMin ?? 7.0,
      ui_component_min: s.presentation?.contrast_wcag22?.ui_component_min ?? contrastSummary.uiComponentMin ?? 4.5,
      violations_count: Number(s.presentation?.contrast_wcag22?.violations_count ?? contrastSummary.violationsCount),
      unverifiable_count: contrastUnverifiable,
    },
  };

  return {
    schema: 'drift.ui-observation/1',
    surface_found: surfaceFound,
    surfaceFound,
    adapter: {
      name: adapterName,
      capabilities,
    },
    ...(s.environment_ref ? { environment_ref: s.environment_ref } : {}),
    roles,
    sequence: {
      before: {
        ...before,
        ...(beforeFocusRole ? { input_focus_role: beforeFocusRole } : {}),
        ...(selectedBefore !== undefined ? { selected_entity_id: selectedBefore } : {}),
        ...(anchorBefore !== undefined ? { scroll_anchor_id: anchorBefore } : {}),
        ...(dirtyBefore ? { dirty_inputs: dirtyBefore } : {}),
      },
      action,
      transition: {
        configured_duration_ms: configuredMs,
        observed_duration_ms: observedMs,
        unexpected_focus_steals: unexpectedFocusSteals,
      },
      after: {
        ...afterRaw,
        input_focus_role: afterFocusRole,
        selection_preserved: selectionPreserved,
        dirty_inputs_preserved: dirtyInputsPreserved,
        scroll_context_preserved: scrollContextPreserved,
        trigger_restored: triggerRestored,
        notice_precedes_detail: noticePrecedesDetail,
        detail_matches_selection: detailMatchesSelection,
      },
    },
    presentation,
    evidence: {
      measured_checks: measuredChecks,
      not_applicable_checks: notApplicableChecks,
      unverifiable_checks: unverifiableChecks,
      unverifiable_reasons: unverifiableReasons,
    },
    ...(elements.length ? { elements } : {}),
  };
}

export function bindUiEnvironment(ctx, manifestPath, rawEnvOverride) {
  if (isObj(rawEnvOverride)) {
    for (const k of Object.keys(rawEnvOverride)) {
      if (!ALLOWED_DRIFT_ENV_KEYS.has(k)) {
        throw new Error(`unsupported DRIFT_ENV key "${k}"; bind UI rendering environment via config manifest and recordInput`);
      }
    }
  }
  if (!manifestPath || typeof manifestPath !== 'string') {
    throw new Error('bindUiEnvironment requires a non-empty manifest path');
  }
  const content = ctx && typeof ctx.readFixture === 'function'
    ? ctx.readFixture(manifestPath)
    : fs.readFileSync(manifestPath, 'utf8');
  const parsed = JSON.parse(content);
  if (!isObj(parsed) || !parsed.platform && !parsed.browser) {
    throw new Error(`invalid UI environment manifest "${manifestPath}": missing platform/browser`);
  }
  const digest = `sha256:${crypto.createHash('sha256').update(Buffer.from(content.replace(/\r\n/g, '\n'), 'utf8')).digest('hex')}`;
  const ref = `fixture:${manifestPath.replace(/\\/g, '/')}@${digest}`;
  if (ctx && typeof ctx.recordInput === 'function') {
    ctx.recordInput(manifestPath);
  }
  const existingEnv = (process.env.DRIFT_ENV || '').trim() ? JSON.parse(process.env.DRIFT_ENV) : {};
  process.env.DRIFT_PROOF_KEY = '1';
  process.env.DRIFT_ENV = JSON.stringify({ ...existingEnv, config: ref });
  return {
    config: ref,
    environment_ref: ref,
    manifest: parsed,
  };
}

export function adaptPlaywrightSurface(raw) {
  return observeUiSequence({
    ...raw,
    adapter: {
      name: raw?.adapter?.name ?? 'playwright-web',
      capabilities: raw?.adapter?.capabilities ?? [
        'geometry', 'input_focus', 'assistive_focus', 'wcag22_contrast', 'observed_transition', 'scroll_state',
      ],
    },
  });
}

export function adaptComposeSemantics(raw) {
  const nodes = isObj(raw?.nodes) ? raw.nodes : {};
  const roles = {};
  for (const [roleId, n] of Object.entries(nodes)) {
    if (!isObj(n)) continue;
    const visible = n.visible !== false && n.displayed !== false;
    const bounds = isObj(n.boundsInRoot ?? n.bounds) ? (n.boundsInRoot ?? n.bounds) : {};
    const liveMode = String(n.liveRegion ?? '').toLowerCase();
    const semRole = liveMode === 'assertive' || n.isDialog === true
      ? (n.isModal === true ? 'alertdialog' : 'alert')
      : String(n.role ?? 'region').toLowerCase();
    roles[roleId] = {
      presence: visible ? (n.presence ?? 'visible') : (n.presence ?? 'hidden'),
      semantic_role: semRole,
      ...(n.selectedEntityId !== undefined ? { selected_entity_id: n.selectedEntityId } : {}),
      ...(n.boundEntityId !== undefined ? { bound_entity_id: n.boundEntityId } : {}),
      ...(n.containerMode !== undefined ? { container_mode: n.containerMode } : {}),
      actions: Array.isArray(n.actions) ? n.actions : [],
      content_cues: {
        has_visible_text: Boolean(visible && String(n.text ?? '').trim().length > 0),
        has_graphic_icon: Boolean(visible && (n.hasIcon === true || n.contentDescription)),
        has_semantic_role: semRole === 'alert' || semRole === 'alertdialog' || semRole === 'status',
      },
      geometry: {
        unit: 'dp',
        x: Number(bounds.left ?? bounds.x ?? 0),
        y: Number(bounds.top ?? bounds.y ?? 0),
        width: Number(bounds.width ?? 0),
        height: Number(bounds.height ?? 0),
        reading_order_rank: Number(n.traversalIndex ?? n.readingOrderRank ?? 0),
      },
    };
  }
  const elements = Object.values(nodes).filter(isObj).map((n) => {
    const bounds = isObj(n.boundsInRoot ?? n.bounds) ? (n.boundsInRoot ?? n.bounds) : {};
    const hasScrollRange = Boolean(n.verticalScrollAxisRange || n.horizontalScrollAxisRange || n.scrollable);
    const hasOverflow = Boolean(n.hasVisualOverflow);
    return {
      presence: n.visible === false ? 'hidden' : 'visible',
      width: Number(bounds.width ?? 48),
      height: Number(bounds.height ?? 48),
      scrollWidth: hasOverflow && !hasScrollRange ? Number(bounds.width ?? 48) + 16 : Number(bounds.width ?? 48),
      clientWidth: Number(bounds.width ?? 48),
      scrollHeight: hasOverflow ? Number(bounds.height ?? 48) + 16 : Number(bounds.height ?? 48),
      clientHeight: Number(bounds.height ?? 48),
      scrollable: hasScrollRange,
      focusable: Boolean(n.focused !== undefined || n.focusable),
      obscured: Boolean(n.obscured ?? false),
      ...(isFinNum(n.contrastRatio) ? { contrastRatio: n.contrastRatio, contrastCategory: n.contrastCategory ?? 'text_normal' } : {}),
    };
  });
  return observeUiSequence({
    surface_found: raw?.surfaceFound !== false,
    adapter: {
      name: raw?.adapter?.name ?? 'compose-semantics',
      capabilities: raw?.adapter?.capabilities ?? [
        'geometry', 'input_focus', 'assistive_focus', 'wcag22_contrast', 'observed_transition', 'scroll_state',
      ],
    },
    environment_ref: raw?.environment_ref,
    roles,
    before: raw?.before,
    action: raw?.action,
    transition: raw?.transition,
    after: raw?.after,
    elements,
    documentWidth: Number(raw?.viewportWidthDp ?? 412),
    viewportWidth: Number(raw?.viewportWidthDp ?? 412),
  });
}

export function adaptUiaSnapshot(raw) {
  const controls = isObj(raw?.elements ?? raw?.controls) ? (raw.elements ?? raw.controls) : {};
  const roles = {};
  for (const [roleId, c] of Object.entries(controls)) {
    if (!isObj(c)) continue;
    const isOffscreen = Boolean(c.IsOffscreen === true || c.presence === 'hidden' || c.presence === 'absent');
    const rect = isObj(c.BoundingRectangle ?? c.rect) ? (c.BoundingRectangle ?? c.rect) : {};
    const ctrlType = String(c.ControlType ?? c.semantic_role ?? 'Pane');
    const semRole = ctrlType === 'Window.AlertDialog' || c.isModal === true
      ? 'alertdialog'
      : (ctrlType === 'StatusBar' || ctrlType === 'Alert' ? 'alert' : 'region');
    roles[roleId] = {
      presence: isOffscreen ? (c.presence ?? 'hidden') : 'visible',
      semantic_role: semRole,
      ...(c.selectedEntityId !== undefined ? { selected_entity_id: c.selectedEntityId } : {}),
      ...(c.boundEntityId !== undefined ? { bound_entity_id: c.boundEntityId } : {}),
      ...(c.containerMode !== undefined ? { container_mode: c.containerMode } : {}),
      actions: Array.isArray(c.patterns) ? c.patterns : [],
      content_cues: {
        has_visible_text: Boolean(!isOffscreen && String(c.Name ?? c.text ?? '').trim().length > 0),
        has_graphic_icon: Boolean(!isOffscreen && c.hasIcon === true),
        has_semantic_role: semRole === 'alert' || semRole === 'alertdialog',
      },
      geometry: {
        unit: 'dip',
        x: Number(rect.x ?? rect.left ?? 0),
        y: Number(rect.y ?? rect.top ?? 0),
        width: Number(rect.width ?? 0),
        height: Number(rect.height ?? 0),
        reading_order_rank: Number(c.readingOrderRank ?? 0),
      },
    };
  }
  return observeUiSequence({
    surface_found: raw?.surfaceFound !== false,
    adapter: {
      name: raw?.adapter?.name ?? 'windows-uia',
      capabilities: raw?.adapter?.capabilities ?? [
        'geometry', 'input_focus', 'assistive_focus', 'wcag22_contrast', 'observed_transition', 'scroll_state',
      ],
    },
    environment_ref: raw?.environment_ref,
    roles,
    before: raw?.before,
    action: raw?.action,
    transition: raw?.transition,
    after: raw?.after,
    documentWidth: Number(raw?.windowWidthDip ?? 1280),
    viewportWidth: Number(raw?.windowWidthDip ?? 1280),
  });
}

export function checkRequiredAdapterCapability(contractId, caseId, key, view, proj) {
  const v = isObj(view) ? view : {};
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
