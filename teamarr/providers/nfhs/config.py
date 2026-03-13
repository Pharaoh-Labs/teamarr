"""NFHS provider configuration."""

SEARCH_API_BASE = "https://search-api.nfhsnetwork.com/v3"
CFUNITY_API_BASE = "https://cfunity.nfhsnetwork.com/v2"


# Provider behavior flags
VARSITY_ONLY = True
INCLUDE_NON_VARSITY = False

# Optional state filter for testing / fallback.
# Keep empty by default so NFHS is disabled unless states are explicitly configured.
STATE_FILTER: set[str] = set()

# Optional: limit supported sports initially
SUPPORTED_SPORTS = {
    "Baseball",
    "Basketball",
    "Bowling",
    "Cheer",
    "Cross Country",
    "Field Hockey",
    "Flag Football",
    "Football",
    "Golf",
    "Gymnastics",
    "Ice Hockey",
    "Lacrosse",
    "Soccer",
    "Softball",
    "Swimming",
    "Tennis",
    "Track & Field",
    "Volleyball",
    "Water Polo",
    "Wrestling",
}

# Levels we will ingest from NFHS (Phase 1: varsity only)
SUPPORTED_LEVELS = {
    "Varsity",
}

# Content/status filtering
SUPPORTED_CONTENT_TYPES = {"game"}
SUPPORTED_STATUSES = {"scheduled", "live", "in_progress"}

# Event discovery tuning
EVENT_PAGE_SIZE = 100
MAX_PAGES = 20
MAX_CONNECTIONS = 20
RETRY_COUNT = 3

# Canonical league mapping used by the NFHS provider
# Key = (sport, gender)
LEAGUE_MAP = {
    ("Football", "boys"): "hs-football",
    ("Football", None): "hs-football",
    ("Basketball", "boys"): "hs-basketball-boys",
    ("Basketball", "girls"): "hs-basketball-girls",
    ("Basketball", None): "hs-basketball",
    ("Soccer", "boys"): "hs-soccer-boys",
    ("Soccer", "girls"): "hs-soccer-girls",
    ("Soccer", None): "hs-soccer",
    ("Baseball", None): "hs-baseball",
    ("Softball", "girls"): "hs-softball",
    ("Softball", None): "hs-softball",
    ("Volleyball", "boys"): "hs-volleyball-boys",
    ("Volleyball", "girls"): "hs-volleyball-girls",
    ("Volleyball", None): "hs-volleyball",
    ("Lacrosse", "boys"): "hs-lacrosse-boys",
    ("Lacrosse", "girls"): "hs-lacrosse-girls",
    ("Lacrosse", None): "hs-lacrosse",
    ("Field Hockey", "girls"): "hs-field-hockey",
    ("Field Hockey", None): "hs-field-hockey",
    ("Swimming", "boys"): "hs-swimming-boys",
    ("Swimming", "girls"): "hs-swimming-girls",
    ("Swimming", None): "hs-swimming",
    ("Cross Country", "boys"): "hs-cross-country-boys",
    ("Cross Country", "girls"): "hs-cross-country-girls",
    ("Cross Country", None): "hs-cross-country",
    ("Golf", "boys"): "hs-golf-boys",
    ("Golf", "girls"): "hs-golf-girls",
    ("Golf", None): "hs-golf",
    ("Tennis", "boys"): "hs-tennis-boys",
    ("Tennis", "girls"): "hs-tennis-girls",
    ("Tennis", None): "hs-tennis",
    ("Track & Field", "boys"): "hs-track-field-boys",
    ("Track & Field", "girls"): "hs-track-field-girls",
    ("Track & Field", None): "hs-track-field",
    ("Wrestling", "boys"): "hs-wrestling-boys",
    ("Wrestling", "girls"): "hs-wrestling-girls",
    ("Wrestling", None): "hs-wrestling",
    ("Bowling", "boys"): "hs-bowling-boys",
    ("Bowling", "girls"): "hs-bowling-girls",
    ("Bowling", None): "hs-bowling",
    ("Cheer", "girls"): "hs-cheer",
    ("Cheer", None): "hs-cheer",
    ("Flag Football", "girls"): "hs-flag-football-girls",
    ("Flag Football", "boys"): "hs-flag-football-boys",
    ("Flag Football", None): "hs-flag-football",
    ("Gymnastics", "girls"): "hs-gymnastics",
    ("Gymnastics", None): "hs-gymnastics",
    ("Ice Hockey", "boys"): "hs-ice-hockey-boys",
    ("Ice Hockey", "girls"): "hs-ice-hockey-girls",
    ("Ice Hockey", None): "hs-ice-hockey",
    ("Water Polo", "boys"): "hs-water-polo-boys",
    ("Water Polo", "girls"): "hs-water-polo-girls",
    ("Water Polo", None): "hs-water-polo",
}

# Some NFHS events report capitalization inconsistently
GENDER_NORMALIZATION = {
    "boys": "boys",
    "Boys": "boys",
    "girls": "girls",
    "Girls": "girls",
    "Coed": None,
    "Mixed": None,
}

LEVEL_NORMALIZATION = {
    "Varsity": "Varsity",
    "varsity": "Varsity",
    "Junior Varsity": "Junior Varsity",
    "junior varsity": "Junior Varsity",
    "JV": "Junior Varsity",
}

SPORT_NORMALIZATION = {
    "Baseball": "Baseball",
    "Basketball": "Basketball",
    "Bowling": "Bowling",
    "Cheer": "Cheer",
    "Cheerleading": "Cheer",
    "Cheerleading and Dance": "Cheer",
    "Competitive Cheer": "Cheer",
    "Spirit": "Cheer",
    "Cross Country": "Cross Country",
    "Football": "Football",
    "Flag Football": "Flag Football",
    "Field Hockey": "Field Hockey",
    "Golf": "Golf",
    "Gymnastics": "Gymnastics",
    "Ice Hockey": "Ice Hockey",
    "Lacrosse": "Lacrosse",
    "Soccer": "Soccer",
    "Softball": "Softball",
    "Swimming": "Swimming",
    "Swimming & Diving": "Swimming",
    "Tennis": "Tennis",
    "Track & Field": "Track & Field",
    "Track & Field/Cross Country": "Track & Field",
    "Track and Field": "Track & Field",
    "Volleyball": "Volleyball",
    "Water Polo": "Water Polo",
    "Wrestling": "Wrestling",
}

# Default HTTP settings for NFHS client
REQUEST_TIMEOUT = 15
USER_AGENT = "Teamarr-NFHS-Provider/1.0"