# Security Audit Report

**Date**: 2026-04-10
**Last updated**: 2026-04-10
**Scope**: Full codebase review of Claude Agents Dashboard
**Threat model**: Localhost single-user developer tool. The server binds to `127.0.0.1` only, is operated by the local developer, and is not designed for network exposure or multi-user access.

---

## Executive Summary

This audit identified **14 security findings** relevant to a localhost developer tool: 2 High, 5 Medium, and 7 Low/Info. Since the initial audit, **6 of 7 actionable findings have been remediated**, bringing the application's security posture from reasonable to **strong for its intended use case**.

The two original high-severity findings (command filter bypass and YOLO mode) have both been addressed with robust fixes. Four of five medium-severity findings have also been resolved. The remaining open items are low-severity or informational.

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
- **Fix implemented**: `ALLOWED_ITEM_COLUMNS` whitelist is defined at module level containing all valid columns (title, description, column_name, status, position, branch_name, worktree_path, session_id, model, base_branch, base_commit, done_at, epic_id, merge_commit, auto_start, commit_message). `update_item()` validates `set(kwargs) - ALLOWED_ITEM_COLUMNS` and raises `ValueError` for invalid keys. A similar `ALLOWED_EPIC_COLUMNS` whitelist is enforced for epic updates.

### 6. No CORS Middleware

- **Severity**: Medium
- **Status**: ✅ **REMEDIATED**
- **File**: `src/web/app.py`
- **Original issue**: No `CORSMiddleware` was configured, allowing cross-origin attacks from malicious websites.
- **Fix implemented**: CORS middleware is now configured via `_build_cors_origins()`, which restricts allowed origins to `localhost` and `127.0.0.1` across ports 8000–8019. This prevents malicious websites from making cross-origin requests to the local server.

### 7. Secret File Detection Is Pattern-Based

- **Severity**: Medium
- **Status**: ⚠️ **OPEN** (accepted risk)
- **File**: `src/web/file_routes.py` (`is_secret_file()`)
- **Description**: The file browser hides files matching known secret patterns (`.env`, `*.key`, `*.pem`, etc.). Files with non-standard names containing secrets (e.g., `credentials.yaml`, `my-tokens.txt`) are not detected and will be visible in the browser — and potentially included in agent context if attached to items.
- **Recommendation**: This is a best-effort feature and the limitation is acceptable. Consider adding a `.browserhidden` config file for project-specific patterns, similar to `.gitignore`.

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
- **Status**: ⚠️ **OPEN**
- **Files**: `src/models.py`, `src/web/routes.py`
- **Description**: `EpicCreate` accepts any `color: str` without validating against the `EPIC_COLORS` whitelist in `constants.py`. Since the local user is the only one creating epics, this is not exploitable — just a missing validation. Arbitrary color strings could cause UI rendering issues if they don't match the predefined theme variants.
- **Recommendation**: Add a Pydantic validator against `EPIC_COLORS` keys (red, orange, amber, green, teal, blue, purple, pink) for completeness.

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
- **Status**: ⚠️ **OPEN** (low priority)
- **File**: `src/web/app.py`
- **Description**: No `X-Frame-Options`, `X-Content-Type-Options`, or `Content-Security-Policy` headers. For a localhost tool, the attack surface for clickjacking or MIME sniffing is minimal.
- **Recommendation**: Low priority. Adding `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` is trivial and good practice.

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
| 7 | Pattern-based secret detection | Medium | ⚠️ Open | Non-standard secrets visible |
| 8 | Sensitive data in work log | Low | ⚠️ Open | Secrets persisted in database |
| 9 | Unsanitized git output | Low | ⚠️ Open | Garbled display |
| 10 | Epic color not validated | Low | ⚠️ Open | Missing input validation |
| 11 | X-Forwarded-For trusted | Info | ⚠️ Open | N/A for localhost |
| 12 | No authentication | Info | ⚠️ Open | By design for localhost |
| 13 | HTTP only | Info | ⚠️ Open | By design for localhost |
| 14 | Missing security headers | Info | ⚠️ Open | Minimal risk on localhost |

---

## Remediation Progress

**6 of 7 actionable findings fixed** (86% remediation rate):

| Priority | Finding | Status |
|----------|---------|--------|
| Do Now | #1 Command filter — shell operator rejection + shlex parsing | ✅ Done |
| Do Now | #6 CORS middleware — localhost-only origin restriction | ✅ Done |
| Do Now | #5 SQL column whitelist — ALLOWED_ITEM_COLUMNS validation | ✅ Done |
| Consider | #3 Symlink skipping — symlinks displayed but not followed | ✅ Done |
| Consider | #4 Diff path validation — validate_file_path() applied | ✅ Done |
| Consider | #2 YOLO mode logging — command tagging + WebSocket events | ✅ Done |

### Remaining Recommendations

1. **Validate epic colors** (Finding #10): Add a Pydantic validator on `EpicCreate.color` against `EPIC_COLORS` keys. ~15 minutes.

2. **Add security response headers** (Finding #14): Add `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` middleware. ~15 minutes.

3. **Consider `.browserhidden` config** (Finding #7): Allow project-specific secret file patterns beyond the built-in list. ~2 hours.

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
- **Secret file hiding**: The file browser proactively hides common secret files (`.env`, keys, certificates).
- **Command access workflow**: The `request_command_access` MCP tool provides a controlled way for agents to ask permission for new commands, with user approval required.
- **Tool filtering**: The `PreToolUse` hook architecture for both command filtering and built-in tool filtering is well-designed and extensible.
- **Shell operator rejection**: The command filter comprehensively blocks shell metacharacters before checking allowed prefixes, using `shlex.split()` for robust parsing.
- **CORS protection**: Localhost-only origin restriction prevents cross-origin attacks from malicious websites.
- **YOLO mode visibility**: Even in unrestricted mode, all commands are logged and tagged for audit trail visibility.
- **Symlink safety**: File browser displays symlinks as indicators without following them, preventing directory escape.
