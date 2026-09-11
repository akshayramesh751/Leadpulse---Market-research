"""Centralized logging configuration with rotating file handler and Rich console handler."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from rich.logging import RichHandler
from config import settings


def setup_logger(name: str = "lead_agent") -> logging.Logger:
    """Configures and returns a logger instance with file and console handlers."""
    logger = logging.getLogger(name)

    # Prevent duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    numeric_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    # Ensure log directory exists
    log_file_path = settings.log_file
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Rotating File Handler (10MB per file, keeps 5 backups)
    file_formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # 2. Rich Console Handler
    console_handler = RichHandler(
        rich_tracebacks=True,
        show_time=True,
        show_level=True,
        show_path=False,
    )
    console_handler.setLevel(numeric_level)
    logger.addHandler(console_handler)

    return logger


# Default application logger
logger = setup_logger()
