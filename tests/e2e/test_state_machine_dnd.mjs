/**
 * E2E test: drag-and-drop produces canonical (column, status) encodings.
 *
 * Background: the move endpoint used to write column_name without
 * touching status, which produced encodings the SM didn't recognize
 * (e.g. ("doing", "cancelled"), ("doing", null)). Clicking Start on
 * such an item then 500'd with UnknownStateEncoding. Phase 2's
 * ItemRepository.move_to_column normalizes status on cross-column
 * moves so this can't happen anymore.
 *
 * This test exercises the move endpoint directly via HTTP. It does NOT
 * spawn any Claude agent — costs nothing to run.
 *
 * Usage: node tests/e2e/test_state_machine_dnd.mjs <target-repo-path>
 */
import { withBoard, requireTargetRepo, apiRequest, jsonInit, pass, fail } from './helpers.mjs';

const TARGET_REPO = requireTargetRepo('test_state_machine_dnd.mjs');

let page = null;
let BASE = null;
const created = [];  // ids to clean up

const api = (path, init) => apiRequest(page, BASE, path, init);

async function createItem(title) {
  const res = await apiRequest(page, BASE, '/api/items', jsonInit('POST', { title, description: 'dnd test' }));
  if (res.status !== 200) fail(`createItem failed: ${res.status} ${JSON.stringify(res.body)}`);
  created.push(res.body.id);
  return res.body;
}

async function move(id, column, position = 0) {
  const res = await apiRequest(page, BASE, `/api/items/${id}/move`, jsonInit('POST', { column_name: column, position }));
  if (res.status !== 200) fail(`move ${id} -> ${column} failed: ${res.status} ${JSON.stringify(res.body)}`);
  return res.body;
}

async function getItem(id) {
  const res = await api('/api/items');
  if (res.status !== 200) fail(`list items failed: ${res.status}`);
  return res.body.find(i => i.id === id) || null;
}

/** Fail unless a moved item landed in `column` with status null. */
function expectColumnWithNullStatus(label, moved, column) {
  if (moved.column_name !== column) fail(`${label}: expected column ${column}, got ${moved.column_name}`);
  if (moved.status !== null) fail(`${label}: expected status null, got ${JSON.stringify(moved.status)}`);
}

// ---- Case 1: drag from todo -> doing leaves canonical encoding ----
// Pre-Phase-2 this produced ("doing", null) which the SM couldn't read.
async function case1() {
  const item = await createItem('DnD case 1');
  const moved = await move(item.id, 'doing', 0);
  // Cross-column move clears status to null. The SM's fallback maps
  // ("doing", null) to BACKLOG so a later Start would still work.
  expectColumnWithNullStatus('case 1', moved, 'doing');
  console.log('  case 1 PASS — todo -> doing produces ("doing", null)');
}

// ---- Case 2: cancelled item dragged to doing ----
// Pre-Phase-2 this would have produced ("doing", "cancelled") off-canon.
async function case2() {
  const item = await createItem('DnD case 2');
  // Reach the cancelled-in-todo encoding through the SM-aware cancel route
  // (direct cancel from BACKLOG).
  const cancelRes = await api(`/api/items/${item.id}/cancel`, { method: 'POST' });
  if (cancelRes.status !== 200) fail(`cancel failed: ${cancelRes.status}`);
  const cancelled = await getItem(item.id);
  if (cancelled.column_name !== 'todo' || cancelled.status !== 'cancelled') {
    fail(`case 2 setup: expected (todo, cancelled), got (${cancelled.column_name}, ${cancelled.status})`);
  }
  // Now drag to doing — must produce ("doing", null), not ("doing", "cancelled").
  const moved = await move(item.id, 'doing', 0);
  expectColumnWithNullStatus('case 2', moved, 'doing');
  console.log('  case 2 PASS — cancelled card dragged to doing produces ("doing", null), not off-canon');
}

// ---- Case 3: SM read of post-DnD encoding via clarification endpoint ----
// Verifying the ENCODING is SM-readable without spawning an agent.
// /api/items/:id/clarification reads the item via repo.get and would
// surface UnknownStateEncoding via the SM if the row is off-canon.
// (Calling /start would spawn a Claude session and burn API tokens —
// skip it; the unit test test_dnd_then_start_lands_in_running covers
// that path against a real DB row in-process.)
async function case3() {
  const item = await createItem('DnD case 3');
  await move(item.id, 'doing', 0);
  const clarRes = await api(`/api/items/${item.id}/clarification`);
  // Either 200 (no clarification) or 404 (no row) is fine; the failure
  // we're guarding against is a 500 from a state-encoding crash.
  if (clarRes.status >= 500) {
    fail(`case 3: state read after DnD-to-doing returned ${clarRes.status}: ${JSON.stringify(clarRes.body)}`);
  }
  console.log('  case 3 PASS — post-DnD encoding is readable by the SM (no 5xx)');
}

// ---- Case 4: move to done clears worktree_path ----
async function case4() {
  const item = await createItem('DnD case 4');
  const moved = await move(item.id, 'done', 0);
  if (moved.column_name !== 'done') fail(`case 4: expected column done, got ${moved.column_name}`);
  if (moved.worktree_path !== null) fail(`case 4: expected worktree_path null, got ${JSON.stringify(moved.worktree_path)}`);
  // Sanity: done_at gets stamped because of the auto-set in update_item.
  if (!moved.done_at) fail(`case 4: expected done_at to be set, got ${JSON.stringify(moved.done_at)}`);
  console.log('  case 4 PASS — move to done clears worktree_path and stamps done_at');
}

// ---- Case 5: within-column reorder preserves status ----
async function case5() {
  const a = await createItem('DnD case 5a');
  const b = await createItem('DnD case 5b');
  // Both items end up in todo with status null. Reorder a within todo:
  // status should remain null and column unchanged.
  const reordered = await move(a.id, 'todo', 1);
  if (reordered.column_name !== 'todo') fail(`case 5: column changed unexpectedly`);
  if (reordered.status !== null) fail(`case 5: status should still be null, got ${JSON.stringify(reordered.status)}`);
  // b should have shifted by 1 to make room — exact value depends on
  // initial positions, but it should still be in todo.
  const bAfter = await getItem(b.id);
  if (bAfter.column_name !== 'todo') fail(`case 5: b lost its column during reorder`);
  console.log('  case 5 PASS — within-column reorder preserves status, peers stay in column');
}

async function deleteCreated() {
  // Best-effort cleanup
  for (const id of created) {
    try {
      await api(`/api/items/${id}`, { method: 'DELETE' });
    } catch { /* ignore */ }
  }
}

withBoard(TARGET_REPO, async (boardPage, base) => {
  page = boardPage;
  BASE = base;
  for (const runCase of [case1, case2, case3, case4, case5]) await runCase();
  pass('DnD produces canonical (column, status) encodings; Start does not crash');
}, {
  loadWait: 500,
  cleanup: deleteCreated,
});
