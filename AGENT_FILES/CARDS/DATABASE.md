# Database & Migrations

> **Load when**: writing or running a DB migration; inspecting the schema; whitelisting a new column.
> **Skip when**: not touching SQL or migrations.

SQLite with **21 versioned migrations (001–021)** in `src/migrations/versions/`. Auto-migrates on startup.

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
