"""The matcher always includes final events (#977).

v2.10.0 removed the "Include final events" toggle and forced the flag on in the
team processor and the event lifecycle service. ``_match_streams`` kept reading
the vestigial ``settings.include_final_events`` column (default 0), so the
lifecycle kept a finished event's channel while the matcher excluded the event
from guide generation — a channel with an empty guide until its delete time.
"""

import sqlite3
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from teamarr.consumers.event_group_processor import matching
from teamarr.consumers.event_group_processor.matching import StreamMatching
from teamarr.database.connection import init_db


@pytest.fixture
def db_factory(tmp_path):
    db_path = tmp_path / "teamarr.db"
    init_db(str(db_path))

    @contextmanager
    def factory():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    return factory


class _Harness(StreamMatching):
    """StreamMatching with just the collaborators _match_streams touches."""

    def __init__(self, db_factory):
        self._db_factory = db_factory
        self._service = MagicMock()
        self._shared_events = {}

    def _load_sport_durations_cached(self):
        return {}

    def _build_epg_index(self, *args, **kwargs):
        return None

    def _get_all_known_leagues(self):
        return ["mlb"]


@pytest.mark.parametrize("stored", [0, 1])
def test_matcher_gets_final_events_whatever_the_column_says(db_factory, stored):
    with db_factory() as conn:
        conn.execute("UPDATE settings SET include_final_events = ? WHERE id = 1", (stored,))

    group = MagicMock()
    group.id = 1
    group.leagues = ["mlb"]

    with patch.object(matching, "StreamMatcher") as matcher_cls:
        matcher_cls.return_value.match_all.return_value = SimpleNamespace()
        _Harness(db_factory)._match_streams([], group, date(2026, 10, 4))

    assert matcher_cls.call_args.kwargs["include_final_events"] is True
