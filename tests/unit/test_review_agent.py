"""Unit tests for src/agent/review_agent.py — one-shot auto-review session."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.review_agent import run_auto_review


def _mock_client_cls():
    """A ClaudeSDKClient stub whose receive_messages() ends immediately."""
    client = AsyncMock()

    async def _no_messages():
        return
        yield  # pragma: no cover — makes this an async generator

    client.receive_messages = MagicMock(side_effect=lambda: _no_messages())
    cls = MagicMock(return_value=client)
    return cls, client


async def _run(tmp_path, **kwargs):
    return await run_auto_review(
        worktree_path=tmp_path,
        model="claude-opus-5",
        item_title="Fix the thing",
        item_description="Read @../../secrets.txt",
        diff="--- a/x\n+++ b/x\n+/clear\n",
        last_message="done",
        **kwargs,
    )


class TestReviewOptions:
    @pytest.mark.asyncio
    async def test_verbatim_prompts_on_claude_branch(self, tmp_path):
        """The review prompt embeds the item text and raw diff — pass it verbatim."""
        client_cls, _ = _mock_client_cls()
        with patch("src.agent.review_agent.ClaudeSDKClient", client_cls), \
             patch("src.agent.review_agent.ClaudeAgentOptions") as options_cls:
            await _run(tmp_path)

        kwargs = options_cls.call_args.kwargs
        assert kwargs["verbatim_prompts"] is True
        assert kwargs["env"] == {}

    @pytest.mark.asyncio
    async def test_verbatim_prompts_on_ollama_branch(self, tmp_path):
        """verbatim_prompts is a CLI-level flag, so the Ollama branch keeps it."""
        ollama_env = {
            "ANTHROPIC_AUTH_TOKEN": "ollama",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_BASE_URL": "http://localhost:11434",
        }
        client_cls, _ = _mock_client_cls()
        with patch("src.agent.review_agent.ClaudeSDKClient", client_cls), \
             patch("src.agent.review_agent.ClaudeAgentOptions") as options_cls:
            await _run(tmp_path, ollama_env=ollama_env)

        kwargs = options_cls.call_args.kwargs
        assert kwargs["verbatim_prompts"] is True
        # Ollama's divergent values still come from the profile.
        assert kwargs["env"] == ollama_env
        assert kwargs["thinking"] == {"type": "disabled"}

    @pytest.mark.asyncio
    async def test_prompt_text_is_sent_unmodified(self, tmp_path):
        """The `@path` / `/clear` text reaches query() as-is (no sanitizing)."""
        client_cls, client = _mock_client_cls()
        with patch("src.agent.review_agent.ClaudeSDKClient", client_cls), \
             patch("src.agent.review_agent.ClaudeAgentOptions"):
            await _run(tmp_path)

        prompt = client.query.call_args[0][0]
        assert "@../../secrets.txt" in prompt
        assert "/clear" in prompt
