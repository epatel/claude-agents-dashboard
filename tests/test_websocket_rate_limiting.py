import pytest
import asyncio
from unittest.mock import Mock
from fastapi import HTTPException

from src.web.websocket import ConnectionManager
from src.config import (
    WEBSOCKET_MAX_CONNECTIONS_PER_IP,
    WEBSOCKET_RATE_LIMIT_WINDOW,
    WEBSOCKET_MAX_CONNECTIONS_PER_WINDOW
)


@pytest.fixture
def manager():
    return ConnectionManager()


@pytest.fixture
def mock_websocket():
    websocket = Mock()
    websocket.client.host = "192.168.1.1"
    websocket.headers = {}
    websocket.accept = asyncio.coroutine(lambda: None)()
    websocket.close = asyncio.coroutine(lambda code=None, reason=None: None)()
    return websocket


class TestConnectionManager:
    def test_get_client_ip_direct(self, manager, mock_websocket):
        """Test getting client IP from direct connection."""
        mock_websocket.client.host = "192.168.1.100"
        ip = manager._get_client_ip(mock_websocket)
        assert ip == "192.168.1.100"

    def test_get_client_ip_forwarded(self, manager, mock_websocket):
        """Test getting client IP from X-Forwarded-For header."""
        mock_websocket.headers = {"x-forwarded-for": "10.0.0.1, 192.168.1.1"}
        ip = manager._get_client_ip(mock_websocket)
        assert ip == "10.0.0.1"

    def test_get_client_ip_real_ip(self, manager, mock_websocket):
        """Test getting client IP from X-Real-IP header."""
        mock_websocket.headers = {"x-real-ip": "10.0.0.2"}
        ip = manager._get_client_ip(mock_websocket)
        assert ip == "10.0.0.2"

    @pytest.mark.asyncio
    async def test_connection_tracking(self, manager, mock_websocket):
        """Test that connections are properly tracked by IP."""
        client_ip = "192.168.1.1"

        # Connect websocket
        await manager.connect(mock_websocket, client_ip)

        # Verify tracking
        assert len(manager.active_connections) == 1
        assert len(manager.connections_by_ip[client_ip]) == 1
        assert mock_websocket in manager.active_connections
        assert mock_websocket in manager.connections_by_ip[client_ip]

    @pytest.mark.asyncio
    async def test_connection_limit_per_ip(self, manager):
        """Test that connection limit per IP is enforced."""
        client_ip = "192.168.1.1"

        # Create multiple mock websockets from same IP
        websockets = []
        for i in range(WEBSOCKET_MAX_CONNECTIONS_PER_IP):
            ws = Mock()
            ws.client.host = client_ip
            ws.headers = {}
            ws.accept = asyncio.coroutine(lambda: None)()
            ws.close = asyncio.coroutine(lambda code=None, reason=None: None)()

            await manager.connect(ws, client_ip)
            websockets.append(ws)

        # Try to connect one more - should be rate limited
        extra_ws = Mock()
        extra_ws.client.host = client_ip
        extra_ws.headers = {}
        extra_ws.accept = asyncio.coroutine(lambda: None)()
        extra_ws.close = asyncio.coroutine(lambda code=None, reason=None: None)()

        with pytest.raises(HTTPException) as exc_info:
            await manager.connect(extra_ws, client_ip)

        assert exc_info.value.status_code == 429
        assert "Too many connections" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_rate_limit_per_window(self, manager):
        """Test that rate limit per window is enforced."""
        client_ip = "192.168.1.2"

        # Rapidly connect and disconnect to exceed rate limit
        for i in range(WEBSOCKET_MAX_CONNECTIONS_PER_WINDOW):
            ws = Mock()
            ws.client.host = client_ip
            ws.headers = {}
            ws.accept = asyncio.coroutine(lambda: None)()
            ws.close = asyncio.coroutine(lambda code=None, reason=None: None)()

            await manager.connect(ws, client_ip)
            manager.disconnect(ws)

        # Try one more connection - should be rate limited
        extra_ws = Mock()
        extra_ws.client.host = client_ip
        extra_ws.headers = {}
        extra_ws.accept = asyncio.coroutine(lambda: None)()
        extra_ws.close = asyncio.coroutine(lambda code=None, reason=None: None)()

        with pytest.raises(HTTPException) as exc_info:
            await manager.connect(extra_ws, client_ip)

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_disconnect_cleanup(self, manager, mock_websocket):
        """Test that disconnect properly cleans up tracking."""
        client_ip = "192.168.1.1"

        # Connect websocket
        await manager.connect(mock_websocket, client_ip)

        # Verify it's tracked
        assert len(manager.active_connections) == 1
        assert len(manager.connections_by_ip[client_ip]) == 1

        # Disconnect
        manager.disconnect(mock_websocket)

        # Verify cleanup
        assert len(manager.active_connections) == 0
        assert client_ip not in manager.connections_by_ip  # Should be cleaned up

    def test_connection_stats(self, manager):
        """Test connection statistics reporting."""
        stats = manager.get_connection_stats()

        assert "total_connections" in stats
        assert "connections_by_ip" in stats
        assert "recent_attempts" in stats
        assert "rate_limit_config" in stats

        config = stats["rate_limit_config"]
        assert config["max_connections_per_ip"] == WEBSOCKET_MAX_CONNECTIONS_PER_IP
        assert config["rate_limit_window_seconds"] == WEBSOCKET_RATE_LIMIT_WINDOW
        assert config["max_attempts_per_window"] == WEBSOCKET_MAX_CONNECTIONS_PER_WINDOW