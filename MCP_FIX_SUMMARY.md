# MCP (Model Context Protocol) Fix Summary

## Issues Identified and Fixed

### 1. **Missing `allowed_tools` Configuration** ⚠️ **Critical Issue**
**Problem**: MCP tools were being created but Claude didn't have permission to use them.
- According to Claude Agent SDK documentation: *"MCP tools require explicit permission before Claude can use them. Without permission, Claude will see that tools are available but won't be able to call them."*
- The session.py was creating MCP servers but not granting tool permissions.

**Fix**: Added dynamic `allowed_tools` configuration in `src/agent/session.py`:
```python
# Configure allowed MCP tools
allowed_tools = []
if "clarification" in mcp_servers:
    allowed_tools.append("mcp__clarification__ask_user")
if "todo" in mcp_servers:
    allowed_tools.append("mcp__todo__create_todo")

# Allow all tools from external MCP servers (using wildcard for each server)
for server_name, server_config in mcp_servers.items():
    if server_name not in ["clarification", "todo"]:  # Skip our built-in servers
        allowed_tools.append(f"mcp__{server_name}__*")
```

### 2. **External MCP Server Configuration Not Loaded**
**Problem**: The `mcp-config.json` file existed but wasn't being loaded by the agent session.
- External MCP servers (like the SMS server) were configured but never actually used.

**Fix**: Added external MCP config loading in `src/agent/session.py`:
```python
# Load external MCP servers from mcp-config.json
mcp_config_path = self.worktree_path / "mcp-config.json"
if mcp_config_path.exists():
    try:
        with open(mcp_config_path, 'r') as f:
            external_config = json.load(f)
            external_servers = external_config.get("mcpServers", {})
            mcp_servers.update(external_servers)
            logger.info(f"Loaded {len(external_servers)} external MCP servers from config")
    except Exception as e:
        logger.warning(f"Failed to load MCP config: {e}")
```

### 3. **Suboptimal Permission Mode**
**Problem**: Using `permission_mode="bypassPermissions"` which is broader than necessary.
- Claude Agent SDK documentation recommends: *"Prefer `allowedTools` over permission modes for MCP access. `permissionMode: "bypassPermissions"` does auto-approve MCP tools but also disables all other safety prompts, which is broader than necessary."*

**Fix**: Changed to more targeted permission mode:
```python
permission_mode="acceptEdits",  # More targeted than bypassPermissions
```

## MCP Tools Available

### Built-in MCP Tools (SDK MCP Servers)
1. **`mcp__clarification__ask_user`**
   - Server: "clarification"
   - Tool: "ask_user"
   - Purpose: Allows agents to ask users questions during execution
   - Schema: `question` (required), `choices` (optional array)

2. **`mcp__todo__create_todo`**
   - Server: "todo"
   - Tool: "create_todo"
   - Purpose: Allows agents to create new todo items
   - Schema: `title` (required), `description` (optional)

### External MCP Tools
3. **`mcp__sms__*`** (from mcp-config.json)
   - Server: "sms"
   - Type: SSE (Server-Sent Events)
   - URL: https://home.memention.net/sms_mcp/sse
   - All tools from this server are now allowed via wildcard

## Key Improvements

- ✅ **Dynamic Tool Permissions**: Tool permissions are now granted dynamically based on configured servers
- ✅ **External Server Support**: Properly loads and grants permissions for external MCP servers
- ✅ **Better Security**: Uses targeted permissions instead of bypassing all permissions
- ✅ **Improved Logging**: Added logging for MCP server loading and tool permissions
- ✅ **Follows SDK Best Practices**: Aligns with current Claude Agent SDK documentation patterns

## Files Modified

- `src/agent/session.py` - Main MCP configuration and permissions fixes
- `MCP_FIX_SUMMARY.md` - This documentation

## Files That Remain Unchanged (Working Correctly)

- `src/agent/clarification.py` - MCP server creation working correctly
- `src/agent/todo.py` - MCP server creation working correctly
- `mcp-config.json` - External server config format is correct
- `src/web/routes.py` - MCP config storage working correctly
- `src/models.py` - MCP data models working correctly
- Database schema - MCP support columns working correctly

## Testing

The MCP tools should now be accessible to Claude agents:
- `mcp__clarification__ask_user` - for user clarification during tasks
- `mcp__todo__create_todo` - for creating new todo items
- `mcp__sms__*` - for SMS-related tools from external server

## Next Steps

1. **Verify functionality** - Test the clarification and todo creation flows
2. **Monitor logs** - Check for any MCP server connection issues
3. **Test external servers** - Verify SMS MCP server connectivity if needed
4. **Consider additional external MCP servers** - Add more external MCP servers to mcp-config.json as needed

## References

- [Claude Agent SDK MCP Documentation](https://platform.claude.com/docs/en/agent-sdk/mcp)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/docs/getting-started/intro)