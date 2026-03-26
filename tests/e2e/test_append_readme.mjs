/**
 * E2E test: verify an agent can modify a file in its worktree.
 * The agent appends a timestamp and "appended by e2e test" to README.md,
 * then we check the diff to confirm the change was made.
 *
 * Usage: node tests/e2e/test_append_readme.mjs <target-repo-path>
 */
import { chromium } from 'playwright';
import { startServer, runAgentTask, deleteItem, printWorkLog } from './helpers.mjs';

const TARGET_REPO = process.argv[2];
if (!TARGET_REPO) {
  console.error('Usage: node tests/e2e/test_append_readme.mjs <target-repo-path>');
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

    const { finished, finalStatus, workLog, itemId } = await runAgentTask(page, BASE, {
      title: 'E2E Test: Append to README',
      description: [
        'Append a new line to the end of README.md with the current timestamp (ISO 8601) followed by "appended by e2e test".',
        'Use the Edit tool or Write tool to make the change.',
        'Then call set_commit_message with "test: append timestamp to README".',
      ].join('\n'),
    });

    printWorkLog(workLog);

    // Check the diff for the appended text
    let diffText = '';
    if (finished) {
      diffText = await page.evaluate(async (args) => {
        const [b, id] = args;
        const r = await fetch(`${b}/api/items/${id}/diff`);
        const data = await r.json();
        return data.diff || '';
      }, [BASE, itemId]);
    }

    console.log(`\n=== Results ===`);
    console.log(`Final status: ${finalStatus}`);
    console.log(`Agent finished: ${finished}`);

    const diffHasAppend = diffText.includes('appended by e2e test');
    const diffHasTimestamp = /\d{4}-\d{2}-\d{2}/.test(diffText);
    console.log(`Diff contains "appended by e2e test": ${diffHasAppend}`);
    console.log(`Diff contains timestamp: ${diffHasTimestamp}`);

    if (diffText) {
      // Show only the + lines from the diff
      const addedLines = diffText.split('\n').filter(l => l.startsWith('+')).slice(0, 10);
      console.log(`\n=== Diff (added lines) ===`);
      for (const line of addedLines) console.log(`  ${line}`);
    }

    await deleteItem(page, BASE, itemId);

    if (!finished) { console.error('\n*** FAIL: Agent did not complete ***'); process.exit(1); }
    if (!diffHasAppend) { console.error('\n*** FAIL: Diff does not contain "appended by e2e test" ***'); process.exit(1); }
    if (!diffHasTimestamp) { console.error('\n*** FAIL: Diff does not contain a timestamp ***'); process.exit(1); }
    console.log('\n*** PASS: Agent appended timestamp and text to README.md ***');

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
