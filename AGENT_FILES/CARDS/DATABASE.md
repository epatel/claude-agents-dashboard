# Database & Migrations

> **Load when**: writing or running a DB migration; inspecting the schema; whitelisting a new column.
> **Skip when**: not touching SQL or migrations.

SQLite with **31 versioned migrations (001–031)** in `src/migrations/versions/`. Auto-migrates on startup (from the FastAPI lifespan). Recent ones: `025` adds `items.use_chrome`, `026` adds `token_usage.api_error_status`, `027` strips the removed `+advisor` model suffix from stored `items`/`agent_config` rows, `028` adds the graphify config columns to `agent_config` (`graphify_enabled`, `graphify_auto_refresh`, `graphify_backend`), `029` adds `agent_config.enabled_skills` (JSON list of per-project enabled library skills), and `030` adds `agent_config.ollama_load_claude_md` (Ollama-only opt-in to load the project `CLAUDE.md`, default off), and `031` bumps the default model from `claude-opus-4-8` to `claude-opus-5` (including the `[1m]` variant).

**CLI**:
```bash
python -m src.manage status
python -m src.manage migrate
python -m src.manage rollback
```

**Adding a migration**:
1. Copy `000_template.py.example`
2. Implement `up()` / `down()`
3. Test with `python -m src.manage migrate`
4. Whitelist any new `items` columns in `repositories/item_repository.py` (`_WRITABLE_ITEM_COLUMNS`)
5. Whitelist any new `epics` columns in `repositories/epic_repository.py` (`_WRITABLE_EPIC_COLUMNS`)
6. Add a unit test under `tests/unit/migrations/`

**Inspect**:
```bash
sqlite3 agents-lab/dashboard.db ".schema"
sqlite3 agents-lab/dashboard.db "SELECT * FROM items;"
```

---

**See also**: [CONVENTIONS](CONVENTIONS.md) (data-layer section), [TESTING](TESTING.md) (`tests/unit/migrations/` is required for new migrations).
