# Skills Library

> **Load when**: working on the Agent-Skills library (install/browse/discover/enable), the Settings ▸ Skills tab, or how enabled skills reach agents.
> **Skip when**: feature work that doesn't touch skills.

A dashboard-managed library of [Agent Skills](https://docs.claude.com/en/docs/claude-code/skills). Agents run with `setting_sources=["project"]`, so a developer's `~/.claude/skills` are **not** ingested — the dashboard installs skills itself and delivers the enabled ones via the SDK `plugins=` option (which loads regardless of git/worktree/`setting_sources`).

## Pieces

- **`src/services/skills_service.py` (`SkillsService`)** — owns the library. Methods:
  - `browse(source="anthropic")` — list installable skills from Anthropic's public `anthropics/skills` repo (cached in-process).
  - `discover(spec)` — find every folder containing a `SKILL.md` in a GitHub repo / sub-path / URL; returns one install `spec` per skill, pinned to the resolved ref.
  - `install(spec)` — download a skill's files into the library; synthesizes a `.claude-plugin/plugin.json`.
  - `list_installed(enabled)` / `installed_names()` — enumerate the library with per-project enabled flags + description + source.
  - `plugin_path(name)` / `remove(name)`.
  - `_parse_spec` accepts `owner/repo[/path][@ref]` or a `https://github.com/...` tree/blob URL.
- **Library layout** (gitignored — `SkillsService._ensure_gitignore` appends `skill-library/` to the dashboard's `.gitignore`):
  ```
  skill-library/<name>/
      .claude-plugin/plugin.json     # {name, version, description, source}
      skills/<name>/SKILL.md         # the skill (+ any sibling files)
  ```
  Each installed skill is wrapped as a **one-skill plugin** so it can be toggled individually.
- **Per-project enable** — `agent_config.enabled_skills` (migration `029`), a JSON list of skill names. The DB lives under `<target>/agents-lab`, so the enabled set is naturally scoped per target project.
- **Delivery to agents** — `SessionService._parse_plugins(plugins, enabled_skills)` resolves each enabled name to `skill-library/<name>` and merges it into the SDK `plugins=` list alongside auto-discovered `plugins/` and user-configured plugins. (Skipped in Ollama mode, like other plugins.)
- **Routes** (`src/web/routes.py`): `GET /api/skills`, `GET /api/skills/browse`, `POST /api/skills/discover`, `POST /api/skills/install`, `POST /api/skills/{name}/enabled`, `DELETE /api/skills/{name}`. `enabled_skills` is written **only** by the `/enabled` endpoint — saving Settings does not touch it.
- **Frontend** — Settings ▸ Skills tab in `src/static/js/config-dialog.js` (`refreshSkills`, `toggleSkill`, `removeSkill`, `showSkillInfo`, install/browse/discover flows); the ⓘ info control opens a skill-info dialog with description + source link.

## Notes

- Skills are **not** an agent MCP tool — they ship as plugins, so there's no `mcp__*` surface to whitelist.
- Separate from the library, everything under the dashboard's `plugins/` directory is auto-discovered and delivered **always-on** to every orchestrated agent (`SessionService`, `src/services/session_service.py:253`). Currently ships `board-workflows` (brainstorm / plan-tasks / debug).
- Installing a skill auto-enables it for the current project (the install route adds the name to `enabled_skills`).
- Tests: `tests/unit/test_skills_service.py` (service), `tests/unit/migrations/test_enabled_skills_029.py` (column), plus route coverage in `tests/unit/test_routes.py`.

---

**See also**: [ARCHITECTURE](ARCHITECTURE.md) (`SkillsService` in the service tour), [DATABASE](DATABASE.md) (migration 029).
