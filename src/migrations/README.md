# Database Migrations

This directory contains the database migration system for the Agents Dashboard. The migration system provides a safe and versioned way to manage database schema changes.

## Overview

The migration system consists of:

- **Migration Runner** (`runner.py`): Manages applying and rolling back migrations
- **Migration Base Class** (`migration.py`): Abstract base class for all migrations
- **Migration Files** (`versions/*.py`): Individual migration implementations
- **Schema Tracking**: Uses `schema_migrations` table to track applied migrations

## Migration Files

Migration files are stored in the `versions/` directory and follow the naming convention:

```
XXX_description.py
```

Where:
- `XXX` is a sequential version number (001, 002, 003, etc.)
- `description` is a brief description of what the migration does

## Creating New Migrations

1. **Copy the template**: Use `000_template.py.example` as a starting point
2. **Name your file**: Follow the `XXX_description.py` pattern
3. **Update the class**: Modify version number and description
4. **Implement methods**:
   - `up()`: Apply the migration changes
   - `down()`: Rollback the migration changes

### Example Migration

```python
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from migration import Migration
import aiosqlite

class AddUserTableMigration(Migration):
    def __init__(self):
        super().__init__(
            version="003",
            description="Add user table for authentication"
        )

    async def up(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

    async def down(self, db: aiosqlite.Connection) -> None:
        await db.execute("DROP TABLE IF EXISTS users")
```

## Running Migrations

Use the management CLI from the project root:

```bash
# Show current status
python -m src.manage status

# Apply all pending migrations
python -m src.manage migrate

# Apply migrations up to a specific version
python -m src.manage migrate --to 002

# Rollback to a specific version
python -m src.manage rollback 001

# Initialize fresh database
python -m src.manage init
```

## Migration Guidelines

### DO:
- Always implement both `up()` and `down()` methods
- Test migrations thoroughly before deploying
- Use sequential version numbers
- Include descriptive migration names
- Document complex migrations in comments
- Backup data before running migrations in production

### DON'T:
- Skip version numbers
- Modify existing migration files after they've been applied
- Create migrations that can't be rolled back
- Use hardcoded paths or values
- Forget to handle edge cases in rollbacks

## SQLite Limitations

SQLite has some limitations that affect migrations:

### No DROP COLUMN Support
SQLite doesn't support `ALTER TABLE DROP COLUMN`. To remove columns:

1. Create new table without the column
2. Copy data from old table to new table
3. Drop old table and rename new table

### Limited ALTER TABLE Support
SQLite only supports:
- `ADD COLUMN`
- `RENAME TABLE`
- `RENAME COLUMN` (SQLite 3.25.0+)

For other changes, you need to recreate the table.

## Best Practices

### Schema Changes
- Always use `IF NOT EXISTS` for new tables/indexes in `up()`
- Always use `IF EXISTS` for drops in `down()`
- Add columns with appropriate defaults
- Consider data migration when changing existing columns

### Data Migrations
- Separate schema changes from data changes when possible
- Use transactions to ensure atomicity
- Validate data before and after migration
- Handle missing or invalid data gracefully

### Testing
- Test both `up()` and `down()` methods
- Test on a copy of production data
- Verify application still works after migration
- Test rollback scenarios

## Troubleshooting

### Migration Fails
1. Check the error message in the logs
2. Verify the migration syntax
3. Ensure the database is not locked by another process
4. Check file permissions

### Rollback Fails
1. Verify the `down()` method is properly implemented
2. Check for dependent data that needs to be handled
3. Consider manual cleanup if necessary

### Missing Migrations
If a migration file is missing but marked as applied in `schema_migrations`:
1. The migration will be skipped (with warning)
2. Recreate the migration file if needed
3. Or manually remove the entry from `schema_migrations`

## Existing Migrations

- **001_initial_schema**: Creates the complete schema (items, work_log, review_comments, clarifications, attachments, agent_config, token_usage)

## Schema Migrations Table

The system automatically creates a `schema_migrations` table to track applied migrations:

```sql
CREATE TABLE schema_migrations (
    version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

This table stores:
- **version**: Migration version number
- **description**: Brief description of the migration
- **applied_at**: Timestamp when the migration was applied