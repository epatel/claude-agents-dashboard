# Key Flows

- **Agent start**: non-blocking via `asyncio.create_task()`. Each item gets its own git worktree (`agents-lab/worktrees/agent-{item_id}`). In multi-repo mode the worktree is rooted in the item's chosen sibling repo and `add_dirs` includes the other sibling repos read-only.
- **Clarification**: `ask_user` MCP tool moves item to "Clarify", `await`s `asyncio.Event`, HTTP endpoint sets the event. Optional `context` field on the tool is stored alongside `prompt`/`choices` (migration 021) and rendered as a panel above the prompt in the Question dialog so the user has background before answering. The clarification row is created **before** the `item_updated` broadcast so the dialog has full context on first open.
- **Merge**: commits uncommitted worktree changes first, then merges. On conflict, captures diff, resets worktree to latest base, restarts agent with conflict prompt.
- **Pause/resume**: captures `session_id`, kills process, later resumes via `ClaudeAgentOptions(resume=session_id, continue_conversation=True)`.
- **Stale worktree detection**: on startup + every 5min, scans worktrees against DB state, emits cleanup notifications.
- **WIP limit**: configurable cap on concurrent running agents; items started beyond the limit are placed in 'doing' with `status='queued'` and auto-started in position order when a slot opens.
- **Multi-repo**: when `target_project` is a parent folder containing ≥1 sibling git repos, items carry a required `repo` field; worktrees are created inside the chosen subrepo.
