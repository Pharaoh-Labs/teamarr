"""Tests for `_refresh_plex_server` — the flow, not just the pure function.

The channelmap PUT replaces a device's whole state, so the safety story lives
in this function: what it decides to send, and when it refuses to send at all.
Every scenario here is one the previous range-based ownership got wrong on a
real server.
"""

import json
import sqlite3

import pytest

from teamarr.consumers.generation_pipeline.media_refresh import refresh_plex_server


def _device(key, channels, enabled_raw="1", carried_also=()):
    """`channels` are enabled; `carried_also` are on the tuner but disabled."""
    mapping = [
        {
            "channelKey": c,
            "deviceIdentifier": c,
            "enabled": enabled_raw,
            "lineupIdentifier": c,
        }
        for c in channels
    ]
    mapping += [
        {"channelKey": c, "deviceIdentifier": c, "enabled": "0", "lineupIdentifier": c}
        for c in carried_also
    ]
    return {"key": key, "uri": "http://dispatcharr:9191/hdhr/Sports",
            "ChannelMapping": mapping}


def _dvrs_payload(devices):
    return {
        "MediaContainer": {
            "Dvr": [
                {
                    "key": "61",
                    "lineup": (
                        "lineup://tv.plex.providers.epg.xmltv/"
                        "http%3A%2F%2Fd%3A9191%2Foutput%2Fepg%2FSports#Sports"
                    ),
                    "Device": devices,
                }
            ]
        }
    }


class FakePlex:
    """Stands in for a Plex server: serves reads, records the PUT, applies it."""

    def __init__(self, devices, apply_writes=True):
        self.devices = devices
        self.apply_writes = apply_writes
        self.puts = []

    def install(self, monkeypatch, httpx):
        def fake_get(url, **kwargs):
            req = httpx.Request("GET", url)
            if "/livetv/dvrs" in url:
                return httpx.Response(
                    200, json=_dvrs_payload(self.devices), request=req
                )
            # Dispatcharr guide readiness probe
            return httpx.Response(200, content=b"<tv></tv>", request=req)

        def fake_put(url, **kwargs):
            params = dict(kwargs.get("params") or [])
            self.puts.append(params)
            if self.apply_writes:
                wanted = set(filter(None, params.get("channelsEnabled", "").split(",")))
                for dev in self.devices:
                    for m in dev["ChannelMapping"]:
                        m["enabled"] = "1" if m["deviceIdentifier"] in wanted else "0"
            return httpx.Response(200, request=httpx.Request("PUT", url))

        monkeypatch.setattr(httpx, "get", fake_get)
        monkeypatch.setattr(httpx, "put", fake_put)

    def last_enabled(self):
        return set(
            filter(None, self.puts[-1].get("channelsEnabled", "").split(","))
        )


@pytest.fixture
def db(tmp_path):
    """A real database, built from schema.sql.

    Deliberately NOT a hand-written subset: an earlier version of this fixture
    invented `managed_team_channels` with a `channel_profile_ids` column the
    real table does not have, so the suite passed while every live run failed
    with "no such column". Build from the shipped schema or the tests prove
    nothing about the queries.
    """
    from teamarr.database.connection import init_db

    path = tmp_path / "t.db"
    init_db(str(path))

    class Factory:
        def __call__(self):
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return _Ctx(c)

    return Factory(), path


class _Ctx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *a):
        self.conn.close()
        return False


def _seed(path, events=(), teams=(), pushed=None, profile=""):
    """Insert event channels, managed team channels, and a pushed-set row."""
    c = sqlite3.connect(path)
    for n in events:
        c.execute(
            "INSERT INTO managed_channels (channel_number, channel_profile_ids, "
            "event_id, event_provider, tvg_id, channel_name) "
            "VALUES (?, ?, ?, 'espn', ?, ?)",
            (n, "[0]", f"evt-{n}", f"tvg-{n}", f"Event {n}"),
        )
    for n in teams:
        c.execute(
            "INSERT INTO teams (team_name, channel_id, provider_team_id, "
            "primary_league, sport, managed_channel_enabled) "
            "VALUES (?, ?, ?, 'nhl', 'hockey', 1)",
            (f"Team {n}", f"team.{n}", f"pt-{n}"),
        )
        c.execute(
            "INSERT INTO managed_team_channels (team_id, dispatcharr_channel_id, "
            "channel_number) VALUES (last_insert_rowid(), ?, ?)",
            (int(n), n),
        )
    if pushed is not None:
        c.execute(
            "INSERT INTO plex_pushed_channels (server_url, device_key, "
            "channel_profile_id, channel_keys, updated_at) "
            "VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
            ("http://plex:32400", "60", profile, json.dumps(sorted(pushed))),
        )
    c.commit()
    c.close()


class Server:
    name = "Test"
    url = "http://plex:32400"
    token = "tok"
    dvr_id = "61"
    device_key = "60"
    channel_profile_id = None


def _run(db_factory):
    return refresh_plex_server(
        Server(), "Test", db_factory, lambda _m: None, lambda: False
    )


class TestOwnership:
    def test_foreign_channels_survive_at_any_number(self, db, monkeypatch):
        """The headline regression: default range claimed everything >= 101."""
        import httpx

        factory, path = db
        _seed(path, events=["101"])
        plex = FakePlex([_device("60", ["5", "150", "9000", "101"])])
        plex.install(monkeypatch, httpx)

        result = _run(factory)

        assert result["success"] is True
        assert plex.last_enabled() == {"5", "150", "9000", "101"}

    def test_team_channels_are_included(self, db, monkeypatch):
        import httpx

        factory, path = db
        _seed(path, events=["101"], teams=["9000"])
        plex = FakePlex([_device("60", ["101"], carried_also=["9000"])])
        plex.install(monkeypatch, httpx)

        _run(factory)

        assert "9000" in plex.last_enabled()

    def test_stale_teamarr_channel_is_removed(self, db, monkeypatch):
        import httpx

        factory, path = db
        _seed(path, events=["102"], pushed={"101"})
        plex = FakePlex([_device("60", ["101", "700"], carried_also=["102"])])
        plex.install(monkeypatch, httpx)

        _run(factory)

        assert plex.last_enabled() == {"102", "700"}

    def test_pushed_set_is_recorded_after_a_verified_write(self, db, monkeypatch):
        import httpx

        factory, path = db
        _seed(path, events=["101", "102"])
        plex = FakePlex([_device("60", ["101"], carried_also=["102"])])
        plex.install(monkeypatch, httpx)

        _run(factory)

        c = sqlite3.connect(path)
        stored = c.execute("SELECT channel_keys FROM plex_pushed_channels").fetchone()[0]
        c.close()
        assert set(json.loads(stored)) == {"101", "102"}


class TestRefusals:
    def test_refuses_when_device_read_has_null_identifier(self, db, monkeypatch):
        import httpx

        factory, path = db
        _seed(path, events=["101"])
        dev = _device("60", ["101"])
        dev["ChannelMapping"].append(
            {"channelKey": "x", "enabled": "1", "lineupIdentifier": "x"}
        )
        plex = FakePlex([dev])
        plex.install(monkeypatch, httpx)

        result = _run(factory)

        assert result["success"] is False
        assert "deviceIdentifier" in result["error"]
        assert plex.puts == []

    def test_refuses_empty_write_against_a_populated_device(self, db, monkeypatch):
        """No managed channels (off-season) plus a read that lost the mapping."""
        import httpx

        factory, path = db
        _seed(path, pushed={"101"})
        plex = FakePlex([_device("60", [])])
        plex.install(monkeypatch, httpx)

        result = _run(factory)

        assert result["success"] is False
        assert plex.puts == []

    def test_enabled_as_json_true_does_not_drop_channels(self, db, monkeypatch):
        """str(True) != "1" used to read as disabled, so the channel was lost."""
        import httpx

        factory, path = db
        _seed(path, events=["101"])
        plex = FakePlex([_device("60", ["700", "701"], enabled_raw=True)])
        plex.install(monkeypatch, httpx)

        _run(factory)

        assert {"700", "701"} <= plex.last_enabled()


class TestWriteVerification:
    def test_unapplied_write_is_reported_as_failure(self, db, monkeypatch):
        """Plex answers 200 to requests it silently ignores (live-tested)."""
        import httpx

        factory, path = db
        _seed(path, events=["101"])
        # 101 is on the tuner but disabled, so the write must change something.
        plex = FakePlex(
            [_device("60", ["700"], carried_also=["101"])], apply_writes=False
        )
        plex.install(monkeypatch, httpx)

        result = _run(factory)

        assert result["success"] is False
        assert "not applied" in result["error"]

    def test_pushed_set_not_recorded_when_write_unverified(self, db, monkeypatch):
        import httpx

        factory, path = db
        _seed(path, events=["101"])
        plex = FakePlex(
            [_device("60", ["700"], carried_also=["101"])], apply_writes=False
        )
        plex.install(monkeypatch, httpx)

        _run(factory)

        c = sqlite3.connect(path)
        rows = c.execute("SELECT COUNT(*) FROM plex_pushed_channels").fetchone()[0]
        c.close()
        assert rows == 0


class TestProfileScoping:
    def test_channels_not_on_this_tuner_do_not_fail_the_write(self, db, monkeypatch, caplog):
        """Unscoped Teamarr config + profile-scoped device: we manage channels
        this tuner does not carry. They cannot be enabled, and that must not
        be mistaken for Plex ignoring the request."""
        import httpx

        factory, path = db
        _seed(path, events=["101", "999"])
        plex = FakePlex([_device("60", ["101"])])
        plex.install(monkeypatch, httpx)

        result = _run(factory)

        assert result["success"] is True
        assert "not on this device's tuner" in caplog.text


class TestTeamChannelProfileScope:
    """Team channels carry no per-row profile — scope comes from the global
    managed_team_channel_profile_ids setting."""

    def _set_team_profiles(self, path, value):
        c = sqlite3.connect(path)
        c.execute(
            "UPDATE settings SET managed_team_channel_profile_ids = ? WHERE id = 1",
            (value,),
        )
        c.commit()
        c.close()

    def test_included_when_the_setting_names_this_profile(self, db, monkeypatch):
        import httpx

        factory, path = db
        _seed(path, teams=["9000"])
        self._set_team_profiles(path, "[7]")
        plex = FakePlex([_device("60", [], carried_also=["9000"])])
        plex.install(monkeypatch, httpx)

        class Scoped(Server):
            channel_profile_id = 7

        refresh_plex_server(Scoped(), "T", factory, lambda _m: None, lambda: False)
        assert "9000" in plex.last_enabled()

    def test_excluded_when_the_setting_names_another_profile(self, db, monkeypatch):
        import httpx

        factory, path = db
        _seed(path, teams=["9000"])
        self._set_team_profiles(path, "[7]")
        plex = FakePlex([_device("60", ["9000"])])
        plex.install(monkeypatch, httpx)

        class Scoped(Server):
            channel_profile_id = 99

        refresh_plex_server(Scoped(), "T", factory, lambda _m: None, lambda: False)
        # Already enabled, so it stays — but it is not something we now manage.
        assert "9000" in plex.last_enabled()
        c = sqlite3.connect(path)
        stored = c.execute("SELECT channel_keys FROM plex_pushed_channels").fetchone()
        c.close()
        assert "9000" not in json.loads(stored[0])

    def test_all_profiles_sentinel_includes_them(self, db, monkeypatch):
        import httpx

        factory, path = db
        _seed(path, teams=["9000"])
        self._set_team_profiles(path, "[0]")
        plex = FakePlex([_device("60", [], carried_also=["9000"])])
        plex.install(monkeypatch, httpx)

        class Scoped(Server):
            channel_profile_id = 42

        refresh_plex_server(Scoped(), "T", factory, lambda _m: None, lambda: False)
        assert "9000" in plex.last_enabled()
