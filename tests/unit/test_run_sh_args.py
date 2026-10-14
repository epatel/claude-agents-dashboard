"""
Tests for the argument parsing in the `run.sh` wrapper.

`run.sh` picks the target project out of its own argv before forwarding the rest
to `src.main` (which uses argparse). The original loop treated any argument that
did not start with `--` as the target, so `run.sh --port 8100` took `8100` as the
target path and failed the git check with a confusing message. These tests pin
the flag-aware behaviour: options that carry a separate value consume it.

The parse block is extracted from `run.sh` and run under bash on its own, so the
test never starts a server or touches the venv.
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SH = REPO_ROOT / "run.sh"

# Options in src/main.py's argparse that take a separate value. Kept here so the
# test fails loudly if a new value-taking option is added to main.py but not to
# the run.sh parse loop.
VALUE_OPTIONS = ("--host", "--port")


def _parse_block() -> str:
    """Extract the target/EXTRA_ARGS parse loop from run.sh."""
    lines = RUN_SH.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('TARGET_PROJECT=""'))
    end = next(i for i, line in enumerate(lines[start:], start) if line == "done")
    return "\n".join(lines[start:end + 1])


def _parse(*argv: str) -> tuple[str, list[str]]:
    """Run the extracted parse block with argv, returning (target, extra_args)."""
    script = (
        "set -euo pipefail\n"
        + _parse_block()
        + '\nprintf "%s\\n" "$TARGET_PROJECT"'
        + '\nprintf "%s\\n" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}\n'
    )
    result = subprocess.run(
        ["bash", "-c", script, "run.sh", *argv],
        capture_output=True, text=True, check=True,
    )
    target, *extra = result.stdout.split("\n")
    return target, [arg for arg in extra if arg]


def test_run_sh_syntax_is_valid():
    assert subprocess.run(["bash", "-n", str(RUN_SH)]).returncode == 0


@pytest.mark.parametrize("option", VALUE_OPTIONS)
def test_value_option_without_target_keeps_target_empty(option):
    """`run.sh --port 8100` must not take 8100 as the target path."""
    target, extra = _parse(option, "8100")
    assert target == ""
    assert extra == [option, "8100"]


def test_target_before_options():
    target, extra = _parse("/tmp/proj", "--port", "8100")
    assert target == "/tmp/proj"
    assert extra == ["--port", "8100"]


def test_target_after_options():
    target, extra = _parse("--experimental", "--port", "8100", "/tmp/proj")
    assert target == "/tmp/proj"
    assert extra == ["--experimental", "--port", "8100"]


def test_option_with_inline_value_consumes_no_following_arg():
    target, extra = _parse("--port=8100", "/tmp/proj")
    assert target == "/tmp/proj"
    assert extra == ["--port=8100"]


def test_host_value_is_forwarded_not_treated_as_target():
    target, extra = _parse("--host", "0.0.0.0", "--ui-map")
    assert target == ""
    assert extra == ["--host", "0.0.0.0", "--ui-map"]


def test_bare_target_only():
    target, extra = _parse("/tmp/proj")
    assert target == "/tmp/proj"
    assert extra == []


def test_no_arguments():
    target, extra = _parse()
    assert target == ""
    assert extra == []


def test_flag_only_options_are_forwarded():
    target, extra = _parse("--experimental", "--ui-map")
    assert target == ""
    assert extra == ["--experimental", "--ui-map"]


def test_value_options_match_mains_argparse():
    """Every value-taking option of src/main.py is handled by run.sh's loop."""
    main_src = (REPO_ROOT / "src" / "main.py").read_text()
    block = _parse_block()
    for option in VALUE_OPTIONS:
        assert f'"{option}"' in main_src, f"{option} no longer exists in src/main.py"
        assert option in block, f"{option} missing from run.sh parse loop"
