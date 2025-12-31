#!/usr/bin/env python3
"""
Hybrid Matching Engine Prototype

Tests the proposed architecture:
1. Alias Lookup (instant, highest priority)
2. Semantic Matching (FAISS embeddings)
3. Fuzzy Matching (rapidfuzz with proper algorithms)

With V1's normalization pipeline ported.

Run: python experiments/hybrid_matching_prototype.py
"""

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# V1 NORMALIZATION PIPELINE (Ported)
# =============================================================================

# Mojibake patterns (UTF-8 bytes decoded as Latin-1)
MOJIBAKE_PATTERNS = [
    ('Ã©', 'é'), ('Ã¨', 'è'), ('Ã±', 'ñ'), ('Ã¼', 'ü'),
    ('Ã¶', 'ö'), ('Ã¤', 'ä'), ('Ã³', 'ó'), ('Ã¡', 'á'),
    ('Ã­', 'í'), ('Ãº', 'ú'), ('Ã§', 'ç'), ('Ã£', 'ã'),
    ('Ãµ', 'õ'), ('Ã', 'Á'),
]

# City/team name variants → ESPN canonical form
CITY_NAME_VARIANTS = {
    # ESPN uses ENGLISH for these German cities
    'münchen': 'munich', 'munchen': 'munich',
    'köln': 'cologne', 'koln': 'cologne',
    # ESPN uses GERMAN for these
    'nuremberg': 'nürnberg', 'nurnberg': 'nürnberg',
    'dusseldorf': 'düsseldorf', 'furth': 'fürth',
    'monchengladbach': 'mönchengladbach',
    # Team name variants
    'hertha bsc': 'hertha berlin',  # Don't expand bare 'hertha' - causes double replacement
    'hamburger sv': 'hamburg sv',
    'inter milan': 'internazionale', 'inter': 'internazionale',
    'atletico madrid': 'atlético madrid',
    'paris sg': 'paris saint-germain', 'psg': 'paris saint-germain',
    # Common English nicknames → full names
    'man u': 'manchester united', 'man utd': 'manchester united',
    'mufc': 'manchester united', 'man united': 'manchester united',
    'man city': 'manchester city', 'mcfc': 'manchester city',
    'spurs': 'tottenham', 'thfc': 'tottenham',
    'gunners': 'arsenal', 'afc': 'arsenal',
    'the reds': 'liverpool', 'lfc': 'liverpool',
    'chelsea fc': 'chelsea', 'cfc': 'chelsea',
    'wolves': 'wolverhampton',
    # US sports nicknames
    'niners': 'san francisco 49ers', '9ers': 'san francisco 49ers', '49ers': 'san francisco 49ers',
    'magic': 'orlando magic',  # Disambiguate from Osceola Magic
    'pats': 'new england patriots', 'patriots': 'new england patriots',
    'pack': 'green bay packers', 'packers': 'green bay packers',
    'boys': 'dallas cowboys', 'cowboys': 'dallas cowboys',
    'bolts': 'los angeles chargers',
    'fins': 'miami dolphins',
    'birds': 'philadelphia eagles',
    # College
    'bama': 'alabama', 'roll tide': 'alabama',
    'dawgs': 'georgia', 'bulldogs': 'georgia',
    'noles': 'florida state',
    'canes': 'miami',
    'ducks': 'oregon',
}

# US state codes to preserve in parentheticals
US_STATE_CODES = frozenset({
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC',
})

# Matchup separators
SEPARATORS = [' vs. ', ' vs ', ' at ', ' @ ', ' v. ', ' v ', ' x ']


def fix_mojibake(text: str) -> str:
    """Fix UTF-8 mojibake (double-encoding)."""
    for wrong, right in MOJIBAKE_PATTERNS:
        text = text.replace(wrong, right)
    return text


def mask_times(text: str) -> tuple[str, list[str]]:
    """Mask time patterns to prevent colon confusion."""
    masked_times = []

    # 12-hour with minutes (8:15pm, 8:15 PM ET)
    def mask_12h(match):
        masked_times.append(match.group(0))
        return ' ' * len(match.group(0))

    text = re.sub(
        r'(?<!\d)(\d{1,2}):(\d{2})\s*(am|pm)(\s*(et|est|pt|pst|ct|cst|mt|mst))?',
        mask_12h, text, flags=re.IGNORECASE
    )

    # Hour-only (12pm, 4pm)
    text = re.sub(
        r'\b(\d{1,2})(am|pm)\b',
        lambda m: (masked_times.append(m.group(0)), ' ' * len(m.group(0)))[1],
        text, flags=re.IGNORECASE
    )

    # 24-hour (18:00)
    def mask_24h(match):
        time_str = match.group(0)
        parts = time_str.split(':')
        if len(parts) == 2:
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h < 24 and 0 <= m < 60:
                masked_times.append(time_str)
                return ' ' * len(time_str)
        return time_str

    text = re.sub(r'\b(\d{2}:\d{2})\b', mask_24h, text)

    return text, masked_times


def normalize_stream_name(text: str) -> str:
    """
    Full V1-style normalization pipeline.

    1. Fix mojibake
    2. Strip provider prefixes
    3. Mask times
    4. Strip metadata prefix (at colon)
    5. Strip dates, rankings, channel numbers
    6. Remove non-state parentheticals
    7. Apply city/team variants
    8. Normalize whitespace
    """
    if not text:
        return ""

    # Step 1: Fix mojibake
    text = fix_mojibake(text)

    # Step 2: Strip provider prefixes
    text = re.sub(r'^\(?\s*(uk|us|usa|ca|au)\s*\)?[\s|:]*', '', text, flags=re.I)
    text = re.sub(r'\([^)]*(?:sky|dazn|peacock|tsn|sportsnet|espn|fox|nbc|cbs|abc)[^)]*\)', '', text, flags=re.I)
    text = re.sub(r'(nfl|nba|nhl|mlb|ncaa[mfwb]?|soccer|epl|mls)\s+on\s+\w+\s*:?\s*', '', text, flags=re.I)
    text = re.sub(r'^(ncaa[mfwb]?|college)\s*(basketball|football|hockey)?\s*:?\s*', '', text, flags=re.I)
    # Language prefixes
    text = re.sub(r'^en\s+espa[ñn]ol[-:\s]*', '', text, flags=re.I)

    # Step 3: Mask times
    masked_text, _ = mask_times(text)

    # Step 4: Strip metadata prefix at colon (using masked text for detection)
    # Find colon in masked text, strip from original
    colon_pos = masked_text.find(':')
    if colon_pos > 0 and colon_pos < len(text) - 1:
        # Only strip if there's content after the colon
        text = text[colon_pos + 1:]

    # Step 5: Lowercase
    text = text.lower()

    # Step 6: Strip dates
    text = re.sub(r'\d{1,2}/\d{1,2}(/\d{2,4})?\s*', '', text)
    text = re.sub(r'\d{4}-\d{2}-\d{2}\s*', '', text)
    text = re.sub(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s*\d{1,2}\s*', '', text, flags=re.I)
    text = re.sub(r'\d{1,2}\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s*', '', text, flags=re.I)

    # Step 7: Strip rankings (but NOT team names like "49ers", "76ers")
    # Only strip if number is followed by space and letter (not "ers", "s", etc.)
    text = re.sub(r'#\d{1,2}\s+(?=[a-z])', '', text)  # Only with # prefix

    # Step 8: Strip channel numbers (require separator after digits)
    text = re.sub(r'\|\s*\d+\s*[-:]?\s*', '', text)
    # Only strip leading digits if followed by separator (not "49ers")
    text = re.sub(r'^\d+\s*[-:]\s*', '', text)  # Require - or :

    # Step 9: Strip suffix after | or @ (date/time info)
    text = re.sub(r'\s*[@|]\s*(?:dec|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov).*$', '', text, flags=re.I)
    text = re.sub(r'\s*[@|]\s*\d{1,2}.*$', '', text)  # "@ 07 pm et" type suffixes
    text = re.sub(r'\s*\([^)]*\)\s*$', '', text)  # Trailing parentheticals
    # Strip any remaining time suffixes
    text = re.sub(r'\s+\d{1,2}\s*(am|pm)\s*(et|est|pt|pst|ct|cst)?\s*$', '', text, flags=re.I)

    # Step 10: Remove non-state parentheticals
    def remove_non_state(match):
        content = match.group(1).strip().upper()
        return match.group(0) if content in US_STATE_CODES else ''
    text = re.sub(r'\(([^)]*)\)', remove_non_state, text)

    # Step 11: Normalize special chars
    text = text.replace('`', "'").replace('_', ' ')
    text = re.sub(r'[|:\-#\[\]]+', ' ', text)
    text = re.sub(r'\.(?!\d)', '', text)  # Remove periods (not in numbers)

    # Step 12: Apply city/team variants
    for variant, canonical in sorted(CITY_NAME_VARIANTS.items(), key=lambda x: len(x[0]), reverse=True):
        pattern = r'\b' + re.escape(variant) + r'\b'
        text = re.sub(pattern, canonical, text, flags=re.I)

    # Step 13: Normalize whitespace
    text = ' '.join(text.split())

    return text.strip()


def extract_teams(normalized: str) -> tuple[str, str] | None:
    """Extract away/home teams from normalized text."""
    for sep in SEPARATORS:
        if sep in normalized:
            parts = normalized.split(sep, 1)
            if len(parts) == 2:
                away = parts[0].strip()
                home = parts[1].strip()
                if away and home:
                    return (away, home)
    return None


# =============================================================================
# TEAM DATABASE
# =============================================================================

@dataclass
class TeamEntry:
    """Team with name variants for matching."""
    id: str
    name: str
    short_name: str | None
    abbreviation: str | None
    league: str

    # Computed
    primary_names: list[str] = field(default_factory=list)
    secondary_names: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Build search name lists."""
        seen = set()

        # Primary: full name, short name, abbreviation
        for val in [self.name, self.short_name, self.abbreviation]:
            if val:
                lower = val.lower().strip()
                if lower and lower not in seen and len(lower) >= 2:
                    seen.add(lower)
                    self.primary_names.append(lower)

        # Secondary: location only (first word(s) before last word)
        if self.name:
            words = self.name.lower().split()
            if len(words) > 1:
                location = ' '.join(words[:-1])  # All but last word
                if location not in seen and len(location) >= 3:
                    self.secondary_names.append(location)


def load_teams() -> list[TeamEntry]:
    """Load teams from database."""
    db_path = Path(__file__).parent.parent / "data" / "teamarr.db"

    if not db_path.exists():
        print("Database not found, using synthetic data")
        return get_synthetic_teams()

    conn = sqlite3.connect(db_path)
    cursor = conn.execute("""
        SELECT provider_team_id, team_name, team_short_name, team_abbrev, league
        FROM team_cache
    """)

    teams = []
    for row in cursor:
        teams.append(TeamEntry(
            id=row[0],
            name=row[1],
            short_name=row[2],
            abbreviation=row[3],
            league=row[4],
        ))

    conn.close()
    print(f"Loaded {len(teams)} teams from database")
    return teams


def get_synthetic_teams() -> list[TeamEntry]:
    """Synthetic teams for testing without database."""
    data = [
        ("man_utd", "Manchester United", "Man United", "MUFC", "eng.1"),
        ("chelsea", "Chelsea", "Chelsea", "CHE", "eng.1"),
        ("liverpool", "Liverpool", "Liverpool", "LIV", "eng.1"),
        ("arsenal", "Arsenal", "Arsenal", "ARS", "eng.1"),
        ("tottenham", "Tottenham Hotspur", "Spurs", "TOT", "eng.1"),
        ("man_city", "Manchester City", "Man City", "MCI", "eng.1"),
        ("bayern", "Bayern Munich", "Bayern", "FCB", "ger.1"),
        ("dortmund", "Borussia Dortmund", "Dortmund", "BVB", "ger.1"),
        ("hertha", "Hertha Berlin", "Hertha", "BSC", "ger.2"),
        ("cologne", "Cologne", "Köln", "KOE", "ger.1"),
        ("heat", "Miami Heat", "Heat", "MIA", "nba"),
        ("magic", "Orlando Magic", "Magic", "ORL", "nba"),
        ("bulls", "Chicago Bulls", "Bulls", "CHI", "nba"),
        ("49ers", "San Francisco 49ers", "49ers", "SF", "nfl"),
        ("seahawks", "Seattle Seahawks", "Seahawks", "SEA", "nfl"),
        ("chiefs", "Kansas City Chiefs", "Chiefs", "KC", "nfl"),
        ("perth", "Perth Glory", "Perth", "PER", "aus.1"),
        ("wellington", "Wellington Phoenix", "Wellington", "WEL", "aus.1"),
        ("alabama", "Alabama Crimson Tide", "Alabama", "ALA", "ncaaf"),
        ("georgia", "Georgia Bulldogs", "Georgia", "UGA", "ncaaf"),
    ]
    return [TeamEntry(*d) for d in data]


# =============================================================================
# MATCHING ENGINES
# =============================================================================

class AliasLookup:
    """Fast alias-based lookup (V1 style)."""

    def __init__(self, teams: list[TeamEntry]):
        # Build reverse index: alias → team
        self.alias_map: dict[str, TeamEntry] = {}

        for team in teams:
            for name in team.primary_names + team.secondary_names:
                if name not in self.alias_map:
                    self.alias_map[name] = team

        # Add explicit aliases from CITY_NAME_VARIANTS
        # (These map nicknames to canonical names that should be in alias_map)
        self.nickname_map = CITY_NAME_VARIANTS

        print(f"AliasLookup: {len(self.alias_map)} direct aliases")

    def find(self, query: str) -> tuple[TeamEntry | None, float, str]:
        """Find team by exact alias match.

        Returns: (team, score, method)
        """
        query_lower = query.lower().strip()

        # Direct alias match
        if query_lower in self.alias_map:
            return (self.alias_map[query_lower], 100.0, "alias_exact")

        # Nickname expansion then alias match
        if query_lower in self.nickname_map:
            expanded = self.nickname_map[query_lower]
            if expanded in self.alias_map:
                return (self.alias_map[expanded], 100.0, "alias_nickname")

        return (None, 0.0, "")


class SemanticMatcher:
    """Semantic matching using sentence-transformers + FAISS."""

    def __init__(self, teams: list[TeamEntry], model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        import faiss
        import numpy as np

        self.model = SentenceTransformer(model_name)
        self.faiss = faiss
        self.np = np

        # Build index
        self.teams = teams
        self.team_for_idx: list[TeamEntry] = []
        self.name_for_idx: list[str] = []

        texts = []
        for team in teams:
            for name in team.primary_names:
                texts.append(name)
                self.team_for_idx.append(team)
                self.name_for_idx.append(name)

        print(f"SemanticMatcher: Embedding {len(texts)} names...")
        embeddings = self.model.encode(texts, show_progress_bar=False)
        self.faiss.normalize_L2(embeddings)

        dim = embeddings.shape[1]
        self.index = self.faiss.IndexFlatIP(dim)
        self.index.add(embeddings.astype('float32'))
        print(f"SemanticMatcher: Index built with {self.index.ntotal} vectors")

    def find(self, query: str, threshold: float = 0.7) -> tuple[TeamEntry | None, float, str]:
        """Find team by semantic similarity.

        Returns: (team, score, method)
        """
        query_emb = self.model.encode([query.lower()])
        self.faiss.normalize_L2(query_emb)

        distances, indices = self.index.search(query_emb.astype('float32'), 5)

        # Dedupe by team ID, take best
        seen = set()
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or dist < threshold:
                continue
            team = self.team_for_idx[idx]
            if team.id in seen:
                continue
            return (team, float(dist), f"semantic:{self.name_for_idx[idx]}")

        return (None, 0.0, "")


class FuzzyMatcher:
    """Fuzzy matching using rapidfuzz with proper algorithms."""

    def __init__(self, teams: list[TeamEntry]):
        from rapidfuzz import fuzz, process
        self.fuzz = fuzz
        self.process = process

        self.teams = teams

        # Build lookup: name → team
        self.name_to_team: dict[str, TeamEntry] = {}
        self.all_names: list[str] = []

        for team in teams:
            for name in team.primary_names:
                if name not in self.name_to_team:
                    self.name_to_team[name] = team
                    self.all_names.append(name)

        print(f"FuzzyMatcher: {len(self.all_names)} searchable names")

    def find(self, query: str, threshold: float = 75.0) -> tuple[TeamEntry | None, float, str]:
        """Find team by fuzzy matching.

        Uses multiple algorithms:
        1. WRatio (weighted combination)
        2. Token set ratio (handles word order)
        3. Partial ratio (substring matching)

        Returns: (team, score, method)
        """
        query_lower = query.lower().strip()

        # Use rapidfuzz's process.extractOne with WRatio
        result = self.process.extractOne(
            query_lower,
            self.all_names,
            scorer=self.fuzz.WRatio,
            score_cutoff=threshold
        )

        if result:
            matched_name, score, _ = result
            team = self.name_to_team[matched_name]
            return (team, score, f"fuzzy_wratio:{matched_name}")

        # Fallback: token_set_ratio for word order variations
        best_score = 0
        best_team = None
        best_name = ""

        for name in self.all_names:
            score = self.fuzz.token_set_ratio(query_lower, name)
            if score > best_score:
                best_score = score
                best_team = self.name_to_team[name]
                best_name = name

        if best_score >= threshold:
            return (best_team, best_score, f"fuzzy_token:{best_name}")

        return (None, 0.0, "")


class HybridMatcher:
    """
    Hybrid matching engine combining all approaches.

    Priority:
    1. Alias lookup (instant, exact)
    2. Semantic matching (fast, handles variations)
    3. Fuzzy matching (fallback)
    """

    def __init__(self, teams: list[TeamEntry], use_semantic: bool = True):
        self.alias = AliasLookup(teams)
        self.semantic = SemanticMatcher(teams) if use_semantic else None
        self.fuzzy = FuzzyMatcher(teams)

    def find(self, query: str) -> tuple[TeamEntry | None, float, str]:
        """Find team using hybrid strategy."""

        # 1. Alias lookup (instant)
        team, score, method = self.alias.find(query)
        if team:
            return (team, score, method)

        # 2. Semantic matching
        if self.semantic:
            team, score, method = self.semantic.find(query, threshold=0.75)
            if team and score >= 0.75:
                return (team, score, method)

        # 3. Fuzzy matching
        team, score, method = self.fuzzy.find(query, threshold=70.0)
        if team:
            return (team, score, method)

        return (None, 0.0, "no_match")


# =============================================================================
# TEST CASES
# =============================================================================

TEST_STREAMS = [
    # Standard formats
    ("ESPN+ 01 : Perth Glory vs. Wellington Phoenix @ Dec 12 05:55 AM ET", "Perth Glory", "Wellington Phoenix"),
    ("NBA 01: Chicago Bulls  vs  Charlotte Hornets @ 07:00 PM ET", "Chicago Bulls", "Charlotte Hornets"),
    ("NFL Game Pass 01: Atlanta Falcons  vs  Tampa Bay Buccaneers @ 08:15 PM ET", "Atlanta Falcons", "Tampa Bay Buccaneers"),

    # Nicknames (THE HARD ONES)
    ("Man U vs Chelsea", "Manchester United", "Chelsea"),
    ("MUFC vs Liverpool", "Manchester United", "Liverpool"),
    ("Spurs vs Arsenal", "Tottenham Hotspur", "Arsenal"),
    ("City vs United", "Manchester City", "Manchester United"),

    # German teams
    ("Hertha BSC vs Bayern Munich", "Hertha Berlin", "Bayern Munich"),
    ("Dortmund vs Köln", "Borussia Dortmund", "Cologne"),
    ("München vs Nürnberg", "Bayern Munich", "1. FC Nürnberg"),

    # US Sports nicknames
    ("Heat vs Magic", "Miami Heat", "Orlando Magic"),
    ("49ers @ Seahawks", "San Francisco 49ers", "Seattle Seahawks"),
    ("Chiefs vs Raiders", "Kansas City Chiefs", "Las Vegas Raiders"),

    # College
    ("#8 Alabama vs #3 Georgia", "Alabama", "Georgia"),
    ("Bama vs Dawgs", "Alabama", "Georgia"),

    # Messy real-world
    ("NCAAW B 14: Washington State vs BYU | 11/30 8:15PM EST", "Washington State", "BYU"),
    ("En Español-Real Sociedad vs. Girona FC @ Dec 12 02:55 PM ET", "Real Sociedad", "Girona"),
    ("SKY+11: Liverpool @ Manchester United (Spanish)", "Liverpool", "Manchester United"),
]


# =============================================================================
# MAIN TEST
# =============================================================================

def main():
    print("=" * 80)
    print("  HYBRID MATCHING ENGINE PROTOTYPE")
    print("=" * 80)
    print()

    # Load teams
    teams = load_teams()

    # Initialize matchers
    print("\n--- Initializing Matchers ---")
    start = time.time()
    hybrid = HybridMatcher(teams, use_semantic=True)
    print(f"Hybrid matcher ready in {time.time() - start:.2f}s")

    # Also init individual matchers for comparison
    alias_only = AliasLookup(teams)
    fuzzy_only = FuzzyMatcher(teams)

    # Test results tracking
    results = {
        'hybrid': {'success': 0, 'fail': 0},
        'alias': {'success': 0, 'fail': 0},
        'fuzzy': {'success': 0, 'fail': 0},
    }

    print("\n" + "=" * 80)
    print("  TEST RESULTS")
    print("=" * 80)

    for stream, expected_away, expected_home in TEST_STREAMS:
        print(f"\n{'─' * 80}")
        print(f"STREAM: {stream}")

        # Normalize
        normalized = normalize_stream_name(stream)
        print(f"NORMALIZED: {normalized}")

        # Extract teams
        extracted = extract_teams(normalized)
        if not extracted:
            print("  ⚠ Could not extract teams")
            continue

        away_text, home_text = extracted
        print(f"EXTRACTED: '{away_text}' vs '{home_text}'")
        print(f"EXPECTED:  '{expected_away}' vs '{expected_home}'")
        print()

        # Test each approach
        for label, team_text, expected in [("AWAY", away_text, expected_away), ("HOME", home_text, expected_home)]:
            print(f"  {label}: '{team_text}'")

            # Hybrid
            team, score, method = hybrid.find(team_text)
            match_str = f"{team.name} ({score:.0f}, {method})" if team else "NO MATCH"
            correct = team and expected.lower() in team.name.lower()
            symbol = "✓" if correct else "✗"
            print(f"    Hybrid: {symbol} {match_str}")
            results['hybrid']['success' if correct else 'fail'] += 1

            # Alias only
            team, score, method = alias_only.find(team_text)
            match_str = f"{team.name} ({score:.0f})" if team else "NO MATCH"
            correct = team and expected.lower() in team.name.lower()
            symbol = "✓" if correct else "✗"
            print(f"    Alias:  {symbol} {match_str}")
            results['alias']['success' if correct else 'fail'] += 1

            # Fuzzy only
            team, score, method = fuzzy_only.find(team_text)
            match_str = f"{team.name} ({score:.0f})" if team else "NO MATCH"
            correct = team and expected.lower() in team.name.lower()
            symbol = "✓" if correct else "✗"
            print(f"    Fuzzy:  {symbol} {match_str}")
            results['fuzzy']['success' if correct else 'fail'] += 1

    # Summary
    print("\n" + "=" * 80)
    print("  SUMMARY")
    print("=" * 80)

    for name, stats in results.items():
        total = stats['success'] + stats['fail']
        pct = stats['success'] / total * 100 if total > 0 else 0
        print(f"  {name.upper():8} {stats['success']}/{total} ({pct:.0f}%)")

    # Performance test
    print("\n" + "=" * 80)
    print("  PERFORMANCE (avg per query)")
    print("=" * 80)

    test_queries = ["man u", "chelsea", "hertha bsc", "chiefs", "49ers", "heat", "dortmund", "bama"]

    # Hybrid
    times = []
    for q in test_queries:
        start = time.time()
        for _ in range(50):
            hybrid.find(q)
        times.append((time.time() - start) / 50 * 1000)
    print(f"  Hybrid: {sum(times)/len(times):.2f}ms avg")

    # Alias only
    times = []
    for q in test_queries:
        start = time.time()
        for _ in range(50):
            alias_only.find(q)
        times.append((time.time() - start) / 50 * 1000)
    print(f"  Alias:  {sum(times)/len(times):.3f}ms avg")

    # Fuzzy only
    times = []
    for q in test_queries:
        start = time.time()
        for _ in range(50):
            fuzzy_only.find(q)
        times.append((time.time() - start) / 50 * 1000)
    print(f"  Fuzzy:  {sum(times)/len(times):.2f}ms avg")

    print("\n" + "=" * 80)
    print("  ANALYSIS")
    print("=" * 80)
    print("""
Key Findings:

1. NORMALIZATION: V1's pipeline handles messy stream names well
   - Mojibake fixing
   - Time masking before colon detection
   - City/team variant expansion

2. ALIAS LOOKUP: Fast and accurate for known nicknames
   - "Man U" → "Manchester United" (via CITY_NAME_VARIANTS)
   - Instant (0.01ms)
   - But requires maintaining the alias list

3. SEMANTIC: Good for similar names, fails for nicknames
   - "Perth Glory" → "Perth Glory" ✓
   - "Man U" → "MAN" ✗ (no knowledge of nicknames)

4. FUZZY (WRatio): Better than basic ratio
   - Handles word order and partial matches
   - But still fails for nicknames

5. HYBRID: Best of all worlds
   - Alias catches known nicknames instantly
   - Semantic/Fuzzy catch similar names
   - Graceful degradation

RECOMMENDATION:
- Use hybrid approach with comprehensive alias dictionary
- Make aliases database-driven (user can add)
- Semantic is optional (nice-to-have, not critical)
- The REAL win is V1's normalization + good alias coverage
""")


if __name__ == "__main__":
    main()
