"""An event template assignment decides event channels, never matching (#1061).

The processor used to skip a source outright when no subscription template
existed anywhere. Managed team channels are fed from that same matching, so
"I want no event channels" became "nothing matches". Now matching always
runs, an event that resolves no template is a clean skip, and channels a
removed assignment had created are retired.
"""

import contextlib
import sqlite3
from datetime import date
from unittest.mock import MagicMock

from teamarr.consumers.event_group_processor import EventGroupProcessor
from teamarr.consumers.matching.matcher import BatchMatchResult
from teamarr.consumers.matching.result import EXCLUDED_DISPLAY, ExcludedReason
from teamarr.database.channels import create_managed_channel
from teamarr.database.groups import create_group, get_group
from teamarr.services.stream_filter import FilterResult
from tests.fakes import make_event
from tests.helpers import SCHEMA_PATH


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def _factory(conn):
    @contextlib.contextmanager
    def factory():
        yield conn
        conn.commit()

    return factory


def _processor(conn):
    return EventGroupProcessor(db_factory=_factory(conn), service=MagicMock())


def _assign_default_template(conn):
    cur = conn.execute("INSERT INTO templates (name, template_type) VALUES ('T', 'event')")
    conn.execute("INSERT INTO subscription_templates (template_id) VALUES (?)", (cur.lastrowid,))
    conn.commit()


def test_reason_has_display_text():
    assert EXCLUDED_DISPLAY[ExcludedReason.NO_EVENT_TEMPLATE] == "No event template for this league"


def test_a_source_matches_without_any_event_template(monkeypatch):
    conn = _db()
    gid = create_group(conn, name="NHL", leagues=["nhl"], m3u_group_id=7)
    conn.commit()
    group = get_group(conn, gid)
    proc = _processor(conn)
    streams = [{"id": 11, "name": "NHL | Red Wings at Leafs"}]
    monkeypatch.setattr(proc, "_fetch_streams", lambda g: list(streams))
    monkeypatch.setattr(
        proc,
        "_filter_streams",
        lambda s, g: (list(streams), FilterResult(total_input=1, passed_count=1)),
    )
    calls = []
    monkeypatch.setattr(
        proc, "_match_streams", lambda *a, **k: calls.append(a) or BatchMatchResult()
    )
    lifecycle = MagicMock()
    monkeypatch.setattr(proc, "_get_lifecycle_service", lambda: lifecycle)

    result = proc._process_group_internal(conn, group, date.today())

    assert len(calls) == 1, "matching must run with no template assigned"
    assert result.errors == []


def test_channels_of_an_untemplated_league_are_retired(monkeypatch):
    conn = _db()
    gid = create_group(conn, name="NHL", leagues=["nhl"], m3u_group_id=7)
    create_managed_channel(
        conn=conn,
        event_epg_group_id=gid,
        event_id="401",
        event_provider="espn",
        tvg_id="tvg-401",
        channel_name="NHL | DET/TOR",
    )
    conn.commit()
    group = get_group(conn, gid)
    proc = _processor(conn)
    deleted = []
    monkeypatch.setattr(
        proc,
        "_delete_channel_for_team_filter",
        lambda c, ch, reason, change_source="team_filter": (
            deleted.append((ch.event_id, reason, change_source)) or True
        ),
    )
    events = {"401": make_event(sport="hockey", league="nhl")}

    assert proc._cleanup_untemplated_channels(group, conn, events) == 1
    assert deleted == [("401", "no_event_template", "template_assignment")]

    # With a default rule back, the same channel is kept.
    deleted.clear()
    _assign_default_template(conn)
    assert proc._cleanup_untemplated_channels(group, conn, events) == 0
    assert deleted == []


def test_channels_for_events_not_matched_this_run_are_left_alone(monkeypatch):
    conn = _db()
    gid = create_group(conn, name="NHL", leagues=["nhl"], m3u_group_id=7)
    create_managed_channel(
        conn=conn,
        event_epg_group_id=gid,
        event_id="999",
        event_provider="espn",
        tvg_id="tvg-999",
        channel_name="NHL | old",
    )
    conn.commit()
    proc = _processor(conn)
    monkeypatch.setattr(proc, "_delete_channel_for_team_filter", lambda *a, **k: True)

    assert proc._cleanup_untemplated_channels(get_group(conn, gid), conn, {}) == 0
