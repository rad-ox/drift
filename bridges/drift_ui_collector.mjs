// Three-stage live UI sequence collector, observed-only capability derivation, and visual overlay focus checks.
import { isElementHidden, observeUiSequence } from './drift_ui.mjs';
import { deriveObservedCapabilities, isPointCoveredByVisualOverlays } from './drift_ui_recovery.mjs';

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isFinNum = (v) => typeof v === 'number' && Number.isFinite(v);

export { deriveObservedCapabilities, isPointCoveredByVisualOverlays };

function extractSurfaceRoleState(root, roleSelectors) {
  const roles = {};
  if (!isObj(root)) return roles;
  if (isObj(root.roles)) {
    for (const [k, v] of Object.entries(root.roles)) {
      roles[k] = isObj(v) ? { ...v, ...(isObj(v.geometry) ? { geometry: { ...v.geometry } } : {}) } : v;
    }
    return roles;
  }
  if (isObj(roleSelectors) && typeof root.querySelector === 'function') {
    for (const [roleId, sel] of Object.entries(roleSelectors)) {
      const node = root.querySelector(sel);
      if (!node) {
        roles[roleId] = { presence: 'absent' };
        continue;
      }
      const rect = typeof node.getBoundingClientRect === 'function' ? node.getBoundingClientRect() : (node.rect ?? {});
      const getAttr = (k) => (typeof node.getAttribute === 'function' ? node.getAttribute(k) : node[k]);
      roles[roleId] = {
        presence: isElementHidden(node) ? 'hidden' : 'visible',
        semantic_role: String(getAttr('role') ?? node.semantic_role ?? 'region').toLowerCase(),
        text: String(node.textContent ?? node.text ?? '').trim(),
        hasIcon: Boolean(node.hasIcon || (typeof node.querySelector === 'function' && node.querySelector('svg, [role="img"]'))),
        ...(getAttr('data-selected-entity-id') || node.selected_entity_id ? { selected_entity_id: getAttr('data-selected-entity-id') ?? node.selected_entity_id } : {}),
        ...(getAttr('data-bound-entity-id') || node.bound_entity_id ? { bound_entity_id: getAttr('data-bound-entity-id') ?? node.bound_entity_id } : {}),
        ...(getAttr('data-container-mode') || node.container_mode ? { container_mode: getAttr('data-container-mode') ?? node.container_mode } : {}),
        geometry: {
          unit: 'px',
          x: Number(rect.left ?? rect.x ?? 0),
          y: Number(rect.top ?? rect.y ?? 0),
          width: Number(rect.width ?? node.width ?? 0),
          height: Number(rect.height ?? node.height ?? 0),
          ...(isFinNum(node.reading_order_rank) ? { reading_order_rank: Number(node.reading_order_rank) } : {}),
        },
      };
    }
  }
  return roles;
}

export async function collectPlaywrightSequence(options) {
  const opts = isObj(options) ? options : {};
  const root = typeof opts.resolveRoot === 'function' ? await opts.resolveRoot() : (opts.root ?? null);
  if (!root || root.surfaceFound === false || root.surface_found === false) {
    return observeUiSequence({
      surface_found: false,
      adapter: { name: opts.adapter?.name ?? 'playwright-collector', capabilities: [] },
      evidence: { unverifiable_checks: 1, unverifiable_reasons: ['surface.missing'] },
    });
  }

  const nowFn = typeof opts.now === 'function' ? opts.now : () => Date.now();
  const beforeSnap = {
    input_focus_role: opts.before?.input_focus_role ?? root.input_focus_role ?? root.activeFocusRole ?? '',
    ...(opts.before?.selected_entity_id !== undefined || root.selected_entity_id !== undefined
      ? { selected_entity_id: opts.before?.selected_entity_id ?? root.selected_entity_id }
      : {}),
    ...(opts.before?.scroll_anchor_id !== undefined || root.scroll_anchor_id !== undefined
      ? { scroll_anchor_id: opts.before?.scroll_anchor_id ?? root.scroll_anchor_id }
      : {}),
    ...(isObj(opts.before?.dirty_inputs ?? root.dirty_inputs)
      ? { dirty_inputs: JSON.parse(JSON.stringify(opts.before?.dirty_inputs ?? root.dirty_inputs)) }
      : {}),
    ...(isObj(opts.before?.step_data ?? root.step_data)
      ? { step_data: JSON.parse(JSON.stringify(opts.before?.step_data ?? root.step_data)) }
      : {}),
  };

  const focusTrace = [];
  let listenersAttached = false;
  let listenersDetached = false;
  const onFocusIn = (evOrRole) => {
    const role = typeof evOrRole === 'string'
      ? evOrRole
      : String(evOrRole?.target?.getAttribute?.('data-drift-role') ?? evOrRole?.target?.roleId ?? evOrRole?.role ?? '');
    if (role) {
      focusTrace.push(role);
      root.input_focus_role = role;
    }
  };

  const attachScoped = () => {
    listenersAttached = true;
    if (typeof root.addEventListener === 'function') {
      root.addEventListener('focusin', onFocusIn);
    } else if (Array.isArray(root._focusListeners)) {
      root._focusListeners.push(onFocusIn);
    } else {
      root._focusListeners = [onFocusIn];
    }
  };

  const detachScoped = () => {
    if (!listenersAttached) return;
    if (typeof root.removeEventListener === 'function') {
      root.removeEventListener('focusin', onFocusIn);
    } else if (Array.isArray(root._focusListeners)) {
      const idx = root._focusListeners.indexOf(onFocusIn);
      if (idx >= 0) root._focusListeners.splice(idx, 1);
    }
    listenersAttached = false;
    listenersDetached = true;
  };

  const asyncRequests = [];
  const optimisticOps = [];
  const scope = {
    root,
    emitFocus: (roleId) => onFocusIn(roleId),
    recordRequest: (req) => { if (isObj(req)) asyncRequests.push({ ...req }); },
    recordOptimisticOp: (op) => { if (isObj(op)) optimisticOps.push({ ...op }); },
    get listenersAttached() { return listenersAttached; },
  };

  const t0 = Number(nowFn());
  let settleTimedOut = false;
  attachScoped();
  try {
    if (typeof opts.action === 'function') {
      await opts.action(scope);
    }
    if (typeof opts.waitUntil === 'function') {
      const timeoutMs = isFinNum(opts.timeoutMs) ? Number(opts.timeoutMs) : 1000;
      const pollMs = isFinNum(opts.pollIntervalMs) ? Number(opts.pollIntervalMs) : 5;
      let settled = Boolean(await opts.waitUntil(scope));
      while (!settled && Number(nowFn()) - t0 < timeoutMs) {
        if (typeof opts.advanceTime === 'function') {
          await opts.advanceTime(pollMs);
        } else {
          await new Promise((r) => setTimeout(r, pollMs));
        }
        settled = Boolean(await opts.waitUntil(scope));
      }
      if (!settled) {
        settleTimedOut = true;
      }
    }
  } finally {
    detachScoped();
  }
  const t1 = Number(nowFn());
  const observedDurationMs = isFinNum(opts.observedDurationMs)
    ? Number(opts.observedDurationMs)
    : Math.max(0, Math.round(t1 - t0));

  const rolesAfter = extractSurfaceRoleState(root, opts.roleSelectors);
  const elementsAfter = Array.isArray(root.elements) ? root.elements : (Array.isArray(opts.elements) ? opts.elements : []);
  const afterSnap = {
    ...(isObj(opts.after) ? opts.after : {}),
    ...(isObj(root.after) ? root.after : {}),
    input_focus_role: root.input_focus_role ?? root.activeFocusRole ?? opts.after?.input_focus_role ?? beforeSnap.input_focus_role,
    ...(root.selected_entity_id !== undefined ? { selected_entity_id: root.selected_entity_id } : {}),
    ...(root.scroll_anchor_id !== undefined ? { scroll_anchor_id: root.scroll_anchor_id } : {}),
    ...(isObj(root.dirty_inputs) ? { dirty_inputs: JSON.parse(JSON.stringify(root.dirty_inputs)) } : {}),
    ...(isObj(root.step_data) ? { step_data: JSON.parse(JSON.stringify(root.step_data)) } : {}),
  };

  const unverifiableReasons = [...(Array.isArray(opts.evidence?.unverifiable_reasons) ? opts.evidence.unverifiable_reasons : [])];
  let unverifiableChecks = Number(opts.evidence?.unverifiable_checks ?? 0);
  if (settleTimedOut) {
    unverifiableChecks += 1;
    unverifiableReasons.push('ui.settle_timeout');
  }

  const obs = observeUiSequence({
    ...opts,
    roles: Object.keys(rolesAfter).length > 0 ? rolesAfter : (opts.roles ?? {}),
    elements: elementsAfter,
    before: beforeSnap,
    action: isObj(opts.actionMeta) ? opts.actionMeta : { kind: opts.actionName ?? 'collected_action' },
    transition: {
      ...(isObj(opts.transition) ? opts.transition : {}),
      ...(isFinNum(opts.configuredDurationMs ?? root.configuredDurationMs)
        ? { configured_duration_ms: Number(opts.configuredDurationMs ?? root.configuredDurationMs) }
        : {}),
      observed_duration_ms: settleTimedOut ? null : observedDurationMs,
      focus_trace: focusTrace,
    },
    after: afterSnap,
    ...(asyncRequests.length > 0 ? { async_requests: asyncRequests } : {}),
    ...(optimisticOps.length > 0 ? { optimistic_ops: optimisticOps } : {}),
    evidence: {
      unverifiable_checks: unverifiableChecks,
      unverifiable_reasons: unverifiableReasons,
    },
  });

  obs.collector = {
    stages_completed: settleTimedOut ? ['before', 'during'] : ['before', 'during', 'after'],
    listeners_detached: listenersDetached && !listenersAttached,
    settle_timed_out: settleTimedOut,
  };
  return obs;
}

export const collectUiSequence = collectPlaywrightSequence;
