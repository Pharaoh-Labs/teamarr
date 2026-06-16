"""TSDB premium-league gating in the startup cache prewarm (epic 46y3).

Without a TSDB premium key, the cache build must NOT roll premium-only TSDB
leagues into the team/league directory — otherwise it wastes free-tier calls on
data it can't fully fetch. Once a premium key is configured the provider reports
is_premium and every league is fetched again.
"""

import contextlib
import sqlite3
import threading
from pathlib import Path

from teamarr.consumers.cache.refresh import CacheRefresher

SCHEMA = Path(__file__).resolve().parents[1] / "teamarr" / "database" / "schema.sql"

# From schema.sql leagues table (tsdb_tier).
PREMIUM = ["ipl", "sa20", "uru.2"]
FREE = ["boxing", "cfl"]


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    return conn


def _shared_factory(conn: sqlite3.Connection):
    @contextlib.contextmanager
    def factory():
        yield conn

    return factory


class _FakeTSDB:
    """Minimal TSDB provider stub that records which leagues were fetched."""

    name = "tsdb"

    def __init__(self, *, is_premium: bool, leagues: list[str]):
        self.is_premium = is_premium
        self._leagues = leagues
        self.fetched: set[str] = set()
        self._lock = threading.Lock()

    def get_supported_leagues(self) -> list[str]:
        return list(self._leagues)

    def supports_league(self, league: str) -> bool:
        return league in self._leagues

    def get_league_teams(self, league: str) -> list:
        with self._lock:
            self.fetched.add(league)
        return []


def test_premium_tsdb_leagues_skipped_without_key():
    conn = _db()  # schema default: no premium key
    refresher = CacheRefresher(db_factory=_shared_factory(conn))
    prov = _FakeTSDB(is_premium=False, leagues=PREMIUM + FREE)

    refresher._discover_from_provider(prov)

    for code in PREMIUM:
        assert code not in prov.fetched, f"premium league {code} should be skipped"
    for code in FREE:
        assert code in prov.fetched, f"free league {code} should be fetched"


def test_premium_tsdb_leagues_included_with_key():
    conn = _db()
    refresher = CacheRefresher(db_factory=_shared_factory(conn))
    prov = _FakeTSDB(is_premium=True, leagues=PREMIUM + FREE)

    refresher._discover_from_provider(prov)

    assert prov.fetched == set(PREMIUM + FREE)


def test_premium_tsdb_leagues_query():
    conn = _db()
    refresher = CacheRefresher(db_factory=_shared_factory(conn))
    premium = refresher._premium_tsdb_leagues()
    # The known premium-tier codes are present; free-tier ones are not.
    assert set(PREMIUM).issubset(premium)
    assert premium.isdisjoint(FREE)
