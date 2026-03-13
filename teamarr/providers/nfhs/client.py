"""NFHS Network API HTTP client.

Handles raw HTTP requests to NFHS endpoints.
No data transformation - just fetch and return JSON.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any

import httpx

from teamarr.providers.nfhs.config import (
    EVENT_PAGE_SIZE,
    MAX_CONNECTIONS,
    MAX_PAGES,
    REQUEST_TIMEOUT,
    RETRY_COUNT,
    SEARCH_API_BASE,
    USER_AGENT,
    CFUNITY_API_BASE,
)

logger = logging.getLogger(__name__)

RETRY_BASE_DELAY = 0.5
RETRY_MAX_DELAY = 10.0
RETRY_JITTER = 0.3

RATE_LIMIT_BASE_DELAY = 5.0
RATE_LIMIT_MAX_DELAY = 60.0
RATE_LIMIT_MAX_RETRIES = 3


class NFHSClient:
    """Low-level NFHS API client."""

    def __init__(self, timeout: float | None = None):
        self._timeout = timeout if timeout is not None else REQUEST_TIMEOUT
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = httpx.Client(
                        timeout=self._timeout,
                        headers={
                            "User-Agent": USER_AGENT,
                            "Accept": "application/json",
                        },
                        limits=httpx.Limits(
                            max_connections=MAX_CONNECTIONS,
                            max_keepalive_connections=MAX_CONNECTIONS,
                        ),
                    )
        return self._client

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff and jitter."""
        base_delay = RETRY_BASE_DELAY * (2**attempt)
        capped = min(base_delay, RETRY_MAX_DELAY)
        jitter = capped * RETRY_JITTER * (2 * random.random() - 1)
        return max(0.1, capped + jitter)

    def _request(self, base_url: str, path: str, params: dict[str, Any] | None = None) -> Any:
        """Make HTTP request with retry logic."""
        url = f"{base_url}{path}"
        rate_limit_retries = 0

        for attempt in range(RETRY_COUNT):
            try:
                client = self._get_client()
                response = client.get(url, params=params)

                if response.status_code == 429:
                    rate_limit_retries += 1
                    if rate_limit_retries > RATE_LIMIT_MAX_RETRIES:
                        logger.error(
                            "[NFHS] Rate limit (429) persisted after %d retries for %s",
                            RATE_LIMIT_MAX_RETRIES,
                            url,
                        )
                        return {}

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
                        "[NFHS] Rate limited (429). Retry %d/%d in %.1fs for %s",
                        rate_limit_retries,
                        RATE_LIMIT_MAX_RETRIES,
                        delay,
                        url,
                    )
                    time.sleep(delay)
                    response = client.get(url, params=params)
                    if response.status_code == 429:
                        continue
                    response.raise_for_status()
                    logger.debug("[FETCH] %s params=%s", url, params)
                    return response.json()

                response.raise_for_status()
                logger.debug("[FETCH] %s params=%s", url, params)
                return response.json()

            except httpx.HTTPStatusError as e:
                logger.warning("[NFHS] HTTP %d for %s", e.response.status_code, url)
                if attempt < RETRY_COUNT - 1:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay)
                    continue
                return {}
            except (httpx.RequestError, RuntimeError, OSError) as e:
                logger.warning("[NFHS] Request failed for %s: %s", url, e)
                if attempt < RETRY_COUNT - 1:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay)
                    continue
                self._reset_client()
                return {}

        return {}

    def _reset_client(self) -> None:
        """Reset the HTTP client to clear stale connections."""
        with self._lock:
            if self._client:
                try:
                    self._client.close()
                except Exception as e:
                    logger.debug("[NFHS] Error closing HTTP client: %s", e)
                self._client = None

    def _get_paginated(
        self,
        path: str,
        *,
        base_url: str = SEARCH_API_BASE,
        size: int = EVENT_PAGE_SIZE,
        max_pages: int = MAX_PAGES,
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch paginated NFHS search results using cursor pagination."""
        items: list[dict[str, Any]] = []
        cursor = ""

        for page in range(max_pages):
            params: dict[str, Any] = {"size": size}
            if cursor:
                params["cursor"] = cursor
            if extra_params:
                params.update(extra_params)

            data = self._request(base_url, path, params)
            if not isinstance(data, dict):
                logger.warning("[NFHS] Unexpected paginated payload type for %s: %s", path, type(data).__name__)
                break

            page_items = data.get("items", [])
            if not page_items:
                logger.info("[NFHS] No more items for %s after page %d", path, page + 1)
                break

            items.extend(page_items)
            logger.debug(
                "[NFHS] Loaded %d items from %s page=%d total=%d",
                len(page_items),
                path,
                page + 1,
                len(items),
            )

            cursor = data.get("cursor") or ""
            if not cursor:
                break

            logger.debug("[NFHS] Continuing pagination for %s with cursor=%s", path, cursor)

        return items

    def get_activities(self) -> list[dict[str, Any]]:
        """Retrieve NFHS activities/sports metadata."""
        data = self._request(CFUNITY_API_BASE, "/activities")
        if isinstance(data, list):
            logger.info("[NFHS] Loaded %d activities", len(data))
            return data
        logger.warning("[NFHS] Activities endpoint returned unexpected payload")
        return []

    def get_teams(self, size: int = EVENT_PAGE_SIZE, max_pages: int = MAX_PAGES) -> list[dict[str, Any]]:
        """Retrieve teams from the NFHS search endpoint."""
        return self._get_paginated("/search/teams", size=size, max_pages=max_pages)

    def get_schools_for_state(self, state_code: str) -> list[dict[str, Any]]:
        """Retrieve all schools for a specific state using the NFHS search endpoint."""

        # First request to determine total number of schools
        probe = self._request(
            SEARCH_API_BASE,
            "/search/schools",
            params={"state": state_code},
        )

        if not isinstance(probe, dict):
            logger.warning("[NFHS] Unexpected schools payload for state=%s", state_code)
            return []

        total = probe.get("total", 0)
        if not total:
            logger.info("[NFHS] No schools found for state=%s", state_code)
            return []

        logger.info("[NFHS] Discovering %s schools for state=%s", total, state_code)

        one_shot_cap = 1000
        one_shot_size = min(total, one_shot_cap)

        if total > one_shot_cap:
            logger.info(
                "[NFHS] State=%s has %s schools, exceeding one-shot cap=%s; using pagination",
                state_code,
                total,
                one_shot_cap,
            )
            return self._get_paginated(
                "/search/schools",
                size=EVENT_PAGE_SIZE,
                max_pages=MAX_PAGES,
                extra_params={
                    "state": state_code,
                    "sort": "school_name+asc",
                    "start": 0,
                },
            )

        # Second request to fetch all schools in a single call
        params = {
            "state": state_code,
            "sort": "school_name+asc",
            "size": one_shot_size,
            "start": 0,
        }

        data = self._request(SEARCH_API_BASE, "/search/schools", params=params)

        if not isinstance(data, dict):
            logger.warning("[NFHS] Unexpected schools payload for state=%s, falling back to pagination", state_code)
            return self._get_paginated(
                "/search/schools",
                size=EVENT_PAGE_SIZE,
                max_pages=MAX_PAGES,
                extra_params={
                    "state": state_code,
                    "sort": "school_name+asc",
                    "start": 0,
                },
            )

        items = data.get("items", [])
        if not items or len(items) < total:
            logger.warning(
                "[NFHS] One-shot school fetch for state=%s returned %d/%d items; falling back to pagination",
                state_code,
                len(items),
                total,
            )
            return self._get_paginated(
                "/search/schools",
                size=EVENT_PAGE_SIZE,
                max_pages=MAX_PAGES,
                extra_params={
                    "state": state_code,
                    "sort": "school_name+asc",
                    "start": 0,
                },
            )

        logger.debug("[NFHS] Loaded %d schools for state=%s", len(items), state_code)

        return items

    def get_school_teams(self, school_key: str, level: str | None = None) -> list[dict[str, Any]]:
        """Retrieve team records for a specific school from NFHS SEARCH v3."""
        # SEARCH v3 does not support server-side level filtering; provider-side
        # filtering and deduplication happen after fetching all rows for a school.
        data = self._request(
            SEARCH_API_BASE,
            "/search/teams",
            params={
                "school_key": school_key,
            },
        )

        if isinstance(data, list):
            logger.debug(
                "[NFHS] Loaded %d SEARCH team rows for school_key=%s",
                len(data),
                school_key,
            )
            return data

        if isinstance(data, dict):
            for key in ("results", "items", "data"):
                rows = data.get(key)
                if isinstance(rows, list):
                    logger.debug(
                        "[NFHS] Loaded %d SEARCH team rows for school_key=%s via %s",
                        len(rows),
                        school_key,
                        key,
                    )
                    return rows

        logger.warning(
            "[NFHS] Unexpected SEARCH teams payload for school_key=%s",
            school_key,
        )
        return []

    def get_school_details(self, school_key: str) -> dict[str, Any]:
        """Compatibility stub: sport inventory now comes from SEARCH v3 team rows."""
        # Kept for compatibility with older callers; provider discovery now uses
        # SEARCH v3 team rows instead of CFUNITY school detail payloads.
        return {}

    def get_upcoming_events(self, size: int = EVENT_PAGE_SIZE, max_pages: int = MAX_PAGES) -> list[dict[str, Any]]:
        """Retrieve upcoming NFHS events."""
        return self._get_paginated("/search/events/upcoming", size=size, max_pages=max_pages)

    def get_live_events(self, size: int = EVENT_PAGE_SIZE, max_pages: int = MAX_PAGES) -> list[dict[str, Any]]:
        """Retrieve currently live NFHS events."""
        return self._get_paginated("/search/events/live", size=size, max_pages=max_pages)

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None