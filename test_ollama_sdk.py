#!/usr/bin/env python3
"""
One-time test: Can the Claude Agent SDK use a local Ollama model as provider?

Uses the manual setup from https://docs.ollama.com/integrations/claude-code:
  ANTHROPIC_AUTH_TOKEN=ollama
  ANTHROPIC_API_KEY=""
  ANTHROPIC_BASE_URL=http://localhost:11434

Model: qwen3.5:9b (local)
"""

import asyncio
import os
import sys

# Set environment BEFORE importing the SDK so the subprocess inherits them
os.environ["ANTHROPIC_AUTH_TOKEN"] = "ollama"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["ANTHROPIC_BASE_URL"] = "http://localhost:11434"

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)


async def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen3.5:9b"
    print(f"Testing Claude Agent SDK with Ollama model: {model}")
    print(f"  ANTHROPIC_BASE_URL = {os.environ['ANTHROPIC_BASE_URL']}")
    print()

    options = ClaudeAgentOptions(
        cwd=".",
        system_prompt="You are a helpful assistant. Keep responses very brief.",
        model=model,
        permission_mode="bypassPermissions",
    )

    client = ClaudeSDKClient(options=options)

    try:
        await client.connect()
        print("SDK connected. Sending query...")
        await client.query("What is 2+2? Reply with just the number.")

        async for message in client.receive_messages():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"\n[Assistant] {block.text}")
                    elif isinstance(block, ThinkingBlock) and block.thinking:
                        print(f"\n[Thinking] {block.thinking[:200]}...")
                    elif isinstance(block, ToolUseBlock):
                        print(f"\n[Tool Use] {block.name}({block.input})")

            elif isinstance(message, ResultMessage):
                print(f"\n--- Result ---")
                print(f"  Success: {not message.is_error}")
                print(f"  Session ID: {message.session_id}")
                if message.is_error:
                    print(f"  Error: {message.result}")
                if message.total_cost_usd is not None:
                    print(f"  Cost: ${message.total_cost_usd:.6f}")
                usage = message.usage or {}
                if usage:
                    print(f"  Tokens: in={usage.get('input_tokens', '?')} out={usage.get('output_tokens', '?')}")
                break

            elif isinstance(message, SystemMessage):
                content = getattr(message, 'content', '')
                if content:
                    print(f"[System] {str(content)[:200]}")

    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
