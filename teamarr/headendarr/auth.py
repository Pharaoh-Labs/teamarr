"""Authentication helpers for Headendarr API."""

import logging
import threading
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)


class TokenManager:
    """Bearer-token authentication for Headendarr."""

    TOKEN_REFRESH_BUFFER_MINUTES = 1
    TOKEN_VALIDITY_MINUTES = 5

    def __init__(self, base_url: str, username: str, password: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout = timeout
        self._token: str | None = None
        self._token_expiry: datetime | None = None
        self._lock = threading.Lock()

    def clear(self) -> None:
        """Clear cached token."""
        with self._lock:
            self._token = None
            self._token_expiry = None

    def _is_valid(self) -> bool:
        if not self._token or not self._token_expiry:
            return False
        return datetime.now() < self._token_expiry

    def get_token(self) -> str | None:
        """Get a bearer token, authenticating if needed."""
        with self._lock:
            if self._is_valid():
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
            self._token_expiry = datetime.now() + timedelta(
                minutes=self.TOKEN_VALIDITY_MINUTES - self.TOKEN_REFRESH_BUFFER_MINUTES
            )
            return token
