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
_NUMBER = r"(?:0?[1-9]|[12][0-9]|3[01])"
_NUMERIC_DATE = (
    rf"(?:[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}|"
    rf"(?!24/7\b){_NUMBER}[./-]{_NUMBER}(?:[./-][0-9]{{4}})?)"
)
_DATE = rf"(?:{_NUMERIC_DATE}|{_MONTH}\s+{_NUMBER}|{_NUMBER}\s+{_MONTH})"
_LABEL = rf"(?:{_DAY}(?:\s+(?:{_DATE}|{_NUMBER}))?|{_DATE})"
_SUFFIX = re.compile(rf"(?:\s*\(\s*{_LABEL}\s*\)|\s*\[\s*{_LABEL}\s*\]|\s+{_LABEL})$")


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
