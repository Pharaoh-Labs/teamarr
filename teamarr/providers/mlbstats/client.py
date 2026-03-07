import logging
from datetime import date
from typing import Any

import requests

logger = logging.getLogger(__name__)


class MLBStatsClient:
    BASE_URL = "https://statsapi.mlb.com/api/v1"

    def __init__(self, session: requests.Session | None = None, timeout: int = 15):
        self._session = session or requests.Session()
        self._timeout = timeout

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        url = f"{self.BASE_URL}{path}"
        try:
            resp = self._session.get(url, params=params or {}, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
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