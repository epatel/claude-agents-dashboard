#!/usr/bin/env python3
"""Minimal MCP server that exposes a 'get_secret' tool via stdio.

Uses only stdlib — no external dependencies required.
Communicates via newline-delimited JSON-RPC 2.0 (NDJSON) over stdio:
one message per line in, one response per line out.

Requests (messages with an "id") get exactly one response — a "result", or a
JSON-RPC "error" for an unknown method. Notifications (no "id") never get a
response. Lines that are not a JSON object are ignored.
"""

import json
import sys


SECRET = "FEC52599-123E-49FF-9E32-9E0D7E51BBA9"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
METHOD_NOT_FOUND = -32601

TOOLS = [{
    "name": "get_secret",
    "description": "Returns the secret value.",
    "inputSchema": {"type": "object", "properties": {}, "required": []},
}]


def send(message):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
    sys.stdout.flush()


def text_content(text, *, is_error=False):
    """A tools/call result holding one text block."""
    result = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    return result


def initialize(params):
    return {
        "protocolVersion": params.get("protocolVersion", DEFAULT_PROTOCOL_VERSION),
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "mini-mcp", "version": "1.0.0"},
    }


def call_tool(params):
    name = params.get("name")
    if name == "get_secret":
        return text_content(SECRET)
    # MCP reports a failing tool as a result with isError, not a protocol error.
    return text_content(f"Unknown tool: {name}", is_error=True)


# Request method -> handler(params) returning the result.
HANDLERS = {
    "initialize": initialize,
    "ping": lambda params: {},
    "tools/list": lambda params: {"tools": TOOLS},
    "tools/call": call_tool,
}


def handle(msg):
    """Answer one decoded message (notifications, e.g. notifications/initialized, get no reply)."""
    if not isinstance(msg, dict) or "id" not in msg:
        return
    method = msg.get("method")
    params = msg.get("params")
    if not isinstance(params, dict):
        params = {}
    handler = HANDLERS.get(method)
    if handler is None:
        send({"id": msg["id"], "error": {"code": METHOD_NOT_FOUND, "message": f"Unknown method: {method}"}})
    else:
        send({"id": msg["id"], "result": handler(params)})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        handle(msg)


if __name__ == "__main__":
    main()
