#!/usr/bin/env python3
"""Minimal MCP server that exposes a 'get_secret' tool via stdio.

Uses only stdlib — no external dependencies required.
Communicates via newline-delimited JSON (NDJSON) over stdio.
"""

import json
import sys


SECRET = "FEC52599-123E-49FF-9E32-9E0D7E51BBA9"


def respond(req_id, result):
    msg = json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def handle(msg):
    method = msg.get("method")
    req_id = msg.get("id")

    if method == "initialize":
        respond(req_id, {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mini-mcp", "version": "1.0.0"},
        })
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        respond(req_id, {"tools": [{
            "name": "get_secret",
            "description": "Returns the secret value.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        }]})
    elif method == "tools/call":
        name = msg.get("params", {}).get("name")
        if name == "get_secret":
            respond(req_id, {"content": [{"type": "text", "text": SECRET}]})
        else:
            respond(req_id, {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True})
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
