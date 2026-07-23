"""Registry duplicate-name guard + matchup/matchup_combat split (#411).

Combat's ``matchup`` ("Fighter1 vs Fighter2") was silently shadowed by
identity's ``matchup`` ("{away} @ {home}") for months — registry.register()
overwrote on duplicate names and import order picked the winner. The fix
renames combat's variant to ``matchup_combat`` and makes duplicate
registration raise, so the whole class of bug fails loudly at import time.
"""

import pytest

from teamarr.templates.variables import get_registry
from teamarr.templates.variables.registry import Category, SuffixRules


def _noop(ctx, gctx):
    return ""


def test_duplicate_registration_raises():
    registry = get_registry()
    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            name="matchup",  # identity's — guaranteed present
            category=Category.COMBAT,
            suffix_rules=SuffixRules.BASE_ONLY,
            extractor=_noop,
        )


def test_matchup_and_matchup_combat_both_registered():
    registry = get_registry()

    generic = registry.get("matchup")
    assert generic is not None
    assert generic.category is Category.IDENTITY

    combat = registry.get("matchup_combat")
    assert combat is not None
    assert combat.category is Category.COMBAT
    assert combat.suffix_rules is SuffixRules.BASE_ONLY


def test_no_silent_shadowing_possible():
    """Every module-level registration survived import — the guard would have
    raised otherwise. Spot-check the registry is intact and non-trivial."""
    registry = get_registry()
    assert len(registry.all_variables()) >= 250
