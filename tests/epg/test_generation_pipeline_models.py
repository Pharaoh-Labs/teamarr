"""Typed pipeline contracts (#830, Packet 2).

``teamarr/consumers/generation_pipeline/models.py`` holds the settings
snapshot, structured progress, cancellation token and run context that the
stage runner (Packet 3) will use. These are internal types, not the plugin
ABI — but they are the shape every later packet builds on, so the guarantees
they make are worth pinning now:

* the snapshot is frozen and holds the objects read at run start;
* structured progress adapts back to the six-argument public callback exactly;
* the token raises only when asked and never touches global status;
* the context holds its dependencies by identity.

Compatibility re-exports from ``teamarr.consumers.generation`` are covered in
``test_generation_contract.py``; what is asserted here is that both paths name
the *same* object.
"""

import dataclasses

import pytest

from teamarr.consumers import FullGenerationResult
from teamarr.consumers import generation as generation_mod
from teamarr.consumers.generation_pipeline import models
from teamarr.consumers.generation_pipeline.models import (
    CallbackCancellationToken,
    GenerationCancelled,
    GenerationContext,
    GenerationResult,
    GenerationSettingsSnapshot,
    ProgressUpdate,
    legacy_progress_reporter,
)
from teamarr.database import get_db, init_db
from teamarr.database.settings.types import (
    DispatcharrSettings,
    DisplaySettings,
    EPGSettings,
)


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    return get_db


def _snapshot(**overrides) -> GenerationSettingsSnapshot:
    return GenerationSettingsSnapshot(
        epg=overrides.get("epg", EPGSettings()),
        dispatcharr=overrides.get("dispatcharr", DispatcharrSettings()),
        display=overrides.get("display", DisplaySettings()),
    )


def _context(**overrides) -> GenerationContext:
    defaults = {
        "db_factory": lambda: None,
        "dispatcharr_client": None,
        "manual": False,
        "settings": _snapshot(),
        "sports_service": object(),
        "progress": lambda update: None,
        "cancellation": CallbackCancellationToken(requested=lambda: False),
        "result": GenerationResult(),
        "stats_run": object(),
        "current_generation": 1,
    }
    defaults.update(overrides)
    return GenerationContext(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Compatibility re-exports
# ---------------------------------------------------------------------------


def test_the_facade_and_the_models_name_the_same_types():
    """Moving these must not create a second class with the same name."""
    assert generation_mod.GenerationResult is GenerationResult
    assert generation_mod.GenerationCancelled is GenerationCancelled
    assert FullGenerationResult is GenerationResult


def test_generation_cancelled_is_still_an_exception():
    assert issubclass(GenerationCancelled, Exception)
    with pytest.raises(GenerationCancelled, match="nope"):
        raise GenerationCancelled("nope")


# ---------------------------------------------------------------------------
# Settings snapshot
# ---------------------------------------------------------------------------


def test_snapshot_is_frozen():
    snapshot = _snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.epg = EPGSettings()  # type: ignore[misc]


def test_snapshot_stores_the_expected_typed_objects():
    epg = EPGSettings()
    dispatcharr = DispatcharrSettings()
    display = DisplaySettings()

    snapshot = GenerationSettingsSnapshot(
        epg=epg, dispatcharr=dispatcharr, display=display
    )

    assert snapshot.epg is epg
    assert snapshot.dispatcharr is dispatcharr
    assert snapshot.display is display


def test_snapshot_holds_only_the_three_groups():
    """Not a global settings snapshot — the other groups keep phase-local reads."""
    assert {f.name for f in dataclasses.fields(GenerationSettingsSnapshot)} == {
        "epg",
        "dispatcharr",
        "display",
    }


def test_a_later_settings_change_does_not_alter_an_existing_snapshot(isolated_db):
    """The run reads the values it started with, even if the user edits them."""
    from teamarr.database.settings import get_epg_settings, update_epg_settings

    with isolated_db() as conn:
        snapshot = _snapshot(epg=get_epg_settings(conn))

    original_days = snapshot.epg.team_schedule_days_ahead
    changed = original_days + 11

    with isolated_db() as conn:
        update_epg_settings(conn, team_schedule_days_ahead=changed)

    with isolated_db() as conn:
        assert get_epg_settings(conn).team_schedule_days_ahead == changed

    assert snapshot.epg.team_schedule_days_ahead == original_days


def test_generation_snapshots_settings_once_per_run(isolated_db, monkeypatch):
    """One read of each group, on one connection, before any stage."""
    import teamarr.database.settings as settings_mod

    reads: list[str] = []

    def _trace(name):
        original = getattr(settings_mod, name)

        def wrapper(*args, **kwargs):
            reads.append(name)
            return original(*args, **kwargs)

        monkeypatch.setattr(settings_mod, name, wrapper)

    _trace("get_epg_settings")
    _trace("get_dispatcharr_settings")
    _trace("get_display_settings")

    result = generation_mod.run_full_generation(
        db_factory=isolated_db, dispatcharr_client=None
    )

    assert result.success is True
    # The snapshot: three reads, in this order, before any stage runs.
    assert reads[:3] == [
        "get_epg_settings",
        "get_dispatcharr_settings",
        "get_display_settings",
    ]
    # EPG and display are read exactly once — the snapshot is their only read.
    assert reads.count("get_epg_settings") == 1
    assert reads.count("get_display_settings") == 1
    # Dispatcharr settings are read a second time by the cleanup step
    # (`_run_cleanup_tasks`, for `cleanup_unused_logos`). That phase-local read
    # is deliberately NOT folded into the snapshot: it has its own failure
    # policy, and hoisting it would move where a bad value is noticed.
    assert reads.count("get_dispatcharr_settings") == 2
    assert reads[-1] == "get_dispatcharr_settings"


# ---------------------------------------------------------------------------
# Structured progress
# ---------------------------------------------------------------------------


def test_progress_update_defaults():
    update = ProgressUpdate(phase="teams", percent=5, message="Processing teams...")
    assert update.current == 0
    assert update.total == 0
    assert update.item_name == ""


def test_progress_update_is_frozen():
    update = ProgressUpdate(phase="teams", percent=5, message="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        update.percent = 6  # type: ignore[misc]


def test_legacy_reporter_passes_exactly_six_positional_values():
    seen: list[tuple] = []

    reporter = legacy_progress_reporter(lambda *args: seen.append(args))
    reporter(
        ProgressUpdate(
            phase="groups",
            percent=72,
            message="Finished Group A (1/2)",
            current=1,
            total=2,
            item_name="Group A",
        )
    )

    assert seen == [("groups", 72, "Finished Group A (1/2)", 1, 2, "Group A")]


def test_legacy_reporter_fills_defaults_positionally():
    seen: list[tuple] = []

    reporter = legacy_progress_reporter(lambda *args: seen.append(args))
    reporter(ProgressUpdate(phase="init", percent=3, message="Refreshing M3U accounts..."))

    assert seen == [("init", 3, "Refreshing M3U accounts...", 0, 0, "")]


def test_a_missing_callback_is_a_no_op():
    reporter = legacy_progress_reporter(None)
    assert reporter(ProgressUpdate(phase="teams", percent=5, message="x")) is None


def test_context_report_helper_emits_a_structured_update():
    seen: list[ProgressUpdate] = []
    context = _context(progress=seen.append)

    context.report("saving", 95, "Saving XMLTV...")
    context.report("groups", 72, "Finished Group A", 1, 2, "Group A")

    assert seen == [
        ProgressUpdate(phase="saving", percent=95, message="Saving XMLTV..."),
        ProgressUpdate(
            phase="groups",
            percent=72,
            message="Finished Group A",
            current=1,
            total=2,
            item_name="Group A",
        ),
    ]


# ---------------------------------------------------------------------------
# Cancellation token
# ---------------------------------------------------------------------------


def test_token_raises_only_when_requested():
    requested = {"value": False}
    token = CallbackCancellationToken(requested=lambda: requested["value"])

    assert token.is_requested() is False
    assert token.checkpoint() is None

    requested["value"] = True

    assert token.is_requested() is True
    with pytest.raises(GenerationCancelled, match="Cancelled by user"):
        token.checkpoint()


def test_token_is_re_evaluated_on_every_call():
    """The predicate is consulted per checkpoint, not cached at construction."""
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return False

    token = CallbackCancellationToken(requested=counting)
    token.checkpoint()
    token.checkpoint()
    token.is_requested()

    assert calls["n"] == 3


def test_token_does_not_touch_global_status():
    """Terminal status stays the facade's outer handler's job."""
    from teamarr.consumers import generation_status as status_mod

    with status_mod._status_lock:
        status_mod._status.reset()
    try:
        assert status_mod.start_generation() is True
        token = CallbackCancellationToken(requested=lambda: True)

        with pytest.raises(GenerationCancelled):
            token.checkpoint()

        status = status_mod.get_status()
        assert status["in_progress"] is True
        assert status["status"] == "starting"
        assert status["cancellation_requested"] is False
    finally:
        with status_mod._status_lock:
            status_mod._status.reset()


def test_context_checkpoint_delegates_to_its_token():
    context = _context(cancellation=CallbackCancellationToken(requested=lambda: True))
    with pytest.raises(GenerationCancelled):
        context.checkpoint()


# ---------------------------------------------------------------------------
# Generation context
# ---------------------------------------------------------------------------


def test_context_retains_its_dependencies_by_identity():
    db_factory = lambda: None  # noqa: E731
    client = object()
    snapshot = _snapshot()
    service = object()
    reporter = lambda update: None  # noqa: E731
    token = CallbackCancellationToken(requested=lambda: False)
    result = GenerationResult()
    stats_run = object()

    context = GenerationContext(
        db_factory=db_factory,
        dispatcharr_client=client,
        manual=True,
        settings=snapshot,
        sports_service=service,  # type: ignore[arg-type]
        progress=reporter,
        cancellation=token,
        result=result,
        stats_run=stats_run,  # type: ignore[arg-type]
        current_generation=7,
    )

    assert context.db_factory is db_factory
    assert context.dispatcharr_client is client
    assert context.manual is True
    assert context.settings is snapshot
    assert context.sports_service is service
    assert context.progress is reporter
    assert context.cancellation is token
    assert context.result is result
    assert context.stats_run is stats_run
    assert context.current_generation == 7


def test_produced_fields_default_to_empty():
    """Everything a stage writes starts empty, not None-or-missing."""
    context = _context()

    assert context.team_result is None
    assert context.group_result is None
    assert context.external_occupied == set()
    assert context.lifecycle_service is None
    assert context.media_jobs == []
    assert context.channels_deleted_count == 0
    assert context.team_channel_manager is None
    assert context.team_matched_streams == []
    assert context.team_completed_groups == set()
    assert context.relayout is False


def test_mutable_defaults_are_not_shared_between_contexts():
    first = _context()
    second = _context()

    first.external_occupied.add(101)
    first.team_matched_streams.append({"id": 1})
    first.team_completed_groups.add(5)
    first.media_jobs.append(("emby", object()))

    assert second.external_occupied == set()
    assert second.team_matched_streams == []
    assert second.team_completed_groups == set()
    assert second.media_jobs == []


def test_context_is_mutable_so_stages_can_publish_results():
    """Unlike the snapshot, the context is written to as the run proceeds."""
    context = _context()

    context.relayout = True
    context.channels_deleted_count = 3

    assert context.relayout is True
    assert context.channels_deleted_count == 3


def test_package_exports_match_the_models_module():
    from teamarr.consumers import generation_pipeline
    from teamarr.consumers.generation_pipeline import runner

    for name in generation_pipeline.__all__:
        source = runner if name in runner.__all__ else models
        assert getattr(generation_pipeline, name) is getattr(source, name), name
