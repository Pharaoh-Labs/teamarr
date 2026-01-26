# Database Migration Issue - Root Cause Analysis

## Problem
Your database shows error: `sqlite3.OperationalError: no such column: update_dev_branch`

## Root Cause
The version 44 migration evolved across multiple commits in this PR, but kept the same version number:

### Timeline of Version 44 Migration Changes:

**Commit 3ddef11** (Initial) - Added only **4 columns**:
```python
if current_version < 44:
    _add_column_if_not_exists(conn, "settings", "update_check_enabled", "INTEGER DEFAULT 1")
    _add_column_if_not_exists(conn, "settings", "update_check_interval_hours", "INTEGER DEFAULT 24")
    _add_column_if_not_exists(conn, "settings", "update_notify_stable", "INTEGER DEFAULT 1")
    _add_column_if_not_exists(conn, "settings", "update_notify_dev", "INTEGER DEFAULT 0")
    conn.execute("UPDATE settings SET schema_version = 44 WHERE id = 1")
```

**Commit 1c2c38b** - Added **5 more columns** (9 total):
```python
# Previous 4 columns +
_add_column_if_not_exists(conn, "settings", "update_github_owner", "TEXT DEFAULT 'Pharaoh-Labs'")
_add_column_if_not_exists(conn, "settings", "update_github_repo", "TEXT DEFAULT 'teamarr'")
_add_column_if_not_exists(conn, "settings", "update_ghcr_owner", "TEXT DEFAULT 'pharaoh-labs'")
_add_column_if_not_exists(conn, "settings", "update_ghcr_image", "TEXT DEFAULT 'teamarr'")
_add_column_if_not_exists(conn, "settings", "update_dev_tag", "TEXT DEFAULT 'dev'")
```

**Commit 0e10dec** - Removed GHCR, added dev_branch (**7 total**):
```python
# Previous 4 columns +
_add_column_if_not_exists(conn, "settings", "update_github_owner", "TEXT DEFAULT 'Pharaoh-Labs'")
_add_column_if_not_exists(conn, "settings", "update_github_repo", "TEXT DEFAULT 'teamarr'")
_add_column_if_not_exists(conn, "settings", "update_dev_branch", "TEXT DEFAULT 'dev'")
# REMOVED: update_ghcr_owner, update_ghcr_image, update_dev_tag
```

## What Happened to Your Database

1. You pulled commit **3ddef11** and started the app
2. Migration ran and added 4 columns
3. Database marked itself as version 44
4. You pulled commit **0e10dec** (or later)
5. Migration saw `current_version = 44`, so it **skipped the migration block**
6. Your database never got the 3 new columns: `update_github_owner`, `update_github_repo`, `update_dev_branch`
7. API code tries to use `update_dev_branch` → **ERROR**

## Verification

Run the diagnostic script:
```bash
python check_db_columns.py
```

Expected output for your database:
```
📊 Schema version: 44

📋 Update-related columns status:
  ✅ update_check_enabled
  ✅ update_check_interval_hours
  ✅ update_notify_stable
  ✅ update_notify_dev
  ❌ update_github_owner
  ❌ update_github_repo
  ❌ update_dev_branch

❌ MISSING COLUMNS: {'update_github_owner', 'update_github_repo', 'update_dev_branch'}
```

## Solutions

### Option 1: Automatic Fix (Recommended)
The new migration code (commit 1d91138) includes a compatibility fix that runs **after** the version 44 check:

```python
# Fix for databases that ran the OLD version 44 migration
if current_version >= 44:
    _add_column_if_not_exists(conn, "settings", "update_github_owner", ...)
    _add_column_if_not_exists(conn, "settings", "update_github_repo", ...)
    _add_column_if_not_exists(conn, "settings", "update_dev_branch", ...)
```

**Action:** Just restart the app. The missing columns will be added automatically.

### Option 2: Regenerate Database (If you prefer fresh start)
```bash
# Backup if needed
cp data/teamarr.db data/teamarr.db.backup

# Delete database
rm data/teamarr.db*

# Restart app - will create fresh database with all columns
docker compose restart
```

This gives you a clean v44 migration with all 7 columns from the start.

## Recommendation

Since this is a development/testing phase and you mentioned you can regenerate:
- **Option 2 (regenerate)** is cleaner and avoids any lingering compatibility concerns
- However, **Option 1 (automatic fix)** proves the migration compatibility works for production users who can't easily regenerate

Your choice! Both will work.
