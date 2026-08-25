"""Team identity resolution over the global team cache (epic goax).

The matcher's oldest structural weakness is that it compares *strings*. It asks
"does this stream side look like the home team?" and "does that side look like
the away team?", accepts when the weaker leg clears a floor, and never asks the
question a human would ask first: **do these two teams actually play each
other?**

Because `token_set_ratio` weighs every token equally, a shared *city* — the
least informative half of a team name — is enough on its own:

    Tampa Bay Lightning / Tampa Bay Rays        = 78.3
    Detroit Red Wings   / Detroit Tigers        = 71.0
    Northern Colorado   / Colorado Rockies      = 66.7
    Eastern Washington  / Washington Nationals  = 73.7

all above BOTH_TEAMS_THRESHOLD (60), so an NHL stream lands on an MLB channel.
This is not a handful of bad pairs: among the six major North American pro
leagues alone there are 161 cross-league team pairs scoring >= 60, and
"New York Mets" / "New York Jets" reaches 92.3 — above even
HIGH_CONFIDENCE_THRESHOLD.

The fix is to resolve each side to the real *teams* that bear that name, using
`team_cache` (~10.8k teams across ~327 leagues and 14 sports, already populated
on every install). A side that resolves only to NHL teams cannot fill a slot in
an MLB fixture, whatever its string score.

Two properties of this index are load-bearing, both measured on real data:

1. **Ties are kept, never collapsed.** `SF Giants` and `NY Giants` produce the
   *same* four-way tie at 80.0 (San Francisco Giants, New York Giants, Keystone
   Giants, Wabash Little Giants). Collapsing to argmax would invent a wrong
   answer half the time. Keeping the tie is correct: the caller only needs the
   set of *leagues* those identities span, and both Giants resolve to leagues
   that include the one being matched.

2. **It vetoes, it never selects.** Resolution is a strong negative signal and a
   weak positive one — `D-backs` resolves to "ACL D-backs" (a rookie-league
   team), not Arizona. So the verdict below can say CONTRADICTED, and otherwise
   defers to the existing scoring ladder. Nothing here can create a match that
   scoring would not already have made; it can only withhold one.

Note what is deliberately *absent*: a schedule lookup. Verifying "is there a
game between these teams at this date/time" needs no new API call, because the
matcher is only ever handed real events drawn from real schedules — the
candidate event's own existence is that evidence. Identity is the only missing
half.
"""

from __future__ import annotations

import logging
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from functools import lru_cache
from sqlite3 import Connection

from rapidfuzz import fuzz, process

from teamarr.consumers.matching.constants import SHORT_CODE_MAX_LEN
from teamarr.database.team_cache import load_team_identities
from teamarr.utilities.constants import TEAM_ALIASES
from teamarr.utilities.fuzzy_match import normalize_text

logger = logging.getLogger(__name__)


# A name must reach this to be considered a plausible identity at all. Below it
# the string simply is not naming that team.
RESOLVE_FLOOR = 78.0

# Everything within this many points of the best hit is kept as a co-candidate.
# Sized from the measured `SF Giants` tie (four hits at exactly 80.0) and the
# measured `Tampa Bay Lightning` separation (100.0 NHL vs 78.3 the MLB Rays):
# wide enough to hold genuine ties, narrow enough that a clean winner excludes
# the same-city impostor.
RESOLVE_MARGIN = 8.0

# Fuzzy candidate pool pulled from rapidfuzz before margin filtering.
_EXTRACT_LIMIT = 25

# When a cached surface form is a strict token-subset of the query,
# token_set_ratio returns 100 for free — the bare short_name "Arizona" scores
# 100 against "arizona d backs" and drags in every Arizona Wildcats row across
# eight college leagues. Require the subset to account for most of the query
# before believing it, so "detroit tigers" still resolves "detroit tigers
# baseball" (61%) while "arizona" cannot claim "arizona d backs" (47%).
_SUBSET_COVERAGE_MIN = 0.55


@dataclass(frozen=True)
class TeamIdentity:
    """A real team, as the provider cache knows it."""

    name: str
    league: str
    sport: str


@dataclass(frozen=True)
class Fixture:
    """A pairing that could physically happen: two teams sharing a league."""

    league: str
    sport: str


@dataclass(frozen=True)
class Resolution:
    """Who a stream side might be, and how sure we are.

    `exact` means the text matched a cached surface form (or a known alias)
    outright rather than fuzzily. Only exact resolutions are trusted enough to
    support the disjoint-league rejection in `verdict`, because fuzzy
    resolution is a weak selector and a misread there would veto a real match.
    """

    identities: tuple[TeamIdentity, ...]
    exact: bool

    def __bool__(self) -> bool:
        return bool(self.identities)

    @property
    def leagues(self) -> set[str]:
        return {i.league for i in self.identities}


class FixtureVerdict:
    """Whether resolved identities can support a candidate event.

    SUPPORTED   - the event's league is a plausible reading of the stream.
    CONTRADICTED- the stream names real teams, and none of them play in this
                  event's league. The only verdict that rejects.
    UNKNOWN     - resolution was empty or one-sided; defer to fuzzy scoring.
    """

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


def _is_short_code(normalized: str) -> bool:
    """A single token this short is an abbreviation, not a name (#472)."""
    return len(normalized) <= SHORT_CODE_MAX_LEN and " " not in normalized


# Residual tokens that discriminate nothing. Club-form suffixes are the classic
# case ("Seattle Sounders FC" is the same club as "Seattle Sounders"), and
# one-or-two character leftovers are provider prefix/suffix noise — real stream
# names arrive as "us seattle sounders a" and "nfl seattle seahawks p". Treating
# either as a discriminator would refuse a team its own event.
_NON_DISCRIMINATING = frozenset(
    {"fc", "cf", "sc", "afc", "ac", "as", "ss", "cd", "sv", "fk", "bk", "if", "ff", "hc"}
)


def _discriminating(tokens: AbstractSet[str]) -> set[str]:
    """The tokens in ``tokens`` that can actually tell two teams apart.

    Takes ``AbstractSet`` rather than ``set``: its callers difference two
    memoized ``frozenset``s, so a ``set``-only annotation would reject the only
    inputs it ever receives.
    """
    return {t for t in tokens if len(t) > 2 and t not in _NON_DISCRIMINATING}


@lru_cache(maxsize=16384)
def _token_set(normalized: str) -> frozenset[str]:
    """Tokens of an already-normalized name, memoized.

    Both arguments of ``residual_contradicts`` are drawn from small pools — the
    stream's own sides and the candidate teams' names — but the function runs
    once per (stream x candidate event x side), so re-splitting the same handful
    of strings millions of times is pure waste.
    """
    return frozenset(normalized.split())


def residual_contradicts(stream_norm: str, team_norm: str) -> bool:
    """Do both sides carry meaningful residual tokens that disagree?

    Generalises the rule that already guards the short_name leg
    (`_short_name_leg_is_safe`, #569) to whole names. When two names overlap but
    each keeps words the other lacks, that residual IS the discriminator:
    "tampa bay LIGHTNING" vs "tampa bay RAYS" share only the city, and the words
    that tell them apart disagree. When one side is a pure subset of the other
    ("rays" / "tampa bay rays") there is no contradiction — that is an
    abbreviation, not a different team.

    Only *discriminating* residuals count. Noise and club suffixes must not
    convict: "us seattle sounders a" vs "Seattle Sounders FC" leaves {us, a}
    against {fc}, which says nothing about whether these are the same club.
    """
    s = _token_set(stream_norm)
    t = _token_set(team_norm)
    shared = s & t
    if not shared:
        return False
    s_residual = _discriminating(s - shared)
    t_residual = _discriminating(t - shared)
    if not s_residual or not t_residual:
        return False
    return not (s_residual & t_residual)


class TeamIdentityIndex:
    """Resolves stream-side text to the real teams bearing that name."""

    def __init__(self, rows: list[tuple[str, str | None, str | None, str, str]]) -> None:
        # One entry per (surface form -> identity). A team contributes its full
        # name and its short name, because streams use whichever the provider
        # liked ("D-backs" is ESPN's own short_name for Arizona, #480).
        self._identities: list[TeamIdentity] = []
        self._surfaces: list[str] = []
        self._by_abbrev: dict[str, list[TeamIdentity]] = {}
        self._exact: dict[str, list[TeamIdentity]] = {}

        for name, short_name, abbrev, league, sport in rows:
            identity = TeamIdentity(name=name, league=league, sport=sport)
            forms = {normalize_text(name)}
            if short_name:
                forms.add(normalize_text(short_name))
            for form in forms:
                if not form:
                    continue
                self._identities.append(identity)
                self._surfaces.append(form)
                self._exact.setdefault(form, []).append(identity)
            if abbrev:
                self._by_abbrev.setdefault(normalize_text(abbrev), []).append(identity)

        # Alias keys, normalized once so lookup and store agree. These carry the
        # forms providers never emit but streams love ("d-backs" -> Arizona,
        # #480); without them a real match resolves to nothing.
        self._alias_tokens: list[tuple[tuple[str, ...], str]] = []
        for key, value in TEAM_ALIASES.items():
            key_norm = normalize_text(key)
            if key_norm:
                self._alias_tokens.append((tuple(key_norm.split()), normalize_text(value)))

        self._cache: dict[str, Resolution] = {}

    @classmethod
    def from_db(cls, conn: Connection) -> TeamIdentityIndex:
        return cls(load_team_identities(conn))

    def __len__(self) -> int:
        return len(self._identities)

    def resolve(self, text: str | None) -> Resolution:
        """Every team this text plausibly names. Ties are kept (see module doc)."""
        if not text:
            return Resolution((), False)
        norm = normalize_text(text)
        if not norm:
            return Resolution((), False)
        if norm not in self._cache:
            self._cache[norm] = self._resolve_uncached(norm)
        return self._cache[norm]

    def _alias_variants(self, norm: str) -> list[str]:
        """Rewrites of `norm` with any embedded alias expanded to canonical.

        "arizona d backs" contains the alias "d backs", so it also reads as
        "arizona diamondbacks" — which IS a cached surface form. Duplicate
        tokens are collapsed so the substitution stays a clean name.
        """
        tokens = norm.split()
        variants: list[str] = []
        for key_tokens, canonical in self._alias_tokens:
            n = len(key_tokens)
            for i in range(len(tokens) - n + 1):
                if tuple(tokens[i : i + n]) == key_tokens:
                    replaced = tokens[:i] + canonical.split() + tokens[i + n :]
                    variants.append(" ".join(dict.fromkeys(replaced)))
        return variants

    def _resolve_uncached(self, norm: str) -> Resolution:
        # Exact surface form wins outright — no fuzzy pass can improve on it.
        if norm in self._exact:
            return Resolution(tuple(dict.fromkeys(self._exact[norm])), True)

        # Short codes match by abbreviation ONLY (#472). token_set_ratio gives a
        # spurious 100 whenever a code is a literal word of an unrelated name
        # ("SEA" in "Portland Sea Dogs").
        if _is_short_code(norm):
            hits = self._by_abbrev.get(norm, [])
            return Resolution(tuple(dict.fromkeys(hits)), bool(hits))

        # A known alias rewrite that lands on a real surface form is as good as
        # an exact hit — it is a curated statement about one specific team.
        for variant in self._alias_variants(norm):
            if variant in self._exact:
                return Resolution(tuple(dict.fromkeys(self._exact[variant])), True)

        hits = process.extract(
            norm,
            self._surfaces,
            scorer=fuzz.token_set_ratio,
            limit=_EXTRACT_LIMIT,
            score_cutoff=RESOLVE_FLOOR,
        )
        if not hits:
            return Resolution((), False)

        query_tokens = set(norm.split())
        best = hits[0][1]
        keep: list[TeamIdentity] = []
        for surface, score, idx in hits:
            if score < best - RESOLVE_MARGIN:
                break
            # A same-city impostor can sneak inside the margin when the true
            # team scores poorly; the residual rule still tells them apart.
            if residual_contradicts(norm, surface):
                continue
            # Free-100 subset guard (see _SUBSET_COVERAGE_MIN).
            surface_tokens = set(surface.split())
            if surface_tokens < query_tokens:
                coverage = len(surface) / len(norm) if norm else 0.0
                if coverage < _SUBSET_COVERAGE_MIN:
                    continue
            keep.append(self._identities[idx])
        return Resolution(tuple(dict.fromkeys(keep)), False)

    def candidate_fixtures(self, side_a: str | None, side_b: str | None) -> list[Fixture]:
        """Leagues in which BOTH sides name a real team — i.e. could be a game.

        A league where only one side exists is not a candidate: a fixture needs
        two teams. This is what stops "Northern Colorado vs Eastern Washington"
        from reading as an MLB game even though "Washington" alone resolves there.
        """
        a = self.resolve(side_a)
        b = self.resolve(side_b)
        if not a or not b:
            return []
        leagues_b = b.leagues
        fixtures = {
            Fixture(league=i.league, sport=i.sport) for i in a.identities if i.league in leagues_b
        }
        return sorted(fixtures, key=lambda f: f.league)

    def fixture_leagues(self, side_a: str | None, side_b: str | None) -> set[str] | None:
        """Leagues where these two sides could actually meet, or None if unknown.

        None means identity resolution has nothing to say and the caller should
        proceed unchanged. An empty set is a real answer, not a failure: both
        sides named real teams that share no league anywhere.
        """
        fixtures = self.candidate_fixtures(side_a, side_b)
        if fixtures:
            return {f.league for f in fixtures}

        # No shared league at all. When BOTH sides resolved exactly, that is
        # positive evidence of a non-fixture: "New York Mets vs New York Jets"
        # (which scores 92.3 as a pair of strings) names two real teams that
        # play in different sports and can never meet. Fuzzy resolutions are too
        # weak to carry this — a single misread would veto a legitimate match.
        a, b = self.resolve(side_a), self.resolve(side_b)
        if a and b and a.exact and b.exact:
            return set()
        return None

    def verdict(
        self, side_a: str | None, side_b: str | None, event_league: str
    ) -> tuple[str, list[Fixture]]:
        """Can `event_league` be a correct reading of these two stream sides?

        Veto-only by construction: SUPPORTED and UNKNOWN both mean "carry on and
        let scoring decide". Only CONTRADICTED rejects, and it requires positive
        evidence — the stream must name real teams, and this league must not be
        somewhere they could meet.
        """
        leagues = self.fixture_leagues(side_a, side_b)
        if leagues is None:
            return FixtureVerdict.UNKNOWN, []
        fixtures = self.candidate_fixtures(side_a, side_b)
        if event_league in leagues:
            return FixtureVerdict.SUPPORTED, fixtures
        return FixtureVerdict.CONTRADICTED, fixtures
