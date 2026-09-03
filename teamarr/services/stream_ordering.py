"""Stream ordering service.

Computes stream priorities from two classes of user-defined rule (epic
teamarr-5ag):

- Priority rules (``mode="priority"``): an ordered, first-match-wins list. The
  first one a stream matches sets its hard *band*. This is the legacy behaviour
  and the strict-precedence escape hatch.
- Score rules (``mode="score"``): additive. A stream sums the ``points`` of
  every score rule it matches; the total ranks streams within a band (signed —
  negatives demote below the baseline).

The two collapse into a single sortable priority int (lower = higher priority);
pure-priority rulesets keep their legacy small values unchanged.
"""

import logging
import re
from dataclasses import dataclass
from sqlite3 import Connection

from teamarr.database.channels.types import ManagedChannelStream
from teamarr.database.settings import get_stream_ordering_settings
from teamarr.database.settings.types import StreamOrderingRule

logger = logging.getLogger(__name__)

# Default priority for streams that don't match any rule (baseline band)
NO_MATCH_PRIORITY = 999

# Additive scoring (epic teamarr-5ag): when any score rule is present, a stream's
# hard band and its summed points are collapsed into one sortable int:
#     final = band * BAND_STRIDE - clamped_score      (lower sorts first)
# The stride keeps priority bands strictly separated no matter how points
# accumulate; the clamp guarantees no realistic score sum can bleed across a band
# boundary. Pure-priority rulesets (every legacy/migrated config, and all existing
# tests) skip this entirely and keep their original small 1-99/999 values, so
# migration is byte-identical, not merely order-preserving.
BAND_STRIDE = 1_000_000
_SCORE_CLAMP = BAND_STRIDE // 2 - 1

# Generic words that never disambiguate a team. Dropping them from the
# team-feed/presence term set avoids over-broad matches (e.g. a club literally
# named "The Strongest" must not turn into a rule that matches any stream
# containing the word "the"). Deliberately conservative — words like "city",
# "united", "real" are kept because they distinguish real clubs.
_TEAM_TERM_STOPWORDS = frozenset({"the", "and", "for", "with"})


@dataclass
class StreamWithPriority:
    """A stream with its computed priority."""

    stream: ManagedChannelStream
    computed_priority: int
    matched_rule_type: str | None = None  # Which rule type set the band (priority-mode winner)
    band: int = NO_MATCH_PRIORITY  # Hard band (priority-mode winner or baseline)
    score: int = 0  # Summed points from matched score-mode rules


@dataclass
class RuleEvaluation:
    """One ordering rule that matched a stream, for the priority explainer popup."""

    type: str
    value: str
    priority: int
    is_winner: bool  # True for the priority-mode rule that set the band (the band winner)
    mode: str = "priority"  # 'priority' (band) or 'score' (additive contributor)
    points: int = 0  # signed contribution for score-mode rules (0 for priority-mode)


class StreamOrderingService:
    """Service for computing stream ordering based on rules.

    A stream's priority is (hard band, additive score) collapsed into one int:
    the first-matching priority-mode rule (or the catch_all/NO_MATCH baseline)
    sets the band; matched score-mode rules sum their points to rank within it.
    Non-matching streams fall to the baseline band (priority 999) with score 0.
    """

    def __init__(
        self,
        rules: list[StreamOrderingRule],
        conn: Connection | None = None,
    ):
        """Initialize the service.

        Args:
            rules: List of ordering rules
            conn: Database connection (optional, needed for group name lookups)
        """
        self.rules = sorted(rules, key=lambda r: r.priority)
        self.conn = conn
        # Only widen the priority scale when scoring is actually in play; a
        # pure-priority ruleset keeps its legacy small values (see BAND_STRIDE).
        self._has_score_rules = any(
            r.mode == "score" and r.type != "catch_all" for r in self.rules
        )
        self._compiled_regex: dict[str, re.Pattern] = {}
        self._group_name_cache: dict[int, str] = {}
        # Keyed by rule.value string so different team selections cache separately
        self._team_feed_patterns: dict[str, re.Pattern | None] = {}
        # Rule value → (sport, provider team id) pairs it selects (#489, #687);
        # compared against a stream's persisted feed_team_id ahead of the name
        # regex, scoped by the stream's channel sport (see _feed_team_selected)
        self._team_feed_ids: dict[str, frozenset[tuple[str | None, str]] | None] = {}
        self._league_sports: dict[str, str | None] = {}
        self._channel_sports: dict[int, str | None] = {}
        # Keyed by sorted comma-joined keys for simple team-presence patterns
        self._team_presence_patterns: dict[str, re.Pattern | None] = {}

    def _resolve_band_and_score(
        self,
        stream: ManagedChannelStream,
        source_group_name: str | None,
    ) -> tuple[int, StreamOrderingRule | None, int]:
        """Resolve a stream's hard band and additive score in one pass.

        Returns (band, band_rule_or_None, total_score):

        - band: the first-matching priority-mode rule's ``priority``; else the
          catch_all baseline; else NO_MATCH_PRIORITY. This is the hard band.
        - band_rule: the priority-mode rule that set the band (None if the
          baseline applied — nothing matched, or only score rules matched).
        - total_score: sum of ``points`` over every matched score-mode rule.

        catch_all is always a baseline, never a band matcher or score contributor.
        Priority-mode rules resolve the band first-match-wins (rules are already
        priority-sorted); score-mode rules all contribute regardless of band.
        """
        catch_all_priority = NO_MATCH_PRIORITY
        band = NO_MATCH_PRIORITY
        band_rule: StreamOrderingRule | None = None
        total_score = 0

        for rule in self.rules:
            if rule.type == "catch_all":
                catch_all_priority = rule.priority
                continue
            if not self._matches(stream, rule, source_group_name):
                continue
            if rule.mode == "score":
                total_score += rule.points
            elif band_rule is None:
                # First matching priority-mode rule wins the band.
                band = rule.priority
                band_rule = rule

        if band_rule is None:
            band = catch_all_priority
        return band, band_rule, total_score

    def _collapse(self, band: int, total_score: int) -> int:
        """Collapse (band, score) into one sortable int (lower = higher priority).

        Pure-priority rulesets keep the legacy plain band value so existing
        configs are unchanged. When scoring is in play, higher score sorts a
        stream earlier within its band via ``band * BAND_STRIDE - score``.
        """
        if not self._has_score_rules:
            return band
        clamped = max(-_SCORE_CLAMP, min(_SCORE_CLAMP, total_score))
        return band * BAND_STRIDE - clamped

    def compute_priority(
        self,
        stream: ManagedChannelStream,
        source_group_name: str | None = None,
    ) -> int:
        """Compute the priority for a single stream.

        Args:
            stream: The stream to compute priority for
            source_group_name: Optional pre-fetched group name (optimization)

        Returns:
            Priority number (lower = higher priority)
        """
        band, _, total_score = self._resolve_band_and_score(stream, source_group_name)
        return self._collapse(band, total_score)

    def compute_priority_with_details(
        self,
        stream: ManagedChannelStream,
        source_group_name: str | None = None,
    ) -> StreamWithPriority:
        """Compute priority with details about which rule matched.

        Args:
            stream: The stream to compute priority for
            source_group_name: Optional pre-fetched group name

        Returns:
            StreamWithPriority with computed priority, band, and summed score
        """
        band, band_rule, total_score = self._resolve_band_and_score(stream, source_group_name)
        matched_type = band_rule.type if band_rule else None
        if matched_type is None and band != NO_MATCH_PRIORITY:
            # Band came from an explicit catch_all baseline rule.
            matched_type = "catch_all"
        return StreamWithPriority(
            stream=stream,
            computed_priority=self._collapse(band, total_score),
            matched_rule_type=matched_type,
            band=band,
            score=total_score,
        )

    def evaluate_rules(
        self,
        stream: ManagedChannelStream,
        source_group_name: str | None = None,
    ) -> list[RuleEvaluation]:
        """Return the rules that matched a stream, marking which set the band.

        Reports every matching rule (not just the band winner) so the UI can
        explain a stream's priority: the priority-mode rule that won the band
        (is_winner=True), each score-mode contributor (with its points), and the
        "everything else" baseline. Rules are already priority-sorted.

        Args:
            stream: The stream to evaluate
            source_group_name: Optional pre-fetched group name (for 'group' rules)

        Returns:
            Matched rules in priority order, always followed by the baseline
            (the configured catch_all rule, or the implicit no-match default).
            is_winner marks the priority-mode rule that set the band — or the
            baseline when no priority rule matched. Score rules never carry the
            winner flag; they contribute additively regardless of band.
        """
        matched: list[RuleEvaluation] = []
        catch_all: StreamOrderingRule | None = None
        band_won = False

        for rule in self.rules:
            if rule.type == "catch_all":
                catch_all = rule
                continue
            if not self._matches(stream, rule, source_group_name):
                continue
            if rule.mode == "score":
                matched.append(
                    RuleEvaluation(
                        rule.type, rule.value, rule.priority, False,
                        mode="score", points=rule.points,
                    )
                )
            else:
                is_winner = not band_won
                band_won = band_won or is_winner
                matched.append(
                    RuleEvaluation(
                        rule.type, rule.value, rule.priority, is_winner, mode="priority"
                    )
                )

        # Always surface the baseline so the popup shows what "everything else"
        # falls back to, even when a specific rule won the band.
        baseline_priority = catch_all.priority if catch_all else NO_MATCH_PRIORITY
        baseline_value = catch_all.value if catch_all else ""
        matched.append(
            RuleEvaluation(
                "catch_all", baseline_value, baseline_priority, not band_won, mode="priority"
            )
        )

        return matched

    def sort_streams(
        self,
        streams: list[ManagedChannelStream],
        source_group_names: dict[int, str] | None = None,
    ) -> list[ManagedChannelStream]:
        """Sort streams by computed priority.

        Args:
            streams: List of streams to sort
            source_group_names: Optional mapping of source_group_id -> group name

        Returns:
            Sorted list of streams (lowest priority first)
        """
        if not self.rules:
            # No rules - preserve existing order by added_at
            return sorted(streams, key=lambda s: (s.priority, s.added_at or 0))

        def sort_key(stream: ManagedChannelStream):
            group_name = None
            if source_group_names and stream.source_group_id:
                group_name = source_group_names.get(stream.source_group_id)
            priority = self.compute_priority(stream, group_name)
            # Secondary sort by added_at for stable ordering within same priority
            return (priority, stream.added_at or 0)

        return sorted(streams, key=sort_key)

    def _matches(
        self,
        stream: ManagedChannelStream,
        rule: StreamOrderingRule,
        source_group_name: str | None = None,
    ) -> bool:
        """Check if a stream matches a rule.

        Args:
            stream: The stream to check
            rule: The rule to match against
            source_group_name: Optional pre-fetched group name

        Returns:
            True if the stream matches the rule
        """
        if rule.type == "m3u":
            return self._match_m3u(stream, rule.value)
        elif rule.type == "group":
            return self._match_group(stream, rule.value, source_group_name)
        elif rule.type == "regex":
            return self._match_regex(stream, rule.value)
        elif rule.type == "stream_type":
            return self._match_stream_type(stream, rule.value)
        elif rule.type == "team_feed":
            return self._match_team_feed(stream, rule.value)
        elif rule.type == "not_team_feed":
            return self._match_not_team_feed(stream, rule.value)
        elif rule.type == "home_feed":
            return self._match_feed_side(stream, "home")
        elif rule.type == "away_feed":
            return self._match_feed_side(stream, "away")
        elif rule.type == "epg_match":
            return self._match_epg_match(stream)
        elif rule.type == "dispatcharr_group":
            return self._match_dispatcharr_group(stream, rule.value)
        elif rule.type == "stats_metric":
            return self._match_stats_metric(stream, rule.value)
        return False

    def _match_m3u(self, stream: ManagedChannelStream, account_name: str) -> bool:
        """Match stream by M3U account name (case-insensitive)."""
        if not stream.m3u_account_name:
            return False
        return stream.m3u_account_name.lower() == account_name.lower()

    def _match_group(
        self,
        stream: ManagedChannelStream,
        group_name: str,
        source_group_name: str | None = None,
    ) -> bool:
        """Match stream by source group name (case-insensitive).

        Args:
            stream: The stream to check
            group_name: The group name to match
            source_group_name: Pre-fetched group name (if available)
        """
        actual_name = source_group_name
        if actual_name is None and stream.source_group_id:
            actual_name = self._get_group_name(stream.source_group_id)
        if not actual_name:
            return False
        return actual_name.lower() == group_name.lower()

    def _match_regex(self, stream: ManagedChannelStream, pattern: str) -> bool:
        """Match stream name by regex pattern (case-insensitive)."""
        if not stream.stream_name:
            return False

        compiled = self._get_compiled_regex(pattern)
        if compiled is None:
            return False

        return bool(compiled.search(stream.stream_name))

    # Detects streams that explicitly name a feed perspective (home/away/cam/feed keyword).
    # Used by not_team_feed to avoid matching generic streams with no feed markers.
    _FEED_INDICATOR_RE = re.compile(
        r"(?i)\b(?:home|away)\b|\bcam\s*0?[12]\b|\bfeed\b"
    )

    def _match_team_feed(self, stream: ManagedChannelStream, rule_value: str) -> bool:
        """Match a stream against the rule's team selection (#489).

        The persisted feed_team_id (matching layer's resolution: broadcast
        markets, tvg-id, team-branded names like 'Brewers.TV', TEAM_ONLY
        matched side) is authoritative when present — it covers streams the
        name regex can't see. Rows without one (NULL) fall back to the name
        regex, so pre-column rows and unresolved streams keep working.
        """
        if stream.feed_team_id:
            team_ids = self._get_team_feed_ids(rule_value)
            return team_ids is not None and self._feed_team_selected(stream, team_ids)
        if not stream.stream_name:
            return False
        pattern = self._get_team_feed_pattern(rule_value)
        if pattern is None:
            return False
        return bool(pattern.search(stream.stream_name))

    def _match_not_team_feed(self, stream: ManagedChannelStream, rule_value: str) -> bool:
        """Match streams that are team feeds but NOT this team's feed.

        A persisted feed_team_id means the stream IS a team feed — match when
        it belongs to a different team than the rule selects. NULL falls back
        to the regex path, which requires an explicit feed indicator first.
        """
        if stream.feed_team_id:
            team_ids = self._get_team_feed_ids(rule_value)
            return team_ids is not None and not self._feed_team_selected(stream, team_ids)
        if not stream.stream_name:
            return False
        if not self._FEED_INDICATOR_RE.search(stream.stream_name):
            return False
        pattern = self._get_team_feed_pattern(rule_value)
        if pattern is None:
            return False
        return not bool(pattern.search(stream.stream_name))

    @staticmethod
    def _match_feed_side(stream: ManagedChannelStream, side: str) -> bool:
        """Match streams whose persisted feed side is exactly `side` (#533).

        Tri-state, deliberately strict: feed_side is 'home', 'away', or NULL
        meaning UNKNOWN. An unknown stream matches NEITHER home_feed nor
        away_feed and falls through to the catch-all band — it is never
        treated as the opposite side just because it isn't this one.

        No name-regex fallback, unlike team_feed. The stream-name feed marker
        is already consumed upstream (classifier.detect_and_strip_feed_hint →
        resolve_feed_side) and persisted here, so re-deriving it at ranking
        time would be a second, weaker copy of a decision already made with
        the event in scope.
        """
        return stream.feed_side == side

    def _match_epg_match(self, stream: ManagedChannelStream) -> bool:
        """Match streams attached via EPG program-data matching (epic 183).

        EPG-matched (time-shared linear) streams carry match_method='epg'; name
        matches carry other methods (fuzzy/cache/…) or None. No value needed.
        """
        return stream.match_method == "epg"

    def _match_dispatcharr_group(self, stream: ManagedChannelStream, group_name: str) -> bool:
        """Match a channel-source stream by its Dispatcharr channel group (ybt.3).

        Only channel-source streams carry dispatcharr_channel_group (the DP
        channel's own group); all others have None and never match. Case-insensitive.
        """
        if not stream.dispatcharr_channel_group:
            return False
        return stream.dispatcharr_channel_group.lower() == group_name.lower()

    _STATS_OPERATORS = {
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        "=": lambda a, b: a == b,
    }

    def _resolve_stat_value(self, stats: dict, metric: str) -> float | None:
        """Resolve a metric name to a float, including virtual derived fields.

        resolution_width / resolution_height extract from the "1920x1080" string
        that Dispatcharr stores in the 'resolution' key.
        """
        if metric == "resolution_width":
            res = str(stats.get("resolution") or "")
            if "x" in res:
                try:
                    return float(res.split("x")[0])
                except (ValueError, IndexError):
                    return None
            return None
        if metric == "resolution_height":
            res = str(stats.get("resolution") or "")
            if "x" in res:
                try:
                    return float(res.split("x")[1])
                except (ValueError, IndexError):
                    return None
            return None
        raw = stats.get(metric)
        if raw is None:
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    def _match_stats_metric(self, stream: ManagedChannelStream, rule_value: str) -> bool:
        """Match stream by numeric stat comparisons encoded in rule_value.

        Supports multiple AND conditions separated by ";":
          "ffmpeg_output_bitrate|>=|4000;source_fps|>=|50"

        Each condition is "metric|operator|threshold". Actual field names match
        Dispatcharr's stream_stats JSON: resolution, source_fps,
        ffmpeg_output_bitrate, audio_bitrate, sample_rate. Virtual metrics
        resolution_width / resolution_height are derived from the resolution string.
        """
        if not rule_value:
            return False
        try:
            for cond in rule_value.split(";"):
                parts = cond.split("|", 2)
                if len(parts) < 2:
                    return False
                metric, operator = parts[0], parts[1]
                threshold_str = parts[2] if len(parts) > 2 else ""

                if operator == "is_unknown":
                    # Matches when stats are absent entirely OR this metric has no value
                    has_value = (
                        stream.stream_stats is not None
                        and self._resolve_stat_value(stream.stream_stats, metric) is not None
                    )
                    if has_value:
                        return False
                else:
                    if not stream.stream_stats:
                        return False
                    val = self._resolve_stat_value(stream.stream_stats, metric)
                    if val is None:
                        return False
                    compare = self._STATS_OPERATORS.get(operator)
                    if compare is None:
                        return False
                    if not compare(val, float(threshold_str)):
                        return False
            return True
        except (ValueError, TypeError, AttributeError):
            return False

    def _match_stream_type(self, stream: ManagedChannelStream, rule_value: str) -> bool:
        """Match stream by type, with optional team filter (value may be 'team|key1,key2')."""
        # The UI offers event / team / EPG as one mutually-exclusive Stream Type
        # select (EPG stores as rule type epg_match). EPG-matched streams also
        # carry match_type event/team, so without this gate an event/team rule
        # listed above the EPG rule captures them first (#448).
        if stream.match_method == "epg":
            return False
        if "|" not in rule_value:
            return stream.match_type == rule_value
        stream_type, team_keys_str = rule_value.split("|", 1)
        if stream.match_type != stream_type:
            return False
        if not team_keys_str:
            return True
        keys = [k.strip() for k in team_keys_str.split(",") if k.strip()]
        if not keys:
            return True
        pattern = self._get_team_presence_pattern(keys)
        if pattern is None:
            return False
        return bool(pattern.search(stream.stream_name or ""))

    def _build_team_terms(self, rows: list) -> set[str]:
        """Extract word/city/abbrev terms from team_cache rows for regex building.

        Terms shorter than 3 chars (2 for abbreviations) and generic stopwords
        are dropped so the resulting pattern stays specific to the team — a club
        named "FC Bayern" yields {Bayern, FC-abbrev} but never the bare "FC", and
        "The Strongest" never contributes the word "the".
        """
        terms: set[str] = set()
        for row in rows:
            name = row["team_name"] or ""
            abbrev = row["team_abbrev"] or ""
            words = name.split()
            for word in words:
                if len(word) >= 3 and word.lower() not in _TEAM_TERM_STOPWORDS:
                    terms.add(re.escape(word))
            city = " ".join(words[:-1]) if len(words) > 1 else ""
            if len(city) >= 3 and city.lower() not in _TEAM_TERM_STOPWORDS:
                terms.add(re.escape(city))
            if len(abbrev) >= 2:
                terms.add(re.escape(abbrev))
        return terms

    def _get_team_presence_pattern(self, keys: list[str]) -> re.Pattern | None:
        """Build and cache a simple word-boundary presence pattern from team keys.

        Unlike _get_team_feed_pattern, this has no home/away/feed directionality —
        it just checks whether the stream name contains any of the team's terms.
        """
        cache_key = ",".join(sorted(keys))
        if cache_key in self._team_presence_patterns:
            return self._team_presence_patterns[cache_key]

        if not self.conn:
            self._team_presence_patterns[cache_key] = None
            return None

        try:
            rows = self._query_team_cache_by_keys(keys)
        except Exception as e:
            logger.warning(
                "[STREAM_ORDER] Failed to query teams for stream_type presence pattern: %s", e
            )
            self._team_presence_patterns[cache_key] = None
            return None

        terms = self._build_team_terms(rows)
        if not terms:
            logger.warning(
                "[STREAM_ORDER] stream_type team filter: no matching teams for keys %r, "
                "filter will block all",
                keys,
            )
            self._team_presence_patterns[cache_key] = None
            return None

        team_alt = "|".join(sorted(terms, key=len, reverse=True))
        pattern: re.Pattern | None = None
        try:
            pattern = re.compile(r"(?i)\b(?:" + team_alt + r")\b")
        except re.error as e:
            logger.warning("[STREAM_ORDER] Failed to compile stream_type presence pattern: %s", e)

        self._team_presence_patterns[cache_key] = pattern
        return pattern

    def _query_team_cache_by_keys(self, keys: list[str]) -> list:
        """Query team_cache for provider-keyed team entries.

        Accepts both formats (mixed lists are fine):
          - 2-part legacy: "provider:provider_team_id"
          - 3-part new:    "provider:league:provider_team_id"
        """
        two_part = [k for k in keys if k.count(":") == 1]
        three_part = [k for k in keys if k.count(":") == 2]
        rows: list = []

        if two_part:
            placeholders = ",".join("?" * len(two_part))
            rows += self.conn.execute(  # type: ignore[union-attr]
                f"SELECT DISTINCT team_name, team_abbrev FROM team_cache"
                f" WHERE provider || ':' || provider_team_id IN ({placeholders})",
                two_part,
            ).fetchall()

        if three_part:
            parts = [k.split(":") for k in three_part]
            conditions = " OR ".join(
                "(provider = ? AND league = ? AND provider_team_id = ?)" for _ in parts
            )
            params = [p for part in parts for p in part]
            rows += self.conn.execute(  # type: ignore[union-attr]
                f"SELECT DISTINCT team_name, team_abbrev FROM team_cache WHERE {conditions}",
                params,
            ).fetchall()

        return rows

    def _league_sport(self, league: str) -> str | None:
        """Sport of a league code, from the leagues table (cached)."""
        key = league.lower()
        if key not in self._league_sports:
            sport = None
            if self.conn:
                try:
                    row = self.conn.execute(
                        "SELECT sport FROM leagues WHERE league_code = ?", (key,)
                    ).fetchone()
                    sport = row[0] if row and row[0] else None
                except Exception as e:
                    logger.debug("[STREAM_ORDER] league sport lookup failed for %s: %s", key, e)
            self._league_sports[key] = sport
        return self._league_sports[key]

    def _stream_sport(self, stream: ManagedChannelStream) -> str | None:
        """Sport of the channel a stream belongs to (cached per channel).

        None when unknown — no connection, or a transient stream that is not
        on a channel yet (attach-time scoring; the end-of-generation reorder
        pass re-scores real rows).
        """
        channel_id = stream.managed_channel_id
        if not channel_id or not self.conn:
            return None
        if channel_id not in self._channel_sports:
            sport = None
            try:
                row = self.conn.execute(
                    "SELECT sport FROM managed_channels WHERE id = ?", (channel_id,)
                ).fetchone()
                sport = row[0] if row and row[0] else None
            except Exception as e:
                logger.debug("[STREAM_ORDER] channel sport lookup failed for %s: %s", channel_id, e)
            self._channel_sports[channel_id] = sport
        return self._channel_sports[channel_id]

    def _feed_team_selected(
        self, stream: ManagedChannelStream, keys: frozenset[tuple[str | None, str]]
    ) -> bool:
        """Does the stream's persisted feed team fall inside the rule's selection?

        Provider team ids are only unique within a SPORT (#687): ESPN's Cubs
        are mlb:16 and its Vikings nfl:16, so a bare-id compare let a Vikings
        selection tag every Cubs feed. Within a sport the id IS stable across
        competitions (Liverpool is 364 in the Premier League and the Champions
        League), so the scope is the sport, never the league — a team picked
        from one competition must keep matching its feeds in another.

        A key without a sport (legacy 2-part 'provider:id') or a stream whose
        channel sport is unknown falls back to the bare-id compare.
        """
        feed_id = stream.feed_team_id
        stream_sport = self._stream_sport(stream)
        for key_sport, key_id in keys:
            if key_id != feed_id:
                continue
            if key_sport is None or stream_sport is None or key_sport == stream_sport:
                return True
        return False

    def _get_team_feed_ids(self, rule_value: str) -> frozenset[tuple[str | None, str]] | None:
        """Resolve a team_feed rule value to the (sport, provider team id) pairs it
        selects (#489, #687).

        Compared against a stream's persisted feed_team_id (the provider team
        id, same namespace as managed_channels.feed_team_id) scoped by sport —
        see _feed_team_selected. 3-part keys ('espn:mlb:158') resolve their
        league to a sport; legacy 2-part keys ('espn:158') carry no league and
        get sport None (bare-id compare); the legacy integer format holds
        teams-table row ids and needs a lookup. Returns None when nothing
        resolves (rule matches no resolved stream). Cached per rule_value.
        """
        if rule_value in self._team_feed_ids:
            return self._team_feed_ids[rule_value]

        keys: set[tuple[str | None, str]] = set()
        if rule_value:
            if ":" in rule_value:
                for key in rule_value.split(","):
                    parts = [p.strip() for p in key.strip().split(":")]
                    if len(parts) >= 3:
                        # provider:league:id — the league names the sport
                        keys.add((self._league_sport(parts[1]), parts[-1]))
                    elif len(parts) == 2:
                        # legacy provider:id — no league, no sport scope
                        keys.add((None, parts[-1]))
            elif self.conn:
                row_ids = [int(x) for x in rule_value.split(",") if x.strip().isdigit()]
                if row_ids:
                    placeholders = ",".join("?" * len(row_ids))
                    try:
                        rows = self.conn.execute(
                            f"SELECT provider_team_id, sport FROM teams"
                            f" WHERE id IN ({placeholders}) AND active = 1",
                            row_ids,
                        ).fetchall()
                        keys.update(
                            ((r[1] or None), str(r[0])) for r in rows if r[0] is not None
                        )
                    except Exception as e:
                        logger.warning(
                            "[STREAM_ORDER] Failed to resolve team ids for team_feed rule: %s",
                            e,
                        )

        result = frozenset(keys) if keys else None
        self._team_feed_ids[rule_value] = result
        return result

    def _get_team_feed_pattern(self, rule_value: str) -> re.Pattern | None:
        """Build and cache the team-feed regex.

        rule_value formats:
          - ""                           → no-op; rule matches nothing
          - "1,5,12"                     → legacy: integer team IDs (teams table)
          - "espn:28,mlbstats:xyz"       → legacy 2-part: provider:provider_team_id (team_cache)
          - "espn:mlb:28,espn:nfl:5"     → new 3-part: provider:league:provider_team_id (team_cache)
        Results are cached per rule_value string.
        """
        if rule_value in self._team_feed_patterns:
            return self._team_feed_patterns[rule_value]

        if not rule_value:
            self._team_feed_patterns[rule_value] = None
            return None

        if not self.conn:
            logger.warning("[STREAM_ORDER] team_feed rule requires a DB connection")
            self._team_feed_patterns[rule_value] = None
            return None

        try:
            if ":" in rule_value:
                # New format: "provider:provider_team_id" pairs → query team_cache
                keys = [k.strip() for k in rule_value.split(",") if ":" in k.strip()]
                if not keys:
                    self._team_feed_patterns[rule_value] = None
                    return None
                rows = self._query_team_cache_by_keys(keys)
            else:
                # Legacy format: integer team IDs → query teams table
                ids = [int(x) for x in rule_value.split(",") if x.strip().isdigit()]
                if not ids:
                    self._team_feed_patterns[rule_value] = None
                    return None
                placeholders = ",".join("?" * len(ids))
                rows = self.conn.execute(
                    f"SELECT team_name, team_abbrev FROM teams"
                    f" WHERE id IN ({placeholders}) AND active = 1",
                    ids,
                ).fetchall()
        except Exception as e:
            logger.warning("[STREAM_ORDER] Failed to query teams for team_feed rule: %s", e)
            self._team_feed_patterns[rule_value] = None
            return None

        terms = self._build_team_terms(rows)

        if not terms:
            logger.warning(
                "[STREAM_ORDER] team_feed rule (value=%r): no matching teams, rule will not match",
                rule_value,
            )
            self._team_feed_patterns[rule_value] = None
            return None

        # Longest terms first so the engine prefers more-specific matches
        team_alt = "|".join(sorted(terms, key=len, reverse=True))
        pattern_str = (
            r"(?i)(?=.*\b(?P<team>" + team_alt + r")\b)"
            r"(?:.*(?:vs|at|@).*(?P=team).*(?:home|\(home\)|cam\s*0?1)"
            r"|.*(?P=team).*(?:vs|at|@).*(?:away|cam\s*0?2)"
            r"|.*\((?P=team)\s+feed\b.*"
            r"|.*home\s*feed.*:\s*\S+\s+(?:vs|at|@)\s+(?P=team)\b"
            r"|.*away\s*feed.*:\s*(?P=team)\s+(?:vs|at|@)\s+\S+)"
        )
        pattern: re.Pattern | None = None
        try:
            pattern = re.compile(pattern_str)
            logger.debug(
                "[STREAM_ORDER] Built team_feed pattern (value=%r) from %d teams (%d terms)",
                rule_value,
                len(rows),
                len(terms),
            )
        except re.error as e:
            logger.warning("[STREAM_ORDER] Failed to compile team_feed pattern: %s", e)

        self._team_feed_patterns[rule_value] = pattern
        return pattern

    def _get_compiled_regex(self, pattern: str) -> re.Pattern | None:
        """Get or compile a regex pattern (with caching)."""
        if pattern not in self._compiled_regex:
            try:
                self._compiled_regex[pattern] = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                logger.warning("[STREAM_ORDER] Invalid regex pattern '%s': %s", pattern, e)
                self._compiled_regex[pattern] = None  # type: ignore
        return self._compiled_regex.get(pattern)

    def _get_group_name(self, group_id: int) -> str | None:
        """Look up group name from database (with caching)."""
        if group_id in self._group_name_cache:
            return self._group_name_cache[group_id]

        if not self.conn:
            return None

        try:
            cursor = self.conn.execute(
                "SELECT name FROM event_epg_groups WHERE id = ?",
                (group_id,),
            )
            row = cursor.fetchone()
            if row:
                self._group_name_cache[group_id] = row["name"]
                return row["name"]
        except Exception as e:
            logger.warning("[STREAM_ORDER] Failed to look up group %d: %s", group_id, e)

        self._group_name_cache[group_id] = None  # type: ignore
        return None


def get_stream_ordering_service(conn: Connection) -> StreamOrderingService:
    """Factory function to create a StreamOrderingService with rules from database.

    Args:
        conn: Database connection

    Returns:
        Configured StreamOrderingService
    """

    settings = get_stream_ordering_settings(conn)
    return StreamOrderingService(rules=settings.rules, conn=conn)
