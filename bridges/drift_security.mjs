// Security probing and pre-projection payload checks for the DRIFT JavaScript bridge (D249).
import {
  checkProjectedLeaf,
  escapePointer,
  invokeVerifiedCallback,
  isObj,
  readPointer,
  throwAssertionError,
  throwError,
  valuesEqual,
} from './drift_checks.mjs';

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
      if (fk in act) {
        throwAssertionError(`${pfx}: forbidden key "${fk}" present on then.${key}`);
      }
    }
  }
}

export function forbiddenWritesOf(view, caseId) {
  const scopeWrites = Array.isArray(view?.scope?.writes) ? view.scope.writes.map(String) : [];
  const caseWrites = view?.cases?.[caseId]?.writes;
  if (!Array.isArray(caseWrites)) return [];
  const allowed = new Set(caseWrites.map(String));
  const allowedBases = new Set(caseWrites.map((w) => String(w).split('#')[0]));
  return scopeWrites.filter((r) => !allowed.has(r) && !allowed.has(r.split('#')[0]) && !allowedBases.has(r));
}

export function verifyCaseFrame(ctx, caseId, frameObs, strict = true) {
  ctx._tag(caseId);
  const forbidden = forbiddenWritesOf(ctx.view, caseId);
  if (!forbidden.length) return;
  const seen = ctx.reads.get(caseId);
  for (const res of forbidden) {
    const baseRes = res.split('#')[0];
    const obs = isObj(frameObs) ? (res in frameObs ? frameObs[res] : (baseRes in frameObs ? frameObs[baseRes] : undefined)) : undefined;
    if (obs === undefined) {
      if (strict) {
        throwAssertionError(`${ctx.contractId}.${caseId}: missing frame observation for forbidden write resource "${res}"`);
      }
      continue;
    }
    let checkedAny = false;
    if (typeof obs === 'number') {
      checkedAny = true;
      if (obs > 0) {
        throwAssertionError(`${ctx.contractId}.${caseId}: frame violation on resource "${res}": expected 0 writes, observed ${obs}`);
      }
    } else if (isObj(obs)) {
      const wCount = typeof obs.writes === 'number'
        ? obs.writes
        : (typeof obs.operations === 'number'
          ? obs.operations
          : (Array.isArray(obs.writes) ? obs.writes.length : (Array.isArray(obs.events) ? obs.events.length : null)));
      if (wCount !== null) {
        checkedAny = true;
        if (wCount > 0) {
          throwAssertionError(`${ctx.contractId}.${caseId}: frame violation on resource "${res}": expected 0 writes, observed ${wCount}`);
        }
      }
      if ('before' in obs && 'after' in obs) {
        checkedAny = true;
        if (!valuesEqual(obs.before, obs.after)) {
          throwAssertionError(`${ctx.contractId}.${caseId}: frame state mutation on resource "${res}": before and after snapshots differ`);
        }
      }
    }
    if (!checkedAny) {
      throwAssertionError(`${ctx.contractId}.${caseId}: frame observation for "${res}" must supply writes/operations/events or before/after snapshots`);
    }
    seen.add(`@frame:${res}`);
  }
}

export async function runProjectionChecks(ctx, caseId, payload, checks = {}) {
  ctx._tag(caseId);
  const seen = ctx.reads.get(caseId);
  const proj = ctx._projMap('then');
  for (const [k, exp] of Object.entries(ctx._tt(caseId))) {
    if (checks && typeof checks[k] === 'function') {
      await invokeVerifiedCallback(checks[k], ctx.contractId, caseId, k, exp, payload);
    } else if (isObj(exp) && (Array.isArray(exp.allowed_keys) || 'forbid_keys' in exp)) {
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
      if (Array.isArray(exp.allowed_keys)) {
        const allowedSet = new Set(exp.allowed_keys.map(String));
        for (const actKey of Object.keys(targetObj)) {
          if (!allowedSet.has(actKey)) {
            throwAssertionError(`${ctx.contractId}.${caseId}: unexpected key "${actKey}" outside allowed_keys ${JSON.stringify(exp.allowed_keys)}`);
          }
        }
      }
      if ('forbid_keys' in exp) {
        if (Array.isArray(exp.forbid_keys)) {
          for (const fk of exp.forbid_keys.map(String)) {
            if (Object.hasOwn(targetObj, fk)) {
              throwAssertionError(`${ctx.contractId}.${caseId}: forbidden key "${fk}" present on then.${k}`);
            }
          }
        } else if (!Object.hasOwn(targetObj, String(exp.forbid_keys))) {
          throwAssertionError(`${ctx.contractId}.${caseId}: drop-forbid-key mutant killed on then.${k}.forbid_keys`);
        }
      }
    } else {
      checkProjectedLeaf(ctx.contractId, caseId, k, exp, payload, proj, ctx.mutationOverride, true, 'no check or projection for');
    }
    seen.add(k);
  }
  const frameObs = isObj(checks?.frame) ? checks.frame : (isObj(payload?._frame) ? payload._frame : null);
  if (frameObs) {
    verifyCaseFrame(ctx, caseId, frameObs, true);
  }
}

export async function runAdverseChecks(ctx, caseId, harness, checks = {}) {
  ctx._tag(caseId);
  const variants = harness?.variants;
  const execute = harness?.execute;
  if (!Array.isArray(variants) || !variants.length || typeof execute !== 'function') {
    throwError(`checkAdverse for ${ctx.contractId}.${caseId} requires non-empty variants and an execute callback`);
  }
  const whenTbl = ctx._wt(caseId);
  const whenProj = ctx._projMap('when');
  for (const variant of variants) {
    if (isObj(variant)) {
      for (const [wk, wexp] of Object.entries(whenTbl)) {
        const ptr = whenProj[wk] || `/${escapePointer(wk)}`;
        const rd = readPointer(variant, ptr);
        if (rd.found && !valuesEqual(rd.value, wexp)) {
          throwAssertionError(`${ctx.contractId}.${caseId}.when.${wk} fixture mismatch: expected ${JSON.stringify(wexp)}, got ${JSON.stringify(rd.value)}`);
        }
      }
    }
    const observed = await execute(variant);
    await runProjectionChecks(ctx, caseId, observed, checks);
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
    version: '0.3.3',
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

