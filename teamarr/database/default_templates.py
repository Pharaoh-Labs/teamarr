"""Curated default template set (epic teamarrv2-tvnk, issue #329).

Gracenote-modeled defaults, seeded UNASSIGNED — the user scopes them (see
docs/guide/templates/defaults.md for the recommended scoping table). Design
decisions (bead tvnk.1, 2026-07-09):

- REPLACE the legacy 2 generic seeds: a pristine legacy "Team"/"Event" row
  (content fingerprint: stock title, subtitle, art in either historical form,
  and stock default description) is upgraded IN PLACE — same row id, so
  template assignments and group references survive. A user-modified legacy
  row is never touched; the curated set is simply added alongside.
- Seed on fresh installs AND upgrades: any set member missing by name is
  added on startup; existing rows are never overwritten.
- Art ships as RELATIVE paths (variable-led, slash-less per #275) prefixed
  by the art_base_url setting at render time (epic z02s) — this also retires
  the localhost:3000 placeholder (bead tvnk.2).
- SUPER SHORT channel titles are a first-class constraint: client guides
  truncate channel names aggressively (~15-20 visible chars), so every event
  template's ``event_channel_name`` is abbreviation-first with no filler.
- ESPN copy is the PRIMARY description source; constructed prose is the
  FALLBACK (tvnk.14): main descriptions carry a ``has_preview →
  {game_preview}`` conditional row above a Tier-2 ``has_structured_preview``
  row (constructed line + recent form + series state, populates days ahead —
  tvnk.15) above the constructed default; pregame
  fillers pair a ``{game_preview}`` primary with a ``description_fallback``;
  postgame conditionals put ``{game_recap}`` in ``description_final`` and the
  filler render falls through to the fallback's constructed result line when
  the recap hasn't been published.
- Per-sport-family registers (tvnk.8 synthesis): the base US-pro travel-line
  register is joined by soccer ("face" match register, article-aware _the
  vars, 'v' channel connector), college (home-led host framing with rank +
  record + conference rows, per the captured Gracenote preview register), and
  year-composed tournament titles (International ``{gracenote_category}
  {year}`` per the tvnk.12 decision; Tennis ``{year} {tournament_name}``).
  Combat/tennis/racing get no team variants — no meaningful team channels
  (racing driver channels are epic hjzo).
"""

from sqlite3 import Connection

# Relative art paths (z02s): prefixed with the art_base_url setting at render.
# Variable-led values stay slash-less — a leading variable may resolve to an
# absolute URL, and a prepended "/" would break it (#275).
#
# Query params follow the game-thumbs conventions (inferred from sethwv's
# server, tvnk.1 decision b): style=1 for team covers, style=6 for event
# matchup covers, logo=true overlays team logos, fallback=true serves generic
# art when a matchup image is missing. Event CHANNEL logos carry a badge=
# overlay showing the broadcast network + quality keyword ("ESPN 4K") right
# on the channel icon.
_TEAM_PARAMS = "?style=1&logo=true&fallback=true"
_EVENT_PARAMS = "?style=6&logo=true&fallback=true"
_ART_PATH = "{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png"
_TEAM_ART = _ART_PATH + _TEAM_PARAMS
_EVENT_ART = _ART_PATH + _EVENT_PARAMS
_ART_NEXT = "{league_id}/{away_team_pascal.next}/{home_team_pascal.next}/cover.png" + _TEAM_PARAMS
_ART_LAST = "{league_id}/{away_team_pascal.last}/{home_team_pascal.last}/cover.png" + _TEAM_PARAMS
_EVENT_LOGO = (
    "{league_id}/{away_team_pascal}/{home_team_pascal}/logo.png"
    "?style=1&logo=true&fallback=true"
    "&badge={broadcast_national_network}%20{exception_keyword}"
)

_XMLTV_FLAGS = {"new": True, "live": True, "date": True}
_XMLTV_VIDEO = {"enabled": False, "quality": "HDTV"}

# Legacy seeds shipped with this placeholder art. Migration v75 (z02s) later
# stripped the origin into the art_base_url setting, so upgraded installs
# carry the RELATIVE form instead — pristine detection accepts both.
LEGACY_PRISTINE_MARKER = "http://localhost:3000/"
_LEGACY_STRIPPED_ART = "{league_id}/{away_team_pascal}/{home_team_pascal}/cover.png"

# Legacy seed name → curated replacement name (upgrade-in-place keeps the row
# id, so assignments and group references survive the rename).
LEGACY_UPGRADES = {"Team": "Default Team (Starter)", "Event": "Default Event (Starter)"}

# Earlier curated-set iterations used these names / had these members. An
# UNEDITED row under a prior name is renamed in place (same id); an unedited
# retired member is removed. Edited rows are always left alone.
PRIOR_NAME_UPGRADES = {
    "Default Team": "Default Team (Starter)",
    "Default Event": "Default Event (Starter)",
    "Combat Event": "Combat Event (Starter)",
    "International Event": "International Event (Starter)",
    # "MiLB Event" retired in tvnk.4 — both name generations are handled by
    # _retired_milb_specs() removal healing instead.
    "Tennis Event": "Tennis Event (Starter)",
}

# Prior-iteration CONTENT of still-current members (tvnk.8): an unedited row
# still carrying the old title_format is upgraded in place to the current
# spec (same id). Maps member name → the title_format earlier seeds shipped.
PRIOR_TITLE_UPGRADES = {
    "International Event (Starter)": "{gracenote_category}",
    "Tennis Event (Starter)": "{tournament_name}",
}

# Content fingerprint of the stock legacy seeds — a row is "pristine" (safe to
# upgrade in place) only when title, subtitle, art AND the default description
# all still match what the seed shipped with. Any user edit to any of them
# leaves the row untouched.
_STOCK_TITLE = "{gracenote_category}"
_STOCK_SUBTITLE = "{away_team} at {home_team}"
_LEGACY_STOCK_CONDITIONAL = {
    "Team": (
        "The {away_team_record} {away_team} travel to {venue_city}, "
        "{venue_state} to take on the {home_team_record} {home_team} at {venue}."
    ),
    "Event": (
        "The {away_team_record} {away_team} travel to {venue_city}, "
        "{venue_state} to play the {home_team_record} {home_team} at {venue}."
    ),
}


def _is_pristine_legacy(row, legacy_name: str) -> bool:
    """True when a legacy seed row still matches its shipped content."""
    if row.title_format != _STOCK_TITLE:
        return False
    if (row.subtitle_template or "") != _STOCK_SUBTITLE:
        return False
    art = row.program_art_url or ""
    stock_art = (
        art.startswith(LEGACY_PRISTINE_MARKER)
        or art == _LEGACY_STRIPPED_ART
        # v75-stripped form with game-thumbs query params (?style=…) — still
        # the stock art pipeline, just parameterized (tvnk.1 decision b).
        or art.startswith(_LEGACY_STRIPPED_ART + "?")
    )
    if not stock_art:
        return False
    conds = row.conditional_descriptions or []
    texts = [c.get("template") for c in conds if isinstance(c, dict)]
    return texts == [_LEGACY_STOCK_CONDITIONAL[legacy_name]]


def _is_unedited_curated(row, spec: dict) -> bool:
    """True when a curated-set row still matches its seeded content.

    Used to heal the transitional state where an earlier seeding pass added a
    curated row alongside a pristine legacy one (before parameterized art
    counted as pristine): the untouched curated duplicate can be folded back
    so the legacy row — which holds the references — upgrades in place.
    Art matches the current spec or its bare (param-less) earlier form.
    """
    if row.title_format != spec.get("title_format"):
        return False
    if (row.subtitle_template or "") != (spec.get("subtitle_template") or ""):
        return False
    if (row.event_channel_name or "") != (spec.get("event_channel_name") or ""):
        return False
    art = row.program_art_url or ""
    spec_art = spec.get("program_art_url") or ""
    bare = spec_art.split("?")[0]
    return art in (spec_art, bare)


def _team_base(**overrides) -> dict:
    """Shared skeleton for the team templates; variants override fields.

    The base register is US-pro (travel-line prose, W-L records); per-sport
    variants (tvnk.8) swap the description register — soccer gets the "face"
    match register, college the home-led rank/record host framing.
    """
    base = {
        "template_type": "team",
        "title_format": "{gracenote_category}",
        "subtitle_template": "{away_team} at {home_team}",
        "program_art_url": _TEAM_ART,
        "game_duration_mode": "sport",
        "pregame_enabled": True,
        "postgame_enabled": True,
        "idle_enabled": True,
        "xmltv_flags": _XMLTV_FLAGS,
        "xmltv_video": _XMLTV_VIDEO,
        "xmltv_categories": ["Sports", "{sport}", "Sports Event"],
        "xmltv_filler_categories": [],
        "pregame_periods": [],
        # ESPN-copy-first (tvnk.14): provider preview is the primary text;
        # the constructed prose is the fallback when no preview exists yet.
        "pregame_fallback": {
            "title": "Coming up: {gracenote_category} at {game_time.next}",
            "subtitle": "{away_team.next} at {home_team.next}",
            "description": "{game_preview.next}",
            "description_fallback": (
                "The {away_team_record.next} {away_team.next} travel to "
                "{venue_city.next}, {venue_state.next} to play the "
                "{home_team_record.next} {home_team.next} {today_tonight.next} "
                "at {game_time.next}."
            ),
            "art_url": _ART_NEXT,
        },
        "postgame_periods": [],
        # Postgame chain (tvnk.14): conditional recap wins when the game is
        # final AND the provider published one; otherwise the fallback's
        # constructed result line renders.
        "postgame_fallback": {
            "title": "{gracenote_category}: {team_name} Postgame",
            "subtitle": "{away_team.last} at {home_team.last}",
            "description": (
                "{team_name_the} {result_text.last} {opponent_the.last} {final_score.last}"
            ),
            "art_url": _ART_LAST,
        },
        "postgame_conditional": {
            "enabled": True,
            "description_final": "{game_recap.last}",
            "description_not_final": (
                "The game between {team_name_the} and {opponent_the.last} on "
                "{game_date.last} has not yet ended as of the last update."
            ),
        },
        "idle_content": {
            "title": "No {team_name} Game Today",
            "subtitle": (
                "Next game: {game_date.next} at {game_time.next} {vs_at.next} {opponent_the.next}"
            ),
            "description": "Next game: {game_date.next} at {game_time.next} vs {opponent.next}",
            "art_url": "",
        },
        "idle_conditional": {
            "enabled": True,
            "description_final": (
                "{team_name_the} {result_text.last} {opponent_the.last} "
                "{final_score.last} {overtime_text.last} on {game_date.last}. "
                "Next game will be with {opponent_the.next} on {game_date.next}"
            ),
            "description_not_final": (
                "{team_name_the} last played against {opponent_the.last} on {game_date.last}."
            ),
        },
        "idle_offseason": {
            "title_enabled": False,
            "title": None,
            "subtitle_enabled": True,
            "subtitle": "No upcoming game currently on schedule in next 30 days",
            "description_enabled": True,
            "description": "No upcoming {team_name} games scheduled.",
        },
        "conditional_descriptions": [
            {
                "condition": "has_preview",
                "condition_value": None,
                "template": "{game_preview}",
                "priority": 10,
                "label": "Preview (provider)",
            },
            {
                "condition": "has_structured_preview",
                "condition_value": None,
                "template": (
                    "The {away_team_record} {away_team} travel to {venue_city}, "
                    "{venue_state} to take on the {home_team_record} {home_team} at "
                    "{venue}. {last_five_summary} {series_summary}"
                ),
                "priority": 20,
                "label": "Structured preview",
            },
            {
                "condition": None,
                "condition_value": None,
                "template": (
                    "The {away_team_record} {away_team} travel to {venue_city}, "
                    "{venue_state} to take on the {home_team_record} {home_team} at {venue}."
                ),
                "priority": 100,
                "label": "Default",
            },
        ],
        "event_channel_name": "{team_name}",
        "event_channel_logo_url": "",
    }
    base.update(overrides)
    return base


def _event_base(**overrides) -> dict:
    """Shared skeleton for the event templates; variants override fields."""
    base = {
        "template_type": "event",
        "title_format": "{gracenote_category}",
        "subtitle_template": "{away_team} at {home_team}",
        "program_art_url": _EVENT_ART,
        "game_duration_mode": "sport",
        "pregame_enabled": True,
        "postgame_enabled": True,
        "idle_enabled": False,
        "xmltv_flags": _XMLTV_FLAGS,
        "xmltv_video": _XMLTV_VIDEO,
        "xmltv_categories": ["Sports", "{sport}", "Sporting Event"],
        "xmltv_filler_categories": [],
        "pregame_periods": [],
        # ESPN-copy-first (tvnk.14): provider preview is the primary text;
        # the constructed prose is the fallback when no preview exists yet.
        "pregame_fallback": {
            "title": "Coming up: {gracenote_category} at {game_time}",
            "subtitle": "{away_team} at {home_team}",
            "description": "{game_preview}",
            "description_fallback": (
                "The {away_team_record} {away_team} travel to {venue_city}, "
                "{venue_state} to play the {home_team_record} {home_team} "
                "{today_tonight} at {game_time}."
            ),
            "art_url": _EVENT_ART,
        },
        "postgame_periods": [],
        # Postgame chain (tvnk.14): conditional recap wins when the game is
        # final AND the provider published one; otherwise the fallback's
        # constructed result line renders. Event templates are positional —
        # only event-scope vars here ({event_result}, never {team_name_the}/
        # {result_text}, which are TEAM_ONLY and fail builder validation, #354).
        "postgame_fallback": {
            "title": "{gracenote_category}: Postgame",
            "subtitle": "{away_team} at {home_team}",
            "description": "Final: {event_result}",
            "art_url": _EVENT_ART,
        },
        "postgame_conditional": {
            "enabled": True,
            "description_final": "{game_recap}",
            "description_not_final": (
                "The game between {away_team_the} and {home_team_the} has not yet "
                "ended as of the last update."
            ),
        },
        "idle_content": {
            # {league}, not {team_name} — event templates have no "our team"
            # and TEAM_ONLY vars fail the event editor's validation (#354).
            "title": "{league} Programming",
            "subtitle": "",
            "description": "",
            "art_url": "",
        },
        "idle_conditional": {
            "enabled": False,
            "description_final": "",
            "description_not_final": "",
        },
        "idle_offseason": {
            "title_enabled": False,
            "title": None,
            "subtitle_enabled": False,
            "subtitle": "",
            "description_enabled": False,
            "description": "",
        },
        "conditional_descriptions": [
            {
                "condition": "has_preview",
                "condition_value": None,
                "template": "{game_preview}",
                "priority": 10,
                "label": "Preview (provider)",
            },
            # Tier-2 (tvnk.15): constructed line enriched with recent form +
            # series state — populates days ahead, unlike preview prose.
            {
                "condition": "has_structured_preview",
                "condition_value": None,
                "template": (
                    "The {away_team_record} {away_team} travel to {venue_city}, "
                    "{venue_state} to play the {home_team_record} {home_team} at "
                    "{venue}. {last_five_summary} {series_summary}"
                ),
                "priority": 20,
                "label": "Structured preview",
            },
            {
                "condition": None,
                "condition_value": None,
                "template": (
                    "The {away_team_record} {away_team} travel to {venue_city}, "
                    "{venue_state} to play the {home_team_record} {home_team} at {venue}."
                ),
                "priority": 100,
                "label": "Default",
            },
        ],
        # SUPER SHORT: "NBA | DET/LAL" — abbrev-first, fits truncating guides.
        "event_channel_name": "{league} | {away_team_abbrev}/{home_team_abbrev}",
        "event_channel_logo_url": _EVENT_LOGO,
    }
    base.update(overrides)
    return base


# Shared conditional-description rows (ESPN-copy-first, tvnk.14).
_PREVIEW_ROW = {
    "condition": "has_preview",
    "condition_value": None,
    "template": "{game_preview}",
    "priority": 10,
    "label": "Preview (provider)",
}


DEFAULT_TEMPLATE_SET: list[dict] = [
    _team_base(name="Default Team (Starter)"),
    # Soccer team channels (tvnk.8): the "face" match register verified live
    # ("Belgium face Spain…"); article-aware _the vars handle club vs national
    # naming; W-D-L records come through the generic record vars.
    _team_base(
        name="Soccer Team (Starter)",
        subtitle_template="{away_team} vs {home_team}",
        pregame_fallback={
            "title": "Coming up: {gracenote_category} at {game_time.next}",
            "subtitle": "{away_team.next} vs {home_team.next}",
            "description": "{game_preview.next}",
            "description_fallback": (
                "{away_team_the.next} face {home_team_the.next} at {venue.next} "
                "{today_tonight.next} at {game_time.next}."
            ),
            "art_url": _ART_NEXT,
        },
        conditional_descriptions=[
            dict(_PREVIEW_ROW),
            {
                "condition": "has_structured_preview",
                "condition_value": None,
                "template": (
                    "{away_team_the} face {home_team_the} at {venue}. "
                    "{last_five_summary} {series_summary}"
                ),
                "priority": 20,
                "label": "Structured preview",
            },
            {
                "condition": None,
                "condition_value": None,
                "template": "{away_team_the} face {home_team_the} at {venue}.",
                "priority": 100,
                "label": "Default",
            },
        ],
    ),
    # College team channels (tvnk.8): Gracenote's college register is home-led
    # host framing with rank + record ("No. 20 Arkansas (20-7) hosts Texas A&M
    # (19-8) at Bud Walton Arena"). Ranks render inline via the empty-safe
    # {*_rank_display} vars ('No. 20' or nothing, #354) — no ranked-only row
    # needed, and one-ranked matchups show the one rank. Names are bare per
    # the captured college register (no article).
    _team_base(
        name="College Team (Starter)",
        conditional_descriptions=[
            dict(_PREVIEW_ROW),
            {
                "condition": "is_conference_game",
                "condition_value": None,
                "template": (
                    "{home_team_rank_display} {home_team} ({home_team_record}) host "
                    "{away_team_rank_display} {away_team} ({away_team_record}) in "
                    "{college_conference} play at {venue}. "
                    "{last_five_summary} {series_summary}"
                ),
                "priority": 18,
                "label": "Conference game",
            },
            {
                "condition": "has_structured_preview",
                "condition_value": None,
                "template": (
                    "{home_team_rank_display} {home_team} ({home_team_record}) host "
                    "{away_team_rank_display} {away_team} ({away_team_record}) at "
                    "{venue}. {last_five_summary} {series_summary}"
                ),
                "priority": 20,
                "label": "Structured preview",
            },
            {
                "condition": None,
                "condition_value": None,
                "template": (
                    "{home_team_rank_display} {home_team} ({home_team_record}) host "
                    "{away_team_rank_display} {away_team} ({away_team_record}) at "
                    "{venue}."
                ),
                "priority": 100,
                "label": "Default",
            },
        ],
    ),
    # Universal event fallback — US pro leagues with abbreviations.
    _event_base(name="Default Event (Starter)"),
    # College events (tvnk.8): same home-led rank/record register as College
    # Team via the empty-safe {*_rank_display} vars (#354); conference row
    # omitted (conference stats aren't reliably present in event context).
    _event_base(
        name="College Event (Starter)",
        conditional_descriptions=[
            dict(_PREVIEW_ROW),
            {
                "condition": "has_structured_preview",
                "condition_value": None,
                "template": (
                    "{home_team_rank_display} {home_team} ({home_team_record}) host "
                    "{away_team_rank_display} {away_team} ({away_team_record}) at "
                    "{venue}. {last_five_summary} {series_summary}"
                ),
                "priority": 20,
                "label": "Structured preview",
            },
            {
                "condition": None,
                "condition_value": None,
                "template": (
                    "{home_team_rank_display} {home_team} ({home_team_record}) host "
                    "{away_team_rank_display} {away_team} ({away_team_record}) at "
                    "{venue}."
                ),
                "priority": 100,
                "label": "Default",
            },
        ],
    ),
    # Club soccer events (tvnk.8): "face" match register, soccer 'v' channel
    # connector; national-team tournaments use International Event instead.
    _event_base(
        name="Soccer Club Event (Starter)",
        subtitle_template="{away_team} vs {home_team}",
        pregame_fallback={
            "title": "Coming up: {gracenote_category} at {game_time}",
            "subtitle": "{away_team} vs {home_team}",
            "description": "{game_preview}",
            "description_fallback": (
                "{away_team_the} face {home_team_the} at {venue} "
                "{today_tonight} at {game_time}."
            ),
            "art_url": _EVENT_ART,
        },
        postgame_fallback={
            "title": "{gracenote_category}: Full Time",
            "subtitle": "{away_team} vs {home_team}",
            "description": "Full time: {event_result}",
            "art_url": _EVENT_ART,
        },
        conditional_descriptions=[
            dict(_PREVIEW_ROW),
            {
                "condition": "has_structured_preview",
                "condition_value": None,
                "template": (
                    "{away_team_the} face {home_team_the} at {venue}. "
                    "{last_five_summary} {series_summary}"
                ),
                "priority": 20,
                "label": "Structured preview",
            },
            {
                "condition": None,
                "condition_value": None,
                "template": "{away_team_the} face {home_team_the} at {venue}.",
                "priority": 100,
                "label": "Default",
            },
        ],
        # "EPL | ARS v CHE" — soccer uses 'v', not '/'
        event_channel_name="{league} | {away_team_abbrev} v {home_team_abbrev}",
    ),
    # Combat (MMA/boxing): card-segment channels, event-number titles.
    _event_base(
        name="Combat Event (Starter)",
        title_format="{league} {event_number}: {card_segment_display}",
        subtitle_template="{away_team} vs {home_team}",
        pregame_fallback={
            "title": "Coming up: {league} {event_number} at {game_time}",
            "subtitle": "{away_team} vs {home_team}",
            "description": "{game_preview}",
            "description_fallback": (
                "{away_team} takes on {home_team} at {venue} {today_tonight} at {game_time}."
            ),
            "art_url": _EVENT_ART,
        },
        # MMA carries no home/away scores, so the base 'Final: {event_result}'
        # would render empty — constructed bout-register line instead (#354).
        postgame_fallback={
            "title": "{league} {event_number}: Postgame",
            "subtitle": "{away_team} vs {home_team}",
            "description": "{away_team} vs {home_team} has concluded at {venue}.",
            "art_url": _EVENT_ART,
        },
        postgame_conditional={
            "enabled": True,
            "description_final": "{game_recap}",
            "description_not_final": (
                "The bout between {away_team} and {home_team} has not yet ended "
                "as of the last update."
            ),
        },
        conditional_descriptions=[
            {
                "condition": "has_preview",
                "condition_value": None,
                "template": "{game_preview}",
                "priority": 10,
                "label": "Preview (provider)",
            },
            {
                "condition": None,
                "condition_value": None,
                "template": "{away_team} takes on {home_team} at {venue}.",
                "priority": 100,
                "label": "Default",
            },
        ],
        # "UFC 310 Main Card"
        event_channel_name="{league} {event_number} {card_segment_display}",
    ),
    # International (national teams / tournaments): category-led naming.
    # Title composes the year per the tvnk.12 decision — real Gracenote brands
    # tournaments year-stamped ('FIFA World Cup 2026'); the seed carries the
    # brand, the template adds the year. Article-aware _the vars keep national
    # teams bare ("Belgium face Spain") and any club sides articled.
    _event_base(
        name="International Event (Starter)",
        title_format="{gracenote_category} {year}",
        subtitle_template="{away_team} vs {home_team}",
        # "NED v JPN"
        event_channel_name="{away_team_abbrev} v {home_team_abbrev}",
        postgame_fallback={
            "title": "{gracenote_category}: Full Time",
            "subtitle": "{away_team} vs {home_team}",
            "description": "Full time: {event_result}",
            "art_url": _EVENT_ART,
        },
        conditional_descriptions=[
            dict(_PREVIEW_ROW),
            {
                "condition": "has_structured_preview",
                "condition_value": None,
                "template": (
                    "{away_team_the} face {home_team_the} at {venue}. "
                    "{last_five_summary} {series_summary}"
                ),
                "priority": 20,
                "label": "Structured preview",
            },
            {
                "condition": None,
                "condition_value": None,
                "template": "{away_team_the} face {home_team_the} at {venue}.",
                "priority": 100,
                "label": "Default",
            },
        ],
    ),
    # Tennis (bead tvnk.13): tournament-led titles, player-surname channels.
    # Year-prefixed per the Gracenote tournament convention ('2026 U.S. Open
    # Golf Championship' captured; tennis majors follow the same shape).
    _event_base(
        name="Tennis Event (Starter)",
        title_format="{year} {tournament_name}",
        subtitle_template="{tennis_round} - {player1} vs {player2}",
        pregame_fallback={
            "title": "Coming up: {tournament_name} at {game_time}",
            "subtitle": "{player1} vs {player2}",
            "description": "{game_preview}",
            "description_fallback": (
                "{player1} takes on {player2} in the {tennis_round} of "
                "{tournament_name_the} ({tennis_draw})."
            ),
            "art_url": _EVENT_ART,
        },
        # Recap-first with a constructed fallback — tvnk.14 finding: the
        # prior seed had {game_recap} as BOTH primary and fallback, so a
        # missing recap rendered an empty description.
        postgame_fallback={
            "title": "{tournament_name}: Match Complete",
            "subtitle": "{player1} vs {player2}",
            "description": (
                "{player1} and {player2} have completed their {tennis_round} "
                "match at {tournament_name_the}."
            ),
            "art_url": _EVENT_ART,
        },
        postgame_conditional={
            "enabled": True,
            "description_final": "{tennis_result}",
            "description_not_final": (
                "The match between {player1} and {player2} has not yet ended as of the last update."
            ),
        },
        conditional_descriptions=[
            {
                "condition": "has_preview",
                "condition_value": None,
                "template": "{game_preview}",
                "priority": 10,
                "label": "Preview (provider)",
            },
            {
                "condition": None,
                "condition_value": None,
                "template": (
                    "{player1} takes on {player2} in the {tennis_round} of "
                    "{tournament_name_the} ({tennis_draw})."
                ),
                "priority": 100,
                "label": "Default",
            },
        ],
        # "Alcaraz v Sinner" — surnames only, super short.
        event_channel_name="{player1_last} v {player2_last}",
    ),
]


def _retired_no_abbrev_spec() -> dict:
    """The retired "No-Abbrev Event" member's content, for removal healing.

    Retired because the *_team_abbrev variables now fall back to short/full
    names when a league has none — Default Event covers the case (#329)."""
    return _event_base(
        name="No-Abbrev Event",
        event_channel_name="{away_team} / {home_team}",
    )


def _retired_milb_specs() -> list[dict]:
    """The retired MiLB member's content, under both name generations.

    Retired in tvnk.4: its branding rationale moved into the data layer —
    the MiLB gracenote_category seeds ('Minor League Baseball', tvnk.8) give
    Default Event the identical title, leaving only the 'MiLB |' channel
    prefix vs Default Event's per-level '{league} |' ('AAA |'), which is the
    more informative form."""
    spec = _event_base(
        name="MiLB Event (Starter)",
        event_channel_name="MiLB | {away_team_abbrev}/{home_team_abbrev}",
    )
    prior = dict(spec)
    prior["name"] = "MiLB Event"
    return [spec, prior]


def _is_referenced(conn: Connection, template_id: int) -> bool:
    """True when any assignment or channel references the template.

    Deleting a referenced template would silently unassign it (teams and
    event_epg_groups SET NULL; group/subscription assignments CASCADE), so
    retirement only removes rows that are unedited AND unreferenced.
    """
    for table in ("teams", "event_epg_groups", "group_templates", "subscription_templates"):
        row = conn.execute(
            f"SELECT 1 FROM {table} WHERE template_id = ? LIMIT 1", (template_id,)
        ).fetchone()
        if row is not None:
            return True
    return False


def seed_default_templates(conn: Connection) -> None:
    """Seed the curated default set — idempotent, safe on every startup.

    1. A PRISTINE legacy seed ("Team"/"Event" still carrying the broken
       localhost:3000 placeholder art) is upgraded in place to its curated
       replacement — same row id, so assignments survive (tvnk.1 decision).
    2. Any set member missing by name is created (fresh installs get the full
       set; upgrades pick up new members). Existing rows are NEVER
       overwritten — except unedited prior-iteration rows, which are healed
       to current content in place (steps 1b/1c).
    """
    from teamarr.database.templates import (
        create_template,
        delete_template,
        get_all_templates,
        update_template,
    )

    existing = {t.name: t for t in get_all_templates(conn)}
    specs = {spec["name"]: spec for spec in DEFAULT_TEMPLATE_SET}

    # 1. Upgrade pristine legacy seeds in place (keeps ids/assignments).
    for legacy_name, curated_name in LEGACY_UPGRADES.items():
        row = existing.get(legacy_name)
        if row is None or not _is_pristine_legacy(row, legacy_name):
            continue  # absent or user-modified — curated added below if missing
        dup = existing.get(curated_name)
        if dup is not None:
            # Transitional healing: an earlier pass seeded the curated row
            # alongside this pristine legacy one. If that duplicate is still
            # untouched, fold it back so the legacy row (which holds the
            # references) becomes the curated one; otherwise leave both.
            if not _is_unedited_curated(dup, specs[curated_name]):
                continue
            delete_template(conn, dup.id)
            del existing[curated_name]
        spec = dict(specs[curated_name])
        update_template(conn, row.id, **spec)
        existing[curated_name] = existing.pop(legacy_name)

    # 1b. Rename unedited prior-iteration curated rows in place (same id).
    # A prior-name row may also carry a prior-iteration TITLE (a pre-tvnk.8
    # "International Event" still titled '{gracenote_category}'), so the
    # fingerprint accepts either title generation.
    for prior, current in PRIOR_NAME_UPGRADES.items():
        row = existing.get(prior)
        if row is None or current in existing or current not in specs:
            continue
        prior_spec = dict(specs[current])
        prior_spec["name"] = prior
        unedited = _is_unedited_curated(row, prior_spec)
        if not unedited and current in PRIOR_TITLE_UPGRADES:
            prior_spec["title_format"] = PRIOR_TITLE_UPGRADES[current]
            unedited = _is_unedited_curated(row, prior_spec)
        if not unedited:
            continue
        update_template(conn, row.id, **specs[current])
        existing[current] = existing.pop(prior)

    # 1c. Upgrade unedited prior-CONTENT rows in place (same id) — members
    # whose seeded title changed across iterations (tvnk.8: year-composed
    # International/Tennis titles). Edited rows are left alone.
    for member, old_title in PRIOR_TITLE_UPGRADES.items():
        row = existing.get(member)
        if row is None or member not in specs:
            continue
        old_spec = dict(specs[member])
        old_spec["title_format"] = old_title
        if not _is_unedited_curated(row, old_spec):
            continue
        update_template(conn, row.id, **specs[member])

    # 1d. Remove retired members that are still our unedited seed — and are
    # unreferenced: a retired starter someone assigned stays put (deleting it
    # would silently unassign their channels).
    for retired_spec in [_retired_no_abbrev_spec(), *_retired_milb_specs()]:
        row = existing.get(retired_spec["name"])
        if row is None or not _is_unedited_curated(row, retired_spec):
            continue
        if _is_referenced(conn, row.id):
            continue
        delete_template(conn, row.id)
        del existing[retired_spec["name"]]

    # 2. Add missing set members.
    for name, spec in specs.items():
        if name in existing:
            continue
        create_template(conn, **spec)
