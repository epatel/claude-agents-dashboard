---
name: brainstorm
description: Use when asked to brainstorm, explore ideas, design a feature, or plan something new. Turns a vague idea into a concrete design through structured Q&A before creating any board items.
version: 1.0.0
---

# Brainstorm

Turn ideas into concrete designs through focused Q&A, then create an Epic with Todos on the board.

## Rules

1. **No board items until the design is approved.** Do not call create_epic or create_todo until the user says the design looks good.
2. **One question at a time.** Prefer multiple-choice. Keep it conversational.
3. **YAGNI.** Cut scope aggressively. The user can always add more later.

## Process

### 1. Understand

- Read the board (mcp__board_view__view_board) to see existing work
- Ask clarifying questions one at a time:
  - What is the goal?
  - What are the constraints?
  - What does "done" look like?
- If the scope is too large for one epic, say so and help decompose

### 2. Propose

- Propose 2-3 approaches with trade-offs
- Lead with your recommendation and why
- Keep each approach to 2-3 sentences

### 3. Design

- Present the design section by section
- Scale detail to complexity: one sentence for simple parts, a short paragraph for complex ones
- Ask "Does this look right?" after presenting
- Revise until the user approves

### 4. Create Board Items

Once approved:

1. **Create an Epic** via mcp__todo__create_epic with a descriptive title and a color that fits the theme
2. **Create Todos** via mcp__todo__create_todo, each assigned to the epic via epic_id
   - Each todo should be a concrete, actionable task
   - Title: imperative verb + what ("Add login form", "Write auth tests")
   - Description: enough detail for an agent to execute without ambiguity
3. **Set commit message** summarizing what was planned

### Writing Good Todos

- **One thing per todo.** If it has "and" in the title, split it.
- **Specific, not vague.** "Add retry logic to API client" not "Improve error handling"
- **Include acceptance criteria** in the description when the task is non-obvious
- **Order matters.** Create foundational tasks first (they appear at the top of the epic group)
