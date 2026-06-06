"""Unit tests for GraphService (graphify knowledge-graph wrapper)."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.graph_service import GraphService, GRAPH_OUT_DIRNAME


def _write_graph(proj: Path, nodes=3, edges=2, communities=2, commit="abc123"):
    """Create a minimal graphify-out/graph.json under proj."""
    out = proj / GRAPH_OUT_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    node_list = [
        {"id": f"n{i}", "community": i % communities} for i in range(nodes)
    ]
    link_list = [{"source": "n0", "target": f"n{i+1}"} for i in range(edges)]
    (out / "graph.json").write_text(
        json.dumps(
            {"nodes": node_list, "links": link_list, "built_at_commit": commit}
        ),
        encoding="utf-8",
    )
    return out


class _FakeProc:
    """Stand-in for an asyncio subprocess."""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr


# --- status / stats --------------------------------------------------------

class TestStatus:
    def test_installed_version_is_real(self, tmp_path):
        # graphifyy is installed in the test venv
        assert GraphService(tmp_path).installed_version() == \
            __import__("importlib.metadata", fromlist=["version"]).version("graphifyy")

    @pytest.mark.asyncio
    async def test_status_no_graph(self, tmp_path):
        gs = GraphService(tmp_path)
        with patch.object(gs, "latest_version", AsyncMock(return_value="9.9.9")):
            st = await gs.status()
        assert st["graph"] == {"exists": False}
        assert st["building"] is False
        assert st["latest_version"] == "9.9.9"
        assert st["graph_dir"].endswith(GRAPH_OUT_DIRNAME)

    @pytest.mark.asyncio
    async def test_status_with_graph_parses_stats(self, tmp_path):
        _write_graph(tmp_path, nodes=5, edges=4, communities=2, commit="deadbeef")
        gs = GraphService(tmp_path)
        with patch.object(gs, "latest_version", AsyncMock(return_value=None)):
            st = await gs.status()
        g = st["graph"]
        assert g["exists"] is True
        assert g["nodes"] == 5
        assert g["edges"] == 4
        assert g["communities"] == 2
        assert g["built_at_commit"] == "deadbeef"
        assert "last_built" in g

    def test_stats_cached_by_mtime(self, tmp_path):
        _write_graph(tmp_path)
        gs = GraphService(tmp_path)
        first = gs._graph_stats()
        # Second call returns the cached object (same identity) without re-parsing
        assert gs._graph_stats() is first


# --- shell safety ----------------------------------------------------------

class TestShellSafety:
    @pytest.mark.asyncio
    async def test_uses_exec_with_argv_no_shell(self, tmp_path):
        gs = GraphService(tmp_path)
        captured = {}

        async def fake_exec(*argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return _FakeProc(0, b"out", b"")

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            rc, out, err = await gs._graphify("update", str(tmp_path), timeout=5)

        assert rc == 0 and out == "out"
        # argv is a real list passed positionally; no shell=True anywhere
        assert captured["argv"][0] == sys.executable
        assert captured["argv"][1:4] == ("-m", "graphify", "update")
        assert "shell" not in captured["kwargs"]


# --- build / refresh -------------------------------------------------------

class TestBuild:
    @pytest.mark.asyncio
    async def test_build_ast_runs_update_and_broadcasts(self, tmp_path):
        ns = MagicMock()
        ns.broadcast_graph_event = AsyncMock()
        gs = GraphService(tmp_path, notification_service=ns)

        async def fake_graphify(*args, timeout):
            # simulate graphify writing the graph
            _write_graph(tmp_path)
            return 0, "ok", ""

        with patch.object(gs, "_graphify", side_effect=fake_graphify) as mock_g:
            result = await gs.build(semantic=False)

        assert result["ok"] is True
        args = mock_g.call_args.args
        assert args[0] == "update"  # AST path, not extract
        # gitignore written
        assert "graphify-out/" in (tmp_path / ".gitignore").read_text().splitlines()
        # broadcast start + ready
        events = [c.args[0] for c in ns.broadcast_graph_event.call_args_list]
        assert events == ["graph_build_progress", "graph_ready"]

    @pytest.mark.asyncio
    async def test_build_semantic_runs_extract(self, tmp_path):
        gs = GraphService(tmp_path)
        with patch.dict("os.environ", {"GEMINI_API_KEY": "x"}, clear=False), \
             patch.object(gs, "_graphify", AsyncMock(return_value=(0, "", ""))) as mock_g:
            await gs.build(semantic=True)
        args = mock_g.call_args.args
        assert args[0] == "extract"
        assert "--backend" in args and "gemini" in args

    @pytest.mark.asyncio
    async def test_concurrent_build_rejected(self, tmp_path):
        gs = GraphService(tmp_path)
        await gs._lock.acquire()
        try:
            result = await gs.build()
        finally:
            gs._lock.release()
        assert result == {"ok": False, "status": "already_building"}

    @pytest.mark.asyncio
    async def test_refresh_never_raises(self, tmp_path):
        gs = GraphService(tmp_path)
        with patch.object(gs, "build", AsyncMock(side_effect=RuntimeError("boom"))):
            result = await gs.refresh()
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_gitignore_skipped_in_multi_repo(self, tmp_path):
        gs = GraphService(tmp_path, repos=["a", "b"])
        gs._ensure_gitignore()
        assert not (tmp_path / ".gitignore").exists()


# --- reads -----------------------------------------------------------------

class TestQuery:
    @pytest.mark.asyncio
    async def test_query_without_graph(self, tmp_path):
        gs = GraphService(tmp_path)
        result = await gs.query("anything")
        assert result["ok"] is False
        assert "build" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_query_passes_graph_path(self, tmp_path):
        _write_graph(tmp_path)
        gs = GraphService(tmp_path)
        with patch.object(gs, "_graphify", AsyncMock(return_value=(0, "answer", ""))) as mock_g:
            result = await gs.query("how does X work")
        assert result == {"ok": True, "answer": "answer", "error": None}
        args = mock_g.call_args.args
        assert args[0] == "query" and args[1] == "how does X work"
        assert "--graph" in args
