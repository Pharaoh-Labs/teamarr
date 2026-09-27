"""Version 1 JSON planning records (Packet 8A).

These are *data* contracts, not the internal GenerationContext or a subprocess
protocol. Applying a plan, ownership, and cross-source conflict checks are
separate M4 packets. No record carries stream URLs or M3U account names.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_PLAN_BYTES = 1_048_576
MAX_CHANNELS = 500
MAX_PROGRAMMES = 5_000
MAX_DIAGNOSTICS = 500

Key = Annotated[str, Field(min_length=1, max_length=192, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Text = Annotated[str, Field(min_length=1, max_length=512)]
Metadata = dict[str, str | int | float | bool | None]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("planning times must have a timezone")
    return value.astimezone(UTC)


def _safe_metadata(value: Metadata) -> Metadata:
    """Keep optional annotations from becoming an escape hatch for stream secrets."""
    forbidden = ("url", "account", "credential", "password", "secret", "token", "m3u", "stream")
    for key, item in value.items():
        if not key or len(key) > 64 or any(term in key.lower() for term in forbidden):
            raise ValueError("metadata key is empty, too long, or sensitive")
        if isinstance(item, str) and (len(item) > 256 or "://" in item):
            raise ValueError("metadata values cannot contain URLs or exceed 256 characters")
    return value


class StreamSnapshot(Record):
    id: int = Field(gt=0)
    source_key: Key
    # Deliberately no stream URL, M3U account name, or credentials.


class SourceSnapshot(Record):
    key: Key
    stream_ids: list[int] = Field(default_factory=list, max_length=MAX_CHANNELS * 10)

    @model_validator(mode="after")
    def valid_streams(self) -> SourceSnapshot:
        if len(self.stream_ids) != len(set(self.stream_ids)) or any(
            i <= 0 for i in self.stream_ids
        ):
            raise ValueError("source stream IDs must be unique positive integers")
        return self


class EventSnapshot(Record):
    key: Key
    name: Text
    start: datetime
    sport: Key
    league: Key

    _start_aware = field_validator("start")(_aware)


class SessionSnapshot(Record):
    key: Key
    event_key: Key
    start: datetime
    end: datetime

    _times_aware = field_validator("start", "end")(_aware)

    @model_validator(mode="after")
    def valid_window(self) -> SessionSnapshot:
        if self.end <= self.start:
            raise ValueError("session end must follow start")
        return self


class ProgrammeSnapshot(Record):
    key: Key
    event_key: Key
    start: datetime
    stop: datetime
    title: Text
    subtitle: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=4_096)
    categories: list[str] = Field(default_factory=list, max_length=16)
    icon_url: str | None = Field(default=None, max_length=2_048)

    _times_aware = field_validator("start", "stop")(_aware)

    @model_validator(mode="after")
    def valid_window(self) -> ProgrammeSnapshot:
        if self.stop <= self.start:
            raise ValueError("programme stop must follow start")
        return self


class MatchSnapshot(Record):
    event_key: Key
    stream_id: int = Field(gt=0)


class PlanRequest(Record):
    schema_version: Literal[1] = 1
    plugin_id: Key
    source: SourceSnapshot
    streams: list[StreamSnapshot] = Field(default_factory=list, max_length=MAX_CHANNELS * 10)
    events: list[EventSnapshot] = Field(default_factory=list, max_length=MAX_CHANNELS)
    sessions: list[SessionSnapshot] = Field(default_factory=list, max_length=MAX_PROGRAMMES)
    programmes: list[ProgrammeSnapshot] = Field(default_factory=list, max_length=MAX_PROGRAMMES)
    matches: list[MatchSnapshot] = Field(default_factory=list, max_length=MAX_CHANNELS * 10)

    @model_validator(mode="after")
    def valid_references(self) -> PlanRequest:
        streams = {stream.id for stream in self.streams}
        events = {event.key for event in self.events}
        sessions = {session.key for session in self.sessions}
        if len(streams) != len(self.streams) or len(events) != len(self.events):
            raise ValueError("snapshot identities must be unique")
        if len(sessions) != len(self.sessions) or any(
            session.event_key not in events for session in self.sessions
        ):
            raise ValueError("sessions must have unique keys and known events")
        if streams != set(self.source.stream_ids):
            raise ValueError("source stream IDs must match the stream snapshots")
        if any(stream.source_key != self.source.key for stream in self.streams):
            raise ValueError("stream belongs to a different source")
        if any(
            match.stream_id not in streams or match.event_key not in events
            for match in self.matches
        ):
            raise ValueError("match references an unknown stream or event")
        if any(programme.event_key not in events for programme in self.programmes):
            raise ValueError("programme references an unknown event")
        return self


class ChannelPlan(Record):
    plugin_id: Key
    logical_key: Key
    adoption_key: Key
    display_name: Text
    xmltv_channel_id: Key
    event_key: Key
    session_keys: list[Key] = Field(default_factory=list, max_length=100)
    variant_key: Key
    ordered_stream_ids: list[int] = Field(default_factory=list, max_length=1_000)
    create_at: datetime
    delete_at: datetime
    programme_start_at: datetime
    programme_end_at: datetime
    per_session_programme_windows: dict[str, tuple[datetime, datetime]] = Field(
        default_factory=dict, max_length=100
    )
    logo_hint: str | None = Field(default=None, max_length=2_048)
    group_hint: str | None = Field(default=None, max_length=192)
    profile_hints: list[Key] = Field(default_factory=list, max_length=32)
    metadata: Metadata = Field(default_factory=dict, max_length=32)

    _times_aware = field_validator(
        "create_at", "delete_at", "programme_start_at", "programme_end_at"
    )(_aware)
    _metadata_safe = field_validator("metadata")(_safe_metadata)

    @model_validator(mode="after")
    def valid_windows(self) -> ChannelPlan:
        if self.delete_at <= self.create_at:
            raise ValueError("channel deletion must follow creation")
        if not self.create_at <= self.programme_start_at < self.programme_end_at <= self.delete_at:
            raise ValueError("programme window must fit the channel lifetime")
        for start, end in self.per_session_programme_windows.values():
            _aware(start)
            _aware(end)
            if not self.programme_start_at <= start < end <= self.programme_end_at:
                raise ValueError("session programme window must fit the channel programme window")
        if len(self.ordered_stream_ids) != len(set(self.ordered_stream_ids)) or any(
            stream_id <= 0 for stream_id in self.ordered_stream_ids
        ):
            raise ValueError("ordered stream IDs must be unique positive integers")
        return self


class ProgrammePlan(Record):
    plugin_id: Key
    channel_logical_key: Key
    programme_key: Key
    start: datetime
    stop: datetime
    title: Text
    subtitle: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=4_096)
    categories: list[str] = Field(default_factory=list, max_length=16)
    is_live: bool = True
    is_new: bool = False
    icon_url: str | None = Field(default=None, max_length=2_048)
    language: str | None = Field(default=None, max_length=32)
    metadata: Metadata = Field(default_factory=dict, max_length=32)

    _times_aware = field_validator("start", "stop")(_aware)
    _metadata_safe = field_validator("metadata")(_safe_metadata)

    @model_validator(mode="after")
    def valid_window(self) -> ProgrammePlan:
        if self.stop <= self.start:
            raise ValueError("programme stop must follow start")
        return self


class PlanDiagnostic(Record):
    code: Key
    message: Text
    item_key: Key | None = None


class PlanResult(Record):
    schema_version: Literal[1] = 1
    plugin_id: Key
    status: Literal["complete", "failed"]
    channels: list[ChannelPlan] = Field(default_factory=list, max_length=MAX_CHANNELS)
    programmes: list[ProgrammePlan] = Field(default_factory=list, max_length=MAX_PROGRAMMES)
    diagnostics: list[PlanDiagnostic] = Field(default_factory=list, max_length=MAX_DIAGNOSTICS)

    @model_validator(mode="after")
    def valid_result(self) -> PlanResult:
        if self.status == "failed":
            if self.channels or self.programmes:
                raise ValueError("failed plans cannot contain actionable records")
            if not self.diagnostics:
                raise ValueError("failed plans require a diagnostic")
        if any(record.plugin_id != self.plugin_id for record in (*self.channels, *self.programmes)):
            raise ValueError("every record must belong to the plan plugin")
        channel_keys = [channel.logical_key for channel in self.channels]
        if len(channel_keys) != len(set(channel_keys)):
            raise ValueError("duplicate channel logical keys")
        if len({(p.channel_logical_key, p.programme_key) for p in self.programmes}) != len(
            self.programmes
        ):
            raise ValueError("duplicate programme keys")
        if any(p.channel_logical_key not in channel_keys for p in self.programmes):
            raise ValueError("programme references an unknown channel")
        return self


def encode_plan_result(result: PlanResult) -> bytes:
    """Canonical, size-limited JSON; never silently truncate a plan."""
    return _encode_limited(result)


def _encode_limited(record: Record) -> bytes:
    payload = record.model_dump_json(exclude_none=True).encode("utf-8")
    if len(payload) > MAX_PLAN_BYTES:
        raise ValueError("planning payload exceeds maximum serialized size")
    return payload


def decode_plan_result(payload: bytes) -> PlanResult:
    """Reject oversized input before parsing, and revalidate after parsing."""
    if len(payload) > MAX_PLAN_BYTES:
        raise ValueError("planning payload exceeds maximum serialized size")
    result = PlanResult.model_validate_json(payload)
    encode_plan_result(result)
    return result


def encode_plan_request(request: PlanRequest) -> bytes:
    """Bound the input snapshot as well as the resulting plan."""
    return _encode_limited(request)


def decode_plan_request(payload: bytes) -> PlanRequest:
    if len(payload) > MAX_PLAN_BYTES:
        raise ValueError("planning payload exceeds maximum serialized size")
    request = PlanRequest.model_validate_json(payload)
    encode_plan_request(request)
    return request
