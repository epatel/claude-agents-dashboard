/**
 * E2E test: AgentConfig list/dict fields round-trip through the DB as
 * real Python types (Phase 3).
 *
 * Background: tools, mcp_servers, plugins, allowed_commands, and
 * allowed_builtin_tools used to be JSON-string fields. Phase 3 promoted
 * them to typed Python collections. This test exercises the API
 * contract: PUT a config with real arrays/objects, GET it back, assert
 * the JSON response has the same shape — not a stringified JSON
 * envelope.
 *
 * No Claude agent is spawned; this is pure HTTP.
 *
 * Usage: node tests/e2e/test_config_roundtrip.mjs <target-repo-path>
 */
import { withBoard, requireTargetRepo, apiRequest, jsonInit, pass, fail } from './helpers.mjs';

const TARGET_REPO = requireTargetRepo('test_config_roundtrip.mjs');

const LIST_FIELDS = ['tools', 'plugins', 'allowed_commands', 'allowed_builtin_tools'];

let page = null;
let BASE = null;
// Initial config, restored at the end.
let savedConfig = null;

const getConfig = () => apiRequest(page, BASE, '/api/config');
const putConfig = (payload) => apiRequest(page, BASE, '/api/config', jsonInit('PUT', payload));

const isPlainObject = (v) => typeof v === 'object' && !Array.isArray(v) && v !== null;
const isEmptyArray = (v) => Array.isArray(v) && v.length === 0;
const isEmptyObject = (v) => typeof v === 'object' && Object.keys(v).length === 0;

// ---- Step 0: capture current config so we can restore it later ----
async function step0() {
  const res = await getConfig();
  if (res.status !== 200) fail(`GET /api/config returned ${res.status}`);
  savedConfig = res.body;
  // Sanity: even on a fresh DB, the typed list/dict fields must arrive
  // as JS arrays/objects, never strings.
  for (const f of LIST_FIELDS) {
    if (!Array.isArray(savedConfig[f])) {
      fail(`fresh config: field "${f}" should be an array, got ${typeof savedConfig[f]}: ${JSON.stringify(savedConfig[f])}`);
    }
  }
  if (!isPlainObject(savedConfig.mcp_servers)) {
    fail(`fresh config: "mcp_servers" should be an object, got ${JSON.stringify(savedConfig.mcp_servers)}`);
  }
  console.log('  step 0 PASS — fresh config returns typed fields, not JSON strings');
}

// ---- Step 1: PUT real arrays/objects, GET back same shape ----
async function step1() {
  const putRes = await putConfig({
    ...savedConfig,
    allowed_commands: ['git', 'npm', 'make'],
    allowed_builtin_tools: ['WebSearch'],
    tools: [],
    plugins: [],
    mcp_servers: { example: { command: 'echo', args: ['hi'] } },
  });
  if (putRes.status !== 200) fail(`PUT /api/config returned ${putRes.status}: ${JSON.stringify(putRes.body)}`);

  const getRes = await getConfig();
  if (getRes.status !== 200) fail(`GET after PUT returned ${getRes.status}`);
  const cfg = getRes.body;

  const expectArr = (field, expected) => {
    if (!Array.isArray(cfg[field])) fail(`step 1: ${field} not an array, got ${typeof cfg[field]}`);
    if (JSON.stringify(cfg[field]) !== JSON.stringify(expected)) {
      fail(`step 1: ${field} round-trip mismatch — expected ${JSON.stringify(expected)}, got ${JSON.stringify(cfg[field])}`);
    }
  };
  expectArr('allowed_commands', ['git', 'npm', 'make']);
  expectArr('allowed_builtin_tools', ['WebSearch']);
  if (cfg.mcp_servers?.example?.command !== 'echo') {
    fail(`step 1: mcp_servers round-trip lost shape: ${JSON.stringify(cfg.mcp_servers)}`);
  }
  console.log('  step 1 PASS — PUT lists/dicts, GET returns same shape');
}

// ---- Step 2: PUT empty values, GET empty defaults ----
// Phase 3 validators turn missing/empty input into empty list/dict.
async function step2() {
  const putRes = await putConfig({
    ...savedConfig,
    allowed_commands: [],
    allowed_builtin_tools: [],
    plugins: [],
    tools: [],
    mcp_servers: {},
  });
  if (putRes.status !== 200) fail(`PUT empty returned ${putRes.status}: ${JSON.stringify(putRes.body)}`);

  const cfg = (await getConfig()).body;
  for (const f of ['allowed_commands', 'allowed_builtin_tools', 'plugins', 'tools']) {
    if (!isEmptyArray(cfg[f])) fail(`step 2: ${f} should be empty array, got ${JSON.stringify(cfg[f])}`);
  }
  if (!isEmptyObject(cfg.mcp_servers)) {
    fail(`step 2: mcp_servers should be empty object, got ${JSON.stringify(cfg.mcp_servers)}`);
  }
  console.log('  step 2 PASS — empty arrays/dict round-trip as empty');
}

// ---- Step 3: tolerate JSON-string input on PUT (legacy clients) ----
// The Pydantic field_validator(mode="before") parses strings.
// This protects callers that haven't migrated from the old
// "everything is a JSON string" shape.
async function step3() {
  const putRes = await putConfig({
    ...savedConfig,
    allowed_commands: '["git"]',          // JSON string, not array
    allowed_builtin_tools: '["WebFetch"]',
    plugins: '[]',
    tools: '[]',
    mcp_servers: '{}',
  });
  if (putRes.status !== 200) {
    fail(`step 3: legacy string input rejected with ${putRes.status}: ${JSON.stringify(putRes.body)}`);
  }
  const cfg = (await getConfig()).body;
  if (!Array.isArray(cfg.allowed_commands) || cfg.allowed_commands[0] !== 'git') {
    fail(`step 3: legacy-string allowed_commands didn't parse to array, got ${JSON.stringify(cfg.allowed_commands)}`);
  }
  console.log('  step 3 PASS — legacy JSON-string input is parsed by validators');
}

async function restoreConfig() {
  if (!savedConfig) return;
  try {
    await putConfig(savedConfig);
  } catch { /* ignore */ }
}

withBoard(TARGET_REPO, async (boardPage, base) => {
  page = boardPage;
  BASE = base;
  for (const step of [step0, step1, step2, step3]) await step();
  pass('AgentConfig list/dict fields round-trip as typed Python collections');
}, {
  loadWait: 500,
  cleanup: restoreConfig,
});
