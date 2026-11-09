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

const isStr = (v) => typeof v === 'string';
const throwError = (msg) => { throw new Error(msg); };

function parseClosedJsObjectKeys(expr) {
  const s = expr.trim();
  if (!s.startsWith('{') || !s.endsWith('}')) return null;
  const body = s.slice(1, -1).trim();
  if (!body) return [];
  const entries = [];
  let start = 0, depth = 0, inQ = '';
  for (let i = 0; i < body.length; i += 1) {
    const ch = body[i];
    if (inQ) {
      if (ch === '\\') i += 1;
      else if (ch === inQ) inQ = '';
    } else if (ch === "'" || ch === '"' || ch === '`') inQ = ch;
    else if (ch === '{' || ch === '[' || ch === '(') depth += 1;
    else if (ch === '}' || ch === ']' || ch === ')') depth -= 1;
    else if (ch === ',' && depth === 0) {
      entries.push(body.slice(start, i).trim());
      start = i + 1;
    }
  }
  entries.push(body.slice(start).trim());
  const keys = [];
  for (const e of entries) {
    if (!e) continue;
    if (e.startsWith('...') || e.startsWith('[')) return null;
    const m = /^(?:(['"])([^'"]+)\1|([A-Za-z_$][A-Za-z0-9_$]*))\s*:/u.exec(e);
    if (!m) return null;
    keys.push(m[2] || m[3]);
  }
  return keys;
}

function collectCaseKeyPolicy(thenTbl, projTbl) {
  const allowed = new Set(), forbidden = new Set(), peers = new Set();
  let hasClosedAllowed = false;
  for (const exp of Object.values(thenTbl)) {
    if (!isObj(exp)) continue;
    if (Array.isArray(exp.allowed_keys)) {
      hasClosedAllowed = true;
      for (const ak of exp.allowed_keys) allowed.add(String(ak));
    }
    if (Array.isArray(exp.forbid_keys)) {
      for (const fk of exp.forbid_keys) forbidden.add(String(fk));
    } else if (isStr(exp.forbid_keys)) {
      forbidden.add(exp.forbid_keys);
    }
    for (const pk of ['le_field', 'ge_field', 'eq_field']) {
      if (isStr(exp[pk])) peers.add(exp[pk].replace(/^\//u, ''));
    }
    if (Array.isArray(exp.sum_fields)) {
      for (const sf of exp.sum_fields) if (isStr(sf)) peers.add(sf.replace(/^\//u, ''));
    }
    if (isObj(exp.balance_fields)) {
      for (const side of ['add', 'sub']) {
        if (Array.isArray(exp.balance_fields[side])) {
          for (const bf of exp.balance_fields[side]) if (isStr(bf)) peers.add(bf.replace(/^\//u, ''));
        }
      }
    }
  }
  if (hasClosedAllowed) {
    for (const k of Object.keys(thenTbl)) allowed.add(k);
    for (const k of Object.keys(projTbl)) allowed.add(k);
    for (const k of peers) allowed.add(k);
  }
  return { hasClosedAllowed, allowed, forbidden, peers };
}

export function runPrecheckTestLiterals(testFiles, resDir, area, fs, path) {
  const views = new Map(), known = new Set();
  for (const dir of [resDir, path.join(area, '.drift', 'upstream')]) {
    if (fs.existsSync(dir)) {
      for (const fn of fs.readdirSync(dir).filter((f) => f.endsWith('.json'))) {
        try {
          const v = JSON.parse(fs.readFileSync(path.join(dir, fn), 'utf8'));
          const cid = v?.id || path.basename(fn, '.json');
          if (!views.has(cid)) views.set(cid, v);
          known.add(cid);
        } catch {}
      }
    }
  }
  const cDir = path.join(area, '.drift', 'contracts');
  if (fs.existsSync(cDir)) {
    for (const fn of fs.readdirSync(cDir).filter((f) => f.endsWith('.toml'))) known.add(path.basename(fn, '.toml'));
  }
  const findings = [], advisory = [];
  let unverified = 0;
  for (const rel of Array.isArray(testFiles) ? testFiles : []) {
    const full = path.isAbsolute(rel) ? rel : path.join(area, rel);
    if (!fs.existsSync(full)) continue;
    const src = fs.readFileSync(full, 'utf8').replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gmu, '');
    const runRx = /\brunDriftCase\s*\(/gu;
    let rm;
    while ((rm = runRx.exec(src)) !== null) {
      const startIdx = rm.index + rm[0].length;
      let depth = 1, i = startIdx, inQ = '';
      while (i < src.length && depth > 0) {
        const ch = src[i];
        if (inQ) { if (ch === '\\') i += 1; else if (ch === inQ) inQ = ''; }
        else if (ch === "'" || ch === '"' || ch === '`') inQ = ch;
        else if (ch === '(') depth += 1;
        else if (ch === ')') depth -= 1;
        i += 1;
      }
      const callBody = src.slice(startIdx, Math.max(startIdx, i - 1)).trim();
      let cid = '', casesRaw = '';
      if (callBody.startsWith('{')) {
        const cm = /\bcontract\s*:\s*(?:(['"])([^'"]+)\1|([^,\s}]+))/u.exec(callBody);
        if (!cm || !cm[2]) { unverified += 1; continue; }
        cid = cm[2];
        const csm = /\bcases\s*:\s*(\[[^\]]*\]|[^,\s}]+)/u.exec(callBody);
        casesRaw = csm ? csm[1].trim() : '';
      } else {
        const cm = /^(?:(['"])([^'"]+)\1|([^,\s)]+))\s*,\s*(?:(['"])[^'"]*\4|[^,]+)\s*,\s*(\[[^\]]*\]|[^,)]+)/u.exec(callBody);
        if (!cm || !cm[2]) { unverified += 1; continue; }
        cid = cm[2];
        casesRaw = (cm[5] || '').trim();
      }
      if (!known.has(cid)) {
        findings.push({ code: 'test.unknown_contract', file: rel, contract: cid, message: `unknown contract "${cid}"` });
        continue;
      }
      const view = views.get(cid);
      if (!isObj(view) || !isObj(view.cases)) { unverified += 1; continue; }
      if (casesRaw.startsWith('[') && casesRaw.endsWith(']')) {
        const inner = casesRaw.slice(1, -1).trim();
        if (inner) {
          for (const part of inner.split(',').map((x) => x.trim()).filter(Boolean)) {
            const lm = /^(['"])([^'"]+)\1$/u.exec(part);
            if (!lm) { unverified += 1; continue; }
            if (!(lm[2] in view.cases)) findings.push({ code: 'test.unknown_case', file: rel, contract: cid, case: lm[2], message: `contract "${cid}" has no case "${lm[2]}"` });
          }
        }
      } else if (casesRaw) unverified += 1;
      const paramMatch = /(?:async\s*)?(?:\(\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*\)|([A-Za-z_$][A-Za-z0-9_$]*))\s*=>|function\s*(?:[A-Za-z_$][A-Za-z0-9_$]*)?\s*\(\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*\)/u.exec(callBody);
      const ctxParam = paramMatch ? (paramMatch[1] || paramMatch[2] || paramMatch[3] || '') : '';
      if (!ctxParam) { unverified += 1; continue; }
      const escParam = ctxParam.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&');
      const hasOtherCheck = new RegExp(`\\b${escParam}\\s*\\.\\s*(?:expect|then|findThen|checkProjection|checkView|checkBounds|checkProfileBounds|checkAdverse|checkSeamBounds)\\s*\\(`, 'u').test(callBody);
      const checkedByCase = new Map(), dynCases = new Set();
      const chkRx = new RegExp(`\\b${escParam}\\s*\\.\\s*check\\s*\\(`, 'gu');
      let cm2;
      while ((cm2 = chkRx.exec(callBody)) !== null) {
        let p = cm2.index + cm2[0].length, d2 = 1, q2 = '';
        while (p < callBody.length && d2 > 0) {
          const c = callBody[p];
          if (q2) { if (c === '\\') p += 1; else if (c === q2) q2 = ''; }
          else if (c === "'" || c === '"' || c === '`') q2 = c;
          else if (c === '(') d2 += 1;
          else if (c === ')') d2 -= 1;
          p += 1;
        }
        const argsStr = callBody.slice(cm2.index + cm2[0].length, Math.max(cm2.index + cm2[0].length, p - 1)).trim();
        const firstComma = argsStr.indexOf(',');
        if (firstComma < 0) { unverified += 1; continue; }
        const firstArg = argsStr.slice(0, firstComma).trim(), secondArg = argsStr.slice(firstComma + 1).trim();
        const clm = /^(['"])([^'"]+)\1$/u.exec(firstArg);
        if (!clm) { unverified += 1; continue; }
        const caseId = clm[2];
        if (!(caseId in view.cases)) {
          findings.push({ code: 'test.unknown_case', file: rel, contract: cid, case: caseId, message: `contract "${cid}" has no case "${caseId}"` });
          continue;
        }
        const litKeys = parseClosedJsObjectKeys(secondArg);
        if (litKeys === null) { unverified += 1; dynCases.add(caseId); continue; }
        const thenTbl = view.cases[caseId]?.then || {};
        const projTbl = isObj(view.projections?.then) ? view.projections.then : {};
        const pol = collectCaseKeyPolicy(thenTbl, projTbl);
        if (!checkedByCase.has(caseId)) checkedByCase.set(caseId, new Set());
        for (const k of litKeys) {
          if (k === '_frame') continue;
          checkedByCase.get(caseId).add(k);
          if (!(k in thenTbl) && !(k in projTbl) && !pol.peers.has(k)) {
            if (pol.forbidden.has(k) || (pol.hasClosedAllowed && !pol.allowed.has(k))) {
              findings.push({ code: 'test.then_key_mismatch', file: rel, contract: cid, case: caseId, key: k, message: `${cid}.${caseId}: unknown then.${k}` });
            } else {
              advisory.push({ code: 'test.extra_check_key', file: rel, contract: cid, case: caseId, key: k, message: `${cid}.${caseId}: extra key "${k}" in check literal` });
            }
          }
        }
      }
      if (!hasOtherCheck) {
        for (const [caseId, seenKeys] of checkedByCase.entries()) {
          if (dynCases.has(caseId)) continue;
          const thenTbl = view.cases[caseId]?.then || {};
          for (const reqK of Object.keys(thenTbl)) {
            if (!seenKeys.has(reqK)) {
              findings.push({ code: 'test.then_key_mismatch', file: rel, contract: cid, case: caseId, key: reqK, message: `${cid}.${caseId}: missing required then.${reqK}` });
            }
          }
        }
      }
    }
  }
  return { ok: findings.length === 0, findings, advisory_findings: advisory, unverified_static: unverified };
}

function fnv1aHex(str) {
  let h1 = 0x811c9dc5, h2 = 0x811c9dc5;
  for (let i = 0; i < str.length; i += 1) {
    const c = str.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ ((c << 3) | (c >>> 5)), 0x01000193) >>> 0;
  }
  return h1.toString(16).padStart(8, '0') + h2.toString(16).padStart(8, '0');
}

export function ensureExportGeneration(area, cli, ids, tomls, resDir, execFileSync, fs, path) {
  const parts = ['drift.export-generation/1'];
  const addFile = (tag, fp) => {
    try { if (fs.existsSync(fp)) parts.push(`${tag}:${fnv1aHex(fs.readFileSync(fp, 'utf8'))}`); } catch {}
  };
  addFile('cfg', path.join(area, '.drift', 'config.toml'));
  const pDir = path.join(area, '.drift', 'profiles');
  if (fs.existsSync(pDir)) {
    for (const f of fs.readdirSync(pDir).filter((x) => x.endsWith('.toml')).sort()) addFile(`prof:${f}`, path.join(pDir, f));
  }
  for (let i = 0; i < tomls.length; i += 1) addFile(`c:${ids[i]}`, tomls[i]);
  const genId = `gen-${fnv1aHex(parts.join('\n'))}`;
  const genRoot = path.join(area, '.drift-work', 'resolved-gen');
  const genDir = path.join(genRoot, genId);
  const manPath = path.join(genDir, 'manifest.json');
  let warmOk = false;
  if (fs.existsSync(manPath)) {
    try {
      const man = JSON.parse(fs.readFileSync(manPath, 'utf8'));
      if (man?.generation === genId && isObj(man.files)) {
        warmOk = ids.every((id) => {
          const gf = path.join(genDir, `${id}.json`);
          return fs.existsSync(gf) && fnv1aHex(fs.readFileSync(gf, 'utf8')) === man.files[id];
        });
      }
    } catch { warmOk = false; }
  }
  if (!warmOk) {
    fs.mkdirSync(genRoot, { recursive: true });
    const tmpDir = path.join(genRoot, `.tmp-${process.pid}-${Date.now()}`);
    fs.mkdirSync(tmpDir, { recursive: true });
    try {
      execFileSync(cli, ['show', ...tomls, '--out', tmpDir], { cwd: area, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
      const files = {};
      for (const id of ids) {
        const tf = path.join(tmpDir, `${id}.json`);
        if (fs.existsSync(tf)) files[id] = fnv1aHex(fs.readFileSync(tf, 'utf8'));
      }
      fs.writeFileSync(path.join(tmpDir, 'manifest.json'), JSON.stringify({ schema: 'drift.export-generation/1', generation: genId, files }) + '\n', 'utf8');
      try {
        if (fs.existsSync(genDir)) fs.rmSync(genDir, { recursive: true, force: true });
        fs.renameSync(tmpDir, genDir);
      } catch {
        fs.rmSync(tmpDir, { recursive: true, force: true });
      }
    } catch (e) {
      fs.rmSync(tmpDir, { recursive: true, force: true });
      const errMsg = String(e?.stderr || e?.stdout || e?.message || '').trim();
      throwError(errMsg || 'drift show failed');
    }
  }
  for (const id of ids) {
    const gf = path.join(genDir, `${id}.json`), rf = path.join(resDir, `${id}.json`);
    if (fs.existsSync(gf)) fs.copyFileSync(gf, rf);
  }
  return genDir;
}
