#!/usr/bin/env python3
"""Diagnostic script to check which update-related columns exist in the database."""

import sqlite3
import sys
from pathlib import Path

# Default database path
DB_PATH = Path(__file__).parent / "data" / "teamarr.db"

def check_database(db_path: Path):
    """Check which columns exist in the settings table."""
    if not db_path.exists():
        print(f"❌ Database not found at: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Get schema version
    try:
        row = conn.execute("SELECT schema_version FROM settings WHERE id = 1").fetchone()
        schema_version = row["schema_version"] if row else "unknown"
        print(f"📊 Schema version: {schema_version}")
    except Exception as e:
        print(f"⚠️  Could not read schema_version: {e}")
        schema_version = "unknown"
    
    # Check which columns exist
    cursor = conn.execute("PRAGMA table_info(settings)")
    existing_columns = {row["name"] for row in cursor.fetchall()}
    
    required_columns = {
        "update_check_enabled",
        "update_check_interval_hours",
        "update_notify_stable",
        "update_notify_dev",
        "update_github_owner",
        "update_github_repo",
        "update_dev_branch",
    }
    
    print("\n📋 Update-related columns status:")
    for col in required_columns:
        status = "✅" if col in existing_columns else "❌"
        print(f"  {status} {col}")
    
    missing = required_columns - existing_columns
    
    if missing:
        print(f"\n❌ MISSING COLUMNS: {missing}")
        print(f"\n💡 This confirms the issue:")
        print(f"   Your database is at version {schema_version} but missing columns: {', '.join(missing)}")
        print(f"   This happened because you ran the OLD v44 migration from commit 3ddef11")
        print(f"   which only added the first 4 columns.")
        print(f"\n🔧 Solutions:")
        print(f"   1. Restart the app - the new migration will add missing columns automatically")
        print(f"   2. OR delete the database and let it recreate (you'll lose data)")
        return False
    else:
        print("\n✅ All required columns exist!")
        return True
    
    conn.close()

if __name__ == "__main__":
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH
    print(f"🔍 Checking database: {db_path}\n")
    success = check_database(db_path)
    sys.exit(0 if success else 1)
