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
import re
from collections.abc import Iterable, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from functools import lru_cache
from sqlite3 import Connection

from rapidfuzz import fuzz, process

from teamarr.consumers.matching.constants import SHORT_CODE_MAX_LEN
from teamarr.database.team_cache import load_label_surfaces, load_team_identities
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
    # Video-quality words that survive into a stream side (#651). "HD"/"SD"/"4K"
    # are already too short to count; these are not, and "1080p" convicted
    # "wagner 1080p" against "wagner seahawks" — a second, independent kill
    # after the score itself.
    | {"uhd", "fhd"}
)
_RESOLUTION_RE = re.compile(r"\d{3,4}[pi]")


def _discriminating(tokens: AbstractSet[str]) -> set[str]:
    """The tokens in ``tokens`` that can actually tell two teams apart.

    Takes ``AbstractSet`` rather than ``set``: its callers difference two
    memoized ``frozenset``s, so a ``set``-only annotation would reject the only
    inputs it ever receives.
    """
    return {
        t
        for t in tokens
        if len(t) > 2 and t not in _NON_DISCRIMINATING and not _RESOLUTION_RE.fullmatch(t)
    }


# Extraction refinement (#799). A stream side is refined to the longest run of
# its tokens that is a known team surface, so provider junk around the name
# ("B1G Football - Howard", "Indiana (Big Ten Network)", "TOLEDO | 9.12 |
# ESPN+") never reaches the scorer or the stored parsed_team fields. Spans are
# capped at four tokens: no cached surface is longer, and the cap bounds the
# per-side lookups to 4 x len(tokens) dictionary hits.
MAX_SPAN_TOKENS = 4
# Lookup-only canonicalisation so "Washington St." finds the "washington state"
# surface. Applied to both the keys and the probe, never to what is returned:
# the refined side is always a verbatim slice of the original text, so the
# scorer still sees "Washington St" and keeps its own St/State tolerance.
_SPAN_CANON = {"st": "state"}


def _canon_span(tokens: Sequence[str]) -> tuple[str, ...]:
    return tuple(_SPAN_CANON.get(t, t) for t in tokens)


def _initialism(tokens: Sequence[str]) -> str:
    """First letter of each token, in order ("san francisco" -> "sf")."""
    return "".join(t[0] for t in tokens if t)


# Cap on TeamIdentityIndex.resolve's memo. Keyed by normalized stream-side text,
# so it grows with the variety of names a run sees, not with team_cache.
_RESOLVE_CACHE_MAX = 16384


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

    def __init__(
        self,
        rows: list[tuple[str, str | None, str | None, str, str]],
        labels: Iterable[str] = (),
    ) -> None:
        # One entry per (surface form -> identity). A team contributes its full
        # name and its short name, because streams use whichever the provider
        # liked ("D-backs" is ESPN's own short_name for Arizona, #480).
        self._identities: list[TeamIdentity] = []
        self._surfaces: list[str] = []
        self._by_abbrev: dict[str, list[TeamIdentity]] = {}
        # Only a FULL name is an identity (#619). A short_name is whatever the
        # provider chose to abbreviate to, and for college, MLS, NWSL and most
        # non-US rows that is the bare city or school: "Milwaukee" is the
        # short_name of the Milwaukee Panthers, "Atlanta" of Atlanta United,
        # "Kansas City" of Sporting KC. Every one of those is also a perfectly
        # ordinary broadcast label for the Brewers, the Braves and the Royals.
        # Reading it as an *exact* identity of the college/MLS side turned a
        # partial label into a veto against the team it partially named.
        self._exact: dict[str, list[TeamIdentity]] = {}
        # Partial readings: short names, and the city/school prefix of a full
        # name ("new york" from "New York Mets"). A side that only hits here is
        # evidence of which teams it *could* be, never proof of which it is not.
        self._partial: dict[str, list[TeamIdentity]] = {}
        self._known_leagues: set[str] = set()

        for name, short_name, abbrev, league, sport in rows:
            identity = TeamIdentity(name=name, league=league, sport=sport)
            self._known_leagues.add(league)
            name_norm = normalize_text(name)
            short_norm = normalize_text(short_name) if short_name else ""
            for form in {name_norm, short_norm}:
                if not form:
                    continue
                self._identities.append(identity)
                self._surfaces.append(form)
            if name_norm:
                self._exact.setdefault(name_norm, []).append(identity)
            if short_norm and short_norm != name_norm:
                self._partial.setdefault(short_norm, []).append(identity)
                # "Milwaukee Brewers" / "Brewers" -> "milwaukee". Only when the
                # short name is the tail of the full name, so a nickname that is
                # not a suffix ("D-backs") does not manufacture a bogus prefix.
                name_tokens = name_norm.split()
                short_tokens = short_norm.split()
                if len(short_tokens) < len(name_tokens) and (
                    name_tokens[-len(short_tokens) :] == short_tokens
                ):
                    prefix = " ".join(name_tokens[: -len(short_tokens)])
                    self._partial.setdefault(prefix, []).append(identity)
            # "Fairmont State Falcons" -> "fairmont state" (#650). A leading run
            # of a full name is a partial reading of it, and for college rows
            # the trailing run is the mascot while the leading run is exactly
            # what broadcasters write.
            #
            # The short-name prefix rule above cannot supply these keys: ESPN
            # abbreviates the SCHOOL for college ("Fairmont State Falcons" ->
            # "Fairmont St", "Eastern Washington Eagles" -> "E Washington"), so
            # the short name is never a suffix of the full name and the rule
            # never fires. That left the school-only form with no route to the
            # football team at all, while NCAA soccer -- where ESPN publishes no
            # mascots, so the full name IS the bare school -- held it as an
            # *exact* identity. One such side narrowed the fixture to
            # usa.ncaa.w.1 and vetoed college-football for 20 of 73 games.
            #
            # Every prefix, not just the mascot-dropped one, because mascots run
            # to two words as often as one ("Central Connecticut Blue Devils").
            # Stop at two tokens: a bare first word is the city/school reading,
            # which the short_name rule already owns, and registering it here
            # would enter every "north"/"saint" against thousands of teams.
            #
            # Safe by construction: partial readings only widen an identity set,
            # and the gate is veto-only, so this can withdraw a veto but never
            # manufacture a match.
            full_tokens = name_norm.split()
            for cut in range(len(full_tokens) - 1, 1, -1):
                prefix = " ".join(full_tokens[:cut])
                if prefix != short_norm:
                    self._partial.setdefault(prefix, []).append(identity)
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

        # Refinement support (#799): which codes each identity answers to, and
        # the span map, built lazily on first use from the surface tables above.
        self._abbrevs_of: dict[TeamIdentity, set[str]] = {}
        for code, identities in self._by_abbrev.items():
            for identity in identities:
                self._abbrevs_of.setdefault(identity, set()).add(code)
        self._span_map: dict[tuple[str, ...], tuple[TeamIdentity, ...]] | None = None
        # Competition, sport and conference labels ("EFL Championship",
        # "Soccer", "Big Ten"): the one kind of word-run that may sit flush
        # against a team name and still be junk. Loaded from the leagues,
        # sports and provider_group_cache tables — data the app already keeps,
        # never a list in code.
        self._labels: set[tuple[str, ...]] = set()
        for label in labels:
            tokens = normalize_text(label).split() if label else []
            if tokens:
                self._labels.add(_canon_span(tokens))

    @classmethod
    def from_db(cls, conn: Connection) -> TeamIdentityIndex:
        return cls(load_team_identities(conn), load_label_surfaces(conn))

    def __len__(self) -> int:
        return len(self._identities)

    def knows_league(self, league: str) -> bool:
        """Does the cache hold any team of this league at all?

        A veto is a statement about who plays in ``league``; the index can only
        make it for leagues it has actually seen. A custom league, a provider
        that failed to seed, or a league added since the last refresh must not
        be refused every stream just because its teams are absent (#619).
        """
        return league in self._known_leagues

    def resolve(self, text: str | None) -> Resolution:
        """Every team this text plausibly names. Ties are kept (see module doc)."""
        if not text:
            return Resolution((), False)
        norm = normalize_text(text)
        if not norm:
            return Resolution((), False)
        hit = self._cache.get(norm)
        if hit is None:
            # Bounded (#609): the index is now shared for the whole run rather
            # than rebuilt per event group, so this memo no longer gets a fresh
            # start every group. Clearing wholesale rather than evicting one
            # entry matches _TEAM_IDENTITY_MEMO in services/sports_data.py, and
            # a rebuilt entry is a few string ops.
            if len(self._cache) >= _RESOLVE_CACHE_MAX:
                self._cache.clear()
            hit = self._resolve_uncached(norm)
            self._cache[norm] = hit
        return hit

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

    # ------------------------------------------------------------------
    # Extraction refinement (#799)
    # ------------------------------------------------------------------

    def _spans(self) -> dict[tuple[str, ...], tuple[TeamIdentity, ...]]:
        """Every surface form as a canonical token tuple -> the teams it names.

        Full names, short names, the ≥2-token prefixes (#650) and the alias
        keys (#480) — the same tables `resolve` reads, so refinement can never
        find a "team" the identity gate does not also know.
        """
        if self._span_map is None:
            spans: dict[tuple[str, ...], list[TeamIdentity]] = {}
            for table in (self._exact, self._partial):
                for key, identities in table.items():
                    spans.setdefault(_canon_span(key.split()), []).extend(identities)
            for key_tokens, canonical in self._alias_tokens:
                identities = self._exact.get(canonical) or self._partial.get(canonical)
                if identities:
                    spans.setdefault(_canon_span(key_tokens), []).extend(identities)
            self._span_map = {
                key: tuple(dict.fromkeys(ids))
                for key, ids in spans.items()
                if len(key) <= MAX_SPAN_TOKENS
            }
        return self._span_map

    def _code_identities(self, raw_token: str, norm_token: str) -> tuple[TeamIdentity, ...]:
        """The teams a code-cased token names, or nothing for prose.

        A provider code is a surface only when the stream writes it as a code:
        "CCSU AT TOLEDO" carries CCSU, "US Open: Day #13" does not carry DAY.
        The #788 audit measured exactly this split (DAY: 1 upper / 217 lower),
        so case is the rule and the stopword list is frozen rather than grown.
        """
        if not (raw_token.isalpha() and raw_token.isupper() and 2 <= len(raw_token) <= 5):
            return ()
        return tuple(self._by_abbrev.get(norm_token, ()))

    def _claims_remainder(
        self,
        remainder: set[str],
        span_tokens: set[str],
        identities: tuple[TeamIdentity, ...],
    ) -> bool:
        """Could any team bearing the span own a token outside it?

        The guard that makes refinement a pure strip of junk: "SF Giants" keeps
        its "SF" because it is the initialism of what the Giants' own full name
        carries beyond "Giants"; "B1G Football - Howard" loses "B1G Football"
        because no team named Howard has any use for those words. A club suffix
        in the remainder ("Dallas FC") also keeps the side whole — that is a
        club-name variant for the alias/fuzzy path, not junk.
        """
        if not remainder:
            return False
        if remainder & _NON_DISCRIMINATING:
            return True
        for identity in identities:
            name_tokens = normalize_text(identity.name).split()
            allowed = set(name_tokens)
            allowed.add(_initialism(name_tokens))
            allowed.add(_initialism([t for t in name_tokens if t not in span_tokens]))
            allowed |= self._abbrevs_of.get(identity, set())
            if remainder & allowed:
                return True
        return False

    def refine_side(self, side: str, *, anchor: str) -> str | None:
        """The slice of ``side`` that names a team, or None to leave it alone.

        Finds the longest run of tokens that is a known surface (ties go to the
        run nearest ``anchor`` — "end" for the side before the separator,
        "start" for the side after it, since that is where the team sits) and
        returns that run verbatim from the original text, provided no team the
        run could name has a claim on any token outside it. None when the side
        is already a surface, contains none, or the remainder might matter — in
        every such case the existing fuzzy path scores the untouched side.
        """
        raw_tokens = side.split()
        if len(raw_tokens) < 2:
            return None
        norm: list[str] = []
        owner: list[int] = []
        for i, token in enumerate(raw_tokens):
            for piece in normalize_text(token).split():
                norm.append(piece)
                owner.append(i)
        total = len(norm)
        if total < 2:
            return None
        canon = _canon_span(norm)
        spans = self._spans()
        best: tuple[int, int, int, tuple[TeamIdentity, ...]] | None = None
        for n in range(min(MAX_SPAN_TOKENS, total), 0, -1):
            for i in range(total - n + 1):
                identities = spans.get(canon[i : i + n])
                if not identities and n == 1:
                    identities = self._code_identities(raw_tokens[owner[i]], norm[i])
                if not identities:
                    continue
                distance = total - (i + n) if anchor == "end" else i
                candidate = (n, -distance, i, identities)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
            if best is not None:
                break
        if best is None:
            return None
        n, _, start, identities = best
        if n == total:
            return None
        span_tokens = set(norm[start : start + n])
        remainder = (set(norm[:start]) | set(norm[start + n :])) - span_tokens
        if self._claims_remainder(remainder, span_tokens, identities):
            return None
        lo, hi = owner[start], owner[start + n - 1]
        if not self._bounded(raw_tokens[:lo][::-1]) or not self._bounded(raw_tokens[hi + 1 :]):
            return None
        return " ".join(raw_tokens[lo : hi + 1])

    def _bounded(self, outward: list[str]) -> bool:
        """Is the stripped text separated from the span by a real boundary?

        ``outward`` is the remainder on one side, nearest token first. A plain
        word flush against the span could be the rest of the name — "Oklahoma
        State", "Ohio Wesleyan", "Georgia Tech" — and when that team is not
        in the cache, nothing else can tell the extension from junk. So the
        run of bare words touching the span must be empty, or be a known
        competition/sport/conference label ("EFL Championship Derby",
        "Soccer Ohio State"); anything else stays whole for the fuzzy path,
        which already rejects "Ohio Wesleyan" against the Bobcats. A token
        with punctuation or a digit ("Football:", "(Big", "|", "13", "6pm")
        is the boundary providers actually write.
        """
        run: list[str] = []
        for token in outward:
            if token.isalpha():
                run.append(token)
            else:
                break
        if not run:
            return True
        words = [piece for token in run for piece in normalize_text(token).split()]
        return _canon_span(words) in self._labels or _canon_span(words[::-1]) in self._labels

    def _resolve_uncached(self, norm: str) -> Resolution:
        # Short codes read by abbreviation (#472) — token_set_ratio gives a
        # spurious 100 whenever a code is a literal word of an unrelated name
        # ("SEA" in "Portland Sea Dogs") — UNIONED with any team whose name or
        # short name is literally that code. TSDB and several ESPN soccer feeds
        # store the code AS the short name, and letting that one row pre-empt
        # the abbreviation table made "SEA" resolve to the Seattle Orcas alone
        # and never the Mariners, Seahawks or Kraken (#619). A code is never an
        # exact identity: "HOU" names sixteen teams in this cache.
        if _is_short_code(norm):
            hits = (
                self._by_abbrev.get(norm, [])
                + self._exact.get(norm, [])
                + self._partial.get(norm, [])
            )
            return Resolution(tuple(dict.fromkeys(hits)), False)

        # A full-name hit is exact. It still carries every partial reading of
        # the same text: the usa.ncaa row literally named "Utah" must not hide
        # the Jazz behind it — and, since #789, every abbreviation reading
        # too. A bare label that happens to be another team's FULL name
        # otherwise resolves narrowly and vetoes the club the stream meant:
        # "Roma" exact-hits the women's club ("Roma", uefa.wchampions) while
        # AS Roma's surfaces are all "AS Roma" (its short name included), so
        # no partial key "roma" exists and "Fenerbahce vs Roma" vetoed the
        # very real uefa.champions fixture. The provider's own code (ROMA)
        # is a curated statement about that club; carried as a never-exact
        # reading it only widens the identity set, per the module rules.
        if norm in self._exact:
            hits = self._exact[norm] + self._partial.get(norm, []) + self._by_abbrev.get(norm, [])
            return Resolution(tuple(dict.fromkeys(hits)), True)

        # A known alias rewrite that lands on a real surface form is as good as
        # an exact hit — it is a curated statement about one specific team —
        # UNLESS the text also reads as a partial label. TEAM_ALIASES was
        # written for the scoring ladder, where "atlanta" -> "atlanta united"
        # merely adds a candidate score; here it would swear that "Atlanta"
        # cannot be the Braves, the Hawks or the Falcons (#619). Keep the alias
        # reading, add the partial ones, and call it exact only when it is the
        # sole reading ("d backs" -> Arizona, #480).
        partial = self._partial.get(norm, [])
        for variant in self._alias_variants(norm):
            if variant in self._exact:
                hits = self._exact[variant] + partial
                return Resolution(tuple(dict.fromkeys(hits)), not partial)

        # Partial-only: a short name or a bare city. Strong evidence of the set
        # of teams it could be, no evidence about any it is not. Abbreviation
        # readings widen the same way (#789) — "lazio" carries SS Lazio's
        # leagues even when no surface form is that bare word.
        if partial:
            hits = partial + self._by_abbrev.get(norm, [])
            return Resolution(tuple(dict.fromkeys(hits)), False)

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
