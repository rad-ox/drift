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
        for (Object k : m.keySet()) if (!(k instanceof String s) || !List.of("min", "max", "min_len", "max_len", "non_empty", "le_field", "ge_field", "eq_field", "in", "sum_fields", "contains", "prefix", "suffix").contains(s)) return false;
        return true;
    }

    static String canonicalStubRef(Object rawRef, Map<String, String> whenProjections, Map<String, String> thenProjections) {
        if (!(rawRef instanceof String ref) || ref.isBlank()) return "";
        String s = ref.trim();
        if (s.startsWith("/")) return splitResourcePointer(s)[1];
        String p = thenProjections != null && thenProjections.containsKey(s) ? thenProjections.get(s) : (whenProjections != null && whenProjections.containsKey(s) ? whenProjections.get(s) : ("/" + s));
        return splitResourcePointer(p)[1];
    }

    static Number maxNum(Number a, Number b) { return a == null ? b : (b == null || a.doubleValue() >= b.doubleValue() ? a : b); }
    static Number minNum(Number a, Number b) { return a == null ? b : (b == null || a.doubleValue() <= b.doubleValue() ? a : b); }

    static Number roundTightenedNum(Number curLo, Number curHi, double rawVal, boolean isMin) {
        boolean isInt = (curLo instanceof Long || curLo instanceof Integer) || (curHi instanceof Long || curHi instanceof Integer) || Math.abs(rawVal - Math.rint(rawVal)) < 1e-9;
        if (isInt) return Long.valueOf((long) (isMin ? Math.ceil(rawVal - 1e-9) : Math.floor(rawVal + 1e-9)));
        return Double.valueOf(rawVal);
    }

    static Number[] lookupPeerNumBounds(Object ref, Map<String, Object> whenMap, Map<String, Object> thenMap, Map<String, String> whenProjections, Map<String, String> thenProjections) {
        String ck = canonicalStubRef(ref, whenProjections, thenProjections);
        String bare = ref instanceof String rs ? rs.trim().replaceFirst("^/+", "") : "";
        for (int i = 0; i < 2; i++) {
            Map<String, Object> m = i == 0 ? thenMap : (whenMap == null ? Map.of() : whenMap);
            Map<String, String> pm = i == 0 ? thenProjections : whenProjections;
            for (Map.Entry<String, Object> e : m.entrySet()) {
                if (e.getKey().equals(ref) || e.getKey().equals(bare) || canonicalStubRef(e.getKey(), whenProjections, pm).equals(ck)) {
                    if (e.getValue() instanceof Number n) return new Number[]{n, n};
                    if (isRelationalMap(e.getValue()) && e.getValue() instanceof Map<?, ?> rm) {
                        return new Number[]{rm.get("min") instanceof Number n1 ? n1 : null, rm.get("max") instanceof Number n2 ? n2 : null};
                    }
                }
            }
        }
        return new Number[]{null, null};
    }

    static int peerOrderRelation(String ckA, String ckB, Map<String, Object> thenMap, Map<String, String> wp, Map<String, String> tp) {
        if (ckA.isEmpty() || ckB.isEmpty() || ckA.equals(ckB) || thenMap == null) return 0;
        for (var e : thenMap.entrySet()) {
            if (!isRelationalMap(e.getValue()) || !(e.getValue() instanceof Map<?, ?> m)) continue;
            String ck = canonicalStubRef(e.getKey(), wp, tp);
            if (ck.equals(ckA)) {
                if (m.containsKey("eq_field") && canonicalStubRef(m.get("eq_field"), wp, tp).equals(ckB)) return 3;
                if (m.containsKey("le_field") && canonicalStubRef(m.get("le_field"), wp, tp).equals(ckB)) return 1;
                if (m.containsKey("ge_field") && canonicalStubRef(m.get("ge_field"), wp, tp).equals(ckB)) return 2;
            } else if (ck.equals(ckB)) {
                if (m.containsKey("eq_field") && canonicalStubRef(m.get("eq_field"), wp, tp).equals(ckA)) return 3;
                if (m.containsKey("ge_field") && canonicalStubRef(m.get("ge_field"), wp, tp).equals(ckA)) return 1;
                if (m.containsKey("le_field") && canonicalStubRef(m.get("le_field"), wp, tp).equals(ckA)) return 2;
            }
        }
        return 0;
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> tightenThenMapBySumResiduals(Map<String, Object> whenMap, Map<String, Object> rawThen, Map<String, String> wp, Map<String, String> tp) {
        if (rawThen == null || rawThen.isEmpty()) return Map.of();
        boolean anyPeer = false;
        for (Object v : rawThen.values()) {
            if (isRelationalMap(v) && v instanceof Map<?, ?> m
                    && ((m.get("sum_fields") instanceof List<?> sf && sf.size() >= 2)
                    || m.containsKey("le_field") || m.containsKey("ge_field") || m.containsKey("eq_field"))) {
                anyPeer = true;
                break;
            }
        }
        if (!anyPeer) return rawThen;
        Map<String, Object> out = (Map<String, Object>) cloneJsonValue(rawThen);
        for (int pass = 0; pass < 3; pass++) {
            for (var e : out.entrySet()) {
                if (!isRelationalMap(e.getValue()) || !(e.getValue() instanceof Map<?, ?> rawM)) continue;
                Map<String, Object> tv = (Map<String, Object>) rawM;
                String ckTgt = canonicalStubRef(e.getKey(), wp, tp);
                Number loK = tv.get("min") instanceof Number n1 ? n1 : null;
                Number hiK = tv.get("max") instanceof Number n2 ? n2 : null;
                for (String pk : List.of("eq_field", "le_field", "ge_field")) {
                    if (!tv.containsKey(pk)) continue;
                    Number[] pb = lookupPeerNumBounds(tv.get(pk), whenMap, out, wp, tp);
                    if ((pk.equals("eq_field") || pk.equals("ge_field")) && pb[0] != null) loK = maxNum(loK, pb[0]);
                    if ((pk.equals("eq_field") || pk.equals("le_field")) && pb[1] != null) hiK = minNum(hiK, pb[1]);
                }
                for (var pe : out.entrySet()) {
                    if (pe.getKey().equals(e.getKey()) || !isRelationalMap(pe.getValue()) || !(pe.getValue() instanceof Map<?, ?> pm)) continue;
                    Number pLo = pm.get("min") instanceof Number pn1 ? pn1 : null;
                    Number pHi = pm.get("max") instanceof Number pn2 ? pn2 : null;
                    if (pm.containsKey("eq_field") && canonicalStubRef(pm.get("eq_field"), wp, tp).equals(ckTgt)) {
                        if (pLo != null) loK = maxNum(loK, pLo);
                        if (pHi != null) hiK = minNum(hiK, pHi);
                    }
                    if (pm.containsKey("le_field") && canonicalStubRef(pm.get("le_field"), wp, tp).equals(ckTgt) && pLo != null) loK = maxNum(loK, pLo);
                    if (pm.containsKey("ge_field") && canonicalStubRef(pm.get("ge_field"), wp, tp).equals(ckTgt) && pHi != null) hiK = minNum(hiK, pHi);
                }
                for (var se : out.entrySet()) {
                    if (se.getKey().equals(e.getKey()) || !isRelationalMap(se.getValue()) || !(se.getValue() instanceof Map<?, ?> sm)
                            || !(sm.get("sum_fields") instanceof List<?> sfList) || sfList.size() < 2) continue;
                    Number sLo = sm.get("min") instanceof Number sn1 ? sn1 : null, sHi = sm.get("max") instanceof Number sn2 ? sn2 : null;
                    if (sLo == null && sHi == null) continue;
                    Map<String, Integer> mult = new LinkedHashMap<>();
                    Map<String, Object> rep = new LinkedHashMap<>();
                    for (Object sf : sfList) {
                        String ck = canonicalStubRef(sf, wp, tp);
                        if (!ck.isEmpty()) { mult.put(ck, mult.getOrDefault(ck, 0) + 1); rep.putIfAbsent(ck, sf); }
                    }
                    int mk = mult.getOrDefault(ckTgt, 0);
                    if (mk < 1) continue;
                    double remLo = 0.0, remHi = 0.0;
                    boolean allLo = true, allHi = true;
                    for (var me : mult.entrySet()) {
                        if (me.getKey().equals(ckTgt)) continue;
                        Number[] b = lookupPeerNumBounds(rep.get(me.getKey()), whenMap, out, wp, tp);
                        if (b[0] != null) remLo += me.getValue() * b[0].doubleValue(); else allLo = false;
                        if (b[1] != null) remHi += me.getValue() * b[1].doubleValue(); else allHi = false;
                    }
                    for (var pe : mult.entrySet()) {
                        String ckP = pe.getKey();
                        int ord = ckP.equals(ckTgt) ? 0 : peerOrderRelation(ckTgt, ckP, out, wp, tp);
                        if (ord == 0) continue;
                        int mp = pe.getValue();
                        double oLo = 0.0, oHi = 0.0;
                        boolean oAllLo = true, oAllHi = true;
                        for (var qe : mult.entrySet()) {
                            if (qe.getKey().equals(ckTgt) || qe.getKey().equals(ckP)) continue;
                            Number[] b = lookupPeerNumBounds(rep.get(qe.getKey()), whenMap, out, wp, tp);
                            if (b[0] != null) oLo += qe.getValue() * b[0].doubleValue(); else oAllLo = false;
                            if (b[1] != null) oHi += qe.getValue() * b[1].doubleValue(); else oAllHi = false;
                        }
                        if ((ord == 1 || ord == 3) && sHi != null && oAllLo) hiK = minNum(hiK, roundTightenedNum(loK, hiK, (sHi.doubleValue() - oLo) / (mk + mp), false));
                        if ((ord == 2 || ord == 3) && sLo != null && oAllHi) loK = maxNum(loK, roundTightenedNum(loK, hiK, (sLo.doubleValue() - oHi) / (mk + mp), true));
                    }
                    for (var be : out.entrySet()) {
                        if (be.getKey().equals(se.getKey()) || be.getKey().equals(e.getKey()) || !isRelationalMap(be.getValue())
                                || !(be.getValue() instanceof Map<?, ?> bm) || !(bm.get("sum_fields") instanceof List<?> bSf) || bSf.size() < 2) continue;
                        Number bLo = bm.get("min") instanceof Number bn1 ? bn1 : null, bHi = bm.get("max") instanceof Number bn2 ? bn2 : null;
                        if (bLo == null && bHi == null) continue;
                        Map<String, Integer> multB = new LinkedHashMap<>();
                        for (Object sf : bSf) {
                            String ck = canonicalStubRef(sf, wp, tp);
                            if (!ck.isEmpty()) multB.put(ck, multB.getOrDefault(ck, 0) + 1);
                        }
                        if (multB.containsKey(ckTgt)) continue;
                        if (bSf.size() < sfList.size() && multB.entrySet().stream().allMatch(x -> mult.getOrDefault(x.getKey(), 0) >= x.getValue())) {
                            double exLo = 0.0, exHi = 0.0;
                            boolean exAllLo = true, exAllHi = true;
                            for (var me : mult.entrySet()) {
                                int d = me.getKey().equals(ckTgt) ? 0 : (me.getValue() - multB.getOrDefault(me.getKey(), 0));
                                if (d > 0) {
                                    Number[] b = lookupPeerNumBounds(rep.get(me.getKey()), whenMap, out, wp, tp);
                                    if (b[0] != null) exLo += d * b[0].doubleValue(); else exAllLo = false;
                                    if (b[1] != null) exHi += d * b[1].doubleValue(); else exAllHi = false;
                                }
                            }
                            if (bLo != null && exAllLo) { remLo = allLo ? Math.max(remLo, bLo.doubleValue() + exLo) : (bLo.doubleValue() + exLo); allLo = true; }
                            if (bHi != null && exAllHi) { remHi = allHi ? Math.min(remHi, bHi.doubleValue() + exHi) : (bHi.doubleValue() + exHi); allHi = true; }
                        }
                        if (mult.size() == 2 && multB.size() == 2) {
                            String yCk = mult.keySet().stream().filter(x -> !x.equals(ckTgt)).findFirst().orElse("");
                            if (!yCk.isEmpty() && mult.getOrDefault(yCk, 0) == 1 && multB.getOrDefault(yCk, 0) == 1) {
                                String zCk = multB.keySet().stream().filter(x -> !x.equals(yCk)).findFirst().orElse("");
                                for (var ce : out.entrySet()) {
                                    if (ce.getKey().equals(se.getKey()) || ce.getKey().equals(be.getKey()) || ce.getKey().equals(e.getKey())
                                            || !isRelationalMap(ce.getValue()) || !(ce.getValue() instanceof Map<?, ?> cm)
                                            || !(cm.get("sum_fields") instanceof List<?> cSf) || cSf.size() != sfList.size()) continue;
                                    Map<String, Integer> multC = new LinkedHashMap<>();
                                    for (Object sf : cSf) {
                                        String ck = canonicalStubRef(sf, wp, tp);
                                        if (!ck.isEmpty()) multC.put(ck, multC.getOrDefault(ck, 0) + 1);
                                    }
                                    if (multC.size() == 2 && multC.getOrDefault(ckTgt, 0) == mk && multC.getOrDefault(zCk, 0) == 1) {
                                        Number cLo = cm.get("min") instanceof Number cn1 ? cn1 : null, cHi = cm.get("max") instanceof Number cn2 ? cn2 : null;
                                        if (sLo != null && cLo != null && bHi != null) loK = maxNum(loK, roundTightenedNum(loK, hiK, (sLo.doubleValue() + cLo.doubleValue() - bHi.doubleValue()) / (2.0 * mk), true));
                                        if (sHi != null && cHi != null && bLo != null) hiK = minNum(hiK, roundTightenedNum(loK, hiK, (sHi.doubleValue() + cHi.doubleValue() - bLo.doubleValue()) / (2.0 * mk), false));
                                    }
                                }
                            }
                        }
                    }
                    if (sLo != null && allHi) loK = maxNum(loK, roundTightenedNum(loK, hiK, (sLo.doubleValue() - remHi) / mk, true));
                    if (sHi != null && allLo) hiK = minNum(hiK, roundTightenedNum(loK, hiK, (sHi.doubleValue() - remLo) / mk, false));
                }
                if (loK != null && (hiK == null || loK.doubleValue() <= hiK.doubleValue())) tv.put("min", loK);
                if (hiK != null && (loK == null || loK.doubleValue() <= hiK.doubleValue())) tv.put("max", hiK);
            }
        }
        return out;
    }
}
