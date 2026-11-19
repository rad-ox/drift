# Adopt DRIFT on an Existing Repository (Shadow Mode & Brownfield)

> **Tier:** Free (Shadow Mode, 2-phase JUnit XML adapter, `--unshadow`) · Pro (`[policy].uncovered`, `[runners.<id>]`, incremental selection)

You can evaluate and adopt DRIFT on any existing, legacy, or third-party repository **without committing a single `.drift/` file** into its Git history.

---

## 1. Zero-Footprint Shadow Mode (`--state-dir`)

Shadow Mode stores `.drift/` configuration, profiles, contracts, baselines, and proof events outside the target repository (`--state-dir` or `DRIFT_STATE_DIR`). The target checkout—and even its `.git` directory—can be mounted **read-only** (`GIT_OPTIONAL_LOCKS=0`):

```bash
# 1. Initialize an external shadow area pointing at an untouched repository
drift init alice /path/to/repo --state-dir ~/.drift-shadows/my-service
drift approve ~/.drift-shadows/my-service/.drift/config.toml --by alice

# 2. Add a profile and scaffold your first slice contract inside the shadow area
mkdir -p ~/.drift-shadows/my-service/.drift/profiles
cp ~/.local/share/drift/example/.drift/profiles/http-json@1.toml ~/.drift-shadows/my-service/.drift/profiles/
drift new ~/.drift-shadows/my-service/.drift/contracts/item-get.toml --profile http-json@1 --intent "Return one catalog item by id."

# 3. Check status from inside the target repo (auto-discovered via ~/.config/drift/shadows.toml)
drift status /path/to/repo
```

- Contract digests remain portable via `<state-dir>/shadow.toml` (`drift.shadow-area/1`), so promoting the area in-tree later preserves your approval seals.
- Content-addressed baselines live in `<state-dir>/.drift-work/baselines/`.
- External state is kept out of the target repo, while your test runner itself may still write its usual build/test output inside the checkout unless configured otherwise.

---

## 2. Credit Existing JUnit XML Suites (Two-Phase Provenance)

Before wiring a runtime bridge into every test, credit existing JUnit XML test runs using the MIT-licensed two-phase adapter (`verifier/drift_shadow_junit.py`):

```bash
# Capture pre-run tree snapshot
python3 verifier/drift_shadow_junit.py begin --state-dir ~/.drift-shadows/my-service --run-id run-01

# Run your existing test suite unmodified
mvn -f /path/to/repo/pom.xml test
cp /path/to/repo/target/surefire-reports/*.xml ~/.drift-shadows/my-service/.drift-work/runs/run-01/reports/

# Verify post-run snapshot and emit proof shards
python3 verifier/drift_shadow_junit.py finish --state-dir ~/.drift-shadows/my-service --run-id run-01

# Evaluate the gate
drift gate ~/.drift-shadows/my-service/.drift/contracts --events ~/.drift-shadows/my-service/.drift-work/events
```

**Epistemic cap:** XML-credited runs reach at most **`bound`** (they prove mapped tests executed and passed against the snapshot, not that assertions read every `then.*` field). If your `[policy]` sets `proof = "verified"`, wire a language bridge (see **[Bridges](../bridges.md)**) to promote cases to `verified`.

---

## 3. Graduate In-Tree When Ready (`--unshadow`)

Once the team is ready to commit `.drift/` into the repository, promote the shadow area while preserving existing approval digests:

```bash
drift init --unshadow /path/to/repo --state-dir ~/.drift-shadows/my-service
```

---

## 4. Incremental Brownfield Coverage (`Pro`)

When adopting DRIFT slice-by-slice in a large repository where most files are not yet governed by contracts:

- Declare explicit uncovered brownfield globs under `[policy]` in `.drift/config.toml` (`uncovered = ["legacy/**"]`) so `drift select` distinguishes intentional uncovered paths (`uncovered_paths`) from accidental unowned code.
- Configure explicit test runner profiles (`[runners.<id>]` with `widen_argv` or exact Rust test selectors) so `drift select --plan` and `drift select --cmd` emit ready-to-run narrowed or widened commands cleanly.
- See **[Incremental Selection & Wave Orchestration](../workflows/incremental-and-waves.md)** and **[Legacy Carve-Outs & Cutover](../workflows/legacy-cutover.md)** for full workflows.
