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
    void weylStubSynthesisBreaksHomologousPeerSymmetry() {
        Map<String, Object> thenMap = Map.of(
                "out_a", Map.of("min", 10L, "max", 20L),
                "out_b", Map.of("min", 10L, "max", 20L));
        Map<String, Object> stub = DriftStubs.synthesizeMap(thenMap, new java.util.HashMap<>(), Map.of(), Map.of(), Map.of(), true);
        assertEquals(10L, stub.get("out_a"));
        assertEquals(20L, stub.get("out_b"));
    }
}
