"""Tests for the static team channel status endpoint helpers."""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from teamarr.api.routes import teams as teams_route
from teamarr.services.team_channel_status import (
    build_team_channel_status,
    find_next_live_window,
    parse_xmltv_timestamp,
)

TEAM = {
    "id": 5762,
    "provider": "espn",
    "provider_team_id": "20",
    "primary_league": "mlb",
    "leagues": ["mlb"],
    "sport": "baseball",
    "team_name": "Washington Nationals",
    "team_abbrev": "WSH",
    "channel_id": "teamarr-team-sfv6-test-washington-nationals-20",
    "active": 1,
}


XMLTV = """<?xml version="1.0"?>
<tv>
  <channel id="teamarr-team-sfv6-test-washington-nationals-20">
    <display-name>Washington Nationals</display-name>
  </channel>
  <programme start="20260609010000 +0000" stop="20260609050000 +0000"
      channel="teamarr-team-sfv6-test-washington-nationals-20">
    <title>Past game</title>
    <live/>
  </programme>
  <programme start="20260610014500 +0000" stop="20260610051500 +0000"
      channel="teamarr-team-sfv6-test-washington-nationals-20">
    <title>MLB Baseball</title>
    <sub-title>Washington Nationals at San Francisco Giants</sub-title>
    <category>Sports Event</category>
    <live/>
  </programme>
  <programme start="20260610194500 +0000" stop="20260610231500 +0000"
      channel="teamarr-team-sfv6-test-washington-nationals-20">
    <title>MLB Baseball Later</title>
    <category>Sports Event</category>
    <live/>
  </programme>
</tv>
"""


@dataclass(frozen=True)
class FakeDispatcharrChannel:
    id: int = 8698
    uuid: str = "e5aa42b8-829d-4902-8a31-ce7c668110ca"
    name: str = "[TEST] Washington Nationals"
    channel_number: str = "9900.0"
    tvg_id: str = "teamarr-team-sfv6-test-washington-nationals-20"
    streams: tuple[int, ...] = (602572, 602573, 602574)


def test_parse_xmltv_timestamp_utc():
    parsed = parse_xmltv_timestamp("20260610014500 +0000")
    assert parsed is not None
    assert parsed.isoformat() == "2026-06-10T01:45:00+00:00"


def test_parse_xmltv_timestamp_invalid_returns_none():
    assert parse_xmltv_timestamp("broken") is None
    assert parse_xmltv_timestamp(None) is None


def test_find_next_live_window_skips_past_programmes():
    window = find_next_live_window(
        XMLTV,
        channel_id="teamarr-team-sfv6-test-washington-nationals-20",
        now=datetime(2026, 6, 9, 20, 0, tzinfo=UTC),
    )

    assert window is not None
    assert window["title"] == "MLB Baseball"
    assert window["sub_title"] == "Washington Nationals at San Francisco Giants"
    assert window["start"].isoformat() == "2026-06-10T01:45:00+00:00"
    assert window["stop"].isoformat() == "2026-06-10T05:15:00+00:00"


def test_find_next_live_window_requires_live_signal():
    xmltv = """<tv>
      <programme start="20260610014500 +0000" stop="20260610051500 +0000"
          channel="team">
        <title>Studio filler</title>
      </programme>
    </tv>"""

    assert find_next_live_window(xmltv, "team", now=datetime(2026, 6, 9, tzinfo=UTC)) is None


def test_find_next_live_window_matches_default_sports_category():
    """Teamarr's DEFAULT output (category 'Sports', no <live> tag) must be found.

    Default templates set xmltv_categories=['Sports'] and live=False, so requiring
    a <live> tag or 'Sports Event' category would make the endpoint never reach
    'ready' on a stock setup. The window is found; is_live reflects the (absent) tag.
    """
    xmltv = """<tv>
      <programme start="20260610014500 +0000" stop="20260610051500 +0000"
          channel="team">
        <title>MLB Baseball</title>
        <category>Sports</category>
      </programme>
    </tv>"""

    window = find_next_live_window(xmltv, "team", now=datetime(2026, 6, 9, tzinfo=UTC))
    assert window is not None
    assert window["title"] == "MLB Baseball"
    assert window["is_live"] is False  # no <live> tag, but still a real game window


def test_build_team_channel_status_ready():
    status = build_team_channel_status(
        team=TEAM,
        dispatcharr_channel=FakeDispatcharrChannel(),
        xmltv_content=XMLTV,
        xmltv_updated_at="2026-06-09 19:27:40",
        now=datetime(2026, 6, 9, 20, 0, tzinfo=UTC),
    )

    assert status["status"] == "ready"
    assert status["missing"] == []
    assert status["team"]["active"] is True
    assert status["dispatcharr_channel"]["found"] is True
    assert status["dispatcharr_channel"]["id"] == 8698
    assert status["dispatcharr_channel"]["stream_count"] == 3
    assert status["next_live_window"]["found"] is True


def test_build_team_channel_status_missing_dispatcharr_and_xmltv():
    status = build_team_channel_status(
        team=TEAM,
        dispatcharr_channel=None,
        xmltv_content=None,
        dispatcharr_error="Dispatcharr connection not available",
    )

    assert status["status"] == "incomplete"
    assert status["missing"] == ["dispatcharr_channel", "team_epg_xmltv"]
    assert status["dispatcharr_channel"]["found"] is False
    assert status["dispatcharr_channel"]["error"] == "Dispatcharr connection not available"
    assert status["next_live_window"]["found"] is False


def _live_now_xmltv() -> str:
    """XMLTV with a programme live *right now* (relative to real time).

    The endpoint doesn't accept an injected ``now``, so endpoint tests must use
    dates relative to the actual clock — fixed dates turn the tests into
    time-bombs that fail once the hardcoded day passes.
    """
    fmt = "%Y%m%d%H%M%S +0000"
    start = (datetime.now(UTC) - timedelta(hours=1)).strftime(fmt)
    stop = (datetime.now(UTC) + timedelta(hours=2)).strftime(fmt)
    return f"""<tv>
      <programme start="{start}" stop="{stop}" channel="{TEAM["channel_id"]}">
        <title>MLB Baseball</title>
        <sub-title>Washington Nationals at San Francisco Giants</sub-title>
        <category>Sports Event</category>
        <live/>
      </programme>
    </tv>"""


def _team_status_db(xmltv: str | None = XMLTV):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            provider TEXT NOT NULL,
            provider_team_id TEXT NOT NULL,
            primary_league TEXT NOT NULL,
            leagues TEXT DEFAULT '[]',
            sport TEXT NOT NULL,
            team_name TEXT NOT NULL,
            team_abbrev TEXT,
            team_logo_url TEXT,
            team_color TEXT,
            channel_id TEXT NOT NULL,
            channel_logo_url TEXT,
            template_id INTEGER,
            active INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE team_epg_xmltv (
            team_id INTEGER PRIMARY KEY,
            xmltv_content TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        """
        INSERT INTO teams (
            id, provider, provider_team_id, primary_league, leagues, sport,
            team_name, team_abbrev, channel_id, active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            TEAM["id"],
            TEAM["provider"],
            TEAM["provider_team_id"],
            TEAM["primary_league"],
            '["mlb"]',
            TEAM["sport"],
            TEAM["team_name"],
            TEAM["team_abbrev"],
            TEAM["channel_id"],
            TEAM["active"],
        ),
    )
    if xmltv is not None:
        conn.execute(
            "INSERT INTO team_epg_xmltv (team_id, xmltv_content) VALUES (?, ?)",
            (TEAM["id"], xmltv),
        )
    conn.commit()
    return conn


def _patch_team_status_db(monkeypatch, conn):
    @contextmanager
    def fake_get_db():
        yield conn

    monkeypatch.setattr(teams_route, "get_db", fake_get_db)


def test_team_channel_status_endpoint_ready(monkeypatch):
    conn = _team_status_db(_live_now_xmltv())
    _patch_team_status_db(monkeypatch, conn)

    import teamarr.dispatcharr as dispatcharr

    class FakeManager:
        def __init__(self, client):
            self.client = client

        def find_by_tvg_id(self, tvg_id):
            assert tvg_id == TEAM["channel_id"]
            return FakeDispatcharrChannel()

    monkeypatch.setattr(dispatcharr, "get_dispatcharr_client", lambda db_factory: object())
    monkeypatch.setattr(dispatcharr, "ChannelManager", FakeManager)

    response = teams_route.get_team_channel_status(TEAM["id"])

    assert response["status"] == "ready"
    assert response["team"]["team_name"] == "Washington Nationals"
    assert response["dispatcharr_channel"]["id"] == 8698
    assert response["next_live_window"]["title"] == "MLB Baseball"


def test_team_channel_status_endpoint_missing_dispatcharr(monkeypatch):
    conn = _team_status_db(_live_now_xmltv())
    _patch_team_status_db(monkeypatch, conn)

    import teamarr.dispatcharr as dispatcharr

    monkeypatch.setattr(dispatcharr, "get_dispatcharr_client", lambda db_factory: None)

    response = teams_route.get_team_channel_status(TEAM["id"])

    assert response["status"] == "incomplete"
    assert response["missing"] == ["dispatcharr_channel"]
    assert response["dispatcharr_channel"]["error"] == "Dispatcharr connection not available"


def test_team_channel_status_endpoint_team_not_found(monkeypatch):
    conn = _team_status_db()
    _patch_team_status_db(monkeypatch, conn)

    with pytest.raises(teams_route.HTTPException) as exc:
        teams_route.get_team_channel_status(999)

    assert exc.value.status_code == 404
