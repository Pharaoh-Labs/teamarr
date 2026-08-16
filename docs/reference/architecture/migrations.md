---
title: Database Migrations
parent: Architecture
grand_parent: Technical Reference
nav_order: 8
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
                    migrations (migrations/versioned.py)
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
| `teamarr/database/connection.py` | `init_db()` startup orchestration |
| `teamarr/database/migrations/pre.py` | Structural pre-migrations (renames, table rebuilds) |
| `teamarr/database/migrations/versioned.py` | `_run_migrations()` + versioned data migrations |

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
    schema_version INTEGER DEFAULT 87
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
   schema_version INTEGER DEFAULT 88  -- was 87
   ```

2. **Add a migration block** after the checkpoint call in `_run_migrations()`:

   ```python
   # v85: Transform my_field from legacy format
   if current_version < 85:
       conn.execute("UPDATE settings SET my_field = ... WHERE my_field = ...")
       conn.execute("UPDATE settings SET schema_version = 85 WHERE id = 1")
       logger.info("[MIGRATE] Schema upgraded to version 85")
       current_version = 85
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

For changes SQLite can't do via ALTER (e.g., tightening a CHECK constraint), use a pre-migration that backs up the table, drops it, and lets `executescript` recreate it from `schema.sql`. See `_migrate_settings_for_v65` in `migrations/pre.py` for the pattern.

## Best Practices

- Use idempotent operations (`_add_column_if_not_exists`, `INSERT OR IGNORE`, `UPDATE ... WHERE col IS NULL`) — see Key Principles above.
- Avoid non-constant defaults: SQLite can't `ALTER TABLE ADD COLUMN` with `DEFAULT CURRENT_TIMESTAMP`; add the column as NULL and populate with a separate `UPDATE`.

## Available Helper Functions

| Function | Purpose |
|----------|---------|
| `_add_column_if_not_exists(conn, table, col, def)` | Add column if missing |
| `_table_exists(conn, table)` | Check if table exists |
| `_get_table_columns(conn, table)` | Get column names as set |
| `_index_exists(conn, name)` | Check if index exists |

## Pre-Migrations

Some schema changes need to happen **before** the checkpoint runs (e.g., renaming columns that the checkpoint references). These live in `teamarr/database/migrations/pre.py` and run via `run_pre_migrations()`:

| Function | Purpose |
|----------|---------|
| `_rename_league_id_column_if_needed` | Renames legacy `league_id` column |
| `_migrate_exception_keywords_columns` | Restructures exception keyword storage |
| `_migrate_settings_for_v65` | Settings table rebuild (channel lifecycle overhaul) |
| `_migrate_detection_keywords_check` | Rebuilds detection_keywords for a new CHECK constraint |
| `_migrate_stream_match_cache_check` | Rebuilds stream_match_cache for a new CHECK constraint |

(Column additions that used to be pre-migrations are now handled by schema reconciliation.)
Pre-migrations are idempotent and only modify the schema if the target column/table doesn't already exist.

## Schema Reconciliation (v2.4.0+)

`reconcile_schema()` runs on every startup after the structural pre-migrations and before `_run_migrations()` (which itself calls the checkpoint internally — so reconciliation runs **before** the checkpoint). It:

1. Builds an **in-memory reference database** from `schema.sql`.
2. For each real table (except `sqlite_sequence`), compares its columns to the reference.
3. Adds any missing columns via `ALTER TABLE ADD COLUMN`, preserving the default from `schema.sql`.
4. Returns a `ReconcileResult` with counts and any errors.

This means "add a new column" is no longer coupled to a schema version bump — the column lives in `schema.sql` and reconciliation ensures every live database has it. Version-gated migrations are still needed for data transforms (Pattern B above) and for table rebuilds (Pattern C).

**Startup order:**
`init_db` → verify integrity → structural pre-migrations → `reconcile_schema` → `executescript` → data migrations → seed cache.

## Version History

**Current schema version: 84** (32 migration blocks across the 41 versions since the checkpoint — not every version number has a block)

| Version | Type | Description |
|---------|------|-------------|
| 2 | Base | Initial V2 schema |
| 3-42 | Consolidated | Merged into checkpoint_v43 |
| 43 | Checkpoint | Checkpoint baseline |
| 44-84 | Incremental | Individual migrations in `migrations/versioned.py` |
