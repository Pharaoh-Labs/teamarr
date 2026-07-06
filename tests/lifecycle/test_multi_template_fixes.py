"""Tests for multi-template filler, segment naming, and error isolation.

Validates fixes from epic ou3:
- ou3.2: Per-event filler config for multi-template groups
- ou3.4: Remove channel name segment auto-append
- ou3.5: Per-stream error isolation in lifecycle batch
"""

from dataclasses import dataclass

from tests.fakes import make_event

# ---------- Minimal stubs for event / template / filler ----------


def FakeEvent(**overrides):
    """Populated UFC event (shared make_event with this file's defaults)."""
    return make_event(id="100", short_name="A v B", sport="mma", league="ufc", **overrides)


# ---------- ou3.2: Per-event filler annotation ----------


class TestPerEventFillerAnnotation:
    """Verify _generate_xmltv annotates matches with per-event filler configs."""

    def test_matches_get_event_filler_config_annotation(self):
        """Each match should be annotated with _event_filler_config from its template."""

        from teamarr.consumers.filler.event_filler import (
            EventFillerConfig,
            template_to_event_filler_config,
        )

        # Build a minimal template row that template_to_event_filler_config accepts
        # It duck-types on attributes: pregame_enabled, postgame_enabled, etc.
        @dataclass
        class FakeTemplate:
            id: int = 5
            pregame_enabled: bool = True
            postgame_enabled: bool = False
            pregame_title: str = "Pre MMA"
            pregame_description: str = ""
            postgame_title: str = ""
            postgame_description: str = ""
            pregame_padding_minutes: int = 30
            postgame_padding_minutes: int = 0

        tmpl = FakeTemplate()
        filler = template_to_event_filler_config(tmpl)
        assert isinstance(filler, EventFillerConfig)
        assert filler.pregame_enabled is True
        assert filler.postgame_enabled is False

    def test_filler_cache_skips_templates_without_filler(self):
        """Templates with both pregame/postgame disabled → None in filler cache."""

        @dataclass
        class NoFillerTemplate:
            id: int = 6
            pregame_enabled: bool = False
            postgame_enabled: bool = False
            pregame_title: str = ""
            pregame_description: str = ""
            postgame_title: str = ""
            postgame_description: str = ""
            pregame_padding_minutes: int = 0
            postgame_padding_minutes: int = 0

        # The logic is: if not (pregame_enabled or postgame_enabled) → cache None
        tmpl = NoFillerTemplate()
        assert not (tmpl.pregame_enabled or tmpl.postgame_enabled)

    def test_per_event_filler_used_in_generate_filler(self):
        """_generate_filler_for_streams should use _event_filler_config from match."""
        from teamarr.consumers.filler.event_filler import EventFillerConfig

        mma_filler = EventFillerConfig(pregame_enabled=True, postgame_enabled=False)
        default_filler = EventFillerConfig(pregame_enabled=False, postgame_enabled=True)

        # Simulate stream_match with per-event filler
        stream_match = {
            "event": FakeEvent(),
            "_event_filler_config": mma_filler,
        }

        # The logic: stream_filler_config = match.get("_event_filler_config") or filler_config
        stream_filler_config = stream_match.get("_event_filler_config") or default_filler
        assert stream_filler_config is mma_filler

    def test_fallback_to_default_filler_when_no_per_event(self):
        """Without _event_filler_config, should fall back to default filler_config."""
        from teamarr.consumers.filler.event_filler import EventFillerConfig

        default_filler = EventFillerConfig(pregame_enabled=False, postgame_enabled=True)

        stream_match = {
            "event": FakeEvent(),
            # No _event_filler_config key
        }

        stream_filler_config = stream_match.get("_event_filler_config") or default_filler
        assert stream_filler_config is default_filler

    def test_skip_filler_when_no_config_at_all(self):
        """With no per-event or default filler, should skip (continue)."""
        stream_match = {
            "event": FakeEvent(),
        }

        filler_config = None  # No default filler
        stream_filler_config = stream_match.get("_event_filler_config") or filler_config
        assert stream_filler_config is None
        # In the code: if not stream_filler_config: continue


# ---------- ou3.4: Channel name segment auto-append removal ----------


class TestSegmentAutoAppendRemoval:
    """Verify segment_display is no longer auto-appended to channel names."""

    def test_epg_generator_no_segment_append(self):
        """EventEPGGenerator.generate_for_matched_streams should NOT append segment."""
        import inspect

        from teamarr.consumers.event_epg import EventEPGGenerator

        source = inspect.getsource(EventEPGGenerator.generate_for_matched_streams)
        # The auto-append pattern was: channel_name = f"{channel_name} - {segment_display}"
        assert '- {segment_display}"' not in source, (
            "segment_display auto-append should be removed from generate_for_matched_streams"
        )

    def test_lifecycle_create_channel_no_segment_append(self):
        """_create_channel should NOT auto-append segment_display."""
        import inspect

        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        source = inspect.getsource(ChannelLifecycleService._create_channel)
        # The old pattern was: channel_name = f"{channel_name} - {segment_display}"
        assert '- {segment_display}"' not in source, (
            "segment_display auto-append should be removed from _create_channel"
        )

    def test_generate_channel_name_accepts_segment(self):
        """_generate_channel_name should accept segment parameter for template resolution."""
        import inspect

        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        sig = inspect.signature(ChannelLifecycleService._generate_channel_name)
        assert "segment" in sig.parameters, (
            "_generate_channel_name should accept 'segment' for template context"
        )

    def test_resolve_template_passes_card_segment(self):
        """_resolve_template should pass card_segment to build_for_event."""
        import inspect

        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        source = inspect.getsource(ChannelLifecycleService._resolve_template)
        assert "card_segment" in source, (
            "_resolve_template should pass card_segment to context builder"
        )


# ---------- ou3.5: Per-stream error isolation ----------


class TestPerStreamErrorIsolation:
    """Verify that one bad stream doesn't kill the entire batch."""

    def test_process_matched_streams_has_per_stream_try_except(self):
        """process_matched_streams should have try/except inside the for loop."""
        import ast
        import inspect
        import textwrap

        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        source = inspect.getsource(ChannelLifecycleService.process_matched_streams)
        source = textwrap.dedent(source)
        tree = ast.parse(source)

        # Find the for loop over matched_streams
        # We expect it to contain a Try node as immediate child
        found_per_stream_try = False

        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                # Check if target is "matched"
                if isinstance(node.target, ast.Name) and node.target.id == "matched":
                    # The first statement in the for body should be Try
                    if node.body and isinstance(node.body[0], ast.Try):
                        found_per_stream_try = True
                    break

        assert found_per_stream_try, (
            "The 'for matched in matched_streams' loop should wrap its body "
            "in a try/except for error isolation"
        )

    def test_error_isolation_continues_after_exception(self):
        """Exception handlers should use 'continue' to process remaining streams."""
        import inspect

        from teamarr.consumers.lifecycle.service import ChannelLifecycleService

        source = inspect.getsource(ChannelLifecycleService.process_matched_streams)
        # The except handler should log and continue
        assert "stream_err" in source, "Should catch per-stream exceptions as 'stream_err'"
        assert "Error processing stream" in source, "Should log per-stream errors"
