"""Unit contracts for deterministic generation-stage orchestration."""

from types import SimpleNamespace

import pytest

from teamarr.consumers.generation_pipeline.runner import GenerationStage, StageRunner


class _Cancellation:
    def __init__(self):
        self.calls = 0

    def checkpoint(self):
        self.calls += 1


def _context():
    return SimpleNamespace(cancellation=_Cancellation())


def test_runner_executes_stages_in_supplied_order():
    context = _context()
    seen: list[str] = []

    StageRunner().run(
        context,
        (
            GenerationStage(lambda _context: seen.append("first")),
            GenerationStage(lambda _context: seen.append("second")),
        ),
    )

    assert seen == ["first", "second"]


def test_runner_checks_cancellation_only_for_marked_stages():
    context = _context()

    StageRunner().run(
        context,
        (
            GenerationStage(lambda _context: None, cancellation_before=True),
            GenerationStage(lambda _context: None),
            GenerationStage(lambda _context: None, cancellation_before=True),
        ),
    )

    assert context.cancellation.calls == 2


def test_runner_propagates_stage_exceptions_unchanged():
    context = _context()
    error = RuntimeError("stage failed")

    def explode(_context):
        raise error

    with pytest.raises(RuntimeError) as raised:
        StageRunner().run(context, (GenerationStage(explode, timing_name="failed"),))

    assert raised.value is error


def test_runner_times_only_successful_timed_stages():
    context = _context()
    timings: list[str] = []

    StageRunner(timings.append).run(
        context,
        (GenerationStage(lambda _context: None, timing_name="successful"),),
    )

    assert timings == ["successful"]


def test_untimed_work_is_billed_to_the_next_time_mark():
    context = _context()
    clock = iter((10.0, 12.345, 15.678))
    timings: dict[str, float] = {}

    class Timer:
        def __init__(self):
            self.last = next(clock)

        def mark(self, phase: str):
            now = next(clock)
            timings[phase] = round(timings.get(phase, 0.0) + now - self.last, 2)
            self.last = now

    StageRunner(Timer().mark).run(
        context,
        (
            GenerationStage(lambda _context: None, timing_name="first"),
            GenerationStage(lambda _context: None),
            GenerationStage(lambda _context: None, timing_name="second"),
        ),
    )

    assert timings == {"first": 2.35, "second": 3.33}
