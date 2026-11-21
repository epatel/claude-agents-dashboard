# setup-todo-list format (v1)

Two files live in the project root:

| File | Committed? | Owner | Purpose |
|---|---|---|---|
| `setup-todo-list.md` | yes | maintainers | Master list of setup steps |
| `setup-todo-list.local.md` | **no** (gitignored) | the agent, per machine | Copy of the master list plus progress state |

Secrets never go in either file. They go in `.env` or similar (which must be gitignored), and the local file only records `provided`.

## Master file: `setup-todo-list.md`

```markdown
---
setup-format: 1
project: my-app
---

# Project setup

> Agents: copy this file to `setup-todo-list.local.md` (gitignored) and work
> through the steps in order, recording progress in the copy. Respect each
> step's `gate`. Never write secrets into either file. To re-check later,
> compare the copy against this file by step id and `rev`.

## [flutter-sdk] Install Flutter SDK
- required: yes
- gate: approve
- rev: 2
- platforms: macos, linux
- check: `flutter --version | grep -E "Flutter 3\.(2[4-9]|[3-9][0-9])"`
- depends: —

Install Flutter 3.24 or newer. On macOS prefer `brew install --cask flutter`.

## [env-file] Create .env with API key
- required: yes
- gate: input
- rev: 1
- inputs: API_KEY (secret) — "Staging API key, ask #backend"
- check: `grep -q '^API_KEY=.' .env`

Copy `.env.example` to `.env` and fill in `API_KEY`.
```

### Step header
`## [<id>] <title>`. The `id` is kebab-case, stable and unique, and **never reused**. Renaming the title is fine. Changing the id counts as removing the old step and adding a new one.

### Step fields
| Field | Values | Default | Meaning |
|---|---|---|---|
| `required` | `yes` / `no` | `yes` | `no` = optional. The agent offers it and you can skip it without it counting as a failure. |
| `gate` | `auto` / `approve` / `input` | `approve` | `auto`: safe to run without asking (read-only, or local and reversible). `approve`: show what will run and wait for yes. `input`: ask for the values in `inputs` first, then treat it as `approve` unless the step says otherwise. |
| `rev` | integer | `1` | Bump this when the step's meaning changes (new version required, new command). Don't bump for typo fixes. A bump makes doctor re-flag the step. |
| `check` | shell command in backticks, or `manual` | `manual` | Exit code 0 means the step is satisfied. Must be read-only and fast. `manual` means you have to confirm it yourself. |
| `inputs` | `NAME (secret?) — "prompt"`, comma-separated | — | Values to ask for. Mark sensitive ones with `(secret)`. |
| `platforms` | `macos`, `linux`, `windows` | all | Skip the step on other platforms (status `n/a`). |
| `depends` | step ids | — | Must be `done` first. |

The body below the fields is free-form instructions for the agent and for humans.

## Local file: `setup-todo-list.local.md`

It's a verbatim copy of the master file with:

1. Extra frontmatter:
   ```yaml
   local-copy-of: setup-todo-list.md
   copied-at: 2026-11-21
   last-doctor: 2026-11-21
   master-commit: 3f2a9c1   # git log -1 --format=%h -- setup-todo-list.md, at last copy/reconcile
   ```
   `master-commit` lets doctor skip its run when the master hasn't changed: same hash and no uncommitted edits.
2. A `- status:` line added to every step, right after its header fields:
   ```
   - status: done @rev2 2026-11-21
   - status: skipped @rev1 2026-11-21 — "use system Python"
   - status: pending
   - status: failed @rev1 2026-11-21 — "brew not installed"
   - status: n/a — platform
   - status: obsolete — removed from master 2026-12-03
   ```
3. Optional `- answer: NAME=value` lines for **non-secret** inputs, and `- answer: NAME=provided (in .env)` for secrets.

`@revN` records which revision of the step the status applies to. That is what lets doctor see that the master file has moved on.

## Doctor comparison rules

For each step id in master ∪ local:

| Situation | Doctor reports | Symbol |
|---|---|---|
| In master, not in local | **new step** | `[!]` |
| `done @revN`, master rev > N | **step changed**, needs re-run | `[!]` |
| `done`, check exits 0 | ok | `[✓]` |
| `done`, check exits non-zero | **drift**: was done, now broken | `[✗]` |
| `done`, check is `manual` | ok (unverified) | `[~]` |
| `pending` / `failed`, required | not done | `[✗]` |
| `pending` / optional, or `skipped` | skipped/optional | `[-]` |
| `skipped @revN`, master rev > N | optional step changed, offer again | `[!]` |
| In local, not in master | removed upstream, mark obsolete | `[-]` |
| `n/a` | not for this platform | `[-]` |
