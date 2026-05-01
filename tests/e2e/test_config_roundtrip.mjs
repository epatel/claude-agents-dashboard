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
import { chromium } from 'playwright';
import { startServer, stopServer, pass, fail } from './helpers.mjs';

const TARGET_REPO = process.argv[2];
if (!TARGET_REPO) {
  console.error('Usage: node tests/e2e/test_config_roundtrip.mjs <target-repo-path>');
  process.exit(1);
}

async function main() {
  console.log(`Starting server with target: ${TARGET_REPO}`);
  const { port, proc: serverProc } = await startServer(TARGET_REPO);
  const BASE = `http://127.0.0.1:${port}`;
  console.log(`Server running on port ${port}`);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  async function api(path, init = {}) {
    return await page.evaluate(async (args) => {
      const [b, p, i] = args;
      const r = await fetch(`${b}${p}`, i);
      const ct = r.headers.get('content-type') || '';
      const body = ct.includes('json') ? await r.json() : await r.text();
      return { status: r.status, body };
    }, [BASE, path, init]);
  }

  // Cache initial config so we can restore it at the end.
  let savedConfig = null;

  try {
    await page.goto(BASE);
    await page.waitForTimeout(500);
    console.log('Board loaded');

    // ---- Step 0: capture current config so we can restore it later ----
    {
      const res = await api('/api/config');
      if (res.status !== 200) fail(`GET /api/config returned ${res.status}`);
      savedConfig = res.body;
      // Sanity: even on a fresh DB, the typed list/dict fields must arrive
      // as JS arrays/objects, never strings.
      const listFields = ['tools', 'plugins', 'allowed_commands', 'allowed_builtin_tools'];
      for (const f of listFields) {
        if (!Array.isArray(savedConfig[f])) {
          fail(`fresh config: field "${f}" should be an array, got ${typeof savedConfig[f]}: ${JSON.stringify(savedConfig[f])}`);
        }
      }
      if (typeof savedConfig.mcp_servers !== 'object' || Array.isArray(savedConfig.mcp_servers) || savedConfig.mcp_servers === null) {
        fail(`fresh config: "mcp_servers" should be an object, got ${JSON.stringify(savedConfig.mcp_servers)}`);
      }
      console.log('  step 0 PASS — fresh config returns typed fields, not JSON strings');
    }

    // ---- Step 1: PUT real arrays/objects, GET back same shape ----
    {
      const payload = {
        ...savedConfig,
        allowed_commands: ['git', 'npm', 'make'],
        allowed_builtin_tools: ['WebSearch'],
        tools: [],
        plugins: [],
        mcp_servers: { example: { command: 'echo', args: ['hi'] } },
      };
      const putRes = await api('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (putRes.status !== 200) fail(`PUT /api/config returned ${putRes.status}: ${JSON.stringify(putRes.body)}`);

      const getRes = await api('/api/config');
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
    {
      const payload = {
        ...savedConfig,
        allowed_commands: [],
        allowed_builtin_tools: [],
        plugins: [],
        tools: [],
        mcp_servers: {},
      };
      const putRes = await api('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (putRes.status !== 200) fail(`PUT empty returned ${putRes.status}: ${JSON.stringify(putRes.body)}`);

      const getRes = await api('/api/config');
      const cfg = getRes.body;
      for (const f of ['allowed_commands', 'allowed_builtin_tools', 'plugins', 'tools']) {
        if (!Array.isArray(cfg[f]) || cfg[f].length !== 0) {
          fail(`step 2: ${f} should be empty array, got ${JSON.stringify(cfg[f])}`);
        }
      }
      if (typeof cfg.mcp_servers !== 'object' || Object.keys(cfg.mcp_servers).length !== 0) {
        fail(`step 2: mcp_servers should be empty object, got ${JSON.stringify(cfg.mcp_servers)}`);
      }
      console.log('  step 2 PASS — empty arrays/dict round-trip as empty');
    }

    // ---- Step 3: tolerate JSON-string input on PUT (legacy clients) ----
    // The Pydantic field_validator(mode="before") parses strings.
    // This protects callers that haven't migrated from the old
    // "everything is a JSON string" shape.
    {
      const payload = {
        ...savedConfig,
        allowed_commands: '["git"]',          // JSON string, not array
        allowed_builtin_tools: '["WebFetch"]',
        plugins: '[]',
        tools: '[]',
        mcp_servers: '{}',
      };
      const putRes = await api('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (putRes.status !== 200) {
        fail(`step 3: legacy string input rejected with ${putRes.status}: ${JSON.stringify(putRes.body)}`);
      }
      const getRes = await api('/api/config');
      const cfg = getRes.body;
      if (!Array.isArray(cfg.allowed_commands) || cfg.allowed_commands[0] !== 'git') {
        fail(`step 3: legacy-string allowed_commands didn't parse to array, got ${JSON.stringify(cfg.allowed_commands)}`);
      }
      console.log('  step 3 PASS — legacy JSON-string input is parsed by validators');
    }

    pass('AgentConfig list/dict fields round-trip as typed Python collections');
  } catch (err) {
    console.error('Test error:', err);
    process.exit(1);
  } finally {
    // Restore original config
    if (savedConfig) {
      try {
        await api('/api/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(savedConfig),
        });
      } catch { /* ignore */ }
    }
    await browser.close();
    await stopServer(port, serverProc);
  }
}

main();
