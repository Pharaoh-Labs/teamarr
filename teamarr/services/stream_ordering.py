"""Stream ordering service.

Computes stream priorities based on user-defined rules.
Rules are evaluated in priority order (lowest first); first match wins.
"""

import logging
import re
from dataclasses import dataclass
from sqlite3 import Connection

from teamarr.database.channels.types import ManagedChannelStream
from teamarr.database.settings import get_stream_ordering_settings
from teamarr.database.settings.types import StreamOrderingRule

logger = logging.getLogger(__name__)

# Default priority for streams that don't match any rule
NO_MATCH_PRIORITY = 999

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
    matched_rule_type: str | None = None  # Which rule type matched


@dataclass
class RuleEvaluation:
    """One ordering rule that matched a stream, for the priority explainer popup."""

    type: str
    value: str
    priority: int
    is_winner: bool  # True for the rule that actually set the priority


class StreamOrderingService:
    """Service for computing stream ordering based on rules.

    Rules are evaluated in priority order (lowest number first).
    First matching rule determines the stream's position.
    Non-matching streams get priority 999 (sorted to end).
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
        self._compiled_regex: dict[str, re.Pattern] = {}
        self._group_name_cache: dict[int, str] = {}
        # Keyed by rule.value string so different team selections cache separately
        self._team_feed_patterns: dict[str, re.Pattern | None] = {}
        # Keyed by sorted comma-joined keys for simple team-presence patterns
        self._team_presence_patterns: dict[str, re.Pattern | None] = {}

    def _find_matching_rule(
        self,
        stream: ManagedChannelStream,
        source_group_name: str | None,
    ) -> tuple[StreamOrderingRule | None, int]:
        """Return (matched_rule_or_None, catch_all_priority).

        Iterates rules in priority order, skipping catch_all (which sets the
        fallback rather than acting as a matcher).
        """
        catch_all_priority = NO_MATCH_PRIORITY
        for rule in self.rules:
            if rule.type == "catch_all":
                catch_all_priority = rule.priority
                continue
            if self._matches(stream, rule, source_group_name):
                return rule, catch_all_priority
        return None, catch_all_priority

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
        matched_rule, catch_all_priority = self._find_matching_rule(stream, source_group_name)
        return matched_rule.priority if matched_rule else catch_all_priority

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
            StreamWithPriority with computed priority and match info
        """
        matched_rule, catch_all_priority = self._find_matching_rule(stream, source_group_name)
        if matched_rule:
            return StreamWithPriority(
                stream=stream,
                computed_priority=matched_rule.priority,
                matched_rule_type=matched_rule.type,
            )
        return StreamWithPriority(
            stream=stream,
            computed_priority=catch_all_priority,
            matched_rule_type="catch_all" if catch_all_priority != NO_MATCH_PRIORITY else None,
        )

    def evaluate_rules(
        self,
        stream: ManagedChannelStream,
        source_group_name: str | None = None,
    ) -> list[RuleEvaluation]:
        """Return the rules that matched a stream, marking which one won.

        Mirrors compute_priority's first-match-wins / catch_all-fallback logic,
        but reports every matching rule (not just the winner) so the UI can
        explain why a stream got its priority. Rules are already priority-sorted.

        Args:
            stream: The stream to evaluate
            source_group_name: Optional pre-fetched group name (for 'group' rules)

        Returns:
            Matched rules in priority order, always followed by the "everything
            else" baseline (the configured catch_all rule, or the implicit
            no-match default). The rule that set the priority — first match, or
            the baseline when nothing matched — has is_winner=True.
        """
        matched: list[RuleEvaluation] = []
        catch_all: StreamOrderingRule | None = None
        winner_found = False

        for rule in self.rules:
            if rule.type == "catch_all":
                catch_all = rule
                continue
            if self._matches(stream, rule, source_group_name):
                is_winner = not winner_found
                winner_found = winner_found or is_winner
                matched.append(
                    RuleEvaluation(rule.type, rule.value, rule.priority, is_winner)
                )

        # Always surface the baseline so the popup shows what "everything else"
        # falls back to, even when a specific rule won.
        baseline_priority = catch_all.priority if catch_all else NO_MATCH_PRIORITY
        baseline_value = catch_all.value if catch_all else ""
        matched.append(
            RuleEvaluation("catch_all", baseline_value, baseline_priority, not winner_found)
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
        """Match stream name against the dynamic team-feed pattern."""
        if not stream.stream_name:
            return False
        pattern = self._get_team_feed_pattern(rule_value)
        if pattern is None:
            return False
        return bool(pattern.search(stream.stream_name))

    def _match_not_team_feed(self, stream: ManagedChannelStream, rule_value: str) -> bool:
        """Match streams that have feed indicators but are NOT this team's feed."""
        if not stream.stream_name:
            return False
        if not self._FEED_INDICATOR_RE.search(stream.stream_name):
            return False
        pattern = self._get_team_feed_pattern(rule_value)
        if pattern is None:
            return False
        return not bool(pattern.search(stream.stream_name))

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
