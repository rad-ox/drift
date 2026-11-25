# Changelog

User-visible changes and capabilities by release.

## 0.11.0

- Release `0.11.0`.
- Package and install `drift-map-ui` across `make install`, release archives, installers, and public export; sync `0.11.0` public docs (`README`, `GUIDE*`, `INSTALL*`, `EDITIONS`, `GUARANTEES`).
- Add Free `drift run [--events DIR] [--gate] [--state-dir DIR] -- <cmd>` wrapper with atomic view export, zero-clobber events, and optional `--gate`.
- Redesign `drift-map-ui` canvas: layered routed links (arrows, labels, legend filters), pan/zoom, search, history, link inspector, on-map Walk; self-test checks served-page CSP hygiene.
- Add `drift map` (`cases`/`flow`/`state`, `--as mermaid`, `--what-if`), `drift map focus`, `drift map walk`, and isolated offline `drift-map-ui` explorer.
- Align CLI `--help` synopses for `gate --as junit|summary|md` (Free: `summary|md`) and `init <owner> [dir] [--observed] [--taplo]`.
- Enforce exact numeric `eq` (no implicit `1e-9` slack without `tol`, plus `BigInt`/unsafe-int guards) on schema `0.3` in Rust, JS, and Python bridges.
- Fail closed with `obs.frame_missing` (`inconclusive`) when `scope.writes \ permitted != empty` and `frame`/`frame.writes` is omitted, across V kernel, offline verifier, and fuzzer.
- Reject non-canonical `(`, `)`, `[`, `]` in `.meta.json` `classes`, `tests`, and `inputs` keys fail-closed (`DR-E701`) in both V kernel and offline verifier.
- Add declarative cross-bridge behavioral conformance matrix (`oracle.jsonl`, Rust `--edition=2021`) checking local, wire, kernel, and verifier parity across JVM, JS, Python, Rust, and C++20.
- Emit contract/config/event findings (`DR-E601`, `DR-E701`) under not-green contracts in `drift gate --as md` and clarify reruns/retries and `(JS/TS)` scope in the superseded explain note.
- Restrict JVM projected observations to exact needed pointers (skipping unused ancestors and UI payloads) and enforce the 1024-char cap in Unicode code points while rejecting lone surrogates.
- Harden drift-junit strictWhen (dynamic cases, DynamicTest, OR env/prop, META-INF Extension, end/finally cleanup), standalone caller IDs, and snapshot-mismatch stderr diagnostics.
- Harden Python bridge: lexical precheck & then-wrapper, strict plan keys, exact int eq, generator guard, sync snapshot check, .plans manifest/autoload, safe sidecar merge/lock, and sibling loader.
- Add cross-process lock + atomic rename on JS/Python single-file `.meta.json`, validate `DRIFT_SNAPSHOT` synchronously in JS, and mirror `.plans/` + unify `attachBridgePlan` on cold auto-resolve.
- Restrict JS/Python projected observations to peer/invariant-referenced pointers (skipping unreferenced ancestors) and align Unicode caps on code points and UTF-8 bytes.
- Treat TOML literal maps containing `"$t"` (in `then` and `when` peer clauses) as plain application maps rather than tagged wire nodes in both the kernel oracle and offline verifier.
- Unescape RFC 8259 JSON object keys (with post-unescape duplicate detection) in `inventory`, `openapi`, `upstream`, `formal`, and `build_graph` parsers, and allow UTF-8 trailing bytes in test IDs.
- Preserve `obs_red` provenance in `drift gate --explain`, render `bound` reasons in `--as md` with `--explain` support, and omit redundant `--explain` advice when already set.
- Harden `drift_cpp.hpp` within the `11200` budget: validate 40/64-hex snapshots, reject stray `]` and blank `inputs`, allow `(...)`/`[...]` spaces, and add `ObsScalar::floating`/`null`.
- Reject non-object `frame`/`presence`, falsy non-list `frame.writes`, and malformed `touched_symbols`/`init_only_symbols` in `drift.observation/1` across both CLI (`DR-E701`) and offline verifier.
- Explain `bound` downgrades from missing `drift.observation/1` or `self_stubbed` in single-contract and directory `drift gate --explain`, keeping exit codes and `--json` unchanged.
- Harden `drift_rust` discovery & shards: subtract `--ignored`, align homonym IDs, project `then` pointers in observations, and merge foreign classes + check snapshots on single-file `.jsonl`.
- Harden `drift_rust` runtime: emit failed events on panics, isolate mutant files, format large floats, reject non-int casts, validate `DRIFT_SNAPSHOT`, and catch `./` self-stubs.
- Add C++20 canonical sidecar inventory and typed `ObsScalar`/`emitObservedProofBatch` `drift.observation/1` emission (`cpp` ceiling `10150 -> 11200`).
- Add JUnit 5 `@DriftCase(strictWhen)` / `DRIFT_STRICT_WHEN` (`AfterTestExecutionCallback`), `unreadWhen()`, and standalone `Drift.runCase()` for MUnit suites.
- Emit bounded `drift.observation/1` payloads from actual pointer reads in JS `checkProjection` and Python `check_projection` (including `__plan` fast-path).
- Add opt-in `strict_when` / `DRIFT_STRICT_WHEN` and `DriftContext.unread_when()` parity to Python bridge.
- Add Free `drift init --observed` preset (`proof = "verified"` + `require_observations = true`, default unchanged) and non-blocking `verified`-without-observations advisory.
- Resolve selected `.drift/config.toml` first in memory during multi-target `drift approve` batches, preserving preflight rollback, area isolation, and `--reviewed` binding.
- Document Gradle + JUnit 5 usage in `docs/bridges.md` (env vars vs allowlisted `systemProperty`, `--rerun`, directory-mode `maxParallelForks`, clean dirs, dynamic `@DriftCase`).
- Harden `drift-junit`: `DRIFT_SNAPSHOT`/`DRIFT_SELECT` env, `@Disabled` container drop, fail-fast config & atomic flush, single-file snapshot lock, empty-cases `@DriftCase`, ClassSource IDs.
- Document Scala 3 / MUnit operational contract in `docs/bridges.md` (clean `DRIFT_EVENTS`, forked sbt env vars, `afterAll` flush, standalone verify boundary, Scala 2.12 caveat).
- Harden `drift-junit`: standalone ThreadLocal reset, Scala 3 case-class/`Map.empty` verify, self-stub & `inputsUnchanged` guards, idempotent flush, `(` IDs, env fallbacks, and projected 0.3 obs.
- Harden Python bridge: pytest/0-event runner guard, fork/switch shard isolation, mutants rc/setup-error handling, async rejection, pytest env.runner, module.Class IDs, and strict CLI parsing.
- Fix Python bridge mtime-guarded inventory merge, gate/prove runner rc propagation, self-stub obs suppression, '(' canonical test IDs, and fail-closed cold 0-file test runs.
- Fix JS bridge Mocha titlePath(), test/ cold discovery and fail-closed empty test runs, runner env detection, UTF-8 4 KiB observation cap, project-scoped DERIVED keys, and retry supersession.
- Fix JS bridge canonical test IDs on '(', gate/prove runner exit-code propagation, and mtime-guarded prior inventory merge to prevent deleted/skipped test resurrection.
- Fix offline verifier canonical_test_id '(' truncation, multi-shard inventory membership parity, and 0.3 missing-profile ValueError/DR-E401 handling.
- Align `docs/bridges.md` (remove `checkLogSink`/plan-loader overclaims on C++/C#/GDScript) and clarify `GUARANTEES.md` exit-2 inventory rejection.
- Fix drift_cpp.hpp NaN/Inf guards, maxDelta==0, multi-run emitProofBatch with outcome/level/0.3 capabilities, JSON escaping, 0.3 monotonic, replayCounterexamples, _frame guard, and emitSimReceipt.
- Fix offline verifier f32/f64 bits decoding, IEEE-754 f32 rounding, and false-positive unevaluated ["touched"] on .meta.json shards without touched.
- Add `drift.observation/1`, single-file `.jsonl` `DRIFT_EVENTS`, `strict_when`, Edition 2021 (`1.80`) to `drift_rust`, and align verifier float `peer.sum`/`balance`.
- Add opaque `[policy]`/`superseded` advisories, JS `drift.d.mts`, `project`/`DRIFT_TEST_PREFIX`, `strictWhen`/`DRIFT_STRICT_WHEN`, and `drift_verify.py --compare-gate`.
- Add native pure-V OpenAPI 3.x YAML 1.2 Core decoder (`sweep`, `export boundary`, `new --openapi`) with fail-closed duplicate/anchor/alias/merge/tab/budget guards.
- Auto-emit schema-valid `drift.observation/1` (`outcome = "returned"`, measured `frame.writes`) in JVM/JS/Python, align JVM 0.3 `eq`, and fix verifier `$$`/U+2028 parity.
- Default `show --out` & `.drift/` under `--state-dir`, add Free frame/floor advisories, and add `drift.stateDir` to `drift-maven-plugin`.
- Exclude doc/line comments from `bridge_budget_test.v` non-ws counting and accept unary `!` mutations in `scripts/selection_check.py`.
- Parallelize `release-build.yml` verify into 3 cached pre-gate jobs, parallelize cross-compile toolchains, and isolate parallel 4-target Free builds in `release_packaging.py`.

## 0.10.0

- Release `0.10.0`.
- Sync public docs for `0.10.0` (`--as packet|digest`, `--lens-diagnostics`, `[policy.autonomy]`, `drift-signature@v2`, surface contract `/2`).
- Add remote snapshot seal `drift.signature-payload/2` (`@v2`), `[policy.autonomy]` envelope, and Pro `review --as digest` backpressure.
- Add Free `review --as packet [--tier 0|1|2]` omnichannel IR (`drift.decision-packet/1`, computed `C0–C4`) and `drift-ask-ui` surface contract `/2`.
- Upgrade red-team benchmark to live unittest/read-only isolation control arms, Free `--edition` skip, fail-closed accounting & P01–P08; add PR live HTTP verifier E2E & README tiers.
- Preserve multi-selector, spaced-path, and repeated `--events` operands in guided `next_command`, omitting unsafe shell commands with an explanatory `next_action`.
- Open guided summaries with verdict, qualifier, `--previous-guided` counts, and all `claim_limits` within 12 lines while keeping JSON/`view_ref`/exit unchanged.
- Preserve advisory `budget-at-risk:` warnings on unchanged `current` contracts in `review --base --delta` without widening `review_snapshot.targets`.
- Reject empty `--max-degraded-lenses=` with exit `2` and add opt-in Pro `--lens-diagnostics` per-clause `requested/emitted/degraded/unavailable` accounting.
- Add objective `relay` skill eval check, verbatim guided-summary relay + `5 of N` choice receipts in `native-flow.md`, and folded-surface quadrature conformance.

## 0.9.1

- Release `0.9.1`.
- Route `make publish-github` through `rad-ox/drift-src` `v*` tag push when `RELEASE_SIGNERS` is pinned so `release-build.yml` signs OpenSSH/Sigstore/TUF assets.

## 0.9.0

- Release `0.9.0`.
- Sync public docs and skill refs for `0.9.0` (`--taplo`, `require_observations`, `verdict_diff_fuzz.py`, `--pairs`, `--density`, `--max-degraded-lenses`, `--pack-base`).
- Add Pro `plan --pack --pack-base` content-addressed backscatter delta (`drift.pack-delta/1`) with channel byte accounting and lossless reconstruction.
- Add Pro `recall query --max-degraded-lenses <N>` fail-closed over-compression guard citing `first_degraded_anchor` over bounded lens counters.
- Add Enterprise `stats --density` per-resource cost-per-verified-obligation (`C/U`) telemetry summing retries before obligation deduplication.
- Add Enterprise `drift mutants --pairs` bounded 2nd-order pairs, `pact.boundary_non_injective` in `sweep --flow --pacts`, and `make confluence-fuzz`.
- Add rewrite-diamond, Yang-Baxter braid replay, 2nd-order mutant pair V tests, and boundary-opacity/undeclared-seam non-collapse harness.
- Deduplicate HyperedgeCollector members with -gc none safe growth in interference_compact.v and rank >8 critical what_if cuts across components in schedule_what_if_select.v.
- Fix triple-conflict parallel-edge cycle masking, enforce simultaneous 3-way at-level overlap (levels_overlap3), and drop -gc none heap array literals in rel_domain.v.
- Partition sparse polytope rows by connected components before the 64-row cap so disjoint rows preserve tightening, mutant witnesses, and `sweep --flow` refutations.
- Add baseline proving-set erosion signal (`proving_tests_removed`, opt-in `block_redundancy_erosion`) and trusted-core LOC/parity ratchet.
- Auto-emit `drift.observation/1` in JS/Py `d.check`, close verifier obs parity, add `policy.require_observations`, and add `verdict_diff_fuzz.py`.
- Block tautology JS/Py callbacks (`() => true`/`lambda v: True`), move release-independent checks pre-merge on PRs, add red-team A12–A14, and align `verified`/`gone` docs.
- Replace ±1e308 sweep sentinels with ±Inf, add Helly-1D triple & restricted-level fast paths, deterministic budget alias/op checks, and O(1) preflight sets in mutants.
- Remove unreachable `apply_polytope_modular_congruence` branch, dead `fixed_pairs` slice allocation, and superseded `rel_balance.v` congruence helpers in `drift/model`.
- Reject `observed_convergence` rebounds strictly above `roundoff_floor` as `sim.convergence_degraded` across V prove and Python verifier.
- Replace quadratic rescan in `exact_relay_refutes_when` with stack/heap single-pass heapsort and per-pointer coverage cache in `sweep --flow`.
- Add CLI remedy hygiene & DR-E602 hints, TTY ANSI/adaptive `show`, collapsible Wave/CI Markdown & `unread_then`, and 0.3 schema descriptions + `init --taplo`.
- Add 128-bit `WideInt` balance/sum cancellation & pivots, GCD-reduced modular bands, signed `balance_fields` couplings, and `TwoSum` 0.3 linear eval.
- Avoid quadratic map cloning in `drift/pact` via zero-clone `when_maps_overlap`, `cell_coverage` root fast-path, and single-pass equalizer `p_hits`.

## 0.8.1

- Release `0.8.1`.
- Set 180-day TUF timestamp/snapshot expiry, add `rotate_signed_root`, export passphrase-encrypted offline TUF root key + `DRIFT_PUBLIC_REPO_TOKEN` in `setup-github-env`.
- Replace DFS relay clamping cache with Tarjan SCC topological and bounded 8-round Jacobi refinement in `sweep`.
- Attribute Saga compensation channels in `sweep --flow` to failure-guarded reads, per-case `writes` frames, and isolated `#anchor` partitions.
- Scope multi-producer hop-1 replay read-side envelopes and case diffs per `(pid, base_r)` edge while keeping write-side global fallbacks.
- Collect all eligible producer candidate values in `resource.unreachable_when.values` on exact integer relay refutations, invariant to relay case ID order.
- De-golf `drift_verify.py` into clean loading (`drift_verify_events.py`), evaluation (`drift_verify_eval.py`), and CLI modules with readability guardrails in `verifier_dag_test.py`.
- Add differential JSON fuzzer, anti-false-green red-team benchmark, honest bridge CI status matrix, and Rust/C++20/COBOL/PHP/C# public CI checks.
- Fix verifier JSON escaped-quote depth scan, align threat/mirror docs & live HTTP CI, and add OpenSSH/SLSA/Sigstore/TUF supply chain + `drift-src` release workflow.

## 0.8.0

- Release `0.8.0`.
- Fix Windows cross-compilation `C.PeekNamedPipe` bool check in `approval_write_windows.c.v` and strip internal ID from `drift-hook.sh` comment.
- Eliminate concurrent `resolved-gen` TOCTOU `rmtree` race in Python/JS `ensure_export_generation` by copying from per-PID staging before atomic rename.
- Harden Free export/packaging, warn on Free sweep=soundness, align SPEC 0.3-only prose, enforce 5-runtime case 101 parity, lock drift/* edges & show tiers, add sanitize.
- Restructure public docs into a 3-line-hero README, L0–L1 guides, auto-generated `docs/cli.md`, `docs/bridges.md`, and 8 focused `docs/` guides with CI parity and link checks.
- Add stdlib `scripts/perf_resource_collector.py` POSIX `wait4` collector emitting verified `cpu_time_ns` + `process_rss` `drift.performance-run/1` bundles and sync docs.
- Add monotonic `[requires].budget_metrics` closure/coherence across check, `dr2a`, grants, cache, review, and multi-case baseline disambiguation.
- Add direct `cpu_time_ns` budget metric with V/Python verifier parity, restrict Pact timeout inference to `request_latency`, and guard `bench --self-perf` metrics.
- Emit `budget.referent_changed` in `review --base` `coarsened` and neutral `budget-offset-unverified:<id>` on strict unchanged-ref shifts.
- Harden Python paths: guard 3.11+ (exit 2) and unify ssh-keygen in verifier, ship verifier/ in dist archives, isolate check.py (-I), and handle missing python3 in install.sh.
- Require `cause` on `red` worker return receipts and halt identical local retries after two matching non-transient reds in `schedule-orchestration.md` across all 3 skill editions.
- Reuse `(color, index)` topological order for `tail` and stop `select_orientation` / local search at exact `rw`/mutex/chordal dual floors with byte-identical plans.
- Extend `review --base` with `added-case-undiscriminated` and `unexercised-then-keys` on modified `0.3` contracts and update `integration-first.md`.
- Add Pro `drift plan --compile-edges` and `--build-graph` stage ordering and `module_deps` in `drift.build-graph/1`.
- Isolate concurrent JS/Python `drift_cli` run paths, shard `drift_v` mutants by PID, and enforce `DRIFT_STATE_DIR` parity across 4 bridges.
- Add diff-anchored `L2` symbol witnesses (`oracle.unexercised_diff_symbol`) in `prove` and `touched_symbols` emission in `drift_v`.
- Run `stale_pack` fencing pre-pack, move completed revisits to `revisit_watch`, and compact partial `plan` mega-lanes.
- Fold quiet-completed `plan` text with `--events`, add Pro `drift plan --active`, and align hooks/skills on `'contextSlice @:, editSlice @'`.
- Degrade overflow `@` code lenses to `@:` in `recall`, report `resource.unbacked_when` in `sweep --simplify`, and add skill attention receipts.
- Anchor desktop option trade-offs to one non-dominated reference, flag dominated options, move `leverage` to details, and enrich Seal.
- Add stdlib `scripts/drift_build_graph.py` Cargo/Maven `drift.build-graph/1` adapter for `select --build-graph` narrowing.
- Gate `Evidence: bound lacks complete expected-value read attestation` in `--as summary` on `bound > 0`.
- Export `DRIFT_*`/runner `env` and inline `drift show --out` in `select --cmd` snippets while keeping `select` `pure_read`.
- Add `#[ignore]`/`--include-ignored` `drift_rust` guidance and `sweep --root --simplify` `code.shared_test_file` unanchored test hygiene.
- Add explicit `[runners.<id>]` config profiles (`rust_test_exact`, `widen_argv`, `uncovered`/`partial`) for `select --plan` and `--cmd`.
- Add `[policy].uncovered` brownfield globs (`uncovered_paths`), `partial_tests` on widened `select`, and `policy.ignored_manifest` in `sweep`.
- Preserve `--phase`/`--at` in guided `gate`, clear `next_command` on non-case blockers, map `model.lookup_reason` in summaries, and cap `hook session` shards.
- Report proven gaps in exact integer relay copies under `sweep --flow`, without changing existing relay bounds.
- Sum frame budget limits exactly in `sweep --flow`, independent of producer order (`budget.frame_envelope_exceeded`).
- Focus `plan` `what_if` on zero-slack critical arcs, tighten `staffing` bounds, and short-circuit optimal chordal orientations.
- Cover open integer intervals in `pact` across V and `drift_verify.py`, and guard `sweep --simplify --apply` against missing cube leaves.
- Keep tolerant affine sums sound, catch zero-support pivot contradictions, and dual-validate relaxation and mutation witnesses.
- Add segmented benefit and complexity scores and inline, keyboard-operable option details to desktop review.
- Guard signed `i64` boundaries in pact `int_range`/`not_in` meet, `enum_set` subsumption, and strict `i64` parsing for full parity with `drift_verify.py`.
- Make the approval name editable on every desktop seal; use the confirmed name for that review without replacing the saved preference.
- Fix false `.uncovered` on unmaterializable pact `when` axes, rank splittable axes by open-child clauses across V and `drift_verify.py`, and skip uniform overlap loops.
- Fix desktop reviews stuck at Approve when the saved identity is not authorized in the current area; allow explicit correction for that review.
- Turn off desktop review inactivity expiry by default; keep explicit user-local idle limits and independent liveness checks.
- Show expected benefit and estimate confidence on desktop option cards and mark a uniquely highest declared benefit without altering recommendations.
- Enforce multi-manifest permutation invariance on `killed_set_relation` in `stats` and `sweep` `proof.overlapping_tests`.
- Couple `(pc, cc)` witnesses (levels, `when`, post-state, joint polytope) and enforce token-bounded exemptions in `sweep --simplify` `resource.unhandled_outcome`.
- Redesign `drift-ask-ui` into Atmospheric DRIFT Observatory across Web Deck and WPF (living sacred-geometry spine, glass monoliths, Obsidian-Quartz Gate CTAs, WCAG AA+ a11y).
- Stratify `drift_verify*.py` into an acyclic DAG, split near-28k V/COBOL/test files, cache V test binaries, batch JVM `select`, and clear remaining T1 clones.
- Add Pro `drift recall record` with typed `[revisit_if: <anchor>]` dead-ends, `[due]` tracking, `--retire`, and `review --base` `recall-revisit` signals.
- Rebalance polyglot bridges `<25k` chars, stream `dup/1` misses (`162 MiB` cold RSS), unify `prove`/`gate` & `impact` helpers, batch `pwsh`, and guard `gate` anti-cache.
- Memoize `sweep` file facts (`-52%` RSS), speed up `status` (`5x`), unify `0.3` peer-refs/`cat-file`/glob helpers, and rebalance LPT/JVM/registry CI lanes.
- Extract T1 commons, prune dead `0.2` check paths, add zero-copy `canon.sha256_hex` and dynamic complexity ratchets, and speed up CLI/JVM/layers test lanes.
- Add Enterprise advisory `code.duplicate_symbol` T1 clones in `sweep --root --simplify`, lazy `dup/1` digests in `area-v1.json`, and `grown`/`diverged`.
- Add Enterprise advisory integer-only `churn.coupled_contracts` pairs (`lift >= 2`, `conf >= 3/5`, single-owner files) in `stats --root --churn-list`.
- Add Enterprise advisory `resource.write_duplicate` `O(N)` projected write-duplicate clusters and `--base` `new`/`grown`/`diverged` in `sweep --simplify`.
- Emit compact `O(R + G)` hyperedge `overlaps` by default in `drift plan` (`--overlaps compact|pairs`) and skip pairwise map allocation in text/pack.
- Add Free-tier single-process `drift hook <session|prompt|stop|notify>` (`< 25 ms`) and thin `drift-hook.{sh,ps1}` shims with full `drift.attention/1` parity.
- Add lazy auto-populated advisory area and Git-blob source-fact cache (`.drift-work/cache/area-v1.json`) with uncached `gate`/`check`/`prove`/`approve` guards.
- Speed up `gate --base` demand-driven reuse, `readdir` walks, `O(F+E)` SCC `sync-scope`, `drift_v` append shards, `drift_verify.py` profile memo, and conformance LPT shards.
- Speed up `gate`/`status` soundness, `recall`, `select`, `sweep`, `PairStore`, and `drift_verify.py`, and measure attested `--drift` RSS in `perf-check`.
- Refine `drift-ask-ui` into Stratigraphic Dossier with 3D vertical cards, living Bezier wave spine, visual `Spec` flow, `[ui].theme`, and PS1 parity.
- Add universal default-on `drift-ask-ui` decision and approval broker (WPF + loopback `web-deck` across Windows/WSL/macOS/Linux, `--off|--on|--status`).
- Project `proposed_choices`, execution choices, and `baseline_delta` in `drift.guided/1` and narrow `--delta --detail guided` snapshots across subdirectories.
- Add cold-start `review --base` signals (`write-without-error-frame`, `singleton-when-domain`, `unexercised-then-keys`) and advisory `merge.disjoint_cases`.
- Add Pro `select --build-graph-base` / `--build-graph` (`drift.build-graph/1` `build_deps_ref` closure narrowing with `code.unowned` fallback).
- Add Linux network/readonly-workspace containment in `contain_exec.py` (0 bridge LOC) and `dr2a:` `guards.require_containment` across kernel and `drift_verify.py`.
- Add Enterprise `gate --allow-break-glass` (`emergency:` `break_glass` signatures, calendar `--verify-time`, inviolable guards, zero reuse, federated taint).
- Harden `--trust-root` symlinks and add `owner:`/`runner:` role-bound `drift-signature@v1` checks, `require_signed_approval`, and `shard_bundle` provenance.
- Add `drift.shard-bundle/1` (`dr2s:`) manifests, retry deduplication, `shard.conflicting_bundle`/`shard.bundle_hash_mismatch`, and `proof_events.py --emit-bundle`.
- Add opt-in `policy.patch_scope = "required"` (`shard.snapshot_required`), directory `--result-snapshot` hash binding, and `.c` `#<symbol>` fencing.
- Add multi-machine `execution_keys_complete` and `uniform_env` across `prove` and `gate` while preserving `proof_keys_complete` and single-env JSON outputs.
- Enforce exact `#<symbol>` `symbol_missing`, additive `imports_only` fencing, cross-slice import `select`/`gate --base`, FSM frames, and `--openapi` schemas.
- Fix `sweep` multi-conflict `unreachable_when`, consumer `peer.balance`, `out` units, fail-closed `0.3 -> pact` atoms/frames/resource pointers, and fleet error sets.
- Align `0.3` `tol` algebra, `num` merged invariants, `keys`+`peer` checks, converted `peer` units, affine `peer` cycles, `O(K log K)` `not_in`, `enum`, and `series`.
- Fix `drift_verify.py` `--base` reuse, `orphan`/`gone`/inventory/floor/`0.2` parity, empty-digest `gate --base`, CLI seam-stub signals, and `review` proof lowering.

## 0.7.0

- Release `0.7.0`.
- Sync `0.3`-only docs, `forbid_touched`/`[requires].budgets`/`alloc_*` surfaces, and public changelog sanitization.
- Add profile `[requires].budgets` posture and `dr2a:` `[assurance.guards].forbid_touched` dynamic symbol guards across kernel, grants, and `drift_verify.py`.
- Add `alloc_bytes_total`/`alloc_count_total` budget metrics, 4x scaling measurement bundles, and regression kill-checks.
- Add fail-closed worker containment, `parse_direct_diag` `fmt` closure, baseline confidence/`dr2*` verifier parity, and `budget-baseline-regressed`.
- Drop legacy schema `0.2` support (`DR-E002` on `drift = "0.2"`), retire `fmt --upgrade` (`replaced_by = "fmt"`), and remove `0.2` schemas and verifier branches.
- Warn on legacy `0.2` files in `doctor`, close `0.3` parity across `peer.eq`, `requires.security`, `emit_03`, and `drift_verify.py`, and migrate corpus/tests to `0.3`.
- Switch `default_schema` (`version`), `init`, `openapi`/`asyncapi`/`wsdl`/`copybook`/`recall` scaffolds, `fmt --upgrade 0.3`, `pack_ref`, and attestations to `0.3`.
- Outperform `0.2` across all 18 `0.3` engine rows via `PreInherited03` slots, `EqInternCache03`, streaming `emit_03`, sorted `ObsField` slices, and parallel `sweep`.
- Parse nested `0.3` inline tables directly in `drift/model` (depth <= 32).
- Add Enterprise `sweep --flow --pacts` fleet conservation laws, `composition-manifest/1` `pact_refs`, MIT `drift_verify.py` pact parity.
- Add `0.3` bilateral contractual equalizer (`drift pact`, `init --pact`, `drift.pact-offer/1`, `drift.pact-lock/1`, `--pact-lock`).
- Decode inline Avro records and Multi-Format Schema Objects in `--asyncapi`/`--epoch-manifest` with writer/reader-default rules, rejecting unknown `+json` formats.
- Replace `crates-io-auth-action@v1` in `publish.yml` with annotation-clean OIDC exchange, `CARGO_REGISTRY_TOKEN` fallback, token revocation, and `setup-java@v6`.
- Emit bare Java `#method` anchors in `sweep sync-scope` (accepting `#Class.method` in `check`), count `[invariants]` in `unused_vocab`, and omit unbounded OpenAPI params.
- Require `--deployment` on `--from-signal`, allow stale `approve --reviewed`, replace `.sig` in `--ssh-sign`, enforce proof floors in `prove`, and clarify `eval --help`.
- Skip gitignored `:(exclude)` paths in JVM/JS/Python snapshots for `-Ddrift.changed=auto` and expose `-Ddrift.mutants.{when,budget}` in `GateMojo`.
- Fix public `verify.yml` Free-tier `gate --explain` self-stub check, `[requires]` profile append, and Node 24 `setup-java@v6`/`setup-node@v7`/`setup-python@v7` actions.

## 0.6.0

- Release `0.6.0`.
- Package `drift-notify-wsl.sh` and `notification` hook entries in release archives, sync `0.6` CLI docs, and harden public changelog sanitization.
- Add `0.3` clean-room specification grants (`export grant`, `init --grant`, `drift.grant-lock/1`, `--grant-lock`, MIT `drift_verify.py` parity).
- Precompute Profile03 canonical schemas, projections, unit pairs, and scope requires, and share unmodified norm_cases in 0.3 digest/resolved views.
- Cache dev/prod CLI builds separately (.build/drift.{dev,prod}), propagate PROD to sub-makes, and restage across mode/BUILD switches without recompiling.
- Harden JS template/regex, Rust nested-comment/raw-string, and multi-line Python import/heal scanners, and optimize subsumed_code_glob_map to O(N*|U|).
- Harden symbolic scope slicing across multi-line headers, inline/leading attrs, receiver homonyms, ordered imports_only preambles, and broad forbid_imports.
- Use checked i64 pivot/merge math in integer polytopes and pass -ffp-contract=off on -prod C builds to prevent near-2^53 rounding and cross-arch FMA drift.
- Keep unknown hook events inert, check polyglot untracked dirs on Stop, and pipe drift.attention/1 to WSL2 in-place Toasts.
- Close `explain` over runtime reasons and envelopes (`--example`), add `init --graduate`, `case --unbound-vocab`, and `doctor` checks.
- Target Java 17 in JVM bridges, skip unadopted reactor modules, add `session.json` fallback, and use `.plan.json` stubs.
- Isolate `sweep` surface staleness per namespace, index Scala basenames in O(1), and load Owned reachable closures.
- Add 3-way relational F2P verdict, batch non-vacuity, and `proof.f2p_regressed` to `gate --compare-before`.
- Unify SweepRootContext/import caches across sweep --root --flow, use O(log N) V/Rust prefix lookup, and parallelize sweep source I/O & SHA-256 pins.
- Parallelize show --out / export views, compiled .plan.json emission, batch mutants generation, fmt / fmt --diff, and pre-warm status/approve.
- Stage only diffed Git baseline blobs, fix O(N^2) gate inventory replay, add header-only batch recall, and run conformance with -gc none.
- Support '#' comments in DirectParser, replace recall token maps with 64-bit masks, parallelize gate verdicts, and add v1/v2 slab inventories.
- Parallelize CLI contract batches and large JSONL shards, stack-sort small JCS maps, add lean prepare_recall, and isolate Surefire test dirs.
- Streamline 0.3 proof/check/verifier hot paths, compact ObsValue/Event maps, shard conformance, and add chk03/proof03+obs bench lanes.
- Clamp DRIFT_EDITION to compiled edition tier, fail-close export_public.py, fix Boehm GC C codegen, and fix array/object stub type hints.
- Thin polyglot bridges onto `.plans/<id>.plan.json` interpreters with zero `drift` CLI in CI/CD, cut >1,600 LOC.
- Synthesize projected `then` stubs, desymmetrized peers, and 2-skeleton variants in `obs_stub.v` and `bridge_suite_plan.v`.
- Compile `0.2`/`0.3` contracts into `.plans/<id>.plan.json` (`drift.bridge-plan/1`) in `show --out` and `export views`.
- Add `fmt --diff` (`pure_read`, unified diff, exit 1 on a difference), `merge --out FILE|-`, `export views|boundary --out -` and atomic `export views --out DIR` staging.
- Add `version --json|--as json` and `explain --list [codes|reasons|checks|operators] [--json]`; `explain <code> --json` prints one entry; plain `version`/`explain` text stays.
- Add `mutants --detail summary` (an `operators: <op>=<count>` line) and `stats --since <ref>` with `--detail summary` (provenance line, radar table, churn).
- List contracts with coarsened obligations first in multi-contract `review` summaries and non-delta `md`; hint `--base HEAD` on directory summaries without `--base`.
- Ship `schemas/drift-boundary-0.3.schema.json`, checked by `make schema-check` against exported bundles; document `diff <a|ref|approved> <b>` in the synopsis.
- Print `verify offline: python3 verifier/drift_verify.py ...` last in the text of `gate --attest`; test `merge` approval safety and `recall sync` on partial checkouts.
- Align `0.3` cause and fix text of codes in the diagnostic catalogue; audit all 29 codes against emission and `explain` (DR-E002, DR-E003, DR-E105, DR-E209, DR-E406, DR-E601, DR-E701, DR-E702).
- Lint `drift` invocations in docs, skills and hooks against the option registry; fix the guide `select --plan --cmd` and Pro/Enterprise cold-review commands.
- Resolve 0.3 schema pointer projections in peer checks and close transitive order stars in partitions and `check`.
- Add `drift plan --pack speculative` and position-independent `content_ref` pack fencing across `plan` and `gate`.
- Heal unowned top-level symbols in `#<symbol>`-partitioned files during `drift sweep sync-scope` via unique intra-file caller fixed-point attribution.
- Add paired `verify_slots`/`verify_pct` pool queues to `drift plan --staffing` and `--staffing` slot locks in `scripts/proof_events.py`.
- Add `drift eval <file|id>#<case> --observation FILE|-` (Free, `pure_read`): judge `drift.observation/1` envelopes with the kernel oracle; exit 0, 1 or 2, no proof event.
- Re-judge `observations` of `0.3` proof events in `prove` and `gate`: a violated or inconclusive one turns a passed event red for its case; malformed ones are `DR-E701`.
- Add `eval` as a `cli` command to the `69-command-coverage-status` golden, as `drift eval` joins the command catalogue.
- Close symmetric star `eq_field` equivalences in bounded partitions, `--when` mutants, `check`, and poset tightening.
- Render multi-option choice trade-offs, speculative picks, consumer impacts, and relaxation witnesses in `review --as md`.
- Validate `--as` and `--detail` in one place: an unsupported value exits 2 with `--as <v> is not supported by <command>; supported: <list>`; `--as json` equals `--json`.
- Accept `--as text|json` on `check`, `diff`, `prove`, `mutants`, `select`, `stats`, `impact`, `plan`, `recall`, `sweep` and `doctor`, and `--detail full` on `prove`.
- Add `summary` to the formats of `status`, `gate` and `review`, `text` and `md` to `show`, and `guided` to the details of `plan` in `drift help --json`.
- Print the effective cases (own, inherited, waived, deferred) and invariants of a contract as a table with `drift show <contract> --as text|md`; JSON stays the default.
- Resolve a target that is no path as a contract `<id>` or profile `<name>@<N>` of the nearest area; an unknown word exits 2 with a near-name hint.
- Narrow `show`, `prove --explain` and `gate --explain` to one case with `<id>#<case>`; the verdict and exit status stay whole; other commands exit 2.
- List the contracts that are not green first in the directory text of `prove` and `gate` and fold green ones into `green: <N> contract(s)`; `--detail full` lists all.
- Add `drift doctor [<dir>] [--json]` (Free, `pure_read`): one ok/warn/fail line per check of edition, config, profiles, contracts, events and hooks; exit 1 only on a fail.
- Add `drift completion <bash|zsh|fish|pwsh>` (Free, `pure_read`): a static script generated from the option registry of the active edition.
- End a text run with a `DR-E401` finding with one `hint: profiles in <dir>: <refs>` line (or `none; create one with drift new <dir>/<name>@<N>.toml`); `--json` unchanged.
- Follow a `DR-E603` finding of `drift approve` with `hint: approvers in <config>: <names>`; exit status 1 unchanged.
- Scaffold a minimal profile with `drift new <dir>/profiles/<name>@<N>.toml`; it checks clean, never overwrites (exit 2) and takes no contract options.
- Read the events of `status`, `prove`, `gate` and `select` from `[area] events` of the area config when `--events` and the state dir give none; reject absolute and `..` paths.
- Open the text of `status`, `prove`, `gate` and `select` with `events: <path> (<source>)` and add `events_source` to their `--json` (not `status`) unless `--events` is given.
- Name the resolved events path in the guided `next_command` instead of `--events <events-dir>` when events resolve.
- Name the shard, line, contract and expected and found digests of each `events.other_digest` event in `select --explain`, and list them as `other_digest_events`.
- Answer `impact --schedule`, `impact --recall`, `sweep --recall` and `new --area` with exit 2 and `was replaced by drift plan|recall query|recall sync|init`, not in help.
- Reject `new --epoch-manifest` and `sweep --from-intent`, which were accepted and ignored, as unknown options.
- Make `drift fmt --upgrade 0.3` write all files or none (exit 1 on a finding) and end with `removed <N> approval(s); review and approve the upgraded files again`.
- Write the profile of `drift sweep --openapi F --scaffold-profile P` only with `--apply`; without it print `would write P`; `sweep check` accepts `--apply`.
- Make the legacy `drift sweep <dir> --root R --sync-scope` preview like `sweep sync-scope` and write only with `--apply`.
- Declare `recall.sync` as `writes_digest_preserving` instead of `writes_ephemeral` in `drift help --json`, and resolve each invocation's effect class from its options.
- Add `; did you mean "<hint>"?` to the first stderr line of an unknown command, subcommand, option or `explain` code with a near name; nothing is run, exit status stays 2.
- Print `Options:` and `Exit status:` sections after the usage lines of `drift <command> --help`, `-h` and `help <command>`, listing every accepted option; usage lines kept.
- Read `--name=value` like `--name value` for every valued option, reject `--switch=value` with `--<name> takes no value`, and end option parsing at a bare `--`.
- Print an `external reads:` line before the text `checks:` line of a sweep that counts external reads, pointing to the `resource.external_read` explain reason; JSON unchanged.
- Open `drift plan` text with its schedule block under a `weights:` line stating the unit of `w`, before the contract and lane lines; JSON unchanged.
- Name `drift sweep sync-scope --root <dir> --apply` instead of the legacy `--sync-scope` flag in the `code.undeclared` remedy shown by `drift explain`.
- Print a `fix: <reason>: <remedy>` line after each not-green gate text verdict, one per distinct catalogue reason; JSON, junit, summary and guided unchanged.
- Print a `checks:` line before the text `sweep ok|not ok` total, naming the check families that ran and the ones skipped for lack of their option; JSON unchanged.
- Print a `merged by:` line under each cluster group and one `what-if cut` line per cut after the totals in `drift plan` text, JSON unchanged.
- Add `drift plan --staffing FILE` and `schedule.staffing`: agent-pool sizing by makespan plus spawn cost under caps and remote handoff.
- Orient colored mutex components in `impact --schedule` by a deterministic weighted portfolio and local search, kept only on strict improvement.
- Contract only the read-after-write cycle inside a mutex component in `impact --schedule`; the rest stays colored.
- Make `list_schedule_makespan` work-conserving so `max_workers` and `what_if` makespans never idle a worker while a group is ready.

## 0.5.1

- Structure dense capability prose into scannable tables/bullets in `GUIDE*.md` and `EDITIONS.md`, clarify `Linux & macOS` paths in `INSTALL*.md`, and refine `README.md` wording.
- Align `INSTALL*.md` JDK 25 source-build deps, `EDITIONS.md` gated flags, `SECURITY.md` version bump, public changelog sanitization, and automated doc-parity checks.
- Bundle OS-aware CLI bootstrap scripts (`scripts/install-cli.{sh,ps1}`) in packaged skills for `skills.sh` installs and auto-fetch Windows archives on clone.
- Build the JVM plugin id from the same tag-aware `git describe --tags` as the Makefile `REV`, so a lightweight release tag names it.
- Point the Stop hook's unmatched-code remedy at `drift sweep sync-scope --root <area> --apply` instead of the legacy `--sync-scope` flag.
- Make the README bootstrap quickstart run from an empty directory with the owner as first approver and the example profile.
- Derive the build `REV` from the nearest Git tag of any kind, so a lightweight release tag names the installed build.
- Make the `DR-E105` explanation cover every case, decision, invariant, parameter, projection, concept and predicate collision (DR-E105).
- Reject unknown single-dash options and `drift version` arguments with exit 2, keeping the `recall query` negation expression valid.
- Let `drift mutants --out -` stream the complete manifest to standard output instead of creating a file named `-`.
- Fix guided text, Markdown and next-action views to render only existing `findings`, so a contract entry without them shows no phantom finding.
- Fix README tier-label rendering; align docs with schema `0.3`, dual seals, profile setup, diagnostics, proof states, and offline-install boundaries.
- Close `0.3` empty invariant/peer meet (`in` $\sqcap$ `min`/`max`), lock concurrent approval/recall/ops writes, verify 180 conformance obligations, and test threats 6–8 (DR-E003, DR-E105).
- Upgrade `central-publishing-maven-plugin` to `0.12.0` to strip `maven-metadata-local.xml` and `_remote.repositories` from Maven Central bundles.
- Release `0.5.1`.
- Harden `0.3` constraint algebra (unit-aware meet/refinement, `not_in`/UTF-8 codepoint lengths, `assurance_ref` simulation, `fmt --upgrade`, `mutants`, bridges, and small-model/ASan/fuzz checks).
- Fix `0.3` guard target globs, `ObsValue` `series`/`contains`, transitive `peer`/unit closures, exempt-case isolation, `extends`/invariant refinement, and upstream owner keys (DR-E105).
- Harden schema `0.3` across `stats`, `approve`, `review`, `sweep`, `merge`, `new`, `drift_verify.py`, and bridges (`dr2b`/`dr2a`, `bind.*`, `scenario`, `ConstraintExpr`).
- Add `.github/workflows/publish.yml` (crates.io OIDC & Maven Central `io.github.rad-ox`) and `make setup-github-env` for zero-local-secret GitHub Environment setup.
- Add the complimentary Open-Source Maintainer Grant for DRIFT Enterprise in `LICENSE` Part III, `EDITIONS.md`, `README.md`, and `SUPPORT.md`.
- Switch Maven `groupId` to `io.github.rad-ox` across POMs, installers (`install.sh`, `install.ps1`), skills, and docs for Maven Central readiness.
- Showcase standout Free → Pro → Enterprise capabilities in `README.md`/`GUIDE*.md`/`EDITIONS.md`, add `skills/drift/` export for `skills.sh`, and add POM/Cargo metadata.
- Add `type = "any"` polymorphic `0.3` predicates, `dr1`-preserving `0.3`->`0.2` profile projection, and migrate `.drift/profiles/*.toml` and initial contracts to `0.3`.
- Align `bridges/rust/Cargo.toml` license to `MIT`, add Part III Pro/Enterprise terms to `LICENSE`.
- Add `0.3` JSON Schema projections (`drift-{contract,profile,config,proof-event}-0.3.schema.json`) in `schemas/` alongside `0.2`.
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
- Scaffold contracts from runtime JSONL traces in `new --from-upstream`, add contract-free bridge `observe()`, and enforce `DR-E602` in `drift_verify.py` (DR-E602).
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
