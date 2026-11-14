// Security probing and pre-projection payload checks for the DRIFT JavaScript bridge.
import {
  applyMutation,
  checkProjectedLeaf,
  checkRelationalLeaf,
  escapePointer,
  evalCompiledPlanCase,
  invokeVerifiedCallback,
  isAssertErr,
  isObj,
  isStr,
  readPointer,
  throwAssertionError,
  throwError,
  unwrap03Eq,
  valuesEqual,
} from './drift_checks.mjs';
import {
  checkBolaVariantPair,
  hasKeyRecursive,
  isFrameMetadataEnvelope,
  requiredProbesOf,
  runIdempotencyProbe,
  runLogSinkProbe,
  runRollbackProbe,
  runSeamProbe,
} from './drift_probes.mjs';

export { hasKeyRecursive, isFrameMetadataEnvelope, requiredProbesOf, runIdempotencyProbe, runLogSinkProbe, runRollbackProbe, runSeamProbe };

export function checkNegativeLeaf(pfx, key, exp, act, mutationOverride) {
  if ('not_in' in exp) {
    if (act === null || act === undefined) {
      throwAssertionError(`${pfx}: expected non-null value for then.${key}.not_in`);
    }
    if (Array.isArray(exp.not_in)) {
      if (exp.not_in.some((x) => valuesEqual(act, x))) {
        throwAssertionError(`${pfx}: forbidden value ${JSON.stringify(act)} in then.${key}.not_in ${JSON.stringify(exp.not_in)}`);
      }
    } else if (!valuesEqual(act, exp.not_in)) {
      throwAssertionError(`${pfx}: pick-forbidden-value mutant on then.${key}.not_in killed (got ${JSON.stringify(act)})`);
    }
  }
  if ('forbid_keys' in exp) {
    if (!isObj(act) || !Array.isArray(exp.forbid_keys)) {
      throwAssertionError(`${pfx}: expected object for then.${key}.forbid_keys`);
    }
    if (mutationOverride && typeof mutationOverride.path === 'string' && mutationOverride.path.endsWith(`/${escapePointer(key)}/forbid_keys`)) {
      throwAssertionError(`${pfx}: drop-forbid-key mutant killed on then.${key}.forbid_keys`);
    }
    for (const fk of exp.forbid_keys.map(String)) {
      if (hasKeyRecursive(act, fk, true)) {
        throwAssertionError(`${pfx}: forbidden key "${fk}" present on then.${key}`);
      }
    }
  }
}

function allowedWriteSetsOf(view, caseId) {
  const scopeWrites = Array.isArray(view?.scope?.writes) ? view.scope.writes.map(String) : [];
  const caseWrites = view?.cases?.[caseId]?.writes;
  const rawAllowed = Array.isArray(caseWrites) ? caseWrites.map(String) : scopeWrites;
  const allowed = new Set(rawAllowed);
  const allowedBases = new Set(rawAllowed.map((w) => w.split('#')[0]));
  return [allowed, allowedBases];
}

function isWriteResourceAllowed(res, allowed, allowedBases) {
  const base = res.split('#')[0];
  return allowed.has(res) || allowed.has(base) || (!res.includes('#') && allowedBases.has(res));
}

export function forbiddenWritesOf(view, caseId) {
  const scopeWrites = Array.isArray(view?.scope?.writes) ? view.scope.writes.map(String) : [];
  const caseWrites = view?.cases?.[caseId]?.writes;
  if (!Array.isArray(caseWrites)) return [];
  const [allowed, allowedBases] = allowedWriteSetsOf(view, caseId);
  return scopeWrites.filter((r) => !isWriteResourceAllowed(r, allowed, allowedBases));
}

function isNonNegSafeInt(v) {
  return typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
}

function verifySingleFrameObs(pfx, res, obs, isAmbient) {
  let checkedAny = false;
  const writeLabel = isAmbient ? `undeclared write on perimeter resource "${res}"` : `frame violation on resource "${res}"`;
  const snapLabel = isAmbient ? `undeclared state mutation on perimeter resource "${res}"` : `frame state mutation on resource "${res}"`;
  if (isNonNegSafeInt(obs)) {
    checkedAny = true;
    if (obs > 0) {
      throwAssertionError(`${pfx}: ${writeLabel}: expected 0 writes, observed ${obs}`);
    }
  } else if (isObj(obs)) {
    let wCount = null;
    for (const wk of ['writes', 'operations', 'events']) {
      if (wk in obs) {
        const wv = obs[wk];
        if (isNonNegSafeInt(wv)) {
          wCount = wv;
          break;
        }
        if (Array.isArray(wv)) {
          wCount = wv.length;
          break;
        }
        throwAssertionError(`${pfx}: invalid frame ${wk} for "${res}": expected non-negative integer, got ${wv}`);
      }
    }
    if (wCount !== null) {
      checkedAny = true;
      if (wCount > 0) {
        throwAssertionError(`${pfx}: ${writeLabel}: expected 0 writes, observed ${wCount}`);
      }
    }
    if ('before' in obs && 'after' in obs) {
      checkedAny = true;
      if (!valuesEqual(obs.before, obs.after)) {
        throwAssertionError(`${pfx}: ${snapLabel}: before and after snapshots differ`);
      }
    }
  }
  if (!checkedAny) {
    throwAssertionError(`${pfx}: frame observation for "${res}" must supply writes/operations/events or before/after snapshots`);
  }
}

export function verifyCaseFrame(ctx, caseId, frameObs, strict = true) {
  ctx._tag(caseId);
  const forbidden = forbiddenWritesOf(ctx.view, caseId);
  const pfx = `${ctx.contractId}.${caseId}`;
  const seen = ctx.reads.get(caseId);
  const checkedKeys = new Set();
  for (const res of forbidden) {
    const baseRes = res.split('#')[0];
    checkedKeys.add(res);
    checkedKeys.add(baseRes);
    const obs = isObj(frameObs) ? (res in frameObs ? frameObs[res] : (baseRes in frameObs ? frameObs[baseRes] : undefined)) : undefined;
    const hasMetrics = isObj(obs) && ('writes' in obs || 'operations' in obs || 'events' in obs || ('before' in obs && 'after' in obs));
    if (hasMetrics) {
      verifySingleFrameObs(pfx, res, obs, false);
    }
    if (obs === undefined || (isObj(obs) && obs.observed === false)) {
      if (ctx && !(ctx.unobservedCases instanceof Set)) ctx.unobservedCases = new Set();
      ctx?.unobservedCases?.add(caseId);
      if (strict) {
        const msg = obs === undefined
          ? `missing frame observation for forbidden write resource "${res}"`
          : `frame.observer_missing for forbidden write resource "${res}"`;
        throwAssertionError(`${pfx}: ${msg}`);
      }
      continue;
    }
    if (!hasMetrics) {
      verifySingleFrameObs(pfx, res, obs, false);
    }
    seen.add(`@frame:${res}`);
  }
  if (isObj(frameObs)) {
    const [allowed, allowedBases] = allowedWriteSetsOf(ctx.view, caseId);
    for (const k of Object.keys(frameObs).sort()) {
      if (checkedKeys.has(k) || isWriteResourceAllowed(k, allowed, allowedBases)) continue;
      const obsK = frameObs[k];
      const hasKMetrics = isObj(obsK) && ('writes' in obsK || 'operations' in obsK || 'events' in obsK || ('before' in obsK && 'after' in obsK));
      if (hasKMetrics) {
        verifySingleFrameObs(pfx, k, obsK, true);
      }
      if (isObj(obsK) && obsK.observed === false) {
        if (strict) {
          throwAssertionError(`${pfx}: frame.observer_missing for perimeter resource "${k}"`);
        }
        continue;
      }
      if (!hasKMetrics) {
        verifySingleFrameObs(pfx, k, obsK, true);
      }
    }
  }
}

export async function runProjectionChecks(ctx, caseId, payload, checks = {}, whenObs = null) {
  ctx._tag(caseId);
  const seen = ctx.reads.get(caseId);
  const hasCallbacks = isObj(checks) && Object.entries(checks).some(([k, v]) => k !== 'frame' && k !== 'strictFrame' && typeof v === 'function');
  const isUiObs = isObj(payload) && (payload.schema === 'drift.ui-observation/1' || isObj(payload.evidence));
  const planCase = !ctx.mutationOverride && !hasCallbacks && whenObs === null && !isUiObs ? ctx.view?.__plan?.cases?.[caseId] : null;
  if (planCase && evalCompiledPlanCase(ctx.contractId, caseId, planCase, payload, seen)) {
    const frameObs = isObj(checks?.frame) ? checks.frame : (isFrameMetadataEnvelope(payload?._frame) ? payload._frame : null);
    if (frameObs) {
      const strictFrame = checks?.strictFrame === true || !Object.values(frameObs).some((v) => isObj(v) && v.observed === false);
      verifyCaseFrame(ctx, caseId, frameObs, strictFrame);
    }
    return;
  }
  const proj = ctx._projMap('then');
  const whenEnv = typeof ctx._whenEnv === 'function' ? ctx._whenEnv(caseId, payload, whenObs) : null;
  for (const [k, exp] of Object.entries(ctx._tt(caseId))) {
    if (checks && typeof checks[k] === 'function') {
      await invokeVerifiedCallback(checks[k], ctx.contractId, caseId, k, unwrap03Eq(exp), payload);
    } else if (isObj(exp) && (Array.isArray(exp.allowed_keys) || 'forbid_keys' in exp || isObj(exp.keys))) {
      const ek = isObj(exp.keys) ? exp.keys : {};
      const allowList = Array.isArray(exp.allowed_keys) ? exp.allowed_keys : (Array.isArray(ek.allow) ? ek.allow : null);
      const forbidVal = 'forbid_keys' in exp ? exp.forbid_keys : ('forbid' in ek ? ek.forbid : undefined);
      let targetObj = payload;
      if (k in proj) {
        const rd = readPointer(payload, proj[k]);
        if (!rd.found) throwAssertionError(`${ctx.contractId}.${caseId}: missing projected path "${proj[k]}" for then.${k}`);
        targetObj = rd.value;
      } else if (isObj(payload) && k in payload && isObj(payload[k])) {
        targetObj = payload[k];
      }
      if (!isObj(targetObj)) {
        throwAssertionError(`${ctx.contractId}.${caseId}: expected object for then.${k}`);
      }
      if (Array.isArray(allowList)) {
        const allowedSet = new Set(allowList.map(String));
        for (const actKey of Object.keys(targetObj)) {
          if (targetObj === payload && actKey === '_frame' && isFrameMetadataEnvelope(targetObj._frame)) continue;
          if (!allowedSet.has(actKey)) {
            throwAssertionError(`${ctx.contractId}.${caseId}: unexpected key "${actKey}" outside allowed_keys ${JSON.stringify(allowList)}`);
          }
        }
      }
      if (forbidVal !== undefined) {
        const isRootTarget = targetObj === payload;
        if (Array.isArray(forbidVal)) {
          for (const fk of forbidVal.map(String)) {
            if (hasKeyRecursive(targetObj, fk, isRootTarget)) {
              throwAssertionError(`${ctx.contractId}.${caseId}: forbidden key "${fk}" present on then.${k}`);
            }
          }
        } else if (!hasKeyRecursive(targetObj, String(forbidVal), isRootTarget)) {
          throwAssertionError(`${ctx.contractId}.${caseId}: drop-forbid-key mutant killed on then.${k}.forbid_keys`);
        }
      }
      checkRelationalLeaf(ctx.contractId, caseId, k, exp, targetObj, payload, proj, ctx.mutationOverride, whenEnv, ctx.view);
    } else {
      checkProjectedLeaf(ctx.contractId, caseId, k, exp, payload, proj, ctx.mutationOverride, true, 'no check or projection for', whenEnv, ctx.view);
    }
    seen.add(k);
  }
  const frameObs = isObj(checks?.frame) ? checks.frame : (isFrameMetadataEnvelope(payload?._frame) ? payload._frame : null);
  if (frameObs) {
    const strictFrame = checks?.strictFrame === true || !Object.values(frameObs).some((v) => isObj(v) && v.observed === false);
    verifyCaseFrame(ctx, caseId, frameObs, strictFrame);
  }
}

export async function runAdverseChecks(ctx, caseId, harness, checks = {}) {
  ctx._tag(caseId);
  const variants = harness?.variants;
  const execute = harness?.execute;
  if (!Array.isArray(variants) || !variants.length || typeof execute !== 'function') {
    throwError(`checkAdverse for ${ctx.contractId}.${caseId} requires non-empty variants and an execute callback`);
  }
  const pfx = `${ctx.contractId}.${caseId}`;
  const whenTbl = ctx._wt(caseId);
  const whenProj = ctx._projMap('when');
  let sawCrossOwner = false;
  for (const variant of variants) {
    if (checkBolaVariantPair(pfx, variant)) {
      sawCrossOwner = true;
    }
    if (isObj(variant)) {
      for (const [wk, rawWexp] of Object.entries(whenTbl)) {
        const wexp = unwrap03Eq(rawWexp);
        const ptr = whenProj[wk] || `/${escapePointer(wk)}`;
        const rd = readPointer(variant, ptr);
        if (rd.found && !isObj(wexp) && !valuesEqual(rd.value, wexp)) {
          throwAssertionError(`${ctx.contractId}.${caseId}.when.${wk} fixture mismatch: expected ${JSON.stringify(wexp)}, got ${JSON.stringify(rd.value)}`);
        }
      }
    }
    const observed = await execute(variant);
    await runProjectionChecks(ctx, caseId, observed, checks, isObj(variant) ? variant : null);
  }
  if ((harness?.requireCrossOwner === true || harness?.bola === true) && !sawCrossOwner) {
    ctx.reads.get(caseId)?.clear();
    if (harness?.strict !== false) {
      throwAssertionError(`${pfx}: bola.unobserved: no cross-owner variant with distinct actor_owner and resource_owner supplied`);
    }
  }
}

export function extractTestOrigin(t) {
  if (!t || typeof t !== 'object') return ['', ''];
  if (isStr(t.filePath) && t.filePath) {
    return [t.filePath, isStr(t.fullName) && t.fullName ? t.fullName : String(t.name ?? '')];
  }
  if (isStr(t.file) && t.file) {
    const tp = Array.isArray(t.titlePath)
      ? t.titlePath.filter((s) => isStr(s) && s && !/\.(?:spec|test|e2e)\.[A-Za-z0-9]+$/u.test(s))
      : [];
    const title = tp.length ? tp.join(' > ') : String(t.title ?? t.name ?? '');
    return [t.file, title];
  }
  if (isObj(t.task) && isStr(t.task.file?.filepath)) {
    return [t.task.file.filepath, String(t.task.name ?? t.name ?? '')];
  }
  if (isStr(t.testPath) && t.testPath) {
    return [t.testPath, String(t.currentTestName ?? t.name ?? '')];
  }
  return ['', ''];
}

export function resolveSeamMutatedThen(curCtx, prodView, idOrRes, resolvedCaseId) {
  const m = curCtx?.mutationOverride;
  if (!m || !isStr(m.path)) return null;
  const prodId = prodView?.id || idOrRes;
  const pfx = `/cases/${escapePointer(m.case)}/seam/${escapePointer(prodId)}#${escapePointer(resolvedCaseId)}/`;
  if (!m.path.startsWith(pfx)) return null;
  const subPath = `/cases/${escapePointer(resolvedCaseId)}/then/${m.path.slice(pfx.length)}`;
  return applyMutation(prodView?.cases?.[resolvedCaseId]?.then || {}, prodId, resolvedCaseId, subPath, m.after, 'then');
}

export async function runSeamBoundsChecks(ctx, caseId, idOrRes, prodCaseOrWhen, checks, base, resolveStubFn, synthesizeVariantsFn) {
  ctx._tag(caseId);
  const [prodView, prodCaseId] = resolveStubFn(idOrRes, prodCaseOrWhen, base);
  const prodId = prodView?.id || idOrRes;
  const variants = synthesizeVariantsFn(prodView, prodCaseId, base);
  const execFn = typeof checks === 'function' ? checks : (isObj(checks) && typeof checks.execute === 'function' ? checks.execute : null);
  if (!execFn) {
    throwError(`checkSeamBounds for ${ctx.contractId}.${caseId} requires an execute function or { execute } object`);
  }
  const projChecks = isObj(checks) ? checks : {};
  for (const variant of variants) {
    try {
      const observed = await execFn(variant);
      await runProjectionChecks(ctx, caseId, observed, projChecks);
    } catch (e) {
      if (isAssertErr(e) && !String(e.message || '').includes('[seam counterexample:')) {
        throwAssertionError(`${ctx.contractId}.${caseId} failed on seam ${prodId}#${prodCaseId} [seam counterexample: ${JSON.stringify(variant)}]: ${e.message}`);
      }
      throw e;
    }
  }
}

export const BRIDGE_CAPABILITIES = Object.freeze([
  'allowed_keys',
  'case_frames',
  'counterexample_replay',
  'forbid_keys',
  'inventory_sidecar',
  'mutants',
  'not_in',
  'predicates',
  'projections',
  'relational_bounds',
  'stubs',
]);

export function bridgeCapabilities() {
  return {
    bridge: 'drift.mjs',
    capabilities: [...BRIDGE_CAPABILITIES],
    runtime_baseline: 'node-24-lts',
    schema: 'drift.bridge-capabilities/1',
    version: '0.7.0',
  };
}

export function requireCapabilities(required) {
  if (!Array.isArray(required)) {
    throwError('bridge.capability_unsupported:invalid');
  }
  for (const cap of required) {
    const k = typeof cap === 'string' ? cap.trim() : '';
    if (!k || !BRIDGE_CAPABILITIES.includes(k)) {
      throwError(`bridge.capability_unsupported:${k}`);
    }
  }
}

export async function replayCounterexamples(ctx, caseId, fixtures, sut, checks = {}) {
  ctx._tag(caseId);
  if (!Array.isArray(fixtures)) {
    throwError('replayCounterexamples requires an array of counterexample fixtures');
  }
  let count = 0;
  for (const fx of fixtures) {
    if (!isObj(fx) || fx.contract !== ctx.contractId || (fx.case && fx.case !== caseId)) continue;
    const whenIn = fx.witness?.when;
    if (!isObj(whenIn)) throwError(`counterexample fixture ${fx.signal_id || ''} missing witness.when`);
    const actual = await sut(whenIn);
    await runProjectionChecks(ctx, caseId, actual, checks);
    count++;
  }
  return count;
}

