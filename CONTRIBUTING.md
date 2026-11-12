# Contributing to DRIFT

Thank you for your interest in contributing to DRIFT.

## Dual-Surface Repository Model

DRIFT is distributed under a dual-surface license model (see [`LICENSE`](LICENSE)):

1. **Open Integration Surface (MIT License)** — All polyglot test bridges (`bridges/`), the independent reference proof verifier (`verifier/`), agent and Git hooks (`hooks/`), editor JSON Schemas (`schemas/`), the Free agent skill (`skill/drift/`), the synthetic example service (`example/`), installers (`install.sh`, `install.ps1`, `install.cmd`, `uninstall.cmd`), and documentation (`*.md`).
2. **DRIFT CLI Engine (`drift` / `drift.exe`)** — The precompiled CLI binary is proprietary software governed by the DRIFT Free Edition License.

Community pull requests are welcome across the entire **Open Integration Surface**, including:

- Bug fixes, diagnostics, and runtime hardening for language bridges (JVM/JUnit 5, Legacy JUnit 4, Scala/MUnit, JavaScript/TypeScript, Python, Rust, V, PHP, COBOL, C++20, C#/.NET, and GDScript).
- Improvements and parity tests for the independent reference verifier (`verifier/drift_verify*.py`).
- Agent hook compatibility (`hooks/drift-hook.sh`, `hooks/drift-notify-wsl.sh`, `hooks/drift-hook.ps1`, `hooks/drift-pi.ts`) across coding assistants.
- JSON Schema refinements (`schemas/*.schema.json`) and documentation improvements in English (`GUIDE.md`, `INSTALL.md`) and Italian (`GUIDE.it.md`, `INSTALL.it.md`).

## Engineering Standards

When submitting a pull request to the Open Integration Surface:

1. **Zero External Runtime Dependencies**: Bridges and `verifier/drift_verify.py` must remain standalone and rely only on the target language's standard library (or JUnit Platform / JUnit 4 for JVM bridges).
2. **Fail-Closed Verification**: Bridges and verifiers must never silently ignore malformed JSON, missing `then` projections, uninspected assertions, or tampered `.meta.json` sidecars.
3. **CLI & Verifier Parity**: Any change to `verifier/drift_verify.py` must preserve field-by-field JSON and exit-code parity with `drift gate`.
4. **Bilingual Documentation**: User-facing installation or workflow changes should keep `GUIDE.md` / `GUIDE.it.md` and `INSTALL.md` / `INSTALL.it.md` synchronized.

## Running Local Validation

Before opening a pull request against [`rad-ox/drift`](https://github.com/rad-ox/drift), run the local verification suite:

```bash
# 1. Run the independent reference verifier self-test suite
python3 verifier/drift_verify.py --self-test

# 2. Validate the example area with the CLI and open verifier
drift check example/.drift
drift status example/.drift/contracts
drift review example/.drift/contracts --brief
```

## Reporting Bugs and Feature Requests

- **Bug Reports**: Open an issue on [`rad-ox/drift`](https://github.com/rad-ox/drift/issues) with the output of `drift version`, your OS/architecture, and a minimal `.drift/contracts/*.toml` or bridge snippet that reproduces the problem.
- **Security Issues**: Follow [`SECURITY.md`](SECURITY.md) for private disclosure.

## License of Contributions

By submitting a pull request or patch to the Open Integration Surface, you agree that your contribution is licensed under the **MIT License** as set forth in Part I of [`LICENSE`](LICENSE).
