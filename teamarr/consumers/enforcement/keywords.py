"""Keyword enforcement for stream placement.

Ensures streams are on the correct channel based on exception keywords.
Runs once per EPG generation to fix any misplaced streams.

When to use:
- A stream with keyword "Spanish" should be on the Spanish channel, not main
- A stream without keywords should be on main channel, not a keyword channel
- Keywords may be added/removed after streams were already placed
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class KeywordEnforcementResult:
    """Result of keyword enforcement run."""

    streams_moved: list[dict] = field(default_factory=list)
    streams_correct: int = 0
    channels_emptied: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    @property
    def moved_count(self) -> int:
        return len(self.streams_moved)

    def to_dict(self) -> dict:
        return {
            "streams_moved": self.streams_moved,
            "streams_correct": self.streams_correct,
            "channels_emptied": self.channels_emptied,
            "errors": self.errors,
            "summary": {
                "moved": self.moved_count,
                "correct": self.streams_correct,
                "emptied": len(self.channels_emptied),
                "errors": len(self.errors),
            },
        }


def _missing_group_evidence(
    group_id: int | None, group_name: str | None, current_keyword: str | None, keywords: list
) -> bool:
    """True when ``current_keyword`` may rest on M3U group data this row lacks.

    Rows attached before #893 have no M3U group, and a row attached on a run
    whose groups list failed to load has the id but no name. Either way a
    keyword that matched the stream by its group can't be re-confirmed from
    the row alone.
    """
    if current_keyword is None or group_name:
        return False
    if group_id is not None:
        return any(kw.label == current_keyword and kw.m3u_group_regex for kw in keywords)
    return any(kw.label == current_keyword and kw.uses_m3u_group for kw in keywords)


def _pick_target(siblings: Any, current: Any, keyword: str | None) -> Any | None:
    """The event's channel for ``keyword``, among every channel of that event.

    Several can qualify — feed separation gives an event a HOME and an AWAY
    channel per keyword, and 'separate' mode one per stream — so prefer the
    channel the stream is already on (no move), then one on the same feed,
    then one from the same event group, then the oldest. The last two only
    break ties; they keep the choice the group-scoped lookup used to make
    whenever it worked.
    """
    matches = [ch for ch in siblings if (ch.exception_keyword or None) == keyword]
    if not matches:
        return None
    feed = getattr(current, "feed_team_id", None) or None
    return min(
        matches,
        key=lambda ch: (
            ch.id != current.id,
            (getattr(ch, "feed_team_id", None) or None) != feed,
            ch.event_epg_group_id != current.event_epg_group_id,
            ch.id,
        ),
    )


class KeywordEnforcer:
    """Enforces correct stream placement based on exception keywords.

    Scans all active streams across all channels and ensures each stream
    is on the correct channel:
    - Streams matching a keyword → keyword channel (or main if not exists)
    - Streams not matching any keyword → main channel

    This corrects misplacements that occur when:
    - Keywords are added/removed after streams were placed
    - Stream names change
    - Manual stream additions
    """

    def __init__(
        self,
        db_factory: Any,
        channel_manager: Any = None,
    ):
        """Initialize the enforcer.

        Args:
            db_factory: Factory returning database connection
            channel_manager: Optional ChannelManager for Dispatcharr sync
        """
        self._db_factory = db_factory
        self._channel_manager = channel_manager
        self._dispatcharr_lock = threading.Lock()

    def enforce(self) -> KeywordEnforcementResult:
        """Run keyword enforcement across all channels.

        Scans all streams and moves any that are on the wrong channel.

        Returns:
            KeywordEnforcementResult with move details
        """
        from teamarr.database.channels import (
            add_stream_to_channel,
            check_exception_keyword,
            event_identity_text,
            get_all_managed_channels,
            get_channel_streams,
            get_exception_keywords,
            get_keywords_for_league,
            get_next_stream_priority,
            get_stored_m3u_group_names,
            log_channel_history,
            remove_stream_from_channel,
            stream_exists_on_channel,
        )

        result = KeywordEnforcementResult()

        try:
            with self._db_factory() as conn:
                # Load exception keywords. Race feeds (#245) are league-scoped
                # keywords merged per channel league below.
                from teamarr.database.race_feeds import race_feed_leagues

                exception_keywords = get_exception_keywords(conn)
                feed_leagues = set(race_feed_leagues(conn))

                if not exception_keywords and not feed_leagues:
                    logger.debug("[KEYWORD] No exception keywords configured, skipping")
                    return result
                league_keywords: dict[str | None, list] = {}
                stored_group_names = get_stored_m3u_group_names(conn)

                # Get all active channels
                channels = get_all_managed_channels(conn, include_deleted=False, core_only=True)

                # An event's channels, whichever event group created each one.
                # Channel identity is event-scoped (find_existing_channel), so
                # the lookup has to be too: keyed on the group as well, a
                # stream on a main channel made by one group could not see the
                # keyword channel made by another, resolved its target to the
                # channel it was already on, and stayed on both (#929).
                channel_lookup: dict[tuple, list[Any]] = {}
                for ch in channels:
                    channel_lookup.setdefault((ch.event_id, ch.event_provider), []).append(ch)

                # Check each channel's streams
                for channel in channels:
                    streams = get_channel_streams(conn, channel.id, include_removed=False)

                    for stream in streams:
                        stream_name = stream.stream_name or ""
                        group_name = stream.m3u_group_name
                        if not group_name and stream.m3u_group_id is not None:
                            # Attached while the groups list failed to load
                            # (#893); another row may carry the group's name.
                            group_name = stored_group_names.get(stream.m3u_group_id)

                        # What keyword should this stream have?
                        league = channel.league if channel.league in feed_leagues else None
                        if league not in league_keywords:
                            league_keywords[league] = get_keywords_for_league(
                                conn, league, exception_keywords
                            )
                        # The persisted programme text (#829) keeps an
                        # EPG-matched stream whose keyword only the guide
                        # names from being moved back to the main channel.
                        expected_keyword, behavior = check_exception_keyword(
                            stream_name,
                            league_keywords[league],
                            event_identity_text(channel),
                            stream.epg_program_title,
                            stream_id=stream.dispatcharr_stream_id,
                            m3u_group_id=stream.m3u_group_id,
                            m3u_group_name=group_name,
                            event_group_id=stream.source_group_id,
                        )

                        # Normalize: None for no keyword
                        current_keyword = channel.exception_keyword or None
                        expected_keyword = expected_keyword if expected_keyword else None

                        if expected_keyword != current_keyword and _missing_group_evidence(
                            stream.m3u_group_id,
                            group_name,
                            current_keyword,
                            league_keywords[league],
                        ):
                            # Attached before the M3U group was stored (#893):
                            # the creator backfills it the next time it sees the
                            # stream, and until then the move would be a guess.
                            result.streams_correct += 1
                            continue

                        # If behavior is 'ignore', stream shouldn't be here at all
                        if behavior == "ignore":
                            # Remove stream entirely
                            remove_stream_from_channel(
                                conn,
                                channel.id,
                                stream.dispatcharr_stream_id,
                                reason=f"Keyword '{expected_keyword}' behavior is ignore",
                            )
                            result.streams_moved.append(
                                {
                                    "stream": stream_name,
                                    "action": "removed",
                                    "reason": f"Keyword '{expected_keyword}' set to ignore",
                                }
                            )
                            continue

                        # Is stream on correct channel?
                        if current_keyword == expected_keyword:
                            result.streams_correct += 1
                            continue

                        # Find target channel
                        siblings = channel_lookup.get(
                            (channel.event_id, channel.event_provider), ()
                        )
                        target_channel = _pick_target(siblings, channel, expected_keyword)

                        # Fallback to main if keyword channel doesn't exist
                        if not target_channel and expected_keyword:
                            target_channel = _pick_target(siblings, channel, None)

                        if not target_channel:
                            # Can't move - target doesn't exist
                            logger.warning(
                                "[KEYWORD] No target channel for keyword '%s': stream '%s' "
                                "stays on '%s'",
                                expected_keyword,
                                stream_name,
                                channel.channel_name,
                            )
                            result.errors.append(
                                {
                                    "stream": stream_name,
                                    "error": f"No target channel for keyword '{expected_keyword}'",
                                }
                            )
                            continue

                        if target_channel.id == channel.id:
                            # Already on correct channel
                            result.streams_correct += 1
                            continue

                        # Move stream: remove from current, add to target
                        target_name = "main" if not expected_keyword else expected_keyword
                        remove_stream_from_channel(
                            conn,
                            channel.id,
                            stream.dispatcharr_stream_id,
                            reason=f"Moved to {target_name} channel",
                        )

                        # The creator may already have attached the stream to the
                        # target this run (its keyword changed); only the removal
                        # above is still needed, or the target gets a second row.
                        if not stream_exists_on_channel(
                            conn, target_channel.id, stream.dispatcharr_stream_id
                        ):
                            # Use sequential priority - final ordering after all matching
                            priority = get_next_stream_priority(conn, target_channel.id)
                            add_stream_to_channel(
                                conn=conn,
                                managed_channel_id=target_channel.id,
                                dispatcharr_stream_id=stream.dispatcharr_stream_id,
                                stream_name=stream_name,
                                priority=priority,
                                source_group_id=stream.source_group_id,
                                source_group_type=stream.source_group_type,
                                exception_keyword=expected_keyword,
                                m3u_account_id=stream.m3u_account_id,
                                m3u_account_name=stream.m3u_account_name,
                                # Carry matcher metadata across the move — dropping it
                                # detached the stream from the epg_match/stream_type
                                # ordering rules and its EPG attach window (#344).
                                match_type=stream.match_type,
                                match_method=stream.match_method,
                                epg_program_title=stream.epg_program_title,
                                feed_team_id=stream.feed_team_id,
                                attach_at=stream.attach_at,
                                detach_at=stream.detach_at,
                                dispatcharr_channel_group=stream.dispatcharr_channel_group,
                                dispatcharr_channel_group_id=stream.dispatcharr_channel_group_id,
                                dispatcharr_source_channel_id=stream.dispatcharr_source_channel_id,
                                m3u_group_id=stream.m3u_group_id,
                                m3u_group_name=group_name,
                            )

                        # Sync to Dispatcharr
                        if self._channel_manager:
                            self._move_stream_in_dispatcharr(
                                from_channel_id=channel.dispatcharr_channel_id,
                                to_channel_id=target_channel.dispatcharr_channel_id,
                                stream_id=stream.dispatcharr_stream_id,
                            )

                        # Log history on both channels
                        log_channel_history(
                            conn=conn,
                            managed_channel_id=channel.id,
                            change_type="stream_removed",
                            change_source="keyword_enforcement",
                            notes=f"Moved stream '{stream_name}' to {target_name} channel",
                        )
                        log_channel_history(
                            conn=conn,
                            managed_channel_id=target_channel.id,
                            change_type="stream_added",
                            change_source="keyword_enforcement",
                            notes=f"Received stream '{stream_name}' from keyword enforcement",
                        )

                        result.streams_moved.append(
                            {
                                "stream": stream_name,
                                "from_channel": channel.channel_name,
                                "to_channel": target_channel.channel_name,
                                "from_keyword": current_keyword,
                                "to_keyword": expected_keyword,
                            }
                        )

                conn.commit()

        except Exception as e:
            logger.exception("[KEYWORD_ERROR] %s", e)
            result.errors.append({"error": str(e)})

        if result.moved_count > 0 or result.errors:
            logger.info(
                "[KEYWORD] Moved %d streams, %d correct, %d error(s)",
                result.moved_count,
                result.streams_correct,
                len(result.errors),
            )

        return result

    def _move_stream_in_dispatcharr(
        self,
        from_channel_id: int | None,
        to_channel_id: int | None,
        stream_id: int,
    ) -> None:
        """Move stream between channels in Dispatcharr.

        Args:
            from_channel_id: Source channel (to remove from)
            to_channel_id: Target channel (to add to)
            stream_id: Stream ID to move
        """
        if not self._channel_manager:
            return

        try:
            with self._dispatcharr_lock:
                # Remove from source
                if from_channel_id:
                    channel = self._channel_manager.get_channel(from_channel_id)
                    if channel and channel.streams:
                        # streams is tuple[int, ...] — filter out the moved stream
                        streams = [s for s in channel.streams if s != stream_id]
                        logger.info(
                            "[STREAM_AUDIT] keyword move: removing stream %d "
                            "from ch %d: %s → %s",
                            stream_id,
                            from_channel_id,
                            list(channel.streams),
                            streams,
                        )
                        self._channel_manager.update_channel(from_channel_id, {"streams": streams})

                # Add to target
                if to_channel_id:
                    channel = self._channel_manager.get_channel(to_channel_id)
                    if channel:
                        # streams is tuple[int, ...] of stream IDs
                        streams = list(channel.streams) if channel.streams else []
                        if stream_id not in streams:
                            streams.append(stream_id)
                            logger.info(
                                "[STREAM_AUDIT] keyword move: adding stream %d "
                                "to ch %d: %s → %s",
                                stream_id,
                                to_channel_id,
                                list(channel.streams) if channel.streams else [],
                                streams,
                            )
                            self._channel_manager.update_channel(
                                to_channel_id, {"streams": streams}
                            )

        except Exception as e:
            logger.warning("[KEYWORD] Failed to move stream in Dispatcharr: %s", e)
