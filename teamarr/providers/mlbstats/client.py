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
import random
import threading
import time
from datetime import date
from typing import Any

import httpx

from teamarr.utilities import call_metrics

logger = logging.getLogger(__name__)

# Environment variable configuration with defaults
# These allow users to tune connection pooling and retries for constrained environments
MLBSTATS_MAX_CONNECTIONS = int(os.environ.get("MLBSTATS_MAX_CONNECTIONS", 20))
MLBSTATS_TIMEOUT = float(os.environ.get("MLBSTATS_TIMEOUT", 15.0))
MLBSTATS_RETRY_COUNT = int(os.environ.get("MLBSTATS_RETRY_COUNT", 3))

# Retry backoff configuration
# MLB Stats API is generally reliable, so we use short delays with jitter
RETRY_BASE_DELAY = 0.5  # Start at 500ms
RETRY_MAX_DELAY = 10.0  # Cap at 10s
RETRY_JITTER = 0.3  # ±30% randomization to prevent thundering herd

# Rate limit (429) handling - reactive defense
# MLB Stats API rarely rate-limits, but we handle it gracefully if it happens
RATE_LIMIT_BASE_DELAY = 5.0  # Start at 5s for 429s
RATE_LIMIT_MAX_DELAY = 60.0  # Cap at 60s
RATE_LIMIT_MAX_RETRIES = 3  # Give up after 3 rate-limit retries


class MLBStatsClient:
    """Low-level MLB Stats API client.

    Connection pool is configured to maximize keepalive connections, reducing
    repeated connection setup and improving throughput during cache refreshes.

    All settings can be tuned via environment variables for constrained environments.
    """

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
                # Double-check after acquiring lock
                if self._client is None:
                    # Set keepalive = max_connections to maximize connection reuse
                    self._client = httpx.Client(
                        timeout=self._timeout,
                        limits=httpx.Limits(
                            max_connections=self._max_connections,
                            max_keepalive_connections=self._max_connections,
                        ),
                    )
        return self._client

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff and jitter.

        MLB Stats-tuned: short base delay since the API is generally reliable,
        with jitter to prevent thundering herd when multiple
        parallel requests retry simultaneously.

        Args:
            attempt: Zero-based attempt number (0, 1, 2...)

        Returns:
            Delay in seconds with jitter applied
        """
        # Exponential backoff: 0.5, 1, 2, 4... capped at 10s
        base_delay = RETRY_BASE_DELAY * (2**attempt)
        capped = min(base_delay, RETRY_MAX_DELAY)
        # Add jitter: ±30% randomization
        jitter = capped * RETRY_JITTER * (2 * random.random() - 1)
        return max(0.1, capped + jitter)  # Minimum 100ms

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Make HTTP request with retry logic.

        Uses exponential backoff with jitter for resilience against
        transient failures. Handles 429 rate limits
        with longer backoff and Retry-After header support.
        """
        url = f"{self.BASE_URL}{path}"
        rate_limit_retries = 0

        for attempt in range(self._retry_count + RATE_LIMIT_MAX_RETRIES):
            try:
                client = self._get_client()
                response = client.get(url, params=params)

                # Handle 429 rate limit separately with longer backoff
                if response.status_code == 429:
                    rate_limit_retries += 1
                    if rate_limit_retries > RATE_LIMIT_MAX_RETRIES:
                        logger.error(
                            "[MLBSTATS] Rate limit (429) persisted after %d retries for %s",
                            RATE_LIMIT_MAX_RETRIES,
                            url,
                        )
                        return None

                    # Respect Retry-After header if present
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            delay = min(float(retry_after), RATE_LIMIT_MAX_DELAY)
                        except ValueError:
                            delay = RATE_LIMIT_BASE_DELAY * (2 ** (rate_limit_retries - 1))
                    else:
                        delay = min(
                            RATE_LIMIT_BASE_DELAY * (2 ** (rate_limit_retries - 1)),
                            RATE_LIMIT_MAX_DELAY,
                        )

                    logger.warning(
                        "[MLBSTATS] Rate limited (429). Retry %d/%d in %.1fs for %s",
                        rate_limit_retries,
                        RATE_LIMIT_MAX_RETRIES,
                        delay,
                        url,
                    )
                    time.sleep(delay)
                    continue

                response.raise_for_status()
                logger.debug("[FETCH] %s", path)
                call_metrics.record_call("mlbstats", path)
                return response.json()

            except httpx.HTTPStatusError as e:
                logger.warning("[MLBSTATS] HTTP %d for %s", e.response.status_code, url)
                if attempt < self._retry_count - 1:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay)
                    continue
                return None
            except (httpx.RequestError, RuntimeError, OSError) as e:
                # RuntimeError: "Cannot send a request, as the client has been closed"
                # OSError: stale connection / bad file descriptor edge cases
                # httpx.RequestError: DNS failures, connection refused, etc.
                logger.warning("[MLBSTATS] Request failed for %s: %s", url, e)
                # Don't reset client here - avoids race conditions in parallel processing
                # httpx connection pool handles stale connections automatically
                if attempt < self._retry_count - 1:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay)
                    continue
                return None

        return None

    def _reset_client(self) -> None:
        """Reset the HTTP client to clear stale connections."""
        with self._lock:
            if self._client:
                try:
                    self._client.close()
                except Exception as e:
                    logger.debug("[MLBSTATS] Error closing HTTP client: %s", e)
                self._client = None

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
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None
