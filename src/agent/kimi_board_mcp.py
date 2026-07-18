#!/usr/bin/env python3
"""Stdio MCP server exposing dashboard board tools to Kimi agents.

Spawned by the Kimi runtime itself (declared via ACP ``session/new``
``mcpServers``), so it runs outside the dashboard process and proxies every
tool call to the dashboard's HTTP API. Stdlib-only — the Kimi runtime spawns
it with the venv's ``sys.executable`` but it must not import dashboard code.

Configuration via environment variables (set by ``KimiAgentSession``):
- ``DASHBOARD_BASE_URL``  — e.g. http://127.0.0.1:8001 (required)
- ``DASHBOARD_ITEM_ID``   — the calling agent's own board item id (required)

Protocol: newline-delimited JSON-RPC 2.0 over stdio (same shape as
``examples/mini-mcp/server.py``): initialize / notifications/initialized /
tools/list / tools/call.
"""

import json
import os
import sys
import urllib.request

BASE_URL = os.environ.get("DASHBOARD_BASE_URL", "").rstrip("/")
ITEM_ID = os.environ.get("DASHBOARD_ITEM_ID", "")

TOOLS = [
    {
        "name": "create_todo",
        "description": (
            "Create a new todo card on the dashboard board for genuinely new, "
            "separate future work (never for the task you are already doing)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short todo title"},
                "description": {"type": "string", "description": "What needs to be done"},
                "epic_id": {"type": "string", "description": "Optional epic to group under"},
                "requires": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Item ids this todo depends on (it starts only after they merge)",
                },
                "autostart": {
                    "type": "boolean",
                    "description": (
                        "Start an agent for the new todo automatically. With no "
                        "requires given, it waits for YOUR card to merge first."
                    ),
                },
                "auto_approve": {
                    "type": "integer",
                    "description": "0=manual review, 1=auto review agent, 2=merge directly",
                },
                "use_chrome": {"type": "boolean", "description": "Give the new agent browser tools"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "delete_todo",
        "description": "Delete a todo card from the board by its item id.",
        "inputSchema": {
            "type": "object",
            "properties": {"item_id": {"type": "string"}},
            "required": ["item_id"],
        },
    },
    {
        "name": "create_epic",
        "description": "Create an epic for grouping related todos.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "color": {
                    "type": "string",
                    "description": "red|orange|amber|green|teal|blue|purple|pink",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "create_shortcut",
        "description": "Create a reusable shell-command shortcut on the dashboard.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "command": {"type": "string"},
            },
            "required": ["name", "command"],
        },
    },
    {
        "name": "view_board",
        "description": "View the current board: every card with id, column, status and title.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "who_am_i",
        "description": "Return the board card this agent is working on (your own item).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]


def _http(method, path, body=None):
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode() or "null")


def _items():
    data = _http("GET", "/api/items")
    return data if isinstance(data, list) else data.get("items", [])


def call_tool(name, args):
    """Run a board tool; returns the text result (raises on failure)."""
    if name == "create_todo":
        body = {
            "title": args["title"],
            "description": args.get("description", ""),
            "requires": args.get("requires") or [],
            "autostart": bool(args.get("autostart", False)),
            "auto_approve": args.get("auto_approve", 0),
            "use_chrome": bool(args.get("use_chrome", False)),
        }
        if args.get("epic_id"):
            body["epic_id"] = args["epic_id"]
        item = _http("POST", f"/api/items/{ITEM_ID}/agent-todos", body)
        if item.get("autostart_scheduled"):
            note = " (agent auto-starting)"
        elif body["requires"] or body["autostart"]:
            note = " (starts after its dependencies merge)"
        else:
            note = ""
        return f"Created todo {item['id']}: {item['title']}{note}"
    if name == "delete_todo":
        _http("DELETE", f"/api/items/{args['item_id']}")
        return f"Deleted todo {args['item_id']}"
    if name == "create_epic":
        body = {"title": args["title"]}
        if args.get("color"):
            body["color"] = args["color"]
        epic = _http("POST", "/api/epics", body)
        return f"Created epic {epic.get('id', '?')}: {args['title']}"
    if name == "create_shortcut":
        sc = _http("POST", "/api/shortcuts", {"name": args["name"], "command": args["command"]})
        return f"Created shortcut {sc.get('id', '?')}: {args['name']}"
    if name == "view_board":
        lines = [
            f"{i.get('id')} | {i.get('column_name')} | {i.get('status') or '-'} | {i.get('title')}"
            for i in _items()
        ]
        return "\n".join(lines) if lines else "(board is empty)"
    if name == "who_am_i":
        for i in _items():
            if i.get("id") == ITEM_ID:
                return json.dumps(i, ensure_ascii=False)
        return f"(item {ITEM_ID} not found on the board)"
    raise KeyError(name)


def respond(req_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
    sys.stdout.flush()


def handle(msg):
    method = msg.get("method")
    req_id = msg.get("id")

    if method == "initialize":
        respond(req_id, {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "board", "version": "1.0.0"},
        })
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        respond(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        try:
            text = call_tool(name, params.get("arguments") or {})
            respond(req_id, {"content": [{"type": "text", "text": text}]})
        except KeyError:
            respond(req_id, {"content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                             "isError": True})
        except Exception as e:
            respond(req_id, {"content": [{"type": "text", "text": f"Board tool failed: {e}"}],
                             "isError": True})
    elif req_id is not None:
        respond(req_id, {"error": {"code": -32601, "message": f"Unknown method: {method}"}})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            handle(json.loads(line))
        except json.JSONDecodeError:
            pass


if __name__ == "__main__":
    main()
