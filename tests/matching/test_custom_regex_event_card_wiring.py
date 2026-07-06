"""Regression tests: Combat/Event Card custom regex reaches the matcher.

The fighters / event_name custom-regex fields were stored, validated and
API-exposed, but ``StreamMatcher`` never accepted them and ``CustomRegexConfig``
was built without them — so the classifier's fighter/event-name override path
was dead at match time (the rest of the feature was a ghost control). These
tests pin the wiring so the EVENT_CARD custom regex stays load-bearing.

(Racing intentionally has no custom regex: it matches by date coverage, not by
name-parsing, and the relevant lever — Date/Time Extraction — already applies
to every category before routing.)
"""

import sqlite3
from unittest.mock import MagicMock

from teamarr.consumers.matching.classifier import StreamCategory, classify_stream
from teamarr.consumers.matching.matcher import StreamMatcher
from tests.helpers import SCHEMA_PATH

SCHEMA = SCHEMA_PATH


def _db_factory():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    return conn


def _matcher(**flags) -> StreamMatcher:
    return StreamMatcher(
        service=MagicMock(),
        db_factory=_db_factory,
        group_id=1,
        search_leagues=["ufc"],
        include_leagues=["ufc"],
        **flags,
    )


def test_fighters_pattern_reaches_custom_regex_config():
    """A fighters pattern enabled on the group must build a CustomRegexConfig."""
    m = _matcher(
        custom_regex_fighters=r"(?P<fighter1>\w+)\s+VS\s+(?P<fighter2>\w+)",
        custom_regex_fighters_enabled=True,
    )
    assert m._custom_regex is not None
    assert m._custom_regex.fighters_enabled
    assert m._custom_regex.get_fighters_pattern() is not None


def test_event_name_pattern_reaches_custom_regex_config():
    m = _matcher(
        custom_regex_event_name=r"(?P<event_name>UFC\s+\d+)",
        custom_regex_event_name_enabled=True,
    )
    assert m._custom_regex is not None
    assert m._custom_regex.event_name_enabled


def test_no_event_card_pattern_leaves_config_none():
    """No enabled pattern → no config (unchanged behaviour)."""
    m = _matcher()
    assert m._custom_regex is None


def test_classifier_applies_custom_fighters_from_matcher_config():
    """End-to-end: the matcher-built config drives the classifier's override."""
    m = _matcher(
        custom_regex_fighters=r"(?P<fighter1>SUPERMAN)\s+VS\s+(?P<fighter2>BATMAN)",
        custom_regex_fighters_enabled=True,
    )
    classified = classify_stream(
        "UFC 300 | SUPERMAN VS BATMAN",
        league_event_type="event_card",
        custom_regex=m._custom_regex,
    )
    assert classified.category == StreamCategory.EVENT_CARD
    assert classified.team1 == "SUPERMAN"
    assert classified.team2 == "BATMAN"
    assert classified.custom_regex_used
