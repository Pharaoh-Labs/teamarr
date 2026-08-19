"""Backend/frontend template-filter registry parity (#484).

The backend registry (teamarr/templates/filters.py FILTERS) and the frontend
preview registry (frontend/src/pages/template-form/constants.ts
TEMPLATE_FILTERS) must expose the SAME filter names — the preview must accept
exactly what the engine accepts. Settings-registry style: the test parses the
frontend source, so adding a filter in only one place fails here.
"""

import re
from pathlib import Path

from teamarr.templates.filters import FILTERS
from teamarr.templates.resolver import _LEGACY_ALIASES

_REPO = Path(__file__).resolve().parents[2]
_CONSTANTS_TS = _REPO / "frontend" / "src" / "pages" / "template-form" / "constants.ts"
_VALIDATION_TS = _REPO / "frontend" / "src" / "utils" / "templateValidation.ts"


def _frontend_filter_names() -> set[str]:
    src = _CONSTANTS_TS.read_text()
    match = re.search(r"TEMPLATE_FILTERS[^{]*\{(.*?)\n\}", src, re.S)
    assert match, "TEMPLATE_FILTERS registry not found in constants.ts"
    return set(re.findall(r"^\s{2}(\w+):", match.group(1), re.M))


def test_filter_registries_match():
    assert _frontend_filter_names() == set(FILTERS)


def test_legacy_alias_maps_match():
    src = _CONSTANTS_TS.read_text()
    match = re.search(r"LEGACY_FILTER_ALIASES[^=]+=\s*\{(.*?)\n\}", src, re.S)
    assert match, "LEGACY_FILTER_ALIASES not found in constants.ts"
    frontend = dict(
        re.findall(r'^\s{2}(\w+):\s*\["(\w+)",\s*"\w+"\]', match.group(1), re.M)
    )
    backend = {old: base for old, (base, _f) in _LEGACY_ALIASES.items()}
    assert frontend == backend

    # templateValidation.ts carries the same base mapping for warnings.
    vsrc = _VALIDATION_TS.read_text()
    vmatch = re.search(r"LEGACY_ALIAS_BASES[^=]+=\s*\{(.*?)\n\}", vsrc, re.S)
    assert vmatch, "LEGACY_ALIAS_BASES not found in templateValidation.ts"
    validation = dict(re.findall(r'^\s{2}(\w+):\s*"(\w+)"', vmatch.group(1), re.M))
    assert validation == backend


def test_every_alias_filter_exists():
    for _old, (_base, filt) in _LEGACY_ALIASES.items():
        assert filt in FILTERS
