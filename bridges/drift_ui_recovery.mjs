// Task-completion recovery invariants (async-action-feedback@1, wizard-form@1) and curated UI scenario matrices.
export const DEFAULT_CURATED_UI_SCENARIOS = Object.freeze(['keyboard_only', 'narrow_viewport', 'long_localized_text', 'reduced_motion', 'slow_or_failed_async']);
export const CAPS_03 = ['rel-keys-guard/1', 'rel-linear-balance/1', 'rel-peer-sum/1', 'rel-series/1', 'rel-tol/1', 'unit-conversion/1'];
const isStr = (v) => typeof v === 'string';
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isFinNum = (v) => typeof v === 'number' && Number.isFinite(v);
const boolOrNull = (v, fb) => (typeof v === 'boolean' ? v : fb);
export const unwrap03Eq = (v) => (isObj(v) && Object.keys(v).length === 1 && 'eq' in v ? v.eq : v);

function isElHiddenBasic(el) {
  if (!isObj(el)) return false;
  const pres = String(el.presence ?? el.state ?? '').toLowerCase();
  if (pres === 'hidden' || pres === 'absent' || pres === 'collapsed' || el.hidden === true || el.ariaHidden === true || el['aria-hidden'] === 'true') return true;
  return String(el.display ?? el.style?.display ?? '').toLowerCase() === 'none' || ['hidden', 'collapse'].includes(String(el.visibility ?? el.style?.visibility ?? '').toLowerCase());
}

export function deriveObservedCapabilities(s, rawRoles, elements, before, transRaw, afterRaw, contrastSummary) {
  const caps = [], els = Array.isArray(elements) ? elements : [];
  const hasRoleGeom = Object.values(isObj(rawRoles) ? rawRoles : {}).some((r) => {
    if (!isObj(r) || isElHiddenBasic(r)) return false;
    const g = isObj(r.geometry) ? r.geometry : r;
    return isFinNum(g?.width) && isFinNum(g?.height) && Number(g.width) > 0 && Number(g.height) > 0;
  });
  const hasElGeom = els.some((el) => isObj(el) && !isElHiddenBasic(el) && isFinNum(el.width) && isFinNum(el.height) && el.width > 0 && el.height > 0);
  if (hasRoleGeom || hasElGeom || (isFinNum(s?.viewportWidth) && Number(s.viewportWidth) > 0 && isFinNum(s?.documentWidth))) caps.push('geometry');
  if (before?.input_focus_role || before?.inputFocusRole || afterRaw?.input_focus_role || afterRaw?.inputFocusRole || Array.isArray(transRaw?.focus_trace) || Array.isArray(transRaw?.focusTrace) || isFinNum(transRaw?.unexpected_focus_steals) || isFinNum(transRaw?.unexpectedFocusSteals) || els.some((el) => isObj(el) && (el.focused !== undefined || el.focusable === true))) caps.push('input_focus');
  if (s?.assistive_announcement !== undefined || s?.active_assistive_focus !== undefined || afterRaw?.assistive_announcement !== undefined || afterRaw?.active_assistive_focus !== undefined || Array.isArray(s?.assistive_trace) || Array.isArray(transRaw?.assistive_trace)) caps.push('assistive_focus');
  const rawCw = s?.presentation?.contrast_wcag22;
  if (contrastSummary?.measuredCount > 0 || isFinNum(rawCw?.text_normal_min) || isFinNum(rawCw?.text_large_min) || isFinNum(rawCw?.ui_component_min) || isFinNum(rawCw?.violations_count) || isFinNum(s?.min_contrast_ratio) || isFinNum(s?.min_contrast_wcag22)) caps.push('wcag22_contrast');
  if (isFinNum(transRaw?.observed_duration_ms) || isFinNum(transRaw?.observedDurationMs) || isFinNum(transRaw?.configured_duration_ms) || isFinNum(transRaw?.configuredDurationMs)) caps.push('observed_transition');
  if (before?.scroll_anchor_id !== undefined || before?.scrollAnchorId !== undefined || afterRaw?.scroll_anchor_id !== undefined || afterRaw?.scrollAnchorId !== undefined || isFinNum(afterRaw?.scroll_offset_delta) || typeof afterRaw?.scroll_context_preserved === 'boolean' || els.some((el) => isObj(el) && (el.scrollable !== undefined || el.horizontallyScrollable !== undefined || el.verticallyScrollable !== undefined || isFinNum(el.scrollWidth) || isFinNum(el.scrollHeight)))) caps.push('scroll_state');
  return caps;
}

export function isPointCoveredByVisualOverlays(px, py, el, overlays) {
  if (!Array.isArray(overlays) || !overlays.length) return false;
  const elZ = Number(el?.zIndex ?? el?.style?.zIndex ?? 0);
  for (const ov of overlays) {
    if (!isObj(ov) || ov === el || isElHiddenBasic(ov)) continue;
    if ((typeof el?.contains === 'function' && el.contains(ov)) || (typeof ov.contains === 'function' && ov.contains(el))) continue;
    const opacity = Number(ov.opacity ?? ov.style?.opacity ?? 1);
    if (Number.isFinite(opacity) && opacity <= 0) continue;
    if (Number(ov.zIndex ?? ov.style?.zIndex ?? 1) < elZ && ov.blocksVisualFocus !== true && ov.isOverlay !== true) continue;
    const r = typeof ov.getBoundingClientRect === 'function' ? ov.getBoundingClientRect() : (ov.rect ?? ov);
    const left = Number(r?.left ?? r?.x ?? 0), top = Number(r?.top ?? r?.y ?? 0), w = Number(r?.width ?? 0), h = Number(r?.height ?? 0);
    if (w > 0 && h > 0 && px >= left && px <= left + w && py >= top && py <= top + h) return true;
  }
  return false;
}

const optSurfaceFlag = (raw) => (raw?.surfaceFound !== undefined ? { surface_found: Boolean(raw.surfaceFound) } : (raw?.surface_found !== undefined ? { surface_found: Boolean(raw.surface_found) } : {}));
export const optAdapter = (raw, defName) => ({ name: raw?.adapter?.name ?? defName, ...(Array.isArray(raw?.adapter?.capabilities ?? raw?.capabilities) ? { capabilities: [...(raw?.adapter?.capabilities ?? raw?.capabilities)] } : {}) });

export function buildComposePayload(raw) {
  const nodes = isObj(raw?.nodes) ? raw.nodes : {}, roles = {};
  for (const [roleId, n] of Object.entries(nodes)) {
    if (!isObj(n)) continue;
    const visible = n.visible !== false && n.displayed !== false, bounds = isObj(n.boundsInRoot ?? n.bounds) ? (n.boundsInRoot ?? n.bounds) : {};
    const semRole = String(n.liveRegion ?? '').toLowerCase() === 'assertive' || n.isDialog === true ? (n.isModal === true ? 'alertdialog' : 'alert') : String(n.role ?? 'region').toLowerCase();
    roles[roleId] = {
      presence: visible ? (n.presence ?? 'visible') : (n.presence ?? 'hidden'), semantic_role: semRole,
      ...(n.selectedEntityId !== undefined ? { selected_entity_id: n.selectedEntityId } : {}),
      ...(n.boundEntityId !== undefined ? { bound_entity_id: n.boundEntityId } : {}),
      ...(n.containerMode !== undefined ? { container_mode: n.containerMode } : {}),
      actions: Array.isArray(n.actions) ? n.actions : [],
      content_cues: { has_visible_text: Boolean(visible && String(n.text ?? '').trim()), has_graphic_icon: Boolean(visible && (n.hasIcon === true || n.contentDescription)), has_semantic_role: ['alert', 'alertdialog', 'status'].includes(semRole) },
      geometry: { unit: 'dp', x: Number(bounds.left ?? bounds.x ?? 0), y: Number(bounds.top ?? bounds.y ?? 0), width: Number(bounds.width ?? 0), height: Number(bounds.height ?? 0), reading_order_rank: Number(n.traversalIndex ?? n.readingOrderRank ?? 0) },
    };
  }
  const elements = Object.values(nodes).filter(isObj).map((n) => {
    const b = isObj(n.boundsInRoot ?? n.bounds) ? (n.boundsInRoot ?? n.bounds) : {}, hasSr = Boolean(n.verticalScrollAxisRange || n.horizontalScrollAxisRange || n.scrollable);
    const bw = isFinNum(b.width) ? Number(b.width) : 0, bh = isFinNum(b.height) ? Number(b.height) : 0;
    return {
      presence: n.visible === false ? 'hidden' : 'visible', width: bw, height: bh,
      scrollWidth: n.hasVisualOverflow && !hasSr ? bw + 16 : bw, clientWidth: bw, scrollHeight: n.hasVisualOverflow ? bh + 16 : bh, clientHeight: bh,
      scrollable: hasSr, focusable: Boolean(n.focused !== undefined || n.focusable),
      ...(typeof n.obscured === 'boolean' ? { obscured: n.obscured } : {}),
      ...(isFinNum(n.contrastRatio) ? { contrastRatio: n.contrastRatio, contrastCategory: n.contrastCategory ?? 'text_normal' } : {}),
    };
  });
  const hasVp = isFinNum(raw?.viewportWidthDp);
  return { ...optSurfaceFlag(raw), adapter: optAdapter(raw, 'compose-semantics'), environment_ref: raw?.environment_ref, roles, before: raw?.before, action: raw?.action, transition: raw?.transition, after: raw?.after, elements, ...(hasVp ? { documentWidth: Number(raw.viewportWidthDp), viewportWidth: Number(raw.viewportWidthDp) } : {}) };
}

export function buildUiaPayload(raw) {
  const controls = isObj(raw?.elements ?? raw?.controls) ? (raw.elements ?? raw.controls) : {}, roles = {};
  for (const [roleId, c] of Object.entries(controls)) {
    if (!isObj(c)) continue;
    const off = Boolean(c.IsOffscreen === true || c.presence === 'hidden' || c.presence === 'absent'), rect = isObj(c.BoundingRectangle ?? c.rect) ? (c.BoundingRectangle ?? c.rect) : {};
    const ct = String(c.ControlType ?? c.semantic_role ?? 'Pane'), semRole = ct === 'Window.AlertDialog' || c.isModal === true ? 'alertdialog' : (ct === 'StatusBar' || ct === 'Alert' ? 'alert' : 'region');
    roles[roleId] = {
      presence: off ? (c.presence ?? 'hidden') : 'visible', semantic_role: semRole,
      ...(c.selectedEntityId !== undefined ? { selected_entity_id: c.selectedEntityId } : {}),
      ...(c.boundEntityId !== undefined ? { bound_entity_id: c.boundEntityId } : {}),
      ...(c.containerMode !== undefined ? { container_mode: c.containerMode } : {}),
      actions: Array.isArray(c.patterns) ? c.patterns : [],
      content_cues: { has_visible_text: Boolean(!off && String(c.Name ?? c.text ?? '').trim()), has_graphic_icon: Boolean(!off && c.hasIcon === true), has_semantic_role: semRole === 'alert' || semRole === 'alertdialog' },
      geometry: { unit: 'dip', x: Number(rect.x ?? rect.left ?? 0), y: Number(rect.y ?? rect.top ?? 0), width: Number(rect.width ?? 0), height: Number(rect.height ?? 0), reading_order_rank: Number(c.readingOrderRank ?? 0) },
    };
  }
  const hasW = isFinNum(raw?.windowWidthDip);
  return { ...optSurfaceFlag(raw), adapter: optAdapter(raw, 'windows-uia'), environment_ref: raw?.environment_ref, roles, before: raw?.before, action: raw?.action, transition: raw?.transition, after: raw?.after, ...(hasW ? { documentWidth: Number(raw.windowWidthDip), viewportWidth: Number(raw.windowWidthDip) } : {}) };
}

export function evaluateTaskRecovery(s, before, afterRaw) {
  const reqs = Array.isArray(s?.async_requests ?? afterRaw?.async_requests) ? (s?.async_requests ?? afterRaw?.async_requests) : null;
  let appliedRequestId = afterRaw?.applied_request_id ?? afterRaw?.appliedRequestId ?? null;
  let staleSuppressed = boolOrNull(afterRaw?.stale_response_suppressed ?? afterRaw?.staleResponseSuppressed, null);
  if (reqs?.length) {
    let latestSeq = -Infinity, latestId = null, maxCom = -Infinity, staleOver = false;
    for (const r of reqs) {
      if (!isObj(r)) continue;
      const seq = Number(r.seq ?? r.request_seq ?? 0), rid = String(r.id ?? r.request_id ?? '');
      if (seq > latestSeq) { latestSeq = seq; latestId = rid; }
      if (r.applied === true || r.overwrote_state === true) {
        if (seq < maxCom) staleOver = true;
        if (seq > maxCom) maxCom = seq;
        appliedRequestId = rid;
      } else if (r.committed === true && seq > maxCom) { maxCom = seq; if (!appliedRequestId) appliedRequestId = rid; }
    }
    appliedRequestId = afterRaw?.applied_request_id ?? afterRaw?.appliedRequestId ?? appliedRequestId;
    if (staleSuppressed === null && latestId !== null && appliedRequestId !== null) staleSuppressed = appliedRequestId === latestId && !staleOver;
  } else if (staleSuppressed === null && afterRaw?.latest_request_id !== undefined && appliedRequestId !== null) {
    staleSuppressed = appliedRequestId === afterRaw.latest_request_id;
  }
  const ops = Array.isArray(s?.optimistic_ops ?? afterRaw?.optimistic_ops) ? (s?.optimistic_ops ?? afterRaw?.optimistic_ops) : null;
  let selectiveRollback = boolOrNull(afterRaw?.selective_rollback_preserved ?? afterRaw?.selectiveRollbackPreserved, null);
  if (ops?.length && selectiveRollback === null) {
    const finalState = isObj(afterRaw?.entity_state ?? afterRaw?.state) ? (afterRaw?.entity_state ?? afterRaw?.state) : {};
    let hasFail = false, hasCom = false, ok = true;
    for (const op of ops) {
      if (!isObj(op)) continue;
      const fld = String(op.field ?? op.id ?? ''), act = fld in finalState ? finalState[fld] : op.after;
      if (op.status === 'failed' || op.outcome === 'failed') { hasFail = true; if (act !== op.before) ok = false; }
      else if (['committed', 'succeeded'].includes(op.status) || op.outcome === 'committed') { hasCom = true; if (act !== (op.committed_value ?? op.optimistic)) ok = false; }
    }
    if (hasFail && hasCom) selectiveRollback = ok;
  }
  const beforeSteps = isObj(before?.step_data ?? before?.stepData) ? (before.step_data ?? before.stepData) : null;
  const afterSteps = isObj(afterRaw?.step_data ?? afterRaw?.stepData) ? (afterRaw.step_data ?? afterRaw.stepData) : null;
  const invFields = Array.isArray(afterRaw?.invalid_fields ?? afterRaw?.invalidFields) ? (afterRaw.invalid_fields ?? afterRaw.invalidFields) : null;
  const blockFields = Array.isArray(afterRaw?.blocking_fields ?? afterRaw?.blockingFields) ? (afterRaw.blocking_fields ?? afterRaw.blockingFields) : null;
  const activeStep = afterRaw?.active_step ?? afterRaw?.activeStep ?? before?.active_step;
  return {
    ...(appliedRequestId !== null ? { applied_request_id: appliedRequestId } : {}),
    stale_response_suppressed: staleSuppressed,
    selective_rollback_preserved: selectiveRollback,
    duplicate_submit_prevented: boolOrNull(afterRaw?.duplicate_submit_prevented ?? afterRaw?.duplicateSubmitPrevented, isFinNum(afterRaw?.in_flight_ignored_submits) && isFinNum(afterRaw?.dispatched_submits) ? Number(afterRaw.in_flight_ignored_submits) > 0 && Number(afterRaw.dispatched_submits) === 1 : null),
    retry_coherent: boolOrNull(afterRaw?.retry_coherent ?? afterRaw?.retryCoherent, isObj(afterRaw?.retry_payload) && isObj(before?.dirty_inputs) ? JSON.stringify(afterRaw.retry_payload) === JSON.stringify(before.dirty_inputs) : null),
    step_data_preserved: boolOrNull(afterRaw?.step_data_preserved ?? afterRaw?.stepDataPreserved, beforeSteps && afterSteps ? Object.keys(beforeSteps).every((k) => JSON.stringify(beforeSteps[k]) === JSON.stringify(afterSteps[k])) : null),
    field_linked_errors: boolOrNull(afterRaw?.field_linked_errors ?? afterRaw?.fieldLinkedErrors, invFields?.length ? invFields.every((f) => isObj(f) && Boolean(f.field_id ?? f.fieldId) && Boolean(f.error_id ?? f.errorId) && (f.error_visible ?? f.errorVisible) === true) : null),
    blocking_gate_scoped: boolOrNull(afterRaw?.blocking_gate_scoped ?? afterRaw?.blockingGateScoped, blockFields && activeStep !== undefined ? blockFields.every((f) => isObj(f) && (f.step ?? f.step_id) === activeStep) : null),
    resumed_from_interruption: boolOrNull(afterRaw?.resumed_from_interruption ?? afterRaw?.resumedFromInterruption, null),
  };
}

export async function evaluateScenarioMatrix(spec, checkViewTableFn) {
  const s = isObj(spec) ? spec : {}, contractId = String(s.contract ?? 'ui-contract'), caseId = String(s.caseId ?? s.case_id ?? 'scenario-matrix');
  const required = Array.isArray(s.required_scenarios ?? s.requiredScenarios) ? [...(s.required_scenarios ?? s.requiredScenarios)] : [...DEFAULT_CURATED_UI_SCENARIOS];
  const scenarios = isObj(s.scenarios) ? s.scenarios : {}, verifiedScenarios = [], verifiedEnvironments = [];
  const aFail = (msg) => { const err = new Error(msg); err.name = 'AssertionError'; err.code = 'ERR_ASSERTION'; throw err; };
  for (const scName of required) {
    const entry = scenarios[scName];
    if (!isObj(entry)) aFail(`${contractId}.${caseId}: scenario_matrix.missing:${scName}`);
    const obs = isObj(entry.observation) ? entry.observation : entry;
    const sf = obs.surface_found === true || obs.surfaceFound === true, unv = Number(obs.evidence?.unverifiable_checks ?? obs.unverifiable_checks ?? 0);
    if (!sf || unv > 0) aFail(`${contractId}.${caseId}: scenario_matrix.unverifiable:${scName}:${!sf ? 'surface.missing' : `unverifiable_checks=${unv}`}`);
    const thenTbl = isObj(entry.then) ? entry.then : (isObj(s.then) ? s.then : null);
    if (thenTbl && typeof checkViewTableFn === 'function') {
      const proj = isObj(entry.projections) ? entry.projections : (isObj(s.projections) ? s.projections : {});
      await checkViewTableFn(contractId, `${caseId}[${scName}]`, thenTbl, new Set(), obs, {}, null, new Map(), () => proj);
    }
    verifiedScenarios.push(scName);
    if (obs.environment_ref && !verifiedEnvironments.includes(obs.environment_ref)) verifiedEnvironments.push(obs.environment_ref);
  }
  return { schema: 'drift.ui-scenario-matrix/1', contract: contractId, case_id: caseId, verified_scenarios: verifiedScenarios, verified_environments: verifiedEnvironments, all_scenarios_passed: verifiedScenarios.length === required.length, claim_scope: 'verified_in_declared_scenarios_and_environments' };
}

const qualifyPeer03 = (s) => (isStr(s) && s.trim() ? ((s.trim().startsWith('when.') || s.trim().startsWith('then.') || s.trim().startsWith('/')) ? s.trim() : `then.${s.trim()}`) : s);
export function desugar03Rel(raw, units = {}, predUnit = null) {
  if (!isObj(raw)) return raw;
  const out = {};
  for (const [k, v] of Object.entries(raw)) {
    if (k === 'tol' && isObj(v)) {
      if ('abs' in v) out.abs_tol = v.abs;
      if ('rel' in v) out.rel_tol = v.rel;
    } else if (k === 'len' && isObj(v)) {
      if ('min' in v) out.min_len = v.min;
      if ('max' in v) out.max_len = v.max;
    } else if (k === 'keys' && isObj(v)) {
      if ('allow' in v) out.allowed_keys = v.allow;
      if ('forbid' in v) out.forbid_keys = v.forbid;
    } else if (k === 'peer' && isObj(v)) {
      if ('le' in v) out.le_field = qualifyPeer03(v.le);
      if ('ge' in v) out.ge_field = qualifyPeer03(v.ge);
      if ('eq' in v) out.eq_field = qualifyPeer03(v.eq);
      if (Array.isArray(v.sum)) out.sum_fields = v.sum.map(qualifyPeer03);
      if (isObj(v.balance)) {
        out.balance_fields = {
          ...(Array.isArray(v.balance.add) ? { add: v.balance.add.map(qualifyPeer03) } : {}),
          ...(Array.isArray(v.balance.sub) ? { sub: v.balance.sub.map(qualifyPeer03) } : {}),
        };
      }
    } else if (k === 'series' && isObj(v)) {
      Object.assign(out, v);
      if (out.monotonic === 'increasing' || out.monotonic === 'decreasing') {
        out.monotonic = `strictly_${out.monotonic}`;
      }
    } else if (k !== 'convert_from') {
      out[k] = v;
    }
  }
  if ('convert_from' in raw) {
    const cf = raw.convert_from;
    const matches = Object.keys(units).filter((k) => k.startsWith(`${cf}->`));
    const target = predUnit ?? raw.unit;
    const ratio = target === cf ? 1 : units[target ? `${cf}->${target}` : (matches.length === 1 ? matches[0] : '')];
    if (typeof ratio !== 'number' || !Number.isFinite(ratio) || ratio <= 0) {
      throw new Error(`missing unit conversion from ${cf}${target ? ` to ${target}` : ''}`);
    }
    const scale = (v) => typeof v === 'number' ? v * ratio : v;
    for (const k of ['eq', 'min', 'max', 'approx', 'abs_tol', 'step_max_delta']) {
      if (k in out) out[k] = scale(out[k]);
    }
    for (const k of ['in', 'not_in']) {
      if (Array.isArray(out[k])) out[k] = out[k].map(scale);
    }
    if ('sum_total' in out) {
      out.sum_total = isObj(out.sum_total)
        ? Object.fromEntries(Object.entries(out.sum_total).map(([k, v]) => [k, scale(v)]))
        : scale(out.sum_total);
    }
  }
  if ('eq' in out && ('abs_tol' in out || 'rel_tol' in out) && !('balance_fields' in out) && !('sum_fields' in out)) {
    out.approx = out.eq;
    delete out.eq;
  }
  return out;
}

export function buildWhenEnv(whenTable, whenProj, thenTable, thenProj, payload = null, explicitWhen = null, readPointer = null, checkRelFn = null, contractId = '', caseId = '') {
  const env = {};
  const hasExp = isObj(explicitWhen) || (isObj(payload) && (isObj(payload.when) || isObj(payload.before)));
  if (!hasExp) {
    for (const [wk, wv] of Object.entries(whenTable || {})) {
      if (!isObj(wv)) env[wk] = wv;
      else if ('eq' in wv && !('peer' in wv) && !('eq_field' in wv)) env[wk] = wv.eq;
    }
  }
  if (isObj(explicitWhen)) {
    for (const [wk, ov] of Object.entries(explicitWhen)) env[wk] = ov;
  }
  if (isObj(payload)) {
    for (const subK of ['when', 'before']) {
      if (isObj(payload[subK])) {
        for (const [wk, ov] of Object.entries(payload[subK])) env[wk] = ov;
      }
    }
    for (const [pk, pv] of Object.entries(payload)) {
      if (pk.startsWith('when.') && pk.length > 5) env[pk.slice(5)] = pv;
    }
    if (isObj(whenProj) && typeof readPointer === 'function') {
      const tPtrs = new Set([...Object.values(thenProj || {}), ...Object.keys(thenTable || {}).map((tk) => `/${tk}`)]);
      for (const [wk, wPtr] of Object.entries(whenProj)) {
        let hit = false;
        for (const src of [explicitWhen, isObj(payload.when) ? payload.when : null, isObj(payload.before) ? payload.before : null]) {
          if (isObj(src)) {
            const r = readPointer(src, wPtr);
            if (r.found) { env[wk] = r.value; hit = true; break; }
          }
        }
        if (!hit && !hasExp && wPtr && !tPtrs.has(wPtr) && !(wk in (thenTable || {}))) {
          const r = readPointer(payload, wPtr);
          if (r.found) env[wk] = r.value;
        }
      }
    }
  }
  if (hasExp && isObj(whenTable) && typeof checkRelFn === 'function') {
    for (const [wk, wexp] of Object.entries(whenTable)) {
      if (wk in env) {
        const actW = env[wk];
        if (isObj(wexp)) checkRelFn(contractId, caseId, `when.${wk}`, wexp, actW, env, whenProj || {}, null, env);
        else if (JSON.stringify(actW) !== JSON.stringify(wexp)) {
          const err = new Error(`${contractId}.${caseId}: expected when.${wk}=${JSON.stringify(wexp)}, got ${JSON.stringify(actW)}`);
          err.name = 'AssertionError';
          err.code = 'ERR_ASSERTION';
          throw err;
        }
      }
    }
  }
  return env;
}

export function resolvePeerValue(ref, payload, proj, whenEnv, readPointer) {
  if (!isStr(ref) || !ref.trim()) return { found: false };
  const r = ref.trim();
  if (r.startsWith('when.')) {
    const wk = r.slice(5);
    if (!wk) return { found: false };
    if (isObj(whenEnv)) {
      if (wk in whenEnv) return { found: true, value: whenEnv[wk] };
      if (r in whenEnv) return { found: true, value: whenEnv[r] };
    }
    if (isObj(payload) && !whenEnv) {
      if (r in payload) return { found: true, value: payload[r] };
      for (const subK of ['when', 'before']) {
        if (isObj(payload[subK]) && wk in payload[subK]) return { found: true, value: payload[subK][wk] };
      }
    }
    return { found: false };
  }
  if (r.startsWith('then.')) {
    const tk = r.slice(5);
    if (!tk) return { found: false };
    const tSrc = isObj(payload) && isObj(payload.then) && !(tk in payload) ? payload.then : payload;
    if (proj && tk in proj) {
      const rd = readPointer(tSrc, proj[tk]);
      if (rd.found) return rd;
    }
    if (isObj(tSrc) && tk in tSrc) return { found: true, value: tSrc[tk] };
    if (isObj(payload) && r in payload) return { found: true, value: payload[r] };
    return { found: false };
  }
  if (r.startsWith('/')) return readPointer(payload, r);
  if (proj && r in proj) return readPointer(payload, proj[r]);
  if (isObj(payload) && r in payload) return { found: true, value: payload[r] };
  if (isObj(whenEnv) && r in whenEnv) return { found: true, value: whenEnv[r] };
  return { found: false };
}

function expandSingleDomain(spec, first = false) {
  if (Array.isArray(spec)) {
    if (!spec.length) throw new Error('domain sample array must not be empty');
    return first ? [spec[0]] : [...spec];
  }
  if (!isObj(spec)) throw new Error('domain specification must be an array or an object');
  if (spec.type === 'int') {
    const min = Number(spec.min);
    const max = Number(spec.max);
    if (!Number.isSafeInteger(min) || !Number.isSafeInteger(max) || min > max) {
      throw new Error(`invalid int domain [${spec.min}, ${spec.max}]`);
    }
    if (first) return [min < 0 && max > 0 ? 0 : min];
    return [...new Set([...(min < 0 && max > 0 ? [0] : []), min, min < max ? min + 1 : min, Math.trunc((min + max) / 2), max > min ? max - 1 : max, max])];
  }
  if (spec.type === 'string' && Array.isArray(spec.enum) && spec.enum.length) {
    return first ? [String(spec.enum[0])] : [...new Set(spec.enum.map(String))];
  }
  return spec.type === 'bool' ? (first ? [false] : [false, true]) : null;
}

export function expandDomain(domain, first = false) {
  const single = expandSingleDomain(domain, first);
  if (single !== null) return single;
  const keys = Object.keys(domain).sort();
  const d = keys.length;
  if (!d) throw new Error('Cartesian domain map must not be empty');
  const valsByKey = keys.map((k) => {
    const vals = expandSingleDomain(domain[k], first);
    if (vals === null) throw new Error(`invalid domain specification for key "${k}"`);
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
