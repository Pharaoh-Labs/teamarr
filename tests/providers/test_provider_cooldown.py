"""The shared provider wait is a rate-limit deadline, nothing else (#1277).

#1246 made retries share one cooldown per provider. It slept while holding
the lock every request waits on, for 5xx and connection retries as well as
429s, and a short backoff could replace a 429's Retry-After. Now only a 429
sets a shared wait, as a deadline that can only be extended; every sleep
happens outside the lock, and other retries sleep in their own thread.

#1246's own test (test_concurrent_response_wave_shares_one_cooldown) pinned
the epoch mechanism this replaces; what it meant to protect — one wait for a
wave of 429s, not one each — is test_a_wave_of_429s_waits_once_not_in_turn.
"""

import threading
import time

import httpx
import pytest

from teamarr.providers import base_client
from teamarr.providers.base_client import BaseHTTPClient, _ProviderCooldown
from teamarr.providers.tsdb import client as tsdb_client
from teamarr.providers.tsdb.client import TSDBClient


class _Stub(BaseHTTPClient):
    PROVIDER = "cooldown-stub"
    LOG_TAG = "STUB"


class _OtherStub(BaseHTTPClient):
    PROVIDER = "cooldown-other"
    LOG_TAG = "OTHER"


def _client(handler, cls=_Stub, **kwargs):
    client = cls(**kwargs)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def _ok(request):
    return httpx.Response(200, json={"ok": True})


def _first_then_ok(first: httpx.Response):
    """A handler answering ``first`` once and 200 from then on."""
    seen = []

    def handler(request):
        seen.append(1)
        return first if len(seen) == 1 else httpx.Response(200, json={"ok": True})

    return handler


class _FakeClock:
    """base_client's clock and sleep, with no real waiting."""

    def __init__(self, monkeypatch):
        self.now = 1000.0
        self.sleeps: list[float] = []
        self.on_sleep = None  # called once, inside the first sleep
        monkeypatch.setattr(base_client, "_monotonic", lambda: self.now)
        monkeypatch.setattr(base_client, "_sleep", self.sleep)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        wake = self.now + seconds
        hook, self.on_sleep = self.on_sleep, None
        if hook:
            hook()
        self.now = max(self.now, wake)


@pytest.fixture
def clock(monkeypatch):
    return _FakeClock(monkeypatch)


# --- the deadline -----------------------------------------------------------


def test_no_deadline_means_no_wait(clock):
    _ProviderCooldown().wait()
    assert clock.sleeps == []


def test_rate_limit_waits_out_its_own_delay(clock):
    cooldown = _ProviderCooldown()
    cooldown.rate_limited(5.0)
    assert clock.sleeps == [5.0]
    cooldown.wait()  # deadline passed: nothing more to wait for
    assert clock.sleeps == [5.0]


def test_a_shorter_rate_limit_never_shortens_the_deadline(clock):
    cooldown = _ProviderCooldown()
    with cooldown._lock:
        cooldown._until = clock.now + 5.0
    cooldown.rate_limited(1.0)
    assert clock.sleeps == [5.0]


def test_a_wait_in_progress_follows_an_extended_deadline(clock):
    """Two 429s, Retry-After 2 and 5: the thread given 2 waits 5 as well."""
    cooldown = _ProviderCooldown()
    # The second 429 lands while the first thread is asleep.
    clock.on_sleep = lambda: _set_deadline(cooldown, clock.now + 5.0)
    cooldown.rate_limited(2.0)
    assert clock.sleeps == [2.0, 3.0]
    assert clock.now == 1005.0


def _set_deadline(cooldown, until):
    """What another thread's 429 does: needs the lock, so it must be free."""
    assert cooldown._lock.acquire(blocking=False), "lock held during a sleep"
    cooldown._until = max(cooldown._until, until)
    cooldown._lock.release()


def test_a_wave_of_429s_waits_once_not_in_turn(clock):
    """#1246's intent: responses from one wave share a wait, they do not queue."""
    cooldown = _ProviderCooldown()
    cooldown.rate_limited(2.0)
    clock.now -= 2.0  # a second response from the same wave, same instant
    cooldown.rate_limited(2.0)
    assert clock.now == 1002.0  # 2 s in all, not 4


# --- through the client -----------------------------------------------------


def test_5xx_retry_sets_no_shared_wait_and_holds_no_lock(clock):
    client = _client(_first_then_ok(httpx.Response(500)), retry_count=3)
    cooldown = client._cooldown
    locked_during_sleep = []
    clock.on_sleep = lambda: locked_during_sleep.append(cooldown._lock.locked())

    assert client._request_json("https://api.test/x") == {"ok": True}

    assert len(clock.sleeps) == 1  # the retry's own backoff
    assert locked_during_sleep == [False]
    assert cooldown._until == 0.0


def test_connection_retry_sets_no_shared_wait(clock):
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"ok": True})

    client = _client(handler, retry_count=3)
    assert client._request_json("https://api.test/x") == {"ok": True}
    assert len(clock.sleeps) == 1
    assert client._cooldown._until == 0.0


def test_5xx_retry_does_not_delay_another_thread(monkeypatch):
    """Thread A sits in a 5xx backoff; a request on another client goes out."""
    sleeping, release = threading.Event(), threading.Event()

    def blocking_sleep(seconds):
        sleeping.set()
        assert release.wait(5)

    monkeypatch.setattr(base_client, "_sleep", blocking_sleep)
    failing = _client(_first_then_ok(httpx.Response(503)), retry_count=3)
    healthy = _client(_ok)
    assert failing._cooldown is healthy._cooldown

    a = threading.Thread(target=failing._request_json, args=("https://a.test/x",))
    a.start()
    try:
        assert sleeping.wait(5)
        result = []
        b = threading.Thread(
            target=lambda: result.append(healthy._request_json("https://b.test/y"))
        )
        b.start()
        b.join(1)
        assert not b.is_alive(), "blocked behind another thread's 5xx retry"
        assert result == [{"ok": True}]
        assert not healthy._cooldown._lock.locked()
    finally:
        release.set()
        a.join(5)


def test_429_wait_holds_no_lock(clock):
    client = _client(_first_then_ok(httpx.Response(429, headers={"Retry-After": "2"})))
    locked = []
    clock.on_sleep = lambda: locked.append(client._cooldown._lock.locked())
    assert client._request_json("https://api.test/x") == {"ok": True}
    assert clock.sleeps == [2.0]
    assert locked == [False]


def test_request_started_during_a_rate_limit_wait_is_held_to_the_deadline(clock):
    limited = _client(_first_then_ok(httpx.Response(429, headers={"Retry-After": "3"})))
    sent_at = []

    def other_handler(request):
        sent_at.append(clock.now)
        return httpx.Response(200, json={"ok": True})

    other = _client(other_handler)
    results = []
    # While the first client waits, a second one starts a request.
    clock.on_sleep = lambda: results.append(other._request_json("https://b.test/y"))

    assert limited._request_json("https://a.test/x") == {"ok": True}

    assert results == [{"ok": True}]  # held, then sent
    assert sent_at == [1003.0]


def test_providers_do_not_share_a_deadline(clock):
    limited = _client(_first_then_ok(httpx.Response(429, headers={"Retry-After": "3"})))
    other = _client(_ok, cls=_OtherStub)
    assert limited._cooldown is not other._cooldown
    results = []
    clock.on_sleep = lambda: results.append((other._request_json("https://o.test/y"), clock.now))

    assert limited._request_json("https://a.test/x") == {"ok": True}

    assert results == [({"ok": True}, 1000.0)]  # sent at once, mid-wait
    assert clock.sleeps == [3.0]
    assert other._cooldown._until == 0.0


# --- real threads, real (small) waits ---------------------------------------

_LONG = 0.3
_SLACK = 0.02  # timer granularity; a sleep never ends early by more


def _run_together(*calls):
    threads = [threading.Thread(target=fn, args=args) for fn, *args in calls]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
        assert not t.is_alive()


def test_short_5xx_backoff_cannot_swallow_a_429(monkeypatch):
    """A: 500, short backoff. B: 429 with a long Retry-After, arriving mid-backoff."""
    b_sent = []
    b_out = threading.Event()

    a_seen: list[int] = []

    def a_handler(request):
        assert b_out.wait(5)  # B's request is in flight before A's 500 lands
        a_seen.append(1)
        return httpx.Response(500) if len(a_seen) == 1 else httpx.Response(200, json={})

    def b_handler(request):
        b_sent.append(time.monotonic())
        if len(b_sent) == 1:
            b_out.set()
            time.sleep(0.03)  # the 429 arrives while A is in its backoff
            return httpx.Response(429, headers={"Retry-After": str(_LONG)})
        return httpx.Response(200, json={})

    a = _client(a_handler, retry_count=3)
    monkeypatch.setattr(a, "_calculate_delay", lambda attempt: 0.1)
    b = _client(b_handler)

    _run_together((a._request_json, "https://a.test/x"), (b._request_json, "https://b.test/y"))

    assert len(b_sent) == 2
    assert b_sent[1] - b_sent[0] >= _LONG - _SLACK


def test_two_429s_both_wait_for_the_longer():
    barrier = threading.Barrier(2)
    start = []
    retried: dict[str, float] = {}

    def handler_for(name, retry_after):
        seen = []

        def handler(request):
            seen.append(1)
            if len(seen) == 1:
                barrier.wait(5)  # both 429s come back together
                start.append(time.monotonic())
                return httpx.Response(429, headers={"Retry-After": str(retry_after)})
            retried[name] = time.monotonic()
            return httpx.Response(200, json={})

        return handler

    short = _client(handler_for("short", 0.05))
    long = _client(handler_for("long", _LONG))

    _run_together(
        (short._request_json, "https://a.test/x"), (long._request_json, "https://b.test/y")
    )

    began = max(start)
    assert retried["long"] - began >= _LONG - _SLACK
    assert retried["short"] - began >= _LONG - _SLACK


# --- TSDB keeps its own request loop ----------------------------------------


@pytest.fixture
def tsdb_sleeps(monkeypatch):
    """TSDB's local retry sleeps (its own ``time.sleep``), kept off the clock."""
    sleeps: list[float] = []
    monkeypatch.setattr(tsdb_client.time, "sleep", sleeps.append)
    return sleeps


def _tsdb(handler, **kwargs):
    client = TSDBClient(api_key="k", **kwargs)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_tsdb_5xx_retry_sleeps_locally(clock, tsdb_sleeps):
    client = _tsdb(_first_then_ok(httpx.Response(500)), retry_count=3, retry_delay=1.0)
    assert client._request("x.php") == {"ok": True}
    assert tsdb_sleeps == [1.0]
    assert clock.sleeps == []  # nothing shared
    assert client._cooldown._until == 0.0


def test_tsdb_connection_retry_sleeps_locally(clock, tsdb_sleeps):
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"ok": True})

    client = _tsdb(handler, retry_count=3, retry_delay=1.0)
    assert client._request("x.php") == {"ok": True}
    assert tsdb_sleeps == [1.0]
    assert clock.sleeps == []


def test_tsdb_429_holds_other_tsdb_requests_and_no_lock(clock, tsdb_sleeps):
    limited = _tsdb(_first_then_ok(httpx.Response(429)))
    sent_at = []

    def other_handler(request):
        sent_at.append(clock.now)
        return httpx.Response(200, json={"ok": True})

    other = _tsdb(other_handler)
    assert limited._cooldown is other._cooldown
    locked = []

    def during_wait():
        locked.append(limited._cooldown._lock.locked())
        other._request("y.php")

    clock.on_sleep = during_wait

    assert limited._request("x.php") == {"ok": True}

    assert clock.sleeps[0] == TSDBClient.BACKOFF_BASE
    assert locked == [False]
    assert sent_at == [1000.0 + TSDBClient.BACKOFF_BASE]
    assert tsdb_sleeps == []


def test_tsdb_and_stub_do_not_share_a_deadline(clock, tsdb_sleeps):
    limited = _tsdb(_first_then_ok(httpx.Response(429)))
    other = _client(_ok)
    results = []
    clock.on_sleep = lambda: results.append((other._request_json("https://o.test/y"), clock.now))
    assert limited._request("x.php") == {"ok": True}
    assert results == [({"ok": True}, 1000.0)]
