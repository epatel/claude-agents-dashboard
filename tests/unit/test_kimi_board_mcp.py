"""Unit tests for src/agent/kimi_board_mcp.py — the Kimi board-tools stdio MCP proxy.

Spawns the real server subprocess against a stub dashboard HTTP API, mirroring
tests/unit/test_mini_mcp.py.
"""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SERVER_PATH = str(Path(__file__).resolve().parents[2] / "src" / "agent" / "kimi_board_mcp.py")

ITEMS = [
    {"id": "self-1", "column_name": "doing", "status": "running", "title": "My own task"},
    {"id": "other-2", "column_name": "todo", "status": None, "title": "Other task"},
]


class StubDashboardHandler(BaseHTTPRequestHandler):
    requests = []  # (method, path, body) — class-level capture

    def _reply(self, payload, status=200):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        type(self).requests.append((self.command, self.path, body))
        return body

    def do_GET(self):
        self._record()
        if self.path == "/api/items":
            self._reply(ITEMS)
        else:
            self._reply({"detail": "Not Found"}, status=404)

    def do_POST(self):
        body = self._record()
        if self.path == "/api/items":
            self._reply({"id": "new-3", "title": body["title"]})
        elif self.path == "/api/epics":
            self._reply({"id": "epic-1", "title": body["title"]})
        elif self.path == "/api/shortcuts":
            self._reply({"id": "sc-1", "name": body["name"]})
        else:
            self._reply({"detail": "Not Found"}, status=404)

    def do_DELETE(self):
        self._record()
        self._reply({"ok": True})

    def log_message(self, *args):
        pass


class McpProc:
    def __init__(self, env_extra):
        env = dict(**env_extra)
        self.proc = subprocess.Popen(
            [sys.executable, SERVER_PATH],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, env={**env, "PATH": ""},
        )
        self._id = 0

    def request(self, method, params=None):
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            msg["params"] = params
        self._id += 1
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def call(self, name, arguments=None):
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=5)


@pytest.fixture
def stub_dashboard():
    StubDashboardHandler.requests = []
    httpd = HTTPServer(("127.0.0.1", 0), StubDashboardHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def mcp(stub_dashboard):
    proc = McpProc({
        "DASHBOARD_BASE_URL": stub_dashboard,
        "DASHBOARD_ITEM_ID": "self-1",
    })
    yield proc
    proc.close()


class TestBoardMcpServer:
    def test_initialize_and_tools_list(self, mcp):
        init = mcp.request("initialize", {"protocolVersion": "2024-11-05"})
        assert init["result"]["serverInfo"]["name"] == "board"
        tools = mcp.request("tools/list")["result"]["tools"]
        assert {t["name"] for t in tools} == {
            "create_todo", "delete_todo", "create_epic",
            "create_shortcut", "view_board", "who_am_i",
        }

    def test_create_todo_posts_to_api(self, mcp):
        resp = mcp.call("create_todo", {"title": "New task", "description": "details"})
        assert "Created todo new-3" in resp["result"]["content"][0]["text"]
        method, path, body = StubDashboardHandler.requests[-1]
        assert (method, path) == ("POST", "/api/items")
        assert body == {"title": "New task", "description": "details"}

    def test_create_todo_includes_repo_when_set(self, stub_dashboard):
        proc = McpProc({
            "DASHBOARD_BASE_URL": stub_dashboard,
            "DASHBOARD_ITEM_ID": "self-1",
            "DASHBOARD_REPO": "backend",
        })
        try:
            proc.call("create_todo", {"title": "T"})
            _, _, body = StubDashboardHandler.requests[-1]
            assert body["repo"] == "backend"
        finally:
            proc.close()

    def test_delete_todo(self, mcp):
        resp = mcp.call("delete_todo", {"item_id": "other-2"})
        assert "Deleted todo other-2" in resp["result"]["content"][0]["text"]
        assert ("DELETE", "/api/items/other-2", None) in StubDashboardHandler.requests

    def test_create_epic_and_shortcut(self, mcp):
        assert "Created epic epic-1" in mcp.call(
            "create_epic", {"title": "E", "color": "teal"})["result"]["content"][0]["text"]
        assert StubDashboardHandler.requests[-1][2] == {"title": "E", "color": "teal"}
        assert "Created shortcut sc-1" in mcp.call(
            "create_shortcut", {"name": "tests", "command": "make test"})["result"]["content"][0]["text"]

    def test_view_board_lists_all_cards(self, mcp):
        text = mcp.call("view_board")["result"]["content"][0]["text"]
        assert "self-1 | doing | running | My own task" in text
        assert "other-2 | todo | - | Other task" in text

    def test_who_am_i_returns_own_item(self, mcp):
        text = mcp.call("who_am_i")["result"]["content"][0]["text"]
        assert json.loads(text)["id"] == "self-1"

    def test_unknown_tool_is_error(self, mcp):
        resp = mcp.call("nope")
        assert resp["result"]["isError"] is True

    def test_http_failure_is_error_not_crash(self, stub_dashboard):
        proc = McpProc({
            "DASHBOARD_BASE_URL": "http://127.0.0.1:9",  # nothing listens here
            "DASHBOARD_ITEM_ID": "self-1",
        })
        try:
            resp = proc.call("view_board")
            assert resp["result"]["isError"] is True
            assert "Board tool failed" in resp["result"]["content"][0]["text"]
            follow_up = proc.request("tools/list")  # server still alive
            assert len(follow_up["result"]["tools"]) == 6
        finally:
            proc.close()
