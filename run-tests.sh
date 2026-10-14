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
"$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements-test.txt"

cd "$SCRIPT_DIR"

# Run the whole tree unless a test path was given (pytest node ids such as
# tests/unit/test_x.py::TestY count as paths).
TARGETS=(tests/)
for arg in "$@"; do
    if [ -e "${arg%%::*}" ]; then
        TARGETS=()
        break
    fi
done

exec "$VENV_DIR/bin/python" -m pytest --color=yes ${TARGETS[@]+"${TARGETS[@]}"} "$@"
