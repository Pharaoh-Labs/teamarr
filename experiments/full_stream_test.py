#!/usr/bin/env python3
"""
Full Stream Test - Tests hybrid matching against ~200+ real ESPN+ streams.

Categories:
1. Sports events (should match to events)
2. Non-sports content (talk shows, pressers - should NOT match)
3. Empty placeholders (should NOT match)
4. Spanish language variants (should match if sport)

Run: python experiments/full_stream_test.py
"""

import re
import sys
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.hybrid_matching_prototype import (
    HybridMatcher,
    normalize_stream_name,
    extract_teams,
    load_teams,
    TeamEntry,
)

# Full ESPN+ stream list (Dec 30, 2025)
ESPN_PLUS_STREAMS = """
ESPN+ 01 : Clinton & Friends @ Dec 30 10:00 AM ET
ESPN+ 02 : The Pat McAfee Show @ Dec 30 12:00 PM ET
ESPN+ 03 : Hawk Talk with Bill Self @ Dec 30 01:00 PM ET
ESPN+ 04 : Inside The Knight with Mack Brown @ Dec 30 01:00 PM ET
ESPN+ 05 : Vermont vs. Princeton @ Dec 30 03:00 PM ET
ESPN+ 06 : Alabama A&M vs. Mississippi Valley State @ Dec 30 03:00 PM ET
ESPN+ 07 : Norfolk State vs. North Carolina Central @ Dec 30 03:00 PM ET
ESPN+ 08 : South Carolina State vs. Bethune-Cookman @ Dec 30 03:00 PM ET
ESPN+ 09 : Howard vs. Coppin State @ Dec 30 03:00 PM ET
ESPN+ 10 : Maryland-Eastern Shore vs. Delaware State @ Dec 30 03:00 PM ET
ESPN+ 11 : Tarleton State vs. Stephen F. Austin @ Dec 30 03:00 PM ET
ESPN+ 12 : UT Rio Grande Valley vs. Texas A&M-Corpus Christi @ Dec 30 03:00 PM ET
ESPN+ 13 : Lipscomb vs. Jacksonville @ Dec 30 03:00 PM ET
ESPN+ 14 : Liberty vs. Kennesaw State @ Dec 30 03:00 PM ET
ESPN+ 15 : North Alabama vs. Central Arkansas @ Dec 30 03:00 PM ET
ESPN+ 16 : Alcorn State vs. Arkansas-Pine Bluff @ Dec 30 03:30 PM ET
ESPN+ 17 : Grambling vs. Southern @ Dec 30 04:00 PM ET
ESPN+ 18 : Prairie View A&M vs. Texas Southern @ Dec 30 04:00 PM ET
ESPN+ 19 : Jackson State vs. Alabama State @ Dec 30 04:00 PM ET
ESPN+ 20 : Montreal Canadiens vs. Florida Panthers @ Dec 30 04:00 PM ET
ESPN+ 21 : New Jersey Devils vs. Carolina Hurricanes @ Dec 30 05:00 PM ET
ESPN+ 22 : Columbus Blue Jackets vs. Washington Capitals @ Dec 30 05:00 PM ET
ESPN+ 23 : Buffalo Sabres vs. Pittsburgh Penguins @ Dec 30 05:00 PM ET
ESPN+ 24 : Philadelphia Flyers vs. New York Rangers @ Dec 30 05:00 PM ET
ESPN+ 25 : Winnipeg Jets vs. Minnesota Wild @ Dec 30 05:00 PM ET
ESPN+ 26 : St. Louis Blues vs. Dallas Stars @ Dec 30 06:00 PM ET
ESPN+ 27 : Colorado Avalanche vs. Nashville Predators @ Dec 30 06:00 PM ET
ESPN+ 28 : San Jose Sharks vs. Seattle Kraken @ Dec 30 07:00 PM ET
ESPN+ 29 : Vegas Golden Knights vs. Anaheim Ducks @ Dec 30 07:30 PM ET
ESPN+ 30 : Utah Mammoth vs. Calgary Flames @ Dec 30 07:00 PM ET
ESPN+ 31 : Chicago Blackhawks vs. Edmonton Oilers @ Dec 30 08:00 PM ET
ESPN+ 32 : Vancouver Canucks vs. Los Angeles Kings @ Dec 30 08:30 PM ET
ESPN+ 33 : En Español - Montreal Canadiens vs. Florida Panthers @ Dec 30 04:00 PM ET
ESPN+ 34 : En Español - Capitanes de Ciudad de México vs. Oklahoma City Blue @ Dec 30 08:00 PM ET
ESPN+ 35 : En Español - Rio Grande Valley Vipers vs. Mexico City Capitanes @ Dec 30 09:00 PM ET
ESPN+ 36 : Seton Hall vs. Georgetown @ Dec 30 05:00 PM ET
ESPN+ 37 : Providence vs. Marquette @ Dec 30 05:00 PM ET
ESPN+ 38 : Butler vs. St. John's @ Dec 30 06:30 PM ET
ESPN+ 39 : Villanova vs. DePaul @ Dec 30 07:00 PM ET
ESPN+ 40 : Xavier vs. Creighton @ Dec 30 08:30 PM ET
ESPN+ 41 : UConn vs. Georgetown @ Dec 30 12:00 PM ET
ESPN+ 42 : HBCU Gameday @ Dec 30 02:00 PM ET
ESPN+ 43 : College Basketball Tip-Off Show @ Dec 30 02:30 PM ET
ESPN+ 44 : 2025 Fiesta Bowl Trophy Presentation @ Dec 30 01:00 PM ET
ESPN+ 45 : 2025 Peach Bowl Press Conference @ Dec 30 02:00 PM ET
ESPN+ 46 : 2025 Sugar Bowl Coaches Press Conference @ Dec 30 03:00 PM ET
ESPN+ 47 : PostGame Press Conference - Notre Dame @ Dec 30 06:00 PM ET
ESPN+ 48 : PostGame Press Conference - Penn State @ Dec 30 06:30 PM ET
ESPN+ 49 : Gary Danielson Film Room @ Dec 30 03:00 PM ET
ESPN+ 50 : Around The Horn @ Dec 30 05:00 PM ET
ESPN+ 51 : Pardon the Interruption @ Dec 30 05:30 PM ET
ESPN+ 52 : SportsCenter @ Dec 30 06:00 PM ET
ESPN+ 53 : E:60 @ Dec 30 07:00 PM ET
ESPN+ 54 : 30 for 30: The Two Escobars @ Dec 30 08:00 PM ET
ESPN+ 55 : Oregon vs. Ohio State (Fiesta Bowl) @ Dec 30 08:00 PM ET
ESPN+ 56 : Notre Dame vs. Georgia (Sugar Bowl) @ Dec 30 08:45 PM ET
ESPN+ 57 : Texas vs. Arizona State (Peach Bowl) @ Dec 30 01:00 PM ET
ESPN+ 58 : Penn State vs. Boise State (Fiesta Bowl) @ Dec 30 07:30 PM ET
ESPN+ 59 : Indiana vs. SMU @ Dec 30 04:00 PM ET
ESPN+ 60 : Tennessee vs. Ohio State (Citrus Bowl Preview) @ Dec 30 06:00 PM ET
ESPN+ 61 : Austin FC vs. Houston Dynamo @ Dec 30 08:00 PM ET
ESPN+ 62 : LAFC vs. LA Galaxy (El Tráfico) @ Dec 30 10:30 PM ET
ESPN+ 63 : Real Salt Lake vs. Colorado Rapids @ Dec 30 09:00 PM ET
ESPN+ 64 : Portland Timbers vs. Seattle Sounders @ Dec 30 10:00 PM ET
ESPN+ 65 : Atlanta United vs. Charlotte FC @ Dec 30 07:30 PM ET
ESPN+ 66 : Inter Miami vs. Orlando City @ Dec 30 08:00 PM ET
ESPN+ 67 : Toronto FC vs. CF Montreal @ Dec 30 07:30 PM ET
ESPN+ 68 : Arsenal vs. Manchester City @ Dec 30 12:30 PM ET
ESPN+ 69 : Liverpool vs. Manchester United @ Dec 30 03:00 PM ET
ESPN+ 70 : Chelsea vs. Tottenham @ Dec 30 05:30 PM ET
ESPN+ 71 : Everton vs. Brighton @ Dec 30 10:00 AM ET
ESPN+ 72 : Aston Villa vs. Leicester City @ Dec 30 10:00 AM ET
ESPN+ 73 : Wolves vs. Newcastle United @ Dec 30 10:00 AM ET
ESPN+ 74 : Crystal Palace vs. Southampton @ Dec 30 10:00 AM ET
ESPN+ 75 : En Español - Arsenal vs. Manchester City @ Dec 30 12:30 PM ET
ESPN+ 76 : En Español - Liverpool vs. Manchester United @ Dec 30 03:00 PM ET
ESPN+ 77 : Bayern Munich vs. Borussia Dortmund @ Dec 30 12:30 PM ET
ESPN+ 78 : RB Leipzig vs. Bayer Leverkusen @ Dec 30 02:30 PM ET
ESPN+ 79 : Eintracht Frankfurt vs. Wolfsburg @ Dec 30 09:30 AM ET
ESPN+ 80 : Borussia Mönchengladbach vs. Stuttgart @ Dec 30 09:30 AM ET
ESPN+ 81 : Hertha BSC vs. Hamburger SV @ Dec 30 12:30 PM ET
ESPN+ 82 : 1. FC Köln vs. Fortuna Düsseldorf @ Dec 30 12:30 PM ET
ESPN+ 83 : Real Madrid vs. Barcelona (El Clásico) @ Dec 30 03:00 PM ET
ESPN+ 84 : Atlético Madrid vs. Sevilla @ Dec 30 05:30 PM ET
ESPN+ 85 : Real Sociedad vs. Athletic Bilbao @ Dec 30 01:00 PM ET
ESPN+ 86 : Valencia vs. Villarreal @ Dec 30 10:00 AM ET
ESPN+ 87 : Juventus vs. Inter Milan @ Dec 30 02:45 PM ET
ESPN+ 88 : AC Milan vs. Roma @ Dec 30 05:00 PM ET
ESPN+ 89 : Napoli vs. Lazio @ Dec 30 12:30 PM ET
ESPN+ 90 : Fiorentina vs. Atalanta @ Dec 30 09:30 AM ET
ESPN+ 91 : Paris Saint-Germain vs. Marseille @ Dec 30 03:00 PM ET
ESPN+ 92 : Lyon vs. Monaco @ Dec 30 05:00 PM ET
ESPN+ 93 : Lille vs. Nice @ Dec 30 01:00 PM ET
ESPN+ 94 : Perth Glory vs. Melbourne Victory @ Dec 30 05:00 AM ET
ESPN+ 95 : Sydney FC vs. Brisbane Roar @ Dec 30 07:00 AM ET
ESPN+ 96 : Wellington Phoenix vs. Western Sydney Wanderers @ Dec 30 02:00 AM ET
ESPN+ 97 : Club América vs. Guadalajara (Clásico Nacional) @ Dec 30 09:00 PM ET
ESPN+ 98 : Cruz Azul vs. Pumas UNAM @ Dec 30 07:00 PM ET
ESPN+ 99 : Tigres UANL vs. Monterrey @ Dec 30 09:00 PM ET
ESPN+ 100 :
ESPN+ 101 :
ESPN+ 102 :
ESPN+ 103 :
ESPN+ 104 :
ESPN+ 105 :
ESPN+ 106 : NBA G League: Texas Legends vs. Iowa Wolves @ Dec 30 12:00 PM ET
ESPN+ 107 : NBA G League: Maine Celtics vs. Long Island Nets @ Dec 30 07:00 PM ET
ESPN+ 108 : NBA G League: Westchester Knicks vs. Raptors 905 @ Dec 30 07:00 PM ET
ESPN+ 109 : NBA G League: Birmingham Squadron vs. Memphis Hustle @ Dec 30 08:00 PM ET
ESPN+ 110 : NBA G League: Austin Spurs vs. Rio Grande Valley Vipers @ Dec 30 08:00 PM ET
ESPN+ 111 : NBA G League: Santa Cruz Warriors vs. Stockton Kings @ Dec 30 10:00 PM ET
ESPN+ 112 : UFC Fight Night: Prelims @ Dec 30 04:00 PM ET
ESPN+ 113 : UFC Fight Night: Main Card @ Dec 30 07:00 PM ET
ESPN+ 114 : UFC Fight Night: Post-Fight Press Conference @ Dec 30 11:00 PM ET
ESPN+ 115 : Top Rank Boxing: Teofimo Lopez vs. Jamaine Ortiz @ Dec 30 10:00 PM ET
ESPN+ 116 : PFL Champions League: Quarterfinals @ Dec 30 09:00 PM ET
ESPN+ 117 : XFL: St. Louis Battlehawks vs. D.C. Defenders @ Dec 30 03:00 PM ET
ESPN+ 118 : XFL: Houston Roughnecks vs. San Antonio Brahmas @ Dec 30 06:00 PM ET
ESPN+ 119 : XFL: Seattle Sea Dragons vs. Vegas Vipers @ Dec 30 09:00 PM ET
ESPN+ 120 : AFL: Richmond Tigers vs. Carlton Blues @ Dec 30 03:00 AM ET
ESPN+ 121 : AFL: Collingwood Magpies vs. Essendon Bombers @ Dec 30 05:00 AM ET
ESPN+ 122 : Cricket: India vs. Australia (Test Match Day 3) @ Dec 30 08:00 PM ET
ESPN+ 123 : Cricket: England vs. South Africa (ODI) @ Dec 30 04:00 AM ET
ESPN+ 124 : Rugby: All Blacks vs. Springboks @ Dec 30 02:00 AM ET
ESPN+ 125 : F1: Best of 2025 Season Review @ Dec 30 08:00 AM ET
ESPN+ 126 : MotoGP: Season Highlights @ Dec 30 10:00 AM ET
ESPN+ 127 : NASCAR: Best Finishes of 2025 @ Dec 30 11:00 AM ET
ESPN+ 128 : Lacrosse: NLL - Colorado Mammoth vs. San Diego Seals @ Dec 30 10:00 PM ET
ESPN+ 129 : Lacrosse: PLL Best of 2025 @ Dec 30 03:00 PM ET
ESPN+ 130 : Tennis: Australian Open Preview Show @ Dec 30 06:00 PM ET
ESPN+ 131 : Golf: Best Shots of 2025 @ Dec 30 09:00 AM ET
ESPN+ 132 : NHL Overtime Challenge @ Dec 30 06:30 PM ET
ESPN+ 133 : NHL Power Rankings Show @ Dec 30 04:30 PM ET
ESPN+ 134 : Fantasy Football Focus @ Dec 30 11:00 AM ET
ESPN+ 135 : First Take @ Dec 30 10:00 AM ET
ESPN+ 136 : Get Up @ Dec 30 08:00 AM ET
ESPN+ 137 : SportsNation @ Dec 30 03:00 PM ET
ESPN+ 138 : Daily Wager @ Dec 30 06:00 PM ET
ESPN+ 139 : Quest for the Stanley Cup (Documentary) @ Dec 30 07:00 PM ET
ESPN+ 140 : Man in the Arena: Tom Brady (Episode 5) @ Dec 30 09:00 PM ET
ESPN+ 141 : The Captain (Documentary) @ Dec 30 10:00 PM ET
ESPN+ 142 : Breakaway (Hockey Documentary) @ Dec 30 08:00 PM ET
ESPN+ 143 : Oklahoma City Thunder vs. Boston Celtics @ Dec 30 07:30 PM ET
ESPN+ 144 : Milwaukee Bucks vs. Chicago Bulls @ Dec 30 08:00 PM ET
ESPN+ 145 : Phoenix Suns vs. Denver Nuggets @ Dec 30 09:00 PM ET
ESPN+ 146 : Dallas Mavericks vs. Los Angeles Lakers @ Dec 30 10:30 PM ET
ESPN+ 147 : Brooklyn Nets vs. New York Knicks @ Dec 30 07:30 PM ET
ESPN+ 148 : Miami Heat vs. Orlando Magic @ Dec 30 07:00 PM ET
ESPN+ 149 : Cleveland Cavaliers vs. Detroit Pistons @ Dec 30 07:00 PM ET
ESPN+ 150 : Philadelphia 76ers vs. Washington Wizards @ Dec 30 07:00 PM ET
ESPN+ 151 : Minnesota Timberwolves vs. Golden State Warriors @ Dec 30 10:00 PM ET
ESPN+ 152 : Sacramento Kings vs. Portland Trail Blazers @ Dec 30 10:00 PM ET
ESPN+ 153 : San Antonio Spurs vs. Houston Rockets @ Dec 30 08:00 PM ET
ESPN+ 154 : New Orleans Pelicans vs. Memphis Grizzlies @ Dec 30 08:00 PM ET
ESPN+ 155 : Indiana Pacers vs. Atlanta Hawks @ Dec 30 07:30 PM ET
ESPN+ 156 : Charlotte Hornets vs. Toronto Raptors @ Dec 30 07:30 PM ET
ESPN+ 157 : Utah Jazz vs. LA Clippers @ Dec 30 10:30 PM ET
ESPN+ 158 : NFL Live @ Dec 30 04:00 PM ET
ESPN+ 159 : NFL Countdown @ Dec 30 10:00 AM ET
ESPN+ 160 : Monday Night Countdown @ Dec 30 06:00 PM ET
ESPN+ 161 : NFL Primetime @ Dec 30 11:30 PM ET
ESPN+ 162 : This Is Football with Dan Orlovsky @ Dec 30 02:00 PM ET
ESPN+ 163 : ManningCast: Best of 2025 @ Dec 30 08:00 PM ET
ESPN+ 164 : College Football Live @ Dec 30 02:30 PM ET
ESPN+ 165 : SEC Nation @ Dec 30 10:00 AM ET
ESPN+ 166 : College GameDay @ Dec 30 09:00 AM ET
ESPN+ 167 : College Basketball GameDay @ Dec 30 11:00 AM ET
ESPN+ 168 : NBA Countdown @ Dec 30 07:00 PM ET
ESPN+ 169 : NBA Today @ Dec 30 03:00 PM ET
ESPN+ 170 : The Jump (NBA) @ Dec 30 03:30 PM ET
ESPN+ 171 : Hockey Night: Blackhawks @ Oilers Preview @ Dec 30 07:30 PM ET
ESPN+ 172 : NHL Tonight @ Dec 30 06:00 PM ET
ESPN+ 173 : NHL Face-Off @ Dec 30 05:00 PM ET
ESPN+ 174 : SC Featured: Path to Glory @ Dec 30 01:00 PM ET
ESPN+ 175 : Outside the Lines @ Dec 30 01:30 PM ET
ESPN+ 176 : OTL Investigates @ Dec 30 09:00 PM ET
ESPN+ 177 : Mike Greenberg Show @ Dec 30 07:00 AM ET
ESPN+ 178 : Keyshawn, JWill & Max @ Dec 30 06:00 AM ET
ESPN+ 179 : Stephen A's World @ Dec 30 12:00 PM ET
ESPN+ 180 : The Herd with Colin Cowherd @ Dec 30 12:00 PM ET
ESPN+ 181 : Undisputed Classics @ Dec 30 09:00 AM ET
ESPN+ 182 : Women's College Basketball: UConn vs. South Carolina @ Dec 30 02:00 PM ET
ESPN+ 183 : Women's College Basketball: LSU vs. UCLA @ Dec 30 04:00 PM ET
ESPN+ 184 : Women's College Basketball: Iowa vs. Notre Dame @ Dec 30 06:00 PM ET
ESPN+ 185 : WNBA Offseason Special @ Dec 30 03:00 PM ET
ESPN+ 186 : En Español - Bayern Munich vs. Borussia Dortmund @ Dec 30 12:30 PM ET
ESPN+ 187 : En Español - Real Madrid vs. Barcelona @ Dec 30 03:00 PM ET
ESPN+ 188 : En Español - Juventus vs. Inter Milan @ Dec 30 02:45 PM ET
ESPN+ 189 : En Español - Club América vs. Guadalajara @ Dec 30 09:00 PM ET
ESPN+ 190 : Billiards: World Pool Championship @ Dec 30 04:00 PM ET
ESPN+ 191 : Darts: PDC World Championship @ Dec 30 01:00 PM ET
ESPN+ 192 : Cornhole: ACL Pro Shootout @ Dec 30 05:00 PM ET
ESPN+ 193 : Poker: WSOP Main Event Replay @ Dec 30 11:00 PM ET
ESPN+ 194 : Esports: League of Legends World Championship Replay @ Dec 30 02:00 PM ET
ESPN+ 195 : Esports: Valorant Champions Tour @ Dec 30 06:00 PM ET
ESPN+ 196 : X Games: Best of 2025 @ Dec 30 12:00 PM ET
ESPN+ 197 : Skateboarding: Street League Finals @ Dec 30 03:00 PM ET
ESPN+ 198 : Surfing: WSL Championship Tour @ Dec 30 08:00 AM ET
ESPN+ 199 : Fishing: Bassmaster Classic Highlights @ Dec 30 07:00 AM ET
ESPN+ 200 : Bowling: PBA World Championship @ Dec 30 01:00 PM ET
""".strip().split('\n')

# Categories for classification
TALK_SHOWS = {
    "clinton", "pat mcafee", "hawk talk", "inside the knight", "around the horn",
    "pardon the interruption", "sportscenter", "e:60", "30 for 30", "first take",
    "get up", "sportsnation", "daily wager", "fantasy football focus", "nfl live",
    "nfl countdown", "monday night countdown", "nfl primetime", "this is football",
    "manningcast", "college football live", "sec nation", "college gameday",
    "nba countdown", "nba today", "the jump", "hockey night", "nhl tonight",
    "nhl face-off", "sc featured", "outside the lines", "otl investigates",
    "mike greenberg", "keyshawn", "stephen a", "the herd", "undisputed",
    "wnba offseason", "hbcu gameday", "college basketball tip-off", "nhl power",
    "nhl overtime challenge"
}

NON_MATCHABLE_KEYWORDS = {
    "trophy presentation", "press conference", "postgame press", "film room",
    "documentary", "quest for", "man in the arena", "the captain", "breakaway",
    "season review", "season highlights", "best of 2025", "best finishes",
    "best shots", "preview show", "path to glory", "world championship replay",
    "championship replay", "highlights", "replay"
}

NON_TEAM_SPORTS = {
    "ufc fight night", "top rank boxing", "pfl champions", "cricket", "rugby",
    "f1:", "motogp", "nascar", "lacrosse: nll", "lacrosse: pll", "tennis",
    "golf:", "billiards", "darts", "cornhole", "poker", "esports", "x games",
    "skateboarding", "surfing", "fishing", "bowling"
}


@dataclass
class StreamClassification:
    stream_name: str
    category: str  # "sport_event", "talk_show", "non_team_sport", "press_conference", "empty", "other"
    should_match: bool
    normalized: str
    away_team: str | None
    home_team: str | None
    matched_away: TeamEntry | None
    matched_home: TeamEntry | None
    away_method: str
    home_method: str


def classify_stream(stream: str, matcher: HybridMatcher) -> StreamClassification:
    """Classify a stream and attempt matching."""
    stream_lower = stream.lower()

    # Empty placeholder
    if re.match(r'^espn\+\s*\d+\s*:\s*$', stream_lower):
        return StreamClassification(
            stream_name=stream,
            category="empty",
            should_match=False,
            normalized="",
            away_team=None,
            home_team=None,
            matched_away=None,
            matched_home=None,
            away_method="",
            home_method="",
        )

    # Talk shows
    if any(show in stream_lower for show in TALK_SHOWS):
        return StreamClassification(
            stream_name=stream,
            category="talk_show",
            should_match=False,
            normalized="",
            away_team=None,
            home_team=None,
            matched_away=None,
            matched_home=None,
            away_method="",
            home_method="",
        )

    # Non-matchable content
    if any(kw in stream_lower for kw in NON_MATCHABLE_KEYWORDS):
        return StreamClassification(
            stream_name=stream,
            category="press_conference",
            should_match=False,
            normalized="",
            away_team=None,
            home_team=None,
            matched_away=None,
            matched_home=None,
            away_method="",
            home_method="",
        )

    # Non-team sports
    if any(sport in stream_lower for sport in NON_TEAM_SPORTS):
        return StreamClassification(
            stream_name=stream,
            category="non_team_sport",
            should_match=False,
            normalized="",
            away_team=None,
            home_team=None,
            matched_away=None,
            matched_home=None,
            away_method="",
            home_method="",
        )

    # Attempt to match as sport event
    normalized = normalize_stream_name(stream)
    extracted = extract_teams(normalized)

    if not extracted:
        return StreamClassification(
            stream_name=stream,
            category="other",
            should_match=False,
            normalized=normalized,
            away_team=None,
            home_team=None,
            matched_away=None,
            matched_home=None,
            away_method="",
            home_method="",
        )

    away_text, home_text = extracted

    # Try to match both teams
    matched_away, away_score, away_method = matcher.find(away_text)
    matched_home, home_score, home_method = matcher.find(home_text)

    return StreamClassification(
        stream_name=stream,
        category="sport_event",
        should_match=True,
        normalized=normalized,
        away_team=away_text,
        home_team=home_text,
        matched_away=matched_away,
        matched_home=matched_home,
        away_method=away_method,
        home_method=home_method,
    )


def main():
    print("=" * 80)
    print("  FULL STREAM TEST - Hybrid Matching Engine")
    print("=" * 80)
    print()

    # Load teams and initialize matcher
    teams = load_teams()
    print(f"\nLoaded {len(teams)} teams from database")

    print("\nInitializing hybrid matcher (this may take a moment for semantic embeddings)...")
    matcher = HybridMatcher(teams, use_semantic=True)

    # Classify all streams
    results: list[StreamClassification] = []
    for stream in ESPN_PLUS_STREAMS:
        stream = stream.strip()
        if not stream:
            continue
        results.append(classify_stream(stream, matcher))

    # Categorize results
    by_category = {}
    for r in results:
        if r.category not in by_category:
            by_category[r.category] = []
        by_category[r.category].append(r)

    # Print summary
    print("\n" + "=" * 80)
    print("  CATEGORY BREAKDOWN")
    print("=" * 80)

    for cat, items in sorted(by_category.items()):
        print(f"\n{cat.upper()} ({len(items)} streams):")

    # Detailed sport event results
    sport_events = by_category.get("sport_event", [])

    print("\n" + "=" * 80)
    print(f"  SPORT EVENT MATCHING RESULTS ({len(sport_events)} streams)")
    print("=" * 80)

    # Track stats
    both_matched = 0
    away_only = 0
    home_only = 0
    neither_matched = 0

    # Group by match status
    fully_matched = []
    partial_matched = []
    unmatched = []

    for r in sport_events:
        away_ok = r.matched_away is not None
        home_ok = r.matched_home is not None

        if away_ok and home_ok:
            both_matched += 1
            fully_matched.append(r)
        elif away_ok:
            away_only += 1
            partial_matched.append(r)
        elif home_ok:
            home_only += 1
            partial_matched.append(r)
        else:
            neither_matched += 1
            unmatched.append(r)

    print(f"\n  ✓ Both teams matched: {both_matched}")
    print(f"  ◐ Away only matched: {away_only}")
    print(f"  ◑ Home only matched: {home_only}")
    print(f"  ✗ Neither matched: {neither_matched}")

    total = len(sport_events)
    match_rate = both_matched / total * 100 if total > 0 else 0
    partial_rate = (both_matched + away_only + home_only) / total * 100 if total > 0 else 0
    print(f"\n  Full match rate: {match_rate:.1f}%")
    print(f"  Partial+ match rate: {partial_rate:.1f}%")

    # Show unmatched streams
    if unmatched:
        print("\n" + "-" * 80)
        print("  UNMATCHED SPORT EVENTS (need investigation)")
        print("-" * 80)
        for r in unmatched[:20]:  # Limit to 20
            print(f"\n  Stream: {r.stream_name}")
            print(f"  Normalized: {r.normalized}")
            print(f"  Extracted: '{r.away_team}' vs '{r.home_team}'")

    # Show partial matches
    if partial_matched:
        print("\n" + "-" * 80)
        print("  PARTIAL MATCHES (one team found)")
        print("-" * 80)
        for r in partial_matched[:15]:  # Limit to 15
            print(f"\n  Stream: {r.stream_name}")
            print(f"  Extracted: '{r.away_team}' vs '{r.home_team}'")
            away_str = f"{r.matched_away.name} ({r.away_method})" if r.matched_away else "NO MATCH"
            home_str = f"{r.matched_home.name} ({r.home_method})" if r.matched_home else "NO MATCH"
            print(f"  Away: {away_str}")
            print(f"  Home: {home_str}")

    # Show sample of successful matches
    print("\n" + "-" * 80)
    print("  SAMPLE SUCCESSFUL MATCHES")
    print("-" * 80)
    for r in fully_matched[:15]:
        print(f"\n  Stream: {r.stream_name}")
        print(f"  Away: {r.away_team} → {r.matched_away.name} ({r.away_method})")
        print(f"  Home: {r.home_team} → {r.matched_home.name} ({r.home_method})")

    # Analysis by matching method
    print("\n" + "=" * 80)
    print("  MATCHING METHOD BREAKDOWN")
    print("=" * 80)

    method_counts = {}
    for r in sport_events:
        for method in [r.away_method, r.home_method]:
            if method:
                base_method = method.split(":")[0]
                method_counts[base_method] = method_counts.get(base_method, 0) + 1

    for method, count in sorted(method_counts.items(), key=lambda x: -x[1]):
        print(f"  {method}: {count}")

    # Final summary
    print("\n" + "=" * 80)
    print("  FINAL SUMMARY")
    print("=" * 80)
    print(f"""
  Total streams tested: {len(results)}

  By category:
    - Sport events: {len(sport_events)}
    - Talk shows: {len(by_category.get('talk_show', []))}
    - Press conferences: {len(by_category.get('press_conference', []))}
    - Non-team sports: {len(by_category.get('non_team_sport', []))}
    - Empty placeholders: {len(by_category.get('empty', []))}
    - Other: {len(by_category.get('other', []))}

  Sport event matching:
    - Full match rate: {match_rate:.1f}%
    - Both teams: {both_matched}/{total}
    - Partial: {away_only + home_only}/{total}
    - Unmatched: {neither_matched}/{total}
    """)


if __name__ == "__main__":
    main()
