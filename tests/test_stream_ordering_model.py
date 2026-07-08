"""Data-model tests for stream ordering rules (epic teamarr-5ag).

Covers the mode/points fields added for additive scoring: parse-time legacy
defaulting, new-rule round-trips through update+read, and validation coercion.
The matching/sort behaviour itself lives in test_stream_ordering.py.
"""

import json

import pytest

from teamarr.database.connection import get_db, init_db
from teamarr.database.settings.read import (
    _parse_stream_ordering_rules,
    get_stream_ordering_settings,
)
from teamarr.database.settings.types import StreamOrderingRule
from teamarr.database.settings.update import update_stream_ordering_rules


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Fresh DB with the default settings row (id=1)."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    init_db()
    yield


# --- parse-time defaulting (no DB) ---------------------------------------


def test_legacy_rule_without_mode_parses_as_priority():
    """Rows written before the field existed must become hard priority rules."""
    legacy = json.dumps([{"type": "m3u", "value": "Acme", "priority": 5}])
    rules = _parse_stream_ordering_rules(legacy)
    assert len(rules) == 1
    assert rules[0].mode == "priority"
    assert rules[0].points == 0
    assert rules[0].priority == 5


def test_new_score_rule_round_trips_through_parse():
    stored = json.dumps(
        [{"type": "regex", "value": ".*4K.*", "priority": 99, "mode": "score", "points": 25}]
    )
    rules = _parse_stream_ordering_rules(stored)
    assert rules[0].mode == "score"
    assert rules[0].points == 25


def test_negative_points_survive_parse():
    stored = json.dumps(
        [{"type": "regex", "value": ".*SD.*", "priority": 99, "mode": "score", "points": -50}]
    )
    assert _parse_stream_ordering_rules(stored)[0].points == -50


def test_invalid_mode_falls_back_to_priority():
    stored = json.dumps([{"type": "m3u", "value": "Acme", "priority": 5, "mode": "bogus"}])
    assert _parse_stream_ordering_rules(stored)[0].mode == "priority"


def test_non_int_points_coerce_to_zero():
    stored = json.dumps(
        [{"type": "m3u", "value": "Acme", "priority": 5, "mode": "score", "points": "abc"}]
    )
    assert _parse_stream_ordering_rules(stored)[0].points == 0


def test_dataclass_default_mode_is_priority():
    """The storage type defaults to the legacy-safe mode; 'score' for new rules
    is applied at the API/UI edge, not here."""
    rule = StreamOrderingRule(type="regex", value=".*HD.*", priority=99)
    assert rule.mode == "priority"
    assert rule.points == 0


# --- write + read round-trip (DB) ----------------------------------------


def test_score_rule_round_trips_through_db(db):
    with get_db() as conn:
        update_stream_ordering_rules(
            conn,
            [{"type": "regex", "value": ".*4K.*", "priority": 99, "mode": "score", "points": 25}],
        )
        conn.commit()
    with get_db() as conn:
        rules = get_stream_ordering_settings(conn).rules
    assert len(rules) == 1
    assert rules[0].mode == "score"
    assert rules[0].points == 25


def test_legacy_dict_write_defaults_to_priority(db):
    """Old UI/API payloads (no mode/points) must persist as hard priority rules."""
    with get_db() as conn:
        update_stream_ordering_rules(conn, [{"type": "m3u", "value": "Acme", "priority": 3}])
        conn.commit()
    with get_db() as conn:
        rules = get_stream_ordering_settings(conn).rules
    assert rules[0].mode == "priority"
    assert rules[0].points == 0


def test_dataclass_write_round_trips(db):
    with get_db() as conn:
        update_stream_ordering_rules(
            conn,
            [
                StreamOrderingRule(
                    type="regex", value=".*HD.*", priority=99, mode="score", points=10
                )
            ],
        )
        conn.commit()
    with get_db() as conn:
        rules = get_stream_ordering_settings(conn).rules
    assert rules[0].mode == "score"
    assert rules[0].points == 10


def test_bool_points_rejected_on_write(db):
    with get_db() as conn:
        update_stream_ordering_rules(
            conn,
            [{"type": "regex", "value": ".*x.*", "priority": 99, "mode": "score", "points": True}],
        )
        conn.commit()
    with get_db() as conn:
        rules = get_stream_ordering_settings(conn).rules
    assert rules[0].points == 0
