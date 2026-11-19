# Formal Verification, Performance Budgets, Security & Regulated Releases

> **Tier:** Free (Local budgets, security, formal & regulated receipt verification in `prove`, `gate`, and `verifier/drift_verify.py`) · Pro (`--security-lock`, `--base` reuse) · Enterprise (`gate --attest --ssh-sign --trust-root`, `--allow-break-glass`, detached quorums)

Beyond runtime tests, DRIFT gates performance, security, formal verification, and regulated effectiveness evidence under the same fail-closed `dr2a:` assurance seal—without invoking external solvers or scanners inside the kernel.

---

## 1. Performance Budgets & Anti-Waterbed Postures (`Free`)

Declare `[assurance.budgets.<id>]` in a contract and optional profile floors `[requires].budgets = "required"` and `[requires].budget_metrics = ["cpu_time_ns", "process_rss"]` to prevent trading one resource bottleneck for another:

- **Supported metrics:** `request_latency`, `frame_time`, `cold_start`, `successful_throughput` (`statistical` with `min_confidence`), plus `process_rss`, `artifact_bytes`, `work_units`, `tick_alloc_bytes`, `tick_alloc_count`, `alloc_bytes_total`, `alloc_count_total`, `frame_hitch_ns`, and `cpu_time_ns` (`observed`).
- Supply verified `drift.performance-run/1` bundles with `--measurements`:

```bash
drift gate .drift/contracts --events .drift/events --phase release \
  --measurements perf/run.json --subject target/app --run-id release-01
```

---

## 2. Security Receipts & Selective `--security-lock` (`Free` + `Pro`)

Profiles require security categories via `[requires].security = ["sast", "deps", "policy", "fuzz"]`. `prove`, `gate`, and `verifier/drift_verify.py` enforce two-stage applicability and `violated`-first precedence over `*.security.json` receipts, binding distinct `subject_ref` and `artifact_ref` hashes. With **Pro**, `--security-lock` enables selective reuse pinned to scanner and ruleset versions.

---

## 3. Formal Verification Obligations (`Free`)

Declare `[assurance.formal.<id>]` targeting `cbmc`, `kani`, `loom`, `tlc`, `alloy`, `spin`, `shuttle`, `stateright`, `dafny`, `gappa` (`arithmetic_model`), or `qcec` (`unitary_equivalence`):

- Receipts (`*.formal.json`, `drift.formal-receipt/1`) bind to a conservative candidate manifest (`drift.subject-manifest/1`) verified against `--subject` / worktree source digests (`subject.candidate_mismatch` on drift).
- Violations always take precedence over truncated explorations (`truncated_unwind`, `truncated_oom`, `truncated_timeout`), insufficient bounds, or vacuous cover checks.
- Counterexample witnesses (`*.cex.json`) replay directly inside bound unit tests without changing the approved contract digest.

---

## 4. Regulated Controls, Detached Multi-Party Quorums & Release Attestations (`Free` + `Enterprise`)

- **Many-to-many risk/control bindings:** `[assurance.risks]` and `[assurance.controls]` separate `implementation_status` from `effectiveness_status`, consuming validity-scoped usability study (`*.study.json`) and planned corpus / `stochastic_experiment` evaluation (`*.evaluation.json`) receipts with subgroup anti-masking.
- **OpenSSH attestations & detached quorums (`Enterprise`):**

```bash
drift gate .drift/contracts --events .drift/events --phase release \
  --signatures approvals/ --signature-policy quorum-policy.json \
  --attest target/drift/attestation.json --ssh-sign ~/.ssh/id_ed25519 \
  --trust-root .drift/allowed_signers --verify-time 2026-11-10T09:00:00Z
```

- Every attestation and detached `*.sig.json` quorum can be re-verified offline without trusting the CLI binary:

```bash
python3 verifier/drift_verify.py .drift/contracts --config .drift/config.toml \
  --events .drift/events --phase release --signatures approvals/ \
  --trust-root .drift/allowed_signers --verify-time 2026-11-10T09:00:00Z --json
```

For audited emergency overrides under explicit `emergency:` signers, `drift gate --allow-break-glass` disables proof reuse, preserves inviolable guards, and taints federated composition manifests.
