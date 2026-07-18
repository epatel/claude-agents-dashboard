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
- The ids are **kimi-code model aliases** (the CLI's `-m` values), not raw
  API model names: `kimi-code/k3` (K3, the CLI default),
  `kimi-code/kimi-for-coding` (K2.7 Coding),
  `kimi-code/kimi-for-coding-highspeed`. Check what an install actually
  offers with `kimi provider list` / `~/.kimi-code/config.toml` — aliases are
  per-install configuration, not a fixed catalog.

## `KimiAgentSession` (`src/agent/kimi_session.py`)

Implements the `AbstractAgentSession` contract (`src/agent/base.py`) over
**ACP**: `start()` spawns a background task that connects
`kimi_agent_sdk.acp.AcpClient` — which spawns `kimi acp` (the Kimi Code CLI
as an Agent Client Protocol server, CLI >= 0.27.0, JSON-RPC over stdio) —
and streams session updates. The ACP module is stdlib-only and targets
whatever `kimi` binary is on PATH; the model is passed via the
`KIMI_MODEL_NAME` env var on the subprocess (ACP has no model param).

Update mapping (partial chunks are aggregated into message-sized entries):
`AgentMessageChunk` → `on_message`, `AgentThoughtChunk` → `on_thinking`,
tool calls → `on_tool_use` — deferred: kimi-code sends `rawInput` (and richer
titles like "Reading app.py") on `tool_call_update`/`ToolCallProgress`, not the
initial `tool_call`, so `_PendingToolCall` holds the call until input arrives
(bounded by completed/failed status, the next tool call, or turn end),
`TurnEnded("end_turn")` → `on_complete(AgentResult(success=True))`,
abnormal stop reasons (`max_tokens`/`max_turn_requests`/`refusal`) and
exceptions → `on_error`. `cancel()` sends ACP `session/cancel`, then tears
down the task/subprocess.

**Pause/resume works**: the ACP session id is captured in
`current_session_id`; on restart the session is resumed via ACP
`session/load` (falls back to a fresh session if the agent lacks the
capability).

**Marked-line text protocols** (Kimi agents have no dashboard MCP tools, so
these travel in the agent's text and are parsed out before it reaches the
work log — both live-verified):

- `COMMIT_MESSAGE: <msg>` on the last line of the final message →
  `on_set_commit_message` (labels the merge commit).
- `ASK_USER: <question>` ends the turn → `on_clarify` blocks in the Clarify
  ("questions") column; the user's answer is sent as the next prompt turn on
  the same stateful ACP session (`User's answer: …`). Chains multiple
  questions. Both instructions are appended to the prompt only when the
  corresponding callback is wired.

**Board tools** (live-verified): `src/agent/kimi_board_mcp.py` is a
stdlib-only stdio MCP server declared in the ACP session's `mcpServers` —
the Kimi runtime spawns it (with the venv's `sys.executable`), and it
proxies `create_todo` / `delete_todo` / `create_epic` / `create_shortcut` /
`view_board` / `who_am_i` to the dashboard's HTTP API. `main.py` publishes
the server's own base URL as `DASHBOARD_BASE_URL`; the proxy also gets
`DASHBOARD_ITEM_ID` (for who_am_i) and `DASHBOARD_REPO` in multi-repo mode
(create_todo's required repo field). Tools surface to the agent as
`mcp__board__*`. Unlike the Claude path's in-process
`create_sdk_mcp_server` objects, this goes through HTTP — no
`workflow_service` callback plumbing (so e.g. create_todo has no
autostart/requires support yet).

**Permission hooks**: the ACP client runs with `yolo=False` and a real
`permission_handler`. Trust model — **kimi decides WHEN to ask, the
dashboard decides the ANSWER**:

- kimi-code's own safety classifier raises `session/request_permission`
  only for operations it deems risky (heuristic and context-dependent —
  worktree-scoped shell like `touch`/`rm` typically auto-executes in the
  session's "default" mode; a `git push` triggered a request in one probe
  but not in another where the task framed it as harmless). There is no
  ACP mode stricter than "default" (options: default/plan/auto/yolo).
- When a request arrives, `_decide_permission` applies the Claude path's
  semantics: non-execute tool calls allowed (acceptEdits-equivalent);
  shell allowed when `bash_yolo` or the first word is in
  `allowed_commands`; shell operators and unlisted commands escalate to
  `on_request_command` — the existing approval flow (item pauses in ASK,
  approval saves the command to the allowlist and restarts the session
  with resume; denial rejects inline). Denied without a callback.
- Verified at the protocol level (raw ACP probe: a request arrived for
  `git push` and a reject outcome stopped the tool) and fully unit-tested;
  a deterministic live trigger doesn't exist because the classifier is
  heuristic.

Remaining limitations (deliberate, mirrors the lean Ollama feature set):

- No external MCP servers / plugins / chrome / graphify.
- System prompt is prepended to the user prompt (ACP has no separate
  system-prompt input).
- **Auto-review**: `workflow_service` skips the one-shot reviewer for Kimi
  models (it runs on the Claude SDK) and leaves the item in Review for a
  human, with a log line.

## Requirements

- `kimi-agent-sdk` >= 0.0.6 — installed via `requirements.txt` from the
  `epatel/kimi-agent-sdk@agentic-setup` fork branch (PyPI <= 0.0.5 lacks the
  ACP client). The import is lazy — the dashboard runs fine without it;
  starting a Kimi session without the package reports `KIMI_SDK_INSTALL_HINT`
  via `on_error`. Note: the *runtime* no longer depends on the package's
  `kimi-cli` pin (ACP talks to the PATH binary), but pip still installs the
  pinned `kimi-cli` as a package dependency.
- Kimi Code CLI (`kimi`) >= 0.27.0 on PATH — it is the execution engine
  (`kimi acp`).
- **Auth**: credentials follow the Kimi Code model — a one-time `kimi login`
  (OAuth tokens stored/refreshed by the CLI) is sufficient; no key to plumb
  through. `KIMI_API_KEY` (optionally `KIMI_BASE_URL`) is the headless/CI
  alternative.

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
