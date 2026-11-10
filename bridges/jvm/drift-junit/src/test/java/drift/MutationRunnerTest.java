package drift;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class MutationRunnerTest {
    private static final String DIGEST = "dr1:sha256:" + "ab".repeat(32);

    static class Samples {
        @Test
        @DriftCase(contract = "mutation-demo", cases = "asserted", level = "unit")
        void asserted() {
            assertEquals(200, Drift.expect("mutation-demo", "asserted").thenInt("status"));
        }

        @Test
        @DriftCase(contract = "mutation-demo", cases = "weak", level = "unit")
        void readsWithoutChecking() {
            Drift.expect("mutation-demo", "weak").thenInt("status");
        }

        @Test
        @DriftCase(contract = "mutation-demo", cases = "branch-checked", level = "unit")
        void branchChecked() {
            Drift.Case c = Drift.expect("mutation-demo", "branch-checked");
            int actualStatus = "GET /items/1".equals(c.whenString("request")) ? 200 : 404;
            assertEquals(c.thenInt("status"), actualStatus);
        }

        @Test
        @DriftCase(contract = "mutation-demo", cases = "peer-swap", level = "unit")
        void peerSwap() {
            Drift.Case c = Drift.expect("mutation-demo", "peer-swap");
            assertEquals(10, c.thenInt("value_a"));
            assertEquals(20, c.thenInt("value_b"));
        }
    }

    @TempDir
    Path directory;

    @AfterEach
    void clearMutationContext() {
        Drift.clearMutation();
    }

    @Test
    void runnerSeparatesKilledAndSurvivedMutants() throws Exception {
        Path resolved = Files.createDirectories(directory.resolve("resolved"));
        Files.writeString(resolved.resolve("mutation-demo.json"),
                "{\"id\":\"mutation-demo\",\"digest\":\"" + DIGEST + "\",\"ref\":\"dr1:abababababab\","
                        + "\"cases\":{\"asserted\":{\"then\":{\"status\":200}},"
                        + "\"branch-checked\":{\"when\":{\"request\":\"GET /items/1\"},\"then\":{\"status\":200}},"
                        + "\"weak\":{\"then\":{\"status\":200}}}}");
        Path events = Files.createDirectories(directory.resolve("events"));
        String binaryName = Samples.class.getName();
        Files.writeString(events.resolve("run.meta.json"),
                "{\"version\":1,\"classes\":[\"" + binaryName + "\"],\"tests\":[\""
                        + binaryName + "#asserted\",\"" + binaryName + "#branchChecked\",\""
                        + binaryName + "#readsWithoutChecking\"]}");
        Path manifest = directory.resolve("mutants.json");
        Files.writeString(manifest, "{\"version\":1,\"contracts\":[{\"id\":\"mutation-demo\","
                + "\"digest\":\"" + DIGEST + "\",\"mutants\":["
                + "{\"id\":\"asserted:/cases/asserted/then/status\",\"case\":\"asserted\","
                + "\"path\":\"/cases/asserted/then/status\","
                + "\"operator\":\"add-one\",\"before\":200,\"after\":201},"
                + "{\"id\":\"branch-checked:/cases/branch-checked/when/request\",\"case\":\"branch-checked\","
                + "\"path\":\"/cases/branch-checked/when/request\","
                + "\"operator\":\"swap-case-when\",\"before\":\"GET /items/1\",\"after\":\"GET /items/999\"},"
                + "{\"id\":\"weak:/cases/weak/then/status\",\"case\":\"weak\","
                + "\"path\":\"/cases/weak/then/status\","
                + "\"operator\":\"add-one\",\"before\":200,\"after\":201}]}]}");
        Path results = directory.resolve("mutation-results");

        Map<String, String> priorProperties = new HashMap<>();
        for (String key : List.of(Drift.RESOLVED, DriftListener.EVENTS, DriftSelect.SELECT)) {
            priorProperties.put(key, System.getProperty(key));
        }
        System.setProperty(Drift.RESOLVED, directory.resolve("ambient-resolved").toString());
        System.setProperty(DriftListener.EVENTS, events.toString());
        System.setProperty(DriftSelect.SELECT, directory.resolve("must-not-read-selection.json").toString());
        try {
            MutationRunner.run(manifest, resolved, events, results,
                    List.of(Samples.class.getProtectionDomain().getCodeSource().getLocation().toURI().getPath()));

            assertEquals(directory.resolve("ambient-resolved").toString(), System.getProperty(Drift.RESOLVED));
            assertEquals(events.toString(), System.getProperty(DriftListener.EVENTS));
            assertEquals(directory.resolve("must-not-read-selection.json").toString(),
                    System.getProperty(DriftSelect.SELECT));
            assertFalse(Files.exists(events.resolve("run.jsonl")));
        } finally {
            priorProperties.forEach((key, prior) -> {
                if (prior == null) {
                    System.clearProperty(key);
                } else {
                    System.setProperty(key, prior);
                }
            });
        }

        List<String> lines = Files.readAllLines(results.resolve("results.jsonl"));
        assertEquals(3, lines.size());
        Map<?, ?> killed = assertInstanceOf(Map.class, Json.parse(lines.get(0)));
        Map<?, ?> whenKilled = assertInstanceOf(Map.class, Json.parse(lines.get(1)));
        Map<?, ?> survived = assertInstanceOf(Map.class, Json.parse(lines.get(2)));
        assertEquals("killed", killed.get("outcome"));
        assertEquals("passed", killed.get("control"));
        assertEquals("killed", whenKilled.get("outcome"));
        assertEquals("passed", whenKilled.get("control"));
        assertEquals("survived", survived.get("outcome"), survived.toString());
        assertEquals("passed", survived.get("control"));
        assertFalse(Files.exists(events.resolve("run.jsonl")));
    }

    @Test
    void mutationBudgetIsExactlyThreeTimesTheSelectedControlRuntime() {
        assertFalse(MutationRunner.budgetExceeded(299, 100));
        assertTrue(MutationRunner.budgetExceeded(300, 100));
        assertTrue(MutationRunner.budgetExceeded(1, 0));
    }

    @Test
    void perCaseMutantBudgetAndBatchBasisScaleWithoutCascadingStarvation() {
        assertFalse(MutationRunner.mutantBudgetExceeded(MutationRunner.MIN_MUTANT_NANOS - 1, 1_000));
        assertTrue(MutationRunner.mutantBudgetExceeded(MutationRunner.MIN_MUTANT_NANOS, 1_000));
        assertFalse(MutationRunner.mutantBudgetExceeded(599_000_000L, 200_000_000L));
        assertTrue(MutationRunner.mutantBudgetExceeded(600_000_000L, 200_000_000L));
        long basis = MutationRunner.batchBudgetBasisNanos(200_000_000L, 2, 10);
        assertEquals(1_000_000_000L, basis);
    }

    @Test
    void runnerAppliesSwapPeerThenDipoleMutation() throws Exception {
        Path resolved = Files.createDirectories(directory.resolve("resolved-swap"));
        Files.writeString(resolved.resolve("mutation-demo.json"),
                "{\"id\":\"mutation-demo\",\"digest\":\"" + DIGEST + "\",\"ref\":\"dr1:abababababab\","
                        + "\"cases\":{\"peer-swap\":{\"then\":{\"value_a\":10,\"value_b\":20}}}}");
        Path events = Files.createDirectories(directory.resolve("events-swap"));
        String binaryName = Samples.class.getName();
        Files.writeString(events.resolve("run.meta.json"),
                "{\"version\":1,\"classes\":[\"" + binaryName + "\"],\"tests\":[\""
                        + binaryName + "#peerSwap\"]}");
        Path manifest = directory.resolve("mutants-swap.json");
        Files.writeString(manifest, "{\"version\":1,\"contracts\":[{\"id\":\"mutation-demo\","
                + "\"digest\":\"" + DIGEST + "\",\"mutants\":["
                + "{\"id\":\"peer-swap:/cases/peer-swap/then/value_a/value_b\",\"case\":\"peer-swap\","
                + "\"path\":\"/cases/peer-swap/then/value_a/value_b\","
                + "\"operator\":\"swap-peer-then\",\"before\":{\"value_a\":10,\"value_b\":20},"
                + "\"after\":{\"value_a\":20,\"value_b\":10}}]}]}");
        Path results = directory.resolve("mutation-results-swap");
        MutationRunner.run(manifest, resolved, events, results,
                List.of(Samples.class.getProtectionDomain().getCodeSource().getLocation().toURI().getPath()));
        List<String> lines = Files.readAllLines(results.resolve("results.jsonl"));
        assertEquals(1, lines.size());
        Map<?, ?> killed = assertInstanceOf(Map.class, Json.parse(lines.get(0)));
        assertEquals("killed", killed.get("outcome"));
        assertEquals("passed", killed.get("control"));
    }

    @Test
    void standaloneSchema03EventsIncludeCapabilities() throws Exception {
        Path resolved = Files.createDirectories(directory.resolve("standalone-resolved"));
        Path events = directory.resolve("standalone.jsonl");
        Files.writeString(resolved.resolve("standalone-parity.json"),
                "{\"drift\":\"0.3\",\"id\":\"standalone-parity\",\"cases\":{}}");
        String oldResolved = System.getProperty(Drift.RESOLVED);
        String oldEvents = System.getProperty(DriftListener.EVENTS);
        try {
            System.setProperty(Drift.RESOLVED, resolved.toString());
            System.setProperty(DriftListener.EVENTS, events.toString());
            DriftListener.recordStandaloneEvent("Parity#standalone", "standalone-parity", List.of("case"),
                    "unit", "passed", List.of("value"));
            DriftListener.flushStandaloneEvents();
            Map<?, ?> event = assertInstanceOf(Map.class, Json.parse(Files.readString(events).strip()));
            assertEquals("0.3", event.get("schema"));
            assertTrue(assertInstanceOf(List.class, event.get("capabilities")).contains("unit-conversion/1"));
        } finally {
            if (oldResolved == null) System.clearProperty(Drift.RESOLVED);
            else System.setProperty(Drift.RESOLVED, oldResolved);
            if (oldEvents == null) System.clearProperty(DriftListener.EVENTS);
            else System.setProperty(DriftListener.EVENTS, oldEvents);
        }
    }

    @Test
    void constraintUnitsKeysAndCollectionParity() {
        Drift.Case c = new Drift.Case("bridge", "parity", Map.of(), Map.of());
        Map<String, Object> context = Map.of("units", Map.of("ms->s", 0.001, "ms->us", 1000),
                "schema", Map.of("then", Map.of("value", Map.of("unit", "s"))));
        Map<String, Object> raw = Map.of("eq", 2000, "min", 1000, "max", 3000,
                "in", List.of(2000, "opaque"), "not_in", List.of(1000), "tol", Map.of("abs", 10), "convert_from", "ms");
        assertTrue(DriftViewChecks.checkRelationalConstraint(c, "value", raw, 2, context, Map.of()));
        org.junit.jupiter.api.Assertions.assertThrows(AssertionError.class,
                () -> DriftViewChecks.checkRelationalConstraint(c, "value", raw, 2000, context, Map.of()));
        assertTrue(DriftViewChecks.checkRelationalConstraint(c, "value",
                Map.of("min", 1000, "convert_from", "ms"), 2, Map.of("units", Map.of("ms->s", 0.001)), Map.of()));
        assertTrue(DriftViewChecks.checkRelationalConstraint(c, "value",
                Map.of("series", Map.of("sum_total", 3000, "step_max_delta", 1000), "convert_from", "ms"), List.of(1, 2), context, Map.of()));
        Map<String, Object> actual = Map.of("a", 1);
        assertTrue(DriftViewChecks.checkRelationalConstraint(c, "value",
                Map.of("keys", Map.of("allow", List.of("a"), "forbid", List.of("secret")),
                        "eq", actual, "len", Map.of("min", 1, "max", 1), "in", List.of(actual)), actual, Map.of(), Map.of()));
        for (Map<String, Object> exp : List.<Map<String, Object>>of(
                Map.of("keys", Map.of("allow", List.of("a")), "eq", Map.of("a", 2)),
                Map.of("allowed_keys", List.of("a"), "min_len", 2),
                Map.of("allowed_keys", List.of("a"), "not_in", List.of(actual)),
                Map.of("allowed_keys", List.of("b")))) {
            org.junit.jupiter.api.Assertions.assertThrows(AssertionError.class,
                    () -> DriftViewChecks.checkRelationalConstraint(c, "value", exp, actual, Map.of(), Map.of()));
        }
        for (Object req : List.of("😀", List.of("😀", "b"))) {
            assertTrue(DriftViewChecks.checkRelationalConstraint(c, "value",
                    Map.of("contains", req, "len", Map.of("min", 3, "max", 3)), "a😀b", Map.of(), Map.of()));
        }
        for (Object req : List.of(2, List.of(1, 2))) {
            assertTrue(DriftViewChecks.checkRelationalConstraint(c, "value",
                    Map.of("contains", req), List.of(1, 2, 3), Map.of(), Map.of()));
        }
    }

    @Test
    void weylStubSynthesisBreaksHomologousPeerSymmetry() {
        Map<String, Object> thenMap = Map.of(
                "out_a", Map.of("min", 10L, "max", 20L),
                "out_b", Map.of("min", 10L, "max", 20L));
        Map<String, Object> stub = DriftStubs.synthesizeMap(thenMap, new java.util.HashMap<>(), Map.of(), Map.of(), Map.of(), true);
        assertEquals(10L, stub.get("out_a"));
        assertEquals(20L, stub.get("out_b"));
        Drift.Case peer03Case = new Drift.Case(
                "bridge",
                "keep",
                Map.of("balance", Map.of("eq", 100L)),
                Map.of("balance", Map.of("peer", Map.of("eq", "when.balance"))));
        assertEquals(100, peer03Case.whenInt("balance"));
        Map<String, Object> relPeerEq = Map.of("peer", Map.of("eq", "when.balance"));
        assertTrue(DriftViewChecks.checkRelationalConstraint(
                peer03Case, "balance", relPeerEq, 100L, Map.of("balance", 100L), Map.of()));
        org.junit.jupiter.api.Assertions.assertThrows(AssertionError.class,
                () -> DriftViewChecks.checkRelationalConstraint(
                        peer03Case, "balance", relPeerEq, 0L, Map.of("balance", 0L), Map.of()));
        Drift.Case uninstPeer03 = new Drift.Case(
                "bridge",
                "range",
                Map.of("balance", Map.of("min", 0L, "max", 100L)),
                Map.of("balance", relPeerEq));
        org.junit.jupiter.api.Assertions.assertThrows(AssertionError.class,
                () -> DriftViewChecks.checkRelationalConstraint(
                        uninstPeer03, "balance", relPeerEq, 0L, Map.of("balance", 0L), Map.of()));
        assertTrue(DriftViewChecks.checkRelationalConstraint(
                uninstPeer03, "balance", relPeerEq, 50L, Map.of("when", Map.of("balance", 50L), "balance", 50L), Map.of()));
        org.junit.jupiter.api.Assertions.assertThrows(AssertionError.class,
                () -> DriftViewChecks.checkRelationalConstraint(
                        uninstPeer03, "balance", relPeerEq, 0L, Map.of("when", Map.of("balance", 50L), "balance", 0L), Map.of()));
    }
}
