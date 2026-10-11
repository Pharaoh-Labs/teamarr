"""Packet 8C: host-state validation of an in-process plan."""

from datetime import UTC, datetime, timedelta

from teamarr.consumers.planning import (
    ChannelPlan,
    PlanResult,
    ProgrammePlan,
    validate_plan,
)
from teamarr.database.channels import create_managed_channel

PLUGIN = "test.provider"
START = datetime(2026, 10, 6, 18, tzinfo=UTC)
STOP = START + timedelta(hours=3)


def _channel(**overrides):
    fields = dict(
        plugin_id=PLUGIN,
        logical_key="event:p:lg:1",
        adoption_key="slot:p:lg:1",
        display_name="Feature Event",
        xmltv_channel_id="plan:p:lg:1",
        event_key="p:lg:1",
        variant_key="main",
        ordered_stream_ids=[8],
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


def test_valid_plan_has_no_diagnostics(db_conn):
    diagnostics = validate_plan(
        _plan(channels=[_channel()], programmes=[_programme()]),
        expected_plugin_id=PLUGIN,
        conn=db_conn,
        resolve_stream_ids=lambda ids: ids,
        resolve_group_hints=lambda names: names,
        resolve_profile_hints=lambda names: names,
    )
    assert diagnostics == []


def test_plan_for_another_plugin_is_rejected_wholesale(db_conn):
    diagnostics = validate_plan(
        _plan(), expected_plugin_id="other.plugin", conn=db_conn
    )
    assert [d.code for d in diagnostics] == ["plan.wrong_plugin"]


def test_programme_outside_channel_window_is_rejected(db_conn):
    late = _programme(stop=STOP + timedelta(minutes=1))
    plan = PlanResult(
        plugin_id=PLUGIN,
        status="complete",
        channels=[_channel()],
        programmes=[late],
    )
    diagnostics = validate_plan(plan, expected_plugin_id=PLUGIN, conn=db_conn)
    assert [d.code for d in diagnostics] == ["plan.programme_window"]
    assert diagnostics[0].item_key == "p:lg:1:main"


def test_xmltv_id_owned_by_core_or_other_plugin_is_a_conflict(db_conn):
    create_managed_channel(
        db_conn, None, "core-1", "espn", "plan:p:lg:1", "Core Channel"
    )
    create_managed_channel(
        db_conn,
        None,
        "evt-2",
        "plugin",
        "plan:p:lg:2",
        "Other Plugin",
        plugin_id="other.plugin",
        plugin_logical_key="other:1",
        plugin_adoption_key="other:slot:1",
    )
    diagnostics = validate_plan(
        _plan(channels=[_channel()], programmes=[_programme()]),
        expected_plugin_id=PLUGIN,
        conn=db_conn,
    )
    conflicts = [d for d in diagnostics if d.code == "plan.tvg_id_conflict"]
    assert [d.item_key for d in conflicts] == ["event:p:lg:1"]
    assert "owned by 'core'" in conflicts[0].message


def test_plugin_channel_matched_by_logical_key_is_not_a_conflict(db_conn):
    create_managed_channel(
        db_conn,
        None,
        "evt-1",
        "plugin",
        "plan:p:lg:1",
        "Feature Event",
        plugin_id=PLUGIN,
        plugin_logical_key="event:p:lg:1",
        plugin_adoption_key="slot:p:lg:1",
    )
    diagnostics = validate_plan(
        _plan(channels=[_channel()], programmes=[_programme()]),
        expected_plugin_id=PLUGIN,
        conn=db_conn,
    )
    assert diagnostics == []


def test_plugin_channel_matched_by_adoption_key_is_not_a_conflict(db_conn):
    # The row keeps the xmltv id the plan wants; adoption renames it in place.
    create_managed_channel(
        db_conn,
        None,
        "evt-1",
        "plugin",
        "plan:p:lg:1",
        "Provisional",
        plugin_id=PLUGIN,
        plugin_logical_key="event:p:provisional",
        plugin_adoption_key="slot:p:lg:1",
    )
    diagnostics = validate_plan(
        _plan(channels=[_channel()], programmes=[_programme()]),
        expected_plugin_id=PLUGIN,
        conn=db_conn,
    )
    assert diagnostics == []


def test_ambiguous_adoption_holder_still_conflicts(db_conn):
    for suffix in ("a", "b"):
        create_managed_channel(
            db_conn,
            None,
            f"evt-{suffix}",
            "plugin",
            "plan:p:lg:1" if suffix == "a" else "plan:other",
            f"Holder {suffix}",
            plugin_id=PLUGIN,
            plugin_logical_key=f"event:p:lg:{suffix}",
            plugin_adoption_key="slot:p:lg:1",
        )
    diagnostics = validate_plan(
        _plan(channels=[_channel()], programmes=[_programme()]),
        expected_plugin_id=PLUGIN,
        conn=db_conn,
    )
    assert [d.code for d in diagnostics] == ["plan.tvg_id_conflict"]


def test_unknown_streams_group_and_profile_hints_are_reported(db_conn):
    diagnostics = validate_plan(
        _plan(channels=[_channel(group_hint="Premium Sports", profile_hints=["1080p"])]),
        expected_plugin_id=PLUGIN,
        conn=db_conn,
        resolve_stream_ids=lambda ids: set(),  # nothing is known
        resolve_group_hints=lambda names: set(),
        resolve_profile_hints=lambda names: set(),
    )
    codes = sorted(d.code for d in diagnostics)
    assert codes == [
        "plan.unknown_group_hint",
        "plan.unknown_profile_hint",
        "plan.unknown_stream",
    ]
    stream = next(d for d in diagnostics if d.code == "plan.unknown_stream")
    assert "stream 8" in stream.message
    assert stream.item_key == "event:p:lg:1"


def test_unknown_catalog_checks_are_skipped_without_resolvers(db_conn):
    diagnostics = validate_plan(
        _plan(channels=[_channel(group_hint="Anything", profile_hints=["x"])]),
        expected_plugin_id=PLUGIN,
        conn=db_conn,
    )
    assert diagnostics == []
