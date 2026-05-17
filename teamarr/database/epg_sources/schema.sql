-- EPG Sources Database Schema
-- Separate database (epg_sources.db) for external EPG source management.
-- Isolated from main teamarr.db for easy upstream merge management.

-- External XMLTV EPG sources (URLs)
CREATE TABLE IF NOT EXISTS epg_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    enabled BOOLEAN DEFAULT 1,
    last_fetched_at TIMESTAMP,
    last_fetch_status TEXT CHECK(last_fetch_status IN ('success', 'error')),
    last_fetch_error TEXT,
    channel_count INTEGER DEFAULT 0,
    programme_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Channels parsed from XMLTV sources
CREATE TABLE IF NOT EXISTS epg_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    channel_xmltv_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    icon_url TEXT,
    FOREIGN KEY (source_id) REFERENCES epg_sources(id) ON DELETE CASCADE,
    UNIQUE(source_id, channel_xmltv_id)
);

-- Manual mapping: Dispatcharr stream <-> EPG channel
CREATE TABLE IF NOT EXISTS epg_stream_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    epg_channel_id INTEGER NOT NULL,
    dispatcharr_stream_id INTEGER NOT NULL UNIQUE,
    dispatcharr_stream_name TEXT,
    m3u_account_id INTEGER,
    enabled BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (epg_channel_id) REFERENCES epg_channels(id) ON DELETE CASCADE
);

-- Cached programmes from last XMLTV fetch (replaced on each refresh)
CREATE TABLE IF NOT EXISTS epg_programmes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    start_time TIMESTAMP NOT NULL,
    stop_time TIMESTAMP NOT NULL,
    description TEXT,
    subtitle TEXT,
    categories TEXT,
    FOREIGN KEY (channel_id) REFERENCES epg_channels(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_epg_programmes_channel ON epg_programmes(channel_id);
CREATE INDEX IF NOT EXISTS idx_epg_programmes_time ON epg_programmes(start_time, stop_time);
CREATE INDEX IF NOT EXISTS idx_epg_channels_source ON epg_channels(source_id);
CREATE INDEX IF NOT EXISTS idx_epg_stream_mappings_channel ON epg_stream_mappings(epg_channel_id);

-- Tracks channels created in the main DB from EPG source matches
CREATE TABLE IF NOT EXISTS epg_managed_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mapping_id INTEGER NOT NULL,
    event_id TEXT NOT NULL,
    event_provider TEXT NOT NULL,
    main_db_channel_id INTEGER,
    programme_title TEXT,
    programme_start TIMESTAMP,
    programme_stop TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (mapping_id) REFERENCES epg_stream_mappings(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_epg_managed_mapping ON epg_managed_channels(mapping_id);
CREATE INDEX IF NOT EXISTS idx_epg_managed_event ON epg_managed_channels(event_id, event_provider);
