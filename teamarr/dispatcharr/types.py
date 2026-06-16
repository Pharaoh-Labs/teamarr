"""Dataclasses for Dispatcharr API responses.

These types represent the data structures returned by the Dispatcharr API.
All types are frozen dataclasses for immutability and hashability.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _parse_iso(value: str | None) -> datetime | None:
    """Parse a Dispatcharr ISO8601 timestamp to an aware UTC datetime.

    Handles the trailing "Z" form (e.g. "2026-06-01T00:00:00Z"). Returns
    None for missing or unparseable values. Naive results are assumed UTC.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


@dataclass(frozen=True)
class DispatcharrChannel:
    """A channel in Dispatcharr."""

    id: int
    uuid: str
    name: str
    channel_number: str
    tvg_id: str | None = None
    channel_group_id: int | None = None
    channel_group_name: str | None = None
    logo_id: int | None = None
    logo_url: str | None = None
    streams: tuple[int, ...] = field(default_factory=tuple)
    stream_profile_id: int | None = None
    channel_profile_ids: tuple[int, ...] | None = None  # None = not in API response

    @classmethod
    def from_api(cls, data: dict) -> "DispatcharrChannel":
        """Create from API response dict."""
        streams = data.get("streams", [])
        if isinstance(streams, list):
            streams = tuple(streams)
        raw_profiles = data.get("channel_profile_ids")
        profile_ids = None
        if raw_profiles is not None:
            if isinstance(raw_profiles, list):
                profile_ids = tuple(raw_profiles)
            else:
                profile_ids = (raw_profiles,) if raw_profiles else ()
        return cls(
            id=data["id"],
            uuid=data.get("uuid", ""),
            name=data.get("name", ""),
            channel_number=str(data.get("channel_number", "")),
            tvg_id=data.get("tvg_id"),
            channel_group_id=data.get("channel_group_id"),
            channel_group_name=data.get("channel_group_name"),
            logo_id=data.get("logo_id"),
            logo_url=data.get("logo_url"),
            streams=streams,
            stream_profile_id=data.get("stream_profile_id"),
            channel_profile_ids=profile_ids,
        )


@dataclass(frozen=True)
class DispatcharrStream:
    """A stream from an M3U source in Dispatcharr."""

    id: int
    name: str
    url: str | None = None
    channel_group: str | None = None
    channel_group_id: int | None = None
    tvg_id: str | None = None
    tvg_name: str | None = None
    tvg_logo: str | None = None
    m3u_account_id: int | None = None
    m3u_account_name: str | None = None
    is_stale: bool = False  # Stream marked as stale in Dispatcharr

    @classmethod
    def from_api(cls, data: dict) -> "DispatcharrStream":
        """Create from API response dict."""
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            url=data.get("url"),
            channel_group=data.get("channel_group"),
            channel_group_id=data.get("channel_group_id"),
            tvg_id=data.get("tvg_id"),
            tvg_name=data.get("tvg_name"),
            tvg_logo=data.get("tvg_logo"),
            m3u_account_id=data.get("m3u_account"),
            m3u_account_name=data.get("m3u_account_name"),
            is_stale=data.get("is_stale", False),
        )


@dataclass(frozen=True)
class DispatcharrEPGSource:
    """An EPG source in Dispatcharr."""

    id: int
    name: str
    source_type: str
    url: str | None = None
    status: str = "idle"
    last_message: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "DispatcharrEPGSource":
        """Create from API response dict."""
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            source_type=data.get("source_type", ""),
            url=data.get("url"),
            status=data.get("status", "idle"),
            last_message=data.get("last_message"),
            updated_at=data.get("updated_at"),
        )


@dataclass(frozen=True)
class DispatcharrEPGData:
    """EPG data entry (channel within an EPG source)."""

    id: int
    tvg_id: str
    name: str | None = None
    icon_url: str | None = None
    epg_source_id: int | None = None

    @classmethod
    def from_api(cls, data: dict) -> "DispatcharrEPGData":
        """Create from API response dict."""
        return cls(
            id=data["id"],
            tvg_id=data.get("tvg_id", ""),
            name=data.get("name"),
            icon_url=data.get("icon_url"),
            epg_source_id=data.get("epg_source"),
        )


@dataclass(frozen=True)
class DispatcharrProgram:
    """An EPG program returned by /api/epg/programs/search/.

    Represents a single guide entry on a tvg_id's timeline. The endpoint
    embeds the channels and streams that carry this program; we keep their
    ids so the matcher (epic teamarrv2-183) can link a program back to the
    Dispatcharr stream that airs it.

    Requires a Dispatcharr build that exposes the program-search endpoint;
    callers must feature-detect via EPGManager.supports_program_search()
    before relying on these results.
    """

    id: int
    tvg_id: str
    title: str
    start_time: str | None = None  # ISO8601 (e.g. "2026-06-01T00:00:00Z")
    end_time: str | None = None
    sub_title: str | None = None
    description: str | None = None
    epg_source: str | None = None  # source name; "_Teamarr" = our own generated EPG
    epg_name: str | None = None
    epg_icon_url: str | None = None
    # custom_properties.categories — e.g. ("Sports", "Sports event", "Baseball").
    # Used by the matcher to distinguish real games ("Sports event") from
    # studio/talk ("Sports non-event") and replays ("Classic Sport Event").
    # Often absent/empty in sloppy EPG, so it is a precision signal, not a gate.
    categories: tuple[str, ...] = field(default_factory=tuple)
    stream_ids: tuple[int, ...] = field(default_factory=tuple)
    channel_ids: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def from_api(cls, data: dict) -> "DispatcharrProgram":
        """Create from API response dict."""
        streams = data.get("streams") or []
        channels = data.get("channels") or []
        stream_ids = tuple(s["id"] for s in streams if isinstance(s, dict) and "id" in s)
        channel_ids = tuple(c["id"] for c in channels if isinstance(c, dict) and "id" in c)
        props = data.get("custom_properties") or {}
        raw_cats = props.get("categories") if isinstance(props, dict) else None
        categories = tuple(str(c) for c in raw_cats) if isinstance(raw_cats, list) else ()
        return cls(
            id=data["id"],
            tvg_id=data.get("tvg_id", ""),
            title=data.get("title", ""),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            sub_title=data.get("sub_title"),
            description=data.get("description"),
            epg_source=data.get("epg_source"),
            epg_name=data.get("epg_name"),
            epg_icon_url=data.get("epg_icon_url"),
            categories=categories,
            stream_ids=stream_ids,
            channel_ids=channel_ids,
        )

    @property
    def start_dt(self) -> "datetime | None":
        """Parse start_time to an aware datetime, or None if unparseable."""
        return _parse_iso(self.start_time)

    @property
    def end_dt(self) -> "datetime | None":
        """Parse end_time to an aware datetime, or None if unparseable."""
        return _parse_iso(self.end_time)

    @property
    def is_teamarr(self) -> bool:
        """True if this program came from Teamarr's own generated EPG source."""
        return self.epg_source == "_Teamarr"


@dataclass(frozen=True)
class DispatcharrLogo:
    """An uploaded logo in Dispatcharr."""

    id: int
    name: str
    url: str

    @classmethod
    def from_api(cls, data: dict) -> "DispatcharrLogo":
        """Create from API response dict."""
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            url=data.get("url", ""),
        )


@dataclass(frozen=True)
class DispatcharrM3UAccount:
    """An M3U account in Dispatcharr."""

    id: int
    name: str
    status: str = "idle"
    url: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "DispatcharrM3UAccount":
        """Create from API response dict."""
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            status=data.get("status", "idle"),
            url=data.get("url"),
            updated_at=data.get("updated_at"),
        )


@dataclass(frozen=True)
class DispatcharrChannelGroup:
    """A channel group in Dispatcharr (from M3U)."""

    id: int
    name: str
    m3u_accounts: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def from_api(cls, data: dict) -> "DispatcharrChannelGroup":
        """Create from API response dict."""
        accounts = data.get("m3u_accounts", [])
        if isinstance(accounts, list):
            accounts = tuple(accounts)
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            m3u_accounts=accounts,
        )


@dataclass(frozen=True)
class DispatcharrChannelProfile:
    """A channel profile in Dispatcharr."""

    id: int
    name: str
    channel_ids: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def from_api(cls, data: dict) -> "DispatcharrChannelProfile":
        """Create from API response dict."""
        channels = data.get("channels", [])
        if isinstance(channels, list):
            channels = tuple(channels)
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            channel_ids=channels,
        )


@dataclass(frozen=True)
class DispatcharrStreamProfile:
    """A stream profile in Dispatcharr.

    Stream profiles define how streams are processed (ffmpeg, VLC, proxy, etc).
    """

    id: int
    name: str
    command: str = ""
    is_active: bool = True

    @classmethod
    def from_api(cls, data: dict) -> "DispatcharrStreamProfile":
        """Create from API response dict."""
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            command=data.get("command", ""),
            is_active=data.get("is_active", True),
        )


@dataclass
class OperationResult:
    """Result of a Dispatcharr API operation.

    This is a mutable dataclass since results are built incrementally.
    """

    success: bool
    message: str | None = None
    error: str | None = None
    data: dict | None = None
    channel: dict | None = None  # For channel operations
    logo: dict | None = None  # For logo operations
    duration: float | None = None  # For timed operations


@dataclass
class RefreshResult:
    """Result of an M3U or EPG refresh operation."""

    success: bool
    message: str | None = None
    duration: float | None = None
    source: dict | None = None  # Final state after refresh
    skipped: bool = False  # True if refresh was skipped (recently refreshed)
    last_status: str | None = None  # Last status before timeout
    last_message: str | None = None  # Last message before timeout


@dataclass
class BatchRefreshResult:
    """Result of refreshing multiple M3U accounts."""

    success: bool  # True if all succeeded
    results: dict[int, RefreshResult] = field(default_factory=dict)  # account_id -> result
    duration: float = 0.0
    failed_count: int = 0
    succeeded_count: int = 0
    skipped_count: int = 0
