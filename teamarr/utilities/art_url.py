"""Game-thumbs base URL reconstruction (epic z02s).

Single shared helper for turning a template's (possibly relative) art/icon value
into the final URL by prefixing the configured base URL. Used everywhere art URLs
are emitted — EPG `<icon>` (xmltv), Dispatcharr channel logos (lifecycle), fillers —
via the resolver's `resolve_art()`, so the reconstruction happens in exactly one place.
"""

import re

from teamarr.database.settings import get_epg_settings

_ABSOLUTE_URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


def apply_art_base_url(value: str | None, base_url: str) -> str | None:
    """Prefix a relative art/icon path with the configured base URL.

    Absolute URLs (anything with a ``scheme://``) and empty values pass through
    unchanged, so templates may mix full URLs and relative paths freely, and the
    function is idempotent (safe to apply more than once). When a base is set and
    the value is relative, they're joined with exactly one slash.
    """
    if not value:
        return value
    # Repair values corrupted by the v76 slash normalization (#275): a leading
    # slash in front of an absolute URL ("/https://…") — treat as absolute.
    stripped = value.lstrip("/")
    if _ABSOLUTE_URL.match(stripped):
        return stripped
    if not base_url:
        return value
    return f"{base_url.rstrip('/')}/{stripped}"


def read_art_base_url(db_factory) -> str:
    """Fetch the configured game-thumbs base URL once via a db_factory.

    Used by generation processors to inject the base into the EPG/filler/logo
    resolvers at construction. Returns "" on any failure (no prefixing).
    """
    try:

        with db_factory() as conn:
            return get_epg_settings(conn).art_base_url or ""
    except Exception:
        return ""
