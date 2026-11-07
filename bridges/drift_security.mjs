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

export async function runProjectionChecks(ctx, caseId, payload, checks = {}) {
  ctx._tag(caseId);
  const seen = ctx.reads.get(caseId);
  const proj = ctx._projMap('then');
  for (const [k, exp] of Object.entries(ctx._tt(caseId))) {
    if (checks && typeof checks[k] === 'function') {
      await invokeVerifiedCallback(checks[k], ctx.contractId, caseId, k, exp, payload);
    } else if (isObj(exp) && Array.isArray(exp.allowed_keys)) {
      let targetObj = payload;
      if (k in proj) {
        const rd = readPointer(payload, proj[k]);
        if (!rd.found) throwAssertionError(`${ctx.contractId}.${caseId}: missing projected path "${proj[k]}" for then.${k}`);
        targetObj = rd.value;
      } else if (isObj(payload) && k in payload && isObj(payload[k])) {
        targetObj = payload[k];
      }
      if (!isObj(targetObj)) {
        throwAssertionError(`${ctx.contractId}.${caseId}: expected object for then.${k}.allowed_keys`);
      }
      const allowedSet = new Set(exp.allowed_keys.map(String));
      for (const actKey of Object.keys(targetObj)) {
        if (!allowedSet.has(actKey)) {
          throwAssertionError(`${ctx.contractId}.${caseId}: unexpected key "${actKey}" outside allowed_keys ${JSON.stringify(exp.allowed_keys)}`);
        }
      }
    } else {
      checkProjectedLeaf(ctx.contractId, caseId, k, exp, payload, proj, ctx.mutationOverride, true, 'no check or projection for');
    }
    seen.add(k);
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
