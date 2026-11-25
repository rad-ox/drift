package drift;

import static java.nio.file.Files.*;
import static drift.Json.*;
import java.io.*;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import static java.nio.file.StandardOpenOption.*;
import java.util.*;
import java.util.concurrent.*;
import org.junit.platform.engine.*;
import org.junit.platform.engine.support.descriptor.*;
import org.junit.platform.launcher.*;

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
        var src = id.getSource().orElse(null);
        if (src instanceof ClassSource) return true;
        if (src instanceof MethodSource ms) {
            try { ms.getJavaMethod(); return false; } catch (RuntimeException e) { return true; }
        }
        return false;
    }

    @Override
    public void executionSkipped(TestIdentifier id, String reason) {
        if (!Drift.mutationRun()) {
            DriftCase tag = id.isTest() ? tagOf(id) : null;
            if (tag != null && tag.cases().length > 0) {
                write(id, "disabled", tag);
            } else if (id.getSource().isPresent()) {
                var src = id.getSource().get();
                synchronized (DriftListener.class) {
                    if (src instanceof MethodSource ms) {
                        DISCOVERED_CLASSES.add(ms.getClassName());
                        Set<String> s = DISCOVERED_TESTS.get(ms.getClassName());
                        if (s != null) s.remove(canonicalId(ms.getClassName() + "#" + ms.getMethodName()));
                    } else if (src instanceof ClassSource cs) {
                        String cn = cs.getClassName();
                        DISCOVERED_CLASSES.add(cn);
                        DISCOVERED_TESTS.keySet().removeIf(k -> k.equals(cn) || k.startsWith(cn + "$"));
                    }
                }
            }
        }
        if (id.isTest()) Drift.end();
    }

    @Override
    public void executionFinished(TestIdentifier id, TestExecutionResult result) {
        if (!id.isTest()) {
            return;
        }
        try {
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
        } finally {
            Drift.end();
        }
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
        return id.getSource().orElse(null) instanceof MethodSource ms ? tagOf(ms) : null;
    }

    private static void write(TestIdentifier id, String outcome, DriftCase tag) {
        String file = eventsTarget();
        if (file == null || tag == null || tag.contract().isEmpty() || tag.cases().length == 0 || id.getSource().isEmpty()) {
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
            methodName = id.getDisplayName().trim().replaceAll("[#\\s\\[\\]()]+", "_");
            if (methodName.isEmpty()) methodName = "test";
        } else {
            return;
        }
        String resolvedDir = Drift.resolvedDir();
        boolean hasContract = Drift.hasContract(tag.contract());
        if (resolvedDir != null && !resolvedDir.isBlank() && !hasContract
                && "passed".equals(outcome)) {
            outcome = "failed";
        }
        if ("passed".equals(outcome) && (!Drift.inputsUnchanged() || DriftWhen.listenerFallbackViolated(tag))) {
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
        String rawTest = className + "#" + methodName;
        String canonicalTest = canonicalId(rawTest);
        String test = rawTest + ordinal(id);
        Map<String, String> inputs = Drift.recordedInputs();
        synchronized (DriftListener.class) {
            if (DriftVerify.isDynamicTag(tag)) {
                DISCOVERED_CLASSES.add(className);
                DISCOVERED_TESTS.computeIfAbsent(className, k -> new TreeSet<>()).add(canonicalTest);
            }
            if (!inputs.isEmpty()) RECORDED_INPUTS.computeIfAbsent(canonicalTest, k -> new TreeMap<>()).putAll(inputs);
        }
        appendEvent(Path.of(file), test, tag.contract(), List.of(tag.cases()), tag.level(), outcome, read);
    }

    static String canonicalId(String test) {
        int h = test.indexOf('#');
        if (h <= 0) return test;
        for (int i = h + 1; i < test.length(); i++) {
            char c = test.charAt(i);
            if ((c == '(' || c == '[') && i > h + 1) return test.substring(0, i);
        }
        return test;
    }

    static String propOrEnv(String prop, String env) {
        String p = System.getProperty(prop);
        if (p != null && !p.isBlank()) return p.trim();
        String e = System.getenv(env);
        return e != null && !e.isBlank() ? e.trim() : null;
    }

    private static void appendEvent(Path p, String test, String contract, List<String> cases, String level, String outcome, List<String> read) {
        StringBuilder line = new StringBuilder("{");
        field(line, "test", test).append(',');
        field(line, "contract", contract).append(',');
        field(line, "cases", cases).append(',');
        field(line, "level", level).append(',');
        field(line, "outcome", outcome);
        if (!read.isEmpty()) field(line.append(','), "read", read);
        String digest = Drift.digest(contract);
        if (digest != null) field(line.append(','), "digest", digest);
        if (Drift.isSchema03(contract)) {
            field(line.append(','), "schema", "0.3");
            field(line.append(','), "capabilities", Drift.requiredCapabilities(contract));
            DriftObservations.appendField(line, contract, outcome, read);
        }
        append(p, line.append("}\n").toString());
    }

    private static String eventsTarget() {
        String direct = propOrEnv(EVENTS, "DRIFT_EVENTS");
        return direct != null ? direct : DriftInternal.sessionProperty("events", true);
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
            String rawTest,
            String contract,
            List<String> cases,
            String level,
            String outcome,
            List<String> read) {
        String file = eventsTarget();
        if (file == null) return;
        Path tgt = Path.of(file).toAbsolutePath().normalize();
        if (standaloneTarget != null && !standaloneTarget.equals(tgt)) {
            flushStandaloneEvents();
            resetState();
        }
        standaloneTarget = tgt;
        standaloneDirty = true;
        if (!standaloneHookRegistered) {
            standaloneHookRegistered = true;
            Runtime.getRuntime().addShutdownHook(new Thread(DriftListener::flushStandaloneEvents));
        }
        if ("passed".equals(outcome) && !Drift.inputsUnchanged()) outcome = "failed";
        String invTest = canonicalId(rawTest);
        int hash = invTest.indexOf('#');
        String className = hash > 0 ? invTest.substring(0, hash) : invTest;
        DISCOVERED_CLASSES.add(className);
        DISCOVERED_TESTS.computeIfAbsent(className, k -> new TreeSet<>()).add(invTest);
        Map<String, String> inputs = Drift.recordedInputs();
        if (!inputs.isEmpty()) RECORDED_INPUTS.computeIfAbsent(invTest, k -> new TreeMap<>()).putAll(inputs);
        appendEvent(tgt, rawTest, contract, cases, level, outcome, read);
    }

    static synchronized void flushStandaloneEvents() {
        if (!standaloneDirty && BUFFERS.isEmpty()) {
            return;
        }
        Path tgt = standaloneTarget;
        if (tgt == null) {
            String f = eventsTarget();
            if (f != null) tgt = Path.of(f);
        }
        try {
            if (tgt != null) flushAndWriteInventory(tgt);
            else flushOpen();
        } finally {
            try { closeOpen(); } catch (RuntimeException ignored) {}
            standaloneDirty = false;
        }
    }

    private static void flushOpen() {
        for (var entry : BUFFERS.entrySet()) {
            if (entry.getValue().length() > 0) flushBuffer(entry.getKey(), entry.getValue());
        }
        closeOpen();
    }

    private static void closeOpen() {
        IOException err = null;
        for (FileChannel ch : OPEN.values()) {
            try { ch.close(); } catch (IOException e) { if (err == null) err = e; }
        }
        OPEN.clear();
        BUFFERS.clear();
        if (err != null) throw new UncheckedIOException("cannot close an events file", err);
    }

    private static void resetState() {
        PLAN_FILE.clear();
        DISCOVERED_CLASSES.clear();
        DISCOVERED_TESTS.clear();
        RECORDED_INPUTS.clear();
        standaloneTarget = null;
        standaloneDirty = false;
    }

    private static void flushAndReset() {
        try {
            String target = eventsTarget();
            if (target != null) flushAndWriteInventory(Path.of(target));
            else flushOpen();
        } finally {
            try { closeOpen(); } catch (RuntimeException ignored) {}
            resetState();
        }
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
    private static Path standaloneTarget;
    private static boolean standaloneDirty;
    private static final Map<Path, Path> PLAN_FILE = new HashMap<>();
    private static final Map<Path, FileChannel> OPEN = new HashMap<>();
    private static final Map<Path, StringBuilder> BUFFERS = new HashMap<>();
    private static final Set<String> DISCOVERED_CLASSES = new TreeSet<>();
    private static final Map<String, Set<String>> DISCOVERED_TESTS = new TreeMap<>();
    private static final Map<String, Map<String, String>> RECORDED_INPUTS = new TreeMap<>();

    /** Records discovery before selection filters exclude descriptors. */
    static synchronized void discovered(TestDescriptor descriptor) {
        if (Drift.mutationRun() || eventsTarget() == null || descriptor.getSource().isEmpty()) return;
        var source = descriptor.getSource().get();
        String cn, mn = null;
        DriftCase tag = null;
        if (source instanceof MethodSource ms) {
            if (isVintageJUnit4Handled(ms.getJavaClass(), descriptor.getUniqueId().toString())) return;
            cn = ms.getClassName();
            mn = ms.getMethodName();
            tag = tagOf(ms);
        } else if (source instanceof ClassSource cs) {
            cn = cs.getClassName();
        } else {
            return;
        }
        DISCOVERED_CLASSES.add(cn);
        if (tag != null && mn != null) DISCOVERED_TESTS.computeIfAbsent(cn, k -> new TreeSet<>()).add(canonicalId(cn + "#" + mn));
    }

    @Override
    public void testPlanExecutionStarted(TestPlan plan) {
        if (Drift.mutationRun()) {
            return;
        }
        synchronized (DriftListener.class) {
            if (standaloneTarget != null) {
                flushStandaloneEvents();
                resetState();
            }
        }
        String target = eventsTarget();
        if (target == null) {
            return;
        }
        validateConfig();
        Path file = planFile(Path.of(target));
        try {
            mkdirs(file);
            if (notExists(file)) createFile(file);
        } catch (IOException e) {
            throw new UncheckedIOException("cannot create an events shard", e);
        }
    }

    @Override
    public void testPlanExecutionFinished(TestPlan plan) {
        if (Drift.mutationRun()) return;
        synchronized (DriftListener.class) {
            flushAndReset();
        }
    }

    private static void mkdirs(Path f) throws IOException {
        Path p = f.toAbsolutePath().getParent();
        if (p != null) createDirectories(p);
    }

    private static synchronized void append(Path target, String line) {
        Path file = planFile(target);
        StringBuilder buf = BUFFERS.computeIfAbsent(file, k -> new StringBuilder(1024));
        buf.append(line);
        if (buf.length() >= BUFFER_FLUSH_THRESHOLD) flushBuffer(file, buf);
    }

    private static void writeBuf(FileChannel ch, StringBuilder buf) throws IOException {
        ByteBuffer bytes = ByteBuffer.wrap(buf.toString().getBytes(StandardCharsets.UTF_8));
        while (bytes.hasRemaining()) ch.write(bytes);
        buf.setLength(0);
    }

    private static void flushBuffer(Path file, StringBuilder buf) {
        try {
            FileChannel ch = OPEN.get(file);
            if (ch == null) {
                mkdirs(file);
                OPEN.put(file, ch = FileChannel.open(file, CREATE, WRITE, APPEND));
            }
            writeBuf(ch, buf);
        } catch (IOException e) {
            throw new UncheckedIOException("cannot append to " + file, e);
        }
    }

    private static boolean isSingleFile(Path t) {
        return t.getFileName() != null && t.getFileName().toString().endsWith(".jsonl");
    }

    private static Path sidecarOf(Path f) {
        String n = f.getFileName().toString();
        return f.resolveSibling(n.substring(0, n.length() - 6) + ".meta.json");
    }

    private static Path planFile(Path target) {
        return isSingleFile(target) ? target
                : PLAN_FILE.computeIfAbsent(target, d -> d.resolve(String.format("%013d-%d-%04d.jsonl",
                        System.currentTimeMillis(), ProcessHandle.current().pid(), ++planSeq)));
    }

    private static String resolveSnapshot() {
        String s = propOrEnv(SNAPSHOT, "DRIFT_SNAPSHOT");
        if (s == null) s = DriftInternal.sessionProperty("snapshot", true);
        if (s != null && !validSnapshot(s = s.trim())) throw new IllegalStateException("invalid drift.snapshot: " + s);
        return s;
    }

    static void validateConfig() {
        if (Drift.mutationRun()) return;
        String target = eventsTarget();
        if (target == null) return;
        String snap = resolveSnapshot();
        resolveEnv();
        ExecutionContext.appendTail(new StringBuilder(), ExecutionContext.executionRef());
        Path t = Path.of(target);
        if (isSingleFile(t)) {
            Path sc = sidecarOf(t);
            if (exists(sc) && !Objects.equals(readInventory(sc, new TreeSet<>(), new TreeMap<>(), new TreeMap<>()), snap)) {
                String msg = "snapshot mismatch for " + sc;
                System.err.println("drift: " + msg);
                throw new IllegalStateException(msg);
            }
        }
    }

    private static void appendStrMap(StringBuilder json, Map<String, String> m) {
        json.append('{');
        boolean first = true;
        for (var e : m.entrySet()) {
            if (!first) json.append(',');
            first = false;
            field(json, e.getKey(), e.getValue());
        }
        json.append('}');
    }

    private static void flushAndWriteInventory(Path target) {
        Path ef = planFile(target), sc = sidecarOf(ef);
        String snap = resolveSnapshot(), ref = ExecutionContext.executionRef();
        Map<String, String> env = resolveEnv();
        StringBuilder tail = new StringBuilder();
        ExecutionContext.appendTail(tail, ref);
        try {
            if (isSingleFile(target)) {
                mkdirs(ef);
                FileChannel prev = OPEN.remove(ef);
                if (prev != null) prev.close();
                try (FileChannel lk = FileChannel.open(ef, CREATE, WRITE, APPEND); var ignored = lk.lock()) {
                    String inv = buildInventory(sc, true, snap, env, ref, tail);
                    StringBuilder b = BUFFERS.remove(ef);
                    if (b != null && b.length() > 0) writeBuf(lk, b);
                    flushOpen();
                    writeAtomic(sc, inv);
                }
            } else {
                String inv = buildInventory(sc, false, snap, env, ref, tail);
                flushOpen();
                writeAtomic(sc, inv);
            }
        } catch (IOException e) {
            throw new UncheckedIOException("cannot write the test inventory " + sc, e);
        }
    }

    private static String buildInventory(
            Path sidecar, boolean single, String snapshot, Map<String, String> env, String ref, StringBuilder tail) {
        Map<String, Set<String>> tests = new TreeMap<>();
        Set<String> classes = new TreeSet<>();
        Map<String, Map<String, String>> inputs = new TreeMap<>();
        if (single && exists(sidecar) && !Objects.equals(readInventory(sidecar, classes, tests, inputs), snapshot))
            throw new IllegalStateException("snapshot mismatch for " + sidecar);
        classes.addAll(DISCOVERED_CLASSES);
        for (String cn : DISCOVERED_CLASSES) tests.put(cn, new TreeSet<>(DISCOVERED_TESTS.getOrDefault(cn, Set.of())));
        List<String> testNames = new ArrayList<>();
        for (Set<String> s : tests.values()) testNames.addAll(s);
        for (var e : RECORDED_INPUTS.entrySet()) {
            if (!e.getValue().isEmpty()) inputs.computeIfAbsent(e.getKey(), k -> new TreeMap<>()).putAll(e.getValue());
        }
        inputs.keySet().retainAll(new HashSet<>(testNames));
        StringBuilder json = new StringBuilder("{\"version\":").append(ref == null ? 1 : 2).append(',');
        field(json, "classes", new ArrayList<>(classes)).append(',');
        field(json, "tests", testNames);
        if (ref != null) field(json.append(','), "execution_ref", ref);
        if (snapshot != null) field(json.append(','), "snapshot", snapshot);
        json.append(tail);
        if (!inputs.isEmpty()) {
            json.append(",\"inputs\":{");
            boolean first = true;
            for (var e : inputs.entrySet()) {
                if (e.getValue().isEmpty()) continue;
                if (!first) json.append(',');
                first = false;
                quote(json, e.getKey()).append(':');
                appendStrMap(json, e.getValue());
            }
            json.append('}');
        }
        if (env != null) appendStrMap(json.append(",\"env\":"), env);
        return json.append("}\n").toString();
    }

    private static void writeAtomic(Path sc, String json) throws IOException {
        mkdirs(sc);
        Path tmp = sc.resolveSibling(sc.getFileName() + ".tmp");
        try {
            writeString(tmp, json);
            move(tmp, sc, StandardCopyOption.REPLACE_EXISTING);
        } finally {
            deleteIfExists(tmp);
        }
    }

    private static Map<String, String> resolveEnv() {
        String raw = propOrEnv(ENV, "DRIFT_ENV"), pk = propOrEnv(PROOF_KEY, "DRIFT_PROOF_KEY");
        if (raw == null && !"1".equals(pk) && !"true".equalsIgnoreCase(pk)) return null;
        Map<String, String> base = new TreeMap<>(Map.of(
                "adapter", "drift-junit@0.11.0", "config", "default", "deps", "none",
                "drift", "0.11.0", "policy", "core@1", "runner", "junit-platform",
                "toolchain", "java@" + System.getProperty("java.version", "unknown")));
        if (raw != null) {
            if (!(Json.parse(raw) instanceof Map<?, ?> map))
                throw new IllegalArgumentException("drift.env / DRIFT_ENV must be a JSON object");
            for (var e : map.entrySet()) {
                if (!(e.getKey() instanceof String k) || !ENV_KEYS.contains(k)
                        || !(e.getValue() instanceof String v) || v.isBlank())
                    throw new IllegalArgumentException("invalid drift.env key: " + e.getKey());
                base.put(k, v.trim());
            }
        }
        return base;
    }

    private static boolean validSnapshot(String v) {
        return v != null && v.matches("[0-9a-f]{40}|[0-9a-f]{64}");
    }

    private static IllegalStateException badInv(Path sidecar, String msg) {
        return new IllegalStateException(sidecar + " " + msg);
    }

    @SuppressWarnings("unchecked")
    private static String readInventory(
            Path sidecar, Set<String> classes, Map<String, Set<String>> tests, Map<String, Map<String, String>> inputs) {
        try {
            if (!(Json.read(sidecar) instanceof Map<?, ?> raw)) throw badInv(sidecar, "is not a JSON object");
            Map<String, Object> inv = (Map<String, Object>) raw;
            Set<String> allowed = Set.of("version", "classes", "tests", "snapshot", "pack_ref",
                    "touched", "self_stubbed", "inputs", "env", "execution_ref");
            ExecutionContext.checkHead(sidecar, inv);
            if (!allowed.containsAll(inv.keySet()) || !(inv.get("classes") instanceof List<?> classList)
                    || !(inv.get("tests") instanceof List<?> testList))
                throw badInv(sidecar, "has an invalid inventory shape");
            String snapshot = null;
            if (inv.containsKey("snapshot")) {
                if (!(inv.get("snapshot") instanceof String snap) || !validSnapshot(snap))
                    throw badInv(sidecar, "has an invalid snapshot");
                snapshot = snap;
            }
            String prev = null;
            for (Object item : classList) {
                if (!(item instanceof String cn)) throw badInv(sidecar, "has a non-string class");
                if (cn.isBlank() || cn.indexOf('#') >= 0) throw badInv(sidecar, "has an invalid class name");
                if (prev != null && prev.compareTo(cn) >= 0) throw badInv(sidecar, "classes are not sorted and unique");
                prev = cn;
                classes.add(cn);
                tests.putIfAbsent(cn, new TreeSet<>());
            }
            prev = null;
            for (Object item : testList) {
                if (!(item instanceof String tn)) throw badInv(sidecar, "has a non-string test");
                int h = tn.indexOf('#');
                String cn = h > 0 ? tn.substring(0, h) : "";
                String m = h > 0 ? tn.substring(h + 1) : "";
                if (h <= 0 || !classes.contains(cn) || m.isBlank() || m.indexOf('#') >= 0
                        || m.indexOf(' ') >= 0 || tn.indexOf('[') >= 0 || tn.indexOf(']') >= 0)
                    throw badInv(sidecar, "has an invalid test name");
                if (prev != null && prev.compareTo(tn) >= 0) throw badInv(sidecar, "tests are not sorted and unique");
                prev = tn;
                tests.computeIfAbsent(cn, k -> new TreeSet<>()).add(tn);
            }
            if (inv.get("inputs") instanceof Map<?, ?> rawIn) {
                for (var e : rawIn.entrySet()) {
                    if (e.getKey() instanceof String tk && e.getValue() instanceof Map<?, ?> fm) {
                        Map<String, String> m = inputs.computeIfAbsent(tk, k -> new TreeMap<>());
                        for (var fe : fm.entrySet()) {
                            if (fe.getKey() instanceof String fk && fe.getValue() instanceof String fv) m.put(fk, fv);
                        }
                    }
                }
            }
            return snapshot;
        } catch (IOException e) {
            throw new UncheckedIOException("cannot read the test inventory " + sidecar, e);
        }
    }
}
