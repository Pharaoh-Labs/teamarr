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
    ):
        self._service = service
        self._cache = cache

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

        candidates = []
        for event in pool:
            if courts:
                event_court = _court_key(event.court) if event.court else None
                if event_court not in courts:
                    continue
            if round_label and _round_key(event.round_name) != round_label:
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
        return [
            e
            for e in events
            if window_start <= e.start_time.astimezone(user_tz).date() <= window_end
        ]

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
        team1 = normalize_text(ctx.classified.team1 or "")
        team2 = normalize_text(ctx.classified.team2 or "")

        stream_instant = self._stream_instant(ctx)

        scored: list[tuple[int, Event]] = []
        for event in events:
            score = self._pair_score(team1, team2, event.home_team, event.away_team)
            if score >= TENNIS_MATCH_THRESHOLD:
                scored.append((score, event))

        if not scored:
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

    def _pair_score(self, team1: str, team2: str, home: Team, away: Team) -> int:
        """Score a parsed player pair against an event's two players.

        Returns the better orientation's min-side score, so BOTH sides must
        match the same event — 0..100.
        """
        straight = min(self._side_score(team1, home), self._side_score(team2, away))
        swapped = min(self._side_score(team1, away), self._side_score(team2, home))
        return max(straight, swapped)

    def _side_score(self, parsed: str, player: Team) -> int:
        """Score one parsed side against one player (0-100).

        Surname-token subset is an exact hit (parsed sides often carry
        tournament prefixes: "wimbledon zheng" ⊇ "zheng"); fuzzy full-name
        similarity is the fallback for spelling variants.
        """
        if not parsed:
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
