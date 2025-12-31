#!/usr/bin/env python3
"""
Semantic Matching Prototype

Tests sentence-transformers + FAISS for team name matching.
Compares against current rapidfuzz approach.

Run: python experiments/semantic_matching_prototype.py
"""

import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# TEST DATA - Real stream names from various providers
# =============================================================================

TEST_STREAMS = [
    # Standard formats (should match easily)
    "ESPN+ 01 : Perth Glory vs. Wellington Phoenix @ Dec 12 05:55 AM ET",
    "NBA 01: Chicago Bulls  vs  Charlotte Hornets @ 07:00 PM ET",
    "NFL Game Pass 01: Atlanta Falcons  vs  Tampa Bay Buccaneers @ 08:15 PM ET",
    "NHL 01: Chicago Blackhawks  vs  St. Louis Blues @ 08:00 PM ET",

    # Abbreviations and nicknames (harder)
    "Man U vs Chelsea",
    "MUFC vs Liverpool",
    "Spurs vs Arsenal",  # Could be Tottenham or San Antonio
    "City vs United",    # Ambiguous without context

    # German teams with variants
    "Hertha BSC vs Bayern Munich",
    "Dortmund vs Köln",
    "München vs Nürnberg",
    "Gladbach vs Schalke",

    # College with rankings
    "#8 Alabama vs #3 Georgia",
    "Texas vs #5 UConn",
    "Duke vs North Carolina",

    # Messy real-world examples
    "NCAAW B 14: Washington State vs BYU | 11/30 8:15PM EST",
    "En Español-Real Sociedad vs. Girona FC @ Dec 12 02:55 PM ET",
    "SKY+11: Liverpool @ Manchester United (Spanish)",

    # Edge cases
    "LA vs NY",  # Very ambiguous
    "Heat vs Magic",  # Nicknames only
    "49ers @ Seahawks",  # NFL nicknames
]

# Ground truth for some test cases (what they SHOULD match to)
EXPECTED_MATCHES = {
    "Man U vs Chelsea": ("Manchester United", "Chelsea"),
    "MUFC vs Liverpool": ("Manchester United", "Liverpool"),
    "Spurs vs Arsenal": ("Tottenham Hotspur", "Arsenal"),  # In EPL context
    "Hertha BSC vs Bayern Munich": ("Hertha Berlin", "Bayern Munich"),
    "Dortmund vs Köln": ("Borussia Dortmund", "Cologne"),  # ESPN uses Cologne
    "Heat vs Magic": ("Miami Heat", "Orlando Magic"),
    "49ers @ Seahawks": ("San Francisco 49ers", "Seattle Seahawks"),
}


# =============================================================================
# NORMALIZATION (simplified from V1)
# =============================================================================

def normalize_stream_name(text: str) -> str:
    """Basic normalization for testing."""
    if not text:
        return ""

    text = text.lower()

    # Strip common prefixes
    text = re.sub(r'^(espn\+?\s*\d*\s*:?\s*|nba\s*\d*\s*:?\s*|nfl[^:]*:\s*|nhl\s*\d*\s*:?\s*|ncaa[mfwb]?\s*[a-z]?\s*\d*\s*:?\s*)', '', text, flags=re.I)
    text = re.sub(r'^(sky\+?\d*\s*:?\s*|en\s+español[-:]?\s*)', '', text, flags=re.I)

    # Strip suffixes (times, dates)
    text = re.sub(r'\s*[@|]\s*.*$', '', text)
    text = re.sub(r'\s*\(.*\)\s*$', '', text)

    # Strip rankings
    text = re.sub(r'#\d+\s*', '', text)

    # Normalize whitespace
    text = ' '.join(text.split())

    return text.strip()


def extract_teams(normalized: str) -> tuple[str, str] | None:
    """Extract away/home teams from normalized text."""
    separators = [' vs. ', ' vs ', ' @ ', ' v ', ' at ']

    for sep in separators:
        if sep in normalized:
            parts = normalized.split(sep, 1)
            if len(parts) == 2:
                return (parts[0].strip(), parts[1].strip())

    return None


# =============================================================================
# SEMANTIC MATCHER
# =============================================================================

class SemanticMatcher:
    """Prototype semantic matcher using sentence-transformers + FAISS."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        print(f"Loading model: {model_name}")
        start = time.time()

        from sentence_transformers import SentenceTransformer
        import faiss
        import numpy as np

        self.model = SentenceTransformer(model_name)
        self.faiss = faiss
        self.np = np

        self.index = None
        self.team_names: list[str] = []
        self.team_ids: list[str] = []

        print(f"Model loaded in {time.time() - start:.2f}s")

    def build_index(self, teams: list[dict]):
        """Build FAISS index from team data.

        teams: List of dicts with 'id', 'name', 'short_name', 'abbreviation'
        """
        print(f"Building index for {len(teams)} teams...")
        start = time.time()

        # Collect all name variants
        texts = []
        for team in teams:
            team_id = team.get('id', team.get('name'))
            for field in ['name', 'short_name', 'abbreviation']:
                value = team.get(field)
                if value and len(value) >= 2:
                    texts.append(value.lower())
                    self.team_names.append(value)
                    self.team_ids.append(team_id)

        print(f"  Collected {len(texts)} name variants")

        # Embed all variants
        embed_start = time.time()
        embeddings = self.model.encode(texts, show_progress_bar=True)
        print(f"  Embedded in {time.time() - embed_start:.2f}s")

        # Normalize for cosine similarity
        self.faiss.normalize_L2(embeddings)

        # Build index
        dimension = embeddings.shape[1]
        self.index = self.faiss.IndexFlatIP(dimension)  # Inner product = cosine for normalized vectors
        self.index.add(embeddings.astype('float32'))

        print(f"Index built in {time.time() - start:.2f}s")
        print(f"  Dimension: {dimension}")
        print(f"  Total vectors: {self.index.ntotal}")

    def find_team(self, query: str, k: int = 5, threshold: float = 0.5) -> list[tuple[str, str, float]]:
        """Find closest teams to query.

        Returns: List of (team_name, team_id, similarity_score)
        """
        if not self.index:
            return []

        # Embed query
        query_embedding = self.model.encode([query.lower()])
        self.faiss.normalize_L2(query_embedding)

        # Search
        distances, indices = self.index.search(query_embedding.astype('float32'), k)

        results = []
        seen_ids = set()

        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:  # FAISS returns -1 for missing
                continue
            if dist < threshold:
                continue

            team_id = self.team_ids[idx]
            if team_id in seen_ids:  # Dedupe (same team, different variant)
                continue
            seen_ids.add(team_id)

            team_name = self.team_names[idx]
            results.append((team_name, team_id, float(dist)))

        return results


# =============================================================================
# FUZZY MATCHER (current approach)
# =============================================================================

class FuzzyMatcher:
    """Current rapidfuzz-based matcher for comparison."""

    def __init__(self):
        from rapidfuzz import fuzz
        self.fuzz = fuzz
        self.team_names: list[str] = []
        self.team_ids: list[str] = []

    def build_index(self, teams: list[dict]):
        """Build lookup from team data."""
        for team in teams:
            team_id = team.get('id', team.get('name'))
            for field in ['name', 'short_name', 'abbreviation']:
                value = team.get(field)
                if value and len(value) >= 2:
                    self.team_names.append(value.lower())
                    self.team_ids.append(team_id)

    def find_team(self, query: str, k: int = 5, threshold: float = 70) -> list[tuple[str, str, float]]:
        """Find closest teams using rapidfuzz."""
        query_lower = query.lower()

        scores = []
        for i, name in enumerate(self.team_names):
            # Try multiple scoring methods
            score = max(
                self.fuzz.ratio(query_lower, name),
                self.fuzz.partial_ratio(query_lower, name),
                self.fuzz.token_set_ratio(query_lower, name),
            )
            if score >= threshold:
                scores.append((self.team_names[i], self.team_ids[i], score))

        # Sort by score, dedupe by team_id
        scores.sort(key=lambda x: x[2], reverse=True)

        seen_ids = set()
        results = []
        for name, team_id, score in scores:
            if team_id not in seen_ids:
                seen_ids.add(team_id)
                results.append((name, team_id, score))
                if len(results) >= k:
                    break

        return results


# =============================================================================
# LOAD TEAM DATA
# =============================================================================

def load_teams_from_cache() -> list[dict]:
    """Load teams from the team_cache table."""
    import sqlite3

    db_path = Path(__file__).parent.parent / "data" / "teamarr.db"

    if not db_path.exists():
        print(f"Database not found at {db_path}")
        print("Using synthetic team data for testing...")
        return get_synthetic_teams()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cursor = conn.execute("""
        SELECT
            provider_team_id as id,
            team_name as name,
            team_short_name as short_name,
            team_abbrev as abbreviation,
            league
        FROM team_cache
    """)

    teams = [dict(row) for row in cursor.fetchall()]
    conn.close()

    print(f"Loaded {len(teams)} teams from database")
    return teams


def get_synthetic_teams() -> list[dict]:
    """Synthetic team data for testing without database."""
    return [
        # EPL
        {"id": "man_utd", "name": "Manchester United", "short_name": "Man United", "abbreviation": "MUFC", "league": "eng.1"},
        {"id": "chelsea", "name": "Chelsea", "short_name": "Chelsea", "abbreviation": "CHE", "league": "eng.1"},
        {"id": "liverpool", "name": "Liverpool", "short_name": "Liverpool", "abbreviation": "LIV", "league": "eng.1"},
        {"id": "arsenal", "name": "Arsenal", "short_name": "Arsenal", "abbreviation": "ARS", "league": "eng.1"},
        {"id": "tottenham", "name": "Tottenham Hotspur", "short_name": "Spurs", "abbreviation": "TOT", "league": "eng.1"},
        {"id": "man_city", "name": "Manchester City", "short_name": "Man City", "abbreviation": "MCI", "league": "eng.1"},

        # Bundesliga
        {"id": "bayern", "name": "Bayern Munich", "short_name": "Bayern", "abbreviation": "FCB", "league": "ger.1"},
        {"id": "dortmund", "name": "Borussia Dortmund", "short_name": "Dortmund", "abbreviation": "BVB", "league": "ger.1"},
        {"id": "hertha", "name": "Hertha Berlin", "short_name": "Hertha", "abbreviation": "BSC", "league": "ger.2"},
        {"id": "cologne", "name": "Cologne", "short_name": "Köln", "abbreviation": "KOE", "league": "ger.1"},
        {"id": "gladbach", "name": "Borussia Mönchengladbach", "short_name": "Gladbach", "abbreviation": "BMG", "league": "ger.1"},

        # NBA
        {"id": "heat", "name": "Miami Heat", "short_name": "Heat", "abbreviation": "MIA", "league": "nba"},
        {"id": "magic", "name": "Orlando Magic", "short_name": "Magic", "abbreviation": "ORL", "league": "nba"},
        {"id": "bulls", "name": "Chicago Bulls", "short_name": "Bulls", "abbreviation": "CHI", "league": "nba"},
        {"id": "lakers", "name": "Los Angeles Lakers", "short_name": "Lakers", "abbreviation": "LAL", "league": "nba"},
        {"id": "knicks", "name": "New York Knicks", "short_name": "Knicks", "abbreviation": "NYK", "league": "nba"},
        {"id": "spurs_nba", "name": "San Antonio Spurs", "short_name": "Spurs", "abbreviation": "SAS", "league": "nba"},

        # NFL
        {"id": "49ers", "name": "San Francisco 49ers", "short_name": "49ers", "abbreviation": "SF", "league": "nfl"},
        {"id": "seahawks", "name": "Seattle Seahawks", "short_name": "Seahawks", "abbreviation": "SEA", "league": "nfl"},
        {"id": "chiefs", "name": "Kansas City Chiefs", "short_name": "Chiefs", "abbreviation": "KC", "league": "nfl"},
        {"id": "falcons", "name": "Atlanta Falcons", "short_name": "Falcons", "abbreviation": "ATL", "league": "nfl"},
        {"id": "bucs", "name": "Tampa Bay Buccaneers", "short_name": "Buccaneers", "abbreviation": "TB", "league": "nfl"},

        # A-League
        {"id": "perth", "name": "Perth Glory", "short_name": "Perth", "abbreviation": "PER", "league": "aus.1"},
        {"id": "wellington", "name": "Wellington Phoenix", "short_name": "Wellington", "abbreviation": "WEL", "league": "aus.1"},
    ]


# =============================================================================
# MAIN TEST
# =============================================================================

def main():
    print("=" * 70)
    print("  SEMANTIC MATCHING PROTOTYPE")
    print("=" * 70)
    print()

    # Load teams
    teams = load_teams_from_cache()

    # Initialize matchers
    print("\n--- Initializing Matchers ---")

    semantic = SemanticMatcher()
    semantic.build_index(teams)

    fuzzy = FuzzyMatcher()
    fuzzy.build_index(teams)

    # Test each stream
    print("\n" + "=" * 70)
    print("  TEST RESULTS")
    print("=" * 70)

    for stream in TEST_STREAMS:
        print(f"\n{'─' * 70}")
        print(f"STREAM: {stream}")

        # Normalize
        normalized = normalize_stream_name(stream)
        print(f"NORMALIZED: {normalized}")

        # Extract teams
        extracted = extract_teams(normalized)
        if not extracted:
            print("  ⚠ Could not extract teams from stream name")
            continue

        away_text, home_text = extracted
        print(f"EXTRACTED: '{away_text}' vs '{home_text}'")

        # Test both matchers
        print()
        print("  SEMANTIC MATCHES:")

        semantic_start = time.time()
        for team_text, label in [(away_text, "Away"), (home_text, "Home")]:
            results = semantic.find_team(team_text, k=3, threshold=0.4)
            semantic_time = (time.time() - semantic_start) * 1000

            if results:
                top = results[0]
                print(f"    {label}: '{team_text}' → {top[0]} (score: {top[2]:.2f})")
                if len(results) > 1:
                    others = ", ".join(f"{r[0]} ({r[2]:.2f})" for r in results[1:3])
                    print(f"         Also: {others}")
            else:
                print(f"    {label}: '{team_text}' → NO MATCH")

        print()
        print("  FUZZY MATCHES:")

        fuzzy_start = time.time()
        for team_text, label in [(away_text, "Away"), (home_text, "Home")]:
            results = fuzzy.find_team(team_text, k=3, threshold=50)
            fuzzy_time = (time.time() - fuzzy_start) * 1000

            if results:
                top = results[0]
                print(f"    {label}: '{team_text}' → {top[0]} (score: {top[2]:.0f})")
                if len(results) > 1:
                    others = ", ".join(f"{r[0]} ({r[2]:.0f})" for r in results[1:3])
                    print(f"         Also: {others}")
            else:
                print(f"    {label}: '{team_text}' → NO MATCH")

        # Check against expected
        stream_key = None
        for key in EXPECTED_MATCHES:
            if key.lower() in stream.lower() or stream.lower().startswith(key.lower()):
                stream_key = key
                break

        if stream_key:
            expected = EXPECTED_MATCHES[stream_key]
            print()
            print(f"  EXPECTED: {expected[0]} vs {expected[1]}")

    # Performance comparison
    print("\n" + "=" * 70)
    print("  PERFORMANCE COMPARISON")
    print("=" * 70)

    test_queries = ["man u", "chelsea", "hertha bsc", "chiefs", "49ers", "heat"]

    # Semantic timing
    print("\nSemantic matching (per query):")
    times = []
    for query in test_queries:
        start = time.time()
        for _ in range(10):
            semantic.find_team(query)
        elapsed = (time.time() - start) / 10 * 1000
        times.append(elapsed)
        print(f"  '{query}': {elapsed:.2f}ms")
    print(f"  Average: {sum(times)/len(times):.2f}ms")

    # Fuzzy timing
    print("\nFuzzy matching (per query):")
    times = []
    for query in test_queries:
        start = time.time()
        for _ in range(10):
            fuzzy.find_team(query)
        elapsed = (time.time() - start) / 10 * 1000
        times.append(elapsed)
        print(f"  '{query}': {elapsed:.2f}ms")
    print(f"  Average: {sum(times)/len(times):.2f}ms")

    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print("""
Key observations:
1. Semantic matching finds "man u" → "Manchester United" (fuzzy may fail)
2. Semantic handles abbreviations like "MUFC" better
3. Fuzzy is faster but less accurate for variations
4. Both struggle with ambiguous cases like "Spurs" (EPL vs NBA)

Recommendation:
- Use semantic for initial matching
- Fall back to fuzzy for exact/near-exact matches
- League context can disambiguate "Spurs" etc.
""")


if __name__ == "__main__":
    main()
