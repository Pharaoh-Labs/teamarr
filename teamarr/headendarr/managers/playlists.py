"""Playlist manager for Headendarr."""

from teamarr.headendarr.client import HeadendarrClient
from teamarr.headendarr.types import HeadendarrPlaylist, HeadendarrStream


class PlaylistManager:
    """Read playlist and stream inventory from Headendarr."""

    def __init__(self, client: HeadendarrClient):
        self._client = client

    def list_playlists(self) -> list[HeadendarrPlaylist]:
        response = self._client.get("/tic-api/playlists/get")
        if response is None or response.status_code != 200:
            return []
        payload = response.json()
        items = payload.get("data", [])
        return [HeadendarrPlaylist.from_api(item) for item in items if item.get("id") is not None]

    def list_streams(self) -> list[HeadendarrStream]:
        response = self._client.get("/tic-api/playlists/streams/all")
        if response is None or response.status_code != 200:
            return []
        payload = response.json()
        data = payload.get("data", {})
        if isinstance(data, dict):
            items = data.get("streams", [])
        elif isinstance(data, list):
            items = data
        else:
            items = []
        return [HeadendarrStream.from_api(item) for item in items if item.get("id") is not None]

    def search_streams(
        self,
        playlist_id: int,
        search_value: str = "",
        group_title: str | None = None,
        start: int = 0,
        length: int = 100,
    ) -> list[HeadendarrStream]:
        response = self._client.post(
            "/tic-api/playlists/streams",
            data={
                "start": start,
                "length": length,
                "search_value": search_value,
                "order_by": "name",
                "order_direction": "asc",
                "playlist_id": playlist_id,
                "group_title": group_title,
            },
        )
        if response is None or response.status_code != 200:
            return []
        payload = response.json()
        data = payload.get("data", {})
        if isinstance(data, dict):
            items = data.get("data") or data.get("streams") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []
        return [HeadendarrStream.from_api(item) for item in items if item.get("id") is not None]
