#!/usr/bin/env bash
set -euo pipefail

export TERM="${TERM:-xterm-256color}"
export PY_COLORS=1
export FORCE_COLOR=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

# Create venv if needed
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# Install/update dependencies
"$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"

cd "$SCRIPT_DIR"
exec "$VENV_DIR/bin/python" -m pytest --color=yes tests/ "$@"
