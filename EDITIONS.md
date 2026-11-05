# DRIFT Editions: Free, Pro & Enterprise

<p align="center">
  <img src="assets/logo.svg" alt="DRIFT Logo" width="120" />
</p>

DRIFT is packaged into three progressive editions—**Free**, **Pro**, and **Enterprise**—across Linux (`x86_64`), macOS (`arm64` Apple Silicon and `x86_64` Intel), and Windows (`x86_64`).

Every edition is a **self-contained standalone package**: installing **Pro** or **Enterprise** gives you the complete CLI, the full progressive-superset Agent Skill (`skill/drift/SKILL.md` + `references/`), all language bridges (`drift-junit`, `drift-maven-plugin`, `drift.mjs`, `drift.py`), editor JSON Schemas, and agent hooks in one step.

---

## 1. Philosophy of the Three Tiers

| Edition | Target Audience | Core Value |
|---|---|---|
| **DRIFT Free** (`drift`) | Individual developers, open-source maintainers, and teams adopting Specification-Driven Development | Complete contract lifecycle: draft, format, check, diff, review, approve, export views, bind JUnit/Node/Python tests, and enforce the release gate. |
| **DRIFT Pro** (`drift-pro`) | Fast-moving engineering teams and multi-agent workflows | Incremental velocity: change-based test selection (`select`), blast-radius & `@recall` context capsules (`impact`), 3-way semantic contract merge (`merge`), baseline delta reviews (`review --base`), and proof reuse (`gate --base`). |
| **DRIFT Enterprise** (`drift-enterprise`) | Regulated, mission-critical, and large-scale multi-service organizations | High-assurance governance: in-process contract mutation testing (`mutants`, `proof = "killed"`), cryptographic gate attestations (`gate --attest`), JUnit XML CI reports (`gate --as junit`), fleet dataflow & vocabulary hygiene (`sweep --flow --simplify --promote`), and multi-version analytics (`stats`). |

---

## 2. Complete Command & Option Matrix

### Standalone CLI Commands

| Command | Free | Pro | Enterprise | Description |
|---|:---:|:---:|:---:|---|
| `drift check` | ✅ | ✅ | ✅ | Static validation of contracts, profiles, and `.drift/config.toml` |
| `drift status` | ✅ | ✅ | ✅ | Compact summary of area approval and proof states |
| `drift show` | ✅ | ✅ | ✅ | Export resolved contract JSON views (`--as json`, `--out`, `--boundary`) |
| `drift fmt` | ✅ | ✅ | ✅ | Canonical TOML formatter (`--check`, `--sync-vocab`) |
| `drift diff` | ✅ | ✅ | ✅ | Structural and semantic diff between two contracts |
| `drift approve` | ✅ | ✅ | ✅ | Owner approval seal (`--by OWNER`, `--pin-sources`) |
| `drift explain` | ✅ | ✅ | ✅ | Detailed cause and remediation for any `DR-E*` diagnostic code |
| `drift version` | ✅ | ✅ | ✅ | Print CLI version, schema version, digest algorithm, and build ID |
| `drift select` | — | ✅ | ✅ | Change-based test selection across code and resource dependencies |
| `drift impact` | — | ✅ | ✅ | Blast radius, transitive dependency graph, wave `--schedule`, and `--recall` capsules |
| `drift merge` | — | ✅ | ✅ | Three-way structural and semantic TOML contract merge |
| `drift mutants` | — | — | ✅ | Generate synthetic contract mutants (`--out`, `--when`, `--budget`) |
| `drift stats` | — | — | ✅ | Area footprint, risk radar, and multi-version benchmark comparison |

### Hybrid Commands (Tiered by Option)

Several core commands belong to **DRIFT Free** in their standard usage and unlock advanced flags in **Pro** and **Enterprise**:

| Command | Free Usage | Pro Options | Enterprise Options |
|---|---|---|---|
| `drift review` | `drift review <path> --brief [--as json\|summary]` | `--base <ref>`, `--delta`, `--base-profiles`, `--events`, `--upstream`, `--as md` | *(all Pro options)* |
| `drift new` | `drift new <file> [--profile REF] [--from <sibling>] [--code ...] [--intent ...]` | `--openapi <file>`, `--from-upstream`, `--from-recall <id>`, `--from-intent` | *(all Pro options)* |
| `drift prove` | `drift prove <path> --events <dir> [--at LEVEL...] [--explain] [--json]` | `--base <ref>`, `--changed`, `--changed-list`, `--changed-none` | `--mutants <file>`, `--mutation-events <dir>` |
| `drift gate` | `drift gate <path> --events <dir> [--at LEVEL...] [--phase ...] [--explain] [--json]` | `--base <ref>`, `--changed`, `--changed-list`, `--changed-none`, `--upstream` | `--mutants`, `--mutation-events`, `--attest <file>`, `--as junit`, `--compare-before` |
| `drift sweep` | — | `drift sweep <path> --root <dir> [--openapi ...] [--sync-scope] [--recall]` | `--flow`, `--simplify`, `--promote`, `--apply` |

---

## 3. Agent Skills & Lifecycle Hooks Across Tiers

| Component | DRIFT Free | DRIFT Pro | DRIFT Enterprise |
|---|---|---|---|
| **Skill Package** | `drift` (Free Core SDD workflow) | `drift-pro` (Complete superset + Cold Review, Wave Orchestration, Recall) | `drift-enterprise` (Complete superset + Area Analysis, Sweep Hygiene, Mutation Proofs) |
| **Bundled `references/`** | `adoption.md`, `integration-first.md`, `jvm-bridge.md` | + `cold-review.md`, `schedule-orchestration.md` | + `area-analysis.md` (all 6 reference guides) |
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
