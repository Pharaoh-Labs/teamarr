"""XMLTV rendering (programmes + filler) and per-group storage."""

import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from sqlite3 import Connection
from typing import TYPE_CHECKING, Any

from teamarr.config import get_user_timezone
from teamarr.consumers.event_epg import EventEPGOptions
from teamarr.consumers.filler.event_filler import (
    EventFillerConfig,
    EventFillerGenerator,
    EventFillerOptions,
    EventFillerResult,
    template_to_event_filler_config,
)
from teamarr.database.groups import EventEPGGroup
from teamarr.database.subscription import (
    get_subscription_template_for_event,
    get_subscription_templates,
)
from teamarr.utilities.xmltv import programmes_to_xmltv

logger = logging.getLogger(__name__)


class XmltvRenderer:
    """Renders XMLTV + filler for matched streams and stores it per group.

    Mixin for EventGroupProcessor — relies on the coordinator's
    ``_service``, ``_epg_generator`` and ``_art_base_url`` attributes.
    """

    if TYPE_CHECKING:
        # Provided by the EventGroupProcessor coordinator / sibling mixins.
        # Declared for type-checkers only — no runtime effect.
        _service: Any
        _epg_generator: Any
        _art_base_url: Any

    def _load_event_template(self, conn: Connection, template_id: int):
        """Load and convert template for event-based EPG.

        Args:
            conn: Database connection
            template_id: Template ID to load

        Returns:
            EventTemplateConfig or None if template not found
        """
        from teamarr.database.templates import get_template, template_to_event_config

        template = get_template(conn, template_id)
        if not template:
            logger.warning("[EVENT_EPG] Template %s not found", template_id)
            return None

        return template_to_event_config(template)

    def _generate_xmltv(
        self,
        matched_streams: list[dict],
        group: EventEPGGroup,
        conn: Connection,
    ) -> tuple[str, int, int, int, int]:
        """Generate XMLTV content from matched streams.

        Args:
            matched_streams: List of matched stream/event dicts
            group: Event group config
            conn: Database connection

        Returns:
            Tuple of (xmltv_content, total_programmes, event_programmes, pregame, postgame)
        """
        if not matched_streams:
            return "", 0, 0, 0, 0

        # Load template options if configured
        # Resolve template from global subscription
        options = EventEPGOptions()
        filler_config: EventFillerConfig | None = None
        template_db = None

        # Get default template from subscription (fallback for all events)
        default_template_id = get_subscription_template_for_event(
            conn, "", ""
        )

        if default_template_id:
            template_config = self._load_event_template(conn, default_template_id)
            if template_config:
                options.template = template_config

            # Load raw template for filler config (used as fallback)
            from teamarr.database.templates import get_template

            template_db = get_template(conn, default_template_id)
            if template_db and (template_db.pregame_enabled or template_db.postgame_enabled):
                filler_config = template_to_event_filler_config(template_db)

        # Resolve per-event templates based on sport/league specificity
        # This allows different templates for different sports/leagues in multi-sport groups
        template_cache: dict = {}  # {template_id: EventTemplateConfig}
        filler_cache: dict[int, EventFillerConfig | None] = {}  # {template_id: filler_config}

        # Load exception keywords for stream annotation (used by EPG generator)
        from teamarr.database.channels import check_exception_keyword, get_exception_keywords

        exception_keywords = get_exception_keywords(conn)

        # Log template resolution context
        sub_templates = get_subscription_templates(conn)
        if len(sub_templates) > 1:
            logger.info(
                "[EVENT_EPG] Multi-template subscription: default=%s, "
                "templates=%s",
                default_template_id,
                [
                    (t.template_id, t.sports, t.leagues)
                    for t in sub_templates
                ],
            )

        for match in matched_streams:
            event = match.get("event")
            if not event:
                continue

            event_sport = getattr(event, "sport", "") or ""
            event_league = getattr(event, "league", "") or ""

            # Resolve the best template for this specific event
            event_template_id = get_subscription_template_for_event(
                conn, event_sport, event_league
            )

            # Log template resolution for multi-template subscriptions
            if len(sub_templates) > 1:
                logger.info(
                    "[EVENT_EPG] Template resolution: event=%s "
                    "sport=%r league=%r -> template=%s (default=%s)",
                    event.id,
                    event_sport,
                    event_league,
                    event_template_id,
                    default_template_id,
                )

            # Store resolved template ID on each match for filler lookup
            match["_event_template_id"] = event_template_id

            if event_template_id and event_template_id != default_template_id:
                # Use cached template if already loaded
                if event_template_id not in template_cache:
                    event_template_config = self._load_event_template(conn, event_template_id)
                    if event_template_config:
                        template_cache[event_template_id] = event_template_config

                if event_template_id in template_cache:
                    match["_event_template"] = template_cache[event_template_id]
                    logger.debug(
                        "[EVENT_EPG] Using sport/league-specific template %d for %s/%s event",
                        event_template_id,
                        event_sport,
                        event_league,
                    )

            # Build per-event filler config cache
            if event_template_id and event_template_id not in filler_cache:
                from teamarr.database.templates import get_template

                tmpl = get_template(conn, event_template_id)
                if tmpl and (tmpl.pregame_enabled or tmpl.postgame_enabled):
                    filler_cache[event_template_id] = template_to_event_filler_config(tmpl)
                else:
                    filler_cache[event_template_id] = None

            # Annotate match with its per-event filler config
            if event_template_id and event_template_id in filler_cache:
                match["_event_filler_config"] = filler_cache[event_template_id]

            # Annotate match with exception keyword for EPG channel name parity
            stream_name = match.get("stream", {}).get("name", "")
            if stream_name and exception_keywords:
                keyword_label, _ = check_exception_keyword(stream_name, exception_keywords)
                if keyword_label:
                    match["_exception_keyword"] = keyword_label

        # Load sport durations and lookback from settings
        options.sport_durations = self._load_sport_durations(conn)
        lookback_hours = self._load_lookback_hours(conn)

        # Generate programmes and channels from matched streams
        programmes, channels = self._epg_generator.generate_for_matched_streams(
            matched_streams, options
        )

        if not programmes:
            return "", 0, 0, 0, 0

        # Track event programmes separately
        event_programmes_count = len(programmes)
        pregame_count = 0
        postgame_count = 0

        # Generate filler if any template (default or per-event) has filler enabled
        any_filler = filler_config or any(
            fc for fc in filler_cache.values() if fc is not None
        )
        if any_filler:
            filler_result = self._generate_filler_for_streams(
                matched_streams,
                filler_config,
                options.sport_durations,
                lookback_hours,
                prepend_postponed_label=options.prepend_postponed_label,
            )
            if filler_result.programmes:
                pregame_count = filler_result.pregame_count
                postgame_count = filler_result.postgame_count
                programmes.extend(filler_result.programmes)
                # Sort all programmes by channel_id then start time
                programmes.sort(key=lambda p: (p.channel_id, p.start))
                logger.debug(
                    f"Added {len(filler_result.programmes)} filler programmes "
                    f"({pregame_count} pregame, {postgame_count} postgame) "
                    f"for group '{group.name}'"
                )

        # Convert to XMLTV
        from teamarr.database.settings import get_epg_settings

        art_base_url = get_epg_settings(conn).art_base_url
        channel_dicts = [{"id": ch.channel_id, "name": ch.name, "icon": ch.icon} for ch in channels]
        xmltv_content = programmes_to_xmltv(
            programmes, channel_dicts, art_base_url=art_base_url
        )

        filler_total = pregame_count + postgame_count
        logger.info(
            f"Generated XMLTV for group '{group.name}': "
            f"{event_programmes_count} events + {filler_total} filler = "
            f"{len(programmes)} programmes, {len(xmltv_content)} bytes"
        )

        return xmltv_content, len(programmes), event_programmes_count, pregame_count, postgame_count

    def _load_sport_durations(self, conn: Connection) -> dict[str, float]:
        """Load sport duration settings from database.

        Dynamically loads all sports from DurationSettings dataclass.
        """
        from teamarr.database.settings import get_all_settings

        all_settings = get_all_settings(conn)
        return asdict(all_settings.durations)

    def _load_lookback_hours(self, conn: Connection) -> int:
        """Load EPG lookback hours setting from database."""
        row = conn.execute("SELECT epg_lookback_hours FROM settings WHERE id = 1").fetchone()
        if not row:
            return 6  # Default
        return row[0] or 6

    def _generate_filler_for_streams(
        self,
        matched_streams: list[dict],
        filler_config: EventFillerConfig | None,
        sport_durations: dict[str, float],
        lookback_hours: int = 6,
        prepend_postponed_label: bool = True,
    ) -> EventFillerResult:
        """Generate filler programmes for matched event streams.

        Args:
            matched_streams: List of matched stream/event dicts
            filler_config: Filler configuration from template
            sport_durations: Sport duration settings
            lookback_hours: How far back to generate EPG (for preceding content)
            prepend_postponed_label: Whether to prepend "Postponed: " for postponed events

        Returns:
            EventFillerResult with programmes and pregame/postgame counts
        """

        filler_generator = EventFillerGenerator(self._service, art_base_url=self._art_base_url)
        result = EventFillerResult()

        # Get configured timezone
        tz = get_user_timezone()

        # Build filler options - lookback allows preceding EPG content
        now = datetime.now(tz)
        epg_start = now - timedelta(hours=lookback_hours)
        options = EventFillerOptions(
            epg_start=epg_start,
            epg_end=now + timedelta(days=1),  # 24 hour window
            epg_timezone=str(tz),
            sport_durations=sport_durations,
            default_duration=3.0,
            postgame_buffer_hours=24.0,
            prepend_postponed_label=prepend_postponed_label,
        )

        for stream_match in matched_streams:
            event = stream_match.get("event")

            if not event:
                continue

            # Use per-event filler config if available, fall back to default
            stream_filler_config = stream_match.get("_event_filler_config") or filler_config
            if not stream_filler_config:
                continue  # No filler config for this event's template

            # UFC segment support: extract segment info if present
            segment = stream_match.get("segment")
            segment_start = stream_match.get("segment_start")
            segment_end = stream_match.get("segment_end")

            # Use consistent tvg_id matching EventEPGGenerator and ChannelLifecycleService.
            # Must include feed_team_id when feed separation is active so filler lands
            # on the same per-feed channel as the live programme.
            from teamarr.consumers.lifecycle import generate_event_tvg_id

            exception_keyword = stream_match.get("_exception_keyword")
            feed_team = stream_match.get("feed_team")
            feed_team_id = feed_team.id if feed_team else None
            channel_id = generate_event_tvg_id(
                event.id, event.provider, segment, exception_keyword, feed_team_id
            )

            # For UFC segments, override event times with segment-specific times
            if segment_start and segment_end:
                segment_options = EventFillerOptions(
                    epg_start=epg_start,
                    epg_end=segment_end + timedelta(hours=24),
                    epg_timezone=str(tz),
                    sport_durations=sport_durations,
                    default_duration=3.0,
                    postgame_buffer_hours=24.0,
                    event_end_override=segment_end,  # Use exact segment end time
                    prepend_postponed_label=prepend_postponed_label,
                )
                # Create a modified event with segment start time
                from dataclasses import replace

                segment_event = replace(event, start_time=segment_start)
                use_event = segment_event
                use_options = segment_options
            else:
                use_event = event
                use_options = options

            try:
                filler_result = filler_generator.generate_with_counts(
                    event=use_event,
                    channel_id=channel_id,
                    config=stream_filler_config,
                    options=use_options,
                    card_segment=segment,
                )
                result.programmes.extend(filler_result.programmes)
                result.pregame_count += filler_result.pregame_count
                result.postgame_count += filler_result.postgame_count
            except Exception as e:
                logger.warning(
                    "[EVENT_EPG] Failed to generate filler for event %s: %s", event.id, e
                )

        return result

    def _store_group_xmltv(
        self,
        conn: Connection,
        group_id: int,
        xmltv_content: str,
    ) -> None:
        """Store XMLTV content for a group in the database.

        This allows the XMLTV to be served at a predictable URL
        that Dispatcharr can fetch.
        """
        # Upsert into event_epg_xmltv table
        conn.execute(
            """
            INSERT INTO event_epg_xmltv (group_id, xmltv_content, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(group_id) DO UPDATE SET
                xmltv_content = excluded.xmltv_content,
                updated_at = datetime('now')
            """,
            (group_id, xmltv_content),
        )
        conn.commit()
        logger.debug("[EVENT_EPG] Stored XMLTV for group %d", group_id)
