# Integrate first

Read when a request bundles behaviour with an experiment (an eval or benchmark
campaign), or when execution is authorized. These rules move the first full
feedback forward; they add no owner stop.

- Feature, proof infrastructure and experiment are separate slices. Draft the
  feature contract alone (declaring deterministic `[assurance]` resource or
  symbol-exclusion bounds with the slice when cost or fast-path behavior
  matters); plan exploratory campaigns as a later slice that starts after the
  feature gate is green.
- Bind tests before implementing and run them once: the expected reasons are
  failing tests, not missing events.
- From the first integrated commit, start the area's full check (its CI
  command) in the background and keep working; do not leave it to closure.
- An expansion the owner pre-authorized with a condition (for example the
  full campaign after a passing probe) proceeds when the condition holds,
  without a new stop.
- Keep full command logs in files and report targeted excerpts.
- Incremental `--base` reuse trusts recorded `.meta.json` `inputs`: record
  external test fixtures in `inputs` or `scope.code`/`scope.sources`, else
  rerun affected tests.
- Inspect `unverified_surface` and `oracle_discrimination` via
  `drift gate ... --explain` before claiming full/release coverage (`deferred`
  and `waived` cases stay unverified).
- When a slice adds an indexed fast-path over a valid fallback or rejects
  saturated inputs, discriminate it via `[assurance.budgets.<id>]`,
  `[assurance.guards].forbid_touched`, or `L3` causal coupling rather than
  return-value assertions alone, and declare `writes = []` on rejection cases.
- For manual-memory or native FFI targets (C/C++/Rust/V), pass sanitizer build
  flags (`-O0 -fsanitize=address,leak,undefined` with fail-closed
  `ASAN_OPTIONS`/`LSAN_OPTIONS`/`UBSAN_OPTIONS`) through the configured runner
  command so both production libraries and test binaries are instrumented.
- Client interaction, protocol negotiation and recovery:
  [native-flow.md](native-flow.md).
