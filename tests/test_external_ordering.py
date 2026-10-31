"""Podium handoff contract: real DB, HTTP boundary, crash recovery and workers."""

import json
import multiprocessing
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.api.routes import channels as routes
from teamarr.consumers import generation
from teamarr.database import get_db, init_db
from teamarr.database.channels import add_stream_to_channel, create_managed_channel
from teamarr.dispatcharr.managers.channels import ChannelManager
from teamarr.services.external_ordering import preserve_live_order
from teamarr.services.ordering_lock import ProcessLock


class FakeHTTP:
    """Dispatcharr's full stream replacement, with injectable uncertain failures."""

    def __init__(self):
        self._base_url = f"http://external-order-test-{id(self)}"
        self.streams = [1, 2, 3]
        self.patches = []
        self.fail = False
        self.read_fails = False
        self.alter_order = False
        self.after_patch = None

    def payload(self):
        return {"id": 800, "uuid": "remote-800", "name": "Channel", "streams": self.streams[:]}

    def get(self, url):
        if self.read_fails:
            return None
        return SimpleNamespace(status_code=200, json=self.payload)

    def paginated_get(self, *args, **kwargs):
        return [self.payload()]

    paginated_get_or_none = paginated_get

    def patch(self, url, data):
        self.patches.append(dict(data))
        if self.fail:
            return SimpleNamespace(status_code=500)
        if "streams" in data:
            self.streams = list(data["streams"])
            if self.alter_order:
                self.streams.reverse()
        if self.after_patch:
            self.after_patch()
        return SimpleNamespace(status_code=200, json=self.payload)

    def parse_api_error(self, response):
        return "injected Dispatcharr failure"


@pytest.fixture(params=["event", "team", "plugin"])
def channel(request, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "teamarr.db"))
    init_db()
    with get_db() as conn:
        if request.param == "team":
            conn.execute(
                "INSERT INTO teams (id, team_name, provider, provider_team_id, "
                "primary_league, sport, channel_id, managed_channel_enabled) "
                "VALUES (1, 'Team', 'espn', '1', 'nfl', 'football', 'team-1', 1)"
            )
            conn.execute(
                "INSERT INTO managed_team_channels (team_id, dispatcharr_channel_id, "
                "channel_number) VALUES (1, 800, 5001)"
            )
            # A source group is required by the team-membership schema.
            conn.execute(
                "INSERT INTO event_epg_groups (id, name, leagues) VALUES (1, 'Source', '[]')"
            )
            for stream in (1, 2, 3):
                conn.execute(
                    "INSERT INTO managed_team_channel_streams (team_id, dispatcharr_stream_id, "
                    "event_id, event_provider, source_group_id, attach_at, priority) "
                    "VALUES (1, ?, 'game', 'espn', 1, '', ?)",
                    (stream, stream),
                )
            table, member_table, member_key = (
                "managed_team_channels",
                "managed_team_channel_streams",
                "team_id",
            )
        else:
            kwargs = {"dispatcharr_channel_id": 800}
            if request.param == "plugin":
                kwargs.update(
                    plugin_id="test", plugin_logical_key="game", plugin_adoption_key="game"
                )
            local_id = create_managed_channel(
                conn, None, "game", "espn", "teamarr-game", "Channel", **kwargs
            )
            for stream in (1, 2, 3):
                add_stream_to_channel(conn, local_id, stream, priority=stream)
            table, member_table, member_key = (
                "managed_channels",
                "managed_channel_streams",
                "managed_channel_id",
            )
    http = FakeHTTP()
    manager = ChannelManager(http)
    monkeypatch.setattr(
        routes, "get_dispatcharr_connection", lambda *a: SimpleNamespace(channels=manager)
    )
    return SimpleNamespace(
        kind=request.param,
        table=table,
        members=member_table,
        member_key=member_key,
        http=http,
        manager=manager,
        client=TestClient(app),
    )


def put(channel, streams):
    return channel.client.put(
        "/api/v1/channels/by-dispatcharr/800/external-order",
        json={"owner": "podium", "streams": streams},
    )


def state(channel):
    with get_db() as conn:
        return dict(conn.execute(f"SELECT * FROM {channel.table}").fetchone())


def stored_order(channel):
    with get_db() as conn:
        return [
            row[0]
            for row in conn.execute(
                f"SELECT dispatcharr_stream_id FROM {channel.members} WHERE removed_at IS NULL "
                "ORDER BY priority, id"
            )
        ]


def test_external_write_persists_and_is_idempotent(channel):
    for _ in range(2):
        response = put(channel, [3, 2, 1])
        assert response.status_code == 200, response.text
        assert response.json() == {"managed": True, "applied": True}
    assert channel.http.streams == stored_order(channel) == [3, 2, 1]
    assert state(channel)["ordering_owner"] == "podium"
    assert state(channel)["external_order_pending"] is None
    assert len(state(channel)["stream_order_hash"]) == 64
    # Fresh connections, manager and initialization simulate process restart.
    init_db()
    fresh = ChannelManager(channel.http)
    assert fresh.update_channel(800, {"streams": [1, 2, 3]}).success
    assert channel.http.streams == [3, 2, 1]


def test_failed_remote_write_retains_ownership_and_fences_generation(channel):
    channel.http.fail = True
    assert put(channel, [3, 1, 2]).status_code == 502
    assert state(channel)["ordering_owner"] == "podium"
    assert json.loads(state(channel)["external_order_pending"])["streams"] == [3, 1, 2]
    channel.http.fail = False
    assert not channel.manager.update_channel(800, {"streams": [1, 2, 3]}).success
    assert put(channel, [3, 1, 2]).json() == {"managed": True, "applied": True}
    assert channel.http.streams == [3, 1, 2]


def test_crash_after_remote_success_recovers_membership_removal(channel):
    def crash():
        raise RuntimeError("worker died after Dispatcharr accepted the write")

    channel.http.after_patch = crash
    assert put(channel, [3, 1]).status_code == 502
    assert channel.http.streams == [3, 1]
    assert 2 in stored_order(channel)
    channel.http.after_patch = None
    assert put(channel, [3, 1]).status_code == 200
    assert stored_order(channel) == [3, 1]
    # Undo may restore a known eligible membership, with its stored metadata.
    assert put(channel, [2, 3, 1]).status_code == 200
    assert stored_order(channel) == [2, 3, 1]


def test_membership_changes_preserve_survivors_append_new_and_remove_obsolete(channel):
    assert put(channel, [3, 2, 1]).status_code == 200
    # A stale ranking combined with a legitimate membership change.
    assert channel.manager.update_channel(800, {"streams": [1, 3, 4]}).success
    assert channel.http.streams == [3, 1, 4]
    assert channel.manager.update_channel(800, {"streams": [4, 3]}).success
    assert channel.http.streams == [3, 4]
    # Metadata/EPG updates remain active.
    assert channel.manager.update_channel(800, {"name": "Updated"}).success


def test_known_local_addition_not_currently_live_is_applied(channel):
    channel.http.streams = [1, 2]
    assert put(channel, [3, 2, 1]).status_code == 200
    assert channel.http.streams == stored_order(channel) == [3, 2, 1]


def test_unknown_membership_addition_is_explicitly_rejected(channel):
    response = put(channel, [3, 99])
    assert response.status_code == 422
    assert "Unsupported membership additions" in response.text
    assert channel.http.patches == []
    assert state(channel)["ordering_owner"] == "teamarr"


@pytest.mark.parametrize("streams", [[1, 1], [True, 2], ["1", 2], [1.0, 2]])
def test_stream_ids_are_unique_strict_integers(channel, streams):
    assert put(channel, streams).status_code == 422
    assert channel.http.patches == []


def test_unmanaged_ack_is_exact_and_has_no_side_effects(channel, monkeypatch):
    def unexpected(*args):
        pytest.fail("Unmanaged acknowledgement must not call Dispatcharr")

    monkeypatch.setattr(routes, "get_dispatcharr_connection", unexpected)
    with get_db() as conn:
        before = list(conn.iterdump())
    response = channel.client.put(
        "/api/v1/channels/by-dispatcharr/999/external-order",
        json={"owner": "podium", "streams": [3, 2, 1]},
    )
    assert response.status_code == 200
    assert response.json() == {"managed": False, "applied": False}
    with get_db() as conn:
        assert list(conn.iterdump()) == before


def test_release_is_explicit_and_allows_normal_ordering(channel):
    assert put(channel, [3, 2, 1]).status_code == 200
    response = channel.client.put("/api/v1/channels/by-dispatcharr/800/ordering-owner")
    assert response.status_code == 200
    assert state(channel)["ordering_owner"] == "teamarr"
    assert channel.manager.update_channel(800, {"streams": [1, 2, 3]}).success
    assert channel.http.streams == [1, 2, 3]


def test_busy_generation_and_channel_locks_block_external_write(channel):
    assert generation._generation_lock.acquire(blocking=False)
    try:
        assert put(channel, [3, 2, 1]).status_code == 409
    finally:
        generation._generation_lock.release()
    lock = ProcessLock("channel-800-order")
    with lock:
        assert put(channel, [3, 2, 1]).status_code == 409
    assert channel.http.patches == []


def test_read_failure_and_malformed_remote_ack_fail_closed(channel):
    channel.http.read_fails = True
    assert put(channel, [3, 2, 1]).status_code == 502
    assert channel.http.patches == []
    channel.http.read_fails = False
    channel.http.alter_order = True
    assert put(channel, [3, 2, 1]).status_code == 502
    assert state(channel)["ordering_owner"] == "podium"
    assert state(channel)["external_order_pending"] is not None


@pytest.mark.parametrize("channel", ["event"], indirect=True)
def test_event_generation_and_reorder_only_keep_external_order_and_ignore_live_pin(channel):
    assert put(channel, [3, 2, 1]).status_code == 200
    # Another worker can retain a pre-handoff cache after Podium succeeds.
    from teamarr.dispatcharr.types import DispatcharrChannel

    stale = channel.http.payload() | {"streams": [1, 2, 3]}
    channel.manager._cache.populate([DispatcharrChannel.from_api(stale)])
    # Even a priority mutation from matching/rule sync must not restore old rank.
    with get_db() as conn:
        conn.execute("UPDATE managed_channel_streams SET priority = dispatcharr_stream_id")
    with (
        patch.object(generation, "ChannelManager", return_value=channel.manager),
        patch("teamarr.consumers.lifecycle.is_channel_event_live", return_value=True),
        patch(
            "teamarr.services.team_channel_manager.TeamChannelManager.sync_stream_ordering",
            return_value={"channels": 0, "streams": 0, "errors": 0},
        ),
    ):
        result = generation._apply_stream_ordering(get_db, channel.http, lambda *a: None)
        assert result["channels_reordered"] == 0
        assert channel.http.streams == stored_order(channel) == [3, 2, 1]
        assert generation.run_stream_ordering_only(get_db, channel.http) is not None
        assert channel.http.streams == stored_order(channel) == [3, 2, 1]


def _hold_worker_lock(name, ready, release):
    with ProcessLock(name):
        ready.set()
        release.wait(15)


def test_multiple_workers_cannot_publish_a_stale_generation(channel):
    # Spawn (not fork) ensures independent Python locks and DB connections.
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_hold_worker_lock, args=("generation", ready, release))
    process.start()
    try:
        assert ready.wait(10)
        assert put(channel, [3, 2, 1]).status_code == 409
        assert generation.run_stream_ordering_only(get_db, channel.http) is None
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join()
    assert process.exitcode == 0
    assert put(channel, [3, 2, 1]).status_code == 200
    # A delayed worker's cached ranking is fenced at the network boundary.
    stale_worker = ChannelManager(channel.http)
    assert stale_worker.update_channel(800, {"streams": [1, 2, 3]}).success
    assert channel.http.streams == [3, 2, 1]


def test_order_merge_is_stable():
    assert preserve_live_order([3, 2, 1], [1, 3, 4]) == [3, 1, 4]
    assert preserve_live_order([3, 2, 1], []) == []


@pytest.mark.parametrize("channel", ["team"], indirect=True)
def test_team_ordering_and_windows_after_external_write(channel):
    from teamarr.services.team_channel_manager import TeamChannelManager

    assert put(channel, [3, 2, 1]).status_code == 200
    with get_db() as conn:
        conn.execute("UPDATE managed_team_channel_streams SET priority = dispatcharr_stream_id")
        conn.execute(
            "UPDATE managed_team_channel_streams SET detach_at = '2000-01-01' "
            "WHERE dispatcharr_stream_id = 2"
        )
    result = TeamChannelManager(get_db, channel.manager).sync_stream_ordering()
    assert result["errors"] == 0
    assert channel.http.streams == [3, 1]
    assert state(channel)["ordering_owner"] == "podium"
    assert put(channel, [2, 3, 1]).status_code == 422


@pytest.mark.parametrize("channel", ["event"], indirect=True)
def test_generation_skips_live_pin_and_rule_scoring(channel):
    assert put(channel, [3, 2, 1]).status_code == 200
    with get_db() as conn:
        conn.execute(
            "UPDATE settings SET stream_ordering_rules = ?",
            (json.dumps([{"type": "catch_all", "value": "", "priority": 10}]),),
        )
    with (
        patch.object(generation, "ChannelManager", return_value=channel.manager),
        patch("teamarr.consumers.lifecycle.is_channel_event_live") as live_pin,
        patch("teamarr.services.stream_ordering.StreamOrderingService.compute_priority") as rank,
    ):
        generation._apply_stream_ordering(get_db, channel.http, lambda *a: None, manual=False)
        live_pin.assert_not_called()
        rank.assert_not_called()
    assert channel.http.streams == stored_order(channel) == [3, 2, 1]


def test_partial_or_ambiguous_ownership_never_acknowledged_unmanaged(channel):
    with get_db() as conn:
        if channel.kind == "team":
            conn.execute("UPDATE teams SET managed_channel_enabled = 0")
        else:
            conn.execute("UPDATE managed_channels SET deleted_at = CURRENT_TIMESTAMP")
    response = put(channel, [3, 2, 1])
    assert response.json() != {"managed": False, "applied": False}
    if channel.kind != "team":
        assert response.status_code == 409


def test_future_membership_cannot_be_attached(channel):
    with get_db() as conn:
        conn.execute(
            f"UPDATE {channel.members} SET attach_at = '2999-01-01', detach_at = '2999-01-02' "
            "WHERE dispatcharr_stream_id = 3"
        )
    assert put(channel, [3, 2, 1]).status_code == 422
    assert channel.http.patches == []


def test_kernel_lock_is_released_when_worker_dies(channel):
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_hold_worker_lock, args=("generation", ready, release))
    process.start()
    try:
        assert ready.wait(10)
        assert put(channel, [3, 2, 1]).status_code == 409
        process.kill()
        process.join(10)
        assert put(channel, [3, 2, 1]).status_code == 200
    finally:
        if process.is_alive():
            process.kill()
            process.join()


def test_upgrade_defaults_existing_channels_to_teamarr(channel):
    with get_db() as conn:
        for table in ("managed_channels", "managed_team_channels"):
            for column in ("ordering_owner", "external_order_pending", "stream_order_hash"):
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.execute("UPDATE settings SET schema_version = 103")
    init_db()
    assert state(channel)["ordering_owner"] == "teamarr"
    assert stored_order(channel) == [1, 2, 3]
    assert put(channel, [3, 2, 1]).status_code == 200


def test_local_finalization_failure_retains_recoverable_intent(channel):
    with patch(
        "teamarr.services.external_ordering.persist_positions",
        side_effect=RuntimeError("DB failure"),
    ):
        assert put(channel, [3, 1]).status_code == 502
    assert state(channel)["external_order_pending"] is not None
    assert channel.http.streams == [3, 1]
    assert put(channel, [3, 1]).status_code == 200
    assert stored_order(channel) == [3, 1]


@pytest.mark.parametrize("channel", ["plugin"], indirect=True)
def test_plugin_sync_keeps_external_rank_and_removes_obsolete_members(channel):
    from teamarr.consumers.planning.applier import PlanApplier, PlanApplyOutcome
    from teamarr.database.channels import get_all_managed_channels

    assert put(channel, [3, 2, 1]).status_code == 200
    applier = PlanApplier(get_db, channel_manager=channel.manager)
    outcome = PlanApplyOutcome(plugin_id="test", plan_generation=1, dry_run=False)
    with get_db() as conn:
        existing = get_all_managed_channels(conn)[0]
        applier._sync_streams(
            conn,
            SimpleNamespace(ordered_stream_ids=[1, 2, 3], logical_key="game"),
            existing,
            outcome,
        )
        assert channel.http.streams == stored_order(channel) == [3, 2, 1]
        applier._sync_streams(
            conn, SimpleNamespace(ordered_stream_ids=[1, 3], logical_key="game"), existing, outcome
        )
    assert channel.http.streams == stored_order(channel) == [3, 1]
    assert not outcome.failures


def test_owner_is_exposed_in_channel_api(channel):
    assert put(channel, [3, 2, 1]).status_code == 200
    response = channel.client.get("/api/v1/channels/managed")
    assert response.status_code == 200, response.text
    rows = [r for r in response.json()["channels"] if r["dispatcharr_channel_id"] == 800]
    assert len(rows) == 1
    assert rows[0]["ordering_owner"] == "podium"


def test_omitted_active_membership_is_removed_even_if_not_live_yet(channel):
    channel.http.streams = [1]
    assert put(channel, [1]).status_code == 200
    assert stored_order(channel) == [1]


@pytest.mark.parametrize("channel", ["team"], indirect=True)
def test_future_membership_is_preserved_when_reusing_removed_live_id(channel):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO managed_team_channel_streams (team_id, dispatcharr_stream_id, "
            "event_id, event_provider, source_group_id, attach_at, detach_at, priority) "
            "VALUES (1, 2, 'future-game', 'espn', 1, '2999-01-01', '2999-01-02', 1)"
        )
    assert put(channel, [3, 1]).status_code == 200
    with get_db() as conn:
        row = conn.execute(
            "SELECT removed_at FROM managed_team_channel_streams WHERE event_id = 'future-game'"
        ).fetchone()
        assert row[0] is None


def test_unassign_and_undo_are_full_membership_edits(channel):
    assert put(channel, []).status_code == 200
    assert channel.http.streams == stored_order(channel) == []
    assert state(channel)["ordering_owner"] == "podium"
    assert put(channel, [3, 2, 1]).status_code == 200
    assert channel.http.streams == stored_order(channel) == [3, 2, 1]


def test_ambiguous_event_and_team_mapping_is_a_conflict(channel):
    with get_db() as conn:
        if channel.kind == "team":
            create_managed_channel(
                conn,
                None,
                "ambiguous",
                "espn",
                "ambiguous",
                "Ambiguous",
                dispatcharr_channel_id=800,
            )
        else:
            conn.execute(
                "INSERT INTO teams (id, team_name, provider, provider_team_id, "
                "primary_league, sport, channel_id) "
                "VALUES (1, 'Team', 'espn', '1', 'nfl', 'football', 'team-1')"
            )
            conn.execute(
                "INSERT INTO managed_team_channels (team_id, dispatcharr_channel_id, "
                "channel_number) VALUES (1, 800, 5001)"
            )
    response = put(channel, [3, 2, 1])
    assert response.status_code == 409
    assert channel.http.patches == []


@pytest.mark.parametrize("channel", ["event"], indirect=True)
def test_put_does_not_resurrect_historical_duplicate_memberships(channel):
    with get_db() as conn:
        local_id = conn.execute("SELECT id FROM managed_channels").fetchone()[0]
        historical = add_stream_to_channel(conn, local_id, 1, priority=50)
        conn.execute(
            "UPDATE managed_channel_streams SET removed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (historical,),
        )
    assert put(channel, [3, 2, 1]).status_code == 200
    assert stored_order(channel) == [3, 2, 1]
    assert put(channel, []).status_code == 200
    assert put(channel, [1, 3, 2]).status_code == 200
    assert stored_order(channel) == [1, 3, 2]
