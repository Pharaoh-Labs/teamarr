import logging
import os
import random
import threading
import time
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Environment variable configuration with defaults
MLBSTATS_MAX_CONNECTIONS = int(os.environ.get("MLBSTATS_MAX_CONNECTIONS", 20))
MLBSTATS_TIMEOUT = float(os.environ.get("MLBSTATS_TIMEOUT", 15.0))
MLBSTATS_RETRY_COUNT = int(os.environ.get("MLBSTATS_RETRY_COUNT", 3))

# Retry backoff configuration
RETRY_BASE_DELAY = 0.5
RETRY_MAX_DELAY = 10.0
RETRY_JITTER = 0.3


class MLBStatsClient:
    BASE_URL = "https://statsapi.mlb.com/api/v1"

    def __init__(
        self,
        timeout: float | None = None,
        retry_count: int | None = None,
        max_connections: int | None = None,
    ):
        self._timeout = timeout if timeout is not None else MLBSTATS_TIMEOUT
        self._retry_count = retry_count if retry_count is not None else MLBSTATS_RETRY_COUNT
        self._max_connections = (
            max_connections if max_connections is not None else MLBSTATS_MAX_CONNECTIONS
        )
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = httpx.Client(
                        timeout=self._timeout,
                        limits=httpx.Limits(
                            max_connections=self._max_connections,
                            max_keepalive_connections=self._max_connections,
                        ),
                    )
        return self._client

    def _calculate_delay(self, attempt: int) -> float:
        base_delay = RETRY_BASE_DELAY * (2**attempt)
        capped = min(base_delay, RETRY_MAX_DELAY)
        jitter = capped * RETRY_JITTER * (2 * random.random() - 1)
        return max(0.1, capped + jitter)

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        url = f"{self.BASE_URL}{path}"

        for attempt in range(self._retry_count):
            try:
                client = self._get_client()
                response = client.get(url, params=params or {})
                response.raise_for_status()
                logger.debug("[MLBSTATS] FETCH %s params=%s", path, params)
                return response.json()
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "[MLBSTATS] HTTP %s for %s params=%s",
                    exc.response.status_code,
                    url,
                    params,
                )
                if attempt < self._retry_count - 1:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay)
                    continue
                return None
            except (httpx.RequestError, RuntimeError, OSError) as exc:
                logger.warning("[MLBSTATS] Request failed for %s params=%s: %s", url, params, exc)
                if attempt < self._retry_count - 1:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay)
                    continue
                return None

        return None

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

    def close(self) -> None:
        if self._client:
            self._client.close()
            self._client = None