# Demo — kanban-demo walkthrough

> **Load when**: explaining how to demo the dashboard end-to-end, reproducing the `kanban-demo` run, or updating the demo docs/links.
> **Skip when**: normal feature work that doesn't touch the demo flow.

A one-prompt showcase of the full pipeline: task-breakdown, dependency chaining, and auto-start all driven from a single Todo.

## The flow

1. Clone the starter repo: `git clone https://github.com/epatel/kanban-demo.git`
2. Point the dashboard at it: `path/to/claude-agents-dashboard/run.sh /path/to/kanban-demo`
3. Create a Todo and start it: **`Lets have some fun. Read @START.md`**

The repo ships with only a `.gitignore` and [`START.md`](https://github.com/epatel/kanban-demo/blob/main/START.md). The agent reads the brief, scaffolds the project (Makefile, virtualenv, `project-plan.md`), then breaks the remaining work into **chained Todo items** that auto-start as their dependencies resolve — the board fills itself in and builds the app hands-off.

## What it builds

**"Doodle Together"** — a real-time multiplayer drawing app: Python + WebSockets backend, accounts, a shared live canvas, side chat, and a Pictionary game mode with a scoreboard. It serves under the `/kanban-demo` path prefix.

A finished reference output is live at **[ai.memention.net/kanban-demo](https://ai.memention.net/kanban-demo/)**.

## Why it's useful

Best single run for seeing task-breakdown, `requires` dependencies, and `auto_start` work together from one prompt (see the Features list in the top-level [README](../../README.md#try-the-demo)).

---

**See also**: [ARCHITECTURE](ARCHITECTURE.md) (the runtime the agents drive), [TESTING](TESTING.md) (the agents write tests as they go).
