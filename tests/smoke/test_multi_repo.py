"""Smoke tests for multi-repo workspace support."""

import asyncio
import subprocess

import pytest

from src.services.git_service import GitService
from src.agent.path_guard import make_path_guard_hook


def _init_git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
    )


@pytest.mark.smoke
class TestMultiRepoSchema:
    async def test_repo_column_exists_after_migration(self, test_db):
        """Migration 020 must add a `repo` column to items."""
        async with test_db.connect() as conn:
            cursor = await conn.execute("PRAGMA table_info(items)")
            cols = {row[1] for row in await cursor.fetchall()}
            assert "repo" in cols, f"expected 'repo' column in items; got {cols}"

    async def test_items_repo_nullable(self, test_db):
        """Existing single-repo inserts (repo=NULL) still work."""
        async with test_db.connect() as conn:
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position) "
                "VALUES ('x1', 't', '', 'todo', 0)"
            )
            await conn.commit()
            cursor = await conn.execute("SELECT repo FROM items WHERE id = 'x1'")
            (repo,) = await cursor.fetchone()
            assert repo is None


@pytest.mark.smoke
class TestGitServiceMulti:
    def test_single_mode_base_is_target(self, tmp_path):
        svc = GitService(target_project=tmp_path, worktree_dir=tmp_path / "wt")
        assert not svc.is_multi()
        assert svc.base_repo_path(None) == tmp_path
        # Worktree path preserves historical naming in single mode
        wp = svc.worktree_path_for("abc", "agent/abc", None)
        assert wp == tmp_path / "wt" / "agent-abc"

    def test_multi_mode_resolves_per_repo(self, tmp_path):
        (tmp_path / "repo_a").mkdir()
        (tmp_path / "repo_b").mkdir()
        svc = GitService(
            target_project=tmp_path,
            worktree_dir=tmp_path / "wt",
            repos=["repo_a", "repo_b"],
        )
        assert svc.is_multi()
        assert svc.base_repo_path("repo_a") == tmp_path / "repo_a"
        assert svc.base_repo_path("repo_b") == tmp_path / "repo_b"
        wp = svc.worktree_path_for("xyz", "agent/xyz", "repo_b")
        assert wp == tmp_path / "wt" / "repo_b-xyz"

    def test_multi_mode_rejects_unknown_or_missing_repo(self, tmp_path):
        svc = GitService(
            target_project=tmp_path,
            worktree_dir=tmp_path / "wt",
            repos=["repo_a"],
        )
        with pytest.raises(ValueError):
            svc.base_repo_path(None)
        with pytest.raises(ValueError):
            svc.base_repo_path("nope")


@pytest.mark.smoke
class TestPathGuardScope:
    """Path guard must let reads reach sibling repos in multi mode,
    but still block writes anywhere outside the worktree."""

    async def _call(self, hook, tool_name, tool_input):
        return await hook(
            {"tool_name": tool_name, "tool_input": tool_input},
            tool_use_id="t",
            context=None,
        )

    async def test_single_mode_blocks_read_outside_worktree(self, tmp_path):
        # Structure: {tmp_path}/proj/agents-lab/worktrees/agent-1
        worktree = tmp_path / "proj" / "agents-lab" / "worktrees" / "agent-1"
        worktree.mkdir(parents=True)
        hook = make_path_guard_hook(worktree)
        outside = tmp_path / "proj" / "src" / "main.py"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_text("x")

        result = await self._call(hook, "Read", {"file_path": str(outside)})
        decision = result.get("hookSpecificOutput", {}).get("permissionDecision")
        assert decision == "deny"

    async def test_multi_mode_allows_read_in_sibling(self, tmp_path):
        workspace = tmp_path / "workspace"
        # Worktree lives under workspace/agents-lab/worktrees/<id>
        worktree = workspace / "agents-lab" / "worktrees" / "repo_a-1"
        worktree.mkdir(parents=True)
        sibling = workspace / "repo_b" / "shared.py"
        sibling.parent.mkdir(parents=True)
        sibling.write_text("shared")

        hook = make_path_guard_hook(worktree, workspace_root=workspace)
        result = await self._call(hook, "Read", {"file_path": str(sibling)})
        # Allowed — no permissionDecision in output means the hook returned {}
        assert result == {} or result.get("hookSpecificOutput", {}).get(
            "permissionDecision"
        ) != "deny"

    async def test_multi_mode_still_blocks_write_in_sibling(self, tmp_path):
        workspace = tmp_path / "workspace"
        worktree = workspace / "agents-lab" / "worktrees" / "repo_a-1"
        worktree.mkdir(parents=True)
        sibling = workspace / "repo_b" / "shared.py"
        sibling.parent.mkdir(parents=True)

        hook = make_path_guard_hook(worktree, workspace_root=workspace)
        result = await self._call(
            hook, "Edit", {"file_path": str(sibling)}
        )
        decision = result.get("hookSpecificOutput", {}).get("permissionDecision")
        assert decision == "deny", (
            "Edit on a sibling repo must be denied even in multi-repo mode"
        )
