# DRIFT Epistemic Guarantees, Threat Model & Proof Protocol

> **Falsifiable Promise:** DRIFT prevents unapproved changes to declared software behaviour from passing the release gate, and distinguishes what was **executed (`bound`)**, **checked against contract expectations (`verified`)**, and **proven against synthetic mutations (`killed`)**.

This document describes the boundaries of what DRIFT guarantees, what it detects vs. blocks, how to verify proofs independently without trusting the proprietary CLI binary, and how the 9 adversarial regression scenarios (covering all 8 threat classes in §1) are tested in CI. All contracts, profiles, and area configurations use **schema `0.3`** (legacy `0.2` files are rejected with `DR-E002`).

---

## 1. Guarantee & Threat Matrix

DRIFT is designed for **epistemic honesty**: it never claims that a green gate proves absence of bugs outside declared contracts.

| Scenario / Threat | Detected by DRIFT Free? | Gate Verdict | Required Condition / Control Boundary |
|---|:---:|:---:|---|
| **1. Unapproved edit to `when` / `then` / `scope.writes`** | **Yes (`DR-E601`)** | **Blocked** | Always active; a behavioural change alters the `dr2b:sha256` digest and makes `[approval].behavior_ref` stale (`[approval].ref` `dr1:` on `.drift/config.toml`). Assurance edits independently stale `assurance_ref`. |
| **2. Stale test replay after contract change** | **Yes** | **Blocked (`proof.not_green`)** | Events carrying an older behavioural digest are counted as `ignored`, leaving the updated case `missing`. |
| **3. Deleted or unexecuted test (`gone`)** | **Yes** | **Blocked (`proof.not_green`)** | Active when the test bridge writes the `.meta.json` discovery inventory sidecar alongside `.jsonl` events. |
| **4. Test passes without checking all `then.*` fields (or forbidden `writes` frame)** | **Yes** | **`bound` only (or `AssertionError` in `d.check` / `checkFrame`)** | Direct observation matching `d.check(case, { key: actual })`, `[invariants]` postconditions, and `checkFrame` / `checks.frame` on `scope.writes \ cases.<id>.writes` fail immediately on mismatch or forbidden writes, and keep unobserved frame cases (including `{ "observed": false }` collector reports) at `bound` (never `verified`). |
| **5. Callback ignores expected value (`() => {}` / `lambda v: None`)** | **Yes** | **Blocked (`AssertionError`)** | Prefer declarative observation matching `d.check(case, { key: actual })`. Legacy callbacks are checked for no-op bodies and `false` returns; full assertion discrimination is proven by `proof = "killed"` (`drift mutants`, **Enterprise**). |
| **6. Forged `[approval].by` or unreviewed `bind.code` change** | **Requires VCS / Policy** | **Requires authenticated review / signatures** | Protect `.drift/**` with GitHub `CODEOWNERS` + signed commits (`git commit -S`). An approver allowlist constrains names, not identity. Enterprise gate attestations are unsigned by default; authenticate them with OpenSSH signatures and a verifier-pinned `--trust-root`. |
| **7. Test feeds contract's own stub into `checkProjection`, uses unverified/stale `.drift/seam-stub/` fixtures, or never calls real code** | **Yes (`oracle.self_stubbed`, `oracle.unverified_seam`, `oracle.stale_seam_stub`)** | **Surfaced in `review` / `gate --explain`; blocked by `proof = "killed"` / `prove.seam_mutants`** | Bridges record self-contract `buildOutput` / `buildStub` calls and `.drift/seam-stub/` producer provenance in `.meta.json` (isolated from `test_inputs`), probe 2-skeleton neighbor extremes via `checkSeamBounds`, and inject incoming-seam faults via `prove.seam_mutants` (**Enterprise**). |
| **8. Missing or violated performance (`[budgets.<id>]`, `[requires].budgets`), security (`[requires].security`), regulated (`[risks]`/`[controls]`, `*.study.json`, `*.evaluation.json`), simulation (`drift.sim-receipt/1`), formal (`[formal.<id>]`), parity/migration (`*.parity.json` / `*.migration.json`), or federated composition (`*.composition.json`, `drift.composition-manifest/1`) evidence** | **Yes** | **Blocked (`performance.*`, `security.*`, `control.*`, `sim.*`, `formal.*`, `parity.*`, `migration.*`, `federation.*`)** | Both `drift gate` and `verifier/drift_verify.py` fail closed when required `--measurements` (including `alloc_bytes_total` / `alloc_count_total`), `*.security.json` (`--security-lock`), `*.study.json` / `*.evaluation.json` (and detached `.sig.json` signatures), `drift.sim-receipt/1`, `*.formal.json` / `*.model.json` (`tlc`, `cbmc`, `alloy`, `spin`, Kani, `gappa`, `stochastic_experiment`, QCEC `equivalence`), `*.parity.json` (`drift.parity-receipt/1`), `*.migration.json` (`drift.migration-receipt/1`), or `*.composition.json` (`drift.composition-manifest/1`) receipts are missing, stale, partial, or violated (`violated` takes precedence over truncation/conflicts). |

---

## 2. Independent Open-Source Proof Verifier (`verifier/drift_verify.py`)

You do **not** need to trust the precompiled `drift` CLI binary to verify a contract's `dr2:` seals (or config `dr1:` seal) or a `drift gate` verdict.

This repository includes **[`verifier/drift_verify.py`](verifier/drift_verify.py)** (100% Python 3.11+ standard library, **MIT License**), an independent reference implementation of the DRIFT proof protocol that:

1. Parses `.drift/config.toml`, `.drift/profiles/*.toml`, and `.drift/contracts/*.toml` on schema `0.3` (including `[concepts]`, `[invariants]`, `[assurance.guards]` with `forbid_touched`, `[risks]`/`[controls]`, case `writes` frames, `[cutover]`, `[budgets.<id>]`, `[requires].security`, `[requires].budgets`, `[formal.<id>]`, and external Shadow Mode areas via `--state-dir` / `DRIFT_STATE_DIR`).
2. Recomputes domain-separated 256-bit `dr2b`/`dr2a`/`dr2r`/`dr2x`/`dr2g`/`dr2p` digests and verifies `[approval].behavior_ref` / `assurance_ref` (`DR-E601`), `[policy].approvers` (`DR-E603`), `policy.max_open`, clean-room `drift.grant-lock/1` (`--grant-lock`), bilateral `drift.pact-lock/1` (`--pact-lock`, directional `0.3` cell coverage, and `pact.producer`/`pact.consumer` quorum), and optional OpenSSH / detached `.sig.json` multi-party signatures (`--trust-root`, `--verify-time`).
3. Validates every `.jsonl` proof event against [`schemas/drift-proof-event-0.3.schema.json`](schemas/drift-proof-event-0.3.schema.json) (plus `drift.observation/1` lossless `ObsValue` records and `drift.bridge-session/1` supervisor sessions), reconciles active tests against `.meta.json` inventory sidecars (`gone`, `superseded`, `ignored`, `self_stubbed`, `.drift/seam-stub/` provenance, and `verifier/drift_shadow_junit.py` `drift.shadow-run/1` two-phase XML runs), and evaluates UI sequence observations (`drift.ui-observation/1`), `--measurements` bundles, `*.security.json` (`--security-lock`), `*.study.json` / `*.evaluation.json`, `drift.sim-receipt/1`, `*.parity.json` / `*.migration.json` cutover receipts, `*.formal.json` / `*.model.json` formal receipts, and `drift.composition-manifest/1` federated composition bundles.
4. Computes the deterministic state (`missing`, `red`, `bound`, `verified`, `killed`) for every `(case, level)` requirement and exits `0` if and only if the gate is green:

```bash
python3 verifier/drift_verify.py example/.drift/contracts \
  --config example/.drift/config.toml \
  --events /tmp/drift-ci/events \
  --json
```

In our public CI ([`.github/workflows/verify.yml`](.github/workflows/verify.yml)), every positive and adversarial scenario is checked by **both** `drift gate` and `python3 verifier/drift_verify.py`, asserting identical verdicts.

---

## 3. Proof Protocol (`0.3` Dual Seals)

### 3.1 Domain-Separated Identities & Canonical JSON

Schema `0.3` uses domain-separated SHA-256 identities:

| Identity | Domain | What It Binds |
|---|---|---|
| `dr2b` | `drift.behavior/2` | Normalized behaviour and its used profile/schema closure, excluding `[assurance]` and `[bind]` |
| `dr2a` | `drift.assurance/2` | Merged requirements, guards, budgets, formal obligations, cutover, risks, and controls |
| `dr2r` | `drift.requirement/2` | An individual obligation, its target cases' behaviour, and linked obligations |
| `dr2x` | `drift.execution/2` | A case's normalized constraints, invariants, write frame, schema/units, selected inputs, and environment |
| `dr2g` | `drift.grant-lock/2` | Clean-room `drift.grant-lock/1` contract behavior digests, posture floors, obligations, and source pins |
| `dr2o` / `dr2p` | `drift.pact-offer/2` / `drift.pact-lock/2` | Blind `drift.pact-offer/1` seam offers and sealed bilateral `drift.pact-lock/1` clause envelopes, operational bounds, and decoupled seam obligations |

`[approval]` records **`behavior_ref = "dr2b:<12-hex>"`** and **`assurance_ref = "dr2a:<12-hex>"`**, plus `by` and `at`; full `dr2b:sha256:<64-hex>` / `dr2a:sha256:<64-hex>` values are also accepted. JSON views expose full `digest` and `assurance_digest`. Behaviour and assurance can become stale independently; both approvals must be current for the gate. Compact references are not collision-resistant authentication and do not prove the identity in `by`.

The exact canonical payload construction is implemented by the open [`verifier/drift_verify_03.py`](verifier/drift_verify_03.py).

All digests follow **RFC 8785 (JSON Canonicalization Scheme)**:
- **UTF-16 Code Unit Key Ordering**: Object keys are sorted by their UTF-16-BE code unit sequence (`key.encode("utf-16-be")`), which matches RFC 8785 §3.2.3 even for supplementary Unicode characters above `U+FFFF`.
- **ECMAScript `Number::toString` Formatting**: Integers must lie within `±(2^53 - 1)`; floats use shortest round-trip decimal digits with `-0.0` rendered as `0`, fixed notation for `-6 < n <= 21`, and exponential notation otherwise (`NaN` and `Infinity` are rejected).
- **String Escaping**: Mandatory escapes `\"`, `\\`, `\b`, `\f`, `\n`, `\r`, `\t`, `\u00xx` for other control bytes `< 0x20`, and literal UTF-8 otherwise.

**Area Configuration Seal (`dr1` on `.drift/config.toml`):**

- Remove the `approval` table from `.drift/config.toml` (`drift = "0.3"`, `kind = "config"`), serialize as RFC 8785 Canonical JSON, and hash with SHA-256: `digest = "dr1:sha256:" + hex`, `ref = "dr1:" + hex[:12]`.

### 3.2 Proof Event Line (`<shard>.jsonl`) & Inventory Sidecar (`<shard>.meta.json`)

Each test execution appends one UTF-8 JSON line to `<shard>.jsonl` (schema: [`schemas/drift-proof-event-0.3.schema.json`](schemas/drift-proof-event-0.3.schema.json)). A simple scalar-only contract with no required capabilities can emit:

```json
{"test":"ci.mjs#found","contract":"item-get","cases":["found"],"level":"http","outcome":"passed","read":["found"],"digest":"dr2b:sha256:5153b5fae73c95f18e67bc30fa4390400dc2a99817ef2219f2304da683b2194f","schema":"0.3","capabilities":[]}
```

The digest is illustrative; bridges must use the current resolved behaviour digest, not copy this value. `schema = "0.3"` and capability coverage prevent older bridges from silently ignoring newer constraints.

Alongside `<shard>.jsonl`, the bridge writes the discovery sidecar **`<shard>.meta.json`** (`{"version": 1, "classes": ["ci.mjs"], "tests": ["ci.mjs#found"]}`):

- **Strict Schema Validation (`DR-E701`)**: Both the CLI and `verifier/drift_verify.py` reject duplicate JSON keys, unknown event properties, empty `cases`, `read` entries not present in `cases`, and invalid digests. Events carry `schema = "0.3"` and `capabilities` covering the resolved view's `required_capabilities`.
- **Version matching**: An event counts only if `event.digest` matches the contract's current `digest` or 12-hex `ref`. Older events are counted as `ignored`.
- **Rerun replacement (`superseded`)**: Within an event stream, a later event for the same `(contract, digest, test)` supersedes earlier events for that test.
- **Inventory reconciliation (`<shard>.meta.json`)**: When `<shard>.meta.json` is absent or an event's `test` / class is absent from `tests` / `classes`, the event is discarded and counted in `gone`.
- **Requirement state (`(case, level)`)**:
  - `missing`: 0 counted events cover `(case, level)`.
  - `red`: at least 1 counted event has `outcome != "passed"`.
  - `verified`: all counted events passed, and at least 1 counted event includes `case` in `event.read` (meaning the bridge verified every key in `cases.<case>.then`).
  - `bound`: all counted events passed, but none includes `case` in `event.read`.

### 3.3 Inventory Sidecar Constraints (`<shard>.meta.json`) & Execution Provenance

Every `<shard>.meta.json` sidecar is validated against `$defs.inventorySidecar` in the [`0.3` proof schema](schemas/drift-proof-event-0.3.schema.json):

- `version`: must be the integer `1` or `2` (booleans and strings rejected; `2` binds `execution_ref` under `drift.execution-context/1`).
- `classes`: sorted, unique array of non-empty class/file names (no `#`, whitespace, `/`, `\`, `[`, `]`).
- `tests`: sorted, unique array of `<class>#<method>` identifiers where `<class>` is present in `classes`.
- `snapshot` *(optional)*: 40-char (SHA-1) or 64-char (SHA-256) lowercase hex Git tree/commit OID. When `snapshot` is set and `tests` is non-empty, an empty `<shard>.jsonl` is flagged as `shard.incomplete`.
- `pack_ref` *(optional)*: `dr2b:<12-hex>` schedule pack reference.
- `execution_ref` *(optional, v2)*: `sha256:<64-hex>` complete execution-context identity.
- `touched` *(optional)*: sorted, unique array of normalized relative paths or `<path>#<symbol>` anchors (no leading `/`, no `\`, no `.` or `..` segments). Represents the **declared execution perimeter** (`DRIFT_TOUCHED` / worker-pack fencing and `[assurance.guards].forbid_touched` checks).
- `inputs` *(optional)*: map from `<test>` (must be in `tests`) to `{ "<relative_path>": "<digest>" }`.
- `env` *(optional)*: object with the exact 7 required non-empty string keys `["toolchain", "deps", "config", "runner", "drift", "adapter", "policy"]`.

**Proof Coherence vs. Trusted Execution Provenance:** A standalone verifier (`drift_verify.py` or `drift gate`) proves that the supplied `.jsonl` events and `.meta.json` sidecars are schema-valid, match the approved behavioural digest (`dr2b`), and cover every required `(case, level)`; the gate also checks current assurance approval and required evidence. Because `.jsonl` files and default `drift gate --attest` RFC 8785 bundles are plain JSON text (not cryptographically signed unless paired with optional OpenSSH `ssh-keygen -Y sign/verify` and a verifier-pinned `--trust-root`), proving that those events were genuinely produced by executing the test suite on a specific commit requires running the test suite and verifier inside a trusted CI runner or verifying an externally signed attestation against a verifier-pinned trust root. Likewise, on clean-room specification handoffs (`drift export grant` / `drift.grant-lock/1`), in-tree `[policy].grant_lock` guards an honest Grantee against unapproved agent edits, while adversarial Grantor acceptance evaluates `<delivered>/.drift/contracts` in Grantor CI with an external `--grant-lock <grantor.lock.json>` (and optional `--trust-root`) rather than trusting Grantee lock files or self-reported events.

---

## 4. Reproducible Conformance & Adversarial Suite (Tested Across Linux, macOS & Windows CI)

The public CI workflow ([`.github/workflows/verify.yml`](.github/workflows/verify.yml)) runs across **Linux (`x86_64`)**, **macOS (`arm64`)**, and **Windows (`x86_64`)**, executing `python3 verifier/drift_verify.py --self-test` (35+ conformance vectors covering RFC 8785, event schema, and all `.meta.json` fields), compiling and running the **JVM Maven/JUnit 5 bridge (`bridges/jvm/drift-junit`)** and **`example/pom.xml` (`ItemGetTest` over live HTTP)**, running **24-way parallel concurrency stress tests** (`AsyncLocalStorage` in JS, `ContextVar` + `RLock` in Python, `ThreadLocal` in JVM), plus 9 end-to-end adversarial scenarios covering all 8 threat classes in §1 against the packaged `0.3` example area:

1. **Scenario A — Incomplete Observation Check (Threat 4)**: A test omits `then.name` when checking `cases.found` → `d.check` throws `AssertionError: item-get.found: no check for then.name`.
2. **Scenario B — Application Regression (`200` → `500`, Threat 4)**: The service returns status `500` → declarative `d.check('found', { status: res.status, name: res.name })` throws `AssertionError: item-get.found: expected then.status=200, got 500`.
3. **Scenario C — Empty / No-Op Callback (Threat 5)**: A test passes `status: (v) => {}` or `lambda v: None` → rejected with `AssertionError: ... must inspect the expected value`.
4. **Scenario D — Unapproved Contract Edit (`DR-E601`, Threat 1 & Threat 2)**: An agent alters `then.status` in `item-get.toml` without owner approval → both `drift gate` and `verifier/drift_verify.py` exit `1` with `reasons: ["contract.findings", "contract.approval.stale", "proof.not_green"]`.
5. **Scenario E — Deleted Test (`gone`) in `<shard>.meta.json` (Threat 3)**: A test listed in `js.jsonl` is removed from `js.meta.json` `classes` / `tests` → both `drift gate` and `verifier/drift_verify.py` exit `1` with `gone: 1` and `reasons: ["proof.not_green"]`.
6. **Scenario F — Malformed Event / Inventory Schema Violation (`DR-E701`, Threat 3)**: An unknown property or invalid `snapshot`/`env`/`inputs` entry is injected into `.jsonl` or `.meta.json` → both `drift gate` and `verifier/drift_verify.py` reject it (`events.invalid`).
7. **Scenario G — Forged / Unlisted Approver (`DR-E603`, Threat 6)**: An unauthorized identity (`by = "forged-actor"`) is injected into `[approval]` under an active `[policy] approvers` allowlist → both `drift gate` and `verifier/drift_verify.py` exit `1` with `contract.approval.unlisted`.
8. **Scenario H — Self-Stubbed Test Oracle (`oracle.self_stubbed`, Threat 7)**: A test feeds `d.buildOutput('found')` back into `d.check` without calling real application code → the bridge records `self_stubbed` in `.meta.json` and `drift review --events` / `drift gate --explain` surfaces `oracle.self_stubbed`.
9. **Scenario I — Missing or Violated Assurance Receipts (`security.*` / `performance.*`, Threat 8)**: A contract requiring `[requires] security = ["sast"]` or `[budgets.<id>]` is evaluated without a valid receipt or with a violated receipt → both `drift gate` and `verifier/drift_verify.py` fail closed (`security.missing`, `security.violated`, `performance.missing`).
