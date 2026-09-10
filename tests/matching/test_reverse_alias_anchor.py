"""The EPG anchor survives the reverse-alias retry (#716).

Reporter's log: 'PL: Brighton v Leeds United Hlts' airing at 22:30 was bound to
the 14:00 kick-off (Δ=510m). The primary pass correctly rejected every candidate
as CANDIDATES_GATED — the 90-minute anchor gate did its job — and then the
reverse-alias retry rebuilt the MatchContext without ``anchor_dt`` and matched
with no time gate at all.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.result import FailedReason
from teamarr.consumers.matching.team_matcher import MatchContext
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TODAY = datetime.now(UTC).date()
KICKOFF = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC) + timedelta(hours=14)


def _team(name: str, abbr: str) -> Team:
    return Team(
        id=f"t-{abbr}",
        provider="espn",
        name=name,
        short_name=name,
        abbreviation=abbr,
        league="eng.1",
        sport="soccer",
    )


def _event() -> Event:
    return Event(
        id="401879290",
        provider="espn",
        name="Leeds United at Brighton & Hove Albion",
        short_name="LEE @ BHA",
        start_time=KICKOFF,
        home_team=_team("Brighton & Hove Albion", "BHA"),
        away_team=_team("Leeds United", "LEE"),
        status=EventStatus(state="scheduled"),
        league="eng.1",
        sport="soccer",
    )


def _ctx(stream: str, anchor: datetime | None) -> MatchContext:
    classified = classify_stream(stream)
    return MatchContext(
        stream_name=stream,
        stream_id=2592,
        group_id=1,
        target_date=TODAY,
        generation=1,
        user_tz=ZoneInfo("UTC"),
        classified=classified,
        team1=classified.team1,
        team2=classified.team2,
        anchor_dt=anchor,
    )


STREAM = "PL: Brighton v Leeds United"
EVENTS = [("eng.1", _event())]


def test_reverse_alias_needed_the_builtin_alias_to_match_at_all():
    """Control: 'Brighton' resolves only through the built-in alias table, so an
    anchored programme at kick-off matches via the retry, not the primary pass."""
    matcher = make_team_matcher()
    ctx = _ctx(STREAM, KICKOFF + timedelta(minutes=5))
    retry = matcher._try_reverse_alias_match(ctx, EVENTS, ["eng.1"])
    assert retry is not None and retry.is_matched
    assert retry.event is not None and retry.event.id == "401879290"


def test_primary_pass_gates_a_programme_hours_after_kickoff():
    matcher = make_team_matcher()
    ctx = _ctx(STREAM, KICKOFF + timedelta(hours=8, minutes=30))
    primary = matcher._match_against_multi_league_events(ctx, EVENTS)
    assert primary.failed_reason is FailedReason.CANDIDATES_GATED


def test_reverse_alias_retry_keeps_the_anchor_gate():
    """The retry must not bind the 22:30 highlights slot to the 14:00 kick-off."""
    matcher = make_team_matcher()
    ctx = _ctx(STREAM, KICKOFF + timedelta(hours=8, minutes=30))
    retry = matcher._try_reverse_alias_match(ctx, EVENTS, ["eng.1"])
    assert retry is None or not retry.is_matched


def test_unanchored_name_path_is_unchanged():
    """A plain stream name (no EPG anchor) still matches through the retry."""
    matcher = make_team_matcher()
    ctx = _ctx(STREAM, None)
    retry = matcher._try_reverse_alias_match(ctx, EVENTS, ["eng.1"])
    assert retry is not None and retry.is_matched
