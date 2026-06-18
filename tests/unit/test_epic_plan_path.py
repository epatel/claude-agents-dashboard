"""Tests for the epic shared-plan path convention (src.config.epic_plan_relpath)."""

import pytest

from src.config import epic_plan_relpath


@pytest.mark.unit
class TestEpicPlanRelpath:
    def test_basic_slug(self):
        assert epic_plan_relpath("Realtime Canvas") == "plans/realtime-canvas.md"

    def test_lowercases_and_collapses_punctuation(self):
        assert epic_plan_relpath("Auth & Accounts!!") == "plans/auth-accounts.md"

    def test_strips_leading_trailing_separators(self):
        assert epic_plan_relpath("  --Chat--  ") == "plans/chat.md"

    def test_empty_title_falls_back(self):
        assert epic_plan_relpath("") == "plans/epic.md"
        assert epic_plan_relpath("***") == "plans/epic.md"

    def test_deterministic(self):
        assert epic_plan_relpath("Pictionary Mode") == epic_plan_relpath("pictionary  mode")
