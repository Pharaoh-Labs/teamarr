"""Centralized logging configuration for Teamarr.

Provides structured logging with console and file output.
Call setup_logging() once at application startup.

Usage:
    # At startup (app.py)
    from teamarr.utilities.logging import setup_logging
    setup_logging()

    # In any module (standard Python pattern)
    import logging
    logger = logging.getLogger(__name__)
    logger.info("[MODULE] Something happened: %s", value)

Environment variables:
    LOG_LEVEL: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
    LOG_DIR: Directory for log files (default: ./logs or /app/data/logs in Docker)
    LOG_FORMAT: "text" or "json" (default: text)
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from teamarr.config import VERSION

# Track if logging has been configured
_configured = False


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging.

    Useful for log aggregation systems (ELK, Loki, etc.)
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            # Naive-UTC ISO + "Z" — matches the deprecated utcnow() output exactly;
            # inlined (not via tz helper) to keep this low-level formatter dep-free.
            "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def _get_log_dir() -> Path:
    """Determine log directory with Docker awareness."""
    # 1. Explicit env var
    if env_dir := os.getenv("LOG_DIR"):
        return Path(env_dir)

    # 2. Docker environment (persisted volume)
    docker_path = Path("/app/data/logs")
    if docker_path.parent.exists():
        return docker_path

    # 3. Local development - project root/logs
    # Walk up from this file to find project root (where pyproject.toml is)
    current = Path(__file__).parent
    for _ in range(5):  # Max 5 levels up
        if (current / "pyproject.toml").exists():
            return current / "logs"
        current = current.parent

    # 4. Fallback to current directory
    return Path("logs")


def _get_log_level() -> int:
    """Get log level from environment."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def _get_formatter(use_json: bool = False) -> logging.Formatter:
    """Get the appropriate formatter."""
    if use_json:
        return JSONFormatter()

    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def setup_logging(
    log_level: str | None = None,
    log_dir: str | Path | None = None,
    use_json: bool | None = None,
) -> None:
    """Initialize the logging system.

    Call this once at application startup. Safe to call multiple times
    (subsequent calls are no-ops).

    Args:
        log_level: Override LOG_LEVEL env var
        log_dir: Override LOG_DIR env var
        use_json: Override LOG_FORMAT env var (True for JSON output)
    """
    global _configured
    if _configured:
        return

    # Resolve configuration
    level = getattr(logging, (log_level or "").upper(), None) or _get_log_level()
    log_path = Path(log_dir) if log_dir else _get_log_dir()

    if use_json is None:
        use_json = os.getenv("LOG_FORMAT", "text").lower() == "json"

    # Create log directory
    log_path.mkdir(parents=True, exist_ok=True)

    # Get formatter
    formatter = _get_formatter(use_json)

    # === Console Handler ===
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # === Main Log File (rotating) ===
    main_log = log_path / "teamarr.log"
    file_handler = RotatingFileHandler(
        main_log,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # Always log DEBUG to file
    file_handler.setFormatter(formatter)

    # === Error Log File (errors only) ===
    error_log = log_path / "teamarr_errors.log"
    error_handler = RotatingFileHandler(
        error_log,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    # === Configure Root Logger ===
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Handlers filter from here

    # Remove any existing handlers (in case of reload)
    root_logger.handlers.clear()

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)

    # === Quiet Noisy Loggers ===
    noisy_loggers = [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "httpx",
        "httpcore",
        "httpcore.connection",
        "httpcore.http11",
        "hpack",
        "watchfiles",
    ]
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Keep uvicorn.error at INFO for startup messages
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    _configured = True

    # Log startup info

    logger = logging.getLogger("teamarr")
    logger.info("[STARTUP] " + "=" * 60)
    logger.info("[STARTUP] Teamarr %s - Dynamic EPG Generator for Sports Channels", VERSION)
    logger.info("[STARTUP] " + "=" * 60)
    logger.info("[STARTUP] Log level: %s", logging.getLevelName(level))
    logger.info("[STARTUP] Log directory: %s", log_path)
    logger.info("[STARTUP] Log format: %s", "JSON" if use_json else "text")
    logger.info("[STARTUP] " + "=" * 60)
