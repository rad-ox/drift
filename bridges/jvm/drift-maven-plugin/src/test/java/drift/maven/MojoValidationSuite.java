package drift.maven;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.stream.Stream;
import org.apache.maven.model.Plugin;
import org.apache.maven.plugin.MojoExecutionException;
import org.apache.maven.plugin.MojoFailureException;
import org.apache.maven.plugin.descriptor.PluginDescriptor;
import org.apache.maven.plugin.logging.Log;
import org.apache.maven.project.MavenProject;
import org.codehaus.plexus.util.xml.Xpp3Dom;
import org.opentest4j.AssertionFailedError;

/**
 * In-process validation suite for {@link PrepareMojo}, {@link GateMojo}, {@link DriftMojo}
 * and {@link Cli} so pure argument/config/version rejections run without spawning Maven JVMs.
 * Named {@code *Suite} rather than {@code *Test} so {@code maven-surefire-plugin} does not
 * require a separate {@code TestEngine} dependency in {@code drift-maven-plugin/pom.xml}.
 */
public final class MojoValidationSuite {
    private MojoValidationSuite() {}

    public static void main(String[] args) throws Exception {
        String pluginVersion = (args.length > 0 && !args[0].isBlank()) ? args[0].trim() : "0.8.1";
        Path work = Files.createTempDirectory("drift-mojo-validation-");
        try {
            testFreshConflictsPreserveProofFiles(work.resolve("fresh-conflict"), pluginVersion);
            testSkipFlagsAndMissingAreaPolicies(work.resolve("skip-policies"), pluginVersion);
            testMissingConfigShowsAdoptionGuide(work.resolve("missing-config"), pluginVersion);
            testGateValidationModesAndMissingInputs(work.resolve("gate-inputs"), pluginVersion);
            testCliLocateVersionAndBuildChecks(work.resolve("cli-checks"), pluginVersion);
            testPrepareShadowedArgLineDiagnostics(work.resolve("shadowed-argline"), pluginVersion);
        } finally {
            deleteRecursively(work);
        }
    }

    private static void testFreshConflictsPreserveProofFiles(Path root, String version) throws Exception {
        Files.createDirectories(root.resolve(".drift"));
        Files.writeString(root.resolve(".drift/config.toml"),
                "drift = \"0.3\"\nkind = \"config\"\n[area]\nowner = \"t\"\n", StandardCharsets.UTF_8);
        Path eventsDir = root.resolve("target/drift/events");
        Files.createDirectories(eventsDir);
        Path shard = eventsDir.resolve("run-1.jsonl");
        Path meta = eventsDir.resolve("run-1.meta.json");
        String shardContent = "{\"contract\":\"item-get\",\"cases\":[\"found\"],\"outcome\":\"passed\"}\n";
        String metaContent = "{\"version\":1,\"classes\":[\"example.ItemTest\"],\"tests\":[\"example.ItemTest#ok\"]}\n";
        Files.writeString(shard, shardContent, StandardCharsets.UTF_8);
        Files.writeString(meta, metaContent, StandardCharsets.UTF_8);

        for (String kind : List.of("changed", "base", "select")) {
            PrepareMojo mojo = newPrepare(root, version, new RecordingLog());
            mojo.fresh = true;
            switch (kind) {
                case "changed" -> mojo.changed = "src/main/java/example/ItemServer.java";
                case "base" -> mojo.base = "HEAD";
                case "select" -> mojo.select = root.resolve("select.json").toString();
                default -> throw new IllegalStateException(kind);
            }
            MojoExecutionException err = expectThrows(MojoExecutionException.class, mojo::execute,
                    "fresh+" + kind + " must fail fast");
            assertContains(err.getMessage(), "drift.fresh cannot be combined", "fresh+" + kind);
            assertEquals(shardContent, Files.readString(shard, StandardCharsets.UTF_8),
                    "fresh+" + kind + " must preserve existing .jsonl shard");
            assertEquals(metaContent, Files.readString(meta, StandardCharsets.UTF_8),
                    "fresh+" + kind + " must preserve existing .meta.json sidecar");
        }
    }

    private static void testSkipFlagsAndMissingAreaPolicies(Path root, String version) throws Exception {
        Files.createDirectories(root);

        RecordingLog skipLog = new RecordingLog();
        PrepareMojo skipMojo = newPrepare(root, version, skipLog);
        skipMojo.skip = true;
        skipMojo.execute();
        assertTrue(skipLog.infos.stream().anyMatch(s -> s.contains("prepare skipped (drift.skip)")),
                "drift.skip must log skip message");

        RecordingLog skipTestsLog = new RecordingLog();
        GateMojo skipTestsGate = newGate(root, version, skipTestsLog);
        skipTestsGate.skipTests = true;
        skipTestsGate.execute();
        assertTrue(skipTestsLog.warns.stream()
                        .anyMatch(s -> s.contains("tests are skipped, so no proof is produced and gate does not run")),
                "skipTests must warn and skip gate");

        RecordingLog mvnSkipLog = new RecordingLog();
        PrepareMojo mvnSkipPrep = newPrepare(root, version, mvnSkipLog);
        mvnSkipPrep.mavenTestSkip = true;
        mvnSkipPrep.execute();
        assertTrue(mvnSkipLog.warns.stream()
                        .anyMatch(s -> s.contains("tests are skipped, so no proof is produced and prepare does not run")),
                "maven.test.skip must warn and skip prepare");

        RecordingLog policySkipLog = new RecordingLog();
        PrepareMojo policySkip = newPrepare(root, version, policySkipLog);
        policySkip.missingArea = "skip";
        policySkip.execute();
        assertTrue(policySkipLog.infos.stream()
                        .anyMatch(s -> s.contains("prepare skipped (module has no .drift directory)")),
                "missingArea=skip must skip unadopted module");
    }

    private static void testMissingConfigShowsAdoptionGuide(Path root, String version) throws Exception {
        Files.createDirectories(root.resolve(".drift"));
        PrepareMojo prep = newPrepare(root, version, new RecordingLog());
        MojoExecutionException prepErr = expectThrows(MojoExecutionException.class, prep::execute,
                "prepare without config.toml must fail");
        assertContains(prepErr.getMessage(), "DRIFT is not adopted in this module", "prepare adoption message");
        assertContains(prepErr.getMessage(), "kind = \"config\"", "prepare config snippet");

        GateMojo gate = newGate(root, version, new RecordingLog());
        MojoExecutionException gateErr = expectThrows(MojoExecutionException.class, gate::execute,
                "gate without config.toml must fail");
        assertContains(gateErr.getMessage(), "kind = \"config\"", "gate config snippet");
    }

    private static void testGateValidationModesAndMissingInputs(Path root, String version) throws Exception {
        Files.createDirectories(root.resolve(".drift"));
        Files.writeString(root.resolve(".drift/config.toml"),
                "drift = \"0.3\"\nkind = \"config\"\n[area]\nowner = \"t\"\n", StandardCharsets.UTF_8);

        GateMojo badMode = newGate(root, version, new RecordingLog());
        badMode.mode = "invalid-mode";
        MojoExecutionException modeErr = expectThrows(MojoExecutionException.class, badMode::execute,
                "invalid drift.mode must be rejected");
        assertContains(modeErr.getMessage(), "drift.mode must be gate or prove", "invalid mode error");

        GateMojo noContracts = newGate(root, version, new RecordingLog());
        MojoFailureException contractsErr = expectThrows(MojoFailureException.class, noContracts::execute,
                "missing contracts directory must fail gate");
        assertContains(contractsErr.getMessage(), "there is no contract to gate", "missing contracts message");

        Files.createDirectories(root.resolve(".drift/contracts"));
        GateMojo noEvents = newGate(root, version, new RecordingLog());
        MojoFailureException eventsErr = expectThrows(MojoFailureException.class, noEvents::execute,
                "missing events must fail gate");
        assertContains(eventsErr.getMessage(), "no test tagged with @DriftCase ran", "missing events message");

        Files.createDirectories(root.resolve("target/drift/events"));
        Files.writeString(root.resolve("target/drift/events/shard.jsonl"), "{}\n", StandardCharsets.UTF_8);
        RecordingLog feedbackLog = new RecordingLog();
        GateMojo feedbackGate = newGate(root, version, feedbackLog);
        feedbackGate.feedback = true;
        feedbackGate.execute();
        assertTrue(feedbackLog.warns.stream().anyMatch(s -> s.contains("feedback, not a proof")),
                "feedback mode must warn and skip CLI execution");
    }

    private static void testCliLocateVersionAndBuildChecks(Path root, String version) throws Exception {
        Files.createDirectories(root);
        MojoExecutionException nonExec = expectThrows(MojoExecutionException.class,
                () -> Cli.locate(root.resolve("missing-drift").toString(), "io.github.rad-ox", version,
                        root, null, null, List.of(), new RecordingLog()),
                "non-executable drift.cli must fail");
        assertContains(nonExec.getMessage(), "is not an executable file", "non-executable cli");

        Path wrongVer = writeStubScript(root.resolve("old-drift"),
                "#!/bin/sh\necho 'drift 9.9.9 (schema 0.3, digest dr2)'\n");
        Cli wrongCli = Cli.locate(wrongVer.toString(), "io.github.rad-ox", version, root, null, null,
                List.of(), new RecordingLog());
        MojoExecutionException verErr = expectThrows(MojoExecutionException.class,
                () -> wrongCli.requireVersion(version, "b1", new RecordingLog()),
                "mismatched CLI version must be refused");
        assertContains(verErr.getMessage(), "is drift 9.9.9, the plugin is " + version, "version mismatch");

        Path brokenVer = writeStubScript(root.resolve("broken-drift"), "#!/bin/sh\necho 'not-a-version'\n");
        Cli brokenCli = Cli.locate(brokenVer.toString(), "io.github.rad-ox", version, root, null, null,
                List.of(), new RecordingLog());
        MojoExecutionException brokenErr = expectThrows(MojoExecutionException.class,
                () -> brokenCli.requireVersion(version, "b1", new RecordingLog()),
                "unparseable version output must be refused");
        assertContains(brokenErr.getMessage(), "does not report a drift version", "broken version");

        Path otherBuild = writeStubScript(root.resolve("other-build-drift"),
                "#!/bin/sh\necho 'drift " + version + " (schema 0.3, digest dr2, build other)'\n");
        Cli otherCli = Cli.locate(otherBuild.toString(), "io.github.rad-ox", version, root, null, null,
                List.of(), new RecordingLog());
        RecordingLog buildWarnLog = new RecordingLog();
        otherCli.requireVersion(version, "plugin-rev", buildWarnLog);
        assertTrue(buildWarnLog.warns.stream()
                        .anyMatch(s -> s.contains("is build other, the plugin is build plugin-rev")),
                "different build must emit warning without failing");

        Path noBuild = writeStubScript(root.resolve("no-build-drift"),
                "#!/bin/sh\necho 'drift " + version + " (schema 0.3, digest dr2)'\n");
        Cli noBuildCli = Cli.locate(noBuild.toString(), "io.github.rad-ox", version, root, null, null,
                List.of(), new RecordingLog());
        RecordingLog cleanBuildLog = new RecordingLog();
        noBuildCli.requireVersion(version, "plugin-rev", cleanBuildLog);
        assertTrue(cleanBuildLog.warns.stream().noneMatch(s -> s.contains("the plugin is build")),
                "CLI without build tag must not emit build mismatch warning");
    }

    private static void testPrepareShadowedArgLineDiagnostics(Path root, String version) throws Exception {
        Files.createDirectories(root.resolve(".drift/contracts"));
        Files.writeString(root.resolve(".drift/config.toml"),
                "drift = \"0.3\"\nkind = \"config\"\n[area]\nowner = \"t\"\n", StandardCharsets.UTF_8);
        Path okDrift = writeStubScript(root.resolve("ok-drift"),
                "#!/bin/sh\nif [ \"$1\" = version ]; then echo 'drift " + version
                        + " (schema 0.3, digest dr2)'; exit 0; fi\nexit 0\n");

        RecordingLog log = new RecordingLog();
        PrepareMojo prep = newPrepare(root, version, log);
        prep.cli = okDrift.toString();
        Plugin surefire = new Plugin();
        surefire.setGroupId("org.apache.maven.plugins");
        surefire.setArtifactId("maven-surefire-plugin");
        Xpp3Dom cfg = new Xpp3Dom("configuration");
        Xpp3Dom argLine = new Xpp3Dom("argLine");
        argLine.setValue("-XX:+UseSerialGC");
        cfg.addChild(argLine);
        surefire.setConfiguration(cfg);
        prep.project.getBuild().addPlugin(surefire);

        prep.execute();
        assertTrue(log.warns.stream()
                        .anyMatch(s -> s.contains("overrides <argLine> without @{argLine}; using session.json fallback")),
                "shadowed argLine warning must be logged");
        Path diag = root.resolve("target/drift/diagnostics.json");
        assertTrue(Files.isRegularFile(diag), "diagnostics.json must be written");
        assertContains(Files.readString(diag, StandardCharsets.UTF_8), "bridge.argline_shadowed",
                "diagnostics.json issue kind");
        assertTrue(Files.isRegularFile(root.resolve("target/drift/session.json")), "session.json must be written");
    }

    private static PrepareMojo newPrepare(Path basedir, String version, RecordingLog log) {
        PrepareMojo mojo = new PrepareMojo();
        configureBase(mojo, basedir, version, log);
        return mojo;
    }

    private static GateMojo newGate(Path basedir, String version, RecordingLog log) {
        GateMojo mojo = new GateMojo();
        configureBase(mojo, basedir, version, log);
        mojo.mode = "gate";
        return mojo;
    }

    private static void configureBase(DriftMojo mojo, Path basedir, String version, RecordingLog log) {
        MavenProject project = new MavenProject();
        project.setFile(basedir.resolve("pom.xml").toFile());
        project.getBuild().setDirectory(basedir.resolve("target").toString());
        project.getBuild().setOutputDirectory(basedir.resolve("target/classes").toString());
        project.getBuild().setTestOutputDirectory(basedir.resolve("target/test-classes").toString());
        PluginDescriptor plugin = new PluginDescriptor();
        plugin.setGroupId("io.github.rad-ox");
        plugin.setArtifactId("drift-maven-plugin");
        plugin.setVersion(version);
        mojo.project = project;
        mojo.plugin = plugin;
        mojo.area = basedir.resolve(".drift").toFile();
        mojo.output = basedir.resolve("target/drift").toFile();
        mojo.missingArea = "auto";
        mojo.repositories = List.of();
        mojo.setLog(log);
    }

    private static Path writeStubScript(Path path, String content) throws IOException {
        Files.writeString(path, content, StandardCharsets.UTF_8);
        if (!path.toFile().setExecutable(true)) {
            throw new IOException("cannot mark executable: " + path);
        }
        return path;
    }

    @FunctionalInterface
    private interface ThrowingRunnable {
        void run() throws Exception;
    }

    private static <T extends Throwable> T expectThrows(Class<T> expected, ThrowingRunnable action, String message) {
        try {
            action.run();
        } catch (Throwable actual) {
            if (expected.isInstance(actual)) {
                return expected.cast(actual);
            }
            throw new AssertionFailedError(message + ": expected " + expected.getSimpleName()
                    + " but caught " + actual.getClass().getSimpleName() + ": " + actual.getMessage(), actual);
        }
        throw new AssertionFailedError(message + ": expected " + expected.getSimpleName() + " to be thrown");
    }

    private static void assertTrue(boolean condition, String message) {
        if (!condition) {
            throw new AssertionFailedError(message);
        }
    }

    private static void assertEquals(String expected, String actual, String message) {
        if (!expected.equals(actual)) {
            throw new AssertionFailedError(message, expected, actual);
        }
    }

    private static void assertContains(String haystack, String needle, String message) {
        if (haystack == null || !haystack.contains(needle)) {
            throw new AssertionFailedError(message + ": expected '" + needle + "' in '" + haystack + "'");
        }
    }

    private static void deleteRecursively(Path root) throws IOException {
        if (!Files.exists(root)) {
            return;
        }
        try (Stream<Path> walk = Files.walk(root)) {
            for (Path p : walk.sorted(Comparator.reverseOrder()).toList()) {
                Files.deleteIfExists(p);
            }
        }
    }

    private static final class RecordingLog implements Log {
        final List<String> infos = new ArrayList<>();
        final List<String> warns = new ArrayList<>();
        final List<String> errors = new ArrayList<>();

        @Override public boolean isDebugEnabled() { return false; }
        @Override public void debug(CharSequence content) {}
        @Override public void debug(CharSequence content, Throwable error) {}
        @Override public void debug(Throwable error) {}
        @Override public boolean isInfoEnabled() { return true; }
        @Override public void info(CharSequence content) { infos.add(String.valueOf(content)); }
        @Override public void info(CharSequence content, Throwable error) { infos.add(String.valueOf(content)); }
        @Override public void info(Throwable error) {}
        @Override public boolean isWarnEnabled() { return true; }
        @Override public void warn(CharSequence content) { warns.add(String.valueOf(content)); }
        @Override public void warn(CharSequence content, Throwable error) { warns.add(String.valueOf(content)); }
        @Override public void warn(Throwable error) {}
        @Override public boolean isErrorEnabled() { return true; }
        @Override public void error(CharSequence content) { errors.add(String.valueOf(content)); }
        @Override public void error(CharSequence content, Throwable error) { errors.add(String.valueOf(content)); }
        @Override public void error(Throwable error) {}
    }
}
