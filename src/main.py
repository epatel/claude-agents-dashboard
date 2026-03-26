import sys
import socket
import subprocess
from pathlib import Path

from .config import DATA_DIR_NAME, DEFAULT_PORT, MAX_PORT_TRIES


def find_available_port(start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + MAX_PORT_TRIES):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
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
    if len(sys.argv) > 1:
        target_project = Path(sys.argv[1]).resolve()
    else:
        target_project = Path.cwd().resolve()

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

    port = find_available_port()
    project_name = get_project_name(target_project)

    print(f"Agents Dashboard for: {project_name}")
    print(f"Target project: {target_project}")
    print(f"Data directory: {data_dir}")
    print(f"Starting on: http://127.0.0.1:{port}")

    import logging
    import uvicorn
    from .web.app import create_app

    # Suppress noisy polling endpoint from access logs
    class _QuietStatsFilter(logging.Filter):
        def filter(self, record):
            return "/api/stats" not in record.getMessage()

    logging.getLogger("uvicorn.access").addFilter(_QuietStatsFilter())

    app = create_app(target_project, data_dir)
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
