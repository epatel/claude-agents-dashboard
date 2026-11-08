/**
 * E2E test: verify an agent can modify a file in its worktree.
 * The agent appends a timestamp and "appended by e2e test" to README.md,
 * then we check the diff to confirm the change was made.
 *
 * Usage: node tests/e2e/test_append_readme.mjs <target-repo-path>
 */
import {
  withBoard, requireTargetRepo, runAgentTask, apiGetDiff, deleteItem, printWorkLog, printAddedLines, pass, fail,
} from './helpers.mjs';

const TARGET_REPO = requireTargetRepo('test_append_readme.mjs');

withBoard(TARGET_REPO, async (page, BASE) => {
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
  const diffText = finished ? await apiGetDiff(page, BASE, itemId) : '';

  console.log(`\n=== Results ===`);
  console.log(`Final status: ${finalStatus}`);
  console.log(`Agent finished: ${finished}`);

  const diffHasAppend = diffText.includes('appended by e2e test');
  const diffHasTimestamp = /\d{4}-\d{2}-\d{2}/.test(diffText);
  console.log(`Diff contains "appended by e2e test": ${diffHasAppend}`);
  console.log(`Diff contains timestamp: ${diffHasTimestamp}`);
  printAddedLines(diffText);

  await deleteItem(page, BASE, itemId);

  if (!finished) fail('Agent did not complete');
  if (!diffHasAppend) fail('Diff does not contain "appended by e2e test"');
  if (!diffHasTimestamp) fail('Diff does not contain a timestamp');
  pass('Agent appended timestamp and text to README.md');
});
