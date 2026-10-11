"""Packet 8C: plan diffing and host application (create/adopt/update/retire)."""

from datetime import UTC, datetime, timedelta

from teamarr.consumers.planning import (
    ChannelPlan,
    PlanApplier,
    PlanDiagnostic,
    PlanResult,
    ProgrammePlan,
    compute_plan_diff,
)
from teamarr.database.channels import (
    add_stream_to_channel,
    create_managed_channel,
    get_channel_streams,
    get_managed_channel,
    get_plugin_channel,
    get_plugin_channels,
)
from teamarr.database.connection import get_connection
from teamarr.dispatcharr.types import OperationResult

PLUGIN = "test.provider"
START = datetime(2026, 10, 6, 18, tzinfo=UTC)
STOP = START + timedelta(hours=3)


class FakeChannelManager:
    def __init__(self):
        self.created: list[dict] = []
        self.updates: list[tuple[int, dict]] = []
        self.deletes: list[int] = []
        self.fail_create = False
        self.fail_update = False
        self.fail_delete = False

    def create_channel(self, **kwargs):
        self.created.append(kwargs)
        if self.fail_create:
            return OperationResult(success=False, error="create boom")
        return OperationResult(
            success=True, channel={"id": 9000 + len(self.created), "uuid": "dp-uuid"}
        )

    def update_channel(self, channel_id, data):
        self.updates.append((channel_id, data))
        if self.fail_update:
            return OperationResult(success=False, error="update boom")
        return OperationResult(success=True)

    def delete_channel(self, channel_id):
        self.deletes.append(channel_id)
        if self.fail_delete:
            return OperationResult(success=False, error="delete boom")
        return OperationResult(success=True)


def _channel(**overrides):
    fields = dict(
        plugin_id=PLUGIN,
        logical_key="event:p:lg:1",
        adoption_key="slot:p:lg:1",
        display_name="Feature Event",
        xmltv_channel_id="plan:p:lg:1",
        event_key="p:lg:1",
        variant_key="main",
        ordered_stream_ids=[8, 12],
        create_at=START,
        delete_at=STOP,
        programme_start_at=START,
        programme_end_at=STOP,
    )
    fields.update(overrides)
    return ChannelPlan(**fields)


def _programme(**overrides):
    fields = dict(
        plugin_id=PLUGIN,
        channel_logical_key="event:p:lg:1",
        programme_key="p:lg:1:main",
        start=START,
        stop=STOP,
        title="Feature Event",
    )
    fields.update(overrides)
    return ProgrammePlan(**fields)


def _plan(**overrides):
    fields = dict(plugin_id=PLUGIN, status="complete")
    fields.update(overrides)
    return PlanResult(**fields)


def _seed_plugin_channel(
    conn,
    *,
    logical_key,
    adoption_key,
    name="Feature Event",
    tvg=None,
    streams=(8, 12),
    delete_at=None,
    number=501,
    dispatcharr_id=777,
):
    channel_id = create_managed_channel(
        conn,
        None,
        f"evt-{logical_key}",
        "plugin",
        tvg or f"plan:{logical_key}",
        name,
        plugin_id=PLUGIN,
        plugin_logical_key=logical_key,
        plugin_adoption_key=adoption_key,
        channel_number=number,
        dispatcharr_channel_id=dispatcharr_id,
        scheduled_delete_at=delete_at.isoformat() if delete_at else None,
    )
    for priority, stream_id in enumerate(streams):
        add_stream_to_channel(conn, channel_id, stream_id, priority=priority)
    conn.commit()
    return channel_id


def _applier(db_factory, manager=None):
    return PlanApplier(db_factory, channel_manager=manager)


# -- diff ---------------------------------------------------------------------


def test_diff_classifies_create_update_stream_order_and_retire(db_path):
    with get_connection(db_path) as conn:
        _seed_plugin_channel(
            conn,
            logical_key="event:p:lg:1",
            adoption_key="slot:p:lg:1",
            tvg="plan:p:lg:1",
            delete_at=STOP,
        )
        # Same logical key, only streams change -> stream_order.
        _seed_plugin_channel(
            conn,
            logical_key="event:p:lg:2",
            adoption_key="slot:p:lg:2",
            tvg="plan:event:p:lg:2",
            streams=(8,),
            number=502,
            dispatcharr_id=778,
            delete_at=STOP,
        )
        # Different logical key, same adoption key -> adopt.
        _seed_plugin_channel(
            conn,
            logical_key="event:p:provisional",
            adoption_key="slot:p:lg:9",
            tvg="plan:event:p:lg:9",
            streams=(8, 12),
            number=503,
            dispatcharr_id=779,
        )
        # Unmatched -> retire.
        _seed_plugin_channel(
            conn,
            logical_key="event:p:lg:gone",
            adoption_key="slot:p:lg:gone",
            tvg="plan:event:p:lg:gone",
            streams=(8,),
            number=504,
            dispatcharr_id=780,
        )

        diff = compute_plan_diff(
            conn,
            _plan(
                channels=[
                    _channel(),  # identical -> no intention
                    _channel(
                        logical_key="event:p:lg:2",
                        adoption_key="slot:p:lg:2",
                        xmltv_channel_id="plan:event:p:lg:2",
                        ordered_stream_ids=[8, 12],
                    ),
                    _channel(
                        logical_key="event:p:lg:9",
                        adoption_key="slot:p:lg:9",
                        xmltv_channel_id="plan:event:p:lg:9",
                    ),
                    _channel(
                        logical_key="event:p:lg:3",
                        adoption_key="slot:p:lg:3",
                        xmltv_channel_id="plan:event:p:lg:3",
                    ),
                ]
            ),
            plugin_id=PLUGIN,
        )

    assert [(i.kind, i.channel.logical_key if i.channel else None) for i in diff.intentions] == [
        ("stream_order", "event:p:lg:2"),
        ("adopt", "event:p:lg:9"),
        ("create", "event:p:lg:3"),
        ("retire", None),
    ]
    retire = diff.intentions[-1]
    assert retire.existing is not None
    assert retire.existing.plugin_logical_key == "event:p:lg:gone"
    assert diff.actionable


def test_diff_reports_delete_at_drift_only_when_times_differ(db_path):
    with get_connection(db_path) as conn:
        same = _seed_plugin_channel(
            conn,
            logical_key="event:p:lg:1",
            adoption_key="slot:p:lg:1",
            tvg="plan:p:lg:1",
            delete_at=STOP,
        )
        diff = compute_plan_diff(conn, _plan(channels=[_channel()]), plugin_id=PLUGIN)
        assert diff.intentions == ()
        assert get_plugin_channel(conn, PLUGIN, "event:p:lg:1") is not None
        assert same


def test_diff_blocks_ambiguous_adoption_without_any_intention(db_path):
    with get_connection(db_path) as conn:
        _seed_plugin_channel(
            conn,
            logical_key="event:p:lg:a",
            adoption_key="slot:p:lg:1",
            tvg="plan:a",
            number=501,
            dispatcharr_id=777,
        )
        _seed_plugin_channel(
            conn,
            logical_key="event:p:lg:b",
            adoption_key="slot:p:lg:1",
            tvg="plan:b",
            number=502,
            dispatcharr_id=778,
        )
        diff = compute_plan_diff(
            conn,
            _plan(
                channels=[
                    _channel(logical_key="event:p:lg:new", xmltv_channel_id="plan:new")
                ]
            ),
            plugin_id=PLUGIN,
        )
        assert not diff.actionable
        assert [d.code for d in diff.blocked] == ["plan.ambiguous_adoption"]
        # Neither candidate was matched, adopted, or retired.
        assert diff.intentions == ()


def test_diff_rejects_plan_belonging_to_another_plugin(db_path):
    with get_connection(db_path) as conn:
        diff = compute_plan_diff(
            conn, _plan(), plugin_id="other.plugin"
        )
        assert not diff.actionable
        assert diff.blocked[0].code == "plan.wrong_plugin"


# -- applier ------------------------------------------------------------------


def test_dry_run_reports_the_diff_without_writing(db_path, db_factory):
    manager = FakeChannelManager()
    with get_connection(db_path) as conn:
        _seed_plugin_channel(
            conn, logical_key="event:p:lg:gone", adoption_key="slot:p:lg:gone"
        )

    outcome = _applier(db_factory, manager).apply(
        _plan(channels=[_channel(logical_key="event:p:lg:new", xmltv_channel_id="plan:new")]),
        plugin_id=PLUGIN,
        plan_generation=3,
        dry_run=True,
    )

    assert outcome.ok and outcome.dry_run
    assert outcome.created == ["event:p:lg:new"]
    assert outcome.retired == ["event:p:lg:gone"]
    assert manager.created == [] and manager.updates == [] and manager.deletes == []
    with get_connection(db_path) as conn:
        assert get_plugin_channels(conn, PLUGIN)


def test_runtime_dry_run_flag_forces_a_no_write_pass(db_path, db_factory, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    manager = FakeChannelManager()
    outcome = _applier(db_factory, manager).apply(
        _plan(channels=[_channel()]), plugin_id=PLUGIN, plan_generation=1
    )
    assert outcome.ok and outcome.dry_run is False  # requested pass was not dry-run
    assert manager.created == []
    assert outcome.to_metrics()["created"] == 1  # would have created


def test_apply_creates_channels_with_ownership_streams_and_history(db_path, db_factory):
    manager = FakeChannelManager()
    outcome = _applier(db_factory, manager).apply(
        _plan(channels=[_channel()], programmes=[_programme()]),
        plugin_id=PLUGIN,
        plan_generation=7,
    )

    assert outcome.ok and outcome.created == ["event:p:lg:1"]
    assert manager.created[0]["stream_ids"] == [8, 12]
    with get_connection(db_path) as conn:
        channel = get_plugin_channel(conn, PLUGIN, "event:p:lg:1")
        assert channel is not None
        assert channel.plugin_adoption_key == "slot:p:lg:1"
        assert channel.plugin_plan_generation == 7
        assert channel.dispatcharr_channel_id == 9001
        assert channel.channel_number is not None
        streams = get_channel_streams(conn, channel.id)
        assert [s.dispatcharr_stream_id for s in streams] == [8, 12]
        assert [s.priority for s in streams] == [0, 1]
        history = conn.execute(
            """SELECT change_type, change_source FROM managed_channel_history
               WHERE managed_channel_id = ?""",
            (channel.id,),
        ).fetchall()
        kinds = [(h["change_type"], h["change_source"]) for h in history]
        assert kinds == [("created", "lifecycle")]


def test_apply_compensates_remote_create_when_local_insert_fails(
    db_path, db_factory, monkeypatch
):
    manager = FakeChannelManager()
    import teamarr.consumers.planning.applier as applier_module

    def boom(*args, **kwargs):
        raise RuntimeError("local insert failed")

    monkeypatch.setattr(applier_module, "create_managed_channel", boom)
    outcome = _applier(db_factory, manager).apply(
        _plan(channels=[_channel()]), plugin_id=PLUGIN, plan_generation=1
    )

    assert not outcome.ok
    assert outcome.failures[0].code == "plan.create_failed"
    assert manager.deletes == [9001]  # remote create was rolled back
    with get_connection(db_path) as conn:
        assert get_plugin_channels(conn, PLUGIN) == []


def test_failed_plan_never_runs_a_deletion_diff(db_path, db_factory):
    manager = FakeChannelManager()
    with get_connection(db_path) as conn:
        _seed_plugin_channel(conn, logical_key="event:p:lg:1", adoption_key="slot:p:lg:1")

    failed = PlanResult(
        plugin_id=PLUGIN,
        status="failed",
        diagnostics=[PlanDiagnostic(code="provider.outage", message="ESPN unreachable")],
    )
    outcome = _applier(db_factory, manager).apply(
        failed, plugin_id=PLUGIN, plan_generation=2
    )

    assert not outcome.ok
    assert outcome.failures[0].code == "plan.not_complete"
    assert outcome.retired == []
    assert manager.deletes == []
    with get_connection(db_path) as conn:
        assert get_plugin_channel(conn, PLUGIN, "event:p:lg:1") is not None


def test_validation_failure_blocks_all_mutation(db_path, db_factory):
    manager = FakeChannelManager()
    with get_connection(db_path) as conn:
        create_managed_channel(
            conn, None, "core-1", "espn", "plan:p:lg:1", "Core Channel"
        )

    outcome = _applier(db_factory, manager).apply(
        _plan(channels=[_channel()], programmes=[_programme()]),
        plugin_id=PLUGIN,
        plan_generation=1,
    )

    assert not outcome.ok
    assert outcome.failures[0].code == "plan.tvg_id_conflict"
    assert manager.created == []


def test_apply_adopts_by_adoption_key_with_remote_rename_first(db_path, db_factory):
    manager = FakeChannelManager()
    with get_connection(db_path) as conn:
        _seed_plugin_channel(
            conn,
            logical_key="event:p:provisional",
            adoption_key="slot:p:lg:1",
            name="Provisional",
            tvg="plan:p:lg:1",
        )

    outcome = _applier(db_factory, manager).apply(
        _plan(
            channels=[
                _channel(display_name="Canonical Name", xmltv_channel_id="plan:p:lg:1")
            ]
        ),
        plugin_id=PLUGIN,
        plan_generation=4,
    )

    assert outcome.ok and outcome.adopted == ["event:p:lg:1"]
    assert manager.updates[0] == (777, {"name": "Canonical Name", "tvg_id": "plan:p:lg:1"})
    with get_connection(db_path) as conn:
        channel = get_plugin_channel(conn, PLUGIN, "event:p:lg:1")
        assert channel is not None
        assert channel.channel_name == "Canonical Name"
        assert channel.plugin_plan_generation == 4
        assert channel.dispatcharr_channel_id == 777  # same row, same channel
        history = conn.execute(
            """SELECT change_type, field_name, old_value, new_value
               FROM managed_channel_history WHERE managed_channel_id = ?""",
            (channel.id,),
        ).fetchall()
        assert [(h["change_type"], h["field_name"]) for h in history] == [
            ("modified", "plugin_logical_key")
        ]
        assert history[0]["old_value"] == "event:p:provisional"
        assert history[0]["new_value"] == "event:p:lg:1"


def test_apply_update_is_closed_loop_on_dispatcharr_failure(db_path, db_factory):
    manager = FakeChannelManager()
    manager.fail_update = True
    with get_connection(db_path) as conn:
        channel_id = _seed_plugin_channel(
            conn, logical_key="event:p:lg:1", adoption_key="slot:p:lg:1", name="Old name"
        )

    outcome = _applier(db_factory, manager).apply(
        _plan(channels=[_channel(display_name="New name")]),
        plugin_id=PLUGIN,
        plan_generation=5,
    )

    assert not outcome.ok
    assert outcome.failures[0].code == "plan.dispatcharr_update_failed"
    with get_connection(db_path) as conn:
        channel = get_managed_channel(conn, channel_id)
        assert channel is not None and channel.channel_name == "Old name"


def test_apply_update_records_local_only_fields_after_remote_success(db_path, db_factory):
    manager = FakeChannelManager()
    with get_connection(db_path) as conn:
        _seed_plugin_channel(
            conn, logical_key="event:p:lg:1", adoption_key="slot:p:lg:1", name="Old name"
        )
    later = STOP + timedelta(hours=2)

    outcome = _applier(db_factory, manager).apply(
        _plan(channels=[_channel(delete_at=later, display_name="New name")]),
        plugin_id=PLUGIN,
        plan_generation=5,
    )

    assert outcome.ok and outcome.updated == ["event:p:lg:1"]
    with get_connection(db_path) as conn:
        channel = get_plugin_channel(conn, PLUGIN, "event:p:lg:1")
        assert channel is not None
        assert channel.channel_name == "New name"
        assert channel.scheduled_delete_at is not None
        from teamarr.consumers.planning import load_host_time

        assert load_host_time(channel.scheduled_delete_at) == later


def test_stream_push_failure_is_reported_but_priorities_stay_desired(db_path, db_factory):
    manager = FakeChannelManager()
    manager.fail_update = True
    with get_connection(db_path) as conn:
        _seed_plugin_channel(
            conn,
            logical_key="event:p:lg:1",
            adoption_key="slot:p:lg:1",
            tvg="plan:p:lg:1",
            streams=(12, 8),
            delete_at=STOP,
        )

    outcome = _applier(db_factory, manager).apply(
        _plan(channels=[_channel()]), plugin_id=PLUGIN, plan_generation=6
    )

    assert not outcome.ok
    assert outcome.failures[0].code == "plan.stream_push_failed"
    with get_connection(db_path) as conn:
        channel = get_plugin_channel(conn, PLUGIN, "event:p:lg:1")
        assert channel is not None
        streams = get_channel_streams(conn, channel.id)
        assert [s.dispatcharr_stream_id for s in streams] == [8, 12]


def test_retire_keeps_row_when_remote_delete_fails(db_path, db_factory):
    manager = FakeChannelManager()
    manager.fail_delete = True
    with get_connection(db_path) as conn:
        _seed_plugin_channel(
            conn, logical_key="event:p:lg:1", adoption_key="slot:p:lg:1"
        )

    outcome = _applier(db_factory, manager).apply(_plan(), plugin_id=PLUGIN, plan_generation=8)

    assert not outcome.ok
    assert outcome.failures[0].code == "plan.dispatcharr_delete_failed"
    with get_connection(db_path) as conn:
        assert get_plugin_channel(conn, PLUGIN, "event:p:lg:1") is not None


def test_retire_deletes_remotely_then_soft_deletes_locally(db_path, db_factory):
    manager = FakeChannelManager()
    with get_connection(db_path) as conn:
        _seed_plugin_channel(
            conn, logical_key="event:p:lg:1", adoption_key="slot:p:lg:1"
        )

    outcome = _applier(db_factory, manager).apply(_plan(), plugin_id=PLUGIN, plan_generation=8)

    assert outcome.ok and outcome.retired == ["event:p:lg:1"]
    assert manager.deletes == [777]
    with get_connection(db_path) as conn:
        assert get_plugin_channel(conn, PLUGIN, "event:p:lg:1") is None
        row = conn.execute(
            "SELECT delete_reason FROM managed_channels WHERE plugin_id = ?",
            (PLUGIN,),
        ).fetchone()
        assert row["delete_reason"] == "plugin_plan_retire"


def test_metrics_shape_matches_run_recording_contract(db_path, db_factory):
    outcome = _applier(db_factory, FakeChannelManager()).apply(
        _plan(channels=[_channel()], programmes=[_programme()]),
        plugin_id=PLUGIN,
        plan_generation=9,
    )
    metrics = outcome.to_metrics()
    assert metrics == {
        "plugin_id": PLUGIN,
        "plan_generation": 9,
        "dry_run": False,
        "created": 1,
        "adopted": 0,
        "updated": 0,
        "stream_ordered": 0,
        "retired": 0,
        "failures": [],
    }
