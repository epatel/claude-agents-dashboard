"""Unit tests for src/agent/base.py — AbstractAgentSession contract."""

import pytest

from src.agent.base import AbstractAgentSession
from src.agent.session import AgentSession


class TestAbstractAgentSession:
    def test_agent_session_implements_contract(self):
        assert issubclass(AgentSession, AbstractAgentSession)

    def test_abstract_base_not_instantiable(self):
        with pytest.raises(TypeError):
            AbstractAgentSession()

    def test_stub_subclass_is_instantiable(self):
        class StubSession(AbstractAgentSession):
            def __init__(self):
                self.current_session_id = None
                self.on_error = None

            async def start(self, prompt, attachments=None, resume_session_id=None):
                pass

            async def cancel(self):
                pass

        stub = StubSession()
        assert stub.current_session_id is None

    def test_incomplete_subclass_not_instantiable(self):
        class MissingCancel(AbstractAgentSession):
            async def start(self, prompt, attachments=None, resume_session_id=None):
                pass

        with pytest.raises(TypeError):
            MissingCancel()
