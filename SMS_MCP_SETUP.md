# SMS MCP Integration Setup

This document explains how to set up and use SMS functionality via MCP (Model Context Protocol) in the Claude Agents Dashboard.

## Current Status

✅ **MCP Configuration Ready**: SMS MCP server configured using proper options.mcpServers parameter.

## Configuration

### Proper MCP Configuration (Recommended)
Configure SMS MCP using the proper options parameter format:

**Method 1: Web Interface**
1. Start the dashboard: `python -m src.main`
2. Open the web interface (default: http://127.0.0.1:8000)
3. Click the "⚙️" (settings) button to open Agent Configuration
4. Check "Enable MCP (Model Context Protocol)"
5. In the "MCP Servers" text area, enter:
   ```json
   {
     "sms": {
       "type": "sse",
       "url": "https://home.memention.net/sms_mcp/sse?api_key=YOUR_API_KEY_HERE"
     }
   }
   ```
6. Click "Save"

**Method 2: Configuration Script**
Run the provided configuration script:
```bash
python configure_sms_mcp.py
```

## Testing SMS Functionality

### Method 1: Create a Task via Web Interface
1. Start the dashboard: `python -m src.main`
2. Open the web interface
3. Create a new task with:
   - **Title**: "Test SMS via MCP"
   - **Description**: "Send an SMS to 0708554888 with the message: 'Hello! This is a test message from Claude via MCP. The SMS integration is working!'"
4. Run the task and verify the SMS is sent

### Method 2: Use the Configuration Script
Run the provided configuration script (requires approval):
```bash
python configure_sms_mcp.py
```

This script will:
- Initialize the database with proper SMS MCP configuration
- Use the correct options.mcpServers format
- Create a test SMS task
- Enable MCP with proper settings

## Expected Behavior

When an agent task runs with SMS MCP enabled, Claude will have access to SMS tools with the pattern `mcp__sms__*`. The agent can:

1. Send SMS messages to phone numbers using `mcp__sms__send_sms`
2. Get SMS queue status using `mcp__sms__get_sms_queue_status`
3. Retrieve SMS messages using `mcp__sms__get_sms`
4. Check battery status using `mcp__sms__get_battery_status`

## Configuration Details

- **Configuration Method**: `options.mcpServers` parameter (proper format)
- **MCP Server Type**: Server-Sent Events (SSE)
- **API Endpoint**: `https://home.memention.net/sms_mcp/sse`
- **API Key**: `YOUR_API_KEY_HERE` (replace with your actual API key)
- **Target Phone Number**: `0708554888` (for testing)
- **Available Tools**: `mcp__sms__*` (automatically allowed)

⚠️ **Important**: Replace `YOUR_API_KEY_HERE` with your actual SMS MCP API key before using.

## Troubleshooting

### Common Issues

1. **MCP tools not available**:
   - Verify MCP is enabled in agent configuration
   - Check that the MCP servers are properly configured in the database
   - Ensure the SMS server URL is accessible
   - Verify the options.mcpServers format is correct

2. **SMS not sent**:
   - Verify the API key is correct
   - Check the phone number format (international format recommended)
   - Review the MCP server logs

3. **Configuration not loading**:
   - Restart the dashboard after configuration changes
   - Check that the JSON syntax is valid
   - Verify database permissions

### Logs and Debugging

Agent session logs will show:
- `Loaded {N} MCP servers from agent configuration` when SMS MCP is loaded
- `Allowing all tools from external MCP server: sms` when SMS tools are enabled
- Tool usage logs when SMS functions are called

## Next Steps

1. ✅ MCP configuration file created
2. ⏳ Start dashboard and test SMS functionality
3. ⏳ Verify SMS delivery to 0708554888
4. ⏳ Document any additional MCP servers needed

---

**Note**: This configuration uses the provided SMS MCP server endpoint. Ensure the API key and endpoint are correct for your environment.