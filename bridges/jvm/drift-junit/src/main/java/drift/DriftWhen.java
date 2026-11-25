package drift;

import java.util.*;
import java.util.function.Consumer;

/** Thread-local tracking for {@code when.*} reads, strict-when enforcement, and standalone {@code runCase} (D463). */
final class DriftWhen {
    private static final ThreadLocal<Map<String, Set<String>>> READS = ThreadLocal.withInitial(HashMap::new);
    private static final ThreadLocal<Map<String, Map<String, Object>>> TABLES = ThreadLocal.withInitial(LinkedHashMap::new);
    private static final ThreadLocal<Boolean> CHECKED = new ThreadLocal<>();
    private static final ThreadLocal<Boolean> IN_RUN = new ThreadLocal<>();

    private DriftWhen() {}

    static void clear() {
        READS.get().clear();
        TABLES.get().clear();
        CHECKED.remove();
    }

    static void register(String c, String id, Map<String, Object> when) {
        TABLES.get().put(c + "\0" + id, when);
    }

    static void mark(String c, String id, String key) {
        READS.get().computeIfAbsent(c + "\0" + id, k -> new HashSet<>()).add(key);
    }

    static void markAll(String c, String id, Map<String, Object> when) {
        if (when != null && !when.isEmpty()) READS.get().computeIfAbsent(c + "\0" + id, k -> new HashSet<>()).addAll(when.keySet());
    }

    static List<String> unread(String c, String id, Map<String, Object> when) {
        if (when == null || when.isEmpty()) return List.of();
        Set<String> seen = READS.get().getOrDefault(c + "\0" + id, Set.of());
        List<String> out = new ArrayList<>();
        for (String k : when.keySet()) if (!seen.contains(k)) out.add(k);
        Collections.sort(out);
        return out;
    }

    private static boolean isTrue(String v) {
        if (v == null) return false;
        String s = v.trim();
        return "1".equals(s) || "true".equals(s);
    }

    static boolean isStrict(DriftCase tag) {
        return (tag != null && tag.strictWhen())
                || isTrue(System.getProperty("drift.strictWhen"))
                || isTrue(System.getenv("DRIFT_STRICT_WHEN"));
    }

    static void requireCase(Drift.Case c) {
        List<String> u = unread(c.contract(), c.id(), c.whenRaw());
        if (!u.isEmpty()) throw new AssertionError(c.contract() + "." + c.id() + ": unread when." + String.join(", when.", u));
    }

    private static String firstViolation() {
        for (var e : TABLES.get().entrySet()) {
            int sep = e.getKey().indexOf('\0');
            if (sep <= 0) continue;
            String c = e.getKey().substring(0, sep), id = e.getKey().substring(sep + 1);
            List<String> u = unread(c, id, e.getValue());
            if (!u.isEmpty()) return c + "." + id + ": unread when." + String.join(", when.", u);
        }
        return null;
    }

    static void enforceAfterExecution(DriftCase tag) {
        if (Drift.mutationRun() || !isStrict(tag) || Boolean.TRUE.equals(CHECKED.get())) return;
        CHECKED.set(Boolean.TRUE);
        String msg = firstViolation();
        if (msg != null) throw new AssertionError(msg);
    }

    static boolean listenerFallbackViolated(DriftCase tag) {
        return !Drift.mutationRun() && isStrict(tag) && !Boolean.TRUE.equals(CHECKED.get()) && firstViolation() != null;
    }

    static boolean inRunCase() { return Boolean.TRUE.equals(IN_RUN.get()); }

    static void checkStandalone(Drift.Case c) {
        if (DriftVerify.isStandalone() && !inRunCase() && !DriftVerify.inAdverse() && isStrict(null)) c.requireWhenRead();
    }

    static void runStandaloneCase(String contract, String caseId, String level, Consumer<Drift.Case> action) {
        if (action == null) throw new IllegalArgumentException("action must not be null");
        if (Boolean.TRUE.equals(Drift.inTest()) || Drift.mutationRun()) {
            action.accept(Drift.expect(contract, caseId, level));
            return;
        }
        Drift.resetStandalone();
        IN_RUN.set(Boolean.TRUE);
        Drift.Case c = null;
        String testId = null;
        try {
            c = Drift.expect(contract, caseId, level);
            testId = DriftVerify.activeStandaloneId(caseId);
            action.accept(c);
            if (isStrict(null)) c.requireWhenRead();
        } catch (Throwable err) {
            if (c != null) {
                DriftObservations.clearCase(c.contract(), c.id());
                DriftVerify.emitStandalone(testId, c, false, false);
            }
            throw err;
        } finally {
            IN_RUN.remove();
        }
        DriftVerify.emitStandalone(testId, c, true, false);
    }
}
