# Support & Documentation

## Documentation Index

Before opening a support issue, check the reference documentation included in every DRIFT repository and release archive:

- **[`README.md`](README.md)** — Quickstart, core lifecycle, polyglot bridge examples, and architecture overview.
- **[`GUIDE.md`](GUIDE.md)** / **[`GUIDE.it.md`](GUIDE.it.md)** — Comprehensive manual covering adoption levels, schema `0.3` contracts, decision cards, proof states (`missing`, `red`, `bound`, `verified`, `killed`), and CI gates (English and Italian).
- **[`INSTALL.md`](INSTALL.md)** / **[`INSTALL.it.md`](INSTALL.it.md)** — Installation, update, offline Maven setup, agent hook configuration, and uninstallation on Linux, macOS, and Windows (English and Italian).
- **[`EDITIONS.md`](EDITIONS.md)** — Feature matrix and capability boundaries across **DRIFT Free**, **DRIFT Pro**, and **DRIFT Enterprise**.
- **[`GUARANTEES.md`](GUARANTEES.md)** — Formal guarantees, non-guarantees, threat model, and independent verification with `verifier/drift_verify.py`.

## Built-In Diagnostics

Every `DR-E*` finding code and gate failure reason has a built-in explanation and fix recommendation:

```bash
# Explain a contract or event diagnostic code
drift explain DR-E601
drift explain DR-E701

# Inspect version, schema compatibility, and build identity
drift version

# Run the standalone reference verifier self-tests
python3 verifier/drift_verify.py --self-test
```

## Getting Help

- **Bugs & Technical Questions**: Open an issue on [`rad-ox/drift`](https://github.com/rad-ox/drift/issues) including your `drift version` output, operating system, and a minimal contract or test snippet.
- **Security Vulnerabilities**: Do not open a public issue; follow the private reporting instructions in [`SECURITY.md`](SECURITY.md).
- **DRIFT Pro & Enterprise Inquiries**: Contact `rad-ox@users.noreply.github.com`.
- **Complimentary Open-Source Maintainer Grant**: Owners of public OSI-licensed open-source repositories may request a free **DRIFT Enterprise** license for their public repositories by emailing `rad-ox@users.noreply.github.com` with the repository URL (subject to Part III, Section 2 of [`LICENSE`](LICENSE)).
