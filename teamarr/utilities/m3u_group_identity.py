"""Identity of provider M3U groups with a trailing day or date label."""

import re
import unicodedata

_DAY = (
    r"(?:mon(?:day)?|tue(?:s|sday)?|wed(?:s|nesday)?|thu(?:r|rs|rsday)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
)
_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_MONTH_NUM = r"(?:0?[1-9]|1[0-2])"
_DAY_NUM = r"(?:0?[1-9]|[12][0-9]|3[01])"
_ISO_DATE = r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
_MD_SLASH_DOT = (
    rf"(?!24[./]7\b)(?:{_MONTH_NUM}[./]{_DAY_NUM}|{_DAY_NUM}[./]{_MONTH_NUM})"
    rf"(?:[./][0-9]{{4}})?"
)
_MD_DASH_FULL = rf"(?:{_MONTH_NUM}-{_DAY_NUM}|{_DAY_NUM}-{_MONTH_NUM})-[0-9]{{4}}"
_MD_DASH_SHORT = rf"(?!24-7\b)(?:{_MONTH_NUM}-{_DAY_NUM}|{_DAY_NUM}-{_MONTH_NUM})"
_BARE_DATE = (
    rf"(?:{_ISO_DATE}|{_MD_SLASH_DOT}|{_MD_DASH_FULL}|"
    rf"{_MONTH}\s+{_DAY_NUM}|{_DAY_NUM}\s+{_MONTH})"
)
_BRACKET_DATE = rf"(?:{_BARE_DATE}|{_MD_DASH_SHORT})"
_BARE_LABEL = rf"(?:{_DAY}(?:\s+(?:{_BRACKET_DATE}|{_DAY_NUM}))?|{_BARE_DATE})"
_BRACKET_LABEL = rf"(?:{_DAY}(?:\s+(?:{_BRACKET_DATE}|{_DAY_NUM}))?|{_BRACKET_DATE})"
_SUFFIX = re.compile(
    rf"(?:\s*\(\s*{_BRACKET_LABEL}\s*\)|\s*\[\s*{_BRACKET_LABEL}\s*\]|\s+{_BARE_LABEL})$"
)


def name_key(text: str) -> str:
    """Lower-case ASCII words, for whole-word comparison of names."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9+]+", " ", folded).strip()


def rotating_group_key(name: str) -> str | None:
    """Return a shared key only for names with a recognized rotating suffix.

    Ordinary groups retain their ID-based identity. Keep provider prefixes and
    qualifiers such as HD, Replay and Preseason in the base name.
    """
    base, stripped = _SUFFIX.subn("", unicodedata.normalize("NFKC", name).lower().strip())
    return (name_key(base) or None) if stripped else None
