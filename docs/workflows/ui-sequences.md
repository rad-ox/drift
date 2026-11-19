# UI Surface Checks & Interaction Sequence Observation

> **Tier:** Free (UI profile checks, `drift.ui-observation/1` verification in `prove`, `gate`, and `verifier/drift_verify.py`)

DRIFT verifies user-interface contracts without coupling the kernel to a browser or UI toolkit. Surface adapters collect structured `before -> during -> after` interaction observations (`drift.ui-observation/1`) across **Web (Playwright)**, **Jetpack Compose**, and **Windows UIA**.

---

## 1. Multi-Level Pattern Profiles

Use or extend UI pattern profiles such as `async-action-feedback@1` and `wizard-form@1` to govern:

- **Fail-closed surface geometry:** three-valued evidence distinguishing genuinely clipped controls from intentionally scrollable containers.
- **APG focus semantics & visual overlay occlusion:** ensures dialogs, drawers, and popovers preserve focus traps and do not occlude active focus targets.
- **Task-completion recovery:** verifies out-of-order async suppression, selective optimistic rollback, and multi-step wizard continuity.
- **Token derivation provenance & layout guards:** checks static token provenance and opt-in spacing / z-index invariants alongside curated scenario matrices (`evaluateScenarioMatrix`).

---

## 2. Collect & Gate UI Sequence Observations

Adapter helpers (`collectPlaywrightSequence` / `observeUiSequence`) emit `drift.ui-observation/1` records bound to an environment manifest (viewport, DPI/scale, platform, and adapter capabilities—observed-only, never fabricated):

```bash
# Run your UI test suite emitting drift.ui-observation/1 shards into target/drift/events
drift gate .drift/contracts --events target/drift/events --explain

# Independently verify the same UI observation receipts with the MIT verifier
python3 verifier/drift_verify.py .drift/contracts --config .drift/config.toml --events target/drift/events --json
```

Automated UI sequence observations validate declared interaction invariants; they never substitute for human usability study receipts (`*.study.json`) when a regulated control requires `study:<id>` effectiveness evidence (see **[Formal & Regulated Releases](formal-and-regulated.md)**).
