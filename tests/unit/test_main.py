"""Unit tests for src/main.py — server startup, port finding, arg parsing."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.main import find_available_port, get_project_name, main
from src.config import DEFAULT_HOST, DEFAULT_PORT, MAX_PORT_TRIES

# uvicorn and create_app are imported *inside* main(), so patch at their
# canonical module locations, not on src.main.
_UVICORN_RUN = "uvicorn.run"
_CREATE_APP  = "src.web.app.create_app"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_main(tmp_path, extra_args=None, project_name="test-proj", port=8000):
    """Run main() with all external side-effects mocked out."""
    argv = ["main.py", str(tmp_path)] + (extra_args or [])
    with patch.object(sys, "argv", argv):
        with patch("src.main.subprocess.run") as mock_subprocess:
            mock_subprocess.return_value = MagicMock(returncode=0, stdout=str(tmp_path))
            with patch("src.main.find_available_port", return_value=port):
                with patch("src.main.get_project_name", return_value=project_name):
                    with patch(_UVICORN_RUN) as mock_uvicorn_run:
                        fake_app = MagicMock()
                        with patch(_CREATE_APP, return_value=fake_app) as mock_create_app:
                            main()
                            return mock_uvicorn_run, fake_app, mock_create_app, mock_subprocess


# ---------------------------------------------------------------------------
# find_available_port
# ---------------------------------------------------------------------------

class TestFindAvailablePort:
    def test_returns_start_port_when_free(self):
        with patch("src.main.socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.bind.return_value = None

            port = find_available_port(DEFAULT_HOST, DEFAULT_PORT)

        assert port == DEFAULT_PORT

    def test_skips_busy_port_returns_next(self):
        with patch("src.main.socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.bind.side_effect = [OSError("in use"), None]

            port = find_available_port(DEFAULT_HOST, DEFAULT_PORT)

        assert port == DEFAULT_PORT + 1

    def test_skips_multiple_busy_ports(self):
        n = 5
        with patch("src.main.socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.bind.side_effect = [OSError()] * (n - 1) + [None]

            port = find_available_port(DEFAULT_HOST, DEFAULT_PORT)

        assert port == DEFAULT_PORT + n - 1

    def test_raises_when_all_ports_busy(self):
        with patch("src.main.socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.bind.side_effect = OSError("busy")

            with pytest.raises(RuntimeError, match="No available port"):
                find_available_port(DEFAULT_HOST, DEFAULT_PORT)

    def test_raises_message_includes_port_range(self):
        with patch("src.main.socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.bind.side_effect = OSError("busy")

            with pytest.raises(RuntimeError) as exc_info:
                find_available_port(DEFAULT_HOST, DEFAULT_PORT)

        msg = str(exc_info.value)
        assert str(DEFAULT_PORT) in msg
        assert str(DEFAULT_PORT + MAX_PORT_TRIES) in msg

    def test_uses_custom_host_and_start_port(self):
        with patch("src.main.socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.bind.return_value = None

            port = find_available_port("0.0.0.0", 9000)

        assert port == 9000
        mock_sock.bind.assert_called_once_with(("0.0.0.0", 9000))

    def test_tries_exactly_max_port_tries_times(self):
        with patch("src.main.socket.socket") as mock_socket_cls:
            mock_sock = MagicMock()
            mock_socket_cls.return_value.__enter__ = MagicMock(return_value=mock_sock)
            mock_socket_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.bind.side_effect = OSError("busy")

            with pytest.raises(RuntimeError):
                find_available_port(DEFAULT_HOST, DEFAULT_PORT)

        assert mock_sock.bind.call_count == MAX_PORT_TRIES


# ---------------------------------------------------------------------------
# get_project_name
# ---------------------------------------------------------------------------

class TestGetProjectName:
    def test_returns_git_toplevel_basename(self, tmp_path):
        fake_toplevel = str(tmp_path / "my-project")
        with patch("src.main.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=fake_toplevel + "\n")
            name = get_project_name(tmp_path)
        assert name == "my-project"

    def test_falls_back_to_dir_name_on_git_error(self, tmp_path):
        project_dir = tmp_path / "fallback-project"
        project_dir.mkdir()
        with patch("src.main.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(128, "git")
            name = get_project_name(project_dir)
        assert name == "fallback-project"

    def test_strips_trailing_newline_from_git_output(self, tmp_path):
        fake_toplevel = str(tmp_path / "clean-name")
        with patch("src.main.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=fake_toplevel + "\n\n")
            name = get_project_name(tmp_path)
        assert name == "clean-name"


# ---------------------------------------------------------------------------
# main() — argument parsing
# ---------------------------------------------------------------------------

class TestMainArgParsing:
    def test_default_target_is_cwd(self, tmp_path):
        # No target arg — should use cwd without crashing
        with patch.object(sys, "argv", ["main.py"]):
            with patch("src.main.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=str(tmp_path))
                with patch("src.main.find_available_port", return_value=8000):
                    with patch("src.main.get_project_name", return_value="proj"):
                        with patch(_UVICORN_RUN):
                            with patch(_CREATE_APP, return_value=MagicMock()):
                                main()  # should not raise

    def test_explicit_target_path(self, tmp_path):
        target = tmp_path / "my-repo"
        target.mkdir()
        with patch.object(sys, "argv", ["main.py", str(target)]):
            with patch("src.main.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=str(target))
                with patch("src.main.find_available_port", return_value=8000):
                    with patch("src.main.get_project_name", return_value="my-repo"):
                        with patch(_UVICORN_RUN):
                            with patch(_CREATE_APP, return_value=MagicMock()):
                                main()

    def test_custom_port_skips_find_available(self, tmp_path):
        with patch.object(sys, "argv", ["main.py", str(tmp_path), "--port", "9999"]):
            with patch("src.main.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=str(tmp_path))
                with patch("src.main.find_available_port") as mock_find:
                    with patch("src.main.get_project_name", return_value="proj"):
                        with patch(_UVICORN_RUN) as mock_uvicorn_run:
                            with patch(_CREATE_APP, return_value=MagicMock()):
                                main()
            mock_find.assert_not_called()
            mock_uvicorn_run.assert_called_once()
            _, kwargs = mock_uvicorn_run.call_args
            assert kwargs["port"] == 9999

    def test_custom_host_passed_to_uvicorn(self, tmp_path):
        with patch.object(sys, "argv", ["main.py", str(tmp_path), "--host", "0.0.0.0", "--port", "8080"]):
            with patch("src.main.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=str(tmp_path))
                with patch("src.main.get_project_name", return_value="proj"):
                    with patch(_UVICORN_RUN) as mock_uvicorn_run:
                        with patch(_CREATE_APP, return_value=MagicMock()):
                            main()
            mock_uvicorn_run.assert_called_once()
            _, kwargs = mock_uvicorn_run.call_args
            assert kwargs["host"] == "0.0.0.0"


# ---------------------------------------------------------------------------
# main() — git repo validation
# ---------------------------------------------------------------------------

class TestMainGitValidation:
    def test_exits_1_when_not_a_git_repo(self, tmp_path):
        with patch.object(sys, "argv", ["main.py", str(tmp_path)]):
            with patch("src.main.subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.CalledProcessError(128, "git")
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 1

    def test_exits_1_when_git_not_found(self, tmp_path):
        with patch.object(sys, "argv", ["main.py", str(tmp_path)]):
            with patch("src.main.subprocess.run") as mock_run:
                mock_run.side_effect = FileNotFoundError("git not found")
                with pytest.raises(SystemExit) as exc_info:
                    main()
        assert exc_info.value.code == 1

    def test_prints_error_message_on_non_git_dir(self, tmp_path, capsys):
        with patch.object(sys, "argv", ["main.py", str(tmp_path)]):
            with patch("src.main.subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.CalledProcessError(128, "git")
                with pytest.raises(SystemExit):
                    main()
        out = capsys.readouterr().out
        assert "not a git repository" in out.lower() or "Error" in out


# ---------------------------------------------------------------------------
# main() — data directory creation
# ---------------------------------------------------------------------------

class TestMainDataDirCreation:
    def test_creates_agents_lab_directory(self, tmp_path):
        _run_main(tmp_path)
        assert (tmp_path / "agents-lab").is_dir()

    def test_creates_assets_subdirectory(self, tmp_path):
        _run_main(tmp_path)
        assert (tmp_path / "agents-lab" / "assets").is_dir()

    def test_data_dir_idempotent_when_already_exists(self, tmp_path):
        # Pre-create the dirs — should not raise
        (tmp_path / "agents-lab" / "assets").mkdir(parents=True)
        _run_main(tmp_path)
        assert (tmp_path / "agents-lab" / "assets").is_dir()


# ---------------------------------------------------------------------------
# main() — .gitignore management
# ---------------------------------------------------------------------------

class TestMainGitignore:
    def test_creates_gitignore_when_absent(self, tmp_path):
        _run_main(tmp_path)
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert "agents-lab/" in gitignore.read_text()

    def test_appends_entry_to_existing_gitignore_missing_entry(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/\n")
        _run_main(tmp_path)
        content = gitignore.read_text()
        assert "agents-lab/" in content
        assert "node_modules/" in content

    def test_does_not_duplicate_entry_in_gitignore(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("agents-lab/\n")
        _run_main(tmp_path)
        content = gitignore.read_text()
        assert content.count("agents-lab/") == 1

    def test_adds_newline_before_entry_when_file_lacks_trailing_newline(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/")  # no trailing newline
        _run_main(tmp_path)
        content = gitignore.read_text()
        assert "\nagents-lab/" in content


# ---------------------------------------------------------------------------
# main() — uvicorn.run call
# ---------------------------------------------------------------------------

class TestMainUvicornCall:
    def test_uvicorn_run_called_once(self, tmp_path):
        mock_uvicorn_run, _, _, _ = _run_main(tmp_path)
        mock_uvicorn_run.assert_called_once()

    def test_uvicorn_run_receives_app(self, tmp_path):
        mock_uvicorn_run, fake_app, _, _ = _run_main(tmp_path)
        args, _ = mock_uvicorn_run.call_args
        assert args[0] is fake_app

    def test_uvicorn_run_default_host(self, tmp_path):
        mock_uvicorn_run, _, _, _ = _run_main(tmp_path)
        _, kwargs = mock_uvicorn_run.call_args
        assert kwargs["host"] == DEFAULT_HOST

    def test_uvicorn_run_uses_detected_port(self, tmp_path):
        mock_uvicorn_run, _, _, _ = _run_main(tmp_path, port=8000)
        _, kwargs = mock_uvicorn_run.call_args
        assert kwargs["port"] == 8000

    def test_create_app_called_with_target_and_data_dir(self, tmp_path):
        _, _, mock_create_app, _ = _run_main(tmp_path)
        mock_create_app.assert_called_once()
        call_args = mock_create_app.call_args[0]
        assert call_args[0] == tmp_path.resolve()
        assert call_args[1] == tmp_path.resolve() / "agents-lab"


# ---------------------------------------------------------------------------
# main() — print output
# ---------------------------------------------------------------------------

class TestMainOutput:
    def test_prints_project_name(self, tmp_path, capsys):
        _run_main(tmp_path, project_name="my-cool-project")
        assert "my-cool-project" in capsys.readouterr().out

    def test_prints_target_project_path(self, tmp_path, capsys):
        _run_main(tmp_path)
        assert str(tmp_path.resolve()) in capsys.readouterr().out

    def test_prints_starting_on_url_with_port(self, tmp_path, capsys):
        _run_main(tmp_path, port=8000)
        assert "8000" in capsys.readouterr().out

    def test_0_0_0_0_host_prints_warning(self, tmp_path, capsys):
        _run_main(tmp_path, extra_args=["--host", "0.0.0.0", "--port", "8000"])
        out = capsys.readouterr().out
        assert "0.0.0.0" in out or "all network" in out.lower()

    def test_0_0_0_0_host_displays_as_127_0_0_1_in_url(self, tmp_path, capsys):
        _run_main(tmp_path, extra_args=["--host", "0.0.0.0", "--port", "8000"])
        assert "127.0.0.1" in capsys.readouterr().out
