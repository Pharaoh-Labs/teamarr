"""Dispatcharr API-key authentication (#817).

An API key is sent as ``X-API-Key`` on every request and nothing is ever
logged in; username/password keep minting JWTs as before.
"""

import contextlib
import sqlite3

import httpx
import pytest

from teamarr.database.settings import get_dispatcharr_settings, update_dispatcharr_settings
from teamarr.dispatcharr.auth import TokenManager
from teamarr.dispatcharr.client import DispatcharrClient
from teamarr.dispatcharr.factory import DispatcharrFactory
from tests.helpers import SCHEMA_PATH

URL = "http://dispatcharr.example"


def _never(self):
    raise AssertionError("username/password login must not run with an API key")


def _client_with(handler, **kwargs) -> DispatcharrClient:
    client = DispatcharrClient(URL, "user", "password", max_retries=0, **kwargs)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


# --- TokenManager / client ---------------------------------------------------


def test_api_key_is_sent_as_x_api_key_and_never_logs_in(monkeypatch):
    TokenManager.clear_all_sessions()
    monkeypatch.setattr(TokenManager, "_authenticate", _never)
    monkeypatch.setattr(TokenManager, "_refresh", _never)
    seen = []

    def handler(request):
        seen.append(dict(request.headers))
        return httpx.Response(200, json={"count": 1})

    client = _client_with(handler, api_key=" k-123 ")
    assert client.request("GET", "/api/channels/channels/").status_code == 200
    assert seen[0]["x-api-key"] == "k-123"
    assert "authorization" not in seen[0]
    assert client._auth.uses_api_key
    assert client._auth.get_token() is None


def test_without_a_key_the_bearer_flow_is_unchanged(monkeypatch):
    TokenManager.clear_all_sessions()

    def fake_authenticate(self):
        from datetime import datetime, timedelta

        self._session["access_token"] = "jwt"
        self._session["token_expiry"] = datetime.now() + timedelta(minutes=5)
        return True

    monkeypatch.setattr(TokenManager, "_authenticate", fake_authenticate)
    seen = []

    def handler(request):
        seen.append(dict(request.headers))
        return httpx.Response(200, json={})

    client = _client_with(handler)
    client.request("GET", "/api/channels/channels/")
    assert seen[0]["authorization"] == "Bearer jwt"
    assert "x-api-key" not in seen[0]
    assert not client._auth.uses_api_key


def test_a_rejected_key_is_not_retried(monkeypatch):
    TokenManager.clear_all_sessions()
    monkeypatch.setattr(TokenManager, "_authenticate", _never)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(401, json={"detail": "Invalid API key"})

    client = _client_with(handler, api_key="bad")
    response = client.request("GET", "/api/channels/channels/")
    assert response.status_code == 401
    assert calls == ["/api/channels/channels/"]


def test_a_blank_key_means_no_key():
    TokenManager.clear_all_sessions()
    manager = TokenManager(URL, "user", "password", api_key="   ")
    assert not manager.uses_api_key


# --- settings + factory ------------------------------------------------------


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def _factory(conn):
    @contextlib.contextmanager
    def factory():
        yield conn
        conn.commit()

    return factory


@pytest.fixture
def conn():
    return _db()


def test_api_key_round_trips_and_clears(conn):
    update_dispatcharr_settings(conn, enabled=True, url=URL, api_key="k-1")
    assert get_dispatcharr_settings(conn).api_key == "k-1"
    update_dispatcharr_settings(conn, username="u")  # omitted = kept
    assert get_dispatcharr_settings(conn).api_key == "k-1"
    update_dispatcharr_settings(conn, api_key=None)  # None = cleared
    assert get_dispatcharr_settings(conn).api_key is None


def test_a_key_alone_configures_the_connection(conn):
    update_dispatcharr_settings(conn, enabled=True, url=URL, api_key="k-1")
    factory = DispatcharrFactory(_factory(conn))
    assert factory.is_configured
    before = factory._get_settings_hash()
    update_dispatcharr_settings(conn, api_key="k-2")
    assert factory._get_settings_hash() != before  # a new key reconnects


def test_a_url_alone_does_not(conn):
    update_dispatcharr_settings(conn, enabled=True, url=URL)
    assert not DispatcharrFactory(_factory(conn)).is_configured


def test_test_connection_prefers_a_typed_key_then_a_typed_password(conn, monkeypatch):
    update_dispatcharr_settings(
        conn, enabled=True, url=URL, username="u", password="saved-pw", api_key="saved-key"
    )
    built = []

    class FakeClient:
        def __init__(self, base_url, username, password, timeout, max_retries, api_key=None):
            built.append((username, password, api_key))

        def get(self, endpoint):
            return httpx.Response(200, json={"count": 3})

        def close(self):
            pass

    monkeypatch.setattr("teamarr.dispatcharr.factory.DispatcharrClient", FakeClient)
    factory = DispatcharrFactory(_factory(conn))

    assert factory.test_connection().auth_method == "api_key"
    assert factory.test_connection(password="typed").auth_method == "password"
    assert factory.test_connection(api_key="typed-key", password="typed").auth_method == "api_key"
    assert [b[2] for b in built] == ["saved-key", None, "typed-key"]
    assert built[1][1] == "typed"


def test_test_connection_names_a_rejected_key(conn, monkeypatch):
    update_dispatcharr_settings(conn, enabled=True, url=URL, api_key="revoked")

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def get(self, endpoint):
            return httpx.Response(401, json={"detail": "Invalid API key"})

        def close(self):
            pass

    monkeypatch.setattr("teamarr.dispatcharr.factory.DispatcharrClient", FakeClient)
    result = DispatcharrFactory(_factory(conn)).test_connection()
    assert not result.success
    assert "API key rejected" in result.error


# --- API --------------------------------------------------------------------


def test_settings_api_masks_keeps_and_removes_the_key(db_factory, monkeypatch):
    from fastapi.testclient import TestClient

    import teamarr.api.routes.settings.dispatcharr as route
    from teamarr.api.app import app

    monkeypatch.setattr(route, "get_db", db_factory)
    monkeypatch.setattr(route, "get_factory", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    api = TestClient(app)

    body = api.put("/api/v1/settings/dispatcharr", json={"api_key": "k-1"}).json()
    assert body["api_key"] == "********"
    with db_factory() as conn:
        assert get_dispatcharr_settings(conn).api_key == "k-1"

    api.put("/api/v1/settings/dispatcharr", json={"api_key": "********", "username": "u"})
    with db_factory() as conn:
        assert get_dispatcharr_settings(conn).api_key == "k-1"

    assert api.put("/api/v1/settings/dispatcharr", json={"api_key": ""}).json()["api_key"] is None
    with db_factory() as conn:
        assert get_dispatcharr_settings(conn).api_key is None


# --- adopt-or-mint (kd5a.5) -------------------------------------------------


def _adopt_client(existing_key, generated="minted-key", log=None):
    log = log if log is not None else []

    class FakeClient:
        def __init__(self, *a, **k):
            log.append(("init", k.get("api_key")))

        def get(self, endpoint):
            log.append(("get", endpoint))
            return httpx.Response(200, json={"key": existing_key})

        def post(self, endpoint, data=None):
            log.append(("post", endpoint))
            return httpx.Response(201, json={"key": generated, "user": {}})

        def close(self):
            pass

    return FakeClient, log


def test_adopt_takes_the_existing_key_and_never_generates(conn, monkeypatch):
    update_dispatcharr_settings(conn, enabled=True, url=URL, username="u", password="pw")
    fake, log = _adopt_client("already-there")
    monkeypatch.setattr("teamarr.dispatcharr.factory.DispatcharrClient", fake)
    factory = DispatcharrFactory(_factory(conn))
    monkeypatch.setattr(factory, "reconnect", lambda: None)

    result = factory.adopt_api_key()
    assert (result.success, result.created) == (True, False)
    assert get_dispatcharr_settings(conn).api_key == "already-there"
    assert ("post", "/api/accounts/api-keys/generate/") not in log
    assert get_dispatcharr_settings(conn).password == "pw"  # left for the user to clear


def test_adopt_generates_only_when_the_account_has_no_key(conn, monkeypatch):
    update_dispatcharr_settings(conn, enabled=True, url=URL, username="u", password="pw")
    fake, log = _adopt_client(None)
    monkeypatch.setattr("teamarr.dispatcharr.factory.DispatcharrClient", fake)
    factory = DispatcharrFactory(_factory(conn))
    monkeypatch.setattr(factory, "reconnect", lambda: None)

    result = factory.adopt_api_key()
    assert (result.success, result.created) == (True, True)
    assert get_dispatcharr_settings(conn).api_key == "minted-key"
    assert ("post", "/api/accounts/api-keys/generate/") in log


def test_adopt_needs_a_saved_password_and_reports_a_failed_read(conn, monkeypatch):
    update_dispatcharr_settings(conn, enabled=True, url=URL, username="u")
    assert not DispatcharrFactory(_factory(conn)).adopt_api_key().success

    update_dispatcharr_settings(conn, password="pw")

    class Refusing:
        def __init__(self, *a, **k):
            pass

        def get(self, endpoint):
            return httpx.Response(401, json={"detail": "bad"})

        def close(self):
            pass

    monkeypatch.setattr("teamarr.dispatcharr.factory.DispatcharrClient", Refusing)
    result = DispatcharrFactory(_factory(conn)).adopt_api_key()
    assert not result.success and "API key" in result.error
    assert get_dispatcharr_settings(conn).api_key is None
