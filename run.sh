#!/usr/bin/env bash
set -euo pipefail

# Resolve the directory where this script lives (the dashboard repo)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
exec "$VENV_DIR/bin/python" -m src.main "$TARGET_PROJECT" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
