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
    # NFHS sports
    "Bowling": "bowling",
    "Cheer": "cheer",
    "Cheerleading": "cheer",
    "Cheerleading and Dance": "cheer",
    "Competitive Cheer": "cheer",
    "Spirit": "cheer",
    "Cross Country": "cross_country",
    "Field Hockey": "field_hockey",
    "Flag Football": "flag_football",
    "Gymnastics": "gymnastics",
    "Swimming": "swimming",
    "Swimming & Diving": "swimming",
    "Track & Field": "track_and_field",
    "Track and Field": "track_and_field",
    "Track & Field/Cross Country": "track_and_field",
    "Water Polo": "water_polo",
    # Common variations
    "ice hockey": "hockey",
    "american football": "football",
    "gridiron": "football",
    "association football": "soccer",
    "fútbol": "soccer",
    "futbol": "soccer",
    # NFHS lowercase/common variations
    "cheerleading": "cheer",
    "cheerleading and dance": "cheer",
    "competitive cheer": "cheer",
    "spirit": "cheer",
    "cross country": "cross_country",
    "field hockey": "field_hockey",
    "flag football": "flag_football",
    "swimming": "swimming",
    "swimming & diving": "swimming",
    "track & field": "track_and_field",
    "track and field": "track_and_field",
    "track & field/cross country": "track_and_field",
    "water polo": "water_polo",
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


def get_sport_display_names_from_db(conn) -> dict[str, str]:
    """Get all sport display names from database.

    Args:
        conn: Database connection

    Returns:
        Dict mapping sport_code to display_name
    """
    cursor = conn.execute("SELECT sport_code, display_name FROM sports")
    return {row["sport_code"]: row["display_name"] for row in cursor.fetchall()}
