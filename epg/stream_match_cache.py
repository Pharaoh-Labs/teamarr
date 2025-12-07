"""
Stream Match Cache - Fingerprint-based caching for EPG generation optimization.

Caches successful stream-to-event matches to avoid expensive tier matching on
every EPG generation. Only successful matches (with event_id) are cached.

Fingerprint = group_id + stream_id + stream_name

On cache hit, we skip tier matching entirely and just refresh dynamic fields
(scores, status, odds) from ESPN's event summary endpoint.

DYNAMIC FIELDS (must refresh each EPG run):
- status (scheduled/in-progress/final)
- home_team.score, away_team.score
- odds (spread, moneyline, over_under)
- home_team.streak, away_team.streak (changes after games)

STATIC FIELDS (cached, never change for an event):
- Everything else: teams, venue, broadcast, logos, records at game start, etc.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Dict, Optional, Any, Tuple, TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from api.espn_client import ESPNClient

logger = logging.getLogger(__name__)

# =============================================================================
# DYNAMIC EVENT FIELDS - Update this when adding new template variables!
# =============================================================================
# These fields are refreshed from ESPN API on every EPG run.
# Everything else in the cached event dict stays cached (static).
#
# If you add a new template variable that depends on data that changes
# during or after a game, add its source field here.
# =============================================================================

DYNAMIC_EVENT_FIELDS = {
    # Game state - changes during game
    'status',           # scheduled/in-progress/final, period, clock
    'competitions',     # Contains live status, scores, situation

    # Scores - change during game
    'home_team.score',
    'away_team.score',

    # Betting lines - shift constantly before game
    'odds',
    'has_odds',

    # Streaks - change after each game
    'home_team.streak',
    'away_team.streak',
}


def compute_fingerprint(group_id: int, stream_id: int, stream_name: str) -> str:
    """
    Compute a hash fingerprint for cache lookup.

    Args:
        group_id: Event group ID
        stream_id: Dispatcharr stream ID
        stream_name: Exact stream name

    Returns:
        16-character hex hash (SHA256 truncated)
    """
    key = f"{group_id}:{stream_id}:{stream_name}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class StreamMatchCache:
    """
    Manages stream fingerprint cache for EPG generation optimization.

    Usage:
        cache = StreamMatchCache(get_connection)

        # Check cache before tier matching
        cached = cache.get(group_id, m3u_account_id, stream_id, stream_name)
        if cached:
            event_id, league, cached_data = cached
            # Refresh dynamic fields and continue
        else:
            # Do full tier matching
            ...
            # Cache successful match
            cache.set(group_id, m3u_account_id, stream_id, stream_name,
                     event_id, league, cached_data, generation)
    """

    # Number of generations to keep unseen fingerprints before purging
    PURGE_AFTER_GENERATIONS = 5

    def __init__(self, get_connection_func):
        """
        Initialize cache with database connection factory.

        Args:
            get_connection_func: Function that returns a database connection
        """
        self.get_connection = get_connection_func
        self._stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'purged': 0,
        }

    def get(
        self,
        group_id: int,
        stream_id: int,
        stream_name: str
    ) -> Optional[Tuple[str, str, Dict]]:
        """
        Look up cached match for a stream fingerprint.

        Args:
            group_id: Event group ID
            stream_id: Dispatcharr stream ID
            stream_name: Exact stream name

        Returns:
            Tuple of (event_id, league, cached_event_data) if found, None otherwise
        """
        fingerprint = compute_fingerprint(group_id, stream_id, stream_name)

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT event_id, league, cached_event_data
                FROM stream_match_cache
                WHERE fingerprint = ?
            """, (fingerprint,))

            row = cursor.fetchone()
            if row:
                self._stats['hits'] += 1
                event_id = row['event_id']
                league = row['league']
                cached_data = json.loads(row['cached_event_data'])
                logger.debug(f"[CACHE HIT] stream_id={stream_id} -> event_id={event_id}")
                return (event_id, league, cached_data)

            self._stats['misses'] += 1
            return None

        finally:
            conn.close()

    def set(
        self,
        group_id: int,
        stream_id: int,
        stream_name: str,
        event_id: str,
        league: str,
        cached_data: Dict,
        generation: int
    ) -> bool:
        """
        Cache a successful stream-to-event match.

        Args:
            group_id: Event group ID
            stream_id: Dispatcharr stream ID
            stream_name: Exact stream name
            event_id: ESPN event ID
            league: Detected league code
            cached_data: Dict with 'event' and 'team_result' for template vars
            generation: Current EPG generation counter

        Returns:
            True if cached successfully
        """
        fingerprint = compute_fingerprint(group_id, stream_id, stream_name)

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO stream_match_cache
                    (fingerprint, group_id, stream_id, stream_name,
                     event_id, league, cached_event_data, last_seen_generation,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (fingerprint)
                DO UPDATE SET
                    event_id = excluded.event_id,
                    league = excluded.league,
                    cached_event_data = excluded.cached_event_data,
                    last_seen_generation = excluded.last_seen_generation,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                fingerprint, group_id, stream_id, stream_name,
                event_id, league, json.dumps(cached_data), generation
            ))
            conn.commit()
            self._stats['sets'] += 1
            logger.debug(f"[CACHE SET] stream_id={stream_id} -> event_id={event_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cache stream match: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def touch(
        self,
        group_id: int,
        stream_id: int,
        stream_name: str,
        generation: int
    ) -> bool:
        """
        Update last_seen_generation for an existing cache entry.
        Called when we use a cached match to keep it fresh.

        Args:
            group_id: Event group ID
            stream_id: Dispatcharr stream ID
            stream_name: Exact stream name
            generation: Current EPG generation counter

        Returns:
            True if updated
        """
        fingerprint = compute_fingerprint(group_id, stream_id, stream_name)

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE stream_match_cache
                SET last_seen_generation = ?, updated_at = CURRENT_TIMESTAMP
                WHERE fingerprint = ?
            """, (generation, fingerprint))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def purge_stale(self, current_generation: int) -> int:
        """
        Remove cache entries not seen in the last N generations.

        Args:
            current_generation: Current EPG generation counter

        Returns:
            Number of entries purged
        """
        threshold = current_generation - self.PURGE_AFTER_GENERATIONS
        if threshold < 0:
            return 0

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM stream_match_cache
                WHERE last_seen_generation < ?
            """, (threshold,))
            purged = cursor.rowcount
            conn.commit()

            if purged > 0:
                self._stats['purged'] += purged
                logger.info(f"[CACHE PURGE] Removed {purged} stale entries (generation < {threshold})")

            return purged
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, int]:
        """Get cache statistics for this session."""
        return self._stats.copy()

    def get_cache_size(self) -> int:
        """Get total number of cached entries."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM stream_match_cache")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def clear_group(self, group_id: int) -> int:
        """
        Clear all cache entries for a specific group.
        Useful when group settings change significantly.

        Args:
            group_id: Event group ID to clear

        Returns:
            Number of entries cleared
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM stream_match_cache WHERE group_id = ?
            """, (group_id,))
            cleared = cursor.rowcount
            conn.commit()
            logger.info(f"[CACHE CLEAR] Cleared {cleared} entries for group {group_id}")
            return cleared
        finally:
            conn.close()

    def clear_all(self) -> int:
        """
        Clear entire cache. Use sparingly.

        Returns:
            Number of entries cleared
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stream_match_cache")
            cleared = cursor.rowcount
            conn.commit()
            logger.info(f"[CACHE CLEAR] Cleared entire cache ({cleared} entries)")
            return cleared
        finally:
            conn.close()


def get_generation_counter(get_connection_func) -> int:
    """Get current EPG generation counter from settings."""
    conn = get_connection_func()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT epg_generation_counter FROM settings WHERE id = 1")
        row = cursor.fetchone()
        return row['epg_generation_counter'] if row and row['epg_generation_counter'] else 0
    except Exception:
        return 0
    finally:
        conn.close()


def increment_generation_counter(get_connection_func) -> int:
    """Increment and return the new EPG generation counter."""
    conn = get_connection_func()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE settings
            SET epg_generation_counter = COALESCE(epg_generation_counter, 0) + 1
            WHERE id = 1
        """)
        conn.commit()

        cursor.execute("SELECT epg_generation_counter FROM settings WHERE id = 1")
        row = cursor.fetchone()
        new_value = row['epg_generation_counter'] if row else 1
        logger.debug(f"EPG generation counter: {new_value}")
        return new_value
    finally:
        conn.close()


def merge_dynamic_fields(cached_event: Dict, fresh_event: Dict) -> Dict:
    """
    Merge dynamic fields from fresh ESPN data into cached event.

    DYNAMIC FIELDS that get refreshed:
    - status (scheduled/in-progress/final, period, detail)
    - home_team.score, away_team.score
    - odds (spread, moneyline, over_under)
    - home_team.streak, away_team.streak

    Args:
        cached_event: Cached normalized event dict
        fresh_event: Fresh event data from get_event_summary()

    Returns:
        Merged event dict with updated dynamic fields
    """
    # Start with cached data
    merged = cached_event.copy()

    if not fresh_event:
        return merged

    # Update status
    if 'status' in fresh_event:
        merged['status'] = fresh_event['status']

    # Update scores
    if 'home_team' in fresh_event and 'score' in fresh_event['home_team']:
        if 'home_team' not in merged:
            merged['home_team'] = {}
        merged['home_team']['score'] = fresh_event['home_team']['score']

    if 'away_team' in fresh_event and 'score' in fresh_event['away_team']:
        if 'away_team' not in merged:
            merged['away_team'] = {}
        merged['away_team']['score'] = fresh_event['away_team']['score']

    # Update streaks (can change after each game)
    if 'home_team' in fresh_event and 'streak' in fresh_event.get('home_team', {}):
        merged['home_team']['streak'] = fresh_event['home_team'].get('streak', '')
    if 'away_team' in fresh_event and 'streak' in fresh_event.get('away_team', {}):
        merged['away_team']['streak'] = fresh_event['away_team'].get('streak', '')

    # Update odds (can shift)
    if 'odds' in fresh_event:
        merged['odds'] = fresh_event['odds']
        merged['has_odds'] = fresh_event.get('has_odds', bool(fresh_event['odds']))

    # Update competitions array for downstream processing
    if 'competitions' in fresh_event:
        merged['competitions'] = fresh_event['competitions']

    # Mark as refreshed
    if '_enrichment' not in merged:
        merged['_enrichment'] = {}
    merged['_enrichment']['refreshed_at'] = datetime.now(ZoneInfo('UTC')).isoformat()
    merged['_enrichment']['from_cache'] = True

    return merged


def refresh_cached_event(
    espn_client: 'ESPNClient',
    cached_data: Dict,
    league: str,
    get_connection_func
) -> Optional[Dict]:
    """
    Refresh a cached event with fresh dynamic data from ESPN.

    Uses get_event_summary() to fetch current scores/status, then merges
    dynamic fields into the cached event data.

    Args:
        espn_client: ESPNClient instance
        cached_data: Dict with 'event' and 'team_result' from cache
        league: League code (e.g., 'nhl', 'nfl')
        get_connection_func: Function that returns a database connection

    Returns:
        Dict with refreshed 'event' and original 'team_result', or None if fetch fails
    """
    from epg.league_config import get_league_config

    cached_event = cached_data.get('event', {})
    event_id = cached_event.get('id')

    if not event_id:
        logger.warning("[CACHE] No event_id in cached data")
        return None

    # Get sport from league config
    league_config = get_league_config(league, get_connection_func)
    if not league_config:
        logger.warning(f"[CACHE] No league config for {league}")
        return cached_data  # Return cached data as-is

    sport = league_config['sport']

    # Fetch fresh event data
    fresh_event = espn_client.get_event_summary(sport, league, event_id)

    if not fresh_event:
        logger.debug(f"[CACHE] Could not fetch fresh data for event {event_id}, using cached")
        return cached_data  # Return cached data as-is

    # Merge dynamic fields into cached event
    merged_event = merge_dynamic_fields(cached_event, fresh_event)

    return {
        'event': merged_event,
        'team_result': cached_data.get('team_result', {})
    }
