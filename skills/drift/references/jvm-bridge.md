# JVM bridge (JUnit Platform)

Read when binding tests to a contract or running the gate on a JVM project.

## Quick path

- With the Maven plugin: `mvn verify` exports the views, runs the tests and
  fails unless every contract is green.
- Without it: `drift show .drift/contracts --as json --out "$OUT/resolved"`,
  then `mvn test -Ddrift.resolved="$OUT/resolved" -Ddrift.events="$OUT/events.jsonl"`,
  then `drift gate .drift/contracts --events "$OUT/events.jsonl" --json`.

## Dependency

The release installer puts `io.github.rad-ox:drift-junit:0.7.0` and
`io.github.rad-ox:drift-maven-plugin:0.7.0` (from `maven/` in the release package) into
the current user's local Maven repository; neither is published to a remote
repository. Contributors working in a DRIFT source checkout can run
`make install` instead. If a build cannot resolve them, check that both use the
same local repository (in particular any `settings.xml` `<localRepository>` or
`-Dmaven.repo.local`); never vendor them into the project. Install the bridge
together with the `drift` CLI: an older bridge gives every dynamic test one
id, and reruns then collapse them.

```xml
<dependency>
  <groupId>io.github.rad-ox</groupId>
  <artifactId>drift-junit</artifactId>
  <version>0.7.0</version>
  <scope>test</scope>
</dependency>
```

## Build with the Maven plugin

```xml
<plugin>
  <groupId>io.github.rad-ox</groupId>
  <artifactId>drift-maven-plugin</artifactId>
  <version>0.7.0</version>
  <executions>
    <execution>
      <goals>
        <goal>prepare</goal>
        <goal>gate</goal>
      </goals>
    </execution>
  </executions>
</plugin>
```

- `prepare` (phase `initialize`):
  - exports every contract of `.drift/contracts` to `target/drift/resolved`
    and adds `-Ddrift.resolved` and `-Ddrift.events` to `argLine`; if the
    surefire configuration sets its own `<argLine>`, put `@{argLine}` in it,
    as for JaCoCo;
  - in a non-ignored Git worktree, captures a Git tree snapshot through a
    temporary copy of `.git/index` and passes `-Ddrift.snapshot`, so each
    shard's `.meta.json` records `snapshot`;
  - with `-Ddrift.fresh=true`, removes old event shards and inventories before
    a full run; it cannot be combined with `drift.changed`, `drift.base` or an
    explicit `drift.select`;
  - with `-Ddrift.changed=path1,path2` and prior events, runs `drift select` on
    `.drift/contracts`, sets `-Ddrift.select=target/drift/select.json` and
    marks the narrowed run as feedback only;
  - with `-Ddrift.changed=auto`, when every effective prior shard has a
    `snapshot`, unions `git diff --no-renames --name-only` from those snapshots
    to the current one, runs `drift select` and keeps `gate` or `prove` active
    at `verify`; when a shard lacks a snapshot it widens and disables base
    reuse.
- `gate` (phase `verify`) runs `drift gate` on `.drift/contracts` with
  `target/drift/events` and the compiled test classes, then fails the build
  unless every contract is green.
  `mvn verify` is the whole loop; `mvn test` stops before the gate.
  With `-Ddrift.mode=prove` it runs `drift prove` instead: a remote worker
  without approval authority verifies that every case is proven against the
  current contract version before the owner runs `drift approve`.
- By default `prepare` sets `-Ddrift.events` to the `target/drift/events`
  directory, and `DriftListener` writes one `<utcMillis>-<pid>-<seq>.jsonl`
  file and matching `.meta.json` inventory per test plan inside it, so forked
  JVMs and local/remote runs never contend on one file and sort in chronological
  order. The inventory records tagged methods before the selection filter runs.
- The plugin runs `<cli>` (`-Ddrift.cli=PATH`) when set, else the
  `io.github.rad-ox:drift-cli` artifact for the platform when it resolves, else `drift`
  on PATH, and stops when its version differs from the plugin's.
- `-Ddrift.skip`, `-DskipTests` and `-Dmaven.test.skip` skip both goals;
  `<area>` and `<output>` move `.drift` and `target/drift`.
- Events stay between builds: a test run again replaces its earlier event.
  After changing production code in `scope.code` to fix a failing case, rerun
  all tests bound to the touched contract (or use `-Ddrift.changed=auto`)
  instead of a single test method, so sibling cases are re-verified against the
  fixed code (`drift stats <dir> --compare before=<red.json> --compare
  after=<green.json> --json` checks `f2p_verified = true` and `regressed = 0`).
  `-Ddrift.fresh=true` explicitly starts a full run from empty
  proof output; `mvn clean` also starts over.

## Tagging a test

```java
@Test
@DriftCase(contract = "item-get", cases = "found", level = "http")
void returnsAnExistingItem() throws Exception {
    Drift.Case c = Drift.expect("item-get", "found");
    HttpResponse<String> r = send(c.whenString("request"));
    assertEquals(c.thenInt("status"), r.statusCode());
}
```

- `level` must be one of the case's `at` levels, or any word when `at` is absent.
- Read expected values from `Drift.expect`, never copy them into the test: a
  changed `then` must turn the test red.
- A case is `verified` only when the test read every `then` value of it,
  through `then(name)`, the typed readers, `findThen`, the values of the
  `then()` map or `check`; reading only some proves it `bound`.
- Assert every `then` predicate read through `Drift.expect` so any violation of
  a contracted outcome fails the test, and avoid asserting uncontracted
  representation details (such as exact JSON key order, whitespace or absent
  optional fields) that would reject valid alternative implementations.
- `c.check(Map.of("status", v -> assertEquals(v, (long) r.statusCode()), ...))`
  runs one check per `then` predicate and fails when one has no check, so a
  predicate added to the contract cannot pass unchecked; checks for
  predicates the case lacks are ignored. `c.checkBounds(Drift.intDomain(min,
  max), Map.of("status", (v, sample) -> ...))` (`d.checkBounds` in JS,
  `d.check_bounds` in Python) verifies every `then` predicate across the
  deterministic boundary lattice and reports the first failing sample as
  `[counterexample: <sample>]`.
- When the profile declares `[projections]` (RFC 6901 JSON Pointers for `when`
  and `then`), `c.buildInput()` (`d.buildInput(caseId)` in JS,
  `d.build_input(case_id)` in Python) synthesizes the request payload with
  active `--when` mutant overrides, and `c.checkProjection(payload)`
  (`await d.checkProjection(caseId, payload)` in JS,
  `d.check_projection(case_id, payload)` in Python) verifies every projected
  `then` predicate (including relational constraint tables with `min`, `max`,
  `min_len`, `max_len`, `non_empty`, `le_field`, `ge_field`, `eq_field` and
  `in`) and marks the case `verified`.
- Without the exported view, `Drift.expect` throws and the test fails: export
  first, then run.
- `when(name)`, `then(name)` and the typed readers throw on a predicate the
  case does not have; read an optional predicate with `findWhen(name)` or
  `findThen(name)`, which return an `Optional`.
- `DriftListener` registers itself through `ServiceLoader`; it writes one JSONL
  event per tagged test and a sibling inventory sidecar only when
  `drift.events` is set. The `DriftSelect` discovery pass records tagged
  methods before it excludes tests from a narrowed plan.
- Inside a running `@DriftCase`-annotated test, `Drift.expect` accepts only the
  contract and cases of its `@DriftCase`. Tag every case the test reads, so
  that selection reruns it when one of them changes. In an unannotated or
  closure-based JVM test (such as Scala 3 MUnit `FunSuite`), calling
  `Drift.expect(contract, caseId[, level])` dynamically binds the running test,
  and `c.verify(entries...)` checks tuple (`_1`/`_2`), map, iterable, record/product
  or key-value entries against `[projections.then]` and relational bounds while
  emitting `.jsonl`/`.meta.json` shards even when `DriftListener` is inactive.

## Run without the plugin

Pass the two system properties to the test JVM:

```xml
<plugin>
  <artifactId>maven-surefire-plugin</artifactId>
  <configuration>
    <systemPropertyVariables>
      <drift.resolved>${drift.resolved}</drift.resolved>
      <drift.events>${drift.events}</drift.events>
    </systemPropertyVariables>
  </configuration>
</plugin>
```

```bash
drift show .drift/contracts --as json --out "$OUT/resolved"
mvn test -Ddrift.resolved="$OUT/resolved" -Ddrift.events="$OUT/events.jsonl"
drift gate .drift/contracts --events "$OUT/events.jsonl" --json
```

Keep `$OUT` under the build directory; never commit resolved views or events.
The events file may keep earlier runs: the gate takes each test's last event
for the current version. `--events` may be repeated, and a directory stands
for its `*.jsonl` files.

### Scala 3 / MUnit and `sbt` (`build.sbt`)

Resolve `io.github.rad-ox:drift-junit` from the local Maven repository in `build.sbt` and
pass `drift.resolved` and `drift.events` to the forked test JVM:

```scala
scalaVersion := "3.9.0"
resolvers += Resolver.mavenLocal
libraryDependencies += "io.github.rad-ox" % "drift-junit" % "0.7.0" % Test
Test / fork := true
Test / javaOptions ++= Seq(
  s"-Ddrift.resolved=${baseDirectory.value}/target/drift/resolved",
  s"-Ddrift.events=${baseDirectory.value}/target/drift/events"
)
```

```scala
import drift.Drift

class ItemSuite extends munit.FunSuite:
  test("returns existing item") {
    val c = Drift.expect("item-get", "found", "http")
    val res = send(c.whenString("request"))
    c.verify("status", res.status, "name", res.name)
  }
```

```bash
drift show .drift/contracts --as json --out target/drift/resolved
sbt test
drift gate .drift/contracts --events target/drift/events --json
```

## Selecting tests after a contract change

```bash
drift select "$BASE/item-get.toml" .drift/contracts/item-get.toml \
  --events "$OUT/events.jsonl" --json > "$OUT/select.json"
mvn test -Ddrift.resolved="$OUT/resolved" -Ddrift.events="$OUT/next.jsonl" \
  -Ddrift.select="$OUT/select.json"
```

- `$BASE` holds the approved version the events were recorded against; the
  events must come from a full run of that version.
- Exit 0 narrows; exit 1 widens (`"all": true`) and the filter runs every test.
  Join several selections with the path separator.
- A narrowed run executes only tests tagged with a changed case of that
  contract or listed in `tests`; code-hit and one-hop resource-hit contracts
  also run every tagged test. Untagged tests are excluded.
- Selection is feedback, not proof: before the gate, run the full suite
  against the new digest.

## Outcomes

| JUnit | event outcome | case state |
|---|---|---|
| successful, every `then` read | passed | verified |
| successful, a `then` not read | passed | bound |
| failed | failed | red |
| failed by `TimeoutException` | timeout | timeout |
| aborted (assumption) | skipped | skipped |
| disabled | disabled | skipped |

## Limits

Reads are recorded per thread: a test that calls `Drift.expect` from another
thread proves `bound`, and the tag check does not apply there.
Selection sees contract changes only; after a change of code, tests or build,
run the full suite. A `@TestFactory`, `@ParameterizedTest` or
`@RepeatedTest` tagged with `@DriftCase` writes one event per invocation,
named after the method and its position (`ItemTest#cases[3]`, nested
`[2.3]`); the gate counts each and lists failing ones under `failing`. A
disabled test class reports no events, so its cases stay `missing`. Results
are never reused across versions: after a contract change and its
re-approval, run the tests again.

## JavaScript (`bridges/drift.mjs`) and Python (`bridges/drift.py`)

Installed at `~/.local/share/drift/bridges/` on Linux and
`%LOCALAPPDATA%\Programs\drift\bridges\` on Windows (`bridges/drift.mjs` and
`bridges/drift.py` in the release package). Both zero-dependency bridges read
`DRIFT_RESOLVED` (or auto-resolve from
`.drift/resolved`, `.drift-work/resolved`, `target/drift/resolved` or
`.drift/contracts/**/<id>.toml` via `drift show --as json` using `DRIFT_CLI` or
`drift`, auto-creating and caching the fresh view in `.drift-work/resolved/<id>.json`
when running a single test without `DRIFT_RESOLVED`), write events and
`.meta.json` sidecars to `DRIFT_EVENTS` (auto-creating `.drift-work/events` on a
cold run inside an area), honour `DRIFT_SELECT` (`selectFiles`/`select_files` or
`drift select --files`), `DRIFT_CONTRACTS=<id1,id2>` (`-Ddrift.contracts` on the
JVM) and `DRIFT_SNAPSHOT`, and can be executed directly as a single-command
runner (`node lib/drift.mjs [test|prove|gate] <contract...> [--prove|--gate]
[--json]` or `python3 lib/drift.py <contract...>`) to export
`.drift-work/resolved`, run only the test files bound to `<contract...>` and
verify the partial gate in one step. They also provide `check(caseId, checks)`,
`checkBounds`/`check_bounds`, `checkProfileBounds`/`check_profile_bounds`,
`checkView`/`check_view` (`baseline_state`, `duplicate_figures`,
`single_metric_source`, `clipped_elements`, `horizontal_overflow_px`,
`min_contrast_ratio`, `min_target_px`, `obscured_focus_elements`,
`preserved_input_on_error`, `claim_matches_evidence`) and
`readFixture`/`read_fixture` (`recordInput`/`record_input`, recording per-test
file digests in `.meta.json` `inputs` alongside optional `DRIFT_ENV` /
`DRIFT_PROOF_KEY=1`), and execute manifest mutants in process when
`DRIFT_MUTANTS` and `DRIFT_MUTATION_EVENTS` are set.

- Node.js (`node --test`):
  ```js
  import { test } from 'node:test';
  import assert from 'node:assert/strict';
  import { runDriftCase } from './lib/drift.mjs';

  test('returns item', async (t) => {
    await runDriftCase({ contract: 'item-get', t, cases: ['found'], level: 'http' }, async (d) => {
      const res = await send(d.when('found', 'request'));
      await d.check('found', { status: (v) => assert.equal(res.status, v) });
    });
  });
  ```
- Python (`pytest` or `python3`):
  ```python
  import drift

  def test_found():
      drift.run_drift_case(
          contract="item-get",
          test="test_items.py#test_found",
          cases=["found"],
          level="http",
          fn=lambda d: d.check("found", {"status": lambda v: assert_eq(send(d.when("found", "request")).status, v)}),
      )
  ```
- Rust (`cargo test` with `drift_rust` in `bridges/rust`):
  ```rust
  use drift_rust::{canonical_rust_test_id, run_drift_case, RunOptions};

  #[test]
  fn test_found() {
      let tid = canonical_rust_test_id("catalog", module_path!(), "test_found");
      run_drift_case(
          RunOptions {
              contract: "item-get".to_string(),
              test: tid,
              cases: vec!["found".to_string()],
              level: "http".to_string(),
              ..Default::default()
          },
          |ctx| ctx.check_projection("found", &send(ctx.when_str("found", "request")?)),
      ).expect("drift case verified");
  }
  ```
- V (`v -path "bridges/v|@vlib|@vmodules" test .` with `drift_v` in `bridges/v/drift_v`):
  ```v
  import drift_v

  fn test_found() {
      res := drift_v.run_drift_case(drift_v.RunOptions{
          contract: 'item-get'
          test:     'items_test#test_found'
          cases:    ['found']
          level:    'http'
      }, fn (mut ctx drift_v.DriftContext) ! {
          ctx.check_projection('found', send(ctx.when_str('found', 'request')!))!
      }) or { panic(err) }
      assert res == 'passed'
  }
  ```
- When `core@1` or `requires.proof = "killed"` is active, generate the mutant
  manifest with `drift mutants .drift/contracts --out "$OUT/mutants.json"
  [--when]`, run the test suite with `DRIFT_MUTANTS="$OUT/mutants.json"` and
  `DRIFT_MUTATION_EVENTS="$OUT/mut-events"` (or `-Ddrift.mutants` / `-Ddrift.mutants.when` / `-Ddrift.mutants.budget` and
  `-Ddrift.mutationEvents` on the JVM), and pass `--mutants
  "$OUT/mutants.json" --mutation-events "$OUT/mut-events"` to `drift prove` or
  `drift gate`.
- Pass `--at LEVEL...` to `prove` or `gate` (or `-Ddrift.at=<level>` in Maven)
  to separate offline `unit` gates from read-only `field` invariants on real
  repositories; pass `--phase execution|release` (or `-Ddrift.phase`) to
  enforce `decide_by` and `blocks` deadlines; pass `--compare-before <file>`
  (or `-Ddrift.compareBefore`) to enforce atomic fault-to-pass (`f2p`) bugfix
  transitions; pass `--explain` (or `-Ddrift.explain=true`) to `prove`, `gate`
  or `select` to inspect `priority_tests` (fail-fast order on narrowed `select`),
  `evidence_matrix` (including `flaky`), `triage` (`flaky_or_env`,
  `code_regression`, `missing_binding`, `weak_oracle`), `reuse`
  (`snapshot_verified`, `proof_key_verified`), `matched_code`,
  `matched_resources` and `matched_inputs`; pass `--attest FILE` (or `-Ddrift.attest=<file>`) to `gate`
  to write a canonical `gate/v1` attestation bundle (`--as junit` for JUnit
  XML).

## Legacy Monolith Bridges (`bridges/legacy/junit4/DriftJUnit4.java`)

Main JVM support (`io.github.rad-ox:drift-junit`) targets LTS Java 25 (`--release 25`), Scala 3.9 LTS, and JUnit 5 Platform. For legacy Java 6–8 / JUnit 4 monoliths without JUnit 5 on the classpath, use the dedicated legacy bridge `drift.junit4.DriftJUnit4` (`bridges/legacy/junit4/DriftJUnit4.java` / `~/.local/share/drift/bridges/legacy/junit4/DriftJUnit4.java`):
- `@DriftJUnit4.Case(contract = "<id>", value = {"<case>"}, level = "unit")` tags JUnit 4 methods.
- `DriftJUnit4.Listener` records `.meta.json` inventories and `bound` proof events (`passed`, `failed`, `skipped` on assumption failure, `disabled` on `@Ignore`).
- `DriftJUnit4.verify(contract, caseId, observations, frames)` checks projections, relational bounds, and forbidden write frames to promote a case to `verified`, and `DriftJUnit4.replayCounterexamples(...)` replays `*.cex.json` regression fixtures.


