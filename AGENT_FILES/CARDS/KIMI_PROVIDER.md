# Kimi Provider (experimental)

> **Load when**: working on the Kimi Agent SDK integration, `KimiAgentSession`, or provider routing beyond Claude/Ollama.
> **Skip when**: changes don't touch model providers.

The dashboard's first **non-Claude agent runtime**. Unlike Ollama (which is a
*profile* of the Claude Agent SDK redirected via env vars — see
[OLLAMA_PROVIDER](OLLAMA_PROVIDER.md)), Kimi models run through the separate
in-process **Kimi Agent SDK** (`kimi-agent-sdk`, installed from a git fork —
see Requirements; its ACP client drives whatever `kimi` binary is on PATH
rather than an embedded runtime).

## Routing

- Model ids starting with `kimi-` route to `KimiAgentSession`
  (`src/agent/profiles.py` `is_kimi_model`; `is_ollama_model` explicitly
  excludes `kimi-*` so an Ollama-enabled workspace never captures them).
- `SessionService.create_session` (`src/services/session_service.py`) branches
  to `KimiAgentSession` before any Ollama/Claude handling.
- Kimi entries (the model feed's `kimi-code-plan-global` provider, ids prefixed `kimi-code/` by `model_catalog`; bundled `constants.KIMI_MODELS` offline) are marked `experimental=True`,
  so they only appear in model dropdowns when the server runs with
  `--experimental` (template-level gating in `board.html`). No DB migration or
  config flag — selection is purely by model id.
- The ids are **kimi-code model aliases** (the CLI's `-m` values), not raw
  API model names: `kimi-code/k3` (K3, the CLI default),
  `kimi-code/k3-256k` (K3-256K), `kimi-code/kimi-for-coding`,
  `kimi-code/kimi-for-coding-highspeed`. Check what an install actually
  offers with `kimi provider list` / `~/.kimi-code/config.toml` — aliases are
  per-install configuration, not a fixed catalog.

## `KimiAgentSession` (`src/agent/kimi_session.py`)

Implements the `AbstractAgentSession` contract (`src/agent/base.py`) over
**ACP**: `start()` spawns a background task that connects
`kimi_agent_sdk.acp.AcpClient` — which spawns `kimi acp` (the Kimi Code CLI
as an Agent Client Protocol server, CLI >= 0.27.0, JSON-RPC over stdio) —
and streams session updates. The ACP module is stdlib-only and targets
whatever `kimi` binary is on PATH; the model is selected per session via an
ACP `session/set_config_option` request (`configId: "model"`, since `kimi acp`
has no model flag), with `KIMI_MODEL_NAME` on the subprocess env as a fallback.

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
`view_board` / `who_am_i` / `peek_worktree` (via `GET
/api/items/{id}/peek`) to the dashboard's HTTP API. `main.py` publishes
the server's own base URL as `DASHBOARD_BASE_URL`; the proxy also gets
`DASHBOARD_ITEM_ID` (who_am_i + creator attribution). Tools surface to the
agent as `mcp__board__*`. `create_todo` has **full Claude-path parity**: it
posts to `POST /api/items/{creator_id}/agent-todos` (route →
`orchestrator.create_agent_todo` → the same `workflow_service` callback the
Claude MCP tool uses), so `requires` dependencies, `autostart` with the
unmerged-creator auto-anchor, `auto_approve`, and `use_chrome` all behave
identically (live-verified: a Kimi-created autostart todo was auto-anchored
to its creator card).

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
- **Debug**: `KIMI_FORCE_PERMISSION_ASK=1` in the server env escalates
  every execute permission request that kimi raises to the user
  (bypassing allowlist/bash_yolo) — a repeatable way to demo the ASK
  approval flow. It cannot make kimi ask more often; it only changes the
  answer side.

### Worktree confinement — read this before trusting `--experimental`

`KimiAgentSession` builds a `path_guard.PathScope` (the same predicate the
Claude `path_guard` PreToolUse hook uses) with **`strict_writes=True`**, and
`_decide_permission` denies any permission request whose path arguments leave
it: writes must stay inside the worktree, reads may also reach the workspace
root in multi-repo mode. Paths come from the ACP tool call's `rawInput` (keys
in `_PATH_KEYS`/`_PATH_LIST_KEYS` — `path` is what kimi-code sends, the
Claude-style aliases are there for other tools) plus ACP's schema'd
`locations[].path`. Relative paths resolve against the worktree, `~` is
expanded, and `.resolve()` collapses `..` and symlinks. A tool kind outside
`_READ_ONLY_KINDS` (`read`/`search`/`think`/`fetch`) — including a **missing**
kind — is checked as a write, so an unrecognized tool fails closed.
`bash_yolo` does not relax this; it governs shell commands only.

**The residual gap (why this is mitigation, not a hard boundary)**: the
Claude guard is a PreToolUse hook, so it sees *every* tool call. On the Kimi
side, **kimi-code's own classifier decides which calls raise a
`session/request_permission`** — an edit it deems safe never reaches
`permission_handler` and therefore cannot be refused there. ACP exposes no
stricter mode and no client-side filesystem interposition in the SDK's ACP
client, so for calls kimi never asks about, confinement is still `cwd` plus the
prompt instruction. What we do have for those: every streamed tool call goes
through `KimiAgentSession.audit_tool_call_scope`, which logs a `WARNING`
naming the out-of-boundary path and the item — detection and an audit trail,
not prevention. **Running a Kimi agent is therefore a weaker containment
guarantee than running a Claude agent**; `--experimental` is a trust decision.
See AUDIT.md finding #15. If the ACP client ever grows client-side
`fs/read_text_file` / `fs/write_text_file` handling, moving the check there
would close the gap for real.

**Project context files**: kimi-cli natively discovers and merges
`AGENTS.md` (root `AGENTS.md`/`agents.md` + `.kimi/AGENTS.md`, project
root down to workdir) — nothing to do when the target project has one.
It never reads `CLAUDE.md`, so `KimiAgentSession` injects the worktree
`CLAUDE.md` into the prompt **only when no AGENTS.md variant exists**
(always on, no config flag — unlike Ollama's opt-in, context size isn't a
concern at 262k).

Remaining limitations (deliberate, mirrors the lean Ollama feature set):

- No external MCP servers / plugins / chrome / graphify.
- System prompt is prepended to the user prompt (ACP has no separate
  system-prompt input).
- **Auto-review**: `workflow_service` skips the one-shot reviewer for Kimi
  models (it runs on the Claude SDK) and leaves the item in Review for a
  human, with a log line.

## Requirements

- `kimi-agent-sdk` — installed via `requirements.txt` from the
  `epatel/kimi-agent-sdk@agentic-setup` fork branch (PyPI <= 0.0.5 lacks the
  ACP client). The requirement is the bare git URL, so **no version floor is
  enforced** — the branch is the contract. The import is lazy — the dashboard runs fine without it;
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

`tests/unit/test_kimi_session.py` (88 tests; fake `kimi_agent_sdk` module
injected via `sys.modules`) — including `TestToolCallPaths`,
`TestPathBoundary`, `TestSessionPathScope` and `TestAuditToolCallScope` for
worktree confinement. Plus `TestKimiRouting` in `test_session_service.py`,
`TestIsKimiModel` in `test_profiles.py`. The `PathScope` predicate itself is
also exercised through the Claude hook in `tests/smoke/test_multi_repo.py`.

---

**See also**: [OLLAMA_PROVIDER](OLLAMA_PROVIDER.md) (the profile-based provider), [ARCHITECTURE](ARCHITECTURE.md) (session contract, `SessionService`).
