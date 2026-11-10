# Security Policy

## Supported Versions

Security fixes are provided for the latest released `0.5.x` line of DRIFT Free, DRIFT Pro, and DRIFT Enterprise, as well as the open reference verifier (`verifier/`) and polyglot test bridges (`bridges/`).

| Version | Supported |
|---|---|
| `0.5.x` | Yes |
| `< 0.5.0` | No (upgrade to `0.5.x`) |

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
- **Independent Open Verifier (`verifier/drift_verify.py`)**: Every release ships a zero-dependency Python 3 reference verifier under the MIT License so teams and auditors can independently verify `dr1:sha256` (`0.2`) and `dr2b:`/`dr2a:`/`dr2r:` (`0.3`) contract digests, `.jsonl` proof events, `.observation.jsonl` lossless records, `.session.json` supervisor sessions, `.meta.json` test inventories, `.security.json` receipts, and OpenSSH trust-root signatures (`--trust-root`) without trusting the precompiled CLI binary.
- **Package Integrity (`SHA256SUMS`)**: Release archives and installers verify SHA-256 digests before installing or updating binaries, skills, hooks, or Maven artifacts.
- **Bounded Opt-In Release Check**: The optional session-start release check (`hooks/release/`) is disabled unless explicitly enabled, reads no credentials, uploads no workspace data, enforces a strict 64 KB response cap and 3-second total timeout, and validates tags against a pinned `release-policy.json`.
