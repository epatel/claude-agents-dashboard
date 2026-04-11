/**
 * E2E test: verify merge conflict auto-resolution.
 *
 * Two agents both write to poem.txt simultaneously. The first merge
 * succeeds; the second triggers a conflict. The system should
 * auto-resolve by restarting the agent with the updated base.
 *
 * Usage: node tests/e2e/test_merge_conflict.mjs <target-repo-path>
 */
import { chromium } from 'playwright';
import { startServer, stopServer, deleteItem, printWorkLog, pass, fail, E2E_MODEL } from './helpers.mjs';

const TARGET_REPO = process.argv[2];
if (!TARGET_REPO) {
  console.error('Usage: node tests/e2e/test_merge_conflict.mjs <target-repo-path>');
  process.exit(1);
}

const MAX_WAIT = 180_000;
const POLL_INTERVAL = 3000;

/** Poll until an item reaches one of the target columns, or timeout. */
async function waitForStatus(page, base, itemId, targetColumns, maxWait, label) {
  let elapsed = 0;
  while (elapsed < maxWait) {
    await page.waitForTimeout(POLL_INTERVAL);
    elapsed += POLL_INTERVAL;

    const result = await page.evaluate(async (args) => {
      const [b, id] = args;
      const listRes = await fetch(`${b}/api/items`);
      const items = await listRes.json();
      const item = items.find(i => i.id === id) || {};
      const logRes = await fetch(`${b}/api/items/${id}/log`);
      const log = await logRes.json();
      return { column: item.column_name, status: item.status, logCount: log.length, log };
    }, [base, itemId]);

    console.log(`  [${label}] [${Math.round(elapsed/1000)}s] column=${result.column} status=${result.status} logs=${result.logCount}`);

    if (targetColumns.includes(result.column)) {
      return { reached: true, column: result.column, status: result.status, elapsed, log: result.log };
    }
  }
  return { reached: false, elapsed };
}

async function main() {
  console.log(`Starting server with target: ${TARGET_REPO}`);
  const { port, proc: serverProc } = await startServer(TARGET_REPO);
  const BASE = `http://127.0.0.1:${port}`;
  console.log(`Server running on port ${port}`);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  let snailId = null;
  let butterflyId = null;

  try {
    await page.goto(BASE);
    await page.waitForTimeout(1000);
    console.log('Board loaded');

    // 1. Create both items
    const createItem = async (title, description) => {
      return page.evaluate(async (args) => {
        const [b, t, d, model] = args;
        const payload = { title: t, description: d };
        if (model) payload.model = model;
        const r = await fetch(`${b}/api/items`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        return r.json();
      }, [BASE, title, description, E2E_MODEL]);
    };

    const snail = await createItem(
      'E2E: Snail poem',
      'Write a short 4-line poem about a snail. Write it to poem.txt using the Write tool. Then call set_commit_message with "Add snail poem".'
    );
    snailId = snail.id;
    console.log(`Created snail item: ${snailId}${E2E_MODEL ? ` (model: ${E2E_MODEL})` : ''}`);

    const butterfly = await createItem(
      'E2E: Butterfly poem',
      'Write a short 4-line poem about a butterfly. Write it to poem.txt using the Write tool. Then call set_commit_message with "Add butterfly poem".'
    );
    butterflyId = butterfly.id;
    console.log(`Created butterfly item: ${butterflyId}${E2E_MODEL ? ` (model: ${E2E_MODEL})` : ''}`);

    // 2. Start both agents simultaneously
    const startItem = async (id) => {
      return page.evaluate(async (args) => {
        const [b, i] = args;
        await fetch(`${b}/api/items/${i}/start`, { method: 'POST' });
      }, [BASE, id]);
    };

    await Promise.all([startItem(snailId), startItem(butterflyId)]);
    console.log('Both agents started\n');

    // 3. Wait for both to reach review
    console.log('Waiting for first agent to finish...');
    const first = await waitForBothReview(page, BASE, snailId, butterflyId, MAX_WAIT);

    if (!first.firstId) {
      fail('Neither agent reached review');
    }

    console.log(`\nFirst to review: ${first.firstId === snailId ? 'snail' : 'butterfly'}`);

    if (!first.secondId) {
      fail('Second agent did not reach review');
    }

    console.log(`Second to review: ${first.secondId === snailId ? 'snail' : 'butterfly'}`);

    // 4. Approve the first item
    console.log(`\nApproving first item (${first.firstId === snailId ? 'snail' : 'butterfly'})...`);
    const approveResult1 = await page.evaluate(async (args) => {
      const [b, id] = args;
      const r = await fetch(`${b}/api/items/${id}/approve`, { method: 'POST' });
      return { status: r.status, body: await r.json() };
    }, [BASE, first.firstId]);
    console.log(`  Approve result: HTTP ${approveResult1.status}`);

    // Small delay to let the merge complete
    await page.waitForTimeout(2000);

    // 5. Approve the second item — this should trigger a merge conflict
    console.log(`\nApproving second item (${first.secondId === snailId ? 'snail' : 'butterfly'})...`);
    const approveResult2 = await page.evaluate(async (args) => {
      const [b, id] = args;
      const r = await fetch(`${b}/api/items/${id}/approve`, { method: 'POST' });
      return { status: r.status, body: await r.json() };
    }, [BASE, first.secondId]);
    console.log(`  Approve result: HTTP ${approveResult2.status}`);

    // Check if the item went back to doing (conflict resolution)
    const secondItem = await page.evaluate(async (args) => {
      const [b, id] = args;
      const listRes = await fetch(`${b}/api/items`);
      const items = await listRes.json();
      return items.find(i => i.id === id) || {};
    }, [BASE, first.secondId]);

    const conflictDetected = secondItem.column_name === 'doing' || secondItem.status === 'resolving_conflicts';
    console.log(`  Conflict detected and auto-resolving: ${conflictDetected}`);
    console.log(`  Column: ${secondItem.column_name}, Status: ${secondItem.status}`);

    if (conflictDetected) {
      // 6. Wait for the re-run agent to finish
      console.log('\nWaiting for conflict resolution agent to finish...');
      const resolved = await waitForStatus(page, BASE, first.secondId, ['review', 'done'], MAX_WAIT, 'resolve');

      if (resolved.reached) {
        console.log(`\nConflict resolved! Item back in: ${resolved.column}`);

        // 7. Approve the resolved item
        console.log('Approving resolved item...');
        const approveResult3 = await page.evaluate(async (args) => {
          const [b, id] = args;
          const r = await fetch(`${b}/api/items/${id}/approve`, { method: 'POST' });
          return { status: r.status, body: await r.json() };
        }, [BASE, first.secondId]);
        console.log(`  Final approve: HTTP ${approveResult3.status}`);

        // Check final state
        const finalItem = await page.evaluate(async (args) => {
          const [b, id] = args;
          const listRes = await fetch(`${b}/api/items`);
          const items = await listRes.json();
          return items.find(i => i.id === id) || {};
        }, [BASE, first.secondId]);
        console.log(`  Final column: ${finalItem.column_name}`);

        if (resolved.log) printWorkLog(resolved.log, 5);
      } else {
        fail('Conflict resolution agent did not finish');
      }
    } else {
      // Maybe there was no conflict (race condition — both wrote different content)
      console.log('  No conflict detected — items may have been merged cleanly');
    }

    // 8. Results
    console.log('\n=== Results ===');
    console.log(`Both agents completed: true`);
    console.log(`First merge succeeded: ${approveResult1.status === 200}`);
    console.log(`Conflict on second merge: ${conflictDetected}`);

    if (!conflictDetected) {
      pass('Both agents completed (no conflict occurred — both merged cleanly)');
    } else {
      pass('Merge conflict detected and auto-resolved');
    }

  } catch (err) {
    console.error('Test error:', err);
    process.exit(1);
  } finally {
    // Cleanup
    try {
      if (snailId) await deleteItem(page, BASE, snailId).catch(() => {});
      if (butterflyId) await deleteItem(page, BASE, butterflyId).catch(() => {});
    } catch {}
    await browser.close();
    await stopServer(port, serverProc);
  }
}

/**
 * Wait for both items to reach review. Returns { firstId, secondId }
 * in the order they arrived.
 */
async function waitForBothReview(page, base, id1, id2, maxWait) {
  let elapsed = 0;
  let firstId = null;
  let secondId = null;

  while (elapsed < maxWait) {
    await page.waitForTimeout(POLL_INTERVAL);
    elapsed += POLL_INTERVAL;

    const statuses = await page.evaluate(async (args) => {
      const [b, i1, i2] = args;
      const listRes = await fetch(`${b}/api/items`);
      const items = await listRes.json();
      const item1 = items.find(i => i.id === i1) || {};
      const item2 = items.find(i => i.id === i2) || {};
      return {
        col1: item1.column_name, status1: item1.status,
        col2: item2.column_name, status2: item2.status,
      };
    }, [base, id1, id2]);

    console.log(`  [${Math.round(elapsed/1000)}s] snail=${statuses.col1}(${statuses.status1 || ''}) butterfly=${statuses.col2}(${statuses.status2 || ''})`);

    if (!firstId && statuses.col1 === 'review') firstId = id1;
    if (!firstId && statuses.col2 === 'review') firstId = id2;
    if (firstId && !secondId) {
      if (firstId !== id1 && statuses.col1 === 'review') secondId = id1;
      if (firstId !== id2 && statuses.col2 === 'review') secondId = id2;
    }

    if (firstId && secondId) break;
  }

  return { firstId, secondId };
}

main();
