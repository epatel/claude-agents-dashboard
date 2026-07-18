# Kimi Provider (experimental)

> **Load when**: working on the Kimi Agent SDK integration, `KimiAgentSession`, or provider routing beyond Claude/Ollama.
> **Skip when**: changes don't touch model providers.

The dashboard's first **non-Claude agent runtime**. Unlike Ollama (which is a
*profile* of the Claude Agent SDK redirected via env vars — see
[OLLAMA_PROVIDER](OLLAMA_PROVIDER.md)), Kimi models run through the separate
in-process **Kimi Agent SDK** (`kimi-agent-sdk` on PyPI, embedding the
`kimi-cli` runtime).

## Routing

- Model ids starting with `kimi-` route to `KimiAgentSession`
  (`src/agent/profiles.py` `is_kimi_model`; `is_ollama_model` explicitly
  excludes `kimi-*` so an Ollama-enabled workspace never captures them).
- `SessionService.create_session` (`src/services/session_service.py`) branches
  to `KimiAgentSession` before any Ollama/Claude handling.
- Kimi entries in `constants.AVAILABLE_MODELS` are marked `experimental=True`,
  so they only appear in model dropdowns when the server runs with
  `--experimental` (template-level gating in `board.html`). No DB migration or
  config flag — selection is purely by model id.

## `KimiAgentSession` (`src/agent/kimi_session.py`)

Implements the `AbstractAgentSession` contract (`src/agent/base.py`):
`start()` spawns a background task that drives the SDK's high-level
`prompt(...)` async generator; `cancel()` cancels it. Messages map to the
dashboard callbacks: assistant text → `on_message`, tool calls (name + parsed
JSON arguments) → `on_tool_use`, normal end of stream →
`on_complete(AgentResult(success=True))`, exceptions → `on_error`.

First-cut limitations (deliberate, mirrors the lean Ollama feature set):

- `yolo=True` — Kimi's approval requests are auto-approved; the dashboard's
  per-command permission hooks are Claude-SDK constructs and don't apply.
- No dashboard MCP tool servers / plugins / chrome / graphify. Consequences:
  no `set_commit_message` (merge uses the default commit message), no
  `ask_user` clarification, no board tools.
- No pause/resume — `current_session_id` stays `None`; a paused item restarts
  fresh. The SDK's `Session.resume` can lift this later.
- System prompt is prepended to the user prompt (the SDK has no separate
  system-prompt input; an `agent_file` could carry it later).
- **Auto-review**: `workflow_service` skips the one-shot reviewer for Kimi
  models (it runs on the Claude SDK) and leaves the item in Review for a
  human, with a log line.

## Requirements

- `pip install kimi-agent-sdk` into the dashboard venv (Python >= 3.12; the
  package hard-pins a `kimi-cli` minor version). The import is lazy — the
  dashboard runs fine without it; starting a Kimi session without the package
  reports `KIMI_SDK_INSTALL_HINT` via `on_error`.
- `KIMI_API_KEY` (optionally `KIMI_BASE_URL`, `KIMI_MODEL_NAME`) in the
  server environment.

## Frontend

- `dialog-utils.js`: `_isKimiModel` / `_getModelProvider` → "Kimi" badge
  (`.provider-badge-kimi` in `style.css`). Kimi ids are in the server-rendered
  model list (so also in `__ANTHROPIC_MODEL_IDS__`) — the kimi- prefix check
  runs first and wins.

## Tests

`tests/unit/test_kimi_session.py` (fake `kimi_agent_sdk` module injected via
`sys.modules`), `TestKimiRouting` in `test_session_service.py`,
`TestIsKimiModel` in `test_profiles.py`.

---

**See also**: [OLLAMA_PROVIDER](OLLAMA_PROVIDER.md) (the profile-based provider), [ARCHITECTURE](ARCHITECTURE.md) (session contract, `SessionService`).
