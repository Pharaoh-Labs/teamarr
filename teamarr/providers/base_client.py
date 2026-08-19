"""Shared HTTP plumbing for provider API clients.

Every provider client needs the same things: a lazily-created, thread-safe,
connection-pooled ``httpx.Client``; a retry loop with exponential backoff and
jitter; and reactive 429 handling with Retry-After support. Before this base
class existed each client re-implemented that stack (espn and mlbstats were
byte-identical; hockeytech/squiggle had weaker copies with no backoff).

Subclasses set ``PROVIDER`` (call_metrics key) and ``LOG_TAG`` (log prefix),
then either:

- call ``_request_json(url, params, label=...)`` for the full
  retry + 429 loop returning parsed JSON, or
- call ``_get_client()`` directly and keep a custom request loop when they
  need special handling (tsdb's sliding-window rate limiter, supabase's
  raw-Response returns).

Connection pools maximize keepalive connections to reduce DNS lookups,
which helps users with rate-limited DNS (PiHole, AdGuard).
"""

import logging
import random
import threading
import time

import httpx

from teamarr.utilities import call_metrics

logger = logging.getLogger(__name__)

# Retry backoff configuration
# Provider APIs are generally fast and reliable, so short delays with jitter
RETRY_BASE_DELAY = 0.5  # Start at 500ms
RETRY_MAX_DELAY = 10.0  # Cap at 10s
RETRY_JITTER = 0.3  # ±30% randomization to prevent thundering herd

# Rate limit (429) handling - reactive defense
RATE_LIMIT_BASE_DELAY = 5.0  # Start at 5s for 429s (more serious)
RATE_LIMIT_MAX_DELAY = 60.0  # Cap at 60s
RATE_LIMIT_MAX_RETRIES = 3  # Give up after 3 rate-limit retries


class BaseHTTPClient:
    """Thread-safe pooled HTTP client with retry, backoff, and 429 handling."""

    PROVIDER = "http"  # call_metrics provider key
    LOG_TAG = "HTTP"  # prefix for log messages

    def __init__(
        self,
        timeout: float = 10.0,
        retry_count: int = 3,
        max_connections: int = 100,
        max_keepalive_connections: int | None = None,
        headers: dict[str, str] | None = None,
    ):
        self._timeout = timeout
        self._retry_count = retry_count
        self._max_connections = max_connections
        # Default keepalive = max_connections to maximize connection reuse
        self._max_keepalive = (
            max_keepalive_connections
            if max_keepalive_connections is not None
            else max_connections
        )
        self._headers = headers
        self._client: httpx.Client | None = None
        self._client_lock = threading.Lock()

    def _get_client(self) -> httpx.Client:
        """Get or create the pooled HTTP client (thread-safe)."""
        if self._client is None:
            with self._client_lock:
                # Double-check after acquiring lock
                if self._client is None:
                    self._client = httpx.Client(
                        timeout=self._timeout,
                        limits=httpx.Limits(
                            max_connections=self._max_connections,
                            max_keepalive_connections=self._max_keepalive,
                        ),
                        headers=self._headers,
                    )
        return self._client

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff and jitter.

        Args:
            attempt: Zero-based attempt number (0, 1, 2...)

        Returns:
            Delay in seconds with jitter applied (minimum 100ms)
        """
        # Exponential backoff: 0.5, 1, 2, 4... capped at 10s
        base_delay = RETRY_BASE_DELAY * (2**attempt)
        capped = min(base_delay, RETRY_MAX_DELAY)
        # Add jitter: ±30% randomization
        jitter = capped * RETRY_JITTER * (2 * random.random() - 1)
        return max(0.1, capped + jitter)

    def _request_json(
        self,
        url: str,
        params: dict | None = None,
        *,
        label: str | None = None,
    ) -> dict | None:
        """Make a GET request with retry logic, returning parsed JSON or None.

        Uses exponential backoff with jitter for resilience against transient
        failures and DNS throttling. Handles 429 rate limits with longer
        backoff and Retry-After header support.

        Args:
            url: Full URL to request
            params: Optional query parameters
            label: Short label for logs/metrics (defaults to the URL;
                call_metrics reduces either form to the last path segment)
        """
        label = label if label is not None else url
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
                            "[%s] Rate limit (429) persisted after %d retries for %s",
                            self.LOG_TAG,
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
                        "[%s] Rate limited (429). Retry %d/%d in %.1fs for %s",
                        self.LOG_TAG,
                        rate_limit_retries,
                        RATE_LIMIT_MAX_RETRIES,
                        delay,
                        url,
                    )
                    time.sleep(delay)
                    continue

                response.raise_for_status()
                logger.debug("[FETCH] %s", label)
                call_metrics.record_call(self.PROVIDER, label)
                return response.json()

            except httpx.HTTPStatusError as e:
                logger.warning(
                    "[%s] HTTP %d for %s", self.LOG_TAG, e.response.status_code, url
                )
                # 4xx is deterministic (429 is handled before raise_for_status),
                # so retrying just repeats the identical failure — only 5xx gets
                # the retry/backoff treatment (#282).
                if e.response.status_code < 500:
                    return None
                if attempt < self._retry_count - 1:
                    time.sleep(self._calculate_delay(attempt))
                    continue
                return None
            except (httpx.RequestError, RuntimeError, OSError) as e:
                # RuntimeError: "Cannot send a request, as the client has been closed"
                # OSError: "Bad file descriptor" from stale connections
                # httpx.RequestError: DNS failures, connection refused, etc.
                logger.warning("[%s] Request failed for %s: %s", self.LOG_TAG, url, e)
                # Don't reset client here - causes race conditions in parallel
                # processing; the httpx pool handles stale connections itself
                if attempt < self._retry_count - 1:
                    time.sleep(self._calculate_delay(attempt))
                    continue
                return None

        return None

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None
