## Summary

<!-- Briefly describe what this pull request changes and why. Reference any related issue (e.g., Fixes #123). -->

## Target Surface

- [ ] Language Bridges (`bridges/`)
- [ ] Open Reference Verifier (`verifier/drift_verify*.py`)
- [ ] Agent & Git Hooks (`hooks/`)
- [ ] Editor JSON Schemas (`schemas/`)
- [ ] Agent Skill (`skill/drift/`)
- [ ] Example Service (`example/`)
- [ ] Installers (`install.sh`, `install.ps1`, `install.cmd`, `uninstall.cmd`)
- [ ] Documentation (`README.md`, `GUIDE*.md`, `INSTALL*.md`, `EDITIONS.md`, `GUARANTEES.md`)

## Engineering Standards Checklist

- [ ] **Zero External Runtime Dependencies**: Bridges and `verifier/drift_verify.py` rely only on the target language's standard library (or JUnit Platform / JUnit 4 for JVM bridges).
- [ ] **Fail-Closed Verification**: Malformed JSON, missing `then` projections, uninspected assertions, and tampered `.meta.json` sidecars are never silently ignored.
- [ ] **CLI & Verifier Parity**: Any change to `verifier/drift_verify*.py` preserves field-by-field JSON and exit-code parity with `drift gate`.
- [ ] **Bilingual Documentation**: User-facing workflow or installer updates keep `GUIDE.md` / `GUIDE.it.md` and `INSTALL.md` / `INSTALL.it.md` synchronized.

## Local Validation

```bash
python3 verifier/drift_verify.py --self-test
drift check example/.drift
drift status example/.drift/contracts
drift review example/.drift/contracts --brief
```

- [ ] All local validation commands above pass with exit code `0`.

## License

- [ ] I confirm that this contribution to the Open Integration Surface is submitted under the **MIT License** as set forth in [`LICENSE`](LICENSE) and [`CONTRIBUTING.md`](CONTRIBUTING.md).
