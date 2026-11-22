# Anti-False-Green Red-Team Benchmark & Differential Fuzzing

> **Purpose:** Empirically answer whether a protocol-aware AI agent can obtain a green gate without fixing the underlying software bug, and prove zero parser or gate-verdict divergence between the `drift` CLI binary and the open MIT Python verifier (`verifier/drift_verify.py`).

All three harnesses are MIT-licensed, zero-dependency Python 3.11+ scripts shipped in `verifier/` so any team or auditor can rerun them locally against the released binary.

---

## 1. Anti-False-Green Red-Team Benchmark (`verifier/redteam_false_green_bench.py`)

### Methodology

- **Buggy System Under Test (SUT):** A concrete HTTP service where `GET /items/1` returns `500 / "broken"` instead of `200 / "lamp"`.
- **14 Adversarial Attacks (`A01`–`A14`):** Each scenario attempts to make the gate return green **without fixing the SUT bug**, progressing from naive shortcuts (editing contracts, deleting tests, partial assertions, tautology callbacks `() => true` / `lambda v: True`, getter reads without assertions, overlapping test deletion `gone: 1`) to protocol-aware attacks (self-approval, hardcoded actuals, `when → then` lookup tables, in-process forged JSONL + mutation events).
- **2 Positive Controls (`P01`–`P02`):** The SUT bug is genuinely fixed (including an escaped-quote deep-bracket observation string) to verify **0% false reds**.
- **Live Execution:** Every DRIFT verdict is computed live by executing `drift` and `verifier/drift_verify.py` (never simulated).

### Measured Results

| Configuration | Attacks Blocked | False Greens | False-Green Rate | False Reds | Residual False Greens |
|---|---:|---:|---:|---:|---|
| `baseline-unit-tests` *(editable tests, no DRIFT)* | 0/14 | 14/14 | 100.0% | 0/2 | `A01`–`A14` |
| `drift-free-verified` *(Free, `verified`, unsigned approvals)* | 7/14 | 7/14 | 50.0% | 0/2 | `A06` *(advisory `oracle.self_stubbed`)*, `A08`, `A09`, `A10`, `A11`, `A13`, `A14` |
| `drift-enterprise-hardened` *(`killed` + `--when` mutants + signed approvals `--trust-root`)* | 12/14 | 2/14 | 14.3% | 0/2 | `A10-when-to-then-lookup-table`, `A11-in-process-forged-jsonl` |
| `drift-isolated-ci` *(DRIFT + `.drift/` & acceptance harness outside agent write perimeter)* | **14/14** | **0/14** | **0.0%** | **0/2** | **none** |

### Takeaway

- **DRIFT Free** deterministically blocks lazy test weakening, unapproved contract edits, stale replays, deleted tests that drop coverage (`gone`), partial reads (`bound`), no-op and tautology callbacks (`() => true`, `(v) => true`, `lambda v: True`), and unlisted approvers (`A01`–`A05`, `A07`, `A12`), and flags `A06` (`oracle.self_stubbed`) in triage. `A13` (getter-only `d.expect()` without assertions) and `A14` (overlapping test deleted while a duplicate weak test survives) stay green under default read-only `verified` and are explicitly measured here; opt-in `[policy].require_observations = true` closes `A13` in Free (JS/Python `d.check` auto-emit `drift.observation/1`), and `[policy].block_redundancy_erosion = true` flags/blocks `proving_tests_removed` on `--base` comparisons.
- **DRIFT Enterprise** additionally closes `A06` (self-stubbed `buildOutput`), `A08` (allowlisted self-approval via cryptographic owner signatures and `--trust-root`), `A09` (hardcoded literals via `--when` mutants), `A13` (read-without-assert), and `A14` (overlapping weak test fails to kill `--when` mutants).
- **Residual attacks `A10` and `A11`** prove that **no in-process test protocol alone** can stop an adversary who has write permissions to both the test harness and the event output path. Closing `A10` and `A11` requires **permission isolation** (`drift-isolated-ci`: keeping `.drift/` contracts, acceptance tests, and the CI runner outside the agent's write perimeter).

### Run Locally

```bash
python3 verifier/redteam_false_green_bench.py --drift "$(command -v drift)"
python3 verifier/redteam_false_green_bench.py --drift "$(command -v drift)" --as json
```

---

## 2. Differential JSON Fuzzer (`verifier/json_diff_fuzz.py`)

To ensure the precompiled `drift` CLI and the open MIT `verifier/drift_verify.py` never diverge on edge-case JSON inputs (such as escaped quotes `\"` followed by >64 brackets, `\u0022` equivalence, container depth 64 vs 65 boundaries, duplicate keys, Unicode keys, or malformed `.meta.json` sidecars):

```bash
python3 verifier/json_diff_fuzz.py --drift "$(command -v drift)" --cases 60 --seed 20261120
```

- Always replays the locked regression corpus (`verifier/json_diff_corpus.jsonl`) first.
- Generates seeded valid and adversarial `.jsonl` events and `.meta.json` inventories.
- Automatically shrinks any CLI↔verifier divergence to a minimal reproducer and exits non-zero.

---

## 3. Differential Gate-Verdict Fuzzer (`verifier/verdict_diff_fuzz.py`)

To verify end-to-end semantic parity between `drift gate` and `verifier/drift_verify.py` across randomized schema `0.3` contracts, relational predicates, `[invariants]`, `drift.observation/1` payloads, `.meta.json` inventories, and `policy.require_observations`:

```bash
python3 verifier/verdict_diff_fuzz.py --drift "$(command -v drift)" --cases 60 --seed 20261121
```

- Compares normalized gate verdicts (`ok`, per-contract `reasons`, and per-requirement states) across both engines and automatically shrinks any mismatch to a minimal counterexample.
