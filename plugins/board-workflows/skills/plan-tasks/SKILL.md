---
name: plan-tasks
description: Use when asked to break down a feature, create a plan, or decompose work into tasks. Takes a known goal and produces an ordered set of Todos in an Epic on the board.
version: 1.0.0
---

# Plan Tasks

Break a known goal into an ordered set of actionable Todos grouped under an Epic on the board.

Unlike brainstorm (which explores what to build), this skill assumes the goal is already clear. It focuses on **how** to break the work into concrete, agent-executable tasks.

## Rules

1. **Read the board first.** Check for existing epics and todos that overlap.
2. **Each todo = one agent session.** A single agent should be able to complete it in one run.
3. **No placeholders.** Every todo needs a title and description with enough detail to execute.
4. **Order by dependency.** Create foundational tasks first — they appear at the top.

## Process

### 1. Assess

- Read the board (mcp__board_view__view_board)
- Understand the goal from the user's description
- If the goal is unclear, ask 1-2 focused questions (not a brainstorm — just fill gaps)

### 2. Decompose

Break the work into tasks following this order:

1. **Data/schema changes** — migrations, models
2. **Backend logic** — services, routes, APIs
3. **Frontend** — templates, JS, CSS
4. **Integration** — wiring pieces together, agent tools
5. **Documentation** — update docs if needed

Each task should:
- Touch a focused set of files (1-5)
- Be testable independently
- Produce a working commit

### 3. Present the Plan

Show the user the task list before creating board items:

```
Epic: [Name] ([color])

1. [Task title] — [one-line summary]
2. [Task title] — [one-line summary]
...
```

Ask: "Does this breakdown look right, or should I adjust?"

### 4. Create Board Items

Once approved:

1. **Create the Epic** via mcp__todo__create_epic
2. **Create each Todo in dependency order** via mcp__todo__create_todo with:
   - `epic_id` — the epic created in step 1
   - `requires` — array of item IDs this task depends on (from previously created todos)
3. **Track created IDs.** Each create_todo call returns an item ID. Save these IDs so later todos can reference them in their `requires` array.
4. **Set commit message** summarizing the plan

**Example dependency chain:**
```
Todo 1 (DB migration)      → ID: abc123, requires: []
Todo 2 (Backend service)   → ID: def456, requires: ["abc123"]
Todo 3 (API routes)        → ID: ghi789, requires: ["def456"]
Todo 4 (Frontend)          → ID: jkl012, requires: ["ghi789"]
```

Dependencies are **enforced by the board** — an agent cannot start a todo until all items in its `requires` list are completed. Always use `requires` instead of only describing dependencies in text.

### Writing Task Descriptions

Each todo description should contain:

- **What to do** — specific files to create/modify and the changes needed
- **How to verify** — test command or expected behavior
- **Dependencies** — mention what this task depends on (for human context), but **always also set the `requires` parameter** with the actual item IDs to enforce the dependency technically

Keep descriptions concise but complete. An agent reading only the title and description should know exactly what to build.
