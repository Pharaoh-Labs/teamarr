"""Template variable validation — backend parity with the editor's inline checks.

Mirrors ``frontend/src/utils/templateValidation.ts`` so the same rules apply
whether a template is saved through the editor or programmatically (API, import,
bulk-assign). Both sides share the engine's ``VARIABLE_PATTERN`` (resolver.py) as
the single definition of what counts as a variable, and the registry as the
single source of valid names.

Validation is **advisory**: the resolver keeps unknown variables literal by
design (to surface typos in the output), so warnings never block a save — they
are logged on write and returned by ``POST /templates/validate`` for callers.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from teamarr.templates.conditions import ConditionEvaluator
from teamarr.templates.resolver import VARIABLE_PATTERN
from teamarr.templates.variables import SuffixRules, get_registry

_SUFFIX_RE = re.compile(r"\.(next|last)$")


@dataclass(frozen=True)
class ValidationWarning:
    """One advisory finding about a template field."""

    variable: str
    message: str
    type: str  # "invalid" | "suffix_not_allowed"


def supported_suffixes(rules: SuffixRules) -> list[str]:
    """Suffix labels a variable supports. ``"base"`` means the bare name."""
    if rules == SuffixRules.ALL:
        return ["base", ".next", ".last"]
    if rules == SuffixRules.BASE_ONLY:
        return ["base"]
    if rules == SuffixRules.BASE_NEXT_ONLY:
        return ["base", ".next"]
    if rules == SuffixRules.LAST_ONLY:
        return [".last"]
    return ["base"]


def build_valid_variable_sets() -> tuple[set[str], set[str]]:
    """Return ``(valid_names, base_names)`` from the live registry.

    ``valid_names`` holds every legal full token (base plus only the suffixes
    each variable actually supports); ``base_names`` holds the bare names. Mirror
    of the frontend ``buildValidVariableSet()``.
    """
    valid_names: set[str] = set()
    base_names: set[str] = set()
    for var in get_registry().all_variables():
        base_names.add(var.name)
        for suffix in supported_suffixes(var.suffix_rules):
            valid_names.add(var.name if suffix == "base" else f"{var.name}{suffix}")
    return valid_names, base_names


def extract_variables(template: str) -> list[str]:
    """Variable tokens the engine would resolve, lowercased (matches resolver)."""
    if not template:
        return []
    return [m.group(1).lower() for m in VARIABLE_PATTERN.finditer(template)]


def _has_suffix(name: str) -> bool:
    return bool(_SUFFIX_RE.search(name))


def validate_template(
    template: str,
    valid_names: set[str],
    base_names: set[str],
    is_event_template: bool,
) -> list[ValidationWarning]:
    """Validate one template string. Mirror of frontend ``validateTemplate()``."""
    warnings: list[ValidationWarning] = []
    for name in extract_variables(template):
        # Suffixed variables are not supported in event templates.
        if is_event_template and _has_suffix(name):
            base = _SUFFIX_RE.sub("", name)
            if base in base_names:
                warnings.append(
                    ValidationWarning(
                        variable=name,
                        message=(
                            f"Suffixed variables like {{{name}}} are not supported in "
                            f"event templates. Use {{{base}}} instead."
                        ),
                        type="suffix_not_allowed",
                    )
                )
            else:
                warnings.append(
                    ValidationWarning(
                        variable=name,
                        message=f"Unknown variable: {{{name}}}",
                        type="invalid",
                    )
                )
        elif name not in valid_names:
            base = _SUFFIX_RE.sub("", name)
            if base in base_names and _has_suffix(name):
                warnings.append(
                    ValidationWarning(
                        variable=name,
                        message=f"{{{name}}} is not a valid suffix for this variable",
                        type="invalid",
                    )
                )
            else:
                warnings.append(
                    ValidationWarning(
                        variable=name,
                        message=f"Unknown variable: {{{name}}}",
                        type="invalid",
                    )
                )
    return warnings


def valid_condition_names() -> set[str]:
    """Authoritative set of condition names a conditional description may use.

    The engine resolves a condition via ``getattr(evaluator, f"_eval_{name}")``
    (conditions.py), so the valid set is exactly the evaluator's ``_eval_*``
    methods — introspected here rather than hardcoded, so it can't drift.
    """

    prefix = "_eval_"
    return {
        name[len(prefix):]
        for name in dir(ConditionEvaluator)
        if name.startswith(prefix)
    }


def validate_conditional_descriptions(
    entries: list,
    is_event_template: bool,
) -> dict[str, list[ValidationWarning]]:
    """Validate conditional-description entries (templates + condition names).

    Each entry (dict or model) carries a ``template`` string and an optional
    ``condition``. The template is checked like any field; the condition must be a
    known evaluator (a typo'd condition silently falls through to the default at
    runtime, so it's worth surfacing). ``condition=None`` is the default branch
    and always valid. Keyed ``conditional_descriptions[i]``.
    """
    if not entries:
        return {}

    def _get(entry, key):
        return entry.get(key) if isinstance(entry, dict) else getattr(entry, key, None)

    valid_names, base_names = build_valid_variable_sets()
    conditions = valid_condition_names()
    results: dict[str, list[ValidationWarning]] = {}

    for i, entry in enumerate(entries):
        warnings = validate_template(
            _get(entry, "template") or "", valid_names, base_names, is_event_template
        )
        cond = _get(entry, "condition")
        if cond and cond not in conditions:
            warnings.append(
                ValidationWarning(
                    variable=cond,
                    message=f"Unknown condition: '{cond}'",
                    type="invalid_condition",
                )
            )
        if warnings:
            results[f"conditional_descriptions[{i}]"] = warnings

    return results


def validate_fields(
    fields: dict[str, str | None],
    is_event_template: bool,
) -> dict[str, list[ValidationWarning]]:
    """Validate a map of ``field_name -> template``; return only fields with warnings."""
    valid_names, base_names = build_valid_variable_sets()
    results: dict[str, list[ValidationWarning]] = {}
    for field_name, value in fields.items():
        if not value:
            continue
        found = validate_template(value, valid_names, base_names, is_event_template)
        if found:
            results[field_name] = found
    return results


def warnings_as_dicts(
    results: dict[str, list[ValidationWarning]],
) -> dict[str, list[dict]]:
    """Serialize per-field warnings for API responses."""
    return {field: [asdict(w) for w in ws] for field, ws in results.items()}
