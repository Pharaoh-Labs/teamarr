"""An in-process shadow adapter for existing event-group match data.

Only an explicit caller/test invokes this adapter. It neither runs the normal
processor nor replaces it; applying/retiring channels and XMLTV publication are
intentionally absent until later packets. The fixture path is the existing
matched-stream dict (``stream`` + ``event``) and generated ``Programme``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol

from teamarr.consumers.planning.contracts import (
    ChannelPlan,
    EventSnapshot,
    MatchSnapshot,
    PlanDiagnostic,
    PlanRequest,
    PlanResult,
    ProgrammePlan,
    ProgrammeSnapshot,
    SourceSnapshot,
    StreamSnapshot,
)
from teamarr.core import Event, Programme
from teamarr.database.groups import EventEPGGroup


class PlanSource(Protocol):
    """Internal plan producer. No database or Dispatcharr dependency."""

    def plan(self, request: PlanRequest) -> PlanResult: ...


def _event_key(event: Event) -> str:
    return f"{event.provider}:{event.league}:{event.id}"


def snapshot_event_group_match(
    group: EventEPGGroup,
    matched_streams: Sequence[dict],
    event_programmes: Sequence[tuple[Event, Programme]],
    *,
    plugin_id: str = "internal.event-group-shadow",
) -> PlanRequest:
    """Copy only IDs and public event/programme fields from the built-in path.

    Caller supplies already-matched events and already-rendered programmes; this
    does not fetch schedules or call any of the existing mutation methods.
    """
    source_key = f"group:{group.id}"
    events: dict[str, EventSnapshot] = {}
    streams: dict[int, StreamSnapshot] = {}
    matches: set[tuple[str, int]] = set()
    for match in matched_streams:
        event: Event = match["event"]
        stream_id = match["stream"]["id"]
        key = _event_key(event)
        events[key] = EventSnapshot(
            key=key,
            name=event.name,
            start=event.start_time,
            sport=event.sport,
            league=event.league,
        )
        streams[stream_id] = StreamSnapshot(id=stream_id, source_key=source_key)
        matches.add((key, stream_id))

    programmes = [
        ProgrammeSnapshot(
            key=f"{_event_key(event)}:main",
            event_key=_event_key(event),
            start=programme.start,
            stop=programme.stop,
            title=programme.title,
            subtitle=programme.subtitle,
            description=programme.description,
            categories=programme.categories,
            icon_url=programme.icon,
        )
        for event, programme in event_programmes
    ]
    return PlanRequest(
        plugin_id=plugin_id,
        source=SourceSnapshot(key=source_key, stream_ids=sorted(streams)),
        streams=[streams[i] for i in sorted(streams)],
        events=[events[key] for key in sorted(events)],
        programmes=sorted(programmes, key=lambda p: p.key),
        matches=[MatchSnapshot(event_key=key, stream_id=i) for key, i in sorted(matches)],
    )


class EventGroupShadowSource:
    """Prove an event-group matched path can produce a host-neutral plan."""

    def plan(self, request: PlanRequest) -> PlanResult:
        streams_by_event: dict[str, list[int]] = defaultdict(list)
        for match in request.matches:
            streams_by_event[match.event_key].append(match.stream_id)
        programmes_by_event: dict[str, list[ProgrammeSnapshot]] = defaultdict(list)
        for programme in request.programmes:
            programmes_by_event[programme.event_key].append(programme)

        if any(
            not streams_by_event[event.key] or not programmes_by_event[event.key]
            for event in request.events
        ):
            return PlanResult(
                plugin_id=request.plugin_id,
                status="failed",
                diagnostics=[
                    PlanDiagnostic(
                        code="shadow.incomplete_event",
                        message="Matched event lacks streams or a complete programme",
                    )
                ],
            )

        channels: list[ChannelPlan] = []
        programmes: list[ProgrammePlan] = []
        for event in request.events:
            entries = programmes_by_event[event.key]
            start = min(p.start for p in entries)
            stop = max(p.stop for p in entries)
            logical_key = f"event:{event.key}"
            channels.append(
                ChannelPlan(
                    plugin_id=request.plugin_id,
                    logical_key=logical_key,
                    adoption_key=logical_key,
                    display_name=event.name,
                    xmltv_channel_id=f"shadow:{request.source.key}:{event.key}",
                    event_key=event.key,
                    variant_key="main",
                    ordered_stream_ids=sorted(set(streams_by_event[event.key])),
                    create_at=start,
                    delete_at=stop,
                    programme_start_at=start,
                    programme_end_at=stop,
                )
            )
            for entry in sorted(entries, key=lambda p: (p.start, p.key)):
                programmes.append(
                    ProgrammePlan(
                        plugin_id=request.plugin_id,
                        channel_logical_key=logical_key,
                        programme_key=entry.key,
                        start=entry.start,
                        stop=entry.stop,
                        title=entry.title,
                        subtitle=entry.subtitle,
                        description=entry.description,
                        categories=entry.categories,
                        icon_url=entry.icon_url,
                    )
                )

        return PlanResult(
            plugin_id=request.plugin_id,
            status="complete",
            channels=channels,
            programmes=programmes,
        )
