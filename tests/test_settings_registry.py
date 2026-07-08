"""Parity tests for the declarative settings registry (registry.py).

Guards the invariants the registry-driven read/update layer depends on:
- every registry column exists in schema.sql's settings table
- every group covers its dataclass's fields exactly
- the API Pydantic models stay field-compatible with the dataclasses
- a fresh schema row reads back as the dataclass defaults
"""

import dataclasses
import re
import sqlite3
from pathlib import Path

import pytest

from teamarr.database.settings.registry import GROUPS
from teamarr.database.settings.types import AllSettings

SCHEMA_PATH = Path(__file__).parent.parent / "teamarr" / "database" / "schema.sql"


@pytest.fixture(scope="module")
def schema_sql() -> str:
    return SCHEMA_PATH.read_text()


@pytest.fixture(scope="module")
def settings_columns(schema_sql) -> set[str]:
    match = re.search(r"CREATE TABLE IF NOT EXISTS settings \((.*?)\n\);", schema_sql, re.S)
    assert match, "settings table not found in schema.sql"
    return set(
        re.findall(
            r"^\s*([a-z_0-9]+)\s+(?:INTEGER|TEXT|REAL|BOOLEAN|JSON|TIMESTAMP)",
            match.group(1),
            re.M,
        )
    )


def test_registry_columns_exist_in_schema(settings_columns):
    missing = [
        f"{group.name}.{fs.name} -> {fs.column}"
        for group in GROUPS.values()
        for fs in group.fields
        if fs.column not in settings_columns
    ]
    assert not missing, f"Registry columns missing from schema.sql: {missing}"


def test_registry_covers_dataclass_fields_exactly():
    for group in GROUPS.values():
        dc_names = {f.name for f in dataclasses.fields(group.cls)}
        spec_names = set(group.field_names)
        assert spec_names == dc_names, (
            f"Group '{group.name}' field specs {spec_names} != dataclass fields {dc_names}"
        )


def test_registry_groups_match_all_settings():
    group_fields = {
        f.name
        for f in dataclasses.fields(AllSettings)
        if dataclasses.is_dataclass(f.type)
    }
    assert set(GROUPS) == group_fields


def test_no_duplicate_columns_across_groups():
    seen: dict[str, str] = {}
    for group in GROUPS.values():
        for fs in group.fields:
            assert fs.column not in seen, (
                f"Column '{fs.column}' claimed by both '{seen[fs.column]}' and '{group.name}'"
            )
            seen[fs.column] = group.name


def test_pydantic_models_field_parity():
    """API models must not reference fields the dataclasses don't have.

    (Models may expose fewer fields than the dataclass — the API contract can
    lag a new backend-only field — but never unknown ones, which would break
    the asdict()-based model building in the routes.)
    """
    from teamarr.api.routes.settings import models as m

    pairs = [
        ("dispatcharr", m.DispatcharrSettingsModel, m.DispatcharrSettingsUpdate),
        ("lifecycle", m.LifecycleSettingsModel),
        ("reconciliation", m.ReconciliationSettingsModel),
        ("scheduler", m.SchedulerSettingsModel, m.SchedulerSettingsUpdate),
        ("epg", m.EPGSettingsModel),
        ("display", m.DisplaySettingsModel),
        ("team_filter", m.TeamFilterSettingsModel),
        ("channel_numbering", m.ChannelNumberingSettingsModel, m.ChannelNumberingSettingsUpdate),
        ("stream_ordering", m.StreamOrderingSettingsModel),
        ("update_check", m.UpdateCheckSettingsModel, m.UpdateCheckSettingsUpdate),
        ("feed_separation", m.FeedSeparationSettingsModel, m.FeedSeparationSettingsUpdate),
        ("emby", m.EmbySettingsModel, m.EmbySettingsUpdate),
        ("jellyfin", m.JellyfinSettingsModel, m.JellyfinSettingsUpdate),
        ("channelsdvr", m.ChannelsDVRSettingsModel, m.ChannelsDVRSettingsUpdate),
    ]
    # Update models may carry control flags that are not persisted fields.
    control_flags = {"clear_include_teams", "clear_exclude_teams"}

    for group_name, *model_classes in pairs:
        dc_names = set(GROUPS[group_name].field_names)
        for model_cls in model_classes:
            unknown = set(model_cls.model_fields) - dc_names - control_flags
            assert not unknown, (
                f"{model_cls.__name__} has fields unknown to group '{group_name}': {unknown}"
            )


def test_fresh_schema_row_reads_back_dataclass_defaults(schema_sql):
    from teamarr.database.settings import get_all_settings

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(schema_sql)
    conn.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")

    from_db = get_all_settings(conn)
    reference = AllSettings()
    for f in dataclasses.fields(AllSettings):
        if f.name == "schema_version":  # DB carries the real version
            continue
        assert getattr(from_db, f.name) == getattr(reference, f.name), (
            f"Fresh-row read of '{f.name}' differs from dataclass default"
        )


def test_missing_columns_fall_back_to_defaults():
    """Partial schemas (un-reconciled DBs / old test fixtures) must not crash."""
    from teamarr.database.settings import get_epg_settings, get_feed_separation_settings

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, epg_timezone TEXT)")
    conn.execute("INSERT INTO settings (id, epg_timezone) VALUES (1, 'UTC')")

    epg = get_epg_settings(conn)
    assert epg.epg_timezone == "UTC"
    assert epg.epg_output_days_ahead == 14  # missing column -> default

    feed = get_feed_separation_settings(conn)
    assert feed.home_terms == ["HOME"]
