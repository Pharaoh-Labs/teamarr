"""Sport normalization utilities.

The `sports` table in the database is the single source of truth for:
- Valid sport codes
- Display names (e.g., "MMA" not "mma")

This module provides normalization logic to map external API sport names
(like "Ice Hockey", "Rugby League") to our canonical lowercase codes.
"""

# Map external API sport names to canonical codes
# This is normalization LOGIC, not data - handles how providers name sports
SPORT_ALIASES: dict[str, str] = {
    # ESPN formats
    "Soccer": "soccer",
    "Football": "football",
    "Basketball": "basketball",
    "Ice Hockey": "hockey",
    "Hockey": "hockey",
    "Baseball": "baseball",
    "Softball": "softball",
    "Lacrosse": "lacrosse",
    "Volleyball": "volleyball",
    "Rugby": "rugby",
    "Rugby League": "rugby",
    "Rugby Union": "rugby",
    "Cricket": "cricket",
    "Boxing": "boxing",
    "MMA": "mma",
    "Mixed Martial Arts": "mma",
    "Golf": "golf",
    "Tennis": "tennis",
    "Racing": "racing",
    "Auto Racing": "racing",
    "Wrestling": "wrestling",
    # Common variations
    "ice hockey": "hockey",
    "american football": "football",
    "gridiron": "football",
    "association football": "soccer",
    "fútbol": "soccer",
    "futbol": "soccer",
}


def normalize_sport(sport: str) -> str:
    """Normalize a sport name to canonical lowercase code.

    Maps external API sport names to our canonical codes using SPORT_ALIASES.
    Unknown sports are returned as lowercase.

    Args:
        sport: Sport name in any format (e.g., "Ice Hockey", "Soccer", "hockey")

    Returns:
        Canonical sport code (e.g., "hockey", "soccer")

    Examples:
        >>> normalize_sport("Ice Hockey")
        'hockey'
        >>> normalize_sport("Rugby League")
        'rugby'
        >>> normalize_sport("football")
        'football'
    """
    if not sport:
        return "unknown"

    # Check alias map (handles title case from APIs like "Ice Hockey")
    if sport in SPORT_ALIASES:
        return SPORT_ALIASES[sport]

    # Check lowercase in aliases
    lower = sport.lower().strip()
    if lower in SPORT_ALIASES:
        return SPORT_ALIASES[lower]

    # Return as lowercase (may or may not be a valid sport in DB)
    return lower


# Sport naming (#691): the seeded display names use US vocabulary. The
# "international" mode relabels the two sports whose names differ; every
# other sport keeps its seeded display name. Applied in ONE place —
# get_sport_display_names_from_db — so templates ({sport}), the {sport}
# Dispatcharr group wildcard, and every UI label inherit it. Matching keywords
# and product vocabulary ("soccer mode", starter template names) are untouched.
SPORT_NAMING_MODES: frozenset[str] = frozenset({"us", "international"})
SPORT_NAMING_OVERRIDES: dict[str, dict[str, str]] = {
    "international": {"soccer": "Football", "football": "American Football"},
}


def apply_sport_naming(names: dict[str, str], mode: str | None) -> dict[str, str]:
    """Return ``names`` with the naming-mode overrides applied (a new dict)."""
    overrides = SPORT_NAMING_OVERRIDES.get(mode or "us", {})
    if not overrides:
        return dict(names)
    return {code: overrides.get(code, name) for code, name in names.items()}


def get_sport_naming_mode(conn) -> str:
    """Read the sport naming mode from settings; 'us' when unset or pre-column."""
    try:
        row = conn.execute("SELECT sport_naming FROM settings WHERE id = 1").fetchone()
    except Exception:  # settings table/column absent (bare test DBs)
        return "us"
    mode = row[0] if row else None
    return mode if mode in SPORT_NAMING_MODES else "us"


def get_sport_display_names_from_db(conn) -> dict[str, str]:
    """Get all sport display names from database, with sport naming applied.

    Args:
        conn: Database connection

    Returns:
        Dict mapping sport_code to display_name
    """
    cursor = conn.execute("SELECT sport_code, display_name FROM sports")
    names = {row["sport_code"]: row["display_name"] for row in cursor.fetchall()}
    return apply_sport_naming(names, get_sport_naming_mode(conn))
