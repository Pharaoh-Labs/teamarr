"""New channels reach media servers with their programmes (#855).

A generation run refreshes Dispatcharr's EPG source, links each managed
channel to its EPG entry, and later refreshes Channels DVR / Emby / Jellyfin.
Two things made a brand-new channel arrive with an empty guide:

- linking called ``set-epg`` on EVERY channel every run, and Dispatcharr queues
  a full XMLTV parse per call whether or not the mapping changed, so the one
  parse the new channel needed sat behind hundreds of redundant ones;
- nothing waited for that parse before the media-server refresh.

Now only changed mappings reach Dispatcharr as work (one ``batch-set-epg``
request, or ``set-epg`` for the changed channels on an older build), and the
run waits, bounded, until the newly linked channels have programmes.
"""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from teamarr.consumers.generation_pipeline.phases import post_processing
from teamarr.dispatcharr.managers import epg as epg_module
from teamarr.dispatcharr.managers.channels import ChannelManager
from teamarr.dispatcharr.managers.epg import EPGManager
from teamarr.dispatcharr.types import DispatcharrChannel, EpgAssociationOutcome


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class _Client:
    """Just enough DispatcharrClient for the channel manager."""

    _counter = 0

    def __init__(self, channels, batch=None, set_epg_status=200):
        _Client._counter += 1
        self._base_url = f"http://fake-{_Client._counter}:9191"  # own channel cache
        self.channels = channels
        self.batch = batch
        self.set_epg_status = set_epg_status
        self.posts: list[tuple[str, dict]] = []

    def paginated_get(self, path, error_context=None):
        return self.channels

    def paginated_get_or_none(self, path, error_context=None):
        return self.channels

    def post(self, path, payload):
        self.posts.append((path, payload))
        if path.endswith("batch-set-epg/"):
            return self.batch
        return _Response(self.set_epg_status, {})

    def parse_api_error(self, response):
        return f"HTTP {getattr(response, 'status_code', None)}"


# Channel 1 is already linked to EPG 11; 2 is linked to the wrong one; 3 is new.
CHANNELS = [
    {"id": 1, "uuid": "a", "epg_data_id": 11},
    {"id": 2, "uuid": "b", "epg_data_id": 99},
    {"id": 3, "uuid": "c", "epg_data_id": None},
]
WANTED = [(1, 11), (2, 22), (3, 33)]


def _batch_ok(updated):
    return _Response(200, {"success": True, "channels_updated": updated, "programs_refreshed": 1})


class TestChannelEpgField:
    def test_channel_carries_its_epg_link(self):
        assert DispatcharrChannel.from_api({"id": 1, "epg_data_id": 11}).epg_data_id == 11
        assert DispatcharrChannel.from_api({"id": 1}).epg_data_id is None


class TestBatchAssociation:
    def test_one_request_carries_every_mapping(self):
        client = _Client(CHANNELS, batch=_batch_ok(2))
        outcome = ChannelManager(client).apply_epg_associations(WANTED)

        assert [path for path, _ in client.posts] == ["/api/channels/channels/batch-set-epg/"]
        assert client.posts[0][1] == {
            "associations": [
                {"channel_id": 1, "epg_data_id": 11},
                {"channel_id": 2, "epg_data_id": 22},
                {"channel_id": 3, "epg_data_id": 33},
            ]
        }
        assert outcome.batched and outcome.applied == 3 and not outcome.failed_channel_ids

    def test_only_new_or_different_mappings_count_as_changed(self):
        outcome = ChannelManager(_Client(CHANNELS, batch=_batch_ok(2))).apply_epg_associations(
            WANTED
        )
        assert outcome.changed_channel_ids == {2, 3}

    def test_dispatcharr_saying_nothing_changed_is_authoritative(self):
        """A stale channel cache must not make the run wait for nothing."""
        outcome = ChannelManager(_Client(CHANNELS, batch=_batch_ok(0))).apply_epg_associations(
            WANTED
        )
        assert outcome.changed_channel_ids == frozenset()

    def test_no_associations_makes_no_request(self):
        client = _Client(CHANNELS, batch=_batch_ok(0))
        assert ChannelManager(client).apply_epg_associations([]) == EpgAssociationOutcome()
        assert client.posts == []


class TestOlderDispatcharrFallback:
    @pytest.mark.parametrize("status", [404, 405])
    def test_only_changed_channels_get_a_set_epg_call(self, status):
        """The per-channel endpoint queues a parse per call, so the unchanged
        channel must not be touched — that redundancy was half the bug."""
        client = _Client(CHANNELS, batch=_Response(status))
        outcome = ChannelManager(client).apply_epg_associations(WANTED)

        assert [path for path, _ in client.posts[1:]] == [
            "/api/channels/channels/2/set-epg/",
            "/api/channels/channels/3/set-epg/",
        ]
        assert not outcome.batched
        assert outcome.applied == 3 and outcome.changed_channel_ids == {2, 3}

    def test_unsupported_is_remembered_and_not_probed_again(self):
        client = _Client(CHANNELS, batch=_Response(404))
        manager = ChannelManager(client)
        manager.apply_epg_associations(WANTED)
        client.posts.clear()

        manager.apply_epg_associations(WANTED)

        assert not any(path.endswith("batch-set-epg/") for path, _ in client.posts)

    def test_a_failed_batch_falls_back_too(self):
        client = _Client(CHANNELS, batch=_Response(500))
        outcome = ChannelManager(client).apply_epg_associations(WANTED)
        assert [path for path, _ in client.posts[1:]] == [
            "/api/channels/channels/2/set-epg/",
            "/api/channels/channels/3/set-epg/",
        ]
        assert outcome.applied == 3

    def test_rejected_channels_are_reported_and_not_waited_on(self):
        client = _Client(CHANNELS, batch=_Response(404), set_epg_status=500)
        outcome = ChannelManager(client).apply_epg_associations(WANTED)
        assert outcome.failed_channel_ids == (2, 3)
        assert outcome.applied == 1
        assert outcome.changed_channel_ids == frozenset()


class _EpgClient:
    """Programme-search endpoint whose answer per tvg-id changes over time."""

    def __init__(self, ready_after=None, search_status=200):
        self.ready_after = ready_after or {}  # tvg_id -> poll number it turns ready on
        self.search_status = search_status
        self.asked: dict[str, int] = {}
        self.urls: list[str] = []

    def get(self, url):
        self.urls.append(url)
        if "tvg_id=" not in url:  # the supports_program_search probe
            return _Response(self.search_status, {"count": 0, "results": []})
        tvg_id = url.split("tvg_id=")[1].split("&")[0]
        self.asked[tvg_id] = self.asked.get(tvg_id, 0) + 1
        ready = self.asked[tvg_id] >= self.ready_after.get(tvg_id, 1)
        return _Response(200, {"count": 3 if ready else 0, "results": []})


@pytest.fixture
def clock(monkeypatch):
    """A clock that only moves when the code sleeps."""
    state = SimpleNamespace(now=0.0, sleeps=[])

    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds

    monkeypatch.setattr(epg_module.time, "monotonic", lambda: state.now)
    monkeypatch.setattr(epg_module.time, "sleep", sleep)
    return state


class TestProgrammeWait:
    def test_returns_at_once_when_programmes_are_already_there(self, clock):
        result = EPGManager(_EpgClient()).wait_for_programmes(["teamarr-event-1"])
        assert result == {
            "waited_for": 1,
            "ready": 1,
            "missing": [],
            "seconds": 0.0,
            "timed_out": False,
        }
        assert clock.sleeps == []

    def test_polls_until_the_parse_lands(self, clock):
        client = _EpgClient(ready_after={"teamarr-event-2": 3})
        result = EPGManager(client).wait_for_programmes(
            ["teamarr-event-1", "teamarr-event-2"], poll_interval=3.0
        )
        assert result["ready"] == 2 and not result["timed_out"]
        assert clock.sleeps == [3.0, 3.0]
        # The channel that was ready on the first poll is not asked again.
        assert client.asked == {"teamarr-event-1": 1, "teamarr-event-2": 3}

    def test_asks_for_one_row_not_the_whole_guide(self, clock):
        client = _EpgClient()
        EPGManager(client).wait_for_programmes(["teamarr-event-1"])
        assert "page_size=1" in client.urls[-1]

    def test_gives_up_after_the_timeout_and_names_what_is_missing(self, clock):
        client = _EpgClient(ready_after={"teamarr-event-9": 10_000})
        result = EPGManager(client).wait_for_programmes(
            ["teamarr-event-1", "teamarr-event-9"], timeout=10.0, poll_interval=3.0
        )
        assert result["timed_out"] is True
        assert result["ready"] == 1 and result["missing"] == ["teamarr-event-9"]
        assert sum(clock.sleeps) == pytest.approx(10.0)

    def test_cancellation_stops_the_wait(self, clock):
        client = _EpgClient(ready_after={"teamarr-event-9": 10_000})
        result = EPGManager(client).wait_for_programmes(
            ["teamarr-event-9"], cancellation_check=lambda: True
        )
        assert result["ready"] == 0 and result["timed_out"] is False
        assert clock.sleeps == []

    def test_a_build_without_programme_search_is_not_waited_on(self, clock):
        result = EPGManager(_EpgClient(search_status=404)).wait_for_programmes(["x"])
        assert result == {"waited_for": 1, "supported": False}
        assert clock.sleeps == []

    def test_nothing_to_wait_for(self, clock):
        client = _EpgClient()
        assert EPGManager(client).wait_for_programmes([])["waited_for"] == 0
        assert client.urls == []


class _FakeChannelManager:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list = []

    def build_epg_lookup(self, epg_source_id):
        return {
            "teamarr-event-1": {"id": 11},
            "teamarr-event-2": {"id": 22},
            "teamarr-event-4": {},  # EPG row without an id
        }

    def apply_epg_associations(self, associations):
        self.calls.append(associations)
        return self.outcome


class TestLifecycleAssociation:
    def _service(self, monkeypatch, channel_manager):
        from unittest.mock import MagicMock

        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        channels = [
            SimpleNamespace(dispatcharr_channel_id=1, tvg_id="teamarr-event-1", channel_name="A"),
            SimpleNamespace(dispatcharr_channel_id=2, tvg_id="teamarr-event-2", channel_name="B"),
            SimpleNamespace(dispatcharr_channel_id=3, tvg_id="teamarr-event-3", channel_name="C"),
            SimpleNamespace(dispatcharr_channel_id=4, tvg_id="teamarr-event-4", channel_name="D"),
            SimpleNamespace(dispatcharr_channel_id=None, tvg_id="teamarr-event-5", channel_name=""),
        ]
        monkeypatch.setattr(
            "teamarr.database.channels.get_all_managed_channels",
            lambda conn, include_deleted=False: channels,
        )
        return ChannelLifecycleService(
            db_factory=lambda: nullcontext(object()),
            sports_service=MagicMock(),
            channel_manager=channel_manager,
            logo_manager=MagicMock(),
            epg_manager=MagicMock(),
        )

    def test_reports_the_newly_linked_guide_channels(self, monkeypatch):
        manager = _FakeChannelManager(
            EpgAssociationOutcome(applied=2, changed_channel_ids=frozenset({2}), batched=True)
        )
        result = self._service(monkeypatch, manager).associate_epg_with_channels(12)

        assert manager.calls == [[(1, 11), (2, 22)]]
        assert result == {
            "associated": 2,
            "not_found": 2,  # no EPG row for event 3, no id on event 4's row
            "errors": 0,
            "updated": 1,
            "new_tvg_ids": ["teamarr-event-2"],
        }

    def test_a_failed_association_does_not_raise(self, monkeypatch):
        manager = _FakeChannelManager(None)
        manager.apply_epg_associations = lambda associations: (_ for _ in ()).throw(
            RuntimeError("dispatcharr down")
        )
        result = self._service(monkeypatch, manager).associate_epg_with_channels(12)
        assert result["errors"] == 2 and "new_tvg_ids" not in result


class TestPipelineWaitsBeforeMediaRefresh:
    def _run(self, monkeypatch, core, team, waiter=None):
        waits: list = []

        class Manager:
            def __init__(self, client):
                pass

            def wait_for_refresh(self, epg_id, *, timeout, cancellation_check):
                return SimpleNamespace(success=True, message="done", duration=1.0)

            def wait_for_programmes(self, tvg_ids, *, timeout, cancellation_check):
                waits.append((tvg_ids, timeout))
                if waiter:
                    return waiter()
                return {"waited_for": len(tvg_ids), "ready": len(tvg_ids), "timed_out": False}

        monkeypatch.setattr(post_processing, "EPGManager", Manager)
        events: list[tuple] = []
        context = SimpleNamespace(
            dispatcharr_client=object(),
            settings=SimpleNamespace(dispatcharr=SimpleNamespace(epg_id=12)),
            result=SimpleNamespace(epg_refresh={}, epg_association={}),
            lifecycle_service=SimpleNamespace(associate_epg_with_channels=lambda epg_id: core),
            team_channel_manager=SimpleNamespace(associate_epg=lambda epg_id: team),
            report=lambda *args: events.append(args),
        )
        post_processing.stage_dispatcharr_epg(context, cancellation_requested=lambda: False)
        return context, waits, events

    def test_waits_for_event_and_team_channels_together(self, monkeypatch):
        context, waits, events = self._run(
            monkeypatch,
            core={"associated": 3, "new_tvg_ids": ["teamarr-event-2"]},
            team={"associated": 1, "new_tvg_ids": ["team-blue"]},
        )
        assert waits == [
            (["teamarr-event-2", "team-blue"], post_processing.NEW_CHANNEL_PROGRAMME_WAIT_SECONDS)
        ]
        assert events[-1] == ("dispatcharr", 97, "Waiting for guide data on 2 new channel(s)...")
        # The id lists are working data, not run metrics.
        assert context.result.epg_association == {
            "associated": 3,
            "managed_team_channels": {"associated": 1},
            "programme_wait": {"waited_for": 2, "ready": 2, "timed_out": False},
        }

    def test_a_run_with_nothing_new_does_not_wait(self, monkeypatch):
        context, waits, _ = self._run(
            monkeypatch, core={"associated": 3, "new_tvg_ids": []}, team={"associated": 1}
        )
        assert waits == []
        assert "programme_wait" not in context.result.epg_association

    def test_a_failing_wait_does_not_fail_the_run(self, monkeypatch):
        def boom():
            raise RuntimeError("search endpoint fell over")

        context, waits, _ = self._run(
            monkeypatch, core={"new_tvg_ids": ["teamarr-event-2"]}, team={}, waiter=boom
        )
        assert len(waits) == 1
        assert "programme_wait" not in context.result.epg_association
