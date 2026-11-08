#!/usr/bin/env bash
set -euo pipefail

export TERM="${TERM:-xterm-256color}"
export PY_COLORS=1
export FORCE_COLOR=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

# Create (or rebuild a too-old) venv; needs Python >= 3.12
. "$SCRIPT_DIR/scripts/python-env.sh"
ensure_venv "$VENV_DIR"

# Install/update dependencies
"$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"
"$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements-test.txt"

cd "$SCRIPT_DIR"

# Run the whole tree unless a test path was given (pytest node ids such as
# tests/unit/test_x.py::TestY count as paths).
TARGETS=(tests/)
FULL_RUN=1
for arg in "$@"; do
    if [ -e "${arg%%::*}" ]; then
        TARGETS=()
        FULL_RUN=0
        break
    fi
done

# Code-health gate (M12 step 7): after a green full run, fail if an aihealth
# score drops below its floor. Floors sit a little under the scores M12 reached
# (project 9.77, src 9.72) so rule tweaks in aihealth don't trip it; raise them
# as the code improves. Skipped for narrowed runs, with AIHEALTH_GATE=0, or when
# aihealth is not installed.
HEALTH_FLOORS=(".:9.5" "src:9.6")

health_gate() {
    if [ "${AIHEALTH_GATE:-1}" = "0" ]; then
        echo "Code-health gate skipped (AIHEALTH_GATE=0)"
        return 0
    fi
    if ! command -v aihealth >/dev/null 2>&1; then
        echo "Code-health gate skipped: aihealth is not installed"
        return 0
    fi
    local failed=0 spec path floor output score
    for spec in "${HEALTH_FLOORS[@]}"; do
        path="${spec%%:*}"
        floor="${spec##*:}"
        if output=$(aihealth scan "$path" --fail-under "$floor" 2>&1); then
            score=$(printf '%s\n' "$output" | grep -m1 "project score" | sed -E 's/.*project score: ([0-9.]+).*/\1/')
            echo "Code health $path: ${score:-?} (floor $floor) — ok"
        else
            score=$(printf '%s\n' "$output" | grep -m1 "project score" | sed -E 's/.*project score: ([0-9.]+).*/\1/')
            echo "Code health $path: ${score:-?} is below the floor $floor — run 'aihealth scan $path' for the findings" >&2
            failed=1
        fi
    done
    return $failed
}

"$VENV_DIR/bin/python" -m pytest --color=yes ${TARGETS[@]+"${TARGETS[@]}"} "$@" || exit $?

if [ "$FULL_RUN" = "1" ]; then
    health_gate
fi
