package drift.maven;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.apache.maven.plugin.MojoExecutionException;

/**
 * Captures a Git tree snapshot of the working tree using a temporary copy of the index
 * so the user's index is never modified, and computes path deltas across snapshots.
 */
final class GitSnapshot {
    private static final Pattern SNAPSHOTS_BLOCK =
            Pattern.compile("\"snapshots\"\\s*:\\s*\\[(.*?)]", Pattern.DOTALL);
    private static final Pattern HEX_OID =
            Pattern.compile("\"([0-9a-f]{40}|[0-9a-f]{64})\"");
    private static final Pattern COMPLETE_TRUE =
            Pattern.compile("\"snapshots_complete\"\\s*:\\s*true\\b");

    record Snapshot(Path topLevel, String treeOid) {}

    record SnapshotInfo(boolean complete, List<String> snapshots) {}

    private GitSnapshot() {}

    static Snapshot capture(Path basedir, List<Path> excludedDirs) throws MojoExecutionException {
        Path normBase = basedir.toAbsolutePath().normalize();
        RunResult revRun = git(normBase, Map.of(), List.of("rev-parse", "--show-toplevel", "--git-dir"));
        if (revRun.status != 0 || revRun.stdout.isBlank()) {
            return null;
        }
        String[] revLines = revRun.stdout.trim().split("\\R");
        if (revLines.length < 2 || revLines[0].isBlank() || revLines[1].isBlank()) {
            return null;
        }
        Path topLevel = Path.of(revLines[0].trim()).toAbsolutePath().normalize();
        if (!normBase.equals(topLevel)) {
            RunResult ignoreRun = git(normBase, Map.of(),
                    List.of("check-ignore", "-q", normBase.toString()));
            if (ignoreRun.status == 0) {
                return null;
            }
        }
        Path rawGitDir = Path.of(revLines[1].trim());
        Path gitDir = (rawGitDir.isAbsolute() ? rawGitDir : normBase.resolve(rawGitDir)).normalize();
        Path realIndex = gitDir.resolve("index");
        Path tempIndex;
        try {
            tempIndex = Files.createTempFile("drift-git-index-", ".idx");
        } catch (IOException e) {
            throw new MojoExecutionException("cannot create temporary git index", e);
        }
        try {
            if (Files.isRegularFile(realIndex)) {
                Files.copy(realIndex, tempIndex, StandardCopyOption.REPLACE_EXISTING);
            } else {
                Files.deleteIfExists(tempIndex);
            }
            Set<String> excludes = new LinkedHashSet<>();
            for (Path excluded : excludedDirs) {
                if (excluded == null) {
                    continue;
                }
                Path normEx = excluded.toAbsolutePath().normalize();
                if (normEx.startsWith(topLevel) && !normEx.equals(topLevel)) {
                    String rel = topLevel.relativize(normEx).toString().replace('\\', '/');
                    if (!rel.isBlank()) {
                        excludes.add(":(exclude)" + rel);
                    }
                }
            }
            List<String> addArgs = new ArrayList<>(
                    List.of("-c", "core.safecrlf=false", "add", "-A", "--", "."));
            addArgs.addAll(excludes);
            Map<String, String> env = Map.of("GIT_INDEX_FILE", tempIndex.toAbsolutePath().toString());
            RunResult addRun = git(topLevel, env, addArgs);
            if (addRun.status != 0) {
                return null;
            }
            RunResult treeRun = git(topLevel, env, List.of("write-tree"));
            if (treeRun.status != 0) {
                return null;
            }
            String oid = treeRun.stdout.trim();
            if (!oid.matches("[0-9a-f]{40}|[0-9a-f]{64}")) {
                return null;
            }
            return new Snapshot(topLevel, oid);
        } catch (IOException e) {
            throw new MojoExecutionException("cannot capture git worktree snapshot", e);
        } finally {
            try {
                Files.deleteIfExists(tempIndex);
            } catch (IOException ignored) {
            }
        }
    }

    /**
     * Returns the sorted unique absolute paths changed between each snapshot in {@code fromTrees}
     * and {@code toTree}, or {@code null} when a tree object is missing or cannot be diffed.
     */
    static List<String> diffTrees(Path topLevel, List<String> fromTrees, String toTree)
            throws MojoExecutionException {
        Set<String> changed = new TreeSet<>();
        for (String fromTree : fromTrees) {
            if (fromTree.equals(toTree)) {
                continue;
            }
            RunResult diff = git(topLevel, Map.of(),
                    List.of("-c", "core.quotepath=false", "diff", "--no-renames", "--name-only",
                            fromTree, toTree));
            if (diff.status != 0) {
                return null;
            }
            for (String line : diff.stdout.split("\\R")) {
                String rel = line.trim();
                if (!rel.isEmpty()) {
                    changed.add(topLevel.resolve(rel).normalize().toAbsolutePath().toString());
                }
            }
        }
        return new ArrayList<>(changed);
    }

    static SnapshotInfo parseProveSnapshots(List<String> lines) {
        String text = String.join("\n", lines);
        if (!COMPLETE_TRUE.matcher(text).find()) {
            return new SnapshotInfo(false, List.of());
        }
        Matcher block = SNAPSHOTS_BLOCK.matcher(text);
        if (!block.find()) {
            return new SnapshotInfo(false, List.of());
        }
        List<String> out = new ArrayList<>();
        Matcher hex = HEX_OID.matcher(block.group(1));
        while (hex.find()) {
            out.add(hex.group(1));
        }
        return out.isEmpty() ? new SnapshotInfo(false, List.of()) : new SnapshotInfo(true, out);
    }

    /**
     * Fast path for the common single-snapshot case: when there is exactly one non-empty event
     * shard in {@code eventsDir} and its sidecar carries a valid {@code snapshot} OID, returns it
     * without spawning {@code drift prove --json}. Returns {@code null} whenever multiple shards,
     * missing sidecars or missing snapshots require full kernel freshness resolution.
     */
    static SnapshotInfo trySingleSnapshot(Path eventsDir) {
        if (!Files.isDirectory(eventsDir)) {
            return null;
        }
        try (var stream = Files.list(eventsDir)) {
            List<Path> jsonls = new ArrayList<>();
            List<Path> metas = new ArrayList<>();
            for (Path p : stream.toList()) {
                String name = p.getFileName().toString();
                if (name.endsWith(".jsonl")) {
                    jsonls.add(p);
                } else if (name.endsWith(".meta.json")) {
                    metas.add(p);
                }
            }
            if (jsonls.size() != 1 || metas.size() != 1) {
                return null;
            }
            Path jsonl = jsonls.get(0);
            Path meta = metas.get(0);
            String baseName = jsonl.getFileName().toString();
            String expectedMeta = baseName.substring(0, baseName.length() - ".jsonl".length()) + ".meta.json";
            if (!meta.getFileName().toString().equals(expectedMeta) || Files.size(jsonl) == 0) {
                return null;
            }
            String metaText = Files.readString(meta, StandardCharsets.UTF_8);
            Matcher snapMatcher = Pattern.compile("\"snapshot\"\\s*:\\s*\"([0-9a-f]{40}|[0-9a-f]{64})\"")
                    .matcher(metaText);
            if (!snapMatcher.find()) {
                return null;
            }
            return new SnapshotInfo(true, List.of(snapMatcher.group(1)));
        } catch (IOException e) {
            return null;
        }
    }

    private record RunResult(int status, String stdout) {}

    private static RunResult git(Path workDir, Map<String, String> extraEnv, List<String> args)
            throws MojoExecutionException {
        List<String> cmd = new ArrayList<>();
        cmd.add("git");
        cmd.add("-C");
        cmd.add(workDir.toString());
        cmd.addAll(args);
        try {
            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.environment().put("GIT_OPTIONAL_LOCKS", "0");
            pb.environment().put("GIT_NO_REPLACE_OBJECTS", "1");
            pb.environment().putAll(extraEnv);
            Process p = pb.start();
            ByteArrayOutputStream stdout = new ByteArrayOutputStream();
            ByteArrayOutputStream stderr = new ByteArrayOutputStream();
            Thread errReader = new Thread(() -> {
                try (InputStream err = p.getErrorStream()) {
                    err.transferTo(stderr);
                } catch (IOException ignored) {
                }
            });
            errReader.setDaemon(true);
            errReader.start();
            try (InputStream in = p.getInputStream()) {
                in.transferTo(stdout);
            }
            errReader.join(5_000);
            if (!p.waitFor(2, TimeUnit.MINUTES)) {
                p.destroyForcibly();
                return new RunResult(1, "");
            }
            return new RunResult(p.exitValue(), stdout.toString(StandardCharsets.UTF_8));
        } catch (IOException e) {
            return new RunResult(1, "");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new MojoExecutionException("interrupted while running git", e);
        }
    }
}
