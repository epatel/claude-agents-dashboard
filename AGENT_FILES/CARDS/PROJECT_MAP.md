# PROJECT_MAP

> **Load when**: the user uses a `flow.*` / `card.*` / `dialog.*` shorthand; you're tracing a flow end-to-end and need line-numbered entry points; you need to know which WS event a flow emits.
> **Skip when**: greenfield work that doesn't touch named flows or UI elements.

Shorthand vocabulary for parts of this project. Use these names in conversation; both sides resolve them to the same code.

Naming convention: `subsystem.element[-modifier]`, dotted, lowercase, kebab-case for multi-word parts.

Two sections: **Flows** (hand-curated) and **UI** (hand-curated table of currently-tagged `data-map-name` attributes; an auto-gen script remains on the [strategy roadmap](PROJECT_MAP_STRATEGY.md)).

Strategy doc: [`PROJECT_MAP_STRATEGY.md`](PROJECT_MAP_STRATEGY.md).

For broader project context (architecture, patterns, dev workflows), see the [card index](README.md). Cross-references in the flow entries below link to the relevant card.

---

## Flows

Backend processes and lifecycle paths. Each entry: purpose · entry-point · WS events broadcast · DB tables touched.

> Subsystem context for the flows below lives in [`ARCHITECTURE.md`](ARCHITECTURE.md) (services, agent runtime, hooks, frontend). Migrations are documented in [`DATABASE.md`](DATABASE.md).

### `flow.agent-start`
Spawns a Claude session in a fresh worktree (`agents-lab/worktrees/agent-{item_id}`), non-blocking via `asyncio.create_task`.
- **Entry:** `src/services/workflow_service.py:139` `start_agent` → `:148` `_start_agent_internal`
- **HTTP:** `POST /api/items/{id}/start` (`src/web/routes.py:685`)
- **WS events:** `item_updated`, `agent_log`
- **Tables:** `items`, `notifications`

### `flow.merge`
Commits uncommitted worktree changes, merges into base. On conflict: captures diff, resets worktree to latest base, restarts agent with conflict prompt.
- **Entry:** `src/services/workflow_service.py:450` `approve_item`
- **HTTP:** `POST /api/items/{id}/approve` (`src/web/routes.py:879`)
- **WS events:** `item_updated`, `merge_blocked`, `agent_log`
- **Tables:** `items`

### `flow.clarify`
MCP `ask_user` moves item to "Clarify" column, awaits `asyncio.Event`. HTTP endpoint sets the event with the user's answer, agent resumes.
- **MCP tool:** `src/agent/clarification.py:55` `ask_user`
- **Callback:** `src/services/workflow_service.py:1018` `_create_on_clarify_callback`
- **Resume:** `src/services/workflow_service.py:843` `submit_clarification`
- **HTTP:** `POST /api/items/{id}/clarify` (`src/web/routes.py:929`)
- **WS events:** `clarification_requested`, `item_updated`
- **Tables:** `items`

### `flow.pause-resume`
Captures `session_id`, kills process. Resume builds `ClaudeAgentOptions(resume=session_id, continue_conversation=True)`.
- **Entry:** `src/services/workflow_service.py:266` `pause_agent` / `:292` `resume_agent`
- **HTTP:** `POST /api/items/{id}/pause` (`src/web/routes.py:712`), `POST /api/items/{id}/resume` (`:727`)
- **Session ops:** `src/services/session_service.py:140` `pause_session`
- **WS events:** `item_updated`, `agent_log`
- **Tables:** `items` (stores `session_id`)

### `flow.stale-scan`
Compares `git worktree list` against DB on startup and every 5 min. Emits cleanup notifications with action buttons.
- **Entry:** `src/services/workflow_service.py:1618` `find_stale_worktrees` / `:1677` `cleanup_stale_worktree`
- **Scheduler:** registered from the FastAPI lifespan in `src/web/app.py`
- **WS events:** `item_updated`, notification with `action` dict
- **Tables:** `items`, `notifications`

### `flow.wip-queue`
Caps concurrent running agents. Items started beyond the limit get `status='queued'` in `doing` column; auto-start in position order when a slot opens.
- **Entry:** `src/services/workflow_service.py:102` `_is_at_wip_limit` · `:111` `_enqueue_item` · `:119` `process_queue`
- **Triggered from:** `start_agent` and every slot-free path (cancel / complete / merge / dependency-resolve)
- **WS events:** `item_updated`
- **Tables:** `items` (`status='queued'`, `column_name='doing'`)

### `flow.multi-repo-start`
When target is a workspace folder of sibling repos, worktree is rooted in the chosen subrepo and other siblings are added read-only via `add_dirs`.
- **Entry:** `src/services/workflow_service.py:80` `_multi_repo_session_kwargs`
- **Subrepo discovery:** `src/main.py:108` `_discover_subrepos`
- **WS events:** `item_updated`
- **Tables:** `items` (`repo` column from migration 020)

### `flow.dependency-autostart`
When a prerequisite item finishes (merged or manually moved to done/archive), auto-starts dependents whose `requires` are now satisfied.
- **Entry:** `src/services/workflow_service.py:704` `notify_and_auto_start_dependents`
- **Invoked from:** the merge pipeline (`approve_item` → all three success paths) and the drag-and-drop move endpoint (`web/routes.py::move_item` when target column is `done`/`archive`)
- **Todo creation w/ deps:** `src/services/workflow_service.py:1165` `_create_on_create_todo_callback` (handles `requires`, `auto_start`)
- **WS events:** `dependencies_resolved`, `blocked_status_changed`, `item_updated`, `agent_log`
- **Tables:** `items` (deps stored via migration 011)

### `flow.commit`
MCP `set_commit_message` stores message on session. Merge path commits any uncommitted worktree changes first using that message.
- **MCP tool:** `src/agent/commit_message.py:44` `set_commit_message` (delegates to `SessionService.set_commit_message` at `src/services/session_service.py:202`)
- **Callback:** `src/services/workflow_service.py:1225` `_create_on_set_commit_message_callback`
- **Commit-on-uncommitted:** inside `approve_item` (~`src/services/workflow_service.py:500`)
- **WS events:** `item_updated`, `agent_log`
- **Tables:** `items` (`merge_commit` from migration 008)

### `flow.command-gate`
PreToolUse hook denies shell commands not in the allowlist. Agent calls `request_command_access` MCP to prompt the user; on approval, session restarts with new permissions.
- **Filter hook:** `src/agent/command_filter.py:34` `make_command_filter_hook` / `:45` `hook`
- **Access MCP:** `src/agent/command_access.py:36` `request_command_access`
- **Callback:** `src/services/workflow_service.py:1032` `_create_on_request_command_callback`
- **Restart:** `src/services/workflow_service.py:1535` `_restart_session_with_new_permissions`
- **HTTP:** `POST /api/items/{id}/approve-command` (`src/web/routes.py:935`)
- **WS events:** `item_updated`, `agent_log`
- **Tables:** `items` (`allowed_commands` from migration 003)

### `flow.tool-gate`
Same shape as `flow.command-gate` but for built-in tools (WebSearch, WebFetch).
- **Filter hook:** `src/agent/tool_filter.py:9` `make_tool_filter_hook` / `:16` `hook`
- **Access MCP:** `src/agent/tool_access.py:36` `request_tool_access`
- **Callback:** `src/services/workflow_service.py:1101` `_create_on_request_tool_callback`
- **WS events:** `item_updated`, `agent_log`
- **Tables:** `items` (`allowed_builtin_tools` from migration 006)

### `flow.path-guard`
PreToolUse hook resolves Read/Edit/Write paths and denies any access outside the worktree (and outside `workspace_root` for reads in multi-repo mode).
- **Hook:** `src/agent/path_guard.py:25` `make_path_guard_hook(worktree_path, workspace_root)` / `:90` `hook`
- **WS events:** none (denial returned to agent)
- **Tables:** n/a

### `flow.notify-broadcast`
Single fan-out point to WebSocket clients on every state change.
- **Service:** `src/services/notification_service.py:18` `broadcast_item_updated` (and `_created` / `_deleted` / `agent_log` / `clarification_requested` / `epic_*`)
- **WS endpoint:** `/ws` (`src/web/routes.py:1555` `websocket_endpoint`)
- **Event types emitted:** `item_updated`, `item_created`, `item_deleted`, `agent_log`, `clarification_requested`, `epic_created`, `epic_updated`, `epic_deleted`, `merge_blocked`
- **Tables:** `items`, `epics`, `notifications`

### `flow.migration`
Versioned schema migrations (`001`–`023` in `src/migrations/versions/`). Auto-runs pending migrations on startup.
- **Trigger:** auto-migrate from the FastAPI lifespan in `src/web/app.py`
- **CLI:** `python -m src.manage [status|migrate|rollback|init]`
- **Note:** any new `items`/`epics` columns must also be added to the repo-level whitelists — `src/repositories/item_repository.py` (`_WRITABLE_ITEM_COLUMNS`) and `src/repositories/epic_repository.py` (`_WRITABLE_EPIC_COLUMNS`)
- **WS events:** none
- **Tables:** all (schema owner)

---

## Overlays

Two independent dev overlays. **Loaded only when the server runs with `--ui-map`:**

```bash
./run.sh /path/to/project --ui-map
```

When loaded, **both overlays default OFF on first load** — cycle them on with Cmd+Shift+M. `sessionStorage` remembers your last active choice within the tab.

### Cmd+Shift+M — cycle modes

When `--ui-map` is set, Cmd+Shift+M cycles through four modes (with a brief "OVERLAY: …" pill at the top of the screen):

| Press | Mode | Map | Spacing | Use case |
|-------|------|-----|---------|----------|
| start | **OFF**     | — | — | default — no overlays; normal interaction |
| 1     | **MAP**     | ✓ | — | names only |
| 2     | **SPACING** | — | ✓ | spacing only |
| 3     | **BOTH**    | ✓ | ✓ | names + spacing |
| 4     | **OFF**     | — | — | back to start |

Inside a modal dialog, overlay elements (badge, tooltip, bands) are re-parented into the dialog's top layer and switched to `position: absolute` so they render inside the dialog's visible box (the dialog's `overflow: hidden` would otherwise clip them).

The cycle is also exposed in console: `__projectMapCoordinator.cycle()` / `.applyMode(MODES[i])`.

### Map overlay — name discovery
- **Hover** any tagged element → tooltip with its `data-map-name`
- **Click** → copies the name to clipboard
- **Badge:** orange "MAP ON" top-right
- **Console:** `__projectMap.activate()` / `.deactivate()` / `.isActive()` / `.listNames()`

### Spacing overlay — padding / margin / gap
- **Hover** any element → translucent bands appear:
  - **Green** for `padding-*`
  - **Orange** for `margin-*`
  - **Blue** for `gap` (between flex/grid children)
- Each non-zero side is labeled like `padding-top: 12px`
- **Badge:** blue "SPACING ON" top-right
- **Console:** `__projectSpacing.activate()` / `.deactivate()` / `.isActive()`

## UI elements

Source of truth: the `data-map-name="..."` attribute on each element. Adding a new name = adding the attribute in the template/JS. The table below is hand-curated; an auto-regen script that greps for `data-map-name=` remains on the [strategy roadmap](PROJECT_MAP_STRATEGY.md).

Subsystem prefixes:
- `topbar.*` — header bar controls
- `shortcuts.*` — shortcuts bar (bottom)
- `board.*` — columns, drop zones, board-level controls _(to be tagged)_
- `card.*` — anything inside a card (buttons, title, work-log) _(to be tagged)_
- `dialog.<name>.*` — fields/buttons inside specific dialogs _(to be tagged)_
- `notif.*` — notification toasts and banners _(to be tagged)_

### Currently tagged

> Card and column names are **per-class**, not per-item. Every start button is `card.btn-start`; every Doing column is `board.column-doing`. The overlay copies the same name regardless of which specific card/column you click.

#### Top bar
| Name | Element | File |
|------|---------|------|
| `topbar` | `<header class="top-bar">` | `src/templates/base.html` |
| `topbar.title` | Project title `<h1>` | `src/templates/base.html` |
| `topbar.stats` | Stats bar wrapper | `src/templates/base.html` |
| `topbar.actions` | Right-side button group | `src/templates/base.html` |
| `topbar.btn-search` | 🔍 Search button | `src/templates/base.html` |
| `topbar.btn-files` | Files button | `src/templates/base.html` |
| `topbar.btn-notifications` | 🔔 Notifications bell | `src/templates/base.html` |
| `topbar.btn-config` | ⚙ Settings button | `src/templates/base.html` |
| `topbar.btn-sound` | 🔊 Sound toggle | `src/templates/base.html` |
| `topbar.btn-theme` | Theme toggle (🖥/☀/☾) | `src/templates/base.html` |

#### Shortcuts bar
| Name | Element | File |
|------|---------|------|
| `shortcuts.bar` | Shortcuts bar (bottom) | `src/templates/base.html` |
| `shortcuts.btn-add` | + button inside shortcuts bar | `src/templates/base.html` |
| `shortcuts.btn-manage` | ⚙ button inside shortcuts bar | `src/templates/base.html` |
| `shortcuts.btn-add-floating` | Floating + Shortcut button | `src/templates/base.html` |
| `shortcuts.btn-shortcut` | One per user-created shortcut (per-class name; same on every shortcut button) | `src/static/js/shortcuts.js:render` |

#### Board / columns
| Name | Element | File |
|------|---------|------|
| `board` | `<main class="board">` | `src/templates/board.html` |
| `board.epic-toggle` | Epic panel chevron toggle (left edge) | `src/templates/board.html` |
| `board.epic-panel` | Epic panel wrapper | `src/templates/board.html` |
| `board.btn-new-item` | + button inside Todo column header | `src/templates/board.html` |
| `board.column-{id}` | Column wrapper, one per column id (`todo`, `doing`, `review`, `done`, `questions`, `archive`) | `src/templates/board.html` |
| `board.column-{id}.header` | Column header bar | `src/templates/board.html` |
| `board.column-{id}.count` | Column item-count badge | `src/templates/board.html` |
| `board.column-{id}.dropzone` | The cards container that accepts drag-drop | `src/templates/board.html` |
| `board.day-group` | Day-grouped cards container (Done & Archive columns) | `src/static/js/board.js:renderDoneColumn` / `:renderArchiveColumn` |
| `board.day-group.header` | Clickable header that collapses/expands the day group | `src/static/js/board.js` |
| `board.day-group.label` | Date label (e.g., "Today", "Yesterday", "Tue Apr 15") | `src/static/js/board.js` |
| `board.day-group.count` | Item count badge in the day-group header | `src/static/js/board.js` |
| `board.day-group.btn-archive-all` | 📦 Archive all from this day (Done column only) | `src/static/js/board.js:renderDoneColumn` |
| `board.day-group.btn-delete-all` | ✕ Delete all from this day (Archive column only) | `src/static/js/board.js:renderArchiveColumn` |

#### Cards (kept in sync between `partials/card.html` and `board.js:renderCard`)
| Name | Element |
|------|---------|
| `card` | The card outer div |
| `card.title` | Card title text |
| `card.status` | Status row (`Running` / `Paused` / `⚠ Merge conflict` / etc.) |
| `card.actions` | Wrapper around the action buttons |
| `card.epic-badge` | Epic badge at top of card |
| `card.repo-badge` | Multi-repo badge |
| `card.blocked-badge` | "🔒 Blocked by …" badge on blocked todos |
| `card.log-count` | Number-of-log-entries badge (Doing column) |
| `card.model-badge` | Model badge (shown only for non-default / Ollama models, JS render only) |
| `card.timestamp` | Done-time badge (Done column, JS render only) |
| `card.btn-start` | ▶ Start agent button (Todo) |
| `card.btn-start-copy` | ▶⧉ Start Copy button (Todo, copy mode) |
| `card.btn-delete` | ✕ Delete (Todo, Archive) |
| `card.btn-pause` | ⏸ Pause (Doing, running) |
| `card.btn-resume` | ▶ Resume (Doing, paused) |
| `card.btn-cancel` | ✕ Cancel agent (Doing) |
| `card.btn-retry` | ↻ Retry (Doing, failed) |
| `card.btn-move-to-todo` | → Todo (Doing, failed) |
| `card.btn-approve` | ✓ Approve & Merge (Review, has changes) |
| `card.btn-done` | ✓ Done (Review, no changes) |
| `card.btn-request-changes` | ↩ Request changes (Review) |
| `card.btn-cancel-review` | ✕ Cancel review (Review) |
| `card.btn-archive` | 📦 Archive (Done, Questions) |
| `card.btn-rerun` | ↻ Re-run (Done) |

#### Settings dialog
| Name | Element | File |
|------|---------|------|
| `dialog.settings` | The `<dialog id="config-dialog">` | `src/templates/board.html` |
| `dialog.settings.header` | Modal header (title row) | `src/templates/board.html` |
| `dialog.settings.btn-close` | × close button | `src/templates/board.html` |
| `dialog.settings.form` | Settings form | `src/templates/board.html` |
| `dialog.settings.tabs` | Tab-bar wrapper | `src/templates/board.html` |
| `dialog.settings.tab-{id}` | Individual tab button; `{id}` ∈ `general`, `prompts`, `ollama`, `mcp`, `plugins`, `appearance` | `src/templates/board.html` |
| `dialog.settings.panel-{id}` | Tab content panel | `src/templates/board.html` |
| `dialog.settings.field-model` | Model `<select>` (General) | `src/templates/board.html` |
| `dialog.settings.field-wip-limit` | WIP limit `<input>` (General) | `src/templates/board.html` |
| `dialog.settings.footer` | Modal footer | `src/templates/board.html` |
| `dialog.settings.btn-cancel` | Cancel button | `src/templates/board.html` |
| `dialog.settings.btn-save` | Save button | `src/templates/board.html` |

---

**See also**: [ARCHITECTURE](ARCHITECTURE.md) (subsystem context behind each flow), [PROJECT_MAP_STRATEGY](PROJECT_MAP_STRATEGY.md) (rationale + roadmap for the vocabulary).
