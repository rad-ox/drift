package drift;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.AbstractMap;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.TreeMap;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.BiConsumer;
import java.util.function.Consumer;
import java.util.stream.Stream;

/**
 * Reads the resolved view of a contract, as written by {@code drift show <file> --as json}
 * into the directory named by the system property {@code drift.resolved}. The listener reports
 * a case as read, and so verified rather than only bound, when the test read every one of its
 * {@code then} values.
 */
public final class Drift {
    public static final String RESOLVED = "drift.resolved";

    private static final Map<String, Map<String, Object>> VIEWS = new ConcurrentHashMap<>();
    private static final Map<Path, String> INPUT_DIGESTS = new ConcurrentHashMap<>();
    private static final ThreadLocal<Set<String>> READS = ThreadLocal.withInitial(HashSet::new);
    private static final ThreadLocal<Map<String, Set<String>>> THEN_READS = ThreadLocal.withInitial(HashMap::new);
    private static final ThreadLocal<Map<String, String>> TEST_INPUTS = ThreadLocal.withInitial(TreeMap::new);
    private static final ThreadLocal<Map<Path, String>> TEST_INPUT_PATHS = ThreadLocal.withInitial(HashMap::new);
    private static final ThreadLocal<DriftCase> TAG = new ThreadLocal<>();
    private static final ThreadLocal<Boolean> IN_TEST = new ThreadLocal<>();
    private static final ThreadLocal<Deque<DriftInternal.MutationOverride>> MUTATION =
            ThreadLocal.withInitial(ArrayDeque::new);
    private static final ThreadLocal<Path> MUTATION_RESOLVED = new ThreadLocal<>();
    private static final ThreadLocal<Boolean> MUTATION_RUN = new ThreadLocal<>();

    private Drift() {}

    /** Returns one case of the contract; the read is recorded for the running test. */
    public static Case expect(String contract, String caseId) {
        return expect(contract, caseId, null);
    }

    /** Returns one case of the contract at an explicit level; auto-binds unannotated/closure tests. */
    public static Case expect(String contract, String caseId, String level) {
        DriftVerify.preCheckExpect(Boolean.TRUE.equals(IN_TEST.get()), TAG.get(), contract, caseId, level);
        Map<String, Object> cases = DriftInternal.map(view(contract).get("cases"), contract + ".cases");
        Object c = cases.get(caseId);
        if (c == null) {
            throw new IllegalArgumentException("contract " + contract + " has no case " + caseId);
        }
        Map<String, Object> m = DriftInternal.map(c, contract + ".cases." + caseId);
        DriftVerify.bindExpect(Boolean.TRUE.equals(IN_TEST.get()), TAG, contract, caseId, level, m);
        READS.get().add(contract + "\u0000" + caseId);
        Map<String, Object> when = DriftInternal.map(m.getOrDefault("when", Map.of()), "when");
        Map<String, Object> then = DriftInternal.map(m.getOrDefault("then", Map.of()), "then");
        DriftInternal.MutationOverride override = activeMutation(contract, caseId);
        if (override != null) {
            if (override.isWhen()) {
                when = override.applyWhen(when);
            } else {
                then = override.apply(then);
            }
        }
        return new Case(contract, caseId, when, then);
    }

    /** Iterates over every case tagged on the running test (or every case of {@code contract}) and passes its {@link Case}. */
    public static void forEachCase(String contract, Consumer<Case> action) {
        DriftCase tag = Boolean.TRUE.equals(IN_TEST.get()) ? TAG.get() : null;
        Collection<String> ids = (tag != null && tag.contract().equals(contract))
                ? List.of(tag.cases())
                : DriftInternal.map(view(contract).get("cases"), contract + ".cases").keySet();
        for (String cid : ids) {
            action.accept(expect(contract, cid));
        }
    }

    private static DriftInternal.MutationOverride activeMutation(String contract, String caseId) {
        for (DriftInternal.MutationOverride ov : MUTATION.get()) {
            if (ov.contract().equals(contract) && ov.caseId().equals(caseId)) {
                return ov;
            }
        }
        return null;
    }

    /** True when the resolved view of the contract exists in {@code drift.resolved}. */
    static boolean hasContract(String contract) {
        try {
            view(contract);
            return true;
        } catch (RuntimeException e) {
            return false;
        }
    }

    /** The version the events name: the reference of the resolved view, else its digest, else null. */
    static String digest(String contract) {
        try {
            Map<String, Object> view = view(contract);
            if (view.get("ref") instanceof String ref && !ref.isEmpty()) {
                return ref;
            }
            return view.get("digest") instanceof String s ? s : null;
        } catch (RuntimeException e) {
            return null;
        }
    }

    static boolean isSchema03(String contract) {
        try {
            return "0.3".equals(view(contract).get("drift"));
        } catch (RuntimeException e) {
            return false;
        }
    }

    static boolean isExplicitSchema02(String contract) {
        try {
            return "0.2".equals(view(contract).get("drift"));
        } catch (RuntimeException e) {
            return false;
        }
    }

    static List<String> requiredCapabilities(String contract) {
        List<String> supported03 = List.of(
                "rel-keys-guard/1", "rel-linear-balance/1", "rel-peer-sum/1",
                "rel-series/1", "rel-tol/1", "unit-conversion/1");
        final Map<String, Object> v;
        try {
            v = view(contract);
        } catch (RuntimeException e) {
            return supported03;
        }
        Object raw = v.get("required_capabilities");
        if (raw instanceof List<?> list) {
            for (Object item : list) {
                if (item instanceof String s && !supported03.contains(s)) {
                    throw new IllegalStateException("bridge.capability_unsupported:" + s);
                }
            }
        }
        return supported03;
    }

    /** True when the running test read every {@code then} value and required frame of the case. */
    static boolean read(String contract, String caseId) {
        String key = contract + "\u0000" + caseId;
        if (!READS.get().contains(key)) {
            return false;
        }
        Map<String, Object> v = view(contract);
        Map<String, Object> c = DriftInternal.map(DriftInternal.map(v.get("cases"), contract + ".cases").get(caseId),
                contract + ".cases." + caseId);
        Set<String> seen = THEN_READS.get().getOrDefault(key, Set.of());
        return seen.containsAll(DriftInternal.map(c.getOrDefault("then", Map.of()), "then").keySet())
                && DriftVerify.allFramesRead(v, caseId, seen);
    }

    static void mark(String contract, String caseId, String predicate) {
        THEN_READS.get().computeIfAbsent(contract + "\u0000" + caseId, k -> new HashSet<>()).add(predicate);
    }

    static void unmarkCase(String contract, String caseId) {
        THEN_READS.get().remove(contract + "\u0000" + caseId);
    }

    /** Records a file read by the running test for proof-key and selection tracking. */
    public static String recordInput(Path file) {
        Path cwd = Path.of("").toAbsolutePath().normalize();
        Path abs = file.isAbsolute() ? file.normalize() : cwd.resolve(file).normalize();
        String rel = abs.startsWith(cwd)
                ? cwd.relativize(abs).toString().replace('\\', '/')
                : file.toString().replace('\\', '/');
        String sig = DriftInternal.fileSignature(abs);
        String cached = INPUT_DIGESTS.get(abs);
        String digest;
        if (cached != null && sig.startsWith("L:") && cached.startsWith(sig + "|")) {
            digest = cached.substring(sig.length() + 1);
        } else {
            digest = DriftInternal.sha256File(abs);
            INPUT_DIGESTS.put(abs, sig + "|" + digest);
        }
        if (!mutationRun()) {
            TEST_INPUTS.get().put(rel, digest);
            TEST_INPUT_PATHS.get().put(abs, sig + "|" + digest);
        }
        return digest;
    }

    static boolean inputsUnchanged() {
        return ExecutionContext.inputsUnchanged(TEST_INPUT_PATHS.get());
    }

    static Map<String, String> recordedInputs() {
        return new TreeMap<>(TEST_INPUTS.get());
    }

    static void recordSelfStub(String contract) {
        if (Boolean.TRUE.equals(IN_TEST.get()) && !mutationRun()) {
            TEST_INPUTS.get().put(".drift/self-stub/" + contract, "sha256:self-stub");
        }
    }

    static void recordSeamStub(String producer, String caseId, String ref) {
        if (Boolean.TRUE.equals(IN_TEST.get()) && !mutationRun()) {
            TEST_INPUTS.get().put(".drift/seam-stub/" + producer + "#" + caseId, ref);
        }
    }

    /** A test starts on this thread; a null tag marks an untagged test. */
    static void begin(DriftCase tag) {
        READS.get().clear();
        THEN_READS.get().clear();
        TEST_INPUTS.get().clear();
        TEST_INPUT_PATHS.get().clear();
        if (!mutationRun()) {
            MUTATION.get().clear();
        }
        TAG.set(tag);
        IN_TEST.set(Boolean.TRUE);
    }

    /** The tag of the test currently running on this thread, or null. */
    static DriftCase tag() {
        return TAG.get();
    }

    static Boolean inTest() {
        return IN_TEST.get();
    }

    /** Flushes any standalone programmatic proof events and inventory sidecars to disk. */
    public static void flushEvents() {
        DriftListener.flushStandaloneEvents();
    }

    /** No test runs on this thread any more; its reads stay until the next begin. */
    static void end() {
        TAG.remove();
        IN_TEST.remove();
        DriftVerify.clearStandalone();
    }

    static void setMutation(String contract, String caseId, String path, Object value) {
        MUTATION.get().push(DriftInternal.MutationOverride.of(contract, caseId, path, value));
    }

    /** Returns the current per-thread mutation override stack depth. */
    public static int mutationDepth() {
        return MUTATION.get().size();
    }

    /** Runs {@code action} under a scoped mutation override on this thread's arbiter stack. */
    public static void withMutation(String contract, String caseId, String path, Object value, Runnable action) {
        Deque<DriftInternal.MutationOverride> stack = MUTATION.get();
        int before = stack.size();
        stack.push(DriftInternal.MutationOverride.of(contract, caseId, path, value));
        try {
            action.run();
        } finally {
            if (!stack.isEmpty()) {
                stack.pop();
            }
            if (stack.size() != before) {
                stack.clear();
                throw new IllegalStateException("unbalanced mutation override stack");
            }
        }
    }

    static void beginMutationRun(Path resolved) {
        MUTATION.get().clear();
        MUTATION_RESOLVED.set(resolved.toAbsolutePath().normalize());
        MUTATION_RUN.set(Boolean.TRUE);
    }

    static void endMutationRun() {
        MUTATION.remove();
        MUTATION_RESOLVED.remove();
        MUTATION_RUN.remove();
    }

    static boolean mutationRun() {
        return Boolean.TRUE.equals(MUTATION_RUN.get()) || !MUTATION.get().isEmpty();
    }

    static boolean isMutatingThen(String contract, String caseId, String key) {
        for (DriftInternal.MutationOverride ov : MUTATION.get()) {
            if (!ov.isWhen()
                    && ov.contract().equals(contract)
                    && ov.caseId().equals(caseId)
                    && ov.segments().length > 0
                    && ov.segments()[0].equals(key)) {
                return true;
            }
        }
        return false;
    }

    static void clearMutation() {
        Deque<DriftInternal.MutationOverride> stack = MUTATION.get();
        if (!stack.isEmpty()) {
            stack.pop();
        }
    }

    static void clearViews() {
        VIEWS.clear();
        INPUT_DIGESTS.clear();
        DriftInternal.clearCache();
    }

    public static List<Long> intDomain(long min, long max) {
        return DriftInternal.intDomain(min, max);
    }

    public static List<String> enumDomain(String... values) {
        return DriftInternal.enumDomain(values);
    }

    public static List<Boolean> boolDomain() {
        return DriftInternal.boolDomain();
    }

    public static List<Map<String, Object>> cartesianDomain(Map<String, ? extends List<?>> domains) {
        return DriftInternal.cartesianDomain(domains);
    }

    public static List<Object> profileDomain(String contract, String param) {
        return DriftInternal.profileDomain(contract, param);
    }

    public static List<Map<String, Object>> profileDomain(String contract, Collection<String> params) {
        return DriftInternal.profileDomain(contract, params);
    }

    public static Map<String, Object> stub(String contractOrResource, String caseId) {
        return DriftStubs.buildStub(contractOrResource, caseId, Map.of(), Boolean.TRUE.equals(IN_TEST.get()));
    }

    public static Map<String, Object> stub(String contractOrResource, String caseId, Map<String, Object> base) {
        return DriftStubs.buildStub(contractOrResource, caseId, base, Boolean.TRUE.equals(IN_TEST.get()));
    }

    public static Map<String, Object> stub(String contractOrResource, Map<String, Object> whenInput) {
        return DriftStubs.buildStubByWhen(contractOrResource, whenInput, Map.of(), Boolean.TRUE.equals(IN_TEST.get()));
    }

    public static Map<String, Object> stub(String contractOrResource, Map<String, Object> whenInput, Map<String, Object> base) {
        return DriftStubs.buildStubByWhen(contractOrResource, whenInput, base, Boolean.TRUE.equals(IN_TEST.get()));
    }

    public static List<Map<String, Object>> stubVariants(String contractOrResource, String caseId) {
        return DriftStubs.buildStubVariants(contractOrResource, caseId, Map.of(), Boolean.TRUE.equals(IN_TEST.get()));
    }

    public static List<Map<String, Object>> stubVariants(String contractOrResource, String caseId, Map<String, Object> base) {
        return DriftStubs.buildStubVariants(contractOrResource, caseId, base, Boolean.TRUE.equals(IN_TEST.get()));
    }

    public static List<Map<String, Object>> stubVariants(String contractOrResource, Map<String, Object> whenInput) {
        return DriftStubs.buildStubVariantsByWhen(contractOrResource, whenInput, Map.of(), Boolean.TRUE.equals(IN_TEST.get()));
    }

    public static List<Map<String, Object>> stubVariants(String contractOrResource, Map<String, Object> whenInput, Map<String, Object> base) {
        return DriftStubs.buildStubVariantsByWhen(contractOrResource, whenInput, base, Boolean.TRUE.equals(IN_TEST.get()));
    }

    public static boolean verifyStub(String contractOrResource, String caseId, Object payload) {
        return DriftStubs.verifyStub(contractOrResource, caseId, payload, Boolean.TRUE.equals(IN_TEST.get()));
    }

    public static boolean verifyStub(String contractOrResource, Map<String, Object> whenInput, Object payload) {
        return DriftStubs.verifyStubByWhen(contractOrResource, whenInput, payload, Boolean.TRUE.equals(IN_TEST.get()));
    }

    public static boolean observe(String contract, String caseId, String test, Map<String, Object> when, Map<String, Object> then) {
        return DriftSelect.observe(contract, caseId, test, when, then);
    }

    static Map<String, Object> view(String contract) {
        Path override = MUTATION_RESOLVED.get();
        String dir = override == null ? System.getProperty(RESOLVED) : override.toString();
        if (dir == null || dir.isBlank()) {
            String env = System.getenv("DRIFT_RESOLVED");
            if (env != null && !env.isBlank()) {
                dir = env;
            }
        }
        if (dir == null || dir.isBlank()) {
            String autoKey = "<auto>\u0000" + contract;
            return VIEWS.computeIfAbsent(autoKey, ignored -> DriftInternal.autoResolve(contract));
        }
        String key = dir + "\u0000" + contract;
        String resolvedDir = dir;
        return VIEWS.computeIfAbsent(key, ignored -> DriftInternal.load(contract, resolvedDir));
    }

    /**
     * One resolved case: its when and then tables. Reading a {@code then} value, through
     * {@link #then(String)}, a typed reader, {@link #findThen(String)}, {@link #check(Map)} or
     * the values of {@link #then()}, counts as reading it; keys alone do not.
     */
    public record Case(String contract, String id, Map<String, Object> when, Map<String, Object> then) {
        private Object unwrap03(Object v) {
            return (!Drift.isExplicitSchema02(contract) && v instanceof Map<?, ?> m && m.size() == 1 && m.containsKey("eq"))
                    ? m.get("eq")
                    : v;
        }

        public Object when(String key) {
            return unwrap03(need(when, "when", key));
        }

        public Object then(String key) {
            Object value = need(then, "then", key);
            Drift.mark(contract, id, key);
            return unwrap03(value);
        }

        /** The then table; reading its values counts as reading them, its keys do not. */
        @Override
        public Map<String, Object> then() {
            return new DriftViewChecks.ThenView(then, key -> Drift.mark(contract, id, key));
        }

        /** The when value, or empty when the case has no such predicate. */
        public Optional<Object> findWhen(String key) {
            return Optional.ofNullable(unwrap03(when.get(key)));
        }

        /** Returns a defensive copy of the case's {@code when} table (including any active {@code --when} mutation). */
        @SuppressWarnings("unchecked")
        public Map<String, Object> whenTable() {
            Object cloned = Json.cloneJsonValue(when);
            return cloned instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
        }

        /** The then value, or empty when the case has no such predicate. */
        public Optional<Object> findThen(String key) {
            Object value = then.get(key);
            if (value != null) {
                Drift.mark(contract, id, key);
            }
            return Optional.ofNullable(unwrap03(value));
        }

        public String whenString(String key) {
            return (String) when(key);
        }

        public boolean whenBoolean(String key) {
            return (Boolean) when(key);
        }

        public int whenInt(String key) {
            return Math.toIntExact(((Number) when(key)).longValue());
        }

        public String thenString(String key) {
            return (String) then(key);
        }

        public boolean thenBoolean(String key) {
            return (Boolean) then(key);
        }

        public int thenInt(String key) {
            return Math.toIntExact(((Number) then(key)).longValue());
        }

        public long thenLong(String key) {
            return ((Number) then(key)).longValue();
        }

        @SuppressWarnings("unchecked")
        public List<Object> thenList(String key) {
            return (List<Object>) then(key);
        }

        @SuppressWarnings("unchecked")
        public Map<String, Object> thenMap(String key) {
            return (Map<String, Object>) then(key);
        }

        public void verify(Object... entries) {
            DriftVerify.verify(this, entries);
        }

        public void check(Map<String, ? extends Consumer<Object>> checks) {
            for (Map.Entry<String, Object> e : thenRaw().entrySet()) {
                Consumer<Object> check = checks.get(e.getKey());
                if (check == null) {
                    throw new AssertionError(contract + "." + id + ": no check for then." + e.getKey());
                }
                check.accept(e.getValue());
                Drift.mark(contract, id, e.getKey());
            }
        }

        public <S> void checkBounds(List<S> domain, Map<String, ? extends BiConsumer<Object, S>> checks) {
            if (domain == null || domain.isEmpty()) {
                throw new IllegalArgumentException("domain must not be empty");
            }
            List<Map.Entry<String, Object>> entries = new ArrayList<>(thenRaw().entrySet());
            List<BiConsumer<Object, S>> boundChecks = new ArrayList<>(entries.size());
            for (Map.Entry<String, Object> e : entries) {
                BiConsumer<Object, S> check = checks == null ? null : checks.get(e.getKey());
                if (check == null) {
                    throw new AssertionError(contract + "." + id + ": no check for then." + e.getKey());
                }
                boundChecks.add(check);
            }
            for (S sample : domain) {
                for (int i = 0; i < entries.size(); i++) {
                    Map.Entry<String, Object> e = entries.get(i);
                    try {
                        boundChecks.get(i).accept(e.getValue(), sample);
                    } catch (AssertionError err) {
                        String msg = err.getMessage() == null ? "" : err.getMessage();
                        if (!msg.contains("[counterexample:")) {
                            throw new AssertionError(contract + "." + id + ".then." + e.getKey()
                                    + " failed [counterexample: " + sample + "]: " + msg, err);
                        }
                        throw err;
                    }
                }
            }
            for (Map.Entry<String, Object> e : entries) {
                Drift.mark(contract, id, e.getKey());
            }
        }

        public void checkProfileBounds(String param, Map<String, ? extends BiConsumer<Object, Object>> checks) {
            checkBounds(Drift.profileDomain(contract, param), checks);
        }

        public void checkProfileBounds(
                Collection<String> params,
                Map<String, ? extends BiConsumer<Object, Map<String, Object>>> checks) {
            checkBounds(Drift.profileDomain(contract, params), checks);
        }

        Map<String, String> projectionMap(String side) {
            return DriftVerify.projectionMap(contract, side);
        }

        public Map<String, Object> buildInput() {
            return buildInput(Map.of());
        }

        public Map<String, Object> buildInput(Map<String, Object> base) {
            return ExecutionContext.buildInput(when, projectionMap("when"), base);
        }

        public Map<String, Object> buildOutput() {
            return buildOutput(Map.of());
        }

        public Map<String, Object> buildOutput(Map<String, Object> base) {
            return DriftVerify.buildOutput(this, base);
        }

        public void checkProjection(Object payload) {
            checkProjection(payload, Map.of());
        }

        public <V> void checkAdverse(List<V> variants, java.util.function.Function<V, Object> execute) {
            DriftVerify.checkAdverse(this, variants, execute, Map.of());
        }

        public <V> void checkAdverse(
                List<V> variants,
                java.util.function.Function<V, Object> execute,
                Map<String, ? extends Consumer<Object>> checks) {
            DriftVerify.checkAdverse(this, variants, execute, checks);
        }

        public void checkFrame(Map<String, Object> frameObs) {
            DriftVerify.checkFrame(this, frameObs);
        }

        public boolean checkIdempotency(Map<String, Object> obs) {
            return DriftProbes.checkIdempotency(this, obs);
        }

        public boolean checkSeamProbe(Map<String, Object> obs) {
            return DriftProbes.checkSeamProbe(this, obs);
        }

        public boolean checkRollback(Map<String, Object> obs) {
            return DriftProbes.checkRollback(this, obs);
        }

        public boolean checkLogSink(Map<String, Object> obs) {
            return DriftProbes.checkLogSink(this, obs);
        }

        /** Verifies every {@code then} predicate against {@code payload} via {@code projections.then} and custom checks. */
        @SuppressWarnings("unchecked")
        public void checkProjection(Object payload, Map<String, ? extends Consumer<Object>> checks) {
            Map<String, String> thenProj = projectionMap("then");
            for (Map.Entry<String, Object> e : thenRaw().entrySet()) {
                String key = e.getKey();
                Object expected = e.getValue();
                Drift.mark(contract, id, key);
                Consumer<Object> custom = checks == null ? null : checks.get(key);
                if (custom != null) {
                    custom.accept(expected);
                    continue;
                }
                DriftViewChecks.checkProjectedLeaf(
                        this, key, expected, payload, thenProj, true, "no check or projection for");
            }
            if (payload instanceof Map<?, ?> pm && pm.get("_frame") instanceof Map<?, ?> fm) {
                boolean strict = fm.values().stream()
                        .noneMatch(v -> v instanceof Map<?, ?> vm && Boolean.FALSE.equals(vm.get("observed")));
                DriftUiChecks.checkFrame(this, (Map<String, Object>) fm, strict);
            }
        }

        /** Verifies UI, accessibility and Outcome Evidence Contract invariants on a view map. */
        public void checkView(Map<String, Object> view) {
            checkView(view, Map.of());
        }

        /** Verifies UI, accessibility and Outcome Evidence Contract invariants with custom overrides. */
        public void checkView(
                Map<String, Object> view,
                Map<String, ? extends BiConsumer<Object, Map<String, Object>>> checks) {
            DriftViewChecks.checkView(this, view, checks);
        }

        Map<String, Object> thenRaw() {
            DriftInternal.MutationOverride ov = activeMutation(contract, id);
            return ov != null && !ov.isWhen() ? ov.apply(then) : then;
        }

        private Object need(Map<String, Object> m, String table, String key) {
            if (!m.containsKey(key)) {
                throw new IllegalArgumentException(contract + "." + id + "." + table + " has no " + key);
            }
            return m.get(key);
        }
    }
}

