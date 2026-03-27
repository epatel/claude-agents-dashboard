#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(pwd)/claude-agents-dashboard-e2e-test"

# Colors
GREEN=$'\033[32m'
RED=$'\033[31m'
RESET=$'\033[0m'

# Parse flags — pass remaining args to test scripts
VERBOSE=""
TEST_ARGS=()
for arg in "$@"; do
    case "$arg" in
        -v|--verbose) VERBOSE="-v" ;;
        *) TEST_ARGS+=("$arg") ;;
    esac
done

# Ensure playwright is installed
if ! node -e "require('playwright')" 2>/dev/null; then
    echo "Installing playwright..."
    npm install --prefix "$SCRIPT_DIR" --no-save playwright
fi

# Set up or reset the test repo
if [ -d "$REPO_DIR" ]; then
    read -p "Test repo $REPO_DIR already exists. Reset it? [y/N] " answer
    case "$answer" in
        [yY]|[yY][eE][sS])
            echo "Resetting test repo..."
            cd "$REPO_DIR"
            git checkout main 2>/dev/null || git checkout master 2>/dev/null || true
            # Remove all worktrees
            git worktree list --porcelain | grep "^worktree " | grep -v "$(pwd)" | while read -r _ wt; do
                git worktree remove --force "$wt" 2>/dev/null || true
            done
            # Prune stale worktree references
            git worktree prune
            # Reset to initial commit with empty README
            git reset --hard HEAD
            git clean -fd
            # Remove agents-lab data directory
            rm -rf agents-lab
            echo "Test repo reset"
            cd "$SCRIPT_DIR"
            ;;
        *)
            echo "Keeping existing repo"
            ;;
    esac
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
    echo "Test repo created"
fi

echo ""
echo "=== Running E2E tests ==="
[ -n "$VERBOSE" ] && echo "(verbose mode)"
echo ""

# Collect test files
tests=("$SCRIPT_DIR"/tests/e2e/test_*.mjs)
total=${#tests[@]}
passed=0
failed=0
failed_names=()

for test_file in "${tests[@]}"; do
    name="$(basename "$test_file")"
    echo "--- Running: $name ---"
    if node "$test_file" "$REPO_DIR" $VERBOSE "${TEST_ARGS[@]+"${TEST_ARGS[@]}"}" 2>&1; then
        ((passed++))
    else
        ((failed++))
        failed_names+=("$name")
    fi
    echo ""
done

if [ $failed -gt 0 ]; then
    echo "${RED}=== E2E Results: $passed/$total passed, $failed failed ===${RESET}"
    echo "${RED}Failed tests:${RESET}"
    for name in "${failed_names[@]}"; do
        echo "  ${RED}- $name${RESET}"
    done
    exit 1
else
    echo "${GREEN}=== E2E Results: $passed/$total passed ===${RESET}"
fi
