"""NFHS provider configuration."""

SEARCH_API_BASE = "https://search-api.nfhsnetwork.com/v3"
CFUNITY_API_BASE = "https://cfunity.nfhsnetwork.com/v2"


# Provider behavior flags
VARSITY_ONLY = True
INCLUDE_NON_VARSITY = False

# Optional state filter for testing (None = all states)
STATE_FILTER = {"KY"}

# Optional: limit supported sports initially
SUPPORTED_SPORTS = {
    "Football",
    "Basketball",
    "Soccer",
    "Baseball",
    "Softball",
    "Volleyball",
    "Lacrosse",
    "Field Hockey",
    "Swimming"
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
    ("Basketball", "boys"): "hs-basketball-boys",
    ("Basketball", "girls"): "hs-basketball-girls",
    ("Soccer", "boys"): "hs-soccer-boys",
    ("Soccer", "girls"): "hs-soccer-girls",
    ("Baseball", None): "hs-baseball",
    ("Softball", "girls"): "hs-softball",
    ("Volleyball", "boys"): "hs-volleyball-boys",
    ("Volleyball", "girls"): "hs-volleyball-girls",
    ("Lacrosse", "boys"): "hs-lacrosse-boys",
    ("Lacrosse", "girls"): "hs-lacrosse-girls",
    ("Field Hockey", "girls"): "hs-field-hockey",
    ("Swimming", "boys"): "hs-swimming-boys",
    ("Swimming", "girls"): "hs-swimming-girls"
}

# Some NFHS events report capitalization inconsistently
GENDER_NORMALIZATION = {
    "boys": "boys",
    "Boys": "boys",
    "girls": "girls",
    "Girls": "girls",
}

LEVEL_NORMALIZATION = {
    "Varsity": "Varsity",
    "varsity": "Varsity",
    "Junior Varsity": "Junior Varsity",
    "junior varsity": "Junior Varsity",
    "JV": "Junior Varsity",
}

SPORT_NORMALIZATION = {
    "Football": "Football",
    "Basketball": "Basketball",
    "Soccer": "Soccer",
    "Baseball": "Baseball",
    "Softball": "Softball",
    "Volleyball": "Volleyball",
    "Lacrosse": "Lacrosse",
    "Field Hockey": "Field Hockey",
    "Flag Football": "Flag Football",
    "Ice Hockey": "Ice Hockey",
    "Swimming": "Swimming",
}

# Default HTTP settings for NFHS client
REQUEST_TIMEOUT = 15
USER_AGENT = "Teamarr-NFHS-Provider/1.0"