"""Failed matches are remembered between runs (#754, flag-gated).

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
    monkeypatch.setenv("TEAMARR_NEGATIVE_CACHE", "1")


def _matcher(db_factory, **kw):
    return StreamMatcher(
        service=None, db_factory=db_factory, group_id=1, search_leagues=["mlb"],
        include_leagues=["mlb"], include_final_events=False, sport_durations={},
        generation=7, shared_events={}, name_match_enabled=True, **kw,
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
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("TEAMARR_NEGATIVE_CACHE", raising=False)
        assert _negative_cache_enabled() is False

    @pytest.mark.parametrize("v", ["0", "false", "no", "off", ""])
    def test_falsey_values_stay_off(self, monkeypatch, v):
        monkeypatch.setenv("TEAMARR_NEGATIVE_CACHE", v)
        assert _negative_cache_enabled() is False

    def test_nothing_written_when_off(self, monkeypatch, db_factory):
        monkeypatch.delenv("TEAMARR_NEGATIVE_CACHE", raising=False)
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
        [FailedReason.DATE_MISMATCH, FailedReason.NO_EVENT_CARD_MATCH,
         FailedReason.CANDIDATES_GATED, FailedReason.NO_RACING_MATCH],
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
        m._remember_failure(
            [_matched_outcome(), _failed(FailedReason.NO_EVENT_FOUND)], 1, "S")
        with db_factory() as c:
            assert c.execute("SELECT COUNT(*) FROM stream_match_cache").fetchone()[0] == 0

    def test_mixed_reasons_are_not_cached(self, on, db_factory):
        m = _matcher(db_factory)
        m._remember_failure(
            [_failed(FailedReason.NO_EVENT_FOUND),
             _failed(FailedReason.FIXTURE_NOT_IN_LEAGUE)], 1, "S")
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

    def test_miss_returns_none(self, on, db_factory):
        m = _matcher(db_factory)
        assert m._cached_failure(self._classified(), 99, "never seen") is None

    def test_hit_is_ignored_when_the_flag_is_off(self, on, db_factory, monkeypatch):
        m = _matcher(db_factory)
        m._remember_failure([_failed(FailedReason.NO_EVENT_FOUND)], 1, "S")
        monkeypatch.delenv("TEAMARR_NEGATIVE_CACHE", raising=False)
        assert m._cached_failure(self._classified(), 1, "S") is None

    def test_a_reason_no_longer_allowlisted_is_re_matched(self, on, db_factory):
        """Written by an older build, or the allowlist shrank — don't trust it."""
        StreamMatchCache(db_factory).set_failed(
            group_id=1, stream_id=1, stream_name="S", generation=7,
            reason=FailedReason.DATE_MISMATCH.value)
        m = _matcher(db_factory)
        assert m._cached_failure(self._classified(), 1, "S") is None

    def test_a_reasonless_failed_row_is_re_matched(self, on, db_factory):
        """Rows from before this change carry no reason and must not be trusted."""
        StreamMatchCache(db_factory).set_failed(
            group_id=1, stream_id=1, stream_name="S", generation=7)
        m = _matcher(db_factory)
        assert m._cached_failure(self._classified(), 1, "S") is None

    def test_a_successful_match_row_is_not_read_as_a_failure(self, on, db_factory):
        StreamMatchCache(db_factory).set(
            group_id=1, stream_id=1, stream_name="S", event_id="e1", league="mlb",
            cached_data={"id": "e1"}, generation=7)
        m = _matcher(db_factory)
        assert m._cached_failure(self._classified(), 1, "S") is None


class TestNoDatabase:
    def test_matcher_without_a_db_factory_does_not_explode(self, on):
        """StreamMatchCache(None) raises on every call; both paths must guard."""
        # days_ahead pinned so __init__ never touches db_factory (see tests/fakes.py)
        m = _matcher(None, days_ahead=3)
        from teamarr.consumers.matching.classifier import classify_stream

        assert m._cached_failure(classify_stream("Rays vs Tigers"), 1, "S") is None
        m._remember_failure([_failed(FailedReason.NO_EVENT_FOUND)], 1, "S")  # no raise
