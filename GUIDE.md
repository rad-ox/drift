# DRIFT Practical Guide

**English** · [Italiano](GUIDE.it.md)

<p align="center">
  <img src="assets/workflow.svg" alt="DRIFT Verification Loop" width="100%" />
</p>

DRIFT keeps one behaviour contract per slice in `.drift/contracts/<id>.toml`.
The human owner approves a specific version of the contract (`dr1:<hash>`), and
the release gate is **green** only when tests that ran against that exact
version pass. Editing a contract's rules or outcomes makes its approval stale
(moving its `scope.code` paths or `owners` does not invalidate the behavioural
digest during internal file renames—protect `.drift/**` via GitHub `CODEOWNERS`
and signed commits so both `[approval]` and `scope.code` edits require
authenticated owner review on pull requests), and an older test run never proves
a newer contract.

Install DRIFT first with **[INSTALL.md](INSTALL.md)** ([Italiano](INSTALL.it.md)).

---

## Core Concepts at a Glance

| Concept | File / Artifact | Role |
|---|---|---|
| **Area** | `.drift/config.toml` | Root configuration defining the area name, optional policy pack, and approvers. |
| **Profile** | `.drift/profiles/<name>@<ver>.toml` | Declares the allowed `when` (inputs/preconditions) and `then` (outcomes) predicates. |
| **Contract** | `.drift/contracts/<slice>.toml` | States the intended behaviour of one slice: `[scope]`, `[cases.<id>]`, and `[decisions.<id>]`. |
| **Approval** | `[approval]` (`ref = "dr1:..."`) | Seal recorded by `drift approve --by <owner>`. Turns `stale` (`DR-E601`) if behaviour is edited. |
| **Resolved View** | `<slice>.json` | Canonical JSON exported by `drift show --as json` and consumed by runtime test bridges. |
| **Proof Event** | `events.jsonl` + `.meta.json` | Emitted by JUnit, Node.js, or Python test runners when bound tests execute against a contract. |
| **Gate** | `drift gate` | Verifies that config + contracts are approved and every required case has a passing current proof. |

---

## Adopt DRIFT in 4 Progressive Levels

Each level delivers standalone value—stop where the cost stops paying, or climb all the way to mutation-verified release attestations:

| Level | You Add | You Get | Edition |
|---|---|---|---|
| **Level 0** | `.drift/config.toml` + `.drift/contracts/*.toml` | Owner-approved behaviour records that automatically turn stale on unapproved edits | **Free** |
| **Level 1** | Test bindings (`@DriftCase`, `runDriftCase`, `run_drift_case`) | A gate that turns **green** only when real tests pass against the approved version | **Free** |
| **Level 2** | Change-aware test selection (`drift select`, `-Ddrift.changed`) | Fast incremental test runs and snapshot-backed proof reuse across large repositories | **Pro** |
| **Level 3** | `[policy]` (`core@1`) + `drift mutants` + `gate --attest` | Listed approvers, mandatory `verified` / `killed` proof floors, and cryptographic gate bundles | **Enterprise** |

---

## Level 0: Contracts, Decision Cards & Owner Approval

### 1. Initialize an Area

Bootstrap a `.drift` area in your project root (or copy a profile from `example/.drift/profiles/http-json@1.toml`):

```bash
drift new --area catalog-service .
drift approve .drift/config.toml --by alice
```

### 2. Scaffold a Slice Contract

```bash
drift new .drift/contracts/item-get.toml --profile http-json@1 --intent "Return one item by id."
```

By design, a freshly scaffolded contract **cannot be approved yet**:
`indirect = "unknown"`, placeholder `todo` values, and any `[open.<id>]`
question block approval (`DR-E602`) so placeholders never slip into production.

### 3. Fill Scope, Cases & Decisions

Replace the placeholders with your concrete slice behaviour:

```toml
drift = "0.2"
id = "item-get"
intent = "Return one item by id."

[use]
profile = "http-json@1"

[scope]
surface = "GET /items/{id}"
writes = []
reads = ["items"]
indirect = "none"
code = ["src/main/java/example/items/**"]

[cases.found]
at = ["http"]
when.request = "GET /items/1"
then.status = 200
then.name = "lamp"

[cases.missing]
at = ["http"]
when.request = "GET /items/99"
then.status = 404
then.error = "not_found"

[decisions.cache-lookup]
kind = "choice"
ask = "Read directly from the primary store or an in-memory cache?"
pick = "primary-store"
cases = ["found", "missing"]
note = "Single-node catalog latency is <2ms; caching adds invalidation complexity."
evidence = "observed"
why = "Direct read keeps consistency trivial without extra state."
options.primary-store = { does = "Query primary store on every GET.", complexity = "1/4", effort_h = 1, risk = "1/4", undo = "easy", leverage = "3/4" }
options.read-through-cache = { does = "Cache items by id with TTL.", complexity = "3/4", effort_h = 4, risk = "2/4", undo = "easy", leverage = "2/4" }
```

> **Note on TOML comments:** DRIFT refuses `#` comments in `.toml` files (`DR-E004`) so rationale is never hidden from review packets or digests. Put all prose inside `intent`, `ask`, `note`, `why`, or `because`.

### 4. Format, Check, Review & Approve

```bash
drift fmt .drift                                      # Canonical key ordering
drift check .drift                                    # Static validation in one pass
drift review .drift/contracts/item-get.toml --brief   # Prints cases + decision cards (exits 1 until approved)
drift approve .drift/contracts/item-get.toml --by alice
```

If `drift check` reports a finding, run `drift explain <code>` (for example `drift explain DR-E601`) to see the exact cause and fix.

---

## Level 1: Binding Tests & Enforcing the Gate

Before any test has run against the approved contract, `drift gate` reports every case as `missing`:

```text
item-get dr1:5922b40e14d7: not green (proof.not_green); 2 missing
```

### Option A: Java / Maven (`drift-junit` + `drift-maven-plugin`)

Add the dependency and plugin to `pom.xml`:

```xml
<dependencies>
  <dependency>
    <groupId>drift</groupId>
    <artifactId>drift-junit</artifactId>
    <version>0.3.0</version>
    <scope>test</scope>
  </dependency>
</dependencies>

<build>
  <plugins>
    <plugin>
      <groupId>drift</groupId>
      <artifactId>drift-maven-plugin</artifactId>
      <version>0.3.0</version>
      <executions>
        <execution>
          <goals>
            <goal>prepare</goal>
            <goal>gate</goal>
          </goals>
        </execution>
      </executions>
    </plugin>
  </plugins>
</build>
```

Bind your JUnit 5 test methods with `@DriftCase` and read expected values via `Drift.expect`:

```java
@Test
@DriftCase(contract = "item-get", cases = "found", level = "http")
void returnsAnExistingItem() throws Exception {
    Drift.Case c = Drift.expect("item-get", "found");
    HttpResponse<String> r = send(c.whenString("request"));
    assertEquals(c.thenInt("status"), r.statusCode());
    assertEquals(c.thenString("name"), parseName(r.body()));
}
```

Then run:

```bash
mvn verify
```

- **`verified` vs `bound`**: When your test reads **every** `then` field of a case through `Drift.expect`, the case reaches **`verified`**. If the test runs and passes without reading all `then` fields, it is recorded as **`bound`**.

### Option B: JavaScript / TypeScript (`bridges/drift.mjs`)

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runDriftCase } from './drift.mjs';

test('returns existing item', async (t) => {
  await runDriftCase({ contract: 'item-get', t, cases: ['found'], level: 'http' }, async (d) => {
    const res = await send(d.when('found', 'request'));
    await d.check('found', {
      status: (v) => assert.equal(res.status, v),
      name:   (v) => assert.equal(res.body.name, v),
    });
  });
});
```

Run your test suite and gate:

```bash
node --test
drift gate .drift/contracts --events .drift/events
```

### Option C: Python 3 (`bridges/drift.py`)

```python
import drift

def test_found():
    drift.run_drift_case(
        contract="item-get",
        test="test_items.py#test_found",
        cases=["found"],
        level="http",
        fn=lambda d: d.check(
            "found",
            {
                "status": lambda v: assert_eq(send(d.when("found", "request")).status, v),
                "name":   lambda v: assert_eq(send(d.when("found", "request")).name, v),
            },
        ),
    )
```

```bash
pytest
drift gate .drift/contracts --events .drift/events
```

---

## Level 2: Incremental Test Selection & Blast Radius (`Pro`)

As an area grows, running every test suite on every edit slows feedback. **DRIFT Pro** uses the `scope.code`, `scope.reads`, and `scope.writes` graph to select only the tests affected by a change—and safely widens to all tests whenever ownership is uncertain:

```bash
# List only the test files affected by modified source paths
drift select .drift/contracts --events .drift/events --changed src/items.js --files

# Reuse prior passing proofs for untouched contracts on a green gate
drift gate .drift/contracts --events .drift/events --base HEAD --changed src/items.js

# Inspect blast radius or query compact @recall context capsules
drift impact .drift --writes items --transitive
drift impact .drift --recall "item lookup #getItem /800t"
```

In Maven projects, `-Ddrift.changed=auto` captures a Git tree snapshot during `prepare` and reuses unchanged test shards automatically while keeping `gate` active.

---

## Level 3: High-Assurance Policy & Mutation Testing (`Enterprise`)

For critical services, add a `[policy]` section to `.drift/config.toml` and re-approve the configuration:

```toml
drift = "0.2"
kind = "config"
area = "catalog-service"

[policy]
pack = "core@1"
approvers = ["alice", "bob"]
proof = "verified"
```

With `pack = "core@1"`:
1. Only owners listed in `approvers` can seal contracts (`DR-E603` otherwise).
2. Every case must reach at least `verified` (`bound` is no longer enough).
3. Setting `proof = "killed"` requires every synthetic `then` mutant generated by `drift mutants` to be killed by the bound tests:

```bash
drift mutants .drift/contracts --out .drift-work/mutants.json
DRIFT_MUTANTS=.drift-work/mutants.json DRIFT_MUTATION_EVENTS=.drift-work/mutation-events node --test
drift gate .drift/contracts --events .drift/events \
  --mutants .drift-work/mutants.json --mutation-events .drift-work/mutation-events \
  --attest target/drift/attestation.json --as junit > target/drift/junit.xml
```

---

## Editor Autocompletion (VS Code & JetBrains)

DRIFT ships JSON Schemas for contracts, profiles, and `.drift/config.toml` (installed in `~/.local/share/drift/schemas/` on Linux/macOS and `%LOCALAPPDATA%\Programs\drift\schemas\` on Windows, or `schemas/` in this repository).

Add the following to `.vscode/settings.json` (with the **Even Better TOML** / Taplo extension installed):

```json
{
  "evenBetterToml.schema.associations": {
    ".*\\.drift/contracts/.*\\.toml$": "./schemas/drift-contract-0.2.schema.json",
    ".*\\.drift/profiles/.*\\.toml$": "./schemas/drift-profile-0.2.schema.json",
    ".*\\.drift/config\\.toml$": "./schemas/drift-config-0.2.schema.json"
  }
}
```

---

## Common Diagnostic Codes Cheat Sheet

Run `drift explain <CODE>` at any time for full details.

| Code | Name | Meaning & How to Fix |
|---|---|---|
| `DR-E004` | `toml.comment` | `#` comments are forbidden in DRIFT TOML files. Move prose into `intent`, `ask`, `note`, `why`, or `because`. |
| `DR-E102` | `contract.id_mismatch` | The `id = "..."` field inside the file must match the filename stem (`<id>.toml`). |
| `DR-E201` | `profile.missing` | The profile named in `[use].profile` was not found in `.drift/profiles/`. |
| `DR-E203` | `vocab.unknown_when` / `then` | A case uses a predicate not declared in the profile's `[vocabulary]` or `[use.vocabulary]`. |
| `DR-E601` | `approval.stale` | The contract or config was edited after approval. Review with `drift review --brief` and run `drift approve --by <owner>`. |
| `DR-E602` | `approval.blocked` | The contract still has `indirect = "unknown"`, a `"todo"` value, or an unresolved `[open.<id>]` question. |
| `DR-E603` | `approval.unauthorized` | The approver in `[approval].by` is not listed in `.drift/config.toml` `[policy].approvers`. |

