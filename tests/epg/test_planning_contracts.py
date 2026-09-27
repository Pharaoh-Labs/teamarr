"""Packet 8A: versioned in-process planning data and shadow event-group proof."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from teamarr.consumers.planning import (
    ChannelPlan,
    EventGroupShadowSource,
    PlanDiagnostic,
    PlanResult,
    ProgrammePlan,
    SessionSnapshot,
    StreamSnapshot,
    decode_plan_request,
    decode_plan_result,
    encode_plan_request,
    encode_plan_result,
    snapshot_event_group_match,
)
from teamarr.consumers.planning.contracts import MAX_PLAN_BYTES, PlanRequest
from teamarr.core import Event, EventStatus, Programme, Team
from teamarr.database.groups import EventEPGGroup

START = datetime(2026, 9, 27, 18, tzinfo=UTC)
STOP = START + timedelta(hours=3)


def _channel(**overrides):
    fields = dict(
        plugin_id="internal.event-group-shadow",
        logical_key="event:espn:nfl:123",
        adoption_key="event:espn:nfl:123",
        display_name="Lions at Bears",
        xmltv_channel_id="shadow:group:7:espn:nfl:123",
        event_key="espn:nfl:123",
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
        plugin_id="internal.event-group-shadow",
        channel_logical_key="event:espn:nfl:123",
        programme_key="espn:nfl:123:main",
        start=START,
        stop=STOP,
        title="Lions at Bears",
    )
    fields.update(overrides)
    return ProgrammePlan(**fields)


def test_plan_json_is_versioned_strict_and_deterministic():
    result = PlanResult(
        plugin_id="internal.event-group-shadow",
        status="complete",
        channels=[_channel()],
        programmes=[_programme()],
    )
    payload = encode_plan_result(result)

    assert decode_plan_result(payload) == result
    assert encode_plan_result(decode_plan_result(payload)) == payload
    assert json.loads(payload)["schema_version"] == 1
    assert b"stream_url" not in payload
    with pytest.raises(ValidationError):
        decode_plan_result(payload.replace(b'"schema_version":1', b'"schema_version":2'))
    with pytest.raises(ValidationError):
        decode_plan_result(payload[:-1] + b',"unrecognized":"value"}')


def test_stream_snapshot_rejects_urls_account_names_and_unknown_fields():
    with pytest.raises(ValidationError):
        StreamSnapshot(id=8, source_key="group:7", stream_url="http://example/secret")
    with pytest.raises(ValidationError):
        StreamSnapshot(id=8, source_key="group:7", m3u_account_name="secret")


def test_metadata_cannot_carry_stream_urls_or_credentials():
    with pytest.raises(ValidationError):
        _channel(metadata={"stream_url": "http://secret/live"})
    with pytest.raises(ValidationError):
        _programme(metadata={"hint": "http://secret/live"})


def test_session_snapshot_rejects_invalid_window():
    with pytest.raises(ValidationError):
        SessionSnapshot(key="race", event_key="espn:nfl:123", start=START, end=START)


@pytest.mark.parametrize(
    "channel_changes",
    [
        {"create_at": datetime(2026, 9, 27, 18)},
        {"delete_at": START},
        {"programme_end_at": STOP + timedelta(minutes=1)},
        {"ordered_stream_ids": [8, 8]},
        {"per_session_programme_windows": {"first": (START, STOP + timedelta(hours=1))}},
    ],
)
def test_channel_rejects_invalid_time_and_stream_boundaries(channel_changes):
    with pytest.raises(ValidationError):
        _channel(**channel_changes)


def test_result_rejects_mixed_ownership_duplicates_and_dangling_programmes():
    with pytest.raises(ValidationError, match="plan plugin"):
        PlanResult(plugin_id="other", status="complete", channels=[_channel()])
    with pytest.raises(ValidationError, match="duplicate channel"):
        PlanResult(
            plugin_id="internal.event-group-shadow",
            status="complete",
            channels=[_channel(), _channel()],
        )
    with pytest.raises(ValidationError, match="unknown channel"):
        PlanResult(
            plugin_id="internal.event-group-shadow", status="complete", programmes=[_programme()]
        )


def test_complete_empty_is_distinct_from_failure():
    empty = PlanResult(plugin_id="internal.event-group-shadow", status="complete")
    failed = PlanResult(
        plugin_id="internal.event-group-shadow",
        status="failed",
        diagnostics=[PlanDiagnostic(code="shadow.incomplete_event", message="Incomplete event")],
    )
    assert decode_plan_result(encode_plan_result(empty)).status == "complete"
    assert decode_plan_result(encode_plan_result(failed)).status == "failed"
    with pytest.raises(ValidationError):
        PlanResult(plugin_id="internal.event-group-shadow", status="failed")
    with pytest.raises(ValidationError):
        PlanResult(plugin_id="internal.event-group-shadow", status="failed", channels=[_channel()])


def test_plan_payload_is_bounded_before_json_parsing():
    with pytest.raises(ValueError, match="maximum serialized size"):
        decode_plan_result(b"{" + b" " * MAX_PLAN_BYTES)
    with pytest.raises(ValueError, match="maximum serialized size"):
        decode_plan_request(b"{" + b" " * MAX_PLAN_BYTES)
    with pytest.raises(ValidationError):
        PlanResult(
            plugin_id="internal.event-group-shadow",
            status="complete",
            channels=[_channel(logical_key=f"event:{i}") for i in range(501)],
        )


def _event():
    lions = Team("lions", "espn", "Lions", "Lions", "DET", "nfl", "football")
    bears = Team("bears", "espn", "Bears", "Bears", "CHI", "nfl", "football")
    return Event(
        id="123",
        provider="espn",
        name="Lions at Bears",
        short_name="DET @ CHI",
        start_time=START,
        home_team=bears,
        away_team=lions,
        status=EventStatus("scheduled"),
        league="nfl",
        sport="football",
    )


def test_event_group_shadow_source_uses_existing_match_and_programme_records():
    event = _event()
    group = EventEPGGroup(id=7, name="NFL")
    entries = [
        {
            "stream": {"id": 12, "name": "Private account name", "url": "http://private"},
            "event": event,
        },
        {"stream": {"id": 8, "url": "http://other"}, "event": event},
    ]
    programme = Programme(
        channel_id="event-123",
        title="Lions at Bears",
        start=START,
        stop=STOP,
        categories=["Sports", "Football"],
    )
    request = snapshot_event_group_match(group, entries, [(event, programme)])
    result = EventGroupShadowSource().plan(request)

    assert result.status == "complete"
    assert result.channels == [_channel()]
    assert result.programmes == [_programme(categories=["Sports", "Football"])]
    assert request.model_dump_json().find("Private account name") == -1
    assert "http://private" not in request.model_dump_json()
    assert encode_plan_result(result) == encode_plan_result(
        EventGroupShadowSource().plan(
            snapshot_event_group_match(group, entries[::-1], [(event, programme)])
        )
    )
    assert PlanRequest.model_validate_json(request.model_dump_json()) == request
    assert decode_plan_request(encode_plan_request(request)) == request
    with pytest.raises(ValidationError):
        decode_plan_request(
            encode_plan_request(request).replace(b'"schema_version":1', b'"schema_version":2')
        )


def test_shadow_source_fails_incomplete_discovery_instead_of_retiring_channels():
    event = _event()
    group = EventEPGGroup(id=7, name="NFL")
    source = EventGroupShadowSource()
    empty = source.plan(snapshot_event_group_match(group, [], []))
    incomplete = source.plan(
        snapshot_event_group_match(group, [{"stream": {"id": 8}, "event": event}], [])
    )

    assert empty.status == "complete" and not empty.channels
    assert incomplete.status == "failed" and not incomplete.channels
    assert incomplete.diagnostics[0].code == "shadow.incomplete_event"
