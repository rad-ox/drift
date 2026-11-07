package drift;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;

/** Optional execution context of the inventory sidecar: execution_ref (version 2), pack_ref and touched paths. */
final class ExecutionContext {
    private ExecutionContext() {
    }

    /** The validated execution reference, or null when none is configured. */
    static String executionRef() {
        String ref = configured(DriftListener.EXECUTION_REF, "DRIFT_EXECUTION_REF");
        if (ref != null && !ref.matches("sha256:[0-9a-f]{64}")) {
            throw new IllegalStateException("invalid drift.executionRef / DRIFT_EXECUTION_REF");
        }
        return ref;
    }

    /** Appends pack_ref and touched after the snapshot; touched is always written with an execution reference. */
    static void appendTail(StringBuilder json, String executionRef) {
        String packRef = configured(DriftListener.PACK_REF, "DRIFT_PACK_REF");
        if (packRef != null) {
            if (!validPackRef(packRef)) {
                throw new IllegalStateException("invalid drift.packRef / DRIFT_PACK_REF");
            }
            Json.field(json.append(','), "pack_ref", packRef);
        }
        TreeSet<String> touched = new TreeSet<>();
        String raw = configured(DriftListener.TOUCHED, "DRIFT_TOUCHED");
        for (String value : raw == null ? new String[0] : raw.split("[\\n,]+")) {
            String path = value.trim();
            if (path.isEmpty()) {
                continue;
            }
            if (!safePath(path)) {
                throw new IllegalStateException("invalid touched path: " + path);
            }
            touched.add(path);
        }
        if (!touched.isEmpty() || executionRef != null) {
            Json.field(json.append(','), "touched", new ArrayList<>(touched));
        }
    }

    /** Rejects a prior sidecar whose version, execution_ref, pack_ref or touched paths are malformed. */
    static void checkHead(Path sidecar, Map<String, Object> inventory) {
        Object version = inventory.get("version");
        boolean v2 = Long.valueOf(2).equals(version);
        if (!(v2 || Long.valueOf(1).equals(version))
                || (v2 ? !(inventory.get("execution_ref") instanceof String ref && ref.matches("sha256:[0-9a-f]{64}"))
                        : inventory.containsKey("execution_ref"))) {
            throw new IllegalStateException(sidecar + " has an invalid inventory shape");
        }
        if (inventory.containsKey("pack_ref")
                && !(inventory.get("pack_ref") instanceof String packRef && validPackRef(packRef))) {
            throw new IllegalStateException(sidecar + " has an invalid pack_ref");
        }
        if (!inventory.containsKey("touched")) {
            return;
        }
        if (!(inventory.get("touched") instanceof List<?> list) || !list.stream().allMatch(String.class::isInstance)) {
            throw new IllegalStateException(sidecar + " has invalid touched paths");
        }
        List<String> paths = list.stream().map(String.class::cast).toList();
        if (!paths.stream().allMatch(ExecutionContext::safePath)) {
            throw new IllegalStateException(sidecar + " has an invalid touched path");
        }
        if (!paths.equals(paths.stream().distinct().sorted().toList())) {
            throw new IllegalStateException(sidecar + " touched paths are not sorted and unique");
        }
    }

    private static String configured(String property, String envName) {
        String value = System.getProperty(property);
        if (value == null || value.isBlank()) {
            value = System.getenv(envName);
        }
        return value == null || value.isBlank() ? null : value.trim();
    }

    private static boolean validPackRef(String value) {
        return value.matches("dr1:[0-9a-f]{12}");
    }

    private static boolean safePath(String path) {
        return !path.startsWith("/") && !path.contains("\\") && List.of(path.split("/", -1)).stream()
                .noneMatch(s -> s.isEmpty() || s.equals(".") || s.equals(".."));
    }
}
