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
import { chromium } from 'playwright';
import { startServer, stopServer, runAgentTask, deleteItem, printWorkLog, pass, fail, warn, PROJECT_ROOT } from './helpers.mjs';
import path from 'node:path';

const TARGET_REPO = process.argv[2];
if (!TARGET_REPO) {
  console.error('Usage: node tests/e2e/test_mini_mcp.mjs <target-repo-path>');
  process.exit(1);
}

const EXPECTED_SECRET = 'FEC52599-123E-49FF-9E32-9E0D7E51BBA9';
const SERVER_SCRIPT = path.join(PROJECT_ROOT, 'examples', 'mini-mcp', 'server.py');

async function configureMiniMcp(page, base) {
  // Get current config
  const config = await page.evaluate(async (b) => {
    const r = await fetch(`${b}/api/config`);
    return r.json();
  }, base);

  // Build MCP servers config: preserve existing servers, add mini-mcp
  let existingServers = {};
  try {
    existingServers = JSON.parse(config.mcp_servers || '{}');
  } catch { /* ignore */ }

  existingServers['mini-mcp'] = {
    command: '/usr/bin/python3',
    args: [SERVER_SCRIPT],
  };

  // Update config with MCP enabled and mini-mcp server
  await page.evaluate(async (args) => {
    const [b, mcpServers] = args;
    await fetch(`${b}/api/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mcp_servers: JSON.stringify(mcpServers),
        mcp_enabled: true,
      }),
    });
  }, [base, existingServers]);

  console.log('Mini-MCP configured');
}

async function main() {
  console.log(`Starting server with target: ${TARGET_REPO}`);
  const { port, proc: serverProc } = await startServer(TARGET_REPO);
  const BASE = `http://127.0.0.1:${port}`;
  console.log(`Server running on port ${port}`);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    await page.goto(BASE);
    await page.waitForTimeout(1000);
    console.log('Board loaded');

    // Configure mini-mcp server
    await configureMiniMcp(page, BASE);

    // Run agent task
    const { finished, workLog, itemId } = await runAgentTask(page, BASE, {
      title: 'E2E Test: Get secret via MCP',
      description: 'Use the get_secret tool and report the exact value it returns. Do not make up a value — you must call the tool.',
    });

    printWorkLog(workLog);

    // Check: agent should have completed
    if (!finished) fail('Agent did not complete');

    // Check: secret should appear in work log
    const allContent = workLog.map(e => e.message || e.content || '').join(' ');
    if (!allContent.includes(EXPECTED_SECRET)) {
      fail(`Secret ${EXPECTED_SECRET} not found in work log`);
    }

    // Check: the agent should have used the MCP tool
    const usedMcpTool = workLog.some(e => {
      const msg = e.message || e.content || '';
      return msg.includes('get_secret') || msg.includes('mcp__mini-mcp');
    });
    if (!usedMcpTool) {
      warn('Could not confirm get_secret tool was called (secret found but tool use not logged)');
    }

    // Clean up
    await deleteItem(page, BASE, itemId);

    pass('Agent retrieved secret via mini-mcp MCP tool');

  } catch (err) {
    console.error('Test error:', err);
    process.exit(1);
  } finally {
    await browser.close();
    await stopServer(port, serverProc);
  }
}

main();
