# DRIFT Epistemic Guarantees, Threat Model & Proof Protocol

> **Falsifiable Promise:** DRIFT prevents unapproved changes to declared software behaviour from passing the release gate, and distinguishes what was **executed (`bound`)**, **checked against contract expectations (`verified`)**, and **proven against synthetic mutations (`killed`)**.

This document defines the exact boundaries of what DRIFT guarantees, what it detects vs. blocks, how to verify proofs independently without trusting the proprietary CLI binary, and how the 5 adversarial regression scenarios are tested in CI.

---

## 1. Guarantee & Threat Matrix

DRIFT is designed for **epistemic honesty**: it never claims that a green gate proves absence of bugs outside declared contracts.

| Scenario / Threat | Detected by DRIFT Free? | Gate Verdict | Required Condition / Control Boundary |
|---|:---:|:---:|---|
| **1. Unapproved edit to `when` / `then` / `scope.writes`** | **Yes (`DR-E601`)** | **Blocked (`contract.unapproved`)** | Always active; any semantic change alters the `dr1:sha256` digest and invalidates `[approval]`. |
| **2. Stale test replay after contract change** | **Yes** | **Blocked (`proof.not_green`)** | Events carrying an older `dr1:` digest are counted as `ignored`, leaving the updated case `missing`. |
| **3. Deleted or unexecuted test (`gone`)** | **Yes** | **Blocked (`proof.not_green`)** | Active when the test bridge writes the `.meta.json` discovery inventory sidecar alongside `.jsonl` events. |
| **4. Test passes without checking all `then.*` fields (or forbidden `writes` frame)** | **Yes** | **`bound` only (or `AssertionError` in `d.check` / `checkFrame`)** | Direct observation matching `d.check(case, { key: actual })`, `[invariants]` postconditions, and `checkFrame` / `checks.frame` on `scope.writes \ cases.<id>.writes` fail immediately on mismatch or forbidden writes, and keep unobserved frame cases (including `{ "observed": false }` collector reports) at `bound` (never `verified`). |
| **5. Callback ignores expected value (`() => {}` / `lambda v: None`)** | **Yes** | **Blocked (`AssertionError`)** | Prefer declarative observation matching `d.check(case, { key: actual })`. Legacy callbacks are checked for no-op bodies and `false` returns; full assertion discrimination is proven by `proof = "killed"` (`drift mutants`, **Enterprise**). |
| **6. Forged `[approval].by` or unreviewed `scope.code` change** | **Requires VCS / Policy** | **Blocked in PR / Enterprise** | In **Free**, protect `.drift/**` with GitHub `CODEOWNERS` + signed commits (`git commit -S`). In **Enterprise**, `[policy] approvers` (`DR-E603`) + deterministic RFC 8785 attestations (`drift gate --attest`, unsigned by default unless paired with optional OpenSSH signature verification and a verifier-pinned `--trust-root`) enforce this in the gate. |
| **7. Test feeds contract's own stub into `checkProjection`, uses unverified/stale `.drift/seam-stub/` fixtures, or never calls real code** | **Yes (`oracle.self_stubbed`, `oracle.unverified_seam`, `oracle.stale_seam_stub`)** | **Surfaced in `review` / `gate --explain`; blocked by `proof = "killed"` / `prove.seam_mutants`** | Bridges record self-contract `buildOutput` / `buildStub` calls and `.drift/seam-stub/` producer provenance in `.meta.json` (isolated from `test_inputs`), probe 2-skeleton neighbor extremes via `checkSeamBounds`, and inject incoming-seam faults via `prove.seam_mutants` (**Enterprise**). |
| **8. Missing or violated performance (`[budgets.<id>]`), security (`[requires].security`), regulated (`[risks]`/`[controls]`, `*.study.json`, `*.evaluation.json`), simulation (`drift.sim-receipt/1`), formal (`[formal.<id>]`), parity/migration (`*.parity.json` / `*.migration.json`), or federated composition (`*.composition.json`, `drift.composition-manifest/1`) evidence** | **Yes** | **Blocked (`performance.*`, `security.*`, `control.*`, `simulation.*`, `formal.*`, `parity.*`, `migration.*`, `federation.*`)** | Both `drift gate` and `verifier/drift_verify.py` fail closed when required `--measurements`, `*.security.json` (`--security-lock`), `*.study.json` / `*.evaluation.json` (and detached `.sig.json` signatures), `drift.sim-receipt/1`, `*.formal.json` / `*.model.json` (`tlc`, `cbmc`, `alloy`, `spin`, Kani, `gappa`, `stochastic_experiment`, QCEC `equivalence`), `*.parity.json` (`drift.parity-receipt/1`), `*.migration.json` (`drift.migration-receipt/1`), or `*.composition.json` (`drift.composition-manifest/1`) receipts are missing, stale, partial, or violated (`violated` takes precedence over truncation/conflicts). |

---

## 2. Independent Open-Source Proof Verifier (`verifier/drift_verify.py`)

You do **not** need to trust the precompiled `drift` CLI binary to verify a contract's `dr1:` / `dr2:` seal or a `drift gate` verdict.

This repository includes **[`verifier/drift_verify.py`](verifier/drift_verify.py)** (100% Python 3.11+ standard library, **MIT License**), an independent reference implementation of the DRIFT proof protocol that:

1. Parses `.drift/config.toml`, `.drift/profiles/*.toml`, and `.drift/contracts/*.toml` across schema `0.2` and `0.3` (including `[concepts]`, `[invariants]`, `[assurance.guards]`, `[risks]`/`[controls]`, case `writes` frames, `[cutover]`, `[budgets.<id>]`, `[requires].security`, `[formal.<id>]`, and external Shadow Mode areas via `--state-dir` / `DRIFT_STATE_DIR`).
2. Recomputes the canonical RFC 8785 `dr1:sha256:<hex>` or domain-separated 256-bit `dr2b`/`dr2a`/`dr2r`/`dr2x` digests (including `evidence_protocols` discriminants) and verifies `[approval].ref` (`DR-E601`), `[policy].approvers` (`DR-E603`), `policy.max_open`, and optional OpenSSH / detached `.sig.json` multi-party signatures (`--trust-root`, `--verify-time`).
3. Validates every `.jsonl` proof event against [`schemas/drift-proof-event-0.2.schema.json`](schemas/drift-proof-event-0.2.schema.json) and [`schemas/drift-proof-event-0.3.schema.json`](schemas/drift-proof-event-0.3.schema.json) (plus `drift.observation/1` lossless `ObsValue` records and `drift.bridge-session/1` supervisor sessions), reconciles active tests against `.meta.json` inventory sidecars (`gone`, `superseded`, `ignored`, `self_stubbed`, `.drift/seam-stub/` provenance, and `verifier/drift_shadow_junit.py` `drift.shadow-run/1` two-phase XML runs), and evaluates UI sequence observations (`drift.ui-observation/1`), `--measurements` bundles, `*.security.json` (`--security-lock`), `*.study.json` / `*.evaluation.json`, `drift.sim-receipt/1`, `*.parity.json` / `*.migration.json` cutover receipts, `*.formal.json` / `*.model.json` formal receipts, and `drift.composition-manifest/1` federated composition bundles.
4. Computes the deterministic state (`missing`, `red`, `bound`, `verified`, `killed`) for every `(case, level)` requirement and exits `0` if and only if the gate is green:

```bash
python3 verifier/drift_verify.py example/.drift/contracts \
  --config example/.drift/config.toml \
  --events /tmp/drift-ci/events \
  --json
```

In our public CI ([`.github/workflows/verify.yml`](.github/workflows/verify.yml)), every positive and adversarial scenario is checked by **both** `drift gate` and `python3 verifier/drift_verify.py`, asserting identical verdicts.

---

## 3. Normative Proof Protocol (`dr1:` & `.jsonl` v0.2)

### 3.1 Canonical Digest (`dr1:sha256:<64-hex>`, RFC 8785 JCS)

All digests follow **RFC 8785 (JSON Canonicalization Scheme)**:
- **UTF-16 Code Unit Key Ordering**: Object keys are sorted by their UTF-16-BE code unit sequence (`key.encode("utf-16-be")`), which matches RFC 8785 §3.2.3 even for supplementary Unicode characters above `U+FFFF`.
- **ECMAScript `Number::toString` Formatting**: Integers must lie within `±(2^53 - 1)`; floats use shortest round-trip decimal digits with `-0.0` rendered as `0`, fixed notation for `-6 < n <= 21`, and exponential notation otherwise (`NaN` and `Infinity` are rejected).
- **String Escaping**: Mandatory escapes `\"`, `\\`, `\b`, `\f`, `\n`, `\r`, `\t`, `\u00xx` for other control bytes `< 0x20`, and literal UTF-8 otherwise.

1. **Configuration (`.drift/config.toml`)**:
   - Remove the `approval` table, serialize as RFC 8785 Canonical JSON, and hash with SHA-256: `digest = "dr1:sha256:" + hex`, `ref = "dr1:" + hex[:12]`.
2. **Contract (`.drift/contracts/<id>.toml`)**:
   - `contract`: copy of the parsed contract map with `approval` and top-level/case `note` removed, `scope.code` / `scope.max_lines` / `scope.forbid_imports` removed, and decision/open `owner` fields removed.
   - `profiles`: `{ "<profile_id>": trimmed_profile }`, where `vocabulary.when` and `vocabulary.then` contain only the predicates used by the contract's `cases` (in profile declaration order).
   - Serialize `{"contract": contract, "profiles": profiles}` as RFC 8785 Canonical JSON and hash with SHA-256.

### 3.2 Proof Event Line (`<shard>.jsonl`) & Inventory Sidecar (`<shard>.meta.json`)

Each test execution appends one UTF-8 JSON line to `<shard>.jsonl` (schema: [`schemas/drift-proof-event-0.2.schema.json`](schemas/drift-proof-event-0.2.schema.json)):

```json
{"test":"ci.mjs#found","contract":"item-get","cases":["found","bad-id"],"level":"http","outcome":"passed","read":["found","bad-id"],"digest":"dr1:sha256:5153b5fae73c95f18e67bc30fa4390400dc2a99817ef2219f2304da683b2194f"}
```

Alongside `<shard>.jsonl`, the bridge writes the discovery sidecar **`<shard>.meta.json`** (`{"version": 1, "classes": ["ci.mjs"], "tests": ["ci.mjs#found"]}`):

- **Strict Schema Validation (`DR-E701`)**: Both the CLI and `verifier/drift_verify.py` reject duplicate JSON keys, unknown properties outside `["test", "contract", "cases", "level", "outcome", "read", "digest"]`, empty `cases`, `read` entries not present in `cases`, and invalid `dr1:` digests.
- **Version matching**: An event counts only if `event.digest` matches the contract's current `digest` or 12-hex `ref`. Older events are counted as `ignored`.
- **Rerun replacement (`superseded`)**: Within an event stream, a later event for the same `(contract, digest, test)` supersedes earlier events for that test.
- **Inventory reconciliation (`<shard>.meta.json`)**: When `<shard>.meta.json` is absent or an event's `test` / class is absent from `tests` / `classes`, the event is discarded and counted in `gone`.
- **Requirement state (`(case, level)`)**:
  - `missing`: 0 counted events cover `(case, level)`.
  - `red`: at least 1 counted event has `outcome != "passed"`.
  - `verified`: all counted events passed, and at least 1 counted event includes `case` in `event.read` (meaning the bridge verified every key in `cases.<case>.then`).
  - `bound`: all counted events passed, but none includes `case` in `event.read`.

### 3.3 Inventory Sidecar Constraints (`<shard>.meta.json`) & Execution Provenance

Every `<shard>.meta.json` sidecar is validated against the `$defs.inventorySidecar` schema in [`schemas/drift-proof-event-0.2.schema.json`](schemas/drift-proof-event-0.2.schema.json):

- `version`: must be the integer `1` or `2` (booleans and strings rejected; `2` binds `execution_ref` under `drift.execution-context/1`).
- `classes`: sorted, unique array of non-empty class/file names (no `#`, whitespace, `/`, `\`, `[`, `]`).
- `tests`: sorted, unique array of `<class>#<method>` identifiers where `<class>` is present in `classes`.
- `snapshot` *(optional)*: 40-char (SHA-1) or 64-char (SHA-256) lowercase hex Git tree/commit OID. When `snapshot` is set and `tests` is non-empty, an empty `<shard>.jsonl` is flagged as `shard.incomplete`.
- `pack_ref` *(optional)*: `dr1:<12-hex>` schedule pack reference.
- `execution_ref` *(optional, v2)*: `sha256:<64-hex>` complete execution-context identity.
- `touched` *(optional)*: sorted, unique array of normalized relative paths (no leading `/`, no `\`, no `.` or `..` segments). Represents the **declared execution perimeter** (`DRIFT_TOUCHED` / worker-pack fencing), not statement or symbol call-coverage (which requires an external coverage runner).
- `inputs` *(optional)*: map from `<test>` (must be in `tests`) to `{ "<relative_path>": "<digest>" }`.
- `env` *(optional)*: object with the exact 7 required non-empty string keys `["toolchain", "deps", "config", "runner", "drift", "adapter", "policy"]`.

**Proof Coherence vs. Trusted Execution Provenance:** A standalone verifier (`drift_verify.py` or `drift gate`) proves that the supplied `.jsonl` events and `.meta.json` sidecars are schema-valid, match the approved `dr1:` contract digest, and cover every required `(case, level)`. Because `.jsonl` files and default `drift gate --attest` RFC 8785 bundles are plain JSON text (not cryptographically signed unless paired with optional OpenSSH `ssh-keygen -Y sign/verify` and a verifier-pinned `--trust-root`), proving that those events were genuinely produced by executing the test suite on a specific commit requires running the test suite and verifier inside a trusted CI runner or verifying an externally signed attestation against a verifier-pinned trust root.

---

## 4. Reproducible Conformance & Adversarial Suite (Tested Across Linux, macOS & Windows CI)

The public CI workflow ([`.github/workflows/verify.yml`](.github/workflows/verify.yml)) runs across **Linux (`x86_64`)**, **macOS (`arm64`)**, and **Windows (`x86_64`)**, executing `python3 verifier/drift_verify.py --self-test` (35+ conformance vectors covering RFC 8785, event schema, and all `.meta.json` fields), compiling and running the **JVM Maven/JUnit 5 bridge (`bridges/jvm/drift-junit`)** and **`example/pom.xml` (`ItemGetTest` over live HTTP)**, running **24-way parallel concurrency stress tests** (`AsyncLocalStorage` in JS, `ContextVar` + `RLock` in Python, `ThreadLocal` in JVM), plus 6 end-to-end adversarial scenarios:

1. **Scenario A — Incomplete Observation Check**: A test omits `then.name` when checking `cases.found` → `d.check` throws `AssertionError: item-get.found: no check for then.name`.
2. **Scenario B — Application Regression (`200` → `500`)**: The service returns status `500` → declarative `d.check('found', { status: res.status, name: res.name })` throws `AssertionError: item-get.found: expected then.status=200, got 500`.
3. **Scenario C — Empty / No-Op Callback**: A test passes `status: (v) => {}` or `lambda v: None` → rejected with `AssertionError: ... must inspect the expected value`.
4. **Scenario D — Unapproved Contract Edit (`DR-E601`)**: An agent alters `then.status` in `item-get.toml` without owner approval → both `drift gate` and `verifier/drift_verify.py` exit `1` with `reasons: ["contract.findings", "contract.approval.stale", "proof.not_green"]`.
5. **Scenario E — Deleted Test (`gone`) in `<shard>.meta.json`**: A test listed in `js.jsonl` is removed from `js.meta.json` `classes` / `tests` → both `drift gate` and `verifier/drift_verify.py` exit `1` with `gone: 1` and `reasons: ["proof.not_green"]`.
6. **Scenario F — Malformed Event / Inventory Schema Violation (`DR-E701`)**: An unknown property or invalid `snapshot`/`env`/`inputs` entry is injected into `.jsonl` or `.meta.json` → both `drift gate` and `verifier/drift_verify.py` reject it (`events.invalid`).
