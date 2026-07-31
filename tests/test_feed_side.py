"""Tri-state feed side: home / away / UNKNOWN (#533).

The governing rule under test everywhere in this file: **unknown is never
inferred**. No code path may reach "away" by failing to prove "home". Each
consumer gets an explicit unknown case asserting it is treated as neither
side — that assertion is the point of the file, not an edge case in it.
"""

from datetime import UTC, datetime

import pytest

from teamarr.consumers.lifecycle.feed_side import resolve_feed_side
from teamarr.consumers.lifecycle.naming import ChannelNaming
from teamarr.core import Event, EventStatus, Team
from teamarr.database.channels.types import ManagedChannelStream
from teamarr.database.settings.types import (
    NO_VALUE_RULE_TYPES,
    VALID_RULE_TYPES,
    StreamOrderingRule,
)
from teamarr.services.stream_ordering import NO_MATCH_PRIORITY, StreamOrderingService


def _team(team_id: str, name: str, abbrev: str, short: str) -> Team:
    return Team(
        id=team_id,
        provider="espn",
        name=name,
        short_name=short,
        abbreviation=abbrev,
        league="mlb",
        sport="baseball",
    )


HOME_TEAM = _team("23", "Pittsburgh Pirates", "PIT", "Pirates")
AWAY_TEAM = _team("16", "Chicago Cubs", "CHC", "Cubs")
STRANGER = _team("99", "Cincinnati Reds", "CIN", "Reds")


def _event(home: Team | None = HOME_TEAM, away: Team | None = AWAY_TEAM) -> Event:
    return Event(
        id="401",
        provider="espn",
        name="CHC @ PIT",
        short_name="CHC @ PIT",
        start_time=datetime(2026, 5, 1, 23, 0, tzinfo=UTC),
        home_team=home,  # type: ignore[arg-type]  # None models a sideless sport
        away_team=away,  # type: ignore[arg-type]
        status=EventStatus(state="scheduled"),
        league="mlb",
        sport="baseball",
    )


# --- resolver ---------------------------------------------------------------


class TestResolveFeedSide:
    def test_explicit_feed_hint_wins(self):
        assert resolve_feed_side(_event(), feed_hint="home") == "home"
        assert resolve_feed_side(_event(), feed_hint="away") == "away"

    def test_matched_side_used_when_no_hint(self):
        assert resolve_feed_side(_event(), matched_side="away") == "away"

    def test_derived_from_team_id(self):
        assert resolve_feed_side(_event(), feed_team_id="23") == "home"
        assert resolve_feed_side(_event(), feed_team_id="16") == "away"

    def test_hint_takes_precedence_over_derivation(self):
        # Explicit signal beats derivation; they should agree in practice, but
        # the cascade order must be deterministic.
        assert resolve_feed_side(_event(), feed_hint="away", feed_team_id="23") == "away"

    # --- the unknowns: each must be None, never coerced to a side -----------

    def test_unknown_when_not_told(self):
        """No signal at all — the common case, not an edge case."""
        assert resolve_feed_side(_event()) is None

    def test_unknown_when_team_matches_neither_side(self):
        assert resolve_feed_side(_event(), feed_team_id=STRANGER.id) is None

    def test_unknown_when_no_event(self):
        assert resolve_feed_side(None, feed_team_id="23") is None

    def test_unknown_when_sport_has_no_sides(self):
        """Racing/combat: a team can be known while a side is meaningless."""
        assert resolve_feed_side(_event(home=None, away=None), feed_team_id="23") is None

    def test_garbage_hint_is_unknown_not_away(self):
        assert resolve_feed_side(_event(), feed_hint="HOME-ish") is None
        assert resolve_feed_side(_event(), matched_side="neither") is None

    @pytest.mark.parametrize("bad", ["", "  ", "Home", "AWAY", "h", None])
    def test_only_exact_lowercase_sides_accepted(self, bad):
        """Near-misses resolve to unknown rather than silently picking a side."""
        assert resolve_feed_side(_event(), feed_hint=bad) is None

    def test_neutral_site_keeps_provider_designation(self):
        """D3: we were told a nominal home side, so we report it."""
        assert resolve_feed_side(_event(), feed_team_id=HOME_TEAM.id) == "home"


# --- ordering rules ---------------------------------------------------------


def _stream(feed_side: str | None) -> ManagedChannelStream:
    return ManagedChannelStream(
        id=1,
        managed_channel_id=1,
        dispatcharr_stream_id=1,
        stream_name="Some Stream",
        feed_side=feed_side,
    )


class TestFeedSideOrderingRules:
    def _svc(self, *rules: StreamOrderingRule) -> StreamOrderingService:
        svc = StreamOrderingService.__new__(StreamOrderingService)
        svc.rules = list(rules)
        svc._team_feed_patterns = {}
        svc._team_feed_ids = {}
        svc._has_score_rules = any(r.mode == "score" for r in rules)
        return svc

    def test_home_rule_matches_only_home(self):
        svc = self._svc(StreamOrderingRule(type="home_feed", value="", priority=1))
        assert svc.compute_priority(_stream("home")) == 1
        assert svc.compute_priority(_stream("away")) == NO_MATCH_PRIORITY

    def test_away_rule_matches_only_away(self):
        svc = self._svc(StreamOrderingRule(type="away_feed", value="", priority=1))
        assert svc.compute_priority(_stream("away")) == 1
        assert svc.compute_priority(_stream("home")) == NO_MATCH_PRIORITY

    def test_unknown_matches_neither_rule(self):
        """The core guarantee: unknown is not swept into either side."""
        svc = self._svc(
            StreamOrderingRule(type="home_feed", value="", priority=1),
            StreamOrderingRule(type="away_feed", value="", priority=2),
        )
        assert svc.compute_priority(_stream(None)) == NO_MATCH_PRIORITY

    def test_unknown_falls_to_catch_all_not_to_a_side(self):
        svc = self._svc(
            StreamOrderingRule(type="home_feed", value="", priority=1),
            StreamOrderingRule(type="away_feed", value="", priority=2),
            StreamOrderingRule(type="catch_all", value="", priority=50),
        )
        assert svc.compute_priority(_stream(None)) == 50

    def test_no_name_regex_fallback(self):
        """A stream *named* home but with no persisted side stays unknown —
        the name signal is consumed upstream at resolution time (D1)."""
        svc = self._svc(StreamOrderingRule(type="home_feed", value="", priority=1))
        stream = _stream(None)
        stream.stream_name = "Pirates HOME Feed"
        assert svc.compute_priority(stream) == NO_MATCH_PRIORITY

    def test_score_mode_weights_without_banding(self):
        svc = self._svc(
            StreamOrderingRule(type="home_feed", value="", priority=1, mode="score", points=25),
            StreamOrderingRule(type="catch_all", value="", priority=50),
        )
        home = svc.compute_priority(_stream("home"))
        unknown = svc.compute_priority(_stream(None))
        assert home < unknown, "home feed should sort ahead of unknown under score mode"


# --- registry parity --------------------------------------------------------


def test_rule_types_registered():
    assert {"home_feed", "away_feed"} <= VALID_RULE_TYPES
    assert {"home_feed", "away_feed"} <= NO_VALUE_RULE_TYPES


# --- channel label ----------------------------------------------------------


class TestHomeAwayLabel:
    def test_home_and_away_labels(self):
        assert ChannelNaming._build_feed_label(HOME_TEAM, _event(), "home_away") == "Home Feed"
        assert ChannelNaming._build_feed_label(AWAY_TEAM, _event(), "home_away") == "Away Feed"

    def test_unknown_renders_no_label_not_away(self):
        """Regression for the pre-#533 `if is_home else "Away Feed"` shape."""
        assert ChannelNaming._build_feed_label(STRANGER, _event(), "home_away") == ""

    def test_sideless_sport_renders_no_label(self):
        event = _event(home=None, away=None)
        assert ChannelNaming._build_feed_label(HOME_TEAM, event, "home_away") == ""

    def test_other_styles_unaffected(self):
        assert ChannelNaming._build_feed_label(HOME_TEAM, _event(), "team_name") == "Pirates Feed"
        assert ChannelNaming._build_feed_label(HOME_TEAM, _event(), "short_name") == "PIT Feed"
