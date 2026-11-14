package drift.maven;

import java.io.IOException;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.LinkedHashSet;
import drift.MutationRunner;
import org.apache.maven.artifact.Artifact;
import org.apache.maven.plugin.MojoExecutionException;
import org.apache.maven.plugin.MojoFailureException;
import org.apache.maven.plugins.annotations.LifecyclePhase;
import org.apache.maven.plugins.annotations.Mojo;
import org.apache.maven.plugins.annotations.Parameter;
import org.apache.maven.plugins.annotations.ResolutionScope;

/**
 * Gates every contract of the area against the events the tests wrote and fails the build
 * when one is not green. By default ({@code -Ddrift.mode=gate}) it runs {@code drift gate}:
 * approved area and contract, and a green proof of the current contract version. With
 * {@code -Ddrift.mode=prove} it runs {@code drift prove}: workers without approval authority
 * verify that the tests prove the current contract version before the owner approves it.
 */
@Mojo(name = "gate", defaultPhase = LifecyclePhase.VERIFY, threadSafe = true,
        requiresDependencyResolution = ResolutionScope.TEST)
public final class GateMojo extends DriftMojo {
    /** {@code gate} (default) or {@code prove} (proof of the current version without requiring approval). */
    @Parameter(property = "drift.mode", defaultValue = "gate")
    String mode;

    /** Optional base contract file or directory for case-level proof reuse ({@code --base}). */
    @Parameter(property = "drift.base")
    String base;

    /** Set by prepare when the test selection was narrowed for feedback. */
    @Parameter(property = "drift.feedback", defaultValue = "false")
    boolean feedback;

    /** Runs the opt-in mutation pass after ordinary tests. */
    @Parameter(property = "drift.mutants", defaultValue = "false")
    boolean mutants;

    /** Includes {@code --when} branch mutants when {@code drift.mutants=true}. */
    @Parameter(property = "drift.mutants.when", defaultValue = "false")
    boolean mutantsWhen;

    /** Optional mutant cap ({@code --budget N}) when {@code drift.mutants=true}. */
    @Parameter(property = "drift.mutants.budget")
    Integer mutantsBudget;

    /** Comma-separated changed source paths, rooted at the Maven module. */
    @Parameter(property = "drift.changed")
    String changed;

    /** Optional level filter ({@code --at}, e.g. {@code unit} or {@code field}). */
    @Parameter(property = "drift.at")
    String at;

    /** Optional prerequisite phase gate ({@code --phase}, {@code execution} or {@code release}). */
    @Parameter(property = "drift.phase")
    String phase;

    /** Optional gate attestation file path ({@code --attest FILE}). */
    @Parameter(property = "drift.attest")
    String attest;

    /** Optional pre-fix proof/gate report for F2P gating ({@code --compare-before FILE}). */
    @Parameter(property = "drift.compareBefore")
    String compareBefore;

    /** Optional explain flag ({@code --explain}). */
    @Parameter(property = "drift.explain", defaultValue = "false")
    boolean explain;

    @Override
    public void execute() throws MojoExecutionException, MojoFailureException {
        if (skipped("gate")) {
            return;
        }
        String command = mode == null ? "gate" : mode.trim();
        if (!command.equals("gate") && !command.equals("prove")) {
            throw new MojoExecutionException("drift.mode must be gate or prove, found " + mode);
        }
        requireArea();
        if (!Files.isDirectory(contracts())) {
            throw new MojoFailureException("drift: " + contracts() + " is missing: there is no contract to " + command);
        }
        if (!hasEvents()) {
            throw new MojoFailureException("drift: " + events() + " is missing: no test tagged with @DriftCase ran,"
                    + " or prepare did not run before the tests");
        }
        if (feedback) {
            getLog().warn("drift: narrowed selection is feedback, not a proof; run without drift.changed for the gate");
            return;
        }
        Cli c = cli();
        Path mutantManifest = null;
        Path mutationEvents = null;
        if (mutants) {
            mutantManifest = output.toPath().resolve("mutants.json");
            mutationEvents = output.toPath().resolve("mutation-events");
            getLog().info("drift: generating mutation manifest " + mutantManifest);
            java.util.ArrayList<String> mutantArgs = new java.util.ArrayList<>(
                    List.of("mutants", contracts().toString(), "--out", mutantManifest.toString()));
            if (mutantsWhen) {
                mutantArgs.add("--when");
            }
            if (mutantsBudget != null) {
                mutantArgs.add("--budget");
                mutantArgs.add(mutantsBudget.toString());
                mutantArgs.add("--events");
                mutantArgs.add(events().toString());
            }
            Cli.Result manifest = c.run(mutantArgs);
            log(manifest);
            if (manifest.status() != 0) {
                throw new MojoFailureException("drift: could not generate the mutation manifest");
            }
            LinkedHashSet<String> classpath = new LinkedHashSet<>();
            classpath.add(project.getBuild().getTestOutputDirectory());
            classpath.add(project.getBuild().getOutputDirectory());
            for (Artifact artifact : project.getTestArtifacts()) {
                File file = artifact.getFile();
                if (file != null && file.exists()) {
                    classpath.add(file.toPath().toAbsolutePath().normalize().toString());
                }
            }
            try {
                MutationRunner.run(mutantManifest, resolved(), events(), mutationEvents,
                        List.copyOf(classpath));
            } catch (IOException | IllegalArgumentException e) {
                throw new MojoExecutionException("drift mutation runner failed", e);
            }
            getLog().info("drift: mutation results written to " + mutationEvents);
        }
        java.util.ArrayList<String> args = new java.util.ArrayList<>(
                List.of(command, contracts().toString(), "--events", events().toString(), "--test-classes",
                        project.getBuild().getTestOutputDirectory()));
        if (at != null && !at.isBlank()) {
            args.add("--at");
            args.add(at.trim());
        }
        if (phase != null && !phase.isBlank() && command.equals("gate")) {
            args.add("--phase");
            args.add(phase.trim());
        }
        if (explain) {
            args.add("--explain");
        }
        if (attest != null && !attest.isBlank() && command.equals("gate")) {
            Path attestPath = Path.of(attest.trim());
            if (!attestPath.isAbsolute()) {
                attestPath = project.getBasedir().toPath().resolve(attestPath).normalize();
            }
            args.add("--attest");
            args.add(attestPath.toString());
        }
        if (compareBefore != null && !compareBefore.isBlank() && command.equals("gate")) {
            Path beforePath = Path.of(compareBefore.trim());
            if (!beforePath.isAbsolute()) {
                beforePath = project.getBasedir().toPath().resolve(beforePath).normalize();
            }
            args.add("--compare-before");
            args.add(beforePath.toString());
        }
        if (mutants) {
            args.add("--mutants");
            args.add(mutantManifest.toString());
            args.add("--mutation-events");
            args.add(mutationEvents.toString());
        }
        if (base != null && !base.isBlank()) {
            args.add("--base");
            args.add(base.trim());
            if (changed != null && !changed.isBlank()) {
                if ("auto".equals(changed.trim())) {
                    String autoState = project.getProperties().getProperty("drift.auto.state", "");
                    if ("none".equals(autoState)) {
                        args.add("--changed-none");
                    } else if ("list".equals(autoState)) {
                        String listPath = project.getProperties().getProperty("drift.auto.list", "");
                        if (!listPath.isBlank()) {
                            args.add("--changed-list");
                            args.add(listPath);
                        }
                    }
                } else {
                    Path module = project.getBasedir().toPath();
                    for (String raw : changed.split(",")) {
                        if (!raw.isBlank()) {
                            Path path = Path.of(raw.trim());
                            args.add("--changed");
                            args.add((path.isAbsolute() ? path : module.resolve(path)).normalize().toAbsolutePath().toString());
                        }
                    }
                }
            }
        }
        Cli.Result r = c.run(args);
        log(r);
        if (r.status() == 1) {
            throw new MojoFailureException("drift: the " + (command.equals("prove") ? "proof" : "gate")
                    + " is not green; see the contracts above");
        }
        if (r.status() != 0) {
            throw new MojoExecutionException("drift " + command + " failed with status " + r.status());
        }
    }
}
