package drift;

import static org.junit.jupiter.api.Assertions.*;
import static org.junit.platform.engine.discovery.DiscoverySelectors.selectClass;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.junit.platform.engine.*;
import org.junit.platform.engine.support.descriptor.*;
import org.junit.platform.launcher.*;
import org.junit.platform.launcher.core.*;

class DriftListenerHardeningTest {
    private static final String SNAP_A = "1111111111111111111111111111111111111111";
    private static final String SNAP_B = "2222222222222222222222222222222222222222";

    static class ContainerDisabledSamples {
        @Disabled("container disabled")
        @RepeatedTest(2)
        @DriftCase(contract = "h", cases = "a", level = "unit")
        void disabledRepeated() {
            Drift.expect("h", "a").thenInt("v");
        }

        @Disabled("plain disabled")
        @Test
        @DriftCase(contract = "h", cases = "b", level = "unit")
        void disabledPlain() {
            Drift.expect("h", "b").thenInt("v");
        }

        @Test
        @DriftCase(contract = "h", cases = "a", level = "unit")
        void activeTest() {
            Drift.expect("h", "a").thenInt("v");
        }
    }

    @Disabled("entire class disabled")
    static class DisabledClassSamples {
        @Test
        @DriftCase(contract = "h", cases = "a", level = "unit")
        void skippedWithClass() {
            Drift.expect("h", "a").thenInt("v");
        }
    }

    static class DynamicAnnotatedSamples {
        @RepeatedTest(2)
        @DriftCase(contract = "h", level = "http")
        void perInvocationDynamic(RepetitionInfo info) {
            String cid = info.getCurrentRepetition() == 1 ? "a" : "b";
            Drift.Case c = Drift.expect("h", cid);
            assertEquals(info.getCurrentRepetition() == 1 ? 1 : 2, c.thenInt("v"));
        }

        @Test
        @DriftCase(contract = "h", cases = "a", level = "unit")
        void plainSibling() {
            Drift.expect("h", "a").thenInt("v");
        }
    }

    @TempDir
    Path dir;

    private final Map<String, String> saved = new HashMap<>();

    @BeforeEach
    void setUp() throws Exception {
        Drift.clearViews();
        for (String p : List.of(Drift.RESOLVED, DriftListener.EVENTS, DriftListener.SNAPSHOT,
                DriftListener.ENV, DriftSelect.SELECT, "drift.contracts")) {
            saved.put(p, System.getProperty(p));
            System.clearProperty(p);
        }
        Path resolved = Files.createDirectories(dir.resolve("resolved"));
        Files.writeString(resolved.resolve("h.json"),
                "{\"id\":\"h\",\"cases\":{\"a\":{\"then\":{\"v\":1}},\"b\":{\"then\":{\"v\":2}}},\"ref\":\"dr1:aaaaaaaaaaaa\"}");
        System.setProperty(Drift.RESOLVED, resolved.toString());
    }

    @AfterEach
    void tearDown() {
        Drift.end();
        Drift.clearViews();
        saved.forEach((k, v) -> {
            if (v == null) System.clearProperty(k);
            else System.setProperty(k, v);
        });
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> readJson(Path file) throws Exception {
        return (Map<String, Object>) Json.read(file);
    }

    @Test
    @SuppressWarnings("unchecked")
    void f2DisabledContainerAndClassAreDroppedFromInventoryTests() throws Exception {
        Path ev = dir.resolve("f2.jsonl");
        System.setProperty(DriftListener.EVENTS, ev.toString());
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(ContainerDisabledSamples.class), selectClass(DisabledClassSamples.class))
                .build());

        Map<String, Object> meta = readJson(dir.resolve("f2.meta.json"));
        List<String> classes = (List<String>) meta.get("classes");
        List<String> tests = (List<String>) meta.get("tests");
        assertTrue(classes.contains(ContainerDisabledSamples.class.getName()));
        assertTrue(classes.contains(DisabledClassSamples.class.getName()));
        assertTrue(tests.contains(ContainerDisabledSamples.class.getName() + "#activeTest"));
        assertTrue(tests.contains(ContainerDisabledSamples.class.getName() + "#disabledPlain"));
        assertFalse(tests.contains(ContainerDisabledSamples.class.getName() + "#disabledRepeated"));
        assertFalse(tests.contains(DisabledClassSamples.class.getName() + "#skippedWithClass"));

        List<Map<String, Object>> events = new ArrayList<>();
        for (String line : Files.readAllLines(ev)) {
            events.add((Map<String, Object>) Json.parse(line));
        }
        assertTrue(events.stream().anyMatch(e -> String.valueOf(e.get("test")).endsWith("#disabledPlain")
                && "disabled".equals(e.get("outcome"))));
        assertFalse(events.stream().anyMatch(e -> String.valueOf(e.get("test")).contains("disabledRepeated")));
    }

    @Test
    void f3InvalidSnapshotAndEnvFailFastWithoutOrphanJsonlOrLeakedState() throws Exception {
        Path evDir = dir.resolve("f3");
        System.setProperty(DriftListener.EVENTS, evDir.toString());
        System.setProperty(DriftListener.SNAPSHOT, "snap-invalid-123");

        assertThrows(IllegalStateException.class, DriftSelect::new);
        assertThrows(IllegalStateException.class, () -> Drift.expect("h", "a"));
        assertFalse(Files.exists(evDir));

        System.clearProperty(DriftListener.SNAPSHOT);
        System.setProperty(DriftListener.ENV, "[]");
        assertThrows(IllegalArgumentException.class, DriftSelect::new);
        assertThrows(IllegalArgumentException.class, () -> Drift.expect("h", "a"));
        assertFalse(Files.exists(evDir));

        // After failed config validation, a valid run in the same JVM succeeds cleanly.
        System.clearProperty(DriftListener.ENV);
        System.setProperty(DriftListener.SNAPSHOT, SNAP_A);
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(ContainerDisabledSamples.class)).build());
        try (var s = Files.list(evDir)) {
            List<Path> metas = s.filter(p -> p.toString().endsWith(".meta.json")).toList();
            assertEquals(1, metas.size());
            assertEquals(SNAP_A, readJson(metas.get(0)).get("snapshot"));
        }
    }

    @Test
    void f4SingleFileModeRejectsSnapshotMismatchAndPreservesPriorFile() throws Exception {
        Path ev = dir.resolve("single.jsonl");
        System.setProperty(DriftListener.EVENTS, ev.toString());
        System.setProperty(DriftListener.SNAPSHOT, SNAP_A);
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(ContainerDisabledSamples.class)).build());
        String beforeJsonl = Files.readString(ev);
        String beforeMeta = Files.readString(dir.resolve("single.meta.json"));

        // Different snapshot must fail fast, print diagnostic to stderr, and leave files untouched.
        System.setProperty(DriftListener.SNAPSHOT, SNAP_B);
        PrintStream oldErr = System.err;
        ByteArrayOutputStream errBuf = new ByteArrayOutputStream();
        try {
            System.setErr(new PrintStream(errBuf));
            assertThrows(IllegalStateException.class, DriftSelect::new);
        } finally {
            System.setErr(oldErr);
        }
        assertTrue(errBuf.toString().contains("drift: snapshot mismatch for "), errBuf.toString());
        assertThrows(IllegalStateException.class, () -> Drift.expect("h", "a"));
        assertEquals(beforeJsonl, Files.readString(ev));
        assertEquals(beforeMeta, Files.readString(dir.resolve("single.meta.json")));

        // Unset snapshot against snapshotted sidecar must also fail fast.
        System.clearProperty(DriftListener.SNAPSHOT);
        assertThrows(IllegalStateException.class, DriftSelect::new);
        assertEquals(beforeJsonl, Files.readString(ev));

        // Same snapshot merges cleanly.
        System.setProperty(DriftListener.SNAPSHOT, SNAP_A);
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(DynamicAnnotatedSamples.class)).build());
        assertEquals(SNAP_A, readJson(dir.resolve("single.meta.json")).get("snapshot"));
    }

    @Test
    @SuppressWarnings("unchecked")
    void f5EmptyCasesAnnotationEmitsSingleCasePerInvocationAndIsDiscovered() throws Exception {
        Path ev = dir.resolve("f5.jsonl");
        System.setProperty(DriftListener.EVENTS, ev.toString());
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(DynamicAnnotatedSamples.class)).build());

        Map<String, Object> meta = readJson(dir.resolve("f5.meta.json"));
        List<String> tests = (List<String>) meta.get("tests");
        assertTrue(tests.contains(DynamicAnnotatedSamples.class.getName() + "#perInvocationDynamic"));

        List<Map<String, Object>> dynEvents = new ArrayList<>();
        for (String line : Files.readAllLines(ev)) {
            Map<String, Object> row = (Map<String, Object>) Json.parse(line);
            if (String.valueOf(row.get("test")).contains("perInvocationDynamic")) {
                dynEvents.add(row);
            }
        }
        assertEquals(2, dynEvents.size());
        assertEquals(List.of("a"), dynEvents.get(0).get("cases"));
        assertEquals("http", dynEvents.get(0).get("level"));
        assertEquals(List.of("a"), dynEvents.get(0).get("read"));
        assertEquals(List.of("b"), dynEvents.get(1).get("cases"));
        assertEquals("http", dynEvents.get(1).get("level"));
        assertEquals(List.of("b"), dynEvents.get(1).get("read"));
    }

    @Test
    @SuppressWarnings("unchecked")
    void f7ClassSourceDisplayNameWithSpacesAndBracketsIsSanitizedForInventory() throws Exception {
        Path ev = dir.resolve("f7.jsonl");
        System.setProperty(DriftListener.EVENTS, ev.toString());
        DriftListener listener = new DriftListener();
        TestDescriptor root = new AbstractTestDescriptor(UniqueId.root("eng", "e"), "root") {
            @Override public Type getType() { return Type.CONTAINER; }
        };
        TestDescriptor child = new AbstractTestDescriptor(
                root.getUniqueId().append("test", "1"),
                "allows non-matching regex [1] (x)",
                ClassSource.from(ContainerDisabledSamples.class)) {
            @Override public Type getType() { return Type.TEST; }
        };
        root.addChild(child);
        TestIdentifier tid = TestIdentifier.from(child);

        listener.testPlanExecutionStarted(null);
        listener.executionStarted(tid);
        Drift.expect("h", "a", "unit").thenInt("v");
        listener.executionFinished(tid, TestExecutionResult.successful());
        listener.testPlanExecutionFinished(null);

        Map<String, Object> meta = readJson(dir.resolve("f7.meta.json"));
        List<String> tests = (List<String>) meta.get("tests");
        assertEquals(1, tests.size());
        String tidOut = tests.get(0);
        assertFalse(tidOut.contains(" "), tidOut);
        assertFalse(tidOut.contains("["), tidOut);
        assertFalse(tidOut.contains("]"), tidOut);
        assertFalse(tidOut.contains("("), tidOut);

        // Verify DriftListener.readInventory accepts the written sidecar on a second single-file run.
        listener.testPlanExecutionStarted(null);
        listener.testPlanExecutionFinished(null);
    }
}
