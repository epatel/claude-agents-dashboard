/**
 * E2E test: verify agents can use Bash commands (ls, wc) without
 * being blocked by the allowed_tools whitelist.
 *
 * Usage: node tests/e2e/test_allowed_tools.mjs <target-repo-path>
 */
import { withBoard, requireTargetRepo, runAgentTask, deleteItem, printWorkLog, pass, fail } from './helpers.mjs';

const TARGET_REPO = requireTargetRepo('test_allowed_tools.mjs');

const DENIAL_MARKERS = ['denied', 'not allowed', 'not in the allowed'];

/** Scan the work log: was Bash used, and was any command denied? Prints each denial. */
function scanBashUse(workLog) {
  let bashUsed = false;
  let bashDenied = false;
  for (const entry of workLog) {
    const msg = entry.message || entry.content || '';
    if (msg.toLowerCase().includes('bash') || ['`ls`', '`wc'].some(m => msg.includes(m))) bashUsed = true;
    if (DENIAL_MARKERS.some(m => msg.includes(m))) {
      bashDenied = true;
      console.log(`  DENIED: ${msg.substring(0, 150)}`);
    }
  }
  return { bashUsed, bashDenied };
}

withBoard(TARGET_REPO, async (page, BASE) => {
  const { finished, workLog, itemId } = await runAgentTask(page, BASE, {
    title: 'E2E Test: Run ls and wc',
    description: 'Run these exact commands:\n1. ls\n2. wc -l README.md\n\nReport the output. Then call set_commit_message with "test: verify bash commands work".',
  });

  const { bashUsed, bashDenied } = scanBashUse(workLog);

  console.log(`\n=== Results ===`);
  console.log(`Bash tool used: ${bashUsed}`);
  console.log(`Bash denied: ${bashDenied}`);
  printWorkLog(workLog);

  await deleteItem(page, BASE, itemId);

  if (bashDenied) fail('Bash commands were denied');
  if (!finished) fail('Agent did not complete');
  pass('Agent ran Bash commands without being blocked');
});
