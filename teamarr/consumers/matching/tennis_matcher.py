"""Tennis match matcher for tennis leagues (ATP, WTA).

Matches "player vs player" streams to per-match tennis Events (one Event per
match, players riding home_team/away_team — see espn/tennis.py).

Matching strategy (combat-style fuzzy names + exact date, no athlete cache):
- Streams reference players by SURNAME only, including multi-word surnames:
  "Wimbledon: Zheng vs Norrie", "Davidovich Fokina vs Cerundolo". The parsed
  team strings may carry tournament-name prefixes ("wimbledon zheng"), so a
  side matches when the player's surname tokens are a subset of the parsed
  side's tokens (exact) or by fuzzy full-name similarity (fallback).
- Both sides must clear the threshold on the SAME event (either orientation)
  — a one-sided surname hit must never match.
- A grand slam runs ~40+ matches/day, so ties are broken by proximity to the
  stream's extracted "@ 12:30 PM" time when present.

Tennis fixture gate (#283, same philosophy as the team fixture gate in
identity.py — veto-only, never a selector):
- Tournament: when the stream names a tournament that is in the candidate
  pool ("Wimbledon: Zheng vs Norrie"), candidates from OTHER tournaments are
  vetoed (FailedReason.TENNIS_TOURNAMENT_MISMATCH). A stream that names no
  pooled tournament defers — the pool passes unfiltered. Applies to both the
  player-pair path and the court/round feed path.
- Draw shape: a side naming one player never matches a doubles pair (rapidfuzz
  token_set_ratio scores "sinner" vs "Sinner/Sonego" 100, so the fuzzy
  fallback is exact-only for pairs), and a side written as a pair ("A/B")
  never matches a singles player. "_" is ambiguous (lazy singles naming) and
  defers.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz

from teamarr.consumers.matching.classifier import ClassifiedStream, StreamCategory
from teamarr.consumers.matching.result import (
    FailedReason,
    FilteredReason,
    MatchMethod,
    MatchOutcome,
)
from teamarr.consumers.stream_match_cache import StreamMatchCache, event_to_cache_data
from teamarr.core.types import Event, Team
from teamarr.services.sports_data import SportsDataService
from teamarr.utilities.fuzzy_match import normalize_text

logger = logging.getLogger(__name__)

# Minimum per-side score for a tennis player-name match (0-100). Both sides
# must clear it on the same event; surname-subset hits score 100.
TENNIS_MATCH_THRESHOLD = 75

# --- Court/round feed extraction (phase 2, bead mf7.7) -----------------------
# Streams name courts as "No 1 Court", "Court 18", "Centre Court", sometimes
# several at once ("Court 4 AND Court 12"). ESPN names them "No. 1 Court",
# "Court 18", "Centre Court", "Court 17 Roehampton" (qualifying). Both sides
# reduce to a canonical key: "centre", "show 1", or the bare number.

_COURT_PATTERNS = [
    (re.compile(r"\bcent(?:re|er)\s+court\b"), lambda m: "centre"),
    (re.compile(r"\bshow\s+court\s+(\d{1,2})\b"), lambda m: f"show {m.group(1)}"),
    (re.compile(r"\bno\s*(\d{1,2})\s+court\b"), lambda m: m.group(1)),
    (re.compile(r"\bcourt\s+no\s*(\d{1,2})\b"), lambda m: m.group(1)),
    (re.compile(r"\bcourt\s+(\d{1,2})\b"), lambda m: m.group(1)),
]

# Ordinal / keyword round labels → canonical ESPN round.displayName form
_ROUND_ORDINALS = {"first": "1", "second": "2", "third": "3", "fourth": "4"}

# Tokens too generic to identify a tournament ("Hall of Fame Open" must match
# on hall/fame, never on open/cup) — used by the feed tournament guard (#316).
_GENERIC_TOURNAMENT_TOKENS = frozenset(
    {
        "atp", "wta", "tour", "tennis", "open", "cup", "championship",
        "championships", "masters", "classic", "international", "invitational",
        "presented", "by", "the", "for", "of", "and", "at", "in", "de", "du",
    }
)

# Draw hints a feed stream can declare ("Ladies' Singles Semifinals").
# normalize_text strips apostrophes, so match the flattened token forms.
_DRAW_GENDER_HINTS = [
    (re.compile(r"\b(?:ladies|womens?)\b"), "women"),
    (re.compile(r"\b(?:gentlemens?|mens?)\b"), "men"),
]
_DRAW_TYPE_HINTS = [
    (re.compile(r"\bmixed\b"), "mixed"),
    (re.compile(r"\bsingles\b"), "singles"),
    (re.compile(r"\bdoubles\b"), "doubles"),
]


def _extract_draw_hints(text: str) -> tuple[str | None, str | None]:
    """(gender, type) a feed stream declares, e.g. ("women", "singles").

    "Mixed" implies doubles with no gender split, so it wins over a stray
    gender token and suppresses the gender hint.
    """
    draw_type = next((v for p, v in _DRAW_TYPE_HINTS if p.search(text)), None)
    if draw_type == "mixed":
        return None, "mixed"
    gender = next((v for p, v in _DRAW_GENDER_HINTS if p.search(text)), None)
    return gender, draw_type


def _draw_key(draw_type: str | None) -> tuple[str | None, str | None]:
    """Canonical (gender, type) for an ESPN grouping displayName.

    "Gentlemen's Singles" / "Men's Singles" → ("men", "singles");
    "Mixed Doubles" → (None, "mixed").
    """
    if not draw_type:
        return None, None
    return _extract_draw_hints(normalize_text(draw_type))


def _tournament_key(event: Event) -> str:
    """Identity the gate compares: the season-stable ESPN tournament id, else name."""
    return event.tournament_id or event.tournament_name or ""


def _named_tournaments(text: str, pool: list[Event]) -> set[str]:
    """Tournament keys the (normalized) stream text names, out of the pool.

    The hint set is derived from the candidate pool itself: a tournament is
    "named" when any of its distinctive name tokens (generic words like
    open/cup/masters excluded) appears in the stream text. No alias table —
    ESPN's own tournament names are the vocabulary.
    """
    text_tokens = set(text.split())
    named: set[str] = set()
    seen: set[str] = set()
    for event in pool:
        key = _tournament_key(event)
        tname = event.tournament_name or ""
        if not key or not tname or key in seen:
            continue
        seen.add(key)
        distinctive = (
            set(normalize_text(tname).split()) - _GENERIC_TOURNAMENT_TOKENS
        )
        if distinctive and distinctive & text_tokens:
            named.add(key)
    return named


def _tournament_guard(text: str, pool: list[Event]) -> tuple[list[Event], list[Event]]:
    """Split the pool into (kept, vetoed) by the tournaments the stream names.

    A court feed says "Wimbledon Day #8 No 1 Court" — without this, its
    court key also joins Court 1 at every OTHER tournament running that day
    (#316); a player-pair stream "Wimbledon: Zheng vs Norrie" likewise must
    not bind to a same-day Zheng match elsewhere (#283). Veto-only: when the
    stream names no pooled tournament, everything is kept.
    """
    named = _named_tournaments(text, pool)
    if not named:
        return pool, []
    kept = [e for e in pool if _tournament_key(e) in named]
    vetoed = [e for e in pool if _tournament_key(e) not in named]
    return kept, vetoed


def _surname_tokens(player: Team) -> set[str]:
    """Normalized surname tokens of a player (doubles pairs flattened)."""
    flat = normalize_text((player.abbreviation or "").replace("/", " ").replace("_", " "))
    return set(flat.split())


def _parsed_side_is_pair(raw_side: str | None) -> bool | None:
    """Does a raw parsed side name a doubles pair? True/False, None = can't tell.

    "/" and "&" are unambiguous pair joiners ("Nys/Roger-Vasselin", "Krejcikova
    & Siniakova"). "_" also joins pairs in some feeds but equally appears in
    lazy singles naming ("jannik_sinner"), so it defers.
    """
    if not raw_side:
        return None
    if "/" in raw_side or "&" in raw_side:
        return True
    if "_" in raw_side:
        return None
    return False


def _extract_courts(text: str) -> set[str]:
    """All canonical court keys mentioned in a (normalized) stream name.

    Patterns are ordered most-specific first; a later (less specific) match
    overlapping an earlier one is suppressed so "show court 1" doesn't also
    yield a bare "1" via the "court N" pattern.
    """
    courts: set[str] = set()
    claimed: list[tuple[int, int]] = []
    for pattern, keyfn in _COURT_PATTERNS:
        for m in pattern.finditer(text):
            span = m.span()
            if any(span[0] < end and start < span[1] for start, end in claimed):
                continue
            claimed.append(span)
            courts.add(keyfn(m))
    return courts


def _court_key(court: str) -> str | None:
    """Canonical key for an ESPN venue.court value (single court)."""
    keys = _extract_courts(normalize_text(court))
    return next(iter(keys)) if len(keys) == 1 else None


def _extract_round(text: str) -> str | None:
    """Canonical round label mentioned in a (normalized) stream name."""
    m = re.search(r"\b(first|second|third|fourth)\s+round\b", text)
    if m:
        return f"round {_ROUND_ORDINALS[m.group(1)]}"
    m = re.search(r"\bround\s+(\d{1,2})\b", text)
    if m:
        return f"round {m.group(1)}"
    if re.search(r"\bquarter\s*finals?\b", text):
        return "quarterfinals"
    if re.search(r"\bsemi\s*finals?\b", text):
        return "semifinals"
    # Bare "final" — but not Spanish/French round-of-N phrases ("octavos de
    # final", "cuartos de final", "huitièmes de finale"), which name EARLIER
    # rounds and must not read as the final.
    if re.search(r"(?<!\bde\s)(?<!\bof\s)\bfinals?\b", text):
        return "final"
    return None


def _round_key(round_name: str | None) -> str | None:
    """Canonical key for an ESPN round.displayName value."""
    if not round_name:
        return None
    return _extract_round(normalize_text(round_name))


@dataclass
class TennisMatchContext:
    """Context for tennis match matching."""

    stream_name: str
    stream_id: int
    group_id: int
    target_date: date
    generation: int
    user_tz: ZoneInfo
    classified: ClassifiedStream


class TennisMatcher:
    """Matches tennis streams (ATP, WTA) to per-match provider events."""

    def __init__(
        self,
        service: SportsDataService,
        cache: StreamMatchCache,
        majors_only: bool = False,
    ):
        self._service = service
        self._cache = cache
        # Only match grand-slam tournaments (#283): ESPN marks tournaments
        # major=true; with the flag on, smaller tournaments never enter the
        # candidate pool, so their channels are never created.
        self._majors_only = majors_only

    def match(
        self,
        classified: ClassifiedStream,
        league: str,
        target_date: date,
        group_id: int,
        stream_id: int,
        generation: int,
        user_tz: ZoneInfo,
    ) -> MatchOutcome:
        """Match a tennis stream to a provider match event."""
        if classified.category != StreamCategory.TENNIS_MATCH:
            return MatchOutcome.filtered(
                FilteredReason.NOT_EVENT,
                stream_name=classified.normalized.original,
                stream_id=stream_id,
                detail="Not a tennis stream",
            )

        # Court/round/day feeds have no player pair — they fan out via
        # match_feed() (routed in StreamMatcher._match_tennis_event); this
        # guard only catches a mis-routed call.
        if not classified.team1 or not classified.team2:
            return MatchOutcome.failed(
                FailedReason.NO_TENNIS_MATCH,
                stream_name=classified.normalized.original,
                stream_id=stream_id,
                detail="No player pair extracted (court/round feeds route via match_feed)",
            )

        match_date = classified.normalized.extracted_date or target_date

        ctx = TennisMatchContext(
            stream_name=classified.normalized.original,
            stream_id=stream_id,
            group_id=group_id,
            target_date=match_date,
            generation=generation,
            user_tz=user_tz,
            classified=classified,
        )

        cache_result = self._check_cache(ctx)
        if cache_result:
            logger.debug(
                "[CACHE HIT] tennis stream=%s matched=%s",
                ctx.stream_name[:50],
                cache_result.event.name if cache_result.event else "None",
            )
            return cache_result

        events = self._events_for_local_date(league, match_date, user_tz)
        result = self._match_to_event(ctx, events, league) if events else None

        # Widened-date fallback: providers frequently stamp streams with the
        # AIRING date (replays, +1-day delayed feeds), not the match date. A
        # player pair meets at most once per tournament (single elimination),
        # so searching a few days back is safe when the top hit is UNIQUE —
        # ambiguity (e.g. round-robin finals rematch) stays unmatched.
        if result is None or not result.is_matched:
            widened = self._events_for_date_window(league, match_date, user_tz)
            fallback = self._match_to_event(ctx, widened, league, require_unique=True)
            if fallback.is_matched:
                result = fallback

        if result is None:
            return MatchOutcome.failed(
                FailedReason.NO_TENNIS_MATCH,
                stream_name=ctx.stream_name,
                stream_id=stream_id,
                detail=f"No {league} matches for {match_date}",
            )

        if result.is_matched and result.event:
            self._cache_result(ctx, result)

        return result

    def match_feed(
        self,
        classified: ClassifiedStream,
        leagues: list[str],
        target_date: date,
        stream_id: int,
        user_tz: ZoneInfo,
        duration_hours: float = 3.0,
    ) -> list[MatchOutcome]:
        """Match a court/round day-feed to ALL its matches (phase 2, mf7.7).

        Court feeds ("Wimbledon Day #6 No 1 Court ft Rybakina Zverev") carry a
        court name that joins against ESPN's per-match venue.court; round
        feeds ("Wimbledon Second Round") join against round.displayName. One
        stream legitimately covers that court/round's whole slate for the
        day, so this fans out one outcome per match — each carrying the
        match's own time slot in epg_program_start/end so the lifecycle layer
        time-shares the stream across the match channels (same windowing the
        EPG-match path uses; buffers overlap-tolerant by design).

        A court hosts BOTH tours' draws (grand slams), so candidates pool
        across all configured tennis leagues. Feed fan-outs are not cached —
        the slate changes daily.
        """
        text = normalize_text(classified.event_hint or classified.normalized.original)
        stream_name = classified.normalized.original

        courts = _extract_courts(text)
        round_label = _extract_round(text)

        if not courts and not round_label:
            return [
                MatchOutcome.failed(
                    FailedReason.NO_TENNIS_MATCH,
                    stream_name=stream_name,
                    stream_id=stream_id,
                    detail="Ambient tennis feed (no court/round/player info to match)",
                )
            ]

        match_date = classified.normalized.extracted_date or target_date

        pool: list[Event] = []
        for league in leagues:
            pool.extend(self._events_for_local_date(league, match_date, user_tz))

        # Tournament guard (#316): "Wimbledon ... No 1 Court" must not join
        # Court 1 at other tournaments running the same day.
        pool, _vetoed = _tournament_guard(text, pool)

        # Draw guard (#316): a round feed that declares its draw ("Ladies'
        # Singles Semifinals") must not fan onto other groupings. Court feeds
        # skip it — the court is authoritative for its whole slate, and their
        # "ft Doubles Semifinals" suffixes are marketing, not scope.
        gender_hint, type_hint = (None, None) if courts else _extract_draw_hints(text)

        candidates = []
        for event in pool:
            if courts:
                event_court = _court_key(event.court) if event.court else None
                if event_court not in courts:
                    continue
            if round_label and _round_key(event.round_name) != round_label:
                continue
            if gender_hint or type_hint:
                event_gender, event_type = _draw_key(event.draw_type)
                if gender_hint and event_gender and event_gender != gender_hint:
                    continue
                if type_hint and event_type and event_type != type_hint:
                    continue
            candidates.append(event)

        if not candidates:
            what = f"courts {sorted(courts)}" if courts else f"round '{round_label}'"
            return [
                MatchOutcome.failed(
                    FailedReason.NO_TENNIS_MATCH,
                    stream_name=stream_name,
                    stream_id=stream_id,
                    detail=f"No tennis matches on {what} for {match_date}",
                )
            ]

        duration = timedelta(hours=duration_hours)
        outcomes = []
        for event in sorted(candidates, key=lambda e: e.start_time):
            outcome = MatchOutcome.matched(
                MatchMethod.DIRECT,
                event,
                detected_league=event.league,
                confidence=0.9,
                stream_name=stream_name,
                stream_id=stream_id,
            )
            outcome.epg_program_start = event.start_time
            outcome.epg_program_end = event.start_time + duration
            outcomes.append(outcome)

        logger.debug(
            "[MATCHED] tennis feed stream=%s -> %d matches (%s)",
            stream_name[:40],
            len(outcomes),
            f"courts={sorted(courts)}" if courts else f"round={round_label}",
        )
        return outcomes

    def match_program(
        self,
        classified: ClassifiedStream,
        program_text: str,
        leagues: list[str],
        program_start: datetime,
        program_end: datetime,
        stream_id: int,
        user_tz: ZoneInfo,
        duration_hours: float = 3.0,
    ) -> list[MatchOutcome]:
        """Match an EPG programme (mf7.9, #642) — tournament + (pair or court).

        Guide entries for tennis are tournament-level ("2026 US Open", "WTA
        1000 Toronto"); one programme covers many concurrent matches, so a
        programme may only bind when its fields (title, sub_title AND
        description — ``program_text`` is all of them) establish:

        1. a **tournament** in the day's pool (same token rule as the fixture
           gate), AND
        2. either a **player pair** (from the title/sub_title classification,
           or both surnames of one pooled match present in the text) or a
           **court** ("Centre Court", "Court 5").

        Pair → that one match. Court → the court's matches inside the
        programme's broadcast window. Anything less fails with
        ``TENNIS_MATCHUP_UNKNOWN`` — never a tournament-wide fan-out.
        """
        stream_name = classified.normalized.original
        text = normalize_text(program_text)
        prog_date = program_start.astimezone(user_tz).date()

        def unknown(detail: str) -> list[MatchOutcome]:
            return [
                MatchOutcome.failed(
                    FailedReason.TENNIS_MATCHUP_UNKNOWN,
                    stream_name=stream_name,
                    stream_id=stream_id,
                    detail=detail,
                )
            ]

        pool: list[Event] = []
        for league in leagues:
            pool.extend(self._events_for_local_date(league, prog_date, user_tz))
        if not pool:
            return unknown(f"No tennis matches on {prog_date}")

        named = _named_tournaments(text, pool)
        if not named:
            return unknown("Programme names no tournament playing that day")
        pool = [e for e in pool if _tournament_key(e) in named]

        duration = timedelta(hours=duration_hours)

        def in_window(event: Event) -> bool:
            return event.start_time < program_end and event.start_time + duration > program_start

        matched: list[Event] = []
        how = ""

        # 1. Player pair from the title/sub_title classification
        if classified.team1 and classified.team2:
            ctx = TennisMatchContext(
                stream_name=program_text,
                stream_id=stream_id,
                group_id=0,
                target_date=prog_date,
                generation=0,
                user_tz=user_tz,
                classified=classified,
            )
            outcome = self._match_to_event(ctx, pool, "tennis")
            if outcome.is_matched and outcome.event:
                matched, how = [outcome.event], "pair"

        # 2. Player pair anywhere in the text: both surnames of one pooled match
        if not matched:
            tokens = set(text.split())
            for event in pool:
                if all(
                    _surname_tokens(p) and _surname_tokens(p) <= tokens
                    for p in (event.home_team, event.away_team)
                ):
                    matched.append(event)
            if matched:
                how = "pair-in-text"

        # 3. Court
        if not matched:
            courts = _extract_courts(text)
            if courts:
                matched = [e for e in pool if e.court and _court_key(e.court) in courts]
                how = f"courts={sorted(courts)}"
                if not matched:
                    return unknown(f"No matches on {how} for the named tournament")

        if not matched:
            return unknown("Programme names a tournament but no player pair or court")

        windowed = [e for e in matched if in_window(e)]
        if not windowed:
            return unknown(f"Matchup found ({how}) but outside the programme window")

        outcomes = []
        for event in sorted(windowed, key=lambda e: e.start_time):
            outcome = MatchOutcome.matched(
                MatchMethod.DIRECT,
                event,
                detected_league=event.league,
                confidence=0.9,
                stream_name=stream_name,
                stream_id=stream_id,
            )
            outcomes.append(outcome)
        logger.debug(
            "[MATCHED] tennis programme '%s' -> %d match(es) via %s",
            program_text[:40],
            len(outcomes),
            how,
        )
        return outcomes

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _events_for_local_date(
        self, league: str, match_date: date, user_tz: ZoneInfo
    ) -> list[Event]:
        """Get tennis matches whose start falls on match_date in the user's tz.

        The provider slices matches by UTC date, so a late local-evening match
        (US tournaments) or an early local-morning match (users east of UTC)
        lands under the neighboring UTC date — fetch a ±1-day UTC window and
        re-slice in the user's timezone. Per-(league, date) results are cached
        by the service layer, so the extra fetches are cheap.
        """
        events: list[Event] = []
        for offset in (-1, 0, 1):
            events.extend(self._service.get_events(league, match_date + timedelta(days=offset)))
        events = self._apply_majors_filter(events)
        return [
            e for e in events if e.start_time.astimezone(user_tz).date() == match_date
        ]

    # How far back the widened-date fallback looks for replay/delayed streams
    _FALLBACK_LOOKBACK_DAYS = 4

    def _events_for_date_window(
        self, league: str, match_date: date, user_tz: ZoneInfo
    ) -> list[Event]:
        """Matches within [match_date - lookback, match_date + 1] (user tz)."""
        events: list[Event] = []
        for offset in range(-self._FALLBACK_LOOKBACK_DAYS - 1, 2):
            events.extend(self._service.get_events(league, match_date + timedelta(days=offset)))
        window_start = match_date - timedelta(days=self._FALLBACK_LOOKBACK_DAYS)
        window_end = match_date + timedelta(days=1)
        events = self._apply_majors_filter(events)
        return [
            e
            for e in events
            if window_start <= e.start_time.astimezone(user_tz).date() <= window_end
        ]

    def _apply_majors_filter(self, events: list[Event]) -> list[Event]:
        """Drop non-major tournaments when tennis_majors_only is set (#283)."""
        if not self._majors_only:
            return events
        return [e for e in events if e.is_major]

    def _check_cache(self, ctx: TennisMatchContext) -> MatchOutcome | None:
        """Check cache for existing match."""
        entry = self._cache.get(ctx.group_id, ctx.stream_id, ctx.stream_name)
        if not entry:
            return None

        self._cache.touch(ctx.group_id, ctx.stream_id, ctx.stream_name, ctx.generation)

        from teamarr.consumers.matching.team_matcher import TeamMatcher

        # Reuse reconstruction logic (same pattern as RacingMatcher)
        matcher = TeamMatcher(self._service, self._cache)
        event = matcher._reconstruct_event(entry.cached_data)

        if not event:
            self._cache.delete(ctx.group_id, ctx.stream_id, ctx.stream_name)
            return None

        # Cached event must still be on the stream's date
        if event.start_time.astimezone(ctx.user_tz).date() != ctx.target_date:
            return None

        # Majors-only gates cache hits too: entries cached before the toggle
        # was enabled would otherwise keep resurrecting non-major matches
        # until expiry (#541).
        if self._majors_only and not event.is_major:
            self._cache.delete(ctx.group_id, ctx.stream_id, ctx.stream_name)
            return None

        return MatchOutcome.matched(
            MatchMethod.CACHE,
            event,
            detected_league=entry.league,
            confidence=1.0,
            stream_name=ctx.stream_name,
            stream_id=ctx.stream_id,
            origin_match_method=entry.match_method,
        )

    def _match_to_event(
        self,
        ctx: TennisMatchContext,
        events: list[Event],
        league: str,
        require_unique: bool = False,
    ) -> MatchOutcome:
        """Match parsed player names to a tennis match event.

        require_unique (widened-date fallback): the top-scoring event must be
        the ONLY one at that score — without a trustworthy date, ambiguity
        (e.g. a round-robin rematch) must not match.
        """
        raw1, raw2 = ctx.classified.team1 or "", ctx.classified.team2 or ""
        team1, team2 = normalize_text(raw1), normalize_text(raw2)
        pair1, pair2 = _parsed_side_is_pair(raw1), _parsed_side_is_pair(raw2)

        stream_instant = self._stream_instant(ctx)

        # Tournament gate (#283): the stream's own text names the tournament
        # when it does; candidates from other tournaments are vetoed.
        candidates, vetoed = _tournament_guard(normalize_text(ctx.stream_name), events)

        def _score(event: Event) -> int:
            return self._pair_score(
                team1, team2, event.home_team, event.away_team, pair1, pair2
            )

        scored: list[tuple[int, Event]] = []
        for event in candidates:
            score = _score(event)
            if score >= TENNIS_MATCH_THRESHOLD:
                scored.append((score, event))

        if not scored:
            # Diagnose a gate veto: the players DID match, elsewhere.
            vetoed_hit = next((e for e in vetoed if _score(e) >= TENNIS_MATCH_THRESHOLD), None)
            if vetoed_hit is not None:
                logger.debug(
                    "[FAILED] tennis stream=%s: players match %s but stream names "
                    "a different tournament",
                    ctx.stream_name[:40],
                    vetoed_hit.name,
                )
                return MatchOutcome.failed(
                    FailedReason.TENNIS_TOURNAMENT_MISMATCH,
                    stream_name=ctx.stream_name,
                    stream_id=ctx.stream_id,
                    detail=f"Players match '{vetoed_hit.name}' but the stream names "
                    f"a different tournament",
                )
            logger.debug(
                "[FAILED] tennis stream=%s: no match in %d matches for %s",
                ctx.stream_name[:40],
                len(events),
                league,
            )
            return MatchOutcome.failed(
                FailedReason.NO_TENNIS_MATCH,
                stream_name=ctx.stream_name,
                stream_id=ctx.stream_id,
                detail=f"No {league} match found for players "
                f"'{ctx.classified.team1}' / '{ctx.classified.team2}'",
            )

        top_score = max(score for score, _ in scored)
        top_events = [e for score, e in scored if score == top_score]

        if require_unique and len(top_events) > 1:
            return MatchOutcome.failed(
                FailedReason.NO_TENNIS_MATCH,
                stream_name=ctx.stream_name,
                stream_id=ctx.stream_id,
                detail=f"Ambiguous: {len(top_events)} {league} matches share the "
                f"top player-name score in the widened date window",
            )

        # Tie-break by proximity to the stream's "@ 12:30 PM" time if present
        if len(top_events) > 1 and stream_instant is not None:
            top_events.sort(
                key=lambda e: abs((e.start_time - stream_instant).total_seconds())
            )

        score, event = top_score, top_events[0]
        method = MatchMethod.DIRECT if score == 100 else MatchMethod.FUZZY
        logger.debug(
            "[MATCHED] tennis stream=%s -> %s (method=%s, score=%d)",
            ctx.stream_name[:40],
            event.name,
            method.value,
            score,
        )
        return MatchOutcome.matched(
            method,
            event,
            detected_league=league,
            confidence=score / 100.0,
            stream_name=ctx.stream_name,
            stream_id=ctx.stream_id,
        )

    def _pair_score(
        self,
        team1: str,
        team2: str,
        home: Team,
        away: Team,
        pair1: bool | None = None,
        pair2: bool | None = None,
    ) -> int:
        """Score a parsed player pair against an event's two players.

        Returns the better orientation's min-side score, so BOTH sides must
        match the same event — 0..100. pair1/pair2: whether each parsed side
        is written as a doubles pair (None = unknown, see _parsed_side_is_pair).
        """
        straight = min(
            self._side_score(team1, home, pair1), self._side_score(team2, away, pair2)
        )
        swapped = min(
            self._side_score(team1, away, pair1), self._side_score(team2, home, pair2)
        )
        return max(straight, swapped)

    def _side_score(self, parsed: str, player: Team, parsed_pair: bool | None = None) -> int:
        """Score one parsed side against one player (0-100).

        Surname-token subset is an exact hit (parsed sides often carry
        tournament prefixes: "wimbledon zheng" ⊇ "zheng"); fuzzy full-name
        similarity is the fallback for spelling variants.

        Draw-shape gate (#283): a doubles pair (abbreviation "A/B") is matched
        exact-only — token_set_ratio("sinner", "Jannik Sinner/Lorenzo Sonego")
        is 100, which let singles streams bind to same-day doubles — and a
        side written as a pair never matches a singles player.
        """
        if not parsed:
            return 0
        player_is_pair = "/" in (player.abbreviation or "")
        if player_is_pair and parsed_pair is False:
            return 0
        if not player_is_pair and parsed_pair is True:
            return 0
        # Stream names join doubles pairs with "/", "_" or "&" and normalize_text
        # keeps "_" inside tokens ("roger_vasselin") — flatten all to spaces.
        parsed_flat = parsed.replace("_", " ").replace("/", " ").replace("&", " ")
        parsed_tokens = set(parsed_flat.split())

        # player.abbreviation carries the surname(s) — "de Minaur",
        # "Nys/Roger-Vasselin" for doubles pairs
        surname_flat = normalize_text(
            player.abbreviation.replace("/", " ").replace("_", " ")
        )
        surname_tokens = set(surname_flat.split())
        if surname_tokens and surname_tokens <= parsed_tokens:
            return 100
        if player_is_pair:
            return 0

        return int(fuzz.token_set_ratio(parsed_flat, normalize_text(player.name)))

    def _stream_instant(self, ctx: TennisMatchContext) -> datetime | None:
        """Stream's extracted date+time as an aware datetime, if time present."""
        extracted_time = ctx.classified.normalized.extracted_time
        if extracted_time is None:
            return None
        return datetime.combine(ctx.target_date, extracted_time, tzinfo=ctx.user_tz)

    def _cache_result(self, ctx: TennisMatchContext, result: MatchOutcome) -> None:
        """Cache a successful match."""
        if not result.event:
            return

        cached_data = event_to_cache_data(result.event)
        match_method_value = result.match_method.value if result.match_method else None

        self._cache.set(
            group_id=ctx.group_id,
            stream_id=ctx.stream_id,
            stream_name=ctx.stream_name,
            event_id=result.event.id,
            league=result.detected_league or result.event.league,
            cached_data=cached_data,
            generation=ctx.generation,
            match_method=match_method_value,
        )
