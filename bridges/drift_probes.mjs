// Reusable observable behavioral probes for the DRIFT JavaScript bridge.
import { isFinNum, isObj, isStr, throwAssertionError, valuesEqual } from './drift_checks.mjs';

const DEFAULT_VOLATILE_KEYS = new Set(['request_id', 'timestamp', 'trace_id', 'audit_id']);
const DEFAULT_ALLOWED_SECOND_WRITES = new Set(['AUDIT_LOG', 'audit_log', 'METRICS', 'metrics']);
const FRAME_ENTRY_KEYS = new Set(['writes', 'operations', 'events', 'before', 'after', 'observed']);

export function isFrameMetadataEnvelope(v) {
  if (!isObj(v)) return false;
  const entries = Object.values(v);
  if (!entries.length) return true;
  return entries.every((e) => (typeof e === 'number' && Number.isSafeInteger(e) && e >= 0)
    || (isObj(e) && Object.keys(e).every((k) => FRAME_ENTRY_KEYS.has(k))));
}

export function requiredProbesOf(view, caseId) {
  const cProbes = view?.cases?.[caseId]?.probes;
  const rProbes = view?.requires?.probes;
  const out = new Set();
  for (const src of [cProbes, rProbes]) {
    if (Array.isArray(src)) for (const p of src) if (isStr(p) && p.trim()) out.add(p.trim());
  }
  return [...out];
}

export function hasKeyRecursive(val, fk, isRoot = true, depth = 0) {
  if (depth > 64) {
    throwAssertionError('observation.incomplete: max_depth_exceeded (> 64)');
  }
  if (Array.isArray(val)) {
    return val.some((item) => hasKeyRecursive(item, fk, false, depth + 1));
  }
  if (val !== null && typeof val === 'object') {
    const proto = Object.getPrototypeOf(val);
    if (proto !== null && proto !== Object.prototype) {
      throwAssertionError('observation.incomplete: non_traversable_object');
    }
    if (val._truncated === true || val.__truncated__ === true) {
      throwAssertionError('observation.incomplete: truncated_capture');
    }
  }
  if (!isObj(val)) return false;
  if (Object.hasOwn(val, fk)) {
    if (!isRoot || fk === '_frame' || !isFrameMetadataEnvelope(val._frame)) return true;
    if (fk !== '_frame') return true;
  }
  for (const [k, v] of Object.entries(val)) {
    if (isRoot && k === '_frame' && fk !== '_frame' && isFrameMetadataEnvelope(v)) continue;
    if (hasKeyRecursive(v, fk, false, depth + 1)) return true;
  }
  return false;
}

function unverifiedOrThrow(ctx, caseId, strict, reason, detail) {
  ctx?.reads?.get(caseId)?.clear();
  if (ctx && !(ctx.unobservedCases instanceof Set)) ctx.unobservedCases = new Set();
  ctx?.unobservedCases?.add(caseId);
  if (strict) {
    throwAssertionError(`${ctx.contractId}.${caseId}: ${reason}: ${detail}`);
  }
  return { observed: false, reason };
}

export async function runIdempotencyProbe(ctx, caseId, obs, runProjectionFn) {
  ctx._tag(caseId);
  const pfx = `${ctx.contractId}.${caseId}`;
  const strict = !isObj(obs) || obs.strict !== false;
  if (!isObj(obs)) {
    return unverifiedOrThrow(ctx, caseId, strict, 'idempotency.unobserved', 'collector reported unobserved state');
  }
  const hasState = 'stateAfterFirst' in obs && 'stateAfterSecond' in obs
    && obs.stateAfterFirst !== undefined && obs.stateAfterSecond !== undefined;
  const secondWrites = isObj(obs.secondWrites) ? obs.secondWrites : null;
  if (hasState && !valuesEqual(obs.stateAfterFirst, obs.stateAfterSecond)) {
    throwAssertionError(`${pfx}: idempotency.domain_state_mutated: stateAfterFirst and stateAfterSecond differ`);
  }
  if (secondWrites) {
    const allowed2 = new Set(
      Array.isArray(obs.allowedSecondWrites)
        ? obs.allowedSecondWrites.map(String)
        : DEFAULT_ALLOWED_SECOND_WRITES,
    );
    for (const [res, wv] of Object.entries(secondWrites)) {
      const base = res.split('#')[0];
      if (allowed2.has(res) || allowed2.has(base)) continue;
      const count = Array.isArray(wv) ? wv.length : Number(wv);
      if (!Number.isSafeInteger(count) || count < 0 || count > 0) {
        throwAssertionError(`${pfx}: idempotency.duplicate_write on resource "${res}": expected 0 writes on replay, observed ${count}`);
      }
    }
  }
  if (isObj(obs.first) && isObj(obs.second)) {
    const vol = new Set(Array.isArray(obs.volatileKeys) ? obs.volatileKeys.map(String) : DEFAULT_VOLATILE_KEYS);
    for (const k of Object.keys(obs.first)) {
      if (vol.has(k) || k === '_frame') continue;
      if (k in obs.second && !valuesEqual(obs.first[k], obs.second[k])) {
        throwAssertionError(`${pfx}: idempotency.response_diverged on key "${k}"`);
      }
    }
  }
  if (obs.observed === false) {
    return unverifiedOrThrow(ctx, caseId, strict, 'idempotency.unobserved', 'collector reported unobserved state');
  }
  if (!hasState && !secondWrites) {
    return unverifiedOrThrow(ctx, caseId, strict, 'idempotency.unobserved', 'missing stateAfterFirst/stateAfterSecond and secondWrites observations');
  }
  if ('first' in obs && obs.first !== undefined && typeof runProjectionFn === 'function') {
    await runProjectionFn(ctx, caseId, obs.first, isObj(obs.checks) ? obs.checks : {});
  }
  ctx?.reads?.get(caseId)?.add('@probe:idempotency');
  return { observed: true, reason: '' };
}

export function runSeamProbe(ctx, caseId, obs) {
  ctx._tag(caseId);
  const pfx = `${ctx.contractId}.${caseId}`;
  const strict = !isObj(obs) || obs.strict !== false;
  if (!isObj(obs)) {
    return unverifiedOrThrow(ctx, caseId, strict, 'seam.unobserved', 'seam collector is unobserved');
  }
  const hasRetrySpec = 'retryable' in obs || 'maxAttempts' in obs;
  const hasTimeoutSpec = obs.timedOut === true;
  const hasQuerySpec = 'maxQueries' in obs;
  if (hasRetrySpec && Number.isSafeInteger(obs.attempts) && obs.attempts > 0) {
    const att = obs.attempts;
    if (obs.retryable === false && att > 1) {
      throwAssertionError(`${pfx}: seam.non_retryable_retried: expected 1 attempt on terminal fault, observed ${att}`);
    }
    if (obs.retryable === true && att < 2) {
      throwAssertionError(`${pfx}: seam.retry_missing: expected >= 2 attempts on transient fault, observed ${att}`);
    }
    if ('maxAttempts' in obs && (!Number.isSafeInteger(obs.maxAttempts) || att > obs.maxAttempts)) {
      throwAssertionError(`${pfx}: seam.max_attempts_exceeded: observed ${att} > maxAttempts ${obs.maxAttempts}`);
    }
  }
  if (hasTimeoutSpec && Number.isSafeInteger(obs.lateWrites) && obs.lateWrites > 0) {
    throwAssertionError(`${pfx}: seam.timeout_late_write: expected 0 writes after timeout, observed ${obs.lateWrites}`);
  }
  if (hasQuerySpec && Number.isSafeInteger(obs.queries) && Number.isSafeInteger(obs.maxQueries) && obs.queries > obs.maxQueries) {
    throwAssertionError(`${pfx}: seam.query_budget_exceeded: observed ${obs.queries} > maxQueries ${obs.maxQueries}`);
  }
  if (obs.observed === false) {
    return unverifiedOrThrow(ctx, caseId, strict, 'seam.unobserved', 'seam collector is unobserved');
  }
  if (!hasRetrySpec && !hasTimeoutSpec && !hasQuerySpec) {
    return unverifiedOrThrow(ctx, caseId, strict, 'seam.unobserved', 'probe specifies neither retry, timeout, nor query bounds');
  }
  if (hasRetrySpec && (!Number.isSafeInteger(obs.attempts) || obs.attempts <= 0)) {
    return unverifiedOrThrow(ctx, caseId, strict, 'seam.unobserved', 'missing positive attempts count from seam spy');
  }
  if (hasTimeoutSpec) {
    const lw = obs.lateWrites ?? 0;
    if (!Number.isSafeInteger(lw) || lw < 0) {
      return unverifiedOrThrow(ctx, caseId, strict, 'seam.unobserved', 'invalid lateWrites observation');
    }
  }
  if (hasQuerySpec) {
    const q = obs.queries;
    const mq = obs.maxQueries;
    if (!Number.isSafeInteger(q) || q < 0 || !Number.isSafeInteger(mq) || mq < 0) {
      return unverifiedOrThrow(ctx, caseId, strict, 'queries.unobserved', 'missing non-negative queries count from SQL listener');
    }
  }
  ctx?.reads?.get(caseId)?.add('@probe:seam');
  return { observed: true, reason: '' };
}

export function runRollbackProbe(ctx, caseId, obs) {
  ctx._tag(caseId);
  const pfx = `${ctx.contractId}.${caseId}`;
  const strict = !isObj(obs) || obs.strict !== false;
  if (isObj(obs) && 'before' in obs && 'after' in obs && obs.before !== undefined && obs.after !== undefined) {
    const res = isStr(obs.resource) && obs.resource ? obs.resource : 'primary';
    if (!valuesEqual(obs.before, obs.after) && obs.compensated !== true) {
      throwAssertionError(`${pfx}: rollback.dirty_partial_write on "${res}": before and after snapshots differ after downstream failure`);
    }
  }
  if (!isObj(obs) || obs.observed === false || !('before' in obs) || !('after' in obs)
      || obs.before === undefined || obs.after === undefined) {
    return unverifiedOrThrow(ctx, caseId, strict, 'rollback.unobserved', 'missing before/after snapshot on primary resource');
  }
  ctx?.reads?.get(caseId)?.add('@probe:rollback');
  return { observed: true, reason: '' };
}

export function checkBolaVariantPair(pfx, variant) {
  if (!isObj(variant)) return false;
  const b = isObj(variant.bola) ? variant.bola : variant;
  if (!('actor_owner' in b) && !('resource_owner' in b)) return false;
  const actor = isStr(b.actor_owner) ? b.actor_owner.trim() : '';
  const owner = isStr(b.resource_owner) ? b.resource_owner.trim() : '';
  if (!actor || !owner || actor === owner) {
    throwAssertionError(`${pfx}: bola.invalid_fixture: cross-owner probe requires distinct non-empty actor_owner and resource_owner`);
  }
  return true;
}

function containsStringLeaf(val, needle, depth = 0) {
  if (depth > 64) {
    throwAssertionError('observation.incomplete: max_depth_exceeded (> 64)');
  }
  if (isStr(val)) return val.includes(needle);
  if (Array.isArray(val)) return val.some((x) => containsStringLeaf(x, needle, depth + 1));
  if (isObj(val)) {
    if (val._truncated === true || val.__truncated__ === true) {
      throwAssertionError('observation.incomplete: truncated_capture');
    }
    return Object.values(val).some((v) => containsStringLeaf(v, needle, depth + 1));
  }
  return false;
}

export function runLogSinkProbe(ctx, caseId, obs) {
  ctx._tag(caseId);
  const pfx = `${ctx.contractId}.${caseId}`;
  const strict = !isObj(obs) || obs.strict !== false;
  if (!isObj(obs)) {
    return unverifiedOrThrow(ctx, caseId, strict, 'log_sink.unobserved', 'log sink collector is unobserved');
  }
  const rawSecrets = Array.isArray(obs.secretValues) ? obs.secretValues : (Array.isArray(obs.secret_values) ? obs.secret_values : []);
  const secrets = rawSecrets.filter((s) => isStr(s) && s.trim() !== '');
  const hasLogs = Array.isArray(obs.logLines) || isStr(obs.logLines) || Array.isArray(obs.log_lines) || isStr(obs.log_lines);
  const hasPayload = 'payload' in obs && obs.payload !== undefined && obs.payload !== null;
  const logs = obs.logLines ?? obs.log_lines;
  for (const s of secrets) {
    if ((hasLogs && containsStringLeaf(logs, s)) || (hasPayload && containsStringLeaf(obs.payload, s))) {
      throwAssertionError(`${pfx}: log_sink.secret_leaked: secret canary leaked in observed sink`);
    }
  }
  if (obs.observed === false || !secrets.length || (!hasLogs && !hasPayload)) {
    return unverifiedOrThrow(ctx, caseId, strict, 'log_sink.unobserved', 'missing secretValues or observed logLines/payload');
  }
  ctx?.reads?.get(caseId)?.add('@probe:log_sink');
  return { observed: true, reason: '' };
}
