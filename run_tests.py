#!/usr/bin/env python3
"""
Test Runner Script for the Agent Dashboard

Provides easy commands to run different test suites:
- All tests
- Unit tests only (fast)
- Integration tests only
- P0 priority tests (core components)
- Coverage reports
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd: list[str]) -> int:
    """Run a command and return exit code."""
    print(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd).returncode


def run_tests(args):
    """Run the specified test suite."""
    base_cmd = ["python", "-m", "pytest"]

    if args.suite == "all":
        cmd = base_cmd + ["tests/"]
    elif args.suite == "unit":
        cmd = base_cmd + ["-m", "unit", "tests/unit/"]
    elif args.suite == "integration":
        cmd = base_cmd + ["-m", "integration", "tests/integration/"]
    elif args.suite == "p0":
        # Run P0 priority tests (migrations + orchestrator lifecycle)
        cmd = base_cmd + [
            "tests/unit/migrations/test_migration_runner.py",
            "tests/integration/test_orchestrator_lifecycle.py"
        ]
    elif args.suite == "p1":
        # Run P1 priority tests (git ops + API routes + path validation + MCP tools)
        cmd = base_cmd + [
            "tests/unit/test_git_operations.py",
            "tests/unit/test_api_routes.py",
            "tests/unit/test_path_validation.py",
            "tests/integration/test_mcp_tool_callbacks.py",
            "tests/unit/test_websocket_manager.py"
        ]
    elif args.suite == "smoke":
        cmd = base_cmd + ["-m", "smoke"]
    else:
        print(f"Unknown test suite: {args.suite}")
        return 1

    # Add additional options
    if args.verbose:
        cmd.append("-v")
    if args.fail_fast:
        cmd.append("-x")
    if args.no_coverage:
        cmd.extend(["--no-cov"])
    if args.parallel:
        cmd.extend(["-n", "auto"])

    return run_command(cmd)


def run_coverage_report():
    """Generate and open coverage report."""
    print("Generating coverage report...")
    subprocess.run(["python", "-m", "pytest", "--cov=src", "--cov-report=html", "tests/"])

    coverage_file = Path("htmlcov/index.html")
    if coverage_file.exists():
        print(f"Coverage report generated: {coverage_file.absolute()}")
        try:
            import webbrowser
            webbrowser.open(f"file://{coverage_file.absolute()}")
        except Exception:
            print("Could not open browser automatically")
    else:
        print("Coverage report not found")


def check_dependencies():
    """Check if required test dependencies are installed."""
    required = ["pytest", "pytest-asyncio", "pytest-cov"]
    missing = []

    for package in required:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            missing.append(package)

    if missing:
        print(f"Missing test dependencies: {', '.join(missing)}")
        print("Install with: pip install " + " ".join(missing))
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Run test suites for the Agent Dashboard")

    # Test suite selection
    parser.add_argument(
        "suite",
        choices=["all", "unit", "integration", "p0", "p1", "smoke"],
        help="Test suite to run"
    )

    # Options
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("-x", "--fail-fast", action="store_true", help="Stop on first failure")
    parser.add_argument("--no-coverage", action="store_true", help="Disable coverage reporting")
    parser.add_argument("-j", "--parallel", action="store_true", help="Run tests in parallel (requires pytest-xdist)")

    # Special commands
    parser.add_argument("--coverage-report", action="store_true", help="Generate and open HTML coverage report")
    parser.add_argument("--check-deps", action="store_true", help="Check test dependencies")

    args = parser.parse_args()

    if args.check_deps:
        if check_dependencies():
            print("All test dependencies are installed ✓")
            return 0
        else:
            return 1

    if args.coverage_report:
        run_coverage_report()
        return 0

    if not check_dependencies():
        return 1

    return run_tests(args)


if __name__ == "__main__":
    exit_code = main()

    if exit_code == 0:
        print("\n✓ Tests completed successfully!")
    else:
        print(f"\n✗ Tests failed with exit code {exit_code}")

    sys.exit(exit_code)