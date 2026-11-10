package drift;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.DynamicContainer.dynamicContainer;
import static org.junit.jupiter.api.DynamicTest.dynamicTest;
import static org.junit.platform.engine.discovery.DiscoverySelectors.selectClass;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DynamicNode;
import org.junit.jupiter.api.RepeatedTest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestFactory;
import org.junit.jupiter.api.io.TempDir;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;

/** Runs sample classes through the JUnit Platform and reads the events the listener wrote. */
class DriftBridgeTest {
    private static final String FULL = "dr1:sha256:" + "ab".repeat(32);
    private static final String REF = "dr1:abababababab";

    static class Samples {
        static void readAll() {
            Drift.expect("bridge", "all").thenInt("status");
        }

        @TestFactory
        @DriftCase(contract = "bridge", cases = "all", level = "unit")
        Stream<DynamicNode> dynamic() {
            return Stream.of(dynamicTest("one", Samples::readAll),
                    dynamicContainer("group", Stream.of(dynamicTest("two", Samples::readAll),
                            dynamicTest("three", Samples::readAll))));
        }

        @RepeatedTest(2)
        @DriftCase(contract = "bridge", cases = "all", level = "unit")
        void repeated() {
            readAll();
        }

        @Test
        @DriftCase(contract = "bridge", cases = "part", level = "partly")
        void partly() {
            Drift.expect("bridge", "part").thenInt("status");
        }

        @Test
        @DriftCase(contract = "bridge", cases = "part", level = "map")
        void throughTheMap() {
            Map<String, Object> then = Drift.expect("bridge", "part").then();
            assertEquals(200L, then.get("status"));
            assertEquals("ok", then.get("name"));
        }

        @Test
        @DriftCase(contract = "bridge", cases = "part", level = "keys")
        void keysOnly() {
            assertEquals(2, Drift.expect("bridge", "part").then().keySet().size());
        }

        @Test
        @DriftCase(contract = "bridge", cases = "part", level = "check")
        void checked() {
            Drift.expect("bridge", "part").check(Map.of(
                    "status", v -> assertEquals(200L, v),
                    "name", v -> assertEquals("ok", v),
                    "other", v -> { }));
        }

        @Test
        @DriftCase(contract = "bridge", cases = "part", level = "bounds")
        void boundsChecked() {
            Drift.expect("bridge", "part").checkBounds(Drift.intDomain(1, 100), Map.of(
                    "status", (v, sample) -> assertTrue(sample >= 1 && sample <= 100 && v.equals(200L)),
                    "name", (v, sample) -> assertEquals("ok", v)));
        }

        @Test
        @DriftCase(contract = "bridge", cases = "part", level = "projected")
        void projected() {
            Drift.Case c = Drift.expect("bridge", "part");
            Map<String, Object> input = c.buildInput(Map.of("request", "GET /items"));
            assertEquals("GET /items", input.get("request"));
            c.checkProjection(Map.of(
                    "status", 200,
                    "body", Map.of("items", List.of(Map.of("name", "ok")))));
        }

        @Test
        @DriftCase(contract = "bridge", cases = "part", level = "unchecked")
        void missingCheck() {
            Drift.expect("bridge", "part").check(Map.of("status", v -> { }));
        }

        @Test
        @DriftCase(contract = "bridge", cases = "part", level = "optional")
        void optional() {
            Drift.Case c = Drift.expect("bridge", "part");
            assertTrue(c.findWhen("absent").isEmpty());
            assertTrue(c.findThen("absent").isEmpty());
            assertEquals(200L, c.findThen("status").orElseThrow());
            assertEquals("ok", c.findThen("name").orElseThrow());
        }

        @Test
        @DriftCase(contract = "legacy", cases = "all", level = "unit")
        void legacyView() {
            Drift.expect("legacy", "all").thenInt("status");
        }
    }

    static class UnknownContract {
        @Test
        @DriftCase(contract = "no-such-contract", cases = "all", level = "unit")
        void boundOnly() { }
    }

    static class OtherSamples {
        @Test
        @DriftCase(contract = "bridge", cases = "all", level = "unit")
        void other() { }
    }

    @TempDir
    Path dir;

    private final Map<String, String> saved = new HashMap<>();

    @BeforeEach
    void isolate() throws Exception {
        Drift.clearViews();
        for (String p : List.of(Drift.RESOLVED, DriftListener.EVENTS, DriftListener.SNAPSHOT, DriftSelect.SELECT,
                DriftListener.EXECUTION_REF)) {
            saved.put(p, System.getProperty(p));
        }
        Path resolved = Files.createDirectories(dir.resolve("resolved"));
        String cases = "{\"all\":{\"then\":{\"status\":200}},\"part\":{\"then\":{\"status\":200,\"name\":\"ok\"}}}";
        String paramSpecs = "{\"limit\":{\"type\":\"int\",\"min\":1,\"max\":10},\"mode\":{\"type\":\"string\",\"enum\":[\"fast\",\"safe\"]}}";
        String projections = "{\"when\":{\"request\":\"/request\"},\"then\":{\"status\":\"/status\",\"name\":\"/body/items/0/name\"}}";
        Files.writeString(resolved.resolve("bridge.json"),
                "{\"id\":\"bridge\",\"cases\":" + cases + ",\"param_specs\":" + paramSpecs
                        + ",\"projections\":" + projections
                        + ",\"digest\":\"" + FULL + "\",\"ref\":\"" + REF + "\"}");
        Files.writeString(resolved.resolve("legacy.json"),
                "{\"id\":\"legacy\",\"cases\":" + cases + ",\"digest\":\"" + FULL + "\"}");
        System.setProperty(Drift.RESOLVED, resolved.toString());
        System.setProperty(DriftListener.EVENTS, dir.resolve("events.jsonl").toString());
        System.clearProperty(DriftListener.SNAPSHOT);
        System.clearProperty(DriftSelect.SELECT);
    }

    @AfterEach
    void restore() {
        Drift.end();
        Drift.clearViews();
        saved.forEach((k, v) -> {
            if (v == null) {
                System.clearProperty(k);
            } else {
                System.setProperty(k, v);
            }
        });
    }

    private Map<String, Map<String, Object>> run() throws Exception {
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(Samples.class)).build());
        Map<String, Map<String, Object>> byTest = new LinkedHashMap<>();
        for (String line : Files.readAllLines(dir.resolve("events.jsonl"))) {
            @SuppressWarnings("unchecked") // the listener writes one JSON object per line
            Map<String, Object> e = (Map<String, Object>) Json.parse(line);
            byTest.put(((String) e.get("test")).substring(Samples.class.getName().length() + 1)
                    + "@" + e.get("level"), e);
        }
        return byTest;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> inventory(Path file) throws Exception {
        return (Map<String, Object>) Json.read(file);
    }

    @Test
    void everyInvocationGetsItsPositionAsAShortId() throws Exception {
        assertEquals(List.of("dynamic[1]@unit", "dynamic[2.1]@unit", "dynamic[2.2]@unit",
                "repeated[1]@unit", "repeated[2]@unit"),
                new ArrayList<>(run().keySet()).stream().filter(t -> t.endsWith("@unit")
                        && !t.startsWith("legacy")).sorted().toList());
    }

    @Test
    void aCaseIsReadOnlyWhenEveryThenValueWasRead() throws Exception {
        Map<String, Map<String, Object>> events = run();
        assertEquals(List.of("all"), events.get("dynamic[2.1]@unit").get("read"));
        assertEquals(null, events.get("partly@partly").get("read"));
        assertEquals(List.of("part"), events.get("throughTheMap@map").get("read"));
        assertEquals(null, events.get("keysOnly@keys").get("read"));
        assertEquals(List.of("part"), events.get("checked@check").get("read"));
        assertEquals(List.of("part"), events.get("boundsChecked@bounds").get("read"));
        assertEquals(List.of("part"), events.get("projected@projected").get("read"));
        assertEquals(List.of("part"), events.get("optional@optional").get("read"));
        assertEquals("passed", events.get("checked@check").get("outcome"));
    }

    @Test
    @DriftCase(contract = "bridge", cases = "all", level = "bounds")
    void checkBoundsShrinksToFirstBoundaryCounterexample() {
        assertEquals(List.of(0L, -10L, -9L, 9L, 10L), Drift.intDomain(-10, 10));
        assertEquals(List.of(1L, 2L, 50L, 99L, 100L), Drift.intDomain(1, 100));
        assertEquals(4, Drift.cartesianDomain(Map.of(
                "mode", Drift.enumDomain("fast", "full"),
                "dry", Drift.boolDomain())).size());
        List<Map<String, Object>> d136 = Drift.cartesianDomain(Map.of(
                "a", Drift.intDomain(1, 100),
                "b", Drift.intDomain(1, 100),
                "c", Drift.intDomain(1, 100),
                "d", Drift.intDomain(1, 100)));
        assertEquals(1 + 4 * 4 + 6 * 16, d136.size());
        assertTrue(d136.stream().allMatch(s -> s.values().stream().filter(v -> !Long.valueOf(1L).equals(v)).count() <= 2));
        AssertionError err = null;
        try {
            Drift.expect("bridge", "all").checkBounds(Drift.intDomain(1, 100), Map.of(
                    "status", (v, sample) -> assertTrue(sample < 100 && v.equals(200L), "off-by-one at max")));
        } catch (AssertionError caught) {
            err = caught;
        }
        assertTrue(err != null && err.getMessage().contains("[counterexample: 100]"));
        assertEquals(List.of(1L, 2L, 5L, 9L, 10L), Drift.profileDomain("bridge", "limit"));
        assertEquals(10, Drift.profileDomain("bridge", List.of("limit", "mode")).size());
        Drift.expect("bridge", "all").checkProfileBounds("limit", Map.of(
                "status", (v, sample) -> assertTrue(((Long) sample) >= 1L && ((Long) sample) <= 10L && v.equals(200L))));
        Drift.expect("bridge", "all").checkView(Map.of("status", 200L));
    }

    @Test
    @DriftCase(contract = "bridge", cases = "part", level = "mutation")
    void aMutationOverrideChangesOnlyItsTargetThenLeaf() {
        Drift.setMutation("bridge", "part", "/cases/part/then/status", 503L);
        try {
            Drift.Case mutated = Drift.expect("bridge", "part");
            assertEquals(503, mutated.thenInt("status"));
            assertEquals("ok", mutated.thenString("name"));
        } finally {
            Drift.clearMutation();
        }
        assertEquals(0, Drift.mutationDepth());
        Drift.withMutation("bridge", "part", "/cases/part/then/status", 202L, () -> {
            assertEquals(1, Drift.mutationDepth());
            assertEquals(202, Drift.expect("bridge", "part").thenInt("status"));
            Drift.withMutation("bridge", "part", "/cases/part/then/status", 504L, () -> {
                assertEquals(2, Drift.mutationDepth());
                assertEquals(504, Drift.expect("bridge", "part").thenInt("status"));
            });
            assertEquals(1, Drift.mutationDepth());
            assertEquals(202, Drift.expect("bridge", "part").thenInt("status"));
        });
        assertEquals(0, Drift.mutationDepth());
        assertEquals(200, Drift.expect("bridge", "part").thenInt("status"));
    }

    @Test
    void aThenPredicateWithoutACheckFailsTheTest() throws Exception {
        assertEquals("failed", run().get("missingCheck@unchecked").get("outcome"));
    }

    @Test
    void eventsNameTheVersionByItsReferenceWhenTheViewHasOne() throws Exception {
        Map<String, Map<String, Object>> events = run();
        assertEquals(REF, events.get("partly@partly").get("digest"));
        assertEquals(FULL, events.get("legacyView@unit").get("digest"));
    }

    @Test
    void inventoryRecordsTaggedDiscoveryBeforeSelectionFiltering() throws Exception {
        Path sel = dir.resolve("select.json");
        Files.writeString(sel, "{\"all\":false,\"contract\":\"legacy\",\"cases\":[],\"tests\":[\""
                + Samples.class.getName() + "#legacyView\"]}");
        System.setProperty(DriftSelect.SELECT, sel.toString());
        assertEquals(List.of("legacyView@unit"), new ArrayList<>(run().keySet()));

        Map<String, Object> metadata = inventory(dir.resolve("events.meta.json"));
        assertEquals(1L, metadata.get("version"));
        assertEquals(List.of(Samples.class.getName()), metadata.get("classes"));
        @SuppressWarnings("unchecked")
        List<String> tests = (List<String>) metadata.get("tests");
        assertTrue(tests.contains(Samples.class.getName() + "#legacyView"));
        assertTrue(tests.contains(Samples.class.getName() + "#partly"));
        assertTrue(tests.contains(Samples.class.getName() + "#throughTheMap"));
        assertEquals(tests.stream().sorted().toList(), tests);
    }

    @Test
    void inventoriesOnOneFilePreserveClassesAbsentFromLaterPlans() throws Exception {
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(Samples.class)).build());
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(OtherSamples.class)).build());

        Map<String, Object> metadata = inventory(dir.resolve("events.meta.json"));
        assertEquals(List.of(OtherSamples.class.getName(), Samples.class.getName()), metadata.get("classes"));
        @SuppressWarnings("unchecked")
        List<String> tests = (List<String>) metadata.get("tests");
        assertTrue(tests.contains(Samples.class.getName() + "#partly"));
        assertTrue(tests.contains(OtherSamples.class.getName() + "#other"));
    }

    @Test
    void inventorySidecarRecordsSnapshotWhenPropertyIsSet() throws Exception {
        String snap = "1234567890abcdef1234567890abcdef12345678";
        System.setProperty(DriftListener.SNAPSHOT, snap);
        System.setProperty(DriftListener.PROOF_KEY, "true");
        try {
            run();
        } finally {
            System.clearProperty(DriftListener.PROOF_KEY);
        }
        Map<String, Object> metadata = inventory(dir.resolve("events.meta.json"));
        assertEquals(snap, metadata.get("snapshot"));
        @SuppressWarnings("unchecked")
        Map<String, Object> env = (Map<String, Object>) metadata.get("env");
        assertEquals("drift-junit@0.5.1", env.get("adapter"));
        assertEquals("junit-platform", env.get("runner"));
    }

    @Test
    void anExecutionRefMakesTheSidecarVersionTwo() throws Exception {
        String ref = "sha256:" + "a".repeat(64);
        System.setProperty(DriftListener.EXECUTION_REF, ref);
        run();
        run();
        Map<String, Object> m = inventory(dir.resolve("events.meta.json"));
        assertEquals(List.of(2L, ref, List.of()),
                List.of(m.get("version"), m.get("execution_ref"), m.get("touched")));
    }

    @Test
    void runsAppendToTheEventsFile() throws Exception {
        run();
        int first = Files.readAllLines(dir.resolve("events.jsonl")).size();
        run();
        assertEquals(2 * first, Files.readAllLines(dir.resolve("events.jsonl")).size());
    }

    @Test
    void anEventsDirectoryGetsOneSortedFilePerTestPlan() throws Exception {
        Path eventsDir = dir.resolve("events");
        System.setProperty(DriftListener.EVENTS, eventsDir.toString());
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(Samples.class)).build());
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(Samples.class)).build());
        try (Stream<Path> s = Files.list(eventsDir)) {
            List<Path> files = s.filter(p -> p.toString().endsWith(".jsonl")).sorted().toList();
            assertEquals(2, files.size());
            assertTrue(files.get(0).getFileName().toString().compareTo(files.get(1).getFileName().toString()) < 0);
            assertEquals(Files.readAllLines(files.get(0)).size(), Files.readAllLines(files.get(1)).size());
            for (Path file : files) {
                Path sidecar = file.resolveSibling(file.getFileName().toString()
                        .replaceFirst("\\.jsonl$", ".meta.json"));
                assertTrue(Files.isRegularFile(sidecar));
                assertEquals(List.of(Samples.class.getName()), inventory(sidecar).get("classes"));
            }
        }
    }

    @Test
    void multiContractSelectionAndUnknownContractDetection() throws Exception {
        Path sel = dir.resolve("select.json");
        Files.writeString(sel, "{\"all\":false,\"reasons\":[],\"contracts\":[{\"all\":false,\"contract\":\"legacy\","
                + "\"cases\":[],\"tests\":[\"" + Samples.class.getName() + "#legacyView\"]}],\"tests\":[]}");
        System.setProperty(DriftSelect.SELECT, sel.toString());
        assertEquals(List.of("legacyView@unit"), new ArrayList<>(run().keySet()));
        System.clearProperty(DriftSelect.SELECT);
        Path uev = dir.resolve("unknown.jsonl");
        System.setProperty(DriftListener.EVENTS, uev.toString());
        LauncherFactory.create().execute(
                LauncherDiscoveryRequestBuilder.request().selectors(selectClass(UnknownContract.class)).build());
        @SuppressWarnings("unchecked")
        Map<String, Object> e = (Map<String, Object>) Json.parse(Files.readAllLines(uev).get(0));
        assertEquals("failed", e.get("outcome"));
    }

    @Test
    void relationalPostconditionsInCheckProjectionAndViewKillMutants() {
        Drift.Case relCase = new Drift.Case(
                "bridge",
                "part",
                Map.of("op", "progress"),
                Map.of(
                        "pct", Map.of("min", 0L, "max", 100L, "le_field", "maxPct"),
                        "items", Map.of("non_empty", Boolean.TRUE, "min_len", 1L),
                        "tier", Map.of("in", List.of("a", "b"))));
        Map<String, Object> validPayload = Map.of(
                "pct", 80L,
                "maxPct", 100L,
                "items", List.of("x"),
                "tier", "a");
        relCase.checkProjection(validPayload);
        assertThrows(AssertionError.class, () -> relCase.checkProjection(
                Map.of("pct", 101L, "maxPct", 100L, "items", List.of("x"), "tier", "a")));
        assertThrows(AssertionError.class, () -> relCase.checkProjection(
                Map.of("pct", 85L, "maxPct", 80L, "items", List.of("x"), "tier", "a")));
        for (double bad : new double[] {Double.NaN, Double.POSITIVE_INFINITY, Double.NEGATIVE_INFINITY}) {
            assertTrue(!Json.valuesEqual(200L, bad));
            assertTrue(!Json.valuesEqual(bad, bad));
            assertThrows(AssertionError.class, () -> relCase.checkProjection(
                    Map.of("pct", bad, "maxPct", 80L, "items", List.of("x"), "tier", "a")));
            assertThrows(AssertionError.class, () -> relCase.checkProjection(
                    Map.of("pct", 50L, "maxPct", bad, "items", List.of("x"), "tier", "a")));
        }
        Drift.withMutation(
                "bridge", "part", "/cases/part/then/pct/max", 101L,
                () -> relCase.checkProjection(validPayload));
        assertThrows(AssertionError.class, () -> Drift.withMutation(
                "bridge", "part", "/cases/part/then/pct/max", 79L,
                () -> relCase.checkProjection(validPayload)));
        assertEquals(8, Drift.cartesianDomain(Map.of(
                "b1", Drift.boolDomain(),
                "b2", Drift.boolDomain(),
                "b3", Drift.boolDomain())).size());
        Drift.Case extCase = new Drift.Case(
                "bridge",
                "ext",
                Map.of("op", "invoice"),
                Map.of(
                        "total", Map.of("sum_fields", List.of("sub", "tax")),
                        "roles", Map.of("contains", List.of("admin")),
                        "code", Map.of("prefix", "INV-", "suffix", "-IT")));
        extCase.checkProjection(Map.of(
                "sub", 100L,
                "tax", 22L,
                "total", 122L,
                "roles", List.of("user", "admin"),
                "code", "INV-2026-IT"));
        Map<String, Object> d143Map = new java.util.LinkedHashMap<>();
        d143Map.put("a_grand", Map.of("sum_fields", List.of("m_sub", "z_tax")));
        d143Map.put("m_sub", Map.of("sum_fields", List.of("x_price", "y_ship")));
        d143Map.put("x_price", Map.of("min", 10L, "max", 20L));
        d143Map.put("y_ship", 5L);
        d143Map.put("z_tax", Map.of("eq_field", "y_ship"));
        Map<String, Object> d143Syn = DriftStubs.synthesizeMap(
                d143Map,
                DriftStubs.buildPeerIndex(Map.of(), d143Map, Map.of(), Map.of()),
                Map.of(),
                Map.of(),
                Map.of(),
                true);
        assertEquals(Map.of("a_grand", 20L, "m_sub", 15L, "x_price", 10L, "y_ship", 5L, "z_tax", 5L), d143Syn);
        Map<String, Object> d150Raw = Map.of(
                "a", Map.of("min", 0L, "max", 10L, "le_field", "b"),
                "b", Map.of("min", 0L, "max", 10L),
                "total", Map.of("min", 10L, "max", 10L, "sum_fields", List.of("a", "b")));
        Map<String, Object> d150Tight = Json.tightenThenMapBySumResiduals(Map.of(), d150Raw, Map.of(), Map.of());
        @SuppressWarnings("unchecked")
        Map<String, Object> d150A = (Map<String, Object>) d150Tight.get("a");
        @SuppressWarnings("unchecked")
        Map<String, Object> d150B = (Map<String, Object>) d150Tight.get("b");
        assertEquals(0L, d150A.get("min"));
        assertEquals(5L, d150A.get("max"));
        assertEquals(5L, d150B.get("min"));
        assertEquals(10L, d150B.get("max"));
        assertThrows(AssertionError.class, () -> extCase.checkProjection(
                Map.of("sub", 100L, "tax", 22L, "total", 120L, "roles", List.of("admin"), "code", "INV-1-IT")));
        assertThrows(AssertionError.class, () -> extCase.checkProjection(
                Map.of("sub", 100L, "tax", 22L, "total", Double.NaN, "roles", List.of("admin"), "code", "INV-1-IT")));
        assertThrows(AssertionError.class, () -> extCase.checkProjection(
                Map.of("sub", Double.NaN, "tax", 22L, "total", 122L, "roles", List.of("admin"), "code", "INV-1-IT")));
        assertThrows(AssertionError.class, () -> extCase.checkProjection(
                Map.of("sub", 100L, "tax", 22L, "total", 122L, "roles", List.of("user"), "code", "INV-1-IT")));
        assertThrows(AssertionError.class, () -> extCase.checkProjection(
                Map.of("sub", 100L, "tax", 22L, "total", 122L, "roles", List.of("admin"), "code", "ORD-1-IT")));
        Drift.Case uiCase = new Drift.Case(
                "bridge",
                "ui",
                Map.of(),
                Map.of("min_target_px", 24L));
        Drift.withMutation("bridge", "ui", "/cases/ui/then/min_target_px", 25L, () -> {
            uiCase.checkView(Map.of("min_target_px", 44L));
            assertThrows(AssertionError.class, () -> uiCase.checkView(Map.of("min_target_px", 24L)));
            AssertionError bErr = assertThrows(AssertionError.class, () ->
                    uiCase.checkBounds(Drift.intDomain(1, 100), Map.of(
                            "min_target_px", (v, sample) -> assertTrue(sample < 100 || v.equals(24L)))));
            assertTrue(bErr.getMessage().contains("[counterexample: 100]"));
        });
    }

    public static final class ScalaTuple {
        private final Object k;
        private final Object v;

        public ScalaTuple(Object k, Object v) {
            this.k = k;
            this.v = v;
        }

        public Object _1() {
            return k;
        }

        public Object _2() {
            return v;
        }
    }

    public static final class ScalaProductRow {
        private final long status;
        private final String name;

        public ScalaProductRow(long status, String name) { this.status = status; this.name = name; }
        public int productArity() { return 2; }
        public String productElementName(int n) { return n == 0 ? "status" : "name"; }
        public Object productElement(int n) { return n == 0 ? status : name; }
    }

    static class UnannotatedClosureSample {
        @Test
        void munitStyleTest() {
            Drift.Case c = Drift.expect("bridge", "part", "http");
            c.verify(new ScalaTuple("status", 200L), new ScalaTuple("name", "ok"));
        }
    }

    @Test
    void closureSuitesAutoBindExpectAndVerifyScalaTuplesAndProducts() throws Exception {
        Path closureEv = dir.resolve("closure-events.jsonl");
        System.setProperty(DriftListener.EVENTS, closureEv.toString());
        LauncherFactory.create().execute(LauncherDiscoveryRequestBuilder.request()
                .selectors(selectClass(UnannotatedClosureSample.class)).build());
        @SuppressWarnings("unchecked")
        Map<String, Object> ev = (Map<String, Object>) Json.parse(Files.readAllLines(closureEv).get(0));
        assertEquals("passed", ev.get("outcome"));
        assertEquals("http", ev.get("level"));
        assertEquals(List.of("part"), ev.get("read"));
        Map<String, Object> meta = inventory(dir.resolve("closure-events.meta.json"));
        assertEquals(List.of(UnannotatedClosureSample.class.getName()), meta.get("classes"));
        assertEquals(List.of(UnannotatedClosureSample.class.getName() + "#munitStyleTest"), meta.get("tests"));

        Drift.end();
        Path standaloneEv = dir.resolve("standalone.jsonl");
        System.setProperty(DriftListener.EVENTS, standaloneEv.toString());
        Drift.Case c = Drift.expect("bridge", "part", "http");
        c.verify(new ScalaProductRow(200L, "ok"));
        assertThrows(AssertionError.class, () -> c.verify(new ScalaTuple("status", 500L), new ScalaTuple("name", "ok")));
        Drift.flushEvents();
        List<String> lines = Files.readAllLines(standaloneEv);
        assertEquals(2, lines.size());
        @SuppressWarnings("unchecked")
        Map<String, Object> passEv = (Map<String, Object>) Json.parse(lines.get(0));
        @SuppressWarnings("unchecked")
        Map<String, Object> failEv = (Map<String, Object>) Json.parse(lines.get(1));
        assertEquals("passed", passEv.get("outcome"));
        assertEquals(List.of("part"), passEv.get("read"));
        assertEquals("failed", failEv.get("outcome"));
    }
}

