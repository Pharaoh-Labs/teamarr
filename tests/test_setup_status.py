"""Getting Started checklist state (#818).

The card reads six facts and hides itself once the install is working — a
completed run and active channels — or once the user dismissed it. Every fact
comes from the database; Dispatcharr's state comes through an injected probe
so the test never touches the network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.database import get_db, init_db
from teamarr.database.settings import update_display_settings
from teamarr.database.stats import create_run, save_run
from teamarr.database.subscription import update_subscription
from teamarr.services.setup_status import compute_setup_status

client = TestClient(app)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    with get_db() as c:
        yield c


def _status(conn, connected=True):
    return compute_setup_status(conn, lambda: (connected, connected))


def _add_source(conn, name="EPL", channel_source=False):
    conn.execute(
        "INSERT INTO event_epg_groups (name, leagues, is_channel_source) VALUES (?, ?, ?)",
        (name, '["nfl"]', int(channel_source)),
    )
    conn.commit()


def _complete_run(conn, streams_matched=12, status="completed", error=None):
    run = create_run(conn, "full_epg")
    run.streams_matched = streams_matched
    run.complete(status, error)
    save_run(conn, run)
    conn.commit()


def _add_channel(conn):
    conn.execute(
        "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name) "
        "VALUES ('e1', 'espn', 'teamarr-e1', 'A vs B')"
    )
    conn.commit()


def test_fresh_install_shows_nothing_done(conn):
    s = _status(conn, connected=False)
    assert s.to_dict() == {
        "dispatcharr_configured": False,
        "dispatcharr_connected": False,
        "sources": 0,
        "leagues": 0,
        "streams_matched": 0,
        "runs_completed": 0,
        "channels_active": 0,
        "dismissed": False,
        "complete": False,
        "visible": True,
    }


def test_each_step_reads_real_state(conn):
    _add_source(conn)
    _add_source(conn, "hidden", channel_source=True)  # system row, not a user source
    update_subscription(conn, leagues=["nfl", "nhl"])
    _complete_run(conn, streams_matched=7)
    s = _status(conn)
    assert s.dispatcharr_connected is True
    assert s.sources == 1
    assert s.leagues == 2
    assert s.streams_matched == 7
    assert s.runs_completed == 1
    assert s.channels_active == 0
    assert s.complete is False and s.visible is True


def test_complete_means_a_run_and_channels_not_page_visits(conn):
    _complete_run(conn)
    assert _status(conn).complete is False  # a run alone is not done
    _add_channel(conn)
    s = _status(conn)
    assert s.complete is True
    assert s.visible is False


def test_a_team_channel_counts_as_a_channel(conn):
    """A team-only install is done when its first team channel exists in Dispatcharr."""
    _complete_run(conn)
    conn.execute(
        "INSERT INTO teams (id, provider_team_id, primary_league, sport, team_name, channel_id) "
        "VALUES (1, '12', 'nfl', 'football', 'Detroit Lions', 'Lions.nfl')"
    )
    conn.execute(
        "INSERT INTO managed_team_channels (team_id, dispatcharr_channel_id, channel_number) "
        "VALUES (1, 500, 1001)"
    )
    conn.commit()
    s = _status(conn)
    assert s.channels_active == 1 and s.complete is True


def test_a_failed_run_does_not_count(conn):
    _complete_run(conn, status="failed", error="boom")
    _add_channel(conn)
    assert _status(conn).runs_completed == 0
    assert _status(conn).complete is False


def test_dismissed_hides_the_card_and_restore_brings_it_back(conn):
    update_display_settings(conn, getting_started_dismissed=True)
    conn.commit()
    s = _status(conn)
    assert s.dismissed is True and s.visible is False
    update_display_settings(conn, getting_started_dismissed=False)
    conn.commit()
    assert _status(conn).visible is True


def test_routes_round_trip(conn):
    """Dismiss and restore through the API, and the status reflects it."""
    assert client.get("/api/v1/setup/status").json()["visible"] is True
    assert client.post("/api/v1/setup/getting-started/dismiss").json() == {"dismissed": True}
    body = client.get("/api/v1/setup/status").json()
    assert body["dismissed"] is True and body["visible"] is False
    assert client.post("/api/v1/setup/getting-started/restore").json() == {"dismissed": False}
    assert client.get("/api/v1/setup/status").json()["visible"] is True
