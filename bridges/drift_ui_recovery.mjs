// Task-completion recovery invariants (async-action-feedback@1, wizard-form@1) and curated UI scenario matrices.

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isFinNum = (v) => typeof v === 'number' && Number.isFinite(v);
const boolOrNull = (v, fb) => (typeof v === 'boolean' ? v : fb);

export const DEFAULT_CURATED_UI_SCENARIOS = Object.freeze([
  'keyboard_only',
  'narrow_viewport',
  'long_localized_text',
  'reduced_motion',
  'slow_or_failed_async',
]);

function isElHiddenBasic(el) {
  if (!isObj(el)) return false;
  const pres = String(el.presence ?? el.state ?? '').toLowerCase();
  if (pres === 'hidden' || pres === 'absent' || pres === 'collapsed') return true;
  if (el.hidden === true || el.ariaHidden === true || el['aria-hidden'] === 'true') return true;
  const disp = String(el.display ?? el.style?.display ?? '').toLowerCase();
  const vis = String(el.visibility ?? el.style?.visibility ?? '').toLowerCase();
  return disp === 'none' || vis === 'hidden' || vis === 'collapse';
}

export function deriveObservedCapabilities(s, rawRoles, elements, before, transRaw, afterRaw, contrastSummary) {
  const caps = [];
  const hasRoleGeom = Object.values(isObj(rawRoles) ? rawRoles : {}).some((r) => {
    if (!isObj(r) || isElHiddenBasic(r)) return false;
    const g = isObj(r.geometry) ? r.geometry : r;
    return isFinNum(g?.width) && isFinNum(g?.height) && Number(g.width) > 0 && Number(g.height) > 0;
  });
  const hasElGeom = (Array.isArray(elements) ? elements : []).some(
    (el) => isObj(el) && !isElHiddenBasic(el) && isFinNum(el.width) && isFinNum(el.height) && el.width > 0 && el.height > 0,
  );
  const hasVpGeom = isFinNum(s?.viewportWidth) && Number(s.viewportWidth) > 0 && isFinNum(s?.documentWidth);
  if (hasRoleGeom || hasElGeom || hasVpGeom) caps.push('geometry');

  if (
    before?.input_focus_role
    || before?.inputFocusRole
    || afterRaw?.input_focus_role
    || afterRaw?.inputFocusRole
    || Array.isArray(transRaw?.focus_trace)
    || Array.isArray(transRaw?.focusTrace)
    || isFinNum(transRaw?.unexpected_focus_steals)
    || isFinNum(transRaw?.unexpectedFocusSteals)
    || (Array.isArray(elements) && elements.some((el) => isObj(el) && (el.focused !== undefined || el.focusable === true)))
  ) {
    caps.push('input_focus');
  }

  if (
    s?.assistive_announcement !== undefined
    || s?.active_assistive_focus !== undefined
    || afterRaw?.assistive_announcement !== undefined
    || afterRaw?.active_assistive_focus !== undefined
    || Array.isArray(s?.assistive_trace)
    || Array.isArray(transRaw?.assistive_trace)
  ) {
    caps.push('assistive_focus');
  }

  const rawCw = s?.presentation?.contrast_wcag22;
  if (
    (contrastSummary && contrastSummary.measuredCount > 0)
    || isFinNum(rawCw?.text_normal_min)
    || isFinNum(rawCw?.text_large_min)
    || isFinNum(rawCw?.ui_component_min)
    || isFinNum(rawCw?.violations_count)
    || isFinNum(s?.min_contrast_ratio)
    || isFinNum(s?.min_contrast_wcag22)
  ) {
    caps.push('wcag22_contrast');
  }

  if (
    isFinNum(transRaw?.observed_duration_ms)
    || isFinNum(transRaw?.observedDurationMs)
    || isFinNum(transRaw?.configured_duration_ms)
    || isFinNum(transRaw?.configuredDurationMs)
  ) {
    caps.push('observed_transition');
  }

  if (
    before?.scroll_anchor_id !== undefined
    || before?.scrollAnchorId !== undefined
    || afterRaw?.scroll_anchor_id !== undefined
    || afterRaw?.scrollAnchorId !== undefined
    || isFinNum(afterRaw?.scroll_offset_delta)
    || typeof afterRaw?.scroll_context_preserved === 'boolean'
    || (Array.isArray(elements) && elements.some((el) => isObj(el) && (
      el.scrollable !== undefined
      || el.horizontallyScrollable !== undefined
      || el.verticallyScrollable !== undefined
      || isFinNum(el.scrollWidth)
      || isFinNum(el.scrollHeight)
    )))
  ) {
    caps.push('scroll_state');
  }
  return caps;
}

export function isPointCoveredByVisualOverlays(px, py, el, overlays) {
  if (!Array.isArray(overlays) || overlays.length === 0) return false;
  const elZ = Number(el?.zIndex ?? el?.style?.zIndex ?? 0);
  for (const ov of overlays) {
    if (!isObj(ov) || ov === el || isElHiddenBasic(ov)) continue;
    if (typeof el?.contains === 'function' && el.contains(ov)) continue;
    if (typeof ov.contains === 'function' && ov.contains(el)) continue;
    const opacity = Number(ov.opacity ?? ov.style?.opacity ?? 1);
    if (Number.isFinite(opacity) && opacity <= 0) continue;
    const ovZ = Number(ov.zIndex ?? ov.style?.zIndex ?? 1);
    if (ovZ < elZ && ov.blocksVisualFocus !== true && ov.isOverlay !== true) continue;
    const r = typeof ov.getBoundingClientRect === 'function' ? ov.getBoundingClientRect() : (ov.rect ?? ov);
    const left = Number(r?.left ?? r?.x ?? 0);
    const top = Number(r?.top ?? r?.y ?? 0);
    const width = Number(r?.width ?? 0);
    const height = Number(r?.height ?? 0);
    if (width > 0 && height > 0 && px >= left && px <= left + width && py >= top && py <= top + height) {
      return true;
    }
  }
  return false;
}

const optSurfaceFlag = (raw) => (
  raw?.surfaceFound !== undefined ? { surface_found: Boolean(raw.surfaceFound) }
    : (raw?.surface_found !== undefined ? { surface_found: Boolean(raw.surface_found) } : {})
);

export const optAdapter = (raw, defName) => ({
  name: raw?.adapter?.name ?? defName,
  ...(Array.isArray(raw?.adapter?.capabilities ?? raw?.capabilities)
    ? { capabilities: [...(raw?.adapter?.capabilities ?? raw?.capabilities)] }
    : {}),
});

export function buildComposePayload(raw) {
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
    const bw = isFinNum(bounds.width) ? Number(bounds.width) : 0;
    const bh = isFinNum(bounds.height) ? Number(bounds.height) : 0;
    return {
      presence: n.visible === false ? 'hidden' : 'visible',
      width: bw,
      height: bh,
      scrollWidth: hasOverflow && !hasScrollRange ? bw + 16 : bw,
      clientWidth: bw,
      scrollHeight: hasOverflow ? bh + 16 : bh,
      clientHeight: bh,
      scrollable: hasScrollRange,
      focusable: Boolean(n.focused !== undefined || n.focusable),
      ...(typeof n.obscured === 'boolean' ? { obscured: n.obscured } : {}),
      ...(isFinNum(n.contrastRatio) ? { contrastRatio: n.contrastRatio, contrastCategory: n.contrastCategory ?? 'text_normal' } : {}),
    };
  });
  const hasVp = isFinNum(raw?.viewportWidthDp);
  return {
    ...optSurfaceFlag(raw),
    adapter: optAdapter(raw, 'compose-semantics'),
    environment_ref: raw?.environment_ref,
    roles,
    before: raw?.before,
    action: raw?.action,
    transition: raw?.transition,
    after: raw?.after,
    elements,
    ...(hasVp ? { documentWidth: Number(raw.viewportWidthDp), viewportWidth: Number(raw.viewportWidthDp) } : {}),
  };
}

export function buildUiaPayload(raw) {
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
  const hasWinW = isFinNum(raw?.windowWidthDip);
  return {
    ...optSurfaceFlag(raw),
    adapter: optAdapter(raw, 'windows-uia'),
    environment_ref: raw?.environment_ref,
    roles,
    before: raw?.before,
    action: raw?.action,
    transition: raw?.transition,
    after: raw?.after,
    ...(hasWinW ? { documentWidth: Number(raw.windowWidthDip), viewportWidth: Number(raw.windowWidthDip) } : {}),
  };
}

export function evaluateTaskRecovery(s, before, afterRaw) {
  const reqs = Array.isArray(s?.async_requests ?? afterRaw?.async_requests)
    ? (s?.async_requests ?? afterRaw?.async_requests)
    : null;
  let appliedRequestId = afterRaw?.applied_request_id ?? afterRaw?.appliedRequestId ?? null;
  let staleSuppressed = boolOrNull(afterRaw?.stale_response_suppressed ?? afterRaw?.staleResponseSuppressed, null);

  if (reqs && reqs.length > 0) {
    let latestSeq = -Infinity;
    let latestId = null;
    let maxCommittedSeqSoFar = -Infinity;
    let staleOverwroteNewer = false;
    for (const r of reqs) {
      if (!isObj(r)) continue;
      const seq = Number(r.seq ?? r.request_seq ?? 0);
      const rid = String(r.id ?? r.request_id ?? '');
      if (seq > latestSeq) {
        latestSeq = seq;
        latestId = rid;
      }
      if (r.applied === true || r.overwrote_state === true) {
        if (seq < maxCommittedSeqSoFar) {
          staleOverwroteNewer = true;
        }
        if (seq > maxCommittedSeqSoFar) {
          maxCommittedSeqSoFar = seq;
        }
        appliedRequestId = rid;
      } else if (r.committed === true && seq > maxCommittedSeqSoFar) {
        maxCommittedSeqSoFar = seq;
        if (!appliedRequestId) appliedRequestId = rid;
      }
    }
    const finalApplied = afterRaw?.applied_request_id ?? afterRaw?.appliedRequestId ?? appliedRequestId;
    appliedRequestId = finalApplied;
    if (staleSuppressed === null && latestId !== null && finalApplied !== null) {
      staleSuppressed = finalApplied === latestId && !staleOverwroteNewer;
    }
  } else if (
    staleSuppressed === null
    && afterRaw?.latest_request_id !== undefined
    && appliedRequestId !== null
  ) {
    staleSuppressed = appliedRequestId === afterRaw.latest_request_id;
  }

  const ops = Array.isArray(s?.optimistic_ops ?? afterRaw?.optimistic_ops)
    ? (s?.optimistic_ops ?? afterRaw?.optimistic_ops)
    : null;
  let selectiveRollback = boolOrNull(afterRaw?.selective_rollback_preserved ?? afterRaw?.selectiveRollbackPreserved, null);
  if (ops && ops.length > 0 && selectiveRollback === null) {
    const finalState = isObj(afterRaw?.entity_state ?? afterRaw?.state) ? (afterRaw?.entity_state ?? afterRaw?.state) : {};
    let hasFailed = false;
    let hasCommitted = false;
    let allValid = true;
    for (const op of ops) {
      if (!isObj(op)) continue;
      const field = String(op.field ?? op.id ?? '');
      const actual = field in finalState ? finalState[field] : op.after;
      if (op.status === 'failed' || op.outcome === 'failed') {
        hasFailed = true;
        if (actual !== op.before) {
          allValid = false;
        }
      } else if (op.status === 'committed' || op.status === 'succeeded' || op.outcome === 'committed') {
        hasCommitted = true;
        const expectedCommitted = op.committed_value ?? op.optimistic;
        if (actual !== expectedCommitted) {
          allValid = false;
        }
      }
    }
    if (hasFailed && hasCommitted) {
      selectiveRollback = allValid;
    }
  }

  const dupPrevented = boolOrNull(
    afterRaw?.duplicate_submit_prevented ?? afterRaw?.duplicateSubmitPrevented,
    isFinNum(afterRaw?.in_flight_ignored_submits) && isFinNum(afterRaw?.dispatched_submits)
      ? Number(afterRaw.in_flight_ignored_submits) > 0 && Number(afterRaw.dispatched_submits) === 1
      : null,
  );

  const retryCoherent = boolOrNull(
    afterRaw?.retry_coherent ?? afterRaw?.retryCoherent,
    isObj(afterRaw?.retry_payload) && isObj(before?.dirty_inputs)
      ? JSON.stringify(afterRaw.retry_payload) === JSON.stringify(before.dirty_inputs)
      : null,
  );

  const beforeSteps = isObj(before?.step_data ?? before?.stepData) ? (before.step_data ?? before.stepData) : null;
  const afterSteps = isObj(afterRaw?.step_data ?? afterRaw?.stepData) ? (afterRaw.step_data ?? afterRaw.stepData) : null;
  const stepDataPreserved = boolOrNull(
    afterRaw?.step_data_preserved ?? afterRaw?.stepDataPreserved,
    beforeSteps && afterSteps
      ? Object.keys(beforeSteps).every((k) => JSON.stringify(beforeSteps[k]) === JSON.stringify(afterSteps[k]))
      : null,
  );

  const invFields = Array.isArray(afterRaw?.invalid_fields ?? afterRaw?.invalidFields)
    ? (afterRaw.invalid_fields ?? afterRaw.invalidFields)
    : null;
  const fieldLinkedErrors = boolOrNull(
    afterRaw?.field_linked_errors ?? afterRaw?.fieldLinkedErrors,
    invFields && invFields.length > 0
      ? invFields.every((f) => isObj(f) && Boolean(f.field_id ?? f.fieldId) && Boolean(f.error_id ?? f.errorId) && (f.error_visible ?? f.errorVisible) === true)
      : null,
  );

  const blockFields = Array.isArray(afterRaw?.blocking_fields ?? afterRaw?.blockingFields)
    ? (afterRaw.blocking_fields ?? afterRaw.blockingFields)
    : null;
  const activeStep = afterRaw?.active_step ?? afterRaw?.activeStep ?? before?.active_step;
  const blockingGateScoped = boolOrNull(
    afterRaw?.blocking_gate_scoped ?? afterRaw?.blockingGateScoped,
    blockFields && activeStep !== undefined
      ? blockFields.every((f) => isObj(f) && (f.step ?? f.step_id) === activeStep)
      : null,
  );

  const resumedFromInterruption = boolOrNull(
    afterRaw?.resumed_from_interruption ?? afterRaw?.resumedFromInterruption,
    null,
  );

  return {
    ...(appliedRequestId !== null ? { applied_request_id: appliedRequestId } : {}),
    stale_response_suppressed: staleSuppressed,
    selective_rollback_preserved: selectiveRollback,
    duplicate_submit_prevented: dupPrevented,
    retry_coherent: retryCoherent,
    step_data_preserved: stepDataPreserved,
    field_linked_errors: fieldLinkedErrors,
    blocking_gate_scoped: blockingGateScoped,
    resumed_from_interruption: resumedFromInterruption,
  };
}

export async function evaluateScenarioMatrix(spec, checkViewTableFn) {
  const s = isObj(spec) ? spec : {};
  const contractId = String(s.contract ?? 'ui-contract');
  const caseId = String(s.caseId ?? s.case_id ?? 'scenario-matrix');
  const required = Array.isArray(s.required_scenarios ?? s.requiredScenarios)
    ? [...(s.required_scenarios ?? s.requiredScenarios)]
    : [...DEFAULT_CURATED_UI_SCENARIOS];
  const scenarios = isObj(s.scenarios) ? s.scenarios : {};
  const verifiedScenarios = [];
  const verifiedEnvironments = [];

  for (const scName of required) {
    const entry = scenarios[scName];
    if (!isObj(entry)) {
      const err = new Error(`${contractId}.${caseId}: scenario_matrix.missing:${scName}`);
      err.name = 'AssertionError';
      err.code = 'ERR_ASSERTION';
      throw err;
    }
    const obs = isObj(entry.observation) ? entry.observation : entry;
    const sf = obs.surface_found === true || obs.surfaceFound === true;
    const unv = Number(obs.evidence?.unverifiable_checks ?? obs.unverifiable_checks ?? 0);
    if (!sf || unv > 0) {
      const reason = !sf ? 'surface.missing' : `unverifiable_checks=${unv}`;
      const err = new Error(`${contractId}.${caseId}: scenario_matrix.unverifiable:${scName}:${reason}`);
      err.name = 'AssertionError';
      err.code = 'ERR_ASSERTION';
      throw err;
    }
    const thenTbl = isObj(entry.then) ? entry.then : (isObj(s.then) ? s.then : null);
    if (thenTbl && typeof checkViewTableFn === 'function') {
      const proj = isObj(entry.projections) ? entry.projections : (isObj(s.projections) ? s.projections : {});
      await checkViewTableFn(contractId, `${caseId}[${scName}]`, thenTbl, new Set(), obs, {}, null, new Map(), () => proj);
    }
    verifiedScenarios.push(scName);
    if (obs.environment_ref && !verifiedEnvironments.includes(obs.environment_ref)) {
      verifiedEnvironments.push(obs.environment_ref);
    }
  }

  return {
    schema: 'drift.ui-scenario-matrix/1',
    contract: contractId,
    case_id: caseId,
    verified_scenarios: verifiedScenarios,
    verified_environments: verifiedEnvironments,
    all_scenarios_passed: verifiedScenarios.length === required.length,
    claim_scope: 'verified_in_declared_scenarios_and_environments',
  };
}
