#!/usr/bin/env bash
set -euo pipefail

# Resolve the directory where this script lives (the dashboard repo)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure full user PATH is available (macOS GUI apps inherit a minimal PATH).
# Previous approach of sourcing .zshrc from bash fails because zsh config
# files use zsh-specific syntax. Instead, spawn the user's actual login shell
# to extract the fully-resolved PATH. Runs once per process tree.
init_user_path() {
    if [ -n "${__PATH_INITIALIZED:-}" ]; then
        return 0
    fi
    export __PATH_INITIALIZED=1
    local shell_path dir
    shell_path=$("${SHELL:-/bin/bash}" -l -c 'echo $PATH' 2>/dev/null || echo "")
    if [ -n "$shell_path" ]; then
        export PATH="$shell_path"
        return 0
    fi
    # Fallback: add common tool directories if login shell extraction failed
    for dir in /opt/homebrew/bin /opt/homebrew/sbin /usr/local/bin; do
        if [ -d "$dir" ] && [[ ":$PATH:" != *":$dir:"* ]]; then
            export PATH="$dir:$PATH"
        fi
    done
}
init_user_path

# Parse arguments: first positional arg is target project, rest are forwarded.
# The loop is flag-aware: options that take a separate value (--host, --port) consume
# the next argument, so `run.sh --port 8100` does not mistake 8100 for the target path.
TARGET_PROJECT=""
EXTRA_ARGS=()
expect_value=0
for arg in "$@"; do
    if [ "$expect_value" -eq 1 ]; then
        EXTRA_ARGS+=("$arg")
        expect_value=0
        continue
    fi
    case "$arg" in
        --host|--port)
            EXTRA_ARGS+=("$arg")
            expect_value=1
            ;;
        --*)
            EXTRA_ARGS+=("$arg")
            ;;
        *)
            if [ -z "$TARGET_PROJECT" ]; then
                TARGET_PROJECT="$arg"
            else
                EXTRA_ARGS+=("$arg")
            fi
            ;;
    esac
done
TARGET_PROJECT="${TARGET_PROJECT:-$(pwd)}"
TARGET_PROJECT="$(cd "$TARGET_PROJECT" && pwd)"

# Verify target is a git repo, or a folder containing ≥1 git subdir (multi-repo mode).
# Deeper validation (and friendlier error message) happens in src/main.py.
if ! git -C "$TARGET_PROJECT" rev-parse --git-dir > /dev/null 2>&1; then
    found_subrepo=""
    for sub in "$TARGET_PROJECT"/*/; do
        [ -d "$sub" ] || continue
        if git -C "$sub" rev-parse --git-dir > /dev/null 2>&1; then
            found_subrepo=1
            break
        fi
    done
    if [ -z "$found_subrepo" ]; then
        echo "Error: $TARGET_PROJECT is not a git repository and contains no git subdirectories"
        exit 1
    fi
fi

# Fetch the dashboard repo's upstream (silently) and set BEHIND to the number of
# commits it lacks. BEHIND stays unset when this is not a git checkout, the fetch
# fails, there is no upstream, or HEAD is already at the upstream commit.
fetch_dashboard_behind() {
    unset BEHIND
    git -C "$SCRIPT_DIR" rev-parse --git-dir > /dev/null 2>&1 || return 0
    git -C "$SCRIPT_DIR" fetch --quiet 2>/dev/null || return 0
    local local_head remote
    local_head=$(git -C "$SCRIPT_DIR" rev-parse HEAD 2>/dev/null)
    remote=$(git -C "$SCRIPT_DIR" rev-parse '@{u}' 2>/dev/null || echo "")
    if [ -z "$remote" ] || [ "$local_head" = "$remote" ]; then
        return 0
    fi
    BEHIND=$(git -C "$SCRIPT_DIR" rev-list --count HEAD..'@{u}' 2>/dev/null || echo "0")
}

# Ask whether to pull the dashboard repo's upstream commits, if there are any.
offer_dashboard_update() {
    local answer
    fetch_dashboard_behind
    if [ -z "${BEHIND+set}" ] || ! [ "$BEHIND" -gt 0 ]; then
        return 0
    fi
    echo "Dashboard repo has $BEHIND commit(s) available to pull."
    read -rp "Pull latest updates? [Y/n] " answer
    answer="${answer:-Y}"
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        echo "Pulling updates..."
        git -C "$SCRIPT_DIR" pull --quiet
        echo "Updated successfully."
    else
        echo "Skipping update."
    fi
}

# When AGENTS_DASHBOARD_AUTO_UPDATE=1 (set by the macOS app), skip the interactive prompt
if [ "${AGENTS_DASHBOARD_AUTO_UPDATE:-0}" != "1" ]; then
    offer_dashboard_update
fi

# Python venv bootstrap (needs Python >= 3.12; see scripts/python-env.sh)
. "$SCRIPT_DIR/scripts/python-env.sh"

VENV_DIR="$SCRIPT_DIR/venv"
ensure_venv "$VENV_DIR"

# Install/update dependencies
"$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"

# Launch the server (must run from the dashboard directory for module imports)
cd "$SCRIPT_DIR"

# Kill all child processes on exit to prevent orphaned Claude agent processes
# when the macOS wrapper (or terminal) closes. Only the rest of the process
# group is killed — never this shell — so the script exits with the server's
# own exit code, or 128+N when stopped by signal N.
cleanup() {
    local status=$?
    trap - EXIT
    # The group-wide SIGTERM below also reaches this shell; ignore it here.
    trap '' TERM INT HUP
    kill -TERM -- -$$ 2>/dev/null || true
    sleep 0.5
    # Force-kill any stragglers in the group, except this shell
    local pid
    for pid in $(pgrep -g "$$" 2>/dev/null); do
        if [ "$pid" != "$$" ]; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

"$VENV_DIR/bin/python" -m src.main "$TARGET_PROJECT" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
