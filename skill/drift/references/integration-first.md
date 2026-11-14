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
- Client interaction, protocol negotiation and recovery:
  [native-flow.md](native-flow.md).
