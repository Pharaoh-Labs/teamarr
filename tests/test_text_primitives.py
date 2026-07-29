"""Tests for shared normalization primitives (Phase 3b, item 13).

Context: two normalization pipelines maintain separate copies of
overlapping concepts:

- ``teamarr.consumers.matching.epg_resolver`` -- channel-identity
  normalization (``normalize_channel_name``), hardcodes its own
  ``_QUALITY_TOKENS`` regex and ``_REGION_PREFIX`` allowlist.
- ``teamarr.consumers.matching.classifier`` -- team-text normalization
  (``_clean_team_name``), hardcodes its own quality-token strip (currently
  only ``HD|SD|FHD|4K|UHD``, at start/end of the string only).

Full behavioral unification is explicitly NOT wanted here (the two jobs are
different: strict channel-name equality vs. team-name extraction). What
this module (``teamarr.consumers.matching.text_primitives``, which does
NOT exist yet) is meant to provide is a SHARED SOURCE for the pieces that
really are the same concept in both places, so adding a token/region code
once makes it available everywhere it should be:

- ``QUALITY_TOKENS``: frozenset[str], lowercase. Must be a superset of the
  union of both pipelines' current token lists. Reading the source on this
  branch: epg_resolver's ``_QUALITY_TOKENS`` already covers
  ``{fhd, uhd, hd, sd, 4k, hevc, h265, h264, hq, lq}``, and classifier's
  ``_clean_team_name`` only knows ``{hd, sd, fhd, 4k, uhd}`` (a subset). So
  the union -- and therefore the minimum required content of
  ``QUALITY_TOKENS`` -- is exactly epg_resolver's current 10-token set.

- ``TEAM_SAFE_QUALITY_TOKENS``: frozenset[str], a SUBSET of
  ``QUALITY_TOKENS`` -- see "token-safety judgment call" below for why this
  exists and what it deliberately excludes.

- ``strip_quality_tokens(text, tokens=QUALITY_TOKENS) -> str``: removes the
  given tokens from ``text`` on word boundaries (so "shdtv" is untouched --
  "hd" is not a standalone word there), collapses whitespace, and
  lowercases the result. Case-insensitive on the token match itself (so
  "FHD", "Fhd", "fhd" are all stripped).

- ``REGION_CODES``: frozenset[str], lowercase. Must be a superset of the
  union of epg_resolver's ORIGINAL region-prefix allowlist and this
  branch's Phase 3a additions (see the current ``_REGION_PREFIX`` regex in
  ``epg_resolver.py``, which already includes both).

--------------------------------------------------------------------------
Token-safety judgment call (for lead review)
--------------------------------------------------------------------------
The spec asks: is it safe to strip ALL of ``QUALITY_TOKENS`` from a TEAM
name (as opposed to a channel/EPG name)? Channel names are provider
metadata strings ("ESPN FHD", "US: TSN 1 HD") where these tokens are
unambiguously video-quality decoration. Team names are extracted from
free-form stream titles and are meant to end up as the actual displayed
team/matchup name, so a false-positive strip is more damaging AND more
plausible there.

Judgment: ``hevc``, ``h265``, and ``h264`` are codec names with no
plausible legitimate overlap with a team, city, or venue name in English
sports broadcasting -- they're safe to strip in the team-name context, and
are added to ``TEAM_SAFE_QUALITY_TOKENS``.

``hq`` and ``lq`` are excluded from ``TEAM_SAFE_QUALITY_TOKENS`` and are
NOT stripped by ``_clean_team_name``. They are common two-letter tokens
that are far more likely to accidentally collide with real name fragments
at a word boundary (initials-style abbreviations, or as part of a venue
name like "... HQ" for a team headquarters/facility) than a channel-name
provider ever would use them ambiguously. Given "hq"/"lq" are a much
rarer/weaker signal for actual stream quality than hd/sd/fhd/4k/uhd/hevc/
h26x in the first place, the safer default for team-name extraction is to
leave them alone and accept that a rare literal "... HQ"/"... LQ" quality
suffix survives in a team name, over the risk of mangling a legitimate
name. ``QUALITY_TOKENS`` (the channel-identity superset) still includes
them, since ``normalize_channel_name`` genuinely needs them and channel
names don't carry this ambiguity risk.

This is a design decision made by the test author (not verified against
any real-world "HQ"/"LQ" team name collision) -- flagged explicitly here
for lead review before implementation locks it in.
"""

import pytest
from teamarr.consumers.matching.text_primitives import (
    QUALITY_TOKENS,
    REGION_CODES,
    TEAM_SAFE_QUALITY_TOKENS,
    strip_quality_tokens,
)

from teamarr.consumers.matching.classifier import _clean_team_name
from teamarr.consumers.matching.epg_resolver import normalize_channel_name

# ================================================================= QUALITY_TOKENS


def test_quality_tokens_is_superset_of_both_pipelines_current_lists():
    minimum_required = {
        "fhd",
        "uhd",
        "hd",
        "sd",
        "4k",
        "hevc",
        "h265",
        "h264",
        "hq",
        "lq",
    }
    assert minimum_required <= QUALITY_TOKENS


def test_quality_tokens_are_all_lowercase():
    assert all(token == token.lower() for token in QUALITY_TOKENS)


def test_team_safe_quality_tokens_is_subset_of_quality_tokens():
    assert TEAM_SAFE_QUALITY_TOKENS <= QUALITY_TOKENS


def test_team_safe_quality_tokens_excludes_hq_and_lq():
    """Judgment call (see module docstring): hq/lq are excluded from the
    team-name-safe subset as too collision-prone for team/venue names."""
    assert "hq" not in TEAM_SAFE_QUALITY_TOKENS
    assert "lq" not in TEAM_SAFE_QUALITY_TOKENS


def test_team_safe_quality_tokens_includes_codec_names():
    """hevc/h265/h264 have no plausible overlap with a team name and are
    judged safe to strip in the team-name context."""
    assert {"hevc", "h265", "h264"} <= TEAM_SAFE_QUALITY_TOKENS


# ============================================================= REGION_CODES


def test_region_codes_contains_original_codes():
    for code in ("us", "uk", "de"):
        assert code in REGION_CODES


def test_region_codes_contains_phase_3a_additions():
    for code in ("jp", "kr", "hk", "tw"):
        assert code in REGION_CODES


def test_region_codes_are_all_lowercase():
    assert all(code == code.lower() for code in REGION_CODES)


# ======================================================= strip_quality_tokens


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ESPN FHD", "espn"),
        ("4K Sports HD", "sports"),
        ("shdtv", "shdtv"),  # word-boundary: "hd" is not a standalone token here
        ("FHD UHD Sports HD", "sports"),  # multiple tokens, all stripped
        ("Willow 2", "willow 2"),  # already clean -- lowercased passthrough
    ],
)
def test_strip_quality_tokens_behavior_table(text, expected):
    assert strip_quality_tokens(text) == expected


def test_strip_quality_tokens_is_case_insensitive_on_the_token():
    assert strip_quality_tokens("ESPN fHd") == "espn"


def test_strip_quality_tokens_accepts_a_custom_token_set():
    # With a restricted token set, tokens outside it are left alone.
    assert strip_quality_tokens("HQ Lakers", tokens=frozenset({"hq"})) == "lakers"
    assert strip_quality_tokens("HEVC Lakers", tokens=frozenset({"hq"})) == "hevc lakers"


# ================================================ anti-drift: epg_resolver
#
# normalize_channel_name's quality-stripping must be driven by
# text_primitives.QUALITY_TOKENS (the shared source), not a private copy.
# Tested behaviorally: every token in the shared set must actually get
# stripped by normalize_channel_name. This is parametrized over the LIVE
# QUALITY_TOKENS set (not a hardcoded list), so if someone adds a new token
# to the shared set later without epg_resolver picking it up (because it
# was refactored to import from text_primitives), this test starts failing
# for that new token automatically.


@pytest.mark.parametrize("token", sorted(QUALITY_TOKENS))
def test_normalize_channel_name_strips_every_shared_quality_token(token):
    assert normalize_channel_name(f"Sample Channel {token.upper()}") == "sample channel"


# ================================================== anti-drift: classifier
#
# _clean_team_name's quality-stripping must be driven by
# text_primitives.TEAM_SAFE_QUALITY_TOKENS (the team-name-safe subset of
# the shared source), not classifier's own private, narrower copy. Today
# classifier only knows hd/sd/fhd/4k/uhd, so this fails for hevc/h265/h264
# until classifier is wired up to the shared subset.


@pytest.mark.parametrize("token", sorted(TEAM_SAFE_QUALITY_TOKENS))
def test_clean_team_name_strips_every_team_safe_quality_token_at_start(token):
    assert _clean_team_name(f"{token.upper()} Lakers") == "Lakers"


@pytest.mark.parametrize("token", sorted(TEAM_SAFE_QUALITY_TOKENS))
def test_clean_team_name_strips_every_team_safe_quality_token_at_end(token):
    assert _clean_team_name(f"Lakers {token.upper()}") == "Lakers"


@pytest.mark.parametrize("token", ["hq", "lq"])
def test_clean_team_name_leaves_unsafe_quality_tokens_untouched(token):
    """hq/lq are deliberately excluded from TEAM_SAFE_QUALITY_TOKENS (see
    module docstring) -- classifier must leave them in place rather than
    risk mangling a legitimate name fragment."""
    assert _clean_team_name(f"{token.upper()} Lakers") == f"{token.upper()} Lakers"
    assert _clean_team_name(f"Lakers {token.upper()}") == f"Lakers {token.upper()}"
