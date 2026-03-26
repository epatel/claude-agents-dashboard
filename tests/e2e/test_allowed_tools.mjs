/**
 * E2E test: verify agents can use Bash commands (ls, wc) without
 * being blocked by the allowed_tools whitelist.
 *
 * Usage: node tests/e2e/test_allowed_tools.mjs <target-repo-path>
 */
import { chromium } from 'playwright';
import { startServer, runAgentTask, deleteItem, printWorkLog } from './helpers.mjs';

const TARGET_REPO = process.argv[2];
if (!TARGET_REPO) {
  console.error('Usage: node tests/e2e/test_allowed_tools.mjs <target-repo-path>');
  process.exit(1);
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

    const { finished, workLog, itemId } = await runAgentTask(page, BASE, {
      title: 'E2E Test: Run ls and wc',
      description: 'Run these exact commands:\n1. ls\n2. wc -l README.md\n\nReport the output. Then call set_commit_message with "test: verify bash commands work".',
    });

    // Analyze
    let bashUsed = false;
    let bashDenied = false;
    for (const entry of workLog) {
      const msg = entry.message || entry.content || '';
      if (msg.toLowerCase().includes('bash') || msg.includes('`ls`') || msg.includes('`wc')) bashUsed = true;
      if (msg.includes('denied') || msg.includes('not allowed') || msg.includes('not in the allowed')) {
        bashDenied = true;
        console.log(`  DENIED: ${msg.substring(0, 150)}`);
      }
    }

    console.log(`\n=== Results ===`);
    console.log(`Bash tool used: ${bashUsed}`);
    console.log(`Bash denied: ${bashDenied}`);
    printWorkLog(workLog);

    await deleteItem(page, BASE, itemId);

    if (bashDenied) { console.error('\n*** FAIL: Bash commands were denied ***'); process.exit(1); }
    if (!finished) { console.error('\n*** FAIL: Agent did not complete ***'); process.exit(1); }
    console.log('\n*** PASS: Agent ran Bash commands without being blocked ***');

  } catch (err) {
    console.error('Test error:', err);
    process.exit(1);
  } finally {
    await browser.close();
    serverProc.kill();
    console.log('Server stopped');
  }
}

main();
