# Shared Python venv bootstrap, sourced by run.sh, run-tests.sh and `make setup`.
# Defines ensure_venv <dir>; tests: tests/unit/test_python_env.py.
# Python floor: kimi-agent-sdk / kimi-cli declare Requires-Python >=3.12, and the
# macOS system python3 (/usr/bin/python3) is 3.9. The macOS wrapper relies on this
# too — it only clones the repo and lets run.sh build the venv.
MIN_PYTHON="3.12"

# True when $1 runs and is at least $MIN_PYTHON (false for a missing/dangling binary).
python_ok() {
    "$1" -c "import sys; sys.exit(sys.version_info[:2] < tuple(map(int, '$MIN_PYTHON'.split('.'))))" \
        > /dev/null 2>&1
}

# Print the first suitable interpreter on PATH, newest first.
find_python() {
    local cand path
    for cand in python3.14 python3.13 python3.12 python3; do
        path="$(command -v "$cand" 2>/dev/null)" || continue
        if python_ok "$path"; then
            echo "$path"
            return 0
        fi
    done
    return 1
}

# Create $1 as a venv on Python >= $MIN_PYTHON, rebuilding one made with an older
# (or since-removed) interpreter. Falls back to a uv-managed Python when no
# suitable interpreter is on PATH.
ensure_venv() {
    local venv_dir="$1" python_bin
    if [ -d "$venv_dir" ] && ! python_ok "$venv_dir/bin/python"; then
        echo "Existing virtual environment is not on Python >= $MIN_PYTHON; rebuilding it..."
        rm -rf "$venv_dir"
    fi
    [ -d "$venv_dir" ] && return 0

    if python_bin="$(find_python)"; then
        echo "Creating virtual environment with $python_bin..."
        "$python_bin" -m venv "$venv_dir"
    elif command -v uv > /dev/null 2>&1; then
        echo "No Python >= $MIN_PYTHON on PATH; creating virtual environment with a uv-managed Python..."
        uv venv --seed --python "$MIN_PYTHON" "$venv_dir"
    else
        echo "Error: Python >= $MIN_PYTHON is required, but none was found on PATH."
        echo "  (python3 is $(python3 --version 2>&1 || echo 'not installed'))"
        echo "Install one, then run again:"
        echo "  brew install python@$MIN_PYTHON"
        echo "  or install uv (https://docs.astral.sh/uv/) — run.sh then fetches Python itself"
        return 1
    fi
}
