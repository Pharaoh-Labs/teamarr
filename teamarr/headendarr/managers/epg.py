"""EPG manager for Headendarr."""

from teamarr.headendarr.client import HeadendarrClient
from teamarr.headendarr.types import HeadendarrEPGSource


class EPGManager:
    """Manage Headendarr EPG sources."""

    def __init__(self, client: HeadendarrClient):
        self._client = client

    def list_sources(self) -> list[HeadendarrEPGSource]:
        response = self._client.get("/tic-api/epgs/get")
        if response is None or response.status_code != 200:
            return []
        payload = response.json()
        items = payload.get("data", [])
        return [HeadendarrEPGSource.from_api(item) for item in items if item.get("id") is not None]

    def get_source(self, epg_id: int) -> HeadendarrEPGSource | None:
        response = self._client.get(f"/tic-api/epgs/settings/{epg_id}")
        if response is None or response.status_code != 200:
            return None
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("id") is None:
            return None
        return HeadendarrEPGSource.from_api(data)

    def create_source(self, name: str, url: str, update_schedule: str) -> bool:
        response = self._client.post(
            "/tic-api/epgs/settings/new",
            data={
                "enabled": True,
                "name": name,
                "url": url,
                "user_agent": "",
                "update_schedule": update_schedule,
            },
        )
        return bool(response and response.status_code == 200)

    def update_source(self, epg_id: int, name: str, url: str, update_schedule: str) -> bool:
        response = self._client.post(
            f"/tic-api/epgs/settings/{epg_id}/save",
            data={
                "enabled": True,
                "name": name,
                "url": url,
                "user_agent": "",
                "update_schedule": update_schedule,
            },
        )
        return bool(response and response.status_code == 200)

    def trigger_update(self, epg_id: int) -> bool:
        response = self._client.post(f"/tic-api/epgs/update/{epg_id}")
        return bool(response and response.status_code == 200)

    def ensure_source(self, name: str, url: str, update_schedule: str, epg_id: int | None = None) -> int | None:
        source_id = epg_id
        if source_id:
            updated = self.update_source(source_id, name=name, url=url, update_schedule=update_schedule)
            return source_id if updated else None

        existing = next((source for source in self.list_sources() if source.name == name), None)
        if existing:
            updated = self.update_source(existing.id, name=name, url=url, update_schedule=update_schedule)
            return existing.id if updated else None

        if not self.create_source(name=name, url=url, update_schedule=update_schedule):
            return None

        created = next((source for source in self.list_sources() if source.name == name), None)
        return created.id if created else None
