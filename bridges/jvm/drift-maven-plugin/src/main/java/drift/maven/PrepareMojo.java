package drift.maven;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Properties;
import java.util.stream.Stream;
import org.apache.maven.plugin.MojoExecutionException;
import org.apache.maven.plugin.MojoFailureException;
import org.apache.maven.plugins.annotations.LifecyclePhase;
import org.apache.maven.plugins.annotations.Mojo;
import org.apache.maven.plugins.annotations.Parameter;

/**
 * Checks and exports the contracts of the area before anything compiles, and passes the
 * bridge its properties through argLine, as coverage agents do, so surefire needs no
 * configuration. Events are kept between builds: a test run again supersedes its earlier
 * event, and a clean build starts over.
 */
@Mojo(name = "prepare", defaultPhase = LifecyclePhase.INITIALIZE, threadSafe = true)
public final class PrepareMojo extends DriftMojo {
    /** Comma-separated changed source paths; when set and events exist, runs drift select and sets drift.select. */
    @Parameter(property = "drift.changed")
    String changed;

    /** Starts a full run with no prior event shards or inventory sidecars. */
    @Parameter(property = "drift.fresh", defaultValue = "false")
    boolean fresh;

    /** Incremental options are incompatible with a fresh full run. */
    @Parameter(property = "drift.base")
    String base;

    @Parameter(property = "drift.select")
    String select;

    @Override
    public void execute() throws MojoExecutionException, MojoFailureException {
        if (skipped("prepare")) {
            return;
        }
        requireArea();
        if (fresh && (set(changed) || set(base) || set(select))) {
            throw new MojoExecutionException("drift.fresh cannot be combined with drift.changed, drift.base,"
                    + " or an explicit drift.select");
        }
        project.getProperties().setProperty("drift.feedback", "false");
        project.getProperties().remove("drift.auto.state");
        project.getProperties().remove("drift.auto.list");
        Cli c = cli();
        Path contracts = contracts();
        if (Files.isDirectory(contracts)) {
            Cli.Result r = c.run(List.of("show", contracts.toString(), "--as", "json", "--out",
                    resolved().toString()));
            log(r);
            if (r.status() != 0) {
                throw new MojoFailureException("drift: a contract has findings and cannot be exported; see above");
            }
        } else {
            getLog().warn("drift: " + contracts + " is missing; the gate has no contract to prove");
        }
        if (fresh) {
            removeProofOutput(events());
        }
        Path basedir = project.getBasedir().toPath().toAbsolutePath().normalize();
        GitSnapshot.Snapshot snapshot = GitSnapshot.capture(basedir, List.of(
                output.toPath(),
                Path.of(project.getBuild().getDirectory()),
                basedir.resolve("target")));
        String line = "-Ddrift.resolved=" + quoted(resolved()) + " -Ddrift.events=" + quoted(events());
        if (snapshot != null) {
            line += " -Ddrift.snapshot=" + snapshot.treeOid();
        }
        if (changed != null && !changed.isBlank() && hasEvents() && Files.isDirectory(contracts)) {
            String trimmedChanged = changed.trim();
            if ("auto".equals(trimmedChanged)) {
                GitSnapshot.SnapshotInfo info = GitSnapshot.trySingleSnapshot(events());
                if (info == null) {
                    Cli.Result pr = c.run(List.of("prove", contracts.toString(), "--events",
                            events().toString(), "--json"));
                    info = GitSnapshot.parseProveSnapshots(pr.lines());
                }
                List<String> delta = (snapshot != null && info.complete())
                        ? GitSnapshot.diffTrees(snapshot.topLevel(), info.snapshots(), snapshot.treeOid())
                        : null;
                if (delta == null) {
                    getLog().warn("drift: drift.changed=auto cannot narrow because prior event shards"
                            + " lack a complete snapshot inventory; running all tests");
                    project.getProperties().setProperty("drift.auto.state", "incomplete");
                } else {
                    Path changedList = output.toPath().resolve("changed.list");
                    try {
                        Files.createDirectories(changedList.getParent());
                        Files.writeString(changedList,
                                delta.isEmpty() ? "" : String.join(System.lineSeparator(), delta) + System.lineSeparator());
                    } catch (IOException e) {
                        throw new MojoExecutionException("cannot write " + changedList, e);
                    }
                    project.getProperties().setProperty("drift.auto.state", delta.isEmpty() ? "none" : "list");
                    project.getProperties().setProperty("drift.auto.list",
                            changedList.toAbsolutePath().normalize().toString());
                    List<String> args = new ArrayList<>();
                    args.add("select");
                    if (set(base)) {
                        args.add(base.trim());
                        args.add(contracts.toString());
                    } else if (delta.isEmpty()) {
                        args.add(contracts.toString());
                        args.add(contracts.toString());
                    } else {
                        args.add(contracts.toString());
                    }
                    args.addAll(List.of("--events", events().toString(), "--area",
                            area.toPath().toAbsolutePath().normalize().getParent().toString(),
                            "--changed-root", snapshot.topLevel().toString()));
                    if (!delta.isEmpty()) {
                        args.add("--changed-list");
                        args.add(changedList.toAbsolutePath().normalize().toString());
                    }
                    args.add("--json");
                    Cli.Result sr = c.run(args);
                    if (sr.status() != 0 && sr.status() != 1) {
                        log(sr);
                        throw new MojoExecutionException("drift select failed with status " + sr.status());
                    }
                    Path sel = output.toPath().resolve("select.json");
                    try {
                        Files.writeString(sel, String.join(System.lineSeparator(), sr.lines()) + System.lineSeparator());
                    } catch (IOException e) {
                        throw new MojoExecutionException("cannot write " + sel, e);
                    }
                    line += " -Ddrift.select=" + quoted(sel);
                }
            } else {
                List<String> args = new ArrayList<>(List.of("select", contracts.toString(),
                        "--events", events().toString(), "--area",
                        area.toPath().toAbsolutePath().normalize().getParent().toString(),
                        "--changed-root", basedir.toString(),
                        "--json"));
                for (String p : changed.split(",")) {
                    if (!p.isBlank()) {
                        args.add("--changed");
                        args.add(p.trim());
                    }
                }
                Cli.Result sr = c.run(args);
                if (sr.status() != 0 && sr.status() != 1) {
                    log(sr);
                    throw new MojoExecutionException("drift select failed with status " + sr.status());
                }
                project.getProperties().setProperty("drift.feedback", Boolean.toString(sr.status() == 0));
                Path sel = output.toPath().resolve("select.json");
                try {
                    Files.writeString(sel, String.join(System.lineSeparator(), sr.lines()) + System.lineSeparator());
                } catch (IOException e) {
                    throw new MojoExecutionException("cannot write " + sel, e);
                }
                line += " -Ddrift.select=" + quoted(sel);
            }
        }
        Properties props = project.getProperties();
        String before = props.getProperty("argLine", "");
        if (!before.contains(line)) {
            props.setProperty("argLine", before.isBlank() ? line : before + " " + line);
        }
        getLog().info("drift: tests read " + resolved() + " and write " + events());
    }

    private static boolean set(String value) {
        return value != null && !value.isBlank();
    }

    private void removeProofOutput(Path directory) throws MojoExecutionException {
        if (!Files.isDirectory(directory)) {
            return;
        }
        try (Stream<Path> files = Files.list(directory)) {
            for (Path file : files.toList()) {
                String name = file.getFileName().toString();
                if (Files.isRegularFile(file) && (name.endsWith(".jsonl") || name.endsWith(".meta.json"))) {
                    Files.deleteIfExists(file);
                }
            }
        } catch (IOException e) {
            throw new MojoExecutionException("cannot remove prior proof events from " + directory, e);
        }
        getLog().info("drift: cleared prior event shards and inventories for a fresh full run");
    }

    private static String quoted(Path p) {
        String s = p.toAbsolutePath().toString();
        return s.contains(" ") ? "\"" + s + "\"" : s;
    }
}
