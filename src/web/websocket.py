import json
import time
from collections import defaultdict, deque
from typing import Dict, List
from fastapi import WebSocket, HTTPException
from ..config import (
    WEBSOCKET_MAX_CONNECTIONS_PER_IP,
    WEBSOCKET_RATE_LIMIT_WINDOW,
    WEBSOCKET_MAX_CONNECTIONS_PER_WINDOW
)


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        # Track connections by IP address for rate limiting
        self.connections_by_ip: Dict[str, List[WebSocket]] = defaultdict(list)
        # Track connection attempts by IP with timestamps
        self.connection_attempts: Dict[str, deque] = defaultdict(lambda: deque())

    def _get_client_ip(self, websocket: WebSocket) -> str:
        """Get client IP address from WebSocket headers."""
        # Check for forwarded headers first (for reverse proxy scenarios)
        forwarded_for = websocket.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        # Check for real IP header
        real_ip = websocket.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

        # Fall back to direct client IP
        return websocket.client.host if websocket.client else "unknown"

    def _cleanup_old_attempts(self, client_ip: str):
        """Remove connection attempts older than the rate limit window."""
        current_time = time.time()
        cutoff_time = current_time - WEBSOCKET_RATE_LIMIT_WINDOW

        attempts = self.connection_attempts[client_ip]
        while attempts and attempts[0] < cutoff_time:
            attempts.popleft()

    def _is_rate_limited(self, client_ip: str) -> bool:
        """Check if client IP is rate limited."""
        self._cleanup_old_attempts(client_ip)

        # Check concurrent connection limit
        if len(self.connections_by_ip[client_ip]) >= WEBSOCKET_MAX_CONNECTIONS_PER_IP:
            return True

        # Check rate limit (connection attempts per window)
        if len(self.connection_attempts[client_ip]) >= WEBSOCKET_MAX_CONNECTIONS_PER_WINDOW:
            return True

        return False

    async def connect(self, websocket: WebSocket, client_ip: str = None):
        """Connect a WebSocket with rate limiting."""
        if client_ip is None:
            client_ip = self._get_client_ip(websocket)

        # Check rate limits before accepting
        if self._is_rate_limited(client_ip):
            await websocket.close(code=4008, reason="Rate limit exceeded")
            raise HTTPException(status_code=429, detail="Too many connections")

        # Record this connection attempt
        current_time = time.time()
        self.connection_attempts[client_ip].append(current_time)

        # Accept connection and track it
        await websocket.accept()
        self.active_connections.append(websocket)
        self.connections_by_ip[client_ip].append(websocket)

        # Store IP on websocket for cleanup
        websocket.client_ip = client_ip

    def disconnect(self, websocket: WebSocket):
        """Disconnect a WebSocket and clean up tracking."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

        # Clean up IP tracking
        client_ip = getattr(websocket, 'client_ip', None)
        if client_ip and client_ip in self.connections_by_ip:
            if websocket in self.connections_by_ip[client_ip]:
                self.connections_by_ip[client_ip].remove(websocket)

            # Clean up empty IP entries
            if not self.connections_by_ip[client_ip]:
                del self.connections_by_ip[client_ip]

    def get_connection_stats(self) -> dict:
        """Get current connection statistics for monitoring."""
        # Clean up old attempts for all IPs
        for ip in list(self.connection_attempts.keys()):
            self._cleanup_old_attempts(ip)
            # Remove empty attempt lists
            if not self.connection_attempts[ip]:
                del self.connection_attempts[ip]

        return {
            "total_connections": len(self.active_connections),
            "connections_by_ip": {
                ip: len(connections)
                for ip, connections in self.connections_by_ip.items()
            },
            "recent_attempts": {
                ip: len(attempts)
                for ip, attempts in self.connection_attempts.items()
            },
            "rate_limit_config": {
                "max_connections_per_ip": WEBSOCKET_MAX_CONNECTIONS_PER_IP,
                "rate_limit_window_seconds": WEBSOCKET_RATE_LIMIT_WINDOW,
                "max_attempts_per_window": WEBSOCKET_MAX_CONNECTIONS_PER_WINDOW
            }
        }

    async def broadcast(self, event_type: str, data: dict):
        message = json.dumps({"type": event_type, "data": data})
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                dead.append(connection)
        for conn in dead:
            self.active_connections.remove(conn)
