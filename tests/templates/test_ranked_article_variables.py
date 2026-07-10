"""Composed rank+article variables — {*_ranked_the} family (#359).

The branching a flat template can't express: '{home_team_rank_display}
{home_team}' loses the Gracenote article for unranked clubs. One composed
variable per perspective encapsulates it (docs/reference/gracenote-categories.md:
"The No. 16 Commodores (7-2, 3-2 SEC) try to bounce back as they host…").
"""

from datetime import UTC, datetime

import pytest

from teamarr.core.naming import ranked_with_article
from teamarr.core.types import Event, EventStatus, Team, TeamStats
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.variables.home_away import (
    extract_away_team_ranked_the,
    extract_home_team_ranked_the,
)
from teamarr.templates.variables.identity import (
    extract_opponent_ranked_the,
    extract_team_name_ranked_the,
)

# --- primitive ---------------------------------------------------------------


class TestRankedWithArticle:
    def test_ranked_club_inserts_rank_after_article(self):
        out = ranked_with_article(
            "Michigan Wolverines", "mens-college-basketball", "basketball", 25
        )
        assert out == "the No. 25 Michigan Wolverines"

    def test_unranked_club_keeps_article(self):
        out = ranked_with_article(
            "Michigan Wolverines", "mens-college-basketball", "basketball", None
        )
        assert out == "the Michigan Wolverines"

    def test_ranked_national_team_no_article(self):
        out = ranked_with_article("Spain", "fifa.world", "soccer", 3)
        assert out == "No. 3 Spain"

    def test_unranked_national_team(self):
        assert ranked_with_article("Spain", "fifa.world", "soccer", None) == "Spain"

    def test_name_already_carrying_article(self):
        out = ranked_with_article("The Citadel Bulldogs", "college-football", "football", 16)
        assert out == "The No. 16 Citadel Bulldogs"

    def test_empty_name(self):
        assert ranked_with_article("", "nba", "basketball", 5) == ""


# --- extractors --------------------------------------------------------------


def _team(name, abbrev, id_, league="mens-college-basketball", sport="basketball"):
    return Team(
        id=id_, provider="espn", name=name, short_name=name,
        abbreviation=abbrev, league=league, sport=sport,
    )


HOME = _team("Arkansas Razorbacks", "ARK", "1")
AWAY = _team("Texas A&M Aggies", "TAMU", "2")


def _ctx(team_rank=None, opponent_rank=None, our_team=HOME):
    """Context where 'our team' is HOME by default; ranks via TeamStats."""
    event = Event(
        id="e1", provider="espn", name="Texas A&M Aggies at Arkansas Razorbacks",
        short_name="TAMU @ ARK",
        start_time=datetime(2026, 7, 10, 19, 0, tzinfo=UTC),
        home_team=HOME, away_team=AWAY, status=EventStatus(state="pre"),
        league="mens-college-basketball", sport="basketball",
    )
    game_ctx = GameContext(
        event=event,
        is_home=(our_team.id == HOME.id),
        opponent_stats=TeamStats(record="10-2", rank=opponent_rank) if opponent_rank else None,
    )
    return TemplateContext(
        game_context=game_ctx,
        team_config=TeamChannelContext(
            team_id=our_team.id, league=event.league, sport=event.sport,
            team_name=our_team.name, team_abbrev=our_team.abbreviation,
        ),
        team_stats=TeamStats(record="12-1", rank=team_rank) if team_rank else None,
    )


class TestHomeAwayRankedThe:
    def test_both_ranked(self):
        ctx = _ctx(team_rank=20, opponent_rank=14)
        assert extract_home_team_ranked_the(ctx, ctx.game_context) == (
            "the No. 20 Arkansas Razorbacks"
        )
        assert extract_away_team_ranked_the(ctx, ctx.game_context) == (
            "the No. 14 Texas A&M Aggies"
        )

    def test_one_ranked_matchup_keeps_article_on_unranked_side(self):
        """The motivating case: unranked side must not lose its article."""
        ctx = _ctx(team_rank=20, opponent_rank=None)
        assert extract_home_team_ranked_the(ctx, ctx.game_context) == (
            "the No. 20 Arkansas Razorbacks"
        )
        assert extract_away_team_ranked_the(ctx, ctx.game_context) == "the Texas A&M Aggies"

    def test_no_event(self):
        ctx = _ctx()
        assert extract_home_team_ranked_the(ctx, None) == ""
        assert extract_away_team_ranked_the(ctx, None) == ""


class TestTeamPerspectiveRankedThe:
    def test_team_name_ranked(self):
        ctx = _ctx(team_rank=7)
        assert extract_team_name_ranked_the(ctx, ctx.game_context) == (
            "the No. 7 Arkansas Razorbacks"
        )

    def test_team_name_unranked(self):
        ctx = _ctx()
        assert extract_team_name_ranked_the(ctx, ctx.game_context) == "the Arkansas Razorbacks"

    def test_opponent_ranked(self):
        ctx = _ctx(opponent_rank=14)
        assert extract_opponent_ranked_the(ctx, ctx.game_context) == (
            "the No. 14 Texas A&M Aggies"
        )

    def test_opponent_unranked(self):
        ctx = _ctx()
        assert extract_opponent_ranked_the(ctx, ctx.game_context) == "the Texas A&M Aggies"


# --- registration ------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["home_team_ranked_the", "away_team_ranked_the", "team_name_ranked_the", "opponent_ranked_the"],
)
def test_registered(name):
    from teamarr.templates.variables import get_registry

    assert get_registry().get(name) is not None
