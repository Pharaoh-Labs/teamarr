"""Tests for CountryNameResolver (PR #233).

Locale-aware resolution of international country names to ESPN's English
canonical form, used as the third tier of TeamMatcher._resolve_alias.
"""

import builtins

import pytest

from teamarr.consumers.matching.country_resolver import CountryNameResolver, _normalize


@pytest.fixture(scope="module")
def resolver():
    return CountryNameResolver()


class TestNormalize:
    def test_unidecode_lowercase_and_punctuation(self):
        assert _normalize("Türkiye") == "turkiye"
        assert _normalize("  Bosnia & Herzegovina  ") == "bosnia herzegovina"
        assert _normalize("Côte d'Ivoire") == "cote d ivoire"


class TestLocalizedResolution:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("brasil", "brazil"),        # Portuguese/Spanish
            ("Marruecos", "morocco"),    # Spanish
            ("Suiza", "switzerland"),    # Spanish
            ("Catar", "qatar"),          # Spanish
            ("Inglaterra", "england"),   # Spanish (FIFA override)
        ],
    )
    def test_resolves_localized_names(self, resolver, name, expected):
        assert resolver.resolve(name) == expected

    def test_english_names_resolve_to_themselves(self, resolver):
        assert resolver.resolve("Brazil") == "brazil"
        assert resolver.resolve("Morocco") == "morocco"

    def test_unknown_name_returns_none(self, resolver):
        assert resolver.resolve("generic sports feed") is None
        assert resolver.resolve("") is None


class TestFifaOverrides:
    """Non-sovereign FIFA members and ESPN spelling quirks."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("escocia", "scotland"),      # Spanish
            ("Écosse", "scotland"),       # French (accented)
            ("turkey", "turkiye"),        # ESPN uses "Türkiye"
            ("Turquía", "turkiye"),       # Spanish, accented
            ("kosovo", "kosovo"),
            ("taiwan", "chinese taipei"),  # FIFA name
        ],
    )
    def test_override_wins(self, resolver, name, expected):
        assert resolver.resolve(name) == expected


class TestImportFallback:
    """Without pycountry/babel, only the dependency-free FIFA overrides load."""

    def test_falls_back_to_overrides_when_deps_missing(self, monkeypatch):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name in ("pycountry", "babel", "babel.core"):
                raise ImportError(f"mocked missing {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        resolver = CountryNameResolver()

        # FIFA overrides still work...
        assert resolver.resolve("turkey") == "turkiye"
        assert resolver.resolve("escocia") == "scotland"
        # ...but pycountry-derived locale names do not.
        assert resolver.resolve("Marruecos") is None
