"""Unit tests for src/web/websocket.py ConnectionManager."""

import json
import time
import pytest
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

from src.web.websocket import ConnectionManager


def make_websocket(host="1.2.3.4", forwarded_for=None, real_ip=None):
    """Create a mock WebSocket with configurable headers and client."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()

    # Build headers dict
    headers = {}
    if forwarded_for:
        headers["x-forwarded-for"] = forwarded_for
    if real_ip:
        headers["x-real-ip"] = real_ip
    ws.headers = headers

    # client.host
    if host is not None:
        ws.client = MagicMock()
        ws.client.host = host
    else:
        ws.client = None

    return ws


# ---------------------------------------------------------------------------
# _get_client_ip
# ---------------------------------------------------------------------------

class TestGetClientIp:
    def setup_method(self):
        self.mgr = ConnectionManager()

    def test_returns_x_forwarded_for_first_ip(self):
        ws = make_websocket(forwarded_for="10.0.0.1, 192.168.1.1")
        assert self.mgr._get_client_ip(ws) == "10.0.0.1"

    def test_strips_whitespace_from_forwarded_for(self):
        ws = make_websocket(forwarded_for="  10.0.0.2 , 192.168.1.1")
        assert self.mgr._get_client_ip(ws) == "10.0.0.2"

    def test_returns_x_real_ip_when_no_forwarded_for(self):
        ws = make_websocket(real_ip="10.0.0.3")
        assert self.mgr._get_client_ip(ws) == "10.0.0.3"

    def test_strips_whitespace_from_real_ip(self):
        ws = make_websocket(real_ip="  10.0.0.4  ")
        assert self.mgr._get_client_ip(ws) == "10.0.0.4"

    def test_falls_back_to_client_host(self):
        ws = make_websocket(host="5.6.7.8")
        assert self.mgr._get_client_ip(ws) == "5.6.7.8"

    def test_returns_unknown_when_client_is_none(self):
        ws = make_websocket(host=None)
        assert self.mgr._get_client_ip(ws) == "unknown"

    def test_x_forwarded_for_takes_priority_over_real_ip(self):
        ws = make_websocket(forwarded_for="10.0.0.1", real_ip="10.0.0.2")
        assert self.mgr._get_client_ip(ws) == "10.0.0.1"

    def test_x_real_ip_takes_priority_over_client_host(self):
        ws = make_websocket(host="5.6.7.8", real_ip="10.0.0.2")
        assert self.mgr._get_client_ip(ws) == "10.0.0.2"


# ---------------------------------------------------------------------------
# _cleanup_old_attempts
# ---------------------------------------------------------------------------

class TestCleanupOldAttempts:
    def setup_method(self):
        self.mgr = ConnectionManager()

    def test_removes_attempts_older_than_window(self):
        ip = "1.2.3.4"
        old_time = time.time() - 9999
        self.mgr.connection_attempts[ip].append(old_time)
        self.mgr._cleanup_old_attempts(ip)
        assert len(self.mgr.connection_attempts[ip]) == 0

    def test_keeps_recent_attempts(self):
        ip = "1.2.3.4"
        recent = time.time()
        self.mgr.connection_attempts[ip].append(recent)
        self.mgr._cleanup_old_attempts(ip)
        assert len(self.mgr.connection_attempts[ip]) == 1

    def test_removes_only_old_entries(self):
        ip = "1.2.3.4"
        old = time.time() - 9999
        recent = time.time()
        self.mgr.connection_attempts[ip].extend([old, recent])
        self.mgr._cleanup_old_attempts(ip)
        assert len(self.mgr.connection_attempts[ip]) == 1
        assert self.mgr.connection_attempts[ip][0] == recent

    def test_no_error_on_empty_deque(self):
        self.mgr._cleanup_old_attempts("9.9.9.9")  # should not raise


# ---------------------------------------------------------------------------
# _is_rate_limited
# ---------------------------------------------------------------------------

class TestIsRateLimited:
    def setup_method(self):
        self.mgr = ConnectionManager()

    def test_not_rate_limited_when_empty(self):
        assert self.mgr._is_rate_limited("1.2.3.4") is False

    @patch("src.web.websocket.WEBSOCKET_MAX_CONNECTIONS_PER_IP", 2)
    def test_rate_limited_when_too_many_concurrent(self):
        ip = "1.2.3.4"
        self.mgr.connections_by_ip[ip] = [MagicMock(), MagicMock()]
        assert self.mgr._is_rate_limited(ip) is True

    @patch("src.web.websocket.WEBSOCKET_MAX_CONNECTIONS_PER_WINDOW", 2)
    def test_rate_limited_when_too_many_attempts_in_window(self):
        ip = "1.2.3.4"
        now = time.time()
        self.mgr.connection_attempts[ip].extend([now, now])
        assert self.mgr._is_rate_limited(ip) is True

    @patch("src.web.websocket.WEBSOCKET_MAX_CONNECTIONS_PER_IP", 5)
    @patch("src.web.websocket.WEBSOCKET_MAX_CONNECTIONS_PER_WINDOW", 10)
    def test_not_rate_limited_below_thresholds(self):
        ip = "1.2.3.4"
        self.mgr.connections_by_ip[ip] = [MagicMock()]
        self.mgr.connection_attempts[ip].append(time.time())
        assert self.mgr._is_rate_limited(ip) is False


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------

class TestConnect:
    def setup_method(self):
        self.mgr = ConnectionManager()

    @pytest.mark.asyncio
    async def test_connect_accepts_websocket(self):
        ws = make_websocket()
        await self.mgr.connect(ws)
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_adds_to_active_connections(self):
        ws = make_websocket()
        await self.mgr.connect(ws)
        assert ws in self.mgr.active_connections

    @pytest.mark.asyncio
    async def test_connect_tracks_by_ip(self):
        ws = make_websocket(host="1.2.3.4")
        await self.mgr.connect(ws)
        assert ws in self.mgr.connections_by_ip["1.2.3.4"]

    @pytest.mark.asyncio
    async def test_connect_records_attempt_timestamp(self):
        ws = make_websocket(host="1.2.3.4")
        before = time.time()
        await self.mgr.connect(ws)
        after = time.time()
        attempts = self.mgr.connection_attempts["1.2.3.4"]
        assert len(attempts) == 1
        assert before <= attempts[0] <= after

    @pytest.mark.asyncio
    async def test_connect_stores_client_ip_on_websocket(self):
        ws = make_websocket(host="1.2.3.4")
        await self.mgr.connect(ws)
        assert ws.client_ip == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_connect_uses_provided_client_ip(self):
        ws = make_websocket(host="1.2.3.4")
        await self.mgr.connect(ws, client_ip="9.9.9.9")
        assert ws.client_ip == "9.9.9.9"
        assert ws in self.mgr.connections_by_ip["9.9.9.9"]

    @pytest.mark.asyncio
    @patch("src.web.websocket.WEBSOCKET_MAX_CONNECTIONS_PER_IP", 1)
    async def test_connect_rate_limited_closes_and_raises(self):
        from fastapi import HTTPException
        ws1 = make_websocket(host="1.2.3.4")
        ws2 = make_websocket(host="1.2.3.4")
        await self.mgr.connect(ws1)
        with pytest.raises(HTTPException) as exc_info:
            await self.mgr.connect(ws2)
        assert exc_info.value.status_code == 429
        ws2.close.assert_awaited_once_with(code=4008, reason="Rate limit exceeded")

    @pytest.mark.asyncio
    async def test_connect_multiple_clients_different_ips(self):
        ws1 = make_websocket(host="1.2.3.4")
        ws2 = make_websocket(host="5.6.7.8")
        await self.mgr.connect(ws1)
        await self.mgr.connect(ws2)
        assert len(self.mgr.active_connections) == 2
        assert ws1 in self.mgr.connections_by_ip["1.2.3.4"]
        assert ws2 in self.mgr.connections_by_ip["5.6.7.8"]

    @pytest.mark.asyncio
    async def test_connect_uses_forwarded_for_header(self):
        ws = make_websocket(host="10.0.0.1", forwarded_for="203.0.113.5")
        await self.mgr.connect(ws)
        assert ws.client_ip == "203.0.113.5"
        assert ws in self.mgr.connections_by_ip["203.0.113.5"]


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------

class TestDisconnect:
    def setup_method(self):
        self.mgr = ConnectionManager()

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_active(self):
        ws = make_websocket()
        await self.mgr.connect(ws)
        self.mgr.disconnect(ws)
        assert ws not in self.mgr.active_connections

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_connections_by_ip(self):
        ws = make_websocket(host="1.2.3.4")
        await self.mgr.connect(ws)
        self.mgr.disconnect(ws)
        assert "1.2.3.4" not in self.mgr.connections_by_ip

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up_empty_ip_entry(self):
        ws = make_websocket(host="1.2.3.4")
        await self.mgr.connect(ws)
        self.mgr.disconnect(ws)
        assert "1.2.3.4" not in self.mgr.connections_by_ip

    @pytest.mark.asyncio
    async def test_disconnect_leaves_other_connections_from_same_ip(self):
        ws1 = make_websocket(host="1.2.3.4")
        ws2 = make_websocket(host="1.2.3.4")
        await self.mgr.connect(ws1)
        await self.mgr.connect(ws2)
        self.mgr.disconnect(ws1)
        assert ws2 in self.mgr.connections_by_ip["1.2.3.4"]
        assert "1.2.3.4" in self.mgr.connections_by_ip

    def test_disconnect_unknown_websocket_no_error(self):
        ws = make_websocket()
        self.mgr.disconnect(ws)  # should not raise

    def test_disconnect_without_client_ip_attr_no_error(self):
        ws = make_websocket()
        # No client_ip set on ws (not connected via connect())
        self.mgr.active_connections.append(ws)
        self.mgr.disconnect(ws)  # should not raise

    @pytest.mark.asyncio
    async def test_disconnect_twice_no_error(self):
        ws = make_websocket(host="1.2.3.4")
        await self.mgr.connect(ws)
        self.mgr.disconnect(ws)
        self.mgr.disconnect(ws)  # second call should not raise


# ---------------------------------------------------------------------------
# broadcast
# ---------------------------------------------------------------------------

class TestBroadcast:
    def setup_method(self):
        self.mgr = ConnectionManager()

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_connections(self):
        ws1 = make_websocket(host="1.2.3.4")
        ws2 = make_websocket(host="5.6.7.8")
        await self.mgr.connect(ws1)
        await self.mgr.connect(ws2)
        await self.mgr.broadcast("test_event", {"key": "value"})
        expected = json.dumps({"type": "test_event", "data": {"key": "value"}})
        ws1.send_text.assert_awaited_once_with(expected)
        ws2.send_text.assert_awaited_once_with(expected)

    @pytest.mark.asyncio
    async def test_broadcast_with_no_connections(self):
        await self.mgr.broadcast("test_event", {})  # should not raise

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self):
        ws1 = make_websocket(host="1.2.3.4")
        ws2 = make_websocket(host="5.6.7.8")
        await self.mgr.connect(ws1)
        await self.mgr.connect(ws2)
        # Make ws1 raise on send
        ws1.send_text.side_effect = Exception("connection broken")
        await self.mgr.broadcast("test_event", {})
        assert ws1 not in self.mgr.active_connections
        assert ws2 in self.mgr.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_continues_after_dead_connection(self):
        ws1 = make_websocket(host="1.2.3.4")
        ws2 = make_websocket(host="5.6.7.8")
        await self.mgr.connect(ws1)
        await self.mgr.connect(ws2)
        ws1.send_text.side_effect = Exception("broken")
        await self.mgr.broadcast("test_event", {"a": 1})
        expected = json.dumps({"type": "test_event", "data": {"a": 1}})
        ws2.send_text.assert_awaited_once_with(expected)

    @pytest.mark.asyncio
    async def test_broadcast_message_format(self):
        ws = make_websocket()
        await self.mgr.connect(ws)
        await self.mgr.broadcast("my_event", {"x": 42})
        call_args = ws.send_text.call_args[0][0]
        parsed = json.loads(call_args)
        assert parsed["type"] == "my_event"
        assert parsed["data"] == {"x": 42}

    @pytest.mark.asyncio
    async def test_broadcast_all_dead_clears_active_connections(self):
        ws1 = make_websocket(host="1.2.3.4")
        ws2 = make_websocket(host="5.6.7.8")
        await self.mgr.connect(ws1)
        await self.mgr.connect(ws2)
        ws1.send_text.side_effect = Exception("broken")
        ws2.send_text.side_effect = Exception("broken")
        await self.mgr.broadcast("event", {})
        assert len(self.mgr.active_connections) == 0


# ---------------------------------------------------------------------------
# get_connection_stats
# ---------------------------------------------------------------------------

class TestGetConnectionStats:
    def setup_method(self):
        self.mgr = ConnectionManager()

    def test_stats_empty_manager(self):
        stats = self.mgr.get_connection_stats()
        assert stats["total_connections"] == 0
        assert stats["connections_by_ip"] == {}
        assert stats["recent_attempts"] == {}
        assert "rate_limit_config" in stats

    @pytest.mark.asyncio
    async def test_stats_total_connections(self):
        ws1 = make_websocket(host="1.2.3.4")
        ws2 = make_websocket(host="5.6.7.8")
        await self.mgr.connect(ws1)
        await self.mgr.connect(ws2)
        stats = self.mgr.get_connection_stats()
        assert stats["total_connections"] == 2

    @pytest.mark.asyncio
    async def test_stats_connections_by_ip(self):
        ws1 = make_websocket(host="1.2.3.4")
        ws2 = make_websocket(host="1.2.3.4")
        ws3 = make_websocket(host="5.6.7.8")
        await self.mgr.connect(ws1)
        await self.mgr.connect(ws2)
        await self.mgr.connect(ws3)
        stats = self.mgr.get_connection_stats()
        assert stats["connections_by_ip"]["1.2.3.4"] == 2
        assert stats["connections_by_ip"]["5.6.7.8"] == 1

    @pytest.mark.asyncio
    async def test_stats_recent_attempts(self):
        ws = make_websocket(host="1.2.3.4")
        await self.mgr.connect(ws)
        stats = self.mgr.get_connection_stats()
        assert stats["recent_attempts"]["1.2.3.4"] == 1

    def test_stats_rate_limit_config_keys(self):
        stats = self.mgr.get_connection_stats()
        config = stats["rate_limit_config"]
        assert "max_connections_per_ip" in config
        assert "rate_limit_window_seconds" in config
        assert "max_attempts_per_window" in config

    def test_stats_cleans_up_old_attempts(self):
        ip = "1.2.3.4"
        old = time.time() - 9999
        self.mgr.connection_attempts[ip].append(old)
        stats = self.mgr.get_connection_stats()
        # Old attempt removed, key cleaned up
        assert ip not in stats["recent_attempts"]

    @pytest.mark.asyncio
    async def test_stats_after_disconnect(self):
        ws = make_websocket(host="1.2.3.4")
        await self.mgr.connect(ws)
        self.mgr.disconnect(ws)
        stats = self.mgr.get_connection_stats()
        assert stats["total_connections"] == 0
        assert stats["connections_by_ip"] == {}
