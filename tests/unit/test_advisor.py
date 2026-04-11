"""Tests for the Sonnet + Advisor model configuration."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.constants import AVAILABLE_MODELS
from src.services.session_service import SessionService


class TestAdvisorModelConstants:
    """Verify advisor model is defined in constants."""

    def test_advisor_model_exists(self):
        assert "CLAUDE_SONNET_4_ADVISOR" in AVAILABLE_MODELS

    def test_advisor_model_has_suffix(self):
        model = AVAILABLE_MODELS["CLAUDE_SONNET_4_ADVISOR"]
        assert model.endswith("+advisor")

    def test_advisor_model_contains_sonnet(self):
        model = AVAILABLE_MODELS["CLAUDE_SONNET_4_ADVISOR"]
        assert "sonnet" in model


class TestSessionServiceAdvisorParsing:
    """Test that SessionService correctly parses +advisor suffix."""

    async def test_advisor_suffix_detected(self, temp_dir):
        service = SessionService()
        session = await service.create_session(
            item_id="test-1",
            worktree_path=temp_dir,
            config={},
            model="claude-sonnet-4-20250514+advisor",
        )
        assert session.use_advisor is True

    async def test_advisor_suffix_stripped_from_model(self, temp_dir):
        service = SessionService()
        session = await service.create_session(
            item_id="test-2",
            worktree_path=temp_dir,
            config={},
            model="claude-sonnet-4-20250514+advisor",
        )
        assert session.model == "claude-sonnet-4-20250514"
        assert "+advisor" not in (session.model or "")

    async def test_no_advisor_without_suffix(self, temp_dir):
        service = SessionService()
        session = await service.create_session(
            item_id="test-3",
            worktree_path=temp_dir,
            config={},
            model="claude-sonnet-4-20250514",
        )
        assert session.use_advisor is False

    async def test_no_advisor_when_model_is_none(self, temp_dir):
        service = SessionService()
        session = await service.create_session(
            item_id="test-4",
            worktree_path=temp_dir,
            config={},
            model=None,
        )
        assert session.use_advisor is False

    async def test_advisor_from_config_model(self, temp_dir):
        """When model comes from config instead of parameter."""
        service = SessionService()
        session = await service.create_session(
            item_id="test-5",
            worktree_path=temp_dir,
            config={"model": "claude-sonnet-4-20250514+advisor"},
            model=None,
        )
        assert session.use_advisor is True
        assert session.model == "claude-sonnet-4-20250514"


class TestAgentSessionAdvisorConfig:
    """Test that AgentSession correctly configures the advisor subagent."""

    def test_use_advisor_stored(self):
        from src.agent.session import AgentSession

        session = AgentSession(
            worktree_path=Path("/tmp/test"),
            system_prompt="test",
            model="claude-sonnet-4-20250514",
            use_advisor=True,
        )
        assert session.use_advisor is True

    def test_no_advisor_by_default(self):
        from src.agent.session import AgentSession

        session = AgentSession(
            worktree_path=Path("/tmp/test"),
            system_prompt="test",
            model="claude-sonnet-4-20250514",
        )
        assert session.use_advisor is False

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    async def test_start_passes_advisor_agents_to_options(
        self, mock_options_cls, mock_client_cls, temp_dir
    ):
        """When use_advisor=True, agents dict with Opus advisor must reach ClaudeAgentOptions."""
        from src.agent.session import AgentSession

        mock_client = AsyncMock()
        mock_client.create_session.return_value = AsyncMock(
            session_id="sess-123",
            result=MagicMock(text="done"),
        )
        mock_client_cls.return_value = mock_client

        session = AgentSession(
            worktree_path=temp_dir,
            system_prompt="test",
            model="claude-sonnet-4-20250514",
            use_advisor=True,
            on_complete=AsyncMock(),
        )

        # Use a real AgentDefinition (not mocked) so we can inspect it
        try:
            await session.start("Do something")
        except Exception:
            pass  # We only care about how options were constructed

        # Verify ClaudeAgentOptions was called
        assert mock_options_cls.called, "ClaudeAgentOptions was never called"
        call_kwargs = mock_options_cls.call_args.kwargs

        # Verify agents dict was passed (not None)
        agents = call_kwargs.get("agents")
        assert agents is not None, "agents should not be None when advisor is enabled"
        assert "advisor" in agents, "agents dict must contain 'advisor' key"

        # Verify the advisor AgentDefinition has correct properties
        advisor_def = agents["advisor"]
        assert advisor_def.model == "opus", f"Advisor model should be 'opus', got '{advisor_def.model}'"
        assert advisor_def.description, "Advisor should have a description"
        assert advisor_def.prompt, "Advisor should have a prompt"

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    async def test_start_no_agents_without_advisor(
        self, mock_options_cls, mock_client_cls, temp_dir
    ):
        """When use_advisor=False, agents=None must be passed to ClaudeAgentOptions."""
        from src.agent.session import AgentSession

        mock_client = AsyncMock()
        mock_client.create_session.return_value = AsyncMock(
            session_id="sess-456",
            result=MagicMock(text="done"),
        )
        mock_client_cls.return_value = mock_client

        session = AgentSession(
            worktree_path=temp_dir,
            system_prompt="test",
            model="claude-sonnet-4-20250514",
            use_advisor=False,
            on_complete=AsyncMock(),
        )

        try:
            await session.start("Do something")
        except Exception:
            pass

        assert mock_options_cls.called, "ClaudeAgentOptions was never called"
        call_kwargs = mock_options_cls.call_args.kwargs
        assert call_kwargs.get("agents") is None, "agents should be None when advisor is disabled"

    @patch("src.agent.session.ClaudeSDKClient")
    @patch("src.agent.session.ClaudeAgentOptions")
    async def test_advisor_model_is_sonnet_not_advisor_string(
        self, mock_options_cls, mock_client_cls, temp_dir
    ):
        """The main agent model must be plain sonnet (no +advisor leak)."""
        from src.agent.session import AgentSession

        mock_client = AsyncMock()
        mock_client.create_session.return_value = AsyncMock(
            session_id="sess-789",
            result=MagicMock(text="done"),
        )
        mock_client_cls.return_value = mock_client

        session = AgentSession(
            worktree_path=temp_dir,
            system_prompt="test",
            model="claude-sonnet-4-20250514",  # Already stripped by SessionService
            use_advisor=True,
            on_complete=AsyncMock(),
        )

        try:
            await session.start("Do something")
        except Exception:
            pass

        assert mock_options_cls.called
        call_kwargs = mock_options_cls.call_args.kwargs
        assert call_kwargs.get("model") == "claude-sonnet-4-20250514"
        assert "+advisor" not in (call_kwargs.get("model") or "")
