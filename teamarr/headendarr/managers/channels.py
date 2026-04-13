"""Channel manager for Headendarr.

Provides a Dispatcharr-shaped surface so Teamarr's existing lifecycle code can
reuse it for Headendarr-backed event channels.
"""

import logging
import threading

from teamarr.dispatcharr.types import OperationResult
from teamarr.headendarr.client import HeadendarrClient
from teamarr.headendarr.constants import HEADENDARR_TEAMARR_EPG_NAME
from teamarr.headendarr.managers.epg import EPGManager
from teamarr.headendarr.managers.playlists import PlaylistManager
from teamarr.headendarr.types import (
    HeadendarrChannelSource,
    HeadendarrLifecycleChannel,
    HeadendarrStream,
)

logger = logging.getLogger(__name__)


class ChannelCache:
    """In-memory cache for Headendarr channels."""

    def __init__(self):
        self._channels: list[HeadendarrLifecycleChannel] | None = None
        self._by_id: dict[int, HeadendarrLifecycleChannel] = {}
        self._by_tvg_id: dict[str, HeadendarrLifecycleChannel] = {}
        self._by_number: dict[str, HeadendarrLifecycleChannel] = {}

    def clear(self) -> None:
        self._channels = None
        self._by_id.clear()
        self._by_tvg_id.clear()
        self._by_number.clear()

    def is_populated(self) -> bool:
        return self._channels is not None

    def populate(self, channels: list[HeadendarrLifecycleChannel]) -> None:
        self._channels = channels
        self._by_id.clear()
        self._by_tvg_id.clear()
        self._by_number.clear()
        for channel in channels:
            self._by_id[channel.id] = channel
            if channel.tvg_id:
                self._by_tvg_id[channel.tvg_id] = channel
            if channel.channel_number:
                self._by_number[channel.channel_number] = channel

    def get_all(self) -> list[HeadendarrLifecycleChannel]:
        return self._channels or []

    def get_by_id(self, channel_id: int) -> HeadendarrLifecycleChannel | None:
        return self._by_id.get(channel_id)

    def get_by_tvg_id(self, tvg_id: str) -> HeadendarrLifecycleChannel | None:
        return self._by_tvg_id.get(tvg_id)

    def get_by_number(self, channel_number: str | int) -> HeadendarrLifecycleChannel | None:
        return self._by_number.get(str(channel_number))

    def invalidate(self, channel_id: int) -> None:
        channel = self._by_id.pop(channel_id, None)
        if channel is None:
            return
        if channel.tvg_id and channel.tvg_id in self._by_tvg_id:
            del self._by_tvg_id[channel.tvg_id]
        if channel.channel_number and channel.channel_number in self._by_number:
            del self._by_number[channel.channel_number]
        if self._channels is not None:
            self._channels = [cached for cached in self._channels if cached.id != channel_id]

    def update(self, channel: HeadendarrLifecycleChannel) -> None:
        self.invalidate(channel.id)
        self._by_id[channel.id] = channel
        if channel.tvg_id:
            self._by_tvg_id[channel.tvg_id] = channel
        if channel.channel_number:
            self._by_number[channel.channel_number] = channel
        if self._channels is not None:
            self._channels.append(channel)


class ChannelManager:
    """Create and update Headendarr channels."""

    _caches: dict[str, ChannelCache] = {}

    def __init__(self, client: HeadendarrClient, playlists: PlaylistManager, epg: EPGManager):
        self._client = client
        self._playlists = playlists
        self._epg = epg
        self._url = client._base_url
        self._lock = threading.Lock()
        self._stream_cache: dict[int, HeadendarrStream] | None = None
        self._epg_channel_ids: dict[str, int] = {}
        self._teamarr_epg_id: int | None = None

        if self._url not in self._caches:
            self._caches[self._url] = ChannelCache()

    @property
    def _cache(self) -> ChannelCache:
        return self._caches[self._url]

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
            self._stream_cache = None
            self._epg_channel_ids = {}
            self._teamarr_epg_id = None

    def _ensure_stream_cache(self) -> dict[int, HeadendarrStream]:
        if self._stream_cache is None:
            streams = self._playlists.list_streams()
            self._stream_cache = {stream.id: stream for stream in streams}
        return self._stream_cache

    def _get_teamarr_epg_id(self) -> int | None:
        if self._teamarr_epg_id is not None:
            return self._teamarr_epg_id

        source = next(
            (item for item in self._epg.list_sources() if item.name == HEADENDARR_TEAMARR_EPG_NAME),
            None,
        )
        self._teamarr_epg_id = source.id if source else None
        return self._teamarr_epg_id

    def _resolve_sources_from_stream_ids(self, stream_ids: list[int] | None) -> list[HeadendarrChannelSource]:
        if not stream_ids:
            return []

        sources: list[HeadendarrChannelSource] = []
        stream_lookup = self._ensure_stream_cache()
        for priority, stream_id in enumerate(stream_ids, start=1):
            # Ensure stream_id is treated as an integer for cache lookup
            lookup_id = int(stream_id)
            stream = stream_lookup.get(lookup_id)
            if not stream or stream.playlist_id is None:
                logger.warning("[HEADENDARR] Stream %s (int=%d) missing from playlist cache", stream_id, lookup_id)
                continue
            sources.append(
                HeadendarrChannelSource(
                    playlist_id=stream.playlist_id,
                    stream_name=stream.name,
                    stream_url=stream.url,
                    priority=priority,
                    source_type="playlist",
                    auto_update=True,
                )
            )
        return sources

    def _stream_ids_from_api_sources(self, sources: list[dict]) -> tuple[int, ...]:
        if not sources:
            return ()

        stream_lookup = self._ensure_stream_cache()
        by_pair = {
            (stream.playlist_id, (stream.name or "").strip()): stream.id
            for stream in stream_lookup.values()
            if stream.playlist_id is not None and stream.name
        }

        resolved: list[int] = []
        for source in sources:
            playlist_id = source.get("playlist_id")
            stream_name = (source.get("stream_name") or "").strip()
            if playlist_id is None or not stream_name:
                continue
            stream_id = by_pair.get((int(playlist_id), stream_name))
            if stream_id is not None:
                resolved.append(stream_id)
        return tuple(resolved)

    def _to_lifecycle_channel(self, data: dict) -> HeadendarrLifecycleChannel | None:
        if data.get("id") is None:
            return None

        guide = data.get("guide") or {}
        guide_id = guide.get("epg_id")
        guide_channel_id = guide.get("channel_id")
        tags = tuple(data.get("tags", []))
        sources = data.get("sources", [])

        return HeadendarrLifecycleChannel(
            id=int(data["id"]),
            uuid=f"headendarr-{data['id']}",
            name=data.get("name", ""),
            channel_number=str(data.get("number") or ""),
            tvg_id=guide_channel_id or None,
            logo_url=data.get("logo_url"),
            streams=self._stream_ids_from_api_sources(sources),
            guide_id=guide_id,
            guide_channel_id=guide_channel_id,
            tags=tags,
        )

    def _get_channel_config(self, channel_id: int) -> dict | None:
        response = self._client.get(f"/tic-api/channels/settings/{channel_id}")
        if response is None or response.status_code != 200:
            return None
        payload = response.json()
        data = payload.get("data")
        return data if isinstance(data, dict) else None

    def _save_channel_config(self, channel_id: int, data: dict) -> OperationResult:
        response = self._client.post(f"/tic-api/channels/settings/{channel_id}/save", data=data)
        if response is None:
            return OperationResult(success=False, error=self._client.parse_api_error(response))
        if response.status_code == 200:
            refreshed = self.get_channel(channel_id, use_cache=False)
            if refreshed:
                with self._lock:
                    self._cache.update(refreshed)
            return OperationResult(success=True)
        return OperationResult(success=False, error=self._client.parse_api_error(response))

    def _ensure_cache(self) -> list[HeadendarrLifecycleChannel]:
        if not self._cache.is_populated():
            response = self._client.get("/tic-api/channels/get")
            if response is None or response.status_code != 200:
                self._cache.populate([])
                return []
            payload = response.json()
            items = payload.get("data", [])
            channels = [
                channel
                for item in items
                if isinstance(item, dict) and (channel := self._to_lifecycle_channel(item)) is not None
            ]
            self._cache.populate(channels)
        return self._cache.get_all()

    def get_channels(self, use_cache: bool = True) -> list[HeadendarrLifecycleChannel]:
        with self._lock:
            if use_cache:
                return self._ensure_cache()

            self._cache.clear()
            return self._ensure_cache()

    def create_channel(
        self,
        name: str,
        channel_number: int,
        stream_ids: list[int] | None = None,
        tvg_id: str | None = None,
        channel_group_id: int | None = None,
        logo_id: int | None = None,
        logo_url: str | None = None,
        channel_profile_ids: list[int] | None = None,
        stream_profile_id: int | None = None,
    ) -> OperationResult:
        del channel_group_id, logo_id, channel_profile_ids, stream_profile_id

        guide_id = self._get_teamarr_epg_id()
        sources = self._resolve_sources_from_stream_ids(stream_ids)
        response = self._client.post(
            "/tic-api/channels/new",
            data={
                "enabled": True,
                "name": name,
                "logo_url": logo_url,
                "number": channel_number,
                "tags": [],
                "guide": {
                    "epg_id": guide_id,
                    "channel_id": tvg_id,
                    "offset_minutes": 0,
                }
                if guide_id and tvg_id
                else {},
                "sources": [source.to_api() for source in sources],
            },
        )
        if response is None:
            return OperationResult(success=False, error=self._client.parse_api_error(response))
        if response.status_code == 200:
            created = self.find_by_tvg_id(tvg_id) if tvg_id else self.find_channel_by_name(name)
            if not created:
                self.get_channels(use_cache=False)
                created = self.find_by_tvg_id(tvg_id) if tvg_id else self.find_channel_by_name(name)
            if created:
                with self._lock:
                    self._cache.update(created)
                return OperationResult(
                    success=True,
                    channel={"id": created.id, "uuid": created.uuid, "name": created.name},
                    data={"id": created.id, "uuid": created.uuid, "name": created.name},
                )
            return OperationResult(success=False, error="Channel created but could not be resolved from Headendarr")
        return OperationResult(success=False, error=self._client.parse_api_error(response))

    def update_channel(
        self,
        channel_id: int,
        data: dict,
    ) -> OperationResult:
        current = self._get_channel_config(channel_id)
        if current is None:
            return OperationResult(success=False, error="Channel not found")

        guide = current.get("guide") or {}
        new_tvg_id = data.get("tvg_id", guide.get("channel_id"))
        guide_id = guide.get("epg_id") or self._get_teamarr_epg_id()
        payload = {
            "enabled": True,
            "name": data.get("name", current.get("name")),
            "logo_url": data.get("logo_url", current.get("logo_url")),
            "number": data.get("channel_number", current.get("number")),
            "tags": current.get("tags", []),
            "guide": {
                "epg_id": guide_id,
                "channel_id": new_tvg_id,
                "offset_minutes": guide.get("offset_minutes", 0),
            }
            if guide_id and new_tvg_id
            else {},
            "sources": current.get("sources", []),
        }

        if "streams" in data:
            payload["sources"] = [
                source.to_api()
                for source in self._resolve_sources_from_stream_ids(data.get("streams"))
            ]

        return self._save_channel_config(channel_id, payload)

    def get_channel(
        self,
        channel_id: int,
        use_cache: bool = True,
    ) -> HeadendarrLifecycleChannel | None:
        with self._lock:
            if use_cache:
                self._ensure_cache()
                cached = self._cache.get_by_id(channel_id)
                if cached:
                    return cached

            data = self._get_channel_config(channel_id)
            if not data:
                return None
            channel = self._to_lifecycle_channel(data)
            if channel and use_cache:
                self._cache.update(channel)
            return channel

    def delete_channel(self, channel_id: int) -> OperationResult:
        response = self._client.delete(f"/tic-api/channels/settings/{channel_id}/delete")
        if response is None:
            return OperationResult(success=False, error=self._client.parse_api_error(response))
        if response.status_code == 200:
            payload = response.json()
            if payload.get("success"):
                with self._lock:
                    self._cache.invalidate(channel_id)
                return OperationResult(success=True)
        return OperationResult(success=False, error=self._client.parse_api_error(response))

    def bulk_update_profile_channels(
        self,
        profile_id: int,
        add_channel_ids: list[int] | None = None,
        remove_channel_ids: list[int] | None = None,
    ) -> OperationResult:
        del profile_id, add_channel_ids, remove_channel_ids
        return OperationResult(success=True)

    def find_by_tvg_id(self, tvg_id: str) -> HeadendarrLifecycleChannel | None:
        with self._lock:
            self._ensure_cache()
            return self._cache.get_by_tvg_id(tvg_id)

    def find_by_number(self, channel_number: int | str) -> HeadendarrLifecycleChannel | None:
        with self._lock:
            self._ensure_cache()
            return self._cache.get_by_number(str(channel_number))

    def find_channel_by_name(self, name: str) -> HeadendarrLifecycleChannel | None:
        with self._lock:
            channels = self._ensure_cache()
            for channel in channels:
                if channel.name == name:
                    return channel
        return None

    def get_epg_data_list(self, epg_source_id: int | None = None) -> list[dict]:
        response = self._client.get("/tic-api/epgs/channels")
        if response is None or response.status_code != 200:
            return []
        payload = response.json()
        items = payload.get("data", [])
        if epg_source_id is not None:
            items = [item for item in items if item.get("epg_id") == epg_source_id]
        return [item for item in items if item.get("channel_id")]

    def build_epg_lookup(self, epg_source_id: int | None = None) -> dict[str, dict]:
        epg_rows = self.get_epg_data_list(epg_source_id)
        self._epg_channel_ids = {
            str(row.get("channel_id")): int(row.get("epg_id"))
            for row in epg_rows
            if row.get("channel_id") is not None and row.get("epg_id") is not None
        }
        return {
            str(row.get("channel_id")): {
                "id": str(row.get("channel_id")),
                "epg_id": row.get("epg_id"),
                "name": row.get("name"),
            }
            for row in epg_rows
            if row.get("channel_id")
        }

    def set_channel_epg(self, channel_id: int, epg_data_id: str) -> OperationResult:
        current = self._get_channel_config(channel_id)
        if current is None:
            return OperationResult(success=False, error="Channel not found")

        guide_id = self._epg_channel_ids.get(str(epg_data_id)) or self._get_teamarr_epg_id()
        if guide_id is None:
            return OperationResult(success=False, error="EPG source not found")

        guide = current.get("guide") or {}
        payload = {
            "enabled": True,
            "name": current.get("name"),
            "logo_url": current.get("logo_url"),
            "number": current.get("number"),
            "tags": current.get("tags", []),
            "guide": {
                "epg_id": guide_id,
                "channel_id": str(epg_data_id),
                "offset_minutes": guide.get("offset_minutes", 0),
            },
            "sources": current.get("sources", []),
        }
        return self._save_channel_config(channel_id, payload)
