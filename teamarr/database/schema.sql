-- Teamarr v2 Database Schema
-- SQLite Database Structure
--
-- Design principles:
--   - Provider-agnostic (no espn_ prefixes)
--   - JSON for complex nested structures
--   - Templates maintain v1 feature parity for export/import
--   - Timestamps on all tables

-- =============================================================================
-- TEMPLATES TABLE
-- EPG generation templates - controls titles, descriptions, filler content
-- Full v1 feature parity for migration support
-- =============================================================================

CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Identity
    name TEXT NOT NULL UNIQUE,
    template_type TEXT DEFAULT 'team' CHECK(template_type IN ('team', 'event')),
    sport TEXT,                              -- Optional filter (basketball, football, etc.)
    league TEXT,                             -- Optional filter (nba, nfl, etc.)

    -- Programme Formatting
    title_format TEXT DEFAULT '{team_name} {sport}',
    subtitle_template TEXT DEFAULT '{venue_full}',
    program_art_url TEXT,

    -- Game Duration
    game_duration_mode TEXT DEFAULT 'sport' CHECK(game_duration_mode IN ('sport', 'default', 'custom')),
    game_duration_override REAL,

    -- XMLTV Metadata
    xmltv_flags JSON DEFAULT '{"new": true, "live": false, "date": false}',
    xmltv_categories JSON DEFAULT '["Sports"]',
    categories_apply_to TEXT DEFAULT 'events' CHECK(categories_apply_to IN ('all', 'events')),

    -- Filler: Pre-Game
    pregame_enabled BOOLEAN DEFAULT 1,
    pregame_periods JSON DEFAULT '[
        {"start_hours_before": 24, "end_hours_before": 6, "title": "Game Preview", "description": "{team_name} plays {opponent} in {hours_until} hours at {venue}"},
        {"start_hours_before": 6, "end_hours_before": 2, "title": "Pre-Game Coverage", "description": "{team_name} vs {opponent} starts at {game_time}"},
        {"start_hours_before": 2, "end_hours_before": 0, "title": "Game Starting Soon", "description": "{team_name} vs {opponent} starts in {hours_until} hours"}
    ]',
    pregame_fallback JSON DEFAULT '{"title": "Pregame Coverage", "subtitle": null, "description": "{team_name} plays {opponent} today at {game_time}", "art_url": null}',

    -- Filler: Post-Game
    postgame_enabled BOOLEAN DEFAULT 1,
    postgame_periods JSON DEFAULT '[
        {"start_hours_after": 0, "end_hours_after": 3, "title": "Game Recap", "description": "{team_name} {result_text} {final_score}"},
        {"start_hours_after": 3, "end_hours_after": 12, "title": "Extended Highlights", "description": "Highlights: {team_name} {result_text} {final_score} vs {opponent}"},
        {"start_hours_after": 12, "end_hours_after": 24, "title": "Full Game Replay", "description": "Replay: {team_name} vs {opponent}"}
    ]',
    postgame_fallback JSON DEFAULT '{"title": "Postgame Recap", "subtitle": null, "description": "{team_name} {result_text.last} the {opponent.last} {final_score.last}", "art_url": null}',
    postgame_conditional JSON DEFAULT '{"enabled": false, "description_final": null, "description_not_final": null}',

    -- Filler: Idle (between games)
    idle_enabled BOOLEAN DEFAULT 1,
    idle_content JSON DEFAULT '{"title": "{team_name} Programming", "subtitle": null, "description": "Next game: {game_date.next} at {game_time.next} vs {opponent.next}", "art_url": null}',
    idle_conditional JSON DEFAULT '{"enabled": false, "description_final": null, "description_not_final": null}',
    idle_offseason JSON DEFAULT '{"enabled": false, "subtitle": null, "description": "No upcoming {team_name} games scheduled."}',

    -- Conditional Descriptions (advanced)
    conditional_descriptions JSON DEFAULT '[]',
    -- Structure: [{"condition": "is_home", "template": "...", "priority": 50, "condition_value": "..."}]

    -- Event Template Specific (for event-based EPG)
    event_channel_name TEXT,
    event_channel_logo_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_templates_name ON templates(name);
CREATE INDEX IF NOT EXISTS idx_templates_type ON templates(template_type);

-- Trigger to auto-update timestamp
CREATE TRIGGER IF NOT EXISTS update_templates_timestamp
AFTER UPDATE ON templates
BEGIN
    UPDATE templates SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;


-- =============================================================================
-- TEAMS TABLE
-- Team channel configurations - provider-agnostic
-- =============================================================================

CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Provider Identification (agnostic)
    provider TEXT NOT NULL DEFAULT 'espn',   -- espn, thesportsdb, etc.
    provider_team_id TEXT NOT NULL,          -- Provider's team ID
    league TEXT NOT NULL,                    -- League code (nfl, nba, eng.1, etc.)
    sport TEXT NOT NULL,                     -- Sport (football, basketball, soccer, etc.)

    -- Team Display Info
    team_name TEXT NOT NULL,
    team_abbrev TEXT,
    team_logo_url TEXT,
    team_color TEXT,

    -- Channel Configuration
    channel_id TEXT NOT NULL UNIQUE,         -- XMLTV channel ID
    channel_logo_url TEXT,                   -- Override logo (uses team_logo_url if null)

    -- Template Assignment
    template_id INTEGER,

    -- Status
    active BOOLEAN DEFAULT 1,

    UNIQUE(provider, provider_team_id, league),
    FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_teams_channel_id ON teams(channel_id);
CREATE INDEX IF NOT EXISTS idx_teams_league ON teams(league);
CREATE INDEX IF NOT EXISTS idx_teams_active ON teams(active);
CREATE INDEX IF NOT EXISTS idx_teams_provider ON teams(provider);

CREATE TRIGGER IF NOT EXISTS update_teams_timestamp
AFTER UPDATE ON teams
BEGIN
    UPDATE teams SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;


-- =============================================================================
-- SETTINGS TABLE
-- Global application settings (single row)
-- =============================================================================

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- EPG Generation
    epg_days_ahead INTEGER DEFAULT 14,
    epg_timezone TEXT DEFAULT 'America/New_York',
    epg_output_path TEXT DEFAULT './teamarr.xml',

    -- Game Duration Defaults (hours)
    duration_default REAL DEFAULT 3.0,
    duration_basketball REAL DEFAULT 3.0,
    duration_football REAL DEFAULT 3.5,
    duration_hockey REAL DEFAULT 3.0,
    duration_baseball REAL DEFAULT 3.5,
    duration_soccer REAL DEFAULT 2.5,

    -- XMLTV
    xmltv_generator_name TEXT DEFAULT 'Teamarr v2',

    -- API
    api_timeout INTEGER DEFAULT 10,
    api_retry_count INTEGER DEFAULT 3,

    -- Channel ID Format
    channel_id_format TEXT DEFAULT '{team_name_pascal}.{league}',

    -- Schema Version
    schema_version INTEGER DEFAULT 1
);

-- Insert default settings
INSERT OR IGNORE INTO settings (id) VALUES (1);

CREATE TRIGGER IF NOT EXISTS update_settings_timestamp
AFTER UPDATE ON settings
BEGIN
    UPDATE settings SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;


-- =============================================================================
-- EVENT_EPG_GROUPS TABLE
-- Configuration for event-based EPG generation
-- =============================================================================

CREATE TABLE IF NOT EXISTS event_epg_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Identity
    name TEXT NOT NULL UNIQUE,

    -- What to scan
    leagues JSON NOT NULL,                   -- ["nfl", "nba"] - leagues to scan for events

    -- Template
    template_id INTEGER,

    -- Channel Settings
    channel_start_number INTEGER,            -- Starting channel number for this group

    -- Lifecycle Settings
    create_timing TEXT DEFAULT 'same_day' CHECK(create_timing IN ('stream_available', 'same_day', 'day_before', 'manual')),
    delete_timing TEXT DEFAULT 'same_day' CHECK(delete_timing IN ('stream_removed', 'same_day', 'day_after', 'manual')),

    -- Status
    active BOOLEAN DEFAULT 1,

    FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE SET NULL
);

CREATE TRIGGER IF NOT EXISTS update_event_epg_groups_timestamp
AFTER UPDATE ON event_epg_groups
BEGIN
    UPDATE event_epg_groups SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;


-- =============================================================================
-- MANAGED_CHANNELS TABLE
-- Dynamically created channels for event-based EPG
-- =============================================================================

CREATE TABLE IF NOT EXISTS managed_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Parent Group
    event_epg_group_id INTEGER NOT NULL,

    -- Event Reference (provider-agnostic)
    event_id TEXT NOT NULL,
    event_provider TEXT NOT NULL,

    -- Channel Info
    tvg_id TEXT NOT NULL UNIQUE,
    channel_name TEXT NOT NULL,
    channel_number TEXT,
    logo_url TEXT,

    -- Lifecycle
    expires_at TIMESTAMP,
    external_channel_id INTEGER,             -- ID in external system (Dispatcharr, etc.)

    FOREIGN KEY (event_epg_group_id) REFERENCES event_epg_groups(id) ON DELETE CASCADE,
    UNIQUE(event_epg_group_id, event_id, event_provider)
);

CREATE INDEX IF NOT EXISTS idx_managed_channels_group ON managed_channels(event_epg_group_id);
CREATE INDEX IF NOT EXISTS idx_managed_channels_event ON managed_channels(event_id, event_provider);
CREATE INDEX IF NOT EXISTS idx_managed_channels_expires ON managed_channels(expires_at);

CREATE TRIGGER IF NOT EXISTS update_managed_channels_timestamp
AFTER UPDATE ON managed_channels
BEGIN
    UPDATE managed_channels SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
