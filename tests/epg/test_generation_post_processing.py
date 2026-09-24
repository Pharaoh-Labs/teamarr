"""Unit contracts for Packet 6A lifecycle and reconciliation phases."""

from contextlib import nullcontext
from types import SimpleNamespace

from teamarr.consumers.generation_pipeline.phases import post_processing


class _Context(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.progress_events: list[tuple] = []

    def report(self, *args):
        self.progress_events.append(args)


def _context(**overrides):
    defaults = {
        "db_factory": lambda: nullcontext(object()),
        "dispatcharr_client": object(),
        "sports_service": object(),
        "settings": SimpleNamespace(dispatcharr=SimpleNamespace(epg_id=12)),
        "result": SimpleNamespace(
            epg_refresh={}, epg_association={}, deletions={}, reconciliation={}
        ),
        "team_channel_manager": SimpleNamespace(associate_epg=lambda _epg_id: {"associated": 1}),
        "channels_deleted_count": 0,
    }
    defaults.update(overrides)
    return _Context(**defaults)


def test_lifecycle_prepare_uses_the_run_scoped_service_and_preserves_call_order():
    context = _context()
    calls = []

    class Lifecycle:
        def compute_external_occupied(self):
            calls.append("occupied")

        def sync_stream_profiles(self):
            calls.append("profiles")

    def factory(db_factory, service, *, dispatcharr_client):
        calls.append((db_factory, service, dispatcharr_client))
        return Lifecycle()

    post_processing.stage_lifecycle_prepare(context, lifecycle_factory=factory)

    assert calls == [
        (context.db_factory, context.sports_service, context.dispatcharr_client),
        "occupied",
        "profiles",
    ]


def test_dispatcharr_epg_preserves_timeout_cancellation_and_association_order(monkeypatch):
    context = _context()
    calls = []
    context.lifecycle_service = SimpleNamespace(
        associate_epg_with_channels=lambda epg_id: calls.append(("lifecycle", epg_id))
        or {"core": 1}
    )
    context.team_channel_manager = SimpleNamespace(
        associate_epg=lambda epg_id: calls.append(("team", epg_id)) or {"team": 1}
    )

    class Manager:
        def __init__(self, client):
            calls.append(("manager", client))

        def wait_for_refresh(self, epg_id, *, timeout, cancellation_check):
            calls.append(("refresh", epg_id, timeout, cancellation_check()))
            return SimpleNamespace(success=True, message="done", duration=2.5)

    monkeypatch.setattr(post_processing, "EPGManager", Manager)

    post_processing.stage_dispatcharr_epg(context, cancellation_requested=lambda: False)

    assert calls == [
        ("manager", context.dispatcharr_client),
        ("refresh", 12, 300, False),
        ("lifecycle", 12),
        ("team", 12),
    ]
    assert context.result.epg_refresh == {"success": True, "message": "done", "duration": 2.5}
    assert context.result.epg_association == {"core": 1, "managed_team_channels": {"team": 1}}


def test_deletions_remain_nonfatal_and_record_the_error():
    context = _context(
        lifecycle_service=SimpleNamespace(
            process_scheduled_deletions=lambda: (_ for _ in ()).throw(RuntimeError("unavailable"))
        )
    )

    post_processing.stage_deletions(context)

    assert context.progress_events == [("lifecycle", 98, "Processing scheduled deletions...")]
    assert context.result.deletions == {"error": "unavailable"}


def test_reconciliation_skips_construction_when_disabled():
    context = _context()

    post_processing.stage_reconciliation(
        context,
        reconciler_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("constructed")),
        reconciliation_settings=lambda _conn: {"reconcile_on_epg_generation": False},
    )

    assert context.progress_events == [("reconciliation", 99, "Running reconciliation...")]
    assert context.result.reconciliation == {}


def test_stream_audit_keeps_stale_detection_and_audit_failures_isolated():
    context = _context()
    calls = []

    def stale(_db_factory):
        calls.append("stale")
        raise RuntimeError("stale failed")

    def audit(db_factory, dispatcharr_client):
        calls.append((db_factory, dispatcharr_client))
        raise RuntimeError("audit failed")

    post_processing.stage_stream_audit(context, stale_group_detector=stale, stream_audit=audit)

    assert calls == ["stale", (context.db_factory, context.dispatcharr_client)]
