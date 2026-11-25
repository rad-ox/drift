# DRIFT CLI Reference

> Generated from the DRIFT CLI option registry (`drift <command> --help`).
> For edition entitlements, sibling binary delegation, and `DRIFT_EDITION`, see **[EDITIONS.md](../EDITIONS.md)**.

## Exit Status Convention

- **`0`** — OK / Gate green / No differences.
- **`1`** — Static findings, formatting differences, review blockers, or gate not green.
- **`2`** — Usage, unknown option, tier entitlement, or I/O error (all files left untouched).

## Command Index

| Command | Tier | Synopsis |
|---|---|---|
| [`drift check`](#drift-check) | **Free** | `drift check <file\|dir>... [--profiles DIR] [--json]` |
| [`drift status`](#drift-status) | **Free** | `drift status [<file\|dir>...] [--events FILE\|DIR...] [--profiles DIR] [--config FILE] [--json \| --as summary]` |
| [`drift show`](#drift-show) | **Free** | `drift show [<file\|dir>...] [--as json\|text\|md] [--out DIR] [--profiles DIR]` |
| [`drift export`](#drift-export) | **Free** | `drift export views [<file\|dir>...] --out DIR [--profiles DIR]` |
| [`drift fmt`](#drift-fmt) | **Free** | `drift fmt <file\|dir>... [--check] [--sync-vocab] [--profiles DIR]` |
| [`drift diff`](#drift-diff) | **Free** | `drift diff <a\|ref\|approved> <b> [--json]` |
| [`drift approve`](#drift-approve) | **Free** | `drift approve <file\|dir>... --by OWNER [--at TIME] [--pin-sources] [--profiles DIR]` |
| [`drift explain`](#drift-explain) | **Free** | `drift explain <code>` |
| [`drift version`](#drift-version) | **Free** | `drift version` |
| [`drift review`](#drift-review) | **Free** | `drift review <file\|dir>... [--brief] [--base <file\|dir\|ref> [--delta]] [--upstream FILE\|DIR...] [--profiles DIR] [--base-profiles DIR] [--events FILE\|DIR...] [--as json\|md\|summary]` |
| [`drift new`](#drift-new) | **Free** | `drift new <file> [--profile REF] [--from FILE \| --openapi FILE \| --from-upstream FILE\|DIR [--resource RES] \| --from-recall ID] [--code PATH...] [--intent TEXT] [--profiles DIR]` |
| [`drift init`](#drift-init) | **Free** | `drift init <owner> [dir] [--observed] [--taplo]` |
| [`drift case`](#drift-case) | **Free** | `drift case add <file> [<id>] [--case ID --ask TEXT [--blocks PHASE] \| --from-intent] [--profiles DIR]` |
| [`drift prove`](#drift-prove) | **Free** | `drift prove <file\|dir>... --events FILE\|DIR... [--at LEVEL...] [--mutants FILE --mutation-events DIR] [--base FILE\|DIR\|REF] [--changed FILE...] [--changed-list FILE...] [--changed-none] [--explain] [--test-classes DIR] [--profiles DIR] [--json]` |
| [`drift gate`](#drift-gate) | **Free** | `drift gate <file\|dir>... --events FILE\|DIR... [--at LEVEL...] [--phase execution\|release] [--mutants FILE --mutation-events DIR] [--base FILE\|DIR\|REF] [--changed FILE...] [--changed-list FILE...] [--changed-none] [--compare-before FILE] [--upstream FILE\|DIR...] [--explain] [--attest FILE] [--test-classes DIR] [--profiles DIR] [--config FILE] [--as junit\|summary\|md \| --json]` |
| [`drift run`](#drift-run) | **Free** | `drift run [--events DIR] [--gate] [--state-dir DIR] [--profiles DIR] [--config FILE] -- <cmd> [args...]` |
| [`drift eval`](#drift-eval) | **Free** | `drift eval <file\|id>#<case> --observation FILE\|- [--profiles DIR] [--as text\|json \| --json]` |
| [`drift map`](#drift-map) | **Free** | `drift map [<file\|dir>] [--view cases\|flow\|state] [--focus REF...] [--depth N] [--max-nodes N] [--skip N] [--flow] [--what-if FILE]... [--as text\|json\|mermaid \| --json] [--profiles DIR]` |
| [`drift doctor`](#drift-doctor) | **Free** | `drift doctor [<dir>] [--json]` |
| [`drift hook`](#drift-hook) | **Free** | `drift hook <session\|prompt\|stop\|notify>` |
| [`drift completion`](#drift-completion) | **Free** | `drift completion <bash\|zsh\|fish\|pwsh>` |
| [`drift select`](#drift-select) | **Pro** | `drift select [<base>] <file\|dir> --events FILE\|DIR... [--base FILE\|DIR\|REF] [--changed FILE...] [--changed-list FILE] [--changed-root DIR] [--upstream-base FILE\|DIR [--upstream FILE\|DIR...]] [--area DIR] [--profiles DIR] [--files] [--explain] [--json]` |
| [`drift impact`](#drift-impact) | **Pro** | `drift impact [<file\|dir\|code>...] [--resource RES...] [--writes RES...] [--reads RES...] [--code PATH...] [--source TEXT...] [--surface TEXT...] [--profile REF...] [--owner OWNER...] [--query TEXT...] [--top N] [--toc] [--transitive] [--depth N] [--upstream FILE\|DIR...] [--profiles DIR] [--json]` |
| [`drift plan`](#drift-plan) | **Pro** | `drift plan [<file\|dir>...] [--events FILE\|DIR...] [--pack GROUP\|ready\|all\|speculative] [--overlaps compact\|pairs] [--staffing FILE] [--upstream FILE\|DIR...] [--profiles DIR] [--json]` |
| [`drift recall`](#drift-recall) | **Pro** | `drift recall query <expr> [<file\|dir>...] [--share] [--profiles DIR] [--json]` |
| [`drift pact`](#drift-pact) | **Pro** | `drift pact offer [<file\|dir>...] --policy FILE --pact-id ID --counterparty AREA --role ROLE [--area NAME] [--authorized-key KEY...] [--out FILE \| --dry-run] [--ssh-sign FILE] [--profiles DIR] [--json]` |
| [`drift merge`](#drift-merge) | **Pro** | `drift merge <base> <ours> <theirs>` |
| [`drift mutants`](#drift-mutants) | **Enterprise** | `drift mutants [<file\|dir>...] --out FILE [--cases ID...] [--base FILE\|DIR\|REF] [--changed [FILE]...] [--changed-list FILE...] [--changed-root DIR] [--when] [--budget N [--events FILE\|DIR...]] [--profiles DIR] [--json]` |
| [`drift stats`](#drift-stats) | **Enterprise** | `drift stats <file\|dir>... [--profiles DIR] [--events FILE\|DIR...] [--reports FILE...] [--ops FILE...] [--compare LABEL=FILE...] [--root DIR --changed-list FILE] [--json]` |
| [`drift sweep`](#drift-sweep) | **Pro / Enterprise** | `drift sweep <file\|dir>... [--root DIR] [--openapi FILE [--scaffold-profile FILE]] [--upstream FILE\|DIR...] [--promote] [--flow [--pacts FILE\|DIR...]] [--simplify [all\|hygiene\|epistemic]] [--apply] [--sync-scope] [--profiles DIR] [--json]` |

---

## Commands

### `drift check`

**Tier:** Free

```text
drift check <file|dir>... [--profiles DIR] [--json] [--help | -h]

Options:
  --profiles DIR   profile directory (default: nearest .drift/profiles)
  --json           print JSON instead of text
  --state-dir DIR  keep area state in DIR outside the repository (shadow mode)
  --as FORMAT      output: text or json

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift status`

**Tier:** Free

```text
drift status [<file|dir>...] [--events FILE|DIR...] [--profiles DIR] [--config FILE] [--json | --as summary] [--help | -h]

Options:
  --events FILE|DIR...    proof events (*.jsonl files or directories)
  --profiles DIR          profile directory (default: nearest .drift/profiles)
  --config FILE           area config (default: nearest .drift/config.toml)
  --json                  print JSON instead of text
  --as FORMAT             output: text, json or summary
  --detail LEVEL          detail level: full, summary or guided
  --previous-guided FILE  earlier guided output to continue (needs --detail guided)
  --state-dir DIR         keep area state in DIR outside the repository (shadow mode)

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift show`

**Tier:** Free

```text
drift show [<file|dir>...] [--as json|text|md] [--out DIR] [--profiles DIR] [--help | -h]

Options:
  --as FORMAT      output: json (default), text or md
  --detail LEVEL   detail level: full
  --out DIR        write one JSON view per contract into DIR
  --profiles DIR   profile directory (default: nearest .drift/profiles)
  --state-dir DIR  keep area state in DIR outside the repository (shadow mode)
  --boundary       export the boundary of the area instead of a view [Pro]
  --area NAME      area name (with --boundary) [Pro]
  --openapi FILE   OpenAPI document (with --boundary) [Pro]
  --asyncapi FILE  AsyncAPI document [Pro]
  --wsdl FILE      WSDL document [Pro]
  --copybook FILE  COBOL copybook [Pro]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift export`

**Tier:** Free

```text
drift export views [<file|dir>...] --out DIR [--profiles DIR] [--help | -h]
drift export boundary [<file|dir>...] --out FILE [--area NAME] [--openapi FILE] [--profiles DIR] [--help | -h]
drift export grant [<file|dir>...] --policy FILE [--out DIR | --dry-run] [--ssh-sign FILE] [--profiles DIR] [--json] [--help | -h]

Options:
  --out DIR|FILE   output: a directory for views, a file for boundary
  --profiles DIR   profile directory (default: nearest .drift/profiles)
  --state-dir DIR  keep area state in DIR outside the repository (shadow mode)
  --area NAME      area name [Pro]
  --openapi FILE   OpenAPI document [Pro]
  --asyncapi FILE  AsyncAPI document [Pro]
  --wsdl FILE      WSDL document [Pro]
  --copybook FILE  COBOL copybook [Pro]
  --policy FILE    grant redaction and source policy file [Pro]
  --dry-run        verify and print the egress manifest without writing [Pro]
  --ssh-sign FILE  sign grant.lock.json with an OpenSSH key [Pro]
  --json           print JSON instead of text [Pro]
  --as FORMAT      output: text or json [Pro]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift fmt`

**Tier:** Free

```text
drift fmt <file|dir>... [--check] [--sync-vocab] [--profiles DIR] [--help | -h]

Options:
  --check          report files that need formatting, change nothing
  --diff           print unified diff of formatting changes without writing
  --sync-vocab     sync the profile vocabulary into the contracts
  --profiles DIR   profile directory (default: nearest .drift/profiles)
  --state-dir DIR  keep area state in DIR outside the repository (shadow mode)

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift diff`

**Tier:** Free

```text
drift diff <a|ref|approved> <b> [--json] [--help | -h]

Options:
  --json           print JSON instead of text
  --state-dir DIR  keep area state in DIR outside the repository (shadow mode)
  --as FORMAT      output: text or json

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift approve`

**Tier:** Free

```text
drift approve <file|dir>... --by OWNER [--at TIME] [--pin-sources] [--profiles DIR] [--help | -h]
drift approve --reviewed FILE --expect-review REF --by OWNER [--at TIME] [--profiles DIR] [--help | -h]

Options:
  --by OWNER           approving owner
  --at TIME            approval time (UTC)
  --pin-sources        pin the digest of each bound source
  --reviewed FILE      review snapshot to approve
  --expect-review REF  sha256 reference the snapshot must match
  --ssh-sign FILE      sign the approval with an OpenSSH key (with --reviewed)
  --profiles DIR       profile directory (default: nearest .drift/profiles)
  --state-dir DIR      keep area state in DIR outside the repository (shadow mode)

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift explain`

**Tier:** Free

```text
drift explain <code> [--help | -h]

Options:
  --list [CATEGORY]  list codes, reasons, checks, operators or envelopes
  --example          print a minimal valid example of an envelope
  --json             print JSON instead of text
  --as FORMAT        output: text or json

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift version`

**Tier:** Free

```text
drift version [--help | -h]

Options:
  --json       print JSON instead of text
  --as FORMAT  output: text or json

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift review`

**Tier:** Free

```text
drift review <file|dir>... [--brief] [--base <file|dir|ref> [--delta]] [--upstream FILE|DIR...] [--profiles DIR] [--base-profiles DIR] [--events FILE|DIR...] [--as json|md|summary] [--help | -h]

Options:
  --brief                 short review of what changed
  --as FORMAT             output: json, packet, summary or text (md needs Pro)
  --tier 0|1|2            decision packet projection tier for --as packet (default: 2)
  --detail LEVEL          detail level: full, summary or guided
  --previous-guided FILE  earlier guided output to continue (needs --detail guided)
  --profiles DIR          profile directory (default: nearest .drift/profiles)
  --state-dir DIR         keep area state in DIR outside the repository (shadow mode)
  --base FILE|DIR|REF     baseline to compare with (a path or a git ref) [Pro]
  --delta                 show only what changed since --base [Pro]
  --base-profiles DIR     profile directory of the baseline [Pro]
  --events FILE|DIR...    proof events (*.jsonl files or directories) [Pro]
  --upstream FILE|DIR...  upstream contracts or profiles [Pro]
  --max-items N           maximum items in --as digest output (default: 20) [Pro]
  --rho FLOAT             owner attention load rho for --as digest backpressure [Pro]
  --measurements FILE     performance measurement bundle [Pro]
  --subject FILE          binary subject the measurements describe [Pro]
  --subject-artifact REF  artifact reference of the measured subject [Pro]
  --subject-tree DIR      source tree of the measured subject [Pro]
  --run-id ID             identifier of the measured run [Pro]
  --security-lock FILE    security lock receipt to reuse [Pro]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift new`

**Tier:** Free

```text
drift new <file> [--profile REF] [--from FILE | --openapi FILE | --from-upstream FILE|DIR [--resource RES] | --from-recall ID] [--code PATH...] [--intent TEXT] [--profiles DIR] [--help | -h]

Options:
  --profile REF             profile the contract uses
  --from FILE               copy the shape of a sibling contract
  --concept ID...           concept to declare in [use]
  --code PATH...            code path to bind in [bind]
  --intent TEXT             intent sentence of the contract
  --profiles DIR            profile directory (default: nearest .drift/profiles)
  --state-dir DIR           keep area state in DIR outside the repository (shadow mode)
  --openapi FILE            scaffold from an OpenAPI document [Pro]
  --from-upstream FILE|DIR  scaffold from upstream contracts [Pro]
  --resource RES            upstream resource to scaffold (with --from-upstream) [Pro]
  --from-recall ID          scaffold from a recall card [Pro]
  --from-intent             draft cases from the untested intent terms [Pro]
  --asyncapi FILE           AsyncAPI document [Pro]
  --wsdl FILE               WSDL document [Pro]
  --copybook FILE           COBOL copybook [Pro]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift init`

**Tier:** Free

```text
drift init <owner> [dir] [--observed] [--taplo] [--help | -h]

Options:
  --observed       scaffold core@1 policy with proof = "verified" and require_observations = true
  --state-dir DIR  keep area state in DIR outside the repository (shadow mode)
  --unshadow       unregister the shadow area of DIR
  --graduate       promote a shadow area into tracked .drift/
  --taplo          scaffold .taplo.toml mapping .drift TOML files to 0.3 JSON Schemas
  --grant DIR      initialize the area from an exported grant directory
  --pact FILE      initialize the area from a sealed drift.pact-lock/1 file

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift case`

**Tier:** Free

```text
drift case add <file> [<id>] [--case ID --ask TEXT [--blocks PHASE] | --from-intent] [--profiles DIR] [--help | -h]

Options:
  --case ID           case id (instead of the <id> operand)
  --ask TEXT          question the new case answers
  --blocks PHASE      phase the case blocks (default: approval)
  --profiles DIR      profile directory (default: nearest .drift/profiles)
  --state-dir DIR     keep area state in DIR outside the repository (shadow mode)
  --from-intent       draft cases from the untested intent terms [Pro]
  --unbound-vocab     draft deferred cases for unbound profile predicates [Pro]
  --from-signal FILE  draft a case from a production signal [Pro]
  --deployment FILE   deployment receipts for --from-signal [Pro]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift prove`

**Tier:** Free

```text
drift prove <file|dir>... --events FILE|DIR... [--at LEVEL...] [--mutants FILE --mutation-events DIR] [--base FILE|DIR|REF] [--changed FILE...] [--changed-list FILE...] [--changed-none] [--explain] [--test-classes DIR] [--profiles DIR] [--json] [--help | -h]

Options:
  --events FILE|DIR...    proof events (*.jsonl files or directories)
  --at LEVEL...           proof level to require
  --explain               explain each verdict with its evidence
  --test-classes DIR      compiled test classes to match events against
  --profiles DIR          profile directory (default: nearest .drift/profiles)
  --json                  print JSON instead of text
  --detail LEVEL          detail level: full lists every contract of a directory
  --measurements FILE     performance measurement bundle
  --subject FILE          binary subject the measurements describe
  --subject-artifact REF  artifact reference of the measured subject
  --subject-tree DIR      source tree of the measured subject
  --run-id ID             identifier of the measured run
  --state-dir DIR         keep area state in DIR outside the repository (shadow mode)
  --base FILE|DIR|REF     baseline to compare with (a path or a git ref) [Pro]
  --changed [FILE]...     changed file; repeat it, or give no value for git changes [Pro]
  --changed-list FILE...  file listing changed paths [Pro]
  --changed-none          declare that nothing changed [Pro]
  --security-lock FILE    security lock receipt to reuse [Pro]
  --mutants FILE          mutant manifest from drift mutants [Enterprise]
  --mutation-events DIR   mutation run events [Enterprise]
  --as FORMAT             output: text or json

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift gate`

**Tier:** Free

```text
drift gate <file|dir>... --events FILE|DIR... [--at LEVEL...] [--phase execution|release] [--mutants FILE --mutation-events DIR] [--base FILE|DIR|REF] [--changed FILE...] [--changed-list FILE...] [--changed-none] [--compare-before FILE] [--upstream FILE|DIR...] [--explain] [--attest FILE] [--test-classes DIR] [--profiles DIR] [--config FILE] [--as junit|summary|md | --json] [--help | -h]

Options:
  --events FILE|DIR...      proof events (*.jsonl files or directories)
  --execution-context FILE  worker-pack execution context to verify against
  --base-snapshot REF       base snapshot for symbolic scope checks
  --result-snapshot REF     result snapshot for symbolic scope checks
  --runner-isolation MODE   unattested or declared_by_runner
  --at LEVEL...             proof level to require
  --phase PHASE             execution or release
  --explain                 explain each verdict with its evidence
  --test-classes DIR        compiled test classes to match events against
  --profiles DIR            profile directory (default: nearest .drift/profiles)
  --config FILE             area config (default: nearest .drift/config.toml)
  --grant-lock FILE         authoritative grant lock file to enforce
  --pact-lock FILE...       authoritative bilateral pact lock file to enforce
  --as FORMAT               output: summary, json or md (junit needs Enterprise)
  --json                    print JSON instead of text
  --detail LEVEL            detail level: full, summary or guided
  --previous-guided FILE    earlier guided output to continue (needs --detail guided)
  --measurements FILE       performance measurement bundle
  --subject FILE            binary subject the measurements describe
  --subject-artifact REF    artifact reference of the measured subject
  --subject-tree DIR        source tree of the measured subject
  --run-id ID               identifier of the measured run
  --state-dir DIR           keep area state in DIR outside the repository (shadow mode)
  --base FILE|DIR|REF       baseline to compare with (a path or a git ref) [Pro]
  --changed [FILE]...       changed file; repeat it, or give no value for git changes [Pro]
  --changed-list FILE...    file listing changed paths [Pro]
  --changed-none            declare that nothing changed [Pro]
  --upstream FILE|DIR...    upstream contracts or profiles [Pro]
  --security-lock FILE      security lock receipt to reuse [Pro]
  --mutants FILE            mutant manifest from drift mutants [Enterprise]
  --mutation-events DIR     mutation run events [Enterprise]
  --compare-before FILE     require the fault-to-pass transition against FILE [Enterprise]
  --attest FILE             write a signed gate attestation [Enterprise]
  --ssh-sign FILE           sign the attestation with an OpenSSH key [Enterprise]
  --trust-root FILE         trusted signer list for signature checks [Enterprise]
  --verify-time TIME        time at which signatures must be valid [Enterprise]
  --attest-sig FILE         detached signature of the attestation [Enterprise]
  --signatures FILE...      detached signature envelope [Enterprise]
  --signature-policy FILE   signature policy to enforce [Enterprise]
  --allow-break-glass       allow emergency break_glass exception for DR-E601 [Enterprise]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift run`

**Tier:** Free

```text
drift run [--events DIR] [--gate] [--state-dir DIR] [--profiles DIR] [--config FILE] -- <cmd> [args...] [--help | -h]

Options:
  --events DIR     proof events directory for DRIFT_EVENTS
  --gate           run drift gate against DRIFT_EVENTS when the command exits 0
  --profiles DIR   profile directory (default: nearest .drift/profiles)
  --config FILE    area config (default: nearest .drift/config.toml)
  --state-dir DIR  keep area state in DIR outside the repository (shadow mode)

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift eval`

**Tier:** Free

```text
drift eval <file|id>#<case> --observation FILE|- [--profiles DIR] [--as text|json | --json] [--help | -h]

Options:
  --observation FILE|-  drift.observation/1 (outcome = "returned", payload = {...}) or - for stdin
  --profiles DIR        profile directory (default: nearest .drift/profiles)
  --json                print JSON instead of text
  --state-dir DIR       keep area state in DIR outside the repository (shadow mode)
  --as FORMAT           output: text or json

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift map`

**Tier:** Free

```text
drift map [<file|dir>] [--view cases|flow|state] [--focus REF...] [--depth N] [--max-nodes N] [--skip N] [--flow] [--what-if FILE]... [--as text|json|mermaid | --json] [--profiles DIR] [--help | -h]
drift map focus <file|dir> <handle>... [--map REF] [--view cases|flow|state] [--what-if FILE]... [--question TEXT] [--as text|json | --json] [--profiles DIR] [--help | -h]
drift map walk [<dir>] --from H#CASE [--via H#CASE...] [--max-hops N] [--what-if FILE]... [--as text|json|mermaid | --json] [--profiles DIR] [--help | -h]

Options:
  --view VIEW          projection: cases (Free), flow (Pro) or state (Enterprise)
  --focus REF...       narrow view around canonical handle or id
  --max-nodes N        maximum visible nodes (default: 40, max: 128)
  --skip N             offset into ordered nodes for pagination (default: 0)
  --as FORMAT          output: text, json or mermaid
  --json               print JSON instead of text
  --profiles DIR       profile directory (default: nearest .drift/profiles)
  --state-dir DIR      keep area state in DIR outside the repository (shadow mode)
  --depth N            hop depth around --focus handles (default: 1, max: 6) [Pro]
  --what-if FILE|-...  in-memory hypothetical 0.3 contract overlay (no disk writes) [Pro]
  --flow               overlay Enterprise sweep --flow findings on nodes and edges [Enterprise]
  --map REF            pin focus against a map_ref sha256 prefix (>=12 hex)
  --question TEXT      optional analysis question attached to drift.focus/1
  --from H#CASE        starting contract/handle case for symbolic walk [Enterprise]
  --via H#CASE...      explicit next-hop contract/handle case override [Enterprise]
  --max-hops N         maximum walk hops (default: 8, max: 32) [Enterprise]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift doctor`

**Tier:** Free

```text
drift doctor [<dir>] [--json] [--help | -h]

Options:
  --json           print JSON instead of text
  --state-dir DIR  keep area state in DIR outside the repository (shadow mode)
  --as FORMAT      output: text or json

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift hook`

**Tier:** Free

```text
drift hook <session|prompt|stop|notify> [--help | -h]

Options:
  --state-dir DIR  keep area state in DIR outside the repository (shadow mode)
  --as FORMAT      output: text or json

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift completion`

**Tier:** Free

```text
drift completion <bash|zsh|fish|pwsh> [--help | -h]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift select`

**Tier:** Pro

```text
drift select [<base>] <file|dir> --events FILE|DIR... [--base FILE|DIR|REF] [--changed FILE...] [--changed-list FILE] [--changed-root DIR] [--upstream-base FILE|DIR [--upstream FILE|DIR...]] [--area DIR] [--profiles DIR] [--files] [--explain] [--json] [--help | -h]

Options:
  --events FILE|DIR...      proof events (*.jsonl files or directories) [Pro]
  --base FILE|DIR|REF       baseline to compare with (a path or a git ref) [Pro]
  --changed [FILE]...       changed file; repeat it, or give no value for git changes [Pro]
  --changed-list FILE       file listing changed paths [Pro]
  --changed-root DIR        root the --changed-list paths are relative to [Pro]
  --upstream-base FILE|DIR  upstream baseline [Pro]
  --upstream FILE|DIR...    upstream contracts or profiles [Pro]
  --build-graph-base FILE   baseline resolved drift.build-graph/1 JSON [Pro]
  --build-graph FILE        candidate resolved drift.build-graph/1 JSON [Pro]
  --area DIR                area to select in [Pro]
  --profiles DIR            profile directory (default: nearest .drift/profiles) [Pro]
  --files                   print the selected test files only [Pro]
  --explain                 explain each verdict with its evidence [Pro]
  --json                    print JSON instead of text [Pro]
  --plan                    print the test plan for the selection [Pro]
  --cmd                     print the test command for the selection [Pro]
  --state-dir DIR           keep area state in DIR outside the repository (shadow mode) [Pro]
  --as FORMAT               output: text or json [Pro]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift impact`

**Tier:** Pro

```text
drift impact [<file|dir|code>...] [--resource RES...] [--writes RES...] [--reads RES...] [--code PATH...] [--source TEXT...] [--surface TEXT...] [--profile REF...] [--owner OWNER...] [--query TEXT...] [--top N] [--toc] [--transitive] [--depth N] [--upstream FILE|DIR...] [--profiles DIR] [--json] [--help | -h]

Options:
  --resource RES...       resource to start from [Pro]
  --writes RES...         resource written [Pro]
  --reads RES...          resource read [Pro]
  --code PATH...          code path to start from [Pro]
  --source TEXT...        source to start from [Pro]
  --surface TEXT...       surface to start from [Pro]
  --profile REF...        profile to start from [Pro]
  --owner OWNER...        owner to start from [Pro]
  --query TEXT...         lexical query over contracts [Pro]
  --top N                 number of results to print (with --query) [Pro]
  --toc                   print the table of contents only [Pro]
  --transitive            follow dependencies transitively [Pro]
  --depth N               depth limit (with --transitive) [Pro]
  --upstream FILE|DIR...  upstream contracts or profiles [Pro]
  --profiles DIR          profile directory (default: nearest .drift/profiles) [Pro]
  --json                  print JSON instead of text [Pro]
  --state-dir DIR         keep area state in DIR outside the repository (shadow mode) [Pro]
  --as FORMAT             output: text or json [Pro]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift plan`

**Tier:** Pro

```text
drift plan [<file|dir>...] [--events FILE|DIR...] [--pack GROUP|ready|all|speculative] [--overlaps compact|pairs] [--staffing FILE] [--upstream FILE|DIR...] [--profiles DIR] [--json] [--help | -h]

Options:
  --events FILE|DIR...                proof events (*.jsonl files or directories) [Pro]
  --pack GROUP|ready|all|speculative  worker pack: a group number, ready, all or speculative [Pro]
  --pack-base FILE                    prior plan --pack JSON to emit a backscatter delta against (needs --pack) [Pro]
  --overlaps MODE                     overlap representation: compact (default) or pairs [Pro]
  --active                            omit quiet-completed groups, lanes, contracts and inactive overlaps [Pro]
  --compile-edges                     derive stage-ordering edges from existing bind.code source imports [Pro]
  --build-graph FILE                  resolved drift.build-graph/1 JSON for module compile edges [Pro]
  --staffing FILE                     agent pools to size the schedule for [Pro]
  --upstream FILE|DIR...              upstream contracts or profiles [Pro]
  --detail LEVEL                      full lists all completed items; guided adds execution context [Pro]
  --shard-dir DIR...                  shard directory of run-local ring and log files [Pro]
  --profiles DIR                      profile directory (default: nearest .drift/profiles) [Pro]
  --json                              print JSON instead of text [Pro]
  --state-dir DIR                     keep area state in DIR outside the repository (shadow mode) [Pro]
  --as FORMAT                         output: text or json [Pro]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift recall`

**Tier:** Pro

```text
drift recall query <expr> [<file|dir>...] [--share] [--profiles DIR] [--json] [--help | -h]
drift recall sync [<file|dir>...] [--root DIR] [--check] [--profiles DIR] [--json] [--help | -h]
drift recall record <id> [--dead-end TEXT [--revisit-if ANCHOR...]] [--retire MATCH] [--shared] [--root DIR] [--profiles DIR] [--json] [--help | -h]

Options:
  --share                  print the shareable form of the result [Pro]
  --max-degraded-lenses N  fail closed if degraded @ code lenses exceed N (N >= 0) [Pro]
  --lens-diagnostics       emit per-clause requested/emitted/degraded/unavailable lens diagnostics [Pro]
  --shard-dir DIR...       shard directory of run-local ring and log files [Pro]
  --profiles DIR           profile directory (default: nearest .drift/profiles) [Pro]
  --json                   print JSON instead of text [Pro]
  --state-dir DIR          keep area state in DIR outside the repository (shadow mode) [Pro]
  --as FORMAT              output: text or json [Pro]
  --root DIR               area root holding .drift/recall.jsonl [Pro]
  --check                  report a stale ring without writing it [Pro]
  --dead-end TEXT          standing or conditional dead-end finding to record [Pro]
  --revisit-if ANCHOR...   typed file, #symbol, glob, or resource anchor [Pro]
  --retire MATCH           retire existing !dead_end entries matching substring [Pro]
  --shared                 record in .drift/recall.jsonl instead of .drift-work/recall.jsonl [Pro]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift pact`

**Tier:** Pro

```text
drift pact offer [<file|dir>...] --policy FILE --pact-id ID --counterparty AREA --role ROLE [--area NAME] [--authorized-key KEY...] [--out FILE | --dry-run] [--ssh-sign FILE] [--profiles DIR] [--json] [--help | -h]
drift pact equalize --left FILE --right FILE --policy FILE [--prev FILE] [--as text|json|md | --json] [--help | -h]
drift pact seal --left FILE --right FILE --policy FILE --out FILE [--prev FILE] [--ssh-sign FILE --signer NAME --meaning MEANING] [--json] [--help | -h]
drift pact ack <lock> --area NAME --subject REF --retired-revision N --out FILE [--ssh-sign FILE] [--json] [--help | -h]

Options:
  --policy FILE            equalizer policy file (equalizer-policy.toml) [Pro]
  --pact-id ID             bilateral pact identifier [Pro]
  --counterparty AREA      counterparty area identifier [Pro]
  --role ROLE              offer party role: producer or consumer [Pro]
  --area NAME              local area identifier override [Pro]
  --authorized-key KEY...  authorized signer key fingerprint [Pro]
  --out FILE               file that receives drift.pact-offer/1 (- for stdout) [Pro]
  --dry-run                verify DLP and print egress manifest without writing [Pro]
  --ssh-sign FILE          sign the offer file with an OpenSSH key [Pro]
  --profiles DIR           profile directory (default: nearest .drift/profiles) [Pro]
  --json                   print JSON instead of text [Pro]
  --state-dir DIR          keep area state in DIR outside the repository (shadow mode) [Pro]
  --as FORMAT              output: text or json [Pro]
  --left FILE              first party drift.pact-offer/1 JSON file [Pro]
  --right FILE             second party drift.pact-offer/1 JSON file [Pro]
  --prev FILE              previous drift.pact-lock/1 for revision transitions [Pro]
  --signer NAME            signer principal for --ssh-sign [Pro]
  --meaning MEANING        signature meaning (pact.producer or pact.consumer) [Pro]
  --subject REF            deployed subject sha256 digest on active revision [Pro]
  --retired-revision N     superseded revision number being retired [Pro]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift merge`

**Tier:** Pro

```text
drift merge <base> <ours> <theirs> [--help | -h]

Options:
  --out FILE|-     write merged output to FILE or - instead of <ours> [Pro]
  --state-dir DIR  keep area state in DIR outside the repository (shadow mode) [Pro]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift mutants`

**Tier:** Enterprise

```text
drift mutants [<file|dir>...] --out FILE [--cases ID...] [--base FILE|DIR|REF] [--changed [FILE]...] [--changed-list FILE...] [--changed-root DIR] [--when] [--budget N [--events FILE|DIR...]] [--profiles DIR] [--json] [--help | -h]

Options:
  --out FILE              file that receives the mutant manifest (- for stdout) [Enterprise]
  --cases ID...           restrict mutants to these cases [Enterprise]
  --base FILE|DIR|REF     baseline to compare with (a path or a git ref) [Enterprise]
  --changed [FILE]...     changed file; repeat it, or give no value for git changes [Enterprise]
  --changed-list FILE...  file listing changed paths [Enterprise]
  --changed-root DIR      root the --changed-list paths are relative to [Enterprise]
  --when                  mutate the when side of the cases [Enterprise]
  --pairs                 append bounded 2nd-order compatible mutant pairs per case [Enterprise]
  --budget N              mutant budget; with --events it ranks by priority_weights [Enterprise]
  --detail LEVEL          full or summary (adds operator breakdown) [Enterprise]
  --events FILE|DIR...    proof events (*.jsonl files or directories) [Enterprise]
  --profiles DIR          profile directory (default: nearest .drift/profiles) [Enterprise]
  --json                  print JSON instead of text [Enterprise]
  --state-dir DIR         keep area state in DIR outside the repository (shadow mode) [Enterprise]
  --as FORMAT             output: text or json [Enterprise]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift stats`

**Tier:** Enterprise

```text
drift stats <file|dir>... [--profiles DIR] [--events FILE|DIR...] [--reports FILE...] [--ops FILE...] [--compare LABEL=FILE...] [--root DIR --changed-list FILE] [--json] [--help | -h]

Options:
  --profiles DIR            profile directory (default: nearest .drift/profiles) [Enterprise]
  --events FILE|DIR...      proof events (*.jsonl files or directories) [Enterprise]
  --reports FILE...         earlier stats reports to compare with [Enterprise]
  --ops FILE...             operational logs [Enterprise]
  --density                 compute per-resource cost-per-verified-obligation (C/U) density (needs --ops) [Enterprise]
  --compare LABEL=FILE...   candidate report to compare [Enterprise]
  --root DIR                area root (with --changed-list or --churn-list) [Enterprise]
  --changed-list FILE       file listing changed paths [Enterprise]
  --json                    print JSON instead of text [Enterprise]
  --since REF               Git ref for churn since REF (needs --root) [Enterprise]
  --detail LEVEL            full or summary (provenance + radar table) [Enterprise]
  --churn-list FILE         churn list for carve-out hotspots (- for stdin) [Enterprise]
  --changed-root DIR        root the churn paths are relative to [Enterprise]
  --top N                   number of hotspots to print (with --churn-list) [Enterprise]
  --mutation-events DIR...  mutation run events [Enterprise]
  --shard-dir DIR...        shard directory of run-local ring and log files [Enterprise]
  --state-dir DIR           keep area state in DIR outside the repository (shadow mode) [Enterprise]
  --as FORMAT               output: text or json [Enterprise]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```

### `drift sweep`

**Tier:** Pro / Enterprise

```text
drift sweep <file|dir>... [--root DIR] [--openapi FILE [--scaffold-profile FILE]] [--upstream FILE|DIR...] [--promote] [--flow [--pacts FILE|DIR...]] [--simplify [all|hygiene|epistemic]] [--apply] [--sync-scope] [--profiles DIR] [--json] [--help | -h]

Options:
  --root DIR                          area root (default: the area of the contracts) [Pro]
  --profiles DIR                      profile directory (default: nearest .drift/profiles) [Pro]
  --json                              print JSON instead of text [Pro]
  --openapi FILE                      OpenAPI document to check boundaries against [Enterprise]
  --scaffold-profile FILE             profile to scaffold with --openapi; written only with --apply [Enterprise]
  --upstream FILE|DIR...              upstream contracts or profiles [Enterprise]
  --promote                           same as sweep promote [Enterprise]
  --flow                              check dataflow, budgets and security boundaries [Enterprise]
  --simplify [all|hygiene|epistemic]  same as sweep simplify (the tier is optional) [Enterprise]
  --apply                             write the proposed changes [Enterprise]
  --sync-scope                        same as sweep sync-scope [Pro]
  --events FILE|DIR...                proof events for the recall ring [Pro]
  --mutation-events DIR...            mutation run events [Pro]
  --base FILE|DIR|REF                 baseline to compare with (a path or a git ref) [Pro]
  --delta                             report only what changed since --base [Pro]
  --check                             report without writing [Pro]
  --staged                            use the staged git changes [Pro]
  --asyncapi FILE                     AsyncAPI document [Enterprise]
  --wsdl FILE                         WSDL document [Enterprise]
  --copybook FILE                     COBOL copybook [Enterprise]
  --epoch-manifest FILE               AsyncAPI epoch manifest (needs --asyncapi) [Enterprise]
  --pacts FILE|DIR...                 sealed pact lock/ack manifests for fleet conservation (with --flow) [Enterprise]
  --state-dir DIR                     keep area state in DIR outside the repository (shadow mode) [Pro]
  --as FORMAT                         output: text, json or md [Pro]
  --level LEVEL                       all, hygiene or epistemic (default: all) [Enterprise]

Exit status:
  0  success
  1  findings or a not-green verdict
  2  usage or input error
```
