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
_FIFA_OVERRIDES: dict[str, tuple[str, str | None]] = {
    # Home nations (part of GB in ISO 3166, compete separately in FIFA)
    "scotland": ("Scotland", "English"),
    "escocia": ("Scotland", "Spanish"),
    "schottland": ("Scotland", "German"),
    "ecosse": ("Scotland", "French"),  # French "Écosse" → unidecoded
    "scozia": ("Scotland", "Italian"),
    "skocia": ("Scotland", "Albanian"),
    "england": ("England", "English"),
    "inglaterra": ("England", "Spanish"),
    "angleterre": ("England", "French"),
    "inghilterra": ("England", "Italian"),
    "engeland": ("England", "Dutch"),
    "wales": ("Wales", "English"),
    "gales": ("Wales", "Spanish"),
    "pays de galles": ("Wales", "French"),
    "galles": ("Wales", "Italian"),
    "cymru": ("Wales", "Welsh"),
    "kymry": ("Wales", "Welsh"),
    "northern ireland": ("Northern Ireland", "English"),
    "irlanda del norte": ("Northern Ireland", "Spanish"),
    "irlande du nord": ("Northern Ireland", "French"),
    "nordirland": ("Northern Ireland", "German"),
    "irlanda del nord": ("Northern Ireland", "Italian"),
    # ESPN uses "Türkiye" (new official English spelling since 2022)
    "turkey": ("Türkiye", "English"),
    "turquie": ("Türkiye", "French"),
    "turkei": ("Türkiye", "German"),  # German "Türkei" → unidecoded
    "turchia": ("Türkiye", "Italian"),
    "turkije": ("Türkiye", "Dutch"),
    "turquia": ("Türkiye", "Spanish"),  # Spanish "Turquía" → unidecoded
    "turquía": ("Türkiye", "Spanish"),  # keep accented form too (resolved via unidecode at lookup)
    # Kosovo (FIFA member since 2016, not universally recognised)
    "kosovo": ("Kosovo", None),
    "cossovo": ("Kosovo", "Portuguese"),
    # Palestine (FIFA member)
    "palestine": ("Palestine", "English"),
    "palestina": ("Palestine", "Spanish"),
    "palastina": ("Palestine", "German"),  # German "Palästina" → unidecoded
    "palestaine": ("Palestine", "Arabic"),
    # Taiwan (FIFA uses "Chinese Taipei")
    "taiwan": ("Chinese Taipei", "English"),
    "chinese taipei": ("Chinese Taipei", "English"),
    "taipei chinos": ("Chinese Taipei", "Spanish"),
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
        self._lang_map: dict[str, str] = {}
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

    def resolve_language(self, name: str) -> str | None:
        """Resolve a name to the language of its country.

        Args:
            name: Team name as extracted from stream (any language/case/accents)

        Returns:
            English name of the language (e.g. "Spanish"), or None if not recognised.
        """
        return self._lang_map.get(_normalize(name))

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
            for k, (v, lang) in _FIFA_OVERRIDES.items():
                norm_k = _normalize(k)
                self._map[norm_k] = _normalize(v)
                if lang:
                    self._lang_map[norm_k] = lang
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
                    norm_loc = _normalize(localized)
                    self._map[norm_loc] = canonical
                    # Store the English name of the language (e.g., "Spanish")
                    self._lang_map[norm_loc] = locale.english_name

        # FIFA overrides win over the pycountry defaults (e.g. "turkey" → "turkiye")
        for k, (v, lang) in _FIFA_OVERRIDES.items():
            norm_k = _normalize(k)
            self._map[norm_k] = _normalize(v)
            if lang and norm_k not in self._lang_map:
                self._lang_map[norm_k] = lang
