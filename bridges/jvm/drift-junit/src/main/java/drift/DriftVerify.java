package drift;

import java.lang.annotation.Annotation;
import java.lang.reflect.Method;
import java.lang.reflect.RecordComponent;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Supports closure-based JVM suites (such as Scala 3 MUnit {@code FunSuite}) and tuple, map,
 * iterable, record or Scala {@code Product} verification without external runtime dependencies.
 */
final class DriftVerify {
    private static final ThreadLocal<String> STANDALONE_TEST_ID = new ThreadLocal<>();
    private static final ThreadLocal<String> STANDALONE_LEVEL = new ThreadLocal<>();

    private DriftVerify() {}

    static final class DynamicDriftCase implements DriftCase {
        private final String contract;
        private final String[] cases;
        private final String level;

        DynamicDriftCase(String contract, String[] cases, String level) {
            this.contract = contract;
            this.cases = cases;
            this.level = level;
        }

        @Override
        public String contract() {
            return contract;
        }

        @Override
        public String[] cases() {
            return cases;
        }

        @Override
        public String level() {
            return level;
        }

        @Override
        public Class<? extends Annotation> annotationType() {
            return DriftCase.class;
        }
    }

    static boolean isDynamicTag(DriftCase tag) {
        return tag instanceof DynamicDriftCase && !tag.contract().isEmpty();
    }

    static DriftCase closureSlot() {
        return new DynamicDriftCase("", new String[0], "");
    }

    static void preCheckExpect(
            boolean inTest,
            DriftCase existing,
            String contract,
            String caseId,
            String level) {
        if (!inTest) {
            return;
        }
        if (existing == null) {
            if (level == null || level.isBlank()) {
                throw new IllegalStateException("the running test has no @DriftCase and cannot read "
                        + contract + "." + caseId);
            }
            return;
        }
        if (!(existing instanceof DynamicDriftCase)) {
            if (!existing.contract().equals(contract) || !List.of(existing.cases()).contains(caseId)) {
                throw new IllegalStateException("the running test is tagged " + existing.contract() + " "
                        + List.of(existing.cases()) + " and cannot read " + contract + "." + caseId);
            }
        }
    }

    static String inferLevel(String explicitLevel, DriftCase currentTag, Map<String, Object> caseMap) {
        if (explicitLevel != null && !explicitLevel.isBlank()) {
            return explicitLevel.trim();
        }
        if (caseMap.get("at") instanceof List<?> atList
                && !atList.isEmpty()
                && atList.get(0) instanceof String firstAt
                && !firstAt.isBlank()) {
            return firstAt;
        }
        if (currentTag != null && currentTag.level() != null && !currentTag.level().isBlank()) {
            return currentTag.level();
        }
        return "unit";
    }

    static void bindExpect(
            boolean inTest,
            ThreadLocal<DriftCase> tagLocal,
            String contract,
            String caseId,
            String level,
            Map<String, Object> caseMap) {
        DriftCase existing = tagLocal.get();
        if (inTest && existing != null && !(existing instanceof DynamicDriftCase)) {
            return;
        }
        String effLevel = inferLevel(level, existing, caseMap);
        if (existing instanceof DynamicDriftCase dyn && dyn.contract().equals(contract)) {
            Set<String> merged = new LinkedHashSet<>(Arrays.asList(dyn.cases()));
            merged.add(caseId);
            tagLocal.set(new DynamicDriftCase(contract, merged.toArray(String[]::new), effLevel));
        } else {
            tagLocal.set(new DynamicDriftCase(contract, new String[] {caseId}, effLevel));
        }
        STANDALONE_LEVEL.set(effLevel);
        if (!inTest && STANDALONE_TEST_ID.get() == null) {
            STANDALONE_TEST_ID.set(resolveCallerTestId(caseId));
        }
    }

    static void clearStandalone() {
        STANDALONE_TEST_ID.remove();
        STANDALONE_LEVEL.remove();
    }

    private static String resolveCallerTestId(String fallbackCaseId) {
        return StackWalker.getInstance(StackWalker.Option.RETAIN_CLASS_REFERENCE)
                .walk(frames -> frames
                        .filter(f -> !f.getClassName().startsWith("drift.")
                                && !f.getClassName().startsWith("java.")
                                && !f.getClassName().startsWith("jdk.")
                                && !f.getClassName().startsWith("org.junit."))
                        .findFirst()
                        .map(f -> {
                            String cls = f.getClassName();
                            if (cls.endsWith("$")) {
                                cls = cls.substring(0, cls.length() - 1);
                            }
                            String m = f.getMethodName();
                            if (m == null || m.isEmpty() || "<init>".equals(m)
                                    || m.contains("$anonfun") || m.contains("lambda$")) {
                                m = fallbackCaseId;
                            }
                            return cls + "#" + m;
                        })
                        .orElse("ScalaSuite#" + fallbackCaseId));
    }

    static void verify(Drift.Case c, Object... entries) {
        Map<String, Object> payload = toPayloadMap(entries);
        Map<String, String> thenProj = c.projectionMap("then");
        Map<String, Object> rawThen = c.thenRaw();
        boolean standalone = !Boolean.TRUE.equals(Drift.inTest()) && !Drift.mutationRun();
        String testId = standalone
                ? (STANDALONE_TEST_ID.get() != null ? STANDALONE_TEST_ID.get() : resolveCallerTestId(c.id()))
                : null;
        String level = STANDALONE_LEVEL.get() != null ? STANDALONE_LEVEL.get() : "unit";
        try {
            for (Map.Entry<String, Object> e : rawThen.entrySet()) {
                String key = e.getKey();
                Object expected = e.getValue();
                Drift.mark(c.contract(), c.id(), key);
                if (thenProj.containsKey(key) && Json.readJsonPointer(payload, thenProj.get(key)).found()) {
                    DriftViewChecks.checkProjectedLeaf(
                            c, key, expected, payload, thenProj, true, "no check or projection for");
                } else if (payload.containsKey(key)) {
                    DriftViewChecks.checkProjectedLeaf(
                            c, key, expected, payload, Map.of(), false, "no check or projection for");
                } else {
                    DriftViewChecks.checkProjectedLeaf(
                            c, key, expected, payload, thenProj, true, "no check or projection for");
                }
            }
            if (standalone) {
                DriftListener.recordStandaloneEvent(
                        testId, c.contract(), List.of(c.id()), level, "passed", List.of(c.id()));
            }
        } catch (Throwable err) {
            if (standalone) {
                DriftListener.recordStandaloneEvent(
                        testId, c.contract(), List.of(c.id()), level, "failed", List.of());
            }
            throw err;
        }
    }

    static Map<String, Object> toPayloadMap(Object... entries) {
        if (entries == null || entries.length == 0) {
            return Map.of();
        }
        if (entries.length == 1 && !isPairLike(entries[0])) {
            Object single = normalizeValue(entries[0]);
            if (single instanceof Map<?, ?> m) {
                Map<String, Object> out = new LinkedHashMap<>();
                for (Map.Entry<?, ?> e : m.entrySet()) {
                    out.put(String.valueOf(e.getKey()), e.getValue());
                }
                return out;
            }
            throw new IllegalArgumentException("verify expects key-value pairs, a Map, or a Product/Record");
        }
        boolean allPairs = true;
        for (Object item : entries) {
            if (!isPairLike(item)) {
                allPairs = false;
                break;
            }
        }
        if (allPairs) {
            Map<String, Object> out = new LinkedHashMap<>();
            for (Object item : entries) {
                Object[] kv = extractPair(item);
                out.put(String.valueOf(kv[0]), normalizeValue(kv[1]));
            }
            return out;
        }
        if (entries.length % 2 == 0) {
            Map<String, Object> out = new LinkedHashMap<>();
            for (int i = 0; i < entries.length; i += 2) {
                out.put(String.valueOf(entries[i]), normalizeValue(entries[i + 1]));
            }
            return out;
        }
        throw new IllegalArgumentException("verify expects (key -> value) tuples, a Map/Product, or even key/value arguments");
    }

    private static boolean isPairLike(Object obj) {
        if (obj == null) {
            return false;
        }
        if (obj instanceof Map.Entry<?, ?>) {
            return true;
        }
        Class<?> cls = obj.getClass();
        try {
            cls.getMethod("_1");
            cls.getMethod("_2");
            return true;
        } catch (NoSuchMethodException e) {
            return false;
        }
    }

    private static Object[] extractPair(Object obj) {
        if (obj instanceof Map.Entry<?, ?> e) {
            return new Object[] {e.getKey(), e.getValue()};
        }
        try {
            Class<?> cls = obj.getClass();
            Object k = cls.getMethod("_1").invoke(obj);
            Object v = cls.getMethod("_2").invoke(obj);
            return new Object[] {k, v};
        } catch (ReflectiveOperationException e) {
            throw new IllegalArgumentException("cannot read tuple (_1, _2) from " + obj, e);
        }
    }

    static Object normalizeValue(Object val) {
        if (val == null || val instanceof String || val instanceof Number || val instanceof Boolean) {
            return val;
        }
        if (val instanceof Map<?, ?> m) {
            Map<String, Object> out = new LinkedHashMap<>();
            for (Map.Entry<?, ?> e : m.entrySet()) {
                out.put(String.valueOf(e.getKey()), normalizeValue(e.getValue()));
            }
            return out;
        }
        if (val instanceof Iterable<?> it) {
            return normalizeIterator(it.iterator());
        }
        Class<?> cls = val.getClass();
        if (cls.isRecord()) {
            Map<String, Object> out = new LinkedHashMap<>();
            try {
                for (RecordComponent rc : cls.getRecordComponents()) {
                    out.put(rc.getName(), normalizeValue(rc.getAccessor().invoke(val)));
                }
                return out;
            } catch (ReflectiveOperationException e) {
                throw new IllegalArgumentException("cannot inspect record " + cls.getName(), e);
            }
        }
        try {
            Method iterMethod = cls.getMethod("iterator");
            Object iterObj = iterMethod.invoke(val);
            if (iterObj instanceof Iterator<?> it) {
                return normalizeIterator(it);
            }
            if (iterObj != null) {
                Method hasNext = iterObj.getClass().getMethod("hasNext");
                Method next = iterObj.getClass().getMethod("next");
                List<Object> items = new ArrayList<>();
                while (Boolean.TRUE.equals(hasNext.invoke(iterObj))) {
                    items.add(next.invoke(iterObj));
                }
                return normalizeItems(items);
            }
        } catch (ReflectiveOperationException ignored) {
        }
        if (!isPairLike(val)) {
            try {
                Method arityM = cls.getMethod("productArity");
                Method nameM = cls.getMethod("productElementName", int.class);
                Method elemM = cls.getMethod("productElement", int.class);
                int n = (int) arityM.invoke(val);
                Map<String, Object> out = new LinkedHashMap<>();
                for (int i = 0; i < n; i++) {
                    String name = String.valueOf(nameM.invoke(val, i));
                    out.put(name, normalizeValue(elemM.invoke(val, i)));
                }
                return out;
            } catch (ReflectiveOperationException ignored) {
            }
        }
        return val;
    }

    private static Object normalizeIterator(Iterator<?> it) {
        List<Object> items = new ArrayList<>();
        while (it.hasNext()) {
            items.add(it.next());
        }
        return normalizeItems(items);
    }

    private static Object normalizeItems(List<Object> items) {
        if (!items.isEmpty() && items.stream().allMatch(DriftVerify::isPairLike)) {
            Map<String, Object> map = new LinkedHashMap<>();
            for (Object item : items) {
                Object[] kv = extractPair(item);
                map.put(String.valueOf(kv[0]), normalizeValue(kv[1]));
            }
            return map;
        }
        List<Object> out = new ArrayList<>(items.size());
        for (Object item : items) {
            out.add(normalizeValue(item));
        }
        return out;
    }

    static Map<String, String> projectionMap(String contract, String side) {
        Object raw = Drift.view(contract).get("projections");
        if (!(raw instanceof Map<?, ?> rawMap)) {
            return Map.of();
        }
        Map<String, String> out = new LinkedHashMap<>();
        for (Map.Entry<?, ?> e : rawMap.entrySet()) {
            if (e.getKey() instanceof String k
                    && !"when".equals(k)
                    && !"then".equals(k)
                    && e.getValue() instanceof String v) {
                out.put(k, v);
            }
        }
        if (rawMap.get(side) instanceof Map<?, ?> sideMap) {
            for (Map.Entry<?, ?> e : sideMap.entrySet()) {
                if (e.getKey() instanceof String k && e.getValue() instanceof String v) {
                    out.put(k, v);
                }
            }
        }
        return out;
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> buildOutput(Drift.Case c, Map<String, Object> base) {
        Drift.recordSelfStub(c.contract());
        Map<String, String> whenProj = c.projectionMap("when");
        Map<String, String> thenProj = c.projectionMap("then");
        Map<String, Object> peerIdx = DriftStubs.buildPeerIndex(c.when(), c.thenRaw(), whenProj, thenProj);
        Object out = Json.cloneJsonValue(base == null ? Map.of() : base);
        for (Map.Entry<String, Object> e : c.thenRaw().entrySet()) {
            String key = e.getKey();
            Object w = DriftStubs.witnessVariants(e.getValue(), out, peerIdx, whenProj, thenProj).get(0);
            if (thenProj.containsKey(key)) {
                out = Json.writeJsonPointer(out, thenProj.get(key), w);
            } else if (out instanceof Map<?, ?> m) {
                ((Map<String, Object>) m).put(key, w);
            }
        }
        return out instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
    }

    static <V> void checkAdverse(
            Drift.Case c,
            List<V> variants,
            java.util.function.Function<V, Object> execute,
            Map<String, ? extends java.util.function.Consumer<Object>> checks) {
        if (variants == null || variants.isEmpty() || execute == null) {
            throw new IllegalArgumentException(
                    "checkAdverse for " + c.contract() + "." + c.id()
                            + " requires non-empty variants and an execute callback");
        }
        Map<String, String> whenProj = c.projectionMap("when");
        String pfx = c.contract() + "." + c.id();
        for (V variant : variants) {
            DriftProbes.checkBolaVariantPair(pfx, variant);
            if (variant instanceof Map<?, ?>) {
                for (Map.Entry<String, Object> we : c.when().entrySet()) {
                    String wk = we.getKey();
                    String ptr = whenProj.getOrDefault(wk, "/" + wk.replace("~", "~0").replace("/", "~1"));
                    Json.PointerLookup rd = Json.readJsonPointer(variant, ptr);
                    if (rd.found() && !Json.valuesEqual(rd.value(), we.getValue())) {
                        throw new AssertionError(c.contract() + "." + c.id() + ".when." + wk
                                + " fixture mismatch: expected " + we.getValue() + ", got " + rd.value());
                    }
                }
            }
            c.checkProjection(execute.apply(variant), checks);
        }
    }

    static List<String> forbiddenWritesOf(Map<String, Object> view, String caseId) {
        return DriftUiChecks.forbiddenWritesOf(view, caseId);
    }

    static boolean allFramesRead(Map<String, Object> view, String caseId, Set<String> seen) {
        for (String fr : forbiddenWritesOf(view, caseId)) {
            if (!seen.contains("@frame:" + fr)) {
                return false;
            }
        }
        return true;
    }

    static void checkFrame(Drift.Case c, Map<String, Object> frameObs) {
        DriftUiChecks.checkFrame(c, frameObs);
    }

    static boolean checkObjectKeysAndNotIn(String pfx, String key, Map<?, ?> exp, Object actual) {
        if (exp.containsKey("allowed_keys") || exp.containsKey("forbid_keys")) {
            if (!(actual instanceof Map<?, ?> actMap)) {
                throw new AssertionError(pfx + ": expected object for then." + key + ", got " + actual);
            }
            if (exp.containsKey("allowed_keys")) {
                if (!(exp.get("allowed_keys") instanceof List<?> allowedList)) {
                    throw new AssertionError(pfx + ": invalid allowed_keys on then." + key);
                }
                Set<String> allowedSet = new LinkedHashSet<>();
                for (Object item : allowedList) {
                    allowedSet.add(String.valueOf(item));
                }
                for (Object actKey : actMap.keySet()) {
                    String ak = String.valueOf(actKey);
                    if ("_frame".equals(ak) && actMap.get(actKey) instanceof Map<?, ?>) {
                        continue;
                    }
                    if (!allowedSet.contains(ak)) {
                        throw new AssertionError(pfx + ": unexpected key \"" + actKey + "\" outside allowed_keys " + allowedList);
                    }
                }
            }
            if (exp.containsKey("forbid_keys")) {
                Object fkObj = exp.get("forbid_keys");
                if (fkObj instanceof List<?> forbidList) {
                    for (Object fk : forbidList) {
                        if (DriftProbes.hasKeyRecursive(actMap, String.valueOf(fk), true)) {
                            throw new AssertionError(pfx + ": forbidden key \"" + fk + "\" present on then." + key);
                        }
                    }
                } else if (fkObj instanceof String fkStr) {
                    if (!DriftProbes.hasKeyRecursive(actMap, fkStr, true)) {
                        throw new AssertionError(pfx + ": drop-forbid-key mutant on then." + key + ".forbid_keys killed");
                    }
                } else {
                    throw new AssertionError(pfx + ": invalid forbid_keys on then." + key);
                }
            }
        }
        if (exp.containsKey("not_in")) {
            if (actual == null) {
                throw new AssertionError(pfx + ": expected non-null value for then." + key + ".not_in");
            }
            Object niObj = exp.get("not_in");
            if (niObj instanceof List<?> forbiddenList) {
                if (forbiddenList.stream().anyMatch(item -> Json.valuesEqual(actual, item))) {
                    throw new AssertionError(pfx + ": forbidden value " + actual + " in then." + key + ".not_in " + forbiddenList);
                }
            } else if (!Json.valuesEqual(actual, niObj)) {
                throw new AssertionError(pfx + ": pick-forbidden-value mutant on then." + key + ".not_in killed");
            }
        }
        return false;
    }

    public static final Set<String> CAPABILITIES = Set.of(
            "allowed_keys",
            "case_frames",
            "counterexample_replay",
            "forbid_keys",
            "inventory_sidecar",
            "mutants",
            "not_in",
            "predicates",
            "projections",
            "relational_bounds",
            "stubs");

    public static Map<String, Object> bridgeCapabilities() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("bridge", "drift-junit");
        out.put("capabilities", new ArrayList<>(new java.util.TreeSet<>(CAPABILITIES)));
        out.put("runtime_baseline", "java-25-lts");
        out.put("schema", "drift.bridge-capabilities/1");
        out.put("version", "0.7.0");
        return out;
    }

    public static void requireCapabilities(java.util.Collection<String> required) {
        if (required == null) {
            throw new IllegalStateException("bridge.capability_unsupported:null");
        }
        for (String cap : required) {
            if (cap == null || cap.isBlank() || !CAPABILITIES.contains(cap.trim())) {
                throw new IllegalStateException("bridge.capability_unsupported:" + (cap == null ? "" : cap.trim()));
            }
        }
    }

    @SuppressWarnings("unchecked")
    public static int replayCounterexamples(
            Drift.Case c,
            java.nio.file.Path cexDirOrFile,
            java.util.function.Function<Map<String, Object>, Object> sut) {
        if (cexDirOrFile == null || !java.nio.file.Files.exists(cexDirOrFile)) {
            return 0;
        }
        List<java.nio.file.Path> files = new ArrayList<>();
        if (java.nio.file.Files.isDirectory(cexDirOrFile)) {
            try (var stream = java.nio.file.Files.list(cexDirOrFile)) {
                stream.filter(p -> p.getFileName().toString().endsWith(".cex.json"))
                        .sorted()
                        .forEach(files::add);
            } catch (java.io.IOException e) {
                throw new IllegalStateException("cannot list counterexample directory " + cexDirOrFile, e);
            }
        } else if (cexDirOrFile.getFileName().toString().endsWith(".cex.json")) {
            files.add(cexDirOrFile);
        }
        int replayed = 0;
        for (java.nio.file.Path f : files) {
            final Object parsed;
            try {
                parsed = Json.read(f);
            } catch (java.io.IOException e) {
                throw new java.io.UncheckedIOException("cannot read counterexample fixture " + f, e);
            }
            if (!(parsed instanceof Map<?, ?> raw)) {
                throw new IllegalStateException("invalid counterexample fixture " + f);
            }
            Map<String, Object> doc = (Map<String, Object>) raw;
            if (!c.contract().equals(doc.get("contract"))) {
                continue;
            }
            String targetCase = doc.get("case") instanceof String s ? s : "";
            if (!targetCase.isEmpty() && !c.id().equals(targetCase)) {
                continue;
            }
            Object witObj = doc.get("witness");
            if (!(witObj instanceof Map<?, ?> witMap) || !(witMap.get("when") instanceof Map<?, ?> whenRaw)) {
                throw new IllegalStateException("counterexample fixture " + f + " is missing witness.when");
            }
            Drift.recordInput(f);
            Object actual = sut.apply((Map<String, Object>) whenRaw);
            c.checkProjection(actual);
            replayed++;
        }
        return replayed;
    }
}
