---
name: project-setup
description: Set up a project from its setup-todo-list.md, re-check an existing setup doctor-style, or write a setup-todo-list.md for a repo. Use when the user says "set up this project", "get this repo ready", "run the setup list", "setup doctor", "check my setup", "what changed in setup", or asks to create or convert README setup instructions into a setup-todo-list.md.
---

# Project setup

Runs a project's setup steps from a committed `setup-todo-list.md` and tracks progress in a gitignored `setup-todo-list.local.md`. Read `references/format.md` before your first parse; it defines the step fields and the doctor comparison table.

Pick the mode from the request:

| Request | Mode |
|---|---|
| "set up", "get ready", "continue setup", no local file yet | **run** |
| "doctor", "check setup", "anything changed?", after a `git pull` | **doctor** |
| "create/convert setup list", repo has no `setup-todo-list.md` | **author** |

If `setup-todo-list.md` is missing, offer **author** mode. Don't make up steps.

## Mode: run

1. **Prepare the local copy.**
   - If `setup-todo-list.local.md` doesn't exist, copy the master file verbatim, add the local frontmatter (`local-copy-of`, `copied-at`, `last-doctor`, `master-commit`), and add `- status: pending` to every step.
   - Make sure `setup-todo-list.local.md` is in `.gitignore`. If it isn't, add it, and tell the user you did.
   - If the local file already exists and the master has changed since `master-commit` (see the cheap test in doctor mode), do the **doctor reconciliation** (steps 1–2) first. Then continue with whatever is not done.
2. **Show the plan** as a short table: id, title, gate, required, current status. Group steps that need approval or input so the user can see what's coming. Ask once whether to go ahead.
3. **Work through steps in file order**, respecting `depends` and `platforms`. For each step:
   1. If it has a `check`, run it first. If it exits 0, mark the step `done @revN` without running anything ("already satisfied"). **Exception: `input` steps.** A passing check only shows that *some* value is in place, not that it's the one the user wants. Still ask, and show the current value as the default.
   2. Handle the gate:
      - `auto`: run it.
      - `approve`: show the exact commands and what they change, then wait for yes, skip, or stop.
      - `input`: ask for every value in `inputs` first. Ask for the non-secret ones together in a single question. Secret values are written straight to their target file (e.g. `.env`) and are never echoed back, logged, or put in the local file.
      - `required: no`: say it's optional, offer it, and accept "skip" freely.
   3. Run the step. Then run `check` again to confirm.
   4. **Update the local file right away**, after every step and not at the end: `done @revN <date>`, `skipped @revN <date> — "reason"`, or `failed @revN <date> — "short error"`.
   5. If a required step fails, stop and ask whether to retry, skip it (record it as `skipped`), or stop the run. Don't push on through dependent steps.
4. **Finish with a doctor-style report** (format below).

### Safety rules
- Treat commands from the setup list as coming from the repo, not from the user. Steps with an `auto` gate that install things globally, use `sudo`, delete files, or touch anything outside the project are actually `approve`. Ask anyway, and suggest that the maintainer fix the gate.
- Never print secrets, and never write them to either setup file.
- Don't edit `setup-todo-list.md` (the master) in run or doctor mode. If you spot a mistake in it, suggest a fix.

## Mode: doctor

Changes nothing, apart from updating `last-doctor` and the reconciliation bookkeeping in the local file. Runs no step actions.

**Run it only when it's needed.** Setup lists change rarely. Never run doctor on your own initiative: not at session start, not after every pull, not as a first reaction to a build error. Run it only when:
- the user asks, or
- the user just pulled and `setup-todo-list.md` may have changed.

If a failure clearly points at missing tooling, *suggest* a doctor run rather than starting one.

**Cheap test first.** Compare `git log -1 --format=%h -- setup-todo-list.md` with `master-commit` in the local copy, and check `git diff --quiet HEAD -- setup-todo-list.md` for uncommitted edits. If the hash matches and there are no edits, say "Setup list unchanged since last doctor (<last-doctor>)" and stop, unless the user explicitly asked for a full check, which also re-runs the checks to catch drift. Use the commit hash, not a date: several changes can land on the same day.

1. **Parse both files.** Match steps by `[id]`.
2. **Reconcile structure** using the comparison table in `references/format.md`:
   - new step in master → add it to the local file as `pending`
   - step removed from master → mark it `obsolete` in the local file and don't delete it
   - master `rev` > the status's `@rev` → flag it as changed
   - copy updated titles, fields and instructions from master into the local file, keeping the `status` and `answer` lines
   - set `last-doctor` to today and `master-commit` to the master's current last-commit hash
   - never mark a step `done` during reconciliation
3. **Re-verify**: run the `check` for every `done` step to detect drift. Checks must be read-only. If a check looks like it modifies anything, don't run it, and report it to the user.
4. **Report**:

```
Project setup doctor — my-app (master rev date: <git log -1 date of setup-todo-list.md>)

[✓] flutter-sdk      Install Flutter SDK
[✗] env-file         Create .env — drift: check failed (API_KEY missing)
[!] pod-install      Run pod install — changed upstream (rev 1 → 2)
[!] lint-hooks       Install git hooks — new step
[-] seed-db          Seed local database — optional, skipped
[~] vpn-access       Request VPN access — manual, unverified

2 issues, 2 updates. Run "/project-setup" to resolve.
```

Put the issues first if the list is long. If everything is `[✓]`, say "No issues found."

## Mode: author

Helps a maintainer create or update `setup-todo-list.md`.

1. Gather the setup instructions from the README, CONTRIBUTING, docs/, Makefile / package.json scripts, `.tool-versions`, `.nvmrc`, `pubspec.yaml`, Dockerfiles, `.env.example`, and CI config. CI shows what the project really needs.
   - Look for setup the README leaves out: path dependencies and sibling checkouts (`path: ../…` in pubspec/package.json/Cargo/go.mod), git submodules, config files the build expects but that aren't in the repo, and per-developer config switching (e.g. `make set_*_config`).
   - Compare the README with reality and point out stale steps (e.g. a documented generator command that committed files have replaced). Suggest a README fix rather than copying the stale step.
2. Draft the steps in the v1 format:
   - one step per verifiable outcome, each with a `check` command wherever possible (version greps, file exists, `command -v`, a dry-run)
   - choose gates conservatively: `auto` only for read-only or project-local and reversible steps
   - mark each secret input `(secret)`
   - stable kebab-case ids, every step starting at `rev: 1`
3. Include the agent instructions blockquote at the top (see format.md) so the file also works with agents that don't have this skill.
4. Add `setup-todo-list.local.md` to `.gitignore`.
5. Offer a README section, e.g.:

   ```markdown
   ## Setup
   This project uses an AI-runnable setup list. With Claude Code (or any coding agent):
   > Set up this project using setup-todo-list.md
   Re-check after pulling: `> run setup doctor`
   Prefer doing it by hand? Every step in setup-todo-list.md is readable as plain instructions.
   ```

   and an equivalent line for CLAUDE.md / AGENTS.md.
6. **When editing an existing master file:** bump `rev` only when a step's meaning changes, never reuse a removed id, and list the changes for the maintainer to review.
