"""Filler generation types and configuration.

These types are used by both the database layer (for template conversion)
and the consumers layer (for filler generation). Placed in core to maintain
proper layer isolation.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class FillerType(StrEnum):
    """Types of filler content."""

    PREGAME = "pregame"
    POSTGAME = "postgame"
    IDLE = "idle"


@dataclass
class FillerTemplate:
    """Template for a specific filler type.

    ``description_fallbacks`` is the ordered cascade tried when
    ``description`` resolves to an empty string at render time — e.g. a
    provider-copy primary like ``{game_recap}`` before the provider
    publishes one (epic tvnk, #329). With condition rows (#420) the chain
    is: winning row → other matching rows by priority → base register.
    """

    title: str
    subtitle: str | None = None
    description: str | None = None
    art_url: str | None = None
    description_fallbacks: list[str] = field(default_factory=list)


def legacy_conditional_to_rows(cond: dict | None) -> list[dict]:
    """Convert a legacy final/not-final filler conditional to condition rows.

    In-memory twin of the v80 migration (#420): an ENABLED legacy dict
    becomes up to two DISJOINT rows — ``is_final`` carrying the ``*_final``
    fields, ``is_not_final`` the ``*_not_final`` fields — in the hehg.2 row
    shape (description under the legacy key ``template``). Falsy values
    count as unset, matching the old ``cond.x or base.x`` per-field chain.

    Applied at config-build time when a template's rows column is empty, so
    legacy conditionals authored after v80 ran (pre-cajd.4 UI) still work.
    """
    if not isinstance(cond, dict) or not cond.get("enabled"):
        return []

    rows: list[dict] = []
    for condition, suffix, label in (
        ("is_final", "_final", "Final (legacy)"),
        ("is_not_final", "_not_final", "In progress (legacy)"),
    ):
        fields: dict = {}
        if cond.get(f"title{suffix}"):
            fields["title"] = cond[f"title{suffix}"]
        if cond.get(f"subtitle{suffix}"):
            fields["subtitle"] = cond[f"subtitle{suffix}"]
        if cond.get(f"description{suffix}"):
            fields["template"] = cond[f"description{suffix}"]
        if fields:
            rows.append(
                {
                    "condition": condition,
                    "condition_value": None,
                    "priority": 50,
                    "label": label,
                    **fields,
                }
            )
    return rows


@dataclass
class OffseasonFillerTemplate:
    """Offseason templates when no games scheduled."""

    enabled: bool = False
    title: str | None = None
    subtitle: str | None = None
    description: str | None = None


@dataclass
class FillerConfig:
    """Configuration for filler generation.

    Populated from database templates table. No hardcoded defaults -
    schema.sql provides all default values.
    """

    # Pregame settings
    pregame_enabled: bool = True
    pregame_template: FillerTemplate = field(
        default_factory=lambda: FillerTemplate(title="", description="")
    )

    # Postgame settings
    postgame_enabled: bool = True
    postgame_template: FillerTemplate = field(
        default_factory=lambda: FillerTemplate(title="", description="")
    )

    # Idle settings
    idle_enabled: bool = True
    idle_template: FillerTemplate = field(
        default_factory=lambda: FillerTemplate(title="", description="")
    )
    idle_offseason: OffseasonFillerTemplate = field(default_factory=OffseasonFillerTemplate)

    # Condition rows per register (#420, epic cajd) — hehg.2 row shape
    # ({condition, condition_value, template, title?, subtitle?, priority,
    # label}). Evaluated against the register's reference game: pregame →
    # next game, postgame/idle → last game. Replace the legacy final/
    # not-final conditionals (converted by v80 / legacy_conditional_to_rows).
    pregame_rows: list[dict] = field(default_factory=list)
    postgame_rows: list[dict] = field(default_factory=list)
    idle_rows: list[dict] = field(default_factory=list)

    # XMLTV categories applied to filler programmes. Independent from event
    # categories on the parent template — empty list means no <category> tags
    # on filler. (Pre-v72 used a categories_apply_to gate to share event
    # categories; replaced by a dedicated filler-categories list.)
    xmltv_categories: list[str] = field(default_factory=list)


@dataclass
class FillerOptions:
    """Options for filler generation."""

    # EPG window
    output_days_ahead: int = 14
    lookback_hours: int = 6  # How far back to start EPG (for recently finished games)

    # Timezone for EPG
    epg_timezone: str = "America/New_York"

    # Midnight crossover mode: 'postgame' or 'idle'
    # Controls what fills the gap when a game crosses midnight
    # and there's no game the next day
    midnight_crossover_mode: str = "postgame"

    # Sport durations (hours) - loaded from settings
    # Keys are sport names (lowercase): basketball, football, hockey, baseball, soccer
    # If not provided, uses hardcoded defaults
    sport_durations: dict[str, float] = field(default_factory=dict)

    # Default duration if sport not found
    default_duration: float = 3.0

    # Pregame buffer (minutes) - gap between pregame filler end and game start
    # Set to 0 so pregame filler ends exactly when the game programme starts
    pregame_buffer_minutes: int = 0

    # Postponed event label
    # When True, prepends "Postponed: " to filler title, subtitle, and description
    # if the relevant event (next for pregame, last for postgame) is postponed
    prepend_postponed_label: bool = True
