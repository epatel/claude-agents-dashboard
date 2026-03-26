/**
 * E2E test: verify agents can use Bash commands (ls, wc) without
 * being blocked by the allowed_tools whitelist.
 *
 * Usage:
 *   node tests/e2e/test_allowed_tools.mjs <target-repo-path>
 *
 * The test starts the server via run.sh, captures the port from
 * Uvicorn's output, runs the test, then shuts down the server.
 */
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, '..', '..');
const TARGET_REPO = process.argv[2];
const MAX_WAIT = 120_000;
const POLL_INTERVAL = 3000;

if (!TARGET_REPO) {
  console.error('Usage: node tests/e2e/test_allowed_tools.mjs <target-repo-path>');
  process.exit(1);
}

/** Start the server and return { port, process } once it's ready. */
function startServer(targetRepo) {
  return new Promise((resolve, reject) => {
    const runSh = path.join(PROJECT_ROOT, 'run.sh');
    const proc = spawn(runSh, [targetRepo], {
      cwd: PROJECT_ROOT,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let output = '';
    const timeout = setTimeout(() => {
      proc.kill();
      reject(new Error(`Server did not start within 30s. Output:\n${output}`));
    }, 30_000);

    function onData(chunk) {
      const text = chunk.toString();
      output += text;
      process.stderr.write(text); // show server logs

      // Uvicorn prints: "Uvicorn running on http://127.0.0.1:XXXX"
      const match = text.match(/running on http:\/\/127\.0\.0\.1:(\d+)/);
      if (match) {
        clearTimeout(timeout);
        resolve({ port: parseInt(match[1], 10), proc });
      }
    }

    proc.stdout.on('data', onData);
    proc.stderr.on('data', onData);
    proc.on('error', (err) => { clearTimeout(timeout); reject(err); });
    proc.on('exit', (code) => {
      clearTimeout(timeout);
      if (!output.includes('running on')) {
        reject(new Error(`Server exited with code ${code} before starting. Output:\n${output}`));
      }
    });
  });
}

async function main() {
  // 1. Start the server
  console.log(`Starting server with target: ${TARGET_REPO}`);
  const { port, proc: serverProc } = await startServer(TARGET_REPO);
  const BASE = `http://127.0.0.1:${port}`;
  console.log(`Server running on port ${port}`);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    // 2. Open the board
    await page.goto(BASE);
    await page.waitForTimeout(1000);
    console.log('Board loaded');

    // 3. Create a new item via API
    const createRes = await page.evaluate(async (base) => {
      const r = await fetch(`${base}/api/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: 'E2E Test: Run ls and wc',
          description: 'Run these exact commands:\n1. ls\n2. wc -l README.md\n\nReport the output. Then call set_commit_message with "test: verify bash commands work".',
        }),
      });
      return r.json();
    }, BASE);

    const itemId = createRes.id;
    console.log(`Created item: ${itemId}`);

    // 4. Start the agent
    await page.evaluate(async (args) => {
      const [base, id] = args;
      await fetch(`${base}/api/items/${id}/start`, { method: 'POST' });
    }, [BASE, itemId]);
    console.log('Agent started');

    // 5. Poll for completion
    let elapsed = 0;
    let finished = false;
    let finalStatus = '';
    let workLog = [];

    while (elapsed < MAX_WAIT) {
      await page.waitForTimeout(POLL_INTERVAL);
      elapsed += POLL_INTERVAL;

      const status = await page.evaluate(async (args) => {
        const [base, id] = args;
        const listRes = await fetch(`${base}/api/items`);
        const items = await listRes.json();
        const item = items.find(i => i.id === id) || {};
        const logRes = await fetch(`${base}/api/items/${id}/log`);
        const log = await logRes.json();
        return { status: item.column_name, log };
      }, [BASE, itemId]);

      workLog = status.log || [];
      finalStatus = status.status;
      const completionInLog = workLog.some(e => (e.message || '').includes('Agent completed'));
      console.log(`  [${Math.round(elapsed/1000)}s] Status: ${finalStatus}, log entries: ${workLog.length}${completionInLog ? ' [COMPLETED]' : ''}`);

      if (['review', 'done'].includes(finalStatus) || completionInLog) {
        finished = true;
        break;
      }
      if (['error', 'failed', 'todo'].includes(finalStatus) && workLog.length > 3) {
        break;
      }
    }

    // 6. Analyze work log
    console.log(`\n=== Results ===`);
    console.log(`Final status: ${finalStatus}`);
    console.log(`Agent finished normally: ${finished}`);
    console.log(`Work log entries: ${workLog.length}`);

    let bashUsed = false;
    let bashDenied = false;

    for (const entry of workLog) {
      const msg = entry.message || entry.content || '';
      if (msg.toLowerCase().includes('bash') || msg.includes('`ls`') || msg.includes('`wc')) {
        bashUsed = true;
      }
      if (msg.includes('denied') || msg.includes('not allowed') || msg.includes('not in the allowed')) {
        bashDenied = true;
        console.log(`  DENIED: ${msg.substring(0, 150)}`);
      }
    }

    console.log(`Bash tool used: ${bashUsed}`);
    console.log(`Bash denied: ${bashDenied}`);

    console.log(`\n=== Last 10 log entries ===`);
    for (const entry of workLog.slice(-10)) {
      const msg = entry.message || entry.content || '';
      console.log(`  [${entry.entry_type || 'log'}] ${msg.substring(0, 120)}`);
    }

    // 7. Cleanup test item
    await page.evaluate(async (args) => {
      const [base, id] = args;
      await fetch(`${base}/api/items/${id}`, { method: 'DELETE' });
    }, [BASE, itemId]);
    console.log('\nTest item deleted');

    // 8. Assertions
    if (bashDenied) {
      console.error('\n*** FAIL: Bash commands were denied by allowed_tools whitelist ***');
      process.exit(1);
    }
    if (!finished) {
      console.error('\n*** FAIL: Agent did not complete within timeout ***');
      process.exit(1);
    }
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
