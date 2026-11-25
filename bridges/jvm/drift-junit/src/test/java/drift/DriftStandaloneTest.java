package drift;

import static org.junit.jupiter.api.Assertions.*;
import static org.junit.platform.engine.discovery.DiscoverySelectors.selectClass;

import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.junit.platform.launcher.core.*;

class DriftStandaloneTest {
    @TempDir Path dir;
    private String oldResolved;
    private String oldEvents;

    @BeforeEach
    void setUp() throws Exception {
        Drift.clearViews();
        Drift.resetStandalone();
        oldResolved = System.getProperty(Drift.RESOLVED);
        oldEvents = System.getProperty(DriftListener.EVENTS);
        Path resolved = Files.createDirectories(dir.resolve("resolved"));
        Files.writeString(resolved.resolve("s03.json"), """
                {
                  "drift":"0.3",
                  "id":"s03",
                  "ref":"dr2b:222222222222",
                  "cases":{
                    "case-a":{"at":["unit"],"when":{"x":{"eq":1}},"then":{"ok":{"eq":true},"printed":{"eq":"{}"}}},
                    "case-b":{"at":["unit"],"when":{"x":{"eq":2}},"then":{"ok":{"eq":true},"printed":{"eq":"[]"}}},
                    "case-nested":{"at":["unit"],"when":{"x":{"eq":3}},"then":{"rows":{"eq":[{"ok":true,"printed":"a"}]},"obj":{"eq":{}},"arr":{"eq":[]}}}
                  }
                }
                """);
        Files.writeString(resolved.resolve("proj03.json"), """
                {
                  "drift":"0.3",
                  "id":"proj03",
                  "ref":"dr2b:333333333333",
                  "projections":{"then":{"status":"/result/status","name":"/result/items/0/name"}},
                  "cases":{
                    "found":{"at":["http"],"when":{"id":{"eq":1}},"then":{"status":{"eq":200},"name":{"eq":"ok"}}}
                  }
                }
                """);
        System.setProperty(Drift.RESOLVED, resolved.toString());
    }

    @AfterEach
    void tearDown() {
        Drift.end();
        Drift.resetStandalone();
        if (oldResolved == null) System.clearProperty(Drift.RESOLVED);
        else System.setProperty(Drift.RESOLVED, oldResolved);
        if (oldEvents == null) System.clearProperty(DriftListener.EVENTS);
        else System.setProperty(DriftListener.EVENTS, oldEvents);
    }

    // Mimics Scala 3 case class (compiler emits _1, _2 AND productPrefix/productArity/productElementName/productElement).
    public static final class Scala3CaseClass {
        private final boolean ok;
        private final String printed;

        public Scala3CaseClass(boolean ok, String printed) { this.ok = ok; this.printed = printed; }
        public Object _1() { return ok; }
        public Object _2() { return printed; }
        public String productPrefix() { return "DeepDropResult"; }
        public int productArity() { return 2; }
        public String productElementName(int n) { return n == 0 ? "ok" : "printed"; }
        public Object productElement(int n) { return n == 0 ? ok : printed; }
    }

    // Mimics specialized scala.Tuple2$mcII$sp (productPrefix() == "Tuple2").
    public static final class ScalaSpecializedTuple2 {
        private final Object a;
        private final Object b;

        public ScalaSpecializedTuple2(Object a, Object b) { this.a = a; this.b = b; }
        public Object _1() { return a; }
        public Object _2() { return b; }
        public String productPrefix() { return "Tuple2"; }
    }

    // Mimics Scala immutable/mutable Map (not a java.util.Map, has Scala-style iterator()).
    public static final class FakeScalaMap implements scala.collection.Map<Object, Object> {
        private final List<Object> pairs;

        public FakeScalaMap(List<Object> pairs) { this.pairs = pairs; }

        @Override
        public Object iterator() {
            return new Object() {
                int i = 0;
                public boolean hasNext() { return i < pairs.size(); }
                public Object next() { return pairs.get(i++); }
            };
        }
    }

    // Mimics Scala List.empty (not a Scala Map, has Scala-style iterator()).
    public static final class FakeScalaList {
        private final List<Object> items;

        public FakeScalaList(List<Object> items) { this.items = items; }

        public Object iterator() {
            return new Object() {
                int i = 0;
                public boolean hasNext() { return i < items.size(); }
                public Object next() { return items.get(i++); }
            };
        }
    }

    @Test
    @SuppressWarnings("unchecked")
    void f1StandaloneThreadLocalResetsAcrossLambdaTestsAndNeverLeaksSelfStub() throws Exception {
        Drift.end();
        Path evDir = Files.createDirectories(dir.resolve("f1-events"));
        System.setProperty(DriftListener.EVENTS, evDir.toString());

        // Simulate MUnit closure tests running sequentially on the same worker thread.
        demo.MUnitCaller.runExpectVerify("s03", "case-a", true, null, "ok", true, "printed", "{}");
        demo.MUnitCaller.runExpectVerify("s03", "case-b", false, null, "ok", true, "printed", "[]");
        // Abandoned expect + self-stub before next test must also not leak.
        demo.MUnitCaller.runAbandonedSelfStub("s03", "case-a");
        demo.MUnitCaller.runExpectVerify("s03", "case-b", false, null, "ok", true, "printed", "[]");
        Drift.flushEvents();

        List<Path> shards = Files.list(evDir).filter(p -> p.toString().endsWith(".jsonl")).sorted().toList();
        assertEquals(1, shards.size());
        List<String> lines = Files.readAllLines(shards.get(0));
        assertEquals(3, lines.size());
        Map<String, Object> ev0 = (Map<String, Object>) Json.parse(lines.get(0));
        Map<String, Object> ev1 = (Map<String, Object>) Json.parse(lines.get(1));
        Map<String, Object> ev2 = (Map<String, Object>) Json.parse(lines.get(2));
        assertTrue(String.valueOf(ev0.get("test")).endsWith("#case-a"), "got " + ev0.get("test"));
        assertTrue(String.valueOf(ev1.get("test")).endsWith("#case-b"), "got " + ev1.get("test"));
        assertNotEquals(ev0.get("test"), ev1.get("test"));
        assertNull(ev0.get("observations"), "self-stubbed case-a must omit observations");
        assertNotNull(ev1.get("observations"), "subsequent case-b must emit clean observations");
        assertNotNull(ev2.get("observations"), "case-b after abandoned self-stub must emit clean observations");

        Path metaFile = shards.get(0).resolveSibling(shards.get(0).getFileName().toString().replace(".jsonl", ".meta.json"));
        Map<String, Object> meta = (Map<String, Object>) Json.read(metaFile);
        Map<String, Object> inputs = (Map<String, Object>) meta.get("inputs");
        assertTrue(inputs.containsKey(ev0.get("test")));
        assertFalse(inputs.containsKey(ev1.get("test")), "self-stub leaked into case-b inputs: " + inputs);
    }

    @Test
    void f2AndF9Scala3CaseClassSpecializedTuple2AndEmptyScalaMap() {
        Drift.begin(null);
        Drift.Case c = Drift.expect("s03", "case-a", "unit");
        assertDoesNotThrow(() -> c.verify(new Scala3CaseClass(true, "{}")));
        assertDoesNotThrow(() -> c.verify(
                new ScalaSpecializedTuple2("ok", true),
                new ScalaSpecializedTuple2("printed", "{}")));

        Drift.Case cn = Drift.expect("s03", "case-nested", "unit");
        assertDoesNotThrow(() -> cn.verify(
                new ScalaSpecializedTuple2("rows", new FakeScalaList(List.of(new Scala3CaseClass(true, "a")))),
                new ScalaSpecializedTuple2("obj", new FakeScalaMap(List.of())),
                new ScalaSpecializedTuple2("arr", new FakeScalaList(List.of()))));
        // Empty Scala Map must NOT match [] and empty Scala List must NOT match {}
        assertThrows(AssertionError.class, () -> cn.verify(
                "rows", List.of(new Scala3CaseClass(true, "a")),
                "obj", new FakeScalaList(List.of()),
                "arr", List.of()));
        assertThrows(AssertionError.class, () -> cn.verify(
                "rows", List.of(new Scala3CaseClass(true, "a")),
                "obj", new FakeScalaMap(List.of()),
                "arr", new FakeScalaMap(List.of())));
        Drift.end();
    }

    @Test
    @SuppressWarnings("unchecked")
    void f3SelfStubViaDriftStubDetectedInStandaloneMode() throws Exception {
        Drift.end();
        Path evFile = dir.resolve("f3.jsonl");
        System.setProperty(DriftListener.EVENTS, evFile.toString());
        Drift.Case c = Drift.expect("s03", "case-a", "unit");
        c.verify(Drift.stub("s03", "case-a"));
        Drift.flushEvents();

        Map<String, Object> ev = (Map<String, Object>) Json.parse(Files.readAllLines(evFile).get(0));
        assertNull(ev.get("observations"), "self-stub via Drift.stub must suppress observations");
        Map<String, Object> meta = (Map<String, Object>) Json.read(dir.resolve("f3.meta.json"));
        Map<String, Object> inputs = (Map<String, Object>) meta.get("inputs");
        assertNotNull(inputs);
        Map<String, Object> testIn = (Map<String, Object>) inputs.values().iterator().next();
        assertEquals("sha256:self-stub", testIn.get(".drift/self-stub/s03"));
    }

    @Test
    @SuppressWarnings("unchecked")
    void f4FlushEventsIsIdempotentInDirectoryAndSingleFileModes() throws Exception {
        Drift.end();
        Path evDir = Files.createDirectories(dir.resolve("f4-dir"));
        Path fixture = Files.writeString(dir.resolve("in.txt"), "hello");
        System.setProperty(DriftListener.EVENTS, evDir.toString());

        demo.MUnitCaller.runExpectVerify("s03", "case-a", false, fixture, "ok", true, "printed", "{}");
        Drift.flushEvents();
        Drift.flushEvents(); // redundant flush must be a no-op
        demo.MUnitCaller.runExpectVerify("s03", "case-b", false, null, "ok", true, "printed", "[]");
        Drift.flushEvents();
        Drift.flushEvents(); // simulates shutdown hook after afterAll

        List<Path> jsonls = Files.list(evDir).filter(p -> p.toString().endsWith(".jsonl")).toList();
        List<Path> metas = Files.list(evDir).filter(p -> p.toString().endsWith(".meta.json")).toList();
        assertEquals(1, jsonls.size(), "must keep single cumulative shard");
        assertEquals(1, metas.size(), "must not mint extra meta shards");
        Map<String, Object> meta = (Map<String, Object>) Json.read(metas.get(0));
        assertEquals(2, ((List<?>) meta.get("tests")).size());
        assertNotNull(meta.get("inputs"));

        // Single-file mode must preserve inputs across repeated flushes
        Path single = dir.resolve("f4-single.jsonl");
        System.setProperty(DriftListener.EVENTS, single.toString());
        demo.MUnitCaller.runExpectVerify("s03", "case-a", false, fixture, "ok", true, "printed", "{}");
        Drift.flushEvents();
        Drift.flushEvents();
        Map<String, Object> singleMeta = (Map<String, Object>) Json.read(dir.resolve("f4-single.meta.json"));
        assertNotNull(singleMeta.get("inputs"), "repeated flush must not wipe single-file inputs");
    }

    @Test
    @SuppressWarnings("unchecked")
    void f5StandaloneMutatedInputFailsEvent() throws Exception {
        Drift.end();
        Path evFile = dir.resolve("f5.jsonl");
        Path fixture = Files.writeString(dir.resolve("mut.txt"), "v1");
        System.setProperty(DriftListener.EVENTS, evFile.toString());

        Drift.Case c = Drift.expect("s03", "case-a", "unit");
        Drift.recordInput(fixture);
        Files.writeString(fixture, "v2-tampered");
        c.verify("ok", true, "printed", "{}");
        Drift.flushEvents();

        Map<String, Object> ev = (Map<String, Object>) Json.parse(Files.readAllLines(evFile).get(0));
        assertEquals("failed", ev.get("outcome"));
        assertNull(ev.get("observations"));
    }

    @Test
    @SuppressWarnings("unchecked")
    void f6ParenthesesInTestIdCanonicalizedInMetaJson() throws Exception {
        Drift.end();
        assertEquals("pkg.Suite#parse", DriftListener.canonicalId("pkg.Suite#parse(ok)"));
        assertEquals("pkg.Suite#parse", DriftListener.canonicalId("pkg.Suite#parse[1]"));
        Path evFile = dir.resolve("f6.jsonl");
        Path fixture = Files.writeString(dir.resolve("f6.txt"), "x");
        System.setProperty(DriftListener.EVENTS, evFile.toString());
        Drift.recordInput(fixture);
        DriftListener.recordStandaloneEvent(
                "pkg.Suite#parse(ok)", "s03", List.of("case-a"), "unit", "passed", List.of("case-a"));
        Drift.flushEvents();

        Map<String, Object> ev = (Map<String, Object>) Json.parse(Files.readAllLines(evFile).get(0));
        assertEquals("pkg.Suite#parse(ok)", ev.get("test"));
        Map<String, Object> meta = (Map<String, Object>) Json.read(dir.resolve("f6.meta.json"));
        assertEquals(List.of("pkg.Suite#parse"), meta.get("tests"));
        assertTrue(((Map<?, ?>) meta.get("inputs")).containsKey("pkg.Suite#parse"));
    }

    static class ProjectedJUnit5Sample {
        @Test
        @DriftCase(contract = "proj03", cases = "found", level = "http")
        void projectedOk() {
            Drift.Case c = Drift.expect("proj03", "found");
            c.checkProjection(Map.of(
                    "result", Map.of("status", 200, "items", List.of(Map.of("name", "ok", "secret", "drop"))),
                    "extra", "ignored"));
        }

        @Test
        @DriftCase(contract = "proj03", cases = "found", level = "http")
        void projectedCustomCallbackWithholdsObs() {
            Drift.Case c = Drift.expect("proj03", "found");
            c.checkProjection(
                    Map.of("result", Map.of("status", 200, "items", List.of(Map.of("name", "ok")))),
                    Map.of("name", v -> assertEquals("ok", v)));
        }
    }

    @Test
    @SuppressWarnings("unchecked")
    void f7ProjectedObservationsEmittedForCheckProjectionAndVerify() throws Exception {
        Path j5Ev = dir.resolve("f7-j5.jsonl");
        System.setProperty(DriftListener.EVENTS, j5Ev.toString());
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(ProjectedJUnit5Sample.class)).build());
        List<String> j5Lines = Files.readAllLines(j5Ev);
        assertEquals(2, j5Lines.size());
        Map<String, Object> okEv = j5Lines.stream()
                .map(l -> (Map<String, Object>) Json.parse(l))
                .filter(m -> String.valueOf(m.get("test")).endsWith("#projectedOk"))
                .findFirst().orElseThrow();
        Map<String, Object> customEv = j5Lines.stream()
                .map(l -> (Map<String, Object>) Json.parse(l))
                .filter(m -> String.valueOf(m.get("test")).endsWith("#projectedCustomCallbackWithholdsObs"))
                .findFirst().orElseThrow();
        Map<String, Object> env = (Map<String, Object>) ((Map<String, Object>) okEv.get("observations")).get("found");
        assertEquals(Map.of("result", Map.of("status", 200L, "items", List.of(Map.of("name", "ok")))), env.get("payload"));
        assertNull(customEv.get("observations"));

        // Standalone checkProjection and verify with [projections.then]
        Drift.end();
        Path stEv = dir.resolve("f7-standalone.jsonl");
        System.setProperty(DriftListener.EVENTS, stEv.toString());
        Map<String, Object> payload = Map.of("result", Map.of("status", 200, "items", List.of(Map.of("name", "ok"))));
        Drift.Case c1 = Drift.expect("proj03", "found", "http");
        c1.checkProjection(payload);
        Drift.Case c2 = Drift.expect("proj03", "found", "http");
        c2.verify(payload);
        Drift.flushEvents();
        List<String> stLines = Files.readAllLines(stEv);
        assertEquals(2, stLines.size());
        for (String line : stLines) {
            Map<String, Object> m = (Map<String, Object>) Json.parse(line);
            assertEquals("passed", m.get("outcome"));
            Map<String, Object> o = (Map<String, Object>) ((Map<String, Object>) m.get("observations")).get("found");
            assertEquals(Map.of("result", Map.of("status", 200L, "items", List.of(Map.of("name", "ok")))), o.get("payload"));
        }
    }

    static class EnvOnlySample {
        @Test
        @DriftCase(contract = "missing-contract", cases = "x", level = "unit")
        void missingContractMustFail() {}
    }

    public static void main(String[] args) {
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(EnvOnlySample.class)).build());
    }

    @Test
    @SuppressWarnings("unchecked")
    void f8JUnit5RespectsEnvVarsForEventsAndResolved() throws Exception {
        Path evDir = Files.createDirectories(dir.resolve("f8-ev"));
        ProcessBuilder pb = new ProcessBuilder(
                Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                "-cp", System.getProperty("java.class.path"),
                DriftStandaloneTest.class.getName());
        pb.environment().put("DRIFT_EVENTS", evDir.toString());
        pb.environment().put("DRIFT_RESOLVED", dir.resolve("resolved").toString());
        pb.redirectErrorStream(true);
        Process p = pb.start();
        String out = new String(p.getInputStream().readAllBytes());
        assertEquals(0, p.waitFor(), out);

        List<Path> shards = Files.list(evDir).filter(f -> f.toString().endsWith(".jsonl")).toList();
        assertEquals(1, shards.size(), "testPlanExecutionStarted must create shard via DRIFT_EVENTS");
        Map<String, Object> ev = (Map<String, Object>) Json.parse(Files.readAllLines(shards.get(0)).get(0));
        assertEquals("failed", ev.get("outcome"), "write() must mark missing contract failed via DRIFT_RESOLVED");
    }

    @Test
    @SuppressWarnings("unchecked")
    void f5StandaloneRunCaseFromSameJavaMethodDisambiguatesTestIds() throws Exception {
        Drift.end();
        Path evDir = Files.createDirectories(dir.resolve("f5-same-method"));
        System.setProperty(DriftListener.EVENTS, evDir.toString());

        demo.MUnitCaller.runTwoStandaloneCasesSameMethod("s03", "case-a", "case-b");
        Drift.flushEvents();

        List<Path> shards = Files.list(evDir).filter(p -> p.toString().endsWith(".jsonl")).sorted().toList();
        assertEquals(1, shards.size());
        List<String> lines = Files.readAllLines(shards.get(0));
        assertEquals(2, lines.size(), lines.toString());
        Map<String, Object> ev0 = (Map<String, Object>) Json.parse(lines.get(0));
        Map<String, Object> ev1 = (Map<String, Object>) Json.parse(lines.get(1));
        assertEquals("demo.MUnitCaller#runTwoStandaloneCasesSameMethod[case-a]", ev0.get("test"));
        assertEquals("demo.MUnitCaller#runTwoStandaloneCasesSameMethod[case-b]", ev1.get("test"));
        assertEquals("passed", ev0.get("outcome"));
        assertEquals("passed", ev1.get("outcome"));

        Path metaFile = shards.get(0).resolveSibling(shards.get(0).getFileName().toString().replace(".jsonl", ".meta.json"));
        Map<String, Object> meta = (Map<String, Object>) Json.read(metaFile);
        List<String> tests = (List<String>) meta.get("tests");
        assertEquals(List.of("demo.MUnitCaller#runTwoStandaloneCasesSameMethod"), tests);
    }
}
