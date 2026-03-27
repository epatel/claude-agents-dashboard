"""End-to-end tests for the mini-mcp server.

Tests the MCP stdio server by spawning it as a subprocess and exercising
the full JSON-RPC protocol: initialize, tools/list, tools/call.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SERVER_PATH = Path(__file__).parent.parent.parent / "examples" / "mini-mcp" / "server.py"
EXPECTED_SECRET = "FEC52599-123E-49FF-9E32-9E0D7E51BBA9"


class MiniMcpClient:
    """Helper to communicate with the mini-mcp server via NDJSON over stdio."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._next_id = 0

    def _send(self, method, params=None, *, is_notification=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not is_notification:
            msg["id"] = self._next_id
            self._next_id += 1
        line = json.dumps(msg) + "\n"
        self.proc.stdin.write(line.encode())
        self.proc.stdin.flush()

    def _recv(self):
        line = self.proc.stdout.readline()
        assert line, "Server closed stdout unexpectedly"
        return json.loads(line)

    def initialize(self):
        self._send("initialize", {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        })
        return self._recv()

    def send_initialized(self):
        self._send("notifications/initialized", is_notification=True)

    def list_tools(self):
        self._send("tools/list", {})
        return self._recv()

    def call_tool(self, name, arguments=None):
        self._send("tools/call", {"name": name, "arguments": arguments or {}})
        return self._recv()

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=5)


@pytest.fixture
def mcp_client():
    client = MiniMcpClient()
    yield client
    try:
        client.close()
    except Exception:
        client.proc.kill()


class TestMiniMcpServer:
    def test_server_script_exists(self):
        assert SERVER_PATH.exists(), f"Server not found at {SERVER_PATH}"

    def test_initialize(self, mcp_client):
        resp = mcp_client.initialize()
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 0
        result = resp["result"]
        assert "protocolVersion" in result
        assert result["capabilities"] == {"tools": {}}
        assert result["serverInfo"]["name"] == "mini-mcp"

    def test_initialize_echoes_protocol_version(self, mcp_client):
        resp = mcp_client.initialize()
        assert resp["result"]["protocolVersion"] == "2025-11-25"

    def test_tools_list(self, mcp_client):
        mcp_client.initialize()
        mcp_client.send_initialized()
        resp = mcp_client.list_tools()
        tools = resp["result"]["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "get_secret"
        assert tools[0]["description"] == "Returns the secret value."
        assert tools[0]["inputSchema"]["type"] == "object"

    def test_call_get_secret(self, mcp_client):
        mcp_client.initialize()
        mcp_client.send_initialized()
        resp = mcp_client.call_tool("get_secret")
        result = resp["result"]
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == EXPECTED_SECRET

    def test_call_unknown_tool(self, mcp_client):
        mcp_client.initialize()
        mcp_client.send_initialized()
        resp = mcp_client.call_tool("nonexistent")
        result = resp["result"]
        assert result["isError"] is True
        assert "Unknown tool" in result["content"][0]["text"]

    def test_unknown_method(self, mcp_client):
        mcp_client._send("bogus/method", {})
        resp = mcp_client._recv()
        assert resp["result"]["error"]["code"] == -32601

    def test_full_handshake(self, mcp_client):
        """Full protocol flow: initialize → initialized → list → call."""
        # Initialize
        init_resp = mcp_client.initialize()
        assert init_resp["result"]["serverInfo"]["name"] == "mini-mcp"

        # Initialized notification (no response expected)
        mcp_client.send_initialized()

        # List tools
        list_resp = mcp_client.list_tools()
        tool_names = [t["name"] for t in list_resp["result"]["tools"]]
        assert "get_secret" in tool_names

        # Call tool
        call_resp = mcp_client.call_tool("get_secret")
        assert call_resp["result"]["content"][0]["text"] == EXPECTED_SECRET

    def test_server_exits_on_stdin_close(self, mcp_client):
        mcp_client.initialize()
        mcp_client.proc.stdin.close()
        exit_code = mcp_client.proc.wait(timeout=5)
        assert exit_code == 0

    def test_multiple_tool_calls(self, mcp_client):
        """Server handles multiple sequential calls correctly."""
        mcp_client.initialize()
        mcp_client.send_initialized()
        for i in range(3):
            resp = mcp_client.call_tool("get_secret")
            assert resp["result"]["content"][0]["text"] == EXPECTED_SECRET
            assert resp["id"] == i + 1  # id 0=init, 1,2,3=calls

    def test_ids_are_sequential(self, mcp_client):
        resp1 = mcp_client.initialize()
        resp2 = mcp_client.list_tools()
        resp3 = mcp_client.call_tool("get_secret")
        assert resp1["id"] == 0
        assert resp2["id"] == 1
        assert resp3["id"] == 2
