#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

# Create venv if needed
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
fi

cd "$SCRIPT_DIR"

echo "Running tests with coverage..."
"$VENV_DIR/bin/python" -m pytest tests/ \
    --cov=src \
    --cov-branch \
    --cov-report=term-missing \
    --cov-report=html:htmlcov \
    "$@"

echo ""
echo "HTML report: open htmlcov/index.html"
