"""Fuzzy event-name matching (Strategy 3) for combat event cards — PR #239.

Named combat events without a standard number (e.g. "UFC at the White House")
should fuzzy-match an event by name, while generic streams (just "UFC | Main
Card") should NOT match anything. event_hint / team1 / team2 are None so
strategies 1 (event number) and 2 (fighter names) are skipped and strategy 3 is
exercised in isolation; it only reads ``event.name``, so stand-in events suffice.
"""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import StreamCategory, classify_stream
from teamarr.consumers.matching.event_matcher import EventCardMatcher, EventMatchContext
from teamarr.consumers.matching.result import MatchMethod
from teamarr.core import Event, EventStatus, Team


def _ctx(stream_name: str) -> EventMatchContext:
    return EventMatchContext(
        stream_name=stream_name,
        stream_id=1,
        group_id=1,
        target_date=date(2026, 6, 14),
        generation=0,
        user_tz=ZoneInfo("UTC"),
        classified=SimpleNamespace(event_hint=None, team1=None, team2=None),
    )


def test_fuzzy_matches_named_event_without_number():
    matcher = EventCardMatcher(service=None, cache=None)
    ctx = _ctx("LIVE | UFC at the White House | Main Card")
    events = [
        SimpleNamespace(name="UFC Fight Night: Smith vs Jones"),
        SimpleNamespace(name="UFC at the White House: Topuria vs Gaethje"),
    ]
    outcome = matcher._match_to_event_card(ctx, events, "ufc")
    assert outcome.is_matched
    assert outcome.match_method == MatchMethod.FUZZY
    assert outcome.event is events[1]


def test_generic_stream_does_not_fuzzy_match():
    # All tokens are noise (ufc/live/main card) -> no distinct name -> no match.
    matcher = EventCardMatcher(service=None, cache=None)
    ctx = _ctx("LIVE | UFC | Main Card")
    events = [SimpleNamespace(name="UFC 300: Pereira vs Hill")]
    outcome = matcher._match_to_event_card(ctx, events, "ufc")
    assert not outcome.is_matched


def test_boxing_stream_matches_boundary_event_by_fighter_names():
    """A locally-Aug-22 card fetched from TSDB reaches the real matcher."""
    fighter1 = Team(
        id="2528767_1",
        provider="tsdb",
        name="Rolando Romero",
        short_name="R. Romero",
        abbreviation="ROMERO",
        league="boxing",
        sport="boxing",
    )
    fighter2 = Team(
        id="2528767_2",
        provider="tsdb",
        name="Teofimo Lopez",
        short_name="T. Lopez",
        abbreviation="LOPEZ",
        league="boxing",
        sport="boxing",
    )
    event = Event(
        id="2528767",
        provider="tsdb",
        name="Rolando Romero vs Teofimo Lopez",
        short_name="LOPEZ vs ROMERO",
        start_time=datetime(2026, 8, 23, 1, tzinfo=UTC),
        home_team=fighter1,
        away_team=fighter2,
        status=EventStatus(state="scheduled"),
        league="boxing",
        sport="boxing",
    )
    service = MagicMock()
    service.get_provider_name.return_value = "tsdb"
    service.get_events.return_value = [event]
    cache = MagicMock()
    cache.get.return_value = None
    classified = classify_stream(
        "LIVE EVENT 02 - 6/8pm Rolly v Teofimo",
        league_event_type="event_card",
        event_league_sport="boxing",
    )
    assert classified.category is StreamCategory.EVENT_CARD

    outcome = EventCardMatcher(service, cache).match(
        classified=classified,
        league="boxing",
        target_date=date(2026, 8, 22),
        group_id=1,
        stream_id=2,
        generation=1,
        user_tz=ZoneInfo("America/New_York"),
    )

    assert outcome.is_matched
    assert outcome.event is event
    assert outcome.match_method is MatchMethod.FUZZY
    service.get_events.assert_called_once_with("boxing", date(2026, 8, 22), cache_only=True)
