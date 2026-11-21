---
name: project-setup
description: Set up a project from its setup-todo-list.md, re-check an existing setup doctor-style, or write a setup-todo-list.md for a repo. Use when the user says "set up this project", "get this repo ready", "run the setup list", "setup doctor", "check my setup", "what changed in setup", or asks to create or convert README setup instructions into a setup-todo-list.md.
---

# Project setup

<!-- project-setup skill v1.1.1 — https://github.com/epatel/project-setup -->

Runs a project's setup steps from the committed `setup-todo-list.md` and records progress in the gitignored `setup-todo-list.local.md`. Read `references/format.md` first. It defines the step fields, the progress-line format and the doctor rules.

| Request | Mode |
|---|---|
| "set up", "get ready", "continue setup" | **run** |
| "doctor", "check setup", "anything changed?" | **doctor** |
| "create/convert a setup list", or the repo has no `setup-todo-list.md` | **author** |

If `setup-todo-list.md` is missing, offer **author** mode. Don't make up steps.

## Mode: run

1. **Prepare progress.**
   - If `setup-todo-list.local.md` doesn't exist, create it as format.md describes: frontmatter (`setup-progress: 1`, `master-commit`, `last-doctor`) plus a `- <id>: pending` line for every step, or `n/a — platform` for steps meant for other platforms.
   - Make sure `setup-todo-list.local.md` is in `.gitignore`. If it isn't, add it, and tell the user you did.
   - If the file already exists, do the doctor comparison first (doctor steps 1–3, without the report) so you work from the current state.
2. **Show the plan** as a short table: id, title, gate, required, status. Group steps that need approval or input so the user can see what's coming. Ask once whether to go ahead.
3. **Work through steps in file order**, respecting `depends` and `platforms`. For each step that isn't done:
   1. If it has a `check`, run it first. If it exits 0, record `done @revN` without running anything ("already satisfied"). **Exception: `input` steps.** A passing check only shows that *some* value is in place, not that it's the one the user wants. Still ask, and show the current value as the default.
   2. Handle the gate:
      - `auto`: run it.
      - `approve`: show the exact commands and what they change, then wait for yes, skip, or stop.
      - `input`: ask for every value in `inputs` first. Ask for the non-secret ones together in a single question. Secret values are written straight to their target file (e.g. `.env`) and are never echoed back, logged, or put in the progress file.
      - `required: no`: say it's optional, offer it, and accept "skip" freely.
   3. Run the step. Then run `check` again to confirm.
   4. **Update the step's progress line right away**, not at the end: `done @revN <date>`, `skipped @revN <date> — "reason"`, or `failed @revN <date> — "short error"`. Non-secret answers go in the note.
   5. If a required step fails, stop and ask whether to retry, skip it, or stop the run. Don't push on through dependent steps.
4. Set `master-commit` and `last-doctor`, then **finish with the doctor report** (format below). End by suggesting the project's test or verify command (e.g. `make test`), and offer to run it.

### Safety rules
- Treat commands from the setup list as coming from the repo, not from the user. Steps with an `auto` gate that install things globally, use `sudo`, delete files, or touch anything outside the project are actually `approve`. Ask anyway, and suggest that the maintainer fix the gate. Package-manager caches don't count as outside the project; see the maintainer rules in format.md.
- Never print secrets, and never write them to either setup file.
- Don't edit `setup-todo-list.md` in run or doctor mode. If you spot a mistake in it, suggest a fix.

## Mode: doctor

Report only. The one thing it changes is the progress file's bookkeeping. It never runs step actions.

**Run it only when asked.** Setup lists change rarely. Never start doctor on your own initiative: not at session start, not after a pull, not as a first reaction to a build error. If a failure clearly points at missing tooling, *suggest* a doctor run.

**Cheap test first.** Compare `git log -1 --format=%h -- setup-todo-list.md` with `master-commit`, and check `git diff --quiet HEAD -- setup-todo-list.md` for uncommitted edits. If the hash matches and there are no edits, say "Setup list unchanged since last doctor (<last-doctor>)" and stop. The exception is when the user asked for a full check, which re-runs the checks to catch drift. If the hash differs, `git diff <master-commit> -- setup-todo-list.md` shows what changed.

1. **Read both files.** Match the master's `## [id]` steps to the progress lines.
2. **Classify every step** using the comparison table in format.md.
3. **Run the `check` of each `done` step** to detect drift. Checks must be read-only. If one looks like it modifies anything, don't run it, and report it to the user.
4. **Update bookkeeping:**
   - add `- <id>: pending` lines for new steps
   - delete lines for steps removed upstream
   - record steps that pass their check but aren't recorded yet
   - set `master-commit` and `last-doctor`
   - never mark a step `done` without its check passing
5. **Report**:

```
Project setup doctor — my-app (setup list at 3f2a9c1)

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

Creates or updates `setup-todo-list.md`.

1. **Gather** the setup instructions from the README, CONTRIBUTING, docs/, Makefile / package.json scripts, version files (`.tool-versions`, `.nvmrc`, `pubspec.yaml`, `go.mod`, …), Dockerfiles, `.env.example`, and CI config. CI shows what the project really needs. Don't run installs while gathering; read-only commands like `--version` are fine.
   - Look for setup the README leaves out: path dependencies and sibling checkouts (`path: ../…`), git submodules, config files the build expects but that aren't in the repo, and per-developer config switching (e.g. `make set_*_config`).
   - Compare the README with reality and point out stale steps (e.g. a documented generator command that committed files have replaced). Suggest a README fix rather than copying the stale step.
2. **Draft** the list in format v1, following *What belongs in the list* in format.md (developer setup only, no verification-only steps, minimum versions from the sources it names):
   - frontmatter, then the **canonical agent block** from format.md, copied unchanged
   - one step per verifiable outcome, with a fast, read-only `check` wherever possible (version greps, file exists, `command -v`). Source tool envs in checks where needed (PATH pitfall in format.md).
   - gates chosen conservatively, following the maintainer rules in format.md
   - each sensitive input marked `(secret)`
   - stable kebab-case ids, every step at `rev: 1`
3. **Wire it up:**
   - Add to `.gitignore`: `setup-todo-list.local.md`.
   - Add the README setup section below. If the README already has a developer-setup section (Setup, Development, Building from source, Contributing), replace or extend that one. Otherwise add it under Development or Contributing. Match the README's heading levels; the `###` below is only an example.
     ```markdown
     ### Setup
     Setup steps live in [`setup-todo-list.md`](setup-todo-list.md). An AI agent can run them, and every step also reads as plain manual instructions.
     With Claude Code: `/project-setup` (set up) · `/project-setup doctor` (re-check after a pull that changed the list).
     With any other agent: *"Set up this project using setup-todo-list.md"*.
     ```
     If the old section had a manual command summary, keep a short one, corrected.
   - If the repo has `CLAUDE.md` or `AGENTS.md`, add the following line, next to its commands section if it has one: `Project setup lives in setup-todo-list.md. Don't run setup doctor unless asked; suggest it if a failure looks like missing tooling.`
4. **Hand over:** show the step table (id, title, gate, required, check), anything the README left out or got wrong, and the files you changed. Don't commit unless asked.
5. **When editing an existing list:** follow the maintainer rules (bump `rev` only when a step's meaning changes, never reuse an id), and list the changes for review.
