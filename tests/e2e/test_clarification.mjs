/**
 * E2E test: verify the ask_user clarification flow.
 * The agent is given a task that forces it to ask the user a question,
 * we detect the question, submit a response, and verify the agent
 * completes using our answer.
 *
 * Usage: node tests/e2e/test_clarification.mjs <target-repo-path>
 */
import { chromium } from 'playwright';
import { startServer, deleteItem, printWorkLog } from './helpers.mjs';

const TARGET_REPO = process.argv[2];
if (!TARGET_REPO) {
  console.error('Usage: node tests/e2e/test_clarification.mjs <target-repo-path>');
  process.exit(1);
}

const MAX_WAIT = 120_000;
const POLL_INTERVAL = 3000;

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

    // 1. Create an item that forces the agent to ask a question
    const createRes = await page.evaluate(async (args) => {
      const [b] = args;
      const r = await fetch(`${b}/api/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: 'E2E Test: Clarification flow',
          description: [
            'You MUST use the ask_user tool (mcp__clarification__ask_user) to ask the user what greeting to write.',
            'Ask them: "What greeting should I write to README.md?"',
            'Wait for their response, then append their exact answer to README.md.',
            'Then call set_commit_message with "test: clarification flow".',
          ].join('\n'),
        }),
      });
      return r.json();
    }, [BASE]);

    const itemId = createRes.id;
    console.log(`Created item: ${itemId}`);

    // 2. Start the agent
    await page.evaluate(async (args) => {
      const [b, id] = args;
      await fetch(`${b}/api/items/${id}/start`, { method: 'POST' });
    }, [BASE, itemId]);
    console.log('Agent started');

    // 3. Wait for the agent to ask a question (item moves to "questions")
    let elapsed = 0;
    let questionReceived = false;
    let clarificationPrompt = '';

    while (elapsed < MAX_WAIT) {
      await page.waitForTimeout(POLL_INTERVAL);
      elapsed += POLL_INTERVAL;

      const status = await page.evaluate(async (args) => {
        const [b, id] = args;
        const listRes = await fetch(`${b}/api/items`);
        const items = await listRes.json();
        const item = items.find(i => i.id === id) || {};
        const clarRes = await fetch(`${b}/api/items/${id}/clarification`);
        const clar = await clarRes.json();
        return { column: item.column_name, prompt: clar.prompt };
      }, [BASE, itemId]);

      console.log(`  [${Math.round(elapsed/1000)}s] Column: ${status.column}, prompt: ${status.prompt ? status.prompt.substring(0, 60) + '...' : 'none'}`);

      if (status.column === 'questions' && status.prompt) {
        questionReceived = true;
        clarificationPrompt = status.prompt;
        break;
      }
    }

    if (!questionReceived) {
      console.error('\n*** FAIL: Agent did not ask a clarification question ***');
      printWorkLog(await getWorkLog(page, BASE, itemId));
      await deleteItem(page, BASE, itemId);
      process.exit(1);
    }

    console.log(`\nAgent asked: "${clarificationPrompt}"`);

    // 4. Submit our answer
    const answer = 'Hello from E2E test!';
    console.log(`Responding with: "${answer}"`);

    await page.evaluate(async (args) => {
      const [b, id, resp] = args;
      await fetch(`${b}/api/items/${id}/clarify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ response: resp }),
      });
    }, [BASE, itemId, answer]);

    // 5. Wait for agent to complete
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

    // 6. Check the diff for our answer
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
    console.log(`Question received: ${questionReceived}`);
    console.log(`Question prompt: "${clarificationPrompt}"`);
    console.log(`Agent finished: ${finished}`);
    console.log(`Final status: ${finalStatus}`);

    const diffHasAnswer = diffText.includes('Hello from E2E test');
    console.log(`Diff contains our answer: ${diffHasAnswer}`);

    printWorkLog(workLog);

    if (diffText) {
      const addedLines = diffText.split('\n').filter(l => l.startsWith('+')).slice(0, 10);
      console.log(`\n=== Diff (added lines) ===`);
      for (const line of addedLines) console.log(`  ${line}`);
    }

    await deleteItem(page, BASE, itemId);

    if (!finished) { console.error('\n*** FAIL: Agent did not complete after clarification ***'); process.exit(1); }
    if (!diffHasAnswer) { console.error('\n*** FAIL: Diff does not contain our answer ***'); process.exit(1); }
    console.log('\n*** PASS: Clarification flow works — agent asked, received answer, and used it ***');

  } catch (err) {
    console.error('Test error:', err);
    process.exit(1);
  } finally {
    await browser.close();
    serverProc.kill();
    console.log('Server stopped');
  }
}

async function getWorkLog(page, base, itemId) {
  return page.evaluate(async (args) => {
    const [b, id] = args;
    const r = await fetch(`${b}/api/items/${id}/log`);
    return r.json();
  }, [base, itemId]);
}

main();
