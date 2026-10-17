"""Thread-scoped DEBUG suppression for the discovery scan (#1081)."""

import logging
import threading

from teamarr.utilities.logging import _QuietDebugFilter, quiet_debug


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append((record.levelno, record.getMessage()))


def _logger(name):
    log = logging.getLogger(name)
    log.setLevel(logging.DEBUG)
    log.propagate = False
    handler = _Collect()
    handler.addFilter(_QuietDebugFilter())
    log.handlers = [handler]
    return log, handler


def test_quiet_debug_drops_only_this_threads_debug():
    log, handler = _logger("test.quiet.a")
    log.debug("before")
    with quiet_debug():
        log.debug("dropped")
        log.info("kept info")
        log.warning("kept warning")
    log.debug("after")
    assert [m for _, m in handler.records] == ["before", "kept info", "kept warning", "after"]


def test_another_thread_keeps_its_debug_while_one_is_quiet():
    log, handler = _logger("test.quiet.b")
    gate, done = threading.Event(), threading.Event()

    def other():
        gate.wait(5)
        log.debug("other thread debug")
        done.set()

    worker = threading.Thread(target=other)
    worker.start()
    with quiet_debug():
        log.debug("quiet thread debug")
        gate.set()
        done.wait(5)
    worker.join(5)
    assert [m for _, m in handler.records] == ["other thread debug"]


def test_quiet_debug_is_released_on_error():
    from teamarr.utilities import logging as tlog

    try:
        with quiet_debug():
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert threading.get_ident() not in tlog._quiet_threads
