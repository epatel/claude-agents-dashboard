<a href="https://claude.ai"><img src="made-with-claude.png" height="32" alt="Made with Claude"></a>

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

The server starts at `http://127.0.0.1:8000` (auto-increments ports 8000–8019 if busy). Your project must be a git repository.

## What it creates

An `agents-lab/` directory in your project (auto-added to `.gitignore`):

```
your-project/agents-lab/
  dashboard.db        # SQLite database
  assets/             # Uploaded images/attachments
  worktrees/          # Git worktrees for active agent tasks
```

The SQLite database uses a versioned migration system to manage schema changes safely.

## Features

- **Kanban board** with drag-and-drop (smooth card spacing), create/edit/delete items
- **Agent orchestration** via Claude Agent SDK — multiple agents can run simultaneously
- **Git worktrees** — each agent works in isolation, branched off main
- **Live work log** — streaming agent output via WebSocket (messages, thinking, tool use)
- **Review & merge** — tabbed dialog with description, diff viewer, and work log; approve or request changes
- **Clarification flow** — agents can ask the user questions mid-task via custom MCP tool
- **Todo creation** — agents can create new todo items while working, breaking down complex tasks into smaller actionable items
- **Custom commit messages** — agents set meaningful commit messages via MCP tool, used when merging
- **Cost tracking** — agent completion logs USD cost for each task
- **Retry & cancel** — cancel a running agent or retry a failed one; retries reuse the existing worktree
- **Session persistence** — request changes resumes the agent's conversation with full context
- **Annotation canvas** — drop images, scale/move them, draw arrows, circles, rectangles, and text; saved as PNG attachments
- **Attachments** — attach annotated screenshots and reference images to items
- **Per-item model selection** — override the default model on individual items (falls back to global config)
- **Agent config** — set system prompt, model, project context, and MCP servers
- **MCP support** — connect external tools and data sources via Model Context Protocol
- **Merge conflict detection** — merge conflicts abort cleanly, keeping the worktree intact for resolution
- **Item cleanup** — deleting an item stops running agents, removes worktrees and branches, and cleans up attachment files
- **Light/dark mode** — respects system preference with manual toggle

## Architecture

- **Backend**: Python, FastAPI, uvicorn, aiosqlite
- **Frontend**: Jinja2 templates, vanilla HTML/CSS/JS, WebSocket
- **Agent**: Claude Agent SDK (`claude-agent-sdk` v0.1.50+), default model: `claude-sonnet-4-20250514`
- **Security**: Localhost only, no authentication

## Requirements

- **Python 3.12+** (tested on macOS, Linux, and Windows with WSL)
- **Git** (any modern version)
- **Claude API key** - set the `ANTHROPIC_API_KEY` environment variable
- **Internet connection** - for Claude API calls

## Example use cases

- **Bug fixes**: Create a "Fix login error" item, let an agent analyze logs and implement a solution
- **Feature development**: "Add dark mode toggle" → agent updates CSS, templates, and JavaScript
- **Code refactoring**: "Extract payment logic to service" → agent reorganizes code while preserving functionality
- **Documentation**: "Update API docs" → agent reviews code and updates documentation files
- **Testing**: "Add unit tests for user service" → agent analyzes code and writes comprehensive tests
- **Task breakdown**: Agents can create follow-up todos like "Add integration tests" or "Update documentation" as they discover related work

## Database Management

The project uses a SQLite database with a versioned migration system for safe schema updates.

### Migration Commands

From the project root directory:

```bash
# Show current migration status
python -m src.manage status

# Run all pending migrations (also runs automatically on startup)
python -m src.manage migrate

# Migrate to a specific version
python -m src.manage migrate --to 002

# Rollback to a specific version
python -m src.manage rollback 001

# Initialize a fresh database
python -m src.manage init
```

### Database Location

The SQLite database is created at `your-project/agents-lab/dashboard.db`. You can specify a different location:

```bash
python -m src.manage status --db-path /path/to/custom/database.db
```

### Creating Migrations

1. Copy the migration template: `src/migrations/versions/000_template.py.example`
2. Rename to format: `XXX_description.py` (e.g., `003_add_user_settings.py`)
3. Update version number and description
4. Implement `up()` method (apply changes) and `down()` method (rollback changes)
5. Test thoroughly before deploying

## Troubleshooting

### Common issues

**Port already in use**: The server auto-increments ports (8000 → 8001 → 8002...), but if all ports in range are busy, restart the conflicting services or wait a moment.

**API key not found**: Ensure `ANTHROPIC_API_KEY` is set in your shell environment:
```bash
export ANTHROPIC_API_KEY=your_api_key_here
echo $ANTHROPIC_API_KEY  # Should print your key
```

**Git worktree errors**: If you see git worktree issues, check that your project has at least one commit on the main/master branch:
```bash
git log --oneline -1  # Should show at least one commit
```

**Permission denied**: On some systems, you may need to make `run.sh` executable:
```bash
chmod +x /path/to/claude-agents-dashboard/run.sh
```

**Python version**: Verify you have Python 3.12+:
```bash
python3 --version  # Should show 3.12.0 or higher
```

### Getting help

If agents seem stuck or unresponsive, check the work log in the UI for error messages. You can always stop a running agent and restart it, or move items back to "Todo" to try a different approach.

## Multiple projects

Each project gets its own server instance. Run `run.sh` from different repos — ports auto-increment (8000, 8001, 8002, ...).
