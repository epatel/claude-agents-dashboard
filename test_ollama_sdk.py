#!/usr/bin/env python3
"""
Manual check: can the Claude Agent SDK use a local Ollama model as provider?

Runs one tiny query ("What is 2+2?") with the same SDK options the dashboard
uses for Ollama runs — the env from `build_ollama_env` (the manual setup from
https://docs.ollama.com/integrations/claude-code) and the local profile from
`src/agent/profiles.py` (thinking disabled, setting_sources=["local"]), plus
`verbatim_prompts=True`. All tools are off and the agent runs in a throwaway
temp directory, so it cannot touch this repo.

Not a pytest test (pytest only collects tests/). Run from the repo root:

    ./venv/bin/python test_ollama_sdk.py [model] [base_url]

The model defaults to the first local (non-":cloud") model Ollama lists; the
base URL to DEFAULT_OLLAMA_BASE_URL. Exits 1 when the run fails.
"""

import asyncio
import json
import sys
import tempfile
import urllib.request

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)

from src.agent.profiles import build_ollama_env, profile_options_kwargs, resolve_profile
from src.constants import DEFAULT_OLLAMA_BASE_URL

PROMPT = "What is 2+2? Reply with just the number."


def first_local_model(base_url: str) -> str | None:
    """The first model Ollama lists that runs locally (cloud models are skipped)."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=5) as resp:
            models = json.load(resp).get("models", [])
    except (OSError, ValueError):
        return None
    names = [m.get("name", "") for m in models]
    return next((n for n in names if n and not n.endswith(":cloud")), None)


def ollama_options(model: str, base_url: str, workdir: str) -> ClaudeAgentOptions:
    """The dashboard's Ollama SDK options, with every tool off."""
    env = build_ollama_env(base_url)
    profile = resolve_profile(env, model=model)
    return ClaudeAgentOptions(
        cwd=workdir,
        system_prompt="You are a helpful assistant. Keep responses very brief.",
        model=model,
        tools=[],
        verbatim_prompts=True,
        **profile_options_kwargs(profile),
    )


def print_assistant(message: AssistantMessage) -> None:
    for block in message.content:
        if isinstance(block, TextBlock):
            print(f"\n[Assistant] {block.text}")
        elif isinstance(block, ThinkingBlock) and block.thinking:
            print(f"\n[Thinking] {block.thinking[:200]}...")
        elif isinstance(block, ToolUseBlock):
            print(f"\n[Tool Use] {block.name}({block.input})")


def print_result(message: ResultMessage) -> None:
    print("\n--- Result ---")
    print(f"  Success: {not message.is_error}")
    print(f"  Session ID: {message.session_id}")
    if message.is_error:
        print(f"  Error: {message.result}")
    if message.total_cost_usd is not None:
        print(f"  Cost: ${message.total_cost_usd:.6f}")
    usage = message.usage or {}
    if usage:
        print(f"  Tokens: in={usage.get('input_tokens', '?')} out={usage.get('output_tokens', '?')}")


def print_system(message: SystemMessage) -> None:
    content = getattr(message, "content", "")
    if content:
        print(f"[System] {str(content)[:200]}")


async def run_query(options: ClaudeAgentOptions) -> bool:
    """Send PROMPT and print the stream until the result; True when it succeeded."""
    client = ClaudeSDKClient(options=options)
    try:
        await client.connect()
        print("SDK connected. Sending query...")
        await client.query(PROMPT)
        async for message in client.receive_messages():
            if isinstance(message, AssistantMessage):
                print_assistant(message)
            elif isinstance(message, SystemMessage):
                print_system(message)
            elif isinstance(message, ResultMessage):
                print_result(message)
                return not message.is_error
        return False
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def main() -> int:
    base_url = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OLLAMA_BASE_URL
    model = sys.argv[1] if len(sys.argv) > 1 else first_local_model(base_url)
    if not model:
        print(f"No local Ollama model found at {base_url} — pass one: test_ollama_sdk.py <model>")
        return 1
    print(f"Testing Claude Agent SDK with Ollama model: {model}")
    print(f"  ANTHROPIC_BASE_URL = {base_url}")
    print()

    with tempfile.TemporaryDirectory(prefix="ollama-sdk-check-") as workdir:
        ok = await run_query(ollama_options(model, base_url, workdir))
    print("\nDone." if ok else "\nFailed.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
