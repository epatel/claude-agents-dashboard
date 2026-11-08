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
from typing import Any, Dict, List, NamedTuple, Optional

import yaml

from ..git.operations import validate_file_path

logger = logging.getLogger(__name__)

LIBRARY_DIRNAME = "skill-library"
NAME_RE = re.compile(r"^[a-z0-9_-]+$")
HTTP_TIMEOUT = 20
USER_AGENT = "claude-agents-dashboard-skills"
# Cap on a single HTTP response. Skills are text files; a remote repo we do not
# control must not be able to make an install write an unbounded amount of data.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

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


def _description_of(skill_md: str) -> str:
    """The ``description`` from a SKILL.md's frontmatter ('' if none)."""
    return _parse_frontmatter(skill_md).get("description", "") or ""


class RepoRef(NamedTuple):
    """A GitHub repo at a resolved ref."""
    owner: str
    repo: str
    ref: str

    def raw_url(self, path: str) -> str:
        return f"https://raw.githubusercontent.com/{self.owner}/{self.repo}/{self.ref}/{path}"


def _is_blob_under(node: Dict[str, Any], prefix: str) -> bool:
    """True for a tree node that is a file (blob) whose path starts with ``prefix``."""
    return node.get("type") == "blob" and node.get("path", "").startswith(prefix)


def _is_skill_md_under(node: Dict[str, Any], prefix: str) -> bool:
    """True for a tree blob named SKILL.md (at any depth) whose path starts with ``prefix``."""
    if not _is_blob_under(node, prefix):
        return False
    p = node.get("path", "")
    return p.endswith("/SKILL.md") or p == "SKILL.md"


def _top_level_skill_names(tree: List[Dict[str, Any]], prefix: str) -> List[str]:
    """Sorted names of the skills directly under ``prefix`` (``<prefix><name>/SKILL.md``)."""
    names = set()
    for node in tree:
        p = node.get("path", "")
        if not _is_blob_under(node, prefix) or not p.endswith("/SKILL.md"):
            continue
        name = p[len(prefix):-len("/SKILL.md")]
        if "/" not in name and _valid_name(name):
            names.add(name)
    return sorted(names)


def _parse_github_url(url: str, ref: Optional[str]):
    """(owner, repo, ref, path) from a github.com URL; a /tree/<ref>/ or /blob/<ref>/
    segment supplies the ref unless ``ref`` (from an ``@ref`` suffix) is set."""
    tail = url.split("github.com/", 1)[-1].strip("/")
    parts = [p for p in tail.split("/") if p]
    owner, repo = parts[0], parts[1]
    if len(parts) > 2 and parts[2] in ("tree", "blob"):
        ref = ref or (parts[3] if len(parts) > 3 else None)
        return owner, repo, ref, "/".join(parts[4:])
    return owner, repo, ref, "/".join(parts[2:])


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
            # Read one byte past the cap so an oversized body is detected
            # rather than silently truncated.
            data = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError(
                f"response from {url} exceeds {MAX_RESPONSE_BYTES} bytes"
            )
        return data

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
            source = ""
            manifest = self.library_dir / name / ".claude-plugin" / "plugin.json"
            try:
                source = json.loads(manifest.read_text(encoding="utf-8")).get("source", "") or ""
            except Exception:
                pass
            out.append({
                "name": name,
                "description": description,
                "source": source,
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
        tree = self._repo_tree(ANTHROPIC_OWNER, ANTHROPIC_REPO, "main")
        prefix = ANTHROPIC_BASE + "/"
        out = []
        for name in _top_level_skill_names(tree, prefix):
            raw = (f"https://raw.githubusercontent.com/{ANTHROPIC_OWNER}/"
                   f"{ANTHROPIC_REPO}/main/{prefix}{name}/SKILL.md")
            out.append({
                "name": name,
                "description": self._remote_description(raw),
                "spec": f"{ANTHROPIC_OWNER}/{ANTHROPIC_REPO}/{prefix}{name}",
            })
        return out

    # ---- GitHub reads shared by browse / discover / install ---------------

    def _resolve_ref(self, owner: str, repo: str, ref: Optional[str]) -> str:
        """``ref`` if given, else the repo's default branch (asks GitHub)."""
        if ref:
            return ref
        info = self._get_json(f"https://api.github.com/repos/{owner}/{repo}")
        return info.get("default_branch", "main")

    def _repo_tree(self, owner: str, repo: str, ref: str) -> List[Dict[str, Any]]:
        """Every node of the repo's tree at ``ref`` (recursive)."""
        return self._get_json(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}?recursive=1"
        ).get("tree", [])

    def _remote_description(self, raw_url: str) -> str:
        """The frontmatter description of a remote SKILL.md ('' if it can't be read)."""
        try:
            return _description_of(self._get_text(raw_url))
        except Exception:
            return ""

    async def discover(self, spec: str) -> List[Dict[str, Any]]:
        """Find every skill (a folder with a SKILL.md) in a repo/path.

        Accepts a bare repo (owner/repo or URL) or a sub-path; returns one entry
        per SKILL.md found, each with a fully-resolved install `spec` pinned to
        the ref. A single exact skill path returns one entry.
        """
        return await asyncio.to_thread(self._discover_sync, spec)

    def _discover_sync(self, spec: str) -> List[Dict[str, Any]]:
        owner, repo, ref, path = self._parse_spec(spec)
        ref = self._resolve_ref(owner, repo, ref)
        tree = self._repo_tree(owner, repo, ref)
        prefix = (path.rstrip("/") + "/") if path else ""
        source = RepoRef(owner, repo, ref)
        found = []
        for node in tree:
            entry = self._discovered_skill(node, prefix, source)
            if entry:
                found.append(entry)
        found.sort(key=lambda s: s["name"])
        return found

    def _discovered_skill(self, node: Dict[str, Any], prefix: str,
                          source: RepoRef) -> Optional[Dict[str, Any]]:
        """The discover() entry for a tree node that is a SKILL.md under ``prefix``, else None."""
        p = node.get("path", "")
        if not _is_skill_md_under(node, prefix):
            return None
        skill_path = p[: -len("SKILL.md")].rstrip("/")  # folder holding SKILL.md
        name = (skill_path.split("/")[-1] if skill_path else source.repo).lower()
        if not _valid_name(name):
            return None
        description = self._remote_description(source.raw_url(p))
        install_spec = f"{source.owner}/{source.repo}" + (f"/{skill_path}" if skill_path else "") + f"@{source.ref}"
        return {
            "name": name,
            "path": skill_path,
            "description": description,
            "spec": install_spec,
        }

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
            return _parse_github_url(spec, ref)
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
        ref = self._resolve_ref(owner, repo, ref)
        name = (path.rstrip("/").split("/")[-1] if path else repo).lower()
        if not _valid_name(name):
            return {"ok": False, "error": f"invalid skill name '{name}'"}

        tree = self._repo_tree(owner, repo, ref)
        prefix = (path.rstrip("/") + "/") if path else ""
        blobs = [n for n in tree if _is_blob_under(n, prefix)]
        if not blobs:
            return {"ok": False, "error": "no files found at that path"}

        dest_root = self.library_dir / name
        skill_dir = self._fresh_skill_dir(dest_root, name)
        raw_base = RepoRef(owner, repo, ref).raw_url("")
        description = self._download_blobs(raw_base, blobs, prefix, skill_dir)
        _write_plugin_manifest(dest_root, name, description, spec)
        return {"ok": True, "name": name, "description": description, "source": spec}

    def _fresh_skill_dir(self, dest_root: Path, name: str) -> Path:
        """Empty ``dest_root`` (replacing an earlier install) and create its skills/<name>/ dir."""
        self._ensure_gitignore()
        if dest_root.exists():
            shutil.rmtree(dest_root)
        skill_dir = dest_root / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        return skill_dir

    def _download_blobs(self, raw_base: str, blobs: List[Dict[str, Any]], prefix: str, skill_dir: Path) -> str:
        """Download each blob under ``prefix`` into ``skill_dir``; return SKILL.md's description."""
        description = ""
        for node in blobs:
            rel = _safe_skill_rel_path(node["path"][len(prefix):])
            if rel is None:
                continue
            raw = self._get(raw_base + node["path"])
            target = skill_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            if rel == "SKILL.md":
                description = _description_of(raw.decode("utf-8", errors="replace"))
        return description


def _safe_skill_rel_path(rel: str) -> Optional[str]:
    """A remote tree path (relative to the skill) made safe to write locally, or None to skip.

    The remote tree decides these paths. Git itself cannot store a ".."
    component, but assert that locally instead of borrowing the invariant
    (AUDIT #16) — same guard as diff / file-browser paths.
    """
    if not rel or rel.endswith("/"):
        return None
    try:
        safe = validate_file_path(rel)
        if safe in (".", ""):  # normalized away to the skill dir itself
            raise ValueError("path does not name a file")
    except ValueError as exc:
        logger.warning("skills: skipping unsafe path %r: %s", rel, exc)
        return None
    return safe


def _write_plugin_manifest(dest_root: Path, name: str, description: str, spec: str) -> None:
    """Write .claude-plugin/plugin.json so the skill loads as a one-skill plugin."""
    manifest_dir = dest_root / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps({
            "name": name, "version": "1.0.0",
            "description": description, "source": spec,
        }, indent=2),
        encoding="utf-8",
    )
