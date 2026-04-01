import argparse
import sys
import socket
import subprocess
from pathlib import Path

from .config import DATA_DIR_NAME, DEFAULT_HOST, DEFAULT_PORT, MAX_PORT_TRIES


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


def main():
    parser = argparse.ArgumentParser(description="Agents Dashboard — scrum board for Claude agents")
    parser.add_argument("target", nargs="?", default=str(Path.cwd()),
                        help="Path to the target git project (default: current directory)")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"Host address to bind to (default: {DEFAULT_HOST}). "
                             "Use 0.0.0.0 to accept connections from any network interface.")
    parser.add_argument("--port", type=int, default=None,
                        help=f"Port to bind to (default: auto-detect starting from {DEFAULT_PORT})")
    args = parser.parse_args()

    target_project = Path(args.target).resolve()
    host = args.host

    # Verify it's a git repo
    try:
        subprocess.run(
            ["git", "-C", str(target_project), "rev-parse", "--git-dir"],
            capture_output=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"Error: {target_project} is not a git repository")
        sys.exit(1)

    # Initialize agents-lab directory
    data_dir = target_project / DATA_DIR_NAME
    data_dir.mkdir(exist_ok=True)
    (data_dir / "assets").mkdir(exist_ok=True)

    # Ensure agents-lab/ is in .gitignore
    gitignore = target_project / ".gitignore"
    ignore_entry = DATA_DIR_NAME + "/"
    if gitignore.exists():
        content = gitignore.read_text()
        if ignore_entry not in content.splitlines():
            with gitignore.open("a") as f:
                if not content.endswith("\n"):
                    f.write("\n")
                f.write(f"{ignore_entry}\n")
    else:
        gitignore.write_text(f"{ignore_entry}\n")

    if args.port is not None:
        port = args.port
    else:
        port = find_available_port(host)
    project_name = get_project_name(target_project)

    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print(f"Agents Dashboard for: {project_name}")
    print(f"Target project: {target_project}")
    print(f"Data directory: {data_dir}")
    print(f"Starting on: http://{display_host}:{port}")
    if host == "0.0.0.0":
        print(f"⚠️  Accepting connections from all network interfaces")

    import logging
    import uvicorn
    from .web.app import create_app

    # Suppress noisy polling endpoint from access logs
    class _QuietStatsFilter(logging.Filter):
        def filter(self, record):
            return "/api/stats" not in record.getMessage()

    logging.getLogger("uvicorn.access").addFilter(_QuietStatsFilter())

    app = create_app(target_project, data_dir)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
