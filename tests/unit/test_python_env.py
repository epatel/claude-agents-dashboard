"""
Tests for the shared Python venv bootstrap, `scripts/python-env.sh`.

The dependencies need Python >= 3.12 (kimi-agent-sdk declares it), but the macOS
system python3 is 3.9. The bootstrap must pick a suitable interpreter, rebuild a
venv made with an older one, fall back to uv, and otherwise fail with a clear
message. run.sh, run-tests.sh and `make setup` source it; the macOS wrapper only
clones and lets run.sh build the venv.

The script is sourced under bash against stub interpreters on a sealed PATH, so
the test never creates a real venv.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ENV_SH = REPO_ROOT / "scripts" / "python-env.sh"
BASH = shutil.which("bash")

# A fake interpreter: `-c` (the version probe) exits with its "too old" status,
# `--version` prints its version, `-m venv DIR` creates DIR/bin/python as a copy of itself.
STUB_PYTHON = """#!{bash}
case "$1" in
    -c) exit {probe_status} ;;
    --version) echo "Python {version}" ;;
    -m) mkdir -p "$3/bin" && cp "$0" "$3/bin/python" && echo "$0" > "$3/created-by" ;;
esac
"""

# A fake uv: `uv venv --seed --python X DIR` creates a venv backed by a 3.12 stub.
STUB_UV = """#!{bash}
dir="${{@: -1}}"
mkdir -p "$dir/bin"
printf '#!{bash}\\ncase "$1" in -c) exit 0 ;; esac\\n' > "$dir/bin/python"
chmod +x "$dir/bin/python"
echo uv > "$dir/created-by"
"""


@pytest.fixture
def env(tmp_path):
    """A sealed PATH: a stub dir plus only the coreutils the block needs."""
    stubs = tmp_path / "stubs"
    tools = tmp_path / "tools"
    stubs.mkdir()
    tools.mkdir()
    for tool in ("mkdir", "cp", "rm", "chmod"):
        (tools / tool).symlink_to(shutil.which(tool))
    return {"stubs": stubs, "path": f"{stubs}:{tools}", "tmp": tmp_path}


def _stub_python(env, name, version):
    too_old = tuple(map(int, version.split("."))) < (3, 12)
    stub = env["stubs"] / name
    stub.write_text(STUB_PYTHON.format(bash=BASH, probe_status=int(too_old), version=version))
    stub.chmod(0o755)
    return stub


def _stub_uv(env):
    stub = env["stubs"] / "uv"
    stub.write_text(STUB_UV.format(bash=BASH))
    stub.chmod(0o755)


def _run(env, body: str) -> subprocess.CompletedProcess:
    script = f'set -euo pipefail\n. "{PYTHON_ENV_SH}"\n{body}\n'
    return subprocess.run(
        [BASH, "-c", script],
        capture_output=True, text=True, env={"PATH": env["path"]},
    )


@pytest.mark.parametrize("script", ["run.sh", "run-tests.sh"])
def test_entry_scripts_use_the_shared_bootstrap(script):
    """No entry script creates the venv with a bare `python3 -m venv` any more."""
    text = (REPO_ROOT / script).read_text()
    assert "scripts/python-env.sh" in text
    assert 'ensure_venv "$VENV_DIR"' in text
    assert "python3 -m venv" not in text


def test_python_ok_accepts_the_running_interpreter(env):
    """The real version probe passes on the >= 3.12 interpreter running the tests."""
    assert sys.version_info >= (3, 12)
    assert _run(env, f'python_ok "{sys.executable}"').returncode == 0


def test_python_ok_rejects_missing_binary(env):
    assert _run(env, f'python_ok "{env["tmp"]}/nope/python"').returncode != 0


def test_find_python_skips_too_old_python3(env):
    _stub_python(env, "python3", "3.9.6")
    newer = _stub_python(env, "python3.12", "3.12.7")
    result = _run(env, "find_python")
    assert result.returncode == 0
    assert result.stdout.strip() == str(newer)


def test_find_python_prefers_newest(env):
    _stub_python(env, "python3.12", "3.12.7")
    newest = _stub_python(env, "python3.13", "3.13.1")
    assert _run(env, "find_python").stdout.strip() == str(newest)


def test_find_python_fails_when_only_old_python(env):
    _stub_python(env, "python3", "3.9.6")
    assert _run(env, "find_python").returncode != 0


def test_ensure_venv_creates_with_suitable_python(env):
    good = _stub_python(env, "python3.12", "3.12.7")
    venv = env["tmp"] / "venv"
    result = _run(env, f'ensure_venv "{venv}"')
    assert result.returncode == 0, result.stdout + result.stderr
    assert (venv / "created-by").read_text().strip() == str(good)


def test_ensure_venv_keeps_a_good_venv(env):
    _stub_python(env, "python3.12", "3.12.7")
    venv = env["tmp"] / "venv"
    _run(env, f'ensure_venv "{venv}"')
    (venv / "keep-me").write_text("x")
    assert _run(env, f'ensure_venv "{venv}"').returncode == 0
    assert (venv / "keep-me").exists()


def test_ensure_venv_rebuilds_venv_made_with_old_python(env):
    old = _stub_python(env, "python3", "3.9.6")
    venv = env["tmp"] / "venv"
    (venv / "bin").mkdir(parents=True)
    shutil.copy(old, venv / "bin" / "python")
    good = _stub_python(env, "python3.13", "3.13.1")
    result = _run(env, f'ensure_venv "{venv}"')
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rebuilding" in result.stdout
    assert (venv / "created-by").read_text().strip() == str(good)


def test_ensure_venv_rebuilds_venv_with_dangling_python(env):
    """A venv whose interpreter was removed (e.g. by a brew upgrade) is rebuilt."""
    venv = env["tmp"] / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(env["tmp"] / "gone" / "python3")
    _stub_python(env, "python3.12", "3.12.7")
    assert _run(env, f'ensure_venv "{venv}"').returncode == 0
    assert (venv / "created-by").exists()


def test_ensure_venv_falls_back_to_uv(env):
    _stub_python(env, "python3", "3.9.6")
    _stub_uv(env)
    venv = env["tmp"] / "venv"
    result = _run(env, f'ensure_venv "{venv}"')
    assert result.returncode == 0, result.stdout + result.stderr
    assert (venv / "created-by").read_text().strip() == "uv"


def test_ensure_venv_fails_clearly_without_python_or_uv(env):
    _stub_python(env, "python3", "3.9.6")
    venv = env["tmp"] / "venv"
    result = _run(env, f'ensure_venv "{venv}"')
    assert result.returncode != 0
    assert "Python >= 3.12 is required" in result.stdout
    assert "3.9.6" in result.stdout
    assert "brew install python@3.12" in result.stdout
    assert not venv.exists()
