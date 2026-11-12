package drift;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeoutException;
import org.junit.platform.engine.TestExecutionResult;
import org.junit.platform.engine.TestDescriptor;
import org.junit.platform.engine.UniqueId;
import org.junit.platform.engine.support.descriptor.ClassSource;
import org.junit.platform.engine.support.descriptor.MethodSource;
import org.junit.platform.launcher.TestExecutionListener;
import org.junit.platform.launcher.TestIdentifier;
import org.junit.platform.launcher.TestPlan;

/**
 * Appends one proof event per {@link DriftCase} test to the JSONL file named by the system
 * property {@code drift.events}. Without the property it does nothing. Every dynamic test and
 * every invocation of a parameterized or repeated test gets its own id, the method with its
 * position, so a test run again supersedes its earlier event (SPEC section 9).
 */
public final class DriftListener implements TestExecutionListener {
    public static final String EVENTS = "drift.events";
    public static final String SNAPSHOT = "drift.snapshot";
    public static final String ENV = "drift.env";
    public static final String PROOF_KEY = "drift.proofKey";
    public static final String PACK_REF = "drift.packRef";
    public static final String TOUCHED = "drift.touched";
    public static final String EXECUTION_REF = "drift.executionRef";
    private static final Set<String> ENV_KEYS = Set.of(
            "adapter", "config", "deps", "drift", "policy", "runner", "toolchain");

    private static final int BUFFER_FLUSH_THRESHOLD = 8192;
    private static final Map<MethodSource, Optional<DriftCase>> SOURCE_TAGS = new ConcurrentHashMap<>();

    private static volatile boolean standaloneHookRegistered;

    @Override
    public void executionStarted(TestIdentifier id) {
        if (id.isTest()) {
            DriftCase tag = tagOf(id);
            if (tag == null && id.getSource().isEmpty()) {
                Drift.end();
            } else if (tag == null && isClosureSource(id)) {
                Drift.begin(DriftVerify.closureSlot());
            } else {
                Drift.begin(tag);
            }
        }
    }

    private static boolean isClosureSource(TestIdentifier id) {
        if (id.getSource().isEmpty()) {
            return false;
        }
        var src = id.getSource().get();
        if (src instanceof ClassSource) {
            return true;
        }
        if (src instanceof MethodSource ms) {
            try {
                ms.getJavaMethod();
                return false;
            } catch (RuntimeException e) {
                return true;
            }
        }
        return false;
    }

    @Override
    public void executionSkipped(TestIdentifier id, String reason) {
        if (id.isTest()) {
            if (!Drift.mutationRun()) {
                write(id, "disabled", tagOf(id));
            }
            Drift.end();
        }
    }

    @Override
    public void executionFinished(TestIdentifier id, TestExecutionResult result) {
        if (!id.isTest()) {
            return;
        }
        String outcome = switch (result.getStatus()) {
            case SUCCESSFUL -> "passed";
            case ABORTED -> "skipped";
            case FAILED -> result.getThrowable().filter(TimeoutException.class::isInstance).isPresent()
                    ? "timeout" : "failed";
        };
        if (!Drift.mutationRun()) {
            DriftCase tag = Drift.tag();
            write(id, outcome, tag != null ? tag : tagOf(id));
        }
        Drift.end();
    }

    static DriftCase tagOf(MethodSource ms) {
        return SOURCE_TAGS.computeIfAbsent(ms, source -> {
            try {
                Method m = source.getJavaMethod();
                return Optional.ofNullable(m.getAnnotation(DriftCase.class));
            } catch (RuntimeException e) {
                return Optional.empty();
            }
        }).orElse(null);
    }

    private static DriftCase tagOf(TestIdentifier id) {
        if (id.getSource().isEmpty() || !(id.getSource().get() instanceof MethodSource ms)) {
            return null;
        }
        return tagOf(ms);
    }

    private static void write(TestIdentifier id, String outcome, DriftCase tag) {
        String file = eventsTarget();
        if (file == null || file.isBlank() || tag == null || tag.contract().isEmpty() || id.getSource().isEmpty()) {
            return;
        }
        String className;
        String methodName;
        var src = id.getSource().get();
        if (src instanceof MethodSource ms) {
            if (isVintageJUnit4Handled(ms.getJavaClass(), id.getUniqueId())) return;
            className = ms.getClassName();
            methodName = ms.getMethodName();
        } else if (src instanceof ClassSource cs) {
            if (isVintageJUnit4Handled(cs.getJavaClass(), id.getUniqueId())) return;
            className = cs.getClassName();
            methodName = id.getDisplayName();
        } else {
            return;
        }
        String resolvedDir = System.getProperty(Drift.RESOLVED);
        boolean hasContract = Drift.hasContract(tag.contract());
        if (resolvedDir != null && !resolvedDir.isBlank() && !hasContract
                && "passed".equals(outcome)) {
            outcome = "failed";
        }
        if ("passed".equals(outcome) && !Drift.inputsUnchanged()) {
            outcome = "failed";
        }
        List<String> read = new ArrayList<>();
        if (hasContract) {
            for (String c : tag.cases()) {
                if (Drift.read(tag.contract(), c)) {
                    read.add(c);
                }
            }
        }
        String canonicalTest = className + "#" + methodName;
        String test = canonicalTest + ordinal(id);
        Map<String, String> inputs = Drift.recordedInputs();
        synchronized (DriftListener.class) {
            if (DriftVerify.isDynamicTag(tag)) {
                DISCOVERED_CLASSES.add(className);
                DISCOVERED_TESTS.computeIfAbsent(className, ignored -> new TreeSet<>()).add(canonicalTest);
            }
            if (!inputs.isEmpty()) {
                RECORDED_INPUTS.computeIfAbsent(canonicalTest, ignored -> new TreeMap<>()).putAll(inputs);
            }
        }
        StringBuilder line = new StringBuilder("{");
        Json.field(line, "test", test).append(',');
        Json.field(line, "contract", tag.contract()).append(',');
        Json.field(line, "cases", List.of(tag.cases())).append(',');
        Json.field(line, "level", tag.level()).append(',');
        Json.field(line, "outcome", outcome);
        if (!read.isEmpty()) {
            Json.field(line.append(','), "read", read);
        }
        String digest = Drift.digest(tag.contract());
        if (digest != null) {
            Json.field(line.append(','), "digest", digest);
        }
        if (Drift.isSchema03(tag.contract())) {
            Json.field(line.append(','), "schema", "0.3");
            Json.field(line.append(','), "capabilities", Drift.requiredCapabilities(tag.contract()));
        }
        line.append("}\n");
        append(Path.of(file), line.toString());
    }

    private static String eventsTarget() {
        String prop = System.getProperty(EVENTS);
        if (prop != null && !prop.isBlank()) return prop;
        String env = System.getenv("DRIFT_EVENTS");
        if (env != null && !env.isBlank()) return env;
        return DriftInternal.sessionProperty("events", true);
    }

    private static boolean isVintageJUnit4Handled(Class<?> cls, String uniqueId) {
        if (cls == null || uniqueId == null || !uniqueId.startsWith("[engine:junit-vintage]")) return false;
        for (var ann : cls.getAnnotations()) {
            if ("org.junit.runner.RunWith".equals(ann.annotationType().getName()) && ann.toString().contains("DriftJUnit4")) {
                return true;
            }
        }
        return false;
    }

    static synchronized void recordStandaloneEvent(
            String canonicalTest,
            String contract,
            List<String> cases,
            String level,
            String outcome,
            List<String> read) {
        String file = eventsTarget();
        if (file == null || file.isBlank()) {
            return;
        }
        if (!standaloneHookRegistered) {
            standaloneHookRegistered = true;
            Runtime.getRuntime().addShutdownHook(new Thread(DriftListener::flushStandaloneEvents));
        }
        int hash = canonicalTest.indexOf('#');
        String className = hash > 0 ? canonicalTest.substring(0, hash) : canonicalTest;
        DISCOVERED_CLASSES.add(className);
        DISCOVERED_TESTS.computeIfAbsent(className, ignored -> new TreeSet<>()).add(canonicalTest);
        Map<String, String> inputs = Drift.recordedInputs();
        if (!inputs.isEmpty()) {
            RECORDED_INPUTS.computeIfAbsent(canonicalTest, ignored -> new TreeMap<>()).putAll(inputs);
        }
        StringBuilder line = new StringBuilder("{");
        Json.field(line, "test", canonicalTest).append(',');
        Json.field(line, "contract", contract).append(',');
        Json.field(line, "cases", cases).append(',');
        Json.field(line, "level", level).append(',');
        Json.field(line, "outcome", outcome);
        if (!read.isEmpty()) {
            Json.field(line.append(','), "read", read);
        }
        String digest = Drift.digest(contract);
        if (digest != null) {
            Json.field(line.append(','), "digest", digest);
        }
        if (Drift.isSchema03(contract)) {
            Json.field(line.append(','), "schema", "0.3");
            Json.field(line.append(','), "capabilities", Drift.requiredCapabilities(contract));
        }
        line.append("}\n");
        append(Path.of(file), line.toString());
    }

    static synchronized void flushStandaloneEvents() {
        for (Map.Entry<Path, StringBuilder> entry : BUFFERS.entrySet()) {
            if (entry.getValue().length() > 0) {
                flushBuffer(entry.getKey(), entry.getValue());
            }
        }
        BUFFERS.clear();
        for (FileChannel channel : OPEN.values()) {
            try {
                channel.close();
            } catch (IOException e) {
                throw new UncheckedIOException("cannot close an events file", e);
            }
        }
        OPEN.clear();
        writeInventory();
        PLAN_FILE.clear();
        DISCOVERED_CLASSES.clear();
        DISCOVERED_TESTS.clear();
        RECORDED_INPUTS.clear();
    }

    /**
     * The position of a dynamic test or of an invocation of a parameterized or repeated test:
     * "[3]", or "[2.3]" when nested; empty for a plain test method.
     */
    static String ordinal(TestIdentifier id) {
        StringBuilder out = new StringBuilder();
        for (UniqueId.Segment segment : id.getUniqueIdObject().getSegments()) {
            String type = segment.getType();
            if (type.equals("dynamic-test") || type.equals("dynamic-container")
                    || type.equals("test-template-invocation")) {
                out.append(out.length() == 0 ? "[" : ".").append(segment.getValue().replace("#", ""));
            }
        }
        return out.length() == 0 ? "" : out.append(']').toString();
    }

    private static int planSeq;
    private static final Map<Path, Path> PLAN_FILE = new HashMap<>();
    private static final Map<Path, FileChannel> OPEN = new HashMap<>();
    private static final Map<Path, StringBuilder> BUFFERS = new HashMap<>();
    private static final Set<String> DISCOVERED_CLASSES = new TreeSet<>();
    private static final Map<String, Set<String>> DISCOVERED_TESTS = new TreeMap<>();
    private static final Map<String, Map<String, String>> RECORDED_INPUTS = new TreeMap<>();

    /** Records discovery before selection filters exclude descriptors. */
    static synchronized void discovered(TestDescriptor descriptor) {
        if (Drift.mutationRun()) {
            return;
        }
        String evTarget = eventsTarget();
        if (evTarget == null || evTarget.isBlank() || descriptor.getSource().isEmpty()) {
            return;
        }
        var source = descriptor.getSource().get();
        String className;
        DriftCase tag = null;
        String methodName = null;
        if (source instanceof MethodSource ms) {
            if (isVintageJUnit4Handled(ms.getJavaClass(), descriptor.getUniqueId().toString())) return;
            className = ms.getClassName();
            methodName = ms.getMethodName();
            DISCOVERED_CLASSES.add(className);
            tag = tagOf(ms);
        } else if (source instanceof ClassSource cs) {
            className = cs.getClassName();
        } else {
            return;
        }
        DISCOVERED_CLASSES.add(className);
        if (tag != null && methodName != null) {
            DISCOVERED_TESTS.computeIfAbsent(className, ignored -> new TreeSet<>())
                    .add(className + "#" + methodName);
        }
    }

    @Override
    public void testPlanExecutionStarted(TestPlan plan) {
        if (Drift.mutationRun()) {
            return;
        }
        String target = System.getProperty(EVENTS);
        if (target == null || target.isBlank()) {
            return;
        }
        Path file = planFile(Path.of(target));
        try {
            Path parent = file.toAbsolutePath().getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            if (Files.notExists(file)) {
                Files.createFile(file);
            }
        } catch (IOException e) {
            throw new UncheckedIOException("cannot create an events shard", e);
        }
    }

    /** Closes the events files at the end of each test plan, so no file stays held open. */
    @Override
    public void testPlanExecutionFinished(TestPlan plan) {
        if (Drift.mutationRun()) {
            return;
        }
        synchronized (DriftListener.class) {
            for (Map.Entry<Path, StringBuilder> entry : BUFFERS.entrySet()) {
                if (entry.getValue().length() > 0) {
                    flushBuffer(entry.getKey(), entry.getValue());
                }
            }
            BUFFERS.clear();
            for (FileChannel channel : OPEN.values()) {
                try {
                    channel.close();
                } catch (IOException e) {
                    throw new UncheckedIOException("cannot close an events file", e);
                }
            }
            OPEN.clear();
            writeInventory();
            PLAN_FILE.clear();
            DISCOVERED_CLASSES.clear();
            DISCOVERED_TESTS.clear();
            RECORDED_INPUTS.clear();
        }
    }

    /**
     * One open channel per events file in this JVM; writes are buffered in memory and flushed at
     * threshold or at the end of the test plan. When {@code drift.events} names a directory (any
     * path not ending in {@code .jsonl}), each test plan writes its own
     * {@code <utcMillis>-<pid>-<seq>.jsonl} file inside it, so forked JVMs and remote workers
     * never contend on one file and lexical order is chronological.
     */
    private static synchronized void append(Path target, String line) {
        Path file = planFile(target);
        StringBuilder buf = BUFFERS.computeIfAbsent(file, ignored -> new StringBuilder(1024));
        buf.append(line);
        if (buf.length() >= BUFFER_FLUSH_THRESHOLD) {
            flushBuffer(file, buf);
        }
    }

    private static void flushBuffer(Path file, StringBuilder buf) {
        try {
            FileChannel channel = OPEN.get(file);
            if (channel == null) {
                Path parent = file.toAbsolutePath().getParent();
                if (parent != null) {
                    Files.createDirectories(parent);
                }
                channel = FileChannel.open(file, StandardOpenOption.CREATE, StandardOpenOption.WRITE,
                        StandardOpenOption.APPEND);
                OPEN.put(file, channel);
            }
            ByteBuffer bytes = ByteBuffer.wrap(buf.toString().getBytes(StandardCharsets.UTF_8));
            buf.setLength(0);
            while (bytes.hasRemaining()) {
                channel.write(bytes);
            }
        } catch (IOException e) {
            throw new UncheckedIOException("cannot append to " + file, e);
        }
    }

    private static Path planFile(Path target) {
        return target.getFileName() != null && target.getFileName().toString().endsWith(".jsonl")
                ? target
                : PLAN_FILE.computeIfAbsent(target, d -> d.resolve(String.format("%013d-%d-%04d.jsonl",
                        System.currentTimeMillis(), ProcessHandle.current().pid(), ++planSeq)));
    }

    private static void writeInventory() {
        String target = eventsTarget();
        if (target == null || target.isBlank()) {
            return;
        }
        Path eventsFile = planFile(Path.of(target));
        Path sidecar = eventsFile.resolveSibling(eventsFile.getFileName().toString()
                .substring(0, eventsFile.getFileName().toString().length() - ".jsonl".length()) + ".meta.json");
        Map<String, Set<String>> tests = new TreeMap<>();
        Set<String> classes = new TreeSet<>();
        String existingSnapshot = null;
        if (Path.of(target).getFileName() != null
                && Path.of(target).getFileName().toString().endsWith(".jsonl")
                && Files.exists(sidecar)) {
            existingSnapshot = readInventory(sidecar, classes, tests);
        }
        String snapshot = System.getProperty(SNAPSHOT);
        if (snapshot == null || snapshot.isBlank()) {
            snapshot = DriftInternal.sessionProperty("snapshot", true);
        }
        if (snapshot == null || snapshot.isBlank()) {
            snapshot = existingSnapshot;
        } else {
            snapshot = snapshot.trim();
            if (!validSnapshot(snapshot)) {
                throw new IllegalStateException("invalid drift.snapshot: " + snapshot);
            }
        }
        classes.addAll(DISCOVERED_CLASSES);
        for (String className : DISCOVERED_CLASSES) {
            tests.put(className, new TreeSet<>(DISCOVERED_TESTS.getOrDefault(className, Set.of())));
        }
        List<String> testNames = new ArrayList<>();
        for (Map.Entry<String, Set<String>> entry : tests.entrySet()) {
            testNames.addAll(entry.getValue());
        }
        String executionRef = ExecutionContext.executionRef();
        StringBuilder json = new StringBuilder("{\"version\":").append(executionRef == null ? 1 : 2).append(',');
        Json.field(json, "classes", new ArrayList<>(classes)).append(',');
        Json.field(json, "tests", testNames);
        if (executionRef != null) {
            Json.field(json.append(','), "execution_ref", executionRef);
        }
        if (snapshot != null && !snapshot.isBlank()) {
            Json.field(json.append(','), "snapshot", snapshot);
        }
        ExecutionContext.appendTail(json, executionRef);
        if (!RECORDED_INPUTS.isEmpty()) {
            json.append(",\"inputs\":{");
            boolean firstTest = true;
            for (Map.Entry<String, Map<String, String>> entry : RECORDED_INPUTS.entrySet()) {
                if (entry.getValue().isEmpty()) {
                    continue;
                }
                if (!firstTest) {
                    json.append(',');
                }
                firstTest = false;
                Json.quote(json, entry.getKey()).append(":{");
                boolean firstFile = true;
                for (Map.Entry<String, String> f : entry.getValue().entrySet()) {
                    if (!firstFile) {
                        json.append(',');
                    }
                    firstFile = false;
                    Json.field(json, f.getKey(), f.getValue());
                }
                json.append('}');
            }
            json.append('}');
        }
        Map<String, String> env = resolveEnv();
        if (env != null) {
            json.append(",\"env\":{");
            boolean firstEnv = true;
            for (Map.Entry<String, String> e : env.entrySet()) {
                if (!firstEnv) {
                    json.append(',');
                }
                firstEnv = false;
                Json.field(json, e.getKey(), e.getValue());
            }
            json.append('}');
        }
        json.append("}\n");
        try {
            Path parent = sidecar.toAbsolutePath().getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            Files.writeString(sidecar, json.toString(), StandardOpenOption.CREATE,
                    StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE);
        } catch (IOException e) {
            throw new UncheckedIOException("cannot write the test inventory " + sidecar, e);
        }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, String> resolveEnv() {
        String raw = System.getProperty(ENV, "");
        if (raw.isBlank()) {
            String envVar = System.getenv("DRIFT_ENV");
            if (envVar != null) {
                raw = envVar.trim();
            }
        } else {
            raw = raw.trim();
        }
        String pk = System.getProperty(PROOF_KEY, "");
        if (pk.isBlank()) {
            String pkVar = System.getenv("DRIFT_PROOF_KEY");
            if (pkVar != null) {
                pk = pkVar.trim();
            }
        } else {
            pk = pk.trim();
        }
        if (raw.isEmpty() && !"1".equals(pk) && !"true".equalsIgnoreCase(pk)) {
            return null;
        }
        Map<String, String> base = new TreeMap<>();
        base.put("adapter", "drift-junit@0.6.0");
        base.put("config", "default");
        base.put("deps", "none");
        base.put("drift", "0.6.0");
        base.put("policy", "core@1");
        base.put("runner", "junit-platform");
        base.put("toolchain", "java@" + System.getProperty("java.version", "unknown"));
        if (!raw.isEmpty()) {
            Object parsed = Json.parse(raw);
            if (!(parsed instanceof Map<?, ?> map)) {
                throw new IllegalArgumentException("drift.env / DRIFT_ENV must be a JSON object");
            }
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                if (!(entry.getKey() instanceof String k) || !ENV_KEYS.contains(k)
                        || !(entry.getValue() instanceof String v) || v.isBlank()) {
                    throw new IllegalArgumentException("invalid drift.env key: " + entry.getKey());
                }
                base.put(k, v.trim());
            }
        }
        return base;
    }

    private static boolean validSnapshot(String value) {
        if (value == null || (value.length() != 40 && value.length() != 64)) {
            return false;
        }
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if ((c < '0' || c > '9') && (c < 'a' || c > 'f')) {
                return false;
            }
        }
        return true;
    }

    @SuppressWarnings("unchecked")
    private static String readInventory(Path sidecar, Set<String> classes, Map<String, Set<String>> tests) {
        try {
            Object value = Json.read(sidecar);
            if (!(value instanceof Map<?, ?> raw)) {
                throw new IllegalStateException(sidecar + " is not a JSON object");
            }
            Map<String, Object> inventory = (Map<String, Object>) raw;
            Set<String> allowed = Set.of("version", "classes", "tests", "snapshot", "pack_ref",
                    "touched", "self_stubbed", "inputs", "env", "execution_ref");
            ExecutionContext.checkHead(sidecar, inventory);
            if (!inventory.containsKey("classes") || !inventory.containsKey("tests")
                    || !allowed.containsAll(inventory.keySet())
                    || !(inventory.get("classes") instanceof List<?> classList)
                    || !(inventory.get("tests") instanceof List<?> testList)) {
                throw new IllegalStateException(sidecar + " has an invalid inventory shape");
            }
            String snapshot = null;
            if (inventory.containsKey("snapshot")) {
                if (!(inventory.get("snapshot") instanceof String snap) || !validSnapshot(snap)) {
                    throw new IllegalStateException(sidecar + " has an invalid snapshot");
                }
                snapshot = snap;
            }
            List<String> sortedClasses = new ArrayList<>();
            for (Object item : classList) {
                if (!(item instanceof String className)) {
                    throw new IllegalStateException(sidecar + " has a non-string class");
                }
                if (className.isBlank() || className.indexOf('#') >= 0) {
                    throw new IllegalStateException(sidecar + " has an invalid class name");
                }
                sortedClasses.add(className);
                classes.add(className);
                tests.putIfAbsent(className, new TreeSet<>());
            }
            if (!sortedClasses.equals(sortedClasses.stream().distinct().sorted().toList())) {
                throw new IllegalStateException(sidecar + " classes are not sorted and unique");
            }
            List<String> sortedTests = new ArrayList<>();
            for (Object item : testList) {
                if (!(item instanceof String testName)) {
                    throw new IllegalStateException(sidecar + " has a non-string test");
                }
                int hash = testName.indexOf('#');
                int methodEnd = testName.indexOf('[', hash + 1);
                String method = methodEnd < 0 ? testName.substring(hash + 1) : testName.substring(hash + 1, methodEnd);
                if (hash <= 0 || hash + 1 >= testName.length()
                        || !classes.contains(testName.substring(0, hash)) || method.isBlank()
                        || method.contains("#") || method.contains(" ") || method.contains("[")
                        || method.contains("]") || testName.contains("[") || testName.contains("]")) {
                    throw new IllegalStateException(sidecar + " has an invalid test name");
                }
                sortedTests.add(testName);
                tests.computeIfAbsent(testName.substring(0, hash), ignored -> new TreeSet<>()).add(testName);
            }
            if (!sortedTests.equals(sortedTests.stream().distinct().sorted().toList())) {
                throw new IllegalStateException(sidecar + " tests are not sorted and unique");
            }
            return snapshot;
        } catch (IOException e) {
            throw new UncheckedIOException("cannot read the test inventory " + sidecar, e);
        }
    }
}
