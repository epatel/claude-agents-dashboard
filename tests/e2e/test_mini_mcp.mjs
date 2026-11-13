/**
 * E2E test: verify an agent can call a custom stdio MCP tool (mini-mcp)
 * and retrieve the secret value.
 *
 * The test configures the mini-mcp server via the API, creates a task
 * asking the agent to call get_secret, and verifies the secret UUID
 * appears in the work log.
 *
 * Usage: node tests/e2e/test_mini_mcp.mjs <target-repo-path>
 */
import {
  withBoard, requireTargetRepo, runAgentTask, deleteItem, printWorkLog, pass, fail, warn, PROJECT_ROOT,
  apiRequest, jsonInit,
} from './helpers.mjs';
import path from 'node:path';

const TARGET_REPO = requireTargetRepo('test_mini_mcp.mjs');

const EXPECTED_SECRET = 'FEC52599-123E-49FF-9E32-9E0D7E51BBA9';
const SERVER_SCRIPT = path.join(PROJECT_ROOT, 'examples', 'mini-mcp', 'server.py');

async function configureMiniMcp(page, base) {
  // GET returns mcp_servers as an object; PUT replaces the whole config, so
  // send the current config back with only the MCP fields changed.
  const { body: config } = await apiRequest(page, base, '/api/config');
  const mcpServers = {
    ...(config.mcp_servers || {}),
    'mini-mcp': { command: '/usr/bin/python3', args: [SERVER_SCRIPT] },
  };
  const res = await apiRequest(page, base, '/api/config',
    jsonInit('PUT', { ...config, mcp_servers: mcpServers, mcp_enabled: true }));
  if (res.status !== 200) fail(`PUT /api/config returned ${res.status}: ${JSON.stringify(res.body)}`);

  console.log('Mini-MCP configured');
}

withBoard(TARGET_REPO, async (page, BASE) => {
  await configureMiniMcp(page, BASE);

  const { finished, workLog, itemId } = await runAgentTask(page, BASE, {
    title: 'E2E Test: Get secret via MCP',
    description: 'Use the get_secret tool and report the exact value it returns. Do not make up a value — you must call the tool.',
  });

  printWorkLog(workLog);

  // Check: agent should have completed
  if (!finished) fail('Agent did not complete');

  // Check: secret should appear in work log
  const messages = workLog.map(e => e.message || e.content || '');
  if (!messages.join(' ').includes(EXPECTED_SECRET)) {
    fail(`Secret ${EXPECTED_SECRET} not found in work log`);
  }

  // Check: the agent should have used the MCP tool
  if (!messages.some(msg => msg.includes('get_secret') || msg.includes('mcp__mini-mcp'))) {
    warn('Could not confirm get_secret tool was called (secret found but tool use not logged)');
  }

  await deleteItem(page, BASE, itemId);
  pass('Agent retrieved secret via mini-mcp MCP tool');
});
