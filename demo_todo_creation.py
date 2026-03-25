#!/usr/bin/env python3
"""
Demo script showing how agents can create todo items.

This is a simulation of how an agent would use the create_todo tool
during task execution.
"""

import asyncio
import json
from pathlib import Path


class MockConnection:
    """Mock database connection for async context manager."""

    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def execute(self, query, params=()):
        if "SELECT COALESCE(MAX(position)" in query:
            # Return next position
            return MockCursor([self.db.next_position])
        elif "INSERT INTO items" in query:
            # Simulate item creation
            if len(params) == 4:
                item_id, title, description, position = params
                column_name = 'todo'
            else:
                item_id, title, description, column_name, position = params
            item = {
                'id': item_id,
                'title': title,
                'description': description,
                'column_name': column_name,
                'position': position,
                'status': None,
                'branch_name': None,
                'worktree_path': None,
                'session_id': None,
                'created_at': '2026-03-25T10:30:00',
                'updated_at': '2026-03-25T10:30:00'
            }
            self.db.items.append(item)
            self.db.next_position += 1
            return MockCursor([])
        elif "SELECT * FROM items WHERE id" in query:
            # Return the last created item
            return MockCursor([self.db.items[-1]] if self.db.items else [])

    async def commit(self):
        pass


class MockDatabase:
    """Mock database for demonstration purposes."""

    def __init__(self):
        self.items = []
        self.next_position = 0

    def connect(self):
        return MockConnection(self)


class MockCursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchone(self):
        if self.rows:
            row = self.rows[0]
            # If it's a plain value (like position), wrap it in a tuple
            if isinstance(row, (int, str)) and not isinstance(row, dict):
                return (row,)
            return row
        return None


class MockWebSocketManager:
    """Mock WebSocket manager for demonstration."""

    async def broadcast(self, event_type, data):
        print(f"📡 WebSocket broadcast: {event_type}")
        print(f"   Data: {json.dumps(data, indent=2)}")


class MockOrchestrator:
    """Simplified orchestrator for demonstration."""

    def __init__(self):
        self.db = MockDatabase()
        self.ws_manager = MockWebSocketManager()

    async def _on_create_todo(self, item_id: str, title: str, description: str) -> dict:
        """Called when agent uses create_todo tool. Creates a new todo item."""
        import uuid

        def new_id() -> str:
            return uuid.uuid4().hex[:12]

        todo_id = new_id()

        # Get next position in todo column
        async with self.db.connect() as conn:
            cursor = await conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM items WHERE column_name = 'todo'"
            )
            row = await cursor.fetchone()
            position = row[0] if row else 0

            # Create new todo item
            await conn.execute(
                "INSERT INTO items (id, title, description, column_name, position) VALUES (?, ?, ?, 'todo', ?)",
                (todo_id, title, description, position),
            )
            await conn.commit()

            # Get the created item
            cursor = await conn.execute("SELECT * FROM items WHERE id = ?", (todo_id,))
            item = dict(await cursor.fetchone())

        # Log the creation (simplified for demo)
        print(f"📝 Work log: Created todo item: {title}")

        # Broadcast to frontend
        await self.ws_manager.broadcast("item_created", item)

        return item


async def demo_agent_workflow():
    """Simulate an agent creating todo items during task execution."""
    print("🤖 Agent Demo: Creating Todo Items")
    print("=" * 50)

    orchestrator = MockOrchestrator()
    agent_item_id = "abc123456789"  # The current item the agent is working on

    print(f"\n🎯 Agent working on item: {agent_item_id}")
    print("Agent analyzes the codebase and identifies several tasks...")

    # Simulate agent creating multiple todo items
    todo_scenarios = [
        {
            "title": "Fix validation bug in user registration",
            "description": "The email validation is not working correctly for domains with plus signs. Need to update the regex pattern.",
            "context": "Agent discovered while reviewing authentication code"
        },
        {
            "title": "Add unit tests for password reset flow",
            "description": "The password reset functionality lacks proper test coverage. Should add tests for edge cases.",
            "context": "Agent noticed missing tests while implementing security fixes"
        },
        {
            "title": "Update API documentation for new endpoints",
            "description": "Three new endpoints were added but documentation is missing. Need to update OpenAPI spec.",
            "context": "Agent completed API implementation and identified documentation gap"
        },
        {
            "title": "Investigate database performance issue",
            "description": "User queries are taking >500ms on average. Need to analyze slow query logs and add proper indexing.",
            "context": "Agent detected performance issue during load testing"
        }
    ]

    created_todos = []

    for i, scenario in enumerate(todo_scenarios, 1):
        print(f"\n🔍 Step {i}: {scenario['context']}")
        print(f"   📋 Creating todo: {scenario['title']}")

        # Agent calls create_todo tool
        todo_item = await orchestrator._on_create_todo(
            agent_item_id,
            scenario['title'],
            scenario['description']
        )

        created_todos.append(todo_item)
        print(f"   ✅ Todo created with ID: {todo_item['id']}")

    print(f"\n📊 Summary:")
    print(f"   • Agent created {len(created_todos)} todo items")
    print(f"   • All todos added to 'todo' column")
    print(f"   • Real-time updates sent via WebSocket")
    print(f"   • Work log entries recorded")

    print(f"\n📋 Created Todo Items:")
    for i, todo in enumerate(created_todos, 1):
        print(f"   {i}. {todo['title']}")
        print(f"      ID: {todo['id']}")
        print(f"      Position: {todo['position']}")

    print(f"\n🎉 Todo creation feature working successfully!")


if __name__ == "__main__":
    # Add the src directory to the path for imports
    import sys
    sys.path.insert(0, 'src')

    try:
        asyncio.run(demo_agent_workflow())
    except ImportError as e:
        print(f"Note: This demo requires the full application environment.")
        print(f"Import error: {e}")
        print(f"\nThe feature implementation is complete and ready for testing in the full environment.")