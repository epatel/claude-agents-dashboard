#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The disposable target repo the E2E tests run agents against. Anchored to the
# dashboard checkout so the result doesn't depend on where the script is run from.
REPO_DIR="$SCRIPT_DIR/claude-agents-dashboard-e2e-test"

# Colors
GREEN=$'\033[32m'
RED=$'\033[31m'
RESET=$'\033[0m'

# Parse flags — pass remaining args to test scripts
VERBOSE=""
TEST_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -v|--verbose) VERBOSE="-v"; shift ;;
        --model) export E2E_MODEL="$2"; shift 2 ;;
        --model=*) export E2E_MODEL="${1#--model=}"; shift ;;
        *) TEST_ARGS+=("$1"); shift ;;
    esac
done

ensure_playwright() {
    if ! node -e "require('playwright')" 2>/dev/null; then
        echo "Installing playwright..."
        npm install --prefix "$SCRIPT_DIR" --no-save playwright
    fi
}

create_test_repo() {
    echo "Creating test repo at $REPO_DIR..."
    mkdir -p "$REPO_DIR"
    (
        cd "$REPO_DIR"
        git init
        git checkout -b main
        touch README.md
        git add README.md
        git commit -m "Initial commit with empty README"
    )
    echo "Test repo created"
}

# Set RESET_ANSWER: whether to reset the existing test repo, from $E2E_RESET
# (yes/no/ask, default ask). "ask" prompts on a TTY and keeps the repo otherwise,
# so the script is usable in CI / `make` / piped contexts with no TTY for `read`.
ask_reset() {
    RESET_ANSWER="${E2E_RESET:-ask}"
    if [ "$RESET_ANSWER" != "ask" ]; then
        return 0
    fi
    if [ -t 0 ]; then
        read -p "Test repo $REPO_DIR already exists. Reset it? [y/N] " RESET_ANSWER
    else
        echo "stdin is not a TTY — defaulting to KEEP. Set E2E_RESET=yes to force reset."
        RESET_ANSWER="no"
    fi
}

# Remove every worktree except the main checkout (the dashboard creates them
# under agents-lab/worktrees/, inside the repo).
remove_extra_worktrees() {
    local main wt
    main="$(git rev-parse --show-toplevel)"
    git worktree list --porcelain | sed -n 's/^worktree //p' | while read -r wt; do
        if [ "$wt" != "$main" ]; then
            git worktree remove --force "$wt" 2>/dev/null || true
        fi
    done
}

# Back to the initial commit: main checked out, no worktrees, no untracked files,
# no agents-lab/ data directory.
reset_test_repo() {
    echo "Resetting test repo..."
    (
        cd "$REPO_DIR"
        git checkout main 2>/dev/null || git checkout master 2>/dev/null || true
        remove_extra_worktrees
        git reset --hard HEAD
        git clean -fd
        rm -rf agents-lab
        # Drop references to worktrees whose directories are gone
        git worktree prune
    )
    echo "Test repo reset"
}

prepare_test_repo() {
    if [ ! -d "$REPO_DIR" ]; then
        create_test_repo
        return 0
    fi
    ask_reset
    case "$RESET_ANSWER" in
        [yY]|[yY][eE][sS]) reset_test_repo ;;
        *) echo "Keeping existing repo" ;;
    esac
}

# Run every tests/e2e/test_*.mjs against the test repo; print a summary and
# return non-zero when any of them failed.
run_tests() {
    local tests=("$SCRIPT_DIR"/tests/e2e/test_*.mjs)
    local total=${#tests[@]} passed=0 failed=0 failed_names=() test_file name

    for test_file in "${tests[@]}"; do
        name="$(basename "$test_file")"
        echo "--- Running: $name ---"
        if node "$test_file" "$REPO_DIR" $VERBOSE "${TEST_ARGS[@]+"${TEST_ARGS[@]}"}" 2>&1; then
            passed=$((passed + 1))
        else
            failed=$((failed + 1))
            failed_names+=("$name")
        fi
        echo ""
    done

    if [ "$failed" -eq 0 ]; then
        echo "${GREEN}=== E2E Results: $passed/$total passed ===${RESET}"
        return 0
    fi
    echo "${RED}=== E2E Results: $passed/$total passed, $failed failed ===${RESET}"
    echo "${RED}Failed tests:${RESET}"
    for name in "${failed_names[@]}"; do
        echo "  ${RED}- $name${RESET}"
    done
    return 1
}

ensure_playwright
prepare_test_repo

echo ""
echo "=== Running E2E tests ==="
[ -n "$VERBOSE" ] && echo "(verbose mode)"
[ -n "${E2E_MODEL:-}" ] && echo "Model override: $E2E_MODEL"
echo ""

run_tests
