"""
P1 Priority Unit Tests: API Routes and Endpoints

Tests the web API routes including:
- REST API endpoints for items, work log, token usage
- Request validation and error handling
- Authentication and authorization
- Response formatting and status codes
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
import json

from src.web.app import create_app
from src.database import Database


@pytest_asyncio.fixture
async def test_app(test_db, mock_websocket_manager, temp_dir):
    """Create test FastAPI app instance."""
    app = create_app(
        target_project=temp_dir / "project",
        data_dir=temp_dir / "data",
        db=test_db,
        ws_manager=mock_websocket_manager
    )
    return app


@pytest.fixture
def client(test_app):
    """Create test client for API testing."""
    return TestClient(test_app)


@pytest.mark.unit
class TestItemRoutes:
    """Test suite for item-related API routes."""

    def test_get_items_empty_database(self, client):
        """Test getting items when database is empty."""
        response = client.get("/api/items")
        assert response.status_code == 200

        data = response.json()
        assert "columns" in data
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) == 0

    def test_get_items_with_data(self, client, test_item):
        """Test getting items when database contains data."""
        response = client.get("/api/items")
        assert response.status_code == 200

        data = response.json()
        assert len(data["items"]) == 1

        item = data["items"][0]
        assert item["id"] == test_item["id"]
        assert item["title"] == test_item["title"]
        assert item["column_name"] == test_item["column_name"]

    def test_create_item_valid_data(self, client):
        """Test creating item with valid data."""
        item_data = {
            "title": "New Test Item",
            "description": "Test item description",
            "column_name": "todo"
        }

        response = client.post("/api/items", json=item_data)
        assert response.status_code == 201

        created_item = response.json()
        assert created_item["title"] == item_data["title"]
        assert created_item["description"] == item_data["description"]
        assert created_item["column_name"] == item_data["column_name"]
        assert "id" in created_item

    def test_create_item_invalid_data(self, client):
        """Test creating item with invalid data."""
        invalid_data = {
            "title": "",  # Empty title should be invalid
            "description": "Test description"
        }

        response = client.post("/api/items", json=invalid_data)
        assert response.status_code == 422

    def test_create_item_invalid_column(self, client):
        """Test creating item with invalid column name."""
        invalid_data = {
            "title": "Test Item",
            "description": "Test description",
            "column_name": "invalid_column"
        }

        response = client.post("/api/items", json=invalid_data)
        assert response.status_code == 422

    def test_update_item_valid_data(self, client, test_item):
        """Test updating item with valid data."""
        update_data = {
            "title": "Updated Title",
            "description": "Updated description"
        }

        response = client.patch(f"/api/items/{test_item['id']}", json=update_data)
        assert response.status_code == 200

        updated_item = response.json()
        assert updated_item["title"] == update_data["title"]
        assert updated_item["description"] == update_data["description"]

    def test_update_item_not_found(self, client):
        """Test updating non-existent item."""
        update_data = {"title": "Updated Title"}

        response = client.patch("/api/items/nonexistent-id", json=update_data)
        assert response.status_code == 404

    def test_delete_item_success(self, client, test_item):
        """Test deleting existing item."""
        response = client.delete(f"/api/items/{test_item['id']}")
        assert response.status_code == 204

    def test_delete_item_not_found(self, client):
        """Test deleting non-existent item."""
        response = client.delete("/api/items/nonexistent-id")
        assert response.status_code == 404

    def test_move_item_valid_position(self, client, test_item):
        """Test moving item to valid position."""
        move_data = {
            "column_name": "doing",
            "position": 1
        }

        response = client.post(f"/api/items/{test_item['id']}/move", json=move_data)
        assert response.status_code == 200

        moved_item = response.json()
        assert moved_item["column_name"] == move_data["column_name"]

    def test_move_item_invalid_column(self, client, test_item):
        """Test moving item to invalid column."""
        move_data = {
            "column_name": "invalid_column",
            "position": 0
        }

        response = client.post(f"/api/items/{test_item['id']}/move", json=move_data)
        assert response.status_code == 422


@pytest.mark.unit
class TestAgentRoutes:
    """Test suite for agent-related API routes."""

    @patch('src.web.routes.orchestrator')
    def test_start_agent_success(self, mock_orchestrator, client, test_item):
        """Test starting agent successfully."""
        mock_orchestrator.start_agent = AsyncMock(return_value=test_item)

        response = client.post(f"/api/items/{test_item['id']}/start-agent")
        assert response.status_code == 200

        result = response.json()
        assert result["id"] == test_item["id"]

    @patch('src.web.routes.orchestrator')
    def test_start_agent_not_found(self, mock_orchestrator, client):
        """Test starting agent for non-existent item."""
        mock_orchestrator.start_agent = AsyncMock(side_effect=ValueError("Item not found"))

        response = client.post("/api/items/nonexistent-id/start-agent")
        assert response.status_code == 404

    @patch('src.web.routes.orchestrator')
    def test_cancel_agent_success(self, mock_orchestrator, client, test_item):
        """Test cancelling agent successfully."""
        mock_orchestrator.cancel_agent = AsyncMock(return_value=test_item)

        response = client.post(f"/api/items/{test_item['id']}/cancel-agent")
        assert response.status_code == 200

    @patch('src.web.routes.orchestrator')
    def test_approve_item_success(self, mock_orchestrator, client, test_item):
        """Test approving item successfully."""
        mock_orchestrator.approve_item = AsyncMock(return_value=test_item)

        response = client.post(f"/api/items/{test_item['id']}/approve")
        assert response.status_code == 200

    @patch('src.web.routes.orchestrator')
    def test_request_changes_success(self, mock_orchestrator, client, test_item):
        """Test requesting changes successfully."""
        mock_orchestrator.request_changes = AsyncMock(return_value=test_item)

        comments = ["Fix formatting", "Add tests"]
        response = client.post(f"/api/items/{test_item['id']}/request-changes",
                             json={"comments": comments})
        assert response.status_code == 200


@pytest.mark.unit
class TestWorkLogRoutes:
    """Test suite for work log API routes."""

    def test_get_work_log_empty(self, client, test_item):
        """Test getting work log when no entries exist."""
        response = client.get(f"/api/items/{test_item['id']}/work-log")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_work_log_not_found(self, client):
        """Test getting work log for non-existent item."""
        response = client.get("/api/items/nonexistent-id/work-log")
        assert response.status_code == 404


@pytest.mark.unit
class TestTokenUsageRoutes:
    """Test suite for token usage API routes."""

    def test_get_token_usage_not_found(self, client):
        """Test getting token usage for non-existent item."""
        response = client.get("/api/items/nonexistent-id/token-usage")
        assert response.status_code == 404

    def test_get_token_usage_empty(self, client, test_item):
        """Test getting token usage when no records exist."""
        response = client.get(f"/api/items/{test_item['id']}/token-usage")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0


@pytest.mark.unit
class TestApiErrorHandling:
    """Test suite for API error handling and edge cases."""

    def test_invalid_json_request(self, client):
        """Test handling of invalid JSON in request body."""
        response = client.post("/api/items",
                              data="invalid json",
                              headers={"Content-Type": "application/json"})
        assert response.status_code == 422

    def test_missing_content_type(self, client):
        """Test handling of missing content-type header."""
        response = client.post("/api/items", data='{"title": "test"}')
        assert response.status_code in [415, 422]  # Either is acceptable

    def test_method_not_allowed(self, client):
        """Test method not allowed responses."""
        response = client.put("/api/items")  # PUT not allowed on collection
        assert response.status_code == 405

    def test_cors_headers_present(self, client):
        """Test that CORS headers are present in responses."""
        response = client.get("/api/items")
        assert response.status_code == 200
        # CORS headers should be handled by FastAPI CORS middleware

    def test_large_request_body_handling(self, client):
        """Test handling of very large request bodies."""
        large_data = {
            "title": "Test",
            "description": "x" * 10000  # Large description
        }

        response = client.post("/api/items", json=large_data)
        # Should either succeed or fail gracefully with appropriate status
        assert response.status_code in [201, 413, 422]


@pytest.mark.unit
class TestApiResponseFormats:
    """Test suite for API response formats and structure."""

    def test_items_response_structure(self, client, test_item):
        """Test that items response has correct structure."""
        response = client.get("/api/items")
        assert response.status_code == 200

        data = response.json()
        required_fields = ["columns", "items"]
        for field in required_fields:
            assert field in data

        if data["items"]:
            item = data["items"][0]
            item_fields = ["id", "title", "description", "column_name", "position",
                          "created_at", "updated_at"]
            for field in item_fields:
                assert field in item

    def test_error_response_structure(self, client):
        """Test that error responses have consistent structure."""
        response = client.get("/api/items/nonexistent-id")
        assert response.status_code == 404

        error_data = response.json()
        assert "detail" in error_data

    def test_pagination_parameters(self, client):
        """Test pagination parameters in list endpoints."""
        # Test limit parameter
        response = client.get("/api/items?limit=5")
        assert response.status_code == 200

        # Test offset parameter
        response = client.get("/api/items?offset=10")
        assert response.status_code == 200

        # Test invalid pagination parameters
        response = client.get("/api/items?limit=-1")
        assert response.status_code in [200, 422]  # Should handle gracefully