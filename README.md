<p align="center">
  <img src="assets/banner.svg" alt="DRIFT — Specification-Driven Proof Gate" width="100%" />
</p>

<p align="center">
  <strong>Behaviour contracts in compact TOML · Cryptographic owner approval · Proof states that never call a skipped test green</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="#why-drift">Why DRIFT?</a> ·
  <a href="#how-it-works">How It Works</a> ·
  <a href="#polyglot-test-bridges">Test Bridges</a> ·
  <a href="#ai-coding-agents">AI Agents</a> ·
  <a href="#editions">Editions</a> ·
  <a href="GUIDE.md">Guide (EN)</a> ·
  <a href="GUIDE.it.md">Guida (IT)</a> ·
  <a href="INSTALL.md">Install (EN)</a> ·
  <a href="INSTALL.it.md">Installa (IT)</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

---

## Why DRIFT?

When AI coding agents—or fast-moving engineering teams—write both the implementation and the test in the same pass, **tests silently drift to validate what the code does rather than what the owner intended**:

- An agent weakens an assertion to make a failing build pass.
- A refactored test skips checking a required field, or gets deleted without notice.
- Markdown specs go stale the moment the first pull request lands.

**DRIFT** closes that gap with a single static binary and zero runtime dependencies:

| Guarantee | How DRIFT enforces it |
|---|---|
| **Explicit Slice Intent** | Every behaviour slice lives in `.drift/contracts/<id>.toml` with typed `when`/`then` predicates, blast-radius `[scope]`, and explicit `[decisions]` trade-off cards. |
| **Human Owner Seal (`dr1:<hash>`)** | Only the owner approves a contract (`drift approve --by <owner>`). Editing any `when`, `then`, `writes`, or decision immediately turns approval **stale** (`DR-E601`). |
| **Honest Runtime Proof** | Tests bind to cases (`@DriftCase`, `runDriftCase`, `run_drift_case`), read expected values directly from the contract, and emit `.jsonl` proof events tied to the exact contract digest. |
| **Deterministic Gate** | `drift gate` is **green** only when configuration and contracts are approved and every case has a passing current-version proof from tests that still exist. |

### Caught in the Act: Traditional Test Runner vs. DRIFT Gate

Suppose an AI coding agent breaks the `name` field in `GET /items/1` and "fixes" the failing test by dropping the `name` assertion (or editing the expected value in the spec):

| What the AI Agent Does | Standard `node --test` / `pytest` / `mvn test` | `drift gate` & `verifier/drift_verify.py` |
|---|---|---|
| **1. Drops `assert.equal(body.name, 'lamp')` so the broken handler passes** | **PASS (False Green)** — `res.status === 200` passes; runner exits `0`. | **FAIL (`AssertionError` / `proof.not_green`)** — `d.check('found', { status: res.status })` throws `no check for then.name`; even if bypassed via raw `d.expect`, the case stays `bound` and fails the `proof = "verified"` policy floor. |
| **2. Passes a dummy callback `name: (expected) => { const x = expected; }`** | **PASS (False Green)** — callback does not throw; runner exits `0`. | **FAIL (`AssertionError`)** — `invokeVerifiedCallback` rejects callbacks that neither assert nor return `true`. |
| **3. Calls `d.buildOutput('found')` without asserting runtime output** | **PASS (False Green)** — test constructs a synthetic object and exits `0`. | **FAIL (`proof.not_green`)** — `buildOutput` never records `then.*` reads (`fullyReadCases() == []`), leaving the case `bound`. |
| **4. Quietly edits `then.status = 500` in `item-get.toml` to match broken code** | **PASS (False Green)** — test reads `500` and passes. | **FAIL (`DR-E601 contract.approval.stale`)** — `dr1:sha256` digest changes; both `drift gate` and `drift_verify.py` reject the unapproved contract. |
| **5. Deletes the failing test method while keeping old `.jsonl` logs** | **PASS (False Green)** — remaining tests pass. | **FAIL (`gone: 1`, `proof.not_green`)** — `<shard>.meta.json` discovery sidecar reconciles active tests and discards orphaned events. |

---

## How It Works

<p align="center">
  <img src="assets/workflow.svg" alt="DRIFT Four-Stage Verification Loop" width="100%" />
</p>

### 1. Write a Slice Contract (`.drift/contracts/item-get.toml`)

```toml
drift = "0.2"
id = "item-get"
intent = "Return a single catalog item by identifier or 404 when absent."

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
then.body = { id = "1", name = "lamp" }

[cases.not-found]
at = ["http"]
when.request = "GET /items/99"
then.status = 404
then.error = "not_found"
```

### 2. Check, Review & Seal with Owner Approval

```bash
drift fmt .drift/contracts/item-get.toml            # Canonical TOML layout
drift check .drift                                  # Every static rule in one pass
drift review .drift/contracts/item-get.toml --brief # Compact owner review packet
drift approve .drift/contracts/item-get.toml --by alice
```

### 3. Run Bound Tests & Verify the Gate

```bash
drift prove .drift/contracts --events target/drift/events.jsonl
drift gate .drift/contracts --events target/drift/events.jsonl
```

```text
item-get dr1:5922b40e14d7: green; 2 verified
gate: green (1/1 contracts)
```

Every case progresses through strict proof states:
- **`missing`** — No current-version test event exists yet (never green).
- **`red`** — A bound test failed or threw an error (never green).
- **`bound`** — The test passed against the current contract digest without reading every `then` value.
- **`verified`** — The test passed **and** read every `then` value from the contract through `Drift.expect` / `d.check` (rejecting missing keys, `false` returns, and empty no-op callbacks).
- **`killed`** *(Enterprise)* — Every synthetic `then` value mutant was killed by the test suite, proving assertion discrimination beyond value reads.

---

## Quick Start

### Install in 10 Seconds

Download the archive for your platform from **[GitHub Releases](https://github.com/rad-ox/drift/releases/latest)** (100% offline install, verified via `SHA256SUMS`) or run `./install.sh` from a clone (which automatically downloads and SHA-256-verifies the matching release binary for Linux `x86_64` or macOS `arm64`/`x86_64`):

```bash
# Linux (x86_64) or macOS (Apple Silicon arm64 / Intel x86_64)
./install.sh

# Windows 10 / 11 (from the extracted drift-*-windows-x64.zip release archive)
.\install.cmd
```

See **[INSTALL.md](INSTALL.md)** ([Italiano](INSTALL.it.md)) for package verification (`SHA256SUMS`), custom prefixes, and IDE setup.

### Explore the Included Sample Area

```bash
drift version
drift check ~/.local/share/drift/example/.drift
drift review ~/.local/share/drift/example/.drift --brief
drift show ~/.local/share/drift/example/.drift/contracts/item-get.toml --as json
drift explain DR-E601
```

### Bootstrap a New Project Area

```bash
drift init my-service .
drift approve .drift/config.toml --by alice
drift new .drift/contracts/health-check.toml --profile http-json@1 --intent "Report service readiness."
```

---

## Polyglot Test Bridges

DRIFT ships with first-class, zero-lock-in bridges for **Java / Scala / JVM**, **JavaScript / TypeScript**, and **Python 3**. Expected values live once—in the `.toml` contract—and tests read them at runtime.

### Java, Scala & Maven (`drift-junit` + `drift-maven-plugin`)

With the Maven plugin configured in `pom.xml`, `mvn verify` automatically exports contracts, runs JUnit 5 tests, records proof shards, and enforces the gate:

```java
import drift.Drift;
import drift.DriftCase;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

class ItemHttpTest {
    @Test
    @DriftCase(contract = "item-get", cases = "found", level = "http")
    void returnsExistingItem() throws Exception {
        Drift.Case c = Drift.expect("item-get", "found");
        var response = send(c.whenString("request"));
        assertEquals(c.thenInt("status"), response.statusCode());
        assertEquals(c.thenMap("body").get("name"), response.json().get("name"));
    }
}
```

In closure-based JVM suites (such as **Scala 3 / MUnit** `FunSuite`), call `Drift.expect(contract, caseId, level)` directly inside the test body and verify tuples, maps, records, or Scala products with `verify(...)`:

```scala
test("returns existing item") {
  val c = Drift.expect("item-get", "found", "http")
  val res = send(c.whenString("request"))
  c.verify("status", res.status, "name", res.name)
}
```

### JavaScript & TypeScript (`bridges/drift.mjs`)

Zero-dependency ES module compatible with `node --test`, **Vitest**, and **Jest**. Pass observed values directly to `d.check`—the bridge verifies every `then.*` key and relational constraint without arbitrary user callbacks:

```js
import { test } from 'node:test';
import { runDriftCase } from './drift.mjs';

test('GET /items/1 returns existing item', async (t) => {
  await runDriftCase({ contract: 'item-get', t, cases: ['found'], level: 'http' }, async (d) => {
    const res = await send(d.when('found', 'request'));
    await d.check('found', {
      status: res.status,
      body:   res.body,
    });
  });
});
```

### Python 3 (`bridges/drift.py`)

Zero-dependency module compatible with **pytest** and `unittest`:

```python
import drift

def test_returns_existing_item():
    def verify(d):
        res = send(d.when("found", "request"))
        d.check("found", {
            "status": res.status,
            "body":   res.json(),
        })

    drift.run_drift_case(
        contract="item-get",
        test="test_items.py#test_returns_existing_item",
        cases=["found"],
        level="http",
        fn=verify,
    )
```

---

## AI Coding Agents

DRIFT is designed from the ground up for **Agentic Specification-Driven Development (SDD)** across **GitHub Copilot CLI**, **Claude Code**, **OpenAI Codex CLI**, **Cursor**, **Gemini CLI**, and **Pi**.

1. **Agent Skill (`skill/drift/SKILL.md`)**: Installed automatically into `~/.copilot/skills/drift/` (and `~/.agents/skills/drift/`). When you ask your agent *"Add `POST /items` with DRIFT"*, the agent:
   - Checks `.drift/config.toml` (Adoption Gate).
   - Drafts `.drift/contracts/item-create.toml` and validates it with `drift fmt` + `drift check`.
   - Presents `drift review --brief` (cases, decision cards, and at most 5 open questions) and **waits for your approval** before writing implementation code.
2. **Automatic Guardrail Hooks (`./install.sh --hooks`)**:
   - **`SessionStart`**: Injects live contract status into the agent's context window.
   - **`Stop`**: Prevents the agent from concluding a turn if `.drift` has static check errors (`DR-E*`) or if source code was modified without a covering contract.

---

## CLI Command Reference

Exit codes are uniform across every command: **`0`** = OK / Gate Green, **`1`** = Findings / Differences / Gate Not Green, **`2`** = Usage or I/O Error.

| Command | Tier | Purpose |
|---|---|---|
| `drift init <owner> [dir]` | **Free** | Initialize a new `.drift/config.toml` area configuration |
| `drift new <file> [--profile REF]` | **Free** *(+Pro)* | Scaffold a new contract or profile (`--openapi`, `--from-recall` in **Pro**) |
| `drift case add <file> [<id>] --ask TEXT` | **Free** *(+Pro)* | Append a draft case or question (`--from-intent` in **Pro**) |
| `drift fmt <file\|dir>... [--check]` | **Free** | Format TOML contracts and configs into canonical order (`--sync-vocab`) |
| `drift check [<file\|dir>...]` | **Free** | Validate syntax, schema, profile vocabulary, budgets, security, and approval hashes |
| `drift diff <a> <b> [--json]` | **Free** | Compute structural and semantic differences between two contracts |
| `drift review [<file\|dir>...] [--brief]` | **Free** *(+Pro)* | Render an owner review brief (`--base`, `--delta`, `--measurements`, `--as md` in **Pro**) |
| `drift approve <file\|dir>... --by OWNER` | **Free** | Seal approved contract or config versions with `dr1:<hash>` |
| `drift show [<file\|dir>...] [--as json]` | **Free** *(+Pro)* | Export resolved contract views for test bridges (`--boundary` in **Pro**) |
| `drift export views\|boundary --out PATH` | **Free / Pro** | Export resolved contract views (**Free**) or area boundary bundles (**Pro**) |
| `drift prove [<file\|dir>...] --events DIR` | **Free** *(+Pro/Ent)* | Evaluate runtime proof states, `--measurements` budgets, and `*.security.json` receipts |
| `drift gate [<file\|dir>...] --events DIR` | **Free** *(+Pro/Ent)* | Enforce the release gate across config, contracts, proof events, budgets, and security |
| `drift status [<file\|dir>...]` | **Free** | Summarize area approval and proof state at a glance |
| `drift explain <DR-Exxx>` | **Free** | Explain the cause and exact fix for any diagnostic code or reason token |
| `drift select [<base>] --events DIR` | **Pro** | Select only tests and performance budgets affected by changed files or coupled resources |
| `drift impact [<dir>]` | **Pro** | Blast-radius analysis, lexical search, and transitive dependency graph |
| `drift plan [<dir>] [--pack GROUP\|ready]` | **Pro** | Wave DAG scheduling, `what_if` cuts, and parallel worker bundles |
| `drift recall query\|sync [<dir>]` | **Pro** | Symbolic `@recall` context capsules and dual-ring maintenance |
| `drift merge <base> <ours> <theirs>` | **Pro** | Three-way semantic merge for concurrent contract branches |
| `drift mutants [<dir>] --out FILE` | **Enterprise** | Generate in-process contract mutants (`--budget` with `[policy].priority_weights`) |
| `drift sweep [check\|sync-scope\|simplify\|promote]` | **Pro / Ent** | Area ownership audit (`check`, `sync-scope`, `--root` in **Pro**; `--flow`, `simplify`, `promote` in **Ent**) |
| `drift stats [<dir>] [--compare ...]` | **Enterprise** | Area footprint, risk radar, and multi-version evaluation ranking |

---

## Editions

DRIFT follows a clean **3-tier progressive architecture**. Each higher edition is a self-contained superset binary and Agent Skill:

| Capability | **DRIFT Free** (`drift`) | **DRIFT Pro** (`drift-pro`) | **DRIFT Enterprise** (`drift-enterprise`) |
|---|:---:|:---:|:---:|
| TOML Contracts, Profiles, Decision Cards, `[budgets.<id>]` & `[requires].security` | ✅ | ✅ | ✅ |
| Static Check (`check`), Canonical Formatter (`fmt`) & Diff (`diff`) | ✅ | ✅ | ✅ |
| Owner Review (`review --brief`) & Cryptographic Seal (`approve`) | ✅ | ✅ | ✅ |
| Resolved Views (`show`, `export views`), Proof Engine (`prove`) & Release Gate (`gate`) | ✅ | ✅ | ✅ |
| JUnit 5, Maven Plugin, Node.js (`drift.mjs`), Python (`drift.py`), V (`drift_v.v`) & Rust (`drift_rs`) Bridges | ✅ | ✅ | ✅ |
| Local Performance (`--measurements`) & Security Receipt (`*.security.json`) Verification | ✅ | ✅ | ✅ |
| Editor JSON Schemas (`schemas/*.schema.json`) & Guardrail Hooks | ✅ | ✅ | ✅ |
| Change-Based Test & Budget Selection (`drift select`) & Proof Reuse (`gate --base --changed`) | — | ✅ | ✅ |
| Blast-Radius (`impact`), Wave Scheduling (`plan`) & `@recall` Capsules (`recall`) | — | ✅ | ✅ |
| 3-Way Semantic Contract Merge (`drift merge`) & Baseline/Measurement Reviews (`review --base`, `--measurements`) | — | ✅ | ✅ |
| OpenAPI, Boundary & Recall Scaffolding (`new --openapi`, `new --from-recall`, `export boundary`) | — | ✅ | ✅ |
| Contract Mutation Testing (`drift mutants`, `proof = "killed"`, `[policy].priority_weights`) | — | — | ✅ |
| Cryptographic Gate Attestations (`gate --attest`) & JUnit CI XML (`gate --as junit`) | — | — | ✅ |
| Fleet Dataflow, Budget & Security Boundary Audits (`sweep --flow --simplify --promote`) | — | — | ✅ |
| Multi-Version Benchmarking & Radar Analytics (`drift stats`) | — | — | ✅ |

See **[EDITIONS.md](EDITIONS.md)** for full details on tier capabilities, sibling binary delegation, and `DRIFT_EDITION` environment pinning.

---

## Documentation & Repository Map

| Document / Path | Description |
|---|---|
| **[GUIDE.md](GUIDE.md)** · **[GUIDE.it.md](GUIDE.it.md)** | Step-by-step practical guide from first contract (L0) to mutation-backed policies (L3), in English and Italian |
| **[INSTALL.md](INSTALL.md)** · **[INSTALL.it.md](INSTALL.it.md)** | Installation, verification, Maven/Node/Python bridge wiring, and troubleshooting for Linux, macOS, and Windows |
| **[EDITIONS.md](EDITIONS.md)** | Complete comparison of **Free**, **Pro**, and **Enterprise** commands, flags, skills, and hooks |
| **[GUARANTEES.md](GUARANTEES.md)** | Epistemic guarantee & threat matrix, normative `dr1:` / `.jsonl` proof protocol, and adversarial CI scenarios |
| **[CHANGELOG.md](CHANGELOG.md)** | Concise release notes and user-visible capabilities by version |
| **`verifier/drift_verify.py`** | Independent, open-source (**MIT**) reference proof verifier in pure Python 3.11+ stdlib (`tomllib` + `hashlib`) |
| **`skill/drift/`** | Agent Skill (`SKILL.md` + `references/`) for GitHub Copilot CLI, Claude Code, Codex, Cursor, and Pi |
| **`bridges/`** | Zero-dependency test bridges for JavaScript/TypeScript (`drift.mjs`) and Python 3 (`drift.py`) |
| **`maven/`** | Offline-ready `drift-junit` bridge and `drift-maven-plugin` artifacts for JVM projects |
| **`schemas/`** | JSON Schemas (`drift-contract-0.2`, `drift-profile-0.2`, `drift-config-0.2`, `drift-proof-event-0.2`) for validation |
| **`hooks/`** | `SessionStart` and `Stop` guardrail hooks (`drift-hook.sh`, `drift-hook.ps1`) |
| **`example/.drift/`** | Ready-to-run reference area with `config.toml`, `http-json@1` profile, and approved contracts |
| **[LICENSE](LICENSE)** | Dual-surface license: **MIT License** for bridges, verifier, skill, schemas, hooks, and examples; **DRIFT Free Edition License** for the CLI binary |

---

## Trust Model, Authentication & Epistemic Boundaries

DRIFT reports what is verified and never overclaims what a static or runtime check can prove (see **[GUARANTEES.md](GUARANTEES.md)** for the full threat matrix and normative proof protocol):

1. **Content Seal (`[approval]`) vs. Identity Authentication**:
   - `drift approve --by <owner>` computes a canonical SHA-256 digest (`dr1:<hash>`) over the contract's normative behaviour (`when`, `then`, `scope.writes`, `scope.reads`, `scope.indirect`, and resolved profile vocabulary). Any subsequent behavioural edit immediately invalidates the seal (`DR-E601`).
   - Because `[approval].by` is a plain string inside the repository, **authentication of who approved a change** belongs to your version-control control plane: enforce **Git signed commits (`git commit -S`)** and **GitHub `CODEOWNERS` + branch protection** on `.drift/**`. In **DRIFT Enterprise**, combine `[policy] approvers` (`DR-E603`) with **Ed25519 cryptographic gate attestations** (`drift gate --attest` using `DRIFT_ATTEST_KEY`).
2. **`scope.code` Governance**:
   - `scope.code` and `owners` are intentionally excluded from the behavioural `dr1:` digest so internal file renames or refactors do not force re-approval of unchanged external behaviour. Protect `.drift/contracts/*.toml` via GitHub `CODEOWNERS` so any change to `scope.code` is reviewed on pull requests.
3. **Proof Floor (`bound` → `verified` → `killed`)**:
   - `bound` proves a tagged test executed and passed against the current contract digest.
   - `verified` proves the test checked every `then.*` key against the contract (directly via declarative `d.check(case, { key: actualValue })` or via checked callbacks that cannot be empty or return `false`).
   - `killed` *(Enterprise)* proves that the test suite's assertions actively reject synthetic mutations of `then.*` values (`drift mutants`).
4. **Independent Verification (`verifier/drift_verify.py`) & Open Integration Surface**:
   - You never have to take the `drift` binary's verdict on faith: **[`verifier/drift_verify.py`](verifier/drift_verify.py)** (MIT-licensed, 100% Python stdlib) independently recomputes `dr1:` digests and evaluates `.jsonl` proof events + `.meta.json` inventories without invoking the CLI binary.
   - The `drift` CLI engine is distributed via **[GitHub Releases](https://github.com/rad-ox/drift/releases)** for Linux (`x86_64`), macOS (`arm64`, `x86_64`), and Windows (`x86_64`), accompanied by `SHA256SUMS` and verified continuously by **[`.github/workflows/verify.yml`](.github/workflows/verify.yml)**.


