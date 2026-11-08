"""Shortcuts: saved shell commands run in the target project, with live output."""

import asyncio
import json
import uuid
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

shortcut_router = APIRouter()


# --- Shortcuts ---

# In-memory process tracker: shortcut_id → { process, output, status, exit_code }
_shortcut_processes: dict[str, dict] = {}


def _shortcuts_file(request: Request) -> Path:
    """Return path to shortcuts JSON file in data dir."""
    return request.app.state.data_dir / "shortcuts.json"


def _load_shortcuts(path: Path) -> list[dict]:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return []


def _save_shortcuts(path: Path, shortcuts: list[dict]):
    path.write_text(json.dumps(shortcuts, indent=2))


def _find_shortcut(shortcuts: list[dict], shortcut_id: str) -> dict:
    """The shortcut with ``shortcut_id``; HTTP 404 if there is none."""
    sc = next((s for s in shortcuts if s["id"] == shortcut_id), None)
    if not sc:
        raise HTTPException(status_code=404, detail="Shortcut not found")
    return sc


def _kill_shortcut_process(proc_info: dict | None, only_if_running: bool = False) -> bool:
    """Kill the shortcut's process, if it has one (and, with ``only_if_running``,
    only while it is still running). True if a kill was sent."""
    proc = proc_info.get("process") if proc_info else None
    if not proc:
        return False
    if only_if_running and proc.returncode is not None:
        return False
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    return True


@shortcut_router.get("/api/shortcuts")
async def list_shortcuts(request: Request):
    return _load_shortcuts(_shortcuts_file(request))


class ShortcutCreate(BaseModel):
    name: str
    command: str


@shortcut_router.post("/api/shortcuts")
async def create_shortcut(request: Request, body: ShortcutCreate):
    path = _shortcuts_file(request)
    shortcuts = _load_shortcuts(path)
    sc = {"id": uuid.uuid4().hex[:10], "name": body.name, "command": body.command}
    shortcuts.append(sc)
    _save_shortcuts(path, shortcuts)
    return sc


class ShortcutUpdate(BaseModel):
    name: str | None = None
    command: str | None = None


@shortcut_router.put("/api/shortcuts/{shortcut_id}")
async def update_shortcut(request: Request, shortcut_id: str, body: ShortcutUpdate):
    path = _shortcuts_file(request)
    shortcuts = _load_shortcuts(path)
    sc = _find_shortcut(shortcuts, shortcut_id)
    if body.name is not None:
        sc["name"] = body.name
    if body.command is not None:
        sc["command"] = body.command
    _save_shortcuts(path, shortcuts)
    return sc


@shortcut_router.delete("/api/shortcuts/{shortcut_id}")
async def delete_shortcut(request: Request, shortcut_id: str):
    path = _shortcuts_file(request)
    shortcuts = _load_shortcuts(path)
    shortcuts = [s for s in shortcuts if s["id"] != shortcut_id]
    _save_shortcuts(path, shortcuts)
    # Kill running process if any
    _kill_shortcut_process(_shortcut_processes.pop(shortcut_id, None))
    return {"ok": True}


@shortcut_router.post("/api/shortcuts/{shortcut_id}/run")
async def run_shortcut(request: Request, shortcut_id: str):
    """Run a shortcut command as a subprocess."""
    sc = _find_shortcut(_load_shortcuts(_shortcuts_file(request)), shortcut_id)

    # Kill previous process for this shortcut if still running
    _kill_shortcut_process(_shortcut_processes.get(shortcut_id), only_if_running=True)

    # Start the subprocess
    cwd = str(request.app.state.target_project)
    proc = await asyncio.create_subprocess_shell(
        sc["command"],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )

    proc_info = {
        "process": proc,
        "output": "",
        "status": "running",
        "exit_code": None,
    }
    _shortcut_processes[shortcut_id] = proc_info

    # Background task to read output
    asyncio.create_task(_read_shortcut_output(proc, proc_info))
    return {"status": "started"}


async def _read_shortcut_output(proc, proc_info: dict) -> None:
    """Collect a shortcut's output into ``proc_info`` and record how it ended.

    Once the user stops the shortcut (``_stopped``), late output and the exit
    status are no longer recorded.
    """
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            # Stop appending once the process has been stopped by the user
            if proc_info.get("_stopped"):
                continue
            proc_info["output"] += line.decode("utf-8", errors="replace")
            # Cap output at 500KB
            if len(proc_info["output"]) > 500_000:
                proc_info["output"] = proc_info["output"][-400_000:]
        await proc.wait()
        # Don't overwrite status if already stopped by user
        if not proc_info.get("_stopped"):
            proc_info["exit_code"] = proc.returncode
            proc_info["status"] = "done" if proc.returncode == 0 else "failed"
    except Exception as e:
        if not proc_info.get("_stopped"):
            proc_info["output"] += f"\n[Error reading output: {e}]"
            proc_info["status"] = "failed"
            proc_info["exit_code"] = -1


@shortcut_router.get("/api/shortcuts/{shortcut_id}/output")
async def get_shortcut_output(shortcut_id: str):
    """Get current output and status of a running shortcut."""
    proc_info = _shortcut_processes.get(shortcut_id)
    if not proc_info:
        return {"status": "idle", "output": "", "exit_code": None}
    return {
        "status": proc_info["status"],
        "output": proc_info["output"],
        "exit_code": proc_info["exit_code"],
    }


@shortcut_router.post("/api/shortcuts/{shortcut_id}/stop")
async def stop_shortcut(shortcut_id: str):
    """Stop a running shortcut, keeping its output log."""
    proc_info = _shortcut_processes.get(shortcut_id)
    if not proc_info:
        return {"ok": False, "detail": "No process found"}
    # Set _stopped flag first so _read_output() stops appending late output
    proc_info["_stopped"] = True
    if _kill_shortcut_process(proc_info, only_if_running=True):
        # Wait briefly for process to finish
        try:
            await asyncio.wait_for(proc_info["process"].wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
    # Yield once so _read_output() can see the _stopped flag and drain
    await asyncio.sleep(0)
    proc_info["output"] += "\n\n======= STOPPED BY USER =======\n"
    proc_info["status"] = "stopped"
    proc_info["exit_code"] = proc_info.get("exit_code") or -15
    return {"ok": True}


@shortcut_router.post("/api/shortcuts/{shortcut_id}/reset")
async def reset_shortcut(shortcut_id: str):
    """Reset a shortcut: kill any running process and clear its output log."""
    _kill_shortcut_process(_shortcut_processes.pop(shortcut_id, None))
    return {"ok": True}
