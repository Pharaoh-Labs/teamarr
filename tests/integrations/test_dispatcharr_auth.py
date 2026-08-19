from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event, Lock
from time import monotonic, sleep

import httpx

from teamarr.dispatcharr.auth import TokenManager
from teamarr.dispatcharr.client import DispatcharrClient


def test_token_authentication_is_serialized_per_session(monkeypatch):
    TokenManager.clear_all_sessions()

    authenticate_calls = 0
    authenticate_lock = Lock()
    release_auth = Event()

    def fake_authenticate(self):
        nonlocal authenticate_calls
        with authenticate_lock:
            authenticate_calls += 1

        release_auth.wait(timeout=5)
        self._session["access_token"] = "shared-token"
        self._session["refresh_token"] = "refresh-token"
        self._session["token_expiry"] = datetime.now() + timedelta(minutes=5)
        return True

    monkeypatch.setattr(TokenManager, "_authenticate", fake_authenticate)

    managers = [TokenManager("http://dispatcharr.example", "user", "password") for _ in range(12)]
    start = Event()

    def get_token(manager):
        start.wait(timeout=5)
        return manager.get_token()

    with ThreadPoolExecutor(max_workers=len(managers)) as executor:
        futures = [executor.submit(get_token, manager) for manager in managers]
        start.set()

        deadline = monotonic() + 5
        while authenticate_calls == 0 and monotonic() < deadline:
            sleep(0.01)
        assert authenticate_calls == 1
        release_auth.set()

        tokens = [future.result(timeout=5) for future in futures]

    assert tokens == ["shared-token"] * len(managers)
    assert authenticate_calls == 1


def test_auth_retry_delay_uses_dispatcharr_throttle_detail():
    manager = TokenManager("http://dispatcharr.example", "user", "password")
    response = httpx.Response(
        429,
        json={"detail": "Request was throttled. Expected available in 12 seconds."},
    )

    assert manager._parse_retry_delay(response) == 12.0


def test_client_close_preserves_shared_auth_session():
    TokenManager.clear_all_sessions()

    client = DispatcharrClient("http://dispatcharr.example", "user", "password")
    client._auth._session["access_token"] = "cached-token"
    client._auth._session["refresh_token"] = "refresh-token"
    client._auth._session["token_expiry"] = datetime.now() + timedelta(minutes=5)

    client.close()

    next_manager = TokenManager("http://dispatcharr.example", "user", "password")
    assert next_manager.get_token() == "cached-token"
