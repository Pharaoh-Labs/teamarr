"""EPG program-data matching logic (epic teamarrv2-183.4).

Pure, dependency-light helpers that turn a Dispatcharr EPG program into an
input string for the EXISTING classify_stream -> TeamMatcher pipeline, and that
decide — from the program's categories — whether a program is worth matching.

Empirical basis (live Dispatcharr probe, 2026-06-01):
- Team names live in ``sub_title``, not ``title``. Titles are generic league
  names ("MLB Baseball", "NHL Hockey"); the matchup is in sub_title
  ("Chicago Cubs at St. Louis Cardinals"). So we match on title + sub_title.
- custom_properties.categories cleanly separate real games ("Sports event")
  from studio/talk ("Sports non-event") and replays ("Classic Sport Event").
  But categories are often absent in sloppy EPG, so they are a PRECISION signal,
  not a hard gate: when absent we fall back to the match itself (team extraction
  + event-window overlap is its own filter).
- "Classic Sport Event" co-occurs with "Sports event" on replays, so the
  classic/replay reject must take precedence over the event accept.

This module holds NO I/O and no StreamMatcher state — it is unit-testable in
isolation. Orchestration (index lookup, TeamMatcher invocation, reconciliation
with name matches, caching) lives in StreamMatcher.
"""

import re
from enum import Enum

from teamarr.dispatcharr.types import DispatcharrProgram

# Decoration characters some EPG feeds append to titles ("Mets at Mariners" +
# superscript "Live"/"New" markers, e.g. U+1D38 U+1DA6 U+1D5B U+1D49). These
# spacing-modifier / phonetic-superscript / super-subscript ranges are never
# part of a team name, so we drop them before team extraction.
_EPG_DECORATION = re.compile(
    "[ʰ-˿ᴬ-ᵪᶠ-ᶿ⁰-₟]+"
)

# Inline matchup separators used by feeds that put the whole matchup in the
# title with no sub_title ("MLB Baseball : Mets at Mariners", "… — …", "… – …").
# Converting the FIRST one to the pipe boundary lets classify_stream treat the
# leading league/category as a strippable hint, same as a real sub_title split.
_INLINE_SEP = re.compile(r"\s+[:–—]\s+")

# Category tokens (lowercased) that classify a program.
_CLASSIC = "classic sport event"
_NON_EVENT = "sports non-event"
_EVENT = "sports event"


class EPGMatchPolicy(Enum):
    """Whether a program should be run through the matcher, based on categories.

    ATTEMPT  — try to match (real game, or unknown/sloppy categories → rely on
               the team-match + window overlap as the filter).
    SKIP_NON_EVENT — studio/talk/highlights; never a game.
    SKIP_CLASSIC   — replay/classic re-air; must not match a current event.
    """

    ATTEMPT = "attempt"
    SKIP_NON_EVENT = "skip_non_event"
    SKIP_CLASSIC = "skip_classic"


def classify_program_policy(categories: tuple[str, ...]) -> EPGMatchPolicy:
    """Decide whether to attempt matching a program from its categories.

    Precedence: SKIP_CLASSIC > SKIP_NON_EVENT > ATTEMPT. Classic wins because
    replays carry both "Sports event" and "Classic Sport Event".

    Empty/unknown categories → ATTEMPT (fail safe via the match itself, never
    fail open — a non-game simply won't extract two real teams in-window).
    """
    if not categories:
        return EPGMatchPolicy.ATTEMPT
    lowered = {c.strip().lower() for c in categories}
    if _CLASSIC in lowered:
        return EPGMatchPolicy.SKIP_CLASSIC
    if _NON_EVENT in lowered:
        return EPGMatchPolicy.SKIP_NON_EVENT
    return EPGMatchPolicy.ATTEMPT


def build_match_input(program: DispatcharrProgram) -> str:
    """Build the string fed to classify_stream for an EPG program.

    Joins title + sub_title with a pipe ("MLB Baseball | Cubs at Cardinals"):
    real linear EPG puts the show/category in the title and the matchup in the
    sub_title. The pipe lets classify_stream treat the leading segment as a
    league/sport hint and strip it, so the matchup is extracted cleanly — a
    plain space would fold the title into the first team ("MLB Baseball Cubs at
    Cardinals" → team1="MLB Baseball Cubs"). A generic title with no sub_title
    (e.g. "NHL Hockey") yields no teams and self-rejects downstream — correct.

    EPG sources are heterogeneous, so both segments are first stripped of feed
    decorations (superscript "Live"/"New" markers). When there is no sub_title,
    a matchup carried inline in the title with a colon/dash separator ("MLB
    Baseball : Mets at Mariners") is split at that separator so the leading
    league/category still becomes a strippable hint — matching the canonical
    title|sub_title shape. Feeds that already split cleanly (no decorations, no
    inline separator) are unaffected.
    """
    title = _clean_epg_segment(program.title or "")
    sub_title = _clean_epg_segment(program.sub_title or "")
    if title and not sub_title:
        title = _INLINE_SEP.sub(" | ", title, count=1)
    parts = [p for p in (title, sub_title) if p]
    return " | ".join(parts)


def _clean_epg_segment(text: str) -> str:
    """Strip feed decoration chars and collapse whitespace in one EPG segment."""
    return re.sub(r"\s+", " ", _EPG_DECORATION.sub(" ", text)).strip()


def should_attempt(program: DispatcharrProgram) -> bool:
    """Convenience: True when the program is worth running through the matcher.

    Requires a non-empty match input AND a non-skip category policy.
    """
    if classify_program_policy(program.categories) is not EPGMatchPolicy.ATTEMPT:
        return False
    return bool(build_match_input(program))
