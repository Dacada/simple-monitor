#!/usr/bin/env python3

import logging
import logging.handlers
import sys

from simpmon import config, paths


class ColorFormatter(logging.Formatter):
    """Custom formatter to add colors for each log level when outputting to a terminal."""

    COLOR_MAP = {
        logging.DEBUG: "\033[94m",
        logging.INFO: "\033[92m",
        logging.WARNING: "\033[93m",
        logging.ERROR: "\033[91m",
        logging.CRITICAL: "\033[95m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = (
            self.COLOR_MAP.get(record.levelno, self.RESET)
            if sys.stdout.isatty()
            else ""
        )
        message = super().format(record)
        return f"{color}{message}{self.RESET}" if color else message


def setup(config: config.Configuration) -> None:
    """Set up logging to both console and a rotating log file."""
    max_bytes = 10 * 1024 * 1024
    backup_count = 5

    log_format = "%(asctime)s - %(levelname)s - %(message)s"
    formatter = ColorFormatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    logger = logging.getLogger()
    logger.setLevel(config.loglevel.to_loglevel())

    log_file_path = paths.log_path()
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file_path, maxBytes=max_bytes, backupCount=backup_count
    )
    file_handler.setFormatter(
        logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.debug(
        f"Logging initialized with rotation. File: {log_file_path}, Max Bytes: {max_bytes}, Backups: {backup_count}"
    )
