import argparse
import atexit
import os
import signal
import sys
import socket
import subprocess
from pathlib import Path

from .config import DATA_DIR_NAME, DEFAULT_HOST, DEFAULT_PORT, MAX_PORT_TRIES


def _get_all_descendant_pids(root_pid: int) -> list[int]:
    """Recursively find all descendant PIDs of a process using pgrep."""
    descendants = []
    try:
        result = subprocess.run(
            ["pgrep", "-P", str(root_pid)],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().splitlines():
            child_pid = int(line.strip())
            descendants.append(child_pid)
            # Recurse into grandchildren
            descendants.extend(_get_all_descendant_pids(child_pid))
    except Exception:
        pass
    return descendants


def _kill_child_processes():
    """Kill all descendant processes (children, grandchildren, etc.) of the current process.

    This is a last-resort cleanup to prevent orphaned Claude agent processes
    when the macOS wrapper (or any parent) terminates the server.
    Uses recursive pgrep to find the entire process tree, since pkill -P
    only kills direct children and misses grandchildren spawned by the SDK.
    """
    import logging
    logger = logging.getLogger(__name__)
    pid = os.getpid()

    descendants = _get_all_descendant_pids(pid)
    if not descendants:
        return

    logger.info(f"Killing {len(descendants)} descendant process(es): {descendants}")

    # Send SIGTERM to all descendants (leaf-first = reversed)
    for dpid in reversed(descendants):
        try:
            os.kill(dpid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    # Give them a moment to exit, then force-kill stragglers
    import time
    time.sleep(0.5)

    for dpid in reversed(descendants):
        try:
            os.kill(dpid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _signal_handler(signum, frame):
    """Handle SIGTERM/SIGINT by killing children then exiting."""
    _kill_child_processes()
    # Re-raise with default handler so uvicorn can also do its cleanup
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def find_available_port(host: str = DEFAULT_HOST, start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + MAX_PORT_TRIES):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port found in range {start}-{start + MAX_PORT_TRIES}")


def get_project_name(target: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip()).name
    except subprocess.CalledProcessError:
        return target.name


def _is_git_repo(path: Path) -> bool:
    try:
        subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--git-dir"],
            capture_output=True, check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _discover_subrepos(parent: Path) -> list[str]:
    """Return sorted names of immediate subdirectories of `parent` that are git repos."""
    if not parent.is_dir():
        return []
    return sorted(
        p.name for p in parent.iterdir()
        if p.is_dir() and not p.name.startswith(".") and _is_git_repo(p)
    )


def main():
    parser = argparse.ArgumentParser(description="Agents Dashboard — scrum board for Claude agents")
    parser.add_argument("target", nargs="?", default=str(Path.cwd()),
                        help="Path to the target git project (default: current directory)")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"Host address to bind to (default: {DEFAULT_HOST}). "
                             "Use 0.0.0.0 to accept connections from any network interface.")
    parser.add_argument("--port", type=int, default=None,
                        help=f"Port to bind to (default: auto-detect starting from {DEFAULT_PORT})")
    parser.add_argument("--experimental", action="store_true", default=False,
                        help="Enable experimental features (e.g. Ollama provider, Sonnet + Advisor model)")
    parser.add_argument("--ui-map", action="store_true", default=False,
                        help="Enable PROJECT_MAP UI overlays (data-map-name discovery + spacing visualizer). "
                             "See AGENT_FILES/PROJECT_MAP.md.")
    args = parser.parse_args()

    target_project = Path(args.target).resolve()
    host = args.host

    # Detect mode:
    #   single — target is itself a git repo (original behavior)
    #   multi  — target is a folder containing ≥1 git subdirectory (repos live side-by-side)
    if _is_git_repo(target_project):
        repos: list[str] | None = None
    else:
        subrepos = _discover_subrepos(target_project)
        if not subrepos:
            print(
                f"Error: {target_project} is not a git repository and contains no git subdirectories"
            )
            sys.exit(1)
        repos = subrepos

    # Initialize agents-lab directory (lives at target_project root in both modes)
    data_dir = target_project / DATA_DIR_NAME
    data_dir.mkdir(exist_ok=True)
    (data_dir / "assets").mkdir(exist_ok=True)

    # Ensure agents-lab/ is in .gitignore of the target repo (single-mode only —
    # in multi mode the parent isn't a git repo, and each subrepo's git scope
    # doesn't include paths outside itself so nothing needs ignoring there).
    if repos is None:
        gitignore = target_project / ".gitignore"
        ignore_entry = DATA_DIR_NAME + "/"
        gitignore_changed = False
        if gitignore.exists():
            content = gitignore.read_text()
            if ignore_entry not in content.splitlines():
                with gitignore.open("a") as f:
                    if not content.endswith("\n"):
                        f.write("\n")
                    f.write(f"{ignore_entry}\n")
                gitignore_changed = True
        else:
            gitignore.write_text(f"{ignore_entry}\n")
            gitignore_changed = True

        if gitignore_changed:
            subprocess.run(
                ["git", "-C", str(target_project), "add", ".gitignore"],
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(target_project), "commit", "-m", "Add agents-lab/ to .gitignore"],
                capture_output=True,
            )

    if args.port is not None:
        port = args.port
    else:
        port = find_available_port(host)
    project_name = get_project_name(target_project)

    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"Agents Dashboard for: {project_name}")
    print(f"Target project: {target_project}")
    if repos:
        print(f"Multi-repo mode — {len(repos)} repo(s): {', '.join(repos)}")
    print(f"Data directory: {data_dir}")
    print(f"Starting on: http://{display_host}:{port}")
    if host == "0.0.0.0":
        print(f"⚠️  Accepting connections from all network interfaces")
    if args.experimental:
        print(f"🧪 Experimental features enabled")
    if args.ui_map:
        print(f"🗺  UI map overlays enabled (AGENT_FILES/PROJECT_MAP.md)")

    import logging
    import uvicorn
    from .web.app import create_app

    # Configure app logging to match uvicorn's INFO level
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s")

    # Suppress noisy polling endpoint from access logs
    class _QuietStatsFilter(logging.Filter):
        def filter(self, record):
            return "/api/stats" not in record.getMessage()

    logging.getLogger("uvicorn.access").addFilter(_QuietStatsFilter())

    # Register cleanup handlers to kill child processes (Claude agents) on exit.
    # This prevents orphaned processes when the macOS wrapper terminates the server.
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    atexit.register(_kill_child_processes)

    app = create_app(target_project, data_dir, experimental=args.experimental, repos=repos, ui_map=args.ui_map)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
