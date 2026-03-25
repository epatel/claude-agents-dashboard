# Todo Creation Feature for Agents

## Overview
This feature allows agents to create new todo items while working on their assigned tasks. Agents can break down complex work into smaller actionable items, create follow-up tasks, or note issues that need attention.

## Implementation Details

### New Files Added
- **`src/agent/todo.py`**: MCP tool for todo creation following the same pattern as clarification

### Modified Files
- **`src/agent/orchestrator.py`**: Added `_on_create_todo` callback and integrated todo server
- **`src/agent/session.py`**: Added `on_create_todo` parameter and todo MCP server integration

## How It Works

### 1. Agent Tool Usage
Agents can now use the `create_todo` tool:
```python
{
    "title": "Fix validation bug in user registration",
    "description": "The email validation is not working correctly for domains with plus signs"
}
```

### 2. Database Integration
- New todos are automatically inserted into the `items` table
- Positioned at the end of the "todo" column
- Get unique 12-character hex IDs
- Follow the same data structure as manually created items

### 3. Real-time Updates
- WebSocket broadcast of `item_created` event
- Frontend automatically updates the kanban board
- Work log entries show when agents create todos

### 4. Tool Logging
- Appears in work log as "**Create Todo** {title}"
- Full tool input stored as JSON metadata
- System log entry: "Created todo item: {title}"

## Usage Examples

### When Agents Should Use This Tool
1. **Breaking down complex tasks**: "Create todo for database migration after fixing this API issue"
2. **Follow-up work**: "Create todo to add tests for the new validation function"
3. **Discovered issues**: "Create todo to investigate performance issue in data processing"
4. **Documentation**: "Create todo to update API documentation with new endpoints"

### Integration with Existing Workflow
- Created todos appear in the "Todo" column like any other item
- Can be assigned to other agents or handled manually
- Support all existing features (drag-drop, editing, agent assignment)
- Maintain full audit trail through work logs

## Technical Architecture

### MCP Tool Schema
```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "description": "The title of the todo item. Should be clear and concise."
    },
    "description": {
      "type": "string",
      "description": "Optional detailed description of the todo item."
    }
  },
  "required": ["title"]
}
```

### Callback Chain
1. Agent calls `create_todo` MCP tool
2. Todo server calls `on_create_todo` callback
3. Orchestrator's `_on_create_todo` method:
   - Generates new item ID
   - Calculates next position in todo column
   - Inserts into database
   - Logs the creation
   - Broadcasts WebSocket event
4. Returns item info to agent

### Database Operations
```sql
-- Get next position
SELECT COALESCE(MAX(position), -1) + 1 FROM items WHERE column_name = 'todo'

-- Create new item
INSERT INTO items (id, title, description, column_name, position)
VALUES (?, ?, ?, 'todo', ?)
```

## Testing Instructions

1. **Start the dashboard**: Run the development server
2. **Create a test item**: Add any task to start an agent
3. **Agent usage**: The agent can now call `create_todo` when needed
4. **Verify**: Check that new todos appear in the Todo column
5. **Check logs**: Verify work log shows todo creation events

## Future Enhancements

### Potential Extensions
1. **Hierarchical todos**: Parent-child relationships between items
2. **Tag assignment**: Automatically tag created todos
3. **Priority setting**: Allow agents to set priority levels
4. **Assignee suggestion**: AI-powered assignee recommendations
5. **Template todos**: Pre-defined todo templates for common patterns

### Integration Points
- Could integrate with external issue tracking (GitHub Issues, Jira)
- Export capabilities for project management tools
- Bulk operations for managing agent-created todos

## Security Considerations

### Access Control
- Agents can only create todos, not modify existing ones
- No elevation of privileges required
- Standard database permissions apply
- Audit trail maintained in work logs

### Rate Limiting
- Consider adding limits on todo creation frequency
- Monitor for excessive todo generation
- Implement cleanup for stale agent-created todos

## Backward Compatibility

This feature is fully backward compatible:
- Existing agents continue to work without changes
- No database schema modifications required
- Optional feature - agents work fine without using it
- No impact on existing todo management workflows