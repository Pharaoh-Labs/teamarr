import logging
import threading
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class MLBStatsClient:
    BASE_URL = "https://statsapi.mlb.com/api/v1"

    def __init__(self, timeout: float = 15.0):
        self._timeout = timeout
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = httpx.Client(
                        timeout=self._timeout,
                        limits=httpx.Limits(
                            max_connections=20,
                            max_keepalive_connections=20,
                        ),
                    )
        return self._client

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        url = f"{self.BASE_URL}{path}"
        try:
            client = self._get_client()
            resp = client.get(url, params=params or {})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "[MLBSTATS] HTTP %s for %s params=%s",
                exc.response.status_code,
                url,
                params,
            )
            return None
        except (httpx.RequestError, RuntimeError, OSError) as exc:
            logger.warning("[MLBSTATS] GET %s params=%s failed: %s", url, params, exc)
            return None

    def get_sports(self) -> dict[str, Any] | None:
        return self._get("/sports")

    def get_teams(self, sport_id: str) -> dict[str, Any] | None:
        return self._get("/teams", params={"sportId": sport_id})

    def get_team(self, team_id: str) -> dict[str, Any] | None:
        return self._get(f"/teams/{team_id}")

    def get_schedule(
        self,
        sport_id: str,
        target_date: date,
        team_id: str | None = None,
    ) -> dict[str, Any] | None:
        params: dict[str, Any] = {
            "sportId": sport_id,
            "date": target_date.strftime("%Y-%m-%d"),
            "hydrate": "teams,venue",
        }
        if team_id:
            params["teamId"] = team_id
        return self._get("/schedule", params=params)

    def get_schedule_range(
        self,
        sport_id: str,
        start_date: date,
        end_date: date,
        team_id: str | None = None,
    ) -> dict[str, Any] | None:
        params: dict[str, Any] = {
            "sportId": sport_id,
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "hydrate": "teams,venue",
        }
        if team_id:
            params["teamId"] = team_id
        return self._get("/schedule", params=params)

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None