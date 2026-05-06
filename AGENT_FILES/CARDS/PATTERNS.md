# Important Patterns

- All state changes broadcast via `NotificationService` for real-time UI.
- `TemplateResponse` requires `request` as first kwarg: `TemplateResponse(request=request, name="...", context={...})`.
- Never use browser `confirm()` or `prompt()` in dialogs — use `Dialogs.confirm()` (returns Promise).
- Tooltips use `position: fixed`, appended to nearest open `<dialog>` or `document.body`. Use `data-tip` / `data-tip-html`.
- Card action buttons use `event.stopPropagation()` on individual buttons, not on the wrapper div.
- Avoid duplicate `from pathlib import Path` inside functions — it's imported at file top and causes `UnboundLocalError`.
- Annotations export two PNGs: `_original.png` (clean) and `_annotations.png` (overlay). The `annotation_summary` column stores a text count.
- Agents run with `permission_mode="acceptEdits"` by default. YOLO mode uses `bypassPermissions`.
- Allowed command prefixes are checked via `PreToolUse` hook (`command_filter.py`). Denied commands prompt `request_command_access`.
- Optional built-in tools (WebSearch, WebFetch) filtered via `PreToolUse` hook (`tool_filter.py`). Denied tools prompt `request_tool_access`.
- Path guard via `PreToolUse` hook (`path_guard.py`) prevents agents from editing files outside their worktree.
- External MCP servers get wildcard tool permissions (`mcp__{server_name}__*`).
- Attachment deletion uses `/api/attachments/{attachment_id}` (not nested under items).
- JavaScript-rendered cards and the server-rendered Jinja2 `card.html` partial must stay in sync.
- Notifications support optional `action` dict (`{label, url, method}`) for action buttons (e.g., stale worktree cleanup).
