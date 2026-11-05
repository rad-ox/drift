package drift;

import java.io.IOException;
import java.lang.reflect.Method;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.ServiceLoader;
import java.util.TreeMap;
import org.junit.platform.engine.TestEngine;
import org.junit.platform.engine.TestExecutionResult;
import org.junit.platform.engine.TestSource;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.engine.support.descriptor.MethodSource;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.LauncherDiscoveryRequest;
import org.junit.platform.launcher.TestExecutionListener;
import org.junit.platform.launcher.TestIdentifier;
import org.junit.platform.launcher.TestPlan;
import org.junit.platform.launcher.core.LauncherConfig;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;

/** Runs current then-value mutants in an isolated JUnit Platform pass. */
public final class MutationRunner {
    private static final String MANIFEST_VERSION = "version";
    private static final long MUTATION_BUDGET_FACTOR = 3;
    static final long MIN_MUTANT_NANOS = 250_000_000L;

    private MutationRunner() {}

    /** Executes controls and mutants, writing version-bound results outside ordinary proof shards. */
    public static void run(Path manifestFile, Path resolved, Path eventsDirectory, Path resultsDirectory,
            List<String> testClasspath) throws IOException {
        byte[] manifestBytes = Files.readAllBytes(manifestFile);
        Object value = Json.read(manifestFile);
        Map<String, Object> manifest = object(value, manifestFile.toString());
        if (!Long.valueOf(1).equals(manifest.get(MANIFEST_VERSION))) {
            throw new IllegalArgumentException("mutation manifest version must be 1");
        }
        String manifestId = "sha256:" + sha256(manifestBytes);
        List<Target> targets = targets(manifest);
        List<TestMethod> inventory = testInventory(eventsDirectory);
        List<CaseKey> cases = cases(targets);

        ClassLoader previousLoader = Thread.currentThread().getContextClassLoader();
        Files.createDirectories(resultsDirectory);
        Path resultFile = resultsDirectory.resolve("results.jsonl");
        Files.deleteIfExists(resultFile);

        List<String> records = new ArrayList<>();
        try (URLClassLoader loader = classLoader(testClasspath, previousLoader)) {
            Map<String, List<TestMethod>> testsByCase = taggedTests(inventory, eventsDirectory, loader);
            Thread.currentThread().setContextClassLoader(loader);
            Drift.beginMutationRun(resolved);
            List<TestEngine> engines = new ArrayList<>();
            for (TestEngine engine : ServiceLoader.load(TestEngine.class, loader)) {
                engines.add(engine);
            }
            if (engines.isEmpty()) {
                String junitEntries = testClasspath.stream().filter(p -> p.contains("junit")
                        || p.contains("test-classes")).toList().toString();
                throw new IOException("no JUnit TestEngine providers are visible; test classpath entries: "
                        + junitEntries);
            }
            LauncherConfig launcherConfig = LauncherConfig.builder()
                    .enableTestEngineAutoRegistration(false)
                    .enableTestExecutionListenerAutoRegistration(false)
                    .addTestEngines(engines.toArray(TestEngine[]::new))
                    .build();
            Map<CaseKey, LauncherDiscoveryRequest> requestsByCase = new HashMap<>();

            Map<CaseKey, Control> controls = new HashMap<>();
            long controlNanos = 0;
            for (CaseKey key : cases) {
                List<TestMethod> tests = testsByCase.getOrDefault(key.toString(), List.of());
                if (tests.isEmpty()) {
                    controls.put(key, new Control(false, 0));
                    continue;
                }
                LauncherDiscoveryRequest request = discoveryRequest(tests);
                requestsByCase.put(key, request);
                Execution control = execute(request, launcherConfig);
                boolean passed = control.passed(tests);
                controls.put(key, new Control(passed, control.elapsedNanos));
                controlNanos += control.elapsedNanos;
            }

            long batchBudgetBasis = batchBudgetBasisNanos(controlNanos, cases.size(), targets.size());
            long mutationStart = System.nanoTime();
            Map<Integer, Target> quarantinedTargets = new LinkedHashMap<>();
            for (int i = 0; i < targets.size(); i++) {
                Target target = targets.get(i);
                CaseKey key = new CaseKey(target.contract, target.caseId);
                Control control = controls.getOrDefault(key, new Control(false, 0));
                String outcome;
                if (!control.passed || controlNanos <= 0) {
                    outcome = "inconclusive";
                } else if (budgetExceeded(System.nanoTime() - mutationStart, batchBudgetBasis)) {
                    outcome = "inconclusive";
                    quarantinedTargets.put(i, target);
                } else {
                    List<TestMethod> caseTests = testsByCase.getOrDefault(key.toString(), List.of());
                    LauncherDiscoveryRequest request = requestsByCase.get(key);
                    Drift.setMutation(target.contract, target.caseId, target.path, target.after);
                    Execution mutated;
                    try {
                        mutated = execute(request, launcherConfig);
                    } finally {
                        Drift.clearMutation();
                    }
                    if (mutantBudgetExceeded(mutated.elapsedNanos, control.elapsedNanos)) {
                        outcome = "inconclusive";
                        quarantinedTargets.put(i, target);
                    } else if (mutated.hasOtherFailure()) {
                        outcome = "inconclusive";
                    } else if (mutated.hasAssertionFailure()) {
                        outcome = "killed";
                    } else if (mutated.passed(caseTests)) {
                        outcome = "survived";
                    } else {
                        outcome = "inconclusive";
                    }
                }
                records.add(eventLine(manifestId, target, outcome,
                        control.passed ? "passed" : "failed"));
            }
            for (Map.Entry<Integer, Target> entry : quarantinedTargets.entrySet()) {
                int idx = entry.getKey();
                Target target = entry.getValue();
                CaseKey key = new CaseKey(target.contract, target.caseId);
                Control control = controls.getOrDefault(key, new Control(false, 0));
                if (!control.passed) {
                    continue;
                }
                List<TestMethod> caseTests = testsByCase.getOrDefault(key.toString(), List.of());
                LauncherDiscoveryRequest request = requestsByCase.get(key);
                Drift.setMutation(target.contract, target.caseId, target.path, target.after);
                Execution retried;
                try {
                    retried = execute(request, launcherConfig);
                } finally {
                    Drift.clearMutation();
                }
                String retryOutcome;
                if (mutantBudgetExceeded(retried.elapsedNanos, control.elapsedNanos)) {
                    retryOutcome = "inconclusive";
                } else if (retried.hasOtherFailure()) {
                    retryOutcome = "inconclusive";
                } else if (retried.hasAssertionFailure()) {
                    retryOutcome = "killed";
                } else if (retried.passed(caseTests)) {
                    retryOutcome = "survived";
                } else {
                    retryOutcome = "inconclusive";
                }
                records.set(idx, eventLine(manifestId, target, retryOutcome,
                        control.passed ? "passed" : "failed"));
            }
        } finally {
            Drift.endMutationRun();
            Thread.currentThread().setContextClassLoader(previousLoader);
        }
        Files.writeString(resultFile, String.join("\n", records) + (records.isEmpty() ? "" : "\n"),
                StandardCharsets.UTF_8);
    }

    private static List<Target> targets(Map<String, Object> manifest) {
        List<?> contractValues = list(manifest.get("contracts"), "contracts");
        List<Target> targets = new ArrayList<>();
        for (Object contractValue : contractValues) {
            Map<String, Object> contract = object(contractValue, "contracts[]");
            String id = string(contract.get("id"), "contracts[].id");
            String digest = string(contract.get("digest"), "contracts[].digest");
            for (Object mutantValue : list(contract.get("mutants"), "mutants")) {
                Map<String, Object> mutant = object(mutantValue, "mutants[]");
                targets.add(new Target(
                        string(mutant.get("id"), "mutants[].id"),
                        id,
                        digest,
                        string(mutant.get("case"), "mutants[].case"),
                        string(mutant.get("path"), "mutants[].path"),
                        mutant.get("after")));
            }
        }
        targets.sort(Comparator.comparing(Target::contract).thenComparing(Target::id));
        return List.copyOf(targets);
    }

    private static List<CaseKey> cases(List<Target> targets) {
        return targets.stream().map(t -> new CaseKey(t.contract, t.caseId)).distinct()
                .sorted(Comparator.comparing(CaseKey::contract).thenComparing(CaseKey::caseId)).toList();
    }

    private static List<TestMethod> testInventory(Path eventsDirectory) throws IOException {
        if (!Files.isDirectory(eventsDirectory)) {
            return List.of();
        }
        List<Path> sidecars;
        try (var paths = Files.list(eventsDirectory)) {
            sidecars = paths.filter(p -> p.getFileName().toString().endsWith(".meta.json"))
                    .sorted().toList();
        }
        Map<String, TestMethod> methods = new TreeMap<>();
        for (Path sidecar : sidecars) {
            Map<String, Object> inventory = object(Json.read(sidecar), sidecar.toString());
            for (Object entry : list(inventory.get("tests"), sidecar + ".tests")) {
                String value = string(entry, sidecar + ".tests[]");
                int hash = value.indexOf('#');
                if (hash <= 0 || hash + 1 >= value.length()) {
                    throw new IllegalArgumentException(sidecar + " has an invalid tagged test " + value);
                }
                String className = value.substring(0, hash);
                String methodName = value.substring(hash + 1);
                int invocation = methodName.indexOf('[');
                if (invocation >= 0) {
                    methodName = methodName.substring(0, invocation);
                }
                methods.put(className + "#" + methodName, new TestMethod(className, methodName, true));
            }
        }
        return List.copyOf(methods.values());
    }

    private static Map<String, List<TestMethod>> taggedTests(List<TestMethod> inventory,
            Path eventsDirectory, ClassLoader loader) throws IOException {
        Map<String, List<TestMethod>> result = new HashMap<>();
        Map<String, Class<?>> loadedClasses = new HashMap<>();
        for (TestMethod test : inventory) {
            Class<?> testClass = loadedClasses.get(test.className);
            if (testClass == null) {
                try {
                    testClass = Class.forName(test.className, false, loader);
                    loadedClasses.put(test.className, testClass);
                } catch (ClassNotFoundException e) {
                    throw new IOException("tagged test class is missing from the test classpath: " + test.className, e);
                }
            }
            Method method = findMethod(testClass, test.methodName);
            DriftCase tag = method.getAnnotation(DriftCase.class);
            if (tag == null) {
                continue;
            }
            TestMethod resolved = new TestMethod(test.className, test.methodName, method.getParameterCount() == 0);
            for (String caseId : tag.cases()) {
                result.computeIfAbsent(new CaseKey(tag.contract(), caseId).toString(),
                        ignored -> new ArrayList<>()).add(resolved);
            }
        }
        if (Files.isDirectory(eventsDirectory)) {
            try (var paths = Files.list(eventsDirectory)) {
                for (Path evFile : paths.filter(p -> p.getFileName().toString().endsWith(".jsonl")).sorted().toList()) {
                    for (String line : Files.readAllLines(evFile, StandardCharsets.UTF_8)) {
                        String trimmed = line.trim();
                        if (trimmed.isEmpty()) continue;
                        try {
                            Map<String, Object> ev = object(Json.parse(trimmed), evFile.toString());
                            if (!(ev.get("contract") instanceof String cid) || !(ev.get("test") instanceof String tid)) continue;
                            int hash = tid.indexOf('#');
                            if (hash <= 0 || hash + 1 >= tid.length()) continue;
                            String cls = tid.substring(0, hash);
                            String mth = tid.substring(hash + 1);
                            int inv = mth.indexOf('[');
                            if (inv >= 0) mth = mth.substring(0, inv);
                            Class<?> loaded = loadedClasses.get(cls);
                            if (loaded == null) {
                                loaded = Class.forName(cls, false, loader);
                                loadedClasses.put(cls, loaded);
                            }
                            TestMethod tm = new TestMethod(cls, mth, hasZeroArgMethod(loaded, mth));
                            if (ev.get("cases") instanceof List<?> cs) {
                                for (Object cObj : cs) {
                                    if (cObj instanceof String cStr && !cStr.isBlank()) {
                                        result.computeIfAbsent(new CaseKey(cid, cStr).toString(), ignored -> new ArrayList<>()).add(tm);
                                    }
                                }
                            }
                        } catch (RuntimeException | ClassNotFoundException ignored) {
                        }
                    }
                }
            }
        }
        result.replaceAll((key, methods) -> methods.stream().distinct()
                .sorted(Comparator.comparing(TestMethod::id)).toList());
        return result;
    }

    private static boolean hasZeroArgMethod(Class<?> testClass, String name) {
        for (Class<?> cur = testClass; cur != null; cur = cur.getSuperclass()) {
            for (Method m : cur.getDeclaredMethods()) {
                if (m.getName().equals(name) && m.getParameterCount() == 0) {
                    return true;
                }
            }
        }
        return false;
    }

    private static Method findMethod(Class<?> testClass, String name) throws IOException {
        for (Class<?> current = testClass; current != null; current = current.getSuperclass()) {
            for (Method method : current.getDeclaredMethods()) {
                if (method.getName().equals(name) && method.getAnnotation(DriftCase.class) != null) {
                    return method;
                }
            }
        }
        throw new IOException("tagged test method is missing or untagged: " + testClass.getName() + "#" + name);
    }

    private static LauncherDiscoveryRequest discoveryRequest(List<TestMethod> tests) {
        List<org.junit.platform.engine.DiscoverySelector> selectors = new ArrayList<>(tests.size());
        for (TestMethod t : tests) {
            selectors.add(t.zeroArg ? DiscoverySelectors.selectMethod(t.className, t.methodName) : DiscoverySelectors.selectClass(t.className));
        }
        return LauncherDiscoveryRequestBuilder.request()
                .selectors(selectors)
                .configurationParameter("junit.jupiter.execution.parallel.enabled", "false")
                .build();
    }

    private static Execution execute(LauncherDiscoveryRequest request, LauncherConfig launcherConfig) {
        if (request == null) {
            return new Execution(Map.of(), 0);
        }
        long start = System.nanoTime();
        Launcher launcher = LauncherFactory.create(launcherConfig);
        ResultListener listener = new ResultListener();
        try {
            launcher.execute(request, new DriftListener(), listener);
        } finally {
            Drift.clearMutation();
        }
        return new Execution(listener.results, System.nanoTime() - start);
    }

    private static URLClassLoader classLoader(List<String> classpath, ClassLoader parent) throws IOException {
        List<URL> urls = new ArrayList<>();
        for (String path : classpath) {
            urls.add(Path.of(path).toAbsolutePath().normalize().toUri().toURL());
        }
        return new URLClassLoader(urls.toArray(URL[]::new), parent);
    }

    private static String eventLine(String manifest, Target target, String outcome, String control) {
        StringBuilder line = new StringBuilder("{");
        Json.field(line, "manifest", manifest).append(',');
        Json.field(line, "contract", target.contract).append(',');
        Json.field(line, "digest", target.digest).append(',');
        Json.field(line, "mutant", target.id).append(',');
        Json.field(line, "case", target.caseId).append(',');
        Json.field(line, "outcome", outcome).append(',');
        Json.field(line, "control", control);
        return line.append('}').toString();
    }

    private static String sha256(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is unavailable", e);
        }
    }

    static boolean budgetExceeded(long mutationNanos, long controlNanos) {
        if (mutationNanos < 0 || controlNanos <= 0) {
            return true;
        }
        long budget = controlNanos > Long.MAX_VALUE / MUTATION_BUDGET_FACTOR
                ? Long.MAX_VALUE : controlNanos * MUTATION_BUDGET_FACTOR;
        return mutationNanos >= budget;
    }

    static boolean mutantBudgetExceeded(long mutantElapsedNanos, long caseControlNanos) {
        if (mutantElapsedNanos < 0 || caseControlNanos <= 0) {
            return true;
        }
        long scaled = caseControlNanos > Long.MAX_VALUE / MUTATION_BUDGET_FACTOR
                ? Long.MAX_VALUE : caseControlNanos * MUTATION_BUDGET_FACTOR;
        long budget = Math.max(MIN_MUTANT_NANOS, scaled);
        return mutantElapsedNanos >= budget;
    }

    static long batchBudgetBasisNanos(long totalControlNanos, int caseCount, int mutantCount) {
        if (totalControlNanos <= 0) {
            return 0;
        }
        long meanCaseNanos = caseCount > 0 ? Math.max(1L, totalControlNanos / caseCount) : totalControlNanos;
        long scaledBasis = mutantCount > 0 && meanCaseNanos > Long.MAX_VALUE / mutantCount
                ? Long.MAX_VALUE : meanCaseNanos * Math.max(1, mutantCount);
        long minBasis = mutantCount > 0 ? (MIN_MUTANT_NANOS / MUTATION_BUDGET_FACTOR) * mutantCount : totalControlNanos;
        return Math.max(totalControlNanos, Math.max(scaledBasis, minBasis));
    }

    private static Map<String, Object> object(Object value, String where) {
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> result = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                if (!(entry.getKey() instanceof String key)) {
                    throw new IllegalArgumentException(where + " has a non-string key");
                }
                result.put(key, entry.getValue());
            }
            return result;
        }
        throw new IllegalArgumentException(where + " is not a JSON object");
    }

    private static List<?> list(Object value, String where) {
        if (value instanceof List<?> list) {
            return list;
        }
        throw new IllegalArgumentException(where + " is not a JSON array");
    }

    private static String string(Object value, String where) {
        if (value instanceof String text && !text.isBlank()) {
            return text;
        }
        throw new IllegalArgumentException(where + " is not a non-empty string");
    }

    private record Target(String id, String contract, String digest, String caseId, String path, Object after) {}

    private record TestMethod(String className, String methodName, boolean zeroArg) {
        String id() {
            return className + "#" + methodName;
        }
    }

    private record CaseKey(String contract, String caseId) {
        public String toString() {
            return contract + "\u0000" + caseId;
        }
    }

    private record Control(boolean passed, long elapsedNanos) {}

    private record Execution(Map<String, List<TestExecutionResult>> results, long elapsedNanos) {
        boolean passed(List<TestMethod> tests) {
            for (TestMethod test : tests) {
                List<TestExecutionResult> outcomes = results.get(test.id());
                if (outcomes == null || outcomes.isEmpty()
                        || outcomes.stream().anyMatch(r -> r.getStatus() != TestExecutionResult.Status.SUCCESSFUL)) {
                    return false;
                }
            }
            return true;
        }

        boolean hasAssertionFailure() {
            return results.values().stream().flatMap(List::stream)
                    .anyMatch(r -> r.getStatus() == TestExecutionResult.Status.FAILED
                            && r.getThrowable().orElse(null) instanceof AssertionError);
        }

        boolean hasOtherFailure() {
            return results.values().stream().flatMap(List::stream)
                    .anyMatch(r -> r.getStatus() != TestExecutionResult.Status.SUCCESSFUL
                            && !(r.getStatus() == TestExecutionResult.Status.FAILED
                                    && r.getThrowable().orElse(null) instanceof AssertionError));
        }
    }

    private static final class ResultListener implements TestExecutionListener {
        private TestPlan plan;
        private final Map<String, List<TestExecutionResult>> results = new TreeMap<>();

        @Override
        public void testPlanExecutionStarted(TestPlan plan) {
            this.plan = plan;
        }

        @Override
        public void executionSkipped(TestIdentifier id, String reason) {
            if (id.isTest()) {
                add(id, TestExecutionResult.aborted(new IllegalStateException("test skipped: " + reason)));
            }
        }

        @Override
        public void executionFinished(TestIdentifier id, TestExecutionResult result) {
            if (id.isTest()) {
                add(id, result);
            }
        }

        private void add(TestIdentifier id, TestExecutionResult result) {
            String method = methodId(id, plan);
            if (method != null) {
                results.computeIfAbsent(method, ignored -> new ArrayList<>()).add(result);
            }
        }

        private static String methodId(TestIdentifier id, TestPlan plan) {
            TestIdentifier current = id;
            while (current != null) {
                TestSource source = current.getSource().orElse(null);
                if (source instanceof MethodSource method) {
                    return method.getClassName() + "#" + method.getMethodName();
                }
                current = plan.getParent(current).orElse(null);
            }
            return null;
        }
    }
}
