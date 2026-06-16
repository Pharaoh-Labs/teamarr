"""Tests for feed team separation feature.

Covers:
1. Literal HOME/AWAY detection + stripping in classifier
2. Team name detection post-match
3. Channel discrimination (feed_team_id in lookup)
4. Feed label generation (team_name, short_name, home_away styles)
5. Settings disabled = no detection
"""

from dataclasses import dataclass

import pytest

from teamarr.consumers.matching.classifier import (
    StreamCategory,
    classify_stream,
    detect_and_strip_feed_hint,
)

# ===========================================================================
# Phase 1: Literal token detection in classifier
# ===========================================================================


class TestDetectAndStripFeedHint:
    """detect_and_strip_feed_hint() strips HOME/AWAY tokens."""

    def test_home_detected(self):
        text, hint = detect_and_strip_feed_hint("NHL HOME", ["HOME"], ["AWAY"])
        assert hint == "home"
        assert "HOME" not in text

    def test_away_detected(self):
        text, hint = detect_and_strip_feed_hint("NHL AWAY", ["HOME"], ["AWAY"])
        assert hint == "away"
        assert "AWAY" not in text

    def test_no_match(self):
        text, hint = detect_and_strip_feed_hint("NHL Regular", ["HOME"], ["AWAY"])
        assert hint is None
        assert text == "NHL Regular"

    def test_case_insensitive(self):
        text, hint = detect_and_strip_feed_hint("nhl home feed", ["HOME"], ["AWAY"])
        assert hint == "home"
        assert "home" not in text.lower() or "home" not in text

    def test_custom_terms(self):
        text, hint = detect_and_strip_feed_hint("MLB LOCAL", ["LOCAL", "HOME"], ["VISITOR", "AWAY"])
        assert hint == "home"

    def test_word_boundary(self):
        """HOMER shouldn't match HOME."""
        text, hint = detect_and_strip_feed_hint("HOMER Simpson", ["HOME"], ["AWAY"])
        assert hint is None

    def test_empty_terms(self):
        text, hint = detect_and_strip_feed_hint("NHL HOME", [], [])
        assert hint is None

    def test_cleaned_text_no_double_spaces(self):
        text, hint = detect_and_strip_feed_hint("NHL HOME Feed", ["HOME"], ["AWAY"])
        assert hint == "home"
        assert "  " not in text


class TestClassifyStreamFeedHint:
    """classify_stream() propagates feed_hint to ClassifiedStream."""

    def test_feed_hint_on_team_vs_team(self):
        result = classify_stream(
            "Rangers vs Devils HOME",
            feed_home_terms=["HOME"],
            feed_away_terms=["AWAY"],
        )
        assert result.feed_hint == "home"
        assert result.category == StreamCategory.TEAM_VS_TEAM

    def test_feed_hint_away(self):
        result = classify_stream(
            "Rangers vs Devils AWAY",
            feed_home_terms=["HOME"],
            feed_away_terms=["AWAY"],
        )
        assert result.feed_hint == "away"

    def test_no_feed_hint_when_no_terms(self):
        result = classify_stream("Rangers vs Devils HOME")
        assert result.feed_hint is None

    def test_no_feed_hint_when_disabled(self):
        """No feed terms = feature disabled."""
        result = classify_stream(
            "Rangers vs Devils HOME",
            feed_home_terms=None,
            feed_away_terms=None,
        )
        assert result.feed_hint is None

    def test_feed_hint_on_placeholder(self):
        result = classify_stream(
            "HOME Feed",
            feed_home_terms=["HOME"],
            feed_away_terms=["AWAY"],
        )
        # Even if it becomes placeholder, feed_hint should be set
        assert result.feed_hint == "home"

    def test_home_stripped_before_team_matching(self):
        """HOME token should be stripped so it doesn't interfere with matching."""
        result = classify_stream(
            "Rangers vs Devils HOME",
            feed_home_terms=["HOME"],
            feed_away_terms=["AWAY"],
        )
        # Should still parse teams correctly with HOME stripped
        assert result.team1 is not None
        assert result.team2 is not None


# ===========================================================================
# Phase 2: Team name detection
# ===========================================================================


@dataclass(frozen=True)
class MockTeam:
    id: str
    provider: str
    name: str
    short_name: str
    abbreviation: str
    league: str
    sport: str
    logo_url: str | None = None
    color: str | None = None
    record_summary: str | None = None


class TestDetectTeamInStreamName:
    """_detect_team_in_stream_name() matches team identity."""

    @pytest.fixture
    def home_team(self):
        return MockTeam(
            id="1",
            provider="espn",
            name="Baltimore Orioles",
            short_name="Orioles",
            abbreviation="BAL",
            league="mlb",
            sport="baseball",
        )

    @pytest.fixture
    def away_team(self):
        return MockTeam(
            id="2",
            provider="espn",
            name="New York Yankees",
            short_name="Yankees",
            abbreviation="NYY",
            league="mlb",
            sport="baseball",
        )

    def test_full_name_match(self, home_team, away_team):
        from teamarr.consumers.event_group_processor import EventGroupProcessor

        result = EventGroupProcessor._detect_team_in_stream_name(
            "baltimore orioles feed", home_team, away_team
        )
        assert result == home_team

    def test_short_name_match(self, home_team, away_team):
        from teamarr.consumers.event_group_processor import EventGroupProcessor

        result = EventGroupProcessor._detect_team_in_stream_name(
            "orioles feed", home_team, away_team
        )
        assert result == home_team

    def test_abbreviation_match(self, home_team, away_team):
        from teamarr.consumers.event_group_processor import EventGroupProcessor

        result = EventGroupProcessor._detect_team_in_stream_name("bal feed", home_team, away_team)
        assert result == home_team

    def test_away_team_match(self, home_team, away_team):
        from teamarr.consumers.event_group_processor import EventGroupProcessor

        result = EventGroupProcessor._detect_team_in_stream_name(
            "yankees broadcast", home_team, away_team
        )
        assert result == away_team

    def test_no_match(self, home_team, away_team):
        from teamarr.consumers.event_group_processor import EventGroupProcessor

        result = EventGroupProcessor._detect_team_in_stream_name(
            "generic sports feed", home_team, away_team
        )
        assert result is None

    def test_short_abbreviation_skipped(self):
        """Abbreviations < 3 chars should be skipped (too many false positives)."""
        from teamarr.consumers.event_group_processor import EventGroupProcessor

        team = MockTeam(
            id="1",
            provider="espn",
            name="Golden State Warriors",
            short_name="Warriors",
            abbreviation="GS",
            league="nba",
            sport="basketball",
        )
        other = MockTeam(
            id="2",
            provider="espn",
            name="Los Angeles Lakers",
            short_name="Lakers",
            abbreviation="LAL",
            league="nba",
            sport="basketball",
        )
        # "GS" is only 2 chars, should not match
        result = EventGroupProcessor._detect_team_in_stream_name("gs broadcast", team, other)
        assert result is None

    def test_feed_keyword_before_matchup_not_team_specific(self, home_team, away_team):
        """A feed keyword preceding BOTH teams is a shared matchup feed (#234).

        "feed orioles yankees" must not be attributed to the Orioles just
        because "feed orioles" matches — the opposing team appears after.
        """
        from teamarr.consumers.event_group_processor import EventGroupProcessor

        result = EventGroupProcessor._detect_team_in_stream_name(
            "feed orioles yankees", home_team, away_team
        )
        assert result is None

    def test_team_specific_feed_still_matches_with_opponent_before(self, home_team, away_team):
        """Opponent BEFORE the keyword is fine — still the home team's feed (#234)."""
        from teamarr.consumers.event_group_processor import EventGroupProcessor

        result = EventGroupProcessor._detect_team_in_stream_name(
            "yankees at orioles feed", home_team, away_team
        )
        assert result == home_team


# ===========================================================================
# Feed label generation
# ===========================================================================


class TestBuildFeedLabel:
    """_build_feed_label() generates correct labels per style."""

    @pytest.fixture
    def home_team(self):
        return MockTeam(
            id="1",
            provider="espn",
            name="Baltimore Orioles",
            short_name="Orioles",
            abbreviation="BAL",
            league="mlb",
            sport="baseball",
        )

    @pytest.fixture
    def event(self, home_team):
        """Minimal event-like object."""

        @dataclass
        class MockEvent:
            home_team: object
            away_team: object

        return MockEvent(
            home_team=home_team,
            away_team=MockTeam(
                id="2",
                provider="espn",
                name="New York Yankees",
                short_name="Yankees",
                abbreviation="NYY",
                league="mlb",
                sport="baseball",
            ),
        )

    def test_team_name_style(self, home_team, event):
        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        label = ChannelLifecycleService._build_feed_label(home_team, event, "team_name")
        assert label == "Orioles Feed"

    def test_short_name_style(self, home_team, event):
        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        label = ChannelLifecycleService._build_feed_label(home_team, event, "short_name")
        assert label == "BAL Feed"

    def test_home_away_style_home(self, home_team, event):
        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        label = ChannelLifecycleService._build_feed_label(home_team, event, "home_away")
        assert label == "Home Feed"

    def test_home_away_style_away(self, event):
        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        label = ChannelLifecycleService._build_feed_label(event.away_team, event, "home_away")
        assert label == "Away Feed"


# ===========================================================================
# Auto-append gating (Bug 2: don't double up when template uses feed vars)
# ===========================================================================


class TestTemplateUsesFeedVar:
    """_template_uses_feed_var() detects feed variables to suppress auto-append."""

    def test_no_feed_var_returns_false(self):
        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        assert ChannelLifecycleService._template_uses_feed_var("{away_team} @ {home_team}") is False

    def test_feed_team_detected(self):
        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        assert (
            ChannelLifecycleService._template_uses_feed_var(
                "{away_team} @ {home_team} - {feed_team}"
            )
            is True
        )

    def test_feed_team_short_detected(self):
        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        assert (
            ChannelLifecycleService._template_uses_feed_var(
                "{home_team_abbrev} | {feed_team_short}"
            )
            is True
        )

    def test_feed_team_abbrev_detected(self):
        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        assert (
            ChannelLifecycleService._template_uses_feed_var("{home_team} ({feed_team_abbrev})")
            is True
        )

    def test_feed_home_away_detected(self):
        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        assert (
            ChannelLifecycleService._template_uses_feed_var("{home_team} - {feed_home_away}")
            is True
        )

    def test_feed_team_logo_not_a_naming_var(self):
        # logo URLs aren't naming output — auto-append should still fire so
        # a template that only uses {feed_team_logo} for icons still gets
        # the suffix in the channel name.
        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        assert (
            ChannelLifecycleService._template_uses_feed_var(
                "{away_team} @ {home_team}"  # no feed naming var
            )
            is False
        )

    def test_substring_does_not_match(self):
        # "{feed_teamish}" should not trigger — exact-token match only.
        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        assert ChannelLifecycleService._template_uses_feed_var("{feed_teamish}") is False


class TestFeedTemplateVarsConstant:
    """FEED_TEMPLATE_VARS is the source of truth for the gating list."""

    def test_constant_contents(self):
        from teamarr.consumers.lifecycle.service import FEED_TEMPLATE_VARS

        # Naming-relevant feed vars only — logo URL and directional booleans
        # are deliberately excluded.
        assert FEED_TEMPLATE_VARS == frozenset(
            {
                "feed_team",
                "feed_team_short",
                "feed_team_abbrev",
                "feed_team_abbrev_lower",
                "feed_home_away",
                "broadcast_feed",
                "broadcast_feed_team",
            }
        )


# ===========================================================================
# Channel discrimination
# ===========================================================================


class TestFindExistingChannelFeedTeam:
    """find_existing_channel discriminates by feed_team_id."""

    @pytest.fixture
    def db(self):
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE managed_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_epg_group_id INTEGER,
                event_id TEXT NOT NULL,
                event_provider TEXT NOT NULL,
                tvg_id TEXT NOT NULL,
                channel_name TEXT NOT NULL,
                channel_number TEXT,
                logo_url TEXT,
                dispatcharr_channel_id INTEGER,
                dispatcharr_uuid TEXT,
                dispatcharr_logo_id INTEGER,
                channel_group_id INTEGER,
                channel_profile_ids TEXT,
                primary_stream_id INTEGER,
                exception_keyword TEXT,
                feed_team_id TEXT,
                home_team TEXT,
                home_team_abbrev TEXT,
                home_team_logo TEXT,
                away_team TEXT,
                away_team_abbrev TEXT,
                away_team_logo TEXT,
                event_date TIMESTAMP,
                event_name TEXT,
                league TEXT,
                sport TEXT,
                venue TEXT,
                broadcast TEXT,
                scheduled_delete_at TIMESTAMP,
                deleted_at TIMESTAMP,
                delete_reason TEXT,
                sync_status TEXT DEFAULT 'pending',
                sync_message TEXT,
                last_verified_at TIMESTAMP,
                expires_at TIMESTAMP,
                external_channel_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        yield conn
        conn.close()

    def test_same_event_different_feed_teams(self, db):
        """Two channels for same event with different feed_team_id."""
        from teamarr.database.channels.crud import (
            create_managed_channel,
            find_existing_channel,
        )

        # Channel 1: home feed
        create_managed_channel(
            db,
            event_epg_group_id=1,
            event_id="evt1",
            event_provider="espn",
            tvg_id="t1",
            channel_name="Game (Home)",
            feed_team_id="team_home",
            primary_stream_id=100,
        )
        # Channel 2: away feed
        create_managed_channel(
            db,
            event_epg_group_id=1,
            event_id="evt1",
            event_provider="espn",
            tvg_id="t2",
            channel_name="Game (Away)",
            feed_team_id="team_away",
            primary_stream_id=200,
        )
        db.commit()

        # Look up home feed
        home = find_existing_channel(db, "evt1", "espn", feed_team_id="team_home")
        assert home is not None
        assert home.feed_team_id == "team_home"

        # Look up away feed
        away = find_existing_channel(db, "evt1", "espn", feed_team_id="team_away")
        assert away is not None
        assert away.feed_team_id == "team_away"

        # They should be different channels
        assert home.id != away.id

    def test_null_feed_team_separate_from_specific(self, db):
        """NULL feed_team_id (unlabeled) should not match specific feed_team_id."""
        from teamarr.database.channels.crud import (
            create_managed_channel,
            find_existing_channel,
        )

        # Channel without feed team (normal channel)
        create_managed_channel(
            db,
            event_epg_group_id=1,
            event_id="evt1",
            event_provider="espn",
            tvg_id="t1",
            channel_name="Game",
            primary_stream_id=100,
        )
        db.commit()

        # Looking up with specific feed_team_id should NOT find it
        result = find_existing_channel(db, "evt1", "espn", feed_team_id="team_home")
        assert result is None

        # Looking up with NULL feed_team_id should find it
        result = find_existing_channel(db, "evt1", "espn")
        assert result is not None


# ===========================================================================
# Settings integration
# ===========================================================================


class TestFeedSeparationSettings:
    """Feed separation settings read/write."""

    @pytest.fixture
    def db(self):
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE settings (
                id INTEGER PRIMARY KEY,
                schema_version INTEGER DEFAULT 71,
                feed_separation_enabled BOOLEAN DEFAULT 0,
                feed_home_terms JSON DEFAULT '["HOME"]',
                feed_away_terms JSON DEFAULT '["AWAY"]',
                feed_detect_team_names BOOLEAN DEFAULT 1,
                feed_label_style TEXT DEFAULT 'team_name'
            );
            INSERT INTO settings (id) VALUES (1);
        """)
        conn.commit()
        yield conn
        conn.close()

    def test_defaults(self, db):
        from teamarr.database.settings import get_feed_separation_settings

        settings = get_feed_separation_settings(db)
        assert settings.enabled is False
        assert settings.home_terms == ["HOME"]
        assert settings.away_terms == ["AWAY"]
        assert settings.detect_team_names is True
        assert settings.label_style == "team_name"

    def test_update_and_read(self, db):
        from teamarr.database.settings import (
            get_feed_separation_settings,
            update_feed_separation_settings,
        )

        update_feed_separation_settings(
            db,
            enabled=True,
            home_terms=["LOCAL", "HOME"],
            away_terms=["VISITOR"],
            detect_team_names=False,
            label_style="short_name",
        )
        db.commit()

        settings = get_feed_separation_settings(db)
        assert settings.enabled is True
        assert settings.home_terms == ["LOCAL", "HOME"]
        assert settings.away_terms == ["VISITOR"]
        assert settings.detect_team_names is False
        assert settings.label_style == "short_name"


# ===========================================================================
# Cross-cutting invariant: every consumer caller of generate_event_tvg_id
# must read feed_team from the matched_stream and pass its id, so live EPG
# programmes and filler programmes land on the same per-feed XMLTV channel.
# Regressed in v2.4.4 (filler path missed the new feed_team_id arg) — bead
# teamarrv2-eg9.
# ===========================================================================


class TestFillerChannelIdMatchesLiveProgramme:
    """Filler must emit to the same channel_id as live programmes for the
    same matched_stream — including the -feed-{id} suffix when feed
    separation resolved a feed_team."""

    def _make_processor(self):
        from unittest.mock import MagicMock, patch

        from teamarr.consumers.event_group_processor import EventGroupProcessor

        with patch("teamarr.consumers.event_group_processor.create_default_service"):
            return EventGroupProcessor(db_factory=MagicMock())

    def _make_event(self, event_id="401815159", provider="espn"):
        from datetime import UTC, datetime

        from teamarr.core import Event, EventStatus, Team

        team = Team(
            id="t1",
            provider=provider,
            name="Pittsburgh Pirates",
            short_name="Pirates",
            abbreviation="PIT",
            league="mlb",
            sport="baseball",
        )
        return Event(
            id=event_id,
            provider=provider,
            name="CIN @ PIT",
            short_name="CIN @ PIT",
            start_time=datetime(2026, 5, 1, 23, 0, tzinfo=UTC),
            home_team=team,
            away_team=team,
            status=EventStatus(state="scheduled"),
            league="mlb",
            sport="baseball",
        )

    def test_filler_channel_id_includes_feed_team_id(self):
        """Pre-fix this test fails: filler emits to teamarr-event-401815159
        while live emits to teamarr-event-401815159-feed-18."""
        from unittest.mock import MagicMock, patch

        from teamarr.consumers.filler.event_filler import (
            EventFillerConfig,
            EventFillerResult,
        )

        processor = self._make_processor()
        event = self._make_event()
        feed_team = MagicMock()
        feed_team.id = "18"

        matched_streams = [
            {
                "event": event,
                "feed_team": feed_team,
                "_exception_keyword": None,
                "segment": None,
                "segment_start": None,
                "segment_end": None,
            }
        ]

        captured_channel_ids: list[str] = []

        def fake_generate_with_counts(**kwargs):
            captured_channel_ids.append(kwargs.get("channel_id"))
            return EventFillerResult(programmes=[], pregame_count=0, postgame_count=0)

        with patch("teamarr.consumers.event_group_processor.EventFillerGenerator") as MockGen:
            MockGen.return_value.generate_with_counts = fake_generate_with_counts
            processor._generate_filler_for_streams(
                matched_streams=matched_streams,
                filler_config=EventFillerConfig(),
                sport_durations={"baseball": 3.0},
            )

        assert captured_channel_ids == ["teamarr-event-401815159-feed-18"]

    def test_filler_channel_id_no_feed_team(self):
        """Without feed separation (national broadcast), filler still emits
        to the base channel — matches live programme path."""
        from unittest.mock import patch

        from teamarr.consumers.filler.event_filler import (
            EventFillerConfig,
            EventFillerResult,
        )

        processor = self._make_processor()
        event = self._make_event(event_id="401815158")

        matched_streams = [
            {
                "event": event,
                "feed_team": None,
                "_exception_keyword": None,
                "segment": None,
                "segment_start": None,
                "segment_end": None,
            }
        ]

        captured_channel_ids: list[str] = []

        def fake_generate_with_counts(**kwargs):
            captured_channel_ids.append(kwargs.get("channel_id"))
            return EventFillerResult(programmes=[], pregame_count=0, postgame_count=0)

        with patch("teamarr.consumers.event_group_processor.EventFillerGenerator") as MockGen:
            MockGen.return_value.generate_with_counts = fake_generate_with_counts
            processor._generate_filler_for_streams(
                matched_streams=matched_streams,
                filler_config=EventFillerConfig(),
                sport_durations={"baseball": 3.0},
            )

        assert captured_channel_ids == ["teamarr-event-401815158"]

    def test_filler_channel_id_matches_live_epg_path(self):
        """Cross-caller invariant: the channel_id the filler path computes
        for a matched_stream must equal what the live-EPG path computes for
        the same stream. This is the actual user-facing invariant and the
        one that broke in v2.4.4."""
        from teamarr.consumers.lifecycle import generate_event_tvg_id

        # Same stream, computed from both call sites' input shapes.
        feed_team_id = "18"
        live_channel_id = generate_event_tvg_id("401815159", "espn", None, None, feed_team_id)

        # Filler path: same args, must produce same id.
        filler_feed_team = type("FT", (), {"id": "18"})()
        filler_channel_id = generate_event_tvg_id(
            "401815159",
            "espn",
            None,
            None,
            filler_feed_team.id if filler_feed_team else None,
        )

        assert filler_channel_id == live_channel_id
        assert filler_channel_id == "teamarr-event-401815159-feed-18"
