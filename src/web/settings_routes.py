"""Settings: agent config, the graphify knowledge graph, and the skills library."""

import asyncio
import json
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from ..models import AgentConfig

settings_router = APIRouter()


# --- Agent config ---

@settings_router.get("/api/config")
async def get_config(request: Request):
    # Phase 3: parse JSON-text fields here (matches db.get_agent_config) so
    # the API returns Python types. Builds a thin DatabaseService rather
    # than going through the orchestrator, so tests with a real db_state +
    # mocked orchestrator still work.
    from ..services.database_service import DatabaseService
    return await DatabaseService(request.app.state.db).get_agent_config()


@settings_router.put("/api/config")
async def update_config(request: Request, body: AgentConfig):
    """Persist agent config. The five list/dict fields on AgentConfig are
    typed Python collections (Phase 3); SQLite stores them as JSON text."""
    from ..services.database_service import DatabaseService
    db = request.app.state.db
    async with db.connect() as conn:
        await conn.execute(
            "UPDATE agent_config SET system_prompt = ?, tools = ?, model = ?, project_context = ?, mcp_servers = ?, mcp_enabled = ?, plugins = ?, allowed_commands = ?, bash_yolo = ?, allowed_builtin_tools = ?, flame_enabled = ?, flame_intensity_multiplier = ?, ollama_enabled = ?, ollama_base_url = ?, ollama_load_claude_md = ?, tiiny_enabled = ?, tiiny_base_url = ?, tiiny_load_claude_md = ?, wip_limit = ?, graphify_enabled = ?, graphify_auto_refresh = ?, graphify_backend = ?, updated_at = datetime('now') WHERE id = 1",
            (
                body.system_prompt,
                json.dumps(body.tools),
                body.model,
                body.project_context,
                json.dumps(body.mcp_servers),
                body.mcp_enabled,
                json.dumps(body.plugins),
                json.dumps(body.allowed_commands),
                body.bash_yolo,
                json.dumps(body.allowed_builtin_tools),
                body.flame_enabled,
                body.flame_intensity_multiplier,
                body.ollama_enabled,
                body.ollama_base_url,
                body.ollama_load_claude_md,
                body.tiiny_enabled,
                body.tiiny_base_url,
                body.tiiny_load_claude_md,
                body.wip_limit,
                body.graphify_enabled,
                body.graphify_auto_refresh,
                body.graphify_backend,
            ),
            # NOTE: enabled_skills is intentionally NOT written here — it is owned
            # by the /api/skills/{name}/enabled endpoints so saving Settings can't
            # wipe a project's enabled skill set.
        )
        await conn.commit()
    return await DatabaseService(db).get_agent_config()


@settings_router.get("/api/config/available-tools")
async def get_available_tools():
    from ..constants import OPTIONAL_BUILTIN_TOOLS
    return OPTIONAL_BUILTIN_TOOLS


# --- Graphify knowledge graph ---------------------------------------------

class GraphBuildRequest(BaseModel):
    semantic: bool = False


@settings_router.get("/api/graphify/status")
async def graphify_status(request: Request):
    """Installed/latest version, whether a build is running, and graph stats."""
    return await request.app.state.orchestrator.graph_service.status()


@settings_router.post("/api/graphify/build")
async def graphify_build(request: Request, body: GraphBuildRequest = GraphBuildRequest()):
    """Kick off a (re)build in the background; progress streams over WebSocket.

    AST `update` by default (free); set semantic=true for LLM extraction.
    """
    graph_service = request.app.state.orchestrator.graph_service
    if graph_service._lock.locked():
        return {"started": False, "status": "already_building"}
    asyncio.create_task(graph_service.build(semantic=body.semantic))
    return {"started": True, "semantic": body.semantic}


@settings_router.post("/api/graphify/install")
async def graphify_install(request: Request):
    """Upgrade graphifyy in the dashboard venv (privileged — confirm in the UI)."""
    return await request.app.state.orchestrator.graph_service.install()


@settings_router.get("/api/graphify/query")
async def graphify_query(request: Request, q: str):
    """BFS traversal of the graph for a natural-language question (read-only)."""
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="query 'q' is required")
    return await request.app.state.orchestrator.graph_service.query(q.strip())


# --- Skills library --------------------------------------------------------

class SkillInstallRequest(BaseModel):
    spec: str


class SkillEnabledRequest(BaseModel):
    enabled: bool


async def _enabled_skills(db) -> list:
    from ..services.database_service import DatabaseService
    cfg = await DatabaseService(db).get_agent_config()
    return list(cfg.get("enabled_skills") or [])


async def _write_enabled_skills(db, enabled: list) -> None:
    async with db.connect() as conn:
        await conn.execute(
            "UPDATE agent_config SET enabled_skills = ?, updated_at = datetime('now') WHERE id = 1",
            (json.dumps(enabled),),
        )
        await conn.commit()


@settings_router.get("/api/skills")
async def skills_list(request: Request):
    """Installed library skills with per-project enabled flags."""
    enabled = await _enabled_skills(request.app.state.db)
    skills = request.app.state.orchestrator.skills_service.list_installed(enabled)
    return {"installed": skills}


@settings_router.get("/api/skills/browse")
async def skills_browse(request: Request, source: str = "anthropic"):
    """List installable skills from a public source (cached)."""
    try:
        skills = await request.app.state.orchestrator.skills_service.browse(source)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"browse failed: {exc}")
    return {"skills": skills}


@settings_router.post("/api/skills/discover")
async def skills_discover(request: Request, body: SkillInstallRequest):
    """Find every skill (folder with a SKILL.md) in a repo/path."""
    if not body.spec or not body.spec.strip():
        raise HTTPException(status_code=400, detail="spec is required")
    try:
        skills = await request.app.state.orchestrator.skills_service.discover(body.spec.strip())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"discover failed: {exc}")
    return {"skills": skills}


@settings_router.post("/api/skills/install")
async def skills_install(request: Request, body: SkillInstallRequest):
    if not body.spec or not body.spec.strip():
        raise HTTPException(status_code=400, detail="spec is required")
    res = await request.app.state.orchestrator.skills_service.install(body.spec.strip())
    # Auto-enable the freshly installed skill for this project.
    if res.get("ok") and res.get("name"):
        db = request.app.state.db
        enabled = await _enabled_skills(db)
        if res["name"] not in enabled:
            enabled.append(res["name"])
            await _write_enabled_skills(db, enabled)
        res["enabled"] = True
    return res


@settings_router.post("/api/skills/{name}/enabled")
async def skills_set_enabled(request: Request, name: str, body: SkillEnabledRequest):
    db = request.app.state.db
    enabled = await _enabled_skills(db)
    if body.enabled and name not in enabled:
        enabled.append(name)
    elif not body.enabled:
        enabled = [n for n in enabled if n != name]
    await _write_enabled_skills(db, enabled)
    return {"ok": True, "enabled": enabled}


@settings_router.delete("/api/skills/{name}")
async def skills_remove(request: Request, name: str):
    db = request.app.state.db
    res = await request.app.state.orchestrator.skills_service.remove(name)
    enabled = [n for n in await _enabled_skills(db) if n != name]
    await _write_enabled_skills(db, enabled)
    return res
