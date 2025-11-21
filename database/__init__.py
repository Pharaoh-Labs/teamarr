"""Database module for Teamarr"""
import sqlite3
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = '/app/data/teamarr.db'

def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize database with schema"""
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')

    with open(schema_path, 'r') as f:
        schema_sql = f.read()

    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()
        print(f"✅ Database initialized successfully at {DB_PATH}")
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        raise
    finally:
        conn.close()

    # Run migrations after schema is initialized
    migrate_team_ids_to_numeric()
    migrate_output_path_to_data_dir()
    migrate_between_games_to_idle()

def migrate_team_ids_to_numeric():
    """
    Migrate existing teams from slug-based IDs to numeric IDs.

    This migration runs automatically on startup to fix the is_home logic.
    ESPN's schedule API returns numeric IDs, so we need numeric IDs in the database
    for proper home/away matching.
    """
    from api.espn_client import ESPNClient

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Find teams with non-numeric IDs (slugs)
        teams = cursor.execute("""
            SELECT id, espn_team_id, league, sport, team_name
            FROM teams
            WHERE espn_team_id NOT GLOB '[0-9]*'
        """).fetchall()

        if not teams:
            # No migration needed
            return

        print(f"\n🔄 Migrating {len(teams)} team(s) to numeric IDs...")

        espn = ESPNClient()
        updated_count = 0

        for team in teams:
            team_dict = dict(team)
            slug_id = team_dict['espn_team_id']

            # Fetch team info using the slug to get numeric ID
            team_data = espn.get_team_info(
                team_dict['sport'],
                team_dict['league'],
                slug_id
            )

            if team_data and 'team' in team_data:
                numeric_id = str(team_data['team'].get('id', ''))

                if numeric_id and numeric_id != slug_id:
                    cursor.execute("""
                        UPDATE teams
                        SET espn_team_id = ?
                        WHERE id = ?
                    """, (numeric_id, team_dict['id']))

                    print(f"  ✅ {team_dict['team_name']}: {slug_id} → {numeric_id}")
                    updated_count += 1

        conn.commit()

        if updated_count > 0:
            print(f"✅ Migrated {updated_count} team(s) to numeric IDs\n")

    except Exception as e:
        print(f"⚠️  Migration warning: {e}")
        # Don't fail startup if migration has issues
    finally:
        conn.close()

def migrate_output_path_to_data_dir():
    """
    Migrate EPG output path from ./output/teamarr.xml to /app/data/teamarr.xml.

    This migration runs automatically on startup to fix the output path for Docker
    volume mounting. The old path was ./output/teamarr.xml which didn't persist
    across container restarts. The new path is /app/data/teamarr.xml which is
    mounted as a Docker volume.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Check if settings has the old path
        result = cursor.execute("""
            SELECT epg_output_path FROM settings WHERE id = 1
        """).fetchone()

        if result:
            current_path = result[0]
            old_paths = ['./output/teamarr.xml', '/app/output/teamarr.xml']

            if current_path in old_paths:
                cursor.execute("""
                    UPDATE settings
                    SET epg_output_path = '/app/data/teamarr.xml'
                    WHERE id = 1
                """)
                conn.commit()
                print(f"🔄 Migrated EPG output path: {current_path} → /app/data/teamarr.xml")

    except Exception as e:
        print(f"⚠️  Output path migration warning: {e}")
        # Don't fail startup if migration has issues
    finally:
        conn.close()

def migrate_between_games_to_idle():
    """
    Rename between_games fields to idle fields for clarity.

    This migration renames:
    - between_games_enabled -> idle_enabled
    - between_games_title -> idle_title
    - between_games_description -> idle_description

    This makes the naming more intuitive since these fields are used for
    "idle" days when there are no games scheduled.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Check if the old column exists
        cursor.execute("PRAGMA table_info(teams)")
        columns = {row[1] for row in cursor.fetchall()}

        # Only migrate if old columns exist and new ones don't
        if 'between_games_enabled' in columns and 'idle_enabled' not in columns:
            print(f"\n🔄 Migrating between_games fields to idle fields...")

            # SQLite doesn't support renaming columns directly in older versions
            # We need to use ALTER TABLE ADD COLUMN and copy data

            # Add new columns
            cursor.execute("ALTER TABLE teams ADD COLUMN idle_enabled BOOLEAN DEFAULT 1")
            cursor.execute("ALTER TABLE teams ADD COLUMN idle_title TEXT DEFAULT '{team_name} Programming'")
            cursor.execute("ALTER TABLE teams ADD COLUMN idle_description TEXT DEFAULT 'Next game: {next_date} at {next_time} vs {next_opponent}'")

            # Copy data from old columns to new columns
            cursor.execute("""
                UPDATE teams
                SET idle_enabled = between_games_enabled,
                    idle_title = between_games_title,
                    idle_description = between_games_description
            """)

            conn.commit()
            print(f"✅ Migrated between_games fields to idle fields\n")

    except Exception as e:
        print(f"⚠️  Idle fields migration warning: {e}")
        # Don't fail startup if migration has issues
    finally:
        conn.close()

def reset_database():
    """Drop all tables and reinitialize"""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"🗑️  Removed existing database at {DB_PATH}")
    init_database()
