package drift;

import java.io.IOException;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/** The JSON subset DRIFT exchanges: objects, arrays, strings, numbers, booleans, null. */
final class Json {
    private final String s;
    private int i;

    private Json(String s) { this.s = s; }

    static Object read(Path file) throws IOException {
        return parse(decode(Files.readAllBytes(file)));
    }

    static String decode(byte[] b) {
        int skip = 0;
        Charset cs = StandardCharsets.UTF_8;
        if (b.length >= 3 && (b[0] & 0xff) == 0xef && (b[1] & 0xff) == 0xbb && (b[2] & 0xff) == 0xbf) skip = 3;
        else if (b.length >= 2 && (b[0] & 0xff) == 0xff && (b[1] & 0xff) == 0xfe) { skip = 2; cs = StandardCharsets.UTF_16LE; }
        else if (b.length >= 2 && (b[0] & 0xff) == 0xfe && (b[1] & 0xff) == 0xff) { skip = 2; cs = StandardCharsets.UTF_16BE; }
        return new String(b, skip, b.length - skip, cs);
    }

    static Object parse(String text) {
        Json p = new Json(text);
        Object v = p.value();
        p.space();
        if (p.i != p.s.length()) throw p.error("trailing content");
        return v;
    }

    static StringBuilder field(StringBuilder b, String key, Object value) {
        quote(b, key).append(':');
        if (value instanceof List<?> l) {
            b.append('[');
            for (int k = 0; k < l.size(); k++) quote(k == 0 ? b : b.append(','), (String) l.get(k));
            return b.append(']');
        }
        return quote(b, (String) value);
    }

    static StringBuilder quote(StringBuilder b, String v) {
        b.append('"');
        for (char c : v.toCharArray()) {
            switch (c) {
                case '"' -> b.append("\\\"");
                case '\\' -> b.append("\\\\");
                case '\n' -> b.append("\\n");
                case '\r' -> b.append("\\r");
                case '\t' -> b.append("\\t");
                default -> b.append(c < 0x20 ? String.format("\\u%04x", (int) c) : String.valueOf(c));
            }
        }
        return b.append('"');
    }

    private Object value() {
        space();
        if (i >= s.length()) throw error("unexpected end");
        return switch (s.charAt(i)) {
            case '{' -> object();
            case '[' -> array();
            case '"' -> string();
            case 't' -> word("true", Boolean.TRUE);
            case 'f' -> word("false", Boolean.FALSE);
            case 'n' -> word("null", null);
            default -> number();
        };
    }

    private Map<String, Object> object() {
        Map<String, Object> m = new LinkedHashMap<>();
        i++;
        space();
        if (peek('}')) return m;
        do {
            space();
            if (i >= s.length() || s.charAt(i) != '"') throw error("expected a key");
            String k = string();
            space();
            expect(':');
            m.put(k, value());
            space();
        } while (peek(','));
        expect('}');
        return m;
    }

    private List<Object> array() {
        List<Object> l = new ArrayList<>();
        i++;
        space();
        if (peek(']')) return l;
        do {
            l.add(value());
            space();
        } while (peek(','));
        expect(']');
        return l;
    }

    private String string() {
        StringBuilder b = new StringBuilder();
        i++;
        while (i < s.length()) {
            char c = s.charAt(i++);
            if (c == '"') {
                return b.toString();
            }
            if (c != '\\') {
                b.append(c);
                continue;
            }
            if (i >= s.length()) {
                break;
            }
            char e = s.charAt(i++);
            switch (e) {
                case '"', '\\', '/' -> b.append(e);
                case 'b' -> b.append('\b');
                case 'f' -> b.append('\f');
                case 'n' -> b.append('\n');
                case 'r' -> b.append('\r');
                case 't' -> b.append('\t');
                case 'u' -> {
                    if (i + 4 > s.length()) {
                        throw error("short unicode escape");
                    }
                    b.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                    i += 4;
                }
                default -> throw error("bad escape");
            }
        }
        throw error("unterminated string");
    }

    private Object number() {
        int start = i;
        while (i < s.length() && "+-0123456789.eE".indexOf(s.charAt(i)) >= 0) {
            i++;
        }
        String n = s.substring(start, i);
        if (n.isEmpty()) {
            throw error("unexpected character");
        }
        try {
            return isInteger(n) ? (Object) Long.valueOf(n) : (Object) Double.valueOf(n);
        } catch (NumberFormatException e) {
            throw error("bad number " + n);
        }
    }

    private static boolean isInteger(String n) {
        int start = n.charAt(0) == '-' ? 1 : 0;
        if (start == n.length()) return false;
        for (int k = start; k < n.length(); k++) {
            char c = n.charAt(k);
            if (c < '0' || c > '9') return false;
        }
        return true;
    }

    private Object word(String w, Object v) {
        if (!s.startsWith(w, i)) throw error("unexpected word");
        i += w.length();
        return v;
    }

    private void space() {
        while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++;
    }

    private boolean peek(char c) {
        if (i < s.length() && s.charAt(i) == c) { i++; return true; }
        return false;
    }

    private void expect(char c) {
        if (!peek(c)) throw error("expected '" + c + "'");
    }

    private IllegalArgumentException error(String what) {
        return new IllegalArgumentException("JSON at " + i + ": " + what);
    }

    record PointerLookup(boolean found, Object value) {}

    private static boolean isArrayIndexSegment(String seg) {
        if ("0".equals(seg)) return true;
        if (seg.isEmpty() || seg.charAt(0) < '1' || seg.charAt(0) > '9') return false;
        for (int i = 1; i < seg.length(); i++) {
            char c = seg.charAt(i);
            if (c < '0' || c > '9') return false;
        }
        return true;
    }

    private static String unescapePointer(String seg) {
        return seg.indexOf('~') < 0 ? seg : seg.replace("~1", "/").replace("~0", "~");
    }

    static String[] splitResourcePointer(String pointer) {
        if (pointer == null || pointer.isEmpty()) {
            return new String[] {"", pointer == null ? "" : pointer};
        }
        int start = pointer.charAt(0) == '/' ? 1 : 0;
        int col = pointer.indexOf(":/", start);
        if (col > start) {
            String res = pointer.substring(start, col);
            boolean ok = res.charAt(0) != '-' && res.charAt(0) != '.';
            for (int i = 0; ok && i < res.length(); i++) {
                char c = res.charAt(i);
                ok = Character.isLetterOrDigit(c) || c == '-' || c == '_' || c == '.';
            }
            if (ok) {
                return new String[] {res, pointer.substring(col + 1)};
            }
        }
        return new String[] {"", pointer};
    }

    static PointerLookup readJsonPointer(Object target, String rawPointer) {
        if (rawPointer == null) {
            return new PointerLookup(false, null);
        }
        String[] split = splitResourcePointer(rawPointer);
        String res = split[0];
        String pointer = split[1];
        Object cur = (!res.isEmpty() && target instanceof Map<?, ?> m && m.containsKey(res))
                ? m.get(res)
                : target;
        if (pointer.isEmpty()) {
            return new PointerLookup(true, cur);
        }
        if (!pointer.startsWith("/")) {
            return new PointerLookup(false, null);
        }
        String[] rawSegs = pointer.substring(1).split("/", -1);
        for (String rawSeg : rawSegs) {
            String seg = unescapePointer(rawSeg);
            if (cur instanceof List<?> list) {
                if (!isArrayIndexSegment(seg)) {
                    return new PointerLookup(false, null);
                }
                int idx = Integer.parseInt(seg);
                if (idx < 0 || idx >= list.size()) {
                    return new PointerLookup(false, null);
                }
                cur = list.get(idx);
            } else if (cur instanceof Map<?, ?> map) {
                if (!map.containsKey(seg)) {
                    return new PointerLookup(false, null);
                }
                cur = map.get(seg);
            } else {
                return new PointerLookup(false, null);
            }
        }
        return new PointerLookup(true, cur);
    }

    @SuppressWarnings("unchecked")
    static Object cloneJsonValue(Object val) {
        if (val instanceof List<?> list) {
            List<Object> copy = new ArrayList<>(list.size());
            for (Object item : list) copy.add(cloneJsonValue(item));
            return copy;
        }
        if (val instanceof Map<?, ?> map) {
            Map<String, Object> copy = new LinkedHashMap<>(map.size());
            for (Map.Entry<?, ?> e : map.entrySet()) copy.put(String.valueOf(e.getKey()), cloneJsonValue(e.getValue()));
            return copy;
        }
        return val;
    }

    @SuppressWarnings("unchecked")
    static Object writeJsonPointer(Object target, String rawPointer, Object value) {
        String pointer = rawPointer == null ? null : splitResourcePointer(rawPointer)[1];
        if (pointer == null || (!pointer.isEmpty() && !pointer.startsWith("/"))) {
            throw new IllegalArgumentException("invalid RFC 6901 JSON Pointer \"" + rawPointer + "\"");
        }
        if (pointer.isEmpty()) return cloneJsonValue(value);
        String[] rawSegs = pointer.substring(1).split("/", -1);
        String[] segs = new String[rawSegs.length];
        for (int i = 0; i < rawSegs.length; i++) segs[i] = unescapePointer(rawSegs[i]);
        return putAtPointer(target, segs, 0, value);
    }

    @SuppressWarnings("unchecked")
    private static Object putAtPointer(Object cur, String[] segs, int index, Object value) {
        String seg = segs[index];
        boolean isLast = index == segs.length - 1;
        boolean nextIsIdx = !isLast && isArrayIndexSegment(segs[index + 1]);
        if (isArrayIndexSegment(seg) && cur instanceof List<?> list) {
            int arrIdx = Integer.parseInt(seg);
            List<Object> copy = new ArrayList<>(list);
            while (copy.size() <= arrIdx) copy.add(null);
            if (isLast) {
                copy.set(arrIdx, cloneJsonValue(value));
            } else {
                Object existing = copy.get(arrIdx);
                Object child = (existing instanceof Map<?, ?> || existing instanceof List<?>)
                        ? existing : (nextIsIdx ? new ArrayList<>() : new LinkedHashMap<String, Object>());
                copy.set(arrIdx, putAtPointer(child, segs, index + 1, value));
            }
            return copy;
        }
        Map<String, Object> baseObj = new LinkedHashMap<>();
        if (cur instanceof Map<?, ?> map) {
            for (Map.Entry<?, ?> e : map.entrySet()) baseObj.put(String.valueOf(e.getKey()), e.getValue());
        }
        if (isLast) {
            baseObj.put(seg, cloneJsonValue(value));
            return baseObj;
        }
        Object existing = baseObj.get(seg);
        Object child = (existing instanceof Map<?, ?> || existing instanceof List<?>)
                ? existing : (nextIsIdx ? new ArrayList<>() : new LinkedHashMap<String, Object>());
        baseObj.put(seg, putAtPointer(child, segs, index + 1, value));
        return baseObj;
    }

    static boolean isFiniteNumber(Object v) { return v instanceof Number n && Double.isFinite(n.doubleValue()); }

    static boolean valuesEqual(Object a, Object b) {
        if (a instanceof Number || b instanceof Number) {
            if (!isFiniteNumber(a) || !isFiniteNumber(b)) return false;
            return ((a instanceof Long || a instanceof Integer) && (b instanceof Long || b instanceof Integer))
                    ? ((Number) a).longValue() == ((Number) b).longValue()
                    : Math.abs(((Number) a).doubleValue() - ((Number) b).doubleValue()) <= 1e-9;
        }
        if (a == b) return true;
        if (a == null || b == null) return false;
        if (a instanceof List<?> la && b instanceof List<?> lb) {
            if (la.size() != lb.size()) return false;
            for (int i = 0; i < la.size(); i++) if (!valuesEqual(la.get(i), lb.get(i))) return false;
            return true;
        }
        if (a instanceof Map<?, ?> ma && b instanceof Map<?, ?> mb) {
            if (ma.size() != mb.size()) return false;
            for (Map.Entry<?, ?> e : ma.entrySet()) if (!mb.containsKey(e.getKey()) || !valuesEqual(e.getValue(), mb.get(e.getKey()))) return false;
            return true;
        }
        return a.equals(b);
    }

    static boolean isRelationalMap(Object val) {
        if (!(val instanceof Map<?, ?> m) || m.isEmpty()) return false;
        for (Object k : m.keySet()) if (!(k instanceof String s) || !List.of("min", "max", "min_len", "max_len", "non_empty", "le_field", "ge_field", "eq_field", "in", "not_in", "sum_fields", "contains", "prefix", "suffix", "allowed_keys", "forbid_keys", "monotonic", "sum_total", "step_max_delta", "approx", "abs_tol", "rel_tol", "balance_fields", "unit", "unit_conversion").contains(s)) return false;
        return true;
    }

    static Map<String, Object> tightenThenMapBySumResiduals(Map<String, Object> whenMap, Map<String, Object> rawThen, Map<String, String> wp, Map<String, String> tp) {
        return ExecutionContext.tightenThenMapBySumResiduals(whenMap, rawThen, wp, tp);
    }

    static void checkNumericAndTuningClauses(
            String pfx, String key, Map<?, ?> exp, Object actual, Object payload, Map<String, String> proj, java.util.Set<String> relKeys) {
        double tol = (isFiniteNumber(exp.get("abs_tol")) && ((Number) exp.get("abs_tol")).doubleValue() >= 0.0)
                ? ((Number) exp.get("abs_tol")).doubleValue() : 1e-9;
        if (exp.containsKey("approx")) {
            double at = exp.containsKey("abs_tol") && isFiniteNumber(exp.get("abs_tol")) ? ((Number) exp.get("abs_tol")).doubleValue() : 0.0;
            double rt = exp.containsKey("rel_tol") && isFiniteNumber(exp.get("rel_tol")) ? ((Number) exp.get("rel_tol")).doubleValue() : 0.0;
            if (!isFiniteNumber(actual) || !isFiniteNumber(exp.get("approx"))
                    || (!exp.containsKey("abs_tol") && !exp.containsKey("rel_tol")) || at < 0.0 || rt < 0.0) {
                throw new AssertionError(pfx + ": invalid approx on then." + key);
            }
            double ap = ((Number) exp.get("approx")).doubleValue();
            double rad = at + rt * Math.abs(ap);
            if (!Double.isFinite(rad) || Math.abs(((Number) actual).doubleValue() - ap) > rad) {
                throw new AssertionError(pfx + ": expected then." + key + " approx " + ap + " (+/- " + rad + "), got " + actual);
            }
        }
        if (exp.containsKey("balance_fields")) {
            if (!(exp.get("balance_fields") instanceof Map<?, ?> bf)) {
                throw new AssertionError(pfx + ": invalid balance_fields on then." + key);
            }
            double sum = 0.0;
            for (String side : new String[] {"add", "sub"}) {
                double sgn = "add".equals(side) ? 1.0 : -1.0;
                if (bf.get(side) instanceof List<?> refs) {
                    for (Object ref : refs) {
                        PointerLookup pr = DriftViewChecks.resolvePeer(payload, proj, ref);
                        if (!pr.found() || !isFiniteNumber(pr.value())) {
                            throw new AssertionError(pfx + ": missing numeric peer \"" + ref + "\" for then." + key + ".balance_fields");
                        }
                        sum += sgn * ((Number) pr.value()).doubleValue();
                    }
                }
            }
            if (!isFiniteNumber(actual) || Math.abs(((Number) actual).doubleValue() - sum) > tol) {
                throw new AssertionError(pfx + ": expected then." + key + " == balance (" + sum + "), got " + actual);
            }
        }
        if ((exp.containsKey("monotonic") || exp.containsKey("step_max_delta") || exp.containsKey("sum_total"))
                && actual instanceof List<?> seqList && (exp.containsKey("min") || exp.containsKey("max"))) {
            for (Object v : seqList) {
                if (!isFiniteNumber(v)
                        || (exp.containsKey("min") && ((Number) v).doubleValue() + tol < ((Number) exp.get("min")).doubleValue())
                        || (exp.containsKey("max") && ((Number) v).doubleValue() - tol > ((Number) exp.get("max")).doubleValue())) {
                    throw new AssertionError(pfx + ": sequence element " + v + " outside [min, max] on then." + key);
                }
            }
        }
        if (exp.containsKey("monotonic")) {
            String mode = String.valueOf(exp.get("monotonic"));
            if (!(actual instanceof List<?> actList) || actList.isEmpty() || !actList.stream().allMatch(Json::isFiniteNumber)) {
                throw new AssertionError(pfx + ": expected non-empty numeric list for then." + key + ".monotonic");
            }
            for (int i = 1; i < actList.size(); i++) {
                double prev = ((Number) actList.get(i - 1)).doubleValue();
                double cur = ((Number) actList.get(i)).doubleValue();
                boolean ok = switch (mode) {
                    case "non_decreasing" -> prev - tol <= cur;
                    case "strictly_increasing" -> prev + tol < cur;
                    case "non_increasing" -> prev + tol >= cur;
                    case "strictly_decreasing" -> prev - tol > cur;
                    default -> false;
                };
                if (!ok) throw new AssertionError(pfx + ": expected then." + key + ".monotonic=" + mode + ", violated at index " + i);
            }
        }
        if (exp.containsKey("step_max_delta")) {
            if (!isFiniteNumber(exp.get("step_max_delta")) || ((Number) exp.get("step_max_delta")).doubleValue() <= 0.0
                    || !(actual instanceof List<?> actList) || actList.isEmpty() || !actList.stream().allMatch(Json::isFiniteNumber)) {
                throw new AssertionError(pfx + ": invalid sequence or step_max_delta on then." + key);
            }
            double delta = ((Number) exp.get("step_max_delta")).doubleValue();
            for (int i = 1; i < actList.size(); i++) {
                if (Math.abs(((Number) actList.get(i)).doubleValue() - ((Number) actList.get(i - 1)).doubleValue()) > delta + tol) {
                    throw new AssertionError(pfx + ": expected then." + key + ".step_max_delta<=" + delta + ", exceeded at index " + i);
                }
            }
        }
        if (exp.containsKey("sum_total")) {
            if (actual instanceof Map<?, ?> am && !am.isEmpty() && am.keySet().stream().allMatch(relKeys::contains)) {
                throw new AssertionError(pfx + ": literal relational table cannot satisfy then." + key + ".sum_total");
            }
            java.util.Collection<?> vals = actual instanceof List<?> l ? l : (actual instanceof Map<?, ?> m ? m.values() : List.of());
            if (vals.isEmpty() || !vals.stream().allMatch(Json::isFiniteNumber)) {
                throw new AssertionError(pfx + ": expected non-empty numeric list or map for then." + key + ".sum_total");
            }
            double total = vals.stream().mapToDouble(v -> ((Number) v).doubleValue()).sum();
            Object st = exp.get("sum_total");
            if (isFiniteNumber(st)) {
                if (Math.abs(total - ((Number) st).doubleValue()) > tol) throw new AssertionError(pfx + ": sum_total mismatch on then." + key);
            } else if (st instanceof Map<?, ?> stMap) {
                if ((stMap.containsKey("eq") && (!isFiniteNumber(stMap.get("eq")) || Math.abs(total - ((Number) stMap.get("eq")).doubleValue()) > tol))
                        || (stMap.containsKey("min") && (!isFiniteNumber(stMap.get("min")) || total + tol < ((Number) stMap.get("min")).doubleValue()))
                        || (stMap.containsKey("max") && (!isFiniteNumber(stMap.get("max")) || total - tol > ((Number) stMap.get("max")).doubleValue()))) {
                    throw new AssertionError(pfx + ": sum_total outside bounds on then." + key);
                }
            } else {
                throw new AssertionError(pfx + ": invalid sum_total on then." + key);
            }
        }
    }
}
