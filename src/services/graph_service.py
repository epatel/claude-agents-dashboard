"""Graph service — manages a graphify knowledge graph of the target project.

The dashboard is the *sole writer* of the graph. graphify writes its output to
`<scan-root>/graphify-out/` (it ignores cwd and has no redirect that keeps the
target clean), so the graph lives at `<target_project>/graphify-out/` and the
dir is added to the target repo's `.gitignore` (mirroring `agents-lab/`). Agents
never write the graph; they only read it (via a future `graph_query` MCP tool).

Builds shell out to the dashboard venv's graphify (`sys.executable -m graphify`):
- AST refresh (free, no LLM): `graphify update <root>` — initial and incremental.
- Semantic build (paid, opt-in): `graphify extract <root> [--backend gemini]`.

See AGENT_FILES/PLAN_graphify_capability_2026-06-06.md.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GRAPH_OUT_DIRNAME = "graphify-out"
PACKAGE_NAME = "graphifyy"

# Timeouts (seconds). AST build is seconds; semantic can run for minutes.
GRAPHIFY_BUILD_TIMEOUT = 1800
GRAPHIFY_QUERY_TIMEOUT = 120
GRAPHIFY_INSTALL_TIMEOUT = 600
PYPI_TIMEOUT = 5


class GraphService:
    """Build, refresh, query, and report on the target project's knowledge graph."""

    def __init__(
        self,
        target_project: Path,
        notification_service: Optional[Any] = None,
        repos: Optional[List[str]] = None,
    ):
        self.target_project = target_project
        self.notification_service = notification_service
        # None = single-repo (target IS the repo); list = multi-repo (parent dir).
        self.repos = repos
        self._lock = asyncio.Lock()
        self._latest_cache: Optional[str] = None
        # (graph.json mtime, parsed stats) — avoids re-parsing the JSON each call.
        self._stats_cache: Optional[tuple] = None

    # ---- paths -----------------------------------------------------------

    @property
    def graph_out(self) -> Path:
        return self.target_project / GRAPH_OUT_DIRNAME

    @property
    def graph_json(self) -> Path:
        return self.graph_out / "graph.json"

    @property
    def cost_json(self) -> Path:
        return self.graph_out / "cost.json"

    # ---- low-level subprocess -------------------------------------------

    async def _exec(
        self, argv: List[str], timeout: float, cwd: Optional[Path] = None
    ) -> tuple:
        """Run argv (no shell), return (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd or self.target_project),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            if proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            raise
        return (
            proc.returncode,
            out.decode(errors="replace"),
            err.decode(errors="replace"),
        )

    async def _graphify(self, *args: str, timeout: float) -> tuple:
        """Run `python -m graphify <args>` using the dashboard venv interpreter."""
        return await self._exec(
            [sys.executable, "-m", "graphify", *args], timeout=timeout
        )

    # ---- version info ----------------------------------------------------

    def installed_version(self) -> Optional[str]:
        try:
            from importlib.metadata import version

            return version(PACKAGE_NAME)
        except Exception:
            return None

    async def latest_version(self) -> Optional[str]:
        """Best-effort PyPI lookup of the latest graphifyy version (cached)."""
        if self._latest_cache is not None:
            return self._latest_cache

        def _fetch() -> str:
            import urllib.request

            url = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
            with urllib.request.urlopen(url, timeout=PYPI_TIMEOUT) as resp:
                return json.load(resp)["info"]["version"]

        try:
            self._latest_cache = await asyncio.to_thread(_fetch)
        except Exception as exc:
            logger.warning("graphify: PyPI version check failed: %s", exc)
        return self._latest_cache

    # ---- graph stats -----------------------------------------------------

    def _read_cost(self) -> Optional[Dict[str, Any]]:
        if not self.cost_json.exists():
            return None
        try:
            cost = json.loads(self.cost_json.read_text(encoding="utf-8"))
            return {
                "total_input_tokens": cost.get("total_input_tokens", 0),
                "total_output_tokens": cost.get("total_output_tokens", 0),
                "runs": len(cost.get("runs", [])),
            }
        except Exception:
            return None

    def _graph_stats(self) -> Dict[str, Any]:
        path = self.graph_json
        if not path.exists():
            return {"exists": False}
        mtime = path.stat().st_mtime
        if self._stats_cache and self._stats_cache[0] == mtime:
            return self._stats_cache[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            nodes = data.get("nodes", [])
            edges = data.get("links") or data.get("edges") or []
            communities = {
                n.get("community") for n in nodes if n.get("community") is not None
            }
            stats = {
                "exists": True,
                "nodes": len(nodes),
                "edges": len(edges),
                "communities": len(communities),
                "built_at_commit": data.get("built_at_commit"),
                "last_built": datetime.fromtimestamp(
                    mtime, tz=timezone.utc
                ).isoformat(),
                "cost": self._read_cost(),
            }
        except Exception as exc:
            logger.warning("graphify: failed to parse graph.json: %s", exc)
            stats = {"exists": True, "error": f"failed to parse graph.json: {exc}"}
        self._stats_cache = (mtime, stats)
        return stats

    async def status(self) -> Dict[str, Any]:
        return {
            "installed_version": self.installed_version(),
            "latest_version": await self.latest_version(),
            "building": self._lock.locked(),
            "graph": self._graph_stats(),
            "graph_dir": str(self.graph_out),
        }

    # ---- gitignore -------------------------------------------------------

    def _ensure_gitignore(self) -> None:
        """Keep graphify-out/ out of the target repo's history (single-repo only).

        In multi-repo mode the parent isn't a git repo, so nothing needs ignoring
        there — same reasoning as agents-lab/ in main.py.
        """
        if self.repos:
            return
        gitignore = self.target_project / ".gitignore"
        entry = GRAPH_OUT_DIRNAME + "/"
        try:
            content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
            if entry in content.splitlines():
                return
            with gitignore.open("a", encoding="utf-8") as f:
                if content and not content.endswith("\n"):
                    f.write("\n")
                f.write(entry + "\n")
            logger.info("graphify: added %s to %s", entry, gitignore)
        except Exception as exc:
            logger.warning("graphify: could not update .gitignore: %s", exc)

    # ---- builds ----------------------------------------------------------

    def _semantic_args(self) -> List[str]:
        if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            return ["--backend", "gemini"]
        return []

    async def _broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        if not self.notification_service:
            return
        try:
            await self.notification_service.broadcast_graph_event(event_type, data)
        except Exception:
            logger.exception("graphify: broadcast failed for %s", event_type)

    async def build(self, semantic: bool = False) -> Dict[str, Any]:
        """Build/rebuild the graph. AST `update` by default; semantic `extract` if asked.

        Serialized by a lock — a concurrent call is rejected rather than queued so
        two builds can't clobber graph.json.
        """
        if self._lock.locked():
            return {"ok": False, "status": "already_building"}
        async with self._lock:
            await self._broadcast(
                "graph_build_progress", {"phase": "started", "semantic": semantic}
            )
            self._ensure_gitignore()
            if semantic:
                args = ["extract", str(self.target_project), *self._semantic_args()]
            else:
                args = ["update", str(self.target_project)]
            try:
                rc, out, err = await self._graphify(
                    *args, timeout=GRAPHIFY_BUILD_TIMEOUT
                )
            except asyncio.TimeoutError:
                await self._broadcast(
                    "graph_ready", {"ok": False, "error": "build timed out"}
                )
                return {"ok": False, "error": "build timed out"}
            self._stats_cache = None  # force re-parse on next status
            stats = self._graph_stats()
            ok = rc == 0
            err_tail = err.strip()[-500:] if not ok else None
            if not ok:
                logger.warning("graphify build failed (rc=%s): %s", rc, err_tail)
            await self._broadcast(
                "graph_ready", {"ok": ok, "graph": stats, "error": err_tail}
            )
            return {"ok": ok, "graph": stats, "error": err_tail}

    async def refresh(self) -> Dict[str, Any]:
        """Incremental AST refresh — the merge-reactive call (free, never raises)."""
        try:
            return await self.build(semantic=False)
        except Exception:
            logger.exception("graphify: refresh failed")
            return {"ok": False, "error": "refresh failed"}

    async def install(self) -> Dict[str, Any]:
        """Upgrade graphifyy in the dashboard venv (privileged; gate in the UI)."""
        rc, out, err = await self._exec(
            [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE_NAME],
            timeout=GRAPHIFY_INSTALL_TIMEOUT,
        )
        ok = rc == 0
        return {
            "ok": ok,
            "version": self.installed_version(),
            "output": (out + err).strip()[-1000:],
        }

    # ---- reads (used by endpoints + future MCP tool) ---------------------

    async def _graph_command(self, *args: str) -> Dict[str, Any]:
        if not self.graph_json.exists():
            return {"ok": False, "error": "No graph built yet — build it first."}
        rc, out, err = await self._graphify(
            *args, "--graph", str(self.graph_json), timeout=GRAPHIFY_QUERY_TIMEOUT
        )
        return {
            "ok": rc == 0,
            "answer": out.strip(),
            "error": err.strip() if rc != 0 else None,
        }

    async def query(self, question: str) -> Dict[str, Any]:
        return await self._graph_command("query", question)

    async def path(self, a: str, b: str) -> Dict[str, Any]:
        return await self._graph_command("path", a, b)

    async def explain(self, node: str) -> Dict[str, Any]:
        return await self._graph_command("explain", node)
