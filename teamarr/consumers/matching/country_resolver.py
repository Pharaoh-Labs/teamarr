"""International country name resolution for team matching.

Builds a locale-aware mapping of country name variants → English canonical name.
Used to resolve non-English team names (e.g. "Brasil" → "Brazil", "Marruecos" →
"Morocco") without requiring manual alias entries.

Covers national-team sports: FIFA World Cup, Copa America, Euros, Olympics, etc.
Club team names are mostly stable across locales (handled by CITY_TRANSLATIONS and
TEAM_ALIASES instead).
"""

import logging
import re

from unidecode import unidecode

logger = logging.getLogger(__name__)

# Locales to query for country name translations.
# Ordered by broadcast language prevalence in sports streams.
_LOCALES = [
    "es",  # Spanish
    "pt",  # Portuguese
    "fr",  # French
    "de",  # German
    "it",  # Italian
    "nl",  # Dutch
    "ru",  # Russian
    "ar",  # Arabic
    "tr",  # Turkish
    "pl",  # Polish
    "cs",  # Czech
    "ro",  # Romanian
    "hu",  # Hungarian
    "sv",  # Swedish
    "da",  # Danish
    "no",  # Norwegian
    "fi",  # Finnish
    "ja",  # Japanese
    "ko",  # Korean
    "zh",  # Chinese
]

# Hardcoded supplement for FIFA members that are NOT sovereign ISO 3166 states,
# plus ESPN spelling quirks. Keys are unidecode-normalised lowercase.
# Values are the exact team_name string ESPN uses.
_FIFA_OVERRIDES: dict[str, str] = {
    # Home nations (part of GB in ISO 3166, compete separately in FIFA)
    "scotland": "Scotland",
    "escocia": "Scotland",
    "schottland": "Scotland",
    "ecosse": "Scotland",  # French "Écosse" → unidecoded
    "scozia": "Scotland",
    "skocia": "Scotland",
    "england": "England",
    "inglaterra": "England",
    "angleterre": "England",
    "inghilterra": "England",
    "engeland": "England",
    "wales": "Wales",
    "gales": "Wales",
    "pays de galles": "Wales",
    "galles": "Wales",
    "cymru": "Wales",
    "kymry": "Wales",
    "northern ireland": "Northern Ireland",
    "irlanda del norte": "Northern Ireland",
    "irlande du nord": "Northern Ireland",
    "nordirland": "Northern Ireland",
    "irlanda del nord": "Northern Ireland",
    # ESPN uses "Türkiye" (new official English spelling since 2022)
    "turkey": "Türkiye",
    "turquie": "Türkiye",
    "turkei": "Türkiye",  # German "Türkei" → unidecoded
    "turchia": "Türkiye",
    "turkije": "Türkiye",
    "turquia": "Türkiye",  # Spanish "Turquía" → unidecoded
    "turquía": "Türkiye",  # keep accented form too (resolved via unidecode at lookup)
    # Kosovo (FIFA member since 2016, not universally recognised)
    "kosovo": "Kosovo",
    "cossovo": "Kosovo",
    # Palestine (FIFA member)
    "palestine": "Palestine",
    "palestina": "Palestine",
    "palastina": "Palestine",  # German "Palästina" → unidecoded
    "palestaine": "Palestine",
    # Taiwan (FIFA uses "Chinese Taipei")
    "taiwan": "Chinese Taipei",
    "chinese taipei": "Chinese Taipei",
    "taipei chinos": "Chinese Taipei",
    # Common colloquial abbreviations that babel/pycountry never supply (full
    # localized names only). Keys are the _normalize() form, so "EE. UU.",
    # "EE.UU." and "EE UU" all collapse to "ee uu" — one entry covers them.
    "ee uu": "United States",  # Spanish "Estados Unidos" abbreviation
    "eeuu": "United States",  # no-space variant
    "eua": "United States",  # Portuguese "Estados Unidos da América"
    "usa": "United States",
}


def _normalize(name: str) -> str:
    """Normalize a name to the same form used by TeamPattern.pattern.

    Mirrors normalize_text() in fuzzy_match.py: unidecode + lowercase +
    punctuation → space + collapsed whitespace.  Both lookup keys and stored
    canonical values use this so that `canonical in tp.pattern` comparisons
    work correctly.
    """
    normalized = unidecode(name.strip().lower())
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return " ".join(normalized.split())


class CountryNameResolver:
    """Resolves international country name variants to English canonical names.

    Built once at TeamMatcher init; the mapping is static for the lifetime of
    the process (country names change at most every few years).

    Usage:
        resolver = CountryNameResolver()
        resolver.resolve("brasil")     # → "brazil"
        resolver.resolve("marruecos")  # → "morocco"
        resolver.resolve("escocia")    # → "scotland"
        resolver.resolve("Turquía")    # → "turkiye"
    """

    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._build()
        logger.debug(
            "[COUNTRY] Country name resolver built: %d entries across %d locales",
            len(self._map),
            len(_LOCALES),
        )

    def resolve(self, name: str) -> str | None:
        """Resolve a name to its normalized canonical country name.

        Returns the same normalized form as TeamPattern.pattern so that
        `canonical in tp.pattern` checks in _check_alias_match work correctly.

        Args:
            name: Team name as extracted from stream (any language/case/accents)

        Returns:
            Normalized canonical (e.g. "brazil", "morocco"), or None if not recognised.
        """
        return self._map.get(_normalize(name))

    def _build(self) -> None:
        """Build the locale-aware name → canonical mapping."""
        try:
            import pycountry
            from babel import Locale
            from babel.core import UnknownLocaleError
        except ImportError:
            logger.warning(
                "[COUNTRY] pycountry/babel not available — "
                "international country name resolution disabled. "
                "Install pycountry and babel to enable."
            )
            # Still load the FIFA overrides which need no extra deps
            self._map.update({_normalize(k): _normalize(v) for k, v in _FIFA_OVERRIDES.items()})
            return

        # Build locale objects up front (skip bad locale codes silently)
        locales: list[Locale] = []
        for code in _LOCALES:
            try:
                locales.append(Locale.parse(code))
            except UnknownLocaleError:
                pass

        for country in pycountry.countries:
            # English canonical: prefer common_name (e.g. "Bolivia" not the
            # full formal "Bolivia, Plurinational State of")
            canonical_en: str = getattr(country, "common_name", None) or country.name
            # Normalize to the same form as TeamPattern.pattern so that
            # `canonical in tp.pattern` checks work (e.g. "brazil" not "Brazil")
            canonical = _normalize(canonical_en)

            # Index the English names themselves
            self._map[_normalize(country.name)] = canonical
            if hasattr(country, "common_name") and country.common_name != country.name:
                self._map[_normalize(country.common_name)] = canonical
            if hasattr(country, "official_name"):
                self._map[_normalize(country.official_name)] = canonical

            # Index locale-specific names
            for locale in locales:
                localized = locale.territories.get(country.alpha_2)
                if localized:
                    self._map[_normalize(localized)] = canonical

        # FIFA overrides win over the pycountry defaults (e.g. "turkey" → "turkiye")
        self._map.update({_normalize(k): _normalize(v) for k, v in _FIFA_OVERRIDES.items()})
