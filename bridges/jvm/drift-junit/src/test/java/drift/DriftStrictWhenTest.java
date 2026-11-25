package drift;

import static org.junit.jupiter.api.Assertions.*;
import static org.junit.jupiter.api.DynamicTest.dynamicTest;
import static org.junit.platform.engine.discovery.DiscoverySelectors.selectMethod;

import java.nio.file.*;
import java.util.*;
import java.util.stream.Stream;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.platform.engine.TestExecutionResult;
import org.junit.platform.engine.UniqueId;
import org.junit.platform.engine.support.descriptor.AbstractTestDescriptor;
import org.junit.platform.engine.support.descriptor.MethodSource;
import org.junit.platform.launcher.*;
import org.junit.platform.launcher.core.*;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;

class DriftStrictWhenTest {
    private static final String RESOLVED_VIEW = """
            {
              "drift": "0.3",
              "id": "sw",
              "digest": "dr2b:sha256:1111111111111111111111111111111111111111111111111111111111111111",
              "ref": "dr2b:111111111111",
              "cases": {
                "c1": {
                  "at": ["unit"],
                  "when": {"a": false, "b": 0, "c": null},
                  "then": {"out": {"peer": {"eq": "when.b"}}}
                },
                "c2": {
                  "at": ["unit"],
                  "when": {"x": "hi"},
                  "then": {"out": "hi"}
                }
              }
            }
            """;

    static class FixtureSuite {
        @Test
        @DriftCase(contract = "sw", cases = {"c1"}, level = "unit", strictWhen = true)
        void strictUnreadFails() {
            Drift.Case c = Drift.expect("sw", "c1");
            // Internal peer evaluation reads when.b via whenRaw() — must NOT mark it read.
            c.checkProjection(Map.of("out", 0L));
        }

        @Test
        @DriftCase(contract = "sw", cases = {"c1"}, level = "unit", strictWhen = true)
        void strictAllReadPasses() {
            Drift.Case c = Drift.expect("sw", "c1");
            assertEquals(List.of("a", "b", "c"), c.unreadWhen());
            assertEquals(Optional.empty(), c.findWhen("missing"));
            assertEquals(Boolean.FALSE, c.when("a"));
            assertEquals(Optional.of(0L), c.findWhen("b"));
            assertEquals(Optional.empty(), c.findWhen("c")); // key exists with null value -> marked read
            assertEquals(List.of(), c.unreadWhen());
            c.checkProjection(Map.of("out", 0L));
        }

        @Test
        @DriftCase(contract = "sw", cases = {"c1"}, level = "unit")
        void defaultUnreadPassesUnlessPropertySet() {
            Drift.Case c = Drift.expect("sw", "c1");
            c.checkProjection(Map.of("out", 0L));
        }

        @Test
        @DriftCase(contract = "sw", cases = {"c1"}, level = "unit", strictWhen = true)
        void originalErrorNotMasked() {
            Drift.expect("sw", "c1");
            throw new IllegalStateException("original-boom");
        }

        @Test
        @DriftCase(contract = "sw", cases = {"c1"}, level = "unit", strictWhen = true)
        void assumptionAbortNotMasked() {
            Drift.expect("sw", "c1");
            Assumptions.assumeTrue(false, "skip-me");
        }

        @ParameterizedTest
        @ValueSource(strings = {"c1", "c2"})
        @DriftCase(contract = "sw", cases = {"c1", "c2"}, level = "unit", strictWhen = true)
        void parameterizedChecksOnlyOpenedCase(String cid) {
            Drift.Case c = Drift.expect("sw", cid);
            if ("c1".equals(cid)) {
                c.whenTable();
                c.checkProjection(Map.of("out", 0L));
            } else {
                String x = c.whenString("x");
                c.checkProjection(Map.of("out", x));
            }
        }

        @ParameterizedTest
        @ValueSource(strings = {"c1", "c2"})
        @DriftCase(contract = "sw", level = "unit", strictWhen = true)
        void dynamicEmptyCasesStrictWhenUnreadFails(String cid) {
            Drift.Case c = Drift.expect("sw", cid);
            if ("c1".equals(cid)) {
                c.checkProjection(Map.of("out", 0L)); // unread when.* must fail
            } else {
                String x = c.whenString("x");
                c.checkProjection(Map.of("out", x));
            }
        }

        @Test
        @DriftCase(contract = "sw", level = "unit", strictWhen = true)
        void dynamicTestEmptyCasesUnreadFails() {
            Drift.Case c = Drift.expect("sw", "c2");
            c.checkProjection(Map.of("out", "hi"));
        }

        @Test
        @DriftCase(contract = "sw", level = "unit", strictWhen = true)
        void dynamicRejectsContractAndLevelRebind() {
            Drift.Case c = Drift.expect("sw", "c2");
            assertEquals("hi", c.whenString("x"));
            assertThrows(IllegalStateException.class, () -> Drift.expect("sw2", "c1"));
            assertThrows(IllegalStateException.class, () -> Drift.expect("sw", "c1", "http"));
            c.checkProjection(Map.of("out", "hi"));
        }

        @Test
        void plainTestWithoutAnnotationUnread() {
            Drift.Case c = Drift.expect("sw", "c2", "unit");
            c.checkProjection(Map.of("out", "hi"));
        }

        @TestFactory
        @DriftCase(contract = "sw", level = "unit", strictWhen = true)
        Stream<DynamicTest> dynamicFactoryStrictWhen() {
            return Stream.of(
                    dynamicTest("reads-when", () -> {
                        Drift.Case c = Drift.expect("sw", "c2");
                        String x = c.whenString("x");
                        c.checkProjection(Map.of("out", x));
                    }),
                    dynamicTest("skips-when", () -> {
                        Drift.Case c = Drift.expect("sw", "c2");
                        c.checkProjection(Map.of("out", "hi"));
                    }),
                    dynamicTest("aborts", () -> {
                        Drift.expect("sw", "c2");
                        Assumptions.assumeTrue(false, "dyn-skip");
                    }));
        }
    }

    private static SummaryGeneratingListener runMethod(String method, Path resolved, Path events, String strictProp) {
        return runMethod(method, "", resolved, events, strictProp, false);
    }

    private static SummaryGeneratingListener runMethod(String method, String paramTypes, Path resolved, Path events, String strictProp) {
        return runMethod(method, paramTypes, resolved, events, strictProp, false);
    }

    private static SummaryGeneratingListener runMethod(
            String method, String paramTypes, Path resolved, Path events, String strictProp, boolean autodetect) {
        String prevRes = System.getProperty("drift.resolved");
        String prevEv = System.getProperty("drift.events");
        String prevSw = System.getProperty("drift.strictWhen");
        try {
            System.setProperty("drift.resolved", resolved.toString());
            System.setProperty("drift.events", events.toString());
            if (strictProp != null) System.setProperty("drift.strictWhen", strictProp);
            else System.clearProperty("drift.strictWhen");
            Drift.clearViews();
            SummaryGeneratingListener summary = new SummaryGeneratingListener();
            Launcher launcher = LauncherFactory.create();
            LauncherDiscoveryRequestBuilder req = LauncherDiscoveryRequestBuilder.request()
                    .selectors(paramTypes.isEmpty()
                            ? selectMethod(FixtureSuite.class, method)
                            : selectMethod(FixtureSuite.class, method, paramTypes));
            if (autodetect) req.configurationParameter("junit.jupiter.extensions.autodetection.enabled", "true");
            launcher.execute(req.build(), summary);
            return summary;
        } finally {
            if (prevRes == null) System.clearProperty("drift.resolved"); else System.setProperty("drift.resolved", prevRes);
            if (prevEv == null) System.clearProperty("drift.events"); else System.setProperty("drift.events", prevEv);
            if (prevSw == null) System.clearProperty("drift.strictWhen"); else System.setProperty("drift.strictWhen", prevSw);
            Drift.clearViews();
        }
    }

    @Test
    void junit5ExtensionAndStandaloneRunCaseEnforceStrictWhen() throws Exception {
        Path tmp = Files.createTempDirectory("drift-strict-when-");
        Path resolved = Files.createDirectories(tmp.resolve("resolved"));
        Files.writeString(resolved.resolve("sw.json"), RESOLVED_VIEW);

        // 1. strictWhen=true fails both JUnit 5 and .jsonl event once, with sorted keys and no observations.
        Path ev1 = tmp.resolve("ev1.jsonl");
        SummaryGeneratingListener s1 = runMethod("strictUnreadFails", resolved, ev1, null);
        assertEquals(1, s1.getSummary().getTestsFailedCount());
        Throwable t1 = s1.getSummary().getFailures().get(0).getException();
        assertInstanceOf(AssertionError.class, t1);
        assertEquals("sw.c1: unread when.a, when.b, when.c", t1.getMessage());
        List<String> lines1 = Files.readAllLines(ev1);
        assertEquals(1, lines1.size());
        assertTrue(lines1.get(0).contains("\"outcome\":\"failed\""), lines1.get(0));
        assertFalse(lines1.get(0).contains("\"observations\""), lines1.get(0));

        // 2. strictWhen=true passes when all keys (incl. false/0/null) are read.
        Path ev2 = tmp.resolve("ev2.jsonl");
        SummaryGeneratingListener s2 = runMethod("strictAllReadPasses", resolved, ev2, null);
        assertEquals(1, s2.getSummary().getTestsSucceededCount());
        String l2 = Files.readString(ev2);
        assertTrue(l2.contains("\"outcome\":\"passed\"") && l2.contains("\"observations\""), l2);

        // 3. Default passes, -Ddrift.strictWhen=true enforces even when strictWhen=false.
        Path ev3a = tmp.resolve("ev3a.jsonl");
        assertEquals(1, runMethod("defaultUnreadPassesUnlessPropertySet", resolved, ev3a, null).getSummary().getTestsSucceededCount());
        Path ev3b = tmp.resolve("ev3b.jsonl");
        SummaryGeneratingListener s3b = runMethod("defaultUnreadPassesUnlessPropertySet", resolved, ev3b, "true");
        assertEquals(1, s3b.getSummary().getTestsFailedCount());
        assertEquals("sw.c1: unread when.a, when.b, when.c", s3b.getSummary().getFailures().get(0).getException().getMessage());

        // 4. Original exception and assumption abort are never masked.
        Path ev4 = tmp.resolve("ev4.jsonl");
        SummaryGeneratingListener s4 = runMethod("originalErrorNotMasked", resolved, ev4, null);
        assertEquals(1, s4.getSummary().getTestsFailedCount());
        assertInstanceOf(IllegalStateException.class, s4.getSummary().getFailures().get(0).getException());
        assertEquals("original-boom", s4.getSummary().getFailures().get(0).getException().getMessage());

        Path ev5 = tmp.resolve("ev5.jsonl");
        SummaryGeneratingListener s5 = runMethod("assumptionAbortNotMasked", resolved, ev5, null);
        assertEquals(1, s5.getSummary().getTestsAbortedCount());
        assertEquals(0, s5.getSummary().getTestsFailedCount());

        // 5. Parameterized test only checks the case opened by each invocation.
        Path ev6 = tmp.resolve("ev6.jsonl");
        SummaryGeneratingListener s6 = runMethod("parameterizedChecksOnlyOpenedCase", "java.lang.String", resolved, ev6, null);
        assertEquals(2, s6.getSummary().getTestsSucceededCount());
        assertEquals(0, s6.getSummary().getTestsFailedCount());

        // 6. Standalone Drift.runCase (MUnit pattern): single event, observations on pass, strictWhen on -Ddrift.strictWhen=1.
        Path ev7 = tmp.resolve("ev7.jsonl");
        String prevRes = System.getProperty("drift.resolved");
        String prevEv = System.getProperty("drift.events");
        String prevSw = System.getProperty("drift.strictWhen");
        try {
            System.setProperty("drift.resolved", resolved.toString());
            System.setProperty("drift.events", ev7.toString());
            System.setProperty("drift.strictWhen", "1");
            Drift.clearViews();
            Drift.runCase("sw", "c2", c -> {
                String x = c.whenString("x");
                c.verify("out", x);
            });
            AssertionError ae = assertThrows(AssertionError.class, () ->
                    Drift.runCase("sw", "c2", c -> c.verify("out", "hi")));
            assertEquals("sw.c2: unread when.x", ae.getMessage());
            Drift.flushEvents();
            List<String> l7 = Files.readAllLines(ev7);
            assertEquals(2, l7.size(), l7.toString());
            assertTrue(l7.get(0).contains("\"outcome\":\"passed\"") && l7.get(0).contains("\"observations\""), l7.get(0));
            assertTrue(l7.get(1).contains("\"outcome\":\"failed\"") && !l7.get(1).contains("\"observations\""), l7.get(1));
        } finally {
            if (prevRes == null) System.clearProperty("drift.resolved"); else System.setProperty("drift.resolved", prevRes);
            if (prevEv == null) System.clearProperty("drift.events"); else System.setProperty("drift.events", prevEv);
            if (prevSw == null) System.clearProperty("drift.strictWhen"); else System.setProperty("drift.strictWhen", prevSw);
            Drift.clearViews();
        }
    }

    public static void main(String[] args) {
        // Subprocess entry point for F7: -Ddrift.strictWhen=false + DRIFT_STRICT_WHEN=1 must still be strict.
        if (!DriftWhen.isStrict(null)) throw new AssertionError("expected OR strictWhen=true");
    }

    @Test
    void f1F4F6F7F8HardeningDynamicCasesAutodetectEndCleanupOrPrecedenceAndTestFactory() throws Exception {
        Path tmp = Files.createTempDirectory("drift-strict-when-h-");
        Path resolved = Files.createDirectories(tmp.resolve("resolved"));
        Files.writeString(resolved.resolve("sw.json"), RESOLVED_VIEW);
        Files.writeString(resolved.resolve("sw2.json"), RESOLVED_VIEW.replace("\"id\": \"sw\"", "\"id\": \"sw2\""));

        // F1: @ParameterizedTest and @Test with cases={} preserve strictWhen=true and reject silent rebind.
        Path evDynParam = tmp.resolve("dyn-param.jsonl");
        SummaryGeneratingListener sdp = runMethod("dynamicEmptyCasesStrictWhenUnreadFails", "java.lang.String", resolved, evDynParam, null);
        assertEquals(1, sdp.getSummary().getTestsSucceededCount());
        assertEquals(1, sdp.getSummary().getTestsFailedCount());
        assertEquals("sw.c1: unread when.a, when.b, when.c", sdp.getSummary().getFailures().get(0).getException().getMessage());
        List<String> dpLines = Files.readAllLines(evDynParam);
        assertEquals(2, dpLines.size());
        assertTrue(dpLines.get(0).contains("\"outcome\":\"failed\"") && !dpLines.get(0).contains("\"observations\""), dpLines.get(0));
        assertTrue(dpLines.get(1).contains("\"outcome\":\"passed\"") && dpLines.get(1).contains("\"observations\""), dpLines.get(1));

        Path evDynTest = tmp.resolve("dyn-test.jsonl");
        SummaryGeneratingListener sdt = runMethod("dynamicTestEmptyCasesUnreadFails", resolved, evDynTest, null);
        assertEquals(1, sdt.getSummary().getTestsFailedCount());
        assertEquals("sw.c2: unread when.x", sdt.getSummary().getFailures().get(0).getException().getMessage());

        Path evRebind = tmp.resolve("dyn-rebind.jsonl");
        assertEquals(1, runMethod("dynamicRejectsContractAndLevelRebind", resolved, evRebind, null).getSummary().getTestsSucceededCount());

        // F4: plain @Test without @DriftCase fails natively when autodetection discovers META-INF/services Extension.
        Path evPlain = tmp.resolve("plain-auto.jsonl");
        SummaryGeneratingListener spl = runMethod("plainTestWithoutAnnotationUnread", "", resolved, evPlain, "true", true);
        assertEquals(1, spl.getSummary().getTestsFailedCount());
        assertEquals("sw.c2: unread when.x", spl.getSummary().getFailures().get(0).getException().getMessage());
        assertTrue(Files.readString(evPlain).contains("\"outcome\":\"failed\""));

        // F8: @TestFactory DynamicTest children are intercepted individually without masking aborts.
        Path evFac = tmp.resolve("factory.jsonl");
        SummaryGeneratingListener sfac = runMethod("dynamicFactoryStrictWhen", resolved, evFac, null);
        assertEquals(1, sfac.getSummary().getTestsSucceededCount());
        assertEquals(1, sfac.getSummary().getTestsFailedCount());
        assertEquals(1, sfac.getSummary().getTestsAbortedCount());
        assertEquals("sw.c2: unread when.x", sfac.getSummary().getFailures().get(0).getException().getMessage());
        List<String> facLines = Files.readAllLines(evFac);
        assertEquals(3, facLines.size(), facLines.toString());
        assertTrue(facLines.get(0).contains("\"outcome\":\"passed\"") && facLines.get(0).contains("\"observations\""));
        assertTrue(facLines.get(1).contains("\"outcome\":\"failed\"") && !facLines.get(1).contains("\"observations\""));
        assertTrue(facLines.get(2).contains("\"outcome\":\"skipped\""));

        // F6: Drift.end() clears DriftWhen state, and executionFinished cleans up in finally even on write failure.
        String prevRes = System.getProperty("drift.resolved");
        String prevEv = System.getProperty("drift.events");
        String prevSw = System.getProperty("drift.strictWhen");
        try {
            System.setProperty("drift.resolved", resolved.toString());
            System.setProperty("drift.strictWhen", "true");
            Drift.clearViews();
            Drift.begin(null);
            Drift.expect("sw", "c2", "unit");
            assertTrue(DriftWhen.listenerFallbackViolated(null));
            Drift.end();
            assertFalse(DriftWhen.listenerFallbackViolated(null), "Drift.end() must clear DriftWhen state");

            // Force write failure synchronously without polluting static listener buffers
            System.setProperty("drift.events", tmp.resolve("throw-write.jsonl").toString());
            DriftListener listener = new DriftListener();
            var m = FixtureSuite.class.getDeclaredMethod("plainTestWithoutAnnotationUnread");
            var desc = new AbstractTestDescriptor(UniqueId.root("e", "1").append("t", "1"), "t", MethodSource.from(m)) {
                @Override public Type getType() { return Type.TEST; }
            };
            TestIdentifier tid = TestIdentifier.from(desc);
            Drift.begin(new DriftCase() {
                @Override public String contract() { throw new IllegalStateException("boom-write"); }
                @Override public String[] cases() { return new String[] {"c2"}; }
                @Override public String level() { return "unit"; }
                @Override public boolean strictWhen() { return true; }
                @Override public Class<DriftCase> annotationType() { return DriftCase.class; }
            });
            DriftWhen.register("sw", "c2", Map.of("x", "hi"));
            assertThrows(IllegalStateException.class, () -> listener.executionFinished(tid, TestExecutionResult.successful()));
            assertNull(Drift.inTest(), "executionFinished finally must clear IN_TEST on write failure");
            assertFalse(DriftWhen.listenerFallbackViolated(null), "executionFinished finally must clear DriftWhen");
        } finally {
            if (prevRes == null) System.clearProperty("drift.resolved"); else System.setProperty("drift.resolved", prevRes);
            if (prevEv == null) System.clearProperty("drift.events"); else System.setProperty("drift.events", prevEv);
            if (prevSw == null) System.clearProperty("drift.strictWhen"); else System.setProperty("drift.strictWhen", prevSw);
            Drift.clearViews();
        }

        // F7: -Ddrift.strictWhen=false must NOT shadow DRIFT_STRICT_WHEN=1 (OR precedence).
        ProcessBuilder pb = new ProcessBuilder(
                Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                "-Ddrift.strictWhen=false",
                "-cp", System.getProperty("java.class.path"),
                DriftStrictWhenTest.class.getName());
        pb.environment().put("DRIFT_STRICT_WHEN", "1");
        pb.redirectErrorStream(true);
        Process p = pb.start();
        String out = new String(p.getInputStream().readAllBytes());
        assertEquals(0, p.waitFor(), out);
    }
}
