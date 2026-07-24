"""ESPN editorial-field drift canary (#375 gap 2, #506).

The editorial features (game recap, event notes, soccer match note, neutral
site) are empty-safe by design: if ESPN renames ``headlines[]``, ``notes[]``,
``altGameNote``, or ``neutralSite``, the features silently go dark instead of
erroring. This canary makes that drift loud.

It counts *key presence* in scoreboard competition payloads — a rename makes
the key vanish from every payload, whereas an empty value is normal. Each
field only counts events where the key is structurally expected (eligibility),
so quiet-but-healthy data can't false-positive:

- ``neutralSite`` / ``notes``: every team-sport scoreboard competition.
- ``headlines``: final events only (that's where Recap objects attach).
- ``altGameNote``: soccer events only (the field is soccer editorial copy).

Once a field's eligible sample crosses its threshold with ZERO presences, one
warning per process is logged. Counters are per provider instance and reset
with the process — a long-running server crosses the thresholds within days
of normal generation traffic.
"""

import logging

logger = logging.getLogger(__name__)


class EditorialDriftCanary:
    """Counts editorial-key presence across parsed scoreboard events."""

    # (field, eligibility) — eligibility keys into the flags passed to record()
    FIELDS: tuple[tuple[str, str], ...] = (
        ("neutralSite", "all"),
        ("notes", "all"),
        ("headlines", "final"),
        ("altGameNote", "soccer"),
    )

    # Eligible-event sample required before a zero-presence field warns.
    # Sparse populations (finals, soccer) get a smaller-but-still-meaningful
    # sample; structural keys expect presence on essentially every event.
    THRESHOLDS: dict[str, int] = {
        "neutralSite": 500,
        "notes": 500,
        "headlines": 200,
        "altGameNote": 300,
    }

    def __init__(self) -> None:
        self._eligible: dict[str, int] = {f: 0 for f, _ in self.FIELDS}
        self._present: dict[str, int] = {f: 0 for f, _ in self.FIELDS}
        self._warned: set[str] = set()

    def record(self, competition: dict, *, sport: str, is_final: bool) -> None:
        """Record one parsed scoreboard competition payload."""
        flags = {"all": True, "final": is_final, "soccer": sport == "soccer"}
        for field, eligibility in self.FIELDS:
            if not flags[eligibility]:
                continue
            self._eligible[field] += 1
            if field in competition:
                self._present[field] += 1
            elif (
                field not in self._warned
                and self._eligible[field] >= self.THRESHOLDS[field]
                and self._present[field] == 0
            ):
                self._warned.add(field)
                logger.warning(
                    "[ESPN] Editorial drift canary: '%s' absent from all %d "
                    "eligible scoreboard events — ESPN may have renamed the "
                    "field; the dependent editorial features (recap/notes/"
                    "neutral-site copy) are silently dark",
                    field,
                    self._eligible[field],
                )
