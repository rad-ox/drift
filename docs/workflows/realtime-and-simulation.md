# Real-Time Simulation, Game Engineering & Frame Budgets

> **Tier:** Free (`series`, `tol`, `peer.balance`, `drift.sim-receipt/1`, real-time budgets, C++20/C#/GDScript bridges) · Enterprise (`sweep --flow` frame-envelope, hot-loop alloc & nondeterminism seam checks)

Game loops, physics engines, and numerical simulations need contracts that tolerate frequent balance tuning while strictly enforcing conservation laws, deterministic replay, and per-tick allocation ceilings.

---

## 1. Tuning-Tolerant Invariants, Tolerances & Balances (`Free`)

Schema `0.3` contracts express trajectory laws, explicit tolerances, signed linear conservation balances, and declared units natively in `then` and `[invariants]`:

- **`series` trajectories:** `monotonic` (`non_decreasing`, `strictly_increasing`, `non_increasing`, `strictly_decreasing`), `sum_total` (exact or bounded interval), and `step_max_delta` (adjacent step ceiling).
- **Explicit numeric tolerances:** `eq` paired with `tol = { abs = 1e-6 }` and/or `tol = { rel = 1e-4 }` (evaluated strictly without hidden slack).
- **Double-entry / conservation balances:** `peer = { balance = { add = [...], sub = [...] } }` and unit conversions declared in `[units]`.

Single-file, zero-dependency bridges for **C++20 (`drift_cpp.hpp`)**, **C# / .NET / Unity (`Drift.cs`)**, and **Godot 4 GDScript (`drift.gd`)** verify these constraints directly; see **[Bridges](../bridges.md#native-game--simulation-bridges)**.

---

## 2. Deterministic Tick Replay & Convergence Receipts (`Free`)

Require deterministic simulation receipts (`*.sim.json`, `drift.sim-receipt/1`) via `[requires].simulation = "required"` in a profile or `[policy].simulation = "required"`:

- **`tick_determinism`**: cross-platform trajectory digest and `divergent_ticks` (`sim.desync_detected`).
- **`rollback_invariance`**: rollback window resimulation mismatches and leaked ambient mutations (`sim.rollback_drift`).
- **`save_epoch_compatibility`**: active save epochs verified against all contract `[invariants]` (`sim.save_epoch_incompatible`).
- **Numerical stability:** optional `observed_convergence` (grid refinement order vs `min_expected_order`) and `trajectory_stability` (finite-horizon drift, `NaN`/`Inf`, and optional `forbid_subnormals`).

```bash
drift gate .drift/contracts --events .drift-work/events --phase release --explain
python3 verifier/drift_verify.py .drift/contracts --config .drift/config.toml --events .drift-work/events --phase release --json
```

---

## 3. Hard Real-Time Frame & Zero-Allocation Budgets (`Free` + `Enterprise`)

Declare `[assurance.budgets.<id>]` using real-time and resource metrics:

- `frame_time` (`ns`, `p99`, `statistical`) and `frame_hitch_ns` (`ns`, `max_observed`)
- `tick_alloc_bytes` and `tick_alloc_count` (`limit = 0` enforces a strict zero-allocation tick hot loop)
- `alloc_bytes_total`, `alloc_count_total`, `process_rss`, and `cpu_time_ns`

Under **Enterprise** `drift sweep check --root . --flow`, DRIFT checks:
- **`budget.frame_envelope_exceeded`**: sums producer `frame_time`/`frame_hitch_ns` budgets across a `tick#*`/`frame#*` pipeline against the consumer envelope.
- **`budget.hot_loop_allocation`**: flags zero-alloc consumers reading from allocating producers.
- **`sim.nondeterministic_api`**: detects ungoverned RNG or wall-clock calls (`std::rand`, `UnityEngine.Random`, `DateTime.Now`, `randf()`, etc.) inside owned simulation files.
