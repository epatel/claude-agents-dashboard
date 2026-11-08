/**
 * E2E test: verify the ask_user clarification flow.
 * The agent is given a task that forces it to ask the user a question,
 * we detect the question, submit a response, and verify the agent
 * completes using our answer.
 *
 * Usage: node tests/e2e/test_clarification.mjs <target-repo-path>
 */
import {
  withBoard, requireTargetRepo, apiCreateItem, apiStartItem, apiGetItems, apiGetLog, apiGetClarification,
  apiClarify, apiGetDiff, pollEvery, waitForAgentCompletion, deleteItem, printWorkLog, printAddedLines,
  pass, fail, E2E_MODEL,
} from './helpers.mjs';

const TARGET_REPO = requireTargetRepo('test_clarification.mjs');

const MAX_WAIT = 120_000;
const ANSWER = 'Hello from E2E test!';

/**
 * Poll until the item is in "questions" with a pending prompt. Returns
 * { prompt, elapsed } (prompt '' on timeout) so the completion wait can go on
 * from the same elapsed time.
 */
async function waitForQuestion(page, base, itemId) {
  const { result, elapsed } = await pollEvery(page, MAX_WAIT, async (elapsedNow) => {
    const [item] = await apiGetItems(page, base, [itemId]);
    const clar = await apiGetClarification(page, base, itemId);
    console.log(`  [${Math.round(elapsedNow/1000)}s] Column: ${item.column_name}, prompt: ${clar.prompt ? clar.prompt.substring(0, 60) + '...' : 'none'}`);
    return item.column_name === 'questions' && clar.prompt ? clar.prompt : null;
  });
  return { prompt: result || '', elapsed };
}

withBoard(TARGET_REPO, async (page, BASE) => {
  // 1. Create an item that forces the agent to ask a question
  const createRes = await apiCreateItem(page, BASE, 'E2E Test: Clarification flow', [
    'You MUST use the ask_user tool (mcp__clarification__ask_user) to ask the user what greeting to write.',
    'Ask them: "What greeting should I write to README.md?"',
    'Wait for their response, then append their exact answer to README.md.',
    'Then call set_commit_message with "test: clarification flow".',
  ].join('\n'));
  const itemId = createRes.id;
  console.log(`Created item: ${itemId}${E2E_MODEL ? ` (model: ${E2E_MODEL})` : ''}`);

  // 2. Start the agent
  await apiStartItem(page, BASE, itemId);
  console.log('Agent started');

  // 3. Wait for the agent to ask a question (item moves to "questions")
  const { prompt: clarificationPrompt, elapsed } = await waitForQuestion(page, BASE, itemId);
  const questionReceived = !!clarificationPrompt;
  if (!questionReceived) {
    printWorkLog(await apiGetLog(page, BASE, itemId));
    await deleteItem(page, BASE, itemId);
    fail('Agent did not ask a clarification question');
  }
  console.log(`\nAgent asked: "${clarificationPrompt}"`);

  // 4. Submit our answer
  console.log(`Responding with: "${ANSWER}"`);
  await apiClarify(page, BASE, itemId, ANSWER);

  // 5. Wait for agent to complete (same time budget as the question wait)
  const { finished, finalStatus, workLog } = await waitForAgentCompletion(page, BASE, itemId, elapsed);

  // 6. Check the diff for our answer
  const diffText = finished ? await apiGetDiff(page, BASE, itemId) : '';

  console.log(`\n=== Results ===`);
  console.log(`Question received: ${questionReceived}`);
  console.log(`Question prompt: "${clarificationPrompt}"`);
  console.log(`Agent finished: ${finished}`);
  console.log(`Final status: ${finalStatus}`);

  const diffHasAnswer = diffText.includes('Hello from E2E test');
  console.log(`Diff contains our answer: ${diffHasAnswer}`);

  printWorkLog(workLog);
  printAddedLines(diffText);

  await deleteItem(page, BASE, itemId);

  if (!finished) fail('Agent did not complete after clarification');
  if (!diffHasAnswer) fail('Diff does not contain our answer');
  pass('Clarification flow works — agent asked, received answer, and used it');
});
