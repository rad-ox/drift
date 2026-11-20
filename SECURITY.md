# Security Policy

## Supported Versions

Security fixes are provided for the latest released `0.8.x` line of DRIFT Free, DRIFT Pro, and DRIFT Enterprise, as well as the open reference verifier (`verifier/`) and polyglot test bridges (`bridges/`).

| Version | Supported |
|---|---|
| `0.8.x` | Yes |
| `< 0.8.0` | No (upgrade to `0.8.x`) |

## Reporting a Vulnerability

Please **do not** report security vulnerabilities through public GitHub issues, discussions, or pull requests.

Instead, report suspected vulnerabilities privately using one of the following channels:

1. **GitHub Private Vulnerability Reporting**: Open a private advisory draft on [`rad-ox/drift`](https://github.com/rad-ox/drift/security/advisories/new).
2. **Email**: Send a detailed report to `rad-ox@users.noreply.github.com` with `[SECURITY] DRIFT` in the subject line.

### What to Include

- Affected component (`drift` CLI binary, `verifier/drift_verify*.py`, a language bridge under `bridges/`, or an installer/hook under `hooks/`).
- Exact version and platform (`drift version` output).
- Minimal reproduction steps, contract/event fixture, or proof-of-concept input.
- Assessment of impact (for example gate bypass, digest collision, path traversal, or untrusted input execution).

## Security Model & High-Assurance Guarantees

DRIFT is designed around fail-closed verification and zero-trust execution boundaries:

- **Deterministic Offline Kernel**: Contract validation (`drift check`), formatting (`drift fmt`), diffing (`drift diff`), review (`drift review`), proof evaluation (`drift prove`), and gating (`drift gate`) execute offline without network access, ambient clock reads, or randomness.
- **Independent Open Verifier (`verifier/drift_verify.py`)**: Every release ships a zero-dependency Python 3 reference verifier under the MIT License so teams and auditors can independently verify `dr2b:`/`dr2a:`/`dr2r:`/`dr2x:` (`0.3`) contract digests (and `dr1:` area config digests), `.jsonl` proof events, `.observation.jsonl` lossless records, `.meta.json` test inventories (`forbid_touched`), `--measurements` budgets (`alloc_bytes_total` / `alloc_count_total` / `cpu_time_ns`, `[requires].budget_metrics`), `.security.json` receipts, `drift.grant-lock/1` clean-room grant locks, `drift.pact-lock/1` bilateral pact locks, and OpenSSH trust-root signatures (`--trust-root`) without trusting the precompiled CLI binary.
- **Release Supply-Chain Verification (Deterministic Archives, OpenSSH, SLSA v1.0, Sigstore & TUF)**:
  - Release archives are packaged with normalized timestamps/ownership and verified against `SHA256SUMS`.
  - Protected CI releases publish an in-toto **SLSA v1.0 provenance statement** (`drift-<ver>.slsa.intoto.jsonl`), detached **OpenSSH signatures** (`SHA256SUMS.sig`, verified against pinned `release/RELEASE_SIGNERS` in namespace `drift-release`), **Sigstore Cosign keyless OIDC bundles** (`*.sigstore.json`), and **TUF v1.0-aligned signed update metadata** (`tuf-{root,timestamp,snapshot,targets}.json`, verified offline by `release/tuf_verify.py` against freeze, rollback, mix-and-match, and tampering attacks).
  - Public installers (`install.sh` / `install.ps1`) fail closed on `SHA256SUMS`, active `release/RELEASE_SIGNERS` signatures, and provisioned `release/tuf/root.json` TUF metadata before extracting any binary.
- **Bounded Opt-In Release Check**: The optional session-start release check (`hooks/release/`) is disabled unless explicitly enabled, reads no credentials, uploads no workspace data, enforces a strict 64 KB response cap and 3-second total timeout, and validates tags against a pinned `release-policy.json`.
