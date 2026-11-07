# Installing DRIFT

**English** · [Italiano](INSTALL.it.md) · [Practical Guide](GUIDE.md) · [Editions](EDITIONS.md)

DRIFT is one command, `drift`, plus optional parts: an agent skill, a JUnit
bridge and Maven plugin for JVM projects, and zero-dependency bridges for
JavaScript (`drift.mjs`) and Python (`drift.py`). The installer puts all of
them in your user account. It needs no administrator rights and no network,
and one command removes everything it installed.

## In short

| | Ubuntu and other Linux | macOS (Apple Silicon & Intel) | Windows 10 and 11 |
|---|---|---|---|
| You receive | `drift-0.3.1-linux-x64.tar.gz` | `drift-0.3.1-macos-arm64.tar.gz` or `drift-0.3.1-macos-x64.tar.gz` | `drift-0.3.1-windows-x64.zip` |
| Install | `tar -xzf drift-0.3.1-linux-x64.tar.gz`<br>`./drift-0.3.1-linux-x64/install.sh` | `tar -xzf drift-0.3.1-macos-arm64.tar.gz`<br>`./drift-0.3.1-macos-arm64/install.sh` | Extract the zip, double-click `install.cmd` |
| Check | `drift version` | `drift version` | `drift version` in a new terminal |
| Remove | `~/.local/share/drift/install.sh --uninstall` | `~/.local/share/drift/install.sh --uninstall` | Settings › Apps › DRIFT › Uninstall |

> **Installing directly from the public GitHub repository (`rad-ox/drift`):**
> Run `./install.sh` on Linux or macOS, or `.\install.cmd` on Windows, directly from the repository root.

Obtain the archive (and `SHA256SUMS`, when distributed alongside it) through a
trusted channel; each archive also carries an internal `SHA256SUMS` covering
every packaged file. The checksum detects accidental damage, not who created
the package; for authenticity, compare its value over a separate trusted
channel.

## What you need

- **Linux**: Ubuntu 20.04 or later, or any 64-bit x86 Linux (the binary is static and needs no libraries).
- **macOS**: macOS 12+ on Apple Silicon (`macos-arm64`) or Intel (`macos-x64`).
- **Windows**: Windows 10 or 11, 64-bit (`windows-x64`).
- Only for the JUnit bridge: JDK 17 or later and Maven 3.6.3 or later.
- Only for the JavaScript or Python bridge: Node.js 18+ or Python 3.9+.
  `drift` itself needs nothing else.
- Only for the skill: an agent that reads skills from `~/.copilot/skills` or
  `~/.agents/skills`, such as GitHub Copilot CLI, Claude Code, Codex, or Pi.

## Ubuntu and other Linux

1. If you received `SHA256SUMS` alongside the archive, put both in one folder,
   open a terminal there and check the archive:

   ```bash
   sha256sum --ignore-missing -c SHA256SUMS
   ```

   You should see `drift-0.3.1-linux-x64.tar.gz: OK`. Anything else means a
   damaged or different file: ask for it again. (If you received only the
   `.tar.gz`, step 2 verifies the internal `SHA256SUMS` inside the archive.)
2. Extract and install:

   ```bash
   tar -xzf drift-0.3.1-linux-x64.tar.gz
   (cd drift-0.3.1-linux-x64 && sha256sum -c SHA256SUMS)
   ./drift-0.3.1-linux-x64/install.sh
   ```

   Every step prints `✓`. A line with `!` tells you what to do next, for
   example `~/.local/bin enters PATH at your next login; in this terminal
   run: . ~/.profile`.
3. Check: `drift version` prints `drift 0.3.1 (schema 0.2, digest dr1, build <id>)`,
   where `<id>` names the source the package was built from.

You can delete the extracted folder afterwards.

## Windows 10 and 11

1. If you received `SHA256SUMS` alongside the zip, put both in one folder, open
   PowerShell there and check the download:

   ```powershell
   (Get-FileHash .\drift-0.3.1-windows-x64.zip).Hash -eq (-split (Select-String windows-x64 .\SHA256SUMS).Line)[0]
   ```

   You should see `True`. (The extracted folder also includes an internal
   `SHA256SUMS` listing every file in the package.)
2. Right-click the zip, choose **Extract All…**, then **Extract**.
3. In the extracted folder, double-click **`install.cmd`**. A window shows
   every step and waits for Enter at the end. From a terminal, run
   `.\install.cmd` instead.
4. Open a **new** terminal, because the PATH changes only for new windows,
   and run `drift version`.

The installer adds `drift` to your user PATH and lists DRIFT in Settings ›
Apps. You can delete the extracted folder afterwards.

## What goes where

| | Linux | Windows |
|---|---|---|
| Command | `~/.local/bin/drift` | `%LOCALAPPDATA%\Programs\drift\bin\drift.exe` |
| Guide, example, schemas, uninstaller | `~/.local/share/drift/` | `%LOCALAPPDATA%\Programs\drift\` |
| JS and Python bridges | `~/.local/share/drift/bridges/drift.mjs`, `drift.py` | `%LOCALAPPDATA%\Programs\drift\bridges\drift.mjs`, `drift.py` |
| Agent skill | `~/.copilot/skills/drift/` (and `~/.agents/skills/` when present or with `--hooks`) | `%USERPROFILE%\.copilot\skills\drift\` (and `%USERPROFILE%\.agents\skills\`) |
| Agent hooks (opt-in) | `~/.pi/agent/extensions/drift.ts`, `~/.copilot/hooks/drift.json`, `~/.codex/hooks.json`, `~/.claude/settings.json` | `%USERPROFILE%\.pi\agent\extensions\drift.ts`, `%USERPROFILE%\.copilot\hooks\drift.json` |
| JUnit bridge | `~/.m2/repository/drift/drift-junit/0.3.1/` | `%USERPROFILE%\.m2\repository\drift\drift-junit\0.3.1\` |
| Maven plugin | `~/.m2/repository/drift/drift-maven-plugin/0.3.1/` | `%USERPROFILE%\.m2\repository\drift\drift-maven-plugin\0.3.1\` |
| Settings changed | none: the installer only prints a PATH hint | user PATH and an entry in Settings › Apps |

If `~/.m2/settings.xml` sets `<localRepository>`, the bridge and the plugin
go there.
Shell profiles are never edited.

## Options

| Linux: `install.sh` | Windows: `install.cmd` | Effect |
|---|---|---|
| `--prefix DIR` | `-Prefix DIR` | install elsewhere; on Linux into `DIR/bin` and `DIR/share/drift` |
| `--skills-dir DIR` | `-SkillsDir DIR` | use another agent skills folder |
| `--no-skill` | `-NoSkill` | skip the agent skill |
| `--hooks` | `-Hooks` | install automatic hooks/extensions for detected agents (Pi, Copilot, Claude, Codex, Cursor, Gemini) |
| `--no-hooks` | `-NoHooks` | skip automatic hooks without prompting |
| `--hooks-dir DIR` | `-HooksDir DIR` | install the automatic hook file into `DIR/drift.json` |
| `--maven-repo DIR` | `-MavenRepo DIR` | use another local Maven repository |
| `--no-maven` | `-NoMaven` | skip the JUnit bridge and the Maven plugin |
| | `-NoPath` | leave the user PATH alone |
| `--dry-run` | `-DryRun` | show the steps and change nothing |
| `--uninstall` | `-Uninstall` | remove what was installed |
| `--lang en` or `--lang it` | `-Lang en` or `-Lang it` | message language; the default follows the system |
| `--help` | `-Help` | list every option |

`DRIFT_LANG=it` also selects Italian, and `NO_COLOR=1` turns colours off.

## First steps

The installer leaves a small example next to this guide:

```bash
drift check ~/.local/share/drift/example/.drift                                    # prints: ok: 3 file(s)
drift review ~/.local/share/drift/example/.drift --brief                           # deterministic review packet
drift show ~/.local/share/drift/example/.drift/contracts/item-get.toml --as json   # resolved view for tests
drift help
drift explain DR-E601
```

On Windows the example is in `$env:LOCALAPPDATA\Programs\drift\example\.drift`.
An agent that reads `~/.copilot/skills` finds the `drift` skill when it next
starts; the skill describes the whole workflow.

## Maven projects (JUnit bridge and plugin)

Add the test dependency and the plugin to the project's `pom.xml`. The
installed skill explains how to tag tests, in `references/jvm-bridge.md`.

```xml
<dependency>
  <groupId>drift</groupId>
  <artifactId>drift-junit</artifactId>
  <version>0.3.1</version>
  <scope>test</scope>
</dependency>
```

```xml
<plugin>
  <groupId>drift</groupId>
  <artifactId>drift-maven-plugin</artifactId>
  <version>0.3.1</version>
  <executions>
    <execution>
      <goals>
        <goal>prepare</goal>
        <goal>gate</goal>
      </goals>
    </execution>
  </executions>
</plugin>
```

Then one command, the same on Linux and Windows, exports the contracts, runs
the tests and asks the gate:

```bash
mvn verify
```

- The build fails when a contract is not green and prints why. A test run
  again replaces its earlier result; `mvn clean verify` starts over.
- The plugin runs the installed `drift`; `-Ddrift.skip` turns it off.
- If the surefire configuration sets its own `<argLine>`, put `@{argLine}`
  in it.
- The first build downloads JUnit and the Maven plugins like any Maven
  build, so it needs network access or a mirror.

Without the plugin, on Linux:

```bash
drift show .drift/contracts --as json --out target/drift/resolved
mvn test -Ddrift.resolved="$PWD/target/drift/resolved" -Ddrift.events="$PWD/target/drift/events.jsonl"
drift gate .drift/contracts --events target/drift/events.jsonl
```

On Windows, in PowerShell:

```powershell
drift show .drift\contracts --as json --out target\drift\resolved
mvn test "-Ddrift.resolved=$PWD\target\drift\resolved" "-Ddrift.events=$PWD\target\drift\events.jsonl"
drift gate .drift\contracts --events target\drift\events.jsonl
```

In PowerShell, quote every `-D...` argument; without quotes PowerShell
splits it at the dot.

## JavaScript and Python projects (`drift.mjs` and `drift.py`)

The installer places the zero-dependency JavaScript and Python 3 bridges in
`~/.local/share/drift/bridges/` on Linux and
`%LOCALAPPDATA%\Programs\drift\bridges\` on Windows (also at `bridges/drift.mjs`
and `bridges/drift.py` inside the extracted package). Copy the bridge for your
runtime into your project's test folder (for example `test/drift.mjs` or
`tests/drift.py`), or add the `bridges` folder to `NODE_PATH` / `PYTHONPATH`.

In **JavaScript / TypeScript** (`node --test`, Vitest or Jest):

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runDriftCase } from './drift.mjs';

test('returns item', async (t) => {
  await runDriftCase({ contract: 'item-get', t, cases: ['found'], level: 'http' }, async (d) => {
    const res = await send(d.when('found', 'request'));
    await d.check('found', { status: (v) => assert.equal(res.status, v) });
  });
});
```

Under Vitest or Jest, pass `test: 'ItemTest#returns_item'` instead of the
`node:test` context `t`.

In **Python 3** (`pytest` or `python3 -m unittest`):

```python
import drift

def test_found():
    drift.run_drift_case(
        contract="item-get",
        test="test_items.py#test_found",
        cases=["found"],
        level="http",
        fn=lambda d: d.check(
            "found",
            {"status": lambda v: assert_eq(send(d.when("found", "request")).status, v)},
        ),
    )
```

Export the resolved views, run the test suite and check the gate:

```bash
drift show .drift/contracts --as json --out .drift/resolved
DRIFT_RESOLVED=.drift/resolved DRIFT_EVENTS=.drift/events node --test   # or npx vitest run, npx jest, pytest
drift gate .drift/contracts --events .drift/events
```

When `DRIFT_RESOLVED` and `DRIFT_EVENTS` are unset and `drift` is on `PATH`,
both bridges auto-resolve `.drift/contracts` (or `.drift/resolved` /
`.drift-work/resolved`) and write events to `.drift/events` (or
`.drift-work/events`), so running `node --test` or `pytest` followed by
`drift gate` also works directly from the area root. Use
`drift select --changed <file>... --files` (or `selectFiles` / `select_files`)
to pass only the affected test files to `node --test` or `pytest`.

| Environment variable | Purpose |
|---|---|
| `DRIFT_RESOLVED` | Directory or `.json` file of exported contract views (auto-resolved from `.drift/` or `.drift-work/resolved` when unset) |
| `DRIFT_EVENTS` | Output file or directory for `.jsonl` proof events and `.meta.json` inventories (defaults to `.drift/events` or `.drift-work/events`) |
| `DRIFT_CLI` | Path to the `drift` executable used when auto-resolving `.drift/contracts` (when `drift` is not on `PATH`) |
| `DRIFT_SNAPSHOT` | Git tree OID recorded in `.meta.json` sidecars for snapshot-backed reuse |

## Update

Run the installer of the newer package. It replaces `drift` and the skill and
adds the new bridge and plugin versions. Older versions stay, because
projects may still use them.

## Uninstall

- Linux: `~/.local/share/drift/install.sh --uninstall`. If you installed with
  `--prefix DIR`, run `DIR/share/drift/install.sh --uninstall`.
- Windows: Settings › Apps › Installed apps › DRIFT › Uninstall, or run
  `%LOCALAPPDATA%\Programs\drift\uninstall.cmd`.

Uninstall removes exactly what the installer recorded in its manifest. Your
contracts and projects are not touched.

## Troubleshooting

**`drift: command not found` on Linux.** Run `. ~/.profile` or log in again.
If that does not help, add the line the installer printed, such as
`export PATH="$HOME/.local/bin:$PATH"`, to `~/.bashrc`.

**`drift` is not recognized on Windows.** Open a new terminal. A terminal
started from a window that was open before the install keeps the old PATH;
sign out and back in if needed. With `-NoPath`, call `drift.exe` by its full
path.

**"Running scripts is disabled on this system".** Start `install.cmd`, not
`install.ps1`: it allows the script for this run only. If your organisation
enforces a policy, ask IT, or copy `bin\drift.exe` to a folder on your PATH
and `skill\drift` to `%USERPROFILE%\.copilot\skills\drift` by hand.

**Windows asks whether to run `install.cmd`, or blocks `drift.exe`.** The
files are not signed and came from another computer. Choose **Run**; to avoid
the question, unblock the zip before extracting it: right-click › Properties ›
Unblock, or `Unblock-File .\drift-0.3.1-windows-x64.zip`. If company rules
block programs in `%LOCALAPPDATA%`, install with `-Prefix` into an allowed
folder or ask IT.

**Maven: `Could not find artifact drift:drift-junit:jar:0.3.1`** (or
`drift-maven-plugin`). Maven uses a different local repository than the
installer did, for example through `-Dmaven.repo.local` or a settings file in
another place. Run the installer again with `--maven-repo DIR` or
`-MavenRepo DIR` pointing to it.

**Maven: "... is drift X, the plugin is Y".** The `drift` on PATH and the
plugin come from different versions. Install the package of the plugin's
version, or point the plugin to a matching `drift` with `-Ddrift.cli=PATH`.

**Odd characters in exported JSON on Windows.** Export with `--out`, or with
the plugin: `drift` then writes the files itself. A view redirected with `>`
needs `[Console]::OutputEncoding = [Text.Encoding]::UTF8` first in Windows
PowerShell 5.1 and PowerShell 7.0 to 7.3. The bridge reads UTF-8 and UTF-16
files, with or without a byte order mark.

**Line endings.** Contracts with Windows line endings (CRLF) check, format
and approve the same as with LF; `drift fmt` writes LF.

**Proxy.** When run from an extracted release archive, the installer never uses the network (when run from a `git clone` without local binaries, `install.sh` downloads and SHA-256-verifies the matching platform archive from GitHub Releases). For Maven, configure
its proxy in `~/.m2/settings.xml`.

**macOS Gatekeeper quarantine.** If macOS blocks the unsigned binary downloaded
from a browser, clear the quarantine attribute on the extracted folder before
running `install.sh`: `xattr -dr com.apple.quarantine ./drift-0.3.1-macos-*`.
