# Polyglot Test Bridges & Observation Protocol

> **Tier:** Free (All 11 bridges, `drift eval`, compiled `.plans/<id>.plan.json`, `drift.observation/1`, `drift.bridge-session/1`)

DRIFT ships **11 zero-dependency, MIT-licensed test bridges**. Expected values live once—in `.drift/contracts/<id>.toml`—and bound tests read inputs (`when`), check observed outputs (`then`), and emit `<shard>.jsonl` proof events + `<shard>.meta.json` discovery inventories.

---

## Bridge Matrix

| Runtime | Artifact | Baseline | CI Verification Status | Proof & Anti-Cheat Capabilities |
|---|---|---|---|---|
| **Java 17–25 (JUnit 5)** | `drift-junit` + `drift-maven-plugin` (`0.9.0`) | Java 25 LTS (Java 17 floor) | **Public CI E2E** (live HTTP + CLI/verifier parity) | `@DriftCase`, `Drift.expect`, `verify`, Maven `prepare`/`gate`, `-Ddrift.changed=auto` |
| **Scala 2.12–3.9 (MUnit / sbt)** | `drift-junit` (`0.9.0`) | Scala 3.9 / sbt | **Shared JVM Artifact** (uses verified `drift-junit`; no sbt job in public CI) | Closure-based `Drift.expect(contract, case, level)` + `c.verify(...)` |
| **JavaScript / TypeScript** | `bridges/drift.mjs` | Node.js 24 LTS (18+) | **Public CI E2E** (live HTTP, concurrency, adversarial, parity) | `runDriftCase`, `d.check`, `node --test`, Vitest, Jest, in-process mutants |
| **Python 3** | `bridges/drift.py` | Python 3.14 (3.11+) | **Public CI E2E** (live HTTP, concurrency, adversarial, parity) | `run_drift_case`, `d.check`, `pytest`, `unittest`, in-process mutants |
| **Rust** | `bridges/rust` (`drift_rust`) | Rust Edition 2024 | **Public CI `cargo test`** + Private E2E parity | `#![forbid(unsafe_code)]`, `run_drift_case`, `check_projection`, subprocess mutants |
| **V** | `bridges/v/drift_v` | V 0.5.2 | **Private CI E2E** (no V compiler installed on public runner) | `vlib`-only `run_drift_case`, `touched_symbols` L2 witness, PID-sharded mutants |
| **C++20** | `bridges/drift_cpp.hpp` | C++20 | **Public CI Smoke (`g++ -std=c++20`)** + Private E2E | Single-header, `series` trajectory invariants, `tol`, `peer.balance`, `sim-receipt/1` |
| **C# / .NET / Unity** | `bridges/Drift.cs` | .NET 8.0+ | **Public CI Smoke (`dotnet`)** when runtime present | Single-file, `series`, `tol`, `peer.balance`, `sim-receipt/1`, `checkLogSink` |
| **Godot 4 GDScript** | `bridges/drift.gd` | GDScript 4.3+ | **Experimental (static checks only; no Godot CI runtime)** | Single-file, `series`, `tol`, `peer.balance`, `sim-receipt/1`, frame collectors |
| **PHP 8.2+** | `bridges/Drift.php` | PHP 8.2+ | **Public CI Smoke (`php`)** when runtime present | Single-file, JSON Pointer projections, `keys.forbid`, `not_in`, `checkFrame`, `*.cex.json` |
| **Java 6–8 (JUnit 4)** | `bridges/legacy/junit4/DriftJUnit4.java` | Java 6+ / JUnit 4 | **Private CI E2E** (compiled & executed in upstream harness) | Single-file `RunListener` (`bound`), `DriftJUnit4.verify` (`verified`), `*.cex.json` |
| **COBOL 85 Batch** | `bridges/drift_cobol.py` | Python 3.11+ | **Public CI Smoke (copybook marshal/check)** + Private parity | Copybook `PIC`/`COMP-3`/EBCDIC marshaling, kernel decode, `drift.parity-receipt/1` |

> **Verification tiers:** *Public CI E2E* runs live SUT tests and CLI↔Python verifier parity in `.github/workflows/verify.yml`; *Public CI Smoke* compiles/executes positive, regression, and unsupported-capability checks in public CI; *Private CI E2E* runs in the upstream build harness; *Experimental* bridges are shipped without live runtime execution in CI.

All bridges support compiled zero-binary verification plans (`.plans/<id>.plan.json`) emitted by `drift show --out <dir>` and `drift export views --out <dir>`, so CI test containers do not need the `drift` binary on `PATH` during test execution.

---

## Primary Bridges

### Java (JUnit 5 & Maven Plugin)

Add `drift-junit` and `drift-maven-plugin` (`0.9.0`) to `pom.xml`, annotate tests with `@DriftCase`, and run `mvn verify`:

```xml
<dependency>
  <groupId>io.github.rad-ox</groupId>
  <artifactId>drift-junit</artifactId>
  <version>0.9.0</version>
  <scope>test</scope>
</dependency>
```

```java
import drift.Drift;
import drift.DriftCase;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertEquals;

class ItemHttpTest {
    @Test
    @DriftCase(contract = "item-get", cases = "found", level = "http")
    void returnsExistingItem() throws Exception {
        Drift.Case c = Drift.expect("item-get", "found");
        var response = send(c.whenString("request"));
        assertEquals(c.thenInt("status"), response.statusCode());
        assertEquals(c.thenString("name"), response.json().get("name"));
    }
}
```

### Scala 3 / sbt (MUnit)

Resolve `drift-junit` from local Maven (`resolvers += Resolver.mavenLocal`, `"io.github.rad-ox" % "drift-junit" % "0.9.0" % Test`) and call `Drift.expect` + `c.verify(...)` inside closure tests:

```scala
import drift.Drift

class ItemSuite extends munit.FunSuite:
  test("returns existing item") {
    val c = Drift.expect("item-get", "found", "http")
    val res = send(c.whenString("request"))
    c.verify("status", res.status, "name", res.name)
  }
```

### JavaScript / TypeScript (`bridges/drift.mjs`)

Compatible with `node --test`, **Vitest**, and **Jest** (pass `test: 'Suite#case'` when not using `node:test`'s `t`):

```js
import { test } from 'node:test';
import { runDriftCase } from './drift.mjs';

test('GET /items/1 returns existing item', async (t) => {
  await runDriftCase({ contract: 'item-get', t, cases: ['found'], level: 'http' }, async (d) => {
    const res = await send(d.when('found', 'request'));
    await d.check('found', { status: res.status, name: res.body.name });
  });
});
```

### Python 3 (`bridges/drift.py`)

Compatible with **pytest** and `unittest`:

```python
import drift

def test_returns_existing_item():
    def verify(d):
        res = send(d.when("found", "request"))
        d.check("found", {"status": res.status, "name": res.json()["name"]})

    drift.run_drift_case(
        contract="item-get",
        test="test_items.py#test_returns_existing_item",
        cases=["found"],
        level="http",
        fn=verify,
    )
```

### Rust (`bridges/rust` · `drift_rust`)

```rust
use drift_rust::{canonical_rust_test_id, run_drift_case, RunOptions};

#[test]
fn returns_existing_item() {
    let tid = canonical_rust_test_id("catalog", module_path!(), "returns_existing_item");
    run_drift_case(
        RunOptions {
            contract: "item-get".to_string(),
            test: tid,
            cases: vec!["found".to_string()],
            level: "http".to_string(),
            ..Default::default()
        },
        |ctx| {
            let payload = send(ctx.when_str("found", "request")?);
            ctx.check_projection("found", &payload)
        },
    ).expect("drift case verified");
}
```

```bash
drift show .drift/contracts --as json --out target/drift/resolved
DRIFT_RESOLVED=target/drift/resolved DRIFT_EVENTS=target/drift/events cargo test
drift gate .drift/contracts --events target/drift/events
```

### V (`bridges/v/drift_v`)

```v
import drift_v

fn test_returns_existing_item() {
	res := drift_v.run_drift_case(drift_v.RunOptions{
		contract: 'item-get'
		test:     'items_test#test_returns_existing_item'
		cases:    ['found']
		level:    'http'
	}, fn (mut ctx drift_v.DriftContext) ! {
		payload := send(ctx.when_str('found', 'request')!)
		ctx.check_projection('found', payload)!
	}) or { panic(err) }
	assert res == 'passed'
}
```

```bash
drift show .drift/contracts --as json --out .drift-work/resolved
DRIFT_RESOLVED=.drift-work/resolved DRIFT_EVENTS=.drift-work/events v -path "bridges/v|@vlib|@vmodules" test .
drift gate .drift/contracts --events .drift-work/events
```

---

## Native, Game & Simulation Bridges

- **C++20 (`bridges/drift_cpp.hpp`)**, **C# / .NET / Unity (`bridges/Drift.cs`)**, and **Godot 4 GDScript (`bridges/drift.gd`)** verify tuning-tolerant `series` invariants (`monotonic`, `sum_total`, `step_max_delta`), explicit numeric tolerances (`eq` with `tol.abs`/`tol.rel`), signed linear balances (`peer.balance`), recursive `keys.forbid`, unobserved frame collectors, `checkLogSink`, and deterministic tick replay receipts (`drift.sim-receipt/1`).
- See **[Real-Time & Simulation Workflows](workflows/realtime-and-simulation.md)** for full contract and budget recipes.

---

## Legacy, PHP & Mainframe Bridges

- **Java 6–8 / JUnit 4 (`bridges/legacy/junit4/DriftJUnit4.java`)**: attach `DriftJUnit4.Listener` to record `.meta.json` inventories and `bound` proof events with zero JUnit 5 dependencies; call `DriftJUnit4.verify(contract, caseId, observations, frames)` to reach `verified` and `DriftJUnit4.replayCounterexamples(...)` for `*.cex.json` replay.
- **PHP 8.2+ (`bridges/Drift.php`)**: single-file bridge supporting RFC 6901 JSON Pointer projections, `keys.forbid`, `not_in`, `checkFrame`, `*.cex.json` replay, and atomic `.jsonl` / `.meta.json` shards.
- **COBOL 85 Batch / Copybook (`bridges/drift_cobol.py`)**: parses `PIC` copybook layouts, marshals `when` JSON into fixed-width records (`PIC X`, `PIC 9`, `COMP-3`, EBCDIC with DB2 `-1` null indicators), feeds raw observations to the kernel decoder, and emits `drift.parity-receipt/1` cutover receipts.
- See **[Legacy Carve-Outs & Cutover](workflows/legacy-cutover.md)** for migration workflows.

---

## Canonical Observation Protocol & Standalone Oracle (`drift eval`)

Bridges can emit lossless `drift.observation/1` (`ObsValue`: `int64`, `uint64`, exact `decimal`, `bytes`, `null` vs `absent` `presence`) and non-stdio `drift.bridge-session/1` supervisor records evaluated directly by the kernel (detecting swallowed runner verdicts via `bridge.verdict_swallowed`).

To test any observation envelope against one contract case without emitting a proof event, run:

```bash
drift eval item-get#found --observation observation.json
```
