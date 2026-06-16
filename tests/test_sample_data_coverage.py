"""Coverage guard for template-variable preview sample data.

The template builder's live preview resolves every variable against
``SAMPLE_DATA`` (teamarr/templates/sample_data.py). A registered variable with
no sample renders as its raw ``{name}`` literal in the preview instead of a
realistic value. This test fails if any registered variable lacks a sample, so
new variables can't ship without preview coverage.
"""

from teamarr.templates.sample_data import (
    AVAILABLE_SPORTS,
    SAMPLE_DATA,
    get_all_sample_data,
)
from teamarr.templates.variables import get_registry


def test_every_registered_variable_has_a_sample():
    registry = get_registry()
    sample_keys = set(SAMPLE_DATA.keys())
    missing = sorted(v.name for v in registry.all_variables() if v.name not in sample_keys)
    assert not missing, (
        "Registered variables missing preview sample data (add to SAMPLE_DATA): "
        f"{missing}"
    )


def test_get_all_sample_data_resolves_for_every_sport():
    """Every available preview sport returns a non-empty value for each base var."""
    registry = get_registry()
    names = [v.name for v in registry.all_variables()]
    for sport in AVAILABLE_SPORTS:
        samples = get_all_sample_data(sport)
        for name in names:
            assert name in samples, f"{name!r} unresolved for sport {sport!r}"
