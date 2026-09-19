"""Deterministic internal orchestration for generation stages."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from teamarr.consumers.generation_pipeline.models import GenerationContext


StageFunction = Callable[["GenerationContext"], None]
TimingMarker = Callable[[str], None]


@dataclass(frozen=True)
class GenerationStage:
    """One fixed generation step and its orchestration metadata."""

    run: StageFunction
    cancellation_before: bool = False
    timing_name: str | None = None


class StageRunner:
    """Execute supplied stages once, in order, without recovery behavior."""

    def __init__(self, mark_timing: TimingMarker | None = None) -> None:
        self._mark_timing = mark_timing

    def run(self, context: GenerationContext, stages: Iterable[GenerationStage]) -> None:
        for stage in stages:
            if stage.cancellation_before:
                context.cancellation.checkpoint()
            stage.run(context)
            if stage.timing_name is not None and self._mark_timing is not None:
                self._mark_timing(stage.timing_name)


__all__ = ["GenerationStage", "StageRunner"]
