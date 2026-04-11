#!/usr/bin/env bash
set -euo pipefail

# Resolve the directory where this script lives (the dashboard repo)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ensure full user PATH is available (macOS GUI apps inherit a minimal PATH).
# Previous approach of sourcing .zshrc from bash fails because zsh config
# files use zsh-specific syntax. Instead, spawn the user's actual login shell
# to extract the fully-resolved PATH.
if [ -z "${__PATH_INITIALIZED:-}" ]; then
    export __PATH_INITIALIZED=1
    USER_SHELL="${SHELL:-/bin/bash}"
    SHELL_PATH=$("$USER_SHELL" -l -c 'echo $PATH' 2>/dev/null || echo "")
    if [ -n "$SHELL_PATH" ]; then
        export PATH="$SHELL_PATH"
    else
        # Fallback: add common tool directories if login shell extraction failed
        for dir in /opt/homebrew/bin /opt/homebrew/sbin /usr/local/bin; do
            if [ -d "$dir" ] && [[ ":$PATH:" != *":$dir:"* ]]; then
                export PATH="$dir:$PATH"
            fi
        done
    fi
fi

# Parse arguments: first positional arg is target project, rest are forwarded
TARGET_PROJECT=""
EXTRA_ARGS=()
for arg in "$@"; do
    if [ -z "$TARGET_PROJECT" ] && [[ "$arg" != --* ]]; then
        TARGET_PROJECT="$arg"
    else
        EXTRA_ARGS+=("$arg")
    fi
done
TARGET_PROJECT="${TARGET_PROJECT:-$(pwd)}"
TARGET_PROJECT="$(cd "$TARGET_PROJECT" && pwd)"

# Verify target is a git repo
if ! git -C "$TARGET_PROJECT" rev-parse --git-dir > /dev/null 2>&1; then
    echo "Error: $TARGET_PROJECT is not a git repository"
    exit 1
fi

# Check if the dashboard repo has upstream commits to pull
# When AGENTS_DASHBOARD_AUTO_UPDATE=1 (set by the macOS app), skip the interactive prompt
if [ "${AGENTS_DASHBOARD_AUTO_UPDATE:-0}" != "1" ]; then
    if git -C "$SCRIPT_DIR" rev-parse --git-dir > /dev/null 2>&1; then
        # Fetch latest from remote (silently)
        if git -C "$SCRIPT_DIR" fetch --quiet 2>/dev/null; then
            LOCAL=$(git -C "$SCRIPT_DIR" rev-parse HEAD 2>/dev/null)
            REMOTE=$(git -C "$SCRIPT_DIR" rev-parse '@{u}' 2>/dev/null || echo "")
            if [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
                BEHIND=$(git -C "$SCRIPT_DIR" rev-list --count HEAD..'@{u}' 2>/dev/null || echo "0")
                if [ "$BEHIND" -gt 0 ]; then
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
                fi
            fi
        fi
    fi
fi

# Set up venv if needed
VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Install/update dependencies
"$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"

# Launch the server (must run from the dashboard directory for module imports)
cd "$SCRIPT_DIR"

# Kill all child processes on exit to prevent orphaned Claude agent processes
# when the macOS wrapper (or terminal) closes.
cleanup() {
    # Send SIGTERM to the entire process group
    kill -- -$$ 2>/dev/null || true
    sleep 0.5
    # Force-kill any stragglers
    kill -9 -- -$$ 2>/dev/null || true
}
trap cleanup EXIT TERM INT HUP

"$VENV_DIR/bin/python" -m src.main "$TARGET_PROJECT" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
