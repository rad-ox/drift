# AI Coding Agents, Lifecycle Hooks & Desktop Approval UI

> **Tier:** Free (Core skill, native `drift hook`, `drift-ask-ui` Observatory Deck) · Pro/Enterprise (Expanded skills, recall orientation, uncontracted-change Stop checks)

DRIFT is built for **Agentic Specification-Driven Development**: agents draft and verify slice contracts, while the human owner approves behavioural intent before implementation starts.

---

## 1. Agent Skill (`skill/drift/SKILL.md`)

Installing DRIFT deploys the skill into `~/.copilot/skills/` (and `~/.agents/skills/` when present or with `--hooks`) for **GitHub Copilot CLI**, **Claude Code**, **OpenAI Codex CLI**, **Cursor**, **Gemini CLI**, and **Pi**.

When you ask an agent *"Add `POST /items` with DRIFT"*, the workflow enforces four boundaries:

1. **Orient:** checks `.drift/config.toml` (and queries `drift recall query` in Pro/Enterprise).
2. **Draft:** scaffolds `.drift/contracts/<id>.toml`, formats (`drift fmt`), and checks (`drift check`).
3. **Human Approval Gate:** presents the review packet via `drift-ask-ui` on desktop workstations (or `drift review --brief` in terminal/headless sessions) with cases, option trade-offs, and at most 5 open questions. The agent never approves on the owner's behalf.
4. **Implement & Prove:** writes code and bound tests, then verifies `drift gate` is green.

---

## 2. Single-Process Native Lifecycle Hooks (`drift hook`)

Enable automatic guardrails during installation (`./install.sh --hooks` or `.\install.cmd -Hooks`):

```bash
drift hook session   # SessionStart: injects compact area status (and recall hints in Pro/Ent)
drift hook prompt    # UserPromptSubmit: records turn-boundary context
drift hook stop      # Stop: blocks turn completion on DR-E* findings (and unowned edits in Pro/Ent)
drift hook notify    # Notification: forwards drift.attention/1 notices (including WSL2 desktop toasts)
```

Hooks read host JSON payloads from `stdin`, execute offline in a single native process (`< 25 ms`), and leave unknown events inert.

---

## 3. Desktop Approval Broker (`drift-ask-ui`)

On desktop workstations, `drift-ask-ui` automates version-bound snapshot approval (`drift review --detail guided --as json` → `drift approve --reviewed <snapshot> --expect-review <ref> --by <owner>`) with **zero background daemons**:

```bash
drift-ask-ui .drift/contracts          # Open Atmospheric DRIFT Observatory review UI
drift-ask-ui --status                  # Inspect mode (auto/off) and renderer
drift-ask-ui --off                     # Fall back to CLI review/approve
drift-ask-ui --on                      # Re-enable desktop review UI
```

- **Omnichannel Packet & Surface Contract `/2`:** `drift review <file|dir> --as packet [--tier 0|1|2]` projects computed `C0–C4` decision classes and independent slice groups into `drift.decision-packet/1`; `drift-ask-ui` speaks the channel-agnostic surface contract (`drift.ui-surface/1`, `ui-request/2`, `ui-gesture/2`).
- **Renderers:** Native WPF window on Windows 10/11 and WSL2; single-use `127.0.0.1` loopback Observatory Deck on macOS and Linux Desktop; automatic CLI fallback in SSH, headless, or CI sessions (`DRIFT_UI=off`).
- **Decision Clarity:** Anchors trade-off options to a single non-dominated reference, flags dominated choices, surfaces baseline relaxations (`coarsened` / `relaxation_witnesses`), keeps the approver name editable per seal, and requires an intentional `Ctrl+Enter` / `Cmd+Enter` gesture after an anti-clickjacking arming window.
- **Strict Local Boundary:** Zero external network calls, strict CSP, one-time `0600` bootstrap secret, and `0700` staging outside `.drift-work`. Configure dark/light/auto theme in `~/.config/drift/ui.toml` (or `%APPDATA%\drift\ui.toml`) via `[ui].theme = "auto|dark|light"`.
