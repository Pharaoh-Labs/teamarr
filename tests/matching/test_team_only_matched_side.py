"""TEAM_ONLY matches record which event side the branded team is (#489).

match_team_only historically discarded the side returned by
_score_single_team_against_event, so the lifecycle could not tell which
team a team-branded stream belongs to. The matched_side field carries it
to the per-stream feed_team_id persistence that drives the
team_feed/not_team_feed ordering rules.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import classify_stream
from tests.fakes import FakeTeam, make_event, make_team_matcher

UTC_TZ = ZoneInfo("UTC")
TARGET = date(2026, 3, 1)


def _brewers_event(home: bool):
    brewers = FakeTeam(id="158", name="Milwaukee Brewers", abbreviation="MIL")
    cubs = FakeTeam(id="16", name="Chicago Cubs", abbreviation="CHC")
    return make_event(
        id="401",
        league="mlb",
        sport="baseball",
        start_time=datetime(2026, 3, 1, 20, 0, tzinfo=UTC),
        home_team=brewers if home else cubs,
        away_team=cubs if home else brewers,
    )


def _match(event):
    matcher = make_team_matcher()
    classified = classify_stream("MLB | Milwaukee Brewers")
    return matcher.match_team_only(
        classified,
        enabled_leagues=["mlb"],
        target_date=TARGET,
        group_id=1,
        stream_id=999991,
        generation=1,
        user_tz=UTC_TZ,
        prefetched_events={"mlb": [event]},
    )


def test_matched_side_home():
    outcomes = _match(_brewers_event(home=True))
    assert len(outcomes) == 1 and outcomes[0].is_matched
    assert outcomes[0].matched_side == "home"


def test_matched_side_away():
    outcomes = _match(_brewers_event(home=False))
    assert len(outcomes) == 1 and outcomes[0].is_matched
    assert outcomes[0].matched_side == "away"
