---
name: drift
description: Drafts, checks and proves DRIFT behaviour contracts (one TOML file per slice under .drift/contracts) and binds their cases to tests through the DRIFT gate. Use when work in an area with .drift/config.toml adds or changes intended behaviour, when its gate or proof needs attention, or when the user names DRIFT for an area without it. Do not use to approve contracts on behalf of the owner.
---
One contract per slice, `.drift/contracts/<id>.toml`, states intended behaviour with profile predicates.
## Workflow
1. **Adopt**: If `.drift/config.toml` is absent and DRIFT was named, adopt with [references/adoption.md](references/adoption.md).
2. **Draft**: Run `drift new <file> [--from <sibling.toml> | --profile <ref>] [--code <path>...]`. Write concrete `then` values at `at` levels; fill `[scope]` and `[open.<id>]`.
3. **Check & Review**: Run `drift fmt <file>`, `drift check <file> --json`, and `drift review <file> --brief`. Wait for explicit owner approval before `drift approve <file> --by <owner>`.
4. **Prove**: Bind tests ([references/jvm-bridge.md](references/jvm-bridge.md), [references/integration-first.md](references/integration-first.md)), run tests, and verify with `drift gate`.
