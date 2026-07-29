"""Shared normalization primitives for the matching pipelines (Phase 3b, item 13).

Two normalization pipelines maintain separate copies of overlapping
concepts:

- ``teamarr.consumers.matching.epg_resolver`` -- channel-identity
  normalization (``normalize_channel_name``), which needs a strict,
  unambiguous quality-token strip and a region-prefix allowlist.
- ``teamarr.consumers.matching.classifier`` -- team-text normalization
  (``_clean_team_name``), which needs a much more conservative quality-token
  strip since a false-positive strip on a team name is more damaging.

Full behavioral unification between the two is explicitly NOT the goal here
(the two jobs are different: strict channel-name equality vs. team-name
extraction). This module exists to be the SHARED SOURCE for the pieces that
really are the same concept in both places, so adding a token or region code
once makes it available everywhere it should apply.
"""

import re

# Quality / video-format tokens that decorate a channel name but don't change
# its identity ("ESPN FHD" and "ESPN" are the same channel). This is the
# superset used by channel-identity normalization (epg_resolver). Team-name
# extraction (classifier) uses the narrower TEAM_SAFE_QUALITY_TOKENS below.
QUALITY_TOKENS: frozenset[str] = frozenset(
    {
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
)

# Subset of QUALITY_TOKENS judged safe to strip from an extracted TEAM name
# (as opposed to a channel/EPG name). See the module-level judgment-call note
# below: "hq"/"lq" are deliberately excluded.
#
# Token-safety judgment call (for lead review): is it safe to strip ALL of
# QUALITY_TOKENS from a TEAM name? Channel names are provider metadata
# strings ("ESPN FHD", "US: TSN 1 HD") where these tokens are unambiguously
# video-quality decoration. Team names are extracted from free-form stream
# titles and are meant to end up as the actual displayed team/matchup name,
# so a false-positive strip is more damaging AND more plausible there.
#
# "hevc", "h265", and "h264" are codec names with no plausible legitimate
# overlap with a team, city, or venue name in English sports broadcasting --
# they're safe to strip in the team-name context.
#
# "hq" and "lq" are excluded. They are common two-letter tokens far more
# likely to accidentally collide with real name fragments at a word boundary
# (initials-style abbreviations, or a venue name like "... HQ" for a team
# headquarters/facility) than a channel-name provider would ever use them
# ambiguously. Given "hq"/"lq" are a much rarer/weaker signal for actual
# stream quality than hd/sd/fhd/4k/uhd/hevc/h26x in the first place, the
# safer default for team-name extraction is to leave them alone and accept
# that a rare literal "... HQ"/"... LQ" quality suffix survives in a team
# name, over the risk of mangling a legitimate name. This is a design
# decision made by the test author (not verified against any real-world
# "HQ"/"LQ" team name collision) -- flagged explicitly here for lead review.
TEAM_SAFE_QUALITY_TOKENS: frozenset[str] = QUALITY_TOKENS - {"hq", "lq"}

# Country / region grouping prefix codes (bead yke). Many providers prefix
# every stream with a country label and a delimiter -- "US: ESPN FHD", "UK |
# Sky Sports". This is the shared allowlist used to build the leading-prefix
# regex in epg_resolver. Includes both the original allowlist and Phase 3a's
# Asia-Pacific / Middle East additions.
REGION_CODES: frozenset[str] = frozenset(
    {
        "us",
        "usa",
        "uk",
        "ca",
        "au",
        "nz",
        "ie",
        "ire",
        "fr",
        "de",
        "es",
        "it",
        "nl",
        "pt",
        "be",
        "ch",
        "no",
        "se",
        "dk",
        "fi",
        "br",
        "mx",
        "ar",
        "in",
        "gr",
        "al",
        "tr",
        "bg",
        "cz",
        "pl",
        "ro",
        "hu",
        "hr",
        "rs",
        "eu",
        "intl",
        "latam",
        "exyu",  # matched as "ex-?yu" by callers (optional hyphen) -- see epg_resolver
        "jp",
        "kr",
        "cn",
        "za",
        "sa",
        "qa",
        "ae",
        "il",
        "pk",
        "ph",
        "th",
        "vn",
        "my",
        "sg",
        "id",
        "hk",
        "tw",
    }
)


def strip_quality_tokens(text: str, tokens: frozenset[str] | None = None) -> str:
    """Strip quality/format tokens from ``text`` on word boundaries.

    The token match is case-insensitive ("FHD", "Fhd", "fhd" are all
    stripped), so "shdtv" is left untouched -- "hd" is not a standalone word
    there. Whitespace left behind by a removed token is collapsed, and the
    result is lowercased.

    Args:
        text: Text to strip tokens from.
        tokens: Token set to strip. Defaults to QUALITY_TOKENS.

    Returns:
        The lowercased, whitespace-collapsed text with the tokens removed.
    """
    if tokens is None:
        tokens = QUALITY_TOKENS

    result = text
    if tokens:
        alternation = "|".join(re.escape(token) for token in sorted(tokens))
        result = re.sub(rf"\b(?:{alternation})\b", "", result, flags=re.IGNORECASE)

    result = re.sub(r"\s+", " ", result).strip().lower()
    return result
