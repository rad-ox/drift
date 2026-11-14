# DRIFT Editions: Free, Pro & Enterprise

<p align="center">
  <img src="assets/logo.svg" alt="DRIFT Logo" width="120" />
</p>

DRIFT is packaged into three progressive editions—**Free**, **Pro**, and **Enterprise**—across Linux (`x86_64`), macOS (`arm64` Apple Silicon and `x86_64` Intel), and Windows (`x86_64`).

Every edition is a **self-contained standalone package**: installing **Pro** or **Enterprise** gives you the complete CLI, the full progressive-superset Agent Skill (`skill/drift/SKILL.md` + `references/`), all language bridges (`drift-junit` for Java & Scala/MUnit, `drift-maven-plugin`, `drift.mjs`, `drift.py`, `bridges/v/drift_v`, `bridges/rust` / `drift_rust`, `Drift.php`, `drift_cobol.py`, `drift_cpp.hpp`, `Drift.cs`, `drift.gd`, and `bridges/legacy/junit4/DriftJUnit4.java`), editor JSON Schemas, and agent hooks in one step.

The [guide](GUIDE.md) uses **contract/profile/config schema `0.3`**: code bindings live in `[bind]`, obligations in `[assurance]`, and owner approval has independent `dr2b:` / `dr2a:` seals (`keys.allow` / `keys.forbid`, `eq` + `tol`, and `peer.balance`).

---

## 1. Philosophy of the Three Tiers

| Edition | Target Audience | Core Value |
|---|---|---|
| **DRIFT Free** (`drift`) | Individual developers, open-source maintainers, and teams adopting Specification-Driven Development | • **Lifecycle & Shadow Mode**: Draft, format (`--sync-vocab` with domain-separated `dr2b:`/`dr2a:` digests), check, diff, review, approve (`--reviewed`, `--ssh-sign`), export views, and adopt zero-footprint via `--state-dir` / `--unshadow` (`verifier/drift_shadow_junit.py`).<br>• **11 Polyglot Bridges**: Bind Java/Scala/JUnit 4/Node/Python/Rust/V/C++/C#/GDScript/PHP/COBOL tests (`drift.observation/1` lossless observations & kernel COBOL copybook decode, `drift.bridge-session/1` supervisor sessions, recursive `keys.allow`/`keys.forbid`, `not_in`, `eq` + `tol.abs`/`tol.rel`, `peer.balance`, `checkFrame`, `checkLogSink`, `checkAdverse`).<br>• **Assurance & Gate**: Verify `[invariants]`, `[assurance.guards]`, `[assurance.risks]`/`[assurance.controls]` (`*.study.json`, `*.evaluation.json`, detached `.sig.json`), `[assurance.budgets.<id>]` (`--measurements`), `*.security.json`, `drift.sim-receipt/1`, and `[assurance.formal.<id>]` (`*.formal.json` / `*.model.json`) receipts at the release gate. |
| **DRIFT Pro** (`drift-pro`) | Fast-moving engineering teams and multi-agent workflows | • **Incremental Selection & Reuse**: Change-based test & budget selection (`select --plan`, `--cmd`) and bounded proof/performance/security reuse (`gate --base`, `--security-lock`).<br>• **Graph, Waves & `@recall`**: Blast-radius (`impact`), wave DAG scheduling (`plan`), `@recall` context capsules (`recall`), and 3-way semantic contract merge (`merge`).<br>• **Scaffolding & Baseline Review**: OpenAPI 3.2/AsyncAPI/WSDL/copybook/runtime-trace scaffolding (`new --openapi`, `--asyncapi`, `--wsdl`, `--copybook`, `--from-upstream`) and baseline delta, rename pairing & leading-indicator reviews (`review --base`, `review --measurements`). |
| **DRIFT Enterprise** (`drift-enterprise`) | Regulated, mission-critical, and large-scale multi-service organizations *(plus public open-source maintainers via complimentary grant)* | • **Mutation Proofs**: Contract and seam mutation testing with configurable `[policy].priority_weights` (`mutants`, `proof = "killed"`).<br>• **Signed Attestations & CI Reports**: Cryptographic gate attestations with performance, security, regulated & OpenSSH signature bundles (`gate --attest`, `--ssh-sign`, `--trust-root`) plus JUnit XML CI reports (`gate --as junit`).<br>• **Fleet Audits & Analytics**: Fleet dataflow, `L0–L3` causal execution coupling, FSM/Saga, AsyncAPI epoch, budget & security boundary audits (`sweep --flow --simplify --promote`) and multi-version analytics (`stats --churn-list`). |

> **DRIFT for Open Source (Complimentary Enterprise Grant):** Owners and maintainers of public OSI-licensed open-source repositories can request a free **DRIFT Enterprise** license for their open-source projects by emailing `rad-ox@users.noreply.github.com` with the repository URL (see Part III, Section 2 of [`LICENSE`](LICENSE)).

---

## 2. Complete Command & Option Matrix

### Standalone CLI Commands

| Command | Free | Pro | Enterprise | Description |
|---|:---:|:---:|:---:|---|
| `drift init` | ✅ | ✅ | ✅ | Initialize an area configuration (`.drift/config.toml`, external shadow state via `--state-dir` / `--unshadow`, promote shadow state via `--graduate`, adopt a clean-room grant via `--grant <dir>`, or onboard a bilateral pact via `--pact <lock.json>`) |
| `drift new` | ✅ | ✅ | ✅ | Scaffold a new contract or profile |
| `drift case` | ✅ | ✅ | ✅ | Append draft cases to an existing contract (`case add`; `--from-intent` and `--unbound-vocab` in **Pro**) |
| `drift check` | ✅ | ✅ | ✅ | Static validation of schema `0.3` contracts, profiles, `[concepts]`, `[invariants]`, `[assurance.guards]` (`forbid_touched`), `[assurance.risks]`/`[assurance.controls]`, `[assurance.cutover]`, `[assurance.budgets.<id>]`, `[requires].security`, `[requires].budgets`, `[assurance.formal.<id>]`, UI surfaces, and `.drift/config.toml` |
| `drift status` | ✅ | ✅ | ✅ | Compact summary of area approval and proof states (`--detail summary\|guided`) |
| `drift show` | ✅ | ✅ | ✅ | Export resolved contract JSON views (`--as json`, `--out`; `--boundary` in **Pro**) |
| `drift export` | ✅ | ✅ | ✅ | Export contract views (`export views` in **Free**; `export boundary` and `export grant` in **Pro**) |
| `drift fmt` | ✅ | ✅ | ✅ | Canonical TOML formatter (`--check`, `--diff`, `--sync-vocab`) |
| `drift diff` | ✅ | ✅ | ✅ | Structural and semantic diff between two contracts |
| `drift approve` | ✅ | ✅ | ✅ | Owner approval seal (`--by OWNER`, `--pin-sources`, `--reviewed --expect-review`, `--ssh-sign`) |
| `drift eval` | ✅ | ✅ | ✅ | Judge `drift.observation/1` envelopes (one object, or JSONL from a file or `-`) against one case, `<id>#<case>`, with the kernel oracle; read-only, exit 0 / 1 / 2, emits no proof event |
| `drift explain` | ✅ | ✅ | ✅ | Detailed cause and remediation for any `DR-E*` code, reason token, sweep check, or external envelope (`--list [codes\|reasons\|checks\|operators\|envelopes]`, `--example`) |
| `drift doctor` | ✅ | ✅ | ✅ | Read-only diagnosis of the area: edition, config approval, approvers, profiles, contracts, resolved events, `DRIFT_*` variable names, merge driver and operational log |
| `drift completion` | ✅ | ✅ | ✅ | Print a shell completion script (`bash`, `zsh`, `fish`, `pwsh`) generated from the option registry of the edition |
| `drift version` | ✅ | ✅ | ✅ | Print CLI version, schema version, digest algorithm, and build ID (`--json` adds editions and capabilities) |
| `drift select` | — | ✅ | ✅ | Change-based test and performance-budget selection (`--plan`, `--cmd`) across JVM (Java/Scala), JS, Python, V, Rust, C++, C#, GDScript, PHP, COBOL, and Pug/Sass/CSS graphs |
| `drift impact` | — | ✅ | ✅ | Blast radius, lexical query, and transitive dependency graph |
| `drift plan` | — | ✅ | ✅ | Wave DAG scheduling, `what_if` cuts, `--pack <group\|ready\|all\|speculative>` worker bundles, and `--staffing <file>` agent-pool & `verify_slots` sizing (`schedule.staffing`) |
| `drift recall` | — | ✅ | ✅ | Symbolic context capsules (`recall query`) and ring maintenance (`recall sync`) across code and `#<Type>.<method>` / `#<mixin>` anchors |
| `drift pact` | — | ✅ | ✅ | Bilateral contractual equalizer across peer areas (`pact offer`, `pact equalize`, `pact seal`, `pact ack` over blind `drift.pact-offer/1` and `drift.pact-lock/1` seam envelopes) |
| `drift merge` | — | ✅ | ✅ | Three-way structural and semantic TOML contract merge (`--out FILE\|-` previews or redirects the result) |
| `drift mutants` | — | — | ✅ | Generate synthetic contract mutants (`--out`, `--when`, `--budget` with `[policy].priority_weights`, `--detail summary`) |
| `drift stats` | — | — | ✅ | Area footprint, risk radar, `--churn-list` and `--since` carve-out hotspots, `--detail summary`, and multi-version benchmark comparison |

### Hybrid Commands (Tiered by Subcommand or Option)

Several core commands belong to **DRIFT Free** in their standard usage and unlock advanced subcommands or flags in **Pro** and **Enterprise**:

| Command | Free Usage | Pro Subcommands / Options | Enterprise Subcommands / Options |
|---|---|---|---|
| `drift case` | `drift case add <file> [<id>] --ask <text> [--blocks <phase>]` | `--from-intent`, `--unbound-vocab`, `--from-signal <file>`, `--deployment <file>` | *(all Pro options)* |
| `drift export` | `drift export views [<path>...] --out <dir>` | `drift export boundary [<path>...] --out <file> [--area ...] [--openapi ... \| --asyncapi ... \| --wsdl ... \| --copybook ...]`, `drift export grant [<path>...] --policy <file> [--out <dir> \| --dry-run] [--ssh-sign <key>] [--json]` | *(all Pro options)* |
| `drift review` | `drift review <path> [--brief] [--as json\|summary] [--detail full\|summary\|guided]` | `--base <ref>` (`contract_change = "renamed"`, `case.moved`, `budget-coarsened`, `security-coarsened`, `concept_changes`, `when.narrowed`/`when.shifted`, `writes.widened`, `allowed_keys`/`forbid_keys`/`not_in` `then.widened`, `refinement`, `relaxation_witnesses`), `--delta`, `--base-profiles`, `--events`, `--measurements` (`budget-at-risk` & `revisit_triggered`), `--subject*`, `--run-id`, `--upstream`, `--as md` | *(all Pro options)* |
| `drift new` | `drift new <file> [--profile REF] [--concept ID...] [--from <sibling>] [--code ...] [--intent ...]` | `--openapi <file>`, `--asyncapi <file>`, `--wsdl <file>`, `--copybook <file>`, `--from-upstream`, `--resource`, `--from-recall <id>`, `--from-intent` | *(all Pro options)* |
| `drift prove` | `drift prove <path> --events <dir> [--measurements <file> --subject* --run-id ...] [--at LEVEL...] [--explain] [--json]` | `--base <ref>`, `--changed`, `--changed-list`, `--changed-none`, `--security-lock` | `--mutants <file>`, `--mutation-events <dir>` |
| `drift gate` | `drift gate <path> --events <dir> [--grant-lock <file>] [--pact-lock <file>...] [--execution-context <file> [--base-snapshot ... --result-snapshot ...]] [--measurements <file> --subject* --run-id ...] [--at LEVEL...] [--phase ...] [--explain] [--as summary\|json] [--detail full\|summary\|guided]` | `--base <ref>` (including `performance_reuse = "execution"` and `--security-lock` receipt reuse), `--changed`, `--changed-list`, `--changed-none`, `--upstream` | `--mutants`, `--mutation-events`, `--attest <file>` (with `performance`, `security_checks`, `--attest-sig`, `--ssh-sign`, `--trust-root`, `--verify-time`, `--signatures`, `--signature-policy`), `--as junit`, `--compare-before` |
| `drift sweep` | — | `sweep check`, `sweep sync-scope [--apply]`, `--root <dir>`, `--base <ref>`, `--delta`, `recall sync` (ring upkeep), `--sync-scope` | `sweep simplify` (`contract.ephemeral_id`, `contract.compound_topic`, `scope.code_in_sources`), `sweep promote`, `--flow` (resource, `L0–L3` causal execution coupling, DB/CICS/ORM/game seam, boundary unit, budget, security, AsyncAPI epoch & `--pacts` fleet conservation checks), `--openapi`, `--asyncapi`, `--wsdl`, `--copybook`, `--epoch-manifest`, `--scaffold-profile`, `--promote`, `--simplify`, `--apply`, `--upstream`, `--pacts` |

---

## 3. Agent Skills & Lifecycle Hooks Across Tiers

| Component | DRIFT Free | DRIFT Pro | DRIFT Enterprise |
|---|---|---|---|
| **Skill Package** | `drift` (Free Core SDD workflow) | `drift-pro` (Complete superset + Cold Review, Wave Orchestration, Recall) | `drift-enterprise` (Complete superset + Area Analysis, Sweep Hygiene, Mutation Proofs) |
| **Bundled `references/`** | `adoption.md`, `integration-first.md`, `jvm-bridge.md`, `native-flow.md` | + `cold-review.md`, `schedule-orchestration.md` | + `area-analysis.md` (all 7 reference guides) |
| **`SessionStart` Hook** | Injects `drift status` into agent context | Injects `drift status` + active recall hints | Injects `drift status` + active recall hints |
| **`Stop` Hook** | Blocks turn on broken contracts (`drift check`) | Blocks on broken contracts **and** uncontracted source changes (`drift sweep --root`) | Blocks on broken contracts **and** uncontracted source changes (`drift sweep --root`) |

---

## 4. Transparent Sibling Delegation & `DRIFT_EDITION`

When `drift-pro` or `drift-enterprise` is installed in the same directory as `drift` (for example `~/.local/bin/`):

1. Invoking `drift <command>` executes **Free** commands directly in-process with zero overhead.
2. If you pass a **Pro** or **Enterprise** command or flag to `drift`, it automatically delegates execution to the sibling `drift-enterprise` or `drift-pro` binary when present.
3. If the required tier binary is not installed, `drift` exits with code **`2`** and prints a clear diagnostic naming the required edition:
   ```text
   drift: command "select" requires DRIFT Pro (install drift-pro)
   drift: option "--attest" on "gate" requires DRIFT Enterprise (install drift-enterprise)
   ```
4. **Simulating a Lower Tier**: Developers with Enterprise installed can test Free or Pro behaviour at any time by setting `DRIFT_EDITION`:
   ```bash
   DRIFT_EDITION=free drift select      # exits 2 (requires DRIFT Pro)
   DRIFT_EDITION=pro  drift mutants     # exits 2 (requires DRIFT Enterprise)
   ```

---

## 5. Feature Tiering Criteria (`Capability` Mapping)

Every new CLI command, subcommand, or option maps to one of the seven `Capability` classes in the CLI capability table:

| Edition | `Capability` Class | Assignment Criteria |
|---|---|---|
| **DRIFT Free** | `core_free` | Single-contract authoring, formatting, static validation, diffing, owner approval, and local runtime verification (`prove`, `gate`, `--measurements` performance bundles, `*.security.json` receipts, `verifier/drift_verify.py`, and all polyglot language bridges: JVM/Scala/JUnit 4, JS/TS, Python, Rust, V, C++20, C#/.NET, GDScript, PHP, COBOL). |
| **DRIFT Pro** | `incremental_baseline`<br>`graph_recall_plan`<br>`boundary_scaffold` | Git-baseline comparisons and proof/budget/security reuse (`--base`, `--delta`, `--changed*`, `review --events`/`--measurements`), dependency graphs and change-based selection (`select`, `impact`, `plan`, `recall`, `sweep check\|sync-scope`), 3-way contract merging (`merge`), and contract/case scaffolding or clean-room handoffs from OpenAPI, boundaries, recall capsules, or prose (`--openapi`, `--from-recall`, `--from-intent`, `export boundary`, `export grant`). |
| **DRIFT Enterprise** | `flow_refactor`<br>`mutation_attest`<br>`fleet_analytics` | Cross-contract dataflow, budget compatibility, and security boundary verification (`sweep --flow`), automated contract/profile simplification and vocabulary promotion (`sweep simplify\|promote`), contract mutation campaigns (`mutants`), cryptographic release attestations and CI JUnit XML (`gate --attest`, `gate --as junit`, `--compare-before`), and multi-version fleet telemetry (`stats`). |

