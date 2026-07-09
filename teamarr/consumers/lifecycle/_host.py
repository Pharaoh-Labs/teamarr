"""Type-only host surface for the lifecycle mixins.

``ChannelLifecycleService`` (service.py) is composed from four mixins —
``ChannelCreator``, ``ChannelNaming``, ``ChannelSyncer`` and ``ChannelCleanup``.
Each mixin freely calls ``self._<x>`` for attributes and methods that the
*composed host* actually defines (on ``ChannelLifecycleService`` or on a
sibling mixin). In isolation Pyright cannot see those cross-mixin members and
reports ``reportAttributeAccessIssue``.

``_LifecycleHost`` declares that borrowed surface for the type checker only.
It is **runtime-empty**: every member lives under ``if TYPE_CHECKING`` so the
class body is empty at import time. Each mixin inherits it, which lets Pyright
resolve the borrowed ``self._x`` access; at runtime the real definitions on the
most-derived ``ChannelLifecycleService`` win in MRO.

Do NOT add ``_LifecycleHost`` to ``ChannelLifecycleService``'s bases — the mixins
already carry it, and the host provides the concrete implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


class _LifecycleHost:
    """Runtime-empty declaration of the host surface borrowed by the mixins."""

    if TYPE_CHECKING:
        # --- data attributes (real types where clear, else Any) ---
        _db_factory: Any
        _sports_service: Any
        _channel_manager: Any
        _logo_manager: Any
        _epg_manager: Any
        _timing_manager: Any
        _dynamic_resolver: Any
        _dispatcharr_lock: Any
        _resolver: Any
        _context_builder: Any
        _external_occupied: set[int] | None
        _league_configs: Any
        _timezone: str
        _exception_keywords: list | None
        _pending_profile_changes: dict[int, dict[str, set[int]]]
        _dispatcharr_failure_count: int
        _stream_drift_fix_count: int

        # --- borrowed methods (permissive signatures) ---
        def _safe_update_channel(self, *args: Any, **kwargs: Any) -> Any: ...
        def _sync_channel_settings(self, *args: Any, **kwargs: Any) -> Any: ...
        def _resolve_logo_url(self, *args: Any, **kwargs: Any) -> Any: ...
        def _generate_channel_name(self, *args: Any, **kwargs: Any) -> Any: ...
        def _collect_profile_change(self, *args: Any, **kwargs: Any) -> Any: ...
        def _apply_pending_profile_changes(self, *args: Any, **kwargs: Any) -> Any: ...
        def _resolve_event_template(self, *args: Any, **kwargs: Any) -> Any: ...
        def _parse_profile_ids(self, *args: Any, **kwargs: Any) -> Any: ...
        def _check_exception_keyword(self, *args: Any, **kwargs: Any) -> Any: ...
