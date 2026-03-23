"""Base HTTP client for Headendarr API."""

import logging
import random
import time

import httpx

from teamarr.headendarr.auth import TokenManager

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {502, 503, 504}


def _calculate_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 32.0) -> float:
    delay = min(max_delay, base_delay * (2**attempt))
    return delay * random.uniform(0.5, 1.5)


class HeadendarrClient:
    """Authenticated client for Headendarr."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: float = 30.0,
        max_retries: int = 5,
    ):
        self._base_url = base_url.rstrip("/")
        self._auth = TokenManager(base_url, username, password, timeout)
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
        return self._client

    def request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        params: dict | None = None,
        retry_on_401: bool = True,
    ) -> httpx.Response | None:
        token = self._auth.get_token()
        if not token:
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        full_url = f"{self._base_url}{endpoint}"
        client = self._get_client()
        last_exception: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = client.request(
                    method.upper(),
                    full_url,
                    headers=headers,
                    json=data,
                    params=params,
                )
                if response.status_code == 401 and retry_on_401:
                    self._auth.clear()
                    return self.request(
                        method=method,
                        endpoint=endpoint,
                        data=data,
                        params=params,
                        retry_on_401=False,
                    )
                if response.status_code in RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                    delay = _calculate_backoff(attempt)
                    logger.warning(
                        "[HEADENDARR] Retryable HTTP %d for %s %s, retry %d/%d after %.1fs",
                        response.status_code,
                        method.upper(),
                        endpoint,
                        attempt + 1,
                        self._max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                return response
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exception = exc
                if attempt < self._max_retries:
                    delay = _calculate_backoff(attempt)
                    logger.warning(
                        "[HEADENDARR] Retryable error for %s %s: %s, retry %d/%d after %.1fs",
                        method.upper(),
                        endpoint,
                        type(exc).__name__,
                        attempt + 1,
                        self._max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                logger.error("[HEADENDARR] Max retries exceeded for %s %s", method.upper(), endpoint)
            except httpx.RequestError as exc:
                logger.error("[HEADENDARR] Request failed: %s", exc)
                return None

        if last_exception:
            logger.error("[HEADENDARR] Request failed after retries: %s", last_exception)
        return None

    def get(self, endpoint: str, params: dict | None = None) -> httpx.Response | None:
        return self.request("GET", endpoint, params=params)

    def post(self, endpoint: str, data: dict | None = None) -> httpx.Response | None:
        return self.request("POST", endpoint, data=data)

    def delete(self, endpoint: str) -> httpx.Response | None:
        return self.request("DELETE", endpoint)

    @staticmethod
    def parse_api_error(response: httpx.Response | None) -> str:
        if response is None:
            return "No response from Headendarr"
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            return payload.get("message") or payload.get("error") or response.text
        return response.text

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "HeadendarrClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
