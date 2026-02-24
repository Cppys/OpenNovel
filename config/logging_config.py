"""Structured logging configuration with file rotation."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: int = logging.INFO,
    log_dir: Optional[str | Path] = None,
    console_enabled: bool = True,
) -> None:
    """Configure application-wide logging with console and file handlers.

    Args:
        level: Logging level (e.g., logging.DEBUG, logging.INFO).
        log_dir: Directory for log files. Defaults to ./data/logs.
        console_enabled: Whether to output to console.
    """
    log_dir = Path(log_dir or "./data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # Console handler
    if console_enabled:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Main file handler (rotating, 10MB, keep 5)
    main_log = log_dir / "opennovel.log"
    file_handler = RotatingFileHandler(
        str(main_log),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Separate LLM call log
    llm_logger = logging.getLogger("tools.agent_sdk_client")
    llm_log = log_dir / "llm_calls.log"
    llm_handler = RotatingFileHandler(
        str(llm_log),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    llm_handler.setLevel(logging.DEBUG)
    llm_handler.setFormatter(formatter)
    llm_logger.addHandler(llm_handler)

    logging.getLogger(__name__).debug("Logging initialized: level=%s, dir=%s", level, log_dir)
