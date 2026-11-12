package drift;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

final class DriftStubs {
    private DriftStubs() {}

    static boolean isRelationalMap(Object val) {
        return Json.isRelationalMap(val);
    }

    static Map<String, Object> tightenThenMapBySumResiduals(Map<String, Object> whenMap, Map<String, Object> rawThen, Map<String, String> whenProjections, Map<String, String> thenProjections) {
        return ExecutionContext.tightenThenMapBySumResiduals(whenMap, rawThen, whenProjections, thenProjections);
    }

    static Map<String, Object> buildPeerIndex(Map<String, Object> whenMap, Map<String, Object> rawThenMap, Map<String, String> whenProjections, Map<String, String> thenProjections) {
        return ExecutionContext.buildPeerIndex(whenMap, rawThenMap, whenProjections, thenProjections);
    }

    static int relPeerRank(Object val) {
        return ExecutionContext.relPeerRank(val);
    }

    static Json.PointerLookup resolveStubPeer(Object rawRef, Object base, Map<String, Object> peerIdx, Map<String, String> whenProjections, Map<String, String> thenProjections) {
        return ExecutionContext.resolveStubPeer(rawRef, base, peerIdx, whenProjections, thenProjections);
    }

    static Number maxNum(Number a, Number b) { return ExecutionContext.maxNum(a, b); }
    static Number minNum(Number a, Number b) { return ExecutionContext.minNum(a, b); }

    static Object witnessValue(Object val, Object base, Map<String, Object> whenMap, Map<String, Object> thenMap, Map<String, String> whenProjections, Map<String, String> thenProjections) {
        return witnessVariants(val, base, buildPeerIndex(whenMap, thenMap, whenProjections, thenProjections), whenProjections, thenProjections).get(0);
    }

    static List<Object> witnessVariants(Object val, Object base, Map<String, Object> peerIdx, Map<String, String> whenProjections, Map<String, String> thenProjections) {
        if (isRelationalMap(val) && val instanceof Map<?, ?> m) {
            if (m.containsKey("eq_field")) {
                Json.PointerLookup pr = resolveStubPeer(m.get("eq_field"), base, peerIdx, whenProjections, thenProjections);
                if (pr.found()) return List.of(Json.cloneJsonValue(pr.value()));
            }
            Number lo = m.get("min") instanceof Number minN ? minN : null;
            Number hi = m.get("max") instanceof Number maxN ? maxN : null;
            if (m.containsKey("ge_field")) {
                Json.PointerLookup pr = resolveStubPeer(m.get("ge_field"), base, peerIdx, whenProjections, thenProjections);
                if (pr.found() && pr.value() instanceof Number n) lo = maxNum(lo, n);
            }
            if (m.containsKey("le_field")) {
                Json.PointerLookup pr = resolveStubPeer(m.get("le_field"), base, peerIdx, whenProjections, thenProjections);
                if (pr.found() && pr.value() instanceof Number n) hi = minNum(hi, n);
            }
            if (m.get("sum_fields") instanceof List<?> sfList && sfList.size() >= 2) {
                boolean allInt = true;
                boolean allFound = true;
                long intSum = 0L;
                double dblSum = 0.0;
                for (Object sf : sfList) {
                    Json.PointerLookup pr = resolveStubPeer(sf, base, peerIdx, whenProjections, thenProjections);
                    if (!pr.found() || !(pr.value() instanceof Number n)) {
                        allFound = false;
                        break;
                    }
                    if (n instanceof Long || n instanceof Integer) {
                        intSum += n.longValue();
                        dblSum += n.doubleValue();
                    } else {
                        allInt = false;
                        dblSum += n.doubleValue();
                    }
                }
                if (allFound) {
                    Number sumN = allInt ? (Number) Long.valueOf(intSum) : (Number) Double.valueOf(Math.round(dblSum * 1e12) / 1e12);
                    lo = maxNum(lo, sumN);
                    hi = minNum(hi, sumN);
                }
            }
            if (m.get("in") instanceof List<?> inList && !inList.isEmpty()) {
                List<Object> out = new ArrayList<>(inList.size());
                for (Object x : inList) {
                    if ((lo == null || (x instanceof Number nx && nx.doubleValue() >= lo.doubleValue()))
                            && (hi == null || (x instanceof Number nx2 && nx2.doubleValue() <= hi.doubleValue()))) {
                        out.add(Json.cloneJsonValue(x));
                    }
                }
                if (!out.isEmpty()) return out;
                for (Object x : inList) out.add(Json.cloneJsonValue(x));
                return out;
            }
            if (m.get("approx") instanceof Number apN) {
                lo = maxNum(lo, apN);
                hi = minNum(hi, apN);
            }
            if (lo != null && hi != null) {
                return Json.valuesEqual(lo, hi) ? List.of(lo) : List.of(lo, hi);
            }
            if (lo != null) return List.of(lo);
            if (hi != null) return List.of(hi);
            if (m.get("contains") instanceof List<?> contList && !contList.isEmpty()) {
                List<Object> out = new ArrayList<>(contList.size());
                for (Object item : contList) out.add(Json.cloneJsonValue(item));
                int minL = Math.max(Boolean.TRUE.equals(m.get("non_empty")) ? 1 : 0,
                        m.get("min_len") instanceof Number mn ? mn.intValue() : 0);
                while (out.size() < minL) out.add(Json.cloneJsonValue(contList.get(0)));
                return List.of(out);
            }
            if (m.get("prefix") instanceof String || m.get("suffix") instanceof String
                    || m.get("min_len") instanceof Number || m.get("max_len") instanceof Number || Boolean.TRUE.equals(m.get("non_empty"))) {
                String pfx = m.get("prefix") instanceof String ps ? ps : "";
                String sfx = m.get("suffix") instanceof String ss ? ss : "";
                int llo = Math.max(Math.max(Boolean.TRUE.equals(m.get("non_empty")) ? 1 : 0,
                        m.get("min_len") instanceof Number mn ? mn.intValue() : 0), pfx.length() + sfx.length());
                int lhi = m.get("max_len") instanceof Number mx ? mx.intValue() : llo;
                String wLo = pfx + "x".repeat(Math.max(0, llo - pfx.length() - sfx.length())) + sfx;
                String wHi = pfx + "x".repeat(Math.max(0, lhi - pfx.length() - sfx.length())) + sfx;
                return lhi > llo ? List.of(wLo, wHi) : List.of(wLo);
            }
            if (m.containsKey("sum_total") || m.containsKey("monotonic") || m.containsKey("step_max_delta")) {
                Object st = m.get("sum_total");
                double tgt = st instanceof Number sn ? sn.doubleValue()
                        : (st instanceof Map<?, ?> sm && sm.get("eq") instanceof Number eqn ? eqn.doubleValue()
                        : (st instanceof Map<?, ?> sm2 && sm2.get("min") instanceof Number mn && sm2.get("max") instanceof Number mx ? (mn.doubleValue() + mx.doubleValue()) / 2.0
                        : (st instanceof Map<?, ?> sm3 && sm3.get("min") instanceof Number mn2 ? mn2.doubleValue()
                        : (st instanceof Map<?, ?> sm4 && sm4.get("max") instanceof Number mx2 ? mx2.doubleValue() : 1.0))));
                double eps = m.get("step_max_delta") instanceof Number dn && dn.doubleValue() > 0.0
                        ? Math.min(0.2, dn.doubleValue() / 2.0) : 0.2;
                String mode = m.get("monotonic") instanceof String ms ? ms : "";
                if ("strictly_decreasing".equals(mode) || "non_increasing".equals(mode)) {
                    double a = Math.round((tgt / 2.0 + eps / 2.0) * 1e12) / 1e12;
                    return List.of(m.containsKey("sum_total") ? List.of(a, Math.round((tgt - a) * 1e12) / 1e12) : List.of(Math.round((1.0 + eps) * 1e12) / 1e12, 1.0));
                }
                if ("strictly_increasing".equals(mode) || "non_decreasing".equals(mode)) {
                    double a = Math.round((tgt / 2.0 - eps / 2.0) * 1e12) / 1e12;
                    return List.of(m.containsKey("sum_total") ? List.of(a, Math.round((tgt - a) * 1e12) / 1e12) : List.of(1.0, Math.round((1.0 + eps) * 1e12) / 1e12));
                }
                return List.of(List.of(tgt / 2.0, tgt - tgt / 2.0));
            }
            return List.of("");
        }
        return List.of(Json.cloneJsonValue(val));
    }

    static Map<String, Object> resolveStubView(String contractOrResource, boolean inTest) {
        DriftInternal.UpstreamMatch up = DriftInternal.findUpstreamContract(contractOrResource);
        DriftCase tag = inTest ? Drift.tag() : null;
        if (up != null) {
            if (inTest && !Drift.mutationRun() && up.file() != null && (tag == null || !tag.contract().equals(contractOrResource))) {
                Drift.recordInput(up.file());
            }
            if (tag != null && tag.contract().equals(contractOrResource)) Drift.recordSelfStub(tag.contract());
            return up.view();
        }
        Map<String, Object> v = Drift.view(contractOrResource);
        if (tag != null && (tag.contract().equals(contractOrResource) || tag.contract().equals(v.get("id")))) Drift.recordSelfStub(tag.contract());
        return v;
    }

    static Map<String, String> extractProjectionMap(Map<String, Object> v, String side) {
        Map<String, String> out = new LinkedHashMap<>();
        if (v.get("projections") instanceof Map<?, ?> pr) {
            for (Map.Entry<?, ?> e : pr.entrySet()) {
                if (e.getKey() instanceof String k && !"when".equals(k) && !"then".equals(k) && e.getValue() instanceof String s) {
                    out.put(k, s);
                }
            }
            if (pr.get(side) instanceof Map<?, ?> tp) {
                for (Map.Entry<?, ?> e : tp.entrySet()) {
                    if (e.getKey() instanceof String k && e.getValue() instanceof String s) {
                        out.put(k, s);
                    }
                }
            }
        }
        return out;
    }

    private static boolean isHomologousKey(String a, String b) {
        if (a.equals(b)) return false;
        String la = a.toLowerCase(), lb = b.toLowerCase();
        String[] ta = la.split("_"), tb = lb.split("_");
        if (ta.length == tb.length && ta.length >= 2) {
            int diff = 0;
            boolean ok = true;
            for (int i = 0; i < ta.length; i++) {
                if (ta[i].equals(tb[i])) continue;
                diff++;
                String p = ta[i] + ":" + tb[i];
                if (!("1:2".equals(p) || "2:1".equals(p) || "a:b".equals(p) || "b:a".equals(p) || "x:y".equals(p) || "y:x".equals(p)
                        || "left:right".equals(p) || "right:left".equals(p) || "src:dst".equals(p) || "dst:src".equals(p)
                        || "source:target".equals(p) || "target:source".equals(p) || "from:to".equals(p) || "to:from".equals(p)
                        || "primary:secondary".equals(p) || "secondary:primary".equals(p) || "first:second".equals(p) || "second:first".equals(p))) {
                    ok = false;
                }
            }
            if (ok && diff == 1) return true;
        }
        return la.length() == lb.length() && la.length() >= 2 && la.substring(0, la.length() - 1).equals(lb.substring(0, lb.length() - 1))
                && "12abxy".indexOf(la.charAt(la.length() - 1)) >= 0 && "12abxy".indexOf(lb.charAt(lb.length() - 1)) >= 0;
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> synthesizeMap(Map<String, Object> thenMap, Map<String, Object> peerIdx, Map<String, String> whenProjections, Map<String, String> thenProjections, Map<String, Object> base, boolean useWitness) {
        Object out = Json.cloneJsonValue(base == null ? Map.of() : base);
        List<Map.Entry<String, Object>> entries = new ArrayList<>(thenMap.entrySet());
        if (useWitness && entries.size() > 1) {
            entries.sort((a, b) -> relPeerRank(a.getValue()) != relPeerRank(b.getValue()) ? Integer.compare(relPeerRank(a.getValue()), relPeerRank(b.getValue())) : a.getKey().compareTo(b.getKey()));
        }
        Map<String, Object> resolved = new LinkedHashMap<>(thenMap.size());
        for (Map.Entry<String, Object> e : entries) {
            List<Object> vars = useWitness ? witnessVariants(e.getValue(), out, peerIdx, whenProjections, thenProjections) : List.of(e.getValue());
            Object w = vars.get(0);
            if (useWitness && vars.size() > 1 && !(e.getValue() instanceof Map<?, ?> rm && rm.containsKey("eq_field"))) {
                for (Map.Entry<String, Object> prev : resolved.entrySet()) {
                    if (isHomologousKey(prev.getKey(), e.getKey()) && Json.valuesEqual(prev.getValue(), w)) {
                        for (int vi = 1; vi < vars.size(); vi++) {
                            if (!Json.valuesEqual(prev.getValue(), vars.get(vi))) {
                                w = vars.get(vi);
                                break;
                            }
                        }
                        break;
                    }
                }
            }
            resolved.put(e.getKey(), w);
            if (useWitness && peerIdx != null) {
                peerIdx.put(e.getKey(), w);
                String tp = thenProjections == null ? "" : Json.splitResourcePointer(thenProjections.getOrDefault(e.getKey(), ""))[1];
                if (tp.startsWith("/")) peerIdx.put(tp, w);
            }
            if (thenProjections.containsKey(e.getKey())) out = Json.writeJsonPointer(out, thenProjections.get(e.getKey()), w);
            else if (out instanceof Map<?, ?> m) ((Map<String, Object>) m).put(e.getKey(), w);
        }
        for (String k : thenMap.keySet()) {
            if (!thenProjections.containsKey(k) && out instanceof Map<?, ?> m) ((Map<String, Object>) m).put(k, resolved.get(k));
        }
        return out instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
    }

    static Json.PointerLookup lookupWhenInput(Map<String, Object> whenInput, String wk, Map<String, String> whenProjections) {
        if (whenInput == null) return new Json.PointerLookup(false, null);
        if (whenInput.containsKey(wk)) return new Json.PointerLookup(true, whenInput.get(wk));
        String rawP = whenProjections == null ? "" : whenProjections.getOrDefault(wk, "");
        String bareP = Json.splitResourcePointer(rawP)[1];
        for (String p : List.of(rawP, bareP, "/" + wk)) {
            if (p == null || p.isEmpty()) continue;
            if (whenInput.containsKey(p)) return new Json.PointerLookup(true, whenInput.get(p));
            Json.PointerLookup r = Json.readJsonPointer(whenInput, p);
            if (r.found()) return r;
        }
        return new Json.PointerLookup(false, null);
    }

    static String resolveStubCaseByWhen(Map<String, Object> v, String contractOrResource, Map<String, Object> whenInput, Map<String, Object> base) {
        Map<String, Object> cases = DriftInternal.map(v.get("cases"), contractOrResource + ".cases");
        Map<String, String> whenProjections = extractProjectionMap(v, "when");
        Map<String, String> thenProjections = extractProjectionMap(v, "then");
        int bestScore = 0;
        List<String> bestCases = new ArrayList<>();
        for (String cId : new TreeMap<>(cases).keySet()) {
            Map<String, Object> cm = DriftInternal.map(cases.get(cId), contractOrResource + ".cases." + cId);
            if (cm.containsKey("status")) continue;
            Map<String, Object> whenMap = DriftInternal.map(cm.getOrDefault("when", Map.of()), "when");
            int matched = 0;
            boolean compat = true;
            for (Map.Entry<String, Object> e : whenMap.entrySet()) {
                Json.PointerLookup hit = lookupWhenInput(whenInput, e.getKey(), whenProjections);
                if (!hit.found()) continue;
                if (!Json.valuesEqual(hit.value(), e.getValue())) {
                    compat = false;
                    break;
                }
                matched++;
            }
            if (compat && matched > 0) {
                if (matched > bestScore) {
                    bestScore = matched;
                    bestCases = new ArrayList<>(List.of(cId));
                } else if (matched == bestScore) {
                    bestCases.add(cId);
                }
            }
        }
        if (bestCases.isEmpty()) {
            throw new IllegalStateException("DRIFT: contract \"" + contractOrResource + "\" has no case matching when input");
        }
        if (bestCases.size() >= 2) {
            List<Map<String, List<Object>>> varsByCase = new ArrayList<>(bestCases.size());
            for (String c : bestCases) {
                Map<String, Object> cm = DriftInternal.map(cases.get(c), contractOrResource + ".cases." + c);
                Map<String, Object> wTbl = DriftInternal.map(cm.getOrDefault("when", Map.of()), "when");
                Map<String, Object> tTbl = DriftInternal.map(cm.getOrDefault("then", Map.of()), "then");
                Map<String, Object> pIdx = buildPeerIndex(wTbl, tTbl, whenProjections, thenProjections);
                Map<String, List<Object>> m = new LinkedHashMap<>();
                for (String tk : new TreeMap<>(tTbl).keySet()) {
                    String ptr = Json.splitResourcePointer(thenProjections.getOrDefault(tk, ""))[1];
                    if (ptr.isEmpty()) ptr = tk;
                    m.putIfAbsent(ptr, witnessVariants(tTbl.get(tk), base, pIdx, whenProjections, thenProjections));
                }
                varsByCase.add(m);
            }
            for (int i = 0; i < bestCases.size(); i++) {
                for (int j = i + 1; j < bestCases.size(); j++) {
                    for (Map.Entry<String, List<Object>> e : varsByCase.get(i).entrySet()) {
                        String ptr = e.getKey();
                        if (varsByCase.get(j).containsKey(ptr) && !Json.valuesEqual(e.getValue(), varsByCase.get(j).get(ptr))) {
                            throw new IllegalStateException("DRIFT: ambiguous boundary projection on \"" + contractOrResource + "\" (" + ptr + ") across " + bestCases.get(i) + ", " + bestCases.get(j));
                        }
                    }
                }
            }
        }
        return bestCases.get(0);
    }

    static Map<String, Object> buildStubByWhen(String contractOrResource, Map<String, Object> whenInput, Map<String, Object> base, boolean inTest) {
        Map<String, Object> v = resolveStubView(contractOrResource, inTest);
        return buildStub(contractOrResource, resolveStubCaseByWhen(v, contractOrResource, whenInput, base), base, inTest);
    }

    static List<Map<String, Object>> buildStubVariantsByWhen(String contractOrResource, Map<String, Object> whenInput, Map<String, Object> base, boolean inTest) {
        Map<String, Object> v = resolveStubView(contractOrResource, inTest);
        String caseId = resolveStubCaseByWhen(v, contractOrResource, whenInput, base);
        return buildStubVariants(contractOrResource, caseId, base, inTest);
    }

    static boolean verifyStubByWhen(String contractOrResource, Map<String, Object> whenInput, Object payload, boolean inTest) {
        Map<String, Object> v = resolveStubView(contractOrResource, inTest);
        String caseId = resolveStubCaseByWhen(v, contractOrResource, whenInput, Map.of());
        return verifyStub(contractOrResource, caseId, payload, inTest);
    }

    static Map<String, Object> requireActiveCase(Map<String, Object> v, String contractOrResource, String caseId) {
        Map<String, Object> cases = DriftInternal.map(v.get("cases"), contractOrResource + ".cases");
        Map<String, Object> cm = DriftInternal.map(cases.get(caseId), contractOrResource + ".cases." + caseId);
        if (cm.containsKey("status")) {
            throw new IllegalStateException("DRIFT: case \"" + caseId + "\" of contract \"" + contractOrResource + "\" is " + cm.get("status") + " and cannot be stubbed");
        }
        return cm;
    }

    private static void recordSeamIfExternal(Map<String, Object> v, String contractOrResource, String caseId, boolean inTest) {
        if (!inTest) return;
        DriftCase tag = Drift.tag();
        if (tag == null) return;
        String prodId = v.get("id") instanceof String s ? s : contractOrResource;
        if (tag.contract().equals(contractOrResource) || tag.contract().equals(prodId)) return;
        String prodRef = v.get("ref") instanceof String r
                ? r
                : (v.get("digest") instanceof String d ? d : "sha256:seam-stub");
        Drift.recordSeamStub(prodId, caseId, prodRef);
    }

    private static Map<String, Object> mergeOntoBase(Map<String, Object> base, Object precomputed) {
        @SuppressWarnings("unchecked")
        Map<String, Object> out = base == null || base.isEmpty()
                ? new LinkedHashMap<>()
                : (Map<String, Object>) Json.cloneJsonValue(base);
        if (precomputed instanceof Map<?, ?> pm) {
            for (Map.Entry<?, ?> e : pm.entrySet()) {
                out.put(String.valueOf(e.getKey()), Json.cloneJsonValue(e.getValue()));
            }
        }
        return out;
    }

    private static Map<String, Object> planCase(Map<String, Object> v, String contractOrResource, String caseId) {
        String cid = v.get("id") instanceof String s ? s : contractOrResource;
        Map<String, Object> plan = DriftInternal.loadPlan(cid);
        return plan != null && plan.get("cases") instanceof Map<?, ?> cs && cs.get(caseId) instanceof Map<?, ?> cm
                ? DriftInternal.map(cm, cid + ".plan.cases." + caseId)
                : null;
    }

    static Map<String, Object> buildStub(String contractOrResource, String caseId, Map<String, Object> base, boolean inTest) {
        Map<String, Object> v = resolveStubView(contractOrResource, inTest);
        Map<String, Object> cm = requireActiveCase(v, contractOrResource, caseId);
        recordSeamIfExternal(v, contractOrResource, caseId, inTest);
        Map<String, Object> pcm = planCase(v, contractOrResource, caseId);
        if (pcm != null && pcm.get("stub_output") instanceof Map<?, ?>) {
            return mergeOntoBase(base, pcm.get("stub_output"));
        }
        Map<String, String> wp = extractProjectionMap(v, "when"), tp = extractProjectionMap(v, "then");
        Map<String, Object> wm = DriftInternal.map(cm.getOrDefault("when", Map.of()), "when");
        Map<String, Object> tm = tightenThenMapBySumResiduals(wm, DriftInternal.map(cm.getOrDefault("then", Map.of()), "then"), wp, tp);
        return synthesizeMap(tm, buildPeerIndex(wm, tm, wp, tp), wp, tp, base, true);
    }

    static List<Map<String, Object>> buildStubVariants(String contractOrResource, String caseId, Map<String, Object> base, boolean inTest) {
        Map<String, Object> v = resolveStubView(contractOrResource, inTest);
        Map<String, Object> cm = requireActiveCase(v, contractOrResource, caseId);
        recordSeamIfExternal(v, contractOrResource, caseId, inTest);
        Map<String, Object> pcm = planCase(v, contractOrResource, caseId);
        if (pcm != null && pcm.get("stub_variants") instanceof List<?> pv && !pv.isEmpty()) {
            List<Map<String, Object>> res = new ArrayList<>(pv.size());
            for (Object item : pv) res.add(mergeOntoBase(base, item));
            return res;
        }
        Map<String, String> wp = extractProjectionMap(v, "when"), tp = extractProjectionMap(v, "then");
        Map<String, Object> wm = DriftInternal.map(cm.getOrDefault("when", Map.of()), "when");
        Map<String, Object> tm = tightenThenMapBySumResiduals(wm, DriftInternal.map(cm.getOrDefault("then", Map.of()), "then"), wp, tp);
        Map<String, Object> peerIdx = buildPeerIndex(wm, tm, wp, tp);
        List<String> keys = new ArrayList<>(new TreeMap<>(tm).keySet());
        List<List<Object>> varsByKey = new ArrayList<>(keys.size());
        Map<String, Object> cur = new LinkedHashMap<>(keys.size());
        for (String k : keys) {
            List<Object> vars = witnessVariants(tm.get(k), base, peerIdx, wp, tp);
            varsByKey.add(vars);
            cur.put(k, vars.get(0));
        }
        List<Map<String, Object>> outList = new ArrayList<>();
        collectStubVariants(keys, varsByKey, 0, 0, keys.size() >= 3 ? 2 : keys.size(), cur, wm, tm, wp, tp, base, outList);
        return outList;
    }

    private static void collectStubVariants(List<String> keys, List<List<Object>> varsByKey, int pos, int exc, int maxExc, Map<String, Object> cur, Map<String, Object> whenMap, Map<String, Object> specTbl, Map<String, String> whenProj, Map<String, String> thenProj, Map<String, Object> base, List<Map<String, Object>> outList) {
        if (pos == keys.size() || exc >= maxExc) {
            Map<String, Object> eff = new LinkedHashMap<>(cur);
            for (int i = 0; i < keys.size(); i++) {
                String k = keys.get(i);
                if (relPeerRank(specTbl.get(k)) > 0 && Json.valuesEqual(eff.get(k), varsByKey.get(i).get(0))) eff.put(k, specTbl.get(k));
            }
            outList.add(synthesizeMap(eff, buildPeerIndex(whenMap, eff, whenProj, thenProj), whenProj, thenProj, base, true));
            return;
        }
        collectStubVariants(keys, varsByKey, pos + 1, exc, maxExc, cur, whenMap, specTbl, whenProj, thenProj, base, outList);
        List<Object> vars = varsByKey.get(pos);
        String k = keys.get(pos);
        for (int i = 1; i < vars.size(); i++) {
            cur.put(k, vars.get(i));
            collectStubVariants(keys, varsByKey, pos + 1, exc + 1, maxExc, cur, whenMap, specTbl, whenProj, thenProj, base, outList);
        }
        cur.put(k, vars.get(0));
    }

    static boolean verifyStub(String contractOrResource, String caseId, Object payload, boolean inTest) {
        Map<String, Object> v = resolveStubView(contractOrResource, inTest);
        Map<String, Object> cases = DriftInternal.map(v.get("cases"), contractOrResource + ".cases");
        Map<String, Object> cm = DriftInternal.map(cases.get(caseId), contractOrResource + ".cases." + caseId);
        Map<String, Object> thenMap = DriftInternal.map(cm.getOrDefault("then", Map.of()), "then");
        Map<String, String> thenProjections = extractProjectionMap(v, "then");
        String cid = v.get("id") instanceof String s ? s : contractOrResource;
        Drift.Case stubCase = new Drift.Case(cid, caseId, Map.of(), thenMap);
        for (Map.Entry<String, Object> e : thenMap.entrySet()) {
            DriftViewChecks.checkProjectedLeaf(stubCase, e.getKey(), e.getValue(), payload, thenProjections, true, "no projection for");
        }
        return true;
    }
}
