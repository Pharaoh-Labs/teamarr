---
title: Database Migrations
parent: Architecture
grand_parent: Technical Reference
nav_order: 6
docs_version: "2.3.1"
---

# Database Migrations

Teamarr uses a **checkpoint + incremental migration + schema reconciliation** system to handle database schema changes safely across versions. Reconciliation (added in v2.4.0) compares every table's live columns against `schema.sql` on every startup and adds any missing columns automatically — so most pure column additions no longer need an explicit migration block.

## Architecture

```
Fresh Install          Existing Database (v2-v42)      Existing Database (v43+)
     │                          │                              │
     ▼                          ▼                              ▼
 schema.sql              checkpoint_v43.py              Skip checkpoint
(creates v43)         (idempotent → v43)                      │
     │                          │                              │
     └──────────────────────────┴──────────────────────────────┘
                                │
                                ▼
                    v44, v45, ... incremental
                    migrations (connection.py)
```

### Key Principles

1. **Idempotent**: Migrations can be run multiple times safely
2. **Defensive**: Check column/table existence before operations
3. **Checkpoint-based**: Old migrations consolidated, new ones are incremental

## Key Files

| File | Purpose |
|------|---------|
| `teamarr/database/schema.sql` | Authoritative schema for fresh installs AND the reference for reconciliation |
| `teamarr/database/checkpoint_v43.py` | Consolidates v2-v43 into single operation |
| `teamarr/database/reconciliation.py` | Compares real DB columns against `schema.sql`, adds any that are missing |
| `teamarr/database/connection.py` | `_run_migrations()` orchestrates everything |

## How It Works

### Fresh Install
1. `schema.sql` creates database directly at current version (v43+)
2. No migrations run

### Existing Database (v2-v42)
1. `apply_checkpoint_v43()` runs
2. Checkpoint is **idempotent** - ensures v43 state regardless of starting point
3. Handles partial migrations gracefully
4. Any v44+ migrations run afterward

### Existing Database (v43+)
1. Checkpoint is skipped (version check)
2. Only v44+ migrations run if needed

## Adding a Schema Change

There are two patterns depending on what you're doing.

### Pattern A — Pure column addition (preferred when possible)

Since v2.4.0, reconciliation handles missing columns automatically. Just edit `schema.sql`:

```sql
CREATE TABLE settings (
    ...
    my_new_setting TEXT DEFAULT 'value',  -- Added
    schema_version INTEGER DEFAULT 73
);
```

On the next startup:
1. Fresh installs get the column from `schema.sql` directly.
2. Existing databases get the column added by `reconcile_schema()` via `ALTER TABLE ADD COLUMN`.

No migration block needed. No version bump needed (for the column itself). This works for any column that SQLite can add via `ALTER TABLE` — i.e. anything without a non-constant default.

### Pattern B — Data migration (when you need to transform existing rows)

When the change requires transforming data (not just adding a column), use a version-gated block in `_run_migrations()`:

1. **Bump `schema_version` DEFAULT** in `schema.sql`:

   ```sql
   schema_version INTEGER DEFAULT 73  -- was 72
   ```

2. **Add a migration block** after the checkpoint call in `_run_migrations()`:

   ```python
   # v72: Transform my_field from legacy format
   if current_version < 72:
       conn.execute("UPDATE settings SET my_field = ... WHERE my_field = ...")
       conn.execute("UPDATE settings SET schema_version = 72 WHERE id = 1")
       logger.info("[MIGRATE] Schema upgraded to version 72")
       current_version = 72
   ```

   Column additions that pair with the data change can use `_add_column_if_not_exists` inside the block as a safety net for tests that call `_run_migrations` directly — reconciliation will also pick them up on real startups.

3. **Write a test** that starts from the previous version and verifies the transform:

   ```python
   def test_v72_migration(temp_db):
       # Setup v71 database with legacy values
       # Run _run_migrations
       # Assert transformed values are correct
   ```

### Pattern C — Table rebuild (CHECK constraint changes)

For changes SQLite can't do via ALTER (e.g., tightening a CHECK constraint), use a pre-migration that backs up the table, drops it, and lets `executescript` recreate it from `schema.sql`. See `_migrate_settings_for_v65` in `connection.py` for the pattern.

## Best Practices

### Use Idempotent Operations

```python
# Safe to run multiple times
_add_column_if_not_exists(conn, "table", "col", "TYPE DEFAULT val")

# Safe INSERT
conn.execute("INSERT OR IGNORE INTO sports (code, name) VALUES ('x', 'X')")

# Safe UPDATE
conn.execute("UPDATE t SET col = 'new' WHERE col IS NULL")
```

### Check Before Operating

```python
if _table_exists(conn, "my_table"):
    columns = _get_table_columns(conn, "my_table")
    if "target_col" in columns:
        conn.execute("UPDATE my_table SET target_col = ...")
```

### Avoid Non-Constant Defaults

```python
# BAD: SQLite can't add CURRENT_TIMESTAMP default
_add_column_if_not_exists(conn, "t", "created", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

# GOOD: Add with NULL, populate separately
_add_column_if_not_exists(conn, "t", "created", "TIMESTAMP")
conn.execute("UPDATE t SET created = CURRENT_TIMESTAMP WHERE created IS NULL")
```

## Available Helper Functions

| Function | Purpose |
|----------|---------|
| `_add_column_if_not_exists(conn, table, col, def)` | Add column if missing |
| `_table_exists(conn, table)` | Check if table exists |
| `_get_table_columns(conn, table)` | Get column names as set |
| `_index_exists(conn, name)` | Check if index exists |

## When to Create a New Checkpoint

Consider a new checkpoint when:
- 15-20+ migrations accumulated since last checkpoint
- Major schema restructure planned
- Migration code becoming unwieldy

To create:
1. Copy `checkpoint_v43.py` to `checkpoint_vXX.py`
2. Update all schema definitions to match current `schema.sql`
3. Update `connection.py` to use new checkpoint
4. Old checkpoint can be removed (or kept for users on very old versions)

## Pre-Migrations

Some schema changes need to happen **before** the checkpoint runs (e.g., renaming columns that the checkpoint references). These are handled by dedicated functions called before `apply_checkpoint_v43()`:

| Function | Purpose |
|----------|---------|
| `_rename_league_id_column_if_needed` | Renames legacy `league_id` column |
| `_add_league_alias_column_if_needed` | Adds `league_alias` column |
| `_add_gracenote_category_column_if_needed` | Adds `gracenote_category` column |
| `_add_logo_url_dark_column_if_needed` | Adds `logo_url_dark` column |
| `_add_series_slug_pattern_column_if_needed` | Adds `series_slug_pattern` column |
| `_add_fallback_columns_if_needed` | Adds `fallback_provider` and `fallback_league_id` |
| `_add_tsdb_tier_column_if_needed` | Adds `tsdb_tier` for TSDB free/premium classification |
| `_migrate_exception_keywords_columns` | Restructures exception keyword storage |
| `_migrate_settings_for_v65` | Channel lifecycle overhaul (v62) |

Pre-migrations are idempotent and only modify the schema if the target column/table doesn't already exist.

## Schema Reconciliation (v2.4.0+)

`reconcile_schema()` runs on every startup after the checkpoint and before `_run_migrations()`. It:

1. Builds an **in-memory reference database** from `schema.sql`.
2. For each real table (except `sqlite_sequence`), compares its columns to the reference.
3. Adds any missing columns via `ALTER TABLE ADD COLUMN`, preserving the default from `schema.sql`.
4. Returns a `ReconcileResult` with counts and any errors.

This means "add a new column" is no longer coupled to a schema version bump — the column lives in `schema.sql` and reconciliation ensures every live database has it. Version-gated migrations are still needed for data transforms (Pattern B above) and for table rebuilds (Pattern C).

**Startup order:**
`init_db` → verify integrity → structural pre-migrations → `reconcile_schema` → `executescript` → data migrations → seed cache.

## Version History

**Current schema version: 74** (32 incremental migrations since checkpoint)

| Version | Type | Description |
|---------|------|-------------|
| 2 | Base | Initial V2 schema |
| 3-42 | Consolidated | Merged into checkpoint_v43 |
| 43 | Checkpoint | Checkpoint baseline |
| 44-71 | Incremental | Individual migrations in `connection.py` |

## Troubleshooting

### "no such column" during migration
Add column existence check before UPDATE operations.

### Migration runs but nothing changes
Verify `schema_version` is being updated in the migration.

### Fresh install has wrong version
Update `schema_version` default in `schema.sql`.

### User reports partial state
The checkpoint handles this - it fills in missing pieces idempotently.
