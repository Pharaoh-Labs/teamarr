"""Constants for the matching module.

Algorithm tuning constants for stream-to-event matching.
For pattern/alias data, see teamarr/utilities/constants.py
"""

# How far back to search for events when matching streams.
# Allows matching streams for recently-finished events (for stats tracking).
# The lifecycle layer filters out past events after matching.
MATCH_WINDOW_DAYS = 30

# Longest near-miss explanation persisted on a failed match (#661). It rides in
# every support bundle at up to 500 failure rows per run, so it is capped to
# keep the archive bounded; the informative half (best candidate + both scores)
# comes first, so a truncation loses only the alias/date tail.
NEAR_MISS_DETAIL_MAX = 400

# =============================================================================
# CONFIDENCE THRESHOLDS
# Fuzzy match score thresholds that control when matches are accepted.
# =============================================================================

# Accept match without requiring date/time validation
HIGH_CONFIDENCE_THRESHOLD = 85.0

# Accept match only if date/time in stream name validates against event
ACCEPT_WITH_DATE_THRESHOLD = 75.0

# Both-teams matching threshold - lower because min() of two scores is strict
# e.g., "William Jessup" vs "Jessup Warriors" scores ~62%, combined with
# "Sacred Heart" vs "Sacred Heart Pioneers" (~100%) gives min(62, 100) = 62
BOTH_TEAMS_THRESHOLD = 60.0

# =============================================================================
# SHORT TEAM CODES (#472)
# =============================================================================

# A stream team string this short is an abbreviation, not a name. Fuzzy
# token matching is pathological on codes: token_set_ratio("sea",
# "portland sea dogs") = 100 because "Sea" is a literal word of the name,
# while the real Seattle Mariners score only 32. Short codes therefore
# match ONLY by abbreviation equality (plus the alternates below).
SHORT_CODE_MAX_LEN = 3

# Well-known alternate codes -> the provider's cached abbreviation
# (normalized lowercase both sides). Covers official rebrands and
# Baseball-Reference-style forms that IPTV stream names commonly use but
# ESPN data doesn't. Deliberately tiny and unambiguous — "LA" is NOT here
# (Dodgers vs Angels); user aliases cover genuinely ambiguous codes.
ALTERNATE_TEAM_CODES: dict[str, str] = {
    "az": "ari",  # Arizona Diamondbacks official rebrand; ESPN keeps ARI
    "cws": "chw",  # MLB.com White Sox code; ESPN uses CHW
    "sfg": "sf",  # Baseball-Reference forms of ESPN codes
    "sdp": "sd",
    "tbr": "tb",
    "kcr": "kc",
    "wsn": "wsh",
}
