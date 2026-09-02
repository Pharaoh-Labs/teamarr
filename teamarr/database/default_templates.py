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
  postgame registers carry a ``has_recap → {game_recap}`` condition row
  (#420, cajd.6 — fires only when the provider published one; tennis gates
  its constructed ``{tennis_result}`` on ``is_final`` instead) over the
  base register's constructed result line, with an ``is_not_final`` row
  for still-running games. Legacy final/not-final columns ship disabled.
- Per-sport-family registers (tvnk.8 synthesis): the base US-pro travel-line
  register is joined by soccer ("face" match register, article-aware _the
  vars, 'v' channel connector), college (home-led host framing with rank +
  record + conference rows, per the captured Gracenote preview register), and
  year-composed tournament titles (International ``{gracenote_category}
  {year}`` per the tvnk.12 decision; Tennis ``{year} {tournament_name}``;
  Racing series-led titles with race + session subtitles, #355 item 1).
  Combat/tennis/racing get no team variants — no meaningful team channels
  (racing driver channels are epic hjzo).
"""

import copy
from sqlite3 import Connection

from teamarr.core.filler_types import legacy_conditional_to_rows
from teamarr.templates.resolver import rewrite_legacy_tokens

# Neutralized legacy filler conditional (#420, cajd.6): starters author
# condition rows natively; the legacy columns ship disabled so the v80
# migration (skips disabled) and the read path's legacy shim (skips when
# rows are non-empty) can never fight the authored rows.
_LEGACY_CONDITIONAL_OFF = {
    "enabled": False,
    "description_final": None,
    "description_not_final": None,
}

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
_ART_PATH = "{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png"
_TEAM_ART = _ART_PATH + _TEAM_PARAMS
_EVENT_ART = _ART_PATH + _EVENT_PARAMS
_ART_NEXT = "{league_id}/{away_team.next|pascal}/{home_team.next|pascal}/cover.png" + _TEAM_PARAMS
_ART_LAST = "{league_id}/{away_team.last|pascal}/{home_team.last|pascal}/cover.png" + _TEAM_PARAMS
_EVENT_LOGO = (
    "{league_code}/{away_team|pascal}/{home_team|pascal}/logo.png"
    "?style=1&logo=true&fallback=true"
    "&badge={broadcast_national_network}%20{exception_keyword}"
)

_XMLTV_FLAGS = {"new": True, "live": True, "date": True}
_XMLTV_VIDEO = {"enabled": False, "quality": "HDTV"}

# Legacy seeds shipped with this placeholder art. Migration v75 (z02s) later
# stripped the origin into the art_base_url setting, so upgraded installs
# carry the RELATIVE form instead — pristine detection accepts both.
LEGACY_PRISTINE_MARKER = "http://localhost:3000/"
_LEGACY_STRIPPED_ART = "{league_id}/{away_team|pascal}/{home_team|pascal}/cover.png"

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
    # Retired transform tokens compare as their base|filter form (#484) —
    # legacy rows predate the v84 rewrite by definition.
    art = rewrite_legacy_tokens(row.program_art_url or "")
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


# ---------------------------------------------------------------------------
# Deep content fingerprint + generation healing (#373, #355 item 14)
# ---------------------------------------------------------------------------

# Every authored surface of a spec. A row counts as "our unedited seed" only
# when ALL of these match a registered content generation — the shallow
# title/subtitle/channel/art check used before #373 let description-only
# edits count as unedited, so heals could clobber them and retirement could
# even delete them.
_CONTENT_FIELDS = (
    "title_format",
    "subtitle_template",
    "event_channel_name",
    "game_duration_mode",
    "pregame_enabled",
    "postgame_enabled",
    "idle_enabled",
    "xmltv_flags",
    "xmltv_video",
    "xmltv_categories",
    "xmltv_filler_categories",
    "pregame_periods",
    "postgame_periods",
    "pregame_fallback",
    "postgame_fallback",
    "postgame_conditional",
    "idle_content",
    "idle_conditional",
    "idle_offseason",
    "pregame_conditional_rows",
    "postgame_conditional_rows",
    "idle_conditional_rows",
    "conditional_descriptions",
)


def _norm(value):
    """Normalization for content comparison: None and '' are equivalent,
    bools and 0/1 are equivalent, empty dict values drop, containers
    recurse, retired transform tokens compare as their base|filter form
    (#484 — a not-yet-migrated row is still 'unedited'). Tolerates JSON
    round-trip and storage-default drift."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items() if _norm(v) != ""}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    if isinstance(value, str):
        return rewrite_legacy_tokens(value)
    return value


def _art_matches(row_value, spec_value) -> bool:
    """Art matches the spec value or its bare (param-less) earlier form.
    Retired transform tokens (#484) compare as their base|filter form."""
    art = rewrite_legacy_tokens(row_value or "")
    spec_art = spec_value or ""
    candidates = {spec_art, spec_art.split("?")[0]}
    if "{league_code}" in spec_art:
        id_variant = spec_art.replace("{league_code}", "{league_id}")
        candidates.add(id_variant)
        candidates.add(id_variant.split("?")[0])
    return art in candidates


def _content_matches(row, spec: dict) -> bool:
    """True when the row still carries exactly the authored content of spec
    — every text surface and filler block, not just title/subtitle/art."""
    if not _art_matches(row.program_art_url, spec.get("program_art_url")):
        return False
    if not _art_matches(row.event_channel_logo_url, spec.get("event_channel_logo_url")):
        return False
    return all(_norm(getattr(row, f)) == _norm(spec.get(f)) for f in _CONTENT_FIELDS)


# Marquee-row text as #364 first shipped it — #367 reframed it to 'meet at'
# (host/travel framing lies at neutral sites). Needed to reconstruct the G2
# generation for healing.
_G2_MARQUEE_US = (
    "{game_event_note}. The {away_team_record} {away_team} travel to "
    "{venue_city}, {venue_state} to take on the {home_team_record} "
    "{home_team} at {venue}."
)
_G2_MARQUEE_COLLEGE = (
    "{game_event_note}. {home_team_rank_display} {home_team} "
    "({home_team_record}) host {away_team_rank_display} {away_team} "
    "({away_team_record}) at {venue}."
)


def _revert_at_vs(text: str | None) -> str | None:
    """Undo the #367 neutral-aware connector: '{at_vs}' back to 'at'."""
    if not text:
        return text
    for suffix in ("", ".next", ".last"):
        text = text.replace(f" {{at_vs{suffix}}} ", " at ")
    return text


# --- pre-#420 filler representation (cajd.6) -------------------------------

_ROWS_TO_LEGACY = (
    ("postgame_conditional_rows", "postgame_conditional"),
    ("idle_conditional_rows", "idle_conditional"),
)

# v80 stamped these labels when converting enabled legacy conditionals; the
# in-memory twin uses "(legacy)". Reconstructed generations must match what
# real upgraded installs carry.
_V80_LABELS = {
    "Final (legacy)": "Final (migrated)",
    "In progress (legacy)": "In progress (migrated)",
}


# --- pre-#692 team order (phase 2) ------------------------------------------

_TEAM_ORDER_REVERTS = (
    tuple((f"{{team1{sfx}}}", f"{{away_team{sfx}}}") for sfx in ("", ".next", ".last"))
    + tuple((f"{{team2{sfx}}}", f"{{home_team{sfx}}}") for sfx in ("", ".next", ".last"))
    + (("{team1_abbrev}", "{away_team_abbrev}"), ("{team2_abbrev}", "{home_team_abbrev}"))
)


def _revert_team_order_text(text):
    """Undo #692 phase 2: order-aware {team1}/{team2} back to away/home."""
    if not text:
        return text
    for new, old in _TEAM_ORDER_REVERTS:
        text = text.replace(new, old)
    return text


def _revert_team_order(spec: dict) -> dict:
    """The spec's content in its pre-#692 shape: subtitles and the event
    channel name spelled with {away_team}/{home_team} instead of the
    order-aware {team1}/{team2} (G5)."""
    g = copy.deepcopy(spec)
    for f in ("subtitle_template", "event_channel_name"):
        g[f] = _revert_team_order_text(g.get(f))
    for section in ("pregame_fallback", "postgame_fallback", "idle_content"):
        block = g.get(section) or {}
        if block.get("subtitle"):
            block["subtitle"] = _revert_team_order_text(block["subtitle"])
    return g


def _revert_filler_rows(spec: dict) -> dict:
    """The spec's content in its pre-#420 shape: native condition rows
    reverted to the enabled legacy final/not-final dicts those generations
    shipped. The primary row (has_recap, or is_final for constructed-result
    registers like tennis) maps to description_final; is_not_final maps to
    description_not_final. Rows columns are emptied (they postdate #420)."""
    g = copy.deepcopy(spec)
    for rows_field, legacy_field in _ROWS_TO_LEGACY:
        rows = {r.get("condition"): r for r in (g.get(rows_field) or [])}
        primary = rows.get("has_recap") or rows.get("is_final")
        not_final = rows.get("is_not_final")
        if primary or not_final:
            g[legacy_field] = {
                "enabled": True,
                "description_final": (primary or {}).get("template"),
                "description_not_final": (not_final or {}).get("template"),
            }
    for f in ("pregame_conditional_rows", "postgame_conditional_rows", "idle_conditional_rows"):
        g[f] = []
    return g


def _with_v80_rows(gen: dict) -> dict:
    """A pre-#420 generation as an UPGRADED install carries it: the enabled
    legacy conditionals plus the v80 migration's converted rows."""
    g = copy.deepcopy(gen)
    for rows_field, legacy_field in _ROWS_TO_LEGACY:
        rows = legacy_conditional_to_rows(g.get(legacy_field))
        g[rows_field] = [{**r, "label": _V80_LABELS.get(r["label"], r["label"])} for r in rows]
    return g


def _prior_generations(name: str, spec: dict) -> list[dict]:
    """Registered prior content generations of a set member, newest first.

    G5 (pre-#692 phase 2): current content with {team1}/{team2} reverted
        to {away_team}/{home_team} in subtitles / event channel name.
    G4 (pre-#420 cajd.6): G5 with the filler condition rows reverted to
        the enabled legacy final/not-final conditionals.
    G3 (#367 era, pre-#369): G4 minus the soccer idle overrides.
    G2 (#364 era, pre-#367): G3 minus neutral-site rows, marquee rows in
        the original travel/host framing, hard-coded 'at' subtitles.
    G0 (tvnk.8, pre-#364): G2 minus marquee/competition-note rows.

    Every pre-#420 generation is emitted in TWO rows-column variants —
    with the v80 migration's converted rows (upgraded installs) and with
    empty rows (rows created in the post-v80/pre-#420 window) — since real
    rows carry one or the other.

    Generations identical to their predecessor are skipped (member
    untouched by that change). Racing joined post-#364 and has no pre-G4
    generations. Prior TITLE variants (PRIOR_TITLE_UPGRADES) are crossed
    in by _matches_any_generation, not here.
    """
    legacy_chain: list[dict] = []

    # G5 (#692 phase 2): current content with {team1}/{team2} reverted to
    # {away_team}/{home_team} in subtitles and the event channel name. It
    # postdates #420, so it carries native rows and is emitted as-is (no
    # v80/empty-rows variants) — see the tail of this function.
    g5 = _revert_team_order(spec)

    g4 = _revert_filler_rows(g5)
    if g4 != g5:
        legacy_chain.append(g4)

    g3 = copy.deepcopy(g4)
    if name == "Soccer Team (Starter)":
        base = _revert_filler_rows(_team_base())
        for f in ("idle_content", "idle_conditional", "idle_offseason"):
            g3[f] = base[f]  # #369 reverted: soccer idle was the base text
    if g3 != g4:
        legacy_chain.append(g3)

    g2 = copy.deepcopy(g3)
    g2["conditional_descriptions"] = [
        r for r in g2["conditional_descriptions"] if r.get("label") != "Neutral site"
    ]
    for r in g2["conditional_descriptions"]:
        if r.get("label") == "Marquee note":
            r["template"] = _G2_MARQUEE_COLLEGE if "College" in name else _G2_MARQUEE_US
    g2["subtitle_template"] = _revert_at_vs(g2.get("subtitle_template"))
    for section in ("pregame_fallback", "postgame_fallback"):
        block = g2.get(section) or {}
        if block.get("subtitle"):
            block["subtitle"] = _revert_at_vs(block["subtitle"])
    if g2 != g3:
        legacy_chain.append(g2)

    g0 = copy.deepcopy(g2)
    g0["conditional_descriptions"] = [
        r
        for r in g0["conditional_descriptions"]
        if r.get("label") not in ("Marquee note", "Competition note")
    ]
    if g0 != g2:
        legacy_chain.append(g0)

    gens: list[dict] = [g5] if g5 != spec else []
    for g in legacy_chain:
        gens.append(_with_v80_rows(g))
        gens.append(g)  # empty-rows variant (post-v80 window)
    return gens


def _matches_any_generation(row, name: str, spec: dict) -> bool:
    """Row content equals the current spec or ANY registered prior content
    generation (crossed with prior title variants) — i.e., it is provably
    our unedited seed. Any user edit fails every candidate and the row is
    left alone."""
    candidates = [spec, *_prior_generations(name, spec)]
    old_title = PRIOR_TITLE_UPGRADES.get(name)
    if old_title:
        for cand in list(candidates):
            titled = copy.deepcopy(cand)
            titled["title_format"] = old_title
            candidates.append(titled)
    return any(_content_matches(row, cand) for cand in candidates)


def _team_base(**overrides) -> dict:
    """Shared skeleton for the team templates; variants override fields.

    The base register is US-pro (travel-line prose, W-L records); per-sport
    variants (tvnk.8) swap the description register — soccer gets the "face"
    match register, college the home-led rank/record host framing.
    """
    base = {
        "template_type": "team",
        "title_format": "{gracenote_category}",
        "subtitle_template": "{team1} {at_vs} {team2}",
        "program_art_url": _TEAM_ART,
        "game_duration_mode": "sport",
        "pregame_enabled": True,
        "postgame_enabled": True,
        "idle_enabled": True,
        "xmltv_flags": _XMLTV_FLAGS,
        "xmltv_video": _XMLTV_VIDEO,
        "xmltv_categories": ["Sports", "{sport}", "Sports event"],
        "xmltv_filler_categories": [],
        "pregame_periods": [],
        # ESPN-copy-first (tvnk.14): provider preview is the primary text;
        # the constructed prose is the fallback when no preview exists yet.
        "pregame_fallback": {
            "title": "Coming up: {gracenote_category} at {game_time.next}",
            "subtitle": "{team1.next} {at_vs.next} {team2.next}",
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
            "subtitle": "{team1.last} {at_vs.last} {team2.last}",
            "description": (
                "{team_name_the} {result_text.last} {opponent_the.last} {final_score.last}"
            ),
            "art_url": _ART_LAST,
        },
        "postgame_conditional": dict(_LEGACY_CONDITIONAL_OFF),
        # Native condition rows (#420, cajd.6): has_recap replaces the old
        # is_final+{game_recap} pairing as the primary mechanism — it fires
        # only when the provider actually published a recap (a final game
        # without one falls straight to the constructed result line).
        "postgame_conditional_rows": [
            {
                "condition": "has_recap",
                "condition_value": None,
                "template": "{game_recap.last}",
                "priority": 10,
                "label": "Recap (provider)",
            },
            {
                "condition": "is_not_final",
                "condition_value": None,
                "template": (
                    "The game between {team_name_the} and {opponent_the.last} on "
                    "{game_date.last} has not yet ended as of the last update."
                ),
                "priority": 50,
                "label": "In progress",
            },
        ],
        "idle_content": {
            "title": "No {team_name} Game Today",
            "subtitle": (
                "Next game: {game_date.next} at {game_time.next} {vs_at.next} {opponent_the.next}"
            ),
            "description": "Next game: {game_date.next} at {game_time.next} vs {opponent.next}",
            "art_url": "",
        },
        "idle_conditional": dict(_LEGACY_CONDITIONAL_OFF),
        "idle_conditional_rows": [
            {
                "condition": "is_final",
                "condition_value": None,
                "template": (
                    "{team_name_the} {result_text.last} {opponent_the.last} "
                    "{final_score.last} {overtime_text.last} on {game_date.last}. "
                    "Next game will be with {opponent_the.next} on {game_date.next}"
                ),
                "priority": 50,
                "label": "Final",
            },
            {
                "condition": "is_not_final",
                "condition_value": None,
                "template": (
                    "{team_name_the} last played against {opponent_the.last} on {game_date.last}."
                ),
                "priority": 50,
                "label": "In progress",
            },
        ],
        "pregame_conditional_rows": [],
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
            # Marquee/playoff note (#355 item 2): 'NBA Finals - Game 5. The…'
            # — fires only when ESPN attaches a note; ordinary games skip it.
            # Framing-neutral 'meet at' prose (#355 item 3): marquee games are
            # often neutral-site (bowls, CFP), where host/travel framing lies.
            {
                "condition": "has_event_note",
                "condition_value": None,
                "template": (
                    "{game_event_note}. The {away_team_record} {away_team} and the "
                    "{home_team_record} {home_team} meet at {venue}."
                ),
                "priority": 15,
                "label": "Marquee note",
            },
            # Neutral site without a note (#355 item 3): kickoff classics,
            # unnoted tournament rounds — nobody hosts, so 'meet at' framing.
            {
                "condition": "is_neutral_site",
                "condition_value": None,
                "template": (
                    "The {away_team_record} {away_team} and the {home_team_record} "
                    "{home_team} meet at {venue}. {last_five_summary} {series_summary}"
                ),
                "priority": 17,
                "label": "Neutral site",
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
        "subtitle_template": "{team1} {at_vs} {team2}",
        "program_art_url": _EVENT_ART,
        "game_duration_mode": "sport",
        "pregame_enabled": True,
        "postgame_enabled": True,
        "idle_enabled": False,
        "xmltv_flags": _XMLTV_FLAGS,
        "xmltv_video": _XMLTV_VIDEO,
        "xmltv_categories": ["Sports", "{sport}", "Sports event"],
        "xmltv_filler_categories": [],
        "pregame_periods": [],
        # ESPN-copy-first (tvnk.14): provider preview is the primary text;
        # the constructed prose is the fallback when no preview exists yet.
        "pregame_fallback": {
            "title": "Coming up: {gracenote_category} at {game_time}",
            "subtitle": "{team1} {at_vs} {team2}",
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
            "subtitle": "{team1} {at_vs} {team2}",
            "description": "Final: {event_result}",
            "art_url": _EVENT_ART,
        },
        "postgame_conditional": dict(_LEGACY_CONDITIONAL_OFF),
        # Native condition rows (#420, cajd.6) — recap-when-published wins;
        # a still-running game gets the in-progress line; a final game with
        # no recap falls to the base "Final: {event_result}".
        "postgame_conditional_rows": [
            {
                "condition": "has_recap",
                "condition_value": None,
                "template": "{game_recap}",
                "priority": 10,
                "label": "Recap (provider)",
            },
            {
                "condition": "is_not_final",
                "condition_value": None,
                "template": (
                    "The game between {away_team_the} and {home_team_the} has not yet "
                    "ended as of the last update."
                ),
                "priority": 50,
                "label": "In progress",
            },
        ],
        "idle_content": {
            # {league}, not {team_name} — event templates have no "our team"
            # and TEAM_ONLY vars fail the event editor's validation (#354).
            "title": "{league} Programming",
            "subtitle": "",
            "description": "",
            "art_url": "",
        },
        "idle_conditional": dict(_LEGACY_CONDITIONAL_OFF),
        "idle_conditional_rows": [],
        "pregame_conditional_rows": [],
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
            # Marquee/playoff note (#355 item 2): 'NBA Finals - Game 5. The…'
            # — fires only when ESPN attaches a note; ordinary games skip it.
            # Framing-neutral 'meet at' prose (#355 item 3): marquee games are
            # often neutral-site (bowls, CFP), where host/travel framing lies.
            {
                "condition": "has_event_note",
                "condition_value": None,
                "template": (
                    "{game_event_note}. The {away_team_record} {away_team} and the "
                    "{home_team_record} {home_team} meet at {venue}."
                ),
                "priority": 15,
                "label": "Marquee note",
            },
            # Neutral site without a note (#355 item 3): kickoff classics,
            # unnoted tournament rounds — nobody hosts, so 'meet at' framing.
            {
                "condition": "is_neutral_site",
                "condition_value": None,
                "template": (
                    "The {away_team_record} {away_team} and the {home_team_record} "
                    "{home_team} meet at {venue}. {last_five_summary} {series_summary}"
                ),
                "priority": 17,
                "label": "Neutral site",
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
        "event_channel_name": "{league} | {team1_abbrev}/{team2_abbrev}",
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

# Competition/stage note for the soccer-register starters (#355 item 2):
# 'FIFA World Cup, Group C. Belgium face Spain at MetLife Stadium.' — fires
# only when the provider attaches a note.
_MATCH_NOTE_ROW = {
    "condition": "has_match_note",
    "condition_value": None,
    "template": "{soccer_match_note}. {away_team_the} face {home_team_the} at {venue}.",
    "priority": 15,
    "label": "Competition note",
}


DEFAULT_TEMPLATE_SET: list[dict] = [
    _team_base(name="Default Team (Starter)"),
    # Soccer team channels (tvnk.8): the "face" match register verified live
    # ("Belgium face Spain…"); article-aware _the vars handle club vs national
    # naming; W-D-L records come through the generic record vars.
    _team_base(
        name="Soccer Team (Starter)",
        subtitle_template="{team1} vs {team2}",
        # Match register (#355 item 5): soccer filler says 'match', never
        # 'game'. College keeps the base text — 'game' IS its register.
        idle_content={
            "title": "No {team_name} Match Today",
            "subtitle": (
                "Next match: {game_date.next} at {game_time.next} "
                "{vs_at.next} {opponent_the.next}"
            ),
            "description": "Next match: {game_date.next} at {game_time.next} vs {opponent.next}",
            "art_url": "",
        },
        idle_conditional_rows=[
            {
                "condition": "is_final",
                "condition_value": None,
                "template": (
                    "{team_name_the} {result_text.last} {opponent_the.last} "
                    "{final_score.last} on {game_date.last}. "
                    "Next match is against {opponent_the.next} on {game_date.next}"
                ),
                "priority": 50,
                "label": "Final",
            },
            {
                "condition": "is_not_final",
                "condition_value": None,
                "template": (
                    "{team_name_the} last played {opponent_the.last} on {game_date.last}."
                ),
                "priority": 50,
                "label": "In progress",
            },
        ],
        idle_offseason={
            "title_enabled": False,
            "title": None,
            "subtitle_enabled": True,
            "subtitle": "No upcoming match currently on schedule in next 30 days",
            "description_enabled": True,
            "description": "No upcoming {team_name} matches scheduled.",
        },
        pregame_fallback={
            "title": "Coming up: {gracenote_category} at {game_time.next}",
            "subtitle": "{team1.next} vs {team2.next}",
            "description": "{game_preview.next}",
            "description_fallback": (
                "{away_team_the.next} face {home_team_the.next} at {venue.next} "
                "{today_tonight.next} at {game_time.next}."
            ),
            "art_url": _ART_NEXT,
        },
        conditional_descriptions=[
            dict(_PREVIEW_ROW),
            dict(_MATCH_NOTE_ROW),
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
            # Marquee note: bowls, CFP rounds, tournament designations
            # ('CFP Quarterfinal at the Cotton Bowl Classic. …', #355 item 2).
            # 'Meet at' framing, not 'host' — these are mostly neutral-site
            # games (#355 item 3).
            {
                "condition": "has_event_note",
                "condition_value": None,
                "template": (
                    "{game_event_note}. {away_team_rank_display} {away_team} "
                    "({away_team_record}) and {home_team_rank_display} {home_team} "
                    "({home_team_record}) meet at {venue}."
                ),
                "priority": 15,
                "label": "Marquee note",
            },
            # Neutral site without a note (#355 item 3).
            {
                "condition": "is_neutral_site",
                "condition_value": None,
                "template": (
                    "{away_team_rank_display} {away_team} ({away_team_record}) and "
                    "{home_team_rank_display} {home_team} ({home_team_record}) meet "
                    "at {venue}. {last_five_summary} {series_summary}"
                ),
                "priority": 17,
                "label": "Neutral site",
            },
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
            # Marquee note: bowls, CFP rounds, tournament designations
            # ('CFP Quarterfinal at the Cotton Bowl Classic. …', #355 item 2).
            # 'Meet at' framing, not 'host' — these are mostly neutral-site
            # games (#355 item 3).
            {
                "condition": "has_event_note",
                "condition_value": None,
                "template": (
                    "{game_event_note}. {away_team_rank_display} {away_team} "
                    "({away_team_record}) and {home_team_rank_display} {home_team} "
                    "({home_team_record}) meet at {venue}."
                ),
                "priority": 15,
                "label": "Marquee note",
            },
            # Neutral site without a note (#355 item 3).
            {
                "condition": "is_neutral_site",
                "condition_value": None,
                "template": (
                    "{away_team_rank_display} {away_team} ({away_team_record}) and "
                    "{home_team_rank_display} {home_team} ({home_team_record}) meet "
                    "at {venue}. {last_five_summary} {series_summary}"
                ),
                "priority": 17,
                "label": "Neutral site",
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
    # Club soccer events (tvnk.8): "face" match register, soccer 'v' channel
    # connector; national-team tournaments use International Event instead.
    _event_base(
        name="Soccer Club Event (Starter)",
        subtitle_template="{team1} vs {team2}",
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
            dict(_MATCH_NOTE_ROW),
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
        subtitle_template="{team1} vs {team2}",
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
        postgame_conditional_rows=[
            {
                "condition": "has_recap",
                "condition_value": None,
                "template": "{game_recap}",
                "priority": 10,
                "label": "Recap (provider)",
            },
            {
                "condition": "is_not_final",
                "condition_value": None,
                "template": (
                    "The bout between {away_team} and {home_team} has not yet ended "
                    "as of the last update."
                ),
                "priority": 50,
                "label": "In progress",
            },
        ],
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
        subtitle_template="{team1} vs {team2}",
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
            dict(_MATCH_NOTE_ROW),
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
        # {tennis_result} is constructed from score data, not provider copy —
        # is_final (not has_recap) is its correct gate.
        postgame_conditional_rows=[
            {
                "condition": "is_final",
                "condition_value": None,
                "template": "{tennis_result}",
                "priority": 50,
                "label": "Final",
            },
            {
                "condition": "is_not_final",
                "condition_value": None,
                "template": (
                    "The match between {player1} and {player2} has not yet ended "
                    "as of the last update."
                ),
                "priority": 50,
                "label": "In progress",
            },
        ],
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
    # Racing (F1/NASCAR/IndyCar/IMSA/WEC, #355 item 1): weekends expand into
    # one channel per session (racing_segments.py), and home/away are the SAME
    # placeholder team — every matchup-shaped surface (subtitle, art paths,
    # abbrev channel names) must be overridden or it renders "Navy 250 at
    # Navy 250". Captured Gracenote shape: title 'NASCAR Cup Series', subtitle
    # 'Navy 250, Practice 1' — series-led title, race + session subtitle.
    _event_base(
        name="Racing Event (Starter)",
        title_format="{gracenote_category}",
        subtitle_template="{race_name}, {session_name}",
        # No matchup art: the pascal-var cover path would compose from the
        # placeholder team and render broken.
        program_art_url="",
        event_channel_logo_url="",
        pregame_fallback={
            "title": "Coming up: {session_name} at {game_time}",
            "subtitle": "{race_name}, {session_name}",
            "description": "{game_preview}",
            "description_fallback": (
                "{race_name} {session_name} from {circuit_name} {today_tonight} at {game_time}."
            ),
            "art_url": "",
        },
        # "Postgame" reads wrong for racing ("Navy 250: Postgame" for a
        # practice session) — session-complete register instead, mirroring
        # the tennis starter's "Match Complete".
        postgame_fallback={
            "title": "{race_name}: {session_name} Complete",
            "subtitle": "{race_name}, {session_name}",
            "description": "{race_name} {session_name} has concluded at {circuit_name}.",
            "art_url": "",
        },
        postgame_conditional_rows=[
            {
                "condition": "has_recap",
                "condition_value": None,
                "template": "{game_recap}",
                "priority": 10,
                "label": "Recap (provider)",
            },
            {
                "condition": "is_not_final",
                "condition_value": None,
                "template": (
                    "{race_name} {session_name} has not yet ended as of the last update."
                ),
                "priority": 50,
                "label": "In progress",
            },
        ],
        conditional_descriptions=[
            dict(_PREVIEW_ROW),
            {
                "condition": None,
                "condition_value": None,
                "template": "{race_name} {session_name} at {circuit_name}.",
                "priority": 100,
                "label": "Default",
            },
        ],
        # "NASCAR Cup | Race", "F1 | Qualifying" — series alias + session.
        event_channel_name="{league} | {session_name}",
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


def seed_default_templates(conn: Connection) -> int:
    """Seed the curated default set — idempotent, safe on every startup.

    1. A PRISTINE legacy seed ("Team"/"Event" still carrying the broken
       localhost:3000 placeholder art) is upgraded in place to its curated
       replacement — same row id, so assignments survive (tvnk.1 decision).
    2. Any set member missing by name is created (fresh installs get the full
       set; upgrades pick up new members) — EXCEPT tombstoned names (#487):
       a user deleting or renaming-away a starter records a tombstone, and
       absence-by-intent must not reseed. Existing rows are NEVER
       overwritten — except unedited prior-iteration rows, which are healed
       to current content in place (steps 1b/1c).

    Returns the number of templates created (step 2).
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
            # untouched (deep fingerprint, any generation), fold it back so
            # the legacy row (which holds the references) becomes the curated
            # one; otherwise leave both.
            if not _matches_any_generation(dup, curated_name, specs[curated_name]):
                continue
            delete_template(conn, dup.id)
            del existing[curated_name]
        spec = dict(specs[curated_name])
        update_template(conn, row.id, **spec)
        existing[curated_name] = existing.pop(legacy_name)

    # 1b. Rename unedited prior-iteration curated rows in place (same id).
    # The generation fingerprint covers prior titles and prior row content,
    # so a pre-tvnk.8 "International Event" (old title) renames AND upgrades.
    for prior, current in PRIOR_NAME_UPGRADES.items():
        row = existing.get(prior)
        if row is None or current in existing or current not in specs:
            continue
        if not _matches_any_generation(row, current, specs[current]):
            continue
        update_template(conn, row.id, **specs[current])
        existing[current] = existing.pop(prior)

    # 1c. Content-generation healing (#373, #355 item 14): a row still
    # exactly matching a registered PRIOR content generation — including
    # prior title variants — is provably our unedited seed and upgrades in
    # place (same id) to current content. Any user edit (title, subtitle,
    # descriptions, fillers, anything) makes the row match no generation and
    # it is left alone. This is how content changes (#363 marquee rows, #365
    # neutral rows/subtitles, #368 soccer idle) reach existing installs.
    for member, spec in specs.items():
        row = existing.get(member)
        if row is None or _content_matches(row, spec):
            continue
        if not _matches_any_generation(row, member, spec):
            continue
        update_template(conn, row.id, **spec)

    # 1d. Remove retired members that are still our unedited seed (deep
    # fingerprint, any generation — real installs carry the retired members
    # in OLD-generation content) — and are unreferenced: a retired starter
    # someone assigned stays put (deleting it would silently unassign their
    # channels).
    for retired_spec in [_retired_no_abbrev_spec(), *_retired_milb_specs()]:
        row = existing.get(retired_spec["name"])
        if row is None:
            continue
        if not _matches_any_generation(row, retired_spec["name"], retired_spec):
            continue
        if _is_referenced(conn, row.id):
            continue
        delete_template(conn, row.id)
        del existing[retired_spec["name"]]

    # 2. Add missing set members — absence-by-user-intent excluded (#487).
    tombstoned = get_seed_tombstones(conn)
    created = 0
    for name, spec in specs.items():
        if name in existing or name in tombstoned:
            continue
        create_template(conn, **spec)
        created += 1
    return created


# =============================================================================
# Seed tombstones (#487): deletes and renames of starter names must not
# resurrect on the next seed run. Recorded by the API layer on user-initiated
# actions only — the seeder's own internal deletes (duplicate healing,
# retired members) never tombstone.
# =============================================================================


def seed_names_affected_by(name: str) -> set[str]:
    """The CURRENT starter-set names that would reseed if ``name`` vanished.

    A deleted row named by a LEGACY or PRIOR-generation seed name causes the
    mapped CURRENT member to be recreated by step 2, so the tombstone must
    target the mapped name too.
    """
    specs = {spec["name"] for spec in DEFAULT_TEMPLATE_SET}
    targets = set()
    if name in specs:
        targets.add(name)
    mapped = LEGACY_UPGRADES.get(name) or PRIOR_NAME_UPGRADES.get(name)
    if mapped and mapped in specs:
        targets.add(mapped)
    return targets


def record_seed_tombstones(conn: Connection, names: set[str]) -> None:
    for n in names:
        conn.execute(
            "INSERT OR IGNORE INTO deleted_default_templates (name) VALUES (?)", (n,)
        )


def get_seed_tombstones(conn: Connection) -> set[str]:
    try:
        rows = conn.execute("SELECT name FROM deleted_default_templates").fetchall()
    except Exception:
        return set()  # pre-reconciliation startup order safety
    return {r[0] for r in rows}


def clear_seed_tombstones(conn: Connection) -> int:
    return conn.execute("DELETE FROM deleted_default_templates").rowcount
