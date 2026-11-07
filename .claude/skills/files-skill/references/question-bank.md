# Question Bank for Phase 5

Templates for the human-in-the-loop triage step. Use structured options where possible — they're easier and faster than free-text. Group related questions together to keep momentum.

## Triage template (per contradiction)

Use this template for each contradiction surfaced in Phase 4. Adapt wording to the specific concern.

> I found two patterns in the codebase for **[concern]**:
>
> - **A:** [pattern A], used in [N] files (examples: [paths])
> - **B:** [pattern B], used in [M] files (examples: [paths])
>
> How should I classify these?

Options:
- A is canonical; B is legacy (don't extend, recognize only)
- B is canonical; A is legacy
- Both are acceptable for now (note in output as "either is fine")
- A is canonical and B is being actively migrated (legacy + migration note)
- B is canonical and A is being actively migrated
- Neither — we want to move to a third pattern (specify)

## Direction questions (asked once per run)

Use these to surface conventions that don't show up in the code yet but the team has opinions about.

### When the codebase is silent on a concern

> I didn't find a consistent pattern for **[concern]** in the sampled files. Is that:
- Intentional — we don't have a convention here
- An oversight — we should have one but don't
- Aspirational — we want one going forward (specify what)

### Hidden conventions

> Are there rules the team follows that wouldn't be visible from reading the code? For example:
- Libraries we deliberately avoid (and why)
- Patterns we prefer that aren't obvious from frequency (e.g., "prefer composition over inheritance")
- Files/directories that are off-limits for new code
- Anything an outsider would get wrong without being told

### Migrations in flight

> Is there a migration in progress that the agent should know about? Common shapes:
- Pattern X is being replaced by pattern Y across the codebase
- Library X is being phased out in favor of library Y
- A directory or module is deprecated and being moved
- Anything else where "current state" and "target state" differ deliberately

### Exemplar files

> For each architectural layer, what's a file you'd point a new contributor at as the canonical example?
- (Layer 1, e.g., "service"): ___
- (Layer 2, e.g., "repository"): ___
- (Layer 3, e.g., "test"): ___

Limit to two or three. Many is worse than few — the agent will read every one cited.

### Off-limits or warning zones

> Any files or directories where the agent should tread carefully or refuse to modify without explicit instruction?
- Generated code
- Vendored / third-party code
- Migrations / historical files
- Other (specify)

## When to skip a question

- If the codebase is uniform on a concern, don't ask about it. Just record the convention and move on.
- If the user has already answered a question implicitly elsewhere in the conversation, don't re-ask. Confirm if needed.
- If a contradiction is trivial (e.g., 47 files do X, 1 file does Y, and Y looks like a one-off), classify Y as legacy automatically and mention it briefly rather than triaging.
