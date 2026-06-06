"""Skills service — a dashboard-managed library of Agent Skills.

Agents run with setting_sources=["project"], so user ~/.claude/skills are not
ingested. We install skills into a gitignored, dashboard-local library and
deliver the *enabled* ones to agents via the SDK `plugins=` option (loads
regardless of git/worktrees/setting_sources). Each installed skill is wrapped
as a one-skill plugin so it can be toggled individually.

Library layout (gitignored in the dashboard repo):
    skill-library/<name>/
        .claude-plugin/plugin.json     # synthesized {name, version, description}
        skills/<name>/SKILL.md         # the skill (+ any sibling files)

Per-project enable lives in agent_config.enabled_skills (the DB is per-target).
See AGENT_FILES/PLAN_skills_library_2026-06-06.md.
"""

import asyncio
import json
import logging
import re
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

LIBRARY_DIRNAME = "skill-library"
NAME_RE = re.compile(r"^[a-z0-9_-]+$")
HTTP_TIMEOUT = 20
USER_AGENT = "claude-agents-dashboard-skills"

# Default browse source.
ANTHROPIC_OWNER = "anthropics"
ANTHROPIC_REPO = "skills"
ANTHROPIC_BASE = "skills"  # skill folders live under skills/<name>/


def _valid_name(name: str) -> bool:
    return bool(name) and bool(NAME_RE.match(name)) and ".." not in name


def _parse_frontmatter(text: str) -> Dict[str, Any]:
    """Return the YAML frontmatter of a SKILL.md as a dict ({} if none)."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    try:
        data = yaml.safe_load(block)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class SkillsService:
    """Install / list / remove library skills; resolve enabled ones to plugin paths."""

    def __init__(self, library_dir: Optional[Path] = None):
        repo_root = Path(__file__).resolve().parents[2]
        self.library_dir = library_dir or (repo_root / LIBRARY_DIRNAME)
        self._browse_cache: Optional[List[Dict[str, Any]]] = None

    # ---- network (patched in tests) -------------------------------------

    def _get(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read()

    def _get_json(self, url: str) -> Any:
        return json.loads(self._get(url).decode("utf-8"))

    def _get_text(self, url: str) -> str:
        return self._get(url).decode("utf-8", errors="replace")

    # ---- installed library ----------------------------------------------

    def _ensure_gitignore(self) -> None:
        gitignore = Path(__file__).resolve().parents[2] / ".gitignore"
        entry = LIBRARY_DIRNAME + "/"
        try:
            content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
            if entry in content.splitlines():
                return
            with gitignore.open("a", encoding="utf-8") as f:
                if content and not content.endswith("\n"):
                    f.write("\n")
                f.write(entry + "\n")
        except Exception as exc:
            logger.warning("skills: could not update .gitignore: %s", exc)

    def _skill_md(self, name: str) -> Optional[Path]:
        skills_dir = self.library_dir / name / "skills"
        if not skills_dir.is_dir():
            return None
        for sub in skills_dir.iterdir():
            md = sub / "SKILL.md"
            if md.exists():
                return md
        return None

    def installed_names(self) -> List[str]:
        if not self.library_dir.is_dir():
            return []
        return sorted(
            e.name for e in self.library_dir.iterdir()
            if e.is_dir() and (e / ".claude-plugin" / "plugin.json").exists()
        )

    def list_installed(self, enabled: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        enabled_set = set(enabled or [])
        out = []
        for name in self.installed_names():
            description = ""
            md = self._skill_md(name)
            if md:
                fm = _parse_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
                description = fm.get("description", "") or ""
            out.append({
                "name": name,
                "description": description,
                "enabled": name in enabled_set,
            })
        return out

    def plugin_path(self, name: str) -> Optional[str]:
        """Absolute plugin path for an installed skill, or None if missing."""
        if not _valid_name(name):
            return None
        d = self.library_dir / name
        if (d / ".claude-plugin" / "plugin.json").exists():
            return str(d.resolve())
        return None

    async def remove(self, name: str) -> Dict[str, Any]:
        if not _valid_name(name):
            return {"ok": False, "error": "invalid skill name"}
        d = self.library_dir / name
        if not d.is_dir():
            return {"ok": False, "error": "not installed"}
        await asyncio.to_thread(shutil.rmtree, d)
        return {"ok": True, "name": name}

    # ---- browse / install ------------------------------------------------

    async def browse(self, source: str = "anthropic") -> List[Dict[str, Any]]:
        """List installable skills from a public source (cached)."""
        if source != "anthropic":
            return []
        if self._browse_cache is not None:
            return self._browse_cache
        try:
            skills = await asyncio.to_thread(self._browse_anthropic)
        except Exception as exc:
            logger.warning("skills: browse failed: %s", exc)
            raise
        self._browse_cache = skills
        return skills

    def _browse_anthropic(self) -> List[Dict[str, Any]]:
        url = (f"https://api.github.com/repos/{ANTHROPIC_OWNER}/{ANTHROPIC_REPO}"
               f"/git/trees/main?recursive=1")
        tree = self._get_json(url).get("tree", [])
        names = []
        prefix = ANTHROPIC_BASE + "/"
        for node in tree:
            p = node.get("path", "")
            if node.get("type") == "blob" and p.startswith(prefix) and p.endswith("/SKILL.md"):
                name = p[len(prefix):-len("/SKILL.md")]
                if "/" not in name and _valid_name(name):
                    names.append(name)
        out = []
        for name in sorted(set(names)):
            description = ""
            try:
                raw = (f"https://raw.githubusercontent.com/{ANTHROPIC_OWNER}/"
                       f"{ANTHROPIC_REPO}/main/{prefix}{name}/SKILL.md")
                description = _parse_frontmatter(self._get_text(raw)).get("description", "") or ""
            except Exception:
                pass
            out.append({
                "name": name,
                "description": description,
                "spec": f"{ANTHROPIC_OWNER}/{ANTHROPIC_REPO}/{prefix}{name}",
            })
        return out

    @staticmethod
    def _parse_spec(spec: str):
        """Resolve a spec to (owner, repo, ref, path). Accepts:
        - owner/repo[/path][@ref]
        - https://github.com/owner/repo/tree/<ref>/<path>
        """
        spec = spec.strip()
        ref = None
        if "@" in spec:
            spec, ref = spec.rsplit("@", 1)
        if spec.startswith(("http://", "https://")):
            tail = spec.split("github.com/", 1)[-1].strip("/")
            parts = [p for p in tail.split("/") if p]
            owner, repo = parts[0], parts[1]
            path = ""
            if len(parts) > 2 and parts[2] in ("tree", "blob"):
                ref = ref or (parts[3] if len(parts) > 3 else None)
                path = "/".join(parts[4:])
            else:
                path = "/".join(parts[2:])
            return owner, repo, ref, path
        parts = [p for p in spec.split("/") if p]
        owner, repo = parts[0], parts[1]
        path = "/".join(parts[2:])
        return owner, repo, ref, path

    async def install(self, spec: str) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self._install_sync, spec)
        except Exception as exc:
            logger.warning("skills: install failed for %r: %s", spec, exc)
            return {"ok": False, "error": str(exc)}

    def _install_sync(self, spec: str) -> Dict[str, Any]:
        owner, repo, ref, path = self._parse_spec(spec)
        if not ref:
            info = self._get_json(f"https://api.github.com/repos/{owner}/{repo}")
            ref = info.get("default_branch", "main")
        name = (path.rstrip("/").split("/")[-1] if path else repo).lower()
        if not _valid_name(name):
            return {"ok": False, "error": f"invalid skill name '{name}'"}

        tree = self._get_json(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}?recursive=1"
        ).get("tree", [])
        prefix = (path.rstrip("/") + "/") if path else ""
        blobs = [n for n in tree if n.get("type") == "blob" and n.get("path", "").startswith(prefix)]
        if not blobs:
            return {"ok": False, "error": "no files found at that path"}

        dest_root = self.library_dir / name
        self._ensure_gitignore()
        if dest_root.exists():
            shutil.rmtree(dest_root)
        skill_dir = dest_root / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        description = ""
        for node in blobs:
            rel = node["path"][len(prefix):]
            if not rel or rel.endswith("/"):
                continue
            raw = self._get(
                f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{node['path']}"
            )
            target = skill_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            if rel == "SKILL.md":
                description = _parse_frontmatter(raw.decode("utf-8", errors="replace")).get("description", "") or ""

        manifest_dir = dest_root / ".claude-plugin"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "plugin.json").write_text(
            json.dumps({"name": name, "version": "1.0.0", "description": description}, indent=2),
            encoding="utf-8",
        )
        return {"ok": True, "name": name, "description": description}
