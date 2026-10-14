# Security Audit Report

**Date**: 2026-04-10
**Last updated**: 2026-10-14 (rev 13 — remediation pass on **#15**, the one open actionable finding of rev 12. The worktree boundary predicate was factored out of `src/agent/path_guard.py` into a shared `PathScope`, and the Kimi runtime now uses it: `_decide_permission` **denies** any ACP permission request whose path arguments resolve outside the agent's worktree (strict writes; reads keep the Claude scope, including the workspace root in multi-repo mode), and every streamed tool call is checked by `KimiAgentSession.audit_tool_call_scope`, which logs a boundary-violation `WARNING`. #15 moves from Open to **Mitigated**, not Remediated: kimi-code's own classifier decides which calls raise a permission request, so calls it never asks about can be logged but not blocked — that residual gap is now documented in `CARDS/KIMI_PROVIDER.md`, the `--experimental` help text and the startup banner. 31 new tests (`test_kimi_session.py` 57 → 88). No new findings; no other finding's status changed.)

**Rev 12 note**: 2026-10-08 (first review of the subsystems added since rev 11: the **Kimi runtime** (`src/agent/kimi_session.py`, `kimi_board_mcp.py`), **`peek_worktree`**, the **skills library** (`src/services/skills_service.py`), the **graphify** surface (`GraphService` + `graph_query`), and the **model feed** (`src/model_catalog.py`). **Three new findings — #15 (Medium), #16 (Low), #17 (Info)** — all open; see "Findings added in rev 12". The headline is #15: Kimi agents are confined to their worktree by `cwd` plus a prompt instruction, with no enforcing `path_guard` equivalent, so the containment guarantee that holds for Claude agents does **not** hold for Kimi agents. It is gated behind `--experimental`. Migrations 025–031 were reviewed and add no shell or SQL-construction surface: 025/026/028/029/030 are column adds, 027 and 031 are parameterized `UPDATE`s (027 uses `REPLACE(model, '+advisor', '')`, 031 rewrites the default model including the `[1m]` variant). All prior remediations still stand; no previously-fixed finding regressed.)

**Rev 11 note**: 2026-05-28 (re-confirmed against migration 024 (`024_update_default_model_to_opus_4_8.py`) and the extended-thinking budget increase (10,000 → 32,000 tokens) in `src/agent/session.py`. **No new security findings.** Migration 024 is a pure data migration (parameterized `UPDATE` of the `model` column across `items`/`agent_config`, with a reversible `down()`) — no shell or SQL-construction surface. Raising the thinking budget changes only token allocation, not the agent-containment boundary, the path guard, or the command filter; all prior remediations stand. Rev 10 notes remain accurate: re-confirmed against migrations 022 (`auto_approve`) and 023 (`pause_message`), plus the auto-review agent at `src/agent/review_agent.py`. The auto-review agent runs as a strictly read-only Claude session — its `can_use_tool` allowlist is `Read`/`Glob`/`Grep` only, with `Edit`/`Write`/`Bash` denied via `PermissionResultDeny`, so the review-agent path does not widen the agent-containment surface; cycle bookkeeping (max 3 retries) lives in `WorkflowService` outside the SDK call. The `pause_message` column is plain user text prepended to the resume prompt — no shell or SQL surface added (parameterized writes via the repo). Finding #5 (dynamic SQL column names) remains remediated and the whitelist constants are `_WRITABLE_*_COLUMNS` (private to each repository module — `_WRITABLE_ITEM_COLUMNS` in `repositories/item_repository.py`, `_WRITABLE_EPIC_COLUMNS` in `repositories/epic_repository.py`). The `AgentConfig` Phase 3 refactor is unchanged.)
**Scope**: Full codebase review of Claude Agents Dashboard
**Threat model**: Localhost single-user developer tool. The server binds to `127.0.0.1` only, is operated by the local developer, and is not designed for network exposure or multi-user access. In multi-repo workspace mode the same threat model applies — agents work in a worktree inside one chosen sibling repo and have read-only access to the other siblings via `add_dirs`, with the path guard hook (`path_guard.py`) preventing writes outside the assigned worktree.

---

## Executive Summary

This audit has identified **17 security findings** relevant to a localhost developer tool: 2 High, 6 Medium, and 9 Low/Info. Of the 10 actionable findings, **9 are remediated and 1 (#15, Kimi path confinement) is mitigated** as of rev 13 — out-of-worktree paths are now denied on every ACP permission request the Kimi runtime receives and logged on the tool calls kimi never asks about, which is the most that can be enforced from outside the CLI. The one fully open actionable finding is **#16** (Low, defense-in-depth).

The two original high-severity findings (command filter bypass and YOLO mode) have both been addressed with robust fixes. The five original medium-severity findings have been resolved, including `.browserhidden` support for project-specific secret patterns. Two low-severity findings (epic color validation and security headers) have also been fixed.

**Posture**: strong for the default Claude-only configuration, which is what the containment design was built around. The experimental providers are still weaker: a Kimi agent's worktree boundary is enforced only on the tool calls kimi-code chooses to raise a permission request for — the rest are logged, not blocked (#15). Treat `--experimental` as a trust decision, not just a feature flag.

Traditional web security concerns (authentication, CORS, rate limiting) are largely irrelevant since the server only listens on `127.0.0.1` for a single local user. This audit focuses on the risks that actually matter: **agent containment**, **file system boundary enforcement**, and **defensive coding practices**.

---

## High Severity — Agent Containment

### 1. Command Filter Bypass via Shell Metacharacters

- **Severity**: High
- **Status**: ✅ **REMEDIATED**
- **File**: `src/agent/command_filter.py`
- **Original issue**: The command filter extracted the first word via `command.split()[0]` and checked it against allowed prefixes. An agent could bypass this with shell operators (`;`, `&&`, `||`, `|`, backticks, `$()`).
- **Fix implemented**: The command filter now defines `SHELL_OPERATORS = [";", "&&", "||", "|", ">>", ">", "<", "$(", "\`"]` and calls `_contains_shell_operators()` to reject any command containing shell operators **before** checking the allowed prefix list. Additionally, `shlex.split()` is used for robust parsing with a fallback that denies commands on malformed input.

### 2. Bash YOLO Mode Has No Guardrails

- **Severity**: High
- **Status**: ✅ **REMEDIATED**
- **File**: `src/services/workflow_service.py`
- **Original issue**: When `bash_yolo` was enabled, agents ran with `permission_mode="bypassPermissions"` with no audit trail, no confirmation, and no visibility into what commands were being executed.
- **Fix implemented**: YOLO mode now has comprehensive tracking and logging:
  - Active YOLO items are tracked via `self._yolo_items` set.
  - A `"⚠️ **YOLO mode active**"` warning is logged as a `"yolo_command"` entry type when YOLO mode activates.
  - Bash commands executed under YOLO mode are tagged with `entry_type = "yolo_command"` and prefixed with `⚡` for visual distinction in the work log.
  - `yolo_mode_changed` WebSocket events are broadcast to the UI so the user has real-time visibility.
  - YOLO tracking is properly cleaned up on cancel/complete.

---

## Medium Severity — File System Boundaries

### 3. Symlink Following in File Browser

- **Severity**: Medium
- **Status**: ✅ **REMEDIATED**
- **File**: `src/web/file_routes.py`
- **Original issue**: The file browser tree scanner followed symlinks, allowing browsing outside the project directory.
- **Fix implemented**: The tree scanner now skips symlinks entirely (`if entry.is_symlink(): continue`). Symlinks are displayed as visual indicators with their target path but are never followed or read. The `get_file_content()` endpoint explicitly blocks reading symlinks (returns 403).

### 4. Unvalidated File Paths in Diff Generation

- **Severity**: Medium
- **Status**: ✅ **REMEDIATED**
- **File**: `src/git/operations.py`
- **Original issue**: Untracked filenames from `git ls-files --others` were used directly to read files without validation.
- **Fix implemented**: Each untracked filename now passes through `validate_file_path()` before use. The resolved path is verified to be within the worktree via string prefix and exact equality checks. Exceptions are caught and the file is skipped on error. Both `get_diff()` and `get_changed_files()` apply this validation.

### 5. Dynamic SQL Column Names

- **Severity**: Medium (code quality)
- **Status**: ✅ **REMEDIATED**
- **File**: `src/services/database_service.py`
- **Original issue**: `update_item()` built SQL with f-string column names from dict keys without validation.
- **Fix implemented**: A `_WRITABLE_ITEM_COLUMNS` whitelist is enforced on every item write (renamed from `ALLOWED_ITEM_COLUMNS` in rev 10; private to the module). As of rev 9 the whitelist lives in `repositories/item_repository.py` (moved out of `database_service.py`) and is checked in `update_fields()` / `transition()` before any SQL is built — invalid keys raise `ValueError`. The equivalent epic whitelist (`_WRITABLE_EPIC_COLUMNS`) is enforced in `repositories/epic_repository.py` (the old `ALLOWED_EPIC_COLUMNS` constant in `database_service.py` was deleted because all writes now route through the repo).

### 6. No CORS Middleware

- **Severity**: Medium
- **Status**: ✅ **REMEDIATED**
- **File**: `src/web/app.py`
- **Original issue**: No `CORSMiddleware` was configured, allowing cross-origin attacks from malicious websites.
- **Fix implemented**: CORS middleware is now configured via `_build_cors_origins()`, which restricts allowed origins to `localhost` and `127.0.0.1` across ports 8000–8019. This prevents malicious websites from making cross-origin requests to the local server.

### 7. Secret File Detection Is Pattern-Based

- **Severity**: Medium
- **Status**: ✅ **REMEDIATED**
- **File**: `src/web/file_routes.py` (`is_secret_file()`)
- **Original issue**: The file browser hid files matching known secret patterns (`.env`, `*.key`, `*.pem`, etc.) but files with non-standard names containing secrets were not detected.
- **Fix implemented**: A `.browserhidden` configuration file (similar to `.gitignore`) is now supported. Projects can define custom glob patterns in a `.browserhidden` file at the project root. The implementation includes:
  - `parse_browserhidden()` parses the config file (comments with `#`, one pattern per line).
  - `load_browserhidden_patterns()` caches parsed patterns with mtime-based invalidation.
  - `matches_browserhidden()` matches filenames and relative paths against patterns.
  - `is_secret_file()` checks both built-in patterns and `.browserhidden` patterns.
  - Patterns are loaded and applied throughout the tree scanner, file content reader, and worktree file browser.

---

## Low / Informational Findings

### 8. Agent Work Log May Contain Sensitive Data

- **Severity**: Low
- **Status**: ⚠️ **OPEN** (accepted risk)
- **Files**: `src/services/notification_service.py`
- **Description**: Agent output (command results, file contents, error messages) is logged to the work log without redaction. If an agent reads a `.env` file or a command prints credentials, they appear in the UI and are stored in the SQLite database.
- **Why it's low for localhost**: The local user already has access to these secrets. The concern is that the work log persists them in the database, making them less ephemeral than they would be in a terminal.
- **Recommendation**: Consider adding optional log redaction for common patterns (`sk-...`, `ghp_...`, API key formats) as a nice-to-have.

### 9. Git Output Not Sanitized

- **Severity**: Low
- **Status**: ⚠️ **OPEN** (cosmetic)
- **File**: `src/git/operations.py`
- **Description**: Git stderr from failed operations may contain ANSI escape codes or control characters, which are passed through to the UI.
- **Mitigating factor**: Jinja2 auto-escapes HTML, and `marked.js` handles the rendering. The risk is cosmetic (garbled output), not exploitable.
- **Recommendation**: Strip ANSI codes from git output for cleaner display.

### 10. Epic Color Input Not Validated

- **Severity**: Low
- **Status**: ✅ **REMEDIATED**
- **File**: `src/models.py`
- **Original issue**: `EpicCreate` accepted any `color: str` without validating against the `EPIC_COLORS` whitelist.
- **Fix implemented**: Both `EpicCreate` and `EpicUpdate` now have a `@field_validator("color")` that validates against `VALID_EPIC_COLOR_KEYS` (derived from `EPIC_COLORS` in `constants.py`). Invalid color values raise a `ValueError` listing the valid options (red, orange, amber, green, teal, blue, purple, pink).

### 11. WebSocket X-Forwarded-For Trusted Unconditionally

- **Severity**: Info
- **Status**: ⚠️ **OPEN** (by design for localhost)
- **File**: `src/web/websocket.py`
- **Description**: `_get_client_ip()` trusts the `X-Forwarded-For` header, taking the first comma-separated value. Also checks `X-Real-IP` before falling back to `websocket.client.host`. On localhost without a reverse proxy, this is irrelevant — all connections come from `127.0.0.1`.
- **Recommendation**: No action needed for localhost use. If ever deployed behind a proxy, add trusted proxy validation.

### 12. No Authentication

- **Severity**: Info (for localhost)
- **Status**: ⚠️ **OPEN** (by design)
- **Files**: `src/web/app.py`, `src/web/routes.py`
- **Description**: No authentication on any endpoint. For a single-user localhost tool, this is the correct design — authentication would add friction with no security benefit since the only user is the local developer.
- **Recommendation**: No action needed. If the application is ever exposed to a network, authentication becomes critical.

### 13. HTTP Only (No TLS)

- **Severity**: Info
- **Status**: ⚠️ **OPEN** (by design)
- **File**: `src/config.py`
- **Description**: Plain HTTP on localhost. Since traffic never leaves the loopback interface, TLS provides no benefit.
- **Recommendation**: No action needed for localhost.

### 14. Missing Security Response Headers

- **Severity**: Info
- **Status**: ✅ **REMEDIATED**
- **File**: `src/web/app.py`
- **Original issue**: No security response headers were set on HTTP responses.
- **Fix implemented**: A `SecurityHeadersMiddleware` (Starlette `BaseHTTPMiddleware`) is registered on the app and sets two headers on every response:
  - `X-Content-Type-Options: nosniff` — prevents MIME type sniffing.
  - `X-Frame-Options: DENY` — prevents clickjacking via iframe embedding.

---

## Findings added in rev 12

These cover the subsystems that landed after rev 11 and had never been reviewed.

### 15. Kimi Agents Are Not Confined to Their Worktree by an Enforcing Hook

- **Severity**: Medium (High class, reduced by the `--experimental` gate) — residual: Low
- **Status**: 🟡 **MITIGATED (rev 13, 2026-10-14)** — see "Remediation" below. The enforceable part is enforced; a documented residual gap remains because kimi-code, not the dashboard, decides which tool calls raise a permission request.
- **Files**: `src/agent/kimi_session.py` (`_decide_permission`, `_tool_call_paths`, `_scope_violations`, `KimiAgentSession.audit_tool_call_scope`), `src/agent/path_guard.py` (`PathScope`), `src/services/session_service.py` (passes `workspace_root`)
- **Description**: For Claude agents, worktree confinement is **enforced**: the `path_guard.py` PreToolUse hook denies `Edit`/`Write` outside the agent's worktree and limits `Read`/`Glob`/`Grep` to the workspace root. The Kimi runtime wires no equivalent. Its ACP permission callback returns `"allow"` for every non-execute tool call (`kimi_session.py:132-133` — "like `permission_mode="acceptEdits"`"), and the only things keeping a Kimi agent inside its worktree are the `cwd` passed to the ACP session and a natural-language instruction in the prompt ("IMPORTANT: Your working directory is …").
- **Exploitation / failure scenario**: A Kimi agent that writes an **absolute path** — whether through model error, a confused multi-repo task, or prompt injection from a file it read — edits files outside its worktree. Nothing denies the call, nothing logs it as a boundary violation, and the write lands in the user's real working tree or home directory rather than in the isolated worktree the review-and-merge model assumes. The dashboard's whole safety story is "agent changes are quarantined until you approve them"; for Kimi that is a convention, not a boundary.
- **What *is* enforced for Kimi**: shell commands reach parity — `_decide_permission` escalates any command containing shell operators, honours the `allowed_commands` allowlist, and respects `bash_yolo` (`kimi_session.py:141-148`). The gap is specific to **file paths**, not commands.
- **Mitigating factors**: Kimi models are only offered with `--experimental` (`src/constants.py` marks `KIMI_MODELS` experimental, `board.html` gates them). Single-user localhost, so there is no privilege boundary being crossed — the agent runs as the user who started it. Auto-review is skipped for Kimi models, so no second agent compounds the write.
- **Recommendation**: Give the Kimi path a real guard. Either (a) extend `_decide_permission` to inspect the tool call's path arguments and return `"ask"` / deny for paths outside `self.worktree_path`, reusing the predicate logic from `path_guard.py`; or (b) if ACP cannot surface paths reliably for every file tool, document the gap prominently in `CARDS/KIMI_PROVIDER.md` and the `--experimental` help text so enabling it is an informed choice. Until one of those lands, the honest statement is the one now in the Executive Summary: enabling Kimi trades away the enforced write boundary.
- **Remediation (rev 13, 2026-10-14)** — both (a) and (b) landed:
  - The boundary predicate was factored out of `path_guard.py` into a **`PathScope`** class, so the Claude PreToolUse hook and the Kimi runtime now share one implementation. `PathScope.resolve()` expands `~`, joins relative paths onto the **worktree** (the agent's cwd, not the server's — this also fixed a latent false-deny in the Claude hook when the dashboard runs on its own repo), and `.resolve()`s away `..` and symlinks.
  - `KimiAgentSession` builds a `PathScope` with **`strict_writes=True`** (a write anywhere outside the worktree is refused, not just one landing in the main checkout — the Kimi runtime has no second line of defense) and passes it to `_decide_permission`, which now returns `"deny"` for any permission request whose path arguments leave the scope, with a `WARNING` naming the path. Writes are worktree-only; reads keep the Claude hook's scope (worktree, plus the workspace root in multi-repo mode — `session_service` now passes `workspace_root` to the Kimi session too). `bash_yolo` does not relax it. Paths are read from the ACP tool call's `rawInput` (`_PATH_KEYS`/`_PATH_LIST_KEYS`: `path` is what kimi-code sends, Claude-style aliases cover other tools) plus ACP's schema'd `locations[].path`; any tool kind outside `read`/`search`/`think`/`fetch` — **including a missing kind** — is checked as a write, so an unknown tool fails closed.
  - 31 tests added in `tests/unit/test_kimi_session.py` (57 → 88): absolute escape, `..` escape, `~` escape, second-path-argument (`move`), ACP `locations`, missing kind, multi-repo sibling read vs. write, `bash_yolo` non-relaxation, unchanged shell-command semantics, and in-worktree writes still allowed — plus end-to-end denial through the real ACP `permission_handler`.
- **Residual gap (why this is Mitigated, not Remediated)**: the Claude guard is a PreToolUse hook and sees every tool call; on the Kimi side **kimi-code's own classifier decides which calls raise `session/request_permission`**, so an edit it deems safe never reaches `permission_handler` and cannot be refused there. ACP offers no stricter mode, and the SDK's ACP client does not expose client-side `fs/read_text_file`/`fs/write_text_file` interposition, which is where a true boundary would live. For calls kimi never asks about, `KimiAgentSession.audit_tool_call_scope` logs a `WARNING` with the offending path and item id for every streamed tool call — detection and an audit trail, not prevention. This is now stated in `CARDS/KIMI_PROVIDER.md` ("Worktree confinement"), in the `--experimental` `--help` text, and on the startup banner when the flag is on, so enabling Kimi is an informed choice. Closing it for real needs client-side ACP filesystem handling (or an OS sandbox around `kimi acp`).

### 16. Skills Install Writes Remote Tree Paths Without Local Validation

- **Severity**: Low
- **Status**: ⚠️ **OPEN** (defense-in-depth)
- **File**: `src/services/skills_service.py` (`_install_sync`)
- **Description**: Installing a skill walks the GitHub tree API and writes each blob to `skill_dir / rel`, where `rel` is derived from the remote `node["path"]`. `rel` is checked only for emptiness and a trailing slash — it is never validated for traversal before being joined and written. The skill **name** is properly validated (`_valid_name` = regex match plus an explicit `".." not in name`), so the containing directory is safe; the per-file paths inside it are not.
- **Why it is Low and not High**: git tree objects cannot contain `..` as a path component — git refuses to create them and `git fsck` flags them — so GitHub's API will not return such a path for a well-formed repository. The protection is real, but it is **borrowed from an upstream invariant** rather than asserted locally, which is exactly the pattern finding #4 was raised about for diff paths.
- **Failure scenario**: Any future change that makes the file list attacker-influenced — a different source backend, a local-directory or archive install path, a tarball fast-path to avoid per-file HTTP — turns an unvalidated join into a write outside `skill-library/`. The fix costs one line today and is easy to forget later.
- **Recommendation**: Run `rel` through the codebase's existing `validate_file_path()` (`src/git/operations.py`) before the join, and skip any entry it rejects. That function already blocks absolute paths, `..`, null bytes, `~/`, `//` and backslashes, and is the same guard used on diff and file-browser paths — reuse it rather than writing a second check.
- **Related, not separately numbered**: installed skills are **third-party instructions executed in the agent's context** (each is wrapped as a plugin and delivered via SDK `plugins=`), and installing one auto-enables it for the project. The command filter and path guard still apply, so a hostile skill cannot exceed the agent's permissions — but it can steer the agent within them. Review a skill's `SKILL.md` before enabling it, the same way you would review a dependency. `_get` also applies no response size cap, so a hostile repo can make an install write arbitrarily large files.

### 17. `peek_worktree` Reads Peer Worktrees Without Secret-File Hiding

- **Severity**: Info (by design)
- **Status**: ⚠️ **OPEN** (accepted — inherent to the feature)
- **Files**: `src/agent/peek_worktree.py`, `WorkflowService.peek_worktree` / `_peek_file_diff`, `GitService.worktree_path_diff`
- **Description**: `peek_worktree` deliberately crosses the one-agent-one-worktree boundary so agents can see in-flight work before it merges. The implementation is tightly scoped and holds up: `item_id` is resolved against the set of **active board items** (an unknown id returns a harmless message, and it is never used as a path), `path` goes through `validate_file_path()`, git runs as an argument list via `run_git` with no shell, the untracked-file fallback re-checks containment with `full_path.resolve()` against the worktree root (which also catches symlink escape), and output is capped. The residual point is that the file browser's secret-hiding (`.env`, keys, certificates, `.browserhidden` patterns — finding #7) does **not** apply to this path, so an agent can request the diff of a secret file another agent created inside its worktree.
- **Why Info**: this is the same exposure class as finding #8 (work log may contain secrets) and rests on the same reasoning — single local user, who already owns every one of these files. No privilege boundary is crossed. It is recorded so the asymmetry with the file browser is deliberate and visible rather than surprising.
- **Recommendation**: none required. If `.browserhidden` handling is ever factored into a reusable predicate, applying it to `_peek_file_diff` would be a cheap consistency win.

---

## Summary Table

| # | Finding | Severity | Status | Primary Risk |
|---|---------|----------|--------|-------------|
| 1 | Command filter bypass via shell operators | **High** | ✅ Fixed | Agent escapes command restrictions |
| 2 | Bash YOLO mode has no guardrails | **High** | ✅ Fixed | Agent runs unrestricted on host |
| 3 | File browser follows symlinks | Medium | ✅ Fixed | Browsing outside project boundary |
| 4 | Unvalidated paths in diff generation | Medium | ✅ Fixed | Reading files outside worktree |
| 5 | Dynamic SQL column names | Medium | ✅ Fixed | Fragile code pattern |
| 6 | No CORS middleware | Medium | ✅ Fixed | Cross-origin attacks from websites |
| 7 | Pattern-based secret detection | Medium | ✅ Fixed | Non-standard secrets visible |
| 8 | Sensitive data in work log | Low | ⚠️ Open | Secrets persisted in database |
| 9 | Unsanitized git output | Low | ⚠️ Open | Garbled display |
| 10 | Epic color not validated | Low | ✅ Fixed | Missing input validation |
| 11 | X-Forwarded-For trusted | Info | ⚠️ Open | N/A for localhost |
| 12 | No authentication | Info | ⚠️ Open | By design for localhost |
| 13 | HTTP only | Info | ⚠️ Open | By design for localhost |
| 14 | Missing security headers | Info | ✅ Fixed | Minimal risk on localhost |
| 15 | Kimi agents not confined by an enforcing hook | **Medium** | 🟡 Mitigated | Out-of-worktree paths denied on permission requests, logged otherwise (experimental only) |
| 16 | Skills install writes remote tree paths unvalidated | Low | ⚠️ Open | Defense-in-depth; relies on a git invariant |
| 17 | `peek_worktree` has no secret-file hiding | Info | ⚠️ Open | Peer-worktree secrets readable (by design) |

---

## Remediation Progress

**9 of 10 actionable findings fixed, plus #15 mitigated** (rev 13). The only
fully open actionable item is #16:

| Priority | Finding | Status |
|----------|---------|--------|
| Do Now | #1 Command filter — shell operator rejection + shlex parsing | ✅ Done |
| Do Now | #6 CORS middleware — localhost-only origin restriction | ✅ Done |
| Do Now | #5 SQL column whitelist — `_WRITABLE_ITEM_COLUMNS` validation (renamed from `ALLOWED_ITEM_COLUMNS` in rev 10) | ✅ Done |
| Consider | #3 Symlink skipping — symlinks displayed but not followed | ✅ Done |
| Consider | #4 Diff path validation — validate_file_path() applied | ✅ Done |
| Consider | #2 YOLO mode logging — command tagging + WebSocket events | ✅ Done |
| Consider | #7 `.browserhidden` config — project-specific secret patterns | ✅ Done |
| Low | #10 Epic color validation — Pydantic field_validator on EpicCreate/EpicUpdate | ✅ Done |
| Low | #14 Security headers — SecurityHeadersMiddleware (nosniff + DENY) | ✅ Done |
| Do Now | #15 Kimi path confinement — shared `PathScope` + path check in `_decide_permission`, violations logged, gap documented | 🟡 Mitigated (residual needs client-side ACP fs handling) |
| Low | #16 Skills install — run `rel` through `validate_file_path()` | ⚠️ Open |

### Not Needed for Localhost

- Authentication (#12) — correct design for single-user localhost
- TLS (#13) — no network traffic to encrypt
- Rate limiting — no untrusted clients
- Database encryption — OS file permissions are sufficient
- Session ownership — single user

---

## Architecture Strengths

The codebase has several good security practices worth noting:

- **Path traversal protection**: `validate_file_path()` in `operations.py` blocks `..`, absolute paths, null bytes, and control characters. This is well-implemented and consistently applied across diff generation and file browsing.
- **Parameterized SQL values**: All user-supplied values in SQL queries use `?` placeholders — no string interpolation of values. Column names are now also validated against whitelists.
- **Git operation timeouts**: Configurable timeouts prevent hung processes (300s default, 600s for merges).
- **Worktree isolation**: Each agent gets its own git worktree, preventing agents from interfering with each other's work.
- **Secret file hiding**: The file browser proactively hides common secret files (`.env`, keys, certificates) and supports project-specific `.browserhidden` config files for custom patterns, with mtime-based caching for performance.
- **Command access workflow**: The `request_command_access` MCP tool provides a controlled way for agents to ask permission for new commands, with user approval required.
- **Tool filtering**: The `PreToolUse` hook architecture for command filtering, built-in tool filtering, and path guarding is well-designed and extensible — but note the hook *mechanism* is **Claude-runtime** only. Since rev 13 the Kimi runtime shares the path-guard *predicate* (`PathScope`) through its ACP permission handler, which is as far as a non-hook runtime can go (#15).
- **No shell invocation anywhere**: `grep -rn "shell=True" src` returns nothing. Every subprocess — git, graphify, the Kimi CLI, the board MCP proxy — is spawned as an argument list, so there is no shell-metacharacter surface in the process-spawning layer at all. This is the single strongest structural property in the codebase.
- **Feed input is validated, not trusted** (rev 12): `model_catalog.parse_model_list` type-checks every field, enforces a provider allowlist (`FEED_PROVIDERS`), regex-validates each model id against `_MODEL_ID_RE`, de-duplicates, and falls back to a display name — so a malformed or hostile feed response cannot inject an arbitrary model id into provider routing or toward a command line. The fetch verifies TLS (default `urllib` behaviour, not weakened), has a 10s timeout, and `refresh()` never raises — a failed fetch keeps the previous list. The one gap is that `resp.read()` applies no size cap.
- **Config via environment, not argv** (rev 12): the Kimi board MCP proxy receives `DASHBOARD_BASE_URL` / `DASHBOARD_ITEM_ID` through the subprocess environment rather than the command line, so they do not appear in `ps` output. Note that `DASHBOARD_ITEM_ID` is an *advisory* identity — the dashboard API is unauthenticated by design (#12), so any agent with shell access could call it as another item. That is a consequence of #12, not a separate finding.
- **Path guard**: `PreToolUse` hook (`path_guard.py`) prevents agents from editing files outside their assigned worktree, blocking accidental writes to the main repo or other agents' worktrees.
- **Shell operator rejection**: The command filter comprehensively blocks shell metacharacters before checking allowed prefixes, using `shlex.split()` for robust parsing.
- **CORS protection**: Localhost-only origin restriction prevents cross-origin attacks from malicious websites.
- **YOLO mode visibility**: Even in unrestricted mode, all commands are logged and tagged for audit trail visibility.
- **Symlink safety**: File browser displays symlinks as indicators without following them, preventing directory escape.
- **Security response headers**: `SecurityHeadersMiddleware` adds `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` to all responses.
- **Input validation**: Epic colors are validated against a whitelist via Pydantic `field_validator`, preventing arbitrary input.
- **Stale worktree detection**: Background periodic task detects and notifies about orphaned worktrees, with UI-driven cleanup actions.
- **Read-only auto-review agent**: The optional auto-approve workflow (migration 022) spawns a separate Claude session via `src/agent/review_agent.py` to grade the diff before merge. The reviewer is strictly read-only — its `can_use_tool` callback returns `PermissionResultAllow` for `Read`/`Glob`/`Grep` and `PermissionResultDeny` for everything else (no `Edit`/`Write`/`Bash`). Cycle bookkeeping (max 3 retries) lives in `WorkflowService._auto_approve_retries` outside the SDK call, so a malicious or buggy reviewer cannot loop indefinitely.
