"""Matching constants for stream-to-event matching.

Contains hardcoded translations, aliases, and patterns that can't be solved
through fuzzy matching alone. Keep this minimal - prefer user-defined aliases
in the database when possible.
"""

# =============================================================================
# CITY NAME TRANSLATIONS
# ESPN uses English city names, but stream names may use native spellings.
# rapidfuzz won't match "München" to "Munich" - need explicit translations.
#
# Format: normalized_variant -> english_name
# All keys should be lowercase, already normalized (no accents via unidecode)
# =============================================================================

CITY_TRANSLATIONS: dict[str, str] = {
    # German cities
    "munchen": "munich",
    "koln": "cologne",
    "nurnberg": "nuremberg",
    "dusseldorf": "dusseldorf",  # Already English spelling
    "frankfurt": "frankfurt",
    "hannover": "hanover",
    "braunschweig": "brunswick",
    # Italian cities
    "milano": "milan",
    "roma": "rome",
    "napoli": "naples",
    "torino": "turin",
    "firenze": "florence",
    "venezia": "venice",
    "genova": "genoa",
    # Spanish cities
    "sevilla": "seville",
    # Brazilian cities (Portuguese)
    "sao paulo": "sao paulo",  # Keep as-is
    # Russian cities (transliterated)
    "moskva": "moscow",
    "sankt peterburg": "st petersburg",
    # Other
    "wien": "vienna",
    "praha": "prague",
    "warszawa": "warsaw",
    "kobenhavn": "copenhagen",
    "goteborg": "gothenburg",
}


# =============================================================================
# BUILT-IN TEAM NAME ALIASES
# Common abbreviations/nicknames that fuzzy matching won't catch.
# User-defined aliases in team_aliases table take precedence.
#
# Format: alias -> canonical_name
# All keys should be lowercase
# =============================================================================

TEAM_ALIASES: dict[str, str] = {
    # English Premier League
    "man u": "manchester united",
    "man utd": "manchester united",
    "man united": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham hotspur",
    "tottenham": "tottenham hotspur",
    "wolves": "wolverhampton wanderers",
    "west ham": "west ham united",
    "brighton": "brighton and hove albion",
    "newcastle": "newcastle united",
    "nottm forest": "nottingham forest",
    "nott forest": "nottingham forest",
    "nottingham": "nottingham forest",
    # German Bundesliga
    "bayern": "bayern munich",
    "bayern munchen": "bayern munich",
    "fc bayern": "bayern munich",
    "dortmund": "borussia dortmund",
    "bvb": "borussia dortmund",
    "gladbach": "borussia monchengladbach",
    "monchengladbach": "borussia monchengladbach",
    "leverkusen": "bayer leverkusen",
    "bayer 04": "bayer leverkusen",
    "leipzig": "rb leipzig",
    "rb leipzig": "rb leipzig",
    "frankfurt": "eintracht frankfurt",
    "wolfsburg": "vfl wolfsburg",
    # Spanish La Liga
    "barca": "barcelona",
    "real": "real madrid",
    "atletico": "atletico madrid",
    "atleti": "atletico madrid",
    "athletic": "athletic bilbao",
    "athletic club": "athletic bilbao",
    "sevilla fc": "sevilla",
    "real sociedad": "real sociedad",
    "villarreal cf": "villarreal",
    # Italian Serie A
    "inter": "inter milan",
    "inter milan": "internazionale",
    "ac milan": "milan",
    "juve": "juventus",
    "napoli": "ssc napoli",
    "lazio": "ss lazio",
    "roma": "as roma",
    "atalanta": "atalanta bc",
    "fiorentina": "acf fiorentina",
    # French Ligue 1
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "paris": "paris saint germain",
    "marseille": "olympique marseille",
    "om": "olympique marseille",
    "lyon": "olympique lyonnais",
    "ol": "olympique lyonnais",
    "monaco": "as monaco",
    "lille": "lille osc",
    # MLS
    "la galaxy": "los angeles galaxy",
    "galaxy": "los angeles galaxy",
    "lafc": "los angeles fc",
    "nycfc": "new york city fc",
    "nyc fc": "new york city fc",
    "nyrb": "new york red bulls",
    "ny red bulls": "new york red bulls",
    "atlanta": "atlanta united",
    "inter miami": "inter miami cf",
    "miami": "inter miami cf",
    "seattle": "seattle sounders",
    "sounders": "seattle sounders",
    "portland": "portland timbers",
    "timbers": "portland timbers",
    # NFL
    "pats": "new england patriots",
    "niners": "san francisco 49ers",
    "9ers": "san francisco 49ers",
    "philly": "philadelphia eagles",
    "big d": "dallas cowboys",
    # NBA
    "lakers": "los angeles lakers",
    "clippers": "la clippers",
    "knicks": "new york knicks",
    "nets": "brooklyn nets",
    "sixers": "philadelphia 76ers",
    "celts": "boston celtics",
    "dubs": "golden state warriors",
    "heat": "miami heat",
    # NHL
    "habs": "montreal canadiens",
    "leafs": "toronto maple leafs",
    "bruins": "boston bruins",
    "wings": "detroit red wings",
    "hawks": "chicago blackhawks",
    "pens": "pittsburgh penguins",
    "caps": "washington capitals",
    "bolts": "tampa bay lightning",
    "avs": "colorado avalanche",
    "canucks": "vancouver canucks",
    "oilers": "edmonton oilers",
    "flames": "calgary flames",
    "sens": "ottawa senators",
    "jets": "winnipeg jets",
    # MLB
    "yanks": "new york yankees",
    "bosox": "boston red sox",
    "redsox": "boston red sox",
    "whitesox": "chicago white sox",
    "dodgers": "los angeles dodgers",
    "cards": "st louis cardinals",
    "cards": "saint louis cardinals",
    "jays": "toronto blue jays",
}


# =============================================================================
# PROVIDER PREFIXES TO STRIP
# Stream names often start with provider identifiers that should be removed
# before matching. Order matters - longer prefixes first to avoid partial matches.
# =============================================================================

PROVIDER_PREFIXES: list[str] = [
    # Streaming services (with common suffixes)
    "espn+ ",
    "espn plus ",
    "espn+ - ",
    "espn +",
    "espn:",
    "espn -",
    "espn",
    "paramount+ ",
    "paramount+: ",
    "paramount plus ",
    "peacock ",
    "peacock: ",
    "max ",
    "max: ",
    "apple tv+ ",
    "apple tv ",
    "amazon prime ",
    "prime video ",
    "dazn ",
    "dazn: ",
    "fubo ",
    "fubotv ",
    "directv ",
    "directv stream ",
    # Sports networks
    "fox sports ",
    "fs1 ",
    "fs2 ",
    "fsn ",
    "nbc sports ",
    "nbcsn ",
    "cbs sports ",
    "tnt ",
    "tbs ",
    "usa network ",
    "nfl network ",
    "nba tv ",
    "nhl network ",
    "mlb network ",
    "bein sports ",
    "bein ",
    "sky sports ",
    "bt sport ",
    "tsn ",
    "sportsnet ",
    # Regional sports networks
    "nesn ",
    "msg ",
    "yes network ",
    "masn ",
    "root sports ",
    "bally sports ",
    "at&t sportsnet ",
    "altitude ",
]


# =============================================================================
# PLACEHOLDER PATTERNS
# Regex patterns that identify placeholder/filler streams with no event info.
# These streams should be classified as PLACEHOLDER and skipped.
# =============================================================================

PLACEHOLDER_PATTERNS: list[str] = [
    # Provider prefix + number with no event info
    r"^espn\+?\s*\d+\s*[-:]?\s*$",
    r"^dazn\s*\d+\s*[-:]?\s*$",
    r"^paramount\+?\s*\d+\s*[-:]?\s*$",
    # Generic numbered channels
    r"^channel\s*\d+\s*$",
    r"^ch\s*\d+\s*$",
    # "Coming Soon" / "TBD" / "TBA" patterns
    r"^coming\s+soon",
    r"^to\s+be\s+announced",
    r"^to\s+be\s+determined",
    r"^tba\s*$",
    r"^tbd\s*$",
    # Maintenance / Off-air
    r"^off\s*air",
    r"^no\s+signal",
    r"^please\s+stand\s+by",
    r"^technical\s+difficulties",
]


# =============================================================================
# GAME SEPARATORS
# Patterns that indicate a stream contains team vs team matchup.
# Used by classifier to determine stream category.
# Order: more specific patterns first
# =============================================================================

GAME_SEPARATORS: list[str] = [
    " vs. ",
    " vs ",
    " v. ",
    " v ",
    " @ ",
    " at ",
    " x ",  # Portuguese/Spanish style
    " contre ",  # French
    " gegen ",  # German
    " contra ",  # Spanish/Portuguese
]


# =============================================================================
# LEAGUE HINT PATTERNS
# Patterns to detect league from stream name for multi-league groups.
# Returns league_code if detected.
#
# Format: (pattern, league_code)
# Patterns are case-insensitive, checked in order
# =============================================================================

LEAGUE_HINT_PATTERNS: list[tuple[str, str]] = [
    # ==========================================================================
    # Major US/Canadian Pro Leagues
    # ==========================================================================
    (r"^nfl[:\s-]", "nfl"),
    (r"^nba[:\s-]", "nba"),
    (r"^nhl[:\s-]", "nhl"),
    (r"^mlb[:\s-]", "mlb"),
    (r"^mls[:\s-]", "usa.1"),
    (r"^wnba[:\s-]", "wnba"),
    (r"^nwsl[:\s-]", "usa.nwsl"),
    (r"^g[\s-]?league[:\s-]", "nba-development"),
    # ==========================================================================
    # US College Sports
    # ==========================================================================
    (r"^ncaaf[:\s-]", "college-football"),
    (r"^ncaam[:\s-]", "mens-college-basketball"),
    (r"^ncaaw[:\s-]", "womens-college-basketball"),
    (r"^ncaab[:\s-]", "mens-college-basketball"),  # Alternate abbreviation
    # ==========================================================================
    # Soccer / Football
    # ==========================================================================
    (r"^epl[:\s-]", "eng.1"),
    (r"^premier\s+league[:\s-]", "eng.1"),
    (r"^la\s+liga[:\s-]", "esp.1"),
    (r"^bundesliga[:\s-]", "ger.1"),
    (r"^serie\s+a[:\s-]", "ita.1"),
    (r"^ligue\s+1[:\s-]", "fra.1"),
    (r"^ucl[:\s-]", "uefa.champions"),
    (r"^champions\s+league[:\s-]", "uefa.champions"),
    (r"^spl[:\s-]", "ksa.1"),  # Saudi Pro League
    # ==========================================================================
    # Hockey (NHL, minor, junior, women's)
    # ==========================================================================
    (r"^pwhl[:\s-]", "pwhl"),
    (r"^ahl[:\s-]", "ahl"),
    (r"^ohl[:\s-]", "ohl"),
    (r"^whl[:\s-]", "whl"),
    (r"^qmjhl[:\s-]", "qmjhl"),
    (r"^ushl[:\s-]", "ushl"),
    # ==========================================================================
    # Combat Sports (event_card types)
    # ==========================================================================
    (r"\bufc\s*\d+", "ufc"),
    (r"\bufc\b", "ufc"),
    (r"\bfight\s+night\b", "ufc"),
    (r"\bboxing[:\s-]", "boxing"),
    (r"\bpbc[:\s-]", "boxing"),  # Premier Boxing Champions
    (r"\btop\s+rank\b", "boxing"),
    (r"\bmatchroom\b", "boxing"),
    # ==========================================================================
    # Cricket
    # ==========================================================================
    (r"\bipl[:\s-]", "ipl"),
    (r"\bcpl[:\s-]", "cpl"),
    (r"\bbbl[:\s-]", "bbl"),  # Big Bash League
    (r"\bsa20[:\s-]", "sa20"),
    # ==========================================================================
    # Lacrosse
    # ==========================================================================
    (r"\bnll[:\s-]", "nll"),
    (r"\bpll[:\s-]", "pll"),
    # ==========================================================================
    # Rugby
    # ==========================================================================
    (r"^nrl[:\s-]", "nrl"),
    (r"^super\s+rugby[:\s-]", "super-rugby"),
]


# =============================================================================
# EVENT CARD KEYWORDS
# Keywords that identify event card streams (UFC, boxing) within their league.
# Used by EventCardMatcher to validate streams.
# =============================================================================

EVENT_CARD_KEYWORDS: dict[str, list[str]] = {
    "ufc": [
        "ufc",
        "fight night",
        "ufc fn",
        "main card",
        "prelims",
        "early prelims",
        "dana white",
        "contender series",
        "dwcs",
    ],
    "boxing": [
        "boxing",
        "main event",
        "undercard",
        "pbc",
        "premier boxing",
        "top rank",
        "matchroom",
        "dazn boxing",
        "showtime boxing",
        "golden boy",
        "ppv",
        "pay per view",
    ],
}
