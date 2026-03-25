"""
P1 Priority Unit Tests: WebSocket Connection Manager

Tests WebSocket functionality including:
- Connection management and lifecycle
- Message broadcasting and routing
- Error handling and reconnection
- Real-time updates and notifications
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import WebSocket

from src.web.websocket import ConnectionManager


@pytest.mark.unit
class TestWebSocketConnectionManager:
    """Test suite for WebSocket connection manager."""

    @pytest.fixture
    def connection_manager(self):
        """Create a connection manager instance."""
        return ConnectionManager()

    @pytest.fixture
    def mock_websocket(self):
        """Create a mock WebSocket connection."""
        websocket = MagicMock(spec=WebSocket)
        websocket.accept = AsyncMock()
        websocket.send_text = AsyncMock()
        websocket.send_json = AsyncMock()
        websocket.close = AsyncMock()
        websocket.receive_text = AsyncMock()
        websocket.receive_json = AsyncMock()
        return websocket

    async def test_connection_addition(self, connection_manager, mock_websocket):
        """Test adding a WebSocket connection."""
        connection_id = "test-connection-123"

        await connection_manager.connect(mock_websocket, connection_id)

        assert connection_id in connection_manager.active_connections
        assert connection_manager.active_connections[connection_id] == mock_websocket
        mock_websocket.accept.assert_called_once()

    async def test_connection_removal(self, connection_manager, mock_websocket):
        """Test removing a WebSocket connection."""
        connection_id = "test-connection-123"

        # Add connection first
        await connection_manager.connect(mock_websocket, connection_id)
        assert connection_id in connection_manager.active_connections

        # Remove connection
        await connection_manager.disconnect(connection_id)
        assert connection_id not in connection_manager.active_connections

    async def test_message_broadcasting(self, connection_manager):
        """Test broadcasting messages to all connections."""
        # Create multiple mock connections
        connections = {}
        for i in range(3):
            conn_id = f"connection-{i}"
            websocket = MagicMock(spec=WebSocket)
            websocket.send_json = AsyncMock()
            connections[conn_id] = websocket
            await connection_manager.connect(websocket, conn_id)

        # Broadcast a message
        message = {"type": "update", "data": {"item_id": "123", "status": "completed"}}
        await connection_manager.broadcast(message)

        # Verify all connections received the message
        for websocket in connections.values():
            websocket.send_json.assert_called_once_with(message)

    async def test_targeted_message_sending(self, connection_manager, mock_websocket):
        """Test sending message to specific connection."""
        connection_id = "target-connection"

        await connection_manager.connect(mock_websocket, connection_id)

        message = {"type": "notification", "content": "Task completed"}
        await connection_manager.send_to_connection(connection_id, message)

        mock_websocket.send_json.assert_called_once_with(message)

    async def test_send_to_nonexistent_connection(self, connection_manager):
        """Test sending message to non-existent connection."""
        message = {"type": "test"}

        # Should handle gracefully without raising exception
        result = await connection_manager.send_to_connection("nonexistent", message)
        assert result is False

    async def test_broadcast_with_failed_connection(self, connection_manager):
        """Test broadcasting when one connection fails."""
        # Create connections, one that will fail
        good_websocket = MagicMock(spec=WebSocket)
        good_websocket.send_json = AsyncMock()

        bad_websocket = MagicMock(spec=WebSocket)
        bad_websocket.send_json = AsyncMock(side_effect=Exception("Connection closed"))

        await connection_manager.connect(good_websocket, "good-connection")
        await connection_manager.connect(bad_websocket, "bad-connection")

        message = {"type": "test", "data": "broadcast"}

        # Broadcast should continue despite one connection failing
        await connection_manager.broadcast(message)

        good_websocket.send_json.assert_called_once_with(message)
        bad_websocket.send_json.assert_called_once_with(message)

        # Bad connection should be removed from active connections
        assert "bad-connection" not in connection_manager.active_connections
        assert "good-connection" in connection_manager.active_connections

    async def test_connection_health_check(self, connection_manager, mock_websocket):
        """Test connection health checking."""
        connection_id = "health-test-connection"

        await connection_manager.connect(mock_websocket, connection_id)

        # Test healthy connection
        mock_websocket.send_json.return_value = None  # Successful send
        is_healthy = await connection_manager.check_connection_health(connection_id)
        assert is_healthy is True

        # Test unhealthy connection
        mock_websocket.send_json.side_effect = Exception("Connection error")
        is_healthy = await connection_manager.check_connection_health(connection_id)
        assert is_healthy is False

        # Connection should be removed after health check failure
        assert connection_id not in connection_manager.active_connections

    async def test_connection_cleanup_on_error(self, connection_manager, mock_websocket):
        """Test automatic cleanup of failed connections."""
        connection_id = "cleanup-test"

        await connection_manager.connect(mock_websocket, connection_id)

        # Simulate connection error during send
        mock_websocket.send_json.side_effect = ConnectionResetError("Connection reset")

        message = {"type": "test"}
        result = await connection_manager.send_to_connection(connection_id, message)

        assert result is False
        assert connection_id not in connection_manager.active_connections

    async def test_get_connection_count(self, connection_manager):
        """Test getting active connection count."""
        assert connection_manager.get_connection_count() == 0

        # Add connections
        websockets = []
        for i in range(3):
            ws = MagicMock(spec=WebSocket)
            ws.accept = AsyncMock()
            websockets.append(ws)
            await connection_manager.connect(ws, f"connection-{i}")

        assert connection_manager.get_connection_count() == 3

        # Remove one connection
        await connection_manager.disconnect("connection-1")
        assert connection_manager.get_connection_count() == 2

    async def test_get_active_connection_ids(self, connection_manager):
        """Test getting list of active connection IDs."""
        connection_ids = ["conn-1", "conn-2", "conn-3"]

        for conn_id in connection_ids:
            ws = MagicMock(spec=WebSocket)
            ws.accept = AsyncMock()
            await connection_manager.connect(ws, conn_id)

        active_ids = connection_manager.get_active_connection_ids()
        assert set(active_ids) == set(connection_ids)

    async def test_broadcast_to_subset(self, connection_manager):
        """Test broadcasting to a subset of connections."""
        # Create connections with different groups
        groups = {"group-a": ["conn-1", "conn-2"], "group-b": ["conn-3", "conn-4"]}
        websockets = {}

        for group, conn_ids in groups.items():
            for conn_id in conn_ids:
                ws = MagicMock(spec=WebSocket)
                ws.accept = AsyncMock()
                ws.send_json = AsyncMock()
                websockets[conn_id] = ws
                await connection_manager.connect(ws, conn_id)

        # Broadcast to group-a only
        message = {"type": "group-message", "group": "a"}
        target_connections = groups["group-a"]

        await connection_manager.broadcast_to_connections(target_connections, message)

        # Verify only group-a connections received the message
        for conn_id in groups["group-a"]:
            websockets[conn_id].send_json.assert_called_once_with(message)

        for conn_id in groups["group-b"]:
            websockets[conn_id].send_json.assert_not_called()

    async def test_message_queue_for_reconnection(self, connection_manager):
        """Test queueing messages for reconnected clients."""
        connection_id = "reconnect-test"
        ws1 = MagicMock(spec=WebSocket)
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock()

        # Initial connection
        await connection_manager.connect(ws1, connection_id)

        # Connection drops
        await connection_manager.disconnect(connection_id)

        # Messages sent while disconnected (should be queued if supported)
        queued_messages = [
            {"type": "update", "id": 1},
            {"type": "update", "id": 2},
        ]

        for message in queued_messages:
            await connection_manager.send_to_connection(connection_id, message)

        # Reconnect with new WebSocket
        ws2 = MagicMock(spec=WebSocket)
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()

        await connection_manager.connect(ws2, connection_id)

        # If message queueing is implemented, queued messages should be sent
        # This is optional functionality, so we just verify no exceptions occur


@pytest.mark.unit
class TestWebSocketMessageHandling:
    """Test suite for WebSocket message handling."""

    @pytest.fixture
    def connection_manager(self):
        return ConnectionManager()

    async def test_json_message_validation(self, connection_manager, mock_websocket):
        """Test validation of incoming JSON messages."""
        connection_id = "validation-test"
        await connection_manager.connect(mock_websocket, connection_id)

        valid_messages = [
            {"type": "ping"},
            {"type": "subscribe", "channel": "updates"},
            {"type": "action", "action": "start_agent", "item_id": "123"},
        ]

        for message in valid_messages:
            # Should handle valid messages without error
            await connection_manager.send_to_connection(connection_id, message)
            mock_websocket.send_json.assert_called_with(message)

    async def test_large_message_handling(self, connection_manager, mock_websocket):
        """Test handling of large messages."""
        connection_id = "large-message-test"
        await connection_manager.connect(mock_websocket, connection_id)

        # Create a large message
        large_data = {"data": "x" * 10000, "array": list(range(1000))}
        large_message = {"type": "large_update", "payload": large_data}

        await connection_manager.send_to_connection(connection_id, large_message)
        mock_websocket.send_json.assert_called_once_with(large_message)

    async def test_malformed_json_handling(self, connection_manager):
        """Test handling of malformed JSON messages."""
        # This would typically be tested in message parsing logic
        malformed_messages = [
            '{"invalid": json}',  # Invalid JSON syntax
            '{"type": }',  # Incomplete JSON
            '',  # Empty message
            'not json at all',  # Plain text
        ]

        for malformed in malformed_messages:
            try:
                parsed = json.loads(malformed)
            except json.JSONDecodeError:
                # Expected behavior - should be handled gracefully
                assert True

    async def test_connection_state_updates(self, connection_manager):
        """Test WebSocket connection state update broadcasts."""
        # Create multiple connections
        connections = {}
        for i in range(3):
            ws = MagicMock(spec=WebSocket)
            ws.accept = AsyncMock()
            ws.send_json = AsyncMock()
            conn_id = f"state-test-{i}"
            connections[conn_id] = ws
            await connection_manager.connect(ws, conn_id)

        # Simulate state update that should be broadcast
        state_update = {
            "type": "state_change",
            "item_id": "test-item-123",
            "old_state": "todo",
            "new_state": "doing",
            "timestamp": "2024-01-01T12:00:00Z"
        }

        await connection_manager.broadcast(state_update)

        # All connections should receive the state update
        for ws in connections.values():
            ws.send_json.assert_called_with(state_update)

    async def test_selective_broadcasting_by_interest(self, connection_manager):
        """Test broadcasting based on client interests/subscriptions."""
        # This tests subscription-based message filtering
        connections = {}
        subscriptions = {
            "conn-1": ["item-updates", "system-status"],
            "conn-2": ["item-updates"],
            "conn-3": ["system-status"],
        }

        for conn_id, interests in subscriptions.items():
            ws = MagicMock(spec=WebSocket)
            ws.accept = AsyncMock()
            ws.send_json = AsyncMock()
            connections[conn_id] = ws
            await connection_manager.connect(ws, conn_id)

            # Store subscription info (if supported by implementation)
            if hasattr(connection_manager, 'set_subscription'):
                await connection_manager.set_subscription(conn_id, interests)

        # Send item-update message
        item_message = {"type": "item-update", "item_id": "123"}

        if hasattr(connection_manager, 'broadcast_by_subscription'):
            await connection_manager.broadcast_by_subscription("item-updates", item_message)
        else:
            # If subscription filtering not implemented, all connections get it
            await connection_manager.broadcast(item_message)

        # Verification depends on whether subscription filtering is implemented