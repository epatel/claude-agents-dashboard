"""Unit tests for ClaudeAgentSession.start() — SDK options and wiring.

Split out of test_session.py. Every test patches ``src.agent.session.ClaudeSDKClient``
and ``src.agent.session.ClaudeAgentOptions`` and inspects the options kwargs.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.session import ClaudeAgentSession

OLLAMA_ENV = {
    "ANTHROPIC_AUTH_TOKEN": "ollama",
    "ANTHROPIC_API_KEY": "",
    "ANTHROPIC_BASE_URL": "http://localhost:11434",
}
CLAUDE_MD_TEXT = "PROJECT CONVENTIONS: use tabs."


class TestStart:
    @pytest.fixture(autouse=True)
    def _patched_sdk(self, tmp_path):
        """Patch the SDK client/options classes; expose them and the worktree on self."""
        with patch("src.agent.session.ClaudeAgentOptions") as options_cls, \
                patch("src.agent.session.ClaudeSDKClient") as client_cls:
            self.client = AsyncMock()
            client_cls.return_value = self.client
            self.options_cls = options_cls
            self.tmp = tmp_path
            yield

    async def _start(self, prompt="test", resume_session_id=None, **session_kwargs):
        """Start a session in the tmp worktree; return the ClaudeAgentOptions kwargs."""
        session = ClaudeAgentSession(
            worktree_path=self.tmp,
            system_prompt=session_kwargs.pop("system_prompt", "You are a helpful agent."),
            **session_kwargs,
        )
        try:
            await session.start(prompt, resume_session_id=resume_session_id)
        except Exception:
            pass
        return self.options_cls.call_args.kwargs

    async def _start_ollama(self, **session_kwargs):
        session_kwargs.setdefault("model", "qwen3.5")
        session_kwargs.setdefault("local_env", OLLAMA_ENV)
        return await self._start(**session_kwargs)

    async def _system_prompt(self, ollama=False, **session_kwargs):
        start = self._start_ollama if ollama else self._start
        return (await start(**session_kwargs))["system_prompt"]

    def _write_claude_md(self):
        (self.tmp / "CLAUDE.md").write_text(CLAUDE_MD_TEXT)

    # --- client wiring ---

    async def test_start_creates_client_and_connects(self):
        await self._start("Do the thing")
        self.client.connect.assert_called_once()

    async def test_start_calls_query_with_prompt(self):
        await self._start("my prompt text")
        self.client.query.assert_called_once()
        prompt_sent = self.client.query.call_args[0][0]
        assert "my prompt text" in prompt_sent

    async def test_start_passes_cwd_to_options(self):
        kwargs = await self._start()
        assert self.options_cls.called
        assert kwargs["cwd"] == self.tmp

    async def test_start_sets_resume_options(self):
        await self._start("resume task", resume_session_id="prev-session-xyz")
        options_obj = self.options_cls.return_value
        assert options_obj.resume == "prev-session-xyz"
        assert options_obj.continue_conversation is True

    # --- plain option values ---

    @pytest.mark.parametrize(
        ("session_kwargs", "key", "expected"),
        [
            pytest.param({"model": "claude-opus-4"}, "model", "claude-opus-4",
                         id="test_start_passes_model_to_options"),
            pytest.param({}, "permission_mode", "acceptEdits",
                         id="test_start_permission_mode_accept_edits"),
            pytest.param({}, "setting_sources", ["project"],
                         id="test_start_sets_setting_sources"),
            # When local_env is None, env should be an empty dict (SDK default).
            pytest.param({}, "env", {}, id="test_start_ollama_env_none_passes_empty_dict"),
        ],
    )
    async def test_start_option_value(self, session_kwargs, key, expected):
        kwargs = await self._start(**session_kwargs)
        assert kwargs.get(key) == expected

    async def test_start_includes_bash_in_allowed_tools(self):
        kwargs = await self._start()
        assert "Bash" in kwargs.get("allowed_tools", [])

    async def test_start_passes_verbatim_prompts(self):
        """Prompts go to the CLI verbatim — no `@path` expansion, no slash dispatch.

        The prompt is built from the board item's own title/description, so
        text like `@../../etc/passwd` or a leading `/clear` must stay text.
        """
        kwargs = await self._start("/clear and read @../../secrets.txt")
        assert kwargs["verbatim_prompts"] is True

    # --- MCP servers ---

    @pytest.mark.parametrize(
        ("session_kwargs", "server", "present"),
        [
            pytest.param(
                {"mcp_enabled": True,
                 "mcp_servers": json.dumps({"my_tool": {"command": "python", "args": ["-m", "my_tool"]}})},
                "my_tool", True, id="test_start_with_mcp_servers_from_config"),
            pytest.param(
                {"mcp_enabled": False,
                 "mcp_servers": json.dumps({"ignored_tool": {"command": "python"}})},
                "ignored_tool", False, id="test_start_mcp_disabled_ignores_servers"),
            pytest.param({"on_clarify": AsyncMock()}, "clarification", True,
                         id="test_start_clarification_server_registered_when_callback"),
            pytest.param({}, "clarification", False,  # no on_clarify
                         id="test_start_no_clarification_server_without_callback"),
        ],
    )
    async def test_start_mcp_server_registration(self, session_kwargs, server, present):
        mcp = (await self._start(**session_kwargs)).get("mcp_servers") or {}
        assert (server in mcp) is present

    # --- system prompt notes ---

    async def test_start_system_prompt_augmented(self):
        sp = await self._system_prompt(system_prompt="Base instructions.")
        assert "Base instructions." in sp
        assert str(self.tmp) in sp  # cwd_note injected
        # lifecycle_note: tells the agent completion is automatic, so it doesn't
        # flail trying to "close" the card (the Ollama failure mode).
        assert "AUTOMATICALLY" in sp
        assert "mcp__inloop__" in sp

    async def test_start_injects_own_item_id(self):
        """When item_id is set, the system prompt tells the agent its own card."""
        sp = await self._system_prompt(item_id="card-42")
        assert "card-42" in sp
        assert "who_am_i" in sp

    async def test_start_injects_shared_plan_note_when_present(self):
        """A project-plan.md in the worktree surfaces the read-first/update note."""
        (self.tmp / "project-plan.md").write_text("# Plan\n")
        sp = await self._system_prompt()
        assert "SHARED PROJECT PLAN" in sp
        assert "project-plan.md" in sp

    async def test_start_injects_epic_plan_note_when_present(self):
        """An item's epic plan file surfaces an EPIC PLAN note alongside the root one."""
        (self.tmp / "project-plan.md").write_text("# Plan\n")
        (self.tmp / "plans").mkdir()
        (self.tmp / "plans" / "realtime-canvas.md").write_text("# Epic plan\n")
        sp = await self._system_prompt(epic_plan_relpath="plans/realtime-canvas.md")
        assert "EPIC PLAN" in sp
        assert "plans/realtime-canvas.md" in sp
        # Coexists with the project-wide plan note.
        assert "SHARED PROJECT PLAN" in sp

    @pytest.mark.parametrize(
        ("session_kwargs", "absent"),
        [
            # No item_id → no 'YOUR BOARD ITEM' note (back-compat for callers that don't set it).
            pytest.param({}, "YOUR BOARD ITEM", id="test_start_omits_item_note_without_item_id"),
            # No project-plan.md → no shared-plan note (don't invent a convention).
            pytest.param({}, "SHARED PROJECT PLAN",
                         id="test_start_omits_shared_plan_note_when_absent"),
            # A configured epic relpath with no file on disk → no EPIC PLAN note.
            pytest.param({"epic_plan_relpath": "plans/realtime-canvas.md"}, "EPIC PLAN",
                         id="test_start_omits_epic_plan_note_when_file_absent"),
        ],
    )
    async def test_start_omits_note(self, session_kwargs, absent):
        assert absent not in await self._system_prompt(**session_kwargs)

    async def test_start_ollama_gets_stronger_lifecycle_note(self):
        """Ollama runs get the blunt 'stop calling tools to finish' addendum."""
        assert "TO FINISH THIS TASK" in await self._system_prompt(ollama=True)

    async def test_start_non_ollama_omits_stronger_lifecycle_note(self):
        """Non-Ollama runs get the general note but not the blunt Ollama addendum."""
        sp = await self._system_prompt()
        assert "AUTOMATICALLY" in sp  # general lifecycle note present
        assert "TO FINISH THIS TASK" not in sp  # Ollama addendum absent

    # --- CLAUDE.md injection (Ollama-only toggle) ---

    async def test_start_ollama_injects_claude_md_when_enabled(self):
        """With ollama_load_claude_md on, the worktree CLAUDE.md is injected
        into the system prompt (the Ollama path's setting_sources=['local']
        does not auto-load it)."""
        self._write_claude_md()
        sp = await self._system_prompt(ollama=True, load_claude_md=True)
        assert CLAUDE_MD_TEXT in sp
        assert "Project CLAUDE.md" in sp

    @pytest.mark.parametrize(
        ("ollama", "session_kwargs"),
        [
            # Default (toggle off): CLAUDE.md is NOT injected, keeping context lean.
            pytest.param(True, {}, id="test_start_ollama_omits_claude_md_by_default"),
            # The flag only affects Ollama runs; Claude runs auto-load CLAUDE.md via
            # setting_sources=['project'] and must not double-inject it.
            pytest.param(False, {"model": "claude-opus-4-8", "load_claude_md": True},
                         id="test_start_non_ollama_ignores_claude_md_flag"),
        ],
    )
    async def test_start_claude_md_not_injected(self, ollama, session_kwargs):
        self._write_claude_md()
        assert CLAUDE_MD_TEXT not in await self._system_prompt(ollama=ollama, **session_kwargs)

    # --- Ollama profile options ---

    async def test_start_ollama_excludes_user_settings(self):
        """Ollama runs must NOT load `user` settings, or global PreToolUse hooks
        (e.g. the RTK command-rewriter) leak in and mangle command output."""
        sources = (await self._start_ollama()).get("setting_sources")
        assert sources is not None, "Ollama must pass an explicit setting_sources to exclude user hooks"
        assert "user" not in sources

    async def test_start_ollama_disables_thinking(self):
        """Ollama returns unsigned thinking blocks that crash on replay, so
        thinking must be explicitly disabled."""
        assert (await self._start_ollama()).get("thinking") == {"type": "disabled"}

    async def test_start_passes_verbatim_prompts_for_ollama(self):
        """verbatim_prompts is a CLI-level flag — the Ollama profile keeps it too."""
        kwargs = await self._start_ollama()
        assert kwargs["verbatim_prompts"] is True
        # The profile still supplies its own divergent values alongside it.
        assert kwargs["env"] == OLLAMA_ENV

    @pytest.mark.parametrize(
        ("model", "base_url"),
        [
            # Ollama env vars are forwarded to ClaudeAgentOptions.env.
            pytest.param("qwen3.5", "http://localhost:11434",
                         id="test_start_passes_ollama_env_to_options"),
            # Ollama running on a custom host/port is forwarded correctly.
            pytest.param("llama3.2", "http://192.168.1.100:11434",
                         id="test_start_ollama_env_custom_base_url"),
        ],
    )
    async def test_start_forwards_ollama_env(self, model, base_url):
        local_env = {**OLLAMA_ENV, "ANTHROPIC_BASE_URL": base_url}
        kwargs = await self._start_ollama(model=model, local_env=local_env)
        assert kwargs["env"] == local_env
        assert kwargs["env"]["ANTHROPIC_BASE_URL"] == base_url
        assert kwargs["model"] == model
