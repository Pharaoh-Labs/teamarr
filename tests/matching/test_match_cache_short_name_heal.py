"""Self-healing for stale stream_match_cache rows missing short_name.

Reproduces issue #201: a user's stream_match_cache held cached_event_data
written before short_name flowed end-to-end (Team has name='Philadelphia
Phillies' but short_name=''). Variables like {home_team_short} resolved
blank for those events.

The fix: TeamMatcher._reconstruct_event treats a row with name set but
short_name empty as stale and returns None, forcing the matcher to
re-fetch and re-cache with proper data on the next pass.
"""

from teamarr.consumers.matching.team_matcher import TeamMatcher


def _make_cached(home_short: str, away_short: str) -> dict:
    """Build a cached_event_data dict like asdict(event) would."""
    return {
        "id": "401815214",
        "provider": "espn",
        "name": "Athletics at Philadelphia Phillies",
        "short_name": "ATH @ PHI",
        "start_time": "2026-05-05T22:40:00+00:00",
        "league": "mlb",
        "sport": "baseball",
        "status": {"state": "scheduled"},
        "home_team": {
            "id": "22",
            "provider": "espn",
            "name": "Philadelphia Phillies",
            "short_name": home_short,
            "abbreviation": "PHI",
            "league": "mlb",
            "sport": "baseball",
        },
        "away_team": {
            "id": "11",
            "provider": "espn",
            "name": "Athletics",
            "short_name": away_short,
            "abbreviation": "ATH",
            "league": "mlb",
            "sport": "baseball",
        },
        "broadcasts": [],
    }


def _matcher() -> TeamMatcher:
    """Build a bare TeamMatcher to call _reconstruct_event in isolation."""
    return TeamMatcher.__new__(TeamMatcher)


class TestReconstructInvalidatesStaleShortName:
    def test_fresh_row_is_reconstructed(self):
        """Properly-populated row reconstructs cleanly."""
        event = _matcher()._reconstruct_event(_make_cached("Phillies", "Athletics"))
        assert event is not None
        assert event.home_team.short_name == "Phillies"
        assert event.away_team.short_name == "Athletics"

    def test_stale_home_short_name_returns_none(self):
        """Home team with name but no short_name → cache miss."""
        event = _matcher()._reconstruct_event(_make_cached("", "Athletics"))
        assert event is None

    def test_stale_away_short_name_returns_none(self):
        """Away team with name but no short_name → cache miss."""
        event = _matcher()._reconstruct_event(_make_cached("Phillies", ""))
        assert event is None

    def test_both_empty_name_and_short_name_is_kept(self):
        """A team with no name AND no short_name is a placeholder, not stale."""
        cached = _make_cached("", "Athletics")
        cached["home_team"]["name"] = ""  # full placeholder team
        event = _matcher()._reconstruct_event(cached)
        assert event is not None
        assert event.home_team.name == ""
        assert event.home_team.short_name == ""

    def test_generated_preview_fields_survive_match_cache(self):
        """A cached match must retain the facts used by generated prose."""
        cached = _make_cached("Phillies", "Athletics")
        cached.update(
            {
                "away_team_record": "72-59",
                "home_probable_starter": "Tyler Phillips (3-6, 3.67 ERA)",
                "away_home_runs_leader": "Willson Contreras — 26 home runs",
            }
        )

        event = _matcher()._reconstruct_event(cached)

        assert event is not None
        assert event.away_team_record == "72-59"
        assert event.home_probable_starter == "Tyler Phillips (3-6, 3.67 ERA)"
        assert event.away_home_runs_leader == "Willson Contreras — 26 home runs"


class TestCheckCacheDateValidation:
    """Positive cache validation for upcoming date-pinned and multi-day events (#1264)."""

    @staticmethod
    def _ctx(stream_name: str, target_date):
        from zoneinfo import ZoneInfo

        from teamarr.consumers.matching.classifier import classify_stream
        from teamarr.consumers.matching.team_matcher import MatchContext

        classified = classify_stream(stream_name)
        return MatchContext(
            stream_name=stream_name,
            stream_id=1,
            group_id=1,
            target_date=target_date,
            generation=5,
            user_tz=ZoneInfo("UTC"),
            classified=classified,
            team1=classified.team1,
            team2=classified.team2,
        )

    def test_upcoming_event_hits_cache_when_stream_carries_trusted_date(self):
        from datetime import date
        from unittest.mock import MagicMock

        from teamarr.consumers.stream_match_cache import StreamCacheEntry
        from tests.fakes import make_team_matcher

        cached = _make_cached("Phillies", "Athletics")
        cached["start_time"] = "2026-05-06T18:00:00+00:00"
        cache = MagicMock()
        cache.get.return_value = StreamCacheEntry(
            event_id="401815214",
            league="mlb",
            cached_data=cached,
            match_method="fuzzy",
            user_corrected=False,
        )
        matcher = make_team_matcher(cache=cache)
        ctx = self._ctx("Athletics at Philadelphia Phillies - 2026-05-06", date(2026, 5, 5))
        # An upcoming event is a hit only while the run lists it, and the
        # listed object is the one served (here: same day, new start).
        listed = matcher._reconstruct_event({**cached, "start_time": "2026-05-06T20:00:00+00:00"})

        ctx.search_leagues, ctx.prefetched_events = ["mlb"], {"mlb": [listed]}

        outcome = matcher._check_cache(ctx)

        assert outcome is not None and outcome.is_matched
        assert outcome.event is listed
        cache.touch.assert_called_once_with(1, 1, ctx.stream_name, 5)

    def test_upcoming_event_misses_cache_without_touch_when_run_does_not_list_it(self):
        from datetime import date
        from unittest.mock import MagicMock

        from teamarr.consumers.stream_match_cache import StreamCacheEntry
        from tests.fakes import make_team_matcher

        cached = _make_cached("Phillies", "Athletics")
        cached["start_time"] = "2026-05-06T18:00:00+00:00"
        cache = MagicMock()
        cache.get.return_value = StreamCacheEntry(
            event_id="401815214",
            league="mlb",
            cached_data=cached,
            match_method="fuzzy",
            user_corrected=False,
        )
        matcher = make_team_matcher(cache=cache)
        ctx = self._ctx("Athletics at Philadelphia Phillies - 2026-05-06", date(2026, 5, 5))
        other = matcher._reconstruct_event({**cached, "id": "401815999"})

        ctx.search_leagues, ctx.prefetched_events = ["mlb"], {"mlb": [other]}
        assert matcher._check_cache(ctx) is None
        # The league the match was found in is no longer searched.
        listed = matcher._reconstruct_event(cached)
        ctx.search_leagues, ctx.prefetched_events = ["nhl"], {"mlb": [listed]}
        assert matcher._check_cache(ctx) is None
        cache.touch.assert_not_called()

    def test_upcoming_event_a_day_off_the_stream_date_misses_cache(self):
        from datetime import date
        from unittest.mock import MagicMock

        from teamarr.consumers.stream_match_cache import StreamCacheEntry
        from tests.fakes import make_team_matcher

        cached = _make_cached("Phillies", "Athletics")
        cached["start_time"] = "2026-05-06T18:00:00+00:00"
        cache = MagicMock()
        cache.get.return_value = StreamCacheEntry(
            event_id="401815214",
            league="mlb",
            cached_data=cached,
            match_method="fuzzy",
            user_corrected=False,
        )
        matcher = make_team_matcher(cache=cache)
        ctx = self._ctx("Athletics at Philadelphia Phillies - 2026-05-07", date(2026, 5, 5))
        listed = matcher._reconstruct_event(cached)

        ctx.search_leagues, ctx.prefetched_events = ["mlb"], {"mlb": [listed]}

        outcome = matcher._check_cache(ctx)

        assert outcome is None
        cache.touch.assert_not_called()

    def test_upcoming_event_misses_cache_without_touch_when_stream_has_no_date(self):
        from datetime import date
        from unittest.mock import MagicMock

        from teamarr.consumers.stream_match_cache import StreamCacheEntry
        from tests.fakes import make_team_matcher

        cached = _make_cached("Phillies", "Athletics")
        cached["start_time"] = "2026-05-06T18:00:00+00:00"
        cache = MagicMock()
        cache.get.return_value = StreamCacheEntry(
            event_id="401815214",
            league="mlb",
            cached_data=cached,
            match_method="fuzzy",
            user_corrected=False,
        )
        matcher = make_team_matcher(cache=cache)
        ctx = self._ctx("Athletics at Philadelphia Phillies", date(2026, 5, 5))

        outcome = matcher._check_cache(ctx)

        assert outcome is None
        cache.touch.assert_not_called()

    def test_multiday_event_with_session_today_hits_cache(self):
        from datetime import date
        from unittest.mock import MagicMock

        from teamarr.consumers.stream_match_cache import StreamCacheEntry
        from tests.fakes import make_team_matcher

        cached = _make_cached("Phillies", "Athletics")
        cached["start_time"] = "2026-05-03T10:00:00+00:00"
        cached["sessions"] = [
            {"code": "D1", "name": "Day 1", "start_time": "2026-05-03T10:00:00+00:00"},
            {"code": "D2", "name": "Day 2", "start_time": "2026-05-04T10:00:00+00:00"},
            {"code": "D3", "name": "Day 3", "start_time": "2026-05-05T10:00:00+00:00"},
        ]
        cache = MagicMock()
        cache.get.return_value = StreamCacheEntry(
            event_id="401815214",
            league="mlb",
            cached_data=cached,
            match_method="fuzzy",
            user_corrected=False,
        )
        matcher = make_team_matcher(cache=cache)
        ctx = self._ctx("Athletics at Philadelphia Phillies", date(2026, 5, 5))

        outcome = matcher._check_cache(ctx)

        assert outcome is not None and outcome.is_matched
        cache.touch.assert_called_once_with(1, 1, ctx.stream_name, 5)
