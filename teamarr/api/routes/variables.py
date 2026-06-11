"""Variables API endpoint for template variable picker."""

from fastapi import APIRouter

from teamarr.templates.sample_data import AVAILABLE_SPORTS, get_all_sample_data
from teamarr.templates.variables import Category, SuffixRules, get_registry

router = APIRouter()


def _category_display_name(category: Category) -> str:
    """Get human-readable category name."""
    names = {
        Category.IDENTITY: "Identity",
        Category.DATETIME: "Date & Time",
        Category.VENUE: "Venue",
        Category.HOME_AWAY: "Home/Away",
        Category.RECORDS: "Records",
        Category.STREAKS: "Streaks",
        Category.SCORES: "Scores",
        Category.OUTCOME: "Outcome",
        Category.STANDINGS: "Standings",
        Category.STATISTICS: "Statistics",
        Category.PLAYOFFS: "Playoffs",
        Category.ODDS: "Odds",
        Category.BROADCAST: "Broadcast",
        Category.RANKINGS: "Rankings",
        Category.CONFERENCE: "Conference",
        Category.SOCCER: "Soccer",
        Category.COMBAT: "Combat Sports",
    }
    return names.get(category, category.name.title())


def _suffix_rules_display(rules: SuffixRules) -> list[str]:
    """Get list of supported suffixes for a variable."""
    if rules == SuffixRules.ALL:
        return ["base", ".next", ".last"]
    elif rules == SuffixRules.BASE_ONLY:
        return ["base"]
    elif rules == SuffixRules.BASE_NEXT_ONLY:
        return ["base", ".next"]
    elif rules == SuffixRules.LAST_ONLY:
        return [".last"]
    return ["base"]


@router.get("/variables")
def get_variables(template_type: str | None = None):
    """Get template variables grouped by category, optionally scoped to a template type.

    Args:
        template_type: Optional filter — 'team' or 'event'. When set, only
            variables valid for that template type are returned (per each
            variable's registered TemplateScope). Unknown values and None
            return all variables (matches the conditions endpoint's behavior).

    Team templates render from an "our team" perspective (variables like
    {team}, {opponent}, {is_home}). Event templates are positional
    (matchup-level) and additionally expose the feed_team family on
    feed-separated channels.
    """
    registry = get_registry()
    scoped_vars = registry.filter_by_template_type(template_type)

    # Group by category
    by_category: dict[str, list[dict]] = {}

    for var in sorted(scoped_vars, key=lambda v: (v.category.value, v.name)):
        cat_name = _category_display_name(var.category)

        if cat_name not in by_category:
            by_category[cat_name] = []

        by_category[cat_name].append(
            {
                "name": var.name,
                "description": var.description or "",
                "suffixes": _suffix_rules_display(var.suffix_rules),
            }
        )

    # Convert to list format for frontend
    categories = []
    for cat_name, variables in by_category.items():
        categories.append(
            {
                "name": cat_name,
                "variables": variables,
            }
        )

    return {
        "total": len(scoped_vars),
        "template_type": template_type,
        "categories": categories,
        "available_sports": AVAILABLE_SPORTS,
    }


@router.get("/variables/samples")
def get_sample_data(sport: str = "NBA"):
    """Get sample data for template variable preview.

    Returns sample values for all variables for a given sport.
    Used for live preview in the template form.
    """
    if sport not in AVAILABLE_SPORTS:
        sport = "NBA"  # Default fallback

    return {
        "sport": sport,
        "available_sports": AVAILABLE_SPORTS,
        "samples": get_all_sample_data(sport),
    }


@router.get("/variables/conditions")
def get_conditions(template_type: str = "team"):
    """Get available conditions for conditional descriptions.

    Args:
        template_type: "team" or "event" - filters to relevant conditions

    Team templates have "our team" perspective, so conditions like
    is_home/is_away and win_streak make sense.

    Event templates are positional (home/away teams), so only
    game-level conditions like is_playoff, has_odds apply.
    """
    # Provider support:
    # - "all": Works with all providers (ESPN, TSDB)
    # - "espn": ESPN leagues only (NFL, NBA, NHL, MLB, MLS, college, soccer)
    # For TSDB-only leagues (OHL, WHL, NLL, etc.), ESPN-only conditions return false

    # Conditions that apply to both template types
    common_conditions = [
        # ESPN-only: requires ranking data
        {
            "name": "is_ranked_matchup",
            "description": "Both teams are ranked (college sports)",
            "requires_value": False,
            "providers": "espn",
        },
        {
            "name": "is_top_ten_matchup",
            "description": "Both teams are ranked in top 10",
            "requires_value": False,
            "providers": "espn",
        },
        # ESPN-only: requires conference data
        {
            "name": "is_conference_game",
            "description": "Game is a conference matchup",
            "requires_value": False,
            "providers": "espn",
        },
        # ESPN-only: requires season type flags
        {
            "name": "is_playoff",
            "description": "Game is a playoff/postseason game",
            "requires_value": False,
            "providers": "espn",
        },
        {
            "name": "is_preseason",
            "description": "Game is a preseason game",
            "requires_value": False,
            "providers": "espn",
        },
        # ESPN-only: requires broadcast data
        {
            "name": "is_national_broadcast",
            "description": "Game is on national TV",
            "requires_value": False,
            "providers": "espn",
        },
        # ESPN-only: only ESPN provides odds data
        {
            "name": "has_odds",
            "description": "Betting odds are available for the game",
            "requires_value": False,
            "providers": "espn",
        },
    ]

    # Team-only conditions (require "our team" perspective)
    team_only_conditions = [
        # Universal: works with all providers
        {
            "name": "is_home",
            "description": "Team is playing at home",
            "requires_value": False,
            "providers": "all",
        },
        {
            "name": "is_away",
            "description": "Team is playing away",
            "requires_value": False,
            "providers": "all",
        },
        {
            "name": "opponent_name_contains",
            "description": "Opponent name contains specific text",
            "requires_value": True,
            "value_type": "string",
            "providers": "all",
        },
        # ESPN-only: requires team stats
        {
            "name": "win_streak",
            "description": "Team is on a win streak of N or more games",
            "requires_value": True,
            "value_type": "number",
            "providers": "espn",
        },
        {
            "name": "loss_streak",
            "description": "Team is on a loss streak of N or more games",
            "requires_value": True,
            "value_type": "number",
            "providers": "espn",
        },
        # ESPN-only: requires ranking data
        {
            "name": "is_ranked",
            "description": "Team is ranked (college sports)",
            "requires_value": False,
            "providers": "espn",
        },
        {
            "name": "is_ranked_opponent",
            "description": "Opponent is ranked (college sports)",
            "requires_value": False,
            "providers": "espn",
        },
    ]

    # Combat sports conditions (MMA/UFC events)
    combat_conditions = [
        {
            "name": "is_knockout",
            "description": "Fight ended by KO or TKO",
            "requires_value": False,
            "providers": "espn",
        },
        {
            "name": "is_submission",
            "description": "Fight ended by submission",
            "requires_value": False,
            "providers": "espn",
        },
        {
            "name": "is_decision",
            "description": "Fight went to decision",
            "requires_value": False,
            "providers": "espn",
        },
        {
            "name": "is_finish",
            "description": "Fight ended by finish (KO/TKO/Submission)",
            "requires_value": False,
            "providers": "espn",
        },
        {
            "name": "went_distance",
            "description": "Fight went all scheduled rounds",
            "requires_value": False,
            "providers": "espn",
        },
    ]

    # Motorsports conditions (F1, NASCAR, IndyCar, MotoGP, ... events)
    motorsports_conditions = [
        {
            "name": "is_race_session",
            "description": "This channel's session is the race itself",
            "requires_value": False,
            "providers": "espn",
        },
        {
            "name": "is_qualifying_session",
            "description": "This channel's session is qualifying or sprint qualifying",
            "requires_value": False,
            "providers": "espn",
        },
        {
            "name": "has_results",
            "description": "This channel's session has finished with results",
            "requires_value": False,
            "providers": "espn",
        },
    ]

    if template_type == "event":
        # Event templates get combat/motorsports conditions only (for event EPG)
        conditions = combat_conditions + motorsports_conditions
    else:
        # Team templates get all conditions
        conditions = (
            team_only_conditions + common_conditions + combat_conditions + motorsports_conditions
        )

    return {"conditions": conditions, "template_type": template_type}
