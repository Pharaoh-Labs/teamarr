"""Template `|filter` modifiers (#478, #484).

Filters are opt-in value transforms applied after a variable resolves:
``{team_name|pascal}`` -> ``DetroitTigers``. They chain left-to-right
(``{team_name|pascal|urlencode}``). An unknown filter keeps the whole token
literal so the author can spot the typo.

Filters are TRANSFORMS ONLY — semantic variants (``_abbrev``, ``_short``)
stay variables. The registry here must stay in lockstep with the frontend
preview registry (``TEMPLATE_FILTERS`` in
``frontend/src/pages/template-form/constants.ts``) — enforced by
``tests/templates/test_filter_parity.py``.
"""

import re
import unicodedata
from collections.abc import Callable
from urllib.parse import quote


def _ascii_fold(value: str) -> str:
    """Normalize accents to ASCII (é -> e); characters with no ASCII
    decomposition are dropped, matching the long-standing pascal-variable
    behavior."""
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def filter_urlencode(value: str) -> str:
    """Percent-encode a resolved value for safe use inside a URL (#478).

    Encodes every reserved character (space, ``&``, ``=``, ``?``, ``/`` …) so a
    value interpolated into an art/poster URL query string — e.g. game-thumbs
    ``/f1/cover?title={race_name|urlencode}`` — survives a value containing
    spaces or ``&`` instead of truncating the URL.
    """
    return quote(value or "", safe="")


def filter_lower(value: str) -> str:
    """Lowercase: ``DET`` -> ``det``."""
    return (value or "").lower()


def filter_upper(value: str) -> str:
    """Uppercase: ``Qualifying`` -> ``QUALIFYING``."""
    return (value or "").upper()


def filter_title(value: str) -> str:
    """Capitalize each word: ``ice hockey`` -> ``Ice Hockey``.

    Word-run based (each alphabetic run capitalized, rest lowered) rather than
    ``str.title()`` so apostrophes behave (``o'neill`` -> ``O'Neill``) and the
    frontend preview can replicate it exactly.
    """
    return re.sub(
        r"[A-Za-z]+",
        lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(),
        value or "",
    )


def filter_pascal(value: str) -> str:
    """PascalCase for channel IDs: ``Detroit Tigers`` -> ``DetroitTigers``.

    Identical to the retired ``*_pascal`` variables' transform: accents
    normalized, split on non-alphanumeric, each word capitalized.
    ``D.C. United`` -> ``DcUnited``.
    """
    words = re.split(r"[^a-zA-Z0-9]+", _ascii_fold(value or ""))
    return "".join(word.capitalize() for word in words if word)


def filter_slug(value: str) -> str:
    """URL/identifier slug: ``St. Louis Cardinals`` -> ``st-louis-cardinals``.

    Accents normalized, lowercased, non-alphanumeric runs collapse to a single
    hyphen, no leading/trailing hyphens.
    """
    folded = _ascii_fold(value or "").lower()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


# Registry of `|filter` modifiers usable in templates. Opt-in by design so
# variables that legitimately hold full URLs are never encoded unless asked.
FILTERS: dict[str, Callable[[str], str]] = {
    "urlencode": filter_urlencode,
    "url": filter_urlencode,  # short alias
    "lower": filter_lower,
    "upper": filter_upper,
    "title": filter_title,
    "pascal": filter_pascal,
    "slug": filter_slug,
}
