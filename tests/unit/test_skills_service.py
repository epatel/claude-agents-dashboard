"""Unit tests for SkillsService (library install / list / enable)."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.services.skills_service import SkillsService, _valid_name, _parse_frontmatter


class TestHelpers:
    def test_name_validation_blocks_traversal(self):
        assert _valid_name("docx") and _valid_name("mcp-builder")
        for bad in ("", "../evil", "a/b", "x.y", "UP"):
            assert not _valid_name(bad)

    def test_frontmatter(self):
        fm = _parse_frontmatter("---\nname: x\ndescription: hi\n---\nbody")
        assert fm == {"name": "x", "description": "hi"}
        assert _parse_frontmatter("no frontmatter") == {}

    def test_parse_spec(self):
        assert SkillsService._parse_spec("anthropics/skills/skills/docx") == \
            ("anthropics", "skills", None, "skills/docx")
        assert SkillsService._parse_spec("o/r/path@v2") == ("o", "r", "v2", "path")
        assert SkillsService._parse_spec("https://github.com/o/r/tree/main/skills/foo") == \
            ("o", "r", "main", "skills/foo")


def _installed_skill(lib: Path, name: str, description: str = "desc"):
    (lib / name / ".claude-plugin").mkdir(parents=True)
    (lib / name / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name}))
    sd = lib / name / "skills" / name
    sd.mkdir(parents=True)
    (sd / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n")


class TestInstalledLibrary:
    def test_list_installed_with_enabled_flags(self, tmp_path):
        svc = SkillsService(library_dir=tmp_path / "lib")
        (tmp_path / "lib").mkdir()
        _installed_skill(tmp_path / "lib", "docx", "Make docx")
        _installed_skill(tmp_path / "lib", "pdf", "Make pdf")
        out = svc.list_installed(enabled=["docx"])
        by_name = {s["name"]: s for s in out}
        assert by_name["docx"]["enabled"] is True
        assert by_name["docx"]["description"] == "Make docx"
        assert by_name["pdf"]["enabled"] is False

    def test_plugin_path_guards_bad_names(self, tmp_path):
        svc = SkillsService(library_dir=tmp_path / "lib")
        (tmp_path / "lib").mkdir()
        _installed_skill(tmp_path / "lib", "docx")
        assert svc.plugin_path("docx")
        assert svc.plugin_path("../evil") is None
        assert svc.plugin_path("missing") is None

    @pytest.mark.asyncio
    async def test_remove(self, tmp_path):
        svc = SkillsService(library_dir=tmp_path / "lib")
        (tmp_path / "lib").mkdir()
        _installed_skill(tmp_path / "lib", "docx")
        assert (await svc.remove("docx"))["ok"] is True
        assert not (tmp_path / "lib" / "docx").exists()
        assert (await svc.remove("../evil"))["ok"] is False


class TestInstall:
    @pytest.mark.asyncio
    async def test_install_mirrors_folder_and_wraps_plugin(self, tmp_path):
        svc = SkillsService(library_dir=tmp_path / "lib")

        def fake_get_json(url):
            if url.endswith("/repos/anthropics/skills"):
                return {"default_branch": "main"}
            if "git/trees/main" in url:
                return {"tree": [
                    {"type": "blob", "path": "skills/docx/SKILL.md"},
                    {"type": "blob", "path": "skills/docx/reference/extra.md"},
                    {"type": "blob", "path": "skills/other/SKILL.md"},  # different skill, excluded
                ]}
            raise AssertionError(f"unexpected json url {url}")

        def fake_get(url):
            if url.endswith("skills/docx/SKILL.md"):
                return b"---\nname: docx\ndescription: Make docx files\n---\n# docx"
            if url.endswith("skills/docx/reference/extra.md"):
                return b"extra"
            raise AssertionError(f"unexpected raw url {url}")

        svc._get_json = fake_get_json
        svc._get = fake_get

        res = await svc.install("anthropics/skills/skills/docx")
        assert res["ok"] is True and res["name"] == "docx"
        assert res["description"] == "Make docx files"
        base = tmp_path / "lib" / "docx"
        assert (base / ".claude-plugin" / "plugin.json").exists()
        assert (base / "skills" / "docx" / "SKILL.md").exists()
        assert (base / "skills" / "docx" / "reference" / "extra.md").read_text() == "extra"
        # only the docx subtree was mirrored
        assert not (base / "skills" / "other").exists()
        manifest = json.loads((base / ".claude-plugin" / "plugin.json").read_text())
        assert manifest["name"] == "docx" and manifest["description"] == "Make docx files"

    @pytest.mark.asyncio
    async def test_install_rejects_bad_name(self, tmp_path):
        svc = SkillsService(library_dir=tmp_path / "lib")
        svc._get_json = lambda url: {"default_branch": "main"}
        # path resolves to a name with a dot → invalid
        res = await svc.install("o/r/bad.name@main")
        assert res["ok"] is False


class TestBrowse:
    @pytest.mark.asyncio
    async def test_browse_anthropic(self, tmp_path):
        svc = SkillsService(library_dir=tmp_path / "lib")
        svc._get_json = lambda url: {"tree": [
            {"type": "blob", "path": "skills/docx/SKILL.md"},
            {"type": "blob", "path": "skills/pdf/SKILL.md"},
            {"type": "blob", "path": "spec/README.md"},  # not a skill
        ]}
        svc._get_text = lambda url: "---\ndescription: D\n---\n"
        skills = await svc.browse("anthropic")
        names = sorted(s["name"] for s in skills)
        assert names == ["docx", "pdf"]
        assert all(s["spec"].startswith("anthropics/skills/skills/") for s in skills)
        # cached: second call returns same object
        assert await svc.browse("anthropic") is skills
