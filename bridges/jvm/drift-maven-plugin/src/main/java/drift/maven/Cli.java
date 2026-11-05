package drift.maven;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.apache.maven.plugin.MojoExecutionException;
import org.apache.maven.plugin.logging.Log;
import org.eclipse.aether.RepositorySystem;
import org.eclipse.aether.RepositorySystemSession;
import org.eclipse.aether.artifact.DefaultArtifact;
import org.eclipse.aether.repository.RemoteRepository;
import org.eclipse.aether.resolution.ArtifactRequest;
import org.eclipse.aether.resolution.ArtifactResolutionException;

/**
 * The drift command the build runs: the configured path, else the drift-cli artifact of the
 * plugin version for this platform, else drift on the PATH. Its version must be the plugin
 * version, so the events the bridge writes are the ones the command reads.
 */
final class Cli {
    private static final Pattern VERSION = Pattern.compile("^drift (\\S+)");
    private static final Pattern BUILD = Pattern.compile(", build ([^)\\s]+)\\)");
    private static final long TIMEOUT_MINUTES = 10;
    private static final Map<String, String> VERIFIED_VERSIONS = new ConcurrentHashMap<>();

    final Path path;

    private Cli(Path path) {
        this.path = path;
    }

    /** The output of one run: its exit status and its merged standard output and error. */
    record Result(int status, List<String> lines) {}

    static Cli locate(String configured, String groupId, String version, Path work, RepositorySystem system,
            RepositorySystemSession session, List<RemoteRepository> repositories, Log log)
            throws MojoExecutionException {
        if (configured != null && !configured.isBlank()) {
            Path p = Path.of(configured);
            if (!Files.isExecutable(p)) {
                throw new MojoExecutionException("drift.cli " + configured + " is not an executable file");
            }
            return new Cli(p);
        }
        String classifier = classifier();
        if (classifier != null && system != null && session != null) {
            DefaultArtifact artifact = new DefaultArtifact(groupId, "drift-cli", classifier, "exe", version);
            try {
                Path resolved = system.resolveArtifact(session,
                        new ArtifactRequest(artifact, repositories, null)).getArtifact().getFile().toPath();
                Path target = work.resolve("bin").resolve(windows() ? "drift.exe" : "drift");
                Files.createDirectories(target.getParent());
                if (!Files.isRegularFile(target) || !Files.isExecutable(target)
                        || Files.size(resolved) != Files.size(target)
                        || Files.mismatch(resolved, target) != -1L) {
                    Path tmp = Files.createTempFile(target.getParent(), ".drift-", ".tmp");
                    try {
                        Files.copy(resolved, tmp, StandardCopyOption.REPLACE_EXISTING);
                        if (!tmp.toFile().setExecutable(true)) {
                            throw new MojoExecutionException("cannot make " + tmp + " executable");
                        }
                        Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING);
                    } finally {
                        Files.deleteIfExists(tmp);
                    }
                }
                log.debug("drift: using " + artifact);
                return new Cli(target);
            } catch (ArtifactResolutionException e) {
                log.debug("drift: " + artifact + " is not available: " + e.getMessage());
            } catch (IOException e) {
                throw new MojoExecutionException("cannot copy the drift command", e);
            }
        }
        String name = windows() ? "drift.exe" : "drift";
        for (String dir : System.getenv().getOrDefault("PATH", "").split(File.pathSeparator)) {
            if (dir.isBlank()) {
                continue;
            }
            Path p = Path.of(dir, name);
            if (Files.isExecutable(p)) {
                return new Cli(p);
            }
        }
        throw new MojoExecutionException("the drift command was not found: set <cli> or -Ddrift.cli, install "
                + "drift on the PATH, or make " + groupId + ":drift-cli:" + version + " available");
    }

    /**
     * Fails unless the command reports the plugin version; warns when both name a build and the
     * builds differ, since builds of one version share the event format (D40).
     */
    void requireVersion(String expected, String build, Log log) throws MojoExecutionException {
        try {
            Path abs = path.toAbsolutePath().normalize();
            String cacheKey = abs + "\u0000" + Files.getLastModifiedTime(abs).toMillis() + "\u0000" + Files.size(abs);
            String want = expected + "\u0000" + build;
            if (want.equals(VERIFIED_VERSIONS.get(cacheKey))) {
                return;
            }
            Result r = run(List.of("version"));
            String line = r.lines().isEmpty() ? "" : r.lines().get(0);
            Matcher m = VERSION.matcher(line);
            if (r.status() != 0 || !m.find()) {
                throw new MojoExecutionException(path + " does not report a drift version: " + r.lines());
            }
            if (!m.group(1).equals(expected)) {
                throw new MojoExecutionException(path + " is drift " + m.group(1) + ", the plugin is " + expected
                        + ": install drift " + expected + " or set <cli> to it");
            }
            Matcher b = BUILD.matcher(line);
            if (!build.isEmpty() && b.find() && !b.group(1).equals(build)) {
                log.warn("drift: " + path + " is build " + b.group(1) + ", the plugin is build " + build
                        + ": re-run the release installer (or make install), or set <cli> to the same build");
            }
            VERIFIED_VERSIONS.put(cacheKey, want);
        } catch (IOException e) {
            throw new MojoExecutionException("cannot stat " + path, e);
        }
    }

    /** The build identity the plugin was built with, empty when none (D40). */
    static String pluginBuild() {
        try (InputStream in = Cli.class.getResourceAsStream("build.properties")) {
            if (in == null) {
                return "";
            }
            Properties p = new Properties();
            p.load(in);
            String b = p.getProperty("build", "").trim();
            return b.startsWith("${") ? "" : b;
        } catch (IOException e) {
            return "";
        }
    }

    Result run(List<String> args) throws MojoExecutionException {
        List<String> command = new ArrayList<>();
        command.add(path.toString());
        command.addAll(args);
        try {
            Process p = new ProcessBuilder(command).redirectErrorStream(true).start();
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            try (InputStream in = p.getInputStream()) {
                in.transferTo(out);
            }
            if (!p.waitFor(TIMEOUT_MINUTES, TimeUnit.MINUTES)) {
                p.destroyForcibly();
                throw new MojoExecutionException(String.join(" ", command) + " did not finish in "
                        + TIMEOUT_MINUTES + " minutes");
            }
            String text = out.toString(StandardCharsets.UTF_8);
            return new Result(p.exitValue(), text.isEmpty() ? List.of() : List.of(text.split("\\R")));
        } catch (IOException e) {
            throw new MojoExecutionException("cannot run " + path, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new MojoExecutionException("interrupted while running " + path, e);
        }
    }

    private static boolean windows() {
        return System.getProperty("os.name", "").toLowerCase(Locale.ROOT).startsWith("windows");
    }

    /** linux-x86_64 or windows-x86_64, the platforms drift-cli is built for; null otherwise. */
    static String classifier() {
        String os = System.getProperty("os.name", "").toLowerCase(Locale.ROOT);
        String arch = System.getProperty("os.arch", "").toLowerCase(Locale.ROOT);
        if (!arch.equals("amd64") && !arch.equals("x86_64")) {
            return null;
        }
        return os.startsWith("linux") ? "linux-x86_64" : os.startsWith("windows") ? "windows-x86_64" : null;
    }
}
