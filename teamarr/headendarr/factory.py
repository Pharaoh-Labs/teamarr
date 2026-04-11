"""Headendarr client factory."""

import logging
import threading
from dataclasses import dataclass
from typing import Any

from teamarr.headendarr.client import HeadendarrClient
from teamarr.headendarr.managers.channels import ChannelManager
from teamarr.headendarr.managers.epg import EPGManager
from teamarr.headendarr.managers.playlists import PlaylistManager

logger = logging.getLogger(__name__)


@dataclass
class HeadendarrConnection:
    """Container for Headendarr client and managers."""

    client: HeadendarrClient
    channels: ChannelManager
    epg: EPGManager
    playlists: PlaylistManager

    def close(self) -> None:
        self.client.close()


@dataclass
class ConnectionTestResult:
    """Result for testing Headendarr connectivity."""

    success: bool
    url: str | None = None
    username: str | None = None
    version: str | None = None
    playlist_count: int | None = None
    epg_count: int | None = None
    error: str | None = None


class HeadendarrFactory:
    """Factory for creating and reusing Headendarr connections."""

    def __init__(self, db_factory: Any):
        self._db_factory = db_factory
        self._connection: HeadendarrConnection | None = None
        self._lock = threading.Lock()
        self._settings_hash: str | None = None

    @property
    def is_configured(self) -> bool:
        from teamarr.database.settings import get_headendarr_settings

        with self._db_factory() as conn:
            settings = get_headendarr_settings(conn)
        return bool(settings.enabled and settings.url and settings.username)

    def _get_settings_hash(self) -> str:
        from teamarr.database.settings import get_headendarr_settings

        with self._db_factory() as conn:
            settings = get_headendarr_settings(conn)
        return "|".join(
            [
                str(settings.enabled),
                settings.url or "",
                settings.username or "",
                settings.password or "",
            ]
        )

    def _create_connection(self) -> HeadendarrConnection:
        from teamarr.database.settings import get_all_settings, get_headendarr_settings

        with self._db_factory() as conn:
            settings = get_headendarr_settings(conn)
            api_settings = get_all_settings(conn).api

        client = HeadendarrClient(
            base_url=settings.url or "",
            username=settings.username or "",
            password=settings.password or "",
            timeout=float(api_settings.timeout),
            max_retries=api_settings.retry_count,
        )
        playlists = PlaylistManager(client)
        epg = EPGManager(client)
        return HeadendarrConnection(
            client=client,
            playlists=playlists,
            epg=epg,
            channels=ChannelManager(client, playlists=playlists, epg=epg),
        )

    def _close_connection(self) -> None:
        if self._connection:
            self._connection.close()
            self._connection = None

    def get_connection(self) -> HeadendarrConnection | None:
        if not self.is_configured:
            return None

        with self._lock:
            current_hash = self._get_settings_hash()
            if self._connection and self._settings_hash != current_hash:
                self._close_connection()
            if not self._connection:
                self._connection = self._create_connection()
                self._settings_hash = current_hash
            return self._connection

    def reconnect(self) -> HeadendarrConnection | None:
        with self._lock:
            self._close_connection()
            self._settings_hash = None
        return self.get_connection()

    def test_connection(
        self,
        url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> ConnectionTestResult:
        from teamarr.database.settings import get_all_settings, get_headendarr_settings

        if url and username and password:
            test_url = url
            test_username = username
            test_password = password
            with self._db_factory() as conn:
                api_settings = get_all_settings(conn).api
        else:
            with self._db_factory() as conn:
                settings = get_headendarr_settings(conn)
                api_settings = get_all_settings(conn).api
            if not settings.url or not settings.username:
                return ConnectionTestResult(success=False, error="Headendarr not configured")
            test_url = url or settings.url
            test_username = username or settings.username
            test_password = password or settings.password or ""

        try:
            client = HeadendarrClient(
                base_url=test_url,
                username=test_username,
                password=test_password,
                timeout=float(api_settings.timeout),
                max_retries=api_settings.retry_count,
            )
            playlists_response = client.get("/tic-api/playlists/get")
            if playlists_response is None:
                client.close()
                return ConnectionTestResult(
                    success=False,
                    url=test_url,
                    username=test_username,
                    error="Authentication failed or server unavailable",
                )
            if playlists_response.status_code != 200:
                error_msg = client.parse_api_error(playlists_response)
                client.close()
                return ConnectionTestResult(
                    success=False,
                    url=test_url,
                    username=test_username,
                    error=f"API error: {error_msg}",
                )

            epg_response = client.get("/tic-api/epgs/get")
            version_response = client.get("/tic-api/version")
            version = None
            if version_response and version_response.status_code == 200:
                try:
                    payload = version_response.json()
                    version = payload.get("version")
                except Exception:
                    version = None

            playlist_count = len(playlists_response.json().get("data", []))
            epg_count = (
                len(epg_response.json().get("data", []))
                if epg_response and epg_response.status_code == 200
                else None
            )
            client.close()
            return ConnectionTestResult(
                success=True,
                url=test_url,
                username=test_username,
                version=version,
                playlist_count=playlist_count,
                epg_count=epg_count,
            )
        except Exception as exc:
            return ConnectionTestResult(
                success=False,
                url=test_url,
                username=test_username,
                error=str(exc),
            )


_factory: HeadendarrFactory | None = None
_factory_lock = threading.Lock()


def get_factory(db_factory: Any | None = None) -> HeadendarrFactory:
    """Get or create the singleton Headendarr factory."""
    global _factory
    with _factory_lock:
        if _factory is None:
            if db_factory is None:
                raise RuntimeError("Headendarr factory not initialized and no db_factory provided")
            _factory = HeadendarrFactory(db_factory)
        return _factory


def get_headendarr_connection(db_factory: Any | None = None) -> HeadendarrConnection | None:
    return get_factory(db_factory).get_connection()


def close_headendarr() -> None:
    global _factory
    with _factory_lock:
        if _factory is not None:
            _factory._close_connection()
            _factory = None
