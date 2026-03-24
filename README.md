# Agents Dashboard

A standalone scrum board that orchestrates Claude agents working on your project. Each board item becomes a task for an AI agent that works in its own git worktree, keeping changes isolated until you approve and merge them.

## How it works

1. **Create items** on the kanban board (Todo → Doing → Clarify → Review → Done → Archive)
2. **Start an agent** on a Todo item — it gets its own git worktree and runs autonomously
3. **Watch progress** in real-time via the work log (thinking, tool use, messages)
4. **Review changes** — browse the diff, approve to merge into main, or request changes
5. **Agent remembers** — when you request changes, it resumes its session with full context

## Quick start

From your project repository:

```bash
path/to/claude-agents-dashboard/run.sh
```

Or pass the project path explicitly:

```bash
path/to/claude-agents-dashboard/run.sh /path/to/your/project
```

The server starts at `http://127.0.0.1:8000` (auto-increments if the port is busy). Your project must be a git repository.

## What it creates

An `agents-lab/` directory in your project (auto-added to `.gitignore`):

```
your-project/agents-lab/
  dashboard.db        # SQLite database
  assets/             # Uploaded images/attachments
  worktrees/          # Git worktrees for active agent tasks
```

## Features

- **Kanban board** with drag-and-drop (smooth card spacing), create/edit/delete items
- **Agent orchestration** via Claude Agent SDK — multiple agents can run simultaneously
- **Git worktrees** — each agent works in isolation, branched off main
- **Live work log** — streaming agent output via WebSocket (messages, thinking, tool use)
- **Review & merge** — tabbed dialog with description, diff viewer, and work log; approve or request changes
- **Clarification flow** — agents can ask the user questions mid-task via custom MCP tool
- **Session persistence** — request changes resumes the agent's conversation with full context
- **Annotation canvas** — drop images, scale/move them, draw arrows, circles, rectangles, and text; saved as PNG attachments
- **Attachments** — attach annotated screenshots and reference images to items
- **Agent config** — set system prompt, model, and project context with tooltips
- **Light/dark mode** — respects system preference with manual toggle

## Architecture

- **Backend**: Python, FastAPI, uvicorn, aiosqlite
- **Frontend**: Jinja2 templates, vanilla HTML/CSS/JS, WebSocket
- **Agent**: Claude Agent SDK (`claude-agent-sdk`)
- **Security**: Localhost only, no authentication

## Requirements

- Python 3.12+
- Git
- A Claude API key (set `ANTHROPIC_API_KEY` environment variable)

## Multiple projects

Each project gets its own server instance. Run `run.sh` from different repos — ports auto-increment (8000, 8001, 8002, ...).
