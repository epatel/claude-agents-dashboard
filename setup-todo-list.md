---
setup-format: 1
project: claude-agents-dashboard
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

All commands run from the dashboard checkout (this repo's root). The dashboard
itself needs no per-project setup: `run.sh` creates `agents-lab/` in the target
project on first launch.

## [git] Git available
- required: yes
- gate: approve
- rev: 1
- check: `git --version`
- depends: —

Any modern Git. On macOS, `xcode-select --install` or `brew install git`.
The target project you point the dashboard at must be a git repo, or a folder
of sibling git repos (multi-repo mode).

## [python-312] Python 3.12 or newer (or uv)
- required: yes
- gate: approve
- rev: 1
- check: `for p in python3.14 python3.13 python3.12 python3; do "$p" -c 'import sys; assert sys.version_info >= (3, 12)' 2>/dev/null && break; done || command -v uv >/dev/null`
- depends: —

`scripts/python-env.sh` picks the newest `python3.1x` on PATH that is 3.12+.
The macOS system Python (`/usr/bin/python3`) is 3.9 and does not qualify.
If no suitable Python is found but `uv` is installed, the venv is built with a
uv-managed Python instead. Install one of:
- `brew install python@3.12` (or newer), or
- uv: https://docs.astral.sh/uv/

The scripts never install Python, uv or Homebrew on their own.

## [claude-code] Claude Code CLI installed
- required: yes
- gate: approve
- rev: 1
- check: `command -v claude >/dev/null`
- depends: —

Agents run through the Claude Agent SDK, which uses your Claude Code session —
no API key is needed. Install Claude Code: https://claude.com/claude-code

## [claude-login] Logged in to Claude Code
- required: yes
- gate: approve
- rev: 1
- check: manual
- depends: claude-code

Run `claude` once in a terminal and complete the login. This is interactive;
an agent can't do it for you. Confirm that `claude` starts without asking you
to log in.

## [github-access] GitHub reachable for the Kimi SDK fork
- required: yes
- gate: auto
- rev: 1
- check: `git ls-remote --exit-code https://github.com/epatel/kimi-agent-sdk agentic-setup >/dev/null`
- depends: git

`requirements.txt` installs `kimi-agent-sdk` from a git fork (the ACP client
is not on PyPI). The install needs GitHub access even if you never use the
Kimi provider.

## [python-venv] Create venv and install dependencies
- required: yes
- gate: auto
- rev: 1
- check: `venv/bin/python -c 'import sys, fastapi, uvicorn, aiosqlite, jinja2, kimi_agent_sdk, pytest, httpx; from importlib.metadata import version; assert sys.version_info >= (3, 12); assert tuple(map(int, version("claude-agent-sdk").split(".")[:3])) >= (0, 2, 165)'`
- depends: python-312, github-access

Run `make setup`. It creates `venv/` (rebuilding one made with a Python older
than 3.12) and installs `requirements.txt` plus `requirements-test.txt`.
Project-local: undo with `rm -rf venv`.

`run.sh` and `run-tests.sh` also do this on every start, so this step mostly
makes the first launch fast. A bare `pytest` does not reinstall requirements:
if 5 tests in `tests/unit/test_allowed_commands.py` fail on
`verbatim_prompts`, the venv has a `claude-agent-sdk` older than 0.2.165 —
rerun this step.

## [smoke-tests] Smoke tests pass
- required: yes
- gate: auto
- rev: 1
- check: `venv/bin/python -m pytest -q -p no:cacheprovider tests/smoke/`
- depends: python-venv

Confirms the install works. The full suite is `./run-tests.sh`; with no test
path it also runs the `aihealth` code-health gate (see `aihealth`).

## [aihealth] aihealth code-health CLI
- required: no
- gate: approve
- rev: 1
- check: `command -v aihealth >/dev/null`
- depends: —

Maintainer tooling. A full `./run-tests.sh` fails if the health score drops
below the floors in `HEALTH_FLOORS`, and `.mcp.json` starts `aihealth mcp` for
Claude Code. Without `aihealth` on PATH, the gate is skipped and the MCP server
does not start. Ask the maintainer where to install it from (it is not on a
public index); `uv tool install` into `~/.local/bin` is the usual layout.

## [node-e2e] Node.js and npm for the E2E suite
- required: no
- gate: approve
- rev: 1
- check: `command -v node >/dev/null && command -v npm >/dev/null`
- depends: —

Only for `./run-e2e-tests.sh` (Playwright, Node). On macOS:
`brew install node`. E2E runs spawn real agents and cost tokens.

## [playwright-chromium] Playwright and its Chromium browser
- required: no
- gate: approve
- rev: 1
- check: `node -e "require('fs').accessSync(require('playwright').chromium.executablePath())"`
- depends: node-e2e

`run-e2e-tests.sh` runs `npm install --no-save playwright` on demand, but
that does not download the browser. Install both up front:

```bash
npm install --no-save playwright
npx playwright install chromium
```

The browser goes to the user-wide Playwright cache
(`~/Library/Caches/ms-playwright` on macOS).

## [kimi-cli] Kimi CLI for the experimental Kimi provider
- required: no
- gate: approve
- rev: 1
- check: `v=$(kimi --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1) && [ "$(printf '0.27.0\n%s\n' "$v" | sort -V | head -1)" = 0.27.0 ]`
- depends: —

Only for `kimi-*` models, shown with `./run.sh <target> --experimental`.
Install the Kimi Code CLI (>= 0.27.0) so `kimi` is on PATH, then run
`kimi login` once (interactive OAuth). For headless use, set `KIMI_API_KEY` in
your shell environment instead. Details: `AGENT_FILES/CARDS/KIMI_PROVIDER.md`.

## [tiiny-key] Tiiny API key for the experimental Tiiny provider
- required: no
- gate: input
- rev: 1
- platforms: macos, linux
- inputs: TIINY_API_KEY (secret) — "API key of your local Tiiny device"
- check: `[ -n "${TIINY_API_KEY:-}" ] || security find-generic-password -s tiiny-api-key >/dev/null 2>&1`
- depends: —

Only for `tiiny/*` models (`--experimental`). The dashboard never stores the
key in its database. It reads `$TIINY_API_KEY`, else (macOS) the Keychain
entry `tiiny-api-key`. Preferred on macOS — the command prompts for the key,
so it never lands in shell history:

```bash
security add-generic-password -s tiiny-api-key -a "$USER" -w
```

Elsewhere, export `TIINY_API_KEY` from your shell profile. Then set the device
URL in Settings ▸ Tiiny. Details: `AGENT_FILES/CARDS/TIINY_PROVIDER.md`.

## [macos-wrapper] Build the macOS wrapper app from source
- required: no
- gate: approve
- rev: 1
- platforms: macos
- check: `test -d "wrappers/macos/.build/release/Agents Dashboard.app"`
- depends: —

Optional — a prebuilt `.app` is on the Releases page. Needs Xcode (Swift
toolchain) and macOS 14+. Run `make -C wrappers/macos release`
(`make -C wrappers/macos install` copies it to `/Applications`). Code signing
and notarization are only for distribution: copy `wrappers/macos/.env.example`
to `wrappers/macos/.env` and fill in the credentials there (never here). See
`wrappers/macos/README.md`.
