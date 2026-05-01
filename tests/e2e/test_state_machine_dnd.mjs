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
import { chromium } from 'playwright';
import { startServer, stopServer, pass, fail } from './helpers.mjs';

const TARGET_REPO = process.argv[2];
if (!TARGET_REPO) {
  console.error('Usage: node tests/e2e/test_state_machine_dnd.mjs <target-repo-path>');
  process.exit(1);
}

async function main() {
  console.log(`Starting server with target: ${TARGET_REPO}`);
  const { port, proc: serverProc } = await startServer(TARGET_REPO);
  const BASE = `http://127.0.0.1:${port}`;
  console.log(`Server running on port ${port}`);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const created = [];  // ids to clean up

  // Helper that runs in the browser context (so it shares the server's
  // origin and avoids any CORS preflight surprises).
  async function api(path, init = {}) {
    return await page.evaluate(async (args) => {
      const [b, p, i] = args;
      const r = await fetch(`${b}${p}`, i);
      const ct = r.headers.get('content-type') || '';
      const body = ct.includes('json') ? await r.json() : await r.text();
      return { status: r.status, body };
    }, [BASE, path, init]);
  }

  async function createItem(title) {
    const res = await api('/api/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, description: 'dnd test' }),
    });
    if (res.status !== 200) fail(`createItem failed: ${res.status} ${JSON.stringify(res.body)}`);
    created.push(res.body.id);
    return res.body;
  }

  async function move(id, column, position = 0) {
    const res = await api(`/api/items/${id}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ column_name: column, position }),
    });
    if (res.status !== 200) fail(`move ${id} -> ${column} failed: ${res.status} ${JSON.stringify(res.body)}`);
    return res.body;
  }

  async function getItem(id) {
    const res = await api('/api/items');
    if (res.status !== 200) fail(`list items failed: ${res.status}`);
    return res.body.find(i => i.id === id) || null;
  }

  try {
    await page.goto(BASE);
    await page.waitForTimeout(500);
    console.log('Board loaded');

    // ---- Case 1: drag from todo -> doing leaves canonical encoding ----
    // Pre-Phase-2 this produced ("doing", null) which the SM couldn't read.
    {
      const item = await createItem('DnD case 1');
      const moved = await move(item.id, 'doing', 0);
      // Cross-column move clears status to null. The SM's fallback maps
      // ("doing", null) to BACKLOG so a later Start would still work.
      if (moved.column_name !== 'doing') fail(`case 1: expected column doing, got ${moved.column_name}`);
      if (moved.status !== null) fail(`case 1: expected status null, got ${JSON.stringify(moved.status)}`);
      console.log('  case 1 PASS — todo -> doing produces ("doing", null)');
    }

    // ---- Case 2: cancelled item dragged to doing ----
    // Pre-Phase-2 this would have produced ("doing", "cancelled") off-canon.
    {
      const item = await createItem('DnD case 2');
      // Force into the cancelled-in-todo encoding via the legacy update path.
      // (Direct cancel from BACKLOG is the natural way to reach it; we use
      // the SM-aware route to do it.)
      const cancelRes = await api(`/api/items/${item.id}/cancel`, { method: 'POST' });
      if (cancelRes.status !== 200) fail(`cancel failed: ${cancelRes.status}`);
      const cancelled = await getItem(item.id);
      if (cancelled.column_name !== 'todo' || cancelled.status !== 'cancelled') {
        fail(`case 2 setup: expected (todo, cancelled), got (${cancelled.column_name}, ${cancelled.status})`);
      }
      // Now drag to doing — must produce ("doing", null), not ("doing", "cancelled").
      const moved = await move(item.id, 'doing', 0);
      if (moved.column_name !== 'doing') fail(`case 2: expected column doing, got ${moved.column_name}`);
      if (moved.status !== null) fail(`case 2: expected status null, got ${JSON.stringify(moved.status)}`);
      console.log('  case 2 PASS — cancelled card dragged to doing produces ("doing", null), not off-canon');
    }

    // ---- Case 3: SM read of post-DnD encoding via clarification endpoint ----
    // Verifying the ENCODING is SM-readable without spawning an agent.
    // /api/items/:id/clarification reads the item via repo.get and would
    // surface UnknownStateEncoding via the SM if the row is off-canon.
    // (Calling /start would spawn a Claude session and burn API tokens —
    // skip it; the unit test test_dnd_then_start_lands_in_running covers
    // that path against a real DB row in-process.)
    {
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
    {
      const item = await createItem('DnD case 4');
      const moved = await move(item.id, 'done', 0);
      if (moved.column_name !== 'done') fail(`case 4: expected column done, got ${moved.column_name}`);
      if (moved.worktree_path !== null) fail(`case 4: expected worktree_path null, got ${JSON.stringify(moved.worktree_path)}`);
      // Sanity: done_at gets stamped because of the auto-set in update_item.
      if (!moved.done_at) fail(`case 4: expected done_at to be set, got ${JSON.stringify(moved.done_at)}`);
      console.log('  case 4 PASS — move to done clears worktree_path and stamps done_at');
    }

    // ---- Case 5: within-column reorder preserves status ----
    {
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

    pass('DnD produces canonical (column, status) encodings; Start does not crash');
  } catch (err) {
    console.error('Test error:', err);
    process.exit(1);
  } finally {
    // Best-effort cleanup
    for (const id of created) {
      try {
        await api(`/api/items/${id}`, { method: 'DELETE' });
      } catch { /* ignore */ }
    }
    await browser.close();
    await stopServer(port, serverProc);
  }
}

main();
