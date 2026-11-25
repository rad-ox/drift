package drift;

import java.nio.charset.StandardCharsets;
import java.util.*;

/**
 * Captures bounded {@code drift.observation/1} payloads and measured {@code frame.writes} for
 * schema 0.3 declarative {@code verify}/{@code checkFrame} calls.
 */
final class DriftObservations {
    private static final long MAX_SAFE_INT = (1L << 53) - 1L;
    private static final ThreadLocal<Map<String, String>> PAYLOADS = ThreadLocal.withInitial(LinkedHashMap::new);
    private static final ThreadLocal<Map<String, List<String>>> FRAMES = ThreadLocal.withInitial(LinkedHashMap::new);

    private DriftObservations() {}

    static void clear() {
        PAYLOADS.get().clear();
        FRAMES.get().clear();
    }

    static void clearCase(String contract, String caseId) {
        String key = contract + "\0" + caseId;
        PAYLOADS.get().remove(key);
        FRAMES.get().remove(key);
    }

    static void clearFrame(Drift.Case c) {
        FRAMES.get().remove(c.contract() + "\0" + c.id());
    }

    private static void addNeed(Set<String> n, Object x) {
        if (x instanceof String s && !s.startsWith("when.")) n.add(s.startsWith("then.") ? s.substring(5) : s);
        else if (x instanceof List<?> l) for (Object i : l) addNeed(n, i);
        else if (x instanceof Map<?, ?> m) { addNeed(n, m.get("add")); addNeed(n, m.get("sub")); }
    }

    private static void refs(Set<String> n, Map<?, ?> t) {
        for (Object v : t.values()) if (v instanceof Map<?, ?> m) {
            if (m.get("peer") instanceof Map<?, ?> p) for (String k : new String[] {"eq", "le", "ge", "sum", "balance"}) addNeed(n, p.get(k));
            for (String k : new String[] {"eq_field", "le_field", "ge_field", "sum_fields", "balance_fields"}) addNeed(n, m.get(k));
        }
    }

    static void recordPayload(Drift.Case c, Object pay, Map<String, Object> rawThen, Map<String, String> proj) {
        String key = c.contract() + "\0" + c.id();
        PAYLOADS.get().remove(key);
        if (pay == null || rawThen == null || rawThen.isEmpty() || !Drift.isSchema03(c.contract()) || Drift.mutationRun() || Drift.hasSelfStub(c.contract())) return;
        if (pay instanceof Map<?, ?> pm && ("drift.ui-observation/1".equals(pm.get("schema")) || pm.get("evidence") instanceof Map<?, ?>)) return;
        Set<String> need = new LinkedHashSet<>(rawThen.keySet());
        Map<?, ?> inv = Drift.view(c.contract()).get("invariants") instanceof Map<?, ?> im ? im : Map.of();
        for (Object k : inv.keySet()) if (k instanceof String s) need.add(s);
        refs(need, rawThen);
        refs(need, inv);
        String json = serializeProjected(pay, rawThen.keySet(), need, proj == null ? Map.of() : proj);
        if (json != null) PAYLOADS.get().put(key, json);
    }

    static String serializeProjected(Object pay, Set<String> tt, Set<String> need, Map<String, String> proj) {
        if (pay == null || tt == null || tt.isEmpty()) return null;
        Object out = new LinkedHashMap<String, Object>();
        for (String k : need) {
            boolean req = tt.contains(k);
            String ptr = proj.get(k);
            if (ptr != null) {
                var lk = Json.readJsonPointer(pay, ptr);
                if (lk.found()) out = Json.writeJsonPointer(out, ptr, lk.value());
                else if (req && pay instanceof Map<?, ?> m && m.containsKey(k)) out = Json.writeJsonPointer(out, ptr, m.get(k));
                else if (req) return null;
            } else if (pay instanceof Map<?, ?> m && m.containsKey(k)) {
                out = Json.writeJsonPointer(out, "/" + k.replace("~", "~0").replace("/", "~1"), m.get(k));
            } else if (req) return null;
        }
        return encodeBounded(out);
    }

    private static String encodeBounded(Object v) {
        StringBuilder sb = new StringBuilder();
        if (!writeVal(sb, v, 0)) return null;
        String s = sb.toString();
        return s.getBytes(StandardCharsets.UTF_8).length <= 4096 ? s : null;
    }

    static void recordFrame(Drift.Case c, List<String> observedWrites) {
        String key = c.contract() + "\0" + c.id();
        if (Drift.mutationRun()) return;
        FRAMES.get().put(key, observedWrites == null ? List.of() : List.copyOf(observedWrites));
    }

    static boolean entryWrote(Object obs) {
        if (obs instanceof Number n && Double.isFinite(n.doubleValue())) {
            double d = n.doubleValue();
            if (d >= 0.0 && d == Math.rint(d) && d <= 9007199254740991.0) return n.longValue() > 0L;
        }
        if (obs instanceof Map<?, ?> om) {
            for (String wk : new String[] {"writes", "operations", "events"}) {
                if (!om.containsKey(wk)) continue;
                Object wv = om.get(wk);
                if (wv instanceof Number n && Double.isFinite(n.doubleValue()) && n.longValue() > 0L) return true;
                if (wv instanceof List<?> wl && !wl.isEmpty()) return true;
            }
            if (om.containsKey("before") && om.containsKey("after")
                    && !Json.valuesEqual(om.get("before"), om.get("after"))) {
                return true;
            }
        }
        return false;
    }

    static void appendField(StringBuilder line, String contract, String outcome, List<String> read) {
        if (!"passed".equals(outcome) || read == null || read.isEmpty() || !Drift.isSchema03(contract) || Drift.hasSelfStub(contract)) {
            return;
        }
        Map<String, Object> view = Drift.view(contract);
        Map<String, String> payloads = PAYLOADS.get();
        Map<String, List<String>> frames = FRAMES.get();
        StringBuilder out = new StringBuilder("{");
        boolean any = false;
        for (String cid : read) {
            String key = contract + "\0" + cid;
            String pay = payloads.get(key);
            if (pay == null) continue;
            List<String> fw = frames.get(key);
            if (!DriftUiChecks.forbiddenWritesOf(view, cid).isEmpty() && fw == null) continue;
            if (any) out.append(',');
            any = true;
            Json.quote(out, cid)
                    .append(":{\"schema\":\"drift.observation/1\",\"outcome\":\"returned\",\"payload\":")
                    .append(pay);
            if (fw != null) {
                Json.field(out.append(",\"frame\":{"), "writes", fw).append('}');
            }
            out.append('}');
        }
        if (any) {
            line.append(",\"observations\":").append(out.append('}'));
        }
    }

    static String serialize(Map<String, Object> payload, Set<String> thenKeys) {
        return serializeProjected(payload, thenKeys, thenKeys, Map.of());
    }

    private static boolean validStr(String s, boolean cap) {
        int cp = 0;
        for (int i = 0, n = s.length(); i < n; i++) {
            char c = s.charAt(i);
            if (Character.isHighSurrogate(c)) { if (++i >= n || !Character.isLowSurrogate(s.charAt(i))) return false; }
            else if (Character.isLowSurrogate(c)) return false;
            if (cap && ++cp > 1024) return false;
        }
        return true;
    }

    private static boolean writeVal(StringBuilder b, Object v, int depth) {
        if (depth > 6) return false;
        if (v == null) { b.append("null"); return true; }
        if (v instanceof Boolean bl) { b.append(bl ? "true" : "false"); return true; }
        if (v instanceof Byte || v instanceof Short || v instanceof Integer || v instanceof Long) {
            long n = ((Number) v).longValue();
            if (n < -MAX_SAFE_INT || n > MAX_SAFE_INT) return false;
            b.append(n);
            return true;
        }
        if (v instanceof Float || v instanceof Double) {
            double x = ((Number) v).doubleValue();
            if (!Double.isFinite(x)) return false;
            if (x == 0.0) b.append("0");
            else if (x == Math.rint(x) && x >= -MAX_SAFE_INT && x <= MAX_SAFE_INT) b.append((long) x);
            else b.append(x);
            return true;
        }
        if (v instanceof String s) {
            if (!validStr(s, true)) return false;
            Json.quote(b, s);
            return true;
        }
        if (v instanceof List<?> l) {
            if (l.size() > 64) return false;
            b.append('[');
            for (int i = 0; i < l.size(); i++) {
                if (i > 0) b.append(',');
                if (!writeVal(b, l.get(i), depth + 1)) return false;
            }
            b.append(']');
            return true;
        }
        if (v instanceof Map<?, ?> m) {
            if (m.size() > 64) return false;
            TreeMap<String, Object> sm = new TreeMap<>();
            for (Map.Entry<?, ?> e : m.entrySet()) {
                if (!(e.getKey() instanceof String rk) || !validStr(rk, false)) return false;
                sm.put(rk.startsWith("$") ? "$" + rk : rk, e.getValue());
            }
            b.append('{');
            boolean first = true;
            for (var e : sm.entrySet()) {
                if (!first) b.append(',');
                first = false;
                Json.quote(b, e.getKey()).append(':');
                if (!writeVal(b, e.getValue(), depth + 1)) return false;
            }
            b.append('}');
            return true;
        }
        return false;
    }
}
