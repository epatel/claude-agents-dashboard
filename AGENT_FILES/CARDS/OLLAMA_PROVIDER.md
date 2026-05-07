# Ollama as a Provider for the Claude Agent SDK

> **Load when**: working on Ollama integration, model selection, or the `--experimental` flag.
> **Skip when**: changes don't touch model providers or `AgentConfig.model`.

**Date tested**: 2026-04-12
**Last reviewed**: 2026-05-01 (no functional changes since last test; the `AgentConfig` Phase 3 refactor preserves `ollama_enabled` / `ollama_base_url` semantics)
**Status**: Working ✓

## Overview

The Claude Agent SDK can use a local Ollama instance as its model provider. Ollama exposes an Anthropic-compatible API at `/v1/messages`, which the SDK calls transparently when configured via environment variables.

## Setup

Three environment variables redirect the SDK to Ollama:

```bash
export ANTHROPIC_AUTH_TOKEN=ollama
export ANTHROPIC_API_KEY=""
export ANTHROPIC_BASE_URL=http://localhost:11434
```

Then pass any Ollama model name as the `model` parameter:

```python
options = ClaudeAgentOptions(
    model="qwen3.5:9b",
    cwd=".",
    system_prompt="...",
    permission_mode="bypassPermissions",
)
```

Reference: https://docs.ollama.com/integrations/claude-code

## Test Results

### Successful run (qwen3.5:9b)

- SDK connected and sent a query to local Ollama
- Got a valid response with thinking block and assistant text
- Session ID assigned correctly
- Token counts reported: ~33,600 input / 86–170 output
- Cost reported as ~$0.10 (phantom — Ollama is free locally, but the SDK calculates Anthropic pricing)

### Verification that Ollama was actually used

1. **`ollama ps`** confirmed `qwen3.5:9b` loaded in memory after the test
2. **Wrong port test** (`ANTHROPIC_BASE_URL=http://localhost:99999`): SDK failed with `"http://localhost:99999/v1/messages?beta=true" cannot be parsed as a URL` — proving all API calls route through `ANTHROPIC_BASE_URL`
3. **Correct port**: SDK hits `http://localhost:11434/v1/messages` (Ollama's Anthropic-compatible endpoint) and succeeds

### Identity quirk

The model roleplays as Claude because the SDK injects Claude's system prompt. Asking "what model are you?" gets a Claude answer even though the inference is 100% local Qwen. This is cosmetic — the actual computation runs on Ollama.

## Available Local Models (as of test date)

| Model | Size |
|---|---|
| qwen3.5:9b | 6.6 GB |
| gpt-oss:20b | 13 GB |
| llama3.2:latest | 2.0 GB |
| llava:latest | 4.7 GB |
| codellama:7b-code-q4_K_M | 4.1 GB |
| exaone-deep:7.8b | 4.8 GB |
| dolphin-llama3:latest | 4.7 GB |
| gemma3:12b | 8.1 GB |

Ollama recommends at least 64k context window. Their recommended models for Claude Code integration: `qwen3.5`, `kimi-k2.5:cloud`, `glm-5:cloud`, `glm-4.7-flash`.

## Integration with the Dashboard

Ollama is fully integrated into the dashboard as an experimental feature. Enable it with:

```bash
./run.sh /path/to/project --experimental
```

### How it works

1. **Migration 016** adds `ollama_enabled` and `ollama_base_url` columns to `agent_config`
2. **Agent config dialog** exposes Ollama toggle and base URL setting
3. **Dynamic model discovery** — the dashboard queries Ollama's REST API (`/api/tags`) to populate model dropdowns with available local models and their sizes
4. **Connection status indicator** — the header shows Ollama connection status (connected/disconnected)
5. **Provider badges** — cards display provider badges (Claude vs Ollama) based on the selected model
6. **Per-agent env injection** — `session.py` sets `ANTHROPIC_AUTH_TOKEN=ollama`, `ANTHROPIC_API_KEY=""`, and `ANTHROPIC_BASE_URL` in the subprocess environment when an Ollama model is selected
7. **Model size info** — dropdowns show model file sizes alongside names

### Architecture

- `constants.py` — `AVAILABLE_MODELS` list uses `(model_id, display_name, experimental)` tuples; Ollama models are discovered dynamically at runtime
- `session.py` — Ollama env passthrough via subprocess environment override
- `session_service.py` — Reads Ollama config from agent_config and passes to session creation
- `routes.py` — `/api/ollama/models` endpoint for dynamic model discovery; `/api/ollama/status` for connection checking

## Test Script

The test script is at `test_ollama_sdk.py` in the project root. Usage:

```bash
source venv/bin/activate
python test_ollama_sdk.py              # defaults to qwen3.5:9b
python test_ollama_sdk.py gemma3:12b   # try another model
```

---

**See also**: [ARCHITECTURE](ARCHITECTURE.md) (`SessionService` is where the provider routing lives).
