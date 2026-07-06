"""MLB Stats API HTTP client.

Handles raw HTTP requests to MLB Stats API endpoints.
No data transformation - just fetch and return JSON.

Configuration via environment variables:
    MLBSTATS_MAX_CONNECTIONS: Max concurrent connections (default: 20)
    MLBSTATS_TIMEOUT: Request timeout in seconds (default: 15)
    MLBSTATS_RETRY_COUNT: Number of retry attempts (default: 3)
"""
import logging
import os
from datetime import date
from typing import Any

from teamarr.providers.base_client import BaseHTTPClient

logger = logging.getLogger(__name__)

# Environment variable configuration with defaults
# These allow users to tune connection pooling and retries for constrained environments
MLBSTATS_MAX_CONNECTIONS = int(os.environ.get("MLBSTATS_MAX_CONNECTIONS", 20))
MLBSTATS_TIMEOUT = float(os.environ.get("MLBSTATS_TIMEOUT", 15.0))
MLBSTATS_RETRY_COUNT = int(os.environ.get("MLBSTATS_RETRY_COUNT", 3))


class MLBStatsClient(BaseHTTPClient):
    """Low-level MLB Stats API client.

    HTTP plumbing (pooled client, retry/backoff, 429 handling) comes from
    BaseHTTPClient. All settings can be tuned via environment variables for
    constrained environments.
    """

    PROVIDER = "mlbstats"
    LOG_TAG = "MLBSTATS"

    BASE_URL = "https://statsapi.mlb.com/api/v1"

    def __init__(
        self,
        timeout: float | None = None,
        retry_count: int | None = None,
        max_connections: int | None = None,
    ):
        super().__init__(
            timeout=timeout if timeout is not None else MLBSTATS_TIMEOUT,
            retry_count=retry_count if retry_count is not None else MLBSTATS_RETRY_COUNT,
            max_connections=(
                max_connections if max_connections is not None else MLBSTATS_MAX_CONNECTIONS
            ),
        )

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self._request_json(f"{self.BASE_URL}{path}", params, label=path)

    def get_sports(self) -> dict[str, Any] | None:
        return self._request("/sports")

    def get_teams(self, sport_id: str) -> dict[str, Any] | None:
        return self._request("/teams", {"sportId": sport_id})

    def get_team(self, team_id: str) -> dict[str, Any] | None:
        return self._request(f"/teams/{team_id}")

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
        return self._request("/schedule", params)

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
        return self._request("/schedule", params)
