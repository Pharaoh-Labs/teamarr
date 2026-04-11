"""Dataclasses for Headendarr API responses."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HeadendarrEPGSource:
    """An EPG source in Headendarr."""

    id: int
    name: str
    url: str | None = None
    enabled: bool = True
    update_schedule: str | None = None

    @classmethod
    def from_api(cls, data: dict) -> "HeadendarrEPGSource":
        return cls(
            id=int(data["id"]),
            name=data.get("name", ""),
            url=data.get("url"),
            enabled=bool(data.get("enabled", True)),
            update_schedule=data.get("update_schedule"),
        )


@dataclass(frozen=True)
class HeadendarrPlaylist:
    """A playlist source in Headendarr."""

    id: int
    name: str
    enabled: bool = True
    connections: int | None = None

    @classmethod
    def from_api(cls, data: dict) -> "HeadendarrPlaylist":
        return cls(
            id=int(data["id"]),
            name=data.get("name", ""),
            enabled=bool(data.get("enabled", True)),
            connections=data.get("connections"),
        )


@dataclass(frozen=True)
class HeadendarrStream:
    """A playlist stream in Headendarr."""

    id: int
    name: str
    url: str | None = None
    playlist_id: int | None = None
    playlist_name: str | None = None
    group_title: str | None = None
    logo_url: str | None = None
    xc_stream_id: int | None = None

    @classmethod
    def from_api(cls, data: dict) -> "HeadendarrStream":
        return cls(
            id=int(data["id"]),
            name=data.get("name", ""),
            url=data.get("url"),
            playlist_id=data.get("playlist_id"),
            playlist_name=data.get("playlist_name"),
            group_title=data.get("group_title"),
            logo_url=data.get("logo") or data.get("tvg_logo"),
            xc_stream_id=data.get("xc_stream_id"),
        )


@dataclass(frozen=True)
class HeadendarrChannelSource:
    """A source entry for a Headendarr channel."""

    playlist_id: int | None = None
    stream_name: str | None = None
    stream_url: str | None = None
    priority: int = 1
    source_type: str = "playlist"
    use_hls_proxy: bool = False
    auto_update: bool = True
    xc_account_id: int | None = None

    def to_api(self) -> dict:
        payload = {
            "priority": self.priority,
            "source_type": self.source_type,
            "use_hls_proxy": self.use_hls_proxy,
            "auto_update": self.auto_update,
        }
        if self.playlist_id is not None:
            payload["playlist_id"] = self.playlist_id
        if self.stream_name is not None:
            payload["stream_name"] = self.stream_name
        if self.stream_url is not None:
            payload["stream_url"] = self.stream_url
        if self.xc_account_id is not None:
            payload["xc_account_id"] = self.xc_account_id
        return payload


@dataclass(frozen=True)
class HeadendarrLifecycleChannel:
    """Dispatcharr-shaped channel state for lifecycle compatibility."""

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
    channel_profile_ids: tuple[int, ...] | None = None
    guide_id: int | None = None
    guide_channel_id: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
