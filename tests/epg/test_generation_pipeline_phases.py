"""Unit contracts for the Packet 4 preparation and processing phases."""

from types import SimpleNamespace

from teamarr.consumers.generation_pipeline.phases import preparation, processing


class _Context(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.progress_events: list[tuple] = []

    def report(self, *args):
        self.progress_events.append(args)


def _context(**overrides):
    defaults = {
        "db_factory": object(),
        "dispatcharr_client": None,
        "sports_service": object(),
        "result": SimpleNamespace(
            teams_processed=0,
            teams_programmes=0,
            groups_processed=0,
            groups_programmes=0,
            programmes_total=0,
            channel_conflicts={},
            m3u_refresh={},
        ),
        "current_generation": 42,
        "stats_run": SimpleNamespace(id=17),
        "external_occupied": set(),
        "team_completed_groups": set(),
        "team_matched_streams": [],
    }
    defaults.update(overrides)
    return _Context(**defaults)


def test_m3u_phase_reports_then_uses_the_injected_compatibility_helper():
    context = _context(dispatcharr_client=object())
    calls = []

    def refresh(db_factory, client):
        calls.append((db_factory, client))
        return {"refreshed": 1}

    preparation.stage_m3u_refresh(context, refresh_m3u_accounts=refresh)

    assert context.progress_events == [("init", 3, "Refreshing M3U accounts...")]
    assert calls == [(context.db_factory, context.dispatcharr_client)]
    assert context.result.m3u_refresh == {"refreshed": 1}


def test_m3u_phase_skips_the_helper_without_a_dispatcharr_client():
    context = _context()

    preparation.stage_m3u_refresh(
        context,
        refresh_m3u_accounts=lambda *_: (_ for _ in ()).throw(AssertionError("called")),
    )

    assert context.result.m3u_refresh == {}


def test_prepare_team_channels_builds_the_manager_and_announces_group_processing(monkeypatch):
    context = _context()
    context.result.teams_processed = 3
    created = []

    def manager(*args):
        created.append(args)
        return "manager"

    monkeypatch.setattr(preparation, "TeamChannelManager", manager)

    preparation.stage_prepare_team_channels(context)

    assert created == [(context.db_factory, None, None, None)]
    assert context.team_channel_manager == "manager"
    assert context.progress_events == [
        (
            "groups",
            50,
            "Teams complete (3 processed), loading event groups...",
            0,
            1,
            "Loading event groups...",
        )
    ]


def test_team_phase_forwards_the_run_scoped_service_and_updates_totals():
    context = _context()
    calls = []

    def process(**kwargs):
        calls.append(kwargs)
        kwargs["progress_callback"](2, 4, "Lions")
        return SimpleNamespace(teams_processed=2, total_programmes=11)

    processing.stage_teams(context, team_processor=process)

    assert calls[0]["db_factory"] is context.db_factory
    assert calls[0]["service"] is context.sports_service
    assert context.result.teams_processed == 2
    assert context.result.teams_programmes == 11
    assert context.progress_events[0] == ("teams", 5, "Processing teams...")
    assert context.progress_events[1][0:2] == ("teams", 27)
    assert context.progress_events[1][3:] == (2, 4, "Lions")


def test_team_phase_uses_its_start_percentage_when_progress_has_no_total():
    context = _context()

    def process(**kwargs):
        kwargs["progress_callback"](0, 0, "Lions")
        return SimpleNamespace(teams_processed=0, total_programmes=0)

    processing.stage_teams(context, team_processor=process)

    assert context.progress_events[1][0:2] == ("teams", 5)
    assert context.progress_events[1][3:] == (0, 0, "Lions")


def test_group_phase_forwards_run_identity_collects_matches_and_updates_totals():
    context = _context()
    context.result.teams_programmes = 11
    calls = []

    def occupied(db_factory, channel_manager):
        assert db_factory is context.db_factory
        assert channel_manager is None
        return {150}

    def validate(db_factory, occupied_channels):
        assert db_factory is context.db_factory
        assert occupied_channels == {150}
        return {"group_warnings": ["collision"]}

    def process(**kwargs):
        calls.append(kwargs)
        kwargs["progress_callback"](1, 2, "Tigers")
        kwargs["matched_stream_callback"](7, [{"stream_id": 99}])
        return SimpleNamespace(groups_processed=1, total_programmes=13)

    processing.stage_groups(
        context,
        group_processor=process,
        external_occupied_provider=occupied,
        validate_channel_ranges=validate,
    )

    assert calls[0]["generation"] == 42
    assert calls[0]["run_id"] == 17
    assert calls[0]["service"] is context.sports_service
    assert calls[0]["aggregate_xmltv"] is False
    assert context.external_occupied == {150}
    assert context.result.channel_conflicts == {"group_warnings": ["collision"]}
    assert context.team_completed_groups == {7}
    assert context.team_matched_streams == [{"stream_id": 99, "source_group_id": 7}]
    assert context.result.groups_processed == 1
    assert context.result.groups_programmes == 13
    assert context.result.programmes_total == 24
    assert context.progress_events[0][0:2] == ("groups", 72)
    assert context.progress_events[0][3:] == (1, 2, "Tigers")


def test_group_phase_preserves_terminal_messages_and_uses_start_percentage_without_total():
    context = _context()

    def process(**kwargs):
        progress = kwargs["progress_callback"]
        progress(0, 0, "No groups")
        progress(1, 2, "✓ Tigers")
        progress(2, 2, "✗ Lions")
        return SimpleNamespace(groups_processed=0, total_programmes=0)

    processing.stage_groups(
        context,
        group_processor=process,
        external_occupied_provider=lambda *_: set(),
        validate_channel_ranges=lambda *_: (_ for _ in ()).throw(AssertionError("called")),
    )

    assert context.progress_events[0][0:2] == ("groups", 50)
    assert context.progress_events[0][3:] == (0, 0, "No groups")
    assert context.progress_events[1] == ("groups", 72, "✓ Tigers", 1, 2, "✓ Tigers")
    assert context.progress_events[2] == ("groups", 95, "✗ Lions", 2, 2, "✗ Lions")
