"""Shared channel name/logo/template resolution for the lifecycle paths.

Used by BOTH the creation path (`ChannelCreator._create_channel`) and the
sync path (`ChannelSyncer._sync_channel_settings`) — see the "Parallel Paths"
section of the ChannelLifecycleService docstring. Keeping these in one module
is what keeps those paths resolving identically.
"""

import logging

from teamarr.consumers.event_epg import POSTPONED_LABEL, is_event_postponed
from teamarr.core import Event
from teamarr.utilities.art_url import apply_art_base_url

from ._host import _LifecycleHost

logger = logging.getLogger(__name__)

# Template variables that, when present in a channel-name template, mean the
# user wants explicit control over feed labeling — so the canned auto-append
# suffix should be skipped to avoid duplication like "Pirates Feed (Pirates)".
# Excludes feed_team_logo (URL field, not visible in channel name) and the
# directional booleans which are typically used in conditions, not naming.
FEED_TEMPLATE_VARS = frozenset({
    "feed_team",
    "feed_team_short",
    "feed_team_abbrev",
    "feed_team_abbrev_lower",
    "feed_home_away",
    "broadcast_feed",
    "broadcast_feed_team",
})


class ChannelNaming(_LifecycleHost):
    """Resolves channel names, logo URLs and template strings.

    Mixin for ChannelLifecycleService — relies on the coordinator's
    ``_db_factory``, ``_context_builder`` and ``_resolver`` attributes.
    """

    def _generate_channel_name(
        self,
        event: Event,
        template,
        exception_keyword: str | None,
        segment: str | None = None,
        feed_team=None,
        feed_label_style: str | None = None,
    ) -> str:
        """Generate channel name for an event using template.

        Template is required - raises ValueError if not provided.

        Supports {exception_keyword} variable in templates. If the template
        includes {exception_keyword}, the value is substituted directly.
        If not included and a keyword is present, it's auto-appended as
        "(Keyword)" to maintain backward compatibility.

        When feed_team is provided, auto-appends a feed label based on
        feed_label_style: 'team_name' → "(Orioles Feed)", 'short_name' →
        "(BAL Feed)", 'home_away' → "(Home Feed)" or "(Away Feed)".

        Also prepends "Postponed: " to the channel name if the event is
        postponed and the prepend_postponed_label setting is enabled.

        Args:
            event: Event data
            template: Required - dict or EventTemplateConfig with channel name format
            exception_keyword: Optional keyword for naming
            segment: UFC card segment code (e.g., "prelims", "main_card")
            feed_team: Team object for feed separation (if detected)
            feed_label_style: Label style ('team_name', 'short_name', 'home_away')

        Raises:
            ValueError: If template is missing or has no channel name format
        """
        # Get channel name format from template or use default
        name_format = None
        if template:
            # Handle both dict and dataclass template types
            if hasattr(template, "channel_name_format"):
                # EventTemplateConfig dataclass
                name_format = template.channel_name_format
            elif hasattr(template, "get"):
                # Dict with event_channel_name
                name_format = template.get("event_channel_name")

        # Build extra variables for template resolution
        # Always include exception_keyword - resolves to "" if None (graceful disappear)
        extra_vars = {
            "exception_keyword": exception_keyword if exception_keyword else "",
        }

        if not name_format:
            raise ValueError(
                f"Template has no channel name format for event {event.id} - "
                "template must define event_channel_name or channel_name_format"
            )

        # Check if template uses {exception_keyword} - if so, don't auto-append
        template_uses_keyword = "{exception_keyword}" in name_format

        # Same gate for feed label: if the template already references any feed-team
        # variable, the user is taking control of where it appears in the channel name
        # — don't double up via the canned auto-append suffix.
        template_uses_feed_var = self._template_uses_feed_var(name_format)

        # Resolve using full template engine with extra variables
        # Unknown variables stay literal (e.g., {bad_var}) so user can identify issues
        base_name = self._resolve_template(
            name_format, event, extra_vars,
            card_segment=segment, feed_team=feed_team,
        )

        # Clean up empty wrappers when {exception_keyword} resolves to ""
        # e.g., "Team A @ Team B ()" → "Team A @ Team B"
        base_name = self._clean_empty_wrappers(base_name)

        # Auto-append keyword only if template didn't use {exception_keyword}
        if exception_keyword and not template_uses_keyword:
            base_name = f"{base_name} ({exception_keyword})"

        # Auto-append feed label when feed_team is present and the template
        # didn't already place a feed variable
        if feed_team and feed_label_style and not template_uses_feed_var:
            feed_label = self._build_feed_label(
                feed_team, event, feed_label_style
            )
            if feed_label:
                base_name = f"{base_name} ({feed_label})"

        # Prepend "POSTPONED | " if event is postponed and setting is enabled
        if is_event_postponed(event):
            from teamarr.database.settings import get_epg_settings

            with self._db_factory() as conn:
                epg_settings = get_epg_settings(conn)
                if epg_settings.prepend_postponed_label:
                    base_name = f"{POSTPONED_LABEL}{base_name}"

        return base_name

    def _clean_empty_wrappers(self, text: str) -> str:
        """Clean up empty wrappers left when variables resolve to empty string.

        Removes:
        - Empty parentheses: () []
        - Trailing separators: " - ", " | ", " : "
        - Multiple consecutive spaces
        - Leading/trailing whitespace

        Examples:
            "Team A @ Team B ()" → "Team A @ Team B"
            "Team A @ Team B []" → "Team A @ Team B"
            "Team A @ Team B - " → "Team A @ Team B"
            "Team A  @  Team B" → "Team A @ Team B"
        """
        import re

        # Remove empty parentheses and brackets (with optional surrounding space)
        text = re.sub(r"\s*\(\s*\)", "", text)
        text = re.sub(r"\s*\[\s*\]", "", text)

        # Remove trailing separators
        text = re.sub(r"\s*[-|:]\s*$", "", text)

        # Collapse multiple spaces into one
        text = re.sub(r"\s{2,}", " ", text)

        return text.strip()

    @staticmethod
    def _template_uses_feed_var(name_format: str) -> bool:
        """True if the channel-name template references any feed-team variable.

        Used to suppress the canned feed-label auto-append so users who place
        {feed_team}/{feed_team_short}/etc. in their template don't get a
        duplicated suffix like "Pirates Feed (Pirates)".
        """
        return any(f"{{{var}}}" in name_format for var in FEED_TEMPLATE_VARS)

    @staticmethod
    def _build_feed_label(feed_team, event: Event, style: str) -> str:
        """Build the feed label based on the configured style.

        Args:
            feed_team: Team object (the resolved feed team)
            event: Event (to determine home/away)
            style: 'team_name', 'short_name', or 'home_away'

        Returns:
            Label string (e.g., "Orioles Feed", "BAL Feed", "Home Feed")
        """
        if style == "home_away":
            is_home = (
                hasattr(event, "home_team")
                and event.home_team
                and event.home_team.id == feed_team.id
            )
            return "Home Feed" if is_home else "Away Feed"
        elif style == "short_name":
            abbrev = getattr(feed_team, "abbreviation", None)
            name = abbrev or feed_team.short_name or feed_team.name
            return f"{name} Feed"
        else:  # team_name (default)
            name = feed_team.short_name or feed_team.name
            return f"{name} Feed"

    def _resolve_logo_url(
        self,
        event: Event,
        template,
        exception_keyword: str | None = None,
        segment: str | None = None,
        feed_team=None,
    ) -> str | None:
        """Resolve logo URL from template.

        Uses full template engine for variable resolution.
        No fallback to team logo - if no template, returns None.

        Args:
            event: Event data
            template: Can be dict, EventTemplateConfig dataclass, or None
            exception_keyword: Optional keyword for {exception_keyword} variable
            segment: UFC card segment code (e.g., "prelims", "main_card")
            feed_team: Team object for feed separation (if detected)
        """
        logo_url = None
        if template:
            # Handle both dict and dataclass template types
            if hasattr(template, "event_channel_logo_url"):
                # EventTemplateConfig dataclass
                logo_url = template.event_channel_logo_url
            elif hasattr(template, "get"):
                # Dict with event_channel_logo_url
                logo_url = template.get("event_channel_logo_url")

        if logo_url:
            # Resolve template variables if present
            # Unknown variables stay literal (e.g., {bad_var}) so user can identify issues
            if "{" in logo_url:
                extra_vars = {
                    "exception_keyword": exception_keyword if exception_keyword else "",
                }
                resolved = self._resolve_template(
                    logo_url, event, extra_vars, card_segment=segment,
                    feed_team=feed_team,
                )
            else:
                resolved = logo_url
            # Apply the game-thumbs base URL (epic z02s) so the Dispatcharr channel
            # logo gets the SAME reconstructed URL as the EPG <icon>. Single base
            # source = the resolver. Idempotent: absolute URLs pass through.

            return apply_art_base_url(resolved, self._resolver.art_base_url)

        return None

    def _resolve_template(
        self,
        template_str: str,
        event: Event,
        extra_variables: dict[str, str] | None = None,
        card_segment: str | None = None,
        feed_team=None,
    ) -> str:
        """Resolve template string using full template engine.

        Supports all 141+ template variables plus optional extra variables.

        Args:
            template_str: Template string with {variable} placeholders
            event: Event to extract context from
            extra_variables: Optional dict of additional variables to resolve
                (e.g., {"exception_keyword": "Spanish"})
            card_segment: UFC card segment code (e.g., "prelims", "main_card")
            feed_team: Team object for feed separation (if detected)

        Returns:
            Resolved string with variables replaced
        """
        # Handle extra variables first (simple replacement)
        if extra_variables:
            for var_name, value in extra_variables.items():
                template_str = template_str.replace(f"{{{var_name}}}", value)

        context = self._context_builder.build_for_event(
            event=event,
            team_id=event.home_team.id if event.home_team else "",
            league=event.league,
            card_segment=card_segment,
        )
        context.feed_team = feed_team
        return self._resolver.resolve(template_str, context)
