# PROJECT_MAP Strategy

Plan for building a shared shorthand vocabulary so the user can reference parts of the project unambiguously and Claude can resolve those references to the right files/symbols without round-trips.

## Goal

Replace phrases like "the merge-conflict auto-resolution path in WorkflowService" or "that thing in the corner" with stable, dotted names like `flow.merge` and `topbar.wip-limit`. Both sides agree on the names; Claude maps them to code locations instantly.

## Filename

`PROJECT_MAP.md` (lives at repo root). "Map" suggests navigation; "dictionary" would suggest definitions only.

## Naming convention

`subsystem.element[-modifier]`, dotted, lowercase, kebab-case for multi-word parts.

Examples:
- UI: `card.btn-merge`, `card.title`, `board.column-doing`, `dialog.clarify.input`, `topbar.wip-limit`, `notif.stale-worktree`
- Flows: `flow.merge`, `flow.clarify`, `flow.wip-queue`, `flow.stale-scan`, `flow.pause-resume`, `flow.multi-repo-start`

Sibling names like `flow.merge` and `card.btn-merge` make the connection obvious (the button kicks off the flow).

## Two sections, one document

### 1. UI elements
- **Source of truth:** `data-map-name="..."` attributes added directly on elements in Jinja2 templates and JS card builders.
- **Why on the element itself:** self-documenting, greppable, can't drift from the markup.
- **Doc generation:** a small script greps for `data-map-name=` and emits the UI section of PROJECT_MAP.md. Stays fresh automatically.
- **Coverage:** only tag things actually referenced in conversation — buttons, dialog inputs, columns, distinct regions. ~40–60 names total. Untagged elements are fine; add the attribute when one is needed.

### 2. Flows / processes
- **Hand-curated** (no DOM node to attach to).
- **Per entry:** one-line purpose, entry-point `file:line`, key WebSocket events, related DB tables.
- **Initial set (~10–15)** drawn from CLAUDE.md: merge, clarify, pause/resume, WIP queue, stale-scan, multi-repo start, MCP tool flows, etc.

## Live overlay (the discovery surface for UI names)

A `?map=1` query param (or Cmd+Shift+M toggle) injects a small debug script:
- Hover any element with `data-map-name` → tooltip showing the name.
- Click → copy name to clipboard.
- Lives at `static/js/map_overlay.js`, only loaded when the param is present, zero cost in normal use.
- ~50 lines of vanilla JS, fits the no-build-step architecture.

**Why overlay-on-real-app over a clickable mockup:** mockups go stale instantly, can't capture dialogs or hover/drag states, and need separate maintenance. The overlay always shows real state.

## Optional v2 tie-in (skip for now)

Overlay reads agent state and badges cards mid-flow — e.g., a card currently merging shows a small `flow.merge` tag. Cute, not essential.

## Order of operations

1. **Draft PROJECT_MAP.md with the flows section first** (~10–15 entries from CLAUDE.md). Pure doc, no code change, immediately useful as a vocabulary check.
2. **Build the overlay** (`static/js/map_overlay.js` + `?map=1` toggle). Lets the user click around and see/propose names live.
3. **Tag UI elements** with `data-map-name` as the user points them out via the overlay, batch by batch.
4. **Add the auto-gen script** that greps `data-map-name` and rewrites the UI section of PROJECT_MAP.md.

## Tradeoffs considered

- **Naming style:** chose functional aliases (`flow.merge`) over codenames (`Mergebot`) — self-documenting, no learning cost — and over hierarchical IDs (`BE/workflow/merge`) — less bureaucratic.
- **UI discovery:** chose live overlay over static mockup for staleness reasons.
- **Coverage:** chose selective tagging over exhaustive — avoids noise, lets the vocabulary grow with actual usage.
