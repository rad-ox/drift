# Changelog

User-visible changes and capabilities by release.

## 0.5.1

- Release `0.5.1`.
- Harden `0.3` constraint algebra (unit-aware meet/refinement, `not_in`/UTF-8 codepoint lengths, `assurance_ref` simulation, `fmt --upgrade`, `mutants`, bridges, and small-model/ASan/fuzz checks).
- Fix `0.3` guard target globs, `ObsValue` `series`/`contains`, transitive `peer`/unit closures, exempt-case isolation, `extends`/invariant refinement, and upstream owner keys (DR-E105).
- Harden schema `0.3` across `stats`, `approve`, `review`, `sweep`, `merge`, `new`, `drift_verify.py`, and bridges (`dr2b`/`dr2a`, `bind.*`, `scenario`, `ConstraintExpr`).
- Add `.github/workflows/publish.yml` (crates.io OIDC & Maven Central `io.github.rad-ox`) and `make setup-github-env` for zero-local-secret GitHub Environment setup.
- Add the complimentary Open-Source Maintainer Grant for DRIFT Enterprise in `LICENSE` Part III, `EDITIONS.md`, `README.md`, and `SUPPORT.md`.
- Switch Maven `groupId` to `io.github.rad-ox` across POMs, installers (`install.sh`, `install.ps1`), skills, and docs for Maven Central readiness.
- Showcase standout Free → Pro → Enterprise capabilities in `README.md`/`GUIDE*.md`/`EDITIONS.md`, add `skills/drift/` export for `skills.sh`, and add POM/Cargo metadata.
- Add portable DRIFT dogfooding & perimeter release audit to `AGENTS.md`/`PUBLISHING.md`, sync `README.md`, `EDITIONS.md`, and `SECURITY.md`, and verify `0.3` schemas in CI.
- Add `type = "any"` polymorphic `0.3` predicates, `dr1`-preserving `0.3`->`0.2` profile projection, and migrate `.drift/profiles/*.toml` and initial contracts to `0.3`.
- Align `bridges/rust/Cargo.toml` license to `MIT`, add Part III Pro/Enterprise terms to `LICENSE`, and update `PUBLISHING.md` Maven Central `<licenses>` note.
- Add `0.3` JSON Schema projections (`drift-{contract, profile, config, proof-event}-0.3.schema.json`) in `SPEC.md` §26 and `schemas/` alongside `0.2`.
- Add GitHub issue forms (`.github/ISSUE_TEMPLATE/`) and `.github/PULL_REQUEST_TEMPLATE.md` and include them in public exports.
- Separate `0.3` `when.*`/`then.*` peer environments in bridges, fix `isStr` in `drift_ui_recovery.mjs`, and verify `0.3` `dr2b`/`dr2a` contracts in `drift_verify.py`.

## 0.5.0

- Release `0.5.0`.
- Add lossless `ObsValue` (`drift.observation/1`), kernel COBOL copybook decode, supervisor session reconciliation (`drift.bridge-session/1`), and `L0–L3` coupling.
- Add opt-in `drift stats --root --churn-list` (`--changed-root`, `--top`) with commit-delimited rename/deletion lineage, 4-state `scope.code` coverage, and co-change ranking.
- Add schema `0.3` typed IR, 256-bit `dr2` digests, `[assurance.guards]`, event handshake, and `fmt --upgrade 0.3` (no new DR-E codes).
- Add `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `SUPPORT.md`, include Pi/release-check installer assets in public exports, and deduplicate `bridges/`.
- Harden `resolved-gen` exports, Windows `DRIFT_TEST_CMD`, literal pre-checks, sticky `unobservedCases`, and overlap triage.
- Add `select --plan`/`--cmd` (`drift.test-plan/1`), wrapper `show` fail-fast/caching & `argv[]` parsing, static literal test pre-checks, and advisory `overlapping_tests`.
- Add `approx`/`abs_tol`/`rel_tol`, `balance_fields`, declared units in `dr1`, `observed_convergence`/`trajectory_stability`, and `gappa` `arithmetic_model` (DR-E003, DR-E101, DR-E202).
- Enforce recursive `forbid_keys`, unobserved frame collector boundaries, and reusable idempotency, seam retry/query, rollback, and BOLA probes across bridges.
- Verify pre-registered `stochastic_experiment` evaluation receipts, two-sided CI bounds, QCEC `equivalence` & case-instance `qubits` bounds, and `sum_total` guards (DR-E102, DR-E202).
- Pair renamed contracts (`contract_change = "renamed"`) and cross-contract `case.moved` obligations in `review --base`, and dogfood M3 `[concepts]`/`[invariants]`/frames.
- Order shadow shards by `sequence`/`supersedes` or `--run-id`, harden bridge predicates and frames, and verify `.composition.json`.
- Add `contract.ephemeral_id`, `contract.compound_topic`, and `scope.code_in_sources` in `sweep --simplify`, exempt literal `todo` in notes, and remediate `.drift/contracts`.
- Add `[risks]`/`[controls]`, `*.study.json` and `*.evaluation.json` receipts, and detached `.sig.json` signatures (DR-E003, DR-E101, DR-E104, DR-E105, DR-E202).
- Add tuning-tolerant invariants (`monotonic`, `sum_total`, `step_max_delta`), `drift.sim-receipt/1`, zero-alloc tick budgets, and C++/C#/GDScript bridges (DR-E003, DR-E102, DR-E202).
- Add 2-stage `.security.json` evaluation (`violated` precedence), distinct `subject_ref`/`artifact_ref` attestation binding, and selective `--security-lock` reuse.

## 0.4.0

- Release `0.4.0`.
- Add 3-stage `collectPlaywrightSequence`, observed-only capabilities, `async-action-feedback@1`/`wizard-form@1` recovery, CSS Color 5 token sweep, and scenario matrices.
- Add shadow mode (`--state-dir`/`DRIFT_STATE_DIR`, `shadow.toml`, 3-root resolver, `GIT_OPTIONAL_LOCKS=0`, and 2-phase XML adapter `drift_shadow_junit.py`).
- Add COBOL and PHP symbolic slicing (`WORKING-STORAGE` preamble guard), `EXEC SQL`/`CICS`/PDO/ORM seam discovery, `--copybook` scaffolding, and PHP/COBOL bridges.
- Add `checkSeamBounds` / `check_seam_bounds` 2-skeleton neighbor probing and `prove.seam_mutants` / `buildStub` incoming-seam fault mutation.
- Record `.drift/seam-stub/` producer provenance in `.meta.json`, isolate from `test_inputs`, and emit `oracle.unverified_seam` / `oracle.stale_seam_stub`.
- Add `code.undeclared_seam` in `sweep --root --flow` and route `policy.ignore` helper edits to importing contracts in `select`/`gate --base`.
- Enforce ambient world-frame checks outside permitted writes across all 6 bridges and compose root `_frame` envelopes with `allowed_keys`.
- Add deterministic `workflow_progress` stage/percent bands to `drift.guided/1` views and `schedule.progress` to event-backed or guided schedules.
- Harden observeUiSequence fail-closed nulls, bind parity candidate_subject_ref (`parity.subject_mismatch`), preserve migration `#` partitions, and align GUIDE TOML blocks.
- Add federated composition manifests (`drift.composition-manifest/1`), bidirectional boundary bundles (`offers`/`requires`), and causal incrementality.

## 0.3.3

- Release `0.3.3`.
- Add fail-closed UI surface checks (`surface.missing`), `drift.ui-observation/1` sequences, Web/Compose/UIA adapters, and token sweep.
- Add DB migration receipts (`drift.migration-receipt/1`), telemetry custody/triage (`drift.production-signal/1`), and `DriftJUnit4`.
- Add JUnit 4 bridge (`DriftJUnit4`), DB seam discovery (`db_seams`), `[cutover]` parity receipts (`drift.parity-receipt/1`), and `--wsdl` scaffolding (DR-E003, DR-E104, DR-E105, DR-E406).
- Add context-qualified `[concepts]`, `use.concepts`, `concept_changes`, `new --concept`, and `@concept` recall outside `dr1` (DR-E003, DR-E101, DR-E102, DR-E104, DR-E105, DR-E202, DR-E209).
- Add contravariant `when.narrowed`/`shifted`, `refinement` lattice, `relaxation_witnesses`, `[invariants]`, case `writes`, and `forbid_keys`/`not_in` (DR-E003, DR-E104, DR-E105, DR-E406).
- Add `[formal.<id>]`, `drift.formal-receipt/1` and `drift.subject-manifest/1` checks with `violated` precedence and Rust counterexample fixtures (DR-E003, DR-E102, DR-E104, DR-E202, DR-E205).
- Harden `.security.json` anchor/case/snapshot/conflict checks, bind `--attest` SSH signatures to the subject, isolate Rust mutant aborts/panics, and add v2 sidecar schema.

## 0.3.2

- Release `0.3.2`.
- Verify optional OpenSSH signatures (`--ssh-sign`, `--trust-root`, `--verify-time`) with `drift-approval@v1` and `drift-attestation@v1` namespaces.
- Emit deterministic, input-reconstructable `executor_ranking` in `plan` and `review --detail guided` with `history_unknown` caution and zero owner queues.
- Add `--asyncapi` and `--epoch-manifest` directional multi-epoch compatibility and duplicate-delivery effect checks in `new` and `sweep check --flow`.
- Verify `#<symbol>` transitions between `base_snapshot` and `result_snapshot` under `--execution-context`, `companion_edits`, and `shard.scope_unverifiable` (DR-E003, DR-E102, DR-E202).
- Reconcile `.drift-work/recall.d` and `ops.d` per-worker shards transparently with idempotent rereads, `shard.truncated_tail`, and `recall_conflicts`.
- Reopen POSIX and Windows Stop diagnostics across host turn IDs and prompt-start events while keeping repeats deduplicated within a turn.
- Emit deterministic `next_command` in `drift.guided/1` JSON, Markdown and text views for check, guarded approve and gate transitions.
- Add `handoffs` to `plan --detail guided` and resolve target-matched or `#<selector>` packs directly in `gate --execution-context`.
- Stop hooks name the first finding and one next step, tell findings from tooling failures, disclose unknown task relevance and do not repeat an unchanged block.
- Skills add a native-client flow: negotiated capabilities, consent tied to the reviewed candidate, full text fallback, current approval state trusted on resume.
- Add a shared `drift.guided/1` view to status, review and gate with identified prior-report deltas, per-case proof state and explicit activity/claim limits.
- Bind scheduled execution scope to a complete `drift.execution-context/1` reference and negotiate v1/v2 proof sidecars without changing legacy pack or contract digests.
- Bind guided JSON review to its exact area, selectors, targets, policy and context; reject stale `approve --reviewed` handoffs.
- Show guided decisions in JSON, Markdown and text with declared impacts; surface `policy.max_open` before deadlines without inferring authority.
- Stage approvals safely, make same-owner retries idempotent, and name partial batch outcomes.
- Add compile-once Rust test bridge (`bridges/rust`) with fail-closed `DRIFT_RESOLVED`, per-process shards, `--list` discovery, and in-process/subprocess mutants.
- Index Rust `mod`/`use crate::` graphs with opaque-crate widening, `libloading`/`dlopen` guards, intra-crate cycle exemption, and `#<Type>.<method>` `impl` symbols.
- Add `allowed_keys` to relational `then` tables and verify raw returned object keys before projection across JS, Python, V and JVM bridges (DR-E003).
- Add contextual `classification`, `encoding_context`, `principal_tenant` and `resource_tenant` roles and 3-state `sweep --flow` checks (`issues` vs `flow_risks`; DR-E003).
- Detect `security-coarsened` envelope diffs in `review --base`, add `policy.priority_weights` for `mutants --budget`, and add `checkAdverse` probing across bridges (DR-E003, DR-E102).
- Validate `.security.json` receipts against `scope.code`, snapshots and canonical reuse tuples in `prove`, `gate` and `drift_verify.py` (DR-E003, DR-E104, DR-E105, DR-E202).
- Resolve V `#<Type>.<method>` and Pug/Sass/CSS `#<symbol>` anchors and index Pug `include`/`extends` and Sass/CSS `@use`/`@forward`/`@import` graphs.
- Add `frame_time`, `cold_start`, `artifact_bytes` and `work_units` to `[budgets.<id>]` and `--measurements` for UI and compiler performance gates (DR-E003, DR-E102, DR-E104, DR-E202).
- Add zero-dependency native V test bridge (`bridges/v/drift_v`) with `verified` projections, relational bounds, stubs, golden fixtures, and in-process mutants.
- Index V module imports and `#flag`/`#include`/`C.*` FFI boundaries in `sweep`, detect `dl.open` dynamic loads, and resolve V `_test` IDs in `select --files`.
- Add policy-gated `performance_reuse = "execution"` for unchanged causal cones, marking reused receipts `provenance = "reused"` and `at_risk` while blocking release (DR-E202).
- Distinguish demonstrated `resource.budget_conflict` from advisory `budget_risks` (`budget.slack_inversion`, `budget.unverifiable`) in `sweep --flow`.
- Add configurable `warn_ratio` leading indicators (`performance.near_limit`, `performance.regression_drift`), `at_risk` grading and preventive `revisit_triggered` (DR-E003, DR-E102).
- Add `performance_verification` (`verified`, `at_risk`, `unverifiable`) and `provenance` (`measured`, `reused`, `pending`) to `assurance_card` and `gate --attest` bundles.
- Select affected performance budgets in `drift select`, widen to all area budgets on artifact/build fallback, and add the `bench.jsonl` performance adapter.
- Evaluate `--measurements` performance bundles, independent subject context, statistical/observed regressions and phase gates in `prove`, `gate` and `drift_verify.py`.
- Add `[budgets.<id>]` schema, `evidence_protocols` digest discriminant, `review --base` budget diffs and fail-closed `prove`/`gate` checks (DR-E003, DR-E102, DR-E104, DR-E202, DR-E205).
- Offer an optional session-start notice for newer stable GitHub releases, with an installer prompt, bounded offline-safe checks and no automatic updates.
- Verify mutation evidence for `proof = "killed"` in `drift_verify.py`, block inherited `deferred` cases at release, and reject `NaN`/`Infinity` in bridges.
- Extract canonical `init`, `case add`, `export`, `plan`, `recall`, and `sweep` subcommands with `OperationSpec` capability gating and `--detail summary`.
- Guard shared utility folders in `sweep --sync-scope`, add `--check` previews and `--staged` Git-index mode, and support `sweep --base` / `--delta`.
- Support multiple contract files in `review --base`, reject extra paths after `--changed`, explain reason tokens in `drift explain`, and add `widening_details`.
- Surface `select` widening reasons (`widened`, `reasons`) and fail fast on invalid `select` invocations in JS and Python bridge runners.

## 0.3.1

- Release `0.3.1`; support Scala/MUnit closure tests and `Drift.Case.verify` in `drift-junit`, Scala source/import indexing, and OpenAPI 3.2 `QUERY`.
- Verify cross-service FSM transitions, Saga compensation and duplicate delivery against `--upstream` boundary bundles in `sweep --flow`.
- Resolve multi-hop internal resource chains and `sum_fields` bounds in `@tree` domain envelopes and `--pack` worker scopes.
- Accept version-bound `*.model.json` formal verification receipts (`tlc`, `cbmc`, `alloy`, `spin`) in `prove` and `gate --explain`.
- Enforce inherited profile cases, `proof = "killed"`, `policy.max_open` and `self_stubbed` checks in the standalone `drift_verify.py` verifier.
- Align JVM, JS and Python bridges on key-order-independent object equality, `1e-9` float tolerance, `sum_fields` rounding and `null` vs absent fields.
- Detect tests that feed a contract's own stub into `checkProjection` and report `oracle.self_stubbed` in `review --brief` and `gate --explain`.
- Widen `select --changed` with `code.dynamic_import` when a runtime family contains unresolved dynamic imports or reflection.
- Support custom `role = "state" | "delivery_attempt"` protocol parameters in profiles for domain-specific `sweep --flow` checks.
- Filter `show --boundary` to active cases, bind post-states in `new --from-upstream`, and evaluate state transitions in `review`, `sweep` and `select`.
- Block unimplemented `deferred` cases in `gate --phase release`, keep active test selection unaffected by deferred edits, and track 2-hop Saga rollbacks.
- Detect state deadlocks, missing Saga compensations, unhandled duplicate deliveries and dynamic imports in `sweep`.
- Add `@tree` domain lenses, `branch:<id>` recall filters, private branch leak checks in `sweep --flow`, and consumer-projected worker pack refs.
- Add `schedule.what_if` bottleneck analysis, 3-service domain conflict checks in `sweep --flow`, and `causal_suspects` ranking in `select --explain`.
- Scaffold contracts from runtime JSONL traces in `new --from-upstream`, add contract-free bridge `observe`, and enforce `DR-E602` in `drift_verify.py` (DR-E602).
- Evaluate relational mutants by semantic satisfaction, include boundary `witness` values in `mutants`, and deduplicate `coupling_culprits` test counts.
- Prioritize `impact --schedule` waves by downstream unlock density, detect 3-contract serial bottlenecks in `sweep`, and report queue load in `stats`.

## 0.3.0

- Speed up `--base approved` lookups by batching Git history queries and skipping Git when no contract is stale.
- Emit optional `suggested_ignores` for unowned test, coverage and tool-config harness files in `drift sweep --root`.
- Distinguish `source` `#<fragment>` anchors from `D<digits>` decision references in `sweep --simplify`.
- Support the reserved `approved` baseline token in `diff`, `review`, `select`, `prove` and `gate` to compare against each contract's approved commit.
- Prevent `sweep --sync-scope` from absorbing test harnesses, sibling areas or top-level shared folders into contract `scope.code`.
- Merge `scope.code`, `scope.forbid_imports` and `use.vocabulary` cleanly in `drift merge` while preserving valid approvals across non-digest edits.
- Release `0.3.0`.
- Group `review --base --delta` wave plans by domain hierarchy, flag uniform `then` cases, and include scope limits in `--pack`.
- The drift skill keeps experiments in their own slice, binds tests before implementing and starts the full check from the first integrated commit.
- Markdown review shows open questions and marks missing comparison, selection and impact evaluations instead of implying empty results.
- `status` reports configuration blockers in exceptions and exits 1 even without events.
- Proof JSON rejects nesting beyond 64 containers before decoding: DR-E701/events.invalid for events, usage errors for inventory sidecars, without crashing.
- Recorded inputs union across retained invocations and shard input lookup; any changed input blocks canonical-test base reuse.
- Every command supports early `--help`/`-h` and `help <cmd>` from one synopsis catalogue.
- `new --area NAME [dir]` writes an unsigned core@1 area; never overwrites it.
- DR-E401 names the searched profiles directory using the CLI's relative display convention.
- DR-E001 reports the original text's 1-based EOF line while preserving the reader's syntax-error excerpt.
- `impact --recall` supports typed selectors, negation, AND and OR queries.
- Base proofs of parameterized tests reuse canonical inventory inputs when disjoint from changed files; changed inputs still block reuse.
- Gate filters versions before effective-shard selection: obsolete reruns cannot erase `shard.scope_escape` or `shard.stale_pack` fences.
- Proof events reject malformed JSON with DR-E701/events.invalid; malformed inventory sidecars remain usage errors, including trailing delimiters.
- Required option values reject a following option before writes; `new` names extra positionals and explains repeated one-value options.
- `status`, `review` and `gate` add `--as summary`: scoped output, one next action and honest proof/Git labels; legacy formats stay unchanged.
- `gate` logs its elapsed `ms` in `.drift-work/ops.jsonl`; `cli` cases record the `at` and `ms` integers of a captured ops log as `"<int>"`.
- `review --brief`, `approve`, `gate` and `stats` search for `.drift-work/ops.jsonl` only up to the nearest directory holding `.drift/`.
- Add coupled numeric mutants, stub desymmetrization and `sweep --simplify --apply`, per-method JUnit mutant runs in `gate`, and `#<prefix>*` symbol globs.
- Detect symmetric cases (`case.symmetric_witness`) and peer-swap mutants, isolate per-case mutant runs, report `coupling_culprits`, and emit `assurance_card`.
- Tighten integer relational bounds and prioritize boundary-central mutants in `mutants --budget`.
- Propagate consumer relational constraints across shared resources in `sweep` and eliminate redundant relational bounds.
- Tighten multi-hop relay bounds and bridge stubs, validate multi-field `sum_fields` invariants, and improve `sweep --promote` grouping.
- Prune duplicate predicates in `sweep --promote --apply`, check joint producer-consumer boundaries, and report peer-coupling changes in `review`.
- Synthesize valid multi-field `sum_fields` stubs across bridges and refine `mutants --budget` scheduling.
- Support cold-area `status`/`impact`, `new --from-recall --code` and `select <base> --changed`; add `sum_fields`, `contains`, `prefix` and `suffix` (`DR-E003`) and `sweep --apply`.
- Distinguish necessary vs sufficient `boundary_impact` changes, diversify `--query`/`--recall` results, and surface `latent_consumers`.
- Expand multi-parameter bridge boundary domains and wave-concentration checks; add diagonal `mutants --when` and multi-hop relay `select`.
- Add precedent checks and `max_open` limits in `review`, `priority_tests`/`flaky`/`triage` in `gate`, crash-safe `schedule --events`, and `by_profile` `stats` flow.
- Add delta `review --base [--delta]` and `wave_plan`, `pack_ref`/`touched` shard fencing, and `stats --ops` flow telemetry.
- Tighten relay bounds in `review --base`, narrow hop-1 `select` per resource, and group cross-contract `sweep --promote` candidates.
- Heal moved directories/globs in `sweep --sync-scope`, resolve TypeScript ESM imports, track `git mv` in `impact`, and isolate monorepo `--changed` runs.
- Check `scope.code` continuity, detect `code.circular_import` cycles, enforce `max_lines` and `forbid_imports` (`DR-E003`, `DR-E105`, `DR-E202`, `DR-E406`), and parse Python imports.
- Propagate multi-hop boundary bounds, schedule conflict-free wave lanes, and support `<path>#<symbol>` code anchors.
- Support coupled relational boundary domains and `mutants --when`; add dirty-worktree JS/Py `DRIFT_SNAPSHOT`, `case.fragile_ui_text` and DOM pointers.
- Add positional `impact <chunk>` with `test_files`, partial-run `.meta.json` merging, `mutants --changed` and `new --code`; add `drift status` and `new --from`.
- Add symbolic context capsules (`impact --recall [--share]`), auto-stamped symbol hashes, `new --from-recall` and `sweep --recall`.
- Expand pairwise boundary coverage for 3+ parameters, merge multi-key relational cases and profile promotions, and add `when` boundary mutants.
- Report `resource.unobserved_fiber`, `projection.folded` and `resource.ambiguous_projection` in `sweep`; support Git refs in `--base` and `fmt --sync-vocab`.
- Support inverse-`when` boundaries and 8-level peers (`DR-E003`), polarity-safe `new --from-upstream` and `<res>:/...` hop-1 `select`, and contiguous integer joins.
- Export boundary bundles (`show --boundary`), verify `--upstream` consumers, scaffold with `new --from-upstream`, and synthesize upstream bridge stubs.
- Add priority-tiered `mutants --budget`, peer-resolved relational bounds (`DR-E003`), `case.flopped` tracking, and `impact --schedule` safety guards.
- Detect `code.unowned_import` and `code.coarsenable` globs, add `sweep --sync-scope`, and bootstrap `.drift-work` automatically.
- Add relational `then` constraints (`min`, `max`, `min_len`, `max_len`, `non_empty`, `le_field`, `ge_field`, `eq_field`, `in`, `DR-E003`), `boundary_impact`, and `select --files`.
- Normalize projected partitions, narrow hop-1 `select` and `sweep --promote`, track `case.split`/`case.merged`, and localize decision options.
- Add decision risk signals (`assumed-high-leverage`, `high-risk-one-way`), `case.untracked_deferred`, `rework_share`, and bottleneck bridge guards.
- Reuse base proofs via `.meta.json` `inputs`, narrow hop-1 `replayed_cases` in `select`, add `mutants --budget` and `shard.incomplete` checks, and rank `unblock_share`.
- Keep `dr1` digests invariant across `extends`, unused `[use.vocabulary]` and prose `note` edits, and flag boolean-only `then` cases in `review`.
- Add outside-digest `note` fields, profile `[projections]` (`DR-E003`, `DR-E101`, `DR-E105`), tiered `sweep --simplify`, and `core@1` `sweep = "soundness"`.
- Release `0.2.1`; profile `extends` (`DR-E105`), `[use.vocabulary]`, `<path>#<symbol>` & `<resource>#<partition>` anchors, and `.drift/events` auto-discovery.

## 0.2.0

- `review --base` `migrated` (`case.split`, `case.merged`) & `coarsened`, `--schedule` anti-chaining guard, and `sweep --simplify` `case.incomplete_partition`/`subsumed`/`coarsenable`.
- Epistemic card signals (`assumed-one-way`, `assumed-high-confidence`, `high-complexity-low-leverage`, `pick-sensitive`), `revisit_triggered`, `notify_owners`, and `perturb-case-when`.
- `gate --phase execution|release`, `stats --compare` `dropped`/`inconclusive`/`mutant_shortfall`, and decision `deps` co-optimization with Hasse reduction.
- `sweep --promote` `disposition`/`waivers`, `sweep --simplify` hygiene audit, `--explain` `exclusive_test` & `shared_test_share`, and `sweep --flow` `resource.dead_write`.
- `impact --schedule --pack` worker packets, `gate --compare-before` F2P verification, `mutants --when` `swap-case-when`, and `stale_cause` in `review --base`.
- Bounded domain probing (`checkBounds`, `param_specs`, `checkProfileBounds`), `impact --schedule --events` wave readiness, and intra/inter-contract conflicts in `sweep`.
- Bridge `readFixture`/`recordInput` & `DRIFT_ENV`, `new --from-intent`, `review --as md` bounds/signals, and Maven `at`/`attest`/`explain` forwarding.
- Bridge auto-resolve, `checkView` & `resource.projection_conflict`, `@sha256` source pins & `new --case`, `intent-untested`, bounded `params` (`DR-E003`), and `--at`.
- `.meta.json` `inputs`/`env`, `prove.compare_keys` & `proof_key_verified`, hybrid `select`, `evidence_matrix`, `snapshot_verified`, and Python bridge `drift.py`.
- `sweep` `surface.status_missing` & `promotion_conflicts`, `impact` `mandatory_leaves`, `gate --attest`, JS `d.check`/mutants, `--explain`, and semantic `merge`.
- Editor schemas validate contracts, profiles, configs, and proof events; `impact --code` `unmatched_code`; `drift version` build id; `DR-E406` single-line formatting.
- `GUIDE.md` adoption levels L0–L3; `review --as md` English sections.
- `impact --schedule` cohesion-aware DAG, `slack_w`, `dispatch_order`, `max_workers` and wave `topology`.
- Outside-digest `open.<id>.owner`, profile `requires.proof`, `sweep --promote` and `stats --compare`.
- `impact --toc`, `--query TEXT [--top N]` and `--depth N`; `DR-E602` blocks any remaining `todo` value.
- Inventory Git `snapshot` & Maven `-Ddrift.changed=auto`; `sweep --openapi`; `stats` `radar` ratios.
- Mutation analysis `drift mutants` and `core@1` `proof = "killed"`; opt-in `core@1` policy pack and `DR-E603` (`e603-approver-unknown`).
- `review --brief --base` & `--as md`; `impact`; inventory sidecars & `gone`; hop-1 resource `select`.
- Area-wide ownership across `select`, `prove --base`, `impact --code` and `sweep`; JS bridge `bridges/drift.mjs`.
- `merge` refuses comments (`DR-E004`); directory targets; `select --changed` matches `scope.code`; unused vocab & `owner` outside digest.
- Short refs `dr1:<12hex>` & `[approval].ref` (`DR-E003`, `DR-E102`, `DR-E104`, `DR-E601`); test reruns & supersession; CRLF invariance.
- Linux x86-64 and Windows x64 release archives and installers; M2 `select` and `DriftSelect`; proof event `digest` validation (`DR-E701`).
- M1 `gate`, JVM JUnit bridge (`@DriftCase`, `Drift.expect`, `DriftListener`), signed `.drift/config.toml`, and `review --brief`.
- M0 kernel (`check`, `show`, `fmt`, `diff`, `approve`, `prove`, `explain`, `version`; `drift/0.2`, `dr1`, `DR-E001`–`DR-E702`).
