"""Naming heuristics for Gracenote-convention prose (epic tvnk, #329).

Gracenote's definite-article rule (confirmed in captured data, see
plans/gracenote-reference.md): club/franchise teams take "the" ("The
Washington Mystics play the New York Liberty…"); national teams do not
("Germany take on Curaçao…"). Individual-sport competitors (tennis players,
fighters, drivers) never take an article.

Tournaments follow ordinary English: "the US Open" / "the French Open" but
"Wimbledon" / "Roland Garros". Ordinary-noun tournament names (Open,
Championships, Cup, …) take the article; bare proper names do not.

The national-team signal is league-based: Teamarr's Team model carries no
club/national flag, and discovered soccer leagues never touch the schema
table, so a slug heuristic over ESPN league codes is the practical signal
(kept conservative and extensible).
"""

# ESPN league-code fragments that identify NATIONAL-TEAM competitions.
# Substring match against the lowercased league code/slug.
_NATIONAL_LEAGUE_FRAGMENTS = (
    "fifa.",  # World Cup, WWC, qualifiers, friendlies (exception below)
    "uefa.euro",  # Euros incl. qualifiers, U21
    "uefa.nations",
    "uefa.wnations",
    "conmebol.america",  # Copa América (libertadores/sudamericana are clubs)
    "concacaf.gold",
    "concacaf.nations",
    "afc.asian",  # Asian Cup (afc.champions is clubs)
    "caf.nations",  # Africa Cup of Nations (caf.champions is clubs)
    ".friendly",  # friendlies are national-team fixtures
    "worldq",  # World Cup qualifying slugs (fifa.worldq.*)
)

# Club competitions whose slugs would otherwise match a national fragment.
_CLUB_LEAGUE_EXCEPTIONS = ("fifa.cwc",)  # FIFA Club World Cup

# Exact league codes that are national-team competitions in other sports.
_NATIONAL_LEAGUE_CODES = frozenset({"itm"})  # rugby International Test Match

# Sports where the "team" is a person or pairing — never takes an article.
_INDIVIDUAL_SPORTS = frozenset({"tennis", "mma", "boxing", "racing", "golf"})

# Tournament-name nouns that read as ordinary nouns and take "the".
_TOURNAMENT_ARTICLE_WORDS = frozenset(
    {
        "open",
        "championship",
        "championships",
        "cup",
        "masters",
        "classic",
        "invitational",
        "finals",
        "series",
        "games",
        "grand",  # Grand Slam / Grand Prix
        "tour",
    }
)


def is_national_team_league(league: str | None) -> bool:
    """True when the league is a national-team competition (league-slug heuristic)."""
    code = (league or "").lower()
    if not code:
        return False
    if code in _NATIONAL_LEAGUE_CODES:
        return True
    if any(exc in code for exc in _CLUB_LEAGUE_EXCEPTIONS):
        return False
    return any(frag in code for frag in _NATIONAL_LEAGUE_FRAGMENTS)


def team_takes_article(league: str | None, sport: str | None) -> bool:
    """Gracenote article rule: clubs/franchises yes; nationals/individuals no.

    Soccer is the exception (tvnk.9 hardening): club names are proper nouns in
    the match register — "Arsenal face Chelsea", "LA Galaxy host Inter Miami" —
    never "the Arsenal"/"the Manchester United". National sides are already
    bare via the league heuristic, so soccer renders articleless throughout.
    """
    sport_code = (sport or "").lower()
    if sport_code in _INDIVIDUAL_SPORTS:
        return False
    if sport_code == "soccer":
        return False
    return not is_national_team_league(league)


def team_with_article(name: str, league: str | None, sport: str | None) -> str:
    """Team name with the Gracenote-convention article: 'the Detroit Pistons',
    'Netherlands'. Lowercase 'the' — the resolver capitalizes a leading 'the '
    when it opens the rendered text."""
    if not name:
        return ""
    if name.lower().startswith("the "):
        return name  # already carries its article (e.g. "The Ohio State…")
    return f"the {name}" if team_takes_article(league, sport) else name


def tournament_takes_article(name: str) -> bool:
    """'the US Open' / 'the French Open' but 'Wimbledon' / 'Roland Garros'."""
    words = {w.strip(".,'’") for w in (name or "").lower().split()}
    return bool(words & _TOURNAMENT_ARTICLE_WORDS)


def tournament_with_article(name: str) -> str:
    """Tournament name with its natural article ('the US Open', 'Wimbledon')."""
    if not name:
        return ""
    if name.lower().startswith("the "):
        return name
    return f"the {name}" if tournament_takes_article(name) else name


# Sports whose matchup convention is "away at home" (Gracenote episodeTitle:
# "Washington Mystics at New York Liberty"). Everything else — soccer, combat,
# tennis, racing, rugby, cricket — reads "X vs. Y".
_AT_SPORTS = frozenset({"football", "basketball", "baseball", "hockey"})


def matchup_connector(sport: str | None) -> str:
    """Perspective-free matchup connector: 'at' for US team sports, 'vs.' else."""
    return "at" if (sport or "").lower() in _AT_SPORTS else "vs."


def surnames(name: str) -> str:
    """Surname portion of a person or pairing display name.

    "Alex de Minaur" → "de Minaur"; "Camilo Ugo Carabelli" → "Ugo Carabelli";
    doubles/pairings "Hugo Nys / Edouard Roger-Vasselin" → "Nys/Roger-Vasselin".
    """
    parts = []
    for person in (name or "").split("/"):
        tokens = person.strip().split()
        parts.append(" ".join(tokens[1:]) if len(tokens) > 1 else person.strip())
    return "/".join(p for p in parts if p)
