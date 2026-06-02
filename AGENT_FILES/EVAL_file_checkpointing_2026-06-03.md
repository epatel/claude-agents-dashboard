# Evaluation — SDK file checkpointing for the review→reject flow

> Point-in-time assessment (2026-06-03). Not maintained. Decision: **do not adopt.**
> Related: [`SDK_BUMP_2026-06-03.md`](SDK_BUMP_2026-06-03.md).

## Question

The 0.2.88 bump exposes `enable_file_checkpointing` + `ClaudeSDKClient.rewind_files(user_message_id)`.
Should we use them to power the review→reject flow (revert an agent's file
changes when a reviewer rejects)?

## TL;DR

**No.** Two independent blockers:

1. **Lifecycle mismatch** — `rewind_files()` requires a *live* `ClaudeSDKClient`;
   by review time the session is already disconnected, so there is nothing to
   rewind against.
2. **Redundant & weaker** — the dashboard already uses **git worktrees** as its
   undo mechanism. Worktree+branch deletion is a complete, durable, cross-session
   revert and is also the source of truth for the merge. SDK checkpoints are
   in-process, local-disk only, and add nothing git doesn't already do better.

## How SDK checkpointing actually works (0.2.88)

- `ClaudeAgentOptions(enable_file_checkpointing=True)` sets
  `CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING=true` on the CLI subprocess
  (`_internal/transport/subprocess_cli.py:464`).
- `await client.rewind_files(uuid)` rewinds tracked files to their state at a
  given **UserMessage UUID** (`client.py:370`). It forwards to the live query
  (`self._query.rewind_files`), so the subprocess must still be running.
- Also requires `extra_args={"replay-user-messages": None}` so `UserMessage`
  objects arrive with a `uuid` to capture as checkpoint ids — the dashboard's
  receive loop (`src/agent/session.py`) does not handle `UserMessage` today.
- Constraint: **cannot be combined with `session_store`**
  (`_internal/session_store_validation.py:40` — "checkpoints are local-disk only
  and would diverge"). This would foreclose the SessionStore option noted as a
  future nice-to-have in the SDK bump doc.

## Why it doesn't fit our flow

The reject paths (from `workflow_service.py`, via `domain/item_state.py`):

| Action | Transition | Worktree | Session at action time | Today's undo |
| --- | --- | --- | --- | --- |
| **REQUEST_CHANGES** | REVIEW → RUNNING | **reused** | none (new one spawned) | changes kept on purpose; agent iterates |
| **CANCEL_REVIEW** ("reject") | REVIEW → BACKLOG | **deleted** | none | git worktree + branch removed → full discard |

- An agent run ends in `on_complete`, which calls
  `self.sessions.remove_session(item_id)` and transitions the item to REVIEW.
  **Review/reject happens strictly after the session disconnects** → no live
  client → `rewind_files()` is uncallable.
- Even within REQUEST_CHANGES, each round spins up a **new** `ClaudeSDKClient`
  (`sessions.create_session`), so a checkpoint from round 1 wouldn't survive into
  round 2 regardless.
- CANCEL_REVIEW already discards *everything* by deleting the worktree+branch —
  stronger and simpler than rewinding tracked files, and it works no matter what
  process state the agent left behind.

## If we ever want granular "revert to a previous review round"

That is a real feature SDK checkpointing still wouldn't serve (cross-session,
post-disconnect). The idiomatic implementation is **git-native**, reusing
existing infrastructure:

- The item already records `base_commit` and owns a branch + worktree.
- Snapshot a **commit SHA per agent round** in the worktree; to revert, `git
  reset --hard <sha>` (or `git revert`) to the chosen round.
- Works across sessions/restarts, survives process death, and stays the merge
  source of truth — none of which SDK checkpoints offer.

Happy to sketch this as a separate proposal if partial-revert is wanted.

## Recommendation

Leave `enable_file_checkpointing` off. No code change. Keep git worktrees as the
checkpoint/undo system. Revisit only if a future need for *intra-session*,
mid-run file rewind appears (not the case for review→reject).
