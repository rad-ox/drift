package drift.maven;

import static java.nio.file.Files.*;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.apache.maven.execution.MavenSession;
import org.apache.maven.plugin.AbstractMojo;
import org.apache.maven.plugin.MojoExecutionException;
import org.apache.maven.plugin.descriptor.PluginDescriptor;
import org.apache.maven.plugins.annotations.Component;
import org.apache.maven.plugins.annotations.Parameter;
import org.apache.maven.project.MavenProject;
import org.eclipse.aether.RepositorySystem;
import org.eclipse.aether.RepositorySystemSession;
import org.eclipse.aether.repository.RemoteRepository;

/** What prepare and gate share: the area, the output directory and the drift command. */
abstract class DriftMojo extends AbstractMojo {
    /** The DRIFT area of the module: config.toml, profiles/ and contracts/. */
    @Parameter(property = "drift.area", defaultValue = "${project.basedir}/.drift")
    File area;

    /** Optional external shadow-mode state directory (passed as --state-dir; contains .drift/). */
    @Parameter(property = "drift.stateDir")
    File stateDir;

    /** Where the resolved views and the events go; a clean build removes them. */
    @Parameter(property = "drift.output", defaultValue = "${project.build.directory}/drift")
    File output;

    /** The drift command; by default the drift-cli artifact of this version, else drift on the PATH. */
    @Parameter(property = "drift.cli")
    String cli;

    /** Skips both goals. */
    @Parameter(property = "drift.skip", defaultValue = "false")
    boolean skip;

    @Parameter(property = "skipTests", defaultValue = "false")
    boolean skipTests;

    @Parameter(property = "maven.test.skip", defaultValue = "false")
    boolean mavenTestSkip;

    /** Policy when .drift/ directory is completely absent: auto (skip unadopted child in reactor), skip, or fail. */
    @Parameter(property = "drift.missingArea", defaultValue = "auto")
    String missingArea;

    @Parameter(defaultValue = "${session}", readonly = true)
    MavenSession mavenSession;

    @Parameter(defaultValue = "${project}", readonly = true, required = true)
    MavenProject project;

    @Parameter(defaultValue = "${plugin}", readonly = true, required = true)
    PluginDescriptor plugin;

    @Parameter(defaultValue = "${repositorySystemSession}", readonly = true)
    RepositorySystemSession repositorySession;

    @Parameter(defaultValue = "${project.remotePluginRepositories}", readonly = true)
    List<RemoteRepository> repositories;

    @Component
    RepositorySystem repositorySystem;

    /** Tests that do not run produce no proof, so neither goal has anything to do. */
    boolean skipped(String goal) {
        if (skip) {
            getLog().info("drift: " + goal + " skipped (drift.skip)");
            return true;
        }
        if (skipTests || mavenTestSkip) {
            getLog().warn("drift: tests are skipped, so no proof is produced and " + goal + " does not run");
            return true;
        }
        if (!exists(effectiveArea())) {
            String policy = missingArea == null ? "auto" : missingArea.trim().toLowerCase();
            if ("skip".equals(policy) || ("auto".equals(policy) && reactorHasAdoptedSibling())) {
                getLog().info("drift: " + goal + " skipped (module has no .drift directory)");
                return true;
            }
        }
        return false;
    }

    private boolean reactorHasAdoptedSibling() {
        if (mavenSession == null || mavenSession.getProjects() == null || mavenSession.getProjects().size() <= 1) {
            return false;
        }
        for (MavenProject p : mavenSession.getProjects()) {
            if (p.getBasedir() != null && isRegularFile(p.getBasedir().toPath().resolve(".drift").resolve("config.toml"))) {
                return true;
            }
        }
        return false;
    }

    Path effectiveArea() {
        return stateDir != null ? stateDir.toPath().resolve(".drift") : area.toPath();
    }

    void appendStateDir(List<String> args) {
        if (stateDir != null) {
            args.add("--state-dir");
            args.add(stateDir.toPath().toAbsolutePath().normalize().toString());
        }
    }

    Path contracts() {
        return effectiveArea().resolve("contracts");
    }

    Path events() {
        return output.toPath().resolve("events");
    }

    boolean hasEvents() throws MojoExecutionException {
        Path ev = events();
        if (isRegularFile(ev)) {
            return true;
        }
        if (isDirectory(ev)) {
            try (var s = list(ev)) {
                return s.anyMatch(p -> p.toString().endsWith(".jsonl"));
            } catch (java.io.IOException e) {
                throw new MojoExecutionException("cannot read " + ev, e);
            }
        }
        return false;
    }

    Path resolved() {
        return output.toPath().resolve("resolved");
    }

    /** The area must be adopted: its configuration is what the owner approves first. */
    void requireArea() throws MojoExecutionException {
        Path config = effectiveArea().resolve("config.toml");
        if (!isRegularFile(config)) {
            throw new MojoExecutionException("DRIFT is not adopted in this module: " + config + " is missing."
                    + System.lineSeparator() + "Create it, then ask the owner to approve it with"
                    + " drift approve " + config + " --by <owner>:" + System.lineSeparator()
                    + System.lineSeparator() + "drift = \"0.3\"" + System.lineSeparator() + "kind = \"config\""
                    + System.lineSeparator() + System.lineSeparator() + "[area]" + System.lineSeparator()
                    + "owner = \"<owner>\"" + System.lineSeparator());
        }
    }

    Cli cli() throws MojoExecutionException {
        Cli c = Cli.locate(cli, plugin.getGroupId(), plugin.getVersion(), output.toPath(), repositorySystem,
                repositorySession, repositories, getLog());
        c.requireVersion(plugin.getVersion(), Cli.pluginBuild(), getLog());
        return c;
    }

    void log(Cli.Result r) {
        for (String line : r.lines()) {
            getLog().info(line);
        }
    }
}
