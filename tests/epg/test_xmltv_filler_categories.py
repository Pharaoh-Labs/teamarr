"""Tests for independent filler XMLTV categories (#199, schema v72).

Templates split categories into two independent lists:
- xmltv_categories: applied to event programmes
- xmltv_filler_categories: applied to filler programmes (pregame/postgame/idle)

Pre-v72 used a categories_apply_to gate ('events' or 'all') with a single
shared list. The v72 migration copies the shared list to xmltv_filler_categories
when the old gate was 'all', and drops the column.
"""

import json
import sqlite3
from pathlib import Path

from teamarr.database.connection import init_db
from teamarr.database.migrations import _run_migrations
from teamarr.database.templates import Template, _row_to_template

# ===========================================================================
# Migration: v71 → v72 splits the shared list correctly
# ===========================================================================


def _make_v71_templates_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a minimal v71 schema with templates that have categories_apply_to."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            schema_version INTEGER DEFAULT 71
        )
    """)
    conn.execute("INSERT INTO settings (id, schema_version) VALUES (1, 71)")

    # Minimal v71 templates table — only the columns the v72 migration touches
    conn.execute("""
        CREATE TABLE templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            xmltv_categories JSON DEFAULT '["Sports"]',
            categories_apply_to TEXT DEFAULT 'events'
                CHECK(categories_apply_to IN ('all', 'events')),
            xmltv_filler_categories JSON DEFAULT '[]'
        )
    """)
    conn.commit()
    return conn


class TestV72Migration:
    """v72 migration splits xmltv_categories + categories_apply_to."""

    def test_apply_to_all_copies_categories_to_filler(self, tmp_path):
        conn = _make_v71_templates_db(tmp_path)
        conn.execute(
            "INSERT INTO templates (name, xmltv_categories, categories_apply_to) VALUES (?, ?, ?)",
            ("EmbyShared", json.dumps(["Sports", "Sports Event"]), "all"),
        )
        conn.commit()

        _run_migrations(conn)

        row = conn.execute(
            "SELECT xmltv_categories, xmltv_filler_categories FROM templates "
            "WHERE name = 'EmbyShared'"
        ).fetchone()
        assert json.loads(row["xmltv_categories"]) == ["Sports", "Sports Event"]
        assert json.loads(row["xmltv_filler_categories"]) == ["Sports", "Sports Event"]

    def test_apply_to_events_leaves_filler_empty(self, tmp_path):
        conn = _make_v71_templates_db(tmp_path)
        conn.execute(
            "INSERT INTO templates (name, xmltv_categories, categories_apply_to) VALUES (?, ?, ?)",
            ("DefaultEvents", json.dumps(["Sports"]), "events"),
        )
        conn.commit()

        _run_migrations(conn)

        row = conn.execute(
            "SELECT xmltv_categories, xmltv_filler_categories FROM templates "
            "WHERE name = 'DefaultEvents'"
        ).fetchone()
        assert json.loads(row["xmltv_categories"]) == ["Sports"]
        assert json.loads(row["xmltv_filler_categories"]) == []

    def test_categories_apply_to_column_dropped(self, tmp_path):
        conn = _make_v71_templates_db(tmp_path)
        conn.execute(
            "INSERT INTO templates (name, categories_apply_to) VALUES (?, ?)",
            ("TestDrop", "all"),
        )
        conn.commit()

        _run_migrations(conn)

        cols = {row["name"] for row in conn.execute("PRAGMA table_info(templates)")}
        assert "categories_apply_to" not in cols
        assert "xmltv_filler_categories" in cols

    def test_schema_version_advanced_past_v72(self, tmp_path):
        conn = _make_v71_templates_db(tmp_path)
        _run_migrations(conn)

        row = conn.execute("SELECT schema_version FROM settings WHERE id = 1").fetchone()
        # v72 ran (other tests cover its data transform). Migrations after v72
        # also run from a v71 starting point — assert we're at the latest
        # version, not pinned to 72.
        assert row["schema_version"] >= 72


# ===========================================================================
# Filler config sources from xmltv_filler_categories, not xmltv_categories
# ===========================================================================


class TestFillerConfigSourcing:
    """The filler-config builders read from xmltv_filler_categories."""

    def test_event_filler_config_independent_lists(self):
        """template_to_event_filler_config builds filler config that uses
        xmltv_filler_categories, not the event-side xmltv_categories."""
        from teamarr.consumers.filler.event_filler import (
            template_to_event_filler_config,
        )

        template = Template(
            id=1,
            name="t",
            template_type="event",
            xmltv_categories=["Sports"],  # event categories
            xmltv_filler_categories=["Series", "Filler"],  # filler-only
        )
        config = template_to_event_filler_config(template)
        assert config.xmltv_categories == ["Series", "Filler"]

    def test_event_filler_empty_filler_categories(self):
        from teamarr.consumers.filler.event_filler import (
            template_to_event_filler_config,
        )

        template = Template(
            id=1,
            name="t",
            template_type="event",
            xmltv_categories=["Sports"],
            xmltv_filler_categories=[],  # explicitly empty
        )
        config = template_to_event_filler_config(template)
        assert config.xmltv_categories == []

    def test_team_filler_config_uses_filler_list(self):
        """template_to_filler_config (team templates) also reads filler list."""
        from teamarr.database.templates import template_to_filler_config

        template = Template(
            id=1,
            name="t",
            template_type="team",
            xmltv_categories=["Sports"],
            xmltv_filler_categories=["Series"],
        )
        config = template_to_filler_config(template)
        assert config.xmltv_categories == ["Series"]


# ===========================================================================
# Default new templates have empty filler categories (graceful default)
# ===========================================================================


class TestDefaults:
    def test_template_dataclass_default_filler_categories_empty(self):
        t = Template(id=1, name="t", template_type="event")
        assert t.xmltv_filler_categories == []
        # Event categories keep the historical "Sports" default for backwards compat
        assert t.xmltv_categories == ["Sports"]


# ===========================================================================
# _row_to_template parses xmltv_filler_categories from the database row
# ===========================================================================


class TestRowParsing:
    def test_row_to_template_parses_filler_categories(self):
        # Mock a row with the new column
        class MockRow:
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data.get(key)

        defaults = {
            "id": 1,
            "name": "t",
            "template_type": "event",
            "sport": None,
            "league": None,
            "title_format": None,
            "subtitle_template": None,
            "description_template": None,
            "program_art_url": None,
            "game_duration_mode": None,
            "game_duration_override": None,
            "xmltv_flags": None,
            "xmltv_video": None,
            "xmltv_categories": json.dumps(["Sports"]),
            "xmltv_filler_categories": json.dumps(["Series"]),
            "pregame_enabled": True,
            "pregame_periods": None,
            "pregame_fallback": None,
            "postgame_enabled": True,
            "postgame_periods": None,
            "postgame_fallback": None,
            "postgame_conditional": None,
            "idle_enabled": True,
            "idle_content": None,
            "idle_conditional": None,
            "idle_offseason": None,
            "conditional_descriptions": None,
            "event_channel_name": None,
            "event_channel_logo_url": None,
            "created_at": None,
            "updated_at": None,
        }
        row = MockRow(defaults)
        template = _row_to_template(row)

        assert template.xmltv_categories == ["Sports"]
        assert template.xmltv_filler_categories == ["Series"]


# ===========================================================================
# Fresh install: schema.sql has xmltv_filler_categories with [] default
# ===========================================================================


class TestFreshInstall:
    def test_fresh_init_db_has_filler_categories_column(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        init_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(templates)")}
        assert "xmltv_filler_categories" in cols
        assert "categories_apply_to" not in cols

        # Fresh install should land on the current schema version (>= 72).
        row = conn.execute("SELECT schema_version FROM settings WHERE id = 1").fetchone()
        assert row["schema_version"] >= 72
