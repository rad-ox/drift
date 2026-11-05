---
name: drift
description: Drafts, checks and proves DRIFT behaviour contracts (one TOML file per slice under .drift/contracts) and binds their cases to tests through the DRIFT gate. Use when work in an area with .drift/config.toml adds or changes intended behaviour, when its gate or proof needs attention, or when the user names DRIFT for an area without it. Do not use to approve contracts on behalf of the owner.
---

# DRIFT (Free Edition)

One contract per slice, `.drift/contracts/<id>.toml`, states intended behaviour with profile predicates. The owner approves one version, and the gate is green only when tests pass against that version.

## 1. Adoption gate (always first)
- If `.drift/config.toml` is absent and DRIFT was not named: STOP.
- If absent and DRIFT was named: adopt with [references/adoption.md](references/adoption.md).

## 2. Lane
- **Behaviour unchanged on covered code**: update code, rerun bound tests, and run `drift gate`.
- **New or changed behaviour**: go to Draft, Check, and `drift review <file> --brief`, wait for owner approval, and seal with `drift approve <file> --by <owner>`.
- **Experiments or authorized execution**: read [references/integration-first.md](references/integration-first.md).

## 3. Draft
1. Read `[use].profile` predicates (`vocabulary.when` and `vocabulary.then`).
2. Run `drift new <file> [--from <sibling.toml> | --profile <ref>] [--code <path>...]`. Never copy `[approval]`.
3. Write concrete `then` values at `at` levels; fill `[scope]` from causal evidence; record gaps as `[open.<id>]`.

## 4. Check & 5. Review
Run `drift fmt <file>`, `drift check <file> --json`, and `drift review <file> --brief`. Show cases, cards, and at most five questions, then WAIT for explicit owner approval before `drift approve <file> --by <owner>`.

## 6. Prove
Bind each test (`@DriftCase` + `Drift.expect` on JVM, `runDriftCase` in JS, `run_drift_case` in Python; see [references/jvm-bridge.md](references/jvm-bridge.md)), run tests, and verify with `drift gate`.
