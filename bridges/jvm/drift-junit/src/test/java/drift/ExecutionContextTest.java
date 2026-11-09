package drift;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

/** Execution context fields of the inventory sidecar and their read-back validation. */
class ExecutionContextTest {
    private static final String REF = "sha256:" + "b".repeat(64);
    private static final Path SIDECAR = Path.of("events.meta.json");

    @AfterEach
    void clear() {
        System.clearProperty(DriftListener.EXECUTION_REF);
        System.clearProperty(DriftListener.PACK_REF);
        System.clearProperty(DriftListener.TOUCHED);
    }

    @Test
    void touchedPathsAreSortedUniqueAndReadBack() {
        System.setProperty(DriftListener.PACK_REF, "dr1:abababababab");
        System.setProperty(DriftListener.TOUCHED, " src/B.java,src/A.java\nsrc/B.java ");
        StringBuilder json = new StringBuilder("{\"version\":2,\"execution_ref\":\"" + REF + "\"");
        ExecutionContext.appendTail(json, REF);
        @SuppressWarnings("unchecked") // appendTail writes one JSON object body
        Map<String, Object> head = (Map<String, Object>) Json.parse(json.append('}').toString());
        assertEquals(List.of("src/A.java", "src/B.java"), head.get("touched"));
        assertEquals("dr1:abababababab", head.get("pack_ref"));
        ExecutionContext.checkHead(SIDECAR, head);
    }

    @Test
    void malformedContextIsRejected() {
        System.setProperty(DriftListener.EXECUTION_REF, "sha256:short");
        assertThrows(IllegalStateException.class, ExecutionContext::executionRef);
        System.setProperty(DriftListener.TOUCHED, "../escape.java");
        assertThrows(IllegalStateException.class, () -> ExecutionContext.appendTail(new StringBuilder(), null));
        for (Map<String, Object> head : List.of(Map.<String, Object>of("version", 2L),
                Map.<String, Object>of("version", 1L, "execution_ref", REF),
                Map.<String, Object>of("version", 2L, "execution_ref", REF, "touched", List.of("b", "a")),
                Map.<String, Object>of("version", 1L, "pack_ref", "dr1:x"))) {
            assertThrows(IllegalStateException.class, () -> ExecutionContext.checkHead(SIDECAR, head));
        }
        Drift.Case typed = new Drift.Case("bridge", "typed",
                Map.of("safe", Boolean.TRUE, "limit", 10L),
                Map.of("ok", Boolean.TRUE, "count", 42L, "items", List.of("a"), "meta", Map.of("k", "v")));
        assertEquals(Boolean.TRUE, typed.whenBoolean("safe"));
        assertEquals(Boolean.TRUE, typed.thenBoolean("ok"));
        assertEquals(10, typed.whenInt("limit"));
        assertEquals(42L, typed.thenLong("count"));
        assertEquals(List.of("a"), typed.thenList("items"));
        assertEquals(Map.of("k", "v"), typed.thenMap("meta"));
        assertEquals("java-25-lts", DriftVerify.bridgeCapabilities().get("runtime_baseline"));
    }

    @Test
    void recursiveForbidKeysAndObservableProbesAreEnforced() {
        assertEquals(
                Boolean.TRUE,
                DriftProbes.hasKeyRecursive(
                        Map.of("status", 200L, "details", Map.of("token", "secret")), "token", true));
        assertEquals(
                Boolean.FALSE,
                DriftProbes.hasKeyRecursive(
                        Map.of("status", 200L, "message", "token=ok"), "token", true));
        Drift.Case c = new Drift.Case(
                "bridge",
                "probe",
                Map.of("op", "charge"),
                Map.of("status", 200L));
        assertEquals(
                Boolean.TRUE,
                c.checkSeamProbe(Map.of("retryable", Boolean.TRUE, "attempts", 2L, "maxAttempts", 3L, "queries", 2L, "maxQueries", 2L)));
        assertThrows(
                AssertionError.class,
                () -> c.checkSeamProbe(Map.of("retryable", Boolean.FALSE, "attempts", 2L)));
        assertEquals(
                Boolean.FALSE,
                c.checkSeamProbe(Map.of("retryable", Boolean.TRUE, "attempts", 0L, "strict", Boolean.FALSE)));
        assertEquals(
                Boolean.TRUE,
                c.checkRollback(Map.of("resource", "ORDERS_DB", "before", Map.of("n", 1L), "after", Map.of("n", 1L))));
        assertThrows(
                AssertionError.class,
                () -> c.checkRollback(Map.of("resource", "ORDERS_DB", "before", Map.of("n", 1L), "after", Map.of("n", 2L))));
        assertThrows(
                AssertionError.class,
                () -> DriftProbes.checkBolaVariantPair("bridge.probe", Map.of("actor_owner", "t1", "resource_owner", "t1")));
        assertEquals(
                Boolean.TRUE,
                DriftProbes.checkBolaVariantPair("bridge.probe", Map.of("actor_owner", "t1", "resource_owner", "t2")));
    }
}
