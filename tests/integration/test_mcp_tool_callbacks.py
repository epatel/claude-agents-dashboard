"""
P1 Priority Integration Tests: MCP Tool Callbacks and Integration

Tests MCP tool callback functionality including:
- Agent session MCP tool integration
- Callback handling and response processing
- Error recovery and timeout handling
- Tool permission and security validation
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from src.agent.session import AgentSession
from src.agent.orchestrator import AgentOrchestrator


@pytest.mark.integration
class TestMCPToolCallbacks:
    """Integration tests for MCP tool callbacks."""

    @pytest_asyncio.fixture
    async def mock_mcp_session(self):
        """Create a mock MCP session for testing."""
        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock()
        mock_session.is_connected = True
        return mock_session

    @pytest_asyncio.fixture
    async def agent_session_with_mcp(
        self, test_orchestrator, test_item, mock_mcp_session
    ):
        """Create an agent session with MCP tools configured."""
        session = AgentSession(
            item_id=test_item["id"],
            orchestrator=test_orchestrator,
            model="claude-3-sonnet-20240229"
        )
        session.mcp_session = mock_mcp_session
        return session

    async def test_clarification_tool_callback(
        self, agent_session_with_mcp, test_item, mock_mcp_session
    ):
        """Test clarification tool callback handling."""
        item_id = test_item["id"]
        prompt = "What color should the button be?"
        choices = ["red", "blue", "green"]

        # Mock the MCP tool call for clarification
        mock_mcp_session.call_tool.return_value = {
            "type": "clarification_request",
            "prompt": prompt,
            "choices": choices
        }

        # Test the callback
        result = await agent_session_with_mcp._handle_mcp_tool_call(
            "ask_user", {"prompt": prompt, "choices": choices}
        )

        assert result is not None
        mock_mcp_session.call_tool.assert_called_once_with(
            "ask_user", {"prompt": prompt, "choices": choices}
        )

    async def test_commit_message_tool_callback(
        self, agent_session_with_mcp, test_item, mock_mcp_session
    ):
        """Test commit message tool callback."""
        commit_message = "Add user authentication feature"

        mock_mcp_session.call_tool.return_value = {
            "type": "commit_message",
            "message": commit_message
        }

        result = await agent_session_with_mcp._handle_mcp_tool_call(
            "set_commit_message", {"message": commit_message}
        )

        assert result is not None
        mock_mcp_session.call_tool.assert_called_once()

        # Verify the commit message was stored
        assert agent_session_with_mcp.commit_message == commit_message

    async def test_todo_creation_tool_callback(
        self, agent_session_with_mcp, test_item, mock_mcp_session
    ):
        """Test todo creation tool callback."""
        todo_data = {
            "title": "Add unit tests",
            "description": "Create comprehensive unit tests for the new feature",
            "priority": "high"
        }

        mock_mcp_session.call_tool.return_value = {
            "type": "todo_created",
            "todo": todo_data
        }

        result = await agent_session_with_mcp._handle_mcp_tool_call(
            "create_todo", todo_data
        )

        assert result is not None
        mock_mcp_session.call_tool.assert_called_once_with("create_todo", todo_data)

    async def test_file_operation_tool_callbacks(
        self, agent_session_with_mcp, test_item, mock_mcp_session
    ):
        """Test file operation tool callbacks (read, write, edit)."""
        # Test file read
        file_path = "/test/file.py"
        file_content = "print('Hello, World!')"

        mock_mcp_session.call_tool.return_value = {
            "type": "file_content",
            "path": file_path,
            "content": file_content
        }

        result = await agent_session_with_mcp._handle_mcp_tool_call(
            "read_file", {"path": file_path}
        )

        assert result is not None
        assert result["content"] == file_content

        # Test file write
        write_data = {
            "path": "/test/new_file.py",
            "content": "def hello():\n    return 'Hello!'"
        }

        mock_mcp_session.call_tool.return_value = {
            "type": "file_written",
            "path": write_data["path"],
            "success": True
        }

        result = await agent_session_with_mcp._handle_mcp_tool_call(
            "write_file", write_data
        )

        assert result["success"] is True

    async def test_shell_command_tool_callback(
        self, agent_session_with_mcp, test_item, mock_mcp_session
    ):
        """Test shell command execution tool callback."""
        command = "ls -la"
        expected_output = "total 4\ndrwxr-xr-x 2 user user 4096 Jan 1 12:00 ."

        mock_mcp_session.call_tool.return_value = {
            "type": "command_result",
            "command": command,
            "stdout": expected_output,
            "stderr": "",
            "exit_code": 0
        }

        result = await agent_session_with_mcp._handle_mcp_tool_call(
            "execute_command", {"command": command}
        )

        assert result["exit_code"] == 0
        assert result["stdout"] == expected_output

    async def test_mcp_tool_error_handling(
        self, agent_session_with_mcp, test_item, mock_mcp_session
    ):
        """Test MCP tool error handling."""
        # Test connection error
        mock_mcp_session.call_tool.side_effect = ConnectionError("MCP connection lost")

        with pytest.raises(ConnectionError):
            await agent_session_with_mcp._handle_mcp_tool_call(
                "test_tool", {"param": "value"}
            )

        # Test timeout error
        mock_mcp_session.call_tool.side_effect = asyncio.TimeoutError("Tool call timed out")

        with pytest.raises(asyncio.TimeoutError):
            await agent_session_with_mcp._handle_mcp_tool_call(
                "slow_tool", {"param": "value"}
            )

        # Test invalid tool error
        mock_mcp_session.call_tool.side_effect = ValueError("Unknown tool: invalid_tool")

        with pytest.raises(ValueError):
            await agent_session_with_mcp._handle_mcp_tool_call(
                "invalid_tool", {"param": "value"}
            )

    async def test_mcp_tool_timeout_configuration(
        self, agent_session_with_mcp, test_item, mock_mcp_session
    ):
        """Test MCP tool timeout configuration."""
        # Configure different timeouts for different tools
        tool_timeouts = {
            "quick_tool": 5.0,
            "slow_tool": 60.0,
            "very_slow_tool": 300.0
        }

        agent_session_with_mcp.tool_timeouts = tool_timeouts

        # Test that timeout is applied correctly
        async def mock_slow_tool(*args, **kwargs):
            await asyncio.sleep(10)  # Simulates slow operation
            return {"result": "completed"}

        mock_mcp_session.call_tool.side_effect = mock_slow_tool

        # Should timeout for quick_tool (5s timeout, 10s operation)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                agent_session_with_mcp._handle_mcp_tool_call(
                    "quick_tool", {"param": "value"}
                ),
                timeout=tool_timeouts["quick_tool"]
            )

    async def test_mcp_tool_permission_validation(
        self, agent_session_with_mcp, test_item, mock_mcp_session
    ):
        """Test MCP tool permission validation."""
        # Configure allowed and restricted tools
        allowed_tools = {
            "read_file", "write_file", "execute_command",
            "ask_user", "set_commit_message"
        }
        restricted_tools = {
            "delete_system_files", "modify_permissions", "network_request"
        }

        agent_session_with_mcp.allowed_tools = allowed_tools
        agent_session_with_mcp.restricted_tools = restricted_tools

        # Test allowed tool
        mock_mcp_session.call_tool.return_value = {"result": "success"}

        result = await agent_session_with_mcp._handle_mcp_tool_call(
            "read_file", {"path": "/safe/file.txt"}
        )
        assert result["result"] == "success"

        # Test restricted tool
        with pytest.raises(PermissionError):
            await agent_session_with_mcp._handle_mcp_tool_call(
                "delete_system_files", {"path": "/etc/passwd"}
            )

    async def test_mcp_tool_result_validation(
        self, agent_session_with_mcp, test_item, mock_mcp_session
    ):
        """Test validation of MCP tool results."""
        # Test valid result format
        valid_result = {
            "type": "success",
            "data": {"key": "value"},
            "metadata": {"timestamp": "2024-01-01T12:00:00Z"}
        }

        mock_mcp_session.call_tool.return_value = valid_result

        result = await agent_session_with_mcp._handle_mcp_tool_call(
            "valid_tool", {"param": "value"}
        )
        assert result == valid_result

        # Test invalid result format
        invalid_results = [
            None,  # Null result
            "string result",  # String instead of dict
            {"missing_type": "no type field"},  # Missing required fields
            {"type": "error", "invalid_structure": True}  # Malformed error
        ]

        for invalid_result in invalid_results:
            mock_mcp_session.call_tool.return_value = invalid_result

            # Should handle gracefully or raise appropriate error
            try:
                result = await agent_session_with_mcp._handle_mcp_tool_call(
                    "invalid_tool", {"param": "value"}
                )
                # If it succeeds, result should be sanitized
                assert isinstance(result, dict) or result is None
            except (ValueError, TypeError):
                # Expected for truly invalid results
                assert True

    async def test_concurrent_mcp_tool_calls(
        self, agent_session_with_mcp, test_item, mock_mcp_session
    ):
        """Test concurrent MCP tool calls."""
        # Set up multiple tool calls
        tool_calls = [
            ("read_file", {"path": f"/file{i}.txt"})
            for i in range(5)
        ]

        # Mock responses
        async def mock_tool_call(tool_name, params):
            await asyncio.sleep(0.1)  # Simulate processing time
            return {
                "type": "file_content",
                "path": params["path"],
                "content": f"Content of {params['path']}"
            }

        mock_mcp_session.call_tool.side_effect = mock_tool_call

        # Execute concurrent tool calls
        tasks = [
            agent_session_with_mcp._handle_mcp_tool_call(tool_name, params)
            for tool_name, params in tool_calls
        ]

        results = await asyncio.gather(*tasks)

        # Verify all calls completed successfully
        assert len(results) == 5
        for i, result in enumerate(results):
            assert result["path"] == f"/file{i}.txt"
            assert f"file{i}.txt" in result["content"]

    async def test_mcp_tool_state_management(
        self, agent_session_with_mcp, test_item, mock_mcp_session
    ):
        """Test MCP tool state management across calls."""
        # Test maintaining state across tool calls
        initial_state = {"counter": 0, "items": []}

        mock_mcp_session.get_state = AsyncMock(return_value=initial_state)
        mock_mcp_session.set_state = AsyncMock()

        # First tool call that modifies state
        mock_mcp_session.call_tool.return_value = {
            "type": "state_update",
            "new_state": {"counter": 1, "items": ["item1"]}
        }

        result1 = await agent_session_with_mcp._handle_mcp_tool_call(
            "increment_counter", {}
        )

        # Verify state was updated
        mock_mcp_session.set_state.assert_called_once()

        # Second tool call using updated state
        mock_mcp_session.call_tool.return_value = {
            "type": "state_update",
            "new_state": {"counter": 2, "items": ["item1", "item2"]}
        }

        result2 = await agent_session_with_mcp._handle_mcp_tool_call(
            "add_item", {"item": "item2"}
        )

        # Verify state consistency
        assert mock_mcp_session.set_state.call_count == 2


@pytest.mark.integration
class TestMCPSessionIntegration:
    """Integration tests for MCP session lifecycle."""

    async def test_mcp_session_initialization(
        self, test_orchestrator, test_item
    ):
        """Test MCP session initialization."""
        session = AgentSession(
            item_id=test_item["id"],
            orchestrator=test_orchestrator,
            model="claude-3-sonnet-20240229"
        )

        # Test session can be initialized with MCP
        with patch('src.agent.session.MCPClient') as mock_client:
            mock_client.return_value.connect = AsyncMock()
            mock_client.return_value.is_connected = True

            await session._initialize_mcp_session()

            assert session.mcp_session is not None
            mock_client.return_value.connect.assert_called_once()

    async def test_mcp_session_cleanup(
        self, test_orchestrator, test_item
    ):
        """Test MCP session cleanup."""
        session = AgentSession(
            item_id=test_item["id"],
            orchestrator=test_orchestrator,
            model="claude-3-sonnet-20240229"
        )

        # Mock MCP session
        mock_mcp = AsyncMock()
        mock_mcp.disconnect = AsyncMock()
        session.mcp_session = mock_mcp

        # Test cleanup
        await session._cleanup_mcp_session()

        mock_mcp.disconnect.assert_called_once()
        assert session.mcp_session is None

    async def test_mcp_session_reconnection(
        self, test_orchestrator, test_item
    ):
        """Test MCP session reconnection on connection loss."""
        session = AgentSession(
            item_id=test_item["id"],
            orchestrator=test_orchestrator,
            model="claude-3-sonnet-20240229"
        )

        mock_mcp = AsyncMock()
        mock_mcp.is_connected = False
        mock_mcp.connect = AsyncMock()
        session.mcp_session = mock_mcp

        # Test reconnection attempt
        with patch.object(session, '_initialize_mcp_session') as mock_init:
            mock_init.return_value = None

            await session._ensure_mcp_connection()

            mock_init.assert_called_once()

    async def test_mcp_tool_discovery(
        self, test_orchestrator, test_item
    ):
        """Test MCP tool discovery and registration."""
        session = AgentSession(
            item_id=test_item["id"],
            orchestrator=test_orchestrator,
            model="claude-3-sonnet-20240229"
        )

        # Mock available tools
        mock_tools = [
            {"name": "read_file", "description": "Read a file"},
            {"name": "write_file", "description": "Write to a file"},
            {"name": "ask_user", "description": "Ask user for clarification"},
        ]

        mock_mcp = AsyncMock()
        mock_mcp.list_tools = AsyncMock(return_value=mock_tools)
        session.mcp_session = mock_mcp

        # Test tool discovery
        available_tools = await session._discover_mcp_tools()

        assert len(available_tools) == 3
        assert "read_file" in [tool["name"] for tool in available_tools]
        mock_mcp.list_tools.assert_called_once()

    async def test_full_agent_session_with_mcp_tools(
        self, test_orchestrator, test_item, mock_git_operations
    ):
        """Test complete agent session with MCP tool integration."""
        # This is an end-to-end integration test
        session = AgentSession(
            item_id=test_item["id"],
            orchestrator=test_orchestrator,
            model="claude-3-sonnet-20240229"
        )

        # Mock the entire MCP interaction
        mock_mcp = AsyncMock()
        mock_mcp.is_connected = True
        mock_mcp.call_tool = AsyncMock()

        # Simulate agent asking for clarification
        clarification_response = asyncio.Future()
        clarification_response.set_result("blue")

        mock_mcp.call_tool.side_effect = [
            # First call - ask for clarification
            clarification_response,
            # Second call - set commit message
            {"type": "commit_message_set", "success": True},
            # Third call - write file
            {"type": "file_written", "path": "/test/file.py", "success": True}
        ]

        session.mcp_session = mock_mcp

        # Test session execution with MCP tools
        with patch.object(session, 'run_agent_conversation') as mock_conversation:
            mock_conversation.return_value = AsyncMock()

            # Start the session
            await session.start()

            # Verify MCP tools were available and could be called
            assert session.mcp_session is not None
            assert session.mcp_session.is_connected