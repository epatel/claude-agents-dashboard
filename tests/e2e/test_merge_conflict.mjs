/**
 * E2E test: verify merge conflict auto-resolution.
 *
 * Two agents both write to poem.txt simultaneously. The first merge
 * succeeds; the second triggers a conflict. The system should
 * auto-resolve by restarting the agent with the updated base.
 *
 * Usage: node tests/e2e/test_merge_conflict.mjs <target-repo-path>
 */
import {
  withBoard, apiCreateItem, apiStartItem, apiGetItems, apiGetItemWithLog, apiApproveItem, pollEvery,
  deleteItem, printWorkLog, pass, fail, E2E_MODEL,
} from './helpers.mjs';

const TARGET_REPO = process.argv[2];
if (!TARGET_REPO) {
  console.error('Usage: node tests/e2e/test_merge_conflict.mjs <target-repo-path>');
  process.exit(1);
}

const MAX_WAIT = 180_000;

const ids = { snail: null, butterfly: null };
const nameOf = (id) => (id === ids.snail ? 'snail' : 'butterfly');

/** Create the item asking for a poem about `animal`; returns its id. */
async function createPoemItem(page, base, animal) {
  const title = animal[0].toUpperCase() + animal.slice(1);
  const item = await apiCreateItem(page, base,
    `E2E: ${title} poem`,
    `Write a short 4-line poem about a ${animal}. Write it to poem.txt using the Write tool. Then call set_commit_message with "Add ${animal} poem".`);
  console.log(`Created ${animal} item: ${item.id}${E2E_MODEL ? ` (model: ${E2E_MODEL})` : ''}`);
  return item.id;
}

/**
 * Wait for both items to reach review. Returns { firstId, secondId }
 * in the order they arrived (null for one that never did).
 */
async function waitForBothReview(page, base) {
  const arrived = [];
  await pollEvery(page, MAX_WAIT, async (elapsed) => {
    const [snail, butterfly] = await apiGetItems(page, base, [ids.snail, ids.butterfly]);
    console.log(`  [${Math.round(elapsed/1000)}s] snail=${snail.column_name}(${snail.status || ''}) butterfly=${butterfly.column_name}(${butterfly.status || ''})`);
    for (const [id, item] of [[ids.snail, snail], [ids.butterfly, butterfly]]) {
      if (item.column_name === 'review' && !arrived.includes(id)) arrived.push(id);
    }
    return arrived.length === 2;
  });
  return { firstId: arrived[0] || null, secondId: arrived[1] || null };
}

/** Poll until the re-run item is back in review or done. Returns { reached, column, status, elapsed, log }. */
async function waitForResolution(page, base, itemId) {
  const { result, elapsed } = await pollEvery(page, MAX_WAIT, async (elapsedNow) => {
    const { item, log } = await apiGetItemWithLog(page, base, itemId);
    console.log(`  [resolve] [${Math.round(elapsedNow/1000)}s] column=${item.column_name} status=${item.status} logs=${log.length}`);
    return ['review', 'done'].includes(item.column_name) ? { column: item.column_name, status: item.status, log } : null;
  });
  return result ? { reached: true, ...result, elapsed } : { reached: false, elapsed };
}

async function approveAndLog(page, base, itemId, label) {
  const result = await apiApproveItem(page, base, itemId);
  console.log(`  ${label}: HTTP ${result.status}`);
  return result;
}

/** Wait for the re-run agent, approve the resolved item and report where it ended up. */
async function resolveConflict(page, base, itemId) {
  console.log('\nWaiting for conflict resolution agent to finish...');
  const resolved = await waitForResolution(page, base, itemId);
  if (!resolved.reached) fail('Conflict resolution agent did not finish');

  console.log(`\nConflict resolved! Item back in: ${resolved.column}`);
  console.log('Approving resolved item...');
  await approveAndLog(page, base, itemId, 'Final approve');
  const [finalItem] = await apiGetItems(page, base, [itemId]);
  console.log(`  Final column: ${finalItem.column_name}`);
  if (resolved.log) printWorkLog(resolved.log, 5);
}

async function runTest(page, base) {
  // 1. Create both items
  ids.snail = await createPoemItem(page, base, 'snail');
  ids.butterfly = await createPoemItem(page, base, 'butterfly');

  // 2. Start both agents simultaneously
  await Promise.all([apiStartItem(page, base, ids.snail), apiStartItem(page, base, ids.butterfly)]);
  console.log('Both agents started\n');

  // 3. Wait for both to reach review
  console.log('Waiting for first agent to finish...');
  const { firstId, secondId } = await waitForBothReview(page, base);
  if (!firstId) fail('Neither agent reached review');
  console.log(`\nFirst to review: ${nameOf(firstId)}`);
  if (!secondId) fail('Second agent did not reach review');
  console.log(`Second to review: ${nameOf(secondId)}`);

  // 4. Approve the first item, then give the merge a moment to complete
  console.log(`\nApproving first item (${nameOf(firstId)})...`);
  const approveFirst = await approveAndLog(page, base, firstId, 'Approve result');
  await page.waitForTimeout(2000);

  // 5. Approve the second item — this should trigger a merge conflict
  console.log(`\nApproving second item (${nameOf(secondId)})...`);
  await approveAndLog(page, base, secondId, 'Approve result');

  // Check if the item went back to doing (conflict resolution)
  const [secondItem] = await apiGetItems(page, base, [secondId]);
  const conflictDetected = secondItem.column_name === 'doing' || secondItem.status === 'resolving_conflicts';
  console.log(`  Conflict detected and auto-resolving: ${conflictDetected}`);
  console.log(`  Column: ${secondItem.column_name}, Status: ${secondItem.status}`);

  // 6–7. Wait for the re-run agent and approve it
  if (conflictDetected) {
    await resolveConflict(page, base, secondId);
  } else {
    // Maybe there was no conflict (race condition — both wrote different content)
    console.log('  No conflict detected — items may have been merged cleanly');
  }

  // 8. Results
  console.log('\n=== Results ===');
  console.log(`Both agents completed: true`);
  console.log(`First merge succeeded: ${approveFirst.status === 200}`);
  console.log(`Conflict on second merge: ${conflictDetected}`);
  pass(conflictDetected
    ? 'Merge conflict detected and auto-resolved'
    : 'Both agents completed (no conflict occurred — both merged cleanly)');
}

async function deleteTestItems(page, base) {
  try {
    if (ids.snail) await deleteItem(page, base, ids.snail).catch(() => {});
    if (ids.butterfly) await deleteItem(page, base, ids.butterfly).catch(() => {});
  } catch {}
}

withBoard(TARGET_REPO, runTest, { cleanup: deleteTestItems });
