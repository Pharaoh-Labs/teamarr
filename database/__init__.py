"""Database module for Teamarr - Template-Based Architecture"""
import sqlite3
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

# Database path - respects Docker volume mount at /app/data
# In Docker: /app/data/teamarr.db (persisted via volume)
# In local dev: ./data/teamarr.db (or project root if data/ doesn't exist)
def get_db_path():
    """Get database path, preferring /app/data/ for Docker compatibility"""
    # Check if we're in Docker (has /app/data directory)
    if os.path.exists('/app/data'):
        return '/app/data/teamarr.db'

    # Check if we have a local data directory
    base_dir = os.path.dirname(os.path.dirname(__file__))
    data_dir = os.path.join(base_dir, 'data')
    if os.path.exists(data_dir):
        return os.path.join(data_dir, 'teamarr.db')

    # Fallback to project root (backward compatible)
    return os.path.join(base_dir, 'teamarr.db')

DB_PATH = get_db_path()

def get_connection():
    """Get database connection with row factory for dict-like access"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def run_migrations(conn):
    """Run database migrations for schema updates"""
    cursor = conn.cursor()

    # Get existing columns in settings table
    cursor.execute("PRAGMA table_info(settings)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    # Dispatcharr integration columns (added in v1.0.6)
    dispatcharr_columns = [
        ("dispatcharr_enabled", "BOOLEAN DEFAULT 0"),
        ("dispatcharr_url", "TEXT DEFAULT 'http://localhost:9191'"),
        ("dispatcharr_username", "TEXT"),
        ("dispatcharr_password", "TEXT"),
        ("dispatcharr_epg_id", "INTEGER"),
        ("dispatcharr_last_sync", "TEXT"),
    ]

    migrations_run = 0
    for col_name, col_def in dispatcharr_columns:
        if col_name not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE settings ADD COLUMN {col_name} {col_def}")
                migrations_run += 1
                print(f"  ✅ Added column: settings.{col_name}")
            except Exception as e:
                print(f"  ⚠️ Could not add column {col_name}: {e}")

    if migrations_run > 0:
        conn.commit()
        print(f"✅ Ran {migrations_run} migration(s)")

    # Conditional postgame/idle description columns (added in v1.0.7)
    cursor.execute("PRAGMA table_info(templates)")
    template_columns = {row[1] for row in cursor.fetchall()}

    conditional_columns = [
        ("postgame_conditional_enabled", "BOOLEAN DEFAULT 0"),
        ("postgame_description_final", "TEXT DEFAULT 'The {team_name} {result_text.last} the {opponent.last} {final_score.last} {overtime_text.last}'"),
        ("postgame_description_not_final", "TEXT DEFAULT 'The game between the {team_name} and {opponent.last} on {game_day.last} {game_date.last} has not yet ended.'"),
        ("idle_conditional_enabled", "BOOLEAN DEFAULT 0"),
        ("idle_description_final", "TEXT DEFAULT 'The {team_name} {result_text.last} the {opponent.last} {final_score.last}. Next: {opponent.next} on {game_date.next}'"),
        ("idle_description_not_final", "TEXT DEFAULT 'The {team_name} last played {opponent.last} on {game_date.last}. Next: {opponent.next} on {game_date.next}'"),
    ]

    for col_name, col_def in conditional_columns:
        if col_name not in template_columns:
            try:
                cursor.execute(f"ALTER TABLE templates ADD COLUMN {col_name} {col_def}")
                print(f"  ✅ Added column: templates.{col_name}")
            except Exception as e:
                print(f"  ⚠️ Could not add column {col_name}: {e}")

    conn.commit()

    # Fix NCAA league logos (use NCAA.com sport banners)
    ncaa_logo_fixes = [
        ("ncaaf", "https://www.ncaa.com/modules/custom/casablanca_core/img/sportbanners/football.png"),
        ("ncaam", "https://www.ncaa.com/modules/custom/casablanca_core/img/sportbanners/basketball.png"),
        ("ncaaw", "https://www.ncaa.com/modules/custom/casablanca_core/img/sportbanners/basketball.png"),
    ]

    for league_code, logo_url in ncaa_logo_fixes:
        try:
            cursor.execute(
                "UPDATE league_config SET logo_url = ? WHERE league_code = ? AND logo_url != ?",
                (logo_url, league_code, logo_url)
            )
            if cursor.rowcount > 0:
                print(f"  ✅ Fixed logo for {league_code}")
        except Exception:
            pass

    conn.commit()

    # EPG history filler count columns (added in v1.1.0)
    cursor.execute("PRAGMA table_info(epg_history)")
    epg_history_columns = {row[1] for row in cursor.fetchall()}

    epg_history_new_columns = [
        ("num_pregame", "INTEGER DEFAULT 0"),
        ("num_postgame", "INTEGER DEFAULT 0"),
        ("num_idle", "INTEGER DEFAULT 0"),
    ]

    for col_name, col_def in epg_history_new_columns:
        if col_name not in epg_history_columns:
            try:
                cursor.execute(f"ALTER TABLE epg_history ADD COLUMN {col_name} {col_def}")
                migrations_run += 1
                print(f"  ✅ Added column: epg_history.{col_name}")
            except Exception as e:
                print(f"  ⚠️ Could not add column {col_name}: {e}")

    conn.commit()

    # Event EPG Groups table (added for Event Channel EPG feature)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='event_epg_groups'")
    if not cursor.fetchone():
        try:
            cursor.execute("""
                CREATE TABLE event_epg_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    dispatcharr_group_id INTEGER NOT NULL UNIQUE,
                    dispatcharr_account_id INTEGER NOT NULL,
                    group_name TEXT NOT NULL,
                    assigned_league TEXT NOT NULL,
                    assigned_sport TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    refresh_interval_minutes INTEGER DEFAULT 60,
                    last_refresh TIMESTAMP,
                    stream_count INTEGER DEFAULT 0,
                    matched_count INTEGER DEFAULT 0
                )
            """)
            cursor.execute("CREATE INDEX idx_event_epg_groups_league ON event_epg_groups(assigned_league)")
            cursor.execute("CREATE INDEX idx_event_epg_groups_enabled ON event_epg_groups(enabled)")
            cursor.execute("""
                CREATE TRIGGER update_event_epg_groups_timestamp
                AFTER UPDATE ON event_epg_groups
                FOR EACH ROW
                BEGIN
                    UPDATE event_epg_groups SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
                END
            """)
            migrations_run += 1
            print("  ✅ Created table: event_epg_groups")
        except Exception as e:
            print(f"  ⚠️ Could not create event_epg_groups table: {e}")

    # Team Aliases table (added for Event Channel EPG feature)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='team_aliases'")
    if not cursor.fetchone():
        try:
            cursor.execute("""
                CREATE TABLE team_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    alias TEXT NOT NULL,
                    league TEXT NOT NULL,
                    espn_team_id TEXT NOT NULL,
                    espn_team_name TEXT NOT NULL,
                    UNIQUE(alias, league)
                )
            """)
            cursor.execute("CREATE INDEX idx_team_aliases_league ON team_aliases(league)")
            cursor.execute("CREATE INDEX idx_team_aliases_alias ON team_aliases(alias)")
            migrations_run += 1
            print("  ✅ Created table: team_aliases")
        except Exception as e:
            print(f"  ⚠️ Could not create team_aliases table: {e}")

    conn.commit()

    # Template type column (added for Event EPG templates)
    cursor.execute("PRAGMA table_info(templates)")
    template_columns = {row[1] for row in cursor.fetchall()}

    if 'template_type' not in template_columns:
        try:
            cursor.execute("""
                ALTER TABLE templates ADD COLUMN template_type TEXT DEFAULT 'team'
                CHECK(template_type IN ('team', 'event'))
            """)
            migrations_run += 1
            print("  ✅ Added column: templates.template_type")
        except Exception as e:
            print(f"  ⚠️ Could not add template_type column: {e}")

    conn.commit()

    # Event template assignment column (added for Event EPG groups)
    cursor.execute("PRAGMA table_info(event_epg_groups)")
    event_group_columns = {row[1] for row in cursor.fetchall()}

    if 'event_template_id' not in event_group_columns:
        try:
            cursor.execute("""
                ALTER TABLE event_epg_groups ADD COLUMN event_template_id INTEGER
                REFERENCES templates(id) ON DELETE SET NULL
            """)
            migrations_run += 1
            print("  ✅ Added column: event_epg_groups.event_template_id")
        except Exception as e:
            print(f"  ⚠️ Could not add event_template_id column: {e}")

    conn.commit()

    # ==========================================================================
    # Channel Lifecycle Management (Phase 8)
    # ==========================================================================

    # Refresh event_group_columns after commit
    cursor.execute("PRAGMA table_info(event_epg_groups)")
    event_group_columns = {row[1] for row in cursor.fetchall()}

    # Channel lifecycle columns for event_epg_groups
    lifecycle_columns = [
        ("channel_start", "INTEGER"),  # Starting channel number for this group
        ("channel_create_timing", "TEXT DEFAULT 'day_of'"),  # When to create: day_of, day_before, 2_days_before, week_before
        ("channel_delete_timing", "TEXT DEFAULT 'stream_removed'"),  # When to delete: stream_removed, end_of_day, end_of_next_day, manual
    ]

    for col_name, col_def in lifecycle_columns:
        if col_name not in event_group_columns:
            try:
                cursor.execute(f"ALTER TABLE event_epg_groups ADD COLUMN {col_name} {col_def}")
                migrations_run += 1
                print(f"  ✅ Added column: event_epg_groups.{col_name}")
            except Exception as e:
                print(f"  ⚠️ Could not add column {col_name}: {e}")

    conn.commit()

    # Managed Channels table (tracks channels Teamarr creates in Dispatcharr)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='managed_channels'")
    if not cursor.fetchone():
        try:
            cursor.execute("""
                CREATE TABLE managed_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    event_epg_group_id INTEGER NOT NULL REFERENCES event_epg_groups(id) ON DELETE CASCADE,
                    dispatcharr_channel_id INTEGER NOT NULL UNIQUE,
                    dispatcharr_stream_id INTEGER NOT NULL,
                    channel_number INTEGER NOT NULL,
                    channel_name TEXT NOT NULL,
                    tvg_id TEXT,
                    espn_event_id TEXT,
                    event_date TEXT,
                    home_team TEXT,
                    away_team TEXT,
                    scheduled_delete_at TIMESTAMP,
                    deleted_at TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX idx_managed_channels_group ON managed_channels(event_epg_group_id)")
            cursor.execute("CREATE INDEX idx_managed_channels_event ON managed_channels(espn_event_id)")
            cursor.execute("CREATE INDEX idx_managed_channels_delete ON managed_channels(scheduled_delete_at)")
            cursor.execute("""
                CREATE TRIGGER update_managed_channels_timestamp
                AFTER UPDATE ON managed_channels
                FOR EACH ROW
                BEGIN
                    UPDATE managed_channels SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
                END
            """)
            migrations_run += 1
            print("  ✅ Created table: managed_channels")
        except Exception as e:
            print(f"  ⚠️ Could not create managed_channels table: {e}")

    conn.commit()

    return migrations_run


def init_database():
    """Initialize database with schema and run migrations"""
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')

    with open(schema_path, 'r') as f:
        schema_sql = f.read()

    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()

        # Run migrations for existing databases
        run_migrations(conn)

        # Sync timezone from environment variable if set
        env_tz = os.environ.get('TZ')
        if env_tz:
            conn.execute(
                "UPDATE settings SET default_timezone = ? WHERE id = 1",
                (env_tz,)
            )
            conn.commit()
            print(f"✅ Database initialized successfully at {DB_PATH} (timezone: {env_tz})")
        else:
            print(f"✅ Database initialized successfully at {DB_PATH}")

    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        raise
    finally:
        conn.close()

def reset_database():
    """Drop all tables and reinitialize (for development)"""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"🗑️  Removed existing database at {DB_PATH}")
    init_database()

# Helper functions for template operations

def _parse_template_json_fields(template: Dict[str, Any]) -> Dict[str, Any]:
    """Parse JSON fields in a template dict"""
    import json

    # Fields that should be parsed from JSON
    json_fields = ['categories', 'flags', 'description_options']

    for field in json_fields:
        if field in template and template[field]:
            try:
                # Parse JSON string to Python object
                template[field] = json.loads(template[field])
            except (json.JSONDecodeError, TypeError):
                # If parsing fails, leave as-is or set to default
                if field == 'categories':
                    template[field] = []
                elif field == 'flags':
                    template[field] = {}
                elif field == 'description_options':
                    template[field] = []

    return template

def _serialize_template_json_fields(template: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize JSON fields in a template dict to strings for database storage"""
    import json

    # Fields that should be serialized to JSON
    json_fields = ['categories', 'flags', 'description_options']

    for field in json_fields:
        if field in template and template[field] is not None:
            if not isinstance(template[field], str):
                # Serialize Python object to JSON string
                template[field] = json.dumps(template[field])

    return template

def get_template(template_id: int) -> Optional[Dict[str, Any]]:
    """Get template by ID"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        result = cursor.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
        if result:
            template = dict(result)
            return _parse_template_json_fields(template)
        return None
    finally:
        conn.close()

def get_all_templates() -> List[Dict[str, Any]]:
    """Get all templates with team count"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        results = cursor.execute("""
            SELECT
                t.*,
                COUNT(tm.id) as team_count
            FROM templates t
            LEFT JOIN teams tm ON t.id = tm.template_id
            GROUP BY t.id
            ORDER BY t.name
        """).fetchall()
        return [_parse_template_json_fields(dict(row)) for row in results]
    finally:
        conn.close()

def create_template(data: Dict[str, Any]) -> int:
    """Create a new template and return its ID"""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # Serialize JSON fields to strings for database storage
        data = _serialize_template_json_fields(data.copy())

        # Extract fields (all are optional except name)
        fields = [
            'name', 'sport', 'league',
            'title_format', 'subtitle_template', 'program_art_url',
            'game_duration_mode', 'game_duration_override',
            'flags', 'categories', 'categories_apply_to',
            'no_game_enabled', 'no_game_title', 'no_game_description', 'no_game_duration',
            'pregame_enabled', 'pregame_periods', 'pregame_title', 'pregame_subtitle', 'pregame_description', 'pregame_art_url',
            'postgame_enabled', 'postgame_periods', 'postgame_title', 'postgame_subtitle', 'postgame_description', 'postgame_art_url',
            'idle_enabled', 'idle_title', 'idle_subtitle', 'idle_description', 'idle_art_url',
            'description_options'
        ]

        # Build INSERT statement dynamically
        present_fields = [f for f in fields if f in data]
        placeholders = ', '.join(['?' for _ in present_fields])
        field_names = ', '.join(present_fields)

        cursor.execute(f"""
            INSERT INTO templates ({field_names})
            VALUES ({placeholders})
        """, [data[f] for f in present_fields])

        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def update_template(template_id: int, data: Dict[str, Any]) -> bool:
    """Update an existing template"""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # Serialize JSON fields to strings for database storage
        data = _serialize_template_json_fields(data.copy())

        # Build UPDATE statement from provided fields
        fields = [k for k in data.keys() if k != 'id']
        set_clause = ', '.join([f"{f} = ?" for f in fields])
        values = [data[f] for f in fields] + [template_id]

        cursor.execute(f"""
            UPDATE templates
            SET {set_clause}
            WHERE id = ?
        """, values)

        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def delete_template(template_id: int) -> bool:
    """
    Delete a template. Teams assigned to this template will have template_id set to NULL
    due to ON DELETE SET NULL foreign key constraint.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def get_template_team_count(template_id: int) -> int:
    """Get count of teams using this template"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        result = cursor.execute("""
            SELECT COUNT(*) FROM teams WHERE template_id = ?
        """, (template_id,)).fetchone()
        return result[0] if result else 0
    finally:
        conn.close()

# Helper functions for team operations

def get_team(team_id: int) -> Optional[Dict[str, Any]]:
    """Get team by ID with template and league information"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        result = cursor.execute("""
            SELECT
                t.*,
                tp.name as template_name,
                lc.league_name
            FROM teams t
            LEFT JOIN templates tp ON t.template_id = tp.id
            LEFT JOIN league_config lc ON t.league = lc.league_code
            WHERE t.id = ?
        """, (team_id,)).fetchone()
        return dict(result) if result else None
    finally:
        conn.close()

def get_all_teams() -> List[Dict[str, Any]]:
    """Get all teams with template information"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        results = cursor.execute("""
            SELECT
                t.*,
                tp.name as template_name,
                lc.league_name,
                lc.sport
            FROM teams t
            LEFT JOIN templates tp ON t.template_id = tp.id
            LEFT JOIN league_config lc ON t.league = lc.league_code
            ORDER BY t.team_name
        """).fetchall()
        return [dict(row) for row in results]
    finally:
        conn.close()

def get_active_teams_with_templates() -> List[Dict[str, Any]]:
    """
    Get all active teams that have a template assigned.
    Used for EPG generation (filters out unassigned teams).
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        results = cursor.execute("""
            SELECT
                t.*,
                tp.*
            FROM teams t
            INNER JOIN templates tp ON t.template_id = tp.id
            WHERE t.active = 1 AND t.template_id IS NOT NULL
            ORDER BY t.team_name
        """).fetchall()

        # Convert to list of dicts, merging team and template data
        teams_with_templates = []
        for row in results:
            row_dict = dict(row)
            # Separate team and template data
            team_data = {k: v for k, v in row_dict.items() if not k.startswith('template_')}
            template_data = {k: v for k, v in row_dict.items() if k.startswith('template_')}

            teams_with_templates.append({
                'team': team_data,
                'template': template_data
            })

        return teams_with_templates
    finally:
        conn.close()

def create_team(data: Dict[str, Any]) -> int:
    """Create a new team and return its ID"""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        fields = [
            'espn_team_id', 'league', 'sport',
            'team_name', 'team_abbrev', 'team_slug', 'team_logo_url', 'team_color',
            'channel_id', 'channel_logo_url', 'template_id', 'active'
        ]

        present_fields = [f for f in fields if f in data]
        placeholders = ', '.join(['?' for _ in present_fields])
        field_names = ', '.join(present_fields)

        cursor.execute(f"""
            INSERT INTO teams ({field_names})
            VALUES ({placeholders})
        """, [data[f] for f in present_fields])

        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def update_team(team_id: int, data: Dict[str, Any]) -> bool:
    """Update an existing team"""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        fields = [k for k in data.keys() if k != 'id']
        set_clause = ', '.join([f"{f} = ?" for f in fields])
        values = [data[f] for f in fields] + [team_id]

        cursor.execute(f"""
            UPDATE teams
            SET {set_clause}
            WHERE id = ?
        """, values)

        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def delete_team(team_id: int) -> bool:
    """Delete a team"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM teams WHERE id = ?", (team_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def bulk_assign_template(team_ids: List[int], template_id: Optional[int]) -> int:
    """Assign a template to multiple teams. Returns count of teams updated."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        placeholders = ', '.join(['?' for _ in team_ids])
        cursor.execute(f"""
            UPDATE teams
            SET template_id = ?
            WHERE id IN ({placeholders})
        """, [template_id] + team_ids)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()

def bulk_delete_teams(team_ids: List[int]) -> int:
    """Delete multiple teams. Returns count of teams deleted."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        placeholders = ', '.join(['?' for _ in team_ids])
        cursor.execute(f"DELETE FROM teams WHERE id IN ({placeholders})", team_ids)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()

def bulk_set_active(team_ids: List[int], active: bool) -> int:
    """Set active status for multiple teams. Returns count of teams updated."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        placeholders = ', '.join(['?' for _ in team_ids])
        cursor.execute(f"""
            UPDATE teams
            SET active = ?
            WHERE id IN ({placeholders})
        """, [1 if active else 0] + team_ids)
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


# =============================================================================
# Team Alias Functions (for Event Channel EPG)
# =============================================================================

def get_alias(alias_id: int) -> Optional[Dict[str, Any]]:
    """Get a team alias by ID."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        result = cursor.execute(
            "SELECT * FROM team_aliases WHERE id = ?",
            (alias_id,)
        ).fetchone()
        return dict(result) if result else None
    finally:
        conn.close()


def get_aliases_for_league(league: str) -> List[Dict[str, Any]]:
    """Get all team aliases for a specific league."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        results = cursor.execute(
            """
            SELECT * FROM team_aliases
            WHERE league = ?
            ORDER BY alias
            """,
            (league.lower(),)
        ).fetchall()
        return [dict(row) for row in results]
    finally:
        conn.close()


def get_all_aliases() -> List[Dict[str, Any]]:
    """Get all team aliases."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        results = cursor.execute(
            """
            SELECT * FROM team_aliases
            ORDER BY league, alias
            """
        ).fetchall()
        return [dict(row) for row in results]
    finally:
        conn.close()


def create_alias(alias: str, league: str, espn_team_id: str, espn_team_name: str) -> int:
    """
    Create a new team alias.

    Args:
        alias: The alias string (will be normalized to lowercase)
        league: League code (e.g., 'nfl', 'epl')
        espn_team_id: ESPN team ID
        espn_team_name: ESPN team display name

    Returns:
        ID of created alias

    Raises:
        sqlite3.IntegrityError if alias already exists for this league
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO team_aliases (alias, league, espn_team_id, espn_team_name)
            VALUES (?, ?, ?, ?)
            """,
            (alias.lower().strip(), league.lower(), espn_team_id, espn_team_name)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_alias(alias_id: int, data: Dict[str, Any]) -> bool:
    """
    Update an existing alias.

    Args:
        alias_id: Alias ID to update
        data: Dict with fields to update (alias, league, espn_team_id, espn_team_name)

    Returns:
        True if updated, False if not found
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # Normalize alias if provided
        if 'alias' in data:
            data['alias'] = data['alias'].lower().strip()
        if 'league' in data:
            data['league'] = data['league'].lower()

        fields = [k for k in data.keys() if k != 'id']
        if not fields:
            return False

        set_clause = ', '.join([f"{f} = ?" for f in fields])
        values = [data[f] for f in fields] + [alias_id]

        cursor.execute(f"""
            UPDATE team_aliases
            SET {set_clause}
            WHERE id = ?
        """, values)

        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_alias(alias_id: int) -> bool:
    """Delete a team alias."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM team_aliases WHERE id = ?", (alias_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def find_alias(alias: str, league: str) -> Optional[Dict[str, Any]]:
    """
    Find an alias by alias string and league.

    Args:
        alias: Alias string to look up
        league: League code

    Returns:
        Alias dict or None if not found
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        result = cursor.execute(
            """
            SELECT * FROM team_aliases
            WHERE alias = ? AND league = ?
            """,
            (alias.lower().strip(), league.lower())
        ).fetchone()
        return dict(result) if result else None
    finally:
        conn.close()


def bulk_create_aliases(aliases: List[Dict[str, str]]) -> int:
    """
    Create multiple aliases at once.

    Args:
        aliases: List of dicts with alias, league, espn_team_id, espn_team_name

    Returns:
        Count of aliases created (skips duplicates)
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        created = 0

        for a in aliases:
            try:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO team_aliases
                    (alias, league, espn_team_id, espn_team_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        a['alias'].lower().strip(),
                        a['league'].lower(),
                        a['espn_team_id'],
                        a['espn_team_name']
                    )
                )
                if cursor.rowcount > 0:
                    created += 1
            except Exception as e:
                print(f"Error creating alias {a.get('alias')}: {e}")
                continue

        conn.commit()
        return created
    finally:
        conn.close()


# =============================================================================
# Event EPG Group Functions (for Event Channel EPG)
# =============================================================================

def get_event_epg_group(group_id: int) -> Optional[Dict[str, Any]]:
    """Get an event EPG group by ID."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        result = cursor.execute(
            "SELECT * FROM event_epg_groups WHERE id = ?",
            (group_id,)
        ).fetchone()
        return dict(result) if result else None
    finally:
        conn.close()


def get_event_epg_group_by_dispatcharr_id(dispatcharr_group_id: int) -> Optional[Dict[str, Any]]:
    """Get an event EPG group by Dispatcharr group ID."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        result = cursor.execute(
            "SELECT * FROM event_epg_groups WHERE dispatcharr_group_id = ?",
            (dispatcharr_group_id,)
        ).fetchone()
        return dict(result) if result else None
    finally:
        conn.close()


def get_all_event_epg_groups(enabled_only: bool = False) -> List[Dict[str, Any]]:
    """Get all event EPG groups."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM event_epg_groups"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY group_name"

        results = cursor.execute(query).fetchall()
        return [dict(row) for row in results]
    finally:
        conn.close()


def create_event_epg_group(
    dispatcharr_group_id: int,
    dispatcharr_account_id: int,
    group_name: str,
    assigned_league: str,
    assigned_sport: str,
    enabled: bool = True,
    refresh_interval_minutes: int = 60,
    event_template_id: int = None
) -> int:
    """
    Create a new event EPG group.

    Args:
        event_template_id: Optional template ID (must be an 'event' type template)

    Returns:
        ID of created group

    Raises:
        sqlite3.IntegrityError if dispatcharr_group_id already exists
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO event_epg_groups
            (dispatcharr_group_id, dispatcharr_account_id, group_name,
             assigned_league, assigned_sport, enabled, refresh_interval_minutes,
             event_template_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dispatcharr_group_id, dispatcharr_account_id, group_name,
                assigned_league.lower(), assigned_sport.lower(),
                1 if enabled else 0, refresh_interval_minutes,
                event_template_id
            )
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_event_epg_group(group_id: int, data: Dict[str, Any]) -> bool:
    """Update an event EPG group."""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # Normalize league/sport if provided
        if 'assigned_league' in data:
            data['assigned_league'] = data['assigned_league'].lower()
        if 'assigned_sport' in data:
            data['assigned_sport'] = data['assigned_sport'].lower()

        fields = [k for k in data.keys() if k != 'id']
        if not fields:
            return False

        set_clause = ', '.join([f"{f} = ?" for f in fields])
        values = [data[f] for f in fields] + [group_id]

        cursor.execute(f"""
            UPDATE event_epg_groups
            SET {set_clause}
            WHERE id = ?
        """, values)

        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_event_epg_group(group_id: int) -> bool:
    """Delete an event EPG group."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM event_epg_groups WHERE id = ?", (group_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_event_epg_group_stats(
    group_id: int,
    stream_count: int,
    matched_count: int
) -> bool:
    """Update stats after EPG generation."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE event_epg_groups
            SET stream_count = ?, matched_count = ?, last_refresh = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (stream_count, matched_count, group_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# =============================================================================
# Managed Channels Functions (for Channel Lifecycle Management)
# =============================================================================

def get_managed_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    """Get a managed channel by ID."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        result = cursor.execute(
            "SELECT * FROM managed_channels WHERE id = ?",
            (channel_id,)
        ).fetchone()
        return dict(result) if result else None
    finally:
        conn.close()


def get_managed_channel_by_dispatcharr_id(dispatcharr_channel_id: int) -> Optional[Dict[str, Any]]:
    """Get a managed channel by Dispatcharr channel ID."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        result = cursor.execute(
            "SELECT * FROM managed_channels WHERE dispatcharr_channel_id = ?",
            (dispatcharr_channel_id,)
        ).fetchone()
        return dict(result) if result else None
    finally:
        conn.close()


def get_managed_channel_by_event(espn_event_id: str, group_id: int = None) -> Optional[Dict[str, Any]]:
    """Get a managed channel by ESPN event ID, optionally filtered by group."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if group_id:
            result = cursor.execute(
                "SELECT * FROM managed_channels WHERE espn_event_id = ? AND event_epg_group_id = ? AND deleted_at IS NULL",
                (espn_event_id, group_id)
            ).fetchone()
        else:
            result = cursor.execute(
                "SELECT * FROM managed_channels WHERE espn_event_id = ? AND deleted_at IS NULL",
                (espn_event_id,)
            ).fetchone()
        return dict(result) if result else None
    finally:
        conn.close()


def get_managed_channels_for_group(group_id: int, include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Get all managed channels for an event EPG group."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM managed_channels WHERE event_epg_group_id = ?"
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        query += " ORDER BY channel_number"

        results = cursor.execute(query, (group_id,)).fetchall()
        return [dict(row) for row in results]
    finally:
        conn.close()


def get_all_managed_channels(include_deleted: bool = False) -> List[Dict[str, Any]]:
    """Get all managed channels."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM managed_channels"
        if not include_deleted:
            query += " WHERE deleted_at IS NULL"
        query += " ORDER BY event_epg_group_id, channel_number"

        results = cursor.execute(query).fetchall()
        return [dict(row) for row in results]
    finally:
        conn.close()


def get_channels_pending_deletion() -> List[Dict[str, Any]]:
    """Get channels that are scheduled for deletion and past their delete time."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        results = cursor.execute(
            """
            SELECT * FROM managed_channels
            WHERE scheduled_delete_at IS NOT NULL
            AND scheduled_delete_at <= CURRENT_TIMESTAMP
            AND deleted_at IS NULL
            ORDER BY scheduled_delete_at
            """
        ).fetchall()
        return [dict(row) for row in results]
    finally:
        conn.close()


def create_managed_channel(
    event_epg_group_id: int,
    dispatcharr_channel_id: int,
    dispatcharr_stream_id: int,
    channel_number: int,
    channel_name: str,
    tvg_id: str = None,
    espn_event_id: str = None,
    event_date: str = None,
    home_team: str = None,
    away_team: str = None,
    scheduled_delete_at: str = None
) -> int:
    """
    Create a new managed channel record.

    Returns:
        ID of created record

    Raises:
        sqlite3.IntegrityError if dispatcharr_channel_id already exists
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO managed_channels
            (event_epg_group_id, dispatcharr_channel_id, dispatcharr_stream_id,
             channel_number, channel_name, tvg_id, espn_event_id, event_date,
             home_team, away_team, scheduled_delete_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_epg_group_id, dispatcharr_channel_id, dispatcharr_stream_id,
                channel_number, channel_name, tvg_id, espn_event_id, event_date,
                home_team, away_team, scheduled_delete_at
            )
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_managed_channel(channel_id: int, data: Dict[str, Any]) -> bool:
    """Update a managed channel record."""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        fields = [k for k in data.keys() if k != 'id']
        if not fields:
            return False

        set_clause = ', '.join([f"{f} = ?" for f in fields])
        values = [data[f] for f in fields] + [channel_id]

        cursor.execute(f"""
            UPDATE managed_channels
            SET {set_clause}
            WHERE id = ?
        """, values)

        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def mark_managed_channel_deleted(channel_id: int) -> bool:
    """Mark a managed channel as deleted (soft delete)."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE managed_channels SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (channel_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_managed_channel(channel_id: int) -> bool:
    """Hard delete a managed channel record."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM managed_channels WHERE id = ?", (channel_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_next_channel_number(group_id: int) -> Optional[int]:
    """
    Get the next available channel number for a group.

    Uses the group's channel_start and finds the next unused number.
    Returns None if the group has no channel_start configured.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # Get the group's channel_start
        group = cursor.execute(
            "SELECT channel_start FROM event_epg_groups WHERE id = ?",
            (group_id,)
        ).fetchone()

        if not group or not group['channel_start']:
            return None

        channel_start = group['channel_start']

        # Get all active channel numbers for this group
        used_numbers = cursor.execute(
            """
            SELECT channel_number FROM managed_channels
            WHERE event_epg_group_id = ? AND deleted_at IS NULL
            ORDER BY channel_number
            """,
            (group_id,)
        ).fetchall()

        used_set = {row['channel_number'] for row in used_numbers}

        # Find the first available number starting from channel_start
        next_num = channel_start
        while next_num in used_set:
            next_num += 1

        return next_num
    finally:
        conn.close()


def cleanup_old_deleted_channels(days_old: int = 30) -> int:
    """
    Hard delete managed channel records that were soft-deleted more than N days ago.

    Returns count of records deleted.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM managed_channels
            WHERE deleted_at IS NOT NULL
            AND deleted_at < datetime('now', ? || ' days')
            """,
            (f"-{days_old}",)
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
