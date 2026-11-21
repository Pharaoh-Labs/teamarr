"""Failed matches are remembered between runs (#754, enabled by default).

49% of match time went to streams that never match, and the same streams failed
identically every run. `StreamMatchCache` already had `set_failed`,
`is_failed_cached` and a purge policy — none of it wired up.

The risk this carries is invisible in the worst way: a cached failure suppresses
a match that would otherwise appear, and nothing errors. So the design is an
ALLOWLIST (a new FailedReason is never cached until measured) and a cache hit
must reproduce the EXACT reason the real attempt gave, or the failure taxonomy
the UI reads quietly flattens.

Allowlist membership was measured over 24 consecutive production run pairs —
see `_CACHEABLE_FAILED_REASONS` for the flip rates.
"""

import pytest

from teamarr.consumers.matching.matcher import (
    _CACHEABLE_FAILED_REASONS,
    StreamMatcher,
    _negative_cache_enabled,
)
from teamarr.consumers.matching.result import FailedReason, MatchOutcome
from teamarr.consumers.stream_match_cache import FAILED_MATCH_EVENT_ID, StreamMatchCache


@pytest.fixture
def on(monkeypatch):
    # Exercise the normal default-enabled path throughout the cache regressions.
    monkeypatch.delenv("TEAMARR_NEGATIVE_CACHE", raising=False)


def _matcher(db_factory, **kw):
    kw.setdefault("generation", 7)
    return StreamMatcher(
        service=None,
        db_factory=db_factory,
        group_id=1,
        search_leagues=["mlb"],
        include_leagues=["mlb"],
        include_final_events=False,
        sport_durations={},
        shared_events={},
        name_match_enabled=True,
        **kw,
    )


def _failed(reason):
    return MatchOutcome.failed(reason, stream_name="S", stream_id=1)


def _matched_outcome():
    """A MATCHED outcome without needing a real Event."""
    o = _failed(FailedReason.NO_EVENT_FOUND)
    from teamarr.consumers.matching.result import ResultCategory

    o.category = ResultCategory.MATCHED
    return o


class TestFlag:
    def test_on_by_default(self, monkeypatch):
        monkeypatch.delenv("TEAMARR_NEGATIVE_CACHE", raising=False)
        assert _negative_cache_enabled() is True

    @pytest.mark.parametrize("v", ["1", "true", "yes", "on", " TRUE ", "On"])
    def test_truthy_values_stay_on(self, monkeypatch, v):
        monkeypatch.setenv("TEAMARR_NEGATIVE_CACHE", v)
        assert _negative_cache_enabled() is True

    @pytest.mark.parametrize("v", ["0", "false", "no", "off", ""])
    def test_falsey_values_stay_off(self, monkeypatch, v):
        monkeypatch.setenv("TEAMARR_NEGATIVE_CACHE", v)
        assert _negative_cache_enabled() is False

    def test_nothing_written_when_off(self, monkeypatch, db_factory):
        monkeypatch.setenv("TEAMARR_NEGATIVE_CACHE", "0")
        m = _matcher(db_factory)
        m._remember_failure([_failed(FailedReason.NO_EVENT_FOUND)], 1, "S")
        with db_factory() as c:
            assert c.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0] == 0


class TestAllowlist:
    """A reason absent from the allowlist must never be cached."""

    @pytest.mark.parametrize("reason", sorted(_CACHEABLE_FAILED_REASONS, key=lambda r: r.value))
    def test_allowlisted_reasons_are_cached(self, on, db_factory, reason):
        m = _matcher(db_factory)
        m._remember_failure([_failed(reason)], 1, "S")
        entry = StreamMatchCache(db_factory).get(1, 1, "S", include_failed=True)
        assert entry is not None and entry.event_id == FAILED_MATCH_EVENT_ID
        assert entry.cached_data["failed_reason"] == reason.value

    @pytest.mark.parametrize(
        "reason",
        [
            FailedReason.DATE_MISMATCH,
            FailedReason.NO_EVENT_CARD_MATCH,
            FailedReason.CANDIDATES_GATED,
            FailedReason.NO_RACING_MATCH,
        ],
    )
    def test_churny_reasons_are_never_cached(self, on, db_factory, reason):
        """Measured flip rates 0.5-1.1% — these must keep re-matching."""
        assert reason not in _CACHEABLE_FAILED_REASONS
        m = _matcher(db_factory)
        m._remember_failure([_failed(reason)], 1, "S")
        with db_factory() as c:
            assert c.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0] == 0


class TestWhatIsNotRemembered:
    def test_a_stream_that_matched_is_not_cached_as_failed(self, on, db_factory):
        m = _matcher(db_factory)
        m._remember_failure([_matched_outcome()], 1, "S")
        with db_factory() as c:
            assert c.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0] == 0

    def test_partial_fanout_match_is_not_cached(self, on, db_factory):
        """TEAM_ONLY fans out; one hit means the stream matched."""
        m = _matcher(db_factory)
        m._remember_failure([_matched_outcome(), _failed(FailedReason.NO_EVENT_FOUND)], 1, "S")
        with db_factory() as c:
            assert c.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0] == 0

    def test_mixed_reasons_are_not_cached(self, on, db_factory):
        m = _matcher(db_factory)
        m._remember_failure(
            [_failed(FailedReason.NO_EVENT_FOUND), _failed(FailedReason.FIXTURE_NOT_IN_LEAGUE)],
            1,
            "S",
        )
        with db_factory() as c:
            assert c.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0] == 0

    def test_no_outcomes_is_not_cached(self, on, db_factory):
        m = _matcher(db_factory)
        m._remember_failure([], 1, "S")
        with db_factory() as c:
            assert c.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0] == 0


class TestReadBack:
    def _classified(self, name="Rays vs Tigers"):
        from teamarr.consumers.matching.classifier import classify_stream

        return classify_stream(name)

    def test_hit_reports_the_same_reason_not_a_generic_one(self, on, db_factory):
        """The #747 lesson: never flatten the failure taxonomy."""
        m = _matcher(db_factory)
        m._remember_failure([_failed(FailedReason.FIXTURE_NOT_IN_LEAGUE)], 1, "S")

        got = m._cached_failure(self._classified(), 1, "S")
        assert got is not None
        assert got[0].failed_reason is FailedReason.FIXTURE_NOT_IN_LEAGUE
        assert got[0].matched is False
        assert got[0].from_cache is True

    def test_a_replayed_failure_is_a_sighting_and_survives_the_purge(self, on, db_factory):
        """A hit refreshes last_seen_generation like a success hit does (#1101).

        Without the touch, a failure written at generation N kept that stamp
        through every replay, purge_stale dropped it at N + 3, and every
        never-matching stream was re-scored on a fixed three-run cycle.
        """
        _matcher(db_factory)._remember_failure([_failed(FailedReason.NO_EVENT_FOUND)], 1, "S")
        cache = StreamMatchCache(db_factory)
        for generation in range(8, 8 + 3 * StreamMatchCache.PURGE_FAILED_AFTER_GENERATIONS):
            cache.purge_stale(generation)  # what every run does first
            got = _matcher(db_factory, generation=generation)._cached_failure(
                self._classified(), 1, "S"
            )
            assert got is not None, f"failure purged before generation {generation}"
            with db_factory() as c:
                stamp = c.execute("SELECT last_seen_generation FROM stream_match_cache").fetchone()[
                    0
                ]
            assert stamp == generation

    def test_miss_returns_none(self, on, db_factory):
        m = _matcher(db_factory)
        assert m._cached_failure(self._classified(), 99, "never seen") is None

    def test_hit_is_ignored_when_the_flag_is_off(self, on, db_factory, monkeypatch):
        m = _matcher(db_factory)
        m._remember_failure([_failed(FailedReason.NO_EVENT_FOUND)], 1, "S")
        monkeypatch.setenv("TEAMARR_NEGATIVE_CACHE", "0")
        assert m._cached_failure(self._classified(), 1, "S") is None

    def test_a_reason_no_longer_allowlisted_is_re_matched(self, on, db_factory):
        """Written by an older build, or the allowlist shrank — don't trust it."""
        StreamMatchCache(db_factory).set_failed(
            group_id=1,
            stream_id=1,
            stream_name="S",
            generation=7,
            reason=FailedReason.DATE_MISMATCH.value,
        )
        m = _matcher(db_factory)
        assert m._cached_failure(self._classified(), 1, "S") is None

    def test_a_reasonless_failed_row_is_re_matched(self, on, db_factory):
        """Rows from before this change carry no reason and must not be trusted."""
        StreamMatchCache(db_factory).set_failed(
            group_id=1, stream_id=1, stream_name="S", generation=7
        )
        m = _matcher(db_factory)
        assert m._cached_failure(self._classified(), 1, "S") is None

    def test_a_successful_match_row_is_not_read_as_a_failure(self, on, db_factory):
        StreamMatchCache(db_factory).set(
            group_id=1,
            stream_id=1,
            stream_name="S",
            event_id="e1",
            league="mlb",
            cached_data={"id": "e1"},
            generation=7,
        )
        m = _matcher(db_factory)
        assert m._cached_failure(self._classified(), 1, "S") is None

    def test_no_event_found_is_rechecked_when_target_date_advances(self, on, db_factory):
        """NO_EVENT_FOUND stays cached for runs on the same target_date, then
        re-evaluates when target_date rolls over to a new calendar day (#1264)."""
        from datetime import date

        day1 = date(2026, 11, 21)
        day2 = date(2026, 11, 22)
        m = _matcher(db_factory)
        m._remember_failure([_failed(FailedReason.NO_EVENT_FOUND)], 1, "S", target_date=day1)

        assert m._cached_failure(self._classified(), 1, "S", target_date=day1) is not None
        assert m._cached_failure(self._classified(), 1, "S", target_date=day2) is None

    @pytest.mark.parametrize("cached_date", [None, "2026-11-20", "2026-11-21", "no_entry"])
    def test_epg_match_does_not_pollute_negative_cache(
        self, on, db_factory, monkeypatch, cached_date
    ):
        """A stream that fails by name but matches via EPG in match_all must not
        leave a __FAILED__ entry in stream_match_cache (#1264)."""
        from datetime import date
        from unittest.mock import MagicMock

        from teamarr.consumers.matching.classifier import StreamCategory
        from teamarr.consumers.matching.matcher import MatchedStreamResult

        cache = StreamMatchCache(db_factory)
        if cached_date != "no_entry":
            cache.set_failed(
                1, 1, "Rays vs Tigers", 6, FailedReason.NO_EVENT_FOUND.value, cached_date
            )
        m = _matcher(db_factory, epg_index=MagicMock(unavailable=None))
        m._epg_index.is_linear.return_value = True
        m._prefetch_events = lambda *a, **kw: None
        monkeypatch.setattr(
            m,
            "_route_to_outcomes",
            lambda *a, **kw: [_failed(FailedReason.NO_EVENT_FOUND)],
        )
        monkeypatch.setattr(
            m,
            "_match_via_epg",
            lambda **kw: [
                MatchedStreamResult(
                    stream_name="S",
                    stream_id=1,
                    matched=True,
                    included=True,
                    category=StreamCategory.TEAM_VS_TEAM,
                )
            ],
        )

        res = m.match_all(
            [{"id": 1, "name": "Rays vs Tigers", "tvg_id": "ch1"}],
            date(2026, 11, 21),
        )

        assert res.matched_count == 1
        assert cache.get(1, 1, "Rays vs Tigers", include_failed=True) is None

    def test_legacy_no_event_found_is_rechecked(self, on, db_factory):
        from datetime import date

        cache = StreamMatchCache(db_factory)
        cache.set_failed(1, 1, "S", 6, FailedReason.NO_EVENT_FOUND.value)
        m = _matcher(db_factory)

        assert m._cached_failure(self._classified(), 1, "S", target_date=date(2026, 11, 21)) is None
        assert cache.get(1, 1, "S", include_failed=True) is None


class TestNoDatabase:
    def test_matcher_without_a_db_factory_does_not_explode(self, on):
        """StreamMatchCache(None) raises on every call; both paths must guard."""
        # days_ahead pinned so __init__ never touches db_factory (see tests/fakes.py)
        m = _matcher(None, days_ahead=3)
        from teamarr.consumers.matching.classifier import classify_stream

        assert m._cached_failure(classify_stream("Rays vs Tigers"), 1, "S") is None
        m._remember_failure([_failed(FailedReason.NO_EVENT_FOUND)], 1, "S")  # no raise


@pytest.mark.parametrize("change", ["alias", "team_cache"])
def test_default_cached_failure_is_rechecked_after_config_change(
    monkeypatch, db_factory, db_path, change
):
    from fastapi.testclient import TestClient

    from teamarr.api.app import app
    from teamarr.consumers.matching.classifier import classify_stream
    from teamarr.database.team_cache import invalidate_team_identity_caches

    monkeypatch.delenv("TEAMARR_NEGATIVE_CACHE", raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    matcher = _matcher(db_factory)
    name = "Rays vs Tigers"
    classified = classify_stream(name)
    matcher._remember_failure([_failed(FailedReason.NO_EVENT_FOUND)], 1, name)
    assert matcher._cached_failure(classified, 1, name) is not None

    if change == "alias":
        response = TestClient(app).post(
            "/api/v1/aliases",
            json={
                "alias": "D-backs",
                "league": "mlb",
                "team_id": "29",
                "team_name": "Arizona Diamondbacks",
            },
        )
        assert response.status_code == 201, response.text
    else:
        invalidate_team_identity_caches()

    assert matcher._cached_failure(classified, 1, name) is None
