package drift;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;

/** Optional execution context of the inventory sidecar: execution_ref (version 2), pack_ref and touched paths. */
final class ExecutionContext {
    private ExecutionContext() {
    }

    /** The validated execution reference, or null when none is configured. */
    static String executionRef() {
        String ref = configured(DriftListener.EXECUTION_REF, "DRIFT_EXECUTION_REF");
        if (ref != null && !ref.matches("sha256:[0-9a-f]{64}")) {
            throw new IllegalStateException("invalid drift.executionRef / DRIFT_EXECUTION_REF");
        }
        return ref;
    }

    /** Appends pack_ref and touched after the snapshot; touched is always written with an execution reference. */
    static void appendTail(StringBuilder json, String executionRef) {
        String packRef = configured(DriftListener.PACK_REF, "DRIFT_PACK_REF");
        if (packRef != null) {
            if (!validPackRef(packRef)) {
                throw new IllegalStateException("invalid drift.packRef / DRIFT_PACK_REF");
            }
            Json.field(json.append(','), "pack_ref", packRef);
        }
        TreeSet<String> touched = new TreeSet<>();
        String raw = configured(DriftListener.TOUCHED, "DRIFT_TOUCHED");
        for (String value : raw == null ? new String[0] : raw.split("[\\n,]+")) {
            String path = value.trim();
            if (path.isEmpty()) {
                continue;
            }
            if (!safePath(path)) {
                throw new IllegalStateException("invalid touched path: " + path);
            }
            touched.add(path);
        }
        if (!touched.isEmpty() || executionRef != null) {
            Json.field(json.append(','), "touched", new ArrayList<>(touched));
        }
    }

    /** Rejects a prior sidecar whose version, execution_ref, pack_ref or touched paths are malformed. */
    static void checkHead(Path sidecar, Map<String, Object> inventory) {
        Object version = inventory.get("version");
        boolean v2 = Long.valueOf(2).equals(version);
        if (!(v2 || Long.valueOf(1).equals(version))
                || (v2 ? !(inventory.get("execution_ref") instanceof String ref && ref.matches("sha256:[0-9a-f]{64}"))
                        : inventory.containsKey("execution_ref"))) {
            throw new IllegalStateException(sidecar + " has an invalid inventory shape");
        }
        if (inventory.containsKey("pack_ref")
                && !(inventory.get("pack_ref") instanceof String packRef && validPackRef(packRef))) {
            throw new IllegalStateException(sidecar + " has an invalid pack_ref");
        }
        if (!inventory.containsKey("touched")) {
            return;
        }
        if (!(inventory.get("touched") instanceof List<?> list) || !list.stream().allMatch(String.class::isInstance)) {
            throw new IllegalStateException(sidecar + " has invalid touched paths");
        }
        List<String> paths = list.stream().map(String.class::cast).toList();
        if (!paths.stream().allMatch(ExecutionContext::safePath)) {
            throw new IllegalStateException(sidecar + " has an invalid touched path");
        }
        if (!paths.equals(paths.stream().distinct().sorted().toList())) {
            throw new IllegalStateException(sidecar + " touched paths are not sorted and unique");
        }
    }

    private static String configured(String property, String envName) {
        String value = System.getProperty(property);
        if (value == null || value.isBlank()) {
            value = System.getenv(envName);
        }
        return value == null || value.isBlank() ? null : value.trim();
    }

    private static boolean validPackRef(String value) {
        return value.matches("dr(?:1|2b):[0-9a-f]{12}");
    }

    private static boolean safePath(String path) {
        return !path.startsWith("/") && !path.contains("\\") && List.of(path.split("/", -1)).stream()
                .noneMatch(s -> s.isEmpty() || s.equals(".") || s.equals(".."));
    }

    static boolean inputsUnchanged(Map<Path, String> inputPaths) {
        for (Map.Entry<Path, String> e : inputPaths.entrySet()) {
            try {
                Path abs = e.getKey();
                if (!Files.isRegularFile(abs)) return false;
                String v = e.getValue();
                int sep = v.indexOf('|');
                String sig = v.substring(0, sep);
                String dig = v.substring(sep + 1);
                if (sig.startsWith("L:")
                        ? !DriftInternal.fileSignature(abs).equals(sig)
                        : !DriftInternal.sha256File(abs).equals(dig)) {
                    return false;
                }
            } catch (RuntimeException ex) {
                return false;
            }
        }
        return true;
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> buildInput(Map<String, Object> when, Map<String, String> whenProj, Map<String, Object> base) {
        Object out = Json.cloneJsonValue(base == null ? Map.of() : base);
        for (Map.Entry<String, Object> e : when.entrySet()) {
            String key = e.getKey();
            Object val = e.getValue();
            if (whenProj.containsKey(key)) {
                out = Json.writeJsonPointer(out, whenProj.get(key), val);
            } else if (out instanceof Map<?, ?> m) {
                ((Map<String, Object>) m).put(key, Json.cloneJsonValue(val));
            }
        }
        return out instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
    }

    static String canonicalStubRef(Object rawRef, Map<String, String> whenProjections, Map<String, String> thenProjections) {
        if (!(rawRef instanceof String ref) || ref.isBlank()) return "";
        String s = ref.trim();
        if (s.startsWith("/")) return Json.splitResourcePointer(s)[1];
        String p = thenProjections != null && thenProjections.containsKey(s) ? thenProjections.get(s) : (whenProjections != null && whenProjections.containsKey(s) ? whenProjections.get(s) : ("/" + s));
        return Json.splitResourcePointer(p)[1];
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
                    if (Json.isRelationalMap(e.getValue()) && e.getValue() instanceof Map<?, ?> rm) {
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
            if (!Json.isRelationalMap(e.getValue()) || !(e.getValue() instanceof Map<?, ?> m)) continue;
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
            if (Json.isRelationalMap(v) && v instanceof Map<?, ?> m
                    && ((m.get("sum_fields") instanceof List<?> sf && sf.size() >= 2)
                    || m.containsKey("le_field") || m.containsKey("ge_field") || m.containsKey("eq_field"))) {
                anyPeer = true;
                break;
            }
        }
        if (!anyPeer) return rawThen;
        Map<String, Object> out = (Map<String, Object>) Json.cloneJsonValue(rawThen);
        for (int pass = 0; pass < 3; pass++) {
            for (var e : out.entrySet()) {
                if (!Json.isRelationalMap(e.getValue()) || !(e.getValue() instanceof Map<?, ?> rawM)) continue;
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
                    if (pe.getKey().equals(e.getKey()) || !Json.isRelationalMap(pe.getValue()) || !(pe.getValue() instanceof Map<?, ?> pm)) continue;
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
                    if (se.getKey().equals(e.getKey()) || !Json.isRelationalMap(se.getValue()) || !(se.getValue() instanceof Map<?, ?> sm)
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
                        if (be.getKey().equals(se.getKey()) || be.getKey().equals(e.getKey()) || !Json.isRelationalMap(be.getValue())
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
                                            || !Json.isRelationalMap(ce.getValue()) || !(ce.getValue() instanceof Map<?, ?> cm)
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

    static int relPeerRank(Object val) {
        if (!Json.isRelationalMap(val) || !(val instanceof Map<?, ?> m)) return 0;
        return m.get("sum_fields") instanceof List<?> sf ? 2 + sf.size() : (m.containsKey("eq_field") || m.containsKey("ge_field") || m.containsKey("le_field") ? 1 : 0);
    }

    static Json.PointerLookup resolveStubPeer(Object rawRef, Object base, Map<String, Object> peerIdx, Map<String, String> whenProjections, Map<String, String> thenProjections) {
        if (!(rawRef instanceof String ref) || ref.isBlank()) return new Json.PointerLookup(false, null);
        String s = ref.trim();
        String bare = s.replaceFirst("^/+", "");
        if (s.startsWith("/")) {
            Json.PointerLookup r = Json.readJsonPointer(base, s);
            if (r.found() && !Json.isRelationalMap(r.value())) return r;
        } else {
            if (base instanceof Map<?, ?> bm && bm.containsKey(s) && !Json.isRelationalMap(bm.get(s))) {
                return new Json.PointerLookup(true, bm.get(s));
            }
            for (Map<String, String> pm : List.of(thenProjections == null ? Map.<String, String>of() : thenProjections, whenProjections == null ? Map.<String, String>of() : whenProjections)) {
                if (pm.containsKey(s)) {
                    Json.PointerLookup r = Json.readJsonPointer(base, pm.get(s));
                    if (r.found() && !Json.isRelationalMap(r.value())) return r;
                }
            }
            Json.PointerLookup r = Json.readJsonPointer(base, "/" + bare);
            if (r.found() && !Json.isRelationalMap(r.value())) return r;
        }
        String rawTgt = s.startsWith("/") ? s : (thenProjections != null && thenProjections.containsKey(s) ? thenProjections.get(s) : (whenProjections != null && whenProjections.containsKey(s) ? whenProjections.get(s) : ("/" + bare)));
        String tgt = Json.splitResourcePointer(rawTgt)[1];
        if (peerIdx != null) {
            for (String cand : List.of(s, bare, tgt)) {
                if (!cand.isEmpty() && peerIdx.containsKey(cand)) {
                    return new Json.PointerLookup(true, peerIdx.get(cand));
                }
            }
        }
        return new Json.PointerLookup(false, null);
    }

    static Map<String, Object> buildPeerIndex(Map<String, Object> whenMap, Map<String, Object> rawThenMap, Map<String, String> whenProjections, Map<String, String> thenProjections) {
        Map<String, Object> thenMap = tightenThenMapBySumResiduals(whenMap, rawThenMap, whenProjections, thenProjections);
        Map<String, Object> idx = new LinkedHashMap<>();
        if (whenMap != null) {
            for (Map.Entry<String, Object> e : whenMap.entrySet()) {
                if (Json.isRelationalMap(e.getValue())) continue;
                idx.put(e.getKey(), e.getValue());
                String wp = whenProjections == null ? "" : Json.splitResourcePointer(whenProjections.getOrDefault(e.getKey(), ""))[1];
                if (wp.startsWith("/")) idx.put(wp, e.getValue());
            }
        }
        List<Map.Entry<String, Object>> relEntries = new ArrayList<>();
        if (thenMap != null) {
            for (Map.Entry<String, Object> e : thenMap.entrySet()) {
                if (Json.isRelationalMap(e.getValue())) {
                    relEntries.add(e);
                    continue;
                }
                idx.put(e.getKey(), e.getValue());
                String tp = thenProjections == null ? "" : Json.splitResourcePointer(thenProjections.getOrDefault(e.getKey(), ""))[1];
                if (tp.startsWith("/")) idx.put(tp, e.getValue());
            }
        }
        if (!relEntries.isEmpty()) {
            relEntries.sort((a, b) -> relPeerRank(a.getValue()) != relPeerRank(b.getValue()) ? Integer.compare(relPeerRank(a.getValue()), relPeerRank(b.getValue())) : a.getKey().compareTo(b.getKey()));
            for (int pass = 0; pass < 8; pass++) {
                boolean progress = false;
                for (Map.Entry<String, Object> e : relEntries) {
                    if (idx.containsKey(e.getKey()) || !(e.getValue() instanceof Map<?, ?> m)) continue;
                    if ((m.containsKey("eq_field") && !resolveStubPeer(m.get("eq_field"), Map.of(), idx, whenProjections, thenProjections).found())
                            || (m.containsKey("ge_field") && !resolveStubPeer(m.get("ge_field"), Map.of(), idx, whenProjections, thenProjections).found())
                            || (m.containsKey("le_field") && !resolveStubPeer(m.get("le_field"), Map.of(), idx, whenProjections, thenProjections).found())
                            || (m.get("sum_fields") instanceof List<?> sfList && sfList.stream().anyMatch(sf -> !resolveStubPeer(sf, Map.of(), idx, whenProjections, thenProjections).found()))) {
                        continue;
                    }
                    Object w = DriftStubs.witnessVariants(e.getValue(), Map.of(), idx, whenProjections, thenProjections).get(0);
                    idx.put(e.getKey(), w);
                    String tp = thenProjections == null ? "" : Json.splitResourcePointer(thenProjections.getOrDefault(e.getKey(), ""))[1];
                    if (tp.startsWith("/")) idx.put(tp, w);
                    progress = true;
                }
                if (!progress) break;
            }
        }
        return idx;
    }
}
