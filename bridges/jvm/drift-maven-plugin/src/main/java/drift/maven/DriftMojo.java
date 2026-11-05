package drift.maven;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
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
        return false;
    }

    Path contracts() {
        return area.toPath().resolve("contracts");
    }

    Path events() {
        return output.toPath().resolve("events");
    }

    boolean hasEvents() throws MojoExecutionException {
        Path ev = events();
        if (Files.isRegularFile(ev)) {
            return true;
        }
        if (Files.isDirectory(ev)) {
            try (var s = Files.list(ev)) {
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
        Path config = area.toPath().resolve("config.toml");
        if (!Files.isRegularFile(config)) {
            throw new MojoExecutionException("DRIFT is not adopted in this module: " + config + " is missing."
                    + System.lineSeparator() + "Create it, then ask the owner to approve it with"
                    + " drift approve " + config + " --by <owner>:" + System.lineSeparator()
                    + System.lineSeparator() + "drift = \"0.2\"" + System.lineSeparator() + "kind = \"config\""
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
