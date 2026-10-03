"""Recording a team's games on its managed team channel (#729).

Dispatcharr schedules a DVR recording from a channel, a start and an end, and
does not de-duplicate: two identical requests make two recordings. So Teamarr
remembers each recording it creates, updates it in place when a game moves,
and deletes a future one when the game is no longer wanted. Only games with a
stream attached to the team channel are recorded; event channels never are.
"""

from datetime import timedelta

import pytest

from teamarr.dispatcharr.types import OperationResult
from teamarr.services.team_channel_manager import (
    RECORDING_POST_MINUTES,
    RECORDING_PRE_MINUTES,
    TeamChannelManager,
)
from teamarr.utilities.tz import now_utc, parse_db_timestamp, to_db_utc

CHANNEL_ID = 36397


class FakeRecordingApi:
    """Stands in for ChannelManager's recording calls; records what it is asked."""

    def __init__(self):
        self.created: list[dict] = []
        self.updated: list[tuple[int, dict]] = []
        self.deleted: list[int] = []
        self.next_id = 100
        self.missing: set[int] = set()

    def create_recording(self, channel_id, start_time, end_time, custom_properties=None):
        self.next_id += 1
        self.created.append(
            {"id": self.next_id, "channel": channel_id, "start": start_time, "end": end_time,
             "props": custom_properties}
        )
        return OperationResult(success=True, data={"id": self.next_id})

    def update_recording(self, recording_id, fields):
        if recording_id in self.missing:
            return OperationResult(success=False, message="not_found", error="gone")
        self.updated.append((recording_id, fields))
        return OperationResult(success=True, data={"id": recording_id})

    def delete_recording(self, recording_id):
        self.deleted.append(recording_id)
        return OperationResult(success=True)


def _team(conn, *, record=True, managed=True, active=True) -> int:
    cur = conn.execute(
        """INSERT INTO teams (provider, provider_team_id, primary_league, leagues, sport,
                              team_name, channel_id, active,
                              managed_channel_enabled, managed_channel_record)
           VALUES ('espn', '130', 'college-football', '["college-football"]', 'football',
                   'Michigan Wolverines', 'michigan.cfb', ?, ?, ?)""",
        (int(active), int(managed), int(record)),
    )
    team_id = cur.lastrowid
    conn.execute(
        "INSERT INTO managed_team_channels (team_id, dispatcharr_channel_id, channel_number, "
        "sync_status) VALUES (?, ?, 800, 'ready')",
        (team_id, CHANNEL_ID),
    )
    return team_id


def _stream(conn, team_id, event_id, start, *, stream_id=1, removed=False):
    conn.execute(
        """INSERT INTO managed_team_channel_streams
               (team_id, dispatcharr_stream_id, event_id, event_provider, source_group_id,
                stream_name, event_start, removed_at)
           VALUES (?, ?, ?, 'espn', 1, 's', ?, ?)""",
        (team_id, stream_id, event_id, to_db_utc(start), to_db_utc(now_utc()) if removed else None),
    )


def _rows(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM managed_team_channel_recordings")]


@pytest.fixture
def api():
    return FakeRecordingApi()


@pytest.fixture
def manager(db_factory, api):
    return TeamChannelManager(db_factory, api)


def test_a_game_with_a_stream_is_recorded_once(db_factory, manager, api):
    kickoff = now_utc().replace(microsecond=0) + timedelta(hours=5)
    with db_factory() as conn:
        team = _team(conn)
        _stream(conn, team, "401", kickoff)
        _stream(conn, team, "401", kickoff, stream_id=2)  # two streams, one game
        conn.commit()

    assert manager.sync_recordings() == {"created": 1, "updated": 0, "removed": 0, "errors": 0}
    made = api.created[0]
    assert made["channel"] == CHANNEL_ID
    assert made["start"] == (kickoff - timedelta(minutes=RECORDING_PRE_MINUTES)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    assert made["props"]["program"]["title"] == "Michigan Wolverines"
    assert made["props"]["teamarr"]["event_id"] == "401"

    # Dispatcharr would happily make a second one: the next run must not ask.
    assert manager.sync_recordings()["created"] == 0
    assert len(api.created) == 1
    with db_factory() as conn:
        assert len(_rows(conn)) == 1


def test_end_runs_past_the_estimated_finish(db_factory, manager, api):
    kickoff = now_utc().replace(microsecond=0) + timedelta(hours=5)
    with db_factory() as conn:
        _stream(conn, _team(conn), "401", kickoff)
        conn.commit()
    manager.sync_recordings()

    with db_factory() as conn:
        row = _rows(conn)[0]
    length = parse_db_timestamp(row["end_time"]) - kickoff
    assert length >= timedelta(hours=2, minutes=RECORDING_POST_MINUTES)


def test_remembered_event_supplies_name_and_end(db_factory, manager, api):
    kickoff = now_utc().replace(microsecond=0) + timedelta(hours=5)
    with db_factory() as conn:
        _stream(conn, _team(conn), "401", kickoff)
        conn.commit()
    manager._recording_events[("espn", "401")] = {
        "name": "Michigan at Minnesota",
        "end": kickoff + timedelta(hours=4),
    }
    manager.sync_recordings()

    made = api.created[0]
    assert made["props"]["program"]["sub_title"] == "Michigan at Minnesota"
    assert made["end"] == (
        kickoff + timedelta(hours=4, minutes=RECORDING_POST_MINUTES)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.parametrize(
    "team_kwargs",
    [{"record": False}, {"managed": False}, {"active": False}],
    ids=["recording off", "channel not managed", "team inactive"],
)
def test_teams_that_do_not_qualify_are_not_recorded(db_factory, manager, api, team_kwargs):
    with db_factory() as conn:
        _stream(conn, _team(conn, **team_kwargs), "401", now_utc() + timedelta(hours=5))
        conn.commit()
    assert manager.sync_recordings()["created"] == 0
    assert api.created == []


def test_a_game_without_an_attached_stream_is_not_recorded(db_factory, manager, api):
    with db_factory() as conn:
        _stream(conn, _team(conn), "401", now_utc() + timedelta(hours=5), removed=True)
        conn.commit()
    assert manager.sync_recordings()["created"] == 0


def test_a_moved_game_updates_the_same_recording(db_factory, manager, api):
    kickoff = now_utc().replace(microsecond=0) + timedelta(hours=5)
    with db_factory() as conn:
        team = _team(conn)
        _stream(conn, team, "401", kickoff)
        conn.commit()
    manager.sync_recordings()
    rec_id = api.created[0]["id"]

    with db_factory() as conn:
        conn.execute(
            "UPDATE managed_team_channel_streams SET event_start = ?",
            (to_db_utc(kickoff + timedelta(hours=1)),),
        )
        conn.commit()
    result = manager.sync_recordings()

    assert result["updated"] == 1 and result["created"] == 0
    assert api.updated[0][0] == rec_id
    with db_factory() as conn:
        assert _rows(conn)[0]["dispatcharr_recording_id"] == rec_id


def test_a_recording_that_has_started_is_left_alone(db_factory, manager, api):
    kickoff = now_utc().replace(microsecond=0) - timedelta(minutes=30)  # in progress
    with db_factory() as conn:
        team = _team(conn)
        _stream(conn, team, "401", kickoff)
        conn.commit()
    manager.sync_recordings()
    assert len(api.created) == 1  # still catches a game already under way

    with db_factory() as conn:
        conn.execute(
            "UPDATE managed_team_channel_streams SET event_start = ?",
            (to_db_utc(kickoff + timedelta(minutes=10)),),
        )
        conn.commit()
    assert manager.sync_recordings() == {"created": 0, "updated": 0, "removed": 0, "errors": 0}
    assert api.updated == [] and api.deleted == []


def test_switching_recording_off_removes_future_recordings(db_factory, manager, api):
    with db_factory() as conn:
        team = _team(conn)
        _stream(conn, team, "401", now_utc() + timedelta(hours=5))
        conn.commit()
    manager.sync_recordings()
    rec_id = api.created[0]["id"]

    with db_factory() as conn:
        conn.execute("UPDATE teams SET managed_channel_record = 0")
        conn.commit()
    assert manager.sync_recordings()["removed"] == 1
    assert api.deleted == [rec_id]
    with db_factory() as conn:
        assert _rows(conn) == []


def test_a_started_recording_survives_the_game_dropping_out(db_factory, manager, api):
    """The stream detaches when the game ends; the recording must finish."""
    with db_factory() as conn:
        team = _team(conn)
        _stream(conn, team, "401", now_utc() - timedelta(minutes=30))
        conn.commit()
    manager.sync_recordings()

    with db_factory() as conn:
        conn.execute("UPDATE managed_team_channel_streams SET removed_at = CURRENT_TIMESTAMP")
        conn.commit()
    assert manager.sync_recordings()["removed"] == 0
    assert api.deleted == []


def test_a_recording_deleted_in_dispatcharr_is_not_made_again(db_factory, manager, api):
    kickoff = now_utc().replace(microsecond=0) + timedelta(hours=5)
    with db_factory() as conn:
        team = _team(conn)
        _stream(conn, team, "401", kickoff)
        conn.commit()
    manager.sync_recordings()
    api.missing.add(api.created[0]["id"])  # the user removed it by hand

    with db_factory() as conn:
        conn.execute(
            "UPDATE managed_team_channel_streams SET event_start = ?",
            (to_db_utc(kickoff + timedelta(hours=1)),),
        )
        conn.commit()
    manager.sync_recordings()
    manager.sync_recordings()
    assert len(api.created) == 1


def test_dry_run_schedules_nothing(db_factory, manager, api, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    with db_factory() as conn:
        _stream(conn, _team(conn), "401", now_utc() + timedelta(hours=5))
        conn.commit()
    assert manager.sync_recordings()["created"] == 0
    assert api.created == []


class TestRecordToggleApi:
    """Recording rides on the managed team channel: no channel, no recording."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        from teamarr.api.app import app
        from teamarr.database import init_db

        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
        init_db()
        return TestClient(app)

    def _make(self, client, **extra) -> int:
        resp = client.post(
            "/api/v1/teams",
            json={
                "provider": "espn", "provider_team_id": "130",
                "primary_league": "college-football", "leagues": ["college-football"],
                "sport": "football", "team_name": "Michigan Wolverines",
                "channel_id": "michigan.cfb", **extra,
            },
        )
        assert resp.status_code in (200, 201), resp.text
        return resp.json()["id"]

    def test_can_be_switched_on_with_a_managed_channel(self, client):
        team = self._make(client, managed_channel_enabled=True)
        resp = client.patch(f"/api/v1/teams/{team}", json={"managed_channel_record": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["managed_channel_record"] is True

    def test_refused_without_a_managed_channel(self, client):
        team = self._make(client)
        resp = client.patch(f"/api/v1/teams/{team}", json={"managed_channel_record": True})
        assert resp.status_code == 400
        assert "managed" in resp.json()["detail"]

    def test_switching_the_channel_off_switches_recording_off(self, client):
        team = self._make(client, managed_channel_enabled=True)
        client.patch(f"/api/v1/teams/{team}", json={"managed_channel_record": True})
        # The edit dialog sends both fields on every save.
        resp = client.patch(
            f"/api/v1/teams/{team}",
            json={"managed_channel_enabled": False, "managed_channel_record": True},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["managed_channel_record"] is False
