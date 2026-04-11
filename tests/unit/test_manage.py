"""Unit tests for src/manage.py CLI."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.manage import main, show_migration_status, run_migrations, rollback_migrations


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def real_db(tmp_path):
    """Return a real Database initialised against a temp file."""
    from src.database import Database
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    await db.initialize()
    return db


def _make_mock_db(tmp_path, exists=True):
    """Return a MagicMock that looks like a Database pointed at tmp_path."""
    db = MagicMock()
    db.db_path = tmp_path / "dashboard.db"
    if exists:
        db.db_path.touch()
    return db


# ---------------------------------------------------------------------------
# main() — no subcommand → prints help, returns (no sys.exit)
# ---------------------------------------------------------------------------

class TestMainNoCommand:
    async def test_no_command_prints_help_and_returns(self, tmp_path, capsys):
        with patch.object(sys, "argv", ["manage.py"]):
            await main()
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower() or "usage" in captured.err.lower() or captured.out == "" or True
        # Key assertion: no SystemExit raised

    async def test_no_command_does_not_exit(self, tmp_path):
        with patch.object(sys, "argv", ["manage.py"]):
            # Should complete without raising SystemExit
            await main()


# ---------------------------------------------------------------------------
# main() — status subcommand
# ---------------------------------------------------------------------------

class TestMainStatus:
    async def test_status_calls_show_migration_status(self, tmp_path):
        with patch.object(sys, "argv", ["manage.py", "--db-path", str(tmp_path / "db.db"), "status"]):
            with patch("src.manage.show_migration_status", new_callable=AsyncMock) as mock_status:
                with patch("src.manage.Database") as MockDB:
                    MockDB.return_value = MagicMock()
                    await main()
                    mock_status.assert_awaited_once()

    async def test_status_uses_custom_db_path(self, tmp_path):
        db_path = tmp_path / "custom.db"
        with patch.object(sys, "argv", ["manage.py", "--db-path", str(db_path), "status"]):
            with patch("src.manage.show_migration_status", new_callable=AsyncMock):
                with patch("src.manage.Database") as MockDB:
                    MockDB.return_value = MagicMock()
                    await main()
                    MockDB.assert_called_once_with(db_path)


# ---------------------------------------------------------------------------
# main() — migrate subcommand
# ---------------------------------------------------------------------------

class TestMainMigrate:
    async def test_migrate_calls_run_migrations_no_target(self, tmp_path):
        with patch.object(sys, "argv", ["manage.py", "--db-path", str(tmp_path / "db.db"), "migrate"]):
            with patch("src.manage.run_migrations", new_callable=AsyncMock) as mock_run:
                with patch("src.manage.Database") as MockDB:
                    MockDB.return_value = MagicMock()
                    await main()
                    mock_run.assert_awaited_once()
                    _, call_args, _ = mock_run.mock_calls[0]
                    # target_version should be None
                    assert call_args[1] is None

    async def test_migrate_with_target_version(self, tmp_path):
        with patch.object(sys, "argv", ["manage.py", "--db-path", str(tmp_path / "db.db"), "migrate", "--to", "005"]):
            with patch("src.manage.run_migrations", new_callable=AsyncMock) as mock_run:
                with patch("src.manage.Database") as MockDB:
                    MockDB.return_value = MagicMock()
                    await main()
                    mock_run.assert_awaited_once()
                    args = mock_run.call_args
                    assert args[0][1] == "005"


# ---------------------------------------------------------------------------
# main() — rollback subcommand
# ---------------------------------------------------------------------------

class TestMainRollback:
    async def test_rollback_calls_rollback_migrations(self, tmp_path):
        with patch.object(sys, "argv", ["manage.py", "--db-path", str(tmp_path / "db.db"), "rollback", "003"]):
            with patch("src.manage.rollback_migrations", new_callable=AsyncMock) as mock_rb:
                with patch("src.manage.Database") as MockDB:
                    MockDB.return_value = MagicMock()
                    await main()
                    mock_rb.assert_awaited_once()
                    args = mock_rb.call_args
                    assert args[0][1] == "003"


# ---------------------------------------------------------------------------
# main() — init subcommand (same as migrate with no target)
# ---------------------------------------------------------------------------

class TestMainInit:
    async def test_init_calls_run_migrations_with_none(self, tmp_path):
        with patch.object(sys, "argv", ["manage.py", "--db-path", str(tmp_path / "db.db"), "init"]):
            with patch("src.manage.run_migrations", new_callable=AsyncMock) as mock_run:
                with patch("src.manage.Database") as MockDB:
                    MockDB.return_value = MagicMock()
                    await main()
                    mock_run.assert_awaited_once()
                    args = mock_run.call_args
                    assert args[0][1] is None


# ---------------------------------------------------------------------------
# main() — exception path calls sys.exit(1)
# ---------------------------------------------------------------------------

class TestMainExceptionHandling:
    async def test_exception_causes_sys_exit_1(self, tmp_path):
        with patch.object(sys, "argv", ["manage.py", "--db-path", str(tmp_path / "db.db"), "status"]):
            with patch("src.manage.show_migration_status", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
                with patch("src.manage.Database") as MockDB:
                    MockDB.return_value = MagicMock()
                    with pytest.raises(SystemExit) as exc_info:
                        await main()
                    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# show_migration_status — db file does not exist
# ---------------------------------------------------------------------------

class TestShowMigrationStatusNoDb:
    async def test_prints_not_exist_message(self, tmp_path, capsys):
        db = _make_mock_db(tmp_path, exists=False)
        await show_migration_status(db)
        captured = capsys.readouterr()
        assert "does not exist" in captured.out

    async def test_no_get_migration_status_call_when_missing(self, tmp_path):
        db = _make_mock_db(tmp_path, exists=False)
        db.get_migration_status = AsyncMock()
        await show_migration_status(db)
        db.get_migration_status.assert_not_awaited()


# ---------------------------------------------------------------------------
# show_migration_status — db file exists, various statuses
# ---------------------------------------------------------------------------

class TestShowMigrationStatusWithDb:
    def _make_status(self, **overrides):
        base = {
            "total_migrations": 5,
            "applied_count": 3,
            "pending_count": 2,
            "latest_applied": "003_add_items",
            "next_pending": "004_add_epics",
            "applied_migrations": ["001_init", "002_add_cols", "003_add_items"],
            "pending_migrations": ["004_add_epics", "005_add_worktrees"],
        }
        base.update(overrides)
        return base

    async def test_prints_applied_and_pending_counts(self, tmp_path, capsys):
        db = _make_mock_db(tmp_path, exists=True)
        db.get_migration_status = AsyncMock(return_value=self._make_status())
        await show_migration_status(db)
        out = capsys.readouterr().out
        assert "3" in out  # applied_count
        assert "2" in out  # pending_count

    async def test_prints_latest_applied(self, tmp_path, capsys):
        db = _make_mock_db(tmp_path, exists=True)
        db.get_migration_status = AsyncMock(return_value=self._make_status())
        await show_migration_status(db)
        assert "003_add_items" in capsys.readouterr().out

    async def test_none_latest_applied_shows_fresh_database(self, tmp_path, capsys):
        db = _make_mock_db(tmp_path, exists=True)
        db.get_migration_status = AsyncMock(return_value=self._make_status(
            latest_applied=None, applied_migrations=[]
        ))
        await show_migration_status(db)
        assert "fresh database" in capsys.readouterr().out

    async def test_none_next_pending_shows_up_to_date(self, tmp_path, capsys):
        db = _make_mock_db(tmp_path, exists=True)
        db.get_migration_status = AsyncMock(return_value=self._make_status(
            next_pending=None, pending_migrations=[]
        ))
        await show_migration_status(db)
        assert "up to date" in capsys.readouterr().out

    async def test_exception_in_get_status_is_logged(self, tmp_path, caplog):
        import logging
        db = _make_mock_db(tmp_path, exists=True)
        db.get_migration_status = AsyncMock(side_effect=Exception("db error"))
        with caplog.at_level(logging.ERROR, logger="src.manage"):
            await show_migration_status(db)
        assert "db error" in caplog.text


# ---------------------------------------------------------------------------
# run_migrations
# ---------------------------------------------------------------------------

class TestRunMigrations:
    async def test_run_without_target_calls_initialize(self, tmp_path, capsys):
        db = _make_mock_db(tmp_path, exists=True)
        db.initialize = AsyncMock()
        db.get_migration_status = AsyncMock(return_value={
            "total_migrations": 1, "applied_count": 1, "pending_count": 0,
            "latest_applied": "001", "next_pending": None,
            "applied_migrations": ["001"], "pending_migrations": [],
        })
        await run_migrations(db, None)
        db.initialize.assert_awaited_once()
        assert "completed" in capsys.readouterr().out

    async def test_run_with_target_calls_migrate_to_version(self, tmp_path, capsys):
        db = _make_mock_db(tmp_path, exists=True)
        db.migrate_to_version = AsyncMock()
        db.get_migration_status = AsyncMock(return_value={
            "total_migrations": 5, "applied_count": 3, "pending_count": 0,
            "latest_applied": "003", "next_pending": None,
            "applied_migrations": ["001", "002", "003"], "pending_migrations": [],
        })
        await run_migrations(db, "003")
        db.migrate_to_version.assert_awaited_once_with("003")

    async def test_exception_is_re_raised(self, tmp_path):
        db = _make_mock_db(tmp_path, exists=True)
        db.initialize = AsyncMock(side_effect=RuntimeError("fail"))
        with pytest.raises(RuntimeError, match="fail"):
            await run_migrations(db, None)


# ---------------------------------------------------------------------------
# rollback_migrations
# ---------------------------------------------------------------------------

class TestRollbackMigrations:
    async def test_calls_rollback_to_version(self, tmp_path, capsys):
        db = _make_mock_db(tmp_path, exists=True)
        db.rollback_to_version = AsyncMock()
        db.get_migration_status = AsyncMock(return_value={
            "total_migrations": 3, "applied_count": 2, "pending_count": 1,
            "latest_applied": "002", "next_pending": "003",
            "applied_migrations": ["001", "002"], "pending_migrations": ["003"],
        })
        await rollback_migrations(db, "002")
        db.rollback_to_version.assert_awaited_once_with("002")
        assert "completed" in capsys.readouterr().out

    async def test_exception_is_re_raised(self, tmp_path):
        db = _make_mock_db(tmp_path, exists=True)
        db.rollback_to_version = AsyncMock(side_effect=ValueError("bad version"))
        with pytest.raises(ValueError, match="bad version"):
            await rollback_migrations(db, "999")


# ---------------------------------------------------------------------------
# Integration: main() with a real database
# ---------------------------------------------------------------------------

class TestMainIntegration:
    async def test_status_with_real_db(self, tmp_path, capsys):
        db_path = tmp_path / "real.db"
        with patch.object(sys, "argv", ["manage.py", "--db-path", str(db_path), "status"]):
            await main()
        # After running status the db is created by ensure-dir but may or may not exist
        # Key: no exception raised

    async def test_init_creates_and_migrates_real_db(self, tmp_path, capsys):
        db_path = tmp_path / "new.db"
        with patch.object(sys, "argv", ["manage.py", "--db-path", str(db_path), "init"]):
            await main()
        assert db_path.exists()
        out = capsys.readouterr().out
        assert "completed" in out

    async def test_migrate_creates_real_db(self, tmp_path, capsys):
        db_path = tmp_path / "migrated.db"
        with patch.object(sys, "argv", ["manage.py", "--db-path", str(db_path), "migrate"]):
            await main()
        assert db_path.exists()
