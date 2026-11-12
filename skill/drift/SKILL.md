---
name: drift
description: Drafts, checks and proves DRIFT behaviour contracts (one TOML file per slice under .drift/contracts) and binds their cases to tests through the DRIFT gate. Use when work in an area with .drift/config.toml adds or changes intended behaviour, when its gate or proof needs attention, or when the user names DRIFT for an area without it. Do not use to approve contracts on behalf of the owner.
---
One contract per slice, `.drift/contracts/<id>.toml`, states intended behaviour with profile predicates.
## Workflow
0. **CLI**: If `drift` is not on `PATH` (for example after `npx skills add rad-ox/drift`), run `sh <skill-dir>/scripts/install-cli.sh` on Linux/macOS or `powershell -NoProfile -ExecutionPolicy Bypass -File <skill-dir>/scripts/install-cli.ps1` on Windows to download, SHA-256-verify, and install the matching OS release.
1. **Adopt**: If `.drift/config.toml` is absent and DRIFT was named, adopt with [references/adoption.md](references/adoption.md).
2. **Draft**: Run `drift new <file> [--from <sibling.toml> | --profile <ref>] [--code <path>...]`. Write concrete `then` values at `at` levels; fill `[scope]` and `[open.<id>]`.
3. **Check & Review**: Run `drift fmt <file>`, `drift check <file> --json`, and `drift review <file> --brief` ([references/native-flow.md](references/native-flow.md)). Wait for explicit owner approval before `drift approve <file> --by <owner>`.
4. **Prove**: Bind tests ([references/jvm-bridge.md](references/jvm-bridge.md), [references/integration-first.md](references/integration-first.md)), run tests, and verify with `drift gate` (inspect `unverified_surface` with `drift gate ... --explain` before claiming full coverage; exempt cases remain unverified).
