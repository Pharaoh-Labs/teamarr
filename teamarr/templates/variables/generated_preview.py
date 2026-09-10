"""Raw typed facts exposed as variables, plus the optional generated preview."""

from teamarr.templates.context import GameContext, TemplateContext
from teamarr.templates.generated_preview import build_generated_preview
from teamarr.templates.variables.registry import Category, SuffixRules, register_variable


def _register_event_field(name: str, description: str, sample: str) -> None:
    """Register a direct Event string/int field as a public template variable."""

    def extract(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
        if not game_ctx or not game_ctx.event:
            return ""
        value = getattr(game_ctx.event, name, "")
        return "" if value in (None, "") else str(value)

    extract.__name__ = f"extract_{name}"
    register_variable(
        name=name,
        category=Category.SUMMARY,
        suffix_rules=SuffixRules.ALL,
        description=description,
        sample=sample,
    )(extract)


# Public variables are raw provider values passed through unchanged, or the
# final {generated_preview} — never a string our own code composed (maintainer
# policy, 2026-09-10, #613). The leader and probable-starter facts are
# "Name — value label" strings assembled by the ESPN parser, so they stay
# internal inputs to the prose builder and are deliberately NOT registered.
_FIELD_DEFINITIONS = {
    "week": ("Provider-reported week number; empty when unavailable", "3"),
    "home_total_yards_per_game": ("Home team total yards per game", "360"),
    "away_total_yards_per_game": ("Away team total yards per game", "204"),
    "home_rushing_yards_per_game": ("Home team rushing yards per game", "162"),
    "away_rushing_yards_per_game": ("Away team rushing yards per game", "63"),
    "home_points_allowed_per_game": ("Home team points allowed per game", "87.0"),
    "away_points_allowed_per_game": ("Away team points allowed per game", "89.9"),
}

# Raw preview fields that ARE public variables (the rest of
# GENERATED_PREVIEW_FIELDS feed {generated_preview} only).
PUBLIC_PREVIEW_FIELDS: frozenset[str] = frozenset(_FIELD_DEFINITIONS)

for _name, (_description, _sample) in _FIELD_DEFINITIONS.items():
    _register_event_field(_name, _description, _sample)


@register_variable(
    name="generated_preview",
    category=Category.SUMMARY,
    suffix_rules=SuffixRules.ALL,
    description=(
        "Optional deterministic preview with sport-specific baseball, football and "
        "basketball prose and a generic matchup sentence for other sports; assembled "
        "from public fields without betting information"
    ),
)
def extract_generated_preview(ctx: TemplateContext, game_ctx: GameContext | None) -> str:
    return build_generated_preview(game_ctx.event if game_ctx else None)
