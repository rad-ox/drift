package drift;

import static drift.DriftInternal.map;
import java.nio.file.Path;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.*;

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

    public static Case expect(String contract, String caseId) {
        return expect(contract, caseId, null);
    }

    public static Case expect(String contract, String caseId, String level) {
        DriftListener.validateConfig();
        DriftVerify.preCheckExpect(activeTest(), TAG.get(), contract, caseId, level);
        Map<String, Object> cases = map(view(contract).get("cases"), contract + ".cases");
        Object c = cases.get(caseId);
        if (c == null) {
            throw new IllegalArgumentException("contract " + contract + " has no case " + caseId);
        }
        Map<String, Object> m = map(c, contract + ".cases." + caseId);
        DriftVerify.bindExpect(activeTest(), TAG, contract, caseId, level, m);
        READS.get().add(contract + "\u0000" + caseId);
        Map<String, Object> when = map(m.getOrDefault("when", Map.of()), "when");
        Map<String, Object> then = map(m.getOrDefault("then", Map.of()), "then");
        DriftInternal.MutationOverride override = activeMutation(contract, caseId);
        if (override != null) {
            if (override.isWhen()) {
                when = override.applyWhen(when);
            } else {
                then = override.apply(then);
            }
        }
        DriftWhen.register(contract, caseId, when);
        return new Case(contract, caseId, when, then);
    }

    public static void runCase(String contract, String caseId, String level, Consumer<Case> action) {
        DriftWhen.runStandaloneCase(contract, caseId, level, action);
    }

    public static void runCase(String contract, String caseId, Consumer<Case> action) {
        runCase(contract, caseId, null, action);
    }

    public static void forEachCase(String contract, Consumer<Case> action) {
        DriftCase tag = activeTest() ? TAG.get() : null;
        Collection<String> ids = (tag != null && tag.contract().equals(contract) && tag.cases().length > 0)
                ? List.of(tag.cases())
                : map(view(contract).get("cases"), contract + ".cases").keySet();
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

    static boolean hasContract(String contract) {
        try {
            view(contract);
            return true;
        } catch (RuntimeException e) {
            return false;
        }
    }

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

    static boolean read(String contract, String caseId) {
        String key = contract + "\u0000" + caseId;
        if (!READS.get().contains(key)) {
            return false;
        }
        Map<String, Object> v = view(contract);
        Map<String, Object> c = map(map(v.get("cases"), contract + ".cases").get(caseId),
                contract + ".cases." + caseId);
        Set<String> seen = THEN_READS.get().getOrDefault(key, Set.of());
        return seen.containsAll(map(c.getOrDefault("then", Map.of()), "then").keySet())
                && DriftVerify.allFramesRead(v, caseId, seen);
    }

    static void mark(String contract, String caseId, String predicate) {
        THEN_READS.get().computeIfAbsent(contract + "\u0000" + caseId, k -> new HashSet<>()).add(predicate);
    }

    static void unmarkCase(String contract, String caseId) {
        THEN_READS.get().remove(contract + "\u0000" + caseId);
    }

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
        if (!mutationRun()) {
            TEST_INPUTS.get().put(".drift/self-stub/" + contract, "sha256:self-stub");
        }
    }

    static boolean hasSelfStub(String contract) {
        return TEST_INPUTS.get().containsKey(".drift/self-stub/" + contract);
    }

    private static boolean activeTest() {
        return Boolean.TRUE.equals(IN_TEST.get());
    }

    static void recordSeamStub(String producer, String caseId, String ref) {
        if (activeTest() && !mutationRun()) {
            TEST_INPUTS.get().put(".drift/seam-stub/" + producer + "#" + caseId, ref);
        }
    }

    private static void clearThreadState() {
        READS.get().clear();
        THEN_READS.get().clear();
        DriftWhen.clear();
        DriftObservations.clear();
        TEST_INPUTS.get().clear();
        TEST_INPUT_PATHS.get().clear();
    }

    static void resetStandalone() {
        clearThreadState();
        TAG.remove();
        DriftVerify.clearStandalone();
    }

    /** A test starts on this thread; a null tag marks an untagged test. */
    static void begin(DriftCase tag) {
        clearThreadState();
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
        DriftObservations.clear();
        DriftWhen.clear();
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
        return DriftSelect.intDomain(min, max);
    }

    public static List<String> enumDomain(String... values) {
        return DriftSelect.enumDomain(values);
    }

    public static List<Boolean> boolDomain() {
        return DriftSelect.boolDomain();
    }

    public static List<Map<String, Object>> cartesianDomain(Map<String, ? extends List<?>> domains) {
        return DriftSelect.cartesianDomain(domains);
    }

    public static List<Object> profileDomain(String contract, String param) {
        return DriftSelect.profileDomain(contract, param);
    }

    public static List<Map<String, Object>> profileDomain(String contract, Collection<String> params) {
        return DriftSelect.profileDomain(contract, params);
    }

    public static Map<String, Object> stub(String contractOrResource, String caseId) {
        return DriftStubs.buildStub(contractOrResource, caseId, Map.of(), activeTest());
    }

    public static Map<String, Object> stub(String contractOrResource, String caseId, Map<String, Object> base) {
        return DriftStubs.buildStub(contractOrResource, caseId, base, activeTest());
    }

    public static Map<String, Object> stub(String contractOrResource, Map<String, Object> whenInput) {
        return DriftStubs.buildStubByWhen(contractOrResource, whenInput, Map.of(), activeTest());
    }

    public static Map<String, Object> stub(String contractOrResource, Map<String, Object> whenInput, Map<String, Object> base) {
        return DriftStubs.buildStubByWhen(contractOrResource, whenInput, base, activeTest());
    }

    public static List<Map<String, Object>> stubVariants(String contractOrResource, String caseId) {
        return DriftStubs.buildStubVariants(contractOrResource, caseId, Map.of(), activeTest());
    }

    public static List<Map<String, Object>> stubVariants(String contractOrResource, String caseId, Map<String, Object> base) {
        return DriftStubs.buildStubVariants(contractOrResource, caseId, base, activeTest());
    }

    public static List<Map<String, Object>> stubVariants(String contractOrResource, Map<String, Object> whenInput) {
        return DriftStubs.buildStubVariantsByWhen(contractOrResource, whenInput, Map.of(), activeTest());
    }

    public static List<Map<String, Object>> stubVariants(String contractOrResource, Map<String, Object> whenInput, Map<String, Object> base) {
        return DriftStubs.buildStubVariantsByWhen(contractOrResource, whenInput, base, activeTest());
    }

    public static boolean verifyStub(String contractOrResource, String caseId, Object payload) {
        return DriftStubs.verifyStub(contractOrResource, caseId, payload, activeTest());
    }

    public static boolean verifyStub(String contractOrResource, Map<String, Object> whenInput, Object payload) {
        return DriftStubs.verifyStubByWhen(contractOrResource, whenInput, payload, activeTest());
    }

    public static boolean observe(String contract, String caseId, String test, Map<String, Object> when, Map<String, Object> then) {
        return DriftSelect.observe(contract, caseId, test, when, then);
    }

    static String resolvedDir() {
        Path ov = MUTATION_RESOLVED.get();
        if (ov != null) return ov.toString();
        String dir = DriftListener.propOrEnv(RESOLVED, "DRIFT_RESOLVED");
        return dir != null ? dir : DriftInternal.sessionProperty("resolved", true);
    }

    static Map<String, Object> view(String contract) {
        String dir = resolvedDir();
        if (dir == null || dir.isBlank()) {
            String autoKey = "<auto>\u0000" + contract;
            return VIEWS.computeIfAbsent(autoKey, ignored -> DriftInternal.autoResolve(contract));
        }
        String key = dir + "\u0000" + contract;
        String resolvedDir = dir;
        return VIEWS.computeIfAbsent(key, ignored -> DriftInternal.load(contract, resolvedDir));
    }

    public record Case(String contract, String id, Map<String, Object> when, Map<String, Object> then) {
        private Object unwrap03(Object v) {
            return (!Drift.isExplicitSchema02(contract) && v instanceof Map<?, ?> m && m.size() == 1 && m.containsKey("eq"))
                    ? m.get("eq")
                    : v;
        }

        public Object when(String key) {
            Object v = need(when, "when", key);
            DriftWhen.mark(contract, id, key);
            return unwrap03(v);
        }

        @Override
        public Map<String, Object> when() {
            return new DriftViewChecks.ThenView(when, key -> DriftWhen.mark(contract, id, key));
        }

        Map<String, Object> whenRaw() {
            return when;
        }

        public List<String> unreadWhen() {
            return DriftWhen.unread(contract, id, when);
        }

        public void requireWhenRead() {
            DriftWhen.requireCase(this);
        }

        public Object then(String key) {
            Object value = need(then, "then", key);
            Drift.mark(contract, id, key);
            return unwrap03(value);
        }

        @Override
        public Map<String, Object> then() {
            return new DriftViewChecks.ThenView(then, key -> Drift.mark(contract, id, key));
        }

        public Optional<Object> findWhen(String key) {
            if (!when.containsKey(key)) return Optional.empty();
            DriftWhen.mark(contract, id, key);
            return Optional.ofNullable(unwrap03(when.get(key)));
        }

        @SuppressWarnings("unchecked")
        public Map<String, Object> whenTable() {
            DriftWhen.markAll(contract, id, when);
            Object cloned = Json.cloneJsonValue(when);
            return cloned instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
        }

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
            DriftWhen.markAll(contract, id, when);
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
            DriftUiChecks.checkFrame(this, frameObs);
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

        @SuppressWarnings("unchecked")
        public void checkProjection(Object payload, Map<String, ? extends Consumer<Object>> checks) {
            Map<String, String> thenProj = projectionMap("then");
            Map<String, Object> rawThen = thenRaw();
            boolean decl = true;
            try {
                for (Map.Entry<String, Object> e : rawThen.entrySet()) {
                    String key = e.getKey();
                    Object expected = e.getValue();
                    Drift.mark(contract, id, key);
                    Consumer<Object> custom = checks == null ? null : checks.get(key);
                    if (custom != null) {
                        decl = false;
                        custom.accept(expected);
                        continue;
                    }
                    DriftViewChecks.checkProjectedLeaf(
                            this, key, expected, payload, thenProj, true, "no check or projection for");
                }
                if (decl) DriftObservations.recordPayload(this, payload, rawThen, thenProj);
                if (payload instanceof Map<?, ?> pm && pm.get("_frame") instanceof Map<?, ?> fm) {
                    boolean strict = fm.values().stream()
                            .noneMatch(v -> v instanceof Map<?, ?> vm && Boolean.FALSE.equals(vm.get("observed")));
                    DriftUiChecks.checkFrame(this, (Map<String, Object>) fm, strict);
                } else {
                    DriftWhen.checkStandalone(this);
                    DriftVerify.emitStandaloneIfActive(this, true);
                }
            } catch (Throwable err) {
                DriftObservations.clearCase(contract, id);
                DriftVerify.emitStandaloneIfActive(this, false);
                throw err;
            }
        }

        public void checkView(Map<String, Object> view) {
            checkView(view, Map.of());
        }

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

