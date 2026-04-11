#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
REPO_DIR="$(pwd)/claude-agents-dashboard-e2e-test"

# Colors
GREEN=$'\033[32m'
RED=$'\033[31m'
YELLOW=$'\033[33m'
RESET=$'\033[0m'

# Create venv if needed
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"
fi

cd "$SCRIPT_DIR"

# Clean previous coverage data
rm -f .coverage .coverage.* htmlcov-combined -rf

echo "${GREEN}=== Phase 1: Unit & Integration Tests ===${RESET}"
echo ""

"$VENV_DIR/bin/python" -m pytest tests/ \
    --cov=src \
    --cov-branch \
    --cov-report=term \
    -q \
    "$@"

# Rename the coverage file so it doesn't get overwritten
mv .coverage .coverage.unit

echo ""
echo "${GREEN}=== Phase 2: E2E Tests (server under coverage) ===${RESET}"
echo ""

# Ensure playwright is installed
if ! node -e "require('playwright')" 2>/dev/null; then
    echo "Installing playwright..."
    npm install --prefix "$SCRIPT_DIR" --no-save playwright
fi

# Set up or reset the test repo (non-interactive: always reset if exists)
if [ -d "$REPO_DIR" ]; then
    echo "Resetting test repo..."
    cd "$REPO_DIR"
    git checkout main 2>/dev/null || git checkout master 2>/dev/null || true
    git worktree list --porcelain | grep "^worktree " | grep -v "$(pwd)" | while read -r _ wt; do
        git worktree remove --force "$wt" 2>/dev/null || true
    done
    git worktree prune
    git reset --hard HEAD
    git clean -fd
    rm -rf agents-lab
    cd "$SCRIPT_DIR"
else
    echo "Creating test repo at $REPO_DIR..."
    mkdir -p "$REPO_DIR"
    cd "$REPO_DIR"
    git init
    git checkout -b main
    touch README.md
    git add README.md
    git commit -m "Initial commit with empty README"
    cd "$SCRIPT_DIR"
fi

# Start server under coverage
echo "Starting server under coverage..."
"$VENV_DIR/bin/python" -m coverage run \
    --source=src \
    --branch \
    --data-file=.coverage.e2e \
    -m src.main "$REPO_DIR" &
SERVER_PID=$!

# Wait for server to be ready
echo -n "Waiting for server"
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:8000/api/items > /dev/null 2>&1; then
        echo " ready!"
        break
    fi
    echo -n "."
    sleep 1
done

if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo ""
    echo "${RED}Server failed to start${RESET}"
    exit 1
fi

# Run E2E tests
tests=("$SCRIPT_DIR"/tests/e2e/test_*.mjs)
total=${#tests[@]}
passed=0
failed=0
failed_names=()

for test_file in "${tests[@]}"; do
    name="$(basename "$test_file")"
    echo "--- Running: $name ---"
    if node "$test_file" "$REPO_DIR" 2>&1; then
        ((passed++))
    else
        ((failed++))
        failed_names+=("$name")
    fi
    echo ""
done

# Stop server gracefully so coverage data is flushed
echo "Stopping server..."
kill -INT $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

# Small delay to ensure .coverage.e2e is written
sleep 1

echo ""
echo "${GREEN}=== Phase 3: Combining Coverage ===${RESET}"
echo ""

# Combine coverage data
"$VENV_DIR/bin/python" -m coverage combine .coverage.unit .coverage.e2e 2>/dev/null || {
    # If e2e coverage wasn't produced (server killed before flush), use unit only
    echo "${YELLOW}Warning: Could not combine E2E coverage, using unit tests only${RESET}"
    cp .coverage.unit .coverage
}

# Generate reports
"$VENV_DIR/bin/python" -m coverage report --sort=-miss
"$VENV_DIR/bin/python" -m coverage html -d htmlcov

echo ""
echo "HTML report: open htmlcov/index.html"
echo ""

# Print E2E summary
if [ $failed -gt 0 ]; then
    echo "${RED}=== E2E: $passed/$total passed, $failed failed ===${RESET}"
    for name in "${failed_names[@]}"; do
        echo "  ${RED}- $name${RESET}"
    done
else
    echo "${GREEN}=== E2E: $passed/$total passed ===${RESET}"
fi

# Clean up temp files
rm -f .coverage.unit .coverage.e2e
