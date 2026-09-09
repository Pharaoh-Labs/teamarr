"""A config fix must take effect on the next run, not three runs later (#757).

Negative match caching (#754) remembers failures derived from team identity,
aliases and league membership. Nothing dropped those entries when that source
data changed, so a user who added an alias to fix a mismatch saw nothing happen
for up to the cache TTL — and the way it fails is silent: the stale verdict
short-circuits before the newly-fixed logic ever runs, so the natural reading is
"my fix didn't work".

Before #754 this was immediate, because failures were never remembered. These
tests pin the invalidation that restores that, and pin what must NOT be cleared
along with it.
"""

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.consumers.matching.result import FailedReason
from teamarr.consumers.stream_match_cache import FAILED_MATCH_EVENT_ID, StreamMatchCache
from teamarr.database import init_db

EVENT = {"id": "e1", "name": "Rays at Tigers"}


def _seed(db_factory):
    """Two failures, a success and a user correction."""
    c = StreamMatchCache(db_factory)
    c.set_failed(group_id=1, stream_id=1, stream_name="fail A", generation=5,
                 reason=FailedReason.NO_EVENT_FOUND.value)
    c.set_failed(group_id=2, stream_id=2, stream_name="fail B", generation=5,
                 reason=FailedReason.FIXTURE_NOT_IN_LEAGUE.value)
    c.set(group_id=1, stream_id=3, stream_name="ok", event_id="e1", league="mlb",
          cached_data=EVENT, generation=5)
    c.set_user_correction(group_id=1, stream_id=4, stream_name="pinned",
                          event_id="e9", league="mlb", cached_data=EVENT)
    return c


def _counts(db_factory):
    with db_factory() as conn:
        total = conn.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM stream_match_cache WHERE event_id = ?",
            (FAILED_MATCH_EVENT_ID,)).fetchone()[0]
        pinned = conn.execute(
            "SELECT COUNT(*) FROM stream_match_cache WHERE user_corrected = 1").fetchone()[0]
    return total, failed, pinned


class TestClearFailed:
    def test_clears_only_failures(self, db_factory):
        _seed(db_factory)
        assert _counts(db_factory) == (4, 2, 1)

        cleared = StreamMatchCache(db_factory).clear_failed()

        assert cleared == 2
        total, failed, pinned = _counts(db_factory)
        assert failed == 0, "failures should be gone"
        assert total == 2, "the success and the pin must survive"
        assert pinned == 1

    def test_successful_match_still_readable_afterwards(self, db_factory):
        c = _seed(db_factory)
        c.clear_failed()
        entry = c.get(1, 3, "ok")
        assert entry is not None and entry.event_id == "e1"

    def test_user_correction_is_never_cleared(self, db_factory):
        """Pins outrank everything, including a config-change invalidation."""
        c = _seed(db_factory)
        c.clear_failed()
        assert c.is_user_corrected(1, 4, "pinned") is True

    def test_is_idempotent(self, db_factory):
        c = _seed(db_factory)
        assert c.clear_failed() == 2
        assert c.clear_failed() == 0

    def test_empty_cache_is_fine(self, db_factory):
        assert StreamMatchCache(db_factory).clear_failed() == 0


class TestTeamIdentityHook:
    """The canonical 'team data changed' hook must cover the negative cache."""

    def test_invalidating_identity_caches_drops_cached_failures(
        self, db_factory, db_path, monkeypatch
    ):
        monkeypatch.setenv("DATABASE_PATH", str(db_path))
        _seed(db_factory)
        assert _counts(db_factory)[1] == 2

        from teamarr.database.team_cache import invalidate_team_identity_caches

        invalidate_team_identity_caches()

        total, failed, pinned = _counts(db_factory)
        assert failed == 0
        assert total == 2, "successes and pins survive a team-cache refresh"

    def test_hook_survives_a_cache_error(self, monkeypatch):
        """Invalidation must never break the refresh that triggered it."""
        import teamarr.consumers.stream_match_cache as smc

        class Boom(smc.StreamMatchCache):
            def clear_failed(self):
                raise RuntimeError("db gone")

        monkeypatch.setattr(smc, "StreamMatchCache", Boom)
        from teamarr.database.team_cache import invalidate_team_identity_caches

        invalidate_team_identity_caches()  # must not raise


# ---------------------------------------------------------------------------
# Alias routes (#757). These cleared NOTHING before this change: an alias is a
# direct input to matching, so a failure cached before it existed is wrong the
# moment it is saved.
# ---------------------------------------------------------------------------

client = TestClient(app)
ALIASES = "/api/v1/aliases"


@pytest.fixture
def api_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    from teamarr.database.connection import get_db

    return get_db


def _seed_failure(db_factory):
    StreamMatchCache(db_factory).set_failed(
        group_id=1, stream_id=1, stream_name="Rays vs Tigers", generation=5,
        reason=FailedReason.FIXTURE_NOT_IN_LEAGUE.value)


def _failed_rows(db_factory):
    with db_factory() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM stream_match_cache WHERE event_id = ?",
            (FAILED_MATCH_EVENT_ID,)).fetchone()[0]


def test_creating_an_alias_clears_cached_failures(api_db):
    _seed_failure(api_db)
    assert _failed_rows(api_db) == 1

    r = client.post(ALIASES, json={"alias": "D-backs", "league": "mlb", "team_id": "29",
                                   "team_name": "Arizona Diamondbacks"})
    assert r.status_code == 201, r.text
    assert _failed_rows(api_db) == 0


def test_updating_an_alias_clears_cached_failures(api_db):
    created = client.post(ALIASES, json={"alias": "Dbacks", "league": "mlb", "team_id": "29",
                                         "team_name": "Arizona Diamondbacks"})
    assert created.status_code == 201, created.text
    alias_id = created.json()["id"]
    _seed_failure(api_db)

    r = client.patch(f"{ALIASES}/{alias_id}", json={"alias": "D-backs"})
    assert r.status_code == 200, r.text
    assert _failed_rows(api_db) == 0


def test_deleting_an_alias_clears_cached_failures(api_db):
    created = client.post(ALIASES, json={"alias": "Dbacks", "league": "mlb", "team_id": "29",
                                         "team_name": "Arizona Diamondbacks"})
    alias_id = created.json()["id"]
    _seed_failure(api_db)

    r = client.delete(f"{ALIASES}/{alias_id}")
    assert r.status_code == 204
    assert _failed_rows(api_db) == 0


def test_reading_an_alias_does_not_clear_the_cache(api_db):
    """Reads must stay free — an earlier draft cleared on GET by mistake."""
    created = client.post(ALIASES, json={"alias": "Dbacks", "league": "mlb", "team_id": "29",
                                         "team_name": "Arizona Diamondbacks"})
    alias_id = created.json()["id"]
    _seed_failure(api_db)

    assert client.get(f"{ALIASES}/{alias_id}").status_code == 200
    assert client.get(ALIASES).status_code == 200
    assert _failed_rows(api_db) == 1, "a read must not invalidate anything"
