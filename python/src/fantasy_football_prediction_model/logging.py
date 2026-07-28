"""Structured logging for the pipeline.

Console output goes through Rich so long pipeline runs stay readable. A plain
text copy is written to ``artifacts/logs/`` so a GitHub Actions run can be
attached to an issue without scraping the workflow UI.

The pipeline never swallows an error silently. Modules log a warning when they
degrade (an optional dataset is unavailable, a feature group has no coverage)
and raise when they cannot proceed.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.logging import RichHandler

_CONSOLE = Console(stderr=True, soft_wrap=False)
_CONFIGURED = False
_LOG_FILE: Path | None = None

LOGGER_NAME = "ffpm"


def configure_logging(
    level: str = "INFO",
    *,
    log_dir: Path | None = None,
    file_logging: bool = True,
    run_name: str = "pipeline",
) -> logging.Logger:
    """Install the console and (optionally) file handlers.

    Safe to call more than once; later calls only adjust the level.

    Args:
        level: One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
        log_dir: Directory for the run log file.
        file_logging: Whether to also write a plain-text log file.
        run_name: Prefix for the log file name.

    Returns:
        The configured ``ffpm`` root logger.
    """
    global _CONFIGURED, _LOG_FILE

    logger = logging.getLogger(LOGGER_NAME)
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    if _CONFIGURED:
        for handler in logger.handlers:
            handler.setLevel(numeric_level)
        return logger

    logger.handlers.clear()
    logger.propagate = False

    console_handler = RichHandler(
        console=_CONSOLE,
        rich_tracebacks=True,
        show_time=True,
        show_path=False,
        omit_repeated_times=False,
        markup=False,
    )
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(logging.Formatter("%(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(console_handler)

    if file_logging and log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        _LOG_FILE = log_dir / f"{run_name}-{stamp}.log"
        file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
        logger.addHandler(file_handler)

    _CONFIGURED = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child of the ``ffpm`` logger.

    Args:
        name: Usually ``__name__``. The package prefix is trimmed for brevity.
    """
    if not name:
        return logging.getLogger(LOGGER_NAME)
    short = name.removeprefix("fantasy_football_prediction_model.")
    return logging.getLogger(f"{LOGGER_NAME}.{short}")


def current_log_file() -> Path | None:
    """Path of the active run log file, if file logging is enabled."""
    return _LOG_FILE


def log_section(logger: logging.Logger, title: str, **details: Any) -> None:
    """Log a visually distinct pipeline stage header."""
    logger.info("")
    logger.info("=" * 78)
    logger.info(title)
    if details:
        width = max(len(key) for key in details)
        for key, value in details.items():
            logger.info("  %-*s : %s", width, key, value)
    logger.info("=" * 78)


class PipelineError(RuntimeError):
    """A pipeline stage could not complete.

    Carries a remediation hint so the CLI can print something actionable
    rather than a bare traceback.
    """

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint

    def render(self) -> str:
        if self.hint:
            return f"{self}\n\nHow to fix this:\n  {self.hint}"
        return str(self)


class DataUnavailableError(PipelineError):
    """A required dataset could not be fetched and is not cached."""


class DataQualityError(PipelineError):
    """Ingested or generated data failed a validation rule."""


class LeakageError(PipelineError):
    """A feature set or fold would leak information from the target season."""


def fail(message: str, *, hint: str | None = None, exit_code: int = 1) -> None:
    """Print an actionable error and exit. Used only from CLI entry points."""
    _CONSOLE.print(f"\n[bold red]Error:[/bold red] {message}")
    if hint:
        _CONSOLE.print(f"\n[bold]How to fix this:[/bold]\n  {hint}")
    sys.exit(exit_code)
