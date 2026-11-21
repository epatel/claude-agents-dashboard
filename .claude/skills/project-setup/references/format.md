# setup-todo-list format (v1)

Two files live in the project root:

| File | Committed? | Written by | Purpose |
|---|---|---|---|
| `setup-todo-list.md` | yes | maintainers | The setup steps |
| `setup-todo-list.local.md` | **no** (gitignored) | the agent, per machine | Progress: one line per step |

Secrets never go in either file. They go in `.env` or similar (which must be gitignored), and progress only records `provided`.

## Master file: `setup-todo-list.md`

```markdown
---
setup-format: 1
project: my-app
---

# Project setup

> **Agents:** set this project up by working through the steps below in order.
> Record progress in `setup-todo-list.local.md` (gitignored), one line per step:
> `- <id>: done @rev<N> <date>`, or `skipped` / `failed` with a reason.
> Respect each step's `gate`: `auto` = just run it, `approve` = show the commands
> and wait for a yes, `input` = ask for the listed values first. Run a step's
> `check` first; if it passes, the step is already done (for `input` steps,
> still confirm the value). Never write secrets into either file. To re-check
> later ("doctor"), compare the progress lines with this file by id and `rev`,
> and re-run the checks.
>
> **Humans:** every step below is plain instructions. Follow them by hand if you prefer.

## [flutter-sdk] Install Flutter SDK
- required: yes
- gate: approve
- rev: 2
- platforms: macos, linux
- check: `flutter --version | grep -Eq "Flutter 3\.(2[4-9]|[3-9][0-9])"`

Install Flutter 3.24 or newer. On macOS prefer `brew install --cask flutter`.

## [env-file] Create .env with API key
- required: yes
- gate: input
- rev: 1
- inputs: API_KEY (secret) — "Staging API key, ask #backend"
- check: `grep -q '^API_KEY=.' .env`

Copy `.env.example` to `.env` and fill in `API_KEY`.
```

The blockquote above is the **canonical agent block**. Copy it into every setup list unchanged, so the list also works with agents that don't have the skill. CI checks that the example matches it.

### Step header
`## [<id>] <title>`. The `id` is kebab-case, stable and unique, and **never reused**. Renaming the title is fine. Changing the id counts as removing the old step and adding a new one.

### Step fields
| Field | Values | Default | Meaning |
|---|---|---|---|
| `required` | `yes` / `no` | `yes` | `no` = optional. The agent offers it and you can skip it without it counting as a failure. |
| `gate` | `auto` / `approve` / `input` | `approve` | `auto`: safe to run without asking (read-only, or local and reversible). `approve`: show what will run and wait for yes. `input`: ask for the values in `inputs` first, then treat it as `approve`. |
| `rev` | integer | `1` | Bump this when the step's meaning changes. A bump makes doctor re-flag the step. |
| `check` | shell command in backticks, or `manual` | `manual` | Exit code 0 means the step is satisfied. Runs in a non-interactive `bash` (Git Bash on Windows), so tools installed through shell init (`~/.cargo/bin`, nvm, pyenv, …) may not be on PATH. Source their env in the check, e.g. `. "$HOME/.cargo/env" 2>/dev/null; rustc --version`. Must be read-only and fast. `manual` means you have to confirm it yourself. |
| `inputs` | `NAME (secret?) — "prompt"`, comma-separated | — | Values to ask for. Mark sensitive ones with `(secret)`. |
| `platforms` | `macos`, `linux`, `windows` | all | Skip the step on other platforms. |
| `depends` | step ids | — | Must be `done` first. |

The body below the fields is free-form instructions for the agent and for humans.

### Maintainer rules
- Never reuse or rename an `id`. Retire it and add a new one instead.
- Bump `rev` when a step's meaning changes (new minimum version, different command). Don't bump it for wording fixes.
- Every `check` must be read-only, fast, and exit 0 when the step is satisfied.
- `auto` is only for read-only or project-local, reversible steps. Anything global, `sudo`, or with side effects outside the project is `approve`.
  - Package-manager caches (`~/.cargo/registry`, `~/.npm`, the pub cache, …) count as project-local. Fetching dependencies and building (`cargo build`, `npm ci`, `flutter pub get`) can be `auto`.
  - Installing tools from a remote source is `approve`, even into a project-local `.venv` or `node_modules`, because it runs code fetched from outside the lockfile.

### What belongs in the list
- **Developer setup only:** what someone needs to build, run and work on the project. End-user install instructions (prebuilt binaries, installing into `~/bin`) stay in the README.
- **No verification-only steps.** "Tests pass" or "lint is clean" has no fast read-only check, so doctor would show it as unverified forever. Run mode instead ends by suggesting the project's test command.
- **Minimum versions:** take them from version files (`rust-toolchain.toml`, `.nvmrc`, `.tool-versions`, the `environment` in `pubspec.yaml`), from CI, or from the dependencies' declared minimums (`rust-version` via `cargo metadata`, `engines`, `python_requires`). Use the highest of them.

## Local file: `setup-todo-list.local.md`

Progress only. It is not a copy of the master.

```markdown
---
setup-progress: 1
master-commit: 3f2a9c1
last-doctor: 2026-11-21
---
# Setup progress (local, gitignored, written by the agent)

- flutter-sdk: done @rev2 2026-11-21
- cocoapods: n/a — platform
- env-file: done @rev1 2026-11-21 — API_BASE_URL=https://staging.example.com, API_KEY=provided (.env)
- pub-get: failed @rev1 2026-11-21 — "network timeout"
- firebase-cli: skipped @rev1 2026-11-21 — "only needed for rules deploy"
- vpn-access: pending
```

- **One line per master step**: `- <id>: <status> [@rev<N> <date>] [— note]`. The status is `pending`, `done`, `skipped`, `failed` or `n/a`.
- **When the file is created**, every step gets a line (`pending`, or `n/a` for other platforms). That way a step that's missing a line later is clearly *new*.
- **`@revN`** is the step's rev when the status was recorded. That's how doctor sees that a step has changed since.
- **Notes** after ` — ` hold failure reasons, skip reasons, and non-secret input answers. Secrets only appear as `provided`.
- **`master-commit`** is `git log -1 --format=%h -- setup-todo-list.md` at the last run or doctor. If it still matches and there are no uncommitted edits, doctor has nothing new to compare. To see what changed in the master since then, run `git diff <master-commit> -- setup-todo-list.md`.

## Doctor comparison rules

For each step id in the master, plus any leftover progress lines:

| Situation | Doctor reports | Symbol |
|---|---|---|
| Step in master, no progress line | **new step** | `[!]` |
| `done @revN`, master rev > N | **step changed**, needs re-run | `[!]` |
| `skipped @revN`, master rev > N | optional step changed, offer again | `[!]` |
| `done`, check exits 0 | ok | `[✓]` |
| `done`, check exits non-zero | **drift**: was done, now broken | `[✗]` |
| `done`, check is `manual` | ok (unverified) | `[~]` |
| `pending` / `failed`, required, check passes | ok, just not recorded yet (record it) | `[✓]` |
| `pending` / `failed`, required | not done | `[✗]` |
| `pending`, optional, or `skipped` | optional / skipped | `[-]` |
| `n/a` | not for this platform | `[-]` |
| Progress line with no matching master step | removed upstream (delete the line) | `[-]` |
