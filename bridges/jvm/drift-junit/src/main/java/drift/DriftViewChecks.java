package drift;

import java.util.AbstractMap;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.BiConsumer;
import java.util.function.Consumer;

final class DriftViewChecks {
    private static final java.util.regex.Pattern COMPARATIVE_BASELINE_PATTERN =
            java.util.regex.Pattern.compile("^(?:invariato|unchanged|same|nessuna variazione|[+-]\\s*\\d).*");
    private static final Set<String> NON_VERIFIED_OP_STATES = Set.of(
            "prepared", "accepted", "queued", "running", "in_progress",
            "partial_failure", "cancellation_requested", "unknown");
    private static final Set<String> TERMINAL_UI_CLAIMS = Set.of(
            "completed", "complete", "verified", "done", "fulfilled",
            "available", "sent", "paid", "approved");
    private static final Set<String> RELATIONAL_KEYS = Set.of(
            "min", "max", "min_len", "max_len", "non_empty",
            "le_field", "ge_field", "eq_field", "in", "not_in",
            "sum_fields", "contains", "prefix", "suffix", "allowed_keys", "forbid_keys",
            "monotonic", "sum_total", "step_max_delta", "approx", "abs_tol", "rel_tol",
            "balance_fields", "unit", "unit_conversion",
            "eq", "len", "keys", "peer", "series", "tol", "convert_from");

    private static String stripSide03(Object raw) {
        if (raw instanceof String s && (s.startsWith("when.") || s.startsWith("then."))) {
            return s.substring(s.indexOf('.') + 1);
        }
        return raw instanceof String s ? s : "";
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> desugar03Rel(Map<?, ?> raw) {
        Map<String, Object> out = new java.util.LinkedHashMap<>();
        for (Map.Entry<?, ?> e : raw.entrySet()) {
            String k = String.valueOf(e.getKey());
            Object v = e.getValue();
            if ("tol".equals(k) && v instanceof Map<?, ?> m) {
                if (m.containsKey("abs")) out.put("abs_tol", m.get("abs"));
                if (m.containsKey("rel")) out.put("rel_tol", m.get("rel"));
            } else if ("len".equals(k) && v instanceof Map<?, ?> m) {
                if (m.containsKey("min")) out.put("min_len", m.get("min"));
                if (m.containsKey("max")) out.put("max_len", m.get("max"));
            } else if ("keys".equals(k) && v instanceof Map<?, ?> m) {
                if (m.containsKey("allow")) out.put("allowed_keys", m.get("allow"));
                if (m.containsKey("forbid")) out.put("forbid_keys", m.get("forbid"));
            } else if ("peer".equals(k) && v instanceof Map<?, ?> m) {
                if (m.containsKey("le")) out.put("le_field", stripSide03(m.get("le")));
                if (m.containsKey("ge")) out.put("ge_field", stripSide03(m.get("ge")));
                if (m.containsKey("eq")) out.put("eq_field", stripSide03(m.get("eq")));
                if (m.get("sum") instanceof List<?> sumList) {
                    out.put("sum_fields", sumList.stream().map(DriftViewChecks::stripSide03).toList());
                }
                if (m.get("balance") instanceof Map<?, ?> bm) {
                    Map<String, Object> nb = new java.util.LinkedHashMap<>();
                    if (bm.get("add") instanceof List<?> addList) {
                        nb.put("add", addList.stream().map(DriftViewChecks::stripSide03).toList());
                    }
                    if (bm.get("sub") instanceof List<?> subList) {
                        nb.put("sub", subList.stream().map(DriftViewChecks::stripSide03).toList());
                    }
                    out.put("balance_fields", nb);
                }
            } else if ("series".equals(k) && v instanceof Map<?, ?> m) {
                for (Map.Entry<?, ?> se : m.entrySet()) {
                    String sk = String.valueOf(se.getKey());
                    Object sv = se.getValue();
                    if ("monotonic".equals(sk) && ("increasing".equals(sv) || "decreasing".equals(sv))) {
                        sv = "strictly_" + sv;
                    }
                    out.put(sk, sv);
                }
            } else if (!"convert_from".equals(k)) {
                out.put(k, v);
            }
        }
        if (out.containsKey("eq") && (out.containsKey("abs_tol") || out.containsKey("rel_tol"))
                && !out.containsKey("balance_fields") && !out.containsKey("sum_fields")) {
            out.put("approx", out.remove("eq"));
        }
        return out;
    }

    private DriftViewChecks() {}

    private static int lengthOfValue(Object v) {
        if (v instanceof String s) {
            return s.length();
        }
        if (v instanceof List<?> l) {
            return l.size();
        }
        if (v instanceof Map<?, ?> m) {
            return m.size();
        }
        return -1;
    }

    static Json.PointerLookup resolvePeer(Object payload, Map<String, String> proj, Object rawRef) {
        if (!(rawRef instanceof String ref) || ref.isBlank()) {
            return new Json.PointerLookup(false, null);
        }
        if (ref.startsWith("/")) {
            return Json.readJsonPointer(payload, ref);
        }
        if (proj != null && proj.containsKey(ref)) {
            return Json.readJsonPointer(payload, proj.get(ref));
        }
        if (payload instanceof Map<?, ?> m && m.containsKey(ref)) {
            return new Json.PointerLookup(true, m.get(ref));
        }
        return new Json.PointerLookup(false, null);
    }

    static boolean checkRelationalConstraint(
            Drift.Case c,
            String key,
            Object expected,
            Object actual,
            Object payload,
            Map<String, String> proj) {
        if (!(expected instanceof Map<?, ?> rawExp) || rawExp.isEmpty()) {
            return false;
        }
        for (Object rk : rawExp.keySet()) {
            if (!(rk instanceof String s) || !RELATIONAL_KEYS.contains(s)) {
                return false;
            }
        }
        Map<String, Object> exp = desugar03Rel(rawExp);
        String pfx = c.contract() + "." + c.id();
        if (exp.containsKey("eq")) {
            if (!Json.valuesEqual(actual, exp.get("eq"))) {
                throw new AssertionError(pfx + ": expected then." + key + "=" + exp.get("eq") + ", got " + actual);
            }
            if (exp.size() == 1) {
                return true;
            }
        }
        if (DriftVerify.checkObjectKeysAndNotIn(pfx, key, exp, actual)) {
            return true;
        }
        boolean isSeqTuning = exp.containsKey("monotonic") || exp.containsKey("step_max_delta") || exp.containsKey("sum_total");
        if (!isSeqTuning) {
            if (exp.containsKey("min")) {
                if (!Json.isFiniteNumber(actual) || !Json.isFiniteNumber(exp.get("min"))
                        || ((Number) actual).doubleValue() + 1e-9 < ((Number) exp.get("min")).doubleValue()) {
                    throw new AssertionError(pfx + ": expected then." + key + ">=" + exp.get("min") + ", got " + actual);
                }
            }
            if (exp.containsKey("max")) {
                if (!Json.isFiniteNumber(actual) || !Json.isFiniteNumber(exp.get("max"))
                        || ((Number) actual).doubleValue() - 1e-9 > ((Number) exp.get("max")).doubleValue()) {
                    throw new AssertionError(pfx + ": expected then." + key + "<=" + exp.get("max") + ", got " + actual);
                }
            }
        }
        if (exp.containsKey("min_len")) {
            int len = lengthOfValue(actual);
            int want = exp.get("min_len") instanceof Number n ? n.intValue() : Integer.MAX_VALUE;
            if (len < 0 || len < want) {
                throw new AssertionError(pfx + ": expected len(then." + key + ")>=" + exp.get("min_len") + ", got " + len);
            }
        }
        if (exp.containsKey("max_len")) {
            int len = lengthOfValue(actual);
            int want = exp.get("max_len") instanceof Number n ? n.intValue() : -1;
            if (len < 0 || len > want) {
                throw new AssertionError(pfx + ": expected len(then." + key + ")<=" + exp.get("max_len") + ", got " + len);
            }
        }
        if (exp.containsKey("non_empty")) {
            int len = lengthOfValue(actual);
            boolean wantNonEmpty = Boolean.TRUE.equals(exp.get("non_empty"));
            if (len < 0 || (wantNonEmpty ? len <= 0 : len != 0)) {
                throw new AssertionError(pfx + ": expected then." + key + ".non_empty=" + wantNonEmpty + ", got len=" + len);
            }
        }
        for (String[] fkOp : new String[][] {{"le_field", "<="}, {"ge_field", ">="}, {"eq_field", "=="}}) {
            String fk = fkOp[0];
            String op = fkOp[1];
            if (!exp.containsKey(fk)) {
                continue;
            }
            Json.PointerLookup peer = resolvePeer(payload, proj, exp.get(fk));
            if (!peer.found()) {
                throw new AssertionError(pfx + ": missing peer \"" + exp.get(fk) + "\" for then." + key + "." + fk);
            }
            boolean ok;
            if ("==".equals(op)) {
                ok = Json.valuesEqual(actual, peer.value());
            } else if (Json.isFiniteNumber(actual) && Json.isFiniteNumber(peer.value())) {
                double aVal = ((Number) actual).doubleValue();
                double pVal = ((Number) peer.value()).doubleValue();
                ok = "<=".equals(op) ? aVal - 1e-9 <= pVal : aVal + 1e-9 >= pVal;
            } else {
                ok = false;
            }
            if (!ok) {
                throw new AssertionError(pfx + ": expected then." + key + " " + op + " "
                        + exp.get(fk) + " (" + peer.value() + "), got " + actual);
            }
        }
        if (exp.containsKey("in")) {
            if (!(exp.get("in") instanceof List<?> allowed)
                    || allowed.stream().noneMatch(item -> Json.valuesEqual(actual, item))) {
                throw new AssertionError(pfx + ": expected then." + key + " in " + exp.get("in") + ", got " + actual);
            }
        }
        if (exp.containsKey("sum_fields")) {
            if (!(exp.get("sum_fields") instanceof List<?> sumRefs) || sumRefs.size() < 2) {
                throw new AssertionError(pfx + ": invalid sum_fields on then." + key);
            }
            double sum = 0.0;
            for (Object ref : sumRefs) {
                Json.PointerLookup pr = resolvePeer(payload, proj, ref);
                if (!pr.found() || !Json.isFiniteNumber(pr.value())) {
                    throw new AssertionError(pfx + ": missing numeric peer \"" + ref + "\" for then." + key + ".sum_fields");
                }
                sum += ((Number) pr.value()).doubleValue();
            }
            if (!Json.isFiniteNumber(actual) || !Double.isFinite(sum)
                    || Math.abs(((Number) actual).doubleValue() - sum) > 1e-9) {
                throw new AssertionError(pfx + ": expected then." + key + " == sum(" + sumRefs + ") (" + sum + "), got " + actual);
            }
        }
        if (exp.containsKey("contains")) {
            if (!(actual instanceof List<?> actList) || !(exp.get("contains") instanceof List<?> reqList)
                    || !reqList.stream().allMatch(req -> actList.stream().anyMatch(x -> Json.valuesEqual(x, req)))) {
                throw new AssertionError(pfx + ": expected then." + key + " to contain " + exp.get("contains") + ", got " + actual);
            }
        }
        if (exp.containsKey("prefix")) {
            String wantPfx = String.valueOf(exp.get("prefix"));
            if (!(actual instanceof String s) || !s.startsWith(wantPfx)) {
                throw new AssertionError(pfx + ": expected then." + key + " to start with \"" + wantPfx + "\", got " + actual);
            }
        }
        if (exp.containsKey("suffix")) {
            String wantSfx = String.valueOf(exp.get("suffix"));
            if (!(actual instanceof String s) || !s.endsWith(wantSfx)) {
                throw new AssertionError(pfx + ": expected then." + key + " to end with \"" + wantSfx + "\", got " + actual);
            }
        }
        Json.checkNumericAndTuningClauses(pfx, key, exp, actual, payload, proj, RELATIONAL_KEYS);
        return true;
    }

    static void checkProjectedLeaf(
            Drift.Case c,
            String key,
            Object expected,
            Object payload,
            Map<String, String> thenProj,
            boolean withAt,
            String missMsg) {
        String pfx = c.contract() + "." + c.id();
        boolean isUiObs = payload instanceof Map<?, ?> pm
                && ("drift.ui-observation/1".equals(pm.get("schema")) || pm.get("evidence") instanceof Map<?, ?>);
        if (thenProj.containsKey(key)) {
            String ptr = thenProj.get(key);
            Json.PointerLookup lookup = Json.readJsonPointer(payload, ptr);
            if (!lookup.found()) {
                throw new AssertionError(pfx + ": missing projected path \"" + ptr + "\" for then." + key);
            }
            if (isUiObs && expected != null && lookup.value() == null) {
                throw new AssertionError(pfx + ": unverifiable then." + key + ": unmeasured value at \"" + ptr + "\"");
            }
            if (checkRelationalConstraint(c, key, expected, lookup.value(), payload, thenProj)) {
                return;
            }
            if (!Json.valuesEqual(lookup.value(), expected)) {
                throw new AssertionError(pfx + ": expected then." + key + "=" + expected
                        + (withAt ? " at \"" + ptr + "\"" : "") + ", got " + lookup.value());
            }
            return;
        }
        if (payload instanceof Map<?, ?> m && m.containsKey(key)) {
            Object actual = m.get(key);
            if (isUiObs && expected != null && actual == null) {
                throw new AssertionError(pfx + ": unverifiable then." + key + ": unmeasured value");
            }
            if (checkRelationalConstraint(c, key, expected, actual, payload, thenProj)) {
                return;
            }
            if (!Json.valuesEqual(actual, expected)) {
                throw new AssertionError(pfx + ": expected then." + key + "=" + expected + ", got " + actual);
            }
            return;
        }
        if (expected instanceof Map<?, ?> expMap
                && (expMap.containsKey("allowed_keys") || expMap.containsKey("forbid_keys"))) {
            if (checkRelationalConstraint(c, key, expected, payload, payload, thenProj)) {
                return;
            }
        }
        throw new AssertionError(pfx + ": " + missMsg + " then." + key);
    }

    public static boolean isElementUnintentionallyClipped(Map<?, ?> el) {
        return DriftUiChecks.isElementUnintentionallyClipped(el);
    }

    @SuppressWarnings("unchecked")
    static void checkView(
            Drift.Case c,
            Map<String, Object> view,
            Map<String, ? extends BiConsumer<Object, Map<String, Object>>> checks) {
        String contract = c.contract();
        String id = c.id();
        Map<String, Object> then = c.thenRaw();
            Map<String, Object> v = view == null ? Map.of() : view;
            if (Boolean.FALSE.equals(v.get("surfaceFound"))
                    || Boolean.FALSE.equals(v.get("surface_found"))
                    || ("drift.ui-observation/1".equals(v.get("schema"))
                            && !Boolean.TRUE.equals(v.get("surface_found"))
                            && !Boolean.TRUE.equals(v.get("surfaceFound")))) {
                throw new AssertionError(contract + "." + id + ": surface.missing");
            }
            if ((v.get("collector") instanceof Map<?, ?> coll && Boolean.TRUE.equals(coll.get("settle_timed_out")))
                    || (v.get("evidence") instanceof Map<?, ?> ev
                            && ev.get("unverifiable_reasons") instanceof List<?> ur
                            && ur.contains("ui.settle_timeout"))) {
                throw new AssertionError(contract + "." + id + ": ui.settle_timeout");
            }
            Map<String, String> thenProj = null;
            for (Map.Entry<String, Object> e : then.entrySet()) {
                String key = e.getKey();
                Object expected = e.getValue();
                Drift.mark(contract, id, key);
                BiConsumer<Object, Map<String, Object>> custom = checks == null ? null : checks.get(key);
                if (custom != null) {
                    custom.accept(expected, v);
                    continue;
                }
                if (v.get("adapter") instanceof Map<?, ?>) {
                    if (thenProj == null) {
                        thenProj = c.projectionMap("then");
                    }
                    DriftUiChecks.checkAdapterCapability(contract, id, key, v, thenProj);
                }
                if (DriftUiChecks.checkSurfaceKey(c, key, expected, v, then, thenProj)) {
                    continue;
                }
                if ("baseline_state".equals(key)) {
                    boolean hasBaseline = v.containsKey("hasBaseline")
                            ? Boolean.TRUE.equals(v.get("hasBaseline"))
                            : v.get("baseline") != null;
                    String label = String.valueOf(v.getOrDefault("baselineLabel",
                            v.getOrDefault("deltaLabel", ""))).trim().toLowerCase();
                    if (!hasBaseline && COMPARATIVE_BASELINE_PATTERN.matcher(label).matches()) {
                        throw new AssertionError(contract + "." + id
                                + ": comparative baseline label \"" + label + "\" without baseline");
                    }
                    String actual = v.get("baseline_state") instanceof String s
                            ? s
                            : (hasBaseline ? "compared" : "first_observation");
                    if (!actual.equals(expected)) {
                        throw new AssertionError(contract + "." + id
                                + ": expected baseline_state=" + expected + ", got " + actual);
                    }
                    continue;
                }
                if ("duplicate_figures".equals(key)) {
                    List<String> figs = new ArrayList<>();
                    if (v.get("figures") instanceof List<?> rawFigs) {
                        for (Object f : rawFigs) {
                            figs.add(String.valueOf(f));
                        }
                    } else if (v.get("metrics") instanceof List<?> rawMetrics) {
                        for (Object item : rawMetrics) {
                            if (item instanceof Map<?, ?> m) {
                                Object lbl = m.containsKey("label") ? m.get("label") : m.get("metric");
                                figs.add((lbl == null ? "" : lbl) + ":" + m.get("value"));
                            }
                        }
                    }
                    long dupCount = figs.size() - new HashSet<>(figs).size();
                    long want = expected instanceof Number n ? n.longValue() : -1L;
                    if (dupCount != want) {
                        throw new AssertionError(contract + "." + id
                                + ": expected duplicate_figures=" + expected + ", got " + dupCount);
                    }
                    continue;
                }
                if ("preserved_input_on_error".equals(key)) {
                    boolean actual = !v.containsKey("preserved_input_on_error")
                            || Boolean.TRUE.equals(v.get("preserved_input_on_error"));
                    boolean hasError = Boolean.TRUE.equals(v.get("error"))
                            || (v.get("error") instanceof String s && !s.isBlank())
                            || Boolean.TRUE.equals(v.get("hasError"));
                    if (hasError && v.get("dirtyInputs") instanceof Map<?, ?> dirty) {
                        Object rawCur = v.containsKey("currentInputs") ? v.get("currentInputs") : v.get("inputs");
                        Map<?, ?> cur = rawCur instanceof Map<?, ?> m ? m : Map.of();
                        actual = true;
                        for (Map.Entry<?, ?> de : dirty.entrySet()) {
                            Object curVal = cur.get(de.getKey());
                            if (curVal == null ? de.getValue() != null : !curVal.equals(de.getValue())) {
                                actual = false;
                                break;
                            }
                        }
                    }
                    if (!Boolean.valueOf(actual).equals(expected)) {
                        throw new AssertionError(contract + "." + id
                                + ": expected preserved_input_on_error=" + expected + ", got " + actual);
                    }
                    continue;
                }
                if ("claim_matches_evidence".equals(key)) {
                    String opState = String.valueOf(v.getOrDefault("operationState",
                            v.getOrDefault("evidenceState", ""))).trim().toLowerCase();
                    String uiClaim = String.valueOf(v.getOrDefault("uiClaim",
                            v.getOrDefault("statusLabel",
                                    v.getOrDefault("completionState", "")))).trim().toLowerCase();
                    boolean claimsComplete = Boolean.TRUE.equals(v.get("claimedComplete"))
                            || TERMINAL_UI_CLAIMS.contains(uiClaim);
                    boolean actual = (!opState.isEmpty() && NON_VERIFIED_OP_STATES.contains(opState) && claimsComplete)
                            ? false
                            : (!v.containsKey("claim_matches_evidence")
                                    || Boolean.TRUE.equals(v.get("claim_matches_evidence")));
                    if (!Boolean.valueOf(actual).equals(expected)) {
                        throw new AssertionError(contract + "." + id
                                + ": expected claim_matches_evidence=" + expected + ", got " + actual);
                    }
                    continue;
                }
                if ("unobserved_controls".equals(key)) {
                    if (thenProj == null) {
                        thenProj = c.projectionMap("then");
                    }
                    List<String> ctrls = new ArrayList<>();
                    Set<String> ctrlSet = new HashSet<>();
                    if (v.get("controls") instanceof Map<?, ?> cm) {
                        for (Object ck : cm.keySet()) {
                            if (ck instanceof String s) {
                                ctrls.add(s);
                                ctrlSet.add(s);
                            }
                        }
                        Collections.sort(ctrls);
                    }
                    Set<String> obs = new HashSet<>();
                    for (String tk : c.thenRaw().keySet()) {
                        if ("unobserved_controls".equals(tk)) {
                            continue;
                        }
                        if (ctrlSet.contains(tk)) {
                            obs.add(tk);
                        }
                        String pStr = thenProj.getOrDefault(tk, "");
                        if (pStr != null && !pStr.isEmpty()) {
                            for (String seg : pStr.split("/")) {
                                if (!seg.isEmpty() && ctrlSet.contains(seg)) {
                                    obs.add(seg);
                                }
                            }
                        }
                    }
                    List<String> unobs = new ArrayList<>();
                    for (String ctrl : ctrls) {
                        if (!obs.contains(ctrl)) {
                            unobs.add(ctrl);
                        }
                    }
                    Object actUnobs = expected instanceof List<?> ? unobs : Long.valueOf(unobs.size());
                    if (!Json.valuesEqual(actUnobs, expected)) {
                        throw new AssertionError(contract + "." + id
                                + ": expected unobserved_controls=" + expected + ", got " + actUnobs + " (" + unobs + ")");
                    }
                    continue;
                }
                if (thenProj == null) {
                    thenProj = c.projectionMap("then");
                }
                checkProjectedLeaf(c, key, expected, v, thenProj, false, "no check for");
            }
    }

    static final class ThenView extends AbstractMap<String, Object> {
        private final Map<String, Object> values;
        private final Consumer<String> read;

        ThenView(Map<String, Object> values, Consumer<String> read) {
            this.values = values;
            this.read = read;
        }

        private void readAll() {
            values.keySet().forEach(read);
        }

        @Override
        public Object get(Object key) {
            Object value = values.get(key);
            if (value != null) {
                read.accept((String) key);
            }
            return value;
        }

        @Override
        public Object getOrDefault(Object key, Object fallback) {
            Object value = get(key);
            return value == null ? fallback : value;
        }

        @Override
        public boolean containsKey(Object key) {
            return values.containsKey(key);
        }

        @Override
        public int size() {
            return values.size();
        }

        @Override
        public Set<String> keySet() {
            return Collections.unmodifiableSet(values.keySet());
        }

        @Override
        public Collection<Object> values() {
            readAll();
            return Collections.unmodifiableCollection(values.values());
        }

        @Override
        public Set<Map.Entry<String, Object>> entrySet() {
            readAll();
            return Collections.unmodifiableMap(values).entrySet();
        }

        @Override
        public void forEach(BiConsumer<? super String, ? super Object> action) {
            readAll();
            values.forEach(action);
        }

        @Override
        public boolean equals(Object o) {
            readAll();
            return values.equals(o);
        }

        @Override
        public int hashCode() {
            readAll();
            return values.hashCode();
        }

        @Override
        public String toString() {
            return values.toString();
        }
    }

}

