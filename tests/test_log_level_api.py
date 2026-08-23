"""Runtime log-level endpoint (#585).

Runtime-only console verbosity: the endpoint flips the console handler's
minimum in-process; file handlers stay at DEBUG and a restart returns to
the LOG_LEVEL default. Tests drive the route functions directly.
"""

import logging

import pytest
from fastapi import HTTPException

import teamarr.utilities.logging as tlog
from teamarr.api.routes.logs import LogLevelUpdate, get_log_level, update_log_level


@pytest.fixture
def console_handler(monkeypatch):
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    monkeypatch.setattr(tlog, "_console_handler", handler)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    return handler


def test_get_reports_level_default_and_choices(console_handler):
    state = get_log_level()
    assert state["level"] == "INFO"
    assert state["default"] == "INFO"
    assert state["levels"] == ["DEBUG", "INFO", "WARNING", "ERROR"]


def test_put_applies_immediately_to_console_handler(console_handler):
    state = update_log_level(LogLevelUpdate(level="debug"))
    assert state["level"] == "DEBUG"
    assert console_handler.level == logging.DEBUG
    # Startup default is untouched — restart reverts (runtime-only by design)
    assert state["default"] == "INFO"


def test_put_rejects_unknown_and_footgun_levels(console_handler):
    with pytest.raises(HTTPException) as exc:
        update_log_level(LogLevelUpdate(level="VERBOSE"))
    assert exc.value.status_code == 400
    # CRITICAL is deliberately not offered: hiding errors isn't verbosity
    with pytest.raises(HTTPException):
        update_log_level(LogLevelUpdate(level="CRITICAL"))
    assert console_handler.level == logging.INFO


def test_put_before_logging_configured_is_503(monkeypatch):
    monkeypatch.setattr(tlog, "_console_handler", None)
    with pytest.raises(HTTPException) as exc:
        update_log_level(LogLevelUpdate(level="DEBUG"))
    assert exc.value.status_code == 503
