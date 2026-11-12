package drift;

import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Reusable observable behavioral probes for the DRIFT JUnit bridge. */
final class DriftProbes {
    private static final Set<String> DEFAULT_VOLATILE_KEYS = Set.of("request_id", "timestamp", "trace_id", "audit_id");
    private static final Set<String> DEFAULT_ALLOWED_SECOND_WRITES = Set.of("AUDIT_LOG", "audit_log", "METRICS", "metrics");

    private DriftProbes() {}

    static boolean hasKeyRecursive(Object val, String fk, boolean isRoot) {
        if (val instanceof List<?> list) {
            for (Object item : list) if (hasKeyRecursive(item, fk, false)) return true;
            return false;
        }
        if (!(val instanceof Map<?, ?> map)) return false;
        for (Map.Entry<?, ?> e : map.entrySet()) {
            String k = String.valueOf(e.getKey());
            if (fk.equals(k)) return true;
            if (isRoot && "_frame".equals(k) && !"_frame".equals(fk) && e.getValue() instanceof Map<?, ?>) continue;
            if (hasKeyRecursive(e.getValue(), fk, false)) return true;
        }
        return false;
    }

    private static Long asNonNegInt(Object v) {
        if (!Json.isFiniteNumber(v)) return null;
        double d = ((Number) v).doubleValue();
        return (d < 0.0 || d != Math.rint(d) || d > 9007199254740991.0) ? null : ((Number) v).longValue();
    }

    private static boolean unverifiedOrThrow(Drift.Case c, boolean strict, String reason, String detail) {
        Drift.unmarkCase(c.contract(), c.id());
        if (strict) throw new AssertionError(c.contract() + "." + c.id() + ": " + reason + ": " + detail);
        return false;
    }

    @SuppressWarnings("unchecked")
    static boolean checkIdempotency(Drift.Case c, Map<String, Object> obs) {
        String pfx = c.contract() + "." + c.id();
        boolean strict = obs == null || !Boolean.FALSE.equals(obs.get("strict"));
        if (obs == null || Boolean.FALSE.equals(obs.get("observed"))) {
            return unverifiedOrThrow(c, strict, "idempotency.unobserved", "collector reported unobserved state");
        }
        Object s1 = obs.containsKey("stateAfterFirst") ? obs.get("stateAfterFirst") : obs.get("state_after_first");
        Object s2 = obs.containsKey("stateAfterSecond") ? obs.get("stateAfterSecond") : obs.get("state_after_second");
        boolean hasState = s1 != null && s2 != null;
        Object swRaw = obs.containsKey("secondWrites") ? obs.get("secondWrites") : obs.get("second_writes");
        Map<?, ?> swMap = swRaw instanceof Map<?, ?> m ? m : null;
        if (!hasState && swMap == null) return unverifiedOrThrow(c, strict, "idempotency.unobserved", "missing state snapshots and secondWrites observations");
        if (obs.get("first") != null) c.checkProjection(obs.get("first"), Map.of());
        if (hasState && !Json.valuesEqual(s1, s2)) throw new AssertionError(pfx + ": idempotency.domain_state_mutated: stateAfterFirst and stateAfterSecond differ");
        if (swMap != null) {
            for (Map.Entry<?, ?> e : swMap.entrySet()) {
                String res = String.valueOf(e.getKey());
                int h = res.indexOf('#');
                String base = h >= 0 ? res.substring(0, h) : res;
                if (DEFAULT_ALLOWED_SECOND_WRITES.contains(res) || DEFAULT_ALLOWED_SECOND_WRITES.contains(base)) continue;
                Object wv = e.getValue();
                long cnt = wv instanceof Collection<?> col ? col.size() : (asNonNegInt(wv) != null ? asNonNegInt(wv) : -1L);
                if (cnt != 0L) throw new AssertionError(pfx + ": idempotency.duplicate_write on resource \"" + res + "\": expected 0 writes on replay, observed " + cnt);
            }
        }
        if (obs.get("first") instanceof Map<?, ?> fMap && obs.get("second") instanceof Map<?, ?> sMap) {
            for (Map.Entry<?, ?> e : fMap.entrySet()) {
                String k = String.valueOf(e.getKey());
                if (DEFAULT_VOLATILE_KEYS.contains(k) || "_frame".equals(k)) continue;
                if (sMap.containsKey(k) && !Json.valuesEqual(e.getValue(), sMap.get(k))) {
                    throw new AssertionError(pfx + ": idempotency.response_diverged on key \"" + k + "\"");
                }
            }
        }
        return true;
    }

    static boolean checkSeamProbe(Drift.Case c, Map<String, Object> obs) {
        String pfx = c.contract() + "." + c.id();
        boolean strict = obs == null || !Boolean.FALSE.equals(obs.get("strict"));
        if (obs == null || Boolean.FALSE.equals(obs.get("observed"))) return unverifiedOrThrow(c, strict, "seam.unobserved", "seam collector is unobserved");
        Object maxAttObj = obs.containsKey("maxAttempts") ? obs.get("maxAttempts") : obs.get("max_attempts");
        boolean hasRetry = obs.containsKey("retryable") || maxAttObj != null;
        boolean hasTimeout = Boolean.TRUE.equals(obs.get("timedOut")) || Boolean.TRUE.equals(obs.get("timed_out"));
        Object maxQObj = obs.containsKey("maxQueries") ? obs.get("maxQueries") : obs.get("max_queries");
        if (!hasRetry && !hasTimeout && maxQObj == null) return unverifiedOrThrow(c, strict, "seam.unobserved", "probe specifies neither retry, timeout, nor query bounds");
        if (hasRetry) {
            Long att = asNonNegInt(obs.get("attempts"));
            if (att == null || att <= 0L) return unverifiedOrThrow(c, strict, "seam.unobserved", "missing positive attempts count from seam spy");
            if (Boolean.FALSE.equals(obs.get("retryable")) && att > 1L) throw new AssertionError(pfx + ": seam.non_retryable_retried: expected 1 attempt on terminal fault, observed " + att);
            if (Boolean.TRUE.equals(obs.get("retryable")) && att < 2L) throw new AssertionError(pfx + ": seam.retry_missing: expected >= 2 attempts on transient fault, observed " + att);
            if (maxAttObj != null) {
                Long ma = asNonNegInt(maxAttObj);
                if (ma == null || att > ma) throw new AssertionError(pfx + ": seam.max_attempts_exceeded: observed " + att + " > maxAttempts " + maxAttObj);
            }
        }
        if (hasTimeout) {
            Long lw = asNonNegInt(obs.containsKey("lateWrites") ? obs.get("lateWrites") : obs.getOrDefault("late_writes", 0));
            if (lw == null) return unverifiedOrThrow(c, strict, "seam.unobserved", "invalid lateWrites observation");
            if (lw > 0L) throw new AssertionError(pfx + ": seam.timeout_late_write: expected 0 writes after timeout, observed " + lw);
        }
        if (maxQObj != null) {
            Long q = asNonNegInt(obs.get("queries")), mq = asNonNegInt(maxQObj);
            if (q == null || mq == null) return unverifiedOrThrow(c, strict, "queries.unobserved", "missing non-negative queries count from SQL listener");
            if (q > mq) throw new AssertionError(pfx + ": seam.query_budget_exceeded: observed " + q + " > maxQueries " + mq);
        }
        return true;
    }

    static boolean checkRollback(Drift.Case c, Map<String, Object> obs) {
        String pfx = c.contract() + "." + c.id();
        boolean strict = obs == null || !Boolean.FALSE.equals(obs.get("strict"));
        if (obs == null || Boolean.FALSE.equals(obs.get("observed")) || obs.get("before") == null || obs.get("after") == null) {
            return unverifiedOrThrow(c, strict, "rollback.unobserved", "missing before/after snapshot on primary resource");
        }
        String res = obs.get("resource") instanceof String s && !s.isBlank() ? s : "primary";
        if (!Json.valuesEqual(obs.get("before"), obs.get("after")) && !Boolean.TRUE.equals(obs.get("compensated"))) {
            throw new AssertionError(pfx + ": rollback.dirty_partial_write on \"" + res + "\": before and after snapshots differ after downstream failure");
        }
        return true;
    }

    static boolean checkBolaVariantPair(String pfx, Object variant) {
        if (!(variant instanceof Map<?, ?> vm)) return false;
        Map<?, ?> b = vm.get("bola") instanceof Map<?, ?> sub ? sub : vm;
        if (!b.containsKey("actor_owner") && !b.containsKey("resource_owner")) return false;
        String actor = b.get("actor_owner") instanceof String s ? s.trim() : "", owner = b.get("resource_owner") instanceof String s ? s.trim() : "";
        if (!actor.isEmpty() && !owner.isEmpty() && !actor.equals(owner)) return true;
        throw new AssertionError(pfx + ": bola.invalid_fixture: cross-owner probe requires distinct non-empty actor_owner and resource_owner");
    }

    private static boolean containsStrLeaf(Object val, String needle) {
        if (val instanceof String s) return s.contains(needle);
        if (val instanceof Collection<?> col) { for (Object x : col) if (containsStrLeaf(x, needle)) return true; return false; }
        if (val instanceof Map<?, ?> map) { for (Object v : map.values()) if (containsStrLeaf(v, needle)) return true; }
        return false;
    }

    static boolean checkLogSink(Drift.Case c, Map<String, Object> obs) {
        String pfx = c.contract() + "." + c.id();
        boolean strict = obs == null || !Boolean.FALSE.equals(obs.get("strict"));
        if (obs == null || Boolean.FALSE.equals(obs.get("observed"))) return unverifiedOrThrow(c, strict, "log_sink.unobserved", "log sink collector is unobserved");
        List<?> secList = (obs.containsKey("secretValues") ? obs.get("secretValues") : obs.get("secret_values")) instanceof List<?> l ? l : List.of();
        Object logs = obs.containsKey("logLines") ? obs.get("logLines") : obs.get("log_lines");
        boolean hasLogs = logs instanceof String || logs instanceof Collection<?>, hasPayload = obs.get("payload") != null;
        if (secList.isEmpty() || (!hasLogs && !hasPayload)) return unverifiedOrThrow(c, strict, "log_sink.unobserved", "missing secretValues or observed logLines/payload");
        for (Object item : secList) {
            if (item instanceof String s && !s.isBlank() && ((hasLogs && containsStrLeaf(logs, s)) || (hasPayload && containsStrLeaf(obs.get("payload"), s)))) {
                throw new AssertionError(pfx + ": log_sink.secret_leaked: secret canary leaked in observed sink");
            }
        }
        return true;
    }
}
