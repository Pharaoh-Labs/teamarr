"""Sport naming setting (#691): US vs International vocabulary for the two
sports whose names differ by region. Applied in ONE place —
core.sports.get_sport_display_names_from_db — so templates, the {sport}
channel-group wildcard, and the UI label map all inherit it."""

import sqlite3

from teamarr.core.sports import (
    SPORT_NAMING_MODES,
    apply_sport_naming,
    get_sport_display_names_from_db,
    get_sport_naming_mode,
)
from teamarr.database.connection import get_connection
from teamarr.database.settings import get_all_settings, update_display_settings
from teamarr.database.team_cache import list_sports


def test_apply_sport_naming_relabels_only_the_two_regional_sports():
    seeded = {"soccer": "Soccer", "football": "Football", "hockey": "Hockey", "mma": "MMA"}
    assert apply_sport_naming(seeded, "us") == seeded
    assert apply_sport_naming(seeded, None) == seeded
    intl = apply_sport_naming(seeded, "international")
    assert intl == {
        "soccer": "Football",
        "football": "American Football",
        "hockey": "Hockey",
        "mma": "MMA",
    }
    assert seeded["soccer"] == "Soccer"  # input untouched


def test_default_is_us_and_survives_the_startup_reseed(db_path):
    with get_connection(db_path) as conn:
        assert get_all_settings(conn).display.sport_naming == "us"
        names = get_sport_display_names_from_db(conn)
    assert names["soccer"] == "Soccer" and names["football"] == "Football"


def test_international_mode_flows_through_every_reader(db_path):
    with get_connection(db_path) as conn:
        update_display_settings(conn, sport_naming="international")
        conn.commit()
        assert get_sport_naming_mode(conn) == "international"
        names = get_sport_display_names_from_db(conn)
        api_map = list_sports(conn)  # /cache/sports → every frontend label
    assert names["soccer"] == "Football"
    assert names["football"] == "American Football"
    assert names["hockey"] == "Hockey"
    assert api_map["soccer"] == "Football" and api_map["football"] == "American Football"
    # list_sports keeps its display-name ordering under the new labels
    assert list(api_map.values()) == sorted(api_map.values())


def test_bare_connection_without_settings_reads_as_us():
    conn = sqlite3.connect(":memory:")
    assert get_sport_naming_mode(conn) == "us"
    assert "us" in SPORT_NAMING_MODES and "international" in SPORT_NAMING_MODES


def test_schema_rejects_unknown_mode(db_path):
    import pytest

    with get_connection(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE settings SET sport_naming = 'klingon'")
