# Adopting DRIFT in an area

Read when the area has no `.drift/config.toml` and the owner named DRIFT, even
as an option: naming it is the choice to adopt. Follow the steps, then report
the four impacts with the approval request.

## Impacts to report

- Files: `.drift/config.toml`, one profile per kind of surface and one
  contract per slice, all under version control; the owner approves the
  configuration and every contract.
- Tests: a tagged test reads its expected values through `Drift.expect` and
  needs the resolved view exported before it runs, or it fails; the DRIFT
  Maven plugin exports it. Untagged tests run as before.
- Build: `drift:drift-junit` and `drift:drift-maven-plugin` live only in
  local Maven repositories ([jvm-bridge.md](jvm-bridge.md)). A build that
  resolves from a remote repository, such as CI or a mirror, cannot compile
  tagged tests until both are published there; when that is not possible,
  offer a local branch.
- Gate: the `drift` CLI must be installed where the gate runs; with the
  plugin, `mvn verify` fails when the gate is not green.

## Steps

1. Create `.drift/config.toml` (or initialize an external shadow area outside a read-only/shared repository with `drift init <owner> <repo> --state-dir <state-dir>` and `DRIFT_STATE_DIR=<state-dir>`, which writes `<state-dir>/.drift/config.toml` and `<state-dir>/shadow.toml` without touching the repository worktree or `.git`); it needs one table besides `[approval]`:

   ```toml
   drift = "0.2"
   kind = "config"

   [area]
   owner = "<owner>"
   ```

2. Create one profile per kind of surface, `.drift/profiles/<name>@1.toml`
   (or compose base profiles with `extends = ["http@1", "ui@1"]` and add
   slice-specific predicates in the contract's `[use.vocabulary]`):
   `kit = "drift-junit"` on the JVM (`drift-node` on Node.js, `drift-pytest`
   on Python), `vocabulary.when` for what a test sets up, `vocabulary.then`
   for what it can observe, and `[requires]` for scope values every contract
   on that surface must hold, such as `writes = []` for a surface that never
   writes.
3. Write the contracts with workflow steps 2 to 4. When execution is
   authorized, wire the runtime bridge ([jvm-bridge.md](jvm-bridge.md):
   `drift-junit` + `drift-maven-plugin` on Maven, `bridges/drift.mjs` on
   Node.js, or `bridges/drift.py` on Python), then bind and
   run the tests before asking for approval: the digest excludes
   `[approval]`, so the events stay valid after it.
4. Ask one approval for the configuration and the contracts together, stating
   the four impacts. On approval run `drift approve .drift --by <owner>`, then
   the gate.
5. For concurrent branches, add `.drift/**/*.toml merge=drift` to
   `.gitattributes` and set `git config merge.drift.driver "drift merge %O %A %B"`
   so three-way merges never conflict on `[approval]`.

## Report format

After adopting DRIFT in this turn, put first:

```text
adopted: <area> · configuration and contracts await the owner's approval
impacts: files · tests · build · gate, one line each from the impacts above
```

## Gotchas

- Line endings never matter: with `core.autocrlf` the digest, the approval
  and `drift fmt --check` are unaffected.
