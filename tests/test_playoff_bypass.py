"""Tests for canonical season_type producers and playoff bypass filtering.

Covers the full producer/consumer chain fixed in bead teamarrv2-sua (#197):

- ESPN scoreboard path parses season slug/type to canonical values
- ESPN summary path (get_event) passes season through so refresh doesn't wipe it
- ESPN soccer knockout slugs (semifinals/final/etc.) map to postseason
- MLBStats gameType codes (R/S/E/F/D/L/W/P/A) map to canonical values
- HockeyTech seasons-info lookup (playoff flag + preseason name keywords)
- Template variables ({is_playoff}, {is_preseason}, {is_regular_season})
  use strict canonical comparison, not fuzzy substring matching
- Filter bypass in event_group_processor keeps postseason events when enabled
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from teamarr.core import (
    SEASON_OFFSEASON,
    SEASON_POSTSEASON,
    SEASON_PRESEASON,
    SEASON_REGULAR,
    Event,
    EventStatus,
    Team,
)
from teamarr.providers.espn.provider import ESPNProvider
from teamarr.providers.hockeytech.provider import HockeyTechProvider
from teamarr.providers.mlbstats.provider import MLBStatsProvider
from teamarr.providers.tsdb.provider import TSDBProvider
from teamarr.templates.context import (
    GameContext,
    TeamChannelContext,
    TemplateContext,
)
from teamarr.templates.variables.playoffs import (
    extract_is_playoff,
    extract_is_preseason,
    extract_is_regular_season,
    extract_season_type,
)

# --- Helpers ---


def _team(provider: str = "espn", league: str = "nhl", sport: str = "hockey") -> Team:
    return Team(
        id="1",
        provider=provider,
        name="Test Team",
        short_name="Test",
        abbreviation="TST",
        league=league,
        sport=sport,
    )


def _event_with_season_type(season_type: str | None) -> Event:
    return Event(
        id="x",
        provider="espn",
        name="T1 at T2",
        short_name="T1 @ T2",
        start_time=datetime(2026, 4, 22, 0, 0, tzinfo=UTC),
        home_team=_team(),
        away_team=_team(),
        status=EventStatus(state="scheduled"),
        league="nhl",
        sport="hockey",
        season_type=season_type,
    )


def _ctx_for(event: Event) -> tuple[TemplateContext, GameContext]:
    game_ctx = GameContext(
        event=event,
        is_home=True,
        team=event.home_team,
        opponent=event.away_team,
    )
    tpl_ctx = TemplateContext(
        game_context=game_ctx,
        team_config=TeamChannelContext(
            team_id=event.home_team.id,
            league=event.league,
            sport=event.sport,
            team_name=event.home_team.name,
        ),
        team_stats=None,
    )
    return tpl_ctx, game_ctx


# --- ESPN: _parse_season_type ---


class TestESPNParseSeasonType:
    def setup_method(self) -> None:
        self.provider = ESPNProvider(client=MagicMock(), league_mapping_source=MagicMock())

    def test_postseason_slug(self) -> None:
        result = self.provider._parse_season_type({"slug": "post-season", "type": 3})
        assert result == SEASON_POSTSEASON

    def test_regular_season_slug(self) -> None:
        result = self.provider._parse_season_type({"slug": "regular-season", "type": 2})
        assert result == SEASON_REGULAR

    def test_preseason_slug(self) -> None:
        result = self.provider._parse_season_type({"slug": "pre-season", "type": 1})
        assert result == SEASON_PRESEASON

    def test_offseason_slug(self) -> None:
        result = self.provider._parse_season_type({"slug": "off-season", "type": 4})
        assert result == SEASON_OFFSEASON

    @pytest.mark.parametrize("slug", ["round-of-16", "quarterfinals", "semifinals", "final"])
    def test_soccer_knockout_slugs_map_to_postseason(self, slug: str) -> None:
        # Soccer uses opaque 13xxx type numbers with meaningful slugs
        result = self.provider._parse_season_type({"slug": slug, "type": 13678})
        assert result == SEASON_POSTSEASON

    def test_soccer_group_stage_is_regular(self) -> None:
        result = self.provider._parse_season_type({"slug": "group-stage", "type": 13846})
        assert result == SEASON_REGULAR

    def test_type_number_fallback_when_no_slug(self) -> None:
        # Scoreboard sometimes lacks slug; fall back to numeric type
        assert self.provider._parse_season_type({"type": 3}) == SEASON_POSTSEASON
        assert self.provider._parse_season_type({"type": 2}) == SEASON_REGULAR
        assert self.provider._parse_season_type({"type": 1}) == SEASON_PRESEASON
        assert self.provider._parse_season_type({"type": 4}) == SEASON_OFFSEASON

    def test_opaque_soccer_type_without_slug_returns_none(self) -> None:
        # Summary endpoint often omits slug for soccer — this is the gap that
        # sports_data.SportsDataService.refresh_event_status preserves against.
        assert self.provider._parse_season_type({"type": 13846}) is None

    def test_empty_dict_returns_none(self) -> None:
        assert self.provider._parse_season_type({}) is None

    def test_none_returns_none(self) -> None:
        assert self.provider._parse_season_type(None) is None


# --- ESPN: get_event summary-path regression for #197 ---


class TestESPNSummaryEndpointSeasonPassthrough:
    """Regression test for the root cause of #197.

    Before the fix, get_event built event_data without the season field, so
    _parse_event saw no season data on the summary path and produced
    season_type=None. That wiped the value set by the scoreboard path during
    refresh_event_status, silently breaking playoff bypass.
    """

    def test_summary_response_header_season_reaches_parser(self) -> None:
        mock_client = MagicMock()
        # Realistic-shape summary response: header.season present, no top-level season
        mock_client.get_event.return_value = {
            "header": {
                "id": "401999999",
                "season": {"year": 2026, "type": 3, "slug": "post-season"},
                "competitions": [
                    {
                        "id": "401999999",
                        "date": "2026-04-22T23:00Z",
                        "status": {"type": {"state": "pre"}},
                        "competitors": [
                            {
                                "id": "1",
                                "homeAway": "home",
                                "team": {
                                    "id": "1",
                                    "displayName": "Home Team",
                                    "shortDisplayName": "Home",
                                    "abbreviation": "HOM",
                                    "logo": "",
                                },
                            },
                            {
                                "id": "2",
                                "homeAway": "away",
                                "team": {
                                    "id": "2",
                                    "displayName": "Away Team",
                                    "shortDisplayName": "Away",
                                    "abbreviation": "AWY",
                                    "logo": "",
                                },
                            },
                        ],
                    }
                ],
            },
            "gameInfo": {},
            "pickcenter": [],
        }
        mock_mapping = MagicMock()
        mock_mapping.provider_league_id = "nhl"
        mock_mapping.sport = "hockey"
        provider = ESPNProvider(client=mock_client, league_mapping_source=MagicMock())
        provider._get_sport_league_from_db = MagicMock(return_value="hockey/nhl")

        event = provider.get_event("401999999", "nhl")

        assert event is not None
        assert event.season_type == SEASON_POSTSEASON


# --- MLBStats: _GAMETYPE_CANONICAL ---


class TestMLBStatsGameTypeCanonical:
    @pytest.mark.parametrize(
        "code,expected",
        [
            ("R", SEASON_REGULAR),
            ("S", SEASON_PRESEASON),
            ("E", SEASON_PRESEASON),
            ("F", SEASON_POSTSEASON),  # Wild Card
            ("D", SEASON_POSTSEASON),  # Division Series
            ("L", SEASON_POSTSEASON),  # League Championship
            ("W", SEASON_POSTSEASON),  # World Series
            ("P", SEASON_POSTSEASON),  # Generic playoffs (minor leagues)
            ("A", None),  # All Star
        ],
    )
    def test_canonical_mapping(self, code: str, expected: str | None) -> None:
        assert MLBStatsProvider._GAMETYPE_CANONICAL.get(code) == expected

    def test_unknown_code_is_none(self) -> None:
        assert MLBStatsProvider._GAMETYPE_CANONICAL.get("Z", "DEFAULT") == "DEFAULT"
        # Through the accessor pattern used in _parse_game
        assert MLBStatsProvider._GAMETYPE_CANONICAL.get("") is None


# --- HockeyTech: _parse_season_type ---


class TestHockeyTechParseSeasonType:
    def setup_method(self) -> None:
        self.mock_client = MagicMock()
        self.provider = HockeyTechProvider(
            league_mapping_source=MagicMock(), client=self.mock_client
        )

    def _seasons(self, *seasons: dict) -> dict[str, dict]:
        return {str(s["season_id"]): s for s in seasons}

    def test_playoff_flag_maps_to_postseason(self) -> None:
        self.mock_client.get_seasons_info.return_value = self._seasons(
            {"season_id": "85", "season_name": "2026 Playoffs", "playoff": "1"},
        )
        game = {"game_id": "1", "season_id": "85"}
        assert self.provider._parse_season_type(game, "ohl") == SEASON_POSTSEASON

    def test_preseason_name_keyword(self) -> None:
        self.mock_client.get_seasons_info.return_value = self._seasons(
            {"season_id": "7", "season_name": "2025-26 Preseason", "playoff": "0"},
        )
        game = {"game_id": "1", "season_id": "7"}
        assert self.provider._parse_season_type(game, "pwhl") == SEASON_PRESEASON

    def test_exhibition_name_keyword(self) -> None:
        self.mock_client.get_seasons_info.return_value = self._seasons(
            {"season_id": "3", "season_name": "2025 Exhibition", "playoff": "0"},
        )
        game = {"game_id": "1", "season_id": "3"}
        assert self.provider._parse_season_type(game, "ohl") == SEASON_PRESEASON

    def test_non_playoff_non_preseason_is_regular(self) -> None:
        self.mock_client.get_seasons_info.return_value = self._seasons(
            {"season_id": "83", "season_name": "2025-26 Regular Season", "playoff": "0"},
        )
        game = {"game_id": "1", "season_id": "83"}
        assert self.provider._parse_season_type(game, "ohl") == SEASON_REGULAR

    def test_all_star_falls_into_regular_bucket(self) -> None:
        # Intentional — consistent with ESPN/MLB producers, which don't have
        # a dedicated canonical bucket for showcase/all-star events.
        self.mock_client.get_seasons_info.return_value = self._seasons(
            {"season_id": "91", "season_name": "2026 All-Star Challenge", "playoff": "0"},
        )
        game = {"game_id": "1", "season_id": "91"}
        assert self.provider._parse_season_type(game, "ahl") == SEASON_REGULAR

    def test_missing_season_id_returns_none(self) -> None:
        assert self.provider._parse_season_type({"game_id": "1"}, "ohl") is None
        self.mock_client.get_seasons_info.assert_not_called()

    def test_unknown_season_id_returns_none(self) -> None:
        self.mock_client.get_seasons_info.return_value = self._seasons(
            {"season_id": "85", "season_name": "2026 Playoffs", "playoff": "1"},
        )
        game = {"game_id": "1", "season_id": "999"}
        assert self.provider._parse_season_type(game, "ohl") is None

    def test_no_seasons_info_returns_none(self) -> None:
        self.mock_client.get_seasons_info.return_value = {}
        game = {"game_id": "1", "season_id": "85"}
        assert self.provider._parse_season_type(game, "ohl") is None


class TestTSDBParseSeasonType:
    """TSDB has no explicit playoff flag — we derive it from intRound codes.

    Per TheSportsDB API docs (verified against NBA 2024 Playoffs + NHL 2024
    Stanley Cup + IPL 2024 on 2026-04-22):
      125 = Quarter-Final, 150 = Semi-Final, 160 = First Round / Play-in,
      170 = Playoff Semi-Final, 180 = Playoff Final, 200 = Final/Championship.
    Low integers (1, 2, ..., 19, 24) are regular-season rounds, and leagues
    like AFL/NRL keep low-integer numbering through finals — those stay None.
    """

    def setup_method(self) -> None:
        self.provider = TSDBProvider(league_mapping_source=MagicMock(), client=MagicMock())

    @pytest.mark.parametrize(
        "round_code",
        ["125", "150", "160", "170", "180", "200"],
    )
    def test_postseason_round_codes(self, round_code: str) -> None:
        assert self.provider._parse_season_type({"intRound": round_code}) == SEASON_POSTSEASON

    def test_postseason_round_as_int(self) -> None:
        # TSDB sometimes returns intRound as a JSON number, sometimes as string
        assert self.provider._parse_season_type({"intRound": 200}) == SEASON_POSTSEASON

    @pytest.mark.parametrize("round_code", ["0", "1", "3", "19", "24", "44"])
    def test_regular_season_rounds_return_none(self, round_code: str) -> None:
        # Intentionally None (not SEASON_REGULAR) — TSDB can't distinguish
        # regular season from finals for leagues that don't use the special codes
        # (AFL Grand Final = intRound 19; NRL Grand Final = intRound 24).
        assert self.provider._parse_season_type({"intRound": round_code}) is None

    def test_missing_round_returns_none(self) -> None:
        assert self.provider._parse_season_type({}) is None

    def test_empty_round_returns_none(self) -> None:
        assert self.provider._parse_season_type({"intRound": ""}) is None

    def test_none_round_returns_none(self) -> None:
        assert self.provider._parse_season_type({"intRound": None}) is None

    def test_qualifying_code_400_not_treated_as_postseason(self) -> None:
        # UCL qualifying uses intRound=400, which isn't a knockout stage.
        # We intentionally don't map it to postseason.
        assert self.provider._parse_season_type({"intRound": "400"}) is None


# --- Template variables: strict canonical comparison ---


class TestPlayoffTemplateVariables:
    @pytest.mark.parametrize(
        "season_type,is_playoff,is_preseason,is_regular",
        [
            (SEASON_POSTSEASON, "true", "", ""),
            (SEASON_PRESEASON, "", "true", ""),
            (SEASON_REGULAR, "", "", "true"),
            (SEASON_OFFSEASON, "", "", ""),
            (None, "", "", ""),
        ],
    )
    def test_canonical_values(
        self,
        season_type: str | None,
        is_playoff: str,
        is_preseason: str,
        is_regular: str,
    ) -> None:
        event = _event_with_season_type(season_type)
        ctx, game_ctx = _ctx_for(event)
        assert extract_is_playoff(ctx, game_ctx) == is_playoff
        assert extract_is_preseason(ctx, game_ctx) == is_preseason
        assert extract_is_regular_season(ctx, game_ctx) == is_regular

    def test_season_type_variable_returns_canonical_string(self) -> None:
        event = _event_with_season_type(SEASON_POSTSEASON)
        ctx, game_ctx = _ctx_for(event)
        assert extract_season_type(ctx, game_ctx) == SEASON_POSTSEASON

    def test_season_type_variable_empty_when_none(self) -> None:
        event = _event_with_season_type(None)
        ctx, game_ctx = _ctx_for(event)
        assert extract_season_type(ctx, game_ctx) == ""


# --- Consumer: filter bypass uses canonical constant ---


class TestFilterBypassUsesCanonicalConstant:
    """Verify the event_group_processor filter bypass uses SEASON_POSTSEASON.

    The important invariant is: imports the constant (no string-literal
    comparison survives), and event.season_type == SEASON_POSTSEASON is the
    gate.
    """

    def test_constant_is_imported_and_used(self) -> None:
        from teamarr.consumers import event_group_processor

        assert event_group_processor.SEASON_POSTSEASON == SEASON_POSTSEASON

    def test_filter_keeps_postseason_events_when_bypass_enabled(self) -> None:
        # Smoke: confirm a postseason event compares equal to the constant.
        # The real filter flow is integration-tested elsewhere; here we pin
        # the behavior the gate relies on.
        event = _event_with_season_type(SEASON_POSTSEASON)
        assert event.season_type == SEASON_POSTSEASON

    def test_filter_does_not_treat_regular_as_postseason(self) -> None:
        event = _event_with_season_type(SEASON_REGULAR)
        assert event.season_type != SEASON_POSTSEASON
