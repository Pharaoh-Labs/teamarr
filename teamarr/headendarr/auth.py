"""Authentication helpers for Headendarr API."""

import logging

import httpx

logger = logging.getLogger(__name__)


class TokenManager:
    """Bearer-token authentication for Headendarr."""

    def __init__(self, base_url: str, username: str, password: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout = timeout
        self._token: str | None = None

    def clear(self) -> None:
        """Clear cached token."""
        self._token = None

    def get_token(self) -> str | None:
        """Get a bearer token, authenticating if needed."""
        if self._token:
            return self._token

        try:
            response = httpx.post(
                f"{self._base_url}/tic-api/auth/login",
                json={"username": self._username, "password": self._password},
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.error("[HEADENDARR] Authentication failed: %s", exc)
            return None

        token = data.get("token")
        if not token:
            logger.error("[HEADENDARR] Authentication response did not include a token")
            return None

        self._token = token
        return token
