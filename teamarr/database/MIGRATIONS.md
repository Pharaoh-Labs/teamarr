# Database Migrations

How database schema changes work in Teamarr v2.

## Architecture

```
Startup (init_db):
  1. Verify integrity (corrupt files raise, V1 databases raise — no longer supported)
  2. Structural pre-migrations (column renames, table rebuilds)
  3. Schema reconciliation ← compares real DB against schema.sql
  4. conn.executescript(schema.sql) ← creates missing tables, seeds data
  5. Data migrations (_run_migrations) ← transforms existing data
  6. Seed TSDB cache
```

### Key Files

| File | Purpose |
|------|---------|
| `schema.sql` | Single source of truth for all table/column definitions |
| `reconciliation.py` | Compares real DB against in-memory reference, adds missing columns |
| `connection.py` | `init_db()` startup flow + `_run_migrations()` data migrations |
| `checkpoint_v43.py` | Consolidates v2–v43 migrations into single idempotent operation |
| `migration.py` | Backup-restore validation helpers |

## The Rule

**Schema (column shape) lives in `schema.sql`. Reconciliation enforces it.
`_run_migrations()` is for data transformations only.**

Concretely:

| Change | Where it goes |
|--------|---------------|
| New column | `schema.sql` only. Reconciliation adds it on next startup. |
| Bump default value of an existing column | `schema.sql` (for new installs) + a `_migrate_v{N}_*` helper to transform existing rows |
| Rename column | Pre-migration in `init_db` (renames before `executescript` runs) |
| New table | `schema.sql` (with `CREATE TABLE IF NOT EXISTS`). Reconciliation does not create tables; `executescript` does. |
| Change a `CHECK` constraint or `FOREIGN KEY` action | Pre-migration that backs up + drops the table; `executescript` recreates it; data-migration restore block |
| Drop a column | Migration helper running `ALTER TABLE ... DROP COLUMN`. Wrap in `try/except OperationalError` for older SQLite. |
| Transform existing data (anything that needs to know the *prior* shape) | `_migrate_v{N}_*` helper |

A single change may touch both — e.g. v72 added `xmltv_filler_categories` (schema.sql), copied data from `xmltv_categories` (migration helper), and dropped `categories_apply_to` (migration helper).

## Adding a New Column

Just add it to `schema.sql`. Bump the `schema_version DEFAULT`. Done.

```sql
CREATE TABLE IF NOT EXISTS settings (
    ...
    my_new_setting TEXT DEFAULT 'default_value',  -- ADD THIS
    schema_version INTEGER DEFAULT 73             -- BUMP THIS
);
```

Reconciliation runs every startup. It creates an in-memory reference database from `schema.sql`, compares each real table against it via `PRAGMA table_info`, and adds any missing columns via `ALTER TABLE ADD COLUMN`.

No migration block needed. No pre-migration function needed.

## Adding a Data Migration

When you need to **transform existing data** (not just add a column):

1. If the migration adds a column, also add the column to `schema.sql` and bump `schema_version DEFAULT`.
2. Write a helper function `_migrate_v{N}_{description}(conn)` that performs the transform.
3. Add a guarded call to it in `_run_migrations`:

```python
def _migrate_v73_my_change(conn: sqlite3.Connection) -> None:
    """v73: short description of what this transforms."""
    # Transform existing rows. The column already exists thanks to schema.sql
    # + reconciliation.
    conn.execute("UPDATE settings SET new_col = old_col * 2 WHERE new_col IS NULL")
```

Then in `_run_migrations`:

```python
if current_version < 73:
    _apply_migration(conn, 73, "short description", _migrate_v73_my_change)
    current_version = 73
```

`_apply_migration` runs the helper, bumps `schema_version`, and emits the standard log line.

If you only need to bump the version (because reconciliation already handled the column adds and there's no data transform):

```python
if current_version < 73:
    _advance_version(conn, 73, "reconciliation: my new column")
    current_version = 73
```

### Defensive column adds

In production, reconciliation runs before `_run_migrations`, so every column declared in `schema.sql` already exists by the time a migration helper runs. Tests sometimes invoke `_run_migrations` directly without reconciliation, though, and helpers that *read* a column will fail if it's missing.

When that's a concern, add a defensive `_add_column_if_not_exists` call inside the migration helper, with a comment explaining why:

```python
def _migrate_v58_sports_subscription(conn: sqlite3.Connection) -> None:
    # Defensive: reconciliation adds this column in production, but standalone
    # _run_migrations test paths bypass reconciliation.
    _add_column_if_not_exists(conn, "event_epg_groups", "soccer_followed_teams", "TEXT")
    ...
```

## Table Rebuild (CHECK / FOREIGN KEY changes)

SQLite bakes CHECK constraints and FK actions into the table at CREATE TABLE time. To change them:

1. Add a pre-migration in `init_db()` that backs up the table and drops it.
2. `executescript` recreates it with the new constraints from `schema.sql`.
3. Add a restore helper (`_migrate_v{N}_*_restore_if_needed`) keyed on the backup table's existence.

See `_migrate_settings_for_v65` (pre-migration) and `_migrate_v65_lifecycle_timing_restore_if_needed` (restore) as the reference pattern. The restore helper checks for the backup table rather than checking `schema_version`, because `executescript` reseeds `schema_version` to its default after the table rebuild.

## Best Practices

**DO:** Use idempotent operations.

```python
conn.execute("INSERT OR IGNORE INTO ...")
conn.execute("UPDATE ... WHERE col IS NULL")  # Only update if not already set
conn.execute("CREATE INDEX IF NOT EXISTS ...")
```

**DON'T:** Add columns with non-constant defaults.

```python
# BAD: SQLite can't ALTER TABLE ADD COLUMN with CURRENT_TIMESTAMP default
# GOOD: Use NULL default, populate separately
_add_column_if_not_exists(conn, "t", "created_at", "TIMESTAMP")
conn.execute("UPDATE t SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
```

**DON'T:** Add a column directly in `_run_migrations` (outside a defensive case).

```python
# BAD — duplicates schema.sql, drifts from reconciliation
if current_version < 73:
    _add_column_if_not_exists(conn, "settings", "my_col", "TEXT")
    conn.execute("UPDATE settings SET schema_version = 73 ...")

# GOOD — column lives in schema.sql; migration only transforms data
if current_version < 73:
    _apply_migration(conn, 73, "set my_col defaults", _migrate_v73_my_col_defaults)
    current_version = 73
```

## Reconciliation Details

`reconciliation.py` — `reconcile_schema(conn, schema_sql)`:

1. Creates in-memory reference DB from `schema.sql`
2. Gets tables from both real and reference DBs
3. For tables in both: compares columns via `PRAGMA table_info`
4. Adds missing columns with type and DEFAULT from reference
5. Skips tables not in real DB (`executescript` creates them)
6. Skips extra columns in real DB (doesn't drop anything)
7. Skips internal tables (names starting with `_`)

Self-healing: any missing column — from bugs, partial migrations, version corruption — gets automatically repaired on next startup.

## Troubleshooting

### "no such column" errors
Reconciliation should prevent this. If it happens, check that `reconcile_schema` runs before `executescript` in `init_db()`. If it happens in tests, the test probably bypasses reconciliation; either call `reconcile_schema` first, or add a defensive `_add_column_if_not_exists` to the migration helper.

### Migration runs but changes aren't visible
Check that `schema_version` is being updated. The `_apply_migration` helper does this for you; inline `conn.execute` paths must do it manually.

### User reports partial migration
Reconciliation self-heals column gaps. For data migration issues, the versioned blocks are idempotent (guarded by `if current_version < N`) and can be re-run safely after fixing the bug — bump the user's `schema_version` back below the broken migration and restart.
