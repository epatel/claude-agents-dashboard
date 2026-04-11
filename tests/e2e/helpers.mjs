/**
 * Shared helpers for E2E tests.
 */
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const PROJECT_ROOT = path.resolve(__dirname, '..', '..');

const MAX_WAIT = 120_000;
const POLL_INTERVAL = 3000;

/** Model override from E2E_MODEL env var (e.g. "claude-haiku-4-5-20251001"). */
export const E2E_MODEL = process.env.E2E_MODEL || null;

/** When set, tests reuse an externally started server instead of spawning their own. */
export const E2E_PORT = process.env.E2E_PORT ? parseInt(process.env.E2E_PORT, 10) : null;

/** Check if -v or --verbose was passed as a CLI argument. */
export const VERBOSE = process.argv.includes('-v') || process.argv.includes('--verbose');

/** ANSI color helpers. */
const GREEN = '\x1b[32m';
const RED = '\x1b[31m';
const YELLOW = '\x1b[33m';
const RESET = '\x1b[0m';

/** Print a colored PASS message. */
export function pass(msg) {
  console.log(`\n${GREEN}*** PASS: ${msg} ***${RESET}`);
}

/** Print a colored FAIL message and exit. */
export function fail(msg) {
  console.error(`\n${RED}*** FAIL: ${msg} ***${RESET}`);
  process.exit(1);
}

/** Print a colored WARNING message. */
export function warn(msg) {
  console.warn(`${YELLOW}WARNING: ${msg}${RESET}`);
}

/** Start the server and return { port, proc } once it's ready.
 *  When E2E_PORT is set, reuses the external server (proc is null). */
export function startServer(targetRepo) {
  if (E2E_PORT) {
    console.log(`Using external server on port ${E2E_PORT}`);
    return Promise.resolve({ port: E2E_PORT, proc: null });
  }
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
      if (VERBOSE) process.stderr.write(text);

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

/** Gracefully stop the server via the shutdown endpoint, then kill the process as fallback.
 *  No-op when using an external server (proc is null). */
export async function stopServer(port, proc) {
  if (!proc) return;  // External server — managed by caller
  try {
    await fetch(`http://127.0.0.1:${port}/api/shutdown`, { method: 'POST' });
    // Give it a moment to exit cleanly
    await new Promise(r => setTimeout(r, 1000));
  } catch {
    // Endpoint may already be down
  }
  proc.kill();
  console.log('Server stopped');
}

/**
 * Create an item, start the agent, and poll until completion.
 * Returns { finished, finalStatus, workLog, itemId }.
 */
export async function runAgentTask(page, base, { title, description }) {
  const createRes = await page.evaluate(async (args) => {
    const [b, t, d] = args;
    const payload = { title: t, description: d };
    if (args[3]) payload.model = args[3];
    const r = await fetch(`${b}/api/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return r.json();
  }, [base, title, description, E2E_MODEL]);

  const itemId = createRes.id;
  console.log(`Created item: ${itemId}${E2E_MODEL ? ` (model: ${E2E_MODEL})` : ''}`);

  await page.evaluate(async (args) => {
    const [b, id] = args;
    await fetch(`${b}/api/items/${id}/start`, { method: 'POST' });
  }, [base, itemId]);
  console.log('Agent started');

  let elapsed = 0;
  let finished = false;
  let finalStatus = '';
  let workLog = [];

  while (elapsed < MAX_WAIT) {
    await page.waitForTimeout(POLL_INTERVAL);
    elapsed += POLL_INTERVAL;

    const status = await page.evaluate(async (args) => {
      const [b, id] = args;
      const listRes = await fetch(`${b}/api/items`);
      const items = await listRes.json();
      const item = items.find(i => i.id === id) || {};
      const logRes = await fetch(`${b}/api/items/${id}/log`);
      const log = await logRes.json();
      return { status: item.column_name, log };
    }, [base, itemId]);

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

  return { finished, finalStatus, workLog, itemId };
}

/** Delete a test item. */
export async function deleteItem(page, base, itemId) {
  await page.evaluate(async (args) => {
    const [b, id] = args;
    await fetch(`${b}/api/items/${id}`, { method: 'DELETE' });
  }, [base, itemId]);
  console.log('Test item deleted');
}

/** Print work log summary. */
export function printWorkLog(workLog, lastN = 10) {
  console.log(`\n=== Last ${lastN} log entries ===`);
  for (const entry of workLog.slice(-lastN)) {
    const msg = entry.message || entry.content || '';
    console.log(`  [${entry.entry_type || 'log'}] ${msg.substring(0, 120)}`);
  }
}
